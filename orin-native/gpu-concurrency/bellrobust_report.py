#!/usr/bin/env python3
"""bellrobust_report.py OUT -- run-bellrobust.sh's robustness matrix for the doorbell into the guest,
by the rule the harness's header fixed before any run (Phase 3b / A6, 2026-09-29). Functional: no
latency is read (times appear only to place ring windows and to scale the idle window's rate).

Each scenario Sn runs in its own boot per repeat r (label Sn_rr). scenarios.log has "<tag> rc=N
t0=NS t1=NS" per exchange set, "ring-<tag> rc=N" per ring set and, for S4, when msixcfg and the
MSI-X monitor were first seen; ring-<tag>.log has the ring window and, for an observer, the
doorbells that came back; kvm-<tag>-idle.json and kvm-<tag>-rings.json hold KVM's counters around
an idle window and around the rings.

A set with no line in scenarios.log never ran. M1 and M2 void a repeat outright; M3 to M8 (the
scenario's condition was really made, and every set it names ran) void only a repeat that would
otherwise pass, so a failure stands whether or not they held.
"""
import json
import os
import re
import sys

BOOT = {"S1": ("ifs-bell.bin", 1), "S2": ("ifs-bell.bin", 1), "S3": ("ifs-bell.bin", 1), "S4": ("ifs-bell.bin", 1),
        "S5": ("ifs-bell.bin", 1), "S6": ("ifs-robust.bin", 1), "S7": ("ifs-unmask-a.bin", 2),
        "S8": ("ifs-unmask-a.bin", 2)}
PRE = ("S1", "S2", "S3", "S5", "S7", "S8")
RINGS = {"S1": 500, "S2": 2000, "S4": 4000, "S7": 500, "S8": 2000}
MSIXCFG = re.compile(r"EventID 0 -> LPI 8193")      # msixcfg's success line, by a short token
# its_probe.c prints its information on stdout under these prefixes and every error on stderr
# under others ("its: msixcfg maps ..." is an error, "its: msixcfg: ..." the success line)
ERR = re.compile(r"(shm-kick: |its: (?!BASER|CBASER |CTLR |CWRITER |GITS 0x|msixcfg: |msixwait|selftest)"
                 r"|monitor: .*(failed|error))")
DELIVERY_PER_RING, OVERLAP = 2.0, 0.8


def main(argv):
    out = argv[0]
    sp = os.path.join(out, "stamp.json")
    stamp = json.load(open(sp)) if os.path.exists(sp) else {}
    repeats = stamp.get("repeats") or 0

    def jload(name):
        try:
            return json.load(open(os.path.join(out, name)))
        except (OSError, ValueError):
            return None

    def text(name):
        try:
            return open(os.path.join(out, name), encoding="utf-8", errors="replace").read()
        except OSError:
            return ""

    rcs, spans, seen = {}, {}, {}
    for ln in text("scenarios.log").splitlines():
        m = re.match(r"(\S+) rc=(\d+)(?: t0=(\d+) t1=(\d+))?\s*$", ln)
        if m:
            rcs[m.group(1)] = int(m.group(2))
            if m.group(3):
                spans[m.group(1)] = (int(m.group(3)), int(m.group(4)))
        m = re.match(r"(\S+) msixcfg_seen=(\S+) msix_monitor_seen=(\S+)", ln)
        if m:
            seen[m.group(1)] = tuple(None if v == "never" else int(v) for v in (m.group(2), m.group(3)))
    boots = {}
    for ln in text("boots.log").splitlines():
        m = re.match(r"(S\d_r\d+) image=(\S+) vectors=(\d)", ln)
        if m:
            boots[m.group(1)] = (m.group(2), int(m.group(3)))

    def ex_state(tag, n):
        """("missing" | "clean" | "bad", the probe's ivshmem peer id)"""
        if tag not in rcs:
            return "missing", None
        s = (jload("ex-%s.json" % tag) or {}).get("summary")
        if rcs[tag] != 0 or s is None:
            return "bad", None
        nt = s.get("notify") or {}
        ok = (s.get("n") == n and s.get("bad") == 0 and s.get("rejected_by_monitor") == 0
              and nt.get("exchanges") == n and nt.get("notifications") == n and nt.get("early_wakeups") == 0
              and nt.get("stray") == 0 and nt.get("eagain") == 0)
        return ("clean" if ok else "bad"), s.get("ivshm_peer")

    def ring_info(tag):
        t = text("ring-%s.log" % tag)
        w = re.search(r"ring: window (\d+) (\d+)", t)
        o = re.search(r"ring: observer: (\d+) doorbell", t)
        rang = re.search(r"ring: (\d+) rung", t)
        if "ring-" + tag not in rcs:
            state = "missing"
        elif rcs["ring-" + tag] == 0 and rang is not None and int(rang.group(1)) == RINGS[tag.split("_")[0]]:
            state = "clean"
        else:
            state = "bad"
        return {"state": state, "window": (int(w.group(1)), int(w.group(2))) if w else None,
                "answered": int(o.group(1)) if o else None}

    def rise(doc):
        """(kernel MMIO exits, ns) between a snapshot pair, or None"""
        try:
            return (doc["after"]["counters"]["mmio_exit_kernel"] - doc["before"]["counters"]["mmio_exit_kernel"],
                    doc["after"]["t_ns"] - doc["before"]["t_ns"])
        except (KeyError, TypeError):
            return None

    print("  repeats %d, one boot per scenario and repeat" % repeats)
    verdicts, errors = {}, set()
    for sc in sorted(BOOT):
        runs = []
        for r in range(1, repeats + 1):
            lab = "%s_r%d" % (sc, r)
            con = text("console-%s.log" % lab)
            errors.update(ln.strip()[:120] for ln in con.splitlines() if ERR.search(ln))
            void, bad, note, unshown = [], [], [], []   # unshown: M3-M8, which void only a would-be pass

            def need(state, what, unshown=unshown, bad=bad):
                if state == "missing":
                    unshown.append("M7 (%s never ran)" % what)
                elif state == "bad":
                    bad.append(what)

            b = boots.get(lab)
            pre = ex_state(lab + "-pre", 100)[0] if sc in PRE else "clean"
            if b is None or b != BOOT[sc]:
                void.append("M1 (%s)" % ("no boot came up" if b is None else "ran %s with %d vector(s)" % b))
            elif pre != "clean":
                void.append("M2 (%s)" % ("the opening check never ran" if pre == "missing"
                                         else "the doorbell was already broken"))
            if not void:
                ri = ring_info(lab) if sc in RINGS else None
                if ri is not None:
                    need(ri["state"], "ring set")
                if sc in ("S1", "S7") and ri["state"] == "clean":
                    if ri["answered"] != 0:
                        bad.append("observer %s doorbell(s)" % ri["answered"])
                    ring, idle = rise(jload("kvm-%s-rings.json" % lab)), rise(jload("kvm-%s-idle.json" % lab))
                    if ring is None or idle is None or idle[1] <= 0:
                        unshown.append("M3 (no KVM snapshots around the rings or the idle window)")
                    else:
                        background = idle[0] * ring[1] / idle[1]
                        if ring[0] - background < DELIVERY_PER_RING * RINGS[sc]:
                            unshown.append("M3 (rings not shown delivered: rise %d against %.0f from the idle rate)"
                                           % (ring[0], background))
                        else:
                            note.append("kernel MMIO rise %d, %.0f expected from the idle rate" % (ring[0], background))
                if sc in ("S2", "S8"):
                    need(ex_state(lab, 400)[0], "the doubled exchanges")
                    sp_ = spans.get(lab)
                    if sp_ is None or ri["window"] is None:
                        unshown.append("M5 (no ring window or probe span)")
                    else:
                        lo, hi = max(sp_[0], ri["window"][0]), min(sp_[1], ri["window"][1])
                        if hi - lo < OVERLAP * (sp_[1] - sp_[0]):
                            unshown.append("M5 (the rings covered %.0f%% of the probe)"
                                           % (100.0 * max(0, hi - lo) / (sp_[1] - sp_[0])))
                if sc == "S3":
                    peers = []
                    for c in range(1, 21):
                        st, peer = ex_state("%s-p%d" % (lab, c), 20)
                        need(st, "probe %d" % c)
                        if st == "clean":
                            peers.append(peer)
                    if len(peers) == 20 and len(set(peers)) != 20:
                        unshown.append("M4 (%d distinct peer ids of 20)" % len(set(peers)))
                if sc == "S4":
                    ms, bs = seen.get(lab, (None, None))
                    if ms is None or bs is None:
                        unshown.append("M6 (msixcfg or the MSI-X monitor was never seen during the rings)")
                    elif ri["window"] is None or not (ri["window"][0] < ms and ri["window"][1] > bs):
                        unshown.append("M6 (the ring window did not span msixcfg and the monitor's start)")
                if sc == "S5":
                    need(ex_state(lab + "-vlm", 100)[0], "the vlm exchanges")
                if sc == "S6":
                    for part in ("-msix", "-console"):
                        need(ex_state(lab + part, 100)[0], "the%s exchanges" % part.replace("-", " "))
                    if len(MSIXCFG.findall(con)) < 2:
                        unshown.append("M8 (msixcfg's success line seen %d time(s))" % len(MSIXCFG.findall(con)))
                if sc != "S6":
                    need(ex_state(lab + "-check", 100)[0], "the closing check")
            if not bad:
                void += unshown
            state = "VOID" if void else ("pass" if not bad else "FAIL")
            runs.append(state)
            print("    %s r%d %s%s%s" % (sc, r, state, "" if not (void or bad) else " (%s)" % ", ".join(void + bad),
                                       "" if not note else " [%s]" % "; ".join(note)))
        ran = [x for x in runs if x != "VOID"]
        if not ran:
            verdicts[sc] = "VOID (in every repeat)"
            continue
        if all(x == "pass" for x in ran):
            v = "HELD"
        elif any(x == "pass" for x in ran):
            v = "PARTIAL"
        else:
            v = "REFUTED"
        verdicts[sc] = v + ("" if len(ran) == len(runs) else " (%d of %d repeats ran)" % (len(ran), len(runs)))
    print("  console lines naming an error, any boot (unscored): %d" % len(errors))
    for e in sorted(errors)[:8]:
        print("     %s" % e)
    for sc in sorted(BOOT):
        print("  P%s  %s passes in every repeat -> %s" % (sc[1:], sc, verdicts[sc]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
