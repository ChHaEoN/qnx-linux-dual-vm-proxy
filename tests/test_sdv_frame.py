"""The kind 4 claim frame (sdv/frame/vssframe.py) and the reference judge (sdv/frame/rules.py): SDV plan
Phase 1 step 8.

The codec is tested against the wire specification's byte layout written out here offset by offset
(the specification's table, not the module's constants), and against the specification's own
struct. The judge is tested reason by reason at each edge, in the specification's order, and for
rule 26 against an independent evaluation with math.tan. Edges at a float limit are placed on binary32
steps; rule 26's tol and a_y edges are placed by computing the rule's own expression, as the
specification's C11 asks, and cross-checked with math.tan so both land on the same side.

Rule 26's arithmetic is also pinned bit for bit: the reference is the C monitor's oracle, so its
expression, operation order, polynomial tan and L * M_PER_MM (never L / 1000) are compared with
specification 7.1 and 7.2 written out literally here, on a grid that separates each rearrangement.

Every limit, the digest, AGE_MAX, the conversion constants and the profile ids come from the generated
contract (sdv-out/gen/vss_contract.py, sdv/vss/generate.py); the tests that need it skip with that reason
when it has not been generated. Every number here is a design value, a spec test vector or computed from
them; none is a measurement.
"""
import ast
import dataclasses
import importlib.util
import math
import random
import struct
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FRAME_DIR = REPO / "sdv" / "frame"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(FRAME_DIR) not in sys.path:
    sys.path.insert(0, str(FRAME_DIR))
import rules  # noqa: E402
import vssframe as vf  # noqa: E402

sys.dont_write_bytecode = _saved

try:
    C = vf.load_contract()
    _WHY = ""
except vf.ContractError as err:
    C = None
    _WHY = str(err)
NEEDS_CONTRACT = pytest.mark.skipif(C is None, reason="needs the generated contract: %s" % _WHY)

SPEC_ORDER = (10, 8, 21, 9, 22, 23, 24, 25, 26, 27)
SPEC_NAMES = {8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid", 21: "vss-catalog-mismatch", 22: "vss-stale",
              23: "vss-speed", 24: "vss-accel", 25: "vss-steer", 26: "vss-yaw-inconsistent", 27: "vss-gear-direction"}


def tables(**kw):
    return rules.Tables.from_contract(C, **kw)


def nominal():
    """The profile the sigsim run judges under (its live default): the one every honest frame here uses."""
    return int(C.LIVE_DEFAULT_PROFILE["sigsim"])


def demo():
    """The compiled demo-ODD profile ('demo-odd' is its limit set in profiles.toml)."""
    ids = [int(r["id"]) for r in C.PROFILES if r["limit_set"] == "demo-odd" and r["compiled"]]
    assert len(ids) == 1, ids
    return ids[0]


def ay_bounded():
    """The compiled profile row with an a_y bound: profile 3, the CARLA ego's, compiled since Phase 7 WP2 froze it (before,
    a test bound it with extra_ids, which prof() still does for an uncompiled id). Since Phase 8's WP3b profile 5, the
    CARLA 0.10.0 taxi's, has an a_y bound too but stays uncompiled until WP3c, so the guest's table holds one bounded row
    and the cases that judge under it take that one (test_reason_8 holds profile 5 unbound)."""
    ids = [int(r["id"]) for r in C.PROFILES if r["ay26_max"] is not None and r["compiled"]]
    assert len(ids) == 1, ids
    return ids[0]


def uncompiled_contract():
    """(contract, id): a stand-in for the generated contract with one more row, generated but not compiled (a stand-in
    L), under the first id no row and no reservation takes. From Phase 7 WP2, which compiled profile 3, until Phase 8's
    WP3b added profile 5 (uncompiled, on stand-in envelope rows) no generated row was uncompiled; the cases of an
    uncompiled row (reason 8 for it, extra_ids binding it) use this one as well, so they hold whatever a freeze compiles:
    the a_y-bounded row's limits, its own source vehicle."""
    used = {int(r["id"]) for r in C.PROFILES} | set(C.RESERVED_PROFILE_IDS)
    sid = min(set(range(1, 256)) - used)
    base = next(r for r in C.PROFILES if int(r["id"]) == ay_bounded())
    row = dict(base, id=sid, source_vehicle="synthetic-uncompiled-car", compiled=False, stand_in=("l_mm",), live_default_for=())
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith("_")})
    ns.PROFILES = tuple(C.PROFILES) + (row,)
    assert sid not in ns.COMPILED_PROFILE_IDS
    return ns, sid


def prof(pid, t=None):
    if t is None:
        t = tables(extra_ids=() if pid in C.COMPILED_PROFILE_IDS else (pid,))
    return t.profiles[pid]


def frame(v=None, a_x=None, delta=None, psi_dot=None, gear=None, age=0, profile=None, digest=None, seq=1):
    return vf.encode(vf.Claim(seq=seq, tstamp_ns=0, profile=nominal() if profile is None else profile, v=v, a_x=a_x, delta=delta,
                              psi_dot=psi_dot, gear=gear, age_ms=age, digest=digest), C)


def judge(fr, t=None):
    return rules.judge_frame(fr, t or tables())


def reject(reason):
    return (rules.V_REJECT, reason)


ACCEPT = (rules.V_ACCEPT, rules.RSN_OK)


def honest(**kw):
    base = dict(v=5.0, a_x=0.0, delta=0.0, psi_dot=0.0, gear=1)
    base.update(kw)
    return frame(**base)


def setp(fr, off, value_bytes):
    """Overwrite payload bytes at payload offset off."""
    b = bytearray(fr)
    b[vf.FRAME_HEADER_BYTES + off:vf.FRAME_HEADER_BYTES + off + len(value_bytes)] = value_bytes
    return bytes(b)


# --- FNV-1 and the contract -------------------------------------------------------------------------

@pytest.mark.parametrize("data,want", [
    (b"", 0x811C9DC5),
    (b"a", 0x050C5D7E),
    (b"foobar", 0x31F0B262),
    (bytes.fromhex("3d2c1b0a04030201efbeadde78563412f0debc9a"), 0xC30680E3),
])
def test_fnv1_vectors(data, want):
    assert vf.fnv1_32(data) == want


VECTOR_UIDS = (0x0A1B2C3D, 0x01020304, 0xDEADBEEF, 0x12345678, 0x9ABCDEF0)       # five made-up staticUIDs: a test vector, not the contract's


def test_digest_of_is_little_endian():
    uids = VECTOR_UIDS
    assert vf.digest_of(uids) == 0xC30680E3
    assert vf.fnv1_32(b"".join(struct.pack(">I", u) for u in uids)) == 0xFA2112AB


def test_a_contract_that_exists_loads():
    """NEEDS_CONTRACT may skip tests when the contract is absent, which is right for a file that was never generated
    and wrong for a loader that refuses a file that is there. This test has no skip mark: if the file exists, the
    loader must take it; _WHY says why it did not."""
    if vf.contract_path().is_file():
        assert C is not None, _WHY


@NEEDS_CONTRACT
def test_contract_digest_recomputes():
    assert vf.digest_of(C.SLOT_UIDS) == C.CATALOG_DIGEST


def test_contract_missing_names_the_generator(tmp_path):
    with pytest.raises(vf.ContractError, match="generate.py"):
        vf.load_contract(tmp_path)


@NEEDS_CONTRACT
def test_contract_hand_edit_refused(tmp_path):
    src = vf.contract_path().read_text(encoding="utf-8")
    line = "CATALOG_DIGEST = 0x%08X" % C.CATALOG_DIGEST
    assert line in src
    (tmp_path / "vss_contract.py").write_text(src.replace(line, "CATALOG_DIGEST = 0x%08X" % (C.CATALOG_DIGEST ^ 1)), encoding="utf-8")
    with pytest.raises(vf.ContractError, match="hand-edited"):
        vf.load_contract(tmp_path)


def _tmp_contract(gen_dir, uids, marker="a tmp contract"):
    """A minimal vss_contract.py (all load_contract reads: SLOT_UIDS and CATALOG_DIGEST) whose digest is
    the FNV-1 of its own UIDs, so only the count can be wrong with it."""
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "vss_contract.py").write_text("SLOT_UIDS = %r\nCATALOG_DIGEST = 0x%08X\nMARKER = %r\n" % (tuple(uids), vf.digest_of(uids), marker),
                                             encoding="utf-8")
    return gen_dir


def test_contract_with_the_wrong_number_of_slots_is_refused(tmp_path):
    """One UID per kind 4 slot: a contract of four or six, with a digest that is consistent with its own
    UIDs, is refused for its count (and says so), while the same file with five loads."""
    ok = vf.load_contract(_tmp_contract(tmp_path / "five", VECTOR_UIDS))
    assert (len(ok.SLOT_UIDS), vf.N_SLOTS) == (5, 5)
    assert ok.CATALOG_DIGEST == vf.digest_of(ok.SLOT_UIDS)
    for name, uids in (("four", VECTOR_UIDS[:4]), ("six", VECTOR_UIDS + (0x0BADF00D,))):
        with pytest.raises(vf.ContractError, match="SLOT_UIDS has %d entries, not 5" % len(uids)):
            vf.load_contract(_tmp_contract(tmp_path / name, uids))


def test_sdv_gen_names_another_generation_directory(tmp_path, monkeypatch):
    """SDV_GEN (documented in the README) moves the contract: contract_path() and load_contract() read the
    directory it names, an explicit directory still wins, and unset it is the default generation."""
    other = _tmp_contract(tmp_path / "other", VECTOR_UIDS, marker="the SDV_GEN directory's")
    monkeypatch.setenv("SDV_GEN", str(other))
    assert vf.contract_path() == other / "vss_contract.py"
    assert vf.load_contract().MARKER == "the SDV_GEN directory's"
    assert vf.contract_path(tmp_path) == tmp_path / "vss_contract.py"
    monkeypatch.delenv("SDV_GEN")
    assert vf.contract_path() == vf.DEFAULT_GEN / "vss_contract.py"


@NEEDS_CONTRACT
def test_conversion_constants_bit_for_bit():
    assert C.DEG_PER_RAD == 180 / math.pi
    assert C.RAD_PER_DEG == math.pi / 180
    assert C.M_PER_MM == 1 / 1000


def test_vssframe_imports_stdlib_only():
    """P11: the codec imports no gRPC (nor anything outside the standard library)."""
    allowed = {"__future__", "importlib", "importlib.util", "os", "struct", "sys", "dataclasses", "pathlib", "typing"}
    tree = ast.parse((FRAME_DIR / "vssframe.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    assert names <= allowed, names - allowed
    rtree = ast.parse((FRAME_DIR / "rules.py").read_text(encoding="utf-8"))
    rnames = {a.name for n in ast.walk(rtree) if isinstance(n, ast.Import) for a in n.names}
    rnames |= {n.module or "" for n in ast.walk(rtree) if isinstance(n, ast.ImportFrom)}
    assert not any("grpc" in n for n in rnames | names)


def _reason_10_patches():
    """The layout rules the specification has the monitor reject with reason 10, each as the byte patch that
    breaks it (none is producible by encode or pack_bits), keyed by the words the docs name it with."""
    g = _good()                                          # v and delta present; a_x, psi_dot and the gear absent
    no_value = vf.pack_bits(9, 0, 1, 0, (None,) * 4, None, 0)
    return {
        "b5..b7": setp(g, 0, bytes([g[16] | 0x20])),
        "p[8..23]": setp(g, 8, b"\x01"),
        "p[44..47]": setp(g, 44, b"\x01"),
        "absent slot": setp(g, 29, b"\x80"),
        "p[41..42]": setp(no_value, 41, b"\x01"),
    }


def test_the_docs_list_every_reason_10_layout_rule_and_state_no_unbuilt_behaviour():
    """README and the module docstring name the layout rules as byte patches that decode refuses. The text must
    describe the codec's rules without the old incomplete lists or an implied guest comparison."""
    readme = (FRAME_DIR / "README.md").read_text(encoding="utf-8")
    sources = {name: (FRAME_DIR / name).read_text(encoding="utf-8") for name in ("vssframe.py", "rules.py")}
    docs = {"README.md": readme, "vssframe.py docstring": vf.__doc__ or ""}
    for where, text in docs.items():
        flat = " ".join(text.split())
        for words, patch in _reason_10_patches().items():
            assert words in flat, (where, words)
            assert vf.layout_errors(patch) != [], words
    # The phrases the old text had, spelled with underscores here so that a grep of the package for them finds prose only.
    present_tense = [p.replace("_", " ") for p in ("three_of_them", "three_more", "as_in_the_guest", "exactly_as_in",
                                                   "the_monitor_rejects", "the_monitor_answers")]
    for where, text in (("README.md", readme), *sources.items()):
        flat = " ".join(text.split())
        assert [s for s in present_tense if s in flat] == [], where


# --- the byte layout ------------------------------------------------------------------------------------

def test_struct_is_64_bytes():
    assert struct.calcsize("<QQBBI18xB4fHb4x") == 64
    assert vf.KIND4.size == vf.FRAME_TOTAL_BYTES == 64
    assert (vf.FRAME_HEADER_BYTES, vf.FRAME_PAYLOAD_BYTES) == (16, 48)


def test_payload_offsets_are_the_specs():
    assert (vf.P_FLAGS, vf.P_PROFILE, vf.P_DIGEST, vf.P_VERDICT, vf.P_REASON, vf.P_T_IN, vf.P_T_OUT, vf.P_KIND) == (0, 1, 2, 6, 7, 8, 16, 24)
    assert (vf.P_V, vf.P_AX, vf.P_DELTA, vf.P_PSI_DOT, vf.P_AGE, vf.P_GEAR, vf.P_RESERVED) == (25, 29, 33, 37, 41, 43, 44)


def test_exact_bytes_of_a_full_frame():
    """Every field at the specification's frame offset, little-endian."""
    fr = vf.pack_bits(0x0102030405060708, 0x1112131415161718, 0x2A, 0xA1B2C3D4,
                      (0x3FC00000, 0xBF800000, 0x41A00000, 0xC2C80000), -3, 0x1234)
    assert len(fr) == 64
    assert fr[0:8] == bytes.fromhex("0807060504030201")           # seq
    assert fr[8:16] == bytes.fromhex("1817161514131211")          # tstamp
    assert fr[16] == 0x1F                                          # flags b0..b4
    assert fr[17] == 0x2A                                          # profile
    assert fr[18:22] == bytes.fromhex("d4c3b2a1")                  # digest u32 LE
    assert fr[22:40] == bytes(18)                                  # p[6..23]
    assert fr[40] == 4                                             # kind
    assert fr[41:45] == bytes.fromhex("0000c03f")                  # v = 1.5
    assert fr[45:49] == bytes.fromhex("000080bf")                  # a_x = -1.0
    assert fr[49:53] == bytes.fromhex("0000a041")                  # delta = 20.0
    assert fr[53:57] == bytes.fromhex("0000c8c2")                  # psi_dot = -100.0
    assert fr[57:59] == bytes.fromhex("3412")                      # age u16 LE
    assert fr[59] == 0xFD                                          # gear -3, two's complement
    assert fr[60:64] == bytes(4)                                   # reserved


@NEEDS_CONTRACT
def test_encode_equals_the_specs_struct():
    c = vf.Claim(seq=7, tstamp_ns=123456789, profile=1, v=12.25, a_x=-3.5, delta=-7.75, psi_dot=0.125, gear=-1, age_ms=42)
    assert vf.encode(c, C) == vf.KIND4.pack(7, 123456789, 0x1F, 1, C.CATALOG_DIGEST, 4, 12.25, -3.5, -7.75, 0.125, 42, -1)


@NEEDS_CONTRACT
def test_digest_position_is_the_contracts():
    fr = frame(v=1.0)
    assert fr[18:22] == struct.pack("<I", C.CATALOG_DIGEST)


@NEEDS_CONTRACT
def test_absent_slots_are_zero_never_negative_zero():
    fr = frame(delta=-0.0, age=3)
    p = fr[16:]
    assert p[0] == vf.F_STEER
    assert p[25:33] == bytes(8) and p[37:41] == bytes(4) and p[43] == 0
    assert p[33:37] == struct.pack("<I", 0x80000000)               # a present -0.0 keeps its sign
    assert vf.decode(fr).slot_bits == (None, None, 0x80000000, None)


@NEEDS_CONTRACT
def test_round_trip_seeded():
    rng = random.Random(4)
    for i in range(2000):
        vals = [rng.choice([None, rng.uniform(-400, 400), 0.0, -0.0]) for _ in range(4)]
        gear = rng.choice([None, rng.randint(-128, 127)])
        age = rng.randint(0, 0xFFFF) if (any(x is not None for x in vals) or gear is not None) else 0
        c = vf.Claim(seq=rng.randint(1, vf.SENTINEL_SEQ - 1), tstamp_ns=rng.getrandbits(64), profile=rng.randint(0, 255),
                     v=vals[0], a_x=vals[1], delta=vals[2], psi_dot=vals[3], gear=gear, age_ms=age, digest=rng.getrandbits(32))
        d = vf.decode(vf.encode(c, C))
        assert (d.seq, d.tstamp_ns, d.profile, d.digest, d.gear, d.age_ms) == (c.seq, c.tstamp_ns, c.profile, c.digest, gear, age), i
        for slot, x in enumerate(vals):
            if x is None:
                assert d.slot_bits[slot] is None
            else:
                assert d.slot_bits[slot] == vf.f32_bits(x)
        assert (d.verdict, d.reason, d.t_in_ns, d.t_out_ns) == (0, 0, None, None)


def test_pack_bits_keeps_every_nan_pattern():
    for bits in (0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0x7FA5A5A5, 0xFFFFFFFF, 0x00000001, 0x80000000):
        d = vf.decode(vf.pack_bits(1, 0, 1, 0, (bits, None, None, None), None, 0))
        assert d.slot_bits[0] == bits


@pytest.mark.parametrize("kw,match", [
    (dict(seq=0), "seq"),
    (dict(seq=(1 << 64) - 1), "seq"),
    (dict(profile=256), "profile"),
    (dict(profile=-1), "profile"),
    (dict(digest=1 << 32), "digest"),
    (dict(age_ms=0x10000), "age"),
    (dict(age_ms=-1), "age"),
    (dict(gear=128), "gear"),
    (dict(gear=-129), "gear"),
    (dict(gear=True), "gear"),
    (dict(v=float("nan")), "not finite"),
    (dict(psi_dot=float("inf")), "not finite"),
    (dict(a_x=-float("inf")), "not finite"),
    (dict(delta=1e39), "binary32"),
    (dict(v=10 ** 400), "binary32"),                # an int beyond a double: a FrameError, not the OverflowError float() raises
    (dict(psi_dot=-10 ** 400), "binary32"),
    (dict(v="1.0"), "not a number"),
    (dict(v=True), "not a number"),                 # a bool is an int to Python and not a number to the frame
    (dict(psi_dot=False), "not a number"),
    (dict(v=None, age_ms=5), "no value"),
])
def test_encode_refuses(kw, match):
    base = dict(seq=1, tstamp_ns=0, profile=1, v=1.0, digest=0x12345678)
    base.update(kw)
    with pytest.raises(vf.FrameError, match=match):
        vf.encode(vf.Claim(**base))


def test_encode_takes_an_int_slot_value_as_its_float():
    """A slot value may be an int (a bool may not): it packs as its float, bit for bit, in every f32 slot."""
    base = dict(seq=1, tstamp_ns=0, profile=1, digest=0x12345678)
    ints = vf.Claim(v=5, a_x=-3, delta=7, psi_dot=-2, **base)
    floats = vf.Claim(v=5.0, a_x=-3.0, delta=7.0, psi_dot=-2.0, **base)
    assert vf.encode(ints) == vf.encode(floats)
    d = vf.decode(vf.encode(ints))
    assert (d.v, d.a_x, d.delta, d.psi_dot) == (5.0, -3.0, 7.0, -2.0)
    assert all(type(x) is float for x in (d.v, d.a_x, d.delta, d.psi_dot))


def test_encode_allows_rule_breaking_but_well_formed_frames():
    """Profile 0, a wrong digest, an over-limit value and a saturated age are well formed: the monitor
    must see them (injection), so the codec packs them."""
    fr = vf.encode(vf.Claim(seq=1, tstamp_ns=0, profile=0, v=1000.0, gear=5, age_ms=0xFFFF, digest=0))
    d = vf.decode(fr)
    assert (d.profile, d.digest, d.v, d.age_ms) == (0, 0, 1000.0, 0xFFFF)


def _good():
    return vf.pack_bits(9, 0, 1, 0x01020304, (vf.f32_bits(2.0), None, vf.f32_bits(3.0), None), None, 7)


def _malformed_cases():
    g = _good()
    yield "short", g[:63]
    yield "long", g + b"\0"
    yield "sentinel seq", struct.pack("<Q", vf.SENTINEL_SEQ) + g[8:]
    yield "zero seq", bytes(8) + g[8:]
    for k in (0, 1, 2, 3, 5, 255):
        yield "kind %d" % k, setp(g, 24, bytes([k]))
    for bit in (0x20, 0x40, 0x80):
        yield "flag bit 0x%02X" % bit, setp(g, 0, bytes([g[16] | bit]))
    for off in range(8, 24):
        yield "p[%d]" % off, setp(g, off, b"\x01")
    for off in range(44, 48):
        yield "p[%d]" % off, setp(g, off, b"\x01")
    for off in list(range(29, 33)) + list(range(37, 41)) + [43]:     # absent: a_x, psi_dot, gear
        yield "absent byte p[%d]" % off, setp(g, off, b"\x80")
    yield "age with no values", vf.pack_bits(9, 0, 1, 0, (None,) * 4, None, 0)[:57] + b"\x01\x00" + bytes(5)
    yield "age high byte with no values", vf.pack_bits(9, 0, 1, 0, (None,) * 4, None, 0)[:57] + b"\x00\x01" + bytes(5)
    yield "verdict in a request", setp(g, 6, b"\x01")
    yield "reason in a request", setp(g, 7, b"\x17")


@pytest.mark.parametrize("name,fr", list(_malformed_cases()), ids=[n for n, _ in _malformed_cases()])
def test_decode_refuses(name, fr):
    with pytest.raises(vf.FrameError):
        vf.decode(fr)


def test_decode_reply_and_stamp():
    g = _good()
    rep = setp(setp(g, 6, b"\x01"), 7, bytes([23]))
    d = vf.decode(rep, reply=True)
    assert (d.verdict, d.reason) == (1, 23)
    assert (d.t_in_ns, d.t_out_ns) == (None, None)                 # a reply without stamps has none: not 0
    with pytest.raises(vf.FrameError):
        vf.decode(setp(g, 7, bytes([23])), reply=True)             # accepted but with a reason
    st = setp(g, 8, struct.pack("<QQ", 111, 222))
    d = vf.decode(st, stamp=True)
    assert (d.t_in_ns, d.t_out_ns) == (111, 222)
    with pytest.raises(vf.FrameError):
        vf.decode(st)


def test_a_rejected_stamp_reply_decodes():
    """A :7161 answer is a reply: `stamp` implies `reply`, so a REJECT (verdict 1, its reason) beside t_in
    and t_out decodes and gives its verdict, reason and stamps back. Without stamp, or with reply alone,
    the stamps at p[8..23] still make it malformed; an inconsistent verdict/reason pair is malformed
    under stamp exactly as under reply."""
    g = _good()
    rej = setp(setp(g, 6, bytes([rules.V_REJECT, rules.RSN_VSS_STALE])), 8, struct.pack("<QQ", 111, 222))
    assert vf.layout_errors(rej, stamp=True) == []
    d = vf.decode(rej, stamp=True)
    assert (d.verdict, d.reason, d.t_in_ns, d.t_out_ns) == (rules.V_REJECT, rules.RSN_VSS_STALE, 111, 222)
    assert (d.seq, d.profile, d.digest, d.age_ms) == (9, 1, 0x01020304, 7)          # the request's own fields survive
    acc = setp(g, 8, struct.pack("<QQ", 3, 4))
    da = vf.decode(acc, stamp=True)
    assert (da.verdict, da.reason, da.t_in_ns, da.t_out_ns) == (rules.V_ACCEPT, rules.RSN_OK, 3, 4)
    for kw in ({}, {"reply": True}):
        with pytest.raises(vf.FrameError, match="p\\[8\\.\\.23\\]"):
            vf.decode(rej, **kw)
    for bad_verdict, bad_reason in ((0, rules.RSN_VSS_STALE), (1, 0), (2, 0), (2, rules.RSN_VSS_STALE)):
        with pytest.raises(vf.FrameError, match="verdict"):
            vf.decode(setp(setp(g, 6, bytes([bad_verdict, bad_reason])), 8, struct.pack("<QQ", 1, 2)), stamp=True)


def test_age_field():
    ms = 1_000_000
    assert vf.age_field(10 * ms, []) == (0, False)
    assert vf.age_field(10 * ms, [10 * ms - 1_999_999, 10 * ms]) == (1, False)       # truncated
    assert vf.age_field(100 * ms, [100 * ms - 250 * ms, 90 * ms]) == (250, False)     # the oldest
    assert vf.age_field(0, [70_000 * ms]) == (0, True)                               # negative -> 0, counted
    assert vf.age_field(70_000 * ms, [0]) == (0xFFFF, False)                         # saturated


def test_f32_stepping():
    assert vf.f32_next_up(40.0) > 40.0 and vf.f32(vf.f32_next_up(40.0)) == vf.f32_next_up(40.0)
    assert vf.f32_next_up(40.0) - 40.0 == 2.0 ** -18
    assert vf.f32_next_down(-1.0) == -vf.f32_next_up(1.0)
    assert vf.f32_next_up(-0.0) == vf.f32_next_up(0.0) > 0
    with pytest.raises(vf.FrameError):
        vf.f32_next_up(0.1)


# --- the judge: tables ----------------------------------------------------------------------------------

def test_reason_names_and_order_are_the_specs():
    assert rules.ORDER == SPEC_ORDER
    for code, name in SPEC_NAMES.items():
        assert rules.REASON_NAMES[code] == name


@NEEDS_CONTRACT
def test_tables_bind_compiled_profiles_only():
    t = tables()
    assert set(t.profiles) == set(C.COMPILED_PROFILE_IDS)
    assert t.digest == C.CATALOG_DIGEST and t.age_max_ms == C.AGE_MAX_MS
    rows = {r["id"]: r for r in C.PROFILES}
    for pid, p in t.profiles.items():
        assert p.l_mm == rows[pid]["l_mm"] and p.tol26 == rows[pid]["tol26"]
        assert p.ay26_max == (rows[pid]["ay26_max"] or 0.0)
    # extra_ids binds a generated but uncompiled row with its own a_y bound, and only when named: profile 5 (Phase 8 WP3b,
    # uncompiled until WP3c), and a synthetic row, which holds whatever a freeze compiles.
    p5 = rows[5]
    assert p5["compiled"] is False and 5 not in t.profiles
    bound5 = tables(extra_ids=(5,)).profiles
    assert bound5[5].ay26_max == p5["ay26_max"] > 0 and bound5[5].l_mm == p5["l_mm"] and bound5[5].tol26 == p5["tol26"]
    syn, sid = uncompiled_contract()
    srow = syn.PROFILES[-1]
    assert sid not in rules.Tables.from_contract(syn).profiles
    bound = rules.Tables.from_contract(syn, extra_ids=(sid,)).profiles
    assert sid in bound and bound[sid].ay26_max == srow["ay26_max"] > 0 and bound[sid].l_mm == srow["l_mm"]
    with pytest.raises(ValueError, match="reserved"):
        tables(profiles=[rules.Profile(0, rules.L_MM_MIN, 1.0, 1.0, 1.0, 1.0, 2.0, 0.0, 1.0, 1.0)])


@NEEDS_CONTRACT
def test_honest_frames_accepted_under_every_compiled_profile():
    for pid in C.COMPILED_PROFILE_IDS:
        assert judge(honest(profile=pid)) == ACCEPT
    assert judge(frame(v=0.0, gear=0)) == ACCEPT


@NEEDS_CONTRACT
def test_empty_frame_accepted():
    """C17: no flags, age 0, everything else valid: ACCEPT (v1 behaviour, pinned)."""
    assert judge(frame()) == ACCEPT


@NEEDS_CONTRACT
def test_sentinel_other_kinds_and_lengths():
    t = tables()
    s = struct.pack("<Q", vf.SENTINEL_SEQ) + honest()[8:]
    assert rules.judge_frame(s, t) is None
    assert rules.reply(s, t) == s
    with pytest.raises(ValueError):
        rules.judge_frame(setp(honest(), 24, b"\x01"), t)
    with pytest.raises(ValueError):
        rules.judge_frame(honest()[:63], t)
    with pytest.raises(ValueError):
        rules.check_vss(bytes(47), t)


@NEEDS_CONTRACT
def test_reply_writes_only_verdict_and_reason():
    t = tables()
    req = honest(psi_dot=100.0)
    rep = rules.reply(req, t)
    diff = [i for i in range(64) if req[i] != rep[i]]
    assert diff == [22, 23] and rep[22:24] == bytes([1, 26])
    assert rules.reply(honest(), t) == honest()


# --- each reason ----------------------------------------------------------------------------------------

@NEEDS_CONTRACT
def test_reason_10():
    g = honest()
    for bit in (0x20, 0x40, 0x80):
        assert judge(setp(g, 0, bytes([g[16] | bit]))) == reject(10)
    for off in range(8, 24):
        assert judge(setp(g, off, b"\x01")) == reject(10), off
    for off in range(44, 48):
        assert judge(setp(g, off, b"\x01")) == reject(10), off
    only_v = frame(v=5.0)
    for off in list(range(29, 41)) + [43]:
        assert judge(setp(only_v, off, b"\x01")) == reject(10), off
    assert judge(setp(only_v, 29, struct.pack("<f", -0.0))) == reject(10)   # -0.0 in an absent slot
    empty = frame()
    assert judge(setp(empty, 41, b"\x01")) == reject(10)                  # age with no flags
    assert judge(setp(empty, 42, b"\x01")) == reject(10)
    assert judge(setp(frame(v=1.0), 43, b"\x01")) == reject(10)           # gear with b4 clear


@NEEDS_CONTRACT
def test_an_age_with_only_the_gear_present_is_not_reason_10():
    """Spec 6, row 10: an age is 'with no value' only when (p[0] & 0x1F) == 0, so the gear bit b4 counts as a value
    beside b0..b3. A mask that left b4 out (0x0F) would reject a gear-only frame that carries an age."""
    assert judge(frame(gear=1, age=5)) == ACCEPT
    assert judge(frame(gear=1, age=C.AGE_MAX_MS)) == ACCEPT
    alone = dict(v=1.0), dict(a_x=1.0), dict(delta=1.0), dict(psi_dot=1.0), dict(gear=1)        # each of b0..b4 alone
    for kw in alone:
        assert judge(frame(age=5, **kw)) == ACCEPT, kw
        assert judge(frame(age=C.AGE_MAX_MS, **kw)) == ACCEPT, kw
    assert judge(setp(frame(), 41, struct.pack("<H", 5))) == reject(10)   # the same age with no flag at all


@NEEDS_CONTRACT
def test_reason_8():
    in_table = {int(r["id"]) for r in C.PROFILES}
    absent = [i for i in range(1, 256) if i not in in_table and i not in C.RESERVED_PROFILE_IDS]
    for pid in tuple(C.RESERVED_PROFILE_IDS) + (absent[0], absent[-1]):     # reserved, and ids nothing defines
        assert judge(honest(profile=pid)) == reject(8), pid
    uncompiled = [r["id"] for r in C.PROFILES if not r["compiled"]]
    assert 5 in uncompiled, "premise (Phase 8 WP3b): profile 5 is generated but not compiled until WP3c's freeze"
    for pid in uncompiled:
        assert judge(honest(profile=pid)) == reject(8), pid              # as the specification's Phase 2 guest will
        assert judge(honest(profile=pid), tables(extra_ids=(pid,))) == ACCEPT
    # The same holds on a synthetic uncompiled row, whatever a freeze compiles.
    syn, sid = uncompiled_contract()
    assert judge(honest(profile=sid), rules.Tables.from_contract(syn)) == reject(8)
    assert judge(honest(profile=sid), rules.Tables.from_contract(syn, extra_ids=(sid,))) == ACCEPT


@NEEDS_CONTRACT
def test_reason_21():
    d = C.CATALOG_DIGEST
    for bit in range(32):
        assert judge(honest(digest=d ^ (1 << bit))) == reject(21), bit
    assert judge(honest(digest=0)) == reject(21)
    assert judge(honest(digest=struct.unpack("<I", struct.pack(">I", d))[0])) == reject(21)


@NEEDS_CONTRACT
def test_reason_9():
    patterns = (0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0x7FA5A5A5, 0xFFFFFFFF)
    base = [vf.f32_bits(x) for x in (5.0, 0.0, 0.0, 0.0)]
    for slot in range(4):
        for bits in patterns:
            b = list(base)
            b[slot] = bits
            fr = vf.pack_bits(1, 0, 1, C.CATALOG_DIGEST, b, 1, 0)
            assert judge(fr) == reject(9), (slot, hex(bits))
    for bits in (0x00000001, 0x807FFFFF, 0x80000000):                     # subnormals and -0.0 are finite
        b = list(base)
        b[1] = bits
        assert judge(vf.pack_bits(1, 0, 1, C.CATALOG_DIGEST, b, 1, 0)) == ACCEPT


@NEEDS_CONTRACT
def test_reason_9_takes_the_largest_finite_exponent_for_finite():
    """The exponent field 0xFF is NaN and infinity; 0xFE is the largest finite one (FLT_MAX 0x7F7FFFFF is its
    top, 2^127 = 0x7F000000 its bottom), so none of those is field-not-finite. psi_dot alone (b3): rule 26
    needs b0, b2 and b3, and rules 23 to 25 read other slots, so nothing else bounds it and the verdict is
    rule 9's alone. (In a_x the same bits would reach rule 24, and be finite there too.)"""
    def alone(bits):
        return vf.pack_bits(1, 0, nominal(), C.CATALOG_DIGEST, (None, None, None, bits), None, 0)
    for bits in (0x7F7FFFFF, 0xFF7FFFFF, 0x7F000000, 0xFF000000):
        assert (bits >> 23) & 0xFF == 0xFE, hex(bits)                     # the premise: the largest finite exponent
        assert vf.f32_is_finite_bits(bits), hex(bits)
        assert judge(alone(bits)) == ACCEPT, hex(bits)
    for bits in (0x7F800000, 0xFF800000):                                 # one exponent up: infinities
        assert (bits >> 23) & 0xFF == 0xFF and not vf.f32_is_finite_bits(bits)
        assert judge(alone(bits)) == reject(9), hex(bits)
    flt_max = [vf.f32_bits(x) for x in (5.0, 0.0, 0.0, 0.0)]
    flt_max[1] = 0x7F7FFFFF                                               # finite and past every a_max: 24, not 9
    assert judge(vf.pack_bits(1, 0, nominal(), C.CATALOG_DIGEST, flt_max, 1, 0)) == reject(24)


@NEEDS_CONTRACT
def test_reason_22():
    m = C.AGE_MAX_MS
    assert judge(honest(age=m)) == ACCEPT
    assert judge(honest(age=m + 1)) == reject(22)
    assert judge(honest(age=0xFFFF)) == reject(22)


@NEEDS_CONTRACT
@pytest.mark.parametrize("which", ["nominal", "demo"])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_reasons_23_24_25_at_their_limits(which, sign):
    pid = {"nominal": nominal, "demo": demo}[which]()
    p = prof(pid)
    for field, lim, reason in (("v", p.v_max, 23), ("a_x", p.a_max, 24), ("delta", p.delta_max, 25)):
        assert vf.f32(lim) == lim                                          # f32-exact (spec 5.4)
        at = sign * lim
        over = sign * vf.f32_next_up(lim)
        assert judge(frame(profile=pid, **{field: at})) == ACCEPT, (field, at)
        assert judge(frame(profile=pid, **{field: over})) == reject(reason), (field, over)


def _kin_ref(v, d, l_mm):
    """psi_dot_kin and a_y_kin with libm's tan and plain division: an independent evaluation."""
    kin = math.degrees(abs(v) * math.tan(math.radians(abs(d))) / (l_mm / 1000.0))
    return kin, abs(v) * math.radians(kin)


@NEEDS_CONTRACT
def test_reason_26_hand_computed():
    p = prof(nominal())
    v, d = 5.0, 20.0
    kin = math.degrees(5.0 * math.tan(math.radians(20.0)) / 2.7)          # the formula, by hand
    assert p.l_mm == 2700          # spec pin, not read from the contract: the design car's wheelbase (spec 5.2), which the line above uses
    assert abs(rules.kinematics(v, d, p.l_mm, tables())[0] - kin) < 1e-9
    assert judge(honest(v=v, delta=d, psi_dot=0.0)) == reject(26)         # yaw zeroed while turning
    assert judge(honest(v=v, delta=d, psi_dot=kin)) == ACCEPT
    assert judge(honest(v=v, delta=d, psi_dot=-kin)) == ACCEPT            # yaw sign flipped: magnitudes
    assert judge(honest(v=-v, delta=d, psi_dot=kin, gear=-1)) == ACCEPT   # reverse
    assert judge(honest(v=v, delta=-d, psi_dot=kin)) == ACCEPT
    assert judge(honest(v=v, delta=d, psi_dot=kin + 5.0)) == reject(26)
    # only with all of b0, b2, b3
    assert judge(frame(v=v, delta=d, gear=1)) == ACCEPT
    assert judge(frame(v=v, psi_dot=100.0)) == ACCEPT
    assert judge(frame(delta=d, psi_dot=100.0)) == ACCEPT


@NEEDS_CONTRACT
def test_reason_26_window_edges():
    p = prof(nominal())
    wild = 100.0
    lo, hi = p.v26_lo, p.v26_hi
    assert judge(honest(v=lo, psi_dot=wild)) == reject(26)
    assert judge(honest(v=hi, psi_dot=wild)) == reject(26)
    assert judge(honest(v=vf.f32_next_down(lo), psi_dot=wild)) == ACCEPT
    assert judge(honest(v=vf.f32_next_up(hi), psi_dot=wild)) == ACCEPT
    assert judge(honest(v=-hi, psi_dot=wild, gear=-1)) == reject(26)
    assert judge(honest(v=-vf.f32_next_up(hi), psi_dot=wild, gear=-1)) == ACCEPT


def _f32_side(pred, lo, hi):
    """Bisect over binary32 values in [lo, hi] (both >= 0) for the edge of a monotone predicate:
    returns (last f32 with pred False, first f32 with pred True)."""
    a, b = vf.f32_bits(lo), vf.f32_bits(hi)
    assert not pred(vf.bits_f32(a)) and pred(vf.bits_f32(b))
    while b - a > 1:
        m = (a + b) // 2
        if pred(vf.bits_f32(m)):
            b = m
        else:
            a = m
    return vf.bits_f32(a), vf.bits_f32(b)


@NEEDS_CONTRACT
def test_reason_26_tol_edges():
    """C11: | |psi_dot| - psi_dot_kin | just below tol ACCEPT, just above REJECT, placed with the rule's
    own expression and cross-checked with math.tan; exactly tol where psi_dot_kin is exactly 0."""
    t = tables()
    p = prof(nominal(), t)
    tol = p.tol26
    assert p.ay26_max == 0.0, "premise: the nominal profile has no a_y bound (profiles.toml: ay26_max = none), so every point below is judged"
    top = min(p.v26_hi, p.v_max)                      # rule 23 precedes 26: only the window up to v_max is reachable
    assert p.v26_lo < top, "premise: rule 26's window reaches above v26_lo before rule 23 (v_max) rejects"
    span = top - p.v26_lo
    mid = vf.f32(p.v26_lo + span / 2)
    assert judge(honest(v=mid, delta=0.0, psi_dot=tol)) == ACCEPT       # kin exactly 0, |y - 0| == tol
    assert judge(honest(v=mid, delta=0.0, psi_dot=vf.f32_next_up(tol))) == reject(26)
    assert judge(honest(v=mid, delta=0.0, psi_dot=-tol)) == ACCEPT
    # Points derived from the profile: inside the window (rule 26 judges them, rule 23 passes them) and inside
    # delta_max (rule 25 passes them): a turn, the window's lower edge at the widest steering, near the top at
    # a small angle, and a reversing point with the steering the other way.
    points = ((p.v26_lo + span * 0.25, p.delta_max * 0.5), (p.v26_lo, p.delta_max),
              (p.v26_lo + span * 0.9, p.delta_max / 16), (-(p.v26_lo + span * 0.4), -p.delta_max * 0.3))
    under_judged = 0
    for v, d in points:
        v, d = vf.f32(v), vf.f32(d)
        assert p.v26_lo <= abs(v) <= top and abs(d) <= p.delta_max
        kin, _ay = rules.kinematics(abs(v), abs(d), p.l_mm, t)
        ref, _ = _kin_ref(v, d, p.l_mm)
        assert abs(kin - ref) < 1e-9
        gear = 1 if v > 0 else -1
        # above: y - kin > tol
        below_y, above_y = _f32_side(lambda y, k=kin: abs(abs(y) - k) > tol and abs(y) > k, kin, kin + 2 * tol)
        assert judge(honest(v=v, delta=d, psi_dot=below_y, gear=gear)) == ACCEPT
        assert judge(honest(v=v, delta=d, psi_dot=above_y, gear=gear)) == reject(26)
        assert (abs(below_y) - ref <= tol) and (abs(above_y) - ref > tol)   # the same side with math.tan
        # under: kin - y > tol
        if kin > tol:
            under_judged += 1
            in_y, out_y = _f32_side(lambda y, k=kin: not (k - y > tol), 0.0, kin)
            assert judge(honest(v=v, delta=d, psi_dot=out_y, gear=gear)) == ACCEPT
            assert judge(honest(v=v, delta=d, psi_dot=in_y, gear=gear)) == reject(26)
            assert judge(honest(v=v, delta=d, psi_dot=-in_y, gear=gear)) == reject(26)
            assert (ref - in_y > tol) and not (ref - out_y > tol)
    assert under_judged >= 2, "premise: at least two of the points have psi_dot_kin above tol26, so the lower edge is tried"


@NEEDS_CONTRACT
def test_reason_26_ay_bound_edges():
    """C11: under each a_y-bounded profile (profile 3, compiled since Phase 7 WP2, and since Phase 8's WP3b profile 5,
    uncompiled until WP3c; extra_ids binds either), a_y_kin just below the bound is judged and just above it skipped,
    placed by bisecting binary32 delta at a fixed binary32 v."""
    bounded = [int(r["id"]) for r in C.PROFILES if r["ay26_max"] is not None]
    assert ay_bounded() in bounded and 5 in bounded
    for aid in bounded:
        t = tables(extra_ids=(aid,))
        p = t.profiles[aid]
        assert p.ay26_max > 0
        wild = 250.0
        for v in (vf.f32(8.0), vf.f32(3.0), vf.f32(p.v26_hi)):
            judged, skipped = _f32_side(lambda d, u=v, q=p, tt=t: rules.kinematics(u, d, q.l_mm, tt)[1] > q.ay26_max, 0.0, p.delta_max)
            assert rules.kinematics(v, judged, p.l_mm, t)[1] <= p.ay26_max < rules.kinematics(v, skipped, p.l_mm, t)[1]
            assert _kin_ref(v, judged, p.l_mm)[1] <= p.ay26_max < _kin_ref(v, skipped, p.l_mm)[1]
            assert judge(honest(v=v, delta=judged, psi_dot=wild, profile=aid), t) == reject(26)
            assert judge(honest(v=v, delta=skipped, psi_dot=wild, profile=aid), t) == ACCEPT
            kin = rules.kinematics(v, judged, p.l_mm, t)[0]
            assert judge(honest(v=v, delta=judged, psi_dot=kin, profile=aid), t) == ACCEPT
            assert judge(honest(v=v, delta=skipped, psi_dot=-wild, profile=aid), t) == ACCEPT   # a wild yaw never moves a frame


@NEEDS_CONTRACT
def test_reason_26_no_ay_bound_never_skips():
    p = prof(nominal())
    assert p.ay26_max == 0.0, "premise: the nominal profile has no a_y bound (profiles.toml: ay26_max = none)"
    v, d = min(p.v26_hi, p.v_max), p.delta_max                # the corner of the reachable envelope with the largest a_y_kin
    bound = prof(ay_bounded()).ay26_max                       # the a_y above which the bounded profile would skip rule 26
    assert rules.kinematics(v, d, p.l_mm, tables())[1] > bound, "premise: the corner's a_y_kin is above the bounded profile's bound"
    assert judge(honest(v=v, delta=d, psi_dot=0.0)) == reject(26)


@NEEDS_CONTRACT
def test_reason_27():
    p = prof(nominal())
    vt = p.v_tol
    wrong = vf.f32(2 * vt)                                                # a wrong-direction speed beyond the tolerance
    assert vt < wrong <= p.v_max, "premise: 2 * v_tol is inside v_max (rule 23 precedes 27), so a wrong-direction speed past v_tol is reachable"
    assert judge(frame(v=-vt, gear=1)) == ACCEPT
    assert judge(frame(v=vf.f32_next_down(-vt), gear=1)) == reject(27)
    assert judge(frame(v=vt, gear=-1)) == ACCEPT
    assert judge(frame(v=vf.f32_next_up(vt), gear=-1)) == reject(27)
    for v in (-p.v_max, -wrong, wrong, p.v_max):                           # up to the speed limit itself (accepted at the limit)
        assert judge(frame(v=v, gear=0)) == ACCEPT                        # gear 0 is never checked
    assert judge(frame(v=-wrong, gear=127)) == reject(27)
    assert judge(frame(v=wrong, gear=-128)) == reject(27)
    assert judge(frame(v=-wrong, gear=5)) == reject(27)
    assert judge(frame(gear=1, a_x=1.0)) == ACCEPT                       # no speed: no 27
    assert judge(frame(v=-wrong)) == ACCEPT                               # no gear: no 27


# --- the order ------------------------------------------------------------------------------------------

def _mutations():
    """One violation per reason, each on its own bytes of the base frame (v 5, a 0, delta 0, psi_dot 0,
    gear 1): 23 and 27 both move v, so they are never combined."""
    p = prof(nominal())
    m = C.AGE_MAX_MS
    return {
        10: lambda b: setp(b, 0, bytes([b[16] | 0x20])),
        8: lambda b: setp(b, 1, b"\x00"),
        21: lambda b: setp(b, 2, struct.pack("<I", C.CATALOG_DIGEST ^ 1)),
        9: lambda b: setp(b, 37, struct.pack("<I", 0x7FC00000)),
        22: lambda b: setp(b, 41, struct.pack("<H", m + 1)),
        23: lambda b: setp(b, 25, struct.pack("<f", vf.f32_next_up(p.v_max))),
        24: lambda b: setp(b, 29, struct.pack("<f", vf.f32_next_up(p.a_max))),
        25: lambda b: setp(b, 33, struct.pack("<f", vf.f32_next_up(p.delta_max))),
        26: lambda b: setp(b, 37, struct.pack("<f", 100.0)),
        27: lambda b: setp(b, 25, struct.pack("<f", -5.0)),
    }


@NEEDS_CONTRACT
def test_each_violation_alone_gives_its_reason():
    base = honest()
    assert judge(base) == ACCEPT
    for reason, mut in _mutations().items():
        assert judge(mut(base)) == reject(reason), reason


@NEEDS_CONTRACT
@pytest.mark.parametrize("pair", list(zip(SPEC_ORDER, SPEC_ORDER[1:])), ids=lambda p: "%d-before-%d" % p)
def test_adjacent_pairs_report_the_earlier(pair):
    first, second = pair
    muts = _mutations()
    base = honest()
    both_orders = (muts[second](muts[first](base)), muts[first](muts[second](base)))
    assert both_orders[0] == both_orders[1]                  # disjoint bytes
    assert judge(both_orders[0]) == reject(first), pair


@NEEDS_CONTRACT
def test_everything_at_once_is_10():
    muts = _mutations()
    fr = honest()
    for reason in (27, 24, 25, 22, 9, 21, 8, 10, 23):       # 26 shares 9's slot; 23 overwrites 27's v
        fr = muts[reason](fr)
    assert judge(fr) == reject(10)
    fr2 = muts[8](muts[21](muts[9](muts[22](muts[23](muts[24](muts[25](honest())))))))
    assert judge(fr2) == reject(8)


@NEEDS_CONTRACT
def test_stateless():
    """The same frame gets the same verdict whatever came before it."""
    t = tables()
    muts = _mutations()
    frames = [honest()] + [m(honest()) for m in muts.values()]
    first = [rules.judge_frame(f, t) for f in frames]
    rng = random.Random(7)
    for _ in range(300):
        i = rng.randrange(len(frames))
        assert rules.judge_frame(frames[i], t) == first[i]


# --- the profile rows: specification 5.4's bounds -------------------------------------------------------

BASE_PROFILE = dict(id=9, l_mm=rules.L_MM_MIN, v_max=10.0, a_max=10.0, delta_max=1.0, v26_lo=1.0, v26_hi=2.0,
                    ay26_max=0.0, tol26=1.0, v_tol=1.0)             # a small valid row of the test's own


def _profile(**kw):
    return rules.Profile(**dict(BASE_PROFILE, **kw))


def test_profile_bounds_are_specification_5_4():
    """The bounds Profile enforces: pinned as the specification writes them (spec values, not generated), and
    equal to the generator's own copies (sdv/vss/generate.py checks profiles.toml against them)."""
    assert (rules.L_MM_MIN, rules.L_MM_MAX, rules.DELTA_MAX_LIMIT_DEG) == (1000, 6000, 57.0)      # spec 5.4 pins
    assert (rules.PSI_DOT_KIN_ERROR_BOUND, rules.TOL_OVER_ERROR_MIN) == (1.0e-5, 1.0e5)           # spec 7.3 and 5.4 pins
    assert rules.F32_LIMITS == ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "v_tol")        # spec 5.4's six limits
    spec = importlib.util.spec_from_file_location("sdv_vss_generate_bounds", str(REPO / "sdv" / "vss" / "generate.py"))
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(gen)
    finally:
        sys.dont_write_bytecode = saved
    assert (gen.L_MM_MIN, gen.L_MM_MAX, gen.DELTA_MAX_LIMIT_DEG) == (rules.L_MM_MIN, rules.L_MM_MAX, rules.DELTA_MAX_LIMIT_DEG)
    assert (gen.PSI_DOT_KIN_ERROR_BOUND, gen.TOL_OVER_ERROR_MIN) == (rules.PSI_DOT_KIN_ERROR_BOUND, rules.TOL_OVER_ERROR_MIN)
    assert gen.PSI_DOT_KIN_ERROR_BOUND * gen.TOL_OVER_ERROR_MIN == rules.TOL26_MIN      # the generator's floor on tol26
    assert tuple(gen.F32_LIMITS) == rules.F32_LIMITS


@NEEDS_CONTRACT
def test_every_generated_profile_row_constructs():
    for row in C.PROFILES:
        assert rules.Profile.from_row(row).id == row["id"]


def _contract_with_first_row(row):
    """A stand-in for the generated contract whose first profile row (a compiled one) is `row`."""
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith("_")})
    ns.PROFILES = (row,) + tuple(C.PROFILES[1:])
    return ns


@NEEDS_CONTRACT
@pytest.mark.parametrize("change,said", [
    (lambda r: dict(r, l_mm=float(r["l_mm"])), "l_mm"),                   # a float that is a whole number: int() would take it
    (lambda r: dict(r, l_mm=str(r["l_mm"])), "l_mm"),
    (lambda r: dict(r, v_max=str(r["v_max"])), "v_max must be numbers"),  # float("40.0") would take it
    (lambda r: dict(r, v_tol=True), "v_tol must be numbers"),             # float(True) is 1.0, a valid v_tol
    (lambda r: dict(r, tol26=None), "tol26 must be numbers"),
    (lambda r: dict(r, id=str(r["id"])), "id .* not an int"),
    (lambda r: dict(r, id=float(r["id"])), "id .* not an int"),
    (lambda r: dict(r, ay26_max=True), "ay26_max must be numbers"),
], ids=["l_mm-float", "l_mm-str", "v_max-str", "v_tol-bool", "tol26-None", "id-str", "id-float", "ay26_max-bool"])
def test_from_row_refuses_a_contract_row_that_profile_would_refuse(change, said):
    """Profile.from_row hands a row's values over unconverted (only ay26_max's None becomes 0.0), so the checks of
    Profile.__post_init__ apply to a contract row as they do to a hand-built profile: a value that int() or
    float() would turn into a valid one (a whole-number float l_mm, "40.0", True) is refused, not converted.
    The generated rows themselves load (test_every_generated_profile_row_constructs)."""
    row = change(C.PROFILES[0])
    with pytest.raises(ValueError, match="profile .*: .*%s" % said):
        rules.Profile.from_row(row)
    with pytest.raises(ValueError, match=said):
        rules.Tables.from_contract(_contract_with_first_row(row))


@pytest.mark.parametrize("kw", [
    dict(l_mm=rules.L_MM_MIN - 1), dict(l_mm=rules.L_MM_MAX + 1), dict(l_mm=0), dict(l_mm=float(rules.L_MM_MIN)), dict(l_mm=True),
    dict(delta_max=0.0), dict(delta_max=-1.0), dict(delta_max=rules.DELTA_MAX_LIMIT_DEG + 0.5), dict(delta_max=80.0),
    dict(delta_max=float("nan")),
    dict(v26_lo=0.0), dict(v26_lo=-1.0), dict(v26_lo=2.0), dict(v26_lo=3.0), dict(v26_hi=1.0), dict(v26_lo=float("nan")),
    dict(v_max=0.0), dict(v_max=-1.0), dict(a_max=0.0), dict(a_max=-1.0), dict(tol26=0.0), dict(tol26=-1.0),
    dict(tol26=float("nan")), dict(v_tol=0.0), dict(v_tol=-1.0),
    dict(ay26_max=-1.0), dict(ay26_max=float("nan")),
])
def test_profile_refuses_what_spec_5_4_forbids(kw):
    with pytest.raises(ValueError, match="profile 9"):
        _profile(**kw)


NUMBERS = ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "ay26_max", "tol26", "v_tol")    # every float of a row


def test_every_number_of_a_row_has_a_refusal_case():
    assert set(NUMBERS) == {f.name for f in dataclasses.fields(rules.Profile)} - {"id", "l_mm"}


@pytest.mark.parametrize("kw,said", [
    # the floor on tol26: the rule-26 error bound times TOL_OVER_ERROR_MIN (spec 5.4)
    (dict(tol26=0.5), "tol26 0.5 below"),
    (dict(tol26=1e-9), "tol26 1e-09 below"),
    (dict(tol26=math.nextafter(rules.TOL26_MIN, 0.0)), "tol26 .* below"),
    # a limit that is not a binary32 (spec 5.4): a double beside one, a value past float32, an int too large for one
    (dict(v_max=0.1), "v_max 0.1 is not exactly representable in binary32"),
    (dict(a_max=0.1), "a_max 0.1 is not exactly representable in binary32"),
    (dict(delta_max=0.1), "delta_max 0.1 is not exactly representable in binary32"),
    (dict(v26_lo=0.1), "v26_lo 0.1 is not exactly representable in binary32"),
    (dict(v26_hi=2.1), "v26_hi 2.1 is not exactly representable in binary32"),
    (dict(v_tol=0.1), "v_tol 0.1 is not exactly representable in binary32"),
    (dict(v_max=math.nextafter(10.0, 11.0)), "v_max .* not exactly representable in binary32"),
    (dict(v_max=1e39), "v_max .* not exactly representable in binary32"),
    (dict(a_max=10 ** 400), "a_max .* not exactly representable in binary32"),
    # a bool is not a number, nor is a string or None
    *[(dict(**{n: True}), "%s must be numbers" % n) for n in NUMBERS],
    (dict(v_max="10.0"), "v_max must be numbers"),
    (dict(ay26_max=None), "ay26_max must be numbers"),
])
def test_profile_refuses_with_its_reason(kw, said):
    with pytest.raises(ValueError, match="profile 9: .*%s" % said):
        _profile(**kw)


def test_profile_accepts_the_bounds_themselves():
    for kw in (dict(l_mm=rules.L_MM_MIN), dict(l_mm=rules.L_MM_MAX), dict(delta_max=rules.DELTA_MAX_LIMIT_DEG),
               dict(delta_max=vf.f32(1e-9)), dict(ay26_max=0.0), dict(ay26_max=2.0),
               dict(v26_lo=vf.f32(1e-9), v26_hi=vf.f32(2e-9)),                                 # just above zero, as binary32
               dict(tol26=rules.TOL26_MIN), dict(tol26=3),                                     # the floor itself; an int is a number
               dict(v_max=10), dict(v_max=vf.f32_next_up(10.0)), dict(v_tol=vf.f32(0.1))):     # a binary32 beside a round decimal
        _profile(**kw)


@NEEDS_CONTRACT
def test_a_hand_built_profile_cannot_take_the_oracle_out_of_the_tan_domain():
    """The row that used to make the oracle raise mid-judgement (delta_max above 57 degrees) is refused when
    built; a row at the bound judges its widest steering without raising, and one step above is rule 25."""
    with pytest.raises(ValueError):
        tables(profiles=[_profile(delta_max=80.0)])
    t = tables(profiles=[_profile(delta_max=rules.DELTA_MAX_LIMIT_DEG)])
    assert judge(honest(v=1.5, delta=rules.DELTA_MAX_LIMIT_DEG, psi_dot=0.0, profile=9), t) == reject(26)
    assert judge(honest(v=1.5, delta=vf.f32_next_up(rules.DELTA_MAX_LIMIT_DEG), psi_dot=0.0, profile=9), t) == reject(25)


@NEEDS_CONTRACT
def test_a_hand_built_profile_with_a_fresh_id_is_bound():
    fresh = _profile()
    assert fresh.id not in {int(r["id"]) for r in C.PROFILES}, "premise: the test row's id is one the contract does not define"
    t = tables(profiles=[fresh])
    assert t.profiles[fresh.id] is fresh and set(t.profiles) == set(C.COMPILED_PROFILE_IDS) | {fresh.id}


@NEEDS_CONTRACT
@pytest.mark.parametrize("case", ["compiled", "extra_ids", "twice"])
def test_a_hand_built_profile_never_replaces_a_bound_one(case):
    """Tables.from_contract refuses a hand-built profile whose id is already bound (a compiled one, one of
    extra_ids, or an earlier hand-built profile) instead of silently replacing it or keeping the old one: a test
    that thinks it judges under its own limits would be judging under the contract's."""
    syn, sid = uncompiled_contract()                          # an uncompiled row to name in extra_ids, whatever a freeze compiles
    contract, kw = {"compiled": (C, dict(profiles=[_profile(id=nominal())])),
                    "extra_ids": (syn, dict(extra_ids=(sid,), profiles=[_profile(id=sid)])),
                    "twice": (C, dict(profiles=[_profile(), _profile()]))}[case]
    assert rules.Tables.from_contract(contract, **{k: v for k, v in kw.items() if k != "profiles"}) is not None
    with pytest.raises(ValueError, match="already bound"):
        rules.Tables.from_contract(contract, **kw)


# --- rule 26's arithmetic against Python's math (the Python half of C19, C20) ----------------------------

def test_vss_tan_error():
    worst = max(abs(rules.vss_tan(i / 200000) - math.tan(i / 200000)) for i in range(200001))
    assert worst <= 1e-9                        # the design bound (spec 7.2)
    assert worst < 2e-12                        # the spec's computed 1.5e-12 at x = 1.0
    assert rules.vss_tan(0.0) == 0.0 and rules.vss_tan(-0.0) == 0.0
    for bad in (-1e-300, math.nextafter(1.0, 2.0), float("nan")):
        with pytest.raises(ValueError):
            rules.vss_tan(bad)
    assert math.radians(rules.DELTA_MAX_LIMIT_DEG) < rules.TAN_DOMAIN_MAX


def test_vss_tan_coefficients():
    assert len(rules.TAN_SIN_COEFFS) == 7 and len(rules.TAN_COS_COEFFS) == 8     # x^13 and x^14
    for k, c in enumerate(rules.TAN_SIN_COEFFS):
        assert c == (-1) ** k / math.factorial(2 * k + 1)
    for k, c in enumerate(rules.TAN_COS_COEFFS):
        assert c == (-1) ** k / math.factorial(2 * k)


def _bits(x):
    return struct.pack("<d", x)


def _tan_by_hand(x):
    """s(x) / c(x) of specification 7.2 written out term by term, not looped: the Taylor polynomials of sin
    through x^13 and of cos through x^14, Horner in x^2 with the highest power innermost, in double."""
    s, c = rules.TAN_SIN_COEFFS, rules.TAN_COS_COEFFS
    x2 = x * x
    sin = x * (s[0] + x2 * (s[1] + x2 * (s[2] + x2 * (s[3] + x2 * (s[4] + x2 * (s[5] + x2 * s[6]))))))
    cos = c[0] + x2 * (c[1] + x2 * (c[2] + x2 * (c[3] + x2 * (c[4] + x2 * (c[5] + x2 * (c[6] + x2 * c[7]))))))
    return sin / cos


def _tan_power_sum(x):
    """The same two polynomials summed as c_k x^n rather than by Horner: a rearrangement the bit test must tell apart."""
    sin = sum(c * x ** (2 * k + 1) for k, c in enumerate(rules.TAN_SIN_COEFFS))
    cos = sum(c * x ** (2 * k) for k, c in enumerate(rules.TAN_COS_COEFFS))
    return sin / cos


def tan_grid():
    """The x [rad] the tan bit tests run on, here and in tests/test_monitor_kind4.py (C19's comparison of the C
    monitor's vss_tan with this reference, bit for bit)."""
    rng = random.Random(21)
    return [0.0, 0.25, 0.5, 0.75, 1.0] + [i / 1000 for i in range(1001)] + [rng.uniform(0.0, 1.0) for _ in range(2000)]


def test_vss_tan_is_the_specs_horner_bit_for_bit():
    """The reference's tan is the specification's polynomial in its arrangement, to the last bit: libm's tan
    or a rearranged polynomial changes bits the C monitor is tested against. The grid has teeth: each
    of those two differs from the Horner form on it, so a reference that used either would fail here."""
    xs = tan_grid()
    for x in xs:
        assert _bits(rules.vss_tan(x)) == _bits(_tan_by_hand(x)), x
    assert sum(_bits(math.tan(x)) != _bits(_tan_by_hand(x)) for x in xs) > 10
    assert sum(_bits(_tan_power_sum(x)) != _bits(_tan_by_hand(x)) for x in xs) > 10


GOLDEN_TAN = {      # x [rad] -> little-endian hex of the double s(x) / c(x); the polynomial's own arithmetic, frozen here
    0.25: "564c3ca48557d03f",
    0.5: "4a47f35b4f7be13f",
    0.75: "6fef1061a3cfed3f",
    1.0: "e0febe5c24ebf83f",
}


def test_vss_tan_golden_bit_patterns():
    """The four values above, computed once from specification 7.2's polynomials (coefficients the doubles nearest
    (-1)^k / n!, Horner in x^2, highest power innermost), are pinned as bits. Four points catch libm's tan, the
    power-sum arrangement, and any other change of coefficient or arrangement that moves a bit at these x, even
    if the test's own copy of the polynomial changes with it. They do not catch every such change: Horner with
    x multiplied into each step, or one ulp on the x^13 coefficient, moves no bit at these four. Those are held
    by test_vss_tan_is_the_specs_horner_bit_for_bit and test_vss_tan_coefficients. Plain double +, * and /
    only, no libm."""
    for x, want in GOLDEN_TAN.items():
        assert _bits(rules.vss_tan(x)).hex() == want, x


@NEEDS_CONTRACT
def test_kinematics_against_math_on_a_grid():
    t = tables()
    worst = 0.0
    for l_mm in (rules.L_MM_MIN, prof(nominal(), t).l_mm, rules.L_MM_MAX):
        for i in range(0, 41):
            v = i * 0.5
            for j in range(0, 58):
                d = float(j)
                kin, ay = rules.kinematics(v, d, l_mm, t)
                ref, ay_ref = _kin_ref(v, d, l_mm)
                worst = max(worst, abs(kin - ref))
                assert abs(ay - ay_ref) <= 1e-9 * max(1.0, ay_ref)
    assert worst <= rules.PSI_DOT_KIN_ERROR_BOUND      # the design bound (spec 7.3; the pins test holds its value)


def kinematics_grid():
    """(ls, vs, ds): the L [mm], |v| [m/s] and |delta| [deg] the kinematics bit test runs on, here and in
    tests/test_monitor_kind4.py (C19's comparison of the C monitor's kinematics with this reference, bit for bit).
    Needs the contract (M_PER_MM picks the L values that separate L * M_PER_MM from L / 1000)."""
    hard = [n for n in range(rules.L_MM_MIN, rules.L_MM_MAX + 1) if n * C.M_PER_MM != n / 1000.0]
    assert len(hard) > 100
    rng = random.Random(5)
    # 2700 and 2701 are here as the design L and its neighbour, not as separators: L * M_PER_MM equals L / 1000 for
    # both (and for 1000 and 6000). 1001, 1003, 5999 and the sampled `hard` values are the ones that separate.
    ls = [rules.L_MM_MIN, 1001, 1003, 2700, 2701, 5999, rules.L_MM_MAX] + rng.sample(hard, 30)
    vs = [0.0, 0.5, 1.0, 3.3, 5.0, 7.77, 12.5, 19.99, 20.0, 39.9] + [rng.uniform(0.0, 40.0) for _ in range(10)]
    ds = [0.0, 0.5, 3.25, 10.0, 20.0, 35.0, rules.DELTA_MAX_LIMIT_DEG] + [rng.uniform(0.0, rules.DELTA_MAX_LIMIT_DEG) for _ in range(10)]
    return ls, vs, ds


@NEEDS_CONTRACT
def test_kinematics_bit_for_bit_from_spec_7_1():
    """Rule 26's expression as the reference must evaluate it, written out literally from specification 7.1
    with the contract's constants and compared exactly (not within a tolerance): L_m is L * M_PER_MM, never
    L / 1000; the tan is the polynomial, never libm's; the operations run left to right. The grid takes L
    values where L * M_PER_MM and L / 1000 differ in the last bit, and each rearrangement below is shown to
    change a result on it, so a reference that made any of them would fail this test."""
    t = tables()
    ls, vs, ds = kinematics_grid()
    changed = {"L / 1000": 0, "libm tan": 0, "speed over L first": 0}
    for l_mm in ls:
        for v in vs:
            for d in ds:
                tan = rules.vss_tan(d * C.RAD_PER_DEG)
                kin = C.DEG_PER_RAD * v * tan / (float(l_mm) * C.M_PER_MM)
                ay = v * kin * C.RAD_PER_DEG
                assert rules.kinematics(v, d, l_mm, t) == (kin, ay), (v, d, l_mm)
                changed["L / 1000"] += C.DEG_PER_RAD * v * tan / (float(l_mm) / 1000.0) != kin
                changed["libm tan"] += C.DEG_PER_RAD * v * math.tan(d * C.RAD_PER_DEG) / (float(l_mm) * C.M_PER_MM) != kin
                changed["speed over L first"] += C.DEG_PER_RAD * (v / (float(l_mm) * C.M_PER_MM)) * tan != kin
    assert all(n > 0 for n in changed.values()), changed


def test_dabs_keeps_negative_zero():
    assert math.copysign(1.0, rules.dabs(-0.0)) == -1.0
    assert rules.dabs(-2.5) == 2.5 and rules.dabs(3.0) == 3.0
