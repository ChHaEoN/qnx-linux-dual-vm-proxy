"""vectors.py -- the test-time vector writer for the Rust kind 4 codec (sdv/claimrs; SDV Phase 9, rustcpp R1).

It writes what sdv/frame/vssframe.py (the codec) and sdv/frame/rules.py (the reference judge) say about a set
of inputs, in the text format `vssclaim vectors` and `vssclaim probe` read (src/bin/vssclaim.rs), so the Rust
codec is held to the Python one record by record. tests/test_sdv_claimrs.py runs it into pytest's tmp
directory; nothing it writes is committed, so it cannot go stale after the contract is regenerated. It
imports vssframe.py and rules.py by path, and the generated contract only through vssframe.load_contract.

THE FORMAT. ASCII text, one record per line, LF, fields separated by one tab. Integers are decimal (gear
signed, nothing else), and bytes and bit patterns are lowercase hex: a digest as 8 digits, a binary32 as 8, a
double as the 16 digits of its IEEE 754 bits, a frame as 128. `-` is an absent value. The first line is the
format and its version, `claimrs-vectors<TAB>1`; then these header lines, in this order:

    contract_sha256   sha256 of the vss_contract.py the file was written from
    catalog_digest    its CATALOG_DIGEST, which must be FNV-1 32 of slot_uids (vssclaim refuses a file where not)
    slot_uids         its five SLOT_UIDS, comma-separated
    seed              the seed of the seeded records (the C21 corpus' for an rt file)
    records           the number of records that follow
    rt_records, rt_encode_bases, rt_patched    how many rt records, how many have an encode base, how many a patch

and the records:

    enc   NAME SEQ TSTAMP PROFILE DIGEST V A_X DELTA PSI_DOT GEAR AGE  frame HEX | error CODE
    pack  NAME SEQ TSTAMP PROFILE DIGEST B0 B1 B2 B3 GEAR AGE          frame HEX | error CODE
    dec   NAME MODE HEX  error CODE,CODE...
    dec   NAME MODE HEX  decoded SEQ TSTAMP FLAGS PROFILE DIGEST B0 B1 B2 B3 GEAR AGE VERDICT REASON T_IN T_OUT
    age   NAME NOW SAMPLES AGE NEGATIVE        (SAMPLES comma-separated or -, NEGATIVE 0 or 1)
    rt    NAME enc|pack SEQ TSTAMP PROFILE DIGEST S0 S1 S2 S3 GEAR AGE REQUEST PATCH REPLY

MODE is request, reply or stamp (stamp implies reply), as vssframe's layout_errors and decode take them. A
dec frame may have any length (the length branch needs other lengths); a frame anywhere else is 64 bytes.
PATCH is - or comma-separated OFF=VV items: OFF a frame offset (decimal, ascending), VV the byte sent there.

THE CODES. A refusal is compared as a code, never as message text: one code per layout_errors branch
(LAYOUT_PATTERNS, one pattern each, the slot branch one per slot) and five for encode and pack_bits
(ENCODE_PATTERNS). A message no pattern takes, or more than one, is refused: a new branch in vssframe.py
fails this writer, not the comparison. vssframe raises one message for seq 0 and for the sentinel, so an enc
or pack record's seq code comes from the seq's value.

THE rt RULE. An rt record carries a frame to send as a base claim, Python's packing of
that base (REQUEST), the byte patch that turns REQUEST into the frame, and rules.reply() of the frame
(REPLY). The base comes from the frame's own bytes: seq, tstamp, profile, digest, the slots whose flag bit is
set, gear when F_GEAR is set, and the age (0 when no flag bit is set). It is an encode base, each value the
binary32 widened to a double, when every present slot is finite, and a pack_bits base with the raw bits
otherwise. The patch may touch only the flags byte's reserved bits, p[6..23], the bytes of an absent slot
(gear's included), the age when no value is present, and p[44..47]; a frame it cannot express that way (a
kind other than 4, a seq of 0 or the sentinel, a length other than 64) is refused. vssclaim holds a file to
the same rule, judged from the record's REQUEST: a patch that touches any other byte is refused (exit 2).

This writes test inputs; it measures nothing and holds no result.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import random
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

FRAME_DIR = Path(__file__).resolve().parents[1] / "frame"
FORMAT = "claimrs-vectors\t1"
SEED = 1717                 # the codec file's seeded claims
N_SEEDED = 10000


class WriterError(ValueError):
    """An input this writer refuses to turn into a vector."""


def _by_path(name: str, path: Path) -> ModuleType:
    """The module at `path` under `name`: the one already imported if it is that file, else loaded by path
    (no bytecode written). rules.py imports vssframe by name, so both must be one module."""
    mod = sys.modules.get(name)
    if mod is not None:
        if Path(getattr(mod, "__file__", "") or "").resolve() != path.resolve():
            raise WriterError("a different %s is already imported (%s)" % (name, getattr(mod, "__file__", None)))
        return mod
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise WriterError("cannot import %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    finally:
        sys.dont_write_bytecode = saved
    return mod


vf = _by_path("vssframe", FRAME_DIR / "vssframe.py")
rules = _by_path("rules", FRAME_DIR / "rules.py")

H = vf.FRAME_HEADER_BYTES
SENTINEL = vf.SENTINEL_SEQ
U64_MAX = (1 << 64) - 1
FLT_MAX = struct.unpack("<f", struct.pack("<I", 0x7F7FFFFF))[0]
MIDPOINT = 2.0 ** 128 - 2.0 ** 103          # halfway between FLT_MAX and 2^128, exactly a double
MODES = ("request", "reply", "stamp")


# --- codes -------------------------------------------------------------------------------------------

LAYOUT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"length \d+, not 64", "length"),
    (r"seq is the sentinel \(a keepalive, not a claim\)", "seq-sentinel"),
    (r"seq 0 \(the bridge counts from 1\)", "seq-zero"),
    (r"kind \d+, not 4", "kind"),
    (r"reserved flag bits 0x[0-9A-F]{2}", "flags-reserved"),
    (r"verdict/reason bytes non-zero in a request", "request-verdict"),
    (r"verdict \d+", "reply-verdict"),
    (r"verdict \d+ with reason \d+", "reply-reason"),
    (r"p\[8\.\.23\] non-zero", "stamp-span"),
    (r"reserved p\[44\.\.47\] non-zero", "reserved-span"),
    (r"slot 0 absent but its bytes are non-zero", "absent-slot-0"),
    (r"slot 1 absent but its bytes are non-zero", "absent-slot-1"),
    (r"slot 2 absent but its bytes are non-zero", "absent-slot-2"),
    (r"slot 3 absent but its bytes are non-zero", "absent-slot-3"),
    (r"slot 4 absent but its bytes are non-zero", "absent-slot-4"),
    (r"age non-zero with no value present", "age-without-value"),
)
_LAYOUT = tuple((re.compile(p), code) for p, code in LAYOUT_PATTERNS)

ENCODE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\S+ does not fit a binary32", "overflow"),
    (r"slot [0-3]: \S+ is not finite \(inject non-finite values with pack_bits\)", "not-finite"),
    (r"seq \d+ outside 1\.\.18446744073709551614", "seq"),
    (r"age \d+ ms with no value present \(the age of no value must be 0\)", "age-without-value"),
)
_ENCODE = tuple((re.compile(p), code) for p, code in ENCODE_PATTERNS)


def layout_code(message: str) -> str:
    """The code of one layout_errors message; WriterError for a message no pattern, or more than one, takes."""
    codes = [code for pat, code in _LAYOUT if pat.fullmatch(message)]
    if len(codes) != 1:
        raise WriterError("an unknown layout_errors message %r (it matches %d patterns)" % (message, len(codes)))
    return codes[0]


def layout_codes(frame: bytes, mode: str) -> List[str]:
    """The codes of vssframe.layout_errors(frame) in this mode, in its order; two messages to one code refused."""
    msgs = vf.layout_errors(bytes(frame), reply=mode != "request", stamp=mode == "stamp")
    codes = [layout_code(m) for m in msgs]
    if len(set(codes)) != len(codes):
        raise WriterError("two layout_errors messages map to one code: %r" % msgs)
    return codes


def encode_code(message: str, seq: int) -> str:
    """The code of an encode or pack_bits refusal; the seq's code from its value (one message for both)."""
    codes = [code for pat, code in _ENCODE if pat.fullmatch(message)]
    if len(codes) != 1:
        raise WriterError("an unknown encode message %r (it matches %d patterns)" % (message, len(codes)))
    if codes[0] != "seq":
        return codes[0]
    if seq == 0:
        return "seq-zero"
    if seq == SENTINEL:
        return "seq-sentinel"
    raise WriterError("an unknown encode message %r for seq %d" % (message, seq))


# --- fields ------------------------------------------------------------------------------------------

def _int(x: Any, lo: int, hi: int, what: str) -> str:
    if isinstance(x, bool) or not isinstance(x, int) or not lo <= x <= hi:
        raise WriterError("%s %r is not an integer in %d..%d" % (what, x, lo, hi))
    return str(x)


def _f64(x: Optional[float]) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool) or not isinstance(x, float):
        raise WriterError("a slot value must be a float, not %r" % (x,))
    return struct.pack(">d", x).hex()


def _b32(b: Optional[int]) -> str:
    return "-" if b is None else "%08x" % int(_int(b, 0, 0xFFFFFFFF, "binary32 bits"))


def _gear(g: Optional[int]) -> str:
    return "-" if g is None else _int(g, -128, 127, "gear")


def _common(seq: int, tstamp: int, profile: int, digest: int) -> List[str]:
    return [_int(seq, 0, U64_MAX, "seq"), _int(tstamp, 0, U64_MAX, "tstamp"), _int(profile, 0, 255, "profile"),
            "%08x" % int(_int(digest, 0, 0xFFFFFFFF, "digest"))]


def _line(fields: Sequence[str]) -> str:
    for f in fields:
        if "\t" in f or "\n" in f:
            raise WriterError("a field with a tab or a newline: %r" % (f,))
    return "\t".join(fields)


# --- records -----------------------------------------------------------------------------------------

def enc_record(name: str, claim: Any) -> str:
    """One enc record: encode(claim) as vssframe does it (the claim's digest given), or its refusal's code."""
    if claim.digest is None:
        raise WriterError("%s: an enc claim carries its digest" % name)
    fields = ["enc", name] + _common(claim.seq, claim.tstamp_ns, claim.profile, claim.digest)
    fields += [_f64(x) for x in claim.floats()] + [_gear(claim.gear), _int(claim.age_ms, 0, 0xFFFF, "age")]
    try:
        fields += ["frame", vf.encode(claim).hex()]
    except vf.FrameError as err:
        fields += ["error", encode_code(str(err), claim.seq)]
    return _line(fields)


def pack_record(name: str, seq: int, tstamp: int, profile: int, digest: int, bits: Sequence[Optional[int]],
                gear: Optional[int], age: int) -> str:
    """One pack record: pack_bits as vssframe does it, or its refusal's code."""
    if len(bits) != 4:
        raise WriterError("%s: four slots" % name)
    fields = ["pack", name] + _common(seq, tstamp, profile, digest) + [_b32(b) for b in bits]
    fields += [_gear(gear), _int(age, 0, 0xFFFF, "age")]
    try:
        fields += ["frame", vf.pack_bits(seq, tstamp, profile, digest, tuple(bits), gear, age).hex()]
    except vf.FrameError as err:
        fields += ["error", encode_code(str(err), seq)]
    return _line(fields)


def dec_record(name: str, frame: bytes, mode: str) -> str:
    """One dec record: decode(frame) in this mode as vssframe does it, or the set of its refusals' codes."""
    if mode not in MODES:
        raise WriterError("%s: no mode %r" % (name, mode))
    frame = bytes(frame)
    fields = ["dec", name, mode, frame.hex()]
    codes = layout_codes(frame, mode)
    if codes:
        return _line(fields + ["error", ",".join(sorted(codes))])
    d = vf.decode(frame, reply=mode != "request", stamp=mode == "stamp")
    fields += ["decoded", str(d.seq), str(d.tstamp_ns), "%02x" % d.flags, str(d.profile), "%08x" % d.digest]
    fields += [_b32(b) for b in d.slot_bits] + [_gear(d.gear), str(d.age_ms), str(d.verdict), str(d.reason)]
    fields += ["-" if d.t_in_ns is None else str(d.t_in_ns), "-" if d.t_out_ns is None else str(d.t_out_ns)]
    return _line(fields)


def age_record(name: str, now: int, samples: Sequence[int]) -> str:
    age, negative = vf.age_field(now, samples)
    fields = ["age", name, _int(now, 0, U64_MAX, "now")]
    fields.append(",".join(_int(s, 0, U64_MAX, "sample") for s in samples) if samples else "-")
    return _line(fields + [str(age), "1" if negative else "0"])


@dataclass(frozen=True)
class Rt:
    """One rt record: the base (kind and fields), Python's packing of it, the patch, the frame sent, the reply."""
    name: str
    base_kind: str
    base: Tuple[str, ...]
    request: bytes
    patch: Tuple[Tuple[int, int], ...]
    sent: bytes
    reply: bytes

    def line(self) -> str:
        patch = ",".join("%d=%02x" % (off, v) for off, v in self.patch) or "-"
        return _line(("rt", self.name, self.base_kind) + self.base + (self.request.hex(), patch, self.reply.hex()))


def _u32(p: bytes, off: int) -> int:
    return int(struct.unpack_from("<I", p, off)[0])


def _patchable(o: int, flags: int, diff: int) -> bool:
    """May a patch change payload byte o (diff = the bits it changes) of a frame with these flags?"""
    if o == vf.P_FLAGS:
        return diff & ~vf.F_RESERVED == 0
    if vf.P_VERDICT <= o < vf.STAMP_SPAN[1] or vf.RESERVED_SPAN[0] <= o < vf.RESERVED_SPAN[1]:
        return True
    if o in (vf.P_AGE, vf.P_AGE + 1):
        return flags & vf.F_SLOTS == 0
    for slot, (lo, hi) in enumerate(vf.SLOT_SPANS):
        if lo <= o < hi:
            return flags & (1 << slot) == 0
    return False


def rt_record(name: str, frame: bytes, tables: Any) -> Rt:
    """The rt record of a frame to send, by the rt rule (module docstring); WriterError if it cannot express it."""
    frame = bytes(frame)
    if len(frame) != vf.FRAME_TOTAL_BYTES:
        raise WriterError("%s: the rt rule cannot express a frame of %d bytes" % (name, len(frame)))
    seq, tstamp = struct.unpack_from("<QQ", frame, 0)
    p = frame[H:]
    f = p[vf.P_FLAGS]
    profile, digest = p[vf.P_PROFILE], _u32(p, vf.P_DIGEST)
    bits = tuple(_u32(p, off) if f & (1 << i) else None for i, off in enumerate(vf.F32_SLOT_OFFSETS))
    gear = (p[vf.P_GEAR] ^ 0x80) - 0x80 if f & vf.F_GEAR else None
    age = struct.unpack_from("<H", p, vf.P_AGE)[0] if f & vf.F_SLOTS else 0
    try:
        if all(b is None or vf.f32_is_finite_bits(b) for b in bits):
            values = tuple(None if b is None else vf.bits_f32(b) for b in bits)
            claim = vf.Claim(seq=seq, tstamp_ns=tstamp, profile=profile, v=values[0], a_x=values[1], delta=values[2],
                             psi_dot=values[3], gear=gear, age_ms=age, digest=digest)
            request = vf.encode(claim)
            kind, slots = "enc", [_f64(x) for x in values]
        else:
            request = vf.pack_bits(seq, tstamp, profile, digest, bits, gear, age)
            kind, slots = "pack", [_b32(b) for b in bits]
    except vf.FrameError as err:
        raise WriterError("%s: the rt rule cannot express this frame: %s" % (name, err)) from err
    patch = tuple((i, frame[i]) for i in range(vf.FRAME_TOTAL_BYTES) if frame[i] != request[i])
    for off, v in patch:
        if off < H or not _patchable(off - H, f, v ^ request[off]):
            raise WriterError("%s: frame byte %d (p[%d]) differs from the base and is not patchable" % (name, off, off - H))
    base = tuple(_common(seq, tstamp, profile, digest) + slots + [_gear(gear), str(age)])
    return Rt(name, kind, base, request, patch, frame, rules.reply(frame, tables))


# --- the files ---------------------------------------------------------------------------------------

def _header(contract: Any, seed: int, records: Sequence[str], rts: Sequence[Rt]) -> List[str]:
    uids = tuple(int(u) for u in contract.SLOT_UIDS)
    if vf.digest_of(uids) != contract.CATALOG_DIGEST:
        raise WriterError("the contract's CATALOG_DIGEST is not FNV-1 32 of its SLOT_UIDS")
    return [FORMAT,
            "contract_sha256\t" + hashlib.sha256(Path(contract.__file__).read_bytes()).hexdigest(),
            "catalog_digest\t%08x" % contract.CATALOG_DIGEST,
            "slot_uids\t" + ",".join("%08x" % u for u in uids),
            "seed\t" + _int(seed, 0, U64_MAX, "seed"),
            "records\t%d" % len(records),
            "rt_records\t%d" % len(rts),
            "rt_encode_bases\t%d" % sum(1 for r in rts if r.base_kind == "enc"),
            "rt_patched\t%d" % sum(1 for r in rts if r.patch)]


def _write(path: Any, contract: Any, seed: int, records: List[str], rts: Sequence[Rt]) -> Dict[str, int]:
    names = [ln.split("\t", 2)[1] for ln in records]
    if len(set(names)) != len(names):
        raise WriterError("duplicate vector names")
    lines = _header(contract, seed, records, rts) + records
    Path(path).write_bytes(("\n".join(lines) + "\n").encode("ascii"))
    return {"records": len(records), "rt_records": len(rts), "rt_encode_bases": sum(1 for r in rts if r.base_kind == "enc"),
            "rt_patched": sum(1 for r in rts if r.patch)}


def write_rt(path: Any, frames: Iterable[bytes], contract: Any = None, tables: Any = None, seed: int = 0) -> Dict[str, int]:
    """An rt file of these frames, in their order (named by seq); refuses the whole file if one frame is refused."""
    contract = contract if contract is not None else vf.load_contract()
    tables = tables if tables is not None else rules.Tables.from_contract(contract)
    rts = [rt_record("rt/seq-%d" % struct.unpack_from("<Q", fr)[0], fr, tables) for fr in frames]
    return _write(path, contract, seed, [r.line() for r in rts], rts)


def write_codec(path: Any, contract: Any = None, tables: Any = None, seed: int = SEED, n_seeded: int = N_SEEDED) -> Dict[str, int]:
    """The codec file: enc and pack edges, n_seeded seeded claims, the dec branches, pairs and sweeps, the age grid,
    and rt records of build_cases' frames and of the patchable reason 10 kinds."""
    contract = contract if contract is not None else vf.load_contract()
    tables = tables if tables is not None else rules.Tables.from_contract(contract)
    records: List[str] = []
    records += _enc_edges(contract)
    records += _pack_edges(contract)
    records += _seeded(contract, seed, n_seeded)
    records += _dec_records(contract, tables)
    records += _age_grid()
    rts = _rt_examples(contract, tables)
    return _write(path, contract, seed, records + [r.line() for r in rts], rts)


# --- the codec file's contents -----------------------------------------------------------------------

def _claim(contract: Any, **kw: Any) -> Any:
    base: Dict[str, Any] = dict(seq=1, tstamp_ns=0x0102030405060708, profile=1, digest=contract.CATALOG_DIGEST)
    base.update(kw)
    return vf.Claim(**base)


def _next_down(x: float) -> float:
    """The double just below a positive finite double."""
    return float(struct.unpack("<d", struct.pack("<Q", struct.unpack("<Q", struct.pack("<d", x))[0] - 1))[0])


def _enc_edges(contract: Any) -> List[str]:
    c = lambda **kw: _claim(contract, **kw)  # noqa: E731
    inf, nan = float("inf"), float("nan")
    edges = [
        ("zero-pos", c(v=0.0)), ("zero-neg", c(v=-0.0)),
        ("min-subnormal", c(v=2.0 ** -149)), ("half-min-subnormal", c(v=2.0 ** -150)), ("neg-half-min-subnormal", c(v=-(2.0 ** -150))),
        ("three-halves-min-subnormal", c(v=3 * 2.0 ** -150)), ("max-subnormal", c(v=(2.0 ** 23 - 1) * 2.0 ** -149)),
        ("tie-even-down", c(v=1.0 + 2.0 ** -24)), ("tie-even-up", c(v=1.0 + 3 * 2.0 ** -24)),
        ("tie-even-neg", c(a_x=-(1.0 + 2.0 ** -24))), ("above-tie", c(v=1.0 + 2.0 ** -24 + 2.0 ** -52)),
        ("flt-max", c(v=FLT_MAX)), ("neg-flt-max", c(delta=-FLT_MAX)), ("below-midpoint", c(v=_next_down(MIDPOINT))),
        ("midpoint", c(v=MIDPOINT)), ("neg-midpoint", c(v=-MIDPOINT)), ("1e39", c(v=1e39)), ("neg-1e39", c(psi_dot=-1e39)),
        ("double-max", c(v=1.7976931348623157e308)), ("double-min-subnormal", c(v=5e-324)),
        ("inf-pos", c(v=inf)), ("inf-neg", c(a_x=-inf)), ("nan", c(v=nan)),
        ("gear-min", c(gear=-128)), ("gear-max", c(gear=127)), ("gear-zero", c(gear=0)), ("gear-absent", c(v=1.0)),
        ("age-0", c(v=1.0, age_ms=0)), ("age-1", c(v=1.0, age_ms=1)), ("age-max", c(v=1.0, age_ms=0xFFFF)),
        ("seq-1", c(v=1.0, seq=1)), ("seq-max-1", c(v=1.0, seq=SENTINEL - 1)), ("seq-0", c(v=1.0, seq=0)),
        ("seq-sentinel", c(v=1.0, seq=SENTINEL)), ("tstamp-0", c(v=1.0, tstamp_ns=0)), ("tstamp-max", c(v=1.0, tstamp_ns=U64_MAX)),
        ("profile-0", c(v=1.0, profile=0)), ("profile-255", c(v=1.0, profile=255)),
        ("digest-0", c(v=1.0, digest=0)), ("digest-max", c(v=1.0, digest=0xFFFFFFFF)),
        ("slot-0-alone", c(v=1.5)), ("slot-1-alone", c(a_x=-2.25)), ("slot-2-alone", c(delta=3.0625)),
        ("slot-3-alone", c(psi_dot=-4.5)), ("slot-4-alone", c(gear=2)),
        ("all-five", c(v=5.0, a_x=-0.75, delta=12.5, psi_dot=-7.25, gear=-1, age_ms=33)),
        ("empty", c()), ("age-no-value", c(age_ms=5)),
        ("order-overflow-0-nonfinite-3", c(v=1e39, psi_dot=inf)),
        ("order-nonfinite-0-overflow-3", c(v=nan, psi_dot=1e39)),
        ("order-overflow-1-nonfinite-2", c(a_x=-1e39, delta=nan)),
        ("order-bad-slot-seq-0", c(seq=0, v=1e39)), ("order-nonfinite-slot-seq-sentinel", c(seq=SENTINEL, delta=inf)),
        ("order-bad-slot-age-no-value", c(v=nan, age_ms=0)),
        ("order-seq-0-age-no-value", c(seq=0, age_ms=5)), ("order-sentinel-age-no-value", c(seq=SENTINEL, age_ms=0xFFFF)),
    ]
    return [enc_record("enc/" + n, cl) for n, cl in edges]


def _pack_edges(contract: Any) -> List[str]:
    d = contract.CATALOG_DIGEST
    t = 0x0102030405060708
    rows: List[Tuple[str, Tuple[Any, ...]]] = [
        ("snan", (1, t, 1, d, (0x7F800001, None, None, None), None, 0)),
        ("all-ones", (1, t, 1, d, (None, 0xFFFFFFFF, None, None), None, 0)),
        ("neg-zero", (1, t, 1, d, (None, None, 0x80000000, None), None, 0)),
        ("qnan", (1, t, 1, d, (None, None, None, 0x7FC00000), None, 0)),
        ("inf", (1, t, 1, d, (0x7F800000, 0xFF800000, None, None), 5, 9)),
        ("subnormal", (1, t, 1, d, (0x00000001, 0x807FFFFF, None, None), None, 0)),
        ("every-slot", (7, t, 3, d, (0x40A00000, 0xBF400000, 0x41480000, 0xC0E80000), -128, 0xFFFF)),
        ("seq-0", (0, t, 1, d, (0x3F800000, None, None, None), None, 0)),
        ("seq-sentinel", (SENTINEL, t, 1, d, (0x3F800000, None, None, None), None, 0)),
        ("age-no-value", (1, t, 1, d, (None, None, None, None), None, 1)),
        ("order-seq-0-age-no-value", (0, t, 1, d, (None, None, None, None), None, 5)),
        ("order-sentinel-age-no-value", (SENTINEL, t, 1, d, (None, None, None, None), None, 0xFFFF)),
    ]
    return [pack_record("pack/" + n, *args) for n, args in rows]


def _seeded_value(rng: random.Random) -> float:
    k = rng.random()
    if k < 0.35:
        return rng.uniform(-40.0, 40.0)                                    # inside the profiles' limits, roughly
    if k < 0.55:
        return rng.uniform(-1e6, 1e6)                                      # out of limit, still a binary32
    if k < 0.70:
        bits = rng.getrandbits(32)                                         # an exact binary32 (subnormals too)
        return vf.bits_f32(bits) if vf.f32_is_finite_bits(bits) else 0.0
    if k < 0.80:
        x = vf.bits_f32(rng.randrange(0x7F7FFFFF))                         # halfway to the next binary32: a tie
        return rng.choice((1.0, -1.0)) * (x + (vf.f32_next_up(x) - x) / 2)
    if k < 0.90:
        return rng.uniform(3.0e38, 3.5e38) * rng.choice((1.0, -1.0))       # around FLT_MAX, overflow among them
    return float(struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0])   # any double: NaN, inf, tiny, huge


def _seeded(contract: Any, seed: int, n: int) -> List[str]:
    """n seeded claims, honest and out of limit, and a dec record of each one encode packs."""
    rng = random.Random(seed)
    out, decs = [], []
    for i in range(n):
        k = rng.random()
        seq = 0 if k < 0.01 else SENTINEL if k < 0.02 else rng.randrange(1, SENTINEL)
        vals = [_seeded_value(rng) if rng.random() < 0.75 else None for _ in range(4)]
        gear = rng.randint(-128, 127) if rng.random() < 0.7 else None
        present = gear is not None or any(v is not None for v in vals)
        age = rng.choice((0, 1, rng.randrange(0x10000), rng.randrange(3000))) if present or rng.random() < 0.3 else 0
        claim = _claim(contract, seq=seq, tstamp_ns=rng.getrandbits(64), profile=rng.randrange(256),
                       digest=contract.CATALOG_DIGEST if rng.random() < 0.7 else rng.getrandbits(32),
                       v=vals[0], a_x=vals[1], delta=vals[2], psi_dot=vals[3], gear=gear, age_ms=age)
        line = enc_record("enc/seeded-%05d" % i, claim)
        out.append(line)
        fields = line.split("\t")
        if fields[12] == "frame":
            decs.append(dec_record("dec/seeded-%05d" % i, bytes.fromhex(fields[13]), "request"))
    return out + decs


def _frame_of(contract: Any, mode: str, full: bool) -> bytes:
    """A frame each mode decodes: every slot present (gear -3, age 7) or none, with a reply's or a stamp's bytes."""
    if full:
        fr = bytearray(vf.encode(_claim(contract, seq=5, v=5.0, a_x=1.0, delta=2.0, psi_dot=3.0, gear=-3, age_ms=7)))
    else:
        fr = bytearray(vf.encode(_claim(contract, seq=5)))
    if mode != "request":
        fr[H + vf.P_VERDICT], fr[H + vf.P_REASON] = 1, 23
    if mode == "stamp":
        struct.pack_into("<QQ", fr, H + vf.P_T_IN, 1_000_000_007, 1_000_000_123)
    return bytes(fr)


Injector = Callable[[bytearray], bytearray]


def _set(off: int, value: int) -> Injector:
    def f(b: bytearray) -> bytearray:
        b[off] = value
        return b
    return f


def _absent(slot: int) -> Injector:
    def f(b: bytearray) -> bytearray:
        b[H] &= ~(1 << slot) & 0xFF
        lo, hi = vf.SLOT_SPANS[slot]
        b[H + hi - 1] |= 0x01                                  # its bytes non-zero, whatever they held
        return b
    return f


def _nothing_present(b: bytearray) -> bytearray:
    b[H] &= ~vf.F_SLOTS & 0xFF
    for lo, hi in vf.SLOT_SPANS:
        b[H + lo:H + hi] = bytes(hi - lo)
    if not b[H + vf.P_AGE] | b[H + vf.P_AGE + 1]:
        b[H + vf.P_AGE] = 9
    return b


def _injectors() -> List[Tuple[str, Injector]]:
    """One injector per layout_errors branch, in an order where any two that can occur together both do when applied
    in it (the age-without-value one before the absent slots, which then make their bytes non-zero again; the
    length last, since a short frame has no p[47])."""
    return [
        ("seq-sentinel", lambda b: bytearray(struct.pack("<Q", SENTINEL)) + b[8:]),
        ("seq-zero", lambda b: bytearray(8) + b[8:]),
        ("kind", _set(H + vf.P_KIND, 5)),
        ("flags-reserved", lambda b: _set(H, b[H] | 0x20)(b)),
        ("request-verdict", _set(H + vf.P_VERDICT, 1)),
        ("reply-verdict", _set(H + vf.P_VERDICT, 2)),
        ("reply-reason", lambda b: _set(H + vf.P_REASON, 0)(_set(H + vf.P_VERDICT, 1)(b))),
        ("stamp-span", _set(H + 15, 0x80)),
        ("reserved-span", _set(H + 47, 0x01)),
        ("age-without-value", _nothing_present),
        ("absent-slot-0", _absent(0)), ("absent-slot-1", _absent(1)), ("absent-slot-2", _absent(2)),
        ("absent-slot-3", _absent(3)), ("absent-slot-4", _absent(4)),
        ("length", lambda b: b[:63]),
    ]


def _dec_records(contract: Any, tables: Any) -> List[str]:
    out: List[str] = []
    inj = _injectors()
    for mode in MODES:
        base = _frame_of(contract, mode, True)
        out.append(dec_record("dec/%s/valid" % mode, base, mode))
        out.append(dec_record("dec/%s/valid-empty" % mode, _frame_of(contract, mode, False), mode))
        usable = [(n, f) for n, f in inj if not (mode == "request" and n in ("reply-verdict", "reply-reason"))
                  and not (mode != "request" and n == "request-verdict") and not (mode == "stamp" and n == "stamp-span")]
        for n, f in usable:
            out.append(dec_record("dec/%s/%s" % (mode, n), bytes(f(bytearray(base))), mode))
        for k in (0, 1, 2, 3, 0xFF):
            out.append(dec_record("dec/%s/kind-%d" % (mode, k), bytes(_set(H + vf.P_KIND, k)(bytearray(base))), mode))
        for (n1, f1), (n2, f2) in itertools.combinations(usable, 2):
            out.append(dec_record("dec/%s/%s+%s" % (mode, n1, n2), bytes(f2(f1(bytearray(base)))), mode))
        for which in ("full", "empty"):
            fr = _frame_of(contract, mode, which == "full")
            for o in range(vf.FRAME_PAYLOAD_BYTES):
                b = bytearray(fr)
                b[H + o] ^= 0x5A
                out.append(dec_record("dec/%s/sweep-%s-p%02d" % (mode, which, o), bytes(b), mode))
        for size in (0, 1, 63, 65, 128):
            out.append(dec_record("dec/%s/length-%d" % (mode, size), (base * 2)[:size], mode))
    accept = _frame_of(contract, "request", True)
    for mode, v, r in (("reply", 0, 5), ("stamp", 0, 9), ("reply", 0, 0), ("stamp", 1, 10), ("reply", 255, 1)):
        b = bytearray(_frame_of(contract, mode, True))
        b[H + vf.P_VERDICT], b[H + vf.P_REASON] = v, r
        out.append(dec_record("dec/%s/verdict-%d-reason-%d" % (mode, v, r), bytes(b), mode))
    out.append(dec_record("dec/request/gear-min", vf.encode(_claim(contract, gear=-128)), "request"))
    out.append(dec_record("dec/stamp/t-max", _stamped(accept, U64_MAX, U64_MAX), "stamp"))
    for case in _cases(contract, tables, 1):
        out.append(dec_record("dec/request/case-" + case.name, case.frame, "request"))
        out.append(dec_record("dec/reply/case-" + case.name, rules.reply(case.frame, tables), "reply"))
    return out


def _stamped(fr: bytes, t_in: int, t_out: int) -> bytes:
    b = bytearray(fr)
    b[H + vf.P_VERDICT], b[H + vf.P_REASON] = 0, 0
    struct.pack_into("<QQ", b, H + vf.P_T_IN, t_in, t_out)
    return bytes(b)


def _age_grid() -> List[str]:
    ms = 1_000_000
    sat = 0xFFFF * ms
    deltas = (0, 1, ms - 1, ms, ms + 1, 2 * ms - 1, 1234 * ms + 999_999, sat - 1, sat, sat + ms - 1, sat + ms, 1 << 62)
    nows = (0, 1, ms - 1, ms, 5 * ms, sat, sat + ms, 1 << 63, U64_MAX - 1, U64_MAX)
    out, i = [], 0
    for now in nows:
        cases: List[List[int]] = [[]]
        cases += [[now - d] for d in deltas if d <= now]
        if now < U64_MAX:
            cases += [[now + 1], [now + 1, max(now - 3 * ms, 0)], [U64_MAX]]
        cases += [[now, max(now - 2 * ms, 0), max(now - 5 * ms, 0)], [0, now]]
        for samples in cases:
            out.append(age_record("age/%03d" % i, now, samples))
            i += 1
    return out


def _cases(contract: Any, tables: Any, start_seq: int) -> List[Any]:
    kc = _by_path("kind4_client", FRAME_DIR / "kind4_client.py")
    return list(kc.build_cases(contract, tables, start_seq=start_seq))


def _rt_examples(contract: Any, tables: Any) -> List[Rt]:
    out = [rt_record("rt/case-" + case.name, case.frame, tables) for case in _cases(contract, tables, 101)]
    f = vf.encode(_claim(contract, seq=200, v=5.0, a_x=1.0, delta=2.0, psi_dot=3.0, gear=1, age_ms=7))
    no_delta = vf.encode(_claim(contract, seq=201, v=5.0, a_x=1.0, psi_dot=3.0, gear=1, age_ms=7))
    no_gear = vf.encode(_claim(contract, seq=202, v=5.0, a_x=1.0, delta=2.0, psi_dot=3.0, age_ms=7))
    nothing = vf.encode(_claim(contract, seq=203))
    for name, fr, pairs in (("reserved-flag", f, [(H, f[H] | 0x40)]), ("stamp-span", f, [(H + 9, 1), (H + 22, 0xFE)]),
                            ("verdict-reason", f, [(H + 6, 0xEE), (H + 7, 0xEE)]),
                            ("absent-f32", no_delta, [(H + vf.P_DELTA + 1, 3)]), ("absent-gear", no_gear, [(H + vf.P_GEAR, 0x80)]),
                            ("age-no-value", nothing, [(H + vf.P_AGE, 1), (H + vf.P_AGE + 1, 1)]),
                            ("reserved-span", f, [(H + 45, 0x10)])):
        b = bytearray(fr)
        for off, v in pairs:
            b[off] = v
        out.append(rt_record("rt/patch-" + name, bytes(b), tables))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Write the claimrs codec vectors (test input, not a result).")
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--gen", type=Path, help="the generation directory (default: vssframe's, or SDV_GEN)")
    args = ap.parse_args(argv)
    counts = write_codec(args.out, vf.load_contract(args.gen), seed=args.seed)
    print("vectors.py: wrote %s: %s" % (args.out, " ".join("%s=%d" % kv for kv in sorted(counts.items()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
