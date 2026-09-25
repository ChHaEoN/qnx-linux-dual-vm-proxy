#!/usr/bin/env python3
"""natural_report.py OUT N WARMUP -- run-natural.sh's test: with nothing injected, how much
of the tail goes when the host's userspace is confined to cores 3 and 5? (Phase 3b / A6,
2026-09-25), by the rule its header fixed before any run.

Each round has an ARM (order.log). Alignment is bursts_report.py's; each timed exchange is
tj (-0.5..+6 ms of a tj-thermal read), other (another zone's read) or out. An arm's tj
EXCESS is its tj median round trip minus its out median, pooled over the arm's aligned
rounds; its p50, p99 and p99.9 are over every timed exchange of those rounds. confine.log
holds the allowed CPUs of udevd, PID 1, gnome-shell and QEMU's threads before and after
every round (confine_report.conf_checks); seqnum.log the kernel's uevent seqnum around each
round. Scored only at k = 40; a prediction resting on a failed check prints VOID.
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
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 40
ARMS = cr.ARMS
SHRINK, LOWER99, LOWER999, SAME = 0.5, 0.95, 0.9, 2.0
MIN_TJ, WINDOW = 40, 10.0


def score_shrink(c, o):
    return "HELD" if o > 0 and c <= SHRINK * o else "REFUTED"


def score_lower(c, o, f):
    return "HELD" if c <= f * o else "REFUTED"


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def seqnums(out):
    """{round: uevents the kernel emitted during it} from seqnum.log."""
    got = {}
    p = os.path.join(out, "seqnum.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) seqnum (\d+) (\d+)", line)
            if m:
                got[int(m.group(1))] = int(m.group(3)) - int(m.group(2))
    return got


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    arms = cr.arms_of(out)
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    by = {a: collections.defaultdict(list) for a in ARMS}
    allv = {a: [] for a in ARMS}
    tail = {a: collections.Counter() for a in ARMS}
    aligned = 0
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        a = arms.get(r)
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        if a not in ARMS or not os.path.exists(tp):
            continue
        ev = tjt.read(tp)
        lens = [int(x) for _, e, x in ev if e == "X" and int(x) >= 100]
        req_len = max(set(lens), key=lens.count) if lens else None
        reqs = [t for t, e, x in ev if e == "X" and int(x) == req_len]
        lat = json.load(open(f))["samples_in_order"]
        if len(reqs) != warm + n or len(lat) != n:
            print("  round %d not aligned: %d requests traced, %d expected" % (r, len(reqs), warm + n))
            continue
        aligned += 1
        tj = [t for t, e, z in ev if e == "T" and z == br.ZONE]
        other = [t for t, e, z in ev if e == "T" and z != br.ZONE]
        cut = br.pct([v * 1000.0 for v in lat], 99)
        for t0, v in zip(reqs[warm:], lat):
            c = br.classify(t0, tj, {}, other)
            by[a][c].append(v * 1000.0)
            allv[a].append(v * 1000.0)
            if v * 1000.0 >= cut:
                tail[a][c] += 1
    k = len(files)
    ex = {a: (st.median(by[a]["tj"]) - st.median(by[a]["out"])) if by[a]["tj"] and by[a]["out"] else float("nan")
          for a in ARMS}
    q = {a: {p: br.pct(allv[a], p) if allv[a] else float("nan") for p in (50, 99, 99.9, 99.99)} for a in ARMS}
    mx = {a: max(allv[a]) if allv[a] else float("nan") for a in ARMS}
    fit, qemu_ok, nr = cr.conf_checks(out, arms)
    nl = br.logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": nr > 0 and fit == nr,
          "M3": all(len(by[a]["tj"]) >= MIN_TJ for a in ARMS) and ex["open"] == ex["open"] and ex["open"] >= WINDOW,
          "M4": nl == 0,
          "M5": nr > 0 and qemu_ok == nr}
    print("  rounds %d, aligned %d, arms %s" % (k, aligned, dict(collections.Counter(arms.values()))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 rounds whose udevd, PID 1 and gnome-shell were on %s (confined) or %s (open), before and after: %d/%d"
          " (want all) -> %s" % (cr.CONF, cr.OPEN, fit, nr, "ok" if ok["M2"] else "FAILED"))
    print("  M3 tj exchanges %s (want >= %d per arm), open tj excess %+.1f us (want >= +%.0f) -> %s"
          % ({a: len(by[a]["tj"]) for a in ARMS}, MIN_TJ, ex["open"], WINDOW, "ok" if ok["M3"] else "FAILED"))
    print("  M4 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M4"] else "FAILED"))
    print("  M5 rounds whose QEMU threads stayed on %s: %d/%d (want all) -> %s" % (cr.QEMU, qemu_ok, nr, "ok" if ok["M5"] else "FAILED"))
    print("  %-9s %7s %8s %8s %8s %8s %8s %10s %11s" % ("arm", "n", "p50", "p99", "p99.9", "p99.99", "max", "tj excess",
                                                          "tj of tail"))
    for a in ARMS:
        nt = sum(tail[a].values())
        print("  %-9s %7d %8.1f %8.1f %8.1f %8.1f %8.1f %+10.1f %6d/%-4d" % (a, len(allv[a]), q[a][50], q[a][99], q[a][99.9],
                                                                           q[a][99.99], mx[a], ex[a], tail[a]["tj"], nt))
    sq = seqnums(out)
    if sq:
        print("  uevents per round (seqnum): %s"
              % {a: sorted(collections.Counter(v for r, v in sq.items() if arms.get(r) == a).items()) for a in ARMS})
    scored = k == SCORED_K
    base = ["M1", "M2", "M4", "M5"]
    print("  P1  the poll's window shrinks: tj confined %+.1f, open %+.1f us -> %s"
          % (ex["confined"], ex["open"], verdict(score_shrink(ex["confined"], ex["open"]), scored, k, ok, base + ["M3"])))
    print("  P2  the tail is lower: p99 confined %.1f, open %.1f us -> %s"
          % (q["confined"][99], q["open"][99], verdict(score_lower(q["confined"][99], q["open"][99], LOWER99), scored, k, ok, base)))
    print("  P3  the far tail is lower: p99.9 confined %.1f, open %.1f us -> %s"
          % (q["confined"][99.9], q["open"][99.9],
             verdict(score_lower(q["confined"][99.9], q["open"][99.9], LOWER999), scored, k, ok, base)))
    print("  P4  the typical exchange does not change: p50 confined %.1f, open %.1f us -> %s"
          % (q["confined"][50], q["open"][50],
             verdict("HELD" if abs(q["confined"][50] - q["open"][50]) <= SAME else "REFUTED", scored, k, ok, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
