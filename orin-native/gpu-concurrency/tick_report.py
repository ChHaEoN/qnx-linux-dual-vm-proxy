#!/usr/bin/env python3
"""tick_report.py OUT N WARMUP -- run-tick.sh's test: with the host's userspace confined, is
the tail that is left the host's tick, and the work it sets off, on QEMU's and the probe's
cores? (Phase 3b / A6, 2026-09-25), by the rule its header fixed before any run.

Each round is light or heavy (order.log). Alignment and classes are run-natural.sh's; only
out-class exchanges count. An exchange is in the TICK BIN when its request's time t0 is in
[3850, 4000) us mod 4000, and a TAIL exchange when its round trip is at or above its round's
p99. Light rounds give the tick bin's tail RATIO and SLOWDOWN; heavy rounds give each
exchange's FOREIGN time, the host's own work on QEMU's cores and the probe's in [t0, t0 +
250 us] (tick_trace.Contexts), and from it DIFF (median, tail minus non-tail) and SHARE
(the part of the difference in means not in hard interrupts). confine.log holds the
allowed CPUs before and after every round (confine_report.conf_checks). Scored only at
k = 40; a prediction resting on a failed check prints VOID.
"""
import bisect
import collections
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bursts_report as br  # noqa: E402
import confine_report as cr  # noqa: E402
import tick_trace as tkt  # noqa: E402
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 40
KINDS = ("light", "heavy")
PERIOD, BIN_LO, WINDOW, GRID_OK = 4000.0, 3850.0, 250.0, 100.0
RATIO, SLOW, DIFF_TICK, SHARE, DIFF_REST, SAME = 3.0, 5.0, 10.0, 0.5, 5.0, 10.0
MIN_LIGHT_TAIL, MIN_HEAVY_TAIL, MIN_HEAVY_REST, MIN_HEAVY_BASE = 30, 20, 20, 100
NOT_HARD = ("softirq", "work", "task")


def kinds_of(out):
    got = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) arm: (light|heavy)", line)
            if m:
                got[int(m.group(1))] = m.group(2)
    return got


def cores(out):
    """(QEMU's cores, the probe's core) from stamp.json, else the A6 defaults."""
    q, p = "0-2", 4
    s = os.path.join(out, "stamp.json")
    if os.path.exists(s):
        pin = json.load(open(s)).get("pin", {})
        q, p = pin.get("qemu", q), int(pin.get("probe", p))
    cs = set()
    for x in str(q).split(","):
        a, _, b = x.partition("-")
        cs.update(range(int(a), int(b or a) + 1))
    return sorted(cs), p


def in_bin(t0):
    return t0 % PERIOD >= BIN_LO


def qtids(out, r):
    p = os.path.join(out, "qtids-t2ms_r%d.txt" % r)
    return {int(x) for x in open(p).read().split()} if os.path.exists(p) else set()


def exchanges(out, r, n, warm):
    """[(t0, rtt_us, tail)] for the round's out-class exchanges, or None if not aligned."""
    ev = tjt.read(os.path.join(out, "tp-t2ms_r%d.log" % r))
    lens = [int(x) for _, e, x in ev if e == "X" and int(x) >= 100]
    req_len = max(set(lens), key=lens.count) if lens else None
    reqs = [t for t, e, x in ev if e == "X" and int(x) == req_len]
    lat = [v * 1000.0 for v in json.load(open(os.path.join(out, "lat-t2ms_r%d.json" % r)))["samples_in_order"]]
    if len(reqs) != warm + n or len(lat) != n:
        return None, lat
    tj = [t for t, e, z in ev if e == "T" and z == br.ZONE]
    other = [t for t, e, z in ev if e == "T" and z != br.ZONE]
    cut = br.pct(lat, 99)
    return [(t0, v, v >= cut) for t0, v in zip(reqs[warm:], lat) if br.classify(t0, tj, {}, other) == "out"], lat


def split(rows, key):
    return [x for x in rows if key(x)], [x for x in rows if not key(x)]


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def med(xs):
    return st.median(xs) if xs else float("nan")


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    kinds = kinds_of(out)
    qc, pc = cores(out)
    traced = qc + [pc]
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    light, heavy, allv = [], [], {k: [] for k in KINDS}
    grid_on = grid_all = 0
    comps = collections.defaultdict(lambda: collections.defaultdict(list))   # (bin, tail) -> label -> [us]
    timers = collections.defaultdict(collections.Counter)                    # (bin, tail) -> function -> count
    aligned = 0
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        kd = kinds.get(r)
        if kd not in KINDS or not os.path.exists(os.path.join(out, "tp-t2ms_r%d.log" % r)):
            continue
        rows, lat = exchanges(out, r, n, warm)
        if rows is None:
            print("  round %d not aligned" % r)
            continue
        aligned += 1
        allv[kd] += lat
        if kd == "light":
            light += rows
            continue
        tk = os.path.join(out, "tk-t2ms_r%d.log" % r)
        if not os.path.exists(tk):
            print("  round %d has no tick trace" % r)
            continue
        ev = tkt.read(tk)
        for t, c, k, fn in ev:
            if k == "H" and fn == "tick_sched_timer":
                grid_all += 1
                grid_on += (t % PERIOD) < GRID_OK
        ids = qtids(out, r)
        ctx = tkt.Contexts(ev, lambda core, comm, pid: pid in ids or (core == pc and comm.startswith("python")))
        expiries = [(t, fn) for t, c, k, fn in ev if k == "E"]
        et = [t for t, _ in expiries]
        for t0, v, tail in rows:
            fg = tkt.foreign(ctx.time(t0, t0 + WINDOW, traced))
            heavy.append((t0, v, tail, sum(fg.values()), sum(u for l, u in fg.items() if l.split(":")[0] in NOT_HARD)))
            key = (in_bin(t0), tail)
            for lab, u in fg.items():
                comps[key][lab].append(u)
            comps[key]["_n"].append(1)
            for t, fn in expiries[bisect.bisect_left(et, t0):bisect.bisect_left(et, t0 + WINDOW)]:
                timers[key][fn] += 1
    k = len(files)
    # light: ratio and slowdown
    lt = [x for x in light if x[2]]
    lb_all = sum(1 for x in light if in_bin(x[0])) / len(light) if light else float("nan")
    lb_tail = sum(1 for x in lt if in_bin(x[0])) / len(lt) if lt else float("nan")
    ratio = lb_tail / lb_all if light and lt and lb_all > 0 else float("nan")
    lin, lout = split(light, lambda x: in_bin(x[0]))
    slowdown = med([x[1] for x in lin]) - med([x[1] for x in lout])
    # heavy: foreign time
    hin, hout = split(heavy, lambda x: in_bin(x[0]))
    hin_t, hin_n = split(hin, lambda x: x[2])
    hout_t, hout_n = split(hout, lambda x: x[2])
    diff_tick = med([x[3] for x in hin_t]) - med([x[3] for x in hin_n])
    diff_rest = med([x[3] for x in hout_t]) - med([x[3] for x in hout_n])
    dmean = mean([x[3] for x in hin_t]) - mean([x[3] for x in hin_n])
    dsoft = mean([x[4] for x in hin_t]) - mean([x[4] for x in hin_n])
    share = dsoft / dmean if dmean == dmean and dmean > 0 else float("nan")
    p50 = {kd: med(allv[kd]) for kd in KINDS}
    fit, qemu_ok, nr = cr.conf_checks(out, {r: "confined" for r in kinds})
    nl = br.logins(out)
    lin_t = [x for x in lin if x[2]]
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": nr > 0 and fit == nr and qemu_ok == nr,
          "M3": nl == 0,
          "M4": grid_all > 0 and grid_on / grid_all >= 0.9,
          "M5a": len(lin_t) >= MIN_LIGHT_TAIL,
          "M5b": len(hin_t) >= MIN_HEAVY_TAIL and len(hin_n) >= MIN_HEAVY_BASE,
          "M5c": len(hout_t) >= MIN_HEAVY_REST,
          "M6": p50["light"] == p50["light"] and p50["heavy"] == p50["heavy"] and abs(p50["heavy"] - p50["light"]) <= SAME}
    print("  rounds %d, aligned %d, kinds %s, traced cores %s" % (k, aligned, dict(collections.Counter(kinds.values())), traced))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds confined (udevd, PID 1, gnome-shell on %s) %d/%d, QEMU's threads on %s %d/%d (want all) -> %s"
          % (cr.CONF, fit, nr, cr.QEMU, qemu_ok, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M3"] else "FAILED"))
    print("  M4 tick_sched_timer expiries within [0, %.0f) us of the %.0f us grid: %d/%d (want >= 90%%) -> %s"
          % (GRID_OK, PERIOD, grid_on, grid_all, "ok" if ok["M4"] else "FAILED"))
    print("  M5 tick-bin tail in light rounds %d (want >= %d) -> %s; heavy tick-bin tail %d, non-tail %d (want >= %d, >= %d)"
          " -> %s; heavy tail outside the bin %d (want >= %d) -> %s"
          % (len(lin_t), MIN_LIGHT_TAIL, "ok" if ok["M5a"] else "FAILED", len(hin_t), len(hin_n), MIN_HEAVY_TAIL,
             MIN_HEAVY_BASE, "ok" if ok["M5b"] else "FAILED", len(hout_t), MIN_HEAVY_REST, "ok" if ok["M5c"] else "FAILED"))
    print("  M6 p50 heavy %.1f, light %.1f us (want within %.0f) -> %s" % (p50["heavy"], p50["light"], SAME, "ok" if ok["M6"] else "FAILED"))
    print("  light: tick bin %.2f%% of out exchanges, %.2f%% of their tail; median %.1f in the bin, %.1f outside"
          % (100 * lb_all, 100 * lb_tail, med([x[1] for x in lin]), med([x[1] for x in lout])))
    print("  heavy: median foreign us in the bin tail %.1f / non-tail %.1f; outside tail %.1f / non-tail %.1f;"
          " mean difference in the bin %+.1f (not hard irq %+.1f)"
          % (med([x[3] for x in hin_t]), med([x[3] for x in hin_n]), med([x[3] for x in hout_t]), med([x[3] for x in hout_n]),
             dmean, dsoft))
    for key, name in (((True, True), "bin tail"), ((True, False), "bin non-tail"), ((False, True), "outside tail"),
                      ((False, False), "outside non-tail")):
        nn = len(comps[key]["_n"])
        if not nn:
            continue
        top = sorted(((sum(v) / nn, lab) for lab, v in comps[key].items() if lab != "_n"), reverse=True)[:6]
        print("    %-17s n %5d  mean us: %s" % (name, nn, ", ".join("%s %.1f" % (lab, u) for u, lab in top)))
        tf = timers[key].most_common(4)
        if tf:
            print("    %-17s timers expiring per exchange: %s" % ("", ", ".join("%s %.2f" % (fn, c / nn) for fn, c in tf)))
    scored = k == SCORED_K
    base = ["M1", "M2", "M3", "M4"]
    print("  P1  the tick bin is over-represented in the tail: RATIO %.2f -> %s"
          % (ratio, verdict("HELD" if ratio >= RATIO else "REFUTED", scored, k, ok, base + ["M5a"])))
    print("  P2  tick-bin exchanges are slower: SLOWDOWN %+.1f us -> %s"
          % (slowdown, verdict("HELD" if slowdown >= SLOW else "REFUTED", scored, k, ok, base + ["M5a"])))
    print("  P3  in the bin, tail exchanges carry more foreign time: DIFF %+.1f us -> %s"
          % (diff_tick, verdict("HELD" if diff_tick >= DIFF_TICK else "REFUTED", scored, k, ok, base + ["M5b", "M6"])))
    print("  P4  that extra is mostly not hard interrupts: SHARE %.2f of %+.1f us -> %s"
          % (share, dmean, verdict("HELD" if share == share and share >= SHARE else "REFUTED", scored, k, ok,
                                   base + ["M5b", "M6"])))
    print("  P5  outside the bin the tail is not host work on those cores: DIFF %+.1f us -> %s"
          % (diff_rest, verdict("HELD" if diff_rest <= DIFF_REST else "REFUTED", scored, k, ok, base + ["M5c", "M6"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
