#!/usr/bin/env python3
"""stats_review.py -- a statistical second look at a run record (Phase 3b / A6,
2026-09-24; suggestion 3 of the literature pass: Kalibera & Jones, ISMM 2013).

  stats_review.py RECORD_DIR --pairs X:Y[,X:Y...] [--arms A,B,...] [--reps 10000] [--run-log PATH]

For every pair X - Y, paired within round, of the per-round p50 round trips:
  - the median difference, as every record reports it;
  - a DISTRIBUTION-FREE confidence interval for that median: the order statistics
    d(j) and d(k-j+1) with the largest j for which the sign test's coverage is at
    least 95% (for k = 12: d(3) and d(10), coverage 96.1%);
  - a percentile BOOTSTRAP 95% interval, resampling rounds (seeded, so repeatable).
For every arm listed (default: every arm in the pairs):
  - VARIANCE COMPONENTS in the two-level form of Kalibera & Jones (their equations
    1-3), adapted from means to medians. Level 1 is the exchange, level 2 the round
    (a round is also a fresh VM boot in the designs that boot per round). The
    within-round sampling variance of a round's median, v, comes from a bootstrap
    of that round's samples, and stands in for their S1^2 / r1. So
    T2^2 = S2^2 - mean(v) (between rounds, S2^2 the variance of the round medians)
    and T1^2 = mean(v) * r1 (per exchange). A T2^2 at or below zero means the round
    level adds nothing that the sampling does not already explain.
  - their equation 3, r1 = ceil(sqrt((c2 / c1) * T1^2 / T2^2)): the number of
    exchanges per arm-round that buys the most precision per unit of time, given
    c1, the time per exchange (the achieved period), and c2, the time an arm-round
    adds beyond its exchanges (from the run log's round times).
  - lag-1 and lag-10 AUTOCORRELATION of the timed samples in their send order, on
    ranks (so a few huge samples do not dominate), median over rounds; and the
    share of rounds whose lag-1 value is outside +-2/sqrt(n), the rough 95% band
    for no correlation.
It reads only lat-*.json (summary, samples_in_order) and run.log (RECORD_DIR/run.log
unless --run-log names another; the AWS captures keep it one level up).
"""
import argparse
import glob
import json
import math
import os
import random
import re
import statistics as st


def exact_ci_ranks(k, conf=0.95):
    """(j, coverage): the median's interval is [d(j), d(k-j+1)] (1-based order stats)."""
    best = None
    for j in range(1, k // 2 + 1):
        tail = sum(math.comb(k, i) for i in range(j)) / 2 ** k        # P(Bin(k, 1/2) <= j-1)
        cov = 1 - 2 * tail
        if cov >= conf:
            best = (j, cov)
    return best if best else (1, 1 - 2 / 2 ** k)


def exact_median_ci(d, conf=0.95):
    s = sorted(d)
    j, cov = exact_ci_ranks(len(s), conf)
    return s[j - 1], s[len(s) - j], cov


def bootstrap_median_ci(d, reps=10000, seed=20260924, conf=0.95):
    rng = random.Random(seed)
    k = len(d)
    meds = sorted(st.median(rng.choice(d) for _ in range(k)) for _ in range(reps))
    lo = meds[int(round((1 - conf) / 2 * (reps - 1)))]
    hi = meds[int(round((1 + conf) / 2 * (reps - 1)))]
    return lo, hi


def within_median_var(samples, reps=200, seed=1):
    rng = random.Random(seed)
    n = len(samples)
    meds = [st.median(rng.choice(samples) for _ in range(n)) for _ in range(reps)]
    return st.pvariance(meds)


def variance_components(per_round_samples, reps=200):
    """per_round_samples: list of sample lists (one per round). Returns a dict."""
    medians = [st.median(s) for s in per_round_samples]
    v = [within_median_var(s, reps, seed=i + 1) for i, s in enumerate(per_round_samples)]
    r1 = st.median(len(s) for s in per_round_samples)
    s2 = st.pvariance(medians)                       # biased, as their S2^2
    t2 = s2 - st.mean(v)
    t1 = st.mean(v) * r1
    return {"k": len(medians), "r1": r1, "S2": s2, "v_mean": st.mean(v), "T2": t2, "T1": t1,
            "sd_between": math.sqrt(max(t2, 0.0)), "sd_median_within": math.sqrt(st.mean(v))}


def optimal_r1(c1, c2, t1, t2):
    """Kalibera & Jones equation 3, two levels. None when the round level adds nothing."""
    if t2 <= 0:
        return None
    return math.ceil(math.sqrt((c2 / c1) * t1 / t2))


def rank_autocorr(x, lag):
    n = len(x)
    if n <= lag + 2:
        return float("nan")
    order = sorted(range(n), key=lambda i: x[i])
    r = [0.0] * n
    for pos, i in enumerate(order):
        r[i] = float(pos)
    m = st.mean(r)
    num = sum((r[i] - m) * (r[i + lag] - m) for i in range(n - lag))
    den = sum((v - m) ** 2 for v in r)
    return num / den if den else float("nan")


def round_seconds(run_log):
    """Median seconds between consecutive 'round r/K done' lines, or None."""
    ts = []
    for line in open(run_log, encoding="utf-8", errors="replace"):
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\] round \d+/\d+ done", line)
        if m:
            ts.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    gaps = [(b - a) % 86400 for a, b in zip(ts, ts[1:])]
    return st.median(gaps) if gaps else None


def load(rec):
    lat = {}
    for f in glob.glob(os.path.join(rec, "lat-*.json")):
        m = re.match(r"lat-(.+)_r(\d+)\.json$", os.path.basename(f))
        if m:
            lat.setdefault(m.group(1), {})[int(m.group(2))] = json.load(open(f))
    return lat


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--arms", default="")
    ap.add_argument("--reps", type=int, default=10000)
    ap.add_argument("--run-log", default="")
    a = ap.parse_args(argv)
    lat = load(a.record)
    pairs = [p.split(":") for p in a.pairs.split(",")]
    arms = a.arms.split(",") if a.arms else sorted({x for p in pairs for x in p})
    rounds = sorted(set.intersection(*(set(lat[x]) for x in arms + [y for p in pairs for y in p])))
    print("record %s: %d rounds in every arm used" % (os.path.basename(os.path.normpath(a.record)), len(rounds)))
    j, cov = exact_ci_ranks(len(rounds))
    print("paired p50 differences, us: median; distribution-free CI [d(%d), d(%d)] (coverage %.1f%%);"
          " bootstrap 95%% CI (rounds resampled, %d reps)" % (j, len(rounds) - j + 1, 100 * cov, a.reps))
    for x, y in pairs:
        d = [(lat[x][r]["summary"]["p50_ms"] - lat[y][r]["summary"]["p50_ms"]) * 1000.0 for r in rounds]
        lo, hi, _ = exact_median_ci(d)
        blo, bhi = bootstrap_median_ci(d, a.reps)
        excl = "excludes 0" if (lo > 0 or hi < 0) else "includes 0"
        print("  %-9s - %-9s %+8.2f   exact [%+.2f, %+.2f] %s   bootstrap [%+.2f, %+.2f]"
              % (x, y, st.median(d), lo, hi, excl, blo, bhi))
    log = a.run_log or os.path.join(a.record, "run.log")
    rs = round_seconds(log) if os.path.exists(log) else None
    n_arms_total = len(lat)
    print("variance components per arm (us^2 unless noted); c1 = achieved period; c2 = an arm-round's time"
          " beyond its exchanges%s" % (" (round %.0f s over %d arms)" % (rs, n_arms_total) if rs else " (no run.log)"))
    print("  %-9s %3s %5s %9s %9s %9s  %8s %8s  %6s %6s %5s  %6s %6s %5s"
          % ("arm", "k", "r1", "S2", "mean v", "T2", "sd_betw", "sd_med", "c1 ms", "c2 s", "r1opt",
             "ac1", "ac10", "|ac1|>"))
    exch_total = None
    for arm in arms:
        per = [[v * 1000.0 for v in lat[arm][r]["samples_in_order"]] for r in rounds]
        vc = variance_components(per)
        per_s = [lat[arm][r]["summary"].get("period_us", {}).get("p50") for r in rounds]
        c1 = (st.median(p for p in per_s if p) / 1e6) if any(per_s) else None
        c2 = None
        if rs and c1:
            warm = lat[arm][rounds[0]]["summary"].get("warmup_discarded", 0)
            if exch_total is None:
                exch_total = sum(
                    (lat[b][rounds[0]]["summary"]["n"] + lat[b][rounds[0]]["summary"].get("warmup_discarded", 0))
                    * (lat[b][rounds[0]]["summary"].get("period_us", {}).get("p50") or 0) / 1e6
                    for b in lat)
            c2 = max(rs - exch_total, 0.0) / n_arms_total
        r1opt = optimal_r1(c1, c2, vc["T1"], vc["T2"]) if (c1 and c2) else None
        acs = [rank_autocorr(lat[arm][r]["samples_in_order"], 1) for r in rounds]
        ac10 = [rank_autocorr(lat[arm][r]["samples_in_order"], 10) for r in rounds]
        n = vc["r1"]
        out = sum(abs(v) > 2 / math.sqrt(n) for v in acs)
        print("  %-9s %3d %5d %9.2f %9.2f %9.2f  %8.2f %8.2f  %6s %6s %5s  %+6.3f %+6.3f %2d/%d"
              % (arm, vc["k"], vc["r1"], vc["S2"], vc["v_mean"], vc["T2"], vc["sd_between"],
                 vc["sd_median_within"], "%.3f" % (c1 * 1000) if c1 else "-", "%.1f" % c2 if c2 is not None else "-",
                 str(r1opt) if r1opt else ("-" if not (c1 and c2) else "no T2"),
                 st.median(acs), st.median(ac10), out, len(acs)))
    print("  sd_betw = sqrt(T2), the spread of round medians beyond sampling; sd_med = the sampling sd of one"
          " round's median. r1opt: exchanges per arm-round that buy the most precision per unit time"
          " (equation 3); 'no T2' when the round level adds nothing. ac1/ac10: rank autocorrelation of the"
          " samples in send order, median over rounds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
