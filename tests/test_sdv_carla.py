"""The Phase 7 CARLA feeder (sdv/carla): the send policy, the world tie, the drive (the route and its controller), the
frame set, the firewall predicate, the capture on a fake simulator and the encoder (SDV plan Phase 7 WP1).

No CARLA, camera, PowerShell or network is used: the capture runs against tests/fixtures/carla/fake_carla.py, a
stand-in for the `carla` client module with a fake clock and a grid of roads; fwcheck's predicate runs over snapshots
shaped like its PowerShell read (tests/fixtures/carla/fwcheck-cases.json, whose expectations were written from the
specification);
the encoder runs in this process against exact stand-ins for cantools' database and python-can's reader, and, where
~/sdv-sim-venv exists, once end to end in that venv with the real ones. The encoder's profile 3 is bound through a
synthetic contract (the base generation does not compile it): a copy of the generated contract with profile 3 marked
compiled, no stand-in, and the fake car's wheelbase as its L, as tests/test_sdv_frame.py binds a profile.

Every number asserted here is a design value, a value of the generated contract, a value of the fake simulator, or
computed from them; none is a measurement. Two of the fake's own values are not arbitrary: FAKE_WHEELBASE_MM is profile
3's L as WP2 freezes it (a design value of the generation), so a take from the fake meets the encoder's wheelbase check
against WP2's generation, and FAKE_MAX_STEER_DEG is CARLA's WheelPhysicsControl class default. Takes, frame sets and
recordings are written under pytest's tmp_path only.
"""
import ast
import dataclasses
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
import zlib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLA_DIR = REPO / "sdv" / "carla"
SIM_DIR = REPO / "sdv" / "sim"
FRAME_DIR = REPO / "sdv" / "frame"
STACK_DIR = REPO / "sdv" / "stack"
FIX = HERE / "fixtures" / "carla"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"
SIM_VENV = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser()
SIM_PY = SIM_VENV / "bin" / "python"
MS = 1_000_000

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (str(CARLA_DIR), str(SIM_DIR), str(FRAME_DIR), str(STACK_DIR), str(FIX)):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _try(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _by_path(name, path):
    """The two command-line tools are loaded by path under names of their own, so a module of another tree with a
    generic name is never the one a test gets."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                    # dataclasses with postponed annotations look their module up there
    spec.loader.exec_module(mod)
    return mod


sendpolicy = _try("sendpolicy")
fwcheck = _try("fwcheck")
frameset = _try("frameset")
drive = _try("drive")
worldtie = _try("worldtie")
carla_iso = _try("carla_iso")
fake = _try("fake_carla")
rules = _try("rules")
sigsim = _try("sigsim")
vf = _try("vssframe")
replaycheck = _try("replaycheck")
capture = _by_path("sdv_carla_capture", CARLA_DIR / "carla_capture.py")
encode = _by_path("sdv_carla_encode", CARLA_DIR / "encode.py")
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


# --- shared helpers -----------------------------------------------------------------------------------------------

def short_drive(**changes):
    """A drive of this test file's own: the spec's segments in a few simulated tens of seconds on the fake simulator's
    grid (one junction turn before the hard brake; the module's DRIVE wants five and runs much longer)."""
    base = dict(start_hold_s=0.5, turns_before_brake=1, brake_straight_m=40.0, entry_abs_steer_max=0.02,
                entry_speed_band=(6.7, 7.3), brake_hold_s=1.0, drive_max_s=120.0, stuck_s=3.0, hard_brake=0.7,
                hard_brake_stage2=None, stopped_hold_s=1.0, stopped_brake=1.0, reverse_throttle=0.2, reverse_s=2.0,
                reverse_stop_brake=0.2, final_hold_s=2.0, max_take_s=200.0)
    base.update(changes)
    return drive.DriveValues(**base)


def short_route(**changes):
    """The module's ROUTE with a shorter route: long enough for the short drive's one turn and its straight."""
    return dataclasses.replace(drive.ROUTE, **dict({"length_m": 600.0}, **changes))


def synthetic_contract(base=None, l_mm=None, compiled=True):
    """The generated contract with profile 3 compiled, its stand-ins cleared and the fake car's wheelbase as its L
    (a SimpleNamespace; the generated file is never edited)."""
    c = base if base is not None else C
    ns = types.SimpleNamespace(**{k: getattr(c, k) for k in dir(c) if not k.startswith("_")})
    pid = int(c.LIVE_DEFAULT_PROFILE["carla"])
    rows = []
    for r in c.PROFILES:
        if int(r["id"]) == pid:
            r = dict(r, compiled=compiled, stand_in=(), l_mm=fake.FAKE_WHEELBASE_MM if l_mm is None else l_mm)
        rows.append(r)
    ns.PROFILES = tuple(rows)
    ids = [i for i in c.COMPILED_PROFILE_IDS if i != pid]
    ns.COMPILED_PROFILE_IDS = tuple(sorted(ids + [pid])) if compiled else tuple(ids)
    return ns


def roots(tmp_path):
    return capture.Roots(takes=tmp_path / "takes", frames=tmp_path / "frames")


def run_take(tmp_path, name="20261017-carla-7", seed=7, frames="off", drv=None, route=None, windows=False, host=None, fw=None,
             contract=None, rts=None, clock=None, extra=(), fresh_process=True, **faults):
    """Run `carla_capture.py take` in this process against a fresh fake simulator. Returns (exit code, fake module, take dir).
    fresh_process clears capture's record of load_world calls, as a new process would start without one."""
    if fresh_process:
        capture._LOADS.clear()
    carla = fake.make(clock, **faults)
    rts = rts or roots(tmp_path)
    argv = ["take", "--name", name, "--seed", str(seed), "--frames", frames] + (["--host", host] if host else []) + list(extra)
    rc = capture.main(argv, carla=carla, roots=rts, windows=windows, fwcheck_run=fw, clock_ns=carla.clock,
                      sleep=carla.clock.sleep, drive_values=drv if drv is not None else short_drive(),
                      route_values=route if route is not None else short_route(),
                      contract=contract if contract is not None else C)
    return rc, carla, rts.takes / name


def read_steps(take):
    return [json.loads(ln) for ln in (take / "steps.jsonl").read_text(encoding="ascii").splitlines()]


def read_capture(take):
    return json.loads((take / "capture.json").read_text(encoding="utf-8"))


def policy():
    return sendpolicy.Policy.from_contract(C)


def times(t_cur_ms, t_vals_ms=None):
    """(t_vals_ns, t_cur_ns) pairs from millisecond lists."""
    t_vals_ms = t_vals_ms if t_vals_ms is not None else t_cur_ms
    return [(int(a * MS), int(b * MS)) for a, b in zip(t_vals_ms, t_cur_ms)]


# =================================================================================================================
# The values WP0's probes settled: one place each, nothing left pending, and loud again if reopened
# =================================================================================================================

PROBED_NAMES = {"DELTA_SOURCE": "carla_iso.py", "WHEEL_STEER_POSITIVE": "carla_iso.py", "DRIVE": "drive.py",
                "ROUTE": "drive.py", "SUBSTEP_S": "worldtie.py"}


def _carla_sources():
    files = sorted(CARLA_DIR.glob("*.py")) + sorted(SIM_DIR.glob("*.py"))
    assert (CARLA_DIR / "carla_capture.py") in files and (SIM_DIR / "carla_iso.py") in files
    return {f: f.read_text(encoding="utf-8") for f in files}


@pytest.mark.parametrize("name", sorted(PROBED_NAMES))
def test_each_probed_value_is_assigned_in_one_place_under_its_marker(name):
    """The delta source, the wheel-angle sign, the drive's and the route's values and the physics substep came from WP0's
    probes: each is assigned exactly once, in its one module, right under a PROBED comment that names its source, so a
    later probe changes one place."""
    hits = []
    for f, text in _carla_sources().items():
        lines = text.splitlines()
        for k, line in enumerate(lines):
            if re.match(r"^%s\s*(?::[^=]*)?=(?!=)" % name, line):
                hits.append((f.name, k, lines))
    assert [h[0] for h in hits] == [PROBED_NAMES[name]], hits
    _f, k, lines = hits[0]
    block = "\n".join(lines[max(0, k - 4):k])
    assert "PROBED" in block and "wp0-facts" in block, name


@pytest.mark.parametrize("name", ["DELTA_SOURCE", "WHEEL_STEER_POSITIVE"])
def test_no_other_module_decides_on_a_probed_conversion_value(name):
    """Only carla_iso.py looks at the delta source and the wheel sign: a comparison anywhere else would be a second place
    a later probe must change."""
    for f, text in _carla_sources().items():
        if f.name == "carla_iso.py":
            continue
        assert not re.search(r"\b%s\b" % name, text), f.name


def test_the_probed_values_are_wp0_s_final_ones_and_nothing_is_pending():
    """Design values all: the wheel source with the steer's sign, the 2 ms substep, the route drive
    (option (a)) with its brake, band and steering-rate limit; nothing pending in the conversion or the drive."""
    assert carla_iso.DELTA_SOURCE == "wheel" and carla_iso.WHEEL_STEER_POSITIVE == "right"
    assert carla_iso.PENDING_PROBE == () and carla_iso.pending() == {}
    assert drive.DRIVE_PENDING_PROBE is False and drive.pending() == {}
    assert worldtie.SUBSTEP_S == 0.002
    d, r = drive.DRIVE, drive.ROUTE
    assert (d.hard_brake, d.entry_speed_band, d.turns_before_brake, d.drive_max_s) == (0.7, (6.7, 7.3), 5, 480.0)
    assert (d.reverse_throttle, d.reverse_stop_brake, d.hard_brake_stage2) == (0.3, 0.3, None)
    assert (r.steer_rate_deg_s, r.deg_per_steer, r.v_cruise, r.launch_engage) == (8.0, 62.5, 7.0, (0.25, 1.0, 0.1))
    assert r.turn_sequence == ("left", "left", "straight", "left", "left", "straight", "left")


def test_a_reopened_wheel_sign_refuses_the_wheel_source_and_a_take_says_so(tmp_path, monkeypatch, capsys):
    """The pending machinery stays: should a probe reopen the wheel sign, the wheel source is refused, and a take and its
    stderr name what is pending."""
    monkeypatch.setattr(carla_iso, "PENDING_PROBE", ("wheel_steer_sign",))
    with pytest.raises(carla_iso.ConversionError, match="PENDING-PROBE"):
        carla_iso.delta_iso(0.1, (7.0, 7.0), (70.0, 70.0), source="wheel")
    assert carla_iso.delta_iso(0.1, (7.0, 7.0), (70.0, 70.0), source="commanded") == -7.0
    if C is not None:
        rc, carla, take = run_take(tmp_path)
        assert read_capture(take)["pending_probe"] == {"wheel_steer_sign": "right"}
        assert "PENDING-PROBE" in capsys.readouterr().err


# =================================================================================================================
# sendpolicy.py: the pacing decision and the frame schedule (K4 16.4, F1), from the generated constants only
# =================================================================================================================

@NEEDS_CONTRACT
def test_the_policy_comes_from_the_generated_constants():
    p = policy()
    assert (p.step_ms, p.interval_ms, p.cap_ms) == (C.CARLA_STEP_MS, C.FEEDER_PACING_INTERVAL_MS, C.FEEDER_REPEAT_CAP_MS)
    assert p.dyn_msg == C.RULE26_DBC_MESSAGE and p.gear_msg == C.SLOT_DBC_MESSAGES[4]
    assert (p.dyn_period_ms, p.gear_period_ms) == (C.DBC_PERIOD_MS[p.dyn_msg], C.DBC_PERIOD_MS[p.gear_msg])
    src = (CARLA_DIR / "sendpolicy.py").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines() if not ln.lstrip().startswith(("#", '"')))
    for value in {C.CARLA_STEP_MS, C.FEEDER_PACING_INTERVAL_MS, C.FEEDER_REPEAT_CAP_MS} | set(C.DBC_PERIOD_MS.values()):
        assert not re.search(r"(?<![\w.])%d(?![\w.])" % value, code), value       # no generated value as a literal


@pytest.mark.parametrize("t_vals,prev,want", [
    (0, None, 0),                     # step 0 is current when its values are complete
    (10, 0, 50),                      # values early: held to one interval after the previous step
    (50, 0, 50),
    (120, 0, 120),                    # values late: current at once, never earlier
    (130, 120, 170),                  # after a slow step: one full interval after it, no catch-up
])
def test_a_step_becomes_current_at_the_later_of_its_values_and_one_interval_after_the_previous(t_vals, prev, want):
    got = sendpolicy.became_current(t_vals * MS, None if prev is None else prev * MS, 50 * MS)
    assert got == want * MS


@NEEDS_CONTRACT
def test_faster_than_real_time_every_step_reaches_two_dynamics_frames_and_none_is_skipped():
    p = policy()
    cur = [k * p.interval_ms for k in range(40)]
    sched = sendpolicy.schedule(times(cur, [c - p.interval_ms + 1 if c else 0 for c in cur]), p)
    dyn = [(t, i) for t, m, i in sched if m == p.dyn_msg]
    per_step = {}
    for _t, i in dyn:
        per_step[i] = per_step.get(i, 0) + 1
    assert set(per_step) == set(range(40)) and min(per_step.values()) >= 2
    assert all(b - a in (0, 1) for (_t1, a), (_t2, b) in zip(dyn, dyn[1:]))       # the same step or the next
    assert [t for t, _i in dyn] == list(range(0, dyn[-1][0] + 1, p.dyn_period_ms))


@NEEDS_CONTRACT
def test_a_step_is_repeated_while_no_older_than_the_cap_then_nothing_until_the_next():
    """Steps 100 ms apart (slower than real time): each is sent until it has been current for the cap, then a gap."""
    p = policy()
    sched = sendpolicy.schedule(times([0, 100, 200]), p)
    dyn = [(t, i) for t, m, i in sched if m == p.dyn_msg]
    want = [(t, k) for k, base in enumerate((0, 100, 200)) for t in range(base, base + p.cap_ms + 1, p.dyn_period_ms)
            if t % p.dyn_period_ms == 0]
    assert dyn == want
    assert sendpolicy.gaps([5, 6, 7], [0, 100 * MS, 200 * MS], p.cap_ns) == [1, 2]


@NEEDS_CONTRACT
def test_the_repeat_window_counts_from_when_the_step_became_current_not_from_its_values():
    """A step whose values arrived early but that the pacing held back keeps its full window."""
    p = policy()
    sched = sendpolicy.schedule(times([0, 50, 115], [0, 10, 115]), p)
    assert (100, p.dyn_msg, 1) in sched                 # 50 ms after it became current, 90 ms after its values


@NEEDS_CONTRACT
def test_gear_frames_are_on_their_own_timer_and_follow_dynamics_at_an_equal_instant():
    p = policy()
    sched = sendpolicy.schedule(times([k * 50 for k in range(20)]), p)
    gear_t = [t for t, m, _i in sched if m == p.gear_msg]
    assert gear_t == list(range(0, gear_t[-1] + 1, p.gear_period_ms))
    assert sched[0][:2] == (0, p.dyn_msg) and sched[1][:2] == (0, p.gear_msg)
    assert sched == sorted(sched, key=lambda f: (f[0], 0 if f[1] == p.dyn_msg else 1))
    assert sendpolicy.counts(sched) == {p.dyn_msg: len([1 for f in sched if f[1] == p.dyn_msg]),
                                        p.gear_msg: len(gear_t)}


@NEEDS_CONTRACT
def test_the_schedule_ends_with_the_last_steps_repeat_window():
    p = policy()
    sched = sendpolicy.schedule(times([0, 50]), p)
    assert max(t for t, _m, _i in sched) <= 50 + p.cap_ms
    assert (100, p.dyn_msg, 1) in sched and (120, p.dyn_msg, 1) in sched and (140, p.dyn_msg, 1) not in sched


@NEEDS_CONTRACT
def test_policy_step_ns_is_the_generated_step_never_the_pacing_interval():
    """The RTF is counted in steps of Policy.step_ns: CARLA_STEP_MS in ns, whatever the pacing interval is (slice.dbc's
    RECORD names the step as the unit, and the generator derives the interval from it, so they only come apart here)."""
    p = dataclasses.replace(policy(), interval_ms=policy().interval_ms + 10)
    assert p.step_ns == int(C.CARLA_STEP_MS) * MS


def test_rtf_is_simulation_advance_over_wall_time_and_the_mean_is_total_over_total():
    elapsed = [1.0, 1.05, 1.10, 1.15]
    t_cur = [0, 50 * MS, 150 * MS, 200 * MS]
    per = sendpolicy.rtf_per_step(elapsed, t_cur, 50 * MS)
    assert per[0] is None and per[1:] == pytest.approx([1.0, 0.5, 1.0])
    s = sendpolicy.rtf_summary(elapsed, t_cur, 50 * MS)
    assert s["min"] == pytest.approx(0.5) and s["max"] == pytest.approx(1.0)
    assert s["mean"] == pytest.approx(0.15 / 0.2)            # total over total, not the mean of the ratios (5/6)
    assert set(s) == {"min", "mean", "max"}


def test_the_first_step_counts_in_the_rtf_min():
    """Step 1 is the first step that has an RTF (step 0 has no previous one): a slow step 1 is the min."""
    s = sendpolicy.rtf_summary([1.0, 1.05, 1.10, 1.15], [0, 60 * MS, 110 * MS, 160 * MS], 50 * MS)
    assert s["min"] == 50 * MS / (60 * MS)


def test_an_accumulated_elapsed_time_s_rounding_never_reads_as_faster_than_real_time():
    """CARLA's elapsed_seconds is a double that accumulates the step: a step of exactly the generated length can read a
    few ulps long. Counted in steps (and in whole ns), it is exactly one step, and a paced take's RTF is exactly 1."""
    elapsed, t = [1.25], 1.25
    for _k in range(200):
        t += 0.05
        elapsed.append(t)
    t_cur = [k * 50 * MS for k in range(201)]
    assert any((b - a) / 0.05 > 1 for a, b in zip(elapsed, elapsed[1:]))          # the raw ratio would exceed 1
    s = sendpolicy.rtf_summary(elapsed, t_cur, 50 * MS)
    assert s == {"min": 1.0, "mean": 1.0, "max": 1.0}
    assert sendpolicy.sim_advance_ns(1.25, 1.3) == 50 * MS


def _single_step_elapsed(start_s, step_s, n):
    """elapsed_seconds as a server that keeps its step in single precision reports it: the start plus n steps, each the
    step rounded to single precision, accumulated in a double (the fake simulator's float32_step)."""
    out, t = [start_s], start_s
    for _k in range(n):
        t += fake.single(step_s)
        out.append(t)
    return out


def test_a_server_that_keeps_its_step_in_single_precision_reads_as_paced_with_an_rtf_of_exactly_one():
    """A synthetic server advances elapsed_seconds by the single-precision value of the step,
    with every step current exactly one interval after the previous. Read in
    whole ns each advance is a nanosecond longer than the step, so every step's RTF read above 1 and the mean, the total
    read once, below them; counted in steps every advance is exactly one, and the triple is exactly 1."""
    step_ns = 50 * MS
    elapsed = _single_step_elapsed(5.25, 0.05, 600)
    t_cur = [k * step_ns for k in range(601)]
    pairs = list(zip(elapsed, elapsed[1:]))
    assert {sendpolicy.sim_advance_ns(a, b) for a, b in pairs} == {step_ns + 1}                       # the premise
    assert sendpolicy.sim_advance_ns(elapsed[0], elapsed[-1]) / t_cur[-1] < (step_ns + 1) / step_ns   # the old mean, below
    assert {sendpolicy.step_advance_ns(a, b, step_ns) for a, b in pairs} == {step_ns}
    assert sendpolicy.rtf_per_step(elapsed, t_cur, step_ns)[1:] == [1.0] * 600
    assert sendpolicy.rtf_summary(elapsed, t_cur, step_ns) == {"min": 1.0, "mean": 1.0, "max": 1.0}


def test_min_mean_and_max_come_from_one_computation_so_min_le_mean_le_max():
    """The mean is the sum of the very per-step advances min and max are taken over, over the total wall time. Advances
    off the step grid (read as they read, in whole ns, each rounding down): the old mean, the total read once, rose above
    every step's RTF, and now equals them; on steps of unequal wall time the mean lies strictly between min and max."""
    step_ns = 50 * MS
    adv_s = 0.05 + 100.4e-9                                    # off the grid by more than the tolerance
    elapsed = [1.0 + k * adv_s for k in range(6)]
    per_adv = [sendpolicy.step_advance_ns(a, b, step_ns) for a, b in zip(elapsed, elapsed[1:])]
    assert per_adv == [step_ns + 100] * 5
    assert sendpolicy.sim_advance_ns(elapsed[0], elapsed[-1]) == 5 * step_ns + 502                    # the old total
    s = sendpolicy.rtf_summary(elapsed, [k * step_ns for k in range(6)], step_ns)
    assert s["min"] == s["mean"] == s["max"] == (step_ns + 100) / step_ns
    uneven = [0, 50 * MS, 110 * MS, 160 * MS, 230 * MS, 280 * MS]
    s = sendpolicy.rtf_summary(elapsed, uneven, step_ns)
    assert s["min"] < s["mean"] < s["max"] and s["mean"] == sum(per_adv) / uneven[-1]


def test_an_advance_counts_as_whole_steps_only_within_the_quantization_tolerance():
    """STEP_QUANT_TOL is the named design value 2^-20 of a step, sixteen times the largest relative error single precision
    puts in a step (2^-24): an advance within it of a whole number of steps counts as exactly that many generated steps;
    anything else reads as it reads, in whole ns -- a world on another step, one and a half steps, a stall, time running
    backwards."""
    step_ns = 50 * MS
    assert sendpolicy.STEP_QUANT_TOL == 2.0 ** -20
    assert sendpolicy.step_advance_ns(1.0, 1.0 + 0.05 * (1 + 2.0 ** -21), step_ns) == step_ns           # inside
    assert sendpolicy.step_advance_ns(1.0, 1.0 + 0.05 * (1 - 2.0 ** -21), step_ns) == step_ns           # inside, short of the grid
    assert sendpolicy.sim_advance_ns(1.0, 1.0 + fake.single(0.04)) == 40 * MS - 1                        # a single-precision 40 ms step reads short
    assert sendpolicy.step_advance_ns(1.0, 1.0 + fake.single(0.04), 40 * MS) == 40 * MS                 # and counts as the step
    beyond = 1.0 + 0.05 * (1 + 2.0 ** -18)                                                              # another step
    assert sendpolicy.step_advance_ns(1.0, beyond, step_ns) == sendpolicy.sim_advance_ns(1.0, beyond) > step_ns
    assert sendpolicy.step_advance_ns(1.0, 1.0 + 2 * fake.single(0.05), step_ns) == 2 * step_ns         # two at once
    assert sendpolicy.step_advance_ns(1.0, 1.075, step_ns) == 75 * MS
    assert sendpolicy.step_advance_ns(1.0, 1.0, step_ns) == 0
    assert sendpolicy.step_advance_ns(1.05, 1.0, step_ns) == -50 * MS
    assert sendpolicy.step_advance_ns(1.0, 1.0 + 3e-8, step_ns) == 0                                     # a near stall: no step
    assert sendpolicy.step_advance_ns(1.0, 1.03, step_ns) == sendpolicy.sim_advance_ns(1.0, 1.03) == 30 * MS   # 0.6 of a step


def test_a_skipped_frame_shows_as_an_rtf_of_two_and_a_gap():
    frames = [10, 11, 13, 14]
    elapsed = [0.5, 0.55, 0.65, 0.70]                          # the snapshot's own time advanced two steps once
    t_cur = [0, 50 * MS, 100 * MS, 150 * MS]
    assert sendpolicy.rtf_per_step(elapsed, t_cur, 50 * MS)[2] == pytest.approx(2.0)
    assert sendpolicy.rtf_summary(elapsed, t_cur, 50 * MS)["max"] > 1
    assert sendpolicy.skipped_frames(frames) == [2]
    assert sendpolicy.gaps(frames, t_cur, 70 * MS) == [2]


def test_a_repeated_or_backward_frame_number_is_a_skipped_frame():
    assert sendpolicy.skipped_frames([5, 6, 6, 7]) == [2] and sendpolicy.skipped_frames([5, 7, 6]) == [1, 2]


def test_a_step_current_more_than_the_cap_after_the_previous_is_a_gap_and_at_the_cap_is_not():
    assert sendpolicy.gaps([1, 2, 3], [0, 70 * MS, 141 * MS], 70 * MS) == [2]


# =================================================================================================================
# drive.py: the segments, their gears and the scripted commands (D5)
# =================================================================================================================

def test_the_segments_and_their_gears_are_the_specifications():
    """Spec 2.2's segments with the route drive of the owner's option (a) in place of the Traffic Manager's."""
    assert drive.SEGMENTS == ("start", "route drive", "hard brake", "stopped", "reverse", "reverse stop", "stopped in reverse")
    assert drive.SEGMENT_GEAR == {"start": 0, "route drive": 1, "hard brake": 1, "stopped": 0, "reverse": -1,
                                  "reverse stop": -1, "stopped in reverse": -1}
    assert drive.SEGMENTS.count(replaycheck.HARD_BRAKE_LABEL) == 1


STEP_S = 0.05
L_M = 2.819


def _straight_ref(n=400, turns=((5, "left"),)):
    """A reference path along +x from the origin at 1 m spacing (this file's own), with turn records at the indices given:
    the Driver counts a turn by its index, so a straight path can stand for a route that has turned."""
    pts = [(float(k), 0.0, 0.0) for k in range(n)]
    return drive.reference(pts, short_route(), L_M), list(turns)


class _Feed:
    """Readings the Driver decides on, step by step: a car along +x at x (or advanced by its speed), its speed, a lateral
    offset y, its yaw and its gearbox gear."""

    def __init__(self, drv, ref=None, turns=None, stop_speed=0.005, route=None):
        if ref is None:
            ref, turns = _straight_ref()
        self.d = drive.Driver(drv, route or short_route(), ref, turns, STEP_S, stop_speed, L_M)
        self.segs, self.cmds, self.x = [], [], 0.0

    def step(self, i, speed, y=0.0, yaw=0.0, gear=1, x=None):
        self.x = self.x + speed * STEP_S if x is None else x
        last = None if i == 0 else {"v": [speed, 0.0, 0.0], "fwd": [1.0, 0.0, 0.0], "loc": [self.x, y, 0.3], "yaw": yaw,
                                    "steer": 0.0, "gear": gear}
        cmds = self.d.before_step(i, last)
        self.cmds += [(i, c.cmd, c.args) for c in cmds]
        self.segs.append(self.d.segment)


def _to_route_drive(f, drv, gear=1):
    """Run the start's hold: the steps 0 .. start_hold, the last of which enters the route drive."""
    n = f.d.steps(drv.start_hold_s)
    for i in range(n + 1):
        f.step(i, 0.0, gear=gear)
    assert f.segs[-1] == "route drive"
    return n + 1


def test_the_driver_runs_the_segments_in_order_with_their_commands():
    """Holds of two steps; past the turn (40 m in) at 7 m/s on a straight, the hard brake enters after brake_hold_s in the
    band; it ends at the step whose reading is below the stop speed, the reverse stop likewise, and the final hold ends the
    drive after its two steps. Only "control" commands: one per route-drive step, one at each other segment's entry."""
    drv = short_drive(start_hold_s=0.1, brake_hold_s=0.1, stopped_hold_s=0.1, reverse_s=0.1, final_hold_s=0.1)
    f = _Feed(drv)
    i = _to_route_drive(f, drv)
    f.step(i, 7.0, x=40.0)
    i += 1
    while f.segs[-1] == "route drive":
        f.step(i, 7.0)
        i += 1
        assert i < 40
    for speed in [4.0, 0.0] + [0.0] * 2 + [0.5] * 2 + [0.5, 0.0] + [0.0] * 2:
        if f.d.done:
            break
        f.step(i, speed)
        i += 1
    assert f.d.done
    runs = [s for k, s in enumerate(f.segs) if k == 0 or s != f.segs[k - 1]]
    assert runs == list(drive.SEGMENTS)
    assert f.segs.count("hard brake") == 2 and f.segs.count("stopped") == 2 and f.segs.count("reverse") == 2
    assert f.segs.count("reverse stop") == 2 and f.segs.count("stopped in reverse") == 2
    assert {c for _i, c, _a in f.cmds} == {"control"}
    drive_steps = [k for k, s in enumerate(f.segs) if s == "route drive"]
    assert sorted(k for k, _c, _a in f.cmds if f.segs[k] == "route drive") == drive_steps
    entries = [(f.segs[k], a["brake"], a["throttle"], a["reverse"], a["steer"]) for k, _c, a in f.cmds if f.segs[k] != "route drive"]
    assert entries == [("start", drv.stopped_brake, 0.0, False, 0.0), ("hard brake", drv.hard_brake, 0.0, False, 0.0),
                       ("stopped", drv.stopped_brake, 0.0, False, 0.0), ("reverse", 0.0, drv.reverse_throttle, True, 0.0),
                       ("reverse stop", drv.reverse_stop_brake, 0.0, True, 0.0),
                       ("stopped in reverse", drv.stopped_brake, 0.0, True, 0.0)]


def _brake_entry(drv, ref, turns, speed=7.0, y=0.0, hold=5):
    """Six route-drive steps at 3 m/s (outside the band) from x = 30, then `hold` steps at `speed` from x = 40; the
    segment after them."""
    f = _Feed(drv, ref, turns)
    i = _to_route_drive(f, drv)
    for k in range(6):
        f.step(i, 3.0, y=y, x=30.0 if k == 0 else None)
        i += 1
    for k in range(hold):
        f.step(i, speed, y=y, x=40.0 if k == 0 else None)
        i += 1
    return f.segs[-1]


@pytest.mark.parametrize("what", ["turn-not-passed", "too-fast", "too-slow", "curve-ahead", "steering", "band-too-short"])
def test_the_hard_brake_waits_for_the_turns_the_straight_the_band_and_its_hold(what):
    """Each condition alone keeps the route drive going; with all of them the hard brake enters (the control case: the
    fourth step in the band, brake_hold_s being four steps)."""
    drv = short_drive(start_hold_s=0.05, brake_hold_s=0.2)
    ref, turns = _straight_ref()
    assert _brake_entry(drv, ref, turns) == "hard brake"
    kw = {}
    if what == "turn-not-passed":
        turns = [(30, "left")]                     # passed only beyond index 50
    elif what == "too-fast":
        kw["speed"] = 7.4
    elif what == "too-slow":
        kw["speed"] = 6.6
    elif what == "curve-ahead":                    # a right turn starting 40 m ahead of the band
        arc = [(79.0 + 10.0 * math.sin(math.radians(3 * j)), 10.0 - 10.0 * math.cos(math.radians(3 * j)), 0.0) for j in range(1, 30)]
        ref = drive.reference([(float(k), 0.0, 0.0) for k in range(80)] + arc, short_route(), L_M)
    elif what == "steering":
        kw["y"] = 3.0                              # off the path: the controller steers back, past the entry limit
    elif what == "band-too-short":
        kw["hold"] = 3
    assert _brake_entry(drv, ref, turns, **kw) == "route drive", what


def test_no_hard_brake_within_drive_max_s_is_a_drive_error():
    drv = short_drive(start_hold_s=0.05, drive_max_s=0.5)
    f = _Feed(drv)
    i = _to_route_drive(f, drv)
    with pytest.raises(drive.DriveError, match="drive_max_s"):
        for k in range(100):
            f.step(i + k, 3.0)


def test_a_stuck_ego_and_the_route_s_end_are_drive_errors():
    drv = short_drive(start_hold_s=0.05, stuck_s=0.5)
    f = _Feed(drv)
    i = _to_route_drive(f, drv)
    with pytest.raises(drive.DriveError, match="stuck"):
        for k in range(40):
            f.step(i + k, 0.0)                     # the launch holds the throttle, the ego does not move
    f = _Feed(short_drive(start_hold_s=0.05, turns_before_brake=9))
    i = _to_route_drive(f, drv)
    with pytest.raises(drive.DriveError, match="end"):
        for k in range(400):
            f.step(i + k, 7.0, x=float(min(399, 30 + k)))


def test_a_take_longer_than_its_cap_is_a_drive_error():
    f = _Feed(short_drive(max_take_s=1.0, start_hold_s=60.0))
    with pytest.raises(drive.DriveError, match="max_take_s"):
        for i in range(100):
            f.step(i, 0.0)


def test_the_two_stage_brake_lowers_the_brake_below_its_speed_once():
    drv = short_drive(start_hold_s=0.05, brake_hold_s=0.05, hard_brake_stage2=(1.0, 0.3))
    f = _Feed(drv)
    i = _to_route_drive(f, drv)
    f.step(i, 7.0, x=40.0)
    f.step(i + 1, 7.0)
    assert f.segs[-1] == "hard brake"
    for k, v in enumerate([3.0, 0.9, 0.5]):
        f.step(i + 2 + k, v)
    brakes = [a["brake"] for k, _c, a in f.cmds if f.segs[k] == "hard brake"]
    assert brakes == [drv.hard_brake, 0.3] and f.segs[-1] == "hard brake"


def test_the_launch_holds_the_brake_until_gear_one_then_releases_it_step_by_step():
    """Throttle against the brake (launch_engage) while the gearbox reads 0; from gear 1 the brake falls by its step, the
    throttle stays at most launch_throttle until launch_until."""
    drv = short_drive(start_hold_s=0.05)
    rv = short_route()
    f = _Feed(drv)
    i = _to_route_drive(f, drv, gear=0)
    for k in range(3):
        f.step(i + k, 0.0, gear=0)
    for k in range(3, 9):
        f.step(i + k, 0.0, gear=1)
    got = [(a["throttle"], a["brake"]) for k, _c, a in f.cmds if f.segs[k] == "route drive"]
    e_thr, e_brk, e_step = rv.launch_engage
    assert got[:4] == [(e_thr, e_brk)] * 4                   # entry, then three steps in gear 0
    brakes = [b for _t, b in got[4:]]
    assert brakes == pytest.approx([e_brk - e_step * k for k in range(1, len(brakes) + 1)])
    assert all(t <= rv.launch_throttle + 1e-12 for t, _b in got)


def test_the_steer_moves_at_most_its_rate_and_stays_within_its_maximum():
    drv = short_drive(start_hold_s=0.05)
    rv = short_route()
    f = _Feed(drv)
    i = _to_route_drive(f, drv)
    for k in range(200):
        f.step(i + k, 5.0, y=-200.0)                   # far left of the path: the controller steers right, hard
    steers = [a["steer"] for k, _c, a in f.cmds if f.segs[k] == "route drive"]
    srate = rv.steer_rate_deg_s * STEP_S / rv.deg_per_steer
    assert max(abs(b - a) for a, b in zip([0.0] + steers, steers)) <= srate + 1e-12
    assert min(steers) >= 0 and max(steers) == pytest.approx(rv.steer_abs_max)
    assert steers[1] - steers[0] == pytest.approx(srate)


def test_the_route_takes_each_branch_s_kind_in_turn_with_the_fallback():
    """On the fake's grid every branch offers left, straight and right: the sequence is taken as it stands. Where a kind
    is missing, turn_fallback's order decides."""
    m = fake.Map("Carla/Maps/Town01")
    start = m.get_waypoint(m.get_spawn_points()[1].location)
    rv = short_route(length_m=1200.0)
    pts, turns = drive.build_route(start, rv)
    assert len(pts) == 1200 and [k for _j, k in turns] == [rv.turn_sequence[n % len(rv.turn_sequence)] for n in range(len(turns))]
    assert len(turns) >= 7
    for j, kind in turns:                                  # the heading 25 points on tells the kind
        dy = drive.wrap180(pts[min(len(pts) - 1, j + 25)][2] - pts[j - 1][2])
        assert {"left": dy < -45, "right": dy > 45, "straight": abs(dy) < 1}[kind], (j, kind, dy)

    class _W:
        """A lane along +x that branches into `branches` at x = 3 (this test's own map)."""

        def __init__(self, x, yaw=0.0, branches=()):
            self.transform = fake.Transform(fake.Location(x, 0.0, 0.0), fake.Rotation(yaw=yaw))
            self.branches, self.x, self.is_junction = branches, x, False

        def next(self, d):
            if self.branches and self.x >= 3:
                return list(self.branches)
            return [_W(self.x + d, branches=self.branches)]

    class _Right(_W):
        def next(self, d):
            return [_W(self.x + d, 90.0)]

    pts, turns = drive.build_route(_W(0.0, branches=(_Right(4.0), _W(4.0))), short_route(length_m=8.0))
    assert turns == [(4, "straight")] and len(pts) == 8      # no left: turn_fallback's next, straight
    with pytest.raises(drive.DriveError, match="none of the kinds"):
        drive.build_route(_W(0.0, branches=(_Right(4.0), _Right(4.0))), short_route(length_m=8.0, turn_fallback=("left", "straight")))


def test_the_spawn_is_the_longest_straight_ahead_and_the_first_of_equals():
    m = fake.Map("Carla/Maps/Town01")
    wps = [m.get_waypoint(p.location) for p in m.get_spawn_points()]
    ahead = [drive.straight_ahead_m(w) for w in wps]
    assert ahead[1] == ahead[3] == max(ahead) and ahead.index(max(ahead)) == 1 and ahead[0] < ahead[1]
    assert drive.spawn_choice(wps) == 1
    assert drive.spawn_choice(wps[2:]) == 1                # the fourth alone is the longest there
    with pytest.raises(drive.DriveError):
        drive.spawn_choice([])


def test_the_reference_plan_starts_at_rest_and_keeps_its_limits():
    m = fake.Map("Carla/Maps/Town01")
    rv = short_route(length_m=900.0)
    pts, _turns = drive.build_route(m.get_waypoint(m.get_spawn_points()[1].location), rv)
    ref = drive.reference(pts, rv, L_M)
    v = ref.vplan
    assert v[0] == 0.0 and max(v) <= rv.v_cruise + 1e-12 and max(v) == pytest.approx(rv.v_cruise)
    ds = rv.spacing_m
    assert all(b * b - a * a <= 2 * rv.a_lim * ds + 1e-9 for a, b in zip(v, v[1:]))
    assert all(a * a - b * b <= 2 * rv.d_lim * ds + 1e-9 for a, b in zip(v, v[1:]))
    assert all(x >= rv.v_floor - 1e-12 for x in v[1:])
    turning = [k for k, kap in enumerate(ref.kappa) if abs(kap) > 1e-3]
    assert turning and all(v[k] <= math.sqrt(rv.ay_drive / abs(ref.kappa[k])) + 1e-9 or v[k] <= rv.v_turn_min + 1e-9 for k in turning)
    assert ref.dff[turning[len(turning) // 2]] == pytest.approx(math.degrees(math.atan(L_M * ref.kappa[turning[len(turning) // 2]])))
    assert 0 < ref.planned_rate_max <= rv.steer_rate_deg_s


# =================================================================================================================
# frameset.py: the reduction, the PNG and the set (2.4)
# =================================================================================================================

def _bgra(w=320, h=256, fill=(0, 0, 0, 255)):
    return bytearray(bytes(fill) * (w * h))


def _put(buf, row, col, bgr, w=320):
    k = (row * w + col) * 4
    buf[k], buf[k + 1], buf[k + 2] = bgr


def test_grey_is_bt601_in_per_mille_with_rounding():
    buf = _bgra()
    for r in range(4):
        for c in range(4):
            _put(buf, r, 32 + c, (10, 20, 30))       # B, G, R
    out = frameset.reduce_bgra(bytes(buf))
    y = (299 * 30 + 587 * 20 + 114 * 10 + 500) // 1000
    assert len(out) == 64 * 64 and out[0] == (16 * y + 8) // 16 and out[1] == 0


@pytest.mark.parametrize("bgr,want", [((0, 0, 2), 1), ((0, 0, 1), 0), ((0, 1, 0), 1), ((5, 0, 0), 1), ((4, 0, 0), 0)])
def test_each_grey_weight_and_the_half_up_rounding(bgr, want):
    buf = _bgra()
    for r in range(4):
        for c in range(4):
            _put(buf, r, 32 + c, bgr)
    assert frameset.reduce_bgra(bytes(buf))[0] == want


def test_the_crop_is_the_centre_256_columns():
    buf = _bgra()
    for r in range(256):
        _put(buf, r, 31, (255, 255, 255))           # just left of the crop
        _put(buf, r, 288, (255, 255, 255))          # just right of it
    assert frameset.reduce_bgra(bytes(buf)) == bytes(64 * 64)
    buf = _bgra()
    for r in range(4):
        _put(buf, r, 32, (255, 255, 255))           # the crop's first column
        _put(buf, r, 287, (255, 255, 255))          # its last
    out = frameset.reduce_bgra(bytes(buf))
    assert out[0] == (4 * 255 + 8) // 16 and out[63] == (4 * 255 + 8) // 16 and out[1] == 0


@pytest.mark.parametrize("ones,want", [(8, 1), (7, 0), (24, 2), (23, 1)])
def test_the_block_mean_rounds_half_up(ones, want):
    """A 4x4 block whose greys sum to `ones`: the output is (sum + 8) // 16. Per-pixel greys from the green channel alone:
    G=1 gives 1 ((587 + 500) // 1000), G=3 gives 2 ((1761 + 500) // 1000)."""
    buf = _bgra()
    vals = [1] * min(ones, 16) + [0] * (16 - min(ones, 16))
    if ones > 16:
        vals = [2] * (ones - 16) + [1] * (16 - (ones - 16))
    k = 0
    for r in range(4):
        for c in range(4):
            _put(buf, r, 32 + c, (0, {0: 0, 1: 1, 2: 3}[vals[k]], 0))
            k += 1
    assert sum(vals) == ones
    assert frameset.reduce_bgra(bytes(buf))[0] == want


def test_a_buffer_of_another_size_is_refused():
    with pytest.raises(frameset.FrameSetError):
        frameset.reduce_bgra(bytes(320 * 240 * 4))


def _chunks(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    k, out = 8, []
    while k < len(png):
        n = struct.unpack(">I", png[k:k + 4])[0]
        typ, data, crc = png[k + 4:k + 8], png[k + 8:k + 8 + n], struct.unpack(">I", png[k + 8 + n:k + 12 + n])[0]
        assert crc == zlib.crc32(typ + data) & 0xFFFFFFFF
        out.append((typ, data))
        k += 12 + n
    return out


def test_the_png_is_64x64_eight_bit_grey_not_interlaced_with_ihdr_idat_iend_only():
    grey = bytes((r * 3 + c) % 256 for r in range(64) for c in range(64))
    png = frameset.png_bytes(grey)
    ch = _chunks(png)
    assert ch[0][0] == b"IHDR" and ch[-1][0] == b"IEND" and {t for t, _d in ch[1:-1]} == {b"IDAT"}
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", ch[0][1])
    assert (w, h, depth, ctype, comp, filt, inter) == (64, 64, 8, 0, 0, 0, 0)
    raw = zlib.decompress(b"".join(d for t, d in ch if t == b"IDAT"))
    rows = [raw[k * 65:(k + 1) * 65] for k in range(64)]
    assert all(r[0] == 0 for r in rows) and b"".join(r[1:] for r in rows) == grey
    assert frameset.png_pixels(png) == grey


def _set_meta():
    return dict(seed=7, stride_steps=20, town="Town01", blueprint="vehicle.toyota.prius")


def test_the_set_is_labelled_and_frames_json_is_written_last(tmp_path):
    root = tmp_path / "frames"
    root.mkdir()
    w = frameset.FrameSetWriter(root, "20261017-carla-7", **_set_meta())
    w.add(0, 101, bytes(4096))
    w.add(20, 121, bytes(range(256)) * 16)
    assert not (root / "20261017-carla-7" / "frames.json").exists()           # only close() writes it
    doc = w.close("ab" * 32)
    d = root / "20261017-carla-7"
    on_disk = json.loads((d / "frames.json").read_text(encoding="utf-8"))
    assert on_disk == doc
    assert list(doc) == ["format", "simulated", "generator", "name", "carla_version", "town", "seed", "blueprint", "camera",
                         "reduction", "stride_steps", "licence", "take_sha256", "frames"]
    assert doc["format"] == 1 and doc["simulated"] is True and doc["generator"] == "carla" and doc["take_sha256"] == "ab" * 32
    assert doc["camera"] == {"type": "sensor.camera.rgb", "width": 320, "height": 256, "mount": {"x": 1.5, "y": 0.0, "z": 1.6}}
    assert doc["reduction"] == {"grey": "BT.601", "crop": "centre-square", "size": 64, "resample": "4x4-block-mean"}
    assert doc["licence"] == "CARLA assets: CC-BY (CARLA's README). Simulated frames; never published."
    assert [f["file"] for f in doc["frames"]] == ["frame-000000.png", "frame-000020.png"]
    for f in doc["frames"]:
        assert f["sha256"] == hashlib.sha256((d / f["file"]).read_bytes()).hexdigest()
    assert sorted(p.name for p in d.iterdir()) == ["frame-000000.png", "frame-000020.png", "frames.json"]
    with pytest.raises(frameset.FrameSetError):
        w.add(40, 141, bytes(4096))                                            # nothing after frames.json
    assert frameset.read_set(d)["name"] == "20261017-carla-7"


def test_the_writer_refuses_an_existing_set_a_bad_name_a_relative_root_and_a_work_tree(tmp_path):
    root = tmp_path / "frames"
    (root / "20261017-carla-7").mkdir(parents=True)
    with pytest.raises(frameset.FrameSetError, match="exists"):
        frameset.FrameSetWriter(root, "20261017-carla-7", **_set_meta())
    for bad in ("../x", "Bad", "a/b", ""):
        with pytest.raises(frameset.FrameSetError):
            frameset.FrameSetWriter(root, bad, **_set_meta())
    with pytest.raises(frameset.FrameSetError):
        frameset.FrameSetWriter(Path("frames"), "20261017-carla-8", **_set_meta())
    tree = tmp_path / "tree"
    (tree / ".git").mkdir(parents=True)
    with pytest.raises(frameset.FrameSetError, match="work tree"):
        frameset.FrameSetWriter(tree / "frames", "20261017-carla-9", **_set_meta())
    w = frameset.FrameSetWriter(root, "20261017-carla-10", **_set_meta())
    for bad_i in (-1, 10 ** 6):
        with pytest.raises(frameset.FrameSetError):
            w.add(bad_i, 1, bytes(4096))
    with pytest.raises(frameset.FrameSetError):
        w.add(0, 1, bytes(4095))                                               # only a reduced frame is ever written


def test_a_git_file_marks_a_work_tree_too(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: E:/elsewhere\n", encoding="ascii")
    assert frameset.inside_work_tree(tmp_path / "wt" / "a" / "b")
    assert not frameset.inside_work_tree(tmp_path / "plain")


def test_a_set_directory_that_itself_holds_git_is_refused(tmp_path):
    d = _good_set(tmp_path)
    (d / ".git").write_text("gitdir: x\n", encoding="ascii")
    with pytest.raises(frameset.FrameSetError, match="work tree"):
        frameset.read_set(d)


def test_the_writer_refuses_a_second_frame_for_one_step(tmp_path):
    w = frameset.FrameSetWriter(tmp_path / "frames", "20261017-carla-7", **_set_meta())
    w.add(20, 120, bytes(4096))
    with pytest.raises(frameset.FrameSetError, match="a frame already"):
        w.add(20, 121, bytes(4096))


def _good_set(tmp_path):
    root = tmp_path / "frames"
    root.mkdir(exist_ok=True)
    w = frameset.FrameSetWriter(root, "20261017-carla-7", **_set_meta())
    w.add(0, 101, bytes(4096))
    w.close("cd" * 32)
    return root / "20261017-carla-7"


def _rewrite_json(d, edit):
    p = d / "frames.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    edit(doc)
    p.write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize("fault", ["no-json", "format", "simulated", "simulated-missing", "generator", "missing-file",
                                   "sha256", "extra-file", "not-grey", "interlaced", "listed-twice", "bad-file-name", "not-json",
                                   "format-bool", "frames-not-list", "file-not-its-i", "i-not-an-int"])
def test_the_reader_refuses_each_case_of_the_specification(tmp_path, fault):
    d = _good_set(tmp_path)
    if fault == "no-json":
        (d / "frames.json").unlink()
    elif fault == "format":
        _rewrite_json(d, lambda j: j.update(format=2))
    elif fault == "simulated":
        _rewrite_json(d, lambda j: j.update(simulated="true"))
    elif fault == "simulated-missing":
        _rewrite_json(d, lambda j: j.pop("simulated"))
    elif fault == "generator":
        _rewrite_json(d, lambda j: j.update(generator="camera"))
    elif fault == "missing-file":
        (d / "frame-000000.png").unlink()
    elif fault == "sha256":
        _rewrite_json(d, lambda j: j["frames"][0].update(sha256="0" * 64))
    elif fault == "extra-file":
        (d / "notes.txt").write_text("x", encoding="ascii")
    elif fault in ("not-grey", "interlaced"):
        png = (d / "frame-000000.png").read_bytes()
        ch = _chunks(png)
        ihdr = bytearray(ch[0][1])
        if fault == "not-grey":
            ihdr[9] = 2                                                         # colour type 2 (RGB)
        else:
            ihdr[12] = 1                                                        # Adam7: 2.4's PNG is not interlaced
        body = b"IHDR" + bytes(ihdr)
        bad = png[:8] + struct.pack(">I", 13) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF) + png[33:]
        (d / "frame-000000.png").write_bytes(bad)
        _rewrite_json(d, lambda j: j["frames"][0].update(sha256=hashlib.sha256(bad).hexdigest()))
    elif fault == "listed-twice":
        _rewrite_json(d, lambda j: j["frames"].append(dict(j["frames"][0])))
    elif fault == "bad-file-name":
        _rewrite_json(d, lambda j: j["frames"][0].update(file="../frame-000000.png"))
    elif fault == "not-json":
        (d / "frames.json").write_text("{", encoding="utf-8")
    elif fault == "format-bool":
        _rewrite_json(d, lambda j: j.update(format=True))
    elif fault == "frames-not-list":
        _rewrite_json(d, lambda j: j.update(frames={}))
    elif fault == "file-not-its-i":
        # frame-000000.png listed for step 20: a reader that names a step by the listed index would name the wrong one (fable#4)
        _rewrite_json(d, lambda j: j["frames"][0].update(i=20))
    elif fault == "i-not-an-int":
        _rewrite_json(d, lambda j: j["frames"][0].update(i="0"))
    with pytest.raises(frameset.FrameSetError):
        frameset.read_set(d)


def test_the_reader_refuses_a_set_inside_a_work_tree(tmp_path):
    d = _good_set(tmp_path)
    (tmp_path / ".git").mkdir()
    with pytest.raises(frameset.FrameSetError, match="work tree"):
        frameset.read_set(d)


# =================================================================================================================
# fwcheck.py: 2.5's predicate over the cmdlets' read
# =================================================================================================================

FW_CASES = json.loads((FIX / "fwcheck-cases.json").read_text(encoding="utf-8"))


def test_the_fixture_names_the_exe_fwcheck_names():
    assert FW_CASES["exe"] == fwcheck.EXE_PATH and fwcheck.WSL_ALIAS_PREFIX == "vEthernet (WSL"
    assert FW_CASES["wsl_alias"].startswith(fwcheck.WSL_ALIAS_PREFIX)
    assert FW_CASES["interpreters"][1] == fwcheck.VENV + "\\Scripts\\python.exe"


def _interp():
    return list(FW_CASES["interpreters"])


@pytest.mark.parametrize("for_", ["windows-client", "wsl"])
@pytest.mark.parametrize("case", FW_CASES["cases"], ids=[c["name"] for c in FW_CASES["cases"]])
def test_fwcheck_prints_what_the_specification_says_for_each_case(case, for_):
    snap = fwcheck.parse(case["doc"])
    assert fwcheck.result_lines(fwcheck.check(snap, for_, _interp()), for_) == case["expect"][for_], case["what"]


def test_every_clause_of_the_predicate_has_a_failing_case():
    clauses = set()
    for case in FW_CASES["cases"]:
        for line in case["expect"]["windows-client"] + case["expect"]["wsl"]:
            m = re.match(r"fwcheck: FAIL \([a-z-]+\): (\w+):", line)
            if m:
                clauses.add(m.group(1))
    assert clauses == {"P1", "P2", "P3", "P4", "read"}


@pytest.mark.parametrize("name", ["interpreter-allow-any", "unbound-tm-port"])
def test_without_a_traffic_manager_p4_is_not_applied_and_the_line_says_so(name):
    """--no-tm (a client that runs no Traffic Manager) waives P4 alone, and says so in the line; P1-P3 still hold."""
    case = next(c for c in FW_CASES["cases"] if c["name"] == name)
    snap = fwcheck.parse(case["doc"])
    for for_ in ("windows-client", "wsl"):
        assert any(": P4: " in ln for ln in case["expect"][for_])
        assert fwcheck.result_lines(fwcheck.check(snap, for_, _interp(), tm=False), for_, tm=False) == \
            ["fwcheck: PASS (%s, no TM: P4 not applied)" % for_]
    today = next(c for c in FW_CASES["cases"] if c["name"] == "today")
    lines = fwcheck.result_lines(fwcheck.check(fwcheck.parse(today["doc"]), "windows-client", (), tm=False), "windows-client", tm=False)
    assert lines and all(ln.startswith("fwcheck: FAIL (windows-client, no TM: P4 not applied): P2: ") for ln in lines)


class _Runner:
    def __init__(self, rc=0, out=None, err=""):
        self.rc, self.out, self.err, self.cmds = rc, out, err, []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        return self.rc, self.out, self.err


def test_main_reads_with_powershell_from_the_active_store_and_writes_nothing(capsys):
    r = _Runner(out=json.dumps(FW_CASES["cases"][0]["doc"]))
    assert fwcheck.main(["--for", "windows-client"], runner=r, windows=True, interpreters=_interp) == 0
    assert capsys.readouterr().out == "fwcheck: PASS (windows-client)\n"
    cmd = r.cmds[0]
    assert cmd[0].lower().startswith("powershell") and "-NoProfile" in cmd and "-NonInteractive" in cmd
    script = cmd[-1]
    calls = re.findall(r"\b(Get-NetFirewall\w+)\b([^\n|;]*)", script)
    assert {c for c, _a in calls} == {"Get-NetFirewallProfile", "Get-NetFirewallRule", "Get-NetFirewallApplicationFilter",
                                      "Get-NetFirewallServiceFilter", "Get-NetFirewallPortFilter", "Get-NetFirewallAddressFilter",
                                      "Get-NetFirewallInterfaceFilter"}
    assert all("-PolicyStore $st" in a or "-PolicyStore ActiveStore" in a for _c, a in calls), calls
    assert "$st = 'ActiveStore'" in script and "Get-NetIPAddress" in script and "vEthernet (WSL" in script
    assert not re.search(r"\b(Set|New|Remove|Enable|Disable|Copy|Rename)-\w+", script)


def test_the_filters_are_read_rule_by_rule_through_the_pipeline_never_in_bulk():
    """A non-elevated shell is denied the port, address and interface filters in bulk but not per rule:
    every filter is read through the pipeline from the inbound rules, and nothing is read with -All. The rule's Owner, the
    application filter's Package and the service filter's Service are read, and a program's environment variables
    expanded."""
    script = fwcheck.PS_SCRIPT
    assert "-All" not in script
    for f in ("Application", "Service", "Port", "Address", "Interface"):
        assert re.search(r"\$inbound \| Get-NetFirewall%sFilter -PolicyStore \$st\)" % f, script), f
    assert "$inbound = @(Get-NetFirewallRule -PolicyStore $st -Direction Inbound)" in script
    assert "$rules = @($inbound | ForEach-Object" in script
    for field in ("Owner = [string]$_.Owner", "[string]$a.Package", "Service = (S $svc[$k].Service)", "ExpandEnvironmentVariables"):
        assert field in script, field


@pytest.mark.parametrize("which,code", [("today", 1), ("scoped", 0), ("interpreter-allow-any", 1)])
def test_main_exits_0_only_on_pass_and_prints_one_line_per_failing_rule(capsys, which, code):
    case = next(c for c in FW_CASES["cases"] if c["name"] == which)
    assert fwcheck.main(["--for", "windows-client"], runner=_Runner(out=json.dumps(case["doc"])), windows=True,
                        interpreters=_interp) == code
    assert capsys.readouterr().out.splitlines() == case["expect"]["windows-client"]


def test_main_with_no_tm_waives_p4_and_without_the_interpreters_read_is_not_a_pass(capsys):
    case = next(c for c in FW_CASES["cases"] if c["name"] == "interpreter-allow-any")
    doc = json.dumps(case["doc"])
    assert fwcheck.main(["--for", "windows-client", "--no-tm"], runner=_Runner(out=doc), windows=True,
                        interpreters=lambda: pytest.fail("--no-tm reads no interpreter")) == 0
    assert capsys.readouterr().out == "fwcheck: PASS (windows-client, no TM: P4 not applied)\n"

    def unreadable():
        raise OSError("no pyvenv.cfg")
    r = _Runner(out=doc)
    assert fwcheck.main(["--for", "windows-client"], runner=r, windows=True, interpreters=unreadable) == 2
    assert fwcheck.main(["--for", "windows-client"], runner=r, windows=True, interpreters=lambda: ()) == 2
    out = capsys.readouterr()
    assert "PASS" not in out.out and "interpreter" in out.err and r.cmds == []


def test_the_interpreters_are_the_venv_s_base_python_and_its_own():
    cfg = "include-system-site-packages = false\nHome =  C:\\Program Files\\Python312 \nversion = 3.12.10\n"
    assert fwcheck.interpreters_of(cfg) == ("C:\\Program Files\\Python312\\python.exe", "E:\\CARLA\\venv312\\Scripts\\python.exe")
    with pytest.raises(ValueError):
        fwcheck.interpreters_of("version = 3.12.10\n")
    with pytest.raises(ValueError):
        fwcheck.interpreters_of("home =\n")
    assert fwcheck.names_interpreter("c:/program files/python312/PYTHON.EXE", fwcheck.interpreters_of(cfg))
    assert not fwcheck.names_interpreter("C:\\Program Files\\Python312\\pythonw.exe", fwcheck.interpreters_of(cfg))


def test_the_read_s_output_is_ascii_whatever_the_console_s_code_page(monkeypatch):
    """A rule name in the console code page's own letters stopped the read on a PC whose code page is not UTF-8:
    the read escapes every non-ASCII character as \\uXXXX, _powershell takes stdout as
    ASCII only, and stdout that is not ASCII is a failed read (exit 2), never decoded by a guess."""
    assert "[regex]::Replace($json, '[^\\x00-\\x7F]', { param($m) '\\u{0:x4}' -f [int][char]$m.Value })" in fwcheck.PS_SCRIPT
    assert fwcheck.PS_SCRIPT.rstrip().endswith("[int][char]$m.Value })")
    scoped = next(c for c in FW_CASES["cases"] if c["name"] == "scoped")
    doc = json.loads(json.dumps(scoped["doc"]))
    doc["rules"][0]["DisplayName"] = "Café CARLA"
    escaped = json.dumps(doc).encode("ascii")                      # json.dumps escapes as the read does
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    calls = []

    def fake_run(cmd, capture_output=False, timeout=None, **kw):
        calls.append(kw)
        return types.SimpleNamespace(returncode=0, stdout=fake_run.out, stderr="dénié".encode("cp1252"))
    monkeypatch.setattr(fwcheck.subprocess, "run", fake_run)
    fake_run.out = escaped
    rc, out, err = fwcheck._powershell(fwcheck.command())
    assert rc == 0 and json.loads(out)["rules"][0]["DisplayName"] == "Café CARLA" and calls == [{}]
    assert fwcheck.run("windows-client", interpreters=_interp) == (0, ["fwcheck: PASS (windows-client)"])
    fake_run.out = raw
    rc, out, err = fwcheck._powershell(fwcheck.command())
    assert rc == -1 and out == "" and "not ASCII" in err
    got = fwcheck.run("windows-client", interpreters=_interp)
    assert got[0] == 2 and got[1][0].startswith("fwcheck: the firewall read failed (-1)")


def test_a_read_that_fails_or_is_not_json_is_not_a_pass(capsys):
    assert fwcheck.main(["--for", "wsl"], runner=_Runner(rc=1, out="", err="denied"), windows=True, interpreters=_interp) == 2
    assert fwcheck.main(["--for", "wsl"], runner=_Runner(out="not json"), windows=True, interpreters=_interp) == 2
    # a PowerShell that exited non-zero is a failed read even when it printed a document that would pass (verify#8)
    scoped = next(c for c in FW_CASES["cases"] if c["name"] == "scoped")
    assert fwcheck.main(["--for", "windows-client"], runner=_Runner(rc=1, out=json.dumps(scoped["doc"]), err="partial"),
                        windows=True, interpreters=_interp) == 2
    assert "PASS" not in capsys.readouterr().out


def test_fwcheck_runs_on_windows_only(capsys):
    assert fwcheck.main(["--for", "wsl"], runner=_Runner(out="{}"), windows=False) == 2
    assert "Windows" in capsys.readouterr().err


# =================================================================================================================
# carla_capture.py against the fake simulator
# =================================================================================================================

@NEEDS_CONTRACT
def test_a_take_writes_its_four_files_with_exactly_the_specified_keys(tmp_path):
    rc, carla, take = run_take(tmp_path)
    assert rc == 0
    assert sorted(p.name for p in take.iterdir()) == ["capture.json", "script.jsonl", "steps.jsonl", "take.sha256"]
    steps = read_steps(take)
    assert [list(s) for s in steps[:1]] == [["i", "frame", "elapsed_s", "t_vals_ns", "t_cur_ns", "seg", "gear", "v", "a", "fwd",
                                             "w", "steer", "throttle", "brake", "reverse", "wheel_deg"]]
    assert all(list(s) == list(steps[0]) for s in steps)
    assert [s["i"] for s in steps] == list(range(len(steps)))
    assert steps[0]["t_cur_ns"] == 0 and steps[0]["t_vals_ns"] == 0
    for line in (take / "steps.jsonl").read_text(encoding="ascii").splitlines():
        assert ": " not in line and ", " not in line                       # compact
    cap = read_capture(take)
    for key in ("format", "name", "seed", "spawn_index", "client_version", "server_version", "map", "blueprint", "world_settings",
                "apply_settings_stderr", "tm", "ego", "camera", "drive", "collisions", "clock", "steps", "sim_s", "rtf", "gaps",
                "skipped_frames", "segments", "fwcheck", "capture_sha256", "completed", "cleanup", "errors"):
        assert key in cap, key
    assert cap["format"] == 1 and cap["completed"] is True and cap["cleanup"] == "ok" and cap["errors"] == []
    assert cap["steps"] == len(steps) and cap["camera"] is None and cap["map"].endswith("Town01")
    assert cap["tm"] is None and cap["collisions"] == []                      # no Traffic Manager runs under option (a)
    assert cap["capture_sha256"] == hashlib.sha256((CARLA_DIR / "carla_capture.py").read_bytes()).hexdigest()
    lines = (take / "take.sha256").read_text(encoding="ascii").splitlines()
    assert [ln.split("  ")[1] for ln in lines] == ["steps.jsonl", "script.jsonl", "capture.json"]
    for ln in lines:
        sha, name = ln.split("  ")
        assert sha == hashlib.sha256((take / name).read_bytes()).hexdigest()


@NEEDS_CONTRACT
def test_the_raw_readings_are_the_actors_own_getters_in_carla_s_axes(tmp_path):
    rc, carla, take = run_take(tmp_path)
    s = next(x for x in read_steps(take) if x["seg"] == "route drive" and abs(x["steer"]) > 0.01 and abs(x["v"][0]) + abs(x["v"][1]) > 1)
    fwd = s["fwd"]
    speed = sum(a * b for a, b in zip(s["v"], fwd))
    assert speed > 0
    # the fake's yaw rate is deg/s, right turn positive, from the steer's own sign: carried raw, unconverted
    assert math.copysign(1, s["w"][2]) == math.copysign(1, s["steer"])
    assert s["wheel_deg"] == pytest.approx([s["steer"] * fake.FAKE_MAX_STEER_DEG] * 2)


@NEEDS_CONTRACT
def test_the_world_is_tied_to_the_generated_step_and_the_substep_and_read_back(tmp_path):
    """Spec 4 item 2 and 2.2: synchronous mode, the generated step and the physics substep applied (the fake starts at CARLA's
    default substep, 0.01 s and 10), read back, and capture.json's world_settings holds exactly the six read-back keys."""
    assert (fake.WorldSettings().max_substep_delta_time, fake.WorldSettings().max_substeps) == (0.01, 10)
    rc, carla, take = run_take(tmp_path)
    assert rc == 0
    ws = read_capture(take)["world_settings"]
    step = C.CARLA_STEP_MS / 1000
    assert list(ws) == list(worldtie.READ_BACK) == ["synchronous_mode", "fixed_delta_seconds", "no_rendering_mode", "substepping",
                                                     "max_substep_delta_time", "max_substeps"]
    assert ws["synchronous_mode"] is True and ws["fixed_delta_seconds"] == step and ws["no_rendering_mode"] is False
    assert ws["substepping"] is True and ws["max_substep_delta_time"] == worldtie.SUBSTEP_S == 0.002
    assert ws["max_substeps"] == worldtie.max_substeps(step) == 25 and ws["max_substeps"] * worldtie.SUBSTEP_S >= step
    applied = [c for c in carla.sim.calls if c.startswith("apply_settings:")]
    assert applied == ["apply_settings:True", "apply_settings:False"]           # the tie, then the cleanup's restore


@pytest.mark.parametrize("step_s,n", [(0.05, 25), (0.002, 1), (0.0021, 2), (0.033, 17), (0.1, 50)])
def test_max_substeps_is_the_least_whole_number_that_covers_the_step(step_s, n):
    assert worldtie.max_substeps(step_s) == n and n * worldtie.SUBSTEP_S >= step_s - worldtie.FLOAT_TOL
    assert (n - 1) * worldtie.SUBSTEP_S < step_s


@NEEDS_CONTRACT
@pytest.mark.parametrize("ignored,start", [
    (("substepping",), {"substepping": False}), (("max_substep_delta_time",), {}), (("max_substeps",), {}),
    (("fixed_delta_seconds",), {}), (("synchronous_mode",), {}),
])
def test_a_world_that_ignores_one_setting_of_the_tie_is_refused_before_any_step(tmp_path, ignored, start):
    """Each of the five settings the capture applies, ignored alone by the world (the substepping case starts from a world
    without substepping, since CARLA's default has it on): refused before anything is spawned."""
    rc, carla, take = run_take(tmp_path, ignore_settings=ignored, start_settings=start)
    assert rc != 0
    cap = read_capture(take)
    assert cap["completed"] is False and cap["steps"] == 0 and any("world settings" in e and ignored[0] in e for e in cap["errors"])
    assert not any(c.startswith("spawn:") for c in carla.sim.calls)


@NEEDS_CONTRACT
def test_the_substep_warning_is_recorded_and_not_refused(tmp_path, capfd):
    """The fake emits a diagnostic below Python's sys.stderr. The capture records what apply_settings
    wrote to fd 2 and goes on; it does not treat that text as a refusal."""
    rc, carla, take = run_take(tmp_path)
    cap = read_capture(take)
    assert rc == 0 and cap["completed"] is True
    assert cap["apply_settings_stderr"] == fake.FAKE_SUBSTEP_WARNING
    assert fake.FAKE_SUBSTEP_WARNING not in capfd.readouterr().err        # captured, not passed through
    os.write(2, b"fd 2 is back\n")
    assert "fd 2 is back" in capfd.readouterr().err


def test_the_fd2_capture_restores_fd2_when_the_call_raises(capfd):
    def boom():
        os.write(2, b"before the error\n")
        raise RuntimeError("apply failed")
    with pytest.raises(RuntimeError, match="apply failed"):
        capture._fd2_text(boom)
    os.write(2, b"after\n")
    err = capfd.readouterr().err
    assert "after" in err and "before the error" not in err


@NEEDS_CONTRACT
@pytest.mark.parametrize("fault", [{"ignore_apply": True}, {"keep_async": True}])
def test_a_world_that_does_not_take_the_step_or_synchronous_mode_is_refused_before_any_step(tmp_path, fault):
    rc, carla, take = run_take(tmp_path, **fault)
    assert rc != 0
    cap = read_capture(take)
    assert cap["completed"] is False and cap["steps"] == 0 and any("settings" in e for e in cap["errors"])
    assert (take / "steps.jsonl").read_text(encoding="ascii") == ""
    assert not any(c.startswith("spawn:") for c in carla.sim.calls)


@NEEDS_CONTRACT
@pytest.mark.parametrize("client,server", [("0.9.16", "0.9.15"), ("0.9.15", "0.9.16"), ("0.10.0", "0.10.0")])
def test_client_and_server_must_both_be_0_9_16(tmp_path, client, server):
    rc, carla, take = run_take(tmp_path, client_version=client, server_version=server)
    assert rc != 0 and read_capture(take)["completed"] is False
    assert carla.sim.loads == [] and not any(c.startswith("spawn:") for c in carla.sim.calls)


@NEEDS_CONTRACT
def test_town01_is_loaded_exactly_when_the_server_is_elsewhere_and_never_twice(tmp_path):
    rc, carla, _take = run_take(tmp_path / "a")
    assert rc == 0 and carla.sim.loads == ["Town01"]
    rc, carla, take = run_take(tmp_path / "c", fresh_process=False)               # a second load in one process
    assert rc != 0 and carla.sim.loads == [] and any("load_world" in e for e in read_capture(take)["errors"])
    assert not any(c.startswith("spawn:") for c in carla.sim.calls)
    rc, carla, _take = run_take(tmp_path / "b", map_name="Carla/Maps/Town01")
    assert rc == 0 and carla.sim.loads == []


@NEEDS_CONTRACT
def test_the_cleanup_runs_in_the_specified_order(tmp_path):
    """Section 1's order without the Traffic Manager's steps (no TM runs, and an autopilot call would start one): the
    sensors stopped and destroyed, tick, the ego destroyed, tick, the world's settings restored."""
    rc, carla, take = run_take(tmp_path, frames="on")
    assert rc == 0
    calls = carla.sim.calls
    k = calls.index("stop:sensor.camera.rgb")
    tail = [c for c in calls[k:] if not c.startswith("listen")]
    assert tail == ["stop:sensor.camera.rgb", "destroy:sensor.camera.rgb", "stop:sensor.other.collision",
                    "destroy:sensor.other.collision", "tick", "destroy:vehicle.toyota.prius", "tick", "apply_settings:False"]


@NEEDS_CONTRACT
def test_capture_json_is_written_once_before_the_cleanup_and_once_after(tmp_path, monkeypatch):
    """The first write survives a cleanup that kills the client (Phase 1b's); the second carries the cleanup's outcome."""
    writes = []
    real = capture._write_json

    def spy(path, doc):
        writes.append((path.name, len(fake._SIM["sim"].calls), doc["cleanup"]))
        real(path, doc)
    monkeypatch.setattr(capture, "_write_json", spy)
    rc, carla, take = run_take(tmp_path, frames="on")
    calls = carla.sim.calls
    first_cleanup = calls.index("stop:sensor.camera.rgb")
    assert [w[0] for w in writes] == ["capture.json", "capture.json"]
    assert writes[0][1] <= first_cleanup and writes[0][2] == "not run"
    assert writes[1][1] == len(calls) and calls[writes[1][1] - 1] == "apply_settings:False" and writes[1][2] == "ok"


@NEEDS_CONTRACT
def test_no_traffic_manager_starts_and_every_control_goes_through_apply_batch_sync(tmp_path):
    """The capture uses no Traffic Manager or autopilot call, and applies every control with apply_batch_sync
    before its tick."""
    rc, carla, take = run_take(tmp_path)
    assert rc == 0
    calls = carla.sim.calls
    assert not any(c.startswith(("get_trafficmanager", "set_autopilot", "tm_", "apply_control")) for c in calls)
    script = (take / "script.jsonl").read_text(encoding="ascii").splitlines()
    assert calls.count("apply_batch_sync") == len(script) > 0
    assert read_capture(take)["tm"] is None


@NEEDS_CONTRACT
def test_the_take_launches_against_the_brake_until_the_gearbox_engages(tmp_path):
    """The controller reads the gearbox's gear (get_control().gear) from the step before: the fake's gearbox engages after
    FAKE_GEAR_ENGAGE_S of throttle, and until the reading says gear 1 every route-drive control holds the launch's
    throttle against its brake; from then the brake falls by its step."""
    rc, carla, take = run_take(tmp_path)
    assert rc == 0
    rv = short_route()
    ctl = [json.loads(x)["args"] for x in (take / "script.jsonl").read_text(encoding="ascii").splitlines()
           if json.loads(x)["seg"] == "route drive"]
    held = 0
    while (ctl[held]["throttle"], ctl[held]["brake"]) == rv.launch_engage[:2]:
        held += 1
    assert held == round(fake.FAKE_GEAR_ENGAGE_S / (C.CARLA_STEP_MS / 1000))
    assert ctl[held]["brake"] == pytest.approx(rv.launch_engage[1] - rv.launch_engage[2])


@NEEDS_CONTRACT
def test_a_control_the_server_did_not_apply_stops_the_take(tmp_path):
    rc, carla, take = run_take(tmp_path, apply_error_at=5)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["cleanup"] == "ok"
    assert any("not applied" in e and "the actor was not found" in e for e in cap["errors"])
    assert len((take / "script.jsonl").read_text(encoding="ascii").splitlines()) == 4


@NEEDS_CONTRACT
def test_a_collision_stops_the_take_and_is_recorded(tmp_path):
    hit = capture.SETTLE_TICKS + 30
    rc, carla, take = run_take(tmp_path, collide_at_tick=hit)
    cap = read_capture(take)
    assert rc == 1 and cap["completed"] is False and cap["cleanup"] == "ok"
    assert cap["collisions"] and cap["collisions"][0]["other"] == "static.fence"
    assert any("collided" in e for e in cap["errors"]) and cap["steps"] == hit - capture.SETTLE_TICKS


@NEEDS_CONTRACT
def test_capture_json_is_written_after_an_error_and_the_cleanup_still_runs(tmp_path):
    rc, carla, take = run_take(tmp_path, fail_at_tick=40)
    assert rc != 0
    cap = read_capture(take)
    assert cap["completed"] is False and cap["cleanup"] == "ok" and any("tick 40" in e for e in cap["errors"])
    assert (take / "take.sha256").is_file() and "destroy:vehicle.toyota.prius" in carla.sim.calls
    assert cap["steps"] == len(read_steps(take)) > 0


@NEEDS_CONTRACT
@pytest.mark.parametrize("float32_step", [False, True], ids=["double-step", "single-step"])
def test_the_pacing_holds_a_fast_simulator_to_one_step_per_interval(tmp_path, float32_step):
    rc, carla, take = run_take(tmp_path, float32_step=float32_step)
    steps = read_steps(take)
    cur = [s["t_cur_ns"] for s in steps]
    assert all(b - a == policy().interval_ns for a, b in zip(cur, cur[1:]))
    assert read_capture(take)["rtf"]["max"] <= 1 and read_capture(take)["gaps"] == []
    assert read_capture(take)["rtf"] == {"min": 1.0, "mean": 1.0, "max": 1.0}


@NEEDS_CONTRACT
def test_a_take_on_a_server_that_keeps_its_step_in_single_precision_is_paced_at_an_rtf_of_exactly_one(tmp_path):
    """The fake server advances elapsed_seconds by the single-precision value of fixed_delta_seconds,
    so every advance, read in whole ns, is longer than the generated step.
    The capture paces each step one interval after the previous all the same and records an RTF of exactly 1: the step's
    representation is not read as the pacing failing."""
    rc, carla, take = run_take(tmp_path, float32_step=True)
    assert rc == 0
    steps = read_steps(take)
    pairs = list(zip(steps, steps[1:]))
    raw = {sendpolicy.sim_advance_ns(a["elapsed_s"], b["elapsed_s"]) for a, b in pairs}
    assert raw == {int(round(fake.single(C.CARLA_STEP_MS / 1000) * 1e9))} != {C.CARLA_STEP_MS * MS}     # the premise
    assert {b["t_cur_ns"] - a["t_cur_ns"] for a, b in pairs} == {C.FEEDER_PACING_INTERVAL_MS * MS}
    cap = read_capture(take)
    assert cap["rtf"] == {"min": 1.0, "mean": 1.0, "max": 1.0} and cap["gaps"] == [] and cap["skipped_frames"] == []


@NEEDS_CONTRACT
def test_the_capture_counts_its_rtf_in_steps_of_the_step_when_the_pacing_interval_differs(tmp_path):
    """A contract whose pacing interval is 10 ms longer than its step, on a server that keeps its step in single
    precision: every step is current one interval after the previous, so every RTF, the mean and the max are exactly step
    over interval (the step is the unit, not the interval)."""
    c = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith("_")})
    c.FEEDER_PACING_INTERVAL_MS = int(C.CARLA_STEP_MS) + 10
    rc, _carla, take = run_take(tmp_path, contract=c, float32_step=True)
    assert rc == 0
    r = int(C.CARLA_STEP_MS) / c.FEEDER_PACING_INTERVAL_MS
    assert read_capture(take)["rtf"] == {"min": r, "mean": r, "max": r}


@NEEDS_CONTRACT
@pytest.mark.parametrize("float32_step", [False, True], ids=["double-step", "single-step"])
def test_capture_json_s_sim_s_is_the_total_the_rtf_mean_divides_not_the_raw_elapsed_difference(tmp_path, float32_step):
    """capture.json's sim_s is spec 2.2's total simulation time, the one the RTF's mean divides by the total wall time: the
    sum of the per-step advances the RTF counts, in seconds. On a server that keeps its step in single precision the
    snapshots' raw elapsed difference reads longer than that total (each step a little over the generated one); the raw
    times stay in steps.jsonl, and sim_s over the total wall time is the recorded mean."""
    rc, carla, take = run_take(tmp_path, float32_step=float32_step)
    assert rc == 0
    steps = read_steps(take)
    el, cur = [s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps]
    total_ns = sum(sendpolicy.advances_ns(el, policy().step_ns))
    assert total_ns == (len(steps) - 1) * C.CARLA_STEP_MS * MS == cur[-1]           # every advance one step, every wall one
    raw_ns = sendpolicy.sim_advance_ns(el[0], el[-1])
    assert raw_ns > total_ns if float32_step else raw_ns == total_ns                 # the premise: only a float32 step reads long
    cap = read_capture(take)
    assert cap["sim_s"] == total_ns / 1e9
    assert cap["sim_s"] / (cur[-1] / 1e9) == cap["rtf"]["mean"] == 1.0


@NEEDS_CONTRACT
def test_the_wait_counts_from_the_previous_step_not_from_the_values(tmp_path):
    """Each tick takes 10 ms of wall time: steps are still exactly one interval apart, not 10 ms more."""
    rc, carla, take = run_take(tmp_path, tick_ns=lambda n: 10 * MS)
    cur = [s["t_cur_ns"] for s in read_steps(take)]
    assert all(b - a == policy().interval_ns for a, b in zip(cur, cur[1:]))
    vals = [s["t_vals_ns"] for s in read_steps(take)]
    assert all(v < c for v, c in zip(vals[1:], cur[1:]))


@NEEDS_CONTRACT
def test_the_next_tick_comes_only_after_the_step_is_current(tmp_path):
    def tick(n):
        return 10 * MS
    rc, carla, take = run_take(tmp_path, tick_ns=tick)
    steps = read_steps(take)
    first = capture.SETTLE_TICKS                                            # the ticks before step 0
    t0 = carla.sim.tick_clock[first] + tick(first + 1)
    for k, s in enumerate(steps[:-1]):
        assert carla.sim.tick_clock[first + k + 1] >= t0 + s["t_cur_ns"], k


@NEEDS_CONTRACT
def test_no_catch_up_after_a_slow_step(tmp_path):
    slow = capture.SETTLE_TICKS + 30
    rc, carla, take = run_take(tmp_path, tick_ns=lambda n: 120 * MS if n == slow else 0)
    steps = read_steps(take)
    k = slow - capture.SETTLE_TICKS - 1                                     # the slow tick's step
    assert steps[k]["t_cur_ns"] - steps[k - 1]["t_cur_ns"] == 120 * MS
    assert steps[k + 1]["t_cur_ns"] - steps[k]["t_cur_ns"] == policy().interval_ns
    assert read_capture(take)["gaps"] == [k]


@NEEDS_CONTRACT
@pytest.mark.parametrize("float32_step", [False, True], ids=["double-step", "single-step"])
def test_a_slower_than_real_time_simulator_leaves_a_gap_after_every_step(tmp_path, float32_step):
    rc, carla, take = run_take(tmp_path, tick_ns=lambda n: 100 * MS, float32_step=float32_step)
    cap = read_capture(take)
    assert cap["gaps"] == list(range(1, cap["steps"])) and cap["rtf"]["max"] <= 0.5 + 1e-9


@NEEDS_CONTRACT
@pytest.mark.parametrize("float32_step", [False, True], ids=["double-step", "single-step"])
def test_a_skipped_frame_is_logged_as_a_skip_and_a_gap_with_an_rtf_of_two(tmp_path, float32_step):
    jump = capture.SETTLE_TICKS + 20
    rc, carla, take = run_take(tmp_path, frame_jump_at=jump, float32_step=float32_step)
    cap = read_capture(take)
    k = jump - capture.SETTLE_TICKS - 1
    assert cap["skipped_frames"] == [k] and k in cap["gaps"] and cap["rtf"]["max"] == pytest.approx(2.0)


@NEEDS_CONTRACT
def test_the_script_holds_every_command_and_the_segments_run_once_in_order(tmp_path):
    rc, carla, take = run_take(tmp_path)
    steps = read_steps(take)
    script = [json.loads(x) for x in (take / "script.jsonl").read_text(encoding="ascii").splitlines()]
    assert all(set(c) == {"i", "seg", "cmd", "args"} and c["cmd"] == "control" for c in script)
    assert script[0]["i"] == 0 and script[0]["seg"] == "start"
    drive_steps = [s["i"] for s in steps if s["seg"] == "route drive"]
    assert [c["i"] for c in script if c["seg"] == "route drive"] == drive_steps    # one control per route-drive step
    for c in script:
        assert steps[c["i"]]["seg"] == c["seg"]
    cap = read_capture(take)
    assert [s[0] for s in cap["segments"]] == list(drive.SEGMENTS)
    for name, a, b in cap["segments"]:
        assert all(steps[i]["seg"] == name and steps[i]["gear"] == drive.SEGMENT_GEAR[name] for i in range(a, b + 1))
    assert all(s["reverse"] == (s["gear"] == -1) for s in steps)


@NEEDS_CONTRACT
def test_the_ego_starts_on_the_route_at_the_longest_straight_and_the_drive_is_recorded(tmp_path):
    """The spawn point with the longest straight lane ahead (the fake's second; its fourth is as long and comes later), the
    ego placed on the route's first point, the route and every drive value in capture.json."""
    rc, carla, take = run_take(tmp_path)
    cap = read_capture(take)
    assert rc == 0 and cap["spawn_index"] == 1
    m = fake.Map("Carla/Maps/Town01")
    wp = m.get_waypoint(m.get_spawn_points()[1].location).transform
    route = cap["drive"]["route"]
    assert route["start"] == [wp.location.x, wp.location.y, wp.rotation.yaw]
    assert carla.sim.spawns[0] == ("vehicle.toyota.prius", wp.location.x, wp.location.y, fake.FAKE_SPAWN_Z, wp.rotation.yaw)
    assert route["points"] == int(short_route().length_m) and [t[1] for t in route["turns"]][:3] == ["left", "left", "straight"]
    assert 0 < route["planned_rate_max_deg_s"] <= short_route().steer_rate_deg_s
    assert cap["drive"]["values"] == json.loads(json.dumps(dataclasses.asdict(short_drive())))
    assert cap["drive"]["route_values"] == json.loads(json.dumps(dataclasses.asdict(short_route())))


@NEEDS_CONTRACT
def test_the_seed_names_the_take_and_nothing_in_the_drive_is_random(tmp_path):
    rc7, _c7, t7 = run_take(tmp_path / "a", seed=7, name="20261017-carla-7")
    rc11, _c11, t11 = run_take(tmp_path / "b", seed=11, name="20261017-carla-11")
    assert rc7 == rc11 == 0 and read_capture(t11)["seed"] == 11
    assert (t7 / "steps.jsonl").read_bytes() == (t11 / "steps.jsonl").read_bytes()
    assert (t7 / "script.jsonl").read_bytes() == (t11 / "script.jsonl").read_bytes()


@NEEDS_CONTRACT
def test_the_ego_s_wheelbase_is_the_axle_midpoints_distance_in_mm(tmp_path):
    rc, carla, take = run_take(tmp_path)
    ego = read_capture(take)["ego"]
    assert ego["wheelbase_mm"] == fake.FAKE_WHEELBASE_MM and ego["front_max_steer_deg"] == [70.0, 70.0]
    assert [w["max_steer_angle"] for w in ego["wheels"]] == [70.0, 70.0, 0.0, 0.0]


@NEEDS_CONTRACT
def test_with_nothing_pending_capture_json_says_so_and_stderr_is_quiet(tmp_path, capsys, monkeypatch):
    rc, carla, take = run_take(tmp_path / "a")
    assert read_capture(take)["pending_probe"] == {}
    assert "PENDING-PROBE" not in capsys.readouterr().err
    monkeypatch.setattr(capture.drive, "DRIVE_PENDING_PROBE", True)        # the drive's values reopened
    rc, carla, take = run_take(tmp_path / "b")
    pend = read_capture(take)["pending_probe"]
    assert set(pend) == {"drive_values"} and pend["drive_values"]["drive"] == json.loads(json.dumps(dataclasses.asdict(short_drive())))
    assert "PENDING-PROBE" in capsys.readouterr().err


@NEEDS_CONTRACT
def test_frames_are_reduced_on_the_stride_matched_by_frame_and_the_raw_buffer_never_written(tmp_path):
    rc, carla, take = run_take(tmp_path, frames="on", image_lag=2)
    cap = read_capture(take)
    steps = read_steps(take)
    d = tmp_path / "frames" / "20261017-carla-7"
    doc = frameset.read_set(d)
    stride = cap["camera"]["stride_steps"]
    assert stride == capture.STRIDE_STEPS == doc["stride_steps"]
    listed = [f["i"] for f in doc["frames"]]
    assert listed and all(i % stride == 0 for i in listed)
    assert set(listed) | set(cap["camera"]["frames_missing"]) == {s["i"] for s in steps if s["i"] % stride == 0}
    for f in doc["frames"]:
        assert f["frame"] == steps[f["i"]]["frame"]
        want = frameset.reduce_bgra(fake.pattern_bgra(f["frame"], 320, 256))
        assert frameset.png_pixels((d / f["file"]).read_bytes()) == want
    assert doc["take_sha256"] == hashlib.sha256((take / "take.sha256").read_bytes()).hexdigest()
    raw = fake.pattern_bgra(steps[listed[0]]["frame"], 320, 256)
    probe = raw[160 * 1280 + 400:160 * 1280 + 464]
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert probe not in p.read_bytes(), p
    assert cap["camera"]["image_size_x"] == 320 and cap["camera"]["image_size_y"] == 256
    assert cap["camera"]["mount"] == {"x": 1.5, "y": 0.0, "z": 1.6} and cap["camera"]["type"] == "sensor.camera.rgb"


@NEEDS_CONTRACT
def test_an_image_that_never_arrives_is_skipped_and_logged(tmp_path):
    first = capture.SETTLE_TICKS
    # the fake's frame numbers: 100 at the start, one per tick; step i's frame is 100 + first + 1 + i
    missing_i = capture.STRIDE_STEPS
    rc, carla, take = run_take(tmp_path, frames="on", drop_images={100 + first + 1 + missing_i})
    cap = read_capture(take)
    assert missing_i in cap["camera"]["frames_missing"]
    assert not (tmp_path / "frames" / "20261017-carla-7" / ("frame-%06d.png" % missing_i)).exists()


@NEEDS_CONTRACT
def test_the_capture_asks_for_at_most_max_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "MAX_FRAMES", 2)
    rc, carla, take = run_take(tmp_path, frames="on")
    doc = json.loads((tmp_path / "frames" / "20261017-carla-7" / "frames.json").read_text(encoding="utf-8"))
    assert rc == 0 and [f["i"] for f in doc["frames"]] == [0, 20] and read_capture(take)["camera"]["max_frames"] == 2


@NEEDS_CONTRACT
def test_an_image_wanted_for_the_predicted_frame_moves_to_the_snapshot_s_when_a_frame_was_skipped(tmp_path):
    """The image wanted for a strided step is first the predicted next frame's; when the snapshot's frame is another (a skipped
    frame), the want moves to the snapshot's, the frame the step's readings carry, and that image is the one written
    (verify#9)."""
    jump = capture.SETTLE_TICKS + capture.STRIDE_STEPS + 1            # the tick of step STRIDE_STEPS: its frame number jumps by 2
    rc, carla, take = run_take(tmp_path, frames="on", image_lag=2, frame_jump_at=jump)
    steps = read_steps(take)
    k = capture.STRIDE_STEPS
    assert steps[k]["frame"] - steps[k - 1]["frame"] == 2             # the premise: the predicted frame was not the step's
    d = tmp_path / "frames" / "20261017-carla-7"
    entry = next(f for f in frameset.read_set(d)["frames"] if f["i"] == k)
    assert entry["frame"] == steps[k]["frame"] and k not in read_capture(take)["camera"]["frames_missing"]
    assert frameset.png_pixels((d / entry["file"]).read_bytes()) == frameset.reduce_bgra(fake.pattern_bgra(entry["frame"], 320, 256))


@NEEDS_CONTRACT
def test_images_still_on_their_way_after_the_last_step_are_waited_for(tmp_path):
    """A camera's thread delivers on its own: images of the strided steps can still be on their way when the last step is
    read. Here none arrives on a tick (a lag no take reaches), so each is missing without the wait; with the fake delivering
    every pending image when the client sleeps with no tick since its previous sleep -- the wait after the last step -- none
    is missing (verify#16)."""
    rc, carla, take = run_take(tmp_path / "a", frames="on", image_lag=10 ** 6)
    strided = [s["i"] for s in read_steps(take) if s["i"] % capture.STRIDE_STEPS == 0]
    assert len(strided) > 1 and read_capture(take)["camera"]["frames_missing"] == strided          # the premise: nothing arrives
    rc, carla, take = run_take(tmp_path / "b", frames="on", image_lag=10 ** 6, deliver_on_idle_sleep=True)
    cap = read_capture(take)
    assert rc == 0 and cap["camera"]["frames_missing"] == [] and cap["camera"]["frames_written"] == len(strided)
    assert [f["i"] for f in frameset.read_set(tmp_path / "b" / "frames" / "20261017-carla-7")["frames"]] == strided


@NEEDS_CONTRACT
def test_a_ctrl_c_ends_the_take_with_130_records_it_and_cleans_up_in_order(tmp_path):
    """Spec 4 item 5: also on Ctrl-C the cleanup runs in section 1's order, capture.json says what happened, take.sha256 and
    (with frames on) frames.json are written, and the exit code is 130 (verify#10)."""
    hit = capture.SETTLE_TICKS + 30
    rc, carla, take = run_take(tmp_path, frames="on", interrupt_at_tick=hit)
    cap = read_capture(take)
    assert rc == 130 and cap["completed"] is False and cap["cleanup"] == "ok"
    assert any(e.startswith("KeyboardInterrupt") for e in cap["errors"]) and cap["steps"] == len(read_steps(take)) == hit - capture.SETTLE_TICKS - 1
    calls = carla.sim.calls
    k = calls.index("stop:sensor.camera.rgb")
    assert [c for c in calls[k:] if not c.startswith("listen")] == [
        "stop:sensor.camera.rgb", "destroy:sensor.camera.rgb", "stop:sensor.other.collision", "destroy:sensor.other.collision",
        "tick", "destroy:vehicle.toyota.prius", "tick", "apply_settings:False"]
    assert (take / "take.sha256").is_file() and frameset.read_set(tmp_path / "frames" / "20261017-carla-7")["simulated"] is True


@NEEDS_CONTRACT
def test_a_cleanup_that_fails_is_recorded_and_fails_the_take(tmp_path):
    """A take that completed but whose cleanup raised (here a sensor that would not stop) exits 1, and capture.json says what
    raised instead of 'ok' (verify#11)."""
    rc, carla, take = run_take(tmp_path, frames="on", stop_raises=True)
    cap = read_capture(take)
    assert cap["completed"] is True and cap["errors"] == []
    assert rc == 1 and cap["cleanup"].startswith("RuntimeError") and "would not stop" in cap["cleanup"]
    assert (take / "take.sha256").is_file()


@NEEDS_CONTRACT
def test_a_server_in_town01_opt_is_in_another_map_and_town01_is_loaded(tmp_path):
    """Town01 is matched as the map's whole last path component: Town01_Opt is not it (verify#16)."""
    rc, carla, _take = run_take(tmp_path, map_name="Carla/Maps/Town01_Opt")
    assert rc == 0 and carla.sim.loads == ["Town01"]


@NEEDS_CONTRACT
@pytest.mark.parametrize("bad", ["20261017-carla-8", "20261017-sigsim-7", "2026101-carla-7", "20261317-carla-7",
                                 "20261017-carla-7X", "20261017-carla-7-x", "20261017-carla-7abcdefghi",
                                 "20261017-CARLA-7", "20261017-carla-7_", "20261017-carla-07"])
def test_a_take_name_that_is_not_date_carla_seed_suffix_is_refused_before_anything(tmp_path, bad):
    rc, carla, take = run_take(tmp_path, name=bad)
    assert rc == 2 and carla.sim.calls == [] and not (tmp_path / "takes").exists()


@NEEDS_CONTRACT
def test_a_suffixed_name_is_taken(tmp_path):
    rc, carla, take = run_take(tmp_path, name="20261017-carla-7b")
    assert rc == 0 and read_capture(take)["name"] == "20261017-carla-7b"


@NEEDS_CONTRACT
@pytest.mark.parametrize("fw", [lambda: (1, ["fwcheck: FAIL (windows-client): P2: CARLA UE4"]),
                                lambda: (2, ["fwcheck: the firewall read failed (1): denied"])], ids=["fail", "read-failed"])
def test_on_windows_a_failing_fwcheck_refuses_before_connecting(tmp_path, fw):
    """A predicate that fails (exit 1) and a read that failed (exit 2, which says nothing about the rules) both refuse."""
    rc, carla, take = run_take(tmp_path, windows=True, fw=fw)
    assert rc == 2 and carla.sim.calls == [] and not (tmp_path / "takes").exists()


@NEEDS_CONTRACT
def test_on_windows_the_take_s_own_fwcheck_applies_p4(tmp_path, monkeypatch):
    """The take runs no Traffic Manager, yet its gate is fwcheck --for windows-client whole: P4 is not waived."""
    seen = []

    def spy(for_, runner=None, tm=True, interpreters=None):
        seen.append((for_, tm))
        return 0, ["fwcheck: PASS (%s)" % for_]
    monkeypatch.setattr(capture.fwcheck, "run", spy)
    rc, carla, take = run_take(tmp_path, windows=True)
    assert rc == 0 and seen == [("windows-client", True)]


def test_the_capture_s_fwcheck_command_forwards_no_tm(monkeypatch):
    seen = []
    monkeypatch.setattr(capture.fwcheck, "main", lambda argv, windows=None: seen.append(list(argv)) or 0)
    assert capture.main(["fwcheck", "--for", "wsl"], windows=True) == 0
    assert capture.main(["fwcheck", "--for", "windows-client", "--no-tm"], windows=True) == 0
    assert seen == [["--for", "wsl"], ["--for", "windows-client", "--no-tm"]]


@NEEDS_CONTRACT
def test_on_windows_a_passing_fwcheck_is_recorded(tmp_path):
    rc, carla, take = run_take(tmp_path, windows=True, fw=lambda: (0, ["fwcheck: PASS (windows-client)"]))
    assert rc == 0 and read_capture(take)["fwcheck"] == "fwcheck: PASS (windows-client)"
    assert carla.sim.calls[0] == "connect:127.0.0.1:2000"


@NEEDS_CONTRACT
@pytest.mark.parametrize("host", ["192.0.2.10", "localhost", "0.0.0.0"])
def test_on_windows_any_host_but_127_0_0_1_is_refused_before_connecting(tmp_path, host):
    rc, carla, take = run_take(tmp_path, windows=True, host=host, fw=lambda: (0, ["fwcheck: PASS (windows-client)"]))
    assert rc == 2 and carla.sim.calls == []


@NEEDS_CONTRACT
def test_an_existing_take_or_set_or_one_inside_a_work_tree_is_refused_before_connecting(tmp_path):
    rts = roots(tmp_path)
    (rts.takes / "20261017-carla-7").mkdir(parents=True)
    rc, carla, _t = run_take(tmp_path, rts=rts)
    assert rc == 2 and carla.sim.calls == []
    (rts.frames / "20261017-carla-8").mkdir(parents=True)
    rc, carla, _t = run_take(tmp_path, rts=rts, name="20261017-carla-8", seed=8, frames="on")
    assert rc == 2 and carla.sim.calls == []
    tree = tmp_path / "wt"
    (tree / ".git").mkdir(parents=True)
    rc, carla, _t = run_take(tmp_path, rts=capture.Roots(takes=tree / "takes", frames=tmp_path / "f2"))
    assert rc == 2 and carla.sim.calls == []
    rc, carla, _t = run_take(tmp_path, rts=capture.Roots(takes=tmp_path / "t3", frames=tree / "frames"), frames="on")
    assert rc == 2 and carla.sim.calls == []


def test_no_generated_contract_is_refused_before_connecting(tmp_path, monkeypatch):
    carla = fake.make()
    def nope():
        raise vf.ContractError("no generated contract at /nowhere")
    monkeypatch.setattr(capture, "load_contract", nope)
    rc = capture.main(["take", "--name", "20261017-carla-7", "--seed", "7"], carla=carla, roots=roots(tmp_path), windows=False,
                      clock_ns=carla.clock, sleep=carla.clock.sleep, drive_values=short_drive())
    assert rc == 2 and carla.sim.calls == []


def test_capture_imports_without_the_carla_module():
    """`carla` is imported inside main only (the tests import carla_capture.py without it; CI has no carla wheel)."""
    src = (CARLA_DIR / "carla_capture.py").read_text(encoding="utf-8")
    assert not re.search(r"^(import carla|from carla)\b", src, re.M)
    assert capture is not None and "carla" not in vars(capture)


def test_no_module_here_shares_a_name_with_a_module_ci_type_checks_beside_it():
    """CI's mypy checks sdv/carla together with scripts/ci, scripts/aws, scripts/twin, tests, sdv/connector, sdv/cloud
    and sdv/ota, and stops on two top-level modules of one name. A package marker here would instead put sdv/ on mypy's
    path and make sdv/stack, sdv/inject and sdv/arm64 empty namespace packages for the tests that import their modules.
    So every module here has a name of its own and there is no __init__.py (scripts/aws has a capture.py, hence
    carla_capture.py)."""
    assert not (CARLA_DIR / "__init__.py").exists()
    mine = {p.stem for p in CARLA_DIR.glob("*.py")}
    others = set()
    for d in ("scripts/ci", "scripts/aws", "scripts/twin", "tests", "sdv/connector", "sdv/cloud", "sdv/ota"):
        others |= {p.stem for p in (REPO / d).rglob("*.py")}
    assert {"carla_capture", "encode", "sendpolicy", "fwcheck", "frameset", "drive", "worldtie"} <= mine and not (mine & others), mine & others


def test_the_take_s_step_keys_and_files_are_one_list_in_the_capture_and_the_encoder():
    assert capture.STEP_KEYS == encode.STEP_KEYS and capture.TAKE_FILES == encode.TAKE_FILES


def test_capture_uses_the_standard_library_and_its_own_package_only():
    """What the Windows client imports (E:\\CARLA\\venv312 holds the carla wheel and pip only): the standard library, this
    directory's modules, and the two standard-library-only modules it shares with the slice (vssframe, carla_iso)."""
    allowed = set(sys.stdlib_module_names) | {"__future__", "sendpolicy", "fwcheck", "frameset", "drive", "worldtie", "vssframe",
                                              "carla_iso"}
    for path in [CARLA_DIR / n for n in ("carla_capture.py", "sendpolicy.py", "fwcheck.py", "frameset.py", "drive.py", "worldtie.py")] + \
            [SIM_DIR / "carla_iso.py", FRAME_DIR / "vssframe.py"]:
        mods = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        assert mods and mods <= allowed, (path.name, mods - allowed)


# =================================================================================================================
# The live sender's hook (SDV plan Phase 7 WP3c, spec-2 section 6): one optional per-step callback, none by default
# =================================================================================================================

def _hook_take(tmp_path, sub, **hook):
    """carla_capture.take on a fresh fake simulator, called as sdv/feeder/live.py calls it; hook: the on_current keyword,
    or none at all. Returns (exit code, fake module, take dir)."""
    capture._LOADS.clear()
    carla = fake.make()
    rts = capture.Roots(takes=tmp_path / sub / "takes", frames=tmp_path / sub / "frames")
    name = "20261017-carla-7"
    rc = capture.take(name, 7, False, carla=carla, rts=rts, host="127.0.0.1", contract=C, clock_ns=carla.clock,
                      sleep=carla.clock.sleep, fwcheck_line="not run: not Windows", drv=short_drive(), rv=short_route(), **hook)
    return rc, carla, rts.takes / name


@NEEDS_CONTRACT
def test_a_take_with_no_hook_is_byte_for_byte_the_take_without_the_parameter_or_with_a_hook_that_returns_nothing(tmp_path):
    """None is the default, and a take with none (passed or not) or with a hook that only looks is one take, byte for byte:
    WP1's take tests above pin that take."""
    looked = []
    takes = [_hook_take(tmp_path, "omitted"), _hook_take(tmp_path, "none", on_current=None),
             _hook_take(tmp_path, "looks", on_current=lambda row, t_cur, ego: looked.append(row["i"]))]
    assert [rc for rc, _c, _t in takes] == [0, 0, 0] and looked
    for name in capture.TAKE_FILES + ("take.sha256",):
        first = (takes[0][2] / name).read_bytes()
        assert all((t / name).read_bytes() == first for _rc, _c, t in takes[1:]), name


@NEEDS_CONTRACT
def test_the_hook_sees_each_step_once_as_written_when_it_becomes_current_and_a_true_return_ends_the_take_completed(tmp_path):
    seen = []
    clock = []

    def hook(row, t_cur, ego):
        seen.append((row, t_cur, dict(ego)))
        clock.append(carla_box[0].clock())
        return row["i"] == 20
    carla_box = []
    capture._LOADS.clear()
    carla_box.append(fake.make())
    rts = capture.Roots(takes=tmp_path / "takes", frames=tmp_path / "frames")
    rc = capture.take("20261017-carla-7", 7, False, carla=carla_box[0], rts=rts, host="127.0.0.1", contract=C,
                      clock_ns=carla_box[0].clock, sleep=carla_box[0].clock.sleep, fwcheck_line="not run: not Windows",
                      drv=short_drive(), rv=short_route(), on_current=hook)
    take = rts.takes / "20261017-carla-7"
    steps, cap = read_steps(take), read_capture(take)
    assert rc == 0 and cap["completed"] is True and cap["cleanup"] == "ok" and not cap["errors"]
    assert [row for row, _t, _e in seen] == steps and len(steps) == 21          # each step once, in order, as written; 20 ended it
    assert [t for _r, t, _e in seen] == clock                                   # called at the moment the step became current
    assert [t - seen[0][1] for _r, t, _e in seen] == [s["t_cur_ns"] for s in steps]
    assert all(e == cap["ego"] for _r, _t, e in seen)
    assert cap["steps"] == 21 and [s[0] for s in cap["segments"]] == ["start", "route drive"]


@NEEDS_CONTRACT
@pytest.mark.parametrize("what", ["row", "ego", "both"])
def test_a_hook_that_changes_what_it_is_given_changes_nothing_of_the_take(tmp_path, what):
    """The hook gets copies of the step's row and of the ego's record (the docstring says so): whatever it does to them, the
    take's files are byte for byte those of a take with no hook. Top-level keys only: the copies are shallow."""
    def vandal(row, t_cur, ego):
        if what in ("row", "both"):
            row["i"], row["seg"], row["v"] = -1, "vandal", [99.0, 0.0, 0.0]
            row["extra"] = True
        if what in ("ego", "both"):
            ego["wheelbase_mm"] = 1
            ego["front_max_steer_deg"] = [0.0]
            ego["extra"] = True
        return None
    plain, vandalised = _hook_take(tmp_path, "plain"), _hook_take(tmp_path, "vandal", on_current=vandal)
    assert plain[0] == vandalised[0] == 0
    for name in capture.TAKE_FILES + ("take.sha256",):
        assert (vandalised[2] / name).read_bytes() == (plain[2] / name).read_bytes(), name


# =================================================================================================================
# encode.py
# =================================================================================================================

class _Sig:
    def __init__(self, name, start, length, scale, lo, hi, unit):
        self.name, self.start, self.length, self.scale, self.minimum, self.maximum, self.unit = name, start, length, scale, lo, hi, unit
        self.offset, self.is_signed = 0, True


class _Msg:
    def __init__(self, name, frame_id, cycle):
        self.name, self.frame_id, self.cycle_time, self.signals, self.length = name, frame_id, cycle, [], 8

    def get_signal_by_name(self, name):
        return next(s for s in self.signals if s.name == name)

    def encode(self, values):
        out = bytearray(8)
        for s in self.signals:
            v = values[s.name]
            if not s.minimum <= v <= s.maximum:
                raise ValueError("fake cantools: %s out of range" % s.name)
            raw = int(round(v / s.scale)) & ((1 << s.length) - 1)
            out[s.start // 8:s.start // 8 + s.length // 8] = raw.to_bytes(s.length // 8, "little")
        return bytes(out)

    def decode(self, data):
        out = {}
        for s in self.signals:
            raw = int.from_bytes(data[s.start // 8:s.start // 8 + s.length // 8], "little", signed=True)
            out[s.name] = raw * s.scale if s.scale != 1 else raw
        return out


class FakeDb:
    """slice.dbc read with a regular expression: the stand-in for cantools' database in this process (the sim-venv tests
    run the real one)."""

    def __init__(self, path=SLICE_DBC):
        self.messages = []
        text = path.read_text(encoding="utf-8")
        cycles = {int(m.group(1)): int(m.group(2)) for m in re.finditer(r'BA_ "GenMsgCycleTime" BO_ (\d+) (\d+);', text)}
        for m in re.finditer(r"^BO_ (\d+) (\w+): 8 \w+\n((?: SG_ .*\n)+)", text, re.M):
            msg = _Msg(m.group(2), int(m.group(1)), cycles.get(int(m.group(1))))
            for s in re.finditer(r' SG_ (\w+) : (\d+)\|(\d+)@1- \(([\d.]+),0\) \[([-\d.]+)\|([-\d.]+)\] "([^"]*)"', m.group(3)):
                scale = float(s.group(4))
                msg.signals.append(_Sig(s.group(1), int(s.group(2)), int(s.group(3)), scale if scale != 1.0 else 1,
                                        float(s.group(5)), float(s.group(6)), s.group(7) or None))
            self.messages.append(msg)

    def get_message_by_name(self, name):
        return next(m for m in self.messages if m.name == name)

    def get_message_by_frame_id(self, fid):
        return next(m for m in self.messages if m.frame_id == fid)

    def decode_message(self, fid, data, decode_choices=False):
        return self.get_message_by_frame_id(fid).decode(data)


def fake_read_log(path):
    out = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        m = re.fullmatch(r"\((\d{10})\.(\d{6})\) (\w+) ([0-9A-F]{3})#([0-9A-F]*)", line)
        if m is None:
            raise ValueError("fake python-can: unreadable line %r" % line)
        out.append((int(m.group(1)) + int(m.group(2)) / 1e6, int(m.group(4), 16), bytes.fromhex(m.group(5)), m.group(3)))
    return out


@pytest.fixture
def stand_ins(monkeypatch):
    """cantools' database and python-can's reader replaced by exact stand-ins, and HOME and the encoder's view of the
    repository moved into tmp_path's reach by the tests that need it."""
    monkeypatch.setattr(encode, "load_dbc", lambda contract, path=None: FakeDb())
    monkeypatch.setattr(encode, "read_log", fake_read_log)
    return monkeypatch


def make_take(tmp_path, name="20261017-carla-7", seed=7, **faults):
    rc, carla, take = run_take(tmp_path / "pc", name=name, seed=seed, **faults)
    assert take.is_dir()
    return rc, take


def record(tmp_path, take, name="20261017-carla-7", contract=None):
    out = tmp_path / "rec" / name
    return encode.record(take, out, name, contract=contract if contract is not None else synthetic_contract()), out


@NEEDS_CONTRACT
def test_a_take_records_and_verifies_with_its_files_in_order_and_the_manifest_line_last(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    assert rc == 0
    written = []
    real_write = encode._write_bytes
    stand_ins.setattr(encode, "_write_bytes", lambda p, data: written.append(p.name) or real_write(p, data))
    res, out = record(tmp_path, take)
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["ok_terms"]
    assert written == ["carla.log", "carla.log.sha256", "steps.jsonl", "summary.json", "manifest-line.json"]
    assert sorted(p.name for p in out.iterdir()) == sorted(written)
    assert (out / "steps.jsonl").read_bytes() == (take / "steps.jsonl").read_bytes()
    sha = hashlib.sha256((out / "carla.log").read_bytes()).hexdigest()
    assert (out / "carla.log.sha256").read_text(encoding="ascii") == "%s  carla.log\n" % sha
    assert set(res["verify"]["ok_terms"]) == set(encode.OK_TERMS) and all(res["verify"]["ok_terms"].values())


@NEEDS_CONTRACT
def test_the_log_is_the_send_schedule_of_the_take_in_candump_form(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    steps = read_steps(take)
    p = policy()
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], p)
    lines = (out / "carla.log").read_text(encoding="ascii").splitlines()
    assert len(lines) == len(sched)
    for line, (t, msg, _i) in zip(lines, sched):
        assert line.startswith("(%010d.%06d) vcan0 " % (t // 1000, (t % 1000) * 1000))
        assert line.split(" ")[2].split("#")[0] == "%03X" % FakeDb().get_message_by_name(msg).frame_id


@NEEDS_CONTRACT
def test_the_manifest_line_is_the_specified_shape_with_exactly_five_params(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    text = (out / "manifest-line.json").read_text(encoding="ascii")
    line = json.loads(text)
    assert text == json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n"
    c = synthetic_contract()
    pid = c.LIVE_DEFAULT_PROFILE["carla"]
    l_mm = {r["id"]: r for r in c.PROFILES}[pid]["l_mm"]
    assert line == {
        "name": "20261017-carla-7", "profile_id": pid,
        "recording": {"format": "candump-log", "path": str(out / "carla.log"),
                      "sha256": hashlib.sha256((out / "carla.log").read_bytes()).hexdigest()},
        "source": {"generator": "carla",
                   "params": {"catalog_digest": "0x%08X" % C.CATALOG_DIGEST, "dbc_sha256": hashlib.sha256(SLICE_DBC.read_bytes()).hexdigest(),
                              "seed": 7, "town": "Town01", "version": "0.9.16"},
                   "rtf": read_capture(take)["rtf"],
                   "vehicle": {"name": "vehicle.toyota.prius", "wheelbase_mm": l_mm}}}
    assert len(line["source"]["params"]) == 5 and set(line["source"]["rtf"]) == {"min", "mean", "max"}
    assert 0 < line["source"]["rtf"]["min"] <= line["source"]["rtf"]["mean"] <= line["source"]["rtf"]["max"] <= 1


def test_a_recording_under_the_default_root_keeps_the_home_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = tmp_path / "sdv-recordings" / "20261017-carla-7"
    assert encode.log_path_shown(out) == "~/sdv-recordings/20261017-carla-7/carla.log"
    assert encode.log_path_shown(tmp_path / "elsewhere" / "x") is None


@NEEDS_CONTRACT
def test_the_summary_keeps_sigsim_s_top_level_keys_and_the_trip_the_stack_reads(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert set(summ) == {"dir", "name", "recorded", "trip", "verify"}
    trip = summ["trip"]
    for key in ("segments", "messages", "periods_ms", "duration_ms", "seed", "params", "profile_id", "wheelbase_mm", "gear_changes",
                "rtf", "gaps", "timestamps", "take", "encoder_sha256"):
        assert key in trip, key
    assert trip["timestamps"] == "feeder send schedule from zero" and trip["gaps"] == []
    assert [s[0] for s in trip["segments"]] == list(drive.SEGMENTS)
    assert trip["params"] == json.loads((out / "manifest-line.json").read_text(encoding="ascii"))["source"]["params"]
    assert trip["take"] == {"name": "20261017-carla-7", "take_sha256": hashlib.sha256((take / "take.sha256").read_bytes()).hexdigest()}
    assert set(trip["encoder_sha256"]) == {"sdv/carla/encode.py", "sdv/carla/sendpolicy.py", "sdv/carla/drive.py",
                                           "sdv/carla/worldtie.py", "sdv/sim/carla_iso.py"}
    for rel, sha in trip["encoder_sha256"].items():
        assert sha == hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    assert [g[1:] for g in trip["gear_changes"]] == [[0, 1], [1, 0], [0, -1]]
    steps = read_steps(take)
    changed = [k for k in range(1, len(steps)) if steps[k]["gear"] != steps[k - 1]["gear"]]
    # the log's clock is the moment a step became current, not the moment its readings were complete (verify#15)
    assert [g[0] for g in trip["gear_changes"]] == [steps[k]["t_cur_ns"] // MS for k in changed]
    assert any(steps[k]["t_vals_ns"] // MS != steps[k]["t_cur_ns"] // MS for k in changed)          # the premise: the clocks differ
    assert trip["pending_probe"] == {}
    for key in ("ok", "ok_terms", "judge", "cantools_decode", "python_can_reader", "regenerated_identical", "log", "log_bytes",
                "log_sha256"):
        assert key in summ["verify"], key
    assert "rule26_above_tol" in summ["verify"]["judge"]
    hb = [s for s in trip["segments"] if s[0] == "hard brake"][0]
    assert replaycheck.hard_brake_segment(trip) == (hb[1], hb[2])


@NEEDS_CONTRACT
def test_record_refuses_a_take_whose_sha256_file_does_not_hold(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    p = take / "steps.jsonl"
    p.write_bytes(p.read_bytes().replace(b'"i":3,', b'"i":3 ,', 1))
    with pytest.raises(encode.EncodeError, match="take.sha256"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_refuses_a_take_whose_step_0_is_not_current_at_0(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    _retake(take, edit_steps=lambda steps: [s.update(t_cur_ns=s["t_cur_ns"] + 5 * MS, t_vals_ns=s["t_vals_ns"] + 5 * MS)
                                            for s in steps])
    with pytest.raises(encode.EncodeError, match="step 0"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_the_trip_duration_is_the_logs_last_frame(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    m = re.match(r"\((\d{10})\.(\d{6})\)", (out / "carla.log").read_text(encoding="ascii").splitlines()[-1])
    want = int(m.group(1)) * 1000 + int(m.group(2)) // 1000
    assert res["trip"]["duration_ms"] == want
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["trip"]["duration_ms"] == want


@NEEDS_CONTRACT
def test_verify_counts_a_timestamp_off_the_ms_grid_as_a_period_error(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    assert res["verify"]["ok"] is True
    log = out / "carla.log"
    lines = log.read_text(encoding="ascii").splitlines(True)
    k = next(k for k, ln in enumerate(lines) if ".000000)" in ln)
    lines[k] = lines[k].replace(".000000)", ".000500)", 1)
    log.write_text("".join(lines), encoding="ascii")
    assert encode.verify(out, synthetic_contract())["ok_terms"]["no_period_errors"] is False


@NEEDS_CONTRACT
def test_a_takes_pending_drive_values_reach_the_recording_and_stderr(tmp_path, stand_ins, capsys):
    rc, take = make_take(tmp_path)
    _retake(take, edit_capture=lambda c: c.update(pending_probe={"drive_values": drive.values_record(drive.DRIVE, drive.ROUTE)}))
    capsys.readouterr()
    res, out = record(tmp_path, take)
    assert "drive_values" in res["trip"]["pending_probe"] and "PENDING-PROBE" in capsys.readouterr().err


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
    (take / "take.sha256").write_text("".join("%s  %s\n" % (hashlib.sha256((take / n).read_bytes()).hexdigest(), n)
                                              for n in ("steps.jsonl", "script.jsonl", "capture.json")), encoding="ascii")


@NEEDS_CONTRACT
@pytest.mark.parametrize("faults,said", [
    ({"tick_ns": (lambda n: 80 * MS if n == 30 else 0)}, "gap"),
    ({"frame_jump_at": 25}, "skipped"),
])
def test_record_refuses_a_take_with_a_gap_or_a_skipped_frame(tmp_path, stand_ins, faults, said):
    rc, take = make_take(tmp_path, **faults)
    with pytest.raises(encode.EncodeError, match=said):
        record(tmp_path, take)


@NEEDS_CONTRACT
@pytest.mark.parametrize("what", ["rtf", "gaps", "completed", "version", "client", "format", "town", "blueprint", "wheelbase"])
def test_record_refuses_a_take_whose_capture_record_disqualifies_it(tmp_path, stand_ins, what):
    rc, take = make_take(tmp_path)
    edits = {"rtf": lambda c: c["rtf"].update(max=1.25), "gaps": lambda c: c.update(gaps=[5]),
             "completed": lambda c: c.update(completed=False), "version": lambda c: c.update(server_version="0.9.15"),
             "client": lambda c: c.update(client_version="0.9.15"), "format": lambda c: c.update(format=2),
             "town": lambda c: c.update(map="Carla/Maps/Town02"), "blueprint": lambda c: c.update(blueprint="vehicle.audi.tt"),
             "wheelbase": lambda c: c["ego"].update(wheelbase_mm=fake.FAKE_WHEELBASE_MM + 1)}
    _retake(take, edit_capture=edits[what])
    with pytest.raises(encode.EncodeError):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("key,value", [("synchronous_mode", False), ("fixed_delta_seconds", 0.02), ("substepping", False),
                                       ("max_substep_delta_time", 0.01), ("max_substeps", 10), ("max_substeps", 25.0),
                                       ("no_rendering_mode", None), ("world_settings", None)])
def test_record_refuses_a_take_whose_world_tie_is_not_the_capture_s(tmp_path, stand_ins, key, value):
    """The encoder does not take the take's world tie on trust (fable#6): capture.json's world_settings must be
    worldtie.py's tie of the generated step, every read-back key present (a missing key, None here, refused too)."""
    rc, take = make_take(tmp_path)

    def edit(c):
        if key == "world_settings":
            c.pop("world_settings")
        elif value is None:
            c["world_settings"].pop(key)
        else:
            c["world_settings"][key] = value
    _retake(take, edit_capture=edit)
    with pytest.raises(encode.EncodeError, match="world settings"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_verify_is_not_ok_when_the_log_s_sha256_file_does_not_hold(tmp_path, stand_ins):
    """carla.log.sha256 is what the stack and the injector check: a recording whose file is wrong is not ok, though the
    nine terms of spec 4 item 6 hold."""
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    assert res["verify"]["ok"] is True and res["verify"]["log_sha256_file_holds"] is True
    (out / "carla.log.sha256").write_text("%s  carla.log\n" % ("0" * 64), encoding="ascii")
    v = encode.verify(out, synthetic_contract())
    assert all(v["ok_terms"].values()) and v["log_sha256_file_holds"] is False and v["ok"] is False
    assert list(v["ok_terms"]) == list(encode.OK_TERMS) and len(encode.OK_TERMS) == 9


@NEEDS_CONTRACT
@pytest.mark.parametrize("early_ns", [10 * MS, 1], ids=["10ms-early", "1ns-early"])
@pytest.mark.parametrize("float32_step", [False, True], ids=["double-step", "single-step"])
def test_record_refuses_a_take_whose_rtf_above_one_is_in_its_steps(tmp_path, stand_ins, early_ns, float32_step):
    """One step made current early_ns sooner than one interval after the previous (10 ms: its RTF 1.25), on a server that
    keeps its step as a double or in single precision, and capture.json recording that same RTF: only the RTF rule
    refuses it. One nanosecond early is refused too: the tolerance the RTF allows is the step's quantization, on the
    simulation's side, never the wall clock's. Steps 10 to 19 move together and step 20 keeps its instant, so step 20's
    wall time is as much longer: the mean stays exactly 1 and only the max shows the early step."""
    rc, take = make_take(tmp_path, float32_step=float32_step)

    def faster(steps):
        for s in steps[10:20]:
            s["t_cur_ns"] -= early_ns
            s["t_vals_ns"] = min(s["t_vals_ns"], s["t_cur_ns"])
    _retake(take, edit_steps=faster)
    steps = read_steps(take)
    rtf = sendpolicy.rtf_summary([s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps], policy().step_ns)
    assert rtf["max"] == policy().step_ns / (policy().interval_ns - early_ns) > 1
    _retake(take, edit_capture=lambda c: c.update(rtf=rtf))
    with pytest.raises(encode.EncodeError, match="above 1"):
        record(tmp_path, take)


@NEEDS_CONTRACT
@pytest.mark.parametrize("where", ["first", "middle", "last"])
def test_record_refuses_a_take_with_one_step_alone_made_current_early(tmp_path, stand_ins, where):
    """One step made current 10 ms early and every other step on schedule, on a server that keeps its step in single
    precision: for the first and a middle step the next wall is 10 ms longer and the mean stays exactly 1, so only the
    max shows it; the first and the last step are each in the max the encoder recomputes."""
    rc, take = make_take(tmp_path, float32_step=True)
    steps = read_steps(take)
    k = {"first": 1, "middle": len(steps) // 2, "last": len(steps) - 1}[where]

    def early(st):
        st[k]["t_cur_ns"] -= 10 * MS
        st[k]["t_vals_ns"] = min(st[k]["t_vals_ns"], st[k]["t_cur_ns"])
    _retake(take, edit_steps=early)
    steps = read_steps(take)
    rtf = sendpolicy.rtf_summary([s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps], policy().step_ns)
    assert rtf["max"] > 1 and (where == "last" or rtf["mean"] == 1.0)
    _retake(take, edit_capture=lambda c: c.update(rtf=rtf))
    with pytest.raises(encode.EncodeError, match="above 1"):
        record(tmp_path, take)


@NEEDS_CONTRACT
def test_a_take_from_a_server_that_keeps_its_step_in_single_precision_records_with_an_rtf_of_exactly_one(tmp_path, stand_ins):
    """Finding F-RTF: a take from a server that keeps its step in single precision, paced as it should be, is accepted,
    not refused as 'the pacing did not hold'; its triple min <= mean <= max with every value exactly 1, the same in
    capture.json, the trip and the manifest line."""
    rc, take = make_take(tmp_path, float32_step=True)
    assert rc == 0
    res, out = record(tmp_path, take)
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["ok_terms"]
    line = json.loads((out / "manifest-line.json").read_text(encoding="ascii"))
    assert line["source"]["rtf"] == res["trip"]["rtf"] == read_capture(take)["rtf"] == {"min": 1.0, "mean": 1.0, "max": 1.0}


@NEEDS_CONTRACT
def test_a_take_whose_capture_json_holds_the_whole_ns_reading_s_rtf_is_refused(tmp_path, stand_ins):
    """A take written before the fix keeps in capture.json the RTF the whole-ns reading made of a single-precision step
    (every step's above 1, the mean below them). The encoder recomputes the RTF from steps.jsonl and refuses a record
    that disagrees: such a take is taken again, never read with the old computation."""
    rc, take = make_take(tmp_path, float32_step=True)
    steps = read_steps(take)
    el, cur = [s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps]
    per = [sendpolicy.sim_advance_ns(a, b) / (d - c) for a, b, c, d in zip(el, el[1:], cur, cur[1:])]
    old = {"min": min(per), "mean": sendpolicy.sim_advance_ns(el[0], el[-1]) / (cur[-1] - cur[0]), "max": max(per)}
    assert old["mean"] < old["min"] and old["max"] > 1                       # the premise: F-RTF's two faults
    _retake(take, edit_capture=lambda c: c.update(rtf=old))
    with pytest.raises(encode.EncodeError, match="capture.json's rtf"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_refuses_a_take_whose_rtf_min_is_not_above_zero(tmp_path, stand_ins):
    """One step whose snapshot time did not advance (the later steps' times moved back by one step, so no RTF exceeds 1),
    and capture.json recording the RTF that follows: only the RTF min rule refuses it (verify#12)."""
    rc, take = make_take(tmp_path)
    step_s = C.CARLA_STEP_MS / 1000

    def stalled(steps):
        for s in steps[10:]:
            s["elapsed_s"] -= step_s
    _retake(take, edit_steps=stalled)
    steps = read_steps(take)
    rtf = sendpolicy.rtf_summary([s["elapsed_s"] for s in steps], [s["t_cur_ns"] for s in steps], policy().step_ns)
    assert rtf["min"] == 0.0 and rtf["max"] <= 1                          # the premise
    _retake(take, edit_capture=lambda c: c.update(rtf=rtf))
    with pytest.raises(encode.EncodeError, match=r"RTF min .* not above 0"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("back_ns", [0, 1], ids=["same-instant", "1ns-before"])
def test_record_refuses_steps_that_do_not_become_current_in_increasing_order(tmp_path, stand_ins, capsys, back_ns):
    """Step 10 made current at the very instant step 9 became current, or 1 ns before it, every later step moved back
    with it so no wall time exceeds the cap: no gap and no skipped frame, and step 10's RTF divides by a zero or negative
    wall time. The encoder refuses the take before the RTF, in schedule()'s words, as 'encode.py: refused' with exit 2
    (verify#6: a zero wall time was a ZeroDivisionError's traceback)."""
    rc, take = make_take(tmp_path)

    def back(steps):
        for s in steps[10:]:
            s["t_cur_ns"] -= policy().interval_ns + back_ns
            s["t_vals_ns"] = min(s["t_vals_ns"], s["t_cur_ns"])
    _retake(take, edit_steps=back)
    steps = read_steps(take)
    cur = [s["t_cur_ns"] for s in steps]
    assert cur[10] - cur[9] == -back_ns and sendpolicy.gaps([s["frame"] for s in steps], cur, policy().cap_ns) == []   # the premise
    with pytest.raises(encode.EncodeError, match="^steps must become current in increasing order"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()
    stand_ins.setattr(encode, "load_contract", synthetic_contract)
    assert encode.main(["record", "--take", str(take), "--name", "20261017-carla-7", "--root", str(tmp_path / "recs")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode.py: refused: steps must become current in increasing order") and "Traceback" not in err
    assert not (tmp_path / "recs").exists()


@NEEDS_CONTRACT
@pytest.mark.parametrize("edit", ["extra-key", "missing-key"])
def test_record_refuses_a_step_that_is_not_exactly_the_specified_keys(tmp_path, stand_ins, edit):
    rc, take = make_take(tmp_path)
    _retake(take, edit_steps=(lambda steps: steps[5].update(extra=1)) if edit == "extra-key" else (lambda steps: steps[5].pop("brake")))
    with pytest.raises(encode.EncodeError, match="exactly the keys"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_refuses_a_take_where_the_gear_and_reverse_disagree(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    _retake(take, edit_steps=lambda steps: steps[-1].update(reverse=False))
    with pytest.raises(encode.EncodeError, match="reverse"):
        record(tmp_path, take)


@NEEDS_CONTRACT
@pytest.mark.parametrize("edit,signal", [
    (lambda steps, k: steps[k].update(a=[-40.0 * f for f in steps[k]["fwd"]]), "LongAccel"),
    (lambda steps, k: steps[k].update(wheel_deg=[400.0, 400.0]), "SteerAngleRow1"),         # delta -400 deg from the wheel source
], ids=["accel", "wheel"])
def test_record_refuses_a_value_outside_slice_dbc_s_range_and_names_the_step_never_clamping(tmp_path, stand_ins, edit, signal):
    rc, take = make_take(tmp_path)
    k = 12
    _retake(take, edit_steps=lambda steps: edit(steps, k))
    with pytest.raises(encode.EncodeError, match=r"step %d\b.*%s" % (k, signal)):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


@NEEDS_CONTRACT
def test_record_names_the_step_of_a_reading_the_conversion_cannot_read(tmp_path, stand_ins):
    """A reading that is not a number is a refusal naming its step (the conversion's ValueError), not a traceback
    (verify#12: the steer-out-of-range case it replaces no longer refuses, since the wheel source does not read steer)."""
    rc, take = make_take(tmp_path)
    _retake(take, edit_steps=lambda steps: steps[12].update(w=[0.0, 0.0, "x"]))
    with pytest.raises(encode.EncodeError, match=r"step 12\b"):
        record(tmp_path, take)
    assert not (tmp_path / "rec").exists()


def test_the_range_check_is_strict_at_both_ends():
    ranges = {"LongAccel": (-32.768, 32.767)}
    assert encode.range_problems([(3, {"LongAccel": 32.767}), (4, {"LongAccel": -32.768})], ranges) == []
    probs = encode.range_problems([(5, {"LongAccel": 32.7671}), (6, {"LongAccel": float("nan")})], ranges)
    assert len(probs) == 2 and "step 5" in probs[0] and "step 6" in probs[1]


@NEEDS_CONTRACT
def test_record_refuses_when_the_generation_does_not_compile_profile_3(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    with pytest.raises(encode.EncodeError, match="compiled"):
        record(tmp_path, take, contract=synthetic_contract(compiled=False))


@NEEDS_CONTRACT
def test_record_refuses_an_existing_directory_and_leaves_it_alone(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    out = tmp_path / "rec" / "20261017-carla-7"
    out.mkdir(parents=True)
    (out / "mine").write_text("x", encoding="ascii")
    with pytest.raises(FileExistsError):
        encode.record(take, out, "20261017-carla-7", contract=synthetic_contract())
    assert [p.name for p in out.iterdir()] == ["mine"]


@NEEDS_CONTRACT
def test_a_failed_verify_leaves_no_manifest_line_and_renames_the_recording(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    real = encode.verify
    def failing(rec_dir, contract=None, **kw):
        v = real(rec_dir, contract, **kw)
        v["ok_terms"]["app_switches_as_designed"] = False
        v["ok"] = False
        return v
    stand_ins.setattr(encode, "verify", failing)
    res, out = record(tmp_path, take)
    assert res["recorded"] is False and not out.exists()
    failed = out.with_name(out.name + ".failed")
    assert sorted(p.name for p in failed.iterdir()) == ["carla.log", "carla.log.sha256", "steps.jsonl", "summary.json"]


@NEEDS_CONTRACT
def test_a_verify_that_raises_frees_the_name_and_is_re_raised(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    def boom(rec_dir, contract=None, **kw):
        raise KeyboardInterrupt
    stand_ins.setattr(encode, "verify", boom)
    with pytest.raises(KeyboardInterrupt):
        record(tmp_path, take)
    assert (tmp_path / "rec" / "20261017-carla-7.failed").is_dir() and not (tmp_path / "rec" / "20261017-carla-7").exists()


@NEEDS_CONTRACT
def test_a_rejected_frame_fails_all_frames_accepted_and_the_recording(tmp_path, stand_ins):
    rc, take = make_take(tmp_path, yaw_scale=3.0)                 # the fake's yaw rate three times the kinematic one
    res, out = record(tmp_path, take)
    assert res["recorded"] is False and res["verify"]["ok_terms"]["all_frames_accepted"] is False
    assert res["verify"]["judge"]["reasons"].get("26", 0) > 0


@NEEDS_CONTRACT
def test_verify_detects_a_log_that_is_not_its_regeneration(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    log = out / "carla.log"
    lines = log.read_text(encoding="ascii").splitlines(True)
    lines[3], lines[4] = lines[4], lines[3]
    log.write_text("".join(lines), encoding="ascii")
    v = encode.verify(out, synthetic_contract())
    assert v["ok"] is False and v["ok_terms"]["regenerated_identical"] is False


@NEEDS_CONTRACT
@pytest.mark.parametrize("fault,term", [("gear-frame", "within_half_lsb"), ("missing-frame", "no_period_errors"),
                                        ("channel", "python_can_reader"), ("last-frame", "within_half_lsb")])
def test_verify_fails_the_term_a_damaged_log_breaks(tmp_path, stand_ins, fault, term):
    """A recording whose log was edited after it was written, each edit breaking one term through verify itself (the
    verify_terms tests give it booleans): a gear frame carrying another gear than its step's (within_half_lsb takes the
    gear exactly), a dynamics frame removed (no_period_errors: its neighbour is two periods away) and one line on another
    channel (python_can_reader), and the log's last frame removed (within_half_lsb: verify matches the frames to the steps
    only when the log holds as many frames as the schedule) (verify#13)."""
    rc, take = make_take(tmp_path)
    res, out = record(tmp_path, take)
    assert res["verify"]["ok"] is True
    pol, db = policy(), FakeDb()
    dyn_id, gear_id = ("%03X" % db.get_message_by_name(m).frame_id for m in (pol.dyn_msg, pol.gear_msg))
    log = out / "carla.log"
    lines = log.read_text(encoding="ascii").splitlines(True)
    ids = [ln.split(" ")[2].split("#")[0] for ln in lines]
    if fault == "gear-frame":
        k = next(k for k, ln in enumerate(lines) if ids[k] == gear_id and ln.split("#")[1].startswith("01"))
        lines[k] = lines[k].replace("#01", "#00", 1)
    elif fault == "missing-frame":
        k = next(k for k in range(20, len(lines)) if ids[k] == dyn_id)
        del lines[k]
    elif fault == "last-frame":
        del lines[-1]
    else:
        k = len(lines) // 2
        lines[k] = lines[k].replace(" vcan0 ", " vcan1 ", 1)
    log.write_text("".join(lines), encoding="ascii")
    v = encode.verify(out, synthetic_contract())
    assert v["ok_terms"][term] is False and v["ok"] is False


@NEEDS_CONTRACT
def test_main_refuses_an_existing_directory_and_a_missing_generation_with_exit_2_and_no_traceback(tmp_path, stand_ins, capsys):
    """Every refusal of encode.py ends 'encode.py: refused: ...' and exit 2, an existing directory (left alone) and a missing
    generation included -- not a traceback and exit 1 (verify#19)."""
    rc, take = make_take(tmp_path)
    name = "20261017-carla-7"
    stand_ins.setattr(encode, "load_contract", synthetic_contract)
    taken = tmp_path / "recs" / name
    taken.mkdir(parents=True)
    (taken / "mine").write_text("x", encoding="ascii")
    assert encode.main(["record", "--take", str(take), "--name", name, "--root", str(tmp_path / "recs")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("encode.py: refused: ") and "Traceback" not in err
    assert [p.name for p in taken.iterdir()] == ["mine"]

    def nope():
        raise vf.ContractError("no generated contract at /nowhere")
    stand_ins.setattr(encode, "load_contract", nope)
    for argv in (["record", "--take", str(take), "--name", name, "--root", str(tmp_path / "recs2")], ["verify", str(taken)]):
        assert encode.main(argv) == 2
        err = capsys.readouterr().err
        assert err.startswith("encode.py: refused: ") and "no generated contract" in err and "Traceback" not in err
    assert not (tmp_path / "recs2").exists()


_TERMS = dict(regenerated_identical=True, per_message={"A": 2}, expected={"A": 2}, period_errors=0, within_half_lsb=True,
              python_can_ok=True, segments_ok=True, app_ok=True, gear_ok=True)


def _terms(**changes):
    kw = dict(_TERMS)
    stats = sigsim.JudgeStats(frames=10, accepted=10)
    if changes.pop("rejected", False):
        stats = sigsim.JudgeStats(frames=10, accepted=9, reasons={26: 1})
    if changes.pop("none_judged", False):
        stats = sigsim.JudgeStats(frames=0, accepted=0)
    kw.update(changes)
    return encode.verify_terms(stats=stats, **kw)


@pytest.mark.parametrize("change,term", [
    ({"regenerated_identical": False}, "regenerated_identical"), ({"per_message": {"A": 1}}, "message_counts"),
    ({"period_errors": 1}, "no_period_errors"), ({"within_half_lsb": False}, "within_half_lsb"),
    ({"python_can_ok": False}, "python_can_reader"), ({"segments_ok": False}, "segments_complete"),
    ({"app_ok": False}, "app_switches_as_designed"), ({"gear_ok": False}, "gear_agrees"),
    ({"rejected": True}, "all_frames_accepted"), ({"none_judged": True}, "all_frames_accepted"),
])
def test_each_verify_term_alone_fails_ok(change, term):
    assert all(_terms().values()) and list(_terms()) == list(encode.OK_TERMS)
    got = _terms(**change)
    assert [k for k, v in got.items() if not v] == [term]


def _pred(*items):
    return [{"t_rec_ms": t, "hazard": h} for t, h in items]


WIN = {"on_window_ms": [980, 2400], "off_window_ms": [2380, 3500]}


@pytest.mark.parametrize("pred,ok", [
    (_pred((1000, True), (2400, False)), True),
    (_pred((1000, True), (2400, False), (2500, True)), False),                  # a second switch on
    (_pred((1000, True), (1500, False), (1600, True), (2400, False)), False),   # off and on again inside the brake
    (_pred((900, True), (2400, False)), False),                                 # on before its window
    (_pred((1000, True), (3600, False)), False),                                # off after its window
    (_pred((1000, True)), False),                                               # never off
    (_pred(), False),
])
def test_the_app_term_wants_one_switch_on_and_one_off_each_in_its_window(pred, ok):
    assert encode.app_term(pred, WIN) is ok


@pytest.mark.parametrize("segs,ok", [
    (list(("start", "route drive", "hard brake", "stopped", "reverse", "reverse stop", "stopped in reverse")), True),
    (["start", "route drive", "hard brake", "stopped", "hard brake", "stopped", "reverse", "reverse stop", "stopped in reverse"], False),
    (["start", "hard brake", "route drive", "stopped", "reverse", "reverse stop", "stopped in reverse"], False),
    (["start", "route drive", "hard brake", "stopped", "reverse", "reverse stop"], False),
])
def test_the_segments_term_wants_the_specified_segments_once_in_order(segs, ok):
    steps = []
    for s in segs:
        for _k in range(3):
            g = drive.SEGMENT_GEAR[s]
            steps.append({"seg": s, "gear": g, "reverse": g == -1})
    assert encode.segments_term(steps) is ok


def test_the_gear_term_is_the_conversion_s_rule():
    assert encode.gear_term([{"gear": -1, "reverse": True}, {"gear": 0, "reverse": False}, {"gear": 1, "reverse": False}])
    assert not encode.gear_term([{"gear": -1, "reverse": False}])
    assert not encode.gear_term([{"gear": 1, "reverse": True}])


@NEEDS_CONTRACT
def test_main_refuses_a_root_inside_the_repository_but_takes_sdv_out(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sigsim, "REPO", repo)
    monkeypatch.setattr(encode, "record", lambda *a, **k: pytest.fail("record must not run"))
    with pytest.raises(SystemExit) as exc:
        encode.main(["record", "--take", str(tmp_path / "t" / "20261017-carla-7"), "--name", "20261017-carla-7", "--root", str(repo / "sdv")])
    assert exc.value.code == 2 and "inside the repository" in capsys.readouterr().err
    seen = []

    def fake_record(take, out, name, path=None, contract=None):
        seen.append(out)
        return {"recorded": True, "verify": {"ok": True}}
    monkeypatch.setattr(encode, "record", fake_record)
    assert encode.main(["record", "--take", str(tmp_path / "t" / "20261017-carla-7"), "--name", "20261017-carla-7",
                        "--root", str(repo / "sdv-out" / "r")]) == 0
    assert seen == [repo / "sdv-out" / "r" / "20261017-carla-7"]


@pytest.mark.parametrize("bad", ["20261017-sigsim-7", "x", "20261017-carla-", "20261317-carla-7", "20261017-CARLA-7",
                                 "20261017-carla-7_", "20261017-carla-7abcdefghi", "20261017-carla-7-"])
def test_main_refuses_a_name_that_is_not_a_carla_recording_name(capsys, bad, monkeypatch):
    monkeypatch.setattr(encode, "record", lambda *a, **k: pytest.fail("record must not run"))
    with pytest.raises(SystemExit) as exc:
        encode.main(["record", "--take", "/nowhere/" + bad, "--name", bad])
    assert exc.value.code == 2


@NEEDS_CONTRACT
def test_record_refuses_a_name_that_is_not_the_take_s(tmp_path, stand_ins):
    rc, take = make_take(tmp_path)
    with pytest.raises(encode.EncodeError, match="name"):
        encode.record(take, tmp_path / "rec" / "20261017-carla-8", "20261017-carla-8", contract=synthetic_contract())


# --- the encoder in the sim venv, with cantools and python-can --------------------------------------------------------

def _synthetic_gen(tmp_path):
    """A generation directory holding the generated contract with profile 3 bound as synthetic_contract binds it (a copy
    with assignments appended; the generated file is never edited)."""
    gen = tmp_path / "gen"
    gen.mkdir()
    src = vf.contract_path().read_text(encoding="utf-8")
    pid = int(C.LIVE_DEFAULT_PROFILE["carla"])
    src += ("\nPROFILES = tuple(dict(r, compiled=True, stand_in=(), l_mm=%d) if r['id'] == %d else r for r in PROFILES)\n"
            "COMPILED_PROFILE_IDS = tuple(sorted(set(COMPILED_PROFILE_IDS) | {%d}))\n" % (fake.FAKE_WHEELBASE_MM, pid, pid))
    (gen / "vss_contract.py").write_text(src, encoding="utf-8")
    return gen


def _run_encode(gen, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SDV_GEN=str(gen))
    return subprocess.run([str(SIM_PY), str(CARLA_DIR / "encode.py")] + [str(a) for a in args], capture_output=True, text=True,
                          env=env, cwd=str(REPO))


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_record_and_verify_with_cantools_and_python_can(tmp_path):
    rc, take = make_take(tmp_path)
    gen = _synthetic_gen(tmp_path)
    p = _run_encode(gen, "record", "--take", take, "--name", "20261017-carla-7", "--root", tmp_path / "recs")
    assert p.returncode == 0, p.stderr[-3000:]
    out = tmp_path / "recs" / "20261017-carla-7"
    assert (out / "manifest-line.json").is_file() and "PENDING-PROBE" not in p.stderr
    v = _run_encode(gen, "verify", out)
    assert v.returncode == 0 and json.loads(v.stdout)["ok"] is True, v.stdout[-3000:]
    log = out / "carla.log"
    text = log.read_text(encoding="ascii")
    first = text.splitlines()[0]
    log.write_text(text.replace(first, first[:-1] + ("0" if first[-1] != "0" else "1"), 1), encoding="ascii")
    v = _run_encode(gen, "verify", out)
    assert v.returncode == 1 and json.loads(v.stdout)["ok_terms"]["regenerated_identical"] is False


@NEEDS_CONTRACT
@NEEDS_SIM_VENV
def test_record_in_the_sim_venv_refuses_the_base_generation_whose_profile_3_is_not_compiled(tmp_path):
    if int(C.LIVE_DEFAULT_PROFILE["carla"]) in C.COMPILED_PROFILE_IDS:
        pytest.skip("this generation compiles profile 3 (WP2's): the contract test runs the encoder against it")
    rc, take = make_take(tmp_path)
    p = _run_encode(vf.contract_path().parent, "record", "--take", take, "--name", "20261017-carla-7", "--root", tmp_path / "recs")
    assert p.returncode != 0 and "compiled" in p.stderr and not (tmp_path / "recs" / "20261017-carla-7").exists()


# =================================================================================================================
# The README
# =================================================================================================================

def test_the_readme_gives_the_commands_the_files_the_refusals_and_what_it_does_not_show():
    text = re.sub(r"\s+", " ", (CARLA_DIR / "README.md").read_text(encoding="utf-8"))
    for s in ("carla_capture.py take --name", "carla_capture.py fwcheck --for", "encode.py record --take", "encode.py verify",
              "steps.jsonl", "script.jsonl", "capture.json", "take.sha256", "carla.log", "summary.json", "manifest-line.json",
              "frames.json", "PENDING-PROBE", "fixed_delta_seconds", "127.0.0.1", "work tree", "does not demonstrate",
              "vehicle dynamics", "CAN timing", "perception", "timing", "worldtie.py", "max_substep_delta_time", "max_substeps",
              "apply_settings_stderr", "route drive", "apply_batch_sync", "no Traffic Manager", "P4", "--no-tm",
              "carla.log.sha256", "unrun against a real firewall"):
        assert s in text, s
    for name in ("FEEDER_PACING_INTERVAL_MS", "FEEDER_REPEAT_CAP_MS"):
        assert name in text
