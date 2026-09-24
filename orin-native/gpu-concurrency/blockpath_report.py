#!/usr/bin/env python3
"""blockpath_report.py OUT N WARMUP -- run-blockpath.sh's table: per arm, the
median over rounds of each round's median segment (blockpath_trace.py), the round
trip, the untraced rest, and the counts per exchange. Then blocked against polled
at each spacing, paired within round, segment by segment, with the share of the
round-trip difference that the traced segments account for (Phase 3b / A6,
2026-09-24). A decomposition: nothing is scored.
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

ARMS = ["N200us", "N2ms", "D200us", "D2ms", "B200us", "B2ms"]
KEYS = ["A", "B", "C", "D", "total"]
CONTRASTS = [("D2ms", "B2ms", "blocked - polled at 2 ms"), ("N200us", "D200us", "blocked - polled at 0.2 ms")]


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    """{arm: {round: {"rtt": us, "seg": summary}}}, rounds present in every arm."""
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


def contrast(per, rounds, x, y, key):
    """Per round, x - y of a segment's median (or of the round trip, key 'rtt')."""
    get = (lambda a, r: per[a][r]["rtt"]) if key == "rtt" else (lambda a, r: per[a][r]["seg"][key + "_p50"])
    return [get(x, r) - get(y, r) for r in rounds]


def main(argv):
    out = argv[0]
    per, rounds = load(out)
    print("  per arm, median over %d rounds of each round's median (us); counts per exchange" % len(rounds))
    print("  %-7s %7s %7s %7s %7s %7s %7s %7s  %6s %6s %6s %6s %7s %7s %6s"
          % ("arm", "rtt", "A", "B", "C", "D", "A..D", "rest", "seg'd", "blk", "poll", "m_wk",
             "wake", "load", "1st bl"))
    for a in ARMS:
        P = per[a]

        def m(k):
            return st.median(P[r]["seg"][k] for r in rounds)
        rtt = st.median(P[r]["rtt"] for r in rounds)
        rest = st.median(P[r]["rtt"] - P[r]["seg"]["total_p50"] for r in rounds)
        seg = st.median(P[r]["seg"]["segmented"] / max(1, P[r]["seg"]["requests"]) for r in rounds)
        print("  %-7s %7.1f %7.1f %7.1f %7.1f %7.1f %7.1f %7.1f  %6.2f %6.2f %6.2f %6.2f %7.1f %7.1f %6.2f"
              % (a, rtt, m("A_p50"), m("B_p50"), m("C_p50"), m("D_p50"), m("total_p50"), rest, seg,
                 m("blocked_p50"), m("polled_p50"), m("m_wakes_p50"), m("wake_us_p50"), m("load_us_p50"),
                 m("first_halt_blocked_share")))
    print("  A: request into the tap -> interrupt raised; B: -> the vCPU's halt ends; C: -> the transmit")
    print("  notify; D: -> the reply out of the tap. rest = rtt - (A..D), the untraced host path.")
    print("  seg'd: share of requests segmented; blk/poll: halts ending blocked/polled inside [I, TX];")
    print("  m_wk: QEMU-main wakings by a vCPU in [V, OUT]; wake/load: us per exchange spent from a")
    print("  blocked vCPU's waking to its switch-in, and from there to its halt's end; 1st bl: share")
    print("  of exchanges whose first halt end after the interrupt was a blocked one.")
    for x, y, what in CONTRASTS:
        print()
        print("  %s (%s - %s), paired within round: median [min, max] us" % (what, x, y))
        d_rtt = contrast(per, rounds, x, y, "rtt")
        for key in KEYS:
            d = contrast(per, rounds, x, y, key)
            print("    %-6s %+7.1f [%+.1f, %+.1f]" % (key if key != "total" else "A..D", st.median(d), min(d), max(d)))
        print("    %-6s %+7.1f [%+.1f, %+.1f]" % ("rtt", st.median(d_rtt), min(d_rtt), max(d_rtt)))
        d_tot = contrast(per, rounds, x, y, "total")
        share = st.median(d_tot) / st.median(d_rtt) if st.median(d_rtt) else float("nan")
        print("    the traced segments account for %.0f%% of the round trip's difference" % (100 * share))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
