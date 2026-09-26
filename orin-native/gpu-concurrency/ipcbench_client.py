#!/usr/bin/env python3
"""ipcbench_client.py HOST PORT COMMAND... -- send one command to a qnx-ipcbench service (Phase 3b /
A6, 2026-09-26; run-ipcbench.sh) and print its reply up to and including "done". Exits 1 if the
reply ends without "done" or holds an "error" line."""
import socket
import sys


def main(argv):
    host, port, cmd = argv[0], int(argv[1]), " ".join(argv[2:])
    s = socket.create_connection((host, port), timeout=120)
    s.sendall((cmd + "\n").encode())
    buf = b""
    while not buf.endswith(b"done\n"):
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    text = buf.decode(errors="replace")
    sys.stdout.write(text)
    return 0 if text.endswith("done\n") and not any(l.startswith("error") for l in text.splitlines()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
