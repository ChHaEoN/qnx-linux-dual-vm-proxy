"""The fleet runner (sdv/stack/fleet.py): video 3's fleet, package P1.

Pure tests (standard library; no Docker, no bus, no databroker): fleet.py is run in this process, on made-up recordings,
a made-up generation and DBC cache (stack.py's paths pointed at them), with the stack's decoder replaced by one that
reads the made-up log's speeds, python-can's reader (stack.py's player_bound_s reads a log's times with it) by one that
reads the made-up log's times, docker's container list and the host's listeners replaced, and stack.py's replay
replaced by a stand-in car process (a script written here) that keeps the gate as the stack does.
  * check: one line per car (label, recording name, run type, moves, distinct) and no other value; a recording that
    moves for at least MIN_MOVING_S by its log's own times (|v| > 0.1 m/s, trip_summary.py's rule) moves, a parked one
    and one that moves for less does not; two cars with one recording (one sha256) are not distinct; exit 0, 1, or 2
    for a command line or a recording the stack refuses, a log its decoder cannot read among them; it writes nothing;
    a log's span runs from its first to its last frame of any message;
  * run's refusals, one at a time, each before anything is written, made or started, each naming the variable or the
    car and never a value: a car check would not pass, a car whose bound on its player the stack refuses (stack.py's
    player_bound_s for its own log: past the ceiling, or not in time order) or whose log ends too near that bound, no
    connector image or one the stack's own rule refuses, a host role other than pc, each device directory rule, a shared
    device directory or thing (a thing given twice is its last line, as docker reads it), the five variables of its own
    environment, a stack container, a port already listened on, the fleet stamp and each car's identity stamp inside the
    start spacing (a car's that is no stamp or from the future too, naming the file to remove), the run directory; a
    fleet stamp that is no stamp or from the future is refused once and written anew;
  * the sequence against stand-in cars: each car started only once the one before it is ready, in a process group of
    its own, go only after every car is ready and none has ended, abort when a car ends before go, gives no ready within
    the wait, or the fleet is interrupted or fails before go, and then one SIGINT to the car still preparing; after go an
    interrupt (SIGINT, SIGTERM) gives every running car one SIGINT and the record is still written; a car past its bound
    is interrupted, and one that ignores that is killed with its process group and its instance's containers removed;
    each car's argument vector, environment and working directory (the repo); the stamps (car A the caller's state
    directory, B and C their own, the fleet's stamp); three short cars pass as before, each bounded by its own log;
  * fleet.json word for word, every path in it relative and each car's its own, a car's witness named though its replay
    left no result.json, the window's two days UTC's whatever the local zone, and no device directory's path, no name
    of a file in it and no value of connector.env anywhere under the run (the cars' logs are masked, the identity's
    values whatever their length);
  * the opt-in broker test's helpers: its guard on the player's bound, its sweep (vcanf1 to vcanf3), and its one new run
    directory held, with the fleet's output, before it is unpacked;
  * the design values;
  * sdv/stack/README.md's fleet section, the next after the twin connector's: its names and design values are fleet.py's
    and stack.py's own.

Does not demonstrate: anything about the real stack, Docker, the bus, a databroker or a broker (the opt-in
tests/test_sdv_fleet_broker.py runs three real cars against a local broker); the real decoder on a real recording; any
timing; that a real stack's finally, interrupted at any point of its prepare, removes all it started.
"""
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"
V_PATH = "Vehicle.DualVm.Motion.LongitudinalVelocity"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import fleet  # noqa: E402

sys.dont_write_bytecode = _saved
stack = fleet.stack
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX only (the fleet runs in WSL)")

DBC = b'VERSION ""\n\nBO_ 256 SliceDynamics: 8 SIGSRC\n SG_ LongVel : 0|16@1- (0.01,0) [-327.68|327.67] "m/s" VSSRX\n'
DBC_SHA = hashlib.sha256(DBC).hexdigest()
OTHER_DBC = DBC.replace(b'VERSION ""', b'VERSION "another"')          # a DBC the made-up generation was not made from
OTHER_DBC_SHA = hashlib.sha256(OTHER_DBC).hexdigest()
IMAGE = "sha256:" + "c0" * 32
THINGS = {"A": "example-thing-a", "B": "example-thing-b", "C": "example-thing-c"}
ENDPOINT = "broker.example.test"


def _nest(nodes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    tree: Dict[str, Any] = {}
    for path, node in nodes.items():
        *branches, leaf = path.split(".")
        level = tree
        for b in branches:
            level = level.setdefault(b, {"type": "branch", "children": {}})["children"]
        level[leaf] = node
    return tree


def speeds(moving_ms: int, v: float = 5.0, start_ms: int = 2000, step_ms: int = 100, tail_ms: int = 3000) -> List[Any]:
    """A made-up drive: standing, then |v| = v from start_ms for moving_ms (its first and last moving samples moving_ms
    apart), then standing again."""
    out: List[Any] = [[t, 0.0] for t in range(0, start_ms, step_ms)]
    out += [[start_ms + t, v] for t in range(0, moving_ms + 1, step_ms)]
    end = start_ms + moving_ms
    out += [[end + t, 0.0] for t in range(step_ms, tail_ms, step_ms)]
    return out


class MadeUpLogReader:
    """python-can's LogReader as stack.py's player_bound_s reads a log, replaced: the made-up log's frames, each at its t_ms."""

    def __init__(self, filename: str) -> None:
        self.rows = json.loads(Path(filename).read_text(encoding="utf-8"))

    def __enter__(self) -> "MadeUpLogReader":
        return self

    def __exit__(self, *_exc: Any) -> None:
        pass

    def __iter__(self) -> Any:
        return iter([types.SimpleNamespace(timestamp=int(t) / 1000.0) for t, _v in self.rows])


class Rig:
    """A made-up generation, DBC cache and overlay, stack.py's paths pointed at them, the decoder replaced by one that
    reads the made-up log (JSON: [[t_ms, v], ...]) as SliceDynamics frames, and python-can's reader by MadeUpLogReader."""

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        self.tmp = tmp_path
        self.gen = tmp_path / "gen"
        self.gen.mkdir()
        overlay = tmp_path / "overlay.vspec"
        overlay.write_text("# a made-up overlay\n", encoding="utf-8")
        mapping = {V_PATH: {"type": "sensor", "datatype": "float", "dbc2vss": {"signal": "LongVel", "interval_ms": 0, "on_change": False}},
                   "Vehicle.Speed": {"type": "sensor", "datatype": "float",
                                     "dbc2vss": {"signal": "LongVel", "interval_ms": 0, "on_change": False, "transform": {"math": "abs(x) * 3.6"}}}}
        (self.gen / "vss-can-mapping.json").write_text(json.dumps(_nest(mapping)), encoding="utf-8")
        catalogue = {p: {k: v for k, v in n.items() if k != "dbc2vss"} for p, n in mapping.items()}
        (self.gen / "vss-databroker.json").write_text(json.dumps(_nest(catalogue)), encoding="utf-8")
        contract = 'VSS_COMMIT = "c1"\nVSS_ARCHIVE_SHA256 = "d2"\nVSS_TOOLS_VERSION = "0.0.0"\nCATALOG_DIGEST = 0x12345678\n'
        (self.gen / "vss_contract.py").write_text(contract, encoding="utf-8")
        (self.gen / "vss-ids.vspec").write_text("# a made-up catalogue id file\n", encoding="utf-8")       # the connector image's label
        self.manifest = {"inputs": {"overlay.vspec": stack.sha256_file(overlay), "slice.dbc": DBC_SHA}}
        self.write_manifest()
        self.cache = tmp_path / "cache"
        (self.cache / "dbc").mkdir(parents=True)
        (self.cache / "dbc" / ("%s.dbc" % DBC_SHA)).write_bytes(DBC)
        self.recs = tmp_path / "recordings"
        self.recs.mkdir()
        self.decoded: List[Any] = []
        for name, value in (("GEN", self.gen), ("OVERLAY", overlay), ("CACHE", self.cache)):
            monkeypatch.setattr(stack, name, value)

        def fake_decode(log_path: Path, dbc_path: Path, mapping: Dict[str, Any], transforms: Dict[str, Any]) -> Dict[str, Any]:
            self.decoded.append((Path(log_path), Path(dbc_path), sorted(mapping)))
            frames = [(int(t), "SliceDynamics", {"LongVel": float(v)}) for t, v in json.loads(Path(log_path).read_text(encoding="utf-8"))]
            values = {p: [transforms[p](f[2]["LongVel"]) for f in frames] for p in mapping}
            return {"values": values, "half_lsb": {p: 0.005 for p in mapping}, "frames": frames}

        monkeypatch.setattr(stack.rc, "decode_recording", fake_decode)
        monkeypatch.setitem(sys.modules, "can", types.SimpleNamespace(LogReader=MadeUpLogReader))

    def write_manifest(self) -> None:
        (self.gen / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def recording(self, name: str, drive: Sequence[Any], gen: str = "sigsim", dbc_sha: str = DBC_SHA, line_sha: Optional[str] = None) -> Path:
        d = self.recs / name
        d.mkdir()
        log_name = {"sigsim": "sigsim.log", "carla": "carla.log", "carla-autoware": "carla.log"}[gen]
        data = (json.dumps([list(x) for x in drive]) + "\n").encode("ascii")
        (d / log_name).write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        (d / (log_name + ".sha256")).write_text("%s  %s\n" % (sha, log_name), encoding="ascii")
        params: Dict[str, Any] = {"dbc_sha256": dbc_sha}
        if gen != "carla-autoware":
            params["seed"] = 7
        line = {"name": name, "profile_id": 1, "recording": {"format": "candump-log", "path": "~/rec/%s/%s" % (name, log_name),
                                                             "sha256": line_sha or sha},
                "source": {"generator": gen, "vehicle": {"name": "made-up", "wheelbase_mm": 2468}, "params": params}}
        (d / "manifest-line.json").write_text(json.dumps(line), encoding="ascii")
        return d

    def twin(self, of: Path, name: str) -> Path:
        """Another directory holding the same recording (the same log, so the same sha256)."""
        d = self.recs / name
        shutil.copytree(of, d)
        return d


def run_main(argv: List[str], capsys: Any) -> types.SimpleNamespace:
    code = fleet.main(argv)
    out, err = capsys.readouterr()
    return types.SimpleNamespace(code=code, out=out, err=err, lines=out.splitlines())


def tree_of(root: Path) -> List[Any]:
    return sorted((str(p.relative_to(root)), p.stat().st_size if p.is_file() else None) for p in root.rglob("*"))


# --- check ------------------------------------------------------------------------------------------------------------

def test_check_prints_one_line_per_car_and_exits_0_when_every_car_moves_and_all_are_distinct(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(75_000, v=-3.0))
    c = rig.recording("20990101-drive-c", speeds(61_000))
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert (r.code, r.lines) == (0, ["A 20990101-drive-a sigsim moves: yes distinct: yes", "B 20990101-drive-b sigsim moves: yes distinct: yes"]), r
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b, "--car", "C=%s" % c], capsys)
    assert r.code == 0 and r.lines[2] == "C 20990101-drive-c sigsim moves: yes distinct: yes" and len(r.lines) == 3, r


@pytest.mark.parametrize("drive, moves", [
    (speeds(0, v=0.0), "no"),                                  # parked throughout
    ([[t, 0.1 if t % 200 else -0.1] for t in range(0, 300_000, 100)], "no"),     # never above 0.1 m/s
    ([[0, 0.0], [2_000, 5.0], [41_999, 5.0], [45_000, 0.0]], "no"),     # moving, but its first and last moving samples 39.999 s apart
    (speeds(40_000), "yes"),                                   # exactly MIN_MOVING_S apart
    (speeds(60_000, v=-0.11), "yes"),                          # reversing just above the threshold
    ([[0, 5.0], [30_000, 0.0], [60_000, 5.0]], "yes"),         # first and last moving samples, whatever lies between
])
def test_check_moves_by_the_first_and_the_last_sample_above_0_1_m_s_by_the_logs_own_times(tmp_path, monkeypatch, capsys, drive, moves):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", drive)
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert r.lines[1] == "B 20990101-drive-b sigsim moves: %s distinct: yes" % moves, r
    assert r.code == (0 if moves == "yes" else 1)


@pytest.mark.parametrize("moving_ms, moves", [(48_000, "yes"), (39_000, "no")])
def test_check_a_synthetic_drive_that_stands_moves_and_stands_again_obeys_the_minimum(tmp_path, monkeypatch, capsys, moving_ms, moves):
    """A synthetic drive: standing, moving, standing again. As car C it moves when its first and last moving samples
    are farther apart than MIN_MOVING_S, and does not below it; its log is longer than MIN_MOVING_S either way."""
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(75_000, v=-3.0))
    drive = speeds(moving_ms, start_ms=20_000, tail_ms=20_000)
    assert drive[-1][0] - drive[0][0] > fleet.MIN_MOVING_S * 1000
    c = rig.recording("20990101-drive-c", drive)
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b, "--car", "C=%s" % c], capsys)
    assert r.lines[2] == "C 20990101-drive-c sigsim moves: %s distinct: yes" % moves, r
    assert r.code == (0 if moves == "yes" else 1)


def test_check_two_cars_with_one_recording_are_not_distinct(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    a2 = rig.twin(a, "20990101-drive-a-copy")
    c = rig.recording("20990101-drive-c", speeds(70_000))
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % a2], capsys)
    assert (r.code, r.lines) == (1, ["A 20990101-drive-a sigsim moves: yes distinct: no",
                                     "B 20990101-drive-a-copy sigsim moves: yes distinct: no"]), r
    r = run_main(["check", "--car", "A=%s" % c, "--car", "B=%s" % a, "--car", "C=%s" % a], capsys)
    assert r.code == 1 and [ln.rsplit(" ", 1)[1] for ln in r.lines] == ["yes", "no", "no"], r


def test_check_three_cars_one_parked_exits_1_naming_only_that_car(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(70_000))
    c = rig.recording("20990101-drive-c", speeds(0, v=0.0))
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b, "--car", "C=%s" % c], capsys)
    assert (r.code, r.lines) == (1, ["A 20990101-drive-a sigsim moves: yes distinct: yes",
                                     "B 20990101-drive-b sigsim moves: yes distinct: yes",
                                     "C 20990101-drive-c sigsim moves: no distinct: yes"]), r


def test_check_prints_no_other_value_and_writes_nothing(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(70_000))
    before = tree_of(tmp_path)
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert tree_of(tmp_path) == before, "check wrote something"
    for ln in r.lines:
        assert re.fullmatch(r"[AB] 20990101-drive-[ab] sigsim moves: (yes|no) distinct: (yes|no)", ln), ln
    sha = json.loads((a / "manifest-line.json").read_text(encoding="utf-8"))["recording"]["sha256"]
    assert sha not in r.out + r.err and str(a) not in r.out


def test_check_decodes_the_recordings_own_log_with_the_dbc_from_the_cache(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(70_000), gen="carla")
    rig.manifest.update(vehicle_layers={"carla": {"file": "vehicle-carla.vspec"}}, databroker_catalogues={"carla": "vss-databroker.json"})
    layer = b"Vehicle.Chassis.Wheelbase:\n  default: 2468\n"
    (rig.gen / "vehicle-carla.vspec").write_bytes(layer)
    rig.manifest["outputs"] = {"vehicle-carla.vspec": {"sha256": hashlib.sha256(layer).hexdigest()},
                               "vss-databroker.json": {"sha256": stack.sha256_file(rig.gen / "vss-databroker.json")}}
    rig.write_manifest()
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert r.code == 0 and r.lines[1] == "B 20990101-drive-b carla moves: yes distinct: yes", r
    assert [(x[0], x[1]) for x in rig.decoded] == [(a / "sigsim.log", rig.cache / "dbc" / ("%s.dbc" % DBC_SHA)),
                                                    (b / "carla.log", rig.cache / "dbc" / ("%s.dbc" % DBC_SHA))]
    assert all(V_PATH in x[2] for x in rig.decoded)


@pytest.mark.parametrize("cars", [
    ["A"], ["B", "A"], ["A", "A"], ["A", "C"], ["A", "B", "C", "A"], ["A", "B", "D"], ["a", "b"],
])
def test_check_exits_2_for_a_command_line_of_other_cars(tmp_path, monkeypatch, capsys, cars):
    rig = Rig(tmp_path, monkeypatch)
    recs = [rig.recording("20990101-drive-%d" % i, speeds(90_000 + i)) for i in range(len(cars))]
    argv = ["check"]
    for label, rec in zip(cars, recs):
        argv += ["--car", "%s=%s" % (label, rec)]
    r = run_main(argv, capsys)
    assert r.code == 2 and r.out == "", r


@pytest.mark.parametrize("word", ["A", "A=", "=x", "A:x"])
def test_check_exits_2_for_a_car_that_is_not_label_equals_directory(tmp_path, monkeypatch, capsys, word):
    rig = Rig(tmp_path, monkeypatch)
    b = rig.recording("20990101-drive-b", speeds(90_000))
    r = run_main(["check", "--car", word, "--car", "B=%s" % b], capsys)
    assert r.code == 2 and r.out == "", r


@pytest.mark.parametrize("problem", ["no directory", "log sha", "dbc not cached", "generation of another dbc",
                                     "carla on a generation without its pair"])
def test_check_exits_2_for_a_recording_the_stack_refuses_and_writes_nothing(tmp_path, monkeypatch, capsys, problem):
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    if problem == "no directory":
        b = rig.recs / "20990101-not-there"
    elif problem == "log sha":
        b = rig.recording("20990101-drive-b", speeds(70_000), line_sha="ab" * 32)
    elif problem == "dbc not cached":
        shutil.rmtree(rig.cache / "dbc")
        b = rig.recording("20990101-drive-b", speeds(70_000))
    elif problem == "generation of another dbc":
        b = rig.recording("20990101-drive-b", speeds(70_000), dbc_sha=OTHER_DBC_SHA)
        (rig.cache / "dbc" / ("%s.dbc" % OTHER_DBC_SHA)).write_bytes(OTHER_DBC)
    else:
        b = rig.recording("20990101-drive-b", speeds(70_000), gen="carla")
    before = tree_of(tmp_path)
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert r.code == 2 and "B" in r.err, r
    assert tree_of(tmp_path) == before, "check wrote something"


def test_check_refuses_a_log_its_decoder_cannot_read_with_exit_2_and_nothing_on_stdout(tmp_path, monkeypatch, capsys):
    """Whatever the stack's decoder raises on a log it cannot read (here a ValueError, no StackError) is the stack refusing
    the recording: exit 2, nothing on stdout, the car named on stderr, and no traceback."""
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))
    b = rig.recording("20990101-drive-b", speeds(70_000))

    def unreadable(*_a: Any, **_kw: Any) -> Any:
        raise ValueError("made up: a frame the decoder cannot read")

    monkeypatch.setattr(stack.rc, "decode_recording", unreadable)
    r = run_main(["check", "--car", "A=%s" % a, "--car", "B=%s" % b], capsys)
    assert r.code == 2 and r.out == "" and "car A" in r.err, r


def test_the_logs_span_runs_from_its_first_to_its_last_frame_of_any_message(tmp_path, monkeypatch):
    """run's bound on the player reads the log's span over every frame the player plays, those after the last dynamics
    frame included: dynamics frames ending at 99.9 s and a last SliceLights frame at 250 s span 250 s."""
    rig = Rig(tmp_path, monkeypatch)
    a = rig.recording("20990101-drive-a", speeds(90_000))

    def decode(log_path: Path, dbc_path: Path, mapping: Dict[str, Any], transforms: Dict[str, Any]) -> Dict[str, Any]:
        frames = [(t, "SliceDynamics", {"LongVel": 5.0}) for t in range(0, 100_000, 100)] + [(250_000, "SliceLights", {"Hazard": 0})]
        return {"values": {p: [] for p in mapping}, "half_lsb": {}, "frames": frames}

    monkeypatch.setattr(stack.rc, "decode_recording", decode)
    c = fleet.check_car("A", a)
    assert c["span_ms"] == 250_000 and c["moves"], c


# --- run: the stand-in cars ---------------------------------------------------------------------------------------------

STANDIN = r'''
"""A stand-in for `stack.py replay` (tests/test_sdv_fleet.py): keeps the fleet's gate as the stack does and writes a
replay's result.json and witness log, nothing else. Its prepare is a sleep, then `up` (where stack.py's replay_once
starts its containers, the connector among them), then its ready. Each SIGINT is logged; the first one is a
KeyboardInterrupt, after which it says `interrupted` and ends (exit 130) half a second later."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

k = int(os.environ["SDV_STACK_INSTANCE"])
gate = Path(os.environ["SDV_STACK_FEED_GATE"])
name = sys.argv[sys.argv.index("--name") + 1]
test_dir = Path(os.environ["FLEET_TEST_DIR"])


def say(what):
    with open(test_dir / "events.log", "a", encoding="utf-8") as f:
        f.write("%s %d %d\n" % (what, k, time.time_ns()))


def on_sigint(_signum, _frame):
    say("sigint")
    raise KeyboardInterrupt


signal.signal(signal.SIGINT, on_sigint)
say("start")
names = ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE", "SDV_RECORDING", "SDV_RUNS", "SDV_DEVICE_DIR", "SDV_CONNECTOR_IMAGE", "SDV_STATE",
         "SDV_SPOOL_DIR", "SDV_STATUS_DIR", "SDV_DEVICE_DIR_A", "SDV_DEVICE_DIR_B", "SDV_DEVICE_DIR_C")
(test_dir / ("env-%d.json" % k)).write_text(json.dumps({"argv": sys.argv[1:], "env": {n: os.environ.get(n) for n in names}, "pid": os.getpid(),
                                                        "pgid": os.getpgid(0), "cwd": os.getcwd()}), encoding="utf-8")
mode = os.environ.get("FLEET_TEST_MODE_%d" % k, "ok")
if mode == "stubborn":                # a car that ignores SIGINT
    signal.signal(signal.SIGINT, signal.SIG_IGN)
try:
    print("car %d: prepared" % k, flush=True)
    if mode == "leaky":
        print("a stand-in that prints its device directory %s and its thing %s"
              % (os.environ["SDV_DEVICE_DIR"], os.environ["FLEET_TEST_THING_%d" % k]), flush=True)
        print("on stderr: %s" % os.environ["SDV_DEVICE_DIR"], file=sys.stderr, flush=True)
        print("its files: %s" % " ".join(sorted(os.listdir(os.environ["SDV_DEVICE_DIR"]))), flush=True)
        print("resolved: %s" % os.path.realpath(os.environ["SDV_DEVICE_DIR"]), flush=True)
    if os.environ.get("FLEET_TEST_PRINT_%d" % k):
        print("a stand-in that prints %s" % os.environ["FLEET_TEST_PRINT_%d" % k], flush=True)
    time.sleep(float(os.environ.get("FLEET_TEST_PREPARE_S_%d" % k, os.environ.get("FLEET_TEST_PREPARE_S", "0.4"))))
    if mode == "fail":
        say("fail")
        sys.exit(3)
    say("up")
    if mode != "silent":
        tmp = gate / (".ready-%d.tmp" % k)
        tmp.write_text(json.dumps({"instance": k, "ready_ms": time.time_ns() // 1000000}), encoding="utf-8")
        os.replace(str(tmp), str(gate / ("ready-%d" % k)))
        say("ready")
    if mode == "end-after-ready":     # a car that ends once it is ready, without waiting for go
        time.sleep(float(os.environ.get("FLEET_TEST_END_AFTER_S_%d" % k, "0.3")))
        say("end")
        sys.exit(4)
    waited = time.monotonic()
    while True:
        if (gate / "abort").exists():
            say("abort")
            sys.exit(1)
        if (gate / "go").exists():
            say("go")
            break
        if time.monotonic() - waited > (20 if mode == "silent" else float(os.environ.get("FLEET_TEST_GATE_WAIT_S", "30"))):
            say("gave-up")
            sys.exit(5)
        time.sleep(0.02)
    if mode == "no-result":           # a car that goes and ends cleanly without writing a result.json
        say("done")
        sys.exit(0)
    rd = Path(os.environ["SDV_RUNS"]) / ("%s-%s" % (time.strftime("%Y%m%d"), name)) / "vcan-1"
    rd.mkdir(parents=True)
    witness = json.dumps({"event": "value", "path": "Vehicle.Speed", "value": k, "car": name}) + "\n"
    if mode == "witness-only":        # a replay that wrote its witness log and no result.json, and failed
        (rd / "vss-witness.jsonl").write_text(witness, encoding="utf-8")
        say("done")
        sys.exit(1)
    ok = mode != "gate-false"
    result = {"feed": "vcan", "bridge_mode": "none", "values": {"ok": ok}, "witness_values": {"ok": True}, "app_values": {"ok": True},
              "decisions": {"ok": True}, "lights": {"mock_log": {"ok": True}}, "listeners": {"ok": True}, "listeners_feed": {"ok": True},
              "listeners_end": {"ok": True}, "c12b": ["C12b", True, "made up"], "vcan_capture": {"identical": True},
              "connector": {"ok": True, "exit": 0, "exit_means": "stopped", "events": {"start": 1, "stop": 1}}}
    (rd / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (rd / "vss-witness.jsonl").write_text(witness, encoding="utf-8")
    if mode == "leaky-file":          # a device item in a file of the run that is not the car's log, which nothing masks
        (rd / "notes.txt").write_text("a stand-in that keeps %s\n" % os.environ["FLEET_TEST_THING_%d" % k], encoding="utf-8")
    if mode == "linger":              # a car that does not end by itself within the test's bound
        say("linger")
        time.sleep(20)
    if mode == "stubborn":            # with a child of its own (as the stack's player is)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL)
        (test_dir / ("child-%d.pid" % k)).write_text(str(child.pid), encoding="ascii")
        say("stubborn")
        time.sleep(60)
    say("done")
    sys.exit(int(os.environ.get("FLEET_TEST_EXIT_%d" % k, "0")))
except KeyboardInterrupt:
    say("interrupted")
    time.sleep(0.5)                   # a second SIGINT in this time is logged too
    sys.exit(130)
'''


class Fleet:
    """A fleet run's surroundings: the rig's recordings, a device directory per car, the state and runs directories, the
    stand-in car, docker's container list and the host's listeners replaced."""

    def __init__(self, tmp_path: Path, monkeypatch: Any, n: int = 3, caller_state: bool = True) -> None:
        self.rig = Rig(tmp_path, monkeypatch)
        self.tmp, self.mp, self.n = tmp_path, monkeypatch, n
        self.labels = "ABC"[:n]
        self.recs = {L: self.rig.recording("20990101-drive-%s" % L.lower(), speeds(80_000 + 1000 * i)) for i, L in enumerate(self.labels)}
        self.test_dir = tmp_path / "standin-out"
        self.test_dir.mkdir()
        standin = tmp_path / "standin" / "stack.py"
        standin.parent.mkdir()
        standin.write_text(STANDIN, encoding="utf-8")
        monkeypatch.setattr(fleet, "STACK_PY", standin)
        monkeypatch.setattr(fleet, "PYTHON", sys.executable)
        self.state = tmp_path / "state"
        self.runs = tmp_path / "runs"
        monkeypatch.setattr(stack, "STATE", self.state)
        monkeypatch.setattr(stack, "RUNS", self.runs)
        for name in fleet.REFUSED_ENV + ("SDV_DEVICE_DIR_A", "SDV_DEVICE_DIR_B", "SDV_DEVICE_DIR_C", "SDV_STATE", "SDV_HOST_ROLE", "SDV_TWIN_RULE"):
            monkeypatch.delenv(name, raising=False)
        if caller_state:
            monkeypatch.setenv("SDV_STATE", str(self.state))
        monkeypatch.setenv("SDV_CONNECTOR_IMAGE", IMAGE)
        monkeypatch.setenv("FLEET_TEST_DIR", str(self.test_dir))
        monkeypatch.setenv("FLEET_TEST_PREPARE_S", "0.4")
        self.devices: Dict[str, Path] = {}
        for i, L in enumerate(self.labels):
            d = tmp_path / ("device-%s" % L.lower())
            d.mkdir()
            for f in ("device.key", "device.crt", "ca.pem"):
                (d / f).write_text("made up\n", encoding="ascii")
            (d / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE=example_rule\n" % (ENDPOINT, THINGS[L]),
                                             encoding="ascii")
            monkeypatch.setenv("SDV_DEVICE_DIR_%s" % L, str(d))
            monkeypatch.setenv("FLEET_TEST_THING_%d" % (i + 1), THINGS[L])
            self.devices[L] = d
        self.containers = ""
        self.instance_containers: Dict[str, str] = {}          # `ps -aq --filter label=sdv.stack.instance=<k>`: its ids
        self.docker_calls: List[List[str]] = []
        self.image_labels = {"sdv.twin.allowlist_version": str(stack.attr.ALLOWLIST_VERSION), "sdv.twin.allowlist_digest": "0x12345678",
                             "sdv.twin.catalogue_sha256": stack.sha256_file(self.rig.gen / "vss-ids.vspec")}
        self.image_user = "1000:1000"
        self.image_in_store = True
        self.sockets: List[Dict[str, str]] = []
        monkeypatch.setattr(stack, "docker", self.docker)
        monkeypatch.setattr(stack, "host_listeners", lambda: {"with_owners": True, "sockets": list(self.sockets)})

    def docker(self, *a: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        """stack.docker replaced: the connector image's inspect, the stack's container list (`label=sdv.stack.run`), an
        instance's (`label=sdv.stack.instance=<k>`), and every other call answered empty; every call kept."""
        args = list(a)
        self.docker_calls.append(args)
        if args[:2] == ["image", "inspect"]:
            if not self.image_in_store:
                if check:
                    raise stack.StackError("docker image inspect failed (1): Error response from daemon: No such image: %s" % args[-1])
                return subprocess.CompletedProcess(args, 1, "", "No such image: %s" % args[-1])
            info = {"Id": args[-1], "RepoTags": ["sdv-twin-connector:made-up"],
                    "Config": {"Labels": dict(self.image_labels), "User": self.image_user}}
            return subprocess.CompletedProcess(args, 0, json.dumps([info]), "")
        if args[:2] == ["ps", "-aq"]:
            flt = args[args.index("--filter") + 1]
            out = self.containers if flt == "label=sdv.stack.run" else self.instance_containers.get(flt, "")
            return subprocess.CompletedProcess(args, 0, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def argv(self, name: str = "v3-fleet") -> List[str]:
        out = ["run", "--name", name]
        for L in self.labels:
            out += ["--car", "%s=%s" % (L, self.recs[L])]
        return out

    def run_dir(self, name: str = "v3-fleet") -> Path:
        return self.runs / ("%s-%s" % (datetime.datetime.now().strftime("%Y%m%d"), name))

    def events(self) -> List[Any]:
        p = self.test_dir / "events.log"
        if not p.exists():
            return []
        return [(w, int(k), int(t)) for w, k, t in (ln.split() for ln in p.read_text(encoding="utf-8").splitlines())]

    def at(self, what: str, k: int) -> int:
        (t,) = [t for w, kk, t in self.events() if (w, kk) == (what, k)]
        return t

    def env(self, k: int) -> Dict[str, Any]:
        return json.loads((self.test_dir / ("env-%d.json" % k)).read_text(encoding="utf-8"))

    def stamp(self, where: Path, age_s: float) -> None:
        where.mkdir(parents=True, exist_ok=True)
        (where / "started.json").write_text(json.dumps({"started_ms": int(time.time() * 1000 - age_s * 1000)}, separators=(",", ":")),
                                            encoding="ascii")

    def forbidden(self) -> List[str]:
        words = [str(d) for d in self.devices.values()] + [d.name for d in self.devices.values()]
        words += ["connector.env", "device.key", "device.crt", "ca.pem", ENDPOINT, "example_rule"] + list(THINGS.values())
        return words


def assert_nothing_made(f: Fleet, name: str = "v3-fleet") -> None:
    assert not f.run_dir(name).exists() and not (f.state / "fleet").exists()
    assert f.events() == [], "a car was started"


def assert_names_no_value(f: Fleet, text: str) -> None:
    for word in [str(d) for d in f.devices.values()] + list(THINGS.values()) + [ENDPOINT, IMAGE]:
        assert word not in text, word


@POSIX
def test_run_starts_each_car_once_the_one_before_is_ready_and_writes_go_only_after_every_car_is_ready(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch)
    r = run_main(f.argv(), capsys)
    assert r.code == 0, r
    for k in (1, 2):
        assert f.at("ready", k) < f.at("start", k + 1), "car %d started before ready-%d" % (k + 1, k)
    assert min(f.at("go", k) for k in (1, 2, 3)) > max(f.at("ready", k) for k in (1, 2, 3)), "go before every car was ready"
    assert r.lines == ["A gates: %s" % json.dumps({"values": True, "decisions": True, "lights": True, "listeners": True, "c12b": True,
                                                   "bus_frames_identical": True, "connector": True}, sort_keys=True),
                       "B gates: " + r.lines[0].split(": ", 1)[1], "C gates: " + r.lines[0].split(": ", 1)[1], "fleet: ok"], r
    assert sorted(p.name for p in (f.run_dir() / "gate").iterdir()) == ["go", "ready-1", "ready-2", "ready-3"]


@POSIX
def test_each_car_runs_the_stacks_replay_with_its_own_instance_gate_recording_runs_and_device_and_none_of_the_refused_variables(
        tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch)
    r = run_main(f.argv(), capsys)
    assert r.code == 0, r
    run = f.run_dir()
    for k, L in enumerate("ABC", 1):
        seen = f.env(k)
        assert seen["argv"] == ["replay", "--name", "v3-fleet-%s" % L, "--feed", "vcan", "--bridge", "none", "--connector"]
        e = seen["env"]
        got = [e[n] for n in ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE", "SDV_RECORDING", "SDV_RUNS", "SDV_DEVICE_DIR", "SDV_CONNECTOR_IMAGE")]
        assert got == [str(k), str(run / "gate"), str(f.recs[L]), str(run / ("car-%s" % L)), str(f.devices[L]), IMAGE]
        assert all(e[n] is None for n in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR", "SDV_DEVICE_DIR_A", "SDV_DEVICE_DIR_B", "SDV_DEVICE_DIR_C")), e
        log = (run / ("car-%s" % L) / "stack.log").read_text(encoding="utf-8")
        assert "car %d: prepared" % k in log


@POSIX
@pytest.mark.parametrize("caller_state", [True, False])
def test_car_a_keeps_the_callers_state_directory_b_and_c_their_own_and_the_fleet_has_a_stamp(tmp_path, monkeypatch, capsys, caller_state):
    f = Fleet(tmp_path, monkeypatch, caller_state=caller_state)
    r = run_main(f.argv(), capsys)
    assert r.code == 0, r
    assert f.env(1)["env"]["SDV_STATE"] == (str(f.state) if caller_state else None), "car A's state directory is the caller's"
    for k, L in ((2, "B"), (3, "C")):
        assert f.env(k)["env"]["SDV_STATE"] == str(f.state / "fleet" / ("car-%s" % L))
    stamp = json.loads((f.state / "fleet" / "started.json").read_text(encoding="ascii"))
    assert set(stamp) == {"started_ms"} and abs(stamp["started_ms"] - time.time() * 1000) < 60_000
    # the fleet stamp is read: a second fleet inside the start spacing is refused before anything is made
    r = run_main(f.argv("v3-fleet-again"), capsys)
    assert r.code == 2 and "fleet" in r.err and not f.run_dir("v3-fleet-again").exists(), r


@POSIX
def test_a_car_that_ends_before_it_is_ready_aborts_the_fleet_and_the_next_car_is_never_started(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "fail")
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    assert ("abort", 1) in [(w, k) for w, k, _t in f.events()] and not [e for e in f.events() if e[1] == 3], f.events()
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["gate"]["go_ms"] is None and isinstance(rec["gate"]["abort"], str) and "B" in rec["gate"]["abort"]
    assert (f.run_dir() / "gate" / "abort").exists() and not (f.run_dir() / "gate" / "go").exists()
    c = {x["label"]: x for x in rec["cars"]}
    assert c["B"]["stack_exit"] == 3 and c["B"]["ready_ms"] is None and c["A"]["stack_exit"] == 1 and isinstance(c["A"]["ready_ms"], int)
    assert {k: c["C"][k] for k in ("result", "witness", "stack_exit", "ready_ms", "gates", "connector")} == dict.fromkeys(
        ("result", "witness", "stack_exit", "ready_ms", "gates", "connector"))
    assert rec["ok"] is False


@POSIX
def test_a_car_that_gives_no_ready_within_the_wait_aborts_the_fleet(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "silent")
    monkeypatch.setattr(fleet, "GATE_WAIT_S", 1.5)
    t0 = time.monotonic()
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok" and time.monotonic() - t0 < 30, r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["gate"]["go_ms"] is None and "car B" in rec["gate"]["abort"] and "no ready" in rec["gate"]["abort"], rec["gate"]
    b = [w for w, k, _t in f.events() if k == 2]          # car B ends at the abort or at the fleet's SIGINT, whichever it meets first
    assert b[:2] == ["start", "up"] and b[-1] in ("abort", "interrupted") and "ready" not in b, b
    assert [w for w, k, _t in f.events() if k == 1][-1] == "abort"
    assert time.monotonic() - t0 < 15, "the fleet waited past its bound for car B's ready"


@POSIX
def test_a_device_item_in_any_file_under_the_run_makes_the_fleet_not_ok(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "leaky-file")
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok" and "notes.txt" in r.err, r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["ok"] is False and all(c["stack_exit"] == 0 and all(c["gates"].values()) for c in rec["cars"])
    assert THINGS["B"] not in r.out + r.err


@POSIX
def test_a_car_that_ends_clean_with_no_result_json_makes_the_fleet_not_ok(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "no-result")
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    b = rec["cars"][1]
    assert b["stack_exit"] == 0 and b["gates"] is None and b["result"] is None and rec["ok"] is False, b


@POSIX
def test_a_cars_witness_is_named_in_the_record_though_its_replay_left_no_result_json(tmp_path, monkeypatch, capsys):
    """A car's witness is its replay's vss-witness.jsonl whenever there is one (null only when there is none): car B's
    replay wrote its witness log and no result.json and exited 1, so its result and gates are null and its witness is
    named."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "witness-only")
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    b = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))["cars"][1]
    assert (b["label"], b["stack_exit"], b["result"], b["gates"]) == ("B", 1, None, None), b
    assert re.fullmatch(r"car-B/\d{8}-v3-fleet-B/vcan-1/vss-witness\.jsonl", b["witness"] or ""), b
    assert (f.run_dir() / b["witness"]).is_file()


@POSIX
def test_a_car_past_its_bound_is_interrupted_and_the_fleet_is_not_ok(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_1", "linger")
    monkeypatch.setattr(fleet, "CAR_TIMEOUT_S", 3.0)
    monkeypatch.setattr(fleet, "STOP_GRACE_S", 60.0)
    t0 = time.monotonic()
    r = run_main(f.argv(), capsys)
    assert time.monotonic() - t0 < 15 and r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["cars"][0]["stack_exit"] not in (0, None) and rec["cars"][1]["stack_exit"] == 0
    assert "done" not in [w for w, k, _t in f.events() if k == 1], "car A ran to its end"


@POSIX
@pytest.mark.parametrize("how", ["a gate", "an exit"])
def test_a_car_whose_gate_is_false_or_whose_stack_exits_non_zero_makes_the_fleet_not_ok(tmp_path, monkeypatch, capsys, how):
    f = Fleet(tmp_path, monkeypatch, n=2)
    if how == "a gate":
        monkeypatch.setenv("FLEET_TEST_MODE_2", "gate-false")
    else:
        monkeypatch.setenv("FLEET_TEST_EXIT_2", "1")
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert isinstance(rec["gate"]["go_ms"], int) and rec["gate"]["abort"] is None and rec["ok"] is False
    b = rec["cars"][1]
    assert (b["gates"]["values"] is False) if how == "a gate" else (b["stack_exit"] == 1)


@POSIX
def test_fleet_json_word_for_word_with_relative_paths_each_cars_own_and_no_device_item_anywhere_under_the_run(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "leaky")          # prints its device directory and its thing: the log is masked
    r = run_main(f.argv(), capsys)
    assert r.code == 0, r
    run = f.run_dir()
    rec = json.loads((run / "fleet.json").read_text(encoding="utf-8"))
    assert set(rec) == {"v", "fleet", "utc_start", "utc_end", "cars", "gate", "window", "ok"}
    assert (rec["v"], rec["fleet"], rec["ok"]) == (1, "v3-fleet", True)
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec[k]) for k in ("utc_start", "utc_end"))
    assert set(rec["gate"]) == {"go_ms", "abort"} and isinstance(rec["gate"]["go_ms"], int) and rec["gate"]["abort"] is None
    w = rec["window"]
    assert set(w) == {"day", "from_ms", "to_ms", "day_at_stop"} and re.fullmatch(r"\d{4}-\d\d-\d\d", w["day"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", w["day_at_stop"]) and w["from_ms"] <= rec["gate"]["go_ms"] <= w["to_ms"]
    assert w["to_ms"] * 1_000_000 >= max(f.at("done", k) for k in (1, 2, 3)), "the window ends after the last car's exit"
    assert w["from_ms"] * 1_000_000 <= min(f.at("start", k) for k in (1, 2, 3)), "the window starts at the fleet's start, before any car's"
    t0, t1 = (datetime.datetime.strptime(rec[k], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
              for k in ("utc_start", "utc_end"))
    assert t0 <= w["from_ms"] / 1000 < t0 + 1 and t1 <= w["to_ms"] / 1000 < t1 + 1, "utc_start goes with from_ms, utc_end with to_ms"
    assert [c["label"] for c in rec["cars"]] == ["A", "B", "C"] and [c["instance"] for c in rec["cars"]] == [1, 2, 3]
    for c in rec["cars"]:
        L = c["label"]
        assert set(c) == {"label", "instance", "recording", "run", "result", "witness", "stack_exit", "ready_ms", "gates", "connector"}
        line = json.loads((f.recs[L] / "manifest-line.json").read_text(encoding="utf-8"))
        assert c["recording"] == {"name": f.recs[L].name, "sha256": line["recording"]["sha256"], "run_type": "sigsim"}
        assert c["run"] == "car-%s" % L and (run / c["run"]).is_dir()
        for key in ("result", "witness"):
            assert not Path(c[key]).is_absolute() and c[key].startswith("car-%s/" % L), (L, key, c[key])
        assert re.fullmatch(r"car-%s/\d{8}-v3-fleet-%s/vcan-1/result\.json" % (L, L), c["result"])
        assert re.fullmatch(r"car-%s/\d{8}-v3-fleet-%s/vcan-1/vss-witness\.jsonl" % (L, L), c["witness"])
        assert json.loads((run / c["witness"]).read_text(encoding="utf-8"))["car"] == "v3-fleet-%s" % L, "the witness is this car's"
        assert (c["stack_exit"], c["connector"]) == (0, {"ok": True, "exit": 0, "exit_means": "stopped"})
        assert isinstance(c["ready_ms"], int) and all(c["gates"].values())
    scanned = 0
    for p in sorted(run.rglob("*")):
        if p.is_file():
            text = p.read_bytes().decode("utf-8", "replace")
            scanned += 1
            for word in f.forbidden():
                assert word not in text, (str(p.relative_to(run)), word)
    assert scanned >= 11
    log_b = (run / "car-B" / "stack.log").read_text(encoding="utf-8")
    assert "<device>" in log_b, "the leaky car's log was masked"
    assert "on stderr: <device>" in log_b, "a car's stderr is in its stack.log, masked"
    assert "its files: " + " ".join(["<device file>"] * 4) in log_b, "the device directory's file names are masked"
    assert str(f.devices["B"]) not in r.err, "a car's stderr is not on the fleet's own"


@POSIX
def test_the_windows_day_and_day_at_stop_are_the_utc_day_whatever_the_local_zone(tmp_path, monkeypatch, capsys):
    """window.day and window.day_at_stop are UTC days, as window.txt's are and as P3's partition query reads them: the
    process's zone is put to one whose date differs from UTC's now (a POSIX zone string, read without a zone database),
    and restored after."""
    zone = "AAA-14" if datetime.datetime.now(datetime.timezone.utc).hour >= 10 else "AAA+11"      # UTC+14, or UTC-11
    old = os.environ.get("TZ")
    monkeypatch.setenv("TZ", zone)
    time.tzset()
    try:
        f = Fleet(tmp_path, monkeypatch, n=2)
        utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        assert datetime.datetime.now().strftime("%Y-%m-%d") != utc, "the zone does not separate the local day from UTC's now"
        r = run_main(f.argv(), capsys)
        assert r.code == 0, r
        w = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))["window"]
        assert w["day"] == w["day_at_stop"] == utc, (w, utc)
    finally:
        if old is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", old)
        time.tzset()


# --- run: the refusals ---------------------------------------------------------------------------------------------------

def refused(f: Fleet, capsys: Any, argv: Optional[List[str]] = None, name: str = "v3-fleet") -> types.SimpleNamespace:
    r = run_main(argv or f.argv(name), capsys)
    assert r.code == 2 and r.out == "", r
    assert_nothing_made(f, name)
    assert_names_no_value(f, r.err)
    return r


@POSIX
def test_run_refuses_a_car_check_would_not_pass(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    f.recs["B"] = f.rig.recording("20990101-parked", speeds(0, v=0.0))
    r = refused(f, capsys)
    assert "car B" in r.err
    f.recs["B"] = f.rig.twin(f.recs["A"], "20990101-copy-of-a")
    r = refused(f, capsys)
    assert "car B" in r.err or "car A" in r.err


@POSIX
@pytest.mark.parametrize("value", [None, ""])
def test_run_refuses_no_connector_image(tmp_path, monkeypatch, capsys, value):
    f = Fleet(tmp_path, monkeypatch, n=2)
    if value is None:
        monkeypatch.delenv("SDV_CONNECTOR_IMAGE")
    else:
        monkeypatch.setenv("SDV_CONNECTOR_IMAGE", value)
    assert "SDV_CONNECTOR_IMAGE" in refused(f, capsys).err


@POSIX
@pytest.mark.parametrize("label", ["A", "B", "C"])
@pytest.mark.parametrize("problem", ["unset", "empty", "relative", "a file", "inside the repo", "no connector.env", "SDV_TWIN_DATABROKER",
                                     "SDV_TWIN_DATABROKER passed through", "no thing"])
def test_run_refuses_each_device_directory_rule_naming_the_cars_variable(tmp_path, monkeypatch, capsys, label, problem):
    f = Fleet(tmp_path, monkeypatch, n=3 if label == "C" else 2)
    dev = f.devices[label]
    if problem == "unset":
        monkeypatch.delenv("SDV_DEVICE_DIR_%s" % label)
    elif problem == "empty":
        monkeypatch.setenv("SDV_DEVICE_DIR_%s" % label, "")
    elif problem == "relative":
        monkeypatch.setenv("SDV_DEVICE_DIR_%s" % label, "device-b")
    elif problem == "a file":
        monkeypatch.setenv("SDV_DEVICE_DIR_%s" % label, str(dev / "ca.pem"))
    elif problem == "inside the repo":
        monkeypatch.setenv("SDV_DEVICE_DIR_%s" % label, str(STACK_DIR))
    elif problem == "no connector.env":
        (dev / "connector.env").unlink()
    elif problem == "SDV_TWIN_DATABROKER":
        with open(dev / "connector.env", "a", encoding="ascii") as fh:
            fh.write("SDV_TWIN_DATABROKER=127.0.0.1:55555\n")
    elif problem == "SDV_TWIN_DATABROKER passed through":
        with open(dev / "connector.env", "a", encoding="ascii") as fh:
            fh.write("  SDV_TWIN_DATABROKER\n")
    else:
        (dev / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\n# SDV_TWIN_THING=%s\n" % (ENDPOINT, THINGS[label]), encoding="ascii")
    r = refused(f, capsys)
    assert "SDV_DEVICE_DIR_%s" % label in r.err and "car %s" % label in r.err, r.err


@POSIX
def test_run_refuses_two_cars_with_one_device_directory_or_one_thing_and_never_prints_the_thing(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setenv("SDV_DEVICE_DIR_C", str(f.devices["A"]))
    r = refused(f, capsys)
    assert "car A" in r.err and "car C" in r.err and "device directory" in r.err and "SDV_DEVICE_DIR_C" in r.err, r.err
    monkeypatch.setenv("SDV_DEVICE_DIR_C", str(f.devices["C"]))
    (f.devices["C"] / "connector.env").write_text("SDV_TWIN_THING=%s\nSDV_TWIN_ENDPOINT=%s\n" % (THINGS["B"], ENDPOINT), encoding="ascii")
    r = refused(f, capsys)
    assert "car B" in r.err and "car C" in r.err and "SDV_TWIN_THING" in r.err


@POSIX
@pytest.mark.parametrize("holder, first, last, code", [("B", "A", "B", 0), ("B", "B", "A", 2), ("A", "B", "A", 0), ("A", "A", "B", 2)])
def test_a_thing_given_twice_in_a_connector_env_is_its_last_line_as_docker_reads_it(tmp_path, monkeypatch, capsys, holder, first, last, code):
    """docker's --env-file rule, which env_file keeps: of two lines naming one variable the last wins. One car's
    connector.env (car B's, or car A's) names SDV_TWIN_THING twice: the other car's thing, then its own, and the fleet
    runs (exit 0); the other way round, it is refused as one thing for two cars (exit 2). Neither value is on stderr."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    (f.devices[holder] / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE=example_rule\n"
                                                  % (ENDPOINT, THINGS[first], THINGS[last]), encoding="ascii")
    r = refused(f, capsys) if code == 2 else run_main(f.argv(), capsys)
    assert r.code == code, r
    if code == 2:
        assert "car A" in r.err and "car B" in r.err and "SDV_TWIN_THING" in r.err, r.err
    assert THINGS["A"] not in r.err and THINGS["B"] not in r.err, r.err


def test_env_files_last_line_wins_a_name_alone_included(tmp_path):
    """env_file's last-line rule when the last line names the variable alone (docker passes the caller's value through:
    None): the earlier NAME=value line does not stand."""
    p = tmp_path / "connector.env"
    p.write_text("SDV_TWIN_THING=%s\nSDV_TWIN_THING\n" % THINGS["A"], encoding="ascii")
    assert fleet.env_file(p) == {"SDV_TWIN_THING": None}


def test_env_files_last_line_wins_a_value_after_a_name_alone(tmp_path):
    """The other order: a NAME=value line after the name alone stands, as docker reads it."""
    p = tmp_path / "connector.env"
    p.write_text("SDV_TWIN_THING\nSDV_TWIN_THING=%s\n" % THINGS["A"], encoding="ascii")
    assert fleet.env_file(p) == {"SDV_TWIN_THING": THINGS["A"]}


@POSIX
@pytest.mark.parametrize("variable", ["SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE", "SDV_DEVICE_DIR", "SDV_SPOOL_DIR", "SDV_STATUS_DIR"])
@pytest.mark.parametrize("value", ["", "1"])
def test_run_refuses_each_of_the_five_variables_in_its_own_environment(tmp_path, monkeypatch, capsys, variable, value):
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv(variable, value if value else "")
    r = refused(f, capsys)
    assert variable in r.err


@POSIX
def test_run_refuses_while_any_container_carries_the_stacks_label(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    f.containers = "0123456789ab\n"
    r = refused(f, capsys)
    assert "sdv.stack.run" in r.err and ["ps", "-aq", "--filter", "label=sdv.stack.run"] in f.docker_calls


@POSIX
@pytest.mark.parametrize("port, car", [(55561, "A"), (55562, "B"), (55563, "C"), (50061, "A"), (50062, "B"), (50063, "C")])
def test_run_refuses_an_instances_databroker_or_mock_port_already_listened_on(tmp_path, monkeypatch, capsys, port, car):
    f = Fleet(tmp_path, monkeypatch)
    f.sockets = [{"proto": "tcp", "local": "127.0.0.1:%d" % port, "process": 'users:(("x",pid=1,fd=3))'}]
    r = refused(f, capsys)
    assert "car %s" % car in r.err and str(port) in r.err


@POSIX
def test_run_refuses_when_the_host_listeners_cannot_be_read(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)

    def fail() -> Any:
        raise stack.StackError("made up: ss failed")

    monkeypatch.setattr(stack, "host_listeners", fail)
    r = refused(f, capsys)
    assert "listeners" in r.err


@POSIX
def test_run_takes_ports_of_the_cars_it_runs_only(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    f.sockets = [{"proto": "tcp", "local": "127.0.0.1:55563", "process": ""}, {"proto": "tcp", "local": "127.0.0.1:55555", "process": ""},
                 {"proto": "udp", "local": "127.0.0.1:50062", "process": ""}]
    assert run_main(f.argv(), capsys).code == 0


@POSIX
@pytest.mark.parametrize("which", ["fleet", "A", "B", "C"])
@pytest.mark.parametrize("age_s, ok", [(10.0, False), (119.0, False), (-30.0, False), (121.0, True)])
def test_run_refuses_the_fleet_stamp_or_any_cars_identity_stamp_inside_the_start_spacing(tmp_path, monkeypatch, capsys, which, age_s, ok):
    f = Fleet(tmp_path, monkeypatch)
    where = {"fleet": f.state / "fleet", "A": f.state / "twin", "B": f.state / "fleet" / "car-B" / "twin",
             "C": f.state / "fleet" / "car-C" / "twin"}[which]
    f.stamp(where, age_s)
    if ok:
        assert run_main(f.argv(), capsys).code == 0
        return
    stamp = (where / "started.json").read_bytes()
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and not f.run_dir().exists() and f.events() == [], r
    assert (which == "fleet" and "fleet" in r.err) or "car %s" % which in r.err, r.err
    assert ("future" in r.err) == (age_s < 0) and ("spacing" in r.err) == (age_s >= 0), r.err
    if which == "fleet" and age_s < 0:          # startstamp.mark's own rule: refused once and written anew, so the refusals end
        assert (where / "started.json").read_bytes() != stamp, "the fleet's stamp from the future was not written anew"
    else:
        assert (where / "started.json").read_bytes() == stamp, "a refused start left the stamp as it was"


@POSIX
def test_run_refuses_a_stamp_that_is_no_stamp(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    (f.state / "fleet" / "car-B" / "twin").mkdir(parents=True)
    (f.state / "fleet" / "car-B" / "twin" / "started.json").write_text("not a stamp", encoding="ascii")
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and "car B" in r.err and not f.run_dir().exists(), r


@POSIX
def test_run_refuses_a_run_directory_that_exists_or_lies_inside_the_repo_and_a_name_that_is_no_name(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    f.run_dir().mkdir(parents=True)
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and "exists" in r.err and f.events() == [] and not (f.state / "fleet").exists(), r
    shutil.rmtree(f.runs)
    monkeypatch.setattr(stack, "RUNS", REPO / "sdv-out" / "no-runs-here")
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and "repo" in r.err and not (REPO / "sdv-out" / "no-runs-here").exists(), r
    monkeypatch.setattr(stack, "RUNS", f.runs)
    for bad in ("a/b", "", ".x", "..", "x y", "_x"):
        r = run_main(f.argv(bad), capsys)
        assert r.code == 2 and f.events() == [] and not f.runs.exists(), (bad, r)


@POSIX
def test_run_refuses_a_state_directory_inside_the_repo_naming_sdv_state(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    inside = REPO / "sdv-out" / "no-state-here"
    monkeypatch.setattr(stack, "STATE", inside)
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and r.out == "" and "SDV_STATE" in r.err and "repo" in r.err, r
    assert f.events() == [] and not f.run_dir().exists() and not inside.exists(), "something was made or started"


@POSIX
def test_run_refuses_when_docker_cannot_list_the_containers(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    real = f.docker

    def failing(*a: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        if list(a)[:2] == ["ps", "-aq"]:
            return subprocess.CompletedProcess(list(a), 1, "", "Cannot connect to the Docker daemon")
        return real(*a, check=check, timeout=timeout)

    monkeypatch.setattr(stack, "docker", failing)
    r = refused(f, capsys)
    assert "docker" in r.err, r.err


@POSIX
def test_a_relative_car_directory_reaches_the_car_as_an_absolute_recording_though_the_fleet_runs_elsewhere(tmp_path, monkeypatch, capsys):
    """The car's process runs with the repo as its working directory (the stand-in records its own: the repo's, though the
    fleet runs elsewhere), so a recording directory given relative to the fleet's own must be made absolute where the
    command line is read."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    argv = ["run", "--name", "v3-fleet"]
    for L in f.labels:
        argv += ["--car", "%s=%s" % (L, os.path.relpath(str(f.recs[L]), str(elsewhere)))]
    r = run_main(argv, capsys)
    assert r.code == 0, r
    for k, L in enumerate(f.labels, 1):
        got = f.env(k)["env"]["SDV_RECORDING"]
        assert os.path.isabs(got) and os.path.realpath(got) == os.path.realpath(str(f.recs[L])), (L, got)
        assert f.env(k)["cwd"] == str(stack.REPO), (L, f.env(k)["cwd"])


@POSIX
def test_a_device_directory_given_through_a_symlink_has_its_resolved_path_masked_too(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    link = tmp_path / "link-to-device-b"
    link.symlink_to(f.devices["B"])
    monkeypatch.setenv("SDV_DEVICE_DIR_B", str(link))
    monkeypatch.setenv("FLEET_TEST_MODE_2", "leaky")          # prints the directory as given and as the OS resolves it
    r = run_main(f.argv(), capsys)
    assert r.code == 0 and r.lines[-1] == "fleet: ok", r
    log = (f.run_dir() / "car-B" / "stack.log").read_text(encoding="utf-8")
    assert "resolved: <device>" in log and str(f.devices["B"].resolve()) not in log, log


@POSIX
def test_a_relative_runs_or_state_directory_reaches_every_car_absolute(tmp_path, monkeypatch, capsys):
    """SDV_RUNS and SDV_STATE relative: the cars run with the repo as their working directory, so the gate, each car's runs
    directory and the state directories of cars B and C are made absolute by the fleet, not refused by each stack."""
    f = Fleet(tmp_path, monkeypatch, caller_state=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stack, "RUNS", Path("runs-rel"))
    monkeypatch.setattr(stack, "STATE", Path("state-rel"))
    r = run_main(f.argv(), capsys)
    assert r.code == 0, r
    for k in (1, 2, 3):
        e = f.env(k)["env"]
        paths = [e["SDV_STACK_FEED_GATE"], e["SDV_RUNS"]] + ([e["SDV_STATE"]] if k > 1 else [])
        assert all(os.path.isabs(p) and p.startswith(str(tmp_path)) for p in paths), (k, paths)
    assert (tmp_path / "runs-rel").is_dir() and not (REPO / "runs-rel").exists()


@POSIX
def test_a_relative_state_directory_with_a_car_stamp_that_is_no_stamp_is_refused_with_exit_2(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2, caller_state=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stack, "STATE", Path("state-rel"))
    stamp_dir = tmp_path / "state-rel" / "fleet" / "car-B" / "twin"
    stamp_dir.mkdir(parents=True)
    (stamp_dir / "started.json").write_text("not a stamp", encoding="ascii")
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and r.out == "" and "fleet/car-B/twin/started.json under SDV_STATE" in r.err, r


@POSIX
def test_car_as_state_directory_is_the_callers_made_absolute(tmp_path, monkeypatch, capsys):
    """Car A's SDV_STATE is the caller's, but the car runs with the repo as its working directory, so a relative one is made
    absolute by the fleet, as B's and C's are."""
    f = Fleet(tmp_path, monkeypatch, n=2, caller_state=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stack, "STATE", Path("state-rel"))
    monkeypatch.setenv("SDV_STATE", "state-rel")
    assert run_main(f.argv(), capsys).code == 0
    a = f.env(1)["env"]["SDV_STATE"]
    assert a == str(tmp_path / "state-rel") and os.path.isabs(a), a


@POSIX
def test_car_as_state_directory_stays_unset_when_the_caller_has_none(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2, caller_state=False)
    assert run_main(f.argv(), capsys).code == 0
    assert f.env(1)["env"]["SDV_STATE"] is None


def test_the_opt_in_broker_test_is_no_twin_test_file():
    """tests/test_sdv_fleet_broker.py skips without SDV_FLEET_BROKER=1: in TWIN_TEST_FILES it would fail every CI run."""
    import twin_gate
    assert "tests/test_sdv_fleet_broker.py" not in twin_gate.TWIN_TEST_FILES and (HERE / "test_sdv_fleet_broker.py").is_file()


def test_the_broker_tests_default_recordings_are_video_3s_three_drives_and_its_docstring_names_the_same():
    """The opt-in test's default recordings are video 3's three drives, car C 20261111-carla010-6d1 (package MM), and its
    RECORDINGS paragraph names the same three. That test does not run here, so its DEFAULTS and its docstring are read."""
    import test_sdv_fleet_broker as FB
    want = {"A": "20261112-carla010-7d1b", "B": "20261111-carla010-2d1", "C": "20261111-carla010-6d1"}
    assert FB.DEFAULTS == {L: "~/sdv-recordings/%s" % name for L, name in want.items()}, FB.DEFAULTS
    doc = re.sub(r"\s+", " ", FB.__doc__ or "")
    assert "encodes them from their takes: %s (R-att's), %s and %s." % (want["A"], want["B"], want["C"]) in doc, "its RECORDINGS paragraph"


def test_the_broker_tests_guard_reads_each_recordings_own_bound_from_the_stack_and_its_logs_own_span(tmp_path, monkeypatch):
    """The opt-in test refuses, before its run, a recording whose bound on its player the stack refuses, or whose log ends
    less than fleet.py's PLAYER_MARGIN_S inside that bound, or past it: the bound is fleet.py's player_bound_s of that
    recording (stack.py's player_bound_s for its log, the one place it is computed), and a log's span is its own first and
    last times."""
    import test_sdv_fleet_broker as FB
    import test_sdv_stack_playerbound as PB
    assert FB.fleet is fleet and not hasattr(fleet, "PLAYER_CALL"), "no reading of a literal in stack.py's source is left"
    monkeypatch.setitem(sys.modules, "can", types.SimpleNamespace(LogReader=PB.CandumpReader))
    d = tmp_path / "20990101-carla010-9d9"
    d.mkdir()
    log = b"(1000.250000) vcan0 100#00\n(1001.000000) vcan0 100#00\n(1123.750000) vcan0 100#00\n"
    (d / "carla.log").write_bytes(log)
    sha = hashlib.sha256(log).hexdigest()
    (d / "carla.log.sha256").write_text("%s  carla.log\n" % sha, encoding="ascii")
    line = {"name": d.name, "recording": {"format": "candump-log", "path": "~/x/%s/carla.log" % d.name, "sha256": sha},
            "source": {"generator": "carla-autoware", "params": {}}}
    (d / "manifest-line.json").write_text(json.dumps(line), encoding="ascii")
    assert fleet.player_bound_s(d) == 154, "123.5 s and PLAYER_HEADROOM_S, rounded up"
    assert FB.log_span_s(d) == 123.5 and not FB.log_too_long(d, 154)
    assert FB.log_too_long(d, 133), "123.5 s is less than PLAYER_MARGIN_S inside a bound of 133 s"
    assert not FB.log_too_long(d, 134) and FB.log_too_long(d, None), "None: a bound the stack refuses"
    assert FB.log_too_long(d, 133.5), "a log ending exactly PLAYER_MARGIN_S inside its bound is too long"
    if stack.SIM_PY.is_file():          # the guard's own reading, by the sim venv's Python and its python-can, as fleet.py run's
        assert FB.stack_bound_s(d, stack.SIM_PY) == 154
        long = tmp_path / "20990101-carla010-9e9"
        shutil.copytree(d, long)
        text = log.decode("ascii") + "(%.6f) vcan0 100#00\n" % (1000.25 + stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S + 0.001)
        (long / "carla.log").write_text(text, encoding="ascii")
        sha2 = hashlib.sha256(text.encode("ascii")).hexdigest()
        (long / "carla.log.sha256").write_text("%s  carla.log\n" % sha2, encoding="ascii")
        (long / "manifest-line.json").write_text(json.dumps(dict(line, recording=dict(line["recording"], sha256=sha2))), encoding="ascii")
        assert FB.stack_bound_s(long, stack.SIM_PY) is None, "one millisecond past the ceiling's span: the stack refuses it"


def test_the_broker_tests_sweep_returns_what_the_fleet_left_and_a_container_left_fails_it(monkeypatch):
    """The opt-in test's cleanup removes every container labelled sdv.stack.instance and every vcanf<k> made during the
    run, and returns them; the test then holds the container list empty, once the fleet's exit is asserted, so a stack
    that leaves a container fails it (the interfaces are the test's to remove: the stack never removes its own)."""
    import test_sdv_fleet_broker as FB
    calls: List[List[str]] = []

    def docker(*a: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
        calls.append(["docker"] + list(a))
        return subprocess.CompletedProcess(list(a), 0, "c0ffee01\n" if list(a[:2]) == ["ps", "-aq"] else "", "")

    def sh(*a: str, check: bool = True, timeout: float = 120, **_kw: Any) -> subprocess.CompletedProcess:
        calls.append(list(a))
        links = "1: lo: <LOOPBACK,UP> mtu 65536\n7: vcanf2: <NOARP,UP,LOWER_UP> mtu 72\n9: vcanf3: <NOARP,UP,LOWER_UP> mtu 72\n"
        return subprocess.CompletedProcess(list(a), 0, links if list(a[:2]) == ["ip", "-o"] else "", "")

    monkeypatch.setattr(FB.CB, "docker", docker)
    monkeypatch.setattr(FB.CB, "sh", sh)
    found = FB.sweep(["vcanf3"])
    assert found == {"containers": ["c0ffee01"], "vcan": ["vcanf2"]}
    assert ["docker", "ps", "-aq", "--filter", "label=sdv.stack.instance"] in calls and ["docker", "rm", "-f", "c0ffee01"] in calls
    assert ["sudo", "-n", "ip", "link", "delete", "vcanf2"] in calls and ["sudo", "-n", "ip", "link", "delete", "vcanf3"] not in calls
    with pytest.raises(AssertionError):
        FB.assert_none_left(found)
    FB.assert_none_left({"containers": [], "vcan": ["vcanf2"]})


@pytest.mark.parametrize("links", [
    "1: lo: <LOOPBACK,UP> mtu 65536\n4: vcanf1: <NOARP,UP,LOWER_UP> mtu 72\n5: vcanf2: <NOARP> mtu 72\n6: vcanf3: <NOARP> mtu 72\n",
    "1: lo: <LOOPBACK,UP> mtu 65536\n4: vcanf1@NONE: <NOARP> mtu 72\n5: vcanf2@NONE: <NOARP> mtu 72\n6: vcanf3@NONE: <NOARP> mtu 72\n",
], ids=["plain", "at-form"])
def test_the_broker_tests_sweep_removes_every_vcanf_the_run_made_the_third_included(monkeypatch, links):
    """With no vcanf<k> there before the run and vcanf1, vcanf2 and vcanf3 after it, the sweep returns all three and
    deletes each with `sudo -n ip link delete`: every car's interface, car C's included. A link prints as `4: vcanf1: ...`
    or, with a peer, as `4: vcanf1@NONE: ...`; both forms are read."""
    import test_sdv_fleet_broker as FB
    calls: List[List[str]] = []

    def docker(*a: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
        calls.append(["docker"] + list(a))
        return subprocess.CompletedProcess(list(a), 0, "", "")

    def sh(*a: str, check: bool = True, timeout: float = 120, **_kw: Any) -> subprocess.CompletedProcess:
        calls.append(list(a))
        return subprocess.CompletedProcess(list(a), 0, links if list(a[:2]) == ["ip", "-o"] else "", "")

    monkeypatch.setattr(FB.CB, "docker", docker)
    monkeypatch.setattr(FB.CB, "sh", sh)
    assert FB.sweep([]) == {"containers": [], "vcan": ["vcanf1", "vcanf2", "vcanf3"]}
    assert [c for c in calls if c[:4] == ["sudo", "-n", "ip", "link"]] == [["sudo", "-n", "ip", "link", "delete", v]
                                                                           for v in ("vcanf1", "vcanf2", "vcanf3")]


def test_the_broker_test_holds_one_new_run_directory_before_it_unpacks_it_showing_the_fleets_output():
    """fleet.py run makes no run directory when it refuses (exit 2): the opt-in test asserts one new run directory, with the
    fleet's exit status, stdout and stderr as the message, before it unpacks it, so its failure says why. That test does not
    run here (it needs Docker and the broker), so its source is read."""
    import inspect
    import test_sdv_fleet_broker as FB
    src = inspect.getsource(FB.test_three_cars_at_the_local_broker_each_on_its_own_topic_with_its_own_witness_values_and_only_the_allowlist)
    lines = [ln.strip() for ln in src.splitlines()]
    new = 'new = sorted(set(runs.glob("*-%s" % NAME)) - before_runs)'
    held = "assert len(new) == 1, (proc.returncode, proc.stdout[-3000:], proc.stderr[-3000:])"
    assert [lines.count(x) for x in (new, held, "(run,) = new")] == [1, 1, 1], "the opt-in test's three lines, once each"
    assert lines.index(new) + 1 == lines.index(held) == lines.index("(run,) = new") - 1, "the three in that order, together"
    assert [ln for ln in lines if ln.startswith("(run,) =")] == ["(run,) = new"], "a run directory unpacked before its count is held"


@POSIX
def test_run_refuses_a_command_line_of_other_cars(tmp_path, monkeypatch, capsys):
    f = Fleet(tmp_path, monkeypatch, n=2)
    for argv in (["run", "--name", "x", "--car", "A=%s" % f.recs["A"]], ["run", "--car", "A=%s" % f.recs["A"], "--car", "B=%s" % f.recs["B"]],
                 ["run", "--name", "x", "--car", "B=%s" % f.recs["A"], "--car", "A=%s" % f.recs["B"]]):
        r = run_main(argv, capsys) if "--name" in argv else None
        if r is None:
            with pytest.raises(SystemExit) as e:
                fleet.main(argv)
            assert e.value.code == 2
            capsys.readouterr()
        else:
            assert r.code == 2 and r.out == "", r
    assert f.events() == [] and not f.runs.exists()


# --- run: the player's bound, the stack's own rules on the role and the image, the stamps that are none -----------------

@POSIX
def test_run_refuses_a_car_whose_bound_the_stack_refuses_or_whose_log_ends_less_than_the_margin_inside_it(tmp_path, monkeypatch, capsys):
    """Each car's bound on its player is the stack's for that car's own log (stack.py's player_bound_s: the log's span plus
    PLAYER_HEADROOM_S, rounded up, at most PLAYER_BOUND_MAX_S). A car whose bound the stack refuses (its log one
    millisecond past the ceiling's span), or whose log ends less than PLAYER_MARGIN_S inside its bound, or past it, is
    refused before anything is written, naming that car and never its recording; a log whose bound is the ceiling runs."""
    f = Fleet(tmp_path, monkeypatch)
    room_ms = (stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S) * 1000
    f.recs["C"] = f.rig.recording("20990101-long-c", speeds(80_000) + [[room_ms + 1, 0.0]])
    r = refused(f, capsys)
    assert "car C" in r.err and "bound on its player" in r.err and "20990101-long-c" not in r.err, r.err
    assert "car A" not in r.err and "car B" not in r.err, r.err
    with monkeypatch.context() as m:          # the docstring's order: a car's bound before the connector image
        m.delenv(stack.CONNECTOR_IMAGE_ENV)
        assert "car C" in refused(f, capsys).err
    with monkeypatch.context() as m:          # the docstring's order: a car check would not pass before a car's bound
        m.setitem(f.recs, "A", f.rig.recording("20990101-parked-a", speeds(1_000)))
        assert "car A would not pass check" in refused(f, capsys).err
    f.recs["C"] = f.rig.recording("20990101-at-c", speeds(80_000) + [[room_ms, 0.0]])
    assert stack.player_bound_s(f.recs["C"] / "sigsim.log") == stack.PLAYER_BOUND_MAX_S
    # While the headroom is the larger, no log the stack takes meets the margin refusal (fleet.py's DESIGN VALUES): it is
    # a guard against a later change of the headroom, so the stack's bound is replaced below to reach it.
    assert stack.PLAYER_HEADROOM_S > fleet.PLAYER_MARGIN_S
    real = stack.player_bound_s
    for past_margin_s, code in ((0, 2), (1, 0)):          # a bound the stack gave PLAYER_MARGIN_S past C's log's end, then a second more
        less = stack.PLAYER_HEADROOM_S - fleet.PLAYER_MARGIN_S - past_margin_s
        with monkeypatch.context() as m:
            m.setattr(stack, "player_bound_s", lambda log, less=less: real(log) - (less if Path(log).parent.name == "20990101-at-c" else 0))
            if code == 2:
                r = refused(f, capsys)
                assert "car C" in r.err and "bound on its player" in r.err and "%d s inside" % fleet.PLAYER_MARGIN_S in r.err, r.err
                assert "20990101-at-c" not in r.err and "car A" not in r.err and "car B" not in r.err, r.err
            else:
                assert run_main(f.argv("v3-fleet-margin"), capsys).code == 0
    f.stamp(f.state / "fleet", 121.0)          # the fleet's start spacing, as after a fleet two minutes ago
    assert run_main(f.argv(), capsys).code == 0, "a log whose bound is the ceiling runs"


@POSIX
@pytest.mark.parametrize("label", ["A", "B", "C"])
def test_run_refuses_any_car_whose_bound_the_stack_refuses_naming_that_car_only(tmp_path, monkeypatch, capsys, label):
    """Each car's bound is read before any car starts, and a refusal names that car alone and never its recording."""
    f = Fleet(tmp_path, monkeypatch)
    real = stack.player_bound_s

    def bound(log):
        if Path(log).parent == f.recs[label]:
            raise stack.StackError("made up: the stack refuses this log")
        return real(log)

    monkeypatch.setattr(stack, "player_bound_s", bound)
    r = refused(f, capsys)
    assert "car %s: the stack refuses the bound on its player: made up" % label in r.err, r.err
    for other in "ABC":
        if other != label:
            assert "car %s" % other not in r.err, r.err
    assert f.recs[label].name not in r.err, r.err


@POSIX
def test_run_refuses_a_car_whose_log_is_not_in_time_order_naming_that_car_only(tmp_path, monkeypatch, capsys):
    """A log with a frame stamped before the one ahead of it plays to its latest stamp, not to its last frame's: the stack
    refuses its bound, so the fleet refuses that car before anything is written, though its span (its last frame less its
    first, 90 s) would pass the margin; the refusal names the car and never its recording."""
    f = Fleet(tmp_path, monkeypatch)
    f.recs["B"] = f.rig.recording("20990101-unordered-b", speeds(80_000) + [[2_000_000, 0.0], [90_000, 0.0]])
    r = refused(f, capsys)
    assert "car B: the stack refuses the bound on its player" in r.err and "not in time order" in r.err, r.err
    assert "car A" not in r.err and "car C" not in r.err and "20990101-unordered-b" not in r.err, r.err


@POSIX
def test_run_identifies_each_cars_recording_once_and_reads_its_bound_from_the_log_check_identified(tmp_path, monkeypatch, capsys):
    """run's bound for a car is the stack's for the log check identified (recording_identity's), so each car's recording
    is identified, its log hashed, once: a refusal of recording_identity is check's, never printed as the bound's."""
    f = Fleet(tmp_path, monkeypatch)
    identified: List[Path] = []
    bounded: List[Path] = []
    real_identity, real_bound = stack.recording_identity, stack.player_bound_s
    monkeypatch.setattr(stack, "recording_identity", lambda d: (identified.append(Path(d)), real_identity(d))[1])
    monkeypatch.setattr(stack, "player_bound_s", lambda log: (bounded.append(Path(log)), real_bound(log))[1])
    monkeypatch.delenv(stack.CONNECTOR_IMAGE_ENV)          # run's first refusal after the bounds
    r = refused(f, capsys)
    assert "%s is not set" % stack.CONNECTOR_IMAGE_ENV in r.err, r.err
    assert identified == [f.recs[L] for L in f.labels], identified
    assert bounded == [f.recs[L] / "sigsim.log" for L in f.labels], bounded


@POSIX
def test_run_reads_a_carla_drives_bound_from_its_own_carla_log(tmp_path, monkeypatch, capsys):
    """A CARLA drive's log is carla.log (recording_identity's name for its generator, as video 3's cars are): run reads that
    car's bound from it, as check identified it, never from a sigsim.log the recording does not hold."""
    f = Fleet(tmp_path, monkeypatch)
    f.rig.manifest.update(vehicle_layers={"carla": {"file": "vehicle-carla.vspec"}}, databroker_catalogues={"carla": "vss-databroker.json"})
    layer = b"Vehicle.Chassis.Wheelbase:\n  default: 2468\n"
    (f.rig.gen / "vehicle-carla.vspec").write_bytes(layer)
    f.rig.manifest.setdefault("outputs", {}).update({"vehicle-carla.vspec": {"sha256": hashlib.sha256(layer).hexdigest()},
                                                     "vss-databroker.json": {"sha256": stack.sha256_file(f.rig.gen / "vss-databroker.json")}})
    f.rig.write_manifest()
    f.recs["B"] = f.rig.recording("20990101-drive-b-carla", speeds(81_000), gen="carla")
    bounded: List[Path] = []
    real = stack.player_bound_s
    monkeypatch.setattr(stack, "player_bound_s", lambda log: (bounded.append(Path(log)), real(log))[1])
    monkeypatch.delenv(stack.CONNECTOR_IMAGE_ENV)          # run's first refusal after the bounds
    r = refused(f, capsys)
    assert "%s is not set" % stack.CONNECTOR_IMAGE_ENV in r.err, r.err
    assert bounded == [f.recs["A"] / "sigsim.log", f.recs["B"] / "carla.log", f.recs["C"] / "sigsim.log"], bounded


@POSIX
def test_a_fleet_of_three_short_cars_passes_as_before_each_bounded_by_its_own_logs_span_read_before_any_car_starts(tmp_path, monkeypatch,
                                                                                                                       capsys):
    """Three cars whose logs end well inside their bounds run as before (fleet: ok). fleet.py's player_bound_s gives, for
    one car's recording, the stack's bound for that car's log (its span plus PLAYER_HEADROOM_S, rounded up: three logs of
    three spans, three bounds), and run reads each car's before it starts any."""
    f = Fleet(tmp_path, monkeypatch)
    spans = {L: fleet.check_car(L, f.recs[L])["span_ms"] for L in f.labels}
    want = {L: -(-(spans[L] + stack.PLAYER_HEADROOM_S * 1000) // 1000) for L in f.labels}
    assert {L: fleet.player_bound_s(f.recs[L]) for L in f.labels} == want and len(set(want.values())) == 3, want
    read: List[Any] = []
    real = stack.player_bound_s
    monkeypatch.setattr(stack, "player_bound_s", lambda log: (read.append((Path(log), f.events())), real(log))[1])
    r = run_main(f.argv(), capsys)
    assert r.code == 0 and r.lines[-1] == "fleet: ok", r
    assert read == [(f.recs[L] / "sigsim.log", []) for L in f.labels], read


@POSIX
@pytest.mark.parametrize("problem", ["role orin", "role unknown", "image not an id", "image of another generation", "image not in the store",
                                     "image runs as root"])
def test_run_refuses_a_host_role_other_than_pc_and_a_connector_image_the_stacks_own_rule_refuses(tmp_path, monkeypatch, capsys, problem):
    """Before the fleet stamp, so that a retry is not held START_SPACING_S: stack.py's own host_role and connector_image
    decide, and neither the image's ID nor the role's value is printed."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    if problem == "role orin":
        monkeypatch.setenv("SDV_HOST_ROLE", "orin")
    elif problem == "role unknown":
        monkeypatch.setenv("SDV_HOST_ROLE", "a-laptop")
    elif problem == "image not an id":
        monkeypatch.setenv("SDV_CONNECTOR_IMAGE", "sdv-twin-connector:latest")
    elif problem == "image of another generation":
        f.image_labels["sdv.twin.catalogue_sha256"] = "0" * 64
    elif problem == "image not in the store":
        f.image_in_store = False
    else:
        f.image_user = "root"
    r = refused(f, capsys)
    assert ("SDV_HOST_ROLE" if problem.startswith("role") else "SDV_CONNECTOR_IMAGE") in r.err, r.err
    assert "a-laptop" not in r.err and "sdv-twin-connector:latest" not in r.err, r.err


@POSIX
@pytest.mark.parametrize("what", ["no stamp", "from the future"])
def test_a_fleet_stamp_that_is_no_stamp_or_from_the_future_is_refused_once_and_written_anew(tmp_path, monkeypatch, capsys, what):
    """startstamp.mark's own rule on the fleet's stamp: the first start is refused and the stamp written anew with this
    moment, so the refusals end START_SPACING_S later; nothing else is made."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    d = f.state / "fleet"
    if what == "no stamp":
        d.mkdir(parents=True)
        (d / "started.json").write_text("not a stamp", encoding="ascii")
    else:
        f.stamp(d, -10 * 86400.0)
    stamp = (d / "started.json").read_bytes()
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and r.out == "" and "fleet" in r.err and "written anew" in r.err and what in r.err, r
    assert not f.run_dir().exists() and f.events() == []
    written = stack.connector_part("startstamp").parse((d / "started.json").read_bytes())
    assert (d / "started.json").read_bytes() != stamp and written is not None and abs(written - time.time() * 1000) < 60_000
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and "spacing" in r.err, r
    f.stamp(d, 121.0)
    assert run_main(f.argv(), capsys).code == 0


@POSIX
@pytest.mark.parametrize("label", ["A", "B"])
@pytest.mark.parametrize("what", ["no stamp", "from the future"])
def test_a_cars_identity_stamp_that_is_no_stamp_or_from_the_future_is_refused_naming_the_file_to_remove(tmp_path, monkeypatch, capsys, label, what):
    """The fleet writes no car's stamp (the car's stack does), so its refusal says which file to remove, by its place under
    SDV_STATE and never by its path; once it is gone, the fleet runs."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    rel = "twin" if label == "A" else "fleet/car-%s/twin" % label
    where = f.state / rel
    if what == "no stamp":
        where.mkdir(parents=True)
        (where / "started.json").write_text("not a stamp", encoding="ascii")
    else:
        f.stamp(where, -86400.0)
    stamp = (where / "started.json").read_bytes()
    r = run_main(f.argv(), capsys)
    assert r.code == 2 and r.out == "" and not f.run_dir().exists() and f.events() == [] and not (f.state / "fleet" / "started.json").exists(), r
    assert "car %s" % label in r.err and what in r.err and "remove" in r.err and "%s/started.json" % rel in r.err and "SDV_STATE" in r.err, r.err
    assert str(f.state) not in r.err and (where / "started.json").read_bytes() == stamp
    (where / "started.json").unlink()
    assert run_main(f.argv(), capsys).code == 0


# --- run: aborts, interrupts and a car that will not end -----------------------------------------------------------------

@POSIX
def test_an_abort_interrupts_a_car_that_is_still_preparing_so_it_never_reaches_its_up(tmp_path, monkeypatch, capsys):
    """Car A ends once it is ready while car B prepares. The abort file alone would reach car B only at its gate, after its
    up() (its containers, the connector among them, started; its stamp marked), so the fleet gives it one SIGINT; car C is
    never started."""
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEET_TEST_MODE_1", "end-after-ready")
    monkeypatch.setenv("FLEET_TEST_PREPARE_S_2", "10")
    t0 = time.monotonic()
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok" and time.monotonic() - t0 < 8, r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["gate"] == {"go_ms": None, "abort": "car A ended before go"}, rec["gate"]
    assert [w for w, k, _t in f.events() if k == 2] == ["start", "sigint", "interrupted"], f.events()
    assert not [e for e in f.events() if e[1] == 3], "car C was started"
    assert [c["stack_exit"] for c in rec["cars"]] == [4, 130, None]


def alive(pid: int) -> bool:
    """A process that is there and is no zombie."""
    try:
        with open("/proc/%d/stat" % pid, encoding="ascii") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


@POSIX
def test_a_car_that_ignores_its_interrupt_is_killed_with_its_process_group_and_its_instances_containers_removed(tmp_path, monkeypatch, capsys):
    """STOP_GRACE_S after its SIGINT a car is killed with its process group (the stack and what it started, the player
    among them), and since its stack's finally never ran, its instance's containers are removed by the stack's instance
    label, nobody else's."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_1", "stubborn")
    monkeypatch.setattr(fleet, "CAR_TIMEOUT_S", 5.0)
    monkeypatch.setattr(fleet, "STOP_GRACE_S", 1.0)
    f.instance_containers = {"label=sdv.stack.instance=1": "c0ffee01\nc0ffee02\n", "label=sdv.stack.instance=2": "beef0002\n"}
    child: Optional[int] = None
    t0 = time.monotonic()
    try:
        r = run_main(f.argv(), capsys)
        child = int((f.test_dir / "child-1.pid").read_text(encoding="ascii"))
        assert time.monotonic() - t0 < 20 and r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
        rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
        assert [c["stack_exit"] for c in rec["cars"]] == [-signal.SIGKILL, 0], rec["cars"]
        assert f.env(1)["pgid"] == f.env(1)["pid"] != os.getpgid(0), "the car is not in a process group of its own"
        end = time.monotonic() + 5
        while alive(child) and time.monotonic() < end:
            time.sleep(0.1)
        assert not alive(child), "the killed car's child (in the stack, its player) runs on"
        swept = [c for c in f.docker_calls if c[:2] in (["ps", "-aq"], ["rm", "-f"]) and c != ["ps", "-aq", "--filter", "label=sdv.stack.run"]]
        assert swept == [["ps", "-aq", "--filter", "label=sdv.stack.instance=1"], ["rm", "-f", "c0ffee01", "c0ffee02"]], swept
        assert "killed" in r.err and "removed" in r.err, r.err
    finally:
        if child is not None and alive(child):
            os.kill(child, signal.SIGKILL)


class Delivered(Exception):
    """A signal that reached the test itself: the fleet had no handler of its own for it."""


@contextlib.contextmanager
def signals_to_the_test() -> Any:
    """SIGINT and SIGTERM raise Delivered while the fleet runs in this process, unless the fleet's own handlers stand."""
    def reached(signum: int, _frame: Any) -> None:
        raise Delivered(signal.Signals(signum).name)

    before = {s: signal.signal(s, reached) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for s, h in before.items():
            signal.signal(s, h)


def signal_when(path: Path, sig: int, delay_s: float = 0.3) -> threading.Thread:
    """A thread that sends sig to this process once path exists, delay_s after."""
    def send() -> None:
        end = time.monotonic() + 20
        while not path.exists() and time.monotonic() < end:
            time.sleep(0.02)
        if path.exists():
            time.sleep(delay_s)
            os.kill(os.getpid(), sig)

    t = threading.Thread(target=send, daemon=True)
    t.start()
    return t


def run_signalled(f: Fleet, capsys: Any, when: Path, sig: int, delay_s: float) -> types.SimpleNamespace:
    with signals_to_the_test():
        t = signal_when(when, sig, delay_s)
        try:
            return run_main(f.argv(), capsys)
        except Delivered as exc:
            pytest.fail("%s reached the test: the fleet has no handler of its own for it" % exc)
        finally:
            t.join(30)


@POSIX
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_an_interrupt_after_go_gives_every_running_car_one_sigint_and_the_fleet_still_writes_its_record(tmp_path, monkeypatch, capsys, sig):
    """SIGINT or SIGTERM to the fleet after go: every running car gets one SIGINT (none a second), each is waited for, and
    fleet.json is written, ok false, with the interrupt as gate.abort's reason; no abort file (the cars are past the gate)."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    for k in (1, 2):
        monkeypatch.setenv("FLEET_TEST_MODE_%d" % k, "linger")
    t0 = time.monotonic()
    r = run_signalled(f, capsys, f.run_dir() / "gate" / "go", sig, 0.5)
    assert time.monotonic() - t0 < 15 and r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert isinstance(rec["gate"]["go_ms"], int) and "interrupted" in rec["gate"]["abort"] and "after go" in rec["gate"]["abort"], rec["gate"]
    assert rec["ok"] is False and not (f.run_dir() / "gate" / "abort").exists()
    for k in (1, 2):
        ev = [w for w, kk, _t in f.events() if kk == k]
        assert ev.count("sigint") == 1 and ev[-1] == "interrupted" and "done" not in ev, (k, ev)
    assert [c["stack_exit"] for c in rec["cars"]] == [130, 130]


@POSIX
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_an_interrupt_before_go_aborts_and_interrupts_the_car_still_preparing(tmp_path, monkeypatch, capsys, sig):
    """SIGINT or SIGTERM to the fleet while car B prepares: the abort ends car A at its gate, car B gets one SIGINT and never
    reaches its up(), car C is never started, and fleet.json is written."""
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEET_TEST_PREPARE_S_2", "10")
    t0 = time.monotonic()
    r = run_signalled(f, capsys, f.run_dir() / "gate" / "ready-1", sig, 0.3)
    assert time.monotonic() - t0 < 8 and r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["gate"]["go_ms"] is None and "interrupted" in rec["gate"]["abort"] and "before go" in rec["gate"]["abort"], rec["gate"]
    assert (f.run_dir() / "gate" / "abort").read_text(encoding="utf-8").strip() == rec["gate"]["abort"]
    assert [w for w, k, _t in f.events() if k == 1][-1] == "abort"
    assert [w for w, k, _t in f.events() if k == 2] == ["start", "sigint", "interrupted"], f.events()
    assert not [e for e in f.events() if e[1] == 3], "car C was started"


@POSIX
def test_a_failure_of_the_fleets_own_while_it_starts_the_cars_aborts_waits_for_them_and_writes_the_record(tmp_path, monkeypatch, capsys):
    """Any exception while the cars start (here car B's process cannot be started) writes the abort, so the started cars end
    at the gate rather than after their own GATE_WAIT_S; they are waited for, fleet.json is written, and the failure is
    raised after it."""
    f = Fleet(tmp_path, monkeypatch)
    start = fleet.Car.start

    def failing_start(car: Any, *a: Any) -> None:
        if car.label == "B":
            raise OSError("made up: car B cannot be started")
        start(car, *a)

    monkeypatch.setattr(fleet.Car, "start", failing_start)
    t0 = time.monotonic()
    with pytest.raises(OSError):
        fleet.main(f.argv())
    capsys.readouterr()
    assert time.monotonic() - t0 < 15
    why = "the fleet failed before go (OSError)"
    assert (f.run_dir() / "gate" / "abort").read_text(encoding="utf-8").strip() == why
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["ok"] is False and rec["gate"] == {"go_ms": None, "abort": why}, rec["gate"]
    assert [c["stack_exit"] for c in rec["cars"]] == [1, None, None]
    assert [w for w, k, _t in f.events() if k == 1][-1] == "abort"


@POSIX
def test_go_is_not_written_when_a_car_ended_in_the_poll_that_saw_the_last_ready(tmp_path, monkeypatch, capsys):
    """The last car's ready and an earlier car's end fall in one poll: a last look before go sees the end, and the fleet
    aborts instead of sending the surviving cars to their feeds."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    monkeypatch.setenv("FLEET_TEST_MODE_1", "end-after-ready")
    monkeypatch.setenv("FLEET_TEST_END_AFTER_S_1", "4.0")
    monkeypatch.setenv("FLEET_TEST_PREPARE_S_2", "0.1")
    cars: Dict[str, Any] = {}
    start, read_ready = fleet.Car.start, fleet.Car.read_ready

    def keep(car: Any, *a: Any) -> None:
        cars[car.label] = car
        start(car, *a)

    def ready_once_a_has_ended(car: Any, gate: Path) -> bool:
        got = read_ready(car, gate)
        if got and car.label == "B":
            cars["A"].proc.wait(15)          # car A ends after car B's ready is seen, before the fleet looks again
        return bool(got)

    monkeypatch.setattr(fleet.Car, "start", keep)
    monkeypatch.setattr(fleet.Car, "read_ready", ready_once_a_has_ended)
    r = run_main(f.argv(), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok", r
    assert [w for w, k, _t in f.events() if k == 1][-1] == "end" and "ready" in [w for w, k, _t in f.events() if k == 2], f.events()
    assert not (f.run_dir() / "gate" / "go").exists(), "go was written although car A had ended"
    rec = json.loads((f.run_dir() / "fleet.json").read_text(encoding="utf-8"))
    assert rec["gate"] == {"go_ms": None, "abort": "car A ended before go"}, rec["gate"]


# --- run: the masks ------------------------------------------------------------------------------------------------------

@POSIX
def test_identity_values_are_masked_and_searched_for_whatever_their_length_and_a_name_alone_by_the_value_passed_through(
        tmp_path, monkeypatch, capsys):
    """A thing of five characters, and a rule given as a NAME line alone (docker passes the fleet's own value through), are
    masked in the car's log, nothing under the run holds either, and the fleet is ok. In a file the car writes, which
    nothing masks, the short thing is found and the fleet is not ok."""
    f = Fleet(tmp_path, monkeypatch, n=2)
    short_thing, short_rule = "vin42", "rul9"
    (f.devices["B"] / "connector.env").write_text("SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE\n" % (ENDPOINT, short_thing),
                                                  encoding="ascii")
    monkeypatch.setenv("SDV_TWIN_RULE", short_rule)
    monkeypatch.setenv("FLEET_TEST_THING_2", short_thing)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "leaky")
    monkeypatch.setenv("FLEET_TEST_PRINT_2", "the rule %s" % short_rule)
    r = run_main(f.argv(), capsys)
    assert r.code == 0 and r.lines[-1] == "fleet: ok", r
    run = f.run_dir()
    log = (run / "car-B" / "stack.log").read_text(encoding="utf-8")
    assert "<device value>" in log and short_thing not in log and short_rule not in log, log
    for p in run.rglob("*"):
        if p.is_file():
            assert short_thing.encode() not in p.read_bytes() and short_rule.encode() not in p.read_bytes(), p
    f.stamp(f.state / "fleet", 121.0)
    monkeypatch.setenv("FLEET_TEST_MODE_2", "leaky-file")
    r = run_main(f.argv("v3-fleet-2"), capsys)
    assert r.code == 1 and r.lines[-1] == "fleet: NOT ok" and "notes.txt" in r.err and short_thing not in r.out + r.err, r


# --- the design values ---------------------------------------------------------------------------------------------------

def test_the_design_values_are_the_ones_fleet_p1s_spec_names():
    """The design values: stack.py's GATE_WAIT_S 600 s and fleet.py's (the same), CAR_TIMEOUT_S 1800 s, PLAYER_MARGIN_S 10 s,
    and limits.py's START_SPACING_S 120 s, unchanged; MIN_MOVING_S an int, 40 s, which fleet.py's
    DESIGN VALUES states with its reason, that the fleet's shortest drive exceeds the threshold."""
    assert (stack.GATE_WAIT_S, fleet.GATE_WAIT_S, fleet.CAR_TIMEOUT_S, fleet.MIN_MOVING_S, fleet.PLAYER_MARGIN_S) == (600, 600, 1800, 40, 10)
    assert type(fleet.MIN_MOVING_S) is int, fleet.MIN_MOVING_S
    assert stack.connector_part("limits").START_SPACING_S == 120
    design = re.search(r"DESIGN VALUES \(none a claim\):(.*?)Does not demonstrate:", re.sub(r"\s+", " ", fleet.__doc__ or ""))
    assert design and "MIN_MOVING_S (40 s" in design.group(1) and (
        "the fleet's shortest drive moves for longer than MIN_MOVING_S, and 40 s still refuses a parked car or a drive that barely moves"
        in design.group(1)), "fleet.py's DESIGN VALUES on MIN_MOVING_S"


def test_min_moving_s_has_one_reason_in_its_comment_and_in_the_design_values():
    """fleet.py gives MIN_MOVING_S's reason in the constant's comment and in DESIGN VALUES: the two say
    the same words, DESIGN VALUES with the constant's value and the reason with what that value still refuses, so neither
    place can say another figure alone."""
    import inspect
    lines = inspect.getsource(fleet).splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("MIN_MOVING_S = "))
    j = next(k for k, ln in enumerate(lines) if ln.startswith("MOVING_MPS = "))
    comment = " ".join(ln.split("#", 1)[1].strip() for ln in lines[i:j])
    said = re.search(r"\(a design value: (.+)\)$", comment)
    design = re.search(r"MIN_MOVING_S \((\d+) s: (.+?)\), GATE_WAIT_S", re.sub(r"\s+", " ", fleet.__doc__ or ""))
    assert said and design, (comment, design)
    assert int(design.group(1)) == fleet.MIN_MOVING_S and said.group(1) == design.group(2), (said.group(1), design.groups())
    assert "%d s still refuses" % fleet.MIN_MOVING_S in said.group(1), said.group(1)


def test_the_design_values_say_the_margin_refusal_is_a_guard_while_the_stacks_headroom_is_the_larger(tmp_path, monkeypatch):
    """With stack.py's PLAYER_HEADROOM_S larger than PLAYER_MARGIN_S, every log the stack bounds, from one frame to the
    ceiling's span, ends more than PLAYER_MARGIN_S inside its bound, so run's margin refusal meets no such log: fleet.py's
    DESIGN VALUES say once that it is a guard against a later change of the headroom."""
    import test_sdv_stack_playerbound as PB
    assert stack.PLAYER_HEADROOM_S > fleet.PLAYER_MARGIN_S
    monkeypatch.setitem(sys.modules, "can", types.SimpleNamespace(LogReader=PB.CandumpReader))
    room_ms = (stack.PLAYER_BOUND_MAX_S - stack.PLAYER_HEADROOM_S) * 1000
    for span_ms in (0, 1, 999, 1000, 123_456, room_ms - 1, room_ms):
        log = PB.candump_log(tmp_path / str(span_ms) / "sigsim.log", [PB.T0, PB.T0 + span_ms / 1000.0])
        bound = stack.player_bound_s(log)
        assert span_ms < (bound - fleet.PLAYER_MARGIN_S) * 1000, (span_ms, bound)
    doc = re.sub(r"\s+", " ", fleet.__doc__ or "")
    design = re.search(r"DESIGN VALUES \(none a claim\):(.*?)Does not demonstrate:", doc)
    assert design, "fleet.py's DESIGN VALUES paragraph"
    for words in ("While stack.py's PLAYER_HEADROOM_S is larger than PLAYER_MARGIN_S", "no log the stack takes ends less than "
                  "PLAYER_MARGIN_S inside its bound", "a guard against a later change of the headroom"):
        assert words in design.group(1), (words, design.group(1))
    assert doc.count("a guard against a later change of the headroom") == 1, "said once"


def test_runs_docstring_names_each_reason_the_stack_refuses_a_cars_bound():
    """fleet.py's RUN paragraph names every reason stack.py's player_bound_s refuses a car's bound for."""
    doc = re.sub(r"\s+", " ", fleet.__doc__ or "")
    run = re.search(r"RUN Refused(.*?)DESIGN VALUES", doc)
    assert run and "a bound over PLAYER_BOUND_MAX_S, no frame, not in time order, unreadable" in run.group(1), doc


# --- sdv/stack/README.md: the fleet section ------------------------------------------------------------------------------

TWIN_CONNECTOR_HEADING = "The twin connector (SDV Phase 4 WP3): `--connector`"


def test_the_stack_readme_has_a_fleet_section_after_the_twin_connectors_with_the_codes_names_and_design_values():
    """sdv/stack/README.md's fleet section, the next one after the twin connector's: both commands and the variables, check's
    rule, each car's stack instance (its names, interface, ports and label), the gate, the start spacing and its stamps, the
    record and the witness, the player's bound with fleet.py's margin, the opt-in test, and what it does not demonstrate.
    Every name and design value is read from fleet.py and stack.py, so a section that says another one fails."""
    text = (STACK_DIR / "README.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert TWIN_CONNECTOR_HEADING in headings, headings
    after = headings[headings.index(TWIN_CONNECTOR_HEADING) + 1]
    assert after.startswith("A fleet "), "the section after the twin connector's is %r, not the fleet's" % after
    m = re.search(r"^## %s\n(.*?)(?=^## |\Z)" % re.escape(after), text, re.M | re.S)
    assert m
    section = re.sub(r"\s+", " ", m.group(1))
    limits, ss = stack.connector_part("limits"), stack.connector_part("startstamp")
    wanted = ["fleet.py check --car A=REC_DIR --car B=REC_DIR [--car C=REC_DIR]", "fleet.py run --name NAME --car A=REC_DIR",
              "%s=<image ID>" % stack.CONNECTOR_IMAGE_ENV, "two or three recordings at once on the PC", "cars A, B and C",
              "stack instances 1, 2 and 3",
              "writes nothing", "`moves`", "`distinct`", "above %s m/s" % fleet.MOVING_MPS, "at least %d s apart" % fleet.MIN_MOVING_S,
              "`stack.py replay --name <NAME>-<L> --feed vcan --bridge none --connector`", "%s=<k>" % stack.INSTANCE_ENV, "`-f<k>`",
              "`vcanf<k>`", "port %d + k" % stack.FLEET_BROKER_PORT_BASE, "port %d + k" % stack.FLEET_MOCK_PORT_BASE,
              "`%s=<k>`" % stack.INSTANCE_LABEL, "`<run>/gate/%s`" % stack.GATE_GO, "`<run>/gate/%s`" % stack.GATE_ABORT, "`GATE_WAIT_S`",
              "one fleet start per %d s" % limits.START_SPACING_S, "`<STATE>/fleet/%s`" % ss.FILE, "`<STATE>/fleet/car-<L>`",
              "car A shares the one-car run's stamp", "`<run>/fleet.json`", "`SDV_RUNS/<YYYYMMDD>-<NAME>`", "`%s`" % stack.WITNESS_LOG,
              "`trip_summary.py --local`", "no device directory's path", "no value of `%s`" % stack.CONNECTOR_ENV_FILE,
              "at least %d s inside its own bound on its player" % fleet.PLAYER_MARGIN_S, "whose bound the stack refuses",
              "`SDV_FLEET_BROKER=1`", "`tests/test_sdv_fleet_broker.py`", "Does not demonstrate", "the cloud", "any timing",
              "the PC's capacity", "removes the fleet's containers"]
    wanted += ["%s=<directory>" % (fleet.DEVICE_ENV % L) for L in fleet.LABELS]
    missing = [w for w in wanted if w.lower() not in section.lower()]          # a word that begins a sentence there has a capital
    assert missing == [], missing
    assert not re.search(r"\d{8}-carla010-", section), "the section names a take: the drives are the opt-in test's and the owner's"
