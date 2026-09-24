#!/usr/bin/env python3
"""smp_report.py OUT N WARMUP -- run-smp.sh's table, its manipulation checks and
its predictions, scored by the thresholds the harness header fixed before any run
(Phase 3b / A6, 2026-09-24). The segments come from blockpath_trace.py. In its own
file so a test can hold the scoring to those thresholds. Nothing is scored at k
other than 12, and a prediction resting on a failed check prints VOID.
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

ARMS = ["2D200us", "2D2ms", "2B200us", "2B2ms", "1D200us", "1D2ms", "1B200us", "1B2ms"]
SCORED_K = 12
RESTS_ON = {"P1": ("M1", "M2"), "P2": ("M1",), "P3": ("M1", "M2")}


def score_p1(blocked_p50_1d2ms):
    """The median over rounds of 1D2ms's per-round median blocked halts in [I, TX]."""
    return "HELD" if blocked_p50_1d2ms <= 1 else "REFUTED"


def score_p2(d):
    """1D2ms - 2D2ms, round trip us, per round."""
    m = st.median(d)
    return "HELD" if m <= -10 else ("REFUTED" if m >= -3 else "PARTIAL")


def score_p3(d):
    """(2D2ms - 2B2ms) - (1D2ms - 1B2ms), round trip us, per round."""
    m = st.median(d)
    return "HELD" if m >= 8 else ("REFUTED" if m <= 2 else "PARTIAL")


def checks(first_blocked_1d2ms, first_blocked_1b2ms, blocked_2d2ms):
    return {"M1": first_blocked_1d2ms >= 0.9 and first_blocked_1b2ms <= 0.1,
            "M2": blocked_2d2ms == 3}


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    per = {}
    for a in ARMS:
        per[a] = {}
        for f in glob.glob("%s/lat-%s_r*.json" % (out, a)):
            r = _round(f)
            bp = os.path.join(out, "bp-%s_r%d.log" % (a, r))
            if not os.path.exists(bp):
                continue
            _, summ = bpt.segments(bpt.read(bp))
            per[a][r] = {"rtt": json.load(open(f))["summary"]["p50_ms"] * 1000.0, "seg": summ}
    rounds = sorted(set.intersection(*(set(per[a]) for a in ARMS)))
    return per, rounds


def main(argv):
    out = argv[0]
    per, rounds = load(out)

    def med(a, k):
        return st.median(per[a][r]["seg"][k] for r in rounds)

    print("  per arm, median over %d rounds of each round's median (us); counts per exchange" % len(rounds))
    print("  %-8s %7s %6s %6s %6s %6s %7s %6s  %5s %5s %6s %6s %6s"
          % ("arm", "rtt", "A", "B", "C", "D", "A..D", "rest", "blk", "poll", "wake", "load", "1st bl"))
    for a in ARMS:
        rtt = st.median(per[a][r]["rtt"] for r in rounds)
        print("  %-8s %7.1f %6.1f %6.1f %6.1f %6.1f %7.1f %6.1f  %5.2f %5.2f %6.1f %6.1f %6.2f"
              % (a, rtt, med(a, "A_p50"), med(a, "B_p50"), med(a, "C_p50"), med(a, "D_p50"), med(a, "total_p50"),
                 st.median(per[a][r]["rtt"] - per[a][r]["seg"]["total_p50"] for r in rounds),
                 med(a, "blocked_p50"), med(a, "polled_p50"), med(a, "wake_us_p50"), med(a, "load_us_p50"),
                 med(a, "first_halt_blocked_share")))

    def rtt_pair(x, y):
        return [per[x][r]["rtt"] - per[y][r]["rtt"] for r in rounds]

    ok = checks(med("1D2ms", "first_halt_blocked_share"), med("1B2ms", "first_halt_blocked_share"),
                med("2D2ms", "blocked_p50"))
    print("  M1 first halt blocked: 1D2ms %.2f (want >= 0.9), 1B2ms %.2f (want <= 0.1) -> %s"
          % (med("1D2ms", "first_halt_blocked_share"), med("1B2ms", "first_halt_blocked_share"),
             "ok" if ok["M1"] else "FAILED"))
    print("  M2 2D2ms blocked halts in [I, TX]: %.1f (want 3) -> %s"
          % (med("2D2ms", "blocked_p50"), "ok" if ok["M2"] else "FAILED"))
    scored = len(rounds) == SCORED_K

    def verdict(name, v):
        if not scored:
            return "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)
        failed = [m for m in RESTS_ON[name] if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    b1 = med("1D2ms", "blocked_p50")
    print("  P1  1D2ms blocked halts in [I, TX]: %.1f (2D2ms %.1f) -> %s"
          % (b1, med("2D2ms", "blocked_p50"), verdict("P1", score_p1(b1))))
    d = rtt_pair("1D2ms", "2D2ms")
    print("  P2  1D2ms - 2D2ms, rtt: median %+.1f us [%+.1f, %+.1f], below zero %d/%d -> %s"
          % (st.median(d), min(d), max(d), sum(x < 0 for x in d), len(d), verdict("P2", score_p2(d))))
    d = [a - b for a, b in zip(rtt_pair("2D2ms", "2B2ms"), rtt_pair("1D2ms", "1B2ms"))]
    print("  P3  (2D2ms - 2B2ms) - (1D2ms - 1B2ms), rtt: median %+.1f us [%+.1f, %+.1f], above zero %d/%d -> %s"
          % (st.median(d), min(d), max(d), sum(x > 0 for x in d), len(d), verdict("P3", score_p3(d))))
    print("  NOT PREDICTED, paired within round, rtt median [min, max] us:")
    for x, y in (("1B2ms", "2B2ms"), ("1D200us", "2D200us"), ("1B200us", "2B200us"),
                 ("2D2ms", "2B2ms"), ("1D2ms", "1B2ms")):
        d = rtt_pair(x, y)
        print("    %-8s - %-8s %+6.1f [%+.1f, %+.1f]" % (x, y, st.median(d), min(d), max(d)))
    print("  and segment C, blocked - polled at 2 ms: two vCPUs %+.1f us, one vCPU %+.1f us"
          % (st.median(per["2D2ms"][r]["seg"]["C_p50"] - per["2B2ms"][r]["seg"]["C_p50"] for r in rounds),
             st.median(per["1D2ms"][r]["seg"]["C_p50"] - per["1B2ms"][r]["seg"]["C_p50"] for r in rounds)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
