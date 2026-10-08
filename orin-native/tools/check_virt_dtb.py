#!/usr/bin/env python3
"""check_virt_dtb.py FILE.dtb [--repo DIR] -- compare the device tree QEMU's virt machine
generates with the addresses and interrupts of that machine that the A6 guest's sources in this
repo hold as constants (Phase 3b / A6, 2026-10-05).

WHY. The guest takes little of the machine from the device tree. The startup we rebuilt, the two
guest programs that configure ivshmem through ECAM, the image build files that start the virtio
console's driver and give rtc the clock's address, and the report that puts a trapped address in
a region each hold QEMU virt's addresses as constants. They were read off one dump by eye
(qemu_virt_startup.h says when, and under which QEMU). Another QEMU release may generate another
tree, and what fails then does not name its cause: with a moved ECAM shmcfg finds no device,
with a moved console slot the kick channel stays silent. This script makes the comparison a
command. It runs no guest and needs no QNX file.

THE DUMP is made by QEMU itself, with the machine and device options the launcher uses
(launch-qnx-kvm-bridged.sh) and no guest code run:

  qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt.dtb -cpu host -enable-kvm \\
      -smp 2 -m 1G -drive file=null-co://,if=none,id=drv0,format=raw \\
      -device virtio-blk-device,drive=drv0 -netdev user,id=n0 -device virtio-net-device,netdev=n0 \\
      -object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-device,rng=rng0 \\
      -display none

It still creates and tears down a KVM VM: on the board it is a step with the owner reachable.

WHAT IS COMPARED. Every constant is READ, at run time, from the file that holds it; this script
holds no address and no interrupt number of the machine, and not the string the PSCI probe
wants. What it does hold is the device-tree binding names it finds a node by (arm,gic-v3,
arm,gic-v3-its, arm,pl011, arm,pl031, pci-host-ecam-generic, virtio,mmio, device_type memory),
the names of the two commands it finds a build file's line by and the option rtc takes its
address with, and the bindings' own arithmetic (a shared peripheral interrupt n is INTID 32 + n;
space code 2 in a PCI range is 32-bit memory). DIR is the checkout whose files are read
(default: the one this script is in).

  orin-native/startup/qemu-virt/qemu_virt_startup.h
      QV_GICD_BASE, QV_GICR_BASE and QV_GICR_SIZE against the arm,gic-v3 node's reg (one
      redistributor region); QV_GITS_BASE against the arm,gic-v3-its node, which must be there;
      QV_PL011_BASE and QV_PL011_IRQ against the arm,pl011 node's reg and interrupt; QV_RAM_BASE
      against the lowest memory node.
  orin-native/startup/qemu-virt/main.c
      the debug device's base against the arm,pl011 node; and the PSCI node's compatible list,
      which must END in the string main.c says the library's probe wants.
  ipc-test/common/shm_map_qnx.c, ipc-test/qnx-its-probe/its_probe.c
      ECAM_BASE against the pci-host-ecam-generic node's reg, with bus 0 at its base and
      ECAM_BUS0_BYTES inside it; MMIO32_BASE and MMIO32_SIZE against the node's one 32-bit
      memory range, whose PCI and CPU addresses must both be MMIO32_BASE.
  orin-native/gpu-concurrency/mmio_report.py
      the FIXED rows GICD, GITS, GICR and UART as regions (base and size); one of its ECAM rows;
      the virtio row against the span the tree's virtio,mmio transports tile; the console row
      (CONSOLE_VIRTIO) against the transport at that address.
  ipc-test/*/*.build
      every line that starts devc-virtio, which ends in LOCATION,INTERRUPT: the tree has a
      transport at LOCATION and it takes that interrupt. CONSOLE_VIRTIO has to be the same slot.
      Every line that runs rtc, which gives it the clock's address as -b ADDRESS: the tree's
      one arm,pl031 node has that base. A tree with no such node, or with two, fails every
      one of these lines.
      Either line is found by its command word, not by where the word stands: a line that is
      not a comment, in which a word names the command (bare or by a path) and at least one
      more word follows it, whatever stands before it (an attribute in brackets, `on -p 20`).
      The image's file list names the command as a word with nothing after it, and is no such
      line. A line that is found and cannot be read is exit 2, never a line to skip: a
      devc-virtio line that does not end in LOCATION,INTERRUPT (a comment after the location
      makes it one), and an rtc line that does not hold -b once with a hexadecimal address as
      its next word, or that has a comment after the command. Exit 2 as well is a line that
      names the command and not as a word (inside quotes, glued to a semicolon, a brace or a
      backslash, after an equals sign): the word rule would pass it over, and a build file
      that runs the command there with another address would agree with any tree. The name
      with a letter, a digit, an underscore, a dot or a hyphen against it, or before a slash,
      is another name and no such line.

One comparison has no constant behind it: the transports' interrupts must rise by one from slot
to slot. The disk image's own startup script, which is not in this repo, binds its block,
network and entropy drivers by address and interrupt on that rule.

  exit 0   every comparison agrees
  exit 1   at least one does not; each is printed on a line that starts MISMATCH and names the
           tree's value, the file, the line and the constant
  exit 2   FILE.dtb is not a device tree this reader can walk, or a source file does not hold a
           constant where this script looks for it, or one of the three steps (reading the
           tree, reading the sources, comparing) stopped on something it did not foresee;
           nothing is concluded

WHAT IT DOES NOT SHOW. A device tree carries no machine-compatibility property, so two machine
types with the same tree are not shown to be the same machine. PCI devices are never in the
tree: ivshmem's ID and its BARs, and the MSI-X table, are not checked here. The tree lists every
virtio-mmio transport whatever is plugged in, so which device sits in which slot is not checked
either (the launcher's device order decides that). The LPI block of startup-qemu-virt-its is a
constant of that startup and is compared with the GIC's own count at boot, not with the tree.
The second ECAM row of mmio_report.py (the address without highmem) is compared with nothing.
Nor is where the image is placed: [image=ADDRESS] in every build file, and QV_IMAGE_BASE, which
repeats it, are an address in RAM and no device's; a tree carries no load address, and only
RAM's base is compared. The repo holds the PL031's base and nothing else of it: its size and its
interrupt are not compared, and the clock type an rtc line names is not read. The files read are
the ones listed above, which are what an A6 guest image is built from and what the report reads;
a virt address in a file of an earlier leg (the payload under orin-native/uefi/t0, say) is not
looked for. And a tree that agrees says nothing about a guest: not that one boots, not that an
interrupt arrives, nothing about timing. Standard library only.
"""
import argparse
import ast
import collections
import glob
import os
import re
import struct
import sys
import traceback

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

HEADER = "orin-native/startup/qemu-virt/qemu_virt_startup.h"
MAIN_C = "orin-native/startup/qemu-virt/main.c"
SHM_C = "ipc-test/common/shm_map_qnx.c"
ITS_C = "ipc-test/qnx-its-probe/its_probe.c"
REPORT = "orin-native/gpu-concurrency/mmio_report.py"
BUILD_GLOB = "ipc-test/*/*.build"
CONSOLE_DRIVER = "devc-virtio"
RTC_COMMAND, RTC_BASE = "rtc", "-b"
SOURCES = (HEADER, MAIN_C, SHM_C, ITS_C, REPORT)

HEADER_NAMES = ("QV_GICD_BASE", "QV_GICR_BASE", "QV_GICR_SIZE", "QV_GITS_BASE", "QV_PL011_BASE", "QV_PL011_IRQ",
                "QV_RAM_BASE")
PCI_NAMES = ("ECAM_BASE", "ECAM_BUS0_BYTES", "MMIO32_BASE", "MMIO32_SIZE")
REPORT_ROWS = ("GICD", "GITS", "GICR", "UART", "console", "virtio", "ECAM")

# A constant as a source file holds it: its value, and "path:line NAME" for the reader.
Const = collections.namedtuple("Const", "value where")


class DtbError(Exception):
    """The file is not a device tree this reader can walk."""


class SourceError(Exception):
    """A source file does not hold a constant where this script looks for it."""


class TreeGap(Exception):
    """The tree parses, and lacks or garbles something a comparison needs: a mismatch, not an error."""


# ------------------------------------------------------------------ the device tree

class Node:
    __slots__ = ("name", "props", "children", "parent")

    def __init__(self, name, parent):
        self.name = name
        self.props = {}
        self.children = []
        self.parent = parent

    def path(self):
        if self.parent is None:
            return "/"
        return self.parent.path().rstrip("/") + "/" + self.name

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def strings(self, prop):
        v = self.props.get(prop)
        if not v:
            return []
        return [s.decode("latin-1") for s in v.rstrip(b"\0").split(b"\0")]

    def u32(self, prop, default):
        """A property of one cell, or default when the node has none. One that is there and is
        not four bytes is a TreeGap: a count that cannot be read is not the binding's default."""
        v = self.props.get(prop)
        if v is None:
            return default
        if len(v) != 4:
            raise TreeGap("%s: %s is %d bytes, not one cell" % (self.path(), prop, len(v)))
        return int.from_bytes(v, "big")


def _cstr(data, pos, end):
    k = data.find(b"\0", pos, end)
    if k < 0:
        raise DtbError("a string runs past its block")
    return data[pos:k].decode("latin-1"), k + 1


def parse_dtb(data):
    """The root Node of a flattened device tree, version 17. DtbError when it cannot be walked."""
    if len(data) < 40:
        raise DtbError("%d bytes: shorter than a device tree's 40-byte header" % len(data))
    (magic, total, off_st, off_str, _off_rsv, version, last_comp, _boot_cpu, size_str,
     size_st) = struct.unpack_from(">10I", data, 0)
    if magic != FDT_MAGIC:
        raise DtbError("it starts with %08x, not with a device tree's d00dfeed" % magic)
    if total < 40 or total > len(data):
        raise DtbError("its header says %d bytes and the file has %d" % (total, len(data)))
    if version < 17 or last_comp > 17:
        raise DtbError("version %d (last compatible %d); this reader reads version 17" % (version, last_comp))
    for what, off, size in (("structure", off_st, size_st), ("strings", off_str, size_str)):
        if off < 40 or off > total or size > total - off:
            raise DtbError("its %s block lies outside the %d bytes its header gives" % (what, total))
    end, str_end = off_st + size_st, off_str + size_str
    root, stack, pos = None, [], off_st

    def align(p):
        return off_st + ((p - off_st + 3) & ~3)

    while True:
        if pos + 4 > end:
            raise DtbError("its structure block ends without an end token")
        tok = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            name, pos = _cstr(data, pos, end)
            pos = align(pos)
            node = Node(name, stack[-1] if stack else None)
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                root = node
            else:
                raise DtbError("it has a second root node")
            stack.append(node)
        elif tok == FDT_END_NODE:
            if not stack:
                raise DtbError("a node ends that was never begun")
            stack.pop()
        elif tok == FDT_PROP:
            if not stack or pos + 8 > end:
                raise DtbError("a property lies outside every node")
            ln, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            if ln > end - pos:
                raise DtbError("a property runs past the structure block")
            val = bytes(data[pos:pos + ln])
            pos = align(pos + ln)
            if nameoff >= size_str:
                raise DtbError("a property's name lies outside the strings block")
            pname, _ = _cstr(data, off_str + nameoff, str_end)
            stack[-1].props[pname] = val
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            if stack:
                raise DtbError("it ends inside an open node")
            break
        else:
            raise DtbError("unknown token 0x%x in its structure block" % tok)
    if root is None:
        raise DtbError("it has no root node")
    return root


def cells(node, prop):
    v = node.props.get(prop)
    if v is None:
        raise TreeGap("%s has no %s" % (node.path(), prop))
    if len(v) % 4:
        raise TreeGap("%s: %s is %d bytes, not whole cells" % (node.path(), prop, len(v)))
    return list(struct.unpack(">%dI" % (len(v) // 4), v))


def number(cs):
    n = 0
    for c in cs:
        n = n << 32 | c
    return n


def addr_cells(node):
    return node.u32("#address-cells", 2)


def size_cells(node):
    return node.u32("#size-cells", 1)


def to_root(node, addr):
    """An address in node's parent bus, carried to the root through every bus's ranges."""
    bus = node.parent
    while bus.parent is not None:
        if "ranges" not in bus.props:
            raise TreeGap("%s: %s has no ranges, so the address cannot be carried to the root" % (node.path(), bus.path()))
        if bus.props["ranges"]:                       # an empty ranges is the identity
            ca, pa, sz = addr_cells(bus), addr_cells(bus.parent), size_cells(bus)
            cs = cells(bus, "ranges")
            if ca + pa + sz == 0 or len(cs) % (ca + pa + sz):
                raise TreeGap("%s: ranges is %d cells, not rows of %d" % (bus.path(), len(cs), ca + pa + sz))
            for i in range(0, len(cs), ca + pa + sz):
                child, parent = number(cs[i:i + ca]), number(cs[i + ca:i + ca + pa])
                if child <= addr < child + number(cs[i + ca + pa:i + ca + pa + sz]):
                    addr = addr - child + parent
                    break
            else:
                raise TreeGap("%s: no ranges row of %s covers 0x%x" % (node.path(), bus.path(), addr))
        bus = bus.parent
    return addr


def regions(node):
    """[(address at the root, size)] of a node's reg."""
    if node.parent is None:
        raise TreeGap("the root node has no reg")
    na, ns = addr_cells(node.parent), size_cells(node.parent)
    cs = cells(node, "reg")
    if not cs or na + ns == 0 or len(cs) % (na + ns):
        raise TreeGap("%s: reg is %d cells, not rows of %d" % (node.path(), len(cs), na + ns))
    return [(to_root(node, number(cs[i:i + na])), number(cs[i + na:i + na + ns])) for i in range(0, len(cs), na + ns)]


def spi_intid(node):
    """The INTID of a node's one interrupt, which must be a shared peripheral interrupt."""
    cs = cells(node, "interrupts")
    if len(cs) != 3:
        raise TreeGap("%s: interrupts is %d cells, not one <type number flags>" % (node.path(), len(cs)))
    if cs[0] != 0:
        raise TreeGap("%s: interrupts <%d %d %d> is not a shared peripheral interrupt (type 0)" % ((node.path(),) + tuple(cs)))
    return 32 + cs[1]


def having(root, compatible):
    return [n for n in root.walk() if compatible in n.strings("compatible")]


def the(root, compatible):
    found = having(root, compatible)
    if len(found) != 1:
        raise TreeGap("the tree has %s compatible with %s" % ("no node" if not found else "%d nodes" % len(found), compatible))
    return found[0]


def distributor(root):
    """(GICD base, size): the first reg row of the tree's GICv3."""
    return regions(the(root, "arm,gic-v3"))[0]


def redistributors(root):
    """(GICR base, size): the second reg row, when the tree has the one region the startup hands on."""
    node = the(root, "arm,gic-v3")
    regs, count = regions(node), node.u32("#redistributor-regions", 1)
    if count != 1 or len(regs) < 2:
        raise TreeGap("%s has %d redistributor regions; the startup gives the library one" % (node.path(), min(count, len(regs) - 1)))
    return regs[1]


def pci_host(root):
    """((ECAM base, size), the first bus, [(PCI address, CPU address, size)] of its 32-bit memory ranges)."""
    node = the(root, "pci-host-ecam-generic")
    ecam = regions(node)[0]
    first_bus = 0                                     # the binding's default when there is no bus-range
    if "bus-range" in node.props:
        buses = cells(node, "bus-range")
        if len(buses) != 2:
            raise TreeGap("%s: bus-range is %d cells, not <first last>" % (node.path(), len(buses)))
        first_bus = buses[0]
    ca, pa, sz = addr_cells(node), addr_cells(node.parent), size_cells(node)
    cs = cells(node, "ranges")
    if ca != 3 or len(cs) % (ca + pa + sz):
        raise TreeGap("%s: ranges is %d cells and #address-cells %d, not PCI rows of %d" % (node.path(), len(cs), ca, 3 + pa + sz))
    mem32 = []
    for i in range(0, len(cs), ca + pa + sz):
        if (cs[i] >> 24) & 3 == 2:                    # the space code of a 32-bit memory range
            mem32.append((number(cs[i + 1:i + ca]), number(cs[i + ca:i + ca + pa]), number(cs[i + ca + pa:i + ca + pa + sz])))
    return ecam, first_bus, mem32


def transports(root):
    """[(base, size, INTID)] of every virtio,mmio node, by address."""
    found = having(root, "virtio,mmio")
    if not found:
        raise TreeGap("the tree has no node compatible with virtio,mmio")
    return sorted(regions(n)[0] + (spi_intid(n),) for n in found)


def ram_base(root):
    bases = [r[0] for n in root.walk() if n.strings("device_type") == ["memory"] for r in regions(n)]
    if not bases:
        raise TreeGap("the tree has no node with device_type memory")
    return min(bases)


def fact(fn, *args):
    """fn's value, or the TreeGap it raised: a comparison prints the gap as its mismatch."""
    try:
        return fn(*args)
    except TreeGap as e:
        return e


def part(value, *index):
    for i in index:
        if isinstance(value, TreeGap):
            break
        value = value[i]
    return value


# ------------------------------------------------------------------ the sources

def read_text(repo, rel):
    try:
        with open(os.path.join(repo, *rel.split("/")), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise SourceError("%s: %s" % (rel, e.strerror or e))


def strip_c_comments(text):
    """C text with every comment blanked and every newline kept, so a match's line number holds."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _line(text, at):
    return text.count("\n", 0, at) + 1


def c_int(literal):
    m = re.match(r"^(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*$", literal)
    if not m:
        return None
    digits = m.group(1)
    if digits[:2] in ("0x", "0X"):
        return int(digits, 16)
    return int(digits, 8 if len(digits) > 1 and digits[0] == "0" else 10)


def c_defines(rel, text, names):
    """{name: Const} for the one `#define name <integer>` each name has in a C file."""
    code, out = strip_c_comments(text), {}
    for name in names:
        found = list(re.finditer(r"(?m)^[ \t]*#[ \t]*define[ \t]+%s[ \t]+(\S+)[ \t]*$" % re.escape(name), code))
        if len(found) != 1:
            raise SourceError("%s: %s is defined %d times as one word; once is expected" % (rel, name, len(found)))
        value = c_int(found[0].group(1))
        if value is None:
            raise SourceError("%s:%d: %s is %s, not one integer" % (rel, _line(code, found[0].start()), name, found[0].group(1)))
        out[name] = Const(value, "%s:%d %s" % (rel, _line(code, found[0].start()), name))
    return out


def c_once(rel, text, pattern, what):
    """The one match of pattern in a C file's code, and its line."""
    code = strip_c_comments(text)
    found = list(re.finditer(pattern, code))
    if len(found) != 1:
        raise SourceError("%s: %s is there %d times; once is expected" % (rel, what, len(found)))
    return found[0], _line(code, found[0].start())


def _py_value(node, env):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_py_value(e, env) for e in node.elts]
    raise ValueError(ast.dump(node))


def report_constants(rel, text):
    """(CONSOLE_VIRTIO as a Const, {row name: [Const((base, size))]}) from mmio_report.py's module-level
    assignments. The file is parsed, never run: a name in a row is looked up among the integers
    assigned above it."""
    try:
        module = ast.parse(text, filename=rel)
    except SyntaxError as e:
        raise SourceError("%s: not Python this interpreter can parse (%s)" % (rel, e.msg))
    env, seen = {}, collections.Counter()
    console, fixed = None, None
    for node in module.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        seen[name] += 1
        try:
            value = _py_value(node.value, env)
        except ValueError:
            env.pop(name, None)
            continue
        env[name] = value
        if name == "CONSOLE_VIRTIO" and isinstance(value, int):
            console = Const(value, "%s:%d CONSOLE_VIRTIO" % (rel, node.lineno))
        elif name == "FIXED" and isinstance(value, list):
            fixed = collections.OrderedDict()
            for row, at in zip(value, node.value.elts):
                if not (isinstance(row, list) and len(row) == 3 and isinstance(row[0], str)
                        and isinstance(row[1], int) and isinstance(row[2], int)):
                    raise SourceError("%s:%d: a FIXED row is not (name, base, size)" % (rel, at.lineno))
                fixed.setdefault(row[0], []).append(Const((row[1], row[2]), "%s:%d FIXED %s" % (rel, at.lineno, row[0])))
    for name, got in (("CONSOLE_VIRTIO", console), ("FIXED", fixed)):
        if got is None or seen[name] != 1:
            raise SourceError("%s: %s is assigned %d times as plain integers at module level; once is expected" % (rel, name, seen[name]))
    for name in REPORT_ROWS:
        if name not in fixed or (name != "ECAM" and len(fixed[name]) != 1):
            raise SourceError("%s: FIXED has %d rows named %s" % (rel, len(fixed.get(name, ())), name))
    return console, fixed


def run_lines(repo, command):
    """[(file, line number, the words after the command word)] of every line of an image build
    file that runs command. The line is found by the command word, wherever it stands (the module
    docstring has the rule): a build file that runs the command by its path, behind an attribute
    or through `on` is read like one that runs it bare, and is never passed over. A line that
    names the command and not as a word is none this rule finds, and stops the script."""
    glued = re.compile(r"(?<![\w.-])%s(?![\w./-])" % re.escape(command))
    out = []
    for path in sorted(glob.glob(os.path.join(repo, *BUILD_GLOB.split("/")))):
        rel = os.path.relpath(path, repo).replace(os.sep, "/")
        for n, line in enumerate(read_text(repo, rel).splitlines(), 1):
            words = line.split()
            if not words or words[0].startswith("#"):
                continue
            at = [i for i, w in enumerate(words) if w.rsplit("/", 1)[-1] == command]
            if not at and glued.search(line):
                raise SourceError("%s:%d: the line names %s, and not as a word of its own (bare or by a path): it cannot be read as "
                                  "the line that runs it, and it is not a line to skip" % (rel, n, command))
            if not at or at[0] == len(words) - 1:     # not named, or named with nothing after it: the file list
                continue
            out.append((rel, n, words[at[0] + 1:]))
    return out


def console_lines(repo):
    """[Const((location, interrupt))] of every line of an image build file that starts the
    console's driver."""
    out = []
    for rel, n, after in run_lines(repo, CONSOLE_DRIVER):
        rest = [w.rstrip("&") for w in after]
        rest = [w for w in rest if w]
        m = re.match(r"^(0[xX][0-9a-fA-F]+),([0-9]+)$", rest[-1]) if rest else None
        if not m:
            raise SourceError("%s:%d: %s is named with words after it, which is read as the line that starts it, and the line "
                              "does not end in LOCATION,INTERRUPT" % (rel, n, CONSOLE_DRIVER))
        out.append(Const((int(m.group(1), 16), int(m.group(2))), "%s:%d %s" % (rel, n, CONSOLE_DRIVER)))
    if not out:
        raise SourceError("no file matching %s starts %s: the console slot would be compared with nothing" % (BUILD_GLOB, CONSOLE_DRIVER))
    return out


def rtc_lines(repo):
    """[Const(address)] of every line of an image build file that runs rtc: the address its
    option gives it, which on this machine is the PL031's."""
    out = []
    for rel, n, after in run_lines(repo, RTC_COMMAND):
        at = [i for i, w in enumerate(after) if w == RTC_BASE]
        m = re.match(r"^0[xX][0-9a-fA-F]+$", after[at[0] + 1]) if len(at) == 1 and at[0] + 1 < len(after) else None
        if not m or any(w.startswith("#") for w in after):
            raise SourceError("%s:%d: %s is named with words after it, which is read as the line that runs it, and the line does not "
                              "give one %s ADDRESS (the option once, a hexadecimal address as its next word, no comment after the "
                              "command)" % (rel, n, RTC_COMMAND, RTC_BASE))
        out.append(Const(int(m.group(0), 16), "%s:%d %s %s" % (rel, n, RTC_COMMAND, RTC_BASE)))
    if not out:
        raise SourceError("no file matching %s runs %s with %s ADDRESS: the PL031's base would be compared with nothing" % (
            BUILD_GLOB, RTC_COMMAND, RTC_BASE))
    return out


Sources = collections.namedtuple("Sources", "header uart_debug psci shm its console fixed build rtc")


def read_sources(repo):
    header = c_defines(HEADER, read_text(repo, HEADER), HEADER_NAMES)
    main_c = read_text(repo, MAIN_C)
    # The library's debug-device string, "base^shift.reserved.clk.baud".
    m, at = c_once(MAIN_C, main_c, r'"(0[xX][0-9a-fA-F]+)\^[0-9]+\.[^"\n]*"', "a debug device string (\"base^shift...\")")
    uart_debug = Const(int(m.group(1), 16), "%s:%d debug device" % (MAIN_C, at))
    # What main.c tells the reader the probe wants, in the message it stops with when the probe fails.
    m, at = c_once(MAIN_C, main_c, r'expected compatible \\"([^"\\\n]+)\\"', "the message that names the PSCI compatible string")
    psci = Const(m.group(1), "%s:%d PSCI compatible" % (MAIN_C, at))
    shm = c_defines(SHM_C, read_text(repo, SHM_C), PCI_NAMES)
    its = c_defines(ITS_C, read_text(repo, ITS_C), PCI_NAMES)
    console, fixed = report_constants(REPORT, read_text(repo, REPORT))
    return Sources(header, uart_debug, psci, shm, its, console, fixed, console_lines(repo), rtc_lines(repo))


# ------------------------------------------------------------------ the comparison

def hexa(v):
    return "0x%x" % v


def region_text(r):
    return "0x%x (0x%x bytes)" % r


class Verdict:
    def __init__(self):
        self.lines, self.bad = [], 0

    def add(self, ok, what, text):
        self.bad += not ok
        self.lines.append("%-9s %s: %s" % ("ok" if ok else "MISMATCH", what, text))

    def equal(self, what, got, const, show=hexa):
        """The tree's value against one constant of one file."""
        if isinstance(got, TreeGap):
            self.add(False, what, "%s; %s is %s" % (got, const.where, show(const.value)))
        elif got == const.value:
            self.add(True, what, "%s = %s" % (show(got), const.where))
        else:
            self.add(False, what, "the tree has %s; %s is %s" % (show(got), const.where, show(const.value)))

    def one_of(self, what, got, consts, show=region_text):
        """The tree's value against rows of which one has to be it."""
        listed = ", ".join("%s is %s" % (c.where, show(c.value)) for c in consts)
        hit = [c for c in consts if not isinstance(got, TreeGap) and c.value == got]
        if hit:
            self.add(True, what, "%s = %s" % (show(got), hit[0].where))
        else:
            self.add(False, what, "%s; %s" % (got if isinstance(got, TreeGap) else "the tree has %s" % show(got), listed))


def compare(root, src, v):
    h, fx = src.header, src.fixed

    gicd, gicr = fact(distributor, root), fact(redistributors, root)
    v.equal("GICD base", part(gicd, 0), h["QV_GICD_BASE"])
    v.equal("GICD region", gicd, fx["GICD"][0], region_text)
    v.equal("GICR base", part(gicr, 0), h["QV_GICR_BASE"])
    v.equal("GICR size", part(gicr, 1), h["QV_GICR_SIZE"])
    v.equal("GICR region", gicr, fx["GICR"][0], region_text)

    gits = fact(lambda: regions(the(root, "arm,gic-v3-its"))[0])
    v.equal("GITS base", part(gits, 0), h["QV_GITS_BASE"])
    v.equal("GITS region", gits, fx["GITS"][0], region_text)

    uart = fact(lambda: regions(the(root, "arm,pl011"))[0])
    v.equal("PL011 base", part(uart, 0), h["QV_PL011_BASE"])
    v.equal("PL011 base", part(uart, 0), src.uart_debug)
    v.equal("PL011 region", uart, fx["UART"][0], region_text)
    v.equal("PL011 interrupt", fact(lambda: spi_intid(the(root, "arm,pl011"))), h["QV_PL011_IRQ"], str)

    v.equal("RAM base", fact(ram_base, root), h["QV_RAM_BASE"])

    pci = fact(pci_host, root)
    ecam, first_bus, mem32 = part(pci, 0), part(pci, 1), part(pci, 2)
    if not isinstance(mem32, TreeGap) and len(mem32) != 1:
        mem32 = TreeGap("the tree's PCI host has %d 32-bit memory ranges" % len(mem32))
    v.one_of("ECAM region", ecam, fx["ECAM"])
    for c in (src.shm, src.its):
        v.equal("ECAM base", part(ecam, 0), c["ECAM_BASE"])
        bus0 = c["ECAM_BUS0_BYTES"]
        if isinstance(pci, TreeGap):
            v.add(False, "ECAM bus 0", "%s; %s is %s" % (pci, bus0.where, hexa(bus0.value)))
        elif first_bus != 0:
            v.add(False, "ECAM bus 0", "the tree's bus-range starts at bus %d; %s maps bus 0 at the ECAM's base" % (first_bus, bus0.where))
        elif ecam[1] < bus0.value:
            v.add(False, "ECAM bus 0", "the tree's ECAM is %s bytes; %s maps %s" % (hexa(ecam[1]), bus0.where, hexa(bus0.value)))
        else:
            v.add(True, "ECAM bus 0", "bus-range starts at 0 and the ECAM's %s bytes hold %s (%s)" % (hexa(ecam[1]), bus0.where, hexa(bus0.value)))
        v.equal("MMIO32 window, PCI address", part(mem32, 0, 0), c["MMIO32_BASE"])
        v.equal("MMIO32 window, CPU address", part(mem32, 0, 1), c["MMIO32_BASE"])
        v.equal("MMIO32 window, size", part(mem32, 0, 2), c["MMIO32_SIZE"])

    slots = fact(transports, root)
    row = fx["virtio"][0]
    if isinstance(slots, TreeGap):
        v.add(False, "virtio-mmio span", "%s; %s is %s" % (slots, row.where, region_text(row.value)))
        v.add(False, "virtio-mmio interrupts", str(slots))
        by_base = slots
    else:
        tiled = all(a[0] + a[1] == b[0] for a, b in zip(slots, slots[1:]))
        span = (slots[0][0], slots[-1][0] + slots[-1][1] - slots[0][0])
        if tiled and span == row.value:
            v.add(True, "virtio-mmio span", "%d transports tile %s = %s" % (len(slots), region_text(span), row.where))
        else:
            v.add(False, "virtio-mmio span", "the tree's %d transports %s %s; %s is %s" % (
                len(slots), "tile" if tiled else "leave gaps or overlap inside", region_text(span), row.where,
                region_text(row.value)))
        jump = [(a, b) for a, b in zip(slots, slots[1:]) if b[2] != a[2] + 1]
        if jump:
            v.add(False, "virtio-mmio interrupts", "they do not rise by one from slot to slot: %s takes INTID %d and %s takes %d" % (
                hexa(jump[0][0][0]), jump[0][0][2], hexa(jump[0][1][0]), jump[0][1][2]))
        else:
            v.add(True, "virtio-mmio interrupts", "INTID %d to %d, rising by one from slot to slot" % (slots[0][2], slots[-1][2]))
        by_base = {s[0]: s for s in slots}

    def slot(base):
        if isinstance(by_base, TreeGap):
            return by_base
        if base not in by_base:
            return TreeGap("the tree has no virtio-mmio transport at %s" % hexa(base))
        return by_base[base]

    row = fx["console"][0]
    v.equal("console transport", part(slot(row.value[0]), slice(0, 2)), row, region_text)
    for line in src.build:
        location, interrupt = line.value
        v.equal("console slot %s, interrupt" % hexa(location), part(slot(location), 2), Const(interrupt, line.where), str)
    named = sorted({line.value[0] for line in src.build})
    if named == [src.console.value]:
        v.add(True, "console slot", "%s %s is the slot of the %d devc-virtio lines" % (src.console.where, hexa(src.console.value), len(src.build)))
    else:
        other = next(line for line in src.build if line.value[0] != src.console.value)
        v.add(False, "console slot", "%s is %s; %s names %s" % (src.console.where, hexa(src.console.value), other.where, hexa(other.value[0])))

    clock = fact(lambda: regions(the(root, "arm,pl031"))[0])
    for line in src.rtc:
        v.equal("PL031 base", part(clock, 0), line)

    want = src.psci
    nodes = [n for n in root.walk() if any(s.startswith(want.value) for s in n.strings("compatible"))]
    listed = ", ".join('"%s"' % s for n in nodes[:1] for s in n.strings("compatible"))
    if len(nodes) != 1:
        v.add(False, "PSCI compatible", "the tree has %s whose compatible list names %s; %s wants \"%s\"" % (
            "no node" if not nodes else "%d nodes" % len(nodes), want.value, want.where, want.value))
    elif nodes[0].strings("compatible")[-1] == want.value:
        v.add(True, "PSCI compatible", "%s ends in %s \"%s\"" % (listed, want.where, want.value))
    else:
        v.add(False, "PSCI compatible", "the tree's list is %s; it does not end in \"%s\" (%s)" % (listed, want.value, want.where))


def stopped(where):
    """Exit status 2 for a stop this script did not foresee, in any of its three steps. Left to
    Python, such a stop would end in status 1, which is kept for "compared, and it differs"."""
    traceback.print_exc()
    print("check_virt_dtb: stopped %s (above); nothing is concluded" % where, file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dtb", metavar="FILE.dtb", help="a device tree written by QEMU's dumpdtb")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    help="the checkout whose files hold the constants (default: the one this script is in)")
    a = ap.parse_args(argv)
    try:
        with open(a.dtb, "rb") as f:
            root = parse_dtb(f.read())
    except (OSError, DtbError) as e:
        print("check_virt_dtb: %s: %s; nothing was compared" % (a.dtb, e.strerror if isinstance(e, OSError) else e), file=sys.stderr)
        return 2
    except Exception:
        return stopped("while reading the device tree")
    try:
        src = read_sources(a.repo)
    except SourceError as e:
        print("check_virt_dtb: %s; nothing was compared" % e, file=sys.stderr)
        return 2
    except Exception:
        return stopped("while reading the sources")
    v = Verdict()
    try:
        compare(root, src, v)
    except Exception:
        # A tree this script's walk did not foresee.
        return stopped("inside the comparison")
    print("\n".join(v.lines))
    if v.bad:
        print("check_virt_dtb: %d of %d comparisons do not match: %s against the sources under %s" % (v.bad, len(v.lines), a.dtb, a.repo))
        return 1
    print("check_virt_dtb: %d comparisons, every one agrees: %s against the sources under %s" % (len(v.lines), a.dtb, a.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
