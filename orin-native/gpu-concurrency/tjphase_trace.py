#!/usr/bin/env python3
"""tjphase_trace.py -- reduce an ftrace of the probe's requests and the thermal
zones' reads to the two things run-tjphase.sh needs (Phase 3b / A6, 2026-09-24).

  reduce   the trace file on stdin. Writes one line per event, "seconds core EVENT
      field", and nothing else. Exits 2 on lost events, a missing header, an
      unparsed line or a frame on another device. The events:
        X len     net_dev_xmit on tap-qnx    a frame into the guest's tap
        T zone    thermal_temperature        a thermal zone was read (its type)
"""
import re
import sys

HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
LOST = re.compile(r"\[LOST \d+ EVENTS\]")
PREFIX = re.compile(r"^\s*(.+?)-(\d+)\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+(\w+):\s+(.*)$")


def reduce(lines, tap="tap-qnx"):
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
        if not m or m.group(5) not in ("net_dev_xmit", "thermal_temperature"):
            return None, "unparsed line at line %d" % no      # its text names other processes: not echoed
        core, ts, ev, body = m.group(3), m.group(4), m.group(5), m.group(6)
        if ev == "net_dev_xmit":
            dev = re.search(r"dev=(\S+)", body)
            ln = re.search(r"len=(\d+)", body)
            if not dev or not ln:
                return None, "unparsed net_dev_xmit at line %d" % no
            if dev.group(1) != tap:
                return None, "a frame on a device other than %s at line %d: the filter failed" % (tap, no)
            out.append("%s %s X %s" % (ts, core, ln.group(1)))
        else:
            z = re.search(r"thermal_zone=(\S+)", body)
            if not z:
                return None, "unparsed thermal_temperature at line %d" % no
            out.append("%s %s T %s" % (ts, core, z.group(1)))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return out, None


def read(path):
    """[(microseconds, event, field)], sorted."""
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.split()
        if len(f) >= 4:
            ev.append((float(f[0]) * 1e6, f[2], f[3]))
    ev.sort()
    return ev


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["reduce"]:
        print("usage: tjphase_trace.py reduce < trace", file=sys.stderr)
        return 2
    out, err = reduce(sys.stdin)
    if err:
        print("tjphase_trace: %s" % err, file=sys.stderr)
        return 2
    sys.stdout.write("".join(l + "\n" for l in out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
