#!/usr/bin/env python3
"""tracectl_client.py HOST PORT SECS OUT STARTED -- ask a qnx-tracectl service for one kernel trace
(Phase 3b / A6, 2026-09-27; run-trace.sh).

Sends "trace SECS"; when the service answers "started pid P" it creates the file STARTED, so the
caller can start its load inside the trace; then it writes everything the service sends, up to
and including "end", to OUT. Exits 1 if the service refused, if the reply ends without "end", or
if a section (tracelogger, traceprinter, pidin) reports a non-zero rc.
"""
import re
import socket
import sys


def ok(text):
    """The reply's verdict: (True, "") or (False, why)."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("started pid "):
        return False, "no 'started' line: " + (lines[0] if lines else "empty reply")
    if lines[-1] != "end":
        return False, "the reply ends without 'end'"
    m = re.search(r"^logged rc (-?\d+) bytes (-?\d+)$", text, re.M)
    if not m or m.group(1) != "0" or int(m.group(2)) <= 0:
        return False, "tracelogger: " + (m.group(0) if m else "no 'logged' line")
    for name in ("tracelogger", "traceprinter", "pidin"):
        r = re.search(r"^=== %s rc (-?\d+)$" % name, text, re.M)
        if not r or r.group(1) != "0":
            return False, "section %s: %s" % (name, r.group(0) if r else "missing")
    return True, ""


def main(argv):
    host, port, secs, out, started = argv[0], int(argv[1]), int(argv[2]), argv[3], argv[4]
    s = socket.create_connection((host, port), timeout=10)
    s.sendall(("trace %d\n" % secs).encode())
    s.settimeout(secs + 120)
    buf, flagged = b"", False
    with open(out, "wb") as f:
        while True:
            c = s.recv(1 << 16)
            if not c:
                break
            f.write(c)
            if not flagged:
                buf += c
                if b"\n" in buf:
                    flagged = True
                    first = buf.split(b"\n", 1)[0].decode(errors="replace")
                    if not first.startswith("started pid "):
                        print("tracectl refused: " + first, file=sys.stderr)
                        return 1
                    open(started, "w").close()
    s.close()
    good, why = ok(open(out, encoding="utf-8", errors="replace").read())
    if not good:
        print("tracectl: " + why, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
