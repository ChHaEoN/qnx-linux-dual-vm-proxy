#!/usr/bin/env python3
"""mss_report.py OUT -- run-mss.sh's map of the guest path's 1280 B bump and its fast path above
one MSS, by the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-26).

Per round, the p50 of each arm; a difference is two arms' p50s in the same round, and per
difference the median over rounds with the distribution-free interval of widest coverage >= 95%.
Packets per exchange: the device's tx (requests) and rx (replies) packets over the arm's
exchanges, warm-up included, median over rounds. Reads per frame: the endpoint's own count per
connection (`sweep: reads :7121 greedy frames=F reads=R`, F = n + warm-up), matched to the arms of
its path in the run's order.
"""
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

G_SIZES = (1024, 1088, 1152, 1216, 1280, 1344, 1408, 1447, 1448, 1449, 1472, 1536)
B_SIZES = (1024, 1280, 1448, 1449)
ARMS = tuple("G%d" % s for s in G_SIZES) + tuple("B%d" % s for s in B_SIZES)
MSS = 1448
PORT = 7121
TOL_READS = 0.02
ONE, TWO = 1.2, 1.8
LINE = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")


def load(out):
    p50, stats = {}, {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-([GB]\d+)_r(\d+)\.json$", f)
        if m:
            s = json.load(open(f))["summary"]
            key = (m.group(1), int(m.group(2)))
            p50[key] = s["p50_ms"] * 1000.0
            stats[key] = (s.get("n"), s.get("bad"), s.get("rejected_by_monitor"), s.get("frame_bytes"))
    return p50, stats


def packets(out, ex):
    cnt = {}
    p = os.path.join(out, "counters.log")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            m = re.match(r"([GB]\d+)_r(\d+)$", f[0]) if len(f) == 7 else None
            if m:
                cnt.setdefault((m.group(1), int(m.group(2))), {})[f[2]] = [int(x) for x in f[3:]]
    per = {}
    for key, c in cnt.items():
        if "before" in c and "after" in c:
            d = [e - b for b, e in zip(c["before"], c["after"])]
            per[key] = (d[1] / ex, d[0] / ex)          # tx (requests), rx (replies)
    return per


def reads(out, frames):
    got, problems = {}, []
    order = []
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) order: (.*)$", line.strip())
            if m:
                order.append((int(m.group(1)), m.group(2).split()))
    for path, name in (("G", "guest-console.log"), ("B", "mss-ns.log")):
        fp = os.path.join(out, name)
        text = open(fp, encoding="utf-8", errors="replace").read() if os.path.exists(fp) else ""
        sess = [(int(f), int(rd)) for pt, _, f, rd in LINE.findall(text) if int(pt) == PORT and int(f) == frames]
        want = [(a, r) for r, arms in order for a in arms if a[0] == path]
        if len(sess) != len(want):
            problems.append("%s: %d connections of %d frames for %d arms" % (path, len(sess), frames, len(want)))
            continue
        for (a, r), (f, rd) in zip(want, sess):
            got[(a, r)] = rd / f
    return got, problems


def main(argv):
    out = argv[0]
    p50, stats = load(out)
    rounds = sorted({r for _, r in p50})
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    ex = (n_want or 1000) + warm
    pk = packets(out, ex)
    rpf, problems = reads(out, ex)
    keys = [(a, r) for a in ARMS for r in rounds]
    one_read = [k for k in keys if int(k[0][1:]) <= MSS]
    ok = {"M1": bool(rounds) and all(k in stats and stats[k][1] == 0 and stats[k][2] == 0 and stats[k][3] == int(k[0][1:])
                                      and (n_want is None or stats[k][0] == n_want) for k in keys),
          "M2": bool(rounds) and not problems and all(k in rpf and abs(rpf[k] - 1.0) <= TOL_READS for k in one_read),
          "M3": bool(rounds) and all(k in pk for k in keys)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm has %d rounds of n samples, none rejected, none bad, its own size -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    for msg in problems:
        print("     %s" % msg)
    print("  M2 one read per frame (within %.2f) in every arm up to %d B -> %s" % (TOL_READS, MSS, "ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm has its counters before and after -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(vals):
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds: p50 (us); packets per exchange tx/rx; reads per frame")
    for a in ARMS:
        print("    %-6s %8.2f   %5.2f/%-5.2f   %s" % (a, med([p50[(a, r)] for r in rounds if (a, r) in p50]),
                                                   med([pk[(a, r)][0] for r in rounds if (a, r) in pk]),
                                                   med([pk[(a, r)][1] for r in rounds if (a, r) in pk]),
                                                   "%.3f" % med([rpf[(a, r)] for r in rounds if (a, r) in rpf])
                                                   if any((a, r) in rpf for r in rounds) else "-"))

    def d(a, b):
        return [p50[(a, r)] - p50[(b, r)] for r in rounds if (a, r) in p50 and (b, r) in p50]

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-22s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    print("  adjacent steps, paired within round (us): median [interval], rounds > 0")
    for x, sizes in (("G", G_SIZES), ("B", B_SIZES)):
        for a, b in zip(sizes, sizes[1:]):
            show("%s%d -> %s%d" % (x, a, x, b), d("%s%d" % (x, b), "%s%d" % (x, a)))
    print("  the scored differences")
    p1 = show("G1449 - G1448", d("G1449", "G1448"))
    p3 = show("B1449 - B1448", d("B1449", "B1448"))
    p4a = show("G1280 - G1024", d("G1280", "G1024"))
    p4b = show("G1448 - G1280", d("G1448", "G1280"))
    t48 = med([pk[("G1448", r)][0] for r in rounds if ("G1448", r) in pk])
    r48 = med([pk[("G1448", r)][1] for r in rounds if ("G1448", r) in pk])
    t49 = med([pk[("G1449", r)][0] for r in rounds if ("G1449", r) in pk])
    r49 = med([pk[("G1449", r)][1] for r in rounds if ("G1449", r) in pk])
    print("  P1  the fast path begins at one MSS: G1449 - G1448 %+.2f us (want <= -8) -> %s"
          % (p1, verdict("HELD" if p1 <= -8 else "REFUTED")))
    print("  P2  packets per exchange tx/rx: G1448 %.2f/%.2f (want <= %.1f), G1449 %.2f/%.2f (want >= %.1f) -> %s"
          % (t48, r48, ONE, t49, r49, TWO,
             verdict("HELD" if t48 <= ONE and r48 <= ONE and t49 >= TWO and r49 >= TWO else "REFUTED")))
    print("  P3  the host path's step at the same byte: B1449 - B1448 %+.2f us (want >= +3) -> %s"
          % (p3, verdict("HELD" if p3 >= 3 else "REFUTED")))
    print("  P4  the bump: G1280 - G1024 %+.2f (want >= +6), G1448 - G1280 %+.2f (want >= -3) -> %s"
          % (p4a, p4b, verdict("HELD" if p4a >= 6 and p4b >= -3 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
