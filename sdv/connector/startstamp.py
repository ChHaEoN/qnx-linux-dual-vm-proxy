"""startstamp.py -- the twin connector's start spacing, held on the device (sdv/connector; SDV Phase 4; prep gap i).

Standard library only. With the spool record (spool.py) this is one of the two files
the connector writes, and the only one it reads back.

WHY. The limiter bounds one process (limiter.py): its windows are new in every process. A start costs a `config` get,
a first `vss` document and a `config` report, and a stop a last document: four shadow publishes a cycle, however
short the process lived. Twelve processes a second apart, each far inside its own cap of 10 in 300 s, are 48 shadow
publishes in twelve seconds. So a start within limits.START_SPACING_S (120 s) of the previous start is refused before
anything is opened, and what a restart policy, a crash loop or a hasty hand can cause on one spool directory is at
most limits.starts_per_window() starts in any closed 300 s.

HOW. mark(DIRECTORY, wall_ms) is called once, first thing in a start (connector.Connector.start):
    no stamp there                  the first start on this directory: the stamp is written, the start goes on.
    a stamp 120 s old, or older     the stamp is written anew, the start goes on. Exactly 120 s old passes.
    a younger stamp                 StartRefused("spacing", what is left of the 120 s). The stamp stays as it is: a
                                    refused start is no start, so a loop of refused starts does not push its own
                                    end away.
    a stamp from the future         The wall clock was set back, or something else wrote the file.
                                    StartRefused("clock", 120), and the stamp is written anew with this moment: the
                                    refusals end 120 s from now, not when the clock has caught up.
    a file that is no stamp         The same: StartRefused("stamp", 120), written anew.
    a directory that cannot be      StartRefused("unwritable", None): no stamp, no start. The connector does not run
      read or written               without the record that spaces its starts; waiting does not help.
"A file that is no stamp" is a file that could be READ and holds something else. Three things are "cannot be read or
written" instead, and nothing is written anew over them: a stamp that is a symbolic link (it is opened O_NOFOLLOW and
never followed, wherever it points), a stamp that may not be read (mode 000), and a temporary name
(.started.json.tmp) that is a directory. Each refuses every start as "unwritable", with no time to wait for, until
somebody takes it away: the connector does not remove what it did not write.
Everything is compared in whole milliseconds, as integers: nothing is rounded, so there is no side to round to.

THE STAMP is DIRECTORY/started.json, at most limits.START_STAMP_MAX_BYTES, one field:

    {"started_ms": <the host's wall clock at the start, in milliseconds since the epoch>}

written by write-then-rename, as the spool record is. It lies beside the spool record because that directory is the
one place the connector can write (design manifest-classes.md, section 6: the only writable host path it has). The
updater reads desired.json there and nothing else. The stamp holds a time and nothing of what was sent or asked for.

THE CLOCK is the host's wall clock: the only one that two processes, two containers and two boots share. A wall clock
stepped forward by 120 s or more between two starts lets the second one through early, once per step; one stepped
back is the "from the future" row above.

Does not demonstrate:
  * anything about a start on another spool directory. Each replay of the stack has its own, so there the stack's own
    rule has to refuse (WP3; limits.py says who holds what);
  * two starts at the same instant: the check and the write are two steps, and both processes may pass;
  * a wall clock that steps forward, a spool directory on a file system that does not survive a reboot (the design's
    tmpfs: the first start after a boot finds no stamp), or a file somebody removes;
  * that the breaker's thresholds sit above what three starts in one window can send (WP5).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import limits

FILE = "started.json"
TMP = ".started.json.tmp"
FIELD = "started_ms"


class StartRefused(Exception):
    """This start is refused, and nothing was opened. `why` is spacing, clock, stamp or unwritable; `retry_after_s` is
    how long until a start can pass, or None when waiting does not help."""

    def __init__(self, why: str, retry_after_s: Optional[float] = None) -> None:
        super().__init__("start refused: %s" % why)
        self.why = why
        self.retry_after_s = retry_after_s


def encode(wall_ms: int) -> bytes:
    """The stamp's bytes for a start at `wall_ms`."""
    return json.dumps({FIELD: wall_ms}, separators=(",", ":")).encode("ascii")


def parse(data: bytes) -> Optional[int]:
    """The start time a stamp's bytes hold, or None when they are no stamp: too large, not JSON, not one object with
    the one field, or a value that is no whole number of milliseconds since the epoch."""
    if len(data) > limits.START_STAMP_MAX_BYTES:
        return None
    try:
        doc = json.loads(data.decode("ascii"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(doc, dict) or set(doc) != {FIELD}:
        return None
    value = doc[FIELD]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _read(directory: Any) -> Optional[bytes]:
    """The stamp file's bytes, one more than the cap at the most; None when there is no such file."""
    try:
        fd = os.open(str(Path(directory) / FILE), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    try:
        return os.read(fd, limits.START_STAMP_MAX_BYTES + 1)
    finally:
        os.close(fd)


def _write(directory: Any, wall_ms: int) -> None:
    """DIRECTORY/started.json by write-then-rename. It makes no directory."""
    target = Path(directory) / FILE
    tmp = Path(directory) / TMP
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        os.write(fd, encode(wall_ms))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))


def mark(directory: Any, wall_ms: int) -> None:
    """Record a start at `wall_ms` (the host's wall clock, whole milliseconds) in DIRECTORY, or raise StartRefused
    when it comes within limits.START_SPACING_S of the start recorded there, or when no record can be kept."""
    if not isinstance(wall_ms, int) or isinstance(wall_ms, bool) or wall_ms < 0:
        raise TypeError("a start time is whole milliseconds since the epoch")
    spacing_ms = limits.START_SPACING_S * 1000
    why = ""
    try:
        data = _read(directory)
        if data is not None:
            previous = parse(data)
            if previous is None:
                why = "stamp"
            elif wall_ms < previous:
                why = "clock"
            elif wall_ms - previous < spacing_ms:
                raise StartRefused("spacing", (spacing_ms - (wall_ms - previous)) / 1000.0)
        _write(directory, wall_ms)
    except OSError:          # its text would name the directory: it stops here
        raise StartRefused("unwritable") from None
    if why:
        raise StartRefused(why, float(limits.START_SPACING_S))
