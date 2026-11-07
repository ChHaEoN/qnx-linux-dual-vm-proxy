#!/usr/bin/env python3
"""probe.py -- the twin connector's two opt-in probes (sdv/connector/probes; SDV Phase 4 WP0).

Run in WSL, from the repo root, where Docker Engine runs. Each probe is refused
unless SDV_CONNECTOR_PROBE=1, writes only under --out (refused inside the repo), uses containers and a network of
its own names only (never the stack's), and removes them whatever happens. No AWS call, no credential, no host
port, no privileged container.

    SDV_CONNECTOR_PROBE=1 python3 sdv/connector/probes/probe.py databroker --out DIR [--gen DIR]
    SDV_CONNECTOR_PROBE=1 python3 sdv/connector/probes/probe.py broker --out DIR

databroker (probe 1)
  A throwaway databroker 0.7.1 (the stack's pinned image, by index digest; `--network none`, a read-only root,
  the generated catalogue staged read-only), as the stack's own probes run one. subscribe_probe.py then runs in
  the recorder image (by image ID; it has kuksa-client 0.6.0 and grpc), joined to that namespace: one kuksa.val.v2
  Subscribe on an actuator's current value (the hazard light), an attribute (Wheelbase) and the eight AppState
  leaves, five of them strings. It records whether the first response carries each current value and whether a
  later write arrives; GetValue is read for every path (the fallback for Wheelbase). The paths, their types and
  the values written come from the generated catalogue (probe_plan); none lies under the branch the twin excludes.
  Nothing is pulled or built: an image that is not there is refused (run sdv/stack/stack.py prepare first).
  Writes DIR/databroker-probe.json, DIR/databroker.log and the staged inputs under DIR/in.

broker (probe 2)
  eclipse-mosquitto 2.0.22, the test broker of images.json's test_only entry, pulled only when absent and only as
  repo@index_digest, run as its own unprivileged user on a Docker network created --internal, with no published
  port and the image's stock configuration (a listener on the container's loopback only). mosquitto_sub and
  mosquitto_pub run inside that container (docker exec) and exchange one QoS 1 message on: a neutral topic (the
  control), each exact topic of AWS_TOPICS (a Basic Ingest topic and a named-shadow update topic, with the
  placeholders example_rule and example-thing), and two wildcard subscriptions on the first of them (`#`, which
  MQTT says must not match a topic beginning with $, and `$aws/#`). `carries_exact_aws_topics` is true when the
  control and both exact topics were delivered: if not, the connector's broker tests (WP3) use a neutral topic
  and the topic strings stay with WP2's unit tests. Writes DIR/broker-probe.json and DIR/mosquitto.log. The
  container is removed with its two anonymous volumes (the image declares its data and log directories as volumes).

DESIGN VALUES (of these probes, none a claim): 30 s for a container to log that it is ready, 15 s for a
subscriber to be subscribed, 10 s for a message to arrive (3 s where none is expected).

Does not demonstrate: anything about the cloud service these topics belong to (no shadow service answers, no
rule runs, no policy authorises, and a Basic Ingest topic can be subscribed to here); what Mosquitto does with
an unauthorised publish (no ACL is loaded); that the connector exists or connects; any timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STACK_DIR = REPO / "sdv" / "stack"
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
IMAGES_FILE = STACK_DIR / "images.json"
SUBSCRIBE_PROBE = HERE / "subscribe_probe.py"

sys.dont_write_bytecode = True
for _d in (str(STACK_DIR), str(APP_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import attribution as attr  # noqa: E402
import hazard  # noqa: E402

OPT_IN_ENV = "SDV_CONNECTOR_PROBE"
LABEL = "sdv.connector.probe"
DATABROKER_NAME = "sdv-p4-probe-databroker"
BROKER_NAME = "sdv-p4-probe-mosquitto"
NETWORK = "sdv-p4-probe-net"
TEST_BROKER = "eclipse-mosquitto"
BROKER_HOST, BROKER_PORT = "127.0.0.1", 55555          # the throwaway databroker, in its own namespace
MQTT_PORT = 1883                                        # the test broker's loopback listener, inside its container
MOSQUITTO_USER = "1883:1883"                            # the image's own unprivileged user: nothing to drop, no capability
COMMON = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m",
          "--memory", "512m", "--memory-swap", "512m"]
SHA = re.compile(r"sha256:[0-9a-f]{64}")

# Placeholders, never a real name: a thing and a rule as the device policy's topics will spell them.
THING, RULE = "example-thing", "example_rule"
AWS_TOPICS = ("$aws/rules/%s/%s" % (RULE, THING), "$aws/things/%s/shadow/name/vss/update" % THING)
NEUTRAL_TOPIC = "sdv/probe/%s" % THING
PAYLOAD = '{"v":0,"probe":"wp0"}'

READY_S = 30.0
SUBSCRIBED_S = 15.0
ARRIVE_S = 10
NO_ARRIVAL_S = 3

# A value of each datatype to write, and a second one for a leaf whose catalogue default is the first.
_WRITES: Dict[str, Tuple[Any, Any]] = {"boolean": (True, False), "uint8": (201, 202), "uint16": (2701, 2702), "uint32": (123456, 123457)}


class ProbeError(RuntimeError):
    pass


# --- small helpers ------------------------------------------------------------------------------

def docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise ProbeError("docker %s failed (%d): %s" % (" ".join(args[:3]), p.returncode, (p.stderr or p.stdout).strip()[-800:]))
    return p


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_images() -> Dict[str, Any]:
    return json.loads(IMAGES_FILE.read_text(encoding="utf-8"))


def outside_repo(out_dir: Path) -> Path:
    """The output directory, resolved; refused inside the repo (a probe's record is a result and stays out of it)."""
    out = out_dir.expanduser().resolve()
    if out == REPO.resolve() or str(out).startswith(str(REPO.resolve()) + os.sep):
        raise ProbeError("the output directory %s is inside the repo" % out)
    return out


def container_logs(name: str) -> str:
    p = docker("logs", name, check=False, timeout=60)
    return (p.stdout or "") + (p.stderr or "")


def wait_log(name: str, pattern: str, timeout: float) -> str:
    rx = re.compile(pattern)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = docker("inspect", "-f", "{{.State.Running}}", name, check=False)
        if st.stdout.strip() != "true":
            raise ProbeError("%s stopped while waiting for /%s/:\n%s" % (name, pattern, container_logs(name)[-1500:]))
        m = rx.search(container_logs(name))
        if m:
            return m.group(0)
        time.sleep(0.3)
    raise ProbeError("timed out after %.0f s waiting for %s to log /%s/:\n%s" % (timeout, name, pattern, container_logs(name)[-1500:]))


# --- probe 1: the databroker --------------------------------------------------------------------

def probe_paths() -> Tuple[str, ...]:
    """An actuator's current value, an attribute, and the eight AppState leaves (five are strings)."""
    return (hazard.HAZARD, attr.WHEELBASE) + tuple(hazard.LEAF_PATHS)


def probe_plan(leaves: Dict[str, Dict[str, Any]], paths: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """For each path, from the generated catalogue's leaves: its type, datatype and default, and a value of that
    datatype to write that is not the default (inside `allowed` where the node lists one)."""
    out: List[Dict[str, Any]] = []
    for path in (probe_paths() if paths is None else paths):
        if path.startswith(attr.MONITOR_PREFIX):
            raise ProbeError("%s lies under the branch the twin excludes: it is never probed" % path)
        node = leaves.get(path)
        if node is None or node.get("type") == "branch":
            raise ProbeError("%s is not a leaf of the generated catalogue" % path)
        dt, default = node["datatype"], node.get("default")
        if dt == "string":
            allowed = list(node.get("allowed") or [])
            candidates: List[Any] = allowed[1:] + allowed[:1] if allowed else ["probe-" + path.rsplit(".", 1)[1], "probe-2"]
        elif dt in _WRITES:
            candidates = list(_WRITES[dt])
        else:
            raise ProbeError("no write value for datatype %r (%s)" % (dt, path))
        out.append({"path": path, "type": node["type"], "datatype": dt, "default": default,
                    "write": next(c for c in candidates if c != default)})
    return out


def databroker_probe(gen: Path, out_dir: Path) -> Dict[str, Any]:
    out_dir = outside_repo(out_dir)
    images = load_images()
    u = images["upstream"][attr.DATABROKER]
    ref = "%s@%s" % (u["repo"], u["index_digest"])
    if docker("image", "inspect", ref, check=False).returncode != 0:
        raise ProbeError("%s is not in the image store: run sdv/stack/stack.py prepare first (this probe pulls nothing)" % ref)
    tag = images["local"][attr.RECORDER]["tag"]
    p = docker("image", "inspect", "-f", "{{.Id}}", tag, check=False)
    client = p.stdout.strip()
    if p.returncode != 0 or not SHA.fullmatch(client):
        raise ProbeError("the recorder image %s is not built: run sdv/stack/stack.py prepare first (this probe builds nothing)" % tag)
    catalogue = gen / "vss-databroker.json"
    plan = probe_plan(attr.leaf_nodes(json.loads(catalogue.read_text(encoding="utf-8"))))
    stage = out_dir / "in"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(catalogue, stage / "vss-databroker.json")
    shutil.copyfile(SUBSCRIBE_PROBE, stage / "subscribe_probe.py")
    (stage / "plan.json").write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    docker("rm", "-f", DATABROKER_NAME, check=False)          # a stale one of this probe's own, by its own name
    try:
        docker("run", "-d", "--name", DATABROKER_NAME, "--label", LABEL + "=databroker", *COMMON, "--network", "none", "--read-only",
               "-e", "KUKSA_DATABROKER_ADDR=" + BROKER_HOST, "-v", "%s:/in:ro" % stage, ref,
               "--vss", "/in/vss-databroker.json", "--address", BROKER_HOST, "--port", str(BROKER_PORT), "--insecure")
        wait_log(DATABROKER_NAME, r"Listening on 127\.0\.0\.1:%d" % BROKER_PORT, READY_S)
        p = docker("run", "--rm", "--network", "container:" + DATABROKER_NAME, *COMMON, "--read-only", "-v", "%s:/in:ro" % stage,
                   "--entrypoint", "python", client, "/in/subscribe_probe.py", "%s:%d" % (BROKER_HOST, BROKER_PORT), "/in/plan.json",
                   check=False, timeout=300)
        if p.returncode != 0:
            raise ProbeError("subscribe_probe.py failed (%d): %s" % (p.returncode, (p.stderr or p.stdout)[-1500:]))
        result = json.loads(p.stdout)
    finally:
        try:          # the log first, while the container is there; but a read that raises must not keep the container
            (out_dir / "databroker.log").write_text(container_logs(DATABROKER_NAME), encoding="utf-8")
        finally:
            docker("rm", "-f", DATABROKER_NAME, check=False)
    rec = {"probe": "databroker", "databroker": ref, "databroker_version": u["version"], "client_image": client, "client_tag": tag,
           "catalogue_sha256": sha256_file(stage / "vss-databroker.json"), "plan": plan,
           "subscribe_probe_sha256": sha256_file(SUBSCRIBE_PROBE), "result": result}
    write_json(out_dir / "databroker-probe.json", rec)
    return rec


# --- probe 2: the test broker -------------------------------------------------------------------

def broker_ref(images: Dict[str, Any]) -> str:
    """The test broker as repo@index_digest, from images.json's test_only entry and nowhere else."""
    pin = (images.get("test_only") or {}).get(TEST_BROKER)
    if not isinstance(pin, dict):
        raise ProbeError("images.json has no test_only pin for %s" % TEST_BROKER)
    if not SHA.fullmatch(str(pin.get("index_digest"))):
        raise ProbeError("images.json: %s's index_digest is not sha256:<64 hex>: %r" % (TEST_BROKER, pin.get("index_digest")))
    return "%s@%s" % (pin["repo"], pin["index_digest"])


def familiar(ref: str) -> str:
    """Docker's short form of a Docker Hub reference, which is how `docker image inspect` lists a repo digest
    (docker.io/library/name@digest is listed as name@digest); any other registry's reference is unchanged."""
    for prefix in ("docker.io/library/", "docker.io/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def exchange_plan() -> List[Tuple[str, str, int]]:
    """(subscription, publish topic, seconds to wait): the control, each exact topic, then two wildcards."""
    first = AWS_TOPICS[0]
    return ([(NEUTRAL_TOPIC, NEUTRAL_TOPIC, ARRIVE_S)] + [(t, t, ARRIVE_S) for t in AWS_TOPICS]
            + [("#", first, NO_ARRIVAL_S), ("$aws/#", first, ARRIVE_S)])


def exchange(sub_topic: str, pub_topic: str, payload: str, wait_s: float) -> Dict[str, Any]:
    """One subscriber and one QoS 1 publish, both mosquitto's own clients inside the broker's container. The
    subscriber runs with a pty so that its lines arrive as it prints them; the publish goes out only once the
    subscriber has printed its SUBACK."""
    client = ["docker", "exec", "-t", BROKER_NAME]
    sub = subprocess.Popen(client + ["mosquitto_sub", "-h", "127.0.0.1", "-p", str(MQTT_PORT), "-i", "sdv-probe-sub", "-q", "1",
                                     "-t", sub_topic, "-C", "1", "-W", str(int(wait_s)), "-v", "-d"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: List[str] = []
    subscribed = threading.Event()

    def drain() -> None:
        assert sub.stdout is not None
        for line in sub.stdout:
            lines.append(line.rstrip("\r\n"))
            if lines[-1].startswith("Subscribed (mid:"):
                subscribed.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    out: Dict[str, Any] = {"sub_topic": sub_topic, "pub_topic": pub_topic, "subscribed": False, "granted_qos": None,
                           "pub_rc": None, "received": False, "sub_rc": None}
    try:
        if subscribed.wait(SUBSCRIBED_S):
            m = re.search(r"^Subscribed \(mid: \d+\): (\d+)", "\n".join(lines), re.M)
            out["granted_qos"] = int(m.group(1)) if m else None
            out["subscribed"] = out["granted_qos"] in (0, 1, 2)
            pub = subprocess.run(["docker", "exec", BROKER_NAME, "mosquitto_pub", "-h", "127.0.0.1", "-p", str(MQTT_PORT), "-i", "sdv-probe-pub",
                                  "-q", "1", "-t", pub_topic, "-m", payload, "-d"], capture_output=True, text=True, timeout=60)
            out["pub_rc"] = pub.returncode
            out["pub_output"] = (pub.stdout + pub.stderr).splitlines()
            try:
                out["sub_rc"] = sub.wait(timeout=wait_s + 15)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if sub.poll() is None:
            sub.kill()
            sub.wait(timeout=30)
        reader.join(10)
    out["received"] = ("%s %s" % (pub_topic, payload)) in lines
    out["sub_output"] = lines
    return out


def broker_verdict(cases: Sequence[Dict[str, Any]]) -> Dict[str, bool]:
    """control_ok: the neutral topic was delivered (else the rig shows nothing). carries_exact_aws_topics: that,
    and each topic of AWS_TOPICS was delivered to a subscriber of exactly that topic."""
    def delivered(sub: str, pub: str) -> bool:
        return any(c["sub_topic"] == sub and c["pub_topic"] == pub and c.get("subscribed") and c.get("received") for c in cases)

    control = delivered(NEUTRAL_TOPIC, NEUTRAL_TOPIC)
    return {"control_ok": control, "carries_exact_aws_topics": control and all(delivered(t, t) for t in AWS_TOPICS)}


def broker_probe(out_dir: Path) -> Dict[str, Any]:
    out_dir = outside_repo(out_dir)
    images = load_images()
    ref = broker_ref(images)
    pin = images["test_only"][TEST_BROKER]
    pulled = False
    if docker("image", "inspect", ref, check=False).returncode != 0:
        docker("pull", "-q", ref, timeout=900)          # by the pinned index digest, never by tag
        pulled = True
    p = docker("image", "inspect", ref, check=False)
    if p.returncode != 0:
        raise ProbeError("%s is not in the image store after the pull" % ref)
    info = json.loads(p.stdout)[0]
    if not {ref, familiar(ref)} & set(info.get("RepoDigests") or []):
        raise ProbeError("%s is not among the image's repo digests %r" % (ref, info.get("RepoDigests")))
    out_dir.mkdir(parents=True, exist_ok=True)
    docker("rm", "-f", "-v", BROKER_NAME, check=False)    # stale ones of this probe's own, by its own names; -v: see below
    docker("network", "rm", NETWORK, check=False)
    cases: List[Dict[str, Any]] = []
    try:
        docker("network", "create", "--internal", "--label", LABEL + "=broker", NETWORK)
        docker("run", "-d", "--name", BROKER_NAME, "--label", LABEL + "=broker", *COMMON, "--read-only", "--user", MOSQUITTO_USER,
               "--network", NETWORK, ref)
        running = wait_log(BROKER_NAME, r"mosquitto version \S+ running", READY_S)
        internal = docker("network", "inspect", "-f", "{{.Internal}}", NETWORK).stdout.strip() == "true"
        ports = json.loads(docker("inspect", "-f", "{{json .NetworkSettings.Ports}}", BROKER_NAME).stdout or "null") or {}
        published = sorted(k for k, v in ports.items() if v) + docker("port", BROKER_NAME, check=False).stdout.split()
        for sub_topic, pub_topic, wait_s in exchange_plan():
            cases.append(exchange(sub_topic, pub_topic, PAYLOAD, wait_s))
    finally:
        try:          # the log first, while the container is there; but neither a read nor a removal that raises (a
            #           docker command timing out) may keep the container or the network
            log = container_logs(BROKER_NAME)
            (out_dir / "mosquitto.log").write_text(log, encoding="utf-8")
        finally:
            try:          # -v: the image declares two volumes, so the container has two anonymous ones, which a
                #           removal that does not name them would leave in the store
                docker("rm", "-f", "-v", BROKER_NAME, check=False)
            finally:
                docker("network", "rm", NETWORK, check=False)
    first = AWS_TOPICS[0]
    wild = {c["sub_topic"]: bool(c.get("received")) for c in cases if c["sub_topic"] != c["pub_topic"] and c["pub_topic"] == first}
    rec: Dict[str, Any] = {"probe": "broker", "image": ref, "image_id": info.get("Id"), "architecture": info.get("Architecture"),
                           "pulled": pulled, "version_pinned": pin["version"], "version_running": running.split()[2],
                           "local_only_mode": "local only mode" in log, "network": NETWORK, "network_internal": internal,
                           "published_ports": published, "user": MOSQUITTO_USER, "payload": PAYLOAD, "cases": cases,
                           "wildcard_delivers_first_aws_topic": wild}
    rec.update(broker_verdict(cases))
    write_json(out_dir / "broker-probe.json", rec)
    return rec


# --- CLI ----------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("databroker", "broker"):
        s = sub.add_parser(cmd)
        s.add_argument("--out", required=True, help="where the record goes; outside the repo")
        if cmd == "databroker":
            s.add_argument("--gen", default=None, help="the generated outputs' directory (default: SDV_GEN or sdv-out/gen)")
    a = ap.parse_args(argv)
    if os.environ.get(OPT_IN_ENV) != "1":
        print("probe: refused: %s=1 opts in (Docker in WSL; `broker` may pull one pinned test image)" % OPT_IN_ENV, file=sys.stderr)
        return 2
    try:
        out = outside_repo(Path(a.out))
        if a.cmd == "databroker":
            gen = Path(a.gen or os.environ.get("SDV_GEN") or str(REPO / "sdv-out" / "gen")).expanduser()
            rec = databroker_probe(gen, out)
            shown: Dict[str, Any] = {"server": rec["result"].get("server"), "summary": rec["result"].get("summary")}
        else:
            rec = broker_probe(out)
            shown = {k: rec[k] for k in ("image", "version_running", "local_only_mode", "network_internal", "published_ports",
                                         "control_ok", "carries_exact_aws_topics", "wildcard_delivers_first_aws_topic")}
    except (ProbeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("probe: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    print(json.dumps(shown, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
