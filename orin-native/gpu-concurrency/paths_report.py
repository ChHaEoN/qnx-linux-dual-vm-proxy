#!/usr/bin/env python3
"""paths_report.py OUT -- run-paths.sh's ladder of every way across the partition, by the rule the
harness's header fixed before any run (Phase 3b / A6, 2026-09-29).

Per arm (T tcp, U udp, S someip, P polled shm, K console-kicked shm, B MSI-X shm) and round: the
probe's p50, p90, p99 and p99.9; for the notified arms the probe's own notification counts; and
from KVM's snapshots the guest vCPU threads' run time and KVM's exits over the arm, per exchange
(warm-up included), and the vCPUs' busy share of the snapshot window. Differences are paired
within the round; the interval is the distribution-free one of widest coverage >= 95%. The
guest's console (console-A_r<round>.log) is read for M3. Each check is kept per arm (M1, M2) or
per line (M3), and a prediction is VOID only when a check it rests on fails.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("T", "U", "S", "P", "K", "B")
PROTO = {"T": "tcp", "U": "udp", "S": "someip", "P": "shm", "K": "shmdb", "B": "shmbell"}
NOTIFIED = ("K", "B")
K_RULE = 18
P1_BT, P1_BU, P2_PB, P3_ST, P4_BK = -80.0, -60.0, -15.0, 3.0, -40.0
VCPU = re.compile(r"^CPU \d+/KVM$")
CONSOLE = {
    "msixcfg": re.compile(r"its: msixcfg: .* -> LPI 8193"),
    "console-kick": re.compile(r"serving shm-kick on .*slot @4096.* kick /dev/vcon2"),
    "msix": re.compile(r"serving shm-kick on .*slot @8192.* kick msix \(LPI 8193\)"),
}
# What each prediction rests on: M1 per arm, M2 per notified arm, M3 per console line.
NEEDS = {
    "P1": {"M1": ("T", "U", "B"), "M2": ("B",), "M3": ("msixcfg", "msix")},
    "P2": {"M1": ("P", "B"), "M2": ("B",), "M3": ("msixcfg", "msix")},
    "P3": {"M1": ("S", "T"), "M2": (), "M3": ()},
    "P4": {"M1": ("K", "B"), "M2": ("K", "B"), "M3": ("msixcfg", "console-kick", "msix")},
}


def load(out):
    lat, kvm, broken = {}, {}, []
    for f in sorted(os.listdir(out)):
        m = re.match(r"lat-([TUSPKB])_r(\d+)\.json$", f)
        if m:
            try:
                lat[(m.group(1), int(m.group(2)))] = json.load(open(os.path.join(out, f)))["summary"]
            except (ValueError, KeyError, TypeError):
                broken.append((m.group(1), int(m.group(2))))
        m = re.match(r"kvm-([TUSPKB])_r(\d+)\.json$", f)
        if m:
            try:
                kvm[(m.group(1), int(m.group(2)))] = json.load(open(os.path.join(out, f)))
            except ValueError:
                pass
    return lat, kvm, broken


def counter_per_ex(doc, counter, exchanges):
    try:
        x, y = doc["before"]["counters"][counter], doc["after"]["counters"][counter]
    except (KeyError, TypeError):
        return None
    if x is None or y is None or not exchanges:
        return None
    return (y - x) / float(exchanges)


def vcpu_run_ns(doc, smp):
    """The guest vCPU threads' run time over the arm in ns, or None unless exactly smp vCPU threads,
    the same ones, appear before and after."""
    try:
        b, a = doc["before"]["threads"], doc["after"]["threads"]
    except (KeyError, TypeError):
        return None
    tb = {tid for tid, t in b.items() if VCPU.match(t.get("comm", ""))}
    ta = {tid for tid, t in a.items() if VCPU.match(t.get("comm", ""))}
    if not smp or tb != ta or len(ta) != smp:
        return None
    return sum(a[tid]["run_ns"] - b[tid]["run_ns"] for tid in ta)


def vcpu_us_per_ex(doc, exchanges, smp):
    ns = vcpu_run_ns(doc, smp)
    return None if ns is None or not exchanges else ns / 1000.0 / exchanges


def vcpu_busy_pct(doc, smp):
    ns = vcpu_run_ns(doc, smp)
    try:
        dt = doc["after"]["t_ns"] - doc["before"]["t_ns"]
    except (KeyError, TypeError):
        return None
    return None if ns is None or dt <= 0 else 100.0 * ns / (dt * smp)


def graded(m, hi, thr):
    if m <= thr:
        return "HELD"
    return "PARTIAL" if (m < 0 and hi < 0) else "REFUTED"


def fmt(v, spec):
    return "-" if v is None or v != v else spec % v


def main(argv):
    out = argv[0]
    sp = os.path.join(out, "stamp.json")
    stamp = json.load(open(sp)) if os.path.exists(sp) else {}
    n_want, warm, k_want, smp = stamp.get("n"), stamp.get("warmup", 200), stamp.get("k"), stamp.get("smp")
    core = (stamp.get("pin") or {}).get("probe")
    lat, kvm, broken = load(out)
    rounds = sorted({r for _, r in lat} | {r for _, r in broken})
    exchanges = (n_want or 0) + warm

    m1 = {a: [] for a in ARMS}
    m1_all = []
    if k_want is None:
        m1_all.append("the stamp has no k")
    elif rounds != list(range(1, k_want + 1)):
        m1_all.append("rounds %s, the stamp's k=%d" % (rounds, k_want))
    m2 = {a: [] for a in NOTIFIED}
    for a in ARMS:
        for r in rounds:
            s = lat.get((a, r))
            if s is None:
                m1[a].append("r%d: %s" % (r, "unreadable" if (a, r) in broken else "missing"))
                continue
            bad = [x for x, ok in (("n", n_want is None or s.get("n") == n_want),
                                   ("warm-up", s.get("warmup_discarded") == warm),
                                   ("bad", s.get("bad") == 0),
                                   ("rejected", s.get("rejected_by_monitor") == 0),
                                   ("proto", s.get("proto") == PROTO[a]),
                                   ("core", core is None or s.get("cpu_affinity") == [core])) if not ok]
            if bad:
                m1[a].append("r%d: %s" % (r, ", ".join(bad)))
            if a in NOTIFIED:
                nt = s.get("notify") or {}
                if not (nt.get("exchanges") == exchanges and nt.get("notifications") == exchanges
                        and nt.get("wakeups") == exchanges and nt.get("early_wakeups") == 0
                        and nt.get("stray") == 0 and nt.get("eagain") == 0):
                    m2[a].append("r%d: notify %s" % (r, nt))
    m3 = {name: [] for name in CONSOLE}
    for r in rounds:
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        for name, rx in CONSOLE.items():
            if len(rx.findall(text)) != 1:
                m3[name].append("r%d" % r)
    keys = [(a, r) for a in ARMS for r in rounds]
    m4 = bool(rounds) and all(k in kvm and vcpu_us_per_ex(kvm[k], exchanges, smp) is not None
                              and counter_per_ex(kvm[k], "exits", exchanges) is not None for k in keys)
    ok1 = bool(rounds) and not m1_all and not any(m1.values())
    ok2 = bool(rounds) and not any(m2.values())
    ok3 = bool(rounds) and not any(m3.values())
    print("  rounds %d (stamp k=%s, smp=%s)" % (len(rounds), k_want, smp))
    print("  M1 every arm a round for each of 1..k of n samples after the warm-up, none rejected or bad, "
          "its own transport, the probe on core %s -> %s" % (core, "ok" if ok1 else "FAILED"))
    for msg in m1_all:
        print("     %s" % msg)
    for a in ARMS:
        if m1[a]:
            print("     %s: %s" % (a, "; ".join(m1[a][:4])))
    print("  M2 K and B: one doorbell per exchange, one wake-up each, none early, no stray byte, no EAGAIN -> %s"
          % ("ok" if ok2 else "FAILED"))
    for a in NOTIFIED:
        if m2[a]:
            print("     %s: %s" % (a, "; ".join(m2[a][:3])))
    print("  M3 every boot: msixcfg done, the console and msix monitors serving -> %s" % ("ok" if ok3 else "FAILED"))
    for name in CONSOLE:
        if m3[name]:
            print("     %s: not exactly one line in %s" % (name, ", ".join(m3[name][:6])))
    print("  M4 KVM's counters and all %s vCPU threads' run times around every arm -> %s"
          % (smp, "ok" if m4 else "FAILED"))
    if not rounds:
        return 0

    unscored = k_want != K_RULE or bool(stamp.get("smoke"))

    def verdict(p, v):
        if m1_all:
            return "VOID (M1 failed: rounds)"
        need = NEEDS[p]
        failed = ["M1 on %s" % a for a in need["M1"] if m1[a]]
        failed += ["M2 on %s" % a for a in need["M2"] if m2[a]]
        failed += ["M3 %s" % name for name in need["M3"] if m3[name]]
        if failed:
            return "VOID (%s failed)" % ", ".join(failed)
        if unscored:
            return "UNSCORED (k=%s%s; the rule is fixed at k = %d)" % (
                k_want, ", smoke" if stamp.get("smoke") else "", K_RULE)
        return v

    def us(a, r, key):
        return lat[(a, r)][key] * 1000.0

    def d(a, b, key="p50_ms"):
        return [us(a, r, key) - us(b, r, key) for r in rounds if (a, r) in lat and (b, r) in lat]

    def show(label, vals, unit="us"):
        if not vals:
            print("    %-28s (no data)" % label)
            return float("nan"), float("nan"), float("nan")
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-28s %+9.2f [%+.2f, %+.2f] %s (%.1f%%), > 0 in %d/%d"
              % (label, m, lo, hi, unit, 100 * cov, sum(v > 0 for v in vals), len(vals)))
        return m, lo, hi

    def med(xs):
        xs = [x for x in xs if x is not None]
        return st.median(xs) if xs else None

    print("  per arm, medians over rounds:   p50 us   p90 us   p99 us  p99.9 us   vCPU us/ex   exits/ex   vCPU busy %")
    for a in ARMS:
        vals = [med(us(a, r, key) for r in rounds if (a, r) in lat) for key in ("p50_ms", "p90_ms", "p99_ms", "p999_ms")]
        cpu = med(vcpu_us_per_ex(kvm.get((a, r)), exchanges, smp) for r in rounds)
        ex = med(counter_per_ex(kvm.get((a, r)), "exits", exchanges) for r in rounds)
        busy = med(vcpu_busy_pct(kvm.get((a, r)), smp) for r in rounds)
        print("    %-2s %-8s %8s %8s %8s %8s %12s %10s %13s" % (
            (a, PROTO[a]) + tuple(fmt(v, "%.2f") for v in vals)
            + (fmt(cpu, "%.1f"), fmt(ex, "%.2f"), fmt(busy, "%.1f"))))
    print("  differences at p50, paired within round: median [interval], rounds > 0")
    bt, _, bt_hi = show("B - T", d("B", "T"))
    bu, _, bu_hi = show("B - U", d("B", "U"))
    pb, _, pb_hi = show("P - B", d("P", "B"))
    s_t, st_lo, st_hi = show("S - T", d("S", "T"))
    bk, _, bk_hi = show("B - K", d("B", "K"))
    show("U - T, unscored", d("U", "T"))
    print("  differences at p99, unscored")
    for a, b in (("B", "T"), ("B", "U"), ("P", "B"), ("S", "T"), ("B", "K")):
        show("%s - %s at p99" % (a, b), d(a, b, "p99_ms"))

    if bt <= P1_BT and bu <= P1_BU:
        p1 = "HELD"
    elif bt < 0 and bu < 0 and bt_hi < 0 and bu_hi < 0:
        p1 = "PARTIAL"
    else:
        p1 = "REFUTED"
    if abs(s_t) <= P3_ST and -P3_ST <= st_lo and st_hi <= P3_ST:
        p3 = "HELD"
    elif abs(s_t) <= P3_ST:
        p3 = "PARTIAL"
    else:
        p3 = "REFUTED"
    print("  P1  B - T %+.2f (<= %.0f), B - U %+.2f (<= %.0f) -> %s" % (bt, P1_BT, bu, P1_BU, verdict("P1", p1)))
    print("  P2  P - B %+.2f (<= %.0f) -> %s" % (pb, P2_PB, verdict("P2", graded(pb, pb_hi, P2_PB))))
    print("  P3  S - T %+.2f [%+.2f, %+.2f] (inside +-%.0f) -> %s" % (s_t, st_lo, st_hi, P3_ST, verdict("P3", p3)))
    print("  P4  B - K %+.2f (<= %.0f) -> %s" % (bk, P4_BK, verdict("P4", graded(bk, bk_hi, P4_BK))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
