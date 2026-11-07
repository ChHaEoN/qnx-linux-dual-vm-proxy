"""replaycheck.py -- what a replay of a recording is checked against (sdv/stack).

The pure functions use the standard library only; decode_recording
needs cantools and python-can (the sim venv, sdv/sim/requirements.lock) and imports them lazily.

  expected_windows   the windows the hazard lights must switch in, derived from the trip the
                     recording was made from (the recording directory's summary.json, trip.segments)
                     and the decoded recording -- never from a run, never from re-running sigsim.
  predict            the app's own decision function (hazard.py) applied to the decoded recording,
                     one evaluation per input value in the provider's write order: the samples at
                     which the app should switch.
  read_recorder_csv  the VSS-layer recorder's CSV (kuksa-csv-provider's recorder.py: columns field,
                     signal, value, delay), with each row's time since the recorder started.
  compare_values     the values the provider wrote (the recorder's current rows, per path, in order)
                     against the decoded recording, count for count, within half an LSB of the DBC
                     signal (scaled through the path's transform), and how many are the decoded value
                     rounded to float32 exactly.
  read_witness,      the buffered kuksa.val.v2 witness's log (sdv/stack/witness.py) and its exact
  compare_exact,     comparison: every value of every CAN-fed path, count for count, equal to the
  load_witness,      decoded value rounded to float32 (how the databroker stores a float); the
  witness_verdict    reading of the log without aborting the replay's record; and the judgement of
                     a replay's witness, each gate (values, log read, no initial value, no stream
                     error, stop record equal to the log, no databroker lag) on its own.
  app_events         the app's JSON-lines log reduced to its decisions, actuations and heartbeats,
                     mapped onto recording time.
  mock_gate,         the hazard light as a replay's verdict reads it: the mock provider's own log (the
  mock_log_clean,    gate: exactly three 'Feeding' lines in their windows and no line of the log above
  behaviour_key,     INFO -- the mock logs each write just before making it, so a failed write leaves
  recorder_light_view  its line and then an error; mock_log_offending lists the lines that are not INFO),
                     the key replays are compared by (the app's decisions and actuations, the mock's
                     writes, the app's state sequence), and the recorder's own hazard rows, kept as the
                     databroker's lossy kuksa.val.v1 view and checked for consistency with the other
                     two. The gate and the key read lossless sources only; the view is reported.

Mapping onto recording time: t_rec = t - t_anchor + t_rec_anchor, where the anchor is the first
value of the signed velocity that is not zero -- in the recording (the launch's first sample) and in
the observer's own record of the replay. The first non-zero value, not the first value, so the
provider's start-up does not enter the mapping. The mapping carries one dynamics period (20 ms, the
recording's resolution) of allowance at the windows' lower edges. No timing claim rests on it.
"""
from __future__ import annotations

import csv
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"

V_PATH = "Vehicle.DualVm.Motion.LongitudinalVelocity"
A_PATH = "Vehicle.Acceleration.Longitudinal"
HAZARD = "Vehicle.Body.Lights.Hazard.IsSignaling"
HARD_BRAKE_LABEL = "hard brake"     # sigsim.script's segment name for the braking_max stop


def hazard_module() -> Any:
    """The app's pure core (sdv/apps/hard-brake-hazard/hazard.py), imported without bytecode."""
    if "hazard" in sys.modules:
        return sys.modules["hazard"]
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(APP_DIR))
    try:
        import hazard  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(APP_DIR))
        sys.dont_write_bytecode = saved
    return hazard


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


# --- the recording ------------------------------------------------------------------------------

def decode_recording(log_path: Path, dbc_path: Path, mapping: Dict[str, Dict[str, Any]],
                     transforms: Dict[str, Callable[[float], float]]) -> Dict[str, Any]:
    """Decode a candump log with cantools through slice.dbc: per VSS path of the mapping, the values
    in log order after its transform; the half LSB of each path; and the dynamics frames as
    (t_ms, {signal: value})."""
    import can  # type: ignore[import-not-found]
    import cantools  # type: ignore[import-not-found]

    db = cantools.database.load_file(str(dbc_path), strict=True)
    by_signal: Dict[str, List[str]] = {}
    for path, block in mapping.items():
        by_signal.setdefault(block["signal"], []).append(path)
    values: Dict[str, List[Any]] = {p: [] for p in mapping}
    frames: List[Tuple[int, str, Dict[str, Any]]] = []
    t0: Optional[float] = None
    for msg in can.LogReader(str(log_path)):
        m = db.get_message_by_frame_id(msg.arbitration_id)
        dec = m.decode(bytes(msg.data), decode_choices=False, scaling=True)
        t0 = msg.timestamp if t0 is None else t0
        frames.append((int(round((msg.timestamp - t0) * 1000.0)), m.name, dict(dec)))
        for sig in m.signal_tree:
            for path in by_signal.get(sig, ()):
                values[path].append(transforms[path](dec[sig]))
    scales = {sg.name: float(sg.scale) for m in db.messages for sg in m.signals}
    half: Dict[str, float] = {}
    for path, block in mapping.items():
        h = scales[block["signal"]] / 2.0
        tf = transforms[path]
        half[path] = abs(tf(h) - tf(0.0))      # half an LSB through the path's transform (linear or abs-linear)
    return {"values": values, "half_lsb": half, "frames": frames}


def hard_brake_segment(trip: Dict[str, Any]) -> Tuple[int, int]:
    """The one HARD_BRAKE_LABEL segment of a trip summary (sigsim's summary(), as the recording
    directory's summary.json keeps it under `trip`): (start_ms, end_ms)."""
    segs = [s for s in trip["segments"] if s[0] == HARD_BRAKE_LABEL]
    if len(segs) != 1:
        raise ValueError("the trip has %d %r segments, expected one" % (len(segs), HARD_BRAKE_LABEL))
    return int(segs[0][1]), int(segs[0][2])


def expected_windows(trip: Dict[str, Any], frames: Sequence[Tuple[int, str, Dict[str, Any]]], v_signal: str,
                     dyn_period_ms: int) -> Dict[str, Any]:
    """The windows the lights must switch in, from the trip the recording was made from (its
    summary.json's `trip`) and the decoded recording: on during the hard brake, off from its end
    until the vehicle next moves."""
    start, end = hard_brake_segment(trip)
    moving_after = [t for t, name, dec in frames if v_signal in dec and t > end and dec[v_signal] != 0.0]
    if not moving_after:
        raise ValueError("the vehicle never moves again after the hard brake")
    first_motion = [t for t, name, dec in frames if v_signal in dec and dec[v_signal] != 0.0]
    return {
        "source": "the recording's summary.json (trip.segments %r) and the decoded recording" % HARD_BRAKE_LABEL,
        "hard_brake_ms": [start, end],
        "on_window_ms": [start - dyn_period_ms, end],
        "off_window_ms": [end - dyn_period_ms, moving_after[0]],
        "anchor": {"what": "first non-zero %s" % v_signal, "t_rec_ms": first_motion[0]},
        "mapping_allowance_ms": dyn_period_ms,
    }


def predict(frames: Sequence[Tuple[int, str, Dict[str, Any]]], v_signal: str, a_signal: str, hz: Any) -> List[Dict[str, Any]]:
    """The app's decisions on the decoded recording: the velocity then the acceleration of each
    dynamics frame, one evaluation each, as the provider writes them (slice.dbc signal order)."""
    v: Optional[float] = None
    a: Optional[float] = None
    on = False
    out = []
    for t, _name, dec in frames:
        for sig in (v_signal, a_signal):
            if sig not in dec:
                continue
            if sig == v_signal:
                v = float(dec[sig])
            else:
                a = float(dec[sig])
            if v is None or a is None:
                continue
            new = hz.decide(on, hz.deceleration(f32(v), f32(a)))
            if new != on:
                on = new
                out.append({"t_rec_ms": t, "hazard": new, "trigger": sig, "v": f32(v), "a": f32(a)})
    return out


# --- the recorder's CSV -------------------------------------------------------------------------

def parse_value(text: str) -> Any:
    if text in ("True", "False"):
        return text == "True"
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            pass
    return text


def read_recorder_csv(path: Path) -> List[Dict[str, Any]]:
    """Rows with a `t` column: seconds since the recorder started (its `delay` accumulated; the
    recorder gives its first row 0 and does not restart its clock there, so the sum is exact)."""
    rows = []
    t = 0.0
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t += float(r["delay"])
            rows.append({"field": r["field"], "signal": r["signal"], "value": parse_value(r["value"]), "t": t})
    return rows


def series(rows: Sequence[Dict[str, Any]], path: str, field: str = "current") -> List[Tuple[float, Any]]:
    return [(r["t"], r["value"]) for r in rows if r["signal"] == path and r["field"] == field]


MAX_GAP = 3   # consecutive unrecorded values an alignment may skip: a slow v1 subscriber loses single updates


def align(expected: Sequence[Any], recorded: Sequence[Any], tol: float, max_gap: int = MAX_GAP) -> Dict[str, Any]:
    """Match every recorded value, in order, to the decoded value at its position, allowing the
    recorder to have missed values (a v1 subscriber of databroker 0.7.1 has a buffer of one and
    drops on lag, which the databroker logs). Returns the skipped (unrecorded) indices, the matched
    pairs' largest error and float32-exact count, and the first recorded value that matches no
    decoded value within max_gap skips (None when all match)."""
    i = 0
    skipped: List[int] = []
    errs: List[float] = []
    exact = 0
    for j, got in enumerate(recorded):
        g = float(got)
        k = i
        while k < len(expected) and k - i <= max_gap and abs(g - float(expected[k])) > tol:
            k += 1
        if k >= len(expected) or k - i > max_gap:
            return {"ok": False, "first_unmatched": {"recorded_index": j, "recorded": got, "expected_from": i,
                                                     "expected": list(expected[i:i + max_gap + 1])},
                    "skipped": skipped, "max_abs_error": max(errs) if errs else None, "float32_exact": exact}
        skipped.extend(range(i, k))
        errs.append(abs(g - float(expected[k])))
        exact += g == f32(float(expected[k]))
        i = k + 1
    skipped.extend(range(i, len(expected)))
    return {"ok": True, "first_unmatched": None, "skipped": skipped, "max_abs_error": max(errs) if errs else None,
            "float32_exact": exact}


def compare_values(expected: Dict[str, List[Any]], half_lsb: Dict[str, float], got: Dict[str, List[Any]],
                   allowed_misses: Optional[int] = None) -> Dict[str, Any]:
    """Recorded against decoded, per path. Exact: equal counts and every value within half an LSB at
    its index. Otherwise the recorded values must still align with the decoded ones in order (every
    recorded value within half an LSB of its decoded value, at most MAX_GAP consecutive values
    unrecorded), and the unrecorded values in all must not exceed allowed_misses (the updates the
    databroker says its slow subscribers missed)."""
    out: Dict[str, Any] = {}
    exact_all, aligned_all, missed = True, True, 0
    for path in sorted(expected):
        exp, have = expected[path], got.get(path, [])
        a = align(exp, have, half_lsb[path])
        res: Dict[str, Any] = {"expected": len(exp), "recorded": len(have), "half_lsb": half_lsb[path],
                               "unrecorded": len(a["skipped"]), "unrecorded_indices": a["skipped"][:20],
                               "max_abs_error": a["max_abs_error"], "float32_exact": a["float32_exact"],
                               "first_unmatched": a["first_unmatched"]}
        res["exact"] = len(exp) == len(have) and all(abs(float(h) - float(e)) <= half_lsb[path] for h, e in zip(have, exp))
        res["aligned"] = a["ok"]
        exact_all = exact_all and res["exact"]
        aligned_all = aligned_all and a["ok"]
        missed += len(a["skipped"])
        out[path] = res
    within = allowed_misses is not None and missed <= allowed_misses
    return {"ok": exact_all or (aligned_all and within), "exact": exact_all, "aligned": aligned_all,
            "unrecorded_total": missed, "broker_reported_misses": allowed_misses, "paths": out}


_LAGGED = re.compile(r"(?:capacity (\d+) )?lagged, missed (\d+) signal updates")


def broker_misses(log_text: str, capacity: Optional[int] = None) -> int:
    """Updates the databroker says its slow subscribers missed ('Slow subscriber with capacity C
    lagged, missed N signal updates'), all of them or only those of subscribers of capacity C.
    Databroker 0.7.1 gives a subscription capacity buffer_size + 1, or 1 without a buffer: every
    kuksa.val.v1 subscriber (the recorder, the mock provider) has 1, the app's v2 subscription 101,
    the witness 1001. A line names no path, so a count of capacity 1 is shared by the v1
    subscribers and cannot say whose update was missed."""
    total = 0
    for cap, n in _LAGGED.findall(log_text):
        if capacity is None or (cap and int(cap) == capacity):
            total += int(n)
    return total


def broker_lags(log_text: str) -> Dict[str, int]:
    """Missed updates per subscriber capacity, as the databroker logged them ('?' when no capacity)."""
    out: Dict[str, int] = {}
    for cap, n in _LAGGED.findall(log_text):
        out[cap or "?"] = out.get(cap or "?", 0) + int(n)
    return out


# --- the v2 witness -----------------------------------------------------------------------------

def read_witness(path: Path, strict: bool = True) -> Dict[str, Any]:
    """The witness's JSON-lines log (sdv/stack/witness.py): per path the values of its `value`
    records in arrival order, how many of them came in the databroker's initial notification, and
    every other record. strict=False stops at a line being written instead of raising."""
    values: Dict[str, List[Any]] = {}
    initial = 0
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                if strict:
                    raise
                break
            if r.get("event") == "value":
                values.setdefault(r["path"], []).append(r["value"])
                initial += bool(r.get("initial"))
            else:
                records.append(r)
    return {"values": values, "initial_values": initial, "records": records}


def compare_exact(expected: Dict[str, List[Any]], got: Dict[str, List[Any]],
                  half_lsb: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Witnessed against decoded, per path, with no allowance: equal counts, and every value, at its
    index, equal to the decoded value rounded to float32 (the databroker stores a float as float32;
    an integer signal compares equal as it is). A path witnessed but not expected fails too, and so
    does a comparison in which nothing was compared (no expected path, or no expected value at all):
    agreement about nothing is not agreement. `compared_total` is the number of expected values. With
    half_lsb, each path also reports its largest error and whether every value was within half an
    LSB, to tell a representation difference from a missing or extra value; neither relaxes `ok`."""
    out: Dict[str, Any] = {}
    ok_all = True
    compared_total = sum(len(v) for v in expected.values())
    for path in sorted(expected):
        exp, have = expected[path], got.get(path, [])
        first = None
        errs: List[float] = []
        for i, (h, e) in enumerate(zip(have, exp)):
            errs.append(abs(float(h) - float(e)))
            if first is None and float(h) != f32(float(e)):
                first = {"index": i, "witnessed": h, "decoded": e, "decoded_float32": f32(float(e))}
        res: Dict[str, Any] = {"expected": len(exp), "witnessed": len(have), "first_mismatch": first,
                               "max_abs_error": max(errs) if errs else None}
        if half_lsb is not None:
            res["within_half_lsb"] = all(x <= half_lsb[path] for x in errs)
        res["ok"] = len(exp) == len(have) and first is None
        ok_all = ok_all and res["ok"]
        out[path] = res
    extra = sorted(set(got) - set(expected))
    return {"ok": ok_all and not extra and compared_total > 0, "compared_total": compared_total, "paths": out,
            "unexpected_paths": extra}


WITNESS_CAPACITY = 1001      # witness.py's BUFFER_SIZE + 1: how the databroker names the witness's lags ('capacity 1001')


def load_witness(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """The witness's log and the reason it could not be read: (read_witness's result, None), or, for
    no log or a torn line, (an empty result, 'ErrorName: message'). A replay with an unreadable
    witness log is judged as one whose witness failed, never aborted: its other records are kept."""
    try:
        return read_witness(path), None
    except (OSError, ValueError) as exc:
        return {"values": {}, "initial_values": 0, "records": []}, "%s: %s" % (type(exc).__name__, exc)


def witness_verdict(expected: Dict[str, List[Any]], half_lsb: Dict[str, float], wit: Dict[str, Any],
                    read_error: Optional[str], broker_log: str, capacity: int = WITNESS_CAPACITY) -> Dict[str, Any]:
    """The judgement of one replay's witness (`wit` and `read_error` as load_witness gives them,
    `broker_log` the databroker's log), as the exact comparison plus each gate on its own, so that a
    replay that fails one says which. Every gate is required:

      values_exact           compare_exact: every value of every expected path, count for count
      log_read               the witness's log was read whole (no error, no torn line)
      no_initial_values      nothing arrived in the databroker's initial notification: the values are
                             the replay's alone
      no_stream_errors       no subscription-error and no stream-ended record: a stream that ended
                             or failed leaves a gap no count could show
      stop_counts_equal_log  the witness's own stop record counts what its log holds, path by path:
                             the log is whole, and the witness stopped cleanly
      no_broker_lag          the databroker logged no lag for a subscriber of the witness's capacity
                             (lines of other capacities are other subscribers' and do not count)
    """
    out = compare_exact(expected, wit["values"], half_lsb)
    stops = [r for r in wit["records"] if r.get("event") == "stop"]
    counts = stops[-1].get("counts") if stops else None       # the witness's own count at its stop
    if not isinstance(counts, dict):                           # no stop record, or one without its counts: not a clean stop
        counts = None
    out["read_error"] = read_error
    out["initial_values"] = wit["initial_values"]
    out["errors"] = [r for r in wit["records"] if r.get("event") in ("subscription-error", "stream-ended")]
    out["stop_counts_equal_log"] = counts is not None and all(
        counts.get(p, 0) == len(wit["values"].get(p, [])) for p in set(counts) | set(wit["values"]))
    out["broker_lagged"] = broker_misses(broker_log, capacity=capacity)
    out["gates"] = {"values_exact": out["ok"], "log_read": read_error is None, "no_initial_values": wit["initial_values"] == 0,
                    "no_stream_errors": not out["errors"], "stop_counts_equal_log": out["stop_counts_equal_log"],
                    "no_broker_lag": out["broker_lagged"] == 0}
    out["ok"] = all(out["gates"].values())
    return out


def anchor_time(points: Sequence[Tuple[float, Any]]) -> Optional[float]:
    for t, v in points:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
            return t
    return None


def to_rec_ms(t: float, t_anchor: float, anchor_rec_ms: int) -> float:
    return (t - t_anchor) * 1000.0 + anchor_rec_ms


def in_window(x: Optional[float], window: Sequence[float]) -> bool:
    return x is not None and window[0] <= x < window[1]


# --- the app's log ------------------------------------------------------------------------------

def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def app_events(records: Sequence[Dict[str, Any]], anchor_rec_ms: int) -> Dict[str, Any]:
    """Decisions and actuations mapped onto recording time, the heartbeat records, the input counts."""
    first = [r for r in records if r.get("event") == "input" and r.get("path") == V_PATH and r.get("value") not in (None, 0, 0.0)]
    t_anchor = first[0]["t"] if first else None
    decisions, actuations = [], []
    for r in records:
        if r.get("event") == "decision":
            decisions.append({"hazard": r["hazard"], "trigger": r["trigger"], "v": r["v"], "a": r["a"], "decel": r["decel"],
                              "t_rec_ms": None if t_anchor is None else to_rec_ms(r["t"], t_anchor, anchor_rec_ms)})
        elif r.get("event") == "actuate":
            actuations.append({"value": r["value"], "result": r["result"],
                               "t_rec_ms": None if t_anchor is None else to_rec_ms(r["t"], t_anchor, anchor_rec_ms)})
    beats = [r for r in records if r.get("event") == "heartbeat"]
    counts = beats[-1]["inputs_received"] if beats else {}
    return {"anchor_found": t_anchor is not None, "decisions": decisions, "actuations": actuations,
            "heartbeats": [b["record"] for b in beats], "inputs_received": counts,
            "monitor_display": [r for r in records if r.get("event") == "monitor-display"],
            "errors": [r for r in records if r.get("event", "").endswith("-error")]}


def collapse(records: Sequence[Dict[str, Any]], keys: Sequence[str]) -> List[Tuple[Any, ...]]:
    """The sequence of distinct consecutive tuples of `keys` (a heartbeat history without seq)."""
    out: List[Tuple[Any, ...]] = []
    for r in records:
        k = tuple(r[x] for x in keys)
        if not out or out[-1] != k:
            out.append(k)
    return out


def window_verdict(decisions: Sequence[Dict[str, Any]], windows: Dict[str, Any]) -> Dict[str, Any]:
    ons = [d for d in decisions if d["hazard"]]
    offs = [d for d in decisions if not d["hazard"]]
    on_t = ons[0]["t_rec_ms"] if ons else None
    off_t = offs[0]["t_rec_ms"] if offs else None
    ok = (len(ons) == 1 and len(offs) == 1 and in_window(on_t, windows["on_window_ms"]) and in_window(off_t, windows["off_window_ms"])
          and not (math.isnan(on_t or 0.0)))
    return {"ok": ok, "n_on": len(ons), "n_off": len(offs), "on_t_rec_ms": on_t, "off_t_rec_ms": off_t}


# --- the hazard light: what the verdict may read, and what it only reports -------------------------
# The recorder is a kuksa.val.v1 subscriber with a buffer of one: the databroker drops an update when
# it lags (and logs it), so a replay's behaviour key and window gate must not read the recorder's
# hazard rows. They read the app's own log (decisions, actuations) and the mock provider's own log
# (its 'Feeding' lines, which it writes just before it makes each write of the light: a line is a write
# the mock was about to make, not one the databroker accepted, so the gate also wants the log clean).
# The recorder's rows are kept, as the databroker's v1 view, and checked against those two for
# consistency; that check is reported and never part of the verdict.

# `docker logs -t` puts dockerd's receive stamp and one space before every line of a container's output,
# a traceback's lines included. The mock provider's INFO records read "INFO:<logger>:<message>".
DOCKER_STAMPED = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z (.*)$")
INFO_RECORD = re.compile(r"^INFO:[\w.\-]+:")


def mock_log_offending(text: str) -> List[str]:
    """The lines of the mock provider's `docker logs -t` text whose body after the dockerd stamp is not
    an INFO record (a Traceback and its lines, an ERROR or a WARNING line, 'Exception in thread', a
    DEBUG line, an empty line), and any line with no stamp at all. The mock logs 'Feeding ... with
    value X' just before it calls the databroker (the pinned image's mockservice.py, as the r4 critic
    read it), and its client turns a failed call into an exception its own handler does not catch: a
    write the databroker refused leaves the 'Feeding' line and then lines this returns."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                                    # the text's last newline ends a line, it does not start one
    out = []
    for line in lines:
        line = line.rstrip("\r")
        m = DOCKER_STAMPED.match(line)
        if m is None or INFO_RECORD.match(m.group(1)) is None:
            out.append(line)
    return out


def mock_log_clean(text: str) -> bool:
    """No line of the mock provider's log is anything but an INFO record (mock_log_offending is empty)."""
    return not mock_log_offending(text)


def mock_gate(mock_writes: Sequence[Dict[str, Any]], windows: Dict[str, Any], log_clean: bool) -> bool:
    """The mock provider's own log: a clean log (mock_log_clean) with exactly three writes of the light,
    in this order: False (its initial value), True inside the on window, False inside the off window.
    The writes are the 'Feeding' lines, which the mock logs before it makes the write: only a clean
    log says none of them failed."""
    return (log_clean
            and [m["value"] for m in mock_writes] == [False, True, False]
            and in_window(mock_writes[1]["t_rec_ms"], windows["on_window_ms"])
            and in_window(mock_writes[2]["t_rec_ms"], windows["off_window_ms"]))


def behaviour_key(decisions: Sequence[Sequence[Any]], actuations: Sequence[Dict[str, Any]],
                  mock_writes: Sequence[Dict[str, Any]], appstate: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """What a replay did, from lossless sources only, for comparing replays: the app's decisions
    (hazard, trigger, v, a), the targets the app itself requested (value and the outcome it logged),
    the lights as the mock provider wrote them, and the app's state sequence. No time enters it, and
    nothing of the recorder's CSV."""
    return {"decisions": [list(d) for d in decisions],
            "targets": [[a["value"], a["result"]] for a in actuations],
            "lights": [m["value"] for m in mock_writes],
            "appstate": [list(x) for x in appstate]}


def recorder_light_view(rows: Sequence[Dict[str, Any]], t_anchor: Optional[float], mock_writes: Sequence[Dict[str, Any]],
                        actuations: Sequence[Dict[str, Any]], allowed_misses: int, windows: Dict[str, Any], anchor_rec_ms: int,
                        hazard_path: str = HAZARD) -> Dict[str, Any]:
    """The recorder's rows of the hazard light, the databroker's kuksa.val.v1 view of it: the current
    value's changes mapped onto recording time through the recorder's own anchor (t_anchor, the time
    of its first non-zero velocity), whether they switch once in each window, and `consistent`: its
    current rows against the mock provider's writes and its target rows against the app's actuations,
    each a subsequence of them (compare_values) with no more rows missing than allowed_misses, the
    updates the databroker says its capacity-1 subscribers missed that the recorder's other rows did
    not already account for. Reported, never part of a replay's verdict."""
    current = series(rows, hazard_path)
    targets = [v for _t, v in series(rows, hazard_path, "target")]
    lights = [{"value": v, "t_rec_ms": None if t_anchor is None else to_rec_ms(t, t_anchor, anchor_rec_ms)} for t, v in current]
    changes = [x for i, x in enumerate(lights) if i == 0 or x["value"] != lights[i - 1]["value"]]
    on = [x for x in changes if x["value"] is True]
    off = [x for x in changes[1:] if x["value"] is False]
    in_windows = (len(on) == 1 and len(off) == 1 and in_window(on[0]["t_rec_ms"], windows["on_window_ms"])
                  and in_window(off[0]["t_rec_ms"], windows["off_window_ms"]) and changes[0]["value"] is False)
    consistent = compare_values({"current": [m["value"] for m in mock_writes], "target": [a["value"] for a in actuations]},
                                {"current": 0.0, "target": 0.0}, {"current": [v for _t, v in current], "target": targets},
                                allowed_misses)
    return {"in_window": in_windows, "changes": changes, "targets": targets, "consistent": consistent,
            "note": "the recorder's kuksa.val.v1 rows (a buffer of one, lossy): reported, never part of the verdict"}
