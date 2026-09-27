#!/usr/bin/env python3
"""offload_report.py OUT -- run-offload.sh's receive-offload test, by the rule the harness's header fixed
before any run (Phase 3b / A6, 2026-09-27).

Per arm (<config><mode>64, config N1 or F1, mode d or s) and round: the probe's p50, and from that
boot's console the endpoint's reads and timing lines for the arm's port -- the arithmetic of
pin_report.py. M3 reads each boot's console for vtnet0's printed options (the last `options=<...>`
line that is not nd6's) and offloads.log for tap-qnx's TSO at that boot.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pin_report as pr  # noqa: E402
from sweep_report import interval  # noqa: E402

CFGS = ("N1", "F1")
ARMS = tuple(c + m + "64" for c in CFGS for m in "ds")
OPTS = re.compile(r"^\s*options=[0-9a-fA-F]+<([^>]*)>\s*$")
TAP = re.compile(r"^(N1|F1)_r(\d+) tap-qnx .*tcp-segmentation-offload: (on|off)")


def vtnet_caps(out, cfg, r):
    p = os.path.join(out, "console-%s_r%d.log" % (cfg, r))
    if not os.path.exists(p):
        return None
    caps = None
    for line in open(p, encoding="utf-8", errors="replace").read().replace("\0", "").splitlines():
        if "nd6" in line:
            continue
        m = OPTS.match(line.replace("\r", ""))
        if m:
            caps = set(m.group(1).split(","))
    return caps


def main(argv):
    out = argv[0]
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    frames = (n_want or 1000) + warm
    arm, bench, bench_ok = pr.load(out, frames, CFGS)
    rounds = sorted({r for _, r in arm})
    keys = [(a, r) for a in ARMS for r in rounds]
    tap = {}
    p = os.path.join(out, "offloads.log")
    if os.path.exists(p):
        for line in open(p):
            m = TAP.match(line.strip())
            if m:
                tap[(m.group(1), int(m.group(2)))] = m.group(3)
    m3 = bool(rounds)
    for c in CFGS:
        for r in rounds:
            caps = vtnet_caps(out, c, r)
            want_on = c == "N1"
            if caps is None or (("RXCSUM" in caps and "LRO" in caps) if want_on else ("RXCSUM" in caps or "LRO" in caps)) != want_on \
                    or tap.get((c, r)) != ("on" if want_on else "off"):
                m3 = False
    ok = {"M1": bool(rounds) and all(k in arm and arm[k]["bad"] == 0 and arm[k]["rej"] == 0 and arm[k]["fb"] == 64
                                      and (n_want is None or arm[k]["n"] == n_want) for k in keys),
          "M2": bool(rounds) and all(k in arm and "rpf" in arm[k] and "r2_n" in arm[k]
                                      and abs(arm[k]["rpf"] - pr.MODES[k[0][2]][1]) <= pr.TOL
                                      and arm[k]["r2_n"] == (frames if k[0][2] == "s" else 0) for k in keys),
          "M3": m3,
          "M4": bool(rounds) and all(bench_ok.get((c, r)) for c in CFGS for r in rounds)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected, none bad, 64-byte frames -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    print("  M2 every arm's connection printed reads and timing as designed -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 the offloads were each configuration's, every boot (vtnet0's options and tap-qnx's TSO) -> %s"
          % ("ok" if ok["M3"] else "FAILED"))
    print("  M4 every boot's benchmark completed with no fail -> %s" % ("ok" if ok["M4"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(a, key):
        vals = [arm[(a, r)][key] for r in rounds if (a, r) in arm and key in arm[(a, r)] and arm[(a, r)][key] >= 0]
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds (us): rtt; r2 w svc")
    for a in ARMS:
        print("    %-6s rtt %7.2f   r2 %6.2f  w %6.2f  svc %6.2f" % (a, med(a, "rtt"), med(a, "r2"), med(a, "w"), med(a, "svc")))

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-44s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def d(a, b, key):
        return [arm[(a, r)][key] - arm[(b, r)][key] for r in rounds
                if (a, r) in arm and (b, r) in arm and key in arm[(a, r)] and key in arm[(b, r)]]

    print("  differences, paired within round (us): median [interval], rounds > 0")
    p1 = show("r2 F1s64 - N1s64", d("F1s64", "N1s64", "r2"))
    step = {c: [arm[(c + "s64", r)]["rtt"] - arm[(c + "d64", r)]["rtt"] for r in rounds] for c in CFGS}
    p3 = show("(F1s64 - F1d64) - (N1s64 - N1d64), rtt", [f - n for f, n in zip(step["F1"], step["N1"])])
    show("rtt F1d64 - N1d64 (unscored)", d("F1d64", "N1d64", "rtt"))
    show("w F1d64 - N1d64 (unscored)", d("F1d64", "N1d64", "w"))
    r2f = med("F1s64", "r2")
    print("  benchmark, spaced, median over rounds of each boot's p50 (us, unscored)")
    for o in ("kcall", "zero", "msg", "sock"):
        print("    %-5s %s" % (o, ", ".join("%s=%.2f" % (c, st.median(bench[(c, o, "spaced", r)] for r in rounds
                                                                              if (c, o, "spaced", r) in bench))
                                           for c in CFGS if any((c, o, "spaced", r) in bench for r in rounds))))
    print("  P1  receive offloads off shorten the second read: r2 F1s64 - N1s64 %+.2f us (want <= -3) -> %s"
          % (p1, verdict("HELD" if p1 <= -3 else "REFUTED")))
    print("  P2  without them the read is as cheap as a loopback read: r2 F1s64 %.2f us (want <= 8.5) -> %s"
          % (r2f, verdict("HELD" if r2f <= 8.5 else "REFUTED")))
    print("  P3  the round trip's step follows: %+.2f us (want <= -3) -> %s" % (p3, verdict("HELD" if p3 <= -3 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
