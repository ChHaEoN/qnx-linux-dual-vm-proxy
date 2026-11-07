"""ctlrules.py -- the Python reference judge of kind 2 (sdv/ctl): reasons 8, 9, 10 and 11-19. CI only.

The rules are the Phase 8 specification's 2.3 (the project's local design notes; not
in this tree); this module is the oracle the C monitor's check_ctl() (WP1a) is compared with, frame by frame, in the
integration stage's contract test. So it reads the payload bytes itself (never through ctlframe's decode, which
refuses what rule 10 must judge), evaluates in the specification's order and returns the first failure:

    order: 10, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19; the first failure wins; every comparison strict (a value
    exactly at a limit is accepted); stateless (v1).

    10  b4..b7 set; any byte of p[8..23] non-zero; p[47] non-zero; an undefined slot (25..28 without b0, 29..32
        without b1, 37..40 without b2, 41..44 without b3) not all zero bytes
    8   p[1] is no compiled kind 2 profile
    9   v_cmd, delta, or a defined slot among acceleration, jerk, steering rate and v_meas, with all exponent bits set
    11  p[45..46] > DT_MAX_MS
    12  |v_cmd| > v_max                     13  b0 and |a| > a_max          14  b1 and |j| > jerk_max
    15  |delta| > steer_max                 16  b2 and |rate| > steer_rate_max
    17  b3 and v_meas * v_meas * tan(|delta|) / L_m > lat_acc_max + TOL17, in double in that operation order, tan =
        sdv/frame/rules.py's vss_tan (the polynomial the C monitor's vss_tan uses), L_m = l_mm * M_PER_MM
    18  b3 and |v_meas| > OVERSPEED_FACTOR * |v_cmd| + OVERSPEED_MARGIN
    19  b3 and v_meas < -ROLLBACK_V and v_cmd >= 0

Every f32 is widened to double exactly before any arithmetic. Every compiled profile has 0 < steer_max <= 1.0 rad
(ctlframe.load_contract refuses anything else), and rule 15 runs first, so vss_tan only ever sees [0, 1]. The
constants and the profile table come from the kind 2 contract; M_PER_MM is the kind 4 generated contract's (it reaches
the C monitor as VSS_M_PER_MM, from vss_contract.h), unless a caller passes its own.

Nothing in the claim node imports this module (tests/test_sdv_ctl.py holds that): the node packs and sends, the
monitor judges, and this judge exists to check the monitor.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_FRAME_DIR = _HERE.parents[1] / "sdv" / "frame"
for _p in (str(_HERE), str(_FRAME_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import ctlframe as cf  # noqa: E402
import rules  # noqa: E402  -- sdv/frame/rules.py: vss_tan only

# The optional slots and the flag that defines each (rule 10's undefined-slot check, rule 9's defined slots).
_OPTIONAL = ((cf.F_ACCEL, cf.P_ACCEL), (cf.F_JERK, cf.P_JERK), (cf.F_RATE, cf.P_RATE), (cf.F_ODOM, cf.P_V_MEAS))


def default_m_per_mm() -> float:
    """M_PER_MM of the kind 4 generated contract (sdv-out/gen/vss_contract.py; SDV_GEN names another directory)."""
    return float(rules.vf.load_contract().M_PER_MM)


def dabs(x: float) -> float:
    """The C monitor's `x < 0.0 ? -x : x` (sdv/frame/rules.py's)."""
    return rules.dabs(x)


def lat_accel(v_meas: float, delta: float, l_mm: int, m_per_mm: float) -> float:
    """Rule 17's left side: v_meas * v_meas * tan(|delta|) / L_m, in double, in that order, L_m = l_mm * M_PER_MM."""
    l_m = float(l_mm) * m_per_mm
    return v_meas * v_meas * rules.vss_tan(dabs(delta)) / l_m


def _u32(p: bytes, off: int) -> int:
    return struct.unpack_from("<I", p, off)[0]


def _f32(p: bytes, off: int) -> float:
    return struct.unpack_from("<f", p, off)[0]


def _nonfinite(p: bytes, off: int) -> bool:
    return ((_u32(p, off) >> 23) & 0xFF) == 0xFF


def check_ctl(payload: bytes, contract: Any, m_per_mm: float) -> Tuple[int, int]:
    """(verdict, reason) of one kind 2 payload (48 bytes), in 2.3's order."""
    p = bytes(payload)
    if len(p) != cf.FRAME_PAYLOAD_BYTES:
        raise ValueError("payload of %d bytes, not %d" % (len(p), cf.FRAME_PAYLOAD_BYTES))
    f = p[cf.P_FLAGS]
    # 10
    if (f & cf.F_RESERVED) or any(p[cf.STAMP_SPAN[0]:cf.STAMP_SPAN[1]]) or p[cf.P_RESERVED] \
            or any(not f & flag and any(p[off:off + 4]) for flag, off in _OPTIONAL):
        return cf.V_REJECT, cf.RSN_FLAGS_INVALID
    # 8
    pid = p[cf.P_PROFILE]
    if pid not in tuple(contract.COMPILED_PROFILE_IDS):
        return cf.V_REJECT, cf.RSN_PROFILE_UNBOUND
    pr = contract.PROFILES[pid]
    # 9
    if _nonfinite(p, cf.P_V_CMD) or _nonfinite(p, cf.P_DELTA) or any(f & flag and _nonfinite(p, off) for flag, off in _OPTIONAL):
        return cf.V_REJECT, cf.RSN_NOT_FINITE
    # 11
    if struct.unpack_from("<H", p, cf.P_INTERVAL)[0] > contract.DT_MAX_MS:
        return cf.V_REJECT, cf.RSN_CTL_INTERVAL
    v_cmd, a, j = _f32(p, cf.P_V_CMD), _f32(p, cf.P_ACCEL), _f32(p, cf.P_JERK)
    delta, rate, v_meas = _f32(p, cf.P_DELTA), _f32(p, cf.P_RATE), _f32(p, cf.P_V_MEAS)
    # 12 .. 16
    if dabs(v_cmd) > pr["v_max"]:
        return cf.V_REJECT, cf.RSN_CTL_SPEED
    if (f & cf.F_ACCEL) and dabs(a) > pr["a_max"]:
        return cf.V_REJECT, cf.RSN_CTL_ACCEL
    if (f & cf.F_JERK) and dabs(j) > pr["jerk_max"]:
        return cf.V_REJECT, cf.RSN_CTL_JERK
    if dabs(delta) > pr["steer_max"]:
        return cf.V_REJECT, cf.RSN_CTL_STEER
    if (f & cf.F_RATE) and dabs(rate) > pr["steer_rate_max"]:
        return cf.V_REJECT, cf.RSN_CTL_STEER_RATE
    if f & cf.F_ODOM:
        # 17
        if lat_accel(v_meas, delta, pr["l_mm"], m_per_mm) > pr["lat_acc_max"] + contract.TOL17:
            return cf.V_REJECT, cf.RSN_CTL_LAT_ACCEL
        # 18
        if dabs(v_meas) > contract.OVERSPEED_FACTOR * dabs(v_cmd) + contract.OVERSPEED_MARGIN:
            return cf.V_REJECT, cf.RSN_CTL_OVERSPEED
        # 19
        if v_meas < -contract.ROLLBACK_V and v_cmd >= 0.0:
            return cf.V_REJECT, cf.RSN_CTL_ROLLING_BACK
    return cf.V_ACCEPT, cf.RSN_OK


def judge(frame: bytes, contract: Any, m_per_mm: Optional[float] = None) -> Optional[Tuple[int, int]]:
    """(verdict, reason) of a 64-byte kind 2 request; None for a sentinel (echoed, never judged).

    Only kind 2 is this oracle's: any other kind byte is a ValueError (the monitor answers an unknown kind with
    reason 5, and its kinds 0, 1 and 4 are outside this module). The verdict and reason bytes of the request are not
    read: the monitor overwrites them."""
    frame = bytes(frame)
    if len(frame) != cf.FRAME_TOTAL_BYTES:
        raise ValueError("frame of %d bytes, not %d" % (len(frame), cf.FRAME_TOTAL_BYTES))
    if struct.unpack_from("<Q", frame, 0)[0] == cf.SENTINEL_SEQ:
        return None
    payload = frame[cf.FRAME_HEADER_BYTES:]
    if payload[cf.P_KIND] != cf.KIND_CTL:
        raise ValueError("kind %d is not kind 2" % payload[cf.P_KIND])
    return check_ctl(payload, contract, default_m_per_mm() if m_per_mm is None else m_per_mm)
