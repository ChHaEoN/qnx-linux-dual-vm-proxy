#!/usr/bin/env python3
"""pin_report.py OUT -- run-pin.sh's placement test, by the rule the harness's header fixed before any
run (Phase 3b / A6, 2026-09-27).

Per arm (<config><mode><size>, config U2 P2 U1, mode d or s) and round: the probe's p50, and from that
boot's console (console-<config>_r<round>.log) the endpoint's `sweep: reads` and `sweep: timing` lines
for the arm's port (d :7120, s :7122) and the connection of n + warm-up frames -- one per port per
boot. Differences are paired within the round; the interval is the distribution-free one of widest
coverage >= 95%. Unscored: each boot's benchmark (bench-<config>_r<round>.txt) and the vCPU threads'
run time per exchange from KVM's snapshots (kvm-<arm>_r<round>.json).
"""
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

CFGS = ("U2", "P2", "U1")
MODES = {"d": (7120, 1), "s": (7122, 2)}
ARMS = tuple(c + m + "64" for c in CFGS for m in "ds")
TOL = 0.02
READS = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")
TIMING = re.compile(r"sweep: timing :(\d+) (\w+) frames=(\d+) r2_n=(\d+) r2_p50_ns=(-?\d+) w_p50_ns=(-?\d+) svc_p50_ns=(-?\d+)")
BENCH = re.compile(r"^op (\w+) regime (\w+) n (\d+) p10_ns (-?\d+) p50_ns (-?\d+) p90_ns (-?\d+) mean_ns (-?\d+)$")


def load(out, frames):
    arm = {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-(U2|P2|U1)([ds])64_r(\d+)\.json$", f)
        if not m:
            continue
        c, mode, r = m.group(1), m.group(2), int(m.group(3))
        s = json.load(open(f))["summary"]
        row = {"rtt": s["p50_ms"] * 1000.0, "n": s.get("n"), "bad": s.get("bad"), "rej": s.get("rejected_by_monitor"),
               "fb": s.get("frame_bytes")}
        con = os.path.join(out, "console-%s_r%d.log" % (c, r))
        text = open(con, encoding="utf-8", errors="replace").read() if os.path.exists(con) else ""
        port = MODES[mode][0]
        rd = [x for x in READS.findall(text) if int(x[0]) == port and int(x[2]) == frames]
        tm = [x for x in TIMING.findall(text) if int(x[0]) == port and int(x[2]) == frames]
        if len(rd) == 1:
            row["rpf"] = int(rd[0][3]) / int(rd[0][2])
        if len(tm) == 1:
            row["r2_n"] = int(tm[0][3])
            row["r2"], row["w"], row["svc"] = (int(tm[0][i]) / 1000.0 for i in (4, 5, 6))
        kv = os.path.join(out, "kvm-%s%s64_r%d.json" % (c, mode, r))
        if os.path.exists(kv):
            d = json.load(open(kv))
            for tid, t in d["after"]["threads"].items():
                t0 = d["before"]["threads"].get(tid)
                if t0 and t["comm"].startswith("CPU ") and t["comm"].endswith("/KVM"):
                    row["run_" + t["comm"].split()[1].split("/")[0]] = (t["run_ns"] - t0["run_ns"]) / frames / 1000.0
        arm[(c + mode + "64", r)] = row
    bench, bench_ok = {}, {}
    for f in glob.glob(os.path.join(out, "bench-*_r*.txt")):
        m = re.search(r"bench-(U2|P2|U1)_r(\d+)\.txt$", f)
        if not m:
            continue
        key = (m.group(1), int(m.group(2)))
        lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
        bench_ok[key] = "done" in lines and not any(l.startswith("fail ") for l in lines)
        for l in lines:
            x = BENCH.match(l.strip())
            if x:
                bench[(key[0], x.group(1), x.group(2), key[1])] = int(x.group(5)) / 1000.0
    return arm, bench, bench_ok


def main(argv):
    out = argv[0]
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    frames = (n_want or 1000) + warm
    arm, bench, bench_ok = load(out, frames)
    rounds = sorted({r for _, r in arm})
    keys = [(a, r) for a in ARMS for r in rounds]
    ok = {"M1": bool(rounds) and all(k in arm and arm[k]["bad"] == 0 and arm[k]["rej"] == 0 and arm[k]["fb"] == 64
                                      and (n_want is None or arm[k]["n"] == n_want) for k in keys),
          "M2": bool(rounds) and all(k in arm and "rpf" in arm[k] and "r2_n" in arm[k]
                                      and abs(arm[k]["rpf"] - MODES[k[0][2]][1]) <= TOL
                                      and arm[k]["r2_n"] == (frames if k[0][2] == "s" else 0) for k in keys),
          "M3": bool(rounds) and all(bench_ok.get((c, r)) for c in CFGS for r in rounds)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected, none bad, 64-byte frames -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    print("  M2 every arm's connection printed reads and timing as designed -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 every boot's benchmark completed with no fail -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(a, key):
        vals = [arm[(a, r)][key] for r in rounds if (a, r) in arm and key in arm[(a, r)] and arm[(a, r)][key] >= 0]
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds (us): rtt; r2 w svc; vCPU threads' run time per exchange")
    for a in ARMS:
        print("    %-6s rtt %7.2f   r2 %6.2f  w %6.2f  svc %6.2f   run v0 %7.1f  v1 %7.1f"
              % (a, med(a, "rtt"), med(a, "r2"), med(a, "w"), med(a, "svc"), med(a, "run_0"), med(a, "run_1")))

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
    p1 = show("r2 P2s64 - U2s64", d("P2s64", "U2s64", "r2"))
    p2 = show("r2 P2s64 - U1s64", d("P2s64", "U1s64", "r2"))
    step = {c: [arm[(c + "s64", r)]["rtt"] - arm[(c + "d64", r)]["rtt"] for r in rounds] for c in CFGS}
    p3 = show("(P2s64 - P2d64) - (U2s64 - U2d64), rtt", [p - u for p, u in zip(step["P2"], step["U2"])])
    for c in CFGS:
        show("rtt %ss64 - %sd64 (unscored)" % (c, c), step[c])
    show("rtt P2d64 - U2d64 (unscored)", d("P2d64", "U2d64", "rtt"))
    show("rtt U1d64 - U2d64 (unscored)", d("U1d64", "U2d64", "rtt"))
    r2u1 = med("U1s64", "r2")
    print("  benchmark, spaced, median over rounds of each boot's p50 (us, unscored)")
    for o in ("kcall", "zero", "msg", "msgx", "sock"):
        print("    %-5s %s" % (o, ", ".join("%s=%.2f" % (c, st.median(bench[(c, o, "spaced", r)] for r in rounds
                                                                              if (c, o, "spaced", r) in bench))
                                           for c in CFGS if any((c, o, "spaced", r) in bench for r in rounds))))
    print("  P1  pinning io-sock shortens the second read: r2 P2s64 - U2s64 %+.2f us (want <= -3) -> %s"
          % (p1, verdict("HELD" if p1 <= -3 else "REFUTED")))
    print("  P2  pinned, two vCPUs are one: r2 P2s64 - U1s64 %+.2f us (want within 3 of 0) -> %s"
          % (p2, verdict("HELD" if abs(p2) <= 3 else "REFUTED")))
    print("  P3  the round trip follows: %+.2f us (want <= -3) -> %s" % (p3, verdict("HELD" if p3 <= -3 else "REFUTED")))
    print("  P4  on one vCPU the extra read is still long: r2 U1s64 %.2f us (want >= 8) -> %s"
          % (r2u1, verdict("HELD" if r2u1 >= 8 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
