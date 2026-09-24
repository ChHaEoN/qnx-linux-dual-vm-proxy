#!/usr/bin/env python3
"""power_report.py OUT -- run-power.sh's table, its manipulation checks and its
predictions, scored by the thresholds the harness header fixed before any run
(Phase 3b / A6, 2026-09-24). Each arm's power is the mean of the rail samples
(power_window.py) inside that arm's KVM snapshots (the same CLOCK_MONOTONIC).
Nothing is scored at k other than 6, and a prediction resting on a failed check
prints VOID.
"""
import glob
import json
import os
import re
import statistics as st
import sys

ARMS = ["Nidle", "N200us", "N2ms", "Didle", "D200us", "D2ms", "Bidle", "B200us", "B2ms"]
CPU = "VDD_CPU_GPU_CV"
RAILS = ["VDD_IN", "VDD_CPU_GPU_CV", "VDD_SOC"]
SCORED_K = 6
RESTS_ON = {"P1": ("M1a", "M2"), "P2": ("M2",), "P3": ("M1b", "M2")}


def score_p1(d):
    m, up = st.median(d), sum(x > 0 for x in d)
    if m >= 150 and up == len(d):
        return "HELD"
    return "REFUTED" if m <= 30 else "PARTIAL"


def score_p2(d):
    return "HELD" if abs(st.median(d)) <= 30 else "FAILED"


def score_p3(d):
    m = st.median(d)
    return "HELD" if m >= 100 else ("REFUTED" if m <= 20 else "PARTIAL")


def checks(share, nsamp):
    """share: {arm: median busiest-thread share}; nsamp: every arm-round's sample count."""
    return {"M1a": share["B2ms"] >= 0.8 and share["D2ms"] <= 0.2,
            "M1b": share["D200us"] >= 0.5 and share["N200us"] <= 0.3,
            "M2": min(nsamp) >= 200}


def window_power(pw, kv):
    """{rail: mean mW} and the sample count, inside the KVM snapshots' window."""
    t0, t1 = kv["before"]["t_ns"], kv["after"]["t_ns"]
    idx = {r: i + 1 for i, r in enumerate(pw["rails"])}
    inside = [s for s in pw["samples"] if t0 <= s[0] <= t1]
    out = {r: (st.mean(s[idx[r]] for s in inside) if inside else float("nan")) for r in pw["rails"]}
    return out, len(inside)


def busiest_share(kv):
    t0, t1 = kv["before"], kv["after"]
    win = t1["t_ns"] - t0["t_ns"]
    shares = [(t1["threads"][t]["run_ns"] - t0["threads"][t]["run_ns"]) / win
              for t in t1.get("threads", {}) if t in t0.get("threads", {})]
    return max(shares) if shares and win > 0 else 0.0


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    per = {a: {} for a in ARMS}
    for a in ARMS:
        for f in glob.glob("%s/pw-%s_r*.json" % (out, a)):
            r = _round(f)
            kp = os.path.join(out, "kvm-%s_r%d.json" % (a, r))
            if not os.path.exists(kp):
                continue
            pw, kv = json.load(open(f)), json.load(open(kp))
            p, n = window_power(pw, kv)
            lat = os.path.join(out, "lat-%s_r%d.json" % (a, r))
            p50 = json.load(open(lat))["summary"]["p50_ms"] * 1000.0 if os.path.exists(lat) else None
            per[a][r] = {"p": p, "n": n, "share": busiest_share(kv), "p50": p50}
    rounds = sorted(set.intersection(*(set(per[a]) for a in ARMS)))
    return per, rounds


def main(argv):
    out = argv[0]
    per, rounds = load(out)
    print("  per arm, median over %d rounds: mean power in the window (mW), QEMU's busiest thread's share, p50"
          % len(rounds))
    print("  %-7s %9s %15s %9s  %7s %6s %8s" % ("arm", "VDD_IN", "VDD_CPU_GPU_CV", "VDD_SOC", "busiest", "n", "p50 us"))
    share = {}
    for a in ARMS:
        P = per[a]
        share[a] = st.median(P[r]["share"] for r in rounds)
        p50 = [P[r]["p50"] for r in rounds if P[r]["p50"] is not None]
        print("  %-7s %9.0f %15.0f %9.0f  %7.2f %6d %8s"
              % (a, *(st.median(P[r]["p"].get(x, float("nan")) for r in rounds) for x in RAILS), share[a],
                 min(P[r]["n"] for r in rounds), ("%.1f" % st.median(p50)) if p50 else "-"))
    nsamp = [per[a][r]["n"] for a in ARMS for r in rounds]
    ok = checks(share, nsamp)
    print("  M1a busiest share: B2ms %.2f (want >= 0.8), D2ms %.2f (want <= 0.2) -> %s"
          % (share["B2ms"], share["D2ms"], "ok" if ok["M1a"] else "FAILED"))
    print("  M1b busiest share: D200us %.2f (want >= 0.5), N200us %.2f (want <= 0.3) -> %s"
          % (share["D200us"], share["N200us"], "ok" if ok["M1b"] else "FAILED"))
    print("  M2  fewest samples in a window: %d (want >= 200) -> %s" % (min(nsamp), "ok" if ok["M2"] else "FAILED"))
    scored = len(rounds) == SCORED_K

    def verdict(name, v):
        if not scored:
            return "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)
        failed = [m for m in RESTS_ON[name] if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def pair(x, y, rail):
        return [per[x][r]["p"][rail] - per[y][r]["p"][rail] for r in rounds]

    for name, x, y, fn in (("P1", "B2ms", "D2ms", score_p1), ("P2", "Bidle", "Didle", score_p2),
                           ("P3", "D200us", "N200us", score_p3)):
        d = pair(x, y, CPU)
        print("  %s  %-6s - %-6s %s: median %+7.0f mW [%+.0f, %+.0f], above zero %d/%d -> %s"
              % (name, x, y, CPU, st.median(d), min(d), max(d), sum(v > 0 for v in d), len(d),
                 verdict(name, fn(d))))
    print("  UNSCORED, paired within round, median [min, max] mW:")
    for x, y in (("B2ms", "D2ms"), ("Bidle", "Didle"), ("D200us", "N200us"), ("B200us", "D200us"),
                 ("Didle", "Nidle"), ("D2ms", "N2ms")):
        cells = []
        for rail in RAILS:
            d = pair(x, y, rail)
            cells.append("%s %+6.0f [%+.0f, %+.0f]" % (rail, st.median(d), min(d), max(d)))
        print("    %-6s - %-6s %s" % (x, y, "   ".join(cells)))
    d_lat = [per["D2ms"][r]["p50"] - per["B2ms"][r]["p50"] for r in rounds]
    d_w = [(per["B2ms"][r]["p"]["VDD_IN"] - per["D2ms"][r]["p"]["VDD_IN"]) / 1000.0 for r in rounds]
    print("  the trade at 2 ms: B saves %.1f us at p50 for %+.2f W at VDD_IN (%.0f us per W)"
          % (st.median(d_lat), st.median(d_w), st.median(d_lat) / st.median(d_w) if st.median(d_w) > 0 else float("nan")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
