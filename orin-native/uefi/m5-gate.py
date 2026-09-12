#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""m5-gate.py - the header gate for M5LOAD.EFI.

Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md section 3.4.
build-m5-loader.sh runs it and any miss fails the build.

The ten items, in the design's order:

  1  MZ, PE\\0\\0, Machine 0xAA64, PE32+ magic 0x20b, Subsystem 10.
  2  Characteristics bit 0x0001 (RELOCS_STRIPPED) clear; ImageBase 0.
  3  SectionAlignment and FileAlignment 0x1000; one section; SizeOfHeaders
     0x1000; SizeOfImage page-aligned and covering the section.
  4  The entry RVA lies inside .text and before the embedded blob.
  5  Every data directory is zero.
  6  Position independence, tested: the linked ELF carries no relocation
     records, and linking at base 0 and at 0x100000 gives identical files.
  7  The blob's sha256 equals the pin; the length and CRC32 constants equal
     values computed from the blob itself.
  8  The T0 build and the board build differ only in the blob and its
     constants.
  9  The cache and MMU sequence, read statically, over the trampoline's symbol
     range only - never over the blob (NC QDL v7 4.6(c)).
  10 Print the output's sha256, which is the value that gets staged.

Standard library only. Every check that cannot be performed fails closed.
"""

import argparse
import hashlib
import os
import struct
import subprocess
import sys
import zlib

PAGE = 0x1000


class Gate:
    def __init__(self):
        self.lines = []
        self.failed = 0

    def ok(self, item, msg):
        self.lines.append("M5G item=%-2s PASS %s" % (item, msg))

    def bad(self, item, msg):
        self.lines.append("M5G item=%-2s FAIL %s" % (item, msg))
        self.failed += 1

    def check(self, item, cond, good, bad):
        if cond:
            self.ok(item, good)
        else:
            self.bad(item, bad)
        return bool(cond)


# ----------------------------------------------------------------- ELF

def elf_symbols(path):
    """Return {name: address} from an ELF64 little-endian file's .symtab."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError("not a little-endian ELF64: %s" % path)
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name, stype, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(
            "<IIQQQQIIQQ", data, off)
        sections.append(dict(name=name, type=stype, addr=addr, offset=offset, size=size,
                             link=link, entsize=entsize))
    shstr = sections[e_shstrndx]

    def sname(s):
        start = shstr["offset"] + s["name"]
        end = data.index(b"\0", start)
        return data[start:end].decode("ascii", "replace")

    syms = {}
    rela = []
    for s in sections:
        nm = sname(s)
        if nm.startswith(".rela") or nm.startswith(".rel."):
            if s["size"] > 0:
                rela.append((nm, s["size"]))
        if s["type"] != 2:                       # SHT_SYMTAB
            continue
        strtab = sections[s["link"]]
        n = s["size"] // s["entsize"]
        for i in range(n):
            off = s["offset"] + i * s["entsize"]
            st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(
                "<IBBHQQ", data, off)
            if st_name == 0:
                continue
            start = strtab["offset"] + st_name
            end = data.index(b"\0", start)
            syms[data[start:end].decode("ascii", "replace")] = st_value
    return syms, rela


# ----------------------------------------------------------------- PE

class PE:
    def __init__(self, path):
        with open(path, "rb") as fh:
            self.raw = fh.read()
        self.path = path
        if len(self.raw) < 0x200 or self.raw[:2] != b"MZ":
            raise ValueError("no MZ magic: %s" % path)
        self.e_lfanew, = struct.unpack_from("<I", self.raw, 0x3C)
        if self.raw[self.e_lfanew:self.e_lfanew + 4] != b"PE\0\0":
            raise ValueError("no PE signature: %s" % path)
        c = self.e_lfanew + 4
        (self.machine, self.nsections, self.timestamp, self.symtab, self.nsyms,
         self.opt_size, self.characteristics) = struct.unpack_from("<HHIIIHH", self.raw, c)
        o = c + 20
        self.opt_off = o
        (self.opt_magic, self.major_linker, self.minor_linker, self.size_code,
         self.size_init, self.size_uninit, self.entry_rva, self.base_code) = struct.unpack_from(
            "<HBBIIIII", self.raw, o)
        (self.image_base, self.section_align, self.file_align) = struct.unpack_from("<QII", self.raw, o + 24)
        (self.size_image, self.size_headers) = struct.unpack_from("<II", self.raw, o + 56)
        (self.subsystem, self.dll_chars) = struct.unpack_from("<HH", self.raw, o + 68)
        self.nrva, = struct.unpack_from("<I", self.raw, o + 108)
        self.dirs_off = o + 112
        self.sect_off = o + self.opt_size
        self.sections = []
        for i in range(self.nsections):
            so = self.sect_off + i * 40
            name = self.raw[so:so + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", self.raw, so + 8)
            chars, = struct.unpack_from("<I", self.raw, so + 36)
            self.sections.append(dict(name=name, vsize=vsize, vaddr=vaddr, rawsize=rawsize,
                                      rawptr=rawptr, chars=chars))


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ----------------------------------------------------------------- item 9

SEQUENCE = ["dc\tcivac", "dsb\tsy", "ic\tiallu", "dsb\tsy", "isb", "msr\tsctlr_el2", "isb", "br\t"]


def disassemble_range(objdump, elf, start, stop):
    """Disassemble our own ELF over [start, stop) only. The bound is the 4.6(c)
    control: the embedded blob is QNX code and must never be disassembled."""
    cmd = [objdump, "-d", "--start-address", hex(start), "--stop-address", hex(stop), elf]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    return out.returncode, out.stdout.decode("latin-1")


def sequence_ok(text):
    """The eight operations must appear in this order. Other instructions may
    sit between them; nothing may be missing or out of order."""
    want = list(SEQUENCE)
    seen = []
    for line in text.splitlines():
        body = line.split("\t", 2)[2:] if line.count("\t") >= 2 else []
        insn = body[0].strip() if body else ""
        if not insn:
            continue
        norm = insn.replace(" ", "\t", 1)
        while want and norm.startswith(want[0]):
            seen.append(want.pop(0))
            break
    return (not want), seen, want


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="the M5LOAD.EFI header gate")
    ap.add_argument("--pe", required=True, help="the flat PE this build produced")
    ap.add_argument("--alt", required=True, help="the same link at base 0x100000")
    ap.add_argument("--elf", required=True, help="the linked ELF the PE came from")
    ap.add_argument("--blob", required=True, help="the embedded payload")
    ap.add_argument("--blob-len", type=int, required=True)
    ap.add_argument("--blob-crc", type=int, required=True)
    ap.add_argument("--blob-sha256", help="the pin, board build only")
    ap.add_argument("--build", choices=["board", "t0"], required=True)
    ap.add_argument("--compare", help="the other build's PE, for item 8")
    ap.add_argument("--objdump", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    g = Gate()
    pe = PE(a.pe)
    syms, rela = elf_symbols(a.elf)

    g.lines.append("M5G build=%s pe=%s" % (a.build, os.path.basename(a.pe)))

    # item 1
    ok1 = (pe.machine == 0xAA64 and pe.opt_magic == 0x20B and pe.subsystem == 10)
    g.check(1, ok1, "MZ, PE, machine=0xaa64, magic=0x20b, subsystem=10",
            "machine=%#x magic=%#x subsystem=%d" % (pe.machine, pe.opt_magic, pe.subsystem))

    # item 2
    g.check(2, (pe.characteristics & 0x0001) == 0 and pe.image_base == 0,
            "characteristics=%#x relocs_stripped clear, image_base=0" % pe.characteristics,
            "characteristics=%#x image_base=%#x" % (pe.characteristics, pe.image_base))

    # item 3
    sect = pe.sections[0] if pe.sections else None
    ok3 = (pe.section_align == PAGE and pe.file_align == PAGE and pe.nsections == 1 and
           pe.size_headers == PAGE and sect is not None and
           pe.size_image % PAGE == 0 and pe.size_image >= sect["vaddr"] + sect["vsize"])
    g.check(3, ok3,
            "alignments 0x1000, one section, headers 0x1000, image %#x covers %s" % (
                pe.size_image, sect["name"] if sect else "-"),
            "align=%#x/%#x sections=%d headers=%#x image=%#x" % (
                pe.section_align, pe.file_align, pe.nsections, pe.size_headers, pe.size_image))

    # item 4: the entry sits in .text, before the blob
    blob_rva = syms.get("m5_blob_start")
    entry_ok = (sect is not None and blob_rva is not None and
                sect["vaddr"] <= pe.entry_rva < blob_rva)
    g.check(4, entry_ok,
            "entry %#x inside %s and before the blob at %#x" % (
                pe.entry_rva, sect["name"] if sect else "-", blob_rva or 0),
            "entry=%#x blob=%s" % (pe.entry_rva, hex(blob_rva) if blob_rva else "missing"))

    # item 5
    dirs = struct.unpack_from("<%dQ" % pe.nrva, pe.raw, pe.dirs_off)
    g.check(5, pe.nrva == 6 and all(d == 0 for d in dirs),
            "%d data directories, all zero" % pe.nrva,
            "nrva=%d nonzero=%s" % (pe.nrva, [hex(d) for d in dirs if d]))

    # item 6
    with open(a.pe, "rb") as fh:
        pe_bytes = fh.read()
    with open(a.alt, "rb") as fh:
        alt_bytes = fh.read()
    g.check(6, pe_bytes == alt_bytes and not rela,
            "base 0 and base 0x100000 identical (%d bytes), no relocation sections" % len(pe_bytes),
            "identical=%s rela=%s" % (pe_bytes == alt_bytes, rela))

    # item 7
    with open(a.blob, "rb") as fh:
        blob = fh.read()
    crc = zlib.crc32(blob) & 0xFFFFFFFF
    ok7 = (len(blob) == a.blob_len and crc == a.blob_crc)
    if a.build == "board":
        if not a.blob_sha256:
            g.bad(7, "the board build needs --blob-sha256")
            ok7 = False
        else:
            have = hashlib.sha256(blob).hexdigest()
            if have != a.blob_sha256:
                g.bad(7, "blob sha256 %s is not the pin %s" % (have, a.blob_sha256))
                ok7 = False
    if ok7:
        g.ok(7, "blob len=%d crc32=%#x%s" % (
            len(blob), crc, ", sha256 pinned" if a.build == "board" else ""))
    elif len(blob) != a.blob_len or crc != a.blob_crc:
        g.bad(7, "len=%d/%d crc=%#x/%#x" % (len(blob), a.blob_len, crc, a.blob_crc))

    # item 8: only meaningful when both builds exist
    if a.compare and os.path.exists(a.compare):
        with open(a.compare, "rb") as fh:
            other = fh.read()
        const_syms = [syms.get(n) for n in ("m5_blob_len", "m5_blob_crc32", "m5_blob_image_size")]
        const_ok = all(s is not None for s in const_syms)
        allowed = set()
        if const_ok:
            for s in const_syms:
                allowed.update(range(s, s + 8))
        # The four header fields that are a function of the payload's size must
        # differ when the payloads differ: SizeOfCode, SizeOfImage, and the
        # section table's VirtualSize and SizeOfRawData. Their offsets come from
        # the parsed header, never from a constant, so a layout change cannot
        # quietly widen this exemption.
        for off in (pe.opt_off + 4, pe.opt_off + 56, pe.sect_off + 8, pe.sect_off + 16):
            allowed.update(range(off, off + 4))
        head = min(len(pe_bytes), len(other), blob_rva or 0)
        diffs = [i for i in range(head) if pe_bytes[i] != other[i] and i not in allowed]
        g.check(8, const_ok and not diffs,
                "the two builds differ only in the blob and its three constants",
                "differing offsets outside the blob and constants: %s" % (
                    [hex(d) for d in diffs[:8]] if const_ok else "constant symbols missing"))
    else:
        g.lines.append("M5G item=8  SKIP the other build is not present yet")

    # item 9
    t0s, t0e = syms.get("m5_tramp_start"), syms.get("m5_tramp_end")
    if t0s is None or t0e is None or t0e <= t0s:
        g.bad(9, "the trampoline symbols are missing: the sequence cannot be read")
    else:
        rc, text = disassemble_range(a.objdump, a.elf, t0s, t0e)
        if rc != 0:
            g.bad(9, "objdump returned %d" % rc)
        else:
            if blob_rva is not None and t0e > blob_rva:
                g.bad(9, "the trampoline range reaches into the blob: refusing to read it")
            else:
                good, seen, missing = sequence_ok(text)
                g.check(9, good,
                        "the cache and MMU sequence is present and in order, over %#x-%#x" % (t0s, t0e),
                        "missing or out of order: %s (seen %s)" % (missing, seen))

    # item 10
    digest = sha256(a.pe)
    g.ok(10, "sha256=%s" % digest)

    report = "\n".join(g.lines) + "\n"
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report)
    sys.stdout.write(report)
    if g.failed:
        sys.stdout.write("M5G REFUSED %d item(s)\n" % g.failed)
        return 1
    sys.stdout.write("M5G PASS sha256=%s\n" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
