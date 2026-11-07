"""The breaker's burst tool, in its own image, at a local broker (sdv/cloud/burst, the image of sdv/connector/build_image.py
build --burst): SDV Phase 4, the burst-tool contract and WP8 item 3.

OPT-IN: skipped unless SDV_BURST_BROKER=1, on POSIX with docker (WSL Ubuntu-24.04's Docker Engine). The tool's tests that
CI runs are tests/test_sdv_burst.py, on fakes; no test there skips.

NO CLOUD, AND NO HOST BUT THE TEST'S OWN BROKER: the far end is the pinned eclipse-mosquitto of the connector's broker
tests (tests/test_sdv_connector_broker.py: its network, its throwaway CA and certificates, its broker and its reading of
the broker's log are used as they are), on a Docker network created --internal, with no published port. The tool runs
as a container of ITS OWN IMAGE, sdv-local/twin-burst:test-only, which is in no pin: the test finds it by its tag and
refuses one whose files are not byte for byte the tree's (python3 sdv/connector/build_image.py build --burst builds it).
The thresholds file is made up here (documentation values), with a stand-in for derive.py --check beside it; the
owner's file is never read. Every name is a placeholder.

What is held (WP8 item 3):
  * the three kinds send what a made-up thresholds file derives and stay under the ceilings: the broker received, from
    the thing, exactly the burst's publishes, each of the file's size, on the kind's one topic, none with the DUP flag;
  * a burst inside 60 s: the tool's log, and the broker's own count;
  * the trickle alternates its two topics, every 10 s, and logs each attempt; a SIGTERM stops it at once and the log
    says so;
  * the CONNECT is the connector's: MQTT 3.1.1, a clean session, a 60 s keep-alive (that it carries no user name is the
    connector's own broker test of the same settings, with a broker that keeps the CONNECT's user name: this one takes
    the certificate's name for it, so that its ACL holds the thing to its topics);
  * the log of a real run holds no identifier: the leak scan finds nothing in it;
  * when the broker goes away in the middle of a burst the burst ends there; the trickle keeps trying, each attempt
    logged as refused; when the broker is back the tool opens ONE new connection, a clean session again, and the
    trickle goes on; no publish of the burst is on the wire after the loss (nothing was queued for later, nothing is
    sent twice);
  * (the hard review) as PID 1 of its container, with no network at all: a SIGTERM or a SIGINT that comes while derive.py's
    own check runs ends the start at once as the refusal `stopped-before-start`, status 1, and nothing is claimed.

DESIGN VALUES of these tests (waits that bound a test, none a claim): how long a burst and a few trickle attempts are
waited for. The tests wait for the configured burst and trickle phases; no elapsed run duration is published here.

LEFT BEHIND: nothing. The tool's containers carry the broker tests' label and are removed with that module's network
fixture; the image is the build's, not this file's.

Does not demonstrate: the cloud service in any respect (no rule runs, no shadow service answers or counts, no policy
authorises, no quota applies, no metric counts, no alarm fires, no breaker cuts); that the service accepts the shadow
document; the tool against any other far end; any timing.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

import test_sdv_burst as TB
import test_sdv_connector_broker as CB
from test_sdv_connector_broker import network, pki  # noqa: F401 -- the broker tests' own fixtures: the internal network, the throwaway CA

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BURST_DIR = REPO / "sdv" / "cloud" / "burst"
CONNECTOR_DIR = REPO / "sdv" / "connector"
TAG = "sdv-local/twin-burst:test-only"
TOOL = "sdv-p4-burst-tool"
BURST_WAIT_S = 75.0          # a burst is paced over 40 s
TRICKLE_WAIT_S = 45.0        # four attempts of the trickle

pytestmark = pytest.mark.skipif(
    os.environ.get("SDV_BURST_BROKER") != "1" or shutil.which("docker") is None or os.name != "posix",
    reason="the burst tool's broker tests run only with SDV_BURST_BROKER=1 (WSL Docker; the pinned test broker; the tool's own image, "
           "built by python3 sdv/connector/build_image.py build --burst)")

# Made-up counts: small, so that a run's log is short, and each over what the tool's own trickle adds to it in one period
# (a file under that is refused: 31 on both topics, 16 on one). No design the owner chose.
THRESHOLDS = dict(TB.THRESHOLDS, **{"Firehose.IncomingRecords": 32, "IoT.RulesExecuted.per_execution": 32, "IoT.RulesExecuted.per_5kb_unit": 33,
                                    "IoT.PublishIn.Success": 33, "Firehose.IncomingBytes": 150000, "IoT.UpdateThingShadow.Accepted": 17})


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def B() -> Any:
    if str(CONNECTOR_DIR) not in sys.path:
        sys.path.insert(0, str(CONNECTOR_DIR))
    return _load("sdv_cloud_burst_for_the_broker_tests", BURST_DIR / "burst.py")


@pytest.fixture(scope="module")
def LS() -> Any:
    return _load("sdv_leakscan_for_the_burst_broker_tests", REPO / "scripts" / "aws" / "leakscan.py")


@pytest.fixture(scope="module")
def image() -> str:
    """The tool's own image, by its tag: in no pin, so held to the tree here, file by file. Nothing is built or pulled."""
    p = CB.docker("image", "inspect", "-f", "{{.Id}} {{.Architecture}} {{.Config.User}}", TAG, check=False)
    assert p.returncode == 0, "no image %s in the store: python3 sdv/connector/build_image.py build --burst" % TAG
    iid, arch, user = p.stdout.split()
    assert (arch, user) == ("amd64", "10001:10001")
    listing = ("import hashlib, json, os; print(json.dumps({n: hashlib.sha256(open('/app/' + n, 'rb').read()).hexdigest() "
               "for n in sorted(os.listdir('/app'))}))")
    held = json.loads(CB.docker("run", "--rm", "--network", "none", "--read-only", "--entrypoint", "python", iid, "-c", listing).stdout)
    want = {n: hashlib.sha256(((BURST_DIR if n.startswith("burst") else CONNECTOR_DIR) / n).read_bytes()).hexdigest()
            for n in ("burst.py", "burst_link.py", "limits.py", "topics.py", "uplink.py", "uplink_aws.py")}
    assert held == want, "the image %s is not built from the tree as it stands: build --burst again" % TAG
    labels = json.loads(CB.docker("image", "inspect", "-f", "{{json .Config.Labels}}", iid).stdout)
    assert labels.get("sdv.burst.test_only") == "1" and "sdv.stack" not in labels
    pins = (REPO / "sdv" / "stack" / "images.json").read_text(encoding="utf-8")
    assert iid not in pins and "twin-burst" not in pins          # never pinned
    return iid


class Tool:
    """One run of the tool's image on the internal network: a device directory, a thresholds directory, a state directory
    of its own and a directory for its log, mounted where the tool is told to look."""

    def __init__(self, image_id: str, top: Path, pki_dir: Path, kind: str, thresholds: Dict[str, int]) -> None:
        self.kind, self.top = kind, top
        self.device = CB.device_directory(top / "device", pki_dir, CB.ADDRESS)
        for name in ("thresholds", "run/state", "run/logs"):
            (top / name).mkdir(parents=True)
        (top / "thresholds" / "thresholds.json").write_text(json.dumps(TB.burst_doc(thresholds)), encoding="ascii")
        (top / "thresholds" / "derive.py").write_text(TB.DERIVE_DOUBLE, encoding="ascii")
        self.log = top / "run" / "logs" / (kind + ".jsonl")
        CB.docker("rm", "-f", TOOL, check=False)
        CB.docker("run", "-d", "--name", TOOL, "--label", CB.LABEL + "=burst", *CB.COMMON, "--read-only",
                  "--user", "%d:%d" % (os.getuid(), os.getgid()), "--network", CB.NET,
                  "--mount", "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % self.device,
                  "--mount", "type=bind,src=%s,dst=/run/sdv-local/thresholds,readonly" % (top / "thresholds"),
                  "--mount", "type=bind,src=%s,dst=/run/sdv-local/burst" % (top / "run"),
                  "--env-file", str(self.device / "connector.env"), image_id,
                  "run", "--kind", kind, "--thresholds", "/run/sdv-local/thresholds/thresholds.json",
                  "--thresholds-sha256", TB.sha_of(top / "thresholds" / "thresholds.json"), "--state", "/run/sdv-local/burst/state",
                  "--log", "/run/sdv-local/burst/logs/%s.jsonl" % kind)

    def lines(self) -> List[Dict[str, Any]]:
        if not self.log.is_file():
            return []
        out = []
        for line in self.log.read_text(encoding="utf-8").split("\n"):
            try:
                out.append(json.loads(line))
            except ValueError:          # the last line, while it is being written
                continue
        return out

    def events(self, *names: str) -> List[Dict[str, Any]]:
        return [rec for rec in self.lines() if rec["event"] in names]

    def wait(self, what: Any, seconds: float) -> Any:
        got = CB.wait_until(what, seconds, poll=0.5)
        assert got, "the tool did not get there: %s | %s" % ([rec["event"] for rec in self.lines()][-8:], self.said()[-600:])
        return got

    def said(self) -> str:
        p = CB.docker("logs", TOOL, check=False)
        return p.stdout + p.stderr

    def stop(self) -> int:
        """SIGTERM, as a withdrawn go: the exit status of the run."""
        CB.docker("kill", "-s", "TERM", TOOL)
        code = int(CB.docker("wait", TOOL, timeout=60).stdout.strip())
        self.output = self.said()
        CB.docker("rm", "-f", TOOL, check=False)
        return code


def from_the_thing(since: int = 0) -> List[Tuple[str, str, int]]:
    """(DUP flag, topic, bytes) of every PUBLISH the broker received from the thing, from the `since`-th on."""
    return CB.inbound()[since:]


@pytest.mark.parametrize("kind", ["count", "bytes", "shadow"])
def test_a_kind_sends_what_the_made_up_file_derives_inside_60_s_and_then_trickles_on_its_two_topics(B, LS, image, pki, network,  # noqa: F811
                                                                                                    tmp_path, kind):
    CB.start_broker(pki, tmp_path / "conf")
    topics = B.topics.Topics(CB.THING, CB.RULE)
    doc = TB.burst_doc(THRESHOLDS)["burst"]
    sends, size, topic = {"count": (doc["count_publishes"], doc["count_publish_bytes"], topics.telemetry),
                          "bytes": (doc["bytes_publishes"], doc["bytes_per_publish"], topics.telemetry),
                          "shadow": (doc["shadow_updates"], len(B.SHADOW_DOCUMENT), topics.vss_update)}[kind]
    assert (sends, size) == {"count": (67, 256), "bytes": (3, 102400), "shadow": (35, len(B.SHADOW_DOCUMENT))}[kind]
    assert sends <= {"count": 2000, "bytes": 2000, "shadow": 60}[kind] and sends * size <= B.CEILINGS["bytes"]
    tool = Tool(image, tmp_path / "tool", pki, kind, THRESHOLDS)
    try:
        (end,) = tool.wait(lambda: tool.events("burst-end"), BURST_WAIT_S)
        burst = from_the_thing()
        tool.wait(lambda: len([rec for rec in tool.events("outcome") if rec["phase"] == "trickle"]) >= 4, TRICKLE_WAIT_S)
        code = tool.stop()
    finally:
        CB.docker("rm", "-f", TOOL, check=False)
    lines = tool.lines()
    text = tool.log.read_text(encoding="utf-8")
    TB.lines_are_in_form(B, lines, text)
    # the burst: what the file derives, inside 60 s, on the one topic, and the broker received exactly that
    assert end["met"] is True and end["inside_window"] is True and end["why"] == "complete" and end["ratio"] == 1.0 and end["span_s"] < 60.0
    attempts = [rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "burst"]
    assert len(attempts) == sends and attempts[-1]["t_mono"] - attempts[0]["t_mono"] < B.WINDOW_S
    assert burst[:sends] == [("d0", topic, size)] * sends, burst[:3]
    # the trickle: its two topics in turn, 10 s apart, each attempt acknowledged; everything the broker received is the log's
    trickle = [rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "trickle"]
    assert [rec["path"] for rec in trickle[:4]] == ["ingest", "shadow", "ingest", "shadow"]
    assert all(b["t_mono"] - a["t_mono"] >= B.TRICKLE_INTERVAL_S - 0.01 for a, b in zip(trickle, trickle[1:]))
    outcomes = {rec["of"]: rec["result"] for rec in lines if rec["event"] == "outcome"}
    acked = [rec for rec in lines if rec["event"] == "attempt" and outcomes.get(rec["t_mono"]) == "acked"]
    received = from_the_thing()
    small = {"ingest": ("d0", topics.telemetry, B.TRICKLE_PUBLISH_BYTES), "shadow": ("d0", topics.vss_update, len(B.SHADOW_DOCUMENT))}
    assert received[sends:] == [small[rec["path"]] for rec in acked if rec["phase"] == "trickle"]
    assert len(received) == len(acked) and not [p for p in received if p[0] != "d0"]          # one packet for one attempt, none sent twice
    assert {p[1] for p in received} <= {topics.telemetry, topics.vss_update}
    # a SIGTERM stops it at once, and the log says so
    last = lines[-1]
    assert code == 0 and (last["event"], last["why"], last["signal"], last["burst_met"], last["exit"]) == ("stopped", "signal", "SIGTERM", True, 0)
    assert tool.output.strip() == ""                                # a run that started says nothing but its log
    # the CONNECT is the connector's
    assert [c[:4] for c in CB.connects()] == [(CB.THING, "p2", "c1", "k60")]          # MQTT 3.1.1, a clean session, a 60 s keep-alive
    # no identifier in the log of a real run: the leak scan finds nothing, and neither does a search for the names
    assert LS.findings(text, False, [CB.THING, CB.RULE, CB.HOST, CB.ADDRESS]) == []
    for word in (CB.THING, CB.RULE, CB.HOST, CB.ADDRESS, "$aws", "/run/sdv-local", "device.key", str(tmp_path)):
        assert word not in text, word
    claims = (tmp_path / "tool" / "run" / "state" / B.LEDGER).read_text(encoding="utf-8")
    assert claims.count('"claim"') == 1 and CB.THING not in claims and CB.ADDRESS not in claims


def test_when_the_broker_goes_away_the_burst_ends_the_trickle_keeps_trying_and_nothing_of_the_burst_is_sent_later(B, image, pki, network,  # noqa: F811
                                                                                                                  tmp_path):
    """WP8 item 3's "it stops when the broker goes away", as the tool's docstring reads it (decision 3)."""
    CB.start_broker(pki, tmp_path / "conf")
    topics = B.topics.Topics(CB.THING, CB.RULE)
    thresholds = dict(THRESHOLDS, **{"IoT.PublishIn.Success": 300})
    sends = TB.burst_doc(thresholds)["burst"]["count_publishes"]
    assert sends == 601
    tool = Tool(image, tmp_path / "tool", pki, "count", thresholds)
    try:
        tool.wait(lambda: len(tool.events("attempt")) >= 100, 30.0)
        CB.docker("kill", CB.BROKER)                                # the broker goes away in the middle of the burst
        (end,) = tool.wait(lambda: tool.events("burst-end"), 30.0)
        tool.wait(lambda: len([rec for rec in tool.events("outcome") if rec["phase"] == "trickle" and rec["result"] == "refused"]) >= 3, 60.0)
        gone = tool.lines()
        CB.docker("start", CB.BROKER)                               # ... and is back
        tool.wait(lambda: len([rec for rec in tool.events("outcome") if rec["phase"] == "trickle" and rec["result"] == "acked"]) >= 2, 120.0)
        code = tool.stop()
    finally:
        CB.docker("rm", "-f", TOOL, check=False)
    lines = tool.lines()
    TB.lines_are_in_form(B, lines, tool.log.read_text(encoding="utf-8"))
    # the burst ended at the loss: not met, and no attempt of it after the cut
    cut = [rec for rec in lines if rec["event"] == "cut"]
    assert len(cut) == 1 and cut[0]["connection"] == 1
    assert end["met"] is False and end["why"] in ("cut", "failed") and end["ratio"] < 1.0
    burst = [rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "burst"]
    assert 100 <= len(burst) < sends and max(rec["t_mono"] for rec in burst) <= cut[0]["t_mono"]
    # while the broker was away the trickle kept trying, and every attempt was logged as refused, with what became of the
    # connection it asked for
    away = [rec for rec in gone if rec["event"] == "outcome" and rec["phase"] == "trickle"]
    assert len(away) >= 3 and {rec["result"] for rec in away} == {"refused"} and {rec["connect"] for rec in away} <= {"refused", "held", "unanswered"}
    assert "refused" in {rec["connect"] for rec in away}            # a connection was really asked for
    # back: ONE new connection, a clean session again, and the trickle goes on, on both topics
    assert [rec["connection"] for rec in lines if rec["event"] == "connected"] == [1, 2]
    assert [c[:4] for c in CB.connects()] == [(CB.THING, "p2", "c1", "k60")] * 2
    # NOTHING OF THE BURST IS ON THE WIRE AFTER THE LOSS: what the broker received in all is the burst's publishes that were
    # acknowledged or in flight at the loss, then only the trickle's small ones; none with the DUP flag
    outcomes = {rec["of"]: rec["result"] for rec in lines if rec["event"] == "outcome"}
    acked_burst = len([rec for rec in burst if outcomes.get(rec["t_mono"]) == "acked"])
    received = from_the_thing()
    of_burst = [p for p in received if p[2] == 256]
    assert acked_burst <= len(of_burst) <= len(burst) and of_burst == [("d0", topics.telemetry, 256)] * len(of_burst)
    after = received[len(of_burst):]
    assert after and not [p for p in after if p[2] == 256] and not [p for p in received if p[0] != "d0"]
    assert {p[1:] for p in after} <= {(topics.telemetry, B.TRICKLE_PUBLISH_BYTES), (topics.vss_update, len(B.SHADOW_DOCUMENT))}
    acked_trickle = len([rec for rec in lines if rec["event"] == "outcome" and rec["phase"] == "trickle" and rec["result"] == "acked"])
    assert len(after) == acked_trickle
    last = lines[-1]
    assert code == B.EXIT["burst-not-met"] and (last["why"], last["signal"], last["burst_met"]) == ("signal", "SIGTERM", False)
    time.sleep(0)


EARLY = "sdv-p4-burst-early"
# derive.py's own check, standing in: it says where it can be seen that it began, takes 40 s and then passes the file
SLOW_DERIVE_IN_THE_IMAGE = '''import time
open("/run/sdv-local/burst/derive-began", "w").close()
time.sleep(40)
'''


@pytest.mark.parametrize("sent", ["TERM", "INT"])
def test_as_pid_1_of_its_image_a_signal_during_the_checks_ends_the_start_as_the_refusal_and_claims_nothing(B, image, tmp_path, sent):
    """The hard review, SHOULD 1, where it was seen: in its image the tool is PID 1 of its container, and the kernel drops a
    signal whose handling is the default one for the first process of a PID namespace. With the handlers installed only
    where the run begins, `docker kill -s TERM` during derive.py's check did nothing: the container ran on, and when the
    check had passed the tool claimed its window and asked for a connection. The handlers come first now: the container
    ends at once with status 1 and the refusal's one line, and nothing is claimed. No network at all here: nothing is sent
    either way, and the far end is not this test's subject."""
    top = tmp_path / "early"
    for name in ("thresholds", "run/state", "run/logs"):
        (top / name).mkdir(parents=True)
    (top / "thresholds" / "thresholds.json").write_text(json.dumps(TB.burst_doc(THRESHOLDS)), encoding="ascii")
    (top / "thresholds" / "derive.py").write_text(SLOW_DERIVE_IN_THE_IMAGE, encoding="ascii")
    CB.docker("rm", "-f", EARLY, check=False)
    try:
        CB.docker("run", "-d", "--name", EARLY, "--label", CB.LABEL + "=burst", *CB.COMMON, "--read-only",
                  "--user", "%d:%d" % (os.getuid(), os.getgid()), "--network", "none",
                  "--mount", "type=bind,src=%s,dst=/run/sdv-local/thresholds,readonly" % (top / "thresholds"),
                  "--mount", "type=bind,src=%s,dst=/run/sdv-local/burst" % (top / "run"),
                  "-e", "SDV_TWIN_THING=" + CB.THING, "-e", "SDV_TWIN_RULE=" + CB.RULE, image,
                  "run", "--kind", "count", "--thresholds", "/run/sdv-local/thresholds/thresholds.json",
                  "--thresholds-sha256", TB.sha_of(top / "thresholds" / "thresholds.json"), "--state", "/run/sdv-local/burst/state",
                  "--log", "/run/sdv-local/burst/logs/early.jsonl")
        assert CB.wait_until(lambda: (top / "run" / "derive-began").exists(), 60.0), CB.docker("logs", EARLY, check=False).stderr
        first = CB.docker("exec", EARLY, "cat", "/proc/1/cmdline").stdout.split("\0")
        assert first[:3] == ["python", "/app/burst.py", "run"]          # the tool IS the container's first process
        began = time.monotonic()
        CB.docker("kill", "-s", sent, EARLY)
        code = int(CB.docker("wait", EARLY, timeout=30).stdout.strip())
        took = time.monotonic() - began
        said = CB.docker("logs", EARLY, check=False)
    finally:
        CB.docker("rm", "-f", EARLY, check=False)
    assert (code, said.stdout, said.stderr) == (B.EXIT["refused"], "", TB.STOPPED_EARLY % ("SIG" + sent)), (code, said.stdout, said.stderr)
    assert took < 20.0                                              # at once: the check's 40 s were not waited for
    assert not (top / "run" / "state" / B.LEDGER).exists() and not list((top / "run" / "logs").iterdir())          # nothing claimed, no log begun
