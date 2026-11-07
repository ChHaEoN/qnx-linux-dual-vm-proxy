"""worldtie.py -- the world settings a CARLA take runs under (sdv/carla), pure: what the capture applies and reads back,
and what the encoder checks the take's record against.

Local branch only (decision 15). Phase 7 spec 4 item 2 and 2.2's world_settings. The capture (carla_capture.py, on
Windows) and the encoder (encode.py, in WSL) both import this module, so the two hold one list of settings and one
substep; and so will the later live sender.

    THE TIE    synchronous mode; fixed_delta_seconds = the generated CARLA_STEP_MS / 1000; the physics substep on, at
               SUBSTEP_S, with max_substeps the least whole number of substeps that covers the step (max_substeps x
               SUBSTEP_S >= the step, as CARLA requires of fixed_delta_seconds). Each is applied and read back, and a
               take is refused when any read-back differs (tie_problems). no_rendering_mode is read back and recorded,
               never set.
    RECORDED   capture.json's world_settings holds exactly READ_BACK, as read back. LibCarla warns on stderr when
               max_substeps is outside the range its client checks (the generated step at SUBSTEP_S is outside it); the
               server honours the value (WP0's substep probe, local notes), so the capture records the warning's text
               beside the settings and does not refuse on it.

DOES NOT SHOW: that CARLA's physics is right at this substep, or that another CARLA build keeps honouring a substep
count outside its client's range; only that the settings a take ran under are the ones named here.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping

# PROBED (wp0-facts 3.1, 5.9-5.11, 5.17; the owner's decision on the stop): the physics substep [s]. A design value: at
# CARLA's default substep the reported yaw rate carries a phantom on a coast and every stop a spike past a_max, and the
# in-range substep the client accepts still spikes at the stop; at this one neither shows (WP0's probes, local notes).
SUBSTEP_S = 0.002
READ_BACK = ("synchronous_mode", "fixed_delta_seconds", "no_rendering_mode", "substepping", "max_substep_delta_time",
             "max_substeps")
FLOAT_TOL = 1e-9          # the two floats of the tie compare within this: a double read back across the RPC, not a sum


def max_substeps(step_s: float) -> int:
    """The least whole number of SUBSTEP_S substeps that covers one step of step_s seconds."""
    if not step_s > 0:
        raise ValueError("the step must be > 0 s, not %r" % (step_s,))
    return max(1, int(math.ceil(step_s / SUBSTEP_S - FLOAT_TOL)))


def wanted(step_s: float) -> Dict[str, Any]:
    """The five settings the capture applies, by name (no_rendering_mode is never set)."""
    return {"synchronous_mode": True, "fixed_delta_seconds": step_s, "substepping": True,
            "max_substep_delta_time": SUBSTEP_S, "max_substeps": max_substeps(step_s)}


def read_back(settings: Any) -> Dict[str, Any]:
    """READ_BACK of a carla.WorldSettings (or anything with those attributes), as plain values."""
    return {"synchronous_mode": bool(settings.synchronous_mode), "fixed_delta_seconds": settings.fixed_delta_seconds,
            "no_rendering_mode": bool(settings.no_rendering_mode), "substepping": bool(settings.substepping),
            "max_substep_delta_time": settings.max_substep_delta_time, "max_substeps": settings.max_substeps}


def _float_is(x: Any, want: float) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and abs(float(x) - want) <= FLOAT_TOL


def tie_problems(got: Mapping[str, Any], step_s: float) -> List[str]:
    """Every setting of the tie that `got` (a read-back, or a take's recorded world_settings) does not hold."""
    out = []
    want = wanted(step_s)
    for key in ("synchronous_mode", "substepping"):
        if got.get(key) is not True:
            out.append("%s %r, not True" % (key, got.get(key)))
    for key in ("fixed_delta_seconds", "max_substep_delta_time"):
        if not _float_is(got.get(key), want[key]):
            out.append("%s %r, not %r" % (key, got.get(key), want[key]))
    n = got.get("max_substeps")
    if isinstance(n, bool) or not isinstance(n, int) or n != want["max_substeps"]:
        out.append("max_substeps %r, not %r" % (n, want["max_substeps"]))
    missing = [k for k in READ_BACK if k not in got]
    if missing:
        out.append("not read back: %s" % ", ".join(missing))
    return out
