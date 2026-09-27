#!/usr/bin/env python3
"""free_report.py OUT -- run-free.sh's last-byte test, by the rule the harness's header fixed before any
run (Phase 3b / A6, 2026-09-27).

Per arm (U1d64 U1d96 U1s64 U1s96) and round: the probe's p50, and the endpoint's printed reads and
timing for the connection that served the arm. Each boot's console (console-U1_r<round>.log) holds
one connection per arm; per port (d :7120, s :7122) its connections of n + warm-up frames are matched
to that port's arms in the order the round ran them (order.log). Differences are paired within the
round; the interval is the distribution-free one of widest coverage >= 95%.
"""
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("U1d64", "U1d96", "U1s64", "U1s96")
PORT = {"d": 7120, "s": 7122}
READS = {"U1d64": 1, "U1d96": 2, "U1s64": 2, "U1s96": 3}
TOL = 0.02
RL = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")
TL = re.compile(r"sweep: timing :(\d+) (\w+) frames=(\d+) r2_n=(\d+) r2_p50_ns=(-?\d+) w_p50_ns=(-?\d+) svc_p50_ns=(-?\d+)")


def load(out, frames):
    arm = {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-(U1[ds](?:64|96))_r(\d+)\.json$", f)
        if m:
            s = json.load(open(f))["summary"]
            arm[(m.group(1), int(m.group(2)))] = {"rtt": s["p50_ms"] * 1000.0, "n": s.get("n"), "bad": s.get("bad"),
                                                  "rej": s.get("rejected_by_monitor"), "fb": s.get("frame_bytes")}
    order = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) order: (.*)$", line.strip())
            if m:
                order[int(m.group(1))] = m.group(2).split()
    problems = []
    for r, arms in order.items():
        con = os.path.join(out, "console-U1_r%d.log" % r)
        text = open(con, encoding="utf-8", errors="replace").read() if os.path.exists(con) else ""
        for mode, port in PORT.items():
            want = [a for a in arms if a[2] == mode]
            rd = [x for x in RL.findall(text) if int(x[0]) == port and int(x[2]) == frames]
            tm = [x for x in TL.findall(text) if int(x[0]) == port and int(x[2]) == frames]
            if len(rd) != len(want) or len(tm) != len(want):
                problems.append("round %d :%d: %d/%d connections for %d arms" % (r, port, len(rd), len(tm), len(want)))
                continue
            for a, x, t in zip(want, rd, tm):
                if (a, r) in arm:
                    arm[(a, r)]["rpf"] = int(x[3]) / int(x[2])
                    arm[(a, r)]["r2_n"] = int(t[3])
                    arm[(a, r)]["r2"], arm[(a, r)]["w"], arm[(a, r)]["svc"] = (int(t[i]) / 1000.0 for i in (4, 5, 6))
    return arm, problems


def main(argv):
    out = argv[0]
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    frames = (n_want or 1000) + warm
    arm, problems = load(out, frames)
    rounds = sorted({r for _, r in arm})
    keys = [(a, r) for a in ARMS for r in rounds]
    ok = {"M1": bool(rounds) and all(k in arm and arm[k]["bad"] == 0 and arm[k]["rej"] == 0 and arm[k]["fb"] == int(k[0][3:])
                                      and (n_want is None or arm[k]["n"] == n_want) for k in keys),
          "M2": bool(rounds) and not problems and all(k in arm and "rpf" in arm[k] and abs(arm[k]["rpf"] - READS[k[0]]) <= TOL
                                                      and arm[k]["r2_n"] == (0 if k[0] == "U1d64" else frames) for k in keys)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected, none bad, its own size -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    for msg in problems[:6]:
        print("     %s" % msg)
    print("  M2 every arm's connection printed reads and timing as designed -> %s" % ("ok" if ok["M2"] else "FAILED"))
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
        print("    %-30s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def d(a, b, key):
        return [arm[(a, r)][key] - arm[(b, r)][key] for r in rounds
                if (a, r) in arm and (b, r) in arm and key in arm[(a, r)] and key in arm[(b, r)]]

    print("  differences, paired within round (us): median [interval], rounds > 0")
    p1 = show("r2 U1s96 - U1s64", d("U1s96", "U1s64", "r2"))
    p3 = show("r2 U1d96 - U1s64", d("U1d96", "U1s64", "r2"))
    show("rtt U1s96 - U1s64 (unscored)", d("U1s96", "U1s64", "rtt"))
    show("rtt U1d96 - U1d64 (unscored)", d("U1d96", "U1d64", "rtt"))
    show("rtt U1s64 - U1d64 (unscored)", d("U1s64", "U1d64", "rtt"))
    r2s96 = med("U1s96", "r2")
    print("  P1  a second read that leaves bytes behind is cheaper: r2 U1s96 - U1s64 %+.2f us (want <= -3) -> %s"
          % (p1, verdict("HELD" if p1 <= -3 else "REFUTED")))
    print("  P2  it is as cheap as a loopback read: r2 U1s96 %.2f us (want <= 8.5) -> %s"
          % (r2s96, verdict("HELD" if r2s96 <= 8.5 else "REFUTED")))
    print("  P3  two last-byte reads cost the same: r2 U1d96 - U1s64 %+.2f us (want within 2 of 0) -> %s"
          % (p3, verdict("HELD" if abs(p3) <= 2 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
