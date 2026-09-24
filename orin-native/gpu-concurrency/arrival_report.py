#!/usr/bin/env python3
"""arrival_report.py OUT N WARMUP -- run-arrival.sh's table, its manipulation
checks and its predictions, scored by the thresholds the harness header fixed
before any run (Phase 3b / A6, 2026-09-24). Nothing is scored at k other than
12, and a prediction resting on a failed check prints VOID.
"""
import glob
import json
import os
import re
import statistics as st
import sys

ARMS = ["Dc200us", "De200us", "Dc2ms", "De2ms", "Ac200us", "Ae200us"]
MEAN_MS = {"Dc200us": 0.2, "De200us": 0.2, "Dc2ms": 2.0, "De2ms": 2.0, "Ac200us": 0.2, "Ae200us": 0.2}
EXP_ARMS = ["De200us", "De2ms", "Ae200us"]
SCORED_K = 12
RESTS_ON = {"P1": ("M1", "M2"), "P2": ("M1", "M2"), "P3": ("M1", "M2"), "C1": ("M1",)}


def score_p1(d):
    m = st.median(d)
    return "HELD" if m >= 10 else ("REFUTED" if m <= 3 else "PARTIAL")


def score_p2(share_e200, share_c200):
    if share_e200 >= 0.90:
        return "REFUTED"
    return "HELD" if (share_e200 <= 0.80 and share_c200 >= 0.90) else "PARTIAL"


def score_p3(d):
    return "HELD" if abs(st.median(d)) <= 5 else "FAILED"


def score_c1(d):
    return "HELD" if abs(st.median(d)) <= 3 else "FAILED"


def check_m1(sleeps):
    """sleeps: [(set_mean_ms, recorded mean_ms, recorded sd_ms), ...] for every exponential arm-round."""
    return all(abs(m - want) <= 0.10 * want and 0.8 <= sd / m <= 1.2 for want, m, sd in sleeps)


def check_m2(share_c200, share_c2):
    return share_c200 >= 0.90 and share_c2 <= 0.20


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    lat, kvm = {}, {}
    for a in ARMS:
        lat[a] = {_round(f): json.load(open(f))["summary"] for f in glob.glob("%s/lat-%s_r*.json" % (out, a))}
        kvm[a] = {}
        for f in glob.glob("%s/kvm-%s_r*.json" % (out, a)):
            d = json.load(open(f))
            b, e = d["before"]["counters"], d["after"]["counters"]
            kvm[a][_round(f)] = {k: e[k] - b[k] for k in ("halt_attempted_poll", "halt_successful_poll",
                                                          "halt_wakeup")}
    rounds = sorted(set.intersection(*(set(lat[a]) & set(kvm[a]) for a in ARMS)))
    return lat, kvm, rounds


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    ex = n + warm
    lat, kvm, rounds = load(out)

    def share(k):
        return k["halt_successful_poll"] / k["halt_attempted_poll"] if k["halt_attempted_poll"] else 0.0

    med = {}
    print("  %-8s %-3s %8s %8s %8s %9s %9s %8s %8s" % ("arm", "k", "p50 rtt", "p90 rtt", "p99 rtt", "period",
                                                    "sleep", "ok share", "wake/ex"))
    for a in ARMS:
        L, K = lat[a], kvm[a]
        med[a] = {"share": st.median(share(K[r]) for r in rounds)}
        sl = [L[r]["arrival"]["sleep_ms"]["mean"] for r in rounds] if a in EXP_ARMS else None
        print("  %-8s %-3d %8.1f %8.1f %8.1f %9.1f %9s %8.2f %8.3f"
              % (a, len(rounds), st.median(L[r]["p50_ms"] * 1000 for r in rounds),
                 st.median(L[r]["p90_ms"] * 1000 for r in rounds), st.median(L[r]["p99_ms"] * 1000 for r in rounds),
                 st.median(L[r]["period_us"]["mean"] for r in rounds),
                 ("%.3f ms" % st.median(sl)) if sl else "const", med[a]["share"],
                 st.median(K[r]["halt_wakeup"] / ex for r in rounds)))
    print("  period = the mean achieved period (us); sleep = the mean recorded sleep, exponential arms")
    sleeps = [(MEAN_MS[a], lat[a][r]["arrival"]["sleep_ms"]["mean"], lat[a][r]["arrival"]["sleep_ms"]["sd"])
              for a in EXP_ARMS for r in rounds]
    ok = {"M1": check_m1(sleeps), "M2": check_m2(med["Dc200us"]["share"], med["Dc2ms"]["share"])}
    worst = max(sleeps, key=lambda s: abs(s[1] - s[0]) / s[0])
    print("  M1 exponential sleeps: worst mean off by %.1f%%, sd/mean %.2f-%.2f (want <= 10%%, 0.8-1.2) -> %s"
          % (100 * abs(worst[1] - worst[0]) / worst[0], min(s[2] / s[1] for s in sleeps),
             max(s[2] / s[1] for s in sleeps), "ok" if ok["M1"] else "FAILED"))
    print("  M2 poll success share: Dc200us %.2f (want >= 0.90), Dc2ms %.2f (want <= 0.20) -> %s"
          % (med["Dc200us"]["share"], med["Dc2ms"]["share"], "ok" if ok["M2"] else "FAILED"))
    scored = len(rounds) == SCORED_K

    def verdict(name, v):
        if not scored:
            return "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)
        failed = [m for m in RESTS_ON[name] if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def pair(x, y):
        return [(lat[x][r]["p50_ms"] - lat[y][r]["p50_ms"]) * 1000.0 for r in rounds]

    d = pair("De200us", "Dc200us")
    print("  P1  De200us - Dc200us, p50: median %+.1f us [%+.1f, %+.1f], above zero %d/%d -> %s"
          % (st.median(d), min(d), max(d), sum(x > 0 for x in d), len(d), verdict("P1", score_p1(d))))
    print("  P2  poll success share: De200us %.2f, Dc200us %.2f -> %s"
          % (med["De200us"]["share"], med["Dc200us"]["share"],
             verdict("P2", score_p2(med["De200us"]["share"], med["Dc200us"]["share"]))))
    d = pair("De2ms", "Dc2ms")
    print("  P3  De2ms - Dc2ms, p50: median %+.1f us [%+.1f, %+.1f] -> %s"
          % (st.median(d), min(d), max(d), verdict("P3", score_p3(d))))
    d = pair("Ae200us", "Ac200us")
    print("  C1  Ae200us - Ac200us, p50: median %+.1f us [%+.1f, %+.1f] -> %s"
          % (st.median(d), min(d), max(d), verdict("C1", score_c1(d))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
