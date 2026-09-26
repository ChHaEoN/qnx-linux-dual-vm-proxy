#!/usr/bin/env python3
"""readtime_report.py OUT -- run-readtime.sh's test: is the extra read()'s cost spent inside the call?
By the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-26).

Per arm and round: the probe's p50, and the endpoint's printed medians (`sweep: timing :PORT MODE
frames=F r2_n=N r2_p50_ns= w_p50_ns= svc_p50_ns=`) for the connection that served the arm, matched
per port and path in the run's order (order.log), F = n + warm-up. The guest's lines are in
guest-console.log, the namespace's in reads-ns-PORT.log. Differences are paired within the round;
the interval is the distribution-free one of widest coverage >= 95%.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reads_report import PORT, load, reads_per_frame, run_order  # noqa: E402
from sweep_report import interval  # noqa: E402

ARMS = ("Gd64", "Gd96", "Gs64", "Gg64", "Bd64", "Bs64")
EXACT = {"Gd64": 1, "Gg64": 1, "Bd64": 1, "Gd96": 2, "Gs64": 2, "Bs64": 2}
LONG_READ = 8.0       # P1, us
SVC_STEP = 8.0        # P2, us
WRITE_SAME = 2.0      # P3, us
RTT_STEP = 10.0       # P4, us
TOL_READS = 0.02
TLINE = re.compile(r"sweep: timing :(\d+) (\w+) frames=(\d+) r2_n=(\d+) r2_p50_ns=(-?\d+) w_p50_ns=(-?\d+) svc_p50_ns=(-?\d+)")


def timings(out, frames):
    """{(arm, round): {"r2_n", "r2", "w", "svc"} in us}, and the matching problems."""
    got, problems = {}, []
    order = run_order(out)
    for path in ("G", "B"):
        for mode, port in PORT.items():
            name = "guest-console.log" if path == "G" else "reads-ns-%d.log" % port
            p = os.path.join(out, name)
            text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
            sess = [m for m in TLINE.findall(text) if int(m[0]) == port and int(m[2]) == frames]
            want = [(a, r) for r, arms in order for a in arms if a[0] == path and a[1] == mode]
            if len(sess) != len(want):
                problems.append("%s :%d: %d timed connections of %d frames for %d arms" % (path, port, len(sess), frames, len(want)))
                continue
            for (a, r), m in zip(want, sess):
                got[(a, r)] = {"r2_n": int(m[3]), "r2": int(m[4]) / 1000.0, "w": int(m[5]) / 1000.0, "svc": int(m[6]) / 1000.0}
    return got, problems


def main(argv):
    out = argv[0]
    p50, stats, fb = load(out)
    rounds = sorted({r for _, r in p50})
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    frames = (n_want or 1000) + warm
    rpf, rproblems = reads_per_frame(out, frames)
    tm, tproblems = timings(out, frames)
    keys = [(a, r) for a in ARMS for r in rounds]
    ok = {"M1": bool(rounds) and all(k in stats and stats[k][1] == 0 and stats[k][2] == 0 and fb.get(k) == int(k[0][2:])
                                      and (n_want is None or stats[k][0] == n_want) for k in keys),
          "M2": bool(rounds) and not rproblems and all(k in rpf and abs(rpf[k] - EXACT[k[0]]) <= TOL_READS for k in keys),
          "M3": bool(rounds) and not tproblems and all(k in tm and tm[k]["r2_n"] == (frames if EXACT[k[0]] == 2 else 0)
                                                       for k in keys)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm has %d rounds of n samples, none rejected, none bad, its own size -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    for msg in rproblems + tproblems:
        print("     %s" % msg)
    print("  M2 the read counts are the design's (within %.2f) -> %s" % (TOL_READS, "ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm's connection printed its timing, with second reads where designed -> %s"
          % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(a, key):
        vals = [tm[(a, r)][key] for r in rounds if (a, r) in tm and tm[(a, r)][key] >= 0]
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds (us): round trip p50; the endpoint's r2, w, svc medians")
    for a in ARMS:
        print("    %-5s rtt %7.2f   r2 %6.2f   w %6.2f   svc %6.2f" % (a, st.median(p50[(a, r)] for r in rounds if (a, r) in p50),
                                                                   med(a, "r2"), med(a, "w"), med(a, "svc")))

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-34s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def dt(a, b, key):
        return [tm[(a, r)][key] - tm[(b, r)][key] for r in rounds if (a, r) in tm and (b, r) in tm]

    def drtt(a, b):
        return [p50[(a, r)] - p50[(b, r)] for r in rounds if (a, r) in p50 and (b, r) in p50]

    print("  differences, paired within round (us): median [interval], rounds > 0")
    d_svc = show("svc Gs64 - Gd64", dt("Gs64", "Gd64", "svc"))
    d_w = show("w Gs64 - Gd64", dt("Gs64", "Gd64", "w"))
    d_rtt = show("rtt Gs64 - Gd64", drtt("Gs64", "Gd64"))
    show("rtt Gd96 - Gd64 (unscored)", drtt("Gd96", "Gd64"))
    show("svc Gd96 - Gd64 (unscored)", dt("Gd96", "Gd64", "svc"))
    show("rtt Bs64 - Bd64 (unscored)", drtt("Bs64", "Bd64"))
    show("svc Bs64 - Bd64 (unscored)", dt("Bs64", "Bd64", "svc"))
    r2s, r2d = med("Gs64", "r2"), med("Gd96", "r2")
    print("  P1  the guest's second read: Gs64 r2 %.2f us, Gd96 r2 %.2f us (want each >= %.0f) -> %s"
          % (r2s, r2d, LONG_READ, verdict("HELD" if r2s >= LONG_READ and r2d >= LONG_READ else "REFUTED")))
    print("  P2  in the service time: svc Gs64 - Gd64 %+.2f us (want >= %+.0f) -> %s"
          % (d_svc, SVC_STEP, verdict("HELD" if d_svc >= SVC_STEP else "REFUTED")))
    print("  P3  the write does not depend on the read mode: w Gs64 - Gd64 %+.2f us (want within %.0f of 0) -> %s"
          % (d_w, WRITE_SAME, verdict("HELD" if abs(d_w) <= WRITE_SAME else "REFUTED")))
    print("  P4  the round trip replicates: rtt Gs64 - Gd64 %+.2f us (want >= %+.0f) -> %s"
          % (d_rtt, RTT_STEP, verdict("HELD" if d_rtt >= RTT_STEP else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
