"""drive.py -- the CARLA take's drive: the route, its controller, the segments, their gears and the commands (sdv/carla), pure.

Local branch only (decision 15). Phase 7 spec 4 item 3 as the owner's option (a) of 2026-10-17 changes it (wp0-facts 3.2,
decisions.md): the feeder drives the ego itself on a fixed route with its own controller, so the envelope's steering rate
and the drive's decelerations are limits the drive enforces; no Traffic Manager runs (wp0-facts F1: on this PC's driver
every Traffic Manager run hung). Then the feeder scripts one hard brake to a stop, a settle at standstill, a short
reverse and a stop, so the stack's window oracle finds exactly one hard brake, rule 27 and the injector's gear event a
direction change. The segments are named as sigsim names its own ("hard brake", "stopped", ...), so
sdv/stack/replaycheck.py reads a CARLA trip unchanged.

    segment             gear  what the capture does
    start                0    holds the ego at a standstill after the spawn (start_hold_s), brake held
    route drive          1    the route controller drives (ROUTE): it launches against the brake, follows the route's
                              reference path with a rate-limited steer and its speed plan with a PI loop
    hard brake           1    the brake (hard_brake), steer 0, entered at the first step at which turns_before_brake
                              junction turns are passed, the reference path is straight for brake_straight_m ahead, and
                              the speed has been inside entry_speed_band with |steer| below entry_abs_steer_max for
                              brake_hold_s; held until the speed is below the stop speed (with hard_brake_stage2 =
                              (speed, brake), the brake is lowered once below that speed)
    stopped              0    brake held (stopped_brake) for stopped_hold_s
    reverse             -1    reverse set, throttle (reverse_throttle) for reverse_s
    reverse stop        -1    reverse kept, the brake (reverse_stop_brake) until the speed is below the stop speed
    stopped in reverse  -1    brake held, reverse kept, for final_hold_s; then the take ends

The declared gears are what spec 2.7's gear rule checks against `reverse`; CARLA's own gearbox gear (it reads 1 while
stopped after the hard brake) enters only the controller's launch.

THE ROUTE (build_route, reference): from the spawn waypoint, waypoints chained at ROUTE.spacing_m by the map's next(); at
each branch the next kind of ROUTE.turn_sequence (left, straight or right by the heading change branch_probe_m on),
falling back in ROUTE.turn_fallback's order when a kind is absent. The reference path is the lane centre averaged over
+-smooth_half_m; its curvature gives a feed-forward wheel angle atan(L kappa) (L the ego's wheelbase as the capture
reads it) and a speed plan: v_cruise on straights, sqrt(ay_drive / kappa) in turns but at least v_turn_min, slowed until
the planned wheel rate is at most rate_plan_deg_s (never below v_floor), accelerating at a_lim and decelerating at
d_lim, from 0 at the start. The spawn is the spawn point with the longest straight lane ahead (spawn_choice; the first on
a tie): the route WP0's trial drove starts there.

THE CONTROLLER (Driver, each route-drive step, from the readings of the step before): the front axle's nearest reference
point; the wanted wheel angle = the feed-forward + k_heading x the heading error - atan(k_cte x the cross-track error /
(|v| + 1)); the steer moves toward it by at most steer_rate_deg_s (in wheel degrees, deg_per_steer per unit steer) and
stays within steer_abs_max; the speed reference is the plan's least value just ahead; a PI loop gives the throttle
(capped at thr_max, rising by at most thr_rate per second) or the brake (capped at brake_max). The launch: throttle
launch_engage[0] against brake launch_engage[1] until the gearbox reads gear 1, then the brake released by
launch_engage[2] a step, the throttle at most launch_throttle until launch_until m/s.

The stop speed is the capture's: half an LSB of the speed signal (the generated contract's DBC_HALF_LSB), so a step read
as stopped carries an exact zero in the log. Durations count simulation steps (a duration over the generated step,
rounded). DriveError stops a take: no hard brake within drive_max_s, the ego stuck (|v| below stuck_speed while the
throttle is above stuck_throttle for stuck_s), the route's end reached, or a take longer than max_take_s.

DRIVE and ROUTE are design values, each with its reason; they are the values WP0's route trial ran (wp0-facts 3.2, local
notes) and no figure measured there is written here.

DOES NOT DEMONSTRATE: vehicle dynamics or a driver: the controller is a test drive's, made to stay inside the envelope,
and that it holds on another route or map, or at other speeds, is not shown (WP0's trial drove one route).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SEGMENTS = ("start", "route drive", "hard brake", "stopped", "reverse", "reverse stop", "stopped in reverse")
SEGMENT_GEAR = {"start": 0, "route drive": 1, "hard brake": 1, "stopped": 0, "reverse": -1, "reverse stop": -1,
                "stopped in reverse": -1}
TURN_KINDS = ("left", "straight", "right")
KAPPA_HALF_PTS = 2        # the curvature: the heading change over +-2 reference points (WP0's trial)
RATE_HALF_PTS = 3         # the speed plan's rate cap: the steepest feed-forward slope within +-3 points (WP0's trial)
STRAIGHT_PROBE_M = 2.0    # spawn_choice walks a lane in steps of this many metres ...
STRAIGHT_LIMIT_M = 300.0  # ... up to this far ...
STRAIGHT_TOL_DEG = 0.5    # ... while its heading stays within this of the start's and no junction comes
ROUTE_END_M = 10.0        # the route's end: within this of its last point (WP0's trial)


@dataclass(frozen=True)
class DriveValues:
    start_hold_s: float                  # standstill after the spawn, before the route drive
    turns_before_brake: int              # junction turns the route drive passes before the hard brake may enter
    brake_straight_m: float              # ... with the reference path straight for this far ahead
    entry_abs_steer_max: float           # ... and |steer| below this
    entry_speed_band: Tuple[float, float]   # ... and the speed [m/s] inside this band
    brake_hold_s: float                  # ... both held for this long
    drive_max_s: float                   # no hard brake within this long in the route drive stops the take
    stuck_s: float                       # |v| below stuck_speed with the throttle above stuck_throttle this long stops it
    hard_brake: float                    # the hard brake's brake value
    hard_brake_stage2: Optional[Tuple[float, float]]   # (speed [m/s], brake): lowered once below it, or None
    stopped_hold_s: float                # the settle at standstill before the reverse
    stopped_brake: float                 # the brake held at a standstill
    reverse_throttle: float              # the reverse's throttle
    reverse_s: float                     # the reverse's duration
    reverse_stop_brake: float            # the brake that stops the reverse
    final_hold_s: float                  # the final hold, long enough for the injector's stop run
    max_take_s: float                    # a take is stopped when it runs longer than this


@dataclass(frozen=True)
class RouteValues:
    spacing_m: float                     # the route's point spacing
    length_m: float                      # the route's length
    turn_sequence: Tuple[str, ...]       # the kind taken at each branch, in turn (cycled)
    turn_fallback: Tuple[str, ...]       # the order tried when a kind is absent at a branch
    branch_probe_m: float                # a branch's kind is its heading change this far into it ...
    branch_turn_deg: float               # ... a turn beyond this many degrees, straight otherwise
    smooth_half_m: float                 # the reference path: the lane centre averaged over +- this
    v_cruise: float                      # the plan's speed on straights [m/s]
    ay_drive: float                      # the plan's cornering bound [m/s^2]
    v_turn_min: float                    # no turn planned slower than this [m/s] ...
    rate_plan_deg_s: float               # ... unless its planned wheel rate exceeds this [deg/s]
    v_floor: float                       # ... and never below this [m/s]
    a_lim: float                         # the plan's acceleration [m/s^2]
    d_lim: float                         # the plan's deceleration [m/s^2]
    steer_rate_deg_s: float              # the steer's rate limit in wheel degrees [deg/s]
    deg_per_steer: float                 # wheel degrees per unit steer near the centre
    steer_abs_max: float                 # |steer| at most this
    k_heading: float                     # feedback on the heading error [deg/deg]
    k_cte: float                         # feedback on the front axle's cross-track error: atan(k e / (|v| + 1))
    kp: float                            # the PI speed loop's gains (per m/s; per m)
    ki: float
    thr_max: float                       # the throttle's cap ...
    thr_rate: float                      # ... and its rise per second
    launch_throttle: float               # the throttle's cap until launch_until [m/s]
    launch_until: float
    launch_engage: Tuple[float, float, float]   # (throttle, brake) held until the gearbox reads gear 1, then the brake's
                                                # release per step
    brake_max: float                     # the drive's brake cap
    lookahead_s: float                   # the speed reference: the plan's least value over |v| x this ...
    lookahead_extra_m: float             # ... plus this many metres ahead
    nearest_window_m: float              # the nearest reference point is searched this far ahead of the last
    turn_passed_m: float                 # a junction turn counts as passed this far past the branch
    straight_tol_deg: float              # "straight ahead": the reference heading within this for brake_straight_m
    stuck_speed: float                   # the stuck rule's speed [m/s] ...
    stuck_throttle: float                # ... and throttle


# PROBED (wp0-facts 3.2: the owner's option (a), WP0's route trial; local notes): the drive's values. Design values, none a
# reading; each reason is the trial's (local notes), never a figure it measured.
DRIVE = DriveValues(
    start_hold_s=2.0,                    # the spawn's drop settles in it
    turns_before_brake=5,                # the route's first junction turns, then a straight
    brake_straight_m=40.0,               # room for the hard brake and its stop on the straight
    entry_abs_steer_max=0.02,            # the hard brake enters straight ahead
    entry_speed_band=(6.7, 7.3),         # around the cruise: the entry speed from which the trial held the hard brake's
                                         # deceleration long enough with every step inside a_max
    brake_hold_s=1.0,                    # the band and the straight steer held this long first
    drive_max_s=480.0,                   # well past the route trial's own route drive
    stuck_s=3.0,                         # a launch moves well within this
    hard_brake=0.7,                      # the brake that held the app's switch-on deceleration long enough at 2 ms
    hard_brake_stage2=None,              # one stage: the 2 ms substep removed the stop's spike
    stopped_hold_s=2.0,
    stopped_brake=1.0,
    reverse_throttle=0.3,                # a reverse under the reverse-speed bound
    reverse_s=3.0,
    reverse_stop_brake=0.3,              # a lighter stop brake lit the hazards in the trial
    final_hold_s=10.0,
    max_take_s=900.0,
)
# PROBED (wp0-facts 3.2: WP0's route trial, ROUTE in phase7/wp0/probes.py; local notes): the route and its controller.
ROUTE = RouteValues(
    spacing_m=1.0,
    length_m=1800.0,                     # the turns before the brake and a straight after them
    turn_sequence=("left", "left", "straight", "left", "left", "straight", "left"),
    turn_fallback=("left", "straight", "right"),   # Town01's right turns are tight: lefts are preferred
    branch_probe_m=15.0,
    branch_turn_deg=45.0,
    smooth_half_m=6.0,                   # a gentle turn entry
    v_cruise=7.0,                        # the hard brake's entry speed
    ay_drive=1.0,                        # half of profile 3's a_y bound
    v_turn_min=2.0,                      # rule 26's window starts below it
    rate_plan_deg_s=6.5,                 # under steer_rate_deg_s, so a turn's planned rate leaves the limiter room
    v_floor=1.0,                         # rule 26's window starts here
    a_lim=0.8,                           # well under the envelope's launch row
    d_lim=1.0,                           # well under the app's switch-off deceleration
    steer_rate_deg_s=8.0,                # under the envelope's steering-rate row
    deg_per_steer=62.5,                  # the wheel angle per unit steer the controller assumes near the centre
                                         # (a design value of WP0's route trial; local notes)
    steer_abs_max=0.9,                   # under profile 3's delta_max at the wheels
    k_heading=0.4,
    k_cte=0.4,
    kp=0.25,
    ki=0.08,
    thr_max=0.5,
    thr_rate=0.4,                        # a gentle throttle: a sharp one jolted the launch
    launch_throttle=0.25,
    launch_until=0.5,
    launch_engage=(0.25, 1.0, 0.1),      # the gearbox engages against the brake, so gear 1 comes in without a jolt
    brake_max=0.25,                      # a light brake: the plan decelerates gently
    lookahead_s=1.0,
    lookahead_extra_m=3.0,
    nearest_window_m=40.0,
    turn_passed_m=20.0,                  # past the junction's turn
    straight_tol_deg=2.0,
    stuck_speed=0.2,
    stuck_throttle=0.2,
)
DRIVE_PENDING_PROBE = False    # WP0's probes settled DRIVE and ROUTE (wp0-facts 3.1-3.2); True would mark them provisional again


class DriveError(RuntimeError):
    """The drive cannot go on as designed (no entry into the hard brake, a stuck ego, the route's end, a take past its cap)."""


@dataclass(frozen=True)
class Command:
    cmd: str                   # "control" (no Traffic Manager: there is no "autopilot" command)
    args: Dict[str, Any]


def values_record(values: DriveValues, route: RouteValues) -> Dict[str, Any]:
    """The drive's values as capture.json records them."""
    return {"drive": asdict(values), "route": asdict(route)}


def pending() -> Dict[str, Any]:
    """The drive's values while they are provisional (DRIVE_PENDING_PROBE), else nothing."""
    return values_record(DRIVE, ROUTE) if DRIVE_PENDING_PROBE else {}


def speed(vec: Sequence[float]) -> float:
    """A velocity vector's magnitude [m/s] (the stop decisions only; the log's speed is carla_iso's)."""
    return math.sqrt(sum(float(x) * float(x) for x in vec))


def control(throttle: float = 0.0, brake: float = 0.0, reverse: bool = False, steer: float = 0.0) -> Command:
    return Command("control", {"throttle": float(throttle), "steer": float(steer), "brake": float(brake), "reverse": bool(reverse),
                               "hand_brake": False, "manual_gear_shift": False})


def wrap180(a: float) -> float:
    return (a + 540.0) % 360.0 - 180.0


def straight_ahead_m(wp: Any) -> float:
    """Metres of lane ahead of a waypoint whose heading stays within STRAIGHT_TOL_DEG of its own, before any junction."""
    yaw0, dist = float(wp.transform.rotation.yaw), 0.0
    while dist < STRAIGHT_LIMIT_M:
        nxt = wp.next(STRAIGHT_PROBE_M)
        if not nxt or nxt[0].is_junction:
            break
        wp = nxt[0]
        if abs(wrap180(float(wp.transform.rotation.yaw) - yaw0)) > STRAIGHT_TOL_DEG:
            break
        dist += STRAIGHT_PROBE_M
    return dist


def spawn_choice(waypoints: Sequence[Any]) -> int:
    """The index of the waypoint with the longest straight lane ahead (the first of equals)."""
    if not waypoints:
        raise DriveError("the map has no spawn point")
    ahead = [straight_ahead_m(w) for w in waypoints]
    return ahead.index(max(ahead))


def _pts(metres: float, spacing: float) -> int:
    return max(1, int(round(metres / spacing)))


def build_route(start_wp: Any, rv: RouteValues) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, str]]]:
    """(points (x, y, yaw), turns (point index, kind)) of the route from start_wp (the module docstring's THE ROUTE)."""
    pts: List[Tuple[float, float, float]] = []
    turns: List[Tuple[int, str]] = []
    wp, k = start_wp, 0
    while len(pts) * rv.spacing_m < rv.length_m:
        t = wp.transform
        pts.append((float(t.location.x), float(t.location.y), float(t.rotation.yaw)))
        nxt = list(wp.next(rv.spacing_m))
        if not nxt:
            break
        if len(nxt) > 1:
            kinds: Dict[str, Any] = {}
            for c in nxt:
                far = c.next(rv.branch_probe_m)
                dy = wrap180(float((far[0] if far else c).transform.rotation.yaw) - float(t.rotation.yaw))
                kind = "right" if dy > rv.branch_turn_deg else ("left" if dy < -rv.branch_turn_deg else "straight")
                kinds.setdefault(kind, c)
            want = rv.turn_sequence[k % len(rv.turn_sequence)]
            k += 1
            order = [want] + [x for x in rv.turn_fallback if x != want]
            got = next((x for x in order if x in kinds), None)
            if got is None:
                raise DriveError("a branch with none of the kinds %s" % ", ".join(order))
            turns.append((len(pts), got))
            nxt = [kinds[got]]
        wp = nxt[0]
    if len(pts) < 2:
        raise DriveError("the route has fewer than two points")
    return pts, turns


@dataclass(frozen=True)
class Reference:
    x: Tuple[float, ...]
    y: Tuple[float, ...]
    yaw: Tuple[float, ...]               # CARLA's: atan2(dy, dx) in degrees, clockwise positive
    kappa: Tuple[float, ...]             # signed curvature [1/m], positive turning right
    dff: Tuple[float, ...]               # the feed-forward wheel angle atan(L kappa) [deg]
    vplan: Tuple[float, ...]             # the speed plan [m/s]
    planned_rate_max: float              # the plan's steepest wheel rate [deg/s]


def reference(pts: Sequence[Tuple[float, float, float]], rv: RouteValues, wheelbase_m: float) -> Reference:
    """The reference path of the route's points (the module docstring's THE ROUTE)."""
    if not wheelbase_m > 0:
        raise ValueError("the wheelbase must be > 0")
    n, h, ds = len(pts), _pts(rv.smooth_half_m, rv.spacing_m), rv.spacing_m
    xs, ys = [], []
    for i in range(n):
        a, b = max(0, i - h), min(n - 1, i + h)
        xs.append(sum(p[0] for p in pts[a:b + 1]) / (b - a + 1))
        ys.append(sum(p[1] for p in pts[a:b + 1]) / (b - a + 1))
    yaw = []
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        yaw.append(math.degrees(math.atan2(ys[b] - ys[a], xs[b] - xs[a])))
    kap = []
    for i in range(n):
        a, b = max(0, i - KAPPA_HALF_PTS), min(n - 1, i + KAPPA_HALF_PTS)
        seg = math.hypot(xs[b] - xs[a], ys[b] - ys[a]) or ds
        kap.append(math.radians(wrap180(yaw[b] - yaw[a])) / seg)
    dff = [math.degrees(math.atan(wheelbase_m * k)) for k in kap]
    v = [rv.v_cruise if abs(k) < 1e-4 else max(rv.v_turn_min, min(rv.v_cruise, math.sqrt(rv.ay_drive / abs(k)))) for k in kap]
    for i in range(n):
        g = max((abs(dff[j + 1] - dff[j]) / ds for j in range(max(0, i - RATE_HALF_PTS), min(n - 1, i + RATE_HALF_PTS))),
                default=0.0)
        if g > 1e-6:
            v[i] = max(rv.v_floor, min(v[i], rv.rate_plan_deg_s / g))
    for i in range(n - 2, -1, -1):
        v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2.0 * rv.d_lim * ds))
    v[0] = 0.0
    for i in range(1, n):
        v[i] = min(v[i], math.sqrt(v[i - 1] ** 2 + 2.0 * rv.a_lim * ds))
    rate = [abs(dff[i + 1] - dff[i]) / ds * max(v[i], v[i + 1]) for i in range(n - 1)]
    return Reference(tuple(xs), tuple(ys), tuple(yaw), tuple(kap), tuple(dff), tuple(v), max(rate, default=0.0))


class Driver:
    """The drive as a state machine over steps: before_step(i, last) returns the commands to apply before step i's tick,
    given the readings of step i - 1 (None before step 0), and sets `segment` to step i's. The readings: "v", "fwd" and
    "loc" ([x, y, z] in CARLA's axes), "yaw" [deg], "steer" and "gear" (the gearbox's, from get_control())."""

    def __init__(self, values: DriveValues, route: RouteValues, ref: Reference, turns: Sequence[Tuple[int, str]], step_s: float,
                 stop_speed: float, wheelbase_m: float) -> None:
        if not step_s > 0 or not stop_speed > 0 or not wheelbase_m > 0:
            raise ValueError("step_s, stop_speed and wheelbase_m must be > 0")
        self.v, self.rv, self.ref, self.turns = values, route, ref, list(turns)
        self.step_s, self.stop_speed, self.L = step_s, stop_speed, wheelbase_m
        self.segment = SEGMENTS[0]
        self.seg_start = 0
        self.done = False
        self.stage2_applied = False
        self.idx, self.steer, self.thr, self.integ = 0, 0.0, 0.0, 0.0
        self.inband = self.stuck = 0
        self.launched = self.engaged = False
        self.release = 0.0

    def steps(self, seconds: float) -> int:
        return max(1, int(round(seconds / self.step_s)))

    def _enter(self, i: int, segment: str) -> None:
        self.segment, self.seg_start = segment, i

    def _route_step(self, last: Mapping[str, Any]) -> Tuple[Command, bool]:
        """One step of the route controller: (its control, whether the hard brake may enter now)."""
        rv, ref, step = self.rv, self.ref, self.step_s
        n = len(ref.x)
        fwd, loc = [float(x) for x in last["fwd"]], [float(x) for x in last["loc"]]
        fx, fy = loc[0] + fwd[0] * self.L / 2.0, loc[1] + fwd[1] * self.L / 2.0          # the front axle
        window = _pts(rv.nearest_window_m, rv.spacing_m)
        self.idx = min(range(self.idx, min(n, self.idx + window)), key=lambda j: (ref.x[j] - fx) ** 2 + (ref.y[j] - fy) ** 2)
        idx = self.idx
        v = sum(float(a) * b for a, b in zip(last["v"], fwd))
        py = math.radians(ref.yaw[idx])
        cte = (fx - ref.x[idx]) * -math.sin(py) + (fy - ref.y[idx]) * math.cos(py)        # > 0: right of the path
        herr = wrap180(ref.yaw[idx] - float(last["yaw"]))                                  # > 0: the path turns right
        ddes = ref.dff[min(n - 1, idx + 1)] + rv.k_heading * herr - math.degrees(math.atan(rv.k_cte * cte / (abs(v) + 1.0)))
        sdes = max(-rv.steer_abs_max, min(rv.steer_abs_max, ddes / rv.deg_per_steer))
        srate = rv.steer_rate_deg_s * step / rv.deg_per_steer
        self.steer += max(-srate, min(srate, sdes - self.steer))
        ahead = ref.vplan[idx + 1:min(n, idx + int(max(v, 0.0) * rv.lookahead_s / rv.spacing_m) + _pts(rv.lookahead_extra_m, rv.spacing_m))]
        vref = min(ahead) if ahead else 0.0
        self.launched = self.launched or v >= rv.launch_until
        e = vref - v
        self.integ = max(0.0, min(rv.thr_max, self.integ + rv.ki * e * step))
        u = rv.kp * e + self.integ
        if u >= 0.0:
            thr, brk = min(u, rv.thr_max, self.thr + rv.thr_rate * step), 0.0
            if not self.launched:
                thr = min(thr, rv.launch_throttle)
        else:
            thr, brk = 0.0, min(-u, rv.brake_max)
        if not self.launched:                           # the launch: engage against the brake, then release it
            e_thr, e_brk, e_step = rv.launch_engage
            if not self.engaged and int(last["gear"]) >= 1:
                self.engaged, self.release = True, e_brk
            if not self.engaged:
                thr, brk = e_thr, e_brk
            else:
                self.release = max(0.0, self.release - e_step)
                thr, brk = (max(thr, e_thr) if self.release > 0.0 else thr), max(brk, self.release)
        self.thr = thr
        margin = _pts(rv.turn_passed_m, rv.spacing_m)
        passed = sum(1 for j, kind in self.turns if kind != "straight" and j < idx - margin)
        span = _pts(self.v.brake_straight_m, rv.spacing_m)
        seg_yaw = ref.yaw[idx:min(n, idx + span)]
        straight = len(seg_yaw) >= span and max(abs(wrap180(y - seg_yaw[0])) for y in seg_yaw) < rv.straight_tol_deg
        lo, hi = self.v.entry_speed_band
        self.inband = self.inband + 1 if (lo <= v <= hi and abs(self.steer) < self.v.entry_abs_steer_max) else 0
        self.stuck = self.stuck + 1 if (abs(v) < rv.stuck_speed and thr > rv.stuck_throttle) else 0
        enter = passed >= self.v.turns_before_brake and straight and self.inband >= self.steps(self.v.brake_hold_s)
        if not enter:
            if self.stuck >= self.steps(self.v.stuck_s):
                raise DriveError("the ego is stuck (|v| below %r m/s with the throttle above %r for %r s)"
                                 % (rv.stuck_speed, rv.stuck_throttle, self.v.stuck_s))
            if idx >= n - _pts(ROUTE_END_M, rv.spacing_m):
                raise DriveError("the route's end was reached before the hard brake could enter")
        return control(throttle=thr, brake=brk, steer=self.steer), enter

    def before_step(self, i: int, last: Optional[Mapping[str, Any]]) -> List[Command]:
        if self.done:
            raise DriveError("the drive has ended; no step %d" % i)
        if i >= self.steps(self.v.max_take_s):
            raise DriveError("the take reached max_take_s (%r s) in segment %r" % (self.v.max_take_s, self.segment))
        v = self.v
        n = i - self.seg_start
        sp = speed(last["v"]) if last is not None else 0.0
        out: List[Command] = []
        if i == 0:
            self._enter(0, "start")
            out.append(control(brake=v.stopped_brake))
        elif self.segment == "start" and n >= self.steps(v.start_hold_s):
            self._enter(i, "route drive")
            assert last is not None
            out.append(self._route_step(last)[0])
        elif self.segment == "route drive":
            assert last is not None
            if n >= self.steps(v.drive_max_s):
                raise DriveError("no entry into the hard brake within drive_max_s (%r s)" % v.drive_max_s)
            cmd, enter = self._route_step(last)
            if enter:
                self._enter(i, "hard brake")
                out.append(control(brake=v.hard_brake))
            else:
                out.append(cmd)
        elif self.segment == "hard brake":
            if sp < self.stop_speed:
                self._enter(i, "stopped")
                out.append(control(brake=v.stopped_brake))
            elif v.hard_brake_stage2 is not None and not self.stage2_applied and sp < v.hard_brake_stage2[0]:
                self.stage2_applied = True
                out.append(control(brake=v.hard_brake_stage2[1]))
        elif self.segment == "stopped" and n >= self.steps(v.stopped_hold_s):
            self._enter(i, "reverse")
            out.append(control(throttle=v.reverse_throttle, reverse=True))
        elif self.segment == "reverse" and n >= self.steps(v.reverse_s):
            self._enter(i, "reverse stop")
            out.append(control(brake=v.reverse_stop_brake, reverse=True))
        elif self.segment == "reverse stop" and sp < self.stop_speed:
            self._enter(i, "stopped in reverse")
            out.append(control(brake=v.stopped_brake, reverse=True))
        if self.segment == "stopped in reverse" and i - self.seg_start + 1 >= self.steps(v.final_hold_s):
            self.done = True
        return out
