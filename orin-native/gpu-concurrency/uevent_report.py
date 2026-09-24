#!/usr/bin/env python3
"""uevent_report.py OUT N WARMUP -- run-uevent.sh's test: is it the uevents? (Phase 3b /
A6, 2026-09-24), by the rule its header fixed before any run.

For every round whose trace holds exactly WARMUP + N requests (frames into the tap of
the round's most common length), timed sample j is request WARMUP + j and its T0 is
that request's time. A TAIL exchange is at or above its round's p99 round trip. Each
timed exchange is put in one class, first match wins:
  tj     T0 within [-0.5, +6] ms of a traced tj-thermal read (the poll itself);
  U      T0 within [-0.5, +8] ms of a U injection's marker (three uevents, no read);
  R      T0 within [-0.5, +8] ms of an R injection's marker (three reads, no uevent);
  other  T0 within [-0.5, +6] ms of another zone's read;
  out    none of these.
The injector's own log (inj-t2ms_rN.jsonl) gives each injection's uevent seqnum before
and after. Scored only at k = 24; a prediction resting on a failed check prints VOID.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tjphase_trace as tjt  # noqa: E402

SCORED_K = 24
ZONE = "tj-thermal"
BEFORE = 500.0                  # us
AFTER_READ, AFTER_INJ = 6000.0, 8000.0
MIN_IN = 30
QUIET = 10.0                    # %
KINDS = ("U", "R")


def pct(v, p):
    s = sorted(v)
    return s[int(round(p / 100.0 * (len(s) - 1)))]


def near(t0, marks, after):
    return any(m - BEFORE <= t0 <= m + after for m in marks)


def classify(t0, tj, inj, other):
    """inj: {"U": [times], "R": [times]}."""
    if near(t0, tj, AFTER_READ):
        return "tj"
    for k in KINDS:
        if near(t0, inj.get(k, []), AFTER_INJ):
            return k
    if near(t0, other, AFTER_READ):
        return "other"
    return "out"


HOT, WARM = 25.0, 10.0           # %: P1, P3


def score_hot(r_in):
    """P1, P3: HELD when the class's tail rate (%) is >= HOT, PARTIAL at >= WARM."""
    return "HELD" if r_in >= HOT else ("PARTIAL" if r_in >= WARM else "REFUTED")


def score_quiet(r_in):
    """P2: HELD when the class's tail rate (%) is below QUIET."""
    return "HELD" if r_in < QUIET else "REFUTED"


def manip_ok(log_rows):
    """(U injections with seqnum +>= 3, U total, R injections with seqnum +0, R total)."""
    u = [r for r in log_rows if r["kind"] == "U"]
    rr = [r for r in log_rows if r["kind"] == "R"]
    return (sum(1 for r in u if r["seq_after"] - r["seq_before"] >= 3), len(u),
            sum(1 for r in rr if r["seq_after"] == r["seq_before"]), len(rr))


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    counts = {c: [0, 0] for c in ("tj", "U", "R", "other", "out")}      # [exchanges, tail]
    aligned = marked = scheduled = 0
    rows = []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        inj = os.path.join(out, "inj-t2ms_r%d.jsonl" % r)
        if not os.path.exists(tp):
            continue
        log_rows = [json.loads(l) for l in open(inj)] if os.path.exists(inj) else []
        ev = tjt.read(tp)
        lens = [int(x) for _, e, x in ev if e == "X" and int(x) >= 100]
        req_len = max(set(lens), key=lens.count) if lens else None
        reqs = [t for t, e, x in ev if e == "X" and int(x) == req_len]
        lat = json.load(open(f))["samples_in_order"]
        if len(reqs) != warm + n or len(lat) != n:
            print("  round %d not aligned: %d requests traced, %d expected" % (r, len(reqs), warm + n))
            continue
        aligned += 1
        rows += log_rows
        scheduled += len(log_rows)
        marks = {k: [t for t, e, x in ev if e == "M" and x == k] for k in KINDS}
        marked += sum(len(v) for v in marks.values())
        tj = [t for t, e, z in ev if e == "T" and z == ZONE]
        other = [t for t, e, z in ev if e == "T" and z != ZONE]
        rtt = [v * 1000.0 for v in lat]
        p99 = pct(rtt, 99)
        for t0, v in zip(reqs[warm:], rtt):
            c = classify(t0, tj, marks, other)
            counts[c][0] += 1
            counts[c][1] += v >= p99
    k = len(files)
    rate = {c: (100.0 * t / e if e else float("nan")) for c, (e, t) in counts.items()}
    u_ok, u_n, r_ok, r_n = manip_ok(rows)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": u_n > 0 and r_n > 0 and u_ok / u_n >= 0.9 and r_ok / r_n >= 0.9,
          "M3": scheduled > 0 and marked / scheduled >= 0.9,
          "M4": counts["U"][0] >= MIN_IN and counts["R"][0] >= MIN_IN,
          "M5": counts["tj"][0] >= MIN_IN}
    print("  rounds %d, aligned %d" % (k, aligned))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U injections that raised the uevent seqnum by >= 3: %d/%d; R injections that left it: %d/%d"
          " (want >= 90%% each) -> %s" % (u_ok, u_n, r_ok, r_n, "ok" if ok["M2"] else "FAILED"))
    print("  M3 injection markers in the traces: %d of %d logged (want >= 90%%) -> %s"
          % (marked, scheduled, "ok" if ok["M3"] else "FAILED"))
    print("  M4 exchanges in U windows %d, in R windows %d (want >= %d each) -> %s"
          % (counts["U"][0], counts["R"][0], MIN_IN, "ok" if ok["M4"] else "FAILED"))
    print("  M5 exchanges in tj windows %d (want >= %d) -> %s" % (counts["tj"][0], MIN_IN, "ok" if ok["M5"] else "FAILED"))
    print("  %-6s %10s %6s %10s" % ("class", "exchanges", "tail", "tail rate"))
    for c in ("tj", "U", "R", "other", "out"):
        print("  %-6s %10d %6d %9.2f%%" % (c, counts[c][0], counts[c][1], rate[c]))
    scored = k == SCORED_K
    ratio = lambda c: rate[c] / rate["out"] if rate["out"] else float("inf")
    v1 = verdict(score_hot(rate["U"]), scored, k, ok, ["M1", "M2", "M3", "M4"])
    v2 = verdict(score_quiet(rate["R"]), scored, k, ok, ["M1", "M2", "M3", "M4"])
    v3 = verdict(score_hot(rate["tj"]), scored, k, ok, ["M1", "M5"])
    print("  P1  three uevents alone make the slow window: U %.2f%% (%.1fx the outside rate) -> %s"
          % (rate["U"], ratio("U"), v1))
    print("  P2  three temperature reads alone do not: R %.2f%% (quiet below %.0f%%) -> %s" % (rate["R"], QUIET, v2))
    print("  P3  the poll itself still does, in this run: tj %.2f%% (%.1fx the outside rate) -> %s"
          % (rate["tj"], ratio("tj"), v3))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
