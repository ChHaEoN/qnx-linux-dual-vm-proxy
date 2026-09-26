#!/usr/bin/env python3
"""ipcbench_report.py OUT -- run-ipcbench.sh's test: what one call costs inside the guest, by kind,
by the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-26).

Each round's bench-G_rK.txt (the guest's run) and bench-N_rK.txt (the native run) hold one line per
op and regime: `op NAME regime R n N p10_ns X p50_ns X p90_ns X mean_ns X`. Per side, op, regime
and round, the run's p50; per side, op and regime, the median over rounds with the distribution-free
interval of widest coverage >= 95%. Values are raw (each includes one clock read's cost).
"""
import glob
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

OPS = {"G": ("clock", "kcall", "zero", "msg", "msgx", "sock"), "N": ("clock", "kcall", "zero", "sock")}
REGIMES = ("tight", "spaced")
N_WANT = 500
LINE = re.compile(r"^op (\w+) regime (\w+) n (\d+) p10_ns (-?\d+) p50_ns (-?\d+) p90_ns (-?\d+) mean_ns (-?\d+)$")


def load(out):
    """{(side, op, regime, round): {"n", "p10", "p50", "p90", "mean"} in us}, and rounds with a fail line."""
    got, failed = {}, set()
    for f in glob.glob(os.path.join(out, "bench-*_r*.txt")):
        m = re.search(r"bench-([GN])_r(\d+)\.txt$", f)
        if not m:
            continue
        side, r = m.group(1), int(m.group(2))
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line.startswith("fail "):
                failed.add((side, r))
            x = LINE.match(line)
            if x:
                got[(side, x.group(1), x.group(2), r)] = {"n": int(x.group(3)), "p10": int(x.group(4)) / 1000.0,
                                                          "p50": int(x.group(5)) / 1000.0, "p90": int(x.group(6)) / 1000.0,
                                                          "mean": int(x.group(7)) / 1000.0}
    return got, failed


def main(argv):
    out = argv[0]
    got, failed = load(out)
    rounds = sorted({k[3] for k in got})
    want = [(s, o, g, r) for s in OPS for o in OPS[s] for g in REGIMES for r in rounds]
    ok = {"M1": bool(rounds) and not failed and all(k in got and got[k]["n"] == N_WANT for k in want)}
    print("  rounds %d" % len(rounds))
    print("  M1 every round has both sides' results for every op and regime, n = %d, no fail -> %s"
          % (N_WANT, "ok" if ok["M1"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        return "VOID (M1 failed)" if not ok["M1"] else v

    med = {}
    print("  per side, op and regime: the median over rounds of each run's p50 (us) [interval]; its p90 likewise")
    for s in OPS:
        for o in OPS[s]:
            for g in REGIMES:
                vals = [got[(s, o, g, r)]["p50"] for r in rounds if (s, o, g, r) in got]
                p90 = [got[(s, o, g, r)]["p90"] for r in rounds if (s, o, g, r) in got]
                if not vals:
                    continue
                lo, hi, cov = interval(vals)
                med[(s, o, g)] = st.median(vals)
                print("    %s %-5s %-6s p50 %7.2f [%.2f, %.2f] (%.1f%%)   p90 %7.2f"
                      % ("guest " if s == "G" else "native", o, g, med[(s, o, g)], lo, hi, 100 * cov, st.median(p90)))

    def m(s, o, g="spaced"):
        return med.get((s, o, g), float("nan"))

    print("  P1  the guest's message pass: msg spaced %.2f us (want <= 5) -> %s"
          % (m("G", "msg"), verdict("HELD" if m("G", "msg") <= 5 else "REFUTED")))
    print("  P2  a read served by procnto: zero spaced %.2f us (want <= 5) -> %s"
          % (m("G", "zero"), verdict("HELD" if m("G", "zero") <= 5 else "REFUTED")))
    print("  P3  an io-sock read: sock spaced %.2f us (want >= 10) -> %s"
          % (m("G", "sock"), verdict("HELD" if m("G", "sock") >= 10 else "REFUTED")))
    print("  P4  a kernel call: kcall spaced %.2f us (want <= 2) -> %s"
          % (m("G", "kcall"), verdict("HELD" if m("G", "kcall") <= 2 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
