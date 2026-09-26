#!/usr/bin/env python3
"""spin_report.py OUT -- run-spin.sh's wait test, by the rule the harness's header fixed before any run
(Phase 3b / A6, 2026-09-27).

Per arm (<config><arm>, config U1 or U2, arm d s0 s5 s20 s50) and round: the probe's p50, and from
that boot's console (console-<config>_r<round>.log) the endpoint's `sweep: reads`, `sweep: timing` and
`sweep: spin` lines for the arm's port and the connection of n + warm-up frames. Differences are
paired within the round; the interval is the distribution-free one of widest coverage >= 95%.
"""
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

CFGS = ("U1", "U2")
ARM = {"d": (7120, 1, 0), "s0": (7122, 2, 0), "s5": (7123, 2, 5), "s20": (7124, 2, 20), "s50": (7125, 2, 50)}
ARMS = tuple(c + a for c in CFGS for a in ARM)
TOL = 0.02
READS = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")
TIMING = re.compile(r"sweep: timing :(\d+) (\w+) frames=(\d+) r2_n=(\d+) r2_p50_ns=(-?\d+) w_p50_ns=(-?\d+) svc_p50_ns=(-?\d+)")
SPIN = re.compile(r"sweep: spin :(\d+) frames=(\d+) spin_us=(\d+) spin_p50_ns=(-?\d+)")


def load(out, frames):
    arm = {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-(U1|U2)(d|s0|s5|s20|s50)_r(\d+)\.json$", f)
        if not m:
            continue
        c, a, r = m.group(1), m.group(2), int(m.group(3))
        s = json.load(open(f))["summary"]
        row = {"rtt": s["p50_ms"] * 1000.0, "n": s.get("n"), "bad": s.get("bad"), "rej": s.get("rejected_by_monitor"),
               "fb": s.get("frame_bytes")}
        con = os.path.join(out, "console-%s_r%d.log" % (c, r))
        text = open(con, encoding="utf-8", errors="replace").read() if os.path.exists(con) else ""
        port = ARM[a][0]
        rd = [x for x in READS.findall(text) if int(x[0]) == port and int(x[2]) == frames]
        tm = [x for x in TIMING.findall(text) if int(x[0]) == port and int(x[2]) == frames]
        sp = [x for x in SPIN.findall(text) if int(x[0]) == port and int(x[1]) == frames]
        if len(rd) == 1:
            row["rpf"] = int(rd[0][3]) / int(rd[0][2])
        if len(tm) == 1:
            row["r2_n"] = int(tm[0][3])
            row["r2"], row["w"], row["svc"] = (int(tm[0][i]) / 1000.0 for i in (4, 5, 6))
        if len(sp) == 1:
            row["spin"] = int(sp[0][3]) / 1000.0
        arm[(c + a, r)] = row
    return arm


def main(argv):
    out = argv[0]
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    frames = (n_want or 1000) + warm
    arm = load(out, frames)
    rounds = sorted({r for _, r in arm})
    keys = [(a, r) for a in ARMS for r in rounds]
    ok = {"M1": bool(rounds) and all(k in arm and arm[k]["bad"] == 0 and arm[k]["rej"] == 0 and arm[k]["fb"] == 64
                                      and (n_want is None or arm[k]["n"] == n_want) for k in keys),
          "M2": bool(rounds) and all(k in arm and "rpf" in arm[k] and "r2_n" in arm[k]
                                      and abs(arm[k]["rpf"] - ARM[k[0][2:]][1]) <= TOL
                                      and arm[k]["r2_n"] == (frames if ARM[k[0][2:]][1] == 2 else 0) for k in keys),
          "M3": bool(rounds) and all(k in arm and "spin" in arm[k]
                                      and ARM[k[0][2:]][2] <= arm[k]["spin"] <= ARM[k[0][2:]][2] + 5
                                      for k in keys if ARM[k[0][2:]][2] > 0)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected, none bad, 64-byte frames -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    print("  M2 every arm's connection printed reads and timing as designed -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 every wait's median within [N, N + 5] us -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(a, key):
        vals = [arm[(a, r)][key] for r in rounds if (a, r) in arm and key in arm[(a, r)] and arm[(a, r)][key] >= 0]
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds (us): rtt; r2 w svc; the wait")
    for a in ARMS:
        print("    %-6s rtt %7.2f   r2 %6.2f  w %6.2f  svc %6.2f   wait %6.2f"
              % (a, med(a, "rtt"), med(a, "r2"), med(a, "w"), med(a, "svc"), med(a, "spin")))

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-40s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def d(a, b, key):
        return [arm[(a, r)][key] - arm[(b, r)][key] for r in rounds
                if (a, r) in arm and (b, r) in arm and key in arm[(a, r)] and key in arm[(b, r)]]

    print("  differences, paired within round (us): median [interval], rounds > 0")
    got = {}
    for c in CFGS:
        for a in ("s5", "s20", "s50"):
            got[(c, a)] = show("r2 %s%s - %ss0" % (c, a, c), d(c + a, c + "s0", "r2"))
        for a in ("s5", "s20", "s50"):
            show("rtt %s%s - %ss0 - wait (unscored)" % (c, a, c),
                 [x - arm[(c + a, r)]["spin"] for x, r in zip(d(c + a, c + "s0", "rtt"), rounds)
                  if "spin" in arm.get((c + a, r), {})])
        show("rtt %ss0 - %sd (unscored)" % (c, c), d(c + "s0", c + "d", "rtt"))
    r2u1 = med("U1s50", "r2")
    print("  P1  on one vCPU a 50 us wait shortens the second read: %+.2f us (want <= -4) -> %s"
          % (got[("U1", "s50")], verdict("HELD" if got[("U1", "s50")] <= -4 else "REFUTED")))
    print("  P2  on one vCPU, after the wait, the read is cheap: r2 U1s50 %.2f us (want <= 8) -> %s"
          % (r2u1, verdict("HELD" if r2u1 <= 8 else "REFUTED")))
    print("  P3  on two vCPUs a 50 us wait shortens it too: %+.2f us (want <= -4) -> %s"
          % (got[("U2", "s50")], verdict("HELD" if got[("U2", "s50")] <= -4 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
