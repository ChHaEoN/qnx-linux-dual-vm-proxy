"""The breaker's burst tool on fakes (sdv/cloud/burst/burst.py, sdv/cloud/burst/burst_link.py): SDV Phase 4, the burst-tool contract.

NO TEST IN THIS FILE MAY SKIP, AND NONE CONNECTS TO ANYTHING. The tool is the one program of this project built to send
MORE than the breaker's thresholds, past the connector's limiter. Here it runs on a link that goes nowhere and remembers
everything, on a clock the test moves, with thresholds files of documentation values. The real SDK at the pinned local
broker is tests/test_sdv_burst_broker.py (opt-in); the image and what holds the tool out of the connector's are
tests/test_sdv_connector.py.

A TEST FIXTURE IS CAPTURE DATA. Every count below is made up for the test and stands in no file the owner chose; the
thing, the rule and the endpoint are the placeholders the connector's tests use. The owner's thresholds file is never
read here.

What is held (the burst-tool contract and the package's decisions, burst.py's docstring):
  the plan     the three kinds take their sizes from the file they are given, and a file is refused before any
               connection when its doubled threshold is over a hard ceiling, when a burst is not more than twice its
               threshold, when its design values are not the tool's, when derive.py's own check does not pass it, or
               when it is no thresholds document; no refusal repeats a count of the file;
  the ceilings count what was ATTEMPTED: whatever the link acknowledges, a burst hands over each publish once and never
               again, and a plan made by hand over a ceiling is cut off at the ceiling;
  the time     is the monotonic clock's: a wall clock that steps moves neither the 60 s nor the 20 minutes; a burst
               that could not be handed over inside its 60 s ends there, says so and is the exit status;
  the trickle  alternates its two topics, one attempt every 10 s, each logged before it is made and again with what
               became of it; after a cut it keeps trying, hands nothing to a connection that is not up, and stops at
               the time ceiling;
  a signal     stops it at once, mid-burst too;
  one run      a second start inside the window of an earlier one is refused, whoever asks and whatever the wall
               clock says; a ledger that cannot be read refuses;
  the topics   are the connector's own two, from names topics.py checked; the command line takes no topic, no count
               and no endpoint;
  the log      is JSON lines in one form, with no identifier and no count of the file, and the leak scan finds nothing;
  the link     on the connector's stand-in for the SDK: a hand-over does not wait, nothing is handed to a connection
               that is down, a lost connection is given up and what the SDK may still hold is never written;
  the cases    (burst-spec; no new behaviour) every value of the file that is no whole count, every line of the ledger
               that is no claim, every pair of names topics.py refuses, every command line that cannot be read, a cut
               and a signal at six and five moments of each kind of run, a connect the SDK answers late; and the log's
               form recorded in a fixture, beside a made-up thresholds document (both in tests/fixtures);
  fix-r2       (after burst-verify-r1) no hand-over and no connection asked for at or after the 20 minutes, also on a
               connection that is opened late, and none after a signal that came inside a connect; the trickle's and
               the connections' counters as a second net behind the tick; an outcome's `connect` only where a connection
               was looked for; which two ends leave attempts without an outcome; a directory that cannot be written, and
               an error of the system's outside a run's own handling; a request for help and an abbreviated option;
  fix-r2-exact (after burst-verify-r1, its problems 2 to 8, 14 and 15) what the package states and no test held: the line
               of an error no check names, the burst's wait for its last answers, the ratio rounded down, the tick from the
               last one's beginning, the bytes in flight, a directory that is not there, the plan's own consistency checks,
               a hand-over at which the SDK raised, give_up(), a connection that showed no life, both signals of a real
               process, two claims that name no boot; a design value written as a float, a time of the ledger that is not
               finite, and the words on what a run can attempt.
  review-fix   (after the hard review and burst-verify-r2) a signal that comes BEFORE the claim, in the checks and inside
               derive.py's own check, is a refusal by a name and claims nothing, as a real process too; the thresholds file is
               held to the sha256 the run was given, and the plan is read from the bytes that were hashed; the trickle's own
               attempts of one period stay under every threshold of the file; a connection opened in an attempt and lost
               before its hand-over has its `cut` line; the time ceiling is said once; a path that leads into a work tree
               through a link; an answer of the link that is no word of the form; the watchdog on the run's clock, and one
               that ends the process although the log cannot be written.
  review-fix-exact (after burst-verify-r2 and the hard review's NITs 5 and 6) what the package states and no test held: the
               cut of a connection opened anew and used, and what a trickle hand-over without a word does; the trickle's 64
               bytes, the burst's span, a hand-over the link refused, a burst cut after its last hand-over, the name of the first
               signal; the boundaries at 60.0 s, at exactly 8 MiB and at 20 outstanding; a missing setting and a missing SDK
               as refusals; the system's clock and boot; the link's answer that cannot be read and a closed link that is asked
               to reopen; and the words on a log with no last line and on the window a failed first connection holds.

Does not demonstrate: the SDK (the stand-in is the connector's model of it); a broker; the cloud service, its quotas,
whether it accepts the shadow document the tool sends, or what a metric counts; that a burst trips an alarm; any timing.
"""
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BURST_DIR = REPO / "sdv" / "cloud" / "burst"
CONNECTOR_DIR = REPO / "sdv" / "connector"
FIXTURES = HERE / "fixtures"
THING, RULE = "example-thing", "example_rule"          # placeholders: no identifier is ever in the tree
ENDPOINT = "broker.example.invalid"                    # a reserved name: nothing answers to it
T0, WALL0 = 5000.0, 1_790_000_000.0                    # where the manual clock starts: fixtures, not times that were read
# Made-up counts (documentation values; no design the owner chose, no figure derive.py wrote).
THRESHOLDS = {"Firehose.IncomingRecords": 611, "Firehose.IncomingBytes": 1234567, "IoT.UpdateThingShadow.Accepted": 23,
              "IoT.PublishIn.Success": 673, "IoT.RuleAction.Failure": 1, "IoT.RulesExecuted.per_execution": 611,
              "IoT.RulesExecuted.per_5kb_unit": 659, "Lambda.Errors": 1}
# What stands in for derive.py --check: it passes a file that says so and refuses any other, by a name.
DERIVE_DOUBLE = '''import json, sys
args = sys.argv[1:]
if len(args) != 2 or args[0] != "--check":
    sys.exit(2)
with open(args[1]) as f:
    doc = json.load(f)
if doc.get("the_double_says") != "ok":
    sys.stderr.write("design estimate | refused: check-differs: the double refuses this file\\n")
    sys.stderr.write("design estimate | refused: burst-over-ceiling:count: 4,001 is over 2,000\\n")
    sys.exit(1)
'''


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


@pytest.fixture(scope="module")
def B() -> Any:
    """burst.py, loaded by its file under a name of this test file's. It imports the connector's limits, topics and
    uplink by name, as its image holds them side by side; no module named `burst` is left behind."""
    assert "burst" not in sys.modules
    mod = _load("sdv_cloud_burst_under_test", BURST_DIR / "burst.py")
    assert "burst" not in sys.modules and "awscrt" not in sys.modules and "awsiot" not in sys.modules
    assert Path(str(mod.topics.__file__)).resolve().parent == CONNECTOR_DIR.resolve()
    return mod


@pytest.fixture(scope="module")
def LS() -> Any:
    return _load("sdv_leakscan_for_the_burst_tests", REPO / "scripts" / "aws" / "leakscan.py")


class ManualClock:
    """A clock the test moves. sleep() is the only thing that moves it; what is planned for a moment (`at`) happens when
    a sleep crosses it, once. The wall clock runs with it and can be stepped on its own."""

    def __init__(self, t: float = T0, wall: float = WALL0, boot: Optional[str] = "boot-a") -> None:
        self.t, self.wall_s, self.boot_id = t, wall, boot
        self.hooks: List[Tuple[float, Callable[[], None]]] = []

    def monotonic(self) -> float:
        return self.t

    def wall(self) -> float:
        return self.wall_s

    def boot(self) -> Optional[str]:
        return self.boot_id

    def at(self, when: float, what: Callable[[], None]) -> None:
        self.hooks.append((when, what))

    def sleep(self, seconds: float) -> None:
        assert seconds > 0, "a sleep of nothing would never move a manual clock"
        end = self.t + seconds
        while True:
            due = sorted((when, i) for i, (when, _what) in enumerate(self.hooks) if when <= end)
            if not due:
                break
            when, i = due[0]
            what = self.hooks.pop(i)[1]
            self.wall_s += max(0.0, when - self.t)
            self.t = max(self.t, when)
            what()
        self.wall_s += end - self.t
        self.t = end


class FakeHandle:
    def __init__(self, link: "FakeLink", began: float, word: Optional[str], connection: int) -> None:
        self.link, self.began, self.word, self.connection = link, began, word, connection

    def state(self) -> Optional[str]:
        """acked | failed, or None while there is no word. A publish in flight on a connection that was cut is failed."""
        if self.word == "silent":
            return None
        if self.word == "failed":
            return "failed"
        lost = self.link.lost_at.get(self.connection)
        answered = self.began + self.link.ack_after
        if lost is not None and lost <= answered:
            return "failed" if self.link.clock.monotonic() >= lost else None
        return "acked" if self.link.clock.monotonic() >= answered else None


class FakeLink:
    """A link that goes nowhere and remembers everything: every hand-over with the time the clock gave, every connect.
    Scripted: how long an acknowledgement takes, which hand-overs fail or get no word, when the connection is cut and
    from when a new one can be opened."""

    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
        self.begun: List[Tuple[float, str, bytes]] = []          # what reached the wire, as far as a link can say
        self.asked: List[float] = []                             # every begin(), handed over or not
        self.connects: List[Tuple[float, str]] = []              # (when, opened | refused)
        self.connection = 0
        self.is_up = False
        self.lost_at: Dict[int, float] = {}
        self.ack_after = 0.0
        self.word: Callable[[int, str, bytes], Optional[str]] = lambda i, topic, payload: None
        self.connect_fails = False
        self.back_at: Optional[float] = None                     # a reopen succeeds from this moment on (None: never)
        self.held_until: Optional[float] = None                  # the link's own back-off
        self.closes = 0
        self.given_up = 0

    def connect(self) -> None:
        if self.connect_fails:
            self.connects.append((self.clock.monotonic(), "refused"))
            raise self._error()("the connection could not be opened to %s" % ENDPOINT)
        self.connection += 1
        self.is_up = True
        self.connects.append((self.clock.monotonic(), "opened"))

    def _error(self) -> Any:
        return sys.modules["uplink"].UplinkError

    def up(self) -> bool:
        return self.is_up

    def cut(self) -> None:
        if self.is_up:
            self.is_up = False
            self.lost_at[self.connection] = self.clock.monotonic()

    def reopen(self) -> str:
        now = self.clock.monotonic()
        if self.is_up:
            return "up"
        if self.held_until is not None and now < self.held_until:
            return "held"
        if self.back_at is None or now < self.back_at:
            self.connects.append((now, "refused"))
            return "refused"
        self.connection += 1
        self.is_up = True
        self.connects.append((now, "opened"))
        return "opened"

    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        now = self.clock.monotonic()
        self.asked.append(now)
        if not self.is_up:
            raise self._error()("not connected to %s" % ENDPOINT)
        word = self.word(len(self.begun), topic, payload)
        self.begun.append((now, topic, bytes(payload)))
        return FakeHandle(self, now, word, self.connection)

    def give_up(self) -> None:
        self.given_up += 1
        self.cut()

    def close(self) -> None:
        self.closes += 1
        self.is_up = False


def burst_doc(thresholds: Optional[Dict[str, int]] = None, **change: Any) -> Dict[str, Any]:
    """A thresholds document in derive.py's shape, its bursts derived as derive.py derives them (more than twice each
    threshold; the bytes burst whole publishes), from made-up thresholds."""
    t = dict(THRESHOLDS if thresholds is None else thresholds)
    count = max(t[k] for k in ("Firehose.IncomingRecords", "IoT.RulesExecuted.per_execution", "IoT.RulesExecuted.per_5kb_unit",
                               "IoT.PublishIn.Success"))
    per = 100 * 1024
    publishes = -(-(2 * t["Firehose.IncomingBytes"] + 1) // per)
    burst = {"window_s": 60, "factor": 2, "count_publishes": 2 * count + 1, "count_publish_bytes": 256, "bytes_publishes": publishes,
             "bytes_per_publish": per, "bytes_total": publishes * per, "shadow_updates": 2 * t["IoT.UpdateThingShadow.Accepted"] + 1,
             "ceiling_publishes": 2000, "ceiling_bytes": 8 * 1024 * 1024, "ceiling_shadow_updates": 60, "ceiling_minutes": 20}
    burst.update(change)
    return {"the_double_says": "ok", "design": {"cap_usd": 10.0, "things": 1}, "thresholds": t, "burst": burst}


COUNTS = sorted(set(THRESHOLDS.values()) | {v for k, v in burst_doc()["burst"].items() if not k.startswith(("ceiling", "window", "factor"))})


@pytest.fixture
def files(tmp_path: Path) -> Any:
    """A thresholds file with its double of derive.py beside it, a state directory and a place for the log, all outside
    every work tree (pytest's own directory)."""
    d = tmp_path / "thresholds"
    d.mkdir()
    (d / "thresholds.json").write_text(json.dumps(burst_doc()), encoding="ascii")
    (d / "derive.py").write_text(DERIVE_DOUBLE, encoding="ascii")
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()

    def put(doc: Dict[str, Any]) -> Path:
        (d / "thresholds.json").write_text(json.dumps(doc), encoding="ascii")
        return d / "thresholds.json"

    return types.SimpleNamespace(thresholds=d / "thresholds.json", derive=d / "derive.py", state=tmp_path / "state",
                                 log=tmp_path / "logs" / "burst.jsonl", put=put, top=tmp_path)


ENV = {"SDV_TWIN_ENDPOINT": ENDPOINT, "SDV_TWIN_THING": THING, "SDV_TWIN_RULE": RULE}


def sha_of(path: Path) -> str:
    """The sha256 a run is given for its thresholds file: the file's own bytes', in the form `twinctl status` prints it. For a
    file that is not there it is the hash of nothing: such a start is refused before any hash is compared."""
    return hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()


def run_argv(files: Any, kind: str = "count", state: Optional[Path] = None, log: Optional[Path] = None, sha256: Optional[str] = None) -> List[str]:
    """The command line of a run: the kind, the thresholds file with ITS sha256 (or the one given), the state directory, the log."""
    return ["run", "--kind", kind, "--thresholds", str(files.thresholds), "--thresholds-sha256", sha256 or sha_of(files.thresholds),
            "--state", str(state if state is not None else files.state), "--log", str(log if log is not None else files.log)]


class Ran:
    def __init__(self, rc: int, out: str, err: str, link: Optional[FakeLink], log: Path, clock: ManualClock) -> None:
        self.rc, self.out, self.err, self.link, self.clock = rc, out, err, link, clock
        self.text = log.read_text(encoding="utf-8") if log.is_file() else ""
        self.lines: List[Dict[str, Any]] = [json.loads(line) for line in self.text.split("\n") if line]

    def events(self, *names: str) -> List[Dict[str, Any]]:
        return [rec for rec in self.lines if rec["event"] in names]

    def one(self, name: str) -> Dict[str, Any]:
        (rec,) = self.events(name)
        return rec


def run(B: Any, files: Any, kind: str, capsys: Any, clock: Optional[ManualClock] = None,
        script: Optional[Callable[[FakeLink, ManualClock], None]] = None, env: Optional[Dict[str, str]] = None, log: Optional[Path] = None,
        stop: Any = None, argv: Optional[List[str]] = None, link_class: Any = None) -> Ran:
    """burst.py's main, with a link that goes nowhere and a clock the test moves. `script` sets the link and the clock up
    before anything is sent; `link_class` is a FakeLink of the test's own."""
    clock = clock if clock is not None else ManualClock()
    made: List[FakeLink] = []

    def make_link(env_: Any, topics: Any) -> FakeLink:
        assert topics.client_id == THING
        link = (link_class or FakeLink)(clock)
        made.append(link)
        if script is not None:
            script(link, clock)
        return link

    log = log if log is not None else files.log
    stop = stop if stop is not None else B.Stop()
    args = argv if argv is not None else run_argv(files, kind, log=log)
    rc = B.main(args, env=dict(ENV if env is None else env), make_link=make_link, clock=clock, stop=stop)
    said = capsys.readouterr()
    return Ran(rc, said.out, said.err, made[0] if made else None, log, clock)


def topics_of(B: Any) -> Any:
    return B.topics.Topics(THING, RULE)


def held_to_its_two_topics(B: Any, ran: Ran) -> None:
    t = topics_of(B)
    assert ran.link is not None and {topic for _when, topic, _payload in ran.link.begun} <= {t.telemetry, t.vss_update}


# ================================================================================================= the design values

def test_the_ceilings_are_gap_ys_and_a_run_ends_before_the_sdks_own_reconnect_could_come(B: Any) -> None:
    L = B.limits
    assert B.CEILINGS == {"publishes": 2000, "bytes": 8 * 1024 * 1024, "shadow_updates": 60, "minutes": 20}
    assert (B.WINDOW_S, B.FACTOR, B.CEILING_S, B.TRICKLE_INTERVAL_S) == (60, 2, 20 * 60, 10)
    assert B.BURST_SPREAD_S < B.WINDOW_S and B.SETTLE_S == L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S
    assert B.TRICKLE_MAX == B.CEILING_S // B.TRICKLE_INTERVAL_S == 120          # the trickle's own bound: 60 on each path
    assert B.KINDS == ("count", "bytes", "shadow") and B.PATHS == ("ingest", "shadow")
    assert B.QOS == L.QOS == 1
    # the SDK's own reconnect timer is held at an hour by the connector's settings, which the tool's link takes whole: a
    # run, its last waits and the watchdog's grace are over before half of it has gone, so nothing the SDK may still hold
    # for a lost connection is ever written by a reconnect of its own
    # (the watchdog reads the run's own clock, the one the uplink reads for that hold; its look and its last line's wait are counted in)
    assert 2 * (B.CEILING_S + B.WATCHDOG_GRACE_S + B.WATCHDOG_LOOK_S + B.WATCHDOG_LINE_S + B.SETTLE_S + L.CONNECT_WAIT_S + L.CLOSE_WAIT_S) \
        <= L.SDK_RECONNECT_HOLD_S
    assert (B.WATCHDOG_GRACE_S, B.WATCHDOG_LOOK_S, B.WATCHDOG_LINE_S) == (30, 1.0, 1.0)
    assert B.MAX_PUBLISH_BYTES == 128 * 1024 and B.EXIT == {"ok": 0, "refused": 1, "arguments": 2, "no-connection": 3, "burst-not-met": 4,
                                                            "error": 5, "watchdog": 6}
    doc = " ".join(str(B.__doc__).split())
    assert "Does not demonstrate" in doc and "SDV Phase 4" in doc


# ================================================================================================= the plan, from the file

def test_the_three_kinds_take_their_sizes_from_the_file_they_are_given(B: Any, files: Any) -> None:
    b = burst_doc()["burst"]
    count = B.load_plan("count", files.thresholds, None)
    assert (count.kind, count.path, count.sends, count.size) == ("count", "ingest", b["count_publishes"], b["count_publish_bytes"])
    big = B.load_plan("bytes", files.thresholds, None)
    assert (big.kind, big.path, big.sends, big.size) == ("bytes", "ingest", b["bytes_publishes"], b["bytes_per_publish"])
    assert big.sends * big.size == b["bytes_total"] > 2 * THRESHOLDS["Firehose.IncomingBytes"]
    shadow = B.load_plan("shadow", files.thresholds, None)
    assert (shadow.kind, shadow.path, shadow.sends) == ("shadow", "shadow", b["shadow_updates"]) and shadow.size == len(B.SHADOW_DOCUMENT)
    # another file, other sizes: nothing is a constant of the tool's
    other = dict(THRESHOLDS, **{"IoT.PublishIn.Success": 301, "Firehose.IncomingRecords": 290, "IoT.RulesExecuted.per_execution": 290,
                                "IoT.RulesExecuted.per_5kb_unit": 300, "IoT.UpdateThingShadow.Accepted": 19})
    files.put(burst_doc(other))
    assert B.load_plan("count", files.thresholds, None).sends == 603 and B.load_plan("shadow", files.thresholds, None).sends == 39
    with pytest.raises(B.Refused) as exc:
        B.load_plan("everything", files.thresholds, None)
    assert exc.value.name == "kind-unknown"


OVER = {"count": {"IoT.PublishIn.Success": 1000}, "bytes": {"Firehose.IncomingBytes": 4 * 1024 * 1024},
        "shadow": {"IoT.UpdateThingShadow.Accepted": 30}}


@pytest.mark.parametrize("kind", ["count", "bytes", "shadow"])
def test_a_file_whose_doubled_threshold_is_over_a_ceiling_is_refused_before_any_connection(B: Any, files: Any, capsys: Any, kind: str) -> None:
    """Twice the threshold and one is the least a burst may be: at 1,000 publishes, 4 MiB or 30 updates that is over the
    ceiling, whatever the file's own burst object says. Refused whichever kind is asked for: such a file is not taken."""
    doc = burst_doc(dict(THRESHOLDS, **OVER[kind]))
    for burst in (doc["burst"], dict(doc["burst"], count_publishes=1999, bytes_publishes=80, bytes_total=80 * 100 * 1024, shadow_updates=59)):
        files.put(dict(doc, burst=burst))
        for asked in B.KINDS:
            ran = run(B, files, asked, capsys)
            assert ran.rc == B.EXIT["refused"] and ran.link is None, (asked, ran.err)          # no link was even made
            assert "burst: refused: over-ceiling:%s:" % kind in ran.err and not files.log.exists()
            assert not (files.state / B.LEDGER).exists()          # and a refused file claims no window
            assert not [n for n in re.findall(r"[0-9][0-9,]*", ran.err) if int(n.replace(",", "")) in COUNTS + list(OVER[kind].values())]


def test_a_burst_that_is_not_more_than_twice_its_threshold_or_design_values_that_are_not_the_tools_are_refused(B: Any, files: Any) -> None:
    b = burst_doc()["burst"]
    cases = [({"count_publishes": 2 * 673}, "not-over-twice:count"), ({"shadow_updates": 2 * 23}, "not-over-twice:shadow"),
             ({"bytes_publishes": 24, "bytes_total": 24 * 100 * 1024}, "not-over-twice:bytes"),
             ({"bytes_total": b["bytes_total"] + 1}, "burst-inconsistent:bytes"), ({"bytes_per_publish": 128 * 1024 + 1}, "burst-inconsistent:bytes"),
             ({"ceiling_publishes": 4000}, "design-differs:ceiling_publishes"), ({"ceiling_bytes": 16 * 1024 * 1024}, "design-differs:ceiling_bytes"),
             ({"ceiling_shadow_updates": 600}, "design-differs:ceiling_shadow_updates"), ({"ceiling_minutes": 60}, "design-differs:ceiling_minutes"),
             ({"window_s": 600}, "design-differs:window_s"), ({"factor": 1}, "design-differs:factor"),
             ({"count_publishes": True}, "burst-value:count_publishes"), ({"shadow_updates": 47.0}, "burst-value:shadow_updates"),
             ({"count_publish_bytes": 0}, "burst-value:count_publish_bytes"), ({"count_publishes": 2001}, "over-ceiling:count"),
             ({"shadow_updates": 61}, "over-ceiling:shadow")]
    # a design value written as a float that EQUALS the tool's (60.0, 2.0, 8388608.0) is not the tool's either: every burst value and
    # every threshold that is a float is refused, and these were taken (burst-verify-r1, problem 15)
    cases += [({key: float(value)}, "design-differs:" + key) for key, value in sorted(B.DESIGN.items())]
    assert len(cases) == 16 + len(B.DESIGN) and all(isinstance(v, float) and v == B.DESIGN[k] for c, _n in cases[16:] for k, v in c.items())
    for change, name in cases:
        files.put(burst_doc(**change))
        with pytest.raises(B.Refused) as exc:
            B.load_plan("count", files.thresholds, None)
        assert exc.value.name == name, (change, exc.value.name)
        assert not [n for n in re.findall(r"[0-9]+", exc.value.detail.replace(",", "")) if int(n) in COUNTS], exc.value.detail


def test_the_file_is_held_to_derive_pys_own_check_and_a_file_that_is_no_thresholds_document_is_refused(B: Any, files: Any, tmp_path: Path) -> None:
    """Decision 6: the reading is held equal to derive.py's by derive.py's own --check, run as twinctl runs it, at every
    load. Its refusals are passed on by their names; what it says after a name (it prints counts) is not."""
    doc = burst_doc()
    doc["the_double_says"] = "no"
    files.put(doc)
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, None)
    assert exc.value.name == "thresholds-check-failed" and "burst-over-ceiling:count, check-differs" in exc.value.detail
    assert "4,001" not in exc.value.detail and "2,000" not in exc.value.detail
    files.put(burst_doc())
    files.derive.unlink()
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, None)
    assert exc.value.name == "thresholds-check-unavailable"
    elsewhere = tmp_path / "elsewhere-derive.py"                    # ... or where --derive says
    elsewhere.write_text(DERIVE_DOUBLE, encoding="ascii")
    assert B.load_plan("count", files.thresholds, elsewhere).sends == burst_doc()["burst"]["count_publishes"]
    # derive.py's check reads the file first: what is no JSON, or no object, is its refusal (the real one names it
    # check-unreadable); a document it passes that holds no bursts, or no thresholds, is this tool's own
    for text, name in (("{ this is no JSON", "thresholds-check-failed"), ("[1, 2]", "thresholds-check-failed"),
                       (json.dumps({"the_double_says": "ok", "thresholds": THRESHOLDS}), "thresholds-unreadable"),
                       (json.dumps({"the_double_says": "ok", "burst": [1], "thresholds": THRESHOLDS}), "thresholds-unreadable"),
                       (json.dumps({"the_double_says": "ok", "burst": burst_doc()["burst"], "thresholds": {}}), "thresholds-value")):
        files.thresholds.write_text(text, encoding="ascii")
        with pytest.raises(B.Refused) as exc:
            B.load_plan("count", files.thresholds, elsewhere)
        assert exc.value.name.split(":")[0] == name, (text[:30], exc.value.name)
    files.thresholds.unlink()
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, elsewhere)
    assert exc.value.name == "thresholds-missing"
    inside = REPO / "sdv" / "cloud" / "thresholds-of-a-test.json"          # never written: the refusal comes before any read
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", inside, elsewhere)
    assert exc.value.name == "inside-a-work-tree" and not inside.exists()


# ================================================================================================= the three bursts

@pytest.mark.parametrize("kind", ["count", "bytes", "shadow"])
def test_a_burst_hands_over_what_the_file_derives_inside_60_s_on_its_one_topic_and_then_the_trickle_runs_to_the_ceiling(
        B: Any, files: Any, capsys: Any, kind: str) -> None:
    plan = B.load_plan(kind, files.thresholds, None)
    ran = run(B, files, kind, capsys)
    link, t = ran.link, topics_of(B)
    assert link is not None and ran.rc == B.EXIT["ok"], ran.err
    assert link.connects == [(T0, "opened")]                        # one connection, opened before the burst
    burst = link.begun[:plan.sends]
    want = t.vss_update if kind == "shadow" else t.telemetry
    assert [topic for _when, topic, _p in burst] == [want] * plan.sends
    assert {len(p) for _when, _topic, p in burst} == {plan.size} and len(B.SHADOW_DOCUMENT) < 64
    assert B.BURST_SPREAD_S - 4.0 < burst[-1][0] - burst[0][0] < B.BURST_SPREAD_S + 0.5 < B.WINDOW_S          # paced: not as fast as it goes
    gaps = [b[0] - a[0] for a, b in zip(burst, burst[1:])]
    assert max(gaps) - min(gaps) < 0.11                             # paced evenly over the spread, to the loop's own slice
    start, end = ran.one("burst-start"), ran.one("burst-end")
    assert (start["kind"], end["kind"]) == (kind, kind)
    assert end["met"] is True and end["inside_window"] is True and end["why"] == "complete" and end["ratio"] == 1.0
    attempts = [rec for rec in ran.events("attempt") if rec["phase"] == "burst"]
    assert len(attempts) == plan.sends and {rec["path"] for rec in attempts} == {plan.path}
    # afterwards the trickle: one attempt every 10 s, its two topics in turn, until the 20 minutes are over
    trickle = link.begun[plan.sends:]
    assert [topic for _when, topic, _p in trickle[:4]] == [t.telemetry, t.vss_update, t.telemetry, t.vss_update]
    steps = [b[0] - a[0] for a, b in zip(trickle, trickle[1:])]
    assert min(steps) >= B.TRICKLE_INTERVAL_S - 1e-6 and max(steps) <= B.TRICKLE_INTERVAL_S + 0.11
    assert {len(p) for _when, topic, p in trickle if topic == t.telemetry} == {B.TRICKLE_PUBLISH_BYTES}
    assert {p for _when, topic, p in trickle if topic == t.vss_update} == {B.SHADOW_DOCUMENT}
    assert abs(sum(1 for x in trickle if x[1] == t.telemetry) - sum(1 for x in trickle if x[1] == t.vss_update)) <= 1
    assert 100 < len(trickle) <= B.TRICKLE_MAX and trickle[-1][0] < T0 + B.CEILING_S
    assert link.begun[-1][0] < T0 + B.CEILING_S and link.closes == 1
    stopped = ran.lines[-1]
    assert stopped["event"] == "stopped" and stopped["why"] == "time-ceiling" and stopped["burst_met"] is True and stopped["exit"] == 0
    assert ran.one("ceiling")["which"] == "minutes"
    held_to_its_two_topics(B, ran)


def test_the_payloads_are_filler_of_the_exact_size_and_the_shadow_document_changes_nothing(B: Any) -> None:
    for size in (B.MIN_PUBLISH_BYTES, 256, 100 * 1024):
        data = B.filler("count", size)
        assert len(data) == size and json.loads(data.decode("ascii"))["burst"] == "count" and set(json.loads(data)) == {"v", "burst", "pad"}
        # The envelope's mark for test traffic: queries filter on v = 1.
        assert json.loads(data)["v"] == 0 == B.TEST_TRAFFIC
    with pytest.raises(B.Refused):
        B.filler("trickle", B.MIN_PUBLISH_BYTES - 1)
    # the shadow document names one key, as null: a key that is not there is deleted, so the document adds none
    assert json.loads(B.SHADOW_DOCUMENT) == {"state": {"reported": {B.SHADOW_KEY: None}}} and B.SHADOW_KEY == "burst"


# ================================================================================================= the ceilings

def by_hand(B: Any, kind: str, sends: int, size: int) -> Any:
    return B.Plan(kind, "shadow" if kind == "shadow" else "ingest", sends, size)


def go(B: Any, plan: Any, clock: ManualClock, link: FakeLink, tmp_path: Path, stop: Any = None) -> Tuple[int, List[Dict[str, Any]]]:
    """The run itself, with a plan made by hand: what load_plan would have refused reaches the run's own counters."""
    path = tmp_path / "by-hand.jsonl"
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        log = B.Log(f, clock)
        link.connect()
        rc = B.Run(plan, link, topics_of(B), clock, log, stop if stop is not None else B.Stop()).go()
    return rc, [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


@pytest.mark.parametrize("kind, sends, size, most", [("count", 2050, 256, 2000), ("bytes", 100, 100 * 1024, 81), ("shadow", 75, 0, 60)])
def test_the_ceilings_count_what_was_attempted_and_cut_a_plan_off_whatever_it_asks_for(B: Any, tmp_path: Path, kind: str, sends: int,
                                                                                         size: int, most: int) -> None:
    """Decision 1. A plan over a ceiling cannot come out of load_plan; made by hand it is cut off at the ceiling by the
    run's own counters, which count a hand-over BEFORE it is made. The link here acknowledges nothing at all: a ceiling
    counted on what was acknowledged would never be reached."""
    clock = ManualClock()
    link = FakeLink(clock)
    link.word = lambda i, topic, payload: "failed"
    plan = by_hand(B, kind, sends, size or len(B.SHADOW_DOCUMENT))
    rc, lines = go(B, plan, clock, link, tmp_path)
    burst = [rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "burst"]
    sent = [x for x in link.begun if x[0] <= [rec for rec in lines if rec["event"] == "burst-end"][0]["t_mono"] + T0]
    assert len(burst) == len(sent) == most and rc == B.EXIT["burst-not-met"]
    assert sum(len(p) for _w, _t, p in sent) <= B.CEILINGS["bytes"]
    end = [rec for rec in lines if rec["event"] == "burst-end"][0]
    assert end["met"] is False and end["why"] == "ceiling" and end["ratio"] == 0.0
    which = {"count": "publishes", "bytes": "bytes", "shadow": "shadow_updates"}[kind]
    assert [rec["which"] for rec in lines if rec["event"] == "ceiling"][0] == which


def test_a_publish_that_failed_is_never_handed_over_again(B: Any, files: Any, capsys: Any) -> None:
    """Decision 1: no resend. Every hand-over of a burst is one of its own payloads, each once; what the link failed or
    said nothing about is logged as that and is not tried a second time."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: FakeLink, clock: ManualClock) -> None:
        link.word = lambda i, topic, payload: "failed" if i % 3 == 1 else None

    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["burst-not-met"]
    burst = ran.link.begun[:plan.sends]
    assert len([rec for rec in ran.events("attempt") if rec["phase"] == "burst"]) == plan.sends == len(burst)
    assert len([x for x in ran.link.begun if len(x[2]) == plan.size]) == plan.sends          # each of the burst's payloads once, and never again
    results = [rec["result"] for rec in ran.events("outcome") if rec["phase"] == "burst"]
    assert results.count("failed") == len([i for i in range(plan.sends) if i % 3 == 1])
    assert results.count("acked") == plan.sends - results.count("failed")
    end = ran.one("burst-end")
    assert end["met"] is False and end["why"] == "failed" and 0.6 < end["ratio"] < 0.7 and end["inside_window"] is True
    assert ran.lines[-1]["burst_met"] is False and ran.lines[-1]["exit"] == B.EXIT["burst-not-met"]
    # every attempt line is followed by exactly one outcome line that names it
    stamps = [rec["t_mono"] for rec in ran.events("attempt")]
    assert len(set(stamps)) == len(stamps) and sorted(rec["of"] for rec in ran.events("outcome")) == sorted(stamps)


# ================================================================================================= the time

def test_a_wall_clock_that_steps_moves_neither_the_60_s_nor_the_20_minutes(B: Any, files: Any, capsys: Any) -> None:
    """Decision 2. The wall clock is stepped forward a day in the middle of the burst (a 60 s read from it would be over
    at once) and back two days in the middle of the trickle (20 minutes read from it would never end); every hand-over
    comes when it would have come, and the run ends where it would have ended."""
    plain = run(B, files, "count", capsys)
    files.log.unlink()
    (files.state / B.LEDGER).unlink()

    def script(link: FakeLink, clock: ManualClock) -> None:
        clock.at(T0 + 20.0, lambda: setattr(clock, "wall_s", clock.wall_s + 86400.0))
        clock.at(T0 + 600.0, lambda: setattr(clock, "wall_s", clock.wall_s - 2 * 86400.0))

    stepped = run(B, files, "count", capsys, script=script)
    assert plain.link is not None and stepped.link is not None and stepped.rc == plain.rc == 0
    assert [(round(w, 6), t) for w, t, _p in stepped.link.begun] == [(round(w, 6), t) for w, t, _p in plain.link.begun]
    assert stepped.link.begun[-1][0] < T0 + B.CEILING_S
    assert stepped.one("burst-end") == dict(plain.one("burst-end"), t_wall=stepped.one("burst-end")["t_wall"])
    assert stepped.lines[-1]["why"] == plain.lines[-1]["why"] == "time-ceiling" and len(stepped.lines) == len(plain.lines)
    walls = [rec["t_wall"] for rec in stepped.lines]
    assert walls != sorted(walls)                                   # the log shows the step; nothing was decided by it
    assert [rec["t_mono"] for rec in stepped.lines] == sorted(rec["t_mono"] for rec in stepped.lines)


def test_a_burst_that_cannot_be_handed_over_inside_its_60_s_ends_there_and_says_so(B: Any, files: Any, capsys: Any) -> None:
    """Decision 2. The far end acknowledges so slowly that the tool's own window of publishes in flight is full for most
    of the time: the burst is not through after 60 s. It ends there (nothing of it is handed over later), the log says
    `window-over`, and the exit status is the burst's, whatever the trickle then shows."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: FakeLink, clock: ManualClock) -> None:
        link.ack_after = 3.0

    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["burst-not-met"]
    end = ran.one("burst-end")
    assert end["met"] is False and end["why"] == "window-over" and end["inside_window"] is False and end["ratio"] < 1.0
    burst = [rec for rec in ran.events("attempt") if rec["phase"] == "burst"]
    assert 0 < len(burst) < plan.sends
    start = ran.one("burst-start")["t_mono"]
    assert max(rec["t_mono"] for rec in burst) - start < B.WINDOW_S
    small = [w for w, topic, p in ran.link.begun if len(p) == plan.size]
    assert len(small) == len(burst) and max(small) - min(small) < B.WINDOW_S           # nothing of the burst after its window
    assert ran.lines[-1]["burst_met"] is False and ran.lines[-1]["exit"] == B.EXIT["burst-not-met"]
    assert len(ran.link.begun) > len(burst)                         # the trickle still ran, and is not the burst


# ================================================================================================= a cut, and the trickle after it

def test_after_a_cut_the_trickle_keeps_trying_hands_nothing_to_a_dead_connection_and_logs_each_attempt_as_refused(
        B: Any, files: Any, capsys: Any) -> None:
    """Decision 3. The connection is cut at 300 s and no new one can be opened (a certificate that was deactivated).
    Every 10 s the tool still tries: the attempt is logged, a connection is asked for when the link's own back-off
    allows, nothing is handed over, and no line says a publish was acknowledged."""
    def script(link: FakeLink, clock: ManualClock) -> None:
        clock.at(T0 + 300.0, link.cut)

    ran = run(B, files, "shadow", capsys, script=script)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"]              # the burst was met; the cut came later
    assert max(w for w, _t, _p in link.begun) < T0 + 300.0          # nothing reached the wire after the cut
    cut = ran.one("cut")
    assert 300.0 <= cut["t_mono"] < 310.1 and cut["connection"] == 1
    after = [rec for rec in ran.events("attempt") if rec["t_mono"] > cut["t_mono"]]
    assert len(after) >= 85 and {rec["path"] for rec in after} == {"ingest", "shadow"}
    assert [rec["path"] for rec in after[:4]] in (["ingest", "shadow"] * 2, ["shadow", "ingest"] * 2)
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    assert {outcomes[rec["t_mono"]]["result"] for rec in after} == {"refused"}
    # ... every one but the run's last: that one comes inside the connector's wait for a connection's answer before the time
    # ceiling, and a connection whose answer could come after the ceiling is not asked for (burst-verify-r1, problem 1)
    assert [outcomes[rec["t_mono"]]["connect"] for rec in after] == ["refused"] * (len(after) - 1) + ["ceiling"]
    assert after[-1]["t_mono"] >= B.CEILING_S - B.limits.CONNECT_WAIT_S > after[-2]["t_mono"]
    assert len([c for c in link.connects if c[1] == "refused"]) == len(after) - 1 < B.CONNECTS_MAX
    assert ran.lines[-1]["why"] == "time-ceiling" and after[-1]["t_mono"] < B.CEILING_S
    acked = [rec for rec in ran.events("outcome") if rec["result"] == "acked"]
    assert len(acked) == len(link.begun) and max(rec["t_mono"] for rec in acked) < 300.0 + 1e-6
    held_to_its_two_topics(B, ran)


def opened_again_script(link: FakeLink, clock: ManualClock) -> None:
    """The scenario of the test below and of the recorded example of the log's form: cut at 300 s; the link's own back-off holds
    until 325 s; a new connection can be opened from 350 s."""
    def cut() -> None:
        link.cut()
        link.held_until = T0 + 325.0
        link.back_at = T0 + 350.0
    clock.at(T0 + 300.0, cut)


def test_a_connection_that_can_be_opened_again_is_logged_and_used_and_the_links_own_back_off_is_said(B: Any, files: Any, capsys: Any) -> None:
    """What A4 reads when a breaker did NOT hold: after the cut the link holds its own back-off (said as `held`, no
    connection was asked for), is refused, and then opens a second connection; the trickle goes on, on both topics."""
    ran = run(B, files, "shadow", capsys, script=opened_again_script)
    link, t = ran.link, topics_of(B)
    assert link is not None and ran.rc == 0
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    words = [outcomes[rec["t_mono"]].get("connect") for rec in ran.events("attempt") if 300.0 < rec["t_mono"] < 375.0]
    assert words[:2] == ["held", "held"] and "refused" in words and words[-2:] == ["opened", None]
    assert [rec["connection"] for rec in ran.events("connected")] == [1, 2] and ran.events("connected")[1]["t_mono"] >= 350.0
    late = [x for x in link.begun if x[0] >= T0 + 350.0]
    assert len(late) > 50 and {x[1] for x in late} == {t.telemetry, t.vss_update}
    assert not [x for x in link.begun if T0 + 300.0 <= x[0] < T0 + 350.0]


def test_a_cut_in_the_middle_of_the_burst_ends_the_burst_there(B: Any, files: Any, capsys: Any) -> None:
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: FakeLink, clock: ManualClock) -> None:
        clock.at(T0 + 10.0, link.cut)

    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["burst-not-met"]
    end = ran.one("burst-end")
    assert end["met"] is False and end["why"] == "cut" and ran.one("cut")["t_mono"] <= end["t_mono"]
    assert 0 < len(ran.link.begun) < plan.sends and max(w for w, _t, _p in ran.link.begun) <= T0 + 10.0
    assert len(ran.link.asked) == len(ran.link.begun)               # and nothing was even asked of a link that was down
    assert ran.lines[-1]["why"] == "time-ceiling" and ran.lines[-1]["burst_met"] is False


def test_a_first_connection_that_cannot_be_opened_sends_nothing(B: Any, files: Any, capsys: Any) -> None:
    def script(link: FakeLink, clock: ManualClock) -> None:
        link.connect_fails = True

    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["no-connection"] and ran.link.begun == [] and ran.link.asked == []
    assert [rec["event"] for rec in ran.lines] == ["start", "connect-failed", "stopped"] and ran.lines[-1]["why"] == "no-connection"
    assert ENDPOINT not in ran.text and ENDPOINT not in ran.err + ran.out


# ================================================================================================= a signal

@pytest.mark.parametrize("when, phase, rc", [(15.0, "burst", 4), (400.0, "trickle", 0)])
def test_a_signal_stops_it_at_once_and_the_log_says_so(B: Any, files: Any, capsys: Any, when: float, phase: str, rc: int) -> None:
    """Decision 8. The stop is raised as a signal's handler raises it; from that moment nothing is handed over."""
    stop = B.Stop()
    handed: List[int] = []

    def script(link: FakeLink, clock: ManualClock) -> None:
        def handler() -> None:
            handed.append(len(link.asked))
            stop.set("SIGTERM")
        clock.at(T0 + when, handler)

    ran = run(B, files, "count", capsys, script=script, stop=stop)
    assert ran.link is not None and ran.rc == rc
    assert handed and len(ran.link.asked) == len(ran.link.begun) == handed[0]          # not one hand-over after the handler ran
    assert max(w for w, _t, _p in ran.link.begun) <= T0 + when and ran.clock.monotonic() < T0 + when + 1.0          # at once: no last waits
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["signal"], last["exit"]) == ("stopped", "signal", "SIGTERM", rc) and ran.link.closes == 1
    if phase == "burst":
        end = ran.one("burst-end")
        assert end["met"] is False and end["why"] == "signal" and not [rec for rec in ran.events("attempt") if rec["phase"] == "trickle"]
    else:
        assert ran.one("burst-end")["met"] is True and last["burst_met"] is True


SIGNAL_DRIVER = '''\
import importlib.util, os, signal, sys, threading, time
spec = importlib.util.spec_from_file_location("burst_for_the_signal_test", sys.argv[1])
B = importlib.util.module_from_spec(spec); sys.dont_write_bytecode = True; spec.loader.exec_module(B)
class Handle:
    def state(self): return "acked"
class Link:
    def __init__(self): self.n = 0; self.live = False
    def connect(self): self.live = True
    def up(self): return self.live
    def reopen(self): return "refused"
    def begin(self, topic, payload):
        self.n += 1
        if self.n == 5:
            print("five", flush=True)
        return Handle()
    def give_up(self): self.live = False
    def close(self): self.live = False; print("closed after %d" % self.n, flush=True)
if len(sys.argv) > 6:          # no signal can be sent to this process from outside (not POSIX): raise it from a thread
    threading.Timer(float(sys.argv[6]), lambda: signal.raise_signal(signal.SIGINT)).start()
sys.exit(B.main(["run", "--kind", "count", "--thresholds", sys.argv[2], "--thresholds-sha256", sys.argv[5], "--state", sys.argv[3],
                 "--log", sys.argv[4]],
                env={"SDV_TWIN_THING": "example-thing", "SDV_TWIN_RULE": "example_rule"}, make_link=lambda env, topics: Link()))
'''


# The signals the tool's decision 8 names. Where a signal can be sent to a process (POSIX) the test sends each of them; elsewhere
# the process raises SIGINT in itself, which is the only one it can (nothing here skips: the other is not a case there).
REAL_SIGNALS = ["SIGINT", "SIGTERM"] if os.name == "posix" else ["SIGINT"]


@pytest.mark.parametrize("sent", REAL_SIGNALS)
def test_a_real_signal_ends_the_real_loop_on_the_real_clock(B: Any, files: Any, tmp_path: Path, sent: str) -> None:
    """The tool as a process of its own, with the system's clock and its own signal handlers; only the link is a
    stand-in. On POSIX the test sends SIGINT and SIGTERM, one process each (a Ctrl-C ended in KeyboardInterrupt, with no
    `stopped` line and the link not closed, when only SIGTERM had the tool's handler); elsewhere the process raises SIGINT
    in itself."""
    driver = tmp_path / "driver.py"
    driver.write_text(SIGNAL_DRIVER, encoding="utf-8")
    posix = os.name == "posix"
    argv = [sys.executable, "-B", str(driver), str(BURST_DIR / "burst.py"), str(files.thresholds), str(files.state), str(files.log),
            sha_of(files.thresholds)]
    proc = subprocess.Popen(argv + ([] if posix else ["2.0"]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "five"             # the burst is under way
        if posix:
            proc.send_signal(getattr(signal, sent))
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == B.EXIT["burst-not-met"] and err == "", err
    lines = [json.loads(line) for line in files.log.read_text(encoding="utf-8").split("\n") if line]
    last = lines[-1]
    assert (last["event"], last["why"], last["signal"]) == ("stopped", "signal", sent)
    attempts = len([rec for rec in lines if rec["event"] == "attempt"])
    assert out.strip() == "closed after %d" % attempts and 5 <= attempts < B.load_plan("count", files.thresholds, None).sends
    assert [rec for rec in lines if rec["event"] == "burst-end"][0]["why"] == "signal"


def test_the_watchdog_ends_the_process_after_the_ceiling_and_its_grace_whatever_a_call_is_waiting_for(B: Any, files: Any, monkeypatch: Any,
                                                                                                    capsys: Any) -> None:
    """Decision 2's last net: a thread of the tool's own that reads the RUN'S clock once a second and ends the process once
    that clock is the grace past the time ceiling, when a call into the SDK never came back. Armed by main() whenever the
    clock is the system's, with that clock and the run's start; cancelled by a run that ended by itself. (The look is
    shortened here: the test would wait a second for each.)"""
    ended: List[int] = []
    monkeypatch.setattr(B.os, "_exit", ended.append)
    monkeypatch.setattr(B, "WATCHDOG_LOOK_S", 0.01, raising=False)
    clock = SuspendedClock()
    with open(str(files.log), "w", encoding="utf-8", newline="\n") as f:
        watchdog = B.arm_watchdog(B.Log(f, clock), clock, T0)
        try:
            assert watchdog.daemon and watchdog.is_alive() and watchdog.until == T0 + B.CEILING_S + B.WATCHDOG_GRACE_S
            clock.ahead = B.CEILING_S + B.WATCHDOG_GRACE_S - 0.5          # the run's clock, half a second before that moment:
            time.sleep(0.2)                                               # twenty looks, and none ends the process
            assert ended == [] and watchdog.is_alive()
            clock.ahead = B.CEILING_S + B.WATCHDOG_GRACE_S                # ... and AT it
            watchdog.join(20.0)
            assert not watchdog.is_alive()
        finally:
            watchdog.cancel()
        assert ended == [B.EXIT["watchdog"]]
        idle = B.arm_watchdog(B.Log(f, clock), clock, T0 + 10 * B.CEILING_S)          # one that is cancelled ends nothing
        idle.cancel()
        idle.join(20.0)
        assert not idle.is_alive() and ended == [B.EXIT["watchdog"]]
    lines = [json.loads(line) for line in files.log.read_text(encoding="utf-8").split("\n") if line]
    assert [(rec["event"], rec["why"], rec["exit"], rec["signal"], rec["burst_met"]) for rec in lines] == [
        ("stopped", "watchdog", B.EXIT["watchdog"], None, False)]
    # main() arms it for the system's clock, with that clock and the moment the run's 20 minutes count from, and cancels it
    armed: List[Any] = []

    def arm(log: Any, run_clock: Any, started: float) -> Any:
        armed.append((run_clock, started))
        return types.SimpleNamespace(cancel=lambda: armed.append("cancelled"))

    monkeypatch.setattr(B, "arm_watchdog", arm)
    files.log.unlink()

    class Refusing(FakeLink):
        def connect(self) -> None:
            raise sys.modules["uplink"].UplinkError("no")

    before = B.SystemClock().monotonic()
    rc = B.main(run_argv(files), env=dict(ENV), make_link=lambda env, topics: Refusing(ManualClock()), stop=B.Stop())
    assert rc == B.EXIT["no-connection"] and len(armed) == 2 and armed[1] == "cancelled"
    assert isinstance(armed[0][0], B.SystemClock) and before <= armed[0][1] <= B.SystemClock().monotonic()
    capsys.readouterr()


# ================================================================================================= one run at a time

def test_a_second_start_inside_the_window_gets_no_allowance_whatever_the_wall_clock_says(B: Any, files: Any, capsys: Any) -> None:
    """Decision 4. The first run is stopped by a signal after 100 s. A second start 200 s after the first one's start is
    refused before a link is made, also with the wall clock stepped a day ahead; so is one a second before the window is
    over; the one at the window's end runs."""
    stop = B.Stop()

    def script(link: FakeLink, clock: ManualClock) -> None:
        clock.at(T0 + 100.0, lambda: stop.set("SIGINT"))

    first = run(B, files, "shadow", capsys, script=script, stop=stop)
    assert first.rc == 0 and first.link is not None and first.link.begun
    for later, wall in ((200.0, 200.0), (200.0, 200.0 + 86400.0), (B.CEILING_S - 1.0, B.CEILING_S - 1.0)):
        again = run(B, files, "count", capsys, clock=ManualClock(T0 + later, WALL0 + wall),
                    log=files.top / "logs" / ("again-%d-%d.jsonl" % (later, wall)))
        assert again.rc == B.EXIT["refused"] and "burst: refused: window-held:" in again.err, (later, wall, again.err)
        assert again.link is not None and again.link.connects == [] and again.link.asked == [] and again.lines == []          # nothing was opened
    ok = run(B, files, "count", capsys, clock=ManualClock(T0 + B.CEILING_S, WALL0 + B.CEILING_S), log=files.top / "logs" / "third.jsonl")
    assert ok.rc == 0 and ok.link is not None and ok.link.begun
    claims = [json.loads(line) for line in (files.state / B.LEDGER).read_text(encoding="utf-8").split("\n") if line]
    assert [("claim" in c, "refused" in c) for c in claims] == [(True, False)] + [(True, False), (False, True)] * 3 + [(True, False)]
    assert not [k for c in claims for k in c if k not in ("claim", "refused", "boot", "mono", "wall", "kind")]
    assert ENDPOINT not in json.dumps(claims) and THING not in json.dumps(claims)


def test_the_tool_runs_from_one_flat_directory_as_its_image_holds_it(B: Any, files: Any, tmp_path: Path) -> None:
    """In its image the tool's two files and the connector's four lie side by side in /app, one level under the root. Found
    by the image's own smoke (the first build stopped on it): the module looked two levels above itself for the tree's
    connector directory before it looked beside itself, and /app has no second parent."""
    app = tmp_path / "app"
    app.mkdir()
    for name in ("burst.py", "burst_link.py"):
        (app / name).write_bytes((BURST_DIR / name).read_bytes())
    for name in ("limits.py", "topics.py", "uplink.py", "uplink_aws.py"):
        (app / name).write_bytes((CONNECTOR_DIR / name).read_bytes())
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    where = "import sys; sys.path.insert(0, sys.argv[1]); import burst; print(burst.topics.__file__); print(burst.limits.__file__)"
    p = subprocess.run([sys.executable, "-B", "-c", where, str(app)], capture_output=True, text=True, timeout=120, env=env, cwd=str(tmp_path))
    assert p.returncode == 0 and [Path(line).parent for line in p.stdout.split()] == [app, app], p.stderr          # its own six, not the tree's
    p = subprocess.run([sys.executable, "-B", str(app / "burst.py"), "check", "--thresholds", str(files.thresholds)], capture_output=True, text=True,
                       timeout=120, env=env, cwd=str(tmp_path))
    assert (p.returncode, p.stdout, p.stderr) == (0, "burst: the thresholds file is taken for all three kinds; nothing was sent\n", "")
    # ... and one level under the root, where its file has one parent and no second: the module's own first lines, run with
    # the name the image gives the file (the connector's modules come from this process's path)
    source = (BURST_DIR / "burst.py").read_text(encoding="utf-8")
    at_root = os.path.join(os.path.abspath(os.sep), "app", "burst.py")
    scope: Dict[str, Any] = {"__file__": at_root, "__name__": "burst_one_level_under_the_root"}
    exec(compile(source, at_root, "exec"), scope)                   # raises where the module reaches for a parent that is not there
    assert scope["CEILINGS"] == B.CEILINGS and ".parents[" not in source


def test_the_ledger_is_judged_by_the_wall_clock_only_across_a_boot_and_a_ledger_that_cannot_be_read_refuses(B: Any, files: Any, capsys: Any) -> None:
    ledger = files.state / B.LEDGER

    def claim(mono: float, wall: float, boot: Optional[str]) -> None:
        B.Ledger(ledger).claim(ManualClock(mono, wall, boot), "count")

    claim(T0, WALL0, "boot-a")
    for mono, wall, boot in ((50.0, WALL0 + 100.0, "boot-b"),          # another boot, 100 s later by the wall clock: held
                             (50.0, WALL0 - 5.0, "boot-b"),            # ... and with a wall clock that went back: held
                             (T0 + 50.0, WALL0 + 86400.0, None),       # a host that names no boot is judged by the wall clock: free ...
                             ):
        if boot is None:
            claim(mono, wall, boot)
            continue
        with pytest.raises(B.Refused) as exc:
            claim(mono, wall, boot)
        assert exc.value.name == "window-held"
    with pytest.raises(B.Refused) as exc:          # ... and holds the next one, on whichever clock can be compared
        claim(T0 + 60.0, WALL0 + 86400.0 + 10.0, "boot-a")
    assert exc.value.name == "window-held"
    claim(60.0, WALL0 + 86400.0 + B.CEILING_S, "boot-c")            # another boot, the window over by the wall clock: free
    ledger.unlink()
    # TWO CLAIMS THAT NAME NO BOOT (a host that has none to name): not "the same boot", so the wall clock decides, whatever the
    # monotonic clock says. 5 minutes old by the wall clock and far apart on the monotonic one: held. A whole window old by the wall
    # clock and a few seconds apart on the monotonic one: free.
    claim(T0, WALL0, None)
    with pytest.raises(B.Refused) as exc:
        claim(T0 + 99999.0, WALL0 + 300.0, None)
    assert exc.value.name == "window-held"
    claim(T0 + 10.0, WALL0 + B.CEILING_S, None)
    for garbage in ("{ no json\n", "[1]\n", json.dumps({"claim": "x", "mono": "soon", "wall": 1.0, "boot": None}) + "\n",
                    json.dumps({"claim": "x"}) + "\n", json.dumps({"something": "else"}) + "\n"):
        ledger.write_text(garbage, encoding="utf-8")
        with pytest.raises(B.Refused) as exc:
            claim(T0 + 99999.0, WALL0 + 99999.0, "boot-a")
        assert exc.value.name == "ledger-unreadable", garbage
        assert ledger.read_text(encoding="utf-8") == garbage        # and it is not written over
    ledger.unlink()
    inside = REPO / "sdv" / "cloud" / "burst-state-of-a-test"
    ran = run(B, files, "count", capsys, argv=run_argv(files, state=inside))
    assert ran.rc == B.EXIT["refused"] and "burst: refused: inside-a-work-tree:" in ran.err and not inside.exists() and ran.link is None
    ran = run(B, files, "count", capsys, log=REPO / "sdv" / "cloud" / "burst-log-of-a-test.jsonl")
    assert ran.rc == B.EXIT["refused"] and "burst: refused: inside-a-work-tree:" in ran.err and ran.link is None
    assert not (REPO / "sdv" / "cloud" / "burst-log-of-a-test.jsonl").exists() and not ledger.exists()
    files.log.write_text(json.dumps({"event": "start", "of": "an earlier run"}) + "\n", encoding="utf-8")
    ran = run(B, files, "count", capsys)
    assert ran.rc == B.EXIT["refused"] and "burst: refused: log-exists:" in ran.err and ran.link is None and not ledger.exists()


# ================================================================================================= the topics and the command line

def test_the_two_topics_are_the_connectors_own_from_names_topics_py_checked_and_the_command_line_takes_none(B: Any, files: Any, capsys: Any) -> None:
    """Decision 5. A name that topics.py refuses ends the start before a link is made and before a window is claimed; the
    refusal does not repeat it. The command line takes a kind and four paths, and nothing else."""
    for thing, rule in (("a/b", RULE), ("#", RULE), ("+", RULE), (THING, "example-rule"), (THING, "a/b"), ("", RULE), (THING, ""),
                        ("$aws/things/x", RULE), ("thing\n", RULE)):
        ran = run(B, files, "count", capsys, env={"SDV_TWIN_ENDPOINT": ENDPOINT, "SDV_TWIN_THING": thing, "SDV_TWIN_RULE": rule})
        assert ran.rc == B.EXIT["refused"] and ran.link is None and "burst: refused: names:" in ran.err, (thing, rule, ran.err)
        assert "a/b" not in ran.err and "$aws" not in ran.err and not files.log.exists() and not (files.state / B.LEDGER).exists()
    ran = run(B, files, "count", capsys, env={"SDV_TWIN_ENDPOINT": ENDPOINT})
    assert ran.rc == B.EXIT["refused"] and "burst: refused: names:" in ran.err and ran.link is None
    options = {a.dest: a for a in B.parser()._subparsers._group_actions[0].choices["run"]._actions}          # type: ignore[union-attr]
    assert sorted(options) == ["derive", "kind", "log", "state", "thresholds", "thresholds_sha256"]          # none of argparse's own: no --help
    assert options["kind"].choices == list(B.KINDS) and all(options[k].required for k in ("kind", "thresholds", "thresholds_sha256", "state", "log"))
    for extra in (["--topic", "x/y"], ["--count", "5"], ["--endpoint", ENDPOINT], ["--publishes", "9"], ["--no-ledger"], ["--minutes", "60"]):
        ran = run(B, files, "count", capsys, argv=run_argv(files) + extra)
        assert ran.rc == B.EXIT["arguments"] and ran.link is None and "burst: refused: arguments-invalid:" in ran.err, extra
        assert ENDPOINT not in ran.err and "x/y" not in ran.err
    # and no value of the environment moves a ceiling or a wait: the module reads three names of it and no other
    source = (BURST_DIR / "burst.py").read_text(encoding="utf-8")
    assert sorted(set(re.findall(r"SDV_[A-Z_]+", source))) == ["SDV_TWIN_ENDPOINT", "SDV_TWIN_RULE", "SDV_TWIN_THING"]
    assert "os.environ.get(" not in source and "getenv" not in source


def test_check_reads_the_file_and_connects_to_nothing(B: Any, files: Any, capsys: Any) -> None:
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds)])
    assert ran.rc == 0 and ran.link is None and ran.out == "burst: the thresholds file is taken for all three kinds; nothing was sent\n"
    assert not (files.state / B.LEDGER).exists() and not [n for n in re.findall(r"[0-9]+", ran.out + ran.err) if int(n) in COUNTS]
    files.put(burst_doc(shadow_updates=46))
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds)])
    assert ran.rc == B.EXIT["refused"] and "burst: refused: not-over-twice:shadow:" in ran.err and ran.out == ""


# ================================================================================================= the log

EVENT_KEYS = {"start": {"kind", "ceilings", "window_s", "trickle_s"}, "connected": {"connection"},
              "connect-failed": {"connection", "why"}, "burst-start": {"kind"}, "attempt": {"phase", "path"},
              "outcome": {"of", "phase", "path", "result", "connect"}, "cut": {"connection"},
              "burst-end": {"kind", "met", "inside_window", "why", "ratio", "span_s"}, "ceiling": {"which"},
              "stopped": {"why", "signal", "burst_met", "exit"}}
WALL = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
CONNECT_WORDS = {"opened", "refused", "held", "unanswered", "ceiling"}          # what an outcome's `connect` can say


def lines_are_in_form(B: Any, lines: List[Dict[str, Any]], text: str) -> None:
    assert text.endswith("\n") and "\r" not in text and all(line == json.dumps(json.loads(line), sort_keys=True) for line in text.split("\n")[:-1])
    for rec in lines:
        assert rec["v"] == 1 and rec["event"] in EVENT_KEYS and WALL.fullmatch(rec["t_wall"]), rec
        assert isinstance(rec["t_mono"], float) and rec["t_mono"] >= 0.0
        rest = set(rec) - {"v", "event", "t_mono", "t_wall"}
        assert rest <= EVENT_KEYS[rec["event"]] and rest >= EVENT_KEYS[rec["event"]] - {"connect"}, rec
    assert lines[0]["event"] == "start" and lines[-1]["event"] == "stopped" and [rec["event"] for rec in lines].count("stopped") == 1
    assert {rec["result"] for rec in lines if rec["event"] == "outcome"} <= set(B.RESULTS)
    assert {rec["connect"] for rec in lines if rec["event"] == "outcome" and "connect" in rec} <= CONNECT_WORDS          # a word, never null
    assert not [rec for rec in lines if "connect" in rec and (rec["event"] != "outcome" or rec["phase"] != "trickle")]


def test_the_log_is_one_json_line_per_attempt_and_event_with_no_identifier_and_no_count_of_the_file(B: Any, LS: Any, files: Any, capsys: Any,
                                                                                                    tmp_path: Path) -> None:
    """Decisions 6 and 7. The log's form is an interface: exit-checks and the session read it. No line holds the endpoint,
    the thing, the rule, a topic, a path of this host or a count of the thresholds file; the number of a burst's attempt
    lines is its size, which is why a log stays outside every work tree like the file."""
    device = tmp_path / "device"
    device.mkdir()
    for name in ("device.crt", "device.key", "ca.pem"):
        (device / name).write_text("a placeholder: no key and no certificate\n", encoding="utf-8")
    env = dict(ENV, SDV_TWIN_CERT=str(device / "device.crt"), SDV_TWIN_KEY=str(device / "device.key"), SDV_TWIN_CA=str(device / "ca.pem"))
    for kind in B.KINDS:
        def script(link: FakeLink, clock: ManualClock) -> None:
            begun = clock.monotonic()

            def cut() -> None:
                link.cut()
                link.back_at = begun + 500.0
            clock.at(begun + 300.0, cut)
            link.word = lambda i, topic, payload: "silent" if i == 3 else ("failed" if i == 5 else None)

        log = files.top / "logs" / (kind + ".jsonl")
        clock = ManualClock(T0 + 2 * B.CEILING_S * B.KINDS.index(kind), WALL0 + 2 * B.CEILING_S * B.KINDS.index(kind))
        ran = run(B, files, kind, capsys, clock=clock, script=script, env=env, log=log)
        assert ran.link is not None and ran.lines, ran.err
        lines_are_in_form(B, ran.lines, ran.text)
        t = topics_of(B)
        for word in (ENDPOINT, THING, RULE, t.telemetry, t.vss_update, "$aws", str(device), str(files.top), "device.key", "thresholds.json",
                     str(files.state)):
            assert word not in ran.text and word not in ran.out + ran.err, (kind, word)
        assert LS.findings(ran.text, False, [ENDPOINT, THING, RULE]) == [], kind
        # no count of the file: not as a value of any field but a time, in any line
        for rec in ran.lines:
            values = [v for k, v in rec.items() if k not in ("t_mono", "of", "span_s", "t_wall") and isinstance(v, (int, float))
                      and not isinstance(v, bool)]
            assert not [v for v in values if v in COUNTS and v != 1], rec
        assert ran.one("start")["ceilings"] == B.CEILINGS and "sends" not in ran.text and "size" not in ran.text
        results = [rec["result"] for rec in ran.events("outcome")]
        assert "no-word" in results and "failed" in results and "refused" in results and "acked" in results
        assert results.count("no-word") == 1 == ran.link.given_up          # ... and the connection it was on is given up, once
        assert ran.out == "" and ran.err == ""                      # a run that started says nothing but its log


def test_an_attempt_is_logged_before_it_is_handed_over(B: Any, tmp_path: Path) -> None:
    """Decision 7: write-ahead. When the link is asked for a hand-over, the attempt's line is already in the file."""
    clock = ManualClock()
    path = tmp_path / "ahead.jsonl"
    seen: List[Tuple[int, int]] = []

    class Looking(FakeLink):
        def begin(self, topic: str, payload: bytes) -> FakeHandle:
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]
            seen.append((len([rec for rec in lines if rec["event"] == "attempt"]), len(self.begun)))
            return super().begin(topic, payload)

    link = Looking(clock)
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        link.connect()
        B.Run(by_hand(B, "shadow", 7, len(B.SHADOW_DOCUMENT)), link, topics_of(B), clock, B.Log(f, clock), B.Stop()).go()
    assert len(seen) > 100 and all(logged == handed + 1 for logged, handed in seen)


def test_this_file_holds_no_skip_and_the_tool_imports_no_sdk_and_nothing_of_its_own_but_the_connectors_four_modules() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for word in ("pytest.mark." + "skip", "pytest." + "skip(", "import" + "orskip", "pytest.mark." + "xfail", "pytest." + "xfail("):
        assert word not in text, word
    import ast
    stdlib = set(sys.stdlib_module_names)
    found: Dict[str, set] = {}
    for name in ("burst.py", "burst_link.py"):
        tree = ast.parse((BURST_DIR / name).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0
                names.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("__import__", "import_module"):
                names.add("<an import by a call>")
        found[name] = names - stdlib
    # burst.py reaches its link, and through it the connector's one SDK importer, only when a run is started
    assert found == {"burst.py": {"burst_link", "limits", "topics", "uplink"}, "burst_link.py": {"uplink", "uplink_aws"}}
    assert sorted(p.name for p in BURST_DIR.iterdir() if p.name not in ("__pycache__", "README.md")) == ["Dockerfile", "burst.py", "burst_link.py"]


# ================================================================================================= the link, on the connector's stand-in for the SDK

@pytest.fixture
def sdk_link(B: Any, tmp_path: Path) -> Any:
    """burst_link.py over the stand-in for the SDK that the connector's own uplink is held to (tests/test_sdv_connector.py).
    Loaded under names of this file's; no module named uplink_aws, burst or burst_link is left behind."""
    TC = importlib.import_module("test_sdv_connector")
    had = "uplink_aws" in sys.modules
    assert not had
    mod = _load("sdv_cloud_burst_link_under_test", BURST_DIR / "burst_link.py")
    try:
        aws = sys.modules["uplink_aws"]
        clock = ManualClock()
        sdk = TC.FakeSdk(clock)
        device = tmp_path / "device"
        device.mkdir()
        env = {"SDV_TWIN_ENDPOINT": ENDPOINT}
        for key, name in (("SDV_TWIN_CERT", "device.crt"), ("SDV_TWIN_KEY", "device.key"), ("SDV_TWIN_CA", "ca.pem")):
            (device / name).write_text("a placeholder: no key and no certificate\n", encoding="utf-8")
            env[key] = str(device / name)
        link = mod.BurstLink(aws.settings_from(env), topics_of(B).client_id, sdk.modules(), monotonic=clock.monotonic)
        yield types.SimpleNamespace(mod=mod, aws=aws, sdk=sdk, link=link, clock=clock, env=env, TC=TC)
    finally:
        for name in ("uplink_aws", "sdv_cloud_burst_link_under_test", "burst_link"):
            sys.modules.pop(name, None)


def test_the_link_hands_a_publish_over_without_waiting_and_its_connect_is_the_connectors(B: Any, sdk_link: Any) -> None:
    s, t = sdk_link, topics_of(B)
    link, sdk = s.link, s.sdk
    assert issubclass(s.mod.BurstLink, s.aws.AwsUplink) and not link.up()
    with pytest.raises(B.UplinkError):
        link.begin(t.telemetry, b"x")                               # no connection: nothing is asked of the SDK
    assert sdk.calls == [] and sdk.built == []
    link.connect()
    (connect,) = sdk.connects
    assert (connect["client_id"], connect["clean"], connect["keep_alive"], connect["port"], connect["user"]) == (THING, True, 60, 8883, None)
    assert sdk.built[0].kwargs["reconnect_min_timeout_secs"] == sdk.built[0].kwargs["reconnect_max_timeout_secs"] == B.limits.SDK_RECONNECT_HOLD_S
    sdk.far_end = "mute"                                            # the SDK holds what it is handed: no answer yet
    handles = [link.begin(t.telemetry, b"p%d" % i) for i in range(5)]
    assert [h.state() for h in handles] == [None] * 5 and sdk.waits == [("connect", B.limits.CONNECT_WAIT_S)]          # no wait for any of them
    sdk.unstick()
    assert [h.state() for h in handles] == ["acked"] * 5 and sdk.published(t.telemetry) == [b"p%d" % i for i in range(5)]
    assert all(call[0] != "subscribe" for call in sdk.calls)        # the tool subscribes to nothing
    with pytest.raises(B.UplinkError):
        link.publish(t.telemetry, b"x")                             # the connector's waiting publish is not this tool's
    with pytest.raises(B.UplinkError):
        link.subscribe(t.vss_update_rejected, lambda topic, payload: None)
    # an acknowledged hand-over is the connection's sign of life: a run longer than the connector's 900 s keeps its connection
    sdk.far_end = "answers"
    s.clock.sleep(B.limits.LINK_LIFE_MAX_S - 10.0)
    assert link.begin(t.vss_update, b"alive").state() == "acked"
    s.clock.sleep(20.0)
    assert link.up()
    sdk.far_end = "silent"
    assert link.begin(t.vss_update, b"q").state() == "failed"
    link.close()
    assert not link.up() and sdk.live() is None


def test_nothing_is_handed_to_a_lost_connection_and_what_the_sdk_still_holds_is_never_written(B: Any, sdk_link: Any) -> None:
    """Decision 1, at the link. A connection the SDK lost is given up at once (the SDK's own reconnecting ends with it);
    a hand-over made while it is down is refused before the SDK is asked; when the far end is back and the SDK's own
    timer has run out, nothing more is on the wire. The next connection is a new one, no sooner than the connector's
    back-off."""
    s, t = sdk_link, topics_of(B)
    link, sdk, clock = s.link, s.sdk, s.clock
    link.connect()
    assert link.begin(t.telemetry, b"one").state() == "acked"
    sdk.far_end = "lost"
    flight = link.begin(t.telemetry, b"in flight")                 # written, and the connection is lost before its answer
    assert flight.state() == "failed" and not link.up()
    sdk.far_end = "answers"
    before = len(sdk.calls)
    with pytest.raises(B.UplinkError):
        link.begin(t.telemetry, b"while down")
    assert sdk.calls[before:] == []                                 # the SDK was not asked: nothing is in its queue
    assert link.reopen() == "held"                                  # the connector's own back-off, taken as it is
    clock.sleep(B.limits.RECONNECT_MIN_S)
    built = len(sdk.built)
    with pytest.raises(B.UplinkError):
        link.begin(t.telemetry, b"once the back-off is over")       # a hand-over never opens a connection: only reopen() does
    assert len(sdk.built) == built and not link.up()
    sdk.connect_fails = "AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE"
    assert link.reopen() == "refused" and not link.up()
    sdk.connect_fails = None
    assert link.reopen() == "held"
    clock.sleep(2 * B.limits.RECONNECT_MIN_S)
    assert link.reopen() == "opened" and link.up() and link.reopen() == "up"
    assert link.begin(t.vss_update, b"two").state() == "acked"
    # the far end is back for every connection the SDK ever made, and its own timer runs out: nothing more is written
    wire = [(p.topic, p.payload) for p in sdk.wire]
    clock.sleep(B.limits.SDK_RECONNECT_HOLD_S + 1.0)
    sdk.come_back()
    assert sdk.elapse() == 0 and [(p.topic, p.payload) for p in sdk.wire] == wire
    assert wire == [(t.telemetry, b"one"), (t.telemetry, b"in flight"), (t.vss_update, b"two")] and not [p for p in sdk.wire if p.dup]
    link.give_up()
    assert not link.up() and [c.state for c in sdk.built] == ["disconnected"] * 3
    link.close()


# ================================================================================================= burst-spec: the cases of the plan, the
# ledger, the names, the command line, a cut and a signal at every moment, the link's late connection, and the log's recorded form
# (no new behaviour: each case is one more way in to a test of this file that holds one of it already)

def refused_plan(B: Any, files: Any, doc: Dict[str, Any]) -> Any:
    files.put(doc)
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, None)
    assert not [n for n in re.findall(r"[0-9]+", exc.value.detail.replace(",", "")) if int(n) in COUNTS], exc.value.detail
    return exc.value


def plan_cases() -> List[Tuple[str, str, Any, str]]:
    """(where, which key, the value: a deleted key is DELETED, the refusal's name or its start), for load_plan's refusals."""
    out: List[Tuple[str, str, Any, str]] = []
    for key in ("window_s", "factor", "ceiling_publishes", "ceiling_bytes", "ceiling_shadow_updates", "ceiling_minutes"):
        out.append(("burst", key, True, "design-differs:" + key))
    for key in ("count_publishes", "count_publish_bytes", "bytes_publishes", "bytes_per_publish", "bytes_total", "shadow_updates"):
        for value in (True, 1.0, "5", -1, 0, DELETED):
            out.append(("burst", key, value, "burst-value:" + key))
    for key in ("Firehose.IncomingRecords", "IoT.RulesExecuted.per_execution", "IoT.RulesExecuted.per_5kb_unit", "IoT.PublishIn.Success",
                "Firehose.IncomingBytes", "IoT.UpdateThingShadow.Accepted"):
        for value in (DELETED, True):
            out.append(("thresholds", key, value, "thresholds-value:" + key))
    out.append(("burst", "count_publish_bytes", 128 * 1024 + 1, "burst-inconsistent:count"))
    return out


DELETED = object()


@pytest.mark.parametrize("where, key, value, name", plan_cases(),
                         ids=["%s-%s-%s" % (w, k, "deleted" if v is DELETED else repr(v)) for w, k, v, _n in plan_cases()])
def test_load_plan_refuses_a_value_of_the_file_that_is_no_whole_count_by_the_exact_name_and_says_no_count_of_it(
        B: Any, files: Any, where: str, key: str, value: Any, name: str) -> None:
    """burst-spec, h3 item 1. Every design value of B.DESIGN that is a boolean, every burst value that is a boolean, a float, a
    string, negative, nothing or missing, every threshold that is missing or a boolean, and a count burst whose publishes are
    over the broker's 128 KiB: refused by name before any connection; the refusal repeats no count of the file."""
    doc = burst_doc()
    if value is DELETED:
        del doc[where][key]
    else:
        doc[where][key] = value
    refused = refused_plan(B, files, doc)
    assert refused.name == name, (where, key, value, refused.name)
    assert name.split(":")[0] in ("design-differs", "burst-value", "thresholds-value", "burst-inconsistent")


def test_the_cases_of_the_plan_are_all_of_the_tools_own_design_values_burst_values_and_count_metrics(B: Any) -> None:
    """The list of cases above is the tool's own lists, not a copy that could drift from them."""
    cases = plan_cases()
    assert sorted(key for where, key, value, name in cases if name.startswith("design-differs:")) == sorted(B.DESIGN) and len(B.DESIGN) == 6
    assert sorted({key for where, key, value, name in cases if name.startswith("burst-value:")}) == sorted(B.BURST_KEYS)
    assert [value for where, key, value, name in cases if key == "count_publishes"][:6] == [True, 1.0, "5", -1, 0, DELETED]
    assert sorted({key for where, key, value, name in cases if name.startswith("thresholds-value:")}) == sorted(
        list(B.COUNT_METRICS) + [B.BYTES_METRIC, B.SHADOW_METRIC])
    assert len(cases) == 6 + 6 * 6 + 6 * 2 + 1


def test_a_ledger_line_that_is_no_claim_and_no_refusal_refuses_and_is_not_written_over_while_blank_lines_and_crlf_are_read(
        B: Any, files: Any) -> None:
    """burst-spec, h3 item 2. A claim whose wall time is a boolean, a claim whose boot is a number and a refusal that names no
    nonce refuse `ledger-unreadable` and leave the file's bytes as they were, and so does a claim whose time is NaN, an infinity
    or an integer too large for a float (burst-verify-r1, problem 15); a blank line between two good claims is skipped
    and CRLF line ends on a good claim are read (both are allowed)."""
    ledger = files.state / B.LEDGER
    later = ManualClock(T0 + 99999.0, WALL0 + 99999.0, "boot-a")
    for entry in ({"claim": "x", "mono": 1.0, "wall": True, "boot": None}, {"claim": "x", "mono": 1.0, "wall": 1.0, "boot": 7}, {"refused": 7},
                  # a time that json.loads reads and no comparison can use: NaN holds no window at all, an infinity holds one for ever,
                  # an integer too large for a float breaks the subtraction (verify-r1#15; a hand-written ledger only)
                  {"claim": "x", "mono": float("nan"), "wall": 1.0, "boot": None}, {"claim": "x", "mono": 1.0, "wall": float("nan"), "boot": None},
                  {"claim": "x", "mono": 1.0, "wall": float("inf"), "boot": None}, {"claim": "x", "mono": float("-inf"), "wall": 1.0, "boot": None},
                  {"claim": "x", "mono": 10 ** 400, "wall": 1.0, "boot": None}):
        ledger.write_bytes((json.dumps(entry) + "\n").encode("ascii"))
        before = ledger.read_bytes()
        with pytest.raises(B.Refused) as exc:
            B.Ledger(ledger).claim(later, "count")
        assert exc.value.name == "ledger-unreadable", entry
        assert ledger.read_bytes() == before, entry
    good = [{"claim": "a", "mono": 1.0, "wall": 1.0, "boot": "boot-a", "kind": "count"},
            {"claim": "b", "mono": 2.0, "wall": 2.0, "boot": "boot-a", "kind": "count"}]
    blank = (json.dumps(good[0]) + "\n\n" + json.dumps(good[1]) + "\n").encode("ascii")
    crlf = (json.dumps(good[0]) + "\r\n").encode("ascii")
    for text in (blank, crlf):
        ledger.write_bytes(text)
        B.Ledger(ledger).claim(later, "count")                        # taken: no exception, the earlier claims are old
        written = ledger.read_bytes()
        assert written.startswith(text) and written.count(b"\n") == text.count(b"\n") + 1
        assert json.loads(written.split(b"\n")[-2])["kind"] == "count"


NAME_PAIRS: List[Tuple[Any, Any]] = [
    ("", RULE), (THING, ""), ("a/b", RULE), ("a+b", RULE), ("#", RULE), ("a b", RULE), ("$aws", RULE), (THING, "example-rule"),
    (THING, "a/b"), (THING, "+"), (THING, "a.b"), ("x" * 129, RULE), (THING, "x" * 129), ("thing\n", RULE), (THING, "rule\n"), (None, RULE),
    (THING, 7)]          # the pairs of tests/test_sdv_connector.py's topics test, each of which topics.py refuses


def test_every_pair_of_names_topics_py_refuses_ends_the_start_before_a_link_is_made_and_is_not_repeated(B: Any, files: Any, capsys: Any) -> None:
    """burst-spec, h3 item 3 (decision 5)."""
    assert len(NAME_PAIRS) == 17
    for thing, rule in NAME_PAIRS:
        env: Any = {"SDV_TWIN_ENDPOINT": ENDPOINT, "SDV_TWIN_THING": thing, "SDV_TWIN_RULE": rule}
        ran = run(B, files, "count", capsys, env=env)
        assert ran.rc == B.EXIT["refused"] and "burst: refused: names:" in ran.err, (thing, rule, ran.err)
        assert ran.link is None and not files.log.exists() and not (files.state / B.LEDGER).exists(), (thing, rule)
        for name in (thing, rule):
            if isinstance(name, str) and name and name not in (THING, RULE):
                assert name not in ran.err, (thing, rule)


def test_a_command_line_that_cannot_be_read_is_one_line_on_standard_error_and_nothing_else(B: Any, files: Any, capsys: Any) -> None:
    """burst-spec, h3 item 4. Status 2, exactly one line that starts `burst: refused: arguments-invalid:`, an empty standard
    output and no link."""
    everything = run_argv(files, "everything")
    assert run_argv(files)[1:3] == ["--kind", "count"]
    cases = [["run"], run_argv(files)[:1] + run_argv(files)[3:], everything,
             ["check", "--thresholds", str(files.thresholds), "--state", str(files.state)],
             ["check", "--thresholds", str(files.thresholds), "--log", str(files.log)], []]
    for argv in cases:
        ran = run(B, files, "count", capsys, argv=argv)
        assert ran.rc == B.EXIT["arguments"] == 2 and ran.out == "" and ran.link is None, argv
        assert ran.err.count("\n") == 1 and ran.err.startswith("burst: refused: arguments-invalid:") and ran.err.endswith("\n"), (argv, ran.err)
        assert not files.log.exists() and not (files.state / B.LEDGER).exists()


@pytest.mark.parametrize("kind", ["count", "bytes", "shadow"])
@pytest.mark.parametrize("when", [1.0, 20.0, 39.0, 45.0, 300.0, 1195.0])
def test_a_cut_at_any_moment_is_one_line_hands_over_nothing_after_it_and_ends_the_burst_only_when_it_came_inside_it(
        B: Any, files: Any, capsys: Any, kind: str, when: float) -> None:
    """burst-spec, h3 item 5 (decision 3). The connection is cut `when` seconds into the run, and no new one can be opened. A
    burst is INSIDE the cut when its last hand-over is later than the cut: that is `(sends - 1)` gaps of the spread from the
    burst's start, so that the cut at 39 s is inside a count burst (last hand-over at about 39.97 s) and a shadow burst (about
    39.15 s) and after a bytes burst (38.4 s)."""
    plan = B.load_plan(kind, files.thresholds, None)
    last_hand_over = (plan.sends - 1) * float(B.BURST_SPREAD_S) / plan.sends

    def script(link: FakeLink, clock: ManualClock) -> None:
        clock.at(T0 + when, link.cut)

    ran = run(B, files, kind, capsys, script=script)
    link = ran.link
    assert link is not None
    assert len(ran.events("cut")) == 1 and ran.one("cut")["connection"] == 1          # one line for the one connection that was lost
    assert len(link.asked) == len(link.begun)                                          # nothing was even asked of a link that was down
    assert not [w for w, _topic, _payload in link.begun if w > T0 + when]              # and nothing reached the wire after the cut
    end = ran.one("burst-end")
    if when < last_hand_over:
        assert end["met"] is False and end["why"] == "cut" and ran.rc == B.EXIT["burst-not-met"], (kind, when, end)
    else:
        assert end["met"] is True and end["why"] == "complete" and ran.rc == B.EXIT["ok"], (kind, when, end)
    assert ran.lines[-1]["event"] == "stopped" and ran.lines[-1]["why"] == "time-ceiling" and ran.lines[-1]["exit"] == ran.rc


@pytest.mark.parametrize("kind", ["count", "bytes", "shadow"])
@pytest.mark.parametrize("when", [0.5, 15.0, 39.9, 45.0, 400.0])
def test_a_signal_at_any_moment_stops_every_hand_over_and_the_status_is_the_bursts(B: Any, files: Any, capsys: Any, kind: str,
                                                                                   when: float) -> None:
    """burst-spec, h3 item 6 (decision 8). The handler records how many hand-overs had been asked of the link when it ran."""
    stop = B.Stop()
    handed: List[int] = []

    def script(link: FakeLink, clock: ManualClock) -> None:
        def handler() -> None:
            handed.append(len(link.asked))
            stop.set("SIGTERM")
        clock.at(T0 + when, handler)

    ran = run(B, files, kind, capsys, script=script, stop=stop)
    link = ran.link
    assert link is not None and len(handed) == 1
    assert len(link.asked) == len(link.begun) == handed[0], (kind, when)                # not one hand-over after the handler ran
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["signal"]) == ("stopped", "signal", "SIGTERM")
    met = ran.one("burst-end")["met"]
    assert ran.rc == (B.EXIT["ok"] if met else B.EXIT["burst-not-met"]) == last["exit"] and last["burst_met"] is met, (kind, when)
    assert link.closes == 1


def test_a_connect_the_sdk_never_answers_is_disconnected_when_it_answers_late_and_a_link_that_was_never_opened_asks_for_no_other(
        B: Any, sdk_link: Any) -> None:
    """burst-spec, h3 item 8. The first connect hangs: the link raises, and when the SDK answers after all the connection nobody
    uses is disconnected at once and counted. reopen() asks for nothing before a first connect succeeded (`refused`; the tool
    itself ends a run at `connect-failed`, exit status 3, and never calls it); where the first connect succeeded, was lost and
    the next hangs, it says `unanswered` while the SDK has not answered, and the late connection is disconnected the same way."""
    s = sdk_link
    link, sdk, clock = s.link, s.sdk, s.clock
    sdk.connect_fails = "hangs"
    with pytest.raises(B.UplinkError):
        link.connect()
    assert link.reopen() == "refused"                          # NOT `unanswered`: the link was never opened (the plan's case, see the notes)
    sdk.connect_fails = None
    assert sdk.answer_connects() == 1
    assert sdk.built[0].state == "disconnected" and link.counters["late"] == 1 and link.up() is False
    # the case where reopen() has a meaning for the tool: opened once, lost, and the next connect never answered
    again = s.mod.BurstLink(s.aws.settings_from(s.env), topics_of(B).client_id, sdk.modules(), monotonic=clock.monotonic)
    link2, built = again, len(sdk.built)
    link2.connect()
    sdk.lose()
    assert not link2.up()
    clock.sleep(2 * B.limits.RECONNECT_MIN_S)
    sdk.connect_fails = "hangs"
    assert link2.reopen() == "refused"                         # asked for, and the SDK did not answer within the wait
    assert [c.state for c in sdk.built[built:]] == ["disconnected", "connecting"]
    assert link2.reopen() == "unanswered" and link2.reopen() == "unanswered" and not link2.up()
    sdk.connect_fails = None
    late = link2.counters["late"]
    assert sdk.answer_connects() == 1
    assert sdk.built[-1].state == "disconnected" and link2.counters["late"] == late + 1 and link2.up() is False
    with pytest.raises(B.UplinkError):
        link2.begin(topics_of(B).telemetry, b"nothing goes to a connection nobody uses")


# ================================================================================================= burst-spec: the fixtures

EXAMPLE_ABOUT = ("A made-up thresholds document for the burst tool's tests: documentation values, no design the owner chose, no figure "
                 "derive.py wrote.")


def test_the_thresholds_example_is_the_made_up_document_of_this_file_and_holds_nothing_else() -> None:
    """burst-spec, h4. tests/fixtures/burst-thresholds-example.json is burst_doc() written out, with the note that says what it is."""
    raw = (FIXTURES / "burst-thresholds-example.json").read_bytes()
    text = raw.decode("ascii")
    assert "\r" not in text and text.endswith("\n") and text == json.dumps(json.loads(text), indent=1, sort_keys=True) + "\n"
    doc = json.loads(text)
    assert list(doc)[0] == "_about" and doc["_about"] == EXAMPLE_ABOUT
    del doc["_about"]
    assert doc == burst_doc()
    assert text == json.dumps(dict({"_about": EXAMPLE_ABOUT}, **burst_doc()), indent=1, sort_keys=True) + "\n"


def test_the_logs_form_is_the_recorded_example(B: Any, LS: Any, files: Any, capsys: Any) -> None:
    """burst-spec, h4. tests/fixtures/burst-log-example.jsonl is the log of a shadow run on the fake link and the manual clock
    with the scenario of `a connection that can be opened again`: the form written down for whoever reads a log at A4 or A5.
    The run is deterministic, so it gives the fixture byte for byte; the example is in the form, and the leak scan finds nothing
    in it. It records no run against a broker or an account."""
    ran = run(B, files, "shadow", capsys, script=opened_again_script)
    assert ran.rc == B.EXIT["ok"] and ran.link is not None
    fixture = (FIXTURES / "burst-log-example.jsonl").read_bytes()
    assert files.log.read_bytes() == fixture
    text = fixture.decode("utf-8")
    lines = [json.loads(line) for line in text.split("\n") if line]
    lines_are_in_form(B, lines, text)
    assert LS.findings(text, False, [ENDPOINT, THING, RULE]) == []
    assert [rec["event"] for rec in lines][:3] == ["start", "connected", "burst-start"] and lines[-1]["why"] == "time-ceiling"
    assert [rec["connection"] for rec in lines if rec["event"] == "connected"] == [1, 2] and len([r for r in lines if r["event"] == "cut"]) == 1


# ================================================================================================= burst-fix-r2 (burst-verify-r1's
# problems 1, 9, 10, 11 and 12): the time ceiling at a connection that is opened late, the trickle's second nets, the log's form
# in two places, a directory that cannot be written, a request for help

class SlowLink(FakeLink):
    """A link whose connects take time on the test's clock, as the tool's own link waits for the SDK's answer to a connect
    (the connector's CONNECT_WAIT_S at the most): `first_takes` for connect(), `reopen_takes` for every reopen() asked at
    or after `slow_from`. A reopen() is remembered with the moment it was ASKED (`reopens`); `connects` keeps the moment
    it was answered, and `closed_at` the moment the link was closed."""

    def __init__(self, clock: ManualClock) -> None:
        super().__init__(clock)
        self.first_takes = 0.0
        self.reopen_takes = 0.0
        self.slow_from: Optional[float] = None
        self.reopens: List[float] = []
        self.closed_at: List[float] = []

    def connect(self) -> None:
        if self.first_takes:
            self.clock.sleep(self.first_takes)
        super().connect()

    def reopen(self) -> str:
        now = self.clock.monotonic()
        self.reopens.append(now)
        if self.reopen_takes and self.slow_from is not None and now >= self.slow_from:
            self.clock.sleep(self.reopen_takes)
        return super().reopen()

    def close(self) -> None:
        self.closed_at.append(self.clock.monotonic())
        super().close()


class SuspendedClock(ManualClock):
    """A manual clock that can be moved forward from outside, as CLOCK_BOOTTIME moves over a host that slept: `ahead` is
    added to what the clock says. A sleep moves it as before."""

    ahead = 0.0

    def monotonic(self) -> float:
        return self.t + self.ahead

    def wall(self) -> float:
        return self.wall_s + self.ahead


def test_no_connection_is_asked_for_when_its_answer_could_come_at_or_after_the_time_ceiling(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 1 (its cases B15 and K7). The link waits for a connection's answer, the connector's
    CONNECT_WAIT_S at the most. A tick that began before the ceiling asked for a connection and handed over when it had
    come: after the 20 minutes, on a connection opened after them. DECIDED: in the last CONNECT_WAIT_S of a run no
    connection is asked for. The attempt is logged all the same, its outcome says `connect: ceiling`, and no line of its
    own is written for it: the `ceiling minutes` line follows within that wait. Here every connect takes 5 s, and a new
    connection could be opened only from 5 s before the ceiling on."""
    wait = B.limits.CONNECT_WAIT_S

    def script(link: Any, clock: ManualClock) -> None:
        link.reopen_takes, link.slow_from = 5.0, T0

        def cut() -> None:
            link.cut()
            link.back_at = T0 + B.CEILING_S - 5.0
        clock.at(T0 + 1100.0, cut)

    ran = run(B, files, "shadow", capsys, script=script, link_class=SlowLink)
    link = ran.link
    assert isinstance(link, SlowLink) and ran.rc == B.EXIT["ok"]
    assert max(w for w, _t, _p in link.begun) < T0 + 1100.0 and not [w for w in link.asked if w >= T0 + 1100.0]          # no hand-over after the cut
    assert link.reopens and all(asked < T0 + B.CEILING_S - wait for asked in link.reopens)          # none asked whose answer could come too late
    assert [c for c in link.connects if c[1] == "opened"] == [(T0, "opened")] and [rec["connection"] for rec in ran.events("connected")] == [1]
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    after = [rec for rec in ran.events("attempt") if rec["t_mono"] > ran.one("cut")["t_mono"]]
    assert len(after) > 5 and {outcomes[rec["t_mono"]]["result"] for rec in after} == {"refused"}
    assert [outcomes[rec["t_mono"]]["connect"] for rec in after] == ["refused"] * (len(after) - 1) + ["ceiling"]
    assert after[-1]["t_mono"] >= B.CEILING_S - wait > after[-2]["t_mono"]          # the one attempt of the run's last 10 s
    assert len(link.reopens) == len(after) - 1 == len(ran.events("connect-failed"))
    assert [rec["which"] for rec in ran.events("ceiling")] == ["minutes"] and ran.lines[-1]["why"] == "time-ceiling" and link.closes == 1
    lines_are_in_form(B, ran.lines, ran.text)
    assert B.CONNECT_ANSWER_S == wait == 10.0                       # the wait the tool counts with is the connector's own


def test_a_connection_that_opens_at_or_after_the_time_ceiling_is_handed_nothing_and_the_run_ends_there(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 1, the second net. The clock is read again right before every hand-over of the trickle. A
    link that took LONGER over its connect than the connector's wait (12 s here; the tool cannot know) was asked while
    its answer was still due inside the run, and opens the connection after the ceiling. The log says that it opened
    (`connected`: it did); the attempt's outcome is `refused` with `connect: opened`; nothing is handed over; and the run
    ends there: the `ceiling minutes` line, and the link is closed at the moment the connection had opened."""
    wait = B.limits.CONNECT_WAIT_S

    def script(link: Any, clock: ManualClock) -> None:
        link.reopen_takes, link.slow_from = wait + 2.0, T0 + 1185.0

        def cut() -> None:
            link.cut()
            link.back_at = T0 + 1185.0
        clock.at(T0 + 1100.0, cut)

    ran = run(B, files, "shadow", capsys, script=script, link_class=SlowLink)
    link = ran.link
    assert isinstance(link, SlowLink) and ran.rc == B.EXIT["ok"]
    asked, (opened_at, word) = link.reopens[-1], link.connects[-1]
    assert asked < T0 + B.CEILING_S - wait and word == "opened" and opened_at >= T0 + B.CEILING_S          # the case this test is about
    assert max(w for w, _t, _p in link.begun) < T0 + 1100.0 and not [w for w in link.asked if w >= T0 + 1100.0]          # nothing was handed over
    assert [rec["connection"] for rec in ran.events("connected")] == [1, 2] and ran.events("connected")[1]["t_mono"] >= B.CEILING_S
    last = ran.events("attempt")[-1]
    (outcome,) = [rec for rec in ran.events("outcome") if rec["of"] == last["t_mono"]]
    assert (outcome["result"], outcome["connect"]) == ("refused", "opened")
    assert [rec["event"] for rec in ran.lines[-4:]] == ["connected", "outcome", "ceiling", "stopped"]
    assert ran.lines[-2]["which"] == "minutes" and ran.lines[-1]["why"] == "time-ceiling" and ran.lines[-1]["exit"] == B.EXIT["ok"]
    assert link.closed_at == [opened_at]                            # closed as the run ends, with no wait in between
    lines_are_in_form(B, ran.lines, ran.text)


def test_the_20_minutes_count_from_the_start_whatever_the_first_connection_takes(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 1 (its mutant V30). The first connect takes the connector's whole wait. The run's ceiling
    is 20 minutes from its START, the moment its claim was made: counted from the connection it would come 10 s later,
    and one more attempt of the trickle would be handed over at or after start + 1,200 s."""
    wait = B.limits.CONNECT_WAIT_S

    def script(link: Any, clock: ManualClock) -> None:
        link.first_takes = wait

    ran = run(B, files, "count", capsys, script=script, link_class=SlowLink)
    link = ran.link
    assert isinstance(link, SlowLink) and ran.rc == B.EXIT["ok"]
    assert link.connects == [(T0 + wait, "opened")] and ran.one("connected")["t_mono"] == wait
    assert max(w for w, _t, _p in link.begun) < T0 + B.CEILING_S and max(rec["t_mono"] for rec in ran.events("attempt")) < B.CEILING_S
    assert T0 + B.CEILING_S <= link.closed_at[0] < T0 + B.CEILING_S + 1.0          # ... and the run ended at that ceiling, not 10 s after it
    assert ran.lines[-1]["why"] == "time-ceiling" and [rec["which"] for rec in ran.events("ceiling")] == ["minutes"]


@pytest.mark.parametrize("slept", ["in-the-first-connect", "in-the-burst"])
def test_a_burst_that_reaches_the_time_ceiling_ends_there_and_nothing_is_handed_over_after_it(B: Any, files: Any, capsys: Any, slept: str) -> None:
    """burst-verify-r1, problem 1 (its mutant V49, its case B21). A burst's own 60 s end long before the 20 minutes unless
    the clock moved under it: a host that slept (the clock is CLOCK_BOOTTIME). In the first case it slept 19.5 minutes
    while the first connection was being opened: the burst begins 30 s before the ceiling and is cut off AT it, in the
    middle of its 40 s. In the second it slept 30 minutes, 20 s into the burst. No trickle follows either."""
    plan = B.load_plan("count", files.thresholds, None)
    clock = SuspendedClock()

    def script(link: Any, clock_: ManualClock) -> None:
        if slept == "in-the-first-connect":
            link.first_takes = B.CEILING_S - 30.0
        else:
            clock_.at(T0 + 20.0, lambda: setattr(clock, "ahead", 1800.0))

    ran = run(B, files, "count", capsys, clock=clock, script=script, link_class=SlowLink)
    link = ran.link
    assert isinstance(link, SlowLink) and ran.rc == B.EXIT["burst-not-met"]
    begun = [w for w, _t, _p in link.begun]
    assert 100 < len(begun) < plan.sends and max(begun) < T0 + B.CEILING_S and len(link.asked) == len(begun)
    if slept == "in-the-first-connect":
        assert max(begun) > T0 + B.CEILING_S - 1.0                  # handed over right up to the ceiling, and not at it
    else:
        assert max(begun) <= T0 + 20.0
    end = ran.one("burst-end")
    assert (end["met"], end["why"], end["inside_window"]) == (False, "ceiling", False)
    assert {rec["which"] for rec in ran.events("ceiling")} == {"minutes"}
    assert not [rec for rec in ran.events("attempt") if rec["phase"] == "trickle"]
    assert ran.lines[-1]["why"] == "time-ceiling" and ran.lines[-1]["burst_met"] is False and link.closes == 1


def test_the_tick_bounds_the_trickle_and_its_connections_and_the_run_counts_both_as_a_second_net(B: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """burst-verify-r1, problem 9. DECIDED: both counters stay, as second nets. In a run as built the TICK bounds them:
    the first attempt of the trickle comes 10 s after the burst's end and none at the time ceiling, so a run has 119
    attempts of the trickle at the most and asks for fewer connections still, and the two words `ceiling trickle` and
    `ceiling connects` are written by no run. The counters hold what the tick holds should the pacing itself ever fail,
    as the burst's own counters stand behind the file's check; like those they are met here by hand, by moving them
    under what a run reaches."""
    one = by_hand(B, "shadow", 1, len(B.SHADOW_DOCUMENT))          # a burst that takes no time: the most ticks a run can have

    def gone(cut_at: Optional[float]) -> Tuple[FakeLink, int, List[Dict[str, Any]]]:
        clock = ManualClock()
        link = FakeLink(clock)
        if cut_at is not None:
            clock.at(T0 + cut_at, link.cut)
        rc, lines = go(B, one, clock, link, tmp_path)
        return link, rc, lines

    def trickle_of(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "trickle"]

    # as built, with a cut right after the burst that no connection comes back from: the most of both
    link, rc, lines = gone(1.0)
    trickle = trickle_of(lines)
    assert rc == B.EXIT["ok"] and len(trickle) == 119 == B.TRICKLE_MAX - 1
    assert [round(rec["t_mono"], 3) for rec in trickle][::59] == [10.0, 600.0, 1190.0]
    assert len(link.connects) - 1 == 118 < B.CONNECTS_MAX == B.TRICKLE_MAX          # every attempt but the run's last asked for one
    assert [rec["which"] for rec in lines if rec["event"] == "ceiling"] == ["minutes"]
    assert [rec["path"] for rec in trickle].count("ingest") == 60 and [rec["path"] for rec in trickle].count("shadow") == 59
    # the trickle's net, moved to 7: seven attempts, the word, and the run ends as at the time ceiling
    monkeypatch.setattr(B, "TRICKLE_MAX", 7)
    link, rc, lines = gone(None)
    assert len(trickle_of(lines)) == 7 and len(link.begun) == 1 + 7 and [rec["which"] for rec in lines if rec["event"] == "ceiling"] == ["trickle"]
    assert (lines[-1]["event"], lines[-1]["why"], round(lines[-1]["t_mono"], 3)) == ("stopped", "time-ceiling", 80.0) and link.closes == 1
    monkeypatch.setattr(B, "TRICKLE_MAX", 120)
    # the connections' net, moved to 3: three are asked for, then none, and each attempt says so; the trickle goes on trying
    monkeypatch.setattr(B, "CONNECTS_MAX", 3)
    link, rc, lines = gone(1.0)
    trickle = trickle_of(lines)
    assert [when - T0 for when, word in link.connects[1:]] == [10.0, 20.0, 30.0] and len(trickle) == 119
    outcomes = {rec["of"]: rec for rec in lines if rec["event"] == "outcome"}
    assert [outcomes[rec["t_mono"]]["connect"] for rec in trickle] == ["refused"] * 3 + ["ceiling"] * 116
    assert [rec["which"] for rec in lines if rec["event"] == "ceiling"] == ["connects"] * 116 + ["minutes"]
    before = [lines[i - 1] for i, rec in enumerate(lines) if rec["event"] == "outcome" and rec.get("connect") == "ceiling"]
    assert [(rec["event"], rec.get("which")) for rec in before] == [("ceiling", "connects")] * 116          # the net's line stands before each


class RefusingAfterAll(FakeLink):
    """A link that says it is up and refuses a hand-over all the same, from `refuses_from` on: with the tool's own link, a
    connection lost between the tool's look and its hand-over."""

    refuses_from: Optional[float] = None

    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        now = self.clock.monotonic()
        if self.refuses_from is not None and now >= self.refuses_from:
            self.asked.append(now)
            raise self._error()("not connected to %s" % ENDPOINT)
        return super().begin(topic, payload)


def test_an_outcome_names_a_connection_only_when_one_was_looked_for(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 10, the first place (its case B13). A trickle attempt whose link said it was up and then
    refused the hand-over looked for no connection: its outcome is `refused` and holds NO `connect` key. It held
    `"connect": null`, a word the log's form does not have."""
    def script(link: Any, clock: ManualClock) -> None:
        link.refuses_from = T0 + 100.0

    ran = run(B, files, "shadow", capsys, script=script, link_class=RefusingAfterAll)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"] and link.connects == [(T0, "opened")] and not ran.events("cut", "connect-failed")
    trickle = [rec for rec in ran.events("outcome") if rec["phase"] == "trickle"]
    late = [rec for rec in trickle if rec["t_mono"] > 100.0]
    assert len(late) > 100 and {rec["result"] for rec in late} == {"refused"} and len(trickle) - len(late) > 3
    assert {rec["result"] for rec in trickle if rec["t_mono"] <= 100.0} == {"acked"}
    assert not [rec for rec in trickle if "connect" in rec] and '"connect"' not in ran.text          # the key is not there: never null
    lines_are_in_form(B, ran.lines, ran.text)


class Breaking(FakeLink):
    """A link whose begin() raises an error no check names at its `breaks_at`-th call."""

    breaks_at = 0

    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        if len(self.asked) + 1 == self.breaks_at:
            self.asked.append(self.clock.monotonic())
            raise RuntimeError("a fault of the link's own, at %s" % ENDPOINT)
        return super().begin(topic, payload)


def fold(text: str) -> str:
    """A text with its white space folded and its code marks taken out: the docstring's words and the README's are compared."""
    return " ".join(text.replace("`", "").split())


def test_a_run_that_did_not_end_by_itself_leaves_attempts_without_an_outcome_and_the_form_says_so(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 10, the second place (its case B14b). An error no check names ends the run where it came
    (exit status 5). The hand-overs then without an answer, and the attempt the error came in, get NO outcome line: the
    tool does not know what became of them and writes nothing it does not know. The form said `an attempt is logged ...
    again with what became of it` and nothing else; it says now which two ends leave attempts without an outcome (the
    watchdog's is the other: it ends the process as it stands), and that a reader counts each as possibly on the wire."""
    def script(link: Any, clock: ManualClock) -> None:
        link.ack_after, link.breaks_at = 0.9, 301

    ran = run(B, files, "count", capsys, script=script, link_class=Breaking)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["error"] == 5 and len(link.begun) == 300 and link.closes == 1
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["exit"], last["burst_met"]) == ("stopped", "error", 5, False)
    attempts = [rec["t_mono"] for rec in ran.events("attempt")]
    named = [rec["of"] for rec in ran.events("outcome")]
    assert len(attempts) == 301 and len(set(named)) == len(named) and set(named) < set(attempts)
    without = sorted(set(attempts) - set(named))
    assert without == attempts[-len(without):] and len(without) > 2          # the last ones: those in flight, and the one the error came in
    assert len(without) == 1 + len([w for w, _t, _p in link.begun if w + link.ack_after > link.asked[-1]])
    assert {rec["result"] for rec in ran.events("outcome")} == {"acked"} and not ran.events("burst-end")
    said = ("Two ends leave attempt lines WITHOUT an outcome: stopped with why error and with why watchdog. Such a run did not end by itself: "
            "the hand-overs then without an answer, and the attempt an error came in, get no outcome line, because the tool does not know "
            "what became of them. A reader counts each as possibly on the wire.")
    rest = "At every other end each attempt has exactly one outcome."          # (burst-review-fix-exact: a sentence stands between the two)
    assert said in fold(str(B.__doc__)) and said in fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    assert rest in fold(str(B.__doc__)) and rest in fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))


def test_a_state_directory_or_a_log_directory_that_cannot_be_written_is_refused_by_a_name_before_the_window_is_claimed(
        B: Any, files: Any, capsys: Any, monkeypatch: Any) -> None:
    """burst-verify-r1, problem 11 (its cases B18a and B18b). Both ended in a traceback (PermissionError, with the path),
    and for the log's directory the window had been claimed first: a run that never started held 20 minutes. Refused now
    by a name, with the other checks: before a link is made and before the claim. On POSIX the directories really are
    mode 555 (a container's user that is not the directories' owner); everywhere, the system's answer is also given by
    hand, for the directories, for a ledger and for an empty log file of another user's."""
    ledger = files.state / B.LEDGER

    def refused(name: str) -> None:
        ran = run(B, files, "count", capsys)
        assert ran.rc == B.EXIT["refused"] and ran.link is None and "burst: refused: %s:" % name in ran.err, ran.err
        assert ran.err.count("\n") == 1 and str(files.top) not in ran.err and ran.out == ""          # one line, and no path in it
        assert not ledger.exists() or ledger.stat().st_size == 0          # no window was claimed

    if os.name == "posix" and os.geteuid() != 0:
        for directory, name in ((files.state, "state-unwritable"), (files.log.parent, "log-unwritable")):
            directory.chmod(0o555)
            try:
                refused(name)
            finally:
                directory.chmod(0o755)
            assert not files.log.exists() and not ledger.exists()
    real = os.access

    def answered(unwritable: Path) -> Callable[..., bool]:
        def access(path: Any, mode: int, **kwargs: Any) -> bool:
            if mode & os.W_OK and os.path.abspath(str(path)) == os.path.abspath(str(unwritable)):
                return False
            return bool(real(path, mode, **kwargs))
        return access

    for unwritable, name in ((files.state, "state-unwritable"), (files.log.parent, "log-unwritable")):
        monkeypatch.setattr(B.os, "access", answered(unwritable))
        refused(name)
        assert not files.log.exists() and not ledger.exists()
    ledger.write_text("", encoding="utf-8")                         # a ledger that is there, and an empty log file, of another user's
    monkeypatch.setattr(B.os, "access", answered(ledger))
    refused("state-unwritable")
    ledger.unlink()
    files.log.write_text("", encoding="utf-8")
    monkeypatch.setattr(B.os, "access", answered(files.log))
    refused("log-unwritable")
    assert files.log.read_text(encoding="utf-8") == "" and not ledger.exists()
    monkeypatch.setattr(B.os, "access", real)
    ran = run(B, files, "count", capsys)                            # ... and with everything writable the same start is taken
    assert ran.rc == B.EXIT["ok"] and ran.link is not None and ledger.exists() and ran.lines[0]["event"] == "start"


def test_a_request_for_help_and_an_abbreviated_option_are_command_lines_that_cannot_be_read(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 12 (its case B19). `--help` printed argparse's usage and left main() by SystemExit(0):
    status 0, which the tool's table gives to a burst that met its goal and to `check`'s yes. And an option was taken by
    any prefix of its name (`--k count --thr F --st D --lo L` reached the state directory's check). Both are command
    lines that cannot be read now: status 2 and the one line, which names the two command lines and is all the help
    there is."""
    full = run_argv(files)
    short = ["run", "--k", "count", "--thr", str(files.thresholds), "--thresholds-sha256", sha_of(files.thresholds), "--st", str(files.state),
             "--lo", str(files.log)]
    cases = [["--help"], ["-h"], ["run", "--help"], ["run", "-h"], ["check", "--help"], ["check", "-h"], full + ["--help"], full + ["-h"], short,
             full[:1] + ["--kin", "count"] + full[3:], ["check", "--thr", str(files.thresholds)],
             ["check", "--thresholds", str(files.thresholds), "--der", str(files.derive)],
             full[:5] + ["--thresholds-sha", sha_of(files.thresholds)] + full[7:]]
    assert full[5] == "--thresholds-sha256"
    for argv in cases:
        ran = run(B, files, "count", capsys, argv=argv)
        assert ran.rc == B.EXIT["arguments"] == 2 and ran.out == "" and ran.link is None, argv
        assert ran.err.count("\n") == 1 and ran.err.startswith("burst: refused: arguments-invalid:"), (argv, ran.err)
        assert "run --kind count|bytes|shadow --thresholds FILE --thresholds-sha256 HEX --state DIR --log FILE [--derive FILE]" in ran.err, argv
        assert "check --thresholds FILE [--thresholds-sha256 HEX] [--derive FILE]" in ran.err and "usage:" not in ran.err, argv
        assert not files.log.exists() and not (files.state / B.LEDGER).exists(), argv
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds), "--derive", str(files.derive)])
    assert ran.rc == B.EXIT["ok"]                                   # the names written out are taken as before


def test_the_docstring_and_the_readme_say_what_holds_at_the_time_ceiling_and_of_the_second_nets(B: Any) -> None:
    """burst-fix-r2. The sentences the decisions of this round are written down in stand in the tool's docstring and in its
    README, word for word (white space and code marks aside): each said something else before, or nothing."""
    doc, readme = fold(str(B.__doc__)), fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    for said in (
            "No hand-over is made and no connection is asked for at or after start + 20 minutes: the clock is read right before each",
            "No connection is asked for in the last 10 s before the ceiling either",
            "A connection that opens at or after the ceiling all the same",
            "The run counts both as well, 120 of each: a second net behind the tick",
            "A count or a bytes run: up to 2,060 publishes on the rule's topic (the burst's 2,000 and the trickle's 60) and up to 60 shadow "
            "updates, 2,120 MQTT publishes in all; a shadow run: up to 60 publishes on the rule's topic and 120 shadow updates",
            "No run as built reaches it, so the two words it has in the log (ceiling trickle, ceiling connects) are never written",
            "2 the command line cannot be read (a request for help and an option that is not written out are such lines",
            "state-unwritable, log-unwritable",
            # burst-review-fix-exact (burst-verify-r2, problem 5; the hard review's NIT 5): a log with no `stopped` line, and the window a
            # first connection that could not be opened holds
            "A log whose last line is no stopped line is a run that was killed from outside (SIGKILL, a signal the tool does not handle "
            "such as SIGHUP, the host's end), or one the watchdog ended while its log could not be written (exit status 6): its attempts "
            "without an outcome count the same way, and its window is held all the same.",
            "so a first connection that cannot be opened (exit 3) holds the window all the same: the next start comes 20 minutes later"):
        assert said in doc, said
        assert said in readme, said
    # (the hard review's NIT 6) what the environment file given to a run names: the README's run section says it, the docstring has the
    # settings' own words
    assert "the environment file given is the device directory's own and names no other certificate, key or CA path; the three default " \
        "to the mounted device directory" in readme
    assert "from its start to its last attempt" not in doc + readme and "at most 120 attempts" not in doc
    assert "2,060 publishes, 8 MiB" not in doc + readme          # the sentence read as a bound on a run's publishes (burst-verify-r1, problem 14)


# ------------------------------------------------------------------------------------------------- burst-fix-r2, found while fixing:
# a signal inside a connect, an error of the system's before a run, and the other half of the form's sentence on outcomes

def every_attempt_has_one_outcome(ran: Ran) -> None:
    stamps = [rec["t_mono"] for rec in ran.events("attempt")]
    assert stamps and len(set(stamps)) == len(stamps) and sorted(rec["of"] for rec in ran.events("outcome")) == sorted(stamps)


def test_a_signal_that_comes_while_a_connection_is_being_opened_is_followed_by_no_hand_over(B: Any, files: Any, capsys: Any) -> None:
    """burst-fix-r2, found with burst-verify-r1's problem 1, in the same line. Decision 8: nothing is handed over after a
    signal's handler ran, and a connection that is being opened when the signal comes is still waited for. The tick
    handed over on that connection when it had come, up to the connector's wait after the handler: the stop was not read
    again. It is read now where the clock is, right before the hand-over. Here a connect takes 5 s and the signal comes
    in the middle of it."""
    stop = B.Stop()
    handed: List[int] = []

    def script(link: Any, clock: ManualClock) -> None:
        link.reopen_takes, link.slow_from = 5.0, T0

        def cut() -> None:
            link.cut()
            link.back_at = T0 + 300.0

        def handler() -> None:
            handed.append(len(link.asked))
            stop.set("SIGTERM")
        clock.at(T0 + 300.0, cut)
        clock.at(T0 + 312.0, handler)

    ran = run(B, files, "shadow", capsys, script=script, stop=stop, link_class=SlowLink)
    link = ran.link
    assert isinstance(link, SlowLink) and ran.rc == B.EXIT["ok"]
    opened_at, word = link.connects[-1]
    assert link.reopens[-1] < T0 + 312.0 < opened_at and word == "opened"          # the case: the signal came inside the connect
    assert handed and len(link.asked) == len(link.begun) == handed[0]          # not one hand-over after the handler ran
    assert [rec["connection"] for rec in ran.events("connected")] == [1, 2]          # the connection did open, and the log says so
    (outcome,) = [rec for rec in ran.events("outcome") if rec["of"] == ran.events("attempt")[-1]["t_mono"]]
    assert (outcome["result"], outcome["connect"]) == ("refused", "opened")
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["signal"], last["exit"]) == ("stopped", "signal", "SIGTERM", B.EXIT["ok"])
    assert link.closed_at == [opened_at]                            # at once: no wait after the connection had come
    every_attempt_has_one_outcome(ran)
    lines_are_in_form(B, ran.lines, ran.text)


@pytest.mark.parametrize("end, kind", [("time-ceiling", "count"), ("signal-in-the-burst", "count"), ("signal-in-the-trickle", "shadow"),
                                       ("cut-in-the-burst", "count"), ("a-far-end-that-goes-silent", "count")])
def test_at_every_end_a_run_comes_to_by_itself_each_attempt_has_exactly_one_outcome(B: Any, files: Any, capsys: Any, end: str, kind: str) -> None:
    """burst-fix-r2 (burst-verify-r1, problem 10): the other half of the form's sentence, `At every other end each attempt
    has exactly one outcome`. Every answer takes 0.9 s here, so that at any moment of a burst there are hand-overs without
    one: at the burst's end, at a signal in the burst and in a tick's own wait, at a cut, and where the far end goes
    silent and the connection is given up."""
    stop = B.Stop()

    def script(link: Any, clock: ManualClock) -> None:
        link.ack_after = 0.9
        if end == "signal-in-the-burst":
            clock.at(T0 + 15.0, lambda: stop.set("SIGINT"))
        elif end == "signal-in-the-trickle":
            clock.at(T0 + 400.5, lambda: stop.set("SIGINT"))
        elif end == "cut-in-the-burst":
            clock.at(T0 + 15.0, link.cut)
        elif end == "a-far-end-that-goes-silent":
            link.word = lambda i, topic, payload: "silent" if i >= 200 else None

    ran = run(B, files, kind, capsys, script=script, stop=stop)
    assert ran.link is not None and ran.lines[-1]["why"] == ("signal" if end.startswith("signal") else "time-ceiling")
    every_attempt_has_one_outcome(ran)
    lines_are_in_form(B, ran.lines, ran.text)
    results = [rec["result"] for rec in ran.events("outcome")]
    if end == "signal-in-the-burst":
        assert results.count("no-word") > 5                         # what was in flight when the handler ran
    elif end == "signal-in-the-trickle":
        assert ran.events("outcome")[-1]["phase"] == "trickle" and results[-1] == "no-word" and results.count("no-word") == 1
    elif end == "cut-in-the-burst":
        assert results.count("failed") > 5 and "refused" in results          # in flight at the cut; then the trickle's attempts
    elif end == "a-far-end-that-goes-silent":
        assert results.count("no-word") > 5 and ran.link.given_up >= 1 and "refused" in results


def test_an_error_of_the_systems_outside_a_runs_own_handling_is_said_by_its_class_with_status_5_and_no_path(
        B: Any, files: Any, capsys: Any, monkeypatch: Any) -> None:
    """burst-fix-r2 (burst-verify-r1, problem 11, what the system cannot say beforehand). A write that fails where
    os.access had said it could be made left main() as a traceback with the path in it, and with Python's status 1, which
    is this tool's `refused before any connection, by a name`. It is an error no check names now: status 5, one line with
    the error's class and nothing of its text. For the ledger nothing was claimed; for the log (POSIX: a link that leads
    nowhere) the claim was made before it, which is what the docstring says is not held."""
    ledger = files.state / B.LEDGER

    def full(self: Any, entry: Dict[str, Any]) -> None:
        raise OSError(28, "No space left on device", str(ledger))

    def said(ran: Ran, kind: str) -> None:
        assert ran.rc == B.EXIT["error"] == 5 and ran.out == "" and ran.err.count("\n") == 1, ran.err
        assert ran.err.startswith("burst: stopped on an error no check names (%s);" % kind), ran.err
        assert str(files.top) not in ran.err and "No space" not in ran.err and "No such file" not in ran.err
        assert ran.link is not None and ran.link.connects == [] and ran.link.asked == []          # nothing was opened, nothing sent

    with monkeypatch.context() as patched:
        patched.setattr(B.Ledger, "_append", full)
        said(run(B, files, "count", capsys), "OSError")
    assert not ledger.exists() and not files.log.exists()
    if os.name == "posix":
        nowhere = files.top / "logs" / "leads-nowhere.jsonl"
        nowhere.symlink_to(files.top / "there-is-no-such-directory" / "burst.jsonl")
        said(run(B, files, "count", capsys, log=nowhere), "FileNotFoundError")
        claims = [json.loads(line) for line in ledger.read_text(encoding="utf-8").split("\n") if line]
        assert len(claims) == 1 and "claim" in claims[0]            # NOT held: this start's claim stands, and it never ran


def test_with_its_own_link_the_tool_asks_the_sdk_for_no_connection_in_the_runs_last_wait(B: Any, sdk_link: Any, tmp_path: Path) -> None:
    """burst-fix-r2 (burst-verify-r1, problem 1, its run K7): the same with the tool's OWN link, on the connector's stand-in
    for the SDK. The connection is lost 15 s before the time ceiling. At the run's last attempt, 10 s before the ceiling,
    the link's own back-off (the connector's 5 s) is over, and the link would ask the SDK for a new connection. It is not
    asked: the SDK builds no second connection, the far end sees one CONNECT and no publish after the loss, and the
    attempt's outcome says `connect: ceiling`."""
    s, t = sdk_link, topics_of(B)
    link, sdk, clock = s.link, s.sdk, s.clock
    lost_at = T0 + B.CEILING_S - 15.0
    clock.at(lost_at, sdk.lose)
    path = tmp_path / "own-link.jsonl"
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        link.connect()
        rc = B.Run(by_hand(B, "shadow", 1, len(B.SHADOW_DOCUMENT)), link, t, clock, B.Log(f, clock), B.Stop()).go()
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]
    assert rc == B.EXIT["ok"] and len(sdk.built) == 1 and len(sdk.connects) == 1          # the SDK was asked for the first connection and no other
    assert sdk.built[0].state == "disconnected" and link.counters["lost"] == 1 and not link.up()
    assert len(sdk.wire) == 1 + 118 and round(max(p.t for p in sdk.wire) - T0, 3) == B.CEILING_S - 20.0          # the trickle, up to the loss
    assert [(rec["connection"], round(rec["t_mono"], 3)) for rec in lines if rec["event"] == "cut"] == [(1, B.CEILING_S - 10.0)]
    attempts = [rec for rec in lines if rec["event"] == "attempt"]
    (outcome,) = [rec for rec in lines if rec["event"] == "outcome" and rec["of"] == attempts[-1]["t_mono"]]
    assert (outcome["result"], outcome["connect"]) == ("refused", "ceiling") and not [rec for rec in lines if rec["event"] == "connect-failed"]
    assert [rec["event"] for rec in lines[-2:]] == ["ceiling", "stopped"] and lines[-2]["which"] == "minutes" and lines[-1]["why"] == "time-ceiling"


# ================================================================================================= burst-fix-r2-exact (burst-verify-r1's
# problems 2 to 8, 14 and 15): behaviours the package states and no test held. None of them changes what the tool does.

class ConnectBreaking(FakeLink):
    """A link whose connect() raises an error no check names, with the endpoint and a path of the host in its text."""

    def connect(self) -> None:
        raise RuntimeError("the key at /srv/device/device.key could not be used for %s" % ENDPOINT)


FAULT_WORDS = ("fault", "link's", "key", "srv/device/device.key", "could not", "used for", ENDPOINT, "broker")


def said_by_its_class_alone(ran: Ran, kind: str) -> None:
    """The line a run that stopped on an error no check names prints: the error's CLASS and the one fixed sentence, and
    nothing of the error's text (a link's error may name the endpoint, a path of the host, a key). The log holds none of it either."""
    fixed = "burst: stopped on an error no check names (%s); the log says how far it came\n" % kind
    assert ran.rc == 5 and ran.out == "" and ran.err == fixed, ran.err
    assert not [word for word in FAULT_WORDS if word in fixed or word in ran.text], "the error's text reached the sentence or the log"
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["exit"], last["burst_met"]) == ("stopped", "error", 5, False)
    assert ran.link is not None and ran.link.closes == 1          # the link was closed on the way out


def test_the_line_of_an_error_no_check_names_holds_its_class_and_nothing_of_its_text(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 2 (its mutant V27; the verifier's own runs B14 and B17b). The comment in the tool says why:
    a link's error may name the endpoint, a path, a key. The line holds RuntimeError and the fixed sentence, whether the error
    came at the first connect or at the n-th hand-over, and the log's last line says `stopped`, why `error`."""
    ran = run(B, files, "count", capsys, link_class=ConnectBreaking)
    said_by_its_class_alone(ran, "RuntimeError")
    assert ran.link is not None and ran.link.connects == [] and ran.link.asked == []          # nothing was opened, nothing was sent
    assert [rec["event"] for rec in ran.lines] == ["start", "stopped"]
    files.log.unlink()
    (files.state / B.LEDGER).unlink()

    def script(link: Any, clock: ManualClock) -> None:
        link.breaks_at = 9

    ran = run(B, files, "count", capsys, script=script, link_class=Breaking)
    said_by_its_class_alone(ran, "RuntimeError")
    assert ran.link is not None and len(ran.link.begun) == 8 and len(ran.events("attempt")) == 9          # the 9th hand-over is where it came
    lines_are_in_form(B, ran.lines, ran.text)


def test_a_burst_whose_last_answers_are_still_outstanding_at_its_last_hand_over_waits_for_them(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 4 (its mutant V17). Every answer takes 0.4 s, so that at the burst's last hand-over the last
    few are not answered. The burst waits for them (SETTLE_S at the most) before it sums itself up: every outcome of the
    burst is `acked`, `burst-end` says `complete` and `met`, its line comes after the last answer, and the status is 0.
    Without the wait, such a burst would end `failed` with status 4 whatever the far end had said."""
    def script(link: Any, clock: ManualClock) -> None:
        link.ack_after = 0.4

    plan = B.load_plan("count", files.thresholds, None)
    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["ok"], ran.err
    burst = [rec for rec in ran.events("outcome") if rec["phase"] == "burst"]
    assert len(burst) == plan.sends and {rec["result"] for rec in burst} == {"acked"}
    end = ran.one("burst-end")
    assert (end["why"], end["met"], end["inside_window"], end["ratio"]) == ("complete", True, True, 1.0)
    last_handed_over = ran.link.begun[plan.sends - 1][0] - T0
    assert end["t_mono"] >= last_handed_over + 0.4 and max(rec["t_mono"] for rec in burst) <= end["t_mono"]          # after the last answer
    assert ran.lines[-1]["burst_met"] is True


def test_a_burst_that_missed_one_publish_of_many_has_its_ratio_rounded_down_and_not_to_the_nearest(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 8 (its mutant V18). 1 failed of the burst's publishes: the ratio is `to two places, rounded
    down` (the form says so), so it is 0.99 and never 1.0, which is the value of a burst that met its goal."""
    plan = B.load_plan("count", files.thresholds, None)
    assert round((plan.sends - 1) / plan.sends, 2) == 1.0          # to the nearest hundredth it would be a whole burst

    def script(link: Any, clock: ManualClock) -> None:
        link.word = lambda i, topic, payload: "failed" if i == 7 else None

    ran = run(B, files, "count", capsys, script=script)
    end = ran.one("burst-end")
    assert ran.rc == B.EXIT["burst-not-met"] and end["met"] is False and end["why"] == "failed" and end["ratio"] == 0.99
    assert [rec["result"] for rec in ran.events("outcome") if rec["phase"] == "burst"].count("failed") == 1


def test_the_trickles_ticks_come_10_s_after_the_last_began_whatever_an_answer_takes(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 8 (its mutant V16). From 100 s on every answer takes 3 s. A tick is due 10 s after the last
    one BEGAN, not after it ended: the attempts stay 10.0 s apart (to the clock's own slice), and their outcomes come 3 s after
    them. A trickle that drifted by what the answers took would be 13 s apart, and the run would have fewer attempts."""
    def script(link: Any, clock: ManualClock) -> None:
        clock.at(T0 + 100.0, lambda: setattr(link, "ack_after", 3.0))

    ran = run(B, files, "count", capsys, script=script)
    assert ran.rc == B.EXIT["ok"]
    attempts = [rec["t_mono"] for rec in ran.events("attempt") if rec["phase"] == "trickle"]
    assert len(attempts) > 100
    gaps = [round(b - a, 3) for a, b in zip(attempts, attempts[1:])]
    assert all(abs(gap - B.TRICKLE_INTERVAL_S) < 1e-3 for gap in gaps), gaps[:20]
    took = {rec["of"]: rec["t_mono"] - rec["of"] for rec in ran.events("outcome") if rec["phase"] == "trickle"}
    late = [took[t] for t in attempts if t > 105.0]
    assert late and all(abs(x - 3.0) < 0.06 for x in late)
    assert {rec["result"] for rec in ran.events("outcome") if rec["phase"] == "trickle"} == {"acked"}


def test_the_bytes_not_yet_answered_are_bounded_as_well_as_their_number(B: Any, tmp_path: Path) -> None:
    """burst-verify-r1, problem 8 (its mutant V31). Publishes of 100 KiB, each answered 6 s after it was handed over, every
    0.8 s: without a bound on the bytes the burst would have 8 of them outstanding (the number bound is 20); with it, 5, which is
    what 512 KiB holds (a sixth would make 600 KiB). The count is taken at every hand-over from what the link was given."""
    clock = ManualClock()
    link = FakeLink(clock)
    link.ack_after = 6.0
    size = 100 * 1024
    assert B.INFLIGHT_MAX_BYTES // size == 5 < B.INFLIGHT_MAX_PUBLISHES
    assert link.ack_after / (B.BURST_SPREAD_S / 50) > 5             # without the bound on the bytes, more than 5 would be outstanding
    rc, lines = go(B, by_hand(B, "bytes", 50, size), clock, link, tmp_path)
    burst = link.begun[:len([rec for rec in lines if rec["event"] == "attempt" and rec["phase"] == "burst"])]
    assert len(burst) > 20
    outstanding = [1 + sum(1 for j in range(i) if burst[j][0] + link.ack_after > burst[i][0]) for i in range(len(burst))]
    assert max(outstanding) == 5, outstanding


def test_a_state_directory_or_a_log_directory_that_is_not_there_is_refused_by_its_name(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r1, problem 8 (its mutants V28 and V29). Both are made by hand once, outside every work tree; a start
    that finds one missing is refused `state-missing` / `log-missing` (status 1) before a link is made, and writes nothing.
    Without the check the system's answer for a directory that is not there would be `unwritable`, which is another thing."""
    elsewhere = files.top / "not-made"
    ran = run(B, files, "count", capsys, argv=run_argv(files, state=elsewhere))
    assert ran.rc == B.EXIT["refused"] and ran.link is None and ran.err.startswith("burst: refused: state-missing:"), ran.err
    ran = run(B, files, "count", capsys, log=elsewhere / "burst.jsonl")
    assert ran.rc == B.EXIT["refused"] and ran.link is None and ran.err.startswith("burst: refused: log-missing:"), ran.err
    assert ran.err.count("\n") == 1 and str(files.top) not in ran.err and ran.out == ""
    assert not elsewhere.exists() and not files.log.exists() and not (files.state / B.LEDGER).exists()          # nothing was made, nothing claimed


PLAN_INCONSISTENT: List[Tuple[str, Callable[[int], Dict[str, Any]], Optional[Dict[str, int]], str]] = [
    # (what the change is, the change to the burst given the filler's frame, thresholds of its own, the refusal's name)
    ("a bytes publish over the broker's 128 KiB, the total whole",
     lambda low: {"bytes_per_publish": 128 * 1024 + 1, "bytes_publishes": 19, "bytes_total": 19 * (128 * 1024 + 1)},
     None, "burst-inconsistent:bytes"),
    ("more bytes publishes than a run may make", lambda low: {"bytes_publishes": 2001, "bytes_per_publish": 1234, "bytes_total": 2001 * 1234},
     None, "burst-inconsistent:bytes"),
    ("a bytes publish smaller than the filler's frame",          # (a threshold the trickle's own bytes of one period stay under)
     lambda low: {"bytes_per_publish": low - 1, "bytes_publishes": 130, "bytes_total": 130 * (low - 1)},
     {"Firehose.IncomingBytes": 2000}, "burst-inconsistent:bytes"),
    ("a count publish smaller than the filler's frame", lambda low: {"count_publish_bytes": low - 1}, None, "burst-inconsistent:count"),
    ("a count burst of more than the bytes ceiling in all", lambda low: {"count_publish_bytes": 64 * 1024}, None, "burst-inconsistent:count")]


@pytest.mark.parametrize("what, change, thresholds, name", PLAN_INCONSISTENT, ids=[c[0] for c in PLAN_INCONSISTENT])
def test_load_plan_holds_every_bytes_and_count_burst_to_the_publishes_a_run_can_make(
        B: Any, files: Any, what: str, change: Callable[[int], Dict[str, Any]], thresholds: Optional[Dict[str, int]], name: str) -> None:
    """burst-verify-r1, problem 7 (its mutants V02, V04, V05, V06 and V07). The plan's own consistency checks beyond derive.py's:
    one case each. Every other check passes in each case (the total whole, the burst more than twice its threshold, under the
    ceilings), so it is this check that refuses, by its name; the refusal repeats no count of the file. Without the check, such a
    plan is taken at load and fails later (a too-small publish only at the first hand-over, after the window was claimed)."""
    own = None if thresholds is None else dict(THRESHOLDS, **thresholds)
    doc = burst_doc(own, **change(B.MIN_PUBLISH_BYTES))
    files.put(doc)
    with pytest.raises(B.Refused) as exc:
        B.load_plan("bytes" if name.endswith("bytes") else "count", files.thresholds, None)
    assert exc.value.name == name, (what, exc.value.name)
    numbers = {int(n) for n in re.findall(r"[0-9]+", exc.value.detail.replace(",", ""))}
    filed = {v for part in ("burst", "thresholds") for k, v in doc[part].items() if isinstance(v, int) and k not in B.DESIGN}
    assert not numbers & filed, (what, exc.value.detail)
    files.put(burst_doc(own))          # the same thresholds with the burst derived as derive.py derives it are taken: only the burst differed
    assert B.load_plan("bytes", files.thresholds, None).kind == "bytes" and B.load_plan("count", files.thresholds, None).kind == "count"


def test_the_link_counts_a_hand_over_at_which_the_sdk_raised_as_handed_over_and_failed(B: Any, sdk_link: Any) -> None:
    """burst-verify-r1, problem 6 (its mutant V36). Whether the SDK took the publish it raised at is not known: the hand-over
    counts, its handle says `failed` at once (the tool logs `failed`, never `refused`, which is `NOT handed over`), the
    connection stays as it was, and nothing is raised to the tool. The next hand-over goes through."""
    s, t = sdk_link, topics_of(B)
    link, sdk = s.link, s.sdk
    link.connect()
    conn = sdk.live()
    assert conn is not None
    real = conn.publish

    def raises(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the SDK's own failure for %s" % ENDPOINT)

    conn.publish = raises
    handle = link.begin(t.telemetry, b"the SDK raised at this one")          # no UplinkError: it is handed over
    assert handle.state() == "failed" and handle.state() == "failed"          # for good
    assert link.up() and link.counters["not_connected"] == 0 and link.counters["given_up"] == 0
    assert sdk.wire == [] and [c.state for c in sdk.built] == ["up"]
    conn.publish = real
    assert link.begin(t.telemetry, b"the next").state() == "acked" and [p.payload for p in sdk.wire] == [b"the next"]


def test_give_up_ends_the_connection_for_good_and_what_the_sdk_holds_for_it_is_never_written(B: Any, sdk_link: Any) -> None:
    """burst-verify-r1, problem 3 (its mutant V40). The tool calls give_up() when a hand-over got no word in time: that
    disconnect is what ends the SDK's own reconnecting, on which `nothing is sent later` rests for a loss the link was never told of.
    The connection is out of use, the stand-in's is disconnected, the count is one (and stays one), a further hand-over raises and
    the SDK is not asked, and what the SDK was holding is not written when the far end answers again."""
    s, t = sdk_link, topics_of(B)
    link, sdk = s.link, s.sdk
    link.connect()
    sdk.far_end = "mute"                                            # the SDK holds what it is handed and says nothing
    handle = link.begin(t.telemetry, b"never answered")
    assert handle.state() is None and link.up() and link.counters["given_up"] == 0
    link.give_up()
    assert not link.up() and link.counters["given_up"] == 1 and [c.state for c in sdk.built] == ["disconnected"]
    assert ("disconnect", 1) in sdk.calls
    asked = len(sdk.calls)
    with pytest.raises(B.UplinkError):
        link.begin(t.telemetry, b"after")
    assert sdk.calls[asked:] == [] and link.counters["not_connected"] == 1          # the SDK was not asked
    link.give_up()
    assert link.counters["given_up"] == 1 and len(sdk.calls) == asked          # nothing in use, nothing more to give up
    sdk.far_end = "answers"
    sdk.unstick()
    sdk.come_back()
    assert sdk.elapse() == 0 and sdk.wire == []                     # what the SDK held for it never went out


def test_a_connection_that_has_shown_no_life_for_the_connectors_limit_is_not_up(B: Any, sdk_link: Any) -> None:
    """burst-verify-r1, problem 8 (its mutant V41). up() is `a connection is in use`: one that showed no life (an
    acknowledgement) for LINK_LIFE_MAX_S is given up there, counted `stale`, and is not up, whatever the SDK says of it."""
    s, t = sdk_link, topics_of(B)
    link, sdk, clock = s.link, s.sdk, s.clock
    link.connect()
    clock.sleep(B.limits.LINK_LIFE_MAX_S - 1.0)
    assert link.up() and link.counters["stale"] == 0
    clock.sleep(2.0)
    assert not link.up() and link.counters["stale"] == 1 and link.counters["given_up"] == 1
    assert [c.state for c in sdk.built] == ["disconnected"]
    with pytest.raises(B.UplinkError):
        link.begin(t.telemetry, b"x")


# ================================================================================================= burst-review-fix (the hard review's two
# SHOULDs and its NITs 3 and 4; burst-verify-r2's NITs 2, 3, 4, 6 and 13): each test fails on the files as they were.

def nothing_was_claimed_or_written(B: Any, files: Any) -> None:
    assert not (files.state / B.LEDGER).exists() and not files.log.exists()


STOPPED_EARLY = ("burst: refused: stopped-before-start: %s came before a run was started: nothing was claimed, nothing was opened and nothing "
                 "is sent\n")


def test_a_signal_that_came_before_the_claim_ends_the_start_as_a_refusal_by_a_name_and_nothing_is_claimed(B: Any, files: Any, capsys: Any,
                                                                                                         monkeypatch: Any) -> None:
    """The hard review, SHOULD 1 (decision 8). The stop a signal's handler raises is looked at before the claim: at the first
    check, after the last one, and after derive.py's own check in `check`. Such a start is a refusal by a name, exit status 1,
    which says which signal; nothing is claimed, no log is begun, no connection is asked for. (The run went on: it claimed its
    window, connected, and ended as a burst that was not met.)"""
    stop = B.Stop()
    stop.set("SIGTERM")                                             # before anything was read: refused at the first check, before a link is made
    ran = run(B, files, "count", capsys, stop=stop)
    assert (ran.rc, ran.out, ran.err) == (B.EXIT["refused"], "", STOPPED_EARLY % "SIGTERM") and ran.link is None
    nothing_was_claimed_or_written(B, files)
    stop = B.Stop()                                                 # ... while the link was being made, the last of the checks

    def script(link: FakeLink, clock: ManualClock) -> None:
        stop.set("SIGINT")

    ran = run(B, files, "count", capsys, script=script, stop=stop)
    assert (ran.rc, ran.out, ran.err) == (1, "", STOPPED_EARLY % "SIGINT")
    assert ran.link is not None and ran.link.connects == [] and ran.link.asked == [] and ran.link.closes == 0          # made, and asked for nothing
    nothing_was_claimed_or_written(B, files)
    stop = B.Stop()                                                 # ... and in `check`, while derive.py's own check ran
    real = B.derive_check

    def derive_check(path: Path, derive: Any, flag: Any = None) -> None:
        real(path, derive, flag)
        flag.set("SIGTERM")

    monkeypatch.setattr(B, "derive_check", derive_check)
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds)], stop=stop)
    assert (ran.rc, ran.out, ran.err) == (1, "", STOPPED_EARLY % "SIGTERM")          # not `taken`: the check was stopped
    monkeypatch.setattr(B, "derive_check", real)
    ran = run(B, files, "count", capsys)                            # a stop that was not raised changes nothing: the same start runs
    assert ran.rc == B.EXIT["ok"] and ran.link is not None and (files.state / B.LEDGER).exists() and ran.lines[0]["event"] == "start"
    assert B.EXIT["refused"] == 1


SLOW_DERIVE = '''import os, sys, time
with open(sys.argv[0] + ".began", "w") as f:
    f.write(str(os.getpid()))
time.sleep(%s)
with open(sys.argv[0] + ".ended", "w") as f:
    f.write("ended")
'''
LOUD_DERIVE = '''import os, sys
refuses = "refuse" in os.path.basename(sys.argv[0])
sys.stdout.write("x" * (1 << 20))
sys.stderr.write(("design estimate | refused: loud-refusal: 4,001 is over 2,000\\n" * 20000) if refuses else "y" * (1 << 20))
sys.exit(1 if refuses else 0)
'''


def test_derive_pys_check_is_ended_when_the_stop_is_raised_or_its_time_is_over_and_is_run_as_twinctl_runs_it(B: Any, files: Any, tmp_path: Path,
                                                                                                            monkeypatch: Any) -> None:
    """The hard review, SHOULD 1: derive.py's own check is a process of its own and the one long wait before the claim. It is
    looked at in slices: a stop raised meanwhile ends it and refuses the start as stopped (it was waited for to its end,
    its time-out 600 s); one that has not ended in its time is ended and counts as a check that could not be run; so does one
    that cannot be started. It is run as twinctl runs it: this interpreter, -B, derive.py, --check, the file. What it writes
    is taken off its pipes while it runs, however much it is."""
    made: List[Any] = []
    real = subprocess.Popen

    def popen(argv: Any, **kwargs: Any) -> Any:
        child = real(argv, **kwargs)
        made.append((list(argv), kwargs, child))
        return child

    monkeypatch.setattr(B.subprocess, "Popen", popen)
    assert B.load_plan("count", files.thresholds, None).kind == "count"
    argv, kwargs, child = made[-1]
    assert argv == [sys.executable, "-B", str(files.derive), "--check", str(files.thresholds)] and child.returncode == 0
    assert (kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]) == (subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE)
    slow = tmp_path / "slow-derive.py"
    slow.write_text(SLOW_DERIVE % "40", encoding="ascii")
    # the stop is raised half a second into the check
    stop = B.Stop()
    timer = threading.Timer(0.5, stop.set, ["SIGTERM"])
    began = time.monotonic()
    timer.start()
    try:
        with pytest.raises(B.Refused) as exc:
            B.load_plan("count", files.thresholds, slow, None, stop)
    finally:
        timer.cancel()
    assert exc.value.name == "stopped-before-start" and "SIGTERM" in exc.value.detail and time.monotonic() - began < 20.0
    assert made[-1][2].poll() is not None and made[-1][2].returncode != 0 and not Path(str(slow) + ".ended").exists()          # ended, not waited for
    # its time is over (shortened here: the test would wait ten minutes)
    monkeypatch.setattr(B, "DERIVE_WAIT_S", 0.6, raising=False)
    began = time.monotonic()
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, slow, None, B.Stop())
    assert exc.value.name == "thresholds-check-unavailable" and time.monotonic() - began < 20.0
    assert made[-1][2].poll() is not None and made[-1][2].returncode != 0 and not Path(str(slow) + ".ended").exists()
    monkeypatch.undo()
    assert B.DERIVE_WAIT_S == 600 and B.DERIVE_LOOK_S == 0.2
    # much output on both pipes: taken off while it runs (a wait that did not read them would never end), and the names are passed on
    loud = tmp_path / "loud-derive.py"
    loud.write_text(LOUD_DERIVE, encoding="ascii")
    assert B.load_plan("count", files.thresholds, loud).kind == "count"
    refusing = tmp_path / "loud-refuse-derive.py"
    refusing.write_text(LOUD_DERIVE, encoding="ascii")
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, refusing)
    assert exc.value.name == "thresholds-check-failed" and "loud-refusal" in exc.value.detail and "4,001" not in exc.value.detail
    # it cannot be started at all

    def cannot(argv: Any, **kwargs: Any) -> Any:
        raise OSError(8, "Exec format error", str(argv[0]))

    monkeypatch.setattr(B.subprocess, "Popen", cannot)
    with pytest.raises(B.Refused) as exc:
        B.load_plan("count", files.thresholds, None)
    assert exc.value.name == "thresholds-check-unavailable" and "Exec format" not in exc.value.detail


EARLY_SIGNAL_DRIVER = '''\
import importlib.util, os, signal, sys, threading, time
spec = importlib.util.spec_from_file_location("burst_for_the_early_signal_test", sys.argv[1])
B = importlib.util.module_from_spec(spec); sys.dont_write_bytecode = True; spec.loader.exec_module(B)
class Link:
    def connect(self): print("CONNECTED", flush=True)
    def up(self): return True
    def reopen(self): return "refused"
    def begin(self, topic, payload):
        print("HANDED OVER", flush=True)
        os._exit(99)
    def give_up(self): pass
    def close(self): pass
def made(env, topics):
    print("LINK MADE", flush=True)
    return Link()
if len(sys.argv) > 7:          # no signal can be sent to this process from outside (not POSIX): raise it here, once derive.py's check runs
    def late():
        while not os.path.exists(sys.argv[7]):
            time.sleep(0.05)
        time.sleep(0.5)
        signal.raise_signal(signal.SIGINT)
    threading.Thread(target=late, daemon=True).start()
sys.exit(B.main(["run", "--kind", "count", "--thresholds", sys.argv[2], "--thresholds-sha256", sys.argv[5], "--state", sys.argv[3],
                 "--log", sys.argv[4], "--derive", sys.argv[6]],
                env={"SDV_TWIN_THING": "example-thing", "SDV_TWIN_RULE": "example_rule"}, make_link=made))
'''


@pytest.mark.parametrize("sent", REAL_SIGNALS)
def test_a_real_signal_during_derive_pys_check_ends_the_start_at_once_as_the_refusal_and_claims_nothing(B: Any, files: Any, tmp_path: Path,
                                                                                                       sent: str) -> None:
    """The hard review, SHOULD 1, as a process of its own with the system's clock and the tool's OWN handlers, which main()
    installs before it reads its command line. derive.py's check here takes 40 s and would then pass the file. The signal
    comes while it runs (on POSIX the test sends SIGINT and SIGTERM, one process each; elsewhere the process raises SIGINT
    in itself). The process ends at once, with status 1 and the one refusal line that names the signal; no link was made,
    nothing was claimed, no log was begun, and derive.py's process is gone. (With the handlers installed only where the run
    begins a SIGTERM ended the process with no word and a status the tool's table does not have, a SIGINT in a traceback
    with the tree's paths; in the tool's image, where it is PID 1, the kernel dropped the signal and the run went on.)"""
    driver, slow = tmp_path / "driver.py", tmp_path / "slow-derive.py"
    driver.write_text(EARLY_SIGNAL_DRIVER, encoding="utf-8")
    slow.write_text(SLOW_DERIVE % "40", encoding="ascii")
    marker = Path(str(slow) + ".began")
    posix = os.name == "posix"
    argv = [sys.executable, "-B", str(driver), str(BURST_DIR / "burst.py"), str(files.thresholds), str(files.state), str(files.log),
            sha_of(files.thresholds), str(slow)]
    proc = subprocess.Popen(argv + ([] if posix else [str(marker)]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        waited = time.monotonic()
        while not (marker.is_file() and marker.read_text(encoding="ascii").strip()) and proc.poll() is None and time.monotonic() - waited < 60.0:
            time.sleep(0.05)
        assert proc.poll() is None and marker.is_file(), "derive.py's check did not begin"          # the check is under way
        if posix:
            proc.send_signal(getattr(signal, sent))
        began = time.monotonic()
        out, err = proc.communicate(timeout=30)
        took = time.monotonic() - began
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert (proc.returncode, out, err) == (B.EXIT["refused"], "", STOPPED_EARLY % sent), (proc.returncode, out, err)
    assert took < 20.0 and not Path(str(slow) + ".ended").exists()          # at once: the check's 40 s were not waited for
    nothing_was_claimed_or_written(B, files)
    if posix:                                                       # ... and the check's own process was ended with it
        with pytest.raises(ProcessLookupError):
            os.kill(int(marker.read_text(encoding="ascii")), 0)


MARKING_DERIVE = DERIVE_DOUBLE + '''with open(sys.argv[0] + ".ran", "a") as f:
    f.write("x")
'''


def test_a_thresholds_file_that_is_not_the_one_whose_sha256_was_given_is_refused_before_derive_py_runs_and_before_anything_is_opened(
        B: Any, files: Any, capsys: Any) -> None:
    """The hard review, SHOULD 2 (decision 6). derive.py's own check passes every file that is what derive.py derives for the
    design the file ITSELF names: a file of another design passes it, and a burst sized on it can be under the threshold the
    account's alarm stands on while the log says the burst met its goal. `run` takes the sha256 of the file the alarms were
    rendered from (twinctl status prints it) and refuses a file whose bytes do not have it, by a name, before derive.py is run
    and before anything is opened; the refusal repeats neither hash and no count. A hash that is no sha256, or none at all,
    is a command line that cannot be read."""
    alarms = json.dumps(burst_doc())                                # the file the account's alarms were rendered from
    other = json.dumps(burst_doc(dict(THRESHOLDS, **{"IoT.PublishIn.Success": 641, "IoT.RulesExecuted.per_5kb_unit": 640})))
    given, of_other = hashlib.sha256(alarms.encode("ascii")).hexdigest(), hashlib.sha256(other.encode("ascii")).hexdigest()
    files.derive.write_text(MARKING_DERIVE, encoding="ascii")
    ran_marker = Path(str(files.derive) + ".ran")
    fixed = ("burst: refused: thresholds-not-the-alarms: the thresholds file is not the one whose sha256 was given, the file the account's "
             "alarms were rendered from (`twinctl status` prints that hash): a burst sized on another file says nothing about those alarms. "
             "Nothing was claimed and nothing is sent\n")
    for text in (other, json.dumps(json.loads(alarms), indent=1), alarms + "\n"):          # another design; the same document in other bytes
        files.thresholds.write_text(text, encoding="ascii")
        for kind in B.KINDS:
            ran = run(B, files, kind, capsys, argv=run_argv(files, kind, sha256=given))
            assert (ran.rc, ran.out, ran.err) == (B.EXIT["refused"], "", fixed) and ran.link is None, (kind, ran.err)
            nothing_was_claimed_or_written(B, files)
        assert not ran_marker.exists()                              # derive.py was not even run on it
    assert given not in fixed and of_other not in fixed and not re.search(r"[0-9a-f]{16}", fixed)
    # `check` holds the file to a hash it is given, and to none when it is given none
    files.thresholds.write_text(other, encoding="ascii")
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds), "--thresholds-sha256", given])
    assert (ran.rc, ran.out, ran.err) == (1, "", fixed) and not ran_marker.exists()
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds), "--thresholds-sha256", of_other])
    assert (ran.rc, ran.out, ran.err) == (0, "burst: the thresholds file is taken for all three kinds, and it is the file whose sha256 was given; "
                                             "nothing was sent\n", "")
    ran = run(B, files, "count", capsys, argv=["check", "--thresholds", str(files.thresholds)])
    assert (ran.rc, ran.out, ran.err) == (0, "burst: the thresholds file is taken for all three kinds; nothing was sent\n", "")
    assert ran_marker.read_text(encoding="ascii") == "xx"
    # a hash that is no sha256 as twinctl prints one, or no hash: the command line cannot be read (status 2), whatever the file is
    files.thresholds.write_text(alarms, encoding="ascii")
    for bad in (given.upper(), given[:63], given + "0", "g" + given[1:], "", "sha256:" + given, given + "\n", " " + given):
        ran = run(B, files, "count", capsys, argv=run_argv(files, sha256="x")[:6] + [bad] + run_argv(files)[7:])
        assert ran.rc == B.EXIT["arguments"] == 2 and ran.link is None and ran.err.startswith("burst: refused: arguments-invalid:"), (bad, ran.err)
        assert given not in ran.err and ran.err.count("\n") == 1
        nothing_was_claimed_or_written(B, files)
    without = run_argv(files)[:5] + run_argv(files)[7:]
    assert "--thresholds-sha256" not in without and len(without) == 9
    ran = run(B, files, "count", capsys, argv=without)
    assert ran.rc == 2 and ran.link is None and "arguments-invalid" in ran.err          # `run` takes no file without its hash
    nothing_was_claimed_or_written(B, files)
    assert not ran_marker.exists() or ran_marker.read_text(encoding="ascii") == "xx"
    ran = run(B, files, "count", capsys, argv=run_argv(files, sha256=given))          # the file with ITS hash: taken, and the run is made
    assert ran.rc == B.EXIT["ok"] and ran.link is not None and ran.link.begun and ran_marker.read_text(encoding="ascii") == "xxx"
    assert given not in ran.text and '"sha256"' not in ran.text          # the log holds no hash of the file: that is the owner's to say


def test_the_plan_is_read_from_the_bytes_that_were_hashed(B: Any, files: Any) -> None:
    """The hard review, SHOULD 2. derive.py's check takes time, and the file is read by it and by the tool. The tool reads the
    file ONCE, before the check: what it hashes is what its plans are made from. Here derive.py's double writes ANOTHER
    document (one its own check passes too) over the file while it checks it: the plan is the hashed document's, and the
    file as it then stands is refused at the next load."""
    first, second = burst_doc(), burst_doc(dict(THRESHOLDS, **{"IoT.UpdateThingShadow.Accepted": 19}))
    files.put(first)
    given = sha_of(files.thresholds)
    files.derive.write_text(DERIVE_DOUBLE + "with open(args[1], 'w') as f:\n    json.dump(%r, f)\n" % (second,), encoding="ascii")
    plan = B.load_plan("shadow", files.thresholds, None, given)
    assert plan.sends == first["burst"]["shadow_updates"] == 47 != second["burst"]["shadow_updates"]
    assert json.loads(files.thresholds.read_text(encoding="ascii")) == second and sha_of(files.thresholds) != given
    with pytest.raises(B.Refused) as exc:
        B.load_plan("shadow", files.thresholds, None, given)
    assert exc.value.name == "thresholds-not-the-alarms"


TRICKLE_UNDER: List[Tuple[str, Dict[str, int], Dict[str, int]]] = [
    # (the kind in the refusal's name, thresholds AT the trickle's own most of one period, thresholds one over it)
    ("shadow", {"IoT.UpdateThingShadow.Accepted": 16}, {"IoT.UpdateThingShadow.Accepted": 17}),
    ("count", {"IoT.RulesExecuted.per_execution": 31}, {"IoT.RulesExecuted.per_execution": 32}),          # ONE of the four: the least decides
    ("count", {"IoT.PublishIn.Success": 31, "Firehose.IncomingRecords": 31, "IoT.RulesExecuted.per_execution": 31,
               "IoT.RulesExecuted.per_5kb_unit": 31},
     {"IoT.PublishIn.Success": 32, "Firehose.IncomingRecords": 32, "IoT.RulesExecuted.per_execution": 32, "IoT.RulesExecuted.per_5kb_unit": 32}),
    ("bytes", {"Firehose.IncomingBytes": 16 * 64}, {"Firehose.IncomingBytes": 16 * 64 + 1})]


@pytest.mark.parametrize("kind, at, over", TRICKLE_UNDER, ids=["shadow", "one-count", "all-counts", "bytes"])
def test_a_file_under_whose_thresholds_the_trickle_itself_would_not_stay_is_refused_whichever_kind_is_asked_for(
        B: Any, files: Any, capsys: Any, kind: str, at: Dict[str, int], over: Dict[str, int]) -> None:
    """burst-verify-r2, problem 13 (b). The trickle is the tool's own traffic for 20 minutes: one attempt every 10 s, the two
    topics in turn, at the most 16 on a topic and 31 on both in any closed 300 s, the alarms' period. An alarm acts AT its
    threshold: a file whose threshold is not MORE than what the trickle adds to it in a period is refused before any
    connection, whichever kind was asked for, by a name that repeats no count of the file; one over it is taken. (Such a file
    was taken: derive.py holds a threshold above what the connector's limiter lets through, which on the shadow topics is
    fewer than the tool's trickle.)"""
    doc = burst_doc(dict(THRESHOLDS, **at))
    files.put(doc)
    for asked in B.KINDS:
        ran = run(B, files, asked, capsys)
        assert ran.rc == B.EXIT["refused"] and ran.link is None and ran.out == "", (asked, ran.err)
        assert ran.err.startswith("burst: refused: trickle-over-threshold:%s: " % kind) and ran.err.count("\n") == 1, ran.err
        nothing_was_claimed_or_written(B, files)
        filed = {v for part in ("burst", "thresholds") for k, v in doc[part].items() if isinstance(v, int) and k not in B.DESIGN and v != 1}
        assert not {int(n) for n in re.findall(r"[0-9]+", ran.err.replace(",", ""))} & filed, ran.err
    files.put(burst_doc(dict(THRESHOLDS, **over)))
    assert [B.load_plan(asked, files.thresholds, None).kind for asked in B.KINDS] == list(B.KINDS)
    assert (B.PERIOD_S, B.TRICKLE_PERIOD_TOPIC, B.TRICKLE_PERIOD_BOTH) == (B.limits.LIMITER_WINDOW_S, 16, 31) and B.PERIOD_S == 300


def test_the_trickles_most_in_one_period_is_what_the_file_is_held_over(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 13 (b): the two numbers the refusal above stands on are the trickle's own, counted on what a
    run handed over: in no closed 300 s more than 16 on one topic and 31 on both, and both are reached."""
    plan = B.load_plan("count", files.thresholds, None)
    ran = run(B, files, "count", capsys)
    assert ran.link is not None and ran.rc == B.EXIT["ok"]
    t = topics_of(B)
    trickle = ran.link.begun[plan.sends:]
    assert len(trickle) > 100

    def most(topics: Tuple[str, ...]) -> int:
        times = [w for w, topic, _p in trickle if topic in topics]
        return max(len([x for x in times if w <= x <= w + B.PERIOD_S + 1e-6]) for w in times)

    assert most((t.telemetry,)) == most((t.vss_update,)) == B.TRICKLE_PERIOD_TOPIC and most((t.telemetry, t.vss_update)) == B.TRICKLE_PERIOD_BOTH
    assert B.TRICKLE_PERIOD_TOPIC * B.TRICKLE_PUBLISH_BYTES == 1024


class LostAtOnce(FakeLink):
    """A link whose every new connection is lost again before the tool's next look at it: reopen() says `opened` and the
    connection is down. With the tool's own link: a loss between the SDK's answer to a connect and the hand-over."""

    def reopen(self) -> str:
        word = super().reopen()
        if word == "opened":
            self.cut()
        return word


def test_a_connection_that_was_opened_in_an_attempt_and_lost_before_its_hand_over_has_its_cut_line(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 2 (its case B14). The form says of `cut`: the connection in use was lost, as the tool noticed
    it. A connection the trickle opened anew and found lost at its look right after had a `connected` line and never a `cut`
    line (20 connected, 1 cut): only its outcome told. DECIDED: the loss is said at once, as every other is: the `cut` line
    stands right after the `connected` line and before the attempt's outcome, which is `refused` with `connect: opened`.
    Nothing is handed over, and the next look finds no change and writes no second line."""
    def script(link: FakeLink, clock: ManualClock) -> None:
        def cut() -> None:
            link.cut()
            link.back_at = T0 + 300.0
        clock.at(T0 + 300.0, cut)

    ran = run(B, files, "shadow", capsys, script=script, link_class=LostAtOnce)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"]
    connected = [rec["connection"] for rec in ran.events("connected")]
    assert len(connected) > 20 and connected == list(range(1, len(connected) + 1))
    assert [rec["connection"] for rec in ran.events("cut")] == connected          # each of them, once: it was [1]
    for i, rec in enumerate(ran.lines):
        if rec["event"] == "connected" and rec["connection"] > 1:
            before, cut, outcome = ran.lines[i - 1], ran.lines[i + 1], ran.lines[i + 2]
            assert (before["event"], before["phase"]) == ("attempt", "trickle")
            assert (cut["event"], cut["connection"]) == ("cut", rec["connection"])
            assert (outcome["event"], outcome["of"], outcome["result"], outcome["connect"]) == ("outcome", before["t_mono"], "refused", "opened")
    assert max(w for w, _t, _p in link.begun) < T0 + 300.0 and not [w for w in link.asked if w >= T0 + 300.0]          # nothing went to any of them
    every_attempt_has_one_outcome(ran)
    lines_are_in_form(B, ran.lines, ran.text)


def test_the_time_ceiling_is_said_once_in_a_run_by_whichever_reached_it(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 3 (its cases B09 and B12a). A burst that ended at the time ceiling wrote `ceiling minutes`,
    and the trickle that follows it and makes no attempt wrote it again. DECIDED: one line in a run. Where the burst reached
    the ceiling the line is the burst's and stands before its `burst-end`; else it is the trickle's, right before `stopped`."""
    clock = SuspendedClock()

    def script(link: FakeLink, clock_: ManualClock) -> None:
        clock_.at(T0 + 20.0, lambda: setattr(clock, "ahead", 1800.0))          # the host slept 30 minutes, 20 s into the burst

    ran = run(B, files, "count", capsys, clock=clock, script=script)
    events = [rec["event"] for rec in ran.lines]
    assert ran.rc == B.EXIT["burst-not-met"] and ran.one("burst-end")["why"] == "ceiling"
    assert [rec["which"] for rec in ran.events("ceiling")] == ["minutes"]          # once: it was written twice
    assert events.index("ceiling") < events.index("burst-end") and events[-2:] == ["burst-end", "stopped"]
    assert not [rec for rec in ran.events("attempt") if rec["phase"] == "trickle"] and ran.lines[-1]["why"] == "time-ceiling"
    lines_are_in_form(B, ran.lines, ran.text)
    files.log.unlink()
    (files.state / B.LEDGER).unlink()
    ran = run(B, files, "count", capsys)                            # a run whose burst ended long before: the line is the trickle's
    assert ran.rc == B.EXIT["ok"] and [rec["which"] for rec in ran.events("ceiling")] == ["minutes"]
    assert [rec["event"] for rec in ran.lines[-2:]] == ["ceiling", "stopped"]


def test_a_state_directory_a_log_or_a_thresholds_file_that_leads_into_a_work_tree_through_a_link_is_inside_one(
        B: Any, files: Any, capsys: Any, monkeypatch: Any) -> None:
    """burst-verify-r2, problem 4 (its case C06). The rule is the run plan's: a run's state, its log and the thresholds file
    stay outside every work tree. The check looked at each path as it was written: one reached through a symbolic link into a
    work tree was taken, and the ledger and the log were written inside the tree. Both forms are looked at now: the path as
    written, and where it leads. The system's answer for `where it leads` is given by hand here (no link can be made on every
    platform this file runs on, and none of its tests may skip); on POSIX the links are real as well."""
    tree = files.top / "a-work-tree"                                # stands for a work tree: a directory with a `.git` FILE, as a worktree has
    for name in ("state", "logs", "thr"):
        (tree / "sub" / name).mkdir(parents=True)
    (tree / ".git").write_text("gitdir: /nonexistent/somewhere-else\n", encoding="ascii")
    for name in ("thresholds.json", "derive.py"):
        (tree / "sub" / "thr" / name).write_bytes((files.thresholds.parent / name).read_bytes())
    held = sorted(str(p.relative_to(tree)) for p in tree.rglob("*"))
    real = os.path.realpath

    def leading(written: Path, to: Path) -> Callable[..., str]:
        def realpath(path: Any, **kwargs: Any) -> str:
            p = os.path.abspath(str(path))
            if p == str(written) or p.startswith(str(written) + os.sep):
                return str(to) + p[len(str(written)):]
            return str(real(path, **kwargs))
        return realpath

    def refused(argv: List[str]) -> None:
        ran = run(B, files, "count", capsys, argv=argv)
        assert ran.rc == B.EXIT["refused"] and ran.link is None and "burst: refused: inside-a-work-tree:" in ran.err, (argv, ran.err)
        assert str(files.top) not in ran.err and sorted(str(p.relative_to(tree)) for p in tree.rglob("*")) == held          # nothing written in it
        nothing_was_claimed_or_written(B, files)

    assert not B.in_a_work_tree(files.state) and not B.in_a_work_tree(files.log) and not B.in_a_work_tree(files.thresholds)
    cases = [(files.state, tree / "sub" / "state", run_argv(files)),
             (files.log.parent, tree / "sub" / "logs", run_argv(files)),
             (files.thresholds.parent, tree / "sub" / "thr", run_argv(files)),
             (files.thresholds.parent, tree / "sub" / "thr", ["check", "--thresholds", str(files.thresholds)])]
    for written, to, argv in cases:
        with monkeypatch.context() as patched:
            patched.setattr(B.os.path, "realpath", leading(written, to))
            refused(argv)
    # ... and a path that is WRITTEN inside a work tree is inside one wherever it leads
    with monkeypatch.context() as patched:
        patched.setattr(B.os.path, "realpath", leading(tree / "sub" / "state", files.state))
        assert B.in_a_work_tree(tree / "sub" / "state")
        refused(run_argv(files, state=tree / "sub" / "state"))
    if os.name == "posix":                                          # the links themselves, where they can be made
        (files.top / "state-by-a-link").symlink_to(tree / "sub" / "state", target_is_directory=True)
        (files.top / "logs-by-a-link").symlink_to(tree / "sub" / "logs", target_is_directory=True)
        (files.top / "thr-by-a-link").symlink_to(tree / "sub" / "thr", target_is_directory=True)
        refused(run_argv(files, state=files.top / "state-by-a-link"))
        refused(run_argv(files, log=files.top / "logs-by-a-link" / "run.jsonl"))
        by_link = types.SimpleNamespace(thresholds=files.top / "thr-by-a-link" / "thresholds.json", state=files.state, log=files.log)
        refused(run_argv(by_link))
    ran = run(B, files, "count", capsys)                            # with every path where it says it is, the same start is taken
    assert ran.rc == B.EXIT["ok"] and ran.link is not None


def test_a_state_directory_that_is_itself_a_work_trees_root_is_inside_one(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-final, problem 2 (its mutant M01; the ledger's burst-critic#4). The rule looks at a path AND at everything
    above it. A path that IS a work tree's root, a directory that holds a `.git` of its own (a FILE, as a worktree's root has,
    or a directory), lies inside one as well; the code is right, and with the path itself not looked at (only what lies above
    it) the whole file passed. Here --state is such a directory: the start is refused by its name, nothing is written in it,
    no log is begun and no link is made."""
    roots = {"git-file": lambda git: git.write_text("gitdir: /nonexistent/somewhere-else\n", encoding="ascii"),
             "git-directory": lambda git: git.mkdir()}
    for name, make in roots.items():
        root = files.top / ("root-with-a-" + name)
        root.mkdir()
        make(root / ".git")
        held = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
        assert B.in_a_work_tree(root) and not B.in_a_work_tree(files.state)          # the root itself, though nothing above it is one
        ran = run(B, files, "count", capsys, argv=run_argv(files, state=root))
        assert ran.rc == B.EXIT["refused"] == 1 and "burst: refused: inside-a-work-tree:" in ran.err, (name, ran.err)
        assert ran.link is None and not (root / B.LEDGER).exists() and not files.log.exists(), name
        assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == held, name          # nothing was written in it
        nothing_was_claimed_or_written(B, files)


def test_main_puts_the_earlier_signal_handlers_back_at_its_end_whichever_way_it_ends(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-final, problem 3 (its mutant M23; the ledger's burst-critic#5). main() with no stop of its own installs a
    handler for SIGINT and for SIGTERM first of all, and puts the earlier ones back at its end: it may be called by something
    that goes on after it. Nothing held that: with the restore taken out the whole file passed. Here two handlers of the test's
    own stand in front, and main() runs with no `stop` for `check`, for a run that is refused (the state directory is not
    there) and for a command line that cannot be read; the same two objects stand after each of them."""
    def earlier_interrupt(_signum: int, _frame: Any) -> None:
        raise AssertionError("the earlier SIGINT handler was called")

    def earlier_terminate(_signum: int, _frame: Any) -> None:
        raise AssertionError("the earlier SIGTERM handler was called")

    kept = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    ended: List[int] = []
    try:
        signal.signal(signal.SIGINT, earlier_interrupt)
        signal.signal(signal.SIGTERM, earlier_terminate)
        for argv in (["check", "--thresholds", str(files.thresholds)],
                     run_argv(files, state=files.top / "no-such-state"),
                     ["run", "--no-such-option"]):
            ended.append(B.main(argv, env=dict(ENV)))
            capsys.readouterr()
            assert signal.getsignal(signal.SIGINT) is earlier_interrupt, argv
            assert signal.getsignal(signal.SIGTERM) is earlier_terminate, argv
    finally:
        for number, handler in kept.items():
            if handler is not None:
                signal.signal(number, handler)
    assert ended == [B.EXIT["ok"], B.EXIT["refused"], B.EXIT["arguments"]]
    nothing_was_claimed_or_written(B, files)


class SaysUp(FakeLink):
    """A link whose reopen() answers `up`, a word the log's form does not have for an outcome, although it is down; from
    `comes_up_at` on it IS up when it says so: a connection the tool did not open."""

    comes_up_at: Optional[float] = None

    def reopen(self) -> str:
        now = self.clock.monotonic()
        self.connects.append((now, "asked"))
        if self.comes_up_at is not None and now >= self.comes_up_at:
            self.is_up = True
        return "up"


def test_an_answer_of_the_link_that_is_no_word_of_the_form_is_written_as_refused_and_nothing_is_handed_over_at_that_attempt(
        B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 6 (its case B18b). The link's answer to reopen() went into the outcome as it came: `connect:
    up`, which the form does not name (the tool's own link says `up` only for a connection in use, and is then not asked).
    DECIDED: an answer that is none of `opened`, `held` and `unanswered` is written as `refused`, not opened as far as the
    tool can say, with its `connect-failed` line and counted as a connection asked for; and an attempt that looked for a
    connection hands over only on one it opened itself. Here the link answers `up` from the cut at 300 s on, and from 600 s
    on it is up when it says so."""
    def script(link: Any, clock: ManualClock) -> None:
        link.comes_up_at = T0 + 600.0
        clock.at(T0 + 300.0, link.cut)

    ran = run(B, files, "shadow", capsys, script=script, link_class=SaysUp)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"]
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    looked = [rec for rec in ran.events("attempt") if "connect" in outcomes[rec["t_mono"]]]
    asked = [when for when, word in link.connects if word == "asked"]
    assert len(looked) == len(asked) > 25 and asked[-1] >= T0 + 600.0 > asked[-2]          # every 10 s from the cut to the one at which it came up
    assert {(outcomes[rec["t_mono"]]["result"], outcomes[rec["t_mono"]]["connect"]) for rec in looked} == {("refused", "refused")}
    assert len(ran.events("connect-failed")) == len(asked) and [rec["connection"] for rec in ran.events("connected")] == [1]
    for rec in looked:                                              # its `connect-failed` line stands between the attempt and its outcome
        i = ran.lines.index(rec)
        assert [x["event"] for x in ran.lines[i:i + 3]] == ["attempt", "connect-failed", "outcome"]
    assert not [w for w in link.asked if T0 + 300.0 <= w <= asked[-1]]          # nothing was handed over at any of them, the last included
    assert '"up"' not in ran.text
    lines_are_in_form(B, ran.lines, ran.text)
    every_attempt_has_one_outcome(ran)


class WeirdHandle(FakeHandle):
    """A handle whose answer, for the hand-overs the link's script marks `weird`, is none of the form's four result words."""

    def state(self) -> Optional[str]:
        return "weird" if self.word == "weird" else super().state()


class WeirdLink(FakeLink):
    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        handle = super().begin(topic, payload)
        return WeirdHandle(handle.link, handle.began, handle.word, handle.connection)


def test_an_answer_of_a_handle_that_is_none_of_the_forms_result_words_is_written_as_failed_in_the_burst_and_in_the_trickle(
        B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-final, problem 4 (its mutants M35 and M36; the ledger's burst-critic#6). A handle's answer that is none of
    `acked`, `failed`, `no-word` and `refused` is written as `failed`, in the burst and in the trickle alike, never as it
    came; the tool's own link cannot give such a word, and nothing held it: with either line taken out the whole file passed.
    Here the first hand-over of a shadow burst and the first of its trickle are answered `weird`: both outcomes say `failed`,
    the burst is not met, and the log is in its form (whose outcomes are the four words and no other)."""
    sends = burst_doc()["burst"]["shadow_updates"]

    def script(link: Any, _clock: ManualClock) -> None:
        link.word = lambda i, _topic, _payload: "weird" if i in (0, sends) else None          # the first burst hand-over and the first tick's

    ran = run(B, files, "shadow", capsys, script=script, link_class=WeirdLink)
    link = ran.link
    assert link is not None and len(link.begun) > sends and ran.rc == B.EXIT["burst-not-met"]
    attempts = ran.events("attempt")
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    first_burst = [rec for rec in attempts if rec["phase"] == "burst"][0]
    first_tick = [rec for rec in attempts if rec["phase"] == "trickle"][0]
    assert outcomes[first_burst["t_mono"]]["result"] == "failed" and outcomes[first_tick["t_mono"]]["result"] == "failed"
    assert [rec["result"] for rec in outcomes.values()].count("failed") == 2 and "weird" not in ran.text
    end = ran.one("burst-end")
    assert (end["met"], end["why"]) == (False, "failed")
    lines_are_in_form(B, ran.lines, ran.text)
    every_attempt_has_one_outcome(ran)


class Stalled:
    """A stream whose write does not return until it is released: a log on a file system that has stalled."""

    def __init__(self) -> None:
        self.inside, self.release = threading.Event(), threading.Event()
        self.written: List[str] = []

    def write(self, text: str) -> int:
        self.inside.set()
        self.release.wait(60.0)
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


@pytest.mark.parametrize("held_by", ["a-write-of-the-runs-own-thread", "the-watchdogs-own-write"])
def test_the_watchdog_ends_the_process_although_the_log_cannot_be_written(B: Any, monkeypatch: Any, held_by: str) -> None:
    """The hard review, its NIT on the watchdog and the log's lock. The watchdog writes its `stopped` line through the log,
    which takes the log's lock: with the run's own thread inside a write that does not return, the lock was never free and
    os._exit never came, so the last net of the time ceiling rested on the log. The line is written by a thread of its own
    now and waited for WATCHDOG_LINE_S at the most (shortened here): then the process is ended without it, also when it is
    the watchdog's own write that does not return."""
    ended: List[int] = []
    monkeypatch.setattr(B.os, "_exit", ended.append)
    monkeypatch.setattr(B, "WATCHDOG_LINE_S", 0.3, raising=False)
    stream = Stalled()
    log = B.Log(stream, ManualClock())
    holder = threading.Thread(target=log.write, args=("attempt",), kwargs={"phase": "trickle", "path": "ingest"}, daemon=True)
    stopper = threading.Thread(target=B._hard_stop, args=(log,), daemon=True)
    try:
        if held_by == "a-write-of-the-runs-own-thread":
            holder.start()
            assert stream.inside.wait(20.0)                         # the run's thread is inside a write, and holds the log's lock
        began = time.monotonic()
        stopper.start()
        stopper.join(8.0)
        took = time.monotonic() - began
        assert ended == [B.EXIT["watchdog"]] and not stopper.is_alive(), "the watchdog waited for the log"
        assert took < 8.0
    finally:
        stream.release.set()
        stopper.join(20.0)
        if holder.is_alive():
            holder.join(20.0)


def test_the_docstring_and_the_readme_say_what_the_rehearsal_of_wp8_found_in_a_logs_reading(B: Any, files: Any, capsys: Any) -> None:
    """WP8's rehearsal of the tool at the local broker (item 3). Four things a reader of a log, or whoever writes the run plan, was
    not told, each said now in the docstring and in the README (white space and code marks aside): a hand-over the log calls
    `failed` may have arrived; `cut` followed by `connected` is also what a second client under the thing's name looks like, so
    that the connector is stopped is a check and not a sentence; the ledger holds the host's boot id and is state; and, in the
    README alone, the opt-in tests' broker takes less than the tool's largest publish."""
    doc, readme = fold(str(B.__doc__)), fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    for said in ("WHAT failed AND no-word DO NOT SAY. Both say what the tool was told, never what the far end read.",
                 "a far end that only stalled reads it when it goes on, late and once",
                 "So the far end's count of a burst lies between the log's acked and its handed-over attempts, and met false with why failed "
                 "does not say that the far end received less than the burst: an alarm can act on a burst this log calls not met.",
                 "A cut FOLLOWED BY connected IS ALSO WHAT A SECOND CLIENT LOOKS LIKE.",
                 "The log cannot tell that from a breaker that did not hold, and the connector's own log says nothing when it loses the id.",
                 "So that the connector is stopped first is a CHECK before each start, and not a sentence",
                 "In the trickle a cut line is written at the tool's next look, so the time of a cut reads to one tick, 10 s.",
                 "THE LEDGER IS NOT THE LOG.",
                 "the host's boot id, a UUID that the leak scanner flags. It is state: it stays in the state directory and goes into no capture "
                 "and no record."):
        assert said in doc and said in readme, said
    assert "and its log ends with its stop line; and no connector is started again before the tool's stopped line" in doc
    for said in ("STOPPED IS A CHECK, of an exited container: before each start of the tool docker inspect -f '{{.State.Running}}' of the "
                 "connector says false, or names no such container, and the connector's log ends with its stop line; and no connector is "
                 "started again before the tool's stopped line",
                 "The opt-in tests' broker takes a packet of 131,072 bytes at the most (max_packet_size), which is less than the tool's "
                 "largest publish, 128 KiB of payload, with its header",
                 # read on the service's page on 2026-10-16 (the owner's A4 answers, question 7), where this said "is read at A1"
                 "gives the limit as the PAYLOAD's: 'MQTT payload size', 128 KB, not adjustable",
                 "The page does not say whether its KB is 1,000 or 1,024 bytes. The tool's ceiling alone does not settle "
                 "which reading a service uses; the thresholds document remains outside every work tree."):
        assert said in readme, said
    assert "is read at A1, before a thresholds file with publishes of that size is used" not in readme
    # what the sentences rest on, held where it can be: the tool's largest publish is the size the opt-in tests' broker takes as a
    # whole packet, and a claim's line holds the boot id beside the four other keys
    broker = (HERE / "test_sdv_connector_broker.py").read_text(encoding="utf-8")
    assert B.MAX_PUBLISH_BYTES == 128 * 1024 == 131072 and '"max_packet_size %d"' % B.MAX_PUBLISH_BYTES in broker
    ran = run(B, files, "count", capsys)
    assert ran.rc == B.EXIT["ok"]
    claims = [json.loads(line) for line in (files.state / B.LEDGER).read_text(encoding="utf-8").split("\n") if line]
    assert len(claims) == 1 and sorted(claims[0]) == ["boot", "claim", "kind", "mono", "wall"]


def test_the_docstring_and_the_readme_say_what_the_review_fix_decided(B: Any) -> None:
    """burst-review-fix. The sentences this round's decisions are written down in stand in the tool's docstring and in its
    README, word for word (white space and code marks aside): each said something else before, or nothing."""
    doc, readme = fold(str(B.__doc__)), fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    for said in (
            "run --kind count|bytes|shadow --thresholds FILE --thresholds-sha256 HEX --state DIR --log FILE [--derive FILE]",
            "check --thresholds FILE [--thresholds-sha256 HEX] [--derive FILE]",
            "THE HANDLERS COME FIRST: main() installs both before it reads its command line and before every check.",
            "In its image the tool is PID 1 of its container, and for the first process of a PID namespace the kernel drops a signal whose "
            "handling is the default one",
            "A signal that comes BEFORE THE CLAIM ends the start as a refusal by a name, stopped-before-start (exit status 1), which says which "
            "signal: nothing was claimed, nothing was opened, nothing is sent; derive.py's check is not waited for",
            "NOT HELD: a signal in the first moments of the process, before the interpreter has reached main(): as PID 1 the tool never sees "
            "it. docker run --init puts a first process in front of the tool that passes signals on",
            "AND IT IS HELD TO THE FILE THE ALARMS WERE MADE FROM, BY ITS SHA256.",
            "refuses a file whose bytes do not have it (thresholds-not-the-alarms), before derive.py is run and before anything is opened. The "
            "bytes that were hashed are the bytes the plan is read from.",
            "The hash is not written into the log: whether a log may hold it is the owner's to say.",
            "One attempt every 10 s, the two topics in turn, is at the most 16 on a topic and 31 on both in any 300 s, the alarms' period read as "
            "a closed window",
            "(trickle-over-threshold:count|bytes|shadow)",
            "THE WATCHDOG, a thread of the tool's own, reads the SAME clock once a second and ends the process 30 s after the time ceiling, "
            "whatever a call is waiting for (exit status 6).",
            "a host that slept inside a call that never came back is seen at the first look after it woke",
            "Its stopped line is written by a thread of its own and waited for 1 s at the most",
            "for one that was opened in an attempt of the trickle and lost before that attempt's hand-over, right after its connected line",
            "minutes is written once in a run, by whichever reached the time ceiling",
            "also written for an answer of the link's that is none of these words: not opened, as far as the tool can say, and counted as asked for",
            "1 refused before any connection, by a name (a signal that came before the claim is one: stopped-before-start)",
            "and so is a hash that is not 64 hexadecimal digits in lower case"):
        assert said in doc, said
        assert said in readme, said
    assert "A timer of the interpreter's own ends the process" not in doc + readme
    assert "The command line takes a kind and paths and nothing else" not in doc + readme


# ================================================================================================= burst-review-fix-exact (burst-verify-r2's
# problems 1, 5 and 7 to 12, and the hard review's NITs 5 and 6): what the package states and no test held. None of them changes what
# the tool does; each test below fails on the file with the one edit its mutant makes (the regression cases below).

class SilentAfterTheBurst(FakeLink):
    """A far end that takes every connection (`back_at` is set by the test) and answers no publish after the burst's own."""

    def __init__(self, clock: ManualClock) -> None:
        super().__init__(clock)
        self.burst_sends = 0
        self.word = lambda i, topic, payload: "silent" if i >= self.burst_sends else None


def test_a_connection_opened_anew_and_lost_again_has_its_cut_line_before_the_attempt_that_found_it(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 1 (its mutant M27, the first half). Cut at 100 s, with a new connection possible from that moment: the
    next attempt says the cut of connection 1, opens connection 2, and its hand-overs are acknowledged. Cut again at 300 s: the cut of
    connection 2 is said as well, on the line before the attempt of the tick that found it, and that attempt opens a third. The form
    says `cut` once for each connection the tool noticed lost; the log said it for the first alone."""
    def script(link: FakeLink, clock: ManualClock) -> None:
        def first() -> None:
            link.cut()
            link.back_at = T0 + 100.0                               # a new connection can be opened from this moment on
        clock.at(T0 + 100.0, first)
        clock.at(T0 + 300.0, link.cut)

    ran = run(B, files, "shadow", capsys, script=script)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"], ran.err
    cuts, connected = ran.events("cut"), ran.events("connected")
    assert [rec["connection"] for rec in cuts] == [1, 2] and [rec["connection"] for rec in connected] == [1, 2, 3]
    for rec in cuts:                                                # each stands right before the attempt of the tick that found it
        after = ran.lines[ran.lines.index(rec) + 1]
        assert (after["event"], after["phase"]) == ("attempt", "trickle"), rec
    assert ran.lines[ran.lines.index(cuts[1]) + 2] == connected[2]  # ... and the third connection is opened by that attempt
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    between = [rec for rec in ran.events("attempt") if connected[1]["t_mono"] < rec["t_mono"] < cuts[1]["t_mono"]]
    assert len(between) > 15 and {outcomes[rec["t_mono"]]["result"] for rec in between} == {"acked"}          # connection 2 was used
    opened = T0 + connected[1]["t_mono"] - 1e-3                      # (the log's times are rounded to the microsecond)
    on_two = [w for w, _t, _p in link.begun if opened <= w < T0 + 300.0]
    assert len(on_two) >= len(between) and not [w for w, _t, _p in link.begun if T0 + 100.0 <= w < opened]
    held_to_its_two_topics(B, ran)
    every_attempt_has_one_outcome(ran)
    lines_are_in_form(B, ran.lines, ran.text)


def test_a_trickle_hand_over_that_gets_no_word_gives_its_connection_up_and_the_next_attempt_says_the_cut_and_asks_for_a_new_one(
        B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 1 (its mutants M28 and M27, on their own wire: the verifier's case B27). After a met burst the far
    end takes every connection and answers no publish any more. Each trickle hand-over is `no-word` after the tool's wait, and its
    connection is given up (gap y: the log says when an attempt is refused or cut): the link counts one give-up for each; the attempt
    after it says the cut of that connection on the line before it and asks for a new connection, which its outcome names. The form says
    of such a hand-over `(the connection is then given up)`."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: Any, clock: ManualClock) -> None:
        link.burst_sends = plan.sends
        link.back_at = T0

    ran = run(B, files, "count", capsys, script=script, link_class=SilentAfterTheBurst)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["ok"], ran.err
    trickle = [rec for rec in ran.events("outcome") if rec["phase"] == "trickle"]
    silent = [rec for rec in trickle if rec["result"] == "no-word"]
    assert len(silent) > 100 and {rec["result"] for rec in trickle} == {"no-word", "refused"}
    assert link.given_up == len(silent)                             # one give-up for each hand-over without a word, and no other
    cuts = ran.events("cut")
    assert [rec["connection"] for rec in cuts] == list(range(1, len(cuts) + 1)) and len(cuts) >= len(silent) - 1
    outcomes = {rec["of"]: rec for rec in ran.events("outcome")}
    for number, rec in enumerate(silent, start=1):
        later = [x for x in ran.lines[ran.lines.index(rec) + 1:] if x["event"] == "attempt"]
        if not later:                                               # the run's last: nothing is attempted after it
            assert number == len(silent)
            continue
        i = ran.lines.index(later[0])
        assert (ran.lines[i - 1]["event"], ran.lines[i - 1]["connection"]) == ("cut", number), (number, ran.lines[i - 1])
        assert outcomes[later[0]["t_mono"]]["connect"] in ("opened", "ceiling"), later[0]
    assert [rec["connection"] for rec in ran.events("connected")] == list(range(1, len(ran.events("connected")) + 1))
    assert len(ran.events("connected")) > 100 and len(ran.events("connected")) - 1 <= B.CONNECTS_MAX
    every_attempt_has_one_outcome(ran)
    lines_are_in_form(B, ran.lines, ran.text)


def test_the_trickles_publish_on_the_rules_topic_is_exactly_64_bytes(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 7 (its mutant M11). Gap y: each attempt of the trickle is small. The test of the whole run compared
    the publishes with the constant, which a constant of 4 KiB satisfies as well."""
    plan = B.load_plan("count", files.thresholds, None)
    ran = run(B, files, "count", capsys)
    assert ran.link is not None and ran.rc == B.EXIT["ok"]
    on_the_rule = [p for _w, topic, p in ran.link.begun[plan.sends:] if topic == topics_of(B).telemetry]
    assert B.TRICKLE_PUBLISH_BYTES == 64 and len(on_the_rule) > 50 and {len(p) for p in on_the_rule} == {64}


def test_a_bursts_span_is_from_its_first_hand_over_to_its_last_and_not_to_its_last_answer(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 7 (its mutant M26). Every answer takes 0.4 s: `span_s` is the last hand-over minus the first, to three
    places, and less than the time to the last answer, which the burst waits for before it sums itself up."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: FakeLink, clock: ManualClock) -> None:
        link.ack_after = 0.4

    ran = run(B, files, "count", capsys, script=script)
    assert ran.link is not None and ran.rc == B.EXIT["ok"], ran.err
    burst = ran.link.begun[:plan.sends]
    end, start = ran.one("burst-end"), ran.one("burst-start")
    assert end["span_s"] == round(burst[-1][0] - burst[0][0], 3) and 39.0 < end["span_s"] < B.WINDOW_S
    assert end["t_mono"] - start["t_mono"] >= end["span_s"] + 0.4 - 1e-3          # the burst waited for the last answer, after the last hand-over


class LostBetweenLookAndHandOver(FakeLink):
    """A link whose begin() raises the link's own UplinkError at its `refuses_at`-th call, as a connection does that was lost between
    the tool's look and the hand-over: the publish is not handed over."""

    refuses_at = 0

    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        if len(self.asked) + 1 == self.refuses_at:
            self.asked.append(self.clock.monotonic())
            raise self._error()("lost between the look and the hand-over to %s" % ENDPOINT)
        return super().begin(topic, payload)


def test_a_burst_hand_over_the_link_refused_is_logged_refused_and_was_not_handed_over(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 7 (its mutant M52; the trickle's own is held by L4). The 9th hand-over of the burst is refused by the
    link: `refused` is `NOT handed over`, so its outcome says that and not `failed`, it is not among what reached the wire, and the
    burst goes on with the next."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: Any, clock: ManualClock) -> None:
        link.refuses_at = 9

    ran = run(B, files, "count", capsys, script=script, link_class=LostBetweenLookAndHandOver)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["burst-not-met"], ran.err
    burst = [rec for rec in ran.events("attempt") if rec["phase"] == "burst"]
    outcomes = {rec["of"]: rec["result"] for rec in ran.events("outcome")}
    assert len(burst) == plan.sends and outcomes[burst[8]["t_mono"]] == "refused"
    assert {outcomes[rec["t_mono"]] for i, rec in enumerate(burst) if i != 8} == {"acked"}
    assert len([x for x in link.begun if len(x[2]) == plan.size]) == plan.sends - 1 and len(link.asked) - len(link.begun) == 1
    assert link.asked[8] not in [w for w, _t, _p in link.begun]    # the refused one is not among what reached the wire
    end = ran.one("burst-end")
    assert end["met"] is False and end["why"] == "failed" and end["ratio"] == 0.99


def test_a_bursts_connection_lost_after_its_last_hand_over_and_before_its_answers_ends_the_burst_cut(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 7 (its mutant M65). Every answer takes 0.4 s and the connection is cut 0.13 s after the last hand-over:
    the last few are failed by the loss, and the burst's end says `cut`, not `failed` (the same loss in the middle of the burst
    ends it `cut` as well: the form names one cause)."""
    plan = B.load_plan("count", files.thresholds, None)

    def script(link: FakeLink, clock: ManualClock) -> None:
        link.ack_after = 0.4
        clock.at(T0 + 40.1, link.cut)

    ran = run(B, files, "count", capsys, script=script)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["burst-not-met"], ran.err
    last = link.begun[plan.sends - 1][0]
    assert T0 + 39.5 < last < T0 + 40.1 and len(link.begun) == plan.sends          # the cut came after the last hand-over
    end = ran.one("burst-end")
    results = [rec["result"] for rec in ran.events("outcome") if rec["phase"] == "burst"]
    assert 0 < results.count("failed") < 20 and results.count("acked") + results.count("failed") == plan.sends
    assert (end["why"], end["met"], end["inside_window"]) == ("cut", False, True) and 0.9 < end["ratio"] < 1.0
    assert ran.one("cut")["t_mono"] <= end["t_mono"]


class SignalledWhileClosing(FakeLink):
    """A link whose close() is where a second signal comes in: the stop is raised again, by another name."""

    stop: Any = None

    def close(self) -> None:
        if self.stop is not None:
            self.stop.set("SIGTERM")
        super().close()


def test_the_last_line_names_the_signal_that_stopped_the_run_and_a_later_one_does_not_rename_it(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 7 (its mutant M42; the verifier's real case R3 kept SIGINT). The first signal stops the run; a second
    one that comes while the link is closed is the same stop: the stop's name stays the first's, and `stopped` says so."""
    stop = B.Stop()
    assert not stop and stop.name is None
    stop.set("SIGINT")
    stop.set("SIGTERM")
    assert stop and stop.name == "SIGINT"
    stop = B.Stop()

    def script(link: Any, clock: ManualClock) -> None:
        link.stop = stop
        clock.at(T0 + 100.0, lambda: stop.set("SIGINT"))

    ran = run(B, files, "count", capsys, script=script, stop=stop, link_class=SignalledWhileClosing)
    assert ran.link is not None and ran.link.closes == 1 and stop.name == "SIGINT"
    last = ran.lines[-1]
    assert (last["event"], last["why"], last["signal"]) == ("stopped", "signal", "SIGINT") and ran.rc == B.EXIT["ok"]


class SlowBegin(FakeLink):
    """A link whose first begin() takes `takes` seconds on the test's clock (a call into the SDK that waits on a busy socket)."""

    takes = 0.0

    def begin(self, topic: str, payload: bytes) -> FakeHandle:
        handle = super().begin(topic, payload)
        if self.takes and len(self.begun) == 1:
            self.clock.sleep(self.takes)
        return handle


def test_a_hand_over_exactly_60_s_after_the_bursts_start_is_not_made_and_one_a_moment_before_is(B: Any, tmp_path: Path) -> None:
    """burst-verify-r2, problem 8 (its mutant M23). Decision 2: a hand-over that would come 60 s or more after the burst's start is
    not made. The first hand-over takes the whole 60.0 s on the clock, so that the second would be made at exactly 60.0: it is not,
    and the burst ends `window-over`. Taking 59.9 s, the same second hand-over is made, and the burst is whole."""
    plan = by_hand(B, "count", 2, 256)
    clock = ManualClock()
    link = SlowBegin(clock)
    link.takes = 60.0
    rc, lines = go(B, plan, clock, link, tmp_path)
    end = [rec for rec in lines if rec["event"] == "burst-end"][0]
    assert len([x for x in link.begun if len(x[2]) == 256]) == 1 and rc == B.EXIT["burst-not-met"]          # the second is not there
    assert (end["why"], end["met"], end["inside_window"]) == ("window-over", False, False)
    clock = ManualClock()
    link = SlowBegin(clock)
    link.takes = 59.9
    rc, lines = go(B, plan, clock, link, tmp_path)
    end = [rec for rec in lines if rec["event"] == "burst-end"][0]
    assert len([x for x in link.begun if len(x[2]) == 256]) == 2 and rc == B.EXIT["ok"]
    assert (end["why"], end["met"], end["inside_window"]) == ("complete", True, True)


def test_a_burst_of_exactly_8_mib_is_handed_over_whole_and_one_publish_more_is_cut_off_at_the_ceiling(B: Any, tmp_path: Path) -> None:
    """burst-verify-r2, problem 8 (its mutant M54). 64 publishes of 128 KiB are exactly the bytes ceiling, which the file's own check
    takes: the run's counter takes them too (64 handed over, no `ceiling` line but the time's). A 65th is the one the ceiling cuts."""
    size = 128 * 1024
    assert 64 * size == B.CEILINGS["bytes"] and size == B.MAX_PUBLISH_BYTES
    clock = ManualClock()
    link = FakeLink(clock)
    rc, lines = go(B, by_hand(B, "bytes", 64, size), clock, link, tmp_path)
    end = [rec for rec in lines if rec["event"] == "burst-end"][0]
    assert len([x for x in link.begun if len(x[2]) == size]) == 64 and rc == B.EXIT["ok"]
    assert (end["why"], end["met"], end["ratio"]) == ("complete", True, 1.0)
    assert [rec["which"] for rec in lines if rec["event"] == "ceiling"] == ["minutes"]
    clock = ManualClock()
    link = FakeLink(clock)
    rc, lines = go(B, by_hand(B, "bytes", 65, size), clock, link, tmp_path)
    end = [rec for rec in lines if rec["event"] == "burst-end"][0]
    assert len([x for x in link.begun if len(x[2]) == size]) == 64 and rc == B.EXIT["burst-not-met"]
    assert (end["why"], end["met"]) == ("ceiling", False)
    assert [rec["which"] for rec in lines if rec["event"] == "ceiling"] == ["bytes", "minutes"]


def test_exactly_20_hand_overs_without_an_answer_are_outstanding_at_the_most_and_never_21(B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 8 (its mutant M55). The far end answers nothing: the burst hands over 20 publishes and then waits
    (the tool's own window of publishes in flight is full), until the first has had no word for the tool's wait and its connection is
    given up. Counted at every hand-over from what the link was given, 20 are outstanding at the most, and never 21."""
    def script(link: FakeLink, clock: ManualClock) -> None:
        link.word = lambda i, topic, payload: "silent"

    ran = run(B, files, "count", capsys, script=script)
    link = ran.link
    assert link is not None and ran.rc == B.EXIT["burst-not-met"], ran.err
    burst = [rec for rec in ran.events("attempt") if rec["phase"] == "burst"]
    assert B.INFLIGHT_MAX_PUBLISHES == 20 and len(burst) == len(link.begun) == 20
    outstanding = [1 + sum(1 for j in range(i) if link.begun[j][0] + B.SETTLE_S > link.begun[i][0]) for i in range(len(burst))]
    assert max(outstanding) == 20
    end = ran.one("burst-end")
    assert (end["why"], end["met"], end["ratio"]) == ("cut", False, 0.0)


def test_settings_that_are_missing_and_an_sdk_that_is_not_installed_are_refusals_by_a_name_and_nothing_is_claimed(
        B: Any, files: Any, capsys: Any) -> None:
    """burst-verify-r2, problem 9 (its mutants M34 and M35). Both come from making the link, before the claim: status 1 and the name
    (`settings`, `sdk`), not status 5 (an error no check names); nothing is claimed and nothing is written. The endpoint is in no line."""
    class NoSettings:
        def __init__(self, clock: ManualClock) -> None:
            raise B.UplinkError("the endpoint is missing (%s)" % ENDPOINT)

    class NoSdk:
        def __init__(self, clock: ManualClock) -> None:
            raise ImportError("No module named 'awscrt' at %s" % ENDPOINT)

    for link_class, name in ((NoSettings, "settings"), (NoSdk, "sdk")):
        ran = run(B, files, "count", capsys, link_class=link_class)
        assert ran.rc == B.EXIT["refused"] == 1 and ran.link is None and ran.out == "", (name, ran.rc, ran.err)
        assert ran.err.startswith("burst: refused: %s:" % name) and ran.err.count("\n") == 1 and ENDPOINT not in ran.err, (name, ran.err)
        nothing_was_claimed_or_written(B, files)


def test_the_systems_clock_is_boottime_where_the_platform_has_it_and_monotonic_where_it_has_not(B: Any, monkeypatch: Any) -> None:
    """burst-verify-r2, problem 10 (its mutant M40). Decision 2: CLOCK_BOOTTIME where the platform has it, so that a suspended host is
    not a longer run. With a `time` of the test's own: the clock's value is CLOCK_BOOTTIME's; where the call raises OSError, or the
    platform has no such clock, it is time.monotonic's."""
    asked: List[int] = []

    def boottime(which: int) -> float:
        asked.append(which)
        return 123.5 if which == 7 else -1.0

    def refusing(which: int) -> float:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(B, "time", types.SimpleNamespace(CLOCK_BOOTTIME=7, clock_gettime=boottime, monotonic=lambda: 1.25))
    assert B.SystemClock().monotonic() == 123.5 and asked == [7]
    monkeypatch.setattr(B, "time", types.SimpleNamespace(CLOCK_BOOTTIME=7, clock_gettime=refusing, monotonic=lambda: 1.25))
    assert B.SystemClock().monotonic() == 1.25
    monkeypatch.setattr(B, "time", types.SimpleNamespace(monotonic=lambda: 1.25))
    assert B.SystemClock().monotonic() == 1.25


def test_the_systems_boot_is_the_kernels_boot_id_and_none_where_there_is_none(B: Any, monkeypatch: Any) -> None:
    """burst-verify-r2, problem 10 (its mutant M41). Decision 4: on one boot the claims are compared on the monotonic clock. The boot
    is the kernel's boot id when the read gives one (a container has its host's); a text that is no id, an empty one and a read that
    raises OSError are none, and the claims are then compared on the wall clock."""
    real = Path.read_text
    wanted = "0d2c6a52-3f1b-4e0a-9a53-0123456789ab"

    def reading(answer: Any) -> Callable[..., str]:
        def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.as_posix().endswith("proc/sys/kernel/random/boot_id"):
                if isinstance(answer, BaseException):
                    raise answer
                return str(answer)
            return real(self, *args, **kwargs)
        return read_text

    for answer, want in ((wanted + "\n", wanted), ("not a boot id\n", None), ("", None), (OSError(2, "No such file or directory"), None)):
        monkeypatch.setattr(Path, "read_text", reading(answer))
        assert B.SystemClock().boot() == want, answer


class RaisesWhenLookedAt:
    """The SDK's answer to a publish that raises when it is asked what became of it."""

    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return False

    def exception(self) -> Any:
        raise RuntimeError("the answer cannot be read")


class AnswersWell:
    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return False

    def exception(self) -> Any:
        return None


def test_an_answer_of_the_sdk_that_raises_when_it_is_looked_at_is_failed_and_no_sign_of_life(B: Any, sdk_link: Any) -> None:
    """burst-verify-r2, problem 11 (its mutant L03). `acked` counts toward a burst's `met`: an answer that cannot be read is a failure
    for good, and the connection's life is not moved by it. A good answer is `acked` and moves it to the moment the request was begun."""
    s = sdk_link
    s.link.connect()
    inner = s.link._in_use()
    assert inner is not None
    life = inner.life
    later = life + 100.0
    broken = s.mod.Handle(inner, RaisesWhenLookedAt(), later)
    assert broken.state() == "failed" and broken.state() == "failed" and inner.life == life
    fine = s.mod.Handle(inner, AnswersWell(), later)
    assert fine.state() == "acked" and inner.life == later


def test_a_link_that_was_closed_asks_the_sdk_for_no_connection_when_it_is_asked_to_reopen(B: Any, sdk_link: Any) -> None:
    """burst-verify-r2, problem 11 (its mutant L04). reopen() on a link that was opened and then closed says `refused` and the SDK is
    asked for nothing: not a connection built, not a connect. The back-off is over (the clock has run past it), so that only the closed
    link says no; the tree's test of the guard has the never-opened half."""
    s = sdk_link
    link, sdk, clock = s.link, s.sdk, s.clock
    link.connect()
    link.close()
    clock.sleep(B.limits.RECONNECT_MAX_S + 1.0)
    built, connects = len(sdk.built), len(sdk.connects)
    assert link.reopen() == "refused" and not link.up()
    assert len(sdk.built) == built and len(sdk.connects) == connects


# ================================================================================================= WP8's fix before A2 (wp8-core; the burst
# package's critic, open item 1): a signal that lands INSIDE the claim. The test fails on the file as it was.

class SignalledInTheClaim(ManualClock):
    """A clock whose boot() raises the stop. The claim asks the clock for the boot once, after its first read of the ledger and
    before it writes its own line; nothing else of a start does. So a signal raised there lands INSIDE the claim: after the tool's
    last look at the stop ahead of it."""

    def __init__(self, stop: Any, name: str) -> None:
        super().__init__()
        self.stop, self.name, self.boots = stop, name, 0

    def boot(self) -> Optional[str]:
        self.boots += 1
        self.stop.set(self.name)
        return super().boot()


def test_a_signal_that_lands_inside_the_claim_holds_the_window_and_no_connection_is_asked_for(B: Any, files: Any, capsys: Any) -> None:
    """Decision 8. The stop was looked at right ahead of the claim and not again before the first connection was asked for: a
    signal that landed inside the claim itself left the window claimed AND one connection opened and closed (nothing was handed
    over), while the tool's own sentence said that such a start opened nothing. The stop is read once more, right before the first
    connection is asked for. The window is held all the same: the claim is in the ledger, and a claim is never taken back."""
    stop = B.Stop()
    clock = SignalledInTheClaim(stop, "SIGTERM")
    ran = run(B, files, "count", capsys, clock=clock, stop=stop)
    assert clock.boots == 1                                         # the claim asked for the boot, and nothing else did
    assert ran.link is not None and ran.link.connects == [] and ran.link.asked == [] and ran.link.closes == 0          # made, and asked for nothing
    assert (ran.rc, ran.out, ran.err) == (B.EXIT["burst-not-met"], "", "")          # a run, not a refusal: its window is held
    lines_are_in_form(B, ran.lines, ran.text)
    assert [rec["event"] for rec in ran.lines] == ["start", "stopped"]
    assert {k: ran.lines[1][k] for k in ("why", "signal", "burst_met", "exit")} == {"why": "signal", "signal": "SIGTERM", "burst_met": False,
                                                                                    "exit": 4}
    # the ledger holds the claim and no word that takes it back
    entries = [json.loads(line) for line in (files.state / B.LEDGER).read_text(encoding="utf-8").split("\n") if line]
    assert len(entries) == 1 and set(entries[0]) == {"claim", "boot", "mono", "wall", "kind"} and entries[0]["kind"] == "count"
    # a second start inside the 20 minutes is told that the window is held, and opens nothing
    log = files.top / "logs" / "second.jsonl"
    second = run(B, files, "count", capsys, clock=ManualClock(T0 + 60.0, WALL0 + 60.0), log=log)
    assert second.rc == B.EXIT["refused"] and second.err.startswith("burst: refused: window-held:") and second.out == ""
    assert second.link is not None and second.link.connects == [] and not log.exists()
    # the tool's own sentences say it, and no longer that such a signal finds a run like any other
    doc, readme = fold(str(B.__doc__)), fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    for said in (
            "BEFORE THE CLAIM is: before the tool's last look at the stop, which stands right ahead of the claim.",
            "THE STOP IS READ ONCE MORE RIGHT BEFORE THE FIRST CONNECTION IS ASKED FOR: a signal that landed inside the claim itself, or "
            "between the claim and that look, ends the run there.",
            "No connection is asked for; the log holds start and stopped (why signal) and nothing between them; the exit status is 4, a "
            "burst that was not met; and the next start inside the 20 minutes is refused as window-held.",
            "A signal that comes later still stops the run as above: a first connection that is being opened is waited for, and is handed "
            "nothing.",
            "With why signal right after start, no line between the two: the signal came before the first connection was asked for, and "
            "none was (decision 8)"):
        assert said in doc, said
        assert said in readme, said
    assert "A signal that comes after the claim finds a run: it is stopped as above" not in doc + readme


def test_the_readme_says_how_a_go_is_withdrawn_where_the_three_mounts_go_and_how_a_frozen_process_reads(B: Any) -> None:
    """wp8-review-fix-exact (WP8's item 3b, findings F3, F5 and F6), in the README alone, white space and code marks aside: a go is
    withdrawn with `docker stop -t 20` and never with a bare `docker stop`, whose 10 s are shorter than the tool's own waits; a
    `ceiling minutes` line later than 1,200 s says that the process did not run meanwhile; and the three read-only mounts of
    derive.py's inputs go where its own defaults look for them, relative to its own directory."""
    readme = fold((BURST_DIR / "README.md").read_text(encoding="utf-8"))
    for said in (
            "A GO IS WITHDRAWN WITH docker stop -t 20, or with docker kill -s TERM and a wait for the container's exit, and never with a "
            "bare docker stop.",
            "A bare one gives the tool 10 s before its KILL, and the tool's own waits are longer: a first connection that is being opened "
            "at a far end that accepts and says nothing is waited for as long as the connector's wait for a connection's answer (10 s), "
            "and the link's close takes up to 2 s more.",
            "a KILL leaves a log with no stopped line and a held window.",
            "A PROCESS THAT WAS FROZEN AND RELEASED READS AS A GAP. A ceiling minutes line (the ceiling event, which minutes) whose t_mono "
            "is later than 1,200 s by more than a moment says that the process did not run meanwhile, and the stretch without lines "
            "before it is a stretch in which nothing tried",
            "The run's own look at the clock ends such a run with its burst's status.",
            "THE THREE MOUNTS GO WHERE derive.py'S OWN DEFAULTS LOOK FOR THEM, relative to its own directory, "
            "which is the thresholds directory: the cost model's directory (cost_model.py and prices.json) and the connector's limits.py.",
            "derive.py and its defaults live beside the thresholds file, outside every work tree, "
            "and so do the run plan's three --mount type=bind,...,readonly lines.",
            "The thresholds directory is mounted at /run/sdv-local/thresholds (where the opt-in tests put it).",
            "The limits.py mounted is the one the image was built from. With one of the three missing, check and run refuse "
            "(thresholds-check-failed)."):
        assert said in readme, said
    # what the sentences add up, held where it can be: the connector's wait for a connection's answer and the link's close
    assert B.CONNECT_ANSWER_S == 10.0 and B.limits.CLOSE_WAIT_S == 2.0
    assert "thresholds-check-failed" in (BURST_DIR / "burst.py").read_text(encoding="utf-8")


def test_the_burst_documents_keep_to_the_width_of_their_files(B: Any) -> None:
    """burst-critic#8 (wp8-review-fix-exact). A re-wrap changes no word, so no test of words can see one: the README (110 columns),
    the docstring (120) and the burst tool's bullet in the connector's README (110) were re-wrapped to the width their files keep,
    and a line wider than that is a paragraph that was joined, or a sentence that was added without the wrap."""
    readme = (BURST_DIR / "README.md").read_text(encoding="utf-8").splitlines()
    assert len(readme) > 300 and max(len(line) for line in readme) <= 110
    docstring = str(B.__doc__).splitlines()
    assert len(docstring) > 200 and max(len(line) for line in docstring) <= 120
    connector = (REPO / "sdv" / "connector" / "README.md").read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(connector) if line.startswith("- **The burst tool**"))
    bullet = [connector[first]]
    for line in connector[first + 1:]:
        if not line.startswith("  "):
            break
        bullet.append(line)
    assert len(bullet) >= 5 and max(len(line) for line in bullet) <= 110
