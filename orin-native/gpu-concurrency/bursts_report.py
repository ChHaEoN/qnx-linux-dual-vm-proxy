#!/usr/bin/env python3
"""bursts_report.py OUT N WARMUP -- run-bursts.sh's test: which kind of work on another
core makes the slow window? (Phase 3b / A6, 2026-09-24), by the rule its header fixed
before any run.

For every round whose trace holds exactly WARMUP + N requests (frames into the tap of the
round's most common length), timed sample j is request WARMUP + j and its T0 is that
request's time. Each timed exchange is put in one class, first match wins: tj (T0 within
-0.5..+6 ms of a traced tj-thermal read), then each injection kind K in U N C M T S (T0
within -0.5..+8 ms of a K marker), then other (another zone's read, -0.5..+6 ms), else
out. A class's EXCESS is the median round trip of its exchanges minus the median of the
out class, pooled over the aligned rounds. The injector's log (inj-t2ms_rN.jsonl) gives
each injection's seqnum before and after, duration and iterations; logins.txt the SSH
logins accepted during the rounds. Scored only at k = 24; a prediction resting on a failed
check prints VOID.
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
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 24
ZONE = "tj-thermal"
KINDS = ("U", "N", "C", "M", "T", "S")
BURSTS = ("C", "M", "T", "S")
BEFORE, AFTER_READ, AFTER_INJ = 500.0, 6000.0, 8000.0
MIN_IN = 50
QUIET, SLOW, SOME = 10.0, 20.0, 10.0          # us of excess
DUR_LO, DUR_HI = 2500.0, 3600.0               # us: a burst ran its length


def pct(v, p):
    s = sorted(v)
    return s[int(round(p / 100.0 * (len(s) - 1)))]


def near(t0, marks, after):
    return any(m - BEFORE <= t0 <= m + after for m in marks)


def classify(t0, tj, marks, other):
    if near(t0, tj, AFTER_READ):
        return "tj"
    for k in KINDS:
        if near(t0, marks.get(k, []), AFTER_INJ):
            return k
    if near(t0, other, AFTER_READ):
        return "other"
    return "out"


def score_quiet(ex):
    return "HELD" if ex < QUIET else "REFUTED"


def score_slow(ex):
    return "HELD" if ex >= SLOW else ("PARTIAL" if ex >= SOME else "REFUTED")


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def logins(out):
    p = os.path.join(out, "logins.txt")
    if not os.path.exists(p):
        return None
    m = re.search(r"accepted=(\d+)", open(p).read())
    return int(m.group(1)) if m else None


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    by = collections.defaultdict(list)
    tails = collections.Counter()
    aligned, marked, rows = 0, 0, []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        if not os.path.exists(tp):
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
        marks = {k: [t for t, e, x in ev if e == "M" and x == k] for k in KINDS}
        marked += sum(len(v) for v in marks.values())
        tj = [t for t, e, z in ev if e == "T" and z == ZONE]
        other = [t for t, e, z in ev if e == "T" and z != ZONE]
        rtt = [v * 1000.0 for v in lat]
        p99 = pct(rtt, 99)
        for t0, v in zip(reqs[warm:], rtt):
            c = classify(t0, tj, marks, other)
            by[c].append(v)
            tails[(c, "n")] += 1
            tails[(c, "t")] += v >= p99
    k = len(files)
    base = st.median(by["out"]) if by["out"] else float("nan")
    ex = {c: (st.median(by[c]) - base) if by[c] else float("nan") for c in ("tj",) + KINDS + ("other",)}
    u = [x for x in rows if x["kind"] == "U"]
    rest = [x for x in rows if x["kind"] != "U"]
    u_ok = sum(1 for x in u if x["seq_after"] - x["seq_before"] >= 3)
    r_ok = sum(1 for x in rest if x["seq_after"] == x["seq_before"])
    dur = {b: [x["dur_us"] for x in rows if x["kind"] == b] for b in BURSTS}
    dur_ok = all(dur[b] and DUR_LO <= st.median(dur[b]) <= DUR_HI for b in BURSTS) \
        and all(x["iters"] > 0 for x in rows if x["kind"] in BURSTS)
    nl = logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": bool(u) and bool(rest) and u_ok / len(u) >= 0.9 and r_ok / len(rest) >= 0.9,
          "M3": bool(rows) and marked / len(rows) >= 0.9,
          "M4": all(len(by[c]) >= MIN_IN for c in KINDS),
          "M5": dur_ok,
          "M6": nl == 0,
          "M7": ex["N"] == ex["N"] and abs(ex["N"]) < QUIET}
    print("  rounds %d, aligned %d" % (k, aligned))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U raised the seqnum by >= 3: %d/%d; the others left it: %d/%d (want >= 90%% each) -> %s"
          % (u_ok, len(u), r_ok, len(rest), "ok" if ok["M2"] else "FAILED"))
    print("  M3 injection markers in the traces: %d of %d logged (want >= 90%%) -> %s"
          % (marked, len(rows), "ok" if ok["M3"] else "FAILED"))
    print("  M4 exchanges per injection class %s (want >= %d each) -> %s"
          % ({c: len(by[c]) for c in KINDS}, MIN_IN, "ok" if ok["M4"] else "FAILED"))
    print("  M5 burst durations (median us) %s, iterations all > 0 (want %.0f-%.0f us) -> %s"
          % ({b: round(st.median(dur[b]), 1) if dur[b] else None for b in BURSTS}, DUR_LO, DUR_HI,
             "ok" if ok["M5"] else "FAILED"))
    print("  M6 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M6"] else "FAILED"))
    print("  M7 the null windows are quiet: N excess %+.1f us (want within +-%.0f) -> %s"
          % (ex["N"], QUIET, "ok" if ok["M7"] else "FAILED"))
    print("  out p50 %.1f us" % base)
    print("  %-6s %10s %10s %6s %10s" % ("class", "exchanges", "excess us", "tail", "tail rate"))
    for c in ("tj",) + KINDS + ("other", "out"):
        n_, t_ = tails[(c, "n")], tails[(c, "t")]
        print("  %-6s %10d %+10.1f %6d %9.2f%%" % (c, n_, ex.get(c, 0.0) if c != "out" else 0.0, t_,
                                                100.0 * t_ / max(1, n_)))
    scored = k == SCORED_K
    allm = ["M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    print("  P1  compute on another core is not it: C %+.1f us (quiet below +%.0f) -> %s"
          % (ex["C"], QUIET, verdict(score_quiet(ex["C"]), scored, k, ok, allm)))
    print("  P2  memory traffic makes the window: M %+.1f us (slow from +%.0f) -> %s"
          % (ex["M"], SLOW, verdict(score_slow(ex["M"]), scored, k, ok, allm)))
    print("  P3  broadcast TLB maintenance makes the window: T %+.1f us (slow from +%.0f) -> %s"
          % (ex["T"], SLOW, verdict(score_slow(ex["T"]), scored, k, ok, allm)))
    print("  P4  plain syscalls are not it: S %+.1f us (quiet below +%.0f) -> %s"
          % (ex["S"], QUIET, verdict(score_quiet(ex["S"]), scored, k, ok, allm)))
    print("  P5  the uevents still make it (the control): U %+.1f us (slow from +%.0f) -> %s"
          % (ex["U"], SLOW, verdict("HELD" if ex["U"] >= SLOW else "REFUTED", scored, k, ok,
                                    ["M1", "M2", "M3", "M4", "M6"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
