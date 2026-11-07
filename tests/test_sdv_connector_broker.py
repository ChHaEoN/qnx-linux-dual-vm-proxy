"""The twin connector's real uplink and image at a local broker, and the stack's full local slice with the connector
(sdv/connector/uplink_aws.py, the image of sdv/connector/build_image.py, sdv/stack/stack.py --connector): SDV Phase 4
WP3.

OPT-IN: skipped unless SDV_CONNECTOR_BROKER=1, on POSIX with docker (WSL Ubuntu-24.04's Docker Engine). This file is
not one the CI recipe's skip check names (tests/twin_gate.py), which is why these tests are here and not in
tests/test_sdv_connector.py. Once opted in, a missing input fails: the generated catalogue and the frozen allowlist go
through the gate, and a connector image that is not the one images.json pins is refused.

NO CLOUD: the far end is the pinned eclipse-mosquitto (images.json, test_only; by index digest) with mutual TLS, on a
Docker network created --internal, with no published port and no listener on the host. The CA, the broker's
certificate, the device's key and certificate (a CSR signed by the CA: the key never leaves the "device"), an
observer's certificate and a device certificate of a SECOND CA are made by this test with openssl, under pytest's
temporary directory, and are gone with it. Every name is a placeholder (example-thing, example_rule, broker.test);
the broker's address is a documentation address (RFC 5737) on that internal network.

The uplink probe (the connector IMAGE by its pinned ID, its own uplink_aws.py on its own SDK, driven by
sdv/connector/probes/uplink_driver.py mounted read-only; the broker and the image on the one internal network):
  * the handshake succeeds with the device's certificate, and the CONNECT the broker logs is MQTT 3.1.1, a clean
    session, a 60 s keep-alive and NO user name: the SDK's metrics are off (prep gap k);
  * the handshake fails with a certificate of another CA, and when the broker's certificate is not from the CA of
    ca_filepath; the broker refuses a client that presents no certificate;
  * a QoS 1 publish is acknowledged and the observer reads the exact bytes on each of the four exact topics; a message
    the observer publishes on a subscribed topic reaches the callback as the exact bytes;
  * with the broker paused a publish fails after the operation time-out and does not hang; it had been written, so
    the broker reads it once it goes on, and it is not sent a second time;
  * a publish in flight when the broker dies is reported as failed and never arrives; a publish made while the broker
    is away is refused at once and never arrives; the SDK's own connection does not come back by itself, with its own
    reconnect timer at HANDOFF_HOLD_S seconds in the driver's process so that its first attempts fall inside the test's
    wait (at the shipped hour the wait could not tell the uplink's disconnect, from inside the SDK's interrupted
    callback, from the hold: the broker would log no CONNECT either way); after the broker's restart the next publish
    opens a new connection (a clean session again), the subscriptions are made again and on_resumed is called; the
    broker's log of everything it received holds no PUBLISH with the DUP flag and nothing that was reported as failed;
  * the hard review's wire run (2026-10-08): the SDK knows of a loss and the uplink is told late (the driver hands the
    SDK's interrupted callback on from another thread, 25 s after), a publish is made in between (the uplink hands it
    to the SDK, whose connection is down: the SDK queues it), and the broker is back, paused across the moment the
    SDK's default reconnect timer would make its attempt and going on before the uplink's own wait for that publish
    ends. The SDK makes no connection of its own: the broker logs no CONNECT that the uplink did not open and no
    PUBLISH that was not acknowledged to the caller; the uplink's own wait gives the connection up; the next publish
    opens the next connection; and the late word of the loss does not touch that one;
  * THE CHOICE, g, with the uplink NEVER told of a loss: with a hold and a life of seconds in the driver's process
    (no test waits the shipped hour out), a publish made in the last seconds before the SDK's own reconnect is
    refused before the SDK is asked, the connection is given up for showing no life, the SDK makes no connection of
    its own although its timer runs out with the broker up, and the broker never receives that publish;
  * what g rests on: the SDK left alone (never told, nothing handed over) makes its own reconnect when the timer it
    was given says and not before, comes back with nothing to send, and is disconnected again by the uplink;
  * what g rests on, the three cases of what the SDK does with a QoS 1 publish that was not acknowledged (the module's
    docstring, 1 to 3), each with the uplink NEVER told of the loss and a timer of seconds in the driver's process:
      - case 3, the SDK's queue: a publish handed over within the connection's life, on a connection the SDK has lost,
        is queued by the SDK, which says nothing; the uplink's own wait gives the connection up; and when the SDK's
        timer runs out with the broker up, the SDK makes no connection of its own and the broker never receives the
        publish (it does when that give-up is taken out: the SDK then reconnects and writes its queue);
      - case 2, in flight when the connection is lost (clean_session=True): the SDK cancels it, and when it comes back
        by itself its own connection writes nothing;
      - case 1, written to a far end that stays silent: the SDK fails it after its operation time-out, and when it
        comes back by itself after the loss its own connection writes nothing. In both of the last two the SDK's
        connection does come back, which the test requires: it makes its CONNECT, the uplink disconnects it again
        (resumed_by_sdk), and no PUBLISH is on it;
  * a connect the SDK answers after the uplink stopped waiting for it (the broker paused across the uplink's wait, and
    going on inside the SDK's own handshake wait): the uplink reports the failure, asks for no second connect while the
    first is unanswered, and disconnects the late connection the moment the SDK reports it; the broker logs that
    CONNECT and its DISCONNECT, and closes no older connection when the next one comes; and the SDK's own handshake
    wait, which the builder cannot be given, is seen with the uplink's wait made long;
  * what this broker does with a publish its ACL denies: it acknowledges it, drops it and keeps the connection, so the
    local broker cannot show one kind of publish failing alone (a note for the account steps, not a property of the
    cloud service).

The full local slice (stack.py replay --feed vcan --connector, the connector started by the stack in the host's
namespace with a test device directory whose endpoint is the broker's address on the internal network):
  * the replay passes every gate of the stack's own, the three listener snapshots among them, and the connector's;
  * the started connector has exactly its three mounts, the host's network, a read-only root, no capability, the host
    user and no published port (docker inspect, taken while it runs);
  * what the observer read is checked against the run: every telemetry cell of a CAN-fed path is a value the
    databroker served for that path (the witness's log, which the stack holds equal to the decoded recording), the
    last vss document holds the witness's last value of each and the app's last AppState record, and every key is an
    allowlisted path;
  * a delta the observer publishes reaches the connector and the spool (the two-field record);
  * stopping the stack flushes one batch and one vss document;
  * the real run directory, the connector's own log in it included, holds neither the endpoint, the thing's or the
    rule's name, the device directory's path nor a name of a file in it.
The slice with the claim bridge (the connector bridge scenario, run (b); only with SDV_BRIDGE_IMAGE, the bridge image's ID): the same
slice with `--bridge broker`, so that the stack builds and starts the native vss monitor and the bridge writes its leaves of
the excluded branch into the databroker the connector reads. Every gate of the stack's own holds, the bridge's and the
connector's among them; the far end received allowlisted keys only; and a sampler that only reads saw every leaf the run's
own attribution table gives the bridge hold a value in one read, with the connector running before and after it.
The canary run (design twin-allowlist.md A6 on the pinned databroker): the same slice with no bridge, and a writer that
plants a value in every leaf of the excluded branch (enumerated from the generated catalogue, never spelled here): a
distinctive number in each counter, and a valid value in the leaves too narrow to hold one. While the connector runs
the databroker holds them (read back). The observer's raw bytes hold no canary and no path of that branch.

DESIGN VALUES of these tests (waits that bound a test, none a claim): WAIT_S for a container or a message, the pauses
around a broker's stop and start, the two values the late-connect tests give the driver's own CONNECT_WAIT_S (3 s
and 30 s, in that process only; the image's limits.py is not touched), DEFER_S, how late the driver hands the
uplink the SDK's word of a loss in the one test that asks for it, NEVER_S, which holds that word back past the end of
a test, and the hold and life the tests of THE CHOICE give the driver's process (HOLD_S and LIFE_S, ALONE_HOLD_S,
HANDOFF_HOLD_S; the shipped ones are 3600 s and 900 s: no test waits them out, so a test that has to tell a give-up
of the uplink's from the SDK's own timer sets a timer of seconds, so that the SDK's attempt would fall inside its
wait). Nothing here is a timing: "took less than" is only "it came back", and "not before its timer" is a bound read
to two seconds on the test's own clock.

LEFT BEHIND: nothing. The broker's image declares two volumes, so each of its containers gets two anonymous ones:
every removal here is docker rm -v, and the network fixture's teardown holds that none of them is still in the store.

Does not demonstrate: the cloud service in any respect (no shadow service answers here, no rule runs, no policy of
that service authorises, no certificate has a status, no quota applies, no metric counts; the broker's ACL is another
language than that service's policy); the default port; the arm64 image (built and scanned, never run); the shipped
hold and life run out (the tests that need the SDK's own attempt to fall inside their wait give the driver's process a
timer of seconds); the SDK's native source (what is seen here is what the pinned SDK did at this broker, on this
host); any timing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytest

import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONNECTOR_DIR = REPO / "sdv" / "connector"
STACK_DIR = REPO / "sdv" / "stack"
PROBES_DIR = CONNECTOR_DIR / "probes"
TWIN_FROZEN = REPO / "sdv-out" / "twin" / "twin_allowlist.py"
IMAGES = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(
    os.environ.get("SDV_CONNECTOR_BROKER") != "1" or shutil.which("docker") is None or os.name != "posix",
    reason="the connector's broker tests run only with SDV_CONNECTOR_BROKER=1 (WSL Docker; the pinned test broker, the connector "
           "image by its pinned ID; the full slice also needs sudo -n for vcan0, the sim venv and the recording)")

sys.dont_write_bytecode = True
for _d in (str(STACK_DIR),):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import attribution as attr  # noqa: E402

THING, RULE = "example-thing", "example_rule"          # placeholders: no identifier is ever in the tree
HOST = "broker.test"                                   # the broker's name on the internal network (a reserved TLD)
SUBNET, ADDRESS = "198.51.100.0/29", "198.51.100.2"    # RFC 5737 documentation addresses, on the internal network only
NET = "sdv-p4-wp3-net"
BROKER = "sdv-p4-wp3-broker"
DRIVER = "sdv-p4-wp3-driver"
WRITER = "sdv-p4-wp3-writer"
LABEL = "sdv.connector.brokertest"
COMMON = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m", "--memory", "512m", "--memory-swap", "512m"]
WAIT_S = 30.0
DEFER_S = 25.0          # how late the uplink is told of a loss the SDK reported, in the one test that defers it
NEVER_S = 120.0         # ... and in the tests that never tell it: past their end (the driver's longest delay)
HOLD_S, LIFE_S = 30, 8           # the SDK's own reconnect timer and the life of a connection, in the driver's process, for g's test
ALONE_HOLD_S = 12       # the SDK's own reconnect timer in the test that leaves the SDK alone, and in the two that fail a request first
HANDOFF_HOLD_S = 8      # ... and in the hand-off test, which tells the uplink of the loss at once: only there to be outlasted
BROKER_VOLUMES: List[str] = []          # the anonymous volumes Docker made for the broker's containers (its image declares two)
SIM_PY = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser() / "bin" / "python"
RECORDING = os.environ.get("SDV_RECORDING", "~/sdv-recordings/20260930-sigsim-1b")
SHADOW = "$aws/things/%s/shadow/name/" % THING
TELEMETRY = "$aws/rules/%s/%s" % (RULE, THING)
# The device's topics, written out here: the far end's view. The ACL the broker loads is made from topics.py; a test
# holds the two equal.
PUBLISH = [TELEMETRY, SHADOW + "vss/update", SHADOW + "config/update", SHADOW + "config/get"]
SUBSCRIBE = [SHADOW + "config/get/accepted", SHADOW + "config/get/rejected", SHADOW + "config/update/delta",
             SHADOW + "config/update/rejected", SHADOW + "vss/update/rejected"]
CONNECT_LINE = re.compile(r"New client connected from \S+ as (\S+) \((p\d), (c\d), (k\d+)(?:, u'([^']*)')?\)\.")
INBOUND = re.compile(r"Received PUBLISH from %s \((d\d), (q\d), r\d, m\d+, '([^']*)', \.\.\. \((\d+) bytes\)\)" % re.escape(THING))


def sh(*args: str, check: bool = True, timeout: float = 120, **kw: Any) -> subprocess.CompletedProcess:
    p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, **kw)
    if check and p.returncode != 0:
        raise AssertionError("%s: exit %d: %s" % (" ".join(args[:4]), p.returncode, (p.stderr or p.stdout)[-1500:]))
    return p


def docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
    return sh("docker", *args, check=check, timeout=timeout)


def wait_until(what: Callable[[], Any], seconds: float = WAIT_S, poll: float = 0.25) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        got = what()
        if got:
            return got
        time.sleep(poll)
    return what()


def broker_log() -> List[str]:
    """Everything the broker logged, in order, without its time stamps (its stdout; a start-up note goes to stderr)."""
    p = subprocess.run(["docker", "logs", BROKER], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=60)
    return [re.sub(r"^\d+: ", "", ln) for ln in p.stdout.splitlines()]


def connects() -> List[Tuple[str, ...]]:
    """(client id, protocol, clean, keep-alive, user name or None) of every CONNECT the broker accepted from the device."""
    return [m.groups() for m in (CONNECT_LINE.search(ln) for ln in broker_log()) if m and m.group(1) == THING]


def inbound() -> List[Tuple[str, str, int]]:
    """(DUP flag, topic, bytes) of every PUBLISH the broker received from the device, in order."""
    return [(m.group(1), m.group(3), int(m.group(4))) for m in (INBOUND.search(ln) for ln in broker_log()) if m]


@pytest.fixture(scope="module")
def parts() -> Any:
    """The connector's topics.py and limits.py (standard library only), by their files: no SDK, no uplink module."""
    import importlib.util
    out = {}
    for name in ("limits", "topics"):
        spec = importlib.util.spec_from_file_location("sdv_connector_%s_for_the_broker_tests" % name, str(CONNECTOR_DIR / (name + ".py")))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out[name] = mod
    t = out["topics"].Topics(THING, RULE)
    assert list(t.publish) == PUBLISH and list(t.subscribe) == SUBSCRIBE and t.client_id == THING
    return type("Parts", (), out)


@pytest.fixture(scope="module")
def image() -> str:
    """The connector's amd64 image, by the ID images.json pins. Nothing is built or pulled here."""
    pin = IMAGES["connector"]["amd64"]
    p = docker("image", "inspect", "-f", "{{.Id}} {{.Architecture}} {{.Config.User}}", pin["id"], check=False)
    assert p.returncode == 0, "the pinned connector image %s is not in the store: python3 sdv/connector/build_image.py build" % pin["id"]
    assert p.stdout.split() == [pin["id"], "amd64", "10001:10001"], p.stdout
    return pin["id"]


@pytest.fixture(scope="module")
def pki(tmp_path_factory) -> Path:
    """A throwaway CA and what it signed, and a second CA with a device certificate of its own. RSA 2048, two days."""
    d = tmp_path_factory.mktemp("pki")

    def ca(name: str) -> None:
        sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / (name + ".key")), "-out", str(d / (name + ".crt")),
           "-subj", "/CN=sdv-test-%s" % name, "-days", "2", "-addext", "basicConstraints=critical,CA:TRUE",
           "-addext", "keyUsage=critical,keyCertSign,cRLSign")

    def leaf(name: str, cn: str, signer: str, ext: str) -> None:
        sh("openssl", "genrsa", "-out", str(d / (name + ".key")), "2048")          # the key is made where it is used ...
        sh("openssl", "req", "-new", "-key", str(d / (name + ".key")), "-subj", "/CN=%s" % cn, "-out", str(d / (name + ".csr")))
        (d / (name + ".ext")).write_text(ext + "\n", encoding="ascii")
        sh("openssl", "x509", "-req", "-in", str(d / (name + ".csr")), "-CA", str(d / (signer + ".crt")), "-CAkey", str(d / (signer + ".key")),
           "-CAcreateserial", "-out", str(d / (name + ".crt")), "-days", "2", "-extfile", str(d / (name + ".ext")))          # ... the CSR is signed

    ca("ca")
    ca("ca2")
    leaf("server", HOST, "ca", "subjectAltName=DNS:%s,DNS:localhost,IP:%s\nextendedKeyUsage=serverAuth" % (HOST, ADDRESS))
    leaf("device", THING, "ca", "extendedKeyUsage=clientAuth")
    leaf("observer", "observer", "ca", "extendedKeyUsage=clientAuth")
    leaf("stranger", THING, "ca2", "extendedKeyUsage=clientAuth")
    return d


def device_directory(root: Path, pki: Path, endpoint: str, cert: str = "device", ca: str = "ca") -> Path:
    """A device directory as the stack mounts one: the key, the certificate, the CA file, and the environment file."""
    d = root
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pki / (cert + ".key"), d / "device.key")
    shutil.copyfile(pki / (cert + ".crt"), d / "device.crt")
    shutil.copyfile(pki / (ca + ".crt"), d / "ca.pem")
    os.chmod(d / "device.key", 0o600)
    (d / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE=%s\n" % (endpoint, THING, RULE), encoding="ascii")
    return d


def volumes_of(container: str) -> List[str]:
    """The Docker volumes mounted into a container, by name. The test broker's image declares two (its data and its
    log directory), so every container of it gets two anonymous ones, which outlive a removal that does not name them."""
    p = docker("inspect", "-f", "{{json .Mounts}}", container, check=False)
    return sorted(m["Name"] for m in (json.loads(p.stdout or "null") or []) if m.get("Type") == "volume") if p.returncode == 0 else []


@pytest.fixture(scope="module")
def network():
    """The internal network, and nothing of these tests left behind: their containers are removed WITH their anonymous
    volumes (docker rm -v), then the network. The teardown holds that no container, no network and none of the volumes
    Docker made for a broker of this module is left (by their own names: another session's volumes are not its
    business)."""
    def clean() -> None:
        ids = docker("ps", "-aq", "--filter", "label=" + LABEL, check=False).stdout.split()
        if ids:
            docker("rm", "-f", "-v", *ids, check=False)
        docker("network", "rm", NET, check=False)

    clean()
    del BROKER_VOLUMES[:]
    docker("network", "create", "--internal", "--subnet", SUBNET, "--label", LABEL + "=1", NET)
    assert docker("network", "inspect", "-f", "{{.Internal}}", NET).stdout.strip() == "true"
    try:
        yield NET
    finally:
        clean()
    assert docker("ps", "-aq", "--filter", "label=" + LABEL).stdout.split() == []
    assert docker("network", "inspect", NET, check=False).returncode != 0
    left = [v for v in BROKER_VOLUMES if docker("volume", "inspect", v, check=False).returncode == 0]
    assert left == [], "volumes of the test broker left in the store: %s" % left


def start_broker(pki: Path, conf_dir: Path, flavour: str = "acl") -> None:
    """The pinned Mosquitto with mutual TLS on the internal network at ADDRESS, no published port. flavour acl: the
    certificate's CN is the user, and an ACL holds the device to its exact topics; raw: the CONNECT's own user name is
    kept (and logged), any client with a certificate of the CA may do anything."""
    pin = IMAGES["test_only"]["eclipse-mosquitto"]
    ref = "%s@%s" % (pin["repo"], pin["index_digest"])
    assert docker("image", "inspect", ref, check=False).returncode == 0, "%s is not in the store (the WP0 probe pulls it by digest)" % ref
    conf_dir.mkdir(parents=True, exist_ok=True)
    lines = ["per_listener_settings false", "persistence false", "log_dest stdout", "log_type all", "connection_messages true",
             "listener 8883", "cafile /certs/ca.crt", "certfile /certs/server.crt", "keyfile /certs/server.key",
             "require_certificate true", "tls_version tlsv1.2", "max_qos 1", "max_packet_size 131072"]
    if flavour == "acl":
        lines += ["use_identity_as_username true", "allow_anonymous false", "acl_file /conf/acl"]
    else:
        lines += ["use_identity_as_username false", "allow_anonymous true"]
    (conf_dir / "mosquitto.conf").write_text("\n".join(lines) + "\n", encoding="ascii")
    acl = (["user observer", "topic readwrite $aws/#", "", "user %s" % THING] + ["topic write %s" % t for t in PUBLISH]
           + ["topic read %s" % t for t in SUBSCRIBE])
    (conf_dir / "acl").write_text("\n".join(acl) + "\n", encoding="ascii")
    os.chmod(conf_dir / "acl", 0o600)
    docker("rm", "-f", "-v", BROKER, check=False)          # -v: with the two anonymous volumes of the broker before it
    docker("run", "-d", "--name", BROKER, "--label", LABEL + "=broker", *COMMON, "--read-only", "--user", "%d:%d" % (os.getuid(), os.getgid()),
           "--network", NET, "--ip", ADDRESS, "--network-alias", HOST, "-v", "%s:/certs:ro" % pki, "-v", "%s:/conf:ro" % conf_dir,
           ref, "/usr/sbin/mosquitto", "-c", "/conf/mosquitto.conf")
    BROKER_VOLUMES.extend(volumes_of(BROKER))
    assert wait_until(lambda: any("mosquitto version 2.0.22 running" in ln for ln in broker_log())), "\n".join(broker_log()[-20:])
    ports = json.loads(docker("inspect", "-f", "{{json .NetworkSettings.Ports}}", BROKER).stdout or "null") or {}
    assert not [k for k, v in ports.items() if v] and docker("port", BROKER, check=False).stdout.strip() == ""          # no host port
    listening = sh("ss", "-ltnH", check=False).stdout
    assert ":8883" not in listening, "a listener on the host: %s" % listening          # nothing listens on the host for it


class Observer:
    """mosquitto_sub inside the broker's container, with the observer's certificate, on `$aws/#` (a `#` alone does not
    match a topic that begins with `$`): every message as (topic, payload bytes), in the order it arrived."""

    def __init__(self, client_id: str = "observer") -> None:
        self.messages: List[Tuple[str, bytes]] = []
        self.lines: List[str] = []
        self._subscribed = threading.Event()
        self.proc = subprocess.Popen(
            ["docker", "exec", "-t", BROKER, "mosquitto_sub", "-h", "localhost", "-p", "8883", "--cafile", "/certs/ca.crt",      # -t: line by line
             "--cert", "/certs/observer.crt", "--key", "/certs/observer.key", "-i", client_id, "-q", "1", "-t", "$aws/#", "-F", "%t %x", "-d"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()
        assert self._subscribed.wait(WAIT_S), "the observer did not subscribe: %s" % self.lines[-10:]

    def _drain(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip("\r\n")
            self.lines.append(line)
            if line.startswith("Subscribed (mid:"):
                self._subscribed.set()
            elif line.startswith("$aws/"):
                topic, _sep, hexed = line.partition(" ")
                self.messages.append((topic, bytes.fromhex(hexed)))

    def on(self, topic: str) -> List[bytes]:
        return [p for t, p in list(self.messages) if t == topic]

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        subprocess.run(["docker", "exec", BROKER, "pkill", "mosquitto_sub"], capture_output=True, timeout=30)
        self._thread.join(5)


def observer_publish(topic: str, payload: bytes) -> None:
    """One QoS 1 message from the observer (mosquitto_pub inside the broker's container): the exact bytes, from a file."""
    p = subprocess.run(["docker", "exec", "-i", BROKER, "mosquitto_pub", "-h", "localhost", "-p", "8883", "--cafile", "/certs/ca.crt",
                        "--cert", "/certs/observer.crt", "--key", "/certs/observer.key", "-i", "observer-pub", "-q", "1", "-t", topic, "-s"],
                       input=payload, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-500:]


class Driver:
    """The connector image by ID, its python on sdv/connector/probes/uplink_driver.py (mounted read-only), on the
    internal network with a device directory mounted where the stack mounts it. One JSON line in, one out."""

    def __init__(self, image_id: str, device: Path, network: str = NET) -> None:
        docker("rm", "-f", DRIVER, check=False)
        self.proc = subprocess.Popen(
            ["docker", "run", "-i", "--rm", "--name", DRIVER, "--label", LABEL + "=driver", *COMMON, "--read-only",
             "--user", "%d:%d" % (os.getuid(), os.getgid()), "--network", network,
             "--mount", "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % device,
             "--mount", "type=bind,src=%s,dst=/probe,readonly" % PROBES_DIR,
             "--env-file", str(device / "connector.env"), "--entrypoint", "python", image_id, "/probe/uplink_driver.py"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def send(self, **cmd: Any) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(cmd) + "\n")
        self.proc.stdin.flush()

    def answer(self) -> Dict[str, Any]:
        assert self.proc.stdout is not None and self.proc.stderr is not None
        line = self.proc.stdout.readline()
        assert line, "the driver ended: %s" % self.proc.stderr.read()[-1500:]
        return json.loads(line)

    def ask(self, **cmd: Any) -> Dict[str, Any]:
        self.send(**cmd)
        return self.answer()

    def publish(self, topic: str, payload: bytes) -> Dict[str, Any]:
        return self.ask(op="publish", topic=topic, hex=payload.hex())

    def open(self, subscribe: Sequence[str] = (), limits: Optional[Dict[str, Any]] = None, defer: Optional[float] = None) -> "Driver":
        """Build; set `limits` (the driver's own `limit` command, which changes a value in its process only) and `defer` (its
        own `defer`: the uplink is told of a loss that many seconds after the SDK knows), both before the connect; connect;
        subscribe."""
        cmds: List[Dict[str, Any]] = [dict(op="build")]
        cmds += [dict(op="limit", name=k, value=v) for k, v in (limits or {}).items()]
        cmds += [dict(op="defer", seconds=defer)] if defer is not None else []
        cmds += [dict(op="connect")] + [dict(op="subscribe", topic=t) for t in subscribe]
        for cmd in cmds:
            r = self.ask(**cmd)
            assert r["ok"], r
        return self

    def end(self) -> Tuple[int, str]:
        assert self.proc.stdin is not None and self.proc.stderr is not None
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait(timeout=30)
        err = self.proc.stderr.read()
        docker("rm", "-f", DRIVER, check=False)
        return self.proc.returncode, err


# ============================================================ the image

def test_the_pinned_image_holds_the_trees_own_modules_and_frozen_allowlist_and_runs_as_its_own_user(image):
    """The pin names an image; this ties it to the tree: every file in the image's /app is, byte for byte, the file
    sdv/connector/build_image.py would stage today, and there is no other file there. A module edited after the last
    build shows here, before any other test of this file says anything about "the connector". No network, a read-only
    root; the image's own user."""
    import hashlib
    import importlib.util
    spec = importlib.util.spec_from_file_location("sdv_connector_build_image_for_the_broker_tests", str(CONNECTOR_DIR / "build_image.py"))
    assert spec is not None and spec.loader is not None
    build_image = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_image)
    code = ("import hashlib, json, os; print(json.dumps({'uid': os.getuid(), 'files': {f: hashlib.sha256(open('/app/' + f, 'rb').read()).hexdigest() "
            "for f in sorted(os.listdir('/app'))}}))")
    p = docker("run", "--rm", "--network", "none", "--read-only", *COMMON, "--entrypoint", "python", image, "-c", code)
    got = json.loads(p.stdout)
    want = {name: hashlib.sha256(src.read_bytes()).hexdigest() for name, src in build_image.staged(TWIN_FROZEN).items()}
    assert got["files"] == want, sorted(k for k in set(got["files"]) | set(want) if got["files"].get(k) != want.get(k))
    assert got["uid"] == 10001 and len(want) == 17 and not [f for f in want if "burst" in f or "probe" in f or "driver" in f]
    labels = json.loads(docker("image", "inspect", "-f", "{{json .Config.Labels}}", image).stdout)
    assert {k: labels.get(k) for k in IMAGES["connector"]["labels"]} == IMAGES["connector"]["labels"]
    # the build's shadow check, run again here as the Dockerfile has it: it passes on the image as it is, and it fails
    # when a module of /app has the name of an installed one (a file of the test's, mounted in for this one run)
    (step,) = [ln for ln in (CONNECTOR_DIR / "Dockerfile").read_text(encoding="utf-8").splitlines() if ln.startswith("RUN python -c ")]
    snippet = step[len('RUN python -c "'):-1]
    assert "find_spec" in snippet and '"' not in snippet
    ok = docker("run", "--rm", "--network", "none", "--read-only", *COMMON, "--workdir", "/", "--entrypoint", "python", image, "-c", snippet,
                check=False)
    assert ok.returncode == 0, (ok.stdout, ok.stderr)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="sdv-p4-wp3-") as tmp:
        os.chmod(tmp, 0o755)
        (Path(tmp) / "rich.py").write_text("# a module of this name is installed in the image\n", encoding="utf-8")
        os.chmod(Path(tmp) / "rich.py", 0o644)
        bad = docker("run", "--rm", "--network", "none", "--read-only", *COMMON, "--workdir", "/",
                     "--mount", "type=bind,src=%s,dst=/app/rich.py,readonly" % (Path(tmp) / "rich.py"),
                     "--entrypoint", "python", image, "-c", snippet, check=False)
    assert bad.returncode == 1 and "shadows an installed module: ['rich']" in bad.stderr, (bad.returncode, bad.stderr)
    # with nothing of a device it cannot be put together: status 2 and one fixed sentence, on a read-only root with no network
    q = docker("run", "--rm", "--network", "none", "--read-only", *COMMON, image, check=False)
    assert q.returncode == 2 and q.stdout == "" and q.stderr.startswith("connector: ") and len(q.stderr.splitlines()) == 1, (q.stdout, q.stderr)


# ============================================================ the uplink probe

def test_the_handshake_succeeds_and_the_connect_is_mqtt_3_1_1_clean_with_a_60_s_keep_alive_and_no_sdk_metrics(image, pki, network, parts, tmp_path):
    """Prep gap k, at the broker: what the SDK's own defaults would be is seen in tests/test_sdv_connector.py on a
    stand-in; here the real SDK's CONNECT is read off the real broker's log. The raw flavour keeps the CONNECT's own
    user name: with the SDK's metrics on it would be a string of the SDK's name, version and features."""
    start_broker(pki, tmp_path / "conf", "raw")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(SUBSCRIBE)
    try:
        r = d.publish(TELEMETRY, b'{"v":0}')
        assert r["ok"] and r["counters"]["opened"] == 1 and r["resumed"] == 0
        assert connects() == [(THING, "p2", "c1", "k%d" % parts.limits.KEEP_ALIVE_S, None)]          # 3.1.1, clean, 60 s, no user name
        assert not [ln for ln in broker_log() if "SDK" in ln or "Metadata" in ln or "u'" in ln]
        assert d.ask(op="close")["ok"]
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")          # the SDK wrote nothing to stderr by itself, and the process ended by itself
    assert any("Received DISCONNECT from %s" % THING in ln for ln in broker_log())          # close() said goodbye


def test_the_handshake_fails_with_a_certificate_of_another_ca_and_with_a_broker_certificate_of_another_ca(image, pki, network, tmp_path):
    start_broker(pki, tmp_path / "conf")
    for name, kw in (("stranger", dict(cert="stranger")), ("other-ca", dict(ca="ca2"))):
        d = Driver(image, device_directory(tmp_path / name, pki, HOST, **kw))
        try:
            assert d.ask(op="build")["ok"]
            r = d.ask(op="connect")
            assert r == dict(r, ok=False, error="UplinkError") and r["counters"]["opened"] == 0 and r["took_s"] < 20
            r = d.publish(TELEMETRY, b"{}")
            assert not r["ok"]          # and nothing is opened by a publish after a connect that never succeeded
        finally:
            rc, err = d.end()
        assert (rc, err) == (0, "")
    assert connects() == [] and inbound() == []
    assert [ln for ln in broker_log() if "certificate verify failed" in ln], broker_log()[-10:]          # the stranger, refused by the broker
    # a client that presents no certificate at all is refused by this broker (the uplink always presents the device's)
    p = subprocess.run(["docker", "exec", BROKER, "mosquitto_pub", "-h", "localhost", "-p", "8883", "--cafile", "/certs/ca.crt",
                        "-i", "no-certificate", "-q", "1", "-t", TELEMETRY, "-m", "x"], capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and connects() == []
    # a file of the device directory that is not there: refused when the uplink is put together, before any connection
    broken = device_directory(tmp_path / "no-key", pki, HOST)
    (broken / "device.key").unlink()
    d = Driver(image, broken)
    try:
        r = d.ask(op="build")
        assert r["ok"] is False and r["error"] == "UplinkError" and "counters" not in r
    finally:
        d.end()


def test_a_qos_1_publish_is_acknowledged_and_the_observer_reads_the_exact_bytes_on_the_exact_topics(image, pki, network, parts, tmp_path):
    start_broker(pki, tmp_path / "conf")
    obs = Observer()
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(SUBSCRIBE)
    try:
        sent = {TELEMETRY: json.dumps({"v": 0, "batch": 1, "paths": ["a"], "rows": [[1, 2.5, None]], "note": "\u00e9 \u2603"}).encode("utf-8"),
                PUBLISH[1]: b'{"state":{"reported":{"k":null}}}', PUBLISH[2]: bytes(range(256)), PUBLISH[3]: b""}
        for topic in PUBLISH:
            r = d.publish(topic, sent[topic])
            assert r["ok"], (topic, r)
        assert wait_until(lambda: len(obs.messages) >= 4)
        assert obs.messages == [(t, sent[t]) for t in PUBLISH]          # the exact bytes, an empty payload and every byte value among them
        assert inbound() == [("d0", t, len(sent[t])) for t in PUBLISH] and connects()[0][:4] == (THING, "p2", "c1", "k60")
        # the other way: the exact bytes of a message on each subscribed topic reach the callback, as bytes
        for i, topic in enumerate(SUBSCRIBE):
            observer_publish(topic, b'{"state":{"n":%d},"raw":"' % i + bytes([0x7f, 0x01]) + b'"}')
        got = wait_until(lambda: (lambda r: r if len(r["messages"]) >= len(SUBSCRIBE) else None)(d.ask(op="state")))
        assert sorted(got["messages"]) == sorted([t, (b'{"state":{"n":%d},"raw":"' % i + bytes([0x7f, 0x01]) + b'"}').hex(), "bytes"]
                                                 for i, t in enumerate(SUBSCRIBE))
        # the device's topics and no other: the ACL made from topics.py denied nothing
        assert not [ln for ln in broker_log() if "Denied PUBLISH from %s" % THING in ln]
        assert d.ask(op="close")["ok"]
    finally:
        rc, err = d.end()
        obs.close()
    assert (rc, err) == (0, "")


def test_with_the_broker_paused_a_publish_times_out_and_does_not_hang_and_is_not_sent_a_second_time(image, pki, network, parts, tmp_path):
    """Case 1 of uplink_aws.py's docstring: written to a far end that stays silent. The SDK fails it after its operation
    time-out and forgets it. It had been written, so the broker reads it when it goes on: a publish reported as failed
    may have arrived (the limiter counts it as if it had). It is not sent again."""
    L = parts.limits
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open()
    try:
        assert d.publish(TELEMETRY, b"before").get("ok")
        docker("pause", BROKER)
        try:
            r = d.publish(TELEMETRY, b"while-paused!")
        finally:
            docker("unpause", BROKER)
        assert r["ok"] is False and r["error"] == "UplinkError"
        assert L.OPERATION_TIMEOUT_S - 1 <= r["took_s"] <= L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S + 1          # it came back: no hang
        assert r["counters"]["undone"] == 0 and r["counters"]["given_up"] == 0          # the SDK itself said so: the connection is kept
        assert wait_until(lambda: len(inbound()) >= 2)
        r = d.publish(TELEMETRY, b"after-the-pause")
        assert r["ok"] and r["counters"]["opened"] == 1
        time.sleep(2.0)
        assert inbound() == [("d0", TELEMETRY, 6), ("d0", TELEMETRY, 13), ("d0", TELEMETRY, 15)]          # each once, none with DUP
        assert len(connects()) == 1
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")


def test_nothing_reported_as_failed_arrives_after_the_broker_is_back_and_the_next_connection_is_a_new_clean_one(image, pki, network, parts,
                                                                                                            tmp_path):
    """The binding hand-off, at the real SDK and a real broker. The broker dies with a publish in flight; a publish is
    made while it is away; it comes back. The SDK's own connection must not come back by itself, nothing of the two
    failed publishes may arrive, and no PUBLISH may carry the DUP flag. The next publish then opens a new connection,
    clean again, with its subscriptions, and on_resumed is called.
    What keeps the SDK's own connection away is THE CHOICE, c: the uplink is told of the loss by the SDK's interrupted
    callback (nothing is deferred here) and disconnects from inside it, which ends the SDK's reconnecting. The SDK's own
    reconnect timer is HANDOFF_HOLD_S seconds in the driver's process, so that its first two attempts (that long after
    the loss, and twice that) fall inside the wait below. At the shipped hour no wait of a test reaches them, the broker
    logs no CONNECT of the SDK's with or without the callback's disconnect, and an empty `by_itself` could not tell the
    two apart. The stage is checked: on a machine too slow to have the broker back before the SDK's first attempt the
    test fails and says so, it does not pass for nothing."""
    L = parts.limits
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(SUBSCRIBE, {"SDK_RECONNECT_HOLD_S": HANDOFF_HOLD_S})
    obs: Optional[Observer] = None
    try:
        # The scenario first, whole; then what it showed, the wire before everything else.
        first = d.publish(TELEMETRY, b"one")
        # in flight: the broker is paused, the publish is written, and the broker is killed before it can answer
        docker("pause", BROKER)
        d.send(op="publish", topic=TELEMETRY, hex=b"in-flight-at-the-kill".hex())
        time.sleep(1.5)
        docker("kill", BROKER)
        t_kill = time.monotonic()
        in_flight = d.answer()
        lost = wait_until(lambda: (lambda st: st if st["counters"]["lost"] >= 1 else None)(d.ask(op="state")), 10)
        # while the broker is away
        away = d.publish(TELEMETRY, b"made-while-the-broker-was-away")
        docker("start", BROKER)
        back = wait_until(lambda: sum("mosquitto version 2.0.22 running" in ln for ln in broker_log()) >= 2)
        t_back = time.monotonic() - t_kill
        # well past the SDK's own first two attempts: HANDOFF_HOLD_S and twice that after the loss (the SDK's timer, set above)
        time.sleep(max(0.0, t_kill + 2 * HANDOFF_HOLD_S + 4.0 - time.monotonic()))
        by_itself = connects()[1:]
        before_next = d.ask(op="state")
        obs = Observer()
        second = d.publish(TELEMETRY, b"two")          # the back-off is over: this publish opens the new connection and goes out on it
        wait_until(lambda: obs.on(TELEMETRY))
        observer_publish(SUBSCRIBE[2], b'{"state":{"rate_hz":10}}')          # its subscriptions are back: this reaches the callback
        got = wait_until(lambda: (lambda st: st if st["messages"] else None)(d.ask(op="state")), 10)
        time.sleep(2.0)
        received, seen = inbound(), list(obs.on(TELEMETRY))
        # the stage was set as the docstring has it (a machine too slow for it fails here, by name): the broker was back
        # before the SDK's first attempt would have come, so that an attempt of its own would have found it
        assert back and t_back < HANDOFF_HOLD_S - 1.0, "the stage was not set in time: the broker was back %.1f s after the loss" % t_back
        # Everything the broker ever received from the device: `one` before the kill and `two` after its return. The
        # one in flight died with the paused broker (never read); neither failed publish arrived later; nothing has DUP.
        assert received == [("d0", TELEMETRY, 3), ("d0", TELEMETRY, 3)], "the broker received %s" % (received,)
        assert seen == [b"two"], seen
        # no CONNECT but the uplink's own, although the SDK's timer ran out twice with the broker up: the connection was given
        # up from the interrupted callback, which ended the SDK's reconnecting
        assert by_itself == [], "the SDK's own connection came back by itself: %s" % (by_itself,)
        assert first["ok"]
        assert in_flight["ok"] is False and in_flight["error"] == "UplinkError", in_flight
        assert in_flight["took_s"] < L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S + 1
        assert lost and lost["counters"]["lost"] == 1 and lost["counters"]["given_up"] == 1, lost          # given up from the SDK's callback
        # refused at once, and not handed to the SDK (its queue would send it later)
        assert away["ok"] is False and away["took_s"] < 3.0 and away["counters"]["opened"] == 1 and away["counters"]["undone"] == 0, away
        assert before_next["counters"]["resumed_by_sdk"] == 0 and before_next["counters"]["opened"] == 1 and before_next["resumed"] == 0
        assert second["ok"] and second["counters"]["opened"] == 2 and second["resumed"] == 1, second
        assert connects() == [(THING, "p2", "c1", "k60", THING)] * 2          # the certificate's CN as the user: this flavour's rule
        assert got and got["messages"] == [[SUBSCRIBE[2], b'{"state":{"rate_hz":10}}'.hex(), "bytes"]]
        subs = [ln for ln in broker_log() if ln.startswith("%s 1 $aws/" % THING)]
        assert sorted(ln.split(" ", 2)[2] for ln in subs) == sorted(SUBSCRIBE * 2)          # five subscriptions on each connection
        d.ask(op="close")
    finally:
        rc, err = d.end()
        if obs is not None:
            obs.close()
    assert (rc, err) == (0, "")


def test_a_publish_handed_to_a_connection_the_sdk_knows_is_lost_never_goes_out_on_a_connection_the_uplink_did_not_open(image, pki, network,
                                                                                                                  parts, tmp_path):
    """The hard review's wire run g2 (2026-10-08), at the real SDK and a real broker. THE CHOICE, c, of uplink_aws.py
    gives a lost connection up from the SDK's interrupted callback; here that callback reaches the uplink DEFER_S late
    (the driver hands it on from another thread, so the SDK's own event loop is not held up). In between a publish is
    made: the uplink believes the connection up, the SDK's connection is down, the SDK queues it. With the SDK's own
    reconnect timer at its default (RECONNECT_MIN_S, which the uplink handed it before), a reconnect could write
    its queue on the CONNACK before on_connection_resumed: a publish reported as failed could arrive on a
    connection the uplink never opened. The broker is back before that moment, paused across
    it and going on before the uplink's own wait for the publish ends, as in that run.
    What must hold: the SDK makes no connection of its own (the broker accepts as many CONNECTs as the uplink opened),
    every PUBLISH the broker received was acknowledged to the caller, and the raced publish is not among them. The
    uplink's own wait (`undone`) is what gives the connection up; the next publish opens the next one; and when the
    late word of the loss arrives at last, the connection then in use is untouched by it.
    The stage is checked too (the staging asserts below): on a machine too slow to set it in time the test fails and
    says so, it does not pass for nothing."""
    L = parts.limits
    wait_s = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S
    raced_payload = b"raced: handed over while the SDK knew of the loss"
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST))
    try:
        assert d.ask(op="build")["ok"]
        refused = d.ask(op="defer", seconds=10000)          # the driver holds a loss back for a bounded time and no longer
        assert refused["ok"] is False and refused["error"] == "no such delay", refused
        assert d.ask(op="defer", seconds=DEFER_S)["ok"]
        for cmd in [dict(op="connect")] + [dict(op="subscribe", topic=t) for t in SUBSCRIBE]:
            r = d.ask(**cmd)
            assert r["ok"], r
        # The scenario first, whole; then what it showed, the wire before everything else.
        first = d.publish(TELEMETRY, b"one")
        docker("kill", BROKER)          # the forced loss
        known = wait_until(lambda: (lambda st: st if st["sdk_lost"] >= 1 else None)(d.ask(op="state")), 15, poll=0.1)
        t_loss = time.monotonic()          # the SDK knows (and has known for a poll at the most); the uplink does not
        docker("start", BROKER)
        back = wait_until(lambda: sum("mosquitto version 2.0.22 running" in ln for ln in broker_log()) >= 2, poll=0.1)
        t_back = time.monotonic() - t_loss
        d.send(op="publish", topic=TELEMETRY, hex=raced_payload.hex())          # THE RACE: handed to the SDK, whose connection is down
        t_asked = time.monotonic() - t_loss
        time.sleep(max(0.0, t_loss + L.RECONNECT_MIN_S - 1.5 - time.monotonic()))
        docker("pause", BROKER)          # across the moment the SDK's default timer would make its own attempt
        t_paused = time.monotonic() - t_loss
        time.sleep(max(0.0, t_loss + L.RECONNECT_MIN_S + 1.0 - time.monotonic()))
        docker("unpause", BROKER)          # ... and going on before the uplink's own wait for the raced publish ends
        t_unpaused = time.monotonic() - t_loss
        raced = d.answer()
        time.sleep(max(0.0, t_loss + 2 * L.RECONNECT_MIN_S + 6 - time.monotonic()))          # well past the default timer's first attempts
        by_itself = connects()[1:]
        before_next = d.ask(op="state")
        second = d.publish(TELEMETRY, b"two")          # the uplink's own back-off is over: this opens the next connection
        told = wait_until(lambda: (lambda st: st if st["counters"]["lost"] >= 1 else None)(d.ask(op="state")), DEFER_S + 10)
        third = d.publish(TELEMETRY, b"three")          # after the late word of the loss: on the connection then in use
        time.sleep(2.0)
        end = d.ask(op="state")
        received, accepted = inbound(), connects()
        # the stage was set as the run had it (a machine too slow for it fails here, by name)
        assert known and back and first["ok"], (known, back, first)
        staged = {"back": t_back, "asked": t_asked, "paused": t_paused, "unpaused": t_unpaused}
        assert t_back < t_asked < t_paused < L.RECONNECT_MIN_S - 0.5 and L.RECONNECT_MIN_S + 0.5 < t_unpaused < t_asked + wait_s - 0.5, \
            "the stage was not set in time (seconds after the loss): %s" % staged
        # the wire: one, two and three, each once, none with DUP, and never the raced publish
        assert received == [("d0", TELEMETRY, 3), ("d0", TELEMETRY, 3), ("d0", TELEMETRY, 5)], \
            "the broker received %s (the raced publish is %d bytes)" % (received, len(raced_payload))
        assert by_itself == [], "the SDK made a connection of its own: %s" % (by_itself,)
        # no CONNECT but the uplink's own: the first, and the one the publish after the back-off opened
        assert accepted == [(THING, "p2", "c1", "k60", THING)] * 2 and end["counters"]["opened"] == 2, (accepted, end)
        # the raced publish: reported as failed by the uplink's own wait, which gave the connection up; the SDK said nothing
        assert raced["ok"] is False and raced["error"] == "UplinkError" and wait_s - 1 <= raced["took_s"] <= wait_s + 2, raced
        assert (raced["counters"]["undone"], raced["counters"]["given_up"], raced["counters"]["lost"]) == (1, 1, 0), raced
        assert before_next["counters"]["resumed_by_sdk"] == 0 and before_next["counters"]["opened"] == 1 and before_next["resumed"] == 0
        assert second["ok"] and second["counters"]["opened"] == 2 and second["resumed"] == 1, second
        # the late word of the loss: counted, and the connection in use is not given up for it
        assert told and told["counters"]["lost"] == 1 and told["counters"]["given_up"] == 1, told
        assert third["ok"] and third["counters"]["opened"] == 2, third
        assert (end["counters"]["resumed_by_sdk"], end["counters"]["late"], end["counters"]["callback_errors"], end["sdk_lost"]) == (0, 0, 0, 1), end
        subs = [ln for ln in broker_log() if ln.startswith("%s 1 $aws/" % THING)]
        assert sorted(ln.split(" ", 2)[2] for ln in subs) == sorted(SUBSCRIBE * 2)          # five subscriptions on each of the two
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    # what this run showed, for the reader of a log (counts and the stage's own seconds; none is a timing)
    print("WP345fix the SDK's own reconnect: the uplink was told of the loss %.0f s late; the raced publish (%d bytes) came back failed "
          "after %.1f s (undone %d); the broker accepted %d CONNECT of the device (the uplink opened %d) and received %d PUBLISH, none of "
          "%d bytes; resumed_by_sdk %d. The stage, seconds after the loss: broker back %.1f, publish asked %.1f, paused %.1f, unpaused %.1f"
          % (DEFER_S, len(raced_payload), raced["took_s"], raced["counters"]["undone"], len(accepted), end["counters"]["opened"],
             len(received), len(raced_payload), end["counters"]["resumed_by_sdk"], t_back, t_asked, t_paused, t_unpaused))


def _lose_the_broker_unseen(d: "Driver") -> Tuple[Any, float, Any]:
    """The broker is killed and started again. The SDK knows of the loss (the driver counted its callback); the uplink
    is not told. Returns the driver's state when the SDK knew, that moment on this test's clock (the SDK has known for
    a poll at the most), and whether the broker is back."""
    docker("kill", BROKER)
    known = wait_until(lambda: (lambda st: st if st["sdk_lost"] >= 1 else None)(d.ask(op="state")), 15, poll=0.1)
    t_loss = time.monotonic()
    docker("start", BROKER)
    back = wait_until(lambda: sum("mosquitto version 2.0.22 running" in ln for ln in broker_log()) >= 2, poll=0.1)
    return known, t_loss, back


def test_with_the_uplink_never_told_of_a_loss_a_publish_in_the_last_seconds_before_the_sdks_own_reconnect_is_not_handed_over(
        image, pki, network, parts, tmp_path):
    """THE CHOICE, g, of uplink_aws.py at the real SDK and a real broker: the binding hand-off (a publish reported as
    failed is never sent later) without the SDK's callback. The uplink is NEVER told of the loss (the driver holds the
    SDK's word back past the end of the test), the broker is back at once, and the SDK is left to make its own
    reconnect when its timer says: a hold of HOLD_S seconds in this process, because no test waits the shipped hour
    out, and a life of LIFE_S. A publish is made in the last seconds before that reconnect: the window the hold alone
    left open, in which an uplink that believes the connection up hands the publish to the SDK, the SDK queues it,
    reconnects, WRITES ITS QUEUE and only then calls back.
    What must hold: that publish is refused before the SDK is asked (the connection showed no life for LIFE_S), the
    connection is given up, the SDK makes NO connection of its own although its timer runs out with the broker up,
    and the broker never receives the publish. The next publish opens the next connection.
    The stage is checked (the staging asserts below): on a machine too slow to set it the test fails and says so."""
    L = parts.limits
    wait_s = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S
    raced_payload = b"raced: in the last seconds before the SDK's own reconnect"
    assert 2 * (LIFE_S + wait_s) <= HOLD_S and LIFE_S + 5 < HOLD_S - wait_s          # the relation limits.py's test holds for the shipped values
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST))
    try:
        assert d.ask(op="build")["ok"]
        for name, value in (("SDK_RECONNECT_HOLD_S", HOLD_S), ("LINK_LIFE_MAX_S", LIFE_S)):
            assert d.ask(op="limit", name=name, value=value)["ok"], name
        assert d.ask(op="defer", seconds=NEVER_S)["ok"]
        for cmd in [dict(op="connect")] + [dict(op="subscribe", topic=t) for t in SUBSCRIBE]:
            r = d.ask(**cmd)
            assert r["ok"], r
        # The scenario first, whole; then what it showed, the wire before everything else.
        first = d.publish(TELEMETRY, b"one")          # acknowledged: the connection's last sign of life
        known, t_loss, back = _lose_the_broker_unseen(d)
        t_back = time.monotonic() - t_loss
        time.sleep(max(0.0, t_loss + HOLD_S - 4.0 - time.monotonic()))
        t_asked = time.monotonic() - t_loss
        raced = d.publish(TELEMETRY, raced_payload)          # THE WINDOW: seconds before the SDK's own attempt, the broker up
        time.sleep(max(0.0, t_loss + HOLD_S + 8.0 - time.monotonic()))          # well past the moment the SDK's timer says
        by_itself = connects()[1:]
        before_next = d.ask(op="state")
        second = d.publish(TELEMETRY, b"two")          # the uplink's own back-off is over: this opens the next connection
        time.sleep(2.0)
        end = d.ask(op="state")
        received, accepted = inbound(), connects()
        # the stage was set (a machine too slow for it fails here, by name)
        assert known and back and first["ok"], (known, back, first)
        assert t_back < HOLD_S - wait_s < t_asked < HOLD_S - 1.0, \
            "the stage was not set in time (seconds after the loss): back %.1f, asked %.1f" % (t_back, t_asked)
        # THE WIRE: one and two, each once, none with DUP, and never the raced publish
        assert received == [("d0", TELEMETRY, 3), ("d0", TELEMETRY, 3)], \
            "the broker received %s (the raced publish is %d bytes)" % (received, len(raced_payload))
        assert by_itself == [], "the SDK made a connection of its own: %s" % (by_itself,)
        assert accepted == [(THING, "p2", "c1", "k60", THING)] * 2 and end["counters"]["opened"] == 2, (accepted, end)
        # the raced publish: refused at once, before the SDK was asked; the connection given up for showing no life
        assert raced["ok"] is False and raced["error"] == "UplinkError" and raced["took_s"] < 2.0, raced
        c = raced["counters"]
        assert (c["stale"], c["given_up"], c["undone"], c["lost"], c["not_connected"]) == (1, 1, 0, 0, 1), raced
        assert before_next["counters"]["resumed_by_sdk"] == 0 and before_next["counters"]["opened"] == 1 and before_next["resumed"] == 0
        assert second["ok"] and second["counters"]["opened"] == 2 and second["resumed"] == 1, second
        # the uplink was never told, to the end: the SDK reported one loss, the uplink counted none
        assert (end["sdk_lost"], end["counters"]["lost"], end["counters"]["resumed_by_sdk"], end["counters"]["late"],
                end["counters"]["callback_errors"]) == (1, 0, 0, 0, 0), end
        subs = [ln for ln in broker_log() if ln.startswith("%s 1 $aws/" % THING)]
        assert sorted(ln.split(" ", 2)[2] for ln in subs) == sorted(SUBSCRIBE * 2)          # five subscriptions on each of the two
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    # what this run showed, for the reader of a log (counts and the stage's own seconds; none is a timing)
    print("WP345fix g, the uplink never told: hold %d s and life %d s in the driver's process; the publish asked %.1f s after the loss "
          "(%d bytes) came back failed after %.1f s (stale %d, undone %d); the broker accepted %d CONNECT of the device (the uplink "
          "opened %d) and received %d PUBLISH, none of %d bytes; the SDK reported %d loss, the uplink was told of %d; resumed_by_sdk %d"
          % (HOLD_S, LIFE_S, t_asked, len(raced_payload), raced["took_s"], c["stale"], c["undone"], len(accepted), end["counters"]["opened"],
             len(received), len(raced_payload), end["sdk_lost"], end["counters"]["lost"], end["counters"]["resumed_by_sdk"]))


def test_the_sdk_left_alone_makes_its_own_reconnect_when_its_timer_says_and_not_before_and_has_nothing_to_send(
        image, pki, network, parts, tmp_path):
    """What THE CHOICE, g, rests on, seen at the real SDK: its own first reconnect attempt comes no sooner after a
    loss than the timer it was given (here ALONE_HOLD_S seconds, in the driver's process; the shipped hold is an
    hour, which no test waits out). The uplink is never told of the loss and nothing is handed over, so nothing gives
    the connection up: the broker, back at once, logs no CONNECT of the device until the timer has run, then one.
    The SDK comes back with an empty queue (nothing arrives), the uplink disconnects that connection from the SDK's
    resumed callback and counts it, and the next publish opens a connection of the uplink's own.
    "Not before" is read off the broker's log against this test's clock, which learns of the loss a poll after the
    SDK does: no CONNECT of the device up to two seconds before the timer's end as counted here, then one. A bound
    of two seconds, no timing."""
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST))
    try:
        assert d.ask(op="build")["ok"]
        assert d.ask(op="limit", name="SDK_RECONNECT_HOLD_S", value=ALONE_HOLD_S)["ok"]
        assert d.ask(op="defer", seconds=NEVER_S)["ok"]
        for cmd in [dict(op="connect")] + [dict(op="subscribe", topic=t) for t in SUBSCRIBE]:
            r = d.ask(**cmd)
            assert r["ok"], r
        first = d.publish(TELEMETRY, b"one")
        known, t_loss, back = _lose_the_broker_unseen(d)
        t_back = time.monotonic() - t_loss
        early: List[Tuple[float, int]] = []          # (seconds after the loss, CONNECTs of the device so far), while the timer runs
        while time.monotonic() < t_loss + ALONE_HOLD_S - 2.0:
            early.append((round(time.monotonic() - t_loss, 1), len(connects())))
            time.sleep(0.5)
        came = wait_until(lambda: len(connects()) >= 2, 12.0, poll=0.2)
        t_came = time.monotonic() - t_loss
        gone = wait_until(lambda: (lambda st: st if st["counters"]["resumed_by_sdk"] >= 1 else None)(d.ask(op="state")), 10, poll=0.2)
        time.sleep(max(0.0, parts.limits.RECONNECT_MIN_S + 1.0))          # the uplink's own back-off after that give-up
        second = d.publish(TELEMETRY, b"two")
        time.sleep(2.0)
        end = d.ask(op="state")
        received, accepted, log = inbound(), connects(), broker_log()
        assert known and back and first["ok"] and t_back < ALONE_HOLD_S - 4.0, (known, back, first, t_back)
        # not before: no CONNECT of the device from the loss to two seconds before the timer's end
        assert len(early) >= 5 and {n for _t, n in early} == {1}, "the SDK reconnected before its timer said: %s" % early
        # and then it does: the timer is what kept it (a hold is a delay, never a switch)
        assert came and ALONE_HOLD_S - 2.0 <= t_came <= ALONE_HOLD_S + 12.0, (came, t_came)
        # it came back with nothing to send, and the uplink disconnected it again: never used
        assert gone and (gone["counters"]["resumed_by_sdk"], gone["counters"]["given_up"], gone["counters"]["lost"]) == (1, 1, 0), gone
        assert received == [("d0", TELEMETRY, 3), ("d0", TELEMETRY, 3)], received          # one, and two; nothing else, ever
        # three CONNECTs under the thing's client id: the uplink's, the SDK's own, the uplink's next
        assert accepted == [(THING, "p2", "c1", "k60", THING)] * 3 and end["counters"]["opened"] == 2, (accepted, end)
        assert second["ok"] and second["resumed"] == 1 and end["counters"]["stale"] == 0 and end["sdk_lost"] == 1, (second, end)
        subs = [ln for ln in log if ln.startswith("%s 1 $aws/" % THING)]
        assert sorted(ln.split(" ", 2)[2] for ln in subs) == sorted(SUBSCRIBE * 2)          # the SDK's own connection made none
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    print("WP345fix the SDK left alone: a timer of %d s in the driver's process; %d looks at the broker's log from %.1f to %.1f s after "
          "the loss found 1 CONNECT of the device each; the second was seen %.1f s after the loss; resumed_by_sdk %d; the broker "
          "received %d PUBLISH (one and two) and accepted %d CONNECT (the uplink opened %d)"
          % (ALONE_HOLD_S, len(early), early[0][0], early[-1][0], t_came, end["counters"]["resumed_by_sdk"], len(received), len(accepted),
             end["counters"]["opened"]))


def test_a_publish_the_sdk_queued_and_the_uplinks_own_wait_gave_up_is_not_written_when_the_sdks_timer_runs_out(
        image, pki, network, parts, tmp_path):
    """THE CHOICE, d, and the second thing g rests on (a disconnect on a connection the SDK is keeping for its own
    reconnect ends that reconnecting, and what it holds for it is never written), at the real SDK and a real broker:
    case 3 of uplink_aws.py's docstring, with the SDK's timer run out. The uplink is NEVER told of the loss (the driver
    holds the SDK's word back past the end of the test), the broker is back at once, and the SDK, which knows, waits for
    its timer (HOLD_S seconds in this process). A publish is made within the connection's life (LIFE_S): the uplink
    believes the connection up and hands it to the SDK, which QUEUES it and says nothing. The uplink's own wait for the
    answer ends (`undone`) and gives the connection up, which disconnects it in the SDK and ends the SDK's reconnecting,
    and with it the queue. Then the SDK's timer runs out with the broker up.
    What must hold: the SDK makes no connection of its own, the broker never receives that publish, and the next publish
    opens the next connection. (The same run with that give-up taken out is the one in which the SDK's timer brings it
    back, it writes its queue on the CONNACK and the broker receives the publish.)
    The stage is checked (the staging asserts below): the publish is handed over within the life, and the uplink's wait
    ends before the SDK's timer does; on a machine too slow for that the test fails and says so."""
    L = parts.limits
    wait_s = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S
    queued_payload = b"queued by the SDK: handed over while it knew of the loss; the uplink never told; then the SDK's timer runs out"
    assert 2 * (LIFE_S + wait_s) <= HOLD_S          # the relation limits.py's test holds for the shipped values
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(
        SUBSCRIBE, {"SDK_RECONNECT_HOLD_S": HOLD_S, "LINK_LIFE_MAX_S": LIFE_S}, defer=NEVER_S)
    try:
        # The scenario first, whole; then what it showed, the wire before everything else.
        t_life = time.monotonic()          # the connection's life begins here, at the latest: the next publish is acknowledged
        first = d.publish(TELEMETRY, b"one")
        known, t_loss, back = _lose_the_broker_unseen(d)
        t_back = time.monotonic() - t_loss
        t_asked = time.monotonic() - t_life
        queued = d.publish(TELEMETRY, queued_payload)          # within the life: handed to the SDK, whose connection is down
        t_answered = time.monotonic() - t_loss
        time.sleep(max(0.0, t_loss + HOLD_S + 8.0 - time.monotonic()))          # well past the moment the SDK's timer says
        by_itself = connects()[1:]
        received_before = inbound()
        before_next = d.ask(op="state")
        second = d.publish(TELEMETRY, b"two")          # the uplink's own back-off is over: this opens the next connection
        time.sleep(2.0)
        end = d.ask(op="state")
        received, accepted = inbound(), connects()
        # the stage was set (a machine too slow for it fails here, by name)
        assert known and back and first["ok"], (known, back, first)
        staged = {"back": t_back, "asked": t_asked, "answered": t_answered}
        assert t_back < t_asked < LIFE_S - 2.0 and t_answered < HOLD_S - 1.0, \
            "the stage was not set in time (seconds after the loss, the asking after the connection's last sign of life): %s" % staged
        # THE WIRE: one and two, each once, none with DUP, and never the queued publish; the SDK's timer ran out with the broker up
        assert received_before == [("d0", TELEMETRY, 3)], \
            "the broker had received %s before the next publish (the queued publish is %d bytes)" % (received_before, len(queued_payload))
        assert received == [("d0", TELEMETRY, 3), ("d0", TELEMETRY, 3)], \
            "the broker received %s (the queued publish is %d bytes)" % (received, len(queued_payload))
        assert by_itself == [], "the SDK made a connection of its own: %s" % (by_itself,)
        assert accepted == [(THING, "p2", "c1", "k60", THING)] * 2 and end["counters"]["opened"] == 2, (accepted, end)
        # the queued publish: handed over (not found stale), the SDK said nothing, the uplink's own wait gave the connection up
        assert queued["ok"] is False and queued["error"] == "UplinkError" and wait_s - 1 <= queued["took_s"] <= wait_s + 2, queued
        c = queued["counters"]
        assert (c["stale"], c["undone"], c["given_up"], c["lost"], c["not_connected"]) == (0, 1, 1, 0, 0), queued
        assert before_next["counters"]["resumed_by_sdk"] == 0 and before_next["counters"]["opened"] == 1 and before_next["resumed"] == 0
        assert second["ok"] and second["counters"]["opened"] == 2 and second["resumed"] == 1, second
        # the uplink was never told, to the end: the SDK reported one loss, the uplink counted none
        assert (end["sdk_lost"], end["counters"]["lost"], end["counters"]["resumed_by_sdk"], end["counters"]["late"],
                end["counters"]["callback_errors"]) == (1, 0, 0, 0, 0), end
        subs = [ln for ln in broker_log() if ln.startswith("%s 1 $aws/" % THING)]
        assert sorted(ln.split(" ", 2)[2] for ln in subs) == sorted(SUBSCRIBE * 2)          # five subscriptions on each of the two
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    # what this run showed, for the reader of a log (counts and the stage's own seconds; none is a timing)
    print("WP3 case 3 past the SDK's timer: hold %d s and life %d s in the driver's process; the uplink never told (the SDK reported %d "
          "loss, the uplink counted %d); the publish handed over %.1f s after the connection's last sign of life (%d bytes) came back "
          "failed after %.1f s (undone %d); the SDK's timer ran out %d s after the loss with the broker up; the broker accepted %d CONNECT "
          "of the device (the uplink opened %d) and received %d PUBLISH, none of %d bytes; resumed_by_sdk %d"
          % (HOLD_S, LIFE_S, end["sdk_lost"], end["counters"]["lost"], t_asked, len(queued_payload), queued["took_s"], c["undone"], HOLD_S,
             len(accepted), end["counters"]["opened"], len(received), len(queued_payload), end["counters"]["resumed_by_sdk"]))


def _the_sdk_comes_back_by_itself(d: "Driver", parts: Any, hold: int, t_kill: float) -> Dict[str, Any]:
    """What the two tests of a request the SDK itself failed share, once the broker has been killed (at t_kill on this
    test's clock) with that request already failed: the SDK knows of the loss (the driver counted its callback); the
    uplink is NEVER told of it (the driver holds the SDK's word back past the end of the test); the broker is started
    again at once, and the SDK is left to come back at its timer, `hold` seconds after the loss. When it has, and the
    uplink has disconnected that connection again (resumed_by_sdk), the uplink's back-off is waited out, one more
    publish opens a connection of the uplink's own, and what the broker saw is returned: the stage, and the wire."""
    known = wait_until(lambda: (lambda st: st if st["sdk_lost"] >= 1 else None)(d.ask(op="state")), 15, poll=0.1)
    docker("start", BROKER)
    back = wait_until(lambda: sum("mosquitto version 2.0.22 running" in ln for ln in broker_log()) >= 2, poll=0.1)
    t_back = time.monotonic() - t_kill
    came = wait_until(lambda: len(connects()) >= 2, hold + 14.0, poll=0.2)
    t_came = time.monotonic() - t_kill
    gone = wait_until(lambda: (lambda st: st if st["counters"]["resumed_by_sdk"] >= 1 else None)(d.ask(op="state")), 10, poll=0.2)
    # whatever the SDK would write on its own connection has had its time; the uplink's back-off after that give-up is over
    time.sleep(parts.limits.RECONNECT_MIN_S + 1.0)
    after_return = (inbound(), connects())
    second = d.publish(TELEMETRY, b"two")
    time.sleep(2.0)
    end = d.ask(op="state")
    subs = [ln for ln in broker_log() if ln.startswith("%s 1 $aws/" % THING)]
    return dict(known=known, back=back, t_back=t_back, came=came, t_came=t_came, gone=gone, after_return=after_return, second=second,
                end=end, received=inbound(), accepted=connects(), subscribed=sorted(ln.split(" ", 2)[2] for ln in subs))


def _assert_the_sdks_own_connection_wrote_nothing(f: Dict[str, Any], first: Dict[str, Any], failed: Dict[str, Any], hold: int,
                                                  failed_bytes: int) -> None:
    """The stage and the wire of _the_sdk_comes_back_by_itself, for a request the SDK failed on its own (`failed` is the
    uplink's answer to it, and the SDK said so: the uplink gave nothing up)."""
    one_publish = ("d0", TELEMETRY, 3)
    # the stage: the broker was back well before the SDK's timer, and the SDK DID come back by itself, not before its
    # timer says -- the case this is about, which a test that never saw it would show nothing of
    assert f["known"] and f["back"] and first["ok"], (f["known"], f["back"], first)
    assert f["t_back"] < hold - 3.0, "the stage was not set in time: the broker was back %.1f s after the loss" % f["t_back"]
    assert f["came"] and f["gone"], "the SDK did not come back by itself: %s" % (f["gone"],)
    assert hold - 2.0 <= f["t_came"] <= hold + 12.0, f["t_came"]
    assert failed["ok"] is False and failed["error"] == "UplinkError", failed
    assert failed["counters"]["undone"] == 0 and failed["counters"]["given_up"] == 0 and failed["counters"]["lost"] == 0, failed
    # THE WIRE: on the SDK's own connection nothing is written, and the failed publish never arrives
    received_after, accepted_after = f["after_return"]
    assert received_after == [one_publish], \
        "the broker received %s after the SDK came back (the failed publish is %d bytes)" % (received_after, failed_bytes)
    assert len(accepted_after) == 2, accepted_after          # the uplink's, and the SDK's own
    assert f["received"] == [one_publish, one_publish], "the broker received %s (the failed publish is %d bytes)" % (f["received"], failed_bytes)
    assert f["accepted"] == [(THING, "p2", "c1", "k60", THING)] * 3, f["accepted"]
    # the SDK's own connection is the uplink's no more: counted for the record, disconnected, no subscription made on it
    end = f["end"]
    assert f["second"]["ok"] and f["second"]["counters"]["opened"] == 2 and f["second"]["resumed"] == 1, f["second"]
    assert (end["counters"]["opened"], end["counters"]["resumed_by_sdk"], end["counters"]["given_up"], end["counters"]["lost"],
            end["counters"]["undone"], end["counters"]["stale"], end["counters"]["late"], end["counters"]["callback_errors"],
            end["sdk_lost"]) == (2, 1, 1, 0, 0, 0, 0, 0, 1), end
    assert f["subscribed"] == sorted(SUBSCRIBE * 2)          # five subscriptions on each of the uplink's two connections, none on the SDK's


def test_a_publish_in_flight_at_a_loss_is_not_written_when_the_sdk_comes_back_by_itself(image, pki, network, parts, tmp_path):
    """Case 2 of uplink_aws.py's docstring (clean_session=True), and the third thing g rests on (a request the SDK failed
    is not written later), at the real SDK and a real broker, with the SDK really coming back. A publish is written to
    the paused broker and the broker is killed 1.5 s later, before it has read it: the SDK cancels the publish and fails
    it at the loss. The uplink is NEVER told of the loss and the broker is started again at once, so the SDK comes back at
    its timer (ALONE_HOLD_S seconds in this process) with the connection of its own: it makes its CONNECT, the uplink
    disconnects it again from the SDK's resumed callback, and the broker never receives the publish: the SDK's own
    connection writes nothing, and no PUBLISH carries the DUP flag. The next publish opens a connection of the uplink's
    own. Not shown here: what the SDK does with clean_session=False (the driver has no switch for it; the module's
    docstring says it sends such a publish again, DUP set, and no test of this file repeats that)."""
    L = parts.limits
    payload = b"in flight at the kill: the uplink never told; then the SDK comes back by itself"
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(SUBSCRIBE, {"SDK_RECONNECT_HOLD_S": ALONE_HOLD_S}, defer=NEVER_S)
    try:
        # The scenario first, whole; then what it showed, the wire before everything else.
        first = d.publish(TELEMETRY, b"one")
        docker("pause", BROKER)
        d.send(op="publish", topic=TELEMETRY, hex=payload.hex())
        time.sleep(1.5)
        docker("kill", BROKER)
        t_kill = time.monotonic()
        failed = d.answer()          # failed by the SDK at the loss, 1.5 s after it was written
        f = _the_sdk_comes_back_by_itself(d, parts, ALONE_HOLD_S, t_kill)
        _assert_the_sdks_own_connection_wrote_nothing(f, first, failed, ALONE_HOLD_S, len(payload))
        assert failed["took_s"] < L.OPERATION_TIMEOUT_S, failed          # cancelled at the loss, not by the SDK's own time-out
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    print("WP3 case 2, the SDK back by itself: a publish in flight at the kill (%d bytes) came back failed after %.1f s; the uplink never "
          "told; the SDK made its own CONNECT %.1f s after the loss (a timer of %d s in the driver's process) and the uplink disconnected "
          "it (resumed_by_sdk %d); the broker accepted %d CONNECT of the device and received %d PUBLISH, none of %d bytes"
          % (len(payload), failed["took_s"], f["t_came"], ALONE_HOLD_S, f["end"]["counters"]["resumed_by_sdk"], len(f["accepted"]),
             len(f["received"]), len(payload)))


def test_a_publish_the_sdk_timed_out_is_not_written_when_the_sdk_comes_back_by_itself(image, pki, network, parts, tmp_path):
    """Case 1 of uplink_aws.py's docstring, and the third thing g rests on (a request the SDK failed is not written
    later), at the real SDK and a real broker, with the SDK really coming back. A publish is written to the paused broker,
    which stays silent: the SDK fails it after its operation time-out, and the uplink, told so by the SDK, keeps the
    connection. The broker is then killed, still paused, so that it never read the publish. The uplink is NEVER told of
    the loss and the broker is started again at once, so the SDK comes back at its timer (ALONE_HOLD_S seconds in this
    process): its own connection writes nothing, and the broker never receives the publish. The next publish opens a
    connection of the uplink's own."""
    L = parts.limits
    payload = b"timed out by the SDK; then the loss; the uplink never told; then the SDK comes back by itself"
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open(SUBSCRIBE, {"SDK_RECONNECT_HOLD_S": ALONE_HOLD_S}, defer=NEVER_S)
    try:
        # The scenario first, whole; then what it showed, the wire before everything else.
        first = d.publish(TELEMETRY, b"one")
        docker("pause", BROKER)
        failed = d.publish(TELEMETRY, payload)          # written to a far end that stays silent: failed by the SDK's own time-out
        docker("kill", BROKER)          # still paused: it never read that publish
        t_kill = time.monotonic()
        f = _the_sdk_comes_back_by_itself(d, parts, ALONE_HOLD_S, t_kill)
        _assert_the_sdks_own_connection_wrote_nothing(f, first, failed, ALONE_HOLD_S, len(payload))
        # failed by the SDK's own time-out: the uplink's wait is longer, and it gave nothing up (undone 0, in the helper's asserts)
        assert L.OPERATION_TIMEOUT_S - 1 <= failed["took_s"] <= L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S + 1, failed
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    print("WP3 case 1, the SDK back by itself: a publish the SDK timed out (%d bytes) came back failed after %.1f s with the connection "
          "kept; the broker was then killed and the uplink never told; the SDK made its own CONNECT %.1f s after the loss (a timer of %d s "
          "in the driver's process) and the uplink disconnected it (resumed_by_sdk %d); the broker accepted %d CONNECT of the device and "
          "received %d PUBLISH, none of %d bytes"
          % (len(payload), failed["took_s"], f["t_came"], ALONE_HOLD_S, f["end"]["counters"]["resumed_by_sdk"], len(f["accepted"]),
             len(f["received"]), len(payload)))


def test_a_connect_the_sdk_answers_late_is_disconnected_at_once_and_the_next_connection_is_not_closed_for_it(image, pki, network, parts,
                                                                                                          tmp_path):
    """THE CHOICE, f, of uplink_aws.py at the real SDK and a real broker. The broker is paused: its kernel still takes
    the TCP connection, and nothing answers the TLS handshake. The uplink stops waiting and reports the connect as
    failed; the SDK refuses to be disconnected while it is connecting, and goes on. The broker goes on before the SDK's
    own handshake wait is over, so the SDK completes the connect AFTER the uplink reported it as failed. That connection
    must be disconnected at once and never used; meanwhile no second connect may be asked for; and the next connection
    must find the client id free (the broker closes an older connection of a client id for a newer one).
    The uplink's wait is shortened here, in the driver's process only, to stage a connect that outlasts it.
    This checks the late-answer path, not a handshake duration with the shipped settings."""
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST))
    try:
        assert d.ask(op="build")["ok"] and d.ask(op="limit", name="CONNECT_WAIT_S", value=3.0)["ok"]
        # The scenario first, whole; then what it showed.
        docker("pause", BROKER)
        began = time.monotonic()
        try:
            first = d.ask(op="connect")          # given up by the uplink after its 3 s
            again = d.ask(op="connect")          # asked at once, while the SDK has not answered the first
            time.sleep(max(0.0, 5.0 - (time.monotonic() - began)))
        finally:
            docker("unpause", BROKER)          # about 5 s in: well inside the SDK's own handshake wait
        late = wait_until(lambda: (lambda st: st if st["counters"]["late"] >= 1 else None)(d.ask(op="state")), 15)
        said_goodbye = wait_until(lambda: [ln for ln in broker_log() if "Received DISCONNECT from %s" % THING in ln], 10)
        after_late = connects()
        second = d.ask(op="connect")          # the SDK has answered: a new connection
        published = d.publish(TELEMETRY, b"x")
        time.sleep(2.0)
        end = d.ask(op="state")
        log = broker_log()
        assert first["ok"] is False and first["error"] == "UplinkError" and 2.0 <= first["took_s"] <= 6.0, first
        assert (first["counters"]["opened"], first["counters"]["given_up"], first["counters"]["late"]) == (0, 1, 0), first
        # refused at once and without a second attempt: the SDK built and tried nothing more
        assert again["ok"] is False and again["took_s"] < 1.0 and again["counters"]["given_up"] == 1, again
        # the SDK's connect succeeded after the uplink had reported it as failed: the broker has the CONNECT ...
        assert late, "the SDK never answered the first connect with a connection: %s" % (d.ask(op="state"),)
        assert after_late == [(THING, "p2", "c1", "k60", THING)], after_late
        # ... and the uplink disconnected that connection at once: counted, never taken into use, and the broker has its DISCONNECT
        assert (late["counters"]["late"], late["counters"]["opened"], late["counters"]["lost"]) == (1, 0, 0), late
        assert said_goodbye, "the late connection was not disconnected: %s" % log[-15:]
        # the next connection found the client id free: the broker closed no older connection for it, and it was not lost
        assert second["ok"] and second["counters"]["opened"] == 1 and published["ok"], (second, published)
        taken_over = [ln for ln in log if "already connected" in ln]
        assert len(connects()) == 2 and not taken_over, taken_over
        goodbye = min(i for i, ln in enumerate(log) if "Received DISCONNECT from %s" % THING in ln)
        newer = [i for i, ln in enumerate(log) if (CONNECT_LINE.search(ln) or [None, None])[1] == THING][1]
        assert goodbye < newer          # the late connection was gone before the next CONNECT arrived
        assert inbound() == [("d0", TELEMETRY, 1)]          # one publish in all, on the connection the uplink opened
        assert (end["counters"]["opened"], end["counters"]["late"], end["counters"]["lost"], end["counters"]["resumed_by_sdk"],
                end["counters"]["callback_errors"]) == (1, 1, 0, 0, 0), end
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    # what this run showed, for the reader of a log (counts and the broker's own lines; the seconds are how long a call
    # blocked here and bound the test, they are no timing)
    print("WP3 late connect: the uplink gave the connect up after %.1f s (its wait here: 3 s) and refused a second one in %.2f s; the SDK "
          "then completed it: late %d, opened %d; the broker logged %d CONNECT of the device in all, %d DISCONNECT before the second "
          "CONNECT, %d line(s) of an older connection closed for a newer one, %d PUBLISH"
          % (first["took_s"], again["took_s"], end["counters"]["late"], end["counters"]["opened"], len(connects()),
             sum(1 for ln in log[:newer] if "Received DISCONNECT from %s" % THING in ln), len(taken_over), len(inbound())))


def test_the_sdk_gives_a_silent_handshake_up_by_itself_after_a_wait_of_its_own_that_the_uplink_cannot_set(image, pki, network, parts, tmp_path):
    """With the uplink's own wait made long in the driver's process, check that a silent handshake is eventually
    refused by the SDK. The builder used here takes no handshake-wait setting. TCP connection, TLS negotiation
    and the CONNECT reply are separate stages; the test deadline establishes no measured handshake duration."""
    L = parts.limits
    start_broker(pki, tmp_path / "conf")
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST))
    try:
        assert d.ask(op="build")["ok"] and d.ask(op="limit", name="CONNECT_WAIT_S", value=30.0)["ok"]
        other = d.ask(op="limit", name="OPERATION_TIMEOUT_S", value=1.0)          # the driver sets that one wait and no other value
        assert other["ok"] is False and other["error"] == "no such limit", other
        docker("pause", BROKER)
        try:
            r = d.ask(op="connect")
        finally:
            docker("unpause", BROKER)
        assert r["ok"] is False and r["error"] == "UplinkError", r
        assert L.SDK_TLS_NEGOTIATION_S - 3 <= r["took_s"] <= L.SDK_TLS_NEGOTIATION_S + 5, r          # the SDK's answer, not the uplink's 30 s
        assert L.CONNECT_WAIT_S < L.TCP_CONNECT_TIMEOUT_S + L.SDK_TLS_NEGOTIATION_S + L.PING_TIMEOUT_S
        time.sleep(3.0)
        st = d.ask(op="state")
        assert (st["counters"]["opened"], st["counters"]["given_up"], st["counters"]["late"]) == (0, 1, 0), st
        assert connects() == []          # the SDK gave that one up itself: no CONNECT ever reached the broker
        d.ask(op="close")
    finally:
        rc, err = d.end()
    assert (rc, err) == (0, "")
    print("WP3 the SDK's own handshake wait: with the uplink's wait at 30 s the connect to the silent far end came back failed after "
          "%.1f s (the test's bound: %d to %d s; no timing), late %d, and no CONNECT reached the broker"
          % (r["took_s"], L.SDK_TLS_NEGOTIATION_S - 3, L.SDK_TLS_NEGOTIATION_S + 5, st["counters"]["late"]))


def test_this_broker_acknowledges_and_drops_a_publish_its_acl_denies_and_keeps_the_connection(image, pki, network, tmp_path):
    """A record of what the LOCAL broker does, for the account steps: Mosquitto 2.0.22 answers a denied QoS 1 publish of
    an MQTT 3.1.1 client with a PUBACK and does not forward it; the connection stays. So nothing here can show the
    connector what a publish the cloud service's policy refuses looks like, or one kind of publish failing alone."""
    start_broker(pki, tmp_path / "conf")
    obs = Observer()
    d = Driver(image, device_directory(tmp_path / "device", pki, HOST)).open()
    try:
        denied = "$aws/rules/another_rule/%s" % THING
        assert d.publish(denied, b"denied").get("ok") is True          # acknowledged all the same
        assert d.publish(TELEMETRY, b"allowed").get("ok") is True
        assert wait_until(lambda: obs.on(TELEMETRY) == [b"allowed"]) and obs.on(denied) == []
        assert [ln for ln in broker_log() if "Denied PUBLISH from %s" % THING in ln and denied in ln]
        assert len(connects()) == 1 and d.ask(op="state")["counters"]["lost"] == 0
        d.ask(op="close")
    finally:
        d.end()
        obs.close()


# ============================================================ the full local slice, and the canary run

def frozen_allowlist() -> Any:
    if not TWIN_FROZEN.is_file():
        twin_gate.missing("needs the frozen allowlist %s (sdv/connector/README.md)" % TWIN_FROZEN)
    import importlib.util
    spec = importlib.util.spec_from_file_location("twin_allowlist_for_the_broker_tests", str(TWIN_FROZEN))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def excluded_plan() -> List[Dict[str, Any]]:
    """One entry per leaf of the branch the twin excludes, enumerated from the generated catalogue: a distinctive number
    for a counter (uint32, uint64), and a valid value for a leaf too narrow to hold one."""
    gen = twin_gate.catalogue("vss-databroker.json")
    leaves = attr.leaf_nodes(json.loads((gen / "vss-databroker.json").read_text(encoding="utf-8")))
    plan = []
    for i, path in enumerate(sorted(p for p in leaves if p.startswith(attr.MONITOR_PREFIX))):
        node = leaves[path]
        dt = node["datatype"]
        if dt == "uint32":
            value: Any = 3_141_592_000 + 7 * i
        elif dt == "uint64":
            value = 9_876_543_210_000 + 7 * i
        elif dt == "boolean":
            value = True
        elif dt == "string":
            value = "canary-%d-zq7" % i
        else:
            value = int(node.get("max", 1))
        plan.append({"path": path, "datatype": dt, "value": value, "distinctive": dt in ("uint32", "uint64", "string")})
    assert len(plan) == 22 and sum(e["distinctive"] for e in plan) == 16, "the excluded branch is not the 22 leaves of today"
    return plan


class Slice:
    """One `stack.py replay --feed vcan --connector` beside the test broker, with a thread that watches it: it takes
    `docker inspect` of the connector while it runs, and does what `during` says once the connector has spoken."""

    def __init__(self, image: str, pki: Path, tmp_path: Path, name: str, before_connector: Optional[Callable[[], Any]] = None,
                 during: Optional[Callable[[], Any]] = None, extra: Sequence[str] = ()) -> None:
        self.extra = list(extra)                # more words for the stack's replay: `--bridge broker` (SDV_BRIDGE_IMAGE is the caller's)
        self.proc: Optional[subprocess.Popen] = None          # the stack's process, once it runs: a sampler reads until it ends
        self.device = device_directory(tmp_path / "device-of-the-slice", pki, ADDRESS)
        self.runs = tmp_path / "runs"
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SDV_CONNECTOR_IMAGE=image, SDV_DEVICE_DIR=str(self.device),
                        SDV_STATE=str(tmp_path / "state"), SDV_RUNS=str(self.runs), SDV_RECORDING=RECORDING)
        self.name = name
        self.inspect: Any = None
        self.notes: Dict[str, Any] = {}
        self.errors: List[str] = []
        self._before, self._during = before_connector, during
        self.obs = Observer()

    def _watch(self, proc: subprocess.Popen) -> None:
        try:
            if self._before is not None:
                def listening() -> bool:
                    p = sh("docker", "logs", "sdv-stack-databroker", check=False)
                    return "Listening on 127.0.0.1" in p.stdout + p.stderr

                up = wait_until(lambda: proc.poll() is not None or listening(), 180)
                if up and proc.poll() is None:
                    self.notes["before"] = self._before()
            seen = wait_until(lambda: proc.poll() is not None or docker(
                "inspect", "sdv-stack-connector", check=False).returncode == 0, 240)
            if not seen or proc.poll() is not None:
                return
            self.inspect = json.loads(docker("inspect", "sdv-stack-connector").stdout)[0]
            if wait_until(lambda: proc.poll() is not None or self.obs.on(PUBLISH[1]), 120) and proc.poll() is None and self._during:
                self.notes["during"] = self._during()
        except Exception as exc:  # noqa: BLE001 -- reported by the test, not lost in a thread
            self.errors.append("%s: %s" % (type(exc).__name__, exc))

    def run(self) -> Dict[str, Any]:
        proc = subprocess.Popen([str(SIM_PY), str(STACK_DIR / "stack.py"), "replay", "--feed", "vcan", "--connector", *self.extra,
                                 "--name", self.name],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=str(REPO))
        self.proc = proc
        watcher = threading.Thread(target=self._watch, args=(proc,), daemon=True)
        watcher.start()
        try:
            out, err = proc.communicate(timeout=900)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        watcher.join(60)
        time.sleep(1.0)
        self.obs.close()
        assert not self.errors, self.errors
        assert proc.returncode == 0, (out[-3000:], err[-3000:])
        (self.run_dir,) = list(self.runs.glob("*-%s" % self.name))
        self.replay = self.run_dir / "vcan-1"
        self.result = json.loads((self.replay / "result.json").read_text(encoding="utf-8"))
        self.stdout = out
        return self.result


def witness_values(replay: Path) -> Dict[str, List[Any]]:
    """Every value the databroker served for each CAN-fed path in this replay, in order: the witness's own log, which the
    stack's analysis holds equal to the decoded recording (result.json, witness_values)."""
    out: Dict[str, List[Any]] = {}
    for line in (replay / "vss-witness.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("event") == "value":
            out.setdefault(rec["path"], []).append(rec["value"])
    return out


def assert_only_the_allowlist(messages: Sequence[Tuple[str, bytes]], allow: Any) -> Dict[str, int]:
    """Every message the observer read: on one of the device's four topics, and holding allowlisted keys only."""
    prefix = attr.MONITOR_PREFIX.rstrip(".").lower()
    counts: Dict[str, int] = {}
    fields = set(allow.APPSTATE_FIELDS.values())
    for topic, payload in messages:
        assert topic in PUBLISH, topic
        counts[topic] = counts.get(topic, 0) + 1
        text = payload.decode("utf-8")
        assert prefix not in text.lower() and prefix.rsplit(".", 1)[1] + "." not in text.lower(), topic
        if topic == PUBLISH[3]:
            assert payload == b""
            continue
        doc = json.loads(text)
        if topic == TELEMETRY:
            assert set(doc) == {"v", "batch", "paths", "rows", "appstate"} and doc["v"] == 1
            assert set(doc["paths"]) <= set(allow.PATHS) and all(len(row) == len(doc["paths"]) + 1 for row in doc["rows"])
            assert all(set(rec) == fields for rec in doc["appstate"])
        else:
            assert set(doc) == {"state"} and set(doc["state"]) == {"reported"}
            reported = doc["state"]["reported"]
            if topic == PUBLISH[1]:
                assert set(reported) == set(allow.PATHS)
            else:
                assert set(reported) == {"rate_hz", "paths"} and set(reported["paths"]) <= set(allow.PATHS)
    return counts


def assert_run_directory_names_nothing_of_the_device(s: Slice) -> int:
    forbidden = [ADDRESS, THING, RULE, str(s.device), s.device.name, "connector.env", "device.key", "device.crt", "ca.pem", "SDV_TWIN_ENDPOINT"]
    files = [p for p in sorted(s.run_dir.rglob("*")) if p.is_file()] + [p for p in sorted(Path(s.env["SDV_STATE"]).rglob("*")) if p.is_file()]
    assert (s.replay / "twin-connector.log") in files and len(files) > 20
    assert {p.name for p in files if p.parent.name == "spool"} >= {"started.json"}          # the connector's own files are among them
    for p in files:
        text = p.read_bytes().decode("utf-8", "replace")
        for word in forbidden:
            assert word not in text, (str(p.relative_to(s.run_dir.parent)) if s.run_dir.parent in p.parents else p.name, word)
    return len(files)


def assert_three_mounts_and_the_host_network(s: Slice) -> None:
    info = s.inspect
    assert info is not None, "the connector was never seen running"
    mounts = sorted((m["Destination"], m["Type"], bool(m["RW"]), m["Source"]) for m in info["Mounts"])
    assert mounts == sorted([("/run/sdv-local/spool/v1", "bind", True, str(s.runs / info["Config"]["Labels"]["sdv.stack.run"] / "spool")),
                             ("/run/sdv-local/status/v1", "bind", False, str(s.runs / info["Config"]["Labels"]["sdv.stack.run"] / "status")),
                             ("/run/sdv-local/device", "bind", False, str(s.device))]), mounts
    hc = info["HostConfig"]
    assert hc["NetworkMode"] == "host" and hc["ReadonlyRootfs"] is True and hc["Privileged"] is False and hc["CapDrop"] == ["ALL"]
    assert not hc.get("CapAdd") and not hc.get("PortBindings") and not hc.get("Binds") and not hc.get("VolumesFrom") and not hc.get("Tmpfs")
    assert hc["RestartPolicy"]["Name"] == "no" and "no-new-privileges" in (hc.get("SecurityOpt") or [])
    assert info["Config"]["User"] == "%d:%d" % (os.getuid(), os.getgid()) and os.getuid() != 0
    assert info["Image"] == IMAGES["connector"]["amd64"]["id"] and not info["Config"].get("ExposedPorts")
    assert "docker.sock" not in json.dumps(info) and info["Path"] == "python" and info["Args"] == ["/app/connector.py"]


def test_the_full_local_slice_with_the_connector_sends_what_the_databroker_served_and_only_the_allowlist(image, pki, network, parts, tmp_path):
    allow = frozen_allowlist()
    start_broker(pki, tmp_path / "conf")
    delta = {"version": 3, "state": {"scenario": "20990101-sigsim-43-brake", "unknown_key": "ignored"}}
    s = Slice(image, pki, tmp_path, "p4-wp3-slice", during=lambda: observer_publish(SUBSCRIBE[2], json.dumps(delta).encode("utf-8")))
    result = s.run()
    gates = json.loads(re.search(r"^gates: (\{.*\})$", s.stdout, re.M).group(1))
    assert gates == {"values": True, "decisions": True, "lights": True, "listeners": True, "c12b": True, "bus_frames_identical": True,
                     "connector": True}, gates
    assert result["witness_values"]["ok"] and result["connector"]["ok"] and result["connector"]["exit"] == 0
    assert_three_mounts_and_the_host_network(s)
    messages = list(s.obs.messages)
    counts = assert_only_the_allowlist([m for m in messages if m[0] in PUBLISH], allow)
    assert counts[PUBLISH[3]] == 1 and counts[TELEMETRY] >= 1 and counts[PUBLISH[1]] >= 2 and counts[PUBLISH[2]] == 1, counts
    assert not [ln for ln in broker_log() if "Denied PUBLISH from %s" % THING in ln]          # its four exact topics and no other
    assert set(d for d, _t, _n in inbound()) == {"d0"} and connects() == [(THING, "p2", "c1", "k60", THING)]
    # against the run: every telemetry cell of a CAN-fed path is a value the databroker served for it in this replay
    served = witness_values(s.replay)
    batches = [json.loads(p) for p in s.obs.on(TELEMETRY)]
    rows = sum(len(b["rows"]) for b in batches)
    checked = 0
    for b in batches:
        for row in b["rows"]:
            for path, cell in zip(b["paths"], row[1:]):
                if path in served and cell is not None:
                    assert cell in served[path], (path, cell)
                    checked += 1
    assert rows >= 20 and checked >= 100, (rows, checked)          # a replay's worth of 1 Hz samples, not a clean sheet of nothing
    moved = {path for path in served if len({c for b in batches for row in b["rows"] for p, c in zip(b["paths"], row[1:]) if p == path}) > 1}
    assert len(moved) >= 2, "the samples of the CAN-fed paths never changed: %s" % sorted(moved)
    # the last vss document (the stop's): the databroker's last value of each CAN-fed path, and the app's last record
    last = json.loads(s.obs.on(PUBLISH[1])[-1])["state"]["reported"]
    for path, values in served.items():
        if path in allow.PATHS:
            assert last[path] == values[-1], path
    heartbeat = result["appstate_first_last"][-1]
    for leaf, prop in allow.APPSTATE_FIELDS.items():
        if prop != "seq" and prop in heartbeat:
            assert last[leaf] == heartbeat[prop], leaf
    # stopping the stack flushed one batch and one vss document: they are the last two things the far end received
    assert [t for t, _p in messages if t in PUBLISH][-2:] == [TELEMETRY, PUBLISH[1]]
    log = [json.loads(m.group(1)) for m in (re.match(r"^\S+Z (\{.*\})$", ln) for ln in (s.replay / "twin-connector.log").read_text(
        encoding="utf-8").splitlines()) if m]
    assert [rec["event"] for rec in log][-3:] == ["batch", "shadow", "stop"] and log[-1]["signal"] == 15 and log[0]["event"] == "start"
    assert log[-1]["counters"]["sent_telemetry"] == counts[TELEMETRY] and log[-1]["counters"]["sent_vss"] == counts[PUBLISH[1]]
    assert sum(log[-1]["counters"]["failed_" + k] for k in ("telemetry", "vss", "config", "get")) == 0
    # the real uplink's own counters are in the real stop line and in the stack's record of the replay: one connection, given up
    # once (the close), never lost, never found without life, and no connection of the SDK's own making
    assert log[-1]["uplink"] == {"opened": 1, "lost": 0, "given_up": 1, "undone": 0, "stale": 0, "late": 0, "resumed_by_sdk": 0,
                                 "callback_errors": 0, "messages": 1, "not_connected": 0}, log[-1]["uplink"]          # one message: the delta
    assert result["connector"]["uplink"] == log[-1]["uplink"]
    # the delta the observer published reached the connector and the spool: the two-field record, and the unknown key nowhere
    assert json.loads((s.replay / "spool" / "desired.json").read_text(encoding="utf-8")) == {"image_id": None, "scenario": "20990101-sigsim-43-brake"}
    spooled = [rec for rec in log if rec["event"] == "spool"]
    assert len(spooled) == 1 and spooled[0] == dict(spooled[0], ok=True, image_id=False, scenario=True) and log[-1]["counters"]["deltas"] == 1
    assert sorted(p.name for p in (s.replay / "spool").iterdir()) == ["desired.json", "started.json"] and not list((s.replay / "status").iterdir())
    scanned = assert_run_directory_names_nothing_of_the_device(s)
    assert "unknown_key" not in (s.replay / "twin-connector.log").read_text(encoding="utf-8")
    # counts of this run, for the reader of a log (none is a measurement)
    print("WP3 slice: the far end received %s; %d telemetry rows, %d cells of CAN-fed paths each a value the databroker served, %d of "
          "those paths moved; the connector's events %s; %d files of the run directory and the state directory searched"
          % ({t.rsplit("/", 2)[-2] + "/" + t.rsplit("/", 1)[-1]: n for t, n in sorted(counts.items())}, rows, checked, len(moved),
             result["connector"]["events"], scanned))


def test_the_canary_run_on_the_pinned_databroker_puts_no_value_of_the_excluded_branch_on_the_wire(image, pki, network, parts, tmp_path):
    """Design twin-allowlist.md A6 as the design has it, on the pinned databroker image: no bridge runs, and a writer
    plants a value in every leaf of the excluded branch before the connector starts. "No key of that branch" alone would
    pass a value of it sent under an allowed key, so the observer's raw bytes are searched for the values themselves."""
    allow = frozen_allowlist()
    plan = excluded_plan()
    (tmp_path / "plan").mkdir()
    (tmp_path / "plan" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    recorder = docker("image", "inspect", "-f", "{{.Id}}", IMAGES["local"]["kuksa-csv-provider-recorder"]["tag"]).stdout.strip()

    def writer(mode: str) -> Dict[str, Any]:
        docker("rm", "-f", WRITER, check=False)
        p = docker("run", "--rm", "--name", WRITER, "--label", LABEL + "=writer", *COMMON, "--read-only", "--network", "host",
                   "--user", "%d:%d" % (os.getuid(), os.getgid()),
                   "--mount", "type=bind,src=%s,dst=/probe,readonly" % PROBES_DIR,
                   "--mount", "type=bind,src=%s,dst=/plan,readonly" % (tmp_path / "plan"),
                   "--entrypoint", "python", recorder, "/probe/canary_writer.py", "127.0.0.1:55555", "/plan/plan.json", mode)
        return json.loads(p.stdout)

    start_broker(pki, tmp_path / "conf")
    s = Slice(image, pki, tmp_path, "p4-wp3-canary", before_connector=lambda: writer("plant"), during=lambda: writer("read"))
    result = s.run()
    assert result["connector"]["ok"] and result["witness_values"]["ok"] and result["bridge_mode"] == "none"
    # the plant: every leaf took its value, and the databroker still held each while the connector ran
    planted, read = s.notes["before"], s.notes["during"]
    assert planted["refused"] == {} and sorted(planted["accepted"]) == sorted(e["path"] for e in plan)
    assert read["refused"] == {} and read["held"] == {e["path"]: e["value"] for e in plan}
    # the wire: allowlisted keys only, and not one canary in the raw bytes of anything the far end received
    messages = [m for m in s.obs.messages if m[0] in PUBLISH]
    counts = assert_only_the_allowlist(messages, allow)
    assert counts[TELEMETRY] >= 1 and counts[PUBLISH[1]] >= 2
    raw = b"\n".join(p for _t, p in s.obs.messages)
    assert len(raw) > 2000 and [t for t, _p in s.obs.messages if t not in PUBLISH] == []
    for e in plan:
        if e["distinctive"]:
            assert str(e["value"]).encode("ascii") not in raw, "a canary of the excluded branch is on the wire"
    assert b"3141592" not in raw and b"9876543210" not in raw and b"canary" not in raw
    # the search is not blind: the same bytes do hold values the databroker served for allowlisted paths in this run
    served = witness_values(s.replay)
    found = sum(1 for path, values in served.items() if path in allow.PATHS and any(json.dumps(v).encode("ascii") in raw for v in set(values)))
    assert found >= 4, "the far end's bytes hold the served values of only %d allowlisted CAN-fed paths" % found
    # nor in the connector's own log; and the run directory names nothing of the device
    assert "3141592" not in (s.replay / "twin-connector.log").read_text(encoding="utf-8")
    assert_three_mounts_and_the_host_network(s)
    scanned = assert_run_directory_names_nothing_of_the_device(s)
    print("WP3 canary: %d leaves of the excluded branch planted and read back while the connector ran, %d of them distinctive; the far end "
          "received %d messages, %d bytes, with the served values of %d allowlisted CAN-fed paths and no canary; %d files searched"
          % (len(plan), sum(e["distinctive"] for e in plan), len(messages), len(raw), found, scanned))


BRIDGE_IMAGE = os.environ.get("SDV_BRIDGE_IMAGE", "")


def read_excluded(plan_dir: Path, recorder: str) -> Dict[str, Any]:
    """One read of every leaf of the excluded branch at the stack's databroker (the probe's `read` mode: GetValue and nothing
    else). Nothing is ever written by it, and the read says so itself."""
    docker("rm", "-f", WRITER, check=False)
    p = docker("run", "--rm", "--name", WRITER, "--label", LABEL + "=writer", *COMMON, "--read-only", "--network", "host",
               "--user", "%d:%d" % (os.getuid(), os.getgid()),
               "--mount", "type=bind,src=%s,dst=/probe,readonly" % PROBES_DIR,
               "--mount", "type=bind,src=%s,dst=/plan,readonly" % plan_dir,
               "--entrypoint", "python", recorder, "/probe/canary_writer.py", "127.0.0.1:55555", "/plan/plan.json", "read", check=False)
    out = json.loads(p.stdout)
    assert out["mode"] == "read" and out["accepted"] == [], out
    return dict(out)


@pytest.mark.skipif(not BRIDGE_IMAGE, reason="the slice with the claim bridge also needs SDV_BRIDGE_IMAGE, the bridge image's ID "
                    "(sdv/bridge/build_image.py: the amd64 one has no pin, and the stack holds it to this generation by its labels)")
def test_the_full_local_slice_with_the_claim_bridge_and_the_native_monitor_sends_only_the_allowlist_while_the_bridges_leaves_hold_values(
        image, pki, network, parts, tmp_path):
    """the connector bridge scenario, run (b), and A4 item 3's local half: `stack.py replay --feed vcan --connector --bridge broker`, so
    that the stack builds and starts the native vss monitor and the claim bridge WRITES its leaves of the excluded branch into
    the databroker while the connector reads the same databroker. The canary run plants values with no bridge; this one has the
    real writer. Held: every gate of the stack's own with the bridge's and the connector's among them; the connector's three
    mounts; the far end received the device's own topics and allowlisted keys only, and no path of the excluded branch; and it
    is not a clean sheet of nothing, because a sampler that only reads saw every leaf the run's own attribution table gives the
    bridge hold a value at the databroker in one read, with the connector's container running before and after that read."""
    allow = frozen_allowlist()
    plan = excluded_plan()
    (tmp_path / "plan").mkdir()
    (tmp_path / "plan" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    recorder = docker("image", "inspect", "-f", "{{.Id}}", IMAGES["local"]["kuksa-csv-provider-recorder"]["tag"]).stdout.strip()
    samples: List[Dict[str, Any]] = []
    holder: List[Slice] = []

    def running() -> bool:
        return docker("inspect", "-f", "{{.State.Running}}", "sdv-stack-connector", check=False).stdout.strip() == "true"

    def sample() -> int:
        s = holder[0]
        while s.proc is not None and s.proc.poll() is None and running():
            rec: Dict[str, Any] = {"before": True}
            try:
                got = read_excluded(tmp_path / "plan", recorder)
                rec.update(held=got["held"], refused=got["refused"])
            except Exception as exc:  # noqa: BLE001 -- a read that proves nothing is a sample that proves nothing
                rec["error"] = type(exc).__name__
            rec["after"] = running()
            samples.append(rec)
            time.sleep(0.5)
        return len(samples)

    start_broker(pki, tmp_path / "conf")
    s = Slice(image, pki, tmp_path, "p4-wp8-bridge", during=sample, extra=("--bridge", "broker"))
    holder.append(s)
    result = s.run()
    gates = json.loads(re.search(r"^gates: (\{.*\})$", s.stdout, re.M).group(1))
    assert gates == {"values": True, "decisions": True, "lights": True, "listeners": True, "c12b": True, "bus_frames_identical": True,
                     "bridge": True, "connector": True}, gates
    assert result["bridge_mode"] == "broker" and result["bridge"]["ok"] and result["connector"]["ok"] and result["connector"]["exit"] == 0
    assert_three_mounts_and_the_host_network(s)
    # the wire: the device's own topics and allowlisted keys only, and no path of the excluded branch (assert_only_the_allowlist)
    messages = list(s.obs.messages)
    counts = assert_only_the_allowlist([m for m in messages if m[0] in PUBLISH], allow)
    assert [t for t, _p in messages if t not in PUBLISH] == [] and counts[TELEMETRY] >= 1 and counts[PUBLISH[1]] >= 2, counts
    assert connects() == [(THING, "p2", "c1", "k60", THING)] and not [ln for ln in broker_log() if "Denied PUBLISH from %s" % THING in ln]
    # the bridge's leaves, from this run's own attribution table: all of the excluded branch, and half of what the canary plants
    rows = json.loads((s.replay / "attribution.json").read_text(encoding="utf-8"))["rows"]
    bridge = sorted(r["path"] for r in rows if r.get("writer") == attr.BRIDGE)
    excluded = sorted(e["path"] for e in plan)
    assert len(bridge) == 11 and set(bridge) < set(excluded) and all(p.startswith(attr.MONITOR_PREFIX) for p in bridge), len(bridge)
    # ... each held a value at the databroker, all in one read, while the connector's container ran before and after it
    good = [x for x in samples if x["before"] and x["after"] and "held" in x and not x["refused"]]
    at_once = [x for x in good if all(x["held"].get(p) is not None for p in bridge)]
    assert at_once and all(good[-1]["held"].get(p) is not None for p in bridge), (len(samples), len(good), len(at_once))
    assert assert_run_directory_names_nothing_of_the_device(s) > 20
    # counts of this run, for the reader of a log (none is a measurement)
    print("WP8 slice with the bridge: %d reads of the excluded branch, %d with the connector running before and after, all %d leaves of the "
          "bridge held a value in %d of them; the far end received %s"
          % (len(samples), len(good), len(bridge), len(at_once),
             {t.rsplit("/", 2)[-2] + "/" + t.rsplit("/", 1)[-1]: n for t, n in sorted(counts.items())}))
