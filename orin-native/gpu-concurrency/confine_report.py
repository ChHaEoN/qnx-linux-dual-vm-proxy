#!/usr/bin/env python3
"""confine_report.py OUT N WARMUP -- run-confine.sh's test: with the host's userspace
confined to cores 3 and 5, how much of the uevent window, and of the tail, goes? (Phase 3b /
A6, 2026-09-25), by the rule its header fixed before any run.

Each round has an ARM (order.log, "round R arm: open|confined"). Alignment and classes are
bursts_report.py's (tj, then the injection kinds, other, out); a class's EXCESS in an arm is
its median round trip minus that arm's out median, pooled over the arm's aligned rounds; an
arm's p50 and p99.9 are over every timed exchange of its aligned rounds. confine.log holds
the allowed CPUs of udevd, PID 1, gnome-shell and QEMU's threads before and after every
round. Scored only at k = 24; a prediction resting on a failed check prints VOID.
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
ARMS = ("open", "confined")
CONF, OPEN, QEMU = "3,5", "0-5", "0-2"
KEEP, LOWER, SAME = 0.5, 0.9, 2.0
QUIET = 10.0
MIN_U, MIN_TJ = 50, 40


def arms_of(out):
    arms = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) arm: (open|confined)", line)
            if m:
                arms[int(m.group(1))] = m.group(2)
    return arms


def conf_checks(out, arms):
    """(rounds whose before and after states fit their arm, rounds whose QEMU threads stayed
    on 0-2 throughout, rounds checked)."""
    seen = collections.defaultdict(list)
    p = os.path.join(out, "confine.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (before|after) udevd=(\S*) pid1=(\S*) gnome-shell=(\S*) qemu=(.*)$", line.rstrip())
            if m:
                seen[int(m.group(1))].append(m.groups()[2:])
    fit = qemu_ok = 0
    for r, a in arms.items():
        obs = seen.get(r, [])
        want = CONF if a == "confined" else OPEN
        if len(obs) == 2 and all(u == want and p1 == want and gs in (want, "none") for u, p1, gs, _ in obs):
            fit += 1
        if len(obs) == 2 and all(q.strip() == QEMU for _, _, _, q in obs):
            qemu_ok += 1
    return fit, qemu_ok, len(arms)


def score_keep(c, o):
    return "HELD" if o > 0 and c >= KEEP * o else "REFUTED"


def score_lower(c, o):
    return "HELD" if c <= LOWER * o else "REFUTED"


def score_same(c, o):
    return "HELD" if abs(c - o) <= SAME else "REFUTED"


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
    allv = {a: [] for a in ARMS}
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
            allv[a].append(v * 1000.0)
    k = len(files)
    ex = {a: {c: (st.median(by[a][c]) - st.median(by[a]["out"])) if by[a][c] and by[a]["out"] else float("nan")
              for c in ("tj", "U", "N")} for a in ARMS}
    p50 = {a: st.median(allv[a]) if allv[a] else float("nan") for a in ARMS}
    p999 = {a: br.pct(allv[a], 99.9) if allv[a] else float("nan") for a in ARMS}
    u = [x for x in rows if x["kind"] == "U"]
    u_ok = sum(1 for x in u if x["seq_after"] - x["seq_before"] >= 3)
    fit, qemu_ok, nr = conf_checks(out, arms)
    nl = br.logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": bool(u) and u_ok / len(u) >= 0.9,
          "M3": nr > 0 and fit == nr,
          "M4": all(len(by[a]["U"]) >= MIN_U and len(by[a]["tj"]) >= MIN_TJ for a in ARMS),
          "M5": nl == 0,
          "M6": all(ex[a]["N"] == ex[a]["N"] and abs(ex[a]["N"]) < QUIET for a in ARMS),
          "M7": nr > 0 and qemu_ok == nr}
    print("  rounds %d, aligned %d, arms %s" % (k, aligned, dict(collections.Counter(arms.values()))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U raised the seqnum by >= 3: %d/%d (want >= 90%%) -> %s" % (u_ok, len(u), "ok" if ok["M2"] else "FAILED"))
    print("  M3 rounds whose udevd, PID 1 and gnome-shell were on %s (confined) or %s (open), before and after: %d/%d"
          " (want all) -> %s" % (CONF, OPEN, fit, nr, "ok" if ok["M3"] else "FAILED"))
    print("  M4 exchanges U %s, tj %s (want >= %d and >= %d per arm) -> %s"
          % ({a: len(by[a]["U"]) for a in ARMS}, {a: len(by[a]["tj"]) for a in ARMS}, MIN_U, MIN_TJ,
             "ok" if ok["M4"] else "FAILED"))
    print("  M5 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M5"] else "FAILED"))
    print("  M6 the null windows are quiet: N excess %s (want within +-%.0f) -> %s"
          % ({a: round(ex[a]["N"], 1) for a in ARMS}, QUIET, "ok" if ok["M6"] else "FAILED"))
    print("  M7 rounds whose QEMU threads stayed on %s: %d/%d (want all) -> %s" % (QEMU, qemu_ok, nr, "ok" if ok["M7"] else "FAILED"))
    print("  %-9s %9s %9s %10s %10s %10s" % ("arm", "p50", "p99.9", "U excess", "tj excess", "N excess"))
    for a in ARMS:
        print("  %-9s %9.1f %9.1f %+10.1f %+10.1f %+10.1f" % (a, p50[a], p999[a], ex[a]["U"], ex[a]["tj"], ex[a]["N"]))
    scored = k == SCORED_K
    base = ["M1", "M3", "M5", "M7"]
    print("  P1  the uevent window does not halve: U confined %+.1f, open %+.1f us -> %s"
          % (ex["confined"]["U"], ex["open"]["U"], verdict(score_keep(ex["confined"]["U"], ex["open"]["U"]), scored, k, ok,
                                                           base + ["M2", "M4", "M6"])))
    print("  P2  neither does the poll's own: tj confined %+.1f, open %+.1f us -> %s"
          % (ex["confined"]["tj"], ex["open"]["tj"], verdict(score_keep(ex["confined"]["tj"], ex["open"]["tj"]), scored, k,
                                                             ok, base + ["M4", "M6"])))
    print("  P3  the far tail is lower: p99.9 confined %.1f, open %.1f us -> %s"
          % (p999["confined"], p999["open"], verdict(score_lower(p999["confined"], p999["open"]), scored, k, ok, base)))
    print("  P4  the typical exchange does not change: p50 confined %.1f, open %.1f us -> %s"
          % (p50["confined"], p50["open"], verdict(score_same(p50["confined"], p50["open"]), scored, k, ok, base)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
