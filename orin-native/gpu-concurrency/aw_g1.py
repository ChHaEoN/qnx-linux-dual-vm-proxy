#!/usr/bin/env python3
"""aw_g1.py -- gate G1's judge and run-aw-g1.sh's small readings. SDV Phase 8 WP8 Step B.

sdv/aw/prereg-g1g2.md (PR) holds every threshold, arm and counting rule; this file holds PR's values as constants and no threshold
of its own. Standard library only, and Python 3.10 (the host's python3 runs it; the judge also runs on a fetched record on a PC).
It imports aw_suite.py beside it for the monitor's `ctl rules:` form.

  now
        prints `MONO_NS WALL_NS`, CLOCK_MONOTONIC and the wall clock read in one action (QNX_CLOCK_FILE for the tests).
  first-route --file SCENARIO_JSONL
        prints the mono_ns of the drive's `route` line of outcome done; exit 1 when it has none.
  record --rec DIR --out F --status S --status-line L --at A --reason R --host-mode M --plan P --work W
        g1.json, written whole: the arm's facts (arm.tsv), the preflight's (W/facts), the verdict's lines, the status.
  judge --rec DIR [--arm main|guest-stopped] [--reset WORDS] [--rerun-of WHAT --rerun-after reset|not-judged] [--out DIR]
        PR sections 5, 6 and 7 on a record: one printed line per item T1, T2, T3, T4, T4w, T5, T6, T7 and per instrument, what
        is recorded and not gated, the findings, then one verdict naming every reason and the line on a re-run. --out also writes
        verdict.txt (what was printed) and windows.tsv. Exit 0 whatever the verdict: a verdict is a result. --reset is the
        operator's word for a reset, a hang or an oops during the arm (nothing on the host can write that record).

THE RECORD (OUT of run-aw-g1.sh, each file the harness's or a recorder's own):
  arm.tsv                  key TAB value, appended, the last value of a key holding: plan, arm, stamp_exit, stamp_mono_ns,
                           first_container_mono_ns, first_route_mono_ns, loop_end, loop_end_mono_ns, last_stop_mono_ns, harness_end
                           (the status line), ctl_digest, console_arm_from, arm_pair_start, arm_pair_end, and the facts of the run
  stamp.json, watchdog.log (`R MONO WALL KB` per read, `E MONO WALL WORD DETAIL` per event), watchdog.stop, sampler.jsonl, clk-g1.log
  placement.tsv            NAME TAB request TAB effective TAB state, per container's start; the resident driver's is aw-scenario, the driver's one
                           start (PR's dated section, item 15), and one row more for each start again (after a container ended with no number,
                           after a bound's 124, or after a driver found ended between drives)
  drives.tsv               `begin K MONO`, `end K EXIT MONO`, `stopped K WHY`; drives/dNNN/scenario.jsonl and, read by no item, drives/dNNN/exit,
                           odometry.jsonl and after-failure.jsonl (the driver's after a non-zero exit, so never a line section 6 reads)
  claim/run/replies.jsonl  the claim node's reply log (main); count/arrivals.jsonl the count recorder's (guest-stopped); diag/diag.jsonl
  vmstat-before.txt, vmstat-end.txt, memory-events-end.tsv (NAME TAB oom_kill or gone), clock-pairs.txt, hc-before.txt, hc-after.txt,
  guest-console.log

Where PR's numbered sections leave a case open, its dated sections read it, and the code cites the item; nothing else here is a choice.

Does not demonstrate: anything but what the record it reads says; see PR section 9 for what no verdict can show. The startup that
boots the guest under KVM is ours, not a QNX-supported configuration, and no timing claim attaches to the boot.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True                  # nothing written into the tarball's tree by the imports below
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aw_suite as aws  # noqa: E402
import vss_setup as vs  # noqa: E402

FORMAT = 1
S_NS = 1_000_000_000
# PR section 4
LOOP_NS = 1200 * S_NS
WINDOW_NS = 10 * S_NS
# PR section 5
T3_KB = 1048576
RATE_MIN = 30                                   # 30.0 per second: an exact comparison on integers
WINDOW_MIN = 150
GAP_NS = 5 * S_NS
CORES = {3, 5}
# PR section 6
CLOCK_TOLERANCE_NS = 1 * S_NS
COUNTED = ("replied", "drop", "lost")
# PR section 7
T5_LIST = ("topic_state_monitor_control_command_control_cmd: control_topic_status",
           "topic_state_monitor_trajectory_follower_control_cmd: control_topic_status",
           "controller_node_exe: incoming_message_timeout")
VALIDATOR_PREFIX = "control_validator"
LATENCY_STATUS = "control_validator: control_validation_latency"
SILENT_NS = 10 * S_NS
LEVEL_OK, LEVEL_ERROR, LEVEL_STALE = 0, 2, 3
HOST_CHECK_END = "status=FAILED at=host-check"
# PR's dated section, item 2: a `docker run -d` exiting non-zero is the harness's own; a drive's ends the loop as docker-run-failed, row `stopped`.
# PR's dated section, item 12: so is a `docker wait` on a drive that read no exit, docker-wait-failed, row `stopped`: that drive began.
# PR's dated section, item 15: the driver is resident, so that `docker run -d` is its one start, and its exit comes from a file in the
# drive's directory.
HARNESS_ENDS = {"watchdog-dead": "it stopped the loop for a dead watchdog", "misplaced": "it stopped the run for a misplaced container",
                "deadline": "the deadline stopped the loop",
                "docker-run-failed": "it could not start a drive (docker run of aw-scenario exited non-zero; drives.tsv holds the exit)",
                "docker-wait-failed": "it read no exit from a drive (no number in the driver's file, none from docker wait and no answer from "
                                      "docker; drives.tsv holds why)"}
PASS, FAIL, NO_READING, NOT_APPLICABLE = "PASS", "FAIL", "no reading", "does not apply"
MISS_LINE = re.compile(r"LIVENESS MISS: .*since seq=(\d+)")
ABOUT = ("run-aw-g1.sh's record (sdv-local, SDV Phase 8 WP8): one arm of gate G1 under sdv/aw/prereg-g1g2.md, Autoware's planning "
         "simulator beside the QNX guest under KVM, on this host, every container under 2.12 and on cores 3,5.")
NOTE = ("A rehearsal's figures (host mode c7g-metal) are never G1's and are compared with nothing. Nothing here is a claim of "
        "isolation, real time, safety or certification. The startup that boots the guest under KVM is ours, not a QNX-supported "
        "configuration, and no timing claim attaches to the boot.")


# --- the small readings -------------------------------------------------------------------------------------------------------

def now_pair() -> Tuple[int, int]:
    """(CLOCK_MONOTONIC, wall clock) in ns, one read after the other (QNX_CLOCK_FILE: the tests' clock)."""
    f = os.environ.get("QNX_CLOCK_FILE")
    if f:
        with open(f, encoding="ascii") as h:
            m, w = h.read().split()
        return int(m), int(w)
    return time.monotonic_ns(), time.time_ns()


def _jsonl(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """The JSON objects of a file, and how many lines were not whole (a torn last line after a kill or a reset)."""
    out: List[Dict[str, Any]] = []
    torn = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    doc = json.loads(ln)
                except ValueError:
                    torn += 1
                    continue
                if isinstance(doc, dict):
                    out.append(doc)
                else:
                    torn += 1
    except OSError:
        pass
    return out, torn


def read_scenario(path: str) -> List[Dict[str, Any]]:
    """A drive's scenario.jsonl: its whole lines, in order."""
    return _jsonl(path)[0]


def _mono(line: Dict[str, Any]) -> Optional[int]:
    v = line.get("mono_ns")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def route_mono(lines: List[Dict[str, Any]]) -> Optional[int]:
    """The mono_ns of the `route` line of outcome done, if the drive has one (PR section 6)."""
    for d in lines:
        if d.get("step") == "route" and d.get("outcome") == "done":
            return _mono(d)
    return None


def last_mono(lines: List[Dict[str, Any]]) -> Optional[int]:
    """The mono_ns of the drive's last line, whatever its outcome."""
    for d in reversed(lines):
        m = _mono(d)
        if m is not None:
            return m
    return None


@dataclass
class Frame:
    seq: Any
    t_ns: Optional[int]
    outcome: Any
    verdict: Any
    reason: Any


@dataclass
class Replies:
    found: bool = False
    frames: List[Frame] = field(default_factory=list)
    summary: Optional[Dict[str, Any]] = None
    torn: int = 0


def tstamp_of(frame_hex: Any) -> Optional[int]:
    """Bytes 8-15 of the frame, the client's clock when it packed it (PR section 6)."""
    try:
        raw = bytes.fromhex(frame_hex)
    except (TypeError, ValueError):
        return None
    return int.from_bytes(raw[8:16], "little") if len(raw) >= 16 else None


def read_replies(path: str) -> Replies:
    """The reply log: frame lines, the summary. A frame's place is its tstamp, never its outcome's mono_ns (PR section 6)."""
    r = Replies(found=os.path.isfile(path))
    docs, r.torn = _jsonl(path)
    for d in docs:
        if "summary" in d:
            s = d["summary"]
            r.summary = s if isinstance(s, dict) else None
        elif "seq" in d:
            r.frames.append(Frame(d.get("seq"), tstamp_of(d.get("frame")), d.get("outcome"), d.get("verdict"), d.get("reason")))
    return r


def read_arrivals(path: str) -> Replies:
    """The count recorder's file, as frames that are always counted: its arrival times read by the same rule (PR section 6)."""
    r = Replies(found=os.path.isfile(path))
    docs, r.torn = _jsonl(path)
    for d in docs:
        if "summary" in d:
            s = d["summary"]
            r.summary = s if isinstance(s, dict) else None
        elif "seq" in d:
            r.frames.append(Frame(d.get("seq"), _mono(d), "replied", 0, 0))
    return r


@dataclass
class Diag:
    found: bool = False
    events: List[Dict[str, Any]] = field(default_factory=list)     # first observations and level changes
    fifth: List[Dict[str, Any]] = field(default_factory=list)      # the 5 s lines


def read_diag(path: str) -> Diag:
    d = Diag(found=os.path.isfile(path))
    for doc in _jsonl(path)[0]:
        if isinstance(doc.get("last_seen"), dict) and _mono(doc) is not None:
            d.fifth.append(doc)
        elif "name" in doc and "level" in doc and _mono(doc) is not None:
            d.events.append(doc)
    return d


@dataclass
class Drive:
    name: str
    k: int
    lines: List[Dict[str, Any]]
    began_ns: Optional[int] = None
    rc: Optional[int] = None
    end_ns: Optional[int] = None
    stopped: str = ""                           # the harness stopped it (a misplaced container): no reading
    route_ns: Optional[int] = None
    last_ns: Optional[int] = None
    frames: List[Frame] = field(default_factory=list)
    windows: List[Tuple[int, int]] = field(default_factory=list)   # (start_ns, count)

    def interval_ns(self) -> Optional[int]:
        """From the first of its frames to its last line (PR section 6); None for a drive with no interval."""
        if not self.frames or self.last_ns is None:
            return None
        t = self.frames[0].t_ns
        return None if t is None else self.last_ns - t


def _int(text: Any) -> Optional[int]:
    try:
        return int(str(text))
    except ValueError:
        return None


def read_drives(rec: str) -> List[Drive]:
    rows: Dict[int, Dict[str, Any]] = {}
    try:
        with open(os.path.join(rec, "drives.tsv"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                c = ln.rstrip("\n").split("\t")
                k = _int(c[1]) if len(c) >= 2 else None
                if k is None:
                    continue
                e = rows.setdefault(k, {})
                if c[0] == "begin" and len(c) >= 3:
                    e["began"] = _int(c[2])
                elif c[0] == "end" and len(c) >= 4:
                    e["rc"], e["end"] = _int(c[2]), _int(c[3])
                elif c[0] == "stopped" and len(c) >= 3:
                    e["stopped"] = c[2]
    except OSError:
        pass
    out = []
    for k in sorted(rows):
        e = rows[k]
        name = "d%03d" % k
        lines = read_scenario(os.path.join(rec, "drives", name, "scenario.jsonl"))
        out.append(Drive(name, k, lines, e.get("began"), e.get("rc"), e.get("end"), e.get("stopped", ""), route_mono(lines), last_mono(lines)))
    return out


def place_frames(drives: List[Drive], frames: List[Frame]) -> int:
    """Each frame to the drive it falls in (after the drive's route line, at or before its last line), and each drive's windows:
    [start, start + 10 s), consecutive from its first frame, dropped when it would end after the interval. Returns the frames
    outside every drive."""
    placed = 0
    timed = sorted((f for f in frames if f.t_ns is not None and f.outcome in COUNTED), key=lambda f: f.t_ns or 0)
    for d in drives:
        if d.route_ns is None or d.last_ns is None:
            continue
        d.frames = [f for f in timed if d.route_ns < (f.t_ns or 0) <= d.last_ns]
        placed += len(d.frames)
        if d.frames and d.frames[0].t_ns is not None:
            start = d.frames[0].t_ns
            i = 0
            while start + WINDOW_NS <= d.last_ns:
                n = 0
                while i < len(d.frames) and (d.frames[i].t_ns or 0) < start + WINDOW_NS:
                    n += 1
                    i += 1
                d.windows.append((start, n))
                start += WINDOW_NS
    return len(timed) - placed


def rate_holds(frames: int, interval_ns: int) -> Optional[bool]:
    """T4's comparison: at least 30.0 per second, on integers; None with no interval to divide by."""
    if interval_ns <= 0:
        return None
    return frames * S_NS >= RATE_MIN * interval_ns


def place_of(drives: List[Drive], t_ns: Optional[int]) -> str:
    """Where a time falls against the drives, in words."""
    if t_ns is None:
        return "at no known time"
    seen = [d for d in drives if d.route_ns is not None and d.last_ns is not None]
    for d in seen:
        if (d.route_ns or 0) < t_ns <= (d.last_ns or 0):
            return "in %s" % d.name
    if not seen or t_ns <= (seen[0].route_ns or 0):
        return "before the first route"
    if t_ns > (seen[-1].last_ns or 0):
        return "after the last drive"
    return "between drives"


# --- one arm's record, read -------------------------------------------------------------------------------------------------

@dataclass
class Item:
    name: str
    state: str
    text: str = ""

    def line(self) -> str:
        return ("%s %s %s" % (self.name, self.state, self.text)).rstrip()


@dataclass
class Instrument:
    name: str
    state: str                                  # OK, MISSING or NOT_APPLICABLE
    text: str = ""

    def line(self) -> str:
        return ("instrument %s %s %s" % (self.name, self.state, self.text)).rstrip()


@dataclass
class Judged:
    verdict: str
    reasons: List[str]
    lines: List[str]
    windows: List[Tuple[str, int, int]]


@dataclass
class Arm:
    rec: str
    name: str
    facts: Dict[str, str]
    drives: List[Drive]
    log: Replies
    diag: Diag
    outside: int
    reset: str
    readings: List[Tuple[int, int]]
    watchdog_events: List[str]
    prevented: bool                              # a reset, or the harness's own exit: T1's end read, T6's summary, T7's 1200 s
    stopped_by_harness: str                      # the harness stopped the loop for its own instrument

    def mono(self, key: str) -> Optional[int]:
        return _int(self.facts.get(key, ""))


def read_arm_tsv(rec: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(os.path.join(rec, "arm.tsv"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                k, tab, v = ln.rstrip("\n").partition("\t")
                if tab:
                    out[k] = v
    except OSError:
        pass
    return out


def read_watchdog(rec: str) -> Tuple[List[Tuple[int, int]], List[str], bool]:
    """(the readings as (mono_ns, kB), its event lines, whether the file exists)."""
    readings: List[Tuple[int, int]] = []
    events: List[str] = []
    p = os.path.join(rec, "watchdog.log")
    if not os.path.isfile(p):
        return readings, events, False
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln in f:
            c = ln.split()
            if len(c) == 4 and c[0] == "R":
                m, kb = _int(c[1]), _int(c[3])
                if m is not None and kb is not None:
                    readings.append((m, kb))
            elif len(c) >= 4 and c[0] == "E":
                events.append(" ".join(c[3:]))
    return readings, events, True


def read_vmstat_oom(path: str) -> Optional[int]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                c = ln.split()
                if len(c) == 2 and c[0] == "oom_kill":
                    return _int(c[1])
    except OSError:
        pass
    return None


# --- the items (PR section 5) -----------------------------------------------------------------------------------------------

def item_t1(a: Arm) -> Item:
    before = read_vmstat_oom(os.path.join(a.rec, "vmstat-before.txt"))
    end = read_vmstat_oom(os.path.join(a.rec, "vmstat-end.txt"))
    p = os.path.join(a.rec, "memory-events-end.tsv")
    if before is None or end is None or not os.path.isfile(p):
        why = "the harness's end read did not happen" if a.prevented else "the harness's reads are not in the record"
        return Item("T1", NO_READING, "(%s)" % why)
    bad, n = [], 0
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln in f:
            c = ln.rstrip("\n").split("\t")
            if len(c) != 2 or c[1] == "gone":   # a scope gone by then is T7's, T6's or the positive control's matter
                continue
            n += 1
            if c[1] != "0":
                bad.append("%s oom_kill %s" % (c[0], c[1]))
    if end != before or bad:
        return Item("T1", FAIL, "/proc/vmstat oom_kill before %d, end %d; memory.events: %s" % (before, end, ", ".join(bad) or "0"))
    return Item("T1", PASS, "/proc/vmstat oom_kill unchanged (%d); memory.events oom_kill 0 in %d scope(s) still there" % (end, n))


def item_t2(a: Arm, have_log: bool) -> Item:
    stops = [e for e in a.watchdog_events if e.split()[0] == "stop"]
    if stops or os.path.exists(os.path.join(a.rec, "watchdog.stop")):
        return Item("T2", FAIL, "the watchdog stopped the arm: %s" % (stops[0] if stops else "its stop file exists"))
    if not have_log:
        return Item("T2", NO_READING, "(the watchdog's log is not in the record)")
    return Item("T2", PASS, "the watchdog's log holds no stop")


def item_t3(a: Arm) -> Item:
    start, end = a.mono("first_container_mono_ns"), a.mono("last_stop_mono_ns")
    if start is None:
        return Item("T3", NO_READING, "(no container started)")
    span = [kb for m, kb in a.readings if start <= m and (end is None or m <= end)]
    if not span:
        return Item("T3", NO_READING, "(the 1 s series holds no reading in the span)")
    low = min(span)
    if low < T3_KB:
        return Item("T3", FAIL, "lowest MemAvailable %d kB, under %d kB, over %d reading(s)" % (low, T3_KB, len(span)))
    return Item("T3", PASS, "lowest MemAvailable %d kB over %d reading(s)" % (low, len(span)))


def _no_end_under_reset(a: Arm, d: Drive) -> bool:
    """PR's dated section, item 6: under a reset, a hang or an oops, a drive with no `end` row enters no interval; its frames stay in the record."""
    return bool(a.reset) and d.rc is None


def _with_interval(a: Arm) -> List[Drive]:
    return [d for d in a.drives if d.interval_ns() is not None and not _no_end_under_reset(a, d)]


def item_t4(a: Arm) -> Item:
    ds = _with_interval(a)
    if not ds:
        return Item("T4", NO_READING, "(no drive has an interval)")
    frames = sum(len(d.frames) for d in ds)
    total = sum(d.interval_ns() or 0 for d in ds)
    holds = rate_holds(frames, total)
    if holds is None:
        return Item("T4", NO_READING, "(the intervals sum to nothing)")
    text = "%.3f per second, %d frames over %.3f s of drive intervals" % (frames * S_NS / total, frames, total / S_NS)
    return Item("T4", PASS if holds else FAIL, text)


def item_t4w(a: Arm) -> Item:
    ds = _with_interval(a)
    if not ds:
        return Item("T4w", NO_READING, "(no drive has an interval)")
    windows = [(d.name, s, n) for d in ds for s, n in d.windows]
    if not windows:
        return Item("T4w", PASS, "no drive holds a whole 10 s window")
    low = [w for w in windows if w[2] < WINDOW_MIN]
    lowest = min(w[2] for w in windows)
    if low:
        return Item("T4w", FAIL, "%d of %d window(s) under %d frames, the lowest %d, first in %s" % (
            len(low), len(windows), WINDOW_MIN, lowest, low[0][0]))
    return Item("T4w", PASS, "%d window(s), the lowest %d frames" % (len(windows), lowest))


def _first_drive_end(a: Arm) -> Optional[int]:
    return a.drives[0].last_ns if a.drives else None


def recorder_seeing_near(diag: Diag, t: int) -> bool:
    """Whether the recorder was seeing some name around t (PR's dated section, item 4): a 5 s line within SILENT_NS of t, some name of it
    seen within SILENT_NS of that line."""
    for doc in diag.fifth:
        m = _mono(doc) or 0
        if abs(m - t) <= SILENT_NS and any(isinstance(v, int) and m - v <= SILENT_NS for v in doc["last_seen"].values()):
            return True
    return False


def item_t5(a: Arm) -> Item:
    # PR's dated section, item 7: a status at STALE (level 3) is no T5 fail, and one on the list that reached it is named on T5's line.
    item = _t5_reading(a)
    stale = [n for n in T5_LIST if any(e.get("name") == n and e.get("level") == LEVEL_STALE for e in a.diag.events)]
    if stale:
        item.text += "; reached STALE, no T5 fail: %s" % ", ".join(stale)
    return item


def _t5_reading(a: Arm) -> Item:
    if not a.diag.found or not (a.diag.events or a.diag.fifth):
        return Item("T5", NO_READING, "(the recorder's file holds nothing)")
    if not a.drives:
        return Item("T5", NO_READING, "(no drive began)")
    problems: List[str] = []
    not_read: List[str] = []
    first_end = _first_drive_end(a)
    # PR's dated section, item 1: with the recorder unseeing at the first drive's end, or a first drive that never ended, that clause is not read.
    ended = a.drives[0].rc is not None
    seeing = ended and first_end is not None and recorder_seeing_near(a.diag, first_end)
    for name in T5_LIST:
        been_ok_at: Optional[int] = None
        for e in a.diag.events:
            if e.get("name") != name:
                continue
            level = e.get("level")
            if level == LEVEL_OK and been_ok_at is None:
                been_ok_at = _mono(e)
            elif level == LEVEL_ERROR and been_ok_at is not None:
                problems.append("%s reached ERROR %s, having been OK" % (name, place_of(a.drives, _mono(e))))
                break
        if first_end is None or been_ok_at is None or been_ok_at > first_end:
            if seeing:
                problems.append("%s had not been OK by the end of the first drive" % name)
            else:
                not_read.append(name)
    problems += silent_validator(a)
    if problems:
        return Item("T5", FAIL, "; ".join(problems))
    if not_read:
        if first_end is None:
            why = "the first drive wrote no line"
        elif not ended:
            why = "the first drive did not end"
        else:
            why = "the recorder saw no name at the end of the first drive"
        return Item("T5", NO_READING, "(%s, so whether %s had been OK by then is not read)" % (why, ", ".join(not_read)))
    if not ended:
        return Item("T5", NO_READING, "(the first drive did not end, so whether each status had been OK by its end is not read)")
    return Item("T5", PASS, "each status on the list OK by the end of the first drive, none back at ERROR; no silent validator")


def silent_validator(a: Arm) -> List[str]:
    """PR section 7's silent validator, as PR's dated section, item 3 reads it: one name of the validator's unseen for over 10 s at a 5 s
    line inside a drive interval, some name not of the validator's seen within the same 10 s of that line."""
    out: List[str] = []
    spans = [(d.frames[0].t_ns or 0, d.last_ns or 0, d.name) for d in _with_interval(a)]
    for doc in a.diag.fifth:
        m = _mono(doc) or 0
        inside = next((name for s, e, name in spans if s <= m <= e), None)
        if inside is None:
            continue
        seen = {k: v for k, v in doc["last_seen"].items() if isinstance(v, int)}
        others = any(m - v <= SILENT_NS for k, v in seen.items() if not k.startswith(VALIDATOR_PREFIX))
        if not others:
            continue
        silent = [k for k, v in seen.items() if k.startswith(VALIDATOR_PREFIX) and m - v > SILENT_NS]
        if silent:
            out.append("a silent validator in %s: %s unseen for over 10 s with the recorder seeing other names" % (inside, silent[0]))
            break
    return out


def item_t6(a: Arm) -> Item:
    if a.name != "main":
        return Item("T6", NOT_APPLICABLE, "(the guest-stopped arm has no claim node: drop and lost do not apply)")
    s = a.log.summary
    if s is None:
        if a.prevented or a.stopped_by_harness:
            return Item("T6", NO_READING, "(the claim node's summary was prevented)")
        if any(e.split()[0] == "stop" for e in a.watchdog_events):
            return Item("T6", NO_READING, "(the claim node's summary is absent: the watchdog killed it)")
        # PR's dated section, item 13: the harness's own docker stop got no answer, so the node was never signalled
        if a.facts.get("claim_stop_exit") not in (None, "0"):
            why = "(the harness's docker stop of the claim node exited %s, so its summary was not read)" % a.facts["claim_stop_exit"]
            return Item("T6", NO_READING, why)
        return Item("T6", FAIL, "the reply log has no summary line: the claim node did not end its run")
    c, ident = s.get("counters"), s.get("identity")
    c = c if isinstance(c, dict) else {}
    ident = ident if isinstance(ident, dict) else {}
    drop, lost, holds = c.get("drop"), c.get("lost_on_reconnect"), ident.get("holds")
    text = "drop %s, lost_on_reconnect %s, identity %s, reconnects %s" % (drop, lost, "holds" if holds is True else "BROKEN", c.get("reconnects"))
    return Item("T6", PASS if drop == 0 and lost == 0 and holds is True else FAIL, text)


def _drive_problem(d: Drive) -> str:
    """Why a drive that began fails T7 by a reading, "" when it does not."""
    if d.rc != 0:
        return "%s exited %s" % (d.name, d.rc)
    steps = {x.get("step"): x for x in d.lines}
    if (steps.get("arrive") or {}).get("outcome") != "done":
        return "%s did not arrive at the goal" % d.name
    if (steps.get("clear") or {}).get("outcome") != "done":
        return "%s did not clear its route" % d.name
    if d.route_ns is None:
        return "%s has no route line of outcome done" % d.name
    if not d.frames:
        return "%s has no frame, so no interval" % d.name
    return ""


def item_t7(a: Arm) -> Item:
    # PR's dated section, item 5: T7 is read in the guest-stopped arm too.
    problems: List[str] = []
    unread: List[str] = []
    for d in a.drives:
        if d.stopped:
            unread.append("%s stopped by the harness (%s)" % (d.name, d.stopped))
        elif d.rc is None:
            if a.prevented or a.stopped_by_harness:
                unread.append("%s has no end" % d.name)
            else:
                problems.append("%s has no end" % d.name)
        else:
            why = _drive_problem(d)
            if why:
                problems.append(why)
    first = a.drives[0].route_ns if a.drives else None
    ended = [d.end_ns for d in a.drives if d.end_ns is not None]
    reached = first is not None and bool(ended) and max(ended) - first >= LOOP_NS
    end = a.facts.get("loop_end", "")
    if not reached:
        if a.prevented or a.stopped_by_harness:
            unread.append("the loop's 1200 s were prevented")
        else:
            problems.append("the loop did not reach 1200 s (its end: %s)" % (end or "none"))
    if problems:
        return Item("T7", FAIL, "; ".join(problems))
    if unread:
        return Item("T7", NO_READING, "(%s)" % "; ".join(unread))
    return Item("T7", PASS, "%d drive(s), each exit 0, at the goal, its route cleared; the loop reached 1200 s" % len(a.drives))


# --- the instruments (PR section 5) ------------------------------------------------------------------------------------------

def inst_series(a: Arm, have_log: bool) -> Instrument:
    start, end = a.mono("first_container_mono_ns"), a.mono("loop_end_mono_ns")
    if not have_log:
        return Instrument("series", "MISSING", "(the 1 s series is not in the record)")
    if start is None:
        return Instrument("series", "MISSING", "(no container started, so no span)")
    if end is None:
        return Instrument("series", "MISSING", "(the record has no loop's end to cover)")
    rows = sorted(a.readings)
    gaps: List[str] = []

    def lowest(part: List[Tuple[int, int]]) -> str:
        return "%d kB" % min(kb for _m, kb in part) if part else "none"

    before = [r for r in rows if r[0] <= start]
    after = [r for r in rows if r[0] > start]
    if not before and (not after or after[0][0] - start > GAP_NS):
        gaps.append("%.3f s from the first container's start to its first reading, lowest after it %s" % (
            ((after[0][0] if after else end) - start) / S_NS, lowest(after)))
    for x, y in zip(rows, rows[1:]):
        if y[0] - x[0] > GAP_NS and x[0] < end and y[0] > start:
            side_a = [r for r in rows if r[0] <= x[0] and r[0] >= start]
            side_b = [r for r in rows if r[0] >= y[0]]
            gaps.append("%.3f s from %d to %d, lowest before it %s, after it %s" % ((y[0] - x[0]) / S_NS, x[0], y[0], lowest(side_a), lowest(side_b)))
    if rows and end - rows[-1][0] > GAP_NS:
        gaps.append("its last reading is %.3f s before the loop's end, lowest before it %s" % ((end - rows[-1][0]) / S_NS, lowest(rows)))
    if not rows:
        gaps.append("no reading at all")
    if gaps:
        return Instrument("series", "MISSING", "a gap over 5 s (itself evidence of pressure): " + "; ".join(gaps))
    return Instrument("series", "OK", "%d reading(s), no gap over 5 s from the first container's start to the loop's end" % len(rows))


def inst_stamp(a: Arm) -> Instrument:
    p = os.path.join(a.rec, "stamp.json")
    if a.facts.get("stamp_exit") not in ("0", None):
        return Instrument("stamp", "MISSING", "(the stamp refused under PLATFORM_POLICY=g1)")
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return Instrument("stamp", "MISSING", "(no stamp.json that parses)")
    plat = doc.get("platform") if isinstance(doc, dict) else None
    policy = plat.get("policy") if isinstance(plat, dict) else None
    if policy != "g1":
        return Instrument("stamp", "MISSING", "(its policy is %r, not g1)" % (policy,))
    at, first = a.mono("stamp_mono_ns"), a.mono("first_container_mono_ns")
    if at is None or (first is not None and at > first):
        return Instrument("stamp", "MISSING", "(it was not written before the first container)")
    return Instrument("stamp", "OK", "written under PLATFORM_POLICY=g1 before any container")


def _cores_within(text: str) -> bool:
    """Whether a CPU list is not empty and names only cores 3 and 5."""
    cores: List[int] = []
    for part in text.split(","):
        lo, dash, hi = part.partition("-")
        if not lo.isdigit() or (dash and not hi.isdigit()):
            return False
        cores += list(range(int(lo), int(hi or lo) + 1))
    return bool(cores) and set(cores) <= CORES


def inst_placement(a: Arm) -> Instrument:
    p = os.path.join(a.rec, "placement.tsv")
    if not os.path.isfile(p):
        return Instrument("placement", "MISSING", "(the harness's reads are not in the record)")
    rows = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln in f:
            c = ln.rstrip("\n").split("\t")
            if c and c[0]:
                rows.append((c + ["", "", ""])[:4])
    bad = ["%s request '%s' effective '%s' (%s)" % (r[0], r[1], r[2], r[3]) for r in rows
           if not _cores_within(r[1]) or not _cores_within(r[2])]
    if a.stopped_by_harness or a.reset or a.facts.get("loop_end") is None:
        want: List[str] = []                    # the run ended before every container started: the rows it has are its reading
    else:
        want = ["aw-sim", "aw-g1-diag", "aw-claim-node" if a.name == "main" else "aw-g1-count"]
        if a.drives:                            # PR's dated section, item 15: section 5's instrument reads the driver's one start
            want.append("aw-scenario")
    have = {r[0] for r in rows}
    lost = [n for n in want if n not in have]
    if bad or lost or not rows:
        return Instrument("placement", "MISSING", "; ".join(bad + ["no read of %s" % n for n in lost]) or "(no container was read)")
    return Instrument("placement", "OK", "%d container start(s), each on {3,5} by its request and its effective cpus" % len(rows))


def inst_reply_log(a: Arm) -> Instrument:
    if a.name != "main":
        return Instrument("reply-log", NOT_APPLICABLE, "(no claim node in this arm)")
    if not a.log.found:
        return Instrument("reply-log", "MISSING", "(the reply log is not in the record)")
    bad = [f.seq for f in a.log.frames if f.outcome not in COUNTED or f.t_ns is None]
    if bad:
        return Instrument("reply-log", "MISSING", "%d frame line(s) with no outcome or no tstamp, the first seq %s" % (len(bad), bad[0]))
    seqs = [f.seq for f in a.log.frames]
    # PR section 5 asks for one line per seq and no order: ctlclient.offer writes a replaced frame's drop line while an older reply is out
    if sorted(s for s in seqs if isinstance(s, int)) != list(range(1, len(seqs) + 1)):
        return Instrument("reply-log", "MISSING", "the frame lines are not one per seq from 1")
    return Instrument("reply-log", "OK", "%d frame line(s), one per seq, each with its outcome" % len(seqs))


def inst_rules_digest(a: Arm) -> Instrument:
    if a.name != "main":
        return Instrument("rules-digest", NOT_APPLICABLE, "(no guest in this arm)")
    want = a.facts.get("ctl_digest", "")
    try:
        with open(os.path.join(a.rec, "guest-console.log"), "rb") as f:
            text = f.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
    except OSError:
        return Instrument("rules-digest", "MISSING", "(the guest's console is not in the record)")
    found = {m.group(1) for m in (aws.CTL_RULES.search(ln.strip()) for ln in text.splitlines()) if m}
    if not found:
        return Instrument("rules-digest", "MISSING", "(the console holds no `ctl rules:` line)")
    if found != {want}:
        return Instrument("rules-digest", "MISSING", "the `ctl rules:` catalog %s is not vss_ctl.py's %s" % (sorted(found), want))
    return Instrument("rules-digest", "OK", "the `ctl rules:` catalog %s is vss_ctl.py's" % want)


def inst_positive_control(a: Arm) -> Instrument:
    if not a.diag.found:
        return Instrument("positive-control", "MISSING", "(the recorder's file is not in the record)")
    ok = any(str(e.get("name", "")).startswith(VALIDATOR_PREFIX) and e.get("level") == LEVEL_OK for e in a.diag.events)
    lost = [d.name for d in a.drives if d.last_ns is not None and not recorder_seeing_near(a.diag, d.last_ns)]
    why = []
    if not ok:
        why.append("no observation of a control_validator status at OK")
    if lost:
        why.append("the recorder saw no name at the end of %s" % ", ".join(lost))
    if not a.drives:
        why.append("no drive")
    if why:
        return Instrument("positive-control", "MISSING", "; ".join(why))
    return Instrument("positive-control", "OK", "a control_validator status seen at OK; the recorder seeing at the end of every drive")


def inst_settings(a: Arm) -> Instrument:
    try:
        with open(os.path.join(a.rec, "hc-before.txt"), encoding="utf-8") as f:
            before = f.read().split()
        with open(os.path.join(a.rec, "hc-after.txt"), encoding="utf-8") as f:
            after = f.read().split()
    except OSError:
        return Instrument("settings", "MISSING", "(2.12's reads before and after are not both in the record)")
    if before != after or not before:
        return Instrument("settings", "MISSING", "2.12's four settings differ: %s" % sorted(set(before) ^ set(after)))
    return Instrument("settings", "OK", "2.12's four settings equal before and after")


def inst_one_clock(a: Arm) -> Instrument:
    pairs: Dict[str, Tuple[int, int]] = {}
    try:
        with open(os.path.join(a.rec, "clock-pairs.txt"), encoding="utf-8") as f:
            for ln in f:
                c = ln.split()
                if len(c) == 3 and c[1].isdigit() and c[2].isdigit():
                    pairs[c[0]] = (int(c[1]), int(c[2]))
    except OSError:
        pass
    if set(pairs) != {"host", "container"}:
        return Instrument("one-clock", "MISSING", "(the pair on each side is not in the record)")
    host, cont = pairs["host"], pairs["container"]
    diff = (host[1] - host[0]) - (cont[1] - cont[0])
    if abs(diff) > CLOCK_TOLERANCE_NS:
        return Instrument("one-clock", "MISSING", "the two offsets differ by %.3f s, over 1 s" % (abs(diff) / S_NS))
    return Instrument("one-clock", "OK", "the host's and a container's CLOCK_MONOTONIC offsets within 1 s")


# --- recorded, not gated ---------------------------------------------------------------------------------------------------------

def _windows_rows(a: Arm) -> List[Tuple[str, int, int]]:
    return [(d.name, s, n) for d in _with_interval(a) for s, n in d.windows]


def info_lines(a: Arm) -> List[str]:
    ds = _with_interval(a)
    out = ["info arm %s; %d drive(s); the sum of the intervals %.3f s" % (a.name, len(a.drives), sum(d.interval_ns() or 0 for d in ds) / S_NS),
           "info frames inside drive intervals: %d" % sum(len(d.frames) for d in ds),
           "info frames outside every drive: %d" % a.outside]
    cut = [d for d in a.drives if _no_end_under_reset(a, d)]
    if cut:
        out.append("info frames of drives with no end row under the reset: %d, kept in the record, in no interval" % sum(len(d.frames) for d in cut))
    counts = sorted(n for _d, _s, n in _windows_rows(a))
    if counts:
        out.append("info windows: %d, lowest %d, median %d, highest %d" % (len(counts), counts[0], counts[len(counts) // 2], counts[-1]))
    for d in a.drives:
        iv = d.interval_ns()
        if _no_end_under_reset(a, d):
            out.append("info drive %s: no end row under the reset, so no interval; %d frames kept in the record" % (d.name, len(d.frames)))
        elif iv is None:
            out.append("info drive %s: no interval" % d.name)
        elif d.route_ns is not None and d.frames[0].t_ns is not None:
            out.append("info drive %s: from SET to the first Control %.3f s, interval %.3f s, %d frames" % (
                d.name, (d.frames[0].t_ns - d.route_ns) / S_NS, iv / S_NS, len(d.frames)))
    if a.name != "main":
        out.append("info the count recorder's callback is lighter than the claim node's: its T4 is another instrument, never subtracted "
                   "from the main arm's, and this arm changes the main arm's verdict in no way")
    # the recorder's other readings: PR section 7's "listed", section 6's measured_rate shown beside T4
    reached: Dict[str, List[int]] = {}
    for e in a.diag.events:
        name, level = str(e.get("name")), e.get("level")
        if name not in T5_LIST and isinstance(level, int) and level >= 1:
            reached.setdefault(name, []).append(level)
    for name in sorted(reached):
        out.append("info status not on the list reached WARN or ERROR, %d time(s), no gate item: %s" % (len(reached[name]), name))
    out.append(latency_line(a))
    out.append(sampler_line(a))
    killed = ["%s %s" % (k[len("oomkilled_"):], v) for k, v in sorted(a.facts.items()) if k.startswith("oomkilled_") and v != "none"]
    if killed:
        out.append("info OOMKilled, information only: %s" % ", ".join(killed))
    between, unanswered = a.facts.get("driver_ended_between_drives"), a.facts.get("driver_inspect_unanswered")
    if between is not None or unanswered is not None:      # a second container is a second join of the resident driver; neither fact gates
        said = []
        if between is not None:
            said.append("last found ended before %s, no drive's reading, and started again" % between)
        if unanswered is not None:
            said.append("an inspect before a drive had no answer from docker (%s), and it was taken to be running" % unanswered)
        out.append("info the resident driver, recorded, no gate item: %s" % "; ".join(said))
    rates = []
    for doc in a.diag.fifth:
        vals = doc.get("values")
        got = vals.get(T5_LIST[0]) if isinstance(vals, dict) else None
        rate = got.get("measured_rate") if isinstance(got, dict) else None
        m = re.match(r"^([0-9.]+)", rate) if isinstance(rate, str) else None
        if m and any((d.frames[0].t_ns or 0) <= (_mono(doc) or 0) <= (d.last_ns or 0) for d in ds):
            rates.append(float(m.group(1)))
    if rates:
        out.append("info control_topic_status measured_rate inside the intervals (ungated, a third subscriber's): lowest %.2f, highest %.2f" % (
            min(rates), max(rates)))
    return out


def sampler_line(a: Arm) -> str:
    """PR section 4: the 5 s sampler is read by no item, and a gap in it is reported (no instrument's failure): its rounds, the largest gap
    between two of them, and how long before the loop's end the last one fell."""
    docs = _jsonl(os.path.join(a.rec, "sampler.jsonl"))[0]
    t = sorted(m for m in (_mono(d) for d in docs if d.get("what") == "meminfo") if m is not None)
    head = "info the 5 s sampler, read by no item:"
    if not t:
        return "%s no round in the record" % head
    gap = max((y - x for x, y in zip(t, t[1:])), default=0)
    text = "%s %d round(s), the largest gap between two %.3f s" % (head, len(t), gap / S_NS)
    end = a.mono("loop_end_mono_ns")
    if end is not None and end > t[-1]:
        text += ", the last round %.3f s before the loop's end" % ((end - t[-1]) / S_NS)
    elif end is not None:
        text += ", the last round after the loop's end"
    return text


def latency_line(a: Arm) -> str:
    """PR section 7's recorded status: control_validation_latency's entries away from OK and its time away, to its last change."""
    entries, away, since = 0, 0, None
    for e in a.diag.events:
        if e.get("name") != LATENCY_STATUS:
            continue
        m = _mono(e) or 0
        if e.get("level") == LEVEL_OK:
            if since is not None:
                away += m - since
                since = None
        elif since is None:
            entries += 1
            since = m
    tail = "; away from OK at its last change" if since is not None else ""
    return "info %s, recorded, no gate item: %d entries away from OK, %.3f s away%s" % (LATENCY_STATUS, entries, away / S_NS, tail)


def finding_lines(a: Arm) -> List[str]:
    """Every REJECT and every MISS, with its seq and its place against the drives (PR section 6): never a gate item."""
    out: List[str] = []
    if a.name != "main":
        return out
    by_seq = {f.seq: f for f in a.log.frames}
    for f in a.log.frames:
        if f.outcome == "replied" and f.verdict != 0:
            out.append("finding REJECT seq=%s reason=%s %s" % (f.seq, f.reason, place_of(a.drives, f.t_ns)))
    start = _int(a.facts.get("console_arm_from", "0")) or 0
    try:
        with open(os.path.join(a.rec, "guest-console.log"), "rb") as h:
            h.seek(start)
            text = h.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
    except OSError:
        text = ""
    for ln in text.splitlines():
        m = MISS_LINE.search(ln)
        if m:
            seq = int(m.group(1))
            hit = by_seq.get(seq)
            out.append("finding MISS seq=%d %s" % (seq, place_of(a.drives, hit.t_ns) if hit else "(no frame of that seq)"))
    return out


def clock_of_windows(a: Arm, rows: List[Tuple[str, int, int]]) -> List[str]:
    """windows.tsv's lines: each window's emc_bpmp_hz, the clock sampler's last reading at or before its start, placed by the arm's
    (CLOCK_MONOTONIC, wall clock) pair."""
    clk: List[Tuple[int, str]] = []
    try:
        with open(os.path.join(a.rec, "clk-g1.log"), encoding="utf-8", errors="replace") as f:
            for ln in f:
                m = re.match(r"^([0-9.]+) emc_bpmp_hz=(\S*)", ln)
                if m:
                    clk.append((int(float(m.group(1)) * S_NS), m.group(2)))
    except OSError:
        pass
    pair = a.facts.get("arm_pair_start", "").split()
    off = int(pair[1]) - int(pair[0]) if len(pair) == 2 and pair[0].isdigit() and pair[1].isdigit() else None
    out = ["drive\tstart_mono_ns\tframes\temc_bpmp_hz"]
    for name, s, n in rows:
        hz = ""
        if off is not None:
            for t, v in clk:
                if t <= s + off:
                    hz = v
                else:
                    break
        out.append("%s\t%d\t%d\t%s" % (name, s, n, hz))
    return out


# --- the verdict ----------------------------------------------------------------------------------------------------------------

def judge_record(rec: str, arm: Optional[str] = None, reset: Optional[str] = None, rerun_of: Optional[str] = None,
                 rerun_after: Optional[str] = None) -> Judged:
    """PR sections 5, 6 and 7 on a record."""
    facts = read_arm_tsv(rec)
    name = arm or facts.get("arm") or "main"
    drives = read_drives(rec)
    if name == "main":
        log = read_replies(os.path.join(rec, "claim", "run", "replies.jsonl"))
    else:
        log = read_arrivals(os.path.join(rec, "count", "arrivals.jsonl"))
    outside = place_frames(drives, log.frames)
    diag = read_diag(os.path.join(rec, "diag", "diag.jsonl"))
    readings, events, have_log = read_watchdog(rec)
    end_word = facts.get("loop_end")
    harness_end = facts.get("harness_end")
    early: List[str] = []                       # the harness's own exit
    said = "%s: %s" % (harness_end, facts["harness_why"]) if facts.get("harness_why") else harness_end
    if end_word is None and not reset:
        early.append("the harness exited before the loop's end" + (" (%s)" % said if harness_end else " (it wrote no status line)"))
    elif harness_end is None and not reset:
        early.append("the harness exited after the loop's end with no status line")
    elif harness_end not in (None, "status=DONE", HOST_CHECK_END) and end_word not in HARNESS_ENDS and not reset:
        early.append("the harness ended %s" % said)
    a = Arm(rec, name, facts, drives, log, diag, outside, reset or "", readings, events, bool(reset) or bool(early),
            HARNESS_ENDS.get(end_word or "", ""))
    items = [
        item_t1(a),
        item_t2(a, have_log),
        item_t3(a),
        item_t4(a),
        item_t4w(a),
        item_t5(a),
        item_t6(a),
        item_t7(a),
    ]
    instruments = [
        inst_series(a, have_log),
        inst_stamp(a),
        inst_placement(a),
        inst_reply_log(a),
        inst_rules_digest(a),
        inst_positive_control(a),
        inst_settings(a),
        inst_one_clock(a),
    ]
    failed = [i for i in items if i.state == FAIL]
    unread = [i for i in items if i.state == NO_READING]
    missing = [i for i in instruments if i.state == "MISSING"]
    reasons = []
    if reset:
        reasons.append("a reset, a hang or an oops during the arm, cause not assigned: %s" % reset)
    reasons += ["%s: %s" % (i.name, i.text) for i in failed]
    if a.stopped_by_harness:
        harness_reasons = ["the harness: %s" % a.stopped_by_harness]
    else:
        harness_reasons = list(early)
    if failed or reset:
        verdict = "FAIL"
        # a reset's prevented readings are not readings (PR section 5): its reason alone stands
        also = [] if reset else ["instrument %s: %s" % (i.name, i.text) for i in missing] + harness_reasons
    elif missing or unread or harness_reasons:
        # PR's dated section, item 8: an item with no reading that no instrument explains is NOT JUDGED, naming the item.
        verdict = "NOT JUDGED"
        also = []
        reasons += ["instrument %s: %s" % (i.name, i.text) for i in missing] + harness_reasons
        reasons += ["%s: no reading %s" % (i.name, i.text) for i in unread]
    else:
        verdict = "PASS"
        also = []
    lines = [i.line() for i in items] + [i.line() for i in instruments]
    lines += info_lines(a) + finding_lines(a)
    label = ""
    if rerun_of:
        label = "a re-run of %s" % rerun_of
        if rerun_after == "reset" and verdict == "PASS":
            label = "passed on a later boot after a reset of unassigned cause; %s" % label
    head = "verdict: %s" % verdict
    if verdict == "PASS":
        vline = "%s (%s)" % (head, label) if label else head
    else:
        vline = "%s: %s" % (head, "; ".join(reasons + (["also " + x for x in also]))) + (" (%s)" % label if label else "")
    lines.append(vline)
    if verdict == "PASS":
        lines.append("re-run: not one; a verdict was given")
    elif verdict == "NOT JUDGED" or (reset and not failed):
        lines.append("re-run: allowed on the owner's word on a later boot, every arm and its partial readings kept in the record")
    else:
        lines.append("re-run: none for a verdict: an item failed by a reading")
    return Judged(verdict, reasons, lines, _windows_rows(a))


# --- the commands ----------------------------------------------------------------------------------------------------------------

def cmd_now(_a: argparse.Namespace) -> int:
    print("%d %d" % now_pair())
    return 0


def cmd_first_route(a: argparse.Namespace) -> int:
    m = route_mono(read_scenario(a.file))
    if m is None:
        return 1
    print(m)
    return 0


def cmd_judge(a: argparse.Namespace) -> int:
    if a.rerun_after and not a.rerun_of:
        raise SystemExit("--rerun-after needs --rerun-of: the record's header says what the arm is a re-run of")
    j = judge_record(a.rec, a.arm, a.reset, a.rerun_of, a.rerun_after)
    text = "".join(ln + "\n" for ln in j.lines)
    sys.stdout.write(text)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "verdict.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        facts = read_arm_tsv(a.rec)
        arm = Arm(a.rec, "", facts, [], Replies(), Diag(), 0, "", [], [], False, "")
        with open(os.path.join(a.out, "windows.tsv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(ln + "\n" for ln in clock_of_windows(arm, j.windows)))
    return 0


def cmd_record(a: argparse.Namespace) -> int:
    verdict: List[str] = []
    try:
        with open(os.path.join(a.rec, "verdict.txt"), encoding="utf-8") as f:
            verdict = f.read().splitlines()
    except OSError:
        pass
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-aw-g1.sh", "host_mode": a.host_mode, "about": ABOUT, "note": NOTE, "plan": a.plan,
                           "status": a.status, "status_line": a.status_line, "at": a.at or None, "reason": a.reason or None,
                           "arm": read_arm_tsv(a.rec), "facts": vs.read_facts(os.path.join(a.work, "facts")), "verdict": verdict}
    vs.write_json(a.out, doc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("now")
    p = sub.add_parser("first-route")
    p.add_argument("--file", required=True)
    p = sub.add_parser("judge")
    p.add_argument("--rec", required=True)
    p.add_argument("--arm", choices=("main", "guest-stopped"))
    p.add_argument("--reset")
    p.add_argument("--rerun-of")
    p.add_argument("--rerun-after", choices=("reset", "not-judged"))
    p.add_argument("--out")
    p = sub.add_parser("record")
    for x in ("--rec", "--out", "--status", "--status-line", "--host-mode", "--work"):
        p.add_argument(x, required=True)
    for x in ("--at", "--reason", "--plan"):
        p.add_argument(x, default="")
    a = ap.parse_args(argv)
    return {"now": cmd_now, "first-route": cmd_first_route, "judge": cmd_judge, "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
