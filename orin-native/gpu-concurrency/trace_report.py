#!/usr/bin/env python3
"""trace_report.py OUT -- run-trace.sh's kernel-trace test, by the rule the harness's header fixed
before any run (Phase 3b / A6, 2026-09-27).

Per window (trace-N_r<pair>.txt, trace-L_r<pair>.txt): the reads of its kind, cut by guesttrace.py
into A, B, R, Cw, Ck; per read io = B + Cw (io-sock's work) and kern = A + R + Ck (the kernel's
pass); per window the median of each over its reads. Per pair N - L; per quantity the median over
pairs with the distribution-free interval of widest coverage >= 95%.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guesttrace as gt  # noqa: E402
from sweep_report import interval  # noqa: E402

GAP_S = 0.001
MIN_READS = 300
MAX_FAILED = 0.02
KEYS = ("A", "B", "R", "Cw", "Ck", "io", "kern", "total")
CLIENT = {"N": "qnx-echo-server-timed", "L": "qnx-ipcbench"}


def window(path, kind):
    """One trace window: (per-key median in us, facts for the checks, description), or None."""
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8", errors="replace").read()
    sec = gt.sections(text)
    facts = {"rc_ok": all(sec["rc"].get(k) == 0 for k in ("tracelogger", "traceprinter", "pidin"))
             and text.startswith("started pid ") and text.rstrip().endswith("end")}
    tr = gt.Trace(sec.get("traceprinter", ""))
    facts["buffers_ok"] = bool(tr.buffers) and tr.buffers_contiguous()
    facts["cpu0"] = tr.cpus() == [0]
    io = tr.pid_of("io-sock")
    if len(io) != 1 or tr.hz <= 0:
        facts.update(n=0, failed=0, found=0)
        return None, facts, {}
    clients = set(tr.pid_of(CLIENT[kind]))
    msgs = [m for m in gt.messages(tr, io[0]) if m["client"][0] in clients]
    gap = GAP_S * tr.hz
    picked = gt.pick_second_reads(msgs, gap) if kind == "N" else gt.pick_loopback_reads(msgs, gap)
    segs, failed = [], 0
    for m in picked:
        s, _why = gt.segments(tr, m, io[0])
        if s is None:
            failed += 1
            continue
        s["io"] = s["B"] + s["Cw"]
        s["kern"] = s["A"] + s["R"] + s["Ck"]
        segs.append(s)
    facts.update(n=len(segs), failed=failed, found=len(picked))
    if not segs:
        return None, facts, {}
    med = {k: st.median(tr.us(s[k]) for s in segs) for k in KEYS}
    return med, facts, gt.summarise(tr, segs)


def main(argv):
    out = argv[0]
    stamp = json.load(open(os.path.join(out, "stamp.json"))) if os.path.exists(os.path.join(out, "stamp.json")) else {}
    n_want = stamp.get("n")
    pairs = []
    p = os.path.join(out, "order.log")
    if os.path.exists(p):
        for line in open(p):
            m = re.match(r"pair (\d+) order: ", line)
            if m:
                pairs.append(int(m.group(1)))
    res, desc, problems = {}, {}, []
    m3 = bool(pairs)
    for r in pairs:
        for kind in ("N", "L"):
            got = window(os.path.join(out, "trace-%s_r%d.txt" % (kind, r)), kind)
            if got is None:
                problems.append("pair %d %s: no trace" % (r, kind))
                continue
            med, facts, d = got
            ok = (facts["rc_ok"] and facts["buffers_ok"] and facts["cpu0"] and facts["n"] >= MIN_READS
                  and facts["failed"] <= MAX_FAILED * max(1, facts["found"]))
            if not ok:
                problems.append("pair %d %s: %s" % (r, kind, facts))
            if med is not None:
                res[(kind, r)] = med
                desc[(kind, r)] = d
        lat = os.path.join(out, "lat-N_r%d.json" % r)
        s = json.load(open(lat))["summary"] if os.path.exists(lat) else None
        if not s or s.get("bad") != 0 or s.get("rejected_by_monitor") != 0 or s.get("frame_bytes") != 64 \
                or (n_want is not None and s.get("n") != n_want):
            m3 = False
            problems.append("pair %d N: the probe's summary is missing or unclean" % r)
        b = os.path.join(out, "bench-L_r%d.txt" % r)
        bt = open(b).read() if os.path.exists(b) else ""
        if not re.search(r"^op sock regime spaced ", bt, re.M) or not bt.rstrip().endswith("done"):
            m3 = False
            problems.append("pair %d L: the benchmark did not run its spaced sock op to done" % r)
    m1 = bool(pairs) and not [x for x in problems if "probe" not in x and "benchmark" not in x]
    rounds = [r for r in pairs if ("N", r) in res and ("L", r) in res]

    def d(key):
        return [res[("N", r)][key] - res[("L", r)][key] for r in rounds]

    total = d("total")
    m2 = bool(total) and st.median(total) >= 3.0
    ok = {"M1": m1, "M2": m2, "M3": m3}
    print("  pairs %d" % len(pairs))
    print("  M1 every window's trace is whole, one CPU, >= %d reads of its kind, <= 2%% not cut -> %s"
          % (MIN_READS, "ok" if m1 else "FAILED"))
    for msg in problems[:8]:
        print("     %s" % msg)
    print("  M2 the whole read is >= 3 us longer for the network read under tracing: %s -> %s"
          % ("%+.2f us" % st.median(total) if total else "n/a", "ok" if m2 else "FAILED"))
    print("  M3 every N probe clean, every L benchmark ran its spaced sock op -> %s" % ("ok" if m3 else "FAILED"))
    if not rounds:
        return 0

    def verdict(v, needs):
        failed = [m for m in needs if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    print("  per kind, median over windows of the window medians (us):")
    print("    kind    n/win " + " ".join("%7s" % k for k in KEYS))
    for kind in ("N", "L"):
        ns = [desc[(kind, r)]["n"] for r in rounds]
        print("    %-6s %6d " % (kind, st.median(ns)) + " ".join("%7.2f" % st.median(res[(kind, r)][k] for r in rounds) for k in KEYS))
    print("  differences N - L, paired within pair (us): median [interval], pairs > 0")
    meds = {}
    for k in KEYS:
        v = d(k)
        lo, hi, cov = interval(v)
        meds[k] = st.median(v)
        print("    %-6s %+7.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (k, meds[k], lo, hi, 100 * cov,
                                                                     sum(x > 0 for x in v), len(v)))
    print("  P1  io-sock's work B + Cw is >= 3 us longer for the network read: %+.2f us -> %s"
          % (meds["io"], verdict("HELD" if meds["io"] >= 3 else "REFUTED", ["M1", "M2", "M3"])))
    print("  P2  the kernel's pass A + R + Ck differs by <= 1.5 us: %+.2f us -> %s"
          % (meds["kern"], verdict("HELD" if abs(meds["kern"]) <= 1.5 else "REFUTED", ["M1", "M2", "M3"])))
    print("  unscored: io-sock's kernel calls per read (mean count x median us), in B and in Cw")
    for kind in ("N", "L"):
        for ph in ("B", "Cw"):
            names = sorted({c for r in rounds for c in desc[(kind, r)]["kc_" + ph]})
            parts = []
            for c in names:
                cnt = st.median(desc[(kind, r)]["kc_" + ph].get(c, (0, 0))[0] for r in rounds)
                us = st.median(desc[(kind, r)]["kc_" + ph].get(c, (0, 0))[1] for r in rounds)
                parts.append("%s %.2fx%.2f" % (c, cnt, us))
            print("    %s %-2s %s" % (kind, ph, "; ".join(parts) if parts else "none"))
    print("  unscored: other threads inside a read (mean us per read): idle, other io-sock threads, other")
    for kind in ("N", "L"):
        print("    %s  %.2f  %.2f  %.2f" % (kind, *(st.median(desc[(kind, r)]["others_" + x] for r in rounds)
                                                for x in ("idle", "io-sock", "other"))))
    print("  unscored: the io-sock thread that served the read")
    for kind in ("N", "L"):
        names = {}
        for r in rounds:
            for w, c in desc[(kind, r)]["w_names"].items():
                names[w] = names.get(w, 0) + c
        print("    %s  %s" % (kind, ", ".join("%s %d" % (w, c) for w, c in sorted(names.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
