#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""m5-gate.py - the header gate for M5LOAD.EFI.

Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md section 3.4, as
amended by section 13 decision L (two sections, not one), and s1-design.md
section 15.13.4 (J7a: items 8 by variant, 11 and 12).
build-m5-loader.sh runs it and any miss fails the build.

The twelve items, in the design's order:

  1  MZ, PE\\0\\0, Machine 0xAA64, PE32+ magic 0x20b, Subsystem 10.
  2  Characteristics bit 0x0001 (RELOCS_STRIPPED) clear; ImageBase 0.
  3  SectionAlignment and FileAlignment 0x1000; exactly two sections, code and
     data, with the code section not writable and the data section not
     executable; SizeOfHeaders 0x1000; SizeOfImage page-aligned and covering
     both sections.
  4  The entry RVA lies inside the code section and before the embedded blob.
  5  Every data directory is zero.
  6  Position independence, tested: the linked ELF carries no relocation
     records, and linking at base 0 and at 0x100000 gives identical files.
  7  The blob's sha256 equals the pin; the length and CRC32 constants equal
     values computed from the blob itself.
  8  The T0 build and the board build differ only in the blob, its constants,
     and the header fields that are a function of the payload's size. Builds
     are compared only within one variant. For J7a the T0 build is padded like
     the kimg (T0_PAD_LIKE), so the size fields must be identical too: blob and
     constants only.
  9  The cache and MMU sequence, read statically, over the trampoline's symbol
     range only - never over the blob (NC QDL v7 4.6(c)).
  10 Print the output's sha256, which is the value that gets staged.
  11 (J7a, UM1) The window-2 and canary constants in m5load-rules.h equal
     board/t234_startup.h's T234_RAM2_* and T234_CANARY* defines.
  12 (J7a) No T0-only force switch in a board build: the ELF defines no
     m5_t0_force and --force is none; the declared variant is the one the
     image carries; and a J7a board build was compared (item 8) with a J7a T0
     build and differs from it only in the blob and constants.

Item 3's characteristics check exists because the first T0b run faulted on the
first write to an in-image static: a single read-write-execute section was
mapped non-writable by the firmware. The check makes that defect impossible to
reintroduce unnoticed.

Standard library only. Every check that cannot be performed fails closed.
"""

import argparse
import hashlib
import os
import re
import struct
import subprocess
import sys
import zlib

PAGE = 0x1000

SCN_CNT_CODE = 0x00000020
SCN_CNT_INIT_DATA = 0x00000040
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000

# The J7a variant's first own line (UM2). Its bytes sit in .text, before the
# blob, and in no other build.
J7A_MARK = b"M5L variant=j7a"
FORCE_SYMBOL = "m5_t0_force"


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
    """Return ({name: address}, [relocation sections]) from an ELF64 LE file."""
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
        if (nm.startswith(".rela") or nm.startswith(".rel.")) and s["size"] > 0:
            rela.append((nm, s["size"]))
        if s["type"] != 2:                       # SHT_SYMTAB
            continue
        strtab = sections[s["link"]]
        for i in range(s["size"] // s["entsize"]):
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
                                      rawptr=rawptr, chars=chars, off=so))

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def variant_of(image, blob_rva):
    """j7a when the J7a marker sits before the blob, else m5."""
    head = image[:blob_rva] if blob_rva else image
    return "j7a" if J7A_MARK in head else "m5"


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


# ----------------------------------------------------------------- item 11

DEFINE_RE = r"^[ \t]*#[ \t]*define[ \t]+%s[ \t]+(0[xX][0-9A-Fa-f]+|[0-9]+)[uUlL]*\b"


def parse_defines(path, names):
    """{name: int} for each '#define NAME <integer>' line; a name that is
    missing or defined twice is absent from the result."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    out = {}
    for n in names:
        hits = re.findall(DEFINE_RE % re.escape(n), text, flags=re.M)
        if len(hits) == 1:
            out[n] = int(hits[0], 0)
    return out


def item11(g, a):
    rules_names = ["M5L_W2_START", "M5L_W2_END", "M5L_CANARY_C1", "M5L_CANARY_C2",
                   "M5L_CANARY_C3", "M5L_CANARY_SIZE", "M5L_CANARY_PAGES"]
    board_names = ["T234_RAM2_BASE", "T234_RAM2_SIZE", "T234_CANARY1_BASE", "T234_CANARY2_BASE",
                   "T234_CANARY3_BASE", "T234_CANARY_SIZE"]
    if not a.rules_src or not a.startup_h:
        g.bad(11, "the J7a build needs --rules-src and --startup-h")
        return
    try:
        r = parse_defines(a.rules_src, rules_names)
        b = parse_defines(a.startup_h, board_names)
    except OSError as e:
        g.bad(11, "cannot read the sources: %s" % e)
        return
    missing = [n for n in rules_names if n not in r] + [n for n in board_names if n not in b]
    if missing:
        g.bad(11, "missing or duplicated defines: %s" % missing)
        return
    pairs = [
        ("M5L_W2_START", r["M5L_W2_START"], "T234_RAM2_BASE", b["T234_RAM2_BASE"]),
        ("M5L_W2_END", r["M5L_W2_END"], "T234_RAM2_BASE+T234_RAM2_SIZE",
         b["T234_RAM2_BASE"] + b["T234_RAM2_SIZE"]),
        ("M5L_CANARY_C1", r["M5L_CANARY_C1"], "T234_CANARY1_BASE", b["T234_CANARY1_BASE"]),
        ("M5L_CANARY_C2", r["M5L_CANARY_C2"], "T234_CANARY2_BASE", b["T234_CANARY2_BASE"]),
        ("M5L_CANARY_C3", r["M5L_CANARY_C3"], "T234_CANARY3_BASE", b["T234_CANARY3_BASE"]),
        ("M5L_CANARY_SIZE", r["M5L_CANARY_SIZE"], "T234_CANARY_SIZE", b["T234_CANARY_SIZE"]),
        ("M5L_CANARY_PAGES*0x1000", r["M5L_CANARY_PAGES"] * PAGE, "T234_CANARY_SIZE",
         b["T234_CANARY_SIZE"]),
    ]
    diff = ["%s != %s" % (x, y) for x, xv, y, yv in pairs if xv != yv]
    g.check(11, not diff,
            "window 2 and the three canaries in m5load-rules.h equal t234_startup.h (%d checks)" % len(pairs),
            "constants differ: %s" % diff)


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
    ap.add_argument("--variant", choices=["m5", "j7a"], default="m5",
                    help="the variant the build script compiled (M5L_J7A)")
    ap.add_argument("--force", choices=["none", "um6-first", "um6-later"], default="none",
                    help="the T0_FORCE the build script compiled")
    ap.add_argument("--rules-src", help="m5load-rules.h, for item 11")
    ap.add_argument("--startup-h", help="board/t234_startup.h, for item 11")
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

    # item 3: two sections, and the page attributes the firmware will apply
    text = pe.section(".text")
    data = pe.section(".data")
    ok3 = (pe.section_align == PAGE and pe.file_align == PAGE and pe.nsections == 2 and
           pe.size_headers == PAGE and text is not None and data is not None and
           pe.size_image % PAGE == 0 and
           pe.size_image >= max(s["vaddr"] + s["vsize"] for s in pe.sections))
    if ok3:
        code_w = bool(text["chars"] & SCN_MEM_WRITE)
        data_x = bool(data["chars"] & SCN_MEM_EXECUTE)
        code_x = bool(text["chars"] & SCN_MEM_EXECUTE)
        data_w = bool(data["chars"] & SCN_MEM_WRITE)
        ok3 = (not code_w) and code_x and data_w and (not data_x)
        g.check(3, ok3,
                "two sections: .text %#x+%#x code, not writable; .data %#x+%#x writable, not executable; image %#x" % (
                    text["vaddr"], text["vsize"], data["vaddr"], data["vsize"], pe.size_image),
                ".text writable=%s executable=%s, .data writable=%s executable=%s "
                "(a writable code section is mapped non-writable by the firmware: section 13 L)" % (
                    code_w, code_x, data_w, data_x))
    else:
        g.bad(3, "align=%#x/%#x sections=%d headers=%#x image=%#x names=%s" % (
            pe.section_align, pe.file_align, pe.nsections, pe.size_headers, pe.size_image,
            [s["name"] for s in pe.sections]))

    # item 4: the entry sits in the code section, before the blob
    blob_rva = syms.get("m5_blob_start")
    entry_ok = (text is not None and blob_rva is not None and
                text["vaddr"] <= pe.entry_rva < text["vaddr"] + text["vsize"] and
                pe.entry_rva < blob_rva)
    g.check(4, entry_ok,
            "entry %#x inside .text and before the blob at %#x" % (pe.entry_rva, blob_rva or 0),
            "entry=%#x text=%s blob=%s" % (
                pe.entry_rva,
                "%#x+%#x" % (text["vaddr"], text["vsize"]) if text else "missing",
                hex(blob_rva) if blob_rva else "missing"))

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

    # item 8: only meaningful when both builds exist, and only within a variant
    own_variant = variant_of(pe_bytes, blob_rva)
    item8_ran = False
    item8_ok = False
    if a.compare and os.path.exists(a.compare):
        with open(a.compare, "rb") as fh:
            other = fh.read()
        # The compare image's own blob offset is not known here (no symbols for it), and it differs
        # between variants (the J7a code is larger), so this build's offset would cut a J7a image
        # before its marker and read it as m5. Scan the whole image: the marker is the loader's own
        # line, compiled only under M5L_J7A, and no blob (the T0 probe or a kimg) carries that text.
        other_variant = variant_of(other, None)
        if other_variant != own_variant:
            g.lines.append("M5G item=8  SKIP the compare build is variant %s, this build is %s" % (
                other_variant, own_variant))
        else:
            const_syms = [syms.get(n) for n in ("m5_blob_len", "m5_blob_crc32", "m5_blob_image_size")]
            const_ok = all(s is not None for s in const_syms)
            allowed = set()
            if const_ok:
                for s in const_syms:
                    allowed.update(range(s, s + 8))
            if own_variant == "m5":
                # The header fields that are a function of the payload's size
                # must differ when the payloads differ: SizeOfCode,
                # SizeOfInitializedData, SizeOfImage, and each section's
                # VirtualSize and SizeOfRawData. Their offsets come from the
                # parsed header, never from a constant, so a layout change
                # cannot quietly widen this exemption.
                for off in (pe.opt_off + 4, pe.opt_off + 8, pe.opt_off + 56):
                    allowed.update(range(off, off + 4))
                for s in pe.sections:
                    allowed.update(range(s["off"] + 8, s["off"] + 12))
                    allowed.update(range(s["off"] + 16, s["off"] + 20))
                same_len = True
            else:
                # J7a: the T0 build is padded like the kimg, so the files are
                # the same length and the size fields are not exempt.
                same_len = len(pe_bytes) == len(other)
            head = min(len(pe_bytes), len(other), blob_rva or 0)
            diffs = [i for i in range(head) if pe_bytes[i] != other[i] and i not in allowed]
            item8_ran = True
            if own_variant == "m5":
                item8_ok = g.check(8, const_ok and not diffs,
                                   "the two builds differ only in the blob, its three constants and the size fields",
                                   "differing offsets outside the blob, constants and size fields: %s" % (
                                       [hex(d) for d in diffs[:8]] if const_ok else "constant symbols missing"))
            else:
                item8_ok = g.check(8, const_ok and not diffs and same_len,
                                   "variant j7a: the two builds differ only in the blob and its constants "
                                   "(size fields and file length identical)",
                                   "variant j7a: same_length=%s; differing offsets outside the blob and constants: %s" % (
                                       same_len,
                                       [hex(d) for d in diffs[:8]] if const_ok else "constant symbols missing"))
    else:
        g.lines.append("M5G item=8  SKIP the other build is not present yet")

    # item 9
    t0s, t0e = syms.get("m5_tramp_start"), syms.get("m5_tramp_end")
    if t0s is None or t0e is None or t0e <= t0s:
        g.bad(9, "the trampoline symbols are missing: the sequence cannot be read")
    else:
        rc, text_out = disassemble_range(a.objdump, a.elf, t0s, t0e)
        if rc != 0:
            g.bad(9, "objdump returned %d" % rc)
        elif blob_rva is not None and t0e > blob_rva:
            g.bad(9, "the trampoline range reaches into the blob: refusing to read it")
        else:
            good, seen, missing = sequence_ok(text_out)
            g.check(9, good,
                    "the cache and MMU sequence is present and in order, over %#x-%#x" % (t0s, t0e),
                    "missing or out of order: %s (seen %s)" % (missing, seen))

    # item 10
    digest = sha256(a.pe)
    g.ok(10, "sha256=%s" % digest)

    # item 11 (J7a only)
    if a.variant == "j7a":
        item11(g, a)
    else:
        g.lines.append("M5G item=11 SKIP variant m5 (M5L_J7A off)")

    # item 12: no force switch in a board build; the variant is what it claims
    force_sym = FORCE_SYMBOL in syms
    fails = []
    if a.variant != own_variant:
        fails.append("declared variant %s, but the image carries %s" % (a.variant, own_variant))
    if a.build == "board":
        if a.force != "none":
            fails.append("a board build declared --force %s" % a.force)
        if force_sym:
            fails.append("the ELF defines %s: a T0_FORCE build presented as a board build" % FORCE_SYMBOL)
        if own_variant == "j7a":
            if not item8_ran:
                fails.append("no J7a T0 build was compared (item 8 did not run within the variant)")
            elif not item8_ok:
                fails.append("it differs from the J7a T0 build outside the blob and constants")
            if a.compare:
                other_elf = os.path.join(os.path.dirname(a.compare), "m5load.elf")
                if os.path.exists(other_elf):
                    try:
                        osyms, _ = elf_symbols(other_elf)
                        if FORCE_SYMBOL in osyms:
                            fails.append("the compare build is a T0_FORCE build")
                    except (OSError, ValueError) as e:
                        fails.append("cannot read the compare build's ELF: %s" % e)
    else:
        if (a.force != "none") != force_sym:
            fails.append("--force %s but %s is %s in the ELF" % (
                a.force, FORCE_SYMBOL, "defined" if force_sym else "absent"))
        if a.force != "none" and own_variant != "j7a":
            fails.append("a force switch outside the J7a variant")
    g.check(12, not fails,
            "build=%s variant=%s force=%s%s" % (
                a.build, own_variant, "none" if not force_sym else a.force,
                ", compared with a J7a T0 build" if (a.build == "board" and own_variant == "j7a") else ""),
            "; ".join(fails))

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
