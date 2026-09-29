#!/usr/bin/env python3
"""mmio_report.py OUT -- run-mmio.sh's count of where the two ways into the guest trap, by the rule
the harness's header fixed before any run (Phase 3b / A6, 2026-09-29).

Per window (arm K, B or I, per round) mmio_trace.py has left mmio-<arm>_r<round>.json (accesses per
guest-physical address, reads and writes, how many went out to QEMU) and the harness
window-<arm>_r<round>.json (the window's monotonic start and end). This script puts each address in
a region (the QEMU virt machine's map, and ivshmem's BAR0 and BAR1 as the boot's console reports
them), takes the background out within the round (I's count per ns of I's window, times the arm's
window length), divides by the arm's exchanges (warm-up included), and takes the median over rounds.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("K", "B", "I")
PROTO = {"K": "shmdb", "B": "shmbell"}
CONSOLE_VIRTIO = 0x0A003800
VIRTIO_STATUS, VIRTIO_ACK = 0x60, 0x64
FIXED = [  # name, base, size -- QEMU virt's memory map; checked before BAR0/BAR1 and ECAM
    ("GICD", 0x08000000, 0x10000),
    ("GITS", 0x08080000, 0x20000),
    ("GICR", 0x080A0000, 0xF60000),
    ("UART", 0x09000000, 0x1000),
    ("console", CONSOLE_VIRTIO, 0x200),
    ("virtio", 0x0A000000, 0x4000),
    ("ECAM", 0x3F000000, 0x1000000),
    ("ECAM", 0x4010000000, 0x10000000),
]
DOORBELL = 0xC
P1_HI, P1_LO, P2_REG, P2_SHARE, P2_LO = 2.0, 0.2, 0.9, 0.90, 0.2
M3_LO, M3_HI, M4_REL, M4_ABS = 0.98, 1.05, 1.02, 20
BAR0_RX = re.compile(r"shm configured: .*BAR0 (0x[0-9a-fA-F]+) \((\d+) bytes\)")
BAR1_RX = re.compile(r"its: msixcfg: .*BAR1 (0x[0-9a-fA-F]+) \((\d+) B\)")
LPI_RX = re.compile(r"Setting up .*LPIs|Implementation supports .*LPIs")
KEY = re.compile(r"^(0x[0-9a-f]+)\|([rw])$")


def bars(console_text):
    """The boot's ivshmem BAR0 and BAR1 as (name, base, size), from the console, or None."""
    b0, b1 = BAR0_RX.findall(console_text), BAR1_RX.findall(console_text)
    if len(set(b0)) != 1 or len(set(b1)) != 1:
        return None
    return [("BAR0", int(b0[0][0], 16), int(b0[0][1])), ("BAR1", int(b1[0][0], 16), int(b1[0][1]))]


def region(gpa, bar_list):
    for name, base, size in FIXED[:6] + bar_list + FIXED[6:]:
        if base <= gpa < base + size:
            return name, gpa - base
    return "other", gpa


def classify(doc, bar_list):
    """{(region, offset, rw, 'kernel'|'user'): count} for one window."""
    out = {}
    for key, n in doc["accesses"].items():
        m = KEY.match(key)
        gpa, rw = int(m.group(1), 16), m.group(2)
        reg, off = region(gpa, bar_list)
        u = doc["to_userspace"].get(key, 0)
        for where, c in (("kernel", n - u), ("user", u)):
            if c:
                out[(reg, off, rw, where)] = out.get((reg, off, rw, where), 0) + c
    return out


def total(cls, reg=None, rw=None, where=None, off=None):
    return sum(c for (g, o, w, h), c in cls.items()
               if (reg is None or g == reg) and (rw is None or w == rw) and (where is None or h == where)
               and (off is None or o == off))


def main(argv):
    out = argv[0]
    sp = os.path.join(out, "stamp.json")
    stamp = json.load(open(sp)) if os.path.exists(sp) else {}
    n_want, warm, k_want, smp = stamp.get("n"), stamp.get("warmup", 200), stamp.get("k"), stamp.get("smp", 2)
    core = (stamp.get("pin") or {}).get("probe")
    exchanges = (n_want or 0) + warm

    def jload(name):
        try:
            return json.load(open(os.path.join(out, name)))
        except (OSError, ValueError):
            return None

    rounds = list(range(1, (k_want or 0) + 1))
    m1, m2, m3, m4 = [], [], [], []
    if not rounds:
        m1.append("the stamp has no k")
    if not n_want:
        m1.append("the stamp has no n")
    cls, dur, lpi_lines = {}, {}, set()
    for r in rounds:
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        lpi_lines.update(ln.strip() for ln in text.splitlines() if LPI_RX.search(ln))
        bl = bars(text)
        if bl is None:
            m3.append("r%d: BAR0/BAR1 not read from the console" % r)
        for a in ARMS:
            if a in PROTO:
                s = (jload("lat-%s_r%d.json" % (a, r)) or {}).get("summary")
                if s is None:
                    m1.append("%s_r%d: missing" % (a, r))
                else:
                    nt = s.get("notify") or {}
                    bad = [x for x, ok in (
                        ("n", s.get("n") == n_want), ("warm-up", s.get("warmup_discarded") == warm),
                        ("bad", s.get("bad") == 0), ("rejected", s.get("rejected_by_monitor") == 0),
                        ("proto", s.get("proto") == PROTO[a]),
                        ("core", core is None or s.get("cpu_affinity") == [core]),
                        ("notify", nt.get("exchanges") == exchanges and nt.get("notifications") == exchanges
                         and nt.get("early_wakeups") == 0 and nt.get("stray") == 0)) if not ok]
                    if bad:
                        m1.append("%s_r%d: %s" % (a, r, ", ".join(bad)))
            elif jload("kvm-I_r%d.json" % r) is None:
                m1.append("I_r%d: no KVM snapshot" % r)
            w = jload("window-%s_r%d.json" % (a, r)) or {}
            try:
                dur[(a, r)] = int(w["t1_ns"]) - int(w["t0_ns"])
                if dur[(a, r)] <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                dur.pop((a, r), None)
                m1.append("%s_r%d: no window length" % (a, r))
            doc = jload("mmio-%s_r%d.json" % (a, r))
            if doc is None or "accesses" not in doc or "to_userspace" not in doc:
                m2.append("%s_r%d: no reduced trace" % (a, r))
                continue
            reads = sum(v for k, v in doc["accesses"].items() if k.endswith("|r"))
            if doc.get("lines_matched") != doc.get("entries"):
                m2.append("%s_r%d: %s lines parsed, %s entries in the buffer"
                          % (a, r, doc.get("lines_matched"), doc.get("entries")))
            if doc.get("events") != doc.get("lines_matched"):
                m2.append("%s_r%d: an event other than the two" % (a, r))
            if not (0 <= doc.get("unpaired_mmio_exits", 0) <= smp
                    and abs(reads - sum(doc.get("reads_completed", {}).values())) <= smp):
                m2.append("%s_r%d: unpaired exits or reads beyond a window's edges" % (a, r))
            if bl is None:
                continue
            c = classify(doc, bl)
            cls[(a, r)] = c
            if a in PROTO:
                db = total(c, "BAR0", "w", off=DOORBELL)
                if not (M3_LO * exchanges <= db <= M3_HI * exchanges) or total(c, "BAR0", "w", "user", DOORBELL):
                    m3.append("%s_r%d: doorbell writes %d (%d to userspace) for %d exchanges"
                              % (a, r, db, total(c, "BAR0", "w", "user", DOORBELL), exchanges))
                kv = jload("kvm-%s_r%d.json" % (a, r)) or {}
                try:
                    b, af = kv["before"]["counters"], kv["after"]["counters"]
                    ck = (af["mmio_exit_kernel"] - b["mmio_exit_kernel"]) + (af["mmio_exit_user"] - b["mmio_exit_user"])
                    cu = af["mmio_exit_user"] - b["mmio_exit_user"]
                except (KeyError, TypeError):
                    m4.append("%s_r%d: no KVM counters" % (a, r))
                else:
                    for label, t, cnt in (("all", total(c), ck), ("user", total(c, where="user"), cu)):
                        if not (cnt <= t <= cnt * M4_REL + M4_ABS):
                            m4.append("%s_r%d: traced %s %d, KVM counted %d" % (a, r, label, t, cnt))
    checks = (("M1", m1, "K and B: n samples after the warm-up per round, none rejected or bad, own transport, "
                         "the probe on core %s, one doorbell per exchange; I windows; window lengths" % core),
              ("M2", m2, "every window's trace whole, only the two events, pairs complete but at the edges"),
              ("M3", m3, "the reply doorbell, BAR0 + 0xc, %.2f-%.2f writes per exchange, all in the kernel; "
                         "BAR0/BAR1 read from every boot" % (M3_LO, M3_HI)),
              ("M4", m4, "traced accesses match KVM's MMIO exit counters (all, and userspace)"))
    ok = bool(rounds) and all(not msgs for _n, msgs, _d in checks)
    print("  rounds %d, %d exchanges per arm" % (len(rounds), exchanges))
    for name, msgs, desc in checks:
        print("  %s %s -> %s" % (name, desc, "ok" if not msgs and rounds else "FAILED"))
        for msg in msgs[:6]:
            print("     %s" % msg)

    def verdict(v):
        return v if ok else "VOID (%s failed)" % (", ".join(n for n, msgs, _d in checks if msgs or not rounds))

    def net(a, r, **sel):
        """The arm's count in round r with I's background taken out, per exchange; None if it cannot be."""
        if (a, r) not in cls or ("I", r) not in cls or (a, r) not in dur or ("I", r) not in dur or not exchanges:
            return None
        return (total(cls[(a, r)], **sel) - total(cls[("I", r)], **sel) * dur[(a, r)] / float(dur[("I", r)])) \
            / float(exchanges)

    def med(vals):
        vals = [v for v in vals if v is not None]
        return (st.median(vals), vals) if vals else (float("nan"), [])

    def show(label, vals):
        m, vs = med(vals)
        if not vs:
            print("    %-40s (no data)" % label)
            return m
        lo, hi, cov = interval(vs)
        print("    %-40s %8.3f [%.3f, %.3f] (%.1f%%)" % (label, m, lo, hi, 100 * cov))
        return m

    for msg in sorted(lpi_lines):
        print("  LPI setup, from the boots' consoles (unscored): %s" % msg)
    regions = sorted({g for c in cls.values() for (g, _o, _w, _h) in c})
    if cls:
        print("  per arm, net per exchange, medians over rounds: region  read-kernel read-user write-kernel write-user")
        for a in ("K", "B"):
            for g in regions:
                row = [med(net(a, r, reg=g, rw=rw, where=wh) for r in rounds)[0]
                       for rw, wh in (("r", "kernel"), ("r", "user"), ("w", "kernel"), ("w", "user"))]
                if any(v and abs(v) >= 0.0005 for v in row):
                    print("    %s  %-8s %10.3f %9.3f %12.3f %10.3f" % ((a, g) + tuple(row)))
        print("  background, I's accesses per 2 ms, medians over rounds (unscored)")
        for g in regions:
            v = med(total(cls[("I", r)], g) * 2e6 / dur[("I", r)] for r in rounds
                    if ("I", r) in cls and ("I", r) in dur)[0]
            if v and v >= 0.0005:
                print("    I  %-8s %10.4f" % (g, v))
        print("  registers in GICD, GITS and the console's transport, net per exchange (medians)")
        offs = sorted({(g, o, w) for c in cls.values() for (g, o, w, _h) in c if g in ("GICD", "GITS", "console")})
        for g, o, w in offs:
            print("    %-8s +%#07x %s  K %8.3f  B %8.3f" % (g, o, w, med(net("K", r, reg=g, rw=w, off=o) for r in rounds)[0],
                                                          med(net("B", r, reg=g, rw=w, off=o) for r in rounds)[0]))
        print("  K - B per region, per exchange, paired within round: median [interval]")
        for g in regions:
            d = [(total(cls[("K", r)], g) - total(cls[("B", r)], g)) / float(exchanges)
                 for r in rounds if ("K", r) in cls and ("B", r) in cls]
            if d and any(v != 0 for v in d):
                lo, hi, cov = interval(d)
                print("    %-8s %+8.3f [%+.3f, %+.3f] (%.1f%%)" % (g, st.median(d), lo, hi, 100 * cov))

    print("  scored quantities, net per exchange: median [interval, not scored]")
    kd = show("K GICD", [net("K", r, reg="GICD") for r in rounds])
    bd = show("B GICD", [net("B", r, reg="GICD") for r in rounds])
    bt = show("B GITS", [net("B", r, reg="GITS") for r in rounds])
    kt = show("K GITS", [net("K", r, reg="GITS") for r in rounds])
    ks = show("K console +0x60 read, userspace", [net("K", r, reg="console", rw="r", where="user", off=VIRTIO_STATUS)
                                                  for r in rounds])
    ka = show("K console +0x64 write, userspace", [net("K", r, reg="console", rw="w", where="user", off=VIRTIO_ACK)
                                                   for r in rounds])
    shares = []
    for r in rounds:
        num = [net("K", r, reg="console", rw="r", where="user", off=VIRTIO_STATUS),
               net("K", r, reg="console", rw="w", where="user", off=VIRTIO_ACK)]
        den = net("K", r, where="user")
        if None not in num and den is not None:
            shares.append((num[0] + num[1]) / den if den > 0 else 0.0)
    sh = show("K's share of its userspace accesses", shares)
    bc = show("B console", [net("B", r, reg="console") for r in rounds])

    gicd, gits = kd >= P1_HI and bd <= P1_LO, bt >= P1_HI and kt <= P1_LO
    p1 = "HELD" if gicd and gits else ("PARTIAL" if gicd or gits else "REFUTED")
    p2 = "HELD" if ks >= P2_REG and ka >= P2_REG and sh >= P2_SHARE and bc <= P2_LO else "REFUTED"
    print("  P1  GICD K %.3f (>= %.1f), B %.3f (<= %.1f); GITS B %.3f (>= %.1f), K %.3f (<= %.1f) -> %s"
          % (kd, P1_HI, bd, P1_LO, bt, P1_HI, kt, P1_LO, verdict(p1)))
    print("  P2  console userspace +0x60 %.3f, +0x64 %.3f (each >= %.1f), share %.3f (>= %.2f); B's console %.3f "
          "(<= %.1f) -> %s" % (ks, ka, P2_REG, sh, P2_SHARE, bc, P2_LO, verdict(p2)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
