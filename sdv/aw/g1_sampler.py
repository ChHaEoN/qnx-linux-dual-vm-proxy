#!/usr/bin/env python3
"""g1_sampler.py -- gate G1's 5 s sampler on the host (sdv/aw). SDV Phase 8 WP8 Step B
(sdv/aw/prereg-g1g2.md, PR, section 4). Standard library only, on the host's python3; run-aw-g1.sh
starts it on core 4, before the guest boots, never by a login.

    g1_sampler.py --out FILE --scopes FILE --max-s N

Every 5 s, one JSON line per read, each with its own time ({"mono_ns", "wall_ns", "what", ...}): meminfo, vmstat, stat (per-core
CPU), docker_stats (with its exit, under a bound: a wedged dockerd delays the next read and stops nothing), and memory_events for
each scope on the harness's list (--scopes, NAME TAB DIRECTORY per line) that still exists. It ends on SIGTERM or after --max-s, its
ceiling. For the tests QNX_MEMINFO_FILE, QNX_VMSTAT_FILE and QNX_STAT_FILE override the three files, as in run-aw-suite.sh, and
--spacing-s the spacing.

INFORMATION ONLY. No item of the gate reads this file; a gap in it is reported and is no instrument's failure (PR section 4).

Does not demonstrate: anything between two reads, or any figure's cause. Its own load (docker stats above all) is recorded by
being in the record, not removed.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

SPACING_S = 5.0                         # PR section 4
DOCKER_BOUND_S = 30
SLICE_S = 0.2                           # how late a SIGTERM may be seen between two rounds


def read_text(path: str) -> str:
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def scopes_of(path: str) -> List[Tuple[str, str]]:
    out = []
    for ln in read_text(path).splitlines():
        name, tab, d = ln.partition("\t")
        if tab and d:
            out.append((name, d))
    return out


def docker_stats() -> Dict[str, Any]:
    try:
        p = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=DOCKER_BOUND_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exit": None, "error": type(exc).__name__}
    return {"exit": p.returncode, "text": p.stdout.decode("ascii", "replace")}


def one_round(out: Any, scopes: str) -> None:
    def line(what: str, **kw: Any) -> None:
        out.write(json.dumps({"mono_ns": time.monotonic_ns(), "wall_ns": time.time_ns(), "what": what, **kw}) + "\n")
        out.flush()

    line("meminfo", text=read_text(os.environ.get("QNX_MEMINFO_FILE", "/proc/meminfo")))
    line("vmstat", text=read_text(os.environ.get("QNX_VMSTAT_FILE", "/proc/vmstat")))
    line("stat", text=read_text(os.environ.get("QNX_STAT_FILE", "/proc/stat")))
    line("docker_stats", **docker_stats())
    for name, d in scopes_of(scopes):
        p = os.path.join(d, "memory.events")
        if os.path.exists(p):
            line("memory_events", name=name, text=read_text(p))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--scopes", required=True)
    ap.add_argument("--max-s", type=float, required=True)
    ap.add_argument("--spacing-s", type=float, default=SPACING_S)
    a = ap.parse_args(argv)
    ended: List[int] = []                       # a plain flag: a handler must not take a lock the main thread may hold
    signal.signal(signal.SIGTERM, lambda *_: ended.append(1))
    last_end = time.monotonic() + a.max_s
    tick = time.monotonic()
    with open(a.out, "a", encoding="ascii", newline="\n") as out:
        while not ended and time.monotonic() < last_end:
            one_round(out, a.scopes)
            tick = max(tick + a.spacing_s, time.monotonic())
            while not ended and time.monotonic() < tick:
                time.sleep(min(SLICE_S, max(0.0, tick - time.monotonic())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
