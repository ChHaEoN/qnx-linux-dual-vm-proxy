#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""parse-s1.py: the PC side of S1-F (Phase 3b).

Implements results/orin-native-port/20260909T1100Z/s1-design.md (revision 2;
the owner took D1-D19 as recommended): the configuration gate of §3.7 (D13,
D19), the FDT checklist of §6.2 read with our own reader (D12), the tier and
pass rules of §5.1-§5.2 with D10's end_ok, and the pipe-free rule of §2 rule 7.
Also revision 3's §15.5 A3: the J diagnostic parse of B2's image (run --diag), and §15.5 B7:
the J6 watcher's parse (run --diag j1) and its analyzer (canwatch). Standard library only
(canwatch's --kpf loads kpf-decode.py, beside this script, on first use).

  parse-s1.py conf FILE [--allow FILE] [--overlay FILE]
  parse-s1.py fdt DTB [--conf FILE]
  parse-s1.py run LOG [--profile tcg|board] [--mode dryrun|boot|hold|host|q2]
                  [--blackbox FILE] [--out-dir DIR|none] [--conf FILE]
                  [--ref-conf-sha256 HEX] [--reset-reason TEXT]
                  [--kexec-tree-sha256 HEX] [--image FILE] [--initrd FILE]
                  [--diag j2|j2b|j4|j1] [--arm control|remove] [--fill-factor F]
                  [--hold-mib MIB] [--kpf HEADER [--kpf HEADER]]
  parse-s1.py canwatch LOG --fill-factor F [--bin-dir DIR] [--kpf HEADER [--kpf HEADER]]
                  [--out-dir DIR|none]
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

run --diag j2|j2b|j4   (s1-design.md §15.5 A3; --profile board --mode host only)
       The same log and B2's line rules for the tiers and canaries, but a
       diagnostic parse, never a pass run (§2 rule 3): step=J2|J2b|J4, no b2=
       field, and verdict=diagnostic complete, or diagnostic incomplete failed=...
       Complete means every record B2's verdict reads was present and parsed,
       whatever the canary values:
         conf_gate passes; L0 and L7 are met; L1 is met apart from its
         canary_start_* values (L1_records=); item 5 is neither refused nor bad;
         for each of c1, c2 and c3, exactly one S1 CANARY line before the first
         S1 ALLOC line (c<n>_start=) and exactly one after it (c<n>_end=), each
         verify=ok or verify=bad; exactly one S1 ALLOC mib=1536 line, fill=ok with
         verify=ok or verify=bad (alloc=);
         J2 and J4, which §15.4.3's detached sequence issues: its s1wq: marker
         ending 'kexec issuing' before the shim line (wq_kexec_issuing=yes), and
         none of its abort, 'kexec did not happen' or fallback firing|forcing
         markers anywhere (wq_reset_marker=no);
         J2b, cmd_run's B2 flow with no additions: no s1wq: marker at all
         (wq_markers=none).
       A check or allocation that is not ok|bad prints absent, multiple, unread (a
       line with no verify=ok|bad: refuse=, map=fail, tool=no-output), unsplit (no
       S1 ALLOC line to split the checks) or map-fail. j_row= is the row of
       §15.4.4's or §15.4.6's table:
         F39 when any c1 or c3 check reads bad, even in an incomplete parse (a
         stop outranks a retry); otherwise F40 when incomplete; otherwise from
         c2_start and c2_end:
         J2  F32 bad at both, F32a bad then ok, F32b ok then bad, F33 ok at both;
         J2b F45 bad at either, F46 ok at both (§15.4.4's J2b table);
         J4  F35 ok at both, F36 bad at either.
       alloc=bad is recorded and changes no row: the J tables have none for it.
       F35's "Bus Master 0 at the issue" is the sequence's own refusal before its
       kexec issuing marker (§15.4.3 Phase B step 7); the parser reads no wq.log.
       Exit as run: 3 when item-5 stamps are missing, and the verdict line then
       reads incomplete with item5 among failed=.

run --diag j1 --arm control|remove --fill-factor F [--hold-mib MIB] [--kpf HEADER]...
       (s1-design.md §15.4.8, §15.5 B7; --profile board --mode host) J6: the s1-j1 image in
       jrun's control arm (step=J6c) or remove arm (step=J6r). A diagnostic parse, never a pass
       run: no b2= field, verdict=diagnostic complete, or diagnostic incomplete failed=...
       B2's line rules give conf_gate, L0, L1_records, L7 and item 5 as for J2; complete also means:
         the procnto line names s1-j1 (rung_j1=yes), and no B2 allocation line (b2_alloc_line=none);
         S1 CONFIG carries a 64-hex memcanary_w_sha256 (the generator's diag-j1 EXTRA_FIELDS stamp; not an
         item-5 field, so ITEM5_FIELDS is unchanged);
         each of the six canary checks exactly once, ok or bad: start = before the first watch or
         hold line, end = after the hold's verify line; no other S1 CANARY line in between
         (canary_between=0: a watch refusal printed in verify's form lands there);
         the hold (memcanary.c's hold forms): one 'S1 ALLOC hold mib=N fill=ok', then one verify
         line, N equal to J1_HOLD_MIB (make-s1-images.sh's, which its constant check compares with
         this file's) on both and to --hold-mib when given: hold=ok|bad (else timeout,
         timeout-bad, map-fail (F28), absent, multiple, unread, mib-differs);
         watches a, b, c and d (§15.4.8's table below): each exactly the eight success lines once,
         base to verdict in that order, on its table canary, and consistent within themselves
         (watch_<l>=ok; else absent, fail, malformed, multiple, incomplete, wrong-canary, order,
         inconsistent problems=...);
         a and b before the hold's fill line, c and d between fill and verify, a before b and c
         before d (watch_order=ok);
         exports j1a..j1d decoded and accepted by canwatch's structure and cross-check
         (export_j1<l>=ok);
         the detached sequence's markers as for J2 and J4 (wq_kexec_issuing=yes, wq_reset_marker=no).
       Also printed, never gating: kpf=, fillrate=, coincide= (canwatch's), and on a complete parse
       c2_sums (the counts the rows use).
       j_row= lists every row of §15.4.8's table that holds, comma-separated, stops first:
         F39   a c1 or c3 check bad, or a well-formed watch line on c1 with bad above 0 (both
               readable in an incomplete parse);
         F49   the hold's verify=bad, or verify=timeout data=bad (also readable when incomplete);
         F40   incomplete; no row below is read then.
         The rest are read over c2's watches a, b and c summed (the parser's reading of the
         table, pre-registered here; s1-design §15.12):
         F34                 prog 0; osc + revert above 0; flip2 (flip2_same + flip2_var) dominant
                             when bad is above 0; revert_flip2 above half of revert when revert is
                             above 0;
         live-writer         prog above 0, or changed_words above 0 with stable above 0 when F34
                             does not hold (F34 takes precedence: the two never print together);
         restoring-writer    healed above 0 with pat_same|pat_other dominant, or whole_heal above 0
                             (a page whose every word healed in one snapshot, on any c2 watch);
         ring-record         small32|hi_pat|lo_pat dominant, or bad at least 8 with the two
                             largest stride bins above half of bad;
         cpu-side            ptr_ram|u32page dominant and coincide=yes; cpu-side-lean when
                             dominant and coincide was not computed (no prequiesce --kpf);
         qnx-shaped          pte|kva dominant;
         positive-signature  ipv4 + beacon + trb_evt above 0 on any of the four watches
                             (positive-only: an absence excludes nothing);
         fill-rate           canwatch's fill-rate row differs (below-floor fires no row);
         writer-none         every c2 watch writer=none, and revert 0 (c2 clean at every scan);
         writer-static       no c2 watch stopped or ongoing, and at least one static;
         no-row              none of the above.
       "Dominant": the group's largest class count is above 0 and no class outside the group is
       larger (ties included); flip2_same and flip2_var count as one class, flip2.
       Exit as run.

run --diag j1 on --profile tcg --mode dryrun (§15.5 B8.5): step=T-J1, the TCG j1 variant. T1's
       items (conf_gate, profile, L2, fdt_gating, conf_identity), item 5, a 64-hex
       memcanary_w_sha256 in S1 CONFIG, and exactly one
       'MEMCANARY-W SELFTEST PASS <n> checks' line with n above 0 and no FAIL form, whose next
       'MEMCANARY SELFTEST' line (memcanary's own, which memcanary-w prints after it) is a PASS
       counting more than n (cw_selftest=ok|failed|absent|multiple|unpaired). A watch line fails
       profile, as asinfo and canary lines do. --arm, --fill-factor, --hold-mib and --kpf are
       usage errors here. No j_row.

canwatch LOG --fill-factor F [--bin-dir DIR] [--kpf HEADER]... [--out-dir DIR|none]
       (§15.5 B7) The J6 analyzer: counts, classes and page bitmaps only; it never reads or
       prints a word value. It reads s1-j1a.bin .. s1-j1d.bin from --bin-dir (default: LOG's
       directory, where run writes them) and LOG's watch lines. For each label: the console
       status as run gives it; the export's structure (reasons below); bin_vs_log, the file's
       bytes and md5 against LOG's S1 BEGIN (or else S1 EXPORT) record for it, which redaction of
       an export body cannot change; and the cross-check of every count with the console lines.
       For each accepted bitmap: pages set, first and last page, runs, and per-MiB page counts;
       per watch the whole-page-heal condition healed >= 512 x healed pages (necessary, not
       sufficient; a record beside the console's whole_heal, which the row reads). With --kpf
       (kpf-decode.py headers of the boot that jumped: one, or a prequiesce and postquiesce pair,
       checked as kpf-decode checks them): each bitmap's pages by
       kpageflags class, and coincide: the union of bad_final and changed_ever over c2's watches
       a-c, yes when more than half of its pages were held (not free, not nopage) in the
       prequiesce snapshot (R45: a record of Linux's CPU-side ownership, weak evidence). The
       fill-rate row: label c's changed_words per snapshot against label b's, differs when
       either rate exceeds F times the other and the larger count is at least FILL_MIN_WORDS
       (8); below-floor when they differ with fewer, and within otherwise (exact rational
       arithmetic; F a decimal >= 1, pre-registered in J-prereg.log). Output: S1CW key=value lines on stdout and in
       OUT/canwatch.txt (OUT = --out-dir or LOG's directory, git-ignored; none writes nothing),
       the last S1CW result=complete, or result=incomplete failed=... (console, export or
       bin_vs_log per label). A kpf refusal is recorded and never makes it incomplete: a snapshot
       failure never stops a rung (§15.4.3). Exit 0 printed; 1 an input error; 2 usage or a
       refused output path.

Watcher records (memcanary-w, §15.4.8; each at most 255 B, fields in exactly this order):
  S1 CANARY <c> watch=base label=<l> bad=<n> pages=<n> first_off=0x<hex> last_off=0x<hex>
  S1 CANARY <c> watch=time label=<l> snaps=<n> changed_snaps=<n> changed_words=<n> healed=<n> osc=<n> prog=<n> stable=<n> stop=count|deadline
  S1 CANARY <c> watch=reread label=<l> revert=<n> revert_flip2=<n> whole_heal=<n>
  S1 CANARY <c> watch=words label=<l> bad=<n> zero=<n> ones=<n> flip2_same=<n> flip2_var=<n> flip8=<n> pat_same=<n> pat_other=<n>
  S1 CANARY <c> watch=words2 label=<l> hi_pat=<n> lo_pat=<n> pte=<n> kva=<n> ptr_self=<n> ptr_ram=<n> u32page=<n> small32=<n> other=<n>
  S1 CANARY <c> watch=stride label=<l> b0=<n> b1=<n> b2=<n> b3=<n> b4=<n> b5=<n> b6=<n> b7=<n>
  S1 CANARY <c> watch=bytes label=<l> ascii_runs=<n> ascii_bytes=<n> ipv4=<n> beacon=<n> trb_evt=<n>
  S1 CANARY <c> watch=verdict label=<l> writer=none|static|stopped|ongoing heal=no|yes reads=stable|revert|osc|prog content=<list>|unclassified|none
  S1 CANARY <c> watch=fail label=<l> reason=nomem|dump-open|dump-write errno=<n>
A watch= line is never one of B2's canary checks: every rule of the steps above reads the S1
CANARY lines without watch=, so B2's six_verify_* semantics are unchanged.
§15.4.8's table as constants: a on c2, 0 ms, 100,000 snapshots; b and c on c2, 1,000 ms, 180;
d on c1, 1,000 ms, 60. Consistency a console watch must show (the parser's reading; <n> decimal):
  base      pages <= bad, pages <= 4096, bad = 0 exactly when pages = 0, bad <= 512 x pages; when
            bad > 0: both offsets 8-aligned, first <= last < 16 MiB, (last - first) / 8 + 1 >= bad;
  time      snaps <= the table count, and snaps = count when stop=count; changed_snaps <= snaps;
            changed_snaps = 0 exactly when changed_words = 0 (changed_words counts change events,
            one per word per snapshot); osc + prog + stable = changed_words (each change event is
            exactly one of them, A-A-C is prog, and a revert is none); healed <= changed_words;
  reread    revert_flip2 <= revert; whole_heal x 512 <= time's healed; whole_heal <= time's
            changed_snaps x 4096;
  words     the 16 word classes of words and words2 sum to words' bad (first match wins);
  stride    b0..b7 sum to words' bad;
  bytes     ascii_bytes >= 16 x ascii_runs; all five 0 when words' bad is 0;
  verdict   when changed_words = 0: none (base's and words' bad both 0), static (base's bad above
            0 and words' bad equal to it), or ongoing (memcanary-w's final read differed from the
            last snapshot, which no console count shows); when changed_words > 0: stopped or
            ongoing; heal=yes exactly when healed > 0; reads=prog when prog > 0, else osc when
            osc > 0, else revert when revert > 0, else stable; content=none exactly when words' bad is 0; otherwise
            unclassified alone, or tokens that are word classes, flip2, ascii_runs, ipv4, beacon
            or trb_evt.

Watcher export s1-j1<l>.bin (xport name j1<l>; content-free, little-endian, 1,632 B; the layout
memcanary.c's cw_export writes):
  offset 0   8 B   magic S1J1PBMP
         8   u32   version 1
         12  4 B   canary name, ASCII, NUL-padded (c1|c2|c3)
         16  8 B   label, ASCII [a-z0-9], NUL-padded
         24  u64   the canary's physical base (§3.3)
         32  u32   page count, 4096
         36  u32   interval, ms, -i (= the table's)
         40  u32   snapshots taken (= time's snaps)
         44  u32   snapshots asked, -c (= the table's count)
         48  u32   deadline, s, -T (= the table's)
         52  u32   stop: 1 count, 2 deadline (= time's stop)
         56  8 B   zero
         64  512 B bad_final     one bit per 4 KiB page, page p = bit p % 8 of byte p // 8 (LSB first)
         576 512 B changed_ever
         1088 512 B healed_ever
         1600 4 u64: bad_base, bad_final, changed_words, healed
  Refusal reasons, first failing check in this order: short, magic, version, page-count, size,
  name (not the label's table canary), label (not the expected label), base, reserved,
  interval, request (the asked count or deadline is not the table's, or stop is neither 1 nor
  2), snaps (above the asked count), counts (healed <= changed_words; snaps = the count when
  stop is 1; or a bitmap against its count: pages set 0 exactly when the count is 0, pages <=
  count, and bad_final <= 512 x its pages), healed-not-changed (a healed page not in
  changed_ever); then, against the console, console-absent (no parsed watch for the label) and
  console-mismatch fields=... (snaps and stop against time's, and the four tail counts against
  base's bad, words' bad and time's).

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
  S1 DRYRUN rc=0 saved=yes fdt_bytes=<n> fdt_md5=<hex> logger_errors=0
                                        (rc is recorded as dryrun_rc=; accepted only as 0)
  STAMP <label> ...                     (stamp's own line)
  S1 HOLD start secs=600 | S1 HOLD end qvm=alive
  S1 ALLOC hold mib=<n> fill=ok [verify=ok]   and a later line with verify=ok
  S1 ALLOC mib=1536 fill=ok verify=ok
  S1 HB k=<1..10> qvm=alive rc=absent
  S1 GUESTRAM w1=yes|no w2=yes|no | S1 GUESTRAM unknown
  S1 BOTH alive
  S1 FAIL_STATE none
  rc=<n>                                (cat of qvm.rc; before S1 STATE teardown it fails L4)
Read by --diag only, from L4T's console before the kexec (§15.4.3; /dev/kmsg lines, so
a printk time may precede them): s1wq: ... kexec issuing; s1wq: ... abort reason=...;
s1wq: ... kexec did not happen; s1wq: ... fallback firing|forcing.
Exports, the framing of orin-native/m4dry/m4dry-host.ksh.in's kevblock with the
S1 prefix:
  S1 BEGIN name=<name> bytes=<n> md5=<hex> enc=base64
  <base64 lines>
  S1 END name=<name>
enc=gzip-base64 adds gz_bytes= and gz_md5= of the gzip layer, as m4dry does;
enc=text carries raw lines: the md5 is over the body lines exactly as captured,
trailing blanks kept, one trailing CR (the capture's) removed from each, each
ending in LF. It frames only LF-only text that ends in LF; anything else is base64.
A guest mode's qvmlog export (the dryrun's stdout and stderr) must decode, and no
line of it may begin with qvm's configuration-diagnostic form '[file:line] '
(C3 as tightened after T1 attempt 1, s1-design.md §14.9).

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
import shutil
import struct
import sys
import tempfile
import zlib
from fractions import Fraction

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
    " hostdev /dev/ptyp3\n"
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

# C3 as tightened after T1 attempt 1 (s1-design.md §14.9): a dryrun is accepted only
# with rc=0, saved=yes, logger_errors=0, a decoded qvmlog export, and no line of that
# export in qvm's configuration-diagnostic form '[file:line] message' at the line start
# (attempt 1's was "[/data/s1/s1-linux.conf:14] Unable to open ..."). The host script
# counts the same lines into logger_errors; the PC counts them again from the export.
QVM_DIAG_RE = re.compile(r"^\[[^\]]+:[0-9]+\] ")
DRYRUN_ACCEPT = ("dryrun", "dryrun_rc", "dryrun_rc_not_0", "dryrun_saved", "dryrun_logger_errors",
                 "qvmlog_export", "dryrun_qvm_diagnostics")


def qvm_diagnostics(data):
    """Lines of qvm's text in the '[file:line] message' form, each CR removed first (§14.9)."""
    return sum(1 for ln in data.decode("latin-1").split("\n") if QVM_DIAG_RE.match(ln.replace("\r", "")))

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

# Revision 3's J diagnostic parse of B2's image (s1-design.md §15.5 A3): board host mode only.
DIAG_STEPS = {"j2": "J2", "j2b": "J2b", "j4": "J4"}
CANARY_CHECKS = tuple(f"{c}_{k}" for c in CANARIES for k in ("start", "end"))
# §15.4.3's markers go to /dev/kmsg, so on COM3 a printk time may stand before them.
WQ_MARK_RE = re.compile(r"(?:^|[\s\]])s1wq:(?:\s|$)")
WQ_ISSUING_RE = re.compile(r"(?:^|[\s\]])s1wq:\s(?:.*\s)?kexec issuing\s*$")
WQ_RESET_RE = re.compile(r"(?:^|[\s\]])s1wq:\s.*"
                         r"(?:abort reason=|kexec did not happen|fallback firing|fallback forcing)")


def diag_row(diag, checks, complete):
    """The §15.4.4 or §15.4.6 table row of a J parse, from the six canary checks (ok|bad|...)."""
    if any(checks[f"{c}_{k}"] == "bad" for c in ("c1", "c3") for k in ("start", "end")):
        return "F39"
    if not complete:
        return "F40"
    both = (checks["c2_start"], checks["c2_end"])
    if diag == "j2":
        return {("bad", "bad"): "F32", ("bad", "ok"): "F32a", ("ok", "bad"): "F32b", ("ok", "ok"): "F33"}[both]
    if diag == "j2b":
        return "F46" if both == ("ok", "ok") else "F45"
    return "F35" if both == ("ok", "ok") else "F36"


# Revision 3's J6 watcher (s1-design.md §15.4.8, §15.5 B7): memcanary-w's console lines and its
# page-bitmap exports, read by run --diag j1 and canwatch. Counts, classes and page bitmaps only:
# no word value, byte or pointer value leaves the target, so none is read or printed here.
J1_STEPS = {("board", "host"): {"control": "J6c", "remove": "J6r", "uefi": "J7a"}, ("tcg", "dryrun"): {None: "T-J1"}}
J1_ARMS = ("control", "remove")
J1_RUNG = "s1-j1"
J1_HOLD_MIB = 2896      # make-s1-images.sh's J1_HOLD_MIB, s1-j1's hold size (its constant check compares the two)
DIAG_CHOICES = tuple(DIAG_STEPS) + ("j1",)
WPAGE = 4096
WPAGES = CANARY_SIZE // WPAGE                   # pages per canary: one bit each in a bitmap
WWORDS = WPAGE // 8                             # 8-byte words per page
# §15.4.8's host-script table: label -> (canary, interval ms, count). Deadlines and bounds are the script's.
WATCH_LABELS = {"a": ("c2", 0, 100000), "b": ("c2", 1000, 180), "c": ("c2", 1000, 180), "d": ("c1", 1000, 60)}
# The same table's deadlines (-T, seconds), which the export's header carries.
WATCH_DEADLINE_S = {"a": 20, "b": 190, "c": 190, "d": 70}
WATCH_C2 = ("a", "b", "c")
WATCH_KINDS = ("base", "time", "reread", "words", "words2", "stride", "bytes", "verdict")   # a complete watch, in order
_NUM = r"[0-9]{1,20}"                           # memcanary-w prints its u64 counts in decimal
_WORDS1 = ("zero", "ones", "flip2_same", "flip2_var", "flip8", "pat_same", "pat_other")
_WORDS2 = ("hi_pat", "lo_pat", "pte", "kva", "ptr_self", "ptr_ram", "u32page", "small32", "other")
WORD_CLASSES = _WORDS1 + _WORDS2
SIGNATURES = ("ipv4", "beacon", "trb_evt")
WATCH_FIELDS = {
    "base": (("bad", _NUM), ("pages", _NUM), ("first_off", r"0x[0-9a-f]{1,8}"), ("last_off", r"0x[0-9a-f]{1,8}")),
    "time": tuple((k, _NUM) for k in ("snaps", "changed_snaps", "changed_words", "healed", "osc", "prog", "stable"))
    + (("stop", "count|deadline"),),
    "reread": tuple((k, _NUM) for k in ("revert", "revert_flip2", "whole_heal")),
    "words": (("bad", _NUM),) + tuple((k, _NUM) for k in _WORDS1),
    "words2": tuple((k, _NUM) for k in _WORDS2),
    "stride": tuple((f"b{k}", _NUM) for k in range(8)),
    "bytes": tuple((k, _NUM) for k in ("ascii_runs", "ascii_bytes") + SIGNATURES),
    "verdict": (("writer", "none|static|stopped|ongoing"), ("heal", "no|yes"), ("reads", "stable|revert|osc|prog"),
                ("content", r"[a-z0-9_]+(?:,[a-z0-9_]+)*")),
    "fail": (("reason", "nomem|dump-open|dump-write"), ("errno", _NUM)),
}
WATCH_RE = {kind: re.compile(r"^S1 CANARY (c1|c2|c3) watch=" + kind + r" label=([a-z0-9]{1,8})" +
                             "".join(f" {name}=({pat})" for name, pat in fields) + r"$")
            for kind, fields in WATCH_FIELDS.items()}
WATCH_ANY_RE = re.compile(r"^S1 CANARY (\S+) watch=(\S*)(?: label=(\S+))?")
WATCH_LINE_MAX = 255
CONTENT_WORDS = frozenset(WORD_CLASSES + ("flip2", "ascii_runs") + SIGNATURES)
# Dominance reads flip2_same and flip2_var as one class (§15.4.8: "flip2 (same and var together)").
DOM_CLASSES = ("zero", "ones", "flip2", "flip8", "pat_same", "pat_other") + _WORDS2
LEAN_RESTORING = ("pat_same", "pat_other")
LEAN_RING = ("hi_pat", "lo_pat", "small32")
LEAN_CPU = ("ptr_ram", "u32page")
LEAN_QNX = ("pte", "kva")
STRIDE_MIN_BAD = 8
J6_ROWS = ("F39", "F49", "F40", "F34", "live-writer", "restoring-writer", "ring-record", "cpu-side", "cpu-side-lean",
           "qnx-shaped", "positive-signature", "fill-rate", "writer-none", "writer-static", "no-row")
CW_MAGIC = b"S1J1PBMP"
CW_VERSION = 1
# memcanary.c's cw_export: magic, version, name, label, base, pages, interval, snaps, count, deadline, stop, zero
CW_HEAD = struct.Struct("<8sI4s8sQIIIIII8s")
CW_TAIL = struct.Struct("<4Q")
CW_MAPS = ("bad_final", "changed_ever", "healed_ever")
CW_TAIL_FIELDS = ("bad_base", "bad_final", "changed_words", "healed")
CW_STOPS = {1: "count", 2: "deadline"}
CW_MAP_BYTES = (WPAGES + 7) // 8
CW_SIZE = CW_HEAD.size + len(CW_MAPS) * CW_MAP_BYTES + CW_TAIL.size
CW_REASONS = ("short", "magic", "version", "page-count", "size", "name", "label", "base", "reserved", "interval",
              "request", "snaps", "counts", "healed-not-changed", "console-absent", "console-mismatch")
CW_SELFTEST_RE = re.compile(r"^MEMCANARY-W SELFTEST (?:PASS ([0-9]+) checks|FAIL ([0-9]+) of ([0-9]+) checks)$")
# memcanary's own self-test line; memcanary-w prints it right after its watcher line, counting both sets.
MC_SELFTEST_RE = re.compile(r"^MEMCANARY SELFTEST (?:PASS ([0-9]+) checks|FAIL ([0-9]+) of ([0-9]+) checks)$")
# The fill-rate row's floor: rates that differ by the factor are read as differs only when the larger
# of labels b and c has at least this many change events; below it the result is below-floor, which
# fires no row (a reading added before J6's pre-registration; HYPOTHESIS on what a stray change is).
FILL_MIN_WORDS = 8
CW_LIMIT = ("counts, classes and page bitmaps only: no word value, byte or pointer value is read or printed "
            "(s1-design.md 15.4.8); page classes from kpageflags describe Linux's CPU-side ownership only (R45)")
EXPORT_REC_RE = re.compile(r"^S1 EXPORT name=(\S+)(?: (.*))?$")
FACTOR_RE = re.compile(r"^[0-9]{1,6}(?:\.[0-9]{1,6})?$")

# Revision 3's J7a (s1-design.md §15.13): s1-j1, unchanged, entered from the UEFI Shell by the M5L_J7A
# loader. `run --diag j1 --entry uefi --arm uefi` reads one COM3 segment; `--entry kexec` (the default)
# leaves every earlier parse byte-identical (R92). The loader's lines are m5load.c's and §15.13.3's
# UM2-UM9; they reach COM3 through the firmware console, so CSI sequences are stripped before matching.
ENTRIES = ("kexec", "uefi")
J7A_ARM = "uefi"
CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
M5L_RX = {
    "start": re.compile(r"^M5L start mode=(check|go) el=([0-9]+)(?!\S)"),
    "variant": re.compile(r"^M5L variant=j7a$"),
    "self": re.compile(r"^M5L self w2=(yes|no) canary=(none|c1|c2|c3)$"),
    # m5load.c's b_hex: lowercase hex without 0x or leading zeros; crc32=fail is no stamp
    "fdt": re.compile(r"^M5L fdt addr=\S+ size=\S+ crc32=([0-9a-f]{1,8})$"),
    "crc_src": re.compile(r"^M5L crc src=ok$"),
    "crc_dst": re.compile(r"^M5L crc dst=ok$"),
    "resmem": re.compile(r"^M5L resmem name=(\S+) (.*)$"),
    "resmem_done": re.compile(r"^M5L resmem done$"),
    "preclaim": re.compile(r"^M5L canary (c1|c2|c3) preclaim=ok$"),
    "w2": re.compile(r"^M5L W2 PASS$"),
    "check": re.compile(r"^M5L CHECK PASS$"),
    "go": re.compile(r"^M5L GO$"),
    "refuse": re.compile(r"^M5L REFUSE(?!\S)"),
}
# m5load-head.S's post-exit tokens, printed on the TCU after ExitBootServices (searched, not anchored).
M5L_EBS_RE = re.compile(r"M5L-EBS(?!\S)")
M5L_EBS_OK_RE = re.compile(r"M5L-EBS ok(?!\S)")
M5L_JUMP_RE = re.compile(r"M5L-JUMP(?!\S)")
# §15.13.7: zero of these after the counted M5L GO (text before it is unconstrained); any s1wq: marker too.
J7A_NEG_AFTER_GO = (("m5l_exc", re.compile(r"M5L-EXC")), ("ebs_fail", re.compile(r"M5L-EBS FAIL")),
                    ("bad_landing", re.compile(r"BAD-LANDING")), ("exc", re.compile(r"EXC ")),
                    ("el_not_2", re.compile(r"EL!=2")), ("kexec", re.compile(r"kexec_core: Starting new kernel")),
                    ("s1wq", WQ_MARK_RE))
J7A_ROWS = ("clean", "bad", "bad-partial", "bad-unstable", "revert-only", "unsettled", "F39c1", "F39c3", "F49", "F62",
            "incomplete")
J7A_FLIP_PAT = ("flip2_same", "flip2_var", "flip8", "pat_same", "pat_other")
# §15.13.10.3 P7: pages in common at least this fraction of each side's bad_final set (a design constant).
P7_SHARE = Fraction(1, 2)
J6C_REF_FILES = ("parse-s1.txt", "canwatch.txt", "s1-j1a.bin", "s1-j1b.bin", "s1-j1c.bin")


def content_rule(counts, bad):
    """memcanary.c's cw_content over counts (class -> n): every class but other holding at least a quarter
    of bad, most first, ties in class order; 'none' with no bad word and 'unclassified' when none holds."""
    if bad == 0:
        return "none"
    got = [k for k in WORD_CLASSES if k != "other" and counts.get(k, 0) and counts[k] * 4 >= bad]
    got.sort(key=lambda k: -counts[k])        # sort is stable, so ties stay in class order
    return ",".join(got) or "unclassified"


def c2_f34(s):
    """§15.12 B5's F34 over j6_sums' counts: prog 0; osc or revert above 0; flip2 dominant in the bad set
    when it has words; more than half the reverts revert_flip2 when there are any."""
    d = j6_dom_counts(s)
    return (s["prog"] == 0 and s["osc"] + s["revert"] > 0 and (s["bad"] == 0 or j6_dominant(d, ("flip2",))) and
            (s["revert"] == 0 or 2 * s["revert_flip2"] > s["revert"]))


def p7_compare(mask_j7a, mask_j6c):
    """§15.13.10.3 P7 on two page bitmaps (bit p = page p of c2): (same, common, only_j7a, only_j6c, presence_same).
    same needs the per-MiB presence vector identical and the pages in common at least P7_SHARE of each set."""
    per = MIB // WPAGE

    def presence(mask):
        return {p // per for p in _bits(mask)}

    common = _pop(mask_j7a & mask_j6c)
    n7, n6 = _pop(mask_j7a), _pop(mask_j6c)
    pres = presence(mask_j7a) == presence(mask_j6c)
    same = pres and common >= P7_SHARE * n7 and common >= P7_SHARE * n6 and n7 > 0 and n6 > 0
    return same, common, n7 - common, n6 - common, pres


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


def j7a_loader(recs):
    """J7a's loader lines in one COM3 segment (s1-design.md §15.13.7). Returns a dict:

    go_i (index of the counted M5L GO, or None), counted (how many GOs were counted), checks
    ({name: True when met}), crc32 (the fdt stamp or None), resmem (the go run's resmem lines as
    {field: text} dicts) and neg (names of negative tokens after the counted GO).

    A GO is counted when no M5L REFUSE comes after it before the next M5L-EBS token (or before the
    next M5L start line or the segment's end when no EBS follows). The Shell visit is the text after
    the last firmware banner before the counted GO's start line; its last check run before that start
    line is T1'. Lines are CSI-stripped and left-stripped first. Nothing here reads a value.
    """
    lines = [(i, CSI_RE.sub("", t).lstrip(" \t")) for i, t in recs]
    starts = [(i, m.group(1), m.group(2)) for i, t in lines for m in [M5L_RX["start"].match(t)] if m]
    gos = [i for i, t in lines if M5L_RX["go"].match(t)]
    refuses = [i for i, t in lines if M5L_RX["refuse"].match(t)]
    ebs = [i for i, t in lines if M5L_EBS_RE.search(t)]
    counted = []
    for g in gos:
        nxt_start = next((i for i, _m, _e in starts if i > g), None)
        stop = next((i for i in ebs if i > g), nxt_start)
        if not any(g < i and (stop is None or i < stop) for i in refuses):
            counted.append(g)
    out = {"go_i": counted[0] if len(counted) == 1 else None, "counted": len(counted), "checks": {}, "crc32": None,
           "resmem": [], "neg": []}
    ck = out["checks"]
    # check_end is M5L CHECK PASS; a J7a parse never prints the word pass (§15.13.7)
    names = ("check_start", "check_run", "go_start", "go_run", "prelude_same", "check_end", "fdt_crc32",
             "after_go", "neg_after_go")
    for n in names:
        ck[n] = False
    if out["go_i"] is None:
        return out
    g = out["go_i"]
    go_start = next((i for i, mode, _e in reversed(starts) if i < g), None)
    if go_start is None or dict((i, (m, e)) for i, m, e in starts)[go_start] != ("go", "2"):
        return out
    ck["go_start"] = True
    banner = max((i for i, t in lines if i < go_start and any(b in t for b in FW_BANNER)), default=-1)
    chk = [(i, e) for i, m, e in starts if m == "check" and banner < i < go_start]
    if chk and chk[-1][1] == "2":
        ck["check_start"] = True
    chk_i = chk[-1][0] if chk else None

    def run_lines(a, b):
        """The M5L lines strictly between index a and index b (the start line excluded)."""
        return [t for i, t in lines if a < i < b and t.startswith("M5L ")]

    def run_ok(body):
        """UM2 directly after the start line, then the checks every run needs, with no refusal."""
        if len(body) < 2 or not M5L_RX["variant"].match(body[0]):
            return False
        sm = M5L_RX["self"].match(body[1])
        pre = [M5L_RX["preclaim"].match(t).group(1) for t in body if M5L_RX["preclaim"].match(t)]
        need = ("crc_src", "crc_dst", "resmem_done", "w2")
        return (sm is not None and sm.group(2) == "none" and pre == ["c1", "c2", "c3"] and
                all(sum(1 for t in body if M5L_RX[k].match(t)) == 1 for k in need) and
                not any(M5L_RX["refuse"].match(t) for t in body))

    go_body = run_lines(go_start, g)
    ck["go_run"] = run_ok(go_body)
    if chk_i is not None:
        cend = next((i for i, t in lines if chk_i < i < go_start and M5L_RX["check"].match(t)), None)
        ck["check_end"] = cend is not None
        chk_body = run_lines(chk_i, cend if cend is not None else go_start)
        ck["check_run"] = run_ok(chk_body)
        ck["prelude_same"] = cend is not None and chk_body == go_body
    fdts = [M5L_RX["fdt"].match(t) for t in go_body if M5L_RX["fdt"].match(t)]
    if len(fdts) == 1:
        out["crc32"] = fdts[0].group(1).lower()
        ck["fdt_crc32"] = True
    for t in go_body:
        m = M5L_RX["resmem"].match(t)
        if m:
            kv, _ = parse_kv(m.group(2))
            out["resmem"].append(dict(kv, name=m.group(1)))
    # after the counted GO, in order: M5L-EBS ok, M5L-JUMP, the shim line with its PC, then t234: WDT0
    pos, seq_ok = g, True
    first_ebs = next((i for i in ebs if i > g), None)
    for rx, pc in ((M5L_EBS_OK_RE, False), (M5L_JUMP_RE, False), (RX["shim"], True), (RX["wdt0"], False)):
        j = next((i for i, t in lines if i > pos and rx.search(t)), None)
        if j is None or (rx is M5L_EBS_OK_RE and j != first_ebs):
            seq_ok = False
            break
        if pc and not any(RX["shim_pc"].search(t) for i, t in lines if j <= i <= j + 3):
            seq_ok = False
            break
        pos = j
    ck["after_go"] = seq_ok
    out["neg"] = [n for n, rx in J7A_NEG_AFTER_GO if any(i > g and rx.search(t) for i, t in lines)]
    ck["neg_after_go"] = not out["neg"]
    return out


def j7a_resmem_summary(resmem):
    """(resmem_c2, resmem_c2_base) from the go run's UM9 lines: node names over c2 (the name before any
    unit address, so no address is printed), or none; base yes when such a line reads base=yes."""
    over = [r for r in resmem if "c2" in (r.get("over") or "").split(",")]
    names = []
    for r in over:
        n = r["name"].split("@", 1)[0]
        if n not in names:
            names.append(n)
    return (",".join(names) or "none"), ("yes" if any(r.get("base") == "yes" for r in over) else "no")


def analyze_run(data, *, profile, mode, conf_bytes, conf_info, conf_gate_ok, bb_data=None, ref_conf_sha256=None,
                reset_reason=None, kexec_tree_sha256=None, pc_image=None, pc_initrd=None, diag=None, arm=None,
                fill_factor=None, hold_mib=None, kpf_paths=(), entry="kexec", loader_sha256=None):
    """The §5.1 tiers and §5.2 items of one run. Returns a dict: lines, blocks, verdict, refused.

    entry uefi is J7a (s1-design.md §15.13.7): diag j1, arm uefi, board host mode, one COM3 segment,
    loader_sha256 in place of kexec_tree_sha256. entry kexec (the default) changes nothing.

    conf_gate_ok is conf_check's result for conf_bytes; pc_image and pc_initrd are
    the PC's payload bytes, or None when not given. diag is None, or j2, j2b or j4
    for §15.5 A3's diagnostic parse of a board host-mode log (the dict adds j_row),
    or j1 for §15.5 B7's: J6 on a board host-mode log with arm control|remove, the
    pre-registered fill_factor, and optionally hold_mib and kpf_paths (the dict adds
    j_row), or T-J1 on a TCG dryrun log with none of those.
    """
    if entry not in ENTRIES:
        raise InputError(f"--entry {entry!r} is not kexec or uefi (s1-design.md 15.13.7)")
    uefi = entry == "uefi"
    if uefi and (diag != "j1" or (profile, mode) != ("board", "host") or arm != J7A_ARM):
        raise InputError("--entry uefi reads J7a's segment only: --diag j1 --arm uefi --profile board --mode host "
                         "(s1-design.md 15.13.7)")
    if arm == J7A_ARM and not uefi:
        raise InputError("--arm uefi needs --entry uefi (s1-design.md 15.13.7)")
    if diag == "j1":
        steps = J1_STEPS.get((profile, mode))
        if steps is None or arm not in steps:
            raise InputError("--diag j1 reads J6's board host-mode log with --arm control|remove, or T-J1's TCG "
                             "dryrun log with no --arm (s1-design.md 15.5 B7)")
        if profile == "board":
            fill_factor = cw_factor(fill_factor)
    elif diag is not None and (diag not in DIAG_STEPS or (profile, mode) != ("board", "host")):
        raise InputError(f"--diag {diag} reads only a board host-mode log (s1-design.md 15.5 A3)")
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
    # a J7a parse never prints pass (s1-design.md §15.13.7); every earlier parse keeps its word
    put("conf_gate", ("ok" if uefi else "pass") if conf_gate_ok else "fail")
    ram_base, ram_size = parse_ram(conf_info["ram"])
    end_i = len(raw)
    reset_i, reset_m = R.first(RX["reset"])
    teardown_i, _ = R.first(RX["teardown"])
    cfg_i, cfg_m = R.first(RX["config"])
    cfg = kvs(cfg_m, 1) if cfg_m else None
    guard_i, guard_m = R.first(RX["guard"])
    # §15.5 B7: a watch= line (memcanary-w, J6) is never one of the canary checks, so every rule
    # below that reads cans (B2's six_verify_* included) is unchanged by one.
    watches = [(i, m) for i, m in R.all(RX["canary"]) if WATCH_ANY_RE.match(m.group(0))]
    cans = [(i, m) for i, m in R.all(RX["canary"]) if not WATCH_ANY_RE.match(m.group(0))]

    def verify_of(m):
        return kvs(m, 2).get("verify")

    # --- L0 (board). Under --entry uefi the loader's lines come first and are read from the counted GO on
    # (§15.13.7: text before it is unconstrained); under kexec l0_after is None and nothing changes.
    j7a = j7a_loader(recs) if uefi else None
    l0_after = j7a["go_i"] if uefi else None
    rung = None
    if board:
        miss["L0"] = []
        pos = l0_after
        i, _ = R.first(RX["shim"], after=l0_after)
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
            need("L0", R.first(rx, after=l0_after, before=reset_i)[0] is None, "neg_" + name)

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
        need("profile", R.first(RX["asinfo"])[0] is None and not cans and not watches, "tcg_asinfo_or_canary")
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
            # C3: the exit code is recorded (dryrun_rc=) and, since T1 attempt 1, must be 0 (§14.9).
            drc = to_int(dk.get("rc"))
            need("L2", drc is not None, "dryrun_rc")
            need("L2", drc is None or drc == 0, "dryrun_rc_not_0")
            need("L2", dk.get("saved") == "yes", "dryrun_saved")
            need("L2", dk.get("logger_errors") == "0", "dryrun_logger_errors")
            bq = R.all(RX["bwait_qvm"], before=di)
            need("L2", bool(bq), "dryrun_bwait_line")
            need("L2", bool(bq) and bq[-1][1].group(3) == "0", "dryrun_within_bound")
        put("dryrun_rc", q(dk["rc"]) if dm and dk.get("rc") else "absent")
        # qvm's own text: a configuration diagnostic fails the dryrun whatever rc says (§14.9).
        qlog = next((b for b in blocks if b["name"] == "qvmlog" and b["status"] == "ok"), None) or \
            next((b for b in blocks if b["name"] == "qvmlog"), None)
        need("L2", qlog is not None, "qvmlog_export")
        ndiag = None
        if qlog is not None:
            need("L2", qlog["status"] == "ok", "qvmlog_export_" + qlog["status"])
            if qlog["status"] == "ok":
                ndiag = qvm_diagnostics(qlog["data"])
                need("L2", ndiag == 0, "dryrun_qvm_diagnostics")
        put("qvmlog_diagnostics", ndiag if ndiag is not None else "not-decoded")
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
            # T3's dryrun rule is C3's as tightened after T1 attempt 1 (§14.9), not saved=yes alone.
            for x in miss.get("L2", []):
                if x in DRYRUN_ACCEPT or x.startswith("qvmlog_export"):
                    need("t3", False, x)
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
    if board and uefi:
        # §15.13.7 item 5 under UEFI entry: the loader's sha256 stands where the kexec tree's did
        if not HEX64_RE.match((loader_sha256 or "").lower()):
            missing.append("loader_sha256")
    elif board and not HEX64_RE.match((kexec_tree_sha256 or "").lower()):
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
        if uefi:
            # §15.13.7 item 5: entry, the loader's sha256 and the tree stamp (its figure stays in this private file)
            put("entry", "uefi")
            put("loader_sha256", loader_sha256.lower() if loader_sha256 and "loader_sha256" not in missing
                else "missing")
            put("fdt_crc32", j7a["crc32"] or "absent")
        else:
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
    if (profile, mode) == ("tcg", "dryrun") and diag is None:
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
    if mode == "host" and diag is None:
        put("b2", "pass" if comp_ok(("L0", "L1", "b2", "L7", "canaries_all_ok")) else "fail")
    if refused:
        put("item5", "refused missing=" + ",".join(missing))
    else:
        put("item5", "ok" if not miss["item5"] else "bad " + ",".join(miss["item5"]))
    if diag == "j1" and not board:
        # §15.5 B8.5: T-J1, the TCG j1 variant's dryrun and memcanary-w's self-test; never pass.
        # memcanary-w prints its watcher line, then memcanary's own line, which counts both sets of checks:
        # ok needs the watcher's PASS and, as the next such line after it, a PASS with a larger count
        sl = R.all(CW_SELFTEST_RE)
        cw_self = ("absent" if not sl else "multiple" if len(sl) > 1 else
                   "failed" if sl[0][1].group(1) is None or int(sl[0][1].group(1)) == 0 else "ok")
        if cw_self == "ok":
            nxt = [m for i, m in R.all(MC_SELFTEST_RE) if i > sl[0][0]]
            cw_self = ("unpaired" if not nxt else "ok" if nxt[0].group(1) is not None and
                       int(nxt[0].group(1)) > int(sl[0][1].group(1)) else "failed")
        put("cw_selftest", cw_self)
        mcw = (cfg or {}).get("memcanary_w_sha256", "").lower()
        put("memcanary_w_sha256", mcw if HEX64_RE.match(mcw) else "absent")
        want = [(n, n in miss and not miss[n]) for n in ITEM1_T1_NEEDS]
        want += [("item5", not refused and not miss["item5"]), ("memcanary_w_sha256", bool(HEX64_RE.match(mcw))),
                 ("cw_selftest", cw_self == "ok")]
        dfailed = [k for k, ok_ in want if not ok_]
        step = J1_STEPS[(profile, mode)][None]
        verdict = "diagnostic " + ("incomplete" if dfailed else "complete")
        put("step", step)
        put("verdict", verdict + ("" if not dfailed else " failed=" + ",".join(dfailed)))
        return {"lines": out, "blocks": blocks, "verdict": verdict, "refused": refused, "step": step}
    if diag == "j1":
        # §15.4.8 J6: s1-j1's records, read without any canary or watch value; never pass, never b2=.
        labs, stray = cw_watches(R)
        widx = [i for L in labs.values() for i in L["idx"]] + stray
        holds = R.all(RX["alloc_hold"])
        hidx = [i for i, _ in holds]
        hold, fill_i, verify_i, hold_bad = j1_hold(holds, hold_mib)
        # The checks: start before the first watch or hold line, end after the hold's verify line
        # (or after the last watch or hold line when there is none, so F39 stays readable).
        start_before = min(widx + hidx) if widx or hidx else None
        end_after = verify_i if verify_i is not None else (max(widx + hidx) if widx or hidx else None)
        checks = {}
        for c in CANARIES:
            mine = [(i, m) for i, m in cans if m.group(1) == c]
            for k in ("start", "end"):
                part = [] if start_before is None else [m for i, m in mine
                                                        if (i < start_before if k == "start" else i > end_after)]
                v = verify_of(part[0]) if len(part) == 1 else None
                checks[f"{c}_{k}"] = ("unsplit" if start_before is None else "absent" if not part else
                                      "multiple" if len(part) > 1 else v if v in ("ok", "bad") else "unread")
        between = 0 if start_before is None else sum(1 for i, _ in cans if start_before <= i <= end_after)
        order = "unread"
        if fill_i is not None and verify_i is not None and all(labs[l]["idx"] for l in WATCH_LABELS):
            lo = {l: min(labs[l]["idx"]) for l in WATCH_LABELS}
            hi = {l: max(labs[l]["idx"]) for l in WATCH_LABELS}
            order = "ok" if (hi["a"] < lo["b"] and hi["b"] < fill_i < lo["c"] and hi["c"] < lo["d"] and
                             hi["d"] < verify_i) else "bad"
        b2_alloc = "present" if R.first(RX["alloc"])[0] is not None else "none"
        hold_mibs = {int(m.group(1)) for _, m in holds}
        cw = cw_analyze(labs, cw_bins_from_blocks(blocks), fill_factor, kpf_paths, entry=entry)
        l1_records = [x for x in miss["L1"] if not x.startswith("canary_start_")]
        put("L1_records", "ok" if not l1_records else "missing " + ",".join(l1_records))
        for k in CANARY_CHECKS:
            put(k, checks[k])
        put("canary_between", between)
        put("hold", hold)
        put("hold_mib_vs_pc", "not_given" if hold_mib is None else "absent" if not hold_mibs else
            "match" if hold_mibs == {hold_mib} else "differs")
        put("b2_alloc_line", b2_alloc)
        put("rung_j1", "yes" if rung == J1_RUNG else "no")
        # The watcher binary that ran: the generator's EXTRA_FIELDS stamp for diag j1 (not an item-5 field).
        mcw = (cfg or {}).get("memcanary_w_sha256", "").lower()
        put("memcanary_w_sha256", mcw if HEX64_RE.match(mcw) else "absent")
        put("watch_stray", len(stray))
        for l, L in labs.items():
            put(f"watch_{l}", q(L["status"] + (" problems=" + ",".join(L["problems"]) if L["problems"] else "")))
        put("watch_order", order)
        for l in WATCH_LABELS:
            put(f"export_j1{l}", q(cw["export"][l]))
        put("kpf", q(cw["kpf"]))
        put("fillrate", q(" ".join(cw["fill"])))
        put("coincide", q(" ".join(cw["coincide"])))
        if uefi:
            # §15.13.7: no kexec markers apply; no s1wq: marker may appear anywhere in the segment
            markers = "present" if R.first(WQ_MARK_RE)[0] is not None else "none"
            put("wq_kexec_issuing", "n/a-uefi")
            put("wq_reset_marker", "n/a-uefi")
            put("wq_markers", markers)
            put("m5l_counted_go", "one" if j7a["counted"] == 1 else "none" if not j7a["counted"] else "multiple")
            for n, met in j7a["checks"].items():
                put(f"m5l_{n}", "ok" if met else "missing")
            put("m5l_neg_after_go", ",".join(j7a["neg"]) or "none")
            rc2, rbase = j7a_resmem_summary(j7a["resmem"])
            put("resmem_c2", q(rc2))
            put("resmem_c2_base", rbase)
            # P2 and P6's facts for canwatch's profile (§15.13.10.3), from c2's two checks
            c2kv = {}
            for k in ("start", "end"):
                part = [] if start_before is None else [m for i, m in cans if m.group(1) == "c2" and
                                                        (i < start_before if k == "start" else i > end_after)]
                c2kv[k] = kvs(part[0], 2) if len(part) == 1 else {}
            fo = c2kv["start"].get("first_off")
            # none: the start check verified, so no first mismatch exists there (P2 then differs)
            fo_ok = bool(re.match(r"^0x[0-9a-fA-F]{1,16}$", fo or ""))    # memcanary prints first_off in hex
            put("c2_start_anchor", "none" if checks["c2_start"] == "ok" else
                "n/a" if checks["c2_start"] != "bad" or not fo_ok else
                "first-word" if int(fo, 16) == 0 else "other")
            words = {k: (0 if checks[f"c2_{k}"] == "ok" else to_int(c2kv[k].get("words"))
                         if checks[f"c2_{k}"] == "bad" else None) for k in ("start", "end")}
            put("c2_check_words", "n/a" if None in words.values() else f"start:{words['start']},end:{words['end']}")
        else:
            shim_i = R.first(RX["shim"])[0]
            issuing = "yes" if R.first(WQ_ISSUING_RE, before=shim_i)[0] is not None else "no"
            reset_marker = "yes" if R.first(WQ_RESET_RE)[0] is not None else "no"
            put("wq_kexec_issuing", issuing)
            put("wq_reset_marker", reset_marker)
        want = [("conf_gate", not miss["conf_gate"]), ("L0", not miss["L0"]), ("L1_records", not l1_records),
                ("L7", not miss["L7"]), ("item5", not refused and not miss["item5"]), ("rung_j1", rung == J1_RUNG),
                ("memcanary_w_sha256", bool(HEX64_RE.match(mcw))), ("b2_alloc_line", b2_alloc == "none")]
        want += [(k, checks[k] in ("ok", "bad")) for k in CANARY_CHECKS]
        want += [("canary_between", between == 0), ("hold", hold in ("ok", "bad")), ("watch_stray", not stray)]
        want += [(f"watch_{l}", labs[l]["status"] == "ok") for l in WATCH_LABELS]
        want.append(("watch_order", order == "ok"))
        want += [(f"export_j1{l}", cw["export"][l] == "ok") for l in WATCH_LABELS]
        if uefi:
            want.append(("wq_markers", markers == "none"))
            want.append(("m5l_counted_go", j7a["counted"] == 1))
            want += [(f"m5l_{n}", met) for n, met in j7a["checks"].items()]
        else:
            want += [("wq_kexec_issuing", issuing == "yes"), ("wq_reset_marker", reset_marker == "no")]
        dfailed = [k for k, ok_ in want if not ok_]
        rows, sums = j6_rows(checks, labs, hold_bad, not dfailed, cw, entry=entry)
        if sums is not None:
            dom = j6_dom_counts(sums)
            top = max(dom.values())
            put("c2_sums", " ".join(f"{k}={v}" for k, v in sums.items()) + " dominant=" +
                (",".join(k for k in DOM_CLASSES if dom[k] == top) if top else "none"))
        row = ",".join(rows)
        step = J1_STEPS[(profile, mode)][arm]
        verdict = "diagnostic " + ("incomplete" if dfailed else "complete")
        put("j_row", row)
        res = {"lines": out, "blocks": blocks, "verdict": verdict, "refused": refused, "step": step, "j_row": row}
        if uefi:
            # §15.13.10.1-2: the run's reading; F62 is a reset that is not MAINSWRST after procnto up and
            # before the image's reset line. Never pass, never b2=.
            f62 = (rung is not None and reset_m is None and reset_reason is not None and
                   "MAINSWRST" not in reset_reason)
            filled_c2 = R.first(CANARY_FILL_RE["c2"], after=l0_after)[0] is not None
            jr = j7a_rows(checks, labs, hold, hold_bad, not dfailed, filled_c2, f62)
            put("j7a_c2", jr["c2"])
            put("j7a_c3", jr["c3"])
            put("j7a", ",".join(jr["rows"]))
            put("j7a_class", jr["class"])
            put("j7a_stop", ",".join(jr["stop"]) or "none")
            res["j7a"] = ",".join(jr["rows"])
            res["j7a_class"] = jr["class"]
        put("step", step)
        put("verdict", verdict + ("" if not dfailed else " failed=" + ",".join(dfailed)))
        return res
    if diag is not None:
        # §15.5 A3: B2's records, read without their canary values; never pass, never b2=.
        checks = {}
        for c in CANARIES:
            mine = [(i, m) for i, m in cans if m.group(1) == c]
            for k in ("start", "end"):
                part = [m for i, m in mine if act_i is not None and (i < act_i if k == "start" else i > act_i)]
                v = verify_of(part[0]) if len(part) == 1 else None
                checks[f"{c}_{k}"] = ("unsplit" if act_i is None else "absent" if not part else
                                      "multiple" if len(part) > 1 else v if v in ("ok", "bad") else "unread")
        allocs = [kvs(m, 2) for _, m in R.all(RX["alloc"]) if int(m.group(1)) == B2_ALLOC_MIB]
        ad = allocs[0] if len(allocs) == 1 else {}
        alloc = ("absent" if not allocs else "multiple" if len(allocs) > 1 else "map-fail" if ad.get("map") == "fail"
                 else ad["verify"] if ad.get("fill") == "ok" and ad.get("verify") in ("ok", "bad") else "unread")
        l1_records = [x for x in miss["L1"] if not x.startswith("canary_start_")]
        want = [("conf_gate", not miss["conf_gate"]), ("L0", not miss["L0"]), ("L1_records", not l1_records),
                ("L7", not miss["L7"]), ("item5", not refused and not miss["item5"])]
        want += [(k, checks[k] in ("ok", "bad")) for k in CANARY_CHECKS]
        want.append(("alloc", alloc in ("ok", "bad")))
        put("L1_records", "ok" if not l1_records else "missing " + ",".join(l1_records))
        for k in CANARY_CHECKS:
            put(k, checks[k])
        put("alloc", alloc)
        if diag in ("j2", "j4"):
            shim_i = R.first(RX["shim"])[0]
            issuing = "yes" if R.first(WQ_ISSUING_RE, before=shim_i)[0] is not None else "no"
            reset_marker = "yes" if R.first(WQ_RESET_RE)[0] is not None else "no"
            put("wq_kexec_issuing", issuing)
            put("wq_reset_marker", reset_marker)
            want += [("wq_kexec_issuing", issuing == "yes"), ("wq_reset_marker", reset_marker == "no")]
        else:
            markers = "present" if R.first(WQ_MARK_RE)[0] is not None else "none"
            put("wq_markers", markers)
            want.append(("wq_markers", markers == "none"))
        dfailed = [k for k, ok_ in want if not ok_]
        row = diag_row(diag, checks, not dfailed)
        step = DIAG_STEPS[diag]
        verdict = "diagnostic " + ("incomplete" if dfailed else "complete")
        put("j_row", row)
        put("step", step)
        put("verdict", verdict + ("" if not dfailed else " failed=" + ",".join(dfailed)))
        return {"lines": out, "blocks": blocks, "verdict": verdict, "refused": refused, "step": step, "j_row": row}
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
               pins=(), diag=None, j1=None):
    head = [f"parser={rel_repo(__file__)} sha256={sha256(open(__file__, 'rb').read())}",
            f"kshcheck_impl={rel_repo(PARSE_M4_PATH)} sha256={sha256(open(PARSE_M4_PATH, 'rb').read())}",
            f"input_log={rel_repo(a_log)} sha256={sha256(data)} bytes={len(data)}",
            (f"input_blackbox={rel_repo(a_blackbox)} sha256={sha256(bb_data)}" if bb_data is not None
             else "input_blackbox=none"),
            f"input_conf={rel_repo(conf_path)} sha256={sha256(conf_bytes)}",
            f"input_allow sha256={sha256(allow_bytes)}"]
    head += [f"input_{key}={rel_repo(p)} sha256={sha256(b)}" if b is not None else f"input_{key}=none"
             for key, p, b in pins]
    if j1:
        # §15.5 B7: J6's pre-registered inputs, stamped with the record they produced.
        head.append(f"fill_factor={j1['fill_factor']}")
        head.append(f"hold_mib={j1['hold_mib'] if j1['hold_mib'] is not None else 'not_given'}")
        head += [f"input_kpf={rel_repo(p)} " + (f"sha256={sha256(PM.read_bytes(p))}" if os.path.isfile(p) else "absent")
                 for p in j1["kpf"]] or ["input_kpf=none"]
    head.append(f"profile={profile} mode={mode}" + (f" diag={diag}" if diag is not None else "") +
                (f" arm={j1['arm']}" if j1 else "") + (" entry=uefi" if j1 and j1.get("entry") == "uefi" else ""))
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
    diag = getattr(a, "diag", None)
    arm = getattr(a, "arm", None)
    fill_factor = getattr(a, "fill_factor", None)
    hold_mib = getattr(a, "hold_mib", None)
    kpf = list(getattr(a, "kpf", None) or [])
    j1_opts = arm is not None or fill_factor is not None or hold_mib is not None or bool(kpf)
    entry = getattr(a, "entry", None) or "kexec"
    loader_sha256 = getattr(a, "loader_sha256", None)
    if entry == "uefi":
        if diag != "j1" or (a.profile, a.mode) != ("board", "host") or arm != J7A_ARM:
            print("parse-s1: usage: --entry uefi reads J7a's segment: --diag j1 --arm uefi --profile board "
                  "--mode host (s1-design.md 15.13.7)", file=sys.stderr)
            return 2
        if not HEX64_RE.match(loader_sha256 or ""):
            print("parse-s1: usage: --entry uefi needs --loader-sha256, the staged loader's sha256 in 64 lowercase "
                  "hex digits (s1-design.md 15.13.7)", file=sys.stderr)
            return 2
        if kpf or getattr(a, "kexec_tree_sha256", None):
            print("parse-s1: usage: --entry uefi takes no --kpf and no --kexec-tree-sha256: no Linux ran in the "
                  "entered power cycle (s1-design.md 15.13.7)", file=sys.stderr)
            return 2
    elif arm == J7A_ARM or loader_sha256 is not None:
        print("parse-s1: usage: --arm uefi and --loader-sha256 need --entry uefi (s1-design.md 15.13.7)",
              file=sys.stderr)
        return 2
    if diag in DIAG_STEPS and (a.profile, a.mode) != ("board", "host"):
        print("parse-s1: usage: --diag j2|j2b|j4 reads B2's image: --profile board --mode host "
              "(s1-design.md 15.5 A3)", file=sys.stderr)
        return 2
    if diag == "j1":
        if (a.profile, a.mode) not in J1_STEPS:
            print("parse-s1: usage: --diag j1 reads J6's log (--profile board --mode host) or T-J1's "
                  "(--profile tcg --mode dryrun) (s1-design.md 15.5 B7)", file=sys.stderr)
            return 2
        if a.profile == "tcg" and j1_opts:
            print("parse-s1: usage: T-J1 takes no --arm, --fill-factor, --hold-mib or --kpf", file=sys.stderr)
            return 2
        if a.profile == "board":
            try:
                cw_factor(fill_factor)
            except InputError as e:
                print(out_line(f"parse-s1: usage: --diag j1 needs the pre-registered --fill-factor: {e}"),
                      file=sys.stderr)
                return 2
            if arm not in (J1_ARMS if entry == "kexec" else (J7A_ARM,)) or len(kpf) > 2:
                print("parse-s1: usage: --diag j1 needs --arm control|remove, and takes at most two --kpf "
                      "headers (s1-design.md 15.4.8)", file=sys.stderr)
                return 2
    elif j1_opts:
        print("parse-s1: usage: --arm, --fill-factor, --hold-mib and --kpf belong to --diag j1", file=sys.stderr)
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
                      pc_initrd=pc_initrd, diag=diag, arm=arm, fill_factor=fill_factor, hold_mib=hold_mib,
                      kpf_paths=kpf, entry=entry, loader_sha256=loader_sha256)
    j1 = ({"arm": arm, "fill_factor": fill_factor, "hold_mib": hold_mib, "kpf": kpf, "entry": entry}
          if diag == "j1" and a.profile == "board" else None)
    text = run_report(a.log, data, bb_data, a.blackbox, conf_path, conf_bytes, allow_bytes, res, a.profile, a.mode,
                      pins=(("image", a.image, pc_image), ("initrd", a.initrd, pc_initrd)), diag=diag, j1=j1)
    out_dir = None if a.out_dir == "none" else (a.out_dir or os.path.dirname(os.path.abspath(a.log)))
    if out_dir is not None:
        for p in write_run_outputs(out_dir, res, text):
            text += out_line(f"S1PC wrote={rel_repo(p)}") + "\n"
    sys.stdout.write(text)
    return 3 if res["refused"] else 0


# ------------------------------------------------------------------ canwatch: the J6 watcher (§15.4.8, §15.5 B7)

_KPF = None


def _kpf():
    """kpf-decode.py as a module, loaded on first use: its snapshot checks and classes, not a copy."""
    global _KPF
    if _KPF is None:
        path = os.path.join(HERE, "kpf-decode.py")
        spec = importlib.util.spec_from_file_location("kpf_decode", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _KPF = mod
    return _KPF


def cw_factor(v):
    """The pre-registered fill-rate factor as an exact Fraction: a decimal of at least 1. InputError otherwise."""
    if isinstance(v, Fraction):
        f = v
    elif v is None or not FACTOR_RE.match(str(v)):
        raise InputError(f"fill factor {v!r} is not a decimal such as 2 or 1.5")
    else:
        f = Fraction(str(v))
    if f < 1:
        raise InputError(f"fill factor {v} is below 1")
    return f


def _ftext(f):
    return str(f.numerator) if f.denominator == 1 else f"{float(f):g}"


def _pop(mask):
    return bin(mask).count("1")


def _bits(mask):
    """The set bit positions of mask, lowest first (page numbers of a bitmap)."""
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def cw_time_ok(snaps, changed_snaps, changed_words, healed, osc, prog, stable):
    """The time counts' own relations on the console (an export's tail carries only changed_words and healed).

    memcanary.c's cw_snap counts every change event as exactly one of osc, prog and stable (A-A-C is
    prog), so their sum is changed_words; a revert is not a change and is none of them.
    """
    return (changed_snaps <= snaps and (changed_snaps == 0) == (changed_words == 0) and
            osc + prog + stable == changed_words and healed <= changed_words)


def cw_reread_ok(t, r):
    """The reread line's relations with the time line: revert_flip2 <= revert; every whole heal is 512
    heals of one page in one changing snapshot, so whole_heal x 512 <= healed and whole_heal <=
    changed_snaps x 4096."""
    return (r["revert_flip2"] <= r["revert"] and r["whole_heal"] * WWORDS <= t["healed"] and
            r["whole_heal"] <= t["changed_snaps"] * WPAGES)


def cw_console_problems(label, f):
    """Names of the relations one parsed watch breaks (the docstring's consistency table)."""
    count = WATCH_LABELS[label][2]
    b, t, r, w, w2, s, y, v = (f[k] for k in WATCH_KINDS)
    bad = w["bad"]
    p = []
    if not (b["pages"] <= min(b["bad"], WPAGES) and (b["bad"] == 0) == (b["pages"] == 0) and
            b["bad"] <= b["pages"] * WWORDS):
        p.append("base_pages")
    if b["bad"] and not (b["first_off"] % 8 == 0 and b["last_off"] % 8 == 0 and
                         b["first_off"] <= b["last_off"] < CANARY_SIZE and
                         (b["last_off"] - b["first_off"]) // 8 + 1 >= b["bad"]):
        p.append("base_offsets")
    if not (t["snaps"] <= count and (t["stop"] == "deadline" or t["snaps"] == count)):
        p.append("time_snaps")
    if not cw_time_ok(t["snaps"], t["changed_snaps"], t["changed_words"], t["healed"], t["osc"], t["prog"],
                      t["stable"]):
        p.append("time_counts")
    if not cw_reread_ok(t, r):
        p.append("reread_counts")
    if bad > WPAGES * WWORDS or sum(w[k] for k in _WORDS1) + sum(w2[k] for k in _WORDS2) != bad:
        p.append("words_sum")
    if sum(s[f"b{k}"] for k in range(8)) != bad:
        p.append("stride_sum")
    if y["ascii_bytes"] < 16 * y["ascii_runs"] or (bad == 0 and any(y.values())):
        p.append("bytes")
    if t["changed_words"] == 0:
        # memcanary.c's cw_writer: with no change in the snapshots, none or static when its final read
        # equals the last snapshot (then words' bad is base's), else ongoing (a change seen only there).
        want_writer = ("ongoing",) + (("none",) if b["bad"] == 0 and bad == 0 else
                                      ("static",) if b["bad"] > 0 and bad == b["bad"] else ())
    else:
        want_writer = ("stopped", "ongoing")
    if v["writer"] not in want_writer:
        p.append("verdict_writer")
    if (v["heal"] == "yes") != (t["healed"] > 0):
        p.append("verdict_heal")
    if v["reads"] != ("prog" if t["prog"] else "osc" if t["osc"] else "revert" if r["revert"] else "stable"):
        p.append("verdict_reads")
    toks = v["content"].split(",")
    if bad == 0:
        content_ok = toks == ["none"]
    else:
        content_ok = toks == ["unclassified"] or all(x in CONTENT_WORDS for x in toks)
    if not content_ok:
        p.append("verdict_content")
    return p


def cw_watches(R):
    """(labels, stray) of a log's watch lines.

    labels maps a, b, c and d to a dict: idx (every line's index), lines (kind ->
    [(index, canary, {field: text})]), status (the docstring's), problems, and f (kind ->
    {field: int or text}, offsets read from hex) when the seven success lines were read
    once each, on the table canary, in order. stray: indexes of watch lines whose label is
    missing or outside the table.
    """
    labs = {l: {"idx": [], "lines": {}, "malformed": 0, "f": None, "problems": []} for l in WATCH_LABELS}
    stray = []
    for i, t in R.r:
        m = WATCH_ANY_RE.match(t)
        if not m:
            continue
        L = labs.get(m.group(3))
        if L is None:
            stray.append(i)
            continue
        L["idx"].append(i)
        rx = WATCH_RE.get(m.group(2))
        mm = rx.match(t) if rx is not None and len(t) <= WATCH_LINE_MAX else None
        if mm is None:
            L["malformed"] += 1
            continue
        fields = {name: mm.group(3 + k) for k, (name, _) in enumerate(WATCH_FIELDS[m.group(2)])}
        L["lines"].setdefault(m.group(2), []).append((i, mm.group(1), fields))
    for l, L in labs.items():
        ls = L["lines"]
        if not L["idx"]:
            st = "absent"
        elif "fail" in ls:
            st = "fail"
        elif L["malformed"]:
            st = "malformed"
        elif any(len(v) > 1 for v in ls.values()):
            st = "multiple"
        elif any(k not in ls for k in WATCH_KINDS):
            st = "incomplete"
        elif any(v[0][1] != WATCH_LABELS[l][0] for v in ls.values()):
            st = "wrong-canary"
        elif [ls[k][0][0] for k in WATCH_KINDS] != sorted(ls[k][0][0] for k in WATCH_KINDS):
            st = "order"
        else:
            L["f"] = {k: {n: int(x, 16) if x.startswith("0x") else int(x) if x.isdigit() else x
                          for n, x in ls[k][0][2].items()} for k in WATCH_KINDS}
            L["problems"] = cw_console_problems(l, L["f"])
            st = "inconsistent" if L["problems"] else "ok"
        L["status"] = st
    return labs, stray


def cw_decode(data, label):
    """(facts, reason, detail) of one watch export s1-j1<label>.bin; reason None when its structure holds.

    The checks run in the docstring's order and the first failing one names the refusal.
    facts: name, label, snaps, interval, maps (bitmap name -> int, bit p = page p) and tail.
    """
    name, interval, count = WATCH_LABELS[label]
    if len(data) < CW_HEAD.size + CW_TAIL.size:
        return None, "short", f"bytes={len(data)}"
    (magic, version, rname, rlabel, base, pages, ival, snaps, rcount, rsecs, stop,
     zero) = CW_HEAD.unpack_from(data, 0)
    if magic != CW_MAGIC:
        return None, "magic", ""
    if version != CW_VERSION:
        return None, "version", f"version={version}"
    if pages != WPAGES:
        return None, "page-count", f"pages={pages}"
    if len(data) != CW_SIZE:
        return None, "size", f"bytes={len(data)} want={CW_SIZE}"
    nm, lb = rname.rstrip(b"\0"), rlabel.rstrip(b"\0")
    if b"\0" in nm or nm != name.encode("ascii"):
        return None, "name", ""
    if b"\0" in lb or lb != label.encode("ascii"):
        return None, "label", ""
    if base != CANARIES[name]:
        return None, "base", ""
    if zero != bytes(len(zero)):
        return None, "reserved", ""
    if ival != interval:
        return None, "interval", f"interval={ival}"
    if rcount != count or rsecs != WATCH_DEADLINE_S[label] or stop not in CW_STOPS:
        return None, "request", f"count={rcount} deadline_s={rsecs} stop={stop}"
    if snaps > count:
        return None, "snaps", f"snaps={snaps}"
    off = CW_HEAD.size
    maps = {}
    for m in CW_MAPS:
        maps[m] = int.from_bytes(data[off:off + CW_MAP_BYTES], "little")
        off += CW_MAP_BYTES
    tail = dict(zip(CW_TAIL_FIELDS, CW_TAIL.unpack_from(data, off)))
    pops = {m: _pop(v) for m, v in maps.items()}
    broken = []
    if tail["healed"] > tail["changed_words"] or (CW_STOPS[stop] == "count" and snaps != count):
        broken.append("time")
    if max(tail["bad_base"], tail["bad_final"]) > WPAGES * WWORDS:
        broken.append("bad")
    for m, n in (("bad_final", tail["bad_final"]), ("changed_ever", tail["changed_words"]),
                 ("healed_ever", tail["healed"])):
        if (pops[m] == 0) != (n == 0) or pops[m] > n:
            broken.append(m)
    if tail["bad_final"] > pops["bad_final"] * WWORDS:
        broken.append("bad_final_pages")
    if broken:
        return None, "counts", "broken=" + ",".join(broken)
    if maps["healed_ever"] & ~maps["changed_ever"]:
        return None, "healed-not-changed", ""
    return {"name": name, "label": label, "snaps": snaps, "interval": ival, "stop": CW_STOPS[stop], "maps": maps,
            "tail": tail}, None, ""


def cw_cross(fx, f):
    """The fields of an accepted export that differ from its parsed console watch."""
    t = f["time"]
    want = {"snaps": t["snaps"], "stop": t["stop"], "bad_base": f["base"]["bad"], "bad_final": f["words"]["bad"],
            "changed_words": t["changed_words"], "healed": t["healed"]}
    got = dict(fx["tail"], snaps=fx["snaps"], stop=fx["stop"])
    return [k for k in want if got[k] != want[k]]


def cw_bins_from_blocks(blocks):
    """label -> a decoded j1<label> export's bytes, or its status text (absent when LOG has no block)."""
    out = {}
    for l in WATCH_LABELS:
        blk = next((b for b in blocks if b["name"] == f"j1{l}"), None)
        out[l] = "absent" if blk is None else blk["data"] if blk.get("status") == "ok" else blk.get("status", "unread")
    return out


def cw_log_records(R, blocks):
    """label -> (bytes, md5) of j1<label> from LOG's S1 BEGIN line, else its S1 EXPORT record; None if neither."""
    out = {}
    for l in WATCH_LABELS:
        name = f"j1{l}"
        kv = next((b["kv"] for b in blocks if b["name"] == name), None)
        if kv is None:
            m = next((m for _, m in R.all(EXPORT_REC_RE) if m.group(1) == name), None)
            kv = kvs(m, 2) if m else {}
        n, h = to_int(kv.get("bytes")), (kv.get("md5") or "").lower()
        out[l] = (n, h) if n is not None and HEX32_RE.match(h) else None
    return out


def cw_kpf_load(paths):
    """(status, {tag: {canary: class index per page}}) of kpf-decode.py headers.

    status is not-given, ok, input-error or 'refused reason=R' (kpf-decode's reasons, and
    its two-header rules: one tag each, one boot_id, postquiesce uptime above prequiesce).
    Only the canaries' own page frames are classified.
    """
    if not paths:
        return "not-given", {}
    K = _kpf()
    if dict(K.CANARIES) != CANARIES or K.PAGE != WPAGE or K.CANARY_SIZE != CANARY_SIZE:
        return "refused reason=constants", {}
    if len(paths) > 2:
        return "refused reason=usage", {}
    try:
        snaps = [K.load_snapshot(p) for p in paths]
        if len(snaps) == 2:
            if sorted(s["kv"]["tag"] for s in snaps) != sorted(K.TAGS):
                raise K.Refused("tag")
            if snaps[0]["kv"]["boot_id"] != snaps[1]["kv"]["boot_id"]:
                raise K.Refused("boot-id-mismatch")
            snaps.sort(key=lambda s: K.TAGS.index(s["kv"]["tag"]))
            if float(snaps[1]["kv"]["uptime_s"]) <= float(snaps[0]["kv"]["uptime_s"]):
                raise K.Refused("uptime-order")
    except K.Refused as e:
        return f"refused reason={e.reason}", {}
    except K.InputError:
        return "input-error", {}
    starts = {r[0]: r[1] for r in K.RANGES}
    out = {}
    for s in snaps:
        offs = {r[0]: r[4] for r in s["ranges"]}
        cls = {}
        for name, base in K.CANARIES:
            rname = K.CANARY_RANGE[name]
            lo = offs[rname] + (base // K.PAGE - starts[rname]) * 8
            cls[name] = K.classify_slice(s["flags"][lo:lo + WPAGES * 8], s["count"][lo:lo + WPAGES * 8])
        out[s["kv"]["tag"]] = cls
    return "ok", out


def cw_kpf_counts(K, cls, mask):
    """(per-class page counts, held, free) of a bitmap's pages under one snapshot's classes."""
    n = [0] * len(K.CLASSES)
    for p in _bits(mask):
        n[cls[p]] += 1
    free = sum(n[i] for i in K.FREE)
    return n, sum(n) - free - n[K.NOPAGE], free


def cw_fill_rate(labs, factor):
    """(result, detail) of §15.4.8's fill-rate row: differs, within or not-computed (exact arithmetic)."""
    if labs["b"]["status"] != "ok" or labs["c"]["status"] != "ok":
        return "not-computed", "reason=watch-b-or-c-not-ok"
    tb, tc = labs["b"]["f"]["time"], labs["c"]["f"]["time"]
    detail = (f"label_b=changed_words:{tb['changed_words']}/snaps:{tb['snaps']} "
              f"label_c=changed_words:{tc['changed_words']}/snaps:{tc['snaps']} factor={_ftext(factor)}")
    if not tb["snaps"] or not tc["snaps"]:
        return "not-computed", detail + " reason=no-snapshots"
    rb, rc = Fraction(tb["changed_words"], tb["snaps"]), Fraction(tc["changed_words"], tc["snaps"])
    if not (rc > factor * rb or rb > factor * rc):
        return "within", detail
    # a rate against a zero or near-zero one: differs only with FILL_MIN_WORDS change events on the larger side
    if max(tb["changed_words"], tc["changed_words"]) < FILL_MIN_WORDS:
        return "below-floor", detail + f" floor={FILL_MIN_WORDS}"
    return "differs", detail


def cw_coincide(facts, kpf):
    """(result, detail): do c2's changed or finally bad pages (watches a-c) sit on pages Linux held before the
    quiesce? A record only (R45)."""
    if "prequiesce" not in kpf:
        return "not-computed", "reason=no-prequiesce-snapshot"
    used = [l for l in WATCH_C2 if l in facts]
    if not used:
        return "not-computed", "reason=no-c2-bitmap"
    mask = 0
    for l in used:
        mask |= facts[l]["maps"]["bad_final"] | facts[l]["maps"]["changed_ever"]
    n, held, _free = cw_kpf_counts(_kpf(), kpf["prequiesce"]["c2"], mask)
    pages = sum(n)
    return (("yes" if pages and 2 * held > pages else "no"),
            f"labels={','.join(used)} pages={pages} held_prequiesce={held}")


def cw_bitmap_line(label, fx, m):
    pages = list(_bits(fx["maps"][m]))
    runs = sum(1 for k, p in enumerate(pages) if k == 0 or pages[k - 1] != p - 1)
    per = [0] * (CANARY_SIZE // MIB)
    for p in pages:
        per[p // (MIB // WPAGE)] += 1
    return (f"bitmap label={label} name={fx['name']} map={m} pages={len(pages)} "
            f"first_page={pages[0] if pages else '-'} last_page={pages[-1] if pages else '-'} runs={runs} "
            f"per_mib={','.join(str(x) for x in per)}")


def cw_analyze(labs, bins, factor, kpf_paths=(), log_recs=None, entry="kexec"):
    """The analyzer: canwatch's lines (key=value, no prefix) and the facts run --diag j1 reads.

    bins maps each label to the export's bytes, or to a status text when there are none
    (absent, truncated, mismatch(...)). log_recs, canwatch's only, maps a label to LOG's
    (bytes, md5) record or None; a file that does not match it is counted as failed.
    Returns lines, failed, facts (accepted exports), export (label -> ok or the refusal),
    kpf (status), fill and coincide ((result, detail) each). Under entry uefi (J7a) no Linux
    ran in the power cycle: kpf is not-applicable and the coincidence line is not printed.
    """
    lines = [f"limit: {CW_LIMIT}"]
    failed, facts, export = [], {}, {}
    if entry == "uefi":
        kstat, kpf = "not-applicable", {}
    else:
        kstat, kpf = cw_kpf_load(list(kpf_paths))
    for l, (name, _interval, _count) in WATCH_LABELS.items():
        L = labs[l]
        data = bins.get(l, "absent")
        extra = ""
        if isinstance(data, (bytes, bytearray)):
            data = bytes(data)
            fx, reason, detail = cw_decode(data, l)
            if reason is None:
                facts[l] = fx
                if L["f"] is None:
                    reason = "console-absent"
                else:
                    mism = cw_cross(fx, L["f"])
                    if mism:
                        reason, detail = "console-mismatch", "fields=" + ",".join(mism)
            export[l] = "ok" if reason is None else f"refused reason={reason}" + (f" {detail}" if detail else "")
            if log_recs is not None:
                rec = log_recs.get(l)
                bvl = "no-record" if rec is None else "match" if rec == (len(data), md5(data)) else "differs"
                extra = f" bin_vs_log={bvl}"
                if bvl != "match":
                    failed.append(f"bin_vs_log_j1{l}")
        else:
            export[l] = str(data)
        if L["status"] != "ok":
            failed.append(f"watch_{l}")
        if export[l] != "ok":
            failed.append(f"export_j1{l}")
        probs = f" problems={','.join(L['problems'])}" if L["problems"] else ""
        lines.append(f"watch label={l} name={name} console={L['status']}{probs} export={q(export[l])}{extra}")
    for l, fx in facts.items():
        lines += [cw_bitmap_line(l, fx, m) for m in CW_MAPS]
        hp = _pop(fx["maps"]["healed_ever"])
        whole = "n/a" if hp == 0 else "consistent" if fx["tail"]["healed"] >= WWORDS * hp else "no"
        # the row reads memcanary-w's whole_heal (a page healed in one snapshot); this event count is a record
        wh = labs[l]["f"]["reread"]["whole_heal"] if labs[l]["f"] is not None else "-"
        lines.append(f"heal label={l} healed_pages={hp} healed={fx['tail']['healed']} whole_page={whole} "
                     f"condition=necessary-only whole_heal={wh}")
    lines.append(f"kpf result={kstat}" + (f" tags={','.join(kpf)}" if kpf else ""))
    if kpf:
        K = _kpf()
        for l, fx in facts.items():
            for tag, cls in kpf.items():
                for m in CW_MAPS:
                    n, held, free = cw_kpf_counts(K, cls[fx["name"]], fx["maps"][m])
                    lines.append(f"kpf tag={tag} label={l} name={fx['name']} map={m} pages={sum(n)} held={held} "
                                 f"free={free} " + " ".join(f"{c}={n[i]}" for i, c in enumerate(K.CLASSES)))
    fill = cw_fill_rate(labs, factor)
    lines.append(f"fillrate result={fill[0]} {fill[1]}")
    if entry == "uefi":
        coincide = ("suppressed", "entry=uefi")
    else:
        coincide = cw_coincide(facts, kpf) if kpf else ("not-computed", "reason=no-kpf")
        lines.append(f"coincide result={coincide[0]} {coincide[1]} record_only=yes")
    lines.append("result=" + ("complete" if not failed else "incomplete failed=" + ",".join(failed)))
    return {"lines": lines, "failed": failed, "facts": facts, "export": export, "kpf": kstat, "fill": fill,
            "coincide": coincide}


def j1_hold(holds, hold_mib):
    """(status, fill index, verify index, bad) of J6's hold lines (memcanary.c's hold forms).

    bad is True when a verify line reads verify=bad, or verify=timeout data=bad (F49),
    whatever the status. Both lines' MIB must be J1_HOLD_MIB, and hold_mib when given.
    """
    parsed = [(i, int(m.group(1)), kvs(m, 2)) for i, m in holds]
    fills = [i for i, _, d in parsed if d.get("fill") == "ok" and "verify" not in d and "map" not in d]
    verifies = [(i, d) for i, _, d in parsed if "verify" in d]
    bad = any(d["verify"] == "bad" or (d["verify"] == "timeout" and d.get("data") == "bad") for _, d in verifies)
    fill_i = fills[0] if len(fills) == 1 else None
    verify_i = verifies[0][0] if len(verifies) == 1 else None
    mibs = {mib for _, mib, _ in parsed}
    if not parsed:
        st = "absent"
    elif any(d.get("map") == "fail" for _, _, d in parsed):
        st = "map-fail"
    elif len(fills) > 1 or len(verifies) > 1:
        st = "multiple"
    elif fill_i is None or verify_i is None:
        st = "absent"
    elif verify_i < fill_i or len(parsed) != 2:
        st = "unread"
    elif mibs != {J1_HOLD_MIB} or (hold_mib is not None and hold_mib != J1_HOLD_MIB):
        st = "mib-differs"
    else:
        d = verifies[0][1]
        st = {("ok", None): "ok", ("bad", None): "bad", ("timeout", "ok"): "timeout",
              ("timeout", "bad"): "timeout-bad"}.get((d["verify"], d.get("data")), "unread")
    return st, fill_i, verify_i, bad


def j6_sums(labs, labels):
    """The counts the J6 rows read, summed over the given (parsed) watches."""
    s = dict.fromkeys(("bad_base", "bad", "changed_words", "healed", "osc", "prog", "stable", "revert", "revert_flip2",
                       "whole_heal") + WORD_CLASSES + SIGNATURES + tuple(f"b{k}" for k in range(8)), 0)
    for l in labels:
        f = labs[l]["f"]
        s["bad_base"] += f["base"]["bad"]
        s["bad"] += f["words"]["bad"]
        for k in ("changed_words", "healed", "osc", "prog", "stable"):
            s[k] += f["time"][k]
        for k in ("revert", "revert_flip2", "whole_heal"):
            s[k] += f["reread"][k]
        for k in _WORDS1:
            s[k] += f["words"][k]
        for k in _WORDS2:
            s[k] += f["words2"][k]
        for k in SIGNATURES:
            s[k] += f["bytes"][k]
        for k in range(8):
            s[f"b{k}"] += f["stride"][f"b{k}"]
    return s


def j6_dom_counts(s):
    d = {k: s[k] for k in DOM_CLASSES if k != "flip2"}
    d["flip2"] = s["flip2_same"] + s["flip2_var"]
    return d


def j6_dominant(d, group):
    """The group's largest class count is above 0 and no class outside the group is larger."""
    top = max(d[k] for k in group)
    return top > 0 and all(v <= top for k, v in d.items() if k not in group)


def c1_watch_bad_of(labs):
    """A c1 watch line (base or words, parsed or not) with bad above 0."""
    return any(int(fields["bad"]) > 0 for L in labs.values() for kind in ("base", "words")
               for _i, canary, fields in L["lines"].get(kind, ()) if canary == "c1")


def j7a_rows(checks, labs, hold, hold_bad, complete, filled_c2, f62):
    """§15.13.10.1-2's reading of one counted J7a run. Returns rows (J7A_ROWS, reading first, then F39c1,
    F39c3, F49, F62), c2 (clean|bad|revert-only|unsettled|bad-partial|unread), c3 (clean|hit|unread),
    class (per run: K-w, K-r(u), E-candidate, none, unsettled, U) and stop (the immediate stops).

    complete: bad when c2 is bad at either check, a c2 watch's base bad is above 0, or a c2 change event
    had stable re-reads; else revert-only on a revert or an oscillation; else clean with both checks ok
    and writer=none on every c2 watch. Anything else (prog or a FINL-only change with no stable re-read,
    revert or oscillation) is 'unsettled': §15.13.10.1 names no state for it, so it is left to the owner.
    Not complete: bad-partial when c2's filled line was printed and a parse-valid check reads c2 bad.
    bad or bad-partial with F34 on c2's parsed watches is bad-unstable.
    """
    parsed = [l for l in WATCH_C2 if labs[l]["f"] is not None]
    s = j6_sums(labs, parsed)
    f34 = bool(parsed) and c2_f34(s)
    c2_checks = (checks["c2_start"], checks["c2_end"])
    c1_bad = c1_watch_bad_of(labs) or "bad" in (checks["c1_start"], checks["c1_end"])
    c3_checks = (checks["c3_start"], checks["c3_end"])
    c3 = "hit" if "bad" in c3_checks else "clean" if c3_checks == ("ok", "ok") else "unread"
    rows = []
    if complete:
        fs = [labs[l]["f"] for l in WATCH_C2]
        if "bad" in c2_checks or any(f["base"]["bad"] > 0 for f in fs) or s["stable"] > 0:
            c2 = "bad"
            rows.append("bad-unstable" if f34 else "bad")
        elif s["revert"] > 0 or s["osc"] > 0:
            c2 = "revert-only"
            rows.append("revert-only")
        elif c2_checks == ("ok", "ok") and all(f["verdict"]["writer"] == "none" for f in fs):
            c2 = "clean"
            if not c1_bad and hold == "ok" and not f62:
                rows.append("clean")
        else:
            c2 = "unsettled"
            rows.append("unsettled")
    else:
        c2 = "bad-partial" if filled_c2 and "bad" in c2_checks else "unread"
        if c2 == "bad-partial":
            rows.append("bad-unstable" if f34 else "bad-partial")
        rows.append("incomplete")
    if c1_bad:
        rows.append("F39c1")
    if c3 == "hit":
        rows.append("F39c3")
    if hold_bad:
        rows.append("F49")
    if f62:
        rows.append("F62")
    if "bad-unstable" in rows:
        cls = "K-r(u)"
    elif "bad" in rows or "bad-partial" in rows:
        cls = "K-w"
    elif "clean" in rows:
        cls = "E-candidate"
    elif "unsettled" in rows:
        cls = "unsettled"
    elif "revert-only" in rows:
        cls = "none"
    else:
        cls = "U"
    return {"rows": rows, "c2": c2, "c3": c3, "class": cls, "stop": [x for x in ("F39c1", "F49") if x in rows],
            "f34": f34}


def j6_rows(checks, labs, hold_bad, complete, cw, entry="kexec"):
    """(rows, c2 sums or None): every row of §15.4.8's table that holds, stops first (docstring).

    Under entry uefi (J7a) no Linux ran in the power cycle, so the Linux-page-coincidence rows
    (cpu-side, cpu-side-lean) are suppressed (s1-design.md §15.13.7 P7)."""
    rows = []
    c1_watch_bad = c1_watch_bad_of(labs)
    if c1_watch_bad or any(checks[f"{c}_{k}"] == "bad" for c in ("c1", "c3") for k in ("start", "end")):
        rows.append("F39")
    if hold_bad:
        rows.append("F49")
    if not complete:
        return rows + ["F40"], None
    s = j6_sums(labs, WATCH_C2)
    d = j6_dom_counts(s)
    bad = s["bad"]
    # F34 (s1-design §15.12): no read in progress; some read that did not hold (osc or a revert); flip2
    # dominant in FINL's bad set when it has words; and most reverts 1-2 bit flips when there are any
    f34 = c2_f34(s)
    if f34:
        rows.append("F34")
    # F34 takes precedence over live-writer's stable arm: an osc keeps a marginal read as the last read,
    # and the next snapshot re-reads the stored word as a stable change (HYPOTHESIS, beside R71). A
    # prog above 0 excludes F34, so the two rows never print together.
    if s["prog"] > 0 or (s["changed_words"] > 0 and s["stable"] > 0 and not f34):
        rows.append("live-writer")
    # whole pages healed together: memcanary-w's whole_heal, a page whose every word healed in one snapshot
    if (s["healed"] > 0 and j6_dominant(d, LEAN_RESTORING)) or s["whole_heal"] > 0:
        rows.append("restoring-writer")
    top2 = sum(sorted(s[f"b{k}"] for k in range(8))[-2:])
    if j6_dominant(d, LEAN_RING) or (bad >= STRIDE_MIN_BAD and 2 * top2 > bad):
        rows.append("ring-record")
    if j6_dominant(d, LEAN_CPU):
        if cw["coincide"][0] == "yes":
            rows.append("cpu-side")
        elif cw["coincide"][0] == "not-computed":
            rows.append("cpu-side-lean")
    if j6_dominant(d, LEAN_QNX):
        rows.append("qnx-shaped")
    if sum(labs[l]["f"]["bytes"][k] for l in WATCH_LABELS for k in SIGNATURES) > 0:
        rows.append("positive-signature")
    if cw["fill"][0] == "differs":
        rows.append("fill-rate")
    writers = {labs[l]["f"]["verdict"]["writer"] for l in WATCH_C2}
    # writer-none is "c2 clean at every scan" (§15.4.8), so a read that did not hold (a revert) rules it out
    if writers == {"none"}:
        if s["revert"] == 0:
            rows.append("writer-none")
    elif not writers & {"stopped", "ongoing"}:
        rows.append("writer-static")
    return rows or ["no-row"], s


def write_canwatch(out_dir, text, check=True):
    """canwatch.txt into out_dir, its path checked first (parse-m4.py's check_out_path when check is True)."""
    checker = PM.check_out_path if check is True else (check or (lambda p: None))
    p = os.path.join(out_dir, "canwatch.txt")
    checker(p)
    os.makedirs(out_dir, exist_ok=True)
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))
    return p


def parse_fields(data):
    """The S1PC key=value lines of a parse-s1.txt (bytes) as a dict, the last line of each key."""
    out = {}
    for ln in data.decode("utf-8", "replace").replace("\r", "").split("\n"):
        if ln.startswith("S1PC ") and "=" in ln:
            k, v = ln[5:].split("=", 1)
            out[k] = v
    return out


def sums_of(text):
    """The integer key=value tokens of a c2_sums line (dominant= and any other word dropped)."""
    return {k: int(v) for k, v in (t.split("=", 1) for t in (text or "").split() if "=" in t) if v.isdigit()}


def j7a_profile(labs, facts, run, ref_sums, ref_facts):
    """§15.13.10.3's profile of a bad or bad-partial J7a run against J6c. Returns (lines, kw_sub).

    labs and facts are J7a's (cw_watches, cw_analyze's accepted exports); run is J7a's parse-s1.txt
    fields (c2_start_anchor, c2_check_words, j7a); ref_sums is J6c's c2_sums (from its registered
    parse-s1.txt) and ref_facts J6c's accepted watch exports. P4 reads memcanary's content rule
    over the c2 sums of both runs, since J6c's registered files carry sums, not content= tokens.
    """
    it = {}
    fs = [labs[l]["f"] for l in WATCH_C2]
    allc2 = all(f is not None for f in fs)
    s = j6_sums(labs, WATCH_C2) if allc2 else None
    fa = labs["a"]["f"]
    it["P1"] = "n/a" if fa is None else "same" if fa["base"]["bad"] > 0 else "differs"
    anc = run.get("c2_start_anchor", "n/a")
    it["P2"] = "n/a" if anc == "n/a" else "same" if anc == "first-word" else "differs"
    it["P3"] = ("n/a" if not allc2 else
                "same" if not c2_f34(s) and all(f["verdict"]["reads"] == "stable" for f in fs) else "differs")
    if not allc2 or not ref_sums or "bad" not in ref_sums:
        it["P4"] = "n/a"
    else:
        same4 = (content_rule(s, s["bad"]) == content_rule(ref_sums, ref_sums["bad"]) and
                 sum(s[k] for k in J7A_FLIP_PAT) == 0)
        it["P4"] = "same" if same4 else "differs"
    it["P5"] = "n/a" if not allc2 else "same" if all(f["verdict"]["writer"] != "ongoing" for f in fs) else "differs"
    m = re.match(r"^start:([0-9]+),end:([0-9]+)$", run.get("c2_check_words", ""))
    it["P6"] = "n/a" if not m else "same" if int(m.group(2)) <= int(m.group(1)) else "differs"
    lines = []
    if "a" in facts and "a" in ref_facts:
        for mp in ("bad_final", "changed_ever"):
            same, common, only7, only6, pres = p7_compare(facts["a"]["maps"][mp], ref_facts["a"]["maps"][mp])
            if mp == "bad_final":
                it["P7"] = "same" if same else "differs"
            lines.append(f"p7 map={mp} " + (f"result={it['P7']} " if mp == "bad_final" else "") +
                         f"pages_common={common} only_j7a={only7} only_j6c={only6} "
                         f"mib_presence={'same' if pres else 'differs'}" +
                         (f" share={P7_SHARE}" if mp == "bad_final" else " record_only=yes"))
    else:
        it["P7"] = "n/a"
        lines.append("p7 map=bad_final result=n/a reason=watch-a-export-not-accepted")
    lines = [f"profile item={k} result={v}" for k, v in it.items()] + lines
    diff = [k for k, v in it.items() if v == "differs"]
    na = [k for k, v in it.items() if v == "n/a"]
    reading = (run.get("j7a") or "").split(",")
    if "bad-partial" in reading or any(it[k] == "n/a" for k in ("P1", "P2", "P7")):
        kw_sub = "partial"
    elif all(it[k] == "same" for k in ("P1", "P2", "P7")):
        kw_sub = "anchored"
    else:
        kw_sub = "differs"
    lines.append("profile_vs_j6c=" + ("same" if not diff and not na else "differs:" + (",".join(diff) or "none")))
    lines.append("profile_na=" + (",".join(na) or "none"))
    lines.append(f"kw_sub={kw_sub}")
    return lines, kw_sub


def j6c_ref_check(ref_dir, pairs):
    """Refused unless every J6C_REF_FILES file in ref_dir hashes as its registered NAME=HEX pair."""
    want = {}
    for p in pairs:
        name, _, hx = p.partition("=")
        if name not in J6C_REF_FILES or not HEX64_RE.match(hx) or name in want:
            raise Refused(f"--ref-sha256 {q(p)} is not NAME=<64 lowercase hex> for one of {','.join(J6C_REF_FILES)}")
        want[name] = hx
    if set(want) != set(J6C_REF_FILES):
        raise Refused("--ref-sha256 must name each of " + ",".join(J6C_REF_FILES) + " once (s1-design.md 15.13.7)")
    got = {}
    for name in J6C_REF_FILES:
        path = os.path.join(ref_dir, name)
        if not os.path.isfile(path):
            raise Refused(f"the J6c reference file {name} is absent")
        got[name] = PM.read_bytes(path)
        if sha256(got[name]) != want[name]:
            raise Refused(f"the J6c reference file {name} does not match its registered sha256 (s1-design.md 15.13.7)")
    return got


def cmd_j6c_refs(a):
    """The J6c reference files' sha256, for J7a's stage to register (s1-design.md §15.13.8)."""
    for name in J6C_REF_FILES:
        path = os.path.join(a.dir, name)
        if not os.path.isfile(path):
            print(out_line(f"parse-s1: input error: the J6c reference file {name} is absent"), file=sys.stderr)
            return 1
        sys.stdout.write(out_line(f"S1REF file={name} sha256={sha256(PM.read_bytes(path))}") + "\n")
    return 0


def cmd_canwatch(a):
    try:
        factor = cw_factor(a.fill_factor)
    except InputError as e:
        print(out_line(f"parse-s1: usage: canwatch needs the pre-registered --fill-factor: {e}"), file=sys.stderr)
        return 2
    kpf = list(a.kpf or [])
    if len(kpf) > 2:
        print("parse-s1: usage: canwatch takes one --kpf header, or a prequiesce and a postquiesce pair",
              file=sys.stderr)
        return 2
    entry = getattr(a, "entry", None) or "kexec"
    ref_dir = getattr(a, "ref_j6c", None)
    ref_pairs = list(getattr(a, "ref_sha256", None) or [])
    run_parse = getattr(a, "run_parse", None)
    if entry == "uefi":
        if kpf or not ref_dir or not run_parse:
            print("parse-s1: usage: canwatch --entry uefi needs --ref-j6c, the five --ref-sha256 pairs and "
                  "--run-parse, and takes no --kpf (s1-design.md 15.13.7)", file=sys.stderr)
            return 2
    elif ref_dir or ref_pairs or run_parse:
        print("parse-s1: usage: --ref-j6c, --ref-sha256 and --run-parse belong to canwatch --entry uefi",
              file=sys.stderr)
        return 2
    data = PM.read_bytes(a.log)
    recs, blocks, _, _ = split_log(data)
    for blk in blocks:
        decode_block(blk)
    R = Recs(recs)
    labs, _stray = cw_watches(R)
    bin_dir = a.bin_dir or os.path.dirname(os.path.abspath(a.log))
    head = [f"parser={rel_repo(__file__)} sha256={sha256(open(__file__, 'rb').read())}",
            f"input_log={rel_repo(a.log)} sha256={sha256(data)} bytes={len(data)}"]
    if entry == "uefi":
        refs = j6c_ref_check(ref_dir, ref_pairs)
        run_bytes = PM.read_bytes(run_parse)
        run = parse_fields(run_bytes)
        if f" sha256={sha256(data)} " not in f" {run.get('input_log', '')} ":
            raise Refused("--run-parse is not the J7a parse of this log (its input_log sha256 differs)")
        if run.get("step") != "J7a":
            raise Refused("--run-parse is not a J7a parse (step is not J7a)")
        head.append("entry=uefi")
        head += [f"input_ref_j6c file={name} registered=match" for name in J6C_REF_FILES]
        head.append(f"input_run_parse={rel_repo(run_parse)} sha256={sha256(run_bytes)}")
    bins = {}
    for l in WATCH_LABELS:
        p = os.path.join(bin_dir, export_filename(f"j1{l}"))
        if os.path.isfile(p):
            bins[l] = PM.read_bytes(p)
            head.append(f"input_bin label={l} file={rel_repo(p)} sha256={sha256(bins[l])} bytes={len(bins[l])}")
        else:
            bins[l] = "absent"
            head.append(f"input_bin label={l} file={rel_repo(p)} absent")
    head += [f"input_kpf={rel_repo(p)} " + (f"sha256={sha256(PM.read_bytes(p))}" if os.path.isfile(p) else "absent")
             for p in kpf] or ["input_kpf=none"]
    head.append(f"fill_factor={a.fill_factor}")
    res = cw_analyze(labs, bins, factor, kpf, cw_log_records(R, blocks), entry=entry)
    if entry == "uefi":
        reading = (run.get("j7a") or "").split(",")
        if "bad-unstable" not in reading and ("bad" in reading or "bad-partial" in reading):
            ref_facts = {}
            for l in WATCH_C2:
                fx, reason, _ = cw_decode(refs[f"s1-j1{l}.bin"], l)
                if reason is None:
                    ref_facts[l] = fx
            plines, _ = j7a_profile(labs, res["facts"], run, sums_of(parse_fields(refs["parse-s1.txt"]).get("c2_sums")),
                                    ref_facts)
        else:
            plines = ["profile=not-computed reason=reading-not-bad j7a=" + (run.get("j7a") or "absent")]
        res["lines"] = res["lines"][:-1] + plines + res["lines"][-1:]
    text = "".join(out_line("S1CW " + ln) + "\n" for ln in head + res["lines"])
    out_dir = None if a.out_dir == "none" else (a.out_dir or os.path.dirname(os.path.abspath(a.log)))
    if out_dir is not None:
        text += out_line(f"S1CW wrote={rel_repo(write_canwatch(out_dir, text))}") + "\n"
    sys.stdout.write(text)
    return 0


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
SYN_QVMLOG = b"FDT saved to '/dev/shmem/s1-fdt.dtb'\r\n"   # a clean dryrun's text, CRLF as T1 attempt 1's export


def syn_stamp(label):
    return f"STAMP {label} cycles=1 cps=31250000 cpu=0 mono_ns=1 bytes=1"


def syn_log(profile, mode, dtb, conf_bytes, cmdline, *, enc="base64", qvmlog=SYN_QVMLOG):
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
        if qvmlog is not None:
            qb = base64.b64encode(qvmlog).decode("ascii")
            L += [f"S1 BEGIN name=qvmlog bytes={len(qvmlog)} md5={md5(qvmlog)} enc=base64"]
            L += [qb[k:k + 76] for k in range(0, len(qb), 76)]
            L += ["S1 END name=qvmlog"]
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


def syn_watch(label, **kw):
    """(console lines, export bytes) of one memcanary-w watch, consistent by construction (SYNTHETIC; not a record).

    kw: classes {class: n} (words' bad is their sum), bad_base (default that bad), the time
    counts (snaps, changed_snaps, changed_words, healed, osc, prog, stable; stable defaults to
    changed_words less osc and prog, as memcanary.c counts), the reread counts (revert,
    revert_flip2, whole_heal; default 0), stride (eight bins; default the bad words at offsets
    0, 8, 16 ... in turn), sig {ascii_runs, ascii_bytes, ipv4, beacon, trb_evt}, writer, content,
    and the page lists bad_pages, changed_pages, healed_pages (defaults: the first pages the
    count needs, page 0, page 0).
    """
    name, interval, count = WATCH_LABELS[label]
    cls = dict.fromkeys(WORD_CLASSES, 0)
    cls.update(kw.get("classes", {}))
    bad = sum(cls.values())
    t = {"snaps": min(count, 180), "changed_snaps": 0, "changed_words": 0, "healed": 0, "osc": 0, "prog": 0,
         "stable": 0}
    t.update((k, kw[k]) for k in list(t) if k in kw)
    if t["changed_words"] and not t["changed_snaps"]:
        t["changed_snaps"] = 1
    if "stable" not in kw:
        t["stable"] = max(t["changed_words"] - t["osc"] - t["prog"], 0)
    rr = {k: kw.get(k, 0) for k in ("revert", "revert_flip2", "whole_heal")}
    bad_base = kw.get("bad_base", bad)
    stride = list(kw.get("stride", [bad // 8 + (1 if k < bad % 8 else 0) for k in range(8)]))
    sig = dict.fromkeys(("ascii_runs", "ascii_bytes") + SIGNATURES, 0)
    sig.update(kw.get("sig", {}))
    cwords = t["changed_words"]
    writer = kw.get("writer") or (("none" if bad_base == 0 and bad == 0 else "static") if cwords == 0 else "stopped")
    reads = "prog" if t["prog"] else "osc" if t["osc"] else "revert" if rr["revert"] else "stable"
    pfx = f"S1 CANARY {name} watch="
    lines = [
        f"{pfx}base label={label} bad={bad_base} pages={-(-bad_base // WWORDS)} first_off=0x0 "
        f"last_off=0x{8 * max(bad_base - 1, 0):x}",
        f"{pfx}time label={label} " + " ".join(f"{k}={v}" for k, v in t.items()) +
        f" stop={'count' if t['snaps'] == count else 'deadline'}",
        f"{pfx}reread label={label} " + " ".join(f"{k}={v}" for k, v in rr.items()),
        f"{pfx}words label={label} bad={bad} " + " ".join(f"{k}={cls[k]}" for k in _WORDS1),
        f"{pfx}words2 label={label} " + " ".join(f"{k}={cls[k]}" for k in _WORDS2),
        f"{pfx}stride label={label} " + " ".join(f"b{k}={v}" for k, v in enumerate(stride)),
        f"{pfx}bytes label={label} " + " ".join(f"{k}={v}" for k, v in sig.items()),
        f"{pfx}verdict label={label} writer={writer} heal={'yes' if t['healed'] else 'no'} reads={reads} "
        f"content={kw.get('content', 'unclassified' if bad else 'none')}"]

    def mask(key, n, default):
        return sum(1 << p for p in set(kw.get(key, default if n else ())))

    maps = (mask("bad_pages", bad, range(-(-bad // WWORDS))), mask("changed_pages", cwords, (0,)),
            mask("healed_pages", t["healed"], (0,)))
    stop = 1 if t["snaps"] == count else 2
    data = (CW_HEAD.pack(CW_MAGIC, CW_VERSION, name.encode("ascii"), label.encode("ascii"), CANARIES[name], WPAGES,
                         interval, t["snaps"], count, WATCH_DEADLINE_S[label], stop, bytes(8)) +
            b"".join(m.to_bytes(CW_MAP_BYTES, "little") for m in maps) +
            CW_TAIL.pack(bad_base, bad, cwords, t["healed"]))
    return lines, data


SYN_WQ_MARKS = ("[  100.000001] s1wq: begin arm=control result=0", "[  400.000001] s1wq: kexec issuing",
                "[  401.000001] kexec_core: Starting new kernel")
SYN_MCW = "a" * 64      # a synthetic memcanary_w_sha256 stamp


def syn_j6_log(conf_bytes, cmdline, *, watches=None, hold=("fill=ok", "verify=ok"), hold_mib=J1_HOLD_MIB,
               drop_exports=(), mcw=SYN_MCW):
    """A J6 COM3 capture of s1-j1 in host mode, in §15.4.8's order, and its exports (SYNTHETIC; not a record).

    B2's synthetic log with the allocation replaced by watches a and b, the hold's fill line,
    watches c and d and the hold's verify line (hold: the two lines' texts after mib=; None
    leaves one out), the detached sequence's markers before the kexec, and the j1a..j1d
    exports after FAIL_STATE.
    """
    made = {l: syn_watch(l, **(watches or {}).get(l, {})) for l in WATCH_LABELS}
    hl = [None if h is None else f"S1 ALLOC hold mib={hold_mib} {h}" for h in hold]
    block = made["a"][0] + made["b"][0] + hl[:1] + made["c"][0] + made["d"][0] + hl[1:]
    out = []
    for ln in syn_log("board", "host", b"", conf_bytes, cmdline):
        ln = ln.replace("T234 S1 s1-h1 ", f"T234 S1 {J1_RUNG} ")
        if ln.startswith("S1 CONFIG ") and mcw:
            ln += f" memcanary_w_sha256={mcw}"
        if ln == f"S1 ALLOC mib={B2_ALLOC_MIB} fill=ok verify=ok":
            out += [x for x in block if x is not None]
            continue
        out.append(ln)
        if ln.startswith("--- raw capture started"):
            out += list(SYN_WQ_MARKS)
        if ln == "S1 FAIL_STATE none":
            for l, (_, data) in made.items():
                if l in drop_exports:
                    continue
                b = base64.b64encode(data).decode("ascii")
                out += [f"S1 BEGIN name=j1{l} bytes={len(data)} md5={md5(data)} enc=base64"]
                out += [b[k:k + 76] for k in range(0, len(b), 76)]
                out += [f"S1 END name=j1{l}", f"S1 EXPORT name=j1{l} bytes={len(data)} md5={md5(data)} enc=base64 rc=0"]
    return out, {l: d for l, (_, d) in made.items()}


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
    check("conf reject hostdev outside vdev", rejects("hostdev /dev/ptyp3\n" + base, "vdev-option-outside-vdev"))
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
            enc="base64", gate_ok=True, image=None, initrd=None, qvmlog=SYN_QVMLOG, diag=None, arm=None,
            fill_factor=None, hold_mib=None, kpf_paths=()):
        blob = fdt_build(tree) if tree is not None else dtb
        if lines is None:
            lines = syn_log(profile, mode, blob, conf_bytes, cmdline, enc=enc, qvmlog=qvmlog)
        data = ("\n".join(lines) + "\n").encode("latin-1")
        bbd = syn_blackbox(lines) if (bb == "auto" and profile == "board") else (bb if bb != "auto" else None)
        return analyze_run(data, profile=profile, mode=mode, conf_bytes=conf_bytes, conf_info=info,
                           conf_gate_ok=gate_ok, bb_data=bbd, ref_conf_sha256=sha256(conf_bytes) if ref else None,
                           reset_reason=reset if profile == "board" else None,
                           kexec_tree_sha256=kexec if profile == "board" else None, pc_image=image,
                           pc_initrd=initrd, diag=diag, arm=arm, fill_factor=fill_factor, hold_mib=hold_mib,
                           kpf_paths=kpf_paths)

    def has(res, text):
        return any(ln.startswith(text) for ln in res["lines"])

    r = run("tcg", "dryrun")
    check("run T1 synthetic passes", r["verdict"] == "pass" and r["step"] == "T1" and has(r, "item1_t1=pass"))
    check("run T1 decodes the fdt export", has(r, "export=name=fdt status=ok") and has(r, "fdt_gating=ok"))
    check("run T1 prints no FreeMem value", not any("1400" in ln for ln in r["lines"]))
    check("run T1 records dryrun rc 0 and no qvm diagnostic", has(r, "dryrun_rc=0") and
          has(r, "qvmlog_diagnostics=0"))
    r = run("tcg", "dryrun", tree=syn_tree(cmdline, psci=False))
    check("run T1 with no PSCI node fails", r["verdict"] == "fail" and has(r, "fdt_gate psci=missing"))

    # C3 as tightened after T1 attempt 1 (s1-design.md §14.9).
    def tier(res, t):
        return next((ln for ln in res["lines"] if ln.startswith(f"tier_{t}=")), "")

    t1 = syn_log("tcg", "dryrun", dtb, conf_bytes, cmdline)
    rc64 = ((r"^BWAIT run prog=qvm rc=0 ", "BWAIT run prog=qvm rc=64 "), (r"^S1 DRYRUN rc=0 ", "S1 DRYRUN rc=64 "))
    r = run("tcg", "dryrun", edit_lines(t1, sub=rc64))
    check("run T1 dryrun rc=64 fails L2 and item 1 (saved=yes, logger_errors=0)", r["verdict"] == "fail" and
          has(r, "item1_t1=fail") and "dryrun_rc_not_0" in tier(r, "L2") and has(r, "dryrun_rc=64"))
    diag = (b"FDT saved to '/dev/shmem/s1-fdt.dtb'\r\n"
            b"[/data/s1/s1-linux.conf:14] Unable to open '/dev/ttyp3': Interrupted function call\r\n")
    r = run("tcg", "dryrun", qvmlog=diag)
    check("run T1 rc=0 with a [file:line] diagnostic in qvmlog fails L2 and item 1", r["verdict"] == "fail" and
          has(r, "item1_t1=fail") and has(r, "dryrun_rc=0") and has(r, "qvmlog_diagnostics=1") and
          "dryrun_qvm_diagnostics" in tier(r, "L2") and "dryrun_rc_not_0" not in tier(r, "L2"))
    r = run("tcg", "dryrun", edit_lines(syn_log("tcg", "dryrun", dtb, conf_bytes, cmdline, qvmlog=diag), sub=rc64))
    check("run T1 shaped like attempt 1 fails on both rc and the diagnostic", r["verdict"] == "fail" and
          "dryrun_rc_not_0" in tier(r, "L2") and "dryrun_qvm_diagnostics" in tier(r, "L2"))
    r = run("tcg", "dryrun", qvmlog=None)
    check("run T1 without the qvmlog export fails L2", r["verdict"] == "fail" and "qvmlog_export" in tier(r, "L2"))
    r = run("tcg", "dryrun", qvmlog=SYN_QVMLOG + b"note: [a.conf:2] not at the line start\r\n")
    check("run T1 counts only [file:line] at the line start", r["verdict"] == "pass" and
          has(r, "qvmlog_diagnostics=0"))
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
    r = run("tcg", "hold", edit_lines(hl, sub=rc64))
    check("run T3 with dryrun rc=64 fails t3", r["verdict"] == "fail" and
          "dryrun_rc_not_0" in next(ln for ln in r["lines"] if ln.startswith("t3=")))
    r = run("tcg", "hold", qvmlog=diag)
    check("run T3 with a qvm diagnostic fails t3", r["verdict"] == "fail" and
          "dryrun_qvm_diagnostics" in next(ln for ln in r["lines"] if ln.startswith("t3=")))
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

    # ---- run --diag (s1-design.md §15.5 A3): J2, J2b and J4 read B2's synthetic log (SYNTHETIC; not a record).
    # J2 and J4 add the detached sequence's /dev/kmsg markers on L4T's console before the kexec.
    wq_marks = tuple((r"^--- raw capture started", ln) for ln in
                     ("[  100.000001] s1wq: begin arm=control result=0", "[  400.000001] s1wq: kexec issuing",
                      "[  401.000001] kexec_core: Starting new kernel"))
    jl = edit_lines(bl, add_after=wq_marks)
    c1_ok, c2_ok, c3_ok = (rf"^S1 CANARY {c} verify=ok$" for c in CANARIES)
    alloc_ok = r"^S1 ALLOC mib=1536 fill=ok verify=ok$"

    def bad(c):
        return f"S1 CANARY {c} verify=bad first_off=0x0 words=1"

    def sub_nth(lines_, pattern, new, n):
        """lines_ with only the n-th (from 0) line matching pattern replaced by new: 0 the start check, 1 the end."""
        out_, k = [], 0
        for ln in lines_:
            if re.search(pattern, ln):
                ln, k = (new if k == n else ln), k + 1
            out_.append(ln)
        return out_

    def field(res, key):
        return next((ln.split("=", 1)[1] for ln in res["lines"] if ln.startswith(key + "=")), None)

    jres = []

    def jrun(diag, lines_):
        res = run("board", "host", lines_, diag=diag)
        jres.append(res)
        return res

    def diag_is(res, verdict, row, failed_=()):
        return (res["verdict"] == "diagnostic " + verdict and res["j_row"] == row and field(res, "j_row") == row and
                all(f in res["lines"][-1].split("failed=", 1)[-1].split(",") for f in failed_) and
                (verdict == "incomplete") == ("failed=" in res["lines"][-1]))

    r = jrun("j2", jl)
    check("run --diag j2 synthetic is complete, row F33, step J2, and prints no b2= field",
          diag_is(r, "complete", "F33") and r["step"] == "J2" and has(r, "step=J2") and
          r["lines"][-1] == "verdict=diagnostic complete" and not has(r, "b2=") and
          [field(r, k) for k in CANARY_CHECKS] == ["ok"] * 6 and field(r, "alloc") == "ok" and
          field(r, "wq_kexec_issuing") == "yes" and field(r, "wq_reset_marker") == "no")
    r = jrun("j2", edit_lines(jl, sub=((c2_ok, bad("c2")),)))
    check("run --diag j2 c2 bad at both checks is complete, row F32, while B2's own L1 still misses it",
          diag_is(r, "complete", "F32") and "canary_start_c2" in tier(r, "L1") and field(r, "L1_records") == "ok"
          and field(r, "c2_start") == "bad" and field(r, "c2_end") == "bad")
    r = jrun("j2", sub_nth(jl, c2_ok, bad("c2"), 0))
    check("run --diag j2 c2 bad at the start check only is row F32a", diag_is(r, "complete", "F32a") and
          field(r, "c2_start") == "bad" and field(r, "c2_end") == "ok")
    r = jrun("j2", sub_nth(jl, c2_ok, bad("c2"), 1))
    check("run --diag j2 c2 bad at the end check only is row F32b", diag_is(r, "complete", "F32b") and
          field(r, "c2_start") == "ok" and field(r, "c2_end") == "bad")
    r = jrun("j2", sub_nth(jl, c1_ok, bad("c1"), 1))
    check("run --diag j2 c1 bad at the end check is row F39", diag_is(r, "complete", "F39"))
    r = jrun("j2", sub_nth(edit_lines(jl, sub=((c2_ok, bad("c2")),)), c3_ok, bad("c3"), 0))
    check("run --diag j2 c3 bad outranks c2 bad: row F39", diag_is(r, "complete", "F39"))
    r = jrun("j2", sub_nth(sub_nth(jl, c1_ok, bad("c1"), 0), c2_ok, "S1 CANARY c2 tool=no-output", 1))
    check("run --diag j2 c1 bad in an incomplete parse is still row F39", diag_is(r, "incomplete", "F39", ("c2_end",))
          and field(r, "c2_end") == "unread")
    r = jrun("j2", sub_nth(jl, c2_ok, "S1 CANARY c2 refuse=in-sysram", 0))
    check("run --diag j2 a canary refusal is incomplete, row F40", diag_is(r, "incomplete", "F40", ("c2_start",)) and
          field(r, "c2_start") == "unread")
    r = jrun("j2", edit_lines(sub_nth(jl, c3_ok, "DROP", 1), drop=(r"^DROP$",)))
    check("run --diag j2 a missing end check is incomplete, row F40", diag_is(r, "incomplete", "F40", ("c3_end",)) and
          field(r, "c3_end") == "absent" and field(r, "c3_start") == "ok")
    r = jrun("j2", edit_lines(jl, add_after=((r"^S1 ALLOC mib=1536", "S1 CANARY c1 verify=ok"),)))
    check("run --diag j2 two lines in one check are incomplete, row F40", diag_is(r, "incomplete", "F40", ("c1_end",))
          and field(r, "c1_end") == "multiple")
    r = jrun("j2", edit_lines(jl, sub=((alloc_ok, "S1 ALLOC mib=1536 map=fail errno=12"),)))
    check("run --diag j2 allocation map=fail is incomplete, row F40", diag_is(r, "incomplete", "F40", ("alloc",)) and
          field(r, "alloc") == "map-fail")
    r = jrun("j2", edit_lines(jl, drop=(r"^S1 ALLOC mib=1536",)))
    check("run --diag j2 with no allocation line leaves every check unsplit, row F40",
          diag_is(r, "incomplete", "F40", ("alloc",) + CANARY_CHECKS) and
          [field(r, k) for k in CANARY_CHECKS] == ["unsplit"] * 6)
    r = jrun("j2", edit_lines(jl, sub=((alloc_ok, "S1 ALLOC mib=1536 fill=ok verify=bad first_off=0x0 words=1"),)))
    check("run --diag j2 allocation verify=bad is recorded and changes no row", diag_is(r, "complete", "F33") and
          field(r, "alloc") == "bad")
    r = jrun("j2", edit_lines(jl, sub=((r"canary_in_sysram=no", "canary_in_sysram=yes"),)))
    check("run --diag j2 an S1 ASINFO difference is incomplete, row F40",
          diag_is(r, "incomplete", "F40", ("L1_records",)) and "asinfo" in field(r, "L1_records"))
    r = jrun("j2", edit_lines(jl, drop=(r"procnto up",)))
    check("run --diag j2 with no procnto up is incomplete, row F40", diag_is(r, "incomplete", "F40", ("L0",)))
    r = jrun("j2", edit_lines(jl, sub=((r" fdt=none", ""),)))
    check("run --diag j2 missing item-5 stamps: refused, incomplete with item5 failed, row F40",
          r["refused"] and diag_is(r, "incomplete", "F40", ("item5",)) and has(r, "item5=refused missing=fdt=none"))
    r = jrun("j2", edit_lines(jl, drop=(r"s1wq: kexec issuing",)))
    check("run --diag j2 without the kexec issuing marker is incomplete, row F40",
          diag_is(r, "incomplete", "F40", ("wq_kexec_issuing",)) and field(r, "wq_kexec_issuing") == "no")
    r = jrun("j2", edit_lines(bl, add_after=((r"procnto up", "[  400.000001] s1wq: kexec issuing"),)))
    check("run --diag j2 a kexec issuing marker after the shim line does not count",
          diag_is(r, "incomplete", "F40", ("wq_kexec_issuing",)))
    r = jrun("j2", edit_lines(jl, add_after=((r"s1wq: kexec issuing", "[  580.000001] s1wq: abort reason=governor"),)))
    check("run --diag j2 with an abort marker is incomplete, row F40",
          diag_is(r, "incomplete", "F40", ("wq_reset_marker",)) and field(r, "wq_reset_marker") == "yes")
    r = jrun("j2b", bl)
    check("run --diag j2b synthetic with no s1wq: marker is complete, row F46, step J2b",
          diag_is(r, "complete", "F46") and r["step"] == "J2b" and field(r, "wq_markers") == "none" and
          field(r, "wq_kexec_issuing") is None)
    r = jrun("j2b", sub_nth(bl, c2_ok, bad("c2"), 1))
    check("run --diag j2b c2 bad at one check is row F45", diag_is(r, "complete", "F45"))
    r = jrun("j2b", jl)
    check("run --diag j2b with s1wq: markers is incomplete, row F40",
          diag_is(r, "incomplete", "F40", ("wq_markers",)) and field(r, "wq_markers") == "present")
    r = jrun("j4", jl)
    check("run --diag j4 synthetic is complete, row F35, step J4", diag_is(r, "complete", "F35") and r["step"] == "J4")
    r = jrun("j4", sub_nth(jl, c2_ok, bad("c2"), 1))
    check("run --diag j4 c2 bad at the end check is row F36", diag_is(r, "complete", "F36"))
    r = jrun("j4", edit_lines(jl, sub=((c2_ok, bad("c2")),)))
    check("run --diag j4 c2 bad at both checks is row F36", diag_is(r, "complete", "F36"))
    r = jrun("j4", sub_nth(jl, c3_ok, bad("c3"), 1))
    check("run --diag j4 c3 bad is row F39", diag_is(r, "complete", "F39"))
    r = jrun("j4", edit_lines(jl, drop=(r"s1wq: kexec issuing",)))
    check("run --diag j4 clean canaries without the kexec issuing marker are not F35: incomplete, row F40",
          diag_is(r, "incomplete", "F40", ("wq_kexec_issuing",)))
    check("run --diag no J parse prints a b2= field, verdict=pass, or pass on any line but conf_gate's",
          len(jres) == 27 and all(not has(x, "b2=") and not any("verdict=pass" in ln for ln in x["lines"]) and
                                  all(ln.startswith("conf_gate=") for ln in x["lines"] if re.search(r"=pass\b", ln))
                                  for x in jres))
    try:
        run("board", "boot", diag="j2")
        check("run --diag on a non-host log is refused", False)
    except InputError:
        check("run --diag on a non-host log is refused", True)
    r = run("board", "host", jl)
    check("run B2 on a log with s1wq: markers still passes and prints no diagnostic field",
          r["verdict"] == "pass" and has(r, "b2=pass") and not any(
              has(r, k + "=") for k in ("j_row", "L1_records", "alloc", "wq_kexec_issuing") + CANARY_CHECKS))
    jlog, jbb = os.path.join(tdir, "j2-com3.log"), os.path.join(tdir, "j2-blackbox.log")
    with open(jlog, "wb") as f:
        f.write(("\n".join(jl) + "\n").encode("latin-1"))
    with open(jbb, "wb") as f:
        f.write(syn_blackbox(jl))

    def jcmd(**kw):
        ns = dict(log=jlog, profile="board", mode="host", blackbox=jbb, out_dir="none", conf=None,
                  ref_conf_sha256=None, reset_reason="MAINSWRST", kexec_tree_sha256=SYN_KEXEC, image=None,
                  initrd=None, diag="j2")
        ns.update(kw)
        b = io.StringIO()
        with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
            rc_ = cmd_run(argparse.Namespace(**ns))
        return rc_, b.getvalue()

    rc, jtext = jcmd()
    check("run cmd --diag j2 prints diag=j2, S1PC step=J2 and the diagnostic verdict last, exit 0",
          rc == 0 and "S1PC profile=board mode=host diag=j2\n" in jtext and "S1PC step=J2\n" in jtext and
          "S1PC j_row=F33\n" in jtext and jtext.endswith("S1PC verdict=diagnostic complete\n"))
    jwritten = write_run_outputs(os.path.join(tdir, "outj"), {"blocks": []}, jtext, check=False)
    with open(jwritten[-1], "rb") as f:
        jfile = f.read().decode("ascii")
    check("run a J parse-s1.txt never contains b2=pass or verdict=pass",
          jwritten[-1].endswith("parse-s1.txt") and "verdict=diagnostic" in jfile and "b2=pass" not in jfile and
          "verdict=pass" not in jfile and "S1PC b2=" not in jfile)
    os.remove(jwritten[-1])
    os.rmdir(os.path.join(tdir, "outj"))
    check("run cmd --diag with --mode boot is a usage error", jcmd(mode="boot")[0] == 2)
    rc, b2text = jcmd(diag=None)
    check("run cmd B2 without --diag keeps b2=pass and verdict=pass", rc == 0 and "S1PC b2=pass\n" in b2text and
          b2text.endswith("S1PC verdict=pass\n") and "diag=" not in b2text and "j_row=" not in b2text)

    # ---- run --diag j1, canwatch and T-J1 (s1-design.md §15.4.8, §15.5 B7 and B8.4): J6's watcher
    # (SYNTHETIC; not a record). The watch lines and exports follow the formats in the docstring.
    watch_line = "S1 CANARY c2 watch=base label=a bad=0 pages=0 first_off=0x0 last_off=0x0"
    r = run("board", "host", edit_lines(bl, add_after=((r"^S1 ALLOC mib=1536", watch_line),)))
    check("run B2 synthetic with an added watch= line still gives b2=pass (six_verify unchanged)",
          r["verdict"] == "pass" and has(r, "b2=pass"))
    r = run("tcg", "boot", edit_lines(syn_log("tcg", "boot", dtb, conf_bytes, cmdline),
                                      add_after=((r"^S1 GATE mem ok", watch_line),)))
    check("run T2 a watch= line on TCG fails the profile check", r["verdict"] == "fail" and
          has(r, "missing_profile=tcg_asinfo_or_canary"))
    j6res = []

    def j6(watches=None, *, arm="control", lines_=None, factor="2", hold_mib=None, kpf=(), **kw):
        if lines_ is None:
            lines_, _ = syn_j6_log(conf_bytes, cmdline, watches=watches, **kw)
        res = run("board", "host", lines_, diag="j1", arm=arm, fill_factor=factor, hold_mib=hold_mib, kpf_paths=kpf)
        j6res.append(res)
        return res

    def j6_is(res, verdict, rows_, failed_=()):
        last = res["lines"][-1]
        return (res["verdict"] == "diagnostic " + verdict and field(res, "j_row") == res["j_row"] and
                set(res["j_row"].split(",")) == set(rows_) and len(res["j_row"].split(",")) == len(rows_) and
                all(f in last.split("failed=", 1)[-1].split(",") for f in failed_) and
                (verdict == "incomplete") == ("failed=" in last))

    def c2w(**kw):
        return {l: kw for l in WATCH_C2}

    other16 = {"classes": {"other": 16}}
    r = j6()
    check("run --diag j1 synthetic control arm: complete, step J6c, row writer-none, no b2= field",
          j6_is(r, "complete", ["writer-none"]) and r["step"] == "J6c" and has(r, "step=J6c") and
          r["lines"][-1] == "verdict=diagnostic complete" and not has(r, "b2=") and
          [field(r, k) for k in CANARY_CHECKS] == ["ok"] * 6 and field(r, "hold") == "ok" and
          field(r, "watch_order") == "ok" and field(r, "canary_between") == "0" and field(r, "rung_j1") == "yes" and
          all(field(r, f"watch_{l}") == "ok" and field(r, f"export_j1{l}") == "ok" for l in WATCH_LABELS) and
          field(r, "kpf") == "not-given" and has(r, "c2_sums=") and field(r, "hold_mib_vs_pc") == "not_given")
    r = j6(arm="remove")
    check("run --diag j1 remove arm is step J6r", j6_is(r, "complete", ["writer-none"]) and r["step"] == "J6r")
    r = j6(c2w(classes={"zero": 16}))
    check("run --diag j1 c2 bad and unchanged at every watch: writer-static", j6_is(r, "complete", ["writer-static"]))
    r = j6(c2w(classes={"flip2_same": 12, "flip2_var": 4}, changed_words=20, osc=20, writer="ongoing"))
    check("run --diag j1 osc above 0, prog 0, flip2 the majority: F34", j6_is(r, "complete", ["F34"]))
    r = j6(c2w(classes={"flip2_same": 12, "flip2_var": 4}, changed_words=20, osc=18, prog=2, writer="ongoing"))
    check("run --diag j1 the same with prog above 0: a live writer, not F34", j6_is(r, "complete", ["live-writer"]))
    r = j6(c2w(classes={"other": 16}, changed_words=3, stable=3))
    check("run --diag j1 changed words with stable re-reads: live-writer", j6_is(r, "complete", ["live-writer"]))
    r = j6(c2w(classes={"small32": 16}, changed_words=4, prog=2, stable=2))
    check("run --diag j1 prog with small32 dominant: live-writer and ring-record",
          j6_is(r, "complete", ["live-writer", "ring-record"]))
    r = j6(c2w(classes={"pat_same": 10, "pat_other": 6}, changed_words=2, osc=2, healed=2))
    check("run --diag j1 healed with pat_same dominant: restoring-writer", j6_is(r, "complete", ["restoring-writer"]))
    heal = {"a": other16, "c": other16, "b": {"classes": {"other": 16}, "changed_words": 1100, "changed_snaps": 20,
                                              "osc": 1100, "healed": 1100, "whole_heal": 2, "changed_pages": (0, 1),
                                              "healed_pages": (0, 1)}}
    r = j6(heal)
    check("run --diag j1 whole_heal above 0 on one watch: restoring-writer (b changes and c does not: fill-rate too)",
          j6_is(r, "complete", ["restoring-writer", "fill-rate"]))
    heal["b"] = dict(heal["b"], whole_heal=0)
    r = j6(heal)
    check("run --diag j1 healed >= 512 x healed pages but no page healed in one snapshot: no restoring-writer",
          j6_is(r, "complete", ["fill-rate"]))
    heal["b"] = dict(heal["b"], healed=600)
    r = j6(heal)
    check("run --diag j1 a heal short of whole pages, other classes, mixed writers: fill-rate only",
          j6_is(r, "complete", ["fill-rate"]))
    r = j6(c2w(revert=6, revert_flip2=5))
    check("run --diag j1 reverts, most of them 1-2 bit flips, and no bad word or change: F34, and no writer-none",
          j6_is(r, "complete", ["F34"]))
    r = j6(c2w(revert=6, revert_flip2=3))
    check("run --diag j1 reverts not mostly 1-2 bit flips: neither F34 nor writer-none", j6_is(r, "complete", ["no-row"]))
    r = j6(c2w(classes={"flip2_same": 6, "zero": 5, "other": 5}, changed_words=4, osc=4, writer="ongoing"))
    check("run --diag j1 flip2 dominant but not above half of bad: F34 (dominance, as the other rows read it)",
          j6_is(r, "complete", ["F34"]))
    r = j6(c2w(classes={"flip2_same": 12, "flip2_var": 4}, changed_words=20, osc=10, stable=10, writer="ongoing"))
    check("run --diag j1 osc with stable re-reads and flip2 dominant: F34 takes precedence over live-writer",
          j6_is(r, "complete", ["F34"]))
    r = j6(c2w(classes={"flip2_var": 1}, changed_words=600, changed_snaps=100, osc=600, healed=600, writer="ongoing"))
    check("run --diag j1 one toggling word with 600 heals on one page: F34, not restoring-writer",
          j6_is(r, "complete", ["F34"]))
    r = j6(c2w(classes={"other": 16}, stride=(16, 0, 0, 0, 0, 0, 0, 0)))
    check("run --diag j1 one dominant stride bin: ring-record", j6_is(r, "complete", ["ring-record", "writer-static"]))
    r = j6(c2w(classes={"other": 16}))
    check("run --diag j1 spread stride bins and other dominant: writer-static only",
          j6_is(r, "complete", ["writer-static"]))
    r = j6(c2w(classes={"other": 16}, writer="ongoing"))
    check("run --diag j1 no change in the snapshots but writer=ongoing (memcanary-w's final read differed): "
          "consistent, and neither writer-none nor writer-static", j6_is(r, "complete", ["no-row"]))
    r = j6(c2w(classes={"pte": 10, "kva": 6}))
    check("run --diag j1 pte dominant: qnx-shaped", j6_is(r, "complete", ["qnx-shaped", "writer-static"]))
    r = j6({"a": {"classes": {"other": 16}, "sig": {"ipv4": 1}}, "b": other16, "c": other16})
    check("run --diag j1 a positive signature: positive-signature",
          j6_is(r, "complete", ["positive-signature", "writer-static"]))
    fill = {"a": other16, "b": {"classes": {"other": 16}, "changed_words": 10, "osc": 10},
            "c": {"classes": {"other": 16}, "changed_words": 100, "osc": 100}}
    r = j6(fill)
    check("run --diag j1 label c's change rate above factor 2 times label b's: fill-rate",
          j6_is(r, "complete", ["fill-rate"]) and field(r, "fillrate").startswith("'differs "))
    r = j6(fill, factor="10")
    check("run --diag j1 a rate exactly the factor times the other is within: no-row",
          j6_is(r, "complete", ["no-row"]) and field(r, "fillrate").startswith("'within "))
    r = j6(dict(fill, c={"classes": {"other": 16}, "changed_words": 15, "osc": 15}))
    check("run --diag j1 rates within the factor: no-row", j6_is(r, "complete", ["no-row"]))
    r = j6(dict(fill, b=other16, c={"classes": {"other": 16}, "changed_words": FILL_MIN_WORDS - 1,
                                    "osc": FILL_MIN_WORDS - 1}))
    check("run --diag j1 a rate against a zero one, under FILL_MIN_WORDS change events: below-floor, no row",
          j6_is(r, "complete", ["no-row"]) and field(r, "fillrate").startswith("'below-floor "))
    r = j6(dict(fill, b=other16, c={"classes": {"other": 16}, "changed_words": FILL_MIN_WORDS, "osc": FILL_MIN_WORDS}))
    check("run --diag j1 a rate against a zero one at FILL_MIN_WORDS change events: fill-rate",
          j6_is(r, "complete", ["fill-rate"]) and field(r, "fillrate").startswith("'differs "))
    r = j6(hold=("fill=ok", "verify=bad first_off=0x28 words=2"))
    check("run --diag j1 the hold's verify=bad: F49, still complete",
          j6_is(r, "complete", ["F49", "writer-none"]) and field(r, "hold") == "bad")
    r = j6({"d": {"classes": {"zero": 16}}})
    check("run --diag j1 a c1 watch with bad above 0: F39", j6_is(r, "complete", ["F39", "writer-none"]))
    j6l, j6bins = syn_j6_log(conf_bytes, cmdline)
    r = j6(lines_=sub_nth(j6l, c3_ok, bad("c3"), 1))
    check("run --diag j1 c3 bad at the end check: F39", j6_is(r, "complete", ["F39", "writer-none"]) and
          field(r, "c3_end") == "bad" and field(r, "c3_start") == "ok")
    fail_c = ((r"^S1 CANARY c2 watch=\S+ label=c ",),
              ((rf"^S1 ALLOC hold mib={J1_HOLD_MIB} fill=ok$",
                "S1 CANARY c2 watch=fail label=c reason=nomem errno=12"),))
    r = j6(lines_=edit_lines(j6l, drop=fail_c[0], add_after=fail_c[1]))
    check("run --diag j1 watch=fail: incomplete, F40", j6_is(r, "incomplete", ["F40"], ("watch_c", "export_j1c")) and
          field(r, "watch_c") == "fail" and not has(r, "c2_sums="))
    fd, _ = syn_j6_log(conf_bytes, cmdline, watches={"d": {"classes": {"zero": 16}}})
    r = j6(lines_=edit_lines(fd, drop=fail_c[0], add_after=fail_c[1]))
    check("run --diag j1 a c1 watch bad in an incomplete parse is still F39", j6_is(r, "incomplete", ["F39", "F40"]))
    r = j6(hold=("map=fail errno=12", None))
    check("run --diag j1 the hold's map=fail (F28): incomplete, F40", j6_is(r, "incomplete", ["F40"], ("hold",)) and
          field(r, "hold") == "map-fail")
    r = j6(hold=("fill=ok", "verify=timeout data=bad first_off=0x0 words=1"))
    check("run --diag j1 a hold timeout with bad data: F49 and F40", j6_is(r, "incomplete", ["F49", "F40"], ("hold",))
          and field(r, "hold") == "timeout-bad")
    r = j6(hold_mib=1024)
    check("run --diag j1 a --hold-mib that differs: incomplete", j6_is(r, "incomplete", ["F40"], ("hold",)) and
          field(r, "hold") == "mib-differs" and field(r, "hold_mib_vs_pc") == "differs")
    r = j6(hold_mib=J1_HOLD_MIB)
    check("run --diag j1 a --hold-mib that matches", j6_is(r, "complete", ["writer-none"]) and
          field(r, "hold_mib_vs_pc") == "match")
    r = j6(lines_=syn_j6_log(conf_bytes, cmdline, hold_mib=2048)[0])
    check("run --diag j1 hold lines at another size than J1_HOLD_MIB, no --hold-mib: incomplete",
          j6_is(r, "incomplete", ["F40"], ("hold",)) and field(r, "hold") == "mib-differs" and
          field(r, "hold_mib_vs_pc") == "not_given")
    r = j6(lines_=syn_j6_log(conf_bytes, cmdline, mcw="")[0])
    check("run --diag j1 without the memcanary_w_sha256 stamp in S1 CONFIG: incomplete",
          j6_is(r, "incomplete", ["F40"], ("memcanary_w_sha256",)) and field(r, "memcanary_w_sha256") == "absent")
    r = j6(drop_exports=("b",))
    check("run --diag j1 a missing export: incomplete", j6_is(r, "incomplete", ["F40"], ("export_j1b",)) and
          field(r, "export_j1b") == "absent")
    r = j6(lines_=edit_lines(j6l, drop=(rf"^S1 ALLOC hold mib={J1_HOLD_MIB} fill=ok$",),
                             add_after=((r"^S1 CANARY c1 watch=verdict label=d ",
                                         f"S1 ALLOC hold mib={J1_HOLD_MIB} fill=ok"),)))
    check("run --diag j1 watches c and d before the hold's fill line: watch_order bad",
          j6_is(r, "incomplete", ["F40"], ("watch_order",)) and field(r, "watch_order") == "bad")
    r = j6(lines_=edit_lines(j6l, add_after=((rf"^S1 ALLOC hold mib={J1_HOLD_MIB} verify=ok$",
                                               "S1 ALLOC mib=1536 fill=ok verify=ok"),)))
    check("run --diag j1 B2's allocation line in the log: incomplete",
          j6_is(r, "incomplete", ["F40"], ("b2_alloc_line",)))
    r = j6(lines_=[ln.replace(f"T234 S1 {J1_RUNG} ", "T234 S1 s1-h1 ") for ln in j6l])
    check("run --diag j1 a procnto line naming another image: incomplete",
          j6_is(r, "incomplete", ["F40"], ("rung_j1",)))
    r = j6(lines_=edit_lines(j6l, drop=(r"s1wq: kexec issuing",)))
    check("run --diag j1 without the kexec issuing marker: incomplete",
          j6_is(r, "incomplete", ["F40"], ("wq_kexec_issuing",)))
    r = j6(lines_=edit_lines(j6l, add_after=((r"^S1 CANARY c2 watch=verdict label=a ",
                                               "S1 CANARY c2 refuse=in-sysram"),)))
    check("run --diag j1 a verify-form line between the checks: incomplete",
          j6_is(r, "incomplete", ["F40"], ("canary_between",)) and field(r, "canary_between") == "1")
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c2 watch=bytes label=b .*)$", r"\1 extra=1"),)))
    check("run --diag j1 a watch line with an extra field is malformed",
          j6_is(r, "incomplete", ["F40"], ("watch_b", "export_j1b")) and field(r, "watch_b") == "malformed")
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c2 watch=words label=a bad=)0 ", r"\g<1>5 "),)))
    check("run --diag j1 words' classes that do not sum to bad: inconsistent, and the export mismatches",
          j6_is(r, "incomplete", ["F40"], ("watch_a", "export_j1a")) and "words_sum" in field(r, "watch_a") and
          field(r, "watch_a").startswith("'inconsistent ") and "console-mismatch" in field(r, "export_j1a"))
    r = j6(lines_=edit_lines(j6l, add_after=((r"^S1 CANARY c2 watch=verdict label=a ",
                                               watch_line.replace("=a ", "=e ")),)))
    check("run --diag j1 a watch line outside the table's labels: incomplete",
          j6_is(r, "incomplete", ["F40"], ("watch_stray",)))
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c2 watch=time label=b .*) stop=count$", r"\1 stop=deadline"),)))
    check("run --diag j1 stop=deadline with snaps equal to count: the console stays consistent, but the export's "
          "stop (count) does not match it",
          j6_is(r, "incomplete", ["F40"], ("export_j1b",)) and field(r, "watch_b") == "ok" and
          "stop" in field(r, "export_j1b"))
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c2 watch=time label=a .*) stop=deadline$", r"\1 stop=count"),)))
    check("run --diag j1 stop=count with fewer snapshots than the count is inconsistent",
          j6_is(r, "incomplete", ["F40"], ("watch_a",)) and "time_snaps" in field(r, "watch_a"))
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c1 watch=verdict label=d .*) content=none$",
                                         r"\1 content=unclassified"),)))
    check("run --diag j1 content other than none on a watch with no bad word is inconsistent",
          j6_is(r, "incomplete", ["F40"], ("watch_d",)) and "verdict_content" in field(r, "watch_d"))
    r = j6(lines_=edit_lines(j6l, sub=((r"^(S1 CANARY c2 watch=reread label=b revert=0 revert_flip2=)0 ", r"\g<1>1 "),)))
    check("run --diag j1 revert_flip2 above revert is inconsistent (the export's tail has no reread count)",
          j6_is(r, "incomplete", ["F40"], ("watch_b",)) and "reread_counts" in field(r, "watch_b") and
          field(r, "export_j1b") == "ok")
    r = j6(c2w(classes={"other": 16}, changed_words=4, stable=2))
    check("run --diag j1 osc, prog and stable that do not sum to changed_words are inconsistent",
          j6_is(r, "incomplete", ["F40"], ("watch_a", "watch_b", "watch_c")) and "time_counts" in field(r, "watch_a"))
    r = j6(lines_=edit_lines(j6l, drop=(r"^S1 CANARY c2 watch=reread label=c ",)))
    check("run --diag j1 a watch without its reread line is incomplete",
          j6_is(r, "incomplete", ["F40"], ("watch_c",)) and field(r, "watch_c") == "incomplete")

    # kpf-decode.py headers: c2's first 16 pages as slab (held) or free, for cpu-side.
    K = _kpf()
    kd = tempfile.mkdtemp(prefix="s1pc-j6-")
    try:
        def kpf_hdr(tag, flags, uptime):
            snap = K._Snap()
            snap.set("w2", 0, 16, flags)
            fb, cb = snap.blobs()
            stem = f"{tag}-{flags:x}"
            for suffix, blob in (("flags", fb), ("count", cb)):
                with open(os.path.join(kd, f"{stem}.{suffix}.bin"), "wb") as fh:
                    fh.write(blob)
            p = os.path.join(kd, f"{stem}.hdr")
            with open(p, "w", encoding="ascii", newline="\n") as fh:
                fh.write(K._header_text(tag, K.FIX_BOOT, uptime, f"{stem}.flags.bin", sha256(fb), f"{stem}.count.bin",
                                        sha256(cb)))
            return p

        pre_held, pre_free = kpf_hdr("prequiesce", 1 << 7, "100.25"), kpf_hdr("prequiesce", 0, "100.5")
        post_held = kpf_hdr("postquiesce", 1 << 7, "240.5")
        cpu = c2w(classes={"ptr_ram": 16})
        r = j6(cpu)
        check("run --diag j1 ptr_ram dominant without --kpf: cpu-side-lean",
              j6_is(r, "complete", ["cpu-side-lean", "writer-static"]) and
              field(r, "coincide").startswith("'not-computed"))
        r = j6(cpu, kpf=(pre_held,))
        check("run --diag j1 with a prequiesce header holding those pages: cpu-side",
              j6_is(r, "complete", ["cpu-side", "writer-static"]) and field(r, "kpf") == "ok" and
              field(r, "coincide").startswith("'yes "))
        r = j6(cpu, kpf=(pre_held, post_held))
        check("run --diag j1 with a prequiesce and postquiesce pair: cpu-side",
              j6_is(r, "complete", ["cpu-side", "writer-static"]))
        r = j6(cpu, kpf=(pre_free,))
        check("run --diag j1 with those pages free before the quiesce: no cpu-side row",
              j6_is(r, "complete", ["writer-static"]) and field(r, "coincide").startswith("'no "))
        r = j6(cpu, kpf=(post_held,))
        check("run --diag j1 with a postquiesce header only: cpu-side-lean",
              j6_is(r, "complete", ["cpu-side-lean", "writer-static"]))
        r = j6(cpu, kpf=(os.path.join(kd, "absent.hdr"),))
        check("run --diag j1 a kpf refusal is recorded and never makes the parse incomplete",
              j6_is(r, "complete", ["cpu-side-lean", "writer-static"]) and
              field(r, "kpf") == "'refused reason=header-missing'")
        r = j6(cpu, kpf=(pre_held, pre_free))
        check("run --diag j1 two prequiesce headers are kpf-decode's tag refusal",
              j6_is(r, "complete", ["cpu-side-lean", "writer-static"]) and field(r, "kpf") == "'refused reason=tag'")
        check("run --diag j1 no J6 parse prints a b2= field, verdict=pass, or pass on any line but conf_gate's",
              len(j6res) == 59 and all(not has(x, "b2=") and not any("verdict=pass" in ln for ln in x["lines"]) and
                                       all(ln.startswith("conf_gate=") for ln in x["lines"]
                                           if re.search(r"=pass\b", ln)) for x in j6res))

        # the export structure: accepted, then each malformation refused by name
        _, good = syn_watch("b", classes={"other": 16}, changed_words=4, stable=2, healed=1)
        fx, reason, _ = cw_decode(good, "b")
        check("canwatch a synthetic export is accepted", reason is None and len(good) == CW_SIZE == 1632 and
              fx["snaps"] == 180 and fx["tail"]["bad_final"] == 16 and _pop(fx["maps"]["changed_ever"]) == 1)

        def patched(off, new):
            return good[:off] + new + good[off + len(new):]

        tail_off = CW_HEAD.size + len(CW_MAPS) * CW_MAP_BYTES
        bad_exports = (
            ("short", good[:90], "b"), ("magic", patched(0, b"S1J1XXXX"), "b"),
            ("version", patched(8, struct.pack("<I", 2)), "b"),
            ("page-count", patched(32, struct.pack("<I", 4095)), "b"),
            ("size", good + b"\0", "b"), ("size", good[:-8], "b"), ("name", patched(12, b"c1\0\0"), "b"),
            ("name", patched(12, b"c2\0x"), "b"), ("label", good, "c"), ("label", patched(16, b"bb\0\0\0\0\0\0"), "b"),
            ("base", patched(24, struct.pack("<Q", CANARIES["c2"] + WPAGE)), "b"),
            ("reserved", patched(63, b"\1"), "b"),
            ("interval", patched(36, struct.pack("<I", 500)), "b"),
            ("request", patched(44, struct.pack("<I", 179)), "b"), ("request", patched(48, struct.pack("<I", 191)), "b"),
            ("request", patched(52, struct.pack("<I", 3)), "b"),
            ("snaps", patched(40, struct.pack("<I", 181)), "b"),
            ("counts", patched(40, struct.pack("<I", 179)), "b"),
            ("counts", patched(tail_off + 16, struct.pack("<Q", 0)), "b"),
            ("counts", patched(CW_HEAD.size, bytes(CW_MAP_BYTES)), "b"),
            ("counts", patched(tail_off + 8, struct.pack("<Q", 5000)), "b"),
            ("healed-not-changed", patched(CW_HEAD.size + 2 * CW_MAP_BYTES, b"\2"), "b"))
        for want, blob, label in bad_exports:
            got = cw_decode(blob, label)
            check(f"canwatch refuses an export by name: {want}", got[0] is None and got[1] == want)
        check("canwatch every structure reason is exercised",
              {w for w, _, _ in bad_exports} == set(CW_REASONS) - {"console-absent", "console-mismatch"})

        # the analyzer on its own: the log's records against the files
        jrecs, jblocks, _, _ = split_log(("\n".join(j6l) + "\n").encode("latin-1"))
        for blk in jblocks:
            decode_block(blk)
        JR = Recs(jrecs)
        jlabs, _ = cw_watches(JR)
        jlog_recs = cw_log_records(JR, jblocks)
        cwr = cw_analyze(jlabs, j6bins, Fraction(2), (), jlog_recs)
        check("canwatch analyzer on the synthetic J6 log: complete, every file matches its log record",
              cwr["lines"][-1] == "result=complete" and
              sum("bin_vs_log=match" in ln for ln in cwr["lines"] if ln.startswith("watch ")) == 4)
        _, alt_b = syn_watch("b", changed_words=4, stable=4)
        cwr = cw_analyze(jlabs, dict(j6bins, b=alt_b), Fraction(2), (), jlog_recs)
        check("canwatch a file whose counts differ from the console: console-mismatch and bin_vs_log differs",
              "export_j1b" in cwr["failed"] and "bin_vs_log_j1b" in cwr["failed"] and
              cwr["export"]["b"].startswith("refused reason=console-mismatch fields=") and
              "changed_words" in cwr["export"]["b"])
        nod = cw_watches(Recs([(i, t) for i, t in jrecs if " label=d " not in t]))[0]
        cwr = cw_analyze(nod, j6bins, Fraction(2))
        check("canwatch an export with no console watch: console-absent",
              cwr["export"]["d"] == "refused reason=console-absent" and "watch_d" in cwr["failed"])

        # the command end to end, files in a temporary directory (no git-ignore query outside the repository)
        cwlog = os.path.join(kd, "j6-com3.log")
        cpul, cpubins = syn_j6_log(conf_bytes, cmdline, watches=cpu)
        with open(cwlog, "wb") as fh:
            fh.write(("\n".join(cpul) + "\n").encode("latin-1"))
        for l, blob in cpubins.items():
            with open(os.path.join(kd, export_filename(f"j1{l}")), "wb") as fh:
                fh.write(blob)

        def cwcmd(**kw):
            ns = dict(log=cwlog, fill_factor="2", bin_dir=None, kpf=[pre_held], out_dir="none")
            ns.update(kw)
            b = io.StringIO()
            with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
                rc_ = cmd_canwatch(argparse.Namespace(**ns))
            return rc_, b.getvalue()

        rc, cwtext = cwcmd()
        check("canwatch cmd: exit 0, complete, bitmaps, kpf page classes, coincide yes, fill-rate within, limit",
              rc == 0 and cwtext.endswith("S1CW result=complete\n") and f"S1CW limit: {CW_LIMIT}\n" in cwtext and
              cwtext.count("S1CW bitmap ") == 12 and cwtext.count("S1CW kpf tag=prequiesce ") == 12 and
              "S1CW kpf result=ok tags=prequiesce\n" in cwtext and "S1CW coincide result=yes " in cwtext and
              "S1CW fillrate result=within " in cwtext and "S1CW fill_factor=2\n" in cwtext)
        cwtexts = [cwtext]
        wrote = write_canwatch(os.path.join(kd, "cwout"), cwtext, check=False)
        with open(wrote, "rb") as fh:
            check("canwatch writes canwatch.txt", os.path.basename(wrote) == "canwatch.txt" and
                  fh.read() == cwtext.encode("utf-8"))
        check("canwatch cmd a factor below 1 is a usage error", cwcmd(fill_factor="0.9")[0] == 2)
        check("canwatch cmd a factor that is not a decimal is a usage error", cwcmd(fill_factor="2x")[0] == 2)
        check("canwatch cmd three --kpf headers are a usage error", cwcmd(kpf=[pre_held, post_held, pre_free])[0] == 2)
        rc, t_ = cwcmd(kpf=None)
        cwtexts.append(t_)
        check("canwatch cmd without --kpf: coincide not computed, still complete",
              rc == 0 and "S1CW kpf result=not-given\n" in t_ and
              "S1CW coincide result=not-computed reason=no-kpf" in t_ and t_.endswith("S1CW result=complete\n"))
        _, alt_c = syn_watch("c", changed_words=4, stable=4)
        with open(os.path.join(kd, export_filename("j1c")), "wb") as fh:
            fh.write(alt_c)
        os.remove(os.path.join(kd, export_filename("j1d")))
        rc, t_ = cwcmd()
        cwtexts.append(t_)
        check("canwatch cmd a file that differs from LOG's record, and a missing file: incomplete",
              rc == 0 and "bin_vs_log=differs" in t_ and "input_bin label=d " in t_ and
              t_.rstrip("\n").split("\n")[-1].startswith("S1CW result=incomplete failed=") and
              all(x in t_.rstrip("\n").split("\n")[-1] for x in ("bin_vs_log_j1c", "export_j1c", "export_j1d")))
        value_hex = re.compile(r"(?<![0-9A-Fa-f])(?:0[xX])?[0-9A-Fa-f]{16}(?![0-9A-Fa-f])")
        quad = re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9.])")
        mac = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f])")
        check("canwatch the value-token screens catch their planted positives",
              value_hex.search("x=0x0123456789abcdef") and quad.search("at 192.0.2.1 ") and
              mac.search("02:00:5e:10:00:01"))
        check("canwatch and J6 output hold no 16-hex-digit value token, dotted quad or MAC pattern",
              not any(rx.search(t) for rx in (value_hex, quad, mac)
                      for t in cwtexts + ["\n".join(x["lines"]) for x in j6res]))

        # run cmd --diag j1: the report head and the usage errors
        j6log, j6bb = os.path.join(kd, "j6-run.log"), os.path.join(kd, "j6-blackbox.log")
        with open(j6log, "wb") as fh:
            fh.write(("\n".join(j6l) + "\n").encode("latin-1"))
        with open(j6bb, "wb") as fh:
            fh.write(syn_blackbox(j6l))

        def j6cmd(**kw):
            ns = dict(log=j6log, profile="board", mode="host", blackbox=j6bb, out_dir="none", conf=None,
                      ref_conf_sha256=None, reset_reason="MAINSWRST", kexec_tree_sha256=SYN_KEXEC, image=None,
                      initrd=None, diag="j1", arm="control", fill_factor="2", hold_mib=None, kpf=None)
            ns.update(kw)
            b = io.StringIO()
            with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
                rc_ = cmd_run(argparse.Namespace(**ns))
            return rc_, b.getvalue()

        rc, jt = j6cmd(kpf=[pre_held], hold_mib=J1_HOLD_MIB)
        check("run cmd --diag j1 prints its inputs, arm, step J6c and the diagnostic verdict last, exit 0",
              rc == 0 and "S1PC fill_factor=2\n" in jt and f"S1PC hold_mib={J1_HOLD_MIB}\n" in jt and
              "S1PC input_kpf=" in jt and
              "S1PC profile=board mode=host diag=j1 arm=control\n" in jt and "S1PC step=J6c\n" in jt and
              "S1PC j_row=writer-none\n" in jt and jt.endswith("S1PC verdict=diagnostic complete\n") and
              "S1PC b2=" not in jt)
        for label, kw in (("without --arm", {"arm": None}), ("without --fill-factor", {"fill_factor": None}),
                          ("with a factor below 1", {"fill_factor": "0.5"}),
                          ("with three --kpf headers", {"kpf": [pre_held, post_held, pre_free]}),
                          ("with --mode boot", {"mode": "boot"}),
                          ("on a TCG dryrun with --arm", {"profile": "tcg", "mode": "dryrun"}),
                          ("--arm with --diag j2", {"diag": "j2"}),
                          ("--kpf without --diag",
                           {"diag": None, "arm": None, "fill_factor": None, "kpf": [pre_held]})):
            check(f"run cmd --diag j1 {label} is a usage error", j6cmd(**kw)[0] == 2)
    finally:
        shutil.rmtree(kd, ignore_errors=True)

    # T-J1: the TCG j1 variant's dryrun with memcanary-w's self-test (§15.5 B8.5)
    t1_plain = syn_log("tcg", "dryrun", dtb, conf_bytes, cmdline)
    t1l = edit_lines(t1_plain, sub=((r"^(S1 CONFIG .*)$", rf"\1 memcanary_w_sha256={SYN_MCW}"),))
    cw_pass = "MEMCANARY-W SELFTEST PASS 120 checks"
    tjres = []

    def tj(lines_):
        res = run("tcg", "dryrun", lines_, diag="j1")
        tjres.append(res)
        return res

    def with_line(*extra):
        return edit_lines(t1l, add_after=tuple((r"^S1 GATE mem ok$", x) for x in extra))

    cw_pair = (cw_pass, "MEMCANARY SELFTEST PASS 170 checks")   # memcanary-w's two lines, as it prints them
    r = tj(with_line(*cw_pair))
    check("run --diag j1 T-J1 synthetic: complete, step T-J1, cw_selftest ok, no item1_t1 pass",
          r["verdict"] == "diagnostic complete" and r["step"] == "T-J1" and field(r, "cw_selftest") == "ok" and
          r["lines"][-1] == "verdict=diagnostic complete" and not has(r, "item1_t1=") and "j_row" not in r)
    r = tj(with_line("MEMCANARY SELFTEST PASS 47 checks", *cw_pair))
    check("run --diag j1 T-J1 memcanary's own line before the watcher's, then the pair: ok",
          field(r, "cw_selftest") == "ok")
    r = tj(with_line("MEMCANARY SELFTEST PASS 47 checks", cw_pass))
    check("run --diag j1 T-J1 the watcher's PASS with no line after it: unpaired, incomplete",
          field(r, "cw_selftest") == "unpaired" and r["verdict"] == "diagnostic incomplete")
    r = tj(with_line(cw_pass, "MEMCANARY SELFTEST FAIL 1 of 170 checks"))
    check("run --diag j1 T-J1 the watcher's PASS then memcanary's own FAIL (a base check failed): failed",
          field(r, "cw_selftest") == "failed" and r["verdict"] == "diagnostic incomplete")
    r = tj(with_line(cw_pass, "MEMCANARY SELFTEST PASS 120 checks"))
    check("run --diag j1 T-J1 a second PASS that does not count more than the watcher's: failed",
          field(r, "cw_selftest") == "failed")
    r = tj(edit_lines(t1_plain, add_after=tuple((r"^S1 GATE mem ok$", x) for x in cw_pair)))
    check("run --diag j1 T-J1 without the memcanary_w_sha256 stamp: incomplete",
          r["verdict"] == "diagnostic incomplete" and field(r, "memcanary_w_sha256") == "absent" and
          r["lines"][-1] == "verdict=diagnostic incomplete failed=memcanary_w_sha256")
    r = tj(t1l)
    check("run --diag j1 T-J1 without the watcher's self-test line: incomplete",
          r["verdict"] == "diagnostic incomplete" and field(r, "cw_selftest") == "absent" and
          r["lines"][-1] == "verdict=diagnostic incomplete failed=cw_selftest")
    r = tj(with_line("MEMCANARY SELFTEST PASS 50 checks"))
    check("run --diag j1 T-J1 memcanary's own self-test line is not the watcher's",
          field(r, "cw_selftest") == "absent" and r["verdict"] == "diagnostic incomplete")
    r = tj(with_line("MEMCANARY-W SELFTEST FAIL 2 of 120 checks"))
    check("run --diag j1 T-J1 a FAIL line: incomplete", field(r, "cw_selftest") == "failed")
    r = tj(with_line("MEMCANARY-W SELFTEST PASS 0 checks"))
    check("run --diag j1 T-J1 a PASS of 0 checks: incomplete", field(r, "cw_selftest") == "failed")
    r = tj(with_line(cw_pass, "MEMCANARY-W SELFTEST FAIL 2 of 120 checks"))
    check("run --diag j1 T-J1 PASS and FAIL together: incomplete", field(r, "cw_selftest") == "multiple")
    r = tj(with_line(cw_pass, watch_line))
    check("run --diag j1 T-J1 a watch line under TCG fails profile: incomplete",
          r["verdict"] == "diagnostic incomplete" and "profile" in r["lines"][-1].split("failed=", 1)[-1].split(","))
    r = tj(edit_lines(with_line(cw_pass), sub=((r"logger_errors=0", "logger_errors=2"),)))
    check("run --diag j1 T-J1 a dryrun logger error fails L2: incomplete",
          "L2" in r["lines"][-1].split("failed=", 1)[-1].split(","))
    check("run --diag j1 no T-J1 parse prints verdict=pass or pass on any line but conf_gate's",
          len(tjres) == 13 and all(not any("verdict=pass" in ln for ln in x["lines"]) and
                                  all(ln.startswith("conf_gate=") for ln in x["lines"] if re.search(r"=pass\b", ln))
                                  for x in tjres))
    # ---- run --diag j1 --entry uefi and canwatch --entry uefi: J7a (s1-design.md §15.13.7, §15.13.10).
    # SYNTHETIC; not a record. J6's synthetic capture with its kexec markers removed and the loader's
    # Shell visit (m5load.c's lines, with CSI sequences) placed before the shim line.
    J7_LOADER = "b" * 64

    def syn_m5l(mode, *, variant=True, self_line="M5L self w2=no canary=none", crc32="1a2b3c4d",
                preclaims=("c1", "c2", "c3"), resmem_done=True, w2=True):
        L_ = [f"M5L start mode={mode} el=2 ctr=8444c004 self=ff000000+2000000"]
        if variant:
            L_.append("M5L variant=j7a")
        L_ += [self_line, "M5L fdt addr=fe000000 size=20000" + (f" crc32={crc32}" if crc32 else ""),
               "M5L con kind=tcu base=3c10000",
               "M5L resmem name=camdbg_carveout@100000000 status=disabled map=no-map prop=alloc-ranges over=c2 base=yes"]
        if resmem_done:
            L_.append("M5L resmem done")
        L_ += ["M5L crc src=ok", "M5L crc dst=ok"] + [f"M5L canary {c} preclaim=ok" for c in preclaims]
        L_.append("M5L map type=Conventional start=100000000 pages=8a000 attr=f")
        if w2:
            L_.append("M5L W2 PASS")
        return L_

    def syn_visit(check_=None, go_=None, after=("M5L-EBS ok", "M5L-JUMP")):
        v = ["\x1b[0m\x1b[2J\x1b[1;1HESC to enter Setup.", "F11 to enter Boot Manager Menu.",
             "\x1b[1;37;40mShell> \x1b[0mfs5:", "FS5:\\> M5LOAD.EFI check"]
        v += check_ if check_ is not None else syn_m5l("check") + ["M5L CHECK PASS"]
        v += ["FS5:\\> M5LOAD.EFI go"] + (go_ if go_ is not None else syn_m5l("go") + ["M5L GO"])
        return v + list(after)

    def syn_j7a(watches=None, hold=("fill=ok", "verify=ok"), visit=None, before=()):
        base, bins_ = syn_j6_log(conf_bytes, cmdline, watches=watches, hold=hold)
        base = [ln for ln in base if ln not in SYN_WQ_MARKS]
        return base[:1] + list(before) + (visit if visit is not None else syn_visit()) + base[1:], bins_

    j7res = []

    def j7(lines_=None, *, reset="MAINSWRST", loader=J7_LOADER, **kw):
        if lines_ is None:
            lines_ = syn_j7a(**kw)[0]
        data_ = ("\n".join(lines_) + "\n").encode("latin-1")
        res = analyze_run(data_, profile="board", mode="host", conf_bytes=conf_bytes, conf_info=info,
                          conf_gate_ok=True, bb_data=syn_blackbox(lines_), reset_reason=reset, diag="j1", arm="uefi",
                          fill_factor="4", entry="uefi", loader_sha256=loader)
        j7res.append(res)
        return res

    def j7_failed(res):
        last = res["lines"][-1]
        return last.split("failed=", 1)[1].split(",") if "failed=" in last else []

    r = j7()
    check("run --entry uefi synthetic J7a: complete, step J7a, j7a=clean, E-candidate, UEFI item 5, no kexec keys",
          r["verdict"] == "diagnostic complete" and r["step"] == "J7a" and r["j7a"] == "clean" and
          field(r, "j7a") == "clean" and field(r, "j7a_class") == "E-candidate" and field(r, "entry") == "uefi" and
          field(r, "loader_sha256") == J7_LOADER and field(r, "fdt_crc32") == "1a2b3c4d" and
          field(r, "kexec_tree_sha256") is None and field(r, "wq_kexec_issuing") == "n/a-uefi" and
          field(r, "wq_markers") == "none" and field(r, "kpf") == "not-applicable" and
          field(r, "conf_gate") == "ok" and field(r, "m5l_counted_go") == "one" and
          all(field(r, f"m5l_{n}") == "ok" for n in ("check_start", "check_run", "go_start", "go_run",
                                                     "prelude_same", "check_end", "fdt_crc32", "after_go",
                                                     "neg_after_go")) and
          field(r, "resmem_c2") == "camdbg_carveout" and field(r, "resmem_c2_base") == "yes" and
          field(r, "j7a_c3") == "clean" and field(r, "j7a_stop") == "none" and
          r["lines"][-1] == "verdict=diagnostic complete")
    for label, kw, want in (
            ("M5L variant=j7a", {"go_": syn_m5l("go", variant=False) + ["M5L GO"]}, "m5l_go_run"),
            ("M5L resmem done", {"check_": syn_m5l("check", resmem_done=False) + ["M5L CHECK PASS"],
                                 "go_": syn_m5l("go", resmem_done=False) + ["M5L GO"]}, "m5l_go_run"),
            ("M5L W2 PASS", {"go_": syn_m5l("go", w2=False) + ["M5L GO"]}, "m5l_go_run"),
            ("a preclaim=ok", {"go_": syn_m5l("go", preclaims=("c1", "c2")) + ["M5L GO"]}, "m5l_go_run"),
            ("M5L-EBS ok", {"after": ("M5L-JUMP",)}, "m5l_after_go"),
            ("the fdt stamp", {"check_": syn_m5l("check", crc32=None) + ["M5L CHECK PASS"],
                               "go_": syn_m5l("go", crc32=None) + ["M5L GO"]}, "m5l_fdt_crc32"),
            ("M5L CHECK PASS", {"check_": syn_m5l("check")}, "m5l_check_end")):
        r = j7(visit=syn_visit(**kw))
        check(f"run --entry uefi without {label}: incomplete, failed names {want}, j7a incomplete",
              r["verdict"] == "diagnostic incomplete" and want in j7_failed(r) and "incomplete" in r["j7a"].split(","))
    lj, _ = syn_j7a(visit=syn_visit(after=("M5L-EBS ok",)))
    lj = edit_lines(lj, add_after=((r"^T234-SHIM EL=2 ", "M5L-JUMP"),))
    r = j7(lj)
    check("run --entry uefi with M5L-JUMP after the shim line: incomplete (after_go)",
          r["verdict"] == "diagnostic incomplete" and "m5l_after_go" in j7_failed(r))
    r = j7(visit=syn_visit(go_=syn_m5l("go") + ["M5L GO", "M5L GO"]))
    check("run --entry uefi with two counted M5L GO lines: incomplete (counted_go multiple)",
          r["verdict"] == "diagnostic incomplete" and field(r, "m5l_counted_go") == "multiple" and
          "m5l_counted_go" in j7_failed(r))
    for neg in ("EXC ESR=0000000096000045", "M5L-EXC ESR=1", "kexec_core: Starting new kernel", "s1wq: begin arm=x"):
        lj, _ = syn_j7a()
        r = j7(edit_lines(lj, add_after=((r"^t234: WDT0 ", neg),)))
        check(f"run --entry uefi a negative token after GO ({neg.split()[0]}): incomplete",
              r["verdict"] == "diagnostic incomplete" and "m5l_neg_after_go" in j7_failed(r))
    lj, _ = syn_j7a(before=["EXC in firmware text before any go", "s1-looking text is unconstrained here"])
    r = j7(lj)
    check("run --entry uefi text before the counted GO is unconstrained (an EXC token there): complete",
          r["verdict"] == "diagnostic complete")
    first_visit = syn_visit(go_=syn_m5l("go") + ["M5L GO", "M5L REFUSE w2-final", "Shell> reset"], after=())
    r = j7(before=first_visit)
    check("run --entry uefi a GO refused by w2-final, then a counted GO in a new Shell visit: the later one only",
          r["verdict"] == "diagnostic complete" and field(r, "m5l_counted_go") == "one" and r["j7a"] == "clean")
    c2bad = "S1 CANARY c2 verify=bad first_off=0x0 words=1"
    lj, _ = syn_j7a()
    lj = edit_lines(sub_nth(lj, r"^S1 CANARY c2 verify=ok$", c2bad, 0), drop=(r"^S1 CANARY c2 watch=\S+ label=c ",))
    r = j7(lj)
    check("run --entry uefi a c2 verify=bad start check then a missing watch: bad-partial, K-w",
          r["verdict"] == "diagnostic incomplete" and r["j7a"] == "bad-partial,incomplete" and
          field(r, "j7a_class") == "K-w" and field(r, "j7a_c2") == "bad-partial")
    lj, _ = syn_j7a()
    lj = edit_lines(lj, drop=(r"^S1 CANARY c2 watch=\S+ label=c ",))
    r = j7(lj)
    check("run --entry uefi a missing watch with c2 clean at its checks: incomplete, U",
          r["j7a"] == "incomplete" and field(r, "j7a_class") == "U" and field(r, "j7a_c2") == "unread")
    bad_both = edit_lines(syn_j7a(watches=c2w(classes={"zero": 10, "kva": 6}))[0],
                          sub=((r"^S1 CANARY c2 verify=ok$", c2bad),))
    r = j7(bad_both)
    check("run --entry uefi complete with c2 bad: bad, K-w, the anchor and word facts for canwatch",
          r["verdict"] == "diagnostic complete" and r["j7a"] == "bad" and field(r, "j7a_class") == "K-w" and
          field(r, "c2_start_anchor") == "first-word" and field(r, "c2_check_words") == "start:1,end:1")
    r = j7(edit_lines(syn_j7a(watches=c2w(classes={"flip2_same": 12, "flip2_var": 4}, changed_words=20, osc=20,
                                          writer="ongoing"))[0], sub=((r"^S1 CANARY c2 verify=ok$", c2bad),)))
    check("run --entry uefi c2 bad with F34 on its watches: bad-unstable, K-r(u)",
          r["j7a"] == "bad-unstable" and field(r, "j7a_class") == "K-r(u)")
    r = j7(watches=c2w(revert=6, revert_flip2=5))
    check("run --entry uefi reverts only: revert-only, class none", r["j7a"] == "revert-only" and
          field(r, "j7a_class") == "none")
    r = j7(watches=c2w(classes={"other": 16}, bad_base=0, changed_words=2, prog=2, stable=0))
    check("run --entry uefi a prog-only c2 change with no stable re-read: unsettled (left to the owner)",
          r["verdict"] == "diagnostic complete" and r["j7a"] == "unsettled" and field(r, "j7a_class") == "unsettled")
    r = j7(watches={"d": {"classes": {"zero": 16}}})
    check("run --entry uefi a c1 watch bad: F39c1 (an immediate stop), no clean token, class U",
          r["j7a"] == "F39c1" and field(r, "j7a_class") == "U" and field(r, "j7a_stop") == "F39c1" and
          field(r, "j7a_c2") == "clean")
    r = j7(sub_nth(syn_j7a()[0], r"^S1 CANARY c3 verify=ok$", "S1 CANARY c3 verify=bad first_off=0x8 words=2", 1))
    check("run --entry uefi c3 bad with c2 clean: clean,F39c3, still E-candidate, c3=hit",
          r["j7a"] == "clean,F39c3" and field(r, "j7a_class") == "E-candidate" and field(r, "j7a_c3") == "hit")
    r = j7(hold=("fill=ok", "verify=bad first_off=0x28 words=2"))
    check("run --entry uefi the hold verify=bad: F49, no clean token, class U", r["j7a"] == "F49" and
          field(r, "j7a_stop") == "F49" and field(r, "j7a_class") == "U")
    no_reset = edit_lines(syn_j7a()[0], drop=(r"resetting so the log can be recovered", r"^ESC to enter Setup\.$",
                                              r"^F11 to enter", r"^Enter to continue"))
    r = j7(no_reset, reset="POR")
    check("run --entry uefi a reset that is not MAINSWRST after procnto up, before the reset line: F62, U",
          r["j7a"] == "incomplete,F62" and field(r, "j7a_class") == "U")
    r = j7(edit_lines(no_reset, sub=((r"^S1 CANARY c2 verify=ok$", c2bad),)), reset="POR")
    check("run --entry uefi F62 with c2 bad at a printed check: bad-partial, K-w",
          r["j7a"] == "bad-partial,incomplete,F62" and field(r, "j7a_class") == "K-w")
    r = j7(loader="")
    check("run --entry uefi without a loader sha256: item 5 refused", r["refused"] and
          field(r, "item5") == "refused missing=loader_sha256" and field(r, "loader_sha256") == "missing")
    for kw, why in (({"arm": "control"}, "--entry uefi with --arm control"), ({"entry": "kexec"}, "--arm uefi under kexec")):
        try:
            args_ = dict(profile="board", mode="host", conf_bytes=conf_bytes, conf_info=info, conf_gate_ok=True,
                         diag="j1", arm="uefi", fill_factor="4", entry="uefi", loader_sha256=J7_LOADER)
            args_.update(kw)
            analyze_run(b"", **args_)
            check(f"run {why} is an input error", False)
        except InputError:
            check(f"run {why} is an input error", True)
    kx, _ = syn_j6_log(conf_bytes, cmdline)
    kxd = ("\n".join(kx) + "\n").encode("latin-1")
    kxa = dict(profile="board", mode="host", conf_bytes=conf_bytes, conf_info=info, conf_gate_ok=True,
               bb_data=syn_blackbox(kx), reset_reason="MAINSWRST", kexec_tree_sha256=SYN_KEXEC, diag="j1",
               arm="control", fill_factor="2")
    check("run --entry kexec given explicitly prints exactly the default parse (R92)",
          analyze_run(kxd, **kxa)["lines"] == analyze_run(kxd, entry="kexec", **kxa)["lines"])

    # P7 on synthetic bitmaps: J6c's pages 0-9 in c2's first MiB; the share is at least half of each set
    j6pages = sum(1 << p for p in range(10))
    for label, pages, want in (("at the threshold (5 of 5 and 5 of 10)", range(5), True),
                               ("below it (4 of 10)", range(4), False),
                               ("above it (10 of 12 and 10 of 10)", range(12), True),
                               ("with a page in another MiB", list(range(5)) + [3 * 256], False)):
        got = p7_compare(sum(1 << p for p in pages), j6pages)
        check(f"canwatch P7 {label}: {'same' if want else 'differs'}", got[0] is want)
    check("canwatch P7 counts common, only-J7a and only-J6c pages", p7_compare(sum(1 << p for p in range(12)),
                                                                              j6pages)[1:4] == (10, 2, 0))

    # the command line: usage refusals, and canwatch's profile end to end in a temporary directory
    ud = tempfile.mkdtemp(prefix="s1pc-j7a-")
    try:
        def put_file(name, blob):
            p_ = os.path.join(ud, name)
            os.makedirs(os.path.dirname(p_), exist_ok=True)
            with open(p_, "wb") as fh:
                fh.write(blob)
            return p_

        j7log = put_file("j7a/com3.log", ("\n".join(bad_both) + "\n").encode("latin-1"))
        j7bb = put_file("j7a/blackbox.log", syn_blackbox(bad_both))

        def j7cmd(**kw):
            ns = dict(log=j7log, profile="board", mode="host", blackbox=j7bb, out_dir="none", conf=None,
                      ref_conf_sha256=None, reset_reason="MAINSWRST", kexec_tree_sha256=None, image=None, initrd=None,
                      diag="j1", arm="uefi", fill_factor="4", hold_mib=None, kpf=None, entry="uefi",
                      loader_sha256=J7_LOADER)
            ns.update(kw)
            b = io.StringIO()
            with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
                rc_ = cmd_run(argparse.Namespace(**ns))
            return rc_, b.getvalue()

        rc, j7text = j7cmd()
        check("run cmd --entry uefi: exit 0, head names entry=uefi and arm uefi, j7a=bad, verdict last",
              rc == 0 and "S1PC profile=board mode=host diag=j1 arm=uefi entry=uefi\n" in j7text and
              "S1PC j7a=bad\n" in j7text and "S1PC step=J7a\n" in j7text and
              j7text.endswith("S1PC verdict=diagnostic complete\n"))
        for label, kw in (("--arm uefi without --entry uefi", {"entry": None}),
                          ("--entry uefi without --loader-sha256", {"loader_sha256": None}),
                          ("--entry uefi with a short --loader-sha256", {"loader_sha256": "b" * 63}),
                          ("--entry uefi with --kpf", {"kpf": [j7bb]}),
                          ("--entry uefi with --kexec-tree-sha256", {"kexec_tree_sha256": SYN_KEXEC}),
                          ("--entry uefi with --arm control", {"arm": "control"}),
                          ("--entry uefi with --diag j2", {"diag": "j2", "arm": None}),
                          ("--loader-sha256 under kexec", {"entry": None, "arm": "control"})):
            check(f"run cmd {label} is a usage error", j7cmd(**kw)[0] == 2)
        j7parse = put_file("j7a/parse-s1.txt", j7text.encode("utf-8"))
        _, j7bins = syn_j7a(watches=c2w(classes={"zero": 10, "kva": 6}))
        for l, blob in j7bins.items():
            put_file(f"j7a/{export_filename('j1' + l)}", blob)
        # J6c's reference: the same watcher lay-down under kexec, its parse, a canwatch file and the exports
        k6 = edit_lines(syn_j6_log(conf_bytes, cmdline, watches=c2w(classes={"zero": 10, "kva": 6}))[0],
                        sub=((r"^S1 CANARY c2 verify=ok$", c2bad),))
        k6d = ("\n".join(k6) + "\n").encode("latin-1")
        k6res = analyze_run(k6d, **dict(kxa, bb_data=syn_blackbox(k6)))
        put_file("j6c/parse-s1.txt", run_report(os.path.join(ud, "j6c", "com3.log"), k6d, None, None, DEFAULT_CONF,
                                                conf_bytes, allow_text.encode("latin-1"), k6res, "board",
                                                "host").encode("utf-8"))
        put_file("j6c/canwatch.txt", b"S1CW result=complete\n")
        k6bins = syn_j6_log(conf_bytes, cmdline, watches=c2w(classes={"zero": 10, "kva": 6}))[1]
        for l in WATCH_C2:
            put_file(f"j6c/s1-j1{l}.bin", k6bins[l])
        refdir = os.path.join(ud, "j6c")
        pairs = [f"{n}={sha256(PM.read_bytes(os.path.join(refdir, n)))}" for n in J6C_REF_FILES]

        def cwu(**kw):
            ns = dict(log=j7log, fill_factor="4", bin_dir=os.path.join(ud, "j7a"), kpf=None, out_dir="none",
                      entry="uefi", ref_j6c=refdir, ref_sha256=pairs, run_parse=j7parse)
            ns.update(kw)
            b = io.StringIO()
            with contextlib.redirect_stdout(b), contextlib.redirect_stderr(io.StringIO()):
                rc_ = cmd_canwatch(argparse.Namespace(**ns))
            return rc_, b.getvalue()

        rc, cwt = cwu()
        check("canwatch --entry uefi on a bad run with J6c's lay-down: anchored, profile same, kpf not-applicable, "
              "no coincide line, result last",
              rc == 0 and "S1CW kw_sub=anchored\n" in cwt and "S1CW profile_vs_j6c=same\n" in cwt and
              "S1CW profile_na=none\n" in cwt and "S1CW kpf result=not-applicable\n" in cwt and
              "S1CW coincide" not in cwt and cwt.count("S1CW profile item=") == 7 and
              "S1CW p7 map=bad_final result=same " in cwt and "S1CW entry=uefi\n" in cwt and
              cwt.endswith("S1CW result=complete\n"))
        cwtexts_u = [cwt]
        moved = syn_j7a(watches={"a": {"classes": {"zero": 10, "kva": 6}, "bad_pages": (3 * 256,)},
                                 "b": {"classes": {"zero": 10, "kva": 6}}, "c": {"classes": {"zero": 10, "kva": 6}}})
        put_file("j7a/s1-j1a.bin", moved[1]["a"])
        mlines = edit_lines(moved[0], sub=((r"^S1 CANARY c2 verify=ok$", c2bad),))
        j7log2 = put_file("j7a/com3-moved.log", ("\n".join(mlines) + "\n").encode("latin-1"))
        _, mtext = j7cmd(log=j7log2, blackbox=put_file("j7a/bb-moved.log", syn_blackbox(mlines)))
        rc, cwt = cwu(log=j7log2, run_parse=put_file("j7a/parse-moved.txt", mtext.encode("utf-8")))
        cwtexts_u.append(cwt)
        check("canwatch --entry uefi on a bad run with a different page set: P7 differs, kw_sub differs",
              rc == 0 and "S1CW profile item=P7 result=differs\n" in cwt and "S1CW kw_sub=differs\n" in cwt and
              "S1CW profile_vs_j6c=differs:P7\n" in cwt)
        for l, blob in j7bins.items():
            put_file(f"j7a/{export_filename('j1' + l)}", blob)
        clean_lines = syn_j7a()[0]
        j7log3 = put_file("j7a/com3-clean.log", ("\n".join(clean_lines) + "\n").encode("latin-1"))
        _, ctext = j7cmd(log=j7log3, blackbox=put_file("j7a/bb-clean.log", syn_blackbox(clean_lines)))
        for l, blob in syn_j7a()[1].items():
            put_file(f"j7a/{export_filename('j1' + l)}", blob)
        rc, cwt = cwu(log=j7log3, run_parse=put_file("j7a/parse-clean.txt", ctext.encode("utf-8")))
        cwtexts_u.append(cwt)
        check("canwatch --entry uefi on a clean run: no profile, kw_sub not printed",
              rc == 0 and "S1CW profile=not-computed reason=reading-not-bad j7a=clean\n" in cwt and "kw_sub" not in cwt)
        for label, kw in (("with --kpf", {"kpf": [j7bb]}), ("without --ref-j6c", {"ref_j6c": None}),
                          ("without --run-parse", {"run_parse": None}),
                          ("--ref-j6c under kexec", {"entry": None})):
            check(f"canwatch {label} is a usage error", cwu(**kw)[0] == 2)
        for label, kw in (("a reference file that does not match its registered sha256",
                           {"ref_sha256": [p if not p.startswith("canwatch.txt=") else "canwatch.txt=" + "0" * 64
                                           for p in pairs]}),
                          ("a missing --ref-sha256 pair", {"ref_sha256": pairs[:-1]}),
                          ("a run parse of another log", {"log": j7log3})):
            try:
                cwu(**kw)
                check(f"canwatch --entry uefi refuses {label}", False)
            except Refused:
                check(f"canwatch --entry uefi refuses {label}", True)
        b = io.StringIO()
        with contextlib.redirect_stdout(b):
            rc = cmd_j6c_refs(argparse.Namespace(dir=refdir))
        check("j6c-refs prints the five registered names with their sha256",
              rc == 0 and b.getvalue().count("S1REF file=") == 5 and all(f"S1REF {p.replace('=', ' sha256=', 1)}"
                                                                         .replace("S1REF ", "S1REF file=", 1) in
                                                                         b.getvalue() for p in pairs))
        value_hex = re.compile(r"(?<![0-9A-Fa-f])(?:0[xX])?[0-9A-Fa-f]{16}(?![0-9A-Fa-f])")
        quad = re.compile(r"(?<![0-9.])[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?![0-9.])")
        mac = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f])")
        outs = ["\n".join(x["lines"]) for x in j7res] + cwtexts_u
        check("run --entry uefi screens cover every synthetic J7a parse", len(j7res) == 28 and len(cwtexts_u) == 3)
        for label, bad_ in (("the word pass", lambda t: re.search(r"pass", t, re.IGNORECASE)),
                            # the b2= verdict field is a line of its own (c2_sums' stride bins b0=..b7= are not it)
                            ("a b2= field", lambda t: re.search(r"(?m)^(?:S1PC |S1CW )?b2=", t)),
                            ("a 16-hex-digit value", value_hex.search),
                            ("a dotted quad", quad.search), ("a MAC form", mac.search)):
            check(f"run --entry uefi and canwatch --entry uefi print no {label}", not any(bad_(t) for t in outs))
    finally:
        shutil.rmtree(ud, ignore_errors=True)

    r = run("board", "boot")
    check("run B3 synthetic passes", r["verdict"] == "pass" and r["step"] == "B3" and has(r, "item2=pass") and
          has(r, "tier_L7=ok") and has(r, "bb_consistent=yes"))
    r = run("board", "boot", qvmlog=diag)
    check("run B3 with a qvm diagnostic in qvmlog fails item 2", r["verdict"] == "fail" and has(r, "item2=fail") and
          "dryrun_qvm_diagnostics" in tier(r, "L2"))
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
              "s1con -O -R -i /dev/ttyp3 -o \"$S/hvc0\" -w 'i_ready=echo S1-SHELL-$((40+2))-OK' &",
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
    r.add_argument("--diag", choices=DIAG_CHOICES,
                   help="J diagnostic parse: j2|j2b|j4 of B2's image (15.5 A3), j1 of s1-j1 or T-J1 (15.5 B7)")
    r.add_argument("--arm", choices=J1_ARMS + (J7A_ARM,),
                   help="--diag j1 on the board: jrun's arm (J6c or J6r), or uefi with --entry uefi (J7a)")
    r.add_argument("--fill-factor", help="--diag j1 on the board: the pre-registered fill-rate factor (>= 1)")
    r.add_argument("--hold-mib", type=int, help="--diag j1 on the board: the generator's @J1_HOLD_MIB@")
    r.add_argument("--kpf", action="append", help="--diag j1 on the board: a kpf-decode.py header (at most two)")
    r.add_argument("--entry", choices=ENTRIES, default=None,
                   help="kexec (the default) or uefi: J7a's segment, with --diag j1 --arm uefi (15.13.7)")
    r.add_argument("--loader-sha256", help="--entry uefi: the staged loader's sha256 (item 5 under UEFI entry)")

    w = sub.add_parser("canwatch")
    w.add_argument("log")
    w.add_argument("--fill-factor", required=True)
    w.add_argument("--bin-dir")
    w.add_argument("--kpf", action="append")
    w.add_argument("--out-dir")
    w.add_argument("--entry", choices=ENTRIES, default=None, help="kexec (the default) or uefi (J7a, 15.13.7)")
    w.add_argument("--ref-j6c", help="--entry uefi: J6c's record directory (the reference profile)")
    w.add_argument("--ref-sha256", action="append",
                   help="--entry uefi: NAME=HEX, J6c's registered sha256 of each of " + ", ".join(J6C_REF_FILES))
    w.add_argument("--run-parse", help="--entry uefi: this J7a run's parse-s1.txt (its reading)")

    j = sub.add_parser("j6c-refs")
    j.add_argument("dir")

    k = sub.add_parser("kshcheck")
    k.add_argument("file", nargs="?")
    k.add_argument("--selftest", action="store_true")

    a = ap.parse_args(argv)
    if a.all_selftest:
        return selftest()
    if not a.cmd:
        ap.print_usage(sys.stderr)
        return 2
    handlers = {"conf": cmd_conf, "fdt": cmd_fdt, "run": cmd_run, "canwatch": cmd_canwatch, "kshcheck": cmd_kshcheck,
                "j6c-refs": cmd_j6c_refs}
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
