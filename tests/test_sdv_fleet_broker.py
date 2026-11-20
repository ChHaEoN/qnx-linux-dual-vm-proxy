"""The fleet runner's three cars at a local broker (sdv/stack/fleet.py run, three stack.py replays with their connectors):
video 3's fleet, package P1, the local stand-in (the design's option C), the PC rehearsal's tool and not a shot.

OPT-IN: skipped unless SDV_FLEET_BROKER=1, on POSIX with docker (WSL Ubuntu-24.04's Docker Engine). Once opted in, a missing
input fails: the recordings (each must pass fleet.py check), the sim venv, the recorder's cached source, sudo -n (each car's
stack makes its vcanf<k>), the connector image images.json pins and the pinned test broker, by repo@index_digest and never
pulled (one missing from the store fails, naming it). Not a file of tests/twin_gate.py's TWIN_TEST_FILES (an opt-in file
there would fail every CI run).

NO CLOUD, AND NOTHING PULLED: the far end is tests/test_sdv_connector_broker.py's (its internal network, its throwaway CA,
its broker's settings and log, its observer, by import; that file is unchanged), with an ACL that holds each car's
certificate to its own thing's topics (sdv/connector/topics.py's). Each car has a placeholder thing (example-thing-a, -b,
-c), the rule example_rule, a key and a certificate this test makes and signs with that CA, and a device directory under
pytest's temporary directory whose endpoint is the broker's RFC 5737 address on the internal network. The cars' stacks run
with docker behind a shim on PATH that turns every `docker pull` into `docker image inspect` (an image not in the store
fails the run; nothing is pulled) and logs every docker call; their builds are the stack's own, from its cache. The state
directory is the test's own, so no stamp of this host's is read or written.

RECORDINGS: SDV_FLEET_RECORDING_A, _B and _C, by default video 3's drives under ~/sdv-recordings, as sdv/carla/encode010.py
encodes them from their takes: 20261112-carla010-7d1b (R-att's), 20261111-carla010-2d1 and 20261111-carla010-6d1. Each must
pass fleet.py check, its bound on its player must be one the stack takes, and its log must end at least fleet.py's
PLAYER_MARGIN_S inside that bound (fleet.py's player_bound_s of the recording, stack.py's player_bound_s for its log;
fleet.py run refuses such a car too): a longer one would end that car's replay at the bound, or never start it.
SDV_FLEET_KEEP=<an existing absolute directory outside the repo>: the fleet's run directory and the observer's capture (JSON
lines of topic, payload and receive wall ms, beside the run directory, never in it) are kept there for the PC rehearsal
(P3); unset, both stay under pytest's temporary directory.

What is held:
  * fleet: ok, and fleet.json's ok, every car's gates and its witness log;
  * each car's telemetry arrives on its own thing's topic only (the broker's log: each client published on its own topics
    and no other, none was denied), and every cell of a CAN-fed path is a value its own witness served; each car has at
    least one cell that no other car's witness holds; the check itself is shown not blind: a cell of car B planted under
    car A's topic is caught;
  * every telemetry and vss document holds allowlisted keys only, and no payload names the Monitor branch;
  * no placeholder name, the endpoint, a device directory's path or name, or a name of a file in one appears under the
    run directory or the state directory;
  * nothing of the fleet's is left once the fleet has ended: the test's sweep finds no container labelled
    sdv.stack.instance to remove, and none labelled sdv.stack.run is there. The vcanf<k> the cars' stacks made are removed
    by the test (the stack never removes its interface), which holds nothing about them.

DESIGN VALUES (waits that bound the test, none a claim): RUN_TIMEOUT_S for the fleet's process.

Does not demonstrate: the cloud in any respect (the broker's ACL is not the cloud's policy, a certificate here can connect
under another client id, no shadow service answers, no rule runs); any timing, or that the feeds start at one instant; the
PC's capacity; that a build of the stack's images needs no download (they come from Docker's cache; the shim's log names
every docker call).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pytest

import test_sdv_connector_broker as CB
from test_sdv_connector_broker import image, network, parts, pki  # noqa: F401 -- the broker tests' fixtures, used as they are

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"
FLEET_PY = STACK_DIR / "fleet.py"
_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import fleet  # noqa: E402 -- fleet.py's player_bound_s: the stack's bound on a recording's player

sys.dont_write_bytecode = _saved
LABELS = ("A", "B", "C")
THINGS = {"A": "example-thing-a", "B": "example-thing-b", "C": "example-thing-c"}          # placeholders
RULE = CB.RULE
NAME = "p1-fleet-broker"
RUN_TIMEOUT_S = 3600.0
DEFAULTS = {"A": "~/sdv-recordings/20261112-carla010-7d1b", "B": "~/sdv-recordings/20261111-carla010-2d1",
            "C": "~/sdv-recordings/20261111-carla010-6d1"}
LOG_TIME = re.compile(r"^\((\d+\.\d+)\)")
PUBLISHED = re.compile(r"Received PUBLISH from (\S+) \((d\d), (q\d), r\d, m\d+, '([^']*)', \.\.\. \((\d+) bytes\)\)")
DENIED = re.compile(r"Denied PUBLISH from (\S+)")
CONNECTED = re.compile(r"New client connected from \S+ as (\S+) \(")

pytestmark = pytest.mark.skipif(
    os.environ.get("SDV_FLEET_BROKER") != "1" or shutil.which("docker") is None or os.name != "posix",
    reason="the fleet's broker test runs only with SDV_FLEET_BROKER=1 (WSL Docker; the pinned test broker, the connector image by its "
           "pinned ID, the stack's images in the store; sudo -n for vcanf1-3, the sim venv and the recordings)")


def fail(what: str) -> None:
    pytest.fail("SDV_FLEET_BROKER=1 and an input is missing: %s" % what, pytrace=False)


def recordings() -> Dict[str, Path]:
    out = {}
    for L in LABELS:
        raw = os.environ.get("SDV_FLEET_RECORDING_%s" % L) or DEFAULTS[L]
        d = Path(raw).expanduser()
        if not (d / "manifest-line.json").is_file():
            fail("car %s's recording %s (SDV_FLEET_RECORDING_%s)" % (L, d, L))
        out[L] = d
    return out


BOUND = """
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import fleet
try:
    print("bound %d" % fleet.player_bound_s(Path(sys.argv[2])))
except fleet.stack.StackError:
    print("refused")
"""


def stack_bound_s(rec: Path, sim_py: Path) -> Any:
    """fleet.py's player_bound_s of a recording (stack.py's player_bound_s for its log), or None when the stack refuses it:
    read by the sim venv's Python, whose python-can fleet.py run reads it with (this test's own Python may have none)."""
    env = {k: v for k, v in os.environ.items() if k not in ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([str(sim_py), "-B", "-c", BOUND, str(STACK_DIR), str(rec)], capture_output=True, text=True, timeout=120, env=env)
    out = r.stdout.strip()
    if r.returncode != 0 or not re.fullmatch(r"bound \d+|refused", out):
        fail("the stack's bound on %s's player, read by the sim venv (exit %d)" % (rec.name, r.returncode))
    return None if out == "refused" else int(out.split()[1])


def log_too_long(rec: Path, bound: Any) -> bool:
    """A recording whose bound on its player the stack refuses (None), or whose log ends less than fleet.py's
    PLAYER_MARGIN_S inside that bound, or past it (fleet.py run refuses such a car; this guard fails before the broker
    starts)."""
    return bound is None or log_span_s(rec) >= bound - fleet.PLAYER_MARGIN_S


def log_span_s(rec: Path) -> float:
    """A recording's log from its first to its last frame, by the log's own times (candump's (seconds) column)."""
    name = json.loads((rec / "manifest-line.json").read_text(encoding="utf-8"))["recording"]["path"].rsplit("/", 1)[-1]
    lines = (rec / name).read_text(encoding="ascii").splitlines()
    first, last = (LOG_TIME.match(ln) for ln in (lines[0], lines[-1]))
    assert first and last, rec
    return float(last.group(1)) - float(first.group(1))


def keep_dir() -> Any:
    raw = os.environ.get("SDV_FLEET_KEEP")
    if raw is None:
        return None
    d = Path(raw)
    if not d.is_absolute() or not d.is_dir():
        fail("SDV_FLEET_KEEP must name an existing absolute directory")
    if d.resolve() == REPO.resolve() or REPO.resolve() in d.resolve().parents:
        fail("SDV_FLEET_KEEP must lie outside the repo")
    return d


def car_pki(ca_dir: Path, root: Path) -> Dict[str, Path]:
    """Each car's key and certificate, the key made here and its signing request signed by the broker tests' CA."""
    out = {}
    for L, thing in THINGS.items():
        d = root / ("car-%s" % L.lower())
        d.mkdir(parents=True)
        CB.sh("openssl", "genrsa", "-out", str(d / "device.key"), "2048")
        CB.sh("openssl", "req", "-new", "-key", str(d / "device.key"), "-subj", "/CN=%s" % thing, "-out", str(d / "device.csr"))
        (d / "device.ext").write_text("extendedKeyUsage=clientAuth\n", encoding="ascii")
        CB.sh("openssl", "x509", "-req", "-in", str(d / "device.csr"), "-CA", str(ca_dir / "ca.crt"), "-CAkey", str(ca_dir / "ca.key"),
              "-CAcreateserial", "-CAserial", str(root / "ca.srl"), "-out", str(d / "device.crt"), "-days", "2", "-extfile", str(d / "device.ext"))
        out[L] = d
    return out


def device_directories(ca_dir: Path, keys: Dict[str, Path], root: Path) -> Dict[str, Path]:
    """A device directory a car, as the stack mounts one: the key, the certificate, the CA file and connector.env (the
    endpoint, the car's thing, the rule; no databroker: the stack sets each car's own)."""
    out = {}
    for L, thing in THINGS.items():
        d = root / ("device-of-car-%s" % L.lower())
        d.mkdir(parents=True)
        shutil.copyfile(keys[L] / "device.key", d / "device.key")
        shutil.copyfile(keys[L] / "device.crt", d / "device.crt")
        shutil.copyfile(ca_dir / "ca.crt", d / "ca.pem")
        os.chmod(d / "device.key", 0o600)
        (d / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE=%s\n" % (CB.ADDRESS, thing, RULE), encoding="ascii")
        out[L] = d
    return out


def start_fleet_broker(ca_dir: Path, conf_dir: Path, connector_parts: Any) -> None:
    """The broker tests' pinned Mosquitto, as start_broker starts it (mutual TLS, the certificate's name as the user, on the
    internal network at their address, no published port), with an ACL that holds each car to its own thing's topics."""
    pin = CB.IMAGES["test_only"]["eclipse-mosquitto"]
    ref = "%s@%s" % (pin["repo"], pin["index_digest"])
    if CB.docker("image", "inspect", ref, check=False).returncode != 0:
        fail("the pinned test broker %s is not in the store (nothing here pulls it)" % ref)
    conf_dir.mkdir(parents=True, exist_ok=True)
    lines = ["per_listener_settings false", "persistence false", "log_dest stdout", "log_type all", "connection_messages true",
             "listener 8883", "cafile /certs/ca.crt", "certfile /certs/server.crt", "keyfile /certs/server.key",
             "require_certificate true", "tls_version tlsv1.2", "max_qos 1", "max_packet_size 131072",
             "use_identity_as_username true", "allow_anonymous false", "acl_file /conf/acl"]
    (conf_dir / "mosquitto.conf").write_text("\n".join(lines) + "\n", encoding="ascii")
    acl = ["user observer", "topic readwrite $aws/#"]
    for thing in THINGS.values():
        t = connector_parts.topics.Topics(thing, RULE)
        acl += ["", "user %s" % thing] + ["topic write %s" % x for x in t.publish] + ["topic read %s" % x for x in t.subscribe]
    (conf_dir / "acl").write_text("\n".join(acl) + "\n", encoding="ascii")
    os.chmod(conf_dir / "acl", 0o600)
    CB.docker("rm", "-f", "-v", CB.BROKER, check=False)
    uid = "%d:%d" % (os.getuid(), os.getgid())
    CB.docker("run", "-d", "--name", CB.BROKER, "--label", CB.LABEL + "=broker", *CB.COMMON, "--read-only", "--user", uid,
              "--network", CB.NET, "--ip", CB.ADDRESS, "--network-alias", CB.HOST, "-v", "%s:/certs:ro" % ca_dir, "-v", "%s:/conf:ro" % conf_dir,
              ref, "/usr/sbin/mosquitto", "-c", "/conf/mosquitto.conf")
    CB.BROKER_VOLUMES.extend(CB.volumes_of(CB.BROKER))
    assert CB.wait_until(lambda: any("mosquitto version 2.0.22 running" in ln for ln in CB.broker_log())), "\n".join(CB.broker_log()[-20:])
    assert CB.docker("port", CB.BROKER, check=False).stdout.strip() == ""          # no host port


class TimedObserver(CB.Observer):
    """The broker tests' observer, every message kept with its receive time (the host's wall clock, ms)."""

    def __init__(self) -> None:
        self.timed: List[Tuple[int, str, bytes]] = []
        super().__init__("fleet-observer")

    def _drain(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip("\r\n")
            self.lines.append(line)
            if line.startswith("Subscribed (mid:"):
                self._subscribed.set()
            elif line.startswith("$aws/"):
                topic, _sep, hexed = line.partition(" ")
                payload = bytes.fromhex(hexed)
                self.timed.append((time.time_ns() // 1_000_000, topic, payload))
                self.messages.append((topic, payload))


def nopull_shim(root: Path) -> Tuple[Path, Path]:
    """A directory holding `docker`, first on the cars' PATH: `docker pull REF` becomes `docker image inspect REF` (an image
    in the store passes as the pull would, one that is not fails the call); every call is logged, every other one passes."""
    d = root / "nopull"
    d.mkdir()
    log = root / "docker-calls.txt"
    shim = d / "docker"
    shim.write_text("\n".join([
        "#!/bin/bash",
        'SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'REAL=""',
        'IFS=: read -r -a dirs <<< "$PATH"',
        'for x in "${dirs[@]}"; do [ "$(cd "$x" 2>/dev/null && pwd)" = "$SELF_DIR" ] && continue; '
        'if [ -x "$x/docker" ]; then REAL="$x/docker"; break; fi; done',
        '[ -n "$REAL" ] || { echo "nopull: no real docker on PATH" >&2; exit 127; }',
        "printf 'docker' >> \"%s\"; printf ' %%q' \"$@\" >> \"%s\"; printf '\\n' >> \"%s\"" % (log, log, log),
        'if [ "${1:-}" = pull ]; then ref="${!#}"; if "$REAL" image inspect --format "{{.Id}}" "$ref" > /dev/null 2>&1; then '
        'echo "$ref"; exit 0; fi; echo "nopull: $ref is not in the store, and nothing is pulled" >&2; exit 1; fi',
        'exec "$REAL" "$@"', ""]), encoding="ascii")
    os.chmod(shim, 0o755)
    return d, log


def served_by(replay: Path) -> Dict[str, List[Any]]:
    return CB.witness_values(replay)


def cells_off_their_witness(batches: Dict[str, List[Dict[str, Any]]], served: Dict[str, Dict[str, List[Any]]]) -> List[str]:
    """Every telemetry cell of a CAN-fed path, by the car whose topic it came on, held to that car's own witness only: the
    cells that witness never served, as `car path cell`."""
    out = []
    for L, docs in batches.items():
        for b in docs:
            for row in b["rows"]:
                for path, cell in zip(b["paths"], row[1:]):
                    if path in served[L] and cell is not None and cell not in served[L][path]:
                        out.append("%s %s %r" % (L, path, cell))
    return out


def own_cells(L: str, batches: Dict[str, List[Dict[str, Any]]], served: Dict[str, Dict[str, List[Any]]]) -> List[Tuple[str, Any]]:
    """Car L's telemetry cells that no other car's witness holds for that path."""
    others = [x for x in served if x != L]
    return [(path, cell) for b in batches[L] for row in b["rows"] for path, cell in zip(b["paths"], row[1:])
            if path in served[L] and cell is not None and all(cell not in served[o].get(path, []) for o in others)]


def scan(roots: Sequence[Path], words: Sequence[str]) -> List[Tuple[str, str]]:
    found = []
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                text = p.read_bytes().decode("utf-8", "replace")
                found += [(p.name, w) for w in words if w in text]
    return found


def vcan_interfaces() -> List[str]:
    p = CB.sh("ip", "-o", "link", "show", check=False)
    return sorted(set(re.findall(r"^\d+: (vcanf[123])[:@]", p.stdout, re.M)))


def sweep(before_vcan: Sequence[str]) -> Dict[str, List[str]]:
    """What the cars left, removed: every container labelled sdv.stack.instance (this test's cars' own: nothing else runs
    an instance) and every vcanf<k> made since before_vcan. Returned, for the test to hold."""
    left = CB.docker("ps", "-aq", "--filter", "label=sdv.stack.instance", check=False).stdout.split()
    if left:
        CB.docker("rm", "-f", *left, check=False)
    made = sorted(set(vcan_interfaces()) - set(before_vcan))
    for v in made:
        CB.sh("sudo", "-n", "ip", "link", "delete", v, check=False)
    return {"containers": left, "vcan": made}


def assert_none_left(found: Dict[str, List[str]]) -> None:
    """No container of the fleet's was left for the sweep to remove (each car's stack removes its own in its finally)."""
    assert found["containers"] == [], "the fleet left containers: %s" % found["containers"]


def test_three_cars_at_the_local_broker_each_on_its_own_topic_with_its_own_witness_values_and_only_the_allowlist(
        image, pki, network, parts, tmp_path):  # noqa: F811 -- the broker tests' fixtures
    sim_py = CB.SIM_PY
    if not sim_py.is_file():
        fail("the sim venv's python %s" % sim_py)
    if CB.sh("sudo", "-n", "true", check=False).returncode != 0:
        fail("sudo -n (each car's stack makes its vcanf<k>)")
    src = CB.IMAGES["sources"]["csv-recorder"]["path"]
    cache = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
    if not (cache / "csv-recorder-0.4.6" / src).is_file():
        fail("the recorder's cached source %s (a build would download it)" % (cache / "csv-recorder-0.4.6" / src))
    if CB.docker("ps", "-aq", "--filter", "label=sdv.stack.run").stdout.split():
        fail("an empty stack: containers labelled sdv.stack.run exist")
    recs = recordings()
    for L, rec in recs.items():
        if log_too_long(rec, stack_bound_s(rec, sim_py)):
            fail("car %s's recording %s: the stack refuses its bound on its player, or its log ends less than %d s inside that "
                 "bound, or past it (SDV_FLEET_RECORDING_%s)" % (L, rec.name, fleet.PLAYER_MARGIN_S, L))
    keep = keep_dir()
    allow = CB.frozen_allowlist()
    base_env = {k: v for k, v in os.environ.items()
                if k not in ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE", "SDV_DEVICE_DIR", "SDV_SPOOL_DIR", "SDV_STATUS_DIR", "SDV_RECORDING",
                             "SDV_DEVICE_DIR_A", "SDV_DEVICE_DIR_B", "SDV_DEVICE_DIR_C")}
    base_env["PYTHONDONTWRITEBYTECODE"] = "1"
    cars = []
    for L in LABELS:
        cars += ["--car", "%s=%s" % (L, recs[L])]
    p = subprocess.run([str(sim_py), "-B", str(FLEET_PY), "check", *cars], capture_output=True, text=True, env=base_env, cwd=str(REPO), timeout=900)
    assert p.returncode == 0, "the recordings do not pass fleet.py check:\n%s%s" % (p.stdout, p.stderr)
    keys = car_pki(pki, tmp_path / "keys")
    devices = device_directories(pki, keys, tmp_path / "devices")
    shim, calls = nopull_shim(tmp_path)
    runs = keep if keep is not None else tmp_path / "runs"
    state = tmp_path / "state"
    env = dict(base_env, SDV_CONNECTOR_IMAGE=image, SDV_STATE=str(state), SDV_RUNS=str(runs), PATH="%s:%s" % (shim, os.environ.get("PATH", "")),
               **{"SDV_DEVICE_DIR_%s" % L: str(devices[L]) for L in LABELS})
    before_vcan = vcan_interfaces()
    before_runs = set(runs.glob("*-%s" % NAME))          # SDV_FLEET_KEEP may hold an earlier day's run of this name
    start_fleet_broker(pki, tmp_path / "conf", parts)
    obs = TimedObserver()
    found: Dict[str, List[str]] = {"containers": [], "vcan": []}
    try:
        proc = subprocess.run([str(sim_py), "-B", str(FLEET_PY), "run", "--name", NAME, *cars], capture_output=True, text=True, env=env,
                              cwd=str(REPO), timeout=RUN_TIMEOUT_S)
        time.sleep(2.0)
    finally:
        obs.close()
        found = sweep(before_vcan)          # held below, once the fleet's exit is
    new = sorted(set(runs.glob("*-%s" % NAME)) - before_runs)
    assert len(new) == 1, (proc.returncode, proc.stdout[-3000:], proc.stderr[-3000:])
    (run,) = new
    if keep is not None:
        capture = keep / ("%s.observer.jsonl" % run.name)
        capture.write_text("".join(json.dumps({"topic": t, "payload": b.decode("utf-8", "replace"), "rx_ms": ms}, sort_keys=True) + "\n"
                                   for ms, t, b in obs.timed), encoding="utf-8")
    assert proc.returncode == 0 and proc.stdout.splitlines()[-1] == "fleet: ok", (proc.stdout[-3000:], proc.stderr[-3000:])
    rec = json.loads((run / "fleet.json").read_text(encoding="utf-8"))
    assert rec["ok"] is True and [c["label"] for c in rec["cars"]] == list(LABELS)
    assert_none_left(found)
    shimmed = calls.read_text(encoding="utf-8").splitlines()
    assert [ln for ln in shimmed if ln.startswith("docker pull ")] and [ln for ln in shimmed if ln.startswith("docker run ")], \
        "the cars' stacks did not go through the shim, which turns every pull into an inspect"
    replays = {}
    for c in rec["cars"]:
        assert c["stack_exit"] == 0 and c["gates"] and all(c["gates"].values()) and c["connector"]["ok"], c
        assert c["witness"] and (run / c["witness"]).is_file(), c
        replays[c["label"]] = (run / c["witness"]).parent
    assert CB.docker("ps", "-aq", "--filter", "label=sdv.stack.run").stdout.split() == [], "a container of the stack is left"
    # each client published on its own thing's topics only, none was denied, and the three things connected
    log = CB.broker_log()
    assert not [ln for ln in log if DENIED.search(ln)], [ln for ln in log if DENIED.search(ln)][:5]
    own = {thing: set(parts.topics.Topics(thing, RULE).publish) for thing in THINGS.values()}
    published = [m.groups() for m in (PUBLISHED.search(ln) for ln in log) if m]
    assert {c for c, *_rest in published} == set(THINGS.values()), {c for c, *_rest in published}
    for client, _dup, _qos, topic, _n in published:
        assert topic in own[client], (client, topic)
    assert {m.group(1) for m in (CONNECTED.search(ln) for ln in log) if m} >= set(THINGS.values())
    # what the observer read, by car: telemetry on each car's own topic, cells held to that car's own witness
    telemetry = {L: "$aws/rules/%s/%s" % (RULE, THINGS[L]) for L in LABELS}
    vss = {L: "$aws/things/%s/shadow/name/vss/update" % THINGS[L] for L in LABELS}
    messages = list(obs.messages)
    assert {t for t, _p in messages} <= set().union(*own.values())
    batches = {L: [json.loads(p) for t, p in messages if t == telemetry[L]] for L in LABELS}
    served = {L: served_by(replays[L]) for L in LABELS}
    for L in LABELS:
        assert batches[L], "no telemetry on car %s's topic" % L
        for b in batches[L]:
            assert set(b) == {"v", "batch", "paths", "rows", "appstate"} and b["v"] == 1 and set(b["paths"]) <= set(allow.PATHS)
    assert cells_off_their_witness(batches, served) == []
    for L in LABELS:
        assert own_cells(L, batches, served), "car %s has no cell that no other car's witness holds" % L
    planted_cell = own_cells("B", batches, served)[0]
    planted = dict(batches, A=batches["A"] + [{"paths": [planted_cell[0]], "rows": [[0, planted_cell[1]]]}])
    assert cells_off_their_witness(planted, served) == ["A %s %r" % planted_cell], "the cross-car check is blind"
    prefix = CB.attr.MONITOR_PREFIX.rstrip(".").lower()
    for t, payload in messages:
        assert prefix not in payload.decode("utf-8", "replace").lower(), t
        if t in vss.values():
            reported = json.loads(payload)["state"]["reported"]
            assert set(reported) <= set(allow.PATHS), t
    # nothing of the far end or the device under the run or the state directory
    words = list(THINGS.values()) + [RULE, CB.ADDRESS, CB.HOST, "connector.env", "device.key", "device.crt", "ca.pem"]
    words += [str(d) for d in devices.values()] + [d.name for d in devices.values()]
    assert scan([run, state], words) == []
    # counts of this run, for the reader of a log (none is a measurement)
    print("fleet broker test: %d messages read; per car, telemetry batches %s" % (len(messages), {L: len(batches[L]) for L in LABELS}))
