#!/usr/bin/env python3
"""bellrate_report.py OUT -- run-bellrate.sh's doorbell against the console kick at three spacings,
by the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-29).

Arms K2/B2 (2 ms constant), Kf/Bf (0.2 ms constant), Ke/Be (exponential, 2 ms mean, the same seed
for both in a round); K is the console kick in, B the MSI-X doorbell in. For a spacing x, S(x) =
B - K at p50 and W(x) = halt_wakeup per exchange of K minus that of B, paired within the round.
P1 scores S(0.2) - S(2), P2 S(exp) - S(2), P3 W(2) - W(0.2). The interval is the distribution-free
one of widest coverage >= 95%. KVM's counters are per exchange (warm-up included).
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("K2", "B2", "Kf", "Bf", "Ke", "Be")
PROTO = {"K": "shmdb", "B": "shmbell"}
SPACING = {"2": (2.0, "const"), "f": (0.2, "const"), "e": (2.0, "exp")}
P1_HELD, P2_BAND, M5_POLL_RISE, M5_IDLE_US = 3.0, 5.0, 0.5, 450.0
PCT = ("p50_ms", "p90_ms", "p99_ms", "p999_ms")
BANNER_K = re.compile(r"serving shm-kick on .*slot @4096.* kick /dev/vcon2")
BANNER_B = re.compile(r"serving shm-kick on .*slot @8192.* kick msix \(LPI 8193\)")
MSIXCFG = re.compile(r"its: msixcfg: .* -> LPI 8193")


def per_exchange(doc, counter, exchanges):
    try:
        x, y = doc["before"]["counters"][counter], doc["after"]["counters"][counter]
    except (KeyError, TypeError):
        return None
    if x is None or y is None or not exchanges:
        return None
    return (y - x) / float(exchanges)


def _num(v):
    return isinstance(v, (int, float)) and v == v


def main(argv):
    out = argv[0]
    sp = os.path.join(out, "stamp.json")
    stamp = json.load(open(sp)) if os.path.exists(sp) else {}
    n_want, warm, k_want = stamp.get("n"), stamp.get("warmup", 200), stamp.get("k")
    core = (stamp.get("pin") or {}).get("probe")
    exchanges = (n_want or 0) + warm
    rounds = list(range(1, (k_want or 0) + 1))

    def jload(name):
        try:
            return json.load(open(os.path.join(out, name)))
        except (OSError, ValueError):
            return None

    m1, m2, m3, m4 = [], [], [], []
    if not rounds:
        m1.append("the stamp has no k")
    lat, kvm = {}, {}
    for r in rounds:
        for a in ARMS:
            s = (jload("lat-%s_r%d.json" % (a, r)) or {}).get("summary")
            if s is None:
                m1.append("%s_r%d: missing" % (a, r))
                continue
            iv, kind = SPACING[a[1]]
            arr = s.get("arrival") or {}
            sl = arr.get("sleep_ms") or {}
            checks = [("n", s.get("n") == n_want), ("warm-up", s.get("warmup_discarded") == warm),
                      ("bad", s.get("bad") == 0), ("rejected", s.get("rejected_by_monitor") == 0),
                      ("proto", s.get("proto") == PROTO[a[0]]),
                      ("percentiles", all(_num(s.get(k)) for k in PCT)),
                      ("spacing", _num(s.get("interval_ms")) and abs(s["interval_ms"] - iv) < 1e-9),
                      ("arrival", arr.get("kind", "const") == kind),
                      ("core", core is None or s.get("cpu_affinity") == [core])]
            if kind == "exp":
                mean, sd = sl.get("mean"), sl.get("sd")
                checks.append(("draws", arr.get("draws") == exchanges and _num(mean) and _num(sd)
                               and abs(mean - iv) <= 0.1 * iv and mean > 0 and 0.8 <= sd / mean <= 1.2))
            bad = [x for x, ok in checks if not ok]
            if bad:
                m1.append("%s_r%d: %s" % (a, r, ", ".join(bad)))
            else:
                lat[(a, r)] = s
            nt = s.get("notify") or {}
            if not (nt.get("exchanges") == exchanges and nt.get("notifications") == exchanges
                    and nt.get("wakeups") == exchanges and nt.get("early_wakeups") == 0
                    and nt.get("stray") == 0 and nt.get("eagain") == 0):
                m2.append("%s_r%d: notify %s" % (a, r, nt))
            kv = jload("kvm-%s_r%d.json" % (a, r))
            if kv is None or any(per_exchange(kv, c, exchanges) is None
                                 for c in ("halt_successful_poll", "halt_wakeup")):
                m4.append("%s_r%d: no KVM counters" % (a, r))
            else:
                kvm[(a, r)] = kv
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        miss = [name for name, rx in (("msixcfg", MSIXCFG), ("console-kick", BANNER_K), ("msix", BANNER_B))
                if len(rx.findall(text)) != 1]
        if miss:
            m3.append("r%d: not exactly one line for %s" % (r, ", ".join(miss)))
    ok = {"M1": bool(rounds) and not m1, "M2": bool(rounds) and not m2, "M3": bool(rounds) and not m3,
          "M4": bool(rounds) and not m4}
    print("  rounds %d, %d exchanges per arm; kvm_halt_poll %s" % (len(rounds), exchanges, stamp.get("kvm_halt_poll")))
    for name, msgs, desc in (
            ("M1", m1, "every arm: n samples after the warm-up, none rejected or bad, own transport, the probe on core "
                       "%s, its spacing and arrival, exp draws as designed" % core),
            ("M2", m2, "one doorbell and one wake-up per exchange, none early, no stray byte, no EAGAIN"),
            ("M3", m3, "every boot: msixcfg done, the console and msix monitors serving"),
            ("M4", m4, "KVM's counters around every arm")):
        print("  %s %s -> %s" % (name, desc, "ok" if ok[name] else "FAILED"))
        for msg in msgs[:6]:
            print("     %s" % msg)

    def show(label, vals, unit="us"):
        if not vals:
            print("    %-30s (no data)" % label)
            return float("nan"), float("nan"), float("nan")
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-30s %+9.3f [%+.3f, %+.3f] %s (%.1f%%), > 0 in %d/%d"
              % (label, m, lo, hi, unit, 100 * cov, sum(v > 0 for v in vals), len(vals)))
        return m, lo, hi

    def s_of(x, r, key="p50_ms"):
        k, b = ("K" + x, r), ("B" + x, r)
        if k not in lat or b not in lat:
            return None
        return (lat[b][key] - lat[k][key]) * 1000.0

    def w_of(x, r):
        k, b = ("K" + x, r), ("B" + x, r)
        if k not in kvm or b not in kvm:
            return None
        return per_exchange(kvm[k], "halt_wakeup", exchanges) - per_exchange(kvm[b], "halt_wakeup", exchanges)

    def dd(f, x, y, key="p50_ms"):
        vals = []
        for r in rounds:
            a, b = (f(x, r, key), f(y, r, key)) if f is s_of else (f(x, r), f(y, r))
            if a is not None and b is not None:
                vals.append(a - b)
        return vals

    def med_counter(a, c):
        xs = [per_exchange(kvm[(a, r)], c, exchanges) for r in rounds if (a, r) in kvm]
        xs = [x for x in xs if x is not None]
        return st.median(xs) if xs else float("nan")

    def idle_gap(a):
        xs = [lat[(a, r)]["period_us"]["p50"] - lat[(a, r)]["p50_ms"] * 1000.0 for r in rounds
              if (a, r) in lat and _num((lat[(a, r)].get("period_us") or {}).get("p50"))]
        return st.median(xs) if xs else float("nan")

    print("  per arm, medians over rounds:   p50 us   p90 us   p99 us  p99.9 us  idle gap us  wakeup/ex  succ_poll/ex  exits/ex")
    for a in ARMS:
        vals = []
        for key in PCT:
            xs = [lat[(a, r)][key] * 1000.0 for r in rounds if (a, r) in lat]
            vals.append("%8.2f" % st.median(xs) if xs else "       -")
        print("    %-3s %s %12.1f %10.2f %13.2f %9.2f" % (a, " ".join(vals), idle_gap(a), med_counter(a, "halt_wakeup"),
                                                     med_counter(a, "halt_successful_poll"), med_counter(a, "exits")))
    print("  S = B - K at p50 and W = K - B halt wake-ups per exchange, paired within round")
    s2 = (float("nan"),) * 3
    for x, label in (("2", "2 ms"), ("f", "0.2 ms"), ("e", "exp")):
        got = show("S(%s)" % label, [v for v in (s_of(x, r) for r in rounds) if v is not None])
        if x == "2":
            s2 = got
        show("W(%s)" % label, [v for v in (w_of(x, r) for r in rounds) if v is not None], "/ex")
    print("  the scored differences")
    p1m, p1lo, _ = show("S(0.2 ms) - S(2 ms)", dd(s_of, "f", "2"))
    p2m, p2lo, p2hi = show("S(exp) - S(2 ms)", dd(s_of, "e", "2"))
    p3m, p3lo, _ = show("W(2 ms) - W(0.2 ms)", dd(w_of, "2", "f"), "/ex")
    print("  S at p99, unscored")
    for x, label in (("2", "S(2 ms) p99"), ("f", "S(0.2 ms) p99"), ("e", "S(exp) p99")):
        show(label, [v for v in (s_of(x, r, "p99_ms") for r in rounds) if v is not None])

    m5 = None
    if ok["M4"]:
        rises = []
        for w in ("K", "B"):
            xs = [per_exchange(kvm[(w + "f", r)], "halt_successful_poll", exchanges)
                  - per_exchange(kvm[(w + "2", r)], "halt_successful_poll", exchanges)
                  for r in rounds if (w + "f", r) in kvm and (w + "2", r) in kvm]
            rises.append(st.median(xs) if xs else float("nan"))
        gaps = [idle_gap("Kf"), idle_gap("Bf")]
        if all(_num(v) for v in rises + gaps):
            m5 = all(v >= M5_POLL_RISE for v in rises) and all(g < M5_IDLE_US for g in gaps)
        print("  M5 (a qualifier) successful polls /ex, 0.2 ms minus 2 ms: K %+.2f, B %+.2f (>= %.1f); idle gap Kf %.0f, "
              "Bf %.0f us (< %.0f) -> %s" % (rises[0], rises[1], M5_POLL_RISE, gaps[0], gaps[1], M5_IDLE_US,
                                             {None: "not evaluated", True: "ok", False: "FAILED"}[m5]))
    else:
        print("  M5 (a qualifier) -> not evaluated (M4 failed)")
    m6 = s2[2] < 0 if _num(s2[2]) else None
    print("  M6 (a qualifier) S(2 ms) interval upper end %+.3f below 0 -> %s"
          % (s2[2], {None: "not evaluated", True: "ok", False: "FAILED"}[m6]))

    def verdict(v, needs, premise=False):
        failed = [m for m in needs if not ok[m]]
        if failed:
            return "VOID (%s failed)" % ", ".join(failed)
        notes = []
        if premise and m5 is False:
            notes.append("H1's premise not met")
        elif premise and m5 is None:
            notes.append("H1's premise not evaluated")
        if premise and m6 is False:
            notes.append("S(2 ms) not below 0")
        return v + ("".join(" -- " + n for n in notes))

    if p1m >= P1_HELD and p1lo > 0:
        p1 = "HELD"
    elif p1lo > 0:
        p1 = "PARTIAL"
    elif p1m > 0:
        p1 = "UNRESOLVED"
    else:
        p1 = "REFUTED"
    if abs(p2m) <= P2_BAND and -P2_BAND <= p2lo and p2hi <= P2_BAND:
        p2 = "HELD"
    elif abs(p2m) <= P2_BAND:
        p2 = "PARTIAL"
    else:
        p2 = "REFUTED"
    p3 = "HELD" if (p3m > 0 and p3lo > 0) else "REFUTED"
    print("  P1  S(0.2 ms) - S(2 ms) %+.3f (>= +%.1f, interval lower %+.3f > 0) -> %s"
          % (p1m, P1_HELD, p1lo, verdict(p1, ("M1", "M2", "M3"), premise=True)))
    print("  P2  S(exp) - S(2 ms) %+.3f [%+.3f, %+.3f] (within +-%.1f) -> %s"
          % (p2m, p2lo, p2hi, P2_BAND, verdict(p2, ("M1", "M2", "M3"))))
    print("  P3  W(2 ms) - W(0.2 ms) %+.3f /ex (> 0, interval lower %+.3f > 0) -> %s"
          % (p3m, p3lo, verdict(p3, ("M1", "M2", "M3", "M4"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
