#!/usr/bin/env python3
"""tailhost_report.py OUT N WARMUP -- run-tailhost.sh's test of the host's share of
the tail (Phase 3b / A6, 2026-09-24), by the rule its header fixed before any run.

Alignment and the tail are run-tailpath.sh's: for a round whose trace holds exactly
WARMUP + N requests, timed sample j is exchange WARMUP + j; a TAIL exchange is at or
above its round's p99 round trip. Each timed exchange's window is its T0 (request
into the tap) to its reply out, and hostact_trace.py charges to it the host's
handler time on QEMU's threads and their preempted time (H). The EXCESS of a tail
exchange is its value minus its round's median. Scored only at k = 24; a
prediction resting on a failed check prints VOID.
"""
import cmath
import glob
import json
import math
import os
import random
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blockpath_trace as bpt  # noqa: E402
import hostact_trace as hat  # noqa: E402
import tailpath_report as tp  # noqa: E402

SCORED_K = 24
GRID = 32000.0                  # us: 8 jiffies at HZ=250, the timer wheel's level-1 granularity
CLASSES = ["irq", "softirq", "ipi", "preempted"]
SEED, DRAWS = 1, 1000


def circ(ts, period):
    """(R, mean phase in [0, period)) of times ts at the given period."""
    z = sum(cmath.exp(2j * math.pi * (t % period) / period) for t in ts) / len(ts)
    return abs(z), (cmath.phase(z) % (2 * math.pi)) / (2 * math.pi) * period


def wrap(d, period):
    """d folded into (-period/2, period/2]."""
    d = d % period
    return d - period if d > period / 2 else d


def score_p1(r_tail, r_p99, dist_ms):
    if r_tail <= r_p99:
        return "REFUTED"
    return "HELD" if abs(dist_ms) <= 2.0 else "PARTIAL"


def score_p2(share):
    if share >= 0.5:
        return "HELD"
    return "PARTIAL" if share >= 0.2 else "REFUTED"


def score_p3(class_excess):
    return "HELD" if max(CLASSES, key=lambda c: class_excess[c]) == "softirq" else "REFUTED"


def checks(aligned, rounds_total, segmented, timed, with_act, known, grid_r):
    return {"M1": rounds_total > 0 and aligned / rounds_total >= 0.9,
            "M2": timed > 0 and segmented / timed >= 0.95,
            "M3": aligned > 0 and with_act == aligned,
            "M4": segmented > 0 and known / segmented >= 0.99,
            "M5": grid_r is not None and grid_r >= 0.1}


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    aligned = segmented = timed = with_act = known = 0
    all_t0, tails, timers, jiffies = [], [], [], []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        lat = json.load(open(f))
        bp = os.path.join(out, "bp-t2ms_r%d.log" % r)
        if not os.path.exists(bp):
            continue
        ev = bpt.read(bp)
        lens = [int(e[3][0]) for e in ev if e[2] == "X" and int(e[3][0]) >= 100]
        req_len = max(set(lens), key=lens.count) if lens else None
        rows, summ = bpt.segments(ev, req_len=req_len)
        pairs = tp.round_rows(lat, rows, summ["requests"], n, warm)
        if pairs is None:
            print("  round %d not aligned: %d requests traced, %d expected" % (r, summ["requests"], n + warm))
            continue
        aligned += 1
        segmented += len(pairs)
        timed += len(lat["samples_in_order"])
        ha = os.path.join(out, "ha-t2ms_r%d.log" % r)
        if not os.path.exists(ha):
            print("  round %d has no host-activity trace" % r)
            continue
        with_act += 1
        hev = hat.read(ha)
        act = hat.Activity(hev)
        timers += [t for t, _, _ in act.timers]
        jiffies += [j for _, _, j in act.timers]
        start = act.known_from(sorted({e[1] for e in hev}))
        charged = []
        for rtt, row in pairs:
            a, b = row["t0"], row["t0"] + row["total"]
            if start is not None and a >= start:
                known += 1
            c = act.charge(a, b)
            c["H"] = sum(c[k] for k in CLASSES)
            charged.append((rtt, row, c))
            all_t0.append(a)
        p99 = tp.pct([x[0] for x in charged], 99)
        med = {k: st.median(x[2][k] for x in charged) for k in CLASSES + ["H"]}
        med["total"] = st.median(x[1]["total"] for x in charged)
        med_keys = {}
        for x in charged:
            for key in x[2]["keys"]:
                med_keys.setdefault(key, None)
        for key in med_keys:
            med_keys[key] = st.median(x[2]["keys"].get(key, 0.0) for x in charged)
        for rtt, row, c in charged:
            if rtt < p99:
                continue
            ex = {k: c[k] - med[k] for k in CLASSES + ["H"]}
            ex["total"] = row["total"] - med["total"]
            ex["t0"] = row["t0"]
            ex["keys"] = {key: c["keys"].get(key, 0.0) - med_keys[key] for key in med_keys}
            tails.append(ex)
    k = len(files)
    grid_r, grid_ph = circ(timers, GRID) if timers else (None, None)
    ok = checks(aligned, k, segmented, timed, with_act, known, grid_r)
    print("  rounds %d, aligned %d, with host activity %d; timed exchanges %d, segmented %d; tail exchanges %d"
          % (k, aligned, with_act, timed, segmented, len(tails)))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 segmented %.1f%% of timed exchanges (want >= 95%%) -> %s"
          % (100.0 * segmented / max(1, timed), "ok" if ok["M2"] else "FAILED"))
    print("  M3 host-activity trace for %d of %d aligned rounds (want all) -> %s"
          % (with_act, aligned, "ok" if ok["M3"] else "FAILED"))
    print("  M4 %.2f%% of segmented windows start after every traced core's task is known (want >= 99%%) -> %s"
          % (100.0 * known / max(1, segmented), "ok" if ok["M4"] else "FAILED"))
    if grid_r is None:
        print("  M5 no timer callbacks traced -> FAILED")
    else:
        print("  M5 timer callbacks %d, their R at 32 ms %.3f at phase %.2f ms (want R >= 0.1) -> %s"
              % (len(timers), grid_r, grid_ph / 1000.0, "ok" if ok["M5"] else "FAILED"))
        print("  unscored: %.1f%% of timer callbacks ran at jiffies = 0 mod 8 (1/8 = 12.5%% if uniform)"
              % (100.0 * sum(1 for j in jiffies if j % 8 == 0) / len(jiffies)))
    if not tails:
        print("  no tail exchanges")
        return 1
    scored = k == SCORED_K

    # P1: the tail's phase against the timer grid
    r_tail, ph_tail = circ([t["t0"] for t in tails], GRID)
    rng = random.Random(SEED)
    rs = sorted(circ(rng.sample(all_t0, len(tails)), GRID)[0] for _ in range(DRAWS))
    r_p99 = rs[int(0.99 * (DRAWS - 1))]
    dist = wrap(ph_tail - grid_ph, GRID) / 1000.0 if grid_ph is not None else float("nan")
    v1 = verdict(score_p1(r_tail, r_p99, dist), scored, k, ok, ["M1", "M2", "M3", "M5"])
    print("  P1  the tail's R at 32 ms %.3f (random subsets' p99 %.3f), its phase %.2f ms, %+.2f ms from the"
          " timers' -> %s" % (r_tail, r_p99, ph_tail / 1000.0, dist, v1))

    # P2: the host's charge against the traced span's excess
    tot = sum(t["total"] for t in tails)
    share = sum(t["H"] for t in tails) / tot if tot > 0 else float("nan")
    print("  the tail exchanges' traced-span excess: median %.1f us; their H excess: median %.1f us"
          % (st.median(t["total"] for t in tails), st.median(t["H"] for t in tails)))
    p2 = score_p2(share)
    v2 = verdict(p2, scored, k, ok, ["M1", "M2", "M3", "M4"])
    print("  P2  H's share of the summed excess %.1f%% -> %s" % (100 * share, v2))

    # P3: which class carries it
    cex = {c: sum(t[c] for t in tails) for c in CLASSES}
    print("  %-10s %16s %14s" % ("class", "summed excess us", "share of H's"))
    hsum = sum(cex.values())
    for c in CLASSES:
        print("  %-10s %16.1f %13.1f%%" % (c, cex[c], 100 * cex[c] / hsum if hsum else float("nan")))
    if scored and p2 == "REFUTED":
        v3 = "not scored (P2 REFUTED: the host's charge is not the tail)"
    else:
        v3 = verdict(score_p3(cex), scored, k, ok, ["M1", "M2", "M3", "M4"])
    print("  P3  the largest class is %s -> %s" % (max(CLASSES, key=lambda c: cex[c]), v3))

    # unscored: the keys that carry it
    keys = {}
    for t in tails:
        for key, v in t["keys"].items():
            keys[key] = keys.get(key, 0.0) + v
    print("  unscored, the largest keys of the tail's summed H excess:")
    for key, v in sorted(keys.items(), key=lambda kv: -kv[1])[:10]:
        print("    %-45s %10.1f us" % (key, v))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
