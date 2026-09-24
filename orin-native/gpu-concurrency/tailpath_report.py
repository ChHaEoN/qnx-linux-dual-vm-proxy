#!/usr/bin/env python3
"""tailpath_report.py OUT N WARMUP -- run-tailpath.sh's decomposition of the tail
(Phase 3b / A6, 2026-09-24), by the rule its header fixed before any run.

For every round whose trace holds exactly WARMUP + N requests, the k-th request is
the probe's k-th exchange; timed sample j is exchange WARMUP + j. Each segmented
timed exchange gets A, B, C, D (blockpath_trace.py) and rest = its round trip minus
A..D. A TAIL exchange is one at or above its round's p99 round trip; its EXCESS in
a segment is its value minus the round's median of that segment. Pooled over every
round's tail exchanges: each segment's median excess, its share of the summed
excess, and which segment carries each exchange's largest excess. P1 is scored
only at k = 24; a failed check prints VOID.
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

SEGS = ["A", "B", "C", "D", "rest"]
SCORED_K = 24


def pct(v, p):
    s = sorted(v)
    return s[int(round(p / 100.0 * (len(s) - 1)))]


def score_p1(med_excess, share):
    """med_excess: {segment: median excess}; share: {segment: share of the summed excess}."""
    top = max(SEGS, key=lambda g: med_excess[g])
    if top != "C":
        return "REFUTED"
    return "HELD" if share["C"] >= 0.5 else "PARTIAL"


def checks(aligned, rounds_total, segmented, timed):
    return {"M1": rounds_total > 0 and aligned / rounds_total >= 0.9,
            "M2": timed > 0 and segmented / timed >= 0.95}


def round_rows(lat, rows, requests, n, warmup):
    """[(rtt_us, row)] for every timed exchange that was segmented, or None if unaligned."""
    if requests != warmup + n:
        return None
    by_k = {r["k"]: r for r in rows}
    out = []
    for j, v in enumerate(lat["samples_in_order"]):
        row = by_k.get(warmup + j)
        if row is not None:
            out.append((v * 1000.0, row))
    return out


def tail_excess(pairs):
    """[(rtt, row)] of one round -> [{segment: excess, 'total': rtt excess, 'row': row}] for its tail."""
    rtts = [p[0] for p in pairs]
    p99 = pct(rtts, 99)
    med = {g: st.median((p[0] - p[1]["total"]) if g == "rest" else p[1][g] for p in pairs) for g in SEGS}
    med_rtt = st.median(rtts)
    out = []
    for rtt, row in pairs:
        if rtt < p99:
            continue
        ex = {g: ((rtt - row["total"]) if g == "rest" else row[g]) - med[g] for g in SEGS}
        ex["total"] = rtt - med_rtt
        ex["row"] = row
        out.append(ex)
    return out


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    aligned, segmented, timed, tails = 0, 0, 0, []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        lat = json.load(open(f))
        bp = os.path.join(out, "bp-t2ms_r%d.log" % r)
        if not os.path.exists(bp):
            continue
        rows, summ = bpt.segments(bpt.read(bp))
        pairs = round_rows(lat, rows, summ["requests"], n, warm)
        if pairs is None:
            print("  round %d not aligned: %d requests traced, %d expected" % (r, summ["requests"], n + warm))
            continue
        aligned += 1
        segmented += len(pairs)
        timed += len(lat["samples_in_order"])
        tails.extend(tail_excess(pairs))
    k = len(files)
    ok = checks(aligned, k, segmented, timed)
    print("  rounds %d, aligned %d; timed exchanges %d, segmented %d; tail exchanges %d"
          % (k, aligned, timed, segmented, len(tails)))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 segmented %.1f%% of timed exchanges (want >= 95%%) -> %s"
          % (100.0 * segmented / max(1, timed), "ok" if ok["M2"] else "FAILED"))
    if not tails:
        print("  no tail exchanges to take apart")
        return 1
    med_ex = {g: st.median(t[g] for t in tails) for g in SEGS}
    tot = sum(t["total"] for t in tails)
    share = {g: sum(t[g] for t in tails) / tot for g in SEGS}
    top_counts = {g: sum(1 for t in tails if max(SEGS, key=lambda x: t[x]) == g) for g in SEGS}
    print("  the tail exchanges' round-trip excess over the round median: median %.1f us, p90 %.1f us"
          % (st.median(t["total"] for t in tails), pct([t["total"] for t in tails], 90)))
    print("  %-5s %12s %14s %18s" % ("seg", "median excess", "share of excess", "largest in (count)"))
    for g in SEGS:
        print("  %-5s %12.1f %13.1f%% %18d" % (g, med_ex[g], 100 * share[g], top_counts[g]))
    blocked = [t["row"]["blocked"] for t in tails]
    print("  tail exchanges' blocked halts in [I, TX]: median %.0f, max %d; wake+load us: median %.1f"
          % (st.median(blocked), max(blocked), st.median(t["row"]["wake_us"] + t["row"]["load_us"] for t in tails)))
    scored = k == SCORED_K
    v = score_p1(med_ex, share)
    if not scored:
        v = "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    elif not (ok["M1"] and ok["M2"]):
        v = "VOID (%s failed)" % ", ".join(m for m in ("M1", "M2") if not ok[m])
    print("  P1  the largest median excess is %s's; C's share %.1f%% -> %s"
          % (max(SEGS, key=lambda g: med_ex[g]), 100 * share["C"], v))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
