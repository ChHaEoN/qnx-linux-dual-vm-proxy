#!/usr/bin/env python3
"""readpath_report.py OUT N WARMUP -- run-readpath.sh's test: where one guest read() goes, on two
vCPUs against one, by the rule the harness's header fixed before any run (Phase 3b / A6,
2026-09-26).

Per arm and round: the probe's p50, and from the trace (blockpath_trace.segments) the median over
exchanges of the blocked halts inside [I, TX] and of the segments A B C D. Reads per frame from the
guest's own count on the boot's console (`sweep: reads :PORT MODE frames=F reads=R`, the
connection of F = n + warm-up). Differences are paired within the round; the interval is the
distribution-free one of widest coverage >= 95%.
"""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blockpath_trace as bpt  # noqa: E402
from sweep_report import interval  # noqa: E402

ARMS = ("2d64", "2s64", "1d64", "1s64")
PORT = {"d64": 7120, "s64": 7122}
DESIGNED = {"d64": 1, "s64": 2}
TOL_READS = 0.02
MIN_SEGMENTED = 0.90
LINE = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")


def score_p1(d):
    return "HELD" if d >= 2 else ("REFUTED" if d <= 0 else "PARTIAL")


def score_p2(d):
    return "HELD" if d <= 5 else ("REFUTED" if d >= 10 else "PARTIAL")


def score_p3(d):
    return "HELD" if d >= 10 else "REFUTED"


def score_p4(d):
    return "HELD" if d == 0 else "REFUTED"


def load(out, frames):
    per = {a: {} for a in ARMS}
    for a in ARMS:
        for f in glob.glob(os.path.join(out, "lat-%s_r*.json" % a)):
            r = int(re.search(r"_r(\d+)\.json$", f).group(1))
            s = json.load(open(f))["summary"]
            row = {"rtt": s["p50_ms"] * 1000.0, "n": s.get("n"), "bad": s.get("bad"),
                   "rej": s.get("rejected_by_monitor")}
            bp = os.path.join(out, "bp-%s_r%d.log" % (a, r))
            if os.path.exists(bp):
                _, summ = bpt.segments(bpt.read(bp))
                row["seg"] = summ
            con = os.path.join(out, "console-smp%s_r%d.log" % (a[0], r))
            if os.path.exists(con):
                text = open(con, encoding="utf-8", errors="replace").read()
                sess = [(int(fr), int(rd)) for pt, _, fr, rd in LINE.findall(text)
                        if int(pt) == PORT[a[1:]] and int(fr) == frames]
                if len(sess) == 1:
                    row["rpf"] = sess[0][1] / sess[0][0]
            per[a][r] = row
    rounds = sorted(set.intersection(*(set(per[a]) for a in ARMS))) if all(per.values()) else []
    return per, rounds


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    per, rounds = load(out, n + warm)
    rows = [per[a][r] for a in ARMS for r in rounds]
    ok = {"M1": bool(rows) and all("rpf" in x and abs(x["rpf"] - DESIGNED[a[1:]]) <= TOL_READS
                                   for a in ARMS for r in rounds for x in [per[a][r]]),
          "M2": bool(rows) and all("seg" in x and x["seg"]["requests"] > 0
                                   and x["seg"]["segmented"] / x["seg"]["requests"] >= MIN_SEGMENTED for x in rows),
          "M3": bool(rows) and all(x["n"] == n and x["bad"] == 0 and x["rej"] == 0 for x in rows)}
    print("  rounds %d" % len(rounds))
    print("  M1 reads per frame as designed (d64 1, s64 2, within %.2f), every arm and round -> %s"
          % (TOL_READS, "ok" if ok["M1"] else "FAILED"))
    print("  M2 the trace segmented >= %d%% of every arm's requests -> %s" % (100 * MIN_SEGMENTED, "ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm has its rounds of n samples, none rejected, none bad -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(a, key):
        vals = [per[a][r]["seg"].get(key + "_p50") for r in rounds if "seg" in per[a][r]]
        vals = [v for v in vals if v is not None]
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds: rtt p50 (us); reads/frame; blocked and polled halts in [I, TX];")
    print("  segments A B C D (us); per blocked halt's wake-up and load (us, summed per exchange)")
    for a in ARMS:
        rr = [per[a][r]["rpf"] for r in rounds if "rpf" in per[a][r]]
        print("    %-5s rtt %7.2f  reads %s  blocked %.1f polled %.1f  A %.1f B %.1f C %.1f D %.1f  wake %.1f load %.1f"
              % (a, st.median(per[a][r]["rtt"] for r in rounds), "%.3f" % st.median(rr) if rr else "-",
                 med(a, "blocked"), med(a, "polled"), med(a, "A"), med(a, "B"), med(a, "C"), med(a, "D"),
                 med(a, "wake_us"), med(a, "load_us")))

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-44s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def rtt(a, b):
        return [per[a][r]["rtt"] - per[b][r]["rtt"] for r in rounds]

    def seg(a, b, key):
        return [per[a][r]["seg"][key + "_p50"] - per[b][r]["seg"][key + "_p50"] for r in rounds
                if "seg" in per[a][r] and "seg" in per[b][r]]

    print("  differences, paired within round: median [interval], rounds > 0")
    b2 = show("blocked halts in [I, TX], 2s64 - 2d64", seg("2s64", "2d64", "blocked"))
    r1 = show("rtt us, 1s64 - 1d64 (one vCPU)", rtt("1s64", "1d64"))
    r2 = show("rtt us, 2s64 - 2d64 (two vCPUs)", rtt("2s64", "2d64"))
    b1 = show("blocked halts in [I, TX], 1s64 - 1d64", seg("1s64", "1d64", "blocked"))
    show("rtt us, 1d64 - 2d64 (unscored)", rtt("1d64", "2d64"))
    show("segment C us, 2s64 - 2d64 (unscored)", seg("2s64", "2d64", "C"))
    show("segment C us, 1s64 - 1d64 (unscored)", seg("1s64", "1d64", "C"))
    print("  P1  two vCPUs, the extra read's blocked halts: %+.1f (want >= 2; 0 or less refutes) -> %s"
          % (b2, verdict(score_p1(b2))))
    print("  P2  one vCPU, the extra read's cost: %+.2f us (want <= +5; >= +10 refutes) -> %s" % (r1, verdict(score_p2(r1))))
    print("  P3  two vCPUs, the extra read's cost: %+.2f us (want >= +10) -> %s" % (r2, verdict(score_p3(r2))))
    print("  P4  one vCPU, the extra read's blocked halts: %+.1f (want 0) -> %s" % (b1, verdict(score_p4(b1))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
