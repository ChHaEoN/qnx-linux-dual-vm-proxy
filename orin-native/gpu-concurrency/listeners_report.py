#!/usr/bin/env python3
"""listeners_report.py OUT N WARMUP -- run-listeners.sh's test: which listener makes the
slow window, and does it matter where it runs? (Phase 3b / A6, 2026-09-24), by the rule
its header fixed before any run.

Each round has one ARM (order.log, "round R arm: A"): free (udevd's own affinity), c3
(every udevd process pinned to core 3, in QEMU's L3) or c5 (pinned to core 5, in the
other L3). Alignment, the tail and the classes are uevent_report.py's (tj, U, R, other,
out). The ATTRIBUTION uses the second trace (sw-t2ms_rN.log, every core's switches):
each task's CPU time inside [mark, mark + 8 ms] of each U and R marker, leaving out
the idle task, QEMU's threads (qemu-tids.txt), the probe and the injector (python3,
sudo). A task's CLASS is systemd-udevd and its workers as "udevd", else its comm up to
any "/". Its EXCESS is its mean CPU per U window minus its mean per R window, in the
free arm. Scored only at k = 24; a prediction resting on a failed check prints VOID.
"""
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import listeners_trace as lt  # noqa: E402
import tjphase_trace as tjt  # noqa: E402
import uevent_report as ur  # noqa: E402

SCORED_K = 24
ARMS = ("free", "c3", "c5")
PIN = {"c3": 3, "c5": 5}
WIN = 8000.0                    # us after a marker, for the attribution
HOT = 25.0                      # %
PIN_SHARE = 0.95
MIN_UDEV_US = 500.0             # mean udevd CPU per U window for the pin check to mean anything
MIN_IN = 30
UDEV = ("systemd-udevd", "(udev-worker)")
SKIP_COMMS = ("idle", "python3", "sudo")


def klass(comm):
    return "udevd" if comm in UDEV else comm.split("/")[0]


def arms_of(out):
    arms = {}
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"round (\d+) arm: (\w+)", line)
            if m:
                arms[int(m.group(1))] = m.group(2)
    return arms


def score_p1(share):
    return "HELD" if share >= 0.5 else "REFUTED"


def score_p2(r3, r5):
    if r3 >= HOT and r3 >= 2 * r5:
        return "HELD"
    return "REFUTED" if r3 < 1.25 * r5 else "PARTIAL"


def score_p3(r):
    return "HELD" if r >= HOT else "REFUTED"


def verdict(v, scored, k, ok, needs):
    if not scored:
        return "not scored (k=%d; the prediction is for k=%d)" % (k, SCORED_K)
    failed = [m for m in needs if not ok[m]]
    return "VOID (%s failed)" % ", ".join(failed) if failed else v


def main(argv):
    out, n, warm = argv[0], int(argv[1]), int(argv[2])
    arms = arms_of(out)
    qemu = set()
    qp = os.path.join(out, "qemu-tids.txt")
    if os.path.exists(qp):
        qemu = {int(x) for x in open(qp).read().split()}
    skip = lambda comm, pid: comm in SKIP_COMMS or pid in qemu
    files = sorted(glob.glob(os.path.join(out, "lat-t2ms_r*.json")),
                   key=lambda f: int(re.search(r"_r(\d+)\.", f).group(1)))
    counts = {a: {c: [0, 0] for c in ("tj", "U", "R", "other", "out")} for a in ARMS}
    aligned = with_sw = 0
    inj_rows = []
    cpu_win = {a: {"U": collections.Counter(), "R": collections.Counter()} for a in ARMS}
    n_win = {a: collections.Counter() for a in ARMS}
    udev_core = {a: collections.Counter() for a in ARMS}
    for f in files:
        r = int(re.search(r"_r(\d+)\.", f).group(1))
        arm = arms.get(r)
        tp = os.path.join(out, "tp-t2ms_r%d.log" % r)
        if arm not in ARMS or not os.path.exists(tp):
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
        rtt = [v * 1000.0 for v in lat]
        p99 = ur.pct(rtt, 99)
        for t0, v in zip(reqs[warm:], rtt):
            c = ur.classify(t0, tj, marks, other)
            counts[arm][c][0] += 1
            counts[arm][c][1] += v >= p99
        sw = os.path.join(out, "sw-t2ms_r%d.log" % r)
        if not os.path.exists(sw):
            continue
        with_sw += 1
        runs = lt.Runs(lt.read(sw))
        for k in ur.KINDS:
            for m in marks[k]:
                n_win[arm][k] += 1
                for (comm, pid, core), us in runs.cpu(m, m + WIN, skip).items():
                    cpu_win[arm][k][klass(comm)] += us
                    if k == "U" and klass(comm) == "udevd":
                        udev_core[arm][core] += us
    k = len(files)
    rate = {a: {c: (100.0 * t / e if e else float("nan")) for c, (e, t) in counts[a].items()} for a in ARMS}
    u_ok, u_n, r_ok, r_n = ur.manip_ok(inj_rows)
    pin_ok, pin_txt = True, []
    for a, core in PIN.items():
        tot = sum(udev_core[a].values())
        share = udev_core[a][core] / tot if tot else 0.0
        mean = tot / n_win[a]["U"] if n_win[a]["U"] else 0.0
        pin_ok &= share >= PIN_SHARE and mean >= MIN_UDEV_US
        pin_txt.append("%s: %.1f%% on core %d, %.0f us per U window" % (a, 100 * share, core, mean))
    ok = {"M1": k > 0 and aligned / k >= 0.9,
          "M2": u_n > 0 and r_n > 0 and u_ok / u_n >= 0.9 and r_ok / r_n >= 0.9,
          "M3": pin_ok,
          "M4": all(counts[a]["U"][0] >= MIN_IN for a in ARMS) and n_win["free"]["R"] >= 5,
          "M5": aligned > 0 and with_sw == aligned}
    print("  rounds %d, aligned %d, arms %s" % (k, aligned, dict(collections.Counter(arms.get(
        int(re.search(r"_r(\d+)\.", f).group(1))) for f in files))))
    print("  M1 aligned rounds %d/%d (want >= 90%%) -> %s" % (aligned, k, "ok" if ok["M1"] else "FAILED"))
    print("  M2 U raised the seqnum by >= 3: %d/%d; R left it: %d/%d (want >= 90%% each) -> %s"
          % (u_ok, u_n, r_ok, r_n, "ok" if ok["M2"] else "FAILED"))
    print("  M3 udevd's CPU in U windows on its pinned core (want >= %.0f%%, and >= %.0f us per window): %s -> %s"
          % (100 * PIN_SHARE, MIN_UDEV_US, "; ".join(pin_txt), "ok" if ok["M3"] else "FAILED"))
    print("  M4 U exchanges per arm %s (want >= %d each), R windows in free %d (want >= 5) -> %s"
          % ({a: counts[a]["U"][0] for a in ARMS}, MIN_IN, n_win["free"]["R"], "ok" if ok["M4"] else "FAILED"))
    print("  M5 switch trace for %d of %d aligned rounds (want all) -> %s" % (with_sw, aligned, "ok" if ok["M5"] else "FAILED"))
    print("  %-5s %-6s %10s %6s %10s" % ("arm", "class", "exchanges", "tail", "tail rate"))
    for a in ARMS:
        for c in ("tj", "U", "R", "out"):
            print("  %-5s %-6s %10d %6d %9.2f%%" % (a, c, counts[a][c][0], counts[a][c][1], rate[a][c]))
    # attribution, free arm
    nu, nr = n_win["free"]["U"], n_win["free"]["R"]
    ex = {}
    for c in set(cpu_win["free"]["U"]) | set(cpu_win["free"]["R"]):
        ex[c] = (cpu_win["free"]["U"][c] / nu if nu else 0.0) - (cpu_win["free"]["R"][c] / nr if nr else 0.0)
    pos = sum(v for v in ex.values() if v > 0)
    share = ex.get("udevd", 0.0) / pos if pos > 0 else 0.0
    print("  free arm: mean CPU per window (us), U minus R, by task class (largest first):")
    for c, v in sorted(ex.items(), key=lambda kv: -kv[1])[:10]:
        print("    %-24s %+9.1f" % (c, v))
    print("  where udevd ran in U windows (us, summed): %s"
          % {a: dict(sorted(udev_core[a].items())) for a in ARMS})
    scored = k == SCORED_K
    v1 = verdict(score_p1(share), scored, k, ok, ["M1", "M2", "M4", "M5"])
    v2 = verdict(score_p2(rate["c3"]["U"], rate["c5"]["U"]), scored, k, ok, ["M1", "M2", "M3", "M4", "M5"])
    v3 = verdict(score_p3(rate["free"]["U"]), scored, k, ok, ["M1", "M2", "M4"])
    print("  P1  udevd's share of the U windows' excess CPU: %.1f%% -> %s" % (100 * share, v1))
    print("  P2  U windows' tail rate with udevd on core 3 %.2f%%, on core 5 %.2f%% -> %s"
          % (rate["c3"]["U"], rate["c5"]["U"], v2))
    print("  P3  U windows' tail rate with udevd free %.2f%% -> %s" % (rate["free"]["U"], v3))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
