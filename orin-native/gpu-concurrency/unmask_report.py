#!/usr/bin/env python3
"""unmask_report.py OUT -- run-unmask.sh's comparison of where the doorbell's LPI is unmasked, by the
rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-29).

U: InterruptUnmask as soon as InterruptWait returns, before the reply. D: the next InterruptWait
unmasks it (_NTO_INTR_WAIT_FLAGS_UNMASK), after the reply. The same attach and the same wait
otherwise. The two images swap which vector each arm sits on (order.log names each round's image).
Per arm and round: the probe's p50, p90, p99 and p99.9, its notification counts, and KVM's exit
counters over the arm divided by its exchanges (warm-up included). Every difference is D - U,
paired within the round; the interval is the distribution-free one of widest coverage >= 95%.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("U", "D")
VECTOR = {"a": {"U": 0, "D": 1}, "b": {"U": 1, "D": 0}}
SLOT = {0: 8192, 1: 12288}
P1_HELD, P2_BAND, M5_BAND = -2.0, 0.5, 0.3
EXITS = ("mmio_exit_kernel", "mmio_exit_user", "exits", "halt_wakeup", "halt_attempted_poll", "halt_successful_poll")
MSIXCFG = (re.compile(r"its: msixcfg: .*EventID 0 -> LPI 8193"), re.compile(r"its: msixcfg: .*EventID 1 -> LPI 8194"))
BANNER = re.compile(r"serving shm-kick on .*slot @(\d+);.* kick (msix1?(?::defer)?) \(LPI (\d+)(, unmask deferred)?\)")
SLOT_RX = re.compile(r"slot @(\d+)")
WANT = {"a": {8192: ("msix", "8193", False), 12288: ("msix1:defer", "8194", True)},
        "b": {8192: ("msix:defer", "8193", True), 12288: ("msix1", "8194", False)}}


def per_exchange(doc, counter, exchanges):
    try:
        x, y = doc["before"]["counters"][counter], doc["after"]["counters"][counter]
    except (KeyError, TypeError):
        return None
    if x is None or y is None or not exchanges:
        return None
    return (y - x) / float(exchanges)


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

    image = {}
    op = os.path.join(out, "order.log")
    if os.path.exists(op):
        for ln in open(op, encoding="utf-8"):
            m = re.match(r"round (\d+) image ([ab]) order: ([UD]) ([UD])\s*$", ln)
            if m:
                image[int(m.group(1))] = m.group(2)
    m1, m2, m3, m4 = [], [], [], []
    if not rounds:
        m1.append("the stamp has no k")
    lat, kvm = {}, {}
    for r in rounds:
        im = image.get(r)
        if im is None:
            m1.append("r%d: no image in order.log" % r)
            continue
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        seen = {}
        for mm in BANNER.finditer(text):
            seen.setdefault(int(mm.group(1)), []).append((mm.group(2), mm.group(3), bool(mm.group(4))))
        bad3 = [rx.pattern for rx in MSIXCFG if len(rx.findall(text)) != 1]
        bad3 += ["slot %d" % sl for sl, want in WANT[im].items() if seen.get(sl) != [want]]
        if bad3:
            m3.append("r%d (image %s): %s" % (r, im, "; ".join(bad3)))
        for a in ARMS:
            v = VECTOR[im][a]
            s = (jload("lat-%s_r%d.json" % (a, r)) or {}).get("summary")
            if s is None:
                m1.append("%s_r%d: missing" % (a, r))
                continue
            lat[(a, r)] = s
            bad = [x for x, ok in (("n", s.get("n") == n_want), ("warm-up", s.get("warmup_discarded") == warm),
                                   ("bad", s.get("bad") == 0), ("rejected", s.get("rejected_by_monitor") == 0),
                                   ("proto", s.get("proto") == "shmbell"), ("vector", s.get("bell_vector", 0) == v),
                                   ("slot", [int(x) for x in SLOT_RX.findall(s.get("shm_region") or "")] == [SLOT[v]]),
                                   ("core", core is None or s.get("cpu_affinity") == [core])) if not ok]
            if bad:
                m1.append("%s_r%d: %s" % (a, r, ", ".join(bad)))
            # the monitor on the arm's slot must unmask as the arm says
            if seen.get(SLOT[v]) and seen[SLOT[v]][0][2] != (a == "D"):
                m3.append("%s_r%d: the monitor on slot %d does not unmask as %s does" % (a, r, SLOT[v], a))
            nt = s.get("notify") or {}
            if not (nt.get("exchanges") == exchanges and nt.get("notifications") == exchanges
                    and nt.get("early_wakeups") == 0 and nt.get("stray") == 0):
                m2.append("%s_r%d: notify %s" % (a, r, nt))
            kv = jload("kvm-%s_r%d.json" % (a, r))
            if kv is None or per_exchange(kv, "mmio_exit_kernel", exchanges) is None:
                m4.append("%s_r%d: no KVM counters" % (a, r))
            else:
                kvm[(a, r)] = kv
    ok = {"M1": bool(rounds) and not m1, "M2": bool(rounds) and not m2, "M3": bool(rounds) and not m3,
          "M4": bool(rounds) and not m4}
    print("  rounds %d, %d exchanges per arm" % (len(rounds), exchanges))
    for name, msgs, desc in (
            ("M1", m1, "U and D: n samples after the warm-up per round, none rejected or bad, shmbell on the image's "
                       "vector and slot, the probe on core %s" % core),
            ("M2", m2, "one doorbell per exchange, none early, no stray byte"),
            ("M3", m3, "every boot: both vectors mapped (LPI 8193, 8194), both monitors serving with the image's "
                       "waits, each arm's slot unmasking as the arm says"),
            ("M4", m4, "KVM's counters around every arm")):
        print("  %s %s -> %s" % (name, desc, "ok" if ok[name] else "FAILED"))
        for msg in msgs[:6]:
            print("     %s" % msg)

    def show(label, vals, unit="us"):
        if not vals:
            print("    %-36s (no data)" % label)
            return float("nan"), float("nan")
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-36s %+9.3f [%+.3f, %+.3f] %s (%.1f%%), > 0 in %d/%d"
              % (label, m, lo, hi, unit, 100 * cov, sum(v > 0 for v in vals), len(vals)))
        return m, hi

    def d(key, rs=None):
        return [(lat[("D", r)][key] - lat[("U", r)][key]) * 1000.0 for r in (rounds if rs is None else rs)
                if ("D", r) in lat and ("U", r) in lat]

    def dk(counter):
        vals = []
        for r in rounds:
            if ("D", r) in kvm and ("U", r) in kvm:
                x, y = per_exchange(kvm[("D", r)], counter, exchanges), per_exchange(kvm[("U", r)], counter, exchanges)
                if x is not None and y is not None:
                    vals.append(x - y)
        return vals

    print("  per arm, medians over rounds:   p50 us   p90 us   p99 us  p99.9 us")
    for a in ARMS:
        vals = []
        for key in ("p50_ms", "p90_ms", "p99_ms", "p999_ms"):
            xs = [lat[(a, r)][key] * 1000.0 for r in rounds if (a, r) in lat]
            vals.append("%8.2f" % st.median(xs) if xs else "       -")
        print("    %s %s" % (a, " ".join(vals)))
    print("  D - U, paired within round")
    p50, p50_hi = show("p50", d("p50_ms"))
    for key in ("p90_ms", "p99_ms", "p999_ms"):
        show("%s, unscored" % key[:-3], d(key))
    per_img = {}
    for im in ("a", "b"):
        per_img[im], _ = show("p50 in image %s (way +- vector), unscored" % im,
                              d("p50_ms", [r for r in rounds if image.get(r) == im]))
    print("    %-36s %+9.3f us" % ("vector effect, (a - b) / 2, unscored", (per_img["a"] - per_img["b"]) / 2.0))
    print("  KVM per exchange, D - U")
    mk, _ = show("mmio_exit_kernel", dk("mmio_exit_kernel"), "/ex")
    hw, _ = show("halt_wakeup (M5)", dk("halt_wakeup"), "/ex")
    for c in EXITS[2:]:
        if c != "halt_wakeup":
            show("%s, unscored" % c, dk(c), "/ex")
    show("mmio_exit_user, unscored", dk("mmio_exit_user"), "/ex")

    m5 = None if hw != hw else abs(hw) <= M5_BAND
    print("  M5 (a qualifier) |D - U halt_wakeup| %.3f /ex (<= %.1f) -> %s"
          % (abs(hw), M5_BAND, {None: "not evaluated", True: "ok", False: "FAILED"}[m5]))

    def verdict(v, needs):
        failed = [m for m in needs if not ok[m]]
        if failed:
            return "VOID (%s failed)" % ", ".join(failed)
        return v if m5 is not False else "%s -- H1 not supported: the ways differ in wake-ups" % v

    p1 = "HELD" if (p50 <= P1_HELD and p50_hi < 0) else ("PARTIAL" if p50_hi < 0 else "REFUTED")
    p2 = "HELD" if abs(mk) <= P2_BAND else "REFUTED"
    print("  P1  D - U at p50 %+.3f (<= %.1f, interval upper %+.3f < 0) -> %s"
          % (p50, P1_HELD, p50_hi, verdict(p1, ("M1", "M2", "M3"))))
    print("  P2  D - U mmio_exit_kernel %+.3f /ex (within +-%.1f) -> %s" % (mk, P2_BAND, verdict(p2, ("M1", "M2", "M3", "M4"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
