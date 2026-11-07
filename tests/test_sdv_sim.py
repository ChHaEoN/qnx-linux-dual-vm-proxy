"""The seeded kinematic signal simulator (sdv/sim/sigsim.py) and the CARLA sign helper
(sdv/sim/carla_iso.py): SDV plan Phase 1 steps 5 and 8.

Two groups. The pure tests import sigsim with the standard library only: the model's kinematics and
determinism, every sigsim envelope row re-checked here on the integrated trip (independently of
sigsim's own check), the clamp and the checker on scripts made to break a row, the whole trip packed
through vssframe and judged by the reference rules under the sigsim live-default profile (no false
reject), the wheelbase against the generated profile table, and the CARLA sign conversion.

The cantools and python-can tests run sigsim.py in its own venv (~/sdv-sim-venv, built from
sdv/sim/requirements.lock as sdv/sim/README.md says; SDV_SIM_VENV overrides the path) and skip with
that reason when it is absent: slice.dbc parses under the locked cantools; two recordings of one seed
are byte-identical; the log reads back with python-can's reader and decodes with cantools to the
model's values within half an LSB; every decoded sample passes rules 21-27; a log that differs from
the model's text fails, each way naming the term of verify's `ok` it breaks; a DBC that disagrees
with the contract is refused.

`live --check` and `record` are tested in the first group too, against a stand-in for python-can's
module and stubs for the cantools-dependent steps, so their exit codes, their pacing and what they
write and rename are pinned without a bus or a venv; so is how `verify` wires each term of its `ok`,
against a stand-in for cantools' database that answers with exact values.

Every number asserted here is a design value, a value of the generated contract, or computed from
them (the trip's own script values are sigsim's module constants, never re-typed); none is a
measurement. Recordings are written under pytest's tmp_path only: the tests that run `record`'s
command line in this process move HOME (and sigsim's REPO) into tmp_path first, so nothing can reach
the real ~/sdv-recordings or the working tree.
"""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIM_DIR = REPO / "sdv" / "sim"
FRAME_DIR = REPO / "sdv" / "frame"
SIGSIM = SIM_DIR / "sigsim.py"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"
SIM_LOCK = SIM_DIR / "requirements.lock"
SIM_VENV = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser()
SIM_PY = SIM_VENV / "bin" / "python"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (str(SIM_DIR), str(FRAME_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla_iso  # noqa: E402
import rules  # noqa: E402
import sigsim  # noqa: E402
import vssframe as vf  # noqa: E402

sys.dont_write_bytecode = _saved

try:
    C = vf.load_contract()
    _WHY = ""
except vf.ContractError as err:
    C = None
    _WHY = str(err)
NEEDS_CONTRACT = pytest.mark.skipif(C is None, reason="needs the generated contract: %s" % _WHY)
NEEDS_SIM_VENV = pytest.mark.skipif(
    not SIM_PY.exists(),
    reason="needs the sim venv ~/sdv-sim-venv built from sdv/sim/requirements.lock (sdv/sim/README.md; WSL Ubuntu-24.04)")

SPEC_SLOT_OF_HALF_LSB_KEY = {"v": 0, "delta": 2, "psi_dot": 3}
"""The generated contract's DBC_HALF_LSB is keyed by signal name, not by slot. This maps its keys to the slots of the
kind 4 signals they describe, which the kind 4 specification fixes in section 4.1 (the slot table: slot 0 is the
longitudinal velocity, 1 the longitudinal acceleration, 2 the steering angle, 3 the yaw rate, 4 the gear). A specification
pin on purpose: the contract carries no such map, so a change of the slot order must fail where it is used, and nowhere else."""

SEEDS = (0, 1, 2, 3, 7)
_TRIPS = {}


def trip(seed):
    if seed not in _TRIPS:
        _TRIPS[seed] = sigsim.simulate(seed, C)
    return _TRIPS[seed]


def run_sim(*args, check=True):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([str(SIM_PY), str(SIGSIM)] + [str(a) for a in args], capture_output=True, text=True, env=env, cwd=str(REPO))
    if check and p.returncode != 0:
        raise AssertionError("sigsim %s failed (%d): %s" % (args, p.returncode, p.stderr[-2000:]))
    return p


# A snippet run in the sim venv beside sigsim: a contract with some constants changed (the real one is never edited).
_SNIPPET_PRELUDE = """\
import json, sys, types
from pathlib import Path
sys.dont_write_bytecode = True
sys.path[:0] = [%r, %r]
import sigsim
import vssframe as vf
C = vf.load_contract()


def alt_contract(**changes):
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith("_")})
    for k, v in changes.items():
        setattr(ns, k, v)
    return ns

"""


def run_snippet(code, *args):
    """Run `code` in the sim venv with sigsim, vssframe, the contract C and alt_contract(**changes) at hand; it
    prints one JSON value, which is returned."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    src = _SNIPPET_PRELUDE % (str(SIM_DIR), str(FRAME_DIR)) + code
    p = subprocess.run([str(SIM_PY), "-c", src] + [str(a) for a in args], capture_output=True, text=True, env=env, cwd=str(REPO))
    if p.returncode != 0:
        raise AssertionError("snippet failed (%d): %s" % (p.returncode, p.stderr[-2000:]))
    return json.loads(p.stdout)


def demo_profile_id():
    """The compiled demo-ODD profile ('demo-odd' is its limit set in profiles.toml)."""
    ids = [int(r["id"]) for r in C.PROFILES if r["limit_set"] == "demo-odd" and r["compiled"]]
    assert len(ids) == 1, ids
    return ids[0]


def lcm_of_periods_ms():
    """The least common multiple of the two message periods sigsim sends (not of every period the DBC lists)."""
    n = 1
    for p in sigsim.setup(C).periods_ms.values():
        n = n * p // math.gcd(n, p)
    return n


def dyn_period():
    """The dynamics message's period [ms], from the generated contract through sigsim's setup."""
    su = sigsim.setup(C)
    return su.periods_ms[su.dyn_msg]


def locked_version(package):
    """The version sdv/sim/requirements.lock pins for a package."""
    m = re.search(r"^%s==(\S+)" % re.escape(package), SIM_LOCK.read_text(encoding="utf-8"), re.M)
    assert m, package
    return m.group(1)


# --- the design car and the contract -------------------------------------------------------------------

def test_the_generated_contract_loads_when_it_is_there():
    """Not marked NEEDS_CONTRACT: a loader that refuses the real contract must fail the tests that need it, not skip them.
    Only a contract that is not there (nothing generated yet) may leave them skipped."""
    if vf.contract_path().is_file():
        assert C is not None, _WHY


@NEEDS_CONTRACT
def test_wheelbase_is_the_live_default_profiles():
    """Spec 5.6: the sigsim profile's L equals sigsim's constant, and the demo-ODD profile is the same car."""
    su = sigsim.setup(C)
    rows = {r["id"]: r for r in C.PROFILES}
    pid = C.LIVE_DEFAULT_PROFILE["sigsim"]
    assert su.profile_id == pid
    assert su.wheelbase_mm == rows[pid]["l_mm"] == rows[demo_profile_id()]["l_mm"] == C.ENVELOPES["sigsim"]["wheelbase_mm"]
    assert trip(1).wheelbase_m == rows[pid]["l_mm"] / 1000.0


@NEEDS_CONTRACT
def test_periods_and_signals_come_from_the_contract():
    su = sigsim.setup(C)
    assert su.periods_ms == {m: C.DBC_PERIOD_MS[m] for m in (su.dyn_msg, su.gear_msg)}
    assert su.signals == tuple(C.SLOT_DBC_SIGNALS)
    assert set(C.SLOT_DBC_MESSAGES[:4]) == {su.dyn_msg} and C.SLOT_DBC_MESSAGES[4] == su.gear_msg


@NEEDS_CONTRACT
def test_envelope_is_the_contracts():
    env = sigsim.Envelope.from_contract(C)
    for k in env.__dataclass_fields__:
        assert getattr(env, k) == C.ENVELOPES["sigsim"][k]
    row = C.ENVELOPES["sigsim"]
    assert env.product_bound == pytest.approx(row["accel_while_steering"] * math.tan(math.radians(row["turn_steer_max"])))
    # the script drives inside it
    assert sigsim.LAUNCH_ACCEL <= env.launch_accel and sigsim.REVERSE_ACCEL <= env.launch_accel
    assert sigsim.STEER_RATE < env.steer_rate
    assert max(sigsim.APPROACH_DECEL, sigsim.REVERSE_BRAKE, sigsim.TURN_ENTRY_DECEL) <= env.braking_max
    assert sigsim.GEAR_SETTLE_MS > max(C.DBC_PERIOD_MS.values()) + min(C.DBC_PERIOD_MS.values())


# --- the model ----------------------------------------------------------------------------------------

@NEEDS_CONTRACT
@pytest.mark.parametrize("seed", SEEDS)
def test_trip_inside_every_envelope_row(seed):
    """Every sigsim envelope row (spec 5.3), re-checked on the integrated trip from its arrays."""
    tr = trip(seed)
    env = tr.setup.env
    assert tr.violations == [] and sum(tr.clamps.values()) == 0
    bound = env.accel_while_steering * math.tan(math.radians(env.turn_steer_max))
    for i in range(tr.duration_ms):
        v, vn, d, dn, a, r, g = tr.v[i], tr.v[i + 1], tr.d[i], tr.d[i + 1], tr.a[i], tr.r[i], tr.gear[i]
        dmax = max(abs(d), abs(dn))
        assert abs((vn - v) * 1000.0 - a) < 1e-6 and abs((dn - d) * 1000.0 - r) < 1e-6, i
        assert abs(r) <= env.steer_rate, i
        assert dmax <= env.turn_steer_max <= env.steer_max, i
        assert dmax == 0.0 or max(abs(v), abs(vn)) <= env.turn_speed_max, i
        assert abs(a) * math.tan(math.radians(dmax)) <= bound, i
        assert abs(a) <= (env.launch_accel if abs(vn) > abs(v) else env.braking_max), i
        assert abs(a) <= env.accel_while_steering or dmax <= env.braking_steer_max, i
        assert -env.reverse_speed_max <= vn <= env.cruise_speed, i
        assert (vn <= 0 or g > 0) and (vn >= 0 or g < 0), i
    for (t, old, new) in tr.gear_changes:
        assert tr.v[t] == 0.0 and old * new >= 0                          # at standstill, never + <-> -
    assert tr.v[-1] == 0.0 and tr.gear[-1] == 0 and tr.d[-1] == 0.0


@NEEDS_CONTRACT
@pytest.mark.parametrize("seed", SEEDS)
def test_trip_has_every_phase(seed):
    """Start, cruise, turn, brake, stop, reverse."""
    tr = trip(seed)
    env = tr.setup.env
    labels = [s[0] for s in tr.segments]
    for want in ("idle", "launch", "cruise", "turn", "hard brake", "stopped", "reverse", "reverse stop"):
        assert want in labels
    assert max(tr.v) == env.cruise_speed and min(tr.v) == -env.reverse_speed_max
    assert max(abs(d) for d in tr.d) > 0
    turning = [i for i, d in enumerate(tr.d) if d != 0.0]
    assert any(tr.v[i] > 0 for i in turning) and any(tr.v[i] < 0 for i in turning)
    assert min(tr.a) == -env.braking_max
    assert [g[2] for g in tr.gear_changes] == [1, 0, -1, 0]
    assert tr.duration_ms % lcm_of_periods_ms() == 0
    stop = dict((s[0], s) for s in tr.segments)["stopped"]
    assert all(tr.v[t] == 0.0 for t in range(stop[1], stop[2] + 1))


@NEEDS_CONTRACT
def test_kinematics_are_self_consistent():
    """psi_dot = v tan(delta) / L at every sample, and the heading is its integral."""
    tr = trip(1)
    L = tr.wheelbase_m
    for t in range(0, tr.duration_ms + 1, dyn_period()):
        v, a, d, y = tr.sample(t)
        assert y == pytest.approx(math.degrees(v * math.tan(math.radians(d)) / L), abs=1e-12)
        assert a == tr.a[t]
    total = sum(tr.v[i] * math.tan(math.radians(tr.d[i])) / L for i in range(tr.duration_ms)) / 1000.0
    assert tr.psi[-1] == pytest.approx(total, abs=1e-9)


@NEEDS_CONTRACT
def test_determinism_and_seed_dependence():
    a, b = sigsim.simulate(3, C), sigsim.simulate(3, C)
    assert (a.v, a.d, a.a, a.gear, a.psi) == (b.v, b.d, b.a, b.gear, b.psi)
    assert sigsim.model_messages(a) == sigsim.model_messages(b)
    assert sigsim.trip_params(3, a.setup.env) == sigsim.trip_params(3, a.setup.env)
    assert sigsim.trip_params(3, a.setup.env) != sigsim.trip_params(4, a.setup.env)
    assert trip(0).v != trip(1).v


def test_seed_must_be_a_non_negative_int():
    """trip_params refuses the seed before it reads the envelope, so the envelope here is a placeholder that holds
    no contract value: if it were read, the refusal would be an AttributeError, not the ValueError asked for."""
    placeholder = None
    for bad in (-1, 1.5, True, "1"):
        with pytest.raises(ValueError):
            sigsim.trip_params(bad, placeholder)


def _steering_trip(direction, steer_deg):
    """The smallest script that steers: engage `direction` (1 forward, -1 reverse), move at the speed a turn is
    allowed at, steer to steer_deg, hold, unwind, stop, neutral. Its own script, not a seed's outcome."""
    env = sigsim.Envelope.from_contract(C)
    Seg = sigsim.Seg
    fwd = direction > 0
    segs = [Seg("engage", gear=direction, hold_ms=sigsim.GEAR_SETTLE_MS),
            Seg("move", v_target=env.turn_speed_max if fwd else -env.reverse_speed_max,
                accel=sigsim.LAUNCH_ACCEL if fwd else sigsim.REVERSE_ACCEL),
            Seg("steer", d_target=steer_deg, steer_rate=sigsim.STEER_RATE, hold_ms=2 * sigsim.IDLE_MS),
            Seg("unwind", d_target=0.0, steer_rate=sigsim.STEER_RATE),
            Seg("stop", v_target=0.0, accel=sigsim.APPROACH_DECEL if fwd else sigsim.REVERSE_BRAKE, hold_ms=sigsim.GEAR_SETTLE_MS),
            Seg("neutral", gear=0, hold_ms=sigsim.IDLE_MS)]
    return sigsim.simulate(1, C, segments=segs)


@NEEDS_CONTRACT
@pytest.mark.parametrize("direction", [1, -1], ids=["forward", "reverse"])
@pytest.mark.parametrize("side", [1, -1], ids=["left", "right"])
def test_iso_8855_geometry(direction, side):
    """ISO 8855 (X forward, Y left, Z up): steering left (delta > 0) while moving forward turns the heading
    counterclockwise (psi grows) and leaves the car at y > 0; right mirrors it. In reverse the same steering angle
    turns the heading the other way (psi_dot = v tan(delta) / L with v < 0), while the car still ends up on the
    side the wheels point to, because it moves backward along an arc whose centre is on that side."""
    tr = _steering_trip(direction, side * sigsim.Envelope.from_contract(C).turn_steer_max / 2)
    assert tr.psi[0] == 0.0 and tr.y[0] == 0.0
    assert tr.psi[-1] != 0.0 and tr.y[-1] != 0.0
    assert (tr.psi[-1] > 0) == (direction * side > 0)
    assert (tr.y[-1] > 0) == (side > 0)
    assert (tr.x[-1] > 0) == (direction > 0)


@NEEDS_CONTRACT
def test_message_stream_order_and_counts():
    tr = trip(2)
    su = tr.setup
    msgs = sigsim.model_messages(tr)
    per = {m: sum(1 for x in msgs if x[1] == m) for m in (su.dyn_msg, su.gear_msg)}
    assert per == {m: tr.duration_ms // su.periods_ms[m] + 1 for m in per}
    for (t1, n1, _), (t2, n2, _) in zip(msgs, msgs[1:]):
        assert t1 < t2 or (t1 == t2 and n1 == su.dyn_msg and n2 == su.gear_msg)


def test_candump_line_format():
    """The writer's format, with ids of its own (not the slice's): zero-padded seconds and microseconds, upper-case hex."""
    assert sigsim.candump_line(1234, 0x123, bytes(range(8))) == "(0000000001.234000) vcan0 123#0001020304050607\n"
    assert sigsim.candump_line(0, 0x7FF, b"\xff" + bytes(7)) == "(0000000000.000000) vcan0 7FF#FF00000000000000\n"
    # an id below 0x100 keeps three digits, as candump writes it (an 11-bit id is always three hex digits)
    assert sigsim.candump_line(0, 0x07F, bytes(8)) == "(0000000000.000000) vcan0 07F#0000000000000000\n"
    assert sigsim.candump_line(0, 0x001, bytes(8)) == "(0000000000.000000) vcan0 001#0000000000000000\n"


# --- the clamp and the checker -------------------------------------------------------------------------

@NEEDS_CONTRACT
def test_checker_catches_each_row():
    """One step just past each envelope row, built from the contract's own row. A step is (v, d, a, r, gear): the next speed
    and steering angle follow from a and r, so only the row under test is broken."""
    env = sigsim.Envelope.from_contract(C)
    dt = sigsim.STEP_MS / 1000.0
    slow = env.turn_speed_max / 2            # a speed a turn is allowed at
    mid = env.turn_steer_max / 2

    def step(v, d, a, r, gear=1):
        return sigsim.check_step(v, d, v + a * dt, d + r * dt, a, r, gear, env)

    assert "steer_rate" in step(slow, 0.0, 0.0, env.steer_rate + 1.0)
    assert "turn_steer_max" in step(slow, env.turn_steer_max, 0.0, 5.0)                       # d + r dt is past it
    assert "turn_speed" in step(env.turn_speed_max + 1.0, 0.0, 0.0, 1.0)                     # any steering, above the turn speed
    assert "launch_accel" in step(1.0, 0.0, env.launch_accel + 0.5, 0.0)
    assert "braking_max" in step(env.cruise_speed / 2, 0.0, -(env.braking_max + 1.0), 0.0)
    assert "accel_while_steering" in step(slow, env.turn_steer_max, -(env.accel_while_steering + 0.1), 0.0)
    assert "braking_steer_max" in step(slow, env.braking_steer_max + 1.0, -(env.accel_while_steering + 0.5), 0.0)
    assert "cruise_speed" in step(env.cruise_speed, 0.0, 1.0, 0.0)
    assert "reverse_speed_max" in step(-env.reverse_speed_max, 0.0, -1.0, 0.0, gear=-1)
    assert "gear_direction" in step(0.0, 0.0, -1.0, 0.0)                                      # reversing in a forward gear
    assert "gear_direction" in step(0.0, 0.0, 1.0, 0.0, gear=0)                               # moving in neutral
    assert "gear_direction" in step(0.0, 0.0, -1.0, 0.0, gear=0)
    assert "a_x is not dv/dt" in sigsim.check_step(1.0, 0.0, 1.002, 0.0, 1.0, 0.0, 1, env)
    # the steering twin: the steering angle moved two steps' worth while the recorded rate says one
    assert "steering rate is not d delta/dt" in sigsim.check_step(slow, 0.0, slow, 2 * dt, 0.0, 1.0, 1, env)
    assert step(slow, mid, 0.0, sigsim.STEER_RATE) == []                                      # the script's own steering is inside
    # decelerating from just above turn_speed_max to just below it while steering: the step touches the row at its faster end
    assert step(env.turn_speed_max + 0.5 * dt, mid, -1.0, 0.0) == ["turn_speed"]
    # the product row's rounding allowance is far narrower than a part in 1e9: a step that far over the row names it
    # (braking_steer_max, which this step also breaks, implies it; the row names are what is pinned)
    assert "accel_while_steering" in step(slow, env.turn_steer_max, -env.accel_while_steering * (1 + 1e-9), 0.0)
    assert "accel_while_steering" not in step(slow, env.turn_steer_max, -env.accel_while_steering, 0.0)    # exactly on the row


@NEEDS_CONTRACT
def test_clamp_holds_a_script_that_asks_too_much():
    """A script asking for a hard launch, fast steering at speed and an over-speed is clamped back
    into the envelope, every row that acted is counted, and nothing leaves it."""
    Seg = sigsim.Seg
    env = sigsim.Envelope.from_contract(C)
    bad = [Seg("go", gear=1, hold_ms=sigsim.GEAR_SETTLE_MS),
           Seg("hard launch", v_target=env.cruise_speed + 5.0, accel=3 * env.launch_accel),
           Seg("slow", v_target=env.turn_speed_max - 1.0, accel=sigsim.APPROACH_DECEL),
           Seg("fast steer", d_target=1.5 * env.turn_steer_max, steer_rate=2.5 * env.steer_rate),
           Seg("hard brake in a turn", v_target=0.0, accel=1.5 * env.braking_max),
           Seg("straighten", d_target=0.0, steer_rate=sigsim.STEER_RATE),
           Seg("park", gear=0, hold_ms=sigsim.IDLE_MS)]
    tr = sigsim.simulate(1, C, segments=bad)
    assert tr.violations == []
    for row in ("launch_accel", "cruise_speed", "steer_rate", "turn_steer_max", "accel_while_steering"):
        assert tr.clamps[row] > 0, row
    assert max(tr.v) == env.cruise_speed and max(abs(d) for d in tr.d) == env.turn_steer_max


def _clamp_scripts():
    """One script per clamp row (turn_speed has two sites, each with its own), each asking for more than that row allows and
    each ending at rest in neutral, straight. Returns {case: (the row it makes the clamp act on, its segments)}. Every
    number is an envelope row or one of sigsim's own script constants."""
    env = sigsim.Envelope.from_contract(C)
    Seg = sigsim.Seg
    settle, idle = sigsim.GEAR_SETTLE_MS, sigsim.IDLE_MS
    turn_v = env.turn_speed_max                                        # the fastest a turn is allowed at
    half_steer = env.turn_steer_max / 2
    mid_steer = (env.braking_steer_max + env.turn_steer_max) / 2       # steering past braking_steer_max, inside turn_steer_max
    forward = [Seg("engage", gear=1, hold_ms=settle)]
    reverse = [Seg("engage reverse", gear=-1, hold_ms=settle)]
    neutral = [Seg("neutral", gear=0, hold_ms=idle)]
    straighten = Seg("straighten", d_target=0.0, steer_rate=sigsim.STEER_RATE)
    stop = Seg("stop", v_target=0.0, accel=sigsim.APPROACH_DECEL, hold_ms=settle)

    def launch_to(v):
        return Seg("launch", v_target=v, accel=sigsim.LAUNCH_ACCEL)

    def steer_to(d):
        return Seg("steer", d_target=d, steer_rate=sigsim.STEER_RATE)

    return {
        # asking a forward gear to roll back: the speed is held at zero
        "gear_direction": ("gear_direction", forward + [
            Seg("roll back", v_target=-env.reverse_speed_max / 2, accel=sigsim.REVERSE_ACCEL)] + neutral),
        # asking neutral (the gear the integrator starts in) to move off: the speed is held at zero
        "gear_direction_neutral": ("gear_direction", [
            Seg("pull away in neutral", v_target=turn_v / 2, accel=sigsim.LAUNCH_ACCEL)]),
        # reversing past reverse_speed_max
        "reverse_speed_max": ("reverse_speed_max", reverse + [
            Seg("too far back", v_target=-(env.reverse_speed_max + 1.0), accel=sigsim.REVERSE_ACCEL),
            Seg("stop", v_target=0.0, accel=sigsim.REVERSE_BRAKE, hold_ms=settle)] + neutral),
        # steering in while still decelerating through turn_speed_max: the steering waits until the speed is down
        "turn_speed_steering_in": ("turn_speed", forward + [
            launch_to(turn_v + 1.0),
            Seg("slow and steer", v_target=turn_v - 1.0, accel=sigsim.APPROACH_DECEL, d_target=half_steer, steer_rate=sigsim.STEER_RATE),
            straighten, stop] + neutral),
        # accelerating in a turn up to turn_speed_max and past it: the speed is held at the row
        "turn_speed_accelerating": ("turn_speed", forward + [
            launch_to(turn_v - 1.0), steer_to(half_steer),
            Seg("too fast in the turn", v_target=turn_v + 2.0, accel=sigsim.LAUNCH_ACCEL),
            straighten, stop] + neutral),
        # braking harder than braking_max
        "braking_max": ("braking_max", forward + [
            launch_to(env.cruise_speed),
            Seg("hard brake", v_target=0.0, accel=1.5 * env.braking_max, hold_ms=settle)] + neutral),
        # braking harder than accel_while_steering while steering past braking_steer_max
        "braking_steer_max": ("braking_steer_max", forward + [
            launch_to(turn_v), steer_to(mid_steer),
            Seg("brake in the turn", v_target=0.0, accel=env.accel_while_steering + 1.0),
            straighten] + neutral),
    }


@NEEDS_CONTRACT
@pytest.mark.parametrize("case", sorted(_clamp_scripts()) if C is not None else ["needs the contract"])
def test_every_clamp_row_holds_a_script_that_asks_for_too_much(case):
    """gear_direction (a forward gear asked to roll back, and neutral asked to move off), reverse_speed_max, turn_speed (both
    sites), braking_max and braking_steer_max: each row acts, is counted, and nothing leaves the envelope (simulate is strict,
    so a step outside it would raise). The scripts that run into a row they cannot pass also end their segment there: `stalled`."""
    row, segs = _clamp_scripts()[case]
    env = sigsim.Envelope.from_contract(C)
    tr = sigsim.simulate(1, C, segments=segs)
    assert tr.violations == []
    assert tr.clamps[row] > 0, tr.clamps
    if case in ("gear_direction", "gear_direction_neutral", "reverse_speed_max", "turn_speed_accelerating"):
        assert tr.clamps["stalled"] > 0
    if case in ("gear_direction", "gear_direction_neutral"):
        assert all(v == 0.0 for v in tr.v)                                     # held at zero, never rolled back or moved off
    if case == "reverse_speed_max":
        assert min(tr.v) == -env.reverse_speed_max
    if case == "turn_speed_steering_in":
        assert max(abs(d) for d in tr.d) == env.turn_steer_max / 2             # the steering did come, once the speed was down
    if case == "turn_speed_accelerating":
        assert max(tr.v) == env.turn_speed_max                                 # held at the row, steering
    if case == "braking_steer_max":
        assert min(tr.a) == -env.accel_while_steering                          # the deceleration was cut to the row


@NEEDS_CONTRACT
def test_clamp_step_pins_the_clamped_magnitudes():
    """Braking at braking_max in a turn between braking_steer_max and turn_steer_max: the product row cuts the deceleration
    to bound / tan(delta) first, which braking_steer_max (still exceeded) cuts to accel_while_steering. Under this envelope the
    product row alone never decides the final value -- the rows after it do -- so what pins it is that both rows act, in
    this order, and that the last one lands on the row exactly."""
    env = sigsim.Envelope.from_contract(C)
    dt = sigsim.STEP_MS / 1000.0
    v = env.turn_speed_max - 1.0
    d = (env.braking_steer_max + env.turn_steer_max) / 2
    v_next, d_next, a, r, hits = sigsim.clamp_step(v, d, v - env.braking_max * dt, d, -env.braking_max, 0.0, 1, env)
    assert hits == ["accel_while_steering", "braking_steer_max"]
    assert a == -env.accel_while_steering and (d_next, r) == (d, 0.0) and v_next == v + a * dt


@NEEDS_CONTRACT
def test_gear_change_while_moving_is_a_script_error():
    Seg = sigsim.Seg
    with pytest.raises(sigsim.ScriptError):
        sigsim.simulate(1, C, segments=[Seg("go", gear=1, hold_ms=600), Seg("roll", v_target=1.0, accel=1.0), Seg("r", gear=0)])
    with pytest.raises(sigsim.ScriptError):
        sigsim.simulate(1, C, segments=[Seg("go", gear=1), Seg("r", gear=-1)])


def _settle_script(hold_ms):
    """Engage forward, hold `hold_ms`, then roll, stop and go back to neutral (after holds of its own)."""
    Seg = sigsim.Seg
    return [Seg("go", gear=1, hold_ms=hold_ms), Seg("roll", v_target=1.0, accel=1.0),
            Seg("stop", v_target=0.0, accel=1.0, hold_ms=sigsim.GEAR_SETTLE_MS), Seg("n", gear=0, hold_ms=sigsim.GEAR_SETTLE_MS)]


@NEEDS_CONTRACT
def test_moving_too_soon_after_a_gear_change_is_refused():
    """The window is one gear period plus one dynamics period (inclusive of its last millisecond): moving at once, or
    anywhere inside it, is refused; holding for more than the window passes."""
    su = sigsim.setup(C)
    window = su.periods_ms[su.gear_msg] + su.periods_ms[su.dyn_msg]
    assert 2 < window < sigsim.GEAR_SETTLE_MS
    for hold in (0, window // 2, window - 1):          # the first motion comes at hold + 1 ms: the last of these lands on the window's last ms
        with pytest.raises(sigsim.EnvelopeError, match="gear change"):
            sigsim.simulate(1, C, segments=_settle_script(hold))
    tr = sigsim.simulate(1, C, segments=_settle_script(window + 1))
    assert tr.violations == [] and [g[2] for g in tr.gear_changes] == [1, 0]


@NEEDS_CONTRACT
@pytest.mark.parametrize("case", ["steered", "in_gear"])
def test_a_trip_that_does_not_end_at_rest_in_neutral_straight_is_refused(case):
    """Each script breaks no per-step row and ends wrong in exactly one way: steered (at rest, in neutral) or in a forward gear
    (at rest, straight). The refusal is the end-state one alone, so dropping the steering condition from the check lets the
    first through and dropping the gear condition the second. (A trip ending with a speed is not a third case: it cannot end
    moving in neutral, since moving in neutral breaks a per-step row, so the speed condition cannot be told from the gear's.)"""
    env = sigsim.Envelope.from_contract(C)
    Seg = sigsim.Seg
    scripts = {
        "steered": [Seg("steer", d_target=env.turn_steer_max / 2, steer_rate=sigsim.STEER_RATE, hold_ms=sigsim.IDLE_MS)],
        "in_gear": [Seg("engage", gear=1, hold_ms=sigsim.GEAR_SETTLE_MS)],
    }
    with pytest.raises(sigsim.EnvelopeError, match="does not end at rest in neutral, straight") as caught:
        sigsim.simulate(1, C, segments=scripts[case])
    assert str(caught.value).count("t=") == 1                   # no other violation came with it


# --- the whole trip through vssframe and the reference rules --------------------------------------------

@NEEDS_CONTRACT
@pytest.mark.parametrize("seed", SEEDS)
def test_whole_trip_passes_rules_21_to_27(seed):
    """Every sample, packed as a replay-mode bridge holding the latest value of each slot would pack
    it, is accepted under the sigsim live-default profile; rules 26 and 27 were actually exercised."""
    tr = trip(seed)
    st = sigsim.judge_stream(sigsim.model_messages(tr), tr.setup)
    assert st.frames == len(sigsim.sample_times(tr, tr.setup.dyn_msg))
    assert st.accepted == st.frames, st.as_dict()
    assert st.rule26_judged > 0 and st.rule27_checked > 0
    assert st.rule26_above_tol > 0                               # frames whose kinematic yaw exceeds tol: a zeroed yaw must fail there
    assert st.turning_frames > 0 and st.turning_outside_window == 0   # every turning frame is in rule 26's speed window
    assert st.rule26_max_residual < 1e-3                         # binary32 rounding only, far below tol
    # the age is the oldest used value's: at every instant both periods divide, the dynamics frame (first in log order) is
    # packed with the gear sample one gear period old, and no frame is older than that
    assert st.max_age_ms == tr.setup.periods_ms[tr.setup.gear_msg] <= C.AGE_MAX_MS and st.age_negative == 0


@NEEDS_CONTRACT
def test_the_rules_would_catch_a_broken_trip():
    """Not vacuous: the same trip with the yaw rate zeroed while turning, or the speed sign flipped in
    a forward gear, is rejected with 26 and 27."""
    tr = trip(1)
    su = tr.setup
    honest = sigsim.judge_stream(sigsim.model_messages(tr), su)
    assert honest.rule26_above_tol > 0
    zeroed = [(t, n, (v[0], v[1], v[2], 0.0) if n == su.dyn_msg else v) for t, n, v in sigsim.model_messages(tr)]
    st = sigsim.judge_stream(zeroed, su)
    assert set(st.reasons) == {rules.RSN_VSS_YAW}
    assert st.reasons[rules.RSN_VSS_YAW] == honest.rule26_above_tol       # exactly the frames whose kinematic yaw exceeds tol
    flipped = [(t, n, (-v[0],) + tuple(v[1:]) if n == su.dyn_msg else v) for t, n, v in sigsim.model_messages(tr)]
    st = sigsim.judge_stream(flipped, su)
    assert st.reasons.get(rules.RSN_VSS_GEAR, 0) > 0
    demo = sigsim.judge_stream(sigsim.model_messages(tr), su, profile_id=demo_profile_id())
    assert set(demo.reasons) == {rules.RSN_VSS_SPEED}            # the demo-ODD profile rejects honest cruise


@NEEDS_CONTRACT
def test_judge_stats_count_what_they_claim():
    """Hand-made samples: a turning one inside rule 26's speed window, a straight one inside it, and a turning one below
    and one above it. The counters the whole-trip tests rely on are shown here to be able to count."""
    su = sigsim.setup(C)
    p = rules.Tables.from_contract(C).profiles[su.profile_id]
    mid = (p.v26_lo + p.v26_hi) / 2
    steer = sigsim.Envelope.from_contract(C).turn_steer_max / 2
    samples = [(mid, steer), (mid, 0.0), (p.v26_lo / 2, steer), (p.v26_hi * 1.5, steer)]
    period = dyn_period()
    msgs = [(0, su.gear_msg, (1,))] + [(period * (i + 1), su.dyn_msg, (v, 0.0, d, 0.0)) for i, (v, d) in enumerate(samples)]
    st = sigsim.judge_stream(msgs, su)
    assert st.frames == len(samples)
    assert (st.turning_frames, st.turning_outside_window) == (3, 2)      # the turning ones; the two outside the window
    assert st.rule26_judged == 2                                         # the two inside it
    assert st.rule26_above_tol == 1                                      # the turning one's kinematic yaw exceeds tol; the straight one's is 0
    # every frame is packed with the gear sample at time 0: the last dynamics frame's oldest used value is that old (the age is
    # the oldest used value's, so a judge that forgot the gear sample's time would report 0)
    assert st.max_age_ms == msgs[-1][0] - msgs[0][0] and st.age_negative == 0


@NEEDS_CONTRACT
def test_rule26_above_tol_leaves_out_frames_rule_26_skips_for_their_lateral_acceleration():
    """Under a profile that bounds a_y (the generated table's profile with ay26_max: profile 3, compiled since Phase 7 WP2;
    extra_ids binds it while it is not compiled), rule 26 is skipped where the kinematic a_y exceeds the bound, so a zeroed
    yaw is not rejected there and the frame must not count toward `rule26_above_tol`; where a_y is inside the bound the same
    zeroed yaw is rejected, and it counts."""
    su = sigsim.setup(C)
    bounded = [int(r["id"]) for r in C.PROFILES if r["ay26_max"]]
    assert bounded
    tb = rules.Tables.from_contract(C, extra_ids=[i for i in bounded if i not in C.COMPILED_PROFILE_IDS])
    pid = bounded[0]
    p = tb.profiles[pid]
    delta = p.delta_max
    fast, slow = p.v26_hi, p.v26_lo                           # inside the speed window, at its two ends
    kin_fast, ay_fast = rules.kinematics(fast, delta, p.l_mm, tb)
    kin_slow, ay_slow = rules.kinematics(slow, delta, p.l_mm, tb)
    assert kin_fast > p.tol26 and ay_fast > p.ay26_max        # rule 26 would compare yaw here, but the a_y bound skips it
    assert kin_slow > p.tol26 and ay_slow <= p.ay26_max       # and here it compares
    period = dyn_period()
    msgs = [(0, su.gear_msg, (1,)), (period, su.dyn_msg, (fast, 0.0, delta, 0.0)), (2 * period, su.dyn_msg, (slow, 0.0, delta, 0.0))]
    st = sigsim.judge_stream(msgs, su, tables=tb, profile_id=pid)
    assert st.frames == 2 and st.rule26_judged == 2
    assert st.rule26_above_tol == 1                           # only the frame inside the a_y bound
    assert (st.accepted, st.reasons) == (1, {rules.RSN_VSS_YAW: 1})       # and the rule agrees: one frame rejected, for yaw


# --- live --check, record and verify's terms, against stand-ins (no bus, no venv) -----------------------------

class _Clock:
    """A virtual clock: sleeping advances it, nothing waits."""

    def __init__(self):
        self.origin = self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.0)


FOREIGN_ID = 0x7FF      # a frame of somebody else's on the channel, with an id of this test's own


def _fake_can(clock, lose=None, change=None, foreign=None, extended=None, remote=None, reorder=None, late=None,
              foreign_late=False):
    """A stand-in for python-can's module: sockets on one channel, a frame sent on one reaches every other, carrying the
    sender's id, extended-id flag and data. Each fault is the index of the frame it acts on. `lose`: the channel drops it.
    `change`: it flips its first byte. `extended` and `remote`: it flips the frame's extended-id or remote-frame flag.
    `reorder`: it is delivered after the frame that follows it. `foreign`: a third party's frame (FOREIGN_ID) appears on the
    channel right after it. `late`: the channel holds it back until the receiver's first blocking read (recv with a timeout),
    where it arrives; `foreign_late` (a flag) puts a third party's frame there too, after it. `sent_at` holds the clock's
    reading at each send, `arrived_at` its reading at each held-back arrival."""
    sent, sent_at, arrived_at = [], [], []

    class Message:
        def __init__(self, arbitration_id=0, is_extended_id=False, data=b"", is_remote_frame=False, **_kw):
            self.arbitration_id, self.is_extended_id, self.data = arbitration_id, is_extended_id, bytes(data)
            self.is_remote_frame = is_remote_frame

    class Bus:
        sockets = []

        def __init__(self, interface=None, channel=None, **_kw):
            self.queue = []             # what a read returns now
            self.after_next = []        # held for the next frame, then delivered behind it (reorder)
            self.until_blocking = []    # held for the first blocking read (late)
            self.blocked = False
            Bus.sockets.append(self)

        def send(self, msg):
            i = len(sent)
            sent.append(msg)
            sent_at.append(clock.now)
            if i == lose:
                return
            data = bytes(msg.data)
            if i == change:
                data = bytes([data[0] ^ 0x01]) + data[1:]
            for other in Bus.sockets:
                if other is self:
                    continue
                delivered = Message(msg.arbitration_id, bool(msg.is_extended_id) != (i == extended), data,
                                    is_remote_frame=bool(msg.is_remote_frame) != (i == remote))
                if i == reorder:
                    other.after_next.append(delivered)
                    continue
                if i == late:
                    other.until_blocking.append(delivered)
                    continue
                other.queue.append(delivered)
                other.queue.extend(other.after_next)
                other.after_next = []
                if i == foreign:
                    other.queue.append(Message(FOREIGN_ID, False, bytes(8)))

        def recv(self, timeout=None):
            if timeout and not self.blocked:
                self.blocked = True
                held = len(self.until_blocking) + int(foreign_late)
                self.queue.extend(self.until_blocking)
                if foreign_late:
                    self.queue.append(Message(FOREIGN_ID, False, bytes(8)))
                arrived_at.extend([clock.now] * held)
            if self.queue:
                return self.queue.pop(0)
            clock.sleep(timeout or 0.0)
            return None

        def shutdown(self):
            Bus.sockets.remove(self)

    return types.SimpleNamespace(Bus=Bus, Message=Message, sent=sent, sent_at=sent_at, arrived_at=arrived_at, clock=clock)


# Stand-in frames (t ms, CAN id, data): arbitrary ids, not the slice's.
STAND_IN_FRAMES = [(t, 0x7A0 + (t // 20) % 2, bytes([t % 251, 1, 2, 3, 4, 5, 6, 7])) for t in (0, 20, 40, 60, 80)]


def _stub_trip_pipeline(monkeypatch):
    """The trip is the real one for seed 1 (cached); the cantools steps are replaced by the stand-in frames."""
    cached = trip(1)                       # before the patch: trip() itself calls sigsim.simulate
    monkeypatch.setattr(sigsim, "simulate", lambda seed, contract=None, **_kw: cached)
    monkeypatch.setattr(sigsim, "load_dbc", lambda su, path=None: None)
    monkeypatch.setattr(sigsim, "encode_frames", lambda tr, db: STAND_IN_FRAMES)


def _stub_live(monkeypatch, **faults):
    """python-can's module and the clock replaced by the stand-ins; `faults` are _fake_can's."""
    clock = _Clock()
    fake = _fake_can(clock, **faults)
    monkeypatch.setitem(sys.modules, "can", fake)
    monkeypatch.setattr(sigsim, "time", types.SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep))
    _stub_trip_pipeline(monkeypatch)
    return fake


def _live(capsys, *args):
    rc = sigsim.main(["live", "--seed", "1"] + list(args))
    return rc, json.loads(capsys.readouterr().out)


@NEEDS_CONTRACT
def test_live_check_passes_when_every_frame_arrives_unchanged(monkeypatch, capsys):
    fake = _stub_live(monkeypatch)
    rc, out = _live(capsys, "--check")
    n = len(STAND_IN_FRAMES)
    assert rc == 0
    assert out == {"channel": sigsim.CHANNEL, "seed": 1, "sent": n, "received": n, "identical": True, "ok": True}
    assert [(m.arbitration_id, m.is_extended_id, bytes(m.data)) for m in fake.sent] == [(cid, False, d) for _t, cid, d in STAND_IN_FRAMES]


@NEEDS_CONTRACT
@pytest.mark.parametrize("args", [(), ("--check",)], ids=["send_only", "check"])
def test_live_sends_each_frame_at_its_time(monkeypatch, capsys, args):
    """The pacing: the clock reads t0 + t / 1000 at every send (t the frame's time [ms]), with and without --check."""
    fake = _stub_live(monkeypatch)
    rc, _out = _live(capsys, *args)
    assert rc == 0
    assert fake.sent_at == pytest.approx([fake.clock.origin + t / 1000.0 for t, _cid, _d in STAND_IN_FRAMES], abs=1e-9)


@NEEDS_CONTRACT
def test_live_check_keeps_reading_for_the_tail_after_the_last_frame(monkeypatch, capsys):
    """After the last send the check reads for CHECK_TAIL_S (the clock, not the frame count, ends it): so a frame of anyone
    else's that comes after the last frame is still seen, however early every own frame arrived."""
    fake = _stub_live(monkeypatch)
    rc, out = _live(capsys, "--check")
    assert rc == 0 and out["ok"] is True
    listened = fake.clock.now - fake.sent_at[-1]
    assert sigsim.CHECK_TAIL_S - 1e-6 <= listened < sigsim.CHECK_TAIL_S + 0.2   # one read (0.1 s) may overshoot the window


@NEEDS_CONTRACT
@pytest.mark.parametrize("fault,received_delta", [
    ("lose", -1), ("change", 0), ("foreign", 1), ("extended", 0), ("remote", 0), ("reorder", 0)])
def test_live_check_exits_1_on_a_lost_changed_foreign_reordered_or_retyped_frame(monkeypatch, capsys, fault, received_delta):
    """A frame lost, a frame changed, a frame of anyone else's on the channel, two frames in the other order, and a frame whose
    extended-id or remote-frame flag is not the one sent all fail the check: it compares everything the second socket
    receives, in order, so the channel must carry no other traffic while it runs."""
    _stub_live(monkeypatch, **{fault: 2})
    rc, out = _live(capsys, "--check")
    assert rc == 1
    assert out["ok"] is False and out["identical"] is False
    assert out["received"] == len(STAND_IN_FRAMES) + received_delta


@NEEDS_CONTRACT
def test_live_check_sees_a_foreign_frame_that_comes_after_the_last_own_frame(monkeypatch, capsys):
    """The foreign frame arrives on the first blocking read after the last send, when every own frame has been received
    already: a check that stopped reading once it had as many frames as it sent would pass."""
    fake = _stub_live(monkeypatch, foreign_late=True)
    rc, out = _live(capsys, "--check")
    assert rc == 1 and out["ok"] is False and out["identical"] is False
    assert out["received"] == len(STAND_IN_FRAMES) + 1
    assert len(fake.arrived_at) == 1 and fake.arrived_at[0] >= fake.sent_at[-1]      # it came on the read after the last send


@NEEDS_CONTRACT
def test_live_check_counts_the_last_own_frame_when_it_is_late(monkeypatch, capsys):
    """The last frame reaches the second socket only on its first blocking read, after every send and its drain: it is counted
    within the tail window, and the check passes. With no tail it would be lost (received n - 1, ok False)."""
    n = len(STAND_IN_FRAMES)
    fake = _stub_live(monkeypatch, late=n - 1)
    rc, out = _live(capsys, "--check")
    assert rc == 0 and out == {"channel": sigsim.CHANNEL, "seed": 1, "sent": n, "received": n, "identical": True, "ok": True}
    assert len(fake.arrived_at) == 1 and fake.sent_at[-1] <= fake.arrived_at[0] <= fake.sent_at[-1] + sigsim.CHECK_TAIL_S


@NEEDS_CONTRACT
def test_live_check_needs_at_least_one_frame_sent(monkeypatch, capsys):
    """--seconds that leaves no frame sends nothing, and nothing received is not a delivery: ok False, exit 1."""
    _stub_live(monkeypatch)
    rc, out = _live(capsys, "--check", "--seconds=-1")
    assert rc == 1
    assert out == {"channel": sigsim.CHANNEL, "seed": 1, "sent": 0, "received": 0, "identical": True, "ok": False}


@NEEDS_CONTRACT
def test_live_without_check_makes_no_claim_about_delivery(monkeypatch, capsys):
    _stub_live(monkeypatch, lose=1)                   # nothing listens, so the lost frame is not seen
    rc, out = _live(capsys)
    assert rc == 0 and out == {"channel": sigsim.CHANNEL, "seed": 1, "sent": len(STAND_IN_FRAMES)}


@NEEDS_CONTRACT
def test_live_seconds_limits_the_frames_and_still_checks(monkeypatch, capsys):
    _stub_live(monkeypatch)
    rc, out = _live(capsys, "--check", "--seconds", "0.045")         # the stand-in frames at 0, 20 and 40 ms
    assert rc == 0 and out["sent"] == out["received"] == 3 and out["ok"] is True


@NEEDS_CONTRACT
@pytest.mark.parametrize("index", range(len(STAND_IN_FRAMES)))
def test_live_seconds_includes_a_frame_exactly_at_the_limit(monkeypatch, capsys, index):
    """--seconds S sends every frame at or before S: S equal to one stand-in frame's time sends that frame and every one
    before it, and a limit a millisecond short of it leaves it out."""
    t_ms = STAND_IN_FRAMES[index][0]
    assert t_ms / 1000.0 * 1000 == t_ms                              # S * 1000 is exactly the frame's time in floating point
    _stub_live(monkeypatch)
    rc, out = _live(capsys, "--check", "--seconds=%r" % (t_ms / 1000.0))
    assert rc == 0 and out["sent"] == out["received"] == index + 1 and out["ok"] is True
    _stub_live(monkeypatch)
    _rc, out = _live(capsys, "--check", "--seconds=%r" % ((t_ms - 1) / 1000.0))
    assert out["sent"] == index


def _stub_record(monkeypatch, verify_result):
    """record's pipeline with verify replaced: `seen` holds what was on disk when verify ran."""
    seen = {}
    _stub_trip_pipeline(monkeypatch)

    def fake_verify(log, seed, contract=None):
        seen["on_disk"] = sorted(q.name for q in log.parent.iterdir())
        if isinstance(verify_result, BaseException):
            raise verify_result
        return verify_result

    monkeypatch.setattr(sigsim, "verify", fake_verify)
    return seen


LOG_SHA = sigsim.LOG_NAME + ".sha256"


@NEEDS_CONTRACT
def test_record_writes_the_manifest_line_only_after_verify_passes(monkeypatch, tmp_path):
    seen = _stub_record(monkeypatch, {"ok": True})
    out = tmp_path / "rec"
    res = sigsim.record(1, out, "20260930-sigsim-1")
    assert seen["on_disk"] == sorted([sigsim.LOG_NAME, LOG_SHA])             # verify ran before the manifest line existed
    assert sorted(q.name for q in out.iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA, "manifest-line.json", "summary.json"])
    assert res["dir"] == str(out) and res["recorded"] is True
    assert json.loads((out / "manifest-line.json").read_text())["recording"]["path"] == str(out / sigsim.LOG_NAME)


@NEEDS_CONTRACT
def test_a_recording_that_fails_verification_has_no_manifest_line_and_frees_its_name(monkeypatch, tmp_path):
    _stub_record(monkeypatch, {"ok": False})
    out, failed = tmp_path / "rec", tmp_path / "rec.failed"
    res = sigsim.record(1, out, "20260930-sigsim-1")
    assert not out.exists() and failed.is_dir()
    assert sorted(q.name for q in failed.iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA, "summary.json"])   # no manifest line
    assert res["dir"] == str(failed) and res["recorded"] is False
    summary = json.loads((failed / "summary.json").read_text())
    assert summary["verify"] == {"ok": False} and summary["dir"] == str(failed) and summary["recorded"] is False
    sigsim.record(1, out, "20260930-sigsim-1")                # the name is free again; a second failure does not collide
    assert (tmp_path / "rec.failed2").is_dir() and not out.exists()
    sigsim.record(1, out, "20260930-sigsim-1")                # nor does a third: the suffix keeps counting past the first collision
    assert (tmp_path / "rec.failed3").is_dir() and not out.exists()
    assert sorted(q.name for q in tmp_path.iterdir()) == ["rec.failed", "rec.failed2", "rec.failed3"]


@NEEDS_CONTRACT
def test_a_verify_that_raises_leaves_no_manifest_line_under_the_name(monkeypatch, tmp_path):
    """summary.json is written for either verdict, but not when verify itself raises: the failed directory then holds the
    log and its sha256 only."""
    _stub_record(monkeypatch, RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        sigsim.record(1, tmp_path / "rec", "20260930-sigsim-1")
    assert not (tmp_path / "rec").exists()
    assert sorted(q.name for q in (tmp_path / "rec.failed").iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA])


@NEEDS_CONTRACT
def test_an_interrupt_during_verify_frees_the_name_and_is_re_raised(monkeypatch, tmp_path):
    """KeyboardInterrupt is a BaseException, not an Exception: the directory is renamed all the same."""
    _stub_record(monkeypatch, KeyboardInterrupt())
    out = tmp_path / "rec"
    with pytest.raises(KeyboardInterrupt):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert not out.exists()
    assert sorted(q.name for q in (tmp_path / "rec.failed").iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA])


@NEEDS_CONTRACT
def test_a_failure_to_build_the_manifest_line_of_a_passing_recording_marks_it_failed(monkeypatch, tmp_path):
    _stub_record(monkeypatch, {"ok": True})

    def broken(*_a, **_kw):
        raise RuntimeError("no entry")

    monkeypatch.setattr(sigsim, "scenario_entry", broken)
    out = tmp_path / "rec"
    with pytest.raises(RuntimeError, match="no entry"):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert not out.exists()
    assert sorted(q.name for q in (tmp_path / "rec.failed").iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA])


@NEEDS_CONTRACT
@pytest.mark.parametrize("target", [sigsim.MANIFEST_NAME, sigsim.SUMMARY_NAME])
def test_a_failed_write_after_verification_leaves_no_manifest_line_and_frees_the_name(monkeypatch, tmp_path, target):
    """The write of `target` fails after writing it (a full disk leaves a partial file): the manifest line is taken away, the
    directory is renamed and the error re-raised."""
    _stub_record(monkeypatch, {"ok": True})
    real = Path.write_text

    def flaky(self, *args, **kwargs):
        n = real(self, *args, **kwargs)
        if self.name == target:
            raise OSError("disk full")
        return n

    monkeypatch.setattr(Path, "write_text", flaky)
    out = tmp_path / "rec"
    with pytest.raises(OSError, match="disk full"):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert not out.exists()
    held = sorted(q.name for q in (tmp_path / "rec.failed").iterdir())
    assert sigsim.MANIFEST_NAME not in held and sigsim.LOG_NAME in held
    monkeypatch.setattr(Path, "write_text", real)
    sigsim.record(1, out, "20260930-sigsim-1")                # the name is free again
    assert (out / sigsim.MANIFEST_NAME).is_file()


@NEEDS_CONTRACT
@pytest.mark.parametrize("fault", ["log_write_interrupted", "log_read_back_fails", "sha256_write_fails"])
def test_a_stop_while_the_log_and_its_sha256_are_written_frees_the_name(monkeypatch, tmp_path, fault):
    """The protected part starts the moment the directory exists: a log half written when an interrupt comes, a log that cannot
    be read back, and a sha256 file whose write fails each leave nothing under the name. What was written is in <name>.failed,
    the error is re-raised, and the name is free for a re-record."""
    _stub_record(monkeypatch, {"ok": True})
    real = {"write_bytes": Path.write_bytes, "read_bytes": Path.read_bytes, "write_text": Path.write_text}

    def half_then_interrupt(self, data):
        if self.name == sigsim.LOG_NAME:
            real["write_bytes"](self, data[:len(data) // 2])
            raise KeyboardInterrupt()
        return real["write_bytes"](self, data)

    def unreadable(self):
        if self.name == sigsim.LOG_NAME:
            raise OSError("log unreadable")
        return real["read_bytes"](self)

    def sha256_write_fails(self, *args, **kwargs):
        n = real["write_text"](self, *args, **kwargs)
        if self.name == LOG_SHA:
            raise OSError("disk full")                          # a full disk leaves a partial file: this one is written, then fails
        return n

    method, patched, error, held = {
        "log_write_interrupted": ("write_bytes", half_then_interrupt, KeyboardInterrupt, [sigsim.LOG_NAME]),
        "log_read_back_fails": ("read_bytes", unreadable, OSError, [sigsim.LOG_NAME]),
        "sha256_write_fails": ("write_text", sha256_write_fails, OSError, [sigsim.LOG_NAME, LOG_SHA]),
    }[fault]
    monkeypatch.setattr(Path, method, patched)
    out, failed = tmp_path / "rec", tmp_path / "rec.failed"
    with pytest.raises(error):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert not out.exists()
    assert sorted(q.name for q in failed.iterdir()) == sorted(held)
    if fault == "log_write_interrupted":
        assert (failed / sigsim.LOG_NAME).stat().st_size == len(sigsim.candump_text(STAND_IN_FRAMES)) // 2     # half a log
    monkeypatch.setattr(Path, method, real[method])
    res = sigsim.record(1, out, "20260930-sigsim-1")          # the name is free again
    assert res["recorded"] is True and (out / sigsim.MANIFEST_NAME).is_file() and failed.is_dir()


@NEEDS_CONTRACT
def test_a_directory_that_already_exists_is_refused_and_left_alone(monkeypatch, tmp_path):
    """Creating the directory is outside the protected part: what is under the name is somebody's recording, and refusing to
    overwrite it must not rename it to <name>.failed."""
    _stub_record(monkeypatch, {"ok": True})
    out = tmp_path / "rec"
    out.mkdir()
    (out / "mine.txt").write_text("a recording", encoding="ascii")
    with pytest.raises(FileExistsError):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert [q.name for q in tmp_path.iterdir()] == ["rec"]
    assert [q.name for q in out.iterdir()] == ["mine.txt"] and (out / "mine.txt").read_text() == "a recording"


@NEEDS_CONTRACT
def test_a_failed_verdicts_summary_that_cannot_be_written_raises_that_error_alone(monkeypatch, tmp_path):
    """verify says not ok: the directory is renamed to <name>.failed and the summary is written into it. When that write fails
    the error that comes out is the write's, not a second one from trying to rename the directory that is already renamed, and
    the failed directory holds the log and its sha256."""
    _stub_record(monkeypatch, {"ok": False})
    real = Path.write_text

    def flaky(self, *args, **kwargs):
        if self.name == sigsim.SUMMARY_NAME:
            raise OSError("disk full")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(OSError, match="disk full"):
        sigsim.record(1, tmp_path / "rec", "20260930-sigsim-1")
    assert sorted(q.name for q in tmp_path.iterdir()) == ["rec.failed"]
    assert sorted(q.name for q in (tmp_path / "rec.failed").iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA])


@NEEDS_CONTRACT
def test_an_interrupt_while_a_failed_recording_is_renamed_still_frees_the_name(monkeypatch, tmp_path):
    """verify says not ok and the rename to <name>.failed is what an interrupt lands in (the first attempt is interrupted before
    it renames anything): the handler renames the directory, so nothing is left under the name, and the interrupt is re-raised."""
    _stub_record(monkeypatch, {"ok": False})
    real, calls = sigsim._mark_failed, []

    def interrupted_once(out_dir):
        calls.append(out_dir)
        if len(calls) == 1:
            raise KeyboardInterrupt()
        return real(out_dir)

    monkeypatch.setattr(sigsim, "_mark_failed", interrupted_once)
    out = tmp_path / "rec"
    with pytest.raises(KeyboardInterrupt):
        sigsim.record(1, out, "20260930-sigsim-1")
    assert len(calls) == 2 and not out.exists()
    assert sorted(q.name for q in tmp_path.iterdir()) == ["rec.failed"]
    assert sorted(q.name for q in (tmp_path / "rec.failed").iterdir()) == sorted([sigsim.LOG_NAME, LOG_SHA])     # no summary, no manifest line


@pytest.fixture
def fake_repo(monkeypatch, tmp_path):
    """sigsim's REPO moved to a directory of this test's own (tmp_path/repo), so that what a test records is outside it
    wherever pytest keeps its temporary files, and what it means to record inside it can be tried without touching the tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sigsim, "REPO", repo)
    return repo


@NEEDS_CONTRACT
@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1)])
def test_record_exits_1_when_verification_fails(monkeypatch, tmp_path, capsys, fake_repo, ok, code):
    _stub_record(monkeypatch, {"ok": ok})
    rc = sigsim.main(["record", "--seed", "1", "--out", str(tmp_path / "rec"), "--date", "20260930"])
    assert rc == code
    assert json.loads(capsys.readouterr().out)["recorded"] is ok


@NEEDS_CONTRACT
@pytest.mark.parametrize("patched", [False, True], ids=["default_root", "patched_default_root"])
def test_a_suffix_gives_a_re_record_a_directory_of_its_own_and_keeps_the_home_relative_path(monkeypatch, tmp_path, capsys, fake_repo, patched):
    """`record --seed 1 --suffix b` is <date>-sigsim-1b, next to <date>-sigsim-1, and the manifest line keeps the
    ~/<root>/... form of the path. HOME is moved into tmp_path first, so the default root (and a patched one) resolves there:
    nothing can reach the real ~/sdv-recordings, which this asserts before anything is written."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root_name = "sdv-recordings"
    if patched:
        root_name = "elsewhere"
        monkeypatch.setattr(sigsim, "DEFAULT_ROOT", Path("~") / root_name)
    else:
        assert str(sigsim.DEFAULT_ROOT) == "~/sdv-recordings"            # the plan's path, in the ~ form the manifest line keeps
    assert sigsim.DEFAULT_ROOT.expanduser() == home / root_name
    _stub_record(monkeypatch, {"ok": True})
    names = []
    for suffix in ((), ("--suffix", "b"), ("--suffix", "c2")):
        rc = sigsim.main(["record", "--seed", "1", "--date", "20260930"] + list(suffix))
        res = json.loads(capsys.readouterr().out)
        assert rc == 0 and res["recorded"] is True
        names.append(res["name"])
        entry = json.loads((home / root_name / res["name"] / sigsim.MANIFEST_NAME).read_text())
        assert entry["name"] == res["name"] and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", res["name"])
        assert entry["recording"]["path"] == "~/%s/%s/%s" % (root_name, res["name"], sigsim.LOG_NAME)
    assert names == ["20260930-sigsim-1", "20260930-sigsim-1b", "20260930-sigsim-1c2"]
    assert sorted(q.name for q in (home / root_name).iterdir()) == sorted(names)


@pytest.mark.parametrize("bad", ["", "B", "a b", "a-b", "a_b", "abcdefghi", "é", "a/b", "..", "0", "2", "2b", "1c2", "a" * 9])
def test_a_bad_suffix_is_refused_before_anything_is_written(monkeypatch, capsys, bad):
    monkeypatch.setattr(sigsim, "record", lambda *a, **k: pytest.fail("record must not run"))
    with pytest.raises(SystemExit) as exc:
        sigsim.main(["record", "--seed", "1", "--suffix", bad])
    assert exc.value.code == 2 and "--suffix" in capsys.readouterr().err


def test_the_suffix_is_a_lower_case_letter_then_up_to_seven_letters_or_digits():
    """A letter first: a suffix that began with a digit would extend the seed (--seed 1 --suffix 2 is --seed 12's name)."""
    for ok in ("a", "b", "c2", "b2", "abcdefg1", "a" * 8, "z9"):
        assert sigsim._suffix(ok) == ok
    for bad in ("", "a" * 9, "A", "a.b", "0", "2b", "9z", "1" * 8):
        with pytest.raises(argparse.ArgumentTypeError):
            sigsim._suffix(bad)


def test_no_seed_and_suffix_can_make_another_seeds_bare_name(monkeypatch, capsys, tmp_path, fake_repo):
    """Names are <date>-sigsim-<seed> and <date>-sigsim-<seed><suffix>. Of the suffixes tried, the ones that begin with a digit
    are refused (they would turn --seed 1 --suffix 2 into --seed 12's name) and the rest give names that are no bare seed's and
    that no other (seed, suffix) pair gives."""
    names, refused = {}, set()
    monkeypatch.setattr(sigsim, "record", lambda seed, out, name, shown=None: {"name": name, "recorded": True})
    for seed in (1, 12, 120, 2):
        for suffix in (None, "b", "c2", "x1", "2", "0", "2b"):
            args = ["record", "--seed", str(seed), "--date", "20260930", "--root", str(tmp_path / "root")]
            try:
                assert sigsim.main(args + (["--suffix", suffix] if suffix else [])) == 0
            except SystemExit as exc:
                assert exc.code == 2
                refused.add(suffix)
                continue
            name = json.loads(capsys.readouterr().out)["name"]
            assert name not in names, (name, names.get(name), (seed, suffix))
            names[name] = (seed, suffix)
            assert bool(suffix) == (re.fullmatch(r"\d{8}-sigsim-\d+", name) is None), name       # only a bare name is all digits
    assert refused == {"2", "0", "2b"}
    assert len(names) == 4 * 4


def test_recordings_inside_the_repository_are_refused_except_under_sdv_out(fake_repo):
    """Inside the tree a recording would leave files git does not ignore (only *.log and sdv-out/ are): refused, with paths
    compared after resolving them (`..`, a sibling whose name merely starts with sdv-out) and the repository itself included."""
    for path in (fake_repo, fake_repo / "rec", fake_repo / "sdv" / "sim" / "rec", fake_repo / "sdv-outer" / "rec",
                 fake_repo / "sdv-out" / ".." / "rec", fake_repo / "sdv-out" / ".." / ".." / "x" / ".." / "repo" / "rec"):
        assert sigsim.inside_repo(path), path
    for path in (fake_repo / "sdv-out", fake_repo / "sdv-out" / "rec", fake_repo / "sdv-out" / "a" / "b",
                 fake_repo.parent / "rec", fake_repo.parent / "repo2" / "rec", Path("/") / "tmp" / "sdv-rec"):
        assert not sigsim.inside_repo(path), path


@pytest.mark.parametrize("where", ["out_in_repo", "out_in_subdirectory", "root_in_repo"])
def test_record_refuses_to_write_inside_the_repository(monkeypatch, capsys, fake_repo, where):
    monkeypatch.setattr(sigsim, "record", lambda *a, **k: pytest.fail("record must not run"))
    where_args = {"out_in_repo": ["--out", str(fake_repo / "rec")],
                  "out_in_subdirectory": ["--out", str(fake_repo / "sdv" / "sim" / "rec")],
                  "root_in_repo": ["--root", str(fake_repo / "sdv")]}[where]
    with pytest.raises(SystemExit) as exc:
        sigsim.main(["record", "--seed", "1", "--date", "20260930"] + where_args)
    assert exc.value.code == 2 and "inside the repository" in capsys.readouterr().err


@NEEDS_CONTRACT
@pytest.mark.parametrize("option", ["--out", "--root"])
def test_record_writes_under_sdv_out_inside_the_repository(monkeypatch, tmp_path, capsys, fake_repo, option):
    """sdv-out/ is the one place inside the tree git ignores as a whole; this one is tmp_path/repo/sdv-out, not the real one."""
    _stub_record(monkeypatch, {"ok": True})
    base = fake_repo / "sdv-out" / "rec"
    arg = base if option == "--out" else base.parent
    assert sigsim.main(["record", "--seed", "1", "--date", "20260930", option, str(arg)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["recorded"] is True and (Path(res["dir"]) / sigsim.MANIFEST_NAME).is_file()
    assert Path(res["dir"]).parent == base.parent
    # not under the default root: the manifest line gives the path the log was written to, not the ~ form of another place
    entry = json.loads((Path(res["dir"]) / sigsim.MANIFEST_NAME).read_text())
    assert entry["recording"]["path"] == str(Path(res["dir"]) / sigsim.LOG_NAME)


@NEEDS_CONTRACT
@pytest.mark.parametrize("how", ["root_expanded_by_the_shell", "root_with_the_tilde", "out_under_the_default_root"])
def test_a_recording_under_the_default_root_keeps_the_home_relative_path_however_it_was_named(monkeypatch, tmp_path, capsys, fake_repo, how):
    """The ~ form depends on where the recording lies, not on how the command line spelled it: --root as a shell expands it
    (an absolute path), --root with the tilde left for sigsim to expand, and an --out inside the default root all give
    ~/sdv-recordings/.../sigsim.log. HOME is moved into tmp_path first, so none of this can reach the real ~/sdv-recordings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert sigsim.DEFAULT_ROOT.expanduser() == home / "sdv-recordings"
    _stub_record(monkeypatch, {"ok": True})
    home_root = home / "sdv-recordings"
    args = {"root_expanded_by_the_shell": ["--root", str(home_root)],
            "root_with_the_tilde": ["--root", "~/sdv-recordings"],
            "out_under_the_default_root": ["--out", str(home_root / "by-hand")]}[how]
    assert sigsim.main(["record", "--seed", "1", "--date", "20260930"] + args) == 0
    res = json.loads(capsys.readouterr().out)
    leaf = "by-hand" if how == "out_under_the_default_root" else res["name"]
    assert Path(res["dir"]) == home_root / leaf
    entry = json.loads((Path(res["dir"]) / sigsim.MANIFEST_NAME).read_text())
    assert entry["recording"]["path"] == "~/sdv-recordings/%s/%s" % (leaf, sigsim.LOG_NAME)
    assert sorted(q.name for q in tmp_path.iterdir()) == ["home", "repo"]                 # nothing went anywhere else


@NEEDS_CONTRACT
@pytest.mark.parametrize("option", ["--out", "--root"])
def test_a_tilde_in_out_or_root_is_expanded_to_home_not_made_a_directory_in_the_working_directory(monkeypatch, tmp_path, capsys, fake_repo, option):
    """A quoted `~/...` reaches sigsim unexpanded: it must go to HOME. HOME and the working directory are both inside tmp_path,
    so an unexpanded `~` would make a directory of that name in the working directory, where this test looks for it."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(cwd)
    _stub_record(monkeypatch, {"ok": True})
    assert sigsim.main(["record", "--seed", "1", "--date", "20260930", option, "~/rec"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert Path(res["dir"]) == (home / "rec" if option == "--out" else home / "rec" / res["name"])
    assert (Path(res["dir"]) / sigsim.MANIFEST_NAME).is_file()
    assert not (cwd / "~").exists() and list(cwd.iterdir()) == []


def _fullwidth(digits):
    """The same digits in the fullwidth form (U+FF10..U+FF19): str.isdigit() is true of them, and strptime takes them in a year."""
    return "".join(chr(0xFF10 + int(c)) for c in digits)


@pytest.mark.parametrize("bad", ["abc", "2026093", "202609300", _fullwidth("20260930"), _fullwidth("2026") + "0930", "2026093" + chr(0xB2),
                                 "20261399", "20230229", "20260631"],
                         ids=["letters", "seven_digits", "nine_digits", "fullwidth_digits", "fullwidth_year_only", "superscript_digit",
                              "month_13", "feb_29_in_a_common_year", "june_31"])
def test_a_date_that_is_not_an_ascii_calendar_date_is_refused_before_anything_is_written(monkeypatch, capsys, bad):
    """The refusal is the date's own (its message names --date): a fullwidth year with an ASCII month and day is a date to
    strptime, and only the ASCII test keeps it out of the name before the name's own check would have to."""
    monkeypatch.setattr(sigsim, "record", lambda *a, **k: pytest.fail("record must not run"))
    with pytest.raises(SystemExit) as exc:
        sigsim.main(["record", "--seed", "1", "--date", bad])
    assert exc.value.code == 2 and "--date" in capsys.readouterr().err


def test_a_real_calendar_date_is_taken_as_the_name_s_date(monkeypatch, capsys, tmp_path, fake_repo):
    monkeypatch.setattr(sigsim, "record", lambda seed, out, name, shown=None: {"name": name, "recorded": True})
    for date in ("20240229", "20261231", "20260101"):                  # a leap day, and the year's last and first days
        assert sigsim.main(["record", "--seed", "1", "--date", date, "--root", str(tmp_path / "root")]) == 0
        assert json.loads(capsys.readouterr().out)["name"] == "%s-sigsim-1" % date


def test_a_name_that_is_not_a_manifest_line_name_is_refused_before_anything_is_written(monkeypatch, capsys, tmp_path, fake_repo):
    """The whole name must be [a-z0-9][a-z0-9-]{0,47}: only a very long seed can break it (the date and the suffix are checked
    on their own). Names of exactly 48 characters are taken, with and without a suffix; one character more is refused."""
    names = []
    monkeypatch.setattr(sigsim, "record", lambda seed, out, name, shown=None: names.append(name) or {"name": name, "recorded": True})
    root = str(tmp_path / "root")
    room = 48 - len("20260930-sigsim-")                                   # the seed's digits when there is no suffix
    for seed, suffix in (("9" * room, None), ("9" * (room - 8), "abcdefgh"), ("9" * (room - 1), "b")):
        args = ["record", "--seed", seed, "--date", "20260930", "--root", root] + (["--suffix", suffix] if suffix else [])
        assert sigsim.main(args) == 0
        assert len(names[-1]) == 48 and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", names[-1])
    capsys.readouterr()
    for seed, suffix in (("9" * (room + 1), None), ("9" * (room - 7), "abcdefgh"), ("9" * room, "b")):
        args = ["record", "--seed", seed, "--date", "20260930", "--root", root] + (["--suffix", suffix] if suffix else [])
        with pytest.raises(SystemExit) as exc:
            sigsim.main(args)
        assert exc.value.code == 2 and "[a-z0-9][a-z0-9-]{0,47}" in capsys.readouterr().err
    assert len(names) == 3                                               # record ran for the three that fit, not for the three that do not


_ZERO_CLAMPS = {row: 0 for row in sigsim.CLAMP_ROWS}


def _terms_inputs(**changes):
    counts = {"first": 3, "second": 2}                # stand-ins for the two messages' frame counts
    kw = dict(regenerated_identical=True, per_message=dict(counts), expected=dict(counts), period_errors=0, within_half_lsb=True,
              gear_mismatches=0, stats=sigsim.JudgeStats(frames=10, accepted=10), clamps=dict(_ZERO_CLAMPS))
    kw.update(changes)
    return kw


_TERM_BREAKS = {
    "regenerated_identical": dict(regenerated_identical=False),
    "message_counts": dict(per_message={"first": 2, "second": 2}),
    "no_period_errors": dict(period_errors=1),
    "within_half_lsb": dict(within_half_lsb=False),
    "no_gear_mismatches": dict(gear_mismatches=1),
    "all_frames_accepted": dict(stats=sigsim.JudgeStats(frames=10, accepted=9)),
    "trip_clamps_all_zero": dict(clamps=dict(_ZERO_CLAMPS, stalled=1)),
}


def _false_terms(**changes):
    return [k for k, v in sigsim.verify_terms(**_terms_inputs(**changes)).items() if not v]


def test_verify_ok_is_every_term_and_each_term_alone_fails_it():
    good = sigsim.verify_terms(**_terms_inputs())
    assert tuple(good) == sigsim.OK_TERMS and all(good.values())
    assert set(_TERM_BREAKS) == set(sigsim.OK_TERMS)            # a new term needs its own negative case here
    for term, change in _TERM_BREAKS.items():
        assert _false_terms(**change) == [term], term


def test_verify_needs_frames_judged_and_every_clamp_counter_including_stalled():
    assert "stalled" in sigsim.CLAMP_ROWS
    for row in sigsim.CLAMP_ROWS:
        assert _false_terms(clamps=dict(_ZERO_CLAMPS, **{row: 1})) == ["trip_clamps_all_zero"], row
    assert _false_terms(stats=sigsim.JudgeStats()) == ["all_frames_accepted"]        # nothing judged is not everything accepted


def test_verify_terms_refuses_clamp_counters_that_lack_a_row():
    """all() over a dict that lacks rows is vacuously true: a caller that passes {} (or forgets `stalled`) gets an error, not ok."""
    with pytest.raises(ValueError, match="CLAMP_ROWS"):
        sigsim.verify_terms(**_terms_inputs(clamps={}))
    for row in sigsim.CLAMP_ROWS:
        with pytest.raises(ValueError, match="CLAMP_ROWS"):
            sigsim.verify_terms(**_terms_inputs(clamps={k: 0 for k in sigsim.CLAMP_ROWS if k != row}))
    with pytest.raises(ValueError, match="CLAMP_ROWS"):
        sigsim.verify_terms(**_terms_inputs(clamps=dict(_ZERO_CLAMPS, made_up=0)))


@NEEDS_CONTRACT
def test_a_real_stall_is_counted_and_fails_the_clamp_term():
    """A script that runs into a row it cannot pass (a forward gear asked to roll back) ends its segment there: the clamp counts
    `stalled` as well as the row, and the clamp term of verify's ok is false for that trip's own counters."""
    _row, segs = _clamp_scripts()["gear_direction"]
    tr = sigsim.simulate(1, C, segments=segs)
    assert tr.clamps["stalled"] > 0 and tr.clamps["gear_direction"] > 0
    assert _false_terms(clamps=tr.clamps) == ["trip_clamps_all_zero"]


@pytest.mark.parametrize("worst_in_lsb,ok", [(0.0, True), (0.5, True), (0.75, False), (1.0, False), (2.0, False)])
def test_the_quantisation_bound_is_half_an_lsb(worst_in_lsb, ok):
    """Rounding to the nearest raw step leaves at most half an LSB: an error between a half and one LSB is a fault."""
    lsb = {"first": 0.25, "second": 0.0625}                 # resolutions of this test's own (exact in binary)
    worst = {"first": worst_in_lsb * lsb["first"], "second": 0.0}
    assert sigsim.quantised_within_half_lsb(worst, lsb) is ok
    worst = {"first": 0.0, "second": worst_in_lsb * lsb["second"]}
    assert sigsim.quantised_within_half_lsb(worst, lsb) is ok


def test_the_quantisation_bound_is_tight_around_half_an_lsb():
    """Float dust (1e-10) on the bound is tolerated, a millionth of an LSB-sized unit past it is not: the slack is far
    narrower than the gap to the next resolvable error."""
    lsb = {"sig": 0.25}
    half = lsb["sig"] / 2
    assert sigsim.quantised_within_half_lsb({"sig": half}, lsb) is True
    assert sigsim.quantised_within_half_lsb({"sig": half + 1e-10}, lsb) is True
    assert sigsim.quantised_within_half_lsb({"sig": half + 1e-6}, lsb) is False


# --- verify() itself, with cantools and python-can replaced by exact stand-ins ---------------------------

DYN_ID, GEAR_ID = 0x7A0, 0x7A1          # the stand-in database's ids: this test's own, not the slice's
FAKE_LSB = 0.125                        # and its resolution for the four dynamics signals (exact in binary; not the slice's)


class _FakeSignal:
    def __init__(self, name, scale):
        self.name, self.scale = name, scale


class _FakeMessage:
    def __init__(self, frame_id, signals):
        self.frame_id, self.signals = frame_id, signals


class _FakeDb:
    """cantools' database as verify() uses it: two messages, and decode_message answering from a table (the 8 data bytes of a
    frame are its index in the log)."""

    def __init__(self, su, decoded):
        self.su, self.decoded = su, decoded
        self.dyn = _FakeMessage(DYN_ID, [_FakeSignal(s, FAKE_LSB) for s in su.signals[:4]])
        self.gear = _FakeMessage(GEAR_ID, [_FakeSignal(su.signals[4], 1.0)])
        self.messages = [self.dyn, self.gear]

    def get_message_by_name(self, name):
        return self.dyn if name == self.su.dyn_msg else self.gear

    def decode_message(self, cid, data, decode_choices=False):
        return self.decoded[int.from_bytes(data, "big")]


def _verify_in_process(monkeypatch, tmp_path, trip_edit=None, decode_edit=None, log_edit=None, read_edit=None):
    """The real verify() on seed 1's trip, its cantools and python-can steps replaced by stand-ins that are exact: the decoded
    values are the model's own unless decode_edit(index, message name, values dict) changes them, and trip_edit(trip) may
    change a copy of the trip first (the clamp counters, say). log_edit(bytes) changes the text of the log file verify reads
    (python-can's reader is a stand-in, so it does not change what the reader returns), and read_edit(messages) changes what
    the reader returns, as (timestamp in s, id, data, channel). Returns verify's dict."""
    tr = copy.copy(trip(1))
    tr.clamps = dict(tr.clamps)
    if trip_edit:
        trip_edit(tr)
    su = tr.setup
    frames, decoded = [], {}
    for i, (t, name, vals) in enumerate(sigsim.model_messages(tr)):
        names = su.signals[:4] if name == su.dyn_msg else su.signals[4:]
        dec = dict(zip(names, (float(x) for x in vals)))
        if decode_edit:
            decode_edit(i, name, dec)
        decoded[i] = dec
        frames.append((t, DYN_ID if name == su.dyn_msg else GEAR_ID, i.to_bytes(8, "big")))
    db = _FakeDb(su, decoded)
    log = tmp_path / "stand-in.log"
    text = sigsim.candump_text(frames).encode("ascii")
    log.write_bytes(log_edit(text) if log_edit else text)
    read = [(t / 1000.0, cid, data, sigsim.CHANNEL) for t, cid, data in frames]
    monkeypatch.setattr(sigsim, "simulate", lambda seed, contract=None, **_kw: tr)
    monkeypatch.setattr(sigsim, "load_dbc", lambda su_, path=None: db)
    monkeypatch.setattr(sigsim, "encode_frames", lambda trip_, db_: frames)
    monkeypatch.setattr(sigsim, "read_log", lambda path: read_edit(read) if read_edit else read)
    monkeypatch.setattr(sigsim, "python_can_writer_text", lambda fr, channel=sigsim.CHANNEL: sigsim.candump_text(fr, channel))
    return sigsim.verify(log, 1, C)


def _failed_terms(ver):
    return sorted(k for k, v in ver["ok_terms"].items() if not v)


@NEEDS_CONTRACT
def test_verify_passes_a_log_that_decodes_to_the_model(monkeypatch, tmp_path):
    ver = _verify_in_process(monkeypatch, tmp_path)
    assert tuple(ver["ok_terms"]) == sigsim.OK_TERMS and all(ver["ok_terms"].values()) and ver["ok"] is True
    assert ver["judge"]["frames"] == ver["judge"]["accepted"] > 0 and ver["trip_clamps"] == {k: 0 for k in sigsim.CLAMP_ROWS}


@NEEDS_CONTRACT
def test_verify_takes_the_trips_own_clamp_counters_into_ok(monkeypatch, tmp_path):
    """verify passes the trip's counters to verify_terms and puts every term into ok: a trip the clamp acted on is refused
    even though its log regenerates, decodes and is accepted."""
    def clamp_acted(tr):
        tr.clamps["stalled"] = 1

    ver = _verify_in_process(monkeypatch, tmp_path, trip_edit=clamp_acted)
    assert _failed_terms(ver) == ["trip_clamps_all_zero"] and ver["ok"] is False and ver["trip_clamps"]["stalled"] == 1


@NEEDS_CONTRACT
def test_verify_counts_a_decoded_gear_that_is_not_the_models(monkeypatch, tmp_path):
    su = sigsim.setup(C)
    first_gear = next(i for i, (_t, n, _v) in enumerate(sigsim.model_messages(trip(1))) if n == su.gear_msg)

    def other_gear(i, name, dec):
        if i == first_gear:
            dec[su.signals[4]] = 1.0          # the model's gear there is 0 (idle): another valid gear

    ver = _verify_in_process(monkeypatch, tmp_path, decode_edit=other_gear)
    assert _failed_terms(ver) == ["no_gear_mismatches"] and ver["cantools_decode"]["gear_mismatches"] == 1 and ver["ok"] is False


@NEEDS_CONTRACT
def test_verify_holds_the_decode_to_half_an_lsb(monkeypatch, tmp_path):
    def one_lsb_out(i, name, dec):
        if i == 0:
            first = sigsim.setup(C).signals[0]
            dec[first] += FAKE_LSB

    ver = _verify_in_process(monkeypatch, tmp_path, decode_edit=one_lsb_out)
    assert _failed_terms(ver) == ["within_half_lsb"] and ver["cantools_decode"]["within_half_lsb"] is False and ver["ok"] is False


@NEEDS_CONTRACT
def test_verify_judges_what_the_log_decodes_to_not_what_the_model_says(monkeypatch, tmp_path):
    """The yaw rate decodes to zero on every turning frame: the model's values (which the trip holds) would all be accepted, the
    decoded ones are not, so the judge term must see the decoded stream. The quantisation term fails too: the decode is far
    from the model."""
    su = sigsim.setup(C)

    def yaw_lost(i, name, dec):
        if name == su.dyn_msg and dec[su.signals[2]] != 0.0:
            dec[su.signals[3]] = 0.0

    ver = _verify_in_process(monkeypatch, tmp_path, decode_edit=yaw_lost)
    assert _failed_terms(ver) == ["all_frames_accepted", "within_half_lsb"]
    assert set(ver["judge"]["reasons"]) == {str(rules.RSN_VSS_YAW)} and ver["judge"]["reasons"][str(rules.RSN_VSS_YAW)] > 0
    honest = sigsim.judge_stream(sigsim.model_messages(trip(1)), su)
    assert honest.accepted == honest.frames                     # the model's own values pass: only the decoded stream can fail here
    assert ver["judge"]["reasons"][str(rules.RSN_VSS_YAW)] == honest.rule26_above_tol


@NEEDS_CONTRACT
@pytest.mark.parametrize("edit", [lambda raw: raw[:-1], lambda raw: raw + b"\n"], ids=["no_final_newline", "extra_blank_line"])
def test_verify_compares_the_log_with_the_regenerated_text_byte_for_byte(monkeypatch, tmp_path, edit):
    """A log that lacks its last newline (or has an extra one) reads back as the model's frames and decodes to its values, but
    it is not this module's text: only the regeneration term fails."""
    ver = _verify_in_process(monkeypatch, tmp_path, log_edit=edit)
    assert _failed_terms(ver) == ["regenerated_identical"] and ver["regenerated_identical"] is False and ver["ok"] is False


@NEEDS_CONTRACT
def test_verify_refuses_a_timestamp_that_is_not_on_a_whole_millisecond(monkeypatch, tmp_path):
    """The first frame 0.5 ms late: the model's frames are on whole milliseconds only, so this is refused, not rounded."""
    def half_a_millisecond_late(messages):
        (ts, cid, data, channel), rest = messages[0], messages[1:]
        return [(ts + 0.0005, cid, data, channel)] + rest

    with pytest.raises(ValueError, match="whole millisecond"):
        _verify_in_process(monkeypatch, tmp_path, read_edit=half_a_millisecond_late)


def _paragraphs(text):
    return [q.strip() for q in re.split(r"\n\s*\n", text) if q.strip()]


def test_log_replay_compatibility_is_marked_unverified():
    """canplayer and the CAN provider's --dumpfile have not been run on this log. The README and sigsim's own docstring each
    carry two separate UNVERIFIED paragraphs, one per tool, each opening with the marker and naming only its own tool, each
    closed by the test that would settle it; neither calls a tool's replay verified. The log is said to be written in
    candump -l's documented form, not to match candump -l."""
    for where, text in (("README.md", (SIM_DIR / "README.md").read_text(encoding="utf-8")), ("sigsim.py", sigsim.__doc__ or "")):
        paras = _paragraphs(text)
        canplayer = [q for q in paras if "canplayer -I" in q]
        dumpfile = [q for q in paras if "--dumpfile" in q]
        assert len(canplayer) == 1 and len(dumpfile) == 1, where
        assert canplayer[0] is not dumpfile[0], where                   # one paragraph each: neither marker covers the other's tool
        can_flat, dump_flat = " ".join(canplayer[0].split()), " ".join(dumpfile[0].split())
        for para in (can_flat, dump_flat):
            assert re.match(r"\W*UNVERIFIED\b", para), (where, para[:60])
            assert not re.search(r"(?<!UN)(?<!un)verified", para, re.I), (where, para)       # never "verified" without the UN
        assert "candump -l" in can_flat and "frame by frame" in can_flat and "Phase 5" in can_flat, where
        assert "Phase 1 step 6" in dump_flat and "Phase 1 exit test" in dump_flat, where
        assert "documented form" in text and not re.search(r"matches\s+`?candump -l", text), where
        assert not re.search(r"\bstage [0-9]\b", text, re.I), where                # the plan's Phase/step names, not the workflow's
    assert not re.search(r"\bstage [0-9]\b", SIGSIM.read_text(encoding="utf-8"), re.I)
    for test_file in (HERE / "test_sdv_sim.py", HERE / "test_sdv_frame.py"):      # the tests use the plan's names too
        assert test_file.is_file(), test_file
        assert not re.search(r"\bstage [0-9]\b", test_file.read_text(encoding="utf-8"), re.I), test_file.name


def test_the_docs_say_what_verify_live_check_and_record_require():
    readme = (SIM_DIR / "README.md").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", readme)
    doc = re.sub(r"\s+", " ", sigsim.__doc__ or "")
    for text in (flat, doc):
        assert "no other traffic" in text and "no frame was sent" in text
        assert "CHECK_TAIL_S" in text and "after the last frame sent" in text            # what --check listens for, and until when
        assert "[a-z][a-z0-9]{0,7}" in text and "-sigsim-<seed>S" in text and "inside the repository" in text     # --suffix and the refusal
        assert "[a-z0-9][a-z0-9-]{0,47}" in text and "ASCII digits" in text                # the whole name, and --date
        assert "requirements.lock" in text
    assert "every decoded gear equals the model's" in flat                              # verify's no_gear_mismatches term
    assert re.search(r"on the platform\s+`requirements.lock` pins", readme)


@NEEDS_CONTRACT
def test_the_docs_name_envelope_rows_not_their_values():
    """sigsim's docstring and the README refer to the rows they mean by name (turn_speed_max, turn_steer_max, v26_hi): a value
    written out (the speed a turn is allowed at, the steering limit, the window's upper end, each with its unit) would go stale
    when the generated contract changes."""
    env = sigsim.Envelope.from_contract(C)
    profile = {int(r["id"]): r for r in C.PROFILES}[C.LIVE_DEFAULT_PROFILE["sigsim"]]
    doc = re.sub(r"\s+", " ", sigsim.__doc__ or "")
    readme = re.sub(r"\s+", " ", (SIM_DIR / "README.md").read_text(encoding="utf-8"))
    for name in ("turn_speed_max", "turn_steer_max", "v26_hi"):
        assert name in doc, name
    values = ((env.turn_speed_max, "m/s"), (env.turn_steer_max, "deg"), (profile["v26_hi"], "m/s"))
    for text in (doc, readme):
        for value, unit in values:
            assert not re.search(r"(?<![\w.])%g %s(?![\w/])" % (value, re.escape(unit)), text), (value, unit)


# --- CARLA to ISO 8855 (Phase 7 WP1: the conventions as WP0 read them; the delta source and the wheel sign PROBED) ---

def _carla_step(v=(5.0, 0.0, 0.0), a=(0.0, 0.0, 0.0), fwd=(1.0, 0.0, 0.0), w=(0.0, 0.0, 0.0), steer=0.0, gear=1, reverse=False,
                wheel=None):
    """One steps.jsonl record of the capture (spec 2.2), in CARLA's axes and units, with only what the conversion reads."""
    return {"v": list(v), "a": list(a), "fwd": list(fwd), "w": list(w), "steer": steer, "gear": gear, "reverse": reverse,
            "wheel_deg": list(wheel) if wheel is not None else [steer * 70.0, steer * 70.0]}


def test_carla_conventions_are_stated_as_read_with_their_sources():
    """No convention is an assumption any longer: each carries how WP0 read it (READ or LIB) and its source; WP0's sign
    probe read the yaw rate's turn sign, the wheel angle's sign and the velocity's frame (5.2), so nothing is
    INFERRED, PENDING or UNVERIFIED."""
    assert not hasattr(carla_iso, "UNVERIFIED")
    doc = carla_iso.__doc__ or ""
    assert "UNVERIFIED" not in doc and "INFERRED" not in doc and "PROBED" in doc
    assert carla_iso.CARLA_AXES.startswith("left-handed") and carla_iso.CARLA_STEER_POSITIVE == "right"
    assert carla_iso.CARLA_YAW_POSITIVE == "clockwise seen from above" and carla_iso.CARLA_ANGULAR_VELOCITY_UNIT == "degrees/s"
    assert set(carla_iso.CONVENTIONS) == {"axes", "steer", "yaw", "angular_velocity_unit", "w_z_turn_sign", "wheel_steer_sign",
                                          "velocity_frame"}
    for name, (value, status, source) in carla_iso.CONVENTIONS.items():
        assert status in ("READ", "LIB") and source and value, name
    for name in ("w_z_turn_sign", "wheel_steer_sign", "velocity_frame"):
        assert carla_iso.CONVENTIONS[name][1] == "READ" and "probe 2" in carla_iso.CONVENTIONS[name][2], name
    assert carla_iso.DELTA_SOURCE == "wheel" and carla_iso.DELTA_SOURCES == ("commanded", "wheel")
    assert carla_iso.WHEEL_STEER_POSITIVE == "right" and carla_iso.PENDING_PROBE == () and carla_iso.pending() == {}


def test_carla_vectors_mirror_y():
    assert carla_iso.vector_to_iso((1.0, 2.0, 3.0)) == (1.0, -2.0, 3.0)
    assert carla_iso.vector_to_iso((0.0, 1.0, 0.0))[1] < 0            # CARLA's right is ISO's -y
    for vec in ((1.5, -2.5, 0.25), (-3.0, 0.0, 9.0)):
        assert carla_iso.vector_to_iso(carla_iso.vector_to_iso(vec)) == vec


def test_a_right_turn_as_carla_reports_it_is_negative_in_iso():
    """A right turn in CARLA's terms as WP0's sign probe read them -- steer > 0, angular velocity z > 0, the wheel angles
    with the steer's sign (all READ) -- is a negative delta and psi_dot in ISO 8855; a left turn positive."""
    v, a, d, y, g = carla_iso.convert(_carla_step(a=(0.5, 0.0, 0.0), w=(0.0, 0.0, 30.0), steer=0.5, wheel=(19.0, 21.0)), (40.0, 40.0))
    assert (v, a, d, y, g) == (5.0, 0.5, -20.0, -30.0, 1)
    _v, _a, d, y, _g = carla_iso.convert(_carla_step(w=(0.0, 0.0, -12.0), steer=-0.25, wheel=(-9.0, -11.0)), (40.0, 40.0))
    assert d == 10.0 and y == 12.0


def test_carla_signs_agree_with_the_kinematic_model():
    """After conversion, a CARLA-consistent turn gives delta and psi_dot of the sign a forward
    kinematic bicycle requires (psi_dot = v tan(delta) / L), and reversing flips only the yaw."""
    L, max_steer = 3.1, 45.0          # a stand-in CARLA vehicle of this test's own: the conversion must not depend on the design car
    for steer, fwd in ((0.3, 1.0), (-0.3, 1.0), (0.3, -1.0), (-0.3, -1.0)):
        speed = 4.0 * fwd
        d_carla = steer * max_steer
        omega_carla = math.degrees(speed * math.tan(math.radians(d_carla)) / L)   # the same model in CARLA's sense
        gear, rev = (1, False) if fwd > 0 else (-1, True)
        v, _a, d, y, _g = carla_iso.convert(_carla_step(v=(speed, 0.0, 0.0), w=(0.0, 0.0, omega_carla), steer=steer, gear=gear,
                                                        reverse=rev, wheel=(d_carla, d_carla)), (max_steer, max_steer))
        assert v == speed
        assert y == pytest.approx(math.degrees(v * math.tan(math.radians(d)) / L))


def test_the_speed_is_the_signed_component_along_the_forward_vector():
    """Reversing gives a negative speed and the acceleration keeps its sign along the heading: a dot product, never the
    vector's length."""
    fwd = (math.cos(math.radians(30.0)), math.sin(math.radians(30.0)), 0.0)
    back = tuple(-2.0 * f for f in fwd)
    v, a, _d, _y, g = carla_iso.convert(_carla_step(v=back, a=tuple(0.5 * f for f in fwd), fwd=fwd, gear=-1, reverse=True), (70.0, 70.0))
    assert v == pytest.approx(-2.0) and a == pytest.approx(0.5) and g == -1
    side = (-fwd[1] * 3.0, fwd[0] * 3.0, 0.0)                         # pure sideways motion has no longitudinal speed
    assert carla_iso.convert(_carla_step(v=side, fwd=fwd), (70.0, 70.0))[0] == pytest.approx(0.0, abs=1e-12)


def test_the_delta_is_minus_the_mean_of_the_front_wheels_physics_angles():
    """The delta source WP0's probe 3 picked (F3, 3.1): the mean of the two front wheels' get_wheel_steer_angle,
    negated (the steer's sign, positive right), not the commanded angle, which this step makes different on purpose; the
    mean of both wheels, not one of them. The commanded angle is taken only when named."""
    step = _carla_step(steer=0.25, wheel=(11.0, 14.0))
    assert carla_iso.DELTA_SOURCE == "wheel"
    assert carla_iso.convert(step, (70.0, 70.0))[2] == -12.5
    assert carla_iso.delta_iso(0.25, (11.0, 14.0), (70.0, 70.0)) == -12.5
    assert carla_iso.delta_iso(-0.25, (-11.0, -14.0), (70.0, 70.0)) == 12.5          # a left turn
    assert carla_iso.delta_iso(0.25, (11.0, 14.0), (70.0, 70.0), source="commanded") == -17.5
    with pytest.raises(carla_iso.ConversionError):
        carla_iso.delta_iso(0.25, (11.0, 14.0), (70.0, 69.0))          # one vehicle, one front maximum
    with pytest.raises(carla_iso.ConversionError):
        carla_iso.delta_iso(0.25, (11.0, 14.0), (70.0, 70.0), source="sideways")


def test_the_wheel_source_is_minus_the_mean_of_the_front_wheels(monkeypatch):
    """The wheel source's value, whatever the pending machinery says (verify#6): the mean of both front wheels, not one of
    them (10 and 14 give 12, not 10), and its sign turned to ISO 8855 exactly when get_wheel_steer_angle is positive right
    -- were it positive left, the mean would already be ISO's."""
    monkeypatch.setattr(carla_iso, "PENDING_PROBE", ())
    assert carla_iso.delta_iso(0.2, (10.0, 14.0), (70.0, 70.0), source="wheel") == -12.0
    monkeypatch.setattr(carla_iso, "WHEEL_STEER_POSITIVE", "left")
    assert carla_iso.delta_iso(0.2, (10.0, 14.0), (70.0, 70.0), source="wheel") == 12.0
    monkeypatch.setattr(carla_iso, "WHEEL_STEER_POSITIVE", "right")
    monkeypatch.setattr(carla_iso, "DELTA_SOURCE", "wheel")
    assert carla_iso.convert(_carla_step(steer=0.2, wheel=(10.0, 14.0)), (70.0, 70.0))[2] == -12.0


@pytest.mark.parametrize("gear,reverse,ok", [(-1, True, True), (0, False, True), (1, False, True), (-1, False, False),
                                             (1, True, False), (0, True, False), (2, False, False)])
def test_the_gear_is_the_step_s_and_reverse_must_be_set_exactly_in_gear_minus_one(gear, reverse, ok):
    step = _carla_step(v=(0.0, 0.0, 0.0), gear=gear, reverse=reverse)
    if ok:
        assert carla_iso.convert(step, (70.0, 70.0))[4] == gear
    else:
        with pytest.raises(carla_iso.ConversionError):
            carla_iso.convert(step, (70.0, 70.0))


def test_the_yaw_rate_is_the_negated_z_component_and_is_never_taken_from_x_or_y():
    step = _carla_step(w=(5.0, -7.0, 2.5))
    assert carla_iso.convert(step, (70.0, 70.0))[3] == -2.5


def test_the_sim_readme_row_says_what_carla_iso_now_holds():
    readme = (SIM_DIR / "README.md").read_text(encoding="utf-8")
    row = next(ln for ln in readme.splitlines() if ln.startswith("| `carla_iso.py`"))
    assert "PROBED" in row and "PENDING-PROBE" not in row and "assumption" not in row and "UNVERIFIED" not in row
    assert "sdv/carla" in row


def test_carla_heading_and_longitudinal():
    """A CARLA heading of +90 deg (facing its +y, the right) faces ISO's -y; the longitudinal
    components are the same dot product in either frame."""
    yaw = 90.0
    fwd_carla = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0.0)
    fwd_iso = carla_iso.vector_to_iso(fwd_carla)
    psi_iso = carla_iso.angle_to_iso(yaw)
    assert fwd_iso[1] == pytest.approx(-1.0) and psi_iso == -90.0
    assert fwd_iso[0] == pytest.approx(math.cos(math.radians(psi_iso))) and fwd_iso[1] == pytest.approx(math.sin(math.radians(psi_iso)))
    vel = (0.3, 7.0, 0.1)
    assert carla_iso.longitudinal(vel, fwd_carla) == pytest.approx(carla_iso.longitudinal(carla_iso.vector_to_iso(vel), fwd_iso))
    assert carla_iso.yaw_rate_to_iso(-12.5) == 12.5
    with pytest.raises(ValueError):
        carla_iso.steer_to_iso_deg(1.5, 35.0)
    with pytest.raises(ValueError):
        carla_iso.steer_to_iso_deg(0.5, 0.0)


# --- cantools and python-can (the sim venv) ------------------------------------------------------------

@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_slice_dbc_parses_with_cantools():
    out = json.loads(run_sim("dbc").stdout)
    assert out["cantools"] == locked_version("cantools") and out["strict"] is True
    su = sigsim.setup(C)
    msgs = out["messages"]
    assert set(msgs) == {su.dyn_msg, su.gear_msg}
    for m in msgs:
        assert msgs[m]["cycle_time"] == C.DBC_PERIOD_MS[m] and msgs[m]["length"] == 8 and not msgs[m]["extended"]
    sigs = {s: v for m in msgs.values() for s, v in m["signals"].items()}
    for i, s in enumerate(C.SLOT_DBC_SIGNALS):
        assert (sigs[s]["unit"] or None) == C.SLOT_DBC_UNITS[i]
        assert sigs[s]["byte_order"] == "little_endian" and sigs[s]["signed"]
    assert set(SPEC_SLOT_OF_HALF_LSB_KEY) == set(C.DBC_HALF_LSB)
    for key, slot in SPEC_SLOT_OF_HALF_LSB_KEY.items():
        assert sigs[C.SLOT_DBC_SIGNALS[slot]]["scale"] / 2 == C.DBC_HALF_LSB[key]


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    if not SIM_PY.exists() or C is None:
        pytest.skip("needs the sim venv and the generated contract")
    base = tmp_path_factory.mktemp("rec")
    out = {}
    for tag, seed in (("a", 5), ("b", 5), ("c", 6)):
        d = base / tag
        res = json.loads(run_sim("record", "--seed", seed, "--out", d, "--date", "20260930").stdout)
        out[tag] = (d, res)
    return out


@NEEDS_SIM_VENV
def test_same_seed_byte_identical(recordings):
    (da, ra), (db, rb), (dc, _rc) = recordings["a"], recordings["b"], recordings["c"]
    la, lb, lc = (d / sigsim.LOG_NAME for d in (da, db, dc))
    assert la.read_bytes() == lb.read_bytes()
    assert la.read_bytes() != lc.read_bytes()
    assert ra["verify"]["log_sha256"] == rb["verify"]["log_sha256"]


@NEEDS_SIM_VENV
def test_sha256_file_and_manifest_line(recordings):
    d, res = recordings["a"]
    log = d / sigsim.LOG_NAME
    sha = hashlib.sha256(log.read_bytes()).hexdigest()
    assert (d / (sigsim.LOG_NAME + ".sha256")).read_text() == "%s  %s\n" % (sha, sigsim.LOG_NAME)
    line = (d / "manifest-line.json").read_text()
    assert line.endswith("\n") and line.count("\n") == 1
    entry = json.loads(line)
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", entry["name"]) and entry["name"] == "20260930-sigsim-5"
    assert entry["recording"] == {"path": str(log), "sha256": sha, "format": "candump-log"}
    assert entry["source"]["generator"] == "sigsim"
    row = {r["id"]: r for r in C.PROFILES}[C.LIVE_DEFAULT_PROFILE["sigsim"]]
    assert entry["source"]["vehicle"] == {"name": row["source_vehicle"], "wheelbase_mm": sigsim.setup(C).wheelbase_mm}
    params = entry["source"]["params"]
    assert params["seed"] == 5
    # the inputs Phase 1 step 6 (the provider run) compares: the hashes of the very files this recording was made from, the
    # catalogue digest of the generated contract, and what the timestamps are
    assert params["dbc_sha256"] == hashlib.sha256(SLICE_DBC.read_bytes()).hexdigest()
    assert params["sigsim_sha256"] == hashlib.sha256(SIGSIM.read_bytes()).hexdigest()
    assert params["catalog_digest"] == "0x%08X" % C.CATALOG_DIGEST
    assert params["timestamps"] == "simulation time from zero"
    assert set(params) == {"seed", "dbc_sha256", "sigsim_sha256", "catalog_digest", "timestamps"}
    assert entry["profile_id"] == C.LIVE_DEFAULT_PROFILE["sigsim"]
    assert rules.L_MM_MIN <= entry["source"]["vehicle"]["wheelbase_mm"] <= rules.L_MM_MAX


@NEEDS_SIM_VENV
def test_log_reads_back_with_python_can_and_cantools(recordings):
    _d, res = recordings["a"]
    ver = res["verify"]
    assert ver["ok"] is True
    assert ver["regenerated_identical"] is True
    rd = ver["python_can_reader"]
    assert rd["per_message"] == rd["expected_per_message"] and rd["period_errors"] == 0 and rd["channels"] == ["vcan0"]
    assert rd["frames"] == sum(rd["expected_per_message"].values()) == sum(res["trip"]["messages"].values())
    assert set(ver["ok_terms"]) == set(sigsim.OK_TERMS) and all(ver["ok_terms"].values()) and ver["ok"] is True
    assert set(ver["trip_clamps"]) == set(sigsim.CLAMP_ROWS) and sum(ver["trip_clamps"].values()) == 0
    dec = ver["cantools_decode"]
    assert dec["within_half_lsb"] is True and dec["gear_mismatches"] == 0
    for s, err in dec["max_abs_error"].items():
        assert err <= dec["half_lsb"][s] + 1e-9


@NEEDS_SIM_VENV
def test_every_decoded_sample_passes_rules(recordings):
    for tag in ("a", "c"):
        _d, res = recordings[tag]
        j = res["verify"]["judge"]
        assert j["frames"] == res["trip"]["messages"][sigsim.setup(C).dyn_msg]
        assert j["accepted"] == j["frames"] and j["reasons"] == {}
        assert j["rule26_judged"] > 0 and j["rule27_checked"] > 0
        assert j["rule26_above_tol"] > 0 and j["turning_frames"] > 0 and j["turning_outside_window"] == 0
        assert res["trip"]["clamped_steps"] == 0 and res["trip"]["violations"] == 0


@NEEDS_SIM_VENV
def test_log_lines_are_candump_format(recordings):
    d, _res = recordings["a"]
    ids = sorted(int(m["frame_id"], 16) for m in json.loads(run_sim("dbc").stdout)["messages"].values())     # slice.dbc's, via cantools
    pat = re.compile(r"\(\d{10}\.\d{6}\) vcan0 (?:%s)#[0-9A-F]{16}" % "|".join("%03X" % i for i in ids))
    lines = (d / sigsim.LOG_NAME).read_text(encoding="ascii").split("\n")
    assert lines[-1] == "" and all(pat.fullmatch(x) for x in lines[:-1])
    assert lines[0].startswith("(0000000000.000000) vcan0 %03X#" % ids[0])


@NEEDS_SIM_VENV
def test_python_can_writer_compared(recordings):
    """python-can's writer (UNVERIFIED in the plan) is compared with this module's, not used: the
    result is recorded either way, and its reader reads this module's log (above)."""
    _d, res = recordings["a"]
    w = res["verify"]["python_can_writer"]
    assert isinstance(w["identical"], bool)
    if not w["identical"]:
        # python-can 4.6.1 writes the -L form: an unpadded timestamp and a direction suffix. The frame
        # itself (timestamp value, channel, id#data) is the same.
        ours, theirs = (x.split() for x in w["first_difference"])
        assert float(ours[0][1:-1]) == float(theirs[0][1:-1])
        assert ours[1:] == theirs[1:3] and theirs[3:] == ["R"]


def _dyn_and_gear_ids():
    """The two messages' CAN ids as the log writes them, from slice.dbc through cantools."""
    su = sigsim.setup(C)
    msgs = json.loads(run_sim("dbc").stdout)["messages"]
    return tuple("%03X" % int(msgs[m]["frame_id"], 16) for m in (su.dyn_msg, su.gear_msg))


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_tampered_log_fails_verification(recordings, tmp_path):
    """One LSB of the speed changed in one dynamics frame: the text is no longer the model's, and the decode is one LSB
    from the model's value (more than the half an LSB that quantisation leaves) -- exactly those two terms of ok fail, and
    verify reports the second through ok, not only through its own decode field."""
    d, _res = recordings["a"]
    dyn, _gear = _dyn_and_gear_ids()
    text = (d / sigsim.LOG_NAME).read_text(encoding="ascii").split("\n")
    i = next(k for k, x in enumerate(text) if " %s#" % dyn in x and k > 500)
    head, data = text[i].split("#")
    text[i] = head + "#" + ("%04X" % (int(data[:4], 16) ^ 0x0100)) + data[4:]
    bad = tmp_path / "bad.log"
    bad.write_text("\n".join(text), encoding="ascii")
    p = run_sim("verify", bad, "--seed", 5, check=False)
    assert p.returncode == 1
    ver = json.loads(p.stdout)
    assert ver["ok"] is False and ver["regenerated_identical"] is False and ver["cantools_decode"]["within_half_lsb"] is False
    assert ver["ok_terms"]["within_half_lsb"] is False
    assert sorted(k for k, v in ver["ok_terms"].items() if not v) == ["regenerated_identical", "within_half_lsb"]


@NEEDS_SIM_VENV
def test_record_refuses_an_existing_directory(recordings):
    d, _res = recordings["a"]
    p = run_sim("record", "--seed", 5, "--out", d, check=False)
    assert p.returncode != 0 and "FileExistsError" in p.stderr


def _broken_terms(tmp_path, lines, name, final_newline=True):
    """Verify a log made of `lines` as seed 5: it must fail; return the terms of ok that failed."""
    bad = tmp_path / name
    bad.write_text("\n".join(lines) + ("\n" if final_newline else ""), encoding="ascii")
    p = run_sim("verify", bad, "--seed", 5, check=False)
    assert p.returncode == 1, p.stderr[-500:]
    return sorted(k for k, v in json.loads(p.stdout)["ok_terms"].items() if not v)


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_a_log_that_is_not_the_models_text_fails_naming_the_terms_it_breaks(recordings, tmp_path):
    d, res = recordings["a"]
    lines = (d / sigsim.LOG_NAME).read_text(encoding="ascii").splitlines()
    dyn, gear = _dyn_and_gear_ids()
    # the same frames, one line in lower case: python-can and cantools read the same bytes, but it is not this module's text
    low = list(lines)
    i = next(i for i, ln in enumerate(lines) if re.search(r"#[0-9]*[A-F]", ln))         # a frame with a hex letter in its data
    low[i] = low[i].lower()
    assert low[i] != lines[i]
    assert _broken_terms(tmp_path, low, "lower.log") == ["regenerated_identical"]
    # the same frames without the last newline: python-can reads every one, but the file is not this module's text
    assert _broken_terms(tmp_path, lines, "no-final-newline.log", final_newline=False) == ["regenerated_identical"]
    # the last frame (a gear frame: at equal times the dynamics message comes first) dropped: one message short
    assert lines[-1].split()[2].startswith(gear + "#")
    assert _broken_terms(tmp_path, lines[:-1], "short.log") == ["message_counts", "regenerated_identical"]
    # one dynamics frame in the middle of the first cruise a millisecond late: two periods off, the values unchanged
    cruise = next(seg for seg in res["trip"]["segments"] if seg[0] == "cruise")
    period = dyn_period()
    t = (cruise[1] + cruise[2]) // 2 // period * period                                   # a dynamics frame's time
    stamp, later = ("(%010d.%06d)" % (u // 1000, u % 1000 * 1000) for u in (t, t + 1))
    k = next(i for i, ln in enumerate(lines) if ln.startswith("%s vcan0 %s#" % (stamp, dyn)))
    late = list(lines)
    late[k] = late[k].replace(stamp, later, 1)
    assert _broken_terms(tmp_path, late, "late.log") == ["no_period_errors", "regenerated_identical"]


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_a_timestamp_off_a_whole_millisecond_is_refused_not_rounded(recordings, tmp_path):
    """The first frame stamped half a millisecond after zero (a log from a capture, not from this model): verify stops with
    the error naming the millisecond, it does not round the stamp to a frame time."""
    d, _res = recordings["a"]
    lines = (d / sigsim.LOG_NAME).read_text(encoding="ascii").splitlines()
    zero = "(0000000000.000000)"
    assert lines[0].startswith(zero + " ")
    bad = tmp_path / "half-millisecond.log"
    bad.write_text("\n".join(["(0000000000.000500)" + lines[0][len(zero):]] + lines[1:]) + "\n", encoding="ascii")
    p = run_sim("verify", bad, "--seed", 5, check=False)
    assert p.returncode != 0 and "whole millisecond" in p.stderr


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_a_changed_gear_frame_fails_naming_its_terms(recordings, tmp_path):
    """The first gear frame (the idle gear, neutral) rewritten to another valid gear, forward: nothing else in the log moves,
    and the frames are all still accepted (the car is at rest in the first 50 ms), so the term that fails through verify's own
    wiring is the decoded gear against the model's -- besides the text, which is no longer the model's."""
    d, _res = recordings["a"]
    su = sigsim.setup(C)
    _dyn, gear = _dyn_and_gear_ids()
    sig = json.loads(run_sim("dbc").stdout)["messages"][su.gear_msg]["signals"][su.signals[4]]
    assert sig["length"] == 8 and sig["start"] % 8 == 0 and sig["byte_order"] == "little_endian" and sig["signed"]
    at = 2 * (sig["start"] // 8)                                                        # the gear's byte, as two hex digits
    lines = (d / sigsim.LOG_NAME).read_text(encoding="ascii").splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.split()[2].startswith(gear + "#"))
    head, data = lines[k].split("#")
    assert data[at:at + 2] == "00"                                                      # neutral
    bad = list(lines)
    bad[k] = head + "#" + data[:at] + "01" + data[at + 2:]                              # forward
    assert _broken_terms(tmp_path, bad, "gear.log") == ["no_gear_mismatches", "regenerated_identical"]


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_verify_judges_the_decoded_log_not_the_model(recordings, tmp_path):
    """The turning dynamics frames of a recorded log, re-encoded through cantools with the yaw rate zero: verify must
    reject them with reason 26, exactly as many as the honest log's turning frames that rule 26 can judge. A verify that
    judged the model's values (which the trip holds, yaw included) would accept every frame."""
    d, res = recordings["a"]
    bad = tmp_path / "noyaw.log"
    out = run_snippet(
        'su = sigsim.setup(C)\n'
        'db = sigsim.load_dbc(su)\n'
        'dyn = db.get_message_by_name(su.dyn_msg)\n'
        'delta, yaw = su.signals[2], su.signals[3]\n'
        'lines, turning = [], 0\n'
        'for ln in Path(sys.argv[1]).read_text(encoding="ascii").splitlines():\n'
        '    head, data = ln.split("#")\n'
        '    if int(head.split()[2], 16) == dyn.frame_id:\n'
        '        vals = db.decode_message(dyn.frame_id, bytes.fromhex(data), decode_choices=False)\n'
        '        if vals[delta] != 0:\n'
        '            vals[yaw] = 0.0\n'
        '            data = bytes(dyn.encode(vals)).hex().upper()\n'
        '            turning += 1\n'
        '    lines.append(head + "#" + data)\n'
        'Path(sys.argv[2]).write_text("".join(x + chr(10) for x in lines), encoding="ascii")\n'
        'print(json.dumps({"turning": turning}))\n',
        d / sigsim.LOG_NAME, bad)
    assert out["turning"] > 0
    p = run_sim("verify", bad, "--seed", 5, check=False)
    assert p.returncode == 1
    ver = json.loads(p.stdout)
    rsn = str(rules.RSN_VSS_YAW)
    assert ver["ok_terms"]["all_frames_accepted"] is False
    assert set(ver["judge"]["reasons"]) == {rsn} and ver["judge"]["reasons"][rsn] > 0
    assert ver["judge"]["reasons"][rsn] == res["verify"]["judge"]["rule26_above_tol"]


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_verify_fails_on_the_judge_term_alone(recordings):
    """The same log, verified under the demo-ODD profile as the live default: it regenerates identically and decodes
    within half an LSB, but the profile rejects honest cruise, so only the judge term fails."""
    d, _res = recordings["a"]
    terms = run_snippet(
        'alt = alt_contract(LIVE_DEFAULT_PROFILE=dict(C.LIVE_DEFAULT_PROFILE, sigsim=int(sys.argv[2])))\n'
        'print(json.dumps(sigsim.verify(Path(sys.argv[1]), 5, alt)["ok_terms"]))\n',
        d / sigsim.LOG_NAME, demo_profile_id())
    assert sorted(k for k, v in terms.items() if not v) == ["all_frames_accepted"]


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_verify_fails_on_the_clamp_term_alone(tmp_path):
    """An envelope the script is not inside (the launch acceleration halved) makes the clamp act. The log that trip
    produces regenerates identically and every frame is accepted, but verify refuses it."""
    out = run_snippet(
        'env = dict(C.ENVELOPES["sigsim"], launch_accel=sigsim.LAUNCH_ACCEL / 2)\n'
        'alt = alt_contract(ENVELOPES=dict(C.ENVELOPES, sigsim=env))\n'
        'trip = sigsim.simulate(5, alt)\n'
        'log = Path(sys.argv[1])\n'
        'log.write_text(sigsim.candump_text(sigsim.encode_frames(trip, sigsim.load_dbc(sigsim.setup(alt)))), encoding="ascii")\n'
        'ver = sigsim.verify(log, 5, alt)\n'
        'print(json.dumps({"terms": ver["ok_terms"], "clamps": ver["trip_clamps"], "ok": ver["ok"]}))\n',
        tmp_path / "clamped.log")
    assert sorted(k for k, v in out["terms"].items() if not v) == ["trip_clamps_all_zero"]
    assert out["ok"] is False and out["clamps"]["launch_accel"] > 0


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_load_dbc_refuses_a_dbc_that_disagrees_with_the_contract(tmp_path):
    text = SLICE_DBC.read_text(encoding="utf-8")
    copy = tmp_path / "copy.dbc"
    copy.write_text(text, encoding="utf-8")
    assert json.loads(run_sim("dbc", "--dbc", copy).stdout)["messages"]                   # an unedited copy loads
    cyc = re.search(r'BA_ "GenMsgCycleTime" BO_ (\d+) (\d+);', text)
    assert cyc
    quoted_unit = '"%s" VSSRX' % C.SLOT_DBC_UNITS[0]
    assert quoted_unit in text
    cases = (("cycle.dbc", text.replace(cyc.group(0), 'BA_ "GenMsgCycleTime" BO_ %s %d;' % (cyc.group(1), int(cyc.group(2)) + 5)),
              "cycle_time"),
             ("unit.dbc", text.replace(quoted_unit, '"%s_x" VSSRX' % C.SLOT_DBC_UNITS[0], 1), "cantools unit"))
    for name, body, why in cases:
        bad = tmp_path / name
        bad.write_text(body, encoding="utf-8")
        p = run_sim("dbc", "--dbc", bad, check=False)
        assert p.returncode != 0 and why in p.stderr, name
