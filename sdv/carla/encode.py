#!/usr/bin/env python3
"""encode.py -- a CARLA take as the stack's kind of recording directory (sdv/carla).

Local branch only (decision 15). Phase 7 spec 4 item 6 and 2.3. Runs in WSL Ubuntu-24.04 with the sim venv's Python
(cantools and python-can, sdv/sim/requirements.lock), from the repo root.

    usage: encode.py record --take DIR --name N [--root DIR]     # writes ROOT/<N>/ (ROOT default ~/sdv-recordings)
           encode.py verify DIR                                  # re-verifies a recording against the current contract

RECORD reads the take (carla_capture.py's output) and refuses, before anything is written: a take whose take.sha256 does not
hold; a name that is not the take's; a take that did not complete; versions, town or blueprint that are not the
capture's; world settings (capture.json's world_settings) that are not worldtie.py's tie of the generated step, each of
the six read-back keys present; steps that do not become current in strictly increasing order (sendpolicy.schedule's
rule: a wall time of zero or less has no RTF); a gap, a skipped frame, an RTF max above 1 (or a min not above 0), each
recomputed from steps.jsonl with sendpolicy.py (the RTF's advance counted in steps of the generated length, so the
server's single-precision step is not read as the pacing failing), and a capture.json that disagrees with that
recomputation (a take recorded with another computation of the RTF is taken again, never re-read with that one); the
carla run type's live-default profile (LIVE_DEFAULT_PROFILE["carla"], id 3) not compiled in the generation, since the
guest would answer 8 to every frame; a take wheelbase other than that profile's L; a step whose gear and reverse
disagree; a value outside slice.dbc's range, the step named, never clamped. main refuses a root inside the repository
(sigsim's rule: only sdv-out/, which git ignores) and record an existing directory, which it leaves alone. Every
refusal, a missing generation and an existing directory included, prints "encode.py: refused: ..." and exits 2 (1 is a
recording that failed verify). Each step goes
through sdv/sim/carla_iso.py (the one place the conversion is written), each frame through cantools (database strict),
the log by sendpolicy's schedule: the dynamics message at every period instant and the gear message at every one of its
own from 0, each from the step current at that instant while it has been current for no longer than
FEEDER_REPEAT_CAP_MS, otherwise no frame. Then, in
this order: carla.log (candump -l text, channel vcan0, timestamps those instants), carla.log.sha256, steps.jsonl (the
take's, byte for byte), verify, summary.json, and manifest-line.json, written last and only when verify passed. A
recording that fails verify, or stops for any other reason once its directory exists, is renamed <name>.failed and has
no manifest line (sigsim's rule).

VERIFY passes only when every term of OK_TERMS holds: all_frames_accepted (every dynamics frame of the decoded log,
packed as a replay-mode bridge packs it, judged ACCEPT by sdv/frame/rules.py under that profile); message_counts and
no_period_errors (against the schedule); within_half_lsb (cantools' decode of every frame against carla_iso's values of
its step, the gear exactly); regenerated_identical (the log made again from steps.jsonl equal byte for byte);
python_can_reader (python-can's reader reads every line as a frame on vcan0); segments_complete (drive.py's segments,
each once, in order, each step in its segment's gear); app_switches_as_designed (sdv/stack/replaycheck.predict on the
decoded log: one switch on inside the hard brake's on-window, one off inside its off-window, nothing else);
gear_agrees (reverse set exactly in gear -1 on every step). ok also wants carla.log.sha256 to hold for carla.log
(log_sha256_file_holds, reported beside the terms: the stack and the injector read that file, so a recording whose file
is wrong is not ok; it is not one of spec 4 item 6's terms, which stay nine). Of sigsim's verify keys it keeps ok,
ok_terms, judge, cantools_decode, python_can_reader, regenerated_identical, log, log_bytes and log_sha256; python_can_writer
and trip_clamps (sigsim's clamp, which a CARLA take has not) are left out.

PENDING-PROBE: should a value of the conversion (carla_iso.pending()) or the take's drive values wait for a probe again,
summary.json's trip.pending_probe names them and record says so on stderr; WP0's probes have settled all of them, so today
it is empty.

DOES NOT DEMONSTRATE: vehicle dynamics, CAN timing (the timestamps are a send schedule, and vcan has no arbitration, error
frames or bus timing), perception, or any timing. That every frame passes the reference rules shows the take agrees
with the rules' own kinematic model, not that the rules are right.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _d in (str(HERE), str(REPO / "sdv" / "sim"), str(REPO / "sdv" / "frame"), str(REPO / "sdv" / "stack")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla_iso  # noqa: E402
import drive  # noqa: E402
import replaycheck as rc  # noqa: E402
import rules  # noqa: E402
import sendpolicy  # noqa: E402
import sigsim  # noqa: E402
import vssframe as vf  # noqa: E402
import worldtie  # noqa: E402

DBC_PATH = sigsim.DBC_PATH
RUN_TYPE = "carla"
GENERATOR = "carla"
TOWN = "Town01"
VERSION = "0.9.16"
BLUEPRINT = "vehicle.toyota.prius"
CHANNEL = "vcan0"
LOG_NAME = "carla.log"
SHA_NAME = LOG_NAME + ".sha256"
STEPS_NAME = "steps.jsonl"
SUMMARY_NAME = "summary.json"
MANIFEST_NAME = "manifest-line.json"
TAKE_FILES = ("steps.jsonl", "script.jsonl", "capture.json")
STEP_KEYS = ("i", "frame", "elapsed_s", "t_vals_ns", "t_cur_ns", "seg", "gear", "v", "a", "fwd", "w", "steer", "throttle",
             "brake", "reverse", "wheel_deg")
DEFAULT_ROOT = Path("~/sdv-recordings")
TIMESTAMPS = "feeder send schedule from zero"
ENCODER_MODULES = ("sdv/carla/encode.py", "sdv/carla/sendpolicy.py", "sdv/carla/drive.py", "sdv/carla/worldtie.py",
                   "sdv/sim/carla_iso.py")
OK_TERMS = ("all_frames_accepted", "message_counts", "no_period_errors", "within_half_lsb", "regenerated_identical",
            "python_can_reader", "segments_complete", "app_switches_as_designed", "gear_agrees")
NAME_RE = re.compile(r"(\d{8})-carla-(\d+)([a-z][a-z0-9]{0,7})?")


class EncodeError(ValueError):
    """A take or a recording this module refuses."""


def load_contract() -> Any:
    return vf.load_contract()


def load_dbc(contract: Any, path: Optional[Path] = None) -> Any:
    """slice.dbc (or the DBC at path) through cantools (strict), checked against the generated contract: every slot signal
    in its message with the contract's unit, the two periods equal to DBC_PERIOD_MS, the dynamics message the lower id."""
    import cantools  # the sim venv (sdv/sim/requirements.lock)
    db = cantools.database.load_file(str(path if path is not None else DBC_PATH), strict=True)
    c = contract
    for i, sig in enumerate(c.SLOT_DBC_SIGNALS):
        s = db.get_message_by_name(c.SLOT_DBC_MESSAGES[i]).get_signal_by_name(sig)
        if (s.unit or None) != c.SLOT_DBC_UNITS[i]:
            raise EncodeError("%s: cantools unit %r, contract %r" % (sig, s.unit, c.SLOT_DBC_UNITS[i]))
    pol = sendpolicy.Policy.from_contract(c)
    for name, period in ((pol.dyn_msg, pol.dyn_period_ms), (pol.gear_msg, pol.gear_period_ms)):
        if db.get_message_by_name(name).cycle_time != period:
            raise EncodeError("%s: cantools cycle_time %r, contract %r" % (name, db.get_message_by_name(name).cycle_time, period))
    if db.get_message_by_name(pol.dyn_msg).frame_id >= db.get_message_by_name(pol.gear_msg).frame_id:
        raise EncodeError("the dynamics message must have the lower CAN id (log order at equal timestamps)")
    return db


def read_log(path: Path) -> List[Tuple[float, int, bytes, Any]]:
    """The log through python-can's reader (sigsim's): (timestamp, id, data, channel)."""
    return sigsim.read_log(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    """Every file of a recording is written through here (the tests read the order)."""
    path.write_bytes(data)


# --- the take ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Take:
    dir: Path
    capture: Dict[str, Any]
    steps: List[Dict[str, Any]]
    steps_bytes: bytes
    take_sha256: str


@dataclass(frozen=True)
class Checked:
    profile_id: int
    l_mm: int
    rtf: Dict[str, float]
    front_max_steer_deg: List[float]


def read_take(take_dir: Path) -> Take:
    """The take, after its take.sha256 holds for exactly its three files."""
    d = Path(take_dir)
    try:
        sums = (d / "take.sha256").read_bytes()
    except OSError as e:
        raise EncodeError("the take %s has no readable take.sha256: %s" % (d, e)) from e
    lines = sums.decode("ascii", errors="replace").splitlines()
    names = [ln.split("  ", 1)[1] if "  " in ln else None for ln in lines]
    if names != list(TAKE_FILES):
        raise EncodeError("the take's take.sha256 lists %r, not %r" % (names, list(TAKE_FILES)))
    raw: Dict[str, bytes] = {}
    for ln in lines:
        sha, name = ln.split("  ", 1)
        try:
            raw[name] = (d / name).read_bytes()
        except OSError as e:
            raise EncodeError("the take has no readable %s: %s" % (name, e)) from e
        if _sha256(raw[name]) != sha:
            raise EncodeError("the take's take.sha256 does not hold for %s" % name)
    try:
        cap = json.loads(raw["capture.json"].decode("utf-8"))
        steps = [json.loads(x) for x in raw["steps.jsonl"].decode("ascii").splitlines()]
    except ValueError as e:
        raise EncodeError("the take's files are not the capture's JSON: %s" % e) from e
    for s in steps:
        if not isinstance(s, dict) or tuple(s) != STEP_KEYS:
            raise EncodeError("a step of steps.jsonl does not have exactly the keys %s" % ", ".join(STEP_KEYS))
    return Take(d, cap, steps, raw["steps.jsonl"], _sha256(sums))


def profile_of(contract: Any) -> Tuple[int, Dict[str, Any]]:
    """The carla run type's live-default profile, refused unless the generation compiles it."""
    pid = int(contract.LIVE_DEFAULT_PROFILE[RUN_TYPE])
    if pid not in tuple(contract.COMPILED_PROFILE_IDS):
        raise EncodeError("profile %d (the carla live default) is not compiled in this generation: the guest would answer 8" % pid)
    return pid, {int(r["id"]): r for r in contract.PROFILES}[pid]


def check_take(t: Take, contract: Any, pol: Any) -> Checked:
    """Every refusal of a take before anything is written (the module docstring's RECORD)."""
    cap, steps = t.capture, t.steps
    if cap.get("format") != 1:
        raise EncodeError("capture.json's format is %r, not 1" % (cap.get("format"),))
    if cap.get("completed") is not True or cap.get("errors"):
        raise EncodeError("the take did not complete: %r" % (cap.get("errors"),))
    if cap.get("client_version") != VERSION or cap.get("server_version") != VERSION:
        raise EncodeError("the take's client %r and server %r are not both %s" % (cap.get("client_version"), cap.get("server_version"), VERSION))
    if str(cap.get("map", "")).split("/")[-1] != TOWN or cap.get("blueprint") != BLUEPRINT:
        raise EncodeError("the take's map %r and blueprint %r are not %s and %s" % (cap.get("map"), cap.get("blueprint"), TOWN, BLUEPRINT))
    ws = cap.get("world_settings")
    tie = worldtie.tie_problems(ws, pol.step_s) if isinstance(ws, dict) else ["no world_settings recorded"]
    if tie:
        raise EncodeError("the take's world settings are not the tie of the generated step: %s" % "; ".join(tie))
    if len(steps) < 2 or [s["i"] for s in steps] != list(range(len(steps))) or steps[0]["t_cur_ns"] != 0:
        raise EncodeError("steps.jsonl is not a sequence of steps from 0 with step 0 current at 0")
    frames = [s["frame"] for s in steps]
    elapsed = [s["elapsed_s"] for s in steps]
    t_cur = [s["t_cur_ns"] for s in steps]
    behind = [k for k in range(1, len(t_cur)) if t_cur[k] <= t_cur[k - 1]]
    if behind:
        raise EncodeError("steps must become current in increasing order: not at steps %s" % behind[:20])
    skipped = sendpolicy.skipped_frames(frames)
    if skipped:
        raise EncodeError("a skipped frame at steps %s" % skipped[:20])
    gaps = sendpolicy.gaps(frames, t_cur, pol.cap_ns)
    if gaps:
        raise EncodeError("a gap at steps %s" % gaps[:20])
    rtf = sendpolicy.rtf_summary(elapsed, t_cur, pol.step_ns)
    if rtf["max"] > 1:
        raise EncodeError("the take's RTF max %r is above 1: the pacing did not hold" % rtf["max"])
    if not rtf["min"] > 0:
        raise EncodeError("the take's RTF min %r is not above 0" % rtf["min"])
    for key, want in (("steps", len(steps)), ("rtf", rtf), ("gaps", gaps), ("skipped_frames", skipped)):
        if cap.get(key) != want:
            raise EncodeError("capture.json's %s %r disagrees with its steps (%r)" % (key, cap.get(key), want))
    pid, row = profile_of(contract)
    ego = cap.get("ego") or {}
    if ego.get("wheelbase_mm") != int(row["l_mm"]):
        raise EncodeError("the take's wheelbase %r mm is not profile %d's L %r mm" % (ego.get("wheelbase_mm"), pid, row["l_mm"]))
    front = list(ego.get("front_max_steer_deg") or [])
    return Checked(pid, int(row["l_mm"]), rtf, front)


def iso_values(steps: Sequence[Dict[str, Any]], front: Sequence[float]) -> List[Tuple[float, float, float, float, int]]:
    """Every step through carla_iso.convert (spec 2.7), a refusal naming the step."""
    out = []
    for s in steps:
        try:
            out.append(carla_iso.convert(s, front))
        except (carla_iso.ConversionError, ValueError) as e:
            raise EncodeError("step %d: %s" % (s["i"], e)) from e
    return out


def dbc_ranges(db: Any, contract: Any) -> Dict[str, Tuple[float, float]]:
    out = {}
    for i, sig in enumerate(contract.SLOT_DBC_SIGNALS):
        s = db.get_message_by_name(contract.SLOT_DBC_MESSAGES[i]).get_signal_by_name(sig)
        out[sig] = (s.minimum, s.maximum)
    return out


def range_problems(items: Sequence[Tuple[int, Dict[str, float]]], ranges: Dict[str, Tuple[float, float]]) -> List[str]:
    """Every value outside its signal's slice.dbc range, the step named (never clamped)."""
    out = []
    for i, vals in items:
        for sig, x in vals.items():
            lo, hi = ranges[sig]
            if not (lo <= x <= hi):
                out.append("step %d: %s %r outside slice.dbc's range [%r, %r] (never clamped)" % (i, sig, x, lo, hi))
    return out


def encode_frames(steps: Sequence[Dict[str, Any]], values: Sequence[Tuple[Any, ...]], pol: Any, db: Any,
                  signals: Sequence[str]) -> Tuple[List[Tuple[int, int, bytes]], List[sendpolicy.Frame]]:
    """(the log's frames as (t_ms, CAN id, data), the schedule) of the take by sendpolicy's schedule."""
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    dyn, gear = db.get_message_by_name(pol.dyn_msg), db.get_message_by_name(pol.gear_msg)
    frames = []
    for t, msg, i in sched:
        if msg == pol.dyn_msg:
            frames.append((t, dyn.frame_id, bytes(dyn.encode(dict(zip(signals[:4], values[i][:4]))))))
        else:
            frames.append((t, gear.frame_id, bytes(gear.encode({signals[4]: values[i][4]}))))
    return frames, sched


def segments_ms(steps: Sequence[Dict[str, Any]]) -> List[List[Any]]:
    """[name, start_ms, end_ms] on the log's clock: the moments the segment's first and last steps became current (the
    hard brake's last step is the one at which the vehicle reads as stopped, where sigsim's segment ends too)."""
    out: List[List[Any]] = []
    for s in steps:
        t = s["t_cur_ns"] // sendpolicy.NS_PER_MS
        if out and out[-1][0] == s["seg"]:
            out[-1][2] = t
        else:
            out.append([s["seg"], t, t])
    return out


def gear_changes(steps: Sequence[Dict[str, Any]]) -> List[List[int]]:
    return [[steps[k]["t_cur_ns"] // sendpolicy.NS_PER_MS, steps[k - 1]["gear"], steps[k]["gear"]]
            for k in range(1, len(steps)) if steps[k]["gear"] != steps[k - 1]["gear"]]


def segments_term(steps: Sequence[Dict[str, Any]]) -> bool:
    """drive.py's segments, each exactly once, in order, and every step in its segment's gear."""
    runs: List[str] = []
    for s in steps:
        if not runs or runs[-1] != s["seg"]:
            runs.append(s["seg"])
    return runs == list(drive.SEGMENTS) and all(s["gear"] == drive.SEGMENT_GEAR.get(s["seg"]) for s in steps)


def gear_term(steps: Sequence[Dict[str, Any]]) -> bool:
    """Spec 2.7's rule on every step: reverse set exactly when the gear is -1."""
    return all(isinstance(s["reverse"], bool) and s["reverse"] == (s["gear"] == -1) for s in steps)


def app_term(prediction: Sequence[Dict[str, Any]], windows: Dict[str, Any]) -> bool:
    """One switch on inside the on-window, then one off inside the off-window, and no other switch."""
    return (len(prediction) == 2 and prediction[0]["hazard"] is True and prediction[1]["hazard"] is False
            and rc.in_window(prediction[0]["t_rec_ms"], windows["on_window_ms"])
            and rc.in_window(prediction[1]["t_rec_ms"], windows["off_window_ms"]))


def verify_terms(*, stats: Any, regenerated_identical: bool, per_message: Dict[str, int], expected: Dict[str, int], period_errors: int,
                 within_half_lsb: bool, python_can_ok: bool, segments_ok: bool, app_ok: bool, gear_ok: bool) -> Dict[str, bool]:
    """The terms of verify's ok, in OK_TERMS order."""
    return {
        "all_frames_accepted": stats.frames > 0 and stats.accepted == stats.frames,
        "message_counts": per_message == expected,
        "no_period_errors": period_errors == 0,
        "within_half_lsb": within_half_lsb,
        "regenerated_identical": regenerated_identical,
        "python_can_reader": python_can_ok,
        "segments_complete": segments_ok,
        "app_switches_as_designed": app_ok,
        "gear_agrees": gear_ok,
    }


def _setup(contract: Any, pid: int, row: Dict[str, Any], pol: Any) -> Any:
    """sigsim's Setup for judging a CARLA log under profile pid (judge_stream packs and judges as the replay mode does)."""
    return sigsim.Setup(contract=contract, env=sigsim.Envelope.from_contract(contract), profile_id=pid, profile=dict(row),
                        dyn_msg=pol.dyn_msg, gear_msg=pol.gear_msg, signals=tuple(contract.SLOT_DBC_SIGNALS),
                        periods_ms={pol.dyn_msg: pol.dyn_period_ms, pol.gear_msg: pol.gear_period_ms})


def verify(rec_dir: Path, contract: Any = None, front_max: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """Re-verify a recording directory (the module docstring's VERIFY). front_max is the take's front wheels'
    max_steer_angle; without it, summary.json's trip.conversion gives it."""
    c = contract if contract is not None else load_contract()
    d = Path(rec_dir)
    pol = sendpolicy.Policy.from_contract(c)
    pid, row = profile_of(c)
    db = load_dbc(c)
    signals = tuple(c.SLOT_DBC_SIGNALS)
    if front_max is None:
        front_max = json.loads((d / SUMMARY_NAME).read_text(encoding="utf-8"))["trip"]["conversion"]["front_max_steer_deg"]
    log = d / LOG_NAME
    raw = log.read_bytes()
    sha = _sha256(raw)
    sha_file = (d / SHA_NAME).read_text(encoding="ascii") if (d / SHA_NAME).is_file() else ""
    steps = [json.loads(x) for x in (d / STEPS_NAME).read_text(encoding="ascii").splitlines()]
    problems: List[str] = []
    gear_ok = gear_term(steps)
    values: Optional[List[Tuple[float, float, float, float, int]]] = None
    try:
        values = iso_values(steps, front_max)
    except EncodeError as e:
        problems.append(str(e))
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    expected = sendpolicy.counts(sched)
    regenerated = False
    if values is not None:
        frames, _s = encode_frames(steps, values, pol, db, signals)
        regenerated = raw == sigsim.candump_text(frames, CHANNEL).encode("ascii")
    try:
        msgs = read_log(log)
        reader_error = None
    except Exception as e:  # noqa: BLE001 - a log python-can cannot read fails its term
        msgs, reader_error = [], "%s: %s" % (type(e).__name__, e)
    lines = raw.decode("ascii", errors="replace").splitlines()
    channels = sorted({str(m[3]) for m in msgs})
    python_can_ok = reader_error is None and len(msgs) == len(lines) and channels == [CHANNEL]
    by_id = {db.get_message_by_name(n).frame_id: n for n in (pol.dyn_msg, pol.gear_msg)}
    period = {pol.dyn_msg: pol.dyn_period_ms, pol.gear_msg: pol.gear_period_ms}
    lsb = {s.name: s.scale for m in db.messages for s in m.signals}
    per_message = {n: 0 for n in by_id.values()}
    last_t: Dict[str, int] = {}
    period_errors = 0
    worst = {s: 0.0 for s in signals[:4]}
    gear_mismatches = 0
    matched = values is not None and len(msgs) == len(sched)
    stream: List[Tuple[int, str, Tuple[Any, ...]]] = []
    decoded: List[Tuple[int, str, Dict[str, Any]]] = []
    for k, (ts, cid, data, _ch) in enumerate(msgs):
        name = by_id.get(cid)
        if name is None:
            problems.append("an unknown CAN id 0x%X" % cid)
            matched = False
            continue
        t_ms = int(round(ts * 1000.0))
        if abs(ts * 1000.0 - t_ms) > 1e-6:
            period_errors += 1
        if name in last_t and t_ms - last_t[name] != period[name]:
            period_errors += 1
        last_t[name] = t_ms
        per_message[name] += 1
        dec = db.decode_message(cid, data, decode_choices=False)
        decoded.append((t_ms, name, dict(dec)))
        step_vals = values[sched[k][2]] if matched and values is not None and sched[k][1] == name else None
        if matched and step_vals is None:
            matched = False
        if name == pol.dyn_msg:
            vals = tuple(float(dec[s]) for s in signals[:4])
            stream.append((t_ms, name, vals))
            if step_vals is not None:
                for s, got, want in zip(signals[:4], vals, step_vals[:4]):
                    worst[s] = max(worst[s], abs(got - want))
        else:
            g = int(dec[signals[4]])
            stream.append((t_ms, name, (g,)))
            if step_vals is not None:
                gear_mismatches += int(g != step_vals[4])
    within = matched and gear_mismatches == 0 and all(worst[s] <= lsb[s] / 2 + 1e-9 for s in worst)
    stats = sigsim.judge_stream(stream, _setup(c, pid, row, pol), rules.Tables.from_contract(c), pid)
    segs = segments_ms(steps)
    app: Dict[str, Any] = {"prediction": [], "windows": None, "error": None}
    try:
        app["windows"] = rc.expected_windows({"segments": segs}, decoded, signals[0], pol.dyn_period_ms)
        app["prediction"] = rc.predict(decoded, signals[0], signals[1], rc.hazard_module())
        app_ok = app_term(app["prediction"], app["windows"])
    except ValueError as e:
        app["error"] = str(e)
        app_ok = False
    terms = verify_terms(stats=stats, regenerated_identical=regenerated, per_message=per_message, expected=expected,
                         period_errors=period_errors, within_half_lsb=within, python_can_ok=python_can_ok,
                         segments_ok=segments_term(steps), app_ok=app_ok, gear_ok=gear_ok)
    sha_holds = sha_file == "%s  %s\n" % (sha, LOG_NAME)
    return {
        "log": str(log), "log_sha256": sha, "log_bytes": len(raw), "log_sha256_file_holds": sha_holds,
        "regenerated_identical": regenerated,
        "python_can_reader": {"frames": len(msgs), "lines": len(lines), "channels": channels, "per_message": per_message,
                              "expected_per_message": expected, "period_errors": period_errors, "error": reader_error},
        "cantools_decode": {"max_abs_error": worst, "half_lsb": {s: lsb[s] / 2 for s in worst}, "within_half_lsb": within,
                            "gear_mismatches": gear_mismatches},
        "judge": stats.as_dict(), "app": app, "segments": [s[0] for s in segs], "problems": problems,
        "ok_terms": terms, "ok": all(terms.values()) and sha_holds,
    }


# --- the recording -------------------------------------------------------------------------------------------------

def params_of(contract: Any, seed: int) -> Dict[str, Any]:
    """The manifest line's five source.params (the injector adds three; the scenario entry's cap is eight)."""
    return {"catalog_digest": "0x%08X" % contract.CATALOG_DIGEST, "dbc_sha256": _sha256(DBC_PATH.read_bytes()), "seed": seed,
            "town": TOWN, "version": VERSION}


def manifest_line(name: str, path: str, sha: str, contract: Any, seed: int, rtf: Dict[str, float], pid: int, l_mm: int) -> Dict[str, Any]:
    """The recording's scenario entry (spec 2.3)."""
    return {"name": name, "profile_id": pid,
            "recording": {"format": "candump-log", "path": path, "sha256": sha},
            "source": {"generator": GENERATOR, "params": params_of(contract, seed),
                       "rtf": {"max": rtf["max"], "mean": rtf["mean"], "min": rtf["min"]},
                       "vehicle": {"name": BLUEPRINT, "wheelbase_mm": l_mm}}}


def log_path_shown(out_dir: Path) -> Optional[str]:
    """The manifest line's path for a recording under DEFAULT_ROOT, in DEFAULT_ROOT's ~ spelling; None elsewhere."""
    try:
        rest = out_dir.expanduser().resolve().relative_to(DEFAULT_ROOT.expanduser().resolve())
    except ValueError:
        return None
    return str(DEFAULT_ROOT / rest / LOG_NAME)


def encoder_sha256() -> Dict[str, str]:
    return {rel: _sha256((REPO / rel).read_bytes()) for rel in ENCODER_MODULES}


def pending_of(take: Take) -> Dict[str, Any]:
    pend = dict(carla_iso.pending())
    taken = (take.capture.get("pending_probe") or {}).get("drive_values")
    if taken is not None:
        pend["drive_values"] = taken
    return pend


def record(take_dir: Path, out_dir: Path, name: str, manifest_path: Optional[str] = None, contract: Any = None) -> Dict[str, Any]:
    """Write a recording directory from a take (the module docstring's RECORD). Everything is computed and checked in
    memory first; the directory's creation is outside the rename (an existing one is somebody's and is left alone)."""
    c = contract if contract is not None else load_contract()
    take = read_take(Path(take_dir))
    if take.capture.get("name") != name or take.dir.name != name:
        raise EncodeError("the recording's name %r is not the take's %r" % (name, take.capture.get("name")))
    pol = sendpolicy.Policy.from_contract(c)
    chk = check_take(take, c, pol)
    db = load_dbc(c)
    signals = tuple(c.SLOT_DBC_SIGNALS)
    values = iso_values(take.steps, chk.front_max_steer_deg)
    probs = range_problems([(s["i"], dict(zip(signals, v))) for s, v in zip(take.steps, values)], dbc_ranges(db, c))
    if probs:
        raise EncodeError("values outside slice.dbc's ranges: %s" % "; ".join(probs[:10]))
    frames, sched = encode_frames(take.steps, values, pol, db, signals)
    text = sigsim.candump_text(frames, CHANNEL)
    pend = pending_of(take)
    if pend:
        print("encode.py: PENDING-PROBE: this recording rests on provisional values that wait for WP0's probes: %s"
              % ", ".join(sorted(pend)), file=sys.stderr)
    seed = int(take.capture["seed"])
    trip = {"segments": segments_ms(take.steps), "messages": sendpolicy.counts(sched),
            "periods_ms": {pol.dyn_msg: pol.dyn_period_ms, pol.gear_msg: pol.gear_period_ms},
            "duration_ms": max(t for t, _m, _i in sched), "seed": seed, "params": params_of(c, seed), "profile_id": chk.profile_id,
            "wheelbase_mm": chk.l_mm, "gear_changes": gear_changes(take.steps), "rtf": chk.rtf, "gaps": [],
            "timestamps": TIMESTAMPS, "take": {"name": name, "take_sha256": take.take_sha256}, "encoder_sha256": encoder_sha256(),
            "conversion": {"front_max_steer_deg": chk.front_max_steer_deg}, "pending_probe": pend}
    out_dir.mkdir(parents=True, exist_ok=False)
    manifest = out_dir / MANIFEST_NAME
    try:
        log = out_dir / LOG_NAME
        _write_bytes(log, text.encode("ascii"))
        sha = _sha256(log.read_bytes())
        _write_bytes(out_dir / SHA_NAME, ("%s  %s\n" % (sha, LOG_NAME)).encode("ascii"))
        _write_bytes(out_dir / STEPS_NAME, take.steps_bytes)
        ver = verify(out_dir, c, front_max=chk.front_max_steer_deg)
        if ver["ok"]:
            result = {"name": name, "dir": str(out_dir), "recorded": True, "trip": trip, "verify": ver}
            _write_bytes(out_dir / SUMMARY_NAME, (json.dumps(result, sort_keys=True, indent=1) + "\n").encode("utf-8"))
            entry = manifest_line(name, manifest_path or str(log), sha, c, seed, chk.rtf, chk.profile_id, chk.l_mm)
            _write_bytes(manifest, (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
            return result
        final = sigsim._mark_failed(out_dir)
        result = {"name": name, "dir": str(final), "recorded": False, "trip": trip, "verify": ver}
        _write_bytes(final / SUMMARY_NAME, (json.dumps(result, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        return result
    except BaseException:
        if out_dir.is_dir():
            manifest.unlink(missing_ok=True)
            sigsim._mark_failed(out_dir)
        raise


def name_problem(name: str) -> Optional[str]:
    m = NAME_RE.fullmatch(name)
    if m is None or not sigsim.NAME_PATTERN.fullmatch(name) or not sigsim._real_date(m.group(1)):
        return "%r is not <yyyymmdd>-carla-<seed>[suffix] (a calendar date; the whole [a-z0-9][a-z0-9-]{0,47})" % name
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="write a recording directory from a take")
    r.add_argument("--take", type=Path, required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    v = sub.add_parser("verify", help="re-verify a recording directory against the current contract and DBC")
    v.add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "record":
            problem = name_problem(a.name)
            if problem:
                ap.error(problem)
            out = a.root.expanduser() / a.name
            if sigsim.inside_repo(out):
                ap.error("%s is inside the repository: a recording belongs outside it (only sdv-out/, which git ignores, is allowed)" % out)
            res = record(a.take.expanduser(), out, a.name, log_path_shown(out))
            ok = res["verify"]["ok"]
        else:
            res = verify(a.dir.expanduser())
            ok = res["ok"]
    except (EncodeError, FileExistsError, vf.ContractError) as e:      # an existing directory, no generation: refusals too
        print("encode.py: refused: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, sort_keys=True, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
