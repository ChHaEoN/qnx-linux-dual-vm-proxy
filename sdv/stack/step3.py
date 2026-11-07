#!/usr/bin/env python3
"""step3.py -- Phase 2 step 3 on the PC: the claim bridge in each of its modes against the native vss monitor
(sdv/stack; Phase 2 WP10).

Runs in WSL Ubuntu-24.04 with the sim venv's Python, from the repo root, with the
bridge image by ID (sdv/bridge/build_image.py prints it) and a sigsim or a CARLA recording (SDV_RECORDING, read, never
written; THE RECORDING below):

    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/step3.py run --mode MODE --spec SPEC [SPEC ...]
        [--repeat N] [--name NAME] [--images build|loaded]
        [--monitor guest --guest-console FILE --guest-image FILE [--guest-host ADDR]]
    ~/sdv-sim-venv/bin/python sdv/stack/step3.py plan --mode MODE --spec SPEC      # the plan only; nothing runs
    ~/sdv-sim-venv/bin/python sdv/stack/step3.py compare --name NAME [--modes MODE ... --] DIR [DIR ...]   # result.json under each DIR

`--images loaded` (SDV Phase 3 WP1) is the stack's images mode on an aarch64 host (stack.py, IMAGES): broker's images are
inspected, never pulled or built, and the bridge must be its arm64 pin; `build`, the default, is the PC's.
`--monitor guest` (SDV Phase 3 WP2) is GUEST MODE, below; `native`, the default, is the PC's. SDV_HOST_ROLE names the
host (stack.py, HOST ROLE); SDV_CONTAINER_CPUSET and SDV_AFTER_START place its containers (stack.py, PLACEMENT: on orin
both are required, in either monitor mode). While the twin-control marker exists (stack.py, TWIN CONTROL; SDV Phase 6
WP2) every `run` is refused before anything is read, made or started, since each one starts a bridge; a run whose
context was made before the marker appeared is refused at the bridge's start. `plan` and `compare` start nothing and
take no notice of it.

A RUN is one spec (step3-runs.json) in one bridge mode: the native vss monitor `monitor-vss 7160 svc 500` (stack.py's
build, never the default OUT) and the bridge image in that mode, configured by the run header, with a script of
control calls (vss_claim_bridge.py, SCRIPT) that this module writes from the spec and the events file:
  broker  the whole stack over the vcan feed (stack.up, as WP8: databroker, providers, recorder, witness, app, the
          bridge with its write-back), then the can-provider and python-can's player on vcan0.
  can     vcan0 (created with sudo -n if missing), the bridge's SocketCAN adapter, python-can's player; no databroker,
          no write-back.
  replay  the bridge reads the staged recording itself; no databroker, no bus, no write-back.

THE RECORDING (SDV Phase 7 WP3b; spec-2 2.1, 5 item 6). Its log is the one its manifest line names by its generator
(line_log: the stack's one rule, bundle.py's log_name_of over LOG_NAMES, inject.py's table held equal by a test):
sigsim.log, or carla.log for a CARLA recording; any other pair is refused naming both. The form of the line's path is not
read (inject.py checks it for the recordings it writes), as the stack, the bundle and setup do not. The stack stages it
under that name (stack.py, RECORDING KINDS AND RUN TYPES), and the player, the bus check and the run's record take it by
that name (stack.log_of). An events file names its recording's log too (inject.py's recording.log), which must be the
line's. compare groups by the recording's sha256, as before.

THE WINDOWS AND THE EXPECTED SET. An injected recording's events file (sdv/inject, WP9; beside the recording, its
recording and log, contract, DBC, tick and manifest line's events sha256 checked) gives the injected events and, per run
(`stop`, `to_end`), its two 22 windows, its run_through_ns and the stop's per-mode realisation. A recording without
one (an honest recording, sigsim or CARLA) has only the to_end run, derived from its own log as inject.py derives it
(its own stale_windows, run_through_ns and realisations, imported, never copied) with no injected event. A spec adds
its own windows (its scripted events). The expected set is {(event, reason)} over every window; the run's set is
reasonsets.reason_set of its reply log on those windows, each window shifted by its origin:
  recording windows  replay: the run's grid anchor (its replay-anchored record); can and broker: the SocketCAN
                     receive time of the recording's first frame on the stack's own vcan capture (CLOCK_REALTIME,
                     the clock both live sources stamp on).
  script windows     the bridge's own script origin (its script-origin record): replay's anchor, can's first frame's
                     receive time, broker's first datapoint timestamp; the instant the scripted call was timed from.

THE STOP (22; the events file's runs.stop.realisation, CHANGES.md Phase 2 design decision v). Its offset S is the
events file's at_offset_ns, never a literal here, and each mode has exactly one realisation, never undone:
  replay  Bridge.pause_intake, a script step at S - tick/2 on the replay clock: between the grid's delivery at
          S - tick and its delivery at S, where the events file says the offline replay's pause lands.
  can     the player stopped (SIGTERM) at origin + S - tick/2 on CLOCK_REALTIME.
  broker  the can-provider stopped at origin + S - tick/2 by SIGKILL to its process (sudo -n kill; its PID read before
          the player starts), not by a docker kill, whose round trip through the daemon would put an unbounded delay
          between the instant and the stop, which the windows' allowance does not cover; the player plays on and the
          databroker keeps the last values, whose datapoint timestamps age.
A to_end run stops nothing (the file's end is the provider stopping). The live modes' half tick is the same instant
as replay's; a late stop (the signal's own delivery included) is what the windows' allowance A covers. Each stop's
issued and returned instants, and the realisation made (its `how`, named by the call that made it, never copied
from the plan), are in the run's result (drive.stop).

RUN-THROUGH. Every run keeps the bridge ticking past the file's end, through the run's run_through_ns: the script's
last step ends the run (as --seconds would) one tick past the first instant of the events file's tick grid at or past
run_through_ns, on the script's origin; for a run_through_ns on the grid, one tick after it. run_through_ns is the
recording's (inject.py's, from its stop or its last frame), not the grid's: a CARLA log's last frame can lie a 20 ms
SliceDynamics period past a grid instant. Replay reads each grid instant half a tick after it, or up to about half a
tick later still (bridge_sources.py, replay), so the end must lie a tick past the first grid instant that can answer
at or past run_through_ns. An end one tick after an off-grid run_through_ns can come before that instant is read,
leaving no reply at or past run_through_ns. The live modes, whose ticks are not on the recording's grid, have a tick
in every tick-long span, and the end is never less than a tick after run_through_ns. The harness never stops the bridge at
the player's end; it waits for the bridge to end itself, and stops it (a failed gate) only END_SLACK_S after the
script's end step. A run is ticked through when its last reply's offset is at or past run_through_ns.

STEP PHASE. A spec's steps sit on the tick grid (their at_ns a multiple of the events file's tick); each runs a
quarter tick after its grid instant, between that instant's delivery (replay delivers on the grid) and the tick that
reads it (half a tick after the grid), so in replay it acts on that tick deterministically.

PER RUN (~/sdv-runs/<date>-<name>/<spec>-<mode>-<k>/): plan.json (the windows, the expected set, the stop, the
script), bridge-script.json, bridge-header.json, the bridge's directory (bridge.jsonl, replies.jsonl -- each reply
with the 64 bytes sent -- summary.json, source.json), monitor.log (the console; guest-console.log in guest mode),
listeners.json (before, during, at the end: the stack may add listeners on loopback only, and the native monitor's
INADDR_ANY one by its PID), attribution.json (the header, C10, C12a, C8 for broker, C12b), player.log (live), the
containers' logs, result.json (with c12b_lines, the number of `vss rules:` lines that parse, and with SDV_AFTER_START set
after_start: the hook's record of each container the run started, stack.py's PLACEMENT, written before a failed hook stops
the run). Its gates:
  reason_set        the run's set equals the expected set (a missing or an extra pair fails it);
  ticked_through    the last reply at or past run_through_ns;
  stop              stop runs: the planned realisation made, at its instant (replay: its script step done between
                    the two deliveries; live: the stack's call issued within the tick before S); to_end runs: none made;
  bridge_ended_itself, bridge_exit, script   the script ran every step and ended the run; the container exited 0;
  identity          packed = replied + drop + lost_on_reconnect, ticks = packed + ticks_empty, the seq partition;
  accounting        drop = 0 and lost_on_reconnect = 0, in every run, the pause runs included (the plan's exit: every
                    actual run; the paths with a drop or a loss are pytest's). The bridge's drop records are reported
                    by their why (drops_by_why); a drop is a finding whatever its why, `paused` included;
  no_fatal, no_uninjected_21;
  console           runs without a pause: no LIVENESS MISS, RESTORED or `client closed:` before the bridge's last
                    session ends (the console's last `client done:`; a MISS after it is the monitor outliving the
                    bridge); pause runs: spec 14.4's sequence (one MISS, then one close for silence, the bridge
                    seeing that close -- one `closed` record with the peer's why after the pause, never its own close
                    at its stop -- and one reconnect, the first frame after the tick's resume ACCEPT (tick) or 22 with
                    its age above AGE_MAX (both), and one RESTORED naming that frame's seq); in guest mode also no
                    garbled line (below);
  start_checks (C10, C12a), listeners (all three snapshots), c12b, and for live runs bus (every frame on vcan0 the
  log's, in order: the whole log, or for a stopped player a prefix ending inside the tick before S); in guest mode
  also console_end (below).

GUEST MODE (--monitor guest; SDV Phase 3 WP2, for the instance's suite)  The run is judged by the QNX guest's vss monitor,
which the guest image starts itself (ifs-vss.build: `qnx-safety-monitor 7160 svc 500`); the bridge reaches it at
--guest-host (default GUEST_HOST, the guest's address on br0; an address that is not IPv4, or is loopback, is refused,
and so is one of this host's own addresses unless SDV_HOST_ROLE is pc, where the stand-in guest is this host; the
component records host_local), and nothing is built or started for it here: no native monitor, and the listener check
allows nothing. --guest-image names the image the guest booted; its file name and sha256 are the run's monitor
component (stack.py's vss-monitor-guest). One call is one fresh boot: --repeat above 1 and more than one spec are
refused.
  The console is the guest's serial console file (--guest-console; QEMU's log, with NUL bytes and CR in it), which must
exist and pass the FRESHNESS GATE at the call and again at the run's start: no LIVENESS line, no `client closed:`, and no
`client done:` with seen above 0, anywhere in a line (five instances share the console, and their lines can
interleave). The launch probe's and the readiness check's seen=0 lines pass only when each probe closes within the
guest's 500 ms deadline: a probe whose socket is held open past it (a descriptor left open, a stalled close) leaves
`client closed: no complete frame` before its seen=0, and the gate refuses the console, saying so. The run's judged
console begins at the offset recorded at the run's gate (the end of the last whole line then). After the run the
console is read once, NUL and CR removed (run_console): the whole goes to the run directory as guest-console.log, which
C12b reads (the five `vss rules:` lines come at boot; result.json's c12b_lines counts those that parse, c12b_expected is
five, and c12b_note notes another count, which fails nothing unless it is 0, when C12b fails for want of a line), and
result.json's console_file records the raw file's path, bytes and sha256 as read. The console gate and the pause
sequences judge only what follows the offset: the guest still runs, and the probe's seen=0 line before it would
otherwise pass for the bridge's last session end and move the run's MISS lines to "after". After the offset the split is
the last clean `client done:` with seen above 0 (the bridge's sessions always end so; a later seen=0 line is a probe's,
counted as seen_0). The gates match their markers at line start, so in guest mode a judged line that holds `LIVENESS`,
`client closed:` or `client done:` anywhere but as its own start is GARBLED (another writer's bytes inside it: only
:7160 should write during the run, but QEMU's stderr and four idle instances share the file) and fails the console gate,
named in result.json's console.problems; native mode counts such lines, not gated. Before that read, a bounded wait
(CONSOLE_END_S) for as many `client done:` lines with seen above 0 after the offset as the bridge had sessions (its
connect records, at least one: a pause run's first session ends before its last); the console_end gate fails unless
exactly that many came, naming a surplus (a client that was not the bridge judged claims on :7160). The last one's seen
is recorded beside the bridge's reply count, not gated: their equality is not established. A console that cannot be
read, at either gate or after the run, is a refusal naming it.

COMPARE (plan step 3's last item): the result.json of every run under the DIRs, grouped by recording (sha256) and
spec; in each group every run was judged and passed its own gates (a result.json that an aborted run left, with no
reason set, fails its group by name), every mode of --modes (default all three) has a run and every set equals every
other (reasonsets.compare_modes), and two replay runs of one group are compared frame by frame, apart from the
header's tstamp (reasonsets.compare_frames on the reply logs' frames). Never frame by frame across modes. A run of one
of the bridge's modes that --modes does not list is left out and named (left_out). compare.json in its own run
directory.

DESIGN VALUES of this harness (none generated, none a claim): STEP_PHASE (a quarter tick), the stop's half tick
(the events file's note), END_SLACK_S (10 s), ORIGIN_TIMEOUT_S (30 s: the player's first frame, the replay's
anchor), PLAYER_SLACK_S (60 s past the file's duration), CONSOLE_END_S (5 s: guest mode's wait for the console's
last session end). The pause test's 1.5 s and every spec offset are the spec file's.

DOES NOT DEMONSTRATE: any timing (the windows carry the specification's allowance A; no field is a latency); CAN
arbitration, error frames or bus timing (vcan has none); in native mode anything about the QNX guest (the monitor is
the native build of the same monitor.c, not the guest, io-sock or the image); that can and replay behave as broker
does behind the VSS API (both bypass it; spec 14.2); that the databroker served each value the provider wrote; for a
CARLA recording, anything about CARLA, its drive or vehicle dynamics (a recorded file is replayed as sigsim's is). In
guest mode: any timing; that the guest's monitor saw every frame the bridge sent (seen is recorded, not compared);
the guest's boot, io-sock, or the image beyond its sha256; on the PC, with the native monitor standing in for the
guest, anything about the guest at all.

The startup-qemu-virt that boots the guest under KVM is ours, not a QNX-supported configuration,
and no timing claim attaches to the boot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.dont_write_bytecode = True
for _d in (REPO / "sdv" / "inject", REPO / "sdv" / "frame", REPO / "sdv" / "bridge", HERE):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import attribution as attr  # noqa: E402
import bridge_sources as bs  # noqa: E402
import inject as inj  # noqa: E402
import reasonsets as rs  # noqa: E402
import rules  # noqa: E402
import stack as st  # noqa: E402
import vss_claim_bridge as vb  # noqa: E402

SPECS_FILE = HERE / "step3-runs.json"
SPECS_FORMAT = 1
MODES = vb.MODES
RECORDING_KINDS = ("honest", "injected")
# the pause sequences of spec 14.4, each with exactly the steps it needs, in order
SEQUENCES = {"tick": ["pause_tick", "resume_tick"], "both": ["pause_intake", "pause_tick", "resume_tick", "resume_intake"]}
SPEC_KEYS = {"what", "recording", "run", "steps", "windows", "sequence"}
WINDOW_KEYS = {"event", "t0_ns", "t1_ns", "reason"}
REASON_BY_NAME = {name: code for code, name in rules.REASON_NAMES.items()}
# The events file's realisation actions (sdv/inject/inject.py REALISATION_22), and the one each mode may make.
STOP_HOW = {"stop the can-provider": "can-provider", "stop the player": "player", "pause the intake": "intake"}
MODE_STOP = {"broker": "can-provider", "can": "player", "replay": "intake"}
INTAKE_CALL = "Bridge.pause_intake"
FEED = {"broker": "vcan", "can": "vcan", "replay": "none"}

# Design values of this harness (module docstring, DESIGN VALUES).
END_SLACK_S = 10.0
ORIGIN_TIMEOUT_S = 30.0
PLAYER_SLACK_S = 60.0
CONSOLE_END_S = 5.0

# Guest mode (module docstring, GUEST MODE).
MONITORS = st.MONITOR_MODES
GUEST_HOST = "192.168.100.10"         # the guest's static address on br0 (launch-qnx-kvm-bridged.sh's :7100 probe)
GUEST_CONSOLE = "guest-console.log"   # the run directory's copy of the guest's console, NUL and CR removed
GUEST_RULES_LINES = 5                 # ifs-vss.build starts the vss monitor five times on one console: five at boot

MISS = "monitor: LIVENESS MISS: "
RESTORED_RX = re.compile(r"^monitor: LIVENESS RESTORED: seq=(\d+) after ")
CLOSED_SILENT = "monitor: client closed: no complete frame for "
CLOSED_UNTAKEN = "monitor: client closed: reply not taken for "
DONE = "monitor: client done: "
DONE_SEEN_RX = re.compile(r"^monitor: client done: seen=(\d+) ")
# The freshness gate's operands (module docstring, GUEST MODE): anywhere in a line, since lines can interleave.
FRESH_LIVENESS = "LIVENESS"
FRESH_CLOSED = "client closed:"
FRESH_SILENT = "client closed: no complete frame for "
FRESH_DONE_RX = re.compile(r"client done: seen=(\d+)")
# A judged line holding one of these anywhere but as its own clean start (one of CLEAN_STARTS) is garbled: another writer's
# bytes are inside it (module docstring, GUEST MODE). The same operands as the freshness gate's.
MARKERS = (FRESH_LIVENESS, FRESH_CLOSED, "client done:")
CLEAN_STARTS = (MISS, "monitor: LIVENESS RESTORED: ", "monitor: client closed: ", DONE)
GARBLED_SHOWN = 5                     # garbled lines recorded whole in result.json (each cut at 200 characters); all counted
# The bridge's `closed` record's why when the peer closed (vss_claim_bridge.py: _readable's EOF, and the check before a
# send); its other whys are its own closes ("stop" at its end, "reply-timeout", ...). A test holds these to the bridge.
PEER_CLOSE_WHY = ("peer closed", "peer-closed (seen before a send)")

Pair = Tuple[Optional[str], int]


class StepError(RuntimeError):
    """A refusal: a spec, an events file or a plan this harness will not run."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _pair_key(p: Sequence[Any]) -> Tuple[str, int]:
    return ("" if p[0] is None else str(p[0]), int(p[1]))


# --- the run specs ------------------------------------------------------------------------------------------------

def check_spec(name: str, s: Any) -> Dict[str, Any]:
    """One run spec, checked (module docstring; step3-runs.json): its keys, recording kind and run, its steps (no end
    step: the harness adds it), its windows (a reason by rules.py's name) and its pause sequence."""
    if not isinstance(s, Mapping) or not set(s) <= SPEC_KEYS or not {"what", "recording", "run"} <= set(s):
        raise StepError("spec %s: keys %s; a spec has what, recording, run and optionally steps, windows, sequence"
                        % (name, sorted(s) if isinstance(s, Mapping) else s))
    if s["recording"] not in RECORDING_KINDS:
        raise StepError("spec %s: recording %r is not one of %s" % (name, s["recording"], ", ".join(RECORDING_KINDS)))
    if s["run"] not in inj.RUNS:
        raise StepError("spec %s: run %r is not one of %s" % (name, s["run"], ", ".join(inj.RUNS)))
    if s["recording"] == "honest" and s["run"] != "to_end":
        raise StepError("spec %s: an honest recording has only the to_end run (no events file names a stop)" % name)
    steps = list(s.get("steps", []))
    if any(not isinstance(x, Mapping) or x.get("call") == "end" for x in steps):
        raise StepError("spec %s: a step is an object, and never end: the harness ends the run past its run_through_ns" % name)
    try:
        vb.parse_script({"format": vb.SCRIPT_FORMAT, "steps": steps})
    except vb.BridgeError as err:
        raise StepError("spec %s: %s" % (name, err)) from err
    for w in s.get("windows", []):
        if not isinstance(w, Mapping) or set(w) != WINDOW_KEYS:
            raise StepError("spec %s: a window is {event, t0_ns, t1_ns, reason}, not %r" % (name, w))
        if w["reason"] not in REASON_BY_NAME or REASON_BY_NAME[w["reason"]] == rules.RSN_OK:
            raise StepError("spec %s: window %s: %r is not a reject reason's name (rules.REASON_NAMES)" % (name, w["event"], w["reason"]))
        if not (isinstance(w["t0_ns"], int) and isinstance(w["t1_ns"], int) and 0 <= w["t0_ns"] < w["t1_ns"]):
            raise StepError("spec %s: window %s is not 0 <= t0_ns < t1_ns in ns" % (name, w["event"]))
    seq = s.get("sequence")
    if seq is not None:
        calls = [x["call"] for x in steps]
        need = SEQUENCES.get(seq)
        if need is None or calls != need:
            raise StepError("spec %s: sequence %r needs exactly the steps %s, in that order (has %s)" % (name, seq, need, calls))
    return dict(s)


def load_specs(path: Path = SPECS_FILE) -> Dict[str, Dict[str, Any]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or doc.get("format") != SPECS_FORMAT or not isinstance(doc.get("specs"), Mapping):
        raise StepError("%s is not a format %d spec file" % (path, SPECS_FORMAT))
    return {name: check_spec(name, s) for name, s in doc["specs"].items()}


# --- the events file ------------------------------------------------------------------------------------------------

def line_log(line: Mapping[str, Any]) -> str:
    """A recording's log by its manifest line (module docstring, THE RECORDING; spec-2 2.1): the stack's one rule,
    bundle.py's log_name_of, the basename of recording.path when it is the generator's (LOG_NAMES, inject.py's table held
    equal by a test); any other pair, another name or another generator is refused naming both. The form of the path is
    not read, as the stack, the bundle and setup do not read it."""
    name, why = st.bd.log_name_of(dict(line))
    if name is None:
        raise StepError("the recording: %s" % why)
    return name


def check_events(doc: Any, raw: bytes, rec_sha256: str, line: Mapping[str, Any], contract: Any) -> List[str]:
    """What an injected recording's events.json must be to run against: WP9's format, this recording and its log (the one
    its manifest line names, line_log), the manifest line's events sha256, this contract and DBC, the bridge's tick, and
    both runs."""
    if not isinstance(doc, Mapping):
        return ["events.json is not an object"]
    problems = []
    params = line["source"]["params"]
    try:
        log: Optional[str] = line_log(line)
    except StepError as err:
        problems.append(str(err))
        log = None
    if doc.get("format") != inj.EVENTS_FORMAT:
        problems.append("format %r, not %d" % (doc.get("format"), inj.EVENTS_FORMAT))
    if (doc.get("recording") or {}).get("sha256") != rec_sha256:
        problems.append("it names recording %s, not this %s (%s)" % ((doc.get("recording") or {}).get("sha256"), log or "log", rec_sha256))
    if log is not None and (doc.get("recording") or {}).get("log") != log:
        problems.append("it names the log %r, not this recording's %r" % ((doc.get("recording") or {}).get("log"), log))
    if params.get("rewrite_events_sha256") != sha256_bytes(raw):
        problems.append("its sha256 is not the manifest line's rewrite_events_sha256")
    c = doc.get("contract") or {}
    if (c.get("digest"), c.get("sha256")) != ("0x%08X" % contract.CATALOG_DIGEST, vb.contract_sha256(contract)):
        problems.append("it was made with another contract (%s, %s)" % (c.get("digest"), c.get("sha256")))
    if doc.get("dbc_sha256") != params.get("dbc_sha256"):
        problems.append("its DBC %s is not the recording's %s" % (doc.get("dbc_sha256"), params.get("dbc_sha256")))
    if (doc.get("design") or {}).get("tick_ns") != vb.TICK_NS:
        problems.append("it was made for a %r ns tick, the bridge ticks every %d ns" % ((doc.get("design") or {}).get("tick_ns"), vb.TICK_NS))
    if set(doc.get("runs") or {}) != set(inj.RUNS):
        problems.append("its runs are %s, not %s" % (sorted(doc.get("runs") or {}), list(inj.RUNS)))
    return problems


def honest_doc(rec_dir: Path, rec_sha256: str, line: Mapping[str, Any], contract: Any) -> Dict[str, Any]:
    """A recording without an events file: its to_end run as inject.py derives it (R the file's last frame, its two 22
    windows, run_through_ns and the realisations, from inject.py's own functions), with no injected event, from the log
    its manifest line names (line_log: an honest CARLA recording's carla.log)."""
    params = line["source"]["params"]
    if any(k in params for k in ("rewrite_of", "rewrite_events_sha256")):
        raise StepError("%s is a rewritten recording (its manifest line names a rewrite) but has no %s" % (rec_dir, inj.EVENTS_NAME))
    log = line_log(line)
    text = (Path(rec_dir) / log).read_text(encoding="ascii")
    lines = inj.parse_lines(text, str(Path(rec_dir) / log))
    if sha256_bytes(text.encode("ascii")) != rec_sha256:
        raise StepError("%s is not the recording the stack staged" % (Path(rec_dir) / log))
    last = inj.last_offset_ns(lines)
    return {"format": inj.EVENTS_FORMAT, "recording": {"name": line["name"], "log": log, "sha256": rec_sha256},
            "derived": "no events file: the to_end run as sdv/inject/inject.py derives it, with no injected event; its "
                       "22 windows' reason is their intended one (nothing injected, so nothing to judge offline)",
            "design": inj.design_of(contract, int(line["profile_id"])), "events": [],
            "runs": {"to_end": {"reference": "the file's last frame", "reference_ns": last, "stop_ns": None,
                                "run_through_ns": inj.run_through_ns(last, contract), "realisation": inj.realisations("to_end", last),
                                "events": [dict(e, reason=e["intended_reason"]) for e in inj.stale_windows("to_end", last, contract)]}},
            "events_file": None}


def events_doc(rec_dir: Path, rec_sha256: str, line: Mapping[str, Any], contract: Any) -> Dict[str, Any]:
    """The run windows' source: the recording's events.json (checked, check_events), or the derived to_end run."""
    path = Path(rec_dir) / inj.EVENTS_NAME
    if not path.is_file():
        return honest_doc(rec_dir, rec_sha256, line, contract)
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    problems = check_events(doc, raw, rec_sha256, line, contract)
    if problems:
        raise StepError("%s cannot be run against: %s" % (path, "; ".join(problems)))
    return dict(doc, events_file={"path": str(path), "sha256": sha256_bytes(raw)})


# --- the plan -------------------------------------------------------------------------------------------------------

def realisation(run_name: str, run: Mapping[str, Any], mode: str, tick_ns: int) -> Optional[Dict[str, Any]]:
    """The run's stop as the events file realises it in this mode (module docstring, THE STOP), or None for a run with no
    stop. Its offset is the file's at_offset_ns, which must be the run's stop_ns; the action must be the mode's one."""
    real = (run.get("realisation") or {}).get(mode)
    if not isinstance(real, Mapping):
        raise StepError("the events file's %s run names no realisation for %s" % (run_name, mode))
    action = str(real.get("action", ""))
    if run.get("stop_ns") is None:
        if not action.startswith("none"):
            raise StepError("the %s run stops nothing, but its %s realisation is %r" % (run_name, mode, action))
        return None
    how = STOP_HOW.get(action)
    if how is None:
        raise StepError("the %s run's %s realisation %r is not one of %s" % (run_name, mode, action, sorted(STOP_HOW)))
    if how != MODE_STOP[mode]:
        raise StepError("the %s run realises %s's stop by %r; %s stops only by %s" % (run_name, mode, action, mode, MODE_STOP[mode]))
    if how == "intake" and real.get("call") != INTAKE_CALL:
        raise StepError("the %s run's replay stop calls %r, not %s" % (run_name, real.get("call"), INTAKE_CALL))
    at = real.get("at_offset_ns")
    if not isinstance(at, int) or isinstance(at, bool) or at != run["stop_ns"]:
        raise StepError("the %s run's %s realisation is at %r, not the run's stop_ns %r" % (run_name, mode, at, run["stop_ns"]))
    if real.get("undone") is not False:
        raise StepError("the %s run's %s stop is undone (%r): a stop here is never undone" % (run_name, mode, real.get("undone")))
    return {"how": how, "action": action, "at_offset_ns": at, "call_offset_ns": at - tick_ns // 2,
            "from": "the events file's runs.%s.realisation.%s" % (run_name, mode)}


def plan_run(doc: Mapping[str, Any], spec_name: str, spec: Mapping[str, Any], mode: str) -> Dict[str, Any]:
    """One run's plan, from the events doc and the spec only: the windows with their origins, the expected set, the
    stop, run_through_ns, and the bridge's script (the spec's steps a quarter tick after their grid instants, replay's
    stop, and the end one tick past the first grid instant at or past run_through_ns)."""
    if mode not in MODES:
        raise StepError("mode %r is not one of %s" % (mode, ", ".join(MODES)))
    spec = check_spec(spec_name, spec)
    tick = int(doc["design"]["tick_ns"])
    if tick != vb.TICK_NS:
        raise StepError("the events doc was made for a %d ns tick, the bridge ticks every %d ns" % (tick, vb.TICK_NS))
    has_file = doc.get("events_file") is not None
    if spec["recording"] == "injected" and not has_file:
        raise StepError("spec %s needs an injected recording's events file; %s has none" % (spec_name, doc["recording"].get("name")))
    if spec["recording"] == "honest" and has_file:
        raise StepError("spec %s is for an honest recording; this one is injected (its windows would overlap the spec's)" % spec_name)
    run = doc["runs"].get(spec["run"])
    if run is None:
        raise StepError("the events doc has no %s run" % spec["run"])
    stop = realisation(spec["run"], run, mode, tick)
    windows = [{"event": e["event"], "t0_ns": int(e["t0_ns"]), "t1_ns": int(e["t1_ns"]), "reason": int(e["reason"]), "origin": "recording"}
               for e in list(doc["events"]) + list(run["events"])]
    windows += [{"event": w["event"], "t0_ns": w["t0_ns"], "t1_ns": w["t1_ns"], "reason": REASON_BY_NAME[w["reason"]], "origin": "script"}
                for w in spec.get("windows", [])]
    steps: List[Dict[str, Any]] = []
    for s in spec.get("steps", []):
        if s["at_ns"] % tick:
            raise StepError("spec %s: step %s at %d ns is not on the %d ns tick grid" % (spec_name, s["call"], s["at_ns"], tick))
        steps.append(dict(s, at_ns=s["at_ns"] + tick // 4))
    if stop is not None and stop["how"] == "intake":
        steps.append({"at_ns": stop["call_offset_ns"], "call": "pause_intake"})
    steps.sort(key=lambda s: s["at_ns"])
    # the first grid instant at or past run_through_ns, plus one tick (module docstring, RUN-THROUGH)
    end = -(-int(run["run_through_ns"]) // tick) * tick + tick
    if steps and steps[-1]["at_ns"] >= end:
        raise StepError("spec %s: a step at %d ns comes at or after the run's end (%d ns)" % (spec_name, steps[-1]["at_ns"], end))
    steps.append({"at_ns": end, "call": "end"})
    script = {"format": vb.SCRIPT_FORMAT, "steps": steps}
    vb.parse_script(script)
    expected = sorted({(w["event"], w["reason"]) for w in windows}, key=_pair_key)
    return {"spec": spec_name, "what": spec["what"], "mode": mode, "run": spec["run"], "recording": dict(doc["recording"]),
            "events_file": doc.get("events_file"), "tick_ns": tick, "stop": stop, "run_through_ns": int(run["run_through_ns"]),
            "end_offset_ns": end, "file_end_ns": int(doc["runs"]["to_end"]["reference_ns"]), "windows": windows,
            "expected": [list(p) for p in expected], "script": script, "sequence": spec.get("sequence")}


# --- driving a run --------------------------------------------------------------------------------------------------

def end_bridge(ops: Any, deadline_ns: int) -> Dict[str, Any]:
    """Wait for the bridge to end itself (its script's end step); stop it only once deadline_ns has passed, which fails
    the run's bridge_ended_itself gate. Never earlier: not at the player's end."""
    seen = ops.wait_bridge(deadline_ns)
    if seen is not None:
        return {"ended_itself": True, "seen_ended_ns": seen, "deadline_ns": deadline_ns}
    return dict(ops.stop_bridge(), ended_itself=False, deadline_ns=deadline_ns)


def drive_live(plan: Mapping[str, Any], ops: Any) -> Dict[str, Any]:
    """can and broker, once the bridge (and for broker the stack and its can-provider) runs: the player, the recording's
    origin from the capture's first frame, the stop at origin + S - tick/2 by the mode's one realisation (to_end runs:
    none), the player's end, then the bridge left to tick on until it ends itself past run_through_ns."""
    if plan["mode"] not in ("can", "broker"):
        raise StepError("drive_live drives can and broker, not %s" % plan["mode"])
    out: Dict[str, Any] = {"origin_ns": None, "stop": None, "player_exit": None}
    ops.start_player()
    origin = ops.wait_origin(ORIGIN_TIMEOUT_S)
    if origin is None:
        out["error"] = "the player's first frame never reached the capture"
        out["bridge"] = end_bridge(ops, ops.now_ns())
        return out
    out["origin_ns"] = origin
    stop = plan["stop"]
    if stop is not None:
        due = origin + stop["call_offset_ns"]
        ops.sleep_until(due)
        # the record's how is the call's own (Ops), never the plan's: the stop gate compares the two
        did = ops.stop_player() if stop["how"] == "player" else ops.stop_provider()
        out["stop"] = dict(did, due_ns=due)
    out["player_exit"] = ops.wait_player(plan["file_end_ns"] / 1e9 + PLAYER_SLACK_S)
    out["player_end_ns"] = ops.now_ns()
    out["bridge"] = end_bridge(ops, origin + plan["end_offset_ns"] + int(END_SLACK_S * 1e9))
    return out


def drive_replay(plan: Mapping[str, Any], ops: Any) -> Dict[str, Any]:
    """replay, once the bridge runs: its grid anchor from its own record, then the bridge left to run its script (the stop
    and the end are its own steps) until it ends itself past run_through_ns."""
    if plan["mode"] != "replay":
        raise StepError("drive_replay drives replay, not %s" % plan["mode"])
    anchor = ops.wait_anchor(ORIGIN_TIMEOUT_S)
    if anchor is None:
        return {"origin_ns": None, "error": "the bridge logged no replay-anchored record", "bridge": end_bridge(ops, ops.now_ns())}
    return {"origin_ns": anchor, "bridge": end_bridge(ops, anchor + plan["end_offset_ns"] + int(END_SLACK_S * 1e9))}


class Ops:
    """What a run does to the outside world, apart from deciding when (drive_live, drive_replay): docker, the player, the
    capture, the clocks. Tests replace it."""

    def __init__(self, replay_dir: Path) -> None:
        self.replay_dir = replay_dir
        self.blog = replay_dir / "bridge" / "bridge.jsonl"

    def now_ns(self) -> int:
        raise NotImplementedError

    def sleep_until(self, t_ns: int) -> None:
        while True:
            left = t_ns - self.now_ns()
            if left <= 0:
                return
            time.sleep(min(left / 1e9, 0.05))

    def wait_bridge(self, deadline_ns: int) -> Optional[int]:
        """docker wait on the bridge, bounded by deadline_ns on this Ops' clock: the instant it was seen ended, or None."""
        left = (deadline_ns - self.now_ns()) / 1e9
        if left > 0:
            try:
                subprocess.run(["docker", "wait", st.BRIDGE_CONTAINER], capture_output=True, text=True, timeout=left)
            except subprocess.TimeoutExpired:
                pass
        running = st.docker("inspect", "-f", "{{.State.Running}}", st.BRIDGE_CONTAINER, check=False).stdout.strip() == "true"
        return None if running else self.now_ns()

    def stop_bridge(self) -> Dict[str, Any]:
        t = self.now_ns()
        p = st.docker("stop", "-t", "10", st.BRIDGE_CONTAINER, check=False, timeout=60)
        return {"stopped_ns": t, "rc": p.returncode, "what": "docker stop -t 10 (SIGTERM: the bridge's drain and summary)"}

    def close(self) -> None:
        pass


class ReplayOps(Ops):
    """replay: the clock is CLOCK_MONOTONIC, the replay grid's (a container shares the host's)."""

    def now_ns(self) -> int:
        return time.monotonic_ns()

    def wait_anchor(self, timeout_s: float) -> Optional[int]:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            found = [r for r in st.jsonl_records(self.blog) if r.get("event") == rs.REPLAY_ANCHORED]
            if found:
                return int(found[0]["anchor_ns"])
            time.sleep(0.1)
        return None


class LiveOps(Ops):
    """can and broker: the clock is CLOCK_REALTIME, the capture's and the live sources'; the player is python-can's,
    the capture stack.VcanCapture."""

    def __init__(self, ctx: Any, replay_dir: Path, capture: Any) -> None:
        super().__init__(replay_dir)
        self.ctx, self.capture = ctx, capture
        self.player: Optional[subprocess.Popen] = None
        self.provider_pid: Optional[int] = None
        self._log: Any = None

    def now_ns(self) -> int:
        return time.time_ns()

    def start_player(self) -> None:
        if self.ctx.bridge == "broker":
            # the can-provider's host PID, read now so the stop is one signal, not a round trip through the docker daemon
            # (module docstring, THE STOP)
            p = st.docker("inspect", "-f", "{{.State.Pid}}", st.NAMES[attr.CAN_PROVIDER])
            self.provider_pid = int(p.stdout.strip())
            if self.provider_pid <= 0:
                raise StepError("the can-provider is not running (PID %r)" % p.stdout.strip())
        self._log = open(self.replay_dir / "player.log", "w", encoding="utf-8")
        log = self.ctx.in_dir / st.log_of(self.ctx)          # the staged recording, by its name (THE RECORDING)
        self.player = subprocess.Popen([str(st.SIM_PY), "-m", "can.player", "-i", "socketcan", "-c", st.VCAN, str(log)],
                                       stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def wait_origin(self, timeout_s: float) -> Optional[int]:
        return self.capture.times_ns[0] if self.capture.first.wait(timeout_s) else None

    def stop_player(self) -> Dict[str, Any]:
        assert self.player is not None
        t0 = self.now_ns()
        self.player.terminate()
        return {"issued_ns": t0, "returned_ns": self.now_ns(), "ok": True, "how": "player", "what": "SIGTERM to the player"}

    def stop_provider(self) -> Dict[str, Any]:
        """SIGKILL to the can-provider's process (its container's init; the container exits 137), through sudo -n: the
        container runs as root. Its PID was read before the player started."""
        if self.provider_pid is None:
            raise StepError("the can-provider's PID was never read")
        t0 = self.now_ns()
        p = st.run(["sudo", "-n", "kill", "-KILL", str(self.provider_pid)], check=False, timeout=60)
        return {"issued_ns": t0, "returned_ns": self.now_ns(), "ok": p.returncode == 0, "rc": p.returncode, "pid": self.provider_pid,
                "how": "can-provider", "what": "sudo -n kill -KILL <the can-provider's PID>"}

    def wait_player(self, timeout_s: float) -> Optional[int]:
        assert self.player is not None
        try:
            return self.player.wait(timeout_s)
        except subprocess.TimeoutExpired:
            self.player.kill()
            self.player.wait(10)
            return None

    def close(self) -> None:
        if self.player is not None and self.player.poll() is None:
            self.player.kill()
            self.player.wait(10)
        if self._log is not None:
            self._log.close()
            self._log = None


# --- judging a run --------------------------------------------------------------------------------------------------

def garbled(line: str) -> bool:
    """A console line holding a marker (MARKERS) anywhere but as its own clean start: two markers, or one that is not
    the line's CLEAN_STARTS prefix. Line-start matching cannot see a marker spliced into another line."""
    n = sum(line.count(m) for m in MARKERS)
    return n > 1 or (n == 1 and not line.startswith(CLEAN_STARTS))


def console_view(console: str, guest: bool = False) -> Dict[str, Any]:
    """The monitor's console split at the bridge's last session end: what came during the run, and what came after (the
    monitor outliving the bridge: a MISS there is expected). Native mode: the last `client done:` line. Guest mode
    (module docstring, GUEST MODE): the last clean `client done:` with seen above 0, since the bridge's sessions always
    end so and a later seen=0 line is a probe's (seen_0 counts them). garbled: the lines holding a marker anywhere but as
    their own start (counted in both modes; guest mode's console gate fails on them)."""
    lines = console.splitlines()
    bad = [ln for ln in lines if garbled(ln)]
    if guest:
        ends = [i for i, ln in enumerate(lines) for m in [DONE_SEEN_RX.match(ln)] if m and int(m.group(1)) > 0 and not garbled(ln)]
    else:
        ends = [i for i, ln in enumerate(lines) if ln.startswith(DONE)]
    last_done = ends[-1] if ends else None
    during = lines[:last_done] if last_done is not None else lines
    after = lines[last_done + 1:] if last_done is not None else []

    def count(prefix: str, ls: Sequence[str]) -> int:
        return sum(1 for ln in ls if ln.startswith(prefix))
    counts = {"miss": count(MISS, during), "restored": sum(1 for ln in during if RESTORED_RX.match(ln)),
              "closed_silent": count(CLOSED_SILENT, during), "closed_untaken": count(CLOSED_UNTAKEN, during)}
    out: Dict[str, Any] = {"sessions": count(DONE, lines), "during": counts, "after_last_session": {"miss": count(MISS, after)},
                           "garbled_lines": len(bad), "garbled": [ln[:200] for ln in bad[:GARBLED_SHOWN]], "lines_during": during}
    if guest:
        out["seen_0"] = sum(1 for ln in lines for m in [DONE_SEEN_RX.match(ln)] if m and int(m.group(1)) == 0 and not garbled(ln))
    return out


# --- the guest's console (module docstring, GUEST MODE) ------------------------------------------------------------------

def strip_console(raw: bytes) -> str:
    """A serial console's bytes as text: every NUL and CR removed (QEMU's serial log holds both; a lone CR would split a
    line), anything that is not UTF-8 replaced. NUL and CR are single bytes in UTF-8, never inside another character."""
    return raw.replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", errors="replace")


def freshness(raw: bytes) -> Dict[str, Any]:
    """The freshness gate on the guest's console as it is now: no LIVENESS line, no `client closed:`, and no `client
    done:` with seen above 0, each anywhere in a line. The probes' seen=0 lines pass only when each probe closed within the
    guest's deadline (MONITOR_DEADLINE_MS): one held open past it leaves `client closed: no complete frame` before its
    seen=0, which this gate refuses, and the refusal says so when that is all the console holds. offset: where the run's
    judged console begins, the end of the last whole line read (a line still being written belongs to the run's part)."""
    text = strip_console(raw)
    seen = [int(s) for s in FRESH_DONE_RX.findall(text)]
    problems = []
    if FRESH_LIVENESS in text:
        problems.append("%d LIVENESS line(s)" % text.count(FRESH_LIVENESS))
    if FRESH_CLOSED in text:
        closed = "%d `client closed:` line(s)" % text.count(FRESH_CLOSED)
        if FRESH_LIVENESS not in text and not any(s > 0 for s in seen) and text.count(FRESH_SILENT) == text.count(FRESH_CLOSED):
            closed += (" for silence, with no claim judged: what a probe held open past the guest's %d ms deadline leaves; open "
                       "and close each probe in one step" % st.MONITOR_DEADLINE_MS)
        problems.append(closed)
    if any(s > 0 for s in seen):
        problems.append("a `client done:` with seen above 0 (%s)" % ", ".join(str(s) for s in seen if s > 0))
    return {"ok": not problems, "problems": problems, "bytes": len(raw), "offset": raw.rfind(b"\n") + 1, "client_done_seen": seen}


def console_end(judged: str, sessions: int = 1) -> Dict[str, Any]:
    """The run's last session end on the guest's console: the `client done:` lines after the gate's offset. ok when exactly
    as many have seen above 0 as the bridge had sessions (its connect records, at least one): the probes' are seen=0, and a
    pause run's first session ends, closed for silence, before its last. More is a problem named here: the bridge logs one
    connect per session and sends a claim in each, so a surplus is a client that was not the bridge judging claims on the
    guest's port during the run. seen is the last such line's."""
    seen = [int(m.group(1)) for ln in judged.splitlines() for m in [DONE_SEEN_RX.match(ln)] if m]
    ended = [s for s in seen if s > 0]
    want = max(1, sessions)
    problems = []
    if len(ended) > want:
        problems.append("%d `client done:` lines with seen above 0 after the offset for %d bridge session(s): a client that was "
                        "not the bridge judged claims on :%d during the run" % (len(ended), want, st.MONITOR_PORT))
    return {"ok": len(ended) == want, "seen": ended[-1] if ended else None, "sessions": want, "ended": len(ended),
            "client_done_seen": seen, "problems": problems}


def wait_console_end(path: Path, offset: int, timeout_s: float, sessions: int = 1) -> bool:
    """Wait, bounded, until the guest's console after offset holds as many session ends (console_end) as the bridge had
    sessions; whether it came. A surplus ends the wait too: it is console_end's to name, and waiting cannot remove it."""
    end = time.monotonic() + timeout_s
    while True:
        try:
            got = console_end(strip_console(path.read_bytes()[offset:]), sessions)
            if got["ended"] >= got["sessions"]:
                return True
        except OSError:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


def read_guest_console(path: Path) -> bytes:
    """The guest's console file's bytes; a file that cannot be read is a StepError naming it (step3's main reports it)."""
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise StepError("the guest console %s cannot be read: %s" % (path, exc)) from None


def c12b_count(whole: str, guest: bool) -> Dict[str, Any]:
    """result.json's C12b count: the `vss rules:` lines that parse. In guest mode GUEST_RULES_LINES are expected (gap 4n)
    and another count is noted, not failed, unless 0, when C12b fails for want of a line: the instances share one
    console, and interleaving drops a line from the parse without making it wrong (C12b, which wants at least one parsed
    line and every parsed line to pass, is the gate)."""
    n = len(attr.vss_rules_lines(whole))
    out: Dict[str, Any] = {"c12b_lines": n}
    if guest:
        out["c12b_expected"] = GUEST_RULES_LINES
        if n == 0:
            out["c12b_note"] = ("0 of %d expected `vss rules:` lines parse: C12b fails for want of one, which says as much about "
                                "the console (the instances' lines can interleave on it) as about the guest" % GUEST_RULES_LINES)
        elif n != GUEST_RULES_LINES:
            out["c12b_note"] = ("%d of %d expected `vss rules:` lines parse: noted, not failed (the instances' lines can "
                                "interleave on the console)" % (n, GUEST_RULES_LINES))
    return out


def run_console(ctx: Any, replay_dir: Path, gate: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A run's console, read through this one function. Native mode: the native monitor's monitor.log as before, judged
    whole. Guest mode: the guest's console file read once, NUL and CR removed, the whole copied to the run directory as
    guest-console.log (C12b's operand) and only what follows the freshness gate's offset judged. Returns the whole text, the
    judged text, the path C12b reads, and (guest mode) the record for result.json: the raw file's path, bytes and sha256."""
    if st.monitor_mode(ctx) != "guest":
        path = replay_dir / "monitor.log"
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        return {"whole": text, "judged": text, "path": path, "record": None}
    if gate is None:
        raise StepError("guest mode judges the console from its freshness gate's offset, and there is none")
    src = Path(ctx.guest["console"])
    raw = read_guest_console(src)
    whole = strip_console(raw)
    copy = replay_dir / GUEST_CONSOLE
    copy.write_bytes(whole.encode("utf-8"))
    record = {"raw": {"path": str(src), "bytes": len(raw), "sha256": sha256_bytes(raw)}, "copy": GUEST_CONSOLE,
              "copy_sha256": st.sha256_file(copy), "removed": {"nul": raw.count(b"\0"), "cr": raw.count(b"\r")},
              "judged_from_offset": int(gate["offset"]),
              "note": "the guest's console as read once after the run (the guest runs on, so the file may grow after); judged "
                      "after the offset recorded at the run's freshness gate"}
    return {"whole": whole, "judged": strip_console(raw[int(gate["offset"]):]), "path": copy, "record": record}


def pause_sequence(kind: str, replies: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]],
                   during: Sequence[str], age_max_ms: int) -> Dict[str, Any]:
    """Spec 14.4's pause sequences (module docstring, the console gate), from the console during the run, the bridge's log
    and its replies. kind tick: the first frame after the tick's resume is ACCEPTed; both: it is 22 with its age above
    AGE_MAX, and frames are ACCEPTed again once the intake has resumed."""
    miss = [i for i, ln in enumerate(during) if ln.startswith(MISS)]
    closed = [i for i, ln in enumerate(during) if ln.startswith(CLOSED_SILENT)]
    restored = [(i, int(m.group(1))) for i, ln in enumerate(during) for m in [RESTORED_RX.match(ln)] if m]
    pauses = [r for r in records if r.get("event") == "pause" and r.get("what") == "tick"]
    resumes = [r for r in records if r.get("event") == "resume" and r.get("what") == "tick"]
    t_pause = pauses[0]["t_mono"] if len(pauses) == 1 else None
    t_resume = resumes[0]["t_mono"] if len(resumes) == 1 else None
    after = sorted((r for r in replies if t_resume is not None and r["t_mono"] > t_resume), key=lambda r: r["seq"])
    first = after[0] if after else None
    # the monitor's close as the bridge saw it, after the tick's pause: never the bridge's own close at its stop, which
    # every run that ends connected logs after the pause too (so "any close after the pause" held in every run)
    closes = [r for r in records if r.get("event") == "closed" and t_pause is not None and r["t_mono"] > t_pause
              and r.get("why") in PEER_CLOSE_WHY]
    connects = [r for r in records if r.get("event") == "connect"]
    want = (rules.V_ACCEPT, rules.RSN_OK) if kind == "tick" else (rules.V_REJECT, rules.RSN_VSS_STALE)
    checks = {
        "one_tick_pause_and_resume": t_pause is not None and t_resume is not None and t_pause < t_resume,
        "one_miss": len(miss) == 1,
        "one_close_for_silence": len(closed) == 1,
        "miss_then_close": bool(miss and closed and miss[0] < closed[0]),
        "bridge_saw_the_close": len(closes) == 1,
        "one_reconnect": len(connects) == 2,
        "first_after_resume": first is not None and (first["verdict"], first["reason"]) == want
                              and (kind == "tick" or int(first["age_ms"]) > age_max_ms),
        "one_restored_after_the_close": len(restored) == 1 and bool(closed) and restored[0][0] > closed[0],
        "restored_names_it": len(restored) == 1 and first is not None and restored[0][1] == first["seq"],
    }
    if kind == "both":
        ri = [r for r in records if r.get("event") == "resume" and r.get("what") == "intake"]
        t_ri = ri[0]["t_mono"] if len(ri) == 1 else None
        checks["intake_resumed_after_the_tick"] = t_ri is not None and t_resume is not None and t_ri > t_resume
        checks["accepted_again"] = t_ri is not None and any(r["t_mono"] > t_ri and r["verdict"] == rules.V_ACCEPT for r in replies)
    shown = None if first is None else {k: first.get(k) for k in ("seq", "verdict", "reason", "age_ms")}
    return {"ok": all(checks.values()), "checks": checks, "first_after_resume": shown, "restored": restored}


def stop_evidence(plan: Mapping[str, Any], drive: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
                  origins: Mapping[str, Optional[int]]) -> Dict[str, Any]:
    """Whether the planned stop was made, at its instant, by its one realisation; and that a run with no stop made none."""
    stop, tick = plan["stop"], plan["tick_ns"]
    pause_steps = [r for r in records if r.get("event") == "script-step" and r.get("call") == "pause_intake"]
    planned_intake = [s for s in plan["script"]["steps"] if s["call"] == "pause_intake"]
    live: Optional[Mapping[str, Any]] = drive.get("stop")
    if stop is None:
        extra = live is not None or len(pause_steps) != len(planned_intake)
        return {"ok": not extra, "planned": None, "made": live}
    s = stop["at_offset_ns"]
    if stop["how"] == "intake":
        step = [r for r in pause_steps if r.get("at_ns") == stop["call_offset_ns"]]
        origin = origins.get("recording")
        done = step[0]["done_ns"] - origin if len(step) == 1 and origin is not None else None
        ok = live is None and done is not None and s - tick < done < s
        return {"ok": ok, "planned": dict(stop), "made": step[0] if step else None, "done_offset_ns": done,
                "between": "the deliveries at S - tick and S on the replay grid"}
    t0 = drive.get("origin_ns")
    off = live["issued_ns"] - t0 if live is not None and t0 is not None else None
    ok = bool(live is not None and live.get("ok") and live.get("how") == stop["how"] and off is not None and s - tick <= off < s
              and not pause_steps)
    return {"ok": ok, "planned": dict(stop), "made": live, "issued_offset_ns": off, "between": "the tick before S, on CLOCK_REALTIME"}


def judge(plan: Mapping[str, Any], replies: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]],
          summary: Optional[Mapping[str, Any]], console: str, origins: Mapping[str, Optional[int]], drive: Mapping[str, Any],
          age_max_ms: int, end: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A run's own gates (module docstring, PER RUN) from its files: the reason set on the plan's windows (each moved by
    its origin), run-through, the stop, the script, the accounting and the console. end (guest mode): console_end of the
    judged console, its gate, and its seen recorded beside the bridge's reply count (not gated); in guest mode the console
    is split as console_view(guest=True) splits it, and a garbled line fails the console gate, named in console.problems."""
    guest = end is not None
    problems: List[str] = []
    windows = []
    for w in plan["windows"]:
        o = origins.get(w["origin"])
        if o is None:
            problems.append("no %s origin for window %s" % (w["origin"], w["event"]))
            continue
        windows.append({"event": w["event"], "t0_ns": o + w["t0_ns"], "t1_ns": o + w["t1_ns"]})
    expected: Set[Pair] = {(p[0], int(p[1])) for p in plan["expected"]}
    got = rs.reason_set(replies, windows) if not problems else set()
    cmp = rs.compare(expected, got)
    rec_origin = origins.get("recording")
    offsets = [int(r["src_now_ns"]) - rec_origin for r in replies] if rec_origin is not None else []
    last = max(offsets) if offsets else None
    stale = sorted(((int(r["src_now_ns"]) - rec_origin, r) for r in replies if r["verdict"] and r["reason"] == rules.RSN_VSS_STALE),
                   key=lambda x: (x[0], x[1]["seq"])) if rec_origin is not None else []
    view = console_view(console, guest)
    console_problems: List[str] = []
    if guest and view["garbled_lines"]:
        # another writer's bytes inside a marker line: the line-start counts cannot be trusted (module docstring, GUEST MODE)
        console_problems.append("%d garbled console line(s): a LIVENESS, `client closed:` or `client done:` marker inside another "
                                "line, where the console gate cannot count it; a second writer on the console" % view["garbled_lines"])
    gates: Dict[str, bool] = {
        "reason_set": not problems and cmp["ok"],
        "ticked_through": last is not None and last >= plan["run_through_ns"],
        "stop": stop_evidence(plan, drive, records, origins)["ok"],
    }
    # the bridge's drop records by their why: a diagnostic only (the accounting gate wants none, whatever the why)
    drops_by_why: Dict[str, int] = {}
    for r in records:
        if r.get("event") == "dropped":
            drops_by_why[str(r.get("why"))] = drops_by_why.get(str(r.get("why")), 0) + 1
    if summary is None:
        gates.update(identity=False, no_fatal=False, no_uninjected_21=False, accounting=False, script=False)
    else:
        n = summary["counters"]
        sc = summary.get("script") or {}
        gates["identity"] = bool(summary["identity"]["holds"] and summary["ticks_identity"]["holds"] and summary["seq_partition"]["holds"])
        gates["no_fatal"] = summary["fatal"] is None
        gates["no_uninjected_21"] = summary["r21_uninjected"] == 0
        # every run, a pause run included (module docstring, PER RUN)
        gates["accounting"] = n["drop"] == 0 and n["lost_on_reconnect"] == 0
        gates["script"] = (sc.get("error") is None and sc.get("done") == len(plan["script"]["steps"]) == sc.get("steps")
                           and sc.get("ended_run") is True)
    seq = None
    if plan["sequence"] is None:
        gates["console"] = not any(view["during"].values()) and not console_problems
    else:
        seq = pause_sequence(plan["sequence"], replies, records, view["lines_during"], age_max_ms)
        gates["console"] = seq["ok"] and not console_problems
    extra: Dict[str, Any] = {}
    if end is not None:
        gates["console_end"] = bool(end["ok"])
        extra["console_end"] = dict(end, bridge_replied=((summary or {}).get("counters") or {}).get("replied"),
                                    note="seen is the guest's count of the bridge's last session, the bridge's reply count its own "
                                         "over the run: recorded side by side, not compared")
    by: Dict[str, int] = {}
    for r in replies:
        k = "ACCEPT" if not r["verdict"] else "REJECT %d" % r["reason"]
        by[k] = by.get(k, 0) + 1
    return {**extra, "gates": gates, "ok": all(gates.values()), "problems": problems,
            "reason_set": {"expected": [list(p) for p in sorted(expected, key=_pair_key)], "got": [list(p) for p in sorted(got, key=_pair_key)],
                           "missing": [list(p) for p in cmp["missing"]], "extra": [list(p) for p in cmp["extra"]]},
            "origins": dict(origins), "last_reply_offset_ns": last, "replies_by_verdict": by, "drops_by_why": drops_by_why,
            "first_22": None if not stale else {"offset_ns": stale[0][0], "age_ms": stale[0][1]["age_ms"], "seq": stale[0][1]["seq"]},
            "stop": stop_evidence(plan, drive, records, origins),
            "console": dict({k: v for k, v in view.items() if k != "lines_during"}, problems=console_problems), "pause_sequence": seq,
            "counters": {k: (summary or {}).get("counters", {}).get(k) for k in ("ticks", "packed", "replied", "accepted", "rejected", "drop",
                                                                                   "lost_on_reconnect", "connects", "reconnects", "injected",
                                                                                   "r21", "r21_injected", "age_over_max")},
            "identity": (summary or {}).get("identity"), "script": (summary or {}).get("script")}


def bus_check(plan: Mapping[str, Any], frames: Sequence[Tuple[int, bytes]], log: Sequence[Tuple[int, int, bytes]]) -> Dict[str, Any]:
    """Every frame on vcan0 the log's, in order: the whole log, or for a player stopped at S a prefix of it that ends
    inside the tick before S (every frame before S - tick sent, none at or after S)."""
    want = [(cid, data) for _t, cid, data in log]
    n = len(frames)
    prefix = list(frames) == want[:n]
    stop = plan["stop"]
    if stop is None or stop["how"] != "player":
        return {"ok": list(frames) == want, "frames_on_bus": n, "frames_in_log": len(want), "identical": list(frames) == want}
    t0 = log[0][0]
    off = [(t - t0) * 1000 for t, _c, _d in log]
    s, tick = stop["at_offset_ns"], plan["tick_ns"]
    ends_in = n > 0 and off[n - 1] < s and (n == len(off) or off[n] >= s - tick)
    return {"ok": prefix and ends_in, "frames_on_bus": n, "frames_in_log": len(want), "prefix_of_log": prefix,
            "last_sent_offset_ns": off[n - 1] if n else None, "first_unsent_offset_ns": off[n] if n < len(off) else None}


# --- the comparison -------------------------------------------------------------------------------------------------

def compare_results(results: Sequence[Mapping[str, Any]], frames_of: Callable[[Mapping[str, Any]], List[bytes]],
                    modes: Sequence[str] = MODES) -> Dict[str, Any]:
    """Plan step 3's comparison (module docstring, COMPARE): grouped by recording and spec, every run judged and passing
    its own gates, every mode of `modes` present and every set equal in each group (reasonsets.compare_modes), and frame by
    frame only between replay runs of one group. A result with no reason set (a run that never reached its judge) fails its
    group by name; it is never compared. A run of one of the bridge's modes that `modes` does not list is left out and
    named; a run of a mode the bridge does not have stays in, and compare_modes refuses it."""
    modes = tuple(dict.fromkeys(modes))
    left_out = [{"run": r["run"], "mode": r["mode"], "dir": r.get("dir")} for r in results if r["mode"] in MODES and r["mode"] not in modes]
    groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for r in results:
        if r["mode"] in MODES and r["mode"] not in modes:
            continue
        groups.setdefault((r["recording"]["sha256"], r["spec"]), []).append(r)
    out = []
    for (sha, spec), runs in sorted(groups.items()):
        judged = [r for r in runs if isinstance((r.get("reason_set") or {}).get("got"), list)]
        was_judged = {id(r) for r in judged}
        problems = ["%s (%s): no reason set, the run was never judged" % (r["run"], r.get("dir")) for r in runs if id(r) not in was_judged]
        problems += ["%s (%s): it failed its own gates (ok %r)" % (r["run"], r.get("dir"), r.get("ok")) for r in judged if r.get("ok") is not True]
        sets = [(r["mode"], {(p[0], int(p[1])) for p in r["reason_set"]["got"]}) for r in judged]
        by_mode = rs.compare_modes(sets, modes)
        replays = [r for r in judged if r["mode"] == "replay"]
        frames = []
        for other in replays[1:]:
            c = rs.compare_frames({"mode": "replay", "frames": frames_of(replays[0])}, {"mode": "replay", "frames": frames_of(other)})
            frames.append(dict(c, runs=[replays[0]["run"], other["run"]], differ=c["differ"][:20], lengths=list(c["lengths"])))
        out.append({"recording_sha256": sha, "spec": spec,
                    "runs": [{"run": r["run"], "mode": r["mode"], "dir": r.get("dir"), "ok": r.get("ok"), "judged": id(r) in was_judged}
                             for r in runs],
                    "problems": problems, "modes": by_mode, "frames": frames,
                    "ok": not problems and by_mode["ok"] and all(f["ok"] for f in frames)})
    return {"ok": bool(out) and all(g["ok"] for g in out), "modes": list(modes), "left_out": left_out, "groups": out}


def replay_frames(result: Mapping[str, Any]) -> List[bytes]:
    """A run's frames from its reply log (reasonsets.reply_frames)."""
    path = Path(result["dir"]) / "bridge" / "replies.jsonl"
    return rs.reply_frames([r for r in st.jsonl_records(path) if r.get("event") == "reply"])


def find_results(dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    """Every result.json of a step-3 run under the given directories (a run directory or one run's)."""
    out = []
    for d in dirs:
        for p in sorted([Path(d) / "result.json"] + list(Path(d).glob("*/result.json"))):
            if p.is_file():
                r = json.loads(p.read_text(encoding="utf-8"))
                if r.get("step3") == 1:
                    out.append(dict(r, dir=str(p.parent)))
    return out


# --- a run on the PC ------------------------------------------------------------------------------------------------

def up_bridge_only(ctx: Any, feed: str, replay_dir: Path, label: str, header: Dict[str, Any]) -> Dict[str, Any]:
    """can and replay: no databroker, no providers; the native monitor (guest mode: none, the guest's runs already) and the
    bridge, with the listener snapshots."""
    st.remove_stack()
    info: Dict[str, Any] = {"feed": feed, "listeners_before": st.host_listeners()}
    if feed == "vcan":
        info["vcan"] = st.ensure_vcan()
    if st.monitor_mode(ctx) == "guest":
        info["monitor"] = st.guest_info(ctx)
    else:
        st.start_monitor(ctx, replay_dir, info)
    st.start_bridge(ctx, feed, replay_dir, label, header)
    st.listeners_now(info, feed, "", st.allowances(ctx))
    return info


def stop_stack() -> None:
    """broker: the stack's containers once the bridge has ended (the recorder and the mock ignore SIGTERM)."""
    for comp in (attr.CAN_PROVIDER, attr.APP, st.WITNESS, attr.RECORDER, attr.MOCK_PROVIDER, attr.DATABROKER):
        st.docker("stop", "-t", "3", st.NAMES[comp], check=False, timeout=60)


def run_one(ctx: Any, plan: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """One run (module docstring, A RUN): start, drive, stop, then judge from the files it left. In guest mode (GUEST MODE)
    the console must pass the freshness gate before anything starts, and is judged after the gate's offset."""
    mode = plan["mode"]
    if mode != ctx.bridge:
        raise StepError("a %s plan in a %s context" % (mode, ctx.bridge))
    guest = st.monitor_mode(ctx) == "guest"
    replay_dir = ctx.run_dir / run_id
    if replay_dir.exists():
        raise StepError("%s exists: a run directory is never reused" % replay_dir)
    replay_dir.mkdir(parents=True)
    st.write_json(replay_dir / "plan.json", plan)
    st.write_json(replay_dir / st.BRIDGE_SCRIPT, plan["script"])
    feed, label = FEED[mode], "%s/%s" % (ctx.run_dir.name, run_id)
    header = ctx.run_header(run_id, feed)
    log = st.log_of(ctx)              # the staged recording's name (stack.py, RECORDING KINDS AND RUN TYPES)
    checks: List[attr.Check] = [attr.check_recording(header, ctx.staged[log], ctx.scenario["dbc_sha256"]), ctx.check_header(header)]
    rows = attr.run_rows(ctx.rows, ctx.image_ids()) if mode == "broker" else []

    def write_table() -> None:
        st.write_json(replay_dir / "attribution.json", {"header": header, "rows": rows, "scenario_checks": ctx.manifest["scenario_checks"],
                                                        "checks": [list(c) for c in checks]})
    write_table()
    result: Dict[str, Any] = {"step3": 1, "run": run_id, "spec": plan["spec"], "mode": mode, "events_run": plan["run"],
                              "recording": {"sha256": ctx.staged[log], "dir": str(st.RECORDING_DIR),
                                            "events_file": plan["events_file"]},
                              "image": ctx.components[attr.BRIDGE]["image_id"], "monitor": st.monitor_component(ctx)["sha256"]}
    if not all(c[1] for c in checks):
        raise StepError("refused before anything started: %s" % [c for c in checks if not c[1]])
    gate: Optional[Dict[str, Any]] = None
    if guest:
        gate = freshness(read_guest_console(ctx.guest["console"]))
        result["console_gate"] = gate
        if not gate["ok"]:
            raise StepError("refused before anything started: the guest console %s is not fresh: %s" % (
                ctx.guest["console"], "; ".join(gate["problems"])))
    info: Dict[str, Any] = {}
    drive: Dict[str, Any] = {}
    capture: Any = None
    ops: Optional[Ops] = None
    st.new_hook_records(ctx)          # stack.py, PLACEMENT: this run's containers only
    try:
        if mode == "broker":
            info = st.up(ctx, feed, replay_dir, label, header)
            st.start(ctx, attr.CAN_PROVIDER, feed, replay_dir, label)
            checks.append(attr.check_images(rows, st.running_images()))
            write_table()
            if not checks[-1][1]:
                raise StepError("C8 failed: %s" % checks[-1][2])
            st.wait_log(st.NAMES[attr.CAN_PROVIDER], r"Starting to receive CAN messages|Using DBC reader", st.START_TIMEOUT_S)
        else:
            info = up_bridge_only(ctx, feed, replay_dir, label, header)
        time.sleep(st.VCAN_READY_S)
        st.listeners_now(info, feed, "_feed", st.allowances(ctx))
        if mode == "replay":
            ops = ReplayOps(replay_dir)
            drive = drive_replay(plan, ops)
        else:
            capture = st.VcanCapture()
            ops = LiveOps(ctx, replay_dir, capture)
            drive = drive_live(plan, ops)
            time.sleep(1.0)
            frames = capture.close()
            capture = None
            result["bus"] = bus_check(plan, frames, bs.read_candump(ctx.in_dir / log))
        st.listeners_now(info, feed, "_end", st.allowances(ctx))
        if mode == "broker":
            stop_stack()
    finally:
        if capture is not None:
            capture.close()
        if ops is not None:
            ops.close()
        if ctx.monitor is not None:
            result["monitor_exit"] = ctx.monitor.stop()
            ctx.monitor = None
        result["containers"] = st.collect(replay_dir)
        st.remove_stack()
        st.write_json(replay_dir / "listeners.json", info)
        result["drive"] = drive
        hooks = st.hook_records(ctx)
        if hooks is not None:
            result[st.AFTER_START_KEY] = hooks          # a failed hook's record too: the run stops after this write
        st.write_json(replay_dir / "result.json", result)
    bdir = replay_dir / "bridge"
    replies = [r for r in st.jsonl_records(bdir / "replies.jsonl") if r.get("event") == "reply"]
    records = st.jsonl_records(bdir / "bridge.jsonl")
    try:
        summary: Optional[Dict[str, Any]] = json.loads((bdir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = None
    sessions = sum(1 for r in records if r.get("event") == "connect")
    if gate is not None:
        wait_console_end(Path(ctx.guest["console"]), int(gate["offset"]), CONSOLE_END_S, sessions)
    console = run_console(ctx, replay_dir, gate)
    if console["record"] is not None:
        result["console_file"] = console["record"]
    origins: Dict[str, Optional[int]] = {"recording": drive.get("origin_ns"), "script": None}
    so = [r for r in records if r.get("event") == "script-origin"]
    if len(so) == 1:
        origins["script"] = int(so[0]["origin_ns"])
    if mode == "replay":
        try:
            origins["recording"] = rs.replay_anchor(records)
        except ValueError:
            origins["recording"] = None
    result.update(judge(plan, replies, records, summary, console["judged"], origins, drive, int(ctx.contract.AGE_MAX_MS),
                        end=console_end(console["judged"], sessions) if guest else None))
    close = st.record_close(header, replay_dir, console["path"])
    checks.append(close)
    write_table()
    result.update(c12b_count(console["whole"], guest))
    gates = result["gates"]
    gates["start_checks"] = all(c[1] for c in checks[:2]) and (mode != "broker" or checks[2][1])
    gates["c12b"] = bool(close[1])
    gates["listeners"] = all(info.get(k, {}).get("ok", False) for k in ("listeners", "listeners_feed", "listeners_end"))
    gates["bridge_ended_itself"] = bool((drive.get("bridge") or {}).get("ended_itself"))
    gates["bridge_exit"] = result["containers"].get(attr.BRIDGE) == "exited 0"
    if mode != "replay":
        gates["bus"] = bool(result.get("bus", {}).get("ok"))
    result["ok"] = all(gates.values())
    st.write_json(replay_dir / "result.json", result)
    return result


def prepared_context(mode: str, name: str, images: str = "build", guest: Optional[Mapping[str, Any]] = None) -> Any:
    """A run directory and its Context in one bridge mode: broker pulls and builds the stack's images (no-ops when present);
    can and replay take only the bridge's parts (its image's labels checked, the native monitor built). images: the stack's
    images mode (stack.py, IMAGES): `build`, or `loaded` on an aarch64 host, where broker's pull and build become
    inspections of the images pulled and loaded before the run and the bridge must be its arm64 pin. guest (GUEST MODE):
    {host, console, image}, the Context's guest mode, where nothing is built for the monitor."""
    kw: Dict[str, Any] = {}
    if guest is not None:
        kw = {"monitor": "guest", "guest_host": guest["host"], "guest_console": guest["console"], "guest_image": guest["image"]}
    ctx = st.Context(st.new_run_dir(name), None, mode, **kw)
    ctx.prepare(pull=mode == "broker", build=mode == "broker", bridge_parts=True, images=images)
    return ctx


def guest_args(a: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """run's guest options, checked before anything is read or written (module docstring, GUEST MODE): None in native mode,
    which takes none of them; in guest mode one spec run once, a guest host that is IPv4 and not loopback, a console and an
    image that are files, and a console that passes the freshness gate."""
    given = ["--" + k.replace("_", "-") for k in ("guest_host", "guest_console", "guest_image") if getattr(a, k) is not None]
    if a.monitor != "guest":
        if given:
            raise StepError("%s: guest mode's options (--monitor guest)" % ", ".join(given))
        return None
    host = GUEST_HOST if a.guest_host is None else a.guest_host
    problems = []
    if a.repeat > 1:
        problems.append("--repeat %d: one run per call (one fresh boot per run)" % a.repeat)
    if len(a.spec) != 1:
        problems.append("%d specs: one spec per call (one fresh boot per run)" % len(a.spec))
    problems += st.guest_problems(host, a.guest_console, a.guest_image)
    if problems:
        raise StepError("guest mode refused: %s" % "; ".join(problems))
    console = Path(a.guest_console)
    gate = freshness(read_guest_console(console))
    if not gate["ok"]:
        raise StepError("guest mode refused: the guest console %s is not fresh: %s" % (console, "; ".join(gate["problems"])))
    return {"host": host, "console": console, "image": Path(a.guest_image)}


def recording_doc(contract: Any) -> Dict[str, Any]:
    rec = st.recording_identity(st.RECORDING_DIR)
    return events_doc(st.RECORDING_DIR, rec["sha256"], rec["manifest_line"], contract)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("run", "plan"):
        p = sub.add_parser(cmd)
        p.add_argument("--mode", choices=MODES, required=True)
        p.add_argument("--spec", nargs="+", required=True)
        if cmd == "run":
            p.add_argument("--repeat", type=int, default=1)
            p.add_argument("--name", default=None)
            p.add_argument("--images", choices=st.IMAGE_MODES, default="build",
                           help="the stack's images mode: build (default, the PC) or loaded (an aarch64 host; stack.py, IMAGES)")
            p.add_argument("--monitor", choices=MONITORS, default="native",
                           help="native (default): the native vss monitor built and started here; guest: the QNX guest's (GUEST MODE)")
            p.add_argument("--guest-host", default=None, help="guest mode: the guest's IPv4 address (default %s, on br0)" % GUEST_HOST)
            p.add_argument("--guest-console", default=None, help="guest mode: the guest's serial console file (read, never written)")
            p.add_argument("--guest-image", default=None, help="guest mode: the image the guest booted (its name and sha256 recorded)")
    c = sub.add_parser("compare")
    c.add_argument("--name", default="step3-compare")
    c.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES),
                   help="the modes compared (default all three); a run of another of the bridge's modes is left out and named. "
                        "Give the directories first, or end the modes with --")
    c.add_argument("dirs", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        st.refuse_bridge_in_twin_control(a.mode)          # TWIN CONTROL: every run starts a bridge; before anything is read
    if a.cmd == "compare":
        results = find_results(Path(d).expanduser() for d in a.dirs)
        res = compare_results(results, replay_frames, a.modes)
        out = st.new_run_dir(a.name)
        out.mkdir(parents=True)
        st.write_json(out / "compare.json", dict(res, inputs=[r["dir"] for r in results], utc=st.utc_now()))
        print(json.dumps({"ok": res["ok"], "modes": res["modes"], "left_out": res["left_out"],
                          "groups": [{k: g[k] for k in ("spec", "ok", "problems", "modes")} for g in res["groups"]]}, indent=1))
        return 0 if res["ok"] else 1
    guest = guest_args(a) if a.cmd == "run" else None
    specs = load_specs()
    unknown = [s for s in a.spec if s not in specs]
    if unknown:
        raise StepError("no spec %s in %s (has %s)" % (unknown, SPECS_FILE.name, sorted(specs)))
    contract = st.load_contract()
    doc = recording_doc(contract)
    plans = [plan_run(doc, s, specs[s], a.mode) for s in a.spec]
    if a.cmd == "plan":
        print(json.dumps(plans, indent=1, sort_keys=True))
        return 0
    if a.repeat < 1:
        raise StepError("--repeat %d: at least one" % a.repeat)
    ctx = prepared_context(a.mode, a.name or "step3-%s" % a.mode, a.images, guest)
    print("prepared %s" % ctx.run_dir, flush=True)
    results = []
    for plan in plans:
        for k in range(1, a.repeat + 1):
            r = run_one(ctx, plan, "%s-%s-%d" % (plan["spec"], a.mode, k))
            results.append(r)
            print("%s: ok %s gates %s set %s" % (r["run"], r["ok"], json.dumps(r["gates"], sort_keys=True), r["reason_set"]["got"]), flush=True)
    st.write_json(ctx.run_dir / "step3.json", {"utc_end": st.utc_now(), "mode": a.mode, "runs": [{k: r[k] for k in ("run", "spec", "ok", "gates")}
                                                                                                 for r in results]})
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (StepError, st.StackError, vb.BridgeError, inj.InjectError) as exc:
        print("step3.py: %s" % exc, file=sys.stderr)
        sys.exit(1)
