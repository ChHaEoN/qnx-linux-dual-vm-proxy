#!/usr/bin/env python3
"""haltpoll_report.py OUT N WARMUP -- run-haltpoll.sh's table, its manipulation
checks and its predictions, scored by the thresholds the harness header fixed
before any run (Phase 3b / A6, 2026-09-24). In its own file so a test can hold
the scoring to those thresholds; the harness and the record's analysis both call
it.

Per arm, medians over rounds: the round trip and the monitor's own time at p50,
the rest, the idle gap, and the VM's halt counters per exchange (attempted and
successful polls, the success share, blocked wake-ups). A prediction resting on
a failed manipulation check prints VOID. Nothing is scored at k other than 12.

Two things are printed UNSCORED, added after review (they are not in the
pre-registered block and decide nothing):
  - the two busiest QEMU threads' share of each arm's window, from the schedstat
    m_kvm_snap captures. A 5 ms window keeps a vCPU spinning where D lets it
    sleep; this shows how much host CPU that took.
  - the within-boot contrasts (X2ms - X200us) - (D2ms - D200us), which cancel any
    offset a single boot carries.
"""
import glob
import json
import os
import re
import statistics as st
import sys

ARMS = ["N200us", "N2ms", "D200us", "D2ms", "B200us", "B2ms"]
SCORED_K = 12


def score_p1(d):
    """N200us - N2ms, round trip us, per round."""
    m = st.median(d)
    return "HELD" if m >= -15 else ("REFUTED" if m <= -30 else "PARTIAL")


def score_p2(d):
    """B2ms - D2ms, round trip us, per round."""
    m = st.median(d)
    return "HELD" if m <= -30 else ("REFUTED" if m >= -15 else "PARTIAL")


def score_p3a(d):
    """N200us - D200us, monitor ticks, per round."""
    m, up = st.median(d), sum(v > 0 for v in d)
    if m >= 4 and up >= 10:
        return "HELD"
    return "REFUTED" if m <= 1 else "PARTIAL"


def score_p3b(d):
    """B2ms - D2ms, monitor ticks, per round."""
    m, down = st.median(d), sum(v < 0 for v in d)
    if m <= -4 and down >= 10:
        return "HELD"
    return "REFUTED" if m >= -1 else "PARTIAL"


def score_c1(rtt_d, mon_d):
    """B200us - D200us: round trip us and monitor ticks, per round."""
    return "HELD" if abs(st.median(rtt_d)) <= 5 and abs(st.median(mon_d)) <= 1 else "FAILED"


def checks(n_attempted_total, wake_b2, wake_d2, share_d200, share_d2):
    """The manipulation checks: {name: bool}."""
    return {"M1": n_attempted_total == 0,
            "M2": wake_b2 <= 0.5 * wake_d2,
            "M3": share_d200 >= 0.9 and share_d2 <= 0.2}


RESTS_ON = {"P1": ("M1",), "P3a": ("M1", "M3"), "P2": ("M2", "M3"), "P3b": ("M2", "M3"), "C1": ("M2", "M3")}


def _round(path):
    return int(re.search(r"_r(\d+)\.", os.path.basename(path)).group(1))


def load(out):
    lat, kvm, busy = {}, {}, {}
    for a in ARMS:
        lat[a] = {_round(f): json.load(open(f))["summary"] for f in glob.glob("%s/lat-%s_r*.json" % (out, a))}
        kvm[a], busy[a] = {}, {}
        for f in glob.glob("%s/kvm-%s_r*.json" % (out, a)):
            d = json.load(open(f))
            b, e = d["before"]["counters"], d["after"]["counters"]
            keys = ("halt_attempted_poll", "halt_successful_poll", "halt_wakeup")
            if any(not isinstance(b.get(k), int) or not isinstance(e.get(k), int) for k in keys):
                raise SystemExit("%s: a halt counter was unreadable (NA); this arm-round cannot be used" % f)
            kvm[a][_round(f)] = {k: e[k] - b[k] for k in keys}
            win = d["after"].get("t_ns", 0) - d["before"].get("t_ns", 0)
            tb, ta = d["before"].get("threads", {}), d["after"].get("threads", {})
            shares = sorted(((ta[t]["run_ns"] - tb[t]["run_ns"]) / win for t in ta if t in tb and win > 0),
                            reverse=True)
            busy[a][_round(f)] = (shares + [0.0, 0.0])[:2]
    rounds = sorted(set.intersection(*(set(lat[a]) & set(kvm[a]) for a in ARMS)))
    return lat, kvm, busy, rounds


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
    lat, kvm, busy, rounds = load(out)

    def ticks(us):
        return us * 1000.0 / tick_ns

    def share(k):
        return k["halt_successful_poll"] / k["halt_attempted_poll"] if k["halt_attempted_poll"] else 0.0

    med = {}
    print("  %-7s %-3s %8s %8s %6s %8s %8s  %8s %8s %8s %8s"
          % ("arm", "k", "rtt", "monitor", "ticks", "rest", "idle gap", "att/ex", "ok/ex", "ok share", "wake/ex"))
    for a in ARMS:
        L, Kv = lat[a], kvm[a]
        rtt = st.median(L[r]["p50_ms"] * 1000.0 for r in rounds)
        mon = st.median(L[r]["server_us"]["p50"] for r in rounds)
        med[a] = {"share": st.median(share(Kv[r]) for r in rounds),
                  "wake": st.median(Kv[r]["halt_wakeup"] / ex for r in rounds)}
        print("  %-7s %-3d %8.2f %8.3f %6.1f %8.2f %8.1f  %8.3f %8.3f %8.2f %8.3f"
              % (a, len(rounds), rtt, mon, ticks(mon), st.median(L[r]["other_us"]["p50"] for r in rounds),
                 st.median(L[r]["period_us"]["p50"] for r in rounds) - rtt,
                 st.median(Kv[r]["halt_attempted_poll"] / ex for r in rounds),
                 st.median(Kv[r]["halt_successful_poll"] / ex for r in rounds), med[a]["share"], med[a]["wake"]))
    print("  tick = %.1f ns; counters are the VM's (both vCPUs), per exchange over the arm" % tick_ns)

    n_att = sum(kvm[a][r]["halt_attempted_poll"] for a in ("N200us", "N2ms") for r in rounds)
    ok = checks(n_att, med["B2ms"]["wake"], med["D2ms"]["wake"], med["D200us"]["share"], med["D2ms"]["share"])
    print("  M1 N arms' attempted polls, all rounds: %d (want 0) -> %s" % (n_att, "ok" if ok["M1"] else "FAILED"))
    print("  M2 blocked wake-ups per exchange, B2ms %.3f vs D2ms %.3f (want <= half) -> %s"
          % (med["B2ms"]["wake"], med["D2ms"]["wake"], "ok" if ok["M2"] else "FAILED"))
    print("  M3 poll success share, D200us %.2f (want >= 0.9), D2ms %.2f (want <= 0.2) -> %s"
          % (med["D200us"]["share"], med["D2ms"]["share"], "ok" if ok["M3"] else "FAILED"))

    scored = len(rounds) == SCORED_K

    def verdict(name, v):
        if not scored:
            return "not scored (k=%d; the predictions are for k=%d)" % (len(rounds), SCORED_K)
        failed = [m for m in RESTS_ON[name] if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def rtt_pair(x, y):
        return [(lat[x][r]["p50_ms"] - lat[y][r]["p50_ms"]) * 1000.0 for r in rounds]

    def mon_pair(x, y):
        return [ticks(lat[x][r]["server_us"]["p50"]) - ticks(lat[y][r]["server_us"]["p50"]) for r in rounds]

    def show(name, what, d, unit, v, below=False):
        side, cnt = ("below", sum(x < 0 for x in d)) if below else ("above", sum(x > 0 for x in d))
        print("  %-3s %-26s median %+6.1f %-5s [%+.1f, %+.1f], %s zero %d/%d -> %s"
              % (name, what, st.median(d), unit, min(d), max(d), side, cnt, len(d), verdict(name, v)))

    d = rtt_pair("N200us", "N2ms")
    show("P1", "N200us - N2ms, rtt", d, "us", score_p1(d))
    d = rtt_pair("B2ms", "D2ms")
    show("P2", "B2ms - D2ms, rtt", d, "us", score_p2(d), below=True)
    d = mon_pair("N200us", "D200us")
    show("P3a", "N200us - D200us, monitor", d, "ticks", score_p3a(d))
    d = mon_pair("B2ms", "D2ms")
    show("P3b", "B2ms - D2ms, monitor", d, "ticks", score_p3b(d), below=True)
    rd, md = rtt_pair("B200us", "D200us"), mon_pair("B200us", "D200us")
    print("  C1  B200us - D200us: rtt median %+.1f us [%+.1f, %+.1f], monitor median %+.1f ticks [%+.1f, %+.1f]"
          " -> %s" % (st.median(rd), min(rd), max(rd), st.median(md), min(md), max(md),
                      verdict("C1", score_c1(rd, md))))

    print("  UNSCORED, added after review:")
    print("    the two busiest QEMU threads' share of the arm's window (median over rounds):")
    for a in ARMS:
        print("      %-7s %.2f  %.2f" % (a, st.median(busy[a][r][0] for r in rounds),
                                      st.median(busy[a][r][1] for r in rounds)))
    print("    within-boot contrasts, (X2ms - X200us) - (D2ms - D200us), median [min, max]:")
    for x in ("N", "B"):
        rt = [((lat[x + "2ms"][r]["p50_ms"] - lat[x + "200us"][r]["p50_ms"])
               - (lat["D2ms"][r]["p50_ms"] - lat["D200us"][r]["p50_ms"])) * 1000.0 for r in rounds]
        mo = [(ticks(lat[x + "2ms"][r]["server_us"]["p50"]) - ticks(lat[x + "200us"][r]["server_us"]["p50"]))
              - (ticks(lat["D2ms"][r]["server_us"]["p50"]) - ticks(lat["D200us"][r]["server_us"]["p50"]))
              for r in rounds]
        print("      %s: rtt %+.1f us [%+.1f, %+.1f]   monitor %+.1f ticks [%+.1f, %+.1f]"
              % (x, st.median(rt), min(rt), max(rt), st.median(mo), min(mo), max(mo)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
