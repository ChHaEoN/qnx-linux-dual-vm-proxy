"""laneframe.py -- the kind 6 `lane` claim frame: constants, the profile table, encode, decode and layout (sdv/lane).

The kind 6 frame's rules come from the project's local design notes, not in this tree. The
64-byte frame it lives in is the repo's (ipc-test/common/frame.h: a 16-byte header of seq and tstamp, u64
little-endian, then a 48-byte payload; ipc-test/qnx-safety-monitor/monitor.c writes verdict p[6], reason p[7], and in
its stamp mode t_in, t_out at p[8..23] after the judgement; it dispatches on kind p[24]). Kind 6 owns p[0..5] and
p[25..47], 29 bytes; little-endian; f32 is IEEE binary32, LEFT positive throughout.

    p[n]     type  field                                                              rules
    0        u8    flags: b0 LANE (a lane found: both boundaries), b1 VEH (vehicle    10
                   values present); b2..b7 zero
    1        u8    confidence, 0..100; zero unless LANE                               10, 28
    2..5     f32   offset of the vehicle's centre from the lane centre [m]; LANE      9, 10, 30, 31
    6, 7     u8    verdict, reason: zero in a request; the monitor writes them        --
    8..23    --    zero in a request (the stamp mode writes t_in, t_out)              10
    24       u8    kind = 6                                                           dispatch
    25..28   f32   heading of the vehicle relative to the lane [rad]; LANE            9, 10, 29, 31
    29..32   f32   lane curvature ahead [1/m]; LANE                                   9, 10, 29
    33..36   f32   lane width [m]; LANE                                               9, 10, 29, 30, 31
    37..40   f32   vehicle speed at the frame [m/s]; VEH                              9, 10, 31
    41..44   f32   vehicle yaw rate at the frame [rad/s]; VEH (judged for finiteness  9, 10
                   only in v1)
    45..46   u16   the claim's age against the frame's time [ms], saturating          -- (carried, not judged in v1)
    47       u8    profile id (a key into PROFILES; 0 is never bound)                 8

When LANE is clear, p[1..5] and p[25..36] are all zero bytes (a "no lane" claim); when VEH is clear, p[37..44] are. "All
zero bytes" means 0x00 bytes: -0.0 (0x80000000) is not zero. A float travels as its exact binary32 bits.

`encode` packs an honest claim (every value finite and inside binary32, a lane's five values together or none, speed
and yaw rate together or neither, a confidence in 0..100, a profile in 1..255, a seq neither 0 nor the sentinel).
`pack_bits` takes each slot's exact binary32 bits, so a non-finite value, profile 0 and a confidence over 100 can be
packed for injection; it still refuses what the layout forbids. A layout fault of rule 10 (a reserved flag bit, a
non-zero byte of p[8..23], bytes in an absent slot) and a foreign kind byte are never written by either: an injection
of one is a byte patch on a packed frame. `decode_request` and `decode_reply` refuse every layout fault, and a reply
whose verdict is not 0 or 1 or whose reason is not zero exactly when the verdict is.

PROFILES is the table monitor.c compiles under its kind 6 guard (LANE_PROFILE_TABLE), mirrored here; a test holds the
two equal. table_errors() is the twin of the monitor's startup self-check. Standard library only, and nothing of any
other sdv package.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

# The frame the payload lives in (ipc-test/common/frame.h).
FRAME_HEADER_BYTES = 16
FRAME_PAYLOAD_BYTES = 48
FRAME_TOTAL_BYTES = FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES
SENTINEL_SEQ = (1 << 64) - 1          # FRAME_SENTINEL_SEQ: a keepalive, never a claim

KIND_LANE = 6

# Payload offsets (2.2).
P_FLAGS = 0
P_CONF = 1
P_OFFSET = 2
P_VERDICT = 6
P_REASON = 7
P_T_IN = 8
P_T_OUT = 16
P_KIND = 24
P_HEADING = 25
P_CURVATURE = 29
P_WIDTH = 33
P_SPEED = 37
P_YAW_RATE = 41
P_AGE = 45
P_PROFILE = 47
STAMP_SPAN = (8, 24)                  # p[8..23]
LANE_SPANS = ((1, 6), (25, 37))       # p[1..5] and p[25..36]: zero bytes unless LANE
VEH_SPAN = (37, 45)                   # p[37..44]: zero bytes unless VEH

F_LANE = 0x01
F_VEH = 0x02
F_DEFINED = 0x03
F_RESERVED = 0xFC

CONF_MAX = 100
AGE_MAX = 0xFFFF

# The six f32 slots in payload order: name, offset, the flag that makes it present.
SLOTS: Tuple[Tuple[str, int, int], ...] = (
    ("offset", P_OFFSET, F_LANE), ("heading", P_HEADING, F_LANE), ("curvature", P_CURVATURE, F_LANE),
    ("width", P_WIDTH, F_LANE), ("speed", P_SPEED, F_VEH), ("yaw_rate", P_YAW_RATE, F_VEH))
LANE_FIELDS = ("offset", "heading", "curvature", "width")
VEH_FIELDS = ("speed", "yaw_rate")

# Verdicts and the reasons of kind 6 (2.3); 5 is the monitor's unknown kind, which a kind 6 frame gets from a build
# without 0x40.
V_ACCEPT = 0
V_REJECT = 1
RSN_OK = 0
RSN_KIND_UNKNOWN = 5
RSN_PROFILE_UNBOUND = 8
RSN_NOT_FINITE = 9
RSN_FLAGS_INVALID = 10
RSN_LANE_CONF_LOW = 28
RSN_LANE_IMPLAUSIBLE = 29
RSN_LANE_DEPARTURE = 30
RSN_LANE_DEPARTURE_IMMINENT = 31
REASON_NAMES = {
    RSN_OK: "ok",
    RSN_KIND_UNKNOWN: "claim-kind-unknown",
    RSN_PROFILE_UNBOUND: "profile-unbound",
    RSN_NOT_FINITE: "field-not-finite",
    RSN_FLAGS_INVALID: "flags-invalid",
    RSN_LANE_CONF_LOW: "lane-conf-low",
    RSN_LANE_IMPLAUSIBLE: "lane-implausible",
    RSN_LANE_DEPARTURE: "lane-departure",
    RSN_LANE_DEPARTURE_IMMINENT: "lane-departure-imminent",
}
ORDER = (RSN_FLAGS_INVALID, RSN_NOT_FINITE, RSN_PROFILE_UNBOUND, RSN_LANE_CONF_LOW, RSN_LANE_IMPLAUSIBLE,
         RSN_LANE_DEPARTURE, RSN_LANE_DEPARTURE_IMMINENT)


# --- the profile table (2.4) -------------------------------------------------------------------------

@dataclass(frozen=True)
class LaneProfile:
    """One row of the kind 6 table: DESIGN values, from road design ranges and the CARLA taxi, never fitted to a run."""
    id: int
    conf_min: int         # rule 28: confidence under it is rejected (and over 100)
    width_min: float      # rule 29: m
    width_max: float      # rule 29: m
    k_max: float          # rule 29: |curvature|, 1/m
    h_max: float          # rule 29: |heading|, rad; at most SIN_DOMAIN, so rule 31's sin stays in its domain
    veh_half_w: float     # rules 30, 31: half the vehicle's width, m
    v_min: float          # rule 31: judged only over this speed, m/s
    tlc_min: float        # rule 31: the least time to the nearer line, s


PROFILE_FIELDS = ("id", "conf_min", "width_min", "width_max", "k_max", "h_max", "veh_half_w", "v_min", "tlc_min")

# monitor.c's LANE_PROFILE_TABLE, row for row.
PROFILES: Dict[int, LaneProfile] = {
    1: LaneProfile(id=1, conf_min=50, width_min=2.5, width_max=4.5, k_max=0.1, h_max=0.5, veh_half_w=0.95, v_min=1.0,
                   tlc_min=1.0),
}

# Rule 31's sin is the odd Taylor polynomial to x^9; |heading| <= h_max <= SIN_DOMAIN after rule 29.
SIN_DOMAIN = 0.5


def _finite_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def table_errors(profiles: Mapping[int, LaneProfile]) -> List[str]:
    """Every invariant of the table the monitor's startup self-check holds, broken ([] when none is): at least one row;
    each key its row's id, an id in 1..255; conf_min in 0..100; 0 < width_min < width_max, both finite; 0 <= veh_half_w
    < width_min / 2 (so rule 30's room is positive at the narrowest width); 0 < k_max finite; 0 < h_max <= SIN_DOMAIN;
    0 <= v_min finite; 0 < tlc_min finite."""
    errs: List[str] = []
    if not profiles:
        return ["no profile: the table binds nothing"]
    for key, p in profiles.items():
        if not isinstance(p, LaneProfile):
            errs.append("profile %r is not a LaneProfile" % (key,))
            continue
        if key != p.id:
            errs.append("profile key %r is not its row's id %r" % (key, p.id))
        if isinstance(p.id, bool) or not isinstance(p.id, int) or not 1 <= p.id <= 0xFF:
            errs.append("profile id %r is not in 1..255 (0 is never bound)" % (p.id,))
        if isinstance(p.conf_min, bool) or not isinstance(p.conf_min, int) or not 0 <= p.conf_min <= CONF_MAX:
            errs.append("profile %r: conf_min %r is not in 0..100" % (p.id, p.conf_min))
        vals = [getattr(p, k) for k in PROFILE_FIELDS[2:]]
        if not all(_finite_num(x) for x in vals):
            errs.append("profile %r: a limit is not a finite number" % (p.id,))
            continue
        if not 0.0 < p.width_min < p.width_max:
            errs.append("profile %r: not 0 < width_min < width_max" % (p.id,))
        if not 0.0 <= p.veh_half_w < p.width_min / 2.0:
            errs.append("profile %r: not 0 <= veh_half_w < width_min / 2" % (p.id,))
        if not p.k_max > 0.0:
            errs.append("profile %r: k_max is not positive" % (p.id,))
        if not 0.0 < p.h_max <= SIN_DOMAIN:
            errs.append("profile %r: h_max is not in (0, %r] rad, the sin polynomial's domain" % (p.id, SIN_DOMAIN))
        if not p.v_min >= 0.0:
            errs.append("profile %r: v_min is negative" % (p.id,))
        if not p.tlc_min > 0.0:
            errs.append("profile %r: tlc_min is not positive" % (p.id,))
    return errs


class FrameError(ValueError):
    """A frame, or the values for one, that the kind 6 layout does not allow."""


# --- binary32 helpers ------------------------------------------------------------------------------

def f32_bits(x: float) -> int:
    """The binary32 bits of x rounded to float32 (FrameError if it overflows float32)."""
    try:
        return int(struct.unpack("<I", struct.pack("<f", x))[0])
    except (OverflowError, struct.error) as err:
        raise FrameError("%r does not fit a binary32" % (x,)) from err


def bits_f32(bits: int) -> float:
    """The binary32 with these bits, widened to a Python float (exactly; a signalling NaN may come back quieted)."""
    return float(struct.unpack("<f", struct.pack("<I", bits))[0])


def f32(x: float) -> float:
    """x rounded to binary32 and widened back: the value a slot carries."""
    return bits_f32(f32_bits(x))


def is_finite_bits(bits: int) -> bool:
    """A binary32 is finite unless all its exponent bits are set (the monitor judges by these bits)."""
    return ((bits >> 23) & 0xFF) != 0xFF


def f32_next_up(x: float) -> float:
    """The next binary32 above the binary32 x (x must already be a finite binary32 value)."""
    if not math.isfinite(x) or f32(x) != x:
        raise FrameError("%r is not a finite binary32 value" % (x,))
    b = f32_bits(x)
    if b == 0x80000000:
        b = 0
    b = b - 1 if b & 0x80000000 else b + 1
    return bits_f32(b)


def f32_next_down(x: float) -> float:
    return -f32_next_up(-x)


# --- packing -----------------------------------------------------------------------------------------

def _int(name: str, x: Any, lo: int, hi: int) -> int:
    if isinstance(x, bool) or not isinstance(x, int):
        raise FrameError("%s must be an int, not %r" % (name, x))
    if not lo <= x <= hi:
        raise FrameError("%s %d outside %d..%d" % (name, x, lo, hi))
    return x


def pack_bits(*, seq: int, tstamp_ns: int = 0, flags: int, profile: int, conf: int = 0, offset: Optional[int] = None,
              heading: Optional[int] = None, curvature: Optional[int] = None, width: Optional[int] = None,
              speed: Optional[int] = None, yaw_rate: Optional[int] = None, age_ms: int = 0) -> bytes:
    """Pack a request from each slot's exact binary32 bits (None = absent, written as four zero bytes).

    The general form, for injection and tests: any bit pattern, a confidence and a profile in 0..255. It refuses what the
    layout forbids: a seq of 0 or the sentinel, a reserved flag bit, a slot whose flag and bits disagree (bits given with
    its flag clear, or its flag set with none), a non-zero confidence with LANE clear, an age outside u16."""
    _int("seq", seq, 1, SENTINEL_SEQ - 1)
    _int("tstamp_ns", tstamp_ns, 0, (1 << 64) - 1)
    _int("flags", flags, 0, 0xFF)
    _int("profile", profile, 0, 0xFF)
    _int("conf", conf, 0, 0xFF)
    _int("age_ms", age_ms, 0, AGE_MAX)
    if flags & F_RESERVED:
        raise FrameError("reserved flag bits 0x%02X (b2..b7 are zero in every request)" % (flags & F_RESERVED))
    if conf and not flags & F_LANE:
        raise FrameError("confidence %d with LANE clear (a no-lane claim carries zero bytes in p[1..5])" % conf)
    given = {"offset": offset, "heading": heading, "curvature": curvature, "width": width, "speed": speed,
             "yaw_rate": yaw_rate}
    p = bytearray(FRAME_PAYLOAD_BYTES)
    p[P_FLAGS] = flags
    p[P_CONF] = conf
    p[P_KIND] = KIND_LANE
    p[P_PROFILE] = profile
    for name, off, flag in SLOTS:
        b = given[name]
        present = bool(flags & flag)
        if present != (b is not None):
            raise FrameError("%s: %s" % (name, "its flag is set but no value is given" if present
                                         else "a value is given but its flag is clear (an absent slot is all zero bytes)"))
        if b is not None:
            struct.pack_into("<I", p, off, _int("%s bits" % name, b, 0, 0xFFFFFFFF))
    struct.pack_into("<H", p, P_AGE, age_ms)
    return struct.pack("<QQ", seq, tstamp_ns) + bytes(p)


def _honest_bits(name: str, x: Any) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise FrameError("%s: %r is not a number" % (name, x))
    try:
        b = f32_bits(float(x))
    except OverflowError as err:          # an int beyond a double is beyond a binary32 too
        raise FrameError("%s: an integer that does not fit a binary32" % name) from err
    if not is_finite_bits(b):
        raise FrameError("%s: %r is not finite (inject non-finite values with pack_bits)" % (name, x))
    return b


def encode(*, seq: int, tstamp_ns: int = 0, profile: int = 1, conf: Optional[int] = None, offset: Optional[float] = None,
           heading: Optional[float] = None, curvature: Optional[float] = None, width: Optional[float] = None,
           speed: Optional[float] = None, yaw_rate: Optional[float] = None, age_ms: int = 0) -> bytes:
    """Pack an honest claim. A lane: conf (0..100) with offset, heading, curvature and width, all five or none (none: a
    "no lane" claim). Vehicle values: speed and yaw_rate, both or neither. Every value finite and inside binary32 (a bool
    is not a number), a profile in 1..255. Inject a non-finite value, profile 0 or a confidence over 100 with
    pack_bits."""
    _int("profile", profile, 1, 0xFF)
    lane_given = [conf, offset, heading, curvature, width]
    if any(x is not None for x in lane_given) and not all(x is not None for x in lane_given):
        raise FrameError("a lane's values come together: conf, offset, heading, curvature and width, or none of them")
    veh_given = [speed, yaw_rate]
    if any(x is not None for x in veh_given) and not all(x is not None for x in veh_given):
        raise FrameError("speed and yaw rate come together, or neither")
    flags = 0
    bits: Dict[str, Optional[int]] = dict.fromkeys(LANE_FIELDS + VEH_FIELDS)
    c = 0
    if conf is not None:
        flags |= F_LANE
        c = _int("conf", conf, 0, CONF_MAX)
        for name, x in (("offset", offset), ("heading", heading), ("curvature", curvature), ("width", width)):
            bits[name] = _honest_bits(name, x)
    if speed is not None:
        flags |= F_VEH
        bits["speed"] = _honest_bits("speed", speed)
        bits["yaw_rate"] = _honest_bits("yaw_rate", yaw_rate)
    return pack_bits(seq=seq, tstamp_ns=tstamp_ns, flags=flags, profile=profile, conf=c, age_ms=age_ms, **bits)


# --- decoding ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Decoded:
    seq: int
    tstamp_ns: int
    flags: int
    conf: int
    profile: int
    bits: Dict[str, Optional[int]]
    age_ms: int
    verdict: int
    reason: int
    t_in_ns: Optional[int]
    t_out_ns: Optional[int]

    @property
    def lane(self) -> bool:
        return bool(self.flags & F_LANE)

    @property
    def veh(self) -> bool:
        return bool(self.flags & F_VEH)

    def value(self, name: str) -> Optional[float]:
        b = self.bits[name]
        return None if b is None else bits_f32(b)


def layout_errors(frame: bytes, reply: bool = False, stamp: bool = False) -> List[str]:
    """Everything that makes these bytes not a well-formed kind 6 frame (an empty list: well formed).

    A request has zero verdict and reason bytes and zero p[8..23]; a reply has the monitor's verdict (0 or 1) and a
    reason that is zero exactly when the verdict is; a stamp reply also carries t_in and t_out at p[8..23], so stamp
    implies reply. A confidence over 100 is no layout fault: rule 28 judges it."""
    reply = reply or stamp
    if len(frame) != FRAME_TOTAL_BYTES:
        return ["length %d, not %d" % (len(frame), FRAME_TOTAL_BYTES)]
    errs = []
    seq = struct.unpack_from("<Q", frame, 0)[0]
    if seq == SENTINEL_SEQ:
        errs.append("seq is the sentinel (a keepalive, not a claim)")
    elif seq == 0:
        errs.append("seq 0 (a client counts from 1)")
    p = frame[FRAME_HEADER_BYTES:]
    if p[P_KIND] != KIND_LANE:
        errs.append("kind %d, not %d" % (p[P_KIND], KIND_LANE))
    f = p[P_FLAGS]
    if f & F_RESERVED:
        errs.append("reserved flag bits 0x%02X" % (f & F_RESERVED))
    if not reply:
        if p[P_VERDICT] or p[P_REASON]:
            errs.append("verdict/reason bytes non-zero in a request")
    elif p[P_VERDICT] not in (V_ACCEPT, V_REJECT):
        errs.append("verdict %d" % p[P_VERDICT])
    elif (p[P_VERDICT] == V_ACCEPT) != (p[P_REASON] == RSN_OK):
        errs.append("verdict %d with reason %d" % (p[P_VERDICT], p[P_REASON]))
    if not stamp and any(p[STAMP_SPAN[0]:STAMP_SPAN[1]]):
        errs.append("p[8..23] non-zero")
    if not f & F_LANE and any(any(p[a:b]) for a, b in LANE_SPANS):
        errs.append("LANE clear but p[1..5] or p[25..36] not all zero bytes")
    if not f & F_VEH and any(p[VEH_SPAN[0]:VEH_SPAN[1]]):
        errs.append("VEH clear but p[37..44] not all zero bytes")
    return errs


def _decode(frame: bytes, reply: bool, stamp: bool) -> Decoded:
    frame = bytes(frame)
    errs = layout_errors(frame, reply=reply, stamp=stamp)
    if errs:
        raise FrameError("malformed kind 6 frame: " + "; ".join(errs))
    seq, tstamp = struct.unpack_from("<QQ", frame, 0)
    p = frame[FRAME_HEADER_BYTES:]
    f = p[P_FLAGS]
    bits: Dict[str, Optional[int]] = {}
    for name, off, flag in SLOTS:
        bits[name] = struct.unpack_from("<I", p, off)[0] if f & flag else None
    t_in = t_out = None
    if stamp:
        t_in, t_out = struct.unpack_from("<QQ", p, P_T_IN)
    return Decoded(seq=seq, tstamp_ns=tstamp, flags=f, conf=p[P_CONF], profile=p[P_PROFILE], bits=bits,
                   age_ms=struct.unpack_from("<H", p, P_AGE)[0], verdict=p[P_VERDICT], reason=p[P_REASON],
                   t_in_ns=t_in, t_out_ns=t_out)


def decode_request(frame: bytes) -> Decoded:
    """A kind 6 request, every layout fault of 2.2 refused (FrameError)."""
    return _decode(frame, reply=False, stamp=False)


def decode_reply(frame: bytes, stamp: bool = False) -> Decoded:
    """The monitor's answer: the request's layout with the verdict and reason written (0 and 0, or 1 and a non-zero
    reason); with stamp, an answer whose p[8..23] carry t_in and t_out."""
    return _decode(frame, reply=True, stamp=stamp)
