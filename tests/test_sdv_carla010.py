"""The CARLA 0.10.0 path of sdv/carla (SDV plan Phase 8 WP9b, spec-2 sections 2.9, 10.1 and 10.2):
carla010_iso.py's conventions and steering law, follow010.py's passive take, encode010.py's carla-autoware recording,
gpucheck.py's read and refusals, and fwcheck.py's --carla choice.

No CARLA, GPU, PowerShell or network is used: the follower runs against tests/fixtures/carla010/fake_carla010.py, a
stand-in for the `carla` 0.10.0 client module whose fake clock drives a fake interface that ticks the world; gpucheck and
fwcheck judge documents shaped like their PowerShell reads; the encoder runs in this process against
tests/test_sdv_carla.py's exact stand-ins for cantools' database and python-can's reader, and, where ~/sdv-sim-venv
exists, once end to end in that venv with the real ones. The encoder's profile 5 is bound through a fixture contract:
the generated contract with LIVE_DEFAULT_PROFILE["carla-autoware"] = 5 and a profile 5 row of this file's (spec-2 10.1:
the generated contract's names, profile 5's L), compiled or not; one test holds the real generation to those names.

Every number asserted here is a design value, a value of the generated contract, a value of the fake simulator, or
computed from them, except WP9a's two PROBED constants, held once, in PROBED below: the steering law's C, fitted locally
(the readings are not published), and the taxi's wheelbase, the blueprint's geometry. Takes and recordings are written
under pytest's tmp_path only.
"""
import ast
import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLA_DIR = REPO / "sdv" / "carla"
SIM_DIR = REPO / "sdv" / "sim"
FRAME_DIR = REPO / "sdv" / "frame"
STACK_DIR = REPO / "sdv" / "stack"
FIX = HERE / "fixtures" / "carla010"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"
SIM_VENV = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser()
SIM_PY = SIM_VENV / "bin" / "python"
MS = 1_000_000

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (str(CARLA_DIR), str(SIM_DIR), str(FRAME_DIR), str(STACK_DIR), str(FIX), str(HERE)):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _try(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _by_path(name, path):
    """The command-line tools are loaded by path under names of their own (a generic name may be another tree's)."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


iso = _try("carla010_iso")
fwcheck = _try("fwcheck")
sendpolicy = _try("sendpolicy")
rules = _try("rules")
sigsim = _try("sigsim")
vf = _try("vssframe")
fake = _try("fake_carla010")
tsc = _try("test_sdv_carla")
follow = _by_path("sdv_carla_follow010", CARLA_DIR / "follow010.py")
enc = _by_path("sdv_carla_encode010", CARLA_DIR / "encode010.py")
gpucheck = _by_path("sdv_carla_gpucheck", CARLA_DIR / "gpucheck.py")
sys.dont_write_bytecode = _saved

try:
    GEN = vf.load_contract()
    _WHY = ""
except vf.ContractError as err:
    GEN = None
    _WHY = str(err)
NEEDS_CONTRACT = pytest.mark.skipif(GEN is None, reason="needs the generated contract: %s" % _WHY)
NEEDS_SIM_VENV = pytest.mark.skipif(
    not SIM_PY.exists(),
    reason="needs the sim venv ~/sdv-sim-venv built from sdv/sim/requirements.lock (sdv/sim/README.md; WSL Ubuntu-24.04)")

# WP9a's PROBED constants, each held here and once in its module or in
# profiles.toml: the steering law's C (E9, sdv/sim/carla010_iso.py) and the taxi's wheelbase (E4, profile 5's l_mm).
PROBED = {"C": 60.1, "L_MM": 2940}
NAME = "20261023-carla010-1"
# The fixture contract's profile 5 (spec-2 10.1): the generated names, PROBED's L; every other value is profile 3's
# design value (D7, D8), as spec-2 2.4 has it for profile 5.
FIXTURE_ROW5 = {"id": 5, "source_vehicle": "carla010-taxi", "limit_set": "nominal", "envelope": "carla010", "stand_in": (),
                "l_mm": PROBED["L_MM"], "v_max": 40.0, "a_max": 10.0, "delta_max": 57.0, "v26_lo": 1.0, "v26_hi": 10.0,
                "ay26_max": 2.0, "tol26": 8.0, "v_tol": 1.0, "live_default_for": ("carla-autoware",)}
# Phase 7's 0.9.16 source-byte pins. Publication-only prose edits move their pins together;
# the encoder inputs also remain bound to the historical record checked below.
FROZEN_0916 = {
    "sdv/carla/carla_capture.py": "3559fb6f218a6bb8f355d56ec7651c5428b714a91fe9f5895a2a1f339a53fc44",
    "sdv/carla/encode.py": "72802bcb200c1946debbc08a1e22663867e7e8a1867c105ce88e58281fe03b7b",
    "sdv/carla/sendpolicy.py": "a203279947d27177411c363438cd2c06be59905899c6a06a02122d0d12a669f4",
    "sdv/carla/drive.py": "9aa33e52f943a19c5cc352b11603b62d60aacd9143718e3d4375af4602ffe98b",
    "sdv/carla/worldtie.py": "5dd44b8e06c4201989f7816548ab393da7b797b39155c2bf4f5b2f3e482707d5",
    "sdv/carla/frameset.py": "f50ade7eca528d7e914e84d88727986ac27ede971c07442a17aa21e31c457f4b",
    "sdv/sim/carla_iso.py": "122ae9abe1ae1444a57327f06deb9781eec6a038fb23bebf77149231f91fd8a6",
}
CARLA_HONEST_SUMMARY = Path("~/sdv-recordings/20261019-carla-1/summary.json").expanduser()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_contract(compiled=False, base=None, live_default=5):
    """The generated contract with profile 5 as FIXTURE_ROW5 (compiled or not) and the carla-autoware run type's live
    default (a SimpleNamespace; the generated file is never edited)."""
    c = base if base is not None else GEN
    ns = types.SimpleNamespace(**{k: getattr(c, k) for k in dir(c) if not k.startswith("_")})
    rows = [r for r in c.PROFILES if int(r["id"]) != 5] + [dict(FIXTURE_ROW5, compiled=compiled)]
    ns.PROFILES = tuple(sorted(rows, key=lambda r: r["id"]))
    ids = [i for i in c.COMPILED_PROFILE_IDS if i != 5]
    ns.COMPILED_PROFILE_IDS = tuple(sorted(ids + ([5] if compiled else [])))
    ns.LIVE_DEFAULT_PROFILE = dict(c.LIVE_DEFAULT_PROFILE, **{"carla-autoware": live_default})
    return ns


def no_listener():
    return []


def run_follow(tmp_path, name=NAME, windows=False, fw=None, host=None, listeners=no_listener, contract=None, root=None,
               extra=(), clock=None, **faults):
    """Run `follow010.py take` in this process against a fresh fake simulator. Returns (exit code, fake module, take dir)."""
    carla = fake.make(clock, **faults)
    root = root if root is not None else tmp_path / "takes"
    argv = ["take", "--name", name] + (["--host", host] if host else []) + list(extra)
    rc = follow.main(argv, carla=carla, take_root=root, windows=windows, fwcheck_run=fw, listeners=listeners,
                     clock_ns=carla.clock, sleep=carla.clock.sleep, contract=contract if contract is not None else GEN)
    return rc, carla, root / name


def read_steps(take):
    return [json.loads(ln) for ln in (take / "steps.jsonl").read_text(encoding="ascii").splitlines()]


def read_capture(take):
    return json.loads((take / "capture.json").read_text(encoding="utf-8"))


def policy():
    return sendpolicy.Policy.from_contract(GEN)


def step(v=(5.0, 0.0, 0.0), a=(0.0, 0.0, 0.0), fwd=(1.0, 0.0, 0.0), w=(0.0, 0.0, 0.0), steer=0.0, gear=1, reverse=False):
    """One 0.10.0 steps.jsonl record (CARLA's axes and units) with what the conversion reads."""
    return {"i": 0, "frame": 1, "elapsed_s": 0.0, "t_vals_ns": 0, "t_cur_ns": 0, "seg": "passive", "gear": gear, "v": list(v),
            "a": list(a), "fwd": list(fwd), "w": list(w), "steer": steer, "throttle": 0.0, "brake": 0.0, "reverse": reverse}


# =================================================================================================================
# carla010_iso.py: the conventions, the steering law, C PROBED (spec-2 2.9)
# =================================================================================================================

def _sources():
    files = sorted(CARLA_DIR.glob("*.py")) + sorted(SIM_DIR.glob("*.py"))
    return {f: f.read_text(encoding="utf-8") for f in files}


def test_c_is_wp9a_s_probed_value_assigned_once_under_its_marker_and_held_once_here():
    """C (W9 E9) is assigned exactly once, in carla010_iso.py, right under a PROBED comment that names its fact, and held
    once more in this file's PROBED: a re-read changes those two places and nothing else holds the number."""
    hits = []
    for f, text in _sources().items():
        lines = text.splitlines()
        for k, line in enumerate(lines):
            if re.match(r"^C\s*(?::[^=]*)?=(?!=)", line):
                hits.append((f.name, k, lines))
    assert [h[0] for h in hits] == ["carla010_iso.py"], hits
    _f, k, lines = hits[0]
    block = "\n".join(lines[max(0, k - 4):k])
    assert "PROBED" in block and "E9" in block and "from E4's wheelbase and E8's curvature" in block
    assert iso.C == PROBED["C"]
    for f, text in _sources().items():
        if f.name != "carla010_iso.py":
            assert not re.search(r"(?<![\d.])60\.1(?!\d)", text), f.name
    mine = (HERE / "test_sdv_carla010.py").read_text(encoding="utf-8")
    assert len(re.findall(r"(?<![\d.])60\.1(?!\d)", mine)) == 1


@pytest.mark.parametrize("s", [0.05, 0.1, 0.25, 0.5, 0.8, 1.0])
def test_delta_is_minus_c_s_abs_s_never_linear_and_never_the_max_steer_angle(s):
    """The law (W9 E8, E9): CARLA's effective wheel angle C x s x |s|, positive right, so ISO 8855's delta (positive left)
    is its negative, on either side; never s x max_steer_angle (E10) and never linear in s."""
    right, left = iso.delta_iso_deg(s), iso.delta_iso_deg(-s)
    assert right == pytest.approx(-PROBED["C"] * s * s, rel=1e-12) and right < 0
    assert left == -right
    assert iso.steer_angle_deg(s) == -right
    if s != 1.0:
        assert right != pytest.approx(-PROBED["C"] * s) and right != pytest.approx(-70.0 * s)
    assert iso.delta_iso_deg(0.0) == 0.0


def test_the_law_s_quarter_and_half_points():
    """Half the steer gives a quarter of the angle: the law is not the linear map the interface assumes."""
    assert iso.delta_iso_deg(0.5) == pytest.approx(iso.delta_iso_deg(1.0) / 4, rel=1e-12)
    assert iso.delta_iso_deg(1.0) == pytest.approx(-PROBED["C"], rel=1e-12)


@pytest.mark.parametrize("bad", [1.01, -1.5, float("nan"), float("inf"), True, "0.1", None])
def test_a_steer_outside_minus_one_to_one_or_not_a_number_is_refused(bad):
    with pytest.raises((iso.ConversionError, ValueError, TypeError)):
        iso.delta_iso_deg(bad)


def test_the_yaw_rate_is_the_negated_z_component_in_degrees_per_second_never_x_y_nor_radians():
    """CARLA's angular velocity is deg/s for the actor and the snapshot (W9 E19, E20) and its z positive turning right
    (E17, E18): ISO 8855's yaw rate (positive left) is -w[2], unscaled."""
    assert iso.convert(step(w=(5.0, -7.0, 12.0)))[3] == -12.0
    assert iso.convert(step(w=(0.0, 0.0, -3.5)))[3] == 3.5
    assert iso.yaw_rate_to_iso(12.0) == -12.0


def test_a_right_turn_reads_negative_delta_and_negative_yaw_rate_in_iso_8855():
    """A right turn in CARLA (steer > 0, w[2] > 0, W9 E18): both ISO values negative (positive left)."""
    _v, _a, d, y, _g = iso.convert(step(steer=0.4, w=(0.0, 0.0, 9.0)))
    assert d < 0 and y < 0
    _v, _a, d, y, _g = iso.convert(step(steer=-0.4, w=(0.0, 0.0, -9.0)))
    assert d > 0 and y > 0


def test_speed_and_acceleration_are_the_world_vectors_along_the_forward_vector():
    """World-frame vectors (W9 E21): v . fwd and a . fwd, a reversing car's speed negative, a sideways velocity zero."""
    yaw = math.radians(90.0)
    fwd = (math.cos(yaw), math.sin(yaw), 0.0)
    v, a, _d, _y, _g = iso.convert(step(v=(0.0, 4.0, 0.0), a=(0.0, -1.5, 0.0), fwd=fwd))
    assert v == pytest.approx(4.0) and a == pytest.approx(-1.5)
    v, _a, _d, _y, g = iso.convert(step(v=(-2.0 * fwd[0], -2.0 * fwd[1], 0.0), fwd=fwd, gear=-1, reverse=True))
    assert v == pytest.approx(-2.0) and g == -1
    assert iso.convert(step(v=(3.0, 0.0, 0.0), fwd=fwd))[0] == pytest.approx(0.0, abs=1e-12)


def test_speed_and_acceleration_take_the_vectors_z_on_a_pitched_road():
    """v . fwd and a . fwd are three-dimensional (W9 E21's world-frame vectors): on a pitched road the forward vector and
    the velocity both have a z component, and the speed along the car is the whole vector's."""
    p = math.radians(8.0)
    fwd = (math.cos(p), 0.0, math.sin(p))
    v, a, _d, _y, _g = iso.convert(step(v=(3.0 * fwd[0], 0.0, 3.0 * fwd[2]), a=(-fwd[0], 0.0, -fwd[2]), fwd=fwd))
    assert v == pytest.approx(3.0, rel=1e-12) and a == pytest.approx(-1.0, rel=1e-12)


def test_the_conversion_reads_no_wheel_angle():
    """The commanded steer is the conversion's delta source, so a wheel angle
    beside a step changes nothing of its conversion."""
    s = step(steer=0.3, w=(0.0, 0.0, 4.0))
    assert iso.convert(dict(s, wheel_deg=[33.0, 31.0])) == iso.convert(s)
    assert iso.convert(s)[2] == pytest.approx(-PROBED["C"] * 0.09)


@pytest.mark.parametrize("gear,reverse,ok", [(-1, True, True), (0, False, True), (1, False, True), (2, False, True),
                                             (5, False, True), (-1, False, False), (1, True, False), (0, True, False),
                                             (1, 0, False), (-1, 1, False),
                                             (-2, True, False), (True, False, False), (1.0, False, False)])
def test_the_gear_is_0_9_16_s_rule_reverse_exactly_in_gear_minus_one_with_the_forward_gear_number_kept(gear, reverse, ok):
    """P7s 2.7's rule (reverse set exactly when the gear is -1) on get_control()'s gear; a forward gear number passes as
    slice.dbc's CurrentGear carries it ("positive forward gear number")."""
    if ok:
        assert iso.gear_of(gear, reverse) == gear
    else:
        with pytest.raises(iso.ConversionError):
            iso.gear_of(gear, reverse)


def test_the_curve_s_own_points_follow_the_class_default_s_prefix():
    """The steering curve reads the client class's default points first, then the vehicle's own (W9 E11): the own points
    are what follows that prefix, and a read without it has no own points to tell."""
    assert iso.CURVE_PREFIX == ((0.0, 1.0), (10.0, 0.5)) and iso.FLAT_CURVE == ((0.0, 1.0), (120.0, 1.0))
    read = [[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [120.0, 1.0]]
    assert iso.own_curve_points(read) == ((0.0, 1.0), (120.0, 1.0))
    shipped = [[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [20.0, 0.9], [60.0, 0.8], [120.0, 0.7]]
    assert iso.own_curve_points(shipped) == ((0.0, 1.0), (20.0, 0.9), (60.0, 0.8), (120.0, 0.7))
    with pytest.raises(iso.ConversionError, match="prefix"):
        iso.own_curve_points([[0.0, 1.0], [120.0, 1.0]])


def test_the_conventions_are_named_with_wp9a_s_fact_ids():
    names = {"axes", "steer", "yaw", "angular_velocity_unit", "w_z_turn_sign", "velocity_frame", "wheel_steer_angle",
             "steering_law", "steering_curve"}
    assert set(iso.CONVENTIONS) == names
    for key, (value, status, source) in iso.CONVENTIONS.items():
        assert value and status in ("READ", "LIB", "INFERRED") and re.search(r"\bE\d+\b", source), key
    assert iso.CONVENTIONS["angular_velocity_unit"][0] == "degrees/s"
    assert iso.CONVENTIONS["steering_law"][1] == "INFERRED" and "E9" in iso.CONVENTIONS["steering_law"][2]
    assert iso.CARLA_VERSION == "0.10.0"


def test_carla010_iso_uses_the_standard_library_only_and_is_not_carla_iso():
    mods = set()
    for node in ast.walk(ast.parse((SIM_DIR / "carla010_iso.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert mods and mods <= set(sys.stdlib_module_names) | {"__future__"}, mods
    assert not hasattr(iso, "steer_to_iso_deg") and not hasattr(iso, "wheel_to_iso_deg")


# =================================================================================================================
# follow010.py: the passive take on the fake simulator (spec-2 2.9, 10.1 item 1)
# =================================================================================================================

def test_the_take_s_step_keys_are_phase_7_s_that_exist_on_0_10_0_and_its_files_phase_7_s():
    """Phase 7's keys but wheel_deg, since this conversion uses commanded steer, and Phase 7's three files: one list
    in the follower and the encoder."""
    p7 = tsc.capture.STEP_KEYS
    assert follow.STEP_KEYS == tuple(k for k in p7 if k != "wheel_deg") == enc.STEP_KEYS
    assert follow.TAKE_FILES == tsc.capture.TAKE_FILES == enc.TAKE_FILES


@NEEDS_CONTRACT
def test_a_passive_take_writes_its_four_files_with_exactly_the_specified_keys(tmp_path):
    rc, carla, take = run_follow(tmp_path)
    assert rc == 0, read_capture(take)["errors"]
    assert sorted(p.name for p in take.iterdir()) == ["capture.json", "script.jsonl", "steps.jsonl", "take.sha256"]
    assert (take / "script.jsonl").read_bytes() == b""                      # the follower commands nothing
    steps = read_steps(take)
    assert len(steps) == carla.sim.ticks_planned and all(tuple(s) == follow.STEP_KEYS for s in steps)
    cap = read_capture(take)
    assert tuple(cap) == follow.CAPTURE_KEYS
    assert cap["format"] == 1 and cap["mode"] == "passive" and cap["name"] == NAME
    assert (cap["client_version"], cap["server_version"]) == ("0.10.0", "0.10.0")
    assert (cap["map"], cap["blueprint"], cap["role_name"]) == ("Carla/Maps/Town10HD_Opt", "vehicle.taxi.ford", "ego_vehicle")
    assert cap["tm"] is None and cap["camera"] is None and cap["refused"] is None and cap["errors"] == []
    assert cap["completed"] is True and cap["end"] == "idle" and cap["ego_id"] == carla.sim.ego.id
    assert cap["listeners"] == {"start": [], "end": []}
    assert cap["follow_sha256"] == _sha(CARLA_DIR / "follow010.py")
    sums = "".join("%s  %s\n" % (_sha(take / n), n) for n in ("steps.jsonl", "script.jsonl", "capture.json"))
    assert (take / "take.sha256").read_text(encoding="ascii") == sums


@NEEDS_CONTRACT
def test_each_step_is_one_frame_from_on_tick_with_the_ego_s_raw_readings_and_its_control(tmp_path):
    """One line per frame the interface ticked, in order, frame numbers consecutive; the readings raw (CARLA's axes and
    units, from the ego's getters at that tick); seg "passive"; steer, throttle, brake, reverse and gear from get_control()
    of that tick, the gear the gearbox's (forward gear numbers kept)."""
    rc, carla, take = run_follow(tmp_path)
    steps = read_steps(take)
    assert [s["i"] for s in steps] == list(range(len(steps)))
    first = fake.FAKE_START_FRAME + 1
    assert [s["frame"] for s in steps] == list(range(first, first + len(steps)))
    assert all(s["seg"] == "passive" for s in steps)
    assert steps[0]["elapsed_s"] == pytest.approx(fake.FAKE_START_ELAPSED + 0.05)
    for k in (5, 40, 100, 150):
        want = fake.default_script(k)
        assert steps[k]["steer"] == pytest.approx(want.get("steer", 0.0)) and steps[k]["throttle"] == want.get("throttle", 0.0)
        assert steps[k]["brake"] == want.get("brake", 0.0) and steps[k]["reverse"] is False
    assert {s["gear"] for s in steps} == {0, 1, 2}
    turning = [s for s in steps if abs(s["steer"]) > 0.1]
    assert turning and all((s["w"][2] > 0) == (s["steer"] > 0) for s in turning if abs(s["w"][2]) > 1e-9)   # raw: right is +
    assert "get_wheel_steer_angle" not in carla.sim.calls


@NEEDS_CONTRACT
def test_the_follower_never_makes_a_forbidden_call_and_sets_its_client_timeout_first(tmp_path):
    """It never applies settings, ticks, loads a world, applies physics or a control, sets a velocity, spawns or asks for a
    Traffic Manager (spec-2 10.1 item 1): the fake records each such call before it raises. The client's timeout is set
    explicitly before any other call (W9 S6); the physics control is read once, at attach (W9 E13 concerns the apply)."""
    assert follow.FORBIDDEN == ("apply_settings", "tick", "load_world", "apply_physics_control", "apply_control",
                                "set_target_velocity", "spawn_actor", "get_trafficmanager")
    rc, carla, take = run_follow(tmp_path)
    assert rc == 0
    calls = carla.sim.calls
    assert not set(calls) & set(fake.FORBIDDEN + fake.ALSO_REFUSED), sorted(set(calls) & set(fake.FORBIDDEN + fake.ALSO_REFUSED))
    assert calls[0] == "connect:127.0.0.1:2000" and calls[1] == "set_timeout"
    assert carla.sim.client_timeout == follow.CLIENT_TIMEOUT_S
    assert calls.count("get_physics_control") == 1 and calls.count("on_tick") == 1 and calls.count("remove_on_tick") == 1
    assert calls.index("get_physics_control") < calls.index("on_tick") and carla.sim.callbacks == {}


def test_the_client_timeout_is_the_interface_s_20_seconds_not_a_timeout_that_expires_at_once():
    """The interface's own client timeout (W: I4), held as a value: 20 s."""
    assert follow.CLIENT_TIMEOUT_S == 20.0


@pytest.mark.parametrize("name", ["apply_settings", "tick", "load_world", "apply_physics_control", "apply_control",
                                  "set_target_velocity", "spawn_actor", "get_trafficmanager"])
def test_the_follower_s_source_holds_no_forbidden_call(name):
    """Belt and braces: no forbidden method is even named as a call in the follower's code."""
    tree = ast.parse((CARLA_DIR / "follow010.py").read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert name not in called


ATTACH_REFUSALS = {
    "two-egos": ({"actors": (("vehicle.taxi.ford", "ego_vehicle"), ("vehicle.taxi.ford", "ego_vehicle"))}, "exactly one"),
    "no-ego": ({"actors": (("vehicle.taxi.ford", "hero"),)}, "exactly one"),
    "no-actors": ({"actors": ()}, "exactly one"),
    "ego-not-the-taxi-beside-a-taxi": ({"actors": (("vehicle.lincoln.mkz", "ego_vehicle"), ("vehicle.taxi.ford", "autopilot"))},
                                        "vehicle.taxi.ford"),
    "another-blueprint": ({"actors": (("vehicle.lincoln.mkz", "ego_vehicle"),)}, "vehicle.taxi.ford"),
    "asynchronous": ({"settings": {"synchronous_mode": False}}, "synchronous"),
    "another-step": ({"settings": {"fixed_delta_seconds": 0.1}}, "fixed_delta_seconds"),
    "near-step": ({"settings": {"fixed_delta_seconds": 0.0500001}}, "fixed_delta_seconds"),     # 1e-7 off is not the step
    "no-step": ({"settings": {"fixed_delta_seconds": None}}, "fixed_delta_seconds"),
    "server-version": ({"server_version": "0.9.16"}, "0.10.0"),
    "client-version": ({"client_version": "0.9.16"}, "0.10.0"),
    "shipped-curve": ({"curve": fake.FAKE_SHIPPED if fake else ()}, "flattening"),
    "no-prefix": ({"curve_read": fake.FAKE_FLAT if fake else ()}, "prefix"),
    "round-trip-curve": ({"curve": ((0.0, 1.0), (10.0, 0.5), (0.0, 1.0), (120.0, 1.0))}, "flattening"),     # W9 E13
    "curve-right-ends": ({"curve": ((0.0, 1.0), (60.0, 0.8), (120.0, 1.0))}, "flattening"),
}


@NEEDS_CONTRACT
@pytest.mark.parametrize("what", sorted(ATTACH_REFUSALS))
def test_a_take_refused_at_attach_records_why_and_follows_nothing(tmp_path, what):
    """Spec-2 2.9's refusals at attach: not exactly one actor with the role name, that actor not the taxi, the world not
    synchronous or not at CARLA_STEP_MS / 1000, client or server not 0.10.0, the own curve points not the interface's
    flattening (so the shipped curve's speed attenuation never enters, W9 E12). The take is marked refused with its
    reason, no frame is followed, and nothing is encoded from it."""
    faults, said = ATTACH_REFUSALS[what]
    rc, carla, take = run_follow(tmp_path, **faults)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["refused"] and said in cap["refused"], cap["refused"]
    assert read_steps(take) == [] and "on_tick" not in carla.sim.calls and cap["steps"] == 0
    assert not set(carla.sim.calls) & set(fake.FORBIDDEN + fake.ALSO_REFUSED)


@NEEDS_CONTRACT
def test_a_world_that_leaves_the_tie_before_a_re_read_refuses_the_take_there(tmp_path):
    """At every re-read too (spec-2 2.9): the settings are read every REREAD_FRAMES frames, never applied; a world made
    asynchronous meanwhile (its step unchanged, so no frame shows it) refuses the take at the first re-read after it, with
    the steps up to there kept and the take marked. A step changed meanwhile refuses it at its first frame (below)."""
    rc, carla, take = run_follow(tmp_path, settings_at={follow.REREAD_FRAMES // 2: {"synchronous_mode": False}})
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and "synchronous" in cap["refused"]
    assert len(read_steps(take)) == follow.REREAD_FRAMES
    assert [w["at"] for w in cap["world_settings"]] == ["attach", "reread"]
    assert "apply_settings" not in carla.sim.calls


def test_step_problem_holds_each_frame_to_one_step_by_its_delta_and_by_its_elapsed_advance():
    """A frame is one step when its delta_seconds and its elapsed time since the previous frame are each one
    step by sendpolicy.step_advance_ns (a step kept in single precision, as the server keeps it, still one); either off
    names the frame. The first frame has no previous one, so only its delta is judged."""
    step = 50 * MS
    one = struct.unpack("f", struct.pack("f", 0.05))[0]                  # 0.05 in single precision, read as a double
    assert follow.step_problem(4001, 0.05, 12.55, None, step) is None
    assert follow.step_problem(4002, one, 12.5 + 2 * one, 12.5 + one, step) is None
    assert "4003's delta_seconds" in follow.step_problem(4003, 0.02, 12.6, 12.55, step)
    assert "frame 4004 advances the simulation 20000000 ns" in follow.step_problem(4004, 0.05, 18.52, 18.5, step)
    assert "frame 4005 advances the simulation 100000000 ns" in follow.step_problem(4005, 0.05, 18.6, 18.5, step)
    assert follow.step_problem(4006, 0.05, 18.52, None, step) is None


@NEEDS_CONTRACT
@pytest.mark.parametrize("at", [0, 30])
def test_a_frame_that_is_not_one_step_of_simulation_refuses_the_take_at_that_frame(tmp_path, at):
    """Each frame's simulation advance is one step of CARLA_STEP_MS (sendpolicy.step_advance_ns): its own
    delta_seconds, and its elapsed time since the previous frame. A world whose step changed refuses the take at the first
    frame of the new step, the first frame of the take included, not at the next re-read."""
    rc, carla, take = run_follow(tmp_path, settings_at={at: {"fixed_delta_seconds": 0.02}})
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and "not one step" in cap["refused"], cap["refused"]
    assert "frame %d" % (fake.FAKE_START_FRAME + at + 1) in cap["refused"]
    assert len(read_steps(take)) == at and [w["at"] for w in cap["world_settings"]] == ["attach"]


@NEEDS_CONTRACT
def test_a_world_made_asynchronous_after_the_last_re_read_refuses_the_take_at_its_end_read(tmp_path):
    """The frames after the last periodic re-read are covered by the settings read the take ends with, judged as
    every other read: a world made asynchronous at frame 210 of 240 (its step unchanged, so no frame shows it) refuses the
    take there, every frame kept."""
    rc, carla, take = run_follow(tmp_path, ticks=240, settings_at={210: {"synchronous_mode": False}})
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["end"] == "idle", cap["refused"]
    assert "at the end, after frame %d" % (fake.FAKE_START_FRAME + 240) in cap["refused"] and "synchronous" in cap["refused"]
    assert [w["at"] for w in cap["world_settings"]] == ["attach", "reread", "end"] and len(read_steps(take)) == 240
    assert "apply_settings" not in carla.sim.calls


@NEEDS_CONTRACT
def test_the_world_settings_are_read_at_attach_every_reread_frames_and_at_the_end_and_the_substep_is_recorded(tmp_path):
    """The six settings as read (worldtie.READ_BACK), at attach, after every REREAD_FRAMES frames and once more when the
    take ends (after its last frame); the substep is a record, never a refusal (W9 E30), whatever it is."""
    rc, carla, take = run_follow(tmp_path, ticks=2 * follow.REREAD_FRAMES + 3,
                                 settings={"max_substep_delta_time": 0.002, "max_substeps": 25})
    cap = read_capture(take)
    assert rc == 0 and cap["refused"] is None
    ws = cap["world_settings"]
    assert [w["at"] for w in ws] == ["attach", "reread", "reread", "end"]
    assert [w["after_frame"] for w in ws] == [None, fake.FAKE_START_FRAME + follow.REREAD_FRAMES,
                                              fake.FAKE_START_FRAME + 2 * follow.REREAD_FRAMES,
                                              fake.FAKE_START_FRAME + 2 * follow.REREAD_FRAMES + 3]
    assert all(tuple(w["settings"]) == tsc.worldtie.READ_BACK for w in ws)
    assert follow.ENDS == ("ego-gone", "idle", "max-frames")
    assert ws[0]["settings"] == {"synchronous_mode": True, "fixed_delta_seconds": 0.05, "no_rendering_mode": False,
                                 "substepping": True, "max_substep_delta_time": 0.002, "max_substeps": 25}


@NEEDS_CONTRACT
def test_a_frame_that_is_not_the_previous_plus_one_refuses_the_take(tmp_path):
    rc, carla, take = run_follow(tmp_path, frame_jump_at=30)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and "not the previous plus one" in cap["refused"]
    assert len(read_steps(take)) == 30


@NEEDS_CONTRACT
@pytest.mark.parametrize("when", ["start", "end"])
def test_a_listening_socket_of_the_client_s_at_start_or_end_refuses_the_take(tmp_path, when):
    """No Traffic Manager (W9 S10): the client's own listening sockets read at the take's start and end; one at either
    refuses the take."""
    reads = []

    def listeners():
        reads.append(1)
        return [{"LocalAddress": "0.0.0.0", "LocalPort": 8000}] if (len(reads) == 1) == (when == "start") else []
    rc, carla, take = run_follow(tmp_path, listeners=listeners)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and "listens" in cap["refused"] and len(reads) == 2
    assert cap["listeners"][when] == ["0.0.0.0:8000"]
    assert (read_steps(take) == []) is (when == "start")


@NEEDS_CONTRACT
def test_a_listener_read_that_fails_refuses_the_take(tmp_path):
    def broken():
        raise OSError("the read failed")
    rc, carla, take = run_follow(tmp_path, listeners=broken)
    cap = read_capture(take)
    assert rc == 1 and "could not be read" in cap["refused"] and read_steps(take) == []


def test_own_listeners_reads_every_listener_and_keeps_this_process_s_and_a_failed_read_is_never_none():
    """`Get-NetTCPConnection -OwningProcess <pid>` writes an error, and powershell.exe exits 1, when the process has
    no listening socket -- the honest case -- so the follower reads every listener and keeps its own pid's with
    Where-Object. The cmdlet stops on an error, so a read that fails exits non-zero and is refused, never read as
    "none" (an unfiltered listener read writes no error on a host that listens anywhere). The answer: no output is none,
    one object (ConvertTo-Json's form for a list of one) a list of it, a list itself; an exit code other than 0 an
    OSError."""
    ps = follow.LISTENERS_PS
    assert "-OwningProcess" not in ps and "SilentlyContinue" not in ps
    assert ps.startswith("Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.OwningProcess -eq %d } | ")
    seen = []

    def answer(rc, out, err=""):
        def run(cmd):
            seen.append(cmd)
            return rc, out, err
        return run
    one = {"LocalAddress": "127.0.0.1", "LocalPort": 50123}
    two = [one, {"LocalAddress": "::", "LocalPort": 50124}]
    assert follow.own_listeners(answer(0, "")) == [] and follow.own_listeners(answer(0, "\r\n")) == []
    assert follow.own_listeners(answer(0, json.dumps(one))) == [one]
    assert follow.own_listeners(answer(0, json.dumps(two))) == two
    with pytest.raises(OSError, match="Access is denied"):
        follow.own_listeners(answer(1, "", "Get-NetTCPConnection : Access is denied."))
    assert all(cmd == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps % os.getpid()] for cmd in seen)
    assert len(seen) == 5


@NEEDS_CONTRACT
def test_a_ctrl_c_during_the_end_listener_read_still_writes_the_record_and_exits_130(tmp_path):
    """The end listener read (a PowerShell run) is in the take's cleanup; a Ctrl-C there is recorded, and
    capture.json and take.sha256 are still written, so the take is whole and marked, not a directory that blocks its name."""
    reads = []

    def listeners():
        reads.append(1)
        if len(reads) == 2:
            raise KeyboardInterrupt
        return []
    try:
        rc, carla, take = run_follow(tmp_path, listeners=listeners)
    except KeyboardInterrupt:
        pytest.fail("a Ctrl-C during the end listener read propagated out of follow010.main")
    cap = read_capture(take)
    assert rc == 130 and cap["completed"] is False and len(reads) == 2 and cap["refused"] is None
    assert cap["errors"] == ["KeyboardInterrupt: during the end listener read"]
    assert cap["listeners"] == {"start": [], "end": "not read: interrupted"}
    sums = "".join("%s  %s\n" % (_sha(take / n), n) for n in ("steps.jsonl", "script.jsonl", "capture.json"))
    assert (take / "take.sha256").read_text(encoding="ascii") == sums and carla.sim.callbacks == {}


@NEEDS_CONTRACT
def test_a_failure_inside_the_tick_callback_is_an_error_and_the_take_is_not_completed(tmp_path, monkeypatch):
    """A getter that fails while the tick callback reads a frame ends the take as an error (recorded, exit 1), never as a
    take that went idle after its last good frame: a truncated take is not completed, so nothing is encoded from it."""
    carla = fake.make()
    real = fake.Vehicle.get_control

    def flaky(self):
        if carla.sim.ticks > 60:
            raise RuntimeError("fake: the control could not be read")
        return real(self)
    monkeypatch.setattr(fake.Vehicle, "get_control", flaky)
    rc = follow.main(["take", "--name", NAME], carla=carla, take_root=tmp_path / "takes", windows=False, listeners=no_listener,
                     clock_ns=carla.clock, sleep=carla.clock.sleep, contract=GEN)
    cap = read_capture(tmp_path / "takes" / NAME)
    assert rc == 1 and cap["completed"] is False and cap["refused"] is None
    assert any("tick callback failed" in e and "could not be read" in e for e in cap["errors"]), cap["errors"]
    assert len(read_steps(tmp_path / "takes" / NAME)) == 60


@NEEDS_CONTRACT
def test_off_windows_with_no_listener_reader_the_check_is_recorded_as_not_run(tmp_path):
    rc, carla, take = run_follow(tmp_path, listeners=None)
    assert rc == 0 and read_capture(take)["listeners"] == {"start": "not run: not Windows", "end": "not run: not Windows"}


@NEEDS_CONTRACT
def test_on_windows_the_take_reads_its_own_listeners_at_the_start_and_at_the_end(tmp_path, monkeypatch):
    """main wires follow010.own_listeners as the reader on Windows when none is given (every other test injects
    one): wiring none would record "not run" and the encoder would refuse every real take."""
    calls = []
    monkeypatch.setattr(follow, "own_listeners", lambda runner=None: calls.append(1) or [])
    carla = fake.make()
    rc = follow.main(["take", "--name", NAME], carla=carla, take_root=tmp_path / "takes", windows=True,
                     fwcheck_run=lambda: (0, ["fwcheck: PASS (windows-client, CARLA 0.10.0)"]), clock_ns=carla.clock,
                     sleep=carla.clock.sleep, contract=GEN)
    assert rc == 0 and calls == [1, 1]
    assert read_capture(tmp_path / "takes" / NAME)["listeners"] == {"start": [], "end": []}


@NEEDS_CONTRACT
def test_a_frame_whose_elapsed_time_jumps_with_its_delta_one_step_refuses_the_take_at_that_frame(tmp_path):
    """The take's loop holds each frame's elapsed advance, not only its delta_seconds, to one step (step_problem's second
    check, wired with the previous frame's elapsed time)."""
    sims = []

    def script(k):
        if k == 30:
            sims[0].elapsed += 0.05
        return fake.default_script(k)
    carla = fake.make(script=script)
    sims.append(carla.sim)
    rc = follow.main(["take", "--name", NAME], carla=carla, take_root=tmp_path / "takes", windows=False, listeners=no_listener,
                     clock_ns=carla.clock, sleep=carla.clock.sleep, contract=GEN)
    cap = read_capture(tmp_path / "takes" / NAME)
    assert rc == 1 and "frame %d advances the simulation" % (fake.FAKE_START_FRAME + 31) in cap["refused"], cap["refused"]
    assert len(read_steps(tmp_path / "takes" / NAME)) == 30


@NEEDS_CONTRACT
def test_max_frames_below_one_is_refused_before_connecting(tmp_path):
    carla = fake.make()
    with pytest.raises(SystemExit):
        follow.main(["take", "--name", NAME, "--max-frames", "0"], carla=carla, take_root=tmp_path / "takes", windows=False,
                    listeners=no_listener, clock_ns=carla.clock, sleep=carla.clock.sleep, contract=GEN)
    assert carla.sim.calls == [] and not (tmp_path / "takes").exists()


@NEEDS_CONTRACT
def test_the_physics_read_holds_each_wheel_s_max_steer_angle_the_curve_as_read_and_the_own_points(tmp_path):
    rc, carla, take = run_follow(tmp_path)
    assert read_capture(take)["physics_read"] == {
        "max_steer_angle": [70.0, 70.0, 0.0, 0.0],
        "steering_curve": [[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [120.0, 1.0]],
        "own_points": [[0.0, 1.0], [120.0, 1.0]]}


@NEEDS_CONTRACT
def test_the_take_ends_when_the_ego_is_gone_and_keeps_every_frame_it_was_in(tmp_path):
    rc, carla, take = run_follow(tmp_path, ego_gone_at=77)
    cap = read_capture(take)
    assert rc == 0 and cap["end"] == "ego-gone" and cap["completed"] is True and len(read_steps(take)) == 77


@NEEDS_CONTRACT
def test_the_take_ends_after_max_frames(tmp_path):
    rc, carla, take = run_follow(tmp_path, extra=("--max-frames", "25"))
    cap = read_capture(take)
    assert rc == 0 and cap["end"] == "max-frames" and len(read_steps(take)) == 25 and cap["steps"] == 25


@NEEDS_CONTRACT
def test_the_take_ends_idle_only_after_idle_timeout_s_without_a_frame(tmp_path):
    """After the interface's last tick the follower waits IDLE_TIMEOUT_S of its clock before it ends the take (idle)."""
    rc, carla, take = run_follow(tmp_path, ticks=40)
    assert rc == 0 and read_capture(take)["end"] == "idle"
    last_tick = carla.clock.now
    assert len(read_steps(take)) == 40
    start = 7_000 * MS
    assert last_tick - (start + 40 * fake.TICK_WALL_NS) >= follow.IDLE_TIMEOUT_S * 1e9


@NEEDS_CONTRACT
def test_no_tick_at_all_is_an_error_not_a_take(tmp_path):
    rc, carla, take = run_follow(tmp_path, ticks=0)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["errors"] and read_steps(take) == []


@NEEDS_CONTRACT
def test_a_ctrl_c_ends_the_take_with_130_and_writes_its_record(tmp_path):
    rc, carla, take = run_follow(tmp_path, interrupt_at=50)
    cap = read_capture(take)
    assert rc == 130 and cap["completed"] is False and "KeyboardInterrupt" in cap["errors"][0]
    assert (take / "take.sha256").is_file() and carla.sim.callbacks == {}


@NEEDS_CONTRACT
def test_a_read_that_fails_at_attach_is_an_error_recorded(tmp_path):
    rc, carla, take = run_follow(tmp_path, physics_raises=True)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["errors"] and cap["refused"] is None


@NEEDS_CONTRACT
def test_a_step_becomes_current_by_the_send_policy_without_pacing_the_world(tmp_path):
    """The follower ticks nothing, so it paces nothing: each step's t_cur is sendpolicy.became_current of its t_vals (the
    moment the follower read it in its callback) and the previous step's t_cur, as a live sender would send it. An
    interface faster than real time leaves t_cur one interval apart and behind t_vals; a slower one leaves gaps, which the
    take records and the encoder refuses."""
    rc, carla, take = run_follow(tmp_path, ticks=60, tick_wall_ns=lambda k: 30 * MS)
    steps = read_steps(take)
    iv = policy().interval_ns
    assert steps[0]["t_cur_ns"] == steps[0]["t_vals_ns"] == 0
    assert all(b["t_cur_ns"] - a["t_cur_ns"] == iv for a, b in zip(steps, steps[1:]))
    assert all(b["t_vals_ns"] - a["t_vals_ns"] == 30 * MS for a, b in zip(steps, steps[1:]))
    cap = read_capture(take)
    assert cap["gaps"] == [] and cap["rtf"] == {"min": 1.0, "mean": 1.0, "max": 1.0}
    rc, carla, take = run_follow(tmp_path / "slow", ticks=60, tick_wall_ns=lambda k: 80 * MS if k == 20 else 50 * MS)
    cap = read_capture(take)
    assert rc == 0 and cap["gaps"] == [20] and cap["rtf"]["min"] < 1


@NEEDS_CONTRACT
def test_capture_json_s_summary_is_sendpolicy_s_over_the_steps(tmp_path):
    rc, carla, take = run_follow(tmp_path)
    steps, cap, pol = read_steps(take), read_capture(take), policy()
    el, cur, frames = [s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps], [s["frame"] for s in steps]
    assert cap["steps"] == len(steps) and cap["segments"] == [["passive", 0, len(steps) - 1]]
    assert cap["rtf"] == sendpolicy.rtf_summary(el, cur, pol.step_ns)
    assert cap["sim_s"] == sum(sendpolicy.advances_ns(el, pol.step_ns)) / sendpolicy.NS_PER_S
    assert cap["gaps"] == sendpolicy.gaps(frames, cur, pol.cap_ns) == [] and cap["skipped_frames"] == []


@pytest.mark.parametrize("bad", ["20261023-carla-1", "20261023-carla010-", "20261323-carla010-1", "20261023-carla010-01",
                                 "20261023-CARLA010-1", "20261023-carla010-1_", "20261023-carla010-1abcdefghi", "x"])
def test_a_take_name_that_is_not_date_carla010_n_suffix_is_refused(bad):
    assert follow.name_problem(bad) and enc.name_problem(bad)


@pytest.mark.parametrize("good", ["20261023-carla010-1", "20261023-carla010-12b", "20270101-carla010-0"])
def test_a_0_10_0_name_is_one_phase_7_s_pattern_never_matches(good):
    """A 0.10.0 take is never read as a 0.9.16 one: Phase 7's NAME_RE (the capture's and the encoder's) cannot match a
    0.10.0 name, and no Phase 7 name is a 0.10.0 one (spec-2 2.9)."""
    assert follow.name_problem(good) is None and enc.name_problem(good) is None
    assert tsc.capture.NAME_RE.fullmatch(good) is None and tsc.encode.NAME_RE.fullmatch(good) is None
    assert follow.NAME_RE.fullmatch("20261017-carla-7") is None and enc.NAME_RE.fullmatch("20261017-carla-7") is None


@NEEDS_CONTRACT
def test_preflight_refusals_touch_nothing_before_connecting(tmp_path, monkeypatch):
    """A bad name, an existing take directory, one inside a work tree, on Windows a host other than 127.0.0.1 or an fwcheck
    that does not pass, and no generated contract: exit 2, nothing written, no call to the simulator."""
    cases = [dict(name="20261023-carla-1"), dict(host="192.0.2.10", windows=True, fw=lambda: (0, ["fwcheck: PASS (x)"])),
             dict(windows=True, fw=lambda: (1, ["fwcheck: FAIL (windows-client, CARLA 0.10.0): P2: x"]))]
    for k, kw in enumerate(cases):
        rc, carla, take = run_follow(tmp_path / str(k), **kw)
        assert rc == 2 and carla.sim.calls == [] and not take.exists(), kw
    (tmp_path / "e" / "takes" / NAME).mkdir(parents=True)
    rc, carla, _t = run_follow(tmp_path / "e")
    assert rc == 2 and carla.sim.calls == []
    tree = tmp_path / "tree"
    (tree / ".git").mkdir(parents=True)
    rc, carla, _t = run_follow(tmp_path, root=tree / "takes")
    assert rc == 2 and carla.sim.calls == []

    def nope():
        raise vf.ContractError("no generated contract at /nowhere")
    monkeypatch.setattr(follow, "load_contract", nope)
    carla = fake.make()
    rc = follow.main(["take", "--name", NAME], carla=carla, take_root=tmp_path / "nc", windows=False, listeners=no_listener,
                     clock_ns=carla.clock, sleep=carla.clock.sleep)
    assert rc == 2 and carla.sim.calls == []


@NEEDS_CONTRACT
def test_on_windows_the_take_runs_fwcheck_for_the_0_10_0_exe_and_records_its_line(tmp_path, monkeypatch):
    seen = []

    def fake_run(for_, runner=None, tm=True, interpreters=None, carla=fwcheck.CARLA_DEFAULT):
        seen.append((for_, tm, carla))
        return 0, ["fwcheck: PASS (windows-client, CARLA 0.10.0)"]
    monkeypatch.setattr(fwcheck, "run", fake_run)
    rc, carla, take = run_follow(tmp_path, windows=True)
    assert rc == 0 and seen == [("windows-client", True, "0.10.0")]
    assert read_capture(take)["fwcheck"] == "fwcheck: PASS (windows-client, CARLA 0.10.0)"


def test_the_follower_s_fwcheck_command_is_fwcheck_s_with_carla_0_10_0(monkeypatch):
    seen = []
    monkeypatch.setattr(fwcheck, "main", lambda argv, windows=None, **k: seen.append((list(argv), windows)) or 0)
    assert follow.main(["fwcheck", "--for", "wsl", "--no-tm"], windows=True) == 0
    assert follow.main(["fwcheck", "--for", "windows-client"], windows=True) == 0
    assert seen == [(["--for", "wsl", "--carla", "0.10.0", "--no-tm"], True), (["--for", "windows-client", "--carla", "0.10.0"], True)]


def test_the_follower_imports_without_carla_and_uses_the_standard_library_and_its_own_package_only():
    src = (CARLA_DIR / "follow010.py").read_text(encoding="utf-8")
    assert not re.search(r"^(import carla|from carla)\b", src, re.M)
    assert follow is not None and "carla" not in vars(follow)
    allowed = set(sys.stdlib_module_names) | {"__future__", "sendpolicy", "fwcheck", "frameset", "worldtie", "vssframe",
                                              "carla010_iso"}
    for path in (CARLA_DIR / "follow010.py", CARLA_DIR / "gpucheck.py"):
        mods = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        assert mods and mods <= allowed, (path.name, mods - allowed)


def test_the_0_10_0_constants_are_wp9a_s_reads():
    """W9 S4, S11, S12, W5 and the interface's defaults (W: I4): the level, the taxi, the role name, the venv's version."""
    assert (follow.VERSION, follow.MAP, follow.BLUEPRINT, follow.ROLE_NAME) == (
        "0.10.0", "Carla/Maps/Town10HD_Opt", "vehicle.taxi.ford", "ego_vehicle")
    assert (follow.HOST, follow.PORT, follow.TAKE_ROOT) == ("127.0.0.1", 2000, Path(r"E:\CARLA\takes"))
    assert (enc.VERSION, enc.MAP, enc.BLUEPRINT) == (follow.VERSION, follow.MAP, follow.BLUEPRINT) and iso.CARLA_VERSION == follow.VERSION


# =================================================================================================================
# encode010.py: a passive take as a carla-autoware recording (spec-2 2.9, 10.1 item 2)
# =================================================================================================================

@pytest.fixture
def stand_ins(monkeypatch):
    """cantools' database and python-can's reader replaced by test_sdv_carla.py's exact stand-ins."""
    monkeypatch.setattr(enc, "load_dbc", lambda contract, path=None: tsc.FakeDb())
    monkeypatch.setattr(enc, "read_log", tsc.fake_read_log)
    return monkeypatch


def make_take(tmp_path, **faults):
    rc, carla, take = run_follow(tmp_path / "pc", **faults)
    assert take.is_dir()
    return rc, take


def record(tmp_path, take, name=NAME, contract=None):
    out = tmp_path / "rec" / name
    return enc.record(take, out, name, contract=contract if contract is not None else fixture_contract(compiled=True)), out


def _retake(take, edit_capture=None, edit_steps=None):
    """Rewrite a take's capture.json or steps.jsonl and its take.sha256, so only the edit is wrong."""
    if edit_capture:
        cap = read_capture(take)
        edit_capture(cap)
        (take / "capture.json").write_text(json.dumps(cap, indent=1), encoding="utf-8")
    if edit_steps:
        steps = read_steps(take)
        edit_steps(steps)
        (take / "steps.jsonl").write_text("".join(json.dumps(s, separators=(",", ":")) + "\n" for s in steps), encoding="ascii")
    (take / "take.sha256").write_text("".join("%s  %s\n" % (_sha(take / n), n) for n in ("steps.jsonl", "script.jsonl", "capture.json")),
                                      encoding="ascii")


@NEEDS_CONTRACT
def test_a_passive_take_records_and_verifies_with_its_files_in_order_and_the_manifest_line_last(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    assert rc == 0
    written = []
    real = enc._write_bytes
    stand_ins.setattr(enc, "_write_bytes", lambda p, data: written.append(p.name) or real(p, data))
    res, out = record(tmp_path, take)
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["ok_terms"]
    assert written == ["carla.log", "carla.log.sha256", "steps.jsonl", "summary.json", "manifest-line.json"]
    assert (out / "steps.jsonl").read_bytes() == (take / "steps.jsonl").read_bytes()
    assert (out / "carla.log.sha256").read_text(encoding="ascii") == "%s  carla.log\n" % _sha(out / "carla.log")
    assert list(res["verify"]["ok_terms"]) == list(enc.OK_TERMS) and all(res["verify"]["ok_terms"].values())


def test_verify_s_terms_are_phase_7_s_without_the_scripted_drive_s_two():
    """A drive Autoware makes has no scripted segments and no hard brake (prep 2c item 8): segments_complete and
    app_switches_as_designed are left out, the other seven kept in Phase 7's order."""
    assert enc.OK_TERMS == tuple(t for t in tsc.encode.OK_TERMS if t not in ("segments_complete", "app_switches_as_designed"))
    assert len(enc.OK_TERMS) == 7


@NEEDS_CONTRACT
def test_the_manifest_line_is_run_type_carla_autoware_under_profile_5_with_five_params_naming_the_law(tmp_path, stand_ins):
    """generator carla-autoware (the stack's rule: a recording's run type is its generator), profile 5
    (LIVE_DEFAULT_PROFILE["carla-autoware"]), the taxi as the declared vehicle with profile 5's L; five params: the
    catalogue digest and the DBC's sha256 (the injector and the bundle read both), the version, the map, and the steering
    law naming C and the flat curve, so the injector's three keep the scenario entry's eight."""
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    text = (out / "manifest-line.json").read_text(encoding="ascii")
    line = json.loads(text)
    assert text == json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n"
    law = "-%g*s*|s| deg on the curve (0,1),(120,1)" % PROBED["C"]
    assert line == {
        "name": NAME, "profile_id": 5,
        "recording": {"format": "candump-log", "path": str(out / "carla.log"), "sha256": _sha(out / "carla.log")},
        "source": {"generator": "carla-autoware",
                   "params": {"catalog_digest": "0x%08X" % GEN.CATALOG_DIGEST, "dbc_sha256": _sha(SLICE_DBC),
                              "version": "0.10.0", "map": "Carla/Maps/Town10HD_Opt", "steer_law": law},
                   "rtf": read_capture(take)["rtf"],
                   "vehicle": {"name": "vehicle.taxi.ford", "wheelbase_mm": PROBED["L_MM"]}}}
    src = (REPO / "sdv" / "inject" / "inject.py").read_text(encoding="utf-8")
    consts = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PARAMS_MAX", "PARAM_LEN_MAX", "REWRITE_PARAMS"):
                consts[node.targets[0].id] = ast.literal_eval(node.value)
    params = line["source"]["params"]
    assert len(params) + len(consts["REWRITE_PARAMS"]) <= consts["PARAMS_MAX"]
    assert all(isinstance(v, str) and len(v) <= consts["PARAM_LEN_MAX"] for v in params.values())


@NEEDS_CONTRACT
def test_the_summary_s_trip_names_the_profile_the_conversion_and_the_take(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert set(summ) == {"dir", "name", "recorded", "trip", "verify"}
    trip = summ["trip"]
    assert tuple(res["trip"]) == enc.TRIP_KEYS and set(trip) == set(enc.TRIP_KEYS)        # the file's keys are sorted
    assert trip["profile_id"] == 5 and trip["profile_compiled"] is True and trip["wheelbase_mm"] == PROBED["L_MM"]
    assert trip["timestamps"] == "feeder send schedule from zero" and trip["gaps"] == []
    assert trip["segments"][0][0] == "passive" and len(trip["segments"]) == 1
    assert trip["take"] == {"name": NAME, "take_sha256": _sha(take / "take.sha256")}
    assert trip["conversion"] == {"law": "delta = -C x s x |s|", "C": PROBED["C"], "curve": [[0.0, 1.0], [120.0, 1.0]]}
    assert set(trip["encoder_sha256"]) == set(enc.ENCODER_MODULES)
    for rel, sha in trip["encoder_sha256"].items():
        assert sha == _sha(REPO / rel)
    assert {"sdv/carla/encode010.py", "sdv/sim/carla010_iso.py", "sdv/carla/encode.py"} <= set(enc.ENCODER_MODULES)
    assert trip["params"] == json.loads((out / "manifest-line.json").read_text(encoding="ascii"))["source"]["params"]


@NEEDS_CONTRACT
def test_each_frame_carries_carla010_iso_s_values_never_0_9_16_s_conversion(tmp_path, stand_ins):
    """The log's dynamics frames decode, within half an LSB, to carla010_iso's values of their steps: delta by the law, the
    yaw rate -w[2]; never carla_iso's linear steer x max_steer_angle."""
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    assert res["verify"]["cantools_decode"]["within_half_lsb"] is True
    steps = read_steps(take)
    db, pol = tsc.FakeDb(), policy()
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    lines = (out / "carla.log").read_text(encoding="ascii").splitlines()
    dyn = db.get_message_by_name(pol.dyn_msg)
    turned = 0
    for line, (_t, msg, i) in zip(lines, sched):
        if msg != pol.dyn_msg:
            continue
        got = dyn.decode(bytes.fromhex(line.split("#")[1]))
        want = iso.convert(steps[i])
        assert got["SteerAngleRow1"] == pytest.approx(want[2], abs=0.005 + 1e-9)
        assert got["YawRate"] == pytest.approx(want[3], abs=0.005 + 1e-9)
        if abs(steps[i]["steer"]) > 0.2:
            turned += 1
            assert abs(got["SteerAngleRow1"] - (-70.0 * steps[i]["steer"])) > 1.0
    assert turned


@NEEDS_CONTRACT
def test_before_wp3c_s_freeze_profile_5_is_judged_by_its_row_and_the_recording_says_it_is_not_compiled(tmp_path, stand_ins, capsys):
    """Profile 5 stays uncompiled until WP3c's freeze (spec-2 2.4): a recording made before it is judged by profile 5's
    own row (rules.Tables' extra_ids), says so in its trip and on stderr, and is regenerated from its take after the
    freeze (spec-2 2.9; the take is the durable artefact)."""
    rc, take = make_take(tmp_path)
    capsys.readouterr()
    res, out = record(tmp_path, take, contract=fixture_contract(compiled=False))
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["ok_terms"]
    assert res["trip"]["profile_compiled"] is False and "PROFILE-NOT-COMPILED" in capsys.readouterr().err
    assert json.loads((out / "manifest-line.json").read_text(encoding="ascii"))["profile_id"] == 5
    res2, out2 = record(tmp_path / "c", take, contract=fixture_contract(compiled=True))
    assert res2["trip"]["profile_compiled"] is True and "PROFILE-NOT-COMPILED" not in capsys.readouterr().err
    assert (out2 / "carla.log").read_bytes() == (out / "carla.log").read_bytes()


@NEEDS_CONTRACT
def test_the_judge_is_profile_5_s_row_not_profile_3_s(tmp_path, stand_ins):
    """A take whose yaw rate is three times the kinematic one is rejected 26 under profile 5's own window and tolerance; and a
    contract whose carla-autoware live default is not 5 is refused outright (the encoder judges no other profile)."""
    rc, take = make_take(tmp_path, w_scale=3.0)
    res, out = record(tmp_path, take)
    assert res["recorded"] is False and res["verify"]["ok_terms"]["all_frames_accepted"] is False
    assert res["verify"]["judge"]["reasons"].get("26", 0) > 0
    rc, take = make_take(tmp_path / "b")
    with pytest.raises(enc.EncodeError, match="profile"):
        record(tmp_path / "b", take, contract=fixture_contract(compiled=True, live_default=3))


@NEEDS_CONTRACT
def test_a_generation_without_the_carla_autoware_run_type_is_refused(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    ns = fixture_contract(compiled=True)
    ns.LIVE_DEFAULT_PROFILE = {k: v for k, v in ns.LIVE_DEFAULT_PROFILE.items() if k != "carla-autoware"}
    with pytest.raises(enc.EncodeError, match="carla-autoware"):
        record(tmp_path, take, contract=ns)
    assert not (tmp_path / "rec").exists()


TAKE_EDITS = {
    "server-0.9.16": (lambda c: c.update(server_version="0.9.16"), None, "0.10.0"),
    "client-0.9.16": (lambda c: c.update(client_version="0.9.16"), None, "0.10.0"),
    "not-passive": (lambda c: c.update(mode="scripted"), None, "passive"),
    "format": (lambda c: c.update(format=2), None, "format"),
    "refused": (lambda c: c.update(refused="two egos"), None, "refused"),
    "incomplete": (lambda c: c.update(completed=False), None, "complete"),
    "errors": (lambda c: c.update(errors=["boom"]), None, "complete"),
    "map": (lambda c: c.update(map="Carla/Maps/Mine_01"), None, "map"),
    "blueprint": (lambda c: c.update(blueprint="vehicle.lincoln.mkz"), None, "blueprint"),
    "role": (lambda c: c.update(role_name="hero"), None, "role"),
    "async-reread": (lambda c: c["world_settings"].append({"at": "reread", "after_frame": 1,
                                                           "settings": dict(c["world_settings"][0]["settings"], synchronous_mode=False)}),
                     None, "synchronous"),
    "step": (lambda c: c["world_settings"][0]["settings"].update(fixed_delta_seconds=0.1), None, "fixed_delta_seconds"),
    "near-step": (lambda c: c["world_settings"][0]["settings"].update(fixed_delta_seconds=0.0500001), None, "fixed_delta_seconds"),
    "no-settings": (lambda c: c.update(world_settings=[]), None, "world settings"),
    # the match is the attach check's own words: the reads check refuses this take too, with a message that says "attach"
    "first-read-not-attach": (lambda c: c["world_settings"][0].update(at="reread"), None, "no world settings read at attach"),
    # a read, its settings or the physics read of another JSON kind: a refusal, never an AttributeError out of check_take
    "settings-entry-int": (lambda c: c.update(world_settings=[1]), None, "not objects, each with a settings object"),
    "settings-entries-str": (lambda c: c.update(world_settings=["x", "y"]), None, "not objects, each with a settings object"),
    "settings-list": (lambda c: c["world_settings"][0].update(settings=[1]), None, "not objects, each with a settings object"),
    "settings-last-str": (lambda c: c["world_settings"][-1].update(settings="synchronous"), None,
                          "not objects, each with a settings object"),
    "physics-list": (lambda c: c.update(physics_read=[1]), None, "physics_read is a list, not an object"),
    "curve": (lambda c: c["physics_read"].update(steering_curve=[[0.0, 1.0], [10.0, 0.5]] + [list(p) for p in fake.FAKE_SHIPPED]),
              None, "flattening"),
    "curve-right-ends": (lambda c: c["physics_read"].update(steering_curve=[[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [60.0, 0.8],
                                                                            [120.0, 1.0]]), None, "flattening"),
    "listener": (lambda c: c["listeners"].update(end=["0.0.0.0:8000"]), None, "listen"),
    "listener-not-run": (lambda c: c.update(listeners={"start": "not run: not Windows", "end": "not run: not Windows"}), None,
                         "listen"),
    "rtf-record": (lambda c: c["rtf"].update(max=0.5), None, "rtf"),
    "steps-record": (lambda c: c.update(steps=c["steps"] + 1), None, "steps"),
    "gaps-record": (lambda c: c.update(gaps=[3]), None, "gaps"),
    "skipped-record": (lambda c: c.update(skipped_frames=[3]), None, "skipped_frames"),
    "not-current-from-0": (None, lambda steps: [s.update(t_cur_ns=s["t_cur_ns"] + 1) for s in steps], "current at 0"),
    "one-step": (None, lambda steps: steps.__delitem__(slice(1, None)), "sequence of steps"),
    "seg":(None, lambda steps: steps[7].update(seg="route drive"), "passive"),
    "gear": (None, lambda steps: steps[-1].update(gear=-1), "reverse"),
    "key": (None, lambda steps: steps[3].update(wheel_deg=[0.0, 0.0]), "exactly the keys"),
    "frame": (None, lambda steps: [s.update(frame=s["frame"] + 1) for s in steps[20:]], "skipped"),
    # the reads are the follower's (at attach, after every REREAD_FRAMES frames, at the end); the end is one of its
    "rereads-stripped": (lambda c: c.update(world_settings=[w for w in c["world_settings"] if w["at"] != "reread"]), None,
                         "settings reads"),
    "last-read-dropped": (lambda c: c["world_settings"].pop(), None, "settings reads"),
    "reread-after-another-frame": (lambda c: c["world_settings"][1].update(after_frame=c["world_settings"][1]["after_frame"] + 1),
                                   None, "settings reads"),
    "end-null": (lambda c: c.update(end=None), None, "take's end"),
    "end-unknown": (lambda c: c.update(end="interrupted"), None, "take's end"),
    "not-increasing": (None, lambda steps: steps[5].update(t_cur_ns=steps[4]["t_cur_ns"]), "increasing order"),
    "settings-key-missing": (lambda c: c["world_settings"][-1]["settings"].pop("synchronous_mode"), None, "synchronous"),
}


@NEEDS_CONTRACT
@pytest.mark.parametrize("what", sorted(TAKE_EDITS))
def test_record_refuses_a_take_whose_record_disqualifies_it_and_writes_nothing(tmp_path, stand_ins, what):
    """The encoder holds the take's own record to the follower's rules again (it never takes it on trust): a take of
    another version, not passive, refused, incomplete, of another map, blueprint or role name, whose world settings left
    the tie at attach or at any re-read (or were never read), whose own curve is not the flattening, whose client listened
    (or whose check never ran), whose record disagrees with its steps; a step not passive, whose gear and reverse disagree,
    with another key set, or after a skipped frame."""
    rc, take = make_take(tmp_path)
    edit_c, edit_s, said = TAKE_EDITS[what]
    _retake(take, edit_capture=edit_c, edit_steps=edit_s)
    with pytest.raises(enc.EncodeError, match=said):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_a_take_ended_by_max_frames_on_a_re_read_frame_records_with_the_end_read_in_that_re_read_s_place(tmp_path, stand_ins):
    """--max-frames ends the take at its last frame before that frame's re-read, so a take of exactly
    REREAD_FRAMES frames holds the attach and the end reads only, and records."""
    rc, take = make_take(tmp_path, extra=("--max-frames", str(follow.REREAD_FRAMES)))
    cap = read_capture(take)
    assert rc == 0 and cap["end"] == "max-frames"
    assert [[w["at"], w["after_frame"]] for w in cap["world_settings"]] == [
        ["attach", None], ["end", fake.FAKE_START_FRAME + follow.REREAD_FRAMES]]
    res, out = record(tmp_path, take)
    assert res["recorded"] is True and res["verify"]["ok"] is True


@NEEDS_CONTRACT
def test_record_refuses_a_take_whose_take_sha256_does_not_hold_or_lists_other_files(tmp_path, stand_ins):
    """The take's sums are its integrity, and the take is the durable artefact a recording is made again from: a file the
    sums do not hold for, or sums that list other files or the three in another order, are refused before anything is
    written (the module docstring's RECORD)."""
    rc, take = make_take(tmp_path)
    steps = (take / "steps.jsonl").read_text(encoding="ascii")
    (take / "steps.jsonl").write_text(steps.replace('"seg":"passive"', '"seg": "passive"', 1), encoding="ascii")
    with pytest.raises(enc.EncodeError, match="does not hold for steps.jsonl"):
        record(tmp_path, take)
    (take / "steps.jsonl").write_text(steps, encoding="ascii")
    sums = (take / "take.sha256").read_text(encoding="ascii")
    lines = sums.splitlines(True)
    for bad in ("".join([lines[1], lines[0], lines[2]]), sums.replace("capture.json", "capture.jsn"), "".join(lines[:2])):
        (take / "take.sha256").write_text(bad, encoding="ascii")
        with pytest.raises(enc.EncodeError, match="lists"):
            record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_refuses_a_take_whose_script_is_not_empty(tmp_path, stand_ins):
    """A passive take commands nothing, so its script.jsonl is empty (sums that hold do not make it so)."""
    rc, take = make_take(tmp_path)
    (take / "script.jsonl").write_bytes(b'{"seg":"launch","t_s":0.0}\n')
    _retake(take)
    with pytest.raises(enc.EncodeError, match="script.jsonl is not empty"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("doc", ["[]", "null", '"a take"', "7"], ids=["list", "null", "string", "number"])
def test_a_capture_json_that_is_not_an_object_is_a_refusal_with_exit_2_never_a_traceback(tmp_path, stand_ins, capsys, doc):
    """Sums that hold do not make capture.json the follower's object; a JSON value of another kind is an
    EncodeError (main: "encode010.py: refused: ...", exit 2), not an AttributeError out of check_take."""
    rc, take = make_take(tmp_path)
    (take / "capture.json").write_text(doc, encoding="utf-8")
    _retake(take)
    with pytest.raises(enc.EncodeError, match="capture.json is not an object"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()
    stand_ins.setattr(enc, "load_contract", lambda: fixture_contract(compiled=True))
    capsys.readouterr()
    assert enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(tmp_path / "recs")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode010.py: refused: ") and "capture.json is not an object" in err and "Traceback" not in err
    assert not (tmp_path / "recs").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("edit", [lambda c: c.update(world_settings=[1]), lambda c: c["world_settings"][0].update(settings=[1]),
                                  lambda c: c.update(physics_read=[1])], ids=["settings-entry-int", "settings-list", "physics-list"])
def test_a_read_or_physics_read_not_an_object_is_a_refusal_with_exit_2_never_a_traceback(tmp_path, stand_ins, capsys, edit):
    """Sums that hold do not make capture.json's world settings reads, their settings or its physics read the follower's
    objects either: one of another JSON kind is "encode010.py: refused: ...", exit 2, with nothing written."""
    rc, take = make_take(tmp_path)
    _retake(take, edit_capture=edit)
    stand_ins.setattr(enc, "load_contract", lambda: fixture_contract(compiled=True))
    capsys.readouterr()
    assert enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(tmp_path / "recs")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode010.py: refused: ") and "Traceback" not in err
    assert "each with a settings object" in err or "physics_read is a list, not an object" in err
    assert not (tmp_path / "recs").exists()


@NEEDS_CONTRACT
def test_an_existing_directory_is_refused_before_the_profile_not_compiled_line_is_printed(tmp_path, stand_ins, capsys):
    """PROFILE-NOT-COMPILED is said once the recording's directory is made, so a refusal for an existing
    directory (somebody's, left alone) is the only thing on stderr, and "encode010.py: refused: " starts it."""
    rc, take = make_take(tmp_path)
    out = tmp_path / "rec" / NAME
    out.mkdir(parents=True)
    capsys.readouterr()
    with pytest.raises(FileExistsError):
        enc.record(take, out, NAME, contract=fixture_contract(compiled=False))
    assert capsys.readouterr().err == "" and list(out.iterdir()) == []
    stand_ins.setattr(enc, "load_contract", lambda: fixture_contract(compiled=False))
    assert enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(tmp_path / "rec")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode010.py: refused: ") and "PROFILE-NOT-COMPILED" not in err
    assert list(out.iterdir()) == []
    res, made = record(tmp_path / "c", take, contract=fixture_contract(compiled=False))
    assert res["recorded"] is True and "PROFILE-NOT-COMPILED" in capsys.readouterr().err


@NEEDS_CONTRACT
def test_record_refuses_a_step_that_advances_the_simulation_by_other_than_one_step(tmp_path, stand_ins):
    """The encoder holds each step's simulation advance to one step (sendpolicy.step_advance_ns) and names the
    first step that is not; here steps 120 on advance 0.02 s each, with the record's RTF made to agree with the steps, so
    only the advance is wrong."""
    rc, take = make_take(tmp_path)
    steps = read_steps(take)
    for k in range(120, len(steps)):
        steps[k]["elapsed_s"] = steps[119]["elapsed_s"] + 0.02 * (k - 119)
    rtf = sendpolicy.rtf_summary([s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps], policy().step_ns)
    assert rtf["max"] <= 1 and rtf["min"] > 0
    _retake(take, edit_capture=lambda c: c.update(rtf=rtf), edit_steps=lambda s: s.__setitem__(slice(None), steps))
    with pytest.raises(enc.EncodeError, match=r"step 120 advances the simulation by 20000000 ns, not one step"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("change", [{"fixed_delta_seconds": 0.02}, {"synchronous_mode": False}])
def test_a_tie_left_after_the_last_re_read_is_not_recorded(tmp_path, stand_ins, change):
    """The world leaves the tie after the last periodic re-read (at frame 210 of 240; the re-read was after frame
    200). A step changed there refuses the take at that frame; a world made asynchronous there, at the settings read the
    take ends with. Either way nothing of it is encoded."""
    rc, take = make_take(tmp_path, ticks=240, settings_at={210: change})
    if rc == 1:
        assert read_capture(take)["refused"]
        return
    with pytest.raises(enc.EncodeError):
        record(tmp_path, take)


@NEEDS_CONTRACT
def test_record_refuses_a_take_with_a_gap(tmp_path, stand_ins):
    rc, take = make_take(tmp_path, tick_wall_ns=lambda k: 80 * MS if k == 30 else 50 * MS)
    assert rc == 0
    with pytest.raises(enc.EncodeError, match="gap"):
        record(tmp_path, take)


@NEEDS_CONTRACT
def test_record_refuses_a_refused_take_as_the_follower_wrote_it(tmp_path, stand_ins):
    rc, take = make_take(tmp_path, curve=fake.FAKE_SHIPPED)
    assert rc == 1
    with pytest.raises(enc.EncodeError, match="refused"):
        record(tmp_path, take)


@NEEDS_CONTRACT
def test_a_phase_7_take_is_refused_by_the_0_10_0_encoder(tmp_path, stand_ins):
    rc, _carla, take = tsc.run_take(tmp_path / "p7")
    assert rc == 0
    with pytest.raises(enc.EncodeError):
        enc.record(take, tmp_path / "rec" / take.name, take.name, contract=fixture_contract(compiled=True))
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_refuses_a_value_outside_slice_dbc_s_range_and_names_the_step(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    _retake(take, edit_steps=lambda steps: steps[12].update(a=[-40.0 * f for f in steps[12]["fwd"]]))
    with pytest.raises(enc.EncodeError, match=r"step 12\b.*LongAccel"):
        record(tmp_path, take)


@NEEDS_CONTRACT
def test_record_refuses_a_name_that_is_not_the_take_s_and_an_existing_directory(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    with pytest.raises(enc.EncodeError, match="name"):
        enc.record(take, tmp_path / "rec" / "20261023-carla010-2", "20261023-carla010-2", contract=fixture_contract(compiled=True))
    out = tmp_path / "rec2" / NAME
    out.mkdir(parents=True)
    (out / "mine").write_text("x", encoding="ascii")
    with pytest.raises(FileExistsError):
        enc.record(take, out, NAME, contract=fixture_contract(compiled=True))
    assert [p.name for p in out.iterdir()] == ["mine"]


@NEEDS_CONTRACT
@pytest.mark.parametrize("fault,term", [("swap", "regenerated_identical"), ("channel", "python_can_reader"),
                                        ("gear-frame", "within_half_lsb"), ("missing-frame", "no_period_errors")])
def test_verify_fails_the_term_a_damaged_log_breaks(tmp_path, stand_ins, fault, term):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    assert res["verify"]["ok"] is True
    pol, db = policy(), tsc.FakeDb()
    dyn_id, gear_id = ("%03X" % db.get_message_by_name(m).frame_id for m in (pol.dyn_msg, pol.gear_msg))
    log = out / "carla.log"
    lines = log.read_text(encoding="ascii").splitlines(True)
    ids = [ln.split(" ")[2].split("#")[0] for ln in lines]
    if fault == "swap":
        lines[3], lines[4] = lines[4], lines[3]
    elif fault == "channel":
        k = len(lines) // 2
        lines[k] = lines[k].replace(" vcan0 ", " vcan1 ", 1)
    elif fault == "gear-frame":
        k = next(k for k, ln in enumerate(lines) if ids[k] == gear_id and ln.split("#")[1].startswith("01"))
        lines[k] = lines[k].replace("#01", "#00", 1)
    else:
        k = next(k for k in range(20, len(lines)) if ids[k] == dyn_id)
        del lines[k]
    log.write_text("".join(lines), encoding="ascii")
    v = enc.verify(out, fixture_contract(compiled=True))
    assert v["ok_terms"][term] is False and v["ok"] is False


@NEEDS_CONTRACT
def test_a_failed_verify_leaves_no_manifest_line_and_renames_the_recording(tmp_path, stand_ins):
    rc, take = make_take(tmp_path, w_scale=3.0)
    res, out = record(tmp_path, take)
    assert res["recorded"] is False and not out.exists()
    failed = out.with_name(out.name + ".failed")
    assert sorted(p.name for p in failed.iterdir()) == ["carla.log", "carla.log.sha256", "steps.jsonl", "summary.json"]


@NEEDS_CONTRACT
def test_verify_is_not_ok_when_the_log_s_sha256_file_does_not_hold(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    (out / "carla.log.sha256").write_text("%s  carla.log\n" % ("0" * 64), encoding="ascii")
    v = enc.verify(out, fixture_contract(compiled=True))
    assert all(v["ok_terms"].values()) and v["log_sha256_file_holds"] is False and v["ok"] is False


@NEEDS_CONTRACT
def test_main_refuses_with_exit_2_and_no_traceback(tmp_path, stand_ins, capsys, monkeypatch):
    rc, take = make_take(tmp_path)
    stand_ins.setattr(enc, "load_contract", lambda: fixture_contract(compiled=True))
    taken = tmp_path / "recs" / NAME
    taken.mkdir(parents=True)
    assert enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(tmp_path / "recs")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode010.py: refused: ") and "Traceback" not in err
    with pytest.raises(SystemExit) as exc:
        enc.main(["record", "--take", str(take), "--name", "20261023-carla-1"])
    assert exc.value.code == 2
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sigsim, "REPO", repo)
    with pytest.raises(SystemExit) as exc:
        enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(repo / "sdv")])
    assert exc.value.code == 2 and "inside the repository" in capsys.readouterr().err
    assert enc.main(["record", "--take", str(take), "--name", NAME, "--root", str(tmp_path / "ok")]) == 0
    assert enc.main(["verify", str(tmp_path / "ok" / NAME)]) == 0


def test_a_recording_under_the_default_root_keeps_the_home_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = tmp_path / "sdv-recordings" / NAME
    assert enc.log_path_shown(out) == "~/sdv-recordings/%s/carla.log" % NAME


def test_the_encoder_reuses_encode_py_read_only_and_never_imports_carla_iso():
    """encode010 loads encode.py by path under a name of its own and calls its functions; it never assigns to it, and the
    0.9.16 conversion (carla_iso) is not one of its modules."""
    src = (CARLA_DIR / "encode010.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                assert not (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "encode"), ast.dump(t)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "carla_iso" not in names and "carla_iso" not in imported
    assert enc.encode.__file__ == str(CARLA_DIR / "encode.py") and enc.encode.__name__ != "encode"


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_record_and_verify_with_cantools_and_python_can_against_the_real_generation(tmp_path):
    """End to end in the sim venv on the real generation (profile 5 uncompiled there until WP3c): recorded, marked not
    compiled, verified; a damaged log fails regenerated_identical."""
    rc, take = make_take(tmp_path)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SDV_GEN=str(vf.contract_path().parent))

    def run(*args):
        return subprocess.run([str(SIM_PY), str(CARLA_DIR / "encode010.py")] + [str(a) for a in args], capture_output=True,
                              text=True, env=env, cwd=str(REPO))
    p = run("record", "--take", take, "--name", NAME, "--root", tmp_path / "recs")
    assert p.returncode == 0, p.stderr[-3000:]
    out = tmp_path / "recs" / NAME
    compiled = 5 in GEN.COMPILED_PROFILE_IDS
    assert ("PROFILE-NOT-COMPILED" in p.stderr) is (not compiled)
    v = run("verify", out)
    assert v.returncode == 0 and json.loads(v.stdout)["ok"] is True, v.stdout[-3000:]
    log = out / "carla.log"
    text = log.read_text(encoding="ascii")
    first = text.splitlines()[0]
    log.write_text(text.replace(first, first[:-1] + ("0" if first[-1] != "0" else "1"), 1), encoding="ascii")
    v = run("verify", out)
    assert v.returncode == 1 and json.loads(v.stdout)["ok_terms"]["regenerated_identical"] is False


# --- the contract test against WP3b's real generation (spec-2 10.1: added at the merge, after WP3b) -----------------

@NEEDS_CONTRACT
def test_the_real_generation_names_what_the_fixture_contract_assumes():
    """LIVE_DEFAULT_PROFILE["carla-autoware"] is 5 and profile 5's L is PROBED's (W9 E4), on the carla010 envelope; the
    generation serves the carla-autoware run type's catalogue."""
    if "carla-autoware" not in GEN.LIVE_DEFAULT_PROFILE:
        pytest.fail("this generation has no carla-autoware run type (WP3b's generation is merged in this tree)")
    assert GEN.LIVE_DEFAULT_PROFILE["carla-autoware"] == 5
    row = {int(r["id"]): r for r in GEN.PROFILES}[5]
    assert row["l_mm"] == PROBED["L_MM"] and row["envelope"] == "carla010" and row["source_vehicle"] == "carla010-taxi"
    man = json.loads((vf.contract_path().parent / "manifest.json").read_text(encoding="utf-8"))
    assert man["databroker_catalogues"]["carla-autoware"] == "vss-databroker-carla-autoware.json"
    assert enc.profile_of(GEN)[:2] == (5, row) and enc.profile_of(GEN)[2] is (5 in GEN.COMPILED_PROFILE_IDS)


# --- Phase 7's 0.9.16 path stays as it is ----------------------------------------------------------------------------

@pytest.mark.parametrize("rel", sorted(FROZEN_0916))
def test_phase_7_s_0_9_16_files_are_byte_for_byte_the_base_s(rel):
    assert _sha(REPO / rel) == FROZEN_0916[rel], rel


def test_carla_honest_s_recorded_encoder_hashes_still_equal_the_encoder_modules():
    """CARLA_HONEST (20261019-carla-1, Phase 7 WP5a's recording) recorded the sha256 of each module that encoded it: each
    still equals the file (read only; skipped where the recording is not on this host)."""
    if not CARLA_HONEST_SUMMARY.is_file():
        pytest.skip("CARLA_HONEST is not on this host (%s)" % CARLA_HONEST_SUMMARY)
    rec = json.loads(CARLA_HONEST_SUMMARY.read_text(encoding="utf-8"))["trip"]["encoder_sha256"]
    assert rec and {rel: _sha(REPO / rel) for rel in rec} == rec


def test_no_new_module_shares_a_name_with_a_module_ci_type_checks_beside_it():
    new = {"follow010", "encode010", "gpucheck"}
    assert {p.stem for p in CARLA_DIR.glob("*.py")} >= new and not (CARLA_DIR / "__init__.py").exists()
    others = set()
    for d in ("scripts/ci", "scripts/aws", "scripts/twin", "tests", "sdv/connector", "sdv/cloud", "sdv/ota", "sdv/feeder",
              "sdv/ctl", "sdv/rosvss", "sdv/drill"):
        if (REPO / d).is_dir():
            others |= {p.stem for p in (REPO / d).rglob("*.py")}
    assert not (new | {"carla010_iso"}) & others


# =================================================================================================================
# gpucheck.py: D21's read before every 0.10.0 server start (spec-2 10.1 item 4)
# =================================================================================================================

def gpu_doc(free=12000, used=4000, total=16000, carla=(), ollama=(), listen=(), others=()):
    """A document shaped like gpucheck's PowerShell read (synthetic values)."""
    return {"utc": "2026-10-23T01:02:03.0000000Z", "gpu": ["%d, %d, %d" % (total, used, free)],
            "carla": [{"Name": n, "Id": i} for n, i in carla], "ollama": [{"Name": n, "Id": i} for n, i in ollama],
            "listen": [{"LocalAddress": a, "LocalPort": p, "OwningProcess": i} for a, p, i in listen],
            "others": [{"Name": n, "Id": i, "Path": p} for n, i, p in others]}


class _Runner:
    def __init__(self, rc=0, out=None, err=""):
        self.rc, self.out, self.err, self.cmds = rc, out, err, []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        return self.rc, self.out, self.err


def test_free_mib_min_is_the_owner_s_9500_in_one_place_with_its_reason():
    assert gpucheck.FREE_MIB_MIN == 9500 and gpucheck.PORTS == (2000, 2001, 2002, 8000)
    lines = (CARLA_DIR / "gpucheck.py").read_text(encoding="utf-8").splitlines()
    hits = [k for k, ln in enumerate(lines) if re.match(r"^FREE_MIB_MIN\s*=", ln)]
    assert len(hits) == 1
    block = "\n".join(lines[max(0, hits[0] - 4):hits[0]])
    assert "owner" in block and "refusal threshold" in block and "headroom" in block
    for f in sorted(CARLA_DIR.glob("*.py")):
        if f.name != "gpucheck.py":
            assert "9500" not in f.read_text(encoding="utf-8"), f.name


@pytest.mark.parametrize("free,ok", [(9500, True), (9499, False), (16000, True), (0, False)])
def test_free_vram_below_9500_mib_refuses_and_at_it_passes(free, ok):
    lines = gpucheck.result_lines(gpucheck.check(gpucheck.parse(gpu_doc(free=free))), gpucheck.parse(gpu_doc(free=free)))
    if ok:
        assert lines == ["gpucheck: PASS (free %d MiB, at least 9500)" % free]
    else:
        assert lines == ["gpucheck: FAIL: free-vram: %d MiB free, below 9500" % free]


@pytest.mark.parametrize("kw,line", [
    ({"carla": [("CarlaUnreal-Win64-Shipping", 4242)]}, "gpucheck: FAIL: carla-process: CarlaUnreal-Win64-Shipping(4242)"),
    ({"carla": [("CarlaUE4", 17)]}, "gpucheck: FAIL: carla-process: CarlaUE4(17)"),
    ({"ollama": [("ollama", 99)]}, "gpucheck: FAIL: ollama-process: ollama(99)"),
    ({"ollama": [("ollama app", 98)]}, "gpucheck: FAIL: ollama-process: ollama app(98)"),
    ({"listen": [("0.0.0.0", 2000, 5)]}, "gpucheck: FAIL: listener: 0.0.0.0:2000 pid 5"),
    ({"listen": [("0.0.0.0", 2001, 5)]}, "gpucheck: FAIL: listener: 0.0.0.0:2001 pid 5"),
    ({"listen": [("::", 2002, 6)]}, "gpucheck: FAIL: listener: :::2002 pid 6"),
    ({"listen": [("127.0.0.1", 8000, 7)]}, "gpucheck: FAIL: listener: 127.0.0.1:8000 pid 7"),
])
def test_a_carla_or_ollama_process_or_a_listener_on_2000_2002_or_8000_refuses(kw, line):
    r = gpucheck.parse(gpu_doc(**kw))
    assert gpucheck.result_lines(gpucheck.check(r), r) == [line]


def test_a_listener_on_another_port_is_not_this_check_s_and_every_failure_gets_its_own_line():
    r = gpucheck.parse(gpu_doc(listen=[("0.0.0.0", 2003, 5), ("0.0.0.0", 1999, 5)]))
    assert gpucheck.check(r) == []
    r = gpucheck.parse(gpu_doc(free=100, carla=[("CarlaUnreal", 1)], ollama=[("ollama", 2)], listen=[("0.0.0.0", 2001, 1)]))
    assert [c for c, _w in gpucheck.check(r)] == ["free-vram", "carla-process", "ollama-process", "listener"]


def test_the_record_is_wp9a_s_d21_form():
    r = gpucheck.parse(gpu_doc(free=12345, used=3655, total=16000, carla=[("CarlaUE4", 3)], listen=[("0.0.0.0", 8000, 3)],
                               others=[("python", 77, "E:\\CARLA\\venv312-010\\Scripts\\python.exe")]))
    assert gpucheck.record(r) == {
        "utc": "2026-10-23T01:02:03.0000000Z", "carla_processes": ["CarlaUE4(3)"], "ollama_processes": [],
        "listening_2000_2002_8000": ["0.0.0.0:8000 pid 3"], "gpu_mib": {"total": 16000, "used": 3655, "free": 12345},
        "min_free_mib": 9500, "other_gpu_relevant_processes": ["python(77) E:\\CARLA\\venv312-010\\Scripts\\python.exe"]}


@pytest.mark.parametrize("path,shown", [
    ("C:\\Users\\someone\\AppData\\Local\\Programs\\Ollama\\ollama.exe", "%USERPROFILE%\\AppData\\Local\\Programs\\Ollama\\ollama.exe"),
    ("c:\\users\\Some.One\\venv\\Scripts\\python.exe", "%USERPROFILE%\\venv\\Scripts\\python.exe"),
    ("D:\\Users\\someone", "%USERPROFILE%"),
    ("E:\\CARLA\\venv312-010\\Scripts\\python.exe", "E:\\CARLA\\venv312-010\\Scripts\\python.exe"),
    ("C:\\Program Files\\Users\\tool.exe", "C:\\Program Files\\Users\\tool.exe"),
], ids=["profile", "profile-lower-case", "profile-itself", "outside-users", "users-elsewhere"])
def test_the_record_shows_a_path_under_a_user_profile_from_the_profile_on_never_its_name(path, shown):
    """The record of the other GPU-relevant processes is redacted at capture time: a path under a user profile
    directory shows %USERPROFILE% in place of the drive, Users and the profile's name; any other path is kept."""
    r = gpucheck.parse(gpu_doc(others=[("python", 77, path)]))
    assert r.others == ("python(77) %s" % shown,)
    assert gpucheck.record(r)["other_gpu_relevant_processes"] == ["python(77) %s" % shown]


def test_gpucheck_s_deciding_reads_stop_on_an_error_and_only_the_record_s_read_continues():
    """A cmdlet run with -ErrorAction SilentlyContinue reads as "none" when it fails, so each read a clause decides
    on (Carla*, ollama*, the listeners) stops on an error: the read fails (exit 2). A wildcard Get-Process name with no
    match and an unfiltered listener read write no error. Only the record's read of the other processes continues past
    one (it decides nothing)."""
    lines = gpucheck.PS_SCRIPT.splitlines()
    assert lines[1] == "$ErrorActionPreference = 'Stop'"
    deciding = [ln for ln in lines if ln.startswith(("$carla =", "$ollama =", "$listen ="))]
    assert len(deciding) == 3 and all("-ErrorAction Stop " in ln and "SilentlyContinue" not in ln for ln in deciding)
    others = [ln for ln in lines if ln.startswith("$others =")]
    assert len(others) == 1 and "-ErrorAction SilentlyContinue " in others[0]


def test_a_failed_nvidia_smi_is_a_failed_read():
    assert 'if ($LASTEXITCODE -ne 0) { throw "nvidia-smi exited $LASTEXITCODE" }' in gpucheck.PS_SCRIPT


def test_a_powershell_list_of_one_or_none_reads_as_a_list():
    """ConvertTo-Json gives one object, or null, for a list of one or none."""
    r = gpucheck.parse(dict(gpu_doc(), carla={"Name": "CarlaUE4", "Id": 3}))
    assert r.carla == ("CarlaUE4(3)",)
    assert gpucheck.parse(dict(gpu_doc(), ollama=None)).ollama == ()
    with pytest.raises(ValueError):
        gpucheck.parse(dict(gpu_doc(), listen=[1, 2]))


@pytest.mark.parametrize("port", ["2001", 2001.0, True, None, [2001]], ids=["string", "float", "bool", "none", "list"])
def test_a_listener_whose_port_is_not_an_integer_is_a_failed_read_never_a_listener_dropped(port, capsys):
    """The PowerShell read casts the port with [int], so any other form is not its output; filtering on PORTS
    first would drop such a listener and let the check pass. It is a ValueError, and main exits 2 without a PASS."""
    doc = dict(gpu_doc(), listen=[{"LocalAddress": "0.0.0.0", "LocalPort": port, "OwningProcess": 5}])
    with pytest.raises(ValueError, match="LocalPort"):
        gpucheck.parse(doc)
    assert gpucheck.main([], runner=_Runner(out=json.dumps(doc)), windows=True) == 2
    got = capsys.readouterr()
    assert "PASS" not in got.out and "LocalPort" in got.err
    ok = gpucheck.parse(dict(gpu_doc(), listen=[{"LocalAddress": "0.0.0.0", "LocalPort": 2001, "OwningProcess": 5},
                                                 {"LocalAddress": "0.0.0.0", "LocalPort": 5555, "OwningProcess": 6}]))
    assert ok.listeners == ("0.0.0.0:2001 pid 5",)


@pytest.mark.parametrize("doc", [{"gpu": []}, {"gpu": ["16000, 4000"]}, {"gpu": ["a, b, c"]},
                                 {"gpu": ["16000, 4000, 12000", "8000, 1000, 7000"]}, {}])
def test_a_gpu_read_that_is_not_one_line_of_three_numbers_is_a_failed_read(doc):
    full = dict(gpu_doc(), **doc) if doc else {}
    with pytest.raises(ValueError):
        gpucheck.parse(full)


def test_main_prints_the_verdict_then_the_record_and_exits_as_fwcheck(capsys):
    assert gpucheck.main([], runner=_Runner(out=json.dumps(gpu_doc())), windows=True) == 0
    out = capsys.readouterr().out
    first, rest = out.split("\n", 1)
    assert first == "gpucheck: PASS (free 12000 MiB, at least 9500)" and json.loads(rest)["gpu_mib"]["free"] == 12000
    assert gpucheck.main([], runner=_Runner(out=json.dumps(gpu_doc(ollama=[("ollama", 1)]))), windows=True) == 1
    out = capsys.readouterr().out
    assert out.startswith("gpucheck: FAIL: ollama-process: ollama(1)\n") and json.loads(out.split("\n", 1)[1])["ollama_processes"]
    assert gpucheck.main([], runner=_Runner(rc=1, out="", err="nvidia-smi was not found"), windows=True) == 2
    assert gpucheck.main([], runner=_Runner(out="not json"), windows=True) == 2
    assert gpucheck.main([], runner=_Runner(out=json.dumps({"gpu": []})), windows=True) == 2
    got = capsys.readouterr()
    assert "PASS" not in got.out and got.err.count("gpucheck:") == 3
    assert gpucheck.main([], runner=_Runner(out=json.dumps(gpu_doc())), windows=False) == 2
    assert "Windows" in capsys.readouterr().err


def test_the_read_is_one_read_only_powershell_command_named_from_the_constants():
    r = _Runner(out=json.dumps(gpu_doc()))
    assert gpucheck.main([], runner=r, windows=True) == 0
    cmd = r.cmds[0]
    assert len(r.cmds) == 1 and cmd[0].lower().startswith("powershell") and "-NoProfile" in cmd and "-NonInteractive" in cmd
    script = cmd[-1]
    assert "nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits" in script
    assert "Get-Process -Name 'Carla*'" in script and "Get-Process -Name 'ollama*'" in script
    assert "Get-NetTCPConnection -State Listen" in script and "2000, 2001, 2002, 8000" in script
    assert not re.search(r"\b(Set|New|Remove|Stop|Start|Enable|Disable|Copy|Rename)-\w+", script)
    assert script.rstrip().endswith("[int][char]$m.Value })")                  # ASCII only, as fwcheck's read


def test_gpucheck_s_read_is_ascii_or_a_failed_read(monkeypatch):
    def fake_run(cmd, capture_output=False, timeout=None, **kw):
        return types.SimpleNamespace(returncode=0, stdout=fake_run.out, stderr=b"")
    monkeypatch.setattr(gpucheck.subprocess, "run", fake_run)
    fake_run.out = json.dumps(gpu_doc()).encode("ascii")
    assert gpucheck._powershell(gpucheck.command())[0] == 0
    fake_run.out = json.dumps(dict(gpu_doc(), utc="caf\u00e9"), ensure_ascii=False).encode("utf-8")
    rc, out, err = gpucheck._powershell(gpucheck.command())
    assert rc == -1 and out == "" and "not ASCII" in err


# =================================================================================================================
# fwcheck.py's --carla choice (spec-2 10.2)
# =================================================================================================================

FW_CASES = json.loads((HERE / "fixtures" / "carla" / "fwcheck-cases.json").read_text(encoding="utf-8"))
EXE_010 = r"E:\CARLA\Carla-0.10.0-Win64-Shipping\CarlaUnreal\Binaries\Win64\CarlaUnreal-Win64-Shipping.exe"
VENV_010 = r"E:\CARLA\venv312-010"


def _as_010(doc):
    """A 0.9.16 case's document with every program that names the 0.9.16 exe (its path in any letter case or separator,
    or its file name at another path) or the 0.9.16 venv's interpreter made the 0.10.0 one's, in the same letter case and
    separator; nothing else changes."""
    name_916, name_010 = "carlaue4-win64-shipping.exe", "CarlaUnreal-Win64-Shipping.exe"

    def styled(new, old):
        if old == old.lower():
            new = new.lower()
        elif old == old.upper():
            new = new.upper()
        return new.replace("\\", "/") if "/" in old else new

    def swap(p):
        key = p.replace("/", "\\").lower()
        if key == FW_CASES["exe"].lower():
            return styled(EXE_010, p)
        if key.endswith("\\" + name_916):
            return p[:-len(name_916)] + styled(name_010, p[-len(name_916):])
        if key == (fwcheck.VENV + "\\Scripts\\python.exe").lower():
            return styled(VENV_010 + "\\Scripts\\python.exe", p)
        return p
    out = json.loads(json.dumps(doc))
    for r in out.get("rules") or ():
        prog = r.get("Program")
        r["Program"] = [swap(p) for p in prog] if isinstance(prog, list) else (swap(prog) if isinstance(prog, str) else prog)
    return out


def test_the_0_10_0_choice_names_wp9a_s_exe_and_venv_and_the_default_is_0_9_16_s_constants_unchanged():
    assert fwcheck.CARLA_CHOICES == ("0.9.16", "0.10.0") and fwcheck.CARLA_DEFAULT == "0.9.16"
    assert fwcheck.CARLA_TARGETS["0.10.0"] == (EXE_010, "CarlaUnreal-Win64-Shipping.exe", VENV_010)
    assert fwcheck.CARLA_TARGETS["0.9.16"] == (fwcheck.EXE_PATH, fwcheck.EXE_NAME, fwcheck.VENV)
    assert (fwcheck.EXE_PATH, fwcheck.EXE_NAME, fwcheck.VENV) == (
        r"E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe", "CarlaUE4-Win64-Shipping.exe", r"E:\CARLA\venv312")
    assert (fwcheck.PORT_LO, fwcheck.PORT_HI, fwcheck.TM_PORT, fwcheck.FOR_CHOICES) == (2000, 2002, 8000, ("windows-client", "wsl"))


@pytest.mark.parametrize("for_", ["windows-client", "wsl"])
@pytest.mark.parametrize("case", FW_CASES["cases"], ids=[c["name"] for c in FW_CASES["cases"]])
def test_the_0_10_0_choice_judges_its_own_exe_as_the_default_judges_0_9_16_s(case, for_):
    """Every Phase 7 case with the 0.9.16 exe made the 0.10.0 exe gives the 0.9.16 verdicts, the line naming the version."""
    interp = [FW_CASES["interpreters"][0], VENV_010 + "\\Scripts\\python.exe"]
    snap = fwcheck.parse(_as_010(case["doc"]))
    got = fwcheck.result_lines(fwcheck.check(snap, for_, interp, carla="0.10.0"), for_, carla="0.10.0")
    assert got == [ln.replace("(%s)" % for_, "(%s, CARLA 0.10.0)" % for_, 1) for ln in case["expect"][for_]]


def test_each_choice_judges_its_own_exe_only(capsys):
    """A 0.9.16-exe rule open to every address fails the default and is another program's to the 0.10.0 choice (its ports
    Any, so neither arm (b) nor (c) judges it); the 0.10.0 exe's unscoped rule fails only the 0.10.0 choice."""
    today = next(c for c in FW_CASES["cases"] if c["name"] == "today")
    doc = json.dumps(today["doc"])
    interp = list(FW_CASES["interpreters"])
    assert fwcheck.main(["--for", "windows-client", "--no-tm"], runner=_Runner(out=doc), windows=True) == 1
    assert fwcheck.main(["--for", "windows-client", "--no-tm", "--carla", "0.9.16"], runner=_Runner(out=doc), windows=True) == 1
    assert fwcheck.main(["--for", "windows-client", "--no-tm", "--carla", "0.10.0"], runner=_Runner(out=doc), windows=True) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "fwcheck: PASS (windows-client, CARLA 0.10.0, no TM: P4 not applied)"
    assert all(ln.startswith("fwcheck: FAIL (windows-client, no TM: P4 not applied): P2: ") for ln in out[:-1])
    doc010 = json.dumps(_as_010(today["doc"]))
    assert fwcheck.main(["--for", "windows-client", "--no-tm"], runner=_Runner(out=doc010), windows=True) == 0
    assert fwcheck.main(["--for", "windows-client", "--no-tm", "--carla", "0.10.0"], runner=_Runner(out=doc010), windows=True) == 1
    assert fwcheck.run("windows-client", runner=_Runner(out=doc), interpreters=lambda: interp)[0] == 1


@pytest.mark.parametrize("name", ["interpreter-allow-any", "unbound-tm-port"])
def test_the_0_10_0_choice_without_a_traffic_manager_waives_p4_and_says_so(name):
    case = next(c for c in FW_CASES["cases"] if c["name"] == name)
    snap = fwcheck.parse(_as_010(case["doc"]))
    interp = [FW_CASES["interpreters"][0], VENV_010 + "\\Scripts\\python.exe"]
    for for_ in ("windows-client", "wsl"):
        assert fwcheck.result_lines(fwcheck.check(snap, for_, interp, tm=False, carla="0.10.0"), for_, tm=False, carla="0.10.0") == [
            "fwcheck: PASS (%s, CARLA 0.10.0, no TM: P4 not applied)" % for_]


def test_the_default_line_is_byte_for_byte_today_s_and_the_0_10_0_line_names_the_version(capsys):
    scoped = next(c for c in FW_CASES["cases"] if c["name"] == "scoped")
    doc = json.dumps(scoped["doc"])
    assert fwcheck.main(["--for", "windows-client"], runner=_Runner(out=doc), windows=True,
                        interpreters=lambda: list(FW_CASES["interpreters"])) == 0
    assert capsys.readouterr().out == "fwcheck: PASS (windows-client)\n"
    assert fwcheck.result_lines([], "wsl", tm=False) == ["fwcheck: PASS (wsl, no TM: P4 not applied)"]
    assert fwcheck.result_lines([], "wsl", carla="0.10.0") == ["fwcheck: PASS (wsl, CARLA 0.10.0)"]
    assert fwcheck.result_lines([("P1", "Public")], "wsl", carla="0.10.0") == ["fwcheck: FAIL (wsl, CARLA 0.10.0): P1: Public"]


def test_the_0_10_0_choice_reads_its_own_venv_s_interpreters(monkeypatch):
    seen = []
    monkeypatch.setattr(fwcheck, "read_interpreters", lambda venv=fwcheck.VENV: seen.append(venv) or ("C:\\py\\python.exe",))
    scoped = json.dumps(_as_010(next(c for c in FW_CASES["cases"] if c["name"] == "scoped")["doc"]))
    assert fwcheck.run("windows-client", runner=_Runner(out=scoped), carla="0.10.0")[0] == 0
    assert fwcheck.run("windows-client", runner=_Runner(out=scoped))[0] in (0, 1)
    assert seen == [VENV_010, fwcheck.VENV]
    assert fwcheck.interpreters_of("home = C:\\py\n", VENV_010) == ("C:\\py\\python.exe", VENV_010 + "\\Scripts\\python.exe")


def test_read_interpreters_reads_the_chosen_venv(monkeypatch):
    """The real reader (the test above replaces it) opens the chosen venv's pyvenv.cfg and names that venv's own
    interpreter. Were it to read 0.9.16's venv for the 0.10.0 choice, P4 would judge a rule for 0.9.16's interpreter and
    leave the one for E:\\CARLA\\venv312-010 unjudged."""
    import io
    opened = []

    def fake_open(path, encoding=None):
        opened.append(path)
        return io.StringIO("home = C:\\py\n")
    monkeypatch.setattr(fwcheck, "open", fake_open, raising=False)
    assert fwcheck.read_interpreters(VENV_010) == ("C:\\py\\python.exe", VENV_010 + "\\Scripts\\python.exe")
    assert fwcheck.read_interpreters() == ("C:\\py\\python.exe", fwcheck.VENV + "\\Scripts\\python.exe")
    assert opened == [VENV_010 + "\\pyvenv.cfg", fwcheck.VENV + "\\pyvenv.cfg"]


def test_an_unknown_carla_choice_is_refused():
    with pytest.raises(SystemExit):
        fwcheck.main(["--for", "wsl", "--carla", "0.9.15"], runner=_Runner(out="{}"), windows=True)
    with pytest.raises(KeyError):
        fwcheck.check(fwcheck.parse({}), "wsl", carla="0.9.15")


# =================================================================================================================
# The READMEs' 0.10.0 sections (spec-2 10.2)
# =================================================================================================================

def _section(path, heading):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## %s\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    assert m, (path.name, heading)
    return re.sub(r"\s+", " ", m.group(1))


def test_the_carla_readme_s_0_10_0_section_gives_the_commands_files_refusals_and_what_it_does_not_show():
    text = _section(CARLA_DIR / "README.md", "CARLA 0.10.0 (Phase 8 WP9b)")
    for s in ("follow010.py take --name", "follow010.py fwcheck --for", "encode010.py record --take", "encode010.py verify",
              "gpucheck.py", "fwcheck.py --carla 0.10.0", "E:\\CARLA\\venv312-010", "<yyyymmdd>-carla010-<n>", "on_tick",
              "passive", "carla-autoware", "profile 5", "PROFILE-NOT-COMPILED", "Town10HD_Opt", "vehicle.taxi.ford",
              "ego_vehicle", "FREE_MIB_MIN", "9,500", "steer_law", "wheel_deg", "flattening", "Traffic Manager",
              "REREAD_FRAMES", "IDLE_TIMEOUT_S", "does not demonstrate", "carla010_iso.py",
              # the consequence of the send policy's schedule for an interface below real time
              "slower than one frame per `FEEDER_REPEAT_CAP_MS`", "refuses it whole"):
        assert s in text, s
    for name in ("apply_settings", "tick", "load_world", "apply_physics_control", "apply_control", "set_target_velocity",
                 "spawn_actor", "get_trafficmanager"):
        assert "`%s`" % name in text, name


def test_the_sim_readme_s_0_10_0_section_states_the_law_and_its_status():
    text = _section(SIM_DIR / "README.md", "CARLA 0.10.0 (Phase 8 WP9b)")
    for s in ("carla010_iso.py", "C x s x |s|", "PROBED", "INFERRED", "E9", "E7", "degrees/s", "-w[2]", "carla_iso.py",
              "0.9.16", "understeer", "WP3c", "does not demonstrate"):
        assert s in text, s
