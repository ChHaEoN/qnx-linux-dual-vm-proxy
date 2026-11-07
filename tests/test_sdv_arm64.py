"""The SDV slice's arm64 images (SDV Phase 3 WP0): the aarch64 locks, the staged arm64 builds, the arm64
pins in sdv/stack/images.json, and the static A72 scan (sdv/arm64/a64scan.py) with its driver (sdv/arm64/arm64.py).

What is tested, and how:

- The classifier on 30 encodings assembled by hand from the ARM ARM (LSE amo with a byte form and an ST* alias, CAS,
  CASP and CASPAL, LDAPR and LDAPRH, LL/SC with a store-exclusive pair, LDLAR and STLLR, and eleven negatives: v8.0
  acquire/release, register-offset, unscaled, pre- and post-indexed and unprivileged loads and stores, a CAS encoding
  with Rt2 != 11111, a data word in the exclusives' space); the guard's exact words (the flag's ldrb w16, [x16], a cbz
  w16 to three words on, the ret) against a CBNZ, w17, other offsets, the 64-bit CBZ, another load and another ret; the
  post-v8.0 information counters (RAX1 is SHA3, not SHA512); the byte-filtered word scan against a word-by-word
  reference on seeded random code with the helpers' shapes and their near misses planted; the fallback window's upper
  bound (an LL/SC word 3 words past the cbz's target guards, 4 or 5 words past it does not); an executable section at
  an address 2 mod 4.
- A synthetic aarch64 ELF built here: an executable section holding the four outline-atomics helpers' shapes (cas, casp,
  swp, ld<op>) and a bare guarded CAS (guarded), and as unguarded: no branch, a branch backwards, a branch onto no
  LL/SC, a branch onto the word itself, a CBZ on w0, a CBNZ w17, the old 8- and 9-word windows, an ldr instead of the
  flag's ldrb, a data word as the fallback, a CBNZ w17 8 words back, one CBZ over two LSE words, a CBNZ w16, a CBZ w17
  after an ldrb w16, no ret after the word; an LDAPR and an LDLAR; a non-executable section holding LSE, LDAPR and LOR
  words that must not count. The same ELF without section headers: the program-header fallback reads the same words at
  the same addresses. An object with an executable PT_LOAD read as 0 words fails the rule; one whose executable PT_LOAD
  runs past the end of the file is an error, with or without section headers; exec_load_words shows a section table that
  covers one word of its segment. Every flagged word is listed with its address and class, uncapped. Big-endian, ILP32
  and x86-64 ELFs are listed apart with their class, encoding and machine, never scanned.
- A synthetic PyInstaller CArchive (a compressed ELF entry, a stored data entry, a PYZ entry that is skipped); a cookie
  magic whose cookie or table of contents does not parse is an error, not a plain ELF: among them a cookie cut by the
  end of the data (an error, not a crash) and a table of contents of length 0 (an error, not an empty archive that
  would hide its entries); a onefile inside a onefile is opened, one nested a level deeper is an error.
- A synthetic `docker save` OCI layout: the manifest named by the image ID and its config digest are checked, every
  layer blob is checked against its digest while it is read, links are not followed, and a non-aarch64 ELF is listed
  apart; a wrong config digest, a tampered layer and a missing manifest are refused. A gzip layer of several members is
  read to its last, split between entries or inside one; a layer whose tar stops before its data does (a second
  archive after the marker, one zero block then entries, a broken or cut header, the marker in the first gzip member)
  is refused, and one without a marker or with zero padding is not; a bzip2 or xz layer of several streams is read to
  its last; zstd, a corrupt xz and gzip with trailing garbage are refused; the module's and scan_layer's docstrings
  name every compression decompressed() reads or refuses and say that a nested tar is not opened. On the command line
  a file that is neither ELF nor tar is an error verdict, not a traceback.
- The locks: each aarch64 lock has its x86_64 twin's names and versions in the same order, every none-any wheel the same
  file and hash, every other wheel a cp312 or abi3 manylinux aarch64 file whose hash differs from the x86_64 one, and
  exactly the native packages expected (tests/test_sdv_stack.py and tests/test_sdv_bridge_sources.py hold the app equal
  to the recorder and the bridge equal to app + sim for the aarch64 files too).
- sdv/bridge/build_image.py and stack.build_local_arm64 against a fake docker on PATH: --arch arm64 sends `buildx build
  --platform linux/arm64 ... --load`, the -arm64 tag and the staged aarch64 lock; without --arch the argv is the one the
  step-3 bridge image was built with, word for word; the app's and the recorder's arm64 contexts are staged with their
  aarch64 locks; a buildx --load that exits 0 but leaves no image under its tag is the same error on both build paths
  ("the build left no image tagged <tag>"), which arm64.py build prints as its CLI error line.
- arm64.py: the HWCAP canary's verdict (HWCAP_ATOMICS clear under cortex-a72, set under max, both on aarch64), the canary
  running before any image smoke and stopping them when it fails, QEMU_CPU=cortex-a72 on every image smoke, an image
  smoke failing on any non-zero exit and on HWCAP_ATOMICS read as set inside the image; the bridge's smoke failing
  when the contract sha256, catalog digest or DBC sha256 its check reports differs from images.json's bridge labels;
  scan_wheel, offline, reading the lock's file and refusing one whose sha256 differs from the lock's; the index check (the pinned
  arm64 manifest must be the index's linux/arm64 entry); the scan's gate and its floor (per upstream image at least the
  read-only map's objects and LSE words); the reviewed exceptions: an object is excepted only for its own sha256, at
  its own path in its own image, and exactly its listed flagged words (a word not listed, a listed word no longer
  flagged, changed bytes, another path or another image fail), and only that object, which is recorded with its
  counts per class and the reason; the three real entries each list their words inside identified tables, each word of
  its stated class.
- images.json: the base's arm64 manifest and the date it was read; per local image and for the bridge (a top-level entry, not under local) an
  arm64 pin {id, config_digest, tag, lock}, digests of 64 hex digits, all distinct; the bridge entry's three labels, equal
  to the current generation's when sdv-out/gen is present.
- With Docker and the pinned arm64 images present (skipped otherwise): each pin's ID names a saved manifest whose config
  digest is the pinned one, for an arm64 config; its tag names it; the bridge image carries the pinned labels.

What this does NOT show: that any image runs on the a1.metal host (Phase 3 V1); the build, the scan of the real images or the
emulated smoke themselves; any timing.
"""
import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ARM_DIR = REPO / "sdv" / "arm64"
BRIDGE_DIR = REPO / "sdv" / "bridge"
STACK_DIR = REPO / "sdv" / "stack"
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
SIM_DIR = REPO / "sdv" / "sim"
RECORDER_DIR = STACK_DIR / "recorder"
GEN = Path(os.environ.get("SDV_GEN", str(REPO / "sdv-out" / "gen"))).expanduser()

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (ARM_DIR, BRIDGE_DIR, STACK_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import a64scan as a64  # noqa: E402
import arm64  # noqa: E402
import build_image  # noqa: E402
import stack  # noqa: E402

sys.dont_write_bytecode = _saved

IMAGES = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
SHA = re.compile(r"sha256:[0-9a-f]{64}")
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX only: a fake docker on PATH (WSL)")

# ============================================================ the classifier

ENCODINGS = {
    0xF8E10062: "amo",    # ldaddal x1, x2, [x3]
    0xB8200020: "amo",    # ldadd w0, w0, [x1]
    0xF8A18062: "amo",    # swpa x1, x2, [x3]  (o3=1 opc=000, A=1)
    0x38201020: "amo",    # ldclrb w0, w0, [x1]
    0x38218062: "amo",    # swpb w1, w2, [x3]
    0xB820003F: "amo",    # stadd w0, [x1]  (ldadd w0, wzr, [x1]: the ST* alias, Rt=31)
    0xC8E0FC41: "cas",    # casal x0, x1, [x2]
    0x08A07C41: "cas",    # casb w0, w1, [x2]
    0x48207C82: "casp",   # casp x0, x1, x2, x3, [x4]  (sz=1: the 64-bit pair)
    0x4860FC82: "casp",   # caspal x0, x1, x2, x3, [x4]
    0xF8BFC020: "ldapr",  # ldapr x0, [x1]
    0x78BFC020: "ldapr",  # ldaprh w0, [x1]
    0xC85F7C20: "llsc",   # ldxr x0, [x1]
    0xC85FFC20: "llsc",   # ldaxr x0, [x1]
    0xC802FC20: "llsc",   # stlxr w2, x0, [x1]
    0xC87F0440: "llsc",   # ldxp x0, x1, [x2]
    0xC8238440: "llsc",   # stlxp w3, x0, x1, [x2]
    0xC8DF7C20: "lor",    # ldlar x0, [x1]  (v8.1 LOR)
    0xC89F7C20: "lor",    # stllr x0, [x1]  (v8.1 LOR)
    0xC8DFFC20: None,     # ldar x0, [x1]   (v8.0)
    0xC89FFC20: None,     # stlr x0, [x1]   (v8.0)
    0xF8626820: None,     # ldr x0, [x1, x2]
    0xD65F03C0: None,     # ret
    0xF8408020: None,     # ldur x0, [x1, #8]   (bit 21 clear: outside the atomics space)
    0xF8008420: None,     # str x0, [x1], #8    (post-indexed)
    0xF8408C20: None,     # ldr x0, [x1, #8]!   (pre-indexed)
    0xF8400820: None,     # ldtr x0, [x1]       (unprivileged)
    0xF8226820: None,     # str x0, [x1, x2]    (register offset: bit 21 set, bits 11:10 = 10)
    0xC8E0F841: None,     # casal's encoding with Rt2 = 11110: not a CAS
    0x08000000: None,     # the exclusives' space with Rt2 = 00000: not an LL/SC word (a data word)
}

NOP, RET = 0xD503201F, 0xD65F03C0
LDRB_W16 = 0x39400210      # ldrb w16, [x16]
ADRP_X16 = 0x90000010      # adrp x16, .
LDR_W16_X0 = 0xB9400010    # ldr w16, [x0]
MOV_W16_W0, MOV_X16_X0, MOV_X17_X1 = 0x2A0003F0, 0xAA0003F0, 0xAA0103F1
CASAL, CASB, CASP = 0xC8E0FC41, 0x08A07C41, 0x48207C82
SWPA, LDADDAL = 0xF8A18062, 0xF8E10062
LDXR, STLXR, LDXP = 0xC85F7C20, 0xC802FC20, 0xC87F0440
LDAPR, LDLAR = 0xF8BFC020, 0xC8DF7C20
DATA_EXCL = 0x08000000     # a data word in the exclusives' space (Rt2 = 00000)


def cbz(reg: int, delta: int, nz: bool = False) -> int:
    """CBZ/CBNZ w<reg>, <delta words> (32-bit form)."""
    return (0x35000000 if nz else 0x34000000) | ((delta & 0x7FFFF) << 5) | reg


# The old guard window's bound (8 words), kept as negatives: a CBZ w16 8 (9) words before the CAS, branching past it to
# the LL/SC fallback, is not the helper's shape.
WINDOW_8 = [LDRB_W16, cbz(16, 10)] + [NOP] * 7 + [CASAL, RET, LDXR, STLXR, RET]
WINDOW_9 = [LDRB_W16, cbz(16, 11)] + [NOP] * 8 + [CASAL, RET, LDXR, STLXR, RET]

# The outline-atomics helpers' four shapes (cas, casp, swp, ld<op>): the flag's address, its load, the CBZ past the LSE
# word and its ret, then the fallback's register copies and its LL/SC loop.
HELPERS = {
    "helper-cas": [ADRP_X16, LDRB_W16, cbz(16, 3), CASAL, RET, MOV_W16_W0, LDXR, STLXR, RET],
    "helper-casp": [ADRP_X16, LDRB_W16, cbz(16, 3), CASP, RET, MOV_X16_X0, MOV_X17_X1, LDXP, RET],
    "helper-swp": [ADRP_X16, LDRB_W16, cbz(16, 3), SWPA, RET, MOV_W16_W0, LDXR, STLXR, RET],
    "helper-ldop": [ADRP_X16, LDRB_W16, cbz(16, 3), LDADDAL, RET, MOV_W16_W0, LDXR, STLXR, RET],
}
# Near misses of that shape (the review's G1-G4 and the branch's own variants): each LSE word in them is unguarded.
NEAR_MISSES = {
    "g1-ldr-not-ldrb": ([LDR_W16_X0, cbz(16, 3), CASAL, RET, NOP, LDXR, STLXR], (2,)),
    "g2-data-fallback": ([LDRB_W16, cbz(16, 3), CASAL, RET, DATA_EXCL, NOP, NOP, NOP, RET], (2,)),
    "g3-cbnz-w17-far": ([cbz(17, 10, nz=True)] + [NOP] * 7 + [SWPA, RET, LDXR, STLXR, RET], (8,)),
    "g4-one-cbz-two-lse": ([LDRB_W16, cbz(16, 3), CASAL, SWPA, LDXR, STLXR, RET], (2, 3)),
    "cbnz-w16-inverted": ([LDRB_W16, cbz(16, 3, nz=True), CASAL, RET, LDXR, STLXR, RET], (2,)),
    "cbz-w17-not-the-loaded-flag": ([LDRB_W16, cbz(17, 3), CASAL, RET, LDXR, STLXR, RET], (2,)),
    "no-ret-after": ([LDRB_W16, cbz(16, 3), CASAL, NOP, LDXR, STLXR, RET], (2,)),
}


@pytest.mark.parametrize("word,want", sorted(ENCODINGS.items()))
def test_the_classifier_on_the_hand_assembled_encodings(word, want):
    assert a64.classify(word) == want


def test_thirty_encodings_cover_every_class_its_forms_and_eleven_negatives():
    assert len(ENCODINGS) == 30
    got = sorted(str(v) for v in ENCODINGS.values())
    assert {"amo", "cas", "casp", "ldapr", "llsc", "lor"} <= set(got) and got.count("None") == 11
    assert all(got.count(c) >= 2 for c in ("amo", "cas", "casp", "ldapr", "llsc", "lor"))


def test_the_guard_is_the_helpers_exact_load_branch_and_ret():
    assert a64.guard_shape(LDRB_W16, cbz(16, 3), RET)
    assert a64.guard_shape(LDRB_W16 | (0x9A5 << 10), 0x34000070, RET)            # ldrb w16, [x16, #0x9a5]; cbz w16, #12
    assert not a64.guard_shape(LDRB_W16, cbz(16, 3, nz=True), RET)                # cbnz: the LSE word runs when the flag is clear
    assert not a64.guard_shape(LDRB_W16, cbz(17, 3), RET)                         # a register the load did not set
    assert not a64.guard_shape(LDRB_W16, cbz(16, 4), RET) and not a64.guard_shape(LDRB_W16, cbz(16, 2), RET)
    assert not a64.guard_shape(LDRB_W16, 0xB4000070, RET)                         # cbz x16: the 64-bit form
    assert not a64.guard_shape(LDR_W16_X0, cbz(16, 3), RET)                       # ldr w16, [x0]: not the flag's load
    assert not a64.guard_shape(0x39400230, cbz(16, 3), RET)                       # ldrb w16, [x17]
    assert not a64.guard_shape(0x39400211, cbz(16, 3), RET)                       # ldrb w17, [x16]
    assert not a64.guard_shape(LDRB_W16, cbz(16, 3), 0xD65F0020)                  # ret x1
    assert not a64.guard_shape(LDRB_W16, cbz(16, 3), NOP)


def test_the_fallback_ll_sc_must_lie_within_four_words_of_the_branch_target():
    """FALLBACK_WINDOW's upper bound, with literal positions: the cbz's target is the word after the helper's ret; an
    LL/SC word 0 or 3 words past it guards the LSE word, one 4 or 5 words past it does not."""
    for gap, guarded in ((0, True), (3, True), (4, False), (5, False)):
        words = [NOP] * 9 + [LDRB_W16, cbz(16, 3), CASAL, RET] + [NOP] * gap + [LDXR, STLXR, RET] + [NOP] * 9
        data = b"".join(struct.pack("<I", w) for w in words)
        counts = a64.new_counts()
        a64.scan_words(data, 0, len(data), 0x1000, counts)
        assert (counts["lse"], counts["guarded"], counts["unguarded"]) == ((1, 1, 0) if guarded else (1, 0, 1)), gap
        assert counts["unguarded_at"] == ([] if guarded else ["0x%x cas %08x" % (0x1000 + 4 * 11, CASAL)]), gap


def test_the_information_counters_name_each_post_v80_class_once():
    assert a64.info_class(0xCE608000) == "sha512"     # sha512h q0, q0, v0.2d
    assert a64.info_class(0xCEC08000) == "sha512"     # sha512su0
    assert a64.info_class(0xCE608C00) == "sha3"       # rax1: SHA3, not SHA512
    assert a64.info_class(0xCE000000) == "sha3"       # eor3
    assert a64.info_class(0x4E809400) == "dotprod"    # sdot v0.4s, v0.16b, v0.16b
    assert a64.info_class(0x6E408400) == "rdm"        # sqrdmlah v0.8h, v0.8h, v0.8h
    assert a64.info_class(0x4E284800) is None         # aese v0.16b, v0.16b: ARMv8.0 crypto, not counted
    for w in ENCODINGS:
        assert a64.info_class(w) is None


def _reference(words: List[int]) -> Dict[str, Any]:
    """Word by word, no byte filter: the guard rule as a64scan's docstring states it, written out here on its own."""
    out: Dict[str, Any] = {k: 0 for k in ("llsc", "cas", "casp", "amo", "ldapr", "lor", "lse", "guarded", "unguarded")}
    out["info"] = {k: 0 for k in a64.INFO}
    n = len(words)
    for i, w in enumerate(words):
        k = a64.info_class(w)
        if k:
            out["info"][k] += 1
        c = a64.classify(w)
        if c is None:
            continue
        out[c] += 1
        if c in a64.LSE:
            out["lse"] += 1
            g = (2 <= i and i + 2 < n and (words[i - 2] & 0xFFC003FF) == 0x39400210 and words[i - 1] == 0x34000070
                 and words[i + 1] == RET and any(a64.classify(words[m]) == "llsc" for m in range(i + 2, min(n, i + 6))))
            out["guarded" if g else "unguarded"] += 1
    return out


def test_the_byte_filtered_scan_equals_a_word_by_word_reference():
    rnd = random.Random(20261002)
    words = [rnd.getrandbits(32) for _ in range(6000)]
    families = [0x08000000, 0x38200000, 0x88200000, 0xC8000000, 0xF8200000, 0xCE000000, 0x0E000000, 0x2E000000, 0x6E000000]
    for i in range(0, 6000, 7):                       # bias towards the classes' own encoding families
        words[i] = rnd.choice(families) | rnd.getrandbits(24)
    for i, w in enumerate(list(ENCODINGS) + [cbz(16, 3), cbz(17, 2, nz=True), cbz(16, -5), LDRB_W16] * 20):
        words[(i * 37) % 6000] = w
    shapes = list(HELPERS.values()) + [ws for ws, _at in NEAR_MISSES.values()]
    for k in range(22):                               # the helpers' shapes and their near misses, among the noise
        at = 250 + 250 * k
        s = shapes[k % len(shapes)]
        words[at:at + len(s)] = s
    words[5700:5700 + len(WINDOW_8)] = WINDOW_8       # the old guard window's bound: its CBZ exactly 8 words before the CAS
    words[5800:5800 + len(WINDOW_9)] = WINDOW_9       # ... and 9 words before it
    data = b"".join(struct.pack("<I", w) for w in words)
    counts = a64.new_counts()
    a64.scan_words(data, 0, len(data), 0x1000, counts)
    ref = _reference(words)
    assert counts["exec_words"] == 6000
    for k, v in ref.items():
        assert counts[k] == v, k
    assert counts["lse"] > 50 and counts["guarded"] >= 8 and counts["unguarded"] and counts["info"]["dotprod"]
    flagged = {int(s.split()[0], 16) for s in counts["unguarded_at"]}
    assert 0x1000 + 4 * (5700 + 9) in flagged and 0x1000 + 4 * (5800 + 10) in flagged
    for k in range(22):                               # each helper's LSE word guarded, each near miss's flagged
        at = 250 + 250 * k
        name = list(HELPERS) + list(NEAR_MISSES)
        nm = name[k % len(name)]
        lse_at = (3,) if nm in HELPERS else NEAR_MISSES[nm][1]
        for j in lse_at:
            assert ((0x1000 + 4 * (at + j)) in flagged) == (nm not in HELPERS), (nm, j)


def test_an_exec_section_at_an_address_2_mod_4_is_read_from_its_first_aligned_word():
    data = b"\x00\x00" + b"".join(struct.pack("<I", w) for w in (CASB, NOP, RET))
    counts = a64.new_counts()
    a64.scan_words(data, 0, len(data), 0x1002, counts)
    assert counts["exec_words"] == 3 and counts["cas"] == 1
    assert counts["unguarded_at"] == ["0x1004 cas %08x" % CASB]


# ============================================================ a synthetic ELF

def _blocks() -> Tuple[List[int], Dict[str, int]]:
    """The executable section's words, and the index of each case's LSE word (a second one in a case is `<name>#2`)."""
    words: List[int] = []
    at: Dict[str, int] = {}

    def block(name: str, ws: List[int], lse_at: Sequence[int]) -> None:
        words.extend([NOP] * 9)                       # padding: each case's shape sees only its own block
        for n, j in enumerate(lse_at):
            at[name if n == 0 else "%s#%d" % (name, n + 1)] = len(words) + j
        words.extend(ws)

    block("guarded", [LDRB_W16, cbz(16, 3), CASAL, RET, LDXR, STLXR, RET], (2,))
    block("no-branch", [CASB, RET], (0,))
    block("backwards", [LDXR, STLXR, RET, LDRB_W16, cbz(16, -4), SWPA, RET], (5,))
    block("no-llsc-at-target", [LDRB_W16, cbz(16, 3), LDADDAL, RET, NOP, NOP, NOP, NOP, RET], (2,))
    block("stops-on-the-word", [LDRB_W16, cbz(16, 1), CASAL, RET, LDXR, RET], (2,))
    block("w0", [cbz(0, 3), CASB, RET, LDXR, STLXR, RET], (1,))
    block("cbnz-w17", [cbz(17, 3, nz=True), CASP, RET, NOP, NOP, LDXR, RET], (1,))
    block("window-8", WINDOW_8, (9,))                 # the old window's first word: not the helper's shape
    block("window-9", WINDOW_9, (10,))
    for name, ws in HELPERS.items():                  # the four real shapes: guarded
        block(name, ws, (3,))
    for name, (ws, lse_at) in NEAR_MISSES.items():
        block(name, ws, lse_at)
    block("rcpc-lor", [LDAPR, LDLAR, RET], ())
    return words, at


TEXT_ADDR, RO_ADDR = 0x10000, 0x40000
GUARDED = {"guarded"} | set(HELPERS)


def make_elf(text_words: List[int], ro_words: List[int], sections: bool = True, machine: int = 183) -> bytes:
    text = b"".join(struct.pack("<I", w) for w in text_words)
    ro = b"".join(struct.pack("<I", w) for w in ro_words)
    phoff, text_off = 64, 0x100
    ro_off = text_off + len(text) + (-len(text)) % 16
    shstr = b"\0.text\0.rodata\0.shstrtab\0"
    shstr_off = ro_off + len(ro)
    shoff = shstr_off + len(shstr) + (-(shstr_off + len(shstr))) % 8
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    hdr = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, machine, 1, TEXT_ADDR, phoff, shoff if sections else 0, 0, 64, 56, 2,
                      64, 4 if sections else 0, 3 if sections else 0)
    ph = (struct.pack("<IIQQQQQQ", 1, 5, text_off, TEXT_ADDR, TEXT_ADDR, len(text), len(text), 0x1000)
          + struct.pack("<IIQQQQQQ", 1, 4, ro_off, RO_ADDR, RO_ADDR, len(ro), len(ro), 0x1000))
    body = bytearray(hdr + ph)
    body += b"\0" * (text_off - len(body)) + text
    body += b"\0" * (ro_off - len(body)) + ro + shstr
    if sections:
        body += b"\0" * (shoff - len(body))
        body += b"\0" * 64
        body += struct.pack("<IIQQQQIIQQ", 1, 1, 0x6, TEXT_ADDR, text_off, len(text), 0, 0, 4, 0)
        body += struct.pack("<IIQQQQIIQQ", 7, 1, 0x2, RO_ADDR, ro_off, len(ro), 0, 0, 8, 0)
        body += struct.pack("<IIQQQQIIQQ", 15, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    return bytes(body)


RO_WORDS = [CASAL, LDADDAL, LDAPR, LDLAR, CASP]       # in a non-executable section: none of these may count


def _expect(rec: Dict[str, Any], at: Dict[str, int], n_words: int) -> None:
    assert rec["exec_words"] == n_words
    assert rec["lse"] == 21 and rec["guarded"] == 5 and rec["unguarded"] == 16
    assert (rec["cas"], rec["casp"], rec["amo"], rec["llsc"], rec["ldapr"], rec["lor"]) == (13, 2, 6, 31, 1, 1)
    flagged = {int(s.split()[0], 16) for s in rec["unguarded_at"]}
    assert flagged == {TEXT_ADDR + 4 * i for name, i in at.items() if name not in GUARDED}
    assert len(rec["ldapr_at"]) == 1 and len(rec["lor_at"]) == 1
    assert (rec["flagged_code_like"], rec["flagged_data_like"], rec["flagged_min_share"]) == (18, 0, 0.0)  # all among code


def test_the_synthetic_elf_counts_only_its_executable_section_under_the_exact_guard():
    words, at = _blocks()
    assert len(at) == 21 and len([n for n in at if n in GUARDED]) == 5
    rec = a64.scan_elf(make_elf(words, RO_WORDS))
    assert rec["source"] == "sections" and rec["exec_load"] and rec["exec_load_words"] == len(words)
    _expect(rec, at, len(words))


def test_without_section_headers_the_program_headers_give_the_same_words():
    words, at = _blocks()
    data = make_elf(words, RO_WORDS, sections=False)
    assert struct.unpack_from("<QHHH", data, 0x28)[0] == 0
    rec = a64.scan_elf(data)
    assert rec["source"].startswith("segments") and "no section headers" in rec["source"]
    _expect(rec, at, len(words))
    assert rec == dict(a64.scan_elf(make_elf(words, RO_WORDS)), source=rec["source"])


def test_a_flagged_word_amid_table_data_reads_data_like_and_still_fails_the_rule():
    rnd = random.Random(7)
    table = [rnd.getrandbits(32) for _ in range(400)]
    table = [w for w in table if a64.classify(w) is None]           # no accidental hit but the one placed below
    table[200] = SWPA
    rec = dict(a64.scan_elf(make_elf([NOP] * 9 + [RET] + table + [RET], [])), path="t")
    assert rec["unguarded"] == 1 and rec["flagged_data_like"] == 1 and rec["flagged_code_like"] == 0
    assert rec["flagged_min_share"] >= a64.CODE_LIKE_MAX_SHARE
    assert any("unguarded" in w for w in a64.clean(a64.summarize([rec])))      # information, never a pass
    assert a64.reserved_top_level(0x00000000) and a64.reserved_top_level(0x02000000) and a64.reserved_top_level(0x06000000)
    assert not any(a64.reserved_top_level(w) for w in (NOP, RET, LDXR, CASAL, SWPA, LDRB_W16, cbz(16, 3), 0x4E809400))


def _data_table(seed: int, planted: Sequence[Tuple[int, int]]) -> List[int]:
    """400 random words none of which classifies, with the planted (index, word) pairs."""
    rnd = random.Random(seed)
    table = [w for w in (rnd.getrandbits(32) for _ in range(800)) if a64.classify(w) is None][:400]
    assert len(table) == 400
    for i, w in planted:
        table[i] = w
    return table


def _table_object(table: List[int], path: str = "L0:usr/lib/libt.so") -> Dict[str, Any]:
    """The object a Collector records for an ELF whose executable section is the table (from word 10 on)."""
    col = a64.Collector()
    col.blob(path, make_elf([NOP] * 9 + [RET] + table + [RET], []))
    (obj,) = col.objects
    return obj


FLAG_WORD = re.compile(r"0x([0-9a-f]+) (cas|casp|amo|ldapr|lor) ([0-9a-f]{8})")


def test_every_flagged_word_is_listed_with_its_address_and_class_uncapped():
    planted = [(10 + 12 * k, [SWPA, CASB, LDLAR, LDAPR][k % 4]) for k in range(30)]
    obj = _table_object(_data_table(5, planted))
    assert (obj["unguarded"], obj["ldapr"], obj["lor"]) == (16, 7, 7)
    words = a64.flagged_words(obj)
    assert len(words) == 30 == len(obj["unguarded_at"]) + len(obj["ldapr_at"]) + len(obj["lor_at"])
    assert words == ["0x%x %s %08x" % (TEXT_ADDR + 4 * (10 + i), a64.classify(w), w) for i, w in planted]
    for w in words:
        m = FLAG_WORD.fullmatch(w)
        assert m and a64.classify(int(m.group(3), 16)) == m.group(2), w


def test_an_object_with_code_read_as_no_words_fails_the_rule():
    words, _at = _blocks()
    rec = dict(a64.scan_elf(make_elf(words, [])), path="x", exec_words=0)
    s = a64.summarize([rec])
    assert s["code_read_as_none"] == ["x"] and any("read as 0 words" in w for w in a64.clean(s))
    ok = dict(a64.scan_elf(make_elf([NOP, RET], [])), path="y")
    assert a64.clean(a64.summarize([ok])) == []


def test_a_clean_summary_needs_no_unguarded_lse_no_ldapr_no_lor_and_no_unread_object():
    words, _at = _blocks()
    rec = dict(a64.scan_elf(make_elf(words, [])), path="flagged")
    why = a64.clean(a64.summarize([rec]))
    assert any("unguarded" in w for w in why) and any("ldapr" in w for w in why) and any("lor" in w for w in why)
    assert any("not read" in w for w in a64.clean(a64.summarize([], errors=["z: broken"])))
    guarded_only = [NOP] * 9 + [LDRB_W16, cbz(16, 3), CASAL, RET, LDXR, STLXR, RET]
    assert a64.clean(a64.summarize([dict(a64.scan_elf(make_elf(guarded_only, [])), path="g")])) == []


def test_a_non_aarch64_elf_and_a_non_elf_are_not_objects():
    col = a64.Collector()
    col.blob("x86", make_elf([NOP], [], machine=62))
    col.blob("text", b"#!/bin/sh\n")
    col.blob("arm", make_elf([NOP], []))
    assert [o["path"] for o in col.objects] == ["arm"]
    s = col.summary()
    assert s["other_elf"] == 1 and s["other_elf_objects"] == [{"path": "x86", "ei_class": 2, "ei_data": 1, "e_machine": 62}]


def test_a_big_endian_or_ilp32_aarch64_elf_is_listed_apart_and_never_scanned():
    le = make_elf([NOP] * 9 + [CASB, RET], [])
    assert a64.scan_elf(le)["unguarded"] == 1
    flipped_data = le[:5] + b"\x02" + le[6:]               # EI_DATA says big-endian: not this scanner's object
    ilp32 = le[:4] + b"\x01" + le[5:]                      # EI_CLASS 1 (ELFCLASS32) with EM_AARCH64
    be = (b"\x7fELF" + bytes([2, 2, 1, 0]) + b"\0" * 8 + struct.pack(">HHI", 3, a64.EM_AARCH64, 1)).ljust(0x100, b"\0") \
        + struct.pack(">I", CASB)                          # a big-endian aarch64 header, its CAS stored big-endian
    col = a64.Collector()
    for name, data in (("flipped", flipped_data), ("ilp32", ilp32), ("be", be), ("short", b"\x7fELF\x02")):
        col.blob(name, data)
    s = col.summary()
    assert col.objects == [] and s["objects"] == 0 and s["other_elf"] == 4
    assert s["other_elf_objects"] == [{"path": "flipped", "ei_class": 2, "ei_data": 2, "e_machine": 0xB700},
                                      {"path": "ilp32", "ei_class": 1, "ei_data": 1, "e_machine": a64.EM_AARCH64},
                                      {"path": "be", "ei_class": 2, "ei_data": 2, "e_machine": a64.EM_AARCH64},
                                      {"path": "short", "ei_class": 2, "ei_data": None, "e_machine": None}]
    assert a64.clean(s) == []                              # listed for a reader, not gated: none of them runs on an LE arm64 kernel as A64


def test_an_executable_segment_cut_by_the_end_of_the_file_is_an_error():
    words, _at = _blocks()
    cut = 0x100 + 4 * 9 + 2                                # inside the text segment, past the first nine words
    for sections in (False, True):                         # with section headers, they lie past the cut: the segment path again
        data = make_elf(words, [], sections=sections)[:cut]
        with pytest.raises(a64.ScanError, match="past the end of the file"):
            a64.scan_elf(data)
        col = a64.Collector()
        col.blob("cut", data)
        assert col.objects == [] and len(col.errors) == 1 and "past the end of the file" in col.errors[0]
        assert any("not read" in w for w in a64.clean(col.summary()))


def test_exec_load_words_shows_a_section_table_that_covers_little_of_its_segment():
    words, _at = _blocks()
    data = bytearray(make_elf(words, []))
    shoff = struct.unpack_from("<Q", data, 0x28)[0]
    struct.pack_into("<Q", data, shoff + 64 + 0x20, 4)      # .text's sh_size: one word of the R-X segment
    rec = a64.scan_elf(bytes(data))
    assert rec["source"] == "sections" and rec["exec_words"] == 1 and rec["exec_load_words"] == len(words)
    assert rec["lse"] == 0                                 # the sections are trusted: information, not a verdict


# ============================================================ PyInstaller

def make_carchive(bootloader: bytes, entries: List[Tuple[str, str, bytes, bool]]) -> bytes:
    """A PyInstaller onefile: the bootloader, the entries' data, the TOC and the 88-byte cookie."""
    data, toc = b"", b""
    for name, typ, blob, compress in entries:
        stored = zlib.compress(blob) if compress else blob
        nm = name.encode() + b"\0"
        nm += b"\0" * ((-(18 + len(nm))) % 16)
        toc += struct.pack("!IIIIBc", 18 + len(nm), len(data), len(stored), len(blob), int(compress), typ.encode()) + nm
        data += stored
    pkg_len = len(data) + len(toc) + 88
    cookie = struct.pack("!8sIIII64s", a64.PYI_MAGIC, pkg_len, len(data), len(toc), 312, b"libpython3.12.so.1.0")
    return bootloader + data + toc + cookie


def test_the_carchive_reader_decompresses_every_entry_but_the_pyz():
    words, _at = _blocks()
    lib = make_elf(words, [])
    boot = make_elf([NOP] * 9 + [LDRB_W16, cbz(16, 3), CASAL, RET, LDXR, STLXR, RET], [])
    exe = make_carchive(boot, [("libfoo.so", "b", lib, True), ("data/notes.txt", "x", b"plain data", False),
                               ("PYZ-00.pyz", "z", b"\0" * 64, False)])
    arc = a64.carchive_entries(exe)
    assert arc is not None and arc["skipped"] == {"z": 1}
    assert [(n, t, b) for n, t, b in arc["entries"]] == [("libfoo.so", "b", lib), ("data/notes.txt", "x", b"plain data")]
    col = a64.Collector()
    col.blob("app/provider", exe)
    assert [o["path"] for o in col.objects] == ["app/provider", "app/provider!libfoo.so"]
    assert col.objects[0]["unguarded"] == 0 and col.objects[1]["unguarded"] == 16
    assert col.carchives == [{"path": "app/provider", "entries": 2, "skipped": {"z": 1}}]


def test_a_cookie_magic_whose_cookie_or_toc_does_not_parse_is_an_error():
    boot = make_elf([NOP], [])
    assert a64.carchive_entries(boot) is None                                   # no magic: no archive
    with pytest.raises(a64.ScanError, match="does not parse"):
        a64.carchive_entries(boot + a64.PYI_MAGIC + b"\xff" * 80)
    words, _at = _blocks()
    good = make_carchive(boot, [("libfoo.so", "b", make_elf(words, []), True)])
    assert a64.carchive_entries(good) is not None
    bad = bytearray(good)                                    # the TOC's length raised to reach the cookie's end
    pos = good.rfind(a64.PYI_MAGIC)
    _m, pkg_len, toc_off, toc_len, _v, _lib = a64.PYI_COOKIE.unpack_from(good, pos)
    struct.pack_into("!I", bad, pos + 16, pkg_len - toc_off)
    with pytest.raises(a64.ScanError, match="does not parse"):
        a64.carchive_entries(bytes(bad))
    for data in (bytes(bad), boot + a64.PYI_MAGIC + b"\xff" * 80):
        col = a64.Collector()
        col.blob("app/exe", data)
        assert [o["path"] for o in col.objects] == ["app/exe"] and col.carchives == []
        assert len(col.errors) == 1 and col.errors[0].startswith("app/exe: ") and "does not parse" in col.errors[0]
        assert any("not read" in w for w in a64.clean(col.summary()))


def test_a_cookie_cut_by_the_end_of_the_data_is_an_error_not_a_crash():
    boot = make_elf([NOP], [])
    words, _at = _blocks()
    good = make_carchive(boot, [("libfoo.so", "b", make_elf(words, []), True)])
    assert good[-a64.PYI_COOKIE.size:].startswith(a64.PYI_MAGIC)
    for cut in (good[:-1], good[:-80], boot + a64.PYI_MAGIC):       # the magic found, fewer than 88 bytes from it on
        with pytest.raises(a64.ScanError, match="does not parse: the cookie runs past the end of the data"):
            a64.carchive_entries(cut)
        col = a64.Collector()
        col.blob("app/exe", cut)
        assert [o["path"] for o in col.objects] == ["app/exe"] and col.carchives == []
        assert len(col.errors) == 1 and col.errors[0].startswith("app/exe: ") and "the cookie runs past the end" in col.errors[0]
        assert any("not read" in w for w in a64.clean(col.summary()))


def test_a_table_of_contents_of_length_zero_is_an_error_not_an_empty_archive():
    boot = make_elf([NOP], [])
    words, _at = _blocks()
    good = make_carchive(boot, [("libfoo.so", "b", make_elf(words, []), True)])
    hidden = bytearray(good)                                         # the cookie's toc_len set to 0: its entry would vanish
    pos = good.rfind(a64.PYI_MAGIC)
    struct.pack_into("!I", hidden, pos + 16, 0)
    _m, pkg_len, toc_off, toc_len, _v, _lib = a64.PYI_COOKIE.unpack_from(bytes(hidden), pos)
    assert toc_len == 0 and pos + a64.PYI_COOKIE.size - pkg_len >= 0 and toc_off <= pkg_len     # no other refusal applies
    for data in (bytes(hidden), make_carchive(boot, [])):             # and an archive written with no entries at all
        with pytest.raises(a64.ScanError, match=r"does not parse: package length \d+, TOC at \d+\+0$"):
            a64.carchive_entries(data)
        col = a64.Collector()
        col.blob("app/exe", data)
        assert [o["path"] for o in col.objects] == ["app/exe"] and col.carchives == []
        assert len(col.errors) == 1 and col.errors[0].startswith("app/exe: ") and "TOC at" in col.errors[0]
        assert any("not read" in w for w in a64.clean(col.summary()))


def test_a_onefile_inside_a_onefile_is_opened_and_one_nested_deeper_is_an_error():
    words, _at = _blocks()
    boot = make_elf([NOP], [])
    inner = make_carchive(boot, [("libfoo.so", "b", make_elf(words, []), True)])
    outer = make_carchive(boot, [("helper-exe", "b", inner, True)])
    col = a64.Collector()
    col.blob("app/exe", outer)
    assert [o["path"] for o in col.objects] == ["app/exe", "app/exe!helper-exe", "app/exe!helper-exe!libfoo.so"]
    assert col.objects[2]["unguarded"] == 16 and col.errors == []
    assert [c["path"] for c in col.carchives] == ["app/exe", "app/exe!helper-exe"]
    deeper = make_carchive(boot, [("outer-exe", "b", outer, True)])
    col = a64.Collector()
    col.blob("app/exe", deeper)
    assert [o["path"] for o in col.objects][:3] == ["app/exe", "app/exe!outer-exe", "app/exe!outer-exe!helper-exe"]
    assert len(col.errors) == 1 and col.errors[0].startswith("app/exe!outer-exe!helper-exe: ") and "nested" in col.errors[0]
    assert any("not read" in w for w in a64.clean(col.summary()))


# ============================================================ OCI layers and docker save

def _tar(members: Sequence[Tuple[str, bytes]], links: Sequence[Tuple[str, str, bool]] = (), gz: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for name, target, hard in links:
            ti = tarfile.TarInfo(name)
            ti.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
            ti.linkname = target
            tf.addfile(ti)
    raw = buf.getvalue()
    return gzip.compress(raw, mtime=0) if gz else raw


def _digest(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def make_saved_image(tmp: Path, layers: List[bytes], arch: str = "arm64", tamper: Optional[int] = None) -> Tuple[Path, str, str]:
    cfg = json.dumps({"architecture": arch, "os": "linux", "rootfs": {"type": "layers"}}).encode()
    man = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                      "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": _digest(cfg), "size": len(cfg)},
                      "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": _digest(lay),
                                  "size": len(lay)} for lay in layers]}).encode()
    blobs = {_digest(b): b for b in [cfg, man] + layers}
    if tamper is not None:          # one byte of file data flipped: the tar still parses, the blob no longer hashes to its name
        bad = bytearray(layers[tamper])
        bad[600] ^= 0x01
        blobs[_digest(layers[tamper])] = bytes(bad)
    index = json.dumps({"schemaVersion": 2, "manifests": [{"digest": _digest(man), "size": len(man)}]}).encode()
    path = tmp / "saved.tar"
    path.write_bytes(_tar([("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'), ("index.json", index)]
                          + [("blobs/sha256/" + d.split(":")[1], b) for d, b in blobs.items()], gz=False))
    return path, _digest(man), _digest(cfg)


def _layers() -> List[bytes]:
    words, _at = _blocks()
    elf = make_elf(words, [])
    lay1 = _tar([("usr/lib/libx.so", elf), ("usr/bin/tool-x86", make_elf([NOP], [], machine=62)), ("etc/conf", b"k=v\n")],
                [("usr/lib/libx.so.1", "libx.so", False), ("usr/lib/libx-hard.so", "usr/lib/libx.so", True)])
    lay2 = _tar([("app/bin", make_elf([NOP] * 4, []))], gz=False)
    return [lay1, lay2]


def test_a_saved_image_is_read_by_its_id_and_config_digest_every_layer_hash_checked(tmp_path):
    path, iid, cd = make_saved_image(tmp_path, _layers())
    r = a64.scan_saved_image(str(path), iid, cd)
    assert r["config_digest"] == cd and r["architecture"] == "arm64" and len(r["layers"]) == 2
    s = r["summary"]
    assert s["objects"] == 2 and s["other_elf"] == 1 and s["unguarded"] == 16
    assert s["other_elf_objects"] == [{"path": "L0:usr/bin/tool-x86", "ei_class": 2, "ei_data": 1, "e_machine": 62}]
    assert [o["path"] for o in r["objects"]] == ["L0:usr/lib/libx.so", "L1:app/bin"]


def _tar_body(members: Sequence[Tuple[str, bytes]]) -> bytes:
    """The tar's entries without its end-of-archive marker (two zero blocks) or any padding."""
    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w")
    for name, data in members:
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    end = tf.offset
    tf.close()
    return buf.getvalue()[:end]


def _scan_blob(blob: bytes) -> a64.Collector:
    col = a64.Collector()
    a64.scan_layer(io.BytesIO(blob), _digest(blob), col, "L0:")
    return col


def test_a_layer_of_several_gzip_members_is_read_to_its_last():
    words, _at = _blocks()
    elf = make_elf(words, [])
    first = _tar_body([("etc/conf", b"k=v\n")])                       # whole entries, no marker: the next member goes on
    second = _tar([("usr/lib/libx.so", elf)], gz=False)                # the ELF and the end-of-archive marker
    col = _scan_blob(gzip.compress(first, mtime=0) + gzip.compress(second, mtime=0))
    assert [o["path"] for o in col.objects] == ["L0:usr/lib/libx.so"] and col.objects[0]["unguarded"] == 16
    whole = first + second                                             # members split mid-entry read the same
    col = _scan_blob(gzip.compress(whole[:700], mtime=0) + gzip.compress(whole[700:5000], mtime=0)
                     + gzip.compress(whole[5000:], mtime=0))
    assert [o["path"] for o in col.objects] == ["L0:usr/lib/libx.so"] and col.errors == []


def test_a_layer_whose_tar_stops_before_its_data_does_is_refused():
    words, _at = _blocks()
    elf = make_elf(words, [])
    conf = _tar_body([("etc/conf", b"k=v\n")])
    lib = _tar([("usr/lib/libx.so", elf)], gz=False)
    cases = [
        _tar([("etc/conf", b"k=v\n")], gz=False) + lib,                # a second archive after the marker
        conf + b"\0" * 512 + lib,                                      # one zero block, then entries
        conf + b"\x01" * 512 + b"\0" * 1024,                           # a broken header after the entries
        conf + b"usr/lib/libx.so\0",                                   # a header cut short
    ]
    blobs = [b for raw in cases for b in (raw, gzip.compress(raw, mtime=0))]
    blobs.append(gzip.compress(_tar([("etc/conf", b"k=v\n")], gz=False), mtime=0) + gzip.compress(lib, mtime=0))
    refused = []                                                       # the last: the marker in the first gzip member
    for blob in blobs:
        try:
            col = _scan_blob(blob)
            refused.append("read: %s" % [o["path"] for o in col.objects])
        except a64.ScanError as exc:
            refused.append("refused" if "after the tar's end" in str(exc) else str(exc))
    assert refused == ["refused"] * len(blobs)
    # what does pass: no marker at all after whole entries, or a marker followed by zeros only (record padding)
    assert [o["path"] for o in _scan_blob(conf + _tar_body([("usr/lib/libx.so", elf)])).objects] == ["L0:usr/lib/libx.so"]
    assert _scan_blob(_tar([("etc/conf", b"k=v\n")], gz=False) + b"\0" * 20480).errors == []


def test_a_zstd_layer_a_corrupt_xz_layer_and_a_gzip_layer_with_trailing_garbage_are_refused():
    zst = a64.ZSTD_MAGIC + b"\0" * 64
    with pytest.raises(a64.ScanError, match="zstd"):
        _scan_blob(zst)
    for blob in (b"\xfd7zXZ\x00" + b"\x01" * 64, gzip.compress(_tar([("etc/conf", b"k=v\n")], gz=False), mtime=0) + b"junk"):
        with pytest.raises(a64.ScanError, match="not a readable tar"):
            _scan_blob(blob)


def test_a_bzip2_or_xz_layer_of_several_streams_is_read_to_its_last():
    words, _at = _blocks()
    elf = make_elf(words, [])
    first = _tar_body([("etc/conf", b"k=v\n")])                       # whole entries, no marker: the next stream goes on
    second = _tar([("usr/lib/libx.so", elf)], gz=False)
    for compress in (bz2.compress, lzma.compress):
        col = _scan_blob(compress(first) + compress(second))
        assert [o["path"] for o in col.objects] == ["L0:usr/lib/libx.so"] and col.errors == [], compress


def test_the_docstrings_name_every_compression_read_or_refused_and_that_a_nested_tar_is_not_opened():
    for where, doc in (("module", a64.__doc__), ("scan_layer", a64.scan_layer.__doc__)):
        flat = " ".join((doc or "").split())
        for word in ("gzip", "member", "bzip2", "xz", "zstd", "refused", "nested", "not opened"):
            assert word in flat, (where, word)
    inner = _tar([("usr/lib/libx.so", make_elf([NOP] * 9 + [CASB, RET], []))], gz=False)
    col = _scan_blob(_tar([("opt/inner.tar", inner), ("opt/inner.tar.gz", gzip.compress(inner, mtime=0))]))
    assert col.objects == [] and col.errors == []                     # as they say: a tar inside a layer is not opened


def test_the_command_line_reports_a_file_that_is_neither_elf_nor_tar_as_an_error(tmp_path, capsys):
    p = tmp_path / "notes.txt"
    p.write_bytes(b"neither an ELF nor a tar\n" * 40)
    elf = tmp_path / "libx.so"
    elf.write_bytes(make_elf([NOP] * 9 + [LDRB_W16, cbz(16, 3), CASAL, RET, LDXR, STLXR, RET], []))
    assert a64.main([str(p), str(elf)]) == 1
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
    assert [(r["path"], r["verdict"]) for r in lines] == [(str(p), "ERROR"), (str(elf), "clean")]
    assert "neither an ELF nor a readable tar" in lines[0]["why"][0]
    assert a64.main([str(elf)]) == 0


def test_a_saved_image_refuses_a_wrong_config_digest_a_tampered_layer_and_a_missing_manifest(tmp_path):
    path, iid, cd = make_saved_image(tmp_path, _layers())
    with pytest.raises(a64.ScanError, match="config digest"):
        a64.scan_saved_image(str(path), iid, "sha256:" + "0" * 64)
    with pytest.raises(a64.ScanError, match="no blob"):
        a64.scan_saved_image(str(path), "sha256:" + "1" * 64, cd)
    path2, iid2, cd2 = make_saved_image(tmp_path, _layers(), tamper=1)
    with pytest.raises(a64.ScanError, match="hashes to"):
        a64.scan_saved_image(str(path2), iid2, cd2)


def test_an_index_digest_is_not_an_image_manifest():
    index = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": []}).encode()
    with pytest.raises(a64.ScanError, match="single-platform"):
        a64.manifest_of(index, _digest(index))
    with pytest.raises(a64.ScanError, match="does not hash"):
        a64.manifest_of(index, "sha256:" + "2" * 64)


def test_the_index_entry_for_linux_arm64_is_found_and_attestations_are_not():
    index = {"manifests": [{"digest": "sha256:a", "platform": {"os": "linux", "architecture": "amd64"}},
                           {"digest": "sha256:b", "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
                           {"digest": "sha256:c", "platform": {"os": "unknown", "architecture": "unknown"}}]}
    assert a64.platform_entry(index) == "sha256:b" and a64.platform_entry(index, arch="riscv64") is None
    assert a64.registry_of("docker.io/library/python") == ("registry-1.docker.io", "library/python")
    assert a64.registry_of("ghcr.io/eclipse-kuksa/kuksa-databroker") == ("ghcr.io", "eclipse-kuksa/kuksa-databroker")


# ============================================================ the locks

PIN = re.compile(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", re.M)
LOCK_DIRS = {"bridge": BRIDGE_DIR, "app": APP_DIR, "recorder": RECORDER_DIR, "sim": SIM_DIR}
NATIVE = {"bridge": {"bitstruct", "grpcio", "grpcio-tools", "protobuf", "wcwidth", "websockets", "wrapt"},
          "app": {"grpcio", "grpcio-tools", "protobuf", "wcwidth", "websockets"},
          "recorder": {"grpcio", "grpcio-tools", "protobuf", "wcwidth", "websockets"},
          "sim": {"bitstruct", "wrapt"}}
COUNTS = {"bridge": 25, "app": 17, "recorder": 17, "sim": 9}


def lock_pins(path: Path) -> List[Tuple[str, str, str, str]]:
    text = path.read_text(encoding="ascii")
    pins = PIN.findall(text)
    assert len(pins) == len(re.findall(r"^[a-z0-9-]+==", text, re.M)), path
    return pins


def _dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


@pytest.mark.parametrize("which", sorted(LOCK_DIRS))
def test_each_aarch64_lock_is_its_x86_64_twin_with_the_native_wheels_swapped(which):
    x86 = lock_pins(LOCK_DIRS[which] / "requirements.lock")
    arm = lock_pins(LOCK_DIRS[which] / "requirements.aarch64.lock")
    assert len(arm) == COUNTS[which] and [(n, v) for n, v, _h, _w in arm] == [(n, v) for n, v, _h, _w in x86]
    native = set()
    for (name, ver, h, whl), (_n, _v, xh, xwhl) in zip(arm, x86):
        assert whl.startswith("%s-%s-" % (_dist(name), ver)), whl
        if xwhl.endswith("-py3-none-any.whl"):
            assert (whl, h) == (xwhl, xh), name                  # the same file, the same hash
            continue
        native.add(name)
        m = re.fullmatch(r"[a-z0-9_]+-[^-]+-(cp312-cp312|cp310-abi3)-(\S+)\.whl", whl)
        assert m, whl
        plats = m.group(2).split(".")
        assert all(p.startswith("manylinux") and p.endswith("_aarch64") for p in plats), whl
        assert h != xh, name                                      # never the x86_64 wheel's hash
    assert native == NATIVE[which]


@pytest.mark.parametrize("which", sorted(LOCK_DIRS))
def test_each_aarch64_lock_header_names_its_platform_its_install_and_its_resolution(which):
    text = (LOCK_DIRS[which] / "requirements.aarch64.lock").read_text(encoding="ascii")
    head = " ".join(ln.lstrip("# ") for ln in text.split("\n") if ln.startswith("#"))
    assert head.startswith("requirements.aarch64.lock -- ") and ("Project-written" in head or which == "sim")
    assert "CPython 3.12, Linux aarch64" in head and "Resolved 2026-10-02" in head and "manylinux2014_aarch64" in head
    assert "--require-hashes --no-deps" in head and "x86_64" not in head


# ============================================================ build_image.py and build_local_arm64 against a fake docker

FAKE_DOCKER = r'''#!%(python)s
import hashlib, json, os, sys
argv = sys.argv[1:]
state_path = os.environ["FAKE_DOCKER_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"tags": {}, "n": 0}
rec = {"argv": argv}
code = 0
out = ""
if argv[:1] == ["build"] or argv[:2] == ["buildx", "build"]:
    ctx = argv[-1]
    rec["context"] = sorted(os.listdir(ctx))
    rec["lock_sha256"] = hashlib.sha256(open(os.path.join(ctx, "requirements.lock"), "rb").read()).hexdigest()
    tag = argv[argv.index("-t") + 1]
    state["n"] += 1
    if os.environ.get("FAKE_BUILD_NO_TAG") != tag:   # otherwise exit 0 all the same: a --load that loaded nothing
        state["tags"][tag] = "sha256:" + hashlib.sha256(("%%s %%d" %% (tag, state["n"])).encode()).hexdigest()
        out = state["tags"][tag]
elif argv[:2] == ["image", "inspect"]:
    ref = argv[-1]
    iid = state["tags"].get(ref) or (ref if ref in state["tags"].values() else None)
    fmt = argv[argv.index("--format") + 1] if "--format" in argv else (argv[argv.index("-f") + 1] if "-f" in argv else None)
    if iid is None:
        code = 1
    elif fmt == "{{.Id}}":
        out = iid
    elif fmt == "{{json .RepoTags}}":
        out = json.dumps([t for t, i in state["tags"].items() if i == iid])
    else:
        out = json.dumps([{"Id": iid}])
elif argv[:1] == ["run"]:
    env = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    cpu = [e.split("=", 1)[1] for e in env if e.startswith("QEMU_CPU=")]
    if os.environ.get("FAKE_QEMU_IGNORED") == "1":
        cpu = ["max"]
    hwcap = 0xFFF if cpu == ["max"] else 0xFFF & ~(1 << 8)
    ref = argv[argv.index("--entrypoint") + 2] if "--entrypoint" in argv else ""
    if os.environ.get("FAKE_IMAGE_ATOMICS") == "1" and ref.startswith("sha256:"):
        hwcap = 0xFFF                                 # an image (run by ID, not the canary's base) reads atomics as set
    if any("getauxval" in a for a in argv):
        out = "aarch64 %%d" %% hwcap
    elif argv[-1] == "check":
        out = os.environ.get("FAKE_CHECK_JSON") or json.dumps({"python": "3.12.14"})
    code = int(os.environ.get("FAKE_RUN_EXIT", "0")) if not any("getauxval" in a for a in argv) else 0
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\n")
json.dump(state, open(state_path, "w"))
if out:
    print(out)
sys.exit(code)
'''


def bridge_check() -> Dict[str, Any]:
    """The bridge image's `check` line (sdv/bridge/bridge_sources.py check: its keys and nesting), reporting the
    contract and the DBC that images.json's bridge labels name."""
    lab = IMAGES["bridge"]["labels"]
    return {"python": "3.12.14", "modules": {"kuksa-client": "0.6.0"},
            "contract": {"digest": lab["sdv.kind4.catalog_digest"], "sha256": lab["sdv.kind4.contract_sha256"], "slot_paths": []},
            "dbc": {"path": "/app/sdv/vss/slice.dbc", "sha256": lab["sdv.kind4.dbc_sha256"], "frame_ids": []},
            "writeback_paths": []}


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "docker"
    exe.write_text(FAKE_DOCKER % {"python": sys.executable}, encoding="utf-8")
    exe.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "docker-state.json"))
    monkeypatch.setenv("FAKE_CHECK_JSON", json.dumps(bridge_check()))     # the pinned generation, as the real image reports it

    def calls() -> List[Dict[str, Any]]:
        return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return calls


LABEL_IDS = {"catalog_digest": "0x12345678", "contract_sha256": "c" * 64, "dbc_sha256": "d" * 64}


@pytest.fixture
def bridge_inputs(tmp_path, monkeypatch):
    """build_image.build without a generation: fixed labels and a two-file staging."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print('a')\n", encoding="utf-8")
    (src / "slice.dbc").write_text("VERSION \"\"\n", encoding="utf-8")
    monkeypatch.setattr(build_image, "check_inputs", lambda gen: dict(LABEL_IDS))
    monkeypatch.setattr(build_image, "staged", lambda gen: {"sdv/bridge/a.py": src / "a.py", "sdv/vss/slice.dbc": src / "slice.dbc"})
    monkeypatch.setattr(build_image, "CACHE", tmp_path / "cache")
    return tmp_path


def _builds(calls):
    return [c for c in calls() if c["argv"][:1] == ["build"] or c["argv"][:2] == ["buildx", "build"]]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@POSIX
def test_build_image_without_arch_sends_todays_argv_word_for_word(fake_docker, bridge_inputs):
    rec = build_image.build(bridge_inputs, smoke=False)
    (b,) = _builds(fake_docker)
    ctx = b["argv"][-1]
    assert b["argv"] == ["build", "-q", "--provenance=false", "--sbom=false",
                         "--build-arg", "SDV_CATALOG_DIGEST=0x12345678",
                         "--build-arg", "SDV_CONTRACT_SHA256=" + "c" * 64,
                         "--build-arg", "SDV_DBC_SHA256=" + "d" * 64,
                         "-f", ctx + "/Dockerfile", "-t", "sdv-local/vss-claim-bridge:0.1.0", ctx]
    assert b["lock_sha256"] == _sha(BRIDGE_DIR / "requirements.lock")
    assert rec["tag"] == "sdv-local/vss-claim-bridge:0.1.0" and rec["lock_sha256"] == _sha(BRIDGE_DIR / "requirements.lock")
    assert "arch" not in rec and rec["build"].startswith("docker build -q --provenance=false --sbom=false --build-arg ")


@POSIX
def test_build_image_arm64_sends_buildx_for_linux_arm64_with_the_staged_aarch64_lock_and_its_own_tag(fake_docker, bridge_inputs):
    rec = build_image.build(bridge_inputs, smoke=False, arch="arm64")
    (b,) = _builds(fake_docker)
    ctx = b["argv"][-1]
    assert b["argv"] == ["buildx", "build", "-q", "--platform", "linux/arm64", "--provenance=false", "--sbom=false", "--load",
                         "--build-arg", "SDV_CATALOG_DIGEST=0x12345678",
                         "--build-arg", "SDV_CONTRACT_SHA256=" + "c" * 64,
                         "--build-arg", "SDV_DBC_SHA256=" + "d" * 64,
                         "-f", ctx + "/Dockerfile", "-t", "sdv-local/vss-claim-bridge:0.1.0-arm64", ctx]
    assert b["lock_sha256"] == _sha(BRIDGE_DIR / "requirements.aarch64.lock") != _sha(BRIDGE_DIR / "requirements.lock")
    assert sorted(b["context"]) == ["Dockerfile", "app", "requirements.lock"]
    assert rec["tag"] == build_image.TAG + "-arm64" and rec["arch"] == "arm64"
    assert rec["lock"] == "sdv/bridge/requirements.aarch64.lock" and rec["lock_sha256"] == b["lock_sha256"]
    assert SHA.fullmatch(rec["image_id"])


@POSIX
def test_build_image_refuses_an_unknown_arch_and_leaves_the_emulated_smoke_to_arm64_py(fake_docker, bridge_inputs, capsys):
    assert build_image.main(["--arch", "arm64", "--smoke", "--gen", str(bridge_inputs)]) == 2
    assert "arm64.py smoke" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build_image.main(["--arch", "riscv64"])
    assert _builds(fake_docker) == []


@POSIX
def test_build_local_arm64_stages_both_contexts_with_their_aarch64_locks(fake_docker, tmp_path, monkeypatch):
    rec_src = tmp_path / "recorder-src"
    rec_src.mkdir()
    (rec_src / "recorder.py").write_text("print('recorder')\n", encoding="utf-8")
    monkeypatch.setattr(stack, "fetch_recorder_source", lambda images: rec_src)
    monkeypatch.setattr(stack, "CACHE", tmp_path / "cache")
    out = stack.build_local_arm64(IMAGES)
    builds = _builds(fake_docker)
    assert [c["argv"][:8] for c in builds] == [["buildx", "build", "-q", "--platform", "linux/arm64", "--provenance=false",
                                                "--sbom=false", "--load"]] * 2
    by_tag = {c["argv"][c["argv"].index("-t") + 1]: c for c in builds}
    app = by_tag["sdv-local/hard-brake-hazard:1.0.0-arm64"]
    rec = by_tag["sdv-local/kuksa-csv-provider-recorder:0.4.6-30a92880-arm64"]
    assert app["argv"][app["argv"].index("-f") + 1] == str(REPO / "sdv/apps/hard-brake-hazard/Dockerfile")
    assert rec["argv"][rec["argv"].index("-f") + 1] == str(REPO / "sdv/stack/recorder/Dockerfile")
    assert app["context"] == ["app.py", "appstate.schema.json", "hazard.py", "requirements.lock"]
    assert rec["context"] == ["recorder.py", "requirements.lock"]
    assert app["lock_sha256"] == _sha(APP_DIR / "requirements.aarch64.lock")
    assert rec["lock_sha256"] == _sha(RECORDER_DIR / "requirements.aarch64.lock")
    assert not any(c["argv"][:1] == ["pull"] for c in fake_docker())
    assert out["hard-brake-hazard"]["lock"] == "sdv/apps/hard-brake-hazard/requirements.aarch64.lock"
    assert out["kuksa-csv-provider-recorder"]["lock"] == "sdv/stack/recorder/requirements.aarch64.lock"
    assert all(SHA.fullmatch(v["image_id"]) and v["platform"] == "linux/arm64" for v in out.values())
    assert not list((tmp_path / "cache" / "arm64-build").iterdir())       # the staged contexts are removed


@POSIX
def test_a_build_that_exits_0_but_leaves_no_tag_is_the_same_error_on_both_paths_and_the_clis_error_line(
        fake_docker, bridge_inputs, monkeypatch, capsys):
    rec_src = bridge_inputs / "recorder-src"
    rec_src.mkdir()
    (rec_src / "recorder.py").write_text("print('recorder')\n", encoding="utf-8")
    monkeypatch.setattr(stack, "fetch_recorder_source", lambda images: rec_src)
    monkeypatch.setattr(stack, "CACHE", bridge_inputs / "stack-cache")
    state = bridge_inputs / "docker-state.json"
    app_tag, bridge_tag = stack.arm64_tag(IMAGES["local"]["hard-brake-hazard"]), build_image.TAG + "-arm64"
    monkeypatch.setenv("FAKE_BUILD_NO_TAG", app_tag)
    with pytest.raises(stack.StackError, match="^the build left no image tagged %s$" % re.escape(app_tag)):
        stack.build_local_arm64(IMAGES)
    assert not list((bridge_inputs / "stack-cache" / "arm64-build").iterdir())      # its staged context removed all the same
    monkeypatch.setenv("FAKE_BUILD_NO_TAG", bridge_tag)                # build_image.build's own error, the model
    with pytest.raises(build_image.BuildError, match="^the build left no image tagged %s$" % re.escape(bridge_tag)):
        build_image.build(bridge_inputs, smoke=False, arch="arm64")
    # arm64.py build: the bridge first (build_image.build), then the app and the recorder (stack.build_local_arm64)
    for tag, kind, n_builds in ((bridge_tag, "BuildError", 1), (app_tag, "StackError", 2)):
        state.unlink(missing_ok=True)                                 # no tag left over from an earlier build
        before = len(_builds(fake_docker))
        monkeypatch.setenv("FAKE_BUILD_NO_TAG", tag)
        assert arm64.main(["build", "--gen", str(bridge_inputs)]) == 1
        assert capsys.readouterr().err == "arm64: %s: the build left no image tagged %s\n" % (kind, tag)
        assert len(_builds(fake_docker)) - before == n_builds         # it stops at the build that left no tag
    assert not any(c["argv"][:1] == ["save"] for c in fake_docker())  # no pin was read back


def test_the_app_context_stages_exactly_what_its_dockerfile_copies():
    text = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")
    copies = [ln.split()[1:-1] for ln in text.splitlines() if ln.startswith("COPY ") and ln.rstrip().endswith("/app/")]
    assert copies == [list(stack.ARM64_APP_FILES)]


# ============================================================ arm64.py: the canary, the smoke, the gate

HW_A72 = 0xFFF & ~(1 << 8)
HW_MAX = 0xFFF


def _canary(a72: int, mx: int, machine: str = "aarch64") -> Dict[str, Any]:
    return {"cortex-a72": {"exit": 0, "machine": machine, "hwcap": a72}, "max": {"exit": 0, "machine": machine, "hwcap": mx}}


def test_the_canary_wants_atomics_clear_under_cortex_a72_and_set_under_max():
    assert arm64.HWCAP_ATOMICS == 1 << 8 and arm64.AT_HWCAP == 16
    assert arm64.canary_verdict(_canary(HW_A72, HW_MAX)) == []
    assert arm64.canary_verdict(_canary(HW_MAX, HW_MAX))              # QEMU_CPU never reached qemu
    assert arm64.canary_verdict(_canary(HW_A72, HW_A72))              # max without atomics: not the emulator we think
    assert arm64.canary_verdict(_canary(HW_MAX, HW_A72))              # inverted
    assert arm64.canary_verdict(_canary(HW_A72, HW_MAX, machine="x86_64"))
    bad_exit = _canary(HW_A72, HW_MAX)
    bad_exit["max"]["exit"] = 125
    assert arm64.canary_verdict(bad_exit)
    assert arm64.canary_verdict({"cortex-a72": _canary(HW_A72, HW_MAX)["cortex-a72"]})


def test_the_canary_output_is_parsed_strictly():
    assert arm64.parse_canary("aarch64 %d\n" % HW_A72) == ("aarch64", HW_A72)
    assert arm64.parse_canary("warning\naarch64 4095") == ("aarch64", 4095)
    assert arm64.parse_canary("") == (None, None) and arm64.parse_canary("aarch64 x") == (None, None)


PINS = {"hard-brake-hazard": {"id": "sha256:" + "a1" * 32, "config_digest": "sha256:" + "a2" * 32, "tag": "t1-arm64", "lock": "l1"},
        "kuksa-csv-provider-recorder": {"id": "sha256:" + "b1" * 32, "config_digest": "sha256:" + "b2" * 32, "tag": "t2-arm64",
                                        "lock": "l2"},
        "bridge": {"id": "sha256:" + "c1" * 32, "config_digest": "sha256:" + "c2" * 32, "tag": "t3-arm64", "lock": "l3"}}


@POSIX
def test_the_canary_runs_first_and_every_smoke_carries_qemu_cpu_cortex_a72(fake_docker, monkeypatch):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    rec = arm64.smoke(IMAGES)
    runs = [c["argv"] for c in fake_docker() if c["argv"][:1] == ["run"]]
    assert rec["ok"] and rec["canary_problems"] == []
    assert [("-e", "QEMU_CPU=cortex-a72") in zip(r, r[1:]) for r in runs].count(False) == 1     # only the canary's max run
    assert any("getauxval" in a for a in runs[0]) and any("getauxval" in a for a in runs[1])
    base = IMAGES["base"]["python"]
    assert runs[0][runs[0].index("--entrypoint") + 2] == "%s@%s" % (base["repo"], base["index_digest"])
    for r in runs:
        assert r[:5] == ["run", "--rm", "--network", "none", "--platform"] and r[5] == "linux/arm64"
    smoked = [r for r in runs[2:] if not any("getauxval" in a for a in r)]
    assert len(smoked) == 3 and any(r[-1] == "check" and "--read-only" in r for r in smoked)
    imports = [r for r in smoked if r[-1] != "check"]
    assert all(r[-1] == arm64.IMPORT_PROBE for r in imports) and len(imports) == 2
    assert set(rec["images"]) == set(PINS) and all(v["ok"] for v in rec["images"].values())


@POSIX
def test_a_canary_that_fails_runs_no_image_smoke(fake_docker, monkeypatch):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    monkeypatch.setenv("FAKE_QEMU_IGNORED", "1")
    rec = arm64.smoke(IMAGES)
    runs = [c["argv"] for c in fake_docker() if c["argv"][:1] == ["run"]]
    assert not rec["ok"] and rec["canary_problems"] and len(runs) == 2 and rec["images"] == {}


@POSIX
def test_an_image_smoke_killed_by_sigill_fails(fake_docker, monkeypatch):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    monkeypatch.setenv("FAKE_RUN_EXIT", "132")
    rec = arm64.smoke(IMAGES)
    assert not rec["ok"] and all(not v["ok"] and v["exit"] == 132 for v in rec["images"].values())


@POSIX
def test_an_image_smoke_passes_on_exit_0_only(fake_docker, monkeypatch):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    monkeypatch.setenv("FAKE_RUN_EXIT", "1")          # an import error: below 128, not SIGILL, still a failure
    rec = arm64.smoke(IMAGES)
    assert rec["canary_problems"] == [] and not rec["ok"] and len(rec["images"]) == 3
    assert all(not v["ok"] and v["exit"] == 1 and not v["sigill"] and v["hwcap_ok"] for v in rec["images"].values())


@POSIX
def test_an_image_that_reads_atomics_as_set_fails_its_smoke(fake_docker, monkeypatch):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    monkeypatch.setenv("FAKE_IMAGE_ATOMICS", "1")
    rec = arm64.smoke(IMAGES)
    assert rec["canary_problems"] == [] and not rec["ok"] and len(rec["images"]) == 3
    for v in rec["images"].values():
        assert v["exit"] == 0 and v["hwcap"]["atomics"] is True and not v["hwcap_ok"] and not v["ok"]


@POSIX
def test_the_bridge_smoke_fails_when_its_check_reports_another_contract_catalog_or_dbc_than_its_labels(
        fake_docker, monkeypatch, capsys):
    monkeypatch.setattr(arm64, "local_pins", lambda images: dict(PINS))
    rec = arm64.smoke(IMAGES)
    assert rec["ok"] and rec["images"]["bridge"]["label_problems"] == []
    assert rec["images"]["bridge"]["check"]["contract"]["sha256"] == IMAGES["bridge"]["labels"]["sdv.kind4.contract_sha256"]
    for part, field, other in (("contract", "sha256", "e" * 64), ("contract", "digest", "0x00000000"), ("dbc", "sha256", "f" * 64)):
        check = bridge_check()
        check[part][field] = other
        monkeypatch.setenv("FAKE_CHECK_JSON", json.dumps(check))
        rec = arm64.smoke(IMAGES)
        br = rec["images"]["bridge"]
        assert not rec["ok"] and not br["ok"] and br["exit"] == 0 and br["hwcap_ok"], (part, field)
        assert len(br["label_problems"]) == 1 and "%s.%s" % (part, field) in br["label_problems"][0], br["label_problems"]
        assert other in br["label_problems"][0], br["label_problems"]
        assert all(v["ok"] for k, v in rec["images"].items() if k != "bridge")
    check = bridge_check()
    del check["dbc"]                                                  # a check that does not report the DBC at all
    monkeypatch.setenv("FAKE_CHECK_JSON", json.dumps(check))
    rec = arm64.smoke(IMAGES)
    assert not rec["ok"] and ["dbc.sha256" in p for p in rec["images"]["bridge"]["label_problems"]] == [True]
    monkeypatch.setenv("FAKE_CHECK_JSON", json.dumps(dict(bridge_check(), dbc={"sha256": "f" * 64})))
    assert arm64.main(["smoke"]) == 1                                  # the command line fails and says why
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["images"]["bridge"]["ok"] is False and "dbc.sha256" in out["images"]["bridge"]["label_problems"][0]


class _Index:
    """A registry client whose every manifest is this index."""

    def __init__(self, index: Dict[str, Any]) -> None:
        self.raw = json.dumps(index).encode()

    def manifest(self, digest: str) -> bytes:
        return self.raw


def _index(arm64_digest: Optional[str]) -> Dict[str, Any]:
    ms = [{"digest": "sha256:" + "4" * 64, "platform": {"os": "linux", "architecture": "amd64"}},
          {"digest": "sha256:" + "7" * 64, "platform": {"os": "unknown", "architecture": "unknown"}}]
    if arm64_digest:
        ms.append({"digest": arm64_digest, "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}})
    return {"schemaVersion": 2, "manifests": ms}


def _check(listed: Optional[str], index_digest: str, pinned: str) -> Dict[str, Any]:
    client: Any = _Index(_index(listed))
    return arm64.check_index(client, index_digest, pinned)


def test_the_index_check_holds_only_when_the_index_lists_the_pinned_arm64_manifest():
    pinned, other, idx = "sha256:" + "5" * 64, "sha256:" + "6" * 64, "sha256:" + "8" * 64
    assert _check(pinned, idx, pinned) == {"index": idx, "arm64_entry": pinned, "ok": True}
    moved = _check(other, idx, pinned)
    assert moved["ok"] is False and moved["arm64_entry"] == other
    gone = _check(None, idx, pinned)
    assert gone["ok"] is False and gone["arm64_entry"] is None
    base = IMAGES["base"]["python"]                   # the base's own pins, through the same check
    assert _check(base["arm64_manifest"], base["index_digest"], base["arm64_manifest"])["ok"] is True
    assert _check(base["amd64_manifest"], base["index_digest"], base["arm64_manifest"])["ok"] is False


def _summary(objects: int, lse: int, **kw: Any) -> Dict[str, Any]:
    s = a64.summarize([])
    s.update(objects=objects, lse=lse, **kw)
    return s


def _scan_record() -> Dict[str, Any]:
    imgs: Dict[str, Any] = {}
    for name, (n, lse) in arm64.UPSTREAM_FLOOR.items():
        imgs[name] = {"summary": _summary(n, lse), "architecture": "arm64", "index_ok": True}
    for name in PINS:
        imgs[name] = {"summary": _summary(arm64.LOCAL_FLOOR_OBJECTS, 3), "architecture": "arm64", "base_layers_match": True}
    return {"images": imgs, "wheels": {w: {"summary": _summary(1, 0), "sha256_ok": True} for w in arm64.SIM_NATIVE},
            "base_index_ok": True}


def test_the_scan_gate_holds_the_floor_per_upstream_image():
    rec = _scan_record()
    assert set(arm64.UPSTREAM_FLOOR) == set(IMAGES["upstream"])
    assert arm64.UPSTREAM_FLOOR["kuksa-databroker"] == (1, 32)
    assert arm64.gate(rec, PINS) == []
    for name, (n, lse) in arm64.UPSTREAM_FLOOR.items():
        low = _scan_record()
        low["images"][name]["summary"] = _summary(n, lse - 1)
        assert any(name in w and "floor" in w for w in arm64.gate(low, PINS)), name
        few = _scan_record()
        few["images"][name]["summary"] = _summary(n - 1, lse)
        assert any(name in w and "floor" in w for w in arm64.gate(few, PINS)), name


def test_the_scan_gate_refuses_flagged_code_a_missing_image_or_wheel_and_a_failed_identity_check():
    for mutate in (lambda r: r["images"]["bridge"]["summary"].update(unguarded=1),
                   lambda r: r["images"]["kuksa-mock-provider"]["summary"].update(ldapr=2),
                   lambda r: r["images"]["hard-brake-hazard"]["summary"].update(code_read_as_none=["L0:x"]),
                   lambda r: r["wheels"]["wrapt"]["summary"].update(lor=1),
                   lambda r: r["images"].pop("kuksa-can-provider"),
                   lambda r: r["wheels"].pop("bitstruct"),
                   lambda r: r["images"]["bridge"].update(base_layers_match=False),
                   lambda r: r["images"]["kuksa-databroker"].update(index_ok=False),
                   lambda r: r["images"]["kuksa-csv-provider"].update(architecture="amd64"),
                   lambda r: r["images"]["hard-brake-hazard"]["summary"].update(objects=arm64.LOCAL_FLOOR_OBJECTS - 1),
                   lambda r: r["wheels"]["wrapt"]["summary"].update(objects=0),
                   lambda r: r["wheels"]["bitstruct"].update(sha256_ok=False),
                   lambda r: r.update(base_index_ok=False)):
        rec = _scan_record()
        mutate(rec)
        assert arm64.gate(rec, PINS), mutate


TABLE_FLAGS = [(100, SWPA), (250, LDLAR)]             # an unguarded LSE word and a LOR word inside a data table


def _with_objects(rec: Dict[str, Any], name: str, objects: List[Dict[str, Any]]) -> Dict[str, Any]:
    r = rec["images"][name]
    r["objects"] = objects
    r["summary"].update({k: sum(o[k] for o in objects) for k in a64.GATED},
                        flagged=[o["path"] for o in objects if any(o[k] for k in a64.GATED)])
    return rec


def _review(obj: Dict[str, Any], words: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    return {obj["sha256"]: {"path": obj["path"].split(":", 1)[1], "image": "kuksa-mock-provider",
                            "tables": ((TEXT_ADDR, TEXT_ADDR + 4 * 420, "a test table"),), "words": tuple(words)}}


def test_a_reviewed_object_is_excepted_for_its_own_bytes_and_exactly_its_flagged_words(monkeypatch):
    obj = _table_object(_data_table(11, TABLE_FLAGS))
    words = a64.flagged_words(obj)
    assert len(words) == 2
    rec = _with_objects(_scan_record(), "kuksa-mock-provider", [obj])
    unreviewed = arm64.gate(rec, PINS)
    assert any("unguarded" in w for w in unreviewed) and any("lor" in w for w in unreviewed)
    monkeypatch.setattr(arm64, "REVIEWED", _review(obj, words))
    assert arm64.gate(rec, PINS) == []
    s, taken, why = arm64.reviewed_split(rec["images"]["kuksa-mock-provider"], "kuksa-mock-provider")
    assert taken == [{"path": obj["path"], "sha256": obj["sha256"], "words": 2, "unguarded": 1, "ldapr": 0, "lor": 1,
                      "reason": arm64.REVIEWED_REASON, "tables": [["0x%x" % TEXT_ADDR, "0x%x" % (TEXT_ADDR + 4 * 420), "a test table"]]}]
    assert why == [] and (s["unguarded"], s["lor"], s["flagged"]) == (0, 0, [])
    # keyed by the path in the image and the image as well as the bytes: the same object elsewhere is gated
    moved = dict(obj, path="L2:usr/lib/other/libt.so")
    why = arm64.gate(_with_objects(_scan_record(), "kuksa-mock-provider", [moved]), PINS)
    assert any("unguarded" in w for w in why) and any(moved["path"] in w and "not this path" in w for w in why)
    why = arm64.gate(_with_objects(_scan_record(), "kuksa-csv-provider", [obj]), PINS)
    assert any(w.startswith("kuksa-csv-provider: ") and "unguarded" in w for w in why)
    assert any(w.startswith("kuksa-csv-provider: ") and "not this path in this image" in w for w in why)
    assert arm64.path_in_image("L12:usr/lib/x.so") == "usr/lib/x.so" and arm64.path_in_image("w.whl!a/b.so") == "w.whl!a/b.so"
    # a flagged word the review does not list: the object is not excepted, and the word is named
    monkeypatch.setattr(arm64, "REVIEWED", _review(obj, words[:1]))
    why = arm64.gate(rec, PINS)
    assert any("lor" in w for w in why) and any(words[1] in w and "not in the review" in w for w in why)
    # a reviewed word no longer flagged: a stale review fails too
    stale = "0x%x amo %08x" % (TEXT_ADDR + 4 * 300, SWPA)
    monkeypatch.setattr(arm64, "REVIEWED", _review(obj, words + [stale]))
    why = arm64.gate(rec, PINS)
    assert any(stale in w and "not flagged" in w for w in why) and any("unguarded" in w for w in why)
    # the same flagged words in other bytes: a changed object is not the reviewed one
    monkeypatch.setattr(arm64, "REVIEWED", _review(obj, words))
    table = _data_table(11, TABLE_FLAGS)
    table[399] = NOP
    changed = _table_object(table)
    assert a64.flagged_words(changed) == words and changed["sha256"] != obj["sha256"] and changed["path"] == obj["path"]
    why = arm64.gate(_with_objects(_scan_record(), "kuksa-mock-provider", [changed]), PINS)
    assert any("unguarded" in w for w in why) and any("lor" in w for w in why)
    # a reviewed object excepts itself only: another object's flagged word in the same image still fails
    other = _table_object(_data_table(12, [(50, CASB)]), path="L1:usr/lib/libu.so")
    both = _with_objects(_scan_record(), "kuksa-mock-provider", [obj, other])
    assert arm64.gate(both, PINS) == ["kuksa-mock-provider: 1 unguarded word(s)"]


def test_the_reviewed_exceptions_list_each_word_of_three_objects_inside_an_identified_table():
    rv = arm64.REVIEWED
    names = sorted(e["path"].rsplit("/", 1)[1] for e in rv.values())
    assert names == ["libcrypto.so.1.1", "libgcrypt.so.20.2.8", "libgnutls.so.30.29.1"]
    for sha, e in rv.items():
        assert re.fullmatch(r"[0-9a-f]{64}", sha) and e["image"] == "kuksa-mock-provider", sha
        assert e["path"].startswith("usr/lib/aarch64-linux-gnu/"), sha
        spans = sorted(e["tables"])
        assert spans and all(lo < hi and lo % 4 == 0 and what for lo, hi, what in spans), sha
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), sha                   # disjoint
        addrs = []
        for w in e["words"]:
            m = FLAG_WORD.fullmatch(w)
            assert m, w
            a, v = int(m.group(1), 16), int(m.group(3), 16)
            assert a % 4 == 0 and a64.classify(v) == m.group(2), w                           # the word is of its class
            assert any(lo <= a < hi for lo, hi, _what in spans), w                           # inside an identified table
            addrs.append(a)
        assert addrs == sorted(set(addrs)), sha                                              # in address order, once each
        assert all(any(lo <= a < hi for a in addrs) for lo, hi, _what in spans), sha        # no table without a word


def test_scan_and_smoke_outputs_may_not_land_in_the_repo(tmp_path):
    with pytest.raises(arm64.Arm64Error, match="inside the repo"):
        arm64.outside_repo(REPO / "sdv" / "scan.json")
    assert arm64.outside_repo(tmp_path / "scan.json") == tmp_path / "scan.json"


WHEEL = "fakepkg-1.0-cp312-cp312-manylinux2014_aarch64.whl"


def _wheel(lib: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in (("fakepkg/__init__.py", b""), ("fakepkg/_native.so", lib)):
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 2, 0, 0, 0)), data)
    return buf.getvalue()


def test_scan_wheel_offline_reads_the_locks_file_and_refuses_one_whose_sha256_differs_from_the_lock(tmp_path, monkeypatch):
    good = _wheel(make_elf([NOP] * 9 + [CASB, RET], []))
    sha = hashlib.sha256(good).hexdigest()
    lock = tmp_path / "requirements.aarch64.lock"
    lock.write_text("# a test lock\nfakepkg==1.0 \\\n    --hash=sha256:%s\n    # %s\n" % (sha, WHEEL), encoding="ascii")
    monkeypatch.setattr(arm64, "SIM_LOCK", lock)
    meta_url, file_url = "https://pypi.org/pypi/fakepkg/1.0/json", "https://files.invalid/" + WHEEL
    served = {meta_url: json.dumps({"urls": [{"filename": WHEEL, "url": file_url},
                                             {"filename": "fakepkg-1.0.tar.gz", "url": "https://files.invalid/fakepkg-1.0.tar.gz"}]}).encode(),
              file_url: good}
    opened = []

    def urlopen(url, timeout=None):
        opened.append(url)
        if url not in served:
            raise AssertionError("not offline: %s" % url)
        return io.BytesIO(served[url])
    monkeypatch.setattr(arm64.urllib.request, "urlopen", urlopen)
    r = arm64.scan_wheel("fakepkg")
    assert r["file"] == WHEEL and r["sha256"] == sha and r["sha256_ok"] is True
    assert [o["path"] for o in r["objects"]] == [WHEEL + "!fakepkg/_native.so"] and r["summary"]["unguarded"] == 1
    served[file_url] = _wheel(make_elf([NOP] * 9 + [RET], []))         # another wheel under the lock's name, a clean one
    with pytest.raises(arm64.Arm64Error, match="%s hashes to [0-9a-f]{64}, the lock says %s$" % (re.escape(WHEEL), sha)):
        arm64.scan_wheel("fakepkg")
    assert opened == [meta_url, file_url] * 2


# ============================================================ images.json

PIN_KEYS = {"id", "config_digest", "tag", "lock"}
LABELS = ("sdv.kind4.catalog_digest", "sdv.kind4.contract_sha256", "sdv.kind4.dbc_sha256")


def arm64_pins() -> Dict[str, Dict[str, str]]:
    out = {name: spec["arm64"] for name, spec in IMAGES["local"].items()}
    out["bridge"] = IMAGES["bridge"]["arm64"]
    return out


def test_the_base_pins_its_arm64_manifest():
    base = IMAGES["base"]["python"]
    assert SHA.fullmatch(base["arm64_manifest"]) and base["arm64_manifest"] not in (base["amd64_manifest"], base["index_digest"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", base["arm64_read"]) and base["arm64_read"] >= base["read"]


def test_every_arm64_pin_is_an_id_a_config_digest_a_tag_and_a_lock():
    pins = arm64_pins()
    assert set(pins) == {"hard-brake-hazard", "kuksa-csv-provider-recorder", "bridge"}
    assert "bridge" not in IMAGES["local"]          # build_local builds every local entry
    for name, pin in pins.items():
        assert set(pin) == PIN_KEYS, name
        assert SHA.fullmatch(pin["id"]) and SHA.fullmatch(pin["config_digest"]), name
        assert pin["tag"].endswith("-arm64") and (REPO / pin["lock"]).is_file(), name
        assert pin["lock"].endswith("requirements.aarch64.lock"), name
    for name, spec in IMAGES["local"].items():
        assert spec["arm64"]["tag"] == spec["tag"] + "-arm64" == stack.arm64_tag(spec), name
        assert spec["arm64"]["lock"] == stack.arm64_lock(spec), name
    assert pins["bridge"]["tag"] == build_image.TAG + "-arm64" and pins["bridge"]["lock"] == "sdv/bridge/requirements.aarch64.lock"
    ids = [p["id"] for p in pins.values()] + [p["config_digest"] for p in pins.values()]
    assert len(set(ids)) == 6
    assert arm64.local_pins(IMAGES) == pins


def test_the_bridge_entry_carries_the_three_labels_it_was_built_with():
    labels = IMAGES["bridge"]["labels"]
    assert tuple(sorted(labels)) == LABELS
    assert re.fullmatch(r"0x[0-9A-F]{8}", labels["sdv.kind4.catalog_digest"])
    assert re.fullmatch(r"[0-9a-f]{64}", labels["sdv.kind4.contract_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", labels["sdv.kind4.dbc_sha256"])
    assert labels["sdv.kind4.dbc_sha256"] == _sha(REPO / "sdv" / "vss" / "slice.dbc")


@pytest.mark.skipif(not (GEN / "vss_contract.py").is_file(), reason="needs the generated contract in %s" % GEN)
def test_the_bridge_pin_binds_the_current_generation():
    ids = build_image.check_inputs(GEN)
    assert {arm64.LABEL_OF[k]: v for k, v in ids.items()} == IMAGES["bridge"]["labels"]


def _docker_ok() -> bool:
    if shutil.which("docker") is None or os.name != "posix":
        return False
    try:
        for pin in arm64_pins().values():
            p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", pin["id"]], capture_output=True, text=True,
                               timeout=60)
            if p.returncode != 0:
                return False
    except (OSError, subprocess.TimeoutExpired, KeyError):
        return False
    return True


NEEDS_PINNED_IMAGES = pytest.mark.skipif(not _docker_ok(), reason="needs Docker with the pinned arm64 images present")


@NEEDS_PINNED_IMAGES
@pytest.mark.parametrize("name", ["hard-brake-hazard", "kuksa-csv-provider-recorder", "bridge"])
def test_each_arm64_pin_is_the_daemons_image(name):
    pin = arm64_pins()[name]
    man, cfg = arm64.saved_from_daemon(pin["id"], pin["config_digest"])
    assert man["config"]["digest"] == pin["config_digest"] and cfg["architecture"] == "arm64" and cfg["os"] == "linux"
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", pin["tag"]], capture_output=True, text=True, timeout=60)
    assert p.stdout.strip() == pin["id"]
    if name == "bridge":
        labels = (cfg.get("config") or {}).get("Labels") or {}
        assert {k: labels.get(k) for k in LABELS} == IMAGES["bridge"]["labels"]
