#!/usr/bin/env python3
"""boots_report.py -- run-boots.sh's test: how much do A6 figures move from one boot of the
board to the next? (Phase 3b / A6, 2026-09-25), by the rule its header fixed before any run.

  boots_report.py --one OUT N WARMUP             one boot's figures, unscored
  boots_report.py B1 B2 B3 B4 B5 B6 N WARMUP     the six boots' directories: the verdicts

Per round: p50 and p99 over its timed exchanges. Per boot: BOOT P50 and BOOT P99, the
median of its rounds' figures, and the tick-bin SLOWDOWN (tick_report's bin, out-class
exchanges). Over the boots: the variance components of the round figures, one-way random
effects (WITHIN, BETWEEN, ICC). Scored only with six boots b1..b6 at k = 8 each; a
prediction resting on a failed check prints VOID.
"""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bursts_report as br  # noqa: E402
import tick_report as tr  # noqa: E402

TAGS = ("b1", "b2", "b3", "b4", "b5", "b6")
SCORED_K, SETTLE_S = 8, 600
RANGE_P50, ICC_P50, RANGE_P99, RANGE_SLOW, MIN_TAIL = 5.0, 0.5, 10.0, 4.0, 10


def boot(out, n, warm):
    stamp = json.load(open(os.path.join(out, "stamp.json")))
    info = stamp.get("boot", "")
    up = re.search(r"uptime at preflight (\d+) s", info)
    tok = re.search(r"cmdline isolcpus/irqaffinity: (\d+) token", info)
    b = {"dir": out, "tag": stamp.get("boot_tag"), "uptime": int(up.group(1)) if up else -1,
         "tokens": int(tok.group(1)) if tok else -1, "p50": [], "p99": [], "rows": [], "rounds": 0, "aligned": 0}
    rounds = sorted(int(re.search(r"_r(\d+)\.", f).group(1)) for f in glob.glob(os.path.join(out, "lat-t2ms_r*.json")))
    b["rounds"] = len(rounds)
    for r in rounds:
        rows, lat = tr.exchanges(out, r, n, warm)
        if rows is None:
            continue
        b["aligned"] += 1
        b["p50"].append(st.median(lat))
        b["p99"].append(br.pct(lat, 99))
        b["rows"] += rows
    qok, seen = 0, {}
    p = os.path.join(out, "confine.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (before|after) .* qemu=(.*)$", line.rstrip())
            if m:
                seen.setdefault(int(m.group(1)), []).append(m.group(3).strip())
    b["qemu_ok"] = sum(1 for r in rounds if len(seen.get(r, [])) == 2 and all(q == "0-2" for q in seen[r]))
    b["logins"] = br.logins(out)
    inb = [v for t0, v, _ in b["rows"] if tr.in_bin(t0)]
    outb = [v for t0, v, _ in b["rows"] if not tr.in_bin(t0)]
    b["slow"] = st.median(inb) - st.median(outb) if inb and outb else float("nan")
    b["bin_tail"] = sum(1 for t0, _, tl in b["rows"] if tl and tr.in_bin(t0))
    b["boot_p50"] = st.median(b["p50"]) if b["p50"] else float("nan")
    b["boot_p99"] = st.median(b["p99"]) if b["p99"] else float("nan")
    return b


def components(groups):
    """(WITHIN, BETWEEN, ICC) of a one-way random-effects model over equal-sized groups."""
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return float("nan"), float("nan"), float("nan")
    k = min(len(g) for g in groups)
    groups = [g[:k] for g in groups]
    msw = sum(st.variance(g) for g in groups) / len(groups)
    msb = k * st.variance([st.mean(g) for g in groups])
    between = max(0.0, (msb - msw) / k)
    icc = between / (between + msw) if between + msw > 0 else float("nan")
    return msw, between, icc


def show(b):
    print("  %-3s rounds %d aligned %d  uptime %d s  BOOT P50 %.1f  BOOT P99 %.1f  SLOWDOWN %+.1f  tick-bin tail %d"
          "  QEMU on 0-2 %d/%d  logins %s"
          % (b["tag"], b["rounds"], b["aligned"], b["uptime"], b["boot_p50"], b["boot_p99"], b["slow"], b["bin_tail"],
             b["qemu_ok"], b["rounds"], b["logins"]))
    print("      round p50: %s" % " ".join("%.1f" % x for x in b["p50"]))


def verdict(v, scored, ok, needs):
    if not scored:
        return "not scored (the prediction is for six boots b1..b6 at k=%d each)" % SCORED_K
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    if argv and argv[0] == "--one":
        show(boot(argv[1], int(argv[2]), int(argv[3])))
        return 0
    if len(argv) != 8:
        print("usage: boots_report.py --one OUT N WARMUP | B1 .. B6 N WARMUP", file=sys.stderr)
        return 2
    n, warm = int(argv[6]), int(argv[7])
    boots = [boot(d, n, warm) for d in argv[:6]]
    for b in boots:
        show(b)
    w50, b50, icc50 = components([b["p50"] for b in boots])
    w99, b99, icc99 = components([b["p99"] for b in boots])
    bp50 = [b["boot_p50"] for b in boots]
    bp99 = [b["boot_p99"] for b in boots]
    slows = [b["slow"] for b in boots]
    ok = {"M1": all(b["rounds"] > 0 and b["aligned"] / b["rounds"] >= 0.9 for b in boots),
          "M2": [b["tag"] for b in boots] == list(TAGS) and all(b["uptime"] >= SETTLE_S and b["tokens"] == 0 for b in boots),
          "M3": all(b["logins"] == 0 for b in boots),
          "M4": all(b["qemu_ok"] == b["rounds"] for b in boots),
          "M5": all(b["bin_tail"] >= MIN_TAIL for b in boots)}
    scored = [b["tag"] for b in boots] == list(TAGS) and all(b["rounds"] == SCORED_K for b in boots)
    print("  M1 every boot's rounds align (>= 90%%): %s -> %s"
          % (", ".join("%s %d/%d" % (b["tag"], b["aligned"], b["rounds"]) for b in boots), "ok" if ok["M1"] else "FAILED"))
    print("  M2 six boots b1..b6, settled (>= %d s), on the shipped command line: %s -> %s"
          % (SETTLE_S, ", ".join("%s %d s %d tok" % (b["tag"], b["uptime"], b["tokens"]) for b in boots),
             "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins during the rounds: %s -> %s" % ([b["logins"] for b in boots], "ok" if ok["M3"] else "FAILED"))
    print("  M4 rounds with QEMU's threads on 0-2: %s -> %s"
          % (", ".join("%s %d/%d" % (b["tag"], b["qemu_ok"], b["rounds"]) for b in boots), "ok" if ok["M4"] else "FAILED"))
    print("  M5 tick-bin tail exchanges per boot: %s (want >= %d each) -> %s"
          % ([b["bin_tail"] for b in boots], MIN_TAIL, "ok" if ok["M5"] else "FAILED"))
    print("  variance components, round p50: WITHIN %.2f, BETWEEN %.2f us^2, ICC %.2f; round p99: WITHIN %.2f, BETWEEN %.2f,"
          " ICC %.2f" % (w50, b50, icc50, w99, b99, icc99))
    base = ["M1", "M2", "M3", "M4"]
    r50, r99, rs = max(bp50) - min(bp50), max(bp99) - min(bp99), max(slows) - min(slows)
    print("  P1  boots differ at p50: BOOT P50 %.1f..%.1f, range %.1f us -> %s"
          % (min(bp50), max(bp50), r50, verdict("HELD" if r50 >= RANGE_P50 else "REFUTED", scored, ok, base)))
    print("  P2  the boot outweighs the round at p50: ICC %.2f -> %s"
          % (icc50, verdict("HELD" if icc50 == icc50 and icc50 >= ICC_P50 else "REFUTED", scored, ok, base)))
    print("  P3  boots differ in the tail: BOOT P99 %.1f..%.1f, range %.1f us -> %s"
          % (min(bp99), max(bp99), r99, verdict("HELD" if r99 >= RANGE_P99 else "REFUTED", scored, ok, base)))
    print("  P4  the tick's cost does not move with the boot: SLOWDOWN %+.1f..%+.1f, range %.1f us -> %s"
          % (min(slows), max(slows), rs, verdict("HELD" if rs <= RANGE_SLOW else "REFUTED", scored, ok, base + ["M5"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
