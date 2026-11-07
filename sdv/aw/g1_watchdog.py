#!/usr/bin/env python3
"""g1_watchdog.py -- gate G1's memory-floor stop on the host (sdv/aw). SDV Phase 8 WP8 Step B
(sdv/aw/prereg-g1g2.md, PR, sections 4 and 5). Standard library only, on the host's python3;
run-aw-g1.sh starts it on core 4, before the guest boots, never by a login.

    g1_watchdog.py --series FILE --stop-file FILE --scopes FILE --max-s N [--floor-kb KB]

Every second it reads MemAvailable from /proc/meminfo, which it holds open, and writes one line to the series, the gate's 1 s
series (T3 reads it):

    R CLOCK_MONOTONIC_NS WALL_NS KB

each line flushed, and fsynced every FSYNC_EVERY lines to request durable storage. An event is a line `E MONO WALL WORD DETAIL`,
fsynced at once; this does not bound data loss on a reset. Below the floor (716800 kB, design value; under T3's 1048576 kB) it
writes the stop file the harness's loop reads
before each drive and the event `stop`, then until it ends, once per spacing, in two threads of their own so that the series goes on
and neither holds the other: one kills every container labelled sdv.aw.run=g1 (`docker ps`, `docker kill`, each under a bound: a
container started after the first kill is caught by a later one); the other, from 5 s after the stop, writes 1 to cgroup.kill of
each scope on the harness's list (--scopes, NAME TAB DIRECTORY per line) that still exists, through `sudo -n tee`, because dockerd
sits on the same saturated cores and may not answer, and no docker call can delay it. It ends on SIGTERM or after --max-s, its
ceiling, so a harness that died cannot leave it behind for long.

It refuses to start (exit 2, before any file is made) with a floor at or above T3's threshold. The one exception is the rehearsal's
named override, G1_REHEARSAL_FLOOR_KB: when set it is the floor, for a host where the watchdog
could not fire otherwise; under VSS_HOST=orin it is refused. For the tests: QNX_MEMINFO_FILE overrides /proc/meminfo, as in
run-aw-suite.sh; --spacing-s and --cgroup-kill-after-s the two design values.

Does not demonstrate: that the host stays up under pressure (it runs on the host it guards, and a stall of core 4 stalls it);
that the kill reaches a container in time, or that a floor of this size is safe; a reading between two lines. It is the only
thing in the gate that stops anything, and it stops on a floor, not on a threshold.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

FLOOR_KB = 716800                       # 700 MiB, the design value (PR section 4)
T3_THRESHOLD_KB = 1048576               # T3's 1 GiB (PR section 5): the floor stays under it
SPACING_S = 1.0                         # PR section 4
CGROUP_KILL_AFTER_S = 5.0               # dockerd may not answer on saturated cores: the kernel's own kill after this long
FSYNC_EVERY = 10                        # request durable storage at this design spacing
LABEL = "sdv.aw.run=g1"
DOCKER_BOUND_S = 10                     # one docker call; a wedged dockerd must not hold the kill thread for long
SUDO_BOUND_S = 10
JOIN_S = 2
OVERRIDE = "G1_REHEARSAL_FLOOR_KB"


class Series:
    """The series file: one line per read, flushed; fsynced every FSYNC_EVERY lines; an event at once."""

    def __init__(self, path: str) -> None:
        self.f = open(path, "a", encoding="ascii", newline="\n")
        self.n = 0
        self.lock = threading.Lock()            # the kill's thread writes its events too

    def reading(self, mono: int, wall: int, kb: int) -> None:
        with self.lock:
            self.f.write("R %d %d %d\n" % (mono, wall, kb))
            self.f.flush()
            self.n += 1
            if self.n % FSYNC_EVERY == 0:
                os.fsync(self.f.fileno())

    def event(self, mono: int, wall: int, word: str, detail: str = "") -> None:
        with self.lock:
            if self.f.closed:                   # a kill's thread that outlived the end's bound
                return
            self.f.write(("E %d %d %s %s" % (mono, wall, word, detail)).rstrip() + "\n")
            self.f.flush()
            os.fsync(self.f.fileno())

    def close(self) -> None:
        with self.lock:
            self.f.flush()
            os.fsync(self.f.fileno())
            self.f.close()


def mem_available(f) -> Optional[int]:
    """MemAvailable in kB from the held-open file, None when it holds none."""
    f.seek(0)
    for ln in f.read().splitlines():
        c = ln.split()
        if len(c) >= 2 and c[0] == "MemAvailable:" and c[1].isdigit():
            return int(c[1])
    return None


def floor_of(asked: int) -> Tuple[Optional[int], str]:
    """(the floor, the refusal when there is one)."""
    text = os.environ.get(OVERRIDE)
    if text is not None:
        if os.environ.get("VSS_HOST") == "orin":
            return None, "%s is refused under VSS_HOST=orin: the override is the rehearsal's (spec.md section 7)" % OVERRIDE
        if not text.isdigit() or int(text) <= 0:
            return None, "%s='%s' is not a whole number of kB" % (OVERRIDE, text)
        return int(text), ""
    if asked >= T3_THRESHOLD_KB:
        return None, "the floor %d kB is at or above T3's threshold %d kB: the gate's reading would never be reached" % (asked, T3_THRESHOLD_KB)
    return asked, ""


def scopes_of(path: str) -> List[Tuple[str, str]]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                name, tab, d = ln.rstrip("\n").partition("\t")
                if tab and d:
                    out.append((name, d))
    except OSError:
        pass
    return out


def _run(argv: List[str], bound: float, stdin: Optional[bytes] = None) -> Tuple[int, str]:
    try:
        p = subprocess.run(argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=bound)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, p.stdout.decode("ascii", "replace")


def docker_round(series: Series) -> None:
    """One round of the kill by label."""
    rc, out = _run(["docker", "ps", "-q", "--filter", "label=%s" % LABEL], DOCKER_BOUND_S)
    ids = out.split() if rc == 0 else []
    if ids:
        _run(["docker", "kill"] + ids, DOCKER_BOUND_S)
        series.event(time.monotonic_ns(), time.time_ns(), "docker-kill", " ".join(ids))


def cgroup_round(series: Series, scopes_file: str) -> None:
    """One round of the kernel's own kill: the cgroup of each listed scope that still exists."""
    for name, d in scopes_of(scopes_file):
        p = os.path.join(d, "cgroup.kill")
        if os.path.exists(p):
            rc, _o = _run(["sudo", "-n", "tee", p], SUDO_BOUND_S, stdin=b"1\n")
            series.event(time.monotonic_ns(), time.time_ns(), "cgroup-kill", "%s exit=%d" % (name, rc))


def docker_killer(series: Series, spacing: float, done: threading.Event) -> None:
    """The kill by label's thread: keeps killing until the watchdog ends. A docker that hangs holds this thread and nothing else."""
    while not done.is_set():
        docker_round(series)
        done.wait(spacing)


def cgroup_killer(series: Series, scopes_file: str, spacing: float, after: float, done: threading.Event) -> None:
    """The cgroup kill's thread: after its wait, every spacing until the watchdog ends. It calls no docker, because the docker that
    does not answer is the case it exists for."""
    if done.wait(after):
        return
    while not done.is_set():
        cgroup_round(series, scopes_file)
        done.wait(spacing)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--series", required=True)
    ap.add_argument("--stop-file", required=True)
    ap.add_argument("--scopes", required=True)
    ap.add_argument("--max-s", type=float, required=True)
    ap.add_argument("--floor-kb", type=int, default=FLOOR_KB)
    ap.add_argument("--spacing-s", type=float, default=SPACING_S)
    ap.add_argument("--cgroup-kill-after-s", type=float, default=CGROUP_KILL_AFTER_S)
    a = ap.parse_args(argv)
    floor, why = floor_of(a.floor_kb)
    if floor is None:
        print("g1_watchdog: refused: %s" % why, file=sys.stderr, flush=True)
        return 2
    meminfo = open(os.environ.get("QNX_MEMINFO_FILE", "/proc/meminfo"), encoding="ascii", errors="replace")
    series = Series(a.series)
    ended: List[int] = []                       # a plain flag: a handler must not take an Event's lock the main thread may hold
    signal.signal(signal.SIGTERM, lambda *_: ended.append(1))
    series.event(time.monotonic_ns(), time.time_ns(), "start", "floor_kb=%d" % floor)
    fired: List[threading.Thread] = []
    done = threading.Event()
    last_end = time.monotonic() + a.max_s
    tick = time.monotonic()
    while not ended and time.monotonic() < last_end:
        mono, wall = time.monotonic_ns(), time.time_ns()
        kb = mem_available(meminfo)
        if kb is None:
            series.event(mono, wall, "unreadable", "MemAvailable")
        else:
            series.reading(mono, wall, kb)
            if kb < floor and not fired:
                series.event(mono, wall, "stop", "floor_kb=%d avail_kb=%d" % (floor, kb))
                with open(a.stop_file, "w", encoding="ascii") as f:
                    f.write("stop %d %d floor_kb=%d avail_kb=%d\n" % (mono, wall, floor, kb))
                    f.flush()
                    os.fsync(f.fileno())
                fired = [threading.Thread(target=docker_killer, args=(series, a.spacing_s, done), daemon=True),
                         threading.Thread(target=cgroup_killer, args=(series, a.scopes, a.spacing_s, a.cgroup_kill_after_s, done), daemon=True)]
                for t in fired:
                    t.start()
        tick += a.spacing_s
        time.sleep(max(0.0, tick - time.monotonic()))
    done.set()
    join_end = time.monotonic() + JOIN_S
    for t in fired:
        t.join(max(0.0, join_end - time.monotonic()))   # daemon threads: a wedged dockerd does not hold the end
    series.event(time.monotonic_ns(), time.time_ns(), "end")
    series.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
