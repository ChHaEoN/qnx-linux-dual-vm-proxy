#!/usr/bin/env python3
"""trace2_report.py OUT -- run-trace2.sh (TCP against UDP in the guest's kernel trace), by the rule the
harness's header fixed before any run (Phase 3b / A6, 2026-09-27).

Per window (trace-T_r<pair>.txt, trace-U_r<pair>.txt): the monitor is the qnx-safety-monitor process
that sent io-sock the most messages; the span runs from its first message's call to its last
message's return; exchanges are half its messages. Over the span, every guest thread's running time
in four classes -- idle (procnto's idle thread), io-sock, the monitor, the rest -- and the trace's
events, each per exchange. Per pair T - U; per quantity the median over pairs with the
distribution-free interval of widest coverage >= 95%.
"""
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guesttrace as gt  # noqa: E402
from sweep_report import interval  # noqa: E402

MIN_EXCHANGES = 300
KEYS = ("busy", "io", "mon", "rest", "idle", "events")
PROTO = {"T": "tcp", "U": "udp"}


def window(path):
    """(per-exchange figures, facts) for one trace window, or (None, facts)."""
    facts = {"exists": os.path.exists(path)}
    if not facts["exists"]:
        return None, facts
    text = open(path, encoding="utf-8", errors="replace").read()
    sec = gt.sections(text)
    facts["rc_ok"] = (all(sec["rc"].get(k) == 0 for k in ("tracelogger", "traceprinter", "pidin"))
                      and text.startswith("started pid ") and text.rstrip().endswith("end"))
    tr = gt.Trace(sec.get("traceprinter", ""))
    facts["buffers_ok"] = bool(tr.buffers) and tr.buffers_contiguous()
    facts["cpu0"] = tr.cpus() == [0]
    io = tr.pid_of("io-sock")
    mons = tr.pid_of("qnx-safety-monitor")
    if len(io) != 1 or not mons or tr.hz <= 0:
        facts["exchanges"] = 0
        return None, facts
    msgs = gt.messages(tr, io[0])
    by = {p: [m for m in msgs if m["client"][0] == p] for p in mons}
    mon = max(by, key=lambda p: len(by[p]))
    mm = by[mon]
    ex = len(mm) // 2
    facts["exchanges"] = ex
    if ex == 0:
        return None, facts
    t_start, t_end = mm[0]["t0"], mm[-1]["t5"]
    run = {"idle": 0, "io": 0, "mon": 0, "rest": 0}
    running, last, events = None, None, 0
    for t, _cpu, cls, name, args in tr.events:
        if t > t_end:
            break
        if t >= t_start:
            events += 1
            if running is not None and last is not None:
                pid, tid = running
                if pid == 1 and tr.threads.get(running, "").startswith("idle"):
                    c = "idle"
                elif pid == io[0]:
                    c = "io"
                elif pid == mon:
                    c = "mon"
                else:
                    c = "rest"
                run[c] += t - max(last, t_start)
        if cls == "THREAD" and name == "THRUNNING":
            m = re.search(r"pid:(\d+) tid:(\d+)", args)
            running = (int(m.group(1)), int(m.group(2))) if m else running
        last = t
    per = {k: tr.us(v) / ex for k, v in run.items()}
    per["busy"] = per["io"] + per["mon"] + per["rest"]
    per["events"] = events / ex
    return per, facts


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
    res, lat, problems, probe_problems = {}, {}, [], []
    for r in pairs:
        for kind in ("T", "U"):
            per, facts = window(os.path.join(out, "trace-%s_r%d.txt" % (kind, r)))
            good = (facts.get("exists") and facts.get("rc_ok") and facts.get("buffers_ok") and facts.get("cpu0")
                    and facts.get("exchanges", 0) >= MIN_EXCHANGES)
            if not good:
                problems.append("pair %d %s: %s" % (r, kind, facts))
            if per is not None:
                res[(kind, r)] = per
            lp = os.path.join(out, "lat-%s_r%d.json" % (kind, r))
            s = json.load(open(lp))["summary"] if os.path.exists(lp) else None
            if (not s or s.get("bad") != 0 or s.get("rejected_by_monitor") != 0 or s.get("proto") != PROTO[kind]
                    or (n_want is not None and s.get("n") != n_want)):
                probe_problems.append("pair %d %s: the probe's summary is missing or unclean" % (r, kind))
            else:
                lat[(kind, r)] = s["p50_ms"] * 1000.0
    rounds = [r for r in pairs if ("T", r) in res and ("U", r) in res]
    lat_d = [lat[("T", r)] - lat[("U", r)] for r in pairs if ("T", r) in lat and ("U", r) in lat]
    ok = {"M1": bool(pairs) and not problems,
          "M2": bool(lat_d) and st.median(lat_d) >= 10.0,
          "M3": bool(pairs) and not probe_problems}
    print("  pairs %d" % len(pairs))
    print("  M1 every window's trace is whole, one CPU, >= %d exchanges in the span -> %s"
          % (MIN_EXCHANGES, "ok" if ok["M1"] else "FAILED"))
    for msg in problems[:6]:
        print("     %s" % msg)
    print("  M2 the probe's p50 is >= 10 us longer for T than U under tracing: %s -> %s"
          % ("%+.2f us" % st.median(lat_d) if lat_d else "n/a", "ok" if ok["M2"] else "FAILED"))
    print("  M3 every window's probe clean, its own transport -> %s" % ("ok" if ok["M3"] else "FAILED"))
    for msg in probe_problems[:6]:
        print("     %s" % msg)
    if not rounds:
        return 0

    def verdict(v):
        failed = [m for m in ok if not ok[m]]
        return "VOID (%s failed)" % ", ".join(failed) if failed else v

    print("  per kind, median over windows of the per-exchange figures (us; events: count):")
    print("    kind " + " ".join("%8s" % k for k in KEYS) + "   probe p50")
    for kind in ("T", "U"):
        print("    %-4s " % kind + " ".join("%8.2f" % st.median(res[(kind, r)][k] for r in rounds) for k in KEYS)
              + "   %8.2f" % st.median(lat[(kind, r)] for r in rounds if (kind, r) in lat))

    def d(key):
        return [res[("T", r)][key] - res[("U", r)][key] for r in rounds]

    print("  differences T - U per exchange, paired within pair: median [interval], pairs > 0")
    meds = {}
    for k in KEYS:
        v = d(k)
        lo, hi, cov = interval(v)
        meds[k] = st.median(v)
        print("    %-7s %+8.2f [%+.2f, %+.2f] (%.1f%%), > 0 in %d/%d" % (k, meds[k], lo, hi, 100 * cov,
                                                                      sum(x > 0 for x in v), len(v)))
    lo, hi, cov = interval(lat_d)
    print("    probe   %+8.2f [%+.2f, %+.2f] (%.1f%%)  (the traced round trips)" % (st.median(lat_d), lo, hi, 100 * cov))
    share = meds["io"] / meds["busy"] if meds["busy"] > 0 else float("nan")
    print("  P1  the guest is busy >= 10 us longer per TCP exchange: %+.2f us -> %s"
          % (meds["busy"], verdict("HELD" if meds["busy"] >= 10 else "REFUTED")))
    print("  P2  io-sock accounts for >= 70%% of it: %+.2f of %+.2f us (%.0f%%) -> %s"
          % (meds["io"], meds["busy"], 100 * share,
             verdict("HELD" if meds["busy"] > 0 and meds["io"] >= 0.7 * meds["busy"] else "REFUTED")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
