#!/usr/bin/env python3
"""partition_report.py -- run-partition.sh's test: does partitioning the kernel take part of
the host's tick off the exchange? (Phase 3b / A6, 2026-09-25), by the rule its header fixed
before any run.

  partition_report.py --one OUT N WARMUP        one boot's figures and checks, unscored
  partition_report.py A1 B1 B2 A2 N WARMUP      the four boots' directories: the verdicts

Alignment, classes, the TICK BIN and TAIL are run-tick.sh's (tick_report.exchanges,
in_bin). Per arm, pooled over its boots: SLOWDOWN (median in the bin minus median of the
other out-class exchanges), RATIO (the bin's share of the tail over its share of the
exchanges) and p50 over every timed exchange; per boot the same SLOWDOWN for P4. The boot
itself is read from stamp.json (arm, tag, command line, isolated cores, uptime), the
confinement from confine.log, QEMU's per-thread pins from pin.log, the softirq and
interrupt counts from irq-t2ms_rN.txt. Scored only with the four boots A1 B1 B2 A2 at
k = 16 each; a prediction resting on a failed check prints VOID.
"""
import collections
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bursts_report as br  # noqa: E402
import tick_report as tr  # noqa: E402

TAGS = ("A1", "B1", "B2", "A2")
ARM_OF = {"A1": "default", "A2": "default", "B1": "partition", "B2": "partition"}
ARMS = ("default", "partition")
SCORED_K, SETTLE_S = 16, 600
PARAMS = ("isolcpus=managed_irq,domain,0-2,4", "irqaffinity=3,5")
WATCHED = (0, 1, 2, 4)
LESS, FLOOR, SAME, SCHED_LEFT, MIN_TAIL = 0.75, 3.0, 3.0, 0.05, 25


def _cpus(s):
    out = set()
    for x in s.split(","):
        if x:
            a, _, b = x.partition("-")
            out.update(range(int(a), int(b or a) + 1))
    return out


def irq_counts(path):
    """{(round phase, row): [per-CPU counts]} for /proc/softirqs rows (SCHED, TIMER, ...)
    and one row DEV: device interrupts (numbered lines, not the timer or kvm)."""
    got, cur, kind = {}, None, None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"== round \d+ (before|after) (softirqs|interrupts)", line)
        if m:
            cur, kind = m.group(1), m.group(2)
            got[(cur, "DEV")] = [0] * 6
            continue
        if cur is None or "CPU0" in line:
            continue
        f = line.split()
        if not f or not f[0].endswith(":"):
            continue
        nums = []
        for x in f[1:7]:
            if not x.isdigit():
                break
            nums.append(int(x))
        if len(nums) != 6:
            continue
        if kind == "softirqs":
            got[(cur, f[0][:-1])] = nums
        elif f[0][:-1].isdigit() and not re.search(r"arch_timer|kvm", line):
            got[(cur, "DEV")] = [a + b for a, b in zip(got[(cur, "DEV")], nums)]
    return got


def delta(counts, row, cpus):
    b, a = counts.get(("before", row)), counts.get(("after", row))
    if b is None or a is None:
        return None
    return sum(a[c] - b[c] for c in cpus)


def boot(out, n, warm):
    """Everything one boot's directory says, as a dict."""
    stamp = json.load(open(os.path.join(out, "stamp.json")))
    info = stamp.get("boot", "")
    up = re.search(r"uptime at preflight (\d+) s", info)
    iso = re.search(r"isolated '([^']*)'", info)
    b = {"dir": out, "tag": stamp.get("boot_tag"), "arm": stamp.get("arm"), "uptime": int(up.group(1)) if up else -1,
         "isolated": iso.group(1) if iso else None, "params": [p for p in PARAMS if p in info],
         "any_param": bool(re.search(r"(isolcpus|irqaffinity)=", info.split(";")[0])),
         "rows": [], "all": [], "rounds": 0, "aligned": 0, "sched": [], "timer": [], "dev0": []}
    rounds = sorted(int(re.search(r"_r(\d+)\.", f).group(1)) for f in glob.glob(os.path.join(out, "lat-t2ms_r*.json")))
    b["rounds"] = len(rounds)
    for r in rounds:
        rows, lat = tr.exchanges(out, r, n, warm)
        if rows is None:
            continue
        b["aligned"] += 1
        b["rows"] += rows
        b["all"] += lat
        p = os.path.join(out, "irq-t2ms_r%d.txt" % r)
        if os.path.exists(p):
            c = irq_counts(p)
            for key, row, cpus in (("sched", "SCHED", WATCHED), ("timer", "TIMER", WATCHED), ("dev0", "DEV", (0,))):
                d = delta(c, row, cpus)
                if d is not None:
                    b[key].append(d)
    conf = collections.defaultdict(list)
    p = os.path.join(out, "confine.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (before|after) udevd=(\S*) pid1=(\S*) gnome-shell=(\S*)", line)
            if m:
                conf[int(m.group(1))].append(m.groups()[2:])
    b["confined"] = sum(1 for r in rounds if len(conf[r]) == 2 and
                        all(u == "3,5" and p1 == "3,5" and gs in ("3,5", "none") for u, p1, gs in conf[r]))
    pins = collections.defaultdict(lambda: [0, 0])
    p = os.path.join(out, "pin.log")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            if len(f) == 6 and f[0] == "round":
                pins[int(f[1])][0] += 1
                pins[int(f[1])][1] += _cpus(f[4]) == _cpus(f[5])
    b["pinned"] = sum(1 for r in rounds if pins[r][0] >= 2 and pins[r][0] == pins[r][1])
    b["logins"] = br.logins(out)
    return b


def figures(rows, allv):
    """(SLOWDOWN, RATIO, p50, tick-bin tail count)."""
    inb = [v for t0, v, _ in rows if tr.in_bin(t0)]
    outb = [v for t0, v, _ in rows if not tr.in_bin(t0)]
    tail = [t0 for t0, _, tl in rows if tl]
    tail_in = sum(1 for t0 in tail if tr.in_bin(t0))
    share_all = len(inb) / len(rows) if rows else float("nan")
    ratio = (tail_in / len(tail)) / share_all if tail and share_all > 0 else float("nan")
    slow = st.median(inb) - st.median(outb) if inb and outb else float("nan")
    return slow, ratio, (st.median(allv) if allv else float("nan")), tail_in


def arm_ok(b):
    if b["arm"] != ARM_OF.get(b["tag"]):
        return False
    if b["arm"] == "partition":
        return len(b["params"]) == len(PARAMS) and b["isolated"] == "0-2,4"
    return not b["any_param"] and b["isolated"] == ""


def show_boot(b):
    slow, ratio, p50, tin = figures(b["rows"], b["all"])
    v = b["all"]
    print("  %-3s %-9s rounds %2d aligned %2d  p50 %.1f  p99 %.1f  p99.9 %.1f  SLOWDOWN %+.1f  RATIO %.2f  tick-bin tail %d"
          % (b["tag"], b["arm"], b["rounds"], b["aligned"], p50, br.pct(v, 99) if v else float("nan"),
             br.pct(v, 99.9) if v else float("nan"), slow, ratio, tin))
    print("      confined %d/%d, pinned %d/%d, logins %s, uptime %d s, isolated '%s', params %d/%d;"
          " per round on cores 0-2,4: SCHED %s, TIMER %s; device IRQs on core 0 %s"
          % (b["confined"], b["rounds"], b["pinned"], b["rounds"], b["logins"], b["uptime"], b["isolated"],
             len(b["params"]), len(PARAMS), _m(b["sched"]), _m(b["timer"]), _m(b["dev0"])))


def _m(xs):
    return "%.0f" % st.median(xs) if xs else "-"


def verdict(v, scored, ok, needs):
    if not scored:
        return "not scored (the prediction is for the four boots A1 B1 B2 A2 at k=%d each)" % SCORED_K
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    if argv and argv[0] == "--one":
        show_boot(boot(argv[1], int(argv[2]), int(argv[3])))
        return 0
    if len(argv) != 6:
        print("usage: partition_report.py --one OUT N WARMUP | A1 B1 B2 A2 N WARMUP", file=sys.stderr)
        return 2
    n, warm = int(argv[4]), int(argv[5])
    boots = [boot(d, n, warm) for d in argv[:4]]
    for b in boots:
        show_boot(b)
    pooled = {a: ([x for b in boots if b["arm"] == a for x in b["rows"]], [x for b in boots if b["arm"] == a for x in b["all"]])
              for a in ARMS}
    fig = {a: figures(*pooled[a]) for a in ARMS}
    per = {b["tag"]: figures(b["rows"], b["all"])[0] for b in boots}
    sched = {a: [x for b in boots if b["arm"] == a for x in b["sched"]] for a in ARMS}
    sd = {a: (sum(sched[a]) / len(sched[a]) if sched[a] else float("nan")) for a in ARMS}
    ok = {"M1": all(b["rounds"] > 0 and b["aligned"] / b["rounds"] >= 0.9 for b in boots),
          "M2": all(b["confined"] == b["rounds"] and b["pinned"] == b["rounds"] for b in boots),
          "M3": all(b["logins"] == 0 for b in boots),
          "M4": all(arm_ok(b) for b in boots) and sd["default"] > 0 and sd["partition"] <= SCHED_LEFT * sd["default"],
          "M5": [b["tag"] for b in boots] == list(TAGS) and all(b["uptime"] >= SETTLE_S for b in boots),
          "M6": all(fig[a][3] >= MIN_TAIL for a in ARMS)}
    scored = [b["tag"] for b in boots] == list(TAGS) and all(b["rounds"] == SCORED_K for b in boots)
    print("  M1 every boot's rounds align (>= 90%%): %s -> %s"
          % (", ".join("%s %d/%d" % (b["tag"], b["aligned"], b["rounds"]) for b in boots), "ok" if ok["M1"] else "FAILED"))
    print("  M2 every round confined and every QEMU thread on its pin: %s -> %s"
          % (", ".join("%s %d+%d/%d" % (b["tag"], b["confined"], b["pinned"], b["rounds"]) for b in boots),
             "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins during the rounds: %s -> %s" % ([b["logins"] for b in boots], "ok" if ok["M3"] else "FAILED"))
    print("  M4 the arms are what they say (%s); SCHED softirqs per round on cores 0-2,4: default %.0f, partition %.0f"
          " (want <= %.0f%%) -> %s" % (", ".join("%s %s" % (b["tag"], "ok" if arm_ok(b) else "WRONG") for b in boots),
                                        sd["default"], sd["partition"], 100 * SCHED_LEFT, "ok" if ok["M4"] else "FAILED"))
    print("  M5 four boots in the order %s, each settled (>= %d s): %s -> %s"
          % (" ".join(TAGS), SETTLE_S, ", ".join("%s %d s" % (b["tag"], b["uptime"]) for b in boots), "ok" if ok["M5"] else "FAILED"))
    print("  M6 tick-bin tail exchanges per arm: %s (want >= %d) -> %s"
          % ({a: fig[a][3] for a in ARMS}, MIN_TAIL, "ok" if ok["M6"] else "FAILED"))
    base = ["M1", "M2", "M3", "M4", "M5"]
    sa, sp = fig["default"][0], fig["partition"][0]
    ra, rp = fig["default"][1], fig["partition"][1]
    print("  P1  the tick costs less: SLOWDOWN partition %+.1f, default %+.1f us -> %s"
          % (sp, sa, verdict("HELD" if sa > 0 and sp <= LESS * sa else "REFUTED", scored, ok, base + ["M6"])))
    print("  P2  not all of it goes: SLOWDOWN partition %+.1f us (want >= +%.0f) -> %s"
          % (sp, FLOOR, verdict("HELD" if sp >= FLOOR else "REFUTED", scored, ok, base)))
    print("  P3  fewer tick-bin exchanges reach the tail: RATIO partition %.2f, default %.2f -> %s"
          % (rp, ra, verdict("HELD" if ra > 0 and rp <= LESS * ra else "REFUTED", scored, ok, base + ["M6"])))
    pb = [per.get(t, float("nan")) for t in ("B1", "B2")]
    pa = [per.get(t, float("nan")) for t in ("A1", "A2")]
    print("  P4  every boot agrees: SLOWDOWN A1 %+.1f, B1 %+.1f, B2 %+.1f, A2 %+.1f us -> %s"
          % (pa[0], pb[0], pb[1], pa[1], verdict("HELD" if max(pb) < min(pa) else "REFUTED", scored, ok, base)))
    print("  P5  the typical exchange does not change: p50 partition %.1f, default %.1f us -> %s"
          % (fig["partition"][2], fig["default"][2],
             verdict("HELD" if abs(fig["partition"][2] - fig["default"][2]) <= SAME else "REFUTED", scored, ok, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
