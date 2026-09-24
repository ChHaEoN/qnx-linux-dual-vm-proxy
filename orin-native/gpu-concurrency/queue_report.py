#!/usr/bin/env python3
"""queue_report.py OUT N WARMUP -- run-queue.sh's test: does the slow window need udevd to
PROCESS the uevents, or is the kernel emitting them enough? (Phase 3b / A6, 2026-09-24), by
the rule its header fixed before any run.

Each round has an ARM (order.log, "round R arm: run|hold"): udevd's exec queue running as
usual, or held (udevadm control --stop-exec-queue) through the round and released after
it. Alignment and classes are bursts_report.py's (tj, then the injection kinds, other,
out); a class's EXCESS in an arm is its median round trip minus that arm's out median,
pooled over the arm's aligned rounds. queue.log records whether udevd's queue held events
at the end of every round, before any release. Scored only at k = 24; a prediction resting
on a failed check prints VOID.
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
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 24
ARMS = ("run", "hold")
QUIET, SLOW = 10.0, 20.0
MIN_U, MIN_TJ = 50, 40


def arms_of(out):
    arms = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) arm: (run|hold)", line)
            if m:
                arms[int(m.group(1))] = m.group(2)
    return arms


def queue_ok(out, arms):
    """(rounds whose end-of-round queue state fits the arm, rounds checked)."""
    seen = {}
    p = os.path.join(out, "queue.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) end: queue (held|empty)", line)
            if m:
                seen[int(m.group(1))] = m.group(2)
    good = sum(1 for r, a in arms.items() if seen.get(r) == ("held" if a == "hold" else "empty"))
    return good, len(arms)


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    arms = arms_of(out)
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    by = {a: collections.defaultdict(list) for a in ARMS}
    aligned, rows = 0, []
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
        inj = os.path.join(out, "inj-t2ms_r%d.jsonl" % r)
        rows += [json.loads(l) for l in open(inj)] if os.path.exists(inj) else []
        marks = {k: [t for t, e, x in ev if e == "M" and x == k] for k in br.KINDS}
        tj = [t for t, e, z in ev if e == "T" and z == br.ZONE]
        other = [t for t, e, z in ev if e == "T" and z != br.ZONE]
        for t0, v in zip(reqs[warm:], lat):
            by[a][br.classify(t0, tj, marks, other)].append(v * 1000.0)
    k = len(files)
    ex = {a: {c: (st.median(by[a][c]) - st.median(by[a]["out"])) if by[a][c] and by[a]["out"] else float("nan")
              for c in ("tj", "U", "N")} for a in ARMS}
    u = [x for x in rows if x["kind"] == "U"]
    u_ok = sum(1 for x in u if x["seq_after"] - x["seq_before"] >= 3)
    q_good, q_n = queue_ok(out, arms)
    nl = br.logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": bool(u) and u_ok / len(u) >= 0.9,
          "M3": q_n > 0 and q_good == q_n,
          "M4": all(len(by[a]["U"]) >= MIN_U and len(by[a]["tj"]) >= MIN_TJ for a in ARMS),
          "M5": nl == 0,
          "M6": all(ex[a]["N"] == ex[a]["N"] and abs(ex[a]["N"]) < QUIET for a in ARMS)}
    print("  rounds %d, aligned %d, arms %s" % (k, aligned, dict(collections.Counter(arms.values()))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U raised the seqnum by >= 3: %d/%d (want >= 90%%) -> %s" % (u_ok, len(u), "ok" if ok["M2"] else "FAILED"))
    print("  M3 rounds whose queue at the end fits the arm (held: events waiting; run: empty): %d/%d (want all) -> %s"
          % (q_good, q_n, "ok" if ok["M3"] else "FAILED"))
    print("  M4 exchanges U %s, tj %s (want >= %d and >= %d per arm) -> %s"
          % ({a: len(by[a]["U"]) for a in ARMS}, {a: len(by[a]["tj"]) for a in ARMS}, MIN_U, MIN_TJ,
             "ok" if ok["M4"] else "FAILED"))
    print("  M5 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M5"] else "FAILED"))
    print("  M6 the null windows are quiet: N excess %s (want within +-%.0f) -> %s"
          % ({a: round(ex[a]["N"], 1) for a in ARMS}, QUIET, "ok" if ok["M6"] else "FAILED"))
    print("  %-5s %10s %10s %10s %10s" % ("arm", "out p50", "U excess", "tj excess", "N excess"))
    for a in ARMS:
        print("  %-5s %10.1f %+10.1f %+10.1f %+10.1f" % (a, st.median(by[a]["out"]) if by[a]["out"] else float("nan"),
                                                     ex[a]["U"], ex[a]["tj"], ex[a]["N"]))
    scored = k == SCORED_K
    base = ["M1", "M3", "M4", "M5", "M6"]
    print("  P1  held, the injected uevents make no window: U %+.1f us (quiet below +%.0f) -> %s"
          % (ex["hold"]["U"], QUIET, verdict("HELD" if ex["hold"]["U"] < QUIET else "REFUTED", scored, k, ok,
                                             base + ["M2"])))
    print("  P2  held, the poll's own uevents make none either: tj %+.1f us (quiet below +%.0f) -> %s"
          % (ex["hold"]["tj"], QUIET, verdict("HELD" if ex["hold"]["tj"] < QUIET else "REFUTED", scored, k, ok, base)))
    print("  P3  running, the injected uevents still make one (the control): U %+.1f us (slow from +%.0f) -> %s"
          % (ex["run"]["U"], SLOW, verdict("HELD" if ex["run"]["U"] >= SLOW else "REFUTED", scored, k, ok,
                                           base + ["M2"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
