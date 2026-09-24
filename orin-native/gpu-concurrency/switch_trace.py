#!/usr/bin/env python3
"""switch_trace.py -- reduce a sched_switch trace to the vCPU threads' switch-ins,
and count from them what KVM's vcpu_load does on each (Phase 3b / A6, 2026-09-24).

  reduce --map TID:IDX[,TID:IDX...]   the trace file on stdin; writes one
      "seconds core vcpu" line per switch-in of a mapped thread. Exits 2 if the
      header is missing, if it shows lost events (entries-in-buffer differs from
      entries-written), or if a switch-in names a thread not in the map (the
      filter should have kept it out). Nothing else from the trace -- no other
      process's name or pid -- is written: the reduction happens on the board, at
      capture time.
  count FILE [--window T0_NS T1_NS]   one reduced file; prints a JSON object.
      With --window, only switch-ins inside it count: the trace clock must then
      be "mono" (CLOCK_MONOTONIC), the clock m_kvm_snap stamps its t_ns with.
  check --sw FILE --kvm KVM.json --mode S|O
      one arm's liveness, inside the KVM snapshots' window. A dead or
      mis-filtered trace would read as "no flush", so it is refused (exit 2):
      every blocked vCPU that KVM wakes (halt_wakeup) is switched in, so the
      switch-ins must reach at least half of the wake-ups once there are 20.
      In an O arm, where each vCPU is pinned alone, there must be no migration,
      no flush condition, and each vCPU seen on one core only, not shared.

THE FLUSH CONDITION. Linux 5.15's kvm_arch_vcpu_load() keeps, per physical core,
the id of this VM's vCPU that last ran there (last_vcpu_ran). When a different
vCPU is loaded, it flushes the core's TLB and I-cache for the VM
(__kvm_flush_cpu_context). A switch-in of a vCPU thread stands for that load
here. That is an approximation. A switch-in while the thread is in QEMU's
userspace loads nothing until the thread re-enters KVM_RUN, normally on the same
core. The first switch-in on each core in a file has no known predecessor, so it
counts as unknown. Each vCPU's first switch-in counts as unknown for migrations.
"""
import argparse
import json
import re
import sys

LOST = re.compile(r"\[LOST \d+ EVENTS\]")
HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
# "<task>-<pid> [<cpu>] <flags> <seconds>: sched_switch: ... next_pid=<pid> ..."
# The task may contain spaces and dashes ("CPU 0/KVM-4242"); the flags column
# may be absent when irq-info is off.
LINE = re.compile(r"^\s*.+?-\d+\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+sched_switch:.*\snext_pid=(\d+)(?:\s|$)")


def parse_map(spec):
    m = {}
    for part in spec.split(","):
        tid, _, idx = part.partition(":")
        if not tid.isdigit() or not idx.isdigit():
            raise ValueError("bad --map entry %r (want TID:IDX)" % part)
        m[int(tid)] = int(idx)
    return m


def reduce(lines, tid_map):
    """(events, error). events: [(seconds_str, core, vcpu)] in trace order."""
    seen_header, events = False, []
    for no, line in enumerate(lines, 1):
        if LOST.search(line):
            return None, "lost events: a LOST line at line %d" % no
        h = HEADER.match(line)
        if h:
            seen_header = True
            if h.group(1) != h.group(2):
                return None, "lost events: entries-in-buffer %s, entries-written %s" % (h.group(1), h.group(2))
            continue
        if line.startswith("#") or "sched_switch:" not in line:
            continue
        m = LINE.match(line)
        if not m:
            # The line's text is not echoed: it names other processes.
            return None, "unparsed sched_switch line at line %d" % no
        nxt = int(m.group(3))
        if nxt not in tid_map:
            return None, "a switch-in of thread %d, which is not in the map" % nxt
        events.append((m.group(2), int(m.group(1)), tid_map[nxt]))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return events, None


def count(events):
    """events: [(seconds, core, vcpu)] in time order."""
    last_on_core, last_core_of = {}, {}
    out = {"switch_ins": 0, "per_vcpu": {}, "per_core": {},
           "flush_cond": 0, "same_vcpu": 0, "flush_unknown": 0,
           "migrations": 0, "stays": 0, "migr_unknown": 0}
    for _, core, vcpu in events:
        out["switch_ins"] += 1
        out["per_vcpu"][str(vcpu)] = out["per_vcpu"].get(str(vcpu), 0) + 1
        out["per_core"][str(core)] = out["per_core"].get(str(core), 0) + 1
        prev = last_on_core.get(core)
        if prev is None:
            out["flush_unknown"] += 1
        elif prev != vcpu:
            out["flush_cond"] += 1
        else:
            out["same_vcpu"] += 1
        last_on_core[core] = vcpu
        pc = last_core_of.get(vcpu)
        if pc is None:
            out["migr_unknown"] += 1
        elif pc != core:
            out["migrations"] += 1
        else:
            out["stays"] += 1
        last_core_of[vcpu] = core
    return out


def read_reduced(path, window=None):
    """window: (t0_ns, t1_ns) on the trace clock, or None for every line."""
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.split()
        if len(f) != 3:
            continue
        if window is not None and not (window[0] <= float(f[0]) * 1e9 <= window[1]):
            continue
        ev.append((f[0], int(f[1]), int(f[2])))
    ev.sort(key=lambda e: float(e[0]))
    return ev


def kvm_window(path):
    """(t0_ns, t1_ns, halt_wakeup delta) from an m_kvm_snap file."""
    d = json.load(open(path))
    b, a = d["before"], d["after"]
    return b["t_ns"], a["t_ns"], a["counters"]["halt_wakeup"] - b["counters"]["halt_wakeup"]


def check(sw_path, kvm_path, mode):
    """(result dict, list of problems) for one arm."""
    t0, t1, wakes = kvm_window(kvm_path)
    ev = read_reduced(sw_path, (t0, t1))
    c = count(ev)
    probs = []
    if wakes >= 20 and c["switch_ins"] < 0.5 * wakes:
        probs.append("%d switch-ins for %d KVM wake-ups: the trace missed vCPU switch-ins"
                     % (c["switch_ins"], wakes))
    cores_of = {}
    for _, core, vcpu in ev:
        cores_of.setdefault(vcpu, set()).add(core)
    if mode == "O":
        if c["migrations"] or c["flush_cond"]:
            probs.append("O arm with %d migration(s) and %d flush condition(s): the pinning did not hold"
                         % (c["migrations"], c["flush_cond"]))
        if any(len(v) != 1 for v in cores_of.values()):
            probs.append("O arm with a vCPU on more than one core")
        owned = [next(iter(v)) for v in cores_of.values() if len(v) == 1]
        if len(owned) != len(set(owned)):
            probs.append("O arm with two vCPUs on one core")
    c["kvm_halt_wakeup"] = wakes
    c["window_s"] = (t1 - t0) / 1e9
    c["cores_of"] = {str(k): sorted(v) for k, v in sorted(cores_of.items())}
    return c, probs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--map", required=True)
    c = sub.add_parser("count")
    c.add_argument("file")
    c.add_argument("--window", nargs=2, type=int, metavar=("T0_NS", "T1_NS"))
    k = sub.add_parser("check")
    k.add_argument("--sw", required=True)
    k.add_argument("--kvm", required=True)
    k.add_argument("--mode", required=True, choices=["S", "O"])
    a = ap.parse_args(argv)
    if a.cmd == "reduce":
        try:
            tid_map = parse_map(a.map)
        except ValueError as e:
            print("switch_trace: %s" % e, file=sys.stderr)
            return 2
        events, err = reduce(sys.stdin, tid_map)
        if err:
            print("switch_trace: %s" % err, file=sys.stderr)
            return 2
        for ts, core, vcpu in events:
            print("%s %d %d" % (ts, core, vcpu))
        return 0
    if a.cmd == "check":
        res, probs = check(a.sw, a.kvm, a.mode)
        print(json.dumps(res, sort_keys=True))
        for p in probs:
            print("switch_trace: %s" % p, file=sys.stderr)
        return 2 if probs else 0
    print(json.dumps(count(read_reduced(a.file, tuple(a.window) if a.window else None)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
