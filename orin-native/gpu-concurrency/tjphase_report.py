#!/usr/bin/env python3
"""tjphase_report.py OUT N WARMUP -- run-tjphase.sh's test: does the slow window move
with tj-thermal's poll? (Phase 3b / A6, 2026-09-24), by the rule its header fixed
before any run.

For every round whose trace holds exactly WARMUP + N requests (frames into the tap of
the round's most common length), the k-th request is the probe's k-th exchange; timed
sample j is request WARMUP + j, and its T0 is that request's time. A TAIL exchange is
one at or above its round's p99 round trip. Each timed exchange is put in one class,
first match wins:
  tj     T0 within [-0.5, +6] ms of a traced read of tj-thermal in its round;
  old    T0 within [-0.5, +6] ms of the OLD phase: tj-thermal's reads before the first
         toggle (tp-before.log), extended every 1024 ms;
  other  T0 within [-0.5, +6] ms of a traced read of any other zone in its round;
  out    none of these.
Scored only at k = 24; a prediction resting on a failed check prints VOID.
"""
import cmath
import glob
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 24
ZONE = "tj-thermal"
PERIOD = 1024000.0              # us: 256 jiffies at HZ=250
BEFORE, AFTER = 500.0, 6000.0   # us: a read's window
AWAY = 32000.0                  # us: a moved poll is at least this far from the old phase
MIN_IN = 30
LATE = 4500.0                   # us: the old reads may lag the earliest by up to one jiffy (4 ms)


def pct(v, p):
    s = sorted(v)
    return s[int(round(p / 100.0 * (len(s) - 1)))]


def cdist(a, b, period=PERIOD):
    """Circular distance between two phases."""
    d = (a - b) % period
    return min(d, period - d)


def old_phase(reads):
    """(phase, spread) of the tj reads before the first toggle, or (None, None). The
    phase is the EARLIEST read's: the poll's timer keeps its jiffy, but the read can run
    a jiffy late (found by the smoke run: two reads 1020 ms apart, not 1024). The spread
    is the latest read's lag behind it."""
    if len(reads) < 2:
        return None, None
    z = sum(cmath.exp(2j * math.pi * (t % PERIOD) / PERIOD) for t in reads) / len(reads)
    mean = (cmath.phase(z) % (2 * math.pi)) / (2 * math.pi) * PERIOD
    lags = [((t - mean + PERIOD / 2) % PERIOD) - PERIOD / 2 for t in reads]     # signed, around the mean
    return (mean + min(lags)) % PERIOD, max(lags) - min(lags)


def near(t0, reads):
    return any(r - BEFORE <= t0 <= r + AFTER for r in reads)


def near_phase(t0, ph):
    d = (t0 - ph) % PERIOD
    return d <= AFTER or d >= PERIOD - BEFORE


def classify(t0, tj, old, other):
    if near(t0, tj):
        return "tj"
    if old is not None and near_phase(t0, old):
        return "old"
    if near(t0, other):
        return "other"
    return "out"


def score_ratio_high(r_in, r_out):
    """P1: HELD at >= 10x, PARTIAL at >= 3x, else REFUTED."""
    if r_out == 0:
        return "HELD" if r_in > 0 else "REFUTED"
    x = r_in / r_out
    return "HELD" if x >= 10 else ("PARTIAL" if x >= 3 else "REFUTED")


QUIET = 10.0                    # %: a class's tail rate below this is quiet (P2, P3)


def score_quiet(r_in):
    """P2, P3: HELD when the class's tail rate (%) is below QUIET."""
    return "HELD" if r_in < QUIET else "REFUTED"


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    before = os.path.join(out, "tp-before.log")
    b_reads = [t for t, e, f in tjt.read(before) if e == "T" and f == ZONE] if os.path.exists(before) else []
    old, spread = old_phase(b_reads)
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    counts = {c: [0, 0] for c in ("tj", "old", "other", "out")}      # [exchanges, tail]
    aligned = with_tj = with_other = moved = 0
    phases = []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        if not os.path.exists(tp):
            continue
        ev = tjt.read(tp)
        lens = [int(x) for _, e, x in ev if e == "X" and int(x) >= 100]
        req_len = max(set(lens), key=lens.count) if lens else None
        reqs = [t for t, e, x in ev if e == "X" and int(x) == req_len]
        lat = json.load(open(f))["samples_in_order"]
        if len(reqs) != warm + n or len(lat) != n:
            print("  round %d not aligned: %d requests traced, %d expected" % (r, len(reqs), warm + n))
            continue
        aligned += 1
        t0s = reqs[warm:]
        tj = [t for t, e, z in ev if e == "T" and z == ZONE]
        other = [t for t, e, z in ev if e == "T" and z != ZONE]
        if any(t0s[0] <= t <= t0s[-1] for t in tj):
            with_tj += 1
        if any(t0s[0] <= t <= t0s[-1] for t in other):
            with_other += 1
        if tj and old is not None and all(cdist(t % PERIOD, old) >= AWAY for t in tj):
            moved += 1
        phases += [round((t % PERIOD) / 1000.0, 1) for t in tj[:1]]
        rtt = [v * 1000.0 for v in lat]
        p99 = pct(rtt, 99)
        for t0, v in zip(t0s, rtt):
            c = classify(t0, tj, old, other)
            counts[c][0] += 1
            counts[c][1] += v >= p99
    k = len(files)
    rate = {c: (100.0 * t / e if e else float("nan")) for c, (e, t) in counts.items()}
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": aligned > 0 and with_tj / aligned >= 0.9 and counts["tj"][0] >= MIN_IN,
          "M3": old is not None and spread <= LATE and aligned > 0 and moved / aligned >= 0.8
          and counts["old"][0] >= MIN_IN,
          "M4": aligned > 0 and with_other / aligned >= 0.9 and counts["other"][0] >= MIN_IN}
    print("  rounds %d, aligned %d" % (k, aligned))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 a tj-thermal read inside the timed span in %d of %d rounds (want >= 90%%), %d exchanges in its"
          " windows (want >= %d) -> %s" % (with_tj, aligned, counts["tj"][0], MIN_IN, "ok" if ok["M2"] else "FAILED"))
    if old is None:
        print("  M3 no old phase: fewer than 2 tj-thermal reads before the first toggle -> FAILED")
    else:
        print("  M3 old phase %.1f ms (the latest read %.2f ms behind the earliest); moved >= %.0f ms away in %d of %d rounds (want >= 80%%);"
              " %d exchanges in its windows (want >= %d) -> %s"
              % (old / 1000.0, spread / 1000.0, AWAY / 1000.0, moved, aligned, counts["old"][0], MIN_IN,
                 "ok" if ok["M3"] else "FAILED"))
    print("  M4 another zone's read inside the timed span in %d of %d rounds (want >= 90%%), %d exchanges in its"
          " windows (want >= %d) -> %s" % (with_other, aligned, counts["other"][0], MIN_IN, "ok" if ok["M4"] else "FAILED"))
    print("  tj-thermal's first read in each round, ms into the 1024 ms cycle:", phases)
    print("  %-6s %10s %6s %10s" % ("class", "exchanges", "tail", "tail rate"))
    for c in ("tj", "old", "other", "out"):
        print("  %-6s %10d %6d %9.2f%%" % (c, counts[c][0], counts[c][1], rate[c]))
    scored = k == SCORED_K
    v1 = verdict(score_ratio_high(rate["tj"], rate["out"]), scored, k, ok, ["M1", "M2", "M3"])
    v2 = verdict(score_quiet(rate["other"]), scored, k, ok, ["M1", "M4"])
    v3 = verdict(score_quiet(rate["old"]), scored, k, ok, ["M1", "M3"])
    ratio = lambda c: rate[c] / rate["out"] if rate["out"] else float("inf")
    print("  P1  the tail follows the moved poll: tj windows %.1fx the outside rate -> %s" % (ratio("tj"), v1))
    print("  P2  other zones' reads do not: their windows' tail rate %.2f%% (quiet below %.0f%%) -> %s"
          % (rate["other"], QUIET, v2))
    print("  P3  the old phase goes quiet: its windows' tail rate %.2f%% (quiet below %.0f%%) -> %s"
          % (rate["old"], QUIET, v3))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
