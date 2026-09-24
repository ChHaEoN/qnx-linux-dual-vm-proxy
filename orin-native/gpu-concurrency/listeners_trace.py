#!/usr/bin/env python3
"""listeners_trace.py -- reduce an ftrace instance's sched_switch events, every core, to
who ran where and when, so run-listeners.sh can charge CPU time to each task inside a
window (Phase 3b / A6, 2026-09-24).

  reduce   the trace file on stdin. Writes one line per switch, "seconds core S comm
      pid": the task switched IN on that core (comm with spaces as _, pid 0 as the
      idle task "idle"). Exits 2 on lost events, a missing header or an unparsed line.
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
        if not m or m.group(5) != "sched_switch":
            return None, "unparsed line at line %d" % no
        s = SWITCH.match(m.group(6))
        if not s:
            return None, "unparsed sched_switch at line %d" % no
        pid = int(s.group(5))
        comm = "idle" if pid == 0 else re.sub(r"\s+", "_", s.group(4).strip())
        out.append("%s %s S %s %d" % (m.group(4), m.group(3), comm, pid))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return out, None


def read(path):
    """[(microseconds, core, comm, pid)], sorted."""
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.split()
        if len(f) >= 5 and f[2] == "S":
            ev.append((float(f[0]) * 1e6, int(f[1]), f[3], int(f[4])))
    ev.sort()
    return ev


class Runs:
    """Per-core run intervals (start, end, comm, pid) from the switch-in events; the
    last task on a core runs to the core's last event."""

    def __init__(self, ev):
        per = collections.defaultdict(list)
        for t, core, comm, pid in ev:
            per[core].append((t, comm, pid))
        self.iv = {}
        for core, xs in per.items():
            self.iv[core] = [(a[0], b[0], a[1], a[2]) for a, b in zip(xs, xs[1:])]
        self.starts = {c: [x[0] for x in iv] for c, iv in self.iv.items()}

    def cpu(self, a, b, skip=lambda comm, pid: comm == "idle"):
        """{(comm, pid, core): us} of CPU time inside [a, b]."""
        out = collections.Counter()
        for core, iv in self.iv.items():
            i = max(0, bisect.bisect_right(self.starts[core], a) - 1)
            for s, e, comm, pid in iv[i:]:
                if s >= b:
                    break
                o = min(e, b) - max(s, a)
                if o > 0 and not skip(comm, pid):
                    out[(comm, pid, core)] += o
        return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["reduce"]:
        print("usage: listeners_trace.py reduce < trace", file=sys.stderr)
        return 2
    out, err = reduce(sys.stdin)
    if err:
        print("listeners_trace: %s" % err, file=sys.stderr)
        return 2
    sys.stdout.write("".join(l + "\n" for l in out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
