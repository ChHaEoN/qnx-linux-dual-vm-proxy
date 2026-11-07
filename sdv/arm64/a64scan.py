#!/usr/bin/env python3
"""a64scan.py -- a static scan of aarch64 ELF code for instructions an ARMv8.0-A core lacks (sdv/arm64; SDV Phase 3 WP0).

Standard library only: an encoding classifier, ELF reader, tree walker and PyInstaller extractor, with post-v8.0 counters.
There is no aarch64 disassembler: every 4-byte aligned word of an object's executable code is classified by its encoding
(ARM ARM, the A64 load/store and SIMD encodings).

    python3 sdv/arm64/a64scan.py FILE...         # one ELF, or a tar (optionally compressed) of files, per argument

WHAT IS CODE  An ELF's SHF_EXECINSTR PROGBITS sections. An ELF with no section headers, or with none executable, is read
  through its executable PT_LOAD segments instead (the program-header fallback), so a stripped object never reads as 0
  words. Each object records `exec_load` (it has an executable PT_LOAD with bytes in the file) beside its word count, so a
  caller can refuse an object that has code and was read as none, and `exec_load_words` (the words of its executable
  PT_LOADs, information: a section table that covers little of its executable segments shows there). An executable
  PT_LOAD that runs past the end of the file is an error: the file is cut, so its code cannot all be read. A PyInstaller
  onefile executable's CArchive is opened: every entry but the PYZ (bytecode) is decompressed and scanned as an object of
  its own, `<outer>!<entry>`, and an entry that is a onefile itself is opened the same way, to PYI_MAX_DEPTH archives
  deep. A cookie magic whose cookie or table of contents does not parse, or one in an object nested deeper than that, is
  an error, never a plain ELF: a format change or a damaged archive cannot hide the objects it holds.

COUNTS PER OBJECT
  llsc      LDXR/LDAXR/STXR/STLXR (Rt2 = 11111) and the pair forms   v8.0 exclusives (LL/SC)
  cas       CAS/CASA/CASL/CASAL (B/H/W/X)                    v8.1 LSE
  casp      CASP*                                            v8.1 LSE
  amo       LDADD/LDCLR/LDEOR/LDSET/LD{S,U}{MAX,MIN}/SWP     v8.1 LSE (A/L variants and the ST* aliases included)
  ldapr     LDAPR*                                           v8.3 RCpc
  lor       LDLAR/STLLR                                      v8.1 LOR
  info      sha512 (v8.2), sha3 (v8.2), dotprod (v8.2 SDOT/UDOT, vector form only, not by element), rdm (v8.1
            SQRDMLAH/SQRDMLSH, vector form only, not by element or scalar): counted, never gated (a v8.0 core lacks them;
            whether the code dispatches them by HWCAP is not traced here). The size field is not checked, so some
            counted words are unallocated encodings.
  Every flagged word (an unguarded LSE word, an LDAPR, a LOR) is also listed, uncapped, as `0x<address> <class> <word>`
  in unguarded_at, ldapr_at and lor_at; flagged_words() gives an object's whole list in address order, which is what a
  caller's reviewed exception is compared with.

GUARDED  An LSE word counts as guarded only inside the exact shape of the compiler runtimes' outline-atomics helpers:
  `ldrb w16, [x16, #imm]` two words before it (the load of the have-LSE flag), `cbz w16` one word before it branching
  exactly three words on (past the LSE word and its ret: the fallback), `ret` right after it, and an LL/SC word within
  FALLBACK_WINDOW words of that target (the fallback loop). Anything else leaves the word unguarded: another load or
  register, a CBNZ (it runs the LSE word when the flag is clear), a branch elsewhere, no ret after the word, no LL/SC at
  the target, two LSE words under one branch.

CONTEXT OF A FLAGGED WORD (information, never gated)  A classifier without a disassembler also reads constant tables
  that a library keeps in its executable section. For every flagged word (unguarded LSE, LDAPR, LOR) the share of words
  within CONTEXT_WINDOW words either side whose A64 top-level field op0 (bits 28:25) is 0000, 0001 or 0011 is computed:
  encodings that are reserved or unallocated, which a compiler or assembler never emits as instructions and which
  arbitrary data hits about 3 times in 16. A flagged word whose context share is below CODE_LIKE_MAX_SHARE counts as
  `flagged_code_like`, any other as `flagged_data_like`. The split is evidence for a reader, not a verdict: a flagged
  word counts against an object whatever its context.

OCI IMAGES  scan_layer() walks one layer blob and checks the blob's sha256 against its digest as it reads it;
  scan_saved_image() takes a `docker save` tar (its blobs/sha256/ layout), checks the manifest blob against the image ID
  and its config digest against an expected one, and walks every layer; RegistryClient fetches a manifest, a config or a
  layer by digest and checks each against its digest. A layer blob and a tar named on the command line are read alike,
  by their first bytes (decompressed()): gzip member after member to the end of its last member (multistream, as the
  container runtimes read a gzip layer), bzip2 and xz stream after stream to the end of their last stream, and an
  uncompressed tar as it is; zstd is recognised and refused (the standard library here has no zstd decoder), so a zstd
  layer is an error, never a layer read as empty. Where the tar walk stops (its end-of-archive marker, the end of the
  data, or a header it cannot read), the rest of the decompressed stream must be zeros: a layer whose tar stops before
  its data does is refused, never read in part. Every regular file of every layer is read (files a later layer deletes or
  replaces included); symbolic and hard links are not followed. A tar nested inside a layer (or inside a tar on the
  command line), compressed or not, is a regular file like any other: it is not opened, and the ELFs it holds are not
  scanned. Other ELFs (not 64-bit little-endian aarch64) are listed with their ELF class, data encoding and machine,
  never scanned.

Does not demonstrate: other post-v8.0 classes the A72 lacks, which this does not classify (FP16 arithmetic, SVE, non-hint
PAC such as RETAA, JSCVT, LDAPUR); that a guarded word's flag is HWCAP_ATOMICS (the load's shape is matched, not the
address it reads); code generated or loaded at run time; code inside zip files (wheels, eggs), static archives or tar
files nested in an image (a tar inside a layer is not opened); that the section headers tell the truth (an ELF's
executable sections are read when it has any, so headers that mark part of an executable segment's code as
non-executable hide it; exec_load_words beside exec_words shows how much of the segments the sections cover); code in
the other ELFs listed; that the counted info classes are or are not dispatched by HWCAP; anything about running the code.
"""
from __future__ import annotations

import bz2
import collections
import gzip
import hashlib
import io
import json
import lzma
import struct
import sys
import tarfile
import urllib.request
import zlib
from typing import IO, Any, Callable, Deque, Dict, Iterator, List, Optional, Sequence, Tuple, cast

ELF_MAGIC = b"\x7fELF"
EM_AARCH64 = 183
SHT_PROGBITS = 1
SHF_EXECINSTR = 0x4
PT_LOAD = 1
PF_X = 0x1
# The guard (GUARDED): the helper's words around an LSE word at i.
GUARD_LOAD = (0xFFC003FF, 0x39400210)   # word i-2: ldrb w16, [x16, #imm12] (any imm12)
GUARD_CBZ = 0x34000070                  # word i-1: cbz w16, .+12 (to i+2, past the LSE word and its ret)
RET = 0xD65F03C0                        # word i+1: ret
FALLBACK_WINDOW = 4       # words from the guard's branch target searched for the LL/SC fallback
GUARD_SHAPE = ("ldrb w16, [x16, #imm12]; cbz w16, .+12; <LSE word>; ret; an LL/SC word within %d words of the cbz's target"
               % FALLBACK_WINDOW)
PYI_MAX_DEPTH = 2         # onefile archives opened: an object's own, and one inside it
LSE = ("cas", "casp", "amo")
GATED = ("unguarded", "ldapr", "lor")
FLAGGED_LISTS = ("unguarded_at", "ldapr_at", "lor_at")
CONTEXT_WINDOW = 64       # words either side of a flagged word whose top-level encodings are counted (information)
CODE_LIKE_MAX_SHARE = 0.05  # below this share of reserved/unallocated words a flagged word's context reads as code
INFO = {
    "sha512": [(0xFFE0FC00, 0xCE608000), (0xFFE0FC00, 0xCE608400), (0xFFE0FC00, 0xCE608800), (0xFFFFFC00, 0xCEC08000)],
    "sha3": [(0xFFE08000, 0xCE000000), (0xFFE08000, 0xCE200000), (0xFFE0FC00, 0xCE608C00), (0xFFE00000, 0xCE800000)],
    "dotprod": [(0xBF20FC00, 0x0E009400), (0xBF20FC00, 0x2E009400)],
    "rdm": [(0xBF20FC00, 0x2E008400), (0xBF20FC00, 0x2E008C00)],
}
PYI_MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
PYI_COOKIE = struct.Struct("!8sIIII64s")
PYI_TOC = struct.Struct("!IIIIBc")
PYI_SKIPPED = ("z", "Z")  # PYZ archives: bytecode, no machine code
GZIP_MAGIC = b"\x1f\x8b\x08"
BZIP2_MAGIC = b"BZh"      # and "1AY&SY" at offset 4
XZ_MAGIC = b"\xfd7zXZ\x00"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class ScanError(RuntimeError):
    pass


# Exceptions a layer or a tar argument can raise while it is decompressed and walked.
READ_ERRORS = (ScanError, tarfile.TarError, EOFError, OSError, zlib.error, lzma.LZMAError, ValueError)


# --- the classifier ------------------------------------------------------------------------------

def classify(w: int) -> Optional[str]:
    """The atomics class of one A64 word, or None."""
    if (w & 0x3FA07C00) == 0x08A07C00:
        return "cas"
    if (w & 0xBFA07C00) == 0x08207C00:
        return "casp"
    if (w & 0x3FA07C00) == 0x08007C00:      # the non-pair forms: Rt2 is 11111
        return "llsc"
    if (w & 0xBFA00000) == 0x88200000:
        return "llsc"
    if (w & 0x3FA08000) == 0x08800000:
        return "lor"
    if (w & 0x3F200C00) == 0x38200000:
        if (w & 0x3FFFFC00) == 0x38BFC000:
            return "ldapr"
        return "amo"
    return None


def info_class(w: int) -> Optional[str]:
    for name, pats in INFO.items():
        if any((w & m) == v for m, v in pats):
            return name
    return None


def guard_shape(load: int, branch: int, after: int) -> bool:
    """The words two before, one before and one after an LSE word are the helper's flag load, its cbz and its ret."""
    return (load & GUARD_LOAD[0]) == GUARD_LOAD[1] and branch == GUARD_CBZ and after == RET


def _table(pred: Callable[[int], bool]) -> bytes:
    return bytes(1 if pred(b) else 0 for b in range(256))


# Byte filters (little-endian words: byte 3 holds bits 31-24). A word that could be any atomics class above passes them;
# so does any word one of the INFO patterns could match. Only those words are classified one by one.
_T3_EXCL = _table(lambda b: (b & 0x3F) == 0x08)      # cas, casp, llsc, lor
_T3_AMO = _table(lambda b: (b & 0x3F) == 0x38)       # amo, ldapr: and bit 21 set, bits 11:10 clear
_T2_BIT21 = _table(lambda b: bool(b & 0x20))
_T1_B1110_CLEAR = _table(lambda b: (b & 0x0C) == 0)
_T3_CRYPTO = _table(lambda b: b == 0xCE)             # sha512, sha3
_T3_SIMD = _table(lambda b: (b & 0xBF) in (0x0E, 0x2E))   # dotprod, rdm: and bit 21 clear, bits 15:10 as below
_T2_BIT21_CLEAR = _table(lambda b: not b & 0x20)
_T1_DOT_RDM = _table(lambda b: (b & 0xFC) in (0x84, 0x8C, 0x94))


def _mask(*parts: bytes) -> int:
    v = -1
    for p in parts:
        v &= int.from_bytes(p, "little")
    return v


def _hits(mask: int, n: int) -> Iterator[int]:
    marks = mask.to_bytes(n, "little")
    i = marks.find(1)
    while i != -1:
        yield i
        i = marks.find(1, i + 1)


def new_counts() -> Dict[str, Any]:
    return {"exec_words": 0, "llsc": 0, "cas": 0, "casp": 0, "amo": 0, "lse": 0, "guarded": 0, "unguarded": 0,
            "ldapr": 0, "lor": 0, "info": {k: 0 for k in INFO}, "unguarded_at": [], "ldapr_at": [], "lor_at": [],
            "flagged_code_like": 0, "flagged_data_like": 0, "flagged_min_share": None}


def reserved_top_level(w: int) -> bool:
    """op0 (bits 28:25) 0000, 0001 or 0011: reserved or unallocated at the A64 top level, never an emitted instruction."""
    return ((w >> 25) & 0xF) in (0b0000, 0b0001, 0b0011)


def scan_words(data: bytes, off: int, size: int, addr: int, counts: Dict[str, Any]) -> None:
    """Classify the aligned words of data[off:off+size] (loaded at addr) into counts."""
    skip = (-addr) % 4
    off, addr, size = off + skip, addr + skip, max(0, size - skip)
    n = size // 4
    if n == 0:
        return
    if off < 0 or off + 4 * n > len(data):
        raise ScanError("code range 0x%x+0x%x lies outside the file (%d bytes)" % (off, 4 * n, len(data)))
    mv = memoryview(data)[off:off + 4 * n]
    b1, b2, b3 = bytes(mv[1::4]), bytes(mv[2::4]), bytes(mv[3::4])
    counts["exec_words"] += n

    def word(k: int) -> int:
        return struct.unpack_from("<I", data, off + 4 * k)[0]

    def guarded(i: int) -> bool:
        if i < 2 or i + 2 >= n or not guard_shape(word(i - 2), word(i - 1), word(i + 1)):
            return False
        return any(classify(word(k)) == "llsc" for k in range(i + 2, min(n, i + 2 + FALLBACK_WINDOW)))

    def context(i: int) -> None:
        """Information only: how data-like the flagged word i's neighbourhood is (CONTEXT OF A FLAGGED WORD)."""
        lo, hi = max(0, i - CONTEXT_WINDOW), min(n, i + CONTEXT_WINDOW + 1)
        share = sum(reserved_top_level(word(k)) for k in range(lo, hi)) / (hi - lo)
        counts["flagged_code_like" if share < CODE_LIKE_MAX_SHARE else "flagged_data_like"] += 1
        if counts["flagged_min_share"] is None or share < counts["flagged_min_share"]:
            counts["flagged_min_share"] = round(share, 4)

    atomics = (int.from_bytes(b3.translate(_T3_EXCL), "little")
               | _mask(b3.translate(_T3_AMO), b2.translate(_T2_BIT21), b1.translate(_T1_B1110_CLEAR)))
    for i in _hits(atomics, n):
        c = classify(word(i))
        if c is None:
            continue
        counts[c] += 1
        a = addr + 4 * i
        if c in LSE:
            counts["lse"] += 1
            if guarded(i):
                counts["guarded"] += 1
            else:
                counts["unguarded"] += 1
                context(i)
                counts["unguarded_at"].append("0x%x %s %08x" % (a, c, word(i)))
        elif c in ("ldapr", "lor"):
            context(i)
            counts[c + "_at"].append("0x%x %s %08x" % (a, c, word(i)))
    ext = (int.from_bytes(b3.translate(_T3_CRYPTO), "little")
           | _mask(b3.translate(_T3_SIMD), b2.translate(_T2_BIT21_CLEAR), b1.translate(_T1_DOT_RDM)))
    for i in _hits(ext, n):
        k = info_class(word(i))
        if k is not None:
            counts["info"][k] += 1


# --- ELF -----------------------------------------------------------------------------------------

def elf_kind(data: bytes) -> Optional[str]:
    """'aarch64' for a 64-bit little-endian aarch64 ELF, 'other' for any other ELF, None for anything else."""
    if data[:4] != ELF_MAGIC:
        return None
    if len(data) < 64 or data[4] != 2 or data[5] != 1 or struct.unpack_from("<H", data, 0x12)[0] != EM_AARCH64:
        return "other"
    return "aarch64"


def elf_ident(path: str, data: bytes) -> Dict[str, Any]:
    """What an ELF that is not scanned says it is: EI_CLASS, EI_DATA and e_machine (read in its EI_DATA's byte order),
    each None where the file is too short or the byte order unknown."""
    enc = data[5] if len(data) > 5 else None
    machine = struct.unpack_from("<H" if enc == 1 else ">H", data, 0x12)[0] if enc in (1, 2) and len(data) >= 0x14 else None
    return {"path": path, "ei_class": data[4] if len(data) > 4 else None, "ei_data": enc, "e_machine": machine}


def exec_sections(data: bytes) -> List[Tuple[int, int, int]]:
    """(addr, offset, size) of every SHF_EXECINSTR PROGBITS section; [] with no section headers."""
    e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
    e_shentsize, e_shnum = struct.unpack_from("<HH", data, 0x3A)
    if e_shoff == 0:
        return []
    if e_shnum == 0:           # more than SHN_LORESERVE sections: the count is section 0's sh_size
        if e_shoff + 64 > len(data):
            raise ScanError("section header table at 0x%x lies outside the file" % e_shoff)
        e_shnum = struct.unpack_from("<Q", data, e_shoff + 0x20)[0]
    if e_shentsize < 64 or e_shoff + e_shnum * e_shentsize > len(data):
        raise ScanError("section header table (0x%x, %d x %d) lies outside the file" % (e_shoff, e_shnum, e_shentsize))
    out = []
    for i in range(e_shnum):
        _name, typ, flags, addr, off, size = struct.unpack_from("<IIQQQQ", data, e_shoff + i * e_shentsize)
        if typ == SHT_PROGBITS and flags & SHF_EXECINSTR and size:
            out.append((addr, off, size))
    return out


def exec_loads(data: bytes) -> List[Tuple[int, int, int]]:
    """(vaddr, offset, p_filesz) of every executable PT_LOAD with bytes in the file (p_filesz > 0)."""
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    if e_phoff == 0 or e_phnum == 0:
        return []
    if e_phentsize < 56 or e_phoff + e_phnum * e_phentsize > len(data):
        raise ScanError("program header table (0x%x, %d x %d) lies outside the file" % (e_phoff, e_phnum, e_phentsize))
    out = []
    for i in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, _p_paddr, p_filesz = struct.unpack_from("<IIQQQQ", data, e_phoff + i * e_phentsize)
        if p_type == PT_LOAD and p_flags & PF_X and p_filesz:
            out.append((p_vaddr, p_offset, p_filesz))
    return out


def scan_elf(data: bytes) -> Dict[str, Any]:
    """One aarch64 ELF: its counts, where its code was read from ('sections', 'segments' with the reason, or 'none'),
    whether it has an executable PT_LOAD (exec_load) and how many words those hold (exec_load_words, information). An
    executable PT_LOAD that runs past the end of the file raises ScanError (a cut file)."""
    counts = new_counts()
    loads = exec_loads(data)
    for _a, o, n in loads:
        if o + n > len(data):
            raise ScanError("executable PT_LOAD at 0x%x+0x%x runs past the end of the file (%d bytes)" % (o, n, len(data)))
    counts["exec_load"] = bool(loads)
    segments = loads
    counts["exec_load_words"] = sum(n // 4 for _a, _o, n in loads)
    why = None
    try:
        sections = exec_sections(data)
    except ScanError as exc:
        sections, why = [], "section headers unreadable (%s)" % exc
    if sum(size // 4 for _a, _o, size in sections):
        counts["source"], regions = "sections", sections
    elif segments:
        if why is None:
            why = "no section headers" if struct.unpack_from("<Q", data, 0x28)[0] == 0 else "no executable section"
        counts["source"], regions = "segments: " + why, segments
    else:
        counts["source"], regions = "none", []
    for addr, off, size in regions:
        scan_words(data, off, size, addr, counts)
    return counts


# --- PyInstaller ---------------------------------------------------------------------------------

def carchive_entries(data: bytes) -> Optional[Dict[str, Any]]:
    """A PyInstaller onefile CArchive appended to data: {'entries': [(name, typecode, bytes)], 'skipped': {type: n}},
    the PYZ entries skipped; None when data holds no cookie magic. A magic whose cookie or table of contents does not
    parse raises ScanError: the bootloader does not hold the whole magic in its own data, so a found magic is an
    archive, and one that cannot be read must not pass as a plain ELF."""
    pos = data.rfind(PYI_MAGIC)
    if pos < 0:
        return None

    def bad(why: str) -> ScanError:
        return ScanError("CArchive cookie magic at 0x%x, but the archive does not parse: %s" % (pos, why))
    if pos + PYI_COOKIE.size > len(data):
        raise bad("the cookie runs past the end of the data")
    _magic, pkg_len, toc_off, toc_len, _pyvers, _pylib = PYI_COOKIE.unpack_from(data, pos)
    start = pos + PYI_COOKIE.size - pkg_len
    if start < 0 or toc_len <= 0 or toc_off + toc_len > pkg_len:
        raise bad("package length %d, TOC at %d+%d" % (pkg_len, toc_off, toc_len))
    p, end = start + toc_off, start + toc_off + toc_len
    entries: List[Tuple[str, str, bytes]] = []
    skipped: Dict[str, int] = collections.Counter()
    while p < end:
        if p + PYI_TOC.size > end:
            raise bad("a TOC entry at 0x%x runs past the TOC" % p)
        esize, eoff, dlen, _ulen, cflag, typ = PYI_TOC.unpack_from(data, p)
        if esize < PYI_TOC.size or p + esize > end or eoff + dlen > pkg_len:
            raise bad("the TOC entry at 0x%x (size %d, data at %d+%d) does not fit" % (p, esize, eoff, dlen))
        name = data[p + PYI_TOC.size:p + esize].rstrip(b"\0").decode("utf-8", "replace")
        p += esize
        t = typ.decode("latin-1")
        if t in PYI_SKIPPED:
            skipped[t] += 1
            continue
        blob = data[start + eoff:start + eoff + dlen]
        if cflag:
            try:
                blob = zlib.decompress(blob)
            except zlib.error as exc:
                raise ScanError("CArchive entry %r does not decompress: %s" % (name, exc)) from exc
        entries.append((name, t, blob))
    return {"entries": entries, "skipped": dict(skipped)}


# --- objects, trees, layers ----------------------------------------------------------------------

class _Seen:
    """A decompressed stream handed to tarfile, which counts what it hands out and keeps the last KEEP bytes of it, so
    that the bytes after the point where the tar walk stopped can be read back (tarfile reads ahead of a header by at
    most its record size)."""

    KEEP = 1 << 16

    def __init__(self, f: Any) -> None:
        self.f, self.pos, self.kept = f, 0, 0
        self.chunks: Deque[Tuple[int, bytes]] = collections.deque()

    def read(self, size: int = -1) -> bytes:
        data = self.f.read(size)
        if data:
            self.chunks.append((self.pos, data))
            self.pos += len(data)
            self.kept += len(data)
            while self.kept - len(self.chunks[0][1]) >= self.KEEP:
                self.kept -= len(self.chunks.popleft()[1])
        return data

    def since(self, offset: int) -> bytes:
        """The bytes handed out from offset on."""
        first = self.chunks[0][0] if self.chunks else self.pos
        if not first <= offset <= self.pos:
            raise ScanError("the tar walk stopped at %d, outside the %d..%d kept" % (offset, first, self.pos))
        return b"".join(c for _o, c in self.chunks)[offset - first:]


def decompressed(f: IO[bytes]) -> Any:
    """f's tar stream: gzip, bzip2 and xz read to the end of their last member or stream (concatenated members are
    read, as the container runtimes read a gzip layer), an uncompressed tar as it is; zstd raises ScanError."""
    if not hasattr(f, "peek"):
        f = cast(IO[bytes], io.BufferedReader(cast(Any, _Raw(f))))
    head = cast(Any, f).peek(10)[:10]
    if head[:4] == ZSTD_MAGIC:
        raise ScanError("zstd-compressed: not readable with the standard library here")
    if head[:3] == GZIP_MAGIC:
        return gzip.GzipFile(fileobj=f, mode="rb")
    if head[:3] == BZIP2_MAGIC and head[4:10] == b"1AY&SY":
        return bz2.BZ2File(f)
    if head[:6] == XZ_MAGIC:
        return lzma.LZMAFile(f)
    return f


class _Raw(io.RawIOBase):
    """Any file object's read() as a raw stream, for a buffer to peek through."""

    def __init__(self, f: IO[bytes]) -> None:
        super().__init__()
        self.f = f

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        data = self.f.read(len(b))
        b[:len(data)] = data
        return len(data)


class Collector:
    """Every scanned object of one walk, and what was seen but not scanned."""

    def __init__(self) -> None:
        self.objects: List[Dict[str, Any]] = []
        self.other_elf: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.carchives: List[Dict[str, Any]] = []

    def blob(self, path: str, data: bytes, depth: int = 0) -> None:
        kind = elf_kind(data)
        if kind is None:
            return
        if kind == "other":
            self.other_elf.append(elf_ident(path, data))
            return
        try:
            rec = scan_elf(data)
        except (ScanError, struct.error) as exc:
            self.errors.append("%s: %s" % (path, exc))
            return
        rec["path"] = path
        rec["bytes"] = len(data)
        rec["sha256"] = hashlib.sha256(data).hexdigest()
        self.objects.append(rec)
        try:
            if depth >= PYI_MAX_DEPTH:
                if PYI_MAGIC in data:
                    raise ScanError("a CArchive cookie magic in an archive nested %d deep: not opened" % depth)
                return
            arc = carchive_entries(data)
        except ScanError as exc:
            self.errors.append("%s: %s" % (path, exc))
            return
        if arc is not None:
            self.carchives.append({"path": path, "entries": len(arc["entries"]), "skipped": arc["skipped"]})
            for name, _t, inner in arc["entries"]:
                self.blob("%s!%s" % (path, name), inner, depth + 1)

    def tar(self, fileobj: IO[bytes], prefix: str) -> None:
        """Every regular file of a tar stream (compressed or not, decompressed()), each ELF among them scanned; the
        stream after the point where the walk stops must be zeros to its end, or ScanError."""
        dec = decompressed(fileobj)
        seen = _Seen(dec)
        with tarfile.open(fileobj=cast(IO[bytes], seen), mode="r|") as tf:
            for m in tf:
                if not m.isreg():
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                head = f.read(4)
                if head != ELF_MAGIC:
                    continue
                self.blob("%s%s" % (prefix, m.name), head + f.read())
            stop = tf.offset
        rest = seen.since(stop)
        while rest:
            if rest.count(0) != len(rest):
                raise ScanError("non-zero data after the tar's end at offset %d (its end-of-archive marker, the end of its "
                                "data, or a header it cannot read)" % stop)
            rest = dec.read(1 << 20)

    def summary(self) -> Dict[str, Any]:
        return summarize(self.objects, self.other_elf, self.errors, self.carchives)


def summarize(objects: Sequence[Dict[str, Any]], other_elf: Sequence[Dict[str, Any]] = (), errors: Sequence[str] = (),
              carchives: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    keys = ("exec_words", "llsc", "cas", "casp", "amo", "lse", "guarded", "unguarded", "ldapr", "lor", "flagged_code_like",
            "flagged_data_like")
    tot = {k: sum(o[k] for o in objects) for k in keys}
    return dict(tot, objects=len(objects), info={k: sum(o["info"][k] for o in objects) for k in INFO},
                flagged=[o["path"] for o in objects if any(o[k] for k in GATED)],
                code_read_as_none=[o["path"] for o in objects if o["exec_load"] and not o["exec_words"]],
                from_segments=[o["path"] for o in objects if o["source"].startswith("segments")],
                other_elf=len(other_elf), other_elf_objects=list(other_elf), errors=list(errors), carchives=list(carchives))


def flagged_words(obj: Dict[str, Any]) -> List[str]:
    """Every flagged word of one object's record, `0x<address> <class> <word>`, in address order."""
    return sorted((w for k in FLAGGED_LISTS for w in obj.get(k, ())), key=lambda s: int(s.split()[0], 16))


def clean(summary: Dict[str, Any]) -> List[str]:
    """Why a summary fails the A72 rule: any unguarded LSE, LDAPR or LOR word, an object with an executable PT_LOAD read
    as 0 words, an object that could not be read."""
    out = ["%d %s word(s)" % (summary[k], k) for k in GATED if summary[k]]
    if summary["code_read_as_none"]:
        out.append("%d object(s) with an executable PT_LOAD read as 0 words: %s" % (len(summary["code_read_as_none"]),
                                                                                    summary["code_read_as_none"][:5]))
    if summary["errors"]:
        out.append("%d object(s) not read: %s" % (len(summary["errors"]), summary["errors"][:5]))
    return out


class HashingReader(io.RawIOBase):
    """Reads a file object through sha256; finish() reads the rest and compares with the digest."""

    def __init__(self, f: IO[bytes], digest: str) -> None:
        super().__init__()
        self.f, self.digest, self.h, self.n = f, digest, hashlib.sha256(), 0

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        data = self.f.read(len(b))
        self.h.update(data)
        self.n += len(data)
        b[:len(data)] = data
        return len(data)

    def finish(self) -> None:
        for chunk in iter(lambda: self.f.read(1 << 20), b""):
            self.h.update(chunk)
            self.n += len(chunk)
        got = "sha256:" + self.h.hexdigest()
        if got != self.digest:
            raise ScanError("blob %s hashes to %s (%d bytes)" % (self.digest, got, self.n))


def scan_layer(f: IO[bytes], digest: str, collector: Collector, prefix: str = "") -> None:
    """One layer blob, checked against its digest as it is read: a tar, uncompressed or compressed as decompressed()
    reads it -- gzip to the end of its last member, bzip2 and xz to the end of their last stream -- with nothing but
    zeros after the tar's end (Collector.tar). A zstd layer is refused (ScanError): this Python has no zstd decoder. A
    tar nested inside the layer, compressed or not, is a file like any other: it is not opened, and its ELFs are not
    scanned."""
    hr = HashingReader(f, digest)
    br = io.BufferedReader(hr, 1 << 20)
    try:
        collector.tar(br, prefix)
    except READ_ERRORS as exc:
        hr.finish()                     # a blob that is not what its digest names is reported as that first
        raise ScanError("layer %s is not a readable tar: %s" % (digest, exc)) from exc
    hr.finish()


def _member(tf: tarfile.TarFile, digest: str) -> IO[bytes]:
    algo, _, hexd = digest.partition(":")
    if algo != "sha256" or len(hexd) != 64:
        raise ScanError("not a sha256 digest: %r" % digest)
    try:
        f = tf.extractfile("blobs/sha256/" + hexd)
    except KeyError:
        f = None
    if f is None:
        raise ScanError("the saved image has no blob %s" % digest)
    return f


MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")


def manifest_of(raw: bytes, digest: str) -> Dict[str, Any]:
    if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
        raise ScanError("manifest %s does not hash to its digest" % digest)
    man = json.loads(raw)
    mt = man.get("mediaType")
    if mt not in MANIFEST_TYPES or "config" not in man or "layers" not in man:
        raise ScanError("%s is not a single-platform image manifest (mediaType %r)" % (digest, mt))
    return man


def saved_image(get: Callable[[str], bytes], image_id: str, config_digest: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The manifest an image ID names among a `docker save` tar's blobs (get(digest) -> the blob's bytes; the containerd
    store's ID of a built or loaded image is its manifest digest) and its config, both hash-checked; the config digest
    must be the expected one when given."""
    man = manifest_of(get(image_id), image_id)
    cd = man["config"]["digest"]
    if config_digest is not None and cd != config_digest:
        raise ScanError("image %s: config digest %s, expected %s" % (image_id, cd, config_digest))
    raw = get(cd)
    if "sha256:" + hashlib.sha256(raw).hexdigest() != cd:
        raise ScanError("config %s does not hash to its digest" % cd)
    return man, json.loads(raw)


def scan_saved_image(path: str, image_id: str, config_digest: Optional[str] = None) -> Dict[str, Any]:
    with tarfile.open(path, mode="r:") as tf:
        man, cfg = saved_image(lambda d: _member(tf, d).read(), image_id, config_digest)
        col = Collector()
        for i, layer in enumerate(man["layers"]):
            scan_layer(_member(tf, layer["digest"]), layer["digest"], col, "L%d:" % i)
    return {"manifest": image_id, "config_digest": man["config"]["digest"], "architecture": cfg.get("architecture"),
            "os": cfg.get("os"), "variant": cfg.get("variant"), "layers": [lay["digest"] for lay in man["layers"]],
            "diff_ids": list((cfg.get("rootfs") or {}).get("diff_ids") or []), "summary": col.summary(), "objects": col.objects}


# --- a registry, read only -----------------------------------------------------------------------

ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])


def registry_of(repo: str) -> Tuple[str, str]:
    """('ghcr.io', 'eclipse-kuksa/x') for 'ghcr.io/eclipse-kuksa/x'; Docker Hub's API host for 'docker.io/...'."""
    host, _, path = repo.partition("/")
    return ("registry-1.docker.io" if host == "docker.io" else host), path


class RegistryClient:
    """Anonymous pulls by digest only; every body is checked against its digest before it is used."""

    def __init__(self, repo: str, timeout: float = 300) -> None:
        self.host, self.path = registry_of(repo)
        self.timeout = timeout
        self._token: Optional[str] = None

    def token(self) -> str:
        if self._token is None:
            if self.host == "ghcr.io":
                url = "https://ghcr.io/token?scope=repository:%s:pull&service=ghcr.io" % self.path
            elif self.host == "registry-1.docker.io":
                url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull" % self.path
            else:
                raise ScanError("no token endpoint known for %s" % self.host)
            with urllib.request.urlopen(url, timeout=60) as r:
                j = json.loads(r.read())
            self._token = j.get("token") or j.get("access_token")
        return self._token or ""

    def _open(self, kind: str, digest: str, accept: Optional[str] = None) -> Any:
        req = urllib.request.Request("https://%s/v2/%s/%s/%s" % (self.host, self.path, kind, digest))
        req.add_header("Authorization", "Bearer " + self.token())
        if accept:
            req.add_header("Accept", accept)
        return urllib.request.urlopen(req, timeout=self.timeout)

    def manifest(self, digest: str) -> bytes:
        with self._open("manifests", digest, ACCEPT) as r:
            raw = r.read()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            raise ScanError("%s/%s: manifest %s does not hash to its digest" % (self.host, self.path, digest))
        return raw

    def blob(self, digest: str) -> bytes:
        with self._open("blobs", digest) as r:
            raw = r.read()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            raise ScanError("%s/%s: blob %s does not hash to its digest" % (self.host, self.path, digest))
        return raw

    def blob_to(self, digest: str, dest: str) -> int:
        h, n = hashlib.sha256(), 0
        with self._open("blobs", digest) as r, open(dest, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                f.write(chunk)
                n += len(chunk)
        if "sha256:" + h.hexdigest() != digest:
            raise ScanError("%s/%s: blob %s hashes to sha256:%s" % (self.host, self.path, digest, h.hexdigest()))
        return n


def platform_entry(index: Dict[str, Any], os_: str = "linux", arch: str = "arm64") -> Optional[str]:
    """The manifest digest an image index lists for one platform (attestation entries, platform unknown/unknown, aside)."""
    hits = [m["digest"] for m in index.get("manifests", [])
            if (m.get("platform") or {}).get("os") == os_ and (m.get("platform") or {}).get("architecture") == arch]
    if len(hits) > 1:
        raise ScanError("the index lists %d %s/%s manifests" % (len(hits), os_, arch))
    return hits[0] if hits else None


# --- command line ----------------------------------------------------------------------------------

def scan_path(path: str) -> Dict[str, Any]:
    """One command-line argument: an ELF, or a tar of files (compressed or not); anything else raises ScanError."""
    col = Collector()
    with open(path, "rb") as f:
        head = f.read(4)
        f.seek(0)
        if head == ELF_MAGIC:
            col.blob(path, f.read())
        else:
            try:
                col.tar(f, path + ":")
            except READ_ERRORS as exc:
                raise ScanError("%s is neither an ELF nor a readable tar: %s" % (path, exc)) from exc
    return {"path": path, "summary": col.summary(), "objects": col.objects}


def main(argv: Optional[Sequence[str]] = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print(__doc__.split("\n\n")[1] if __doc__ else "", file=sys.stderr)
        return 2
    bad = 0
    for p in paths:
        try:
            r = scan_path(p)
        except (ScanError, OSError) as exc:
            bad += 1
            print(json.dumps({"path": p, "verdict": "ERROR", "why": [str(exc)]}, sort_keys=True))
            continue
        s = r["summary"]
        why = clean(s)
        bad += bool(why)
        print(json.dumps({"path": p, "verdict": "clean" if not why else "FLAGGED", "why": why,
                          "summary": {k: v for k, v in s.items() if k not in ("from_segments",)}}, sort_keys=True))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
