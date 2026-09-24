#!/usr/bin/env python3
"""hostact_trace.py -- reduce an ftrace of the host's own activity on QEMU's cores
to what can be charged to one exchange: interrupt, softirq and IPI handlers that ran
while one of QEMU's threads held the core, and the time a QEMU thread spent
preempted (Phase 3b / A6, 2026-09-24; run-tailhost.sh).

  reduce --map ROLE:PID[,ROLE:PID...]   the trace file on stdin (roles m, v0, v1 as
      in blockpath_trace.py, and q for any other QEMU thread, repeatable). Writes one
      line per event, "seconds core EVENT fields", and nothing else: no other
      process's name or pid, no kernel address. Exits 2 on lost events, a missing
      header or an unparsed line. The events, and what each line keeps:
        HE irq name       irq_handler_entry    a device interrupt's handler starts
        HX irq            irq_handler_exit
        SE vec action     softirq_entry        a softirq starts (TIMER, RCU, NET_RX...)
        SX vec action     softirq_exit
        PE kind           ipi_entry            an IPI's handler starts (kind: its text,
        PX kind           ipi_exit               spaces as _, e.g. Function_call_interrupts)
        SW prev state next  sched_switch       prev and next are roles: m, v0, v1, q,
                                               idle, or for anyone else a class of
                                               kernel thread (kw kworker, ks ksoftirqd,
                                               rcu, mg migration) or o; state is
                                               prev_state (R, R+, S, D, ...)
        TE function jiffies  timer_expire_entry  a timer_list callback runs, at jiffies

THE CHARGE of a window [a, b] (an exchange's T0 to its reply out):
  handler time  every HE..HX, SE..SX and PE..PX interval on any core, clipped to the
                window, counted only while the core's current task (its last SW's
                next) is one of QEMU's threads (m, v0, v1, q). Time nested in
                another handler is counted once, as the inner one's: an IPI arrives
                inside an interrupt named IPI (arm64, found on the board), and an
                interrupt or IPI can land inside a softirq.
  preempted     every interval from a switch OUT of m, v0 or v1 in state R or R+
                to that thread's next switch IN, clipped to the window.
  unknown       handler time on a core whose current task is not yet known (no SW
                seen on it since the trace began); reported, never charged.
"""
import argparse
import bisect
import re
import sys
from collections import defaultdict

HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
LOST = re.compile(r"\[LOST \d+ EVENTS\]")
PREFIX = re.compile(r"^\s*(.+?)-(\d+)\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+(\w+):\s+(.*)$")
EVENTS = ("irq_handler_entry", "irq_handler_exit", "softirq_entry", "softirq_exit", "ipi_entry", "ipi_exit",
          "sched_switch", "timer_expire_entry")
OWN = ("m", "v0", "v1", "q")
MAXLEN = 20000.0            # us: a handler or a preemption longer than this is not looked back for


def parse_map(spec):
    m = {}
    for part in spec.split(","):
        role, _, pid = part.partition(":")
        if role not in OWN or not pid.isdigit():
            raise ValueError("bad --map entry %r (want m|v0|v1|q:PID)" % part)
        if role != "q" and role in m.values():
            raise ValueError("role %s given twice" % role)
        m[int(pid)] = role
    return m


def klass(pid, comm, pid_role):
    if pid in pid_role:
        return pid_role[pid]
    if pid == 0:
        return "idle"
    for pre, k in (("kworker", "kw"), ("ksoftirqd", "ks"), ("rcu", "rcu"), ("migration", "mg")):
        if comm.startswith(pre):
            return k
    return "o"


SWITCH = re.compile(r"prev_comm=(.*) prev_pid=(\d+) prev_prio=\S+ prev_state=(\S+) ==> "
                    r"next_comm=(.*) next_pid=(\d+) next_prio=\S+$")


def reduce(lines, pid_role):
    """(list of reduced lines, error)."""
    seen_header, out = False, []
    for no, line in enumerate(lines, 1):
        if LOST.search(line):
            return None, "lost events: a LOST line at line %d" % no
        h = HEADER.match(line)
        if h:
            seen_header = True
            if h.group(1) != h.group(2):
                return None, "lost events: entries-in-buffer %s, entries-written %s" % (h.group(1), h.group(2))
            continue
        if line.startswith("#") or not line.strip():
            continue
        m = PREFIX.match(line.rstrip("\n"))
        if not m or m.group(5) not in EVENTS:
            return None, "unparsed line at line %d" % no      # its text names other processes: not echoed
        core, ts, ev, body = m.group(3), m.group(4), m.group(5), m.group(6)
        if ev == "irq_handler_entry":
            mm = re.match(r"irq=(\d+) name=(.+?)\s*$", body)     # names may hold spaces
            if not mm:
                return None, "unparsed irq_handler_entry at line %d" % no
            out.append("%s %s HE %s %s" % (ts, core, mm.group(1), re.sub(r"\s+", "_", mm.group(2))))
        elif ev == "irq_handler_exit":
            mm = re.match(r"irq=(\d+) ", body)
            if not mm:
                return None, "unparsed irq_handler_exit at line %d" % no
            out.append("%s %s HX %s" % (ts, core, mm.group(1)))
        elif ev in ("softirq_entry", "softirq_exit"):
            mm = re.match(r"vec=(\d+) \[action=(\w+)\]", body)
            if not mm:
                return None, "unparsed %s at line %d" % (ev, no)
            out.append("%s %s %s %s %s" % (ts, core, "SE" if ev == "softirq_entry" else "SX",
                                           mm.group(1), mm.group(2)))
        elif ev in ("ipi_entry", "ipi_exit"):
            mm = re.match(r"\((.+)\)\s*$", body)
            if not mm:
                return None, "unparsed %s at line %d" % (ev, no)
            out.append("%s %s %s %s" % (ts, core, "PE" if ev == "ipi_entry" else "PX",
                                        re.sub(r"\s+", "_", mm.group(1).strip())))
        elif ev == "sched_switch":
            mm = SWITCH.match(body)
            if not mm:
                return None, "unparsed sched_switch at line %d" % no
            prev = klass(int(mm.group(2)), mm.group(1), pid_role)
            nxt = klass(int(mm.group(5)), mm.group(4), pid_role)
            out.append("%s %s SW %s %s %s" % (ts, core, prev, mm.group(3), nxt))
        else:  # timer_expire_entry
            fn = re.search(r"function=(\S+)", body)
            now = re.search(r"now=(\d+)", body)
            if not fn or not now:
                return None, "unparsed timer_expire_entry at line %d" % no
            out.append("%s %s TE %s %s" % (ts, core, fn.group(1), now.group(1)))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return out, None


def read(path):
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.split()
        if len(f) >= 3:
            ev.append((float(f[0]) * 1e6, int(f[1]), f[2], f[3:]))   # microseconds
    ev.sort(key=lambda e: e[0])
    return ev


class Activity:
    """The reduced events of one round, indexed for charging windows."""

    def __init__(self, ev):
        self.cur = defaultdict(lambda: ([], []))        # core -> (times, roles) of switches in
        self.hand = defaultdict(list)                   # core -> [(start, end, class, key)]
        self.pre = []                                   # [(start, end, role)]
        self.timers = []                                # [(t, function, jiffies)]
        open_h = {}                                     # (core, class) -> (start, key)
        open_p = {}                                     # role -> start of its preemption
        for t, core, e, f in ev:
            if e == "SW":
                prev, state, nxt = f[0], f[1], f[2]
                ts, rs = self.cur[core]
                ts.append(t)
                rs.append(nxt)
                if prev in ("m", "v0", "v1") and state.startswith("R"):
                    open_p[prev] = t
                if nxt in open_p:
                    self.pre.append((open_p.pop(nxt), t, nxt))
            elif e in ("HE", "SE", "PE"):
                cls = {"HE": "irq", "SE": "softirq", "PE": "ipi"}[e]
                key = f[1] if e in ("HE", "SE") else f[0]
                open_h[(core, cls)] = (t, key)
            elif e in ("HX", "SX", "PX"):
                cls = {"HX": "irq", "SX": "softirq", "PX": "ipi"}[e]
                o = open_h.pop((core, cls), None)
                if o is not None:
                    self.hand[core].append((o[0], t, cls, o[1]))
            elif e == "TE":
                self.timers.append((t, f[0], int(f[1])))
        for core in self.hand:
            self.hand[core].sort()
        self.starts = {c: [h[0] for h in hs] for c, hs in self.hand.items()}
        self.pre.sort()
        self.pre_starts = [p[0] for p in self.pre]

    def role_at(self, core, t):
        ts, rs = self.cur[core]
        i = bisect.bisect_right(ts, t) - 1
        return rs[i] if i >= 0 else None

    def _near(self, starts, items, a, b):
        i = bisect.bisect_left(starts, a - MAXLEN)
        j = bisect.bisect_left(starts, b)
        return [x for x in items[i:j] if x[1] > a]

    def charge(self, a, b):
        """{'irq': us, 'softirq': us, 'ipi': us, 'preempted': us, 'unknown': us, 'keys': {key: us}}."""
        out = {"irq": 0.0, "softirq": 0.0, "ipi": 0.0, "preempted": 0.0, "unknown": 0.0}
        keys = defaultdict(float)
        for core, hs in self.hand.items():
            near = self._near(self.starts[core], hs, a, b)
            inner = {"ipi": [], "irq": _merge([(s, e) for s, e, c, _ in near if c == "ipi"]),
                     "softirq": _merge([(s, e) for s, e, c, _ in near if c != "softirq"])}
            for s, e, cls, key in near:
                lo, hi = max(s, a), min(e, b)
                if hi <= lo:
                    continue
                # Time nested in it is the inner handler's, counted once: an IPI arrives
                # inside an interrupt named IPI (arm64), and an interrupt can land in a softirq.
                span = hi - lo - sum(max(0.0, min(hi, te_) - max(lo, ts_)) for ts_, te_ in inner[cls])
                role = self.role_at(core, s)
                if role is None:
                    out["unknown"] += span
                elif role in OWN:
                    out[cls] += span
                    keys["%s:%s" % (cls, key)] += span
        for s, e, role in self._near(self.pre_starts, self.pre, a, b):
            lo, hi = max(s, a), min(e, b)
            if hi > lo:
                out["preempted"] += hi - lo
                keys["preempted:%s" % role] += hi - lo
        out["keys"] = dict(keys)
        return out

    def known_from(self, cores):
        """The time from which every one of the cores has a known current task."""
        firsts = [self.cur[c][0][0] for c in cores if self.cur[c][0]]
        return max(firsts) if len(firsts) == len(cores) else None


def _merge(iv):
    """The union of intervals, as sorted disjoint intervals."""
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--map", required=True)
    a = ap.parse_args(argv)
    try:
        pid_role = parse_map(a.map)
    except ValueError as e:
        print("hostact_trace: %s" % e, file=sys.stderr)
        return 2
    out, err = reduce(sys.stdin, pid_role)
    if err:
        print("hostact_trace: %s" % err, file=sys.stderr)
        return 2
    sys.stdout.write("".join(l + "\n" for l in out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
