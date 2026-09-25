#!/usr/bin/env python3
"""metal_report.py OUT N WARMUP -- run-metal.sh's test on a host that is not the Orin: the
tick bin, and what confining the host's userspace changes (Phase 3b / A6, 2026-09-25), by
the rule its header fixed before any run.

stamp.json gives the host's online cores (ALL), the confined set (CONF), QEMU's cores and
HZ; the tick PERIOD is 1e6/HZ us. Each round has an ARM (order.log). Alignment and the out
class are run-natural.sh's (tick_report.exchanges). An out-class exchange is in the TICK BIN
when t0 is in [PERIOD - 150, PERIOD) mod PERIOD, TAIL when at or above its round's p99.
Pooled over both arms: the bin's tail RATIO and SLOWDOWN; per arm: p50 and p99 over every
timed exchange. confine.log holds udevd's, PID 1's and QEMU's allowed CPUs before and after
every round; tk-t2ms_rN.log the hrtimer expiries on QEMU's cores and the probe's. Scored
only at k = 40; a prediction resting on a failed check prints VOID.
"""
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
import tick_report as tr  # noqa: E402
import tick_trace as tkt  # noqa: E402

SCORED_K = 40
BIN_W, GRID_OK = 150.0, 100.0
RATIO, SLOW, TAIL_SAME, SAME, MIN_TAIL = 2.0, 3.0, 0.05, 2.0, 30


def cpus(s):
    out = set()
    for x in str(s).replace(" ", ",").split(","):
        if x:
            a, _, b = x.partition("-")
            out.update(range(int(a), int(b or a) + 1))
    return frozenset(out)


def host(out):
    s = json.load(open(os.path.join(out, "stamp.json")))
    h, pin = s.get("host", {}), s.get("pin", {})
    return {"all": cpus(h.get("all", "")), "conf": cpus(h.get("conf", "")), "hz": int(h.get("hz", 0) or 0),
            "qemu": cpus(pin.get("qemu", "0-2"))}


def states(out, arms, hs):
    """(rounds whose udevd and PID 1 fit their arm before and after, rounds whose QEMU
    threads stayed on QEMU's cores, rounds)."""
    seen = collections.defaultdict(list)
    p = os.path.join(out, "confine.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (before|after) udevd=(\S*) pid1=(\S*) gnome-shell=\S* qemu=(.*)$", line.rstrip())
            if m:
                seen[int(m.group(1))].append((cpus(m.group(3)), cpus(m.group(4)), [cpus(q) for q in m.group(5).split()]))
    fit = qok = 0
    for r, a in arms.items():
        want = hs["conf"] if a == "confined" else hs["all"]
        obs = seen.get(r, [])
        fit += len(obs) == 2 and all(u == want and p1 == want for u, p1, _ in obs)
        qok += len(obs) == 2 and all(qs and all(q == hs["qemu"] for q in qs) for _, _, qs in obs)
    return fit, qok, len(arms)


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    hs = host(out)
    period = 1e6 / hs["hz"] if hs["hz"] else float("nan")
    arms = cr.arms_of(out)
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")), key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    rows, allv = [], {a: [] for a in cr.ARMS}
    grid_on = grid_all = aligned = 0
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        a = arms.get(r)
        if a not in cr.ARMS:
            continue
        got, lat = tr.exchanges(out, r, n, warm)
        if got is None:
            print("  round %d not aligned" % r)
            continue
        aligned += 1
        allv[a] += lat
        rows += got
        tk = os.path.join(out, "tk-t2ms_r%d.log" % r)
        if os.path.exists(tk):
            for t, _, k, fn in tkt.read(tk):
                if k == "H" and fn == "tick_sched_timer":
                    grid_all += 1
                    grid_on += (t % period) < GRID_OK
    k = len(files)

    def in_bin(t0):
        return t0 % period >= period - BIN_W

    inb = [v for t0, v, _ in rows if in_bin(t0)]
    outb = [v for t0, v, _ in rows if not in_bin(t0)]
    tail = [t0 for t0, _, tl in rows if tl]
    tin = sum(1 for t0 in tail if in_bin(t0))
    share = len(inb) / len(rows) if rows else float("nan")
    ratio = (tin / len(tail)) / share if tail and share > 0 else float("nan")
    slow = st.median(inb) - st.median(outb) if inb and outb else float("nan")
    p50 = {a: st.median(allv[a]) if allv[a] else float("nan") for a in cr.ARMS}
    p99 = {a: br.pct(allv[a], 99) if allv[a] else float("nan") for a in cr.ARMS}
    p999 = {a: br.pct(allv[a], 99.9) if allv[a] else float("nan") for a in cr.ARMS}
    fit, qok, nr = states(out, arms, hs)
    nl = br.logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": nr > 0 and fit == nr,
          "M3": nr > 0 and qok == nr,
          "M4": nl == 0,
          "M5": grid_all > 0 and grid_on / grid_all >= 0.9,
          "M6": tin >= MIN_TAIL}
    print("  host: HZ %s (tick period %.0f us), all cores %s, confined to %s, QEMU on %s"
          % (hs["hz"], period, sorted(hs["all"]), sorted(hs["conf"]), sorted(hs["qemu"])))
    print("  rounds %d, aligned %d, arms %s" % (k, aligned, dict(collections.Counter(arms.values()))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds whose udevd and PID 1 fit their arm, before and after: %d/%d (want all) -> %s"
          % (fit, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 rounds whose QEMU threads stayed on their cores: %d/%d (want all) -> %s" % (qok, nr, "ok" if ok["M3"] else "FAILED"))
    print("  M4 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M4"] else "FAILED"))
    print("  M5 tick_sched_timer expiries within [0, %.0f) us of the grid: %d/%d (want >= 90%%) -> %s"
          % (GRID_OK, grid_on, grid_all, "ok" if ok["M5"] else "FAILED"))
    print("  M6 tick-bin tail exchanges %d (want >= %d) -> %s" % (tin, MIN_TAIL, "ok" if ok["M6"] else "FAILED"))
    print("  tick bin: %.2f%% of out-class exchanges, %d of their %d tail; median %.1f in the bin, %.1f outside"
          % (100 * share, tin, len(tail), st.median(inb) if inb else float("nan"), st.median(outb) if outb else float("nan")))
    print("  %-9s %8s %8s %8s" % ("arm", "p50", "p99", "p99.9"))
    for a in cr.ARMS:
        print("  %-9s %8.1f %8.1f %8.1f" % (a, p50[a], p99[a], p999[a]))
    scored = k == SCORED_K
    base = ["M1", "M2", "M3", "M4"]

    def verdict(v, needs):
        if not scored:
            return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
        failed = [m for m in needs if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    print("  P1  the tick bin is over-represented in the tail: RATIO %.2f -> %s"
          % (ratio, verdict("HELD" if ratio >= RATIO else "REFUTED", base + ["M5", "M6"])))
    print("  P2  tick-bin exchanges are slower: SLOWDOWN %+.1f us -> %s"
          % (slow, verdict("HELD" if slow >= SLOW else "REFUTED", base + ["M5", "M6"])))
    print("  P3  confinement changes the tail little: p99 confined %.1f, open %.1f us -> %s"
          % (p99["confined"], p99["open"],
             verdict("HELD" if abs(p99["confined"] - p99["open"]) <= TAIL_SAME * p99["open"] else "REFUTED", base)))
    print("  P4  the typical exchange does not change: p50 confined %.1f, open %.1f us -> %s"
          % (p50["confined"], p50["open"], verdict("HELD" if abs(p50["confined"] - p50["open"]) <= SAME else "REFUTED", base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
