"""sendpolicy.py -- the CARLA feeder's pacing decision and frame schedule (sdv/carla), pure functions.

Local branch only (decision 15). slice.dbc DESIGN VALUES (2) and the kind 4 specification (5.5, 16.4) define them;
the capture (carla_capture.py) and the encoder (encode.py) use them, and so will the later live sender. Every number comes
from the generated contract (Policy.from_contract): the step, the pacing interval, the repeat cap, the two messages
and their periods. None is a literal here; the one design value of this module, STEP_QUANT_TOL, is a tolerance on how
a server represents the step, not a number of the policy.

    PACING     a step becomes CURRENT at the later of the moment its readings were complete (t_vals) and one pacing
               interval after the previous step became current (became_current); the next tick only after that, and
               never a catch-up: a step that became current late does not shorten the wait for the next one.
    SCHEDULE   the dynamics message at every instant k x its period from 0, the gear message at every instant k x
               its own, both at 0; each frame filled from the step current at that instant if that step has been
               current for no longer than the repeat cap, otherwise no frame (schedule). The cap counts from the
               moment the step became current, never from its readings. At an equal instant the dynamics message,
               the lower CAN id, comes first. The schedule ends with the last step's repeat window.
    RTF        per step, the snapshot's own elapsed-time advance over the wall time since the previous step became
               current (rtf_per_step), the advance counted in steps (step_advance_ns): one within STEP_QUANT_TOL of a
               whole number of steps is exactly that many steps of the generated length, any other reads as it reads,
               in whole ns (sim_advance_ns). The run's {min, mean, max}: min and max over the steps, mean the total
               simulation time over the total wall time, the total the sum of the same per-step advances, so min <=
               mean <= max holds by construction for steps current in increasing order (rtf_summary; a wall time of
               zero or less has no RTF, and schedule and the encoder refuse such steps).
    GAPS       a step that became current more than the repeat cap after the previous one, or that follows a skipped
               frame number (gaps); a skipped frame is a snapshot frame number that is not the previous one plus one
               (skipped_frames). Both are lists of step indices.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000
SINGLE_ROUNDOFF = 2.0 ** -24      # single precision's unit roundoff: the largest relative error of a value rounded to it
# A design value: how far an elapsed-time advance may lie from a whole number of steps, in steps, and still count as that
# many steps of the generated length. CARLA 0.9.16's server keeps fixed_delta_seconds in single precision and a double
# accumulates it into elapsed_seconds (WP5a's first take, finding F-RTF, local notes), so one step reads up to
# SINGLE_ROUNDOFF of itself off the generated length: that is the step's representation, not the pacing. Sixteen times
# that bound is the round power of two 2^-20 of a step, a margin over the bound (a double's rounding in the accumulated
# time is one ulp of elapsed_seconds, orders below both), and far below a whole step, so a skipped
# frame, a stall or a world on another step still reads as it is. It touches the simulation's side only: the wall time
# is never rounded, so a step made current even 1 ns early reads above 1.
STEP_QUANT_TOL = 16 * SINGLE_ROUNDOFF

StepTime = Tuple[int, int]          # (t_vals_ns, t_cur_ns) of one step, from step 0's t_cur_ns
Frame = Tuple[int, str, int]        # (instant [ms], message name, step index)


@dataclass(frozen=True)
class Policy:
    step_ms: int
    interval_ms: int
    cap_ms: int
    dyn_msg: str
    gear_msg: str
    dyn_period_ms: int
    gear_period_ms: int

    @classmethod
    def from_contract(cls, c: Any) -> "Policy":
        """The policy of the generated contract: CARLA_STEP_MS, FEEDER_PACING_INTERVAL_MS, FEEDER_REPEAT_CAP_MS,
        RULE26_DBC_MESSAGE (the dynamics message), the gear slot's message and DBC_PERIOD_MS."""
        dyn, gear = c.RULE26_DBC_MESSAGE, c.SLOT_DBC_MESSAGES[4]
        if dyn == gear:
            raise ValueError("the dynamics and gear slots share message %r" % dyn)
        return cls(step_ms=int(c.CARLA_STEP_MS), interval_ms=int(c.FEEDER_PACING_INTERVAL_MS), cap_ms=int(c.FEEDER_REPEAT_CAP_MS),
                   dyn_msg=dyn, gear_msg=gear, dyn_period_ms=int(c.DBC_PERIOD_MS[dyn]), gear_period_ms=int(c.DBC_PERIOD_MS[gear]))

    @property
    def interval_ns(self) -> int:
        return self.interval_ms * NS_PER_MS

    @property
    def cap_ns(self) -> int:
        return self.cap_ms * NS_PER_MS

    @property
    def step_ns(self) -> int:
        return self.step_ms * NS_PER_MS

    @property
    def step_s(self) -> float:
        return self.step_ms / 1000.0


def became_current(t_vals_ns: int, prev_t_cur_ns: Optional[int], interval_ns: int) -> int:
    """The moment a step becomes current: the later of t_vals and the previous step's t_cur plus the pacing interval
    (step 0, with no previous step, at t_vals)."""
    if prev_t_cur_ns is None:
        return t_vals_ns
    return max(t_vals_ns, prev_t_cur_ns + interval_ns)


def schedule(steps: Sequence[StepTime], policy: Policy) -> List[Frame]:
    """Every frame of the send policy over the steps, in log order: (instant [ms], message, step index). Step 0 must be
    current at 0 and the steps current in increasing order."""
    t_cur = [c for _v, c in steps]
    if not t_cur or t_cur[0] != 0:
        raise ValueError("step 0 must be current at 0")
    if any(b <= a for a, b in zip(t_cur, t_cur[1:])):
        raise ValueError("steps must become current in increasing order")
    end_ns = t_cur[-1] + policy.cap_ns
    out: List[Tuple[int, int, str, int]] = []
    for order, msg, period in ((0, policy.dyn_msg, policy.dyn_period_ms), (1, policy.gear_msg, policy.gear_period_ms)):
        t_ms = 0
        while t_ms * NS_PER_MS <= end_ns:
            t_ns = t_ms * NS_PER_MS
            cur = bisect.bisect_right(t_cur, t_ns) - 1
            if t_ns - t_cur[cur] <= policy.cap_ns:
                out.append((t_ms, order, msg, cur))
            t_ms += period
    out.sort(key=lambda f: (f[0], f[1]))
    return [(t, msg, i) for t, _o, msg, i in out]


def counts(frames: Sequence[Frame]) -> Dict[str, int]:
    """Frames per message."""
    out: Dict[str, int] = {}
    for _t, msg, _i in frames:
        out[msg] = out.get(msg, 0) + 1
    return out


def sim_advance_ns(earlier_s: float, later_s: float) -> int:
    """The simulation time between two snapshots' elapsed_seconds as it reads, in whole ns (the wall clock's unit)."""
    return int(round((later_s - earlier_s) * NS_PER_S))


def step_advance_ns(earlier_s: float, later_s: float, step_ns: int) -> int:
    """The simulation time between two snapshots' elapsed_seconds, in whole ns, counted in steps of step_ns: an advance
    within STEP_QUANT_TOL of a whole number of steps is exactly that many steps, whether the server keeps its step in
    single precision or a double's rounding makes it read a few ulps long; any other advance reads as it reads."""
    steps = (later_s - earlier_s) * NS_PER_S / step_ns
    n = round(steps)
    if abs(steps - n) <= STEP_QUANT_TOL:
        return n * step_ns
    return sim_advance_ns(earlier_s, later_s)


def advances_ns(elapsed_s: Sequence[float], step_ns: int) -> List[int]:
    """Each step's simulation advance since the previous step (step_advance_ns), from step 1 on."""
    return [step_advance_ns(elapsed_s[k - 1], elapsed_s[k], step_ns) for k in range(1, len(elapsed_s))]


def rtf_per_step(elapsed_s: Sequence[float], t_cur_ns: Sequence[int], step_ns: int) -> List[Optional[float]]:
    """Each step's real-time factor: the snapshot's elapsed-time advance, counted in steps of step_ns, over the wall time
    since the previous step became current (None for step 0, which has no previous step)."""
    out: List[Optional[float]] = [None] if elapsed_s else []
    for k, adv in enumerate(advances_ns(elapsed_s, step_ns), start=1):
        out.append(adv / (t_cur_ns[k] - t_cur_ns[k - 1]))
    return out


def rtf_summary(elapsed_s: Sequence[float], t_cur_ns: Sequence[int], step_ns: int) -> Dict[str, float]:
    """{min, max} over the steps' real-time factors, and mean = the total simulation time over the total wall time, the
    total the sum of the same per-step advances: a mean of the ratios weighted by their wall times, so min <= mean <=
    max (every division is of two integers, correctly rounded, and rounding keeps their order) when every wall time is
    above 0, i.e. the steps became current in increasing order; the caller refuses any other (encode.check_take), since
    a zero wall time divides by zero and a negative one gives a ratio of the wrong sign."""
    per = [r for r in rtf_per_step(elapsed_s, t_cur_ns, step_ns) if r is not None]
    if not per:
        raise ValueError("an RTF needs at least two steps")
    return {"min": min(per), "mean": sum(advances_ns(elapsed_s, step_ns)) / (t_cur_ns[-1] - t_cur_ns[0]), "max": max(per)}


def skipped_frames(frames: Sequence[int]) -> List[int]:
    """The steps whose snapshot frame number is not the previous step's plus one."""
    return [k for k in range(1, len(frames)) if frames[k] - frames[k - 1] != 1]


def gaps(frames: Sequence[int], t_cur_ns: Sequence[int], cap_ns: int) -> List[int]:
    """The steps that became current more than the repeat cap after the previous one, or that follow a skipped frame."""
    skipped = set(skipped_frames(frames))
    return [k for k in range(1, len(t_cur_ns)) if t_cur_ns[k] - t_cur_ns[k - 1] > cap_ns or k in skipped]
