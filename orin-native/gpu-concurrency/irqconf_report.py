#!/usr/bin/env python3
"""irqconf_report.py OUT N WARMUP -- run-irqconf.sh's test: with the host's userspace confined,
is part of the remaining tail the device interrupts landing on QEMU's cores? (Phase 3b / A6,
2026-09-29), by the rule its header fixed before any run.

Per arm-round p50/p99/p99.9; DIFF(q) is moved minus dflt in the same round, and verdicts use
its median over the rounds. EXCESS is moved's pooled share at or above dflt's pooled p99.
In dflt arms, RESIDUAL exchanges (out-class, outside the tick bin, no guest timer DURING) are
DEVICE when a hard interrupt other than IPI, arch_timer and kvm starts on QEMU's or the
probe's cores in [t0 - 500 us, t0 + rtt]; LIFT is DEVICE's share among the residual tail over
its share among the rest. Scored only at k = 40; a prediction resting on a failed check
prints VOID.
"""
import bisect
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
import guesttick_report as gr  # noqa: E402
import tick_report as tr  # noqa: E402
import tick_trace as tkt  # noqa: E402
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 40
P99_HELD, EXCESS_HELD, EXCESS_REFUTED, P50_BAND = -3.0, 0.8, 1.0, 2.0
LIFT_HELD, LIFT_REFUTED = 3.0, 1.5
LEAD = 500.0
NOT_DEVICE = ("IPI", "arch_timer", "kvm")
MOVED_MAX, DFLT_MIN = 2, 20
MIN_RESID_TAIL, MIN_DEVICE = 100, 200
ALIGN = 0.9


def samples(out, tag):
    """The arm-round's timed round trips in us, in order, or None."""
    p = os.path.join(out, "lat-%s.json" % tag)
    if not os.path.exists(p):
        return None
    return [v * 1000.0 for v in json.load(open(p))["samples_in_order"]]


def rounds(out):
    return sorted(int(re.search(r"_r(\d+)\.", f).group(1)) for f in glob.glob(os.path.join(out, "lat-dflt_r*.json")))


def quantiles(v):
    return {"p50": br.pct(v, 50), "p99": br.pct(v, 99), "p999": br.pct(v, 99.9)}


def exchanges(out, tag, n, warm):
    """[(t0, rtt_us, tail)] for the arm-round's out-class exchanges, or None if not aligned.
    run-tick.sh's alignment (tick_report.exchanges), for any arm tag."""
    ev = tjt.read(os.path.join(out, "tp-%s.log" % tag))
    lens = [int(x) for _, e, x in ev if e == "X" and int(x) >= 100]
    req_len = max(set(lens), key=lens.count) if lens else None
    reqs = [t for t, e, x in ev if e == "X" and int(x) == req_len]
    lat = samples(out, tag)
    if lat is None or len(reqs) != warm + n or len(lat) != n:
        return None
    tj = [t for t, e, z in ev if e == "T" and z == br.ZONE]
    other = [t for t, e, z in ev if e == "T" and z != br.ZONE]
    cut = br.pct(lat, 99)
    return [(t0, v, v >= cut) for t0, v in zip(reqs[warm:], lat) if br.classify(t0, tj, {}, other) == "out"]


def trace_events(path):
    """(sorted device interrupt starts, sorted guest timer events), both in us."""
    dev, guest = [], []
    for t, _c, k, f in tkt.read(path):
        if k == "I" and f not in NOT_DEVICE:
            dev.append(t)
        if (k == "I" and f == "kvm") or (k == "H" and f == "kvm_bg_timer_expire"):
            guest.append(t)
    return sorted(dev), sorted(guest)


def device_near(t0, rtt, dev):
    i = bisect.bisect_left(dev, t0 - LEAD)
    return i < len(dev) and dev[i] <= t0 + rtt


def residual(rows, dev, guest):
    """[(device, tail)] of the residual exchanges among rows."""
    out = []
    for t0, v, tail in rows:
        if tr.in_bin(t0) or gr.klass(t0, guest) == "DURING":
            continue
        out.append((device_near(t0, v, dev), tail))
    return out


def lift(res):
    t = [d for d, tail in res if tail]
    o = [d for d, tail in res if not tail]
    if not t or not o or sum(o) == 0:
        return float("nan")
    return (sum(t) / len(t)) / (sum(o) / len(o))


def irq_fired(out, tag, cores):
    """Movable interrupts fired on `cores` during the arm (after minus before), or None."""
    b, a = os.path.join(out, "irq-%s.before" % tag), os.path.join(out, "irq-%s.after" % tag)
    if not (os.path.exists(b) and os.path.exists(a)):
        return None

    def load(p):
        d = {}
        for line in open(p):
            f = line.split()
            if len(f) == 7:
                d[f[0]] = [int(x) for x in f[1:]]
        return d
    x, y = load(b), load(a)
    return sum(y[k][c] - x[k][c] for k in y if k in x for c in cores)


def grade(v, held, refuted, lower=True):
    if lower:
        return "HELD" if v <= held else "REFUTED" if v >= refuted else "PARTIAL"
    return "HELD" if v >= held else "REFUTED" if v <= refuted else "PARTIAL"


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    qc, pc = tr.cores(out)
    measured = qc + [pc]
    rs = rounds(out)
    k = len(rs)
    diffs = {"p50": [], "p99": [], "p999": []}
    pooled = {"dflt": [], "moved": []}
    complete = aligned = 0
    moved_fired, dflt_fired = [], []
    res = []
    for r in rs:
        d, m = samples(out, "dflt_r%d" % r), samples(out, "moved_r%d" % r)
        if d is None or m is None or len(d) != n or len(m) != n:
            print("  round %d incomplete" % r)
            continue
        complete += 1
        qd, qm = quantiles(d), quantiles(m)
        for q in diffs:
            diffs[q].append(qm[q] - qd[q])
        pooled["dflt"] += d
        pooled["moved"] += m
        mf = irq_fired(out, "moved_r%d" % r, measured)
        df = irq_fired(out, "dflt_r%d" % r, measured)
        moved_fired.append(mf)
        dflt_fired.append(df)
        rows = exchanges(out, "dflt_r%d" % r, n, warm)
        tk = os.path.join(out, "tk-dflt_r%d.log" % r)
        if rows is None or not os.path.exists(tk):
            print("  round %d: dflt not aligned or without an interrupt trace" % r)
            continue
        aligned += 1
        dev, guest = trace_events(tk)
        res += residual(rows, dev, guest)

    med = {q: st.median(x) if x else float("nan") for q, x in diffs.items()}
    cut = br.pct(pooled["dflt"], 99) if pooled["dflt"] else float("nan")
    excess = 100.0 * sum(1 for v in pooled["moved"] if v >= cut) / len(pooled["moved"]) if pooled["moved"] else float("nan")
    lf = lift(res)
    resid_tail = sum(1 for _d, t in res if t)
    device_n = sum(1 for d, _t in res if d)
    fit, qok, nr = cr.conf_checks(out, {r: "confined" for r in rs})
    nl = br.logins(out)
    dflt_med = st.median([x for x in dflt_fired if x is not None]) if any(x is not None for x in dflt_fired) else -1
    ok = {"M1": k > 0 and complete == k and aligned >= ALIGN * k,
          "M2": nr > 0 and fit == nr and qok == nr,
          "M3": nl == 0,
          "M4": (bool(moved_fired) and all(x is not None and x <= MOVED_MAX for x in moved_fired)
                 and dflt_med >= DFLT_MIN),
          "M5": resid_tail >= MIN_RESID_TAIL and device_n >= MIN_DEVICE}
    print("  rounds %d, complete %d, dflt aligned %d" % (k, complete, aligned))
    print("  M1 complete %d/%d, dflt aligned %d/%d (want all complete, >= 90%% aligned) -> %s"
          % (complete, k, aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds confined %d/%d, QEMU's threads on %s %d/%d (want all) -> %s"
          % (fit, nr, cr.QEMU, qok, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M3"] else "FAILED"))
    print("  M4 movable interrupts on the measured cores: moved max %s (want <= %d in every arm-round), "
          "dflt median %s (want >= %d) -> %s"
          % (max((x for x in moved_fired if x is not None), default="-"), MOVED_MAX, dflt_med, DFLT_MIN,
             "ok" if ok["M4"] else "FAILED"))
    print("  M5 dflt residual tail %d (want >= %d), DEVICE residual %d (want >= %d) -> %s"
          % (resid_tail, MIN_RESID_TAIL, device_n, MIN_DEVICE, "ok" if ok["M5"] else "FAILED"))
    print("  median DIFF (moved - dflt, us): p50 %+.1f  p99 %+.1f  p99.9 %+.1f (p99.9 not predicted)"
          % (med["p50"], med["p99"], med["p999"]))
    print("  EXCESS: %.2f%% of moved at or above dflt's pooled p99 (%.1f us)" % (excess, cut))
    print("  LIFT: DEVICE among the residual tail over the rest: %.1f" % lf)
    scored = k == SCORED_K
    base = ["M1", "M2", "M3", "M4"]
    print("  P1  p99 falls: median DIFF(p99) %+.1f us -> %s"
          % (med["p99"], verdict(grade(med["p99"], P99_HELD, 0.0), scored, k, ok, base)))
    print("  P2  fewer slow exchanges: EXCESS %.2f%% -> %s"
          % (excess, verdict(grade(excess, EXCESS_HELD, EXCESS_REFUTED), scored, k, ok, base)))
    print("  P3  the median does not move: |median DIFF(p50)| %.1f us -> %s"
          % (abs(med["p50"]), verdict("HELD" if abs(med["p50"]) <= P50_BAND else "REFUTED", scored, k, ok, base)))
    print("  P4  device interrupts go with the residual tail: LIFT %.1f -> %s"
          % (lf, verdict(grade(lf, LIFT_HELD, LIFT_REFUTED, lower=False), scored, k, ok, base + ["M5"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
