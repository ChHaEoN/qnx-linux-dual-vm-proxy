"""ctlframe.py -- the kind 2 `ctl` claim frame: constants, encode, decode and the contract loader (sdv/ctl).

The kind 2 frame is the Phase 8 specification's 2.2 (the project's local design
notes; not in this tree), unchanged from the earlier plan's 2.2, with no digest on the wire and p[47] reserved. The
64-byte frame it lives in is the repo's (ipc-test/common/frame.h: a 16-byte header of seq and tstamp, u64
little-endian, then a 48-byte payload; ipc-test/qnx-safety-monitor/monitor.c writes verdict p[6], reason p[7], and
in its stamp mode t_in, t_out at p[8..23] after the judgement; it dispatches on kind p[24]).

    p[n]     type  field                                                              rules
    0        u8    flags: b0 acceleration defined, b1 jerk defined, b2 steering rate   10
                   defined, b3 odometry present and inside the node's freshness
                   window; b4..b7 zero
    1        u8    profile id (0 is never bound)                                      8
    2..5     f32   v_cmd, longitudinal velocity command [m/s], always present         9, 12, 18, 19
    6, 7     u8    verdict, reason: zero in a request; the monitor writes them        --
    8..23    --    zero in a request (the stamp mode writes t_in, t_out)              10
    24       u8    kind = 2                                                           dispatch
    25..28   f32   acceleration [m/s^2]; all zero bytes unless b0                     9, 10, 13
    29..32   f32   jerk [m/s^3]; all zero bytes unless b1                             9, 10, 14
    33..36   f32   delta, steering tire angle [rad], positive left, always present    9, 15, 17
    37..40   f32   steering tire rotation rate [rad/s]; all zero bytes unless b2      9, 10, 16
    41..44   f32   v_meas, measured speed [m/s]; all zero bytes unless b3             9, 10, 17, 18, 19
    45..46   u16   the ROS stamp interval [ms], 0 for the first, saturated at 0xFFFF  11
    47       u8    reserved, zero                                                     10

"All zero bytes" means four 0x00 bytes: -0.0 (0x80000000) is not zero. A float travels as its exact binary32 bits.

`encode` packs an honest request (every value finite and inside binary32, each optional value given exactly when its
flag is set, a profile in 1..255, a seq neither 0 nor the sentinel). `pack_bits` takes each slot's exact binary32 bits,
so a non-finite value (a signalling NaN included) and profile 0 can be packed for injection; it still refuses what the
layout forbids. A layout fault of rule 10 (a reserved flag bit, a non-zero reserved byte, bytes in an undefined slot)
and a foreign kind byte are never written by either: an injection of one is a byte patch on a packed frame
(ctlclient.py), as sdv/frame/vssframe.py does for kind 4. `decode_request` and `decode_reply` refuse every layout fault,
and a reply whose verdict is not 0 or 1 or whose reason is not zero exactly when the verdict is.

The kind 2 contract (2.4: the Python module vss_ctl.py, generated beside today's outputs from WP1b on) is loaded by
path with `load_contract`, never imported by name from sys.path. Standard library only: the claim node imports this
module, and the node imports no gRPC, no KUKSA client and nothing of sdv/frame.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# The frame the payload lives in (ipc-test/common/frame.h).
FRAME_HEADER_BYTES = 16
FRAME_PAYLOAD_BYTES = 48
FRAME_TOTAL_BYTES = FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES
SENTINEL_SEQ = (1 << 64) - 1          # FRAME_SENTINEL_SEQ: a keepalive the node never sends (svc counts it as no life)

KIND_CTL = 2

# Payload offsets (2.2).
P_FLAGS = 0
P_PROFILE = 1
P_V_CMD = 2
P_VERDICT = 6
P_REASON = 7
P_T_IN = 8
P_T_OUT = 16
P_KIND = 24
P_ACCEL = 25
P_JERK = 29
P_DELTA = 33
P_RATE = 37
P_V_MEAS = 41
P_INTERVAL = 45
P_RESERVED = 47
STAMP_SPAN = (8, 24)                  # p[8..23]

F_ACCEL = 0x01
F_JERK = 0x02
F_RATE = 0x04
F_ODOM = 0x08
F_DEFINED = 0x0F
F_RESERVED = 0xF0

INTERVAL_MAX = 0xFFFF

# The six f32 slots in payload order: name, offset, the flag that defines it (None = always present).
SLOTS: Tuple[Tuple[str, int, Optional[int]], ...] = (
    ("v_cmd", P_V_CMD, None), ("accel", P_ACCEL, F_ACCEL), ("jerk", P_JERK, F_JERK),
    ("delta", P_DELTA, None), ("rate", P_RATE, F_RATE), ("v_meas", P_V_MEAS, F_ODOM))
SLOT_NAMES = tuple(s[0] for s in SLOTS)

# Verdicts and the reasons of kind 2 (2.3); 5 is the monitor's unknown kind, which an injected kind byte gets.
V_ACCEPT = 0
V_REJECT = 1
RSN_OK = 0
RSN_KIND_UNKNOWN = 5
RSN_PROFILE_UNBOUND = 8
RSN_NOT_FINITE = 9
RSN_FLAGS_INVALID = 10
RSN_CTL_INTERVAL = 11
RSN_CTL_SPEED = 12
RSN_CTL_ACCEL = 13
RSN_CTL_JERK = 14
RSN_CTL_STEER = 15
RSN_CTL_STEER_RATE = 16
RSN_CTL_LAT_ACCEL = 17
RSN_CTL_OVERSPEED = 18
RSN_CTL_ROLLING_BACK = 19
REASON_NAMES = {
    RSN_OK: "ok",
    RSN_KIND_UNKNOWN: "kind-unknown",
    RSN_PROFILE_UNBOUND: "profile-unbound",
    RSN_NOT_FINITE: "field-not-finite",
    RSN_FLAGS_INVALID: "flags-invalid",
    RSN_CTL_INTERVAL: "ctl-interval",
    RSN_CTL_SPEED: "ctl-speed",
    RSN_CTL_ACCEL: "ctl-accel",
    RSN_CTL_JERK: "ctl-jerk",
    RSN_CTL_STEER: "ctl-steer",
    RSN_CTL_STEER_RATE: "ctl-steer-rate",
    RSN_CTL_LAT_ACCEL: "ctl-lat-accel",
    RSN_CTL_OVERSPEED: "ctl-overspeed",
    RSN_CTL_ROLLING_BACK: "ctl-rolling-back",
}
ORDER = (RSN_FLAGS_INVALID, RSN_PROFILE_UNBOUND, RSN_NOT_FINITE, RSN_CTL_INTERVAL, RSN_CTL_SPEED, RSN_CTL_ACCEL,
         RSN_CTL_JERK, RSN_CTL_STEER, RSN_CTL_STEER_RATE, RSN_CTL_LAT_ACCEL, RSN_CTL_OVERSPEED, RSN_CTL_ROLLING_BACK)

# The kind 2 contract (2.4).
CONTRACT_FORMAT = 1
CONTRACT_SLOT_PATHS = (
    "Vehicle.DualVm.ControlCommand.Velocity",
    "Vehicle.DualVm.ControlCommand.Acceleration",
    "Vehicle.DualVm.ControlCommand.Jerk",
    "Vehicle.DualVm.ControlCommand.SteeringTireAngle",
    "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate",
    "Vehicle.DualVm.Motion.LongitudinalVelocity",
    "Vehicle.DualVm.ControlCommand.StampInterval",
)
PROFILE_KEYS = ("l_mm", "v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max", "run_window_max_ms",
                "compiled")
PROFILE_LIMITS = ("v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max")
STEER_MAX_LIMIT = 1.0                 # rad: rule 15 runs before 17, so tan is only ever taken inside [0, 1]
CONTRACT_CONSTANTS = ("DT_MAX_MS", "TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN", "ROLLBACK_V")


class FrameError(ValueError):
    """A frame, or the values for one, that the kind 2 layout does not allow."""


class ContractError(RuntimeError):
    """The kind 2 contract is missing or breaks a loader rule."""


# --- binary32 helpers ------------------------------------------------------------------------------

def f32_bits(x: float) -> int:
    """The binary32 bits of x rounded to float32 (FrameError if it overflows float32)."""
    try:
        return struct.unpack("<I", struct.pack("<f", x))[0]
    except (OverflowError, struct.error) as err:
        raise FrameError("%r does not fit a binary32" % (x,)) from err


def bits_f32(bits: int) -> float:
    """The binary32 with these bits, widened to a Python float (exactly; a signalling NaN may come back quieted)."""
    return struct.unpack("<f", struct.pack("<I", bits))[0]


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


def honest_bits(x: float) -> int:
    """The bits a value the gate sent is packed with: its binary32 rounding, an overflow as the infinity of its sign
    (what a C float conversion gives), a NaN as it is. Never refuses: every counted Control packs one frame."""
    try:
        return struct.unpack("<I", struct.pack("<f", x))[0]
    except (OverflowError, struct.error):
        return 0xFF800000 if x < 0 else 0x7F800000


# --- the digest -------------------------------------------------------------------------------------

def fnv1_32(data: bytes) -> int:
    """FNV-1 32 (multiply, then xor; not FNV-1a): the hash vss-tools uses for staticUIDs."""
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def digest_of(uids: Iterable[int]) -> int:
    """The kind 2 digest (2.4): FNV-1 32 over the seven UIDs, each as four little-endian bytes, in slot order."""
    return fnv1_32(b"".join(struct.pack("<I", u) for u in uids))


# --- packing -----------------------------------------------------------------------------------------

def _int(name: str, x: Any, lo: int, hi: int) -> int:
    if isinstance(x, bool) or not isinstance(x, int):
        raise FrameError("%s must be an int, not %r" % (name, x))
    if not lo <= x <= hi:
        raise FrameError("%s %d outside %d..%d" % (name, x, lo, hi))
    return x


def pack_bits(*, seq: int, tstamp_ns: int, flags: int, profile: int, v_cmd: int, delta: int, accel: Optional[int] = None,
              jerk: Optional[int] = None, rate: Optional[int] = None, v_meas: Optional[int] = None,
              interval_ms: int = 0) -> bytes:
    """Pack a request from each slot's exact binary32 bits (None = undefined, written as four zero bytes).

    The general form, for injection and tests: any bit pattern, profile 0..255. It refuses what the layout forbids:
    a seq of 0 or the sentinel, a reserved flag bit, a slot whose flag and bits disagree (bits given with the flag
    clear, or the flag set with none), an interval outside u16."""
    _int("seq", seq, 1, SENTINEL_SEQ - 1)
    _int("tstamp_ns", tstamp_ns, 0, (1 << 64) - 1)
    _int("flags", flags, 0, 0xFF)
    _int("profile", profile, 0, 0xFF)
    _int("interval_ms", interval_ms, 0, INTERVAL_MAX)
    if flags & F_RESERVED:
        raise FrameError("reserved flag bits 0x%02X (b4..b7 are zero in every request)" % (flags & F_RESERVED))
    given = {"v_cmd": v_cmd, "accel": accel, "jerk": jerk, "delta": delta, "rate": rate, "v_meas": v_meas}
    p = bytearray(FRAME_PAYLOAD_BYTES)
    p[P_FLAGS] = flags
    p[P_PROFILE] = profile
    p[P_KIND] = KIND_CTL
    for name, off, flag in SLOTS:
        b = given[name]
        defined = flag is None or bool(flags & flag)
        if defined != (b is not None):
            raise FrameError("%s: %s" % (name, "its flag is set but no value is given" if defined
                                         else "a value is given but its flag is clear (an undefined slot is all zero bytes)"))
        if b is not None:
            struct.pack_into("<I", p, off, _int("%s bits" % name, b, 0, 0xFFFFFFFF))
    struct.pack_into("<H", p, P_INTERVAL, interval_ms)
    return struct.pack("<QQ", seq, tstamp_ns) + bytes(p)


def encode(*, seq: int, tstamp_ns: int, flags: int, profile: int, v_cmd: float, delta: float,
           accel: Optional[float] = None, jerk: Optional[float] = None, rate: Optional[float] = None,
           v_meas: Optional[float] = None, interval_ms: int = 0) -> bytes:
    """Pack an honest request: every value given finite and inside binary32 (a bool is not a number), each optional
    value given exactly when its flag is set, a profile in 1..255. Inject a non-finite value or profile 0 with
    pack_bits."""
    _int("profile", profile, 1, 0xFF)
    bits: Dict[str, Optional[int]] = {}
    for name, x in (("v_cmd", v_cmd), ("accel", accel), ("jerk", jerk), ("delta", delta), ("rate", rate), ("v_meas", v_meas)):
        if x is None:
            bits[name] = None
            continue
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise FrameError("%s: %r is not a number" % (name, x))
        try:
            b = f32_bits(float(x))
        except OverflowError as err:          # an int beyond a double is beyond a binary32 too
            raise FrameError("%s: an integer that does not fit a binary32" % name) from err
        if not is_finite_bits(b):
            raise FrameError("%s: %r is not finite (inject non-finite values with pack_bits)" % (name, x))
        bits[name] = b
    v, d = bits.pop("v_cmd"), bits.pop("delta")
    if v is None or d is None:
        raise FrameError("v_cmd and delta are always present")
    return pack_bits(seq=seq, tstamp_ns=tstamp_ns, flags=flags, profile=profile, v_cmd=v, delta=d,
                     interval_ms=interval_ms, **bits)


def interval_ms(prev_stamp_ns: Optional[int], stamp_ns: int) -> int:
    """p[45..46]: this Control's stamp minus the previous counted one's, in whole ms (truncated), 0 for the first,
    saturated at 0xFFFF. A stamp earlier than the previous one gives 0 (the client counts it as interval_negative)."""
    if prev_stamp_ns is None:
        return 0
    diff = stamp_ns - prev_stamp_ns
    if diff < 0:
        return 0
    return min(diff // 1_000_000, INTERVAL_MAX)


# --- decoding ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Decoded:
    seq: int
    tstamp_ns: int
    flags: int
    profile: int
    bits: Dict[str, Optional[int]]
    interval_ms: int
    verdict: int
    reason: int
    t_in_ns: Optional[int]
    t_out_ns: Optional[int]

    def value(self, name: str) -> Optional[float]:
        b = self.bits[name]
        return None if b is None else bits_f32(b)

    @property
    def v_cmd(self) -> Optional[float]:
        return self.value("v_cmd")

    @property
    def accel(self) -> Optional[float]:
        return self.value("accel")

    @property
    def jerk(self) -> Optional[float]:
        return self.value("jerk")

    @property
    def delta(self) -> Optional[float]:
        return self.value("delta")

    @property
    def rate(self) -> Optional[float]:
        return self.value("rate")

    @property
    def v_meas(self) -> Optional[float]:
        return self.value("v_meas")


def layout_errors(frame: bytes, reply: bool = False, stamp: bool = False) -> List[str]:
    """Everything that makes these bytes not a well-formed kind 2 frame (an empty list: well formed).

    A request has zero verdict and reason bytes and zero p[8..23]; a reply has the monitor's verdict (0 or 1) and a
    reason that is zero exactly when the verdict is; a stamp reply also carries t_in and t_out at p[8..23], so stamp
    implies reply."""
    reply = reply or stamp
    if len(frame) != FRAME_TOTAL_BYTES:
        return ["length %d, not %d" % (len(frame), FRAME_TOTAL_BYTES)]
    errs = []
    seq = struct.unpack_from("<Q", frame, 0)[0]
    if seq == SENTINEL_SEQ:
        errs.append("seq is the sentinel (a keepalive, not a claim)")
    elif seq == 0:
        errs.append("seq 0 (the node counts from 1)")
    p = frame[FRAME_HEADER_BYTES:]
    if p[P_KIND] != KIND_CTL:
        errs.append("kind %d, not %d" % (p[P_KIND], KIND_CTL))
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
    if p[P_RESERVED]:
        errs.append("reserved p[47] non-zero")
    for name, off, flag in SLOTS:
        if flag is not None and not f & flag and any(p[off:off + 4]):
            errs.append("%s undefined but its bytes are not all zero" % name)
    return errs


def _decode(frame: bytes, reply: bool, stamp: bool) -> Decoded:
    frame = bytes(frame)
    errs = layout_errors(frame, reply=reply, stamp=stamp)
    if errs:
        raise FrameError("malformed kind 2 frame: " + "; ".join(errs))
    seq, tstamp = struct.unpack_from("<QQ", frame, 0)
    p = frame[FRAME_HEADER_BYTES:]
    f = p[P_FLAGS]
    bits: Dict[str, Optional[int]] = {}
    for name, off, flag in SLOTS:
        bits[name] = struct.unpack_from("<I", p, off)[0] if flag is None or f & flag else None
    t_in = t_out = None
    if stamp:
        t_in, t_out = struct.unpack_from("<QQ", p, P_T_IN)
    return Decoded(seq=seq, tstamp_ns=tstamp, flags=f, profile=p[P_PROFILE], bits=bits,
                   interval_ms=struct.unpack_from("<H", p, P_INTERVAL)[0], verdict=p[P_VERDICT], reason=p[P_REASON],
                   t_in_ns=t_in, t_out_ns=t_out)


def decode_request(frame: bytes) -> Decoded:
    """A kind 2 request, every layout fault of 2.2 refused (FrameError)."""
    return _decode(frame, reply=False, stamp=False)


def decode_reply(frame: bytes, stamp: bool = False) -> Decoded:
    """The monitor's answer: the request's layout with the verdict and reason written (0 and 0, or 1 and a non-zero
    reason); with stamp, a :7151 answer whose p[8..23] carry t_in and t_out."""
    return _decode(frame, reply=True, stamp=stamp)


def fields_of(frame: bytes) -> Dict[str, Any]:
    """The fields of any 64-byte frame as packed, without judging its layout: kind, flags, profile, the interval and
    each slot's value as a float, or None when its flag is clear (an injected frame is read by its own flags)."""
    frame = bytes(frame)
    if len(frame) != FRAME_TOTAL_BYTES:
        raise FrameError("length %d, not %d" % (len(frame), FRAME_TOTAL_BYTES))
    p = frame[FRAME_HEADER_BYTES:]
    f = p[P_FLAGS]
    out: Dict[str, Any] = {"seq": struct.unpack_from("<Q", frame, 0)[0], "kind": p[P_KIND], "flags": f,
                           "profile": p[P_PROFILE], "interval_ms": struct.unpack_from("<H", p, P_INTERVAL)[0]}
    for name, off, flag in SLOTS:
        out[name] = bits_f32(struct.unpack_from("<I", p, off)[0]) if flag is None or f & flag else None
    return out


# --- the kind 2 contract -------------------------------------------------------------------------------

def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def contract_errors(mod: Any) -> List[str]:
    """Every loader rule (2.4) the module breaks: FORMAT not the int 1 (the generated module writes `FORMAT = 1`, the C
    header `1u`: neither True nor 1.0 is that), DIGEST not the FNV-1 32 of SLOT_UIDS, a compiled profile's steer_max
    outside (0, 1.0]; and the shape the generated module has (the seven slot paths in slot order, seven u32 UIDs, the
    five constants, every profile row's nine keys, COMPILED_PROFILE_IDS the compiled rows' ids ascending, no profile
    0)."""
    errs: List[str] = []
    fmt = getattr(mod, "FORMAT", None)
    if type(fmt) is not int or fmt != CONTRACT_FORMAT:
        return ["FORMAT %r is not the int %d" % (fmt, CONTRACT_FORMAT)]
    if tuple(getattr(mod, "SLOT_PATHS", ())) != CONTRACT_SLOT_PATHS:
        errs.append("SLOT_PATHS are not the seven kind 2 slots in slot order")
    uids = tuple(getattr(mod, "SLOT_UIDS", ()))
    if len(uids) != len(CONTRACT_SLOT_PATHS) or not all(isinstance(u, int) and not isinstance(u, bool) and 0 <= u <= 0xFFFFFFFF
                                                        for u in uids):
        errs.append("SLOT_UIDS must be seven u32 ints")
    elif getattr(mod, "DIGEST", None) != digest_of(uids):
        errs.append("DIGEST %r is not FNV-1 32 of SLOT_UIDS (0x%08X): a hand-edited contract?" % (getattr(mod, "DIGEST", None),
                                                                                                 digest_of(uids)))
    for name in CONTRACT_CONSTANTS:
        if not _num(getattr(mod, name, None)):
            errs.append("%s missing or not a number" % name)
    profiles = getattr(mod, "PROFILES", None)
    if not isinstance(profiles, dict):
        return errs + ["PROFILES is not a dict of id: row"]
    compiled = []
    for pid, row in sorted(profiles.items(), key=lambda kv: kv[0] if isinstance(kv[0], int) else -1):
        if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 0xFF:
            errs.append("profile id %r is not in 1..255 (0 is never bound)" % (pid,))
            continue
        if not isinstance(row, dict) or set(row) != set(PROFILE_KEYS):
            errs.append("profile %d: keys are not %s" % (pid, ", ".join(PROFILE_KEYS)))
            continue
        if row["compiled"] is True:
            compiled.append(pid)
            sm = row["steer_max"]
            if not (_num(sm) and 0 < sm <= STEER_MAX_LIMIT):          # a NaN fails too
                errs.append("compiled profile %d: steer_max %r is outside (0, %r] rad" % (pid, sm, STEER_MAX_LIMIT))
            if not (isinstance(row["l_mm"], int) and not isinstance(row["l_mm"], bool) and row["l_mm"] > 0):
                errs.append("compiled profile %d: l_mm %r is not a positive int" % (pid, row["l_mm"]))
            bad = [k for k in PROFILE_LIMITS if not (_num(row[k]) and row[k] > 0)]
            if bad:
                errs.append("compiled profile %d: %s not positive numbers" % (pid, ", ".join(bad)))
        elif row["compiled"] is not False:
            errs.append("profile %d: compiled %r is not a bool" % (pid, row["compiled"]))
        w = row["run_window_max_ms"]
        if w is not None and not (isinstance(w, int) and not isinstance(w, bool) and w > 0):
            errs.append("profile %d: run_window_max_ms %r is not None or a positive int" % (pid, w))
    if tuple(getattr(mod, "COMPILED_PROFILE_IDS", ())) != tuple(compiled):
        errs.append("COMPILED_PROFILE_IDS %r are not the compiled rows' ids %r" % (getattr(mod, "COMPILED_PROFILE_IDS", None),
                                                                                 tuple(compiled)))
    return errs


def load_contract(path: Any) -> Any:
    """Load the kind 2 contract module from this file (a directory means its vss_ctl.py), by path: it is never put
    into sys.modules under a name and leaves no bytecode beside it. ContractError when it is missing or breaks a
    loader rule (contract_errors)."""
    p = Path(path)
    if p.is_dir():
        p = p / "vss_ctl.py"
    p = p.resolve()
    if not p.is_file():
        raise ContractError("no kind 2 contract at %s (sdv/vss/generate.py writes vss_ctl.py from WP1b on)" % p)
    name = "vss_ctl_%08x" % fnv1_32(str(p).encode())
    spec = importlib.util.spec_from_file_location(name, str(p))
    if spec is None or spec.loader is None:
        raise ContractError("cannot import %s" % p)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    except Exception as err:  # noqa: BLE001 -- any failure to execute the file is a contract that does not load
        raise ContractError("%s does not load: %s: %s" % (p, type(err).__name__, err)) from err
    finally:
        sys.dont_write_bytecode = saved
    errs = contract_errors(mod)
    if errs:
        raise ContractError("%s: %s" % (p, "; ".join(errs)))
    mod.__dict__["CONTRACT_PATH"] = str(p)
    return mod


def contract_sha256(contract: Any) -> str:
    """The sha256 of the contract file a loaded module came from (the run header carries it)."""
    path = getattr(contract, "CONTRACT_PATH", None) or contract.__file__
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
