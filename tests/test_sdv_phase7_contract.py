"""The Phase 7 early packages against each other on the integration branch p7-early (SDV plan Phase 7, spec section
10).

Each package's own tests meet the others only through stand-ins: WP1's encoder binds profile 3 through a synthetic
contract (WP1's tree held the base generation), WP3a rewrites the sigsim recording relabelled carla under profile 1, WP9
reads frame sets of its own patterns, WP4a plans against stand-in headers. Here they meet on one tree, against this
tree's own generation (sdv-out/gen, made by WP2's generate.py: profile 3 compiled, no stand-in), one item of section 10
each:

- THE CHAIN. A take made by WP1's capture (sdv/carla/carla_capture.py) on the fake simulator
  (tests/fixtures/carla/fake_carla.py) with WP1's short drive (tests/test_sdv_carla.py: one junction turn before the
  hard brake), encoded by WP1's encoder (sdv/carla/encode.py) against the real generation with no synthetic contract,
  under an absolute temporary root (encode.py writes the line's path unresolved outside ~/sdv-recordings, and a scenario
  entry's path starts at / or ~): every verify term holds and the manifest line is spec 2.3's, its wheelbase profile 3's
  L, the carla vehicle layer's default and the fake car's. WP3a's source checks (sdv/inject/inject.py) read it by its
  log's name, find the reverse its trip engages and count the frames rule 26 must fire on under profile 3 exactly as the
  encoder's verify counted them (verify.judge.rule26_above_tol, which the yaw event reads); the injector rewrites it into
  another temporary root (carla.log, the rtf unchanged, the five params and the rewrite's three, no steps.jsonl) and
  `check` passes on the result, each run giving each event its intended reason, the source unchanged. In this process
  with the exact stand-ins of WP1's and WP3a's tests for cantools and python-can, and, where ~/sdv-sim-venv exists, as
  the two tools' command lines in that venv with the real ones, whose logs are the stand-ins' byte for byte. A second
  take, on the fake simulator keeping its step in single precision as CARLA 0.9.16's server does (finding F-RTF),
  reaches the injector's source checks with an rtf of exactly 1, their rtf rule unchanged.
- THE FRAME SET. A set WP1's frame-set writer (sdv/carla/frameset.py) wrote in tmp, the capture's own from the fake
  camera and one of synthetic patterns, is read by WP9's reader (orin-native/edge-llm/camera_client.py read_frames) in
  its listed order, and the two readers refuse the same sets: each refusal of spec 2.4, a file listed for another step
  than its name, and a step index that is not an integer. A take whose every image was lost writes a set with no frame,
  which WP9's reader refuses ('no frames listed'): that refusal is the camera app's side.
- THE NAMES. The capture's and the encoder's constants are the generation's names: every name sdv/carla reads from a
  contract is one this generation defines, and none is bound as a literal there; the send policy takes each value from
  its own name (a contract whose values all differ), and a take ties its world to CARLA_STEP_MS and paces at
  FEEDER_PACING_INTERVAL_MS when those differ from the generation's.
- THE IMAGE'S BUILD. `make -n -B vss-carla` (WP4a's Makefile) plans against this tree's vss_profiles.h, whose profile 3
  row is the generation's: exactly the vss line with '-o qnx-safety-monitor-carla', nothing on stderr, nothing written;
  with VSS_CARLA_GEN at a copy of the generation's headers without profile 3's row it stops with 'holds no profile 3'.
- THE FIREWALL PREDICATE. Spec 2.5 sentence by sentence, each with a case of WP1's fixtures
  (tests/fixtures/carla/fwcheck-cases.json) where it fails and one where it holds: the predicate's clauses in a table,
  fwcheck giving each named case its expected lines; P4's other arm ('or the client runs no Traffic Manager', --no-tm)
  on every case, its P4 lines alone gone and the line saying so; and the output sentence through fwcheck.run on every
  case, the case's lines and exit 0 exactly on PASS. --for windows-client never checks P3.

Every number here is a design value, a value of the generation or of the fake simulator, or computed from them; none is
a measurement. Takes, recordings and frame sets are written under pytest's tmp_path only, never under ~/sdv-recordings,
E:\\CARLA or a work tree; make runs with -n only.

Under SDV_REQUIRE_GEN=1 (the recipe's switch, read as tests/twin_gate.py reads it) a tree without its generated
contract, or without the generation the Makefile's VSS_CARLA_GEN names, fails this file at collection: its items do not
skip, since twin_gate's skip check does not read this file. Without the switch they skip as before.

What this does NOT show: that a recording is judged by any guest (WP4b, WP6, WP7); the stack replaying a CARLA
recording (WP3b; the strict xfail in tests/test_sdv_inject.py); anything about CARLA, a firewall, a camera or a compiler
(each is a stand-in here: the fake simulator, the fixtures' snapshots, synthetic frames, make -n); vehicle dynamics, CAN
timing, perception, any timing. WSL only, as tests/test_sdv_inject.py is: the injector's bridge module imports fcntl.
"""
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import types
import zlib
from pathlib import Path

import pytest

import test_sdv_bridge_sources as tsbs
import test_sdv_carla as tsc
import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLA_DIR = REPO / "sdv" / "carla"
INJECT_DIR = REPO / "sdv" / "inject"
MON_DIR = REPO / "ipc-test" / "qnx-safety-monitor"
MAKE_GEN = REPO / "sdv-out" / "gen"                 # what the Makefile's VSS_CARLA_GEN names by default
CAMERA_CLIENT = REPO / "orin-native" / "edge-llm" / "camera_client.py"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(INJECT_DIR) not in sys.path:
    sys.path.insert(0, str(INJECT_DIR))
import inject as inj  # noqa: E402

sys.dont_write_bytecode = _saved

C = tsc.C
capture, encode, frameset, fwcheck, fake = tsc.capture, tsc.encode, tsc.frameset, tsc.fwcheck, tsc.fake
sendpolicy, worldtie, vf = tsc.sendpolicy, tsc.worldtie, tsc.vf
NEEDS_CONTRACT = tsc.NEEDS_CONTRACT
MS = 1_000_000
NAME, SEED = "20261018-carla-7", 7
INJ_NAME = NAME + "-inj"
RUN_TYPE = "carla"
RECORDING_FILES = ["carla.log", "carla.log.sha256", "manifest-line.json", "steps.jsonl", "summary.json"]
REWRITE_FILES = ["carla.log", "carla.log.sha256", "events.json", "manifest-line.json", "summary.json"]
VSS_BIN, CARLA_BIN = "qnx-safety-monitor-vss", "qnx-safety-monitor-carla"
PROFILE3_ERROR = "holds no profile 3"
# The send policy's and the profile's names in the generated contract (spec 1's list, as the capture and the encoder
# read them): each must stay a name the generation defines.
CONTRACT_NAMES = ("CARLA_STEP_MS", "FEEDER_PACING_INTERVAL_MS", "FEEDER_REPEAT_CAP_MS", "DBC_PERIOD_MS", "RULE26_DBC_MESSAGE",
                  "SLOT_DBC_MESSAGES", "SLOT_DBC_SIGNALS", "DBC_HALF_LSB", "LIVE_DEFAULT_PROFILE", "COMPILED_PROFILE_IDS",
                  "PROFILES", "CATALOG_DIGEST")
FW = json.loads((HERE / "fixtures" / "carla" / "fwcheck-cases.json").read_text(encoding="utf-8"))
FW_CASES = {c["name"]: c for c in FW["cases"]}


def missing_generation(contract, make_gen):
    """What this file's items need and this tree lacks, or None: the generated contract the chain, the names and the
    capture's frame set read (C, from SDV_GEN, default sdv-out/gen), and the generation the Makefile's VSS_CARLA_GEN names,
    which the make items read (make_gen: this tree's sdv-out/gen)."""
    if contract is None:
        return str(NEEDS_CONTRACT.kwargs["reason"])
    if not (Path(make_gen) / "vss_contract.py").is_file():
        return "no generated contract at %s (the Makefile's VSS_CARLA_GEN)" % (Path(make_gen) / "vss_contract.py")
    return None


# Under SDV_REQUIRE_GEN=1 (the recipe's switch, read as tests/twin_gate.py reads it: 1, or off) a missing generation fails
# this file at collection instead of skipping its items: twin_gate's skip check holds only the twin files and the Monitor
# guard, so a skip here would leave the recipe green with section 10's gate never run.
MISSING = missing_generation(C, MAKE_GEN)
if MISSING is not None and twin_gate.required():
    pytest.fail("SDV_REQUIRE_GEN=1 and this tree has no generated contract (%s): the Phase 7 contract test cannot run"
                % MISSING, pytrace=False)


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jload(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tree_hashes(root):
    return {str(p.relative_to(root)): sha256_of(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def gen_dir():
    """The generation C was loaded from (sdv-out/gen unless SDV_GEN names another)."""
    return vf.contract_path().parent


def carla_profile(contract=None):
    c = contract if contract is not None else C
    pid = int(c.LIVE_DEFAULT_PROFILE[RUN_TYPE])
    return pid, {int(r["id"]): r for r in c.PROFILES}[pid]


def contract_copy(**changes):
    """The generated contract as a namespace with some names given other values (the generated file is never edited)."""
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith("_")})
    for k, v in changes.items():
        setattr(ns, k, v)
    return ns


class StandInDB(tsbs.StandInDB):
    """tests/test_sdv_bridge_sources.py's stand-in for cantools' database plus what the injector reads, as
    tests/test_sdv_inject.py builds it: get_message_by_frame_id and each signal's minimum, maximum and scale."""

    def __init__(self, text):
        super().__init__(text)
        parsed = tsbs.attr.parse_dbc(text)["messages"]
        for m in self.messages:
            for s in m.signals:
                spec = parsed[m.name]["signals"][s.name]
                s.minimum, s.maximum, s.scale = spec["min"], spec["max"], spec["factor"]
        self._by_id = {m.frame_id: m for m in self.messages}

    def get_message_by_frame_id(self, frame_id):
        return self._by_id[frame_id]


# =================================================================================================================
# The chain: capture -> encoder (WP2's generation) -> the injector's source checks, rewrite and check
# =================================================================================================================

@pytest.fixture(scope="module")
def take(tmp_path_factory):
    """WP1's capture on the fake simulator with WP1's short drive and route, against the real contract."""
    rc, _carla, d = tsc.run_take(tmp_path_factory.mktemp("pc"), name=NAME, seed=SEED)
    return types.SimpleNamespace(rc=rc, dir=d)


@pytest.fixture(scope="module")
def recording(take, tmp_path_factory):
    """encode.record on the take against the real contract (no synthetic one), cantools' database and python-can's reader
    replaced by WP1's tests' exact stand-ins, into an absolute temporary root."""
    out = tmp_path_factory.mktemp("recordings") / NAME
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(encode, "load_dbc", lambda contract, path=None: tsc.FakeDb())
        mp.setattr(encode, "read_log", tsc.fake_read_log)
        res = encode.record(take.dir, out, NAME, contract=C)
    return types.SimpleNamespace(res=res, dir=out)


@pytest.fixture(scope="module")
def injected(recording, tmp_path_factory):
    """The injector's build, write (into another temporary root) and check of the encoder's recording."""
    db = StandInDB(tsbs.SLICE_TEXT)
    before = tree_hashes(recording.dir)
    built = inj.build(recording.dir, INJ_NAME, db, C, inj.bs.SLICE_DBC)
    dest = tmp_path_factory.mktemp("injected") / INJ_NAME
    out = inj.write(built, dest)
    checked = inj.check(dest, db, C, inj.bs.SLICE_DBC)
    return types.SimpleNamespace(built=built, dest=dest, out=out, checked=checked, before=before,
                                 after=tree_hashes(recording.dir))


@NEEDS_CONTRACT
def test_the_generation_compiles_profile_3_and_its_carla_layer_carries_the_fake_cars_wheelbase():
    """WP2's generation, as the chain below needs it: the carla run type's live-default profile compiled with no stand-in,
    its L the fake car's wheelbase (FAKE_WHEELBASE_MM is that L by design), the carla vehicle layer's default and its
    vspec's, and manifest.json's vehicle_layer still the sigsim layer's object (sdv/stack/stack.py reads it)."""
    pid, row = carla_profile()
    assert pid in C.COMPILED_PROFILE_IDS and row["compiled"] is True and not row["stand_in"], row
    manifest = jload(gen_dir() / "manifest.json")
    layer = manifest["vehicle_layers"][RUN_TYPE]
    assert layer["profile_id"] == pid and layer["default"] == row["l_mm"] == fake.FAKE_WHEELBASE_MM
    assert "  default: %d\n" % row["l_mm"] in (gen_dir() / layer["file"]).read_text(encoding="utf-8")
    assert manifest["vehicle_layer"] == manifest["vehicle_layers"]["sigsim"]


@NEEDS_CONTRACT
def test_a_take_on_the_fake_simulator_records_and_verifies_against_this_trees_generation(take, recording):
    assert take.rc == 0
    res, out = recording.res, recording.dir
    v = res["verify"]
    assert res["recorded"] is True and v["ok"] is True, (v["ok_terms"], v["problems"])
    assert set(v["ok_terms"]) == set(encode.OK_TERMS) and all(v["ok_terms"].values()) and v["log_sha256_file_holds"] is True
    assert sorted(p.name for p in out.iterdir()) == RECORDING_FILES
    sha = sha256_of(out / "carla.log")
    assert (out / "carla.log.sha256").read_text(encoding="ascii") == "%s  carla.log\n" % sha
    pid, row = carla_profile()
    line = jload(out / "manifest-line.json")
    assert line["name"] == NAME and line["profile_id"] == pid
    assert line["recording"] == {"format": "candump-log", "path": str(out / "carla.log"), "sha256": sha}
    assert inj.is_scenario_path(line["recording"]["path"])
    src = line["source"]
    assert src["generator"] == "carla" and sorted(src) == ["generator", "params", "rtf", "vehicle"]
    assert src["params"] == {"catalog_digest": "0x%08X" % C.CATALOG_DIGEST, "dbc_sha256": sha256_of(inj.bs.SLICE_DBC),
                             "seed": SEED, "town": "Town01", "version": "0.9.16"}
    assert src["vehicle"] == {"name": "vehicle.toyota.prius", "wheelbase_mm": row["l_mm"]}
    rtf = src["rtf"]
    assert sorted(rtf) == ["max", "mean", "min"] and 0 < rtf["min"] <= rtf["mean"] <= rtf["max"] <= 1
    trip = jload(out / "summary.json")["trip"]
    assert trip["rtf"] == rtf and trip["profile_id"] == pid and trip["wheelbase_mm"] == row["l_mm"]
    assert (out / "steps.jsonl").read_bytes() == (take.dir / "steps.jsonl").read_bytes()


@NEEDS_CONTRACT
def test_the_injector_reads_the_recording_by_its_log_and_counts_rule_26_frames_as_the_encoder_did(recording):
    """WP3a's source checks on WP1's real output: carla.log by the basename of recording.path, its .sha256 beside it, the
    reverse gear the trip engages, a replay-mode bridge binding profile 3 with the line's vehicle, and inject's own
    rule-26 count under profile 3 equal to the encoder's verify.judge.rule26_above_tol, and not zero (the yaw event
    needs frames there)."""
    src = inj.read_source(recording.dir)
    assert src.log_name == "carla.log" and src.line == jload(recording.dir / "manifest-line.json")
    assert inj.reverse_gear(src.summary) == -1
    cfg = inj.bridge_config(src.line)
    tables, problems = inj.vb.bind(cfg, C)
    pid, _row = carla_profile()
    assert not problems and cfg.profile_id == pid, problems
    pr = tables.profiles[pid]
    dec = inj.decode_lines(inj.parse_lines(src.log_text, "carla.log"), StandInDB(tsbs.SLICE_TEXT), C)
    counted = sum(1 for _off, vals in dec.dyn if inj.rule26_must_fire(vals, pr, tables))
    assert counted == src.summary["verify"]["judge"]["rule26_above_tol"] > 0


@NEEDS_CONTRACT
def test_the_injector_rewrites_the_recording_into_another_root_and_checks_it(recording, injected):
    dest = injected.dest
    assert dest.parent != recording.dir.parent
    assert sorted(p.name for p in dest.iterdir()) == REWRITE_FILES
    old, line = jload(recording.dir / "manifest-line.json"), jload(dest / "manifest-line.json")
    assert line["name"] == INJ_NAME and line["profile_id"] == old["profile_id"]
    assert line["recording"] == {"format": "candump-log", "path": inj.path_form(dest / "carla.log"),
                                 "sha256": sha256_of(dest / "carla.log")}
    assert line["source"]["generator"] == "carla" and line["source"]["vehicle"] == old["source"]["vehicle"]
    assert line["source"]["rtf"] == old["source"]["rtf"]
    assert line["source"]["params"] == dict(old["source"]["params"], rewrite_of=NAME,
                                            rewrite_of_sha256=old["recording"]["sha256"],
                                            rewrite_events_sha256=sha256_of(dest / "events.json"))
    assert len(line["source"]["params"]) == inj.PARAMS_MAX
    assert "steps.jsonl" in jload(dest / "summary.json")["rewrite"]["not_copied"]
    assert injected.checked["ok"] is True and "diff" in injected.checked["source"], injected.checked
    for run in inj.RUNS:
        want = [(e["event"], e["intended_reason"]) for e in inj.run_events(injected.built.events, run)]
        assert [tuple(x) for x in injected.checked["runs"][run]] == want, run
    assert injected.after == injected.before


@NEEDS_CONTRACT
def test_a_take_from_a_server_that_keeps_its_step_in_single_precision_reaches_the_injector_with_its_rtf(tmp_path):
    """Finding F-RTF (WP5a's first take, local notes): CARLA 0.9.16's server keeps fixed_delta_seconds in single
    precision. A take on the fake simulator stepping so, encoded against this tree's generation, gives a line whose rtf
    is exactly 1 in each value, and the injector's source checks take it with their rtf rule unchanged (each value a
    number above 0, min <= mean <= max)."""
    rc, _carla, d = tsc.run_take(tmp_path / "pc", name=NAME, seed=SEED, float32_step=True)
    assert rc == 0
    out = tmp_path / "recordings" / NAME
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(encode, "load_dbc", lambda contract, path=None: tsc.FakeDb())
        mp.setattr(encode, "read_log", tsc.fake_read_log)
        res = encode.record(d, out, NAME, contract=C)
    assert res["recorded"] is True and res["verify"]["ok"] is True, (res["verify"]["ok_terms"], res["verify"]["problems"])
    line = jload(out / "manifest-line.json")
    assert line["source"]["rtf"] == {"max": 1.0, "mean": 1.0, "min": 1.0}
    assert inj.rtf_problems(line["source"]) == []
    assert inj.read_source(out).line == line


@NEEDS_CONTRACT
@tsc.NEEDS_SIM_VENV
def test_the_two_command_lines_in_the_sim_venv_make_the_same_chain_with_the_real_cantools(take, recording, injected,
                                                                                          tmp_path):
    """encode.py record and inject.py rewrite and check, run as their command lines in the sim venv against the same
    generation, with the real cantools and python-can: each passes, and each log is the in-process stand-ins' byte for
    byte (the stand-ins are exact, so the in-process chain above stands for the real one)."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    env.update(PYTHONDONTWRITEBYTECODE="1", SDV_GEN=str(gen_dir()))

    def run(*args):
        return subprocess.run([str(tsc.SIM_PY)] + [str(a) for a in args], capture_output=True, text=True, env=env,
                              cwd=str(REPO))
    p = run(CARLA_DIR / "encode.py", "record", "--take", take.dir, "--name", NAME, "--root", tmp_path / "recs")
    assert p.returncode == 0, p.stderr[-3000:]
    out = tmp_path / "recs" / NAME
    ver = json.loads(p.stdout)["verify"]
    assert ver["ok"] is True
    assert ver["judge"]["rule26_above_tol"] == recording.res["verify"]["judge"]["rule26_above_tol"]
    assert (out / "carla.log").read_bytes() == (recording.dir / "carla.log").read_bytes()
    (tmp_path / "inj").mkdir()
    p = run(INJECT_DIR / "inject.py", "rewrite", "--from", out, "--name", INJ_NAME, "--root", tmp_path / "inj",
            "--gen", gen_dir())
    assert p.returncode == 0, p.stderr[-3000:]
    p = run(INJECT_DIR / "inject.py", "check", tmp_path / "inj" / INJ_NAME, "--gen", gen_dir())
    assert p.returncode == 0 and json.loads(p.stdout)["ok"] is True, p.stderr[-3000:]
    assert (tmp_path / "inj" / INJ_NAME / "carla.log").read_bytes() == (injected.dest / "carla.log").read_bytes()


# =================================================================================================================
# The frame set: WP1's writer -> WP9's reader
# =================================================================================================================

@pytest.fixture(scope="module")
def cc():
    """orin-native/edge-llm/camera_client.py loaded by path under a name of its own; the sys.path entry it adds when it
    loads is taken back, and no bytecode is written."""
    saved_path, saved_dwb = list(sys.path), sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("camera_client_p7_contract", str(CAMERA_CLIENT))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_dwb
    return mod


def write_set(root, steps=(0, 20, 40), name=NAME):
    """A set from WP1's writer, each frame the fake camera's synthetic pattern for its frame number, reduced (spec 2.4)."""
    w = frameset.FrameSetWriter(root, name, seed=SEED, stride_steps=capture.STRIDE_STEPS, town=capture.TOWN,
                                blueprint=capture.BLUEPRINT)
    for i in steps:
        w.add(i, 1000 + i, frameset.reduce_bgra(fake.pattern_bgra(1000 + i, frameset.WIDTH, frameset.HEIGHT)))
    w.close(hashlib.sha256(b"a take.sha256 of this test's own\n").hexdigest())
    return w.dir


def listed(doc):
    return [(e["i"], e["file"], e["sha256"]) for e in doc["frames"]]


def read_by_wp9(cc, d):
    return [(f.i, f.file, f.sha256) for f in cc.read_frames(str(d))]


@NEEDS_CONTRACT
def test_the_captures_own_frame_set_is_read_by_the_camera_apps_reader(tmp_path, cc):
    rc, _carla, take_dir = tsc.run_take(tmp_path, name=NAME, seed=SEED, frames="on")
    assert rc == 0
    d = tmp_path / "frames" / NAME
    doc = frameset.read_set(d)
    assert doc["frames"] and read_by_wp9(cc, d) == listed(doc)
    assert all(e["i"] % capture.STRIDE_STEPS == 0 for e in doc["frames"])
    assert doc["take_sha256"] == sha256_of(take_dir / "take.sha256")


def test_a_set_of_synthetic_patterns_from_wp1s_writer_is_read_by_the_camera_apps_reader_in_its_order(tmp_path, cc):
    d = write_set(tmp_path / "frames", steps=(40, 0, 20))
    doc = frameset.read_set(d)
    assert [e["i"] for e in doc["frames"]] == [0, 20, 40]
    assert read_by_wp9(cc, d) == listed(doc)
    assert cc.FRAME_SIDE == frameset.SIZE


def _png(width, height, colour):
    """A PNG of a test's own: 8-bit, not interlaced, filter 0, the given colour type (0 grey, 2 RGB)."""
    channels = {0: 1, 2: 3}[colour]
    rows = b"".join(b"\x00" + bytes((x * 7 + y) % 256 for x in range(width * channels)) for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _edit(d, change):
    doc = jload(d / "frames.json")
    change(doc)
    (d / "frames.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def _replace_png(d, data):
    (d / "frame-000020.png").write_bytes(data)
    _edit(d, lambda doc: doc["frames"][1].update(sha256=hashlib.sha256(data).hexdigest()))


FAULTS = {
    "no-frames-json": lambda d: (d / "frames.json").unlink(),
    "format-2": lambda d: _edit(d, lambda doc: doc.update(format=2)),
    "simulated-missing": lambda d: _edit(d, lambda doc: doc.pop("simulated")),
    "simulated-false": lambda d: _edit(d, lambda doc: doc.update(simulated=False)),
    "generator-sigsim": lambda d: _edit(d, lambda doc: doc.update(generator="sigsim")),
    "listed-file-missing": lambda d: (d / "frame-000020.png").unlink(),
    "sha256-another": lambda d: _edit(d, lambda doc: doc["frames"][1].update(sha256=hashlib.sha256(b"another").hexdigest())),
    "unlisted-file": lambda d: (d / "notes.txt").write_text("x\n", encoding="ascii"),
    "png-32x32": lambda d: _replace_png(d, _png(32, 32, 0)),
    "png-rgb": lambda d: _replace_png(d, _png(64, 64, 2)),
    "listed-for-another-step": lambda d: _edit(d, lambda doc: doc["frames"][1].update(i=60)),
    "step-a-string": lambda d: _edit(d, lambda doc: doc["frames"][1].update(i="20")),
    "step-a-bool": lambda d: _edit(d, lambda doc: doc["frames"][0].update(i=False)),
}


@pytest.mark.parametrize("fault", sorted(FAULTS) + ["inside-a-work-tree"])
def test_the_two_readers_refuse_the_same_sets(tmp_path, cc, fault):
    """Spec 2.4's refusals, a file listed for another step than its name says, and a step index that is not an integer
    (WP1's reader's added rule): WP1's reader and WP9's both refuse each; neither takes one of these sets."""
    if fault == "inside-a-work-tree":
        (tmp_path / "tree" / ".git").mkdir(parents=True)
        d = tmp_path / "tree" / "frames" / NAME
        d.parent.mkdir()
        shutil.copytree(write_set(tmp_path / "frames"), d)
    else:
        d = write_set(tmp_path / "frames")
        frameset.read_set(d)
        cc.read_frames(str(d))
        FAULTS[fault](d)
    with pytest.raises(frameset.FrameSetError):
        frameset.read_set(d)
    with pytest.raises(cc.FramesRefused):
        cc.read_frames(str(d))


@NEEDS_CONTRACT
def test_a_take_whose_every_image_was_lost_writes_a_set_the_camera_apps_reader_refuses(tmp_path, cc):
    """No image reached the capture: it logs every wanted step as missing and writes a set with no frame; WP9's reader
    refuses that set ('no frames listed'), so the dry run of section 9 cannot pass over it."""
    rc, _carla, take_dir = tsc.run_take(tmp_path, name=NAME, seed=SEED, frames="on", drop_images=set(range(10_000)))
    cap = tsc.read_capture(take_dir)
    d = tmp_path / "frames" / NAME
    assert jload(d / "frames.json")["frames"] == [] and cap["camera"]["frames_written"] == 0
    assert cap["camera"]["frames_missing"] and all(i % capture.STRIDE_STEPS == 0 for i in cap["camera"]["frames_missing"])
    with pytest.raises(cc.FramesRefused, match="no frames listed"):
        cc.read_frames(str(d))


# =================================================================================================================
# The names: the capture's and the encoder's constants are the generation's
# =================================================================================================================

def _modules():
    return sorted(CARLA_DIR.glob("*.py")) + [REPO / "sdv" / "sim" / "carla_iso.py"]


@NEEDS_CONTRACT
def test_every_name_sdv_carla_reads_from_a_contract_is_the_generations_and_none_is_a_literal_there():
    reads, bound = set(), {}
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("c", "contract")
                    and node.attr.isupper()):
                reads.add(node.attr)
        for stmt in tree.body:
            targets = list(stmt.targets) if isinstance(stmt, ast.Assign) else []
            if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
                targets.append(stmt.target)
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        bound.setdefault(n.id, []).append(path.name)
    assert set(CONTRACT_NAMES) <= reads, sorted(set(CONTRACT_NAMES) - reads)
    assert [n for n in sorted(reads) if not hasattr(C, n)] == []
    assert {n: bound[n] for n in sorted(reads) if n in bound} == {}


@NEEDS_CONTRACT
def test_the_send_policy_takes_each_value_from_its_own_generated_name():
    """A contract whose names all carry values of their own: the policy's step, pacing interval, repeat cap, dynamics
    message (RULE26_DBC_MESSAGE, not another slot's), gear message (the gear slot's) and the two periods each follow
    their own name (in the generation the step and the interval are equal, so only a contract like this tells them
    apart)."""
    ns = contract_copy(CARLA_STEP_MS=41, FEEDER_PACING_INTERVAL_MS=43, FEEDER_REPEAT_CAP_MS=47,
                       RULE26_DBC_MESSAGE="Rule26Msg", SLOT_DBC_MESSAGES=("Slot0Msg", "Slot1Msg", "Slot2Msg", "Slot3Msg", "GearMsg"),
                       DBC_PERIOD_MS={"Rule26Msg": 23, "GearMsg": 59, "Slot0Msg": 29})
    want = sendpolicy.Policy(step_ms=41, interval_ms=43, cap_ms=47, dyn_msg="Rule26Msg", gear_msg="GearMsg", dyn_period_ms=23,
                             gear_period_ms=59)
    assert sendpolicy.Policy.from_contract(ns) == want


@NEEDS_CONTRACT
def test_a_take_ties_its_world_and_paces_by_the_generations_names(tmp_path):
    """The capture handed a contract whose step and pacing interval differ from each other and from the generation's: the
    world is tied to that CARLA_STEP_MS (read back), each step advances the simulation by it, and each step becomes
    current one FEEDER_PACING_INTERVAL_MS after the previous (the fake simulator takes no wall time per tick)."""
    step_ms, interval_ms = C.CARLA_STEP_MS - 10, C.CARLA_STEP_MS - 5
    ns = contract_copy(CARLA_STEP_MS=step_ms, FEEDER_PACING_INTERVAL_MS=interval_ms)
    rc, _carla, d = tsc.run_take(tmp_path, name=NAME, seed=SEED, contract=ns)
    assert rc == 0
    ws, steps = tsc.read_capture(d)["world_settings"], tsc.read_steps(d)
    assert worldtie.tie_problems(ws, step_ms / 1000.0) == []
    assert worldtie.tie_problems(ws, C.CARLA_STEP_MS / 1000.0) != []
    pairs = list(zip(steps, steps[1:]))
    assert {sendpolicy.sim_advance_ns(a["elapsed_s"], b["elapsed_s"]) for a, b in pairs} == {step_ms * MS}
    assert {b["t_cur_ns"] - a["t_cur_ns"] for a, b in pairs} == {interval_ms * MS}


@NEEDS_CONTRACT
def test_the_rtf_counts_in_steps_of_the_generated_step_not_the_pacing_interval(tmp_path):
    """A contract whose step and pacing interval differ (40 and 45 ms), the fake simulator keeping its step in single
    precision: float32(0.04) is short of the step, so in whole ns each advance reads under it, and a count in steps of
    the pacing interval would leave it so. Counted in steps of CARLA_STEP_MS every value of the rtf is exactly step /
    interval."""
    step_ms, interval_ms = C.CARLA_STEP_MS - 10, C.CARLA_STEP_MS - 5
    ns = contract_copy(CARLA_STEP_MS=step_ms, FEEDER_PACING_INTERVAL_MS=interval_ms)
    rc, _carla, d = tsc.run_take(tmp_path, name=NAME, seed=SEED, contract=ns, float32_step=True)
    assert rc == 0
    steps = tsc.read_steps(d)
    pairs = list(zip(steps, steps[1:]))
    assert all(sendpolicy.sim_advance_ns(a["elapsed_s"], b["elapsed_s"]) < step_ms * MS for a, b in pairs)   # the premise
    assert {b["t_cur_ns"] - a["t_cur_ns"] for a, b in pairs} == {interval_ms * MS}
    want = step_ms / interval_ms
    assert tsc.read_capture(d)["rtf"] == {"min": want, "mean": want, "max": want}


# =================================================================================================================
# The image's build: make -n -B vss-carla against this tree's vss_profiles.h
# =================================================================================================================

def run_make(*args):
    make = shutil.which("make")
    if make is None or os.name != "posix":
        pytest.skip("needs GNU make (WSL)")
    drop = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "VSS_GEN", "VSS_CARLA_GEN", "CC")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    p = subprocess.run([make, "--no-print-directory", *args], cwd=str(MON_DIR), capture_output=True, text=True, env=env)
    return p.returncode, [ln for ln in p.stdout.splitlines() if ln.strip()], p.stderr


def profile_rows(header):
    """{id: [the X() row's ten values]} of a vss_profiles.h in the generator's form."""
    rows = {}
    for ln in header.splitlines():
        m = re.fullmatch(r"\s*X\((.*)\)\s*\\?\s*", ln)
        if m:
            vals = [float(x.strip().rstrip("u")) for x in m.group(1).split(",")]
            rows[int(vals[0])] = vals
    return rows


needs_make_gen = pytest.mark.skipif(not (MAKE_GEN / "vss_contract.py").is_file(), reason="needs this tree's sdv-out/gen")


@needs_make_gen
def test_make_vss_carla_plans_the_vss_line_against_this_trees_vss_profiles_h():
    """The Makefile's default VSS_CARLA_GEN is this tree's generation, whose vss_profiles.h holds profile 3's row as the
    guard reads it (the whole word X(3u,) with the contract's values: `make -n -B vss-carla` plans exactly the vss line
    with the carla binary's name, says nothing on stderr and writes nothing."""
    con = vf.load_contract(MAKE_GEN)
    pid, row = carla_profile(con)
    header = (MAKE_GEN / "vss_profiles.h").read_text(encoding="ascii")
    assert "X(%du," % pid in header.split()
    assert profile_rows(header)[pid] == [pid, row["l_mm"], row["v_max"], row["a_max"], row["delta_max"], row["v26_lo"],
                                         row["v26_hi"], row["ay26_max"] or 0.0, row["tol26"], row["v_tol"]]
    before = sorted(p.name for p in MON_DIR.iterdir())
    rc, vss, err = run_make("-n", "-B", "vss")
    assert rc == 0 and err == "" and len(vss) == 1, (rc, vss, err)
    assert " -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I../../sdv-out/gen -o %s " % VSS_BIN in vss[0]
    rc, carla, err = run_make("-n", "-B", "vss-carla")
    assert rc == 0 and err == "", (rc, carla, err)
    assert carla == [vss[0].replace(" -o %s " % VSS_BIN, " -o %s " % CARLA_BIN)]
    assert sorted(p.name for p in MON_DIR.iterdir()) == before


@needs_make_gen
def test_make_vss_carla_stops_for_a_generation_without_profile_3(tmp_path):
    """VSS_CARLA_GEN at a copy of this generation's two headers with profile 3's row taken out (a profile-1-and-2
    table, as the base tree generated): make stops before any compile line with the guard's message."""
    pid, _row = carla_profile(vf.load_contract(MAKE_GEN))
    gen = tmp_path / "gen"
    gen.mkdir()
    shutil.copy2(MAKE_GEN / "vss_contract.h", gen / "vss_contract.h")
    lines = (MAKE_GEN / "vss_profiles.h").read_text(encoding="ascii").splitlines()
    rows = [ln.strip().rstrip("\\").strip() for ln in lines if ln.lstrip().startswith("X(")]
    kept = [r for r in rows if not r.startswith("X(%du," % pid)]
    assert len(kept) == len(rows) - 1
    first = next(k for k, ln in enumerate(lines) if ln.lstrip().startswith("X("))
    body = ["    %s%s" % (r, " \\" if k < len(kept) - 1 else "") for k, r in enumerate(kept)]
    out = lines[:first] + body + lines[first + len(rows):]
    ids = sorted(profile_rows("\n".join(out)))
    text = "\n".join(out) + "\n"
    text = re.sub(r"#define VSS_PROFILE_COUNT \d+u", "#define VSS_PROFILE_COUNT %du" % len(ids), text)
    text = re.sub(r'#define VSS_PROFILE_IDS "[^"]*"', '#define VSS_PROFILE_IDS "%s"' % " ".join(map(str, ids)), text)
    (gen / "vss_profiles.h").write_text(text, encoding="ascii")
    assert pid not in ids and ids and "X(%du," % pid not in text.split()
    rc, out_lines, err = run_make("-n", "-B", "vss-carla", "VSS_CARLA_GEN=" + str(gen))
    assert rc == 2 and PROFILE3_ERROR in err and str(gen) in err, (rc, out_lines, err)
    assert not any("qcc" in ln for ln in out_lines)


# =================================================================================================================
# The firewall predicate: WP1's fixtures hold every sentence of spec 2.5
# =================================================================================================================

BOTH = ("windows-client", "wsl")
# (an id, the sentence of spec 2.5, the clause its failure prints, the fors that check it, the cases where it fails, the
# cases where it holds). Read from the specification; where fwcheck reads a sentence more strictly (P3's own-rule half)
# the row says so. Each case is WP1's fixture of that name.
# Not rows, since a row is judged with a Traffic Manager by result_lines alone: P4's other arm (--no-tm) and the output
# and exit-code sentence, which the no-TM and output tests below hold on every case.
SPEC_2_5 = [
    ("p1-enabled", "every firewall profile is enabled", "P1", BOTH, ["profile-disabled", "no-profiles"], ["scoped"]),
    ("p1-default", "its default inbound action is Block or NotConfigured", "P1", BOTH, ["profile-default-allow"], ["scoped"]),
    ("p2-tcp", "an enabled inbound Allow rule that names the CARLA exe is TCP", "P2", BOTH, ["udp", "today"],
     ["scoped", "tcp-by-number"]),
    ("p2-exe-case", "the exe is named case-insensitively", "P2", BOTH, ["exe-case"], ["scoped"]),
    ("p2-ports", "with local ports inside 2000-2002", "P2", BOTH, ["port-outside"], ["port-list"]),
    ("p2-alias", "scoped by its interface alias, the WSL adapter's only", "P2", BOTH,
     ["non-wsl-alias", "mixed-alias", "remote-any"], ["scoped"]),
    ("p2-address", "or by every remote address inside that adapter's IPv4 subnet", "P2", BOTH,
     ["address-outside", "address-localsubnet", "ipv6-remote"], ["address-scoped", "address-host-and-range"]),
    ("p2-unbound", "a rule naming no program, service, package or Owner SID whose local ports meet 2000-2002 is judged",
     "P2", BOTH, ["unbound-allow-all", "unbound-tcp-any-port", "unbound-no-service-read"],
     ["unbound-scoped-2000", "unbound-other-port", "unbound-icmp", "store-app-owner", "store-app-package", "service-rule"]),
    ("p2-bypass", "an allow rule with OverrideBlockRules is an Allow rule for P2", "P2", BOTH, ["bypass-open"],
     ["bypass-scoped"]),
    ("p2-block-disabled", "block rules and disabled rules pass", "P2", BOTH, [],
     ["disabled-open", "block-exe", "block-exe-disabled", "outbound-open"]),
    ("p2-other-program", "an Allow on port 2000 for another program fails (spec 11)", "P2", BOTH,
     ["port-2000-other-program", "port-range-overlapping"], ["udp-other-port-not-judged"]),
    ("p2-wsl-down", "with no WSL adapter up a P2 rule passes only by an alias beginning vEthernet (WSL", "P2", BOTH,
     ["address-wsl-down"], ["alias-wsl-down"]),
    ("p4", "a rule naming the client's interpreter is scoped as P2 requires, with port 8000", "P4", BOTH,
     ["interpreter-allow-any", "interpreter-case", "interpreter-udp", "interpreter-other-port", "interpreter-unscoped",
      "interpreter-outside-address", "unbound-tm-port"],
     ["interpreter-scoped-alias", "interpreter-scoped-address", "interpreter-disabled", "interpreter-block"]),
    ("p3-own-rule",
     "at least one of 2.5's own P2 rules (the exe by its path, or an unbound rule) passes P2 (fwcheck's reading of "
     "'exists': a rule that fails P2 admits nothing from WSL)", "P3", ("wsl",),
     ["no-p2-rule", "today", "address-wsl-down", "p3-other-program-only", "p3-exe-copy-only"],
     ["scoped", "address-scoped", "alias-wsl-down", "unbound-scoped-2000", "p3-unbound-only",
      "p3-exe-path-other-case"]),
    ("p3-block", "no enabled Block rule for the exe covers a profile the WSL adapter is in", "P3", ("wsl",),
     ["block-exe", "block-exe-wsl-alias"], ["block-exe-disabled", "bypass-scoped"]),
    ("read", "an enabled inbound allow rule whose filters could not be read fails", "read", BOTH, ["unreadable-filter"],
     ["scoped"]),
]


@pytest.mark.parametrize("sentence,clause,fors,failing,passing", [r[1:] for r in SPEC_2_5], ids=[r[0] for r in SPEC_2_5])
def test_the_firewall_fixtures_hold_each_sentence_of_spec_2_5(sentence, clause, fors, failing, passing):
    for names, fails in ((failing, True), (passing, False)):
        for name in names:
            case = FW_CASES[name]
            for for_ in fors:
                got = fwcheck.result_lines(fwcheck.check(fwcheck.parse(case["doc"]), for_, FW["interpreters"]), for_)
                assert got == case["expect"][for_], (name, for_)
                assert any(": %s: " % clause in ln for ln in got) is fails, (sentence, name, for_, got)


def test_the_table_covers_every_clause_and_windows_client_never_checks_p3():
    assert {r[2] for r in SPEC_2_5} == {"P1", "P2", "P3", "P4", "read"}
    assert all(r[4] or r[0] == "p2-block-disabled" for r in SPEC_2_5) and all(r[5] for r in SPEC_2_5)
    assert [c["name"] for c in FW["cases"] if any(": P3: " in ln for ln in c["expect"]["windows-client"])] == []
    for name in sorted({n for r in SPEC_2_5 if r[2] == "P3" for n in r[4]}):
        assert any(": P3: " in ln for ln in FW_CASES[name]["expect"]["wsl"]), name


def no_tm_lines(lines, for_):
    """A case's lines as spec 2.5's other P4 arm wants them when the client runs no Traffic Manager (--no-tm): its P4
    lines gone, every other line kept in its order, the tag saying P4 was not applied; PASS when nothing is left."""
    tag = "%s, no TM: P4 not applied" % for_
    kept = [ln for ln in lines if ": P4: " not in ln and not ln.startswith("fwcheck: PASS")]
    if not kept:
        return ["fwcheck: PASS (%s)" % tag]
    return [ln.replace("fwcheck: FAIL (%s): " % for_, "fwcheck: FAIL (%s): " % tag, 1) for ln in kept]


@pytest.mark.parametrize("name", sorted(FW_CASES))
def test_without_a_traffic_manager_p4_alone_is_not_applied_on_every_case(name):
    """P4's 'or the client runs no Traffic Manager': with tm false (fwcheck --no-tm) each case gives its own lines
    without the P4 ones, the tag saying so. P1-P3 and the read still fail where they do."""
    case = FW_CASES[name]
    for for_ in BOTH:
        got = fwcheck.result_lines(fwcheck.check(fwcheck.parse(case["doc"]), for_, FW["interpreters"], tm=False), for_,
                                   tm=False)
        assert got == no_tm_lines(case["expect"][for_], for_), (name, for_)


def test_the_no_tm_arm_has_a_case_it_passes_and_one_it_still_fails():
    """The arm's two sides among the fixtures: a case of the table's P4 row that fails P4 alone passes without a Traffic
    Manager, and a rule that fails P2 and P4 (unbound-allow-all: any protocol, port and remote) still fails P2."""
    p4_only = [n for r in SPEC_2_5 if r[0] == "p4" for n in r[4]
               if all(": P4: " in ln for ln in FW_CASES[n]["expect"]["windows-client"])]
    assert p4_only, "no case of the P4 row fails P4 alone"
    for name in p4_only:
        assert no_tm_lines(FW_CASES[name]["expect"]["windows-client"], "windows-client") == \
            ["fwcheck: PASS (windows-client, no TM: P4 not applied)"], name
    both = FW_CASES["unbound-allow-all"]["expect"]["windows-client"]
    assert any(": P4: " in ln for ln in both) and any(": P2: " in ln for ln in both), both
    tag = "fwcheck: FAIL (windows-client, no TM: P4 not applied): P2: "
    assert no_tm_lines(both, "windows-client") == [tag + ln.split(": P2: ", 1)[1] for ln in both if ": P2: " in ln]


FAIL_LINE = re.compile(r"fwcheck: FAIL \((windows-client|wsl)(, no TM: P4 not applied)?\): (P1|P2|P3|P4|read): \S.*")


@pytest.mark.parametrize("name", sorted(FW_CASES))
def test_the_output_is_a_pass_line_or_a_line_per_failing_rule_and_exit_0_only_on_pass(name):
    """Spec 2.5's output sentence on each case through fwcheck.run, main's own path with the read answered by the case's
    JSON: the lines are the case's, one PASS line or one FAIL line per failing rule in the specified form, and the exit
    code is 0 exactly on PASS and 1 on FAIL; the same with --no-tm."""
    case = FW_CASES[name]
    doc = json.dumps(case["doc"])
    for for_ in BOTH:
        for tm in (True, False):
            want = case["expect"][for_] if tm else no_tm_lines(case["expect"][for_], for_)
            rc, lines = fwcheck.run(for_, runner=lambda cmd: (0, doc, ""), tm=tm,
                                    interpreters=lambda: tuple(FW["interpreters"]))
            assert lines == want, (name, for_, tm)
            passed = len(lines) == 1 and lines[0].startswith("fwcheck: PASS (")
            assert rc == (0 if passed else 1), (name, for_, tm, rc)
            assert passed or all(FAIL_LINE.fullmatch(ln) for ln in lines), lines


# =================================================================================================================
# The gate: under SDV_REQUIRE_GEN=1 a tree without its generation fails this file, it does not skip its items
# =================================================================================================================

def test_missing_generation_names_what_this_tree_lacks(tmp_path):
    """The chain, the names and the capture's frame set read the generated contract (C, from SDV_GEN, default
    sdv-out/gen); the make items read the generation the Makefile's VSS_CARLA_GEN names (this tree's sdv-out/gen). Each
    absence is named; with both there, nothing is."""
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "vss_contract.py").write_text("# a stand-in: only its presence is read here\n", encoding="ascii")
    assert missing_generation(types.SimpleNamespace(), gen) is None
    assert str(tmp_path / "absent" / "vss_contract.py") in missing_generation(types.SimpleNamespace(), tmp_path / "absent")
    assert "needs the generated contract" in missing_generation(None, gen)


def _collect(tmp_path, **changes):
    """pytest --collect-only of this file in a child process, SDV_GEN at a directory that does not exist (so the contract
    it loads is None) and the environment changed as given; no bytecode and no cache. (returncode, its output)."""
    drop = ("GIT_DIR", "GIT_WORK_TREE", "PYTEST_ADDOPTS", "SDV_REQUIRE_GEN")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(PYTHONDONTWRITEBYTECODE="1", SDV_GEN=str(tmp_path / "no-such-gen"), **changes)
    p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "-p", "no:cacheprovider",
                        str(Path(__file__).resolve())], cwd=str(REPO), env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_under_sdv_require_gen_a_tree_without_its_generated_contract_fails_this_file_at_collection(tmp_path):
    """The recipe sets SDV_REQUIRE_GEN=1, and tests/twin_gate.py's skip check reads only the twin files and the Monitor
    guard: were this file's items to skip for want of a generated contract, the recipe would end 'ci: ok' with section
    10's gate never run. Under the switch the file fails to collect and names what is missing; a mistyped switch fails
    too (twin_gate's strict reading, 1 or off); without it the items are collected, to skip as before."""
    rc, out = _collect(tmp_path, SDV_REQUIRE_GEN="1")
    assert rc != 0 and "SDV_REQUIRE_GEN=1 and this tree has no generated contract" in out, (rc, out[-3000:])
    assert str(tmp_path / "no-such-gen") in out, out[-3000:]
    rc, out = _collect(tmp_path, SDV_REQUIRE_GEN="yes")
    assert rc != 0 and "SDV_REQUIRE_GEN is 'yes'" in out, (rc, out[-3000:])
    rc, out = _collect(tmp_path)
    assert rc == 0 and re.search(r"\b[0-9]+ tests? collected\b", out), (rc, out[-3000:])
