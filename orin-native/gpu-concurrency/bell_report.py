#!/usr/bin/env python3
"""bell_report.py OUT -- run-bell.sh's comparison of the two ways into the guest's notified shared
memory, by the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-29).

Per arm (K: the console kick, B: the MSI-X doorbell into the guest) and round: the probe's p50,
p90, p99 and p99.9, its own notification counts, and KVM's exit counters over the arm divided by
the arm's exchanges (warm-up included). Every difference is B - K, paired within the round; the
interval is the distribution-free one of widest coverage >= 95%. The guest's console
(console-A_r<round>.log) is read for M3.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("K", "B")
PROTO = {"K": "shmdb", "B": "shmbell"}
P1_HELD = -40.0
P3_USER, P3_KERNEL = -1.0, 2.0
EXITS = ("mmio_exit_user", "mmio_exit_kernel", "exits", "halt_attempted_poll", "halt_successful_poll",
         "halt_wakeup")
BANNER_K = re.compile(r"serving shm-kick on .*slot @4096.* kick /dev/vcon2")
BANNER_B = re.compile(r"serving shm-kick on .*slot @8192.* kick msix \(LPI 8193\)")
MSIXCFG = re.compile(r"its: msixcfg: .* -> LPI 8193")


def load(out):
    lat, kvm = {}, {}
    for f in os.listdir(out):
        m = re.match(r"lat-([KB])_r(\d+)\.json$", f)
        if m:
            lat[(m.group(1), int(m.group(2)))] = json.load(open(os.path.join(out, f)))["summary"]
        m = re.match(r"kvm-([KB])_r(\d+)\.json$", f)
        if m:
            kvm[(m.group(1), int(m.group(2)))] = json.load(open(os.path.join(out, f)))
    return lat, kvm


def per_exchange(doc, counter, exchanges):
    """(after - before) / exchanges for one KVM counter, or None when either end is missing."""
    try:
        x = doc["before"]["counters"][counter]
        y = doc["after"]["counters"][counter]
    except (KeyError, TypeError):
        return None
    if x is None or y is None or not exchanges:
        return None
    return (y - x) / float(exchanges)


def grade_p1(m, hi):
    if m <= P1_HELD:
        return "HELD"
    return "PARTIAL" if (m < 0 and hi < 0) else "REFUTED"


def grade_p2(m, hi):
    if m < 0 and hi < 0:
        return "HELD"
    return "PARTIAL" if m < 0 else "REFUTED"


def grade_p3(user, kern):
    got = (user <= P3_USER) + (kern >= P3_KERNEL)
    return ("REFUTED", "PARTIAL", "HELD")[got]


def main(argv):
    out = argv[0]
    sp = os.path.join(out, "stamp.json")
    stamp = json.load(open(sp)) if os.path.exists(sp) else {}
    n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    core = (stamp.get("pin") or {}).get("probe")
    lat, kvm = load(out)
    rounds = sorted({r for _, r in lat})
    keys = [(a, r) for a in ARMS for r in rounds]
    exchanges = (n_want or 0) + warm

    m1_problems, m2_problems = [], []
    for k in keys:
        s = lat.get(k)
        if s is None:
            m1_problems.append("%s_r%d: missing" % k)
            continue
        bad = [x for x, ok in (("n", n_want is None or s.get("n") == n_want), ("bad", s.get("bad") == 0),
                               ("rejected", s.get("rejected_by_monitor") == 0),
                               ("proto", s.get("proto") == PROTO[k[0]]),
                               ("core", core is None or s.get("cpu_affinity") == [core])) if not ok]
        if bad:
            m1_problems.append("%s_r%d: %s" % (k[0], k[1], ", ".join(bad)))
        nt = s.get("notify") or {}
        if not (nt.get("exchanges") == exchanges and nt.get("notifications") == exchanges
                and nt.get("early_wakeups") == 0 and nt.get("stray") == 0):
            m2_problems.append("%s_r%d: notify %s, want %d exchanges and notifications, none early or stray"
                               % (k[0], k[1], nt, exchanges))
    m3_problems = []
    for r in rounds:
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        have = [len(rx.findall(text)) for rx in (MSIXCFG, BANNER_K, BANNER_B)]
        if have != [1, 1, 1]:
            m3_problems.append("round %d: msixcfg %d, console monitor %d, msix monitor %d (want 1 each)"
                               % (r, have[0], have[1], have[2]))
    m4 = bool(rounds) and all(k in kvm and per_exchange(kvm[k], "mmio_exit_user", exchanges) is not None
                              and per_exchange(kvm[k], "mmio_exit_kernel", exchanges) is not None for k in keys)
    ok = {"M1": bool(rounds) and not m1_problems, "M2": bool(rounds) and not m2_problems,
          "M3": bool(rounds) and not m3_problems, "M4": m4}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected or bad, its own transport, the probe on "
          "core %s -> %s" % (len(rounds), core, "ok" if ok["M1"] else "FAILED"))
    for msg in m1_problems[:6]:
        print("     %s" % msg)
    print("  M2 one doorbell per exchange, none early, no stray byte -> %s" % ("ok" if ok["M2"] else "FAILED"))
    for msg in m2_problems[:6]:
        print("     %s" % msg)
    print("  M3 every boot: msixcfg done, the console and the msix monitors serving -> %s"
          % ("ok" if ok["M3"] else "FAILED"))
    for msg in m3_problems[:6]:
        print("     %s" % msg)
    print("  M4 KVM's counters around every arm -> %s" % ("ok" if ok["M4"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v, needs=("M1", "M2", "M3")):
        failed = [m for m in needs if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def us(a, r, key):
        return lat[(a, r)][key] * 1000.0

    both = [r for r in rounds if ("K", r) in lat and ("B", r) in lat]

    def d(key):
        return [us("B", r, key) - us("K", r, key) for r in both]

    def dk(counter):
        vals = []
        for r in both:
            b = per_exchange(kvm.get(("B", r)), counter, exchanges)
            k = per_exchange(kvm.get(("K", r)), counter, exchanges)
            if b is not None and k is not None:
                vals.append(b - k)
        return vals

    def show(label, vals, unit="us"):
        if not vals:
            print("    %-34s (no data)" % label)
            return float("nan"), float("nan")
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-34s %+9.2f [%+.2f, %+.2f] %s (%.1f%%), > 0 in %d/%d"
              % (label, m, lo, hi, unit, 100 * cov, sum(v > 0 for v in vals), len(vals)))
        return m, hi

    print("  per arm, medians over rounds (us):   p50      p90      p99    p99.9")
    for a in ARMS:
        vals = [st.median(us(a, r, key) for r in rounds if (a, r) in lat)
                for key in ("p50_ms", "p90_ms", "p99_ms", "p999_ms")]
        print("    %-2s %-8s %9.2f %8.2f %8.2f %8.2f" % ((a, PROTO[a]) + tuple(vals)))
    print("  B - K, paired within round: median [interval], rounds > 0")
    m50, hi50 = show("DIFF(p50)", d("p50_ms"))
    show("DIFF(p90), unscored", d("p90_ms"))
    m99, hi99 = show("DIFF(p99)", d("p99_ms"))
    show("DIFF(p99.9), unscored", d("p999_ms"))
    print("  KVM exits per exchange, B - K (warm-up included)")
    mu, _ = show("mmio_exit_user", dk("mmio_exit_user"), "/ex")
    mk, _ = show("mmio_exit_kernel", dk("mmio_exit_kernel"), "/ex")
    for c in EXITS[2:]:
        show("%s, unscored" % c, dk(c), "/ex")
    print("  P1  median DIFF(p50) %+.2f us, interval upper %+.2f (HELD at <= %.0f) -> %s"
          % (m50, hi50, P1_HELD, verdict(grade_p1(m50, hi50))))
    print("  P2  median DIFF(p99) %+.2f us, interval upper %+.2f -> %s"
          % (m99, hi99, verdict(grade_p2(m99, hi99))))
    print("  P3  mmio_exit_user %+.2f (want <= %.1f), mmio_exit_kernel %+.2f (want >= %+.1f) per exchange -> %s"
          % (mu, P3_USER, mk, P3_KERNEL, verdict(grade_p3(mu, mk), ("M1", "M2", "M3", "M4"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
