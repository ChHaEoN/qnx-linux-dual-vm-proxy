"""update.py -- the ROS->VSS feeder's update: one plain record per received message, built from the message's fields
and checked, and the claim node's verdict message parsed and checked (sdv/rosvss; Phase 8 WP3a).

Local branch only (decision 15). Standard library only: no ROS. The feeder's subscription callbacks
(feeder_node.py) build an update from each message with the from_* functions here, which read the message's
attributes and nothing else, so the stand-in message classes of the tests drive them as rclpy's would. The mapping
(mapping.py) takes nothing but a checked update: it is the one interface the tests drive.

THE UPDATE (Phase 8 spec 2.8; the topics and fields of the export, spec 2.7, for four of them)
    {"topic": str, "recv_ns": int, "stamp_ns": int|null, "fields": {...}}
  /vehicle/status/velocity_status  longitudinal_velocity [m/s], heading_rate [rad/s]       (header.stamp)
  /vehicle/status/steering_status  steering_tire_angle [rad]                               (stamp)
  /vehicle/status/gear_status      report (u8), report_name (str: the message class's own constant name for report)
                                                                                           (stamp)
  /localization/acceleration       ax [m/s^2] (accel.accel.linear.x)                       (header.stamp)
  /qnx_monitor/verdict             the parsed spec 2.6 object, its keys in 2.6's order     (std_msgs/String: no stamp,
                                                                                            stamp_ns null)
  recv_ns is the feeder's receive time (CLOCK_REALTIME ns, as a bag's receive time), stamp_ns the message's own
  stamp in ns. A float field is a finite int or float (never a bool), as the export's JSON can carry it.

REFUSALS (Refused, with a code; the writer counts them by code and never writes the update)
  record      not a dict, or its keys are not exactly topic, recv_ns, stamp_ns, fields
  topic       any topic but the five above (the claim topic /control/command/control_cmd above all)
  recv_ns, stamp_ns  not a non-negative int (stamp_ns may be null)
  fields      not a dict, or its keys are not exactly the topic's
  type        a field of another type
  not-finite  a float field that is NaN or infinite, or an int beyond the double range
  range       an integer outside its type (report: u8)
  verdict-size   a verdict text over VERDICT_MAX_BYTES = 1024 bytes (spec 2.6: at most 1024)
  verdict-json   not text, not ASCII, not compact (any whitespace: 2.6's separators leave none, and the object
                 holds no string), not JSON, a duplicate key, NaN or Infinity, or not an object
  verdict-keys   the keys not exactly 2.6's, in 2.6's order
  verdict-value  a value outside 2.6: v not 1; seq outside u64 or the sentinel (frame.h's FRAME_SENTINEL_SEQ,
                 UINT64_MAX, which the node never sends); profile outside u8; a command float that is not null or
                 a finite binary32 value (2.6: the binary32 value packed, so it round-trips through binary32
                 exactly); interval_ms outside u16; verdict not null, 0 or 1; reason not null or u8; one of the
                 two null without the other; reason not 0 exactly when the verdict is 0 (ACCEPT); a connection
                 change (seq 0) carrying a reply; a counter outside u32 (the overlay's uint32 leaves);
                 connected not a bool
  The accounting identities (packed = replied + dropped + lost_on_reconnect) are not checked: a connection change
  sent while a frame is in flight has that frame packed and not yet answered, and the feeder copies, it does not
  judge. The command fields of a connection change are checked for their types only (2.6 gives them no frame).

DOES NOT DEMONSTRATE: anything about rclpy's message classes beyond the attributes read here (WP4a reads the
definitions at Autoware 1.9.0); that a message's stamp is on any particular clock.
"""
from __future__ import annotations

import json
import math
import re
import struct
from typing import Any, Dict, List, Mapping, Optional, Tuple

VELOCITY = "/vehicle/status/velocity_status"
STEERING = "/vehicle/status/steering_status"
GEAR = "/vehicle/status/gear_status"
ACCEL = "/localization/acceleration"
VERDICT = "/qnx_monitor/verdict"
VEHICLE_TOPICS = (VELOCITY, STEERING, GEAR, ACCEL)
TOPICS = VEHICLE_TOPICS + (VERDICT,)

RECORD_KEYS = ("topic", "recv_ns", "stamp_ns", "fields")
FIELDS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    VELOCITY: (("longitudinal_velocity", "float"), ("heading_rate", "float")),
    STEERING: (("steering_tire_angle", "float"),),
    GEAR: (("report", "u8"), ("report_name", "str")),
    ACCEL: (("ax", "float"),),
}

VERDICT_FORMAT = 1
VERDICT_MAX_BYTES = 1024
VERDICT_KEYS = ("v", "seq", "profile", "v_cmd", "acc", "jerk", "steer", "steer_rate", "interval_ms", "verdict", "reason",
                "packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects", "connected")
VERDICT_FLOATS = ("v_cmd", "acc", "jerk", "steer", "steer_rate")
VERDICT_COUNTERS = ("packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects")
SENTINEL_SEQ = 2 ** 64 - 1
U8_MAX, U16_MAX, U32_MAX, U64_MAX = 0xFF, 0xFFFF, 0xFFFFFFFF, 2 ** 64 - 1

UNKNOWN_GEAR = "UNKNOWN_%d"
_CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Refused(ValueError):
    """An update or a verdict message the feeder does not take. `code` names the refusal for the counts; the message
    names keys and topics only, never a value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(x)
    except OverflowError:                       # an int beyond the double range
        return False


def _check_float(x: Any, what: str) -> float:
    if not _is_number(x):
        raise Refused("type", "%s is not a number" % what)
    if not _finite(x):
        raise Refused("not-finite", "%s is not finite" % what)
    return x


def check(update: Any) -> Dict[str, Any]:
    """The update, checked (a Refused otherwise); returned as given."""
    if not isinstance(update, dict) or set(update) != set(RECORD_KEYS):
        raise Refused("record", "an update is a dict with exactly the keys %s" % ", ".join(RECORD_KEYS))
    topic = update["topic"]
    if not isinstance(topic, str) or topic not in TOPICS:
        raise Refused("topic", "not a topic the feeder takes")
    if not _is_int(update["recv_ns"]) or update["recv_ns"] < 0:
        raise Refused("recv_ns", "recv_ns is not a non-negative int")
    stamp = update["stamp_ns"]
    if stamp is not None and (not _is_int(stamp) or stamp < 0):
        raise Refused("stamp_ns", "stamp_ns is not null or a non-negative int")
    fields = update["fields"]
    if not isinstance(fields, dict):
        raise Refused("fields", "fields is not a dict")
    if topic == VERDICT:
        check_verdict(fields)
        return update
    spec = FIELDS[topic]
    if set(fields) != {k for k, _t in spec}:
        raise Refused("fields", "the fields of %s are exactly %s" % (topic, ", ".join(k for k, _t in spec)))
    for key, kind in spec:
        value = fields[key]
        if kind == "float":
            _check_float(value, key)
        elif kind == "u8":
            if not _is_int(value):
                raise Refused("type", "%s is not an int" % key)
            if not 0 <= value <= U8_MAX:
                raise Refused("range", "%s is outside u8" % key)
        elif not isinstance(value, str):
            raise Refused("type", "%s is not text" % key)
    return update


# --- the verdict message (spec 2.6) -------------------------------------------------------------------------------

def _pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise Refused("verdict-json", "a duplicate key")
        out[key] = value
    return out


def _no_constant(name: str) -> Any:
    raise Refused("verdict-json", "NaN or Infinity is not 2.6")


def parse_verdict(data: Any) -> Dict[str, Any]:
    """The 2.6 object of a verdict message's `data`, checked (a Refused otherwise)."""
    if not isinstance(data, str):
        raise Refused("verdict-json", "the verdict is not text")
    if len(data.encode("utf-8", "surrogatepass")) > VERDICT_MAX_BYTES:
        raise Refused("verdict-size", "the verdict is over %d bytes" % VERDICT_MAX_BYTES)
    if not data.isascii():
        raise Refused("verdict-json", "the verdict is not ASCII")
    if any(c in data for c in " \t\r\n"):
        raise Refused("verdict-json", "the verdict is not compact")
    try:
        obj = json.loads(data, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except ValueError as err:
        if isinstance(err, Refused):
            raise
        raise Refused("verdict-json", "the verdict is not JSON") from None
    if not isinstance(obj, dict):
        raise Refused("verdict-json", "the verdict is not an object")
    return check_verdict(obj)


def _binary32(x: Any, key: str) -> None:
    if not _is_number(x) or not _finite(x):
        raise Refused("verdict-value", "%s is not null or a finite number" % key)
    try:
        same = struct.unpack("<f", struct.pack("<f", x))[0] == x
    except (OverflowError, struct.error):
        same = False
    if not same:
        raise Refused("verdict-value", "%s is not a binary32 value" % key)


def _int_in(obj: Mapping[str, Any], key: str, lo: int, hi: int) -> int:
    x = obj[key]
    if not _is_int(x) or not lo <= x <= hi:
        raise Refused("verdict-value", "%s is not an int in [%d, %d]" % (key, lo, hi))
    return x


def check_verdict(obj: Any) -> Dict[str, Any]:
    """A parsed 2.6 object, checked (a Refused otherwise); returned as given."""
    if not isinstance(obj, dict):
        raise Refused("verdict-json", "the verdict is not an object")
    if tuple(obj) != VERDICT_KEYS:
        raise Refused("verdict-keys", "the keys are not exactly 2.6's, in its order")
    if not _is_int(obj["v"]) or obj["v"] != VERDICT_FORMAT:
        raise Refused("verdict-value", "v is not %d" % VERDICT_FORMAT)
    seq = _int_in(obj, "seq", 0, U64_MAX)
    if seq == SENTINEL_SEQ:
        raise Refused("verdict-value", "seq is the sentinel")
    _int_in(obj, "profile", 0, U8_MAX)
    for key in VERDICT_FLOATS:
        if obj[key] is not None:
            _binary32(obj[key], key)
    _int_in(obj, "interval_ms", 0, U16_MAX)
    verdict, reason = obj["verdict"], obj["reason"]
    if (verdict is None) != (reason is None):
        raise Refused("verdict-value", "verdict and reason are null together or not at all")
    if verdict is not None:
        if not _is_int(verdict) or verdict not in (0, 1):
            raise Refused("verdict-value", "verdict is not null, 0 or 1")
        _int_in(obj, "reason", 0, U8_MAX)
        if (reason == 0) != (verdict == 0):
            raise Refused("verdict-value", "reason is not 0 exactly when the verdict is 0")
        if seq == 0:
            raise Refused("verdict-value", "a connection change (seq 0) carries no reply")
    for key in VERDICT_COUNTERS:
        _int_in(obj, key, 0, U32_MAX)
    if not isinstance(obj["connected"], bool):
        raise Refused("verdict-value", "connected is not a bool")
    return obj


# --- messages to updates (the subscription callbacks' builders) ----------------------------------------------------

def stamp_ns(t: Any) -> int:
    """A builtin_interfaces/Time (sec, nanosec) in ns."""
    return int(t.sec) * 1_000_000_000 + int(t.nanosec)


def constant_names(cls: Any) -> Dict[int, str]:
    """{value: name} of a message class's own named int constants (all-capital names). rosidl_generator_py serves them
    as properties of the class's metaclass and puts them in the class namespace too, so both are read. Two names for
    one value are refused (ValueError): a report would have no single name."""
    names = sorted({n for n in dir(cls) if _CONSTANT_NAME.match(n)} | {n for n in dir(type(cls)) if _CONSTANT_NAME.match(n)})
    out: Dict[int, str] = {}
    for name in names:
        value = getattr(cls, name, None)
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        if value in out:
            raise ValueError("%s has two constants for one value: %s and %s" % (getattr(cls, "__name__", cls), out[value], name))
        out[value] = name
    return out


def build(topic: str, recv_ns: int, stamp: Optional[int], fields: Dict[str, Any]) -> Dict[str, Any]:
    return check({"topic": topic, "recv_ns": recv_ns, "stamp_ns": stamp, "fields": fields})


def from_velocity(msg: Any, recv_ns: int) -> Dict[str, Any]:
    """autoware_vehicle_msgs/msg/VelocityReport."""
    return build(VELOCITY, recv_ns, stamp_ns(msg.header.stamp),
                 {"longitudinal_velocity": float(msg.longitudinal_velocity), "heading_rate": float(msg.heading_rate)})


def from_steering(msg: Any, recv_ns: int) -> Dict[str, Any]:
    """autoware_vehicle_msgs/msg/SteeringReport."""
    return build(STEERING, recv_ns, stamp_ns(msg.stamp), {"steering_tire_angle": float(msg.steering_tire_angle)})


def from_gear(msg: Any, recv_ns: int, names: Mapping[int, str]) -> Dict[str, Any]:
    """autoware_vehicle_msgs/msg/GearReport; names: constant_names(GearReport). A report with no constant gets the name
    UNKNOWN_<n>, which the mapping refuses."""
    report = int(msg.report)
    return build(GEAR, recv_ns, stamp_ns(msg.stamp), {"report": report, "report_name": names.get(report, UNKNOWN_GEAR % report)})


def from_accel(msg: Any, recv_ns: int) -> Dict[str, Any]:
    """geometry_msgs/msg/AccelWithCovarianceStamped."""
    return build(ACCEL, recv_ns, stamp_ns(msg.header.stamp), {"ax": float(msg.accel.accel.linear.x)})


def from_verdict(msg: Any, recv_ns: int) -> Dict[str, Any]:
    """std_msgs/msg/String on /qnx_monitor/verdict (no stamp)."""
    return build(VERDICT, recv_ns, None, parse_verdict(msg.data))
