"""The Rust kind 4 codec and svc probe (sdv/claimrs): SDV plan Phase 9, rustcpp R1, T0-T6.

sdv/claimrs is a std-only, unsafe-free Rust port of the kind 4 claim codec (sdv/frame/vssframe.py) with a
blocking svc client. It is held three ways, which must agree:

- T1, `cargo test`: the crate's own tests, written from the layout and the published FNV-1 values only (no
  Python input);
- T2, `vssclaim vectors`: against the vectors sdv/claimrs/vectors.py writes from vssframe.py and rules.py at
  test time, into pytest's tmp directory (never committed, so a regenerated contract cannot leave it stale);
- T4, `vssclaim probe`: end to end on loopback against the vss monitor built natively from monitor.c with
  build-monitor-native.sh (gcc, MONITOR_EXT_KINDS=0x10), started as `PORT svc 60000` through
  monitor_corpus._start_on_port as test_monitor_kind4.py's svc sessions are: C21's 10,000 seeded frames
  (test_monitor_kind4.c21_corpus, called here, not copied), then kind4_client.build_cases from seq 10001.
  Every reply must be rules.reply()'s, byte for byte.

T0 holds the crate's shape (no dependencies, unsafe forbidden, the toolchain pin, frame.h's constants read
from the header here). T3 holds the writer itself (one code per layout_errors branch, an unknown message
refused, the header's digest, the rt rule's refusal and patches). T5 holds the probe's failure paths against
a Python fake peer. T6 is `cargo fmt --check` and clippy with -D warnings.

WHEN IT RUNS. On Linux, when `~/.cargo/bin/rustup toolchain list` (RUSTUP_AUTO_INSTALL=0) names
1.100.0-x86_64-unknown-linux-gnu and the generated contract is in sdv-out/gen; a cargo on PATH or another
toolchain does not count. Otherwise every test skips with the reason. With CLAIMRS_REQUIRED=1 in the
environment every skip here, the toolchain's and the contract's alike, is a failure instead. Every cargo
call runs with --locked --offline, RUSTUP_AUTO_INSTALL=0 and RUSTUP_TOOLCHAIN=1.100.0, and builds into a
pytest tmp directory, never into the tree.

What this does NOT show: any timing (the probe prints no time); anything on aarch64, the Orin or the guest
(the monitor here is the gcc build on x86-64, not the guest's qcc binary); that agreement on these inputs
is agreement on every input; any property of the bridge, which stays Python.
"""
import ast
import hashlib
import importlib.util
import itertools
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import monitor_corpus as mc
import test_monitor_kind4 as tmk
import test_sdv_frame as tsf

rules = tsf.rules
vf = tsf.vf
C = tsf.C
H = vf.FRAME_HEADER_BYTES

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CRATE = REPO / "sdv" / "claimrs"
WRITER = CRATE / "vectors.py"
FRAME_H = REPO / "ipc-test" / "common" / "frame.h"
NATIVE = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"
GEN = REPO / "sdv-out" / "gen"
GEN_HEADERS = ("vss_contract.h", "vss_profiles.h")

TOOLCHAIN = "1.100.0"
TOOLCHAIN_TRIPLE = TOOLCHAIN + "-x86_64-unknown-linux-gnu"
CARGO_BIN = Path.home() / ".cargo" / "bin"
REQUIRED = os.environ.get("CLAIMRS_REQUIRED") == "1"

SENTINEL = (1 << 64) - 1
C21_SEED = 2121
CASES_START = 10001


# ============================================================ when the module runs

def skip_or_fail(why):
    """Every skip in this module goes through here: under CLAIMRS_REQUIRED=1 it is a failure."""
    if REQUIRED:
        pytest.fail("CLAIMRS_REQUIRED=1, so this does not skip: " + why)
    pytest.skip(why)


def rust_env(target=None):
    env = dict(os.environ)
    env["RUSTUP_AUTO_INSTALL"] = "0"
    env["RUSTUP_TOOLCHAIN"] = TOOLCHAIN
    env["PATH"] = str(CARGO_BIN) + os.pathsep + env.get("PATH", "")
    for k in ("RUSTFLAGS", "CARGO_BUILD_TARGET", "CARGO_TARGET_DIR"):
        env.pop(k, None)
    if target is not None:
        env["CARGO_TARGET_DIR"] = str(target)
    return env


def toolchain_why():
    """'' when the pinned toolchain is installed; otherwise why not."""
    if not sys.platform.startswith("linux"):
        return "the Rust crate builds in WSL Ubuntu-24.04 only"
    rustup = CARGO_BIN / "rustup"
    if not rustup.is_file():
        return "no ~/.cargo/bin/rustup (the pinned toolchain is required)"
    try:
        r = subprocess.run([str(rustup), "toolchain", "list"], env=rust_env(), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "~/.cargo/bin/rustup toolchain list failed: %s" % e
    names = [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]
    if r.returncode != 0 or TOOLCHAIN_TRIPLE not in names:
        return "rustup lists no %s toolchain (it lists %s)" % (TOOLCHAIN_TRIPLE, names)
    return ""


def contract_why():
    if C is None:
        return "needs the generated contract: %s" % tsf._WHY
    missing = [h for h in GEN_HEADERS if not (GEN / h).is_file()]
    if missing:
        return "needs the generated headers %s in sdv-out/gen (sdv/vss/generate.py)" % ", ".join(missing)
    return ""


@pytest.fixture(autouse=True, scope="module")
def _the_module_runs():
    why = toolchain_why() or contract_why()
    if why:
        skip_or_fail(why)


# ============================================================ the crate, the writer, the binary

def cargo(target, *args, timeout=900):
    if not (CRATE / "Cargo.toml").is_file():
        pytest.fail("no crate: sdv/claimrs/Cargo.toml is missing")
    return subprocess.run([str(CARGO_BIN / "cargo"), *args], cwd=str(CRATE), env=rust_env(target),
                          capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def target(tmp_path_factory):
    return tmp_path_factory.mktemp("claimrs-target")


@pytest.fixture(scope="module")
def vssclaim(target):
    r = cargo(target, "--locked", "--offline", "build", "--release", "--bin", "vssclaim")
    assert r.returncode == 0, "the release build must pass offline and locked:\n" + r.stderr
    exe = Path(target) / "release" / "vssclaim"
    assert exe.is_file(), exe
    return str(exe)


@pytest.fixture(scope="module")
def writer():
    if not WRITER.is_file():
        pytest.fail("no vector writer: sdv/claimrs/vectors.py is missing")
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("claimrs_vectors", str(WRITER))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["claimrs_vectors"] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    assert mod.vf is vf and mod.rules is rules, "the writer imports the same vssframe.py and rules.py as the tests"
    return mod


def run(argv, timeout=120):
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)


def read_vectors(path):
    """(header {key: value}, [record fields]) of a vector file, read here without the writer."""
    lines = Path(path).read_text(encoding="ascii").split("\n")
    assert lines[-1] == "", "the file ends with a newline"
    lines = lines[:-1]
    assert lines[0] == "claimrs-vectors\t1"
    header = {}
    i = 1
    while i < len(lines) and not lines[i].startswith(("enc\t", "pack\t", "dec\t", "age\t", "rt\t")):
        k, v = lines[i].split("\t")
        header[k] = v
        i += 1
    records = [ln.split("\t") for ln in lines[i:]]
    assert int(header["records"]) == len(records)
    return header, records


def by_name(records):
    out = {}
    for r in records:
        assert r[1] not in out, "duplicate vector name %r" % r[1]
        out[r[1]] = r
    return out


def build_cases(start_seq):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from sdv.frame import kind4_client as kc
    finally:
        sys.dont_write_bytecode = saved
    return kc.build_cases(C, tsf.tables(), start_seq=start_seq)


def set_byte(fr, off, value):
    b = bytearray(fr)
    b[off] = value
    return bytes(b)


# ============================================================ T0: the shape

def toml(path):
    import tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_t0_cargo_toml_has_no_dependencies_forbids_unsafe_and_checks_overflow():
    t = toml(CRATE / "Cargo.toml")
    assert t["package"]["name"] == "claimrs" and t["package"]["edition"] == "2024"
    assert not {"dependencies", "dev-dependencies", "build-dependencies", "target", "patch", "replace"} & set(t), sorted(t)
    assert t["lints"]["rust"]["unsafe_code"] == "forbid"
    assert t["profile"]["release"]["overflow-checks"] is True


def test_t0_cargo_lock_lists_the_crate_alone():
    lock = toml(CRATE / "Cargo.lock")
    assert [p["name"] for p in lock["package"]] == ["claimrs"]
    assert not {"source", "checksum", "dependencies"} & set(lock["package"][0])


def test_t0_rust_toolchain_pins_1_100_0_minimal_with_clippy_and_rustfmt():
    t = toml(CRATE / "rust-toolchain.toml")["toolchain"]
    assert t["channel"] == TOOLCHAIN and t["profile"] == "minimal"
    assert sorted(t["components"]) == ["clippy", "rustfmt"]


def frame_h_defines():
    """frame.h's valued #defines, evaluated here: integer literals (a `u` suffix dropped), UINT64_MAX, names
    defined above them, and +."""
    text = FRAME_H.read_text(encoding="utf-8")
    exprs = dict(re.findall(r"(?m)^#define[ \t]+(\w+)[ \t]+(\S.*?)[ \t]*$", text))

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            return (1 << 64) - 1 if node.id == "UINT64_MAX" else value(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return ev(node.left) + ev(node.right)
        raise AssertionError("frame.h: an expression this reader does not take: %s" % ast.dump(node))

    def value(name):
        return ev(ast.parse(re.sub(r"\b(\d+)u\b", r"\1", exprs[name]), mode="eval"))

    return {name: value(name) for name in exprs}


def test_t0_consts_equal_frame_h(vssclaim):
    want = frame_h_defines()
    assert want == {"FRAME_HEADER_BYTES": 16, "FRAME_PAYLOAD_BYTES": 48, "FRAME_TOTAL_BYTES": 64,
                    "FRAME_SENTINEL_SEQ": SENTINEL}, "premise: frame.h as this test reads it"
    r = run([vssclaim, "consts"])
    assert r.returncode == 0, r.stderr
    got = {}
    for ln in r.stdout.splitlines():
        name, val = ln.split(" ")
        assert name not in got
        got[name] = int(val)
    assert got == want


# ============================================================ T1: cargo test

T1_TESTS = (
    "frame::tests::sizes_offsets_and_flags",
    "kind4::tests::fnv1_32_published_values",
    "kind4::tests::digest_of_hashes_the_uids_little_endian",
    "kind4::tests::hand_written_v_5_0",
    "kind4::tests::hand_written_every_field",
    "kind4::tests::rounding_to_binary32",
    "kind4::tests::one_frame_per_refusal_class",
    "kind4::tests::encode_refusals_in_python_order",
    "kind4::tests::age_field_cases",
    "link::tests::a_reply_in_two_writes_is_read_whole",
    "link::tests::a_peer_that_closes_mid_reply_is_an_error",
    "link::tests::a_silent_peer_hits_the_deadline",
    "link::tests::bytes_after_the_last_reply_are_trailing",
    "link::tests::a_clean_end_of_session",
    "link::tests::the_default_deadline_and_the_trailing_window",
    "tests::a_patch_keeps_to_the_rt_rule",
)


def test_t1_cargo_test_from_the_specification_only(target):
    r = cargo(target, "--locked", "--offline", "test")
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    passed = set(re.findall(r"(?m)^test (\S+) \.\.\. ok$", r.stdout))
    missing = [t for t in T1_TESTS if t not in passed]
    assert not missing, "T1's tests must run and pass: %r" % missing
    assert not re.search(r"(?m)^test \S+ \.\.\. (FAILED|ignored)", r.stdout)


# ============================================================ T2: the codec against Python

@pytest.fixture(scope="module")
def codec_vectors(writer, tmp_path_factory):
    path = tmp_path_factory.mktemp("vectors") / "codec.tsv"
    writer.write_codec(path, C, tsf.tables())
    return path


def test_t2_every_codec_vector_matches(vssclaim, codec_vectors):
    header, records = read_vectors(codec_vectors)
    r = run([vssclaim, "vectors", codec_vectors], timeout=300)
    lines = r.stdout.splitlines()
    assert r.returncode == 0, [ln for ln in lines if not ln.startswith("ok ")][:20] + [r.stderr]
    assert lines[-1] == "vectors done: total=%d matched=%d" % (len(records), len(records))
    assert lines[:-1] == ["ok " + rec[1] for rec in records]


ENC_EDGES = (
    "zero-pos", "zero-neg", "min-subnormal", "half-min-subnormal", "neg-half-min-subnormal", "tie-even-down", "tie-even-up",
    "flt-max", "below-midpoint", "midpoint", "neg-midpoint", "1e39", "inf-pos", "inf-neg", "nan",
    "gear-min", "gear-max", "gear-absent", "age-0", "age-1", "age-max", "seq-1", "seq-max-1", "seq-0", "seq-sentinel",
    "slot-0-alone", "slot-1-alone", "slot-2-alone", "slot-3-alone", "slot-4-alone", "all-five", "empty", "age-no-value",
    "order-overflow-0-nonfinite-3", "order-nonfinite-0-overflow-3", "order-bad-slot-seq-0", "order-seq-0-age-no-value",
)
PACK_EDGES = ("snan", "all-ones", "neg-zero", "order-seq-0-age-no-value", "seq-0", "seq-sentinel", "age-no-value")
LAYOUT_CODES = ("length", "seq-sentinel", "seq-zero", "kind", "flags-reserved", "request-verdict", "reply-verdict", "reply-reason",
                "stamp-span", "reserved-span", "absent-slot-0", "absent-slot-1", "absent-slot-2", "absent-slot-3", "absent-slot-4",
                "age-without-value")
MODE_CODES = {
    "request": [c for c in LAYOUT_CODES if c not in ("reply-verdict", "reply-reason")],
    "reply": [c for c in LAYOUT_CODES if c != "request-verdict"],
    "stamp": [c for c in LAYOUT_CODES if c not in ("request-verdict", "stamp-span")],
}
# The pairs that cannot occur together: a wrong length returns alone, and the seq and the reply branches are if/elif.
EXCLUSIVE = {frozenset(("seq-sentinel", "seq-zero")), frozenset(("reply-verdict", "reply-reason"))}


def dec_codes(rec):
    assert rec[0] == "dec"
    return set() if rec[4] == "decoded" else set(rec[5].split(","))


def test_t2_the_vectors_carry_every_case_the_spec_names(codec_vectors):
    header, records = read_vectors(codec_vectors)
    names = by_name(records)
    for e in ENC_EDGES:
        assert names["enc/" + e][0] == "enc", e
    for e in PACK_EDGES:
        assert names["pack/" + e][0] == "pack", e
    seeded = [n for n in names if n.startswith("enc/seeded-")]
    assert len(seeded) == 10000 and int(header["seed"]) > 0
    want = {"enc/midpoint": "overflow", "enc/1e39": "overflow", "enc/inf-pos": "not-finite", "enc/nan": "not-finite",
            "enc/seq-0": "seq-zero", "enc/seq-sentinel": "seq-sentinel", "enc/age-no-value": "age-without-value"}
    for n, code in want.items():
        assert names[n][12:] == ["error", code], (n, names[n][12:])
    for mode, codes in MODE_CODES.items():
        assert dec_codes(names["dec/%s/valid" % mode]) == set()
        for k in (0, 1, 2, 3, 0xFF):
            assert dec_codes(names["dec/%s/kind-%d" % (mode, k)]) == {"kind"}, (mode, k)
        for c in codes:
            assert dec_codes(names["dec/%s/%s" % (mode, c)]) == {c}, (mode, c)
        for a, b in itertools.combinations(codes, 2):
            rec = names.get("dec/%s/%s+%s" % (mode, a, b)) or names["dec/%s/%s+%s" % (mode, b, a)]
            if "length" not in (a, b) and frozenset((a, b)) not in EXCLUSIVE:
                assert dec_codes(rec) == {a, b}, (mode, a, b)
        for base in ("full", "empty"):
            for o in range(vf.FRAME_PAYLOAD_BYTES):
                assert names["dec/%s/sweep-%s-p%02d" % (mode, base, o)][0] == "dec"
    for case in build_cases(1):
        assert dec_codes(names["dec/request/case-" + case.name]) <= {"reserved-span"}
        assert names["dec/reply/case-" + case.name][2] == "reply"
    assert len([n for n in names if n.startswith("age/")]) >= 60
    assert int(header["rt_records"]) == len([r for r in records if r[0] == "rt"]) > 0


# ============================================================ T3: the writer itself

def honest():
    return tsf.frame(v=5.0, a_x=1.0, delta=2.0, psi_dot=3.0, gear=1, age=7, seq=5)


def reply_of(fr, verdict=1, reason=23):
    b = bytearray(fr)
    b[H + vf.P_VERDICT], b[H + vf.P_REASON] = verdict, reason
    return bytes(b)


def clear_flag(fr, slot):
    return set_byte(fr, H, fr[H] & ~(1 << slot) & 0xFF)


# One frame per layout_errors branch, written from the layout: (code, mode, frame).
def branch_frames():
    f = honest()
    empty_with_age = bytearray(tsf.frame(seq=5))
    struct.pack_into("<H", empty_with_age, H + vf.P_AGE, 9)
    return [
        ("length", "request", f[:63]),
        ("seq-sentinel", "request", struct.pack("<Q", SENTINEL) + f[8:]),
        ("seq-zero", "request", struct.pack("<Q", 0) + f[8:]),
        ("kind", "request", set_byte(f, H + vf.P_KIND, 5)),
        ("flags-reserved", "request", set_byte(f, H, f[H] | 0x40)),
        ("request-verdict", "request", set_byte(f, H + vf.P_REASON, 3)),
        ("reply-verdict", "reply", reply_of(f, 2, 0)),
        ("reply-reason", "reply", reply_of(f, 1, 0)),
        ("stamp-span", "reply", set_byte(reply_of(f), H + 23, 1)),
        ("reserved-span", "stamp", set_byte(reply_of(f), H + 47, 1)),
        ("absent-slot-0", "request", clear_flag(f, 0)),
        ("absent-slot-1", "request", clear_flag(f, 1)),
        ("absent-slot-2", "request", clear_flag(f, 2)),
        ("absent-slot-3", "request", clear_flag(f, 3)),
        ("absent-slot-4", "request", clear_flag(f, 4)),
        ("age-without-value", "request", bytes(empty_with_age)),
    ]


def test_t3_each_layout_errors_branch_reaches_exactly_one_code(writer):
    frames = branch_frames()
    assert [c for c, _, _ in frames] == list(LAYOUT_CODES)
    for code, mode, fr in frames:
        msgs = vf.layout_errors(fr, reply=mode != "request", stamp=mode == "stamp")
        assert len(msgs) == 1, (code, msgs)
        assert writer.layout_code(msgs[0]) == code, (code, msgs[0])
        assert writer.layout_codes(fr, mode) == [code]
    assert sorted({code for _, code in writer.LAYOUT_PATTERNS}) == sorted(LAYOUT_CODES)
    assert len(writer.LAYOUT_PATTERNS) == len(LAYOUT_CODES), "one pattern per branch"


@pytest.mark.parametrize("message", ["seq 0 (the bridge counts from 0)", "kind 4, not 5 or 6", "verdict 1 with reason 2 and 3",
                                     "reserved flag bits 0x2", "slot 5 absent but its bytes are non-zero", "",
                                     "length 63, not 65", "seq is the sentinel", "kind 4", "reserved flag bits 0x20 ", "verdict",
                                     "p[8..23] zero", "reserved p[44..48] non-zero", "slot 0 absent but its bytes are zero",
                                     "age non-zero with a value present"])
def test_t3_an_unknown_layout_message_is_refused(writer, message):
    with pytest.raises(writer.WriterError, match="layout_errors message"):
        writer.layout_code(message)


@pytest.mark.parametrize("message,seq", [("seq 5 outside 1..18446744073709551614", 5), ("profile 256 outside 0..255", 1),
                                         ("slot 4: nan is not finite (inject non-finite values with pack_bits)", 1),
                                         ("slot 0: an integer that does not fit a binary32", 1)])
def test_t3_an_unknown_encode_message_is_refused(writer, message, seq):
    with pytest.raises(writer.WriterError, match="encode message"):
        writer.encode_code(message, seq)


def test_t3_the_header_digest_is_digest_of_slot_uids_and_vectors_refuses_a_mismatch(writer, vssclaim, tmp_path):
    path = tmp_path / "small.tsv"
    writer.write_codec(path, C, tsf.tables(), n_seeded=20)
    header, _records = read_vectors(path)
    uids = [int(u, 16) for u in header["slot_uids"].split(",")]
    assert uids == list(C.SLOT_UIDS)
    assert int(header["catalog_digest"], 16) == vf.digest_of(uids) == C.CATALOG_DIGEST
    assert header["contract_sha256"] == hashlib.sha256(vf.contract_path().read_bytes()).hexdigest()
    assert run([vssclaim, "vectors", path]).returncode == 0
    for key, flip in (("catalog_digest", "%08x" % (C.CATALOG_DIGEST ^ 1)),
                      ("slot_uids", ",".join("%08x" % (u ^ (i == 2)) for i, u in enumerate(uids)))):
        text = path.read_text(encoding="ascii")
        bad = tmp_path / ("bad-%s.tsv" % key)
        bad.write_text(text.replace("%s\t%s\n" % (key, header[key]), "%s\t%s\n" % (key, flip), 1), encoding="ascii")
        assert bad.read_text(encoding="ascii") != text
        r = run([vssclaim, "vectors", bad])
        assert r.returncode == 2 and "digest" in r.stderr and not r.stdout, (key, r.returncode, r.stdout[:200], r.stderr)


def test_t3_vectors_gives_1_and_names_the_one_record_that_differs(writer, vssclaim, tmp_path):
    path = tmp_path / "small.tsv"
    writer.write_codec(path, C, tsf.tables(), n_seeded=20)
    _header, records = read_vectors(path)
    lines = path.read_text(encoding="ascii").split("\n")
    k = [i for i, ln in enumerate(lines) if ln.startswith("enc\tenc/all-five\t")][0]
    fields = lines[k].split("\t")
    assert fields[12] == "frame"
    fields[13] = fields[13][:-1] + ("0" if fields[13][-1] != "0" else "1")
    lines[k] = "\t".join(fields)
    path.write_text("\n".join(lines), encoding="ascii")
    r = run([vssclaim, "vectors", path])
    out = r.stdout.splitlines()
    assert r.returncode == 1, r.stdout[-500:] + r.stderr
    diffs = [ln for ln in out if ln.startswith("diff ")]
    assert len(diffs) == 1 and diffs[0].startswith("diff enc/all-five"), diffs
    assert out[-1] == "vectors done: total=%d matched=%d" % (len(records), len(records) - 1)


@pytest.mark.parametrize("what", ["kind 5", "seq 0", "sentinel", "63 bytes"])
def test_t3_a_frame_the_rt_rule_cannot_express_is_refused(writer, what):
    f = honest()
    fr = {"kind 5": set_byte(f, H + vf.P_KIND, 5), "seq 0": struct.pack("<Q", 0) + f[8:],
          "sentinel": struct.pack("<Q", SENTINEL) + f[8:], "63 bytes": f[:63]}[what]
    with pytest.raises(writer.WriterError, match="cannot express" if what != "kind 5" else "not patchable"):
        writer.rt_record("t3", fr, tsf.tables())


def _patched(f, pairs):
    b = bytearray(f)
    for off, v in pairs:
        b[off] = v
    return bytes(b)


def test_t3_a_reason_10_frame_of_each_patchable_kind_is_a_base_plus_a_patch_on_exactly_those_bytes(writer):
    t = tsf.tables()
    f = honest()
    nothing = tsf.frame(seq=5)
    no_delta = tsf.frame(v=5.0, a_x=1.0, psi_dot=3.0, gear=1, age=7, seq=5)
    no_gear = tsf.frame(v=5.0, a_x=1.0, delta=2.0, psi_dot=3.0, age=7, seq=5)
    cases = [
        ("reserved flag bits", _patched(f, [(H, f[H] | 0x80)]), {H}),
        ("p[8..23]", _patched(f, [(H + 8, 1), (H + 23, 0xFF)]), {H + 8, H + 23}),
        ("an absent f32 slot", _patched(no_delta, [(H + vf.P_DELTA, 1), (H + vf.P_DELTA + 3, 0x40)]), {H + 33, H + 36}),
        ("the absent gear slot", _patched(no_gear, [(H + vf.P_GEAR, 0xFF)]), {H + vf.P_GEAR}),
        ("an age with no value", _patched(nothing, [(H + vf.P_AGE + 1, 2)]), {H + vf.P_AGE + 1}),
        ("p[44..47]", _patched(f, [(H + 44, 1), (H + 47, 2)]), {H + 44, H + 47}),
    ]
    for what, fr, offsets in cases:
        assert rules.judge_frame(fr, t) == (1, 10), "premise: %s is reason 10" % what
        rec = writer.rt_record("t3 " + what, fr, t)
        assert rec.base_kind == "enc", what
        assert {off for off, _ in rec.patch} == offsets, (what, rec.patch)
        assert _patched(rec.request, rec.patch) == rec.sent == fr, what
        assert rec.reply == rules.reply(fr, t), what
    # p[6..7] in a request are patchable too (the monitor overwrites them; never reason 10), and a frame whose
    # present slot is not finite gets a raw-bits base with no patch.
    rec = writer.rt_record("t3 p[6..7]", _patched(f, [(H + 6, 0xEE), (H + 7, 0xEE)]), t)
    assert {off for off, _ in rec.patch} == {H + 6, H + 7} and rec.reply == rules.reply(rec.sent, t)
    nan = vf.pack_bits(5, 0, 1, C.CATALOG_DIGEST, (0x7F800001, None, None, None), None, 0)
    rec = writer.rt_record("t3 snan", nan, t)
    assert rec.base_kind == "pack" and rec.patch == () and rec.request == nan


# ============================================================ T4: end to end against the native vss monitor

def gcc():
    path = shutil.which("gcc")
    if path is None:
        skip_or_fail("needs gcc on Linux (WSL Ubuntu-24.04)")
    return path


@pytest.fixture(scope="module")
def vss_monitor(tmp_path_factory):
    gcc()
    out = tmp_path_factory.mktemp("claimrs-monitor") / "monitor-vss"
    env = dict(os.environ, OUT=str(out), MONITOR_EXT_KINDS="0x10")
    for k in ("MONITOR_VSS_GEN", "FORCE", "CC"):
        env.pop(k, None)
    r = subprocess.run(["bash", str(NATIVE)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file() and "switch: MONITOR_EXT_KINDS=0x10" in r.stdout
    return str(out)


DONE_RE = re.compile(rb"monitor: client done: seen=(\d+) accepted=(\d+) rejected=(\d+)\n\Z")


def test_t4_the_probe_against_the_native_vss_monitor(writer, vssclaim, vss_monitor, tmp_path):
    t = tsf.tables()
    frames = tmk.c21_corpus(n=10000, seed=C21_SEED)
    assert [struct.unpack_from("<Q", fr)[0] for fr in frames] == list(range(1, 10001))
    frames += [case.frame for case in build_cases(CASES_START)]
    path = tmp_path / "rt.tsv"
    counts = writer.write_rt(path, frames, C, t, seed=C21_SEED)
    header, records = read_vectors(path)
    assert len(records) == int(header["rt_records"]) == len(frames) == 10011
    assert int(header["rt_encode_bases"]) == counts["rt_encode_bases"] > 0
    assert int(header["rt_patched"]) == counts["rt_patched"] > 0
    print("T4 vector counts: rt_records=%s rt_encode_bases=%s rt_patched=%s"
          % (header["rt_records"], header["rt_encode_bases"], header["rt_patched"]))
    replies = [bytes.fromhex(rec[15]) for rec in records]
    assert replies == [rules.reply(fr, t) for fr in frames]

    proc, port = mc._start_on_port(vss_monitor, ["svc", str(mc.SVC_DEADLINE_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        r = run([vssclaim, "probe", "--host", "127.0.0.1", "--port", port, "--vectors", path], timeout=600)
        proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    lines = r.stdout.splitlines()
    assert r.returncode == 0, [ln for ln in lines if not ln.startswith("ok ")][:20] + [r.stderr]
    assert lines[-1] == "probe done: sent=10011 matched=10011"
    assert lines[:-1] == ["ok " + rec[1] for rec in records]
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    done = [m for m in (DONE_RE.match(ln) for ln in list(proc.out)) if m]
    assert len(done) == 1
    accepted = sum(1 for rep in replies if rep[H + vf.P_VERDICT] == 0)
    assert tuple(int(x) for x in done[0].groups()) == (len(replies), accepted, len(replies) - accepted)
    assert 0 < accepted < len(replies)
    assert proc.count(b"LIVENESS MISS") == 0


# ============================================================ T5: the probe's failure paths

class FakePeer:
    """A stand-in for the monitor's svc port on loopback, for one connection: it reads 64-byte requests and
    answers each with the next of `replies`, as `mode` says. serve=False only listens, so a test can tell
    whether anything connected."""

    def __init__(self, replies, mode="normal", serve=True):
        self.replies = list(replies)
        self.mode = mode
        self.requests = []
        self.accepted = 0
        self.done = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = None
        if serve:
            self.thread = threading.Thread(target=self._serve, daemon=True)
            self.thread.start()

    def _serve(self):
        self.sock.settimeout(0.05)
        while not self.done.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepted += 1
            with conn:
                try:
                    self._session(conn)
                except OSError:
                    pass
            return

    def _session(self, conn):
        conn.settimeout(30)
        for rep in self.replies:
            req = b""
            while len(req) < vf.FRAME_TOTAL_BYTES:
                part = conn.recv(vf.FRAME_TOTAL_BYTES - len(req))
                if not part:
                    return
                req += part
            self.requests.append(req)
            if self.mode == "silent":
                self.done.wait(60)
                return
            if self.mode == "close-mid":
                conn.sendall(rep[:30])
                return
            if self.mode == "late" and len(self.requests) == 1:
                self.done.wait(1.0)                               # the first reply 1.0 s late, the rest at once
            if self.mode == "drip" and len(self.requests) == 1:       # the first reply a byte every 40 ms (2.56 s in all)
                for k in range(len(rep)):
                    conn.sendall(rep[k : k + 1])
                    time.sleep(0.04)
            elif self.mode == "split":
                conn.sendall(rep[:21])
                time.sleep(0.05)
                conn.sendall(rep[21:])
            else:
                conn.sendall(rep)
        if self.mode == "trailing":
            conn.sendall(b"\x00")
        if self.mode == "after-eof":
            conn.recv(1)                                              # the probe's end of session
            time.sleep(0.1)
            conn.sendall(b"\x00")                                     # a byte 100 ms after it, inside the 200 ms window
            time.sleep(0.3)
            return
        conn.recv(1)                                            # the probe's end of session

    def connected(self):
        """Whether anything connected (for serve=False: a connection the kernel completed counts)."""
        if self.thread is None:
            self.sock.settimeout(0.3)
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                return False
            conn.close()
            return True
        return self.accepted > 0

    def close(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(10)
        self.sock.close()


@pytest.fixture
def small(writer, tmp_path):
    """A vector file of build_cases' eleven frames as rt records, and their records."""
    path = tmp_path / "small.tsv"
    writer.write_rt(path, [case.frame for case in build_cases(1)], C, tsf.tables(), seed=0)
    _header, records = read_vectors(path)
    return path, records


def probe(vssclaim, port, path, *extra, timeout=30):
    return run([vssclaim, "probe", "--host", "127.0.0.1", "--port", port, "--vectors", path, *extra], timeout=timeout)


def replies_of(records):
    return [bytes.fromhex(rec[15]) for rec in records]


def rewrite(path, line_index, fn):
    lines = path.read_text(encoding="ascii").split("\n")
    lines[line_index] = fn(lines[line_index])
    path.write_text("\n".join(lines), encoding="ascii")


def record_line(path, k):
    """The line index of record k in the file."""
    lines = path.read_text(encoding="ascii").split("\n")
    return [i for i, ln in enumerate(lines) if ln.startswith("rt\t")][k]


def edit_field(path, k, field, fn):
    """Rewrite field `field` of record k (13 the request, 14 the patch, 15 the reply) through fn."""
    def line(ln):
        fields = ln.split("\t")
        fields[field] = fn(fields[field])
        return "\t".join(fields)
    rewrite(path, record_line(path, k), line)


def flip(hexstr, index, mask):
    """hexstr with byte `index` xor mask."""
    b = bytearray.fromhex(hexstr)
    b[index] ^= mask
    return b.hex()


def sent_frames(records):
    """The frames a vector file's rt records send: each expected request with its patch applied."""
    out = []
    for rec in records:
        b = bytearray.fromhex(rec[13])
        if rec[14] != "-":
            for item in rec[14].split(","):
                off, val = item.split("=")
                b[int(off)] = int(val, 16)
        out.append(bytes(b))
    return out


@pytest.mark.parametrize("mode", ["normal", "split"])
def test_t5_a_peer_that_answers_right_gives_0_also_when_a_reply_comes_in_two_writes(vssclaim, small, mode):
    path, records = small
    peer = FakePeer(replies_of(records), mode)
    try:
        r = probe(vssclaim, peer.port, path)
    finally:
        peer.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines() == ["ok " + rec[1] for rec in records] + ["probe done: sent=11 matched=11"]
    assert peer.requests == sent_frames(records)
    assert any(rec[14] != "-" for rec in records), "premise: a patched frame is among them (build_cases' reason 10)"


def test_t5_one_flipped_expected_byte_gives_1_naming_the_vector(vssclaim, small):
    path, records = small
    k = 4
    good = replies_of(records)
    edit_field(path, k, 15, lambda x: flip(x, H + 1, 0x10))
    peer = FakePeer(good)
    try:
        r = probe(vssclaim, peer.port, path)
    finally:
        peer.close()
    assert r.returncode == 1, r.stdout + r.stderr
    diffs = [ln for ln in r.stdout.splitlines() if ln.startswith("diff ")]
    assert len(diffs) == 1 and diffs[0].split(" ")[:3] == ["diff", records[k][1], "reply"], diffs
    assert r.stdout.splitlines()[-1] == "probe done: sent=11 matched=10"


def test_t5_a_peer_that_closes_mid_reply_gives_1(vssclaim, small):
    path, records = small
    peer = FakePeer(replies_of(records), "close-mid")
    try:
        r = probe(vssclaim, peer.port, path)
    finally:
        peer.close()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "probe done: sent=1 matched=0" in r.stdout


def test_t5_a_silent_peer_gives_1_after_the_reply_timeout(vssclaim, small):
    path, records = small
    peer = FakePeer(replies_of(records), "silent")
    try:
        start = time.monotonic()
        r = probe(vssclaim, peer.port, path, "--reply-timeout-ms", "200", timeout=20)
        took = time.monotonic() - start
    finally:
        peer.close()
    assert r.returncode == 1, r.stdout + r.stderr
    assert took < 15 and "deadline" in r.stdout


@pytest.mark.parametrize("ms,rc", [("200", 1), ("5000", 0)], ids=["200ms-gives-1", "5000ms-gives-0"])
def test_t5_the_reply_timeout_option_decides_a_reply_1_s_late(vssclaim, small, ms, rc):
    """The first reply comes 1.0 s late: under --reply-timeout-ms 200 that is past the deadline, under 5000 it is
    not. A probe that ignores the option (the 3000 ms default) fails the first case, one that caps it the second;
    no time is asserted."""
    path, records = small
    peer = FakePeer(replies_of(records), "late")
    try:
        r = probe(vssclaim, peer.port, path, "--reply-timeout-ms", ms, timeout=30)
    finally:
        peer.close()
    assert r.returncode == rc, r.stdout + r.stderr
    if rc:
        assert "deadline" in r.stdout and r.stdout.splitlines()[-1] == "probe done: sent=1 matched=0", r.stdout
    else:
        assert r.stdout.splitlines() == ["ok " + rec[1] for rec in records] + ["probe done: sent=11 matched=11"]


def test_t5_bytes_after_the_last_reply_give_1_trailing(vssclaim, small):
    path, records = small
    peer = FakePeer(replies_of(records), "trailing")
    try:
        r = probe(vssclaim, peer.port, path)
    finally:
        peer.close()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "trailing" in r.stdout and r.stdout.splitlines()[-1] == "probe done: sent=11 matched=11"


def test_t5_a_byte_100_ms_after_the_end_of_session_gives_1_trailing(vssclaim, small):
    """The byte comes only after the probe's EOF, so a probe that does not shut down its write side, or waits less
    than the 200 ms window, does not see it."""
    path, records = small
    peer = FakePeer(replies_of(records), "after-eof")
    try:
        r = probe(vssclaim, peer.port, path)
    finally:
        peer.close()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "trailing" in r.stdout and r.stdout.splitlines()[-1] == "probe done: sent=11 matched=11"


def test_t5_a_reply_dripped_past_the_deadline_gives_1(vssclaim, small):
    """One reply byte every 40 ms takes 2.56 s: under --reply-timeout-ms 500 the one deadline for the whole reply
    is past, whereas a deadline reset by each read, or an ignored option (3000 ms), lets it through."""
    path, records = small
    peer = FakePeer(replies_of(records), "drip")
    try:
        start = time.monotonic()
        r = probe(vssclaim, peer.port, path, "--reply-timeout-ms", "500", timeout=20)
        took = time.monotonic() - start
    finally:
        peer.close()
    assert r.returncode == 1 and "deadline" in r.stdout, r.stdout + r.stderr
    assert took < 2.0, took


def test_t5_no_listener_gives_1(vssclaim, small):
    path, _ = small
    r = probe(vssclaim, mc._free_port(socket.SOCK_STREAM), path)
    assert r.returncode == 1 and "error connect" in r.stdout, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "probe done: sent=0 matched=0"


def test_t5_a_request_the_rust_encoder_disagrees_with_gives_1_before_any_connect(vssclaim, small):
    path, records = small
    k = 0
    edit_field(path, k, 13, lambda x: flip(x, vf.FRAME_TOTAL_BYTES - 1, 1))
    peer = FakePeer(replies_of(records), serve=False)
    try:
        r = probe(vssclaim, peer.port, path)
        seen = peer.connected()
    finally:
        peer.close()
    assert r.returncode == 1 and not seen, (r.returncode, seen, r.stdout, r.stderr)
    assert [ln.split(" ")[:3] for ln in r.stdout.splitlines() if ln.startswith("diff ")] == [["diff", records[k][1], "request"]]


def _bad_hex(path):
    edit_field(path, 2, 15, lambda x: "zz" + x[2:])


def _upper_hex(path):
    edit_field(path, 2, 13, lambda x: x.upper())


def _short(path):
    edit_field(path, 3, 15, lambda x: x[:-2])


def _version(path):
    rewrite(path, 0, lambda ln: "claimrs-vectors\t2")


def _digest(path):
    def fn(text):
        return re.sub(r"(?m)^catalog_digest\t([0-9a-f]{8})$", lambda m: "catalog_digest\t%08x" % (int(m.group(1), 16) ^ 0x100), text)
    path.write_text(fn(path.read_text(encoding="ascii")), encoding="ascii")


def _truncated(path):
    lines = path.read_text(encoding="ascii").split("\n")
    path.write_text("\n".join(lines[:-2] + [""]), encoding="ascii")


def _patch_offset(path):
    edit_field(path, 3, 14, lambda x: "64=00")


def _record_type(path):
    rewrite(path, record_line(path, 1), lambda ln: "xx" + ln[2:])


def _key_order(path):
    lines = path.read_text(encoding="ascii").split("\n")
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("\n".join(lines), encoding="ascii")


def _no_final_newline(path):
    path.write_text(path.read_text(encoding="ascii").rstrip("\n"), encoding="ascii")


def _rt_count(path):
    text = path.read_text(encoding="ascii")
    path.write_text(re.sub(r"(?m)^rt_patched\t(\d+)$", lambda m: "rt_patched\t%d" % (int(m.group(1)) + 1), text), encoding="ascii")


def _first_patched(path):
    """The index of the first rt record that carries a patch, so a replaced patch leaves rt_patched right."""
    rts = [ln.split("\t") for ln in path.read_text(encoding="ascii").split("\n") if ln.startswith("rt\t")]
    return [k for k, f in enumerate(rts) if f[14] != "-"][0]


def _patch_the_kind(path):
    edit_field(path, _first_patched(path), 14, lambda x: "%d=05" % (H + vf.P_KIND))


def _patch_the_header(path):
    edit_field(path, _first_patched(path), 14, lambda x: "0=ff")


def _no_rt_record(path):
    """A file of one enc record and no rt record, counted right in its header."""
    mod = sys.modules["claimrs_vectors"]
    claim = vf.Claim(seq=1, tstamp_ns=0, profile=1, digest=C.CATALOG_DIGEST, v=5.0)
    mod._write(path, C, 0, [mod.enc_record("enc/one", claim)], [])


def _space_in_a_name(path):
    edit_field(path, 0, 1, lambda x: x.replace("-", " ", 1))


def _sha_62_digits(path):
    rewrite(path, 1, lambda ln: ln[:-2])


REFUSALS = {"bad-hex": _bad_hex, "uppercase-hex": _upper_hex, "wrong-length": _short, "wrong-format-version": _version,
            "digest-mismatch": _digest, "record-count-not-the-headers": _truncated,
            "patch-offset-64": _patch_offset, "unknown-record-type": _record_type, "header-key-order": _key_order,
            "no-final-newline": _no_final_newline, "rt-patched-count": _rt_count,
            "patch-outside-the-rt-rule-kind": _patch_the_kind, "patch-outside-the-rt-rule-header": _patch_the_header,
            "no-rt-record": _no_rt_record, "space-in-a-name": _space_in_a_name, "contract-sha256-62-digits": _sha_62_digits}


@pytest.mark.parametrize("what", sorted(REFUSALS))
def test_t5_a_vector_file_refusal_gives_2_and_the_peer_sees_no_connection(vssclaim, small, what):
    path, records = small
    before = path.read_text(encoding="ascii")
    REFUSALS[what](path)
    assert path.read_text(encoding="ascii") != before
    peer = FakePeer(replies_of(records), serve=False)
    try:
        r = probe(vssclaim, peer.port, path)
        seen = peer.connected()
    finally:
        peer.close()
    assert r.returncode == 2 and not seen and not r.stdout, (what, r.returncode, seen, r.stdout[:300], r.stderr)
    assert r.stderr.strip()


@pytest.mark.parametrize("argv", [["probe"], ["probe", "--host", "127.0.0.1", "--vectors", "x"], ["vectors"], ["frobnicate"],
                                  ["probe", "--host", "127.0.0.1", "--port", "0", "--vectors", "x"],
                                  ["probe", "--host", "127.0.0.1", "--port", "1", "--vectors", "x", "--reply-timeout-ms", "0"]])
def test_t5_a_usage_error_gives_2(vssclaim, argv):
    r = run([vssclaim, *argv])
    assert r.returncode == 2 and not r.stdout, (argv, r.returncode, r.stdout, r.stderr)


def test_t5_an_option_given_twice_gives_2_and_the_peer_sees_no_connection(vssclaim, small):
    path, records = small
    peer = FakePeer(replies_of(records), serve=False)
    try:
        r = probe(vssclaim, peer.port, path, "--port", peer.port)
        seen = peer.connected()
    finally:
        peer.close()
    assert r.returncode == 2 and not seen and not r.stdout, (r.returncode, seen, r.stdout[:300], r.stderr)
    assert "given twice" in r.stderr


# ============================================================ T6: lint

def test_t6_cargo_fmt_check(target):
    r = cargo(target, "--locked", "--offline", "fmt", "--check")
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


def test_t6_cargo_clippy_denies_warnings(target):
    r = cargo(target, "clippy", "--all-targets", "--locked", "--offline", "--", "-D", "warnings")
    assert r.returncode == 0, r.stderr[-6000:]
