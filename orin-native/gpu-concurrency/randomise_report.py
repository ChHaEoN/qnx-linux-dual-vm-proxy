#!/usr/bin/env python3
"""randomise_report.py -- run-randomise.sh's analysis (Phase 3b / A6, 2026-10-17), by the rules its
header fixed before any run: the A6 setup randomisation.

  randomise_report.py --schedule FILE B1 B2 B3 B4 B5 B6   the six scored board boots: checks, verdicts,
                                                          the unscored sections
  randomise_report.py --one --schedule FILE BOOTDIR       one board boot (the smoke b0 included): its
                                                          rounds and checks, never scored

WHAT IT READS. A board boot's directory, named by its tag, as the harness writes it:
  boot.json      the board boot: boot_tag, kind, pattern, schedule_sha256, reset_reason, pstore
                 {sys, archive}, first_reads, uptime_first_vm_s, cmdline_tokens, emc_first {bpmp, ccf},
                 boot_id, hooks (every path the host was read through, and TEGRA), complete (true,
                 written last, once the restores were judged)
  logins.txt     "v<n> r<k> accepted=N", one line per round
  v<n>/          one VM boot:
    stamp.json   lib-measure.sh's stamp, with s_regime, qemu_pin, qemu_pad and schedule_sha256
    order.log    "round <k> cell=<cell> order: A B C D"
    readback.log "<qemu|mon-host|mon-ns|probe-A..D> r<k|-> pid=N personality=HEX environ=N
                  startstack=N maps=... stack=... t_ms=N", one line per launch
    threads.log  "round <k> before|after tid=N last=C allowed=LIST comm=NAME", every QEMU thread
    cpu.log      "round <k> after-<arm> tid=N last=C allowed=LIST comm=NAME", between arm-rounds
    confine.log  "round <k> before|after udevd=LIST pid1=LIST shells=LIST;LIST|none"
    emc.log      "round <k> after-<arm> bpmp=HZ ccf=HZ"
    halt.log     "start <halt_poll_ns and companions>", "end <the same>"
    gpu.log      "start <GR3D %>", "end <GR3D %>"
    lat-<arm>_r<k>.json and kvm-<arm>_r<k>.json for the scored rounds; _s0 for the settling round
                 (the KVM snapshot's per-thread schedstat run_ns, before and after the arm-round, says
                 which threads ran in it: M4 and U5 read it)

THE RULES (the header's sections 5 to 7, applied here to the letter):
  per round   K1 = C - B, K2 = D - C, K3 = B - A, Lv = p50(D), the floor p50(A), from the p50 of
              each arm-round's 1000 timed samples; round 0 is never used
  P1, P2      per VM boot, the order effect 1/2[(K_RF + K_RR) - (K_FF + K_FR)] and the layout effect
              1/2[(K_FR + K_RR) - (K_FF + K_RF)] (subscripts O, L) of p50(A), K1, K2, K3; k = 24
  P3, C1      per adjacent F-R pair (VM boots 1-2 and 3-4), V(R) - V(F), V the mean of the VM boot's
              four scored rounds; P3 for K1, K2, K3, C1 for p50(A); k = 12
  verdicts    HELD when I95 lies wholly inside [-m, +m], REFUTED when I999 lies wholly outside it,
              UNRESOLVED otherwise; m = 3 us; I95 d(3)-d(10) at k = 12 and d(7)-d(18) at k = 24,
              I999 d(1)-d(12) and d(4)-d(21)
  P4          phi = s2_vm / (s2_vm + s2_board) for Lv from the F VM boots only: each round less its
              cell's median deviation, then a balanced nested ANOVA by moments (board boots, VM
              boots, rounds); the interval from 10 000 resamples of whole board boots seeded by the
              schedule's bootstrap seed, a resample with both components zero undefined, counted
              and left out; HELD when the 2.5% bound is at least 0.5, REFUTED when the 97.5% bound
              is below 0.5, UNRESOLVED otherwise or when more than 10% are undefined
  checks      M1-M9 as the header's table; a prediction resting on a failed one prints VOID
  reporting   below the headline, each arm's quantile table per S regime (7.7); then the unscored
              7.2 interaction, 7.3 position in pair with the difference of its two medians, and U1-U8,
              U5 with each QEMU thread's run time and U6 with the tail's share of variance at the board
              and VM levels

DECIDED HERE, where the design leaves a choice (all but the last also in the harness's header):
  - a percentile of the bootstrap is the nearest rank, x[ceil(p/100 * m)] of the m defined values;
  - a bootstrap resample recomputes the whole estimator, the cells' deviations included;
  - a resample index is int(random() * 6) from random.Random(bootstrap_seed), so no Python version
    changes the interval;
  - C1 is guarded by the checks that guard all, and not by M2 or M4, whose rows name P2, P3 and
    P3, P4;
  - U4 sets each outcome against the layout of the probe launch of the arm it adds (A for p50(A), C
    for K1, D for K2, B for K3);
  - M4's thread-CPU sample judges a thread's last CPU (/proc stat field 39) for both vCPU threads,
    and for every other thread whose schedstat run time rose in that arm-round's KVM snapshot (a
    thread born during it counting from zero): a thread that slept from its pin through the
    arm-round keeps the CPU it had before the pin, and it ran nowhere. A thread off its core with no
    entry at the snapshot's end has no run-time record and fails M4;
  - M5 also fails on a test hook in force (a boot.json hook other than BOARD_HOOKS, a stamp whose
    tegra is not 1 or whose proc and sys roots are not /proc and /sys) and on a stamp whose kernel,
    QEMU or L4T release is not the label's; M8 also needs each board boot's boot id, and six distinct;
  - a probe read-back that ended later than READBACK_BOUND_MS after its launch (200 exchanges at
    2 ms, the earliest the warm-up can end) is flagged and kept; a flag voids nothing;
  - M1 also needs boot.json's complete, which the harness writes only once the restores were
    judged: a board boot that stopped after its last VM boot stopped as a stalled one does. Each
    stamp's s_regime, qemu_pad and qemu_pin must equal its schedule line (section 4.5): the pad under
    M2, the pin under M4, and the regime, which names both of S's parts, under both;
  - U6's share of variance is section 7.4's decomposition of the arm-round p99 and largest observed
    value, cells removed, per S regime: s2_board and s2_vm over their sum with s2_round.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import random
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import randomise_schedule as rs  # noqa: E402

# The committed schedule (the header states both; M9 checks the file against the hash).
MASTER_SEED = 979784927940495478
SCHEDULE_SHA256 = "0da177e5aaeadc77511bf1927de5fa0017133bc83863a9679875adf3712119b9"
LABEL = ("L4T R39, kernel 6.8.12-1021-tegra, QEMU 8.2.2, a robustness experiment; no figure here is "
         "comparable with any R36 record or is an R39 baseline")
# What the label names, compared with every stamp (M5): the label is printed on every page, so a stamp
# from another kernel, QEMU or L4T release would make it false.
LABEL_KERNEL = "6.8.12-1021-tegra"
LABEL_QEMU = "8.2.2"
LABEL_L4T = "R39"
# The paths the harness reads the host through, as the board has them (its own defaults and
# lib-measure.sh's), and TEGRA as the board sets it. boot.json records them as "hooks"; any other value is
# a test hook in force, and a figure read through a stand-in is not the board's (M5).
BOARD_HOOKS = {"proc_root": "/proc", "sys_root": "/sys",
               "reset_reason": "/sys/devices/platform/bus@0/c360000.pmc/reset_reason",
               "pstore_var": "/var/lib/systemd/pstore", "emc_bpmp": "/sys/kernel/debug/bpmp/debug/clk/emc/rate",
               "emc_ccf": "/sys/kernel/debug/clk/emc/clk_rate", "sysfs_cpu": "/sys/devices/system/cpu",
               "kvm_debugfs": "/sys/kernel/debug/kvm", "tegra": 1}
MARGIN = 3.0
INTERVALS = {12: {"I95": (3, 10), "I999": (1, 12)}, 24: {"I95": (7, 18), "I999": (4, 21)}}
P4_THRESHOLD = 0.5
UNDEFINED_MAX = 0.10
EMC_FLAG_MAX = 0.05
SETTLE_S = 600
N_TIMED, N_WARMUP = 1000, 200
INTERVAL_MS = 2
# A probe's warm-up is N_WARMUP exchanges, each followed by the constant sleep: it cannot end sooner than
# this after the launch, so a read-back that ended by then ended before the timed window began.
READBACK_BOUND_MS = N_WARMUP * INTERVAL_MS
BOOTSTRAP_N_DESIGN = 10000
BOOTSTRAP_N = BOOTSTRAP_N_DESIGN
ARM_NAME = {"A": "A-loopback", "B": "B-bridge", "C": "C-null", "D": "D-guest"}
NOT_RANDOM = 0x0040000          # ADDR_NO_RANDOMIZE
OUTCOMES = ("A", "K1", "K2", "K3")
P1 = ("P1 A", "P1 K1", "P1 K2", "P1 K3")
P2 = ("P2 A", "P2 K1", "P2 K2", "P2 K3")
P3 = ("P3 K1", "P3 K2", "P3 K3")
ALL = P1 + P2 + P3 + ("C1 A", "P4")
GUARDS = {"M1": ALL, "M2": P2 + P3, "M3": P1 + P2, "M4": P3 + ("P4",), "M5": ALL, "M6": ALL, "M7": ALL,
          "M8": ALL, "M9": ALL}


# ------------------------------------------------------------------ the statistics

def coverage(k, j):
    """Coverage for the median of the order-statistic pair d(j), d(k + 1 - j) of k values."""
    tail = sum(math.comb(k, i) for i in range(j)) / 2.0 ** k
    return 1.0 - 2.0 * tail


def interval(values):
    """The median, I95, I999 and the min-max band of k values, k one the design has intervals for."""
    k = len(values)
    if k not in INTERVALS:
        raise ValueError("no interval is fixed for k = %d" % k)
    d = sorted(values)
    out = {"k": k, "median": st.median(d), "band": (d[0], d[-1])}
    for name, (lo, hi) in INTERVALS[k].items():
        out[name] = (d[lo - 1], d[hi - 1])
    return out


def verdict(iv, m=MARGIN):
    lo, hi = iv["I95"]
    if -m <= lo and hi <= m:
        return "HELD"
    lo, hi = iv["I999"]
    if lo > m or hi < -m:
        return "REFUTED"
    return "UNRESOLVED"


def vm_effects(c):
    """(order, layout, interaction) of one VM boot from its four cells' values."""
    order = 0.5 * ((c["RF"] + c["RR"]) - (c["FF"] + c["FR"]))
    layout = 0.5 * ((c["FR"] + c["RR"]) - (c["FF"] + c["RF"]))
    inter = 0.5 * ((c["RR"] - c["RF"]) - (c["FR"] - c["FF"]))
    return order, layout, inter


def components(data):
    """(s2_round, s2_vm, s2_board) of a balanced nested design data[board][vm][round], by moments."""
    a, b, n = len(data), len(data[0]), len(data[0][0])
    if a < 2 or b < 2 or n < 2 or any(len(x) != b or any(len(y) != n for y in x) for x in data):
        raise ValueError("not a balanced nested design")
    grand = st.mean(v for x in data for y in x for v in y)
    bm = [st.mean(v for y in x for v in y) for x in data]
    vm = [[st.mean(y) for y in x] for x in data]
    ms_board = b * n * sum((m - grand) ** 2 for m in bm) / (a - 1)
    ms_vm = n * sum((vm[i][j] - bm[i]) ** 2 for i in range(a) for j in range(b)) / (a * (b - 1))
    ms_round = sum((v - vm[i][j]) ** 2 for i in range(a) for j in range(b) for v in data[i][j]) / (a * b * (n - 1))
    return ms_round, max(0.0, (ms_vm - ms_round) / n), max(0.0, (ms_board - ms_vm) / (b * n))


def phi(s2_vm, s2_board):
    tot = s2_vm + s2_board
    return None if tot == 0 else s2_vm / tot


def remove_cells(boards):
    """boards[board][vm] = [(cell, value), ...] -> the values less their cell's deviation: the
    cell's median over these rounds minus their overall median."""
    vals = [v for x in boards for y in x for _c, v in y]
    overall = st.median(vals)
    dev = {}
    for cell in sorted({c for x in boards for y in x for c, _v in y}):
        dev[cell] = st.median([v for x in boards for y in x for c, v in y if c == cell]) - overall
    return [[[v - dev[c] for c, v in y] for y in x] for x in boards]


def phi_of(boards):
    comps = components(remove_cells(boards))
    return phi(comps[1], comps[2]), comps


def nearest_rank(xs, p):
    return xs[max(0, int(math.ceil(p / 100.0 * len(xs))) - 1)]


def bootstrap_phi(boards, seed, n):
    """Whole board boots resampled with replacement n times; phi recomputed on each."""
    rng = random.Random(seed)
    a = len(boards)
    got, undefined = [], 0
    for _ in range(n):
        pick = [boards[min(a - 1, int(rng.random() * a))] for _i in range(a)]
        f, _c = phi_of(pick)
        if f is None:
            undefined += 1
        else:
            got.append(f)
    got.sort()
    lo = nearest_rank(got, 2.5) if got else None
    hi = nearest_rank(got, 97.5) if got else None
    return {"lo": lo, "hi": hi, "undefined": undefined, "n": n, "mean": st.mean(got) if got else None}


def p4_verdict(bs):
    if bs["lo"] is None or bs["undefined"] > UNDEFINED_MAX * bs["n"]:
        return "UNRESOLVED"
    if bs["lo"] >= P4_THRESHOLD:
        return "HELD"
    if bs["hi"] < P4_THRESHOLD:
        return "REFUTED"
    return "UNRESOLVED"


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def _pearson(x, y):
    if len(x) < 3:
        return None
    mx, my = st.mean(x), st.mean(y)
    sx = sum((v - mx) ** 2 for v in x)
    sy = sum((v - my) ** 2 for v in y)
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sx * sy)


def spearman(x, y):
    return _pearson(_ranks(x), _ranks(y))


def rank_autocorr(xs, lag):
    if len(xs) <= lag + 2:
        return None
    r = _ranks(xs)
    return _pearson(r[:-lag], r[lag:])


def mad(xs):
    m = st.median(xs)
    return st.median([abs(v - m) for v in xs])


def cpuset(spec):
    out = set()
    try:
        for part in spec.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(part))
    except ValueError:
        return None
    return out


# ------------------------------------------------------------------ the records

def _lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f]
    except OSError:
        return []


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _fields(text):
    """key=value tokens, the last key comm= taking the rest of the line (a thread name has spaces)."""
    head, sep, comm = text.partition(" comm=")
    d = {}
    for t in head.split():
        k, s, v = t.partition("=")
        if s:
            d.setdefault(k, v)
    if sep:
        d["comm"] = comm
    return d


class VM(object):
    def __init__(self, path, v):
        self.v, self.path = v, path
        self.stamp = _json(os.path.join(path, "stamp.json")) or {}
        self.lat, self.samples, self.kvm, self.stalls = {}, {}, {}, []
        for r in range(0, 5):
            for arm, name in ARM_NAME.items():
                tag = "%s_%s%d" % (name, "s" if r == 0 else "r", r)
                d = _json(os.path.join(path, "lat-%s.json" % tag))
                if d and isinstance(d.get("summary"), dict):
                    self.lat[(r, arm)] = d["summary"]
                    self.samples[(r, arm)] = d.get("samples_in_order") or []
                k = _json(os.path.join(path, "kvm-%s.json" % tag))
                if k:
                    self.kvm[(r, arm)] = k
        self.stalls = glob.glob(os.path.join(path, "stall-*.json"))
        self.order = {}
        for ln in _lines(os.path.join(path, "order.log")):
            m = re.match(r"round (\d+) cell=(\S+) order: ([A-D](?: [A-D])*)$", ln)
            if m:
                self.order.setdefault(int(m.group(1)), []).append((m.group(2), m.group(3).split()))
        self.readback = []
        for ln in _lines(os.path.join(path, "readback.log")):
            m = re.match(r"(qemu|mon-host|mon-ns|probe-[A-D]) r(-|\d) (.*)$", ln)
            if m:
                self.readback.append((m.group(1), m.group(2), _fields(m.group(3))))
        self.threads = self._tagged("threads.log", r"round (\d+) (before|after) (.*)$")
        self.cpu = self._tagged("cpu.log", r"round (\d+) after-([A-D]) (.*)$")
        self.confine = self._tagged("confine.log", r"round (\d+) (before|after) (.*)$")
        self.emc = self._tagged("emc.log", r"round (\d+) after-([A-D]) (.*)$")
        self.halt = dict((ln.split(" ", 1) + [""])[:2] for ln in _lines(os.path.join(path, "halt.log")) if ln)
        self.gpu = dict((ln.split(" ", 1) + [""])[:2] for ln in _lines(os.path.join(path, "gpu.log")) if ln)

    def _tagged(self, name, rx):
        out = []
        for ln in _lines(os.path.join(self.path, name)):
            m = re.match(rx, ln)
            if m:
                out.append((int(m.group(1)), m.group(2), _fields(m.group(3))))
        return out

    def p50(self, r, arm):
        s = self.lat.get((r, arm))
        return None if s is None else s["p50_ms"] * 1000.0

    def outcomes(self, r):
        a, b, c, d = (self.p50(r, x) for x in "ABCD")
        if None in (a, b, c, d):
            return None
        return {"A": a, "K1": c - b, "K2": d - c, "K3": b - a, "Lv": d}


class Boot(object):
    def __init__(self, path):
        self.path = path
        self.boot = _json(os.path.join(path, "boot.json"))
        if not isinstance(self.boot, dict) or "boot_tag" not in self.boot:
            raise ValueError("%s is not a board boot of run-randomise.sh (no boot.json)" % path)
        self.tag = self.boot["boot_tag"]
        self.vms = {}
        for d in sorted(glob.glob(os.path.join(path, "v[1-4]"))):
            v = int(os.path.basename(d)[1:])
            self.vms[v] = VM(d, v)
        self.logins = {}
        for ln in _lines(os.path.join(path, "logins.txt")):
            m = re.match(r"v(\d) r(\d) accepted=(\d+)$", ln)
            if m:
                self.logins[(int(m.group(1)), int(m.group(2)))] = int(m.group(3))


# ------------------------------------------------------------------ the checks

def _want_core(pin, comm):
    return pin[0] if comm == "CPU 0/KVM" else pin[1] if comm == "CPU 1/KVM" else pin[2]


def _ran(kv):
    """{tid: whether the thread's schedstat run time rose during the arm-round}, from the arm-round's KVM
    snapshot (kvm-<arm>_r<k>.json). A thread in the snapshot's end and not its start was born during the
    arm-round, and its run time counts from zero. A thread missing from the end is not in the result: it
    has no run-time record."""
    out = {}
    try:
        before, after = kv["before"]["threads"], kv["after"]["threads"]
    except (KeyError, TypeError):
        return out
    for tid, a in after.items():
        try:
            out[tid] = int(a["run_ns"]) > int((before.get(tid) or {}).get("run_ns", 0))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def check_boot(b, sched):
    """{check: [problems]} for one board boot against its schedule; an empty list is a pass. M7's
    entry is the list of flagged arm-rounds, which fails only past the share M7 allows."""
    p = {m: [] for m in GUARDS}
    sb = sched["boots"].get(b.tag)
    if sb is None:
        p["M9"].append("%s is not a board boot of the schedule" % b.tag)
        return p
    if sorted(b.vms) != sorted(sb["vms"]):
        p["M1"].append("%s: VM boots %s, the schedule has %s" % (b.tag, sorted(b.vms), sorted(sb["vms"])))
    bj = b.boot
    # M1: the board boot ran to its end. The harness writes complete last, once the restores were judged, so
    # a board boot that stopped after its last VM boot stopped as a stalled one does.
    if bj.get("complete") is not True:
        p["M1"].append("%s: the board boot did not run to its end (boot.json complete %r)" % (b.tag, bj.get("complete")))
    # M8: reset_reason and pstore first, settled, the shipped command line
    if not isinstance(bj.get("reset_reason"), str) or not bj.get("reset_reason") or not bj.get("first_reads"):
        p["M8"].append("%s: reset_reason not read first" % b.tag)
    ps = bj.get("pstore")
    if not isinstance(ps, dict) or not isinstance(ps.get("sys"), list) or not isinstance(ps.get("archive"), list):
        p["M8"].append("%s: pstore not read" % b.tag)
    if not isinstance(bj.get("uptime_first_vm_s"), int) or bj["uptime_first_vm_s"] < SETTLE_S:
        p["M8"].append("%s: uptime %s s at the first VM boot" % (b.tag, bj.get("uptime_first_vm_s")))
    if bj.get("cmdline_tokens") != 0:
        p["M8"].append("%s: %s isolcpus=/irqaffinity= token(s)" % (b.tag, bj.get("cmdline_tokens")))
    if not isinstance(bj.get("boot_id"), str) or not bj.get("boot_id"):
        p["M8"].append("%s: no boot id recorded" % b.tag)
    # M5: no test hook in force -- every path the host was read through is the board's own
    hooks = bj.get("hooks")
    if not isinstance(hooks, dict):
        p["M5"].append("%s: no hooks recorded" % b.tag)
    else:
        for key, want in sorted(BOARD_HOOKS.items()):
            if hooks.get(key) != want:
                p["M5"].append("%s: hook %s %r, the board's %r" % (b.tag, key, hooks.get(key), want))
    if bj.get("schedule_sha256") != SCHEDULE_SHA256:
        p["M9"].append("%s: boot.json names another schedule" % b.tag)
    emc0 = bj.get("emc_first") or {}
    halt0 = None
    for v, svm in sorted(sb["vms"].items()):
        vm = b.vms.get(v)
        if vm is None:
            continue
        nr = len(svm["cells"])
        where = "%s v%d" % (b.tag, v)
        stp = vm.stamp
        # The stamp against its schedule line, as section 4.5 asks: the pad is QEMU's layout (M2), the pin its
        # threads' cores (M4), and the regime names both of S's parts, so it fails both.
        sched_pad = "-" if svm["pad"] is None else str(svm["pad"])
        sched_pin = ",".join(str(c) for c in svm["pin"])
        if stp.get("s_regime") != svm["S"]:
            for m in ("M2", "M4"):
                p[m].append("%s: the stamp's s_regime %r, scheduled %s" % (where, stp.get("s_regime"), svm["S"]))
        if stp.get("qemu_pad") != sched_pad:
            p["M2"].append("%s: the stamp's qemu_pad %r, scheduled %s" % (where, stp.get("qemu_pad"), sched_pad))
        if stp.get("qemu_pin") != sched_pin:
            p["M4"].append("%s: the stamp's qemu_pin %r, scheduled %s" % (where, stp.get("qemu_pin"), sched_pin))
        # M1: every scored arm-round complete, no stall
        for r in range(1, nr + 1):
            for arm in "ABCD":
                s = vm.lat.get((r, arm))
                tag = "%s_r%d" % (ARM_NAME[arm], r)
                if s is None:
                    p["M1"].append("%s %s: missing" % (where, tag))
                    continue
                for key, want in (("tag", tag), ("n", N_TIMED), ("warmup_discarded", N_WARMUP), ("bad", 0),
                                  ("rejected_by_monitor", 0)):
                    if s.get(key) != want:
                        p["M1"].append("%s %s: %s=%r" % (where, tag, key, s.get(key)))
        if vm.stalls:
            p["M1"].append("%s: stall record(s)" % where)
        # M2: every launch read back as scheduled
        seen = {}
        for who, r, f in vm.readback:
            seen.setdefault((who, r), []).append(f)
        want = [("qemu", "-", svm)]
        for r, rd in sorted(svm["rounds"].items()):
            want += [("mon-host", str(r), rd["mon"]["host"]), ("mon-ns", str(r), rd["mon"]["ns"])]
            want += [("probe-" + a, str(r), rd["probe"][a]) for a in "ABCD"]
        for who, r, la in want:
            got = seen.get((who, r), [])
            if len(got) != 1:
                p["M2"].append("%s %s r%s: %d read-back(s)" % (where, who, r, len(got)))
                continue
            f = got[0]
            try:
                norand = int(f.get("personality", "x"), 16) & NOT_RANDOM != 0
            except ValueError:
                p["M2"].append("%s %s r%s: personality %r" % (where, who, r, f.get("personality")))
                continue
            if norand != (la["norand"] == 1):
                p["M2"].append("%s %s r%s: ADDR_NO_RANDOMIZE %s, scheduled %s" % (where, who, r, norand, la["norand"]))
            if f.get("environ") != str(la["env"]):
                p["M2"].append("%s %s r%s: environ %s, scheduled %d" % (where, who, r, f.get("environ"), la["env"]))
            if not (f.get("startstack") or "").isdigit():
                p["M2"].append("%s %s r%s: startstack not recorded" % (where, who, r))
        # M3: order.log and the cell order as the schedule
        for r, rd in sorted(svm["rounds"].items()):
            got = vm.order.get(r, [])
            if got != [(rd["cell"], rd["order"])]:
                p["M3"].append("%s r%d: order %s, scheduled %s %s" % (where, r, got, rd["cell"], rd["order"]))
        # M4: every QEMU thread on its group's core, before and after every round and between arm-rounds
        pin = svm["pin"]
        for r in sorted(svm["rounds"]):
            for when in ("before", "after"):
                rows = [f for rr_, w, f in vm.threads if rr_ == r and w == when]
                if not rows:
                    p["M4"].append("%s r%d %s: no thread read-back" % (where, r, when))
                for f in rows:
                    if cpuset(f.get("allowed", "")) != {_want_core(pin, f.get("comm", ""))}:
                        p["M4"].append("%s r%d %s: %s allowed %s" % (where, r, when, f.get("comm"), f.get("allowed")))
            # A thread's last CPU is judged when it ran during the arm-round (its schedstat run time
            # rose), and always for a vCPU: a thread that slept from its pin through the arm-round keeps
            # the CPU it had before the pin, and it ran nowhere, so it is not off its core.
            for arm in "ABCD":
                rows = [f for rr_, a, f in vm.cpu if rr_ == r and a == arm]
                if not rows:
                    p["M4"].append("%s r%d after %s: no thread-CPU sample" % (where, r, arm))
                ran = _ran(vm.kvm.get((r, arm)))
                for f in rows:
                    comm = f.get("comm", "")
                    if f.get("last") == str(_want_core(pin, comm)):
                        continue
                    if re.match(r"CPU \d+/KVM$", comm) or ran.get(f.get("tid")):
                        p["M4"].append("%s r%d after %s: %s last on %s" % (where, r, arm, comm, f.get("last")))
                    elif f.get("tid") not in ran:
                        p["M4"].append("%s r%d after %s: %s (tid %s) last on %s, no run-time record"
                                       % (where, r, arm, comm, f.get("tid"), f.get("last")))
        # M5: the platform
        if stp.get("governor_state") != "pinned" or stp.get("governor_after") != "performance":
            p["M5"].append("%s: governor %s/%s" % (where, stp.get("governor_state"), stp.get("governor_after")))
        if stp.get("cstate_policy") != "shallow":
            p["M5"].append("%s: idle states %s" % (where, stp.get("cstate_policy")))
        for key in ("platform", "platform_after"):
            pl = stp.get(key) or {}
            for unit in ("docker", "docker_socket", "containerd"):
                if (pl.get(unit) or {}).get("active") not in ("inactive", "failed"):
                    p["M5"].append("%s: %s %s is %s" % (where, key, unit, (pl.get(unit) or {}).get("active")))
            if pl.get("dockerd_cpus") != "not running" or pl.get("containerd_cpus") != "not running" \
                    or pl.get("containerd_shims") != 0:
                p["M5"].append("%s: %s daemons %s/%s, shims %s" % (where, key, pl.get("dockerd_cpus"),
                                                                    pl.get("containerd_cpus"), pl.get("containerd_shims")))
        nv = ((stp.get("system") or {}).get("nvpmodel") or "").split()
        if not nv or nv[-1] != "1":
            p["M5"].append("%s: nvpmodel %r" % (where, " ".join(nv)))
        # the GPU read for real and the host read through /proc and /sys, never a test hook
        if stp.get("tegra") != 1:
            p["M5"].append("%s: the stamp's tegra is %s, not 1" % (where, stp.get("tegra")))
        for key in ("platform", "platform_after", "system"):
            obj = stp.get(key) or {}
            for root, want in (("proc_root", "/proc"), ("sys_root", "/sys")):
                if obj.get(root) != want:
                    p["M5"].append("%s: %s %s %r" % (where, key, root, obj.get(root)))
        # the label printed on every page names this kernel, QEMU and L4T release
        if stp.get("kernel") != LABEL_KERNEL:
            p["M5"].append("%s: kernel %r, the label's %s" % (where, stp.get("kernel"), LABEL_KERNEL))
        if not re.search(r"\bversion %s\b" % re.escape(LABEL_QEMU), stp.get("qemu_version") or ""):
            p["M5"].append("%s: QEMU %r, the label's %s" % (where, stp.get("qemu_version"), LABEL_QEMU))
        l4t = (stp.get("system") or {}).get("l4t_release") or ""
        if not l4t.startswith("# %s " % LABEL_L4T):
            p["M5"].append("%s: L4T %r, the label's %s" % (where, l4t, LABEL_L4T))
        for r in sorted(svm["rounds"]):
            for when in ("before", "after"):
                rows = [f for rr_, w, f in vm.confine if rr_ == r and w == when]
                if len(rows) != 1:
                    p["M5"].append("%s r%d %s: no confinement read-back" % (where, r, when))
                    continue
                f = rows[0]
                lists = [f.get("udevd", ""), f.get("pid1", "")]
                if f.get("shells") != "none":
                    lists += (f.get("shells") or "").split(";")
                if any(cpuset(x) != {3, 5} for x in lists):
                    p["M5"].append("%s r%d %s: confinement %s" % (where, r, when, f))
        if not vm.halt.get("start") or vm.halt.get("start") != vm.halt.get("end"):
            p["M5"].append("%s: halt polling %r -> %r" % (where, vm.halt.get("start"), vm.halt.get("end")))
        if halt0 is None:
            halt0 = vm.halt.get("start")
        elif vm.halt.get("start") != halt0:
            p["M5"].append("%s: halt polling differs from the board boot's first VM boot" % where)
        if vm.gpu.get("start") != "0" or vm.gpu.get("end") != "0":
            p["M5"].append("%s: GR3D %s/%s" % (where, vm.gpu.get("start"), vm.gpu.get("end")))
        if stp.get("schedule_sha256") != SCHEDULE_SHA256:
            p["M9"].append("%s: the stamp names another schedule" % where)
        # M6: no login during any round
        for r in sorted(svm["rounds"]):
            if b.logins.get((v, r)) != 0:
                p["M6"].append("%s r%d: accepted logins %s" % (where, r, b.logins.get((v, r))))
        # M7: the EMC read after every scored arm-round against the board boot's first read
        for r in range(1, nr + 1):
            for arm in "ABCD":
                rows = [f for rr_, a, f in vm.emc if rr_ == r and a == arm]
                if len(rows) != 1 or rows[0].get("bpmp") != emc0.get("bpmp") or rows[0].get("ccf") != emc0.get("ccf") \
                        or not emc0.get("bpmp"):
                    p["M7"].append("%s r%d %s" % (where, r, arm))
    return p


def check_all(boots, sched, sched_raw):
    """{check: (ok, problems, note)} over the board boots."""
    probs = {m: [] for m in GUARDS}
    if hashlib.sha256(sched_raw).hexdigest() != SCHEDULE_SHA256:
        probs["M9"].append("the schedule file's sha256 is not the committed one")
    images = set()
    ids = {}
    for b in boots:
        for m, ps in check_boot(b, sched).items():
            probs[m] += ps
        for vm in b.vms.values():
            images.add(vm.stamp.get("guest_ifs_sha256"))
        bid = b.boot.get("boot_id")
        if isinstance(bid, str) and bid:
            if bid in ids:          # section 4.1: each board boot a fresh boot
                probs["M8"].append("%s and %s ran on one boot (%s)" % (ids[bid], b.tag, bid))
            else:
                ids[bid] = b.tag
    if len(images) != 1 or None in images:
        probs["M5"].append("guest images: %d distinct" % len(images))
    n_ar = sum(len(sched["boots"][b.tag]["vms"][v]["cells"]) * 4 for b in boots if b.tag in sched["boots"]
               for v in sched["boots"][b.tag]["vms"])
    out = {}
    for m, ps in probs.items():
        if m == "M7":
            share = len(ps) / float(n_ar) if n_ar else 1.0
            out[m] = (share <= EMC_FLAG_MAX, ps, "%d of %d arm-rounds flagged" % (len(ps), n_ar))
        else:
            out[m] = (not ps, ps, "")
    return out


CHECK_TEXT = {
    "M1": "every scored arm-round complete (1000 timed after 200 warm-up), no stall",
    "M2": "every launch's personality, environment size and startstack read back as scheduled",
    "M3": "order.log and the cell order equal the schedule in every round",
    "M4": "every QEMU thread on its group's core, before and after every round, and between arm-rounds "
          "every vCPU and every thread that ran",
    "M5": "platform: governor, c7, confinement, Docker, halt polling, nvpmodel 1, GPU idle, one image, "
          "no test hook, the label's kernel, QEMU and L4T",
    "M6": "no SSH login accepted during any round",
    "M7": "EMC between arm-rounds equal to the board boot's first read (VOID past 5%)",
    "M8": "reset_reason and pstore read first, uptime >= 600 s at the first VM boot, shipped command line, "
          "a boot of its own",
    "M9": "the schedule file's sha256 equals the committed one",
}


def late_readbacks(boots):
    """([flagged], total): the probe read-backs that ended later than READBACK_BOUND_MS after their
    launch -- past the earliest end of the warm-up, so possibly inside the timed window -- out of every
    probe read-back. Reported and kept: a flag voids nothing (the header's DECIDED HERE)."""
    late, total = [], 0
    for b in boots:
        for v, vm in sorted(b.vms.items()):
            for who, r, f in vm.readback:
                if not who.startswith("probe-"):
                    continue
                total += 1
                t = f.get("t_ms", "")
                if not t.isdigit() or int(t) > READBACK_BOUND_MS:
                    late.append("%s v%d r%s %s t_ms=%s" % (b.tag, v, r, who, t or "unread"))
    return late, total


def _late_text(boots):
    late, total = late_readbacks(boots)
    out = ["  probe read-backs that ended past %d ms from their launch, the earliest the warm-up can end: %d of %d "
           "(flagged and kept; a flag voids nothing)" % (READBACK_BOUND_MS, len(late), total)]
    out += ["       %s" % x for x in late[:8]]
    if len(late) > 8:
        out.append("       ... and %d more" % (len(late) - 8))
    return out


# ------------------------------------------------------------------ the scoring

def _fmt(x):
    return "n/a" if x is None else "%+.2f" % x


def _iv_text(iv):
    named = "the min-max band: at k = 12 the 99.95% interval, the same as I999" if iv["k"] == 12 else "the min-max band"
    return "median %s us, I95 [%s, %s], I999 [%s, %s], min-max [%s, %s] (%s), k=%d" % (
        _fmt(iv["median"]), _fmt(iv["I95"][0]), _fmt(iv["I95"][1]), _fmt(iv["I999"][0]), _fmt(iv["I999"][1]),
        _fmt(iv["band"][0]), _fmt(iv["band"][1]), named, iv["k"])


def _void(name, checks):
    failed = [m for m, guarded in GUARDS.items() if name in guarded and not checks[m][0]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else None


def _vm_cells(vm, svm, key):
    vals = {}
    for r in range(1, 5):
        o = vm.outcomes(r)
        if o is None:
            return None
        vals[svm["rounds"][r]["cell"]] = o[key]
    return vals


def score(boots, sched, checks, n_boot):
    lines = []
    by = {b.tag: b for b in boots}
    # P1 and P2, per VM boot
    eff = {key: {"order": [], "layout": [], "inter": []} for key in OUTCOMES}
    for tag in rs.SCORED:
        for v, svm in sorted(sched["boots"][tag]["vms"].items()):
            vm = by[tag].vms.get(v)
            for key in OUTCOMES:
                c = _vm_cells(vm, svm, key) if vm else None
                if c is None:
                    continue
                o, lay, inter = vm_effects(c)
                eff[key]["order"].append(o)
                eff[key]["layout"].append(lay)
                eff[key]["inter"].append(inter)
    label = {"A": "p50(A)", "K1": "K1 = C - B", "K2": "K2 = D - C", "K3": "K3 = B - A"}
    for pname, kind in (("P1", "order"), ("P2", "layout")):
        for key in OUTCOMES:
            name = "%s %s" % (pname, key)
            vals = eff[key][kind]
            v = _void(name, checks)
            if len(vals) != 24:
                lines.append("  %-6s %s effect on %s: k=%d of 24 VM boots -> %s" % (name, kind, label[key], len(vals),
                                                                                  v or "VOID (M1 failed)"))
                continue
            iv = interval(vals)
            lines.append("  %-6s %s effect on %s: %s -> %s" % (name, kind, label[key], _iv_text(iv), v or verdict(iv)))
    # P3 and C1, per adjacent pair
    pairs = {key: [] for key in OUTCOMES}
    position = {key: {"F first": [], "R first": []} for key in OUTCOMES}
    for tag in rs.SCORED:
        svms = sched["boots"][tag]["vms"]
        for v1, v2 in ((1, 2), (3, 4)):
            for key in OUTCOMES:
                means = {}
                for v in (v1, v2):
                    vm = by[tag].vms.get(v)
                    c = _vm_cells(vm, svms[v], key) if vm else None
                    if c is not None:
                        means[svms[v]["S"]] = st.mean(c.values())
                if sorted(means) != ["F", "R"]:
                    continue
                d = means["R"] - means["F"]
                pairs[key].append(d)
                position[key]["F first" if svms[v1]["S"] == "F" else "R first"].append(d)
    for key in ("K1", "K2", "K3", "A"):
        name = ("P3 %s" % key) if key != "A" else "C1 A"
        vals = pairs[key]
        v = _void(name, checks)
        tail = " (scored, not a gate: a REFUTED C1 does not void P3)" if key == "A" else ""
        if len(vals) != 12:
            lines.append("  %-6s S effect on %s: k=%d of 12 pairs -> %s%s" % (name, label[key], len(vals),
                                                                           v or "VOID (M1 failed)", tail))
            continue
        iv = interval(vals)
        lines.append("  %-6s S effect on %s, V(R) - V(F) per adjacent pair: %s -> %s%s"
                     % (name, label[key], _iv_text(iv), v or verdict(iv), tail))
    # P4
    fboards = _f_boards(by, sched, "Lv")
    v = _void("P4", checks)
    if fboards is None:
        lines.append("  P4 phi for Lv from the F VM boots: the F rounds are not complete -> %s" % (v or "VOID (M1 failed)"))
    else:
        f, comps = phi_of(fboards)
        bs = bootstrap_phi(fboards, sched["bootstrap_seed"], n_boot)
        lines.append("  P4 phi = s2_vm / (s2_vm + s2_board) for Lv, F VM boots: phi %s (s2_round %.3f, s2_vm %.3f, "
                     "s2_board %.3f us^2); board-boot bootstrap 2.5%% %s, 97.5%% %s over %d resamples, %d undefined -> %s"
                     % ("undefined" if f is None else "%.3f" % f, comps[0], comps[1], comps[2],
                        "n/a" if bs["lo"] is None else "%.3f" % bs["lo"], "n/a" if bs["hi"] is None else "%.3f" % bs["hi"],
                        bs["n"], bs["undefined"], v or p4_verdict(bs)))
    return lines, eff, position


def _f_boards(by, sched, key, regime="F", tags=rs.SCORED):
    """[board][vm][(cell, value)] of the regime's VM boots, or None when one is not complete."""
    out = []
    for tag in tags:
        vms = []
        for v, svm in sorted(sched["boots"][tag]["vms"].items()):
            if svm["S"] != regime:
                continue
            vm = by[tag].vms.get(v)
            rows = []
            for r in range(1, 5):
                o = vm.outcomes(r) if vm else None
                if o is None:
                    return None
                rows.append((svm["rounds"][r]["cell"], o[key]))
            vms.append(rows)
        out.append(vms)
    return out


def _stat_boards(by, sched, arm, stat, regime):
    """[board][vm][(cell, value in us)] of one arm's arm-round statistic (p99_ms, max_ms) in the regime's
    VM boots, or None when one is not complete."""
    out = []
    for tag in rs.SCORED:
        vms = []
        for v, svm in sorted(sched["boots"][tag]["vms"].items()):
            if svm["S"] != regime:
                continue
            vm = by[tag].vms.get(v)
            rows = []
            for r in range(1, 5):
                s = vm.lat.get((r, arm)) if vm else None
                if s is None or not isinstance(s.get(stat), (int, float)):
                    return None
                rows.append((svm["rounds"][r]["cell"], s[stat] * 1000.0))
            vms.append(rows)
        out.append(vms)
    return out


def _run_ms(kv):
    """{thread name: run time in ms during the arm-round} from its KVM snapshot, the threads of one name
    summed; a thread born during the arm-round counts from zero."""
    out = {}
    try:
        before, after = kv["before"]["threads"], kv["after"]["threads"]
    except (KeyError, TypeError):
        return out
    for tid, a in after.items():
        try:
            d = int(a["run_ns"]) - int((before.get(tid) or {}).get("run_ns", 0))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        out[a.get("comm", "?")] = out.get(a.get("comm", "?"), 0.0) + d / 1e6
    return out


QUANTILES = (("min", "min_ms"), ("p50", "p50_ms"), ("p90", "p90_ms"), ("p99", "p99_ms"), ("p99.9", "p999_ms"),
             ("max", "max_ms"))


def quantile_tables(by, sched):
    """Section 7.7: below the headline, each arm's within-arm-round quantiles as the median over its k
    scored arm-rounds, per S regime -- the measurement design's quantile table, kept as detail."""
    out = ["quantile tables (detail below the headline; the median over the k scored arm-rounds of each "
           "arm-round's quantile, us):"]
    for regime in ("F", "R"):
        for a in "ABCD":
            cols = {q: [] for q, _key in QUANTILES}
            k = 0
            for tag in rs.SCORED:
                for v, svm in sched["boots"][tag]["vms"].items():
                    vm = by[tag].vms.get(v)
                    if svm["S"] != regime or vm is None:
                        continue
                    for r in range(1, 5):
                        s = vm.lat.get((r, a))
                        if s is None:
                            continue
                        k += 1
                        for q, key in QUANTILES:
                            if isinstance(s.get(key), (int, float)):
                                cols[q].append(s[key] * 1000.0)
            out.append("  7.7 quantiles, S=%s arm %s (k=%d): %s" % (regime, a, k, " ".join(
                "%s %s" % (q, "%.1f" % st.median(cols[q]) if cols[q] else "n/a") for q, _key in QUANTILES)))
    return out


# ------------------------------------------------------------------ unscored

def unscored(by, sched, eff, position):
    out = ["unscored (reported, never decisive):"]
    for key in OUTCOMES:
        vals = eff[key]["inter"]
        if len(vals) == 24:
            iv = interval(vals)
            out.append("  7.2 interaction 1/2[(K_RR - K_RF) - (K_FR - K_FF)] of %s: median %s, I95 [%s, %s], min-max [%s, %s], "
                       "k=24" % (key, _fmt(iv["median"]), _fmt(iv["I95"][0]), _fmt(iv["I95"][1]), _fmt(iv["band"][0]),
                                 _fmt(iv["band"][1])))
    for key in OUTCOMES:
        pp = position[key]
        mf = st.median(pp["F first"]) if pp["F first"] else None
        mr = st.median(pp["R first"]) if pp["R first"] else None
        out.append("  7.3 position in pair, S effect on %s: F first median %s (k=%d), R first median %s (k=%d), "
                   "difference F first - R first %s" % (key, _fmt(mf), len(pp["F first"]), _fmt(mr), len(pp["R first"]),
                                                        _fmt(None if mf is None or mr is None else mf - mr)))
    # U1
    for regime in ("F", "R"):
        for key in ("Lv", "K1", "K2", "K3"):
            bd = _f_boards(by, sched, key, regime)
            if bd is None:
                continue
            f, c = phi_of(bd)
            out.append("  U1 variance components, %s VM boots, %s: s2_round %.3f, s2_vm %.3f, s2_board %.3f us^2, phi %s"
                       % (regime, key, c[0], c[1], c[2], "undefined" if f is None else "%.3f" % f))
    for pat in rs.PATTERNS:
        tags = [t for t in rs.SCORED if sched["boots"][t]["pattern"] == pat]
        bd = _f_boards(by, sched, "Lv", "F", tags)
        if bd is not None and len(bd) >= 2:
            f, c = phi_of(bd)
            out.append("  U1 split by S pattern, %s board boots (%s), F VM boots, Lv: s2_vm %.3f, s2_board %.3f us^2, phi %s"
                       % (pat, " ".join(tags), c[1], c[2], "undefined" if f is None else "%.3f" % f))
    # U2: position effects in O-random rounds
    pos = {(a, i): [] for a in "ABCD" for i in range(1, 5)}
    for tag in rs.SCORED:
        for v, svm in sched["boots"][tag]["vms"].items():
            vm = by[tag].vms.get(v)
            if vm is None:
                continue
            for a in "ABCD":
                xs = [vm.p50(r, a) for r in range(1, 5)]
                if None in xs:
                    continue
                mean = st.mean(xs)
                for r in range(1, 5):
                    rd = svm["rounds"][r]
                    if rd["O"] == "R":
                        pos[(a, rd["order"].index(a) + 1)].append(vm.p50(r, a) - mean)
    for a in "ABCD":
        out.append("  U2 position effect, arm %s, positions 1-4: %s" % (a, " ".join(
            "%s (k=%d)" % (_fmt(st.median(pos[(a, i)]) if pos[(a, i)] else None), len(pos[(a, i)])) for i in range(1, 5))))
    # U3: placement among R VM boots
    group = {0: "vCPU 0", 1: "vCPU 1", 2: "the rest"}
    for key in ("K1", "Lv"):
        by_g = {g: [] for g in group}
        for tag in rs.SCORED:
            for v, svm in sched["boots"][tag]["vms"].items():
                vm = by[tag].vms.get(v)
                if svm["S"] != "R" or vm is None:
                    continue
                os_ = [vm.outcomes(r) for r in range(1, 5)]
                if None in os_:
                    continue
                by_g[svm["pin"].index(0)].append(st.mean(o[key] for o in os_))
        out.append("  U3 %s by the thread group on core 0 (R VM boots, VM-boot means): %s" % (key, "; ".join(
            "%s: %s (n=%d)" % (group[g], _fmt(st.median(xs)) if xs else "n/a", len(xs)) for g, xs in by_g.items())))
    # U4: layout against outcome in L-random rounds
    minuend = {"A": "A", "K1": "C", "K2": "D", "K3": "B"}
    for key in OUTCOMES:
        rows = []
        for tag in rs.SCORED:
            for v, svm in sched["boots"][tag]["vms"].items():
                vm = by[tag].vms.get(v)
                if vm is None:
                    continue
                rb = {(w, r): f for w, r, f in vm.readback}
                for r in range(1, 5):
                    rd = svm["rounds"][r]
                    o = vm.outcomes(r)
                    f = rb.get(("probe-" + minuend[key], str(r)))
                    if rd["L"] != "R" or o is None or f is None or not (f.get("startstack") or "").isdigit():
                        continue
                    e = rd["probe"][minuend[key]]["pad"]
                    rows.append((o[key], e % 64, e % 4096, int(f["startstack"]) % 4096))
        if len(rows) >= 3:
            ys = [x[0] for x in rows]
            cs = [spearman(ys, [x[i] for x in rows]) for i in (1, 2, 3)]
            out.append("  U4 %s against E mod 64, E mod 4096, startstack within its page (probe %s, L-random rounds): "
                       "rank correlations %s (n=%d)" % (key, minuend[key], ", ".join(
                           "n/a" if c is None else "%+.2f" % c for c in cs), len(rows)))
    # U5: KVM per cell and regime
    for regime in ("F", "R"):
        for cell in rs.CELLS:
            share, wake = [], []
            for tag in rs.SCORED:
                for v, svm in sched["boots"][tag]["vms"].items():
                    vm = by[tag].vms.get(v)
                    if svm["S"] != regime or vm is None:
                        continue
                    for r in range(1, 5):
                        if svm["rounds"][r]["cell"] != cell:
                            continue
                        for a in "ABCD":
                            k = vm.kvm.get((r, a)) or {}
                            try:
                                c0, c1 = k["before"]["counters"], k["after"]["counters"]
                                att = c1["halt_attempted_poll"] - c0["halt_attempted_poll"]
                                share.append((c1["halt_successful_poll"] - c0["halt_successful_poll"]) / float(att))
                                wake.append((c1["halt_wakeup"] - c0["halt_wakeup"]) / float(N_TIMED + N_WARMUP))
                            except (KeyError, TypeError, ZeroDivisionError):
                                continue
            out.append("  U5 KVM, S=%s cell %s: halt-poll success share median %s, blocked wake-ups per exchange median %s"
                       " (n=%d arm-rounds)" % (regime, cell, "n/a" if not share else "%.3f" % st.median(share),
                                               "n/a" if not wake else "%.3f" % st.median(wake), len(share)))
    # U5: each QEMU thread's run time per arm-round (schedstat, the KVM snapshots), by thread name
    for regime in ("F", "R"):
        for cell in rs.CELLS:
            per, n = {}, 0
            for tag in rs.SCORED:
                for v, svm in sched["boots"][tag]["vms"].items():
                    vm = by[tag].vms.get(v)
                    if svm["S"] != regime or vm is None:
                        continue
                    for r in range(1, 5):
                        if svm["rounds"][r]["cell"] != cell:
                            continue
                        for a in "ABCD":
                            for comm, ms in _run_ms(vm.kvm.get((r, a))).items():
                                per.setdefault(comm, []).append(ms)
                            n += 1 if vm.kvm.get((r, a)) else 0
            out.append("  U5 QEMU thread run time per arm-round, S=%s cell %s: %s (n=%d arm-rounds)" % (
                regime, cell, "; ".join("%s median %.3f ms" % (c, st.median(xs)) for c, xs in sorted(per.items())) or "n/a",
                n))
    # U6: tails
    for a in "ABCD":
        for cell in rs.CELLS:
            p99, mx = [], []
            for tag in rs.SCORED:
                for v, svm in sched["boots"][tag]["vms"].items():
                    vm = by[tag].vms.get(v)
                    if vm is None:
                        continue
                    for r in range(1, 5):
                        s = vm.lat.get((r, a))
                        if s is not None and svm["rounds"][r]["cell"] == cell:
                            p99.append(s["p99_ms"] * 1000.0)
                            mx.append(s["max_ms"] * 1000.0)
            if p99:
                out.append("  U6 tail, arm %s cell %s: p99 min/median/max %.1f/%.1f/%.1f us, largest observed value per round "
                           "min/median/max %.1f/%.1f/%.1f us (k=%d)" % (a, cell, min(p99), st.median(p99), max(p99),
                                                                      min(mx), st.median(mx), max(mx), len(p99)))
    # U6: the tail's share of variance at the board and VM levels, by section 7.4's decomposition
    for regime in ("F", "R"):
        for a in "ABCD":
            parts = []
            for stat, name in (("p99_ms", "p99"), ("max_ms", "largest observed value")):
                bd = _stat_boards(by, sched, a, stat, regime)
                if bd is None:
                    parts.append("%s n/a" % name)
                    continue
                _f, c = phi_of(bd)
                tot = sum(c)
                parts.append("%s board share %s, VM share %s" % (name, "n/a" if tot == 0 else "%.2f" % (c[2] / tot),
                                                                 "n/a" if tot == 0 else "%.2f" % (c[1] / tot)))
            out.append("  U6 tail variance, S=%s arm %s: %s (shares of the per-round variance, k=12 VM boots in 6 board "
                       "boots)" % (regime, a, "; ".join(parts)))
    # U7: autocorrelation within arm-rounds, by regime
    for regime in ("F", "R"):
        for a in "ABCD":
            l1, l10 = [], []
            for tag in rs.SCORED:
                for v, svm in sched["boots"][tag]["vms"].items():
                    vm = by[tag].vms.get(v)
                    if svm["S"] != regime or vm is None:
                        continue
                    for r in range(1, 5):
                        xs = vm.samples.get((r, a)) or []
                        c1, c10 = rank_autocorr(xs, 1), rank_autocorr(xs, 10)
                        if c1 is not None:
                            l1.append(c1)
                        if c10 is not None:
                            l10.append(c10)
            out.append("  U7 rank autocorrelation, S=%s arm %s: lag 1 median %s, lag 10 median %s (n=%d arm-rounds)" % (
                regime, a, "n/a" if not l1 else "%+.3f" % st.median(l1), "n/a" if not l10 else "%+.3f" % st.median(l10),
                len(l1)))
    # U8: spread in the all-fixed cell against the all-random cell
    for key in ("K1", "K2", "K3"):
        fixed, rand = [], []
        for tag in rs.SCORED:
            for v, svm in sched["boots"][tag]["vms"].items():
                vm = by[tag].vms.get(v)
                if vm is None:
                    continue
                for r in range(1, 5):
                    o = vm.outcomes(r)
                    if o is None:
                        continue
                    cell = svm["S"] + svm["rounds"][r]["cell"]
                    if cell == "FFF":
                        fixed.append(o[key])
                    elif cell == "RRR":
                        rand.append(o[key])
        out.append("  U8 round-to-round MAD of %s: all-fixed cell %s (k=%d), all-random cell %s (k=%d)" % (
            key, "n/a" if len(fixed) < 2 else "%.3f us" % mad(fixed), len(fixed),
            "n/a" if len(rand) < 2 else "%.3f us" % mad(rand), len(rand)))
    return out


ARM_TABLE = ["per-arm configuration:",
             "  A loopback  probe (core 4) -> 127.0.0.1:7100 -> monitor-native on core 3",
             "  B bridge    probe (core 4) -> br0 -> veth -> namespace -> monitor-native on core 3",
             "  C null      probe (core 4) -> br0 -> tap-qnx -> the guest's echo server on :7000",
             "  D guest     probe (core 4) -> br0 -> tap-qnx -> the guest's plain monitor on :7100",
             "  every arm: TCP, 1000 timed exchanges after 200 warm-up, 2 ms constant spacing, QEMU on cores 0-2"]


def one_boot(b, sched):
    out = []
    sb = sched["boots"].get(b.tag)
    if sb is None:
        return ["%s is not a board boot of the schedule" % b.tag]
    if sb["kind"] == "smoke":
        out.append("%s (smoke): never scored; its data is not used by any prediction" % b.tag)
    else:
        out.append("%s (scored board boot, one of six): unscored here; the verdicts need all six" % b.tag)
    for v, svm in sorted(sb["vms"].items()):
        vm = b.vms.get(v)
        out.append("  VM boot v%d: S=%s pin=%s pad=%s" % (v, svm["S"], ",".join(map(str, svm["pin"])),
                                                         "-" if svm["pad"] is None else svm["pad"]))
        for r in range(1, len(svm["cells"]) + 1):
            rd = svm["rounds"][r]
            o = vm.outcomes(r) if vm else None
            ps = " ".join("%s %s" % (a, "n/a" if vm is None or vm.p50(r, a) is None else "%.1f" % vm.p50(r, a)) for a in "ABCD")
            ks = "n/a" if o is None else "K1 %+.1f K2 %+.1f K3 %+.1f" % (o["K1"], o["K2"], o["K3"])
            out.append("  v%d r%d cell=%s order=%s  p50 us: %s  %s" % (v, r, rd["cell"], ",".join(rd["order"]), ps, ks))
    for m, ps in check_boot(b, sched).items():
        if m == "M7":
            out.append("  %s %d arm-round(s) flagged" % (m, len(ps)))
        else:
            out.append("  %s %s" % (m, "ok" if not ps else "FAILED: " + "; ".join(ps[:5])))
    return out + _late_text([b])


def main(argv=None):
    ap = argparse.ArgumentParser(description="run-randomise.sh's analysis")
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--one", action="store_true", help="one board boot, unscored")
    ap.add_argument("boots", nargs="+")
    a = ap.parse_args(argv)
    try:
        raw = open(a.schedule, "rb").read()
        sched = rs.parse(raw.decode("utf-8"))
        boots = [Boot(d) for d in a.boots]
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print("randomise_report: %s" % e)
        return 2
    print(LABEL)
    print("randomise_report: schedule %s, sha256 %s (committed %s)" % (
        a.schedule, hashlib.sha256(raw).hexdigest()[:16], SCHEDULE_SHA256[:16]))
    if a.one:
        if len(boots) != 1:
            print("randomise_report: --one takes one board boot")
            return 2
        for ln in one_boot(boots[0], sched):
            print(ln)
        print(LABEL)
        return 0
    tags = sorted(b.tag for b in boots)
    checks = check_all(boots, sched, raw)
    print("checks (a prediction resting on a failed one prints VOID):")
    for m in sorted(GUARDS):
        ok, ps, note = checks[m]
        print("  %s %s%s -> %s" % (m, CHECK_TEXT[m], (": " + note) if note else "", "ok" if ok else "FAILED"))
        for x in ps[:8]:
            print("       %s" % x)
        if len(ps) > 8:
            print("       ... and %d more" % (len(ps) - 8))
    for line in _late_text(boots):
        print(line)
    for line in ARM_TABLE:
        print(line)
    if tags != list(rs.SCORED) or any(b.boot.get("kind") != "scored" for b in boots):
        print("not scored: the predictions are for the six scored board boots b1..b6 (got %s)" % " ".join(tags))
        for b in boots:
            for ln in one_boot(b, sched):
                print(ln)
        print(LABEL)
        return 0
    by = {b.tag: b for b in boots}
    print("predictions (margin m = %.0f us; HELD: I95 wholly inside [-m, +m]; REFUTED: I999 wholly outside it; "
          "else UNRESOLVED):" % MARGIN)
    lines, eff, position = score(boots, sched, checks, BOOTSTRAP_N)
    for ln in lines:
        print(ln)
    for ln in quantile_tables(by, sched):
        print(ln)
    for ln in unscored(by, sched, eff, position):
        print(ln)
    print(LABEL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
