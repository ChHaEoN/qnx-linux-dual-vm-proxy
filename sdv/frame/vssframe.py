"""vssframe.py -- the kind 4 `vss` claim frame: encode and decode (sdv/frame).

The kind 4 wire specification (the project's local design notes,
section 2; not in this tree) defines the layout; the 64-byte frame it lives in is the repo's
(ipc-test/common/frame.h: a 16-byte header of seq and tstamp, u64 little-endian, then a 48-byte
payload; ipc-test/qnx-safety-monitor/monitor.c: verdict at payload[6], reason [7], stamp t_in [8..15]
and t_out [16..23], kind [24]).

    p[n]      frame   field
    0         16      flags: b0 speed, b1 longitudinal acceleration, b2 steering angle, b3 yaw rate,
                      b4 gear, each "a value is present"; b5..b7 zero
    1         17      profile id (an opaque key into the compiled table the specification gives the guest)
    2..5      18..21  catalogue digest, u32 (the generated CATALOG_DIGEST)
    6, 7      22, 23  verdict, reason: zero in a request; the specification has the monitor write them
    8..23     24..39  zero in a request; t_in, t_out (u64 ns) in a stamp reply
    24        40      kind = 4
    25..40    41..56  four f32: v [m/s], a_x [m/s^2], delta [degrees], psi_dot [degrees/s]
    41..42    57..58  u16 age [ms] of the oldest value, saturated at 0xFFFF
    43        59      i8 gear
    44..47    60..63  reserved, zero

Every multi-byte field is little-endian. A value's VSS identity is implied by its slot; the digest
binds the five slots to one catalogue. An absent slot is all zero bytes (0.0, never -0.0).

This module is the codec only. It refuses a frame that is malformed (the layout rules the specification
has the monitor answer with reason 10 in Phase 2; plus the length, the seq, the kind and the verdict and
reason bytes), never one that is well formed but breaks a rule: an unbound profile, a wrong digest, a
stale age or an over-limit value must reach the monitor, so injection can produce them. A non-finite
value is refused by `encode` (no honest source sends one) and packed only through `pack_bits`, which
takes each slot's exact binary32 bits (a signalling NaN does not survive a Python float). It imports
nothing outside the standard library, and no gRPC.

What the layout forbids is never written by `encode` or `pack_bits`, and `decode` refuses all of it.
Two kinds. The layout rules the specification has the monitor reject with reason 10: the flags'
reserved bits b5..b7 (flags are derived from which slots are present), non-zero p[8..23], non-zero
p[44..47], non-zero bytes in an absent slot (an absent slot is packed as all zero), and a non-zero age
(p[41..42]) with no value present (b0..b4 all clear). Fields `decode` refuses on its own: a length
other than 64 bytes, a verdict or reason byte in a request (p[6..7]: the specification has the monitor
overwrite them, never judge them), in a reply a verdict other than 0 or 1 or a reason that is not zero
exactly when the verdict is, a zero or sentinel seq, and a kind other than 4. The bridge's reserved-bit
injection mode (spec 14.4), and any test that sets one of these bytes, is a byte patch on the packed
frame, as the tests build them, not a codec option.

The generated contract (sdv-out/gen/vss_contract.py, written by sdv/vss/generate.py) is loaded by
path; `SDV_GEN` names another generation directory.
"""
from __future__ import annotations

import importlib.util
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
DEFAULT_GEN = REPO / "sdv-out" / "gen"

# The frame the payload lives in (ipc-test/common/frame.h).
FRAME_HEADER_BYTES = 16
FRAME_PAYLOAD_BYTES = 48
FRAME_TOTAL_BYTES = FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES
SENTINEL_SEQ = (1 << 64) - 1          # FRAME_SENTINEL_SEQ: a keepalive, echoed untouched, never judged

KIND_VSS = 4

# Payload offsets (wire specification, section 2).
P_FLAGS = 0
P_PROFILE = 1
P_DIGEST = 2
P_VERDICT = 6
P_REASON = 7
P_T_IN = 8
P_T_OUT = 16
P_KIND = 24
P_V = 25
P_AX = 29
P_DELTA = 33
P_PSI_DOT = 37
P_AGE = 41
P_GEAR = 43
P_RESERVED = 44
STAMP_SPAN = (8, 24)                  # p[8..23]
RESERVED_SPAN = (44, 48)              # p[44..47]

# Slots: 0..3 are f32, 4 is the i8 gear. Offsets in the payload.
F32_SLOT_OFFSETS = (P_V, P_AX, P_DELTA, P_PSI_DOT)
SLOT_SPANS = ((P_V, P_V + 4), (P_AX, P_AX + 4), (P_DELTA, P_DELTA + 4), (P_PSI_DOT, P_PSI_DOT + 4), (P_GEAR, P_GEAR + 1))
F_SPEED, F_ACCEL, F_STEER, F_YAW, F_GEAR = 0x01, 0x02, 0x04, 0x08, 0x10
F_SLOTS = 0x1F
F_RESERVED = 0xE0
N_SLOTS = len(SLOT_SPANS)             # one staticUID per slot in the generated contract's SLOT_UIDS

AGE_SATURATED = 0xFFFF

# The whole frame as the specification writes it (section 2, "Python"): seq, tstamp, flags, profile,
# digest, [6..23] zero, kind, v, a_x, delta, psi_dot, age_ms, gear, [44..47] zero.
KIND4 = struct.Struct("<QQBBI18xB4fHb4x")
# The same layout with each f32 slot as its raw bits, which is how this module packs (so -0.0 and
# every NaN pattern are exact).
_WIRE = struct.Struct("<QQBBI18xB4IHb4x")
assert KIND4.size == _WIRE.size == FRAME_TOTAL_BYTES


class FrameError(ValueError):
    """A frame, or the values for one, that the kind 4 layout does not allow."""


class ContractError(RuntimeError):
    """The generated contract is missing or inconsistent."""


# --- the generated contract ------------------------------------------------------------------

_CONTRACTS: Dict[str, Any] = {}


def fnv1_32(data: bytes) -> int:
    """FNV-1 32 (multiply, then xor; not FNV-1a): the hash vss-tools uses for staticUIDs."""
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def digest_of(uids: Iterable[int]) -> int:
    """The catalogue digest: FNV-1 32 over the slot UIDs as u32 little-endian, in slot order."""
    return fnv1_32(b"".join(struct.pack("<I", u) for u in uids))


def contract_path(gen_dir: Optional[os.PathLike] = None) -> Path:
    base = Path(gen_dir) if gen_dir is not None else Path(os.environ.get("SDV_GEN") or DEFAULT_GEN)
    return base / "vss_contract.py"


def load_contract(gen_dir: Optional[os.PathLike] = None) -> Any:
    """Import the generated vss_contract.py by path (no bytecode left beside it), once per path.

    Refuses a contract with other than N_SLOTS slot UIDs, and one whose digest is not the FNV-1 of its
    own slot UIDs: a hand-edited file."""
    path = contract_path(gen_dir).resolve()
    key = str(path)
    if key in _CONTRACTS:
        return _CONTRACTS[key]
    if not path.is_file():
        raise ContractError("no generated contract at %s: run sdv/vss/generate.py (sdv/vss/README.md)" % path)
    spec = importlib.util.spec_from_file_location("vss_contract_%08x" % (fnv1_32(key.encode()),), str(path))
    if spec is None or spec.loader is None:
        raise ContractError("cannot import %s" % path)
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    if len(mod.SLOT_UIDS) != N_SLOTS:
        raise ContractError("%s: SLOT_UIDS has %d entries, not %d (one per kind 4 slot)" % (path, len(mod.SLOT_UIDS), N_SLOTS))
    if digest_of(mod.SLOT_UIDS) != mod.CATALOG_DIGEST:
        raise ContractError("%s: CATALOG_DIGEST is not FNV-1 32 of its SLOT_UIDS (a hand-edited contract?)" % path)
    _CONTRACTS[key] = mod
    return mod


# --- binary32 helpers ------------------------------------------------------------------------

def f32_bits(x: float) -> int:
    """The binary32 bits of x rounded to float32 (raises FrameError if it overflows float32)."""
    try:
        return struct.unpack("<I", struct.pack("<f", x))[0]
    except (OverflowError, struct.error) as err:
        raise FrameError("%r does not fit a binary32" % (x,)) from err


def bits_f32(bits: int) -> float:
    """The binary32 with these bits, widened to a Python float (exact, except that a signalling NaN
    may come back quieted: keep the bits when the pattern matters)."""
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def f32(x: float) -> float:
    """x rounded to binary32 and widened back: the value a slot carries."""
    return bits_f32(f32_bits(x))


def f32_is_finite_bits(bits: int) -> bool:
    return ((bits >> 23) & 0xFF) != 0xFF


def f32_next_up(x: float) -> float:
    """The next binary32 above the binary32 x (x must already be a binary32 value, finite)."""
    b = f32_bits(x)
    if f32(x) != x:
        raise FrameError("%r is not a binary32 value" % (x,))
    if b == 0x80000000:
        b = 0
    if b & 0x80000000:
        b -= 1
    else:
        b += 1
    return bits_f32(b)


def f32_next_down(x: float) -> float:
    return -f32_next_up(-x)


# --- the claim --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    """One kind 4 claim as the bridge packs it. None = the slot is absent (its flag clear).

    digest None means the loaded contract's CATALOG_DIGEST."""
    seq: int
    tstamp_ns: int
    profile: int
    v: Optional[float] = None
    a_x: Optional[float] = None
    delta: Optional[float] = None
    psi_dot: Optional[float] = None
    gear: Optional[int] = None
    age_ms: int = 0
    digest: Optional[int] = None

    def floats(self) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        return (self.v, self.a_x, self.delta, self.psi_dot)


def _check_int(name: str, x: Any, lo: int, hi: int) -> int:
    if isinstance(x, bool) or not isinstance(x, int):
        raise FrameError("%s must be an int, not %r" % (name, x))
    if not lo <= x <= hi:
        raise FrameError("%s %d outside %d..%d" % (name, x, lo, hi))
    return x


def pack_bits(seq: int, tstamp_ns: int, profile: int, digest: int,
              slot_bits: Sequence[Optional[int]], gear: Optional[int], age_ms: int) -> bytes:
    """Pack a request from raw parts: slot_bits are the four f32 slots' binary32 bits (None = absent).

    The general form, for injection and tests: any bit pattern, any profile byte and digest. It still
    refuses what the layout forbids (a sentinel or zero seq, an out-of-range field, an age with no
    value present). None of the reason-10 layout patterns is injectable here (reserved flag bits,
    non-zero p[8..23] or p[44..47], non-zero bytes in an absent slot, an age with no value present):
    patch the packed bytes (module docstring)."""
    _check_int("seq", seq, 1, SENTINEL_SEQ - 1)
    _check_int("tstamp_ns", tstamp_ns, 0, (1 << 64) - 1)
    _check_int("profile", profile, 0, 0xFF)
    _check_int("digest", digest, 0, 0xFFFFFFFF)
    _check_int("age_ms", age_ms, 0, AGE_SATURATED)
    if len(slot_bits) != 4:
        raise FrameError("four f32 slots, not %d" % len(slot_bits))
    flags = 0
    raw = []
    for i, b in enumerate(slot_bits):
        if b is None:
            raw.append(0)
        else:
            raw.append(_check_int("slot %d bits" % i, b, 0, 0xFFFFFFFF))
            flags |= 1 << i
    g = 0
    if gear is not None:
        g = _check_int("gear", gear, -128, 127)
        flags |= F_GEAR
    if flags == 0 and age_ms != 0:
        raise FrameError("age %d ms with no value present (the age of no value must be 0)" % age_ms)
    return _WIRE.pack(seq, tstamp_ns, flags, profile, digest, KIND_VSS, raw[0], raw[1], raw[2], raw[3], age_ms, g)


def encode(claim: Claim, contract: Any = None) -> bytes:
    """Pack an honest claim: every present value finite and inside binary32. A slot's value is a float or
    an int (an int packs as its float: v=5 is 5.0); a bool is not a number, and an int too large for a
    binary32 is a FrameError like a float too large for one."""
    bits: list = []
    for i, x in enumerate(claim.floats()):
        if x is None:
            bits.append(None)
            continue
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise FrameError("slot %d: %r is not a number" % (i, x))
        try:
            fx = float(x)
        except OverflowError as err:         # an int beyond a double is beyond a binary32 too
            raise FrameError("slot %d: an integer that does not fit a binary32" % i) from err
        b = f32_bits(fx)
        if not f32_is_finite_bits(b):
            raise FrameError("slot %d: %r is not finite (inject non-finite values with pack_bits)" % (i, x))
        bits.append(b)
    digest = claim.digest
    if digest is None:
        digest = (contract if contract is not None else load_contract()).CATALOG_DIGEST
    return pack_bits(claim.seq, claim.tstamp_ns, claim.profile, digest, bits, claim.gear, claim.age_ms)


@dataclass(frozen=True)
class Decoded:
    seq: int
    tstamp_ns: int
    flags: int
    profile: int
    digest: int
    slot_bits: Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]
    gear: Optional[int]
    age_ms: int
    verdict: int
    reason: int
    t_in_ns: Optional[int]
    t_out_ns: Optional[int]

    def value(self, slot: int) -> Optional[float]:
        b = self.slot_bits[slot]
        return None if b is None else bits_f32(b)

    @property
    def v(self) -> Optional[float]:
        return self.value(0)

    @property
    def a_x(self) -> Optional[float]:
        return self.value(1)

    @property
    def delta(self) -> Optional[float]:
        return self.value(2)

    @property
    def psi_dot(self) -> Optional[float]:
        return self.value(3)


def layout_errors(frame: bytes, reply: bool = False, stamp: bool = False) -> list:
    """Everything that makes these bytes not a well-formed kind 4 frame (empty list = well formed).

    A request has zero verdict and reason bytes; a reply has the monitor's verdict (0 or 1) and a reason
    that is zero exactly when the verdict is; a stamp answer (:7161) is a reply that also carries t_in
    and t_out at p[8..23], so `stamp` implies `reply`."""
    reply = reply or stamp
    errs = []
    if len(frame) != FRAME_TOTAL_BYTES:
        return ["length %d, not %d" % (len(frame), FRAME_TOTAL_BYTES)]
    seq = struct.unpack_from("<Q", frame, 0)[0]
    if seq == SENTINEL_SEQ:
        errs.append("seq is the sentinel (a keepalive, not a claim)")
    elif seq == 0:
        errs.append("seq 0 (the bridge counts from 1)")
    p = frame[FRAME_HEADER_BYTES:]
    if p[P_KIND] != KIND_VSS:
        errs.append("kind %d, not %d" % (p[P_KIND], KIND_VSS))
    f = p[P_FLAGS]
    if f & F_RESERVED:
        errs.append("reserved flag bits 0x%02X" % (f & F_RESERVED))
    if not reply:
        if p[P_VERDICT] or p[P_REASON]:
            errs.append("verdict/reason bytes non-zero in a request")
    else:
        if p[P_VERDICT] not in (0, 1):
            errs.append("verdict %d" % p[P_VERDICT])
        elif (p[P_VERDICT] == 0) != (p[P_REASON] == 0):
            errs.append("verdict %d with reason %d" % (p[P_VERDICT], p[P_REASON]))
    if not stamp and any(p[STAMP_SPAN[0]:STAMP_SPAN[1]]):
        errs.append("p[8..23] non-zero")
    if any(p[RESERVED_SPAN[0]:RESERVED_SPAN[1]]):
        errs.append("reserved p[44..47] non-zero")
    for slot, (lo, hi) in enumerate(SLOT_SPANS):
        if not f & (1 << slot) and any(p[lo:hi]):
            errs.append("slot %d absent but its bytes are non-zero" % slot)
    if not f & F_SLOTS and (p[P_AGE] | p[P_AGE + 1]):
        errs.append("age non-zero with no value present")
    return errs


def decode(frame: bytes, reply: bool = False, stamp: bool = False) -> Decoded:
    """Unpack a kind 4 request; with reply, the monitor's answer (verdict and reason written); with stamp,
    a :7161 answer: a reply with t_in and t_out at p[8..23] (stamp implies reply, ACCEPT or REJECT)."""
    frame = bytes(frame)
    errs = layout_errors(frame, reply=reply, stamp=stamp)
    if errs:
        raise FrameError("malformed kind 4 frame: " + "; ".join(errs))
    seq, tstamp, flags, profile, digest, _kind, b0, b1, b2, b3, age, gear = _WIRE.unpack(frame)
    bits = tuple(b if flags & (1 << i) else None for i, b in enumerate((b0, b1, b2, b3)))
    p = frame[FRAME_HEADER_BYTES:]
    t_in = t_out = None
    if stamp:
        t_in, t_out = struct.unpack_from("<QQ", p, P_T_IN)
    return Decoded(seq=seq, tstamp_ns=tstamp, flags=flags, profile=profile, digest=digest,
                   slot_bits=bits,  # type: ignore[arg-type]
                   gear=gear if flags & F_GEAR else None, age_ms=age,
                   verdict=p[P_VERDICT], reason=p[P_REASON], t_in_ns=t_in, t_out_ns=t_out)


# --- the age field ----------------------------------------------------------------------------

def age_field(now_ns: int, sample_ns: Iterable[int]) -> Tuple[int, bool]:
    """The age of the oldest used value at packing: (now - oldest) truncated to ms, saturated at
    0xFFFF; a negative difference is sent as 0 and reported (the bridge counts it as age_negative).
    No value used gives (0, False)."""
    samples = list(sample_ns)
    if not samples:
        return 0, False
    diff = now_ns - min(samples)
    if diff < 0:
        return 0, True
    return min(diff // 1_000_000, AGE_SATURATED), False
