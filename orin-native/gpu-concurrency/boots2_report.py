#!/usr/bin/env python3
"""boots2_report.py -- run-boots2.sh's test: does the boot shift every arm of a run equally?
(Phase 3b / A6, 2026-09-25), by the rule its header fixed before any run.

  boots2_report.py --one OUT N WARMUP             one boot's figures, unscored
  boots2_report.py B1 B2 B3 B4 B5 B6 N WARMUP     the six boots' directories: the verdicts

Per round: p50 of each arm (t2ms, t200us) and DIFF = p50(t2ms) - p50(t200us). Over the
boots: the one-way random-effects variance components (boots_report.components) of the
t2ms p50, the t200us p50 and DIFF; SD_between is the square root of BETWEEN. Per boot: the
tick-bin SLOWDOWN of t2ms, and its count of out-class tick-bin exchanges (M5). Scored only
with six boots b1..b6 at k = 8 each; a prediction resting on a failed check prints VOID.
"""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import boots_report as bo  # noqa: E402
import tick_report as tr  # noqa: E402

ICC_T2, SD_RATIO, ICC_T200, RANGE_SLOW, MIN_BIN = 0.5, 0.5, 0.5, 4.0, 200


def boot(out, n, warm):
    b = bo.boot(out, n, warm)                       # t2ms: rounds, p50, rows, SLOWDOWN, checks
    fast, diff = {}, []
    for f in glob.glob(os.path.join(out, "lat-t200us_r*.json")):
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        lat = [v * 1000.0 for v in json.load(open(f))["samples_in_order"]]
        if len(lat) == n:
            fast[r] = st.median(lat)
    slow = {}
    for f in glob.glob(os.path.join(out, "lat-t2ms_r*.json")):
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        lat = [v * 1000.0 for v in json.load(open(f))["samples_in_order"]]
        if len(lat) == n:
            slow[r] = st.median(lat)
    for r in sorted(set(fast) & set(slow)):
        diff.append(slow[r] - fast[r])
    b["fast"] = [fast[r] for r in sorted(fast)]
    b["fast_rounds"] = len(fast)
    b["diff"] = diff
    b["bin_n"] = sum(1 for t0, _, _ in b["rows"] if tr.in_bin(t0))
    return b


def show(b):
    print("  %-3s rounds %d aligned %d  uptime %d s  p50 t2ms %.1f  t200us %.1f  DIFF %.1f  SLOWDOWN %+.1f"
          "  tick-bin exchanges %d  QEMU on 0-2 %d/%d  logins %s"
          % (b["tag"], b["rounds"], b["aligned"], b["uptime"], b["boot_p50"],
             st.median(b["fast"]) if b["fast"] else float("nan"), st.median(b["diff"]) if b["diff"] else float("nan"),
             b["slow"], b["bin_n"], b["qemu_ok"], b["rounds"], b["logins"]))


def verdict(v, scored, ok, needs):
    if not scored:
        return "not scored (the prediction is for six boots b1..b6 at k=%d each)" % bo.SCORED_K
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    if argv and argv[0] == "--one":
        show(boot(argv[1], int(argv[2]), int(argv[3])))
        return 0
    if len(argv) != 8:
        print("usage: boots2_report.py --one OUT N WARMUP | B1 .. B6 N WARMUP", file=sys.stderr)
        return 2
    n, warm = int(argv[6]), int(argv[7])
    boots = [boot(d, n, warm) for d in argv[:6]]
    for b in boots:
        show(b)
    w2, b2, icc2 = bo.components([b["p50"] for b in boots])
    wf, bf, iccf = bo.components([b["fast"] for b in boots])
    wd, bd, iccd = bo.components([b["diff"] for b in boots])
    sd2, sdd = b2 ** 0.5 if b2 == b2 else float("nan"), bd ** 0.5 if bd == bd else float("nan")
    slows = [b["slow"] for b in boots]
    ok = {"M1": all(b["rounds"] > 0 and b["aligned"] / b["rounds"] >= 0.9 and b["fast_rounds"] == b["rounds"] for b in boots),
          "M2": [b["tag"] for b in boots] == list(bo.TAGS) and all(b["uptime"] >= bo.SETTLE_S and b["tokens"] == 0 for b in boots),
          "M3": all(b["logins"] == 0 for b in boots),
          "M4": all(b["qemu_ok"] == b["rounds"] for b in boots),
          "M5": all(b["bin_n"] >= MIN_BIN for b in boots)}
    scored = [b["tag"] for b in boots] == list(bo.TAGS) and all(b["rounds"] == bo.SCORED_K for b in boots)
    print("  M1 t2ms rounds aligned and t200us rounds written: %s -> %s"
          % (", ".join("%s %d/%d+%d" % (b["tag"], b["aligned"], b["rounds"], b["fast_rounds"]) for b in boots),
             "ok" if ok["M1"] else "FAILED"))
    print("  M2 six boots b1..b6, settled (>= %d s), on the shipped command line: %s -> %s"
          % (bo.SETTLE_S, ", ".join("%s %d s" % (b["tag"], b["uptime"]) for b in boots), "ok" if ok["M2"] else "FAILED"))
    print("  M3 SSH logins during the rounds: %s -> %s" % ([b["logins"] for b in boots], "ok" if ok["M3"] else "FAILED"))
    print("  M4 rounds with QEMU's threads on 0-2: %s -> %s"
          % (", ".join("%s %d/%d" % (b["tag"], b["qemu_ok"], b["rounds"]) for b in boots), "ok" if ok["M4"] else "FAILED"))
    print("  M5 out-class t2ms exchanges in the tick bin per boot: %s (want >= %d each) -> %s"
          % ([b["bin_n"] for b in boots], MIN_BIN, "ok" if ok["M5"] else "FAILED"))
    print("  components (us^2): t2ms p50 WITHIN %.2f BETWEEN %.2f ICC %.2f | t200us p50 WITHIN %.2f BETWEEN %.2f ICC %.2f"
          " | DIFF WITHIN %.2f BETWEEN %.2f ICC %.2f" % (w2, b2, icc2, wf, bf, iccf, wd, bd, iccd))
    base = ["M1", "M2", "M3", "M4"]
    print("  P1  the boot sets the 2 ms level again: ICC(p50 t2ms) %.2f -> %s"
          % (icc2, verdict("HELD" if icc2 == icc2 and icc2 >= ICC_T2 else "REFUTED", scored, ok, base)))
    print("  P2  the boot shifts both arms alike: SD_between(DIFF) %.2f, SD_between(p50 t2ms) %.2f us -> %s"
          % (sdd, sd2, verdict("HELD" if sd2 > 0 and sdd <= SD_RATIO * sd2 else "REFUTED", scored, ok, base)))
    print("  P3  the boot sets the 0.2 ms level too: ICC(p50 t200us) %.2f -> %s"
          % (iccf, verdict("HELD" if iccf == iccf and iccf >= ICC_T200 else "REFUTED", scored, ok, base)))
    rs = max(slows) - min(slows)
    print("  P4  the tick's cost does not move with the boot: SLOWDOWN %+.1f..%+.1f, range %.1f us -> %s"
          % (min(slows), max(slows), rs, verdict("HELD" if rs <= RANGE_SLOW else "REFUTED", scored, ok, base + ["M5"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
