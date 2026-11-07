#!/usr/bin/env python3
"""awscan.py -- the Autoware arm64 image's static A72 scan: every aarch64 ELF in a `docker save` tar of one image, named
by its manifest digest, held to a64scan.py's rules, with the reviewed exceptions of aw-exceptions.json (sdv/arm64; SDV
Phase 8 WP6, spec-2 9.1).

Standard library only; a64scan.py is imported read only, and its reader and its rules
are used as they are. Run in WSL from the repo root, on the tar `docker save` wrote of the image pulled by its arm64
manifest digest (never by tag):

    python3 sdv/arm64/awscan.py --saved FILE --digest sha256:<64 hex> --out <outside every work tree>/aw-scan.json
                                [--exceptions FILE]          # default: sdv/arm64/aw-exceptions.json

THE IMAGE  --digest names the image's manifest. a64scan reads the blob it names from the tar's blobs/sha256/, checks
  that it hashes to the digest and is a single-platform manifest (an index's digest is refused), then the config it
  names, checked against its own digest, which must say linux/arm64. Each layer blob is checked against its digest as
  it is read (a64scan.scan_layer): a blob that does not hash to its digest fails the scan even when its tar reads
  clean. Every regular file of every layer is read, files a later layer replaces or deletes included; symbolic and
  hard links are not followed, and a tar nested in a layer is not opened (a64scan's reader, as its docstring says).

THE FINDINGS  One per file and kind, each named by its layer (its index in the manifest and its digest) and its path in
  that layer as the layer's tar names it (an entry of a PyInstaller onefile: <path>!<entry>):
    flagged            an aarch64 ELF holding an unguarded LSE word, an LDAPR or a LOR (a64scan's gated classes under
                       its guard rule), with every flagged word and, information only, where they sit (code-like or
                       data-like context)
    unread             an aarch64 ELF a64scan could not read (a cut file, a onefile archive that does not parse)
    code-read-as-none  an aarch64 ELF with an executable PT_LOAD read as 0 words
  These are a64scan.clean's reasons, file by file, and only these can be set aside by an exception. The others never
  are:
    image              the image could not be read as named (no blob under the digest, an index, a manifest, config or
                       layer that does not hash to its digest, a manifest or config of another shape, a config that is
                       not linux/arm64, a layer whose tar does not read), or it holds no aarch64 ELF at all: a scan
                       that reads no code cannot pass
    exception          an exception that sets nothing aside (THE EXCEPTIONS)
    exceptions-file    the exceptions file could not be read; the image is then not read at all
  The post-v8.0 information classes (SHA512, SHA3, dot product, RDM) are counted per file in elf_files and are never a
  finding, as a64scan counts them; an ELF that is not 64-bit little-endian aarch64 is listed there, never scanned.

THE EXCEPTIONS  aw-exceptions.json: {"format": 1, "about": <optional text>, "exceptions": [entry, ...]}, each entry
  exactly {"layer_digest": "sha256:<64 hex>", "path", "reason", "reviewer"}, every string non-empty, no two entries for
  one layer digest and path; anything else refuses the file. An entry sets aside every finding (flagged, unread,
  code-read-as-none) of the file at its path in the layer its digest names, and in no other layer: a layer digest names
  the layer's bytes, so an entry holds for exactly the bytes reviewed. Once the image has been read whole, an entry
  that sets nothing aside is refused, as a finding of kind exception: it names no layer of the image, no aarch64 ELF at
  that path in that layer, or a file with no finding. With an image finding no entry is applied or refused: the files
  listed may then hold bytes no digest vouches for (a layer is read before its hash check ends).

THE RECORD  aw-scan.json, {"format": 1, "image_digest", "elf_files", "findings", "exceptions_applied", "verdict"}:
  image_digest is --digest; elf_files every ELF read, in layer order, each with its layer, layer_digest, path and
  `scanned` (an aarch64 ELF with its sha256, size and counts; any other with its class, encoding and machine); findings
  each {kind, layer, layer_digest, path, why, detail, excepted}; exceptions_applied each entry that set something
  aside, with the kinds it set aside; verdict "pass" only when every finding is set aside by an exception, else "fail".
  --out must be named aw-scan.json and lie outside the repo and outside every git work tree (no directory from it up
  to the root holds a .git, file or directory). Every run that gets past its argument checks first removes an earlier
  record at --out, then writes its own whole (a temporary file beside it, renamed over it): a failed rerun never leaves
  an earlier pass behind, and one that does not finish (a crash, an interrupt) leaves no record at all. A finding's why
  names a file the host could not open (the saved tar, the exceptions file) by its own name, never with the host's
  directories. Exit 0 on pass, 1 on fail, 2 when refused before anything is read (nothing is written or removed then).

Does not demonstrate: that an image that passes runs on an A72, a c7g.metal host or the Orin (the sessions decide); the
post-v8.0 classes a64scan does not classify (FP16 arithmetic, SVE, non-hint PAC, JSCVT, LDAPUR); that the information
classes are dispatched by HWCAP; that a guarded word's flag is HWCAP_ATOMICS; code generated or loaded at run time, or
inside Python bytecode, zip files (wheels, eggs), static archives or tars nested in a layer; code in the other ELFs
listed; that an ELF's section headers tell the truth; that control never reaches the bytes an exception sets aside (its
reason says what was checked); that the image a session pulls is the one scanned (the harness compares the digests);
any timing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_WRITE_BYTECODE = sys.dont_write_bytecode
sys.dont_write_bytecode = True                           # no sdv/arm64/__pycache__ from importing a64scan; the flag is put back
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import a64scan as a64  # noqa: E402

sys.dont_write_bytecode = _WRITE_BYTECODE

EXCEPTIONS_FILE = HERE / "aw-exceptions.json"
OUT_NAME = "aw-scan.json"
FORMAT = 1
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ENTRY_KEYS = ("layer_digest", "path", "reason", "reviewer")
FILE_KEYS = ("format", "about", "exceptions")             # "about" optional
EXCEPTABLE = ("flagged", "unread", "code-read-as-none")
KINDS = ("image",) + EXCEPTABLE + ("exception", "exceptions-file")
# What an aarch64 ELF's entry in elf_files carries from a64scan's record of it.
SCANNED_KEYS = ("sha256", "bytes", "source", "exec_words", "exec_load_words", "llsc", "lse", "guarded", "unguarded", "ldapr",
                "lor", "info")
# What can stop the image's read: a64scan's read errors, and a manifest or config without the fields it should have or of
# another shape (a list or null where an object should be, a number where a digest should be).
IMAGE_ERRORS = a64.READ_ERRORS + (KeyError, TypeError, AttributeError, struct.error)
LAYER_PREFIX = re.compile(r"L(\d+):(.*)\Z", re.S)        # a64scan's path of an object read from layer n
OPEN_LINES = 40                                          # open findings printed; aw-scan.json lists them all


class AwScanError(RuntimeError):
    pass


class _Collector(a64.Collector):
    """a64scan's Collector, which also notes the path each unread object's error is about: the innermost blob() call
    it came from (a onefile entry's own path, not its archive's)."""

    def __init__(self) -> None:
        super().__init__()
        self.error_paths: Dict[int, str] = {}

    def blob(self, path: str, data: bytes, depth: int = 0) -> None:
        n = len(self.errors)
        super().blob(path, data, depth)
        for i in range(n, len(self.errors)):
            self.error_paths.setdefault(i, path)


def _finding(kind: str, layer: Optional[int], layer_digest: Optional[str], path: Optional[str], why: str,
             detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"kind": kind, "layer": layer, "layer_digest": layer_digest, "path": path, "why": why, "detail": detail or {},
            "excepted": False}


def _say(exc: BaseException) -> str:
    """'<type>: <text>' of an error; an OSError's files by their own names only, so a record names no directory of the host."""
    if isinstance(exc, OSError) and exc.strerror:
        names = [os.path.basename(os.fsdecode(n)) for n in (exc.filename, exc.filename2) if isinstance(n, (str, bytes, os.PathLike))]
        return "%s: %s" % (type(exc).__name__, ": ".join([exc.strerror] + names))
    return "%s: %s" % (type(exc).__name__, exc)


def _where(path: str, layers: Sequence[str]) -> Tuple[Optional[int], Optional[str], str]:
    """(layer index, layer digest, path in the layer) of a64scan's `L<n>:<path>`."""
    m = LAYER_PREFIX.match(path)
    if m is None or int(m.group(1)) >= len(layers):
        return None, None, path
    return int(m.group(1)), layers[int(m.group(1))], m.group(2)


# --- the exceptions --------------------------------------------------------------------------------

def load_exceptions(path: Path) -> List[Dict[str, str]]:
    """The entries of an exceptions file (THE EXCEPTIONS); AwScanError says what is wrong with one that is refused."""
    name = Path(path).name
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AwScanError("%s: not a readable JSON file: %s" % (name, _say(exc))) from exc
    if not isinstance(doc, dict) or not {"format", "exceptions"} <= set(doc) <= set(FILE_KEYS):
        raise AwScanError("%s: not an object of format and exceptions, with an optional about" % name)
    if type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise AwScanError("%s: format %r, this tool reads format %d" % (name, doc["format"], FORMAT))
    if not isinstance(doc.get("about", ""), str):
        raise AwScanError("%s: about is not a string" % name)
    entries = doc["exceptions"]
    if not isinstance(entries, list):
        raise AwScanError("%s: exceptions is not a list" % name)
    seen = set()
    out: List[Dict[str, str]] = []
    for n, e in enumerate(entries):
        if not isinstance(e, dict) or set(e) != set(ENTRY_KEYS):
            raise AwScanError("%s: entry %d is not exactly %s" % (name, n, ", ".join(ENTRY_KEYS)))
        bad = [k for k in ENTRY_KEYS if not isinstance(e[k], str) or not e[k].strip()]
        if bad:
            raise AwScanError("%s: entry %d: %s empty or not a string" % (name, n, ", ".join(bad)))
        if not DIGEST.fullmatch(e["layer_digest"]):
            raise AwScanError("%s: entry %d: layer_digest %r is not sha256:<64 hex>" % (name, n, e["layer_digest"]))
        key = (e["layer_digest"], e["path"])
        if key in seen:
            raise AwScanError("%s: entry %d names layer %s and path %s a second time" % (name, n, key[0], key[1]))
        seen.add(key)
        out.append({k: e[k] for k in ENTRY_KEYS})
    return out


def _unused(e: Dict[str, str], layers: Sequence[str], files: Sequence[Dict[str, Any]]) -> str:
    """Why an exception that set nothing aside is refused."""
    if e["layer_digest"] not in layers:
        return "it names no layer of this image"
    if not any(f["scanned"] and f["layer_digest"] == e["layer_digest"] and f["path"] == e["path"] for f in files):
        return "it names no aarch64 ELF at that path in that layer"
    return "that file has no finding: the exception sets nothing aside"


# --- the scan --------------------------------------------------------------------------------------

def scan(saved: Path, digest: str, exceptions: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """The record (THE RECORD) of the image a saved tar holds under a manifest digest, with the exceptions applied."""
    col = _Collector()
    layers: List[str] = []
    image: List[Dict[str, Any]] = []
    at: Optional[int] = None
    try:
        with tarfile.open(str(saved), mode="r:") as tf:
            man, cfg = a64.saved_image(lambda d: a64._member(tf, d).read(), digest)
            layers = [lay["digest"] for lay in man["layers"]]
            plat = "%s/%s" % (cfg.get("os"), cfg.get("architecture"))
            if plat != "linux/arm64":
                raise a64.ScanError("the config says %s, not linux/arm64" % plat)
            for at, layer in enumerate(layers):
                a64.scan_layer(a64._member(tf, layer), layer, col, "L%d:" % at)
            at = None
    except IMAGE_ERRORS as exc:
        image.append(_finding("image", at, None if at is None else layers[at], None, _say(exc)))
    files: List[Dict[str, Any]] = []
    found: List[Dict[str, Any]] = []
    for o in col.objects:
        i, d, p = _where(o["path"], layers)
        entry: Dict[str, Any] = {"layer": i, "layer_digest": d, "path": p, "scanned": True}
        entry.update({k: o[k] for k in SCANNED_KEYS})
        files.append(entry)
        gated = ["%d %s word(s)" % (o[k], k) for k in a64.GATED if o[k]]
        if gated:
            detail: Dict[str, Any] = {"sha256": o["sha256"], "words": a64.flagged_words(o)}
            detail.update({k: o[k] for k in a64.GATED})
            detail["context"] = {"code_like": o["flagged_code_like"], "data_like": o["flagged_data_like"],
                                 "min_share": o["flagged_min_share"]}
            found.append(_finding("flagged", i, d, p, ", ".join(gated), detail))
        if o["exec_load"] and not o["exec_words"]:
            found.append(_finding("code-read-as-none", i, d, p, "an executable PT_LOAD read as 0 words",
                                  {"sha256": o["sha256"], "source": o["source"], "exec_load_words": o["exec_load_words"]}))
    for o in col.other_elf:
        i, d, p = _where(o["path"], layers)
        files.append({"layer": i, "layer_digest": d, "path": p, "scanned": False, "ei_class": o["ei_class"], "ei_data": o["ei_data"],
                      "e_machine": o["e_machine"]})
    for n, err in enumerate(col.errors):
        where = col.error_paths.get(n, "")
        i, d, p = _where(where, layers) if where else (None, None, "")
        found.append(_finding("unread", i, d, p or None, err[len(where) + 2:] if where and err.startswith(where + ": ") else err))
    files.sort(key=lambda f: (-1 if f["layer"] is None else f["layer"], f["path"]))
    found.sort(key=lambda f: (-1 if f["layer"] is None else f["layer"], f["path"] or "", KINDS.index(f["kind"])))
    if not image and not col.objects:
        image.append(_finding("image", None, None, None, "no aarch64 ELF in the image: a scan that reads no code cannot pass"))
    findings = image + found
    applied: List[Dict[str, Any]] = []
    for e in exceptions:                                 # only on an image read whole: with an image finding none applies
        hit = [] if image else [f for f in findings if f["kind"] in EXCEPTABLE
                                and f["path"] == e["path"] and f["layer_digest"] == e["layer_digest"]]
        for f in hit:
            f["excepted"] = True
        if hit:
            done: Dict[str, Any] = dict(e)
            done["kinds"] = sorted({f["kind"] for f in hit}, key=KINDS.index)
            applied.append(done)
        elif not image:
            findings.append(_finding("exception", None, e["layer_digest"], e["path"], _unused(e, layers, files), {"entry": dict(e)}))
    open_ = [f for f in findings if not f["excepted"]]
    return {"format": FORMAT, "image_digest": digest, "elf_files": files, "findings": findings, "exceptions_applied": applied,
            "verdict": "fail" if open_ else "pass"}


def refused_record(digest: str, why: str) -> Dict[str, Any]:
    """The record of a run whose exceptions file was refused: the image is not read."""
    return {"format": FORMAT, "image_digest": digest, "elf_files": [], "findings": [_finding("exceptions-file", None, None, None, why)],
            "exceptions_applied": [], "verdict": "fail"}


# --- the record ------------------------------------------------------------------------------------

def output_path(out: str) -> Path:
    """--out, refused (AwScanError) unless it is named aw-scan.json and lies outside the repo and every git work tree."""
    p = Path(out).expanduser()
    if p.name != OUT_NAME:
        raise AwScanError("the record is named %s, not %s" % (OUT_NAME, p.name))
    r, repo = p.resolve(), REPO.resolve()
    if r == repo or repo in r.parents:
        raise AwScanError("%s is inside the repo: aw-scan.json is written outside every work tree" % p)
    for d in r.parents:
        if (d / ".git").exists():
            raise AwScanError("%s is inside the git work tree %s: aw-scan.json is written outside every work tree" % (p, d))
    return p


def write_record(out: Path, rec: Dict[str, Any]) -> None:
    """The record, whole: written beside its place, then renamed over it (LF only on every host)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    part.write_bytes((json.dumps(rec, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(str(part), str(out))


def report(rec: Dict[str, Any]) -> None:
    files, findings = rec["elf_files"], rec["findings"]
    scanned = sum(1 for f in files if f["scanned"])
    still = [f for f in findings if not f["excepted"]]
    print("awscan: %s: %d aarch64 ELF file(s) scanned, %d other ELF file(s) listed; %d finding(s), %d set aside by an exception"
          % (rec["image_digest"], scanned, len(files) - scanned, len(findings), len(findings) - len(still)))
    for f in still[:OPEN_LINES]:
        print("awscan: open: %s %s %s: %s" % (f["kind"], f["layer_digest"] or "-", f["path"] or "-", f["why"]))
    if len(still) > OPEN_LINES:
        print("awscan: and %d more open finding(s): aw-scan.json lists them all" % (len(still) - OPEN_LINES))
    print("awscan: verdict %s" % rec["verdict"])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--saved", required=True, help="the `docker save` tar of the image (its blobs/sha256/ layout)")
    ap.add_argument("--digest", required=True, help="the image's manifest digest, sha256:<64 hex>: the digest it was pulled by")
    ap.add_argument("--out", required=True, help="aw-scan.json, outside the repo and every git work tree")
    ap.add_argument("--exceptions", default=str(EXCEPTIONS_FILE), help="the reviewed exceptions (default: sdv/arm64/aw-exceptions.json)")
    a = ap.parse_args(argv)
    try:
        out = output_path(a.out)
        if not DIGEST.fullmatch(a.digest):
            raise AwScanError("--digest %r is not sha256:<64 hex>" % a.digest)
    except AwScanError as exc:
        print("awscan: refused: %s" % exc, file=sys.stderr)
        return 2
    if out.is_file() or out.is_symlink():
        out.unlink()                                     # no earlier record outlives a run: one that does not finish leaves none
    try:
        exceptions = load_exceptions(Path(a.exceptions))
    except AwScanError as exc:
        rec = refused_record(a.digest, str(exc))
    else:
        rec = scan(Path(a.saved), a.digest, exceptions)
    write_record(out, rec)
    report(rec)
    return 0 if rec["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
