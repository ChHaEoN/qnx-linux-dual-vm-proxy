#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""parse-s1.py: the PC side of S1-F (Phase 3b).

Implements results/orin-native-port/20260909T1100Z/s1-design.md (revision 2;
the owner took D1-D19 as recommended): the configuration gate of §3.7 (D13,
D19), the FDT checklist of §6.2 read with our own reader (D12), the tier and
pass rules of §5.1-§5.2 with D10's end_ok, and the pipe-free rule of §2 rule 7.
Standard library only.

  parse-s1.py conf FILE [--allow FILE] [--overlay FILE]
  parse-s1.py fdt DTB [--conf FILE]
  parse-s1.py run LOG [--profile tcg|board] [--mode dryrun|boot|hold|host|q2]
                  [--blackbox FILE] [--out-dir DIR|none] [--conf FILE]
                  [--ref-conf-sha256 HEX] [--reset-reason TEXT]
                  [--kexec-tree-sha256 HEX] [--image FILE] [--initrd FILE]
  parse-s1.py kshcheck FILE | --selftest
  parse-s1.py --selftest

conf   The gate. FILE is checked against s1-conf.allow (beside this script by
       default): keywords in the grammar places the allow-list permits, the vdev
       types, the forbidden words, and D19's one overlay approved by sha256. Also
       refused: a CR, NUL or non-ASCII byte, no final newline, a missing
       required directive, a vdev without loc and intr (§3.7: MMIO transports), a
       payload path outside /data/s1/ (C2). An approved overlay must also pass a
       screen: no node name, property name or string value (labels under
       __fixups__ included) matching gpu, nvidia, host1x, smmu, iommu or
       passthr, and no fragment targeted by phandle (target-path only, so the
       target can be read). Exit 0 pass, 1 fail.

fdt    Prints the §6.2 checklist of a qvm-dumped tree: gating rows (memory
       covering the configuration's ram line, GICv3, armv8 timer with
       interrupts, virtio,mmio at 0x20000000 with interrupts, /chosen/bootargs
       equal to the configuration's cmdline, the initrd inside guest RAM, a PSCI
       node with a method) and recorded rows, plus conf_gate= for --conf. Exit 0
       when every gating row is present and the configuration passes the gate, 1
       otherwise or on a malformed tree.

run    Reads a TCG serial log or a board COM3 capture (and, on the board, the
       black box), decodes the exports, and reports tiers L0-L7, pass items 1, 2,
       3, 4 and 5 for the step (T1 tcg/dryrun, T2 tcg/boot, T3 tcg/hold, B2
       board/host, B3 board/boot, B4 board/hold, B5 board/q2), and one verdict.
       Every step needs --conf to pass the gate (conf_gate=), and every step that
       stages the configuration (all but B2) needs its S1 CONFIG conf_sha256 and
       its target md5sum line for /data/s1/s1-linux.conf to equal the PC file's
       (§2 rule 2); B3, B4 and B5 also need --ref-conf-sha256, T2's. In a guest
       mode the target md5sum lines of Image, initrd.cpio.gz and s1-linux.conf
       must all be present (§5.2 item 5); --image and --initrd, when given, pin
       the Image and initrd lines and S1 CONFIG's image_sha256 and initrd_sha256
       to those PC files.
       Output: S1PC key=value lines on stdout and in OUT/parse-s1.txt, where OUT
       is --out-dir or the log's directory, plus each decoded export (fdt as
       s1-fdt.dtb). Every file written must be git-ignored (parse-m4.py's
       check_out_path); --out-dir none writes nothing. No FreeMem value and no
       duration is ever printed (§2 rule 8).

kshcheck  parse-m4.py's implementation, imported, so the rule cannot drift (§4.2).

Record formats this parser expects from the S1 host script (§5.1):
  S1 CONFIG <item-5 fields, below> [fdt=none on host mode]
  S1 MEM <label> <FreeMem as pidin prints it, e.g. 900MB/992MB>
  S1 GATE mem ok | S1 W2 reflected=yes
  S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no
  S1 CANARY c1|c2|c3 verify=ok
  S1 CHECK image|initrd|conf md5_pre|md5_post ok
  S1 STATE <name>                       (hostcheck and teardown are read)
  BWAIT run prog=qvm rc=.. sig=.. killed=0 ms=..   (bwait's own line, before S1 DRYRUN)
  S1 DRYRUN rc=<n> saved=yes fdt_bytes=<n> fdt_md5=<hex> logger_errors=0
  STAMP <label> ...                     (stamp's own line)
  S1 HOLD start secs=600 | S1 HOLD end qvm=alive
  S1 ALLOC hold mib=<n> fill=ok [verify=ok]   and a later line with verify=ok
  S1 ALLOC mib=1536 fill=ok verify=ok
  S1 HB k=<1..10> qvm=alive rc=absent
  S1 GUESTRAM w1=yes|no w2=yes|no | S1 GUESTRAM unknown
  S1 BOTH alive
  S1 FAIL_STATE none
  rc=<n>                                (cat of qvm.rc; before S1 STATE teardown it fails L4)
Exports, the framing of orin-native/m4dry/m4dry-host.ksh.in's kevblock with the
S1 prefix:
  S1 BEGIN name=<name> bytes=<n> md5=<hex> enc=base64
  <base64 lines>
  S1 END name=<name>
enc=gzip-base64 adds gz_bytes= and gz_md5= of the gzip layer, as m4dry does;
enc=text carries raw lines: the md5 is over the body lines exactly as captured,
trailing blanks kept, one trailing CR (the capture's) removed from each, each
ending in LF. It frames only LF-only text that ends in LF; anything else is base64.

Item-5 fields required in S1 CONFIG (§5.2 item 5): image_sha256 initrd_sha256
conf_sha256 cmdline_sha256 init_sha256 s1con_sha256 memcanary_sha256
stamp_sha256 bwait_sha256 startup_sha256 startup_line cpu_lines ram_line windows
canaries guest_set hold_s guard_s gpu_range. A TCG run gives the board-only ones
a non-empty placeholder (startup_sha256=tcg-profile, canaries=none,
gpu_range=none). Also required: fdt=none on host mode, and on the board
--kexec-tree-sha256 (p0's reading). A guest mode's FDT sha256 comes from its own
decoded export (§5.2 item 5); an export that is absent or does not decode fails
L2 and item 5 instead of refusing the verdict, because that is evidence that
failed, not a stamp left out. cmdline_sha256 is the sha256 of the cmdline
string between its quotes.

Exit (run): 0 a verdict was given, pass or fail; 3 the verdict is refused because
item-5 stamps are missing; 1 an input error; 2 a refused output path or a usage
error. Every figure from a run is evaluation output under NC QDL v7 4.6(i).
"""

import argparse
import base64
import binascii
import contextlib
import gzip
import hashlib
import importlib.util
import io
import os
import re
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
PARSE_M4_PATH = os.path.join(REPO, "orin-native", "m4", "parse-m4.py")
DEFAULT_CONF = os.path.join(HERE, "s1-linux.conf")
DEFAULT_ALLOW = os.path.join(HERE, "s1-conf.allow")


def _import_parse_m4():
    """parse-m4.py as a module. kshcheck is its implementation, not a copy (§4.2)."""
    spec = importlib.util.spec_from_file_location("parse_m4", PARSE_M4_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {PARSE_M4_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PM = _import_parse_m4()
Refused = PM.Refused
InputError = PM.InputError
redact = PM.redact
rel_repo = PM.rel_repo
parse_kv = PM.parse_kv
to_int = PM.to_int
kshcheck_text = PM.kshcheck_text
cmd_kshcheck = PM.cmd_kshcheck

MIB = 1 << 20
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def md5(b):
    return hashlib.md5(b).hexdigest()


def out_line(s):
    """A printed line: user names redacted, and ASCII only, so no console code page can fail on it."""
    return redact(s).encode("ascii", "backslashreplace").decode("ascii")


def q(s):
    """A value for a key=value line: single-quoted when it has a space, redacted."""
    s = out_line(str(s)).replace("'", '"')
    return f"'{s}'" if (not s or re.search(r"\s", s)) else s


# ------------------------------------------------------------------ design constants

# §3.7: the configuration text, byte for byte (the selftest compares the file).
DESIGN_CONF = (
    "system s1-linux\n"
    "logger error,fatal,internal,warn,info stderr\n"
    "ram 0x80000000,512M\n"
    "cpu cluster _cpu-1\n"
    "cpu cluster _cpu-2\n"
    "cpu cluster _cpu-3\n"
    "load /data/s1/Image\n"
    "initrd load /data/s1/initrd.cpio.gz\n"
    'cmdline "console=hvc0 earlycon=pl011,0x1c090000 keep_bootcon nokaslr rdinit=/init panic=-1 cma=16M loglevel=7"\n'
    "vdev pl011\n"
    " hostdev >-\n"
    " loc 0x1c090000\n"
    " intr gic:37\n"
    "vdev virtio-console\n"
    " loc 0x20000000\n"
    " intr gic:42\n"
    " hostdev /dev/ttyp3\n"
)

DESIGN_KEYWORDS = ("system", "logger", "ram", "cpu", "cluster", "load", "initrd", "cmdline", "vdev", "hostdev",
                   "loc", "intr")
DESIGN_VDEV_TYPES = ("pl011", "virtio-console")
DESIGN_FORBIDDEN = ("pass", "smmu", "fdt load", "virtio-net", "virtio-blk", "shmem")

# The grammar: where each allowed word may stand.
DIRECTIVES = ("system", "logger", "ram", "cpu", "load", "initrd", "cmdline", "vdev")
VDEV_OPTIONS = ("hostdev", "loc", "intr")
OPTION_WORDS = {"cpu": ("cluster",), "initrd": ("load",)}
ARITY = {"system": (2, 2), "logger": (2, 3), "ram": (2, 2), "load": (2, 2), "cmdline": (2, 2), "vdev": (2, 2),
         "hostdev": (2, 2), "loc": (2, 2), "intr": (2, 2), "initrd": (3, 3)}
ONCE = ("system", "load", "initrd", "cmdline")
REQUIRED = ("system", "ram", "cpu", "load", "initrd", "cmdline", "vdev")
PAYLOAD_DIR = "/data/s1/"
WORD_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OVERLAY_GPU_RE = re.compile(r"gpu|nvidia|host1x|smmu|iommu|passthr", re.IGNORECASE)

# §3.3 constants (board/t234_startup.h's, by the design's table).
CANARIES = {"c1": 0xBD000000, "c2": 0x100000000, "c3": 0x189000000}
CANARY_SIZE = 0x1000000

# §5.1 memory gate constants, MiB.
MEM_GATE_MIB = {("tcg", "dryrun"): 596, ("tcg", "boot"): 596, ("tcg", "hold"): 660, ("tcg", "q2"): 1255,
                ("board", "dryrun"): 596, ("board", "boot"): 596, ("board", "hold"): 852, ("board", "q2"): 1255}
W1_MIB = 992                 # host mode: FreeMem above window 1's total means window 2 is reflected
HOLD_MIB = {"tcg": 64, "board": 256}
HOLD_SECS = 600
HB_COUNT = 10
B2_ALLOC_MIB = 1536
BB_CAP = 65520               # the black box cap (§3.4)
BB_GATE = 60000              # M3's rebuild-at--vv rule and R22's T3 gate
IPC_ITERS = 15               # M3's completion rule for B5
IPC_PAYLOAD = 48

ITEM5_FIELDS = ("image_sha256", "initrd_sha256", "conf_sha256", "cmdline_sha256", "init_sha256", "s1con_sha256",
                "memcanary_sha256", "stamp_sha256", "bwait_sha256", "startup_sha256", "startup_line", "cpu_lines",
                "ram_line", "windows", "canaries", "guest_set", "hold_s", "guard_s", "gpu_range")

GUEST_MODES = ("dryrun", "boot", "hold", "q2")
LAUNCH_MODES = ("boot", "hold", "q2")

# The firmware banner after the image's reset (m5-design.md C12: the hotkey lines of
# NV PlatformBm.c, then L4TLauncher). The exact texts are HYPOTHESIS: not read here.
FW_BANNER = ("ESC to enter Setup", "F11 to enter Boot Manager Menu", "L4TLauncher:", "MB1")

# Every step needs the configuration to pass the §3.7 gate. Every step that stages it
# (all but B2) needs literal identity with the PC file (§2 rule 2), and every board
# step after T2 also identity with T2's conf_sha256 (--ref-conf-sha256).
STEPS = {
    ("tcg", "dryrun"): ("T1", ("conf_gate", "profile", "L2", "fdt_gating", "conf_identity", "item5")),
    ("tcg", "boot"): ("T2", ("conf_gate", "profile", "L2", "fdt_gating", "L4", "L5", "conf_identity", "item5")),
    ("tcg", "hold"): ("T3", ("conf_gate", "profile", "t3", "bb_text", "conf_identity", "item5")),
    ("tcg", "q2"): ("T3-q2", ("conf_gate", "profile", "L2", "fdt_gating", "L5", "item3", "conf_identity", "item5")),
    ("board", "host"): ("B2", ("conf_gate", "L0", "L1", "b2", "L7", "canaries_all_ok", "item5")),
    ("board", "dryrun"): ("B3-dryrun", ("conf_gate", "L0", "L1", "L2", "fdt_gating", "L7", "canaries_all_ok",
                                        "conf_identity", "item5")),
    ("board", "boot"): ("B3", ("conf_gate", "L0", "L1", "L2", "fdt_gating", "L4", "L5", "L7", "canaries_all_ok",
                               "conf_identity", "conf_ref", "item5")),
    ("board", "hold"): ("B4", ("conf_gate", "L6", "L7", "canaries_all_ok", "conf_identity", "conf_ref", "item5")),
    ("board", "q2"): ("B5", ("conf_gate", "L5", "item3", "L7", "canaries_all_ok", "conf_identity", "conf_ref",
                             "item5")),
}
ITEM1_T1_NEEDS = ("conf_gate", "profile", "L2", "fdt_gating", "conf_identity")
ITEM1_T2_NEEDS = ("conf_gate", "profile", "L2", "fdt_gating", "L4", "L5", "conf_identity")
ITEM2_NEEDS = ("conf_gate", "L0", "L1", "L2", "fdt_gating", "L4", "L5", "L7", "canaries_all_ok", "conf_identity",
               "conf_ref")
ITEM4_NEEDS = ("conf_gate", "L6", "L7", "canaries_all_ok", "conf_identity", "conf_ref")


# ------------------------------------------------------------------ conf: the gate (§3.7)

class Allow:
    def __init__(self):
        self.keywords = set()
        self.vdev_types = set()
        self.forbidden = set()
        self.overlays = []


def parse_allow(text):
    """(Allow, errors). An error makes the allow-list itself invalid, so the gate fails."""
    al = Allow()
    errors = []
    grammar = set(DIRECTIVES) | set(VDEV_OPTIONS) | {w for ws in OPTION_WORDS.values() for w in ws}
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("vdev:"):
            t = line[5:].strip()
            if WORD_RE.match(t):
                al.vdev_types.add(t)
            else:
                errors.append(f"line={n} reason=bad-vdev-type")
        elif line.startswith("forbid:"):
            words = line[7:].split()
            if words and all(WORD_RE.match(w) for w in words):
                al.forbidden.add(" ".join(words))
            else:
                errors.append(f"line={n} reason=bad-forbid")
        elif line.startswith("overlay-sha256:"):
            h = line[len("overlay-sha256:"):].strip().lower()
            if HEX64_RE.match(h):
                al.overlays.append(h)
            else:
                errors.append(f"line={n} reason=bad-overlay-sha256")
        elif WORD_RE.match(line):
            if line in grammar:
                al.keywords.add(line)
            else:
                errors.append(f"line={n} word={line} reason=no-place-in-grammar")
        else:
            errors.append(f"line={n} reason=unparsed")
    for f in DESIGN_FORBIDDEN:
        if f not in al.forbidden:
            errors.append(f"forbid={f.replace(' ', '_')} reason=missing-from-allow-list")
    for t in sorted(al.vdev_types):
        if t not in DESIGN_VDEV_TYPES:
            errors.append(f"vdev={t} reason=beyond-design")
    for w in sorted(al.keywords | al.vdev_types):
        if any(forbidden_hit(f.split(), [w]) for f in al.forbidden):
            errors.append(f"word={w} reason=allowed-and-forbidden")
    if len(al.overlays) > 1:
        errors.append("overlay-sha256 reason=more-than-one")
    return al, errors


def conf_tokens(line):
    """(quoted, text) tokens of one line; a double-quoted string is one token."""
    toks = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise ValueError("unterminated-quote")
            if j + 1 < n and line[j + 1] not in " \t":
                raise ValueError("text-glued-to-quote")
            toks.append((True, line[i + 1:j]))
            i = j + 1
            continue
        j = i
        while j < n and line[j] not in " \t":
            if line[j] in '"#':
                raise ValueError("quote-or-hash-inside-word")
            j += 1
        toks.append((False, line[i:j]))
        i = j
    return toks


def forbidden_hit(fwords, low):
    """True when the forbidden word sequence stands in the unquoted lower-case words."""
    if len(fwords) > 1:
        return any(low[k:k + len(fwords)] == fwords for k in range(len(low) - len(fwords) + 1))
    rx = re.compile(r"(?:^|[-,:=])" + re.escape(fwords[0]) + r"(?:$|[-,:=])")
    return any(w is not None and rx.search(w) for w in low)


def payload_path_ok(p):
    return (p.startswith(PAYLOAD_DIR) and len(p) > len(PAYLOAD_DIR) and not p.endswith("/")
            and "/../" not in p + "/" and "/./" not in p + "/" and "//" not in p)


def parse_ram(spec):
    m = re.fullmatch(r"(0x[0-9a-fA-F]+|\d+),(0x[0-9a-fA-F]+|\d+)([KMG]?)", spec or "")
    if not m:
        raise InputError(f"ram line {spec!r} is not <base>,<size>[K|M|G]")
    return int(m.group(1), 0), int(m.group(2), 0) << {"": 0, "K": 10, "M": 20, "G": 30}[m.group(3)]


def _prop_texts(v):
    """The strings of a property value that is a printable NUL-terminated string list, else []."""
    if not v or v[-1:] != b"\0":
        return []
    parts = v[:-1].split(b"\0")
    if any(not p or any(c < 0x20 or c > 0x7E for c in p) for p in parts):
        return []
    return [p.decode("ascii") for p in parts]


def overlay_screen(root):
    """(reason, detail) of the first thing D19's screen refuses in an overlay, or None.

    Node names, property names and string values are all read, so a label under
    __fixups__ or __symbols__, a phandle property such as iommus, and a target-path
    each count. A fragment's target by phandle cannot be read, so it is refused.
    """
    for node in root.walk():
        if "target" in node.props:
            return "overlay-target-by-phandle", f"{node.path()}:target"
        texts = [node.name]
        for pn, pv in node.props.items():
            texts += [pn] + _prop_texts(pv)
        hit = next((t for t in texts if OVERLAY_GPU_RE.search(t)), None)
        if hit is not None:
            return "overlay-names-gpu-smmu-or-iommu", f"{node.path()}:{hit}"
    return None


def conf_check(conf_bytes, allow_text, conf_dir, overlay_file=None):
    """§3.7's gate. Returns (ok, out lines, info)."""
    out = []
    rejects = []
    info = {"cmdline": None, "ram": None, "cpu_lines": [], "vdevs": [], "overlay": "none"}
    al, aerr = parse_allow(allow_text)
    for e in aerr:
        out.append(f"allow_error {e}")

    def reject(n, reason, word=None):
        rejects.append(f"reject line={n} reason={reason}" + (f" word={q(word)}" if word is not None else ""))

    if not conf_bytes:
        reject(0, "empty")
    if b"\r" in conf_bytes:
        reject(0, "carriage-return")
    if any(b > 0x7E or (b < 0x20 and b not in (0x09, 0x0A)) for b in conf_bytes):
        reject(0, "non-ascii-or-control-byte")
    if conf_bytes and not conf_bytes.endswith(b"\n"):
        reject(0, "no-final-newline")
    text = conf_bytes.decode("latin-1").replace("\r", "")
    seen = {}
    vdev = None
    fdt_lines = []
    for n, raw in enumerate(text.split("\n"), 1):
        s = raw.strip(" \t")
        if not s or s.startswith("#"):
            continue
        try:
            toks = conf_tokens(s)
        except ValueError as e:
            reject(n, str(e))
            continue
        words = [t for _, t in toks]
        low = [None if qu else t.lower() for qu, t in toks]
        hit = None
        for f in sorted(al.forbidden):
            if f == "fdt load" and al.overlays:
                continue            # D19: judged below
            if forbidden_hit(f.split(), low):
                hit = f
                break
        if hit:
            reject(n, "forbidden", hit)
            continue
        kw = low[0]
        if kw is None:
            reject(n, "quoted-keyword")
            continue
        if kw == "fdt" and al.overlays:
            vdev = None
            if len(toks) == 3 and low[1] == "load" and low[2] is not None:
                fdt_lines.append((n, words[2]))
            else:
                reject(n, "fdt-not-a-load-line")
            continue
        if kw in DIRECTIVES:
            vdev = None
        if kw not in al.keywords:
            reject(n, "keyword-not-allowed", kw)
            continue
        if kw in VDEV_OPTIONS:
            if vdev is None:
                reject(n, "vdev-option-outside-vdev", kw)
                continue
        elif kw not in DIRECTIVES:
            reject(n, "not-a-directive", kw)
            continue
        if kw == "cpu":
            opts = toks[1:]
            if len(opts) % 2:
                reject(n, "cpu-option-without-value")
                continue
            bad = None
            for k in range(0, len(opts), 2):
                w = opts[k][1].lower()
                if opts[k][0] or w not in OPTION_WORDS["cpu"] or w not in al.keywords or opts[k + 1][0]:
                    bad = opts[k][1]
                    break
            if bad is not None:
                reject(n, "cpu-option-not-allowed", bad)
                continue
            info["cpu_lines"].append(" ".join(words))
        else:
            lo, hi = ARITY[kw]
            if not lo <= len(toks) <= hi:
                reject(n, "token-count", kw)
                continue
            quoted = [k for k, (qu, _) in enumerate(toks) if qu]
            if kw == "cmdline":
                if quoted != [1]:
                    reject(n, "cmdline-not-quoted")
                    continue
                info["cmdline"] = words[1]
            elif quoted:
                reject(n, "quoted-value", kw)
                continue
            if kw == "initrd":
                if low[1] not in OPTION_WORDS["initrd"] or low[1] not in al.keywords:
                    reject(n, "initrd-option-not-allowed", words[1])
                    continue
                if not payload_path_ok(words[2]):
                    reject(n, "path-outside-data-s1", words[2])
                    continue
            if kw == "load" and not payload_path_ok(words[1]):
                reject(n, "path-outside-data-s1", words[1])
                continue
            if kw == "vdev":
                if low[1] not in al.vdev_types:
                    reject(n, "vdev-type-not-allowed", words[1])
                    continue
                vdev = {"type": low[1], "line": n, "opts": {}}
                info["vdevs"].append(vdev)
            if kw in VDEV_OPTIONS:
                if kw in vdev["opts"]:
                    reject(n, "vdev-option-twice", kw)
                    continue
                vdev["opts"][kw] = words[1]
            if kw == "ram":
                info["ram"] = words[1]
        seen[kw] = seen.get(kw, 0) + 1
    for r in REQUIRED:
        if not seen.get(r):
            reject(0, "missing-required", r)
    for k in ONCE:
        if seen.get(k, 0) > 1:
            reject(0, "more-than-once", k)
    for v in info["vdevs"]:
        for o in ("loc", "intr"):
            if o not in v["opts"]:
                reject(v["line"], "vdev-without-" + o, v["type"])
    if fdt_lines:
        if len(fdt_lines) > 1:
            reject(fdt_lines[1][0], "fdt-load-more-than-once")
        n, path = fdt_lines[0]
        if not payload_path_ok(path):
            reject(n, "path-outside-data-s1", path)
        else:
            pc = overlay_file or os.path.join(conf_dir, path.rsplit("/", 1)[1])
            try:
                with open(pc, "rb") as f:
                    ov = f.read()
            except OSError:
                reject(n, "overlay-file-missing", path.rsplit("/", 1)[1])
            else:
                h = sha256(ov)
                if h not in al.overlays:
                    reject(n, "overlay-sha256-not-approved")
                else:
                    try:
                        root, _ = fdt_parse(ov)
                    except InputError:
                        reject(n, "overlay-not-an-fdt")
                    else:
                        screen = overlay_screen(root)
                        if screen:
                            reject(n, screen[0], screen[1])
                        else:
                            info["overlay"] = h
    elif al.overlays:
        out.append("overlay approved=yes used=no")
    out += rejects
    if info["cmdline"] is not None:
        out.append(f"cmdline_sha256={sha256(info['cmdline'].encode('latin-1'))}")
    out.append(f"ram={q(info['ram'] or 'none')} cpu_lines={len(info['cpu_lines'])} "
               f"vdevs={','.join(v['type'] for v in info['vdevs']) or 'none'} overlay={info['overlay']}")
    ok = not aerr and not rejects
    out.append(f"gate={'pass' if ok else 'fail'} rejects={len(rejects)} allow_errors={len(aerr)}")
    return ok, out, info


def load_conf_facts(conf_path, allow_path=DEFAULT_ALLOW):
    conf_bytes = PM.read_bytes(conf_path)
    allow_text = PM.read_bytes(allow_path).decode("latin-1")
    ok, _, info = conf_check(conf_bytes, allow_text, os.path.dirname(os.path.abspath(conf_path)))
    if info["cmdline"] is None or info["ram"] is None:
        raise InputError(f"{rel_repo(conf_path)} has no usable cmdline or ram line")
    return conf_bytes, info, ok


def cmd_conf(a):
    conf_bytes = PM.read_bytes(a.file)
    allow_path = a.allow or DEFAULT_ALLOW
    allow_bytes = PM.read_bytes(allow_path)
    ok, lines, _ = conf_check(conf_bytes, allow_bytes.decode("latin-1"), os.path.dirname(os.path.abspath(a.file)),
                              a.overlay)
    print(out_line(f"S1CONF file={rel_repo(a.file)} sha256={sha256(conf_bytes)} bytes={len(conf_bytes)}"))
    print(out_line(f"S1CONF allow={rel_repo(allow_path)} sha256={sha256(allow_bytes)}"))
    for ln in lines:
        print(out_line("S1CONF " + ln))
    return 0 if ok else 1


# ------------------------------------------------------------------ fdt: a stdlib FDT v17 reader (§6.2, D12)

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


class FdtNode:
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

    def child(self, name):
        return next((c for c in self.children if c.name == name), None)

    def prop_strs(self, name):
        v = self.props.get(name)
        if not v:
            return []
        return [s.decode("latin-1") for s in v.rstrip(b"\0").split(b"\0")]

    def prop_str(self, name):
        s = self.prop_strs(name)
        return s[0] if s else None

    def cells(self, name, default):
        v = self.props.get(name)
        return int.from_bytes(v, "big") if v is not None and len(v) == 4 else default


def _cstr(data, pos, end):
    k = data.find(b"\0", pos, end)
    if k < 0:
        raise InputError("FDT string runs past its block")
    return data[pos:k].decode("latin-1"), k + 1


def fdt_parse(data):
    """(root, header facts) of a flattened device tree, version 16 or 17. InputError when malformed."""
    if len(data) < 40:
        raise InputError("FDT shorter than its 40-byte header")
    (magic, total, off_st, off_str, off_rsv, version, last_comp, _boot_cpu, size_str,
     size_st) = struct.unpack_from(">10I", data, 0)
    if magic != FDT_MAGIC:
        raise InputError(f"FDT magic 0x{magic:08x}, not d00dfeed")
    if total < 40 or total > len(data):
        raise InputError("FDT totalsize is outside the file")
    if version < 16 or last_comp > 17:
        raise InputError(f"FDT version {version} (last compatible {last_comp}) is not readable as v17")
    if version < 17:
        size_st = total - off_st
    for off, size in ((off_st, size_st), (off_str, size_str), (off_rsv, 16)):
        if off < 40 or off > total or size > total - off:
            raise InputError("FDT block lies outside totalsize")
    pos = off_rsv
    rsv = []
    while True:
        if pos + 16 > total:
            raise InputError("FDT reserve map is not terminated")
        a, s = struct.unpack_from(">QQ", data, pos)
        pos += 16
        if a == 0 and s == 0:
            break
        rsv.append((a, s))
    end = off_st + size_st
    str_end = off_str + size_str
    root = None
    stack = []
    pos = off_st

    def align(p):
        return off_st + ((p - off_st + 3) & ~3)

    while True:
        if pos + 4 > end:
            raise InputError("FDT structure block ends without FDT_END")
        tok = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if tok == FDT_BEGIN_NODE:
            name, pos = _cstr(data, pos, end)
            pos = align(pos)
            node = FdtNode(name, stack[-1] if stack else None)
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                if name != "":
                    raise InputError("FDT root node has a name")
                root = node
            else:
                raise InputError("FDT has a second root node")
            stack.append(node)
        elif tok == FDT_END_NODE:
            if not stack:
                raise InputError("FDT_END_NODE with no open node")
            stack.pop()
        elif tok == FDT_PROP:
            if not stack or pos + 8 > end:
                raise InputError("FDT property outside a node")
            ln, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            if ln > end - pos:
                raise InputError("FDT property runs past the structure block")
            val = bytes(data[pos:pos + ln])
            pos = align(pos + ln)
            if nameoff >= size_str:
                raise InputError("FDT property name offset outside the strings block")
            pname, _ = _cstr(data, off_str + nameoff, str_end)
            stack[-1].props[pname] = val
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            if stack:
                raise InputError("FDT_END inside an open node")
            break
        else:
            raise InputError(f"FDT unknown token 0x{tok:x}")
    if root is None:
        raise InputError("FDT has no root node")
    return root, {"version": version, "last_comp": last_comp, "totalsize": total, "rsv": len(rsv)}


def _be(b):
    return int.from_bytes(b, "big")


def fdt_translate(bus, addr):
    """addr in bus's child address space, carried to the root through each ranges; None if untranslatable."""
    node = bus
    while node.parent is not None:
        r = node.props.get("ranges")
        if r is None:
            return None
        if r:
            cac = node.cells("#address-cells", 2)
            csc = node.cells("#size-cells", 1)
            pac = node.parent.cells("#address-cells", 2)
            step = 4 * (cac + pac + csc)
            if step == 0 or len(r) % step:
                return None
            for i in range(0, len(r), step):
                c = _be(r[i:i + 4 * cac])
                p = _be(r[i + 4 * cac:i + 4 * (cac + pac)])
                s = _be(r[i + 4 * (cac + pac):i + step])
                if c <= addr < c + s:
                    addr = p + (addr - c)
                    break
            else:
                return None
        node = node.parent
    return addr


def fdt_reg(node):
    """[(root address or None, child address, size)] of node's reg."""
    par = node.parent
    v = node.props.get("reg")
    if par is None or v is None:
        return []
    ac = par.cells("#address-cells", 2)
    sc = par.cells("#size-cells", 1)
    step = 4 * (ac + sc)
    if ac == 0 or len(v) % step:
        return []
    out = []
    for i in range(0, len(v), step):
        a = _be(v[i:i + 4 * ac])
        s = _be(v[i + 4 * ac:i + step]) if sc else 0
        out.append((fdt_translate(par, a), a, s))
    return out


def _reg_at(node, addr):
    return any((t if t is not None else a) == addr for t, a, _ in fdt_reg(node))


def _cells_hex(v):
    if not v or len(v) % 4:
        return "none"
    return ",".join("0x%x" % _be(v[i:i + 4]) for i in range(0, len(v), 4))


def fdt_checklist(data, cmdline, ram_base, ram_size):
    """§6.2 step 4. Returns (rows, header): rows are (kind gate|rec, key, ok, detail)."""
    root, hdr = fdt_parse(data)
    nodes = list(root.walk())
    rows = []

    def compat_has(n, text):
        return any(text in c for c in n.prop_strs("compatible"))

    def has_intr(n):
        return bool(n.props.get("interrupts")) or bool(n.props.get("interrupts-extended"))

    mem = None
    for n in nodes:
        if n.prop_str("device_type") == "memory" or (n.parent is root and re.match(r"^memory(@|$)", n.name)):
            for t, a, s in fdt_reg(n):
                b = t if t is not None else a
                if b <= ram_base and b + s >= ram_base + ram_size:
                    mem = n
                    break
        if mem is not None:
            break
    rows.append(("gate", "memory", mem is not None,
                 f"node={mem.path()}" if mem else f"want=0x{ram_base:x}+0x{ram_size:x}"))
    gic = next((n for n in nodes if compat_has(n, "arm,gic-v3")), None)
    rows.append(("gate", "gicv3", gic is not None, f"node={gic.path()}" if gic else "absent"))
    timers = [n for n in nodes if compat_has(n, "arm,armv8-timer")]
    timer = next((n for n in timers if has_intr(n)), None)
    rows.append(("gate", "timer", timer is not None,
                 f"node={timer.path()}" if timer else ("no-interrupts" if timers else "absent")))
    virtios = [n for n in nodes if compat_has(n, "virtio,mmio")]
    virtio = next((n for n in virtios if _reg_at(n, 0x20000000) and has_intr(n)), None)
    rows.append(("gate", "virtio_mmio", virtio is not None,
                 f"node={virtio.path()}" if virtio else f"none-at-0x20000000-with-interrupts candidates={len(virtios)}"))
    chosen = root.child("chosen")
    ba = chosen.props.get("bootargs") if chosen else None
    ba_text = ba.rstrip(b"\0").decode("latin-1") if ba is not None else None
    rows.append(("gate", "bootargs", ba_text is not None and ba_text == cmdline,
                 "match" if ba_text == cmdline else ("absent" if ba_text is None else f"dumped={q(ba_text)}")))
    ist = chosen.props.get("linux,initrd-start") if chosen else None
    ien = chosen.props.get("linux,initrd-end") if chosen else None
    ok_i = False
    detail = "absent"
    if ist is not None and ien is not None and len(ist) in (4, 8) and len(ien) in (4, 8):
        s, e = _be(ist), _be(ien)
        ok_i = ram_base <= s < e <= ram_base + ram_size
        detail = f"start=0x{s:x} end=0x{e:x}" + ("" if ok_i else " outside-guest-ram")
    rows.append(("gate", "initrd", ok_i, detail))
    psci_nodes = [n for n in nodes if compat_has(n, "arm,psci")]
    psci = next((n for n in psci_nodes if n.prop_str("method")), None)
    rows.append(("gate", "psci", psci is not None,
                 f"node={psci.path()}" if psci else ("no-method" if psci_nodes else "absent")))

    pn = psci or (psci_nodes[0] if psci_nodes else None)
    rows.append(("rec", "psci_method", True, q(pn.prop_str("method") or "none") if pn else "none"))
    rows.append(("rec", "psci_compatible", True, q(",".join(pn.prop_strs("compatible"))) if pn else "none"))
    cpus = [n for n in nodes if n.prop_str("device_type") == "cpu"]
    methods = sorted({n.prop_str("enable-method") or "none" for n in cpus})
    rows.append(("rec", "cpus", True, f"{len(cpus)} enable_methods={q(','.join(methods) or 'none')}"))
    pl = next((n for n in nodes if compat_has(n, "arm,pl011") and _reg_at(n, 0x1C090000)), None)
    rows.append(("rec", "pl011", True,
                 f"{pl.path()} clocks={'present' if 'clocks' in pl.props else 'absent'} "
                 f"clock_names={q(','.join(pl.prop_strs('clock-names')) or 'none')}" if pl else "absent"))
    sp = chosen.prop_str("stdout-path") if chosen else None
    rows.append(("rec", "stdout_path", True, q(sp) if sp is not None else "absent"))
    rows.append(("rec", "kaslr_seed", True, "present" if chosen and "kaslr-seed" in chosen.props else "absent"))
    rows.append(("rec", "interrupts_gic37", True, _cells_hex(pl.props.get("interrupts")) if pl else "no-pl011"))
    vi = virtio or next((n for n in virtios if _reg_at(n, 0x20000000)), None)
    rows.append(("rec", "interrupts_gic42", True, _cells_hex(vi.props.get("interrupts")) if vi else "no-virtio"))
    return rows, hdr


def fdt_lines(rows, prefix):
    out = []
    for kind, key, ok, detail in rows:
        if kind == "gate":
            out.append(f"{prefix}gate {key}={'ok' if ok else 'missing'} {detail}")
        else:
            out.append(f"{prefix}rec {key}={detail}")
    missing = [key for kind, key, ok, _ in rows if kind == "gate" and not ok]
    out.append(f"{prefix}gating=" + ("ok" if not missing else "missing rows=" + ",".join(missing)))
    return out, not missing


def cmd_fdt(a):
    data = PM.read_bytes(a.dtb)
    conf_path = a.conf or DEFAULT_CONF
    conf_bytes, info, gate_ok = load_conf_facts(conf_path)
    base, size = parse_ram(info["ram"])
    print(out_line(f"S1FDT file={rel_repo(a.dtb)} sha256={sha256(data)} bytes={len(data)}"))
    print(out_line(f"S1FDT conf={rel_repo(conf_path)} sha256={sha256(conf_bytes)} "
                   f"conf_gate={'pass' if gate_ok else 'fail'}"))
    rows, hdr = fdt_checklist(data, info["cmdline"], base, size)
    print(f"S1FDT magic=d00dfeed version={hdr['version']} last_comp={hdr['last_comp']} "
          f"totalsize={hdr['totalsize']} rsv_entries={hdr['rsv']}")
    lines, ok = fdt_lines(rows, "")
    for ln in lines:
        print(out_line("S1FDT " + ln))
    return 0 if ok and gate_ok else 1


# ------------------------------------------------------------------ run: tiers and pass items (§5.1, §5.2)

BEGIN_RE = re.compile(r"^S1 BEGIN name=(\S+)(?: (.*))?$")
END_RE = re.compile(r"^S1 END name=(\S+)\s*$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

RX = {
    "shim": re.compile(r"T234-SHIM EL=2(?![0-9])"),
    "shim_pc": re.compile(r"\bPC=0000000080080000\b"),
    "wdt0": re.compile(r"t234: WDT0 CR="),
    "ram_w2": re.compile(r"t234: ram w2 base=0x100000000 size=0x8a000000(?!\S)"),
    "gpu_range": re.compile(r"t234: gpu range base=0x18a000000 size=0xc0000000 not added(?!\S)"),
    "procnto_up": re.compile(r"T234 S1 (\S+) -P4: procnto up(?!\S)"),
    "reset": re.compile(r"T234 S1 (\S+) -P4: resetting so the log can be recovered"),
    "guard": re.compile(r"^BWAIT guard armed secs=(\d+)"),
    "guard_expired": re.compile(r"BWAIT guard deadline"),
    "config": re.compile(r"^S1 CONFIG(?: (.*))?$"),
    "mem_boot": re.compile(r"^S1 MEM boot (\S+)"),
    "mem_hb10": re.compile(r"^S1 MEM hb10 \S+"),
    "gate_mem": re.compile(r"^S1 GATE mem ok(?!\S)"),
    "w2": re.compile(r"^S1 W2 reflected=(\S+)"),
    "asinfo": re.compile(r"^S1 ASINFO\b"),
    "asinfo_ok": re.compile(r"^S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no "
                            r"gpu_in_sysram=no\s*$"),
    "canary": re.compile(r"^S1 CANARY (\S+)(?: (.*))?$"),
    "check": re.compile(r"^S1 CHECK (image|initrd|conf) md5_(pre|post) ok(?!\S)"),
    "hostcheck": re.compile(r"^S1 STATE hostcheck(?!\S)"),
    "teardown": re.compile(r"^S1 STATE teardown(?!\S)"),
    "dryrun": re.compile(r"^S1 DRYRUN(?: (.*))?$"),
    "bwait_qvm": re.compile(r"^BWAIT run prog=qvm rc=(-?\d+) sig=(\d+) killed=([01])"),
    "stamp": re.compile(r"^STAMP (\S+)"),
    "qvm_rc": re.compile(r"^(?:rc=-?\d+\s*|S1 QVM ended\b.*)$"),
    "hold_start": re.compile(r"^S1 HOLD start secs=(\d+)(?!\S)"),
    "hold_end": re.compile(r"^S1 HOLD end qvm=(\S+)"),
    "alloc_hold": re.compile(r"^S1 ALLOC hold mib=(\d+)(?: (.*))?$"),
    "alloc": re.compile(r"^S1 ALLOC mib=(\d+)(?: (.*))?$"),
    "hb": re.compile(r"^S1 HB(?: (.*))?$"),
    "fail_state": re.compile(r"^S1 FAIL_STATE (\S+)"),
    "fail": re.compile(r"^S1 FAIL(?:\s|$)"),
    "guestram": re.compile(r"^S1 GUESTRAM (.*)$"),
    "both": re.compile(r"^S1 BOTH alive(?!\S)"),
    "samples": re.compile(r"^samples=(\d+) payload=(\d+) cps=\d+"),
    "md5line": re.compile(r"^([0-9a-fA-F]{32})\s+\S*/data/s1/(Image|initrd\.cpio\.gz|s1-linux\.conf)\s*$"),
}
CANARY_FILL_RE = {c: re.compile(r"t234: canary " + c + r" base=(0x[0-9a-fA-F]+) size=0x1000000 filled(?!\S)")
                  for c in CANARIES}
NEG_L0 = (("bad_landing", re.compile(r"BAD-LANDING")), ("exc", re.compile(r"EXC ")),
          ("el_not_2", re.compile(r"EL!=2")), ("canary_overlaps", re.compile(r"t234: canary c\d+ overlaps")))
BB_PREFIXES = ("S1 ", "STAMP ", "BWAIT ", "T234 ", "T234-SHIM", "t234: ")


def split_log(data):
    """(record lines, export blocks, raw lines, block-body line indexes) of a log.

    Record lines are (index, text left-stripped, CR removed). A capture header and
    footer (orin-native/m4/parse-m4.py's parse_capture) are cut first. A block that
    never sees its S1 END gives its body back to the record lines.
    """
    cs, ce = 0, len(data)
    if data.startswith(b"--- raw capture started"):
        cap = PM.parse_capture(data, "capture")
        cs, ce = cap["cs"], cap["ce"]
    raw = data[cs:ce].decode("latin-1").split("\n")
    recs = []
    blocks = []
    body_idx = set()
    cur = None

    def close_unended(blk):
        blocks.append(blk)
        recs.extend((i, s) for i, _t, s in blk["body"])

    for i, line in enumerate(raw):
        t = line.replace("\r", "").rstrip(" \t")
        s = t.lstrip(" \t")
        tb = line[:-1] if line.endswith("\r") else line     # enc=text body: as captured, less the capture's CR
        if cur is not None:
            m = END_RE.match(s)
            if m and m.group(1) == cur["name"]:
                cur["ended"] = True
                body_idx.update(j for j, _t, _s in cur["body"])
                blocks.append(cur)
                cur = None
                recs.append((i, s))
                continue
            if BEGIN_RE.match(s):
                close_unended(cur)
                cur = None
            else:
                cur["body"].append((i, tb, s))
                continue
        mb = BEGIN_RE.match(s)
        if mb:
            kv, _ = parse_kv(mb.group(2) or "")
            cur = {"name": mb.group(1), "kv": kv, "begin": i, "body": [], "ended": False}
            recs.append((i, s))
            continue
        recs.append((i, s))
    if cur is not None:
        close_unended(cur)
    recs.sort(key=lambda r: r[0])
    return recs, blocks, raw, body_idx


def decode_block(blk):
    """Decode and md5-check one export. Sets blk['status'], and blk['data'] and blk['sha256'] when ok."""
    kv = blk["kv"]
    enc = kv.get("enc", "base64")
    blk["data"] = None
    if not NAME_RE.match(blk["name"]):
        blk["status"] = "bad-name"
        return
    if not blk["ended"]:
        blk["status"] = "truncated"
        return
    if enc in ("base64", "gzip-base64"):
        if any(not B64_RE.match(s) for _i, _t, s in blk["body"]):
            blk["status"] = "bad-line"
            return
        try:
            raw = base64.b64decode("".join(s for _i, _t, s in blk["body"]), validate=True)
        except (binascii.Error, ValueError):
            blk["status"] = "bad-base64"
            return
        if enc == "gzip-base64":
            if to_int(kv.get("gz_bytes")) != len(raw) or (kv.get("gz_md5") or "").lower() != md5(raw):
                blk["status"] = "gz-mismatch"
                return
            try:
                raw = gzip.decompress(raw)
            except (OSError, EOFError, zlib.error):
                blk["status"] = "gz-corrupt"
                return
    elif enc == "text":
        raw = "".join(t + "\n" for _i, t, _s in blk["body"]).encode("latin-1")
    else:
        blk["status"] = "unknown-enc"
        return
    bad = []
    if to_int(kv.get("bytes")) != len(raw):
        bad.append("bytes")
    if (kv.get("md5") or "").lower() != md5(raw):
        bad.append("md5")
    if bad:
        blk["status"] = "mismatch(" + "+".join(bad) + ")"
        return
    blk["status"] = "ok"
    blk["data"] = raw
    blk["sha256"] = sha256(raw)


def export_filename(name):
    return "s1-fdt.dtb" if name == "fdt" else f"s1-{name}.bin"


class Recs:
    def __init__(self, recs):
        self.r = recs

    def first(self, rx, after=None, before=None):
        for i, t in self.r:
            if after is not None and i <= after:
                continue
            if before is not None and i >= before:
                break
            m = rx.search(t)
            if m:
                return i, m
        return None, None

    def all(self, rx, after=None, before=None):
        out = []
        for i, t in self.r:
            if after is not None and i <= after:
                continue
            if before is not None and i >= before:
                break
            m = rx.search(t)
            if m:
                out.append((i, m))
        return out

    def lines(self, prefixes):
        return [t for _, t in self.r if t.startswith(prefixes)]


def mem_mib(v):
    m = re.match(r"^(\d+)([KkMmGg])i?[Bb]?(?:/.*)?$", v or "")
    if not m:
        return None
    n = int(m.group(1))
    u = m.group(2).upper()
    return n // 1024 if u == "K" else n * 1024 if u == "G" else n


def kvs(m, group):
    return parse_kv(m.group(group) or "")[0] if m else {}


def is_subsequence(sub, seq):
    """(True, -1) when sub is a subsequence of seq, else (False, index of the first sub line not found)."""
    k = 0
    for line in seq:
        if k < len(sub) and line == sub[k]:
            k += 1
    return k == len(sub), (-1 if k == len(sub) else k)


def analyze_run(data, *, profile, mode, conf_bytes, conf_info, conf_gate_ok, bb_data=None, ref_conf_sha256=None,
                reset_reason=None, kexec_tree_sha256=None, pc_image=None, pc_initrd=None):
    """The §5.1 tiers and §5.2 items of one run. Returns a dict: lines, blocks, verdict, refused.

    conf_gate_ok is conf_check's result for conf_bytes; pc_image and pc_initrd are
    the PC's payload bytes, or None when not given.
    """
    out = []
    put = lambda k, v: out.append(f"{k}={v}")  # noqa: E731
    board = profile == "board"
    guest = mode in GUEST_MODES
    launched = mode in LAUNCH_MODES
    hold = mode == "hold"
    recs, blocks, raw, body_idx = split_log(data)
    R = Recs(recs)
    miss = {}

    def need(comp, cond, reason):
        miss.setdefault(comp, [])
        if not cond:
            miss[comp].append(reason)

    miss["conf_gate"] = [] if conf_gate_ok else ["conf_fails_gate"]
    put("conf_gate", "pass" if conf_gate_ok else "fail")
    ram_base, ram_size = parse_ram(conf_info["ram"])
    end_i = len(raw)
    reset_i, reset_m = R.first(RX["reset"])
    teardown_i, _ = R.first(RX["teardown"])
    cfg_i, cfg_m = R.first(RX["config"])
    cfg = kvs(cfg_m, 1) if cfg_m else None
    guard_i, guard_m = R.first(RX["guard"])
    cans = R.all(RX["canary"])

    def verify_of(m):
        return kvs(m, 2).get("verify")

    # --- L0 (board)
    rung = None
    if board:
        miss["L0"] = []
        pos = None
        i, _ = R.first(RX["shim"])
        need("L0", i is not None, "shim")
        if i is not None:
            need("L0", any(RX["shim_pc"].search(t) for j, t in recs if i <= j <= i + 3), "shim_pc")
            pos = i
        for key in ("wdt0", "ram_w2", "gpu_range"):
            j, _ = R.first(RX[key], after=pos)
            need("L0", j is not None, key)
            pos = j if j is not None else pos
        for c, base in CANARIES.items():
            j, m = R.first(CANARY_FILL_RE[c], after=pos)
            need("L0", j is not None and int(m.group(1), 16) == base, "filled_" + c)
            pos = j if j is not None else pos
        j, m = R.first(RX["procnto_up"], after=pos)
        need("L0", j is not None, "procnto_up")
        if j is not None:
            rung = m.group(1)
            pos = j
        j, _ = R.first(RX["guard"], after=pos)
        need("L0", j is not None, "guard_after_procnto")
        pos = j if j is not None else pos
        j, _ = R.first(RX["config"], after=pos)
        need("L0", j is not None, "config_after_guard")
        for name, rx in NEG_L0:
            need("L0", R.first(rx, before=reset_i)[0] is None, "neg_" + name)

    # --- L1
    miss["L1"] = []
    if guest:
        act_i = R.first(RX["dryrun"])[0]
    elif mode == "host":
        act_i = R.first(RX["alloc"])[0]
    else:
        act_i = None
    _, mb = R.first(RX["mem_boot"])
    need("L1", mb is not None, "mem_boot")
    free = mem_mib(mb.group(1)) if mb else None
    if mode == "host":
        _, wm = R.first(RX["w2"])
        need("L1", wm is not None and wm.group(1) == "yes", "w2_reflected")
        need("L1", free is not None and free > W1_MIB, "w2_reflected_pc")
    else:
        need("L1", R.first(RX["gate_mem"])[0] is not None, "gate_mem")
        need("L1", free is not None and free >= MEM_GATE_MIB[(profile, mode)], "gate_mem_pc")
    if board:
        need("L1", R.first(RX["asinfo_ok"])[0] is not None, "asinfo")
        for c in CANARIES:
            first = next(((i, m) for i, m in cans if m.group(1) == c), None)
            need("L1", first is not None and verify_of(first[1]) == "ok" and (act_i is None or first[0] < act_i),
                 "canary_start_" + c)
        need("L1", all(m.group(1) in CANARIES for _, m in cans), "canary_names")
    if mode != "host":
        for f in ("image", "initrd", "conf"):
            need("L1", any(m.group(1) == f and m.group(2) == "pre" for _, m in R.all(RX["check"])), "md5_pre_" + f)
        need("L1", R.first(RX["hostcheck"])[0] is not None, "hostcheck")
    miss["profile"] = []
    if not board:
        need("profile", R.first(RX["asinfo"])[0] is None and not cans, "tcg_asinfo_or_canary")
    if board:
        need("canaries_all_ok", bool(cans) and all(verify_of(m) == "ok" for _, m in cans), "canary_not_ok")

    # --- exports
    for blk in blocks:
        decode_block(blk)
        put("export", f"name={q(blk['name'])} status={blk['status']}" +
            (f" bytes={len(blk['data'])} sha256={blk['sha256']}" if blk["status"] == "ok" else ""))
    fdt_blk = next((b for b in blocks if b["name"] == "fdt" and b["status"] == "ok"), None) or \
        next((b for b in blocks if b["name"] == "fdt"), None)
    fdt_sha = fdt_blk["sha256"] if fdt_blk is not None and fdt_blk["status"] == "ok" else None

    # --- L2 and the FDT checklist
    fdt_ok = False
    if guest:
        miss["L2"] = []
        di, dm = R.first(RX["dryrun"])
        need("L2", dm is not None, "dryrun")
        dk = kvs(dm, 1) if dm else {}
        if dm:
            need("L2", to_int(dk.get("rc")) is not None, "dryrun_rc")
            need("L2", dk.get("saved") == "yes", "dryrun_saved")
            need("L2", dk.get("logger_errors") == "0", "dryrun_logger_errors")
            bq = R.all(RX["bwait_qvm"], before=di)
            need("L2", bool(bq), "dryrun_bwait_line")
            need("L2", bool(bq) and bq[-1][1].group(3) == "0", "dryrun_within_bound")
        need("L2", fdt_blk is not None, "fdt_export")
        if fdt_blk is not None:
            need("L2", fdt_blk["status"] == "ok", "fdt_export_" + fdt_blk["status"])
        if fdt_sha:
            fd = fdt_blk["data"]
            need("L2", fd[:4] == b"\xd0\x0d\xfe\xed", "fdt_magic")
            if dm:
                need("L2", to_int(dk.get("fdt_bytes")) == len(fd) and (dk.get("fdt_md5") or "").lower() == md5(fd),
                     "fdt_vs_dryrun_line")
            try:
                rows, _ = fdt_checklist(fd, conf_info["cmdline"], ram_base, ram_size)
            except InputError as e:
                put("fdt_error", q(str(e)))
                need("fdt_gating", False, "fdt_unreadable")
            else:
                flines, fdt_ok = fdt_lines(rows, "fdt_")
                out.extend(flines)
                need("fdt_gating", fdt_ok, "gating_rows")
        else:
            need("fdt_gating", False, "no_decoded_fdt")

    # --- L3 to L5
    stamps = {m.group(1) for _, m in R.all(RX["stamp"])}
    if launched:
        miss["L3"] = [] if "l_kernel" in stamps else ["l_kernel"]
        miss["L4"] = []
        need("L4", "i_start" in stamps, "i_start")
        need("L4", "i_ready" in stamps, "i_ready")
        need("L4", "l_panic" not in stamps, "l_panic")
        need("L4", "l_rbfail" not in stamps, "l_rbfail")
        need("L4", R.first(RX["qvm_rc"], before=teardown_i if teardown_i is not None else end_i)[0] is None,
             "qvm_rc_before_teardown")
        miss["L5"] = list(miss["L4"])
        need("L5", "shell_ok" in stamps, "shell_ok")

    # --- L6 (hold modes)
    if hold:
        miss["L6"] = []
        want = HOLD_MIB[profile]
        hs_i, hs_m = R.first(RX["hold_start"])
        need("L6", hs_m is not None and int(hs_m.group(1)) == HOLD_SECS, "hold_start")
        he_i, he_m = R.first(RX["hold_end"])
        need("L6", he_m is not None and he_m.group(1) == "alive", "hold_end_alive")
        holds = [(i, m, kvs(m, 2)) for i, m in R.all(RX["alloc_hold"])]
        need("L6", any(int(m.group(1)) == want and d.get("fill") == "ok" for _, m, d in holds), "alloc_hold_fill")
        need("L6", any(int(m.group(1)) == want and d.get("verify") == "ok" for _, m, d in holds),
             "alloc_hold_verify")
        need("L6", not any(d.get("verify", "ok") != "ok" or d.get("fill", "ok") != "ok" for _, _, d in holds),
             "alloc_hold_not_ok")
        hbs = [(i, kvs(m, 1)) for i, m in R.all(RX["hb"])]
        ks = [to_int(d.get("k")) for _, d in hbs]
        need("L6", ks == list(range(1, HB_COUNT + 1)), "heartbeats_k1_to_k10")
        need("L6", all(d.get("qvm") == "alive" and d.get("rc") == "absent" for _, d in hbs), "heartbeat_not_alive")
        if hbs and hs_i is not None and he_i is not None:
            need("L6", all(hs_i < i < he_i for i, _ in hbs), "heartbeats_inside_hold")
        need("L6", R.first(RX["mem_hb10"])[0] is not None, "mem_hb10")
        need("L6", "end_ok" in stamps, "end_ok")
        if board:
            for c in CANARIES:
                pre = [m for i, m in cans if m.group(1) == c and he_i is not None and i > he_i and
                       (teardown_i is None or i < teardown_i)]
                post = [m for i, m in cans if m.group(1) == c and teardown_i is not None and i > teardown_i]
                need("L6", bool(pre) and all(verify_of(m) == "ok" for m in pre), "canary_before_teardown_" + c)
                need("L6", bool(post) and all(verify_of(m) == "ok" for m in post), "canary_after_teardown_" + c)

    # --- L7 (board)
    if board:
        miss["L7"] = []
        if mode != "host":
            for f in ("image", "initrd", "conf"):
                need("L7", any(m.group(1) == f and m.group(2) == "post" for _, m in R.all(RX["check"])),
                     "md5_post_" + f)
        fs = R.all(RX["fail_state"])
        need("L7", bool(fs) and all(m.group(1) == "none" for _, m in fs), "fail_state_none")
        need("L7", R.first(RX["fail"])[0] is None, "fail_line")
        need("L7", R.first(RX["guard_expired"])[0] is None, "guard_expired")
        need("L7", reset_m is not None and (rung is None or reset_m.group(1) == rung), "reset_line")
        need("L7", reset_i is not None and any(any(b in t for b in FW_BANNER) for i, t in recs if i > reset_i),
             "firmware_banner_after_reset")
        if launched and not hold:
            for c in CANARIES:
                post = [m for i, m in cans if m.group(1) == c and teardown_i is not None and i > teardown_i]
                need("L7", bool(post) and all(verify_of(m) == "ok" for m in post), "canary_after_teardown_" + c)
        if reset_reason is None:
            need("L7", False, "reset_reason_not_given")
        else:
            need("L7", "MAINSWRST" in reset_reason, "reset_reason_not_mainswrst")
        if bb_data is None:
            need("L7", False, "blackbox_not_given")
        else:
            brecs, _, _, _ = split_log(bb_data)
            bb_lines = [t for _, t in brecs if t.startswith(BB_PREFIXES)]
            com3_lines = R.lines(BB_PREFIXES)
            cons, first_bad = is_subsequence(bb_lines, com3_lines)
            put("bb_bytes", len(bb_data))
            put("bb_records", len(bb_lines))
            put("bb_consistent", "yes" if cons and bb_lines else f"no first_missing_record={first_bad}")
            put("bb_over_60000", "yes" if len(bb_data) > BB_GATE else "no")
            put("bb_at_cap", "yes" if len(bb_data) >= BB_CAP else "no")
            need("L7", bool(bb_lines), "blackbox_no_records")
            need("L7", cons, "blackbox_not_consistent_with_com3")

    # --- B2 (host mode)
    if mode == "host":
        miss["b2"] = []
        for c in CANARIES:
            need("b2", sum(1 for _, m in cans if m.group(1) == c and verify_of(m) == "ok") >= 2, "six_verify_" + c)
        allocs = [kvs(m, 2) for _, m in R.all(RX["alloc"]) if int(m.group(1)) == B2_ALLOC_MIB]
        need("b2", any(d.get("fill") == "ok" and d.get("verify") == "ok" for d in allocs), "alloc_1536")
        need("b2", not any(d.get("verify", "ok") != "ok" for d in allocs), "alloc_not_ok")

    # --- item 3 (q2)
    if mode == "q2":
        miss["item3"] = []
        need("item3", "banner" in stamps, "banner")
        need("item3", any(int(m.group(1)) == IPC_ITERS and int(m.group(2)) == IPC_PAYLOAD
                          for _, m in R.all(RX["samples"])), "ipc_completion")
        need("item3", R.first(RX["both"])[0] is not None, "both_alive")

    # --- T3 token list (tcg hold) and the black-box text estimate (R22)
    if not board:
        first_s1 = next((i for i, t in recs if t.startswith("S1 ")), None)
        bb_text = 0 if first_s1 is None else sum(len(raw[i]) + 1 for i in range(first_s1, len(raw))
                                                 if i not in body_idx)
        put("bb_text_bytes", bb_text)
        put("bb_text_scope", "host-script-lines-without-export-bodies")
        miss["bb_text"] = [] if bb_text < BB_GATE else ["over_60000"]
        if hold:
            miss["t3"] = []
            need("t3", R.first(RX["gate_mem"])[0] is not None, "gate_mem")
            need("t3", not miss.get("L2") or "dryrun_saved" not in miss["L2"] and "dryrun" not in miss["L2"],
                 "dryrun_saved")
            need("t3", "shell_ok" in stamps, "shell_ok")
            for r in miss.get("L6", []):
                need("t3", False, r)
            for f in ("image", "initrd", "conf"):
                need("t3", any(m.group(1) == f and m.group(2) == "post" for _, m in R.all(RX["check"])),
                     "md5_post_" + f)

    # --- configuration identity (items 1, 2) and item 5
    pc_sha = sha256(conf_bytes)
    pc_md5 = md5(conf_bytes)
    cfg_conf = (cfg or {}).get("conf_sha256", "").lower()
    tgt_md5 = {"Image": [], "initrd.cpio.gz": [], "s1-linux.conf": []}
    for _, m in R.all(RX["md5line"]):
        tgt_md5[m.group(2)].append(m.group(1).lower())
    miss["conf_identity"] = []
    need("conf_identity", cfg_conf == pc_sha, "config_conf_sha256_vs_pc")
    tmd5 = tgt_md5["s1-linux.conf"]
    if guest:
        need("conf_identity", bool(tmd5), "target_md5_absent")
    need("conf_identity", all(h == pc_md5 for h in tmd5), "target_md5_vs_pc")
    if ref_conf_sha256:
        need("conf_identity", cfg_conf == ref_conf_sha256.lower(), "vs_ref_conf_sha256")
        miss["conf_ref"] = [] if cfg_conf == ref_conf_sha256.lower() else ["differs"]
    else:
        miss["conf_ref"] = ["not_given"]
    put("conf_sha256_pc", pc_sha)
    put("conf_md5_target", "absent" if not tmd5 else ("match" if all(h == pc_md5 for h in tmd5) else "mismatch"))
    pc_cmd = sha256(conf_info["cmdline"].encode("latin-1"))
    put("cmdline_sha256_vs_pc", "absent" if not cfg or not cfg.get("cmdline_sha256") else
        ("match" if cfg["cmdline_sha256"].lower() == pc_cmd else "differs"))

    missing = []
    if cfg is None:
        missing.append("S1_CONFIG")
    else:
        missing += [f for f in ITEM5_FIELDS if not cfg.get(f)]
    if mode == "host" and (cfg or {}).get("fdt") != "none":
        missing.append("fdt=none")
    if board and not HEX64_RE.match((kexec_tree_sha256 or "").lower()):
        missing.append("kexec_tree_sha256")
    miss["item5"] = []
    if guest:
        need("item5", bool(fdt_sha), "fdt_sha256_not_decoded")
        # Target side: md5 of the same files (§5.2 item 5). An absent line is evidence
        # that failed (a run can stop before its integrity check), not a stamp left out.
        for f, key in (("Image", "image"), ("initrd.cpio.gz", "initrd"), ("s1-linux.conf", "conf")):
            need("item5", bool(tgt_md5[f]), f"target_md5_{key}_absent")
            need("item5", len(set(tgt_md5[f])) <= 1, f"target_md5_{key}_changed")
        for f, key, pin in (("Image", "image", pc_image), ("initrd.cpio.gz", "initrd", pc_initrd)):
            if pin is None:
                put(f"{key}_vs_pc", "not_given")
                continue
            md5_ok = bool(tgt_md5[f]) and all(h == md5(pin) for h in tgt_md5[f])
            sha_ok = (cfg or {}).get(f"{key}_sha256", "").lower() == sha256(pin)
            put(f"{key}_vs_pc", f"md5={'match' if md5_ok else ('absent' if not tgt_md5[f] else 'mismatch')} "
                f"config_sha256={'match' if sha_ok else 'differs'}")
            need("item5", md5_ok, f"target_md5_{key}_vs_pc")
            need("item5", sha_ok, f"config_{key}_sha256_vs_pc")
    if cfg is not None:
        if guard_m is not None:
            need("item5", cfg.get("guard_s") == guard_m.group(1), "guard_s_vs_bwait_guard")
        if hold:
            need("item5", cfg.get("hold_s") == str(HOLD_SECS), "hold_s")
    refused = bool(missing)

    if board and launched:
        gr = R.first(RX["guestram"])[1]
        put("guestram", q(gr.group(1)) if gr else "absent")
    if board:
        put("rung", rung or "unknown")
        put("kexec_tree_sha256", kexec_tree_sha256.lower() if kexec_tree_sha256 and not
            "kexec_tree_sha256" in missing else "missing")
    put("fdt_sha256", fdt_sha or ("none" if mode == "host" else "missing"))

    # --- tiers, items, verdict
    for t in ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"):
        if t not in miss:
            put(f"tier_{t}", "n/a")
        else:
            put(f"tier_{t}", "ok" if not miss[t] else "missing " + ",".join(miss[t]))
    put("tiers_reached", ",".join(t for t in ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")
                                  if t in miss and not miss[t]) or "none")

    def comp_ok(names):
        return all(n in miss and not miss[n] for n in names)

    def failed(names):
        return [n for n in names if n not in miss or miss[n]]

    step, needs = STEPS[(profile, mode)]
    if (profile, mode) == ("tcg", "dryrun"):
        put("item1_t1", "pass" if comp_ok(ITEM1_T1_NEEDS) else "fail failed=" + ",".join(failed(ITEM1_T1_NEEDS)))
    elif (profile, mode) == ("tcg", "boot"):
        put("item1_t2", "pass" if comp_ok(ITEM1_T2_NEEDS) else "fail failed=" + ",".join(failed(ITEM1_T2_NEEDS)))
    else:
        put("item1", "n/a")
    if board and mode in ("boot", "hold"):
        put("item2", ("pass" if comp_ok(ITEM2_NEEDS) else "fail") +
            ("" if comp_ok(ITEM2_NEEDS) else " failed=" + ",".join(failed(ITEM2_NEEDS))))
    else:
        put("item2", "n/a")
    put("item3", ("pass" if not miss["item3"] else "fail missing=" + ",".join(miss["item3"]))
        if "item3" in miss else "n/a")
    if board and hold:
        put("item4", ("pass" if comp_ok(ITEM4_NEEDS) else "fail failed=" + ",".join(failed(ITEM4_NEEDS))) +
            " end_ok=" + ("yes" if "end_ok" in stamps else "no"))
    else:
        put("item4", "n/a (T3 rehearsal)" if hold else "n/a")
    if hold and not board:
        t3_needs = ("conf_gate", "profile", "t3", "bb_text", "conf_identity")
        put("t3", "pass" if comp_ok(t3_needs) else
            "fail failed=" + ",".join(failed(t3_needs)) + " missing=" + ",".join(miss["t3"] + miss["bb_text"]))
    if mode == "host":
        put("b2", "pass" if comp_ok(("L0", "L1", "b2", "L7", "canaries_all_ok")) else "fail")
    if refused:
        put("item5", "refused missing=" + ",".join(missing))
    else:
        put("item5", "ok" if not miss["item5"] else "bad " + ",".join(miss["item5"]))
    for n in needs:
        if n in miss and miss[n] and n not in ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"):
            put(f"missing_{n}", ",".join(miss[n]))
    if refused:
        verdict = "refused"
    else:
        verdict = "pass" if comp_ok(needs) else "fail"
    put("step", step)
    put("verdict", verdict + ("" if verdict != "fail" else " failed=" + ",".join(failed(needs))))
    return {"lines": out, "blocks": blocks, "verdict": verdict, "refused": refused, "step": step}


def run_report(a_log, data, bb_data, a_blackbox, conf_path, conf_bytes, allow_bytes, res, profile, mode,
               pins=()):
    head = [f"parser={rel_repo(__file__)} sha256={sha256(open(__file__, 'rb').read())}",
            f"kshcheck_impl={rel_repo(PARSE_M4_PATH)} sha256={sha256(open(PARSE_M4_PATH, 'rb').read())}",
            f"input_log={rel_repo(a_log)} sha256={sha256(data)} bytes={len(data)}",
            (f"input_blackbox={rel_repo(a_blackbox)} sha256={sha256(bb_data)}" if bb_data is not None
             else "input_blackbox=none"),
            f"input_conf={rel_repo(conf_path)} sha256={sha256(conf_bytes)}",
            f"input_allow sha256={sha256(allow_bytes)}"]
    head += [f"input_{key}={rel_repo(p)} sha256={sha256(b)}" if b is not None else f"input_{key}=none"
             for key, p, b in pins]
    head.append(f"profile={profile} mode={mode}")
    return "".join(out_line("S1PC " + ln) + "\n" for ln in head + res["lines"])


def write_run_outputs(out_dir, res, text, check=True):
    """Decoded exports and parse-s1.txt into out_dir.

    Every path is checked before the first write, so a refused path leaves nothing
    behind. check=True is parse-m4.py's check_out_path (git-ignored, not under
    results/hw or results/cloud); the selftest passes a stand-in or False.
    """
    checker = PM.check_out_path if check is True else (check or (lambda p: None))
    items = [(os.path.join(out_dir, export_filename(b["name"])), b["data"]) for b in res["blocks"]
             if b.get("status") == "ok"]
    items.append((os.path.join(out_dir, "parse-s1.txt"), text.encode("utf-8")))
    for p, _ in items:
        checker(p)
    os.makedirs(out_dir, exist_ok=True)
    for p, data in items:
        with open(p, "wb") as f:
            f.write(data)
    return [p for p, _ in items]


def cmd_run(a):
    if a.profile == "tcg" and a.mode == "host":
        print("parse-s1: usage: --mode host is the board's B2; a TCG script never calls memcanary asinfo",
              file=sys.stderr)
        return 2
    data = PM.read_bytes(a.log)
    bb_data = PM.read_bytes(a.blackbox) if a.blackbox else None
    conf_path = a.conf or DEFAULT_CONF
    conf_bytes, info, gate_ok = load_conf_facts(conf_path)
    allow_bytes = PM.read_bytes(DEFAULT_ALLOW)
    pc_image = PM.read_bytes(a.image) if a.image else None
    pc_initrd = PM.read_bytes(a.initrd) if a.initrd else None
    res = analyze_run(data, profile=a.profile, mode=a.mode, conf_bytes=conf_bytes, conf_info=info,
                      conf_gate_ok=gate_ok, bb_data=bb_data, ref_conf_sha256=a.ref_conf_sha256,
                      reset_reason=a.reset_reason, kexec_tree_sha256=a.kexec_tree_sha256, pc_image=pc_image,
                      pc_initrd=pc_initrd)
    text = run_report(a.log, data, bb_data, a.blackbox, conf_path, conf_bytes, allow_bytes, res, a.profile, a.mode,
                      pins=(("image", a.image, pc_image), ("initrd", a.initrd, pc_initrd)))
    out_dir = None if a.out_dir == "none" else (a.out_dir or os.path.dirname(os.path.abspath(a.log)))
    if out_dir is not None:
        for p in write_run_outputs(out_dir, res, text):
            text += out_line(f"S1PC wrote={rel_repo(p)}") + "\n"
    sys.stdout.write(text)
    return 3 if res["refused"] else 0


# ------------------------------------------------------------------ selftest (synthetic inputs only)

def _u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def _u64(v):
    return struct.pack(">Q", v)


def _s(*strs):
    return b"".join(x.encode("latin-1") + b"\0" for x in strs)


def fdt_build(tree):
    """A v17 blob from (name, [(prop, bytes)], [children]); the selftest's writer."""
    strings = bytearray()
    offs = {}
    st = bytearray()

    def soff(name):
        if name not in offs:
            offs[name] = len(strings)
            strings.extend(name.encode("latin-1") + b"\0")
        return offs[name]

    def align():
        while len(st) % 4:
            st.append(0)

    def emit(node):
        name, props, kids = node
        st.extend(struct.pack(">I", FDT_BEGIN_NODE))
        st.extend(name.encode("latin-1") + b"\0")
        align()
        for pn, pv in props:
            st.extend(struct.pack(">III", FDT_PROP, len(pv), soff(pn)))
            st.extend(pv)
            align()
        for k in kids:
            emit(k)
        st.extend(struct.pack(">I", FDT_END_NODE))

    emit(tree)
    st.extend(struct.pack(">I", FDT_END))
    off_rsv = 40
    off_st = off_rsv + 16
    off_str = off_st + len(st)
    total = off_str + len(strings)
    hdr = struct.pack(">10I", FDT_MAGIC, total, off_st, off_str, off_rsv, 17, 16, 0, len(strings), len(st))
    return hdr + struct.pack(">QQ", 0, 0) + bytes(st) + bytes(strings)


def syn_tree(cmdline, *, psci=True, psci_method=True, bootargs=None, initrd=(0x88000000, 0x88400000),
             virtio_addr=0x20000000, timer_intr=True, bus=False, gic=True, mem_size=512 * MIB):
    chosen = ("chosen", [("bootargs", _s(cmdline if bootargs is None else bootargs)),
                         ("linux,initrd-start", _u64(initrd[0])), ("linux,initrd-end", _u64(initrd[1])),
                         ("stdout-path", _s("/pl011@1c090000")), ("kaslr-seed", _u64(0))], [])
    memory = ("memory@80000000", [("device_type", _s("memory")), ("reg", _u32(0, 0x80000000, 0, mem_size))], [])
    cpus = ("cpus", [("#address-cells", _u32(1)), ("#size-cells", _u32(0))],
            [(f"cpu@{k}", [("device_type", _s("cpu")), ("compatible", _s("arm,armv8")), ("reg", _u32(k)),
                           ("enable-method", _s("psci"))], []) for k in range(3)])
    kids = [chosen, memory, cpus]
    if psci:
        kids.append(("psci", [("compatible", _s("arm,psci-1.0", "arm,psci-0.2"))] +
                     ([("method", _s("hvc"))] if psci_method else []), []))
    if gic:
        kids.append(("intc@2f000000", [("compatible", _s("arm,gic-v3")),
                                       ("reg", _u32(0, 0x2F000000, 0, 0x10000, 0, 0x2F100000, 0, 0x200000)),
                                       ("interrupt-controller", b""), ("#interrupt-cells", _u32(3))], []))
    kids.append(("timer", [("compatible", _s("arm,armv8-timer"))] +
                 ([("interrupts", _u32(1, 13, 4, 1, 14, 4, 1, 11, 4, 1, 10, 4))] if timer_intr else []), []))
    kids.append(("pl011@1c090000", [("compatible", _s("arm,pl011", "arm,primecell")),
                                    ("reg", _u32(0, 0x1C090000, 0, 0x1000)), ("interrupts", _u32(0, 5, 4))], []))
    vprops = [("compatible", _s("virtio,mmio")), ("interrupts", _u32(0, 10, 1))]
    if bus:
        kids.append(("bus@20000000", [("compatible", _s("simple-bus")), ("#address-cells", _u32(1)),
                                      ("#size-cells", _u32(1)), ("ranges", _u32(0, 0, virtio_addr, 0x1000))],
                     [("virtio_mmio@0", vprops + [("reg", _u32(0, 0x1000))], [])]))
    else:
        kids.append((f"virtio_mmio@{virtio_addr:x}", vprops + [("reg", _u32(0, virtio_addr, 0, 0x1000))], []))
    return ("", [("#address-cells", _u32(2)), ("#size-cells", _u32(2)), ("compatible", _s("linux,dummy-virt"))],
            kids)


SYN_HEX = {k: c * 64 for k, c in (("image_sha256", "1"), ("initrd_sha256", "2"), ("init_sha256", "3"),
                                  ("s1con_sha256", "4"), ("memcanary_sha256", "5"), ("stamp_sha256", "6"),
                                  ("bwait_sha256", "7"))}
SYN_KEXEC = "9" * 64


def syn_stamp(label):
    return f"STAMP {label} cycles=1 cps=31250000 cpu=0 mono_ns=1 bytes=1"


def syn_log(profile, mode, dtb, conf_bytes, cmdline, *, enc="base64"):
    """A synthetic record of one run, as a list of lines (SYNTHETIC; not a record)."""
    board = profile == "board"
    rung = {"host": "s1-h1", "boot": "s1-n1", "hold": "s1-n2", "dryrun": "s1-n1", "q2": "s1-q2"}[mode]
    guard = 2400 if mode in ("hold", "q2") else 1800
    cfg = dict(SYN_HEX)
    cfg.update(conf_sha256=sha256(conf_bytes), cmdline_sha256=sha256(cmdline.encode("latin-1")),
               startup_sha256=("8" * 64 if board else "tcg-profile"),
               startup_line="'-vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -b w2,canary -Dtcu'" if board
               else "tcg-profile",
               cpu_lines="'cpu cluster _cpu-1;cpu cluster _cpu-2;cpu cluster _cpu-3'",
               ram_line="'ram 0x80000000,512M'",
               windows="w1=0x80000000/992M,w2=0x100000000/0x8a000000" if board else "'tcg -m 2G'",
               canaries="c1,c2,c3" if board else "none", guest_set="none" if mode == "host" else "linux",
               hold_s=str(HOLD_SECS) if mode == "hold" else "0", guard_s=str(guard),
               gpu_range="0x18a000000/0xc0000000" if board else "none")
    if mode == "host":
        cfg["fdt"] = "none"
    L = []
    if board:
        L += ["--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=1789344000 seconds=3600 ---",
              "", "T234-SHIM EL=2 HCR=0000000000000000 PC=0000000080080000 X0=0000000084000000",
              "t234: WDT0 CR=0x00000000",
              "t234: ram w2 base=0x100000000 size=0x8a000000",
              "t234: gpu range base=0x18a000000 size=0xc0000000 not added",
              "t234: canary c1 base=0xbd000000 size=0x1000000 filled",
              "t234: canary c2 base=0x100000000 size=0x1000000 filled",
              "t234: canary c3 base=0x189000000 size=0x1000000 filled",
              f"T234 S1 {rung} -P4: procnto up"]
    canary_set = [f"S1 CANARY {c} verify=ok" for c in CANARIES] if board else []
    L += [f"BWAIT guard armed secs={guard} prio=50", "S1 STATE config",
          "S1 CONFIG " + " ".join(f"{k}={v}" for k, v in cfg.items()), "S1 STATE preflight"]
    if mode == "host":
        L += ["S1 MEM boot 3100MB/3200MB", "S1 W2 reflected=yes",
              "S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no"]
        L += canary_set + ["S1 ALLOC mib=1536 fill=ok verify=ok"] + canary_set + ["S1 MEM end 3100MB/3200MB"]
    else:
        L += ["S1 MEM boot 1400MB/2048MB", "S1 GATE mem ok"]
        if board:
            L += ["S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no"]
            L += canary_set
        L += ["1" * 32 + "  /data/s1/Image", "2" * 32 + "  /data/s1/initrd.cpio.gz",
              md5(conf_bytes) + "  /data/s1/s1-linux.conf",
              "S1 CHECK image md5_pre ok", "S1 CHECK initrd md5_pre ok", "S1 CHECK conf md5_pre ok",
              "S1 STATE hostcheck", "S1 STATE dryrun", "BWAIT run prog=qvm rc=0 sig=0 killed=0 ms=4000",
              f"S1 DRYRUN rc=0 saved=yes fdt_bytes={len(dtb)} fdt_md5={md5(dtb)} logger_errors=0"]
        if mode in LAUNCH_MODES:
            L += ["S1 STATE launch", "BWAIT path hit=/dev/shmem/i_ready.hit ms=1"]
            L += [syn_stamp(x) for x in ("l_kernel", "l_run_init", "i_start", "i_ready", "shell_ok")]
            if mode == "q2":
                L += [syn_stamp("banner"), "samples=15 payload=48 cps=31250000", "S1 BOTH alive"]
            if mode == "hold":
                want = HOLD_MIB[profile]
                L += [f"S1 ALLOC hold mib={want} fill=ok", f"S1 HOLD start secs={HOLD_SECS}"]
                L += [f"S1 HB k={k} qvm=alive rc=absent" for k in range(1, HB_COUNT + 1)]
                L += ["S1 MEM hb10 1100MB/2048MB", syn_stamp("end_ok"), "S1 HOLD end qvm=alive",
                      f"S1 ALLOC hold mib={want} fill=ok verify=ok"] + canary_set
            if board:
                L += ["S1 GUESTRAM unknown"]
            L += ["S1 STATE teardown", "rc=0"] + canary_set
        L += ["S1 CHECK image md5_post ok", "S1 CHECK initrd md5_post ok", "S1 CHECK conf md5_post ok"]
    L += ["S1 STATE export"]
    if mode in GUEST_MODES:
        payload = dtb
        extra = ""
        if enc == "gzip-base64":
            payload = gzip.compress(dtb, mtime=0)
            extra = f" gz_bytes={len(payload)} gz_md5={md5(payload)}"
        b = base64.b64encode(payload).decode("ascii")
        L += [f"S1 BEGIN name=fdt bytes={len(dtb)} md5={md5(dtb)}{extra} enc={enc}"]
        L += [b[k:k + 76] for k in range(0, len(b), 76)]
        L += ["S1 END name=fdt"]
    L += ["S1 FAIL_STATE none"]
    if board:
        L += [f"T234 S1 {rung} -P4: resetting so the log can be recovered", "",
              "ESC to enter Setup.", "F11 to enter Boot Manager Menu.", "Enter to continue boot.",
              "--- raw capture ended 2026-09-14T01:00:00Z bytes=1 ---"]
    return L


def syn_blackbox(lines):
    """The black box a board run would keep: startup to the reset line, export bodies left out."""
    out = []
    started = False
    in_body = False
    for ln in lines:
        if ln.startswith("t234: WDT0"):
            started = True
        if not started:
            continue
        if ln.startswith("S1 END "):
            in_body = False
        if not in_body:
            out.append(ln)
        if ln.startswith("S1 BEGIN "):
            in_body = True
        if "resetting so the log can be recovered" in ln:
            break
    return ("\n".join(out) + "\n").encode("latin-1")


def edit_lines(lines, drop=(), sub=(), add_after=()):
    out = []
    for ln in lines:
        if any(re.search(p, ln) for p in drop):
            continue
        for p, new in sub:
            if re.search(p, ln):
                ln = re.sub(p, new, ln)
        out.append(ln)
        for p, new in add_after:
            if re.search(p, ln):
                out.append(new)
    return out


def selftest():
    results = []

    def check(name, cond):
        results.append(bool(cond))
        print(f"S1PC-SELFTEST {name} {'ok' if cond else 'FAIL'}")

    # ---- conf
    try:
        conf_bytes = PM.read_bytes(DEFAULT_CONF)
        allow_text = PM.read_bytes(DEFAULT_ALLOW).decode("latin-1")
    except InputError as e:
        print(f"S1PC-SELFTEST inputs FAIL {e}")
        return 1
    check("conf committed file equals design section 3.7 text", conf_bytes == DESIGN_CONF.encode("ascii"))
    al, aerr = parse_allow(allow_text)
    check("conf allow-list parses", not aerr)
    check("conf allow-list keywords equal the design list", al.keywords == set(DESIGN_KEYWORDS))
    check("conf allow-list vdev types equal the design list", al.vdev_types == set(DESIGN_VDEV_TYPES))
    check("conf allow-list forbidden words equal the design list", al.forbidden == set(DESIGN_FORBIDDEN))
    check("conf allow-list approves no overlay", al.overlays == [])
    ok, _, info = conf_check(conf_bytes, allow_text, HERE)
    check("conf committed configuration passes", ok)
    check("conf cmdline read", info["cmdline"] and info["cmdline"].startswith("console=hvc0 "))
    check("conf three cpu cluster lines", len(info["cpu_lines"]) == 3)
    tdir = tempfile.mkdtemp(prefix="s1pc-selftest-")

    def gate(text, allow=allow_text, overlay=None):
        return conf_check(text.encode("latin-1") if isinstance(text, str) else text, allow, tdir, overlay)

    def rejects(text, reason, allow=allow_text):
        ok_, lines_, _ = gate(text, allow)
        return (not ok_) and any(f"reason={reason}" in ln for ln in lines_)

    base = DESIGN_CONF
    check("conf reject pass line", rejects(base + "pass loc mem:0x40000000,0x1000,rw=0x40000000\n", "forbidden"))
    check("conf reject vdev smmu", rejects(base + "vdev smmu\n loc 0x1\n intr gic:1\n", "forbidden"))
    check("conf reject smmu inside a word", rejects(base + "vdev smmu-v3\n loc 0x1\n intr gic:1\n", "forbidden"))
    check("conf reject fdt load without approval", rejects(base + "fdt load /data/s1/ov.dtbo\n", "forbidden"))
    check("conf reject vdev virtio-net", rejects(base + "vdev virtio-net\n loc 0x1\n intr gic:1\n", "forbidden"))
    check("conf reject vdev virtio-blk", rejects(base + "vdev virtio-blk\n loc 0x1\n intr gic:1\n", "forbidden"))
    check("conf reject vdev shmem", rejects(base + "vdev shmem\n loc 0x1\n intr gic:1\n", "forbidden"))
    check("conf reject unknown keyword", rejects(base + "unsupported register ignore\n", "keyword-not-allowed"))
    check("conf reject unknown vdev type", rejects(base + "vdev virtio-rng\n loc 0x1\n intr gic:1\n",
                                                   "vdev-type-not-allowed"))
    check("conf reject cluster at line start", rejects(base + "cluster _cpu-1\n", "not-a-directive"))
    check("conf reject cpu option not allowed", rejects(base + "cpu runmask 0x2\n", "cpu-option-not-allowed"))
    check("conf reject hostdev outside vdev", rejects("hostdev /dev/ttyp3\n" + base, "vdev-option-outside-vdev"))
    check("conf reject vdev without loc", rejects(base.replace(" loc 0x20000000\n", ""), "vdev-without-loc"))
    check("conf reject missing cmdline", rejects("".join(ln + "\n" for ln in base.splitlines()
                                                         if not ln.startswith("cmdline")), "missing-required"))
    check("conf reject a second cmdline", rejects(base + 'cmdline "x"\n', "more-than-once"))
    check("conf reject unquoted cmdline", rejects(base.replace('cmdline "console=hvc0 earlycon=pl011,0x1c090000 '
                                                               'keep_bootcon nokaslr rdinit=/init panic=-1 cma=16M '
                                                               'loglevel=7"', "cmdline console=hvc0"),
                                                  "cmdline-not-quoted"))
    check("conf reject unterminated quote", rejects(base + 'cmdline "x\n', "unterminated-quote"))
    check("conf reject load outside /data/s1", rejects(base.replace("load /data/s1/Image",
                                                                    "load /proc/boot/Image"),
                                                       "path-outside-data-s1"))
    check("conf reject CRLF", rejects(base.replace("\n", "\r\n"), "carriage-return"))
    check("conf reject no final newline", rejects(base.rstrip("\n"), "no-final-newline"))
    no_cluster = allow_text.replace("\ncluster\n", "\n")
    check("conf allow-list without cluster rejects cpu cluster",
          rejects(base, "cpu-option-not-allowed", allow=no_cluster))
    ok_, lines_, _ = gate(base, allow_text.replace("forbid:shmem\n", ""))
    check("conf allow-list missing a forbidden word is invalid",
          not ok_ and any("forbid=shmem" in ln for ln in lines_))
    ok_, lines_, _ = gate(base, allow_text + "vdev:virtio-net\n")
    check("conf allow-list allowing a forbidden word is invalid",
          not ok_ and any("allowed-and-forbidden" in ln or "beyond-design" in ln for ln in lines_))
    ok_, lines_, _ = gate(base, allow_text + "fdt\n")
    check("conf allow-list word with no grammar place is invalid",
          not ok_ and any("no-place-in-grammar" in ln for ln in lines_))
    # D19: one non-GPU overlay approved by hash.
    ov = fdt_build(("", [], [("fragment@0", [("target-path", _s("/"))],
                              [("__overlay__", [], [("psci", [("compatible", _s("arm,psci-1.0")),
                                                              ("method", _s("hvc"))], [])])])]))
    with open(os.path.join(tdir, "ov.dtbo"), "wb") as f:
        f.write(ov)
    gpu_ov = fdt_build(("", [], [("fragment@0", [("target-path", _s("/"))],
                                  [("__overlay__", [], [("gpu@17000000", [("compatible", _s("nvidia,ga10b"))],
                                                         [])])])]))
    with open(os.path.join(tdir, "gpu.dtbo"), "wb") as f:
        f.write(gpu_ov)
    approved = allow_text + f"overlay-sha256:{sha256(ov)}\n"
    ok_, lines_, info_ = gate(base + "fdt load /data/s1/ov.dtbo\n", approved)
    check("conf D19 approved overlay accepted", ok_ and info_["overlay"] == sha256(ov))
    check("conf D19 approved but unused overlay passes", gate(base, approved)[0])
    check("conf D19 wrong hash rejected", rejects(base + "fdt load /data/s1/ov.dtbo\n", "overlay-sha256-not-approved",
                                                  allow=allow_text + "overlay-sha256:" + "0" * 64 + "\n"))
    check("conf D19 GPU overlay rejected even when approved",
          rejects(base + "fdt load /data/s1/gpu.dtbo\n", "overlay-names-gpu-smmu-or-iommu",
                  allow=allow_text + f"overlay-sha256:{sha256(gpu_ov)}\n"))
    check("conf D19 two fdt load lines rejected",
          rejects(base + "fdt load /data/s1/ov.dtbo\nfdt load /data/s1/ov.dtbo\n", "fdt-load-more-than-once",
                  allow=approved))
    check("conf D19 overlay file missing rejected",
          rejects(base + "fdt load /data/s1/absent.dtbo\n", "overlay-file-missing", allow=approved))
    check("conf D19 two approvals make the allow-list invalid",
          not gate(base, approved + "overlay-sha256:" + "0" * 64 + "\n")[0])
    # The screen reads property names and labels, not only node names and compatibles.
    vnode = ("virtio_mmio@20000000", [("compatible", _s("virtio,mmio")), ("iommus", _u32(1, 0))], [])
    iommu_ov = fdt_build(("", [], [("fragment@0", [("target-path", _s("/"))], [("__overlay__", [], [vnode])]),
                                   ("__fixups__", [("smmu", _s("/fragment@0/__overlay__/virtio_mmio@20000000:"
                                                                "iommus:0"))], [])]))
    with open(os.path.join(tdir, "iommu.dtbo"), "wb") as f:
        f.write(iommu_ov)
    check("conf D19 overlay with an iommus property and an smmu label rejected even when approved",
          rejects(base + "fdt load /data/s1/iommu.dtbo\n", "overlay-names-gpu-smmu-or-iommu",
                  allow=allow_text + f"overlay-sha256:{sha256(iommu_ov)}\n"))
    ph_ov = fdt_build(("", [], [("fragment@0", [("target", _u32(0xFFFFFFFF))],
                                 [("__overlay__", [("status", _s("okay"))], [])]),
                                ("__fixups__", [("x", _s("/fragment@0:target:0"))], [])]))
    with open(os.path.join(tdir, "ph.dtbo"), "wb") as f:
        f.write(ph_ov)
    check("conf D19 overlay targeted by phandle rejected even when approved",
          rejects(base + "fdt load /data/s1/ph.dtbo\n", "overlay-target-by-phandle",
                  allow=allow_text + f"overlay-sha256:{sha256(ph_ov)}\n"))

    # ---- fdt
    cmdline = info["cmdline"]
    rb, rs = parse_ram(info["ram"])
    dtb = fdt_build(syn_tree(cmdline))

    def gating(blob):
        rows_, _ = fdt_checklist(blob, cmdline, rb, rs)
        return {k: ok__ for kind, k, ok__, _ in rows_ if kind == "gate"}, rows_

    g, rows = gating(dtb)
    check("fdt synthetic tree passes every gating row", all(g.values()) and len(g) == 7)
    rec = {k: d for kind, k, _, d in rows if kind == "rec"}
    check("fdt records psci method", rec.get("psci_method") == "hvc")
    check("fdt records kaslr-seed", rec.get("kaslr_seed") == "present")
    check("fdt records gic:37 cells", rec.get("interrupts_gic37") == "0x0,0x5,0x4")
    check("fdt records gic:42 cells", rec.get("interrupts_gic42") == "0x0,0xa,0x1")
    check("fdt records three psci cpus", rec.get("cpus", "").startswith("3 enable_methods=psci"))
    check("fdt missing PSCI node fails", gating(fdt_build(syn_tree(cmdline, psci=False)))[0]["psci"] is False)
    check("fdt PSCI without method fails",
          gating(fdt_build(syn_tree(cmdline, psci_method=False)))[0]["psci"] is False)
    check("fdt bootargs mismatch fails",
          gating(fdt_build(syn_tree(cmdline, bootargs="console=ttyAMA0")))[0]["bootargs"] is False)
    check("fdt initrd outside guest RAM fails",
          gating(fdt_build(syn_tree(cmdline, initrd=(0x9F000000, 0xA0100000))))[0]["initrd"] is False)
    check("fdt virtio at another address fails",
          gating(fdt_build(syn_tree(cmdline, virtio_addr=0x20001000)))[0]["virtio_mmio"] is False)
    check("fdt virtio behind a simple-bus ranges passes",
          gating(fdt_build(syn_tree(cmdline, bus=True)))[0]["virtio_mmio"] is True)
    check("fdt timer without interrupts fails",
          gating(fdt_build(syn_tree(cmdline, timer_intr=False)))[0]["timer"] is False)
    check("fdt no GICv3 fails", gating(fdt_build(syn_tree(cmdline, gic=False)))[0]["gicv3"] is False)
    check("fdt memory smaller than the ram line fails",
          gating(fdt_build(syn_tree(cmdline, mem_size=256 * MIB)))[0]["memory"] is False)
    for label, blob in (("bad magic", b"\0" * 4 + dtb[4:]), ("truncated", dtb[:len(dtb) // 2]),
                        ("short", dtb[:20])):
        try:
            fdt_parse(blob)
            check(f"fdt {label} refused", False)
        except InputError:
            check(f"fdt {label} refused", True)
    for label, blob, want in (("cmd exit 0 on a full tree", dtb, 0),
                              ("cmd exit 1 on a missing PSCI node", fdt_build(syn_tree(cmdline, psci=False)), 1)):
        p = os.path.join(tdir, "t.dtb")
        with open(p, "wb") as f:
            f.write(blob)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_fdt(argparse.Namespace(dtb=p, conf=None))
        check(f"fdt {label}", rc == want)
    # A configuration outside the allow-list: fdt still prints the tree but exits 1.
    bad_conf_bytes = (base + "vdev shmem\n loc 0x1\n intr gic:1\n").encode("ascii")
    bad_conf = os.path.join(tdir, "bad.conf")
    with open(bad_conf, "wb") as f:
        f.write(bad_conf_bytes)
    with open(os.path.join(tdir, "t.dtb"), "wb") as f:
        f.write(dtb)                                      # the full tree, so only the gate can fail
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_fdt(argparse.Namespace(dtb=os.path.join(tdir, "t.dtb"), conf=bad_conf))
    check("fdt cmd exit 1 when --conf fails the gate", rc == 1 and "conf_gate=fail" in buf.getvalue())

    # ---- run
    def run(profile, mode, lines=None, *, bb="auto", ref=True, reset="MAINSWRST", kexec=SYN_KEXEC, tree=None,
            enc="base64", gate_ok=True, image=None, initrd=None):
        blob = fdt_build(tree) if tree is not None else dtb
        if lines is None:
            lines = syn_log(profile, mode, blob, conf_bytes, cmdline, enc=enc)
        data = ("\n".join(lines) + "\n").encode("latin-1")
        bbd = syn_blackbox(lines) if (bb == "auto" and profile == "board") else (bb if bb != "auto" else None)
        return analyze_run(data, profile=profile, mode=mode, conf_bytes=conf_bytes, conf_info=info,
                           conf_gate_ok=gate_ok, bb_data=bbd, ref_conf_sha256=sha256(conf_bytes) if ref else None,
                           reset_reason=reset if profile == "board" else None,
                           kexec_tree_sha256=kexec if profile == "board" else None, pc_image=image,
                           pc_initrd=initrd)

    def has(res, text):
        return any(ln.startswith(text) for ln in res["lines"])

    r = run("tcg", "dryrun")
    check("run T1 synthetic passes", r["verdict"] == "pass" and r["step"] == "T1" and has(r, "item1_t1=pass"))
    check("run T1 decodes the fdt export", has(r, "export=name=fdt status=ok") and has(r, "fdt_gating=ok"))
    check("run T1 prints no FreeMem value", not any("1400" in ln for ln in r["lines"]))
    r = run("tcg", "dryrun", tree=syn_tree(cmdline, psci=False))
    check("run T1 with no PSCI node fails", r["verdict"] == "fail" and has(r, "fdt_gate psci=missing"))
    r = run("tcg", "boot")
    check("run T2 synthetic passes", r["verdict"] == "pass" and has(r, "item1_t2=pass") and
          has(r, "tier_L5=ok"))
    r = run("tcg", "boot", enc="gzip-base64")
    check("run T2 gzip-base64 export decodes", r["verdict"] == "pass")
    lines = syn_log("tcg", "boot", dtb, conf_bytes, cmdline)
    r = run("tcg", "boot", edit_lines(lines, sub=((r"^S1 BEGIN name=fdt bytes=(\d+) md5=[0-9a-f]+",
                                                   r"S1 BEGIN name=fdt bytes=\1 md5=" + "0" * 32),)))
    check("run T2 export md5 mismatch fails L2", r["verdict"] == "fail" and has(r, "export=name=fdt status=mismatch"))
    check("run T2 export md5 mismatch fails item 5 without refusing",
          not r["refused"] and has(r, "item5=bad fdt_sha256_not_decoded"))
    r = run("tcg", "boot", edit_lines(lines, drop=(r"^S1 END name=fdt",)))
    check("run T2 unterminated export fails but later records stay read",
          r["verdict"] == "fail" and has(r, "export=name=fdt status=truncated"))
    r = run("tcg", "boot", edit_lines(lines, add_after=((r"^STAMP shell_ok", syn_stamp("l_rbfail")),)))
    check("run T2 l_rbfail fails L4", r["verdict"] == "fail" and has(r, "tier_L4=missing l_rbfail"))
    r = run("tcg", "boot", edit_lines(lines, add_after=((r"^STAMP i_ready", "rc=0"),)))
    check("run T2 qvm.rc before teardown fails L4", has(r, "tier_L4=missing qvm_rc_before_teardown"))
    r = run("tcg", "boot", edit_lines(lines, drop=(r"^STAMP shell_ok",)))
    check("run T2 no shell_ok fails L5 only", r["verdict"] == "fail" and has(r, "tier_L4=ok") and
          has(r, "tier_L5=missing shell_ok"))
    r = run("tcg", "boot", edit_lines(lines, add_after=((r"^S1 GATE mem ok", "S1 CANARY c1 verify=ok"),)))
    check("run T2 a canary line on TCG fails the profile check", r["verdict"] == "fail" and
          has(r, "missing_profile=tcg_asinfo_or_canary"))
    r = run("tcg", "boot", edit_lines(lines, sub=((r"logger_errors=0", "logger_errors=2"),)))
    check("run T2 dryrun logger errors fail L2", has(r, "tier_L2=missing dryrun_logger_errors"))
    r = run("tcg", "boot", edit_lines(lines, sub=((r" init_sha256=\S+", ""),)))
    check("run T2 missing item-5 field refuses the verdict", r["verdict"] == "refused" and r["refused"] and
          has(r, "item5=refused missing=init_sha256"))
    md5_line_re = r"^[0-9a-f]{32}  /data/s1/"
    r = run("tcg", "boot", edit_lines(lines, drop=(md5_line_re,)))
    check("run T2 with no target md5 lines fails conf identity and item 5", r["verdict"] == "fail" and
          has(r, "conf_md5_target=absent") and "conf_identity" in r["lines"][-1] and
          has(r, "item5=bad") and "target_md5_image_absent" in next(ln for ln in r["lines"]
                                                                    if ln.startswith("item5=")))
    r = run("tcg", "boot", gate_ok=False)
    check("run T2 with a configuration failing the gate fails", r["verdict"] == "fail" and has(r, "conf_gate=fail")
          and has(r, "item1_t2=fail") and "conf_gate" in r["lines"][-1])
    bad_log = os.path.join(tdir, "bad-t2.log")
    with open(bad_log, "wb") as f:
        f.write(("\n".join(syn_log("tcg", "boot", dtb, bad_conf_bytes, cmdline)) + "\n").encode("latin-1"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_run(argparse.Namespace(log=bad_log, profile="tcg", mode="boot", blackbox=None, out_dir="none",
                                        conf=bad_conf, ref_conf_sha256=None, reset_reason=None,
                                        kexec_tree_sha256=None, image=None, initrd=None))
    check("run cmd with --conf failing the gate gives verdict fail failed=conf_gate",
          rc == 0 and "S1PC conf_gate=fail" in buf.getvalue() and "S1PC verdict=fail failed=conf_gate\n"
          in buf.getvalue())
    img, ird = b"synthetic image\n", b"synthetic initrd\n"
    pinned = edit_lines(lines, sub=((r"^1{32}  ", md5(img) + "  "), (r"^2{32}  ", md5(ird) + "  "),
                                    (r" image_sha256=\S+", " image_sha256=" + sha256(img)),
                                    (r" initrd_sha256=\S+", " initrd_sha256=" + sha256(ird))))
    r = run("tcg", "boot", pinned, image=img, initrd=ird)
    check("run T2 with --image and --initrd pins matching passes", r["verdict"] == "pass" and
          has(r, "image_vs_pc=md5=match config_sha256=match") and has(r, "initrd_vs_pc=md5=match"))
    r = run("tcg", "boot", pinned, image=img + b"x", initrd=ird)
    check("run T2 with an --image pin that differs fails item 5", r["verdict"] == "fail" and
          has(r, "image_vs_pc=md5=mismatch config_sha256=differs") and
          "target_md5_image_vs_pc" in next(ln for ln in r["lines"] if ln.startswith("item5=")))
    # enc=text keeps trailing blanks and removes only the capture's CR.
    txt = b"line one \nline two\t\n  three\n"
    tlines = [f"S1 BEGIN name=t bytes={len(txt)} md5={md5(txt)} enc=text"] + \
        txt.decode("ascii").split("\n")[:-1] + ["S1 END name=t"]
    for label, sep in (("LF", "\n"), ("CRLF", "\r\n")):
        _, tblocks, _, _ = split_log((sep.join(tlines) + sep).encode("latin-1"))
        decode_block(tblocks[0])
        check(f"run enc=text with trailing blanks decodes ({label})", tblocks[0]["status"] == "ok" and
              tblocks[0]["data"] == txt)
    _, tblocks, _, _ = split_log(("\n".join(tlines).replace("line two\t", "line two") + "\n").encode("latin-1"))
    decode_block(tblocks[0])
    check("run enc=text with a changed body is a mismatch", tblocks[0]["status"].startswith("mismatch"))
    r = run("tcg", "hold")
    check("run T3 synthetic passes", r["verdict"] == "pass" and has(r, "t3=pass") and has(r, "tier_L6=ok"))
    hl = syn_log("tcg", "hold", dtb, conf_bytes, cmdline)
    r = run("tcg", "hold", edit_lines(hl, drop=(r"^S1 HB k=10 ",)))
    check("run T3 nine heartbeats fail", r["verdict"] == "fail" and "heartbeats_k1_to_k10" in
          next(ln for ln in r["lines"] if ln.startswith("tier_L6=")))
    r = run("tcg", "hold", edit_lines(hl, add_after=((r"^S1 STATE export", "x" * 61000),)))
    check("run T3 black-box text over 60,000 B fails", r["verdict"] == "fail" and has(r, "missing_bb_text=over_60000"))

    r = run("board", "host")
    check("run B2 synthetic passes", r["verdict"] == "pass" and r["step"] == "B2" and has(r, "b2=pass") and
          has(r, "fdt_sha256=none"))
    bl = syn_log("board", "host", dtb, conf_bytes, cmdline)
    r = run("board", "host", edit_lines(bl, sub=((r"^S1 CANARY c2 verify=ok$", "S1 CANARY c2 verify=bad "
                                                                                "first_off=0x0 words=1"),)))
    check("run B2 canary verify=bad fails", r["verdict"] == "fail" and has(r, "missing_canaries_all_ok"))
    r = run("board", "host", edit_lines(bl, sub=((r" fdt=none", ""),)))
    check("run B2 without fdt=none refuses the verdict", r["verdict"] == "refused")
    r = run("board", "boot")
    check("run B3 synthetic passes", r["verdict"] == "pass" and r["step"] == "B3" and has(r, "item2=pass") and
          has(r, "tier_L7=ok") and has(r, "bb_consistent=yes"))
    r = run("board", "boot", ref=False)
    check("run B3 without the T2 conf sha256 fails item 2", r["verdict"] == "fail" and
          has(r, "missing_conf_ref=not_given"))
    r = run("board", "boot", kexec=None)
    check("run B3 without the kexec tree sha256 refuses", r["verdict"] == "refused" and
          has(r, "item5=refused missing=kexec_tree_sha256"))
    r = run("board", "boot", bb=None)
    check("run B3 without a black box fails L7", r["verdict"] == "fail" and "blackbox_not_given" in
          next(ln for ln in r["lines"] if ln.startswith("tier_L7=")))
    b3 = syn_log("board", "boot", dtb, conf_bytes, cmdline)
    r = run("board", "boot", bb=syn_blackbox(edit_lines(b3, add_after=((r"^S1 STATE hostcheck",
                                                                        "S1 NOTE black box only"),))))
    check("run B3 black box inconsistent with COM3 fails", r["verdict"] == "fail" and has(r, "bb_consistent=no"))
    r = run("board", "boot", edit_lines(b3, add_after=((r"^T234-SHIM", "BAD-LANDING pc=0000000080000000"),)))
    check("run B3 BAD-LANDING fails L0", r["verdict"] == "fail" and "neg_bad_landing" in
          next(ln for ln in r["lines"] if ln.startswith("tier_L0=")))
    r = run("board", "boot", edit_lines(b3, drop=(r"^ESC to enter|^F11 to enter|^Enter to continue",)))
    check("run B3 no firmware banner after reset fails L7", "firmware_banner_after_reset" in
          next(ln for ln in r["lines"] if ln.startswith("tier_L7=")))
    r = run("board", "boot", reset="POR")
    check("run B3 reset reason not MAINSWRST fails L7", r["verdict"] == "fail")
    r = run("board", "boot", edit_lines(b3, drop=(md5_line_re,)))
    check("run B3 with no target md5 lines fails item 2", r["verdict"] == "fail" and has(r, "item2=fail") and
          "target_md5_absent" in next(ln for ln in r["lines"] if ln.startswith("missing_conf_identity=")))
    r = run("board", "hold")
    check("run B4 synthetic passes", r["verdict"] == "pass" and r["step"] == "B4" and has(r, "item4=pass") and
          has(r, "item2=pass"))
    b4 = syn_log("board", "hold", dtb, conf_bytes, cmdline)
    r = run("board", "hold", edit_lines(b4, drop=(r"^STAMP end_ok",)))
    check("run B4 missing end_ok fails item 4 (D10)", r["verdict"] == "fail" and
          has(r, "item4=fail") and "end_ok=no" in next(ln for ln in r["lines"] if ln.startswith("item4=")))
    r = run("board", "hold", edit_lines(b4, sub=((r"^S1 HB k=7 qvm=alive rc=absent$", "S1 HB k=7 qvm=gone rc=present"),)))
    check("run B4 a dead heartbeat fails", r["verdict"] == "fail")
    r = run("board", "hold", edit_lines(b4, sub=((r"^S1 ALLOC hold mib=256 fill=ok verify=ok$",
                                                  "S1 ALLOC hold mib=256 fill=ok verify=bad"),)))
    check("run B4 hold allocation verify=bad fails", r["verdict"] == "fail")
    other_conf = ((r" conf_sha256=[0-9a-f]{64}", " conf_sha256=" + "f" * 64),)
    r = run("board", "hold", edit_lines(b4, sub=other_conf))
    check("run B4 with a changed conf_sha256 fails item 4 and the verdict", r["verdict"] == "fail" and
          has(r, "item4=fail") and "conf_identity" in next(ln for ln in r["lines"] if ln.startswith("item4=")) and
          "conf_ref" in r["lines"][-1])
    r = run("board", "hold", ref=False)
    check("run B4 without the T2 conf sha256 fails", r["verdict"] == "fail" and has(r, "missing_conf_ref=not_given"))
    r = run("board", "q2")
    check("run B5 synthetic passes", r["verdict"] == "pass" and has(r, "item3=pass"))
    r = run("board", "q2", edit_lines(syn_log("board", "q2", dtb, conf_bytes, cmdline), sub=other_conf))
    check("run B5 with a changed conf_sha256 fails", r["verdict"] == "fail" and "conf_identity" in r["lines"][-1])
    r = run("board", "q2", edit_lines(syn_log("board", "q2", dtb, conf_bytes, cmdline), drop=(r"^S1 BOTH alive",)))
    check("run B5 without S1 BOTH alive fails item 3", r["verdict"] == "fail" and has(r, "item3=fail"))
    # end to end: outputs into a temporary directory (no git-ignore query outside the repository)
    lines = syn_log("board", "boot", dtb, conf_bytes, cmdline)
    data = ("\n".join(lines) + "\n").encode("latin-1")
    res = analyze_run(data, profile="board", mode="boot", conf_bytes=conf_bytes, conf_info=info, conf_gate_ok=True,
                      bb_data=syn_blackbox(lines), ref_conf_sha256=sha256(conf_bytes), reset_reason="MAINSWRST",
                      kexec_tree_sha256=SYN_KEXEC)
    text = run_report(os.path.join(tdir, "com3.log"), data, None, None, DEFAULT_CONF, conf_bytes,
                      allow_text.encode("latin-1"), res, "board", "boot")
    written = write_run_outputs(os.path.join(tdir, "out"), res, text, check=False)
    with open(os.path.join(tdir, "out", "s1-fdt.dtb"), "rb") as f:
        check("run writes the decoded fdt byte for byte", f.read() == dtb)
    check("run writes parse-s1.txt", any(p.endswith("parse-s1.txt") for p in written))

    def refuse_report(p):
        if p.endswith("parse-s1.txt"):
            raise Refused("stand-in refusal")

    try:
        write_run_outputs(os.path.join(tdir, "out2"), res, text, check=refuse_report)
        check("run writes nothing when any output path is refused", False)
    except Refused:
        check("run writes nothing when any output path is refused", not os.path.exists(os.path.join(tdir, "out2")))
    try:
        PM.check_out_path(os.path.join(REPO, "orin-native", "s1", "parse-s1.py"))
        check("run refuses a tracked output path", False)
    except Refused:
        check("run refuses a tracked output path", True)

    # ---- kshcheck: parse-m4.py's implementation, imported
    check("kshcheck is parse-m4.py's function", kshcheck_text is PM.kshcheck_text and
          os.path.normcase(os.path.abspath(PM.__file__)) == os.path.normcase(os.path.abspath(PARSE_M4_PATH)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_kshcheck(argparse.Namespace(selftest=True, file=None))
    check("kshcheck parse-m4.py's own selftest passes through the import", rc == 0 and "KSHCHECK selftest ok" in
          buf.getvalue())
    for s in ('bwait -k 60 -o "$S/dry.out" -e "$S/dry.err" -- /proc/boot/qvm @/data/s1/s1-linux.conf '
              'set fdt-dump-file /dev/shmem/s1-fdt.dtb dryrun',
              "s1con -O -i /dev/ptyp3 -o \"$S/hvc0\" -w 'i_ready=echo S1-SHELL-$((40+2))-OK' &",
              'bwait -p "$S/shell_ok.hit" -p "$S/l_rbfail.hit" -t 120 || say "FAIL shell_ok"'):
        check(f"kshcheck accepts {s[:40]!r}", not kshcheck_text(s + "\n"))
    for s in ('base64 "$S/s1-fdt.dtb" | tcu-cat', 'F=$(md5sum /data/s1/Image)',
              'say "S1-SHELL-$((40+2))-OK"'):
        check(f"kshcheck rejects {s[:40]!r}", bool(kshcheck_text(s + "\n")))
    for label, body, want in (("clean script exits 0", "say ok\n", 0), ("piped script exits 1", "a | b\n", 1)):
        p = os.path.join(tdir, "t.ksh")
        with open(p, "w", encoding="latin-1", newline="\n") as f:
            f.write(body)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_kshcheck(argparse.Namespace(selftest=False, file=p))
        check(f"kshcheck {label}", rc == want)

    for name in os.listdir(os.path.join(tdir, "out")):
        os.remove(os.path.join(tdir, "out", name))
    os.rmdir(os.path.join(tdir, "out"))
    for name in os.listdir(tdir):
        os.remove(os.path.join(tdir, name))
    os.rmdir(tdir)
    ok = all(results)
    print(f"S1PC-SELFTEST result={'ok' if ok else 'fail'} cases={len(results)} failed={results.count(False)}")
    return 0 if ok else 1


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description="The PC side of S1-F (s1-design.md §3.7, §5, §6.2).")
    ap.add_argument("--selftest", dest="all_selftest", action="store_true",
                    help="every subcommand against synthetic inputs")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("conf")
    c.add_argument("file")
    c.add_argument("--allow")
    c.add_argument("--overlay")

    f = sub.add_parser("fdt")
    f.add_argument("dtb")
    f.add_argument("--conf")

    r = sub.add_parser("run")
    r.add_argument("log")
    r.add_argument("--profile", choices=("tcg", "board"), default="tcg")
    r.add_argument("--mode", choices=("dryrun", "boot", "hold", "host", "q2"), default="boot")
    r.add_argument("--blackbox")
    r.add_argument("--out-dir")
    r.add_argument("--conf")
    r.add_argument("--ref-conf-sha256")
    r.add_argument("--reset-reason")
    r.add_argument("--kexec-tree-sha256")
    r.add_argument("--image")
    r.add_argument("--initrd")

    k = sub.add_parser("kshcheck")
    k.add_argument("file", nargs="?")
    k.add_argument("--selftest", action="store_true")

    a = ap.parse_args(argv)
    if a.all_selftest:
        return selftest()
    if not a.cmd:
        ap.print_usage(sys.stderr)
        return 2
    handlers = {"conf": cmd_conf, "fdt": cmd_fdt, "run": cmd_run, "kshcheck": cmd_kshcheck}
    try:
        return handlers[a.cmd](a)
    except Refused as e:
        print(out_line(f"parse-s1: refused: {e}"), file=sys.stderr)
        return 2
    except InputError as e:
        print(out_line(f"parse-s1: input error: {e}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
