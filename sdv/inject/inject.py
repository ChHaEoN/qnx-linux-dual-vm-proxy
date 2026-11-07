#!/usr/bin/env python3
"""inject.py -- the injected recordings of Phase 2 step 3 and their events file (sdv/inject; Phase 2 WP9).

The kind 4 wire specification (the project's local design notes, sections 6,
14.2 and 14.5; not in this tree) asks Phase 2 step 3 for a recording whose frames carry reasons 23-27, and for
the provider stopping (22). sigsim cannot make them: its clamp and envelope refuse a speed, an acceleration or a
steering angle beyond the profile's limits and a gear against the direction of travel, and its yaw rate is computed
from v and delta, so it never zeroes it in a turn. So this tool rewrites the candump frames of an existing sigsim
recording (or a CARLA one: A CARLA SOURCE), inside slice.dbc's ranges, into a NEW recording directory, and writes
beside it the events file Phase 2 WP10 runs against.

    inject.py rewrite --from DIR --name NAME [--root DIR | --out DIR] [--dbc FILE] [--gen DIR]
    inject.py check DIR [--dbc FILE] [--gen DIR]

Run it with the sim venv's Python (cantools and python-can, sdv/sim/requirements.lock), from the repo root.
`rewrite` reads the source recording (never writes it: every file it reads is hashed before and after, and a
change refuses), computes the whole new recording in memory, checks it, and only then creates <root>/<NAME>
(refusing one that exists: an existing recording is never touched) and writes into it, in this order: the log
(under the source's own name, sigsim.log or carla.log), its .sha256, events.json, summary.json,
manifest-line.json. Anything that fails after the directory was created removes what was written and the
directory. `check` re-reads a recording made here and checks it again, the same way, with nothing reused from the
rewrite, against the current contract and DBC (the events file's contract digest and sha256 and its DBC's sha256
must be theirs); it exits 1 on any failure, and says on stderr when the source recording is gone, so its diff
against the source was skipped.

THE EVENTS (in time order; each a rewrite of one slot's signal in every frame of its message inside the event's
injected span, everything else in those frames unchanged)
  speed  23  the speed slot (LongVel) at INJECT_FACTOR x the profile's v_max, with the frames' sign of travel
  accel  24  the acceleration slot (LongAccel) at INJECT_FACTOR x a_max, along the direction of travel, so the
             hard-brake app's deceleration (-a_x sign(v)) only falls: its predicted switches stay the source's
  steer  25  the steering slot (SteerAngleRow1) at INJECT_FACTOR x delta_max
  yaw    26  the yaw-rate slot (YawRate) zeroed, where rule 26 must fire: every frame of the window is one sigsim's
             counter counts (summary.json verify.judge.rule26_above_tol: inside rule 26's speed window, under the
             a_y bound, psi_dot_kin above tol), and its psi_dot_kin is above tol by more than the yaw margin
             (DESIGN VALUES). The predicate is checked against that counter on the whole decoded source, and the
             rewrite refuses when they disagree
  gear   27  the gear slot (CurrentGear) at the reverse gear the trip itself engages (summary.json trip.gear_changes),
             where every frame's speed is above the profile's v_tol forward by more than the gear margin
  Then 22, in each of the two runs below: no rewrite, the held values ageing past AGE_MAX once nothing more arrives.
  Every limit is the generated profile table's (the profile the source's manifest line names), and the periods, the
  pipeline allowance A, AGE_MAX and the two margins are the contract's: no generated value is written in this file as
  a literal. The tick is not generated: it is the bridge's own design value (vss_claim_bridge.TICK_NS, specification
  15's bridge sampling rate), imported from the bridge and never repeated here. How far beyond its limit a 23-25
  value goes (INJECT_FACTOR) is not generated either; it is one of this tool's own design values, which DESIGN
  VALUES lists apart from the generated ones.

THE RUNS. The events file names two runs of the recording. Each is the five events above plus a pair of 22 windows
from its reference R: a bounded first window [R, R + FIRST_22_NS) that must hold the first 22, and the open-ended
rest [R + FIRST_22_NS, OPEN_END_NS).
  stop    (windows "stop", "stop-held") R is the stop: an offset after every event's window and after the hard-brake
          app's expected windows (sdv/stack/replaycheck.expected_windows), with the run's run_through_ns at or before
          the file's last frame. It is realised per mode as data for WP10: broker, stop the can-provider; can, stop
          the player; replay, pause the intake (Bridge.pause_intake); none of them undone. A run whose stop is not
          realised gets its first 22 only after the file's end, so its first window holds no 22 and its set lacks
          (stop, 22): the stop's realisation is checked, not assumed.
  to_end  (windows "end", "end-held") R is the file's last frame and nothing is stopped: the file's end is the
          provider stopping. A run that only plays the file (23-27) is this one, and is never taken for the stop test.
  Each run states run_through_ns, R + FIRST_22_NS + EVENT_SPAN_NS: the offset it must keep ticking through, so its
  open-ended window holds at least MIN_EVENT_TICKS ticks (a run cut earlier lacks that pair).
  Neither run can be played through the stack as WP8 left it (sdv/stack/stack.py): it plays the whole file with the
  player, stops the bridge at the player's end, and has no way to stop the player or the can-provider mid-file. So
  WP10's harness (sdv/stack/step3.py) keeps the bridge ticking through each run's run_through_ns, past the player's
  end, and makes the stop at its offset by the mode's realisation (replay's is the bridge's own Bridge.pause_intake).
  Played through stack.py's own replay, each run lacks its 22 pairs: a loud failure of the set comparison, never a
  silent pass.

PLACEMENT. Each event has an injected span of EVENT_SPAN_NS (whole ticks: MIN_EVENT_TICKS ticks plus the generated
pipeline allowance A, rounded up), starting on the tick grid, and a window: the span widened by A on both sides
(t0_ns, t1_ns, half open). A tick of a live mode (can, broker) whose value arrived up to A late still finds at
least MIN_EVENT_TICKS ticks inside the span, and a reject it sees late still falls inside the window. The events
are placed in the order above, each at the earliest grid instant whose whole window satisfies its condition and
starts at least SEPARATION_NS after the previous window ends (the first: SEPARATION_NS after the file's first frame),
so no frame carries two faults (the first failure wins, rules.py) and honest ACCEPTs bracket every event. The stop
comes SEPARATION_NS after the last window and the app's windows, on the grid.

THE EXPECTED REASONS are computed, never assumed: in each run the rewritten frames go offline through the replay-mode
bridge (bridge_sources.ReplaySource on a fake clock, its Intake, HeldValues and ClaimCore.tick -- the bridge's own
packing, on the tick grid exactly as a real replay schedules it, the stop run's intake pause included) and every
packed frame is judged with rules.judge_frame (rules.reply). An event's reason is the one reason of the ticks inside
its injected span; a 22 window's, the one reason of the rejects inside it. The rewrite refuses unless, in each run:
every tick of each injected span was rejected with the intended reason, at least MIN_EVENT_TICKS of them; every other
tick before R was ACCEPTed; from R on, ticks are ACCEPT until the first 22 and 22 after it; the first 22 comes at most
AGE_MAX plus one tick after R (specification 14.1, P9) with an age above AGE_MAX and at most AGE_MAX plus one tick;
each 22 window holds at least MIN_EVENT_TICKS rejects; the replay ticked through run_through_ns; and the
event-to-reason set (reasonsets.reason_set on the run's windows shifted by the run's anchor) is exactly the run's.
The five events must judge identically in both runs.

THE EVENTS FILE (events.json, format 2, beside the recording): the recording's sha256, the source's identity, this
tool's sha256, the contract's digest and sha256, the DBC's sha256, the design values below; `events`, the five
injected events, each with its name, reason (computed), intended reason, window (t0_ns, t1_ns: ns from the
recording's first frame, half open; reasonsets.shift_windows puts them on a run's src_now_ns clock), injected span,
rewrite (slot, VSS path, message, signal, the value as the DBC carries it, the limit it is beyond or the condition
and margin it holds by, the frames rewritten) and the offline replay's ticks; and `runs`, per run its reference, its
stop (or null), the per-mode realisation, run_through_ns, its two 22 windows and its offline replay's check.
run_events(doc, run) gives a run's whole window list in time order (the five events, then its two 22 windows).

THE NEW RECORDING is the stack's kind of recording directory (sdv/stack/stack.py reads a sigsim one like any other):
the log under the source's own name (the source's lines, verbatim except the rewritten ones, which keep the source's
line form and channel), its .sha256, summary.json and the manifest line, written last. summary.json's trip is the
source's cut to the fields that still describe the file, since the rewrite moves no frame (TRIP_KEPT: segments,
message counts, periods, duration, seed, the source's params, profile and wheelbase, and a CARLA trip's rtf,
timestamps and gaps -- the gaps are where the log's schedule had no frame, which the rewrite leaves where they were,
and a replay's 22s are read against the gaps and the rtf together, manifest-classes.md section 4); the fields that
describe the drive's values (ranges, gear changes, clamps, violations and the like) or a CARLA take and its encoding
are dropped and named in rewrite.trip_fields_dropped, beside the rewrite's provenance. The manifest line is the
source's with its own name, path and sha256, and three source.params entries naming the rewrite (REWRITE_PARAMS:
rewrite_of, the source's name; rewrite_of_sha256, the source log's sha256; rewrite_events_sha256, events.json's
sha256), which must keep source.params within the scenario entry's eight short values, each an integer or a string
(manifest-classes.md sections 4 and 9): a source whose params would break them, or already carry one of the three, is
refused before anything is written. A path under ~/sdv-recordings keeps that ~ form in the line, as sigsim's do. The
line's recording.path, the source's and the new one's, is a scenario entry path (SCENARIO_PATH: from ~ or /, no ..
segment); a destination whose path would not be one is refused before it is created.

A CARLA SOURCE (Phase 7 WP3a). A CARLA recording (Phase 7 WP1's sdv/carla/encode.py, source.generator carla) is read
and rewritten as a sigsim one is, by every rule above unchanged; only its log's name, its rtf and its steps.jsonl
differ. A recording's log is the basename of its manifest line's recording.path, which must be its generator's
(LOG_NAMES: sigsim.log for sigsim, carla.log for carla), with <log>.sha256 beside it, whose name, where it gives one,
is the log's; another name or another generator is refused, and the new recording keeps the source's log name. A
carla source carries source.rtf and a sigsim source none ({min, mean, max}, each a number above 0, min <= mean <=
max: manifest-classes.md section 4), and summary.json's trip rtf, where the trip has one, is the line's. The rtf is
copied unchanged into the new line, since the rewrite moves no frame, and recorded in events.json's rewritten_from
(a carla source's only, so a sigsim rewrite's bytes do not change); `check` holds the new line's rtf to that record
always, and to the source's when the source is there: the run launcher copies it into every run header's source_rtf
(manifest-classes.md section 4, C12a), so a changed one would mislabel every run. A CARLA line's five params and the
rewrite's three make the scenario entry's eight. steps.jsonl, the take's steps beside a CARLA log, is not copied: the
rewritten log cannot be made again from it, and summary.json says so (rewrite.not_copied). The judge is the generated
table's compiled profiles, as for sigsim, so a CARLA recording under profile 3 is rewritten once the generation
compiles that profile.

DESIGN VALUES. The quantities the events are built from are of five kinds, kept apart here.
  Generated, read at run time from the contract (sdv-out/gen), never written in this file: the profile's limits
    (v_max, a_max, delta_max), its rule-26 tol, window and a_y bound, v_tol, L, the DBC's periods, the pipeline
    allowance A, AGE_MAX, QUANT_BOUND and DBC_HALF_LSB. The DBC's signal ranges are read from the DBC itself.
  The bridge's own design value, imported from the bridge and never repeated here: the tick
    (vss_claim_bridge.TICK_NS, from TICK_HZ, specification 15's bridge sampling rate). It is not generated.
  This tool's own, written here as literals: chosen, not derived from the contract or the bridge, and recorded with
    their reasons as Phase 2 design decisions s-v and rows of specification 15 (the project's local design notes):
    MIN_EVENT_TICKS = 2: the wire specification's sampling bullet (14.2): only the latest value at each tick is
      judged, so an event shorter than two ticks may be judged once or never. The specification's rule, not a
      generated value.
    INJECT_FACTOR = 1.25: a free choice: an injected 23-25 value a quarter beyond its limit, far from the edge (the
      edges are the monitor's own tests, C9). Every value written is checked against its signal's range in the
      DBC, and refused outside it; the offline replay confirms each reject after the DBC's quantisation.
    SEPARATION_NS = 1 s: a free choice: honest frames between two windows, ten ticks of today's tick but not
      computed from it. It equals the guest's one-second log-summary interval (specification 12 and 15), so one
      bucket never holds two events; that interval is a specification value, which the contract does not
      generate.
    OPEN_END_NS = 2^63 - 1 ns: an open-ended window's end, "to the end of the run"; a sentinel, not a duration.
  Forms, this tool's choice, whose every input is a generated value, the bridge's tick or MIN_EVENT_TICKS:
    EVENT_SPAN_NS = ceil((MIN_EVENT_TICKS ticks + A) / tick) ticks; a window is the span widened by A on both sides.
    FIRST_22_NS = AGE_MAX + one tick + A: P9's bound (22 within AGE_MAX plus one tick of the stop) plus the pipeline
      allowance for a live mode's late delivery or late stop. Offline, P9's own bound is held (THE EXPECTED REASONS).
    run_through_ns = R + FIRST_22_NS + EVENT_SPAN_NS: the open-ended window gets an event's span of its own.
    The yaw margin = the generated QUANT_BOUND of the profile (slice.dbc's quantisation bound of psi_dot_kin): a
      zeroed yaw is still detected if v and delta were each off by their half LSB. The gear margin = the generated
      DBC_HALF_LSB of v: the speed is above v_tol by more than its own quantisation. 23-25 have no generated margin:
      they sit beyond their limits by INJECT_FACTOR's free quarter instead.
  Fixed elsewhere, and no design value of this tool: the svc port in the offline bridge's configuration (SVC_PORT,
    specification 13; offline nothing is opened), source.params' limits and the name pattern (PARAMS_MAX and
    NAME_PATTERN: manifest-classes.md section 4; PARAM_LEN_MAX: the maxLength of its section 9 schema), source.rtf's
    form (RTF_KEYS, the same section), a scenario entry's path (SCENARIO_PATH and DOTDOT_SEGMENT: the section 9
    schema's path), the file names the stack reads and the CARLA encoder writes (LOG_NAMES), and the fake clock's start
    (CLOCK0_NS, any value: the replay is relative to its own anchor).
  22 is realised in the injected recording itself, not in a recording of its own: the stop needs honest frames before
    it and the five events' windows apart from it, which this file has after its last event; the to_end run of the
    same file is the run that only plays it.

DOES NOT DEMONSTRATE: any timing; what a live mode samples (can and broker sample at their own instants: the windows'
allowance A is the pipeline allowance of the specification, not a measured delay, and WP10 compares sets, not frames);
that the guest judges as the Python reference does (that is the monitor's own tests and WP10's run); anything about
a vehicle (the values are injected, not driven); that a rewritten recording is replayed by a live stack.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _d in (REPO / "sdv" / "frame", REPO / "sdv" / "bridge"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import bridge_sources as bs  # noqa: E402
import reasonsets as rs  # noqa: E402
import rules  # noqa: E402
import vss_claim_bridge as vb  # noqa: E402
import vssframe as vf  # noqa: E402

TOOL = Path(__file__).resolve()
STACK_DIR = REPO / "sdv" / "stack"
RECORDINGS = Path("~/sdv-recordings")
LOG_NAME = "sigsim.log"                      # a sigsim recording's log: the file name the stack reads in a recording directory
CARLA_LOG_NAME = "carla.log"                 # a CARLA recording's log (sdv/carla/encode.py)
# A recording's log by its source.generator: its line's recording.path's basename (module docstring, A CARLA SOURCE).
LOG_NAMES = {"sigsim": LOG_NAME, "carla": CARLA_LOG_NAME}
STEPS_NAME = "steps.jsonl"                   # the take's steps beside a CARLA log: never copied (A CARLA SOURCE)
MANIFEST_NAME = "manifest-line.json"
SUMMARY_NAME = "summary.json"
EVENTS_NAME = "events.json"
EVENTS_FORMAT = 2
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")      # a manifest-line name (manifest-classes.md section 4)
PARAMS_MAX = 8                               # source.params: at most eight values (manifest-classes.md section 4)
PARAM_LEN_MAX = 64                           # each a short string or an integer (manifest-classes.md section 9 schema)
REWRITE_PARAMS = ("rewrite_of", "rewrite_of_sha256", "rewrite_events_sha256")    # the source.params a rewrite adds
RTF_KEYS = ("min", "mean", "max")            # source.rtf, a carla source's only (manifest-classes.md section 4)
SCENARIO_PATH = re.compile(r"(~|/)[A-Za-z0-9._/-]{1,255}")       # a scenario entry's path (manifest-classes.md section 9 schema)
DOTDOT_SEGMENT = re.compile(r"(^|/)[.][.](/|$)")                 # ... which holds no .. segment (the same schema)
MS = 1_000_000
US = 1000
# summary.json trip fields that still describe a rewritten file (module docstring, THE NEW RECORDING); the stack reads
# segments, seed, params and messages (sdv/stack/stack.py recording_summary, check_summary_counts). rtf, timestamps and
# gaps are a CARLA trip's (the RTF it was made at, the log's time base, the steps where its schedule had no frame: the
# frames' times, which the rewrite does not move); a sigsim trip has none of them.
TRIP_KEPT = ("segments", "messages", "periods_ms", "duration_ms", "seed", "params", "profile_id", "wheelbase_mm", "rtf",
             "timestamps", "gaps")
TRIP_NEEDED = ("segments", "messages", "seed")

# Design values (module docstring, DESIGN VALUES).
MIN_EVENT_TICKS = 2
INJECT_FACTOR = 1.25
SEPARATION_NS = 1_000_000_000
OPEN_END_NS = (1 << 63) - 1

TICK_NS = vb.TICK_NS
SVC_PORT = 7160                              # the svc port the claims would go to (specification 13); offline, nothing is opened
CLOCK0_NS = 10**12                           # the offline replay's fake monotonic clock at the bridge's start (any value)

SLOT_V, SLOT_AX, SLOT_DELTA, SLOT_YAW, SLOT_GEAR = range(vf.N_SLOTS)

REALISATION_22 = {
    "broker": {"action": "stop the can-provider", "note": "the databroker keeps the last values; their datapoint timestamps age"},
    "can": {"action": "stop the player", "note": "the last frames' receive times age"},
    "replay": {"action": "pause the intake", "call": "Bridge.pause_intake",
               "note": "the stream is drained, nothing more is held; any call after the grid's delivery at the offset minus one tick "
                       "and before its delivery at the offset (wall clock: anchor_ns + offset - tick/2, between two deliveries) "
                       "holds the same frames as the offline replay"},
}
REALISATION_END = {
    "broker": {"action": "none: the player plays the file to its end",
               "note": "the can-provider stays up and receives nothing more; the databroker's last values age"},
    "can": {"action": "none: the player plays the file to its end", "note": "the last frames' receive times age"},
    "replay": {"action": "none: the stream ends with the file", "note": "ReplaySource logs replay-ended; the held values age"},
}
RUNS = ("stop", "to_end")
RUN_WINDOWS = {"stop": ("stop", "stop-held"), "to_end": ("end", "end-held")}


class InjectError(RuntimeError):
    """A refusal: nothing is written (or what was written is removed)."""


@dataclass(frozen=True)
class Kind:
    event: str
    reason: int                 # the reason intended; the events file's reason is computed (module docstring)
    slot: Optional[int]
    limit: Optional[str]        # the profile field the injected value goes beyond


SLOT_EVENTS = (
    Kind("speed", rules.RSN_VSS_SPEED, SLOT_V, "v_max"),
    Kind("accel", rules.RSN_VSS_ACCEL, SLOT_AX, "a_max"),
    Kind("steer", rules.RSN_VSS_STEER, SLOT_DELTA, "delta_max"),
    Kind("yaw", rules.RSN_VSS_YAW, SLOT_YAW, None),
    Kind("gear", rules.RSN_VSS_GEAR, SLOT_GEAR, None),
)
STALE_REASON = rules.RSN_VSS_STALE


def event_span_ns(contract: Any) -> int:
    """MIN_EVENT_TICKS ticks plus the pipeline allowance A, rounded up to whole ticks (module docstring, PLACEMENT)."""
    need = MIN_EVENT_TICKS * TICK_NS + int(contract.PIPELINE_ALLOWANCE_MS) * MS
    return -(-need // TICK_NS) * TICK_NS


def allowance_ns(contract: Any) -> int:
    return int(contract.PIPELINE_ALLOWANCE_MS) * MS


def first22_ns(contract: Any) -> int:
    """FIRST_22_NS: AGE_MAX plus one tick (P9) plus A (module docstring, DESIGN VALUES)."""
    return int(contract.AGE_MAX_MS) * MS + TICK_NS + allowance_ns(contract)


def run_through_ns(ref_ns: int, contract: Any) -> int:
    return ref_ns + first22_ns(contract) + event_span_ns(contract)


def margins(contract: Any, profile_id: int) -> Dict[int, Dict[str, Any]]:
    """The yaw and gear placements' margins (module docstring, DESIGN VALUES): generated values, by slot."""
    return {SLOT_YAW: {"over": "tol26", "by": "QUANT_BOUND[%d]" % profile_id, "value": float(contract.QUANT_BOUND[profile_id])},
            SLOT_GEAR: {"over": "v_tol", "by": "DBC_HALF_LSB['v']", "value": float(contract.DBC_HALF_LSB["v"])}}


def grid_ceil(t_ns: int) -> int:
    return -(-t_ns // TICK_NS) * TICK_NS


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def run_events(doc: Dict[str, Any], run: str) -> List[Dict[str, Any]]:
    """A run's whole window list, in time order: the five injected events, then the run's two 22 windows."""
    return list(doc["events"]) + list(doc["runs"][run]["events"])


# --- the candump lines ------------------------------------------------------------------------------------

_LINE = re.compile(r"^\((\d+)\.(\d{6})\) (\S+) ([0-9A-F]{3})#((?:[0-9A-F]{2}){0,8})$")


@dataclass
class Line:
    text: str                   # the line as read, without its newline
    t_us: int
    channel: str
    can_id: int
    data: bytes


def format_line(t_us: int, channel: str, can_id: int, data: bytes) -> str:
    """sigsim's candump -l line form (sigsim.candump_line), without the newline."""
    return "(%010d.%06d) %s %03X#%s" % (t_us // 1_000_000, t_us % 1_000_000, channel, can_id, bytes(data).hex().upper())


def parse_lines(text: str, where: str) -> List[Line]:
    """Every line of a sigsim log, each in sigsim's own form (so a rewritten line keeps it): refused otherwise."""
    out: List[Line] = []
    if not text.endswith("\n"):
        raise InjectError("%s does not end with a newline" % where)
    for n, s in enumerate(text[:-1].split("\n"), 1):
        m = _LINE.match(s)
        if m is None:
            raise InjectError("%s:%d is not a line of sigsim's candump form: %r" % (where, n, s[:80]))
        t_us = int(m.group(1)) * 1_000_000 + int(m.group(2))
        ln = Line(s, t_us, m.group(3), int(m.group(4), 16), bytes.fromhex(m.group(5)))
        if format_line(ln.t_us, ln.channel, ln.can_id, ln.data) != s:
            raise InjectError("%s:%d does not round-trip through sigsim's line form: %r" % (where, n, s[:80]))
        if out and t_us < out[-1].t_us:
            raise InjectError("%s:%d: the timestamp goes back" % (where, n))
        out.append(ln)
    if not out:
        raise InjectError("%s holds no frame" % where)
    return out


def frames_of(lines: Sequence[Line]) -> List[Tuple[int, int, bytes]]:
    """(t_us, CAN id, data): what bridge_sources.read_candump gives for the same text."""
    return [(ln.t_us, ln.can_id, ln.data) for ln in lines]


def last_offset_ns(lines: Sequence[Line]) -> int:
    """The file's last frame, in ns from its first."""
    return (lines[-1].t_us - lines[0].t_us) * US


# --- the source recording ---------------------------------------------------------------------------------

@dataclass
class Source:
    dir: Path
    line: Dict[str, Any]
    summary: Dict[str, Any]
    log_text: str
    hashes: Dict[str, str]      # every file read, by name: checked again before anything is written
    log_name: str               # the log's file name (log_name_of): sigsim.log or carla.log


def is_scenario_path(path: Any) -> bool:
    """A scenario entry's path (manifest-classes.md section 9's schema): ~ or /, then 1 to 255 characters of
    [A-Za-z0-9._/-], with no .. segment."""
    return isinstance(path, str) and SCENARIO_PATH.fullmatch(path) is not None and DOTDOT_SEGMENT.search(path) is None


def log_name_of(line: Dict[str, Any]) -> str:
    """A recording's log: the basename of its manifest line's recording.path, which must be a scenario entry path
    (is_scenario_path) and end in its generator's name (LOG_NAMES); any other path or name, or a generator this tool
    does not read, is refused (module docstring, A CARLA SOURCE)."""
    rec, source = line.get("recording"), line.get("source")
    path = rec.get("path") if isinstance(rec, dict) else None
    gen = source.get("generator") if isinstance(source, dict) else None
    if not isinstance(gen, str) or gen not in LOG_NAMES:
        raise InjectError("the source's generator is %r: this tool reads %s recordings only" % (gen, " and ".join(sorted(LOG_NAMES))))
    if not isinstance(path, str) or not path:
        raise InjectError("the manifest line names no recording.path")
    if not is_scenario_path(path):
        raise InjectError("the recording.path %r is not a scenario entry path (manifest-classes.md section 9)" % path)
    name = PurePosixPath(path).name
    if name != LOG_NAMES[gen]:
        raise InjectError("the recording's log is %r: a %s recording's log is %s, and no other name is read" % (name, gen, LOG_NAMES[gen]))
    return name


def _positive(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def rtf_problems(source: Dict[str, Any]) -> List[str]:
    """source.rtf as the scenario entry has it (manifest-classes.md section 4, and its loader's check): required
    exactly for a carla source; exactly min, mean and max, each a number above 0, with min <= mean <= max."""
    gen = source.get("generator")
    if gen != "carla":
        return ["a %s source carries an rtf: only a carla recording has one" % gen] if "rtf" in source else []
    if "rtf" not in source:
        return ["a carla source has no rtf (manifest-classes.md section 4)"]
    rtf = source["rtf"]
    if not isinstance(rtf, dict) or set(rtf) != set(RTF_KEYS):
        return ["the rtf %r is not {min, mean, max}" % (rtf,)]
    bad = [k for k in RTF_KEYS if not _positive(rtf[k])]
    if bad:
        return ["the rtf has a value that is not a number above 0: %s" % bad]
    if not rtf["min"] <= rtf["mean"] <= rtf["max"]:
        return ["the rtf %r does not hold min <= mean <= max" % (rtf,)]
    return []


def params_problems(params: Any) -> List[str]:
    """A source's params against the scenario entry's limits once the rewrite's three (REWRITE_PARAMS) are added: at
    most PARAMS_MAX values, each an integer or a string, a string at most PARAM_LEN_MAX characters (manifest-classes.md
    sections 4 and 9; the schema bounds no integer, and neither does this), and none of the three already there (a
    rewrite of a rewrite: manifest_line keeps the same check as the write-time guard). A bool is no integer here:
    JSON's true is not a number. read_source refuses params that are not an object first; the guard below is for a
    direct caller."""
    if not isinstance(params, dict):
        return ["source.params is not an object: %r" % (params,)]
    problems = []
    if len(params) + len(REWRITE_PARAMS) > PARAMS_MAX:
        problems.append("source.params would carry %d values with the rewrite's %d, more than the scenario entry's %d"
                        % (len(params) + len(REWRITE_PARAMS), len(REWRITE_PARAMS), PARAMS_MAX))
    too_long = sorted(k for k, v in params.items() if isinstance(v, str) and len(v) > PARAM_LEN_MAX)
    if too_long:
        problems.append("source.params %s longer than %d characters" % (too_long, PARAM_LEN_MAX))
    wrong = sorted(k for k, v in params.items() if isinstance(v, bool) or not isinstance(v, (int, str)))
    if wrong:
        problems.append("source.params %s are not integers or strings" % wrong)
    clash = sorted(set(REWRITE_PARAMS) & set(params))
    if clash:
        problems.append("source.params already carry %s: a rewrite of a rewrite is not supported" % clash)
    return problems


def read_source(src_dir: Path) -> Source:
    """The source recording, checked as the stack checks one (sdv/stack/stack.py recording_identity, recording_seed,
    recording_summary): its log (log_name_of: sigsim.log or carla.log) hashes to its manifest line's sha256 and to
    <log>.sha256's, which names no file but the log (a bare hash is read as the stack reads it); summary.json names the
    line's recording and seed; a carla source carries its rtf, a sigsim one none (rtf_problems), and summary.json's
    trip rtf, where the trip has one, is the line's. source.params that is not an object is refused before the seed is
    read in it. Read only."""
    src_dir = Path(src_dir)
    raw: Dict[str, bytes] = {}

    def read(n: str) -> bytes:
        try:
            raw[n] = (src_dir / n).read_bytes()
        except OSError as err:
            raise InjectError("the source recording %s has no readable %s: %s" % (src_dir, n, err)) from err
        return raw[n]

    line = json.loads(read(MANIFEST_NAME).decode("ascii"))
    if not isinstance(line, dict):
        raise InjectError("the source recording %s: its manifest line is not an object" % src_dir)
    log = log_name_of(line)
    if not isinstance(line["source"].get("params"), dict):
        raise InjectError("the source recording %s: its manifest line's source.params is not an object" % src_dir)
    for n in (log, log + ".sha256", SUMMARY_NAME):
        read(n)
    summary = json.loads(raw[SUMMARY_NAME].decode("utf-8"))
    if not isinstance(summary, dict):
        raise InjectError("the source recording %s: its summary.json is not an object" % src_dir)
    sha = sha256_bytes(raw[log])
    listed = raw[log + ".sha256"].decode("ascii").split()
    problems = []
    if line.get("recording", {}).get("sha256") != sha:
        problems.append("%s hashes to %s, its manifest line says %s" % (log, sha, line.get("recording", {}).get("sha256")))
    if not listed or listed[0] != sha:
        problems.append("%s hashes to %s, %s.sha256 says %s" % (log, sha, log, listed[0] if listed else "nothing"))
    if len(listed) > 1 and listed[1:] != [log]:
        problems.append("%s.sha256 names %s, not %s" % (log, listed[1:], log))
    seed = line.get("source", {}).get("params", {}).get("seed")
    if summary.get("name") != line.get("name"):
        problems.append("summary.json names %r, the manifest line %r" % (summary.get("name"), line.get("name")))
    if not isinstance(summary.get("trip"), dict) or summary["trip"].get("seed") != seed:
        problems.append("summary.json's trip is not the manifest line's seed %r" % (seed,))
    if line.get("recording", {}).get("format") != "candump-log":
        problems.append("the recording's format is %r, not candump-log" % (line.get("recording", {}).get("format"),))
    problems += rtf_problems(line["source"])
    trip = summary.get("trip")
    if isinstance(trip, dict) and "rtf" in trip and trip["rtf"] != line["source"].get("rtf"):
        problems.append("summary.json's trip rtf %r is not the manifest line's %r" % (trip["rtf"], line["source"].get("rtf")))
    if problems:
        raise InjectError("the source recording %s does not check: %s" % (src_dir, "; ".join(problems)))
    return Source(src_dir, line, summary, raw[log].decode("ascii"), {n: sha256_bytes(b) for n, b in raw.items()}, log)


def source_unchanged(src: Source) -> None:
    now = {n: sha256_file(src.dir / n) for n in src.hashes}
    if now != src.hashes:
        raise InjectError("the source recording %s changed while it was read: %s" % (
            src.dir, sorted(n for n in now if now[n] != src.hashes[n])))


# --- the decoded timeline -------------------------------------------------------------------------------------

@dataclass
class Decoded:
    """The slot messages' frames as the bridge would hold them: offsets in ns from the file's first frame."""
    t0_us: int
    dyn: List[Tuple[int, Dict[int, float]]]          # (offset, {slot: value}) for the dynamics message's slots
    by_line: List[Tuple[str, Dict[str, Any]]]        # (message name, decoded signals) per line, in file order


def held(slot: int, value: Any) -> Any:
    """A value as the bridge holds it: a float slot through binary32 (vss_claim_bridge.raw_of), the gear as it is."""
    return value if slot == SLOT_GEAR else vf.bits_f32(vb.raw_of(slot, value))


def decode_lines(lines: Sequence[Line], db: Any, contract: Any) -> Decoded:
    sig_slot = {s: i for i, s in enumerate(contract.SLOT_DBC_SIGNALS)}
    dyn_msg = contract.SLOT_DBC_MESSAGES[SLOT_V]
    t0 = lines[0].t_us
    dyn: List[Tuple[int, Dict[int, float]]] = []
    by_line: List[Tuple[str, Dict[str, Any]]] = []
    for ln in lines:
        try:
            msg = db.get_message_by_frame_id(ln.can_id)
            vals = msg.decode(ln.data, decode_choices=False, scaling=True)
        except Exception as err:  # noqa: BLE001 -- a frame the DBC cannot decode refuses the file
            raise InjectError("the frame %r does not decode with the DBC: %r" % (ln.text, err)) from err
        by_line.append((msg.name, dict(vals)))
        if msg.name == dyn_msg:
            dyn.append(((ln.t_us - t0) * US, {sig_slot[s]: held(sig_slot[s], v) for s, v in vals.items() if s in sig_slot}))
    return Decoded(t0, dyn, by_line)


def rule26_excess(vals: Dict[int, float], pr: rules.Profile, tables: rules.Tables) -> Optional[float]:
    """psi_dot_kin - tol where rule 26 judges a frame with a zeroed yaw (inside its speed window and delta_max, under the
    a_y bound); None elsewhere."""
    av, ad = rules.dabs(vals[SLOT_V]), rules.dabs(vals[SLOT_DELTA])
    if not (pr.v26_lo <= av <= pr.v26_hi and ad <= pr.delta_max):
        return None
    kin, ay = rules.kinematics(av, ad, pr.l_mm, tables)
    if not (pr.ay26_max == 0.0 or ay <= pr.ay26_max):
        return None
    return kin - pr.tol26


def rule26_must_fire(vals: Dict[int, float], pr: rules.Profile, tables: rules.Tables) -> bool:
    """sigsim's rule26_above_tol counter (sigsim.judge_stream): inside rule 26's speed window and delta_max, under the
    a_y bound, psi_dot_kin above tol -- a zeroed yaw must give 26 there."""
    over = rule26_excess(vals, pr, tables)
    return over is not None and over > 0.0


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


# --- placement --------------------------------------------------------------------------------------------------

@dataclass
class Placed:
    kind: Kind
    inj0: int                   # the injected span [inj0, inj1), ns from the first frame
    inj1: int
    t0: int                     # the window [t0, t1)
    t1: int
    value: Any = None           # the value written (as the DBC carries it, filled by the rewrite)
    can_id: Optional[int] = None    # the CAN id of the message rewritten (the DBC's)
    frames: List[int] = field(default_factory=list)    # line indexes rewritten
    travel: int = 0             # the sign of travel over the window (speed, accel)
    least: Optional[float] = None   # the least excess over the window's condition (yaw: kin - tol; gear: v - v_tol)


def _condition(kind: Kind, vals: Dict[int, float], pr: rules.Profile, tables: rules.Tables,
               need: Dict[int, Dict[str, Any]]) -> Optional[Tuple[int, Optional[float]]]:
    """None if the frame does not suit the event; else (its sign of travel, 0 where it does not matter; the excess over
    the event's condition, where it has one, which must exceed the event's margin)."""
    if kind.slot in (SLOT_V, SLOT_AX):
        s = sign(vals[SLOT_V])
        return (s, None) if s != 0 else None
    if kind.slot == SLOT_YAW:
        over = rule26_excess(vals, pr, tables)
        return (0, over) if over is not None and over > need[SLOT_YAW]["value"] else None
    if kind.slot == SLOT_GEAR:
        over = vals[SLOT_V] - pr.v_tol
        return (0, over) if over > need[SLOT_GEAR]["value"] else None
    return (0, None)


def place(dec: Decoded, pr: rules.Profile, tables: rules.Tables, contract: Any, profile_id: int) -> List[Placed]:
    span, allow = event_span_ns(contract), allowance_ns(contract)
    if span < MIN_EVENT_TICKS * TICK_NS:
        raise InjectError("an event's span of %d ns is shorter than %d ticks (specification 14.2)" % (span, MIN_EVENT_TICKS))
    need = margins(contract, profile_id)
    end = dec.dyn[-1][0]
    cursor = SEPARATION_NS
    out: List[Placed] = []
    for kind in SLOT_EVENTS:
        inj0 = grid_ceil(cursor + allow)
        while True:
            t0, t1 = inj0 - allow, inj0 + span + allow
            if t1 > end:
                raise InjectError("no place in the recording for the %s event after %d ms" % (kind.event, cursor // MS))
            got = [_condition(kind, vals, pr, tables, need) for off, vals in dec.dyn if t0 <= off < t1]
            ok = [g for g in got if g is not None]
            if got and len(ok) == len(got) and len({g[0] for g in ok}) == 1:
                excess = [g[1] for g in ok if g[1] is not None]
                out.append(Placed(kind, inj0, inj0 + span, t0, t1, travel=int(ok[0][0]), least=min(excess) if excess else None))
                break
            inj0 += TICK_NS
        cursor = t1 + SEPARATION_NS
    return out


# --- the rewrite -------------------------------------------------------------------------------------------------

def reverse_gear(summary: Dict[str, Any]) -> int:
    """The reverse gear the source trip itself engages (summary.json trip.gear_changes: [t_ms, old, new])."""
    for change in summary["trip"].get("gear_changes", []):
        if isinstance(change[2], int) and change[2] < 0:
            return int(change[2])
    raise InjectError("the source trip never engages a reverse gear (summary.json trip.gear_changes)")


def target_value(p: Placed, pr: rules.Profile, gear: int) -> Any:
    if p.kind.slot == SLOT_YAW:
        return 0.0
    if p.kind.slot == SLOT_GEAR:
        return gear
    assert p.kind.limit is not None
    limit = float(getattr(pr, p.kind.limit)) * INJECT_FACTOR
    return p.travel * limit if p.kind.slot in (SLOT_V, SLOT_AX) else limit


def rewrite(lines: List[Line], dec: Decoded, placed: Sequence[Placed], db: Any, contract: Any, pr: rules.Profile,
            gear: int) -> List[Line]:
    """The lines with every event's frames rewritten (module docstring, THE EVENTS); refused if a value leaves the
    DBC's range, or if a re-encoded frame changes anything but the event's signal."""
    out = list(lines)
    for p in placed:
        assert p.kind.slot is not None
        sig_name = contract.SLOT_DBC_SIGNALS[p.kind.slot]
        msg_name = contract.SLOT_DBC_MESSAGES[p.kind.slot]
        msg = db.get_message_by_name(msg_name)
        sig = msg.get_signal_by_name(sig_name)
        want = target_value(p, pr, gear)
        p.can_id = int(msg.frame_id)
        if not (sig.minimum <= want <= sig.maximum):
            raise InjectError("the %s event's value %r is outside %s's range [%r, %r] in the DBC" % (
                p.kind.event, want, sig_name, sig.minimum, sig.maximum))
        for i, ln in enumerate(lines):
            off = (ln.t_us - dec.t0_us) * US
            if ln.can_id != msg.frame_id or not p.inj0 <= off < p.inj1:
                continue
            _name, vals = dec.by_line[i]
            if bytes(msg.encode(dict(vals))) != ln.data:
                raise InjectError("%r does not re-encode to its own bytes through the DBC" % ln.text)
            data = bytes(msg.encode(dict(vals, **{sig_name: want})))
            got = msg.decode(data, decode_choices=False, scaling=True)
            others = {k: v for k, v in got.items() if k != sig_name}
            if others != {k: v for k, v in vals.items() if k != sig_name}:
                raise InjectError("rewriting %s in %r changed another signal" % (sig_name, ln.text))
            if p.value is None:
                p.value = got[sig_name]
            elif got[sig_name] != p.value:
                raise InjectError("the %s event's value is not the same in every frame" % p.kind.event)
            out[i] = Line(format_line(ln.t_us, ln.channel, ln.can_id, data), ln.t_us, ln.channel, ln.can_id, data)
            p.frames.append(i)
        if len(p.frames) < 1:
            raise InjectError("the %s event rewrote no frame" % p.kind.event)
    return out


# --- the offline replay: the replay-mode bridge's packing and the reference judge ----------------------------------

@dataclass
class Replay:
    anchor_ns: int
    records: List[Dict[str, Any]]       # ClaimCore.reply's record of every packed frame, in seq order
    counters: Dict[str, int]
    intake: Dict[str, int]

    def offsets(self) -> List[Tuple[int, Dict[str, Any]]]:
        return [(r["src_now_ns"] - self.anchor_ns, r) for r in self.records]


def bridge_config(line: Dict[str, Any]) -> vb.Config:
    """The run items a replay-mode bridge would get for this recording (its scenario entry: profile and vehicle)."""
    return vb.Config(host="127.0.0.1", port=SVC_PORT, mode="replay", profile_id=line["profile_id"], profile_source="scenario",
                     source_vehicle=dict(line["source"]["vehicle"]))


def replay_offline(frames: Sequence[Tuple[int, int, bytes]], db: Any, contract: Any, cfg: vb.Config, until_ns: int,
                   stop_ns: Optional[int] = None) -> Replay:
    """What a replay-mode bridge packs from these frames, tick by tick, each judged by rules.reply.

    The source is bridge_sources.ReplaySource on a fake monotonic clock: the bridge's start reads it first (the grid's
    origin, half a tick later, logged as replay-anchored), its stream is run to its end with a sleep that moves the
    clock to each due instant, and the ticks then come one tick apart from the start reading, as the claim thread's
    loop schedules them, each offered first the batches delivered before it. stop_ns realises the stop (22) as the
    replay mode does, an intake pause: no batch due at or after that offset is held. The ticks run through until_ns
    (an offset from the file's first frame), past the file's end if it is later."""
    tables, problems = vb.bind(cfg, contract)
    if problems or tables is None:
        raise InjectError("the bridge would refuse to start: %s" % "; ".join(problems))
    t = [CLOCK0_NS]

    def clock() -> int:
        return t[0]

    def sleep(seconds: float) -> None:
        t[0] += max(1, math.ceil(seconds * 1e9))

    log = vb.EventLog()
    src = bs.ReplaySource(bs.SlotDecoder(db, contract), frames, clock=clock, sleep=sleep)
    src.attach_log(log.write)
    start = t[0]
    src.now_ns()
    anchor = rs.replay_anchor(log.records)
    deliveries: List[Tuple[int, List[vb.Update]]] = []
    for batch in src.updates():
        deliveries.append(((t[0] - anchor) // TICK_NS, batch))
    hv = vb.HeldValues()
    intake = vb.Intake(hv, log)
    core = vb.ClaimCore(cfg, contract, tables, log)
    records: List[Dict[str, Any]] = []
    i = j = 0
    while True:
        wall = start + j * TICK_NS
        while i < len(deliveries) and anchor + deliveries[i][0] * TICK_NS < wall:
            k, batch = deliveries[i]
            if stop_ns is not None and k * TICK_NS >= stop_ns:
                intake.paused.set()
            intake.offer(batch)
            i += 1
        t[0] = wall
        now = src.now_ns()
        if now - anchor > until_ns:
            break
        p = core.tick(hv.snapshot(), now, wall)
        if p is not None:
            q = core.take()
            assert q is p
            ok, rec = core.reply(q, rules.reply(q.frame, tables))
            if not ok:
                raise InjectError("the bridge refused the reference judge's reply to seq %d: %s" % (q.seq, rec))
            records.append(rec)
        j += 1
    return Replay(anchor, records, dict(core.n), dict(intake.n))


# --- the expected reasons -------------------------------------------------------------------------------------------

def windows(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"event": e["event"], "t0_ns": e["t0_ns"], "t1_ns": e["t1_ns"]} for e in events]


def _one_reason(e: Dict[str, Any], rejects: Sequence[Tuple[int, Dict[str, Any]]]) -> List[int]:
    reasons = sorted({r["reason"] for _off, r in rejects})
    if len(reasons) == 1:
        e["reason"] = reasons[0]
        e["reason_name"] = rules.REASON_NAMES[reasons[0]]
    return reasons


def judge_run(rp: Replay, events: List[Dict[str, Any]], through_ns: int, contract: Any) -> Dict[str, Any]:
    """One run's events (the five injected ones, then the run's two 22 windows; copies) judged on its offline replay:
    fills each one's reason and replay, and refuses unless the replay is exactly the events (module docstring, THE
    EXPECTED REASONS)."""
    injected, first, rest = events[:-2], events[-2], events[-1]
    if (first["intended_reason"] != STALE_REASON or rest["intended_reason"] != STALE_REASON or first["t1_ns"] != rest["t0_ns"]
            or rest["t1_ns"] != OPEN_END_NS or not all(e["injected_ns"] for e in injected)
            or any(e["t1_ns"] > first["t0_ns"] for e in injected)):
        raise InjectError("a run is its injected events, then a bounded 22 window and an open-ended one after them")
    ref = first["t0_ns"]
    age_max_ms = int(contract.AGE_MAX_MS)
    spans = [(e["injected_ns"][0], e["injected_ns"][1], e) for e in injected]
    problems: List[str] = []
    seen: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {e["event"]: [] for e in injected}
    after: List[Tuple[int, Dict[str, Any]]] = []
    elsewhere = {"accepted": 0, "rejected": 0}
    offsets = rp.offsets()
    for off, r in offsets:
        inside = next((e for a, b, e in spans if a <= off < b), None)
        if inside is not None:
            seen[inside["event"]].append((off, r))
        elif off >= ref:
            after.append((off, r))
        elif r["verdict"]:
            elsewhere["rejected"] += 1
            problems.append("a reject (reason %d) at %d ms, outside every event" % (r["reason"], off // MS))
        else:
            elsewhere["accepted"] += 1
    if not offsets or offsets[-1][0] + TICK_NS < through_ns:
        problems.append("the replay ended before the run's run_through_ns (%d ms)" % (through_ns // MS))
    for e in injected:
        got = seen[e["event"]]
        rej = [(off, r) for off, r in got if r["verdict"]]
        reasons = _one_reason(e, rej)
        acc = [off for off, r in got if not r["verdict"]]
        if acc or reasons != [e["intended_reason"]] or len(rej) < MIN_EVENT_TICKS:
            problems.append("%s: its span was judged %s with %d rejects (need %d) and ACCEPTs at %s ms; intended %d" % (
                e["event"], reasons, len(rej), MIN_EVENT_TICKS, [a // MS for a in acc], e["intended_reason"]))
        e["replay"] = {"ticks_ms": [off // MS for off, _r in got], "rejected_ticks": len(rej)}
    rej = [(off, r) for off, r in after if r["verdict"]]
    in_first = [(off, r) for off, r in rej if off < first["t1_ns"]]
    in_rest = [(off, r) for off, r in rej if off >= rest["t0_ns"]]
    for e, part in ((first, in_first), (rest, in_rest)):
        reasons = _one_reason(e, part)
        if reasons != [STALE_REASON] or len(part) < MIN_EVENT_TICKS:
            problems.append("%s: judged %s with %d rejects (need %d)" % (e["event"], reasons, len(part), MIN_EVENT_TICKS))
    if rej:
        t_first, r0 = rej[0]
        late = [off // MS for off, r in after if not r["verdict"] and off > t_first]
        if late:
            problems.append("%s: ACCEPTs after the first 22 at %s ms" % (first["event"], late[:3]))
        if t_first - ref > age_max_ms * MS + TICK_NS:
            problems.append("%s: the first 22 comes %d ms after %d ms, not within AGE_MAX plus one tick" % (
                first["event"], (t_first - ref) // MS, ref // MS))
        if not age_max_ms < r0["age_ms"] <= age_max_ms + TICK_NS // MS:
            problems.append("%s: the first 22 has age %d ms, not above AGE_MAX and within AGE_MAX plus one tick" % (first["event"], r0["age_ms"]))
        first["replay"] = {"reference_ms": ref // MS, "first_reject_ms": t_first // MS, "first_reject_age_ms": r0["age_ms"],
                           "accepted_from_reference_ms": [off // MS for off, r in after if not r["verdict"]], "rejected_ticks": len(in_first)}
        rest["replay"] = {"rejected_ticks": len(in_rest), "last_tick_ms": after[-1][0] // MS}
    else:
        problems.append("%s: no 22 at or after %d ms" % (first["event"], ref // MS))
    expected = {(e["event"], e.get("reason")) for e in events}
    got_set = rs.reason_set(rp.records, rs.shift_windows(windows(events), rp.anchor_ns))
    cmp = rs.compare(expected, got_set)
    if not cmp["ok"]:
        problems.append("the event-to-reason set is not the run's: %s" % cmp)
    if problems:
        raise InjectError("the offline replay does not give the events: " + "; ".join(problems))
    return {"ticks": rp.counters["ticks"], "packed": rp.counters["packed"], "replied": rp.counters["replied"],
            "accepted_before_reference": elsewhere["accepted"], "rejected_outside_events": elsewhere["rejected"],
            "reason_set": sorted([list(p) for p in got_set], key=lambda p: (str(p[0]), p[1])),
            "intake": rp.intake}


def stale_windows(run: str, ref_ns: int, contract: Any) -> List[Dict[str, Any]]:
    """A run's two 22 windows from its reference (module docstring, THE RUNS)."""
    a, b = RUN_WINDOWS[run]
    mid = ref_ns + first22_ns(contract)
    return [{"event": a, "intended_reason": STALE_REASON, "t0_ns": ref_ns, "t1_ns": mid, "injected_ns": None, "rewrite": None,
             "first_22_by_ns": ref_ns + int(contract.AGE_MAX_MS) * MS + TICK_NS},
            {"event": b, "intended_reason": STALE_REASON, "t0_ns": mid, "t1_ns": OPEN_END_NS, "open_end": True,
             "injected_ns": None, "rewrite": None}]


def judge_runs(frames: Sequence[Tuple[int, int, bytes]], injected: List[Dict[str, Any]], runs: Dict[str, Dict[str, Any]], db: Any,
               contract: Any, cfg: vb.Config) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Each run replayed offline (the stop run with its intake pause) and judged (judge_run); refused unless the
    injected events judge the same in every run. Returns the judged injected events and runs (copies)."""
    until = max(r["run_through_ns"] for r in runs.values())
    judged_inj: Optional[List[Dict[str, Any]]] = None
    out: Dict[str, Dict[str, Any]] = {}
    for name in RUNS:
        run = copy.deepcopy(runs[name])
        evs = copy.deepcopy(injected) + run["events"]
        rp = replay_offline(frames, db, contract, cfg, until, stop_ns=run["stop_ns"])
        run["replay_check"] = judge_run(rp, evs, run["run_through_ns"], contract)
        run["events"] = evs[-2:]
        if judged_inj is None:
            judged_inj = evs[:-2]
        elif evs[:-2] != judged_inj:
            raise InjectError("the injected events judge differently in the %s run" % name)
        out[name] = run
    assert judged_inj is not None
    return judged_inj, out


# --- the hard-brake app's view (the stack's own checks of a recording) --------------------------------------------------

def _replaycheck() -> Any:
    """sdv/stack/replaycheck.py, read-only (its pure functions; no bytecode written)."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    if str(STACK_DIR) not in sys.path:
        sys.path.insert(0, str(STACK_DIR))
    try:
        import replaycheck
    finally:
        sys.dont_write_bytecode = saved
    return replaycheck


def app_view(lines: Sequence[Line], db: Any, contract: Any, trip: Dict[str, Any]) -> Dict[str, Any]:
    """The hard-brake app's predicted switches and the stack's expected windows on a log, as the stack's prepare
    computes them (replaycheck.predict, expected_windows), from frames decoded as replaycheck.decode_recording gives them."""
    rc = _replaycheck()
    t0 = lines[0].t_us
    frames = []
    for ln in lines:
        msg = db.get_message_by_frame_id(ln.can_id)
        frames.append((int(round((ln.t_us - t0) / 1000.0)), msg.name, dict(msg.decode(ln.data, decode_choices=False, scaling=True))))
    v_sig, a_sig = contract.SLOT_DBC_SIGNALS[SLOT_V], contract.SLOT_DBC_SIGNALS[SLOT_AX]
    win = rc.expected_windows(trip, frames, v_sig, int(contract.DBC_PERIOD_MS[contract.RULE26_DBC_MESSAGE]))
    return {"prediction": rc.predict(frames, v_sig, a_sig, rc.hazard_module()), "windows": win}


# --- the whole rewrite, in memory --------------------------------------------------------------------------------------

@dataclass
class Built:
    name: str
    source: Source
    log_text: str
    events: Dict[str, Any]


def tool_sha256() -> str:
    return sha256_file(TOOL)


def build(src_dir: Path, name: str, db: Any, contract: Any, dbc_path: Path) -> Built:
    """Everything of the new recording but its paths, computed and checked in memory (module docstring)."""
    if not NAME_PATTERN.fullmatch(name):
        raise InjectError("the name %r is not a manifest-line name [a-z0-9][a-z0-9-]{0,47}" % name)
    src = read_source(src_dir)
    if name == src.line["name"]:
        raise InjectError("the new recording needs a name of its own, not the source's %r" % name)
    missing = [k for k in TRIP_NEEDED if k not in src.summary["trip"]]
    if missing:
        raise InjectError("the source's summary.json trip has no %s" % missing)
    params = src.line["source"]["params"]
    over = params_problems(params)                                   # refused before anything is written (THE NEW RECORDING)
    if over:
        raise InjectError("the source's params would break the scenario entry's limits: %s" % "; ".join(over))
    dbc_sha = bs.check_dbc_generation(Path(dbc_path), contract)      # the DBC a replay-mode bridge would take (its generation)
    if params.get("dbc_sha256") != dbc_sha:
        raise InjectError("the DBC %s (sha256 %s) is not the one the source was encoded with (%s): name that one with --dbc"
                          % (dbc_path, dbc_sha, params.get("dbc_sha256")))
    if params.get("catalog_digest") != "0x%08X" % contract.CATALOG_DIGEST:
        raise InjectError("the source was made for catalogue digest %s, the contract's is 0x%08X"
                          % (params.get("catalog_digest"), contract.CATALOG_DIGEST))
    cfg = bridge_config(src.line)
    tables, problems = vb.bind(cfg, contract)
    if problems or tables is None:
        raise InjectError("a replay-mode bridge would refuse this recording: %s" % "; ".join(problems))
    pr = tables.profiles[cfg.profile_id]
    lines = parse_lines(src.log_text, str(src.dir / src.log_name))
    if frames_of(lines) != bs.read_candump(src.dir / src.log_name):
        raise InjectError("this tool and the bridge's candump reader read the source differently")
    dec = decode_lines(lines, db, contract)
    counted = sum(1 for _off, vals in dec.dyn if rule26_must_fire(vals, pr, tables))
    want26 = src.summary.get("verify", {}).get("judge", {}).get("rule26_above_tol")
    if counted != want26:
        raise InjectError("the rule-26 predicate counts %d frames of the decoded source, sigsim's counter %r: they are not the same"
                          % (counted, want26))
    placed = place(dec, pr, tables, contract, cfg.profile_id)
    new_lines = rewrite(lines, dec, placed, db, contract, pr, reverse_gear(src.summary))
    before, after = app_view(lines, db, contract, src.summary["trip"]), app_view(new_lines, db, contract, src.summary["trip"])
    if before["prediction"] != after["prediction"]:
        raise InjectError("the rewrite changes the hard-brake app's predicted switches: %s -> %s" % (before["prediction"], after["prediction"]))
    last = last_offset_ns(new_lines)
    stop = grid_ceil(max(placed[-1].t1, int(after["windows"]["off_window_ms"][1]) * MS) + SEPARATION_NS)
    if run_through_ns(stop, contract) > last:
        raise InjectError("no room for the stop run before the file's end: it runs through %d ms, the last frame is at %d ms"
                          % (run_through_ns(stop, contract) // MS, last // MS))
    runs = {
        "stop": {"reference": "the stop", "reference_ns": stop, "stop_ns": stop, "run_through_ns": run_through_ns(stop, contract),
                 "realisation": realisations("stop", stop), "events": stale_windows("stop", stop, contract)},
        "to_end": {"reference": "the file's last frame", "reference_ns": last, "stop_ns": None, "run_through_ns": run_through_ns(last, contract),
                   "realisation": realisations("to_end", last), "events": stale_windows("to_end", last, contract)},
    }
    need = margins(contract, cfg.profile_id)
    injected = [event_record(p, contract, cfg.profile_id, need) for p in placed]
    injected, runs = judge_runs(frames_of(new_lines), injected, runs, db, contract, cfg)
    text = "".join(ln.text + "\n" for ln in new_lines)
    rewritten_from = {"name": src.line["name"], "dir": str(src.dir), "log_sha256": src.hashes[src.log_name],
                      "manifest_line_sha256": src.hashes[MANIFEST_NAME], "summary_sha256": src.hashes[SUMMARY_NAME]}
    if "rtf" in src.line["source"]:
        rewritten_from["rtf"] = dict(src.line["source"]["rtf"])    # the rtf the line copies, on record (A CARLA SOURCE)
    doc = {
        "format": EVENTS_FORMAT,
        "recording": {"name": name, "log": src.log_name, "sha256": sha256_bytes(text.encode("ascii"))},
        "rewritten_from": rewritten_from,
        "tool": {"path": str(TOOL.relative_to(REPO)), "sha256": tool_sha256()},
        "contract": {"digest": "0x%08X" % contract.CATALOG_DIGEST, "sha256": vb.contract_sha256(contract), "profile_id": cfg.profile_id,
                     "age_max_ms": int(contract.AGE_MAX_MS), "pipeline_allowance_ms": int(contract.PIPELINE_ALLOWANCE_MS)},
        "dbc_sha256": dbc_sha,
        "time_base": "t0_ns, t1_ns, injected_ns, reference_ns, stop_ns and run_through_ns are ns from the recording's first frame; "
                     "a window is half open; reasonsets.shift_windows puts them on a run's src_now_ns clock (replay: the run's "
                     "replay-anchored anchor_ns)",
        "design": design_of(contract, cfg.profile_id),
        "checks": {"rule26_predicate_count": counted, "hazard_prediction_unchanged": True, "app_windows": after["windows"]},
        "events": injected,
        "runs": runs,
    }
    laid = layout_problems(doc, new_lines, contract) + condition_problems(doc, decode_lines(new_lines, db, contract), contract, cfg)
    if laid:
        raise InjectError("the events file is not laid out as designed: %s" % "; ".join(laid))
    source_unchanged(src)
    return Built(name, src, text, doc)


def design_of(contract: Any, profile_id: int) -> Dict[str, Any]:
    """events.json's design block: the design values (module docstring, DESIGN VALUES) as the current contract makes them."""
    need = margins(contract, profile_id)
    return {"tick_ns": TICK_NS, "allowance_ns": allowance_ns(contract), "event_span_ns": event_span_ns(contract),
            "first_22_ns": first22_ns(contract), "min_event_ticks": MIN_EVENT_TICKS, "inject_factor": INJECT_FACTOR,
            "separation_ns": SEPARATION_NS, "open_end_ns": OPEN_END_NS, "margins": {"yaw": need[SLOT_YAW], "gear": need[SLOT_GEAR]}}


def realisations(run: str, ref_ns: int) -> Dict[str, Dict[str, Any]]:
    if run == "stop":
        return {m: dict(r, at_offset_ns=ref_ns, undone=False) for m, r in REALISATION_22.items()}
    return {m: dict(r) for m, r in REALISATION_END.items()}


def layout_problems(doc: Dict[str, Any], lines: Sequence[Line], contract: Any) -> List[str]:
    """events.json's windows, runs and design block laid out as this tool lays them out (module docstring, PLACEMENT,
    THE RUNS), recomputed from the design values and the current contract."""
    problems: List[str] = []
    span, allow = event_span_ns(contract), allowance_ns(contract)
    if doc.get("design") != design_of(contract, int(doc["contract"]["profile_id"])):
        problems.append("events.json's design block is not this tool's with this contract")
    if [e["event"] for e in doc["events"]] != [k.event for k in SLOT_EVENTS]:
        problems.append("events.json's events are %s" % [e["event"] for e in doc["events"]])
    prev_end: Optional[int] = None
    for e in doc["events"]:
        a, b = e["injected_ns"]
        if b - a != span or a % TICK_NS or (e["t0_ns"], e["t1_ns"]) != (a - allow, b + allow):
            problems.append("the %s event's span or window is not the design's" % e["event"])
        if prev_end is not None and e["t0_ns"] - prev_end < SEPARATION_NS:
            problems.append("the %s event's window starts less than SEPARATION_NS after the previous one" % e["event"])
        prev_end = e["t1_ns"]
    last = last_offset_ns(lines)
    if set(doc["runs"]) != set(RUNS):
        problems.append("events.json's runs are %s" % sorted(doc["runs"]))
        return problems
    for name in RUNS:
        run = doc["runs"][name]
        ref = run["reference_ns"]
        if name == "stop":
            ok = (run["stop_ns"] == ref and ref % TICK_NS == 0 and prev_end is not None and ref >= prev_end + SEPARATION_NS
                  and run_through_ns(ref, contract) <= last)
        else:
            ok = run["stop_ns"] is None and ref == last
        if not ok:
            problems.append("the %s run's reference or stop is not the design's" % name)
        if run["run_through_ns"] != run_through_ns(ref, contract) or run["realisation"] != realisations(name, ref):
            problems.append("the %s run's run_through_ns or realisation is not the design's" % name)
        if [{k: v for k, v in e.items() if k not in JUDGED_KEYS} for e in run["events"]] != stale_windows(name, ref, contract):
            problems.append("the %s run's 22 windows are not the design's" % name)
    return problems


def condition_problems(doc: Dict[str, Any], dec: Decoded, contract: Any, cfg: vb.Config) -> List[str]:
    """Every frame of each event's window, in the file itself, still meets the event's placement condition with its
    margin (the rewrite changes no signal a condition reads), and the least excess events.json records is the file's."""
    tables, bad = vb.bind(cfg, contract)
    if bad or tables is None:
        return ["a replay-mode bridge would refuse this recording: %s" % "; ".join(bad)]
    pr, need = tables.profiles[cfg.profile_id], margins(contract, cfg.profile_id)
    problems: List[str] = []
    for e in doc["events"]:
        kind = next(k for k in SLOT_EVENTS if k.event == e["event"])
        got = [_condition(kind, vals, pr, tables, need) for off, vals in dec.dyn if e["t0_ns"] <= off < e["t1_ns"]]
        ok = [g for g in got if g is not None]
        excess = [g[1] for g in ok if g[1] is not None]
        least = min(excess) if excess else None
        recorded = e["rewrite"].get("condition", {}).get("least_excess")
        if not got or len(ok) != len(got) or len({g[0] for g in ok}) != 1 or least != recorded:
            problems.append("the %s event's window no longer meets its condition with its margin, or its least excess is not %r"
                            % (e["event"], recorded))
    return problems


def event_record(p: Placed, contract: Any, profile_id: int, need: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    assert p.kind.slot is not None
    rec: Dict[str, Any] = {
        "event": p.kind.event, "intended_reason": p.kind.reason, "t0_ns": p.t0, "t1_ns": p.t1, "injected_ns": [p.inj0, p.inj1],
        "rewrite": {"slot": p.kind.slot, "vss_path": contract.SLOT_PATHS[p.kind.slot], "message": contract.SLOT_DBC_MESSAGES[p.kind.slot],
                    "signal": contract.SLOT_DBC_SIGNALS[p.kind.slot], "can_id": p.can_id, "value": p.value, "frames": len(p.frames)}}
    if p.kind.limit is not None:
        rows = {int(r["id"]): r for r in contract.PROFILES}
        rec["rewrite"]["beyond"] = {"profile_id": profile_id, "limit": p.kind.limit, "value": rows[profile_id][p.kind.limit],
                                    "factor": INJECT_FACTOR}
    else:
        rec["rewrite"]["condition"] = dict(need[p.kind.slot], least_excess=p.least)
    return rec


# --- writing the new directory -------------------------------------------------------------------------------------

def path_form(log: Path) -> str:
    """The recording's path as its manifest line keeps it: the ~ form under ~/sdv-recordings, else as written."""
    home_rec = RECORDINGS.expanduser().resolve()
    try:
        rel = log.resolve().relative_to(home_rec)
    except ValueError:
        return str(log.resolve())
    return str(RECORDINGS / rel)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def summary_of(b: Built, dest: Path, events_sha: str) -> Dict[str, Any]:
    """summary.json: the source's trip cut to TRIP_KEPT (module docstring, THE NEW RECORDING), and the provenance; for a
    carla source, that steps.jsonl was not copied (A CARLA SOURCE)."""
    trip = b.source.summary["trip"]
    rewrite = {"from": dict(b.events["rewritten_from"]), "events": EVENTS_NAME, "events_sha256": events_sha,
               "tool": dict(b.events["tool"]), "trip_fields_dropped": sorted(k for k in trip if k not in TRIP_KEPT),
               "note": "trip is the source recording's, cut to the fields that still describe this file (the rewrite moves no "
                       "frame); the dropped fields describe the source drive's values, which the events change; the source's "
                       "verify block is not carried over (its frames are not these)"}
    if b.source.line["source"]["generator"] == "carla":
        rewrite["not_copied"] = {STEPS_NAME: "the take's steps, from which this log cannot be regenerated: the events rewrite "
                                             "frames the steps would give back unchanged"}
    return {"name": b.name, "dir": str(dest), "trip": {k: trip[k] for k in TRIP_KEPT if k in trip}, "rewrite": rewrite}


def write(b: Built, dest: Path) -> Dict[str, Any]:
    """Create dest (never an existing one) and write the recording into it; on any failure remove what was written."""
    dest = Path(dest)
    if _inside(dest, REPO):
        raise InjectError("refused: %s is inside the repository; recordings belong outside it (~/sdv-recordings)" % dest)
    if _inside(dest, b.source.dir) or _inside(b.source.dir, dest):
        raise InjectError("refused: %s and the source recording %s overlap" % (dest, b.source.dir))
    if dest.name != b.name:
        raise InjectError("refused: the directory %s is not named %s" % (dest, b.name))
    if not is_scenario_path(path_form(dest / b.source.log_name)):     # else check, and the manifest's loader, refuse it
        raise InjectError("refused: the new recording's path %r is not a scenario entry path (manifest-classes.md section 9)"
                          % path_form(dest / b.source.log_name))
    source_unchanged(b.source)
    os.mkdir(dest)                                  # exclusive: an existing directory is somebody's recording (FileExistsError)
    written: List[Path] = []

    def put(name: str, data: bytes) -> str:
        path = dest / name
        with open(path, "xb") as f:
            written.append(path)
            f.write(data)
        return sha256_bytes(data)

    log = b.source.log_name                         # the new recording keeps the source's log name
    try:
        log_bytes = b.log_text.encode("ascii")
        sha = put(log, log_bytes)
        if bs.read_candump(dest / log) != frames_of(parse_lines(b.log_text, "the new log")):
            raise InjectError("the written log does not read back as the rewrite's frames")
        put(log + ".sha256", ("%s  %s\n" % (sha, log)).encode("ascii"))
        events_bytes = (json.dumps(b.events, sort_keys=True, indent=1) + "\n").encode("ascii")
        events_sha = put(EVENTS_NAME, events_bytes)
        put(SUMMARY_NAME, (json.dumps(summary_of(b, dest, events_sha), sort_keys=True, indent=1) + "\n").encode("ascii"))
        line = manifest_line(b, path_form(dest / log), sha, events_sha)
        put(MANIFEST_NAME, (json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
        source_unchanged(b.source)
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)
        dest.rmdir()
        raise
    return {"dir": str(dest), "name": b.name, "sha256": sha, "events_sha256": events_sha,
            "runs": {run: [(e["event"], e.get("reason")) for e in run_events(b.events, run)] for run in RUNS}}


def manifest_line(b: Built, path: str, sha: str, events_sha: str) -> Dict[str, Any]:
    src = b.source.line
    params = dict(src["source"]["params"])
    added = {"rewrite_of": src["name"], "rewrite_of_sha256": b.source.hashes[b.source.log_name], "rewrite_events_sha256": events_sha}
    clash = sorted(set(added) & set(params))
    if clash:
        raise InjectError("the source's params already carry %s: a rewrite of a rewrite is not supported" % clash)
    params.update(added)
    if len(params) > PARAMS_MAX or any(isinstance(v, str) and len(v) > PARAM_LEN_MAX for v in params.values()):
        raise InjectError("source.params would break the scenario entry's limits: %s" % params)
    source = {"generator": src["source"]["generator"], "params": params, "vehicle": dict(src["source"]["vehicle"])}
    if "rtf" in src["source"]:
        source["rtf"] = dict(src["source"]["rtf"])     # unchanged: the rewrite moves no frame (A CARLA SOURCE)
    return {"name": b.name, "profile_id": src["profile_id"],
            "recording": {"format": src["recording"]["format"], "path": path, "sha256": sha}, "source": source}


# --- check: a recording made here, again ------------------------------------------------------------------------------

JUDGED_KEYS = ("reason", "reason_name", "replay")


def check(rec_dir: Path, db: Any, contract: Any, dbc_path: Path) -> Dict[str, Any]:
    """A recording made by `rewrite`, checked again from its own files: its identity (the stack's), the events file it
    names, made with this contract and this DBC (the generation's), the line's rtf the one events.json records (none
    for a sigsim recording), every frame decoding with the DBC, each run's offline replay giving exactly the reasons
    and replay records events.json carries, and -- when the source recording is still there -- the source unchanged,
    its rtf the line's, and the rewrite exactly the events' frames (when it is gone, a warning on stderr and
    `source.skipped`). Raises InjectError on the first failure."""
    rec = read_source(rec_dir)
    ev_raw = (Path(rec_dir) / EVENTS_NAME).read_bytes()
    doc = json.loads(ev_raw.decode("ascii"))
    if doc.get("format") != EVENTS_FORMAT:
        raise InjectError("events.json is format %r; this tool reads format %d" % (doc.get("format"), EVENTS_FORMAT))
    params = rec.line["source"]["params"]
    dbc_sha = bs.check_dbc_generation(Path(dbc_path), contract)
    problems = []
    if params.get("rewrite_events_sha256") != sha256_bytes(ev_raw):
        problems.append("events.json's sha256 is not the manifest line's rewrite_events_sha256")
    if (doc["recording"]["sha256"] != rec.hashes[rec.log_name] or doc["recording"]["name"] != rec.line["name"]
            or doc["recording"].get("log") != rec.log_name):
        problems.append("events.json names another recording")
    if params.get("rewrite_of_sha256") != doc["rewritten_from"]["log_sha256"] or params.get("rewrite_of") != doc["rewritten_from"]["name"]:
        problems.append("the manifest line and events.json name different sources")
    if doc["rewritten_from"].get("rtf") != rec.line["source"].get("rtf"):
        problems.append("the manifest line's rtf %r is not the one events.json says the rewrite copied (%r)"
                        % (rec.line["source"].get("rtf"), doc["rewritten_from"].get("rtf")))
    if rec.summary.get("rewrite", {}).get("events_sha256") != sha256_bytes(ev_raw):
        problems.append("summary.json's rewrite names another events file")
    if (doc["contract"]["digest"], doc["contract"]["sha256"]) != ("0x%08X" % contract.CATALOG_DIGEST, vb.contract_sha256(contract)):
        problems.append("events.json was made with another contract (%s, %s)" % (doc["contract"]["digest"], doc["contract"]["sha256"]))
    if doc["dbc_sha256"] != dbc_sha or params.get("dbc_sha256") != dbc_sha:
        problems.append("events.json (%s) or the manifest line (%s) names another DBC than %s"
                        % (doc["dbc_sha256"], params.get("dbc_sha256"), dbc_sha))
    if problems:
        raise InjectError("; ".join(problems))
    lines = parse_lines(rec.log_text, str(Path(rec_dir) / rec.log_name))
    dec = decode_lines(lines, db, contract)
    laid = layout_problems(doc, lines, contract) + condition_problems(doc, dec, contract, bridge_config(rec.line))
    if laid:
        raise InjectError("events.json is not laid out as designed: %s" % "; ".join(laid))
    strip =[{k: v for k, v in e.items() if k not in JUDGED_KEYS} for e in doc["events"]]
    runs = {name: dict({k: v for k, v in doc["runs"][name].items() if k != "replay_check"},
                       events=[{k: v for k, v in e.items() if k not in JUDGED_KEYS} for e in doc["runs"][name]["events"]])
            for name in RUNS}
    injected, judged = judge_runs(frames_of(lines), strip, runs, db, contract, bridge_config(rec.line))
    for mine, theirs in zip(injected + [e for n in RUNS for e in judged[n]["events"]],
                            doc["events"] + [e for n in RUNS for e in doc["runs"][n]["events"]]):
        if mine.get("reason") != theirs.get("reason"):
            raise InjectError("the %s event: the replay gives %r, events.json says %r" % (mine["event"], mine.get("reason"), theirs.get("reason")))
        if mine.get("replay") != theirs.get("replay"):
            raise InjectError("the %s event: the replay's record is not events.json's" % mine["event"])
    for name in RUNS:
        if json.loads(json.dumps(judged[name]["replay_check"])) != doc["runs"][name]["replay_check"]:
            raise InjectError("the %s run: the replay's check is not events.json's" % name)
    out: Dict[str, Any] = {"dir": str(rec_dir), "ok": True,
                           "runs": {n: [(e["event"], e["reason"]) for e in injected + judged[n]["events"]] for n in RUNS}}
    src_dir = Path(doc["rewritten_from"]["dir"])
    if (src_dir / rec.log_name).exists():
        src = read_source(src_dir)
        if src.hashes[src.log_name] != doc["rewritten_from"]["log_sha256"]:
            raise InjectError("the source recording %s is not the one this was rewritten from" % src_dir)
        if rec.line["source"].get("rtf") != src.line["source"].get("rtf"):
            raise InjectError("the recording's rtf %r is not its source's %r: a rewrite copies it unchanged"
                              % (rec.line["source"].get("rtf"), src.line["source"].get("rtf")))
        out["source"] = {"dir": str(src_dir), "diff": diff_against(src, lines, doc, db)}
    else:
        why = "the source recording %s is gone: the diff against it was skipped" % src_dir
        print("inject: warning: %s" % why, file=sys.stderr)
        out["source"] = {"dir": str(src_dir), "skipped": why}
    return out


def diff_against(src: Source, lines: Sequence[Line], doc: Dict[str, Any], db: Any) -> Dict[str, int]:
    """The rewritten lines against the source's: the same frames in the same order, and only the events' frames (their
    message, inside their injected span) differ, each only in the event's signal, which carries the event's value.
    Returns the number of differing lines per event."""
    old = parse_lines(src.log_text, str(src.dir / src.log_name))
    if len(old) != len(lines):
        raise InjectError("the rewrite has %d lines, the source %d" % (len(lines), len(old)))
    t0 = old[0].t_us
    rewrites = [e for e in doc["events"] if e["rewrite"]]
    by_event = {e["event"]: 0 for e in rewrites}
    for a, b in zip(old, lines):
        if (a.t_us, a.channel, a.can_id) != (b.t_us, b.channel, b.can_id):
            raise InjectError("the rewrite moved a frame: %r -> %r" % (a.text, b.text))
        if a.text == b.text:
            continue
        off = (a.t_us - t0) * US
        owner = [e for e in rewrites if e["rewrite"]["can_id"] == a.can_id and e["injected_ns"][0] <= off < e["injected_ns"][1]]
        if len(owner) != 1:
            raise InjectError("a line differs outside every event: %r -> %r" % (a.text, b.text))
        e = owner[0]
        msg = db.get_message_by_frame_id(a.can_id)
        va = msg.decode(a.data, decode_choices=False, scaling=True)
        vb_ = msg.decode(b.data, decode_choices=False, scaling=True)
        sig = e["rewrite"]["signal"]
        if {k: v for k, v in va.items() if k != sig} != {k: v for k, v in vb_.items() if k != sig} or vb_[sig] != e["rewrite"]["value"]:
            raise InjectError("the %s event's line changes more than %s, or not to its value: %r -> %r" % (e["event"], sig, a.text, b.text))
        by_event[e["event"]] += 1
    for e in rewrites:
        if by_event[e["event"]] != e["rewrite"]["frames"]:
            raise InjectError("the %s event names %d frames, %d differ" % (e["event"], e["rewrite"]["frames"], by_event[e["event"]]))
    return by_event


# --- the command line --------------------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("rewrite", help="write a new injected recording and its events file")
    w.add_argument("--from", dest="src", required=True, help="the source recording directory (a sigsim or a CARLA recording)")
    w.add_argument("--name", required=True, help="the new recording's name (a new directory under --root)")
    g = w.add_mutually_exclusive_group()
    g.add_argument("--root", default=None, help="where the new directory goes (default ~/sdv-recordings)")
    g.add_argument("--out", default=None, help="the new directory itself (its last component must be --name)")
    w.add_argument("--dbc", default=None, help="the DBC the source was encoded with (default sdv/vss/slice.dbc)")
    w.add_argument("--gen", default=None, help="the generated contract's directory (default sdv-out/gen)")
    c = sub.add_parser("check", help="check a recording this tool made, again")
    c.add_argument("dir")
    c.add_argument("--dbc", default=None, help="the DBC (default sdv/vss/slice.dbc); it must be the contract's generation")
    c.add_argument("--gen", default=None)
    return ap


def main(argv: Optional[Sequence[str]] = None, load_db: Optional[Callable[[Path, Any], Any]] = None) -> int:
    a = _parser().parse_args(argv)
    try:
        contract = vf.load_contract(a.gen)
        dbc = Path(a.dbc) if a.dbc else bs.SLICE_DBC
        db = (load_db or _load_db)(dbc, contract)
        if a.cmd == "rewrite":
            dest = Path(a.out) if a.out else Path(a.root or RECORDINGS).expanduser() / a.name
            built = build(Path(a.src).expanduser(), a.name, db, contract, dbc)
            out = write(built, dest)
        else:
            out = check(Path(a.dir).expanduser(), db, contract, dbc)
    except (InjectError, vf.ContractError, vb.BridgeError, OSError, ValueError, KeyError) as err:
        print("inject: %s: %s" % (type(err).__name__, err), file=sys.stderr)
        return 1
    print(json.dumps(out, sort_keys=True))
    return 0


def _load_db(path: Path, contract: Any) -> Any:
    """The DBC through cantools, strict (the sim venv's); build and check also hold it to the contract's generation."""
    import cantools  # lazily: only the command line needs it
    return cantools.database.load_file(str(path), strict=True)


if __name__ == "__main__":
    sys.exit(main())
