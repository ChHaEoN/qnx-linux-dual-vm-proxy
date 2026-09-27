#!/usr/bin/env python3
"""someip0_report.py OUT -- run-someip0.sh's follow-up (vsomeip without its nPDU retention), by the rule
the harness's header fixed before any run (Phase 3b / A6, 2026-09-27, OD12).

Per arm (CT VT VT0 CU VU VU0) and round: the probe's p50 and p99. Differences are paired within the
round; the interval is the distribution-free one of widest coverage >= 95%. M3 reads each boot's
guest console (console-A_r<round>.log): one full, clean "tcp client done (eof)" line per TCP arm.
M4 reads the four vsomeip configurations the run wrote.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from someip_report import DONE  # noqa: E402
from sweep_report import interval  # noqa: E402

ARMS = ("CT", "VT", "VT0", "CU", "VU", "VU0")
PROTO = {"CT": "csomeip", "VT": "vsomeip", "VT0": "vsomeip", "CU": "csomeipu", "VU": "vsomeipu", "VU0": "vsomeipu"}
TCP_ARMS = ("CT", "VT", "VT0")
NPDU = ("debounce-time-request", "debounce-time-response", "max-retention-time-request", "max-retention-time-response")


def configs_ok(out):
    """M4: tcp0 and udp0 carry the four timings at "0"; tcp and udp carry none."""
    for name in ("tcp", "udp", "tcp0", "udp0"):
        p = os.path.join(out, "vsomeip-%s.json" % name)
        if not os.path.exists(p):
            return False
        t = json.load(open(p)).get("npdu-default-timings")
        if name.endswith("0"):
            if not t or sorted(t) != sorted(NPDU) or any(v != "0" for v in t.values()):
                return False
        elif t is not None:
            return False
    return True


def main(argv):
    out = argv[0]
    stamp = json.load(open(os.path.join(out, "stamp.json"))) if os.path.exists(os.path.join(out, "stamp.json")) else {}
    n_want, warm = stamp.get("n"), stamp.get("warmup", 200)
    core = (stamp.get("pin") or {}).get("probe")
    arm = {}
    for f in os.listdir(out):
        m = re.match(r"lat-(CT|VT0|VT|CU|VU0|VU)_r(\d+)\.json$", f)
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
    ok = {"M1": bool(rounds) and not problems,
          "M2": bool(rounds) and all(k in arm and arm[k].get("vsomeip") == (None if k[0] in ("CT", "CU") else "3.4.10")
                                     for k in keys),
          "M3": bool(rounds) and not m3_problems,
          "M4": configs_ok(out)}
    print("  rounds %d" % len(rounds))
    print("  M1 every arm %d rounds of n samples, none rejected or bad, its own transport, the client on core %s -> %s"
          % (len(rounds), core, "ok" if ok["M1"] else "FAILED"))
    for msg in problems[:6]:
        print("     %s" % msg)
    print("  M2 VT, VU, VT0, VU0 name vsomeip 3.4.10, CT and CU none -> %s" % ("ok" if ok["M2"] else "FAILED"))
    print("  M3 every boot's guest judged all of CT's, VT's and VT0's requests, none rejected or in error -> %s"
          % ("ok" if ok["M3"] else "FAILED"))
    for msg in m3_problems[:6]:
        print("     %s" % msg)
    print("  M4 the 0 configurations carry the four npdu timings at 0, the others none -> %s" % ("ok" if ok["M4"] else "FAILED"))
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
        print("    %-4s %-9s %9.2f %9.2f" % (a, PROTO[a], med(a), med(a, "p99_ms")))

    def d(a, b, key="p50_ms"):
        return [us(a, r, key) - us(b, r, key) for r in rounds if (a, r) in arm and (b, r) in arm]

    def show(label, vals):
        lo, hi, cov = interval(vals)
        m = st.median(vals)
        print("    %-34s %+9.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (label, m, lo, hi, 100 * cov,
                                                                         sum(v > 0 for v in vals), len(vals)))
        return m

    print("  differences at p50, paired within round (us): median [interval], rounds > 0")
    vt_vt0 = show("VT - VT0  (the retention, TCP)", d("VT", "VT0"))
    vu_vu0 = show("VU - VU0  (the retention, UDP)", d("VU", "VU0"))
    vt0_ct = show("VT0 - CT  (vsomeip, TCP)", d("VT0", "CT"))
    vu0_cu = show("VU0 - CU  (vsomeip, UDP)", d("VU0", "CU"))
    show("VT - CT   (unscored)", d("VT", "CT"))
    show("VU - CU   (unscored)", d("VU", "CU"))
    print("  differences at p99, paired within round (us), unscored")
    for a, b in (("VT0", "CT"), ("VU0", "CU")):
        show("%s - %s at p99" % (a, b), d(a, b, "p99_ms"))
    ct, cu = med("CT"), med("CU")
    p1 = 4800 <= vt_vt0 <= 5200 and 4800 <= vu_vu0 <= 5200
    p2 = vt0_ct >= 10 and vu0_cu >= 10
    p3 = vt0_ct <= 0.25 * ct and vu0_cu <= 0.25 * cu
    print("  P1  the retention is the ~5 ms: VT - VT0 %+.2f, VU - VU0 %+.2f us (want both in [4800, 5200]) -> %s"
          % (vt_vt0, vu_vu0, verdict("HELD" if p1 else "REFUTED")))
    print("  P2  vsomeip without it still adds >= 10 us: VT0 - CT %+.2f, VU0 - CU %+.2f us -> %s"
          % (vt0_ct, vu0_cu, verdict("HELD" if p2 else "REFUTED")))
    print("  P3  and <= 0.25 x the plain C++ p50: %+.2f <= %.2f (TCP), %+.2f <= %.2f (UDP) -> %s"
          % (vt0_ct, 0.25 * ct, vu0_cu, 0.25 * cu, verdict("HELD" if p3 else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
