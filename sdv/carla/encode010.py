#!/usr/bin/env python3
"""encode010.py -- a CARLA 0.10.0 passive take as a carla-autoware recording directory (sdv/carla).

Phase 8 spec-2 2.9 and 10.1 item 2. Runs in WSL Ubuntu-24.04 with the sim venv's Python
(cantools and python-can, sdv/sim/requirements.lock), from the repo root. encode.py stays Phase 7's 0.9.16 encoder: this
module loads it by path under a name of its own and calls its functions read-only (the DBC check, the frame encoder, the
range check, the reader, the summary pieces), so none of its outputs changes; the conversion is carla010_iso.py's, never
carla_iso.py's.

    usage: encode010.py record --take DIR --name N [--root DIR]     # writes ROOT/<N>/ (ROOT default ~/sdv-recordings)
           encode010.py verify DIR                                  # re-verifies a recording against the current contract

THE RUN TYPE AND THE PROFILE: run type carla-autoware (the recording's source.generator, the stack's rule: a recording's
run type is its generator), judged under LIVE_DEFAULT_PROFILE["carla-autoware"] (profile 5, carla010-taxi), whose L is the
recording's wheelbase: 0.10.0 gives no wheel geometry to read (WP9a E1-E3), so a take carries none. Until WP3c's freeze
profile 5 is not compiled (its envelope holds stand-in rows): a recording made meanwhile is judged by profile 5's own row
(rules.Tables' extra_ids, as the rules module binds a profile before it is compiled), its trip says profile_compiled
false, stderr says PROFILE-NOT-COMPILED (a guest would answer 8 to every frame), and it is regenerated from its take after
the freeze; the take is the durable artefact, and regenerated_identical holds for each.

RECORD reads the take (follow010.py's output) and refuses, before anything is written: a take whose take.sha256 does not
hold for exactly its three files, whose script.jsonl is not empty (a passive take commands nothing), whose capture.json is
not a JSON object, or whose steps do not carry exactly follow010.STEP_KEYS; a name that is not the take's; a take that is
not format 1 and passive, that was refused, that did not complete, that recorded an error, or whose end is not one of
follow010.ENDS; versions, map, blueprint or role name other than 0.10.0, carla010's level, the taxi and ego_vehicle; a
world settings read, its settings or the physics read that is not a JSON object; world settings (every read) that
are not synchronous at the generated step, or none read, or reads that are not the follower's (at attach, after every
follow010.REREAD_FRAMES frames, after the frame it followed, and at the end, after the last frame); a steering curve
whose own points are not the flattening; listener reads that are not both empty (a take whose check did not run
included); a step that is not passive; steps that do not become current in strictly increasing order, a skipped frame,
a step whose simulation advance is not one step (sendpolicy.step_advance_ns, the step named), a gap, an RTF max above 1
or a min not above 0, each recomputed from steps.jsonl with sendpolicy.py, and a capture.json that disagrees with that
recomputation; a generation without the carla-autoware run type, or whose live default for it is not the 0.10.0 taxi's
profile; a step whose gear and reverse disagree or that the conversion cannot read; a value outside slice.dbc's range,
the step named, never clamped. main refuses a name that is not <yyyymmdd>-carla010-<n>[suffix], a root inside the
repository (sigsim's rule: only sdv-out/) and record an existing directory, which it leaves alone. Every refusal prints
"encode010.py: refused: ..." and exits 2 (1 is a recording that failed verify). Each step goes through carla010_iso.convert,
each frame through cantools (database strict), the log by sendpolicy's schedule (Phase 7's: encode.encode_frames). Then,
in this order: carla.log, carla.log.sha256, steps.jsonl (the take's, byte for byte), verify, summary.json, and
manifest-line.json, written last and only when verify passed. A recording that fails verify, or stops for any other
reason once its directory exists, is renamed <name>.failed and has no manifest line (sigsim's rule).

VERIFY passes only when every term of OK_TERMS holds -- Phase 7's nine without segments_complete and
app_switches_as_designed, which assume its scripted drive (a drive Autoware makes has no scripted segment and no hard
brake): all_frames_accepted (every dynamics frame of the decoded log, packed as a replay-mode bridge packs it, judged
ACCEPT by sdv/frame/rules.py under profile 5), message_counts and no_period_errors (against the schedule),
within_half_lsb (cantools' decode of every frame against carla010_iso's values of its step, the gear exactly),
regenerated_identical (the log made again from steps.jsonl equal byte for byte), python_can_reader, gear_agrees
(reverse set exactly in gear -1 on every step). ok also wants carla.log.sha256 to hold for carla.log.

THE MANIFEST LINE: generator carla-autoware, profile 5, the taxi as the declared vehicle with profile 5's L, the RTF, and
five params: catalog_digest and dbc_sha256 (the injector and the bundle read both), version, map, and steer_law, which
names C and the flat curve (the injector adds three params to the scenario entry's eight, each a short string).

DOES NOT DEMONSTRATE: vehicle dynamics, CAN timing (the timestamps are a send schedule, and vcan has no arbitration, error
frames or bus timing), or any timing. That every frame passes the reference rules shows the take agrees with the rules'
own kinematic model through the steering law, not that the rules or the law are right.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _d in (str(HERE), str(REPO / "sdv" / "sim"), str(REPO / "sdv" / "frame"), str(REPO / "sdv" / "stack")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla010_iso as iso  # noqa: E402
import follow010  # noqa: E402
import rules  # noqa: E402
import sendpolicy  # noqa: E402
import sigsim  # noqa: E402
import vssframe as vf  # noqa: E402


def _load(name: str, path: Path) -> Any:
    """A command-line module of sdv/carla by path, under a name of its own (its generic name may be another tree's)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                    # dataclasses with postponed annotations look their module up there
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    return mod


encode = _load("sdv_carla010_encode", HERE / "encode.py")

RUN_TYPE = "carla-autoware"
GENERATOR = RUN_TYPE
SOURCE_VEHICLE = "carla010-taxi"       # profile 5's source_vehicle (spec-2 2.4): the 0.10.0 taxi's profile
VERSION = follow010.VERSION
MAP = follow010.MAP
BLUEPRINT = follow010.BLUEPRINT
ROLE_NAME = follow010.ROLE_NAME
CHANNEL = "vcan0"
LOG_NAME = encode.LOG_NAME
SHA_NAME = LOG_NAME + ".sha256"
STEPS_NAME = "steps.jsonl"
SUMMARY_NAME = "summary.json"
MANIFEST_NAME = "manifest-line.json"
TAKE_FILES = ("steps.jsonl", "script.jsonl", "capture.json")
STEP_KEYS = ("i", "frame", "elapsed_s", "t_vals_ns", "t_cur_ns", "seg", "gear", "v", "a", "fwd", "w", "steer", "throttle",
             "brake", "reverse")
DEFAULT_ROOT = encode.DEFAULT_ROOT
TIMESTAMPS = "feeder send schedule from zero"
ENCODER_MODULES = ("sdv/carla/encode010.py", "sdv/carla/encode.py", "sdv/carla/follow010.py", "sdv/carla/sendpolicy.py",
                   "sdv/carla/worldtie.py", "sdv/sim/carla010_iso.py")
OK_TERMS = ("all_frames_accepted", "message_counts", "no_period_errors", "within_half_lsb", "regenerated_identical",
            "python_can_reader", "gear_agrees")
TRIP_KEYS = ("segments", "messages", "periods_ms", "duration_ms", "params", "profile_id", "profile_compiled", "wheelbase_mm",
             "gear_changes", "rtf", "gaps", "timestamps", "take", "encoder_sha256", "conversion")
NAME_RE = follow010.NAME_RE
LAW = "delta = -C x s x |s|"
EncodeError = encode.EncodeError


def steer_law() -> str:
    """The manifest line's steer_law param: the law with C and the flat curve, from carla010_iso's constants."""
    return "-%g*s*|s| deg on the curve %s" % (iso.C, ",".join("(%g,%g)" % p for p in iso.FLAT_CURVE))


def load_contract() -> Any:
    return vf.load_contract()


def load_dbc(contract: Any, path: Optional[Path] = None) -> Any:
    """slice.dbc through cantools (strict), checked against the generated contract: encode.load_dbc."""
    return encode.load_dbc(contract, path)


def read_log(path: Path) -> List[Tuple[float, int, bytes, Any]]:
    """The log through python-can's reader: encode.read_log."""
    return encode.read_log(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    """Every file of a recording is written through here (the tests read the order)."""
    path.write_bytes(data)


def log_path_shown(out_dir: Path) -> Optional[str]:
    """The manifest line's path for a recording under DEFAULT_ROOT, in its ~ spelling; None elsewhere (encode.py's)."""
    return encode.log_path_shown(out_dir)


def name_problem(name: str) -> Optional[str]:
    return follow010.name_problem(name)


# --- the take ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Checked:
    profile_id: int
    l_mm: int
    compiled: bool
    rtf: Dict[str, float]


def read_take(take_dir: Path) -> Any:
    """The take (an encode.Take), after its take.sha256 holds for exactly its three files and every step carries exactly
    STEP_KEYS."""
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
    if raw["script.jsonl"] != b"":
        raise EncodeError("the take's script.jsonl is not empty: a passive take commands nothing")
    try:
        cap = json.loads(raw["capture.json"].decode("utf-8"))
        steps = [json.loads(x) for x in raw["steps.jsonl"].decode("ascii").splitlines()]
    except ValueError as e:
        raise EncodeError("the take's files are not the follower's JSON: %s" % e) from e
    if not isinstance(cap, dict):
        raise EncodeError("the take's capture.json is not an object")
    for s in steps:
        if not isinstance(s, dict) or tuple(s) != STEP_KEYS:
            raise EncodeError("a step of steps.jsonl does not have exactly the keys %s" % ", ".join(STEP_KEYS))
    return encode.Take(d, cap, steps, raw["steps.jsonl"], _sha256(sums))


def profile_of(contract: Any) -> Tuple[int, Dict[str, Any], bool]:
    """(profile id, its row, whether the generation compiles it) of the carla-autoware run type's live default, refused
    unless the generation has that run type and its profile is the 0.10.0 taxi's."""
    live = dict(contract.LIVE_DEFAULT_PROFILE)
    if RUN_TYPE not in live:
        raise EncodeError("this generation has no %s run type (LIVE_DEFAULT_PROFILE %r): WP3b's generation is needed" % (RUN_TYPE, live))
    pid = int(live[RUN_TYPE])
    row = {int(r["id"]): r for r in contract.PROFILES}.get(pid)
    if row is None or row.get("source_vehicle") != SOURCE_VEHICLE:
        raise EncodeError("profile %d (the %s live default) is not the %s's profile" % (pid, RUN_TYPE, SOURCE_VEHICLE))
    return pid, row, pid in tuple(contract.COMPILED_PROFILE_IDS)


def tables_of(contract: Any) -> Tuple[Any, int]:
    """The reference rules' tables with the live default bound: the compiled ones, plus profile 5's own row while it is
    not compiled (rules.Tables.from_contract's extra_ids)."""
    pid, _row, compiled = profile_of(contract)
    return rules.Tables.from_contract(contract, extra_ids=() if compiled else (pid,)), pid


def check_take(t: Any, contract: Any, pol: Any) -> Checked:
    """Every refusal of a take before anything is written (the module docstring's RECORD)."""
    cap, steps = t.capture, t.steps
    if cap.get("format") != 1:
        raise EncodeError("capture.json's format is %r, not 1" % (cap.get("format"),))
    if cap.get("mode") != follow010.MODE:
        raise EncodeError("the take's mode is %r: not a passive 0.10.0 take" % (cap.get("mode"),))
    if cap.get("refused"):
        raise EncodeError("the take was refused: %s" % cap.get("refused"))
    if cap.get("completed") is not True or cap.get("errors"):
        raise EncodeError("the take did not complete: %r" % (cap.get("errors"),))
    end = cap.get("end")
    if end not in follow010.ENDS:
        raise EncodeError("the take's end %r is not one of %s" % (end, ", ".join(follow010.ENDS)))
    if cap.get("client_version") != VERSION or cap.get("server_version") != VERSION:
        raise EncodeError("the take's client %r and server %r are not both %s" % (cap.get("client_version"), cap.get("server_version"), VERSION))
    for key, want in (("map", MAP), ("blueprint", BLUEPRINT), ("role_name", ROLE_NAME)):
        if cap.get(key) != want:
            raise EncodeError("the take's %s %r is not %s" % (key, cap.get(key), want))
    reads = cap.get("world_settings")
    if isinstance(reads, list):
        shapeless = [k for k, r in enumerate(reads) if not isinstance(r, dict) or not isinstance(r.get("settings"), dict)]
        if shapeless:
            raise EncodeError("the take's world settings reads %s are not objects, each with a settings object" % shapeless[:20])
    if not isinstance(reads, list) or not reads or reads[0].get("at") != "attach":
        raise EncodeError("the take holds no world settings read at attach")
    for r in reads:
        problems = follow010.world_problems(r.get("settings") or {}, pol.step_s)
        if problems:
            raise EncodeError("the take's world settings read %s: %s" % (r.get("at"), "; ".join(problems)))
    physics = cap.get("physics_read")
    if not isinstance(physics, dict):
        raise EncodeError("the take's physics_read is a %s, not an object" % type(physics).__name__)
    curve = physics.get("steering_curve")
    problems, _own = follow010.curve_problems(curve if isinstance(curve, list) else [])
    if problems:
        raise EncodeError("the take's steering curve: %s" % "; ".join(problems))
    if cap.get("listeners") != {"start": [], "end": []}:
        raise EncodeError("the take's client listened, or its listening sockets were not read: %r" % (cap.get("listeners"),))
    if len(steps) < 2 or [s["i"] for s in steps] != list(range(len(steps))) or steps[0]["t_cur_ns"] != 0:
        raise EncodeError("steps.jsonl is not a sequence of steps from 0 with step 0 current at 0")
    if any(s["seg"] != follow010.SEG for s in steps):
        raise EncodeError("a step is not passive (seg %r)" % next(s["seg"] for s in steps if s["seg"] != follow010.SEG))
    frames = [s["frame"] for s in steps]
    elapsed = [s["elapsed_s"] for s in steps]
    t_cur = [s["t_cur_ns"] for s in steps]
    behind = [k for k in range(1, len(t_cur)) if t_cur[k] <= t_cur[k - 1]]
    if behind:
        raise EncodeError("steps must become current in increasing order: not at steps %s" % behind[:20])
    skipped = sendpolicy.skipped_frames(frames)
    if skipped:
        raise EncodeError("a skipped frame at steps %s" % skipped[:20])
    off = [k for k in range(1, len(steps)) if sendpolicy.step_advance_ns(elapsed[k - 1], elapsed[k], pol.step_ns) != pol.step_ns]
    if off:
        raise EncodeError("step %d advances the simulation by %d ns, not one step (%d ns); such steps: %s"
                          % (off[0], sendpolicy.sim_advance_ns(elapsed[off[0] - 1], elapsed[off[0]]), pol.step_ns, off[:20]))
    every = follow010.REREAD_FRAMES
    rereads = (len(steps) - (1 if end == "max-frames" else 0)) // every
    reads_want: List[List[Any]] = ([["attach", None]] + [["reread", frames[j * every - 1]] for j in range(1, rereads + 1)]
                                   + [["end", frames[-1]]])
    reads_got = [[r.get("at"), r.get("after_frame")] for r in reads]
    if reads_got != reads_want:
        raise EncodeError("the take's world settings reads %s are not the follower's %s (at attach, after every %d frames and at "
                          "the end)" % (reads_got[:6], reads_want[:6], every))
    gaps = sendpolicy.gaps(frames, t_cur, pol.cap_ns)
    if gaps:
        raise EncodeError("a gap at steps %s" % gaps[:20])
    rtf = sendpolicy.rtf_summary(elapsed, t_cur, pol.step_ns)
    if rtf["max"] > 1:
        raise EncodeError("the take's RTF max %r is above 1" % rtf["max"])
    if not rtf["min"] > 0:
        raise EncodeError("the take's RTF min %r is not above 0" % rtf["min"])
    recomputed: Dict[str, Any] = {"steps": len(steps), "rtf": rtf, "gaps": gaps, "skipped_frames": skipped}
    for key, value in recomputed.items():
        if cap.get(key) != value:
            raise EncodeError("capture.json's %s %r disagrees with its steps (%r)" % (key, cap.get(key), value))
    pid, row, compiled = profile_of(contract)
    return Checked(pid, int(row["l_mm"]), compiled, rtf)


def iso_values(steps: Sequence[Dict[str, Any]]) -> List[Tuple[float, float, float, float, int]]:
    """Every step through carla010_iso.convert, a refusal naming the step."""
    out = []
    for s in steps:
        try:
            out.append(iso.convert(s))
        except (iso.ConversionError, ValueError, TypeError, KeyError, IndexError) as e:
            raise EncodeError("step %d: %s" % (s["i"], e)) from e
    return out


def verify_terms(*, stats: Any, regenerated_identical: bool, per_message: Dict[str, int], expected: Dict[str, int],
                 period_errors: int, within_half_lsb: bool, python_can_ok: bool, gear_ok: bool) -> Dict[str, bool]:
    """The terms of verify's ok, in OK_TERMS order."""
    return {
        "all_frames_accepted": stats.frames > 0 and stats.accepted == stats.frames,
        "message_counts": per_message == expected,
        "no_period_errors": period_errors == 0,
        "within_half_lsb": within_half_lsb,
        "regenerated_identical": regenerated_identical,
        "python_can_reader": python_can_ok,
        "gear_agrees": gear_ok,
    }


def verify(rec_dir: Path, contract: Any = None) -> Dict[str, Any]:
    """Re-verify a recording directory (the module docstring's VERIFY)."""
    c = contract if contract is not None else load_contract()
    d = Path(rec_dir)
    pol = sendpolicy.Policy.from_contract(c)
    tables, pid = tables_of(c)
    _pid, row, compiled = profile_of(c)
    db = load_dbc(c)
    signals = tuple(c.SLOT_DBC_SIGNALS)
    log = d / LOG_NAME
    raw = log.read_bytes()
    sha = _sha256(raw)
    sha_file = (d / SHA_NAME).read_text(encoding="ascii") if (d / SHA_NAME).is_file() else ""
    steps = [json.loads(x) for x in (d / STEPS_NAME).read_text(encoding="ascii").splitlines()]
    problems: List[str] = []
    gear_ok = encode.gear_term(steps)
    values: Optional[List[Tuple[float, float, float, float, int]]] = None
    try:
        values = iso_values(steps)
    except EncodeError as e:
        problems.append(str(e))
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    expected = sendpolicy.counts(sched)
    regenerated = False
    if values is not None:
        frames, _s = encode.encode_frames(steps, values, pol, db, signals)
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
    stats = sigsim.judge_stream(stream, encode._setup(c, pid, row, pol), tables, pid)
    terms = verify_terms(stats=stats, regenerated_identical=regenerated, per_message=per_message, expected=expected,
                         period_errors=period_errors, within_half_lsb=within, python_can_ok=python_can_ok, gear_ok=gear_ok)
    sha_holds = sha_file == "%s  %s\n" % (sha, LOG_NAME)
    return {
        "log": str(log), "log_sha256": sha, "log_bytes": len(raw), "log_sha256_file_holds": sha_holds,
        "regenerated_identical": regenerated, "profile_id": pid, "profile_compiled": compiled,
        "python_can_reader": {"frames": len(msgs), "lines": len(lines), "channels": channels, "per_message": per_message,
                              "expected_per_message": expected, "period_errors": period_errors, "error": reader_error},
        "cantools_decode": {"max_abs_error": worst, "half_lsb": {s: lsb[s] / 2 for s in worst}, "within_half_lsb": within,
                            "gear_mismatches": gear_mismatches},
        "judge": stats.as_dict(), "problems": problems, "ok_terms": terms, "ok": all(terms.values()) and sha_holds,
    }


# --- the recording -------------------------------------------------------------------------------------------------

def params_of(contract: Any) -> Dict[str, Any]:
    """The manifest line's five source.params (the injector adds three; the scenario entry's cap is eight)."""
    return {"catalog_digest": "0x%08X" % contract.CATALOG_DIGEST, "dbc_sha256": _sha256(encode.DBC_PATH.read_bytes()),
            "version": VERSION, "map": MAP, "steer_law": steer_law()}


def manifest_line(name: str, path: str, sha: str, contract: Any, rtf: Dict[str, float], pid: int, l_mm: int) -> Dict[str, Any]:
    """The recording's scenario entry (Phase 7 spec 2.3's shape, run type carla-autoware)."""
    return {"name": name, "profile_id": pid,
            "recording": {"format": "candump-log", "path": path, "sha256": sha},
            "source": {"generator": GENERATOR, "params": params_of(contract),
                       "rtf": {"max": rtf["max"], "mean": rtf["mean"], "min": rtf["min"]},
                       "vehicle": {"name": BLUEPRINT, "wheelbase_mm": l_mm}}}


def encoder_sha256() -> Dict[str, str]:
    return {rel: _sha256((REPO / rel).read_bytes()) for rel in ENCODER_MODULES}


def record(take_dir: Path, out_dir: Path, name: str, manifest_path: Optional[str] = None, contract: Any = None) -> Dict[str, Any]:
    """Write a recording directory from a passive take (the module docstring's RECORD). Everything is computed and
    checked in memory first; the directory's creation is outside the rename (an existing one is somebody's)."""
    c = contract if contract is not None else load_contract()
    take = read_take(Path(take_dir))
    if take.capture.get("name") != name or take.dir.name != name:
        raise EncodeError("the recording's name %r is not the take's %r" % (name, take.capture.get("name")))
    pol = sendpolicy.Policy.from_contract(c)
    chk = check_take(take, c, pol)
    db = load_dbc(c)
    signals = tuple(c.SLOT_DBC_SIGNALS)
    values = iso_values(take.steps)
    probs = encode.range_problems([(s["i"], dict(zip(signals, v))) for s, v in zip(take.steps, values)], encode.dbc_ranges(db, c))
    if probs:
        raise EncodeError("values outside slice.dbc's ranges: %s" % "; ".join(probs[:10]))
    frames, sched = encode.encode_frames(take.steps, values, pol, db, signals)
    text = sigsim.candump_text(frames, CHANNEL)
    trip = {"segments": encode.segments_ms(take.steps), "messages": sendpolicy.counts(sched),
            "periods_ms": {pol.dyn_msg: pol.dyn_period_ms, pol.gear_msg: pol.gear_period_ms},
            "duration_ms": max(t for t, _m, _i in sched), "params": params_of(c), "profile_id": chk.profile_id,
            "profile_compiled": chk.compiled, "wheelbase_mm": chk.l_mm, "gear_changes": encode.gear_changes(take.steps),
            "rtf": chk.rtf, "gaps": [], "timestamps": TIMESTAMPS, "take": {"name": name, "take_sha256": take.take_sha256},
            "encoder_sha256": encoder_sha256(), "conversion": {"law": LAW, "C": iso.C, "curve": [list(p) for p in iso.FLAT_CURVE]}}
    out_dir.mkdir(parents=True, exist_ok=False)
    if not chk.compiled:                       # after the mkdir: an existing directory is refused before anything is said
        print("encode010.py: PROFILE-NOT-COMPILED: profile %d (the %s live default) is not compiled in this generation (its "
              "envelope holds stand-in rows until WP3c's freeze): a guest would answer 8 to every frame; this recording is "
              "judged by the profile's own row and is made again from its take after the freeze" % (chk.profile_id, RUN_TYPE),
              file=sys.stderr)
    manifest = out_dir / MANIFEST_NAME
    try:
        log = out_dir / LOG_NAME
        _write_bytes(log, text.encode("ascii"))
        sha = _sha256(log.read_bytes())
        _write_bytes(out_dir / SHA_NAME, ("%s  %s\n" % (sha, LOG_NAME)).encode("ascii"))
        _write_bytes(out_dir / STEPS_NAME, take.steps_bytes)
        ver = verify(out_dir, c)
        if ver["ok"]:
            result = {"name": name, "dir": str(out_dir), "recorded": True, "trip": trip, "verify": ver}
            _write_bytes(out_dir / SUMMARY_NAME, (json.dumps(result, sort_keys=True, indent=1) + "\n").encode("utf-8"))
            entry = manifest_line(name, manifest_path or str(log), sha, c, chk.rtf, chk.profile_id, chk.l_mm)
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="write a carla-autoware recording directory from a passive take")
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
        print("encode010.py: refused: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, sort_keys=True, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
