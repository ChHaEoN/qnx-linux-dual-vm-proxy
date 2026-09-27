#!/usr/bin/env python3
"""someip_report.py OUT -- run-someip.sh's SOME/IP arm, by the rule the harness's header fixed before
any run (Phase 3b / A6, 2026-09-27, OD12).

Per arm (T U ST SU CT CU VT VU) and round: the probe's p50 and p99. Differences are paired within
the round; the interval is the distribution-free one of widest coverage >= 95%. The guest's
console (console-A_r<round>.log) is read for M3: one "tcp client done (eof)" line per TCP SOME/IP
arm, each with every request judged and none rejected or in error.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_report import interval  # noqa: E402

ARMS = ("T", "U", "ST", "SU", "CT", "CU", "VT", "VU")
PROTO = {"T": "tcp", "U": "udp", "ST": "someip", "SU": "someipu", "CT": "csomeip", "CU": "csomeipu",
         "VT": "vsomeip", "VU": "vsomeipu"}
TCP_SOMEIP = ("ST", "CT", "VT")
DONE = re.compile(r"someip: tcp client done \(eof\): seen=(\d+) accepted=(\d+) rejected=(\d+) errors=(\d+) dropped=(\d+)")


def load(out):
    arm = {}
    for a in ARMS:
        for f in os.listdir(out):
            m = re.match(r"lat-%s_r(\d+)\.json$" % a, f)
            if m:
                s = json.load(open(os.path.join(out, f)))["summary"]
                arm[(a, int(m.group(1)))] = s
    return arm


def main(argv):
    out = argv[0]
    stamp = json.load(open(os.path.join(out, "stamp.json"))) if os.path.exists(os.path.join(out, "stamp.json")) else {}
    n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    core = (stamp.get("pin") or {}).get("probe")
    arm = load(out)
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
    m1 = bool(rounds) and not problems
    m2 = bool(rounds) and all(k in arm and arm[k].get("vsomeip") == ("3.4.10" if k[0] in ("VT", "VU") else None)
                              for k in keys if k[0] in ("CT", "CU", "VT", "VU"))
    m3_problems = []
    for r in rounds:
        p = os.path.join(out, "console-A_r%d.log" % r)
        text = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
        full = [x for x in DONE.findall(text) if n_want is not None and int(x[0]) == n_want + warm]
        clean = [x for x in full if x[2] == "0" and x[3] == "0"]
        if len(full) != len(TCP_SOMEIP) or len(clean) != len(TCP_SOMEIP):
            m3_problems.append("round %d: %d full connection(s), %d clean, want %d"
                               % (r, len(full), len(clean), len(TCP_SOMEIP)))
    m3 = bool(rounds) and not m3_problems
    ok = {"M1": m1, "M2": m2, "M3": m3}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected or bad, its own transport, the client on core %s -> %s"
          % (len(rounds), core, "ok" if m1 else "FAILED"))
    for msg in problems[:6]:
        print("     %s" % msg)
    print("  M2 VT and VU name vsomeip 3.4.10, CT and CU none -> %s" % ("ok" if m2 else "FAILED"))
    print("  M3 every boot's guest judged all of ST's, CT's and VT's requests, none rejected or in error -> %s"
          % ("ok" if m3 else "FAILED"))
    for msg in m3_problems[:6]:
        print("     %s" % msg)
    if not rounds:
        return 0

    def verdict(v, needs=("M1", "M2", "M3")):
        failed = [m for m in needs if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    def us(a, r, key="p50_ms"):
        return arm[(a, r)][key] * 1000.0

    def med(a, key="p50_ms"):
        return st.median(us(a, r, key) for r in rounds if (a, r) in arm)

    print("  per arm, medians over rounds (us):   p50      p99")
    for a in ARMS:
        print("    %-3s %-9s %9.2f %9.2f" % (a, PROTO[a], med(a), med(a, "p99_ms")))

    def d(a, b, key="p50_ms"):
        return [us(a, r, key) - us(b, r, key) for r in rounds if (a, r) in arm and (b, r) in arm]

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-32s %+8.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                        sum(v > 0 for v in vals), len(vals)))
        return m

    print("  differences at p50, paired within round (us): median [interval], rounds > 0")
    st_t = show("ST - T   (header, TCP)", d("ST", "T"))
    su_u = show("SU - U   (header, UDP)", d("SU", "U"))
    vt_ct = show("VT - CT  (vsomeip, TCP)", d("VT", "CT"))
    vu_cu = show("VU - CU  (vsomeip, UDP)", d("VU", "CU"))
    show("CT - ST  (C++ client, unscored)", d("CT", "ST"))
    show("CU - SU  (C++ client, unscored)", d("CU", "SU"))
    show("VT - VU  (unscored)", d("VT", "VU"))
    print("  differences at p99, paired within round (us), unscored")
    for a, b in (("ST", "T"), ("SU", "U"), ("VT", "CT"), ("VU", "CU")):
        show("%s - %s at p99" % (a, b), d(a, b, "p99_ms"))
    ct, cu = med("CT"), med("CU")
    p1 = abs(st_t) <= 3 and abs(su_u) <= 3
    p2 = vt_ct >= 10 and vu_cu >= 10
    p3 = vt_ct <= 0.25 * ct and vu_cu <= 0.25 * cu
    print("  P1  the header is next to free: ST - T %+.2f, SU - U %+.2f us (want both within 3 of 0) -> %s"
          % (st_t, su_u, verdict("HELD" if p1 else "REFUTED")))
    print("  P2  vsomeip adds >= 10 us: VT - CT %+.2f, VU - CU %+.2f us -> %s"
          % (vt_ct, vu_cu, verdict("HELD" if p2 else "REFUTED")))
    print("  P3  and <= 0.25 x the plain C++ p50: %+.2f <= %.2f (TCP), %+.2f <= %.2f (UDP) -> %s"
          % (vt_ct, 0.25 * ct, vu_cu, 0.25 * cu, verdict("HELD" if p3 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
