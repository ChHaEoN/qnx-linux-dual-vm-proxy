#!/usr/bin/env python3
"""tail_report.py OUT -- run-tail.sh's table, its manipulation check and its
predictions, scored by the thresholds the harness header fixed before any run
(Phase 3b / A6, 2026-09-24). Also, unscored: each factor alone, with
distribution-free intervals (stats_review.py), and where a tail sample's time
went (the monitor's own span or the rest). Nothing is scored at k other than 12.
"""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stats_review  # noqa: E402

ARMS = ["base", "irq", "fifo", "iso"]
SCORED_K = 12
RESTS_ON = {"P1": ("M1",), "P2": ("M1",), "P3": ("M1",)}
KEYS = [("p50_ms", "p50"), ("p90_ms", "p90"), ("p99_ms", "p99"), ("p999_ms", "p99.9"), ("max_ms", "max")]


def score_p1(d):
    m, below = st.median(d), sum(x < 0 for x in d)
    if m <= -5 and below >= 9:
        return "HELD"
    return "REFUTED" if m >= 0 else "PARTIAL"


def score_p2(d):
    m, below = st.median(d), sum(x < 0 for x in d)
    if m < 0 and below >= 8:
        return "HELD"
    return "REFUTED" if m >= 0 else "PARTIAL"


def score_p3(d):
    return "HELD" if abs(st.median(d)) <= 3 else "FAILED"


def check_m1(counts):
    """counts: moved-irq firings on cores 0-2, one per irq/iso arm-round."""
    return max(counts) <= 2 if counts else False


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def irq_on_qemu_cores(out, tag):
    """The moved interrupts' firings on cores 0-2 between the arm's two snapshots."""
    def read(p):
        d = {}
        for line in open(p):
            f = line.split()
            if len(f) >= 7:
                d[f[0]] = [int(x) for x in f[1:7]]
        return d
    b, a = read(os.path.join(out, "irq-%s.before" % tag)), read(os.path.join(out, "irq-%s.after" % tag))
    return sum(sum(a[k][c] - b[k][c] for c in (0, 1, 2)) for k in a if k in b)


def load(out):
    lat = {}
    for a in ARMS:
        lat[a] = {_round(f): json.load(open(f)) for f in glob.glob("%s/lat-%s_r*.json" % (out, a))}
    rounds = sorted(set.intersection(*(set(lat[a]) for a in ARMS)))
    return lat, rounds


def main(argv):
    out = argv[0]
    lat, rounds = load(out)
    irq = {a: {r: irq_on_qemu_cores(out, "%s_r%d" % (a, r)) for r in rounds} for a in ARMS}
    print("  per arm, median over %d rounds (us); moved irqs on cores 0-2 per arm-round; samples over 0.5 ms"
          % len(rounds))
    print("  %-5s %8s %8s %8s %8s %9s  %9s %8s %10s" % ("arm", "p50", "p90", "p99", "p99.9", "max",
                                                      "irqs 0-2", ">0.5ms", "mon p99"))
    for a in ARMS:
        S = {r: lat[a][r]["summary"] for r in rounds}
        over = [sum(1 for v in lat[a][r]["samples_in_order"] if v > 0.5) for r in rounds]
        print("  %-5s %8.1f %8.1f %8.1f %8.1f %9.1f  %9.0f %8.1f %10.2f"
              % (a, *(st.median(S[r][k] * 1000 for r in rounds) for k, _ in KEYS),
                 st.median(irq[a][r] for r in rounds), st.median(over),
                 st.median(S[r]["server_us"]["p99"] for r in rounds)))
    moved = [irq[a][r] for a in ("irq", "iso") for r in rounds]
    ok = {"M1": check_m1(moved)}
    print("  M1 moved irqs on cores 0-2 in irq/iso arm-rounds: max %d (want <= 2); base median %.0f -> %s"
          % (max(moved), st.median(irq["base"][r] for r in rounds), "ok" if ok["M1"] else "FAILED"))
    scored = len(rounds) == SCORED_K

    def verdict(name, v):
        if not scored:
            return "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)
        failed = [m for m in RESTS_ON[name] if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def pair(x, y, key):
        return [(lat[x][r]["summary"][key] - lat[y][r]["summary"][key]) * 1000.0 for r in rounds]

    for name, key, fn in (("P1", "p99_ms", score_p1), ("P2", "p999_ms", score_p2), ("P3", "p50_ms", score_p3)):
        d = pair("iso", "base", key)
        print("  %s  iso - base, %-6s median %+7.1f us [%+.1f, %+.1f], below zero %d/%d -> %s"
              % (name, key[:-3], st.median(d), min(d), max(d), sum(x < 0 for x in d), len(d),
                 verdict(name, fn(d))))
    print("  UNSCORED: each factor, paired within round, median; distribution-free 96.1% interval")
    for x in ("iso", "irq", "fifo"):
        for key, lab in KEYS:
            d = pair(x, "base", key)
            lo, hi, _ = stats_review.exact_median_ci(d)
            print("    %-4s - base %-5s %+8.1f us  [%+.1f, %+.1f]" % (x, lab, st.median(d), lo, hi))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
