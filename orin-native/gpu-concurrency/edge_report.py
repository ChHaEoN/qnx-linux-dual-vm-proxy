#!/usr/bin/env python3
"""edge_report.py OUT -- run-edge.sh's map of where the guest path's fast path begins, by the rule
the harness's header fixed before any run (Phase 3b / A6, 2026-09-26). The same arithmetic as
mss_report.py (load, packets), over its own arms; the namespace's read counts are in edge-ns.log.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mss_report import LINE, PORT, load, packets  # noqa: E402
from sweep_report import interval  # noqa: E402

G_SIZES = (1448, 1449, 1452, 1456, 1458, 1459, 1460, 1461, 1462, 1464, 1468, 1472)
B_SIZES = (1460, 1461)
ARMS = tuple("G%d" % s for s in G_SIZES) + tuple("B%d" % s for s in B_SIZES)
TOL_READS = 0.02
EDGE = -8.0        # P1, us
FLAT = 3.0         # P2, P3, us
HOST_FLAT = 2.0    # P4, us
TWO = 1.8          # P5, packets per exchange each way


def reads(out, frames):
    got, problems, order = {}, [], []
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) order: (.*)$", line.strip())
            if m:
                order.append((int(m.group(1)), m.group(2).split()))
    for path, name in (("G", "guest-console.log"), ("B", "edge-ns.log")):
        fp = os.path.join(out, name)
        text = open(fp, encoding="utf-8", errors="replace").read() if os.path.exists(fp) else ""
        sess = [(int(f), int(rd)) for pt, _, f, rd in LINE.findall(text) if int(pt) == PORT and int(f) == frames]
        want = [(a, r) for r, arms in order for a in arms if a[0] == path]
        if len(sess) != len(want):
            problems.append("%s: %d connections of %d frames for %d arms" % (path, len(sess), frames, len(want)))
            continue
        for (a, r), (f, rd) in zip(want, sess):
            got[(a, r)] = rd / f
    return got, problems


def main(argv):
    out = argv[0]
    p50, stats = load(out)
    rounds = sorted({r for _, r in p50})
    n_want, warm = None, 200
    sp = os.path.join(out, "stamp.json")
    if os.path.exists(sp):
        stamp = json.load(open(sp))
        n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    ex = (n_want or 1000) + warm
    pk = packets(out, ex)
    rpf, problems = reads(out, ex)
    keys = [(a, r) for a in ARMS for r in rounds]
    ok = {"M1": bool(rounds) and all(k in stats and stats[k][1] == 0 and stats[k][2] == 0 and stats[k][3] == int(k[0][1:])
                                      and (n_want is None or stats[k][0] == n_want) for k in keys),
          "M2": bool(rounds) and not problems and all(("G1448", r) in rpf and abs(rpf[("G1448", r)] - 1.0) <= TOL_READS
                                                      for r in rounds),
          "M3": bool(rounds) and all(k in pk for k in keys)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm has %d rounds of n samples, none rejected, none bad, its own size -> %s"
          % (len(rounds), "ok" if ok["M1"] else "FAILED"))
    for msg in problems:
        print("     %s" % msg)
    print("  M2 one read per frame (within %.2f) at G1448 -> %s" % (TOL_READS, "ok" if ok["M2"] else "FAILED"))
    print("  M3 every arm has its counters before and after -> %s" % ("ok" if ok["M3"] else "FAILED"))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def med(vals):
        return st.median(vals) if vals else float("nan")

    print("  per arm, medians over rounds: p50 (us); packets per exchange tx/rx; reads per frame")
    for a in ARMS:
        print("    %-6s %8.2f   %5.2f/%-5.2f   %s" % (a, med([p50[(a, r)] for r in rounds if (a, r) in p50]),
                                                   med([pk[(a, r)][0] for r in rounds if (a, r) in pk]),
                                                   med([pk[(a, r)][1] for r in rounds if (a, r) in pk]),
                                                   "%.3f" % med([rpf[(a, r)] for r in rounds if (a, r) in rpf])
                                                   if any((a, r) in rpf for r in rounds) else "-"))

    def d(a, b):
        return [p50[(a, r)] - p50[(b, r)] for r in rounds if (a, r) in p50 and (b, r) in p50]

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-22s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                       sum(v > 0 for v in vals), len(vals)))
        return m

    print("  adjacent steps on the guest path, paired within round (us): median [interval], rounds > 0")
    for a, b in zip(G_SIZES, G_SIZES[1:]):
        show("G%d -> G%d" % (a, b), d("G%d" % b, "G%d" % a))
    print("  the scored differences")
    p1 = show("G1461 - G1460", d("G1461", "G1460"))
    p2 = show("G1460 - G1449", d("G1460", "G1449"))
    p3 = show("G1472 - G1461", d("G1472", "G1461"))
    p4 = show("B1461 - B1460", d("B1461", "B1460"))
    over = {s: (med([pk[("G%d" % s, r)][0] for r in rounds if ("G%d" % s, r) in pk]),
                med([pk[("G%d" % s, r)][1] for r in rounds if ("G%d" % s, r) in pk])) for s in G_SIZES if s > 1448}
    lowest = min(min(t, x) for t, x in over.values())
    print("  P1  the edge at 1460/1461: G1461 - G1460 %+.2f us (want <= %+.0f) -> %s"
          % (p1, EDGE, verdict("HELD" if p1 <= EDGE else "REFUTED")))
    print("  P2  flat before it: G1460 - G1449 %+.2f us (want within %.0f of 0) -> %s"
          % (p2, FLAT, verdict("HELD" if abs(p2) <= FLAT else "REFUTED")))
    print("  P3  flat after it: G1472 - G1461 %+.2f us (want within %.0f of 0) -> %s"
          % (p3, FLAT, verdict("HELD" if abs(p3) <= FLAT else "REFUTED")))
    print("  P4  no edge on the host path: B1461 - B1460 %+.2f us (want within %.0f of 0) -> %s"
          % (p4, HOST_FLAT, verdict("HELD" if abs(p4) <= HOST_FLAT else "REFUTED")))
    print("  P5  two packets each way from 1449 to 1472 B: lowest %.2f per exchange (want >= %.1f) -> %s"
          % (lowest, TWO, verdict("HELD" if lowest >= TWO else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
