"""reasonsets.py -- the event-to-reason sets Phase 2 step 3 compares (sdv/bridge; kind4-spec 16.2 P13).

Phase 2 step 3 runs the same recording through the bridge in each source
mode (broker, can, replay) and compares what the guest answered. Its evidence is the bridge's reply log
(vss_claim_bridge.py's replies.jsonl), never the guest's console, which prints a kind 4 REJECT only when the
reason changes (spec 12). The modes sample at different instants, so their frames are not the same frames:

- across modes, the comparison is of sets of (event, reason): every reject in an event's window gives
  (event, reason), and a reject outside every window gives (None, reason), an unexpected one. Identical sets
  pass; a missing or an extra pair fails;
- frame by frame, only between two `replay` runs: replay is the deterministic mode (spec 14.1), so two replays
  of one recording pack the same frames apart from the header's tstamp (P4). Any other pairing is refused.

An event window is {"event": name, "t0_ns": start, "t1_ns": end}, half open, on the clock of the reply
records' src_now_ns (the source's own clock at packing, the one the age is computed on). The events
themselves (the injected recording's events file) are Phase 2 WP9's; taken as offsets from the
recording's first frame, each mode's run puts them on its own src_now_ns clock with shift_windows and an
origin:

- replay: src_now_ns is CLOCK_MONOTONIC read down to a tick grid whose origin, the instant the file's first
  frame maps to, is a per-run value (bridge_sources.ReplaySource). The run logs it once, as the
  `replay-anchored` record of bridge.jsonl (anchor_ns; source.json carries it too), so a window at offset
  off maps to anchor_ns + off, read back from the run's own record by replay_anchor. No reply is needed to
  find it, and no heuristic (such as "the first reply with age 0") is used;
- can and broker: src_now_ns is CLOCK_REALTIME (the receive time, the datapoint timestamp), so the origin is
  the instant the player sent the recording's first frame on CLOCK_REALTIME, which the stack records
  (Phase 2 WP10: sdv/stack/step3.py takes its vcan capture's receive time of that frame; not this module, and
  not the bridge, which never sees the player).

Across the modes (compare_modes): the runs of one recording, at least one per mode, and every set equal to every
other; a mode with no run fails the comparison, so it can never pass by leaving a mode out. The frames for the
replay comparison are the reply log's own (each reply record carries the 64 bytes sent; reply_frames).

Standard library only.

Does not demonstrate: that the events file names the right windows, or any timing.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

Pair = Tuple[Optional[str], int]

TSTAMP = slice(8, 16)          # the frame header's tstamp (ipc-test/common/frame.h): the one field two replays may differ in
REPLAY_ANCHORED = "replay-anchored"     # the bridge.jsonl record of a replay run's grid origin (bridge_sources.py logs it)


def replay_anchor(bridge_records: Iterable[Mapping[str, Any]]) -> int:
    """A replay run's grid origin (anchor_ns) from its bridge.jsonl records: the src_now_ns its recording's first
    frame maps to. Exactly one `replay-anchored` record is required; a run without one is refused (ValueError)."""
    found = [r for r in bridge_records if r.get("event") == REPLAY_ANCHORED]
    if len(found) != 1:
        raise ValueError("a replay run logs its anchor exactly once; found %d %s records" % (len(found), REPLAY_ANCHORED))
    return int(found[0]["anchor_ns"])


def shift_windows(windows: Sequence[Mapping[str, Any]], origin_ns: int) -> List[Dict[str, Any]]:
    """Windows whose t0_ns and t1_ns are offsets from a recording's first frame, moved onto a run's src_now_ns
    clock by its origin (module docstring); every other key is kept."""
    return [dict(w, t0_ns=int(origin_ns) + int(w["t0_ns"]), t1_ns=int(origin_ns) + int(w["t1_ns"])) for w in windows]


def reason_set(replies: Iterable[Mapping[str, Any]], windows: Sequence[Mapping[str, Any]],
               time_key: str = "src_now_ns") -> Set[Pair]:
    """{(event, reason)} of a reply log's rejects: the event whose window holds the record's time_key, or
    None outside every window. Overlapping windows are refused: a reject must belong to one event."""
    spans = sorted((int(w["t0_ns"]), int(w["t1_ns"]), str(w["event"])) for w in windows)
    for (_a0, a1, an), (b0, _b1, bn) in zip(spans, spans[1:]):
        if b0 < a1:
            raise ValueError("event windows %s and %s overlap" % (an, bn))
    for t0, t1, name in spans:
        if not t0 < t1:
            raise ValueError("event window %s is empty" % name)
    out: Set[Pair] = set()
    for r in replies:
        if not r.get("verdict"):
            continue
        t = int(r[time_key])
        event = next((name for t0, t1, name in spans if t0 <= t < t1), None)
        out.add((event, int(r["reason"])))
    return out


def compare(expected: Set[Pair], got: Set[Pair]) -> Dict[str, Any]:
    """Two event-to-reason sets: ok only when equal; missing and extra name the difference."""
    key = _sort_key
    return {"ok": expected == got, "missing": sorted(expected - got, key=key), "extra": sorted(got - expected, key=key)}


def _sort_key(p: Pair) -> Tuple[str, int]:
    return ("" if p[0] is None else p[0], p[1])


def compare_frames(run_a: Mapping[str, Any], run_b: Mapping[str, Any]) -> Dict[str, Any]:
    """Frame by frame, between two replay runs only: each run is {"mode": ..., "frames": [64-byte frames in
    seq order]}. The frames must be equal apart from the header's tstamp; returns {"ok", "differ": [index],
    "lengths": (len a, len b)}."""
    modes = (run_a.get("mode"), run_b.get("mode"))
    if modes != ("replay", "replay"):
        raise ValueError("frame-by-frame comparison is offered only between two replay runs, not %s and %s" % modes)
    fa: List[bytes] = [bytes(f) for f in run_a["frames"]]
    fb: List[bytes] = [bytes(f) for f in run_b["frames"]]
    differ = [i for i, (a, b) in enumerate(zip(fa, fb)) if _without_tstamp(a) != _without_tstamp(b)]
    return {"ok": not differ and len(fa) == len(fb), "differ": differ, "lengths": (len(fa), len(fb))}


def _without_tstamp(frame: bytes) -> bytes:
    return frame[:TSTAMP.start] + frame[TSTAMP.stop:]


MODES = ("broker", "can", "replay")     # the bridge's source modes (vss_claim_bridge.MODES; a test holds the two equal)


def compare_modes(runs: Sequence[Tuple[str, Set[Pair]]], modes: Sequence[str] = MODES) -> Dict[str, Any]:
    """Phase 2 step 3's comparison of one recording across the bridge's modes: runs is [(mode, set)], one entry per run.
    ok only when every mode in `modes` has a run and every run's set equals every other's; `missing_modes` names a
    mode with none, `differ` each run whose set is not the first run's (its missing and extra pairs against it), and
    `unknown_modes` a run of a mode not in `modes` (refused: it is not one of the comparison's)."""
    seen = [m for m, _s in runs]
    missing = [m for m in modes if m not in seen]
    unknown = sorted({m for m in seen if m not in modes})
    differ = []
    if runs:
        ref_mode, ref = runs[0]
        for i, (mode, got) in enumerate(runs):
            c = compare(ref, got)
            if not c["ok"]:
                differ.append({"run": i, "mode": mode, "against": ref_mode, "missing": c["missing"], "extra": c["extra"]})
    return {"ok": bool(runs) and not missing and not unknown and not differ, "modes": seen, "missing_modes": missing,
            "unknown_modes": unknown, "differ": differ}


def reply_frames(replies: Iterable[Mapping[str, Any]]) -> List[bytes]:
    """The frames a run sent, in seq order, from its reply log (each reply record's `frame`, the 64 bytes sent, hex):
    what compare_frames takes. A reply with no frame is refused (ValueError): a log written before the records
    carried one cannot be compared frame by frame."""
    out = []
    for r in sorted(replies, key=lambda r: int(r["seq"])):
        if not isinstance(r.get("frame"), str):
            raise ValueError("reply seq %s carries no frame" % r.get("seq"))
        out.append(bytes.fromhex(r["frame"]))
    return out
