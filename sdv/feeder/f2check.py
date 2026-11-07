#!/usr/bin/env python3
"""f2check.py -- K4 16.4's F2 over a live run: the guest's first 22 after the feeder's last frame, within AGE_MAX plus one tick (sdv/feeder).

SDV plan Phase 7 WP3c (spec-2 2.4 and section 6 item 4). Runs in WSL with the sim venv's
or the feeder venv's Python (the standard library, this package and the generated contract), from the repo root, once
`stack.py live` and `live.py run --freeze-at-s T` have ended:

    python sdv/feeder/f2check.py RUN_DIR [--feeder-out DIR]

RUN_DIR is the live run's directory, the one `stack.py live` printed (~/sdv-runs/<date>-<name>/). Its LIVE_REPLAY
directory holds the records read here: result.json (the bridge mode, the take's directory, its --feeder-out, and the run's own
gates), attribution.json (the run header), bridge/replies.jsonl (the bridge's per-frame verdicts), CAPTURE (every frame on
vcan0 with its SocketCAN receive time) and monitor.log (the native monitor's console); the take's live.json is read from the
take's directory (or from --feeder-out). It writes RUN_DIR/f2.json, never over an existing one, and exits 0 when the verdict
is ok, 1 when it is not, and 2 when the records cannot be read or judged (a reply record with no src_now_ns, say),
result.json holds no gates (no live run's), or the run header's AGE_MAX is not the generated contract's.

THE VERDICT (verdict, pure), one per run and so per bridge mode:
  froze            live.json records a freeze of live.py's FREEZE_S.
  the last frame   the latest frame on vcan0 in the stack's capture (python-can's SocketCAN receive times, CLOCK_REALTIME):
                   the feeder is the bus's one sender, and after its freeze nothing follows its last frame. In `can` mode its
                   receive time is the age source of the values it carried. In `broker` mode the age source is the datapoint
                   timestamp the databroker sets on receipt, which no record holds for the last frame (the bridge keeps it
                   and logs only each frame's age): the receive time is a lower bound of it (the CAN provider reads the frame,
                   then writes it), so the delay below is an upper bound of the delay from the datapoint timestamp, and a pass
                   stands. Beside it, information only: the first 22's own age (its age_ms, the bridge's age of the oldest
                   value it packed, truncated to ms) and the age-source time it implies for that oldest slot (src_now_ns
                   minus age_ms, at most 1 ms after it): in broker mode that slot's datapoint timestamp, in can mode its
                   receive time; the oldest slot's, which is never later than the last frame's.
  the first 22     the first reply with reason 22 (vss-stale) packed after the last frame (its src_now_ns, CLOCK_REALTIME,
                   the bridge's age clock in both modes); within when its delay from the last frame is at most AGE_MAX (the
                   generated contract's AGE_MAX_MS) plus one tick (live.py's TICK_MS), K4 16.4's bound.
  before freeze    every reply packed before the freeze began (live.json's freeze start, CLOCK_REALTIME) is ACCEPT, and
                   there is at least one.
  no MISS          no `monitor: LIVENESS MISS:` line in the native monitor's console before its last `monitor: client done:`
                   line, where the bridge's last session ended (step3.console_view's rule for the same monitor): the
                   monitor outlives the bridge at a live run's end (stack.py live stops the bridge, then the other
                   containers, then the monitor) and reports that silence, which is not the run's. The MISS lines after it
                   are counted apart (miss_after_last_session). A console with no `client done:` is judged whole.
  answered after   the bridge's last reply was packed at or after the freeze's end (live.json's end_real_ns): its last
  the freeze       session lasted through the freeze, so a MISS of the freeze cannot fall after that session's end.
  feeder ok        live.json's take exit code is 0 (completed and cleaned up) and no send failed.
  run gates        result.json's own gates (stack.live_gates: C12a, C8, the listeners, the take, C12b, the bridge) all hold,
                   recorded by name (run_gates): F2's ok is never said of a run the stack itself failed.
  ok               every check holds. Nothing is tuned to a run: the bound and FREEZE_S come from the contract and live.py.

DOES NOT DEMONSTRATE: any timing (the bound is a functional deadline: one 22 inside it and no MISS; no delay here is a
figure), CAN timing (vcan has no arbitration), vehicle dynamics; in broker mode, the datapoint timestamp of the last frame
itself (only the oldest slot's at the first 22).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_FRAME_DIR = str(REPO / "sdv" / "frame")
if _FRAME_DIR not in sys.path:
    sys.path.insert(0, _FRAME_DIR)
import rules  # noqa: E402
import vssframe  # noqa: E402


def _load_live() -> Any:
    """live.py by path, under the name its tests give it (its design values: FREEZE_S, TICK_MS, LIVE_JSON)."""
    name = "sdv_feeder_live"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(HERE / "live.py"))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % (HERE / "live.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    return mod


live = _load_live()

F2_JSON = "f2.json"
LIVE_REPLAY = "live-1"                 # stack.py's LIVE_REPLAY: the live run's one replay directory (a test holds them equal)
CAPTURE = "vcan-capture.json"          # stack.py's LIVE_CAPTURE
MISS = "monitor: LIVENESS MISS: "      # step3.MISS (a test holds them equal)
DONE = "monitor: client done: "        # step3.DONE: a bridge session's end in the native monitor's console
NS_PER_MS = 1_000_000
MODES = ("broker", "can")
AGE_SOURCES = {
    "can": "the SocketCAN receive time of the feeder's last frame on vcan0 (the stack's capture): the age source of the values "
           "it carried in can mode",
    "broker": "the SocketCAN receive time of the feeder's last frame on vcan0 (the stack's capture): a lower bound of its values' "
              "datapoint timestamp, the age source in broker mode, which no record holds for the last frame (the databroker "
              "stamps on receipt, after the CAN provider read the frame), so the delay is an upper bound",
}
OLDEST_SLOT_SOURCES = {
    "can": "the first 22's src_now_ns minus its age_ms: the receive time of the oldest value it packed (the age source in can "
           "mode), at most 1 ms after it (age_ms is truncated to ms); information only",
    "broker": "the first 22's src_now_ns minus its age_ms: the datapoint timestamp of the oldest value it packed (the age source "
              "in broker mode), at most 1 ms after it (age_ms is truncated to ms), never later than the last frame's; "
              "information only",
}


class F2Refused(RuntimeError):
    """Records f2check cannot judge."""


def console_split(console: str) -> Tuple[int, List[str], List[str]]:
    """The native monitor's console split at its last `client done:` line, the bridge's last session's end (step3.console_view's
    native rule): (the sessions ended, the lines before that line, the lines after it); no such line: all lines before."""
    lines = console.splitlines()
    ends = [i for i, ln in enumerate(lines) if ln.startswith(DONE)]
    if not ends:
        return 0, lines, []
    return len(ends), lines[:ends[-1]], lines[ends[-1] + 1:]


def _int(x: Any) -> Optional[int]:
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def verdict(mode: str, replies: Sequence[Dict[str, Any]], frames: Sequence[Sequence[Any]], console: str, live_doc: Dict[str, Any],
            age_max_ms: int, tick_ms: int, freeze_s: float, run_gates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """f2.json's verdict (the module docstring, THE VERDICT). replies: the bridge's reply records; frames: [t_ns, can_id, data]
    on CLOCK_REALTIME; console: the native monitor's; live_doc: the take's live.json; run_gates: result.json's gates (main
    always passes them; None judges the F2 records alone and adds no run_gates check)."""
    bound_ms = int(age_max_ms) + int(tick_ms)
    fz = live_doc.get("freeze") if isinstance(live_doc, dict) else None
    froze = (isinstance(fz, dict) and fz.get("freeze_s") == freeze_s and isinstance(fz.get("start_real_ns"), int)
             and not isinstance(fz.get("start_real_ns"), bool))
    ordered = sorted((int(f[0]), int(f[1])) for f in frames)
    last = ordered[-1] if ordered else None
    by_time = sorted(replies, key=lambda r: (int(r["src_now_ns"]), int(r.get("seq", 0))))
    before = [r for r in by_time if froze and int(r["src_now_ns"]) < int(fz["start_real_ns"])] if isinstance(fz, dict) else []
    not_accepted = [r for r in before if r.get("reason") != rules.RSN_OK]
    first22 = None
    if last is not None:
        first22 = next((r for r in by_time if r.get("reason") == rules.RSN_VSS_STALE and int(r["src_now_ns"]) > last[0]), None)
    delay_ns = int(first22["src_now_ns"]) - last[0] if first22 is not None and last is not None else None
    age_ms = _int(first22.get("age_ms")) if first22 is not None else None
    sessions, during, after = console_split(console)
    miss = sum(1 for ln in during if ln.startswith(MISS))
    end_real = _int(fz.get("end_real_ns")) if isinstance(fz, dict) else None
    last_reply = int(by_time[-1]["src_now_ns"]) if by_time else None
    take_rc = live_doc.get("take_rc") if isinstance(live_doc, dict) else None
    send_errors = live_doc.get("send_errors") if isinstance(live_doc, dict) else None
    checks = {
        "froze": bool(froze),
        "last_frame_found": last is not None,
        "first_22_found": first22 is not None,
        "first_22_within_bound": delay_ns is not None and delay_ns <= bound_ms * NS_PER_MS,
        "every_frame_before_the_freeze_accepted": bool(before) and not not_accepted,
        "no_miss": miss == 0,
        "bridge_answered_after_the_freeze": end_real is not None and last_reply is not None and last_reply >= end_real,
        "feeder_ok": _int(take_rc) == 0 and send_errors == [],
    }
    if run_gates is not None:
        checks["run_gates"] = bool(run_gates) and all(v is True for v in run_gates.values())
    out = {
        "format": 1, "mode": mode, "age_source": AGE_SOURCES[mode], "age_max_ms": int(age_max_ms), "tick_ms": int(tick_ms),
        "bound_ms": bound_ms, "freeze_s": freeze_s, "freeze": fz,
        "last_frame": None if last is None else {
            "t_ns": last[0], "can_id": "0x%03X" % last[1], "frames_on_bus": len(ordered),
            "after_freeze_start_ms": (last[0] - int(fz["start_real_ns"])) / NS_PER_MS if froze and isinstance(fz, dict) else None},
        "first_22": None if first22 is None or delay_ns is None else {
            "seq": first22.get("seq"), "src_now_ns": int(first22["src_now_ns"]), "delay_ms": delay_ns / NS_PER_MS,
            "age_ms": age_ms,
            "oldest_slot_age_source_ns": None if age_ms is None else int(first22["src_now_ns"]) - age_ms * NS_PER_MS},
        "oldest_slot_age_source": OLDEST_SLOT_SOURCES[mode],
        "before_freeze": {"replies": len(before), "accepted": len(before) - len(not_accepted),
                          "not_accepted": [{"seq": r.get("seq"), "reason": r.get("reason")} for r in not_accepted[:20]]},
        "miss": miss, "miss_after_last_session": sum(1 for ln in after if ln.startswith(MISS)), "sessions": sessions,
        "last_reply_src_now_ns": last_reply,
        "feeder": {"take_rc": take_rc, "send_errors": len(send_errors) if isinstance(send_errors, list) else None},
        "checks": checks, "ok": all(checks.values()),
    }
    if run_gates is not None:
        out["run_gates"] = dict(run_gates)
    return out


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _replies(path: Path) -> List[Dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("event") == "reply":
                out.append(rec)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("run", type=Path, help="the live run's directory (stack.py live printed it)")
    ap.add_argument("--feeder-out", type=Path, default=None, help="the take's directory, if not the one the run recorded")
    a = ap.parse_args(argv)
    run = a.run.expanduser()
    out = run / F2_JSON
    try:
        if out.exists():
            raise F2Refused("%s exists: a verdict is never rewritten" % out)
        rd = run / LIVE_REPLAY
        result = _json(rd / "result.json")
        header = _json(rd / "attribution.json")["header"]
        mode = result["bridge_mode"]
        if mode not in MODES:
            raise F2Refused("the run's bridge mode %r is not one of %s" % (mode, ", ".join(MODES)))
        gates = result["gates"]
        if not isinstance(gates, dict):
            raise F2Refused("result.json's gates are not a table of the run's gates: %r" % (gates,))
        feeder_out = (a.feeder_out.expanduser() if a.feeder_out is not None else Path(result["feeder_out"]))
        doc = _json(feeder_out / live.LIVE_JSON)
        replies = _replies(rd / "bridge" / "replies.jsonl")
        frames = _json(rd / CAPTURE)["frames"]
        console = (rd / "monitor.log").read_text(encoding="utf-8", errors="replace")
        contract = vssframe.load_contract()
        if header.get("age_max_ms") != int(contract.AGE_MAX_MS):
            raise F2Refused("the run header's age_max_ms %r is not the generated contract's AGE_MAX_MS %r"
                            % (header.get("age_max_ms"), contract.AGE_MAX_MS))
        v = verdict(mode, replies, frames, console, doc, int(contract.AGE_MAX_MS), live.TICK_MS, live.FREEZE_S, run_gates=gates)
    except (F2Refused, OSError, ValueError, KeyError, TypeError, vssframe.ContractError) as e:      # also a record verdict cannot read
        print("f2check.py: refused: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    v.update(run=run.name, feeder_out=str(feeder_out))
    out.write_text(json.dumps(v, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": v["ok"], "checks": v["checks"]}, sort_keys=True))
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
