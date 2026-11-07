"""The Autoware arm64 image's static A72 scan (SDV Phase 8 WP6, spec-2 9.1): sdv/arm64/awscan.py, its
reviewed exceptions sdv/arm64/aw-exceptions.json and its record aw-scan.json, on synthetic `docker save` OCI layouts
built here as tests/test_sdv_arm64.py builds them. awscan is imported by a fixture, so each test is red on its own
before the module exists.

What is tested, and how:

- A clean image (a guarded outline-atomics helper, a non-ELF file, an x86-64 ELF, a symbolic and a hard link) passes:
  the record holds exactly format 1, image_digest (the digest given), elf_files (each aarch64 ELF with its layer, layer
  digest, path, sha256 and counts; the x86-64 one listed, not scanned; neither link), findings [], exceptions_applied
  [] and verdict pass. Links are not followed: a symbolic, an absolute and a hard link to a flagged ELF add no file and
  no finding, so the exception for the ELF itself is enough.
- A flagged ELF (an unguarded CAS, an LDAPR, an LDLAR; each of the three alone is enough) is a finding of kind flagged
  with every flagged word as a64scan.flagged_words gives it, and fails the scan without an exception; an exception
  naming its layer digest and path sets it aside, is listed under exceptions_applied with its reason, its reviewer and
  the kinds it set aside, and the scan passes. An entry of a PyInstaller onefile in a layer is named <path>!<entry>, and
  so is its exception; an entry a64scan cannot read is an unread finding under that name, not under its archive's.
- An exception holds for its own layer only: the same bytes at the same path in a second layer stay gated. An
  exception naming a layer the image lacks, a path that is no aarch64 ELF in the layer, or a file with no finding sets
  nothing aside and is refused: a finding of kind exception, so the scan fails. A layer listed twice is read twice, one
  exception covers both. An entry holds for its exact path: not for a onefile entry under that path, not for a path it
  prefixes.
- An aarch64 ELF that cannot be read (its executable segment cut by the end of the file) and one whose executable
  PT_LOAD reads as 0 words are findings (unread, code-read-as-none), each set aside only by its own exception. One with
  no executable PT_LOAD is listed and is no finding.
- The image: a layer one byte of whose file data was flipped (its tar still reads clean) fails, the layer named; so do
  a digest that names no blob, an index's digest, a config that is not linux/arm64, a zstd layer, an image with no
  aarch64 ELF, a saved file that is not a tar and one that is not there, and a manifest or config of another shape (a
  list, null, no config digest, a layer digest that is a number), each an image finding written over an earlier pass.
  No exception sets an image finding aside, and with one no entry is applied or refused, not even for a layer that was
  read whole. A layer read uncompressed, as gzip of one or two members, bzip2 or xz scans the same.
- The exceptions file: the shipped one is format 1 with no entry and LF only; an entry with a missing or extra field,
  an empty or non-string reason, reviewer or path, a layer digest that is not sha256:<64 hex> (a tail is not), two
  entries for one layer and path (one path in two layers is two entries), another format, an extra top-level key, no
  exceptions key, entries that are not a list, an about that is not a string, a bare list, or a file that is not JSON is
  refused; on the command line that is a fail record before the image is read.
- The command line: exit 0 on pass and 1 on fail, each writing aw-scan.json whole (LF only, nothing left beside it), a
  failed rerun over an earlier pass included; a run that does not finish leaves no record, not an earlier one; a missing
  saved tar or exceptions file is named in the record by its own name, never with the host's directories; 2, with
  nothing written, for a digest that is not sha256:<64 hex> (a tail is not) and for an output not named aw-scan.json,
  inside the repo, or inside any git work tree (a .git directory, or a linked worktree's .git file, right above it or
  far above it, or a link into one). Without --exceptions the shipped file is read.
- Importing awscan leaves sys.dont_write_bytecode as it found it, and a64scan is imported without writing bytecode.
- The findings agree with a64scan.clean's rule over the same saved images: none exactly when clean() finds nothing,
  and the flagged counts are a64scan's.

What this does NOT show: the scan of the real Autoware arm64 image (it waits for the owner's yes to the pull and is the
orchestrator's run); that an image that passes runs on an A72, a c7g.metal host or the Orin (A1 and G1 decide); what
tests/test_sdv_arm64.py shows of a64scan's classifier, guard and reader, which this file relies on; any timing.
"""
import bz2
import gzip
import hashlib
import importlib
import io
import json
import lzma
import os
import struct
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ARM_DIR = REPO / "sdv" / "arm64"
EXCEPTIONS_FILE = ARM_DIR / "aw-exceptions.json"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(ARM_DIR) not in sys.path:
    sys.path.insert(0, str(ARM_DIR))
import a64scan as a64  # noqa: E402

sys.dont_write_bytecode = _saved

RECORD_KEYS = {"format", "image_digest", "elf_files", "findings", "exceptions_applied", "verdict"}
FINDING_KEYS = {"kind", "layer", "layer_digest", "path", "why", "detail", "excepted"}


@pytest.fixture(scope="module")
def aw() -> Any:
    """sdv/arm64/awscan.py, imported here so that each test is red on its own before the module exists."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module("awscan")
    finally:
        sys.dont_write_bytecode = saved


# ============================================================ synthetic ELFs, layers and saved images

NOP, RET = 0xD503201F, 0xD65F03C0
LDRB_W16 = 0x39400210      # ldrb w16, [x16]
CASAL, CASB = 0xC8E0FC41, 0x08A07C41
LDXR, STLXR = 0xC85F7C20, 0xC802FC20
LDAPR, LDLAR = 0xF8BFC020, 0xC8DF7C20
TEXT_ADDR = 0x10000


def cbz(reg: int, delta: int) -> int:
    """CBZ w<reg>, <delta words> (32-bit form)."""
    return 0x34000000 | ((delta & 0x7FFFF) << 5) | reg


GUARDED_HELPER = [NOP] * 9 + [LDRB_W16, cbz(16, 3), CASAL, RET, LDXR, STLXR, RET]   # the outline-atomics shape: guarded
FLAGGED_CODE = [NOP] * 9 + [CASB, RET, LDAPR, LDLAR, RET]                             # an unguarded CAS, an LDAPR, a LOR


def make_elf(text_words: List[int], sections: bool = True, machine: int = 183) -> bytes:
    """A 64-bit little-endian ELF: one R-X PT_LOAD holding the words, a .text section over it when `sections`."""
    text = b"".join(struct.pack("<I", w) for w in text_words)
    phoff, text_off = 64, 0x100
    shstr = b"\0.text\0.shstrtab\0"
    shstr_off = text_off + len(text)
    shoff = shstr_off + len(shstr) + (-(shstr_off + len(shstr))) % 8
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    hdr = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, machine, 1, TEXT_ADDR, phoff, shoff if sections else 0, 0, 64, 56, 1,
                      64, 3 if sections else 0, 2 if sections else 0)
    ph = struct.pack("<IIQQQQQQ", 1, 5, text_off, TEXT_ADDR, TEXT_ADDR, len(text), len(text), 0x1000)
    body = bytearray(hdr + ph)
    body += b"\0" * (text_off - len(body)) + text + shstr
    if sections:
        body += b"\0" * (shoff - len(body))
        body += b"\0" * 64
        body += struct.pack("<IIQQQQIIQQ", 1, 1, 0x6, TEXT_ADDR, text_off, len(text), 0, 0, 4, 0)
        body += struct.pack("<IIQQQQIIQQ", 7, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    return bytes(body)


def make_carchive(bootloader: bytes, entries: List[Tuple[str, str, bytes]]) -> bytes:
    """A PyInstaller onefile: the bootloader, the entries' data (compressed), the TOC and the 88-byte cookie."""
    data, toc = b"", b""
    for name, typ, blob in entries:
        stored = zlib.compress(blob)
        nm = name.encode() + b"\0"
        nm += b"\0" * ((-(18 + len(nm))) % 16)
        toc += struct.pack("!IIIIBc", 18 + len(nm), len(data), len(stored), len(blob), 1, typ.encode()) + nm
        data += stored
    cookie = struct.pack("!8sIIII64s", a64.PYI_MAGIC, len(data) + len(toc) + 88, len(data), len(toc), 312, b"libpython3.12.so.1.0")
    return bootloader + data + toc + cookie


def _tar(members: Sequence[Tuple[str, bytes]], links: Sequence[Tuple[str, str, bool]] = (), gz: bool = False) -> bytes:
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


def make_saved(tmp: Path, layers: List[bytes], arch: str = "arm64", os_: str = "linux", replace: Optional[Dict[int, bytes]] = None,
               extra: Sequence[bytes] = (), name: str = "saved.tar") -> Tuple[Path, str, List[str]]:
    """A `docker save` OCI layout of one image: (its path, the manifest digest, the layer digests). `replace` puts other
    bytes under a layer's digest (a tampered blob); `extra` adds blobs (an index)."""
    cfg = json.dumps({"architecture": arch, "os": os_, "rootfs": {"type": "layers", "diff_ids": []}}).encode()
    man = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                      "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": _digest(cfg), "size": len(cfg)},
                      "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar", "digest": _digest(lay), "size": len(lay)}
                                 for lay in layers]}).encode()
    blobs = {_digest(b): b for b in [cfg, man] + list(layers) + list(extra)}
    for i, bad in (replace or {}).items():
        blobs[_digest(layers[i])] = bad
    index = json.dumps({"schemaVersion": 2, "manifests": [{"digest": _digest(man), "size": len(man)}]}).encode()
    path = tmp / name
    path.write_bytes(_tar([("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'), ("index.json", index)]
                          + [("blobs/sha256/" + d.split(":")[1], b) for d, b in blobs.items()]))
    return path, _digest(man), [_digest(lay) for lay in layers]


def _exc(layer: str, path: str, reason: str = "a reason", reviewer: str = "a reviewer") -> Dict[str, str]:
    return {"layer_digest": layer, "path": path, "reason": reason, "reviewer": reviewer}


def _clean_layers() -> List[bytes]:
    lay0 = _tar([("usr/lib/libclean.so", make_elf(GUARDED_HELPER)), ("usr/bin/tool-x86", make_elf([NOP], machine=62)),
                 ("etc/conf", b"k=v\n")],
                [("usr/lib/libclean.so.1", "libclean.so", False), ("usr/lib/libclean-hard.so", "usr/lib/libclean.so", True)], gz=True)
    lay1 = _tar([("app/bin", make_elf([NOP] * 4))])
    return [lay0, lay1]


def _flagged_layer() -> bytes:
    return _tar([("usr/lib/libf.so", make_elf(FLAGGED_CODE)), ("usr/lib/libclean.so", make_elf(GUARDED_HELPER))])


def _flagged_words(elf: bytes) -> List[str]:
    col = a64.Collector()
    col.blob("x", elf)
    (obj,) = col.objects
    return a64.flagged_words(obj)


def _cut_and_none() -> Tuple[bytes, bytes]:
    """An ELF whose executable segment is cut by the end of the file, and one whose executable PT_LOAD holds 3 bytes."""
    cut = make_elf(FLAGGED_CODE)[:0x100 + 4 * 9 + 2]
    none = bytearray(make_elf([NOP, RET], sections=False))
    struct.pack_into("<Q", none, 64 + 32, 3)                  # p_filesz of the one PT_LOAD: no whole word in the file
    return cut, bytes(none)


def _empty_exceptions(tmp: Path) -> Path:
    p = tmp / "exceptions" / "aw-exceptions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"format": 1, "exceptions": []}), encoding="utf-8")
    return p


# ============================================================ the record and the rule

def test_a_clean_image_passes_and_its_record_holds_exactly_the_six_keys(aw, tmp_path):
    path, digest, layers = make_saved(tmp_path, _clean_layers())
    rec = aw.scan(path, digest, [])
    assert set(rec) == RECORD_KEYS and rec["format"] == 1 and rec["image_digest"] == digest
    assert rec["findings"] == [] and rec["exceptions_applied"] == [] and rec["verdict"] == "pass"
    files = [(f["layer"], f["layer_digest"], f["path"], f["scanned"]) for f in rec["elf_files"]]
    assert files == [(0, layers[0], "usr/bin/tool-x86", False), (0, layers[0], "usr/lib/libclean.so", True), (1, layers[1], "app/bin", True)]
    x86, lib, app = rec["elf_files"]
    assert (x86["ei_class"], x86["ei_data"], x86["e_machine"]) == (2, 1, 62) and "lse" not in x86
    elf = make_elf(GUARDED_HELPER)
    assert lib["sha256"] == hashlib.sha256(elf).hexdigest() and lib["bytes"] == len(elf)
    assert (lib["exec_words"], lib["lse"], lib["guarded"], lib["unguarded"], lib["ldapr"], lib["lor"]) == (len(GUARDED_HELPER), 1, 1, 0, 0, 0)
    assert lib["source"] == "sections" and set(lib["info"]) == set(a64.INFO)
    assert app["exec_words"] == 4 and app["lse"] == 0
    assert json.loads(json.dumps(rec)) == rec


def test_links_are_not_followed_so_a_link_to_a_flagged_elf_adds_no_file_and_no_finding(aw, tmp_path):
    links = [("usr/lib/libf.so.1", "libf.so", False), ("opt/abs.so", "/usr/lib/libf.so", False), ("usr/lib/libf-hard.so", "usr/lib/libf.so", True)]
    lay = _tar([("usr/lib/libf.so", make_elf(FLAGGED_CODE))], links, gz=True)
    path, digest, layers = make_saved(tmp_path, [lay])
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/lib/libf.so")])
    assert [f["path"] for f in rec["elf_files"]] == ["usr/lib/libf.so"]
    assert [(f["kind"], f["path"], f["excepted"]) for f in rec["findings"]] == [("flagged", "usr/lib/libf.so", True)]
    assert rec["verdict"] == "pass"


def test_a_flagged_elf_is_a_finding_with_every_flagged_word_and_fails_without_an_exception(aw, tmp_path):
    path, digest, layers = make_saved(tmp_path, [_flagged_layer()])
    rec = aw.scan(path, digest, [])
    assert rec["verdict"] == "fail" and rec["exceptions_applied"] == []
    (f,) = rec["findings"]
    assert set(f) == FINDING_KEYS
    assert (f["kind"], f["layer"], f["layer_digest"], f["path"], f["excepted"]) == ("flagged", 0, layers[0], "usr/lib/libf.so", False)
    elf = make_elf(FLAGGED_CODE)
    words = _flagged_words(elf)
    assert len(words) == 3 and f["detail"]["words"] == words
    assert (f["detail"]["unguarded"], f["detail"]["ldapr"], f["detail"]["lor"]) == (1, 1, 1)
    assert f["detail"]["sha256"] == hashlib.sha256(elf).hexdigest()
    assert set(f["detail"]["context"]) == {"code_like", "data_like", "min_share"}
    assert "unguarded" in f["why"] and "ldapr" in f["why"] and "lor" in f["why"]


@pytest.mark.parametrize("word", ["ldapr", "lor", "cas"])
def test_each_gated_class_alone_is_a_finding_and_fails(aw, tmp_path, word):
    words = {"ldapr": [NOP] * 9 + [LDAPR, RET], "lor": [NOP] * 9 + [LDLAR, RET], "cas": [NOP] * 9 + [CASB, RET]}[word]
    path, digest, layers = make_saved(tmp_path, [_tar([("usr/lib/libw.so", make_elf(words)), ("usr/lib/libclean.so", make_elf(GUARDED_HELPER))])])
    rec = aw.scan(path, digest, [])
    assert [(f["kind"], f["path"]) for f in rec["findings"]] == [("flagged", "usr/lib/libw.so")] and rec["verdict"] == "fail"
    assert rec["findings"][0]["detail"]["unguarded" if word == "cas" else word] == 1
    assert aw.scan(path, digest, [_exc(layers[0], "usr/lib/libw.so")])["verdict"] == "pass"


def test_an_exception_naming_the_findings_layer_and_path_sets_it_aside_and_is_recorded(aw, tmp_path):
    path, digest, layers = make_saved(tmp_path, [_flagged_layer()])
    e = _exc(layers[0], "usr/lib/libf.so", reason="every flagged word lies in a constant table", reviewer="the owner")
    rec = aw.scan(path, digest, [e])
    assert [(f["kind"], f["excepted"]) for f in rec["findings"]] == [("flagged", True)]
    assert rec["exceptions_applied"] == [dict(e, kinds=["flagged"])]
    assert rec["verdict"] == "pass"


def test_an_exception_holds_for_its_own_layer_only_and_one_that_sets_nothing_aside_is_refused(aw, tmp_path):
    flagged = make_elf(FLAGGED_CODE)
    lay0 = _tar([("usr/lib/libf.so", flagged), ("usr/lib/libclean.so", make_elf(GUARDED_HELPER))])
    lay1 = _tar([("usr/lib/libf.so", flagged), ("etc/other", b"x\n")])     # the same bytes at the same path, another layer
    path, digest, layers = make_saved(tmp_path, [lay0, lay1])
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/lib/libf.so")])
    assert [(f["kind"], f["layer_digest"], f["excepted"]) for f in rec["findings"]] == [("flagged", layers[0], True), ("flagged", layers[1], False)]
    assert rec["verdict"] == "fail" and [e["layer_digest"] for e in rec["exceptions_applied"]] == [layers[0]]
    both = [_exc(layers[0], "usr/lib/libf.so"), _exc(layers[1], "usr/lib/libf.so")]
    rec = aw.scan(path, digest, both)
    assert rec["verdict"] == "pass" and [e["layer_digest"] for e in rec["exceptions_applied"]] == layers
    for e, why in ((_exc("sha256:" + "ab" * 32, "usr/lib/libf.so"), "names no layer of this image"),
                   (_exc(layers[0], "usr/lib/libg.so"), "no aarch64 ELF at that path"),
                   (_exc(layers[1], "etc/other"), "no aarch64 ELF at that path"),
                   (_exc(layers[0], "usr/lib/libclean.so"), "no finding")):
        rec = aw.scan(path, digest, both + [e])
        refused = [f for f in rec["findings"] if f["kind"] == "exception"]
        assert rec["verdict"] == "fail" and len(refused) == 1, e
        assert (refused[0]["layer_digest"], refused[0]["path"], refused[0]["excepted"]) == (e["layer_digest"], e["path"], False)
        assert why in refused[0]["why"] and refused[0]["detail"]["entry"] == e
        assert len(rec["exceptions_applied"]) == 2 and all(f["excepted"] for f in rec["findings"] if f["kind"] == "flagged")


def test_a_layer_the_manifest_lists_twice_is_read_twice_and_one_exception_covers_both(aw, tmp_path):
    lay = _flagged_layer()
    path, digest, layers = make_saved(tmp_path, [lay, lay])
    assert layers[0] == layers[1]
    rec = aw.scan(path, digest, [])
    assert [(f["kind"], f["layer"], f["path"]) for f in rec["findings"]] == [("flagged", 0, "usr/lib/libf.so"), ("flagged", 1, "usr/lib/libf.so")]
    assert rec["verdict"] == "fail"
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/lib/libf.so")])
    assert rec["verdict"] == "pass" and rec["exceptions_applied"] == [dict(_exc(layers[0], "usr/lib/libf.so"), kinds=["flagged"])]


def test_an_unreadable_elf_and_one_whose_code_reads_as_no_words_are_findings_each_set_aside_by_its_own_exception(aw, tmp_path):
    cut, none = _cut_and_none()
    with pytest.raises(a64.ScanError, match="past the end of the file"):
        a64.scan_elf(cut)
    assert a64.scan_elf(none)["exec_load"] and a64.scan_elf(none)["exec_words"] == 0
    path, digest, layers = make_saved(tmp_path, [_tar([("usr/lib/cut.so", cut), ("usr/lib/none.so", none)])])
    rec = aw.scan(path, digest, [])
    assert [(f["kind"], f["path"], f["excepted"]) for f in rec["findings"]] == [("unread", "usr/lib/cut.so", False),
                                                                               ("code-read-as-none", "usr/lib/none.so", False)]
    assert "past the end of the file" in rec["findings"][0]["why"] and rec["verdict"] == "fail"
    assert [f["path"] for f in rec["elf_files"]] == ["usr/lib/none.so"]               # an unread file was not scanned
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/lib/cut.so")])
    assert [f["excepted"] for f in rec["findings"]] == [True, False] and rec["verdict"] == "fail"
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/lib/cut.so"), _exc(layers[0], "usr/lib/none.so")])
    assert rec["verdict"] == "pass" and [e["kinds"] for e in rec["exceptions_applied"]] == [["unread"], ["code-read-as-none"]]


def test_an_aarch64_elf_without_an_executable_segment_is_listed_and_is_no_finding(aw, tmp_path):
    data = bytearray(make_elf([NOP, RET], sections=False))
    struct.pack_into("<I", data, 64 + 4, 4)                   # p_flags of the one PT_LOAD: R, not X
    path, digest, _layers = make_saved(tmp_path, [_tar([("usr/lib/data.so", bytes(data)), ("usr/lib/libclean.so", make_elf(GUARDED_HELPER))])])
    rec = aw.scan(path, digest, [])
    assert rec["findings"] == [] and rec["verdict"] == "pass"
    assert [(f["path"], f["exec_words"]) for f in rec["elf_files"]] == [("usr/lib/data.so", 0), ("usr/lib/libclean.so", len(GUARDED_HELPER))]


def test_an_entry_of_a_onefile_archive_is_named_path_bang_entry_and_so_is_its_exception(aw, tmp_path):
    cut, _none = _cut_and_none()
    exe = make_carchive(make_elf(GUARDED_HELPER), [("libfoo.so", "b", make_elf(FLAGGED_CODE))])
    exe2 = make_carchive(make_elf(GUARDED_HELPER), [("libcut.so", "b", cut)])          # an entry a64scan cannot read
    path, digest, layers = make_saved(tmp_path, [_tar([("usr/bin/app", exe), ("usr/bin/app2", exe2)])])
    rec = aw.scan(path, digest, [])
    assert [f["path"] for f in rec["elf_files"]] == ["usr/bin/app", "usr/bin/app!libfoo.so", "usr/bin/app2"]
    assert [(f["kind"], f["path"]) for f in rec["findings"]] == [("flagged", "usr/bin/app!libfoo.so"), ("unread", "usr/bin/app2!libcut.so")]
    assert rec["findings"][1]["why"].startswith("executable PT_LOAD") and "past the end of the file" in rec["findings"][1]["why"]
    assert rec["verdict"] == "fail"
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/bin/app!libfoo.so"), _exc(layers[0], "usr/bin/app2!libcut.so")])
    assert rec["verdict"] == "pass"


def test_an_exception_holds_for_its_own_path_only_and_not_for_a_path_it_prefixes(aw, tmp_path):
    exe = make_carchive(make_elf(GUARDED_HELPER), [("libfoo.so", "b", make_elf(FLAGGED_CODE))])
    lay = _tar([("usr/bin/app", exe), ("usr/lib/libf.so", make_elf(FLAGGED_CODE)), ("usr/lib/libf.so.1.2", make_elf(FLAGGED_CODE))])
    path, digest, layers = make_saved(tmp_path, [lay])
    rec = aw.scan(path, digest, [_exc(layers[0], "usr/bin/app"), _exc(layers[0], "usr/lib/libf.so")])
    assert [(f["kind"], f["path"], f["excepted"]) for f in rec["findings"]] == [
        ("flagged", "usr/bin/app!libfoo.so", False), ("flagged", "usr/lib/libf.so", True), ("flagged", "usr/lib/libf.so.1.2", False),
        ("exception", "usr/bin/app", False)]
    assert "no finding" in rec["findings"][-1]["why"]
    assert rec["verdict"] == "fail" and [e["path"] for e in rec["exceptions_applied"]] == ["usr/lib/libf.so"]


def test_an_exception_names_one_path_exactly_neither_a_suffix_nor_an_archive_holding_it(aw, tmp_path):
    exe = make_carchive(make_elf(GUARDED_HELPER), [("libfoo.so", "b", make_elf(FLAGGED_CODE))])
    path, digest, layers = make_saved(tmp_path, [_tar([("usr/lib/libf.so", make_elf(FLAGGED_CODE)), ("usr/bin/app", exe)])])
    for near in ("libf.so", "lib/libf.so", "usr/lib/libf", "usr/bin/app", "libfoo.so"):
        rec = aw.scan(path, digest, [_exc(layers[0], near)])
        assert [f["excepted"] for f in rec["findings"] if f["kind"] == "flagged"] == [False, False], near
        assert [f["path"] for f in rec["findings"] if f["kind"] == "exception"] == [near] and rec["verdict"] == "fail", near


# ============================================================ the image

def test_a_layer_whose_bytes_are_not_its_digests_fails_even_when_its_tar_reads_clean(aw, tmp_path):
    lay0 = _tar([("usr/lib/libclean.so", make_elf(GUARDED_HELPER))], gz=True)
    lay1 = _tar([("etc/conf", b"k=v\n"), ("app/bin", make_elf([NOP] * 4))])
    bad = bytearray(lay1)
    bad[512] ^= 0x01                                          # the first byte of etc/conf's data
    col = a64.Collector()
    col.tar(io.BytesIO(bytes(bad)), "x:")
    assert col.errors == [] and [o["path"] for o in col.objects] == ["x:app/bin"] and a64.clean(col.summary()) == []
    path, digest, layers = make_saved(tmp_path, [lay0, lay1], replace={1: bytes(bad)})
    for exceptions in ([], [_exc(layers[1], "app/bin")]):
        rec = aw.scan(path, digest, exceptions)
        assert rec["verdict"] == "fail" and rec["image_digest"] == digest
        (f,) = [f for f in rec["findings"] if not f["excepted"]]
        assert (f["kind"], f["layer"], f["layer_digest"], f["path"]) == ("image", 1, layers[1], None)
        assert "hashes to" in f["why"]


def test_with_an_image_finding_no_exception_is_applied_or_refused(aw, tmp_path):
    lay1 = _tar([("usr/lib/libg.so", make_elf(FLAGGED_CODE))])
    other = _tar([("usr/lib/libg.so", make_elf(FLAGGED_CODE)), ("etc/other", b"x\n")])   # reads clean, under lay1's digest
    path, digest, layers = make_saved(tmp_path, [_flagged_layer(), lay1], replace={1: other})
    entries = [_exc(layers[0], "usr/lib/libf.so"), _exc(layers[1], "usr/lib/libg.so"), _exc("sha256:" + "ab" * 32, "usr/lib/libh.so")]
    rec = aw.scan(path, digest, entries)
    assert [(f["kind"], f["layer"], f["path"], f["excepted"]) for f in rec["findings"]] == [
        ("image", 1, None, False), ("flagged", 0, "usr/lib/libf.so", False), ("flagged", 1, "usr/lib/libg.so", False)]
    assert rec["exceptions_applied"] == [] and rec["verdict"] == "fail"
    whole, digest2, _ = make_saved(tmp_path, [_flagged_layer(), lay1], name="whole.tar")       # the same image, untampered
    assert digest2 == digest and aw.scan(whole, digest, entries[:2])["verdict"] == "pass"


@pytest.mark.parametrize("compress", ["none", "gzip", "gzip-two-members", "bzip2", "xz"])
def test_a_layer_compressed_as_a64scan_reads_it_scans_the_same(aw, tmp_path, compress):
    raw = _tar([("usr/lib/libf.so", make_elf(FLAGGED_CODE)), ("etc/conf", b"k=v\n")])
    blob = {"none": raw, "gzip": gzip.compress(raw, mtime=0),
            "gzip-two-members": gzip.compress(raw[:700], mtime=0) + gzip.compress(raw[700:], mtime=0),
            "bzip2": bz2.compress(raw), "xz": lzma.compress(raw)}[compress]
    path, digest, layers = make_saved(tmp_path, [blob])
    rec = aw.scan(path, digest, [])
    assert [(f["kind"], f["path"]) for f in rec["findings"]] == [("flagged", "usr/lib/libf.so")] and rec["verdict"] == "fail"
    assert aw.scan(path, digest, [_exc(layers[0], "usr/lib/libf.so")])["verdict"] == "pass"


IMAGE_CASES = {
    "another-digest": "no blob",
    "an-index": "single-platform",
    "amd64": "not linux/arm64",
    "not-linux": "not linux/arm64",
    "zstd-layer": "zstd",
    "no-aarch64-elf": "no aarch64 ELF",
    "not-a-tar": "",
    "missing": "",
}


@pytest.mark.parametrize("case", sorted(IMAGE_CASES))
def test_an_image_that_cannot_be_read_as_named_fails_and_no_exception_sets_it_aside(aw, tmp_path, case):
    layers = _clean_layers()
    kw: Dict[str, Any] = {}
    if case in ("amd64", "not-linux"):
        kw = {"arch": "amd64"} if case == "amd64" else {"os_": "windows"}
    elif case == "zstd-layer":
        layers = layers + [a64.ZSTD_MAGIC + b"\0" * 64]
    elif case == "no-aarch64-elf":
        layers = [_tar([("usr/bin/tool-x86", make_elf([NOP], machine=62)), ("etc/conf", b"k=v\n")])]
    index = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": []}).encode()
    path, digest, digests = make_saved(tmp_path, layers, extra=[index], **kw)
    if case == "another-digest":
        digest = "sha256:" + "1" * 64
    elif case == "an-index":
        digest = _digest(index)
    elif case == "not-a-tar":
        path.write_bytes(b"neither a tar nor anything else\n" * 40)
    elif case == "missing":
        path = tmp_path / "absent.tar"
    rec = aw.scan(path, digest, [_exc(digests[0], "usr/lib/libclean.so")])
    assert rec["verdict"] == "fail" and rec["image_digest"] == digest
    assert [f["kind"] for f in rec["findings"] if not f["excepted"]] == ["image"]
    (f,) = [f for f in rec["findings"] if f["kind"] == "image"]
    assert IMAGE_CASES[case] in f["why"] and f["path"] is None and f["excepted"] is False


def _saved_blobs(tmp: Path, manifest: bytes, blobs: Sequence[bytes], name: str) -> Tuple[Path, str]:
    """A saved tar holding the manifest and the blobs, each under its own digest: (its path, the manifest digest)."""
    path = tmp / name
    path.write_bytes(_tar([("blobs/sha256/" + _digest(b).split(":")[1], b) for b in [manifest] + list(blobs)]))
    return path, _digest(manifest)


OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
ARM_CONFIG = json.dumps({"architecture": "arm64", "os": "linux"}).encode()
SHAPES: Dict[str, Tuple[Any, List[bytes]]] = {                # each blob hashes to its digest: only its shape is wrong
    "manifest-a-list": ([], []),
    "config-a-list": ({"mediaType": OCI_MANIFEST, "config": {"digest": _digest(b"[]")}, "layers": []}, [b"[]"]),
    "config-null": ({"mediaType": OCI_MANIFEST, "config": {"digest": _digest(b"null")}, "layers": []}, [b"null"]),
    "config-without-digest": ({"mediaType": OCI_MANIFEST, "config": {}, "layers": []}, []),
    "layer-digest-a-number": ({"mediaType": OCI_MANIFEST, "config": {"digest": _digest(ARM_CONFIG)}, "layers": [{"digest": 5}]}, [ARM_CONFIG]),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_manifest_or_config_of_another_shape_is_an_image_finding_written_over_an_earlier_pass(aw, tmp_path, shape):
    empty = _empty_exceptions(tmp_path)
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    out = tmp_path / "rec" / "aw-scan.json"
    assert aw.main(_argv(path, digest, out, empty)) == 0
    manifest, blobs = SHAPES[shape]
    odd, odd_digest = _saved_blobs(tmp_path, json.dumps(manifest).encode(), blobs, "odd.tar")
    assert aw.main(_argv(odd, odd_digest, out, empty)) == 1
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["image_digest"] == odd_digest and rec["verdict"] == "fail" and [f["kind"] for f in rec["findings"]] == ["image"]


# ============================================================ the exceptions file

def test_the_shipped_exceptions_file_is_format_1_with_no_entry_and_lf_only(aw):
    raw = EXCEPTIONS_FILE.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    doc = json.loads(raw)
    assert set(doc) == {"format", "about", "exceptions"} and doc["format"] == 1 and isinstance(doc["about"], str)
    assert doc["exceptions"] == []          # as 9.1 ships it: an entry comes only after the real scan, reviewed in notes
    assert aw.load_exceptions(EXCEPTIONS_FILE) == [] and Path(aw.EXCEPTIONS_FILE) == EXCEPTIONS_FILE


GOOD = _exc("sha256:" + "ab" * 32, "usr/lib/libf.so")
MALFORMED: Dict[str, Any] = {
    "missing-field": {"format": 1, "exceptions": [{k: v for k, v in GOOD.items() if k != "reviewer"}]},
    "extra-field": {"format": 1, "exceptions": [dict(GOOD, words=[])]},
    "empty-reason": {"format": 1, "exceptions": [dict(GOOD, reason="  ")]},
    "empty-reviewer": {"format": 1, "exceptions": [dict(GOOD, reviewer="")]},
    "empty-path": {"format": 1, "exceptions": [dict(GOOD, path="")]},
    "non-string-reason": {"format": 1, "exceptions": [dict(GOOD, reason=1)]},
    "short-digest": {"format": 1, "exceptions": [dict(GOOD, layer_digest="sha256:" + "ab" * 31)]},
    "a-tag-not-a-digest": {"format": 1, "exceptions": [dict(GOOD, layer_digest="ghcr.io/x/y:latest")]},
    "duplicate": {"format": 1, "exceptions": [GOOD, dict(GOOD, reason="another reason")]},
    "format-2": {"format": 2, "exceptions": []},
    "format-true": {"format": True, "exceptions": []},
    "extra-top-key": {"format": 1, "exceptions": [], "more": 1},
    "entries-not-a-list": {"format": 1, "exceptions": GOOD},
    "a-bare-list": [GOOD],
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_a_malformed_exceptions_file_is_refused(aw, tmp_path, case):
    p = tmp_path / "aw-exceptions.json"
    p.write_text(json.dumps(MALFORMED[case]), encoding="utf-8")
    with pytest.raises(aw.AwScanError):
        aw.load_exceptions(p)


def test_an_about_that_is_not_a_string_is_refused(aw, tmp_path):
    p = tmp_path / "aw-exceptions.json"
    p.write_text(json.dumps({"format": 1, "about": 1, "exceptions": []}), encoding="utf-8")
    with pytest.raises(aw.AwScanError, match="about"):
        aw.load_exceptions(p)


MORE_MALFORMED: Dict[str, Any] = {
    "no-exceptions-key": {"format": 1},
    "about-not-a-string": {"format": 1, "about": 5, "exceptions": []},
    "exceptions-an-object": {"format": 1, "exceptions": {}},
    "digest-with-a-tail": {"format": 1, "exceptions": [dict(GOOD, layer_digest=GOOD["layer_digest"] + "0")]},
}


@pytest.mark.parametrize("case", sorted(MORE_MALFORMED))
def test_more_malformed_exceptions_files_are_refused_and_one_path_in_two_layers_is_not(aw, tmp_path, case):
    p = tmp_path / "aw-exceptions.json"
    p.write_text(json.dumps(MORE_MALFORMED[case]), encoding="utf-8")
    with pytest.raises(aw.AwScanError):
        aw.load_exceptions(p)
    two = [GOOD, dict(GOOD, layer_digest="sha256:" + "cd" * 32)]
    p.write_text(json.dumps({"format": 1, "exceptions": two}), encoding="utf-8")
    assert aw.load_exceptions(p) == two


def test_a_well_formed_entry_loads_and_a_file_that_is_not_json_is_refused(aw, tmp_path):
    p = tmp_path / "aw-exceptions.json"
    p.write_text(json.dumps({"format": 1, "about": "x", "exceptions": [GOOD, dict(GOOD, path="usr/lib/libg.so")]}), encoding="utf-8")
    assert aw.load_exceptions(p) == [GOOD, dict(GOOD, path="usr/lib/libg.so")]
    p.write_text("{", encoding="utf-8")
    with pytest.raises(aw.AwScanError):
        aw.load_exceptions(p)
    with pytest.raises(aw.AwScanError):
        aw.load_exceptions(tmp_path / "absent.json")


def test_a_malformed_exceptions_file_on_the_command_line_is_a_fail_record_before_the_image_is_read(aw, tmp_path, capsys):
    p = tmp_path / "bad" / "aw-exceptions.json"
    p.parent.mkdir()
    p.write_text(json.dumps(MALFORMED["duplicate"]), encoding="utf-8")
    out = tmp_path / "out" / "aw-scan.json"
    digest = "sha256:" + "c" * 64
    rc = aw.main(["--saved", str(tmp_path / "absent.tar"), "--digest", digest, "--out", str(out), "--exceptions", str(p)])
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 1 and set(rec) == RECORD_KEYS and rec["verdict"] == "fail" and rec["image_digest"] == digest
    assert [f["kind"] for f in rec["findings"]] == ["exceptions-file"] and rec["elf_files"] == [] and rec["exceptions_applied"] == []
    assert "verdict fail" in capsys.readouterr().out


# ============================================================ the command line

def _argv(saved: Path, digest: str, out: Path, exceptions: Path) -> List[str]:
    return ["--saved", str(saved), "--digest", digest, "--out", str(out), "--exceptions", str(exceptions)]


def test_the_command_line_exits_0_on_pass_and_1_on_fail_and_a_failed_rerun_overwrites_an_earlier_pass(aw, tmp_path, capsys):
    empty = _empty_exceptions(tmp_path)
    lay0, lay1 = _clean_layers()
    path, digest, _layers = make_saved(tmp_path, [lay0, lay1])
    out = tmp_path / "rec" / "aw-scan.json"
    assert aw.main(_argv(path, digest, out, empty)) == 0
    raw = out.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and json.loads(raw)["verdict"] == "pass"
    assert "verdict pass" in capsys.readouterr().out
    bad = bytearray(lay1)
    bad[600] ^= 0x01                                          # app/bin's p_paddr, which the scan never reads: the tar still reads
    tampered, digest2, _ = make_saved(tmp_path, [lay0, lay1], replace={1: bytes(bad)}, name="tampered.tar")
    assert digest2 == digest
    assert aw.main(_argv(tampered, digest, out, empty)) == 1
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["verdict"] == "fail" and [f["kind"] for f in rec["findings"]] == ["image"]
    assert "verdict fail" in capsys.readouterr().out
    assert sorted(os.listdir(str(out.parent))) == ["aw-scan.json"]
    flagged, digest3, _ = make_saved(tmp_path, [_flagged_layer()], name="flagged.tar")
    assert aw.main(_argv(flagged, digest3, out, empty)) == 1 and json.loads(out.read_text(encoding="utf-8"))["image_digest"] == digest3


def test_the_command_line_reads_the_shipped_exceptions_file_when_none_is_given(aw, tmp_path, capsys):
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    out = tmp_path / "rec" / "aw-scan.json"
    assert aw.main(["--saved", str(path), "--digest", digest, "--out", str(out)]) == 0
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["verdict"] == "pass" and rec["findings"] == [] and rec["exceptions_applied"] == []
    assert "verdict pass" in capsys.readouterr().out


def test_a_run_that_does_not_finish_leaves_no_earlier_record_behind(aw, tmp_path, monkeypatch):
    empty = _empty_exceptions(tmp_path)
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    out = tmp_path / "rec" / "aw-scan.json"
    assert aw.main(_argv(path, digest, out, empty)) == 0 and out.exists()

    def interrupted(*_a: Any, **_k: Any) -> Dict[str, Any]:
        raise KeyboardInterrupt

    monkeypatch.setattr(aw, "scan", interrupted)
    with pytest.raises(KeyboardInterrupt):
        aw.main(_argv(path, digest, out, empty))
    assert os.listdir(str(out.parent)) == []


def test_a_record_names_a_missing_file_by_its_own_name_and_no_directory_of_the_host(aw, tmp_path, capsys):
    empty = _empty_exceptions(tmp_path)
    out = tmp_path / "rec" / "aw-scan.json"
    digest = "sha256:" + "c" * 64
    gone = tmp_path / "gone" / "aw-exceptions.json"
    for exceptions, kind, name in ((empty, "image", "absent.tar"), (gone, "exceptions-file", "aw-exceptions.json")):
        assert aw.main(_argv(tmp_path / "absent.tar", digest, out, exceptions)) == 1
        raw = out.read_text(encoding="utf-8")
        (f,) = json.loads(raw)["findings"]
        assert f["kind"] == kind and "FileNotFoundError" in f["why"] and f["why"].endswith(": " + name), f["why"]
        assert tmp_path.name not in raw and tmp_path.name not in capsys.readouterr().out


def test_the_record_is_refused_inside_the_repo_inside_any_work_tree_under_another_name_and_for_a_bad_digest(aw, tmp_path, capsys):
    empty = _empty_exceptions(tmp_path)
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    plain = tmp_path / "plain-repo"
    (plain / ".git").mkdir(parents=True)
    linked = tmp_path / "linked-worktree"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    refused = [REPO / "aw-scan.json", ARM_DIR / "aw-scan.json", plain / "sub" / "aw-scan.json",
               linked / "deep" / "er" / "aw-scan.json", tmp_path / "out" / "scan.json"]
    for out in refused:
        assert aw.main(_argv(path, digest, out, empty)) == 2, out
        assert not out.exists(), out
        assert out.parent in (REPO, ARM_DIR) or not out.parent.exists(), out
    err = capsys.readouterr().err
    assert "inside the repo" in err and "work tree" in err and "aw-scan.json" in err
    ok = tmp_path / "out" / "aw-scan.json"
    for bad in ("sha256:" + "1" * 63, "ghcr.io/autowarefoundation/autoware:universe-jazzy-1.9.0", digest.upper()):
        assert aw.main(_argv(path, bad, ok, empty)) == 2 and not ok.exists(), bad
    assert aw.main(_argv(path, digest, ok, empty)) == 0 and ok.exists()


def test_a_digest_with_a_tail_is_refused_on_the_command_line(aw, tmp_path):
    empty = _empty_exceptions(tmp_path)
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    out = tmp_path / "out" / "aw-scan.json"
    assert aw.main(_argv(path, digest + "0", out, empty)) == 2 and not out.exists()


def test_the_record_is_refused_right_under_a_work_tree_far_under_one_and_through_a_link_into_one(aw, tmp_path):
    empty = _empty_exceptions(tmp_path)
    path, digest, _layers = make_saved(tmp_path, _clean_layers())
    plain = tmp_path / "plain-repo"
    (plain / ".git").mkdir(parents=True)
    (plain / "sub").mkdir()
    refused = [plain / "aw-scan.json", plain / "a" / "b" / "c" / "d" / "aw-scan.json"]
    if os.name == "posix":
        (tmp_path / "link").symlink_to(plain / "sub", target_is_directory=True)
        refused.append(tmp_path / "link" / "aw-scan.json")
    for out in refused:
        assert aw.main(_argv(path, digest, out, empty)) == 2 and not out.exists(), out


# ============================================================ against a64scan's own rule

def test_the_findings_agree_with_a64scans_clean_rule_over_the_same_saved_images(aw, tmp_path):
    cut, none = _cut_and_none()
    images = {"clean": _clean_layers(), "flagged": [_flagged_layer()], "cut-and-none": [_tar([("usr/lib/cut.so", cut), ("usr/lib/none.so", none)])],
              "two-layers": [_flagged_layer(), _tar([("usr/lib/libf.so", make_elf(FLAGGED_CODE))])]}
    for name, layers in images.items():
        path, digest, _digests = make_saved(tmp_path, layers, name=name + ".tar")
        rec = aw.scan(path, digest, [])
        r = a64.scan_saved_image(str(path), digest)
        assert bool(rec["findings"]) == bool(a64.clean(r["summary"])), name
        assert (rec["verdict"] == "pass") == (a64.clean(r["summary"]) == []), name
        flagged = [f["detail"] for f in rec["findings"] if f["kind"] == "flagged"]
        for k in a64.GATED:
            assert sum(d[k] for d in flagged) == r["summary"][k], (name, k)
        scanned = ["L%d:%s" % (f["layer"], f["path"]) for f in rec["elf_files"] if f["scanned"]]
        assert sorted(scanned) == sorted(o["path"] for o in r["objects"]), name


def test_the_module_docstring_names_the_record_the_exceptions_and_what_it_does_not_show(aw):
    flat = " ".join((aw.__doc__ or "").split())
    for word in sorted(RECORD_KEYS) + ["layer_digest", "reviewer", "not followed", "hash", "outside every", "Does not demonstrate"]:
        assert word in flat, word


def test_importing_awscan_leaves_the_bytecode_flag_as_it_was_and_a64scan_without_bytecode(tmp_path):
    code = ("import sys; sys.dont_write_bytecode = False; sys.path.insert(0, %r); import awscan; "
            "print(sys.dont_write_bytecode, 'a64scan' in sys.modules)" % str(ARM_DIR))
    cache = tmp_path / "pyc"                                  # bytecode goes here, never into the tree
    p = subprocess.run([sys.executable, "-X", "pycache_prefix=" + str(cache), "-c", code], cwd=str(tmp_path),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert p.stdout.decode("utf-8").split() == ["False", "True"]
    written = sorted(f.name.split(".")[0] for f in cache.rglob("*.pyc"))
    assert "awscan" in written and "a64scan" not in written, written
