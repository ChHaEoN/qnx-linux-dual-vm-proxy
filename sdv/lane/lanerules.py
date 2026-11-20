"""lanerules.py -- the Python reference judge of kind 6 (sdv/lane): reasons 10, 9, 8 and 28-31.

The rules come from the project's local design notes, not in this tree; this module
is the oracle the C monitor's check_lane() is compared with, frame by frame (tests/test_monitor_lane.py and
tests/test_sdv_lane_contract.py). So it reads the payload bytes itself (never through laneframe's decode, which refuses
what rule 10 must judge), evaluates in the specification's order and returns the first failure:

    order: 10, 9, 8, then a "no lane" claim is accepted, then 28, 29, 30, 31; the first failure wins; every comparison
    strict (a value exactly at a limit is accepted); stateless.

    10  b2..b7 set; any byte of p[8..23] non-zero; LANE clear and a byte of p[1..5] or p[25..36] non-zero; VEH clear
        and a byte of p[37..44] non-zero (-0.0 is not zero bytes)
    9   a present f32 with all exponent bits set: offset, heading, curvature, width when LANE; speed, yaw rate when VEH
    8   p[47] names no profile of the table
    --  LANE clear: ACCEPT
    28  confidence < conf_min, or > 100
    29  width < width_min or > width_max, or |curvature| > k_max, or |heading| > h_max
    30  |offset| > room, room = width / 2 - veh_half_w
    31  VEH and speed > v_min and moving toward the nearer line (vl = speed * lane_sin(heading); vl > 0 when offset > 0,
        vl < 0 when offset < 0, vl != 0 when offset == 0), and room - |offset| < tlc_min * |vl|

Every f32 is widened to double exactly before any arithmetic, and every operation is the C judge's in its order (the
lane builds pass -ffp-contract=off, so neither fuses a multiply-add). lane_sin is the odd Taylor polynomial of sin to
x^9, by Horner in x^2 with the highest power innermost, as monitor.c's lane_sin(); rule 29 keeps |heading| <= h_max <=
0.5 rad before rule 31 takes it, where the polynomial is within 2e-11 of sin.

Nothing in a claim's client needs this module: the client packs and sends, the monitor judges, and this judge exists
to check the monitor.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Mapping, Optional, Tuple

# sdv/lane is no package (an __init__.py would put sdv/ on CI's mypy path): laneframe is imported by name, with this
# module's own directory on sys.path, as sdv/ctl/ctlrules.py imports ctlframe.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import laneframe as lf  # noqa: E402

# The doubles nearest (-1)^k / (2k+1)! for k = 0..4 (x^1, x^3, ..., x^9), printed with %.17g, as monitor.c's lane_sin_c.
SIN_COEFFS = (1.0, -0.16666666666666666, 0.0083333333333333332, -0.00019841269841269841, 2.7557319223985893e-06)


def lane_sin(x: float) -> float:
    """sin(x) for |x| <= 0.5: x * (c0 + x2 * (c1 + x2 * (c2 + x2 * (c3 + x2 * c4)))), in double, x2 = x * x."""
    x2 = x * x
    s = SIN_COEFFS[4]
    for k in (3, 2, 1, 0):
        s = SIN_COEFFS[k] + x2 * s
    return x * s


def dabs(x: float) -> float:
    """The C monitor's `x < 0.0 ? -x : x` (no NaN reaches it: rule 9 runs first)."""
    return -x if x < 0.0 else x


def imminent(pr: lf.LaneProfile, flags: int, offset: float, heading: float, room: float, speed: float) -> bool:
    """Rule 31's predicate on values already read, as monitor.c's lane_imminent(): VEH set, speed over v_min, the
    lateral speed toward the nearer line, and the margin room - |offset| under tlc_min * |vl|."""
    if not flags & lf.F_VEH or not speed > pr.v_min:
        return False
    vl = speed * lane_sin(heading)
    if not ((offset > 0.0 and vl > 0.0) or (offset < 0.0 and vl < 0.0) or (offset == 0.0 and vl != 0.0)):
        return False
    return room - dabs(offset) < pr.tlc_min * dabs(vl)


def _u32(p: bytes, off: int) -> int:
    return int(struct.unpack_from("<I", p, off)[0])


def _f32(p: bytes, off: int) -> float:
    return float(struct.unpack_from("<f", p, off)[0])


def _nonfinite(p: bytes, off: int) -> bool:
    return ((_u32(p, off) >> 23) & 0xFF) == 0xFF


def check_lane(payload: bytes, profiles: Optional[Mapping[int, lf.LaneProfile]] = None) -> Tuple[int, int]:
    """(verdict, reason) of one kind 6 payload (48 bytes), in 2.3's order, against `profiles` (laneframe.PROFILES when
    None)."""
    table = lf.PROFILES if profiles is None else profiles
    p = bytes(payload)
    if len(p) != lf.FRAME_PAYLOAD_BYTES:
        raise ValueError("payload of %d bytes, not %d" % (len(p), lf.FRAME_PAYLOAD_BYTES))
    f = p[lf.P_FLAGS]
    lane, veh = bool(f & lf.F_LANE), bool(f & lf.F_VEH)
    # 10
    if (f & lf.F_RESERVED) or any(p[lf.STAMP_SPAN[0]:lf.STAMP_SPAN[1]]) \
            or (not lane and any(any(p[a:b]) for a, b in lf.LANE_SPANS)) \
            or (not veh and any(p[lf.VEH_SPAN[0]:lf.VEH_SPAN[1]])):
        return lf.V_REJECT, lf.RSN_FLAGS_INVALID
    # 9
    if any((lane if flag == lf.F_LANE else veh) and _nonfinite(p, off) for _name, off, flag in lf.SLOTS):
        return lf.V_REJECT, lf.RSN_NOT_FINITE
    # 8
    pr = table.get(p[lf.P_PROFILE])
    if pr is None:
        return lf.V_REJECT, lf.RSN_PROFILE_UNBOUND
    # a "no lane" claim: nothing more to judge
    if not lane:
        return lf.V_ACCEPT, lf.RSN_OK
    # 28
    conf = p[lf.P_CONF]
    if conf < pr.conf_min or conf > lf.CONF_MAX:
        return lf.V_REJECT, lf.RSN_LANE_CONF_LOW
    off, h = _f32(p, lf.P_OFFSET), _f32(p, lf.P_HEADING)
    k, w = _f32(p, lf.P_CURVATURE), _f32(p, lf.P_WIDTH)
    # 29
    if w < pr.width_min or w > pr.width_max or dabs(k) > pr.k_max or dabs(h) > pr.h_max:
        return lf.V_REJECT, lf.RSN_LANE_IMPLAUSIBLE
    # 30
    room = w / 2.0 - pr.veh_half_w
    if dabs(off) > room:
        return lf.V_REJECT, lf.RSN_LANE_DEPARTURE
    # 31
    if imminent(pr, f, off, h, room, _f32(p, lf.P_SPEED)):
        return lf.V_REJECT, lf.RSN_LANE_DEPARTURE_IMMINENT
    return lf.V_ACCEPT, lf.RSN_OK


def judge(frame: bytes, profiles: Optional[Mapping[int, lf.LaneProfile]] = None) -> Tuple[int, int]:
    """(verdict, reason) of a 64-byte kind 6 request, against `profiles` (laneframe.PROFILES when None).

    Only kind 6 claims are this oracle's: a sentinel (echoed by the monitor, never judged) and any other kind byte are a
    ValueError (the monitor answers an unknown kind with reason 5, and its other kinds are outside this module). The
    verdict and reason bytes of the request are not read: the monitor overwrites them."""
    frame = bytes(frame)
    if len(frame) != lf.FRAME_TOTAL_BYTES:
        raise ValueError("frame of %d bytes, not %d" % (len(frame), lf.FRAME_TOTAL_BYTES))
    if struct.unpack_from("<Q", frame, 0)[0] == lf.SENTINEL_SEQ:
        raise ValueError("a sentinel is echoed, never judged")
    payload = frame[lf.FRAME_HEADER_BYTES:]
    if payload[lf.P_KIND] != lf.KIND_LANE:
        raise ValueError("kind %d is not kind 6" % payload[lf.P_KIND])
    return check_lane(payload, profiles)
