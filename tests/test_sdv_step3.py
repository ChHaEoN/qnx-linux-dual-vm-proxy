"""Phase 2 step 3 on the PC (sdv/stack/step3.py; the bridge's script, sdv/bridge; sdv Phase 2, WP10).

What is tested, and how. Pure tests, on synthetic events documents built with sdv/inject/inject.py's own functions and
the generated contract (no Docker, no bus, no databroker):

- The stop's realisation per mode reads its offset from the events file: for two different stop offsets, broker
  plans the can-provider's stop, can the player's, replay a Bridge.pause_intake script step, each at the file's
  at_offset_ns less half a tick; replay's is the script's only pause, the live modes' scripts hold none; a to_end run
  plans none; an events file whose realisation is not the mode's one, is at another offset than the run's stop, or
  is undone, is refused.
- Run-through is honoured: every plan's script ends one tick past the doc's run_through_ns when it is on the tick grid
  (off it, below: F-THROUGH), and the drivers (drive_live, drive_replay; a fake Ops on a fake clock) give the bridge
  until then plus the slack: a bridge that ends itself is never stopped, not at the player's end either; one that
  outlives the deadline is stopped and the run marked so. The live driver makes the stop by the mode's realisation at
  origin + S - tick/2 (to_end: none).
- The judge: the real injected recording (~/sdv-recordings/20261002-sigsim-1b-inj4, read only; skipped without it),
  replayed offline as WP9's test does (the bridge's own ReplaySource, Intake and ClaimCore on a fake clock), gives
  the plan's set and ticks through; without its stop it lacks exactly (stop, 22); cut at the player's end (the
  bridge stopped there) it neither ticks through nor holds its 22 windows.
- The comparison: three modes with one set pass; one differing pair fails and names its mode; a missing mode fails, and
  so does a run of a mode the comparison does not know;
  a run that failed its own gates fails its group, and a result an aborted run left (no reason set) fails its group by
  name without being compared; frames are compared only between two replay runs, and one differing frame fails.
- The pause sequences (spec 14.4) and the console split at the bridge's last session.
- Each exit-bearing gate of the judge made to fail on its own: the accounting (one drop, `paused` included, or one
  loss, in a run with or without a pause); the live stop (issued at or after S, before S - tick, by the other
  realisation, failed, or with the bridge pausing too); the replay stop (its step done outside (S - tick, S), or not
  the planned step, or with a live stop); a to_end run making any stop; the bus (a frame missing, reordered, doubled
  or altered; a stopped player's prefix ending before the tick before S, reaching S, or with a gap); the console of a
  run without a pause (a MISS, a close or a RESTORED before the bridge's last session ends); pause-both (the intake
  resumed before the tick; a first 22 whose age is AGE_MAX, not above it).
- Whole runs as the judge reads them, on files laid out as final3's are (the bridge's own `closed` at its stop
  included): the spec file's pause-tick and pause-both plans pass every gate on files holding spec 14.4's sequence,
  and each part of the sequence broken on its own (the tick's resume before its pause, or no pause record; no MISS
  or two; no close for silence or two; the bridge seeing no peer close, or two; one connect or three; RESTORED
  before the close, missing, or naming another frame; the first frame after the resume wrong; for both, the intake
  resumed first, or no ACCEPT once it runs) fails exactly the checks it breaks and the console gate, nothing else
  but a reason set the break itself changes. The judge's peer-close whys are the bridge's own strings. Each summary
  field broken on its own (each identity, the script's done, steps, end and error, a fatal, an uninjected 21, a drop,
  a loss) fails only its gate, and a run with no summary fails every gate read from one.
- The run specs (step3-runs.json) all plan in every mode, with the pause test's 1.5 s (kind4-spec 15) and
  pause-both's order (both paused at one instant, the tick resumed before the intake) pinned; a malformed spec is
  refused.
- The bridge's script (vss_claim_bridge.py, SCRIPT): parse refusals, the stamp refusal, a script thread timed from the
  first held update and ending the run, and, end to end in process, a replay run (bridge_sources.py's command line
  with a candump file that runs on well past the run's end and a Python peer answering with the reference judge,
  rules.reply) whose plan-made script realises the stop by the intake pause between the two deliveries and ends one
  tick past run_through_ns, its last reply at run_through_ns: the judge passes every gate, the reply log's frames are
  the frames the peer received, and the same run without its stop step lacks (stop, 22).
- stack.start runs the bridge in can and replay modes with the staged inputs and the script mounted read-only.
- `run --images loaded` (SDV Phase 3 WP1) reaches Context.prepare in every mode, `build` without it.
- Guest mode (SDV Phase 3 WP2), on synthetic consoles salted as QEMU's serial log is (NUL bytes, CRLF, a lone CR):
  the console reader removes NUL and CR, copies the console into the run directory and records the raw file's path,
  bytes and sha256, and C12b reads the four of five `vss rules:` lines that parse (one interleaved), failing on one
  that disagrees; the freshness gate refuses a LIVENESS line, a `client closed:` and a `client done:` with seen above
  0, and passes the probe's seen=0; a run with the probe's line before the gate's offset and a MISS but no final
  `client done:` after it fails console_end and the console gate (read whole, it would pass vacuously), lines before
  the offset are not judged; run_one in guest mode (the stack's calls replaced) starts no native monitor, allows no
  listener, judges the console after the offset and records c12b_lines; the bridge reaches the guest's host; `run`
  refuses --repeat above 1, two specs, no console, a loopback host and a console that is not fresh; `compare --modes`
  leaves out and names an unlisted mode's run and wants every listed one.
- The review's consoles (WP12fix): a MISS spliced into another instance's line, a close inside a REJECT line, a MISS
  inside the final `client done:` line each fail guest mode's console gate by name (native mode counts them, not
  gated); a guest pause run (tick and both) passes every gate with no garbled line, and a second MISS, close or RESTORED
  spliced into another of its lines fails its console gate alone, by name, though pause_sequence passes; a late seen=0
  after the bridge's end is counted, not taken for the split; a surplus session end fails console_end by name, and the
  wait does not wait it out; a probe held past the deadline is refused with the reason; no parsed rules line is noted
  as failing C12b; off the PC this host's own address is refused as the guest host.
- The twin-control marker (SDV Phase 6 WP2, D11): while it exists every `run` (each one starts a bridge) is refused
  before anything is read, made or started, in every mode, and a run_one whose context was made before the marker
  appeared is refused at the bridge's start with no container started; `plan` and `compare` start nothing and are not
  refused.
- A CARLA recording (SDV Phase 7 WP3b; spec-2 2.1 and 5 item 6): an honest one has only its to_end run, derived from
  the carla.log its line names (a sigsim.log beside it is never read); a line whose generator and log do not pair is
  refused naming both, by events_doc and by check_events; the log taken by the stack's one rule (bundle.py's
  log_name_of), whatever the form of the line's path (relative, bare, with a space or a .. segment), a sigsim recording
  so running as before Phase 7, and every line accepted or refused as the stack does; an events file naming another log
  than the line's is refused though its sha256 is the staged recording's; the live player and run_one take the staged log by the name the context
  gives (a context that names none is a sigsim one); WP1's fake take encoded against this tree's generation and its
  injected twin (tests/test_sdv_phase7_contract.py's builders): the twin's events file passes check_events against its
  own carla.log and plans the step-less specs in every mode, and is refused for another log, recording or contract;
  WP5a's real pair (skipped without it) plans every spec in every mode.
- For a run_through_ns off the tick grid, the end is a tick past the first grid instant at or past it; on the grid
  it is one tick after it, in every mode and run. A step at or after that end is refused in the same words, one
  before it taken. The judged replay model reads each grid instant late and answers only before the end step.
  The previous end rule can fail ticked_through alone off the grid; on the grid both rules agree. In process, a file
  whose last frame is 3.02 s from its first ticks through and passes every gate the judge holds, its last tick reading
  the clock after the reference plans' end; the sigsim pair's plans (skipped without it) are the reference's byte for
  byte, and the CARLA pair's (skipped without it) the reference's but for the to_end runs' end, its stop plans whole,
  the model ticking through each to_end replay plan; step3's RUN-THROUGH paragraph and the stack README's Run-through
  bullet count the harness's deadline from the script's end step.

The integration test (SDV_STEP3=1, with SDV_BRIDGE_IMAGE and SDV_RECORDING the injected recording) runs the
injected-stop spec in all three modes through the real stack and compares them; it writes only under ~/sdv-runs.
The guest-mode integration test (SDV_STEP3_GUEST=1, with SDV_BRIDGE_IMAGE and SDV_RECORDING an honest recording) runs
the honest spec in replay mode against a stand-in guest: the native vss monitor on :7160 (svc 500, INADDR_ANY), its
stdout relayed into a console file salted as QEMU's serial log is, reached at WSL's eth0 IPv4; then `compare --modes
replay`. It skips without a non-loopback IPv4 on eth0.

The cases include design values, generated values, synthetic inputs and record-derived regression inputs.
What this does NOT show: any timing; the QNX guest, io-sock or the image (the stand-in is the native
build); that br0 to the guest behaves as WSL's eth0; that a live mode samples as replay does (the integration test's
and the records' business).
"""
import hashlib
import importlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import test_sdv_bridge as tsb
import test_sdv_bridge_sources as tsbs
import test_sdv_frame as tsf
import test_sdv_inject as tsi

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import step3  # noqa: E402

sys.dont_write_bytecode = _saved

st, inj, rs, vb, bs, rules, attr = step3.st, step3.inj, step3.rs, step3.vb, step3.bs, step3.rules, step3.attr
vf = tsf.vf
C = tsf.C
MS = 1_000_000
TICK = vb.TICK_NS if C is not None else 0
STALE = rules.RSN_VSS_STALE
pytestmark = [tsf.NEEDS_CONTRACT]


@pytest.fixture(autouse=True)
def _no_host_twin_control(monkeypatch, tmp_path_factory):
    """No test reads this host's own twin-control marker (SDV Phase 6 WP2): the variable names a path no test makes unless
    it sets the variable itself. And no test reaches the daemon through the stack's stream seam (docker_stream, build
    mode's `docker save`) without a fake of its own: the stand-in fails loudly, as tests/test_sdv_stack.py's does."""
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(tmp_path_factory.getbasetemp() / "no-twin-control-marker-here"))
    monkeypatch.setattr(st, "docker_stream", lambda *a: (_ for _ in ()).throw(
        AssertionError("a step-3 test reached stack.docker_stream without a fake")), raising=False)


# ============================================================ synthetic events documents (inject.py's own functions)

def synth_doc(stop_ns=3_000 * MS, last_ns=5_000 * MS, events=(), events_file=True):
    """An events document as WP9's tool writes one: the design block, the injected events, and both runs built with
    inject.py's realisations, stale_windows and run_through_ns on the generated contract."""
    def run(name, ref, stop):
        return {"reference_ns": ref, "stop_ns": stop, "run_through_ns": inj.run_through_ns(ref, C),
                "realisation": inj.realisations(name, ref),
                "events": [dict(e, reason=e["intended_reason"]) for e in inj.stale_windows(name, ref, C)]}
    return {"format": inj.EVENTS_FORMAT, "recording": {"name": "syn", "sha256": "ab" * 32}, "design": inj.design_of(C, tsb.nominal()),
            "events": [dict(e) for e in events], "runs": {"stop": run("stop", stop_ns, stop_ns), "to_end": run("to_end", last_ns, None)},
            "events_file": {"path": "syn/events.json", "sha256": "cd" * 32} if events_file else None}


SPEED = {"event": "speed", "t0_ns": 1_000 * MS, "t1_ns": 1_700 * MS, "injected_ns": [1_150 * MS, 1_550 * MS],
         "intended_reason": rules.RSN_VSS_SPEED, "reason": rules.RSN_VSS_SPEED}
INJECTED = {"what": "t", "recording": "injected", "run": "stop"}
TO_END = {"what": "t", "recording": "injected", "run": "to_end"}


# ============================================================ the stop's realisation per mode, from the events file

@pytest.mark.parametrize("stop_ms", [3_000, 3_700])
@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_the_stop_realisation_per_mode_reads_its_offset_from_the_events_file(mode, stop_ms):
    doc = synth_doc(stop_ns=stop_ms * MS, events=[SPEED])
    plan = step3.plan_run(doc, "x", INJECTED, mode)
    want_how = {"broker": "can-provider", "can": "player", "replay": "intake"}[mode]
    real = doc["runs"]["stop"]["realisation"][mode]
    assert plan["stop"]["how"] == want_how and plan["stop"]["action"] == real["action"]
    assert plan["stop"]["at_offset_ns"] == real["at_offset_ns"] == stop_ms * MS
    assert plan["stop"]["call_offset_ns"] == stop_ms * MS - doc["design"]["tick_ns"] // 2
    pauses = [s for s in plan["script"]["steps"] if s["call"] == "pause_intake"]
    if mode == "replay":
        assert pauses == [{"at_ns": stop_ms * MS - TICK // 2, "call": "pause_intake"}], plan["script"]
    else:
        assert pauses == [], "a live stop is the stack's, never the bridge's: %s" % plan["script"]
    assert plan["run_through_ns"] == doc["runs"]["stop"]["run_through_ns"]
    assert {(w["event"], w["reason"]) for w in plan["windows"]} == {("speed", 23), ("stop", STALE), ("stop-held", STALE)}
    assert all(w["origin"] == "recording" for w in plan["windows"])


@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_a_to_end_run_plans_no_stop(mode):
    plan = step3.plan_run(synth_doc(events=[SPEED]), "x", TO_END, mode)
    assert plan["stop"] is None and not [s for s in plan["script"]["steps"] if s["call"] == "pause_intake"]
    assert {(w["event"], w["reason"]) for w in plan["windows"]} == {("speed", 23), ("end", STALE), ("end-held", STALE)}


@pytest.mark.parametrize("change, match", [
    (lambda r: r["realisation"]["can"].update(action="stop the can-provider"), "can stops only by player"),
    (lambda r: r["realisation"]["can"].update(action="stop the bus"), "is not one of"),
    (lambda r: r["realisation"]["can"].update(at_offset_ns=r["stop_ns"] + TICK), "not the run's stop_ns"),
    (lambda r: r["realisation"]["can"].update(undone=True), "undone"),
    (lambda r: r["realisation"].pop("can"), "names no realisation for can"),
])
def test_an_events_file_whose_stop_is_not_the_modes_one_is_refused(change, match):
    doc = synth_doc()
    change(doc["runs"]["stop"])
    with pytest.raises(step3.StepError, match=match):
        step3.plan_run(doc, "x", INJECTED, "can")


def test_the_replay_stop_must_be_the_bridges_intake_pause():
    doc = synth_doc()
    doc["runs"]["stop"]["realisation"]["replay"]["call"] = "Bridge.pause_tick"
    with pytest.raises(step3.StepError, match="Bridge.pause_intake"):
        step3.plan_run(doc, "x", INJECTED, "replay")


# ============================================================ run-through

@pytest.mark.parametrize("stop_ms, last_ms", [(3_000, 5_000), (4_200, 9_000)])
@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_every_script_ends_one_tick_past_the_runs_run_through(mode, stop_ms, last_ms):
    doc = synth_doc(stop_ns=stop_ms * MS, last_ns=last_ms * MS)
    for run in ("stop", "to_end"):
        plan = step3.plan_run(doc, "x", dict(INJECTED, run=run), mode)
        want = doc["runs"][run]["run_through_ns"] + TICK
        assert plan["end_offset_ns"] == want and plan["script"]["steps"][-1] == {"at_ns": want, "call": "end"}
        assert all(s["at_ns"] < want for s in plan["script"]["steps"][:-1])


class FakeOps:
    """step3's Ops on a fake clock: the player plays the file from `origin` (its first frame reaches the capture at once),
    a stopped player ends at its stop, the bridge ends itself at bridge_ends_ns (None: never)."""

    def __init__(self, file_end_ns, bridge_ends_ns=None, origin=10**18):
        self.t = origin - 2 * 10**9
        self.origin, self.file_end = origin, file_end_ns
        self.bridge_ends = bridge_ends_ns
        self.calls: List[tuple] = []
        self.player_stopped: Optional[int] = None

    def now_ns(self):
        return self.t

    def sleep_until(self, t):
        self.t = max(self.t, t)

    def start_player(self):
        self.calls.append(("start_player", self.t))

    def wait_origin(self, _timeout):
        self.t = self.origin
        return self.origin

    def stop_player(self):
        self.calls.append(("stop_player", self.t))
        self.player_stopped = self.t
        return {"issued_ns": self.t, "returned_ns": self.t, "ok": True, "how": "player"}

    def stop_provider(self):
        self.calls.append(("stop_provider", self.t))
        return {"issued_ns": self.t, "returned_ns": self.t, "ok": True, "how": "can-provider"}

    def wait_player(self, _timeout):
        self.t = max(self.t, self.player_stopped if self.player_stopped is not None else self.origin + self.file_end)
        self.calls.append(("player_end", self.t))
        return 0

    def wait_anchor(self, _timeout):
        self.t = self.origin
        return self.origin

    def wait_bridge(self, deadline):
        if self.bridge_ends is not None and self.bridge_ends <= deadline:
            self.t = max(self.t, self.bridge_ends)
            return self.t
        self.t = max(self.t, deadline)
        return None

    def stop_bridge(self):
        self.calls.append(("stop_bridge", self.t))
        return {"stopped_ns": self.t}


@pytest.mark.parametrize("mode, run", [("can", "stop"), ("broker", "stop"), ("can", "to_end"), ("broker", "to_end")])
def test_the_live_driver_stops_by_the_modes_realisation_and_never_stops_the_bridge_at_the_players_end(mode, run):
    doc = synth_doc(stop_ns=3_700 * MS, last_ns=6_000 * MS)
    plan = step3.plan_run(doc, "x", dict(INJECTED, run=run), mode)
    o = 10**18
    ops = FakeOps(plan["file_end_ns"], bridge_ends_ns=o + plan["end_offset_ns"] + 3 * MS, origin=o)
    out = step3.drive_live(plan, ops)
    stops = [c for c in ops.calls if c[0] in ("stop_player", "stop_provider")]
    if run == "stop":
        name = {"can": "stop_player", "broker": "stop_provider"}[mode]
        assert stops == [(name, o + doc["runs"]["stop"]["realisation"][mode]["at_offset_ns"] - TICK // 2)], ops.calls
        assert out["stop"]["how"] == plan["stop"]["how"] and out["stop"]["due_ns"] == stops[0][1]
    else:
        assert stops == [] and out["stop"] is None
    assert step3.stop_evidence(plan, out, [], {"recording": o})["ok"], "the driver's record passes the stop gate"
    assert not [c for c in ops.calls if c[0] == "stop_bridge"], "the bridge ends itself past run_through: %s" % ops.calls
    player_end = [c for c in ops.calls if c[0] == "player_end"][0][1]
    ends = o + plan["end_offset_ns"] + 3 * MS
    assert out["bridge"]["ended_itself"] is True and out["bridge"]["seen_ended_ns"] == max(ends, player_end)
    assert out["bridge"]["deadline_ns"] == o + plan["end_offset_ns"] + int(step3.END_SLACK_S * 1e9)
    if (mode, run) != ("broker", "stop"):
        assert player_end < ends, "the bridge ticks on past the player's end"
    else:
        assert player_end == o + plan["file_end_ns"] > ends, "broker's stop is the provider's: the player plays the file to its end"


def test_a_bridge_that_outlives_its_deadline_is_stopped_and_the_run_marked():
    plan = step3.plan_run(synth_doc(), "x", TO_END, "can")
    o = 10**18
    ops = FakeOps(plan["file_end_ns"], bridge_ends_ns=None, origin=o)
    out = step3.drive_live(plan, ops)
    deadline = o + plan["end_offset_ns"] + int(step3.END_SLACK_S * 1e9)
    assert ops.calls[-1] == ("stop_bridge", deadline) and out["bridge"]["ended_itself"] is False


def test_the_replay_driver_waits_from_the_runs_anchor_through_run_through():
    plan = step3.plan_run(synth_doc(), "x", INJECTED, "replay")
    o = 5 * 10**12
    ops = FakeOps(plan["file_end_ns"], bridge_ends_ns=o + plan["end_offset_ns"] + MS, origin=o)
    out = step3.drive_replay(plan, ops)
    assert out["origin_ns"] == o and out["bridge"]["ended_itself"] is True
    assert out["bridge"]["deadline_ns"] == o + plan["end_offset_ns"] + int(step3.END_SLACK_S * 1e9)
    assert ops.calls == [], "replay's stop and end are the bridge's own script steps"
    with pytest.raises(step3.StepError):
        step3.drive_live(plan, ops)


# ============================================================ the judge, on the real injected recording replayed offline

INJ = tsi.MADE
NEEDS_INJ = pytest.mark.skipif(not (INJ / "events.json").is_file(), reason="needs the injected recording %s (read only)" % INJ)


@pytest.fixture(scope="module")
def inj4():
    db = tsi.StandInDB(tsbs.SLICE_TEXT)
    line = tsi.jload(INJ / "manifest-line.json")
    sha = hashlib.sha256((INJ / "sigsim.log").read_bytes()).hexdigest()
    doc = step3.events_doc(INJ, sha, line, C)
    return types.SimpleNamespace(db=db, line=line, doc=doc, log=INJ / "sigsim.log")


def _offline(r, stop_ns, until_ns):
    return tsi.replay(r.log, r.db, r.line, stop_ns, until_ns)


def _intake_step(plan, anchor):
    s = plan["stop"]
    return [{"event": "script-step", "call": "pause_intake", "at_ns": s["call_offset_ns"], "done_ns": anchor + s["call_offset_ns"]}]


@NEEDS_INJ
def test_the_real_events_file_plans_its_own_offsets(inj4):
    for mode in step3.MODES:
        plan = step3.plan_run(inj4.doc, "injected-stop", INJECTED, mode)
        real = inj4.doc["runs"]["stop"]["realisation"][mode]
        assert plan["stop"]["at_offset_ns"] == real["at_offset_ns"] == inj4.doc["runs"]["stop"]["stop_ns"]
        assert plan["end_offset_ns"] == inj4.doc["runs"]["stop"]["run_through_ns"] + TICK
        assert plan["events_file"]["sha256"] == hashlib.sha256((INJ / "events.json").read_bytes()).hexdigest()


@NEEDS_INJ
def test_the_judge_passes_the_stop_run_and_fails_it_without_its_stop_or_cut_at_the_players_end(inj4):
    plan = step3.plan_run(inj4.doc, "injected-stop", INJECTED, "replay")
    s, through = plan["stop"]["at_offset_ns"], plan["run_through_ns"]
    replies, anchor = _offline(inj4, s, through)
    origins = {"recording": anchor, "script": anchor}
    ok = step3.judge(plan, replies, _intake_step(plan, anchor), None, "", origins, {}, C.AGE_MAX_MS)
    assert ok["gates"]["reason_set"] and ok["gates"]["ticked_through"] and ok["gates"]["stop"], ok["reason_set"]
    assert ok["reason_set"]["got"] == plan["expected"]
    assert ok["first_22"]["offset_ns"] >= s and ok["first_22"]["age_ms"] > C.AGE_MAX_MS
    # the stop never realised: replayed to the file's end and past it, the file's end gives the 22s, in the open-ended
    # window only (WP9's own finding); ended at the run's end, the run holds no 22 at all
    replies, anchor = _offline(inj4, None, max(r["run_through_ns"] for r in inj4.doc["runs"].values()))
    bad = step3.judge(plan, replies, [], None, "", {"recording": anchor, "script": anchor}, {}, C.AGE_MAX_MS)
    assert not bad["gates"]["reason_set"] and bad["reason_set"]["missing"] == [["stop", STALE]], bad["reason_set"]
    assert not bad["gates"]["stop"]
    replies, anchor = _offline(inj4, None, through)
    bad = step3.judge(plan, replies, [], None, "", {"recording": anchor, "script": anchor}, {}, C.AGE_MAX_MS)
    assert bad["reason_set"]["missing"] == [["stop", STALE], ["stop-held", STALE]] and bad["gates"]["ticked_through"]
    # the bridge stopped at the player's end (can: the player stops at S - tick/2)
    replies, anchor = _offline(inj4, s, plan["stop"]["call_offset_ns"])
    cut = step3.judge(plan, replies, _intake_step(plan, anchor), None, "", {"recording": anchor, "script": anchor}, {}, C.AGE_MAX_MS)
    assert not cut["gates"]["ticked_through"] and not cut["gates"]["reason_set"]
    assert ["stop", STALE] in cut["reason_set"]["missing"] and ["stop-held", STALE] in cut["reason_set"]["missing"]


@NEEDS_INJ
def test_a_to_end_run_cut_at_the_files_end_neither_ticks_through_nor_holds_its_held_window(inj4):
    plan = step3.plan_run(inj4.doc, "injected-to-end", TO_END, "replay")
    replies, anchor = _offline(inj4, None, plan["run_through_ns"])
    full = step3.judge(plan, replies, [], None, "", {"recording": anchor, "script": anchor}, {}, C.AGE_MAX_MS)
    assert full["gates"]["reason_set"] and full["gates"]["ticked_through"] and full["gates"]["stop"]
    replies, anchor = _offline(inj4, None, plan["file_end_ns"])
    cut = step3.judge(plan, replies, [], None, "", {"recording": anchor, "script": anchor}, {}, C.AGE_MAX_MS)
    assert not cut["gates"]["ticked_through"] and ["end-held", STALE] in cut["reason_set"]["missing"]


@NEEDS_INJ
def test_the_injected_recordings_events_file_is_checked_against_the_recording(inj4, tmp_path):
    raw = (INJ / "events.json").read_bytes()
    sha = hashlib.sha256((INJ / "sigsim.log").read_bytes()).hexdigest()
    assert step3.check_events(json.loads(raw), raw, sha, inj4.line, C) == []
    assert step3.check_events(json.loads(raw), raw, "00" * 32, inj4.line, C), "another recording"
    doc = json.loads(raw)
    doc["design"]["tick_ns"] = TICK * 2
    assert any("tick" in p for p in step3.check_events(doc, raw, sha, inj4.line, C))
    doc = json.loads(raw)
    doc["contract"]["sha256"] = "ee" * 32
    assert any("contract" in p for p in step3.check_events(doc, raw, sha, inj4.line, C))
    assert any("rewrite_events_sha256" in p for p in step3.check_events(json.loads(raw), raw + b" ", sha, inj4.line, C))


# ============================================================ an honest recording: the to_end run derived as inject.py derives it

LOGS = {"sigsim": "sigsim.log", "carla": "carla.log"}         # a recording's log by its generator (spec-2 2.1), this file's spelling


def _honest_dir(tmp_path, ms=2_000, gen="sigsim", **params):
    """An honest recording's directory and manifest line: the log its generator names (gen: sigsim or carla, SDV Phase 7
    WP3b), a line whose recording.path names it."""
    d = tmp_path / "honest"
    d.mkdir()
    log = LOGS[gen]
    tsbs.candump(tsbs.trip(ms, vary=False), d / log)
    line = {"name": "syn-honest", "profile_id": tsb.nominal(),
            "recording": {"format": "candump-log", "path": "~/sdv-recordings/syn-honest/%s" % log},
            "source": {"generator": gen, "params": dict(params)}}
    return d, line, hashlib.sha256((d / log).read_bytes()).hexdigest()


def test_an_honest_recording_has_only_its_to_end_run_as_inject_derives_it(tmp_path):
    d, line, sha = _honest_dir(tmp_path)
    doc = step3.events_doc(d, sha, line, C)
    assert doc["events_file"] is None and doc["events"] == [] and list(doc["runs"]) == ["to_end"]
    r = doc["runs"]["to_end"]
    assert r["reference_ns"] == 2_000 * MS and r["run_through_ns"] == inj.run_through_ns(2_000 * MS, C)
    assert [(e["event"], e["reason"]) for e in r["events"]] == [("end", STALE), ("end-held", STALE)]
    plan = step3.plan_run(doc, "honest", {"what": "t", "recording": "honest", "run": "to_end"}, "replay")
    assert plan["expected"] == [["end", STALE], ["end-held", STALE]]
    with pytest.raises(step3.StepError, match="injected recording's events file"):
        step3.plan_run(doc, "x", INJECTED, "replay")
    with pytest.raises(step3.StepError, match="for an honest recording"):
        step3.plan_run(synth_doc(), "x", {"what": "t", "recording": "honest", "run": "to_end"}, "replay")


def test_a_rewritten_recording_without_its_events_file_is_refused(tmp_path):
    d, line, sha = _honest_dir(tmp_path, rewrite_of="x")
    with pytest.raises(step3.StepError, match="rewritten recording"):
        step3.events_doc(d, sha, line, C)


# ============================================================ a CARLA recording (SDV Phase 7 WP3b; spec-2 2.1 and 5 item 6)

def test_an_honest_carla_recording_has_only_its_to_end_run_read_from_its_carla_log(tmp_path):
    """The honest doc is derived from the log the line names: a sigsim.log beside a CARLA recording's carla.log (another
    file, never read) changes nothing; the line's log is the doc's recording.log."""
    d, line, sha = _honest_dir(tmp_path, ms=3_000, gen="carla")
    tsbs.candump(tsbs.trip(1_000, vary=False), d / "sigsim.log")
    doc = step3.events_doc(d, sha, line, C)
    assert doc["recording"] == {"name": "syn-honest", "log": "carla.log", "sha256": sha} and doc["events_file"] is None
    assert list(doc["runs"]) == ["to_end"] and doc["runs"]["to_end"]["reference_ns"] == 3_000 * MS
    plan = step3.plan_run(doc, "honest", {"what": "t", "recording": "honest", "run": "to_end"}, "replay")
    assert plan["expected"] == [["end", STALE], ["end-held", STALE]] and plan["recording"]["log"] == "carla.log"
    with pytest.raises(step3.StepError, match="injected recording's events file"):
        step3.plan_run(doc, "x", INJECTED, "replay")


@pytest.mark.parametrize("gen", ["carla", "sigsim"])
def test_an_honest_recording_that_is_not_the_one_the_stack_staged_is_refused(tmp_path, gen):
    """The derived to_end run is of the staged recording: a log that hashes to another sha256 than the stack's is refused,
    for a carla.log as for a sigsim.log (the check is keyed by the line's log, not by sigsim's)."""
    d, line, sha = _honest_dir(tmp_path, gen=gen)
    assert step3.events_doc(d, sha, line, C)["recording"]["sha256"] == sha
    with pytest.raises(step3.StepError, match="is not the recording the stack staged"):
        step3.events_doc(d, "00" * 32, line, C)


@pytest.mark.parametrize("gen, path_log", [("carla", "sigsim.log"), ("sigsim", "carla.log"), ("carla", "drive.log"), ("vtd", "sigsim.log"),
                                           ("carla", "carla.log.bak"), ("sigsim", "sigsim.LOG")])
def test_a_line_whose_generator_and_log_do_not_pair_is_refused_naming_both(tmp_path, gen, path_log):
    d, line, sha = _honest_dir(tmp_path)
    line = dict(line, recording={"format": "candump-log", "path": "~/sdv-recordings/syn-honest/" + path_log},
                source={"generator": gen, "params": {}})
    with pytest.raises(step3.StepError) as exc:
        step3.events_doc(d, sha, line, C)
    assert repr(gen) in str(exc.value) and path_log in str(exc.value), str(exc.value)
    assert any(repr(gen) in p and path_log in p for p in step3.check_events(synth_doc(), b"{}", "ab" * 32, line, C))


def test_check_events_refuses_an_events_file_of_another_log(tmp_path):
    """events.json names its recording's log (sdv/inject/inject.py's recording.log): one that names another log than the
    line's is refused, though its sha256 is the staged recording's."""
    line = {"name": "x", "profile_id": tsb.nominal(), "recording": {"format": "candump-log", "path": "~/sdv-recordings/x/carla.log"},
            "source": {"generator": "carla", "params": {}}}
    doc = synth_doc()
    doc["recording"]["log"] = "sigsim.log"
    got = step3.check_events(doc, b"{}", "ab" * 32, line, C)
    assert [p for p in got if "'sigsim.log'" in p and "'carla.log'" in p], got
    doc["recording"]["log"] = "carla.log"
    assert not [p for p in step3.check_events(doc, b"{}", "ab" * 32, line, C) if "log" in p]
    del doc["recording"]["log"]
    assert [p for p in step3.check_events(doc, b"{}", "ab" * 32, line, C) if "None" in p and "'carla.log'" in p]


# One rule for a line's log (the WP3b review): step 3 takes it as the stack, the bundle and setup take it, by bundle.py's
# log_name_of (the generator and the basename of recording.path); the form of the path is not read, so a sigsim recording
# whose line sigsim.py record wrote under a relative --out (or a path with a space) runs here as before Phase 7.
# sdv/inject/inject.py checks a scenario entry path for the recordings it reads and writes.
LOG_PATH_FORMS = ["~/sdv-recordings/syn-honest/%s", "/home/u/rec/syn-honest/%s", "sdv-out/rec/syn-honest/%s", "%s",
                  "/tmp/my rec/%s", "/home/u/sdv_recordings/x/%s", "../other/%s"]


@pytest.mark.parametrize("form", LOG_PATH_FORMS, ids=["tilde", "absolute", "relative", "bare", "space", "underscore", "dotdot"])
def test_step3_takes_a_lines_log_by_the_stacks_rule_whatever_the_form_of_its_path(tmp_path, form):
    d, line, sha = _honest_dir(tmp_path)
    line = dict(line, recording=dict(line["recording"], path=form % "sigsim.log"))
    assert step3.line_log(line) == "sigsim.log" == st.bd.log_name_of(line)[0]
    doc = step3.events_doc(d, sha, line, C)
    assert doc["recording"]["log"] == "sigsim.log" and list(doc["runs"]) == ["to_end"]
    events = synth_doc()
    events["recording"]["log"] = "sigsim.log"
    assert not [p for p in step3.check_events(events, b"{}", "ab" * 32, line, C) if "log" in p or "path" in p]


def test_step3s_log_rule_is_the_stacks_on_every_line():
    """step3.line_log accepts what bundle.log_name_of accepts, with the same name, and refuses what it refuses, with its
    words (each naming the generator and the log)."""
    lines: List[Dict[str, Any]] = [{"recording": {"path": form % log}, "source": {"generator": gen}} for form in LOG_PATH_FORMS
                                   for gen in ("sigsim", "carla", "vtd") for log in ("sigsim.log", "carla.log", "drive.log")]
    lines += [{"recording": {}, "source": {"generator": "sigsim"}}, {"recording": {"path": "~/x/sigsim.log"}, "source": {}},
              {"recording": {"path": 7}, "source": {"generator": "carla"}}, {"source": {"generator": "carla"}}]
    taken = 0
    for line in lines:
        name, why = st.bd.log_name_of(line)
        if name is not None:
            assert step3.line_log(line) == name, line
            taken += 1
            continue
        with pytest.raises(step3.StepError) as exc:
            step3.line_log(line)
        assert why is not None and why in str(exc.value), (str(exc.value), why)
    assert taken == 2 * len(LOG_PATH_FORMS)


def test_the_live_player_plays_the_staged_log_by_its_name(tmp_path, monkeypatch):
    seen: List[List[str]] = []

    class Player:
        def __init__(self, argv, **_kw):
            seen.append(list(argv))

        def poll(self):
            return 0
    monkeypatch.setattr(step3.subprocess, "Popen", Player)
    for log in ("carla.log", "sigsim.log"):
        ctx = types.SimpleNamespace(bridge="can", in_dir=tmp_path / "in", log_name=log)
        ops = step3.LiveOps(ctx, tmp_path, None)
        ops.start_player()
        ops.close()
        assert seen[-1][1:] == ["-m", "can.player", "-i", "socketcan", "-c", st.VCAN, str(tmp_path / "in" / log)], seen[-1]
    ctx = types.SimpleNamespace(bridge="can", in_dir=tmp_path / "in")         # a context that names no log is a sigsim one
    ops = step3.LiveOps(ctx, tmp_path, None)
    ops.start_player()
    ops.close()
    assert seen[-1][-1] == str(tmp_path / "in" / "sigsim.log")


def test_run_one_reads_the_staged_carla_log_by_its_name(tmp_path, monkeypatch):
    """run_one's recording is the staged log the context names (a CARLA run's carla.log; the context holds no sigsim.log)."""
    ctx, plan, _console, _seen = _guest_run_one(tmp_path, monkeypatch, [FINAL_DONE])
    ctx.log_name, ctx.staged = "carla.log", {"carla.log": "cd" * 32}
    r = step3.run_one(ctx, plan, "honest-replay-1")
    assert r["recording"]["sha256"] == "cd" * 32 and r["ok"], [g for g, v in r["gates"].items() if not v]


@pytest.mark.parametrize("log", ["carla.log", "sigsim.log"])
def test_run_one_in_can_mode_reads_the_staged_log_by_its_name_for_the_bus_check(tmp_path, monkeypatch, log):
    """The bus check of a can run compares vcan0 with the staged log the context names: a CARLA run's carla.log, a sigsim
    run's sigsim.log, never the other (spec-2 2.1: every argv, player and record names the staged log). The stack, the
    capture, the player and the drive are stand-ins; a spy takes the place of the candump reader and records its path."""
    ctx, _replay, _console, _seen = _guest_run_one(tmp_path, monkeypatch, [FINAL_DONE])
    ctx.bridge, ctx.log_name, ctx.staged, ctx.in_dir = "can", log, {log: "cd" * 32}, tmp_path / "in"
    plan = step3.plan_run(_honest_30s(), "honest", step3.load_specs()["honest"], "can")
    read: List[Path] = []

    class Capture:
        def close(self):
            return []

    class Ops:
        def __init__(self, *_args):
            pass

        def close(self):
            pass
    monkeypatch.setattr(st, "ensure_vcan", lambda: {"created": False})
    monkeypatch.setattr(st, "VcanCapture", Capture)
    monkeypatch.setattr(step3, "LiveOps", Ops)
    monkeypatch.setattr(step3, "drive_live", lambda plan, ops: {"origin_ns": ORIGIN, "bridge": {"ended_itself": True}})
    monkeypatch.setattr(bs, "read_candump", lambda path: (read.append(Path(path)), [])[1])
    r = step3.run_one(ctx, plan, "honest-can-1")
    assert read == [tmp_path / "in" / log], read
    assert r["mode"] == "can" and r["recording"]["sha256"] == "cd" * 32 and r["bus"]["ok"] is True, r.get("bus")


@pytest.fixture(scope="module")
def fake_carla(tmp_path_factory):
    """WP1's fake take encoded against this tree's generation and its injected twin (tests/test_sdv_phase7_contract.py's
    builders and stand-ins), in pytest's tmp only."""
    tp7 = importlib.import_module("test_sdv_phase7_contract")
    rc_take, _carla, take = tp7.tsc.run_take(tmp_path_factory.mktemp("take"), name=tp7.NAME, seed=tp7.SEED)
    assert rc_take == 0
    out = tmp_path_factory.mktemp("rec") / tp7.NAME
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tp7.encode, "load_dbc", lambda contract, path=None: tp7.tsc.FakeDb())
        mp.setattr(tp7.encode, "read_log", tp7.tsc.fake_read_log)
        res = tp7.encode.record(take, out, tp7.NAME, contract=tp7.C)
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["problems"]
    built = inj.build(out, tp7.INJ_NAME, tsi.StandInDB(tsbs.SLICE_TEXT), C, bs.SLICE_DBC)
    dest = tmp_path_factory.mktemp("inj") / tp7.INJ_NAME
    inj.write(built, dest)
    return types.SimpleNamespace(dir=out, inj=dest)


def _doc_of(d):
    line = tsi.jload(d / "manifest-line.json")
    sha = hashlib.sha256((d / inj.log_name_of(line)).read_bytes()).hexdigest()
    return line, sha, step3.events_doc(d, sha, line, C)


def test_an_injected_carla_recordings_events_file_is_checked_as_sigsims_is(fake_carla):
    """The fake take's recording and its rewrite: the honest one has only its to_end run; the injected one's events.json
    passes check_events against its own carla.log and plans every injected spec in every mode, its stop at the file's own
    offset; the same events file is refused for another log, another recording, another contract."""
    _line, _sha, honest = _doc_of(fake_carla.dir)
    assert list(honest["runs"]) == ["to_end"] and honest["events_file"] is None and honest["recording"]["log"] == "carla.log"
    line, sha, doc = _doc_of(fake_carla.inj)
    raw = (fake_carla.inj / "events.json").read_bytes()
    assert doc["events_file"]["sha256"] == hashlib.sha256(raw).hexdigest() and set(doc["runs"]) == set(inj.RUNS)
    specs = step3.load_specs()
    for name in ("honest", "injected-to-end", "injected-stop"):         # the specs without steps of their own (a short take)
        for mode in step3.MODES:
            spec = specs[name]
            plan = step3.plan_run(doc if spec["recording"] == "injected" else honest, name, spec, mode)
            if spec["run"] == "stop":
                assert plan["stop"]["at_offset_ns"] == doc["runs"]["stop"]["stop_ns"]
    assert step3.check_events(json.loads(raw), raw, sha, line, C) == []
    other = json.loads(raw)
    other["recording"]["log"] = "sigsim.log"
    assert [p for p in step3.check_events(other, raw, sha, line, C) if "'sigsim.log'" in p]
    assert step3.check_events(json.loads(raw), raw, "00" * 32, line, C), "another recording"
    other = json.loads(raw)
    other["contract"]["sha256"] = "ee" * 32
    assert [p for p in step3.check_events(other, raw, sha, line, C) if "contract" in p]


CARLA_PAIR = (Path("~/sdv-recordings").expanduser() / "20261019-carla-1", Path("~/sdv-recordings").expanduser() / "20261019-carla-1-inj")
NEEDS_CARLA_PAIR = pytest.mark.skipif(not all((d / "manifest-line.json").is_file() for d in CARLA_PAIR) or
                                      not (CARLA_PAIR[1] / "events.json").is_file(),
                                      reason="needs WP5a's CARLA pair %s and its -inj twin (read only)" % CARLA_PAIR[0])


@NEEDS_CARLA_PAIR
def test_the_real_carla_pair_plans_every_spec_in_every_mode():
    """Read only: WP5a's honest recording has only its to_end run; its twin's events file is checked against its carla.log
    (by the stack's own identity) and every spec plans in every mode."""
    docs = {}
    for kind, d in zip(("honest", "injected"), CARLA_PAIR):
        rec = st.recording_identity(d)
        assert rec["log_name"] == "carla.log"
        docs[kind] = step3.events_doc(d, rec["sha256"], rec["manifest_line"], C)
    assert list(docs["honest"]["runs"]) == ["to_end"] and docs["injected"]["events_file"] is not None
    for name, spec in step3.load_specs().items():
        for mode in step3.MODES:
            step3.plan_run(docs[spec["recording"]], name, spec, mode)


# ============================================================ the run specs

def test_every_spec_in_the_file_plans_in_every_mode(tmp_path):
    specs = step3.load_specs()
    assert {"honest", "injected-to-end", "injected-stop", "inject", "pause-tick", "pause-both"} <= set(specs)
    d, line, sha = _honest_dir(tmp_path, ms=30_000)
    honest = step3.events_doc(d, sha, line, C)
    injected = synth_doc(stop_ns=25_000 * MS, last_ns=30_000 * MS, events=[SPEED])
    for name, spec in specs.items():
        for mode in step3.MODES:
            plan = step3.plan_run(injected if spec["recording"] == "injected" else honest, name, spec, mode)
            steps = plan["script"]["steps"]
            assert steps[-1]["call"] == "end" and [s["at_ns"] for s in steps] == sorted(s["at_ns"] for s in steps)
            for s, given in zip([s for s in steps if s["call"] not in ("end",) and not (plan["stop"] and s["call"] == "pause_intake")],
                                spec.get("steps", [])):
                assert s["at_ns"] == given["at_ns"] + TICK // 4, "a quarter tick after its grid instant"
    inject = step3.plan_run(honest, "inject", specs["inject"], "replay")
    assert {(w["event"], w["reason"]) for w in inject["windows"] if w["origin"] == "script"} == {
        ("inject-nan", rules.RSN_NOT_FINITE), ("inject-reserved", rules.RSN_FLAGS_INVALID), ("inject-digest", rules.RSN_VSS_CATALOG),
        ("inject-profile0", rules.RSN_PROFILE_UNBOUND)}
    assert step3.plan_run(honest, "pause-tick", specs["pause-tick"], "can")["sequence"] == "tick"
    assert step3.plan_run(honest, "inject", specs["inject"], "can")["sequence"] is None
    # kind4-spec 15's row "pause test | 1.5 s (plan)", and 14.4's order for both: paused at one instant, the tick resumed
    # before the intake (so the first frame after the tick's resume is a deterministic 22); in the file and in each plan
    for name in ("pause-tick", "pause-both"):
        for steps in [specs[name]["steps"]] + [step3.plan_run(honest, name, specs[name], m)["script"]["steps"] for m in step3.MODES]:
            at = {s["call"]: s["at_ns"] for s in steps}
            assert at["resume_tick"] - at["pause_tick"] == 1_500 * MS, (name, steps)
            if name == "pause-both":
                assert at["pause_intake"] == at["pause_tick"] and at["resume_intake"] > at["resume_tick"], steps


@pytest.mark.parametrize("spec, match", [
    ({"what": "t", "recording": "honest", "run": "stop"}, "only the to_end run"),
    ({"what": "t", "recording": "injected", "run": "stop", "steps": [{"at_ns": 0, "call": "end"}]}, "never end"),
    ({"what": "t", "recording": "injected", "run": "stop", "steps": [{"at_ns": 0, "call": "inject", "mode": "nan"}]}, "keys"),
    ({"what": "t", "recording": "honest", "run": "to_end", "windows": [{"event": "e", "t0_ns": 0, "t1_ns": 1, "reason": "ok"}]}, "reject reason"),
    ({"what": "t", "recording": "honest", "run": "to_end", "steps": [{"at_ns": 0, "call": "pause_tick"}], "sequence": "both"}, "sequence"),
    ({"what": "t", "recording": "elsewhere", "run": "to_end"}, "recording"),
    ({"what": "t", "recording": "honest", "run": "to_end", "extra": 1}, "keys"),
])
def test_a_malformed_spec_is_refused(spec, match):
    with pytest.raises(step3.StepError, match=match):
        step3.check_spec("bad", spec)


def test_a_step_off_the_tick_grid_or_past_the_end_is_refused(tmp_path):
    d, line, sha = _honest_dir(tmp_path)
    doc = step3.events_doc(d, sha, line, C)
    spec = {"what": "t", "recording": "honest", "run": "to_end", "steps": [{"at_ns": 150 * MS, "call": "pause_tick"}]}
    with pytest.raises(step3.StepError, match="tick grid"):
        step3.plan_run(doc, "x", spec, "replay")
    spec["steps"] = [{"at_ns": doc["runs"]["to_end"]["run_through_ns"] + TICK, "call": "pause_tick"}]
    with pytest.raises(step3.StepError, match="run's end"):
        step3.plan_run(doc, "x", spec, "replay")


# ============================================================ the comparison

def _result(mode, got, spec="injected-stop", sha="ab" * 32, run=None):
    return {"step3": 1, "run": run or "%s-%s-1" % (spec, mode), "spec": spec, "mode": mode, "recording": {"sha256": sha},
            "reason_set": {"got": [list(p) for p in got]}, "ok": True, "dir": "/runs/%s" % mode}


GOOD = [("speed", 23), ("stop", STALE), ("stop-held", STALE)]


def _no_frames(r):
    raise AssertionError("frames read for %s" % r["run"])


def test_the_comparison_passes_three_modes_with_one_set():
    res = step3.compare_results([_result(m, GOOD) for m in step3.MODES], _no_frames)
    assert res["ok"] and res["groups"][0]["modes"]["ok"]


@pytest.mark.parametrize("odd", ["broker", "can", "replay"])
def test_the_comparison_fails_on_one_differing_pair_in_any_mode(odd):
    runs = [_result(m, GOOD if m != odd else GOOD[:2] + [(None, STALE)]) for m in step3.MODES]
    res = step3.compare_results(runs, _no_frames)
    assert not res["ok"]
    differ = res["groups"][0]["modes"]["differ"]
    assert differ and {d["mode"] for d in differ} == ({odd} if odd != "broker" else {"can", "replay"}), differ


def test_the_comparison_fails_when_a_mode_has_no_run():
    res = step3.compare_results([_result(m, GOOD) for m in ("broker", "replay")], _no_frames)
    assert not res["ok"] and res["groups"][0]["modes"]["missing_modes"] == ["can"]


def test_frames_are_compared_only_between_replay_runs_and_one_differing_frame_fails():
    frames = [bytes(64), bytes(range(64))]
    other = [bytes(64), bytes(range(1, 65))]
    runs = [_result("broker", GOOD), _result("can", GOOD), _result("replay", GOOD, run="r1"), _result("replay", GOOD, run="r2")]
    asked: List[str] = []

    def frames_of(r):
        assert r["mode"] == "replay", "frames are never read for a %s run" % r["mode"]
        asked.append(r["run"])
        return frames
    res = step3.compare_results(runs, frames_of)
    assert res["ok"] and asked == ["r1", "r2"] and res["groups"][0]["frames"][0]["runs"] == ["r1", "r2"]
    res = step3.compare_results(runs, lambda r: frames if r["run"] == "r1" else other)
    assert not res["ok"] and res["groups"][0]["frames"][0]["differ"] == [1]


def test_a_result_an_aborted_run_left_fails_its_group_by_name_and_is_never_compared():
    """run_one writes result.json before its judge runs: an aborted run leaves one with no reason set."""
    aborted = {k: v for k, v in _result("can", GOOD).items() if k not in ("reason_set", "ok")}
    res = step3.compare_results([_result("broker", GOOD), aborted, _result("replay", GOOD)], _no_frames)
    g = res["groups"][0]
    assert not res["ok"] and not g["ok"] and g["problems"] == ["%s (%s): no reason set, the run was never judged" % (aborted["run"], aborted["dir"])]
    assert g["modes"]["missing_modes"] == ["can"] and [r["judged"] for r in g["runs"]] == [True, False, True]


def test_a_run_that_failed_its_own_gates_fails_its_group_though_the_sets_agree():
    runs = [_result(m, GOOD) for m in step3.MODES]
    runs[1]["ok"] = False
    res = step3.compare_results(runs, _no_frames)
    g = res["groups"][0]
    assert not res["ok"] and not g["ok"] and g["modes"]["ok"]
    assert g["problems"] == ["%s (%s): it failed its own gates (ok False)" % (runs[1]["run"], runs[1]["dir"])]


def test_reasonsets_compare_modes_and_its_modes_are_the_bridges():
    assert rs.MODES == vb.MODES
    one = {("speed", 23)}
    assert rs.compare_modes([(m, set(one)) for m in vb.MODES])["ok"]
    assert not rs.compare_modes([])["ok"]
    unknown = rs.compare_modes([(m, set(one)) for m in vb.MODES] + [("dumpfile", set(one))])
    assert unknown["unknown_modes"] == ["dumpfile"] and not unknown["ok"], "a run of a mode the comparison does not know is refused"


def test_reply_frames_need_every_reply_to_carry_its_frame():
    recs = [{"seq": 2, "frame": "02" * 64}, {"seq": 1, "frame": "01" * 64}]
    assert rs.reply_frames(recs) == [bytes([1]) * 64, bytes([2]) * 64]
    with pytest.raises(ValueError, match="no frame"):
        rs.reply_frames([{"seq": 1}])


# ============================================================ the console and the pause sequences

def _console(*lines):
    return "\n".join(["monitor: vss rules: kind 4, catalog 0x00000000 (vss x), age_max 250 ms, profiles 1 2"] + list(lines)) + "\n"


def test_a_miss_after_the_bridges_last_session_is_not_held_against_the_run():
    v = step3.console_view(_console("monitor: client done: seen=5 accepted=5 rejected=0",
                                    "monitor: LIVENESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)"))
    assert not any(v["during"].values()) and v["after_last_session"]["miss"] == 1
    v = step3.console_view(_console("monitor: LIVENESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)",
                                    "monitor: client done: seen=5 accepted=5 rejected=0"))
    assert v["during"]["miss"] == 1


def _pause_run(kind, first=(0, 0, 100), restored_seq=11, miss=True, intake_first=False):
    """A pause run's replies, bridge records and console. intake_first: both, with the intake resumed before the tick."""
    t = iter(range(1, 100))
    records = [{"event": "connect", "t_mono": next(t)}]
    replies = [{"seq": s, "verdict": 0, "reason": 0, "age_ms": 0, "t_mono": next(t)} for s in range(1, 11)]
    if kind == "both":
        records.append({"event": "pause", "what": "intake", "t_mono": next(t)})
    records += [{"event": "pause", "what": "tick", "t_mono": next(t)}, {"event": "closed", "why": "peer closed", "t_mono": next(t)}]
    if kind == "both" and intake_first:
        records.append({"event": "resume", "what": "intake", "t_mono": next(t)})
    records += [{"event": "resume", "what": "tick", "t_mono": next(t)}, {"event": "connect", "t_mono": next(t)}]
    replies.append({"seq": 11, "verdict": first[0], "reason": first[1], "age_ms": first[2], "t_mono": next(t)})
    if kind == "both" and not intake_first:
        records.append({"event": "resume", "what": "intake", "t_mono": next(t)})
    replies.append({"seq": 12, "verdict": 0, "reason": 0, "age_ms": 0, "t_mono": next(t)})
    lines = ["monitor: client done: seen=0 accepted=0 rejected=0"]
    if miss:
        lines.append("monitor: LIVENESS MISS: no claim for 500 ms since seq=10 (deadline 500 ms, miss 1)")
    lines += ["monitor: client closed: no complete frame for 500 ms", "monitor: client done: seen=10 accepted=10 rejected=0",
              "monitor: LIVENESS RESTORED: seq=%d after 1600 ms without a claim" % restored_seq]
    return replies, records, lines


@pytest.mark.parametrize("kind, first", [("tick", (0, 0, 40)), ("both", (1, STALE, 1600))])
def test_the_pause_sequences_of_spec_14_4(kind, first):
    replies, records, lines = _pause_run(kind, first)
    res = step3.pause_sequence(kind, replies, records, lines, C.AGE_MAX_MS)
    assert res["ok"], res
    for bad in (dict(miss=False), dict(restored_seq=12)):
        r2 = step3.pause_sequence(kind, *_pause_run(kind, first, **bad), C.AGE_MAX_MS)
        assert not r2["ok"], (bad, r2)
    wrong = (1, STALE, 1600) if kind == "tick" else (0, 0, 40)
    assert not step3.pause_sequence(kind, *_pause_run(kind, wrong), C.AGE_MAX_MS)["checks"]["first_after_resume"]


def _failed(res):
    return [k for k, v in res["checks"].items() if not v]


def test_pause_both_fails_with_the_intake_resumed_before_the_tick_or_a_first_22_no_older_than_age_max():
    """Spec 14.4's both-paused sequence, one check at a time: the tick resumes first, and the first frame after it is a
    22 whose age is above AGE_MAX (22 is age > AGE_MAX: an age at the limit is accepted, spec 6)."""
    first = (1, STALE, C.AGE_MAX_MS + 1)
    assert step3.pause_sequence("both", *_pause_run("both", first), C.AGE_MAX_MS)["ok"]
    r = step3.pause_sequence("both", *_pause_run("both", first, intake_first=True), C.AGE_MAX_MS)
    assert not r["ok"] and _failed(r) == ["intake_resumed_after_the_tick"], r
    r = step3.pause_sequence("both", *_pause_run("both", (1, STALE, C.AGE_MAX_MS)), C.AGE_MAX_MS)
    assert not r["ok"] and _failed(r) == ["first_after_resume"], r


# ============================================================ the judge's gates, each made to fail

ORIGIN = 10**18
PAUSE_TICK = dict(INJECTED, steps=[{"at_ns": 500 * MS, "call": "pause_tick"}, {"at_ns": 2_000 * MS, "call": "resume_tick"}], sequence="tick")


def _summary(plan, drop=0, lost=0):
    """A bridge summary that passes every summary gate of the plan's run, but for the drop and lost counters given."""
    n = len(plan["script"]["steps"])
    return {"counters": {"drop": drop, "lost_on_reconnect": lost}, "identity": {"holds": True}, "ticks_identity": {"holds": True},
            "seq_partition": {"holds": True}, "fatal": None, "r21_uninjected": 0,
            "script": {"error": None, "done": n, "steps": n, "ended_run": True}}


@pytest.mark.parametrize("spec", [INJECTED, PAUSE_TICK], ids=["no-pause", "pause"])
def test_the_accounting_gate_wants_drop_0_and_lost_0_in_every_run_a_pause_run_included(spec):
    """The plan's exit: drop = 0 and lost_on_reconnect = 0 in every actual run. A drop the bridge calls `paused` is
    reported by its why, and fails the gate like any other."""
    plan = step3.plan_run(synth_doc(), "x", spec, "replay")

    def judged(drop=0, lost=0, records=()):
        return step3.judge(plan, [], list(records), _summary(plan, drop, lost), "", {"recording": 0, "script": 0}, {}, C.AGE_MAX_MS)
    good = judged()
    assert good["gates"]["accounting"] and good["gates"]["script"] and good["drops_by_why"] == {}
    assert not judged(lost=1)["gates"]["accounting"]
    paused = judged(drop=1, records=[{"event": "dropped", "seq": 7, "why": "paused"}])
    assert not paused["gates"]["accounting"] and paused["drops_by_why"] == {"paused": 1}, "a paused drop is a finding, not exempt"
    assert not judged(drop=1, records=[{"event": "dropped", "seq": 7, "why": "stop"}])["gates"]["accounting"]
    assert not judged(drop=1)["gates"]["accounting"], "the counter decides, with or without its record"


def _live_drive(plan, off_ns, how=None, ok=True):
    """drive_live's record of a stop issued at ORIGIN + off_ns (how: the realisation the stack's call names)."""
    return {"origin_ns": ORIGIN, "stop": {"issued_ns": ORIGIN + off_ns, "returned_ns": ORIGIN + off_ns + MS, "ok": ok,
                                          "how": plan["stop"]["how"] if how is None else how, "due_ns": ORIGIN + plan["stop"]["call_offset_ns"]}}


@pytest.mark.parametrize("mode", ["can", "broker"])
def test_the_live_stop_gate_wants_the_planned_realisation_issued_within_the_tick_before_s(mode):
    plan = step3.plan_run(synth_doc(stop_ns=3_700 * MS), "x", INJECTED, mode)
    s, half = plan["stop"]["at_offset_ns"], plan["stop"]["call_offset_ns"]
    origins = {"recording": ORIGIN, "script": ORIGIN}

    def ok(drive, records=()):
        return step3.stop_evidence(plan, drive, list(records), origins)["ok"]
    assert ok(_live_drive(plan, half)) and ok(_live_drive(plan, s - TICK)) and ok(_live_drive(plan, s - 1)), "the tick before S"
    for off in (s, s + 1, s + TICK, s - TICK - 1, 0):
        assert not ok(_live_drive(plan, off)), "issued at %d ns, S %d" % (off, s)
    other = {"can": "can-provider", "broker": "player"}[mode]
    assert not ok(_live_drive(plan, half, how=other)), "the other live mode's realisation"
    assert not ok(_live_drive(plan, half, how="intake")) and not ok(_live_drive(plan, half, ok=False)), "replay's, or a failed call"
    assert not ok({"origin_ns": ORIGIN, "stop": None}) and not ok(dict(_live_drive(plan, half), origin_ns=None)), "none made, or no origin"
    assert not ok(_live_drive(plan, half), [{"event": "script-step", "call": "pause_intake", "at_ns": half, "done_ns": ORIGIN + half}]), \
        "a live run's bridge pauses nothing"
    late = step3.judge(plan, [], [], None, "", origins, _live_drive(plan, s), C.AGE_MAX_MS)
    assert not late["gates"]["stop"] and late["stop"]["issued_offset_ns"] == s


def test_the_replay_stop_gate_wants_the_intake_pause_done_between_the_deliveries_at_s_minus_tick_and_s():
    plan = step3.plan_run(synth_doc(stop_ns=3_700 * MS), "x", INJECTED, "replay")
    s, half, a = plan["stop"]["at_offset_ns"], plan["stop"]["call_offset_ns"], 5 * 10**12

    def ok(done_off, drive=None, at=None):
        rec = [{"event": "script-step", "call": "pause_intake", "at_ns": half if at is None else at, "done_ns": a + done_off}]
        return step3.stop_evidence(plan, drive or {}, rec, {"recording": a, "script": a})["ok"]
    assert ok(half) and ok(s - TICK + 1) and ok(s - 1)
    for off in (s - TICK, s, s + 1, s + TICK // 2, s - 2 * TICK):
        assert not ok(off), "done at %d ns, S %d" % (off, s)
    assert not ok(half, at=half + 1), "not the planned step"
    assert not ok(half, drive={"origin_ns": a, "stop": {"how": "intake", "ok": True, "issued_ns": a + half}}), "replay's stop is the bridge's"
    assert not step3.stop_evidence(plan, {}, [], {"recording": a, "script": a})["ok"], "no step done"
    assert not step3.stop_evidence(plan, {}, [], {"recording": None, "script": None})["ok"], "no anchor"


@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_a_to_end_run_that_makes_any_stop_fails_its_stop_gate(mode):
    plan = step3.plan_run(synth_doc(), "x", TO_END, mode)
    o = {"recording": ORIGIN, "script": ORIGIN}
    assert step3.stop_evidence(plan, {"origin_ns": ORIGIN, "stop": None}, [], o)["ok"]
    assert not step3.stop_evidence(plan, {"origin_ns": ORIGIN, "stop": {"issued_ns": ORIGIN, "ok": True, "how": "player"}}, [], o)["ok"]
    assert not step3.stop_evidence(plan, {}, [{"event": "script-step", "call": "pause_intake", "at_ns": 0, "done_ns": ORIGIN}], o)["ok"]


def _bus_log(ms=5_000, every_ms=10):
    """A candump log as bridge_sources.read_candump gives it (us, id, data): a frame every every_ms, each one distinct."""
    return [(1_700_000_000_000_000 + i * every_ms * 1000, 0x100 + i % 2, bytes([i % 256, i // 256]) + bytes(6)) for i in range(ms // every_ms + 1)]


@pytest.mark.parametrize("mode, run", [("broker", "stop"), ("broker", "to_end"), ("can", "to_end")])
def test_the_bus_gate_wants_every_frame_of_the_log_in_order(mode, run):
    """A player that was not stopped (broker's stop is the provider's): the whole log, in order, once."""
    plan = step3.plan_run(synth_doc(stop_ns=3_700 * MS), "x", dict(INJECTED, run=run), mode)
    log = _bus_log()
    frames = [(c, d) for _t, c, d in log]
    assert step3.bus_check(plan, frames, log)["ok"]
    for what, bad in [("the last frame missing", frames[:-1]), ("one frame missing", frames[:10] + frames[11:]),
                      ("two frames reordered", frames[:10] + [frames[11], frames[10]] + frames[12:]), ("a frame twice", frames + frames[-1:]),
                      ("one frame's data", frames[:10] + [(frames[10][0], bytes(8))] + frames[11:]), ("none", [])]:
        assert not step3.bus_check(plan, bad, log)["ok"], what


def test_the_bus_gate_for_a_stopped_player_wants_a_prefix_of_the_log_ending_inside_the_tick_before_s():
    plan = step3.plan_run(synth_doc(stop_ns=3_700 * MS), "x", INJECTED, "can")
    s, every = plan["stop"]["at_offset_ns"], 10 * MS
    log = _bus_log()
    frames = [(c, d) for _t, c, d in log]

    def before(off_ns):
        """the frames sent before off_ns"""
        return frames[:-(-off_ns // every)]
    assert step3.bus_check(plan, before(plan["stop"]["call_offset_ns"]), log)["ok"]
    assert step3.bus_check(plan, before(s), log)["ok"] and step3.bus_check(plan, before(s - TICK), log)["ok"], "the tick's ends"
    r = step3.bus_check(plan, before(s - TICK - every), log)
    assert not r["ok"] and r["first_unsent_offset_ns"] == s - TICK - every, "it ends before the tick before S"
    r = step3.bus_check(plan, before(s + 1), log)
    assert not r["ok"] and r["last_sent_offset_ns"] == s, "a frame at S was sent"
    assert not step3.bus_check(plan, frames, log)["ok"] and not step3.bus_check(plan, [], log)["ok"], "the whole log, or nothing"
    gap = before(s - TICK // 2)
    r = step3.bus_check(plan, gap[:100] + gap[101:] + [frames[len(gap)]], log)
    assert not r["ok"] and not r["prefix_of_log"], "one frame missing inside the prefix"


def test_the_console_gate_of_a_run_without_a_pause_fails_on_a_miss_close_or_restored_before_the_last_session_ends():
    plan = step3.plan_run(synth_doc(), "x", INJECTED, "replay")
    done = "monitor: client done: seen=5 accepted=5 rejected=0"
    lines = {"miss": "monitor: LIVENESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)",
             "closed_silent": "monitor: client closed: no complete frame for 500 ms",
             "closed_untaken": "monitor: client closed: reply not taken for 500 ms",
             "restored": "monitor: LIVENESS RESTORED: seq=6 after 600 ms without a claim"}

    def console_gate(*ls):
        return step3.judge(plan, [], [], None, _console(*ls), {"recording": 0, "script": 0}, {}, C.AGE_MAX_MS)["gates"]["console"]
    assert console_gate(done) and console_gate(done, lines["miss"]), "a MISS after the last session is the monitor outliving the bridge"
    for what, ln in lines.items():
        assert not console_gate(ln, done), "%s before the last session ends" % what
        assert not console_gate(done, ln, done), "%s between two sessions" % what


# ============================================================ whole runs as the judge reads them: the pause runs, the summary

def _reply(seq, off_ns, verdict=0, reason=0, age_ms=0):
    """A reply record at off_ns on the run's origin (ORIGIN); replay's t_mono and src_now_ns are on one clock."""
    return {"seq": seq, "src_now_ns": ORIGIN + off_ns, "t_mono": ORIGIN + off_ns, "verdict": verdict, "reason": reason, "age_ms": age_ms}


def _rec(event, off_ns, **kw):
    return dict(kw, event=event, t_mono=ORIGIN + off_ns)


def _step(call, at_ns):
    return _rec("script-step", at_ns, call=call, at_ns=at_ns, due_ns=ORIGIN + at_ns, done_ns=ORIGIN + at_ns)


def _honest_30s():
    """A 30 s honest file's events doc (no events file: its to_end run only, R at 30 s)."""
    return synth_doc(stop_ns=25_000 * MS, last_ns=30_000 * MS, events_file=False)


def _end_replies(plan, seq):
    """After the file's end: a 22 at R (the end window), at the end-held window's start and at run_through_ns (the last
    reply: the run ticked through)."""
    w = {x["event"]: x for x in plan["windows"]}
    offs = [w["end"]["t0_ns"], w["end-held"]["t0_ns"], plan["run_through_ns"]]
    return [_reply(seq + i, o, 1, STALE, C.AGE_MAX_MS + 1 + i * 100) for i, o in enumerate(offs)]


def _end_records(plan):
    """The script's end step, then the bridge's own close at its stop (every run that ends connected logs one)."""
    return [_step("end", plan["end_offset_ns"]), _rec("closed", plan["end_offset_ns"] + MS, why="stop", outstanding=None)]


def _judge_files(plan, replies, records, summary, console):
    return step3.judge(plan, replies, records, summary, console, {"recording": ORIGIN, "script": ORIGIN}, {}, C.AGE_MAX_MS)


def _failing(res):
    return [g for g, v in res["gates"].items() if not v]


def _pause_files(plan, tick_pause="ok", misses=1, silences=1, peer_closes=1, connects=2, restored="after", restored_seq=11,
                 first=None, intake="after", accept_again=True):
    """A replay pause run's replies, bridge records and console, laid out as final3's pause runs' files are (spec 14.4):
    ten ACCEPTs, the pause (for both, the intake's at the same instant), the monitor's MISS and its close for silence,
    the bridge seeing that close ('peer closed'), the tick's resume, the reconnect, the first frame (tick: ACCEPT;
    both: 22 above AGE_MAX, then 22 until the intake resumes, then ACCEPT), RESTORED naming it in the console's second
    session, the 22s after the file's end, the script's end and the bridge's own close at its stop. Each keyword
    breaks one part: tick_pause "none" (no tick pause record) or "resume_first" (the tick's resume record before its
    pause); misses, silences (closes for silence), peer_closes (the bridge's 'peer closed' records) and connects as
    counts; restored "before" (the close) or "none"; restored_seq; first (verdict, reason, age_ms); intake "first" (both:
    the intake resumed before the tick); accept_again False (both: no ACCEPT once the intake runs)."""
    kind = plan["sequence"]
    at = {s["call"]: s["at_ns"] for s in plan["script"]["steps"]}
    p, r = at["pause_tick"], at["resume_tick"]
    records = [_rec("replay-anchored", 0, anchor_ns=ORIGIN), _rec("script-origin", 0, origin_ns=ORIGIN), _rec("connect", 18_950 * MS)]
    replies = [_reply(s, (18_900 + 100 * s) * MS) for s in range(1, 11)]
    if kind == "both":
        records += [_rec("pause", at["pause_intake"], what="intake"), _step("pause_intake", at["pause_intake"])]
    if tick_pause != "none":
        records.append(_rec("pause", p + 1, what="tick"))
    records.append(_step("pause_tick", p + 1))
    whys = ["peer closed", "peer-closed (seen before a send)"]
    records += [_rec("closed", p + 425 * MS + i, why=whys[i % 2], outstanding=None) for i in range(peer_closes)]
    records += [_rec("resume", 19_950 * MS if tick_pause == "resume_first" else r, what="tick"), _step("resume_tick", r)]
    if kind == "both":
        records += [_rec("resume", r - 25 * MS if intake == "first" else at["resume_intake"], what="intake"),
                    _step("resume_intake", at["resume_intake"])]
    records += [_rec("connect", r + 25 * MS) for _ in range(min(connects, 2) - 1)] + [_rec("connect", 25_000 * MS)] * (connects - 2)
    want = (0, 0, 0) if kind == "tick" else (1, STALE, 1_575)
    v, why, age = first or want
    replies.append(_reply(11, r + 75 * MS, v, why, age))
    replies.append(_reply(12, r + 175 * MS) if kind == "tick" else _reply(12, r + 175 * MS, 1, STALE, 1_675))
    replies.append(_reply(13, r + 275 * MS) if accept_again else _reply(13, r + 275 * MS, 1, STALE, 1_775))
    replies += _end_replies(plan, 14)
    records += _end_records(plan)
    miss = "monitor: LIVENESS MISS: no claim for 500 ms since seq=10 (deadline 500 ms, miss %d)"
    silence = "monitor: client closed: no complete frame for 500 ms"
    back = "monitor: LIVENESS RESTORED: seq=%d after 1600 ms without a claim" % restored_seq
    lines = [miss % (i + 1) for i in range(misses)] + ([back] if restored == "before" else []) + [silence] * silences
    lines += ["monitor: client done: seen=10 accepted=10 rejected=0"] + ([back] if restored == "after" else [])
    lines += ["monitor: client done: seen=6 accepted=3 rejected=3",
              "monitor: LIVENESS MISS: no claim for 501 ms since seq=16 (deadline 500 ms, miss %d)" % (misses + 1)]
    return replies, records, _console(*lines)


def _pause_plan(kind):
    return step3.plan_run(_honest_30s(), "pause-" + kind, step3.load_specs()["pause-" + kind], "replay")


def test_the_judges_peer_close_whys_are_the_bridges_and_its_stop_is_not_one():
    """bridge_saw_the_close counts only the closes the bridge logs when the peer closed; the strings are the bridge's own."""
    src = (REPO / "sdv" / "bridge" / "vss_claim_bridge.py").read_text(encoding="utf-8")
    assert step3.PEER_CLOSE_WHY and all('self._close("%s")' % why in src for why in step3.PEER_CLOSE_WHY), step3.PEER_CLOSE_WHY
    assert 'self._close("stop" if self.fatal is None else "fatal")' in src and not {"stop", "fatal"} & set(step3.PEER_CLOSE_WHY)


@pytest.mark.parametrize("kind", ["tick", "both"])
def test_a_pause_run_whose_files_hold_spec_14_4s_sequence_passes_every_gate(kind):
    """The spec file's pause plan, judged on files laid out as a real pause run's (the bridge's own close at its stop
    included): every gate holds, the console's by the sequence."""
    plan = _pause_plan(kind)
    replies, records, console = _pause_files(plan)
    res = _judge_files(plan, replies, records, _summary(plan), console)
    assert res["ok"] and res["gates"]["console"] and res["pause_sequence"]["ok"], (_failing(res), res["pause_sequence"], res["reason_set"])
    assert res["pause_sequence"]["first_after_resume"]["seq"] == 11 and res["pause_sequence"]["restored"][0][1] == 11


_BOTH_KINDS = [
    ("the tick's resume before its pause", dict(tick_pause="resume_first"), ["one_tick_pause_and_resume"]),
    # the bridge's close is looked for after the tick's pause: with no pause record there is no "after"
    ("no tick pause record", dict(tick_pause="none"), ["one_tick_pause_and_resume", "bridge_saw_the_close"]),
    ("no MISS", dict(misses=0), ["one_miss", "miss_then_close"]),
    ("two MISS", dict(misses=2), ["one_miss"]),
    ("no close for silence", dict(silences=0), ["one_close_for_silence", "miss_then_close", "one_restored_after_the_close"]),
    ("two closes for silence", dict(silences=2), ["one_close_for_silence"]),
    ("the bridge never saw the close (only its own at the stop)", dict(peer_closes=0), ["bridge_saw_the_close"]),
    ("the bridge saw two closes", dict(peer_closes=2), ["bridge_saw_the_close"]),
    ("one connect (no reconnect)", dict(connects=1), ["one_reconnect"]),
    ("three connects (two reconnects)", dict(connects=3), ["one_reconnect"]),
    ("RESTORED before the close", dict(restored="before"), ["one_restored_after_the_close"]),
    ("no RESTORED", dict(restored="none"), ["one_restored_after_the_close", "restored_names_it"]),
    ("RESTORED naming another frame", dict(restored_seq=12), ["restored_names_it"]),
]
_PAUSE_BREAKS = [("tick", what, kw, checks, ["console"]) for what, kw, checks in _BOTH_KINDS] + \
    [("both", what, kw, checks, ["console"]) for what, kw, checks in _BOTH_KINDS] + [
    # a 22 outside every window of the tick-only plan is also an unexpected (None, 22)
    ("tick", "the first frame after the resume a 22", dict(first=(1, STALE, 1_575)), ["first_after_resume"], ["reason_set", "console"]),
    ("both", "the first frame after the resume ACCEPTed", dict(first=(0, 0, 0)), ["first_after_resume"], ["console"]),
    # (the contract's AGE_MAX is read in the test: C may be absent at collection)
    ("both", "the first 22's age at AGE_MAX, not above", dict(first=(1, STALE, "AGE_MAX")), ["first_after_resume"], ["console"]),
    ("both", "the intake resumed before the tick", dict(intake="first"), ["intake_resumed_after_the_tick"], ["console"]),
    ("both", "no ACCEPT once the intake resumed", dict(accept_again=False), ["accepted_again"], ["console"]),
]


@pytest.mark.parametrize("kind, what, brk, checks, gates", _PAUSE_BREAKS, ids=["%s: %s" % (b[0], b[1]) for b in _PAUSE_BREAKS])
def test_each_check_of_a_pause_sequence_fails_its_run_on_its_own(kind, what, brk, checks, gates):
    """One part of spec 14.4's sequence broken at a time, in the files of a run that otherwise passes every gate: the
    judge's pause_sequence fails exactly the checks named, and the run fails its console gate (and nothing else, but for
    a reason set that the break itself changes)."""
    plan = _pause_plan(kind)
    if brk.get("first") == (1, STALE, "AGE_MAX"):
        brk = dict(brk, first=(1, STALE, C.AGE_MAX_MS))
    replies, records, console = _pause_files(plan, **brk)
    res = _judge_files(plan, replies, records, _summary(plan), console)
    assert _failed(res["pause_sequence"]) == checks, (what, res["pause_sequence"])
    assert not res["pause_sequence"]["ok"] and _failing(res) == gates and not res["ok"], (what, _failing(res))


def _plain_run():
    """The honest spec on a 30 s file, judged on files that pass every gate: two ACCEPTs, the 22s after the file's end
    through run_through_ns, the script's end, the bridge's close at its stop, one session on the console."""
    plan = step3.plan_run(_honest_30s(), "honest", step3.load_specs()["honest"], "replay")
    replies = [_reply(1, 1_000 * MS), _reply(2, 1_100 * MS)] + _end_replies(plan, 3)
    return plan, replies, _end_records(plan), _console("monitor: client done: seen=5 accepted=2 rejected=3")


_SUMMARY_BREAKS = [
    ("packed != replied + drop + lost", lambda s: s["identity"].update(holds=False), ["identity"]),
    ("ticks != packed + ticks_empty", lambda s: s["ticks_identity"].update(holds=False), ["identity"]),
    ("the seqs not partitioned", lambda s: s["seq_partition"].update(holds=False), ["identity"]),
    ("a script step not done", lambda s: s["script"].update(done=s["script"]["steps"] - 1), ["script"]),
    ("another script (one step more, all done)", lambda s: s["script"].update(done=s["script"]["steps"] + 1, steps=s["script"]["steps"] + 1),
     ["script"]),
    ("the script did not end the run", lambda s: s["script"].update(ended_run=False), ["script"]),
    ("a script error", lambda s: s["script"].update(error="step 1 (end): RuntimeError"), ["script"]),
    ("a fatal", lambda s: s.update(fatal="RuntimeError: boom"), ["no_fatal"]),
    ("an uninjected 21", lambda s: s.update(r21_uninjected=1), ["no_uninjected_21"]),
    ("one drop", lambda s: s["counters"].update(drop=1), ["accounting"]),
    ("one lost on reconnect", lambda s: s["counters"].update(lost_on_reconnect=1), ["accounting"]),
    ("no summary.json", None, ["identity", "no_fatal", "no_uninjected_21", "accounting", "script"]),
]


@pytest.mark.parametrize("what, brk, gates", _SUMMARY_BREAKS, ids=[b[0] for b in _SUMMARY_BREAKS])
def test_each_summary_field_fails_only_its_own_gate(what, brk, gates):
    """The bridge's summary, one field broken at a time, in a run that otherwise passes every gate; a run that left no
    summary fails every gate read from it."""
    plan, replies, records, console = _plain_run()
    good = _judge_files(plan, replies, records, _summary(plan), console)
    assert good["ok"], (_failing(good), good["reason_set"])
    summary = None
    if brk is not None:
        summary = _summary(plan)
        brk(summary)
    res = _judge_files(plan, replies, records, summary, console)
    assert _failing(res) == gates and not res["ok"], (what, _failing(res))


# ============================================================ the bridge's script

@pytest.mark.parametrize("doc, match", [
    ({"steps": []}, "format"),
    ({"format": 1, "steps": [{"at_ns": 0, "call": "explode"}]}, "not one of"),
    ({"format": 1, "steps": [{"at_ns": -1, "call": "pause_tick"}]}, "int >= 0"),
    ({"format": 1, "steps": [{"at_ns": 2, "call": "pause_tick"}, {"at_ns": 1, "call": "resume_tick"}]}, "in order"),
    ({"format": 1, "steps": [{"at_ns": 1, "call": "end"}, {"at_ns": 2, "call": "pause_tick"}]}, "end is the last"),
    ({"format": 1, "steps": [{"at_ns": 1, "call": "inject", "mode": "fire", "frames": 1}]}, "injection"),
    ({"format": 1, "steps": [{"at_ns": 1, "call": "inject", "mode": "nan", "frames": 0}]}, "frames"),
    ({"format": 1, "steps": [{"at_ns": 1, "call": "pause_tick", "frames": 1}]}, "keys"),
    ({"format": 1, "steps": [{"at_ns": True, "call": "pause_tick"}]}, "int >= 0"),
])
def test_a_malformed_script_is_refused(doc, match):
    with pytest.raises(vb.BridgeError, match=match):
        vb.parse_script(doc)


def test_a_script_with_any_control_call_is_refused_on_the_stamp_port(tmp_path):
    lock = str(tmp_path / "lock")
    steps = vb.parse_script({"format": 1, "steps": [{"at_ns": 0, "call": "pause_tick"}, {"at_ns": 1, "call": "end"}]})
    with pytest.raises(vb.BridgeError, match="stamp port"):
        vb.Bridge(tsb.cfg(vb.STAMP_PORT, lock_path=lock), vb.QueueSource(), contract=C, script=steps)
    vb.Bridge(tsb.cfg(vb.STAMP_PORT, lock_path=lock), vb.QueueSource(), contract=C,
              script=vb.parse_script({"format": 1, "steps": [{"at_ns": 1, "call": "end"}]}))


def test_the_script_runs_from_the_first_held_update_and_its_end_ends_the_run(tmp_path):
    """A source with no origin of its own: the script's origin is the first held update's age-source timestamp, every
    step runs at origin + at_ns on the source's clock, an inject step injects, and the end step calls on_end."""
    mon = tsb.FakeMonitor(tsb.accept_all)
    ended = threading.Event()
    src = vb.QueueSource()
    steps = vb.parse_script({"format": 1, "steps": [{"at_ns": 300 * MS, "call": "inject", "mode": "nan", "frames": 1},
                                                    {"at_ns": 600 * MS, "call": "end"}]})
    b = vb.Bridge(tsb.cfg(mon.port, lock_path=str(tmp_path / "lock")), src, contract=C, script=steps, on_end=ended.set).start()
    try:
        t0 = time.monotonic_ns() - 5 * MS
        src.push(*[vb.Update(i, v, t0) for i, v in enumerate((5.0, 0.0, 0.0, 0.0, 1))])
        assert ended.wait(5.0), "the end step ends the run"
    finally:
        s = b.stop()
        mon.close()
    assert [r["origin_ns"] for r in b.log.find("script-origin")] == [t0]
    done = b.log.find("script-step")
    assert [(r["call"], r["due_ns"]) for r in done] == [("inject", t0 + 300 * MS), ("end", t0 + 600 * MS)]
    assert all(0 <= r["done_ns"] - r["due_ns"] < 200 * MS for r in done), done
    assert [r["seq"] for r in b.replies.records if r.get("inject") == "nan"], "the inject step injected a frame"
    assert s["script"] == dict(s["script"], steps=2, done=2, ended_run=True, error=None, origin_ns=t0)
    assert s["identity"]["holds"] and s["threads"]["script_alive"] is False


def _replay_run(tmp_path, capsys, plan, drop_calls=()):
    """bridge_sources.py's command line in replay mode on an honest file as long as the plan's file (its file_end_ns),
    with the plan's script (less drop_calls), against a Python peer that answers with the reference judge."""
    log = tsbs.candump(tsbs.trip(plan["file_end_ns"] // MS, vary=False), tmp_path / "sigsim.log")
    script = dict(plan["script"], steps=[s for s in plan["script"]["steps"] if s["call"] not in drop_calls])
    sp = tmp_path / "script.json"
    sp.write_text(json.dumps(script), encoding="utf-8")
    tables = tsf.tables()
    mon = tsb.FakeMonitor(lambda f: rules.reply(f, tables))
    out = tmp_path / ("run-" + "-".join(drop_calls or ("all",)))
    try:
        code, _o, err = tsbs.run_cli(tsbs.argv_for("replay", mon.port, out, tmp_path / "lock", "--log", str(log), "--script", str(sp)),
                                     tsbs.Opens(), capsys)
    finally:
        mon.close()
    assert code == 0, err
    replies = [r for r in tsbs.jsonl(out / "replies.jsonl") if r["event"] == "reply"]
    records = tsbs.jsonl(out / "bridge.jsonl")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    anchor = rs.replay_anchor(records)
    so = [r["origin_ns"] for r in records if r["event"] == "script-origin"]
    return types.SimpleNamespace(replies=replies, records=records, summary=summary, anchor=anchor, script_origin=so, frames=mon.frames)


def test_a_replay_run_realises_the_stop_by_its_script_and_ticks_through_run_through(tmp_path, capsys):
    """End to end in process: the plan's script, in the bridge's replay mode, pauses the intake between the deliveries at
    S - tick and S and ends the run one tick past run_through_ns; the judge passes every gate it holds. The file runs on
    well past that end, so a run ended at the file's end (or at any instant but run_through_ns + tick) fails here."""
    doc = synth_doc(stop_ns=1_000 * MS, last_ns=3_000 * MS)
    plan = step3.plan_run(doc, "syn-stop", INJECTED, "replay")
    assert plan["end_offset_ns"] + 5 * TICK <= plan["file_end_ns"], plan
    r = _replay_run(tmp_path, capsys, plan)
    assert r.script_origin == [r.anchor], "replay's script origin is the grid's anchor"
    origins = {"recording": r.anchor, "script": r.anchor}
    res = step3.judge(plan, r.replies, r.records, r.summary, "", origins, {}, C.AGE_MAX_MS)
    assert res["ok"], (res["gates"], res["reason_set"], res["stop"])
    s = plan["stop"]["at_offset_ns"]
    offs = [(x["src_now_ns"] - r.anchor, x) for x in r.replies]
    first22 = next(o for o, x in offs if x["verdict"])
    assert all(not x["verdict"] for o, x in offs if o < first22) and all(x["reason"] == STALE for o, x in offs if o >= first22)
    assert s <= first22 <= s + C.AGE_MAX_MS * MS + TICK, first22
    assert offs[-1][0] == plan["run_through_ns"], "the last tick is at run_through_ns, then the end step"
    assert s - TICK < res["stop"]["done_offset_ns"] < s
    assert rs.reply_frames(r.replies) == r.frames, "each reply record carries the frame the peer received"


def test_the_same_replay_run_without_its_stop_step_lacks_stop_22(tmp_path, capsys):
    doc = synth_doc(stop_ns=1_000 * MS, last_ns=3_000 * MS)
    plan = step3.plan_run(doc, "syn-stop", INJECTED, "replay")
    r = _replay_run(tmp_path, capsys, plan, drop_calls=("pause_intake",))
    res = step3.judge(plan, r.replies, r.records, r.summary, "", {"recording": r.anchor, "script": r.anchor}, {}, C.AGE_MAX_MS)
    assert not res["gates"]["reason_set"] and not res["gates"]["stop"]
    assert ["stop", STALE] in res["reason_set"]["missing"], res["reason_set"]


# ============================================================ a run_through_ns off the tick grid (SDV Phase 7 F-THROUGH)

def _first_grid_at_or_past(t_ns):
    """The first instant of the tick grid at or past t_ns, worked out here without the plan's own arithmetic."""
    below = t_ns - t_ns % TICK
    return below if below == t_ns else below + TICK


def _through_doc(through_ns, run="to_end", events_file=True):
    """A synthetic events document whose `run` run has through_ns for its run_through_ns, set as given (plan_run takes it
    from the doc as it is)."""
    doc = synth_doc(events_file=events_file)
    doc["runs"][run]["run_through_ns"] = through_ns
    return doc


# (run_through_ns, the end the rule gives): off the grid, the first grid instant at or past it plus one tick; on it, one
# tick after it, as before
END_RULE = [
    pytest.param(300_920 * MS, 301_100 * MS, id="carla-honest"),        # record-derived case; off the grid
    pytest.param(300_900 * MS + 1, 301_100 * MS, id="1ns-past"),
    pytest.param(301_000 * MS - 1, 301_100 * MS, id="1ns-before"),
    pytest.param(300_950 * MS, 301_100 * MS, id="half-tick-past"),
    pytest.param(300_970 * MS, 301_100 * MS, id="70ms-past"),
    pytest.param(3_000 * MS + 1, 3_200 * MS, id="just-past-3s"),
    pytest.param(300_900 * MS, 301_000 * MS, id="on-grid"),
    pytest.param(45_900 * MS, 46_000 * MS, id="sigsim-to-end"),
    pytest.param(38_400 * MS, 38_500 * MS, id="sigsim-stop"),
    pytest.param(288_200 * MS, 288_300 * MS, id="carla-stop"),
]


@pytest.mark.parametrize("run", ["stop", "to_end"])
@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
@pytest.mark.parametrize("through, end", END_RULE)
def test_the_end_is_a_tick_past_the_first_grid_instant_at_or_past_run_through(through, end, mode, run):
    plan = step3.plan_run(_through_doc(through, run), "x", dict(INJECTED, run=run), mode)
    assert plan["run_through_ns"] == through and plan["end_offset_ns"] == end, (through, plan["end_offset_ns"])
    assert plan["script"]["steps"][-1] == {"at_ns": end, "call": "end"} and end % TICK == 0
    assert end == _first_grid_at_or_past(through) + TICK
    if through % TICK == 0:
        assert end == through + TICK, "on the grid: one tick after run_through_ns, as before"


def test_a_step_at_or_after_the_end_is_refused_in_the_same_words_and_one_before_it_taken():
    """A step before the planned end is taken; one at or after it is refused. The final step must be judged,
    rather than only the first one."""
    doc = _through_doc(300_920 * MS, events_file=False)
    spec = {"what": "t", "recording": "honest", "run": "to_end", "steps": [{"at_ns": 301_000 * MS, "call": "pause_tick"}]}
    plan = step3.plan_run(doc, "x", spec, "replay")
    assert plan["script"]["steps"] == [{"at_ns": 301_000 * MS + TICK // 4, "call": "pause_tick"}, {"at_ns": 301_100 * MS, "call": "end"}]
    spec["steps"] = [{"at_ns": TICK, "call": "pause_tick"}, {"at_ns": 301_100 * MS, "call": "resume_tick"}]
    msg = "spec x: a step at %d ns comes at or after the run's end (%d ns)" % (301_100 * MS + TICK // 4, 301_100 * MS)
    with pytest.raises(step3.StepError, match="^%s$" % re.escape(msg)):
        step3.plan_run(doc, "x", spec, "replay")


def _replay_model(plan, lag_ns):
    """The stand-in replay bridge, its replies as the judge's tests model them (_reply, on ORIGIN, the grid anchor): every
    instant g of the recording's tick grid is read lag_ns after it (replay reads it half a tick after it: bridge_sources.py,
    replay) and answered only if that reading comes before the script's end step (on the same origin); ACCEPT while the
    file's last frame is at most AGE_MAX old, then 22 with its age."""
    last, age_max = plan["file_end_ns"], C.AGE_MAX_MS * MS
    out: List[Dict[str, Any]] = []
    g = 0
    while g + lag_ns < plan["end_offset_ns"]:
        stale = g - last > age_max
        out.append(_reply(len(out) + 1, g, int(stale), STALE if stale else 0, (g - last) // MS if stale else 0))
        g += TICK
    return out


def _judged_model(plan, lag_ns):
    """The model's replies judged as a whole run's files: the anchor and script origin, the script's end step and the
    bridge's close at its stop, a summary that passes, one session on the console."""
    replies = _replay_model(plan, lag_ns)
    rej = sum(1 for r in replies if r["verdict"])
    console = _console("monitor: client done: seen=%d accepted=%d rejected=%d" % (len(replies), len(replies) - rej, rej))
    records = [_rec("replay-anchored", 0, anchor_ns=ORIGIN), _rec("script-origin", 0, origin_ns=ORIGIN)] + _end_records(plan)
    return _judge_files(plan, replies, records, _summary(plan), console)


def _todays_end(plan):
    """The plan with the reference end: one tick after run_through_ns, wherever that lies."""
    end = plan["run_through_ns"] + TICK
    return dict(plan, end_offset_ns=end, script=dict(plan["script"], steps=plan["script"]["steps"][:-1] + [{"at_ns": end, "call": "end"}]))


@pytest.mark.parametrize("lag", [TICK // 2, TICK // 2 + MS, 3 * TICK // 4, TICK - 1], ids=["half", "half+1ms", "three-quarters", "tick-1ns"])
@pytest.mark.parametrize("through, end", [pytest.param(300_920 * MS, 301_100 * MS, id="off-grid"),
                                          pytest.param(45_900 * MS, 46_000 * MS, id="on-grid")])
def test_a_replay_reading_each_grid_instant_late_ticks_through_before_the_end(through, end, lag):
    """For an off-grid run-through offset, the model must read the first grid instant at or past it before the end.
    The previous end rule can stop too early, failing only ticked_through. On the grid both rules agree."""
    doc = synth_doc(last_ns=through - inj.run_through_ns(0, C), events_file=False)
    plan = step3.plan_run(doc, "honest", step3.load_specs()["honest"], "replay")
    assert plan["run_through_ns"] == through and plan["end_offset_ns"] == end, (through, plan["end_offset_ns"])
    res = _judged_model(plan, lag)
    assert res["ok"], (_failing(res), res["last_reply_offset_ns"], res["reason_set"])
    assert through <= res["last_reply_offset_ns"] == _first_grid_at_or_past(through) < end
    today = _judged_model(_todays_end(plan), lag)
    if through % TICK:
        assert _failing(today) == ["ticked_through"], (_failing(today), today["reason_set"])
        assert today["last_reply_offset_ns"] == _first_grid_at_or_past(through) - TICK < through
    else:
        assert _todays_end(plan) == plan and today["ok"]


def test_a_replay_run_of_a_file_ending_off_the_grid_ticks_through_before_its_end(tmp_path, capsys):
    """End to end in process, as the stop run above (bridge_sources.py's command line in replay mode, the plan's script, a
    Python peer answering with the reference judge): an honest file whose last frame is 3.02 s from its first has its
    run_through_ns off the grid; the bridge reads the first grid instant at or past it before the script's end step, and
    the judge passes every gate it holds. The reference end (run_through_ns + tick) comes before that instant is read
    (the last reply's tstamp_ns, the clock reading of the tick that packed it, is past that end)."""
    d, line, sha = _honest_dir(tmp_path, ms=3_020)
    plan = step3.plan_run(step3.events_doc(d, sha, line, C), "honest", step3.load_specs()["honest"], "replay")
    through = plan["run_through_ns"]
    assert plan["file_end_ns"] == 3_020 * MS and through % TICK, "run_through_ns off the grid"
    assert plan["end_offset_ns"] == _first_grid_at_or_past(through) + TICK
    r = _replay_run(tmp_path, capsys, plan)
    res = step3.judge(plan, r.replies, r.records, r.summary, "", {"recording": r.anchor, "script": r.anchor}, {}, C.AGE_MAX_MS)
    assert res["ok"], (_failing(res), res["last_reply_offset_ns"], res["reason_set"])
    assert res["last_reply_offset_ns"] == _first_grid_at_or_past(through), "the last tick reads that instant, then the end step"
    # the bridge's start reads the replay clock (the anchor: half a tick later) before its tick loop starts, so a tick reads
    # its grid instant half a tick to a tick after it (bridge_sources.py, ReplaySource._anchor): past run_through_ns + tick,
    # which lies only 20 ms past the instant read last
    assert r.replies[-1]["tstamp_ns"] - r.anchor > through + TICK, "the reference end would have come before the read that ticks through"


def test_the_run_through_text_counts_the_harness_deadline_from_the_script_end_step():
    """The drivers stop a bridge that has not ended itself only END_SLACK_S past the script's end step (origin +
    end_offset_ns + END_SLACK_S: the driver tests above). step3's RUN-THROUGH paragraph and the stack README's
    Run-through bullet say so of that step by name: 'that instant' there would name the instant the sentence before them
    ends on (run_through_ns, or the next grid instant read)."""
    para = " ".join(str(step3.__doc__).split("\nRUN-THROUGH. ", 1)[1].split("\n\n", 1)[0].split())
    readme = (REPO / "sdv" / "stack" / "README.md").read_text(encoding="utf-8")
    bullet = " ".join(readme.split("\n- **Run-through.** ", 1)[1].split("\n- ", 1)[0].split())
    assert "stops it (a failed gate) only END_SLACK_S after the script's end step." in para, para
    assert "stops it (a failed gate) only `END_SLACK_S` past the script's end step." in bullet, bullet


SIGSIM_PAIR = (Path("~/sdv-recordings").expanduser() / "20260930-sigsim-1b", INJ)
NEEDS_SIGSIM_PAIR = pytest.mark.skipif(not all((d / "manifest-line.json").is_file() for d in SIGSIM_PAIR) or
                                       not (SIGSIM_PAIR[1] / "events.json").is_file(),
                                       reason="needs the sigsim pair %s and %s (read only)" % SIGSIM_PAIR)
SIX = ("honest", "inject", "pause-tick", "pause-both", "injected-to-end", "injected-stop")
# _plan_digest of each group of plans (SIX in every mode, in that order), taken with the reference step3.py on the
# original recordings. Regenerate the digest only with that reference and those recordings.
FAD47A99_PLANS = {
    "sigsim": "94d6521eb50e3d7f73da29b9efee5d8da7af8da84598518864efa3324b1a472e",             # every plan, whole
    "carla-stop": "e1855dd6fbfdd79dce3a362727423720888ccd26722210952d430000c8316207",         # the injected-stop plans, whole
    "carla-but-the-end": "05289de4a6a617f931c1deabc99a68d52a5da018e120cea6592070efe01b67fb",  # every plan, less its end
}


def _plan_digest(plans, but_the_end=False):
    """sha256 of the plans' JSON (sorted keys, no spaces), each events file's path reduced to its name; but_the_end: each
    plan without its end_offset_ns and its script's end step."""
    out = []
    for p in plans:
        ef = p["events_file"]
        p = dict(p, events_file=None if ef is None else dict(ef, path=Path(ef["path"]).name))
        if but_the_end:
            p = {k: v for k, v in p.items() if k != "end_offset_ns"}
            p["script"] = dict(p["script"], steps=[s for s in p["script"]["steps"] if s["call"] != "end"])
        out.append(p)
    return hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _pair_plans(pair):
    """SIX in every mode on a recording pair (honest, injected), read as the stack identifies each (read only)."""
    docs = {}
    for kind, d in zip(("honest", "injected"), pair):
        rec = st.recording_identity(d)
        docs[kind] = step3.events_doc(d, rec["sha256"], rec["manifest_line"], C)
    specs = step3.load_specs()
    return [step3.plan_run(docs[specs[n]["recording"]], n, specs[n], m) for n in SIX for m in step3.MODES]


@NEEDS_SIGSIM_PAIR
def test_the_sigsim_pairs_plans_are_fad47a99s_byte_for_byte():
    """The sigsim pair's run-through offsets are on the grid. Every plan matches the reference, with its end one tick
    after the offset."""
    plans = _pair_plans(SIGSIM_PAIR)
    ends = {(p["run"], p["run_through_ns"], p["end_offset_ns"]) for p in plans}
    assert ends == {("to_end", 45_900 * MS, 46_000 * MS), ("stop", 38_400 * MS, 38_500 * MS)}, ends
    assert _plan_digest(plans) == FAD47A99_PLANS["sigsim"]


@NEEDS_CARLA_PAIR
def test_the_carla_pairs_to_end_plans_end_past_the_first_grid_instant_and_its_stop_plans_are_fad47a99s():
    """WP5a's pair: every plan is the reference's but for its end; a to_end run's run_through_ns is off the grid and its end
    a tick past the first grid instant at or past it, which the model reads in replay before the end (with the reference
    end it does not); the stop runs' run_through_ns is on the grid, their plans the reference's byte for byte."""
    plans = _pair_plans(CARLA_PAIR)
    assert _plan_digest(plans, but_the_end=True) == FAD47A99_PLANS["carla-but-the-end"], "nothing but the end moves"
    stops = [p for p in plans if p["run"] == "stop"]
    assert [p["mode"] for p in stops] == list(step3.MODES) and _plan_digest(stops) == FAD47A99_PLANS["carla-stop"]
    for p in plans:
        through, end = p["run_through_ns"], p["end_offset_ns"]
        if p["run"] == "stop":
            assert through % TICK == 0 and end == through + TICK, (p["spec"], p["mode"], through, end)
            continue
        assert through % TICK and end == _first_grid_at_or_past(through) + TICK != through + TICK, (p["spec"], p["mode"], through, end)
        if p["mode"] == "replay":
            for plan, through_ok in ((p, True), (_todays_end(p), False)):
                got = step3.judge(plan, _replay_model(plan, TICK // 2 + MS), [], None, "", {"recording": ORIGIN, "script": ORIGIN}, {},
                                  C.AGE_MAX_MS)
                assert got["gates"]["ticked_through"] is through_ok, (p["spec"], plan["end_offset_ns"], got["last_reply_offset_ns"])


# ============================================================ the stack runs the bridge in can and replay modes

@pytest.mark.parametrize("mode, extra", [("can", ["--channel", "vcan0", "--dbc", "/in/slice.dbc"]),
                                         ("replay", ["--log", "/in/sigsim.log", "--dbc", "/in/slice.dbc"])])
@pytest.mark.parametrize("script", [False, True])
def test_the_stack_runs_the_bridge_in_can_and_replay_modes_with_its_inputs_and_script(tmp_path, monkeypatch, mode, extra, script):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    calls: List[List[str]] = []
    monkeypatch.setattr(st, "docker", lambda *a, **_kw: calls.append(list(a)) or subprocess.CompletedProcess(a, 0, "", ""))
    img = "sha256:" + "ef" * 32
    ctx = types.SimpleNamespace(image_ids=lambda: {attr.BRIDGE: img}, in_dir=tmp_path / "in", bridge=mode)
    rd = tmp_path / "r"
    (rd / "bridge").mkdir(parents=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    if script:
        (rd / st.BRIDGE_SCRIPT).write_text("{}", encoding="utf-8")
    st.start(ctx, attr.BRIDGE, step3.FEED[mode], rd, "test/run")
    args = calls[-1]
    i = args.index(img)
    opts, cmd = args[:i], args[i + 1:]
    assert opts[opts.index("--network") + 1] == "host" and "--read-only" in opts
    assert "%s:/in:ro" % (tmp_path / "in") in opts
    tail = ["--script", "/script.json"] if script else []
    assert cmd == ["run", "--host", "127.0.0.1", "--port", "7160", "--header", "/header.json"] + extra + ["--out", "/out"] + tail
    assert ("%s:/script.json:ro" % (rd / st.BRIDGE_SCRIPT) in opts) == script
    with pytest.raises(st.StackError, match="needs --feed vcan"):
        st.start(ctx, attr.BRIDGE, "dumpfile", rd, "test/run")


def test_a_context_takes_every_bridge_mode_and_replay_takes_only_broker():
    assert set(vb.MODES) < set(st.BRIDGE_MODES) and st.REPLAY_BRIDGE_MODES == ("none", "broker")
    assert {m: st.age_clock(m) for m in vb.MODES} == {"broker": "realtime", "can": "realtime", "replay": "monotonic"}
    assert all(st.BRIDGE_NOTES[m] for m in vb.MODES) and st.BRIDGE_NOTES["none"] is None


# ============================================================ --images (SDV Phase 3 WP1)

def test_run_passes_the_images_mode_through_to_prepare(tmp_path, monkeypatch):
    """`run --images loaded` reaches Context.prepare in every mode (broker pulls and builds, now inspects; can and replay
    take the bridge's parts only); without it the mode is `build`, today's; another value is refused by the parser."""
    seen = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, run_dir, seed, mode):
            self.run_dir = run_dir

        def prepare(self, pull, build, bridge_parts, images="build"):
            seen.append((pull, build, bridge_parts, images))
            raise Stop()

    monkeypatch.setattr(st, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(st, "Context", FakeContext)
    monkeypatch.setattr(st, "load_contract", lambda: object())
    monkeypatch.setattr(step3, "load_specs", lambda: {"s": {}})
    monkeypatch.setattr(step3, "recording_doc", lambda contract: {})
    monkeypatch.setattr(step3, "plan_run", lambda doc, name, spec, mode: {"spec": name})
    for mode in ("broker", "can", "replay"):
        for extra in (["--images", "loaded"], []):
            with pytest.raises(Stop):
                step3.main(["run", "--mode", mode, "--spec", "s", "--name", "n%d" % len(seen)] + extra)
    assert seen == [(m == "broker", m == "broker", True, i) for m in ("broker", "can", "replay") for i in ("loaded", "build")]
    with pytest.raises(SystemExit):
        step3.main(["run", "--mode", "replay", "--spec", "s", "--images", "pulled"])


# ============================================================ the twin-control marker (SDV Phase 6 WP2, D11)

def test_every_run_is_refused_while_the_twin_control_marker_exists_and_plan_and_compare_are_not(tmp_path, monkeypatch):
    """Every step-3 run starts a bridge, in each of its modes: while the marker exists `run` is refused before a spec, the
    recording or the guest's console is read and before a context is made. plan and compare start nothing."""
    marker = tmp_path / "twin-control"
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))

    def reached(*_a, **_kw):
        raise AssertionError("step3 went on")
    for name in ("guest_args", "load_specs", "recording_doc", "prepared_context", "find_results"):
        monkeypatch.setattr(step3, name, reached)
    monkeypatch.setattr(st, "RUNS", tmp_path / "runs")
    marker.touch()
    for mode in ("broker", "can", "replay"):
        with pytest.raises(st.StackError, match="twin-control marker"):
            step3.main(["run", "--mode", mode, "--spec", "s"])
    with pytest.raises(AssertionError, match="step3 went on"):                    # plan reads the specs: the marker does not stop it
        step3.main(["plan", "--mode", "replay", "--spec", "s"])
    with pytest.raises(AssertionError, match="step3 went on"):                    # nor compare
        step3.main(["compare", str(tmp_path)])
    marker.unlink()
    with pytest.raises(AssertionError, match="step3 went on"):                    # without the marker a run goes on as before
        step3.main(["run", "--mode", "replay", "--spec", "s"])
    assert not (tmp_path / "runs").exists()


def test_a_run_whose_context_predates_the_marker_is_refused_at_the_bridges_start(tmp_path, monkeypatch):
    marker = tmp_path / "twin-control"
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))
    started: List[str] = []
    for name, fn in (("remove_stack", lambda: None), ("host_listeners", lambda: {"with_owners": True, "sockets": []}),
                     ("start_monitor", lambda ctx, rd, info: started.append("monitor")), ("collect", lambda rd: {}),
                     ("docker", lambda *a, **kw: started.append(" ".join(a[:1])) or subprocess.CompletedProcess(a, 0, "", ""))):
        monkeypatch.setattr(st, name, fn)
    monkeypatch.setattr(attr, "check_recording", lambda header, sha, dbc: ("C10", True, "synthetic"))
    plan = {"mode": "replay", "spec": "s", "run": "to_end", "events_file": None, "script": {"format": 1, "steps": []}}
    img = "sha256:" + "ef" * 32
    ctx = types.SimpleNamespace(
        bridge="replay", run_dir=tmp_path / "runs" / "m", run_header=lambda rid, feed: {"run_id": rid},
        check_header=lambda h: ("C12a", True, "synthetic"), staged={"sigsim.log": "ab" * 32}, scenario={"dbc_sha256": "x"}, rows=[],
        manifest={"scenario_checks": []}, components={attr.BRIDGE: {"image_id": img}, st.VSS_MONITOR: {"sha256": "0" * 64}},
        image_ids=lambda: {attr.BRIDGE: img}, monitor_mode="native", monitor=None, guest=None, in_dir=tmp_path / "in", images={},
        cpuset=None, after_start=None, after_start_records=[])
    marker.touch()
    with pytest.raises(st.StackError, match="twin-control marker"):
        step3.run_one(ctx, plan, "s-replay-1")
    assert "run" not in started and not (ctx.run_dir / "s-replay-1" / "bridge").exists()


# ============================================================ guest mode (SDV Phase 3 WP2)
# The QNX guest judges the run (--monitor guest): the bridge reaches its vss monitor over br0, and the run's console is
# QEMU's serial log, which carries NUL bytes, CRLF and the odd lone CR. Five instances of the vss build share that
# console (ifs-vss.build), so it holds five `vss rules:` lines from boot, and their lines can interleave. Synthetic values
# throughout; the guest's address here is a documentation address (RFC 5737).

GUEST = "192.0.2.10"
SYN_DIGEST, SYN_AGE_MAX_MS = "0x12345678", 240
PROBE_DONE = "monitor: client done: seen=0 accepted=0 rejected=0"      # the launch probe's (or the readiness check's) session
MISS_LINE = "monitor: LIVENESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)"
FINAL_DONE = "monitor: client done: seen=5 accepted=2 rejected=3"


def _rules_line(digest=SYN_DIGEST, age=SYN_AGE_MAX_MS, profiles="1 2"):
    """A `monitor: vss rules:` line in monitor.c's own format, read from the source (wire spec 12)."""
    src = (REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c").read_text(encoding="utf-8")
    m = re.search(r'printf\("(monitor: vss rules: [^"]*)\\n"', src)
    assert m is not None, "monitor.c lost its vss rules printf"
    return m.group(1).replace("0x%08X", "%s") % (digest, "6.0", age, profiles)


def _boot_lines(rules=None):
    """The guest console's boot: the five instances' rules lines (the second with a lone CR inside it, the third
    interleaved with another's, so it does not parse), then the :7160 banner."""
    r = list(rules) if rules is not None else [_rules_line() for _ in range(5)]
    r[1] = r[1].replace("kind 4, catalog", "kind 4,\r catalog")
    r[2] = r[2][:24] + r[2]
    return ["monitor: claim kinds: 0 1 4"] + r + ["monitor: service monitor listening on :7160 (frame=64 bytes), liveness deadline 500 ms"]


def _salt(lines):
    """Lines as QEMU's serial log holds them: CRLF ends, a NUL after each, and a NUL inside every `vss rules:` line."""
    return "".join(ln.replace("vss rules:", "vss\0 rules:") + "\r\n\0" for ln in lines).encode("utf-8")


def _guest_header():
    return {"bridge_mode": "replay", "run_type": "sigsim", "profile_id": 1, "age_max_ms": SYN_AGE_MAX_MS, "source_rtf": None,
            "catalogue": {"kind4_digest": SYN_DIGEST}}


def _guest_connect():
    return {"event": "connect", "digest": SYN_DIGEST, "age_max_ms": SYN_AGE_MAX_MS, "profile_id": 1, "mode": "replay"}


def _guest_ctx(console, image=None, host=GUEST, **kw):
    return types.SimpleNamespace(monitor_mode="guest", guest={"host": host, "console": Path(console), "image": image}, monitor=None, **kw)


def _connect_log(rd):
    (rd / "bridge").mkdir(parents=True, exist_ok=True)
    (rd / "bridge" / "bridge.jsonl").write_text(json.dumps(_guest_connect()) + "\n", encoding="utf-8")


def test_the_guest_console_reader_strips_nul_and_cr_and_c12b_reads_the_four_rules_lines_that_parse(tmp_path):
    raw = _salt(_boot_lines() + [PROBE_DONE])
    assert b"\0" in raw and b"\r\n" in raw and b",\r catalog" in raw
    assert attr.vss_rules_lines(raw.decode("utf-8")) == [], "as QEMU wrote it, not one rules line parses"
    console = tmp_path / "serial.log"
    console.write_bytes(raw)
    rd = tmp_path / "run"
    _connect_log(rd)
    got = step3.run_console(_guest_ctx(console), rd, step3.freshness(raw))
    copy = rd / step3.GUEST_CONSOLE
    assert got["path"] == copy and copy.read_bytes() == raw.replace(b"\0", b"").replace(b"\r", b"")
    assert b"\0" not in copy.read_bytes() and b"\r" not in copy.read_bytes()
    assert got["record"]["raw"] == {"path": str(console), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert got["record"]["copy"] == step3.GUEST_CONSOLE and got["record"]["removed"] == {"nul": raw.count(b"\0"), "cr": raw.count(b"\r")}
    assert got["whole"] == copy.read_text(encoding="utf-8") and got["judged"] == "", "nothing after the gate's offset yet"
    assert len(attr.vss_rules_lines(got["whole"])) == 4, "five rules lines, one interleaved: four parse"
    h = _guest_header()
    c = st.record_close(h, rd, got["path"])
    assert c[1] and "4 vss rules line(s), 1 bridge connect record(s)" in c[2] and h["header_check"] == "ok", c
    # one of the four that parse disagreeing with the header fails C12b
    rules = [_rules_line() for _ in range(5)]
    rules[4] = _rules_line(digest="0x87654321")
    raw2 = _salt(_boot_lines(rules))
    console.write_bytes(raw2)
    rd2 = tmp_path / "run2"
    _connect_log(rd2)
    got2 = step3.run_console(_guest_ctx(console), rd2, step3.freshness(raw2))
    c = st.record_close(_guest_header(), rd2, got2["path"])
    assert not c[1] and "vss rules: catalog 0x87654321" in c[2], c


def test_the_native_console_is_the_monitors_log_as_before(tmp_path):
    rd = tmp_path / "r"
    rd.mkdir()
    ctx = types.SimpleNamespace(bridge="replay", monitor=None)       # a context without a monitor mode is native
    got = step3.run_console(ctx, rd, None)
    assert (got["whole"], got["judged"], got["path"], got["record"]) == ("", "", rd / "monitor.log", None)
    (rd / "monitor.log").write_bytes(b"monitor: a\0line\r\n")
    got = step3.run_console(ctx, rd, None)
    assert got["whole"] == got["judged"] == "monitor: a\0line\n" and not (rd / step3.GUEST_CONSOLE).exists(), "read as today (read_text)"


@pytest.mark.parametrize("line, fresh", [
    (MISS_LINE, False),
    ("monitor: LIVENESS RESTORED: seq=6 after 600 ms without a claim", False),
    ("monitor: client closed: no complete frame for 500 ms", False),
    ("monitor: client closed: reply not taken for 500 ms", False),
    ("monitor: client done: seen=5 accepted=5 rejected=0", False),
    ("monitor: client done: seen=1 accepted=0 rejected=1", False),
    ("monitor: client done: seen=0 acmonitor: LIVENESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)", False),
    ("monitor: LIVE\0NESS MISS: no claim for 500 ms since seq=5 (deadline 500 ms, miss 1)", False),
    (PROBE_DONE, True),
    ("monitor: frame read failed: Success", True),          # the launch probe's newline: a partial frame, then EOF
    ("monitor: stopped (liveness misses=0)", True),
])
def test_the_freshness_gate_refuses_what_a_used_console_holds_and_passes_the_probes_seen_0(line, fresh):
    raw = _salt(_boot_lines() + [PROBE_DONE, line])
    g = step3.freshness(raw)
    assert g["ok"] is fresh and bool(g["problems"]) is not fresh, g
    assert g["bytes"] == len(raw) and g["offset"] == raw.rfind(b"\n") + 1


def test_the_freshness_offset_is_the_end_of_the_last_whole_line():
    whole = _salt(_boot_lines() + [PROBE_DONE])
    g = step3.freshness(whole + b"monitor: client do")
    assert g["ok"] and g["bytes"] == len(whole) + len(b"monitor: client do") and g["offset"] == whole.rfind(b"\n") + 1
    assert step3.freshness(b"")["offset"] == 0 and step3.freshness(b"")["ok"]


def _guest_judged(tmp_path, before, during):
    """The salted guest console: the boot and `before`, the freshness gate taken there, then `during` (the run) appended;
    read back as run_one reads it (run_console)."""
    console = tmp_path / "serial.log"
    console.write_bytes(_salt(_boot_lines() + list(before)))
    gate = step3.freshness(console.read_bytes())
    with open(console, "ab") as f:
        f.write(_salt(list(during)))
    rd = tmp_path / "run"
    rd.mkdir()
    return gate, step3.run_console(_guest_ctx(console), rd, gate)


def _judge_guest(console, replied=5):
    """The plain run's files judged on the guest console's judged part, with its end (console_end)."""
    plan, replies, records, _c = _plain_run()
    summary = _summary(plan)
    summary["counters"]["replied"] = replied
    return step3.judge(plan, replies, records, summary, console["judged"], {"recording": ORIGIN, "script": ORIGIN}, {}, C.AGE_MAX_MS,
                       end=step3.console_end(console["judged"]))


def test_a_guest_run_with_its_final_client_done_passes_and_records_seen_beside_the_bridges_replies(tmp_path):
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], [FINAL_DONE, MISS_LINE])
    assert gate["ok"]
    res = _judge_guest(con, replied=7)
    assert res["ok"] and res["gates"]["console_end"] and res["gates"]["console"], _failing(res)
    assert res["console_end"] == dict(res["console_end"], ok=True, seen=5, bridge_replied=7), res["console_end"]
    assert res["console"]["after_last_session"]["miss"] == 1, "the monitor outliving the bridge"


def test_without_a_final_client_done_a_guest_run_fails_console_end_and_the_console_gate(tmp_path):
    """The launch probe's seen=0 line is on the console before the run; the run's MISS comes after the gate's offset and no
    final `client done:` does. console_end fails, and the console gate with it. Read whole, the console would pass the
    console gate vacuously: the probe's line would be taken for the bridge's last session end."""
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], [MISS_LINE])
    assert gate["ok"]
    res = _judge_guest(con)
    assert _failing(res) == ["console", "console_end"] and not res["ok"], _failing(res)
    assert res["console_end"]["seen"] is None and res["console"]["during"]["miss"] == 1
    plan, replies, records, _c = _plain_run()
    whole = step3.judge(plan, replies, records, _summary(plan), con["whole"], {"recording": ORIGIN, "script": ORIGIN}, {}, C.AGE_MAX_MS)
    assert whole["gates"]["console"], "the vacuous pass the offset prevents"


@pytest.mark.parametrize("during", [[], [PROBE_DONE]], ids=["nothing", "a seen=0 session only"])
def test_a_guest_run_with_no_session_after_the_offset_fails_console_end_alone(tmp_path, during):
    _gate, con = _guest_judged(tmp_path, [PROBE_DONE], during)
    res = _judge_guest(con)
    assert _failing(res) == ["console_end"], _failing(res)


def test_lines_before_the_gates_offset_are_not_judged(tmp_path):
    """A MISS and a close before the offset (a gate refuses such a console; here the judge is given its offset anyway),
    and a clean session after it: the console gate passes. Judged whole, it would not."""
    gate, con = _guest_judged(tmp_path, [MISS_LINE, "monitor: client closed: no complete frame for 500 ms", PROBE_DONE], [FINAL_DONE])
    assert not gate["ok"]
    assert MISS_LINE in con["whole"] and MISS_LINE not in con["judged"]
    res = _judge_guest(con)
    assert res["ok"] and res["gates"]["console"] and res["gates"]["console_end"], _failing(res)
    plan, replies, records, _c = _plain_run()
    whole = step3.judge(plan, replies, records, _summary(plan), con["whole"], {"recording": ORIGIN, "script": ORIGIN}, {}, C.AGE_MAX_MS)
    assert not whole["gates"]["console"]


def _guest_run_one(tmp_path, monkeypatch, during, before=(PROBE_DONE,), connects=1):
    """run_one in guest mode on the plain run's replay plan, with the stack's calls replaced: the fake bridge leaves the
    plain run's files (with `connects` connect records), and the guest's console gets `during` while the bridge runs."""
    plan, replies, records, _c = _plain_run()
    records = [_rec("replay-anchored", 0, anchor_ns=ORIGIN), _rec("script-origin", 0, origin_ns=ORIGIN)] + \
        [dict(_guest_connect(), t_mono=ORIGIN + i) for i in range(connects)] + records
    summary = _summary(plan)
    console = tmp_path / "serial.log"
    console.write_bytes(_salt(_boot_lines() + list(before)))
    image = tmp_path / "ifs-stand-in.bin"
    image.write_bytes(b"a stand-in image")
    seen: Dict[str, Any] = {"allowed": [], "native": [], "bridge": []}

    def native(*_a, **_kw):
        seen["native"].append(_a)
        raise AssertionError("guest mode started the native monitor")

    def start_bridge(ctx, feed, rd, label, header):
        seen["bridge"].append(st.monitor_host(ctx))
        (rd / "bridge").mkdir(exist_ok=True)
        (rd / "bridge" / "replies.jsonl").write_text("".join(json.dumps(dict(r, event="reply")) + "\n" for r in replies), encoding="utf-8")
        (rd / "bridge" / "bridge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        (rd / "bridge" / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        with open(console, "ab") as f:
            f.write(_salt(list(during)))

    def listeners_now(info, feed, suffix, allowed=()):
        seen["allowed"].append(list(allowed))
        info["listeners" + suffix] = {"ok": True}

    for name, fn in (("remove_stack", lambda: None), ("host_listeners", lambda: {"with_owners": True, "sockets": []}),
                     ("start_monitor", native), ("NativeMonitor", native), ("build_native_monitor", native), ("start_bridge", start_bridge),
                     ("listeners_now", listeners_now), ("collect", lambda rd: {attr.BRIDGE: "exited 0"})):
        monkeypatch.setattr(st, name, fn)
    monkeypatch.setattr(st, "VCAN_READY_S", 0.0)
    monkeypatch.setattr(step3, "CONSOLE_END_S", 0.3)
    monkeypatch.setattr(step3, "drive_replay", lambda plan, ops: {"origin_ns": ORIGIN, "bridge": {"ended_itself": True}})
    monkeypatch.setattr(attr, "check_recording", lambda header, sha, dbc: ("C10", True, "synthetic"))
    comp = {"form": "guest", "image": image.name, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    ctx = _guest_ctx(console, image, bridge="replay", run_dir=tmp_path / "runs" / "g", staged={"sigsim.log": "ab" * 32},
                     components={attr.BRIDGE: {"image_id": "sha256:" + "ef" * 32}, st.VSS_MONITOR_GUEST: comp},
                     scenario={"dbc_sha256": "sha256:" + "cd" * 32}, rows=[], manifest={"scenario_checks": []},
                     contract=types.SimpleNamespace(AGE_MAX_MS=C.AGE_MAX_MS), image_ids=lambda: {},
                     run_header=lambda run_id, feed: dict(_guest_header(), run_id=run_id), check_header=lambda h: ("C12a", True, "synthetic"))
    return ctx, plan, console, seen


def test_run_one_in_guest_mode_judges_the_console_after_the_offset_and_starts_no_native_monitor(tmp_path, monkeypatch):
    ctx, plan, console, seen = _guest_run_one(tmp_path, monkeypatch, [FINAL_DONE, MISS_LINE])
    pre = console.read_bytes()
    r = step3.run_one(ctx, plan, "honest-replay-1")
    assert r["ok"], [g for g, v in r["gates"].items() if not v]
    assert r["gates"]["console_end"] and r["gates"]["console"] and r["gates"]["c12b"] and r["gates"]["listeners"]
    assert seen["native"] == [] and seen["allowed"] == [[], [], []] and seen["bridge"] == [GUEST], seen
    assert r["monitor"] == ctx.components[st.VSS_MONITOR_GUEST]["sha256"] and "monitor_exit" not in r
    raw = console.read_bytes()
    assert r["console_gate"]["ok"] and r["console_gate"]["offset"] == pre.rfind(b"\n") + 1 and r["console_gate"]["bytes"] == len(pre)
    assert r["console_file"]["raw"] == {"path": str(console), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    rd = ctx.run_dir / "honest-replay-1"
    assert b"\0" not in (rd / step3.GUEST_CONSOLE).read_bytes() and not (rd / "monitor.log").exists()
    assert r["c12b_lines"] == 4 and r["console_end"]["seen"] == 5
    assert (r["console_end"]["sessions"], r["console_end"]["ended"]) == (1, 1)
    assert r["c12b_expected"] == step3.GUEST_RULES_LINES == 5 and r["c12b_note"].startswith("4 of 5 "), "noted, not failed"
    assert json.loads((rd / "result.json").read_text(encoding="utf-8"))["ok"] is True


def test_run_one_in_guest_mode_fails_console_end_and_the_console_gate_without_a_final_client_done(tmp_path, monkeypatch):
    ctx, plan, _console, seen = _guest_run_one(tmp_path, monkeypatch, [MISS_LINE])
    r = step3.run_one(ctx, plan, "honest-replay-1")
    assert [g for g, v in r["gates"].items() if not v] == ["console", "console_end"] and not r["ok"]
    assert seen["native"] == []


def test_run_one_in_guest_mode_refuses_a_console_that_is_not_fresh_before_anything_starts(tmp_path, monkeypatch):
    ctx, plan, _console, seen = _guest_run_one(tmp_path, monkeypatch, [FINAL_DONE], before=(PROBE_DONE, MISS_LINE))
    with pytest.raises(step3.StepError, match="not fresh"):
        step3.run_one(ctx, plan, "honest-replay-1")
    assert seen["bridge"] == [] and seen["allowed"] == []


class _Clock:
    """step3's time module, swapped in for the console-end wait: a clock that moves only when step3 sleeps, and a hook at
    each sleep. A line can then reach the console while step3 waits, with no thread and no race."""

    def __init__(self, hook: Any = None) -> None:
        self.now, self.sleeps, self.hook = 0.0, 0, hook

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps += 1
        self.now += s
        if self.hook is not None:
            self.hook(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


class _Late:
    """Lines that reach the guest's console late: appended at the first sleep at which when() holds."""

    def __init__(self, console: Path, lines: List[str], when: Any = lambda: True) -> None:
        self.console, self.lines, self.when = console, list(lines), when
        self.appended_at: Optional[float] = None

    def __call__(self, clock: _Clock) -> None:
        if self.appended_at is None and self.when():
            with open(self.console, "ab") as f:
                f.write(_salt(self.lines))
            self.appended_at = clock.now


def _gated_console(tmp_path, during, before=(PROBE_DONE,)):
    """The salted console, its freshness gate's offset taken after `before`, then `during` appended."""
    console = tmp_path / "serial.log"
    console.write_bytes(_salt(_boot_lines() + list(before)))
    offset = step3.freshness(console.read_bytes())["offset"]
    with open(console, "ab") as f:
        f.write(_salt(list(during)))
    return console, offset


def test_the_console_end_wait_takes_a_final_client_done_that_arrives_while_it_waits(tmp_path, monkeypatch):
    """The run's MISS is on the console, its final `client done:` not yet (a serial line can trail the bridge's end): the
    wait reads, sleeps, and the line it then finds ends it, inside its bound."""
    console, off = _gated_console(tmp_path, [MISS_LINE])
    late = _Late(console, [FINAL_DONE])
    clock = _Clock(late)
    monkeypatch.setattr(step3, "time", clock)
    assert step3.wait_console_end(console, off, 5.0) is True
    assert late.appended_at is not None and clock.sleeps >= 1 and clock.now < 5.0, (late.appended_at, clock.sleeps, clock.now)


@pytest.mark.parametrize("during", [[MISS_LINE], [MISS_LINE, PROBE_DONE]], ids=["no session end", "a seen=0 session only"])
def test_the_console_end_wait_gives_up_at_its_bound_when_the_runs_end_never_comes(tmp_path, monkeypatch, during):
    console, off = _gated_console(tmp_path, during)
    clock = _Clock()
    monkeypatch.setattr(step3, "time", clock)
    assert step3.wait_console_end(console, off, 5.0) is False
    assert 5.0 <= clock.now < 6.0 and clock.sleeps > 1, "it waited out its bound, and no longer"


def test_a_pause_runs_console_end_is_its_last_sessions_end_not_its_first(tmp_path, monkeypatch):
    """A pause run has two sessions (the bridge's two connect records): the first ends with the monitor's close for
    silence and a `client done:` with seen above 0 before the run's last session does. console_end wants one such line
    per session, so the wait goes on for the second, which trails here; with one session one line is enough."""
    first = ["monitor: LIVENESS MISS: no claim for 500 ms since seq=10 (deadline 500 ms, miss 1)",
             "monitor: client closed: no complete frame for 500 ms", "monitor: client done: seen=10 accepted=10 rejected=0",
             "monitor: LIVENESS RESTORED: seq=11 after 1600 ms without a claim"]
    console, off = _gated_console(tmp_path, first)
    judged = step3.strip_console(console.read_bytes()[off:])
    assert step3.console_end(judged)["ok"] and step3.console_end(judged, 1)["ok"]
    end = step3.console_end(judged, 2)
    assert not end["ok"] and end["seen"] == 10 and (end["sessions"], end["ended"]) == (2, 1), end
    assert step3.console_end(judged, 0)["sessions"] == 1, "a bridge that never connected still wants its one session's end"
    late = _Late(console, [FINAL_DONE])
    monkeypatch.setattr(step3, "time", _Clock(late))
    assert step3.wait_console_end(console, off, 5.0, 2) is True and late.appended_at is not None
    end = step3.console_end(step3.strip_console(console.read_bytes()[off:]), 2)
    assert end["ok"] and end["seen"] == 5 and (end["sessions"], end["ended"]) == (2, 2), end


def _after_the_run(ctx, run_id="honest-replay-1"):
    """True once run_one has written its run's result.json: the bridge has ended and the containers are collected."""
    return lambda: (ctx.run_dir / run_id / "result.json").is_file()


def test_run_one_in_guest_mode_waits_for_a_final_client_done_that_trails_the_bridges_end(tmp_path, monkeypatch):
    """Nothing of the run is on the console when the bridge has ended; its final `client done:` and the MISS of the
    monitor outliving it arrive while run_one waits. Every gate passes. Without the wait, or with one that does not wait,
    the console is read first and console_end fails."""
    ctx, plan, console, seen = _guest_run_one(tmp_path, monkeypatch, [])
    late = _Late(console, [FINAL_DONE, MISS_LINE], when=_after_the_run(ctx))
    monkeypatch.setattr(step3, "time", _Clock(late))
    r = step3.run_one(ctx, plan, "honest-replay-1")
    assert late.appended_at is not None, "the lines came during run_one's wait"
    assert r["ok"] and r["gates"]["console_end"] and r["gates"]["console"], [g for g, v in r["gates"].items() if not v]
    assert r["console_end"]["seen"] == 5 and r["console"]["after_last_session"]["miss"] == 1 and seen["native"] == []


@pytest.mark.parametrize("trailing", [False, True], ids=["one of two session ends", "the second trailing"])
def test_run_one_in_guest_mode_wants_a_session_end_per_bridge_connect(tmp_path, monkeypatch, trailing):
    """Two connect records in the bridge's log: one `client done:` with seen above 0 is not the run's end. With the second
    arriving while run_one waits, every gate passes; without it, console_end alone fails."""
    session1 = "monitor: client done: seen=3 accepted=3 rejected=0"
    ctx, plan, console, _seen = _guest_run_one(tmp_path, monkeypatch, [session1], connects=2)
    late = _Late(console, [FINAL_DONE] if trailing else [], when=_after_the_run(ctx))
    monkeypatch.setattr(step3, "time", _Clock(late))
    r = step3.run_one(ctx, plan, "honest-replay-1")
    end = r["console_end"]
    if trailing:
        assert r["ok"] and (end["sessions"], end["ended"], end["seen"]) == (2, 2, 5), ([g for g, v in r["gates"].items() if not v], end)
    else:
        assert [g for g, v in r["gates"].items() if not v] == ["console_end"] and (end["sessions"], end["ended"], end["seen"]) == (2, 1, 3)


def test_a_guest_console_that_cannot_be_read_is_a_refusal_naming_it(tmp_path, monkeypatch):
    """The console gone between the call's gate and the run's read: a StepError naming the console (which step3's main
    reports), never a traceback. The run's result.json then has no reason set, so compare fails its group by name."""
    missing = tmp_path / "gone.log"
    rd = tmp_path / "run"
    rd.mkdir()
    with pytest.raises(step3.StepError, match="guest console .*gone.log"):
        step3.run_console(_guest_ctx(missing), rd, {"offset": 0})
    ctx, plan, console, _seen = _guest_run_one(tmp_path, monkeypatch, [FINAL_DONE])
    monkeypatch.setattr(st, "collect", lambda rd: console.unlink() or {attr.BRIDGE: "exited 0"})
    with pytest.raises(step3.StepError, match="guest console .*serial.log"):
        step3.run_one(ctx, plan, "honest-replay-1")
    left = json.loads((ctx.run_dir / "honest-replay-1" / "result.json").read_text(encoding="utf-8"))
    assert "reason_set" not in left and "ok" not in left
    (tmp_path / "b").mkdir()
    ctx2, plan2, console2, seen2 = _guest_run_one(tmp_path / "b", monkeypatch, [FINAL_DONE])
    console2.unlink()
    with pytest.raises(step3.StepError, match="guest console .*serial.log"):
        step3.run_one(ctx2, plan2, "honest-replay-1")
    assert seen2["bridge"] == [], "refused at the run's gate, before anything started"


def test_the_c12b_count_is_recorded_with_five_expected_in_guest_mode_and_noted_not_failed():
    five = "\n".join(_rules_line() for _ in range(5)) + "\n"
    assert step3.c12b_count(five, guest=True) == {"c12b_lines": 5, "c12b_expected": 5}
    three = "\n".join(_rules_line() for _ in range(3)) + "\n"
    got = step3.c12b_count(three, guest=True)
    assert got["c12b_lines"] == 3 and got["c12b_expected"] == 5 and got["c12b_note"].startswith("3 of 5 "), got
    assert step3.c12b_count(three, guest=False) == {"c12b_lines": 3}, "native mode: one instance, no expectation"


def test_no_parsed_rules_line_in_guest_mode_is_noted_as_the_consoles_failure_as_much_as_the_guests():
    """Five instances started at once can garble every banner; C12b (at least one parsed line) then fails, and the note
    says so instead of `noted, not failed`."""
    got = step3.c12b_count("monitor: vss rmonitor: vss rules: kind 4,\n", guest=True)
    assert got["c12b_lines"] == 0 and got["c12b_expected"] == 5, got
    assert "noted, not failed" not in got["c12b_note"] and "C12b fails" in got["c12b_note"] and "console" in got["c12b_note"], got


# The review's consoles (pure functions on the plain replay run's files, the judged text after the gate's offset): a second
# writer on the console can splice a marker into another line, or add a session end the bridge did not make.
VSS_SUMMARY = "monitor: vss summary: seen=7 rejected=3 suppressed=0 by reason: 23=3"
REJECT_LINE = "monitor: REJECT seq=4 kind=vss profile=1 reason=23"
SILENT = "monitor: client closed: no complete frame for 500 ms"
_GARBLED = [
    ("C1: a MISS inside another line", [VSS_SUMMARY + MISS_LINE, FINAL_DONE]),
    ("C1b: a close inside a REJECT line", [REJECT_LINE + SILENT, FINAL_DONE]),
    ("C4: a MISS inside the final client done line", ["monitor: client done: seen=5 ac" + MISS_LINE, "cepted=2 rejected=3"]),
]


@pytest.mark.parametrize("what, during", _GARBLED, ids=[g[0].split(":")[0] for g in _GARBLED])
def test_a_guest_console_line_holding_a_marker_anywhere_but_at_its_start_fails_the_console_gate_by_name(tmp_path, what, during):
    """Line-start matching would not see these markers (a false PASS); the freshness gate, matching anywhere, would refuse
    the same text. In guest mode a judged line that holds `LIVENESS`, `client closed:` or `client done:` anywhere but as its
    own start is garbled, and fails the console gate with a named problem; native mode records it, not gated."""
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], during)
    assert gate["ok"] and not step3.freshness(_salt(during))["ok"], "the freshness gate would refuse the same text"
    res = _judge_guest(con)
    assert _failing(res) == ["console"] and not res["ok"], (what, _failing(res), res["console"])
    assert res["console"]["garbled_lines"] == 1 and res["console"]["garbled"] == [during[0]], (what, res["console"])
    assert [p for p in res["console"]["problems"] if p.startswith("1 garbled console line(s)")], res["console"]
    plan, replies, records, _c = _plain_run()
    native = step3.judge(plan, replies, records, _summary(plan), con["judged"], {"recording": ORIGIN, "script": ORIGIN}, {}, C.AGE_MAX_MS)
    assert native["gates"]["console"] and native["console"]["garbled_lines"] == 1, "native mode: one writer; recorded, not gated"


def test_run_one_in_guest_mode_fails_the_console_gate_on_a_garbled_marker_line(tmp_path, monkeypatch):
    ctx, plan, _console, _seen = _guest_run_one(tmp_path, monkeypatch, [VSS_SUMMARY + MISS_LINE, FINAL_DONE])
    r = step3.run_one(ctx, plan, "honest-replay-1")
    assert [g for g, v in r["gates"].items() if not v] == ["console"] and r["console"]["garbled_lines"] == 1, r["console"]


def _guest_pause(tmp_path, kind, splice=None):
    """A pause run's files (_pause_files) judged in guest mode, as V2's pause-tick and pause-both are: the run's console
    lines (the boot's rules line left out) appended after the freshness gate to the salted guest console, judged with
    console_end for the bridge's connects (two). splice: a line put in after the run's MISS. Returns the guest-mode
    result and the same files judged in native mode."""
    plan = _pause_plan(kind)
    replies, records, console = _pause_files(plan)
    during = console.splitlines()[1:]
    if splice is not None:
        during.insert(1, splice)
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], during)
    assert gate["ok"], gate
    end = step3.console_end(con["judged"], sum(1 for r in records if r.get("event") == "connect"))
    origins = {"recording": ORIGIN, "script": ORIGIN}
    guest = step3.judge(plan, replies, records, _summary(plan), con["judged"], origins, {}, C.AGE_MAX_MS, end=end)
    native = step3.judge(plan, replies, records, _summary(plan), con["judged"], origins, {}, C.AGE_MAX_MS)
    return guest, native


@pytest.mark.parametrize("kind", ["tick", "both"])
def test_a_guest_pause_run_holding_spec_14_4s_sequence_passes_every_gate_with_no_garbled_line(tmp_path, kind):
    """The pause run's MISS, close for silence, RESTORED and two session ends each start their own line: none is garbled,
    and in guest mode every gate holds, console_end by the bridge's two sessions."""
    res, _native = _guest_pause(tmp_path, kind)
    assert res["ok"] and res["pause_sequence"]["ok"], (_failing(res), res["pause_sequence"], res["console"])
    assert res["console"]["garbled_lines"] == 0 and res["console"]["problems"] == [] and res["console"]["seen_0"] == 0, res["console"]
    assert res["console_end"]["ok"] and (res["console_end"]["sessions"], res["console_end"]["ended"]) == (2, 2), res["console_end"]


_PAUSE_SPLICES = [
    ("a second MISS inside a summary line",
     VSS_SUMMARY + "monitor: LIVENESS MISS: no claim for 500 ms since seq=10 (deadline 500 ms, miss 2)"),
    ("a second close for silence inside a REJECT line", REJECT_LINE + SILENT),
    ("a RESTORED inside a REJECT line", REJECT_LINE + "monitor: LIVENESS RESTORED: seq=11 after 1600 ms without a claim"),
]


@pytest.mark.parametrize("kind", ["tick", "both"])
@pytest.mark.parametrize("what, splice", _PAUSE_SPLICES, ids=[s[0] for s in _PAUSE_SPLICES])
def test_a_marker_spliced_into_another_line_of_a_guest_pause_run_fails_the_console_gate_by_name(tmp_path, kind, what, splice):
    """pause_sequence counts markers at a line's start, so it still sees one MISS, one close and one RESTORED and passes:
    in guest mode the garbled line alone fails the console gate, named in console.problems; native mode counts it, not
    gated."""
    res, native = _guest_pause(tmp_path, kind, splice)
    assert res["pause_sequence"]["ok"], (what, "line-start counting alone passes it", res["pause_sequence"])
    assert _failing(res) == ["console"] and not res["ok"], (what, _failing(res), res["console"])
    assert res["console"]["garbled_lines"] == 1 and res["console"]["garbled"] == [splice], (what, res["console"])
    assert [p for p in res["console"]["problems"] if p.startswith("1 garbled console line(s)")], res["console"]
    assert native["ok"] and native["console"]["garbled_lines"] == 1, (what, "native mode: one writer; recorded, not gated")


def test_a_late_seen_0_session_after_the_bridges_end_is_counted_not_taken_for_the_split(tmp_path):
    """C3: the bridge's session ends (seen=5), the monitor outlives it (MISS), then a late connect-and-close leaves a seen=0
    line. In guest mode the split is the last session end with seen above 0 (the bridge's always are), so the MISS is
    after it; the seen=0 line is counted as information."""
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], [FINAL_DONE, MISS_LINE, PROBE_DONE])
    res = _judge_guest(con)
    assert res["ok"] and res["gates"]["console"] and res["gates"]["console_end"], (_failing(res), res["console"])
    assert res["console"]["after_last_session"]["miss"] == 1 and res["console"]["seen_0"] == 1, res["console"]


@pytest.mark.parametrize("during, seen", [
    (["monitor: client done: seen=3 accepted=3 rejected=0", FINAL_DONE], 5),
    ([FINAL_DONE, "monitor: client done: seen=99 accepted=99 rejected=0"], 99),
], ids=["C2: a session before the bridge's", "C9: a foreign session after it"])
def test_more_session_ends_than_bridge_sessions_fail_console_end_and_name_the_surplus(tmp_path, monkeypatch, during, seen):
    """The bridge logs one connect per session and sends at least one claim in each: more `client done:` lines with seen
    above 0 than connects means a client that was not the bridge judged claims on :7160 during the run."""
    gate, con = _guest_judged(tmp_path, [PROBE_DONE], during)
    end = step3.console_end(con["judged"], 1)
    assert not end["ok"] and (end["sessions"], end["ended"], end["seen"]) == (1, 2, seen), end
    assert [p for p in end["problems"] if p.startswith("2 `client done:` lines with seen above 0") and "not the bridge" in p], end
    res = _judge_guest(con)
    assert _failing(res) == ["console_end"], (_failing(res), res["console_end"])
    # the wait ends once the bridge's session ends are there: a surplus is the judge's to name, never a reason to wait
    clock = _Clock()
    monkeypatch.setattr(step3, "time", clock)
    assert step3.wait_console_end(tmp_path / "serial.log", gate["offset"], 5.0, 1) is True and clock.sleeps == 0


def test_a_probe_held_past_the_guests_deadline_leaves_a_close_the_freshness_gate_refuses_and_explains():
    """On the real monitor (monitor.c serve_svc_client) a connect with no bytes closed at once leaves only `client done:
    seen=0`, the launch probe's newline `frame read failed` then seen=0; one held open past the 500 ms deadline leaves
    `client closed: no complete frame` first, and the gate refuses that console: the refusal says how it comes about."""
    held = step3.freshness(_salt(_boot_lines() + [PROBE_DONE, SILENT, PROBE_DONE]))
    assert not held["ok"] and [p for p in held["problems"] if "held open" in p and "in one step" in p], held
    prompt = step3.freshness(_salt(_boot_lines() + ["monitor: frame read failed: Success", PROBE_DONE, PROBE_DONE]))
    assert prompt["ok"], prompt
    used = step3.freshness(_salt(_boot_lines() + [MISS_LINE, SILENT, PROBE_DONE]))
    assert not used["ok"] and not [p for p in used["problems"] if "held open" in p], "a MISS is a used console, not a held probe"


def test_guest_mode_refuses_this_hosts_own_address_off_the_pc(tmp_path, monkeypatch):
    """--guest-host naming one of this host's own addresses: on a1-metal or orin the guest is never this host, so the run
    would be judged by whatever listens here; refused before anything is prepared. On the PC the stand-in is this host."""
    g = _guest_main(tmp_path, monkeypatch)
    monkeypatch.setattr(st, "local_ipv4", lambda: ["192.0.2.1", GUEST], raising=False)
    monkeypatch.setenv("SDV_HOST_ROLE", "a1-metal")
    with pytest.raises(step3.StepError, match="one of this host's own addresses"):
        step3.main(_guest_argv(g))
    assert g.built == []
    monkeypatch.setenv("SDV_HOST_ROLE", "pc")
    with pytest.raises(g.Stop):
        step3.main(_guest_argv(g))
    assert len(g.built) == 1


@pytest.mark.parametrize("mode", ["native", "guest"])
def test_up_bridge_only_starts_the_native_monitor_in_native_mode_only(tmp_path, monkeypatch, mode):
    started: List[str] = []
    allowed: List[Any] = []
    monkeypatch.setattr(st, "remove_stack", lambda: None)
    monkeypatch.setattr(st, "host_listeners", lambda: {"with_owners": True, "sockets": []})
    monkeypatch.setattr(st, "start_bridge", lambda *a: started.append("bridge"))
    monkeypatch.setattr(st, "listeners_now", lambda info, feed, suffix, al=(): allowed.append(list(al)))

    def start_monitor(ctx, rd, info):
        started.append("monitor")
        ctx.monitor = types.SimpleNamespace(allowance=lambda: {"pid": 4242, "proto": "tcp", "port": 7160, "why": "the native monitor"})
    monkeypatch.setattr(st, "start_monitor", start_monitor)
    if mode == "guest":
        ctx = _guest_ctx(tmp_path / "serial.log", bridge="replay")
    else:
        ctx = types.SimpleNamespace(bridge="replay", monitor=None, monitor_mode="native", guest=None)
    info = step3.up_bridge_only(ctx, "none", tmp_path, "x/r", {})
    if mode == "native":
        assert started == ["monitor", "bridge"] and allowed == [[{"pid": 4242, "proto": "tcp", "port": 7160, "why": "the native monitor"}]]
    else:
        assert started == ["bridge"] and allowed == [[]] and st.allowances(ctx) == []
        assert info["monitor"] == {"form": "guest", "host": GUEST, "port": 7160}


@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_the_bridge_reaches_the_guest_at_its_host_in_guest_mode_and_the_loopback_in_native_mode(tmp_path, monkeypatch, mode):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    calls: List[List[str]] = []
    monkeypatch.setattr(st, "docker", lambda *a, **_kw: calls.append(list(a)) or subprocess.CompletedProcess(a, 0, "", ""))
    img = "sha256:" + "ef" * 32
    rd = tmp_path / "r"
    (rd / "bridge").mkdir(parents=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    for monitor_mode, host in (("guest", GUEST), ("native", "127.0.0.1")):
        ctx = types.SimpleNamespace(image_ids=lambda: {attr.BRIDGE: img}, in_dir=tmp_path / "in", bridge=mode, monitor_mode=monitor_mode,
                                    guest={"host": GUEST} if monitor_mode == "guest" else None)
        st.start(ctx, attr.BRIDGE, step3.FEED[mode], rd, "test/run")
        cmd = calls[-1][calls[-1].index(img) + 1:]
        assert cmd[:5] == ["run", "--host", host, "--port", "7160"], (monitor_mode, cmd)


def _guest_main(tmp_path, monkeypatch):
    """step3.main's run with Context replaced: a constructed context is recorded (with its keyword arguments) and its
    prepare stops the call; nothing is prepared."""
    built: List[Dict[str, Any]] = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, run_dir, seed, mode, **kw):
            built.append(dict(kw, mode=mode))
            self.run_dir = run_dir

        def prepare(self, pull, build, bridge_parts, images="build"):
            raise Stop()

    monkeypatch.setattr(st, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(st, "Context", FakeContext)
    monkeypatch.setattr(st, "load_contract", lambda: object())
    monkeypatch.setattr(step3, "load_specs", lambda: {"s": {}, "t": {}})
    monkeypatch.setattr(step3, "recording_doc", lambda contract: {})
    monkeypatch.setattr(step3, "plan_run", lambda doc, name, spec, mode: {"spec": name})
    console = tmp_path / "serial.log"
    console.write_bytes(_salt(_boot_lines() + [PROBE_DONE]))
    image = tmp_path / "ifs-stand-in.bin"
    image.write_bytes(b"a stand-in image")
    return types.SimpleNamespace(built=built, Stop=Stop, console=console, image=image)


def _guest_argv(g, spec=("s",), repeat=None, host=GUEST, console="ok", image="ok"):
    argv = ["run", "--mode", "replay", "--spec", *spec, "--name", "g", "--monitor", "guest"]
    argv += ["--repeat", repeat] if repeat is not None else []
    argv += ["--guest-host", host] if host is not None else []
    argv += ["--guest-console", str(g.console if console == "ok" else console)] if console is not None else []
    argv += ["--guest-image", str(g.image if image == "ok" else image)] if image is not None else []
    return argv


@pytest.mark.parametrize("change, why", [
    (dict(repeat="2"), "--repeat 2"),
    (dict(spec=("s", "t")), "2 specs"),
    (dict(console=None), "no guest console"),
    (dict(console="/nonexistent/serial.log"), "no guest console"),
    (dict(host="127.0.0.1"), "loopback"),
    (dict(host="127.3.2.1"), "loopback"),
    (dict(host="0.0.0.0"), "loopback"),
    (dict(host="localhost"), "not an IPv4 address"),
    (dict(image=None), "no guest image"),
    ("stale", "not fresh"),
])
def test_guest_mode_refuses_before_anything_is_prepared(tmp_path, monkeypatch, change, why):
    g = _guest_main(tmp_path, monkeypatch)
    if change == "stale":
        with open(g.console, "ab") as f:
            f.write(_salt([MISS_LINE]))
        change = {}
    with pytest.raises(step3.StepError, match=re.escape(why)):
        step3.main(_guest_argv(g, **change))
    assert g.built == [] and not (tmp_path / "runs").exists()


def test_guest_mode_reaches_the_context_with_its_host_console_and_image_and_native_takes_no_guest_option(tmp_path, monkeypatch):
    g = _guest_main(tmp_path, monkeypatch)
    with pytest.raises(g.Stop):
        step3.main(_guest_argv(g))
    with pytest.raises(g.Stop):
        step3.main(_guest_argv(g, host=None))       # the default host: the guest's address on br0
    assert g.built == [dict(mode="replay", monitor="guest", guest_host=h, guest_console=g.console, guest_image=g.image)
                       for h in (GUEST, step3.GUEST_HOST)], g.built
    assert step3.GUEST_HOST == "192.168.100.10"
    for opt in (["--guest-console", str(g.console)], ["--guest-host", GUEST], ["--guest-image", str(g.image)]):
        with pytest.raises(step3.StepError, match="--monitor guest"):
            step3.main(["run", "--mode", "replay", "--spec", "s", "--name", "n"] + opt)
    with pytest.raises(g.Stop):
        step3.main(["run", "--mode", "replay", "--spec", "s", "t", "--repeat", "2", "--name", "n"])     # native: as before
    assert g.built[-1] == {"mode": "replay"}


def test_compare_modes_leaves_out_and_names_an_unlisted_modes_run_and_wants_every_listed_one():
    two = ("broker", "replay")
    res = step3.compare_results([_result(m, GOOD) for m in two], _no_frames, two)
    assert res["ok"] and res["modes"] == ["broker", "replay"] and res["left_out"] == []
    odd_can = _result("can", GOOD[:2] + [(None, STALE)])
    res = step3.compare_results([_result("broker", GOOD), odd_can, _result("replay", GOOD)], _no_frames, two)
    assert res["ok"] and res["left_out"] == [{"run": odd_can["run"], "mode": "can", "dir": odd_can["dir"]}], res["left_out"]
    assert [r["mode"] for r in res["groups"][0]["runs"]] == ["broker", "replay"]
    res = step3.compare_results([_result("broker", GOOD)], _no_frames, two)
    assert not res["ok"] and res["groups"][0]["modes"]["missing_modes"] == ["replay"]
    assert not step3.compare_results([_result(m, GOOD) for m in two], _no_frames)["ok"], "the default wants all three, as before"
    assert step3.compare_results([_result(m, GOOD) for m in step3.MODES], _no_frames)["left_out"] == []


def test_compare_takes_modes_on_its_command_line(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "RUNS", tmp_path / "runs")
    dirs = {}
    for m in step3.MODES:
        d = tmp_path / m
        (d / "r").mkdir(parents=True)
        (d / "r" / "result.json").write_text(json.dumps(_result(m, GOOD)), encoding="utf-8")
        dirs[m] = str(d)
    assert step3.main(["compare", "--name", "c1", dirs["broker"], dirs["replay"], "--modes", "broker", "replay"]) == 0
    assert step3.main(["compare", "--name", "c2", dirs["broker"], dirs["replay"]]) == 1, "without --modes all three are wanted"
    assert step3.main(["compare", "--name", "c3", "--modes", "broker", "replay", "--", dirs["broker"], dirs["replay"], dirs["can"]]) == 0
    out = json.loads(next((tmp_path / "runs").glob("*-c3")).joinpath("compare.json").read_text(encoding="utf-8"))
    assert out["modes"] == ["broker", "replay"] and [x["mode"] for x in out["left_out"]] == ["can"] and len(out["inputs"]) == 3
    assert step3.main(["compare", "--name", "c4", dirs["broker"], "--modes", "broker", "replay"]) == 1, "a listed mode is missing"
    assert step3.main(["compare", "--name", "c5", dirs["replay"], "--modes", "replay"]) == 0
    # an unknown mode; a directory taken for a mode (the directories go first, or after --)
    for bad in (["--modes", "dumpfile", "--", dirs["broker"]], ["--modes", "replay", dirs["replay"]]):
        with pytest.raises(SystemExit):
            step3.main(["compare"] + bad)


# ============================================================ integration (opt-in)

def _rec_dir() -> Path:
    return Path(os.environ.get("SDV_RECORDING", "")).expanduser()


@pytest.mark.skipif(os.environ.get("SDV_STEP3") != "1" or not os.environ.get("SDV_BRIDGE_IMAGE") or not (_rec_dir() / "events.json").is_file(),
                    reason="the step-3 integration runs only with SDV_STEP3=1, SDV_BRIDGE_IMAGE and SDV_RECORDING an injected recording "
                           "(Docker, sudo -n for vcan0, ~4 min)")
def test_step3_injected_stop_in_every_mode_and_the_comparison():
    """step3.py in the sim venv (python-can and cantools), as the stack's own exit test runs stack.py."""
    tag = "%d" % int(time.time())
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    runs = Path(os.environ.get("SDV_RUNS", "~/sdv-runs")).expanduser()

    def step3_cli(*args):
        return subprocess.run([str(tsbs.SIM_PY), str(STACK_DIR / "step3.py"), *args], capture_output=True, text=True, env=env, cwd=str(REPO),
                              timeout=1200)
    names = []
    for mode in step3.MODES:
        name = "step3-it-%s-%s" % (mode, tag)
        p = step3_cli("run", "--mode", mode, "--spec", "injected-stop", "--name", name)
        assert p.returncode == 0, (mode, p.stdout[-3000:], p.stderr[-3000:])
        names.append(next(runs.glob("*-%s" % name)))
    p = step3_cli("compare", "--name", "step3-it-compare-%s" % tag, *[str(n) for n in names])
    assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
    results: Dict[str, Any] = {r["mode"]: r for r in step3.find_results(names)}
    assert set(results) == set(step3.MODES) and all(r["ok"] for r in results.values()), {m: r["gates"] for m, r in results.items()}


def _eth0_ipv4() -> Optional[str]:
    """WSL's eth0 IPv4 (gap 4z): the stand-in guest's address, a real non-loopback target; None when there is none."""
    try:
        p = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", "eth0"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for m in re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+)/", p.stdout):
        a = ipaddress.IPv4Address(m.group(1))
        if not (a.is_loopback or a.is_unspecified):
            return str(a)
    return None


class _SerialRelay:
    """The stand-in guest's console: the native monitor's stdout copied into a file the way QEMU's serial log holds a
    console (two NULs first, CRLF line ends with a NUL after each, a NUL inside each `vss rules:`)."""

    def __init__(self, proc: subprocess.Popen, path: Path) -> None:
        self.proc, self.path = proc, path
        self.f = open(path, "wb")
        self.f.write(b"\0\0")
        self.f.flush()
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self) -> None:
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                return
            self.f.write(chunk.replace(b"vss rules:", b"vss\0 rules:").replace(b"\n", b"\r\n\0"))
            self.f.flush()

    def text(self) -> str:
        return step3.strip_console(self.path.read_bytes())

    def close(self) -> None:
        self.t.join(timeout=10)
        self.f.close()


def _honest_recording() -> bool:
    return (_rec_dir() / "sigsim.log").is_file() and not (_rec_dir() / "events.json").is_file()


@pytest.mark.skipif(os.environ.get("SDV_STEP3_GUEST") != "1" or not os.environ.get("SDV_BRIDGE_IMAGE") or not _honest_recording(),
                    reason="the guest-mode integration runs only with SDV_STEP3_GUEST=1, SDV_BRIDGE_IMAGE and SDV_RECORDING an honest "
                           "recording (Docker, gcc for the stand-in, a few minutes)")
def test_step3_in_guest_mode_against_a_stand_in_guest_and_compare_modes_replay(tmp_path):
    """The stand-in guest is the native vss monitor (`7160 svc 500`, INADDR_ANY), started before step3, its stdout relayed
    into a console file salted as QEMU's serial log is; step3 reaches it at WSL's eth0 IPv4 in guest mode, then
    `compare --modes replay`. Every gate passes: the listener gate with no allowance (the stand-in listened before the
    first snapshot), C12b on the salted console."""
    host = _eth0_ipv4()
    if host is None:
        pytest.skip("no non-loopback IPv4 on eth0 (gap 4z)")
    if not (sys.platform.startswith("linux") and shutil.which("gcc")):
        pytest.skip("the stand-in needs Linux and gcc")
    with socket.socket() as s:
        try:
            s.bind(("0.0.0.0", st.MONITOR_PORT))
        except OSError:
            pytest.skip(":%d is taken on this host" % st.MONITOR_PORT)
    out = tmp_path / "bin" / st.MONITOR_BIN
    st.build_native_monitor(out)
    console = tmp_path / "guest-serial.log"
    image = tmp_path / "ifs-stand-in.bin"
    image.write_bytes(b"a stand-in for the guest image: the native vss monitor plays the guest here\n")
    proc = subprocess.Popen([str(out), str(st.MONITOR_PORT), "svc", str(st.MONITOR_DEADLINE_MS)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    relay = _SerialRelay(proc, console)
    tag = "%d" % int(time.time())
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    runs = Path(os.environ.get("SDV_RUNS", "~/sdv-runs")).expanduser()

    def step3_cli(*args):
        return subprocess.run([str(tsbs.SIM_PY), str(STACK_DIR / "step3.py"), *args], capture_output=True, text=True, env=env, cwd=str(REPO),
                              timeout=1200)
    try:
        st.wait_for(lambda: "service monitor listening on :%d " % st.MONITOR_PORT in relay.text(), 20, "the stand-in's svc banner")
        # WP5's readiness check: a connect and close on :7160 with no bytes, which leaves a seen=0 line, as the launch probe does
        socket.create_connection((host, st.MONITOR_PORT), timeout=5).close()
        st.wait_for(lambda: PROBE_DONE in relay.text(), 10, "the readiness check's seen=0 line")
        name = "step3-guest-it-%s" % tag
        p = step3_cli("run", "--mode", "replay", "--spec", "honest", "--name", name, "--monitor", "guest", "--guest-host", host,
                      "--guest-console", str(console), "--guest-image", str(image))
        assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
        run_dir = next(runs.glob("*-%s" % name))
        p = step3_cli("compare", "--name", "step3-guest-it-compare-%s" % tag, str(run_dir), "--modes", "replay")
        assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
        compare = json.loads(next(runs.glob("*-step3-guest-it-compare-%s" % tag)).joinpath("compare.json").read_text(encoding="utf-8"))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)
        relay.close()
    assert proc.returncode == 0 and "monitor: stopped (liveness misses=" in relay.text()
    (r,) = step3.find_results([run_dir])
    assert r["ok"] and r["mode"] == "replay" and r["spec"] == "honest", {g: v for g, v in r["gates"].items() if not v}
    assert all(r["gates"][g] for g in ("console", "console_end", "c12b", "listeners", "reason_set", "ticked_through"))
    assert r["monitor"] == hashlib.sha256(image.read_bytes()).hexdigest() and r["console_end"]["seen"] > 0
    assert r["console_gate"]["ok"] and r["console_file"]["raw"]["path"] == str(console) and r["c12b_lines"] == 1, "one instance here"
    assert r["console"]["garbled_lines"] == 0 and r["console_end"]["problems"] == [], (r["console"], r["console_end"])
    comp = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["components"][st.VSS_MONITOR_GUEST]
    assert comp["host_local"] is True, "the PC's stand-in is this host (SDV_HOST_ROLE pc), and the record says so"
    raw = console.read_bytes()
    assert b"\0" in raw and b"\r\n" in raw and attr.vss_rules_lines(raw.decode("utf-8", "replace")) == [], "the console was salted"
    copy = (Path(r["dir"]) / step3.GUEST_CONSOLE).read_bytes()
    assert b"\0" not in copy and b"\r" not in copy and not (Path(r["dir"]) / "monitor.log").exists()
    assert compare["ok"] and compare["modes"] == ["replay"] and compare["left_out"] == []
