#!/usr/bin/env python3
"""wifi_report.py OUT N WARMUP -- run-wifi.sh's test: with the host's userspace confined, is part of
the remaining tail the Wi-Fi? (Phase 3b / A6, 2026-09-29), by the rule its header fixed before any
run.

Per arm-round p50/p99/p99.9; DIFF(q) is off minus on in the same round, and verdicts use its
median over the rounds. EXCESS is off's pooled share at or above on's pooled p99. In on arms,
RESIDUAL exchanges (out-class, outside the tick bin, no guest timer DURING) are WIFI when the
Wi-Fi's hard interrupt starts on QEMU's or the probe's cores in [t0 - 500 us, t0 + rtt]; LIFT is
WIFI's share among the residual tail over its share among the rest. Scored only at k = 40; a
prediction resting on a failed check prints VOID. The per-arm helpers are irqconf_report's.
"""
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
import irqconf_report as ir  # noqa: E402
import tick_report as tr  # noqa: E402
import tick_trace as tkt  # noqa: E402

SCORED_K = 40
P99_HELD, EXCESS_HELD, EXCESS_REFUTED, P50_BAND = -3.0, 0.8, 1.0, 2.0
LIFT_HELD, LIFT_REFUTED = 3.0, 1.5
OFF_MAX, ON_MIN = 2, 5
MIN_RESID_TAIL, MIN_WIFI = 100, 50
ALIGN = 0.9


def wifi_name(out):
    """The Wi-Fi driver's interrupt name, from stamp.json, else rtl88x2ce."""
    p = os.path.join(out, "stamp.json")
    if os.path.exists(p):
        return json.load(open(p)).get("wifi", {}).get("driver", "rtl88x2ce")
    return "rtl88x2ce"


def rounds(out):
    fs = os.listdir(out) if os.path.isdir(out) else []
    return sorted(int(m.group(1)) for m in (re.match(r"lat-on_r(\d+)\.json$", f) for f in fs) if m)


def trace_events(path, name):
    """(sorted starts of the Wi-Fi's interrupt, sorted guest timer events), both in us."""
    wifi, guest = [], []
    for t, _c, k, f in tkt.read(path):
        if k == "I" and f == name:
            wifi.append(t)
        if (k == "I" and f == "kvm") or (k == "H" and f == "kvm_bg_timer_expire"):
            guest.append(t)
    return sorted(wifi), sorted(guest)


def wifi_fired(out, tag):
    """The Wi-Fi's interrupt count on all cores during the arm (after minus before), or None."""
    vals = []
    for w in ("before", "after"):
        p = os.path.join(out, "wifi-%s.%s" % (tag, w))
        if not os.path.exists(p):
            return None
        f = open(p).read().split()
        if len(f) != 7:
            return None
        vals.append(sum(int(x) for x in f[1:]))
    return vals[1] - vals[0]


def radio_states(out):
    """{(round, arm): [(rfkill_soft, nm), ...]} from wifi-state.log, before and after."""
    s = {}
    p = os.path.join(out, "wifi-state.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (on|off) (before|after) rfkill_soft=(\S*) nm=(\S*)", line.strip())
            if m:
                s.setdefault((int(m.group(1)), m.group(2)), []).append((m.group(4), m.group(5)))
    return s


def switch_ok(states, r, arm):
    obs = states.get((r, arm), [])
    if len(obs) != 2:
        return False
    if arm == "off":
        return all(soft == "yes" and not nm.startswith("connected") for soft, nm in obs)
    return all(soft == "no" and nm == "connected" for soft, nm in obs)


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    name = wifi_name(out)
    qc, pc = tr.cores(out)
    rs = rounds(out)
    k = len(rs)
    diffs = {"p50": [], "p99": [], "p999": []}
    pooled = {"on": [], "off": []}
    complete = aligned = 0
    off_fired, on_fired = [], []
    states = radio_states(out)
    switched = 0
    res = []
    for r in rs:
        on, off = ir.samples(out, "on_r%d" % r), ir.samples(out, "off_r%d" % r)
        if on is None or off is None or len(on) != n or len(off) != n:
            print("  round %d incomplete" % r)
            continue
        complete += 1
        qn, qf = ir.quantiles(on), ir.quantiles(off)
        for q in diffs:
            diffs[q].append(qf[q] - qn[q])
        pooled["on"] += on
        pooled["off"] += off
        off_fired.append(wifi_fired(out, "off_r%d" % r))
        on_fired.append(wifi_fired(out, "on_r%d" % r))
        switched += switch_ok(states, r, "on") and switch_ok(states, r, "off")
        rows = ir.exchanges(out, "on_r%d" % r, n, warm)
        tk = os.path.join(out, "tk-on_r%d.log" % r)
        if rows is None or not os.path.exists(tk):
            print("  round %d: on not aligned or without an interrupt trace" % r)
            continue
        aligned += 1
        wifi, guest = trace_events(tk, name)
        for t0, v, tail in rows:
            if tr.in_bin(t0) or gr.klass(t0, guest) == "DURING":
                continue
            res.append((ir.device_near(t0, v, wifi), tail))

    med = {q: st.median(x) if x else float("nan") for q, x in diffs.items()}
    cut = br.pct(pooled["on"], 99) if pooled["on"] else float("nan")
    excess = 100.0 * sum(1 for v in pooled["off"] if v >= cut) / len(pooled["off"]) if pooled["off"] else float("nan")
    lf = ir.lift(res)
    resid_tail = sum(1 for _w, t in res if t)
    wifi_n = sum(1 for w, _t in res if w)
    fit, qok, nr = cr.conf_checks(out, {r: "confined" for r in rs})
    nl = br.logins(out)
    on_ok = [x for x in on_fired if x is not None]
    on_med = st.median(on_ok) if on_ok else -1
    ok = {"M1": k > 0 and complete == k and aligned >= ALIGN * k,
          "M2": nr > 0 and fit == nr and qok == nr,
          "M3": nl == 0,
          "M4": (complete > 0 and switched == complete and len(on_ok) == complete
                 and all(x is not None and x <= OFF_MAX for x in off_fired) and on_med >= ON_MIN),
          "M5": resid_tail >= MIN_RESID_TAIL and wifi_n >= MIN_WIFI}
    print("  rounds %d, complete %d, on aligned %d; the Wi-Fi's interrupt is %s" % (k, complete, aligned, name))
    print("  M1 complete %d/%d, on aligned %d/%d (want all complete, >= 90%% aligned) -> %s"
          % (complete, k, aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds confined %d/%d, QEMU's threads on %s %d/%d (want all) -> %s"
          % (fit, nr, cr.QEMU, qok, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M3"] else "FAILED"))
    print("  M4 radio as designed in %d/%d rounds; the Wi-Fi's interrupt: off max %s (want <= %d in every "
          "arm-round), on median %s (want >= %d) -> %s"
          % (switched, complete, max((x for x in off_fired if x is not None), default="-"), OFF_MAX, on_med,
             ON_MIN, "ok" if ok["M4"] else "FAILED"))
    print("  M5 on residual tail %d (want >= %d), WIFI residual %d (want >= %d) -> %s"
          % (resid_tail, MIN_RESID_TAIL, wifi_n, MIN_WIFI, "ok" if ok["M5"] else "FAILED"))
    print("  median DIFF (off - on, us): p50 %+.1f  p99 %+.1f  p99.9 %+.1f (p99.9 not predicted)"
          % (med["p50"], med["p99"], med["p999"]))
    print("  EXCESS: %.2f%% of off at or above on's pooled p99 (%.1f us)" % (excess, cut))
    print("  LIFT: WIFI among the residual tail over the rest: %.1f" % lf)
    scored = k == SCORED_K
    base = ["M1", "M2", "M3", "M4"]
    print("  P1  p99 falls: median DIFF(p99) %+.1f us -> %s"
          % (med["p99"], ir.verdict(ir.grade(med["p99"], P99_HELD, 0.0), scored, k, ok, base)))
    print("  P2  fewer slow exchanges: EXCESS %.2f%% -> %s"
          % (excess, ir.verdict(ir.grade(excess, EXCESS_HELD, EXCESS_REFUTED), scored, k, ok, base)))
    print("  P3  the median does not move: |median DIFF(p50)| %.1f us -> %s"
          % (abs(med["p50"]), ir.verdict("HELD" if abs(med["p50"]) <= P50_BAND else "REFUTED", scored, k, ok, base)))
    print("  P4  the Wi-Fi's interrupt goes with the residual tail: LIFT %.1f -> %s"
          % (lf, ir.verdict(ir.grade(lf, LIFT_HELD, LIFT_REFUTED, lower=False), scored, k, ok, base + ["M5"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
