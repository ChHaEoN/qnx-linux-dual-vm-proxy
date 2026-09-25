#!/usr/bin/env python3
"""guesttick_report.py OUT N WARMUP -- run-guesttick.sh's test: with the host's userspace
confined, is the rest of the tail the guest's own timer firing while an exchange is in
the guest? (Phase 3b / A6, 2026-09-25), by the rule its header fixed before any run.

Alignment, classes, the host TICK BIN and TAIL are run-tick.sh's (tick_report.exchanges,
in_bin). The guest events are tk-t2ms_rN.log's hard IRQs named kvm (the "kvm guest vtimer"
IRQ) and hrtimer expiries of kvm_bg_timer_expire. Outside the tick bin, an out-class
exchange is DURING, AFTER or NONE by its first guest event's offset from t0 ([25, 150),
[175, 250) us, or none in [0, 250) us). RATIO is a class's tail share over NONE's, SLOWDOWN
DURING's median round trip minus NONE's, COVER the share of all out-class tail exchanges
in the tick bin or DURING. Scored only at k = 40; a prediction resting on a failed check
prints VOID.
"""
import bisect
import collections
import glob
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bursts_report as br  # noqa: E402
import confine_report as cr  # noqa: E402
import tick_report as tr  # noqa: E402
import tick_trace as tkt  # noqa: E402

SCORED_K = 40
DURING, AFTER, SPAN = (25.0, 150.0), (175.0, 250.0), 250.0
RATIO_DURING, SLOW, RATIO_AFTER, COVER = 5.0, 5.0, 2.0, 0.4
MIN_EVENTS, MIN_DURING, MIN_AFTER = 500, 700, 500


def guest_events(path):
    """Sorted times (us) of the guest's timer events in one round's reduced trace."""
    return sorted(t for t, _, k, f in tkt.read(path)
                  if (k == "I" and f == "kvm") or (k == "H" and f == "kvm_bg_timer_expire"))


def klass(t0, ev):
    """DURING, AFTER, NONE or None, by the first guest event at or after t0."""
    i = bisect.bisect_left(ev, t0)
    if i == len(ev) or ev[i] - t0 >= SPAN:
        return "NONE"
    off = ev[i] - t0
    if DURING[0] <= off < DURING[1]:
        return "DURING"
    if AFTER[0] <= off < AFTER[1]:
        return "AFTER"
    return None


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    rounds = sorted(int(re.search(r"_r(\d+)\.", f).group(1)) for f in glob.glob(os.path.join(out, "lat-t2ms_r*.json")))
    k = len(rounds)
    cls = collections.defaultdict(list)            # class -> [(v, tail)]
    per_round_events, aligned = [], 0
    tail_all = tail_bin = 0
    offs = collections.defaultdict(lambda: [0, 0])  # 25-us offset bin of the first event -> [n, tail]
    for r in rounds:
        rows, _ = tr.exchanges(out, r, n, warm)
        tk = os.path.join(out, "tk-t2ms_r%d.log" % r)
        if rows is None or not os.path.exists(tk):
            print("  round %d not aligned or without a guest trace" % r)
            continue
        aligned += 1
        ev = guest_events(tk)
        per_round_events.append(len(ev))
        for t0, v, tail in rows:
            tail_all += tail
            if tr.in_bin(t0):
                tail_bin += tail
                continue
            c = klass(t0, ev)
            if c:
                cls[c].append((v, tail))
            i = bisect.bisect_left(ev, t0)
            if i < len(ev) and ev[i] - t0 < SPAN:
                b = int((ev[i] - t0) // 25)
                offs[b][0] += 1
                offs[b][1] += tail

    def share(c):
        xs = cls[c]
        return sum(1 for _, t in xs if t) / len(xs) if xs else float("nan")

    def med(c):
        return st.median(v for v, _ in cls[c]) if cls[c] else float("nan")

    base = share("NONE")
    r_during = share("DURING") / base if base and base > 0 else float("nan")
    r_after = share("AFTER") / base if base and base > 0 else float("nan")
    slow = med("DURING") - med("NONE")
    during_tail = sum(1 for _, t in cls["DURING"] if t)
    cover = (tail_bin + during_tail) / tail_all if tail_all else float("nan")
    fit, qok, nr = cr.conf_checks(out, {r: "confined" for r in rounds})
    nl = br.logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": nr > 0 and fit == nr and qok == nr,
          "M3": nl == 0,
          "M4": bool(per_round_events) and min(per_round_events) >= MIN_EVENTS and len(per_round_events) == aligned,
          "M5a": len(cls["DURING"]) >= MIN_DURING,
          "M5b": len(cls["AFTER"]) >= MIN_AFTER}
    print("  rounds %d, aligned %d" % (k, aligned))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds confined (udevd, PID 1, gnome-shell on %s) %d/%d, QEMU's threads on %s %d/%d (want all) -> %s"
          % (cr.CONF, fit, nr, cr.QEMU, qok, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M3"] else "FAILED"))
    print("  M4 guest timer events per round: min %s, median %s (want >= %d in every round) -> %s"
          % (min(per_round_events) if per_round_events else "-",
             st.median(per_round_events) if per_round_events else "-", MIN_EVENTS, "ok" if ok["M4"] else "FAILED"))
    print("  M5 DURING exchanges %d (want >= %d) -> %s; AFTER exchanges %d (want >= %d) -> %s"
          % (len(cls["DURING"]), MIN_DURING, "ok" if ok["M5a"] else "FAILED", len(cls["AFTER"]), MIN_AFTER,
             "ok" if ok["M5b"] else "FAILED"))
    for c in ("DURING", "AFTER", "NONE"):
        xs = cls[c]
        print("  %-7s n %6d  tail %4d  tail share %.2f%%  median %.1f us" % (c, len(xs), sum(1 for _, t in xs if t),
                                                                           100 * share(c), med(c)))
    print("  tail exchanges: %d, in the tick bin %d, DURING %d" % (tail_all, tail_bin, during_tail))
    print("  tail share by the first guest event's offset after t0 (25 us bins): "
          + "  ".join("[%d] %.1f%%/%d" % (b * 25, 100.0 * t / m, m) for b, (m, t) in sorted(offs.items())))
    scored = k == SCORED_K
    base_m = ["M1", "M2", "M3", "M4"]
    print("  P1  DURING exchanges are over-represented in the tail: RATIO %.1f -> %s"
          % (r_during, verdict("HELD" if r_during >= RATIO_DURING else "REFUTED", scored, k, ok, base_m + ["M5a"])))
    print("  P2  they are slower: SLOWDOWN %+.1f us -> %s"
          % (slow, verdict("HELD" if slow >= SLOW else "REFUTED", scored, k, ok, base_m + ["M5a"])))
    print("  P3  the same event after the exchange is harmless: RATIO(AFTER) %.2f -> %s"
          % (r_after, verdict("HELD" if r_after <= RATIO_AFTER else "REFUTED", scored, k, ok, base_m + ["M5b"])))
    print("  P4  the two ticks together cover much of the tail: COVER %.2f -> %s"
          % (cover, verdict("HELD" if cover >= COVER else "REFUTED", scored, k, ok, base_m + ["M5a"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
