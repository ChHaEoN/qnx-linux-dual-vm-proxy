#!/usr/bin/env python3
"""sigsim.py -- the slice's seeded kinematic signal simulator (sdv/sim).

Plan Phase 1 step 5: a seeded kinematic single-track (bicycle)
model of the sigsim design car drives one scripted trip -- start, cruise, turn, brake, stop,
reverse -- and its five kind 4 signals are encoded with cantools through sdv/vss/slice.dbc at that
file's message periods, into a candump-format log (and optionally live onto vcan0).

    usage: sigsim.py summary [--seed N]
           sigsim.py record  [--seed N] [--suffix S] [--root DIR | --out DIR] [--date YYYYMMDD]
           sigsim.py verify  LOG --seed N
           sigsim.py live    [--seed N] [--channel vcan0] [--seconds S] [--check]
           sigsim.py dbc     [--dbc PATH]

THE MODEL. Rear-axle reference point, no slip: v is the longitudinal speed along the vehicle X axis,
delta the single-track road-wheel angle, psi_dot = v tan(delta) / L, a_x = dv/dt. Axes and signs
are ISO 8855 (X forward, Y left, Z up; delta and psi_dot positive left / counterclockwise seen from
above), the signs slice.dbc carries, so nothing is converted. The model integrates on a fixed step
of one millisecond, with the speed and steering angle piecewise linear in time; heading and position
are integrated too but never sent.

WHERE ITS NUMBERS COME FROM. The wheelbase is the generated profile table's (the profile that is the
live default for the sigsim run type, whose L is the sigsim envelope's wheelbase); the message
periods and signal names are slice.dbc's (the generated contract's DBC_PERIOD_MS, cross-checked
against cantools' cycle_time); the envelope rows are the generated contract's ENVELOPES["sigsim"].
None of them is a literal here. The trip script's own values (below) are sigsim's design values,
each with its reason; where the script drives exactly at an envelope row, it takes that row's value.

THE ENVELOPE. Every one-millisecond step is checked against every sigsim envelope row after it is
integrated (check_step), independently of the clamp that limits the commands before integration
(clamp_step). The clamp counts each row it acted on; the scripted trip is designed so that it never
acts, and every counter is reported. verify and record require every counter, `stalled` included, to
be zero: a trip the clamp had to act on is not the trip the script describes. The rows as checked
(the kind 4 specification, section 5.3):
  - |delta| <= turn_steer_max (<= the design car's steer_max);
  - any non-zero delta only at |v| <= turn_speed_max (a turn is any step with a non-zero steering
    angle, since the specification puts the point (v26_hi, turn_steer_max) outside the envelope);
  - |d delta / dt| <= steer_rate;
  - |a_x| x tan|delta| <= accel_while_steering x tan(turn_steer_max), with |delta| the larger of the
    step's two ends (the product the rule-26 v-skew row is proportional to);
  - |a_x| <= launch_accel while |v| grows, <= braking_max while it falls; |a_x| > accel_while_steering
    only at |delta| <= braking_steer_max;
  - v <= cruise_speed, v >= -reverse_speed_max;
  - v > 0 only with gear > 0, v < 0 only with gear < 0; gear changes only at standstill and never
    straight between forward and reverse (0 at standstill before any direction change).
The script also holds still after every gear change for at least one period of the gear message
plus one of the dynamics message, so a frame packed from a replay never pairs the previous gear
with motion.

THE LOG. Written in candump -l's documented form, one frame per line: "(%010d.%06d) vcan0 %03X#<hex>".
Timestamps are simulation time from zero, not wall time, so the same seed gives a byte-identical log
on the platform sdv/sim/requirements.lock pins (the model's tan is libm's; another interpreter or
libm is not shown to give the same bytes, and verify would then fail). At equal timestamps the
dynamics message (the lower CAN id) precedes the gear message.

RECORD AND VERIFY. record writes the log and its sha256, verifies the log, and only then writes the
manifest line (the one Phase 1 step 6 consumes). A recording that fails verification is renamed
<name>.failed and has no manifest line; so is one that stops for any other reason once its directory
exists (a failed write of the log or its sha256, an exception from verify, an interrupt, a failed write
of the manifest line or the summary), and the exception is re-raised. summary.json, with the
verification, is written for either verdict, but not when verify itself raises. The name is
<date>-sigsim-<seed> and, with --suffix S ([a-z][a-z0-9]{0,7}: a letter first, so a suffix never extends
the seed into another seed's name), <date>-sigsim-<seed>S, which is how a same-day re-record gets a
directory of its own; the whole name must stay [a-z0-9][a-z0-9-]{0,47}. --date is a real calendar date
in ASCII digits. record refuses --out or --root inside the repository, except under sdv-out/ (git
ignores that); recordings belong outside it. A recording under ~/sdv-recordings keeps that ~ form of
its path in the manifest line, however the directory was named on the command line; one anywhere else
keeps the path it was written to. verify's `ok` is the conjunction of the terms it reports under
"ok_terms" (OK_TERMS). live --check reads the channel until CHECK_TAIL_S after the last frame sent,
and exits 1 when a frame sent is not received unchanged (id, frame type and data, in order), when no
frame was sent, and when any other frame appears on the channel up to that time: the channel must
carry no other traffic during --check, and a frame of somebody else's that comes later is not seen.

DOES NOT DEMONSTRATE. The kinematic model is not vehicle dynamics (no tyres, no slip, no
understeer); the DBC describes no real vehicle; vcan has no arbitration, error frames, bus timing or
IRQ, and a live send makes no timing claim. The reader checks alone do not establish a replay-tool integration.

UNVERIFIED: that can-utils' `canplayer -I sigsim.log` replays this log onto vcan0. The unit checks do not establish
this integration. Checked by running `canplayer -I sigsim.log` onto vcan0 and comparing what arrives
with `candump -l`, frame by frame
(plan: Phase 5 step 4, or whenever can-utils is available).

UNVERIFIED: that the CAN provider's --dumpfile accepts a log whose timestamps count from zero. Closed by
running the provider's --dumpfile on this log (plan: Phase 1 step 6, and the Phase 1 exit test).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_FRAME_DIR = str(REPO / "sdv" / "frame")
if _FRAME_DIR not in sys.path:
    sys.path.insert(0, _FRAME_DIR)
import rules  # noqa: E402
import vssframe as vf  # noqa: E402

DBC_PATH = REPO / "sdv" / "vss" / "slice.dbc"
RUN_TYPE = "sigsim"
CHANNEL = "vcan0"
LOG_NAME = "sigsim.log"
DEFAULT_SEED = 1
DEFAULT_ROOT = Path("~/sdv-recordings")
MANIFEST_NAME = "manifest-line.json"
SUMMARY_NAME = "summary.json"
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")      # a recording's name is a manifest-line name
SUFFIX_PATTERN = re.compile(r"[a-z][a-z0-9]{0,7}")         # record --suffix: a letter first, so <seed><suffix> is never another seed's digits
CHECK_TAIL_S = 1.0          # live --check keeps reading the channel this long after the last frame sent, so a frame
                            # still in flight arrives, and a frame of anyone else's that comes soon after is seen

# --- the trip script: sigsim's design values ------------------------------------------------------
STEP_MS = 1                 # integration step: one millisecond, far below the fastest message period
IDLE_MS = 1000              # standstill in neutral at the start, the end, and between the legs
GEAR_SETTLE_MS = 500        # hold after each gear change before moving; must exceed one gear period
                            # plus one dynamics period (checked), so a replayed frame never pairs the
                            # previous gear with motion
LAUNCH_ACCEL = 2.5          # m/s^2, a moderate launch, inside the envelope's launch acceleration
APPROACH_DECEL = 2.0        # m/s^2, slowing from cruise to the turn speed
STEER_RATE = 8.0            # deg/s at the road wheel, inside the envelope's steering rate, so no
                            # float step of the ramp ever sits on the row
TURN_ENTRY_DECEL = 1.0      # m/s^2, braking gently while steering into the turn: exercises the
                            # acceleration-while-steering row inside its bound
TURN_EXIT_ACCEL = 1.0       # m/s^2, accelerating gently while unwinding out of the turn
REVERSE_ACCEL = 1.5         # m/s^2, reversing away, inside the launch acceleration
REVERSE_BRAKE = 2.0         # m/s^2, stopping from reverse
# Seeded choices (random.Random(seed)); every range lies inside the envelope.
CRUISE_MS_RANGE = (6000, 10000)      # the first cruise, in 100 ms steps
CRUISE2_MS_RANGE = (2000, 4000)      # the cruise after the turn
TURN_HOLD_MS_RANGE = (1000, 3000)    # holding the turn angle
REVERSE_HOLD_MS_RANGE = (1000, 2000)  # holding the reverse steering angle
TURN_ANGLE_FRACTION = (0.5, 1.0)     # of the envelope's turn_steer_max, in half-degree steps
REVERSE_ANGLE_FRACTION = (0.25, 0.75)

# A moving segment that has not reached its targets after this long is a script or clamp fault.
MAX_SEGMENT_MS = 120000

# Tolerance of the integration-consistency checks ((v_next - v) / dt against the recorded a_x):
# float rounding only, far below any envelope row.
_CONSISTENCY = 1e-6


class ScriptError(RuntimeError):
    """The script asked for something the model cannot do (a gear change while moving)."""


class EnvelopeError(AssertionError):
    """A step left the sigsim envelope."""


# --- inputs from the generated contract -------------------------------------------------------------

@dataclass(frozen=True)
class Envelope:
    wheelbase_mm: int
    cruise_speed: float
    turn_speed_max: float
    turn_steer_max: float
    steer_max: float
    steer_rate: float
    accel_while_steering: float
    braking_max: float
    braking_steer_max: float
    launch_accel: float
    reverse_speed_max: float

    @classmethod
    def from_contract(cls, c: Any) -> "Envelope":
        e = c.ENVELOPES[RUN_TYPE]
        return cls(**{k: e[k] for k in cls.__dataclass_fields__})  # type: ignore[attr-defined]

    @property
    def product_bound(self) -> float:
        """accel_while_steering x tan(turn_steer_max): the bound on |a_x| x tan|delta|."""
        return self.accel_while_steering * math.tan(math.radians(self.turn_steer_max))


@dataclass(frozen=True)
class Setup:
    """Everything sigsim takes from the generated contract."""
    contract: Any
    env: Envelope
    profile_id: int
    profile: Dict[str, Any]
    dyn_msg: str
    gear_msg: str
    signals: Tuple[str, str, str, str, str]
    periods_ms: Dict[str, int]

    @property
    def wheelbase_mm(self) -> int:
        return int(self.profile["l_mm"])


def setup(contract: Any = None) -> Setup:
    c = contract if contract is not None else vf.load_contract()
    env = Envelope.from_contract(c)
    pid = int(c.LIVE_DEFAULT_PROFILE[RUN_TYPE])
    rows = {int(r["id"]): r for r in c.PROFILES}
    prof = rows[pid]
    if int(prof["l_mm"]) != int(env.wheelbase_mm):
        raise ValueError("profile %d's L %s differs from the sigsim envelope's wheelbase %s" % (pid, prof["l_mm"], env.wheelbase_mm))
    msgs = tuple(c.SLOT_DBC_MESSAGES)
    dyn = c.RULE26_DBC_MESSAGE
    if msgs[:4] != (dyn,) * 4 or msgs[4] == dyn:
        raise ValueError("slots 0..3 must share the dynamics message and the gear its own: %r" % (msgs,))
    periods = {m: int(c.DBC_PERIOD_MS[m]) for m in (dyn, msgs[4])}
    return Setup(contract=c, env=env, profile_id=pid, profile=dict(prof), dyn_msg=dyn, gear_msg=msgs[4],
                 signals=tuple(c.SLOT_DBC_SIGNALS), periods_ms=periods)  # type: ignore[arg-type]


# --- the script ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Seg:
    """One scripted segment: speed and steering each move toward a target at a rate (None = keep);
    the segment ends when both are reached, then holds for hold_ms. A gear change happens at its
    start, at standstill only."""
    label: str
    v_target: Optional[float] = None
    accel: float = 0.0
    d_target: Optional[float] = None
    steer_rate: float = 0.0
    hold_ms: int = 0
    gear: Optional[int] = None


@dataclass(frozen=True)
class TripParams:
    seed: int
    cruise_ms: int
    cruise2_ms: int
    turn_dir: int
    turn_angle: float
    turn_hold_ms: int
    rev_dir: int
    rev_angle: float
    rev_hold_ms: int


def _half_degrees(rng: random.Random, lo: float, hi: float) -> float:
    return rng.randint(int(math.ceil(lo * 2)), int(math.floor(hi * 2))) / 2.0


def trip_params(seed: int, env: Envelope) -> TripParams:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative int")
    rng = random.Random(seed)
    return TripParams(
        seed=seed,
        cruise_ms=rng.randrange(CRUISE_MS_RANGE[0], CRUISE_MS_RANGE[1] + 1, 100),
        cruise2_ms=rng.randrange(CRUISE2_MS_RANGE[0], CRUISE2_MS_RANGE[1] + 1, 100),
        turn_dir=rng.choice((1, -1)),
        turn_angle=_half_degrees(rng, env.turn_steer_max * TURN_ANGLE_FRACTION[0], env.turn_steer_max * TURN_ANGLE_FRACTION[1]),
        turn_hold_ms=rng.randrange(TURN_HOLD_MS_RANGE[0], TURN_HOLD_MS_RANGE[1] + 1, 100),
        rev_dir=rng.choice((1, -1)),
        rev_angle=_half_degrees(rng, env.turn_steer_max * REVERSE_ANGLE_FRACTION[0], env.turn_steer_max * REVERSE_ANGLE_FRACTION[1]),
        rev_hold_ms=rng.randrange(REVERSE_HOLD_MS_RANGE[0], REVERSE_HOLD_MS_RANGE[1] + 1, 100),
    )


def script(p: TripParams, env: Envelope) -> List[Seg]:
    """The trip: start, cruise, turn, brake, stop, reverse."""
    turn = p.turn_dir * p.turn_angle
    ramp_s = p.turn_angle / STEER_RATE                        # time to steer in (and out)
    entry_v = env.turn_speed_max - TURN_ENTRY_DECEL * ramp_s  # the speed the entry ramp ends at
    rev = p.rev_dir * p.rev_angle
    return [
        Seg("idle", hold_ms=IDLE_MS),
        Seg("engage forward", gear=1, hold_ms=GEAR_SETTLE_MS),
        Seg("launch", v_target=env.cruise_speed, accel=LAUNCH_ACCEL),
        Seg("cruise", hold_ms=p.cruise_ms),
        Seg("approach", v_target=env.turn_speed_max, accel=APPROACH_DECEL),
        Seg("turn in", v_target=entry_v, accel=TURN_ENTRY_DECEL, d_target=turn, steer_rate=STEER_RATE),
        Seg("turn", hold_ms=p.turn_hold_ms),
        Seg("turn out", v_target=env.turn_speed_max, accel=TURN_EXIT_ACCEL, d_target=0.0, steer_rate=STEER_RATE),
        Seg("accelerate", v_target=env.cruise_speed, accel=LAUNCH_ACCEL),
        Seg("cruise again", hold_ms=p.cruise2_ms),
        Seg("hard brake", v_target=0.0, accel=env.braking_max),
        Seg("stopped", hold_ms=GEAR_SETTLE_MS),
        Seg("neutral", gear=0, hold_ms=IDLE_MS),
        Seg("engage reverse", gear=-1, hold_ms=GEAR_SETTLE_MS),
        Seg("reverse", v_target=-env.reverse_speed_max, accel=REVERSE_ACCEL),
        Seg("reverse steer", d_target=rev, steer_rate=STEER_RATE),
        Seg("reverse turn", hold_ms=p.rev_hold_ms),
        Seg("reverse straighten", d_target=0.0, steer_rate=STEER_RATE),
        Seg("reverse stop", v_target=0.0, accel=REVERSE_BRAKE),
        Seg("stopped in reverse", hold_ms=GEAR_SETTLE_MS),
        Seg("neutral at end", gear=0, hold_ms=IDLE_MS),
    ]


# --- the envelope: clamp (commands) and check (integrated steps) -------------------------------------

CLAMP_ROWS = ("steer_rate", "turn_steer_max", "turn_speed", "launch_accel", "braking_max", "accel_while_steering",
              "braking_steer_max", "cruise_speed", "reverse_speed_max", "gear_direction", "stalled")
# The product row of a clamped command (|a| = bound / tan|delta|) can land one rounding above the
# bound when multiplied back; the check allows that much and no more.
_PRODUCT_ROUNDING = 1e-12


def _sgn(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def clamp_step(v: float, d: float, v_next: float, d_next: float, a: float, r: float, gear: int,
               env: Envelope) -> Tuple[float, float, float, float, List[str]]:
    """Limit one step's command -- the next speed and steering angle, and the acceleration and
    steering rate that reach them -- to the envelope. The rates are compared as commanded, never
    re-derived from the two ends (a float difference of a command exactly at a row would read as
    over it). Returns (v_next, d_next, a, r, rows that acted)."""
    hits: List[str] = []
    dt = STEP_MS / 1000.0
    # steering
    if abs(r) > env.steer_rate:
        r = _sgn(r) * env.steer_rate
        d_next = d + r * dt
        hits.append("steer_rate")
    if abs(d_next) > env.turn_steer_max:
        d_next = _sgn(d_next) * env.turn_steer_max
        r = (d_next - d) / dt
        hits.append("turn_steer_max")
    if abs(d_next) > abs(d) and max(abs(v), abs(v_next)) > env.turn_speed_max:
        d_next, r = d, 0.0
        hits.append("turn_speed")
    # speed
    dmax = max(abs(d), abs(d_next))
    if dmax > 0 and abs(v_next) > env.turn_speed_max and abs(v_next) > abs(v):
        v_next = _sgn(v_next) * max(env.turn_speed_max, abs(v))
        a = (v_next - v) / dt
        hits.append("turn_speed")
    growing = abs(v_next) > abs(v)
    lim = env.launch_accel if growing else env.braking_max
    if abs(a) > lim:
        a = _sgn(a) * lim
        v_next = v + a * dt
        hits.append("launch_accel" if growing else "braking_max")
    t = math.tan(math.radians(dmax))
    if t > 0 and abs(a) * t > env.product_bound:
        a = _sgn(a) * env.product_bound / t
        v_next = v + a * dt
        hits.append("accel_while_steering")
    if abs(a) > env.accel_while_steering and dmax > env.braking_steer_max:
        a = _sgn(a) * env.accel_while_steering
        v_next = v + a * dt
        hits.append("braking_steer_max")
    if v_next > env.cruise_speed:
        v_next = env.cruise_speed
        a = (v_next - v) / dt
        hits.append("cruise_speed")
    if v_next < -env.reverse_speed_max:
        v_next = -env.reverse_speed_max
        a = (v_next - v) / dt
        hits.append("reverse_speed_max")
    if (gear > 0 and v_next < 0) or (gear < 0 and v_next > 0) or (gear == 0 and v_next != 0):
        v_next = 0.0
        a = (v_next - v) / dt
        hits.append("gear_direction")
    return v_next, d_next, a, r, hits


def check_step(v: float, d: float, v_next: float, d_next: float, a: float, r: float, gear: int, env: Envelope) -> List[str]:
    """Every sigsim envelope row one integrated step breaks (empty = inside). Independent of the clamp."""
    bad: List[str] = []
    dt = STEP_MS / 1000.0
    dmax = max(abs(d), abs(d_next))
    vmax = max(abs(v), abs(v_next))
    if abs((v_next - v) / dt - a) > _CONSISTENCY:
        bad.append("a_x is not dv/dt")
    if abs((d_next - d) / dt - r) > _CONSISTENCY:
        bad.append("steering rate is not d delta/dt")
    if abs(r) > env.steer_rate:
        bad.append("steer_rate")
    if dmax > env.turn_steer_max or dmax > env.steer_max:
        bad.append("turn_steer_max")
    if dmax > 0 and vmax > env.turn_speed_max:
        bad.append("turn_speed")
    if abs(v_next) > abs(v):
        if abs(a) > env.launch_accel:
            bad.append("launch_accel")
    elif abs(a) > env.braking_max:
        bad.append("braking_max")
    if abs(a) * math.tan(math.radians(dmax)) > env.product_bound * (1 + _PRODUCT_ROUNDING):
        bad.append("accel_while_steering")
    if abs(a) > env.accel_while_steering and dmax > env.braking_steer_max:
        bad.append("braking_steer_max")
    if v_next > env.cruise_speed:
        bad.append("cruise_speed")
    if v_next < -env.reverse_speed_max:
        bad.append("reverse_speed_max")
    if (v_next > 0 and gear <= 0) or (v_next < 0 and gear >= 0):
        bad.append("gear_direction")
    return bad


# --- the simulation ---------------------------------------------------------------------------------

@dataclass
class Trip:
    """The integrated trip, one entry per millisecond t = 0..duration_ms. a[t] and r[t] are the
    acceleration and steering rate over [t, t + 1 ms) (0 at the end)."""
    params: TripParams
    setup: Setup
    v: List[float] = field(default_factory=list)
    d: List[float] = field(default_factory=list)
    a: List[float] = field(default_factory=list)
    r: List[float] = field(default_factory=list)
    gear: List[int] = field(default_factory=list)
    psi: List[float] = field(default_factory=list)
    x: List[float] = field(default_factory=list)
    y: List[float] = field(default_factory=list)
    segments: List[Tuple[str, int, int]] = field(default_factory=list)
    gear_changes: List[Tuple[int, int, int]] = field(default_factory=list)
    clamps: Dict[str, int] = field(default_factory=dict)
    violations: List[Tuple[int, str]] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return len(self.v) - 1

    @property
    def wheelbase_m(self) -> float:
        return self.setup.wheelbase_mm / 1000.0

    def psi_dot(self, t: int) -> float:
        """The model's yaw rate at t [deg/s]: v tan(delta) / L."""
        return math.degrees(self.v[t] * math.tan(math.radians(self.d[t])) / self.wheelbase_m)

    def sample(self, t: int) -> Tuple[float, float, float, float]:
        """(v [m/s], a_x [m/s^2], delta [deg], psi_dot [deg/s]) at t ms."""
        return self.v[t], self.a[t], self.d[t], self.psi_dot(t)


class _Integrator:
    def __init__(self, trip: Trip, env: Envelope, strict: bool):
        self.trip, self.env, self.strict = trip, env, strict
        self.v = self.d = self.psi = self.x = self.y = 0.0
        self.g = 0
        self.t = 0
        for row in CLAMP_ROWS:
            trip.clamps[row] = 0

    def _record(self) -> None:
        tr = self.trip
        tr.v.append(self.v)
        tr.d.append(self.d)
        tr.gear.append(self.g)
        tr.psi.append(self.psi)
        tr.x.append(self.x)
        tr.y.append(self.y)

    def start(self) -> None:
        self._record()

    def step(self, v_next: float, d_next: float, a: float, r: float) -> None:
        tr, env = self.trip, self.env
        bad = check_step(self.v, self.d, v_next, d_next, a, r, self.g, env)
        for row in bad:
            tr.violations.append((self.t, row))
        if bad and self.strict:
            raise EnvelopeError("t=%d ms: %s" % (self.t, ", ".join(bad)))
        tr.a.append(a)
        tr.r.append(r)
        dt = STEP_MS / 1000.0
        yaw = self.v * math.tan(math.radians(self.d)) / tr.wheelbase_m
        self.x += self.v * math.cos(self.psi) * dt
        self.y += self.v * math.sin(self.psi) * dt
        self.psi += yaw * dt
        self.v, self.d = v_next, d_next
        self.t += STEP_MS
        self._record()

    def run(self, seg: Seg) -> None:
        tr, env = self.trip, self.env
        t0 = self.t
        if seg.gear is not None:
            if self.v != 0.0:
                raise ScriptError("%s: gear change at v=%r (only at standstill)" % (seg.label, self.v))
            if seg.gear * self.g < 0:
                raise ScriptError("%s: gear %d -> %d skips neutral" % (seg.label, self.g, seg.gear))
            if seg.gear != self.g:
                tr.gear_changes.append((self.t, self.g, seg.gear))
                self.g = seg.gear
                tr.gear[-1] = self.g
        dt = STEP_MS / 1000.0
        vt = float(self.v if seg.v_target is None else seg.v_target)     # no target: keep the speed
        st = float(self.d if seg.d_target is None else seg.d_target)
        a_cmd = _sgn(vt - self.v) * seg.accel
        r_cmd = _sgn(st - self.d) * seg.steer_rate
        v0, d0, k = self.v, self.d, 0
        while (a_cmd and self.v != vt) or (r_cmd and self.d != st):
            k += 1
            v_next, a = self.v, 0.0
            if a_cmd and self.v != vt:
                v_next, a = v0 + a_cmd * (k * STEP_MS / 1000.0), a_cmd
                if (v_next - vt) * a_cmd >= 0:                     # reached or crossed
                    v_next = vt
                    a = _sgn(a_cmd) * min(abs(a_cmd), abs(v_next - self.v) / dt)
            d_next, r = self.d, 0.0
            if r_cmd and self.d != st:
                d_next, r = d0 + r_cmd * (k * STEP_MS / 1000.0), r_cmd
                if (d_next - st) * r_cmd >= 0:
                    d_next = st
                    r = _sgn(r_cmd) * min(abs(r_cmd), abs(d_next - self.d) / dt)
            cv, cd, ca, cr, hits = clamp_step(self.v, self.d, v_next, d_next, a, r, self.g, env)
            if hits:
                for h in hits:
                    tr.clamps[h] += 1
                if cv == self.v and cd == self.d:
                    tr.clamps["stalled"] += 1        # the envelope's edge is this segment's end
                    break
                v_next, d_next, a, r = cv, cd, ca, cr
                v0, d0, k = v_next, d_next, 0
            self.step(v_next, d_next, a, r)
            if self.t - t0 > MAX_SEGMENT_MS:
                raise ScriptError("%s: not finished after %d ms (does the clamp hold the model back?)" % (seg.label, MAX_SEGMENT_MS))
        for _ in range(seg.hold_ms // STEP_MS):
            self.step(self.v, self.d, 0.0, 0.0)
        tr.segments.append((seg.label, t0, self.t))


def simulate(seed: int = DEFAULT_SEED, contract: Any = None, segments: Optional[Sequence[Seg]] = None,
             strict: bool = True) -> Trip:
    """Integrate one trip. strict raises EnvelopeError at the first step outside the envelope; with
    strict False every violation is collected in trip.violations instead."""
    su = setup(contract)
    params = trip_params(seed, su.env)
    trip = Trip(params=params, setup=su)
    it = _Integrator(trip, su.env, strict)
    it.start()
    for seg in (segments if segments is not None else script(params, su.env)):
        it.run(seg)
    # pad the final standstill to a whole number of both periods, so both messages end together
    lcm = 1
    for p in su.periods_ms.values():
        lcm = lcm * p // math.gcd(lcm, p)
    while it.t % lcm:
        it.step(it.v, it.d, 0.0, 0.0)
    trip.a.append(0.0)
    trip.r.append(0.0)
    _check_trip(trip)
    return trip


def _check_trip(trip: Trip) -> None:
    """Whole-trip checks beyond the per-step rows: the settle after each gear change, the end state."""
    su = trip.setup
    settle_min = su.periods_ms[su.gear_msg] + su.periods_ms[su.dyn_msg]
    if GEAR_SETTLE_MS <= settle_min:
        raise EnvelopeError("GEAR_SETTLE_MS must exceed one gear period plus one dynamics period")
    for t, _old, _new in trip.gear_changes:
        moving = [u for u in range(t, min(t + settle_min, trip.duration_ms) + 1) if trip.v[u] != 0.0]
        if moving:
            trip.violations.append((t, "moved within %d ms of a gear change" % settle_min))
    if trip.v[-1] != 0.0 or trip.gear[-1] != 0 or trip.d[-1] != 0.0:
        trip.violations.append((trip.duration_ms, "the trip does not end at rest in neutral, straight"))
    if trip.violations:
        raise EnvelopeError("; ".join("t=%d %s" % tv for tv in trip.violations[:10]))


# --- the message stream -------------------------------------------------------------------------------

def sample_times(trip: Trip, msg: str) -> range:
    return range(0, trip.duration_ms + 1, trip.setup.periods_ms[msg])


def model_messages(trip: Trip) -> List[Tuple[int, str, Tuple[Any, ...]]]:
    """Every message of the log, in log order, with the model's (unquantised) values:
    (t_ms, message, values). The dynamics message precedes the gear message at equal t."""
    su = trip.setup
    out: List[Tuple[int, int, str, Tuple[Any, ...]]] = []
    for t in sample_times(trip, su.dyn_msg):
        out.append((t, 0, su.dyn_msg, trip.sample(t)))
    for t in sample_times(trip, su.gear_msg):
        out.append((t, 1, su.gear_msg, (trip.gear[t],)))
    out.sort(key=lambda m: (m[0], m[1]))
    return [(t, name, vals) for t, _o, name, vals in out]


@dataclass
class JudgeStats:
    frames: int = 0
    accepted: int = 0
    reasons: Dict[int, int] = field(default_factory=dict)
    first_reject: Optional[Tuple[int, int]] = None
    rule26_judged: int = 0           # frames inside rule 26's speed window (the rule compares yaw there)
    rule26_above_tol: int = 0        # of those, frames whose psi_dot_kin exceeds tol26: a zeroed yaw must give 26 on each
    rule26_max_residual: float = 0.0
    rule27_checked: int = 0
    turning_frames: int = 0          # frames with a non-zero steering angle
    turning_outside_window: int = 0  # of those, frames outside rule 26's speed window (none, by design)
    max_age_ms: int = 0
    age_negative: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"frames": self.frames, "accepted": self.accepted, "reasons": {str(k): v for k, v in sorted(self.reasons.items())},
                "first_reject": list(self.first_reject) if self.first_reject else None, "rule26_judged": self.rule26_judged,
                "rule26_above_tol": self.rule26_above_tol, "rule26_max_residual_deg_s": self.rule26_max_residual,
                "rule27_checked": self.rule27_checked, "turning_frames": self.turning_frames,
                "turning_outside_window": self.turning_outside_window, "max_age_ms": self.max_age_ms,
                "age_negative": self.age_negative}


def judge_stream(messages: Iterable[Tuple[int, str, Tuple[Any, ...]]], su: Setup, tables: Optional[rules.Tables] = None,
                 profile_id: Optional[int] = None) -> JudgeStats:
    """Pack one kind 4 frame after every dynamics message, as a replay-mode bridge holding the latest
    value of each slot would, and judge it with the reference rules. Timestamps are the messages'
    (simulation time); the age is the oldest used value's."""
    tb = tables if tables is not None else rules.Tables.from_contract(su.contract)
    pid = su.profile_id if profile_id is None else profile_id
    prof = tb.profiles[pid]
    st = JudgeStats()
    held: Dict[str, Tuple[Tuple[Any, ...], int]] = {}
    seq = 0
    for t, name, vals in messages:
        held[name] = (vals, t)
        if name != su.dyn_msg:
            continue
        dyn, t_dyn = held[su.dyn_msg]
        gear = held.get(su.gear_msg)
        now_ns = t * 1_000_000
        used = [t_dyn * 1_000_000] + ([gear[1] * 1_000_000] if gear else [])
        age, neg = vf.age_field(now_ns, used)
        seq += 1
        claim = vf.Claim(seq=seq, tstamp_ns=now_ns, profile=pid, v=dyn[0], a_x=dyn[1], delta=dyn[2], psi_dot=dyn[3],
                         gear=int(gear[0][0]) if gear else None, age_ms=age)
        frame = vf.encode(claim, su.contract)
        verdict, reason = rules.judge_frame(frame, tb)  # type: ignore[misc]
        st.frames += 1
        st.max_age_ms = max(st.max_age_ms, age)
        st.age_negative += int(neg)
        if verdict == rules.V_ACCEPT:
            st.accepted += 1
        else:
            st.reasons[reason] = st.reasons.get(reason, 0) + 1
            if st.first_reject is None:
                st.first_reject = (seq, reason)
        dec = vf.decode(frame)
        v, dl, y = dec.v, dec.delta, dec.psi_dot
        assert v is not None and dl is not None and y is not None
        av = rules.dabs(v)
        in_window = prof.v26_lo <= av <= prof.v26_hi
        if dl != 0.0:
            st.turning_frames += 1
            st.turning_outside_window += int(not in_window)
        if in_window and rules.dabs(dl) <= prof.delta_max:
            kin, ay = rules.kinematics(av, rules.dabs(dl), prof.l_mm, tb)
            st.rule26_judged += 1
            st.rule26_above_tol += int(kin > prof.tol26 and (prof.ay26_max == 0.0 or ay <= prof.ay26_max))
            st.rule26_max_residual = max(st.rule26_max_residual, rules.dabs(rules.dabs(y) - kin))
        if dec.gear is not None and dec.gear != 0:
            st.rule27_checked += 1
    return st


def summary(trip: Trip) -> Dict[str, Any]:
    su = trip.setup
    product = 0.0
    for i in range(trip.duration_ms):
        dmax = max(abs(trip.d[i]), abs(trip.d[i + 1]))
        product = max(product, abs(trip.a[i]) * math.tan(math.radians(dmax)))
    return {
        "seed": trip.params.seed,
        "params": trip.params.__dict__,
        "duration_ms": trip.duration_ms,
        "messages": {m: len(sample_times(trip, m)) for m in (su.dyn_msg, su.gear_msg)},
        "periods_ms": dict(su.periods_ms),
        "wheelbase_mm": su.wheelbase_mm,
        "profile_id": su.profile_id,
        "segments": [list(s) for s in trip.segments],
        "gear_changes": [list(g) for g in trip.gear_changes],
        "clamps": dict(trip.clamps),
        "clamped_steps": sum(trip.clamps.values()),
        "violations": len(trip.violations),
        "v_range": [min(trip.v), max(trip.v)],
        "delta_range": [min(trip.d), max(trip.d)],
        "a_range": [min(trip.a), max(trip.a)],
        "max_abs_a_tan_delta": product,
        "product_bound": su.env.product_bound,
        "heading_end_deg": math.degrees(trip.psi[-1]),
    }


# --- cantools, the log, python-can -------------------------------------------------------------------

def load_dbc(su: Setup, path: Optional[Path] = None) -> Any:
    """slice.dbc (or the DBC at `path`) through cantools (strict), checked against the generated contract:
    every slot signal in its message, the periods equal to DBC_PERIOD_MS, the units equal to SLOT_DBC_UNITS."""
    import cantools  # the sim venv (sdv/sim/requirements.lock)
    db = cantools.database.load_file(str(path if path is not None else DBC_PATH), strict=True)
    c = su.contract
    for i, sig in enumerate(su.signals):
        msg = db.get_message_by_name(c.SLOT_DBC_MESSAGES[i])
        s = msg.get_signal_by_name(sig)
        unit = s.unit if s.unit else None
        if unit != c.SLOT_DBC_UNITS[i]:
            raise ValueError("%s: cantools unit %r, contract %r" % (sig, s.unit, c.SLOT_DBC_UNITS[i]))
    for name, period in su.periods_ms.items():
        got = db.get_message_by_name(name).cycle_time
        if got != period:
            raise ValueError("%s: cantools cycle_time %r, contract DBC_PERIOD_MS %r" % (name, got, period))
    if db.get_message_by_name(su.dyn_msg).frame_id >= db.get_message_by_name(su.gear_msg).frame_id:
        raise ValueError("the dynamics message must have the lower CAN id (log order at equal timestamps)")
    return db


def dbc_description(su: Setup, path: Optional[Path] = None) -> Dict[str, Any]:
    import cantools
    dbc_path = path if path is not None else DBC_PATH
    db = load_dbc(su, dbc_path)
    out: Dict[str, Any] = {"cantools": cantools.__version__, "dbc_sha256": hashlib.sha256(dbc_path.read_bytes()).hexdigest(),
                           "strict": True, "messages": {}}
    for m in db.messages:
        out["messages"][m.name] = {
            "frame_id": "0x%03X" % m.frame_id, "length": m.length, "cycle_time": m.cycle_time, "send_type": m.send_type,
            "extended": m.is_extended_frame,
            "signals": {s.name: {"start": s.start, "length": s.length, "byte_order": s.byte_order, "signed": s.is_signed,
                                 "scale": s.scale, "offset": s.offset, "min": s.minimum, "max": s.maximum, "unit": s.unit,
                                 "choices": {str(k): str(v) for k, v in (s.choices or {}).items()}} for s in m.signals}}
    return out


def encode_frames(trip: Trip, db: Any) -> List[Tuple[int, int, bytes]]:
    """(t_ms, CAN id, data) of every frame of the trip, in log order."""
    su = trip.setup
    sig = su.signals
    dyn, gear = db.get_message_by_name(su.dyn_msg), db.get_message_by_name(su.gear_msg)
    frames = []
    for t, name, vals in model_messages(trip):
        if name == su.dyn_msg:
            data = dyn.encode(dict(zip(sig[:4], vals)))
            frames.append((t, dyn.frame_id, bytes(data)))
        else:
            data = gear.encode({sig[4]: vals[0]})
            frames.append((t, gear.frame_id, bytes(data)))
    if frames != sorted(frames, key=lambda f: (f[0], f[1])):
        raise AssertionError("log order is not (timestamp, CAN id)")
    return frames


def candump_line(t_ms: int, can_id: int, data: bytes, channel: str = CHANNEL) -> str:
    return "(%010d.%06d) %s %03X#%s\n" % (t_ms // 1000, (t_ms % 1000) * 1000, channel, can_id, data.hex().upper())


def candump_text(frames: Iterable[Tuple[int, int, bytes]], channel: str = CHANNEL) -> str:
    return "".join(candump_line(t, i, d, channel) for t, i, d in frames)


def python_can_writer_text(frames: Iterable[Tuple[int, int, bytes]], channel: str = CHANNEL) -> str:
    """The same frames through python-can's CanutilsLogWriter (for comparison only)."""
    import can
    buf = io.StringIO()
    w = can.CanutilsLogWriter(buf, channel=channel)
    for t, i, d in frames:
        w.on_message_received(can.Message(timestamp=t / 1000.0, arbitration_id=i, is_extended_id=False, data=d, channel=channel))
    text = buf.getvalue()
    w.stop()
    return text


def read_log(path: Path) -> List[Tuple[float, int, bytes, Any]]:
    """The log through python-can's CanutilsLogReader: (timestamp, id, data, channel)."""
    import can
    out = []
    with can.CanutilsLogReader(str(path)) as reader:
        for m in reader:
            if m.is_extended_id or m.is_remote_frame or m.is_error_frame or m.is_fd:
                raise ValueError("unexpected frame type in %s: %r" % (path, m))
            out.append((m.timestamp, m.arbitration_id, bytes(m.data), m.channel))
    return out


# verify's `ok` is the conjunction of exactly these terms (each reported under "ok_terms"), so a failure
# names itself and a term dropped from the conjunction changes the reported keys.
OK_TERMS = ("regenerated_identical", "message_counts", "no_period_errors", "within_half_lsb", "no_gear_mismatches",
            "all_frames_accepted", "trip_clamps_all_zero")


def quantised_within_half_lsb(worst: Dict[str, float], lsb: Dict[str, float]) -> bool:
    """Every signal's worst decode error (|decoded - model|) is at most half its LSB: what rounding the
    model's value to the nearest raw step leaves, plus 1e-9 of float slack."""
    return all(worst[s] <= lsb[s] / 2 + 1e-9 for s in worst)


def verify_terms(*, regenerated_identical: bool, per_message: Dict[str, int], expected: Dict[str, int], period_errors: int,
                 within_half_lsb: bool, gear_mismatches: int, stats: JudgeStats, clamps: Dict[str, int]) -> Dict[str, bool]:
    """The terms of verify's `ok`, in OK_TERMS order. The trip's clamp counters must all be zero, `stalled`
    included: the design is a trip the clamp never acts on, so a recording of one it acted on (an envelope
    row moved under the script) is not the recording the design describes. `clamps` must hold every row
    of CLAMP_ROWS (all() over a dict that lacks them is vacuously true), else ValueError."""
    if set(clamps) != set(CLAMP_ROWS):
        raise ValueError("clamps must hold exactly the rows of CLAMP_ROWS, got %s" % sorted(clamps))
    return {
        "regenerated_identical": regenerated_identical,
        "message_counts": per_message == expected,
        "no_period_errors": period_errors == 0,
        "within_half_lsb": within_half_lsb,
        "no_gear_mismatches": gear_mismatches == 0,
        "all_frames_accepted": stats.frames > 0 and stats.accepted == stats.frames,
        "trip_clamps_all_zero": all(n == 0 for n in clamps.values()),
    }


def verify(log: Path, seed: int, contract: Any = None) -> Dict[str, Any]:
    """Read a log back with python-can and decode it with cantools; compare with the model for the
    seed; judge every dynamics sample through vssframe and the reference rules; compare python-can's
    writer with this module's. `ok` needs every term of verify_terms."""
    su = setup(contract)
    trip = simulate(seed, su.contract)
    db = load_dbc(su)
    raw = log.read_bytes()
    msgs = read_log(log)
    by_id = {db.get_message_by_name(n).frame_id: n for n in (su.dyn_msg, su.gear_msg)}
    counts: Dict[str, int] = {n: 0 for n in by_id.values()}
    last_us: Dict[str, int] = {}
    period_errors = 0
    decoded_stream: List[Tuple[int, str, Tuple[Any, ...]]] = []
    lsb = {s.name: s.scale for m in db.messages for s in m.signals}
    worst: Dict[str, float] = {s: 0.0 for s in su.signals[:4]}
    gear_mismatch = 0
    channels = set()
    for ts, cid, data, ch in msgs:
        channels.add(ch)
        name = by_id[cid]
        us = int(round(ts * 1e6))
        if us % 1000:
            raise ValueError("timestamp %r is not on a whole millisecond" % ts)
        t = us // 1000
        if name in last_us and us - last_us[name] != su.periods_ms[name] * 1000:
            period_errors += 1
        last_us[name] = us
        counts[name] += 1
        dec = db.decode_message(cid, data, decode_choices=False)
        if name == su.dyn_msg:
            vals = tuple(float(dec[s]) for s in su.signals[:4])
            model = trip.sample(t)
            for s, got, want in zip(su.signals[:4], vals, model):
                worst[s] = max(worst[s], abs(got - want))
            decoded_stream.append((t, name, vals))
        else:
            g = int(dec[su.signals[4]])
            gear_mismatch += int(g != trip.gear[t])
            decoded_stream.append((t, name, (g,)))
    expected = {n: len(sample_times(trip, n)) for n in counts}
    quant_ok = quantised_within_half_lsb(worst, lsb)
    ours = candump_text(encode_frames(trip, db))
    theirs = python_can_writer_text(encode_frames(trip, db))
    diff = None
    if ours != theirs:
        for a, b in zip(ours.splitlines(), theirs.splitlines()):
            if a != b:
                diff = [a, b]
                break
    stats = judge_stream(decoded_stream, su)
    identical = raw == ours.encode("ascii")
    terms = verify_terms(regenerated_identical=identical, per_message=counts, expected=expected, period_errors=period_errors,
                         within_half_lsb=quant_ok, gear_mismatches=gear_mismatch, stats=stats, clamps=trip.clamps)
    return {
        "log": str(log), "log_sha256": hashlib.sha256(raw).hexdigest(), "log_bytes": len(raw),
        "regenerated_identical": identical,
        "python_can_reader": {"frames": len(msgs), "channels": sorted(str(c) for c in channels),
                              "per_message": counts, "expected_per_message": expected, "period_errors": period_errors},
        "cantools_decode": {"max_abs_error": worst, "half_lsb": {s: lsb[s] / 2 for s in worst}, "within_half_lsb": quant_ok,
                            "gear_mismatches": gear_mismatch},
        "python_can_writer": {"identical": ours == theirs, "first_difference": diff},
        "judge": stats.as_dict(),
        "trip_clamps": dict(trip.clamps),
        "ok_terms": terms,
        "ok": all(terms.values()),
    }


def scenario_entry(name: str, path: str, sha: str, trip: Trip) -> Dict[str, Any]:
    """The recording's manifest line, shaped like a host-manifest scenario entry (without the
    signal-ownership table, which Phase 1 step 6, the provider run, writes)."""
    su = trip.setup
    return {
        "name": name,
        "recording": {"path": path, "sha256": sha, "format": "candump-log"},
        "source": {"generator": "sigsim", "vehicle": {"name": su.profile["source_vehicle"], "wheelbase_mm": su.wheelbase_mm},
                   "params": {"seed": trip.params.seed,
                              "sigsim_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              "dbc_sha256": hashlib.sha256(DBC_PATH.read_bytes()).hexdigest(),
                              "catalog_digest": "0x%08X" % su.contract.CATALOG_DIGEST,
                              "timestamps": "simulation time from zero"}},
        "profile_id": su.profile_id,
    }


def _mark_failed(out_dir: Path) -> Path:
    """Rename a recording directory that did not verify to <name>.failed (then .failed2, ...): nothing
    complete-looking is left under its name, and the name is free for a re-record."""
    target = out_dir.with_name(out_dir.name + ".failed")
    n = 1
    while target.exists():
        n += 1
        target = out_dir.with_name("%s.failed%d" % (out_dir.name, n))
    out_dir.rename(target)
    return target


def record(seed: int, out_dir: Path, name: str, manifest_path: Optional[str] = None) -> Dict[str, Any]:
    """Write a recording: the log and its sha256, then verify it, then -- only if every term of verify's ok
    holds -- the manifest line Phase 1 step 6 consumes. A recording that fails verification is renamed
    <name>.failed and carries no manifest line. summary.json (with the verification) is written for either
    verdict, but not when verify itself raises: then nothing follows the log and its sha256. Anything else
    that stops the record once the directory exists -- a failed write of the log or its sha256, verify
    raising, an interrupt (BaseException), a failed write of the manifest line or of a summary -- takes the
    manifest line away, renames the directory the same way and re-raises, so nothing complete-looking is left
    under <name> and the name is free for a re-record. The directory's own creation is outside that: a
    directory that already exists is somebody's recording and is left alone (FileExistsError)."""
    su = setup()
    trip = simulate(seed, su.contract)
    db = load_dbc(su)
    text = candump_text(encode_frames(trip, db))
    out_dir.mkdir(parents=True, exist_ok=False)          # outside the try: a failure here is not ours to rename
    manifest = out_dir / MANIFEST_NAME
    try:
        log = out_dir / LOG_NAME
        log.write_bytes(text.encode("ascii"))
        sha = hashlib.sha256(log.read_bytes()).hexdigest()
        (out_dir / (LOG_NAME + ".sha256")).write_text("%s  %s\n" % (sha, LOG_NAME), encoding="ascii")
        ver = verify(log, seed, su.contract)
        if ver["ok"]:
            entry = scenario_entry(name, manifest_path or str(log), sha, trip)
            manifest.write_text(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
            result = {"name": name, "dir": str(out_dir), "recorded": True, "trip": summary(trip), "verify": ver}
            (out_dir / SUMMARY_NAME).write_text(json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="ascii")
            return result
        final = _mark_failed(out_dir)
        result = {"name": name, "dir": str(final), "recorded": False, "trip": summary(trip), "verify": ver}
        (final / SUMMARY_NAME).write_text(json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="ascii")
        return result
    except BaseException:
        if out_dir.is_dir():                             # not when the failed verdict's rename already happened
            manifest.unlink(missing_ok=True)
            _mark_failed(out_dir)
        raise


def _seen(m: Any) -> Tuple[int, bool, bool, bytes]:
    """What live --check keeps of a received frame: its id, whether it is an extended-id or a remote frame, and its data."""
    return (m.arbitration_id, bool(m.is_extended_id), bool(m.is_remote_frame), bytes(m.data))


def live(seed: int, channel: str, seconds: Optional[float], check: bool) -> Dict[str, Any]:
    """Send the trip onto a SocketCAN channel at the log's pace (wall clock; no timing claim). With check,
    a second socket on the channel records everything it receives -- the id, whether the frame is extended
    or remote, and the data -- until CHECK_TAIL_S after the last frame sent, and compares that with what was
    sent, so `ok` needs at least one frame sent, every frame received unchanged and in order, and nothing
    else: the channel must carry no other traffic during --check (a foreign frame fails it), and a
    foreign frame that comes after the tail is not seen."""
    import can
    su = setup()
    trip = simulate(seed, su.contract)
    frames = encode_frames(trip, load_dbc(su))
    if seconds is not None:
        frames = [f for f in frames if f[0] <= seconds * 1000]
    rx = can.Bus(interface="socketcan", channel=channel) if check else None
    tx = can.Bus(interface="socketcan", channel=channel)
    got: List[Tuple[int, bool, bool, bytes]] = []
    try:
        t0 = time.monotonic()
        for t, cid, data in frames:
            wait = t0 + t / 1000.0 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            tx.send(can.Message(arbitration_id=cid, is_extended_id=False, data=data))
            if rx is not None:
                while True:
                    m = rx.recv(timeout=0)
                    if m is None:
                        break
                    got.append(_seen(m))
        if rx is not None:
            deadline = time.monotonic() + CHECK_TAIL_S
            while time.monotonic() < deadline:
                m = rx.recv(timeout=0.1)
                if m is not None:
                    got.append(_seen(m))
    finally:
        tx.shutdown()
        if rx is not None:
            rx.shutdown()
    out: Dict[str, Any] = {"channel": channel, "seed": seed, "sent": len(frames)}
    if check:
        out["received"] = len(got)
        out["identical"] = got == [(cid, False, False, d) for _t, cid, d in frames]
        out["ok"] = len(frames) > 0 and len(got) == len(frames) and out["identical"]    # main() exits 1 unless this holds
    return out


def _suffix(text: str) -> str:
    """argparse type of record --suffix: [a-z][a-z0-9]{0,7}. A letter first, so the suffix never extends the seed
    into another seed's digits (--seed 1 --suffix 2 would otherwise be the name of --seed 12)."""
    if not SUFFIX_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError("%r is not [a-z][a-z0-9]{0,7}" % text)
    return text


def _real_date(text: str) -> bool:
    """YYYYMMDD: eight ASCII digits that are a calendar date (str.isdigit() accepts other scripts' digits, and strptime takes
    them in the year, so the ASCII test is not redundant)."""
    if len(text) != 8 or not (text.isascii() and text.isdigit()):
        return False
    try:
        datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return False
    return True


def log_path_shown(out_dir: Path) -> Optional[str]:
    """The path the manifest line gives for the log when the recording lies under DEFAULT_ROOT: DEFAULT_ROOT's own ~
    spelling and the rest of the path, whatever the command line called the directory (a shell-expanded --root
    included). None for a recording anywhere else: the manifest line then keeps the path record writes to."""
    try:
        rest = out_dir.expanduser().resolve().relative_to(DEFAULT_ROOT.expanduser().resolve())
    except ValueError:
        return None
    return str(DEFAULT_ROOT / rest / LOG_NAME)


def inside_repo(path: Path) -> bool:
    """True when `path` lies in the repository tree other than under sdv-out/ (which git ignores as a whole):
    a recording written there would leave untracked files in the tree. Compared after resolving both."""
    p = path.expanduser().resolve()
    root = REPO.resolve()
    if p != root and root not in p.parents:
        return False
    ignored = root / "sdv-out"
    return not (p == ignored or ignored in p.parents)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="the trip's design timeline (no cantools needed)")
    s.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r = sub.add_parser("record", help="write a recording directory: log, sha256 file, manifest line, summary")
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    r.add_argument("--out", type=Path, help="write exactly here instead of ROOT/<date>-sigsim-<seed>[SUFFIX]")
    r.add_argument("--date", help="YYYYMMDD for the recording's name (default: today, UTC)")
    r.add_argument("--suffix", type=_suffix, help="[a-z][a-z0-9]{0,7}, appended to the name (<date>-sigsim-<seed>S): a re-record of the "
                   "same seed on the same day, into a directory of its own (a letter first: it never extends the seed)")
    v = sub.add_parser("verify", help="read a log back with python-can and cantools and judge it")
    v.add_argument("log", type=Path)
    v.add_argument("--seed", type=int, required=True)
    li = sub.add_parser("live", help="send the trip onto a SocketCAN channel at the log's pace")
    li.add_argument("--seed", type=int, default=DEFAULT_SEED)
    li.add_argument("--channel", default=CHANNEL)
    li.add_argument("--seconds", type=float, help="send only the first S seconds of the trip")
    li.add_argument("--check", action="store_true", help="receive on a second socket and compare ids and data")
    d = sub.add_parser("dbc", help="load slice.dbc with cantools and describe it")
    d.add_argument("--dbc", type=Path, help="describe this DBC instead of slice.dbc (it is still checked against the contract)")
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        res: Any = summary(simulate(a.seed))
    elif a.cmd == "record":
        date = a.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        if not _real_date(date):
            ap.error("--date must be YYYYMMDD, a calendar date in ASCII digits")
        name = "%s-sigsim-%d%s" % (date, a.seed, a.suffix or "")
        if not NAME_PATTERN.fullmatch(name):
            ap.error("the recording's name %r is not [a-z0-9][a-z0-9-]{0,47}: use a shorter --seed or no --suffix" % name)
        root = a.root.expanduser()
        out = a.out.expanduser() if a.out else root / name
        if inside_repo(out):
            ap.error("%s is inside the repository: a recording belongs outside it (only sdv-out/, which git ignores, is allowed)" % out)
        res = record(a.seed, out, name, log_path_shown(out))
    elif a.cmd == "verify":
        res = verify(a.log.expanduser(), a.seed)
    elif a.cmd == "live":
        res = live(a.seed, a.channel, a.seconds, a.check)
    else:
        res = dbc_description(setup(), a.dbc.expanduser() if a.dbc else None)
    print(json.dumps(res, sort_keys=True, indent=1))
    if isinstance(res, dict) and res.get("verify", res).get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
