#!/usr/bin/env python3
"""tick_trace.py -- reduce an ftrace instance's scheduling, interrupt, softirq, workqueue
and timer events on QEMU's and the probe's cores to who or what held each core when, so
run-tick.sh can charge the time inside a window to the host's own work (Phase 3b / A6,
2026-09-25).

  reduce   the trace file on stdin. Writes one line per event, "seconds core KIND field",
      and nothing else. Exits 2 on lost events, a missing header or an unparsed line.
      The events and their lines:
        sched_switch             S comm pid   the task switched IN (spaces in comm as _,
                                              pid 0 as "idle")
        irq_handler_entry        I name       a hard interrupt's handler starts
        irq_handler_exit         i            ... and ends
        softirq_entry            Q action     a softirq vector starts (TIMER, SCHED, ...)
        softirq_exit             q            ... and ends
        workqueue_execute_start  W function   a work item starts in a kworker
        workqueue_execute_end    w            ... and ends
        timer_expire_entry       E function   a timer-wheel timer expires
        hrtimer_expire_entry     H function   an hrtimer expires (tick_sched_timer: the tick)

Contexts turns the reduced lines into, per core, a timeline of what held the core, the
innermost first: a hard interrupt (hardirq:NAME), else a softirq (softirq:ACTION), else a
work item in a kworker (work:FUNCTION), else the running task (task:COMM), where a task
the caller calls its own (QEMU's threads, the probe) is "own" and the idle task "idle".
"""
import bisect
import collections
import re
import sys

HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
LOST = re.compile(r"\[LOST \d+ EVENTS\]")
PREFIX = re.compile(r"^\s*(.+?)-(\d+)\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+(\w+):\s+(.*)$")
SWITCH = re.compile(r"prev_comm=(.*) prev_pid=(\d+) prev_prio=\S+ prev_state=(\S+) ==> "
                    r"next_comm=(.*) next_pid=(\d+) next_prio=\S+$")
EVENTS = ("sched_switch", "irq_handler_entry", "irq_handler_exit", "softirq_entry", "softirq_exit",
          "workqueue_execute_start", "workqueue_execute_end", "timer_expire_entry", "hrtimer_expire_entry")
FOREIGN = ("hardirq", "softirq", "work", "task")


def _one(ev, body):
    """(KIND, field) or None when the body does not parse."""
    if ev == "sched_switch":
        s = SWITCH.match(body)
        if not s:
            return None
        pid = int(s.group(5))
        comm = "idle" if pid == 0 else re.sub(r"\s+", "_", s.group(4).strip())
        return "S", "%s %d" % (comm, pid)
    if ev == "irq_handler_entry":
        m = re.search(r"irq=\d+ name=(\S+)", body)
        return ("I", m.group(1)) if m else None
    if ev == "irq_handler_exit":
        return ("i", "-") if re.search(r"irq=\d+ ret=", body) else None
    if ev in ("softirq_entry", "softirq_exit"):
        m = re.search(r"vec=\d+ \[action=(\w+)\]", body)
        if not m:
            return None
        return ("Q", m.group(1)) if ev == "softirq_entry" else ("q", "-")
    if ev in ("workqueue_execute_start", "workqueue_execute_end"):
        m = re.search(r"function (\S+)", body)
        if not m:
            return None
        return ("W", m.group(1)) if ev == "workqueue_execute_start" else ("w", "-")
    m = re.search(r"function=(\S+)", body)
    if not m:
        return None
    return ("E" if ev == "timer_expire_entry" else "H"), m.group(1)


def reduce(lines):
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
        got = _one(m.group(5), m.group(6))
        if got is None:
            return None, "unparsed %s at line %d" % (m.group(5), no)
        out.append("%s %s %s %s" % (m.group(4), m.group(3), got[0], got[1]))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return out, None


def read(path):
    """[(microseconds, core, KIND, field)] in file order (the trace's, time-sorted)."""
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split(" ", 3)
        if len(f) == 4:
            ev.append((float(f[0]) * 1e6, int(f[1]), f[2], f[3]))
    ev.sort(key=lambda x: x[0])
    return ev


class Contexts:
    """Per-core segments (start, end, label) of what held the core. own(core, comm, pid)
    says which tasks are the caller's own. Before a core's first switch its task is
    "unknown"; a core's last segment ends at its last event."""

    def __init__(self, ev, own):
        per = collections.defaultdict(list)
        for x in ev:
            per[x[1]].append(x)
        self.seg, self.starts = {}, {}
        for core, xs in per.items():
            task, cur, irq, sirq, work, segs = "unknown", None, [], [], {}, []
            prev = None
            for t, _, k, f in xs:
                if prev is not None and t > prev:
                    segs.append((prev, t, self._label(task, irq, sirq, work.get(cur))))
                prev = t
                if k == "S":
                    comm, pid = f.rsplit(" ", 1)
                    cur = int(pid)
                    task = "idle" if cur == 0 else ("own" if own(core, comm, cur) else "task:" + comm)
                elif k == "I":
                    irq.append(f)
                elif k == "i":
                    irq = irq[:-1]
                elif k == "Q":
                    sirq.append(f)
                elif k == "q":
                    sirq = sirq[:-1]
                elif k == "W":
                    work[cur] = f
                elif k == "w":
                    work.pop(cur, None)
            self.seg[core] = segs
            self.starts[core] = [s[0] for s in segs]

    @staticmethod
    def _label(task, irq, sirq, work):
        if irq:
            return "hardirq:" + irq[-1]
        if sirq:
            return "softirq:" + sirq[-1]
        if work is not None and task.startswith("task:kworker"):
            return "work:" + work
        return task

    def time(self, a, b, cores):
        """Counter {label: us} inside [a, b] on the given cores."""
        out = collections.Counter()
        for core in cores:
            segs = self.seg.get(core, [])
            i = max(0, bisect.bisect_right(self.starts.get(core, []), a) - 1)
            for s, e, lab in segs[i:]:
                if s >= b:
                    break
                o = min(e, b) - max(s, a)
                if o > 0:
                    out[lab] += o
        return out


def foreign(counter):
    """The part of a time() Counter that is the host's own work: every label but own,
    idle and unknown."""
    return {k: v for k, v in counter.items() if k.split(":")[0] in FOREIGN}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["reduce"]:
        print("usage: tick_trace.py reduce < trace", file=sys.stderr)
        return 2
    out, err = reduce(sys.stdin)
    if err:
        print("tick_trace: %s" % err, file=sys.stderr)
        return 2
    sys.stdout.write("".join(l + "\n" for l in out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
