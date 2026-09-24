#!/usr/bin/env python3
"""headless_report.py OUT N WARMUP -- run-headless.sh's test: does the uevent window, and
the background tail, need the desktop? (Phase 3b / A6, 2026-09-24), by the rule its
header fixed before any run.

Each round has a STATE (order.log, "round R state: G|H"): G with the desktop
(graphical.target), H without it (multi-user.target). Alignment and the classes are
uevent_report.py's (tj, U, R, other, out). A class's EXCESS in a state is the median
round trip of its exchanges minus the median of that state's out class, pooled over the
state's aligned rounds. The background tail of a state is the p99 of its out class,
pooled. The manipulation checks read states.log (gnome-shell and Xorg counts before and
after every round) and logins.txt (SSH logins accepted during the rounds). Scored only
at k = 24; a prediction resting on a failed check prints VOID.
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
import uevent_report as ur  # noqa: E402

SCORED_K = 24
STATES = ("G", "H")
KEEP = 0.5                       # P1, P3: H's excess >= KEEP x G's
LOWER = 0.9                      # P2: H's out p99 <= LOWER x G's
MIN_WINDOW_US = 15.0             # M4: G's U excess, for P1 to mean anything
MIN_U, MIN_TJ = 60, 40


def states_of(out):
    st_ = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) state: ([GH])", line)
            if m:
                st_[int(m.group(1))] = m.group(2)
    return st_


def desktop_ok(out, states):
    """(rounds whose before and after counts fit their state, rounds checked)."""
    seen = collections.defaultdict(list)
    p = os.path.join(out, "states.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) (before|after) gnome-shell=(\d+) xorg=(\d+)", line)
            if m:
                seen[int(m.group(1))].append((int(m.group(3)), int(m.group(4))))
    good = 0
    for r, s in states.items():
        obs = seen.get(r, [])
        want_on = s == "G"
        if len(obs) == 2 and all((gs > 0 and xo > 0) if want_on else (gs == 0 and xo == 0) for gs, xo in obs):
            good += 1
    return good, len(states)


def logins(out):
    p = os.path.join(out, "logins.txt")
    if not os.path.exists(p):
        return None
    m = re.search(r"accepted=(\d+)", open(p).read())
    return int(m.group(1)) if m else None


def score_keep(h, g):
    return "HELD" if g > 0 and h >= KEEP * g else "REFUTED"


def score_lower(h, g):
    return "HELD" if h <= LOWER * g else "REFUTED"


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    states = states_of(out)
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    by = {s: collections.defaultdict(list) for s in STATES}
    aligned, inj_rows = 0, []
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        s = states.get(r)
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        if s not in STATES or not os.path.exists(tp):
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
        inj_rows += [json.loads(l) for l in open(inj)] if os.path.exists(inj) else []
        marks = {k: [t for t, e, x in ev if e == "M" and x == k] for k in ur.KINDS}
        tj = [t for t, e, z in ev if e == "T" and z == ur.ZONE]
        other = [t for t, e, z in ev if e == "T" and z != ur.ZONE]
        for t0, v in zip(reqs[warm:], lat):
            by[s][ur.classify(t0, tj, marks, other)].append(v * 1000.0)
    k = len(files)
    u_ok, u_n, r_ok, r_n = ur.manip_ok(inj_rows)
    d_good, d_n = desktop_ok(out, states)
    ex = {s: {c: (st.median(by[s][c]) - st.median(by[s]["out"])) if by[s][c] and by[s]["out"] else float("nan")
              for c in ("U", "tj", "R")} for s in STATES}
    p99 = {s: ur.pct(by[s]["out"], 99) if by[s]["out"] else float("nan") for s in STATES}
    nl = logins(out)
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": u_n > 0 and r_n > 0 and u_ok / u_n >= 0.9 and r_ok / r_n >= 0.9,
          "M3": d_n > 0 and d_good == d_n,
          "M4": ex["G"]["U"] >= MIN_WINDOW_US,
          "M5": all(len(by[s]["U"]) >= MIN_U and len(by[s]["tj"]) >= MIN_TJ for s in STATES),
          "M6": nl == 0}
    print("  rounds %d, aligned %d, states %s" % (k, aligned, dict(collections.Counter(states.values()))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U raised the seqnum by >= 3: %d/%d; R left it: %d/%d (want >= 90%% each) -> %s"
          % (u_ok, u_n, r_ok, r_n, "ok" if ok["M2"] else "FAILED"))
    print("  M3 rounds whose gnome-shell and Xorg counts fit their state before and after: %d/%d (want all) -> %s"
          % (d_good, d_n, "ok" if ok["M3"] else "FAILED"))
    print("  M4 the window with the desktop: U excess %+.1f us (want >= %.0f) -> %s"
          % (ex["G"]["U"], MIN_WINDOW_US, "ok" if ok["M4"] else "FAILED"))
    print("  M5 exchanges U %s, tj %s (want >= %d and >= %d per state) -> %s"
          % ({s: len(by[s]["U"]) for s in STATES}, {s: len(by[s]["tj"]) for s in STATES}, MIN_U, MIN_TJ,
             "ok" if ok["M5"] else "FAILED"))
    print("  M6 SSH logins accepted during the rounds: %s (want 0) -> %s" % (nl, "ok" if ok["M6"] else "FAILED"))
    print("  %-5s %10s %10s %10s %10s %12s" % ("state", "out p50", "U excess", "tj excess", "R excess", "out p99"))
    for s in STATES:
        print("  %-5s %10.1f %+10.1f %+10.1f %+10.1f %12.1f" % (s, st.median(by[s]["out"]) if by[s]["out"] else float("nan"),
                                                           ex[s]["U"], ex[s]["tj"], ex[s]["R"], p99[s]))
    scored = k == SCORED_K
    base = ["M1", "M3", "M6"]
    v1 = verdict(score_keep(ex["H"]["U"], ex["G"]["U"]), scored, k, ok, base + ["M2", "M4", "M5"])
    v2 = verdict(score_lower(p99["H"], p99["G"]), scored, k, ok, base)
    v3 = verdict(score_keep(ex["H"]["tj"], ex["G"]["tj"]), scored, k, ok, base + ["M5"])
    print("  P1  the uevent window survives without the desktop: U excess H %+.1f us, G %+.1f us -> %s"
          % (ex["H"]["U"], ex["G"]["U"], v1))
    print("  P2  the background tail is lower without it: out p99 H %.1f us, G %.1f us -> %s" % (p99["H"], p99["G"], v2))
    print("  P3  the poll's own window survives too: tj excess H %+.1f us, G %+.1f us -> %s"
          % (ex["H"]["tj"], ex["G"]["tj"], v3))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
