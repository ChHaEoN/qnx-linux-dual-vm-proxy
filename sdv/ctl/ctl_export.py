#!/usr/bin/env python3
"""ctl_export.py -- a recorded drive's bag to the ROS-free export ctlreplay.py reads (sdv/ctl). rosbag2_py, in the
Jazzy container.

The Phase 8 specification (the project's local design notes, sections 2.7 and 4 item
6; not in this tree) defines the export: JSON Lines, one compact object per message in the bag's receive order,

    {"topic": str, "recv_ns": int, "stamp_ns": int|null, "fields": {...}}

for the six topics of TOPICS (any other topic in the bag is skipped), then one last line

    {"summary": {"messages": {topic: n}, "bag_sha256": {file: hex}, "export_format": 1}}

recv_ns is the bag's receive time, stamp_ns the message's own stamp (its header's, or its stamp field) in ns; a
non-finite float is written as null (ctlreplay.py packs it back as a quiet NaN), so every line is strict JSON. The
gear's report_name is resolved from the message class's own constants (GearReport's named values); a value no
constant has is written UNKNOWN_<n>, which every reader refuses as a gear.

    ctl_export.py --bag DIR --out FILE.jsonl

Refused before rosbag2_py is even imported, with exit 2: an output that exists (an export is never overwritten), and
an output or a bag inside the repo or any other git work tree (a recording and its export stay out of every tree).
Refused before the output is opened: a topic of TOPICS recorded with another message type than the one named there.
The conversion from message to record is pure functions (tested without ROS); only main touches rosbag2_py,
rclpy.serialization and rosidl_runtime_py, inside main. An export that fails part way is removed, not left half
written.

Does not demonstrate: that the bag holds what the run did (rosbag2 records what reached it), or anything about the
messages' meaning beyond their field names; the message types are those the specification names (WP4a reads them on
the deployed release).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ctlclient as cc  # noqa: E402

EXPORT_FORMAT = 1
CONTROL_TOPIC = "/control/command/control_cmd"
ODOM_TOPIC = "/localization/kinematic_state"
VELOCITY_TOPIC = "/vehicle/status/velocity_status"
STEERING_TOPIC = "/vehicle/status/steering_status"
GEAR_TOPIC = "/vehicle/status/gear_status"
ACCEL_TOPIC = "/localization/acceleration"
# The six topics in 2.7's order, each with the message type the specification names.
TOPICS: Dict[str, str] = {
    CONTROL_TOPIC: "autoware_control_msgs/msg/Control",
    ODOM_TOPIC: "nav_msgs/msg/Odometry",
    VELOCITY_TOPIC: "autoware_vehicle_msgs/msg/VelocityReport",
    STEERING_TOPIC: "autoware_vehicle_msgs/msg/SteeringReport",
    GEAR_TOPIC: "autoware_vehicle_msgs/msg/GearReport",
    ACCEL_TOPIC: "geometry_msgs/msg/AccelWithCovarianceStamped",
}


class ExportError(RuntimeError):
    """A refusal: nothing is written."""


# --- pure conversions --------------------------------------------------------------------------------------------------

def stamp_to_ns(t: Any) -> int:
    return int(t.sec) * 1_000_000_000 + int(t.nanosec)


def stamp_ns_of(msg: Any) -> Optional[int]:
    """The message's own stamp in ns: its header's when it has a header, else its stamp field, else None."""
    if hasattr(msg, "header"):
        return stamp_to_ns(msg.header.stamp)
    if hasattr(msg, "stamp"):
        return stamp_to_ns(msg.stamp)
    return None


def num(x: Any) -> Optional[float]:
    """A float field as a JSON number, or None when it is not finite."""
    f = float(x)
    return f if math.isfinite(f) else None


def gear_names(cls: Any) -> Dict[int, str]:
    """GearReport's named constants, value to name (upper-case names with int values; the first name in sorted order
    when two share a value)."""
    out: Dict[int, str] = {}
    for name in sorted(dir(cls)):
        if name.startswith("_") or not name.isupper():
            continue
        v = getattr(cls, name, None)
        if isinstance(v, int) and not isinstance(v, bool):
            out.setdefault(v, name)
    return out


def control_fields(msg: Any) -> Dict[str, Any]:
    lat, lon = msg.lateral, msg.longitudinal
    return {"velocity": num(lon.velocity), "acceleration": num(lon.acceleration), "jerk": num(lon.jerk),
            "is_defined_acceleration": bool(lon.is_defined_acceleration), "is_defined_jerk": bool(lon.is_defined_jerk),
            "steering_tire_angle": num(lat.steering_tire_angle), "steering_tire_rotation_rate": num(lat.steering_tire_rotation_rate),
            "is_defined_steering_tire_rotation_rate": bool(lat.is_defined_steering_tire_rotation_rate)}


def odometry_fields(msg: Any) -> Dict[str, Any]:
    return {"v": num(msg.twist.twist.linear.x)}


def velocity_fields(msg: Any) -> Dict[str, Any]:
    return {"longitudinal_velocity": num(msg.longitudinal_velocity), "heading_rate": num(msg.heading_rate)}


def steering_fields(msg: Any) -> Dict[str, Any]:
    return {"steering_tire_angle": num(msg.steering_tire_angle)}


def acceleration_fields(msg: Any) -> Dict[str, Any]:
    return {"ax": num(msg.accel.accel.linear.x)}


def gear_fields(msg: Any, gear: Optional[Dict[int, str]]) -> Dict[str, Any]:
    report = int(msg.report)
    return {"report": report, "report_name": (gear or {}).get(report, "UNKNOWN_%d" % report)}


CONVERTERS: Dict[str, Callable[[Any], Dict[str, Any]]] = {
    CONTROL_TOPIC: control_fields, ODOM_TOPIC: odometry_fields, VELOCITY_TOPIC: velocity_fields,
    STEERING_TOPIC: steering_fields, ACCEL_TOPIC: acceleration_fields,
}


def to_record(topic: str, recv_ns: int, msg: Any, gear: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """One message as its 2.7 record."""
    fields = gear_fields(msg, gear) if topic == GEAR_TOPIC else CONVERTERS[topic](msg)
    return {"topic": topic, "recv_ns": int(recv_ns), "stamp_ns": stamp_ns_of(msg), "fields": fields}


def dumps(obj: Any) -> str:
    """One compact, strict JSON line (no NaN, no Infinity), ASCII."""
    return json.dumps(obj, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


# --- paths -----------------------------------------------------------------------------------------------------------

def check_paths(bag: str, out: str) -> Tuple[Path, Path]:
    """(bag, out) as absolute paths, or ExportError: the bag a directory, neither inside the repo or a work tree (a path
    reached through a symbolic link is judged by where the link leads), the output not existing."""
    b = Path(bag).expanduser().absolute()
    o = Path(out).expanduser().absolute()
    for p, what in ((b, "bag"), (o, "output")):
        wt = cc.work_tree_of(p)
        if wt is not None:
            raise ExportError("refused: the %s %s is inside the work tree %s" % (what, p, wt))
    if o.exists() or o.is_symlink():
        raise ExportError("refused: %s exists (an export is never overwritten)" % o)
    if not b.is_dir():
        raise ExportError("refused: the bag %s is not a directory" % b)
    return b, o


def bag_sha256(bag: Path) -> Dict[str, str]:
    """Every file of the bag directory, by its path relative to it, with its sha256."""
    out: Dict[str, str] = {}
    for p in sorted(x for x in bag.rglob("*") if x.is_file()):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        out[p.relative_to(bag).as_posix()] = h.hexdigest()
    return out


# --- main ------------------------------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ctl_export.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bag", required=True, help="the rosbag2 directory")
    ap.add_argument("--out", required=True, help="the export to write (JSON Lines; must not exist)")
    args = ap.parse_args(argv)
    try:
        bag, out = check_paths(args.bag, args.out)
    except ExportError as err:
        print("ctl_export: %s" % err, file=sys.stderr, flush=True)
        return 2
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id=""), rosbag2_py.ConverterOptions("", ""))
    recorded = {t.name: t.type for t in reader.get_all_topics_and_types()}
    wrong = ["%s is %s, not %s" % (t, recorded[t], ty) for t, ty in TOPICS.items() if t in recorded and recorded[t] != ty]
    if wrong:
        print("ctl_export: refused: a topic of another message type: %s" % "; ".join(wrong), file=sys.stderr, flush=True)
        return 2
    present = [t for t in TOPICS if t in recorded]
    reader.set_filter(rosbag2_py.StorageFilter(topics=present))
    classes = {t: get_message(TOPICS[t]) for t in present}
    gear = gear_names(classes[GEAR_TOPIC]) if GEAR_TOPIC in classes else None
    counts = {t: 0 for t in TOPICS}
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        f = open(out, "x", encoding="utf-8", newline="\n")
    except FileExistsError:
        print("ctl_export: refused: %s exists (an export is never overwritten)" % out, file=sys.stderr, flush=True)
        return 2
    try:
        with f:
            while reader.has_next():
                topic, data, recv_ns = reader.read_next()
                if topic not in classes:
                    continue
                msg = deserialize_message(data, classes[topic])
                f.write(dumps(to_record(topic, recv_ns, msg, gear)) + "\n")
                counts[topic] += 1
            f.write(dumps({"summary": {"messages": counts, "bag_sha256": bag_sha256(bag), "export_format": EXPORT_FORMAT}}) + "\n")
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    print("ctl_export: %d messages from %s" % (sum(counts.values()), bag), file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
