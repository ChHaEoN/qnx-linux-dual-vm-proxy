#!/usr/bin/env python3
"""vss_claim_bridge.py -- the kind 4 claim bridge's core (sdv/bridge): one claim per 10 Hz tick from the
latest held VSS values, sent to the QNX guest's monitor (:7160 svc; :7161 stamp for timing runs only).

The kind 4 wire specification (the project's local design notes, section
14 and the design values of section 15; not in this tree) defines the bridge; Phase 2's design decisions
b (the reply timeout) and c (the tick never waits on the gRPC side) and the owner's calls of 2026-10-01
(reason 21: keep sending; the scenario lock: held while connected) are built in. The frame is packed by
sdv/frame/vssframe.py; the profile table, the digest, AGE_MAX and the spread thresholds come from the
generated contract (sdv-out/gen/vss_contract.py), never copied here. Standard library only: the source
adapters (broker, can, replay) and the write-back sink are bridge_sources.py's, which imports kuksa-client,
python-can and cantools lazily; this module imports no gRPC.

    vss_claim_bridge.py run --port PORT [--host ADDR] (--header FILE | --mode MODE --profile ID
        --profile-source SOURCE --vehicle NAME --wheelbase-mm MM [--demo-odd START_S,DURATION_S])
        [--seconds S] [--script FILE] [--name NAME | --out DIR] [--lock PATH] [--gen DIR]

The command line runs the core against a source supplied in-process (`main(argv, source=...)`); from a
shell it has none, so it refuses with exit 2 and names `bridge_sources.py run`, which takes the same flags
and opens the mode's real source (the container's entry point). It runs until --seconds, SIGTERM or
SIGINT, a script's end step, or the claim thread's end (a fatal: exit 1); a signal ends a run given --seconds
as well (docker stop sends SIGTERM), with the same drain, summary and exit code as any stop. Output:
~/sdv-runs/<date>-<name>/ (SDV_RUNS moves the root) or --out; never inside the repo or under ~/sdv-recordings. A start refused after
the run directory was opened (the source's clock) removes its empty logs, and the directory if the bridge
made it, so the same --out or --name can run again.

THREADS (design decision c)
  intake    iterates the source's blocking stream of updates and writes the held values. A pause keeps
            draining the stream and only stops updating them. It holds the held values' lock only to copy
            a batch in, never while it waits on the stream.
  claim     the 10 Hz tick and the claim socket, one select() loop: it takes a locked snapshot of the held
            values, packs, sends, reads the reply, and never waits on the intake or the write-back. It is
            the event log's only file writer while it runs: the intake's and the control calls' records are
            appended in memory and written at its next pass (EventLog), so it never waits on another
            thread's file I/O. Its own synchronous writes are the log, the reply log and two stderr lines
            (the first reason 21 and a fatal).
  writeback the write-back to the local databroker's Monitor branch (spec 14.4; the sink is
            bridge_sources.MonitorWriteBack): a bounded queue the claim thread offers to without
            blocking; a full queue drops the record and counts it.
  script    only with a script (SCRIPT, below): makes its control calls at their instants, as any other
            thread may make them; its records reach the file at the claim thread's next pass.

HELD VALUES AND THE TICK (spec 3, 14.1)
  A slot is held from its first value on and is never cleared by age, so a dead source shows as 22, not
  as an absent signal. Each tick packs one frame from the snapshot if any slot is held (else it counts
  ticks_empty); the age is the oldest used value's against the source's own clock (Source.now_ns, int ns;
  anything else is refused at start and a fatal mid-run), via vssframe.age_field: truncated to ms,
  saturated at 0xFFFF, a negative difference sent as 0 and counted (age_negative). seq is assigned at
  packing, from 1. A tick is counted with its frame or as empty, never before the pack.
  A frame's age is its age at packing, never updated when it is sent. While the tick runs, a queued frame is
  sent, if at all, before the next tick replaces it, so it goes out at most about one tick after its packing
  (the stop's drain is the exception: there the queued frame waits for the outstanding one's reply or reply
  timeout). A paused tick packs nothing, and every send attempt (_try_send, once per pass of the claim
  thread) checks the pause first: once pause_tick() has set the flag, the next attempt -- after a paused
  tick, the outstanding frame's reply or the backoff's end, or in the stop's drain -- drops the frame still
  queued from before the pause (drop, why "paused") instead of sending it. So a frame packed before a pause
  is never sent inside it carrying its packing-time age (with a slow or restarting peer it would otherwise
  go out whenever the connection next allowed, seconds old and judged fresh); only a send already past that
  check when the flag is set completes, at the pause. A pause that ends before that attempt drops nothing.
  Phase 2's exit wants drop = 0 in every actual run, a pause run included (sdv/stack/step3.py): such a drop
  there is a finding; the paths with a drop are pytest's.

ACCOUNTING (spec 14.2): packed = replied + drop + lost_on_reconnect; ticks = packed + ticks_empty.
  One request is outstanding at a time; a frame packed while one is outstanding replaces the queued one
  (1-deep), the replaced one counted as drop, and while the tick is paused the queued one is dropped instead
  of sent (above). So the replied seqs, the dropped seqs and the lost seqs partition 1..packed. At a stop
  (the drain): no tick, no reconnect; the queued frame is sent at once if nothing is outstanding, the
  connection is open and the tick is not paused (paused, it is dropped as above), and
  every frame outstanding, the one at the stop or the queued one sent in the drain, gets its reply or the
  reply timeout; whatever is left is counted (lost or drop): the identity holds when a run ends. Per packed
  frame: age_over_max (seq and the slot that set the age), and with b0, b2 and b3 set the rule-26 spread
  (newest minus oldest of the three age-source timestamps, at their own resolution, never truncated to ms):
  spread_exceeded above SPREAD_EXCEEDED_MS, and on a 26 reply the attribution against the profile's
  ATTRIBUTION_SPREAD_MS (every 26 logged with both); r26_skip_window and r26_skip_ay with the profile table
  and rules.kinematics, as the guest computes them.

CONNECTION (spec 14.3 items 1-4 and 6)
  Connect at the first frame to send; after a close, reconnect only when the next frame is to be sent; a
  failed connect (refused, or not completed within the connect timeout) backs off from one tick, doubling,
  capped at 2 s. Before every send, a non-blocking recv(MSG_PEEK) checks whether the peer has closed, and
  reconnects first if it has. A frame sent and unanswered when the connection drops is lost_on_reconnect;
  so is one with no reply for 500 ms (the reply timeout, design decision b), after which the bridge closes
  the connection itself. "Lost" means unanswered, not unjudged: a frame given up after the reply timeout
  sits in the dead connection's receive buffer and a monitor that resumes may still judge it, so the
  guest's console totals (seen, accepted, rejected, and its kind 4 REJECT lines) can exceed the reply log
  by at most lost_on_reconnect; reason sets come from the reply log (reasonsets.py), whose records carry the
  64 bytes sent (`frame`, hex) for the frame-by-frame comparison of two replay runs. The connect log
  carries the digest, the profile and its source, the declared source vehicle, the mode, AGE_MAX and the
  sha256 of the generated contract.

SCENARIO LOCK (spec 14.3 item 5; owner, 2026-10-01: held while connected)
  An flock on a fixed path (/run/lock/sdv-scenario.lock). A path that cannot be opened, or that opens but is
  not a regular file (a character device such as /dev/null, a FIFO), is refused at start. By default the file
  is created if absent, and SDV_SCENARIO_LOCK or --lock moves it. SDV_SCENARIO_LOCK_MUST_EXIST=1 (the container
  image sets it) takes only the host's file, the one inode the host's updater checks: --lock and
  SDV_SCENARIO_LOCK may name no other path than /run/lock/sdv-scenario.lock, the bridge never creates the file,
  and the file must be a mount point (/proc/self/mountinfo: the host's file bind-mounted there with --mount).
  Anything else -- another path, a missing file, a file made inside the container, /dev/null mounted there --
  is refused at start, so a container started without the mount can never take a private lock of its own;
  only an explicit act defeats it (SDV_SCENARIO_LOCK_MUST_EXIST=0 as root, which then creates the file in
  /run/lock, or another file mounted at that path). Taken when a connect completes, before the connection
  counts as open, and released at its close: the bridge is CONNECTED exactly while it holds the lock, so
  nothing is ever sent without it, and it is free before the first connect, while a connect is pending (a
  guest that restarts), after a detected close and during the backoff. The lock gates the bridge's state
  and its sending, not the TCP connection the guest sees: that is open, and unlocked, from the end of the
  handshake until the claim thread sees the connect complete and takes the lock. A lock someone else holds
  closes the new connection unused, counts lock_busy and backs off like a failed connect; each such attempt
  was still a connection on the guest's side, so it leaves a "monitor: client done: seen=0 accepted=0
  rejected=0" line on the console at the backoff's spacing, which the bridge's log shows only as
  lock-busy. updater_check() is the updater's non-blocking check (the updater is Phase 6's; this is its
  double).

REASON 21 (spec 14.4; owner, 2026-10-01): logged once (stderr and the log), counted every time, and the
  bridge keeps sending: every frame is still judged. An uninjected 21 fails the run's exit condition.

INJECTION (spec 14.4, demos and tests only): nan (slot 0 a quiet NaN: 9), reserved (flag b5: 10), digest
  (one bit of the digest flipped: 21), profile0 (profile byte 0: 8, Phase 2 WP10 step 3), and the two
  pauses. Every one of them is refused when the target port is :7161 (the stamp port), whatever the
  config's stamp field says (stamp=False with :7161 is refused at start), and on any port marked stamp, so
  no injection can enter a timing run.

SCRIPT (Phase 2 WP10: plan step 3's scripted runs; --script FILE, or Bridge(script=...)): the control calls
  above, made by a script thread at fixed offsets: {"format": 1, "steps": [{"at_ns", "call", ["mode",
  "frames"]}, ...]}, the calls inject (mode and frames), pause_tick, resume_tick, pause_intake, resume_intake
  and end (the run ends as at --seconds: drain, summary). Each step runs at origin + at_ns on the source's own
  clock: the source's raw clock when it has one (raw_now_ns: replay's CLOCK_MONOTONIC before it is read down
  to the tick grid), else now_ns. The origin is the source's own when it names one (origin_ns: replay's grid
  anchor, where the file's first frame maps, so a step's at_ns is a recording offset), else the age-source
  timestamp of the first update the intake held (can: the receive time of the first frame; broker: the
  datapoint timestamp of the first value). Both are logged (script-origin, then one script-step record per
  step with its due and done instants on that clock) and in the summary's `script`. A script is checked whole
  at start (known calls with exactly their keys, at_ns ints >= 0 in order, an end step last if any); one with
  any step but end is refused on a stamp target, like the calls themselves. A step that fails ends the run.

DEMO-ODD WINDOW (spec 5.7; attribution-table 3.1 demo_odd_window): the run header's {profile_id, start_s,
  duration_s}, counted from the first packed frame. The bridge sends the demo profile only inside it,
  refuses one longer than that profile's generated run_window_max_ms, and logs the first and last seq.

DESIGN VALUES (spec 15; none is generated): the 10 Hz tick, the 500 ms reply timeout, the backoff (one
  tick, doubling, 2 s cap), :7161. This file's own choices, rows of spec 15 since (Phase 2's design decisions
  h-k): the connect timeout (the reply timeout's 500 ms; no lock is held while it runs), the write-back queue (WRITEBACK_QUEUE_MAX: one
  second of replies at the tick rate; each record carries the cumulative counters, so a dropped one loses
  no count), the stop's drain bound (two reply timeouts: the outstanding frame's, then the queued one's) and
  END_POLL_S (50 ms: how often main() looks for a signal, whose handler only sets a flag; Ending; also the
  script thread's longest single wait, so each step is re-timed against its clock at least that often).

DOES NOT DEMONSTRATE: any timing (the logs order events; nothing here is a measurement), what any source
delivers (bridge_sources.py's adapters; their tests use a fake databroker and a fake bus), or anything
about the guest beyond its replies. The Monitor write-back is the bridge's own view, labelled as such.
Nor a quiet process beside the claim thread: main()'s wait wakes every END_POLL_S (20 Hz) to look for a
signal and briefly takes the GIL, in every run, those aimed at :7161 included; a script's thread wakes at
least as often while a step is due. A script step's logged due and done instants order its call against the
ticks; neither is a timing.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import errno
import fcntl
import hashlib
import json
import os
import queue
import re
import select
import signal
import socket
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FRAME_DIR = REPO / "sdv" / "frame"
if str(FRAME_DIR) not in sys.path:
    sys.path.insert(0, str(FRAME_DIR))
import rules  # noqa: E402
import vssframe as vf  # noqa: E402

MS = 1_000_000

# Design values (spec 15 and 14.3; design decision b). None of them is generated.
TICK_HZ = 10
TICK_NS = 1_000_000_000 // TICK_HZ
REPLY_TIMEOUT_NS = 500 * MS
BACKOFF_FIRST_NS = TICK_NS
BACKOFF_CAP_NS = 2000 * MS
STAMP_PORT = 7161
# This file's choices (module docstring, DESIGN VALUES).
CONNECT_TIMEOUT_NS = REPLY_TIMEOUT_NS
WRITEBACK_QUEUE_MAX = TICK_HZ
DRAIN_NS = 2 * REPLY_TIMEOUT_NS
END_POLL_S = 0.05

MODES = ("broker", "can", "replay")
PROFILE_SOURCES = ("scenario", "live-default")
INJECTIONS = ("nan", "reserved", "digest", "profile0")
SCRIPT_FORMAT = 1
SCRIPT_CALLS = ("inject", "pause_tick", "resume_tick", "pause_intake", "resume_intake", "end")
QUIET_NAN_BITS = 0x7FC00000
RESERVED_FLAG = vf.F_RESERVED & -vf.F_RESERVED         # b5, the lowest reserved flag bit
GEAR_SLOT = vf.N_SLOTS - 1
RULE26_FLAGS = vf.F_SPEED | vf.F_STEER | vf.F_YAW
RULE26_SLOTS = tuple(i for i in range(vf.N_SLOTS) if RULE26_FLAGS & (1 << i))
DEFAULT_LOCK = "/run/lock/sdv-scenario.lock"             # the designated path (module docstring, SCENARIO LOCK)
LOCK_MUST_EXIST_ENV = "SDV_SCENARIO_LOCK_MUST_EXIST"     # "1": only the designated path, mounted, never created
MOUNTINFO = "/proc/self/mountinfo"                       # where a must-exist start reads whether the lock is mounted

# The Monitor branch the write-back fills (overlay.vspec, Vehicle.<project branch>.Monitor.VssClaim).
MONITOR_BRANCH = "Monitor.VssClaim"
WRITEBACK_LEAVES = ("Verdict", "Reason", "LastSeq", "Packed", "Replied", "Accepted", "Rejected", "Dropped",
                    "LostOnReconnect", "IsConnected", "Reconnects")

COUNTERS = ("ticks", "ticks_empty", "ticks_paused", "tick_overruns", "packed", "replied", "accepted", "rejected",
            "drop", "lost_on_reconnect", "age_negative", "age_over_max", "spread_exceeded", "r26_skip_window",
            "r26_skip_ay", "r21", "r21_injected", "injected", "demo_odd_frames", "sends", "peer_checks", "connects",
            "reconnects", "connect_failures", "lock_busy", "reply_timeouts", "reply_invalid", "stray_bytes")

DISCONNECTED, CONNECTING, CONNECTED = "disconnected", "connecting", "connected"


class BridgeError(RuntimeError):
    """A refusal: the bridge does not start, or a control call is refused."""


# --- what a source delivers ----------------------------------------------------------------------

@dataclass(frozen=True)
class Update:
    """One value from a source: slot 0..4 in vssframe's slot order, the value in its VSS unit (the bridge
    converts nothing), and its age-source timestamp in the source's own clock (the one Source.now_ns reads)."""
    slot: int
    value: Any
    t_ns: int


class QueueSource:
    """An in-process source: whatever pushes batches into it (a test, a demo driver) is the intake's stream.

    The protocol every source keeps: now_ns() reads the clock its timestamps are on; updates() is a
    blocking iterator of batches (iterables of Update); close() ends it."""

    def __init__(self, clock: Callable[[], int] = time.monotonic_ns) -> None:
        self._q: "queue.Queue[Optional[List[Update]]]" = queue.Queue()
        self._clock = clock

    def now_ns(self) -> int:
        return self._clock()

    def push(self, *updates: Update) -> None:
        self._q.put(list(updates))

    def updates(self) -> Iterator[List[Update]]:
        while True:
            batch = self._q.get()
            if batch is None:
                return
            yield batch

    def close(self) -> None:
        self._q.put(None)


def raw_of(slot: int, value: Any) -> int:
    """The slot's wire form: a float slot's binary32 bits (NaN and Inf kept as they are: the guest judges
    them, reason 9), the gear's int8. FrameError for what has none: a bool or a non-number, a finite value
    beyond binary32, a gear that is not an int in -128..127."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise vf.FrameError("slot %d: %r is not a number" % (slot, value))
    if slot == GEAR_SLOT:
        if not isinstance(value, int) or not -128 <= value <= 127:
            raise vf.FrameError("gear %r is not an int8" % (value,))
        return value
    try:
        fx = float(value)
    except OverflowError as err:
        raise vf.FrameError("slot %d: an integer beyond binary32" % slot) from err
    return vf.f32_bits(fx)


class HeldValues:
    """The latest value of each slot (its wire form) and its age-source timestamp. A slot once held stays
    held for the run: its flag is never cleared by age (spec 3). The intake writes and the tick reads
    through one lock, held only to copy: the locked snapshot of design decision c."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: List[Optional[Tuple[int, int]]] = [None] * vf.N_SLOTS

    def put(self, items: Sequence[Tuple[int, int, int]]) -> None:
        with self._lock:
            for slot, raw, t_ns in items:
                self._slots[slot] = (raw, t_ns)

    def snapshot(self) -> Tuple[Optional[Tuple[int, int]], ...]:
        with self._lock:
            return tuple(self._slots)


class Intake:
    """The intake loop: the source's stream into the held values. Pausable on its own: a pause keeps
    draining the stream and only stops updating the held values (so a resume never drains a stale
    backlog). It never waits on the stream while holding the held values' lock."""

    def __init__(self, held: HeldValues, log: "EventLog") -> None:
        self.held = held
        self.paused = threading.Event()
        self.n: Dict[str, int] = {"accepted": 0, "discarded": 0, "refused": 0}
        self._log = log
        # The age-source timestamp of the first update held (the earliest of its batch), once: a script's origin when
        # the source names none of its own (module docstring, SCRIPT). first_held is set with it.
        self.first_t_ns: Optional[int] = None
        self.first_held = threading.Event()

    def offer(self, updates: Iterable[Update]) -> None:
        """One batch: each item is held or refused on its own, so one malformed item (a FrameError, or anything
        else it raises, such as an object that is not an Update) never ends the stream."""
        items = []
        for u in updates:
            try:
                if isinstance(u.slot, bool) or not isinstance(u.slot, int) or not 0 <= u.slot < vf.N_SLOTS:
                    raise vf.FrameError("slot %r" % (u.slot,))
                if isinstance(u.t_ns, bool) or not isinstance(u.t_ns, int):
                    raise vf.FrameError("timestamp %r is not an int (ns)" % (u.t_ns,))
                items.append((u.slot, raw_of(u.slot, u.value), u.t_ns))
            except Exception as err:  # noqa: BLE001 -- one bad item is refused and counted, never the end of the intake
                self.n["refused"] += 1
                if self.n["refused"] == 1:
                    why = str(err) if isinstance(err, vf.FrameError) else "%s: %s" % (type(err).__name__, err)
                    self._log.write("update-refused", error=why, note="logged once; every one is counted")
        if self.paused.is_set():
            self.n["discarded"] += len(items)
            return
        if items:
            self.held.put(items)
            self.n["accepted"] += len(items)
            if self.first_t_ns is None:
                self.first_t_ns = min(t for _slot, _raw, t in items)
                self.first_held.set()

    def run(self, source: Any, stop: threading.Event) -> None:
        for batch in source.updates():
            if stop.is_set():
                return
            self.offer(batch)


# --- the run-level items ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    """The run-level items (attribution-table 3.1) and the target. extra_profile_ids binds a generated
    but uncompiled profile row, for tests only (rules.Tables' extra_ids): the guest would answer it with 8."""
    host: str
    port: int
    mode: str
    profile_id: int
    profile_source: str
    source_vehicle: Mapping[str, Any]
    demo_odd_window: Optional[Mapping[str, Any]] = None
    header_age_max_ms: Optional[int] = None
    stamp: Optional[bool] = None
    lock_path: Optional[str] = None
    extra_profile_ids: Tuple[int, ...] = ()

    @classmethod
    def from_header(cls, header: Mapping[str, Any], host: str, port: int, **kw: Any) -> "Config":
        """The bridge's items from a run header: bridge_mode, profile_id, profile_source, source_vehicle,
        age_max_ms and demo_odd_window."""
        missing = [k for k in ("bridge_mode", "profile_id", "profile_source", "source_vehicle", "age_max_ms") if k not in header]
        if missing:
            raise BridgeError("run header lacks %s" % ", ".join(missing))
        return cls(host=host, port=port, mode=header["bridge_mode"], profile_id=header["profile_id"],
                   profile_source=header["profile_source"], source_vehicle=header["source_vehicle"],
                   demo_odd_window=header.get("demo_odd_window"), header_age_max_ms=header["age_max_ms"], **kw)

    def is_stamp(self) -> bool:
        """A stamp target: the stamp port always (bind refuses stamp=False there), or another port marked stamp."""
        return self.port == STAMP_PORT or bool(self.stamp)

    def lock(self) -> str:
        return self.lock_path or os.environ.get("SDV_SCENARIO_LOCK") or DEFAULT_LOCK

    @staticmethod
    def lock_must_exist() -> bool:
        """SDV_SCENARIO_LOCK_MUST_EXIST: "1" takes only the designated lock file, mounted, and never creates it; unset or
        "0" takes the configured path and creates the file if absent (module docstring, SCENARIO LOCK)."""
        v = os.environ.get(LOCK_MUST_EXIST_ENV, "0")
        if v not in ("0", "1"):
            raise BridgeError("refused to start: %s=%r is not 0 or 1" % (LOCK_MUST_EXIST_ENV, v))
        return v == "1"


def _int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def bind(cfg: Config, contract: Any) -> Tuple[Optional[rules.Tables], List[str]]:
    """The profile tables the bridge judges its counters with, and every reason it refuses to start."""
    problems: List[str] = []
    if cfg.mode not in MODES:
        problems.append("bridge mode %r is not one of %s" % (cfg.mode, ", ".join(MODES)))
    if cfg.profile_source not in PROFILE_SOURCES:
        problems.append("profile source %r is not one of %s" % (cfg.profile_source, ", ".join(PROFILE_SOURCES)))
    if not _int(cfg.port) or not 0 < cfg.port < 65536:
        problems.append("port %r" % (cfg.port,))
    if cfg.port == STAMP_PORT and cfg.stamp is False:
        problems.append("stamp=False with the stamp port :%d: its replies always carry the stamps, and an injection is "
                        "always refused there (spec 14.4)" % STAMP_PORT)
    rows = {int(r["id"]): r for r in contract.PROFILES}
    try:
        tables: Optional[rules.Tables] = rules.Tables.from_contract(contract, extra_ids=tuple(cfg.extra_profile_ids))
    except (KeyError, ValueError) as err:
        return None, problems + ["extra profile ids %r: %s" % (cfg.extra_profile_ids, err)]
    assert tables is not None

    def bound(pid: Any, what: str) -> Optional[rules.Profile]:
        if not _int(pid) or not 0 <= pid <= 0xFF:
            problems.append("%s %r is not a profile id (0..255)" % (what, pid))
        elif pid == 0:
            problems.append("%s 0 is reserved and never bound (spec 5.1)" % what)
        elif pid not in rows:
            problems.append("%s %d is not in the generated profile table" % (what, pid))
        elif pid not in tables.profiles:
            problems.append("%s %d is generated but not compiled into the guest (compiled: %s); the guest would answer 8"
                            % (what, pid, ", ".join(str(i) for i in contract.COMPILED_PROFILE_IDS)))
        else:
            return tables.profiles[pid]
        return None

    pr = bound(cfg.profile_id, "profile")
    sv = cfg.source_vehicle if isinstance(cfg.source_vehicle, Mapping) else {}
    if not (isinstance(sv.get("name"), str) and _int(sv.get("wheelbase_mm"))):
        problems.append("the declared source vehicle must give its name and its wheelbase_mm (spec 5.6)")
        sv = {}
    if pr is not None and sv and sv["wheelbase_mm"] != pr.l_mm:
        problems.append("the declared source vehicle %r has wheelbase %d mm, not profile %d's L %d mm (spec 5.6, 14.4)"
                        % (sv["name"], sv["wheelbase_mm"], pr.id, pr.l_mm))
    if cfg.header_age_max_ms is not None and cfg.header_age_max_ms != contract.AGE_MAX_MS:
        problems.append("the run header's age_max_ms %r is not the generated AGE_MAX_MS %d" % (cfg.header_age_max_ms, contract.AGE_MAX_MS))
    w = cfg.demo_odd_window
    if w is not None:
        if not isinstance(w, Mapping) or set(w) != {"profile_id", "start_s", "duration_s"}:
            problems.append("demo_odd_window must be {profile_id, start_s, duration_s}, not %r" % (w,))
        else:
            dp = bound(w["profile_id"], "demo_odd_window profile")
            row = rows.get(w["profile_id"]) if dp is not None else None
            limit = row.get("run_window_max_ms") if row is not None else None
            if dp is not None and limit is None:
                problems.append("profile %d has no generated run window (run_window_max_ms): it is not a demo-ODD profile" % dp.id)
            if not (_num(w["start_s"]) and w["start_s"] >= 0):
                problems.append("demo_odd_window start_s %r must be >= 0" % (w["start_s"],))
            if not (_num(w["duration_s"]) and w["duration_s"] > 0):
                problems.append("demo_odd_window duration_s %r must be > 0" % (w["duration_s"],))
            elif limit is not None and w["duration_s"] * 1000 > limit:
                problems.append("demo_odd_window of %r s exceeds profile %d's generated run window of %d ms (spec 5.7)"
                                % (w["duration_s"], dp.id if dp else 0, limit))
            if dp is not None and sv and sv["wheelbase_mm"] != dp.l_mm:
                problems.append("the demo profile %d's L %d mm is not the declared source vehicle's wheelbase" % (dp.id, dp.l_mm))
    return tables, problems


def identity(n: Mapping[str, int]) -> Dict[str, Any]:
    """Spec 14.2's identity, packed = replied + drop + lost_on_reconnect, with its terms."""
    return {"packed": n["packed"], "replied": n["replied"], "drop": n["drop"], "lost_on_reconnect": n["lost_on_reconnect"],
            "holds": n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"]}


def ticks_identity(n: Mapping[str, int]) -> Dict[str, Any]:
    """ticks = packed + ticks_empty (spec 14.2)."""
    return {"ticks": n["ticks"], "packed": n["packed"], "ticks_empty": n["ticks_empty"],
            "holds": n["ticks"] == n["packed"] + n["ticks_empty"]}


def writeback_paths(contract: Any) -> Dict[str, str]:
    """Each write-back leaf's full VSS path, under the generated project branch's Monitor.VssClaim."""
    return {leaf: "%s.%s.%s" % (contract.PROJECT_BRANCH, MONITOR_BRANCH, leaf) for leaf in WRITEBACK_LEAVES}


# --- the script --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ScriptStep:
    """One scripted control call, at_ns after the script's origin on the source's own clock (module docstring, SCRIPT).
    mode and frames are an inject step's (the injection and how many packed frames carry it); every other call has none."""
    at_ns: int
    call: str
    mode: Optional[str] = None
    frames: Optional[int] = None

    def record(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"at_ns": self.at_ns, "call": self.call}
        if self.call == "inject":
            out.update(mode=self.mode, frames=self.frames)
        return out


def parse_script(doc: Any) -> Tuple[ScriptStep, ...]:
    """A run's script, {"format": 1, "steps": [{"at_ns", "call", ["mode", "frames"]}, ...]}, checked whole: every step a
    known call with exactly its keys (inject: a known injection and frames >= 1), at_ns ints >= 0 in non-decreasing
    order, and an end step, if any, the last. Anything else is a BridgeError (a refusal at start)."""
    if not isinstance(doc, Mapping) or set(doc) != {"format", "steps"} or doc.get("format") != SCRIPT_FORMAT:
        shown = sorted(doc) if isinstance(doc, Mapping) else doc
        raise BridgeError("a script is {\"format\": %d, \"steps\": [...]}, not %r" % (SCRIPT_FORMAT, shown))
    steps = doc["steps"]
    if not isinstance(steps, list):
        raise BridgeError("a script's steps are a list")
    out: List[ScriptStep] = []
    for n, s in enumerate(steps, 1):
        if not isinstance(s, Mapping):
            raise BridgeError("script step %d is not an object: %r" % (n, s))
        call = s.get("call")
        if call not in SCRIPT_CALLS:
            raise BridgeError("script step %d: call %r is not one of %s" % (n, call, ", ".join(SCRIPT_CALLS)))
        keys = {"at_ns", "call", "mode", "frames"} if call == "inject" else {"at_ns", "call"}
        if set(s) != keys:
            raise BridgeError("script step %d (%s) has keys %s, not %s" % (n, call, sorted(s), sorted(keys)))
        at = s["at_ns"]
        if not _int(at) or at < 0:
            raise BridgeError("script step %d: at_ns %r is not an int >= 0 (ns after the script's origin)" % (n, at))
        if out and at < out[-1].at_ns:
            raise BridgeError("script step %d at %d ns comes before step %d at %d ns: steps run in order" % (n, at, n - 1, out[-1].at_ns))
        if out and out[-1].call == "end":
            raise BridgeError("script step %d follows the end step: end is the last" % n)
        if call == "inject":
            if s["mode"] not in INJECTIONS:
                raise BridgeError("script step %d: injection %r is not one of %s" % (n, s["mode"], ", ".join(INJECTIONS)))
            if not _int(s["frames"]) or s["frames"] < 1:
                raise BridgeError("script step %d: frames %r is not an int >= 1" % (n, s["frames"]))
            out.append(ScriptStep(at, call, s["mode"], s["frames"]))
        else:
            out.append(ScriptStep(at, call))
    return tuple(out)


# --- logs ------------------------------------------------------------------------------------------

class EventLog:
    """JSON lines, in memory and (with a path) in a file; every record carries t_mono, which orders the
    records; these timestamps make no performance claim.

    While a writer thread is set (the claim thread, for a run's duration), only it writes the file: a record
    from any other thread (the intake, a control call) is appended in memory under a lock held only to
    append, and reaches the file at the writer's next flush. So the claim thread never waits on another
    thread's file I/O. With no writer set, the caller writes the file itself."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._lock = threading.Lock()                # the records: held only to append or swap
        self._flock = threading.Lock()               # the file: taken only by the thread that flushes
        self.records: List[Dict[str, Any]] = []
        self._pending: List[Dict[str, Any]] = []
        self._writer: Optional[threading.Thread] = None
        self._f = open(path, "a", encoding="utf-8", buffering=1) if path is not None else None

    def set_writer(self, thread: Optional[threading.Thread]) -> None:
        self._writer = thread
        if thread is None:
            self.flush()

    def write(self, event: str, **fields: Any) -> Dict[str, Any]:
        rec: Dict[str, Any] = {"event": event, "t_mono": time.monotonic_ns()}
        rec.update(fields)
        with self._lock:
            self.records.append(rec)
            if self._f is not None:
                self._pending.append(rec)
        writer = self._writer
        if writer is None or writer is threading.current_thread():
            self.flush()
        return rec

    def flush(self) -> None:
        with self._flock:
            with self._lock:
                pending, self._pending = self._pending, []
            if self._f is not None:
                for rec in pending:
                    self._f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")

    def find(self, event: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [r for r in self.records if r["event"] == event]

    def close(self) -> None:
        self._writer = None
        self.flush()
        with self._flock:
            if self._f is not None:
                self._f.close()
                self._f = None


# --- packing and accounting ------------------------------------------------------------------------

@dataclass
class Packed:
    seq: int
    frame: bytes
    profile: int
    inject: Optional[str]
    demo: bool
    age_ms: int
    age_slot: int
    spread_ns: Optional[int]
    a_y_kin: Optional[float]
    src_now_ns: int
    tstamp_ns: int
    sent_mono: Optional[int] = None


class ClaimCore:
    """Packing and accounting: no I/O and no clock of its own (every instant is passed in), so the tests can
    drive it deterministically. Only the claim thread calls it, except set_injection."""

    def __init__(self, cfg: Config, contract: Any, tables: rules.Tables, log: EventLog) -> None:
        self.cfg = cfg
        self.contract = contract
        self.tables = tables
        self.log = log
        self.stamp = cfg.is_stamp()
        self.n: Dict[str, int] = {k: 0 for k in COUNTERS}
        self.by_reason: "collections.Counter[int]" = collections.Counter()
        self.rejected_by_origin: "collections.Counter[str]" = collections.Counter()
        self.next_seq = 1
        self.queued: Optional[Packed] = None
        self.replied_seqs: List[int] = []
        self.dropped_seqs: List[int] = []
        self.lost_seqs: List[int] = []
        self.first_mono: Optional[int] = None
        self.r21_logged = False
        self.last: Optional[Tuple[int, int, int]] = None          # verdict, reason, seq of the last reply
        w = cfg.demo_odd_window
        self.demo_window: Optional[Tuple[int, int, int]] = None
        if w is not None:
            self.demo_window = (int(w["profile_id"]), int(round(w["start_s"] * 1e9)), int(round(w["duration_s"] * 1e9)))
        self.demo: Dict[str, Any] = {"first_seq": None, "last_seq": None, "frames": 0, "logged": False}
        self._inject_lock = threading.Lock()
        self._inject: Optional[str] = None
        self._inject_left: Optional[int] = None

    def set_injection(self, mode: Optional[str], frames: Optional[int]) -> None:
        with self._inject_lock:
            self._inject, self._inject_left = mode, (frames if mode is not None else None)

    def _take_injection(self) -> Optional[str]:
        with self._inject_lock:
            mode = self._inject
            if mode is not None and self._inject_left is not None:
                self._inject_left -= 1
                if self._inject_left <= 0:
                    self._inject, self._inject_left = None, None
            return mode

    def _profile_at(self, mono_ns: int) -> Tuple[int, bool]:
        if self.demo_window is None or self.first_mono is None:
            return self.cfg.profile_id, False
        pid, start, dur = self.demo_window
        el = mono_ns - self.first_mono
        if start <= el < start + dur:
            return pid, True
        return self.cfg.profile_id, False

    def tick(self, snapshot: Sequence[Optional[Tuple[int, int]]], src_now_ns: int, mono_ns: int) -> Optional[Packed]:
        """One tick: a frame packed and queued if any slot is held, else ticks_empty. A tick is counted with its
        frame or as empty, never before: a pack that raises leaves ticks = packed + ticks_empty whole."""
        if all(s is None for s in snapshot):
            self.n["ticks"] += 1
            self.n["ticks_empty"] += 1
            return None
        p = self.pack(snapshot, src_now_ns, mono_ns)
        self.enqueue(p)
        return p

    def pack(self, snapshot: Sequence[Optional[Tuple[int, int]]], src_now_ns: int, mono_ns: int) -> Packed:
        """Only tick() calls this: the tick is counted here, together with its frame."""
        if self.next_seq >= vf.SENTINEL_SEQ:
            raise BridgeError("seq would reach the sentinel %#x: a new run starts from 1" % vf.SENTINEL_SEQ)
        seq = self.next_seq
        if self.first_mono is None:
            self.first_mono = mono_ns
        present = [i for i, s in enumerate(snapshot) if s is not None]
        times = [snapshot[i][1] for i in present]          # type: ignore[index]
        age, negative = vf.age_field(src_now_ns, times)
        oldest = min(times)
        age_slot = next(i for i in present if snapshot[i][1] == oldest)   # type: ignore[index]
        slot_bits: List[Optional[int]] = [snapshot[i][0] if snapshot[i] is not None else None for i in range(GEAR_SLOT)]  # type: ignore[index]
        gear = snapshot[GEAR_SLOT][0] if snapshot[GEAR_SLOT] is not None else None  # type: ignore[index]
        profile, demo = self._profile_at(mono_ns)
        digest = int(self.contract.CATALOG_DIGEST)
        inject = self._take_injection()
        honest_profile = profile
        if inject == "nan":
            slot_bits[0] = QUIET_NAN_BITS
        elif inject == "digest":
            digest ^= 1
        elif inject == "profile0":
            profile, demo = 0, False
        frame = vf.pack_bits(seq, mono_ns, profile, digest, slot_bits, gear, age)
        if inject == "reserved":
            b = bytearray(frame)
            b[vf.FRAME_HEADER_BYTES + vf.P_FLAGS] |= RESERVED_FLAG
            frame = bytes(b)
        self.next_seq += 1
        self.n["packed"] += 1
        self.n["ticks"] += 1
        spread, a_y = self._intake_counters(seq, snapshot, honest_profile)
        if negative:
            self.n["age_negative"] += 1
            self.log.write("age-negative", seq=seq)
        if age > self.contract.AGE_MAX_MS:
            self.n["age_over_max"] += 1
            self.log.write("age-over-max", seq=seq, age_ms=age, slot=age_slot)
        if inject is not None:
            self.n["injected"] += 1
        if demo:
            self.n["demo_odd_frames"] += 1
            self.demo["frames"] += 1
            if self.demo["first_seq"] is None:
                self.demo["first_seq"] = seq
            self.demo["last_seq"] = seq
        elif self.demo["first_seq"] is not None and not self.demo["logged"] and inject is None:
            self.log_demo_window()
        return Packed(seq=seq, frame=frame, profile=profile, inject=inject, demo=demo, age_ms=age, age_slot=age_slot,
                      spread_ns=spread, a_y_kin=a_y, src_now_ns=src_now_ns, tstamp_ns=mono_ns)

    def log_demo_window(self) -> None:
        if self.demo["first_seq"] is None or self.demo["logged"]:
            return
        self.demo["logged"] = True
        assert self.demo_window is not None
        self.log.write("demo-odd-window", profile_id=self.demo_window[0], first_seq=self.demo["first_seq"],
                       last_seq=self.demo["last_seq"], frames=self.demo["frames"])

    def _intake_counters(self, seq: int, snapshot: Sequence[Optional[Tuple[int, int]]], pid: int) -> Tuple[Optional[int], Optional[float]]:
        """The rule-26 spread and skip counters for a frame with b0, b2 and b3 (spec 14.2)."""
        if any(snapshot[i] is None for i in RULE26_SLOTS):
            return None, None
        ts = [snapshot[i][1] for i in RULE26_SLOTS]          # type: ignore[index]
        spread = max(ts) - min(ts)
        if spread > self.contract.SPREAD_EXCEEDED_MS * MS:
            self.n["spread_exceeded"] += 1
            self.log.write("spread-exceeded", seq=seq, spread_ns=spread)
        pr = self.tables.profiles.get(pid)
        bits = [snapshot[i][0] for i in RULE26_SLOTS]        # type: ignore[index]
        if pr is None or not all(vf.f32_is_finite_bits(b) for b in bits):
            return spread, None
        v, d = vf.bits_f32(bits[0]), vf.bits_f32(bits[1])
        av, ad = rules.dabs(v), rules.dabs(d)
        if not pr.v26_lo <= av <= pr.v26_hi:
            self.n["r26_skip_window"] += 1
            return spread, None
        if ad > pr.delta_max:
            return spread, None                              # rule 25 comes first, and tan's domain ends there
        _kin, a_y = rules.kinematics(av, ad, pr.l_mm, self.tables)
        if pr.ay26_max != 0.0 and a_y > pr.ay26_max:
            self.n["r26_skip_ay"] += 1
        return spread, a_y

    def enqueue(self, p: Packed) -> None:
        """The 1-deep queue: a frame packed while one waits replaces it, and the replaced one is a drop."""
        if self.queued is not None:
            self.drop(self.queued, "replaced")
        self.queued = p

    def take(self) -> Optional[Packed]:
        p, self.queued = self.queued, None
        return p

    def drop(self, p: Packed, why: str) -> None:
        self.n["drop"] += 1
        self.dropped_seqs.append(p.seq)
        self.log.write("dropped", seq=p.seq, why=why)

    def lost(self, p: Packed, why: str) -> None:
        self.n["lost_on_reconnect"] += 1
        self.lost_seqs.append(p.seq)
        self.log.write("lost", seq=p.seq, why=why, sent_mono=p.sent_mono)

    def _reply_problem(self, p: Packed, data: bytes) -> Optional[str]:
        h = vf.FRAME_HEADER_BYTES
        if len(data) != vf.FRAME_TOTAL_BYTES:
            return "a reply of %d bytes" % len(data)
        free = {h + vf.P_VERDICT, h + vf.P_REASON}
        if self.stamp:
            free.update(range(h + vf.STAMP_SPAN[0], h + vf.STAMP_SPAN[1]))
        diff = [i for i in range(len(data)) if i not in free and data[i] != p.frame[i]]
        if diff:
            return "bytes %s differ from the request (seq %d)" % (diff[:8], p.seq)
        verdict, reason = data[h + vf.P_VERDICT], data[h + vf.P_REASON]
        if verdict not in (rules.V_ACCEPT, rules.V_REJECT) or (verdict == rules.V_ACCEPT) != (reason == rules.RSN_OK):
            return "verdict %d with reason %d" % (verdict, reason)
        return None

    def reply(self, p: Packed, data: bytes) -> Tuple[bool, Dict[str, Any]]:
        """A reply to the outstanding frame: (True, its record), or (False, why) with the frame counted lost."""
        problem = self._reply_problem(p, data)
        if problem is not None:
            self.n["reply_invalid"] += 1
            self.log.write("reply-invalid", seq=p.seq, why=problem)
            self.lost(p, "invalid reply")
            return False, {"why": problem}
        h = vf.FRAME_HEADER_BYTES
        verdict, reason = data[h + vf.P_VERDICT], data[h + vf.P_REASON]
        self.n["replied"] += 1
        self.replied_seqs.append(p.seq)
        self.by_reason[reason] += 1
        self.last = (verdict, reason, p.seq)
        rec: Dict[str, Any] = {"seq": p.seq, "verdict": verdict, "reason": reason, "profile": p.profile, "inject": p.inject,
                               "demo": p.demo, "age_ms": p.age_ms, "src_now_ns": p.src_now_ns, "tstamp_ns": p.tstamp_ns,
                               "frame": p.frame.hex()}
        if verdict == rules.V_ACCEPT:
            self.n["accepted"] += 1
        else:
            self.n["rejected"] += 1
            self.rejected_by_origin["injected" if p.inject else "demo_odd" if p.demo else "other"] += 1
        if reason == rules.RSN_VSS_CATALOG:
            self.n["r21"] += 1
            if p.inject:
                self.n["r21_injected"] += 1
            if not self.r21_logged:
                self.r21_logged = True
                msg = ("reason 21 vss-catalog-mismatch at seq %d: the guest's catalogue digest is not this bridge's 0x%08X; "
                       "sending goes on (every frame is still judged); the run fails its exit condition%s"
                       % (p.seq, self.contract.CATALOG_DIGEST, " (this frame was injected)" if p.inject else ""))
                self.log.write("catalog-mismatch", seq=p.seq, injected=bool(p.inject), note=msg,
                               counted="every 21 is counted (r21); this line is written once")
                print("vss_claim_bridge: " + msg, file=sys.stderr, flush=True)
        if reason == rules.RSN_VSS_YAW:
            attr_ms = self.contract.ATTRIBUTION_SPREAD_MS.get(p.profile)
            rec["spread_ns"] = p.spread_ns
            rec["attribution_spread_ms"] = attr_ms
            rec["attributed"] = bool(attr_ms is not None and p.spread_ns is not None and p.spread_ns > attr_ms * MS)
        if self.stamp:
            rec["t_in_ns"] = int.from_bytes(data[h + vf.P_T_IN:h + vf.P_T_IN + 8], "little")
            rec["t_out_ns"] = int.from_bytes(data[h + vf.P_T_OUT:h + vf.P_T_OUT + 8], "little")
        return True, rec

    def seq_partition(self) -> Dict[str, Any]:
        """The replied, dropped and lost seqs partition 1..packed (seq is assigned at packing)."""
        r, d, lo = set(self.replied_seqs), set(self.dropped_seqs), set(self.lost_seqs)
        disjoint = len(r) + len(d) + len(lo) == len(r | d | lo) == len(self.replied_seqs) + len(self.dropped_seqs) + len(self.lost_seqs)
        whole = (r | d | lo) == set(range(1, self.n["packed"] + 1))
        return {"holds": disjoint and whole, "disjoint": disjoint, "covers_1_to_packed": whole,
                "gaps_in_replied": self.n["packed"] - len(r)}


# --- the reconnect backoff and the scenario lock ---------------------------------------------------

class Backoff:
    """Spec 14.3 item 2 and 15: from one tick, doubling, capped at 2 s; reset by a connect."""

    def __init__(self) -> None:
        self._next = BACKOFF_FIRST_NS

    def reset(self) -> None:
        self._next = BACKOFF_FIRST_NS

    def next_ns(self) -> int:
        d = self._next
        self._next = min(2 * d, BACKOFF_CAP_NS)
        return d


class LockFileError(BridgeError):
    """The scenario lock's path opens but is not a regular file: an flock there is no scenario lock."""


def _file_kind(mode: int) -> str:
    for test, name in ((stat.S_ISCHR, "a character device"), (stat.S_ISBLK, "a block device"), (stat.S_ISFIFO, "a FIFO"),
                       (stat.S_ISSOCK, "a socket"), (stat.S_ISDIR, "a directory")):
        if test(mode):
            return name
    return "of file type %#o" % stat.S_IFMT(mode)


class ScenarioLock:
    """The scenario lock, as an flock on a fixed path: the kernel drops it if the bridge dies. Every open checks that
    the path is a regular file (LockFileError if not); the path is opened afresh at each connect."""

    def __init__(self, path: str, create: bool = True) -> None:
        self.path = Path(path)
        self.create = create
        self._flags = os.O_RDWR | (os.O_CREAT if create else 0)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def _open(self) -> int:
        fd = os.open(str(self.path), self._flags, 0o644)
        try:
            mode = os.fstat(fd).st_mode
        except BaseException:
            os.close(fd)
            raise
        if not stat.S_ISREG(mode):
            os.close(fd)
            raise LockFileError("the scenario lock %s is %s, not a regular file: an flock there is no scenario lock"
                                % (self.path, _file_kind(mode)))
        return fd

    def probe(self) -> None:
        """At start: the lock file can be opened (created if absent, unless create is False) and is a regular file,
        so a bad path is a refusal, not a fatal at the first connect. OSError or LockFileError if not. It takes no
        lock."""
        os.close(self._open())

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def mount_points(path: Optional[str] = None) -> List[str]:
    """The mount points /proc/self/mountinfo lists (proc(5): the fifth field, with the kernel's octal escapes of space,
    tab, newline and backslash undone). OSError if it cannot be read."""
    with open(path or MOUNTINFO, encoding="utf-8", errors="surrogateescape") as f:
        fields = [line.split(" ") for line in f]
    return [re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), x[4]) for x in fields if len(x) > 4]


def _lock_hint(err: OSError, must_exist: bool) -> str:
    """What to do about a lock file that cannot be opened, by errno (only the must-exist setting needs a hint)."""
    if not must_exist:
        return ""
    if err.errno == errno.ENOENT:
        return (" (%s=1: the bridge never creates it; it must be the host's lock file, bind-mounted there with "
                "--mount type=bind,src=<the host's file>,dst=%s)" % (LOCK_MUST_EXIST_ENV, DEFAULT_LOCK))
    if err.errno in (errno.EACCES, errno.EPERM):
        return (" (%s=1: the file is there, but this user cannot open it read-write: run the container as the host "
                "file's owner, --user UID:GID)" % LOCK_MUST_EXIST_ENV)
    if err.errno == errno.EROFS:
        return " (%s=1: the file is mounted read-only; mount it read-write)" % LOCK_MUST_EXIST_ENV
    if err.errno == errno.EISDIR:
        return (" (%s=1: a directory, which `docker run -v` leaves for a missing host file; create the host's file first "
                "and mount it with --mount type=bind, which refuses a missing source)" % LOCK_MUST_EXIST_ENV)
    return ""


def scenario_lock(cfg: Config) -> ScenarioLock:
    """The run's scenario lock, checked at start (module docstring, SCENARIO LOCK); every refusal is a BridgeError.
    With SDV_SCENARIO_LOCK_MUST_EXIST=1: the designated path only, an existing regular file, and a mount point."""
    must = cfg.lock_must_exist()
    path = cfg.lock()
    if must and path != DEFAULT_LOCK:
        named = "--lock" if cfg.lock_path else "SDV_SCENARIO_LOCK"
        raise BridgeError("refused to start: %s names the scenario lock %s, but with %s=1 the bridge takes only %s, the "
                          "host's lock file bind-mounted there: another file would be a private lock the host's updater "
                          "never sees" % (named, path, LOCK_MUST_EXIST_ENV, DEFAULT_LOCK))
    lock = ScenarioLock(path, create=not must)
    try:
        lock.probe()
    except LockFileError as err:
        raise BridgeError("refused to start: %s" % err) from err
    except OSError as err:
        raise BridgeError("refused to start: the scenario lock %s cannot be opened: %s%s" % (path, err, _lock_hint(err, must))) from err
    if must:
        try:
            mounted = path in mount_points()
        except OSError as err:
            raise BridgeError("refused to start: %s=1 and %s cannot be read to check that the scenario lock %s is mounted: %s"
                              % (LOCK_MUST_EXIST_ENV, MOUNTINFO, path, err)) from err
        if not mounted:
            raise BridgeError("refused to start: the scenario lock %s is not a mount point: with %s=1 it must be the host's "
                              "lock file, bind-mounted there (--mount type=bind,src=<the host's file>,dst=%s); a file made "
                              "inside the container is a private lock the host's updater never sees"
                              % (path, LOCK_MUST_EXIST_ENV, path))
    return lock


def updater_check(path: str) -> bool:
    """The updater's non-blocking check (the updater is Phase 6's; this is its double): may a scenario
    switch go ahead now? False while the bridge (anyone) holds the lock."""
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


# --- the write-back --------------------------------------------------------------------------------

class WriteBack:
    """The queue to the gRPC side (design decision c): offer() never blocks; a full queue drops the record
    and counts it. With no sink there is no write-back at all (nothing offered, nothing counted)."""

    def __init__(self, sink: Optional[Callable[[Dict[str, Any]], None]], maxsize: int = WRITEBACK_QUEUE_MAX) -> None:
        self.sink = sink
        self.q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize)
        self.n: Dict[str, int] = {"offered": 0, "written": 0, "dropped": 0, "failed": 0}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.sink is not None:
            self._thread = threading.Thread(target=self._run, name="vss-bridge-writeback", daemon=True)
            self._thread.start()

    def offer(self, rec: Dict[str, Any]) -> None:
        if self.sink is None:
            return
        self.n["offered"] += 1
        try:
            self.q.put_nowait(rec)
        except queue.Full:
            self.n["dropped"] += 1

    def _run(self) -> None:
        assert self.sink is not None
        while not self._stop.is_set():
            try:
                rec = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self.sink(rec)
                self.n["written"] += 1
            except Exception:  # noqa: BLE001 -- a failing sink is counted; it never reaches the tick
                self.n["failed"] += 1

    def stop(self, timeout: float) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True


# --- the bridge ------------------------------------------------------------------------------------

def contract_sha256(contract: Any) -> Optional[str]:
    path = getattr(contract, "__file__", None)
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Bridge:
    """The bridge: the intake, the claim thread, the write-back and the scenario lock around ClaimCore."""

    def __init__(self, cfg: Config, source: Any, *, contract: Any = None, gen_dir: Optional[os.PathLike] = None,
                 writeback_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
                 observer: Optional[Callable[[str], None]] = None, run_dir: Optional[Path] = None,
                 writeback_max: int = WRITEBACK_QUEUE_MAX, on_end: Optional[Callable[[], None]] = None,
                 script: Optional[Sequence[ScriptStep]] = None) -> None:
        self.contract = contract if contract is not None else vf.load_contract(gen_dir)
        tables, problems = bind(cfg, self.contract)
        if script is not None:
            controls = sorted({s.call for s in script if s.call != "end"})
            if controls and cfg.is_stamp():
                problems.append("a script with %s on the stamp port :%d (or a port marked stamp): no injection or pause enters "
                                "a timing run (spec 14.4)" % (", ".join(controls), cfg.port))
        if problems or tables is None:
            raise BridgeError("refused to start: " + "; ".join(problems))
        try:
            infos = socket.getaddrinfo(cfg.host, cfg.port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError as err:
            raise BridgeError("refused to start: cannot resolve %r: %s" % (cfg.host, err)) from err
        self.addr = infos[0][4]
        self.lock = scenario_lock(cfg)
        self.cfg = cfg
        self.source = source
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self._made_run_dir = False
        if self.run_dir is not None:
            self._made_run_dir = not self.run_dir.exists()
            self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log = EventLog(self.run_dir / "bridge.jsonl" if self.run_dir else None)
        self.replies = EventLog(self.run_dir / "replies.jsonl" if self.run_dir else None)
        self.core = ClaimCore(cfg, self.contract, tables, self.log)
        self.held = HeldValues()
        self.intake = Intake(self.held, self.log)
        self.writeback = WriteBack(writeback_sink, writeback_max)
        self.backoff = Backoff()
        self.observer = observer
        self.on_end = on_end
        self.contract_sha256 = contract_sha256(self.contract)
        self.stamp = cfg.is_stamp()
        self.fatal: Optional[str] = None
        self._state = DISCONNECTED
        self._sock: Optional[socket.socket] = None
        self._out: Optional[Packed] = None
        self._rbuf = b""
        self._reply_due = 0
        self._connect_due = 0
        self._connect_started: Optional[int] = None
        self._next_connect = 0
        self._draining = False
        self._stopping = threading.Event()
        self._intake_stop = threading.Event()
        self._tick_paused = threading.Event()
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._claim_thread = threading.Thread(target=self._claim_main, name="vss-bridge-claim", daemon=True)
        self._intake_thread = threading.Thread(target=self._intake_main, name="vss-bridge-intake", daemon=True)
        self.script: Optional[Tuple[ScriptStep, ...]] = tuple(script) if script is not None else None
        self.script_state: Optional[Dict[str, Any]] = (
            {"steps": len(self.script), "done": 0, "origin_ns": None, "origin": None, "ended_run": False, "error": None}
            if self.script is not None else None)
        self._script_stop = threading.Event()
        self._script_thread = threading.Thread(target=self._script_main, name="vss-bridge-script", daemon=True)
        self._started = False
        self._summary: Optional[Dict[str, Any]] = None

    # -- control (any thread) --

    def start(self) -> "Bridge":
        try:
            self._src_now()                              # a source whose clock is not int ns is refused before any thread
        except BaseException:
            self._discard_run_dir()
            raise
        self.log.write("start", **self.run_items())
        if self.script is not None:
            self.log.write("script", steps=[s.record() for s in self.script])
        self.log.set_writer(self._claim_thread)
        self._started = True
        self.writeback.start()
        self._intake_thread.start()
        self._claim_thread.start()
        if self.script is not None:
            self._script_thread.start()
        return self

    def _discard_run_dir(self) -> None:
        """A refused start leaves no run behind: it closes both logs, removes each that is still empty, and removes
        the run directory if this bridge made it and it is then empty, so the same --out or --name runs next time.
        A log that holds records (bridge_sources.py writes what it opened before the start) is kept."""
        self.log.close()
        self.replies.close()
        if self.run_dir is None:
            return
        for name in ("bridge.jsonl", "replies.jsonl"):
            try:
                if (self.run_dir / name).stat().st_size == 0:
                    (self.run_dir / name).unlink()
            except OSError:
                pass
        if self._made_run_dir:
            try:
                self.run_dir.rmdir()                     # only when empty
            except OSError:
                pass

    def run_items(self) -> Dict[str, Any]:
        """What the connect log carries (spec 14.3 item 6), plus the target."""
        return {"digest": "0x%08X" % self.contract.CATALOG_DIGEST, "profile_id": self.cfg.profile_id,
                "profile_source": self.cfg.profile_source, "source_vehicle": dict(self.cfg.source_vehicle),
                "mode": self.cfg.mode, "age_max_ms": self.contract.AGE_MAX_MS, "contract_sha256": self.contract_sha256,
                "demo_odd_window": dict(self.cfg.demo_odd_window) if self.cfg.demo_odd_window else None,
                "target": {"host": self.cfg.host, "port": self.cfg.port, "stamp": self.stamp}}

    def _refuse_on_stamp(self, what: str) -> None:
        if self.cfg.port == STAMP_PORT or self.stamp:
            self.log.write("injection-refused", what=what, port=self.cfg.port)
            raise BridgeError("%s refused: the target is the stamp port :%d, and an injection never enters a timing run (spec 14.4)"
                              % (what, self.cfg.port))

    def inject(self, mode: Optional[str], frames: Optional[int] = 1) -> None:
        """Inject into the next `frames` packed frames (None: until inject(None))."""
        self._refuse_on_stamp("injection %s" % mode)
        if mode is not None and mode not in INJECTIONS:
            raise BridgeError("injection %r is not one of %s" % (mode, ", ".join(INJECTIONS)))
        self.core.set_injection(mode, frames)
        self.log.write("inject", mode=mode, frames=frames)

    def pause_tick(self) -> None:
        self._refuse_on_stamp("pause tick")
        self.log.write("pause", what="tick")         # before the flag: a 'paused' drop never precedes its pause in the log
        self._tick_paused.set()

    def resume_tick(self) -> None:
        self._tick_paused.clear()
        self.log.write("resume", what="tick")

    def pause_intake(self) -> None:
        self._refuse_on_stamp("pause intake")
        self.intake.paused.set()
        self.log.write("pause", what="intake")

    def resume_intake(self) -> None:
        self.intake.paused.clear()
        self.log.write("resume", what="intake")

    @property
    def connected(self) -> bool:
        return self._state == CONNECTED

    def counters(self) -> Dict[str, int]:
        return dict(self.core.n)

    def stop(self) -> Dict[str, Any]:
        """Stop ticking, drain (module docstring, ACCOUNTING), close, and return the summary."""
        if self._summary is not None:
            return self._summary
        self._script_stop.set()                          # no scripted call once the stop begins
        if self._script_thread.is_alive() and self._script_thread is not threading.current_thread():
            self._script_thread.join(1.0)
        self._stopping.set()
        self._wake()
        if self._started:
            self._claim_thread.join(DRAIN_NS / 1e9 + 2.0)
        self._intake_stop.set()
        try:
            self.source.close()
        except Exception as err:  # noqa: BLE001 -- the source's own problem, recorded
            self.log.write("source-close-failed", error=repr(err))
        if self._started:
            self._intake_thread.join(1.0)
        wb_stopped = self.writeback.stop(0.5)
        s = self.summary()
        s["threads"] = {"claim_alive": self._claim_thread.is_alive(), "intake_alive": self._intake_thread.is_alive(),
                        "writeback_stopped": wb_stopped, "script_alive": self._script_thread.is_alive()}
        self.log.write("stop", identity_holds=s["identity"]["holds"], ticks_identity_holds=s["ticks_identity"]["holds"],
                       fatal=self.fatal)
        if self.run_dir is not None:
            (self.run_dir / "summary.json").write_text(json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        self.log.close()
        self.replies.close()
        self._wake_r.close()
        self._wake_w.close()
        self._summary = s
        return s

    def summary(self) -> Dict[str, Any]:
        n = dict(self.core.n)
        return {
            "run_items": self.run_items(),
            "counters": n,
            "identity": identity(n),
            "ticks_identity": ticks_identity(n),
            "seq_partition": self.core.seq_partition(),
            "in_flight": {"outstanding": self._out.seq if self._out else None,
                          "queued": self.core.queued.seq if self.core.queued else None},
            "by_reason": {str(k): v for k, v in sorted(self.core.by_reason.items())},
            "rejected_by_origin": dict(self.core.rejected_by_origin),
            "r21_uninjected": n["r21"] - n["r21_injected"],
            "demo_odd": ({k: self.core.demo[k] for k in ("first_seq", "last_seq", "frames")}
                         if self.cfg.demo_odd_window is not None else None),
            "intake": dict(self.intake.n),
            "writeback": dict(self.writeback.n) if self.writeback.sink is not None else None,
            "script": dict(self.script_state) if self.script_state is not None else None,
            "fatal": self.fatal,
        }

    # -- threads --

    def _wake(self) -> None:
        try:
            self._wake_w.send(b"x")
        except OSError:
            pass

    def _intake_main(self) -> None:
        try:
            self.intake.run(self.source, self._intake_stop)
        except Exception as err:  # noqa: BLE001 -- a broken stream is logged; the ticks go on, the values age into 22
            self.log.write("intake-failed", error="%s: %s" % (type(err).__name__, err))
        if not self._intake_stop.is_set():
            self.log.write("intake-ended")

    def _script_clock(self) -> int:
        """The script's clock: the source's raw clock if it has one (replay's, before the grid), else its now_ns."""
        fn = getattr(self.source, "raw_now_ns", None)
        t = fn() if callable(fn) else self.source.now_ns()
        if not _int(t):
            raise BridgeError("the source's script clock returned %r, not an int of ns" % (t,))
        return t

    def _script_origin(self) -> Optional[int]:
        """The source's own origin (origin_ns: replay's grid anchor), else the first held update's age-source timestamp,
        waited for; None if the run stops first. Logged once (script-origin) and kept in the summary."""
        assert self.script_state is not None
        fn = getattr(self.source, "origin_ns", None)
        if callable(fn):
            origin, how = fn(), "the source's origin_ns (replay: the grid anchor the file's first frame maps to)"
        else:
            while not self.intake.first_held.wait(END_POLL_S):
                if self._script_stop.is_set():
                    return None
            origin, how = self.intake.first_t_ns, "the age-source timestamp of the first update the intake held"
        if not _int(origin):
            raise BridgeError("the script's origin %r is not an int of ns" % (origin,))
        self.script_state.update(origin_ns=origin, origin=how)
        self.log.write("script-origin", origin_ns=origin, origin=how)
        return origin

    def _end_run(self) -> None:
        """A script's end step (or its failure): the run ends as at --seconds, through on_end (main's)."""
        assert self.script_state is not None
        self.script_state["ended_run"] = True
        if self.on_end is not None:
            self.on_end()

    def _script_call(self, step: ScriptStep) -> None:
        if step.call == "inject":
            self.inject(step.mode, step.frames)
        elif step.call == "end":
            self._end_run()
        else:
            getattr(self, step.call)()

    def _script_main(self) -> None:
        """The script thread (module docstring, SCRIPT): each step at origin + at_ns on the script's clock, made through the
        control calls any thread may make (they take no lock the claim thread waits on), each logged with its due and done
        instants. It waits at most END_POLL_S at a time, re-reading the clock. A step that raises ends the run."""
        assert self.script is not None and self.script_state is not None
        try:
            origin = self._script_origin()
            if origin is None:
                return
            for n, step in enumerate(self.script, 1):
                due = origin + step.at_ns
                while not self._script_stop.is_set():
                    left = due - self._script_clock()
                    if left <= 0:
                        break
                    self._script_stop.wait(min(left / 1e9, END_POLL_S))
                if self._script_stop.is_set():
                    return
                done = self._script_clock()
                self._script_call(step)
                self.script_state["done"] = n
                self.log.write("script-step", n=n, due_ns=due, done_ns=done, **step.record())
        except Exception as err:  # noqa: BLE001 -- recorded; the run ends rather than going on unscripted
            self.script_state["error"] = "%s: %s" % (type(err).__name__, err)
            self.log.write("script-failed", error=self.script_state["error"])
            self._end_run()

    def _notify(self, what: str) -> None:
        if self.observer is None:
            return
        try:
            self.observer(what)
        except Exception as err:  # noqa: BLE001 -- an observer never stops the claim thread
            self.log.write("observer-failed", error=repr(err))

    def _writeback(self) -> None:
        n = self.core.n
        last = self.core.last or (None, None, None)
        self.writeback.offer({"Verdict": last[0], "Reason": last[1], "LastSeq": last[2], "Packed": n["packed"],
                              "Replied": n["replied"], "Accepted": n["accepted"], "Rejected": n["rejected"],
                              "Dropped": n["drop"], "LostOnReconnect": n["lost_on_reconnect"],
                              "IsConnected": self._state == CONNECTED, "Reconnects": n["reconnects"]})

    def _claim_main(self) -> None:
        try:
            self._loop()
            self._drain()
        except Exception as err:  # noqa: BLE001 -- recorded and reported, and the identity still closes below
            self.fatal = "%s: %s" % (type(err).__name__, err)
            self.log.write("fatal", error=self.fatal)
            print("vss_claim_bridge: fatal: %s" % self.fatal, file=sys.stderr, flush=True)
        finally:
            self._close("stop" if self.fatal is None else "fatal")
            if self.core.queued is not None:
                self.core.drop(self.core.take(), "stop")    # type: ignore[arg-type]
            self.core.log_demo_window()
            self.log.set_writer(None)
            if self.on_end is not None:
                try:
                    self.on_end()
                except Exception as err:  # noqa: BLE001 -- the hook's own problem, recorded
                    self.log.write("on-end-failed", error=repr(err))

    def _src_now(self) -> int:
        t = self.source.now_ns()
        if not _int(t):
            raise BridgeError("the source's now_ns() returned %r, not an int of ns" % (t,))
        return t

    def _loop(self) -> None:
        next_tick = time.monotonic_ns()
        while not self._stopping.is_set():
            now = time.monotonic_ns()
            due = [next_tick]
            if self._out is not None:
                due.append(self._reply_due)
            if self._state == CONNECTING:
                due.append(self._connect_due)
            if self._state == DISCONNECTED and self._out is None and self.core.queued is not None:
                due.append(self._next_connect)
            self._wait(max(0, min(due) - now) / 1e9)
            now = time.monotonic_ns()
            self._check_timeouts(now)
            if self._stopping.is_set():
                break
            if now >= next_tick:
                self._tick(now)
                next_tick += TICK_NS
                if next_tick <= now:
                    self.core.n["tick_overruns"] += 1
                    next_tick = now + TICK_NS
            self._try_send(time.monotonic_ns())
            self.log.flush()                         # the other threads' records (EventLog)

    def _drain(self) -> None:
        """At a stop: no tick and no reconnect. The queued frame is sent at once if nothing is outstanding and
        the connection is open (with the tick paused, _try_send drops it instead: 'paused'), and the outstanding
        frame, whenever it was sent, gets its reply or the reply timeout. At most two frames go through here (the
        outstanding one, then the queued one), so the drain ends within two reply timeouts (DRAIN_NS); nothing
        is sent once that bound has passed."""
        self._draining = True
        end = time.monotonic_ns() + DRAIN_NS
        while True:
            now = time.monotonic_ns()
            self._check_timeouts(now)
            if now < end:
                self._try_send(now)
            if self._out is None:
                return
            self._wait(max(0, self._reply_due - now) / 1e9)

    def _tick(self, now: int) -> None:
        if self._tick_paused.is_set():
            self.core.n["ticks_paused"] += 1            # packs nothing; _try_send, later in this pass, drops a queued frame
            return
        snap = self.held.snapshot()
        self.core.tick(snap, self._src_now(), now)

    def _wait(self, timeout: float) -> None:
        rl: List[Any] = [self._wake_r]
        wl: List[Any] = []
        if self._sock is not None and self._state == CONNECTED:
            rl.append(self._sock)
        elif self._sock is not None and self._state == CONNECTING:
            wl.append(self._sock)
        r, w, _x = select.select(rl, wl, [], timeout)
        if self._wake_r in r:
            try:
                while self._wake_r.recv(64):
                    pass
            except (BlockingIOError, InterruptedError):
                pass
        if self._sock is not None and self._state == CONNECTING and self._sock in w:
            self._connect_done(time.monotonic_ns())
        elif self._sock is not None and self._state == CONNECTED and self._sock in r:
            self._readable()

    def _check_timeouts(self, now: int) -> None:
        if self._out is not None and now >= self._reply_due:
            self.core.n["reply_timeouts"] += 1
            self.log.write("reply-timeout", seq=self._out.seq, waited_ms=(now - (self._out.sent_mono or now)) // MS)
            self._close("reply-timeout")
        if self._state == CONNECTING and now >= self._connect_due:
            self._abandon_connect(now, errno.ETIMEDOUT)

    def _try_send(self, now: int) -> None:
        if self.core.queued is not None and self._tick_paused.is_set():
            self.core.drop(self.core.take(), "paused")    # type: ignore[arg-type]  # packed before the pause (module docstring)
            return
        if self._out is not None or self.core.queued is None or self._state == CONNECTING:
            return
        for _attempt in range(2):
            if self._state == DISCONNECTED:
                if self._draining or now < self._next_connect:
                    return
                self._connect(now)
            if self._state != CONNECTED:
                return
            self.core.n["peer_checks"] += 1
            if not self._peer_closed():
                break
            self._close("peer-closed (seen before a send)")
        else:
            return
        p = self.core.take()
        assert p is not None and self._sock is not None
        try:
            sent = self._sock.send(p.frame)
        except OSError as err:
            sent = -1
            why = "send failed: %s" % (errno.errorcode.get(err.errno or 0, str(err)),)
        else:
            why = "short send of %d bytes" % sent
        p.sent_mono = now
        if sent != len(p.frame):
            self._close(why)
            self.core.lost(p, why)
            return
        self.core.n["sends"] += 1
        self._out = p
        self._reply_due = now + REPLY_TIMEOUT_NS
        self._rbuf = b""

    def _peer_closed(self) -> bool:
        """Spec 14.3 item 3: a non-blocking recv(MSG_PEEK) that returns 0 bytes, or fails, means closed."""
        assert self._sock is not None
        try:
            data = self._sock.recv(1, socket.MSG_PEEK)
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
        return data == b""

    def _connect(self, now: int) -> None:
        """A connect attempt. It takes no lock: the lock is taken when the connect completes (_connected), so
        a connect that hangs (a guest restarting, SYNs dropped) holds none; CONNECT_TIMEOUT_NS ends it."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setblocking(False)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._connect_started = now
        err = s.connect_ex(self.addr)
        if err == 0:
            self._connected(s, now)
        elif err in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EAGAIN):
            self._sock = s
            self._state = CONNECTING
            self._connect_due = now + CONNECT_TIMEOUT_NS
        else:
            s.close()
            self._connect_failed(now, err)

    def _connect_done(self, now: int) -> None:
        assert self._sock is not None
        err = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err == 0:
            s, self._sock = self._sock, None
            self._connected(s, now)
        else:
            self._abandon_connect(now, err)

    def _abandon_connect(self, now: int, err: int) -> None:
        s, self._sock = self._sock, None
        self._state = DISCONNECTED
        if s is not None:
            s.close()
        self._connect_failed(now, err)

    def _backoff(self, now: int) -> int:
        d = self.backoff.next_ns()
        self._next_connect = now + d
        return d

    def _connect_failed(self, now: int, err: int) -> None:
        self.core.n["connect_failures"] += 1
        d = self._backoff(now)
        waited = (now - self._connect_started) // MS if self._connect_started is not None else None
        self.log.write("connect-failed", error=errno.errorcode.get(err, str(err)), waited_ms=waited, backoff_ms=d // MS)

    def _connected(self, s: socket.socket, now: int) -> None:
        """The connect completed: take the scenario lock now (owner, 2026-10-01: held while connected). If someone
        else holds it, close the unused connection (nothing was sent on it) and back off like a failed connect."""
        try:
            got = self.lock.acquire()
        except BaseException:
            s.close()                                    # the lock file went away or changed mid-run: a fatal, no socket left open
            raise
        if not got:
            s.close()
            self._sock = None
            self._state = DISCONNECTED
            self.core.n["lock_busy"] += 1
            d = self._backoff(now)
            self.log.write("lock-busy", path=str(self.lock.path), backoff_ms=d // MS,
                           note="the connection was closed unused: nothing is sent without the lock")
            return
        self._sock = s
        self._state = CONNECTED
        self._rbuf = b""
        n = self.core.n
        n["connects"] += 1
        if n["connects"] > 1:
            n["reconnects"] += 1
        self.backoff.reset()
        self.log.write("connect", lock=self.lock.held, connects=n["connects"], **self.run_items())
        self._notify("connected")
        self._writeback()

    def _close(self, why: str) -> None:
        was = self._state
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._state = DISCONNECTED
        out, self._out = self._out, None
        self._rbuf = b""
        self.lock.release()
        if out is not None:
            self.core.lost(out, why)
        if was == CONNECTED:
            self.log.write("closed", why=why, outstanding=out.seq if out is not None else None)
            self._notify("closed")
            self._writeback()

    def _readable(self) -> None:
        assert self._sock is not None
        try:
            data = self._sock.recv(vf.FRAME_TOTAL_BYTES - len(self._rbuf))
        except (BlockingIOError, InterruptedError):
            return
        except OSError as err:
            self._close("recv failed: %s" % (errno.errorcode.get(err.errno or 0, str(err)),))
            return
        if not data:
            self._close("peer closed")
            return
        if self._out is None:
            self.core.n["stray_bytes"] += len(data)
            self.log.write("stray-bytes", n=len(data))
            self._close("stray bytes with nothing outstanding")
            return
        self._rbuf += data
        if len(self._rbuf) < vf.FRAME_TOTAL_BYTES:
            return
        p, self._out = self._out, None
        data, self._rbuf = self._rbuf, b""
        ok, rec = self.core.reply(p, data)
        if ok:
            self.replies.write("reply", **rec)
            self._writeback()
        else:
            self._close("invalid reply")


# --- the command line ------------------------------------------------------------------------------

RUNS = Path(os.environ.get("SDV_RUNS", "~/sdv-runs")).expanduser()
RECORDINGS = Path("~/sdv-recordings").expanduser()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def out_dir(name: Optional[str], out: Optional[str]) -> Path:
    """The run directory: --out, or <SDV_RUNS>/<date>-<name>; never inside the repo or under ~/sdv-recordings."""
    d = Path(out).expanduser() if out else RUNS / ("%s-%s" % (datetime.datetime.now().strftime("%Y%m%d"), name or "bridge"))
    for root, what in ((REPO, "the repo"), (RECORDINGS, "~/sdv-recordings")):
        if _inside(d, root):
            raise BridgeError("refused: the run directory %s is inside %s" % (d, what))
    if d.exists() and any(d.iterdir()):
        raise BridgeError("refused: %s exists and is not empty: pick another --name" % d)
    return d


def load_script_file(path: Optional[str]) -> Optional[Tuple[ScriptStep, ...]]:
    """--script FILE, parsed whole (parse_script); None without one. A file that cannot be read or is not JSON is a
    BridgeError, as a malformed script is."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as err:
        raise BridgeError("refused to start: the script %s cannot be read: %s" % (path, err)) from err
    return parse_script(doc)


class Ending:
    """How main() waits for a run's end: --seconds, SIGTERM or SIGINT (with or without --seconds; docker stop sends
    SIGTERM), a script's end step, or the claim thread's end (done, which on_end sets, for either; a fatal included).
    Each ends the run the same way: the stop, its drain, the summary and the exit code. A handler sets a plain attribute and nothing else: an
    Event.set() inside a handler can deadlock against the main thread's own wait on that Event (the handler runs on
    the waiting thread, and both take the Event's lock), so the wait polls the attribute every END_POLL_S. Python
    runs handlers on the main thread only, so a main() called on another thread installs none."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.signalled: Optional[int] = None
        self._restore: List[Tuple[int, Any]] = []

    def install(self) -> None:
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                self._restore.append((sig, signal.signal(sig, self._on_signal)))

    def _on_signal(self, signum: int, _frame: Any) -> None:
        self.signalled = signum

    def restore(self) -> None:
        for sig, old in self._restore:
            signal.signal(sig, old)
        self._restore = []

    def wait(self, seconds: Optional[float]) -> None:
        end = None if seconds is None else time.monotonic() + seconds
        try:
            while self.signalled is None:
                left = END_POLL_S if end is None else min(END_POLL_S, end - time.monotonic())
                if left <= 0 or self.done.wait(left):
                    return
        except KeyboardInterrupt:      # defensive: with the handlers installed, SIGINT never raises one here
            self.signalled = signal.SIGINT

    def log_to(self, log: EventLog) -> None:
        if self.signalled is not None:
            log.write("signal", signal=signal.Signals(self.signalled).name, note="the run ends as at --seconds: drain, summary")


def main(argv: Optional[Sequence[str]] = None, source: Any = None,
         writeback_sink: Optional[Callable[[Dict[str, Any]], None]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the bridge against a source supplied in-process")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--header", help="a run header (JSON): its bridge items configure the bridge; the item flags are then refused")
    r.add_argument("--mode", choices=MODES)
    r.add_argument("--profile", type=int)
    r.add_argument("--profile-source", choices=PROFILE_SOURCES)
    r.add_argument("--vehicle")
    r.add_argument("--wheelbase-mm", type=int)
    r.add_argument("--demo-odd", metavar="START_S,DURATION_S")
    r.add_argument("--seconds", type=float, default=None, help="run this long (SIGTERM or SIGINT ends it earlier; default: until one)")
    r.add_argument("--script", default=None, help="a script of control calls (JSON; module docstring, SCRIPT)")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--name")
    g.add_argument("--out")
    r.add_argument("--lock", default=None, help="the scenario lock (default: SDV_SCENARIO_LOCK or %s; with "
                   "SDV_SCENARIO_LOCK_MUST_EXIST=1 no other path is taken)" % DEFAULT_LOCK)
    r.add_argument("--gen", default=None, help="the generated contract's directory (default: SDV_GEN or sdv-out/gen)")
    a = ap.parse_args(argv)
    items = (a.mode, a.profile, a.profile_source, a.vehicle, a.wheelbase_mm, a.demo_odd)
    ending = Ending()
    try:
        script = load_script_file(a.script)
        if a.header:
            if any(x is not None for x in items):
                raise BridgeError("--header gives the run items: --mode, --profile, --profile-source, --vehicle, --wheelbase-mm "
                                  "and --demo-odd are refused with it")
            with open(a.header, encoding="utf-8") as f:
                cfg = Config.from_header(json.load(f), a.host, a.port, lock_path=a.lock)
        else:
            if any(x is None for x in items[:5]):
                raise BridgeError("without --header, give --mode, --profile, --profile-source, --vehicle and --wheelbase-mm")
            demo = None
            if a.demo_odd:
                start, dur = (float(x) for x in a.demo_odd.split(","))
                demo = {"profile_id": [int(r["id"]) for r in vf.load_contract(a.gen).PROFILES if "run_window_max_ms" in r][0],
                        "start_s": start, "duration_s": dur}
            cfg = Config(host=a.host, port=a.port, mode=a.mode, profile_id=a.profile, profile_source=a.profile_source,
                         source_vehicle={"name": a.vehicle, "wheelbase_mm": a.wheelbase_mm}, demo_odd_window=demo, lock_path=a.lock)
        if source is None:
            print("vss_claim_bridge: no source for mode %r: this command line runs the core against a source supplied in-process "
                  "(main(argv, source=...)); from a shell use bridge_sources.py run, which takes the same flags and opens the "
                  "broker, can or replay source" % cfg.mode, file=sys.stderr)
            return 2
        run_dir = out_dir(a.name, a.out)
        bridge = Bridge(cfg, source, gen_dir=a.gen, writeback_sink=writeback_sink, run_dir=run_dir, on_end=ending.done.set,
                        script=script)
    except (BridgeError, vf.ContractError, OSError, ValueError) as err:
        print("vss_claim_bridge: %s" % err, file=sys.stderr)
        return 2
    ending.install()
    try:
        try:
            bridge.start()
        except BridgeError as err:
            bridge.log.close()
            bridge.replies.close()
            print("vss_claim_bridge: %s" % err, file=sys.stderr)
            return 2
        try:
            ending.wait(a.seconds)
            ending.log_to(bridge.log)
        finally:
            s = bridge.stop()
    finally:
        ending.restore()
    print(json.dumps({"run_dir": str(run_dir), "identity": s["identity"], "ticks_identity": s["ticks_identity"],
                      "by_reason": s["by_reason"], "fatal": s["fatal"]}, sort_keys=True))
    ok = s["fatal"] is None and s["identity"]["holds"] and s["ticks_identity"]["holds"] and s["seq_partition"]["holds"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
