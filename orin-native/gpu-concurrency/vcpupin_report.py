#!/usr/bin/env python3
"""vcpupin_report.py OUT N WARMUP -- run-vcpupin.sh's table and its three
predictions, scored by the thresholds the harness header fixed before any run
(Phase 3b / A6, 2026-09-24). In its own file so a test can hold the scoring to
those thresholds; the harness and the record's analysis both call it.

Per arm, medians over rounds: the round trip, the monitor's own time (in µs and
in counter ticks), the rest, the idle gap, the halt-poll success share, blocked
wake-ups, and from the sched_switch trace the vCPU switch-ins, migrations and
flush conditions (switch_trace.py), all per exchange. The trace is counted inside
the KVM snapshots' window, like the counters beside it; "sw/wake" is its
switch-ins over KVM's wake-ups there, the evidence that it saw them.

The predictions are scored only at k = 12, the k they were written for.
"""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import switch_trace  # noqa: E402

ARMS = ["S200us", "S2ms", "O200us", "O2ms"]
SCORED_K = 12


def score_p1(diffs):
    """O2ms - S2ms, monitor p50 in ticks, one value per round."""
    m, neg = st.median(diffs), sum(v < 0 for v in diffs)
    if m <= -4 and neg >= 10:
        return "HELD"
    if m >= -1:
        return "REFUTED"
    return "PARTIAL"


def score_p2(diffs):
    """O200us - S200us, monitor p50 in ticks, one value per round."""
    return "HELD" if abs(st.median(diffs)) <= 1 else "FAILED"


def score_p3(flush_s2, flush_s200, flush_o_total):
    """Per-exchange medians for the S arms; the O arms' total count."""
    held = "HELD" if (flush_s2 >= 0.5 and flush_s200 < 0.1) else "FAILED"
    return held, ("ok" if flush_o_total == 0 else "PINNING BROKEN")


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    lat, kvm, sw = {}, {}, {}
    for a in ARMS:
        lat[a] = {_round(f): json.load(open(f))["summary"] for f in glob.glob("%s/lat-%s_r*.json" % (out, a))}
        kvm[a] = {}
        for f in glob.glob("%s/kvm-%s_r*.json" % (out, a)):
            d = json.load(open(f))
            b, e = d["before"]["counters"], d["after"]["counters"]
            kvm[a][_round(f)] = {k: e[k] - b[k] for k in ("halt_attempted_poll", "halt_successful_poll",
                                                          "halt_wakeup")}
        sw[a] = {}
        for f in glob.glob("%s/sw-%s_r*.log" % (out, a)):
            k = os.path.join(os.path.dirname(f), "kvm-%s.json" % os.path.basename(f)[len("sw-"):-len(".log")])
            sw[a][_round(f)] = switch_trace.check(f, k, a[0])[0]
    rounds = sorted(set.intersection(*(set(lat[a]) & set(kvm[a]) & set(sw[a]) for a in ARMS)))
    return lat, kvm, sw, rounds


def tick_ns_of(out):
    m = re.search(r"running at ([0-9.]+)MHz", json.load(open(out + "/stamp.json")).get("counter", ""))
    return 1000.0 / float(m.group(1)) if m else None


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    ex = n + warm
    tick_ns = tick_ns_of(out)
    if tick_ns is None:
        print("no counter frequency in stamp.json: the predictions are in ticks and cannot be scored")
        return 1
    lat, kvm, sw, rounds = load(out)

    def ticks(us):
        return us * 1000.0 / tick_ns

    print("  %-7s %-3s %8s %8s %6s %8s %8s  %8s %8s  %8s %8s %8s %8s"
          % ("arm", "k", "rtt", "monitor", "ticks", "rest", "idle gap", "ok share", "wake/ex",
             "sw-in/ex", "migr/ex", "flush/ex", "sw/wake"))
    for a in ARMS:
        L, Kv, Sw = lat[a], kvm[a], sw[a]
        rtt = st.median(L[r]["p50_ms"] * 1000.0 for r in rounds)
        mon = st.median(L[r]["server_us"]["p50"] for r in rounds)
        print("  %-7s %-3d %8.2f %8.3f %6.1f %8.2f %8.1f  %8.2f %8.3f  %8.3f %8.3f %8.3f %8.2f"
              % (a, len(rounds), rtt, mon, ticks(mon), st.median(L[r]["other_us"]["p50"] for r in rounds),
                 st.median(L[r]["period_us"]["p50"] for r in rounds) - rtt,
                 st.median(Kv[r]["halt_successful_poll"] / max(1, Kv[r]["halt_attempted_poll"]) for r in rounds),
                 st.median(Kv[r]["halt_wakeup"] / ex for r in rounds),
                 st.median(Sw[r]["switch_ins"] / ex for r in rounds),
                 st.median(Sw[r]["migrations"] / ex for r in rounds),
                 st.median(Sw[r]["flush_cond"] / ex for r in rounds),
                 st.median(Sw[r]["switch_ins"] / max(1, Sw[r]["kvm_halt_wakeup"]) for r in rounds)))
    print("  tick = %.1f ns; flush = a vCPU switched in on a core where the other vCPU was the last"
          " switched in (switch_trace.py)" % tick_ns)

    def mon_pair(x, y):
        return [ticks(lat[x][r]["server_us"]["p50"]) - ticks(lat[y][r]["server_us"]["p50"]) for r in rounds]

    scored = len(rounds) == SCORED_K

    def verdict(v):
        return v if scored else "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)

    p1 = mon_pair("O2ms", "S2ms")
    print("  P1 monitor p50, O2ms - S2ms: median %+.1f ticks [%+.1f, %+.1f], below zero %d/%d -> %s"
          % (st.median(p1), min(p1), max(p1), sum(v < 0 for v in p1), len(p1), verdict(score_p1(p1))))
    p2 = mon_pair("O200us", "S200us")
    print("  P2 monitor p50, O200us - S200us: median %+.1f ticks [%+.1f, %+.1f] -> %s"
          % (st.median(p2), min(p2), max(p2), verdict(score_p2(p2))))
    f2 = st.median(sw["S2ms"][r]["flush_cond"] / ex for r in rounds)
    f02 = st.median(sw["S200us"][r]["flush_cond"] / ex for r in rounds)
    fo = sum(sw[a][r]["flush_cond"] for a in ("O200us", "O2ms") for r in rounds)
    held, pin = score_p3(f2, f02, fo)
    print("  P3 flush per exchange: S2ms %.3f (want >= 0.5), S200us %.3f (want < 0.1) -> %s;"
          " O arms total %d (must be 0: %s)" % (f2, f02, verdict(held), fo, pin))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
