"""orin-native/tools/check_virt_dtb.py against device trees built here (Phase 3b / A6, 2026-10-05).

The tool compares the device tree QEMU's virt machine generates with the addresses and interrupts
of that machine that the A6 guest's sources in this repo hold as constants, and it reads each
constant from the file that holds it. Three things are tested: a tree with the repo's values
passes; a tree that differs in one place fails and names the place, the file and the constant;
and the verdict follows the sources (a changed copy of a source in a temporary tree changes it,
and a tree and a set of sources moved together still agree), so the tool cannot be carrying a
second copy of any constant. A fourth, because a build file can run a command in more than one
way. Two of its lines hold an address of the machine: the one that starts the console's driver
and the one that gives rtc the clock's. Each is read in every form in which the command is a word
of the line (bare, by a path, behind an attribute, through `on`), and a build file that names the
command in any other way is not passed over: the tool stops on that line (exit 2).

No dump of a real QEMU is in the repo, and none is read here: every tree is written by the small
FDT writer below. Its shape is the virt machine's (the node names, the bindings, two address and
two size cells at the root, the PCI host's seven-cell ranges rows). The addresses and interrupts
in MAP are the virt machine's map as this repo's sources hold it, typed here by hand so that the
first test also pins what the tool reads out of the real files. Everything else is made up: the
phandles, the RAM size, the clock, the seeds, the RTC's size and its interrupt. MOVED is a second
map that is made up throughout.

What these tests do NOT show: that a real QEMU's tree passes (that is a run on the board), that
the reader copes with every tree a QEMU could write, or anything about a guest.
"""
import contextlib
import functools
import glob
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tokenize

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "orin-native", "tools")
TOOL = os.path.join(TOOLS, "check_virt_dtb.py")
sys.path.insert(0, TOOLS)
import check_virt_dtb as tool  # noqa: E402

HEADER, MAIN_C, SHM_C, ITS_C, REPORT = tool.SOURCES
KICK_BUILD = "ipc-test/qnx-safety-monitor/ifs-kick.build"

# QEMU virt's map as the repo's sources hold it (see the module docstring), and a tree's other values.
MAP: dict = dict(
    gicd=(0x08000000, 0x10000), gicr=(0x080A0000, 0xF60000), its=(0x08080000, 0x20000),
    uart=(0x09000000, 0x1000), uart_irq=(0, 1, 4), rtc=(0x09010000, 0x1000), ram=(0x40000000, 0x30000000),
    ecam=(0x4010000000, 0x10000000), bus_range=(0, 255), mmio32=(0x10000000, 0x10000000, 0x2EFF0000),
    virtio=(0x0A000000, 0x200, 32), virtio_spi=16, psci=("arm,psci-1.0", "arm,psci-0.2", "arm,psci"))
CONSOLE, CONSOLE_INTID = 0x0A003800, 76
RTC = MAP["rtc"][0]


def _text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def names_the_driver(text):
    """The lines of a build file that name the console's driver outside a comment line."""
    return [ln for ln in text.splitlines() if "devc-virtio" in ln and not ln.lstrip().startswith("#")]


# The image build files that have to come out of the tool as one comparison each, found here by a
# search of their own, so that an image added later is one more comparison and no edit to these
# tests. The rule is NOT the tool's, on purpose. The tool looks for a line that starts the driver;
# this takes every build file that names the driver at all outside a comment (its start line, or
# only the file list's entry). So a build file that starts the driver in a form the tool does not
# read, or ships it and never starts it, fails the first test below and is not passed over.
BUILDS_WITH_CONSOLE = sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                             for p in glob.glob(os.path.join(REPO, "ipc-test", "*", "*.build"))
                             if names_the_driver(_text(p)))
CONSOLE_LINES = len(BUILDS_WITH_CONSOLE)
# The start line as every one of those files writes it today (the tests below rewrite it).
START = r"^devc-virtio -u 2 0xa003800,76 &$"


def names_rtc(text):
    """The lines of a build file that name rtc outside a comment line: the three letters with no
    letter, digit or underscore on either side."""
    return [ln for ln in text.splitlines() if "rtc" in re.split(r"[^A-Za-z0-9_]+", ln) and not ln.lstrip().startswith("#")]


# The same for the line that gives rtc the clock's address: every build file that names rtc at
# all outside a comment (the line that runs it, or only the file list's entry) has to come out
# of the tool as one comparison. Again a search of this file's own, and wider than the tool's.
BUILDS_WITH_RTC = sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                         for p in glob.glob(os.path.join(REPO, "ipc-test", "*", "*.build"))
                         if names_rtc(_text(p)))
RTC_LINES = len(BUILDS_WITH_RTC)
# The line as every one of those files writes it today, inside its start script.
RTC_RUN = r"^    rtc -b 0x9010000 primecell$"


# ------------------------------------------------------------------ a small FDT writer

def _u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def _u64(*v):
    return b"".join(struct.pack(">Q", x) for x in v)


def _s(*strs):
    return b"".join(x.encode("latin-1") + b"\0" for x in strs)


def fdt(tree, version=17, magic=0xD00DFEED, last_comp=16, nops=False, tail=b""):
    """A flattened device tree from (name, [(property, bytes)], [children]). nops puts a NOP
    token before every property and before every node's end; tail goes in after the root's end."""
    strings, offs, st = bytearray(), {}, bytearray()

    def soff(name):
        if name not in offs:
            offs[name] = len(strings)
            strings.extend(name.encode("latin-1") + b"\0")
        return offs[name]

    def pad():
        while len(st) % 4:
            st.append(0)

    def emit(node):
        name, props, kids = node
        st.extend(_u32(1))
        st.extend(name.encode("latin-1") + b"\0")
        pad()
        for pn, pv in props:
            st.extend(_u32(4) if nops else b"")
            st.extend(_u32(3, len(pv), soff(pn)))
            st.extend(pv)
            pad()
        for k in kids:
            emit(k)
        st.extend(_u32(4) if nops else b"")
        st.extend(_u32(2))

    emit(tree)
    st.extend(tail)
    st.extend(_u32(9))
    off_st = 40 + 16
    off_str = off_st + len(st)
    head = struct.pack(">10I", magic, off_str + len(strings), off_st, off_str, 40, version, last_comp, 0, len(strings), len(st))
    return head + _u64(0, 0) + bytes(st) + bytes(strings)


def virt(gicd=MAP["gicd"], gicr=MAP["gicr"], gicr2=None, its=MAP["its"], gic_compat="arm,gic-v3", uart=MAP["uart"],
         uart_irq=MAP["uart_irq"], ram=MAP["ram"], ecam=MAP["ecam"], bus_range=MAP["bus_range"], mmio32=MAP["mmio32"],
         virtio=MAP["virtio"], virtio_spi=MAP["virtio_spi"], virtio_swap=None, virtio_skip=None, descending=False, psci=MAP["psci"],
         its_ranges=b"", its_reg=None, root_cells=(2, 2), ram2=None, uart2=None, psci2=None, mmio32_more=(), rtc=MAP["rtc"],
         rtc2=None, pci_cells=(3, 2)):
    """A tree of the virt machine's shape. The phandles, the clock, the seeds and the RTC's
    interrupt are made up. its_ranges=None and bus_range=None leave the property out; gicr=None
    leaves the GIC node its distributor's row only; uart2, rtc2 and psci2 add a second node of the
    same binding; mmio32_more adds ranges rows (space code, PCI address, CPU address, size);
    pci_cells are the PCI host's own address and size cells, with its rows left as they are."""
    gic_ph, its_ph, clk_ph = 0x71, 0x72, 0x70
    kids = []
    for name, compat in (("psci", psci), ("psci-b", psci2)):
        if compat:
            kids.append((name, [("migrate", _u32(0xC4000005)), ("cpu_on", _u32(0xC4000003)), ("cpu_off", _u32(0x84000002)),
                                ("cpu_suspend", _u32(0xC4000001)), ("method", _s("hvc")), ("compatible", _s(*compat))], []))
    for r in (ram2, ram):                              # the higher node first, when there are two
        if r:
            kids.append(("memory@%x" % r[0], [("reg", _u64(*r)), ("device_type", _s("memory"))], []))
    base, size, count = virtio
    spis = [virtio_spi + i for i in range(count)]
    if virtio_swap:
        a, b = virtio_swap
        spis[a], spis[b] = spis[b], spis[a]
    slots = [("virtio_mmio@%x" % (base + i * size),
              [("dma-coherent", b""), ("interrupts", _u32(0, spis[i], 1)), ("reg", _u64(base + i * size, size)),
               ("compatible", _s("virtio,mmio"))], []) for i in range(count)]
    if virtio_skip is not None:
        del slots[virtio_skip]
    kids += reversed(slots) if descending else slots
    ranges = _u32(0x01000000, 0, 0) + _u64(0x3EFF0000, 0x10000)
    if mmio32:
        ranges += _u32(0x02000000) + _u64(*mmio32)
    for row in mmio32_more:
        ranges += _u32(row[0]) + _u64(*row[1:])
    ranges += _u32(0x03000000) + _u64(0x8000000000, 0x8000000000, 0x8000000000)
    buses = [("bus-range", _u32(*bus_range))] if bus_range is not None else []
    kids.append(("pcie@10000000", [("ranges", ranges), ("reg", _u64(*ecam)), ("msi-map", _u32(0, its_ph, 0, 0x10000)),
                                   ("dma-coherent", b"")] + buses + [("linux,pci-domain", _u32(0)),
                                   ("#size-cells", _u32(pci_cells[1])), ("#address-cells", _u32(pci_cells[0])),
                                   ("device_type", _s("pci")), ("compatible", _s("pci-host-ecam-generic"))], []))
    for r in (rtc, rtc2):
        if r:
            kids.append(("pl031@%x" % r[0], [("clock-names", _s("apb_pclk")), ("clocks", _u32(clk_ph)), ("interrupts", _u32(0, 9, 4)),
                                             ("reg", _u64(*r)), ("compatible", _s("arm,pl031", "arm,primecell"))], []))
    for u in (uart, uart2):
        if u:
            kids.append(("pl011@%x" % u[0], [("clock-names", _s("uartclk", "apb_pclk")), ("clocks", _u32(clk_ph, clk_ph)),
                                             ("interrupts", _u32(*uart_irq)), ("reg", _u64(*u)),
                                             ("compatible", _s("arm,pl011", "arm,primecell"))], []))
    its_node = []
    if its:
        its_node = [("its@%x" % its[0], [("phandle", _u32(its_ph)), ("reg", its_reg or _u64(*its)), ("#msi-cells", _u32(1)),
                                         ("msi-controller", b""), ("compatible", _s("arm,gic-v3-its"))], [])]
    gic_ranges = [("ranges", its_ranges)] if its_ranges is not None else []
    kids.append(("intc@%x" % gicd[0],
                 [("phandle", _u32(gic_ph)), ("reg", _u64(*gicd) + (_u64(*gicr) if gicr else b"") + (_u64(*gicr2) if gicr2 else b"")),
                  ("#redistributor-regions", _u32(2 if gicr2 else 1)), ("compatible", _s(gic_compat))] + gic_ranges +
                 [("#size-cells", _u32(2)), ("#address-cells", _u32(2)), ("interrupt-controller", b""),
                  ("#interrupt-cells", _u32(3))], its_node))
    kids.append(("cpus", [("#size-cells", _u32(0)), ("#address-cells", _u32(1))],
                 [("cpu@%d" % k, [("reg", _u32(k)), ("enable-method", _s("psci")), ("compatible", _s("arm,arm-v8")),
                                  ("device_type", _s("cpu"))], []) for k in range(2)]))
    kids.append(("timer", [("interrupts", _u32(1, 13, 4, 1, 14, 4, 1, 11, 4, 1, 10, 4)), ("always-on", b""),
                           ("compatible", _s("arm,armv8-timer", "arm,armv7-timer"))], []))
    kids.append(("apb-pclk", [("phandle", _u32(clk_ph)), ("clock-frequency", _u32(24000000)), ("#clock-cells", _u32(0)),
                              ("compatible", _s("fixed-clock"))], []))
    kids.append(("chosen", [("stdout-path", _s("/pl011@%x" % uart[0])), ("rng-seed", bytes(range(32))),
                            ("kaslr-seed", bytes(range(8)))], []))
    return ("", [("interrupt-parent", _u32(gic_ph)), ("model", _s("made-up,virt")), ("#size-cells", _u32(root_cells[1])),
                 ("#address-cells", _u32(root_cells[0])), ("compatible", _s("made-up,virt"))], kids)


def with_prop(tree, node, prop, value):
    """The tree with one property of one node given other bytes. node is the node's name before
    its unit address ("" is the root)."""
    name, props, kids = tree
    if name.split("@")[0] == node:
        assert [p for p, _v in props].count(prop) == 1, (node, prop)
        props = [(p, value if p == prop else v) for p, v in props]
    return name, props, [with_prop(k, node, prop, value) for k in kids]


def write(tmp_path, blob, name="virt.dtb"):
    p = tmp_path / name
    p.write_bytes(blob)
    return str(p)


def run(dtb, repo=REPO):
    """(exit status, stdout, stderr) of the tool's main(), run in this process."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = tool.main([dtb, "--repo", str(repo)])
    return rc, out.getvalue(), err.getvalue()


def mismatches(out):
    return [ln for ln in out.splitlines() if ln.startswith("MISMATCH")]


def said(rc, bad, want=None):
    """What a failed assertion prints first: the status, the count, and the MISMATCH lines."""
    return "exit %d with %d MISMATCH lines%s:%s" % (rc, len(bad), "" if want is None else " where %d are expected" % want,
                                                    "".join("\n  " + ln for ln in bad))


def verdict(tmp_path, repo=REPO, tree=None, **changes):
    """The tool on a tree built with these changes, or on the tree given: (exit status, MISMATCH
    lines, all of stdout)."""
    rc, out, err = run(write(tmp_path, fdt(virt(**changes) if tree is None else tree)), repo)
    bad = mismatches(out)
    # Whatever else a test asserts: the exit status and the printed lines never disagree.
    assert rc in (0, 1) and err == "", (rc, err)
    assert (rc == 0) == (not bad), "exit %d with %d MISMATCH lines" % (rc, len(bad))
    last = out.splitlines()[-1]
    if bad:
        assert last.startswith("check_virt_dtb: %d of %d comparisons do not match" % (len(bad), len(out.splitlines()) - 1)), last
    else:
        assert "every one agrees" in last and all(ln.startswith("ok ") for ln in out.splitlines()[:-1]), out
    return rc, bad, out


# ------------------------------------------------------------------ a tree with the repo's values passes

@pytest.mark.parametrize("changes", [
    {},
    {"descending": True},
    {"psci": ("arm,psci-0.2", "arm,psci")},
    {"ram": (MAP["ram"][0], 0x80000000)},
    {"ram2": (0x100000000, 0x40000000)},
    {"bus_range": None},
    {"rtc": (RTC, 0x2000)},
], ids=["as built", "transports listed from the top", "the shorter PSCI list", "another RAM size", "a second memory node above",
        "no bus-range (the binding's default is bus 0)", "another PL031 size (the repo holds its base only)"])
def test_a_tree_with_the_repos_values_passes(tmp_path, changes):
    rc, bad, out = verdict(tmp_path, **changes)
    assert rc == 0 and not bad, said(rc, bad, 0)
    for rel in tool.SOURCES:
        assert rel + ":" in out, "no comparison names %s" % rel
    # Every image build file that names the console's driver is one comparison, by its own line:
    # exactly one each, and no comparison besides (BUILDS_WITH_CONSOLE is this file's own search).
    assert KICK_BUILD in BUILDS_WITH_CONSOLE, BUILDS_WITH_CONSOLE
    for b in BUILDS_WITH_CONSOLE:
        assert out.count("console slot 0x%x, interrupt: %d = %s:" % (CONSOLE, CONSOLE_INTID, b)) == 1, b
    assert out.count("console slot 0x%x, interrupt" % CONSOLE) == CONSOLE_LINES
    # And every one that names rtc is one comparison of the PL031's base, by its own line.
    assert KICK_BUILD in BUILDS_WITH_RTC, BUILDS_WITH_RTC
    for b in BUILDS_WITH_RTC:
        assert out.count("PL031 base: 0x%x = %s:" % (RTC, b)) == 1, b
    assert out.count("PL031 base") == RTC_LINES


def test_nop_tokens_in_a_tree_are_read_past(tmp_path):
    """A tree that was edited in place carries NOP tokens where a property or a node was."""
    rc, out, _err = run(write(tmp_path, fdt(virt(), nops=True)))
    assert rc == 0, said(rc, mismatches(out), 0)
    assert out == verdict(tmp_path)[2]


def test_a_comparison_names_the_line_the_constant_is_on(tmp_path):
    _rc, _bad, out = verdict(tmp_path)

    def line_of(rel, needle):
        with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8", errors="replace") as f:
            hits = [n for n, ln in enumerate(f, 1) if ln.startswith(needle)]
        assert len(hits) == 1, (rel, needle, hits)
        return hits[0]

    assert "%s:%d QV_RAM_BASE" % (HEADER, line_of(HEADER, "#define QV_RAM_BASE")) in out
    assert "%s:%d MMIO32_SIZE" % (ITS_C, line_of(ITS_C, "#define MMIO32_SIZE")) in out
    assert "%s:%d FIXED GITS" % (REPORT, line_of(REPORT, '    ("GITS",')) in out
    assert "%s:%d CONSOLE_VIRTIO" % (REPORT, line_of(REPORT, "CONSOLE_VIRTIO =")) in out
    assert "%s:%d devc-virtio" % (KICK_BUILD, line_of(KICK_BUILD, "devc-virtio ")) in out
    assert "%s:%d rtc -b" % (KICK_BUILD, line_of(KICK_BUILD, "    rtc ")) in out
    assert "%s:%d debug device" % (MAIN_C, line_of(MAIN_C, '\t\t{ "0x')) in out


# ------------------------------------------------------------------ a tree that differs fails and names it

EVERY_BUILD_LINE = ["devc-virtio"] * CONSOLE_LINES
TREES = [
    # id, the change, how many comparisons fail, what the MISMATCH lines name (each at least once)
    ("the ECAM moved", {"ecam": (0x4020000000, 0x10000000)}, 3, ["ECAM region", REPORT, SHM_C + ":", ITS_C + ":", "ECAM_BASE"]),
    ("the ECAM moved by a whole number of 4 GiB", {"ecam": (0x5010000000, 0x10000000)}, 3, ["ECAM region", "ECAM base", "ECAM_BASE"]),
    ("the ECAM without highmem", {"ecam": (0x3F000000, 0x1000000)}, 2, ["ECAM base", SHM_C + ":", ITS_C + ":"]),
    ("the ECAM's buses start at 1", {"bus_range": (1, 255)}, 2, ["ECAM bus 0", "ECAM_BUS0_BYTES", "bus 1"]),
    ("the ECAM too small for bus 0", {"ecam": (0x4010000000, 0x80000)}, 3, ["ECAM bus 0", "ECAM region"]),
    ("the console slot's interrupt moved", {"virtio_spi": 17}, CONSOLE_LINES, ["console slot 0x%x, interrupt" % CONSOLE] + EVERY_BUILD_LINE),
    ("the transports moved up one slot", {"virtio": (0x0A000200, 0x200, 32)}, CONSOLE_LINES + 1,
     ["virtio-mmio span", "console slot 0x%x, interrupt" % CONSOLE, "the tree has 75"]),
    ("no transport at the console's address", {"virtio": (0x0A000000, 0x200, 28)}, CONSOLE_LINES + 2,
     ["virtio-mmio span", "console transport", "no virtio-mmio transport at 0x%x" % CONSOLE]),
    ("transports twice as wide", {"virtio": (0x0A000000, 0x400, 16)}, CONSOLE_LINES + 1, ["console transport", "FIXED console"]),
    ("two transports' interrupts swapped", {"virtio_swap": (3, 4)}, 1, ["virtio-mmio interrupts", "do not rise by one"]),
    ("a transport missing from the middle", {"virtio_skip": 5}, 2, ["virtio-mmio span", "leave gaps or overlap", "virtio-mmio interrupts"]),
    ("the console's interrupt swapped with its neighbour's", {"virtio_swap": (27, 28)}, CONSOLE_LINES + 1,
     ["virtio-mmio interrupts", "console slot 0x%x, interrupt" % CONSOLE]),
    ("the PL011's interrupt changed", {"uart_irq": (0, 2, 4)}, 1, ["PL011 interrupt", "the tree has 34", "QV_PL011_IRQ is 33"]),
    ("the PL011's interrupt is not an SPI", {"uart_irq": (1, 1, 4)}, 1, ["PL011 interrupt", "QV_PL011_IRQ"]),
    ("the PL011 moved", {"uart": (0x09100000, 0x1000)}, 3, ["QV_PL011_BASE", "debug device", "FIXED UART"]),
    ("no ITS node", {"its": None}, 2, ["no node compatible with arm,gic-v3-its", "QV_GITS_BASE", "FIXED GITS"]),
    ("the ITS moved", {"its": (0x08090000, 0x20000)}, 2, ["GITS base", "QV_GITS_BASE", "FIXED GITS"]),
    ("the ITS one frame short", {"its": (0x08080000, 0x10000)}, 1, ["GITS region", "FIXED GITS"]),
    ("the distributor moved", {"gicd": (0x08010000, 0x10000)}, 2, ["QV_GICD_BASE", "FIXED GICD"]),
    ("the redistributors moved", {"gicr": (0x080C0000, 0xF60000)}, 2, ["QV_GICR_BASE", "FIXED GICR"]),
    ("the redistributor region resized", {"gicr": (0x080A0000, 0xF40000)}, 2, ["QV_GICR_SIZE", "FIXED GICR"]),
    ("two redistributor regions", {"gicr2": (0x4000000000, 0x1000000)}, 3, ["2 redistributor regions", "QV_GICR_BASE", "QV_GICR_SIZE"]),
    ("not a GICv3", {"gic_compat": "arm,cortex-a15-gic"}, 5, ["no node compatible with arm,gic-v3;", "QV_GICD_BASE", "FIXED GICR"]),
    ("RAM moved", {"ram": (0x80000000, 0x30000000)}, 1, ["RAM base", "QV_RAM_BASE"]),
    ("the 32-bit window's CPU address is not its PCI address", {"mmio32": (0x10000000, 0x20000000, 0x2EFF0000)}, 2,
     ["MMIO32 window, CPU address", SHM_C + ":", ITS_C + ":", "MMIO32_BASE"]),
    ("the 32-bit window resized", {"mmio32": (0x10000000, 0x10000000, 0x1EFF0000)}, 2, ["MMIO32 window, size", "MMIO32_SIZE"]),
    ("no 32-bit window", {"mmio32": None}, 6, ["0 32-bit memory ranges", "MMIO32_BASE", "MMIO32_SIZE"]),
    ("a bus-range of one cell", {"bus_range": (0,)}, 11, ["bus-range is 1 cells", "ECAM region", "ECAM_BASE", "MMIO32_SIZE"]),
    ("the PSCI list without the string", {"psci": ("arm,psci-1.0",)}, 1, ["PSCI compatible", "does not end in", MAIN_C + ":"]),
    ("the PSCI list with the string first", {"psci": ("arm,psci", "arm,psci-1.0")}, 1, ["PSCI compatible", "does not end in"]),
    ("no PSCI node", {"psci": None}, 1, ["PSCI compatible", "no node", MAIN_C + ":"]),
    # A tree that says a thing twice, or leaves out what a comparison goes through, is not read by its first word.
    ("a second PSCI node", {"psci2": MAP["psci"]}, 1, ["PSCI compatible", "2 nodes", MAIN_C + ":"]),
    ("a second PL011 node", {"uart2": (0x09100000, 0x1000)}, 4,
     ["2 nodes compatible with arm,pl011"] * 4 + ["QV_PL011_BASE", "debug device", "FIXED UART", "QV_PL011_IRQ"]),
    ("the PL011 with two interrupts", {"uart_irq": (0, 1, 4, 0, 2, 4)}, 1, ["PL011 interrupt", "interrupts is 6 cells", "QV_PL011_IRQ"]),
    ("the GIC node without ranges above the ITS", {"its_ranges": None}, 2, ["has no ranges"] * 2 + ["QV_GITS_BASE", "FIXED GITS"]),
    ("a second 32-bit window", {"mmio32_more": [(0x02000000, 0x40000000, 0x40000000, 0x10000000)]}, 6,
     ["2 32-bit memory ranges"] * 6 + ["MMIO32_BASE", "MMIO32_SIZE"]),
    ("a second 32-bit window, prefetchable", {"mmio32_more": [(0x42000000, 0x40000000, 0x40000000, 0x10000000)]}, 6,
     ["2 32-bit memory ranges"] * 6 + ["MMIO32_BASE", "MMIO32_SIZE"]),
    # The RTC: the one address every build file gives to rtc.
    ("the PL031 moved", {"rtc": (0x09020000, 0x1000)}, RTC_LINES,
     ["PL031 base"] * RTC_LINES + ["the tree has 0x9020000"] * RTC_LINES + ["rtc -b is 0x9010000"] * RTC_LINES + [KICK_BUILD + ":"]),
    ("no PL031 node", {"rtc": None}, RTC_LINES, ["PL031 base"] * RTC_LINES + ["no node compatible with arm,pl031"] * RTC_LINES),
    ("a second PL031 node", {"rtc2": (0x09020000, 0x1000)}, RTC_LINES,
     ["PL031 base"] * RTC_LINES + ["2 nodes compatible with arm,pl031"] * RTC_LINES),
    # Cases a comparison's own edge decides.
    ("the ECAM exactly as long as bus 0", {"ecam": (0x4010000000, 0x100000)}, 1, ["ECAM region", "FIXED ECAM"]),
    ("a GIC node with the distributor's row only", {"gicr": None}, 3,
     ["has 0 redistributor regions"] * 3 + ["QV_GICR_BASE", "QV_GICR_SIZE", "FIXED GICR"]),
    ("a PCI host with two address cells", {"pci_cells": (2, 2), "mmio32_more": [(0x03000000, 0x9000000000 + i, 0x9000000000 + i, 0x1000)
                                                                                 for i in range(3)]}, 11,
     ["#address-cells 2, not PCI rows"] * 11),
]


@pytest.mark.parametrize("change,count,named", [t[1:] for t in TREES], ids=[t[0] for t in TREES])
def test_a_tree_that_differs_fails_and_names_it(tmp_path, change, count, named):
    rc, bad, out = verdict(tmp_path, **change)
    assert rc == 1 and len(bad) == count, said(rc, bad, count)
    text = "\n".join(bad)
    for word in set(named):
        assert text.count(word) >= named.count(word), "%r is named %d times in:\n%s" % (word, text.count(word), text)
    # every line says where the constant it failed against is held
    assert all(re.search(r"[\w./-]+:\d+ ", ln) or "virtio-mmio interrupts" in ln for ln in bad), text


def test_the_highmem_off_ecam_is_the_reports_other_row_and_only_the_reports(tmp_path):
    """mmio_report.py lists both ECAM addresses; the two guest programs hold one."""
    _rc, bad, out = verdict(tmp_path, ecam=(0x3F000000, 0x1000000))
    assert not any(REPORT in ln for ln in bad) and "ok        ECAM region" in out, out


def test_every_mismatch_is_named_not_only_the_first(tmp_path):
    rc, bad, out = verdict(tmp_path, ecam=(0x4020000000, 0x10000000), uart_irq=(0, 2, 4), its=None, psci=("arm,psci-1.0",))
    assert rc == 1 and len(bad) == 3 + 1 + 2 + 1, said(rc, bad, 7)
    for word in ("ECAM region", "ECAM base", "PL011 interrupt", "GITS base", "GITS region", "PSCI compatible"):
        assert any(word in ln for ln in bad), word
    # and what did not change is still compared and still agrees
    assert "ok        GICD base" in out and "ok        virtio-mmio span" in out and "ok        console slot:" in out


def test_an_address_below_a_bus_is_carried_to_the_root_before_it_is_compared(tmp_path):
    """The ITS sits below the GIC node. QEMU gives that node an empty ranges (child address ==
    parent address); a tree whose GIC node shifts its children must be compared after the shift."""
    base, size = MAP["its"]
    shift = _u64(0x100000, base, size)                 # child 0x100000.. is root base..
    rc, bad, out = verdict(tmp_path, its_ranges=shift, its_reg=_u64(0x100000, size))
    assert rc == 0, said(rc, bad, 0)
    rc, bad, out = verdict(tmp_path, its_ranges=shift, its_reg=_u64(base, size))
    assert rc == 1 and len(bad) == 2 and all("no ranges row" in ln for ln in bad), said(rc, bad, 2)


# ------------------------------------------------------------------ the constants are READ from the sources

def copy_sources(tmp_path):
    """A tree holding copies of the files the tool reads, and nothing else."""
    repo = tmp_path / "repo"
    rels = list(tool.SOURCES) + [os.path.relpath(p, REPO).replace(os.sep, "/")
                                 for p in glob.glob(os.path.join(REPO, *tool.BUILD_GLOB.split("/")))]
    for rel in rels:
        dst = repo.joinpath(*rel.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(REPO, *rel.split("/")), str(dst))
    return repo


def edit(repo, rel, pattern, repl, count=1):
    p = repo.joinpath(*rel.split("/"))
    text = p.read_bytes().decode("utf-8")
    new, n = re.subn(pattern, repl, text, flags=re.M)
    assert n == count, "%s: %r matched %d times, not %d" % (rel, pattern, n, count)
    p.write_bytes(new.encode("utf-8"))


def define(name, value):
    return r"^(#define\s+%s\s+)\S+" % name, r"\g<1>" + value


CHANGED = [
    # the file, (pattern, replacement), the name the MISMATCH lines carry, how many comparisons fail
    (HEADER, define("QV_GICD_BASE", "0x08010000u"), "QV_GICD_BASE", 1),
    (HEADER, define("QV_GICR_BASE", "0x080C0000u"), "QV_GICR_BASE", 1),
    (HEADER, define("QV_GICR_SIZE", "0x00F40000u"), "QV_GICR_SIZE", 1),
    (HEADER, define("QV_GITS_BASE", "0x08090000u"), "QV_GITS_BASE", 1),
    (HEADER, define("QV_PL011_BASE", "0x09100000u"), "QV_PL011_BASE", 1),
    (HEADER, define("QV_PL011_IRQ", "34u"), "QV_PL011_IRQ", 1),
    (HEADER, define("QV_RAM_BASE", "0x80000000ull"), "QV_RAM_BASE", 1),
    (MAIN_C, (r'"0x09000000\^', '"0x09100000^'), "debug device", 1),
    (MAIN_C, (r'expected compatible \\"arm,psci\\"', r'expected compatible \\"arm,psci-0.2\\"'), "PSCI compatible", 1),
    (SHM_C, define("ECAM_BASE", "0x4020000000ull"), "ECAM_BASE", 1),
    (SHM_C, define("ECAM_BUS0_BYTES", "0x20000000u"), "ECAM_BUS0_BYTES", 1),
    (SHM_C, define("MMIO32_BASE", "0x20000000ull"), "MMIO32_BASE", 2),
    (SHM_C, define("MMIO32_SIZE", "0x1eff0000ull"), "MMIO32_SIZE", 1),
    (ITS_C, define("ECAM_BASE", "0x4020000000ull"), "ECAM_BASE", 1),
    (ITS_C, define("ECAM_BUS0_BYTES", "0x20000000u"), "ECAM_BUS0_BYTES", 1),
    (ITS_C, define("MMIO32_BASE", "0x20000000ull"), "MMIO32_BASE", 2),
    (ITS_C, define("MMIO32_SIZE", "0x1eff0000ull"), "MMIO32_SIZE", 1),
    (REPORT, (r'\("GICD", 0x08000000, 0x10000\)', '("GICD", 0x08010000, 0x10000)'), "FIXED GICD", 1),
    (REPORT, (r'\("GICD", 0x08000000, 0x10000\)', '("GICD", 0x08000000, 0x20000)'), "FIXED GICD", 1),
    (REPORT, (r'\("GITS", 0x08080000, 0x20000\)', '("GITS", 0x08080000, 0x10000)'), "FIXED GITS", 1),
    (REPORT, (r'\("GICR", 0x080A0000, 0xF60000\)', '("GICR", 0x080A0000, 0xF40000)'), "FIXED GICR", 1),
    (REPORT, (r'\("UART", 0x09000000, 0x1000\)', '("UART", 0x09100000, 0x1000)'), "FIXED UART", 1),
    (REPORT, (r'\("UART", 0x09000000, 0x1000\)', '("UART", 0x09000000, 0x100)'), "FIXED UART", 1),
    (REPORT, (r'\("console", CONSOLE_VIRTIO, 0x200\)', '("console", CONSOLE_VIRTIO, 0x400)'), "FIXED console", 1),
    (REPORT, (r'\("virtio", 0x0A000000, 0x4000\)', '("virtio", 0x0A000000, 0x3E00)'), "FIXED virtio", 1),
    (REPORT, (r'\("virtio", 0x0A000000, 0x4000\)', '("virtio", 0x0A000200, 0x4000)'), "FIXED virtio", 1),
    (REPORT, (r'\("ECAM", 0x4010000000, 0x10000000\)', '("ECAM", 0x4020000000, 0x10000000)'), "FIXED ECAM", 1),
    (REPORT, (r"^CONSOLE_VIRTIO = 0x0A003800$", "CONSOLE_VIRTIO = 0x0A003600"), "CONSOLE_VIRTIO", 1),
    (REPORT, (r"^CONSOLE_VIRTIO = 0x0A003800$", "CONSOLE_VIRTIO = 0x0A004000"), "CONSOLE_VIRTIO", 2),
    (KICK_BUILD, (START, "devc-virtio -u 2 0xa003800,77 &"), "devc-virtio", 1),
    (KICK_BUILD, (START, "devc-virtio -u 2 0xa003600,76 &"), "devc-virtio", 2),
    (KICK_BUILD, (RTC_RUN, "    rtc -b 0x9020000 primecell"), "rtc -b", 1),
    (BUILDS_WITH_RTC[0], (RTC_RUN, "    rtc -b 0x9000000 primecell"), "rtc -b", 1),
    (BUILDS_WITH_RTC[-1], (RTC_RUN, "    rtc -b 0x19010000 primecell"), "rtc -b", 1),
]


def test_a_copy_of_the_sources_gives_the_verdict_the_checkout_gives(tmp_path):
    repo = copy_sources(tmp_path)
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0, said(rc, bad, 0)
    assert out.replace(str(repo), "R") == verdict(tmp_path)[2].replace(REPO, "R")


@pytest.mark.parametrize("rel,change,name,count", CHANGED,
                         ids=["%s %s -> %s" % (c[0].rsplit("/", 1)[-1], c[2], c[1][1].replace("\\g<1>", "")) for c in CHANGED])
def test_a_changed_copy_of_a_source_changes_the_verdict(tmp_path, rel, change, name, count):
    """The tree is the one that passes against the checkout. One constant differs in one copied
    file, and the tool fails on exactly the comparisons that read it."""
    repo = copy_sources(tmp_path)
    edit(repo, rel, *change)
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 1 and len(bad) == count, said(rc, bad, count)
    assert all(rel + ":" in ln for ln in bad), "a line that does not name %s:\n%s" % (rel, "\n".join(bad))
    assert any(name in ln for ln in bad), "%s is not named:\n%s" % (name, "\n".join(bad))


# A second map, made up throughout, and every source rewritten to hold it.
MOVED: dict = dict(
    gicd=(0x18000000, 0x20000), gicr=(0x180C0000, 0xE00000), its=(0x18040000, 0x40000),
    uart=(0x19000000, 0x2000), uart_irq=(0, 7, 4), rtc=(0x19040000, 0x2000), ram=(0x80000000, 0x10000000),
    ecam=(0x5010000000, 0x20000000), mmio32=(0x20000000, 0x20000000, 0x1EFF0000),
    virtio=(0x1A000000, 0x400, 16), virtio_spi=40, psci=("arm,psci-1.0", "made-up,psci"))
MOVED_CONSOLE = (0x1A003000, 32 + 40 + 12)            # the thirteenth of the sixteen transports
MOVED_EDITS = [
    (HEADER, define("QV_GICD_BASE", "0x18000000u")), (HEADER, define("QV_GICR_BASE", "0x180C0000u")),
    (HEADER, define("QV_GICR_SIZE", "0x00E00000u")), (HEADER, define("QV_GITS_BASE", "0x18040000u")),
    (HEADER, define("QV_PL011_BASE", "0x19000000u")), (HEADER, define("QV_PL011_IRQ", "39u")),
    (HEADER, define("QV_RAM_BASE", "0x80000000ull")),
    (MAIN_C, (r'"0x09000000\^', '"0x19000000^')),
    (MAIN_C, (r'expected compatible \\"arm,psci\\"', r'expected compatible \\"made-up,psci\\"')),
    (SHM_C, define("ECAM_BASE", "0x5010000000ull")), (SHM_C, define("MMIO32_BASE", "0x20000000ull")),
    (SHM_C, define("MMIO32_SIZE", "0x1eff0000ull")), (SHM_C, define("ECAM_BUS0_BYTES", "0x18000000u")),
    (ITS_C, define("ECAM_BASE", "0x5010000000ull")), (ITS_C, define("MMIO32_BASE", "0x20000000ull")),
    (ITS_C, define("MMIO32_SIZE", "0x1eff0000ull")), (ITS_C, define("ECAM_BUS0_BYTES", "0x18000000u")),
    (REPORT, (r"^CONSOLE_VIRTIO = 0x0A003800$", "CONSOLE_VIRTIO = 0x1A003000")),
    (REPORT, (r'\("GICD", 0x08000000, 0x10000\)', '("GICD", 0x18000000, 0x20000)')),
    (REPORT, (r'\("GITS", 0x08080000, 0x20000\)', '("GITS", 0x18040000, 0x40000)')),
    (REPORT, (r'\("GICR", 0x080A0000, 0xF60000\)', '("GICR", 0x180C0000, 0xE00000)')),
    (REPORT, (r'\("UART", 0x09000000, 0x1000\)', '("UART", 0x19000000, 0x2000)')),
    (REPORT, (r'\("console", CONSOLE_VIRTIO, 0x200\)', '("console", CONSOLE_VIRTIO, 0x400)')),
    (REPORT, (r'\("virtio", 0x0A000000, 0x4000\)', '("virtio", 0x1A000000, 0x4000)')),
    (REPORT, (r'\("ECAM", 0x4010000000, 0x10000000\)', '("ECAM", 0x5010000000, 0x20000000)')),
]


def moved_sources(tmp_path):
    repo = copy_sources(tmp_path)
    for rel, change in MOVED_EDITS:
        edit(repo, rel, *change)
    for rel in BUILDS_WITH_CONSOLE:
        edit(repo, rel, START, "devc-virtio -u 2 0x%x,%d &" % MOVED_CONSOLE)
    for rel in BUILDS_WITH_RTC:
        edit(repo, rel, RTC_RUN, "    rtc -b 0x%x primecell" % MOVED["rtc"][0])
    return repo


def test_a_tree_and_the_sources_moved_together_still_agree(tmp_path):
    """Every constant the tool compares differs from the checkout's, in the sources and in the
    tree alike. It passes only if every value it compares with came out of the copied files."""
    repo = moved_sources(tmp_path)
    rc, bad, out = verdict(tmp_path, repo=repo, **MOVED)
    assert rc == 0, said(rc, bad, 0)
    assert "console slot 0x%x, interrupt: %d = " % MOVED_CONSOLE in out and '"made-up,psci"' in out
    assert out.count("PL031 base: 0x%x = " % MOVED["rtc"][0]) == RTC_LINES, out


def test_the_checkouts_tree_fails_every_comparison_against_the_moved_sources(tmp_path):
    """The other direction. Against sources that hold another map, the tree that passes against
    the checkout agrees with nothing but the comparison that has no constant behind it (the
    transports' interrupts rise by one) and the one between two source files. The moved tree
    against the checkout fails as widely; there bus 0 also still fits, twice, which is right: the
    moved ECAM is the larger one."""
    def agreeing(out):
        return [ln.split(":")[0] for ln in out.splitlines() if ln.startswith("ok ")]

    rc, _bad, out = verdict(tmp_path, repo=moved_sources(tmp_path))
    assert rc == 1 and agreeing(out) == ["ok        virtio-mmio interrupts", "ok        console slot"], out
    rc, _bad, out = verdict(tmp_path, **MOVED)
    assert rc == 1 and agreeing(out) == ["ok        ECAM bus 0", "ok        ECAM bus 0", "ok        virtio-mmio interrupts",
                                         "ok        console slot"], out


def test_the_tool_holds_no_address_and_no_string_of_its_own():
    """A static look beside the behaviour above: no integer in the tool is large enough to be an
    address except the device tree's magic, and the PSCI string and the names of the constants'
    values appear nowhere in it."""
    big = []
    with open(TOOL, "rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.NUMBER and re.fullmatch(r"0[xX][0-9a-fA-F]+|[0-9]+", tok.string) and int(tok.string, 0) >= 0x10000:
                big.append(tok.string)
    assert big == ["0xD00DFEED"], big
    text = _text(TOOL)
    assert "arm,psci" not in text and "0xa003800" not in text.lower() and "a003800" not in text.lower()
    assert "9010000" not in text, "the address the build files give rtc is in the tool"


# ------------------------------------------------------------------ exit 2: nothing could be compared

GOOD = fdt(virt())
HEAD = struct.unpack(">10I", GOOD[:40])


def _head(**fields):
    names = ("magic", "total", "off_st", "off_str", "off_rsv", "version", "last_comp", "boot_cpu", "size_str", "size_st")
    return struct.pack(">10I", *[fields.get(n, HEAD[i]) for i, n in enumerate(names)]) + GOOD[40:]


NOT_TREES = [
    ("empty", b"", "shorter than"),
    ("39 bytes", GOOD[:39], "shorter than"),
    ("text", b"/dts-v1/;\n/ {\n\tcompatible = \"made-up,virt\";\n};\n" * 4, "not with a device tree's d00dfeed"),
    ("another magic", fdt(virt(), magic=0xD00DFEEE), "not with a device tree's d00dfeed"),
    ("cut short", GOOD[:len(GOOD) // 2], "the file has"),
    ("version 16", fdt(virt(), version=16), "version 16"),
    ("structure block past the end", _head(size_st=HEAD[9] + len(GOOD)), "structure block lies outside"),
    ("strings block past the end", _head(off_str=HEAD[1] + 4), "strings block lies outside"),
    ("no end token", _head(size_st=HEAD[9] - 4), "ends without an end token"),
    ("an unknown token", GOOD[:HEAD[2]] + _u32(7) + GOOD[HEAD[2] + 4:], "unknown token 0x7"),
    ("a node that ends twice", GOOD[:HEAD[2]] + _u32(2) + GOOD[HEAD[2] + 4:], "never begun"),
    ("no root", GOOD[:HEAD[2]] + _u32(9) + GOOD[HEAD[2] + 4:], "no root node"),
    ("a second root node", fdt(virt(), tail=_u32(1, 0, 2)), "a second root node"),
    ("a last compatible version above 17", fdt(virt(), last_comp=18), "last compatible 18"),
    ("the structure block inside the header", _head(off_st=36), "structure block lies outside"),
    ("the strings block inside the header", _head(off_str=36), "strings block lies outside"),
]


@pytest.mark.parametrize("blob,why", [t[1:] for t in NOT_TREES], ids=[t[0] for t in NOT_TREES])
def test_a_file_that_is_not_a_device_tree_is_exit_2_and_no_verdict(tmp_path, blob, why):
    rc, out, err = run(write(tmp_path, blob))
    assert rc == 2 and out == "", (rc, out)
    assert why in err and "nothing was compared" in err, err


def test_a_file_that_is_not_there_is_exit_2(tmp_path):
    rc, out, err = run(str(tmp_path / "none.dtb"))
    assert rc == 2 and out == "" and "nothing was compared" in err, (rc, out, err)


def test_a_tree_whose_cells_cannot_be_read_is_a_mismatch_per_comparison_not_a_crash(tmp_path):
    """A tree that parses and whose root gives no address and no size cells: every address read
    at the root fails its comparisons by name. What does not go through the root's cells still
    agrees: the ITS, read below the GIC node; an interrupt; a list of strings; and the one
    comparison between two source files."""
    rc, bad, out = verdict(tmp_path, root_cells=(0, 0))
    assert rc == 1 and all("not rows of 0" in ln for ln in bad), said(rc, bad)
    assert sorted({ln.split(":")[0] for ln in out.splitlines() if ln.startswith("ok ")}) == [
        "ok        GITS base", "ok        GITS region", "ok        PL011 interrupt", "ok        PSCI compatible",
        "ok        console slot"], out


EIGHT, THREE = _u64(2), b"\0\0\2"
NOT_ONE_CELL = [
    # the node, the property, its bytes, how many comparisons fail (None: every one that reads an address at the root)
    ("", "#address-cells", EIGHT, None),
    ("", "#size-cells", THREE, None),
    ("intc", "#address-cells", EIGHT, 2),
    ("intc", "#size-cells", b"", 2),
    ("intc", "#redistributor-regions", THREE, 3),
    ("intc", "#redistributor-regions", _u64(1), 3),
    ("pcie", "#address-cells", _u64(3), 11),
    ("pcie", "#size-cells", THREE, 11),
]


@pytest.mark.parametrize("node,prop,value,count", NOT_ONE_CELL,
                         ids=["%s %s in %d bytes" % (n[0] or "the root's", n[1], len(n[2])) for n in NOT_ONE_CELL])
def test_a_cells_property_that_is_not_one_cell_is_a_mismatch_and_not_its_default(tmp_path, node, prop, value, count):
    """A count that is there and is not four bytes is not read as the count the binding gives
    when the property is missing: every comparison that needs it fails, and says so. (Read as the
    default, the root's and the GIC node's #address-cells here and the GIC node's
    #redistributor-regions would each pass: for this machine the default is the right number.)"""
    rc, bad, out = verdict(tmp_path, tree=with_prop(virt(), node, prop, value))
    where = "/" if not node else [n for n in tool.parse_dtb(fdt(virt())).walk() if n.name.split("@")[0] == node][0].path()
    says = "%s: %s is %d bytes, not one cell" % (where, prop, len(value))
    assert rc == 1 and bad and all(says in ln for ln in bad), said(rc, bad, count)
    if count is None:
        # what does not read the root's cells still agrees, as in the test above
        assert sorted({ln.split(":")[0] for ln in out.splitlines() if ln.startswith("ok ")}) == [
            "ok        GITS base", "ok        GITS region", "ok        PL011 interrupt", "ok        PSCI compatible",
            "ok        console slot"], out
    else:
        assert len(bad) == count, said(rc, bad, count)


def test_an_error_inside_the_comparison_is_exit_2_and_no_verdict(tmp_path, monkeypatch):
    """Exit 1 means "compared, and it differs". A stop the comparison did not foresee is neither
    a pass nor a mismatch, and prints none of the lines it had got to."""
    def stops(_root, _src, v):
        v.add(True, "made up", "one line before the stop")
        raise RuntimeError("made up")

    monkeypatch.setattr(tool, "compare", stops)
    rc, out, err = run(write(tmp_path, GOOD))
    assert rc == 2 and out == "", (rc, out)
    assert "RuntimeError: made up" in err and "nothing is concluded" in err, err


@pytest.mark.parametrize("step", ["parse_dtb", "read_sources"])
def test_an_error_before_the_comparison_that_was_not_foreseen_is_exit_2_as_well(tmp_path, monkeypatch, step):
    """The reader and the source reader each name what they cannot read (exit 2, above). A stop
    in either that is none of those must not be left to Python, whose status for a traceback is 1."""
    def stops(*_args):
        raise RuntimeError("made up")

    monkeypatch.setattr(tool, step, stops)
    rc, out, err = run(write(tmp_path, GOOD))
    assert rc == 2 and out == "", (rc, out)
    assert "RuntimeError: made up" in err and "nothing is concluded" in err, err


def test_qemus_padding_after_the_tree_is_read_past(tmp_path):
    """QEMU writes the tree into a buffer larger than the tree; the header says where it ends."""
    blob = bytearray(GOOD + b"\0" * 4096)
    struct.pack_into(">I", blob, 4, len(blob))
    rc, out, _err = run(write(tmp_path, bytes(blob)))
    assert rc == 0, said(rc, mismatches(out), 0)


def remove(repo, rel):
    repo.joinpath(*rel.split("/")).unlink()


BROKEN = [
    # id, what is done to the copied sources, what the message says
    ("a define gone", lambda r: edit(r, HEADER, r"^#define QV_GITS_BASE.*\n", ""), [HEADER, "QV_GITS_BASE", "0 times"]),
    ("a define only in a comment", lambda r: edit(r, SHM_C, r"^(#define ECAM_BASE .*)$", r"/* \g<1> */"), [SHM_C, "ECAM_BASE", "0 times"]),
    ("a define twice", lambda r: edit(r, ITS_C, r"^(#define MMIO32_SIZE .*)$", "\\g<1>\n\\g<1>"), [ITS_C, "MMIO32_SIZE", "2 times"]),
    ("a define that is not an integer", lambda r: edit(r, HEADER, *define("QV_RAM_BASE", "RAM_BASE_FROM_ELSEWHERE")),
     [HEADER, "QV_RAM_BASE", "not one integer"]),
    ("no debug device string", lambda r: edit(r, MAIN_C, r'"0x09000000\^2\.0\.0\.115200"', '""'), [MAIN_C, "debug device", "0 times"]),
    ("the PSCI message reworded", lambda r: edit(r, MAIN_C, r"expected compatible", "wanted compatible"), [MAIN_C, "PSCI", "0 times"]),
    ("a report row gone", lambda r: edit(r, REPORT, r'^\s*\("GITS", .*\n', ""), [REPORT, "0 rows named GITS"]),
    ("a report row twice", lambda r: edit(r, REPORT, r'^(\s*\("UART", .*\n)', "\\g<1>\\g<1>"), [REPORT, "2 rows named UART"]),
    ("a report row of another shape", lambda r: edit(r, REPORT, r'\("GICD", 0x08000000, 0x10000\)', '("GICD", 0x08000000)'),
     [REPORT, "not (name, base, size)"]),
    ("the report's console address assigned twice", lambda r: edit(r, REPORT, r"^(CONSOLE_VIRTIO = .*)$", "\\g<1>\n\\g<1>"),
     [REPORT, "CONSOLE_VIRTIO", "2 times"]),
    ("the report's console address computed", lambda r: edit(r, REPORT, r"^CONSOLE_VIRTIO = .*$", "CONSOLE_VIRTIO = int('0x0A003800', 16)"),
     [REPORT, "CONSOLE_VIRTIO"]),
    ("the report does not parse", lambda r: edit(r, REPORT, r"^FIXED = \[", "FIXED = [("), [REPORT, "parse"]),
    ("a console line without its location", lambda r: edit(r, KICK_BUILD, START, "devc-virtio -u 2 &"), [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line that is the driver and an ampersand", lambda r: edit(r, KICK_BUILD, START, "devc-virtio &"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line by its path, without its location", lambda r: edit(r, KICK_BUILD, START, "/proc/boot/devc-virtio -u 2 &"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line through on, without its location", lambda r: edit(r, KICK_BUILD, START, "on -p 20 devc-virtio -u 2 &"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line whose location is not its last word", lambda r: edit(r, KICK_BUILD, START, "devc-virtio 0xa003800,76 -u 2 &"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line that names the driver again as its last word",
     lambda r: edit(r, KICK_BUILD, START, "devc-virtio -u 2 0xa003800,76 -o /proc/boot/devc-virtio"), [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line with a comment after its location", lambda r: edit(r, KICK_BUILD, START, "devc-virtio -u 2 0xa003800,76 &  # the console"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a console line with text after its interrupt", lambda r: edit(r, KICK_BUILD, START, "devc-virtio -u 2 0xa003800,76th &"),
     [KICK_BUILD, "LOCATION,INTERRUPT"]),
    ("a define whose value is an expression", lambda r: edit(r, HEADER, *define("QV_PL011_IRQ", "32u + 1u")), [HEADER, "QV_PL011_IRQ", "0 times"]),
    ("the debug device string twice", lambda r: edit(r, MAIN_C, r'^(\t\t\{ "0x09000000\^2\.0\.0\.115200", "" \},\n)', "\\g<1>\\g<1>"),
     [MAIN_C, "debug device", "2 times"]),
    ("the PSCI message twice", lambda r: edit(r, MAIN_C, r"^(.*expected compatible.*\n)", "\\g<1>\\g<1>"), [MAIN_C, "PSCI", "2 times"]),
] + [(what, functools.partial(edit, rel=KICK_BUILD, pattern=RTC_RUN, repl=line), [KICK_BUILD + ":", "-b ADDRESS"]) for what, line in [
    # A line that runs rtc and from which one address cannot be read is never a line to skip.
    ("an rtc line without -b", "    rtc primecell"),
    ("an rtc line with -b glued to its address", "    rtc -b0x9010000 primecell"),
    ("an rtc line with -b twice", "    rtc -b 0x9010000 -b 0x9020000 primecell"),
    ("an rtc line with -b twice, the same address", "    rtc -b 0x9010000 -b 0x9010000 primecell"),
    ("an rtc line with -b as its last word", "    rtc primecell -b"),
    ("an rtc line whose address is not hexadecimal", "    rtc -b 9010000 primecell"),
    ("an rtc line with text after its address", "    rtc -b 0x9010000th primecell"),
    ("an rtc line with a comment after it", "    rtc -b 0x9010000 primecell  # the PL031"),
    ("an rtc line whose address stands in a comment after it", "    rtc primecell # -b 0x9010000"),
]] + [("%s gone" % rel.rsplit("/", 1)[-1], functools.partial(remove, rel=rel), [rel]) for rel in tool.SOURCES]


@pytest.mark.parametrize("breakage,says", [t[1:] for t in BROKEN], ids=[t[0] for t in BROKEN])
def test_a_source_that_does_not_hold_its_constant_is_exit_2_and_no_verdict(tmp_path, breakage, says):
    repo = copy_sources(tmp_path)
    breakage(repo)
    rc, out, err = run(write(tmp_path, GOOD), repo)
    assert rc == 2 and out == "", (rc, out)
    assert "nothing was compared" in err and all(s in err for s in says), err


def test_no_build_file_that_starts_the_console_is_exit_2_not_a_pass(tmp_path):
    """With no line that starts the driver the console slot would be compared with nothing. The
    file lists still name the driver, in every one of the copies: that is not a start line."""
    repo = copy_sources(tmp_path)
    for rel in BUILDS_WITH_CONSOLE:
        edit(repo, rel, START + r"\n", "")
        assert names_the_driver(_text(str(repo.joinpath(*rel.split("/"))))), rel
    rc, out, err = run(write(tmp_path, GOOD), repo)
    assert rc == 2 and out == "", (rc, out)
    assert "starts devc-virtio" in err and "nothing was compared" in err, err


# ------------------------------------------------------------------ a start line is found by its command word

ELSEWHERE = (CONSOLE - MAP["virtio"][1], CONSOLE_INTID - 1)    # the slot below the console's, and the interrupt a tree gives it
FORMS = [
    ("by its path in the image", "/proc/boot/devc-virtio -u 2 %s &"),
    ("by its path in the file list", "sbin/devc-virtio -u 2 %s &"),
    ("behind an attribute", "[pri=20] devc-virtio -u 2 %s &"),
    ("through on", "on -p 20 devc-virtio -u 2 %s &"),
    ("through on, by its path", "on -p 20 /proc/boot/devc-virtio -u 2 %s &"),
    ("indented", "\t  devc-virtio -u 2 %s &"),
    ("in the foreground", "devc-virtio -u 2 %s"),
    ("with no blank before the ampersand", "devc-virtio -u 2 %s&"),
    ("with no option before the location", "devc-virtio %s &"),
]


@pytest.mark.parametrize("form", [f[1] for f in FORMS], ids=[f[0] for f in FORMS])
def test_a_start_line_is_read_in_each_form_in_which_the_driver_is_a_word(tmp_path, form):
    """One build file starts the driver in another form than the others. At the console's slot it
    is still that file's one comparison. At another slot the tool fails and names the file: a
    start line it did not recognise would be passed over, and the moved slot would pass."""
    repo = copy_sources(tmp_path)
    edit(repo, KICK_BUILD, START, form % ("0x%x,%d" % (CONSOLE, CONSOLE_INTID)))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0, said(rc, bad, 0)
    assert out.count("console slot 0x%x, interrupt: %d = %s:" % (CONSOLE, CONSOLE_INTID, KICK_BUILD)) == 1, out
    assert out.count("console slot 0x%x, interrupt" % CONSOLE) == CONSOLE_LINES, out

    repo = copy_sources(tmp_path)
    edit(repo, KICK_BUILD, START, form % ("0x%x,%d" % ELSEWHERE))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 1 and len(bad) == 1, said(rc, bad, 1)
    assert bad[0].startswith("MISMATCH  console slot:") and KICK_BUILD + ":" in bad[0] and "names 0x%x" % ELSEWHERE[0] in bad[0], bad[0]
    # the tree does give that slot that interrupt, so the one failure is the slot itself
    assert "ok        console slot 0x%x, interrupt: %d = %s:" % (ELSEWHERE + (KICK_BUILD,)) in out, out
    assert out.count("console slot 0x%x, interrupt" % CONSOLE) == CONSOLE_LINES - 1, out


@pytest.mark.parametrize("which", [0, -1], ids=["the first build file the search finds", "the last"])
def test_a_start_line_is_read_in_every_build_file_the_search_finds(tmp_path, which):
    """Not only in the files that start the driver today. A start line added at another slot to
    the first and to the last build file of the search fails, and names that file."""
    repo = copy_sources(tmp_path)
    rel = sorted(p.relative_to(repo).as_posix() for p in repo.glob("ipc-test/*/*.build"))[which]
    with open(str(repo.joinpath(*rel.split("/"))), "ab") as f:
        f.write(("devc-virtio -u 2 0x%x,%d &\n" % ELSEWHERE).encode("ascii"))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 1 and len(bad) == 1, said(rc, bad, 1)
    assert bad[0].startswith("MISMATCH  console slot:") and rel + ":" in bad[0], bad[0]
    assert "ok        console slot 0x%x, interrupt: %d = %s:" % (ELSEWHERE + (rel,)) in out, out


def test_a_commented_console_line_and_the_file_list_are_not_console_lines(tmp_path):
    """Comment lines, and the driver named with nothing after it (the file list, in three ways of
    writing an entry), each beside the real start line and each at another slot where it has one."""
    repo = copy_sources(tmp_path)
    elsewhere = "0x%x,%d" % ELSEWHERE
    edit(repo, KICK_BUILD, r"^(devc-virtio -u 2 0xa003800,76 &)$",
         "# devc-virtio -u 2 %s &\n\t# /proc/boot/devc-virtio -u 2 %s &\n#devc-virtio -u 2 %s &\n#was: devc-virtio -u 2 %s &\n\\g<1>\n"
         "[perms=0755] sbin/devc-virtio\n/proc/boot/devc-virtio=sbin/devc-virtio\n  sbin/devc-virtio" % ((elsewhere,) * 4))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0 and out.count("devc-virtio\n") == CONSOLE_LINES, said(rc, bad, 0)

    def unnumbered(text):                              # the start line is four lines lower in the edited copy
        return re.sub(re.escape(KICK_BUILD) + r":\d+", KICK_BUILD, text)

    assert unnumbered(out) == unnumbered(verdict(tmp_path, repo=copy_sources(tmp_path))[2]), "the added lines changed what is compared"


# ------------------------------------------------------------------ the line that gives rtc the clock's address

RTC_ELSEWHERE = RTC + 0x10000
RTC_FORMS = [
    ("at the line's start", "rtc -b %s primecell"),
    ("by its path in the image", "    /proc/boot/rtc -b %s primecell"),
    ("by its path in the file list", "    sbin/rtc -b %s primecell"),
    ("behind an attribute", "    [pri=20] rtc -b %s primecell"),
    ("through on", "    on -p 20 rtc -b %s primecell"),
    ("through on, by its path", "    on -p 20 /proc/boot/rtc -b %s primecell"),
    ("with an option before the address", "    rtc -l -b %s primecell"),
    ("with an option after the address", "    rtc -b %s -l primecell"),
    ("with no clock type after the address (the tool reads none)", "    rtc -b %s"),
    ("in the background", "    rtc -b %s primecell &"),
]


@pytest.mark.parametrize("form", [f[1] for f in RTC_FORMS], ids=[f[0] for f in RTC_FORMS])
@pytest.mark.parametrize("digits", ["0x%x", "0X%X"], ids=["lower case", "upper case"])
def test_an_rtc_line_is_read_in_each_form_in_which_rtc_is_a_word(tmp_path, form, digits):
    """One build file runs rtc in another form than the others. With the PL031's address it is
    still that file's one comparison. With another address the tool fails and names the file."""
    repo = copy_sources(tmp_path)
    edit(repo, KICK_BUILD, RTC_RUN, form % (digits % RTC))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0, said(rc, bad, 0)
    assert out.count("PL031 base: 0x%x = %s:" % (RTC, KICK_BUILD)) == 1 and out.count("PL031 base") == RTC_LINES, out

    repo = copy_sources(tmp_path)
    edit(repo, KICK_BUILD, RTC_RUN, form % (digits % RTC_ELSEWHERE))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 1 and len(bad) == 1, said(rc, bad, 1)
    assert bad[0].startswith("MISMATCH  PL031 base: the tree has 0x%x; %s:" % (RTC, KICK_BUILD)), bad[0]
    assert bad[0].endswith("rtc -b is 0x%x" % RTC_ELSEWHERE) and out.count("ok        PL031 base") == RTC_LINES - 1, out


def test_a_second_rtc_line_in_a_build_file_is_a_second_comparison(tmp_path):
    """Not the first line of a file only: a line added at another address to the first and to the
    last build file of the search fails, once each, and names that file's added line."""
    repo = copy_sources(tmp_path)
    rels = sorted(p.relative_to(repo).as_posix() for p in repo.glob("ipc-test/*/*.build"))
    for rel in (rels[0], rels[-1]):
        with open(str(repo.joinpath(*rel.split("/"))), "ab") as f:
            f.write(("rtc -b 0x%x primecell\n" % RTC_ELSEWHERE).encode("ascii"))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 1 and len(bad) == 2, said(rc, bad, 2)
    for rel, ln in zip((rels[0], rels[-1]), bad):
        last = len(_text(str(repo.joinpath(*rel.split("/")))).splitlines())
        assert "%s:%d rtc -b is 0x%x" % (rel, last, RTC_ELSEWHERE) in ln, ln
    assert out.count("ok        PL031 base") == RTC_LINES, out


def test_a_commented_rtc_line_and_the_file_list_are_not_rtc_lines(tmp_path):
    """Comment lines, and rtc named with nothing after it (the file list, in three ways of
    writing an entry), each beside the real line and each at another address where it has one."""
    repo = copy_sources(tmp_path)
    elsewhere = "0x%x" % RTC_ELSEWHERE
    edit(repo, KICK_BUILD, r"^(    rtc -b 0x9010000 primecell)$",
         "    # rtc -b %s primecell\n# /proc/boot/rtc -b %s primecell\n#rtc -b %s primecell\n    #was: rtc -b %s primecell\n\\g<1>\n"
         "[perms=0755] sbin/rtc\n/proc/boot/rtc=sbin/rtc\n  sbin/rtc" % ((elsewhere,) * 4))
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0 and out.count("PL031 base") == RTC_LINES, said(rc, bad, 0)

    def unnumbered(text):                              # the lines below the added ones are seven lines lower in the edited copy
        return re.sub(re.escape(KICK_BUILD) + r":\d+", KICK_BUILD, text)

    assert unnumbered(out) == unnumbered(verdict(tmp_path, repo=copy_sources(tmp_path))[2]), "the added lines changed what is compared"


def test_no_build_file_that_runs_rtc_is_exit_2_not_a_pass(tmp_path):
    """With no line that runs rtc the PL031's base would be compared with nothing. The file
    lists still name rtc, in every one of the copies: that is not a line that runs it."""
    repo = copy_sources(tmp_path)
    for rel in BUILDS_WITH_RTC:
        edit(repo, rel, RTC_RUN + r"\n", "")
        assert names_rtc(_text(str(repo.joinpath(*rel.split("/"))))), rel
    rc, out, err = run(write(tmp_path, GOOD), repo)
    assert rc == 2 and out == "", (rc, out)
    assert "runs rtc" in err and "nothing was compared" in err, err


# ------------------------------------------------------------------ a command that is named, and not as a word

NOT_A_WORD = [
    ("in a quoted command", 'ksh -c "%(name)s %(args)s"'),
    ("after a semicolon with no blank", "uname -a;%(name)s %(args)s"),
    ("in quotes", '"%(name)s" %(args)s'),
    ("in a brace group on one line", "{%(name)s %(args)s}"),
    ("behind a backslash", "\\%(name)s %(args)s"),
    ("after an equals sign", "RUN=%(name)s %(args)s"),
]
NAMED = [
    # the command, the pattern of its line today, its other words with the machine's values, and with others
    ("devc-virtio", START, "-u 2 0x%x,%d &" % (CONSOLE, CONSOLE_INTID), "-u 2 0x%x,%d &" % ELSEWHERE),
    ("rtc", RTC_RUN, "-b 0x%x primecell" % RTC, "-b 0x%x primecell" % RTC_ELSEWHERE),
]


@pytest.mark.parametrize("form", [f[1] for f in NOT_A_WORD], ids=[f[0] for f in NOT_A_WORD])
@pytest.mark.parametrize("command,today,same,other", NAMED, ids=[n[0] for n in NAMED])
@pytest.mark.parametrize("moved", [False, True], ids=["the machine's values", "other values"])
def test_a_line_that_names_a_command_and_not_as_a_word_stops_the_tool(tmp_path, form, command, today, same, other, moved):
    """The tool finds a line by its command word. A line in which the command's name is glued to
    something else (a quote, a semicolon, a brace, a backslash, an equals sign) holds no such
    word: by the word rule alone it would be passed over, and a build file that runs the command
    there with another address would pass. It is exit 2 and names the line, whatever its values."""
    repo = copy_sources(tmp_path)
    at = [n for n, ln in enumerate(_text(str(repo.joinpath(*KICK_BUILD.split("/")))).splitlines(), 1) if re.match(today, ln)]
    line = form % {"name": command, "args": other if moved else same}
    edit(repo, KICK_BUILD, today, lambda _m: line)
    rc, out, err = run(write(tmp_path, GOOD), repo)
    assert rc == 2 and out == "", (rc, out)
    assert len(at) == 1 and "%s:%d:" % (KICK_BUILD, at[0]) in err and "names %s" % command in err and "nothing was compared" in err, err


@pytest.mark.parametrize("line", ["waitfor /dev/rtc0 5", "smartctl -a /dev/hd0", "ls /proc/boot/rtc-test /dev/devc-virtio.log",
                                  "devc-virtio-other -u 2 0xa003600,75 &", "rtc.sh -b 0x9020000", "x-rtc -b 0x9020000 primecell",
                                  "ls /etc/rtc/zone /proc/boot/devc-virtio/log"],
                         ids=["rtc0", "smartctl", "longer names in paths", "a longer driver name", "rtc.sh", "x-rtc", "directories"])
def test_a_longer_name_that_holds_a_commands_name_is_not_that_command(tmp_path, line):
    """Neither a line to read nor a line to stop on: the command's name with a letter, a digit,
    an underscore, a dot or a hyphen against it is another name, and before a slash it is a
    directory's."""
    repo = copy_sources(tmp_path)
    edit(repo, KICK_BUILD, r"^(    rtc -b 0x9010000 primecell)$", "\\g<1>\n" + line)
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0, said(rc, bad, 0)
    assert out.count("PL031 base") == RTC_LINES and out.count("console slot 0x%x, interrupt" % CONSOLE) == CONSOLE_LINES, out


def test_what_a_c_comment_holds_is_not_a_constant(tmp_path):
    """A define, a debug-device string and the PSCI message, each written a second time inside a
    comment with another value: the code's own are still the ones read, and still read once."""
    repo = copy_sources(tmp_path)
    edit(repo, HEADER, r"^(#define QV_GICD_BASE .*)$", "/*\n#define QV_GICD_BASE 0x1u\n*/\n\\g<1>  // #define QV_GICD_BASE 0x2u")
    edit(repo, SHM_C, r"^(#define MMIO32_SIZE .*)$", "/* was:\n#define MMIO32_SIZE     0x1000ull\n*/\n\\g<1>")
    edit(repo, MAIN_C, r"^(int\nmain\()", '/* { "0x01000000^2.0.0.115200", "" } and expected compatible \\\\"other,psci\\\\" */\n\\g<1>')
    rc, bad, out = verdict(tmp_path, repo=repo)
    assert rc == 0, said(rc, bad, 0)
    # the line a comparison names is the code's line, counted with the comment's lines before it
    with open(str(repo.joinpath(*HEADER.split("/"))), encoding="utf-8") as f:
        at = [n for n, ln in enumerate(f, 1) if ln.startswith("#define QV_GICD_BASE")]
    assert len(at) == 2 and "%s:%d QV_GICD_BASE" % (HEADER, at[1]) in out, (at, out)


# ------------------------------------------------------------------ the pieces

def test_c_comments_are_blanked_and_lines_kept():
    text = 'a /* #define X 1\n   still */ b // #define Y 2\n"// not a comment" \'"\' c /* open'
    got = tool.strip_c_comments(text)
    assert got.count("\n") == text.count("\n") and "#define" not in got
    assert '"// not a comment"' in got and got.splitlines()[0].rstrip() == "a" and got.splitlines()[1].split() == ["b"]
    assert "open" not in got and got.splitlines()[2].rstrip().endswith("c")


@pytest.mark.parametrize("literal,value", [
    ("0x08000000u", 0x08000000), ("0x4010000000ull", 0x4010000000), ("33u", 33), ("0", 0), ("017", 15), ("0X1fUL", 31),
    ("(33u)", None), ("QV_OTHER", None), ("0x", None), ("33u+1", None), ("1.5", None)])
def test_a_c_integer_is_read_as_c_reads_it(literal, value):
    assert tool.c_int(literal) == value


def test_the_reader_keeps_properties_and_children_as_written():
    root = tool.parse_dtb(fdt(virt()))
    assert root.parent is None and root.path() == "/" and root.strings("compatible") == ["made-up,virt"]
    its = [n for n in root.walk() if n.name.startswith("its@")]
    assert len(its) == 1 and its[0].path() == "/intc@8000000/its@8080000" and its[0].props["msi-controller"] == b""
    assert its[0].strings("compatible") == ["arm,gic-v3-its"] and tool.regions(its[0]) == [MAP["its"]]
    assert len(tool.having(root, "virtio,mmio")) == 32 and root.u32("#address-cells", 0) == 2 and root.u32("none", 5) == 5
    psci = [n for n in root.walk() if n.name == "psci"][0]
    assert psci.strings("compatible") == list(MAP["psci"]) and psci.strings("none") == []


# ------------------------------------------------------------------ the command, as a process

def _cli(*args):
    return subprocess.run([sys.executable, "-B", TOOL] + list(args), capture_output=True, text=True, timeout=60)


def test_the_command_exits_0_1_and_2_and_reads_its_own_checkout_by_default(tmp_path):
    good = write(tmp_path, GOOD, "good.dtb")
    r = _cli(good)
    assert r.returncode == 0 and "every one agrees" in r.stdout and "MISMATCH" not in r.stdout, r.stdout + r.stderr
    moved = write(tmp_path, fdt(virt(ecam=(0x4020000000, 0x10000000))), "moved.dtb")
    r = _cli(moved)
    assert r.returncode == 1 and r.stdout.count("\nMISMATCH") == 3, r.stdout + r.stderr
    r = _cli(write(tmp_path, b"not a tree", "junk.dtb"))
    assert r.returncode == 2 and r.stdout == "" and "nothing was compared" in r.stderr, r.stdout + r.stderr
    r = _cli()
    assert r.returncode == 2 and "usage" in r.stderr, r.stdout + r.stderr
    r = _cli(good, "--repo", str(tmp_path))
    assert r.returncode == 2 and r.stdout == "" and "nothing was compared" in r.stderr, r.stdout + r.stderr


def test_no_device_tree_blob_is_kept_in_the_repo():
    """The trees are built here. A dump of a real QEMU is capture data and stays out."""
    kept = [p for d in (HERE, TOOLS) for p in glob.glob(os.path.join(d, "**", "*.dtb"), recursive=True)]
    assert kept == [], kept
