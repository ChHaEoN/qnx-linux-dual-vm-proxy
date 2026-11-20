"""The stack's bound on a replay's player from the recording's own span (sdv/stack/stack.py player_bound_s and replay_once;
video 4's package PB).

Pure tests (standard library; no Docker, no bus, no databroker, no python-can): python-can's LogReader is replaced by an
exact stand-in of what the bound reads of a candump file (CanutilsLogReader's "(seconds)" column: blank lines skipped,
three fields a line, the stamp between its parentheses; the file opened when the reader is made, a suffix other than
.log refused), and replay_once's every outside call by a stand-in.
  * the bound: the log's span from its first to its last frame as the stack decodes it (replaycheck.decode_recording's
    milliseconds), plus PLAYER_HEADROOM_S, rounded up to a whole second; a log at PLAYER_BOUND_MAX_S is taken and one
    second past it refused; a log with no frame, one not in time order (a frame stamped before the one ahead of it;
    frames of one stamp are in order), one that cannot be read and a host without python-can refused; each refusal
    names the log's file name, never its path; the file is read once and nothing is written;
  * replay_once: a log over the ceiling or not in time order refused before docker, vcan, the player or any file of the
    replay, on either feed; the vcan feed's can.player call and the dumpfile feed's wait for the provider's end each take
    the bound, and the vcan feed's wait for the provider's start keeps START_TIMEOUT_S;
  * the design values, and sdv/stack/README.md saying the rule in one place.
In the sim venv (skipped without it): the bound read by the real python-can from a candump file.

Does not demonstrate: that a real player or provider ends within its bound, that any recording of the project replays,
or any timing: the bound is a timeout, never a figure.
"""
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import stack  # noqa: E402

sys.dont_write_bytecode = _saved
attr, rc = stack.attr, stack.rc
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX only (the stack runs in WSL)")
T0 = 1763290000.0          # a candump stamp's seconds, as a log's first frame carries them


class CandumpReader:
    """python-can's LogReader on a candump file, replaced: each line's stamp as CanutilsLogReader parses it, nothing else."""

    made: List[str] = []

    def __init__(self, filename: str) -> None:
        if Path(filename).suffix.lower() != ".log":
            raise ValueError('No read support for unknown log format "%s"' % Path(filename).suffix)
        CandumpReader.made.append(filename)
        self.file = Path(filename).open(mode="r", encoding="utf-8")

    def __enter__(self) -> "CandumpReader":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.file.close()

    def __iter__(self) -> Any:
        for line in self.file:
            temp = line.strip()
            if not temp:
                continue
            stamp, _channel, _frame = temp.split()
            yield types.SimpleNamespace(timestamp=float(stamp[1:-1]))


@pytest.fixture
def candump(monkeypatch: Any) -> Any:
    CandumpReader.made = []
    monkeypatch.setitem(sys.modules, "can", types.SimpleNamespace(LogReader=CandumpReader))
    return CandumpReader


def candump_log(path: Path, stamps: List[float]) -> Path:
    """A candump -l file whose frames carry these stamps (seconds), one SliceDynamics-sized frame each."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join("(%.6f) vcan0 100#0000000000000000\n" % t for t in stamps), encoding="ascii")
    return path


def tree_of(root: Path) -> List[Any]:
    return sorted((str(p.relative_to(root)), p.stat().st_size if p.is_file() else None) for p in root.rglob("*"))


# --- the bound ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("offsets, bound", [
    ([0.0, 10.0], 40),                        # a whole number of seconds: the headroom alone, nothing rounded up
    ([0.0, 6.0, 12.3456], 43),                # 12346 ms (the decoder's milliseconds) and 30 s, rounded up to 43 s
    ([0.0, 10.0006], 41),                     # 10001 ms: one millisecond past 40 s rounds up to 41 s
    ([0.0, 10.0004], 40),                     # 10000 ms as the decoder rounds it: 40 s
    ([0.0, 0.5, 1.0, 100.0], 130),            # the frames between the first and the last do not change it
    ([0.0], 30),                              # one frame: a span of 0, the headroom alone
])
def test_the_bound_is_the_logs_span_from_its_first_to_its_last_frame_plus_the_headroom_rounded_up(tmp_path, candump, offsets, bound):
    log = candump_log(tmp_path / "sigsim.log", [T0 + o for o in offsets])
    got = stack.player_bound_s(log)
    assert got == bound and isinstance(got, int), got


def test_the_bound_at_the_ceiling_is_taken_and_one_second_past_it_is_refused_naming_the_logs_file_only(tmp_path, candump):
    room = stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S
    at = candump_log(tmp_path / "at" / "carla.log", [T0, T0 + 1.0, T0 + room])
    assert stack.player_bound_s(at) == stack.PLAYER_BOUND_MAX_S
    past = candump_log(tmp_path / "past" / "carla.log", [T0, T0 + 1.0, T0 + room + 0.001])
    with pytest.raises(stack.StackError) as e:
        stack.player_bound_s(past)
    msg = str(e.value)
    assert "carla.log" in msg and str(tmp_path) not in msg and "%d s" % stack.PLAYER_BOUND_MAX_S in msg, msg
    assert "PLAYER_BOUND_MAX_S" in msg and "refused" in msg, msg


@pytest.mark.parametrize("offset, outcome", [
    (869.9994, 900),          # 869999 ms rounds up to 900 s
    (870.0004, 900),          # 870000.4 ms is 870000 ms as the decoder rounds it: 900 s
    (870.0006, "refused"),    # 870000.6 ms is 870001 ms: 901 s, refused
])
def test_the_ceiling_is_read_in_the_decoders_milliseconds(tmp_path, candump, offset, outcome):
    log = candump_log(tmp_path / "carla.log", [T0, T0 + offset])
    if outcome == "refused":
        with pytest.raises(stack.StackError) as e:
            stack.player_bound_s(log)
        assert "PLAYER_BOUND_MAX_S" in str(e.value) and "carla.log" in str(e.value)
    else:
        assert stack.player_bound_s(log) == outcome


@pytest.mark.parametrize("offsets", [
    [31.0, 0.0],                              # stamped backwards: its last frame less its first is -31 s, a bound of -1 s
    [100.0, 50.0, 0.0],                       # backwards throughout: a bound of -70 s
    [0.0, 2000.0, 10.0],                      # a middle frame far past the last: played to 2000 s, its last frame says 40 s
    [0.0, 100.0, 5.0],                        # log order: its last frame is not its latest stamp
])
def test_a_log_not_in_time_order_is_refused_naming_its_file_never_its_path(tmp_path, candump, offsets):
    """python-can's player sends each frame at its own stamp's offset from the first frame's, so a log stamped out of order
    plays to its latest stamp, not to its last frame's: its first to its last frame bounds no such player, and the log is
    refused, read once."""
    home = tmp_path / "home" / "someone" / "sdv-runs" / "20990101-x" / "in"
    log = candump_log(home / "carla.log", [T0 + o for o in offsets])
    with pytest.raises(stack.StackError) as e:
        stack.player_bound_s(log)
    msg = str(e.value)
    assert "carla.log" in msg and "not in time order" in msg and str(home) not in msg and "someone" not in msg, msg
    assert candump.made == [str(log)], candump.made


def test_frames_of_one_stamp_are_in_time_order(tmp_path, candump):
    """A frame is out of order only when stamped before the one ahead of it: frames of one stamp (a schedule's two messages
    of one instant) are taken, and the span is still the log's first to its last frame."""
    log = candump_log(tmp_path / "carla.log", [T0, T0, T0 + 5.0, T0 + 5.0])
    assert stack.player_bound_s(log) == 35


@pytest.mark.parametrize("problem", ["empty", "blank lines only", "missing", "a directory", "a line that is no frame", "no python-can"])
def test_a_log_with_no_frame_or_that_cannot_be_read_is_refused_naming_its_file_never_its_path(tmp_path, candump, monkeypatch, problem):
    home = tmp_path / "home" / "someone" / "sdv-runs" / "20990101-x" / "in"
    home.mkdir(parents=True)
    log = home / "sigsim.log"
    if problem == "empty":
        log.write_text("", encoding="ascii")
    elif problem == "blank lines only":
        log.write_text("\n  \n\n", encoding="ascii")
    elif problem == "a directory":
        log.mkdir()
    elif problem == "a line that is no frame":
        log.write_text("(%.6f) vcan0 100#00\nnot a candump line\n" % T0, encoding="ascii")
    elif problem == "no python-can":
        candump_log(log, [T0, T0 + 1.0])
        monkeypatch.setitem(sys.modules, "can", None)          # `import can` raises ImportError
    with pytest.raises(stack.StackError) as e:
        stack.player_bound_s(log)
    msg = str(e.value)
    assert "sigsim.log" in msg and str(home) not in msg and "someone" not in msg, msg
    if problem in ("empty", "blank lines only"):
        assert "no frame" in msg, msg
    else:
        assert "cannot be read" in msg, msg


def test_the_bound_reads_the_log_once_and_writes_nothing(tmp_path, candump):
    log = candump_log(tmp_path / "in" / "sigsim.log", [T0, T0 + 5.0])
    before = tree_of(tmp_path)
    assert stack.player_bound_s(log) == 35
    assert candump.made == [str(log)], candump.made
    assert tree_of(tmp_path) == before


def test_the_design_values_are_the_specs():
    """PLAYER_HEADROOM_S an int, 30; PLAYER_BOUND_MAX_S an int, 900."""
    for value, want in ((stack.PLAYER_HEADROOM_S, 30), (stack.PLAYER_BOUND_MAX_S, 900)):
        assert type(value) is int and value == want, value
    doc = re.sub(r"\s+", " ", stack.__doc__ or "")          # the module docstring's FEEDS says both values
    assert "PLAYER_HEADROOM_S (%d s)" % stack.PLAYER_HEADROOM_S in doc and "PLAYER_BOUND_MAX_S (%d s)" % stack.PLAYER_BOUND_MAX_S in doc


# --- replay_once ----------------------------------------------------------------------------------------------------------

def replay_ctx(tmp_path: Path, log_name: str = "sigsim.log") -> Any:
    """A context replay_once can run with every outside call replaced, its staged log under in/."""
    return types.SimpleNamespace(bridge="none", monitor_mode="native", monitor=None, guest=None, run_dir=tmp_path / "runs" / "p",
                                 run_header=lambda rid, feed: {"run_id": rid}, check_header=lambda h: ("C12a", True, "synthetic"),
                                 rows=[], image_ids=lambda: {}, staged={log_name: "ab" * 32}, scenario={"dbc_sha256": "x"},
                                 manifest={"scenario_checks": []}, decoded={"values": {rc.V_PATH: [], attr.SLOT_PATHS[4]: []}},
                                 in_dir=tmp_path / "in", log_name=log_name, cpuset=None, after_start=None, after_start_records=[])


def refused_before_any_effect(tmp_path: Path, monkeypatch: Any, feed: str, offsets: List[float]) -> str:
    """replay_once on a staged carla.log of these stamps, every outside call replaced by one that fails the test: the
    StackError's words, once nothing was called, written or made."""
    candump_log(tmp_path / "in" / "carla.log", [T0 + o for o in offsets])
    called: List[str] = []

    def touched(name: str) -> Any:
        def fn(*_a: Any, **_kw: Any) -> Any:
            called.append(name)
            raise AssertionError("the replay reached %s though its log was refused" % name)
        return fn

    for name in ("docker", "run", "ensure_vcan", "up", "remove_stack", "start", "host_listeners", "write_json", "VcanCapture",
                 "wait_log", "wait_for", "collect", "stop_containers", "build_native_monitor", "log_frames"):
        monkeypatch.setattr(stack, name, touched(name))
    ctx = replay_ctx(tmp_path, "carla.log")
    ctx.run_header = touched("run_header")
    before = tree_of(tmp_path)
    with pytest.raises(stack.StackError) as e:
        stack.replay_once(ctx, feed, "%s-1" % feed)
    assert called == [] and tree_of(tmp_path) == before and not ctx.run_dir.exists()
    return str(e.value)


@POSIX
@pytest.mark.parametrize("feed", ["vcan", "dumpfile"])
def test_replay_once_refuses_a_log_over_the_ceiling_before_any_container_vcan_player_or_file(tmp_path, candump, monkeypatch, feed):
    room = stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S
    msg = refused_before_any_effect(tmp_path, monkeypatch, feed, [0.0, room + 1.0])
    assert "carla.log" in msg and "PLAYER_BOUND_MAX_S" in msg, msg


@POSIX
@pytest.mark.parametrize("feed", ["vcan", "dumpfile"])
def test_replay_once_refuses_a_log_not_in_time_order_before_any_container_vcan_player_or_file(tmp_path, candump, monkeypatch, feed):
    msg = refused_before_any_effect(tmp_path, monkeypatch, feed, [0.0, 2000.0, 10.0])          # under the ceiling by its last frame
    assert "carla.log" in msg and "not in time order" in msg, msg


def replay_world(monkeypatch: Any) -> Dict[str, List[Any]]:
    """replay_once's outside calls replaced, the player's run and every wait_log kept with their bounds."""
    seen: Dict[str, List[Any]] = {"run": [], "wait_log": []}

    def fake_up(ctx: Any, feed: str, rd: Path, label: str, header: Any = None) -> Dict[str, Any]:
        rd.mkdir(parents=True, exist_ok=True)
        return {"feed": feed, "listeners_before": {}, "listeners": {"ok": True}}

    def listeners_now(info: Dict[str, Any], feed: str, suffix: str, allowed: Any = ()) -> None:
        info["listeners" + suffix] = {"ok": True}

    def fake_run(cmd: Any, check: bool = True, timeout: Any = None, input_text: Any = None) -> subprocess.CompletedProcess:
        seen["run"].append((list(cmd), {"check": check, "timeout": timeout}))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    class Capture:
        def close(self) -> List[Tuple[int, bytes]]:
            return []

    fakes: List[Tuple[str, Any]] = [
        ("up", fake_up), ("listeners_now", listeners_now), ("wait_for", lambda *a, **kw: None),
        ("wait_log", lambda name, pattern, timeout: seen["wait_log"].append((name, pattern, timeout))),
        ("stop_containers", lambda ctx: None), ("collect", lambda rd: {}), ("remove_stack", lambda: None),
        ("analyse", lambda ctx, rd: {}), ("record_close", lambda header, rd, console=None: ("C12b", True, "synthetic")),
        ("start", lambda ctx, comp, feed, rd, label: ""), ("running_images", lambda: {}), ("run", fake_run),
        ("log_frames", lambda path: []), ("VcanCapture", Capture), ("docker", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", ""))]
    for name, fn in fakes:
        monkeypatch.setattr(stack, name, fn)
    for name, fn in (("check_recording", lambda header, sha, dbc: ("C10", True, "synthetic")), ("run_rows", lambda rows, ids: []),
                     ("check_images", lambda rows, running: ("C8", True, "synthetic")), ("render_markdown", lambda h, r: "")):
        monkeypatch.setattr(attr, name, fn)
    monkeypatch.setattr(stack, "VCAN_READY_S", 0.0)
    monkeypatch.setattr(stack.time, "sleep", lambda _s: None)
    return seen


@POSIX
@pytest.mark.parametrize("feed", ["vcan", "dumpfile"])
def test_the_players_run_and_the_dumpfile_feeds_wait_for_the_providers_end_take_the_bound(tmp_path, candump, monkeypatch, feed):
    seen = replay_world(monkeypatch)
    log = candump_log(tmp_path / "in" / "carla.log", [T0, T0 + 6.0, T0 + 12.3456])          # 12346 ms: a bound of 43 s
    ctx = replay_ctx(tmp_path, "carla.log")
    stack.replay_once(ctx, feed, "%s-1" % feed)
    can = stack.NAMES[attr.CAN_PROVIDER]
    if feed == "vcan":
        assert seen["run"] == [([str(stack.SIM_PY), "-m", "can.player", "-i", "socketcan", "-c", stack.VCAN, str(log)],
                                {"check": False, "timeout": 43})], seen["run"]
        assert seen["wait_log"] == [(can, r"Starting to receive CAN messages|Using DBC reader", stack.START_TIMEOUT_S)], seen["wait_log"]
    else:
        assert seen["run"] == [], seen["run"]
        assert seen["wait_log"] == [(can, r"Replayed all messages from CAN log file", 43)], seen["wait_log"]
    assert candump.made == [str(log)], "the bound read the staged log once"


# --- the sim venv: the real python-can -----------------------------------------------------------------------------------

READ = """
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import stack
for p in sys.argv[2:]:
    try:
        print("bound %d" % stack.player_bound_s(Path(p)))
    except stack.StackError as exc:
        print("refused: %s" % exc)
"""


@POSIX
@pytest.mark.skipif(not stack.SIM_PY.is_file(), reason="needs the sim venv (~/sdv-sim-venv, SDV_SIM_VENV) for the real python-can")
def test_with_the_real_python_can_the_bound_reads_a_candump_file_as_the_stand_in_does(tmp_path):
    room = stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S
    logs = [candump_log(tmp_path / "a" / "sigsim.log", [T0, T0 + 6.0, T0 + 12.3456]),
            candump_log(tmp_path / "b" / "carla.log", [T0, T0 + room]),
            candump_log(tmp_path / "c" / "carla.log", [T0, T0 + room + 0.001]),
            candump_log(tmp_path / "d" / "sigsim.log", [])]
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "sigsim.log").write_text("(%.6f) vcan0 100#00\nnot a candump line\n" % T0, encoding="ascii")
    unordered = candump_log(tmp_path / "f" / "carla.log", [T0, T0 + 2000.0, T0 + 10.0])
    env = {k: v for k, v in os.environ.items() if k not in ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([str(stack.SIM_PY), "-B", "-c", READ, str(STACK_DIR)] + [str(p) for p in logs] + [str(tmp_path / "e" / "sigsim.log"),
                                                                                                       str(unordered)],
                       capture_output=True, text=True, timeout=120, env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[:2] == ["bound 43", "bound %d" % stack.PLAYER_BOUND_MAX_S], lines
    assert lines[2].startswith("refused: ") and "carla.log" in lines[2] and "PLAYER_BOUND_MAX_S" in lines[2], lines
    assert lines[3].startswith("refused: ") and "no frame" in lines[3], lines
    assert lines[4].startswith("refused: ") and "cannot be read" in lines[4] and str(tmp_path) not in lines[4], lines
    assert lines[5].startswith("refused: ") and "not in time order" in lines[5] and str(tmp_path) not in lines[5], lines
    assert len(lines) == 6, lines


# --- sdv/stack/README.md ---------------------------------------------------------------------------------------------------

def test_the_stack_readme_says_the_rule_in_one_place():
    """The bound is the log's span plus 30 s, at most 900 s, and a longer log (or one not in time order)
    is refused before the replay starts, said once, under the rules the stack keeps; the old fixed bound is said nowhere."""
    text = (STACK_DIR / "README.md").read_text(encoding="utf-8")
    rules = re.search(r"^## The rules it keeps\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert rules
    bullets = [re.sub(r"\s+", " ", b) for b in re.findall(r"^- (.*?)(?=^- |^\n|\Z)", text, re.M | re.S)]
    said = [b for b in bullets if b.startswith("**The player's bound.**")]
    assert len(said) == 1 and said[0] in re.sub(r"\s+", " ", rules.group(1)), said
    for words in ("the log's own span", "its first to its last frame", "plus %d s" % stack.PLAYER_HEADROOM_S,
                  "rounded up to a whole second", "at most %d s" % stack.PLAYER_BOUND_MAX_S, "refused before the replay starts",
                  "`player_bound_s`", "not in time order"):
        assert words in said[0], (words, said[0])
    flat = re.sub(r"\s+", " ", text)
    assert "300 s bound" not in flat and flat.count("plus %d s" % stack.PLAYER_HEADROOM_S) == 1, "the rule is said in one place"
