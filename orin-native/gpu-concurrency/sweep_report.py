#!/usr/bin/env python3
"""sweep_report.py OUT -- run-sweep.sh's test: how the round trip grows with the frame, through
the guest (G) and on the host alone (B), by the rule the harness's header fixed before any run
(measurement-design.md section 3.4; Phase 3b / A6, 2026-09-26).

Per round r and path X: the p50 of each arm; d_X(S) = p50(X_S) - p50(X_64). Per path, the
median over rounds with the distribution-free interval d(j)..d(k+1-j) of widest coverage
>= 95% (d(6)..d(15), 95.9%, at k = 20). The line is the least-squares fit of d_X(S) on S over
the sizes below one segment (S <= 1280); a residual is a size's median minus the line, and a
step at S above one segment is d_X(S) minus the line extrapolated, per round. The counters give
packets per exchange through the arm's device (tx: requests, rx: replies).
"""
import glob
import json
import os
import re
import statistics as st
import sys
from math import comb

SIZES = (64, 96, 256, 512, 768, 1024, 1280, 1536, 1792, 2048)
BELOW = tuple(s for s in SIZES if s <= 1280)
ABOVE = tuple(s for s in SIZES if s > 1280)
PATHS = ("G", "B")
LINEAR = 3.0          # P1: us, every residual below one segment, each path
MAX_SLOPE = 10.0      # P2: ns per byte, the guest path's slope
STEP = 5.0            # P3: us, the guest path's step at 1536 B against the extrapolated line
STEP_EXPECTED = False  # P3: the header's prediction (no step), fixed before any run
MAX_PKTS = 1.2        # P4: packets per exchange each way that still means "one packet"


def interval(vals):
    """(lo, hi, coverage): the widest-coverage symmetric order-statistic interval >= 95%."""
    v, k = sorted(vals), len(vals)
    best = (v[0], v[-1], 1.0 - 2.0 * 0.5 ** k)
    for j in range(1, k // 2 + 1):
        cov = 1.0 - 2.0 * sum(comb(k, i) for i in range(j)) / 2.0 ** k
        if cov >= 0.95:
            best = (v[j - 1], v[k - j], cov)
    return best


def fit(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def load(out):
    p50, fb, stats = {}, {}, {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-([GB])(\d+)_r(\d+)\.json$", f)
        if not m:
            continue
        s = json.load(open(f))["summary"]
        key = (m.group(1), int(m.group(2)), int(m.group(3)))
        p50[key] = s["p50_ms"] * 1000.0
        fb[key] = s.get("frame_bytes")
        stats[key] = (s.get("n"), s.get("bad"), s.get("rejected_by_monitor"))
    cnt = {}
    p = os.path.join(out, "counters.log")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            m = re.match(r"([GB])(\d+)_r(\d+)$", f[0]) if len(f) == 7 else None
            if m:
                cnt.setdefault((m.group(1), int(m.group(2)), int(m.group(3))), {})[f[2]] = [int(x) for x in f[3:]]
    return p50, fb, stats, cnt


def main(argv):
    out = argv[0]
    p50, fb, stats, cnt = load(out)
    rounds = sorted({r for _, _, r in p50})
    k = len(rounds)
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    ex = (n_want or 1000) + warm          # exchanges per arm, warm-up included: the counters see them all
    keys = [(x, s, r) for x in PATHS for s in SIZES for r in rounds]
    ok = {"M1": k > 0 and all(key in stats and stats[key][1] == 0 and stats[key][2] == 0
                               and (n_want is None or stats[key][0] == n_want) for key in keys),
          "M2": k > 0 and all(fb.get(key) == key[1] for key in keys),
          "M3": k > 0 and all(set(cnt.get(key, {})) >= {"before", "after"} for key in keys)}
    print("  rounds %d" % k)
    print("  M1 every arm has %d rounds of n samples, none rejected, none bad -> %s" % (k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 every arm's summary records its own frame size -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm has its counters before and after -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not ok["M1"]:
        print("  (an arm is missing or unclean; nothing below is scored)")

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    d, med, res, slope, step, pk = {}, {}, {}, {}, {}, {}
    for x in PATHS:
        for r in rounds:
            base = p50.get((x, 64, r))
            for s in SIZES:
                if base is not None and (x, s, r) in p50:
                    d[(x, s, r)] = p50[(x, s, r)] - base
        full = [r for r in rounds if all((x, s, r) in d for s in SIZES)]
        med[x] = {s: st.median(d[(x, s, r)] for r in full) if full else float("nan") for s in SIZES}
        if full:
            a, b = fit(BELOW, [med[x][s] for s in BELOW])
            res[x] = {s: med[x][s] - (a + b * s) for s in SIZES}
        slope[x], step[x] = {}, {}
        for r in full:
            a, b = fit(BELOW, [d[(x, s, r)] for s in BELOW])
            slope[x][r] = b * 1000.0
            step[x][r] = {s: d[(x, s, r)] - (a + b * s) for s in ABOVE}
        for s in SIZES:
            per = []
            for r in rounds:
                c = cnt.get((x, s, r), {})
                if "before" in c and "after" in c:
                    dl = [e - b_ for b_, e in zip(c["before"], c["after"])]
                    per.append((dl[1] / ex, dl[0] / ex, (dl[3] / dl[1]) if dl[1] else 0.0, (dl[2] / dl[0]) if dl[0] else 0.0))
            pk[(x, s)] = tuple(st.median(p[i] for p in per) for i in range(4)) if per else (float("nan"),) * 4

    print("  per size, medians over rounds (us); packets per exchange tx (requests) / rx (replies), bytes per packet")
    print("  %6s %9s %9s %9s %9s %9s  %11s %11s  %13s %13s" % ("S", "d_G", "d_B", "G-B", "resid G", "resid B",
                                                              "G pkt tx/rx", "B pkt tx/rx", "G bytes/pkt", "B bytes/pkt"))
    for s in SIZES:
        print("  %6d %9.2f %9.2f %9.2f %9.2f %9.2f  %5.2f/%5.2f %5.2f/%5.2f  %6.0f/%6.0f %6.0f/%6.0f"
              % (s, med["G"][s], med["B"][s], med["G"][s] - med["B"][s], res.get("G", {}).get(s, float("nan")),
                 res.get("B", {}).get(s, float("nan")), pk[("G", s)][0], pk[("G", s)][1], pk[("B", s)][0],
                 pk[("B", s)][1], pk[("G", s)][2], pk[("G", s)][3], pk[("B", s)][2], pk[("B", s)][3]))
    for x in PATHS:
        if slope[x]:
            lo, hi, cov = interval(list(slope[x].values()))
            print("  slope %s below one segment: %.2f ns/B per round trip [%.2f, %.2f] (%.1f%%)"
                  % (x, st.median(slope[x].values()), lo, hi, 100 * cov))

    worst = {x: max(abs(res[x][s]) for s in BELOW) if x in res else float("nan") for x in PATHS}
    print("  P1  no step below one segment: largest |residual| G %.2f, B %.2f us; at 256 B G %+.2f, B %+.2f "
          "(want each <= %.0f) -> %s"
          % (worst["G"], worst["B"], res.get("G", {}).get(256, float("nan")), res.get("B", {}).get(256, float("nan")),
             LINEAR, verdict("HELD" if all(worst[x] <= LINEAR for x in PATHS) else "REFUTED")))
    both = [r for r in rounds if r in slope["G"] and r in slope["B"]]
    if both:
        diff = [slope["G"][r] - slope["B"][r] for r in both]
        lo, hi, cov = interval(diff)
        sg = st.median(slope["G"].values())
        print("  P2  the guest's per-byte cost: slope G %.2f ns/B (want <= %.0f), G - B %.2f [%.2f, %.2f] (%.1f%%, want > 0) -> %s"
              % (sg, MAX_SLOPE, st.median(diff), lo, hi, 100 * cov,
                 verdict("HELD" if sg <= MAX_SLOPE and lo > 0 else "REFUTED")))
        s15 = [step["G"][r][1536] for r in slope["G"]]
        lo, hi, cov = interval(s15)
        m15 = st.median(s15)
        if STEP_EXPECTED is None:
            v = "NOT SCORED (no prediction set)"
        elif STEP_EXPECTED:
            v = verdict("HELD" if lo >= STEP else "REFUTED")
        else:
            v = verdict("HELD" if abs(m15) <= STEP else "REFUTED")
        print("  P3  the guest's step at 1536 B against the line: %+.2f us [%+.2f, %+.2f] (%.1f%%; %s) -> %s"
              % (m15, lo, hi, 100 * cov, "want the interval >= %.0f" % STEP if STEP_EXPECTED
                 else "want |median| <= %.0f" % STEP, v))
    over = {s: pk[("G", s)][:2] for s in ABOVE}
    print("  P4  no segmentation on the guest path: packets per exchange tx/rx %s (want each <= %.1f) -> %s"
          % (", ".join("%d B %.2f/%.2f" % (s, t, r) for s, (t, r) in over.items()), MAX_PKTS,
             verdict("HELD" if all(t <= MAX_PKTS and r <= MAX_PKTS for t, r in over.values()) else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
