#!/usr/bin/env python3
"""ctlreplay.py -- replay a recorded drive's export through the kind 2 core, with no ROS (sdv/ctl).

The Phase 8 specification (the project's local design notes, sections 2.7 and 4 item
5; not in this tree) defines it: the earlier plan's replay source, for a host where ROS does not run (the bare-metal
host's Python) and for comparing a replay's verdicts with the live run's.

    ctlreplay.py --export FILE.jsonl --host ADDR [--port 7150] [--stamp] [--profile ID] [--demo START_MS:DURATION_MS]
        [--inject SEQ:MODE ...] [--pause AFTER_SEQ:DURATION_MS] [--contract vss_ctl.py] --out DIR

The export is 2.7's JSON Lines (ctl_export.py writes it): one message per line in receive order, then the summary
line. It is checked whole before anything is sent: every line's keys and types, the topics, the receive times never
decreasing, the summary's counts and format. Each Control is then handed to ctlclient.py's core -- the node's core,
with the same arguments, reply log and header (mode "replay", plus the export's sha256) -- paired with the latest
odometry received before it in the file (never a later one), and offered at its recorded receive time after the first
Control's; the core takes the interval from the recorded stamps (never the receive times) and judges the odometry's
freshness on the recorded receive times, so reasons 11, 17, 18 and 19 come out as they would have live. A value the
export holds as null (a non-finite value in the bag) is packed as a quiet NaN, which the monitor answers with 9 as it
would have answered the original. The other four topics of the export are read and checked but not sent.

Exit 0 when the accounting identity holds, 1 when it does not, 2 for a refusal before anything is sent.

Does not demonstrate: that a replay reproduces the live run's verdicts (that is what comparing the two reply logs
shows, or fails to); any timing: the offers follow the recorded spacing only as closely as this host's scheduler
allows.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ctlclient as cc  # noqa: E402

CONTROL_TOPIC = "/control/command/control_cmd"
ODOM_TOPIC = "/localization/kinematic_state"
EXPORT_FORMAT = 1
RECORD_KEYS = ("topic", "recv_ns", "stamp_ns", "fields")
SUMMARY_KEYS = ("messages", "bag_sha256", "export_format")
NUM, FLAG, INT, STR = "number", "bool", "int", "str"
# 2.7: each topic's fields and their types (a number may be null: a non-finite value in the bag).
EXPORT_FIELDS: Dict[str, Dict[str, str]] = {
    CONTROL_TOPIC: {"velocity": NUM, "acceleration": NUM, "jerk": NUM, "is_defined_acceleration": FLAG, "is_defined_jerk": FLAG,
                    "steering_tire_angle": NUM, "steering_tire_rotation_rate": NUM,
                    "is_defined_steering_tire_rotation_rate": FLAG},
    ODOM_TOPIC: {"v": NUM},
    "/vehicle/status/velocity_status": {"longitudinal_velocity": NUM, "heading_rate": NUM},
    "/vehicle/status/steering_status": {"steering_tire_angle": NUM},
    "/vehicle/status/gear_status": {"report": INT, "report_name": STR},
    "/localization/acceleration": {"ax": NUM},
}
POLL_S = 0.05                          # the longest wait between two looks at the clock while a Control is not yet due


class ReplayError(RuntimeError):
    """An export this replay refuses."""


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _typed(kind: str, x: Any) -> bool:
    if kind == NUM:
        return x is None or (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))
    if kind == FLAG:
        return isinstance(x, bool)
    if kind == INT:
        return _is_int(x)
    return isinstance(x, str)


def check_record(obj: Any) -> None:
    """One message line of 2.7, or ReplayError: exactly its four keys, a known topic with exactly its fields, each of
    its type, recv_ns an int, stamp_ns an int or null (an int for a Control: its interval comes from it)."""
    if not isinstance(obj, dict) or set(obj) != set(RECORD_KEYS):
        raise ReplayError("a line is not {topic, recv_ns, stamp_ns, fields}: %r" % (sorted(obj) if isinstance(obj, dict) else obj,))
    topic, fields = obj["topic"], obj["fields"]
    if topic not in EXPORT_FIELDS:
        raise ReplayError("topic %r is not one of the export's" % (topic,))
    if not _is_int(obj["recv_ns"]) or obj["recv_ns"] < 0:
        raise ReplayError("%s: recv_ns %r is not a non-negative int" % (topic, obj["recv_ns"]))
    st = obj["stamp_ns"]
    if not (st is None or _is_int(st)) or (topic == CONTROL_TOPIC and st is None):
        raise ReplayError("%s: stamp_ns %r" % (topic, st))
    want = EXPORT_FIELDS[topic]
    if not isinstance(fields, dict) or set(fields) != set(want):
        raise ReplayError("%s: fields %r are not %s" % (topic, sorted(fields) if isinstance(fields, dict) else fields, sorted(want)))
    bad = [k for k, kind in want.items() if not _typed(kind, fields[k])]
    if bad:
        raise ReplayError("%s: fields of the wrong type: %s" % (topic, ", ".join(bad)))


def _strict(line: str) -> Any:
    def refuse(const: str) -> Any:
        raise ReplayError("%s is not JSON" % const)
    try:
        return json.loads(line, parse_constant=refuse)
    except ValueError as err:
        raise ReplayError("a line that is not JSON: %s" % err) from err


def read_export(path: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """(the message records in file order, the summary), the export checked whole."""
    records: List[Dict[str, Any]] = []
    summary: Optional[Dict[str, Any]] = None
    last_recv = -1
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            if not line.strip():
                raise ReplayError("line %d is empty" % i)
            obj = _strict(line)
            if summary is not None:
                raise ReplayError("line %d comes after the summary" % i)
            if isinstance(obj, dict) and set(obj) == {"summary"}:
                summary = obj["summary"]
                continue
            check_record(obj)
            if obj["recv_ns"] < last_recv:
                raise ReplayError("line %d: recv_ns goes back (the export is in receive order)" % i)
            last_recv = obj["recv_ns"]
            records.append(obj)
    if summary is None:
        raise ReplayError("no summary line: the export is incomplete")
    if not isinstance(summary, dict) or set(summary) != set(SUMMARY_KEYS):
        raise ReplayError("the summary is not {messages, bag_sha256, export_format}")
    if not _is_int(summary["export_format"]) or summary["export_format"] != EXPORT_FORMAT:
        raise ReplayError("export_format %r is not %d" % (summary["export_format"], EXPORT_FORMAT))
    counts: Dict[str, int] = {}
    for r in records:
        counts[r["topic"]] = counts.get(r["topic"], 0) + 1
    stated = summary["messages"]
    if not isinstance(stated, dict) or any(not _is_int(n) for n in stated.values()) \
            or {t: n for t, n in stated.items() if n} != counts:
        raise ReplayError("the summary's message counts %r are not the file's %r" % (stated, counts))
    return records, summary


def _value(x: Optional[float]) -> float:
    return float("nan") if x is None else float(x)


def controls_with_odometry(records: Sequence[Mapping[str, Any]]) -> List[Tuple[cc.Control, Optional[cc.Odometry]]]:
    """Each Control with the latest odometry before it in receive order (None before the first one), both with their
    recorded receive times."""
    out: List[Tuple[cc.Control, Optional[cc.Odometry]]] = []
    odom: Optional[cc.Odometry] = None
    for r in records:
        f = r["fields"]
        if r["topic"] == ODOM_TOPIC:
            odom = cc.Odometry(v=_value(f["v"]), recv_ns=r["recv_ns"])
        elif r["topic"] == CONTROL_TOPIC:
            out.append((cc.Control(stamp_ns=r["stamp_ns"], recv_ns=r["recv_ns"], velocity=_value(f["velocity"]),
                                   acceleration=_value(f["acceleration"]), is_defined_acceleration=f["is_defined_acceleration"],
                                   jerk=_value(f["jerk"]), is_defined_jerk=f["is_defined_jerk"],
                                   steering_tire_angle=_value(f["steering_tire_angle"]),
                                   steering_tire_rotation_rate=_value(f["steering_tire_rotation_rate"]),
                                   is_defined_steering_tire_rotation_rate=f["is_defined_steering_tire_rotation_rate"]), odom))
    return out


def schedule_ns(pairs: Sequence[Tuple[cc.Control, Optional[cc.Odometry]]]) -> List[int]:
    """Each Control's offset from the first Control, from the recorded receive times."""
    if not pairs:
        return []
    first = pairs[0][0].recv_ns
    return [c.recv_ns - first for c, _o in pairs]


def file_sha256(path: Any) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay(export: Any, cfg: cc.Config, contract: Any, reply_log: Optional[Any] = None,
           clock: Callable[[], int] = time.monotonic_ns, sink: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Send the export's Controls through the core at their recorded spacing, inline (no client thread), then stop
    (the drain) and return the summary."""
    records, _summary = read_export(export)
    pairs = controls_with_odometry(records)
    offsets = schedule_ns(pairs)
    c = cc.CtlClient(cfg, contract, clock=clock, sink=sink, reply_log=reply_log, mode="replay",
                     header_extra={"export_sha256": file_sha256(export), "export_controls": len(pairs)})
    start = clock()
    try:
        for (ctl, odom), off in zip(pairs, offsets):
            due = start + off
            while True:
                now = clock()
                if now >= due:
                    break
                c.wait(min((due - now) / 1e9, POLL_S))
            c.offer(ctl, odom)
            c.pump()
    finally:
        s = c.stop()
    return s


def argument_parser() -> Any:
    ap = cc.argument_parser("ctlreplay.py", __doc__)
    ap.add_argument("--export", required=True, help="the 2.7 export (JSON Lines) to replay")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        read_export(args.export)
        cfg, contract, run_dir = cc.prepare(args)
    except (cc.ClientError, ReplayError, OSError) as err:
        msg = str(err)
        print("ctlreplay: %s" % (msg if msg.startswith("refused") else "refused: " + msg), file=sys.stderr, flush=True)
        return 2
    try:
        s = replay(args.export, cfg, contract, reply_log=run_dir / cc.REPLY_LOG)
    except KeyboardInterrupt:
        print("ctlreplay: interrupted", file=sys.stderr, flush=True)
        return 1
    print(cc.summary_line("ctlreplay", s), file=sys.stderr, flush=True)
    return cc.exit_code(s)


if __name__ == "__main__":
    sys.exit(main())
