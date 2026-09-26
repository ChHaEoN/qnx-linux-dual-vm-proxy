#!/usr/bin/env python3
"""clock_report.py OUT N WARMUP -- run-clock.sh's test: the guest's tick at 1 kHz (A) and 100 Hz
(B), alternated by guest boot within one board boot (Phase 3b / A6, 2026-09-26), by the rule
its header fixed before any run.

order.log gives each round's arm and guest boot; guests.log each guest boot's image and the
period qnx-clockctl read back. Alignment and classes are run-tick.sh's (tick_report). Per arm:
GUESTSHARE, the share of out-class tail exchanges whose first guest event (guesttick_report)
comes within 150 us of t0; P50, the median of round p50s; POLL, the median over rounds of
KVM's halt_successful_poll / halt_attempted_poll during the round (kvm-*.json); EVENTS, the
median guest events per round. Scored only at k = 40; a prediction resting on a failed check
prints VOID.
"""
import bisect
import collections
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bursts_report as br  # noqa: E402
import confine_report as cr  # noqa: E402
import guesttick_report as gr  # noqa: E402
import tick_report as tr  # noqa: E402

SCORED_K = 40
ARMS = ("A", "B")
WANT = {"A": "period 1000000", "B": "period 10000000"}
PATTERN = ["A", "B", "B", "A", "A", "B", "B", "A"]
NEAR = 150.0
SHARE_LESS, P50_MORE, POLL_LESS, EVENTS_LESS = 0.5, 30.0, 0.5, 1.0 / 3


def rounds_of(out):
    got = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) arm: ([AB]) guest (\d+)", line)
            if m:
                got[int(m.group(1))] = (m.group(2), int(m.group(3)))
    return got


def guests_of(out):
    got = []
    p = os.path.join(out, "guests.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"guest (\d+) arm ([AB]) .* clockctl (.*) want (\d+)$", line.rstrip())
            if m:
                got.append((int(m.group(1)), m.group(2), m.group(3).strip()))
    return got


def poll_fraction(path):
    d = json.load(open(path))
    b, a = d["before"]["counters"], d["after"]["counters"]
    att = a["halt_attempted_poll"] - b["halt_attempted_poll"]
    ok = a["halt_successful_poll"] - b["halt_successful_poll"]
    return ok / att if att > 0 else float("nan")


def med(xs):
    xs = [x for x in xs if x == x]
    return st.median(xs) if xs else float("nan")


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    rounds = rounds_of(out)
    k = len(rounds)
    tail = {a: [0, 0] for a in ARMS}           # [out-class tail exchanges, of them near a guest event]
    p50 = collections.defaultdict(list)
    poll = collections.defaultdict(list)
    events = collections.defaultdict(list)
    aligned = 0
    for r in sorted(rounds):
        arm = rounds[r][0]
        rows, lat = tr.exchanges(out, r, n, warm)
        tk = os.path.join(out, "tk-t2ms_r%d.log" % r)
        if rows is None or not os.path.exists(tk):
            print("  round %d not aligned or without a guest trace" % r)
            continue
        aligned += 1
        ev = gr.guest_events(tk)
        events[arm].append(len(ev))
        p50[arm].append(st.median(lat))
        kv = os.path.join(out, "kvm-t2ms_r%d.json" % r)
        if os.path.exists(kv):
            poll[arm].append(poll_fraction(kv))
        for t0, v, tl in rows:
            if not tl:
                continue
            tail[arm][0] += 1
            i = bisect.bisect_left(ev, t0)
            tail[arm][1] += i < len(ev) and ev[i] - t0 < NEAR
    share = {a: tail[a][1] / tail[a][0] if tail[a][0] else float("nan") for a in ARMS}
    P50 = {a: med(p50[a]) for a in ARMS}
    POLL = {a: med(poll[a]) for a in ARMS}
    EV = {a: med(events[a]) for a in ARMS}
    guests = guests_of(out)
    fit, qok, nr = cr.conf_checks(out, {r: "confined" for r in rounds})
    nl = br.logins(out)
    per_arm = collections.Counter(a for a, _ in rounds.values())
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": nr > 0 and fit == nr and qok == nr,
          "M3": nl == 0,
          "M4": bool(guests) and all(got == WANT[a] for _, a, got in guests)
          and EV["A"] == EV["A"] and EV["B"] <= EVENTS_LESS * EV["A"],
          "M5": [a for _, a, _ in sorted(guests)] == PATTERN and per_arm["A"] == 20 and per_arm["B"] == 20}
    print("  rounds %d, aligned %d, per arm %s, guest boots %s" % (k, aligned, dict(per_arm), "".join(a for _, a, _ in sorted(guests))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds confined and QEMU's threads on %s: %d/%d, %d/%d (want all) -> %s"
          % (cr.QEMU, fit, nr, qok, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M3"] else "FAILED"))
    print("  M4 periods read back %s; guest events per round A %s, B %s (want B <= A/3) -> %s"
          % (["%d%s:%s" % (g, a, got.split()[-1] if got else "?") for g, a, got in sorted(guests)], EV["A"], EV["B"],
             "ok" if ok["M4"] else "FAILED"))
    print("  M5 guest boots in the pattern %s, 20 rounds per arm -> %s" % ("".join(PATTERN), "ok" if ok["M5"] else "FAILED"))
    for a in ARMS:
        print("  %s  tail exchanges %4d, near a guest event %4d (%.1f%%); P50 %.1f us; POLL %.2f; EVENTS %s"
              % (a, tail[a][0], tail[a][1], 100 * share[a], P50[a], POLL[a], EV[a]))
    scored = k == SCORED_K
    base = ["M1", "M2", "M3", "M4", "M5"]
    print("  P1  the tail meets the guest's timer far less: GUESTSHARE B %.3f, A %.3f -> %s"
          % (share["B"], share["A"], verdict("HELD" if share["A"] > 0 and share["B"] <= SHARE_LESS * share["A"] else "REFUTED",
                                             scored, k, ok, base)))
    d50 = P50["B"] - P50["A"]
    print("  P2  the typical exchange is slower with the 10 ms tick: P50 B - A %+.1f us -> %s"
          % (d50, verdict("HELD" if d50 >= P50_MORE else "REFUTED", scored, k, ok, base)))
    print("  P3  because halt polling succeeds less: POLL B %.2f, A %.2f -> %s"
          % (POLL["B"], POLL["A"], verdict("HELD" if POLL["A"] > 0 and POLL["B"] <= POLL_LESS * POLL["A"] else "REFUTED",
                                           scored, k, ok, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
