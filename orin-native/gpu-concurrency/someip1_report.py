#!/usr/bin/env python3
"""someip1_report.py OUT -- run-someip1.sh (vsomeip's threads off the client's core), by the rule the
harness's header fixed before any run (Phase 3b / A6, 2026-09-27, OD12).

Per arm (CT VT0 VT0s CU VU0 VU0s) and round: the probe's p50 and p99. Differences are paired within
the round; the interval is the distribution-free one of widest coverage >= 95%. M3 reads each boot's
guest console; M4 the two configurations; M5 the threads each client reported (vprobe_threads).
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from someip0_report import NPDU  # noqa: E402
from someip_report import DONE  # noqa: E402
from sweep_report import interval  # noqa: E402

ARMS = ("CT", "VT0", "VT0s", "CU", "VU0", "VU0s")
PROTO = {"CT": "csomeip", "VT0": "vsomeip", "VT0s": "vsomeip", "CU": "csomeipu", "VU0": "vsomeipu", "VU0s": "vsomeipu"}
TCP_ARMS = ("CT", "VT0", "VT0s")


def placement_ok(s, arm, core, aux):
    """M5 for one file: VT0/VU0 every thread on the probe core; VT0s/VU0s one or more on aux, none
    outside {core, aux}; the plain arms are not judged."""
    if arm in ("CT", "CU"):
        return True
    th = s.get("vprobe_threads") or []
    cpus = [t.get("cpus") for t in th]
    if not cpus:
        return False
    if arm in ("VT0", "VU0"):
        return all(c == str(core) for c in cpus)
    return str(aux) in cpus and all(c in (str(core), str(aux)) for c in cpus)


def main(argv):
    out = argv[0]
    stamp = json.load(open(os.path.join(out, "stamp.json"))) if os.path.exists(os.path.join(out, "stamp.json")) else {}
    n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    pin = stamp.get("pin") or {}
    core, aux = pin.get("probe"), pin.get("aux")
    arm = {}
    for f in os.listdir(out):
        m = re.match(r"lat-(CT|VT0s|VT0|CU|VU0s|VU0)_r(\d+)\.json$", f)
        if m:
            arm[(m.group(1), int(m.group(2)))] = json.load(open(os.path.join(out, f)))["summary"]
    rounds = sorted({r for _, r in arm})
    keys = [(a, r) for a in ARMS for r in rounds]
    problems = []
    for k in keys:
        s = arm.get(k)
        if s is None:
            problems.append("%s_r%d: missing" % k)
            continue
        bad = [x for x, ok in (("n", n_want is None or s.get("n") == n_want), ("bad", s.get("bad") == 0),
                               ("rejected", s.get("rejected_by_monitor") == 0),
                               ("proto", s.get("proto") == PROTO[k[0]]),
                               ("core", core is None or s.get("cpu_affinity") == [core])) if not ok]
        if bad:
            problems.append("%s_r%d: %s" % (k[0], k[1], ", ".join(bad)))
    m3_problems = []
    for r in rounds:
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        full = [x for x in DONE.findall(text) if n_want is not None and int(x[0]) == n_want + warm]
        clean = [x for x in full if x[2] == "0" and x[3] == "0"]
        if len(full) != len(TCP_ARMS) or len(clean) != len(TCP_ARMS):
            m3_problems.append("round %d: %d full connection(s), %d clean, want %d" % (r, len(full), len(clean), len(TCP_ARMS)))
    m4 = True
    for name in ("tcp0", "udp0"):
        p = os.path.join(out, "vsomeip-%s.json" % name)
        t = json.load(open(p)).get("npdu-default-timings") if os.path.exists(p) else None
        if not t or sorted(t) != sorted(NPDU) or any(v != "0" for v in t.values()):
            m4 = False
    placed = [k for k in keys if k in arm and not placement_ok(arm[k], k[0], core, aux)]
    ok = {"M1": bool(rounds) and not problems,
          "M2": bool(rounds) and all(k in arm and arm[k].get("vsomeip") == (None if k[0] in ("CT", "CU") else "3.4.10")
                                     for k in keys),
          "M3": bool(rounds) and not m3_problems,
          "M4": m4,
          "M5": bool(rounds) and not placed and core is not None and aux is not None}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected or bad, its own transport, the main thread on core %s -> %s"
          % (len(rounds), core, "ok" if ok["M1"] else "FAILED"))
    for msg in problems[:6]:
        print("     %s" % msg)
    print("  M2 the vsomeip arms name vsomeip 3.4.10, CT and CU none -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 every boot's guest judged all of CT's, VT0's and VT0s's requests, none rejected or in error -> %s"
          % ("ok" if ok["M3"] else "FAILED"))
    for msg in m3_problems[:6]:
        print("     %s" % msg)
    print("  M4 both configurations carry the four npdu timings at 0 -> %s" % ("ok" if ok["M4"] else "FAILED"))
    print("  M5 threads as designed: VT0/VU0 all on core %s; VT0s/VU0s on %s and %s only, one or more on %s -> %s"
          % (core, core, aux, aux, "ok" if ok["M5"] else "FAILED"))
    for k in placed[:6]:
        print("     %s_r%d: %s" % (k[0], k[1], arm[k].get("vprobe_threads")))
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def us(a, r, key="p50_ms"):
        return arm[(a, r)][key] * 1000.0

    def med(a, key="p50_ms"):
        return st.median(us(a, r, key) for r in rounds if (a, r) in arm)

    print("  per arm, medians over rounds (us):   p50      p99")
    for a in ARMS:
        print("    %-5s %-9s %9.2f %9.2f" % (a, PROTO[a], med(a), med(a, "p99_ms")))
    threads = sorted({t.get("comm") for k in keys if k in arm for t in (arm[k].get("vprobe_threads") or [])} - {None})
    print("  client threads seen: %s" % ", ".join(threads))

    def d(a, b, key="p50_ms"):
        return [us(a, r, key) - us(b, r, key) for r in rounds if (a, r) in arm and (b, r) in arm]

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-34s %+9.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                         sum(v > 0 for v in vals), len(vals)))
        return m

    print("  differences at p50, paired within round (us): median [interval], rounds > 0")
    t_move = show("VT0 - VT0s (off the core, TCP)", d("VT0", "VT0s"))
    u_move = show("VU0 - VU0s (off the core, UDP)", d("VU0", "VU0s"))
    t_cost = show("VT0s - CT  (vsomeip, spread, TCP)", d("VT0s", "CT"))
    u_cost = show("VU0s - CU  (vsomeip, spread, UDP)", d("VU0s", "CU"))
    show("VT0 - CT   (unscored)", d("VT0", "CT"))
    show("VU0 - CU   (unscored)", d("VU0", "CU"))
    print("  differences at p99, paired within round (us), unscored")
    for a, b in (("VT0", "VT0s"), ("VU0", "VU0s"), ("VT0s", "CT"), ("VU0s", "CU")):
        show("%s - %s at p99" % (a, b), d(a, b, "p99_ms"))
    p1 = abs(t_move) <= 10 and abs(u_move) <= 10
    p2 = t_cost >= 30 and u_cost >= 30
    print("  P1  moving vsomeip's threads off the client's core changes little: %+.2f (TCP), %+.2f us (UDP), want both within 10 of 0 -> %s"
          % (t_move, u_move, verdict("HELD" if p1 else "REFUTED")))
    print("  P2  vsomeip spread still costs >= 30 us: VT0s - CT %+.2f, VU0s - CU %+.2f us -> %s"
          % (t_cost, u_cost, verdict("HELD" if p2 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
