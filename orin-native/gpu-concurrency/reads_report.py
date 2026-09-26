#!/usr/bin/env python3
"""reads_report.py OUT -- run-reads.sh's test: is the guest path's 64 -> 96 B step the frame's size
or the endpoint's second read()? By the rule the harness's header fixed before any run (Phase 3b /
A6, 2026-09-26).

Per round, the p50 of each arm; a difference is two arms' p50s in the same round, and per
difference the median over rounds with the distribution-free interval of widest coverage >= 95%.
Reads per frame: each endpoint instance prints `sweep: reads :PORT MODE frames=F reads=R` per
connection; the connections that served an arm (F = n + warm-up) are matched to the arms on that
port and path in the run's order (order.log). The guest's lines are in guest-console.log, the
namespace's in reads-ns-PORT.log.
"""
import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("Gd64", "Gd96", "Gg64", "Gg96", "Gs64", "Gd1024", "Gd1280", "Gd1536", "Gg1024", "Gg1280", "Gg1536",
        "Bd64", "Bd96", "Bg64", "Bg96", "Bs64")
PORT = {"d": 7120, "g": 7121, "s": 7122}
EXACT = {"Gd64": 1, "Gg64": 1, "Gg96": 1, "Bd64": 1, "Bg64": 1, "Bg96": 1,
         "Gd96": 2, "Gs64": 2, "Bd96": 2, "Bs64": 2}
TOL_READS = 0.02
NONE_WITHIN = 3.0     # P1, P4: us
STEP_AT_LEAST = 10.0  # P2, P3: us
CHEAP = 3.0           # P4: us
BUMP_AT_LEAST = 5.0   # P5: us
LINE = re.compile(r"sweep: reads :(\d+) (\w+) frames=(\d+) reads=(\d+)")


def load(out):
    p50, stats, fb = {}, {}, {}
    for f in glob.glob(os.path.join(out, "lat-*_r*.json")):
        m = re.search(r"lat-([GB][dgs]\d+)_r(\d+)\.json$", f)
        if m:
            s = json.load(open(f))["summary"]
            key = (m.group(1), int(m.group(2)))
            p50[key] = s["p50_ms"] * 1000.0
            stats[key] = (s.get("n"), s.get("bad"), s.get("rejected_by_monitor"))
            fb[key] = s.get("frame_bytes")
    return p50, stats, fb


def run_order(out):
    rows = []
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) order: (.*)$", line.strip())
            if m:
                rows.append((int(m.group(1)), m.group(2).split()))
    return rows


def reads_per_frame(out, frames):
    """{(arm, round): reads/frame}, and the problems met matching connections to arms."""
    got, problems = {}, []
    texts = {"G": "", "B": {}}
    p = os.path.join(out, "guest-console.log")
    if os.path.exists(p):
        texts["G"] = open(p, encoding="utf-8", errors="replace").read()
    for port in PORT.values():
        p = os.path.join(out, "reads-ns-%d.log" % port)
        texts["B"][port] = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
    order = run_order(out)
    for path in ("G", "B"):
        for mode, port in PORT.items():
            text = texts["G"] if path == "G" else texts["B"][port]
            sess = [(int(f), int(rd)) for pt, _, f, rd in LINE.findall(text) if int(pt) == port and int(f) == frames]
            want = [(a, r) for r, arms in order for a in arms if a[0] == path and a[1] == mode]
            if len(sess) != len(want):
                problems.append("%s :%d: %d connections of %d frames for %d arms" % (path, port, len(sess), frames, len(want)))
                continue
            for (a, r), (f, rd) in zip(want, sess):
                got[(a, r)] = rd / f
    return got, problems


def main(argv):
    out = argv[0]
    p50, stats, fb = load(out)
    rounds = sorted({r for _, r in p50})
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    rpf, problems = reads_per_frame(out, (n_want or 1000) + warm)
    keys = [(a, r) for a in ARMS for r in rounds]
    cnt = set()
    p = os.path.join(out, "counters.log")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            if len(f) == 7:
                cnt.add((f[0], f[2]))
    bad_reads = [(a, r, rpf.get((a, r))) for a in EXACT for r in rounds
                 if rpf.get((a, r)) is None or abs(rpf[(a, r)] - EXACT[a]) > TOL_READS]
    ok = {"M1": len(rounds) > 0 and all(k in stats and stats[k][1] == 0 and stats[k][2] == 0
                                         and (n_want is None or stats[k][0] == n_want)
                                         and fb.get(k) == int(k[0][2:]) for k in keys),
          "M2": len(rounds) > 0 and not problems and not bad_reads,
          "M3": len(rounds) > 0 and all(("%s_r%d" % k, w) in cnt for k in keys for w in ("before", "after"))}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm has %d rounds of n samples, none rejected, none bad -> %s" % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    for msg in problems:
        print("     %s" % msg)
    for a, r, v in bad_reads[:8]:
        print("     %s round %d: reads per frame %s, designed %d" % (a, r, "missing" if v is None else "%.3f" % v, EXACT[a]))
    print("  M2 the read counts are the design's (within %.2f) -> %s" % (TOL_READS, "ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm has its counters before and after -> %s" % ("ok" if ok["M3"] else "FAILED"))

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    print("  per arm: p50 (median over rounds, us); reads per frame (median over rounds)")
    for a in ARMS:
        v = [p50[(a, r)] for r in rounds if (a, r) in p50]
        rr = [rpf[(a, r)] for r in rounds if (a, r) in rpf]
        print("    %-7s %8.2f   reads/frame %s" % (a, st.median(v) if v else float("nan"),
                                                   "%.3f" % st.median(rr) if rr else "-"))

    def diff(fn):
        vals = []
        for r in rounds:
            try:
                vals.append(fn(r))
            except KeyError:
                pass
        return vals

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-40s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    def d(a, b):
        return diff(lambda r: p50[(a, r)] - p50[(b, r)])

    def bump(x):
        return diff(lambda r: p50[(x + "1280", r)] - (p50[(x + "1024", r)] + p50[(x + "1536", r)]) / 2.0)

    if not rounds:
        return 0
    print("  differences, paired within round (us): median [interval], rounds > 0")
    g_g = show("Gg96 - Gg64 (one read each)", d("Gg96", "Gg64"))
    g_s = show("Gs64 - Gd64 (two reads against one)", d("Gs64", "Gd64"))
    g_d = show("Gd96 - Gd64 (the sweep's step)", d("Gd96", "Gd64"))
    b_s = show("Bs64 - Bd64", d("Bs64", "Bd64"))
    b_g = show("Bg96 - Bg64", d("Bg96", "Bg64"))
    show("Bd96 - Bd64", d("Bd96", "Bd64"))
    g_b = show("Gd1280 - mean(Gd1024, Gd1536)", bump("Gd"))
    show("Gg1280 - mean(Gg1024, Gg1536) (unscored)", bump("Gg"))
    show("Gg1280 - Gd1280 (unscored)", d("Gg1280", "Gd1280"))
    print("  P1  one read removes the step: Gg96 - Gg64 %+.2f (want within %.0f of 0) -> %s"
          % (g_g, NONE_WITHIN, verdict("HELD" if abs(g_g) <= NONE_WITHIN else "REFUTED")))
    print("  P2  two reads make it at 64 B: Gs64 - Gd64 %+.2f (want >= %+.0f) -> %s"
          % (g_s, STEP_AT_LEAST, verdict("HELD" if g_s >= STEP_AT_LEAST else "REFUTED")))
    print("  P3  the step replicates: Gd96 - Gd64 %+.2f (want >= %+.0f) -> %s"
          % (g_d, STEP_AT_LEAST, verdict("HELD" if g_d >= STEP_AT_LEAST else "REFUTED")))
    print("  P4  natively an extra read is cheap: Bs64 - Bd64 %+.2f (want <= %+.0f), Bg96 - Bg64 %+.2f "
          "(want within %.0f of 0) -> %s"
          % (b_s, CHEAP, b_g, NONE_WITHIN, verdict("HELD" if b_s <= CHEAP and abs(b_g) <= NONE_WITHIN else "REFUTED")))
    print("  P5  the 1280 B bump replicates: %+.2f (want >= %+.0f) -> %s"
          % (g_b, BUMP_AT_LEAST, verdict("HELD" if g_b >= BUMP_AT_LEAST else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
