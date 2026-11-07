"""mapping.py -- the ROS->VSS feeder's write sets and its mapping from an update to VSS values (sdv/rosvss; Phase 8
WP3a). Pure functions, standard library only.

Local branch only (decision 15). The feeder writes under the attribution writer name WRITER (sdv/stack/attribution.py
lets only it write under Monitor.CtlClaim). One writer per signal (plan 3.2): what the feeder may write depends on the
run type, and nothing outside its run type's write set is ever written (vsswriter.py filters and counts).

WRITE SETS (spec 2.8)
  planning-sim    the five kind 4 slots (attribution.SLOT_PATHS) and Vehicle.Speed, every ControlCommand leaf (ten,
                  sdv/vss/overlay-ctl.vspec) and every Monitor.CtlClaim leaf (eleven, sdv/vss/overlay.vspec)
  carla-autoware  the same overlay and no standard signal: the CAN path writes those in that run type (plan:213)
  Never written in any run type: Vehicle.Body.Lights.Hazard.IsSignaling (the mock provider's), Vehicle.DualVm.AppState.*
  (the app's), Vehicle.DualVm.Monitor.VssClaim.* (the kind 4 bridge's), Vehicle.Chassis.Wheelbase (the catalogue's).
  write_set() refuses a set holding one of them (never_written), so an edit of WRITE_SETS cannot slip one in.

MAPPING (spec 2.8; units are the catalogue's: Motion.LongitudinalVelocity m/s, Vehicle.Speed km/h, AngularVelocity.Yaw
degrees/s, Chassis.Axle.Row1.SteeringAngle degrees, Acceleration.Longitudinal m/s^2, CurrentGear none)
  velocity_status  longitudinal_velocity -> Motion.LongitudinalVelocity, as it is (signed, m/s)
                                         -> Vehicle.Speed = abs(v) * 3.6 (km/h, the magnitude; attribution's m/s to
                                            km/h factor and the CAN path's transform "abs(x) * 3.6")
                   heading_rate          -> AngularVelocity.Yaw, rad/s to deg/s (math.degrees), no sign change:
                                            positive = yawing left in both the overlay and Autoware (INFERRED, as the
                                            spec says; a test pins it)
  steering_status  steering_tire_angle   -> Chassis.Axle.Row1.SteeringAngle, rad to degrees, positive left in both
  acceleration     ax                    -> Acceleration.Longitudinal, as it is (m/s^2)
  gear_status      report_name           -> CurrentGear: a name beginning DRIVE or LOW -> 1, beginning REVERSE -> -1,
                                            NEUTRAL, PARK or NONE -> 0 (CurrentGear has no park value: the overlay's
                                            comment), anything else refused (code gear)
  verdict          a frame's message (seq > 0): the command leaves (Velocity, Acceleration with IsAccelerationDefined,
                   Jerk with IsJerkDefined, SteeringTireAngle, SteeringTireRotationRate with
                   IsSteeringTireRotationRateDefined, ProfileId, StampInterval) and, when the frame was replied
                   (verdict not null), CtlClaim.Verdict, Reason and LastSeq; every message: CtlClaim.Packed, Replied,
                   Accepted, Rejected, Dropped, LostOnReconnect, Reconnects and IsConnected. A null value is not
                   written; its Is...Defined leaf is written false. A connection change (seq 0) writes only
                   IsConnected, Reconnects and the counters.
  LastSeq only with a reply: the spec maps it from every frame's seq, but the overlay (the code, which holds) defines
  it as the "sequence number of the last reply received", so a dropped or lost frame leaves it, with Verdict and
  Reason, at the last reply's.

DOES NOT DEMONSTRATE: that Autoware's heading_rate is positive to the left (INFERRED); that the databroker serves these
paths with these datatypes (vsswriter.start_problems checks a running one at start); any timing.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import update as upd  # noqa: E402

WRITER = "ros-vss-feeder"
PLANNING_SIM = "planning-sim"
CARLA_AUTOWARE = "carla-autoware"
RUN_TYPES = (PLANNING_SIM, CARLA_AUTOWARE)

LONG_VEL = "Vehicle.DualVm.Motion.LongitudinalVelocity"
ACCEL_LONG = "Vehicle.Acceleration.Longitudinal"
STEER_ANGLE = "Vehicle.Chassis.Axle.Row1.SteeringAngle"
YAW = "Vehicle.AngularVelocity.Yaw"
CURRENT_GEAR = "Vehicle.Powertrain.Transmission.CurrentGear"
SPEED = "Vehicle.Speed"
SLOT_PATHS = (LONG_VEL, ACCEL_LONG, STEER_ANGLE, YAW, CURRENT_GEAR)      # attribution.SLOT_PATHS, slot order
STANDARD = SLOT_PATHS + (SPEED,)

CC = "Vehicle.DualVm.ControlCommand."
CTL = "Vehicle.DualVm.Monitor.CtlClaim."
CONTROL_COMMAND = tuple(CC + leaf for leaf in (
    "Velocity", "Acceleration", "IsAccelerationDefined", "Jerk", "IsJerkDefined", "SteeringTireAngle",
    "SteeringTireRotationRate", "IsSteeringTireRotationRateDefined", "ProfileId", "StampInterval"))
CTL_CLAIM = tuple(CTL + leaf for leaf in (
    "Verdict", "Reason", "LastSeq", "Packed", "Replied", "Accepted", "Rejected", "Dropped", "LostOnReconnect",
    "Reconnects", "IsConnected"))
OVERLAY = CONTROL_COMMAND + CTL_CLAIM

WRITE_SETS: Dict[str, FrozenSet[str]] = {
    PLANNING_SIM: frozenset(STANDARD + OVERLAY),
    CARLA_AUTOWARE: frozenset(OVERLAY),
}
NEVER_WRITTEN = ("Vehicle.Body.Lights.Hazard.IsSignaling", "Vehicle.Chassis.Wheelbase")
NEVER_PREFIXES = ("Vehicle.DualVm.AppState.", "Vehicle.DualVm.Monitor.VssClaim.")

# The datatype of every path of the write sets (VSS 6.0's for the standard ones, the overlay files' for the rest),
# which the writer sends with each value and the start check compares with what the databroker serves.
DATATYPES: Dict[str, str] = {
    LONG_VEL: "float", ACCEL_LONG: "float", STEER_ANGLE: "float", YAW: "float", CURRENT_GEAR: "int8", SPEED: "float",
    CC + "Velocity": "float", CC + "Acceleration": "float", CC + "IsAccelerationDefined": "boolean", CC + "Jerk": "float",
    CC + "IsJerkDefined": "boolean", CC + "SteeringTireAngle": "float", CC + "SteeringTireRotationRate": "float",
    CC + "IsSteeringTireRotationRateDefined": "boolean", CC + "ProfileId": "uint8", CC + "StampInterval": "uint16",
    CTL + "Verdict": "uint8", CTL + "Reason": "uint8", CTL + "LastSeq": "uint64", CTL + "Packed": "uint32",
    CTL + "Replied": "uint32", CTL + "Accepted": "uint32", CTL + "Rejected": "uint32", CTL + "Dropped": "uint32",
    CTL + "LostOnReconnect": "uint32", CTL + "Reconnects": "uint32", CTL + "IsConnected": "boolean",
}
# The unit each standard value is converted to (the generated catalogue's; a test compares).
UNITS: Dict[str, Any] = {LONG_VEL: "m/s", SPEED: "km/h", YAW: "degrees/s", STEER_ANGLE: "degrees", ACCEL_LONG: "m/s^2",
                         CURRENT_GEAR: None}
KMH_PER_MS = 3.6

COUNTER_LEAVES = (("Packed", "packed"), ("Replied", "replied"), ("Accepted", "accepted"), ("Rejected", "rejected"),
                  ("Dropped", "dropped"), ("LostOnReconnect", "lost_on_reconnect"), ("Reconnects", "reconnects"))
# (value leaf, its Is...Defined leaf or None, the 2.6 key)
COMMAND_FLOATS = (("Velocity", None, "v_cmd"), ("Acceleration", "IsAccelerationDefined", "acc"), ("Jerk", "IsJerkDefined", "jerk"),
                  ("SteeringTireAngle", None, "steer"),
                  ("SteeringTireRotationRate", "IsSteeringTireRotationRateDefined", "steer_rate"))

Item = Tuple[str, Any]


def never_written(path: str) -> bool:
    """Whether path is one spec 2.8 keeps every run type from writing (NEVER_WRITTEN and NEVER_PREFIXES)."""
    return path in NEVER_WRITTEN or path.startswith(NEVER_PREFIXES)


def write_set(run_type: str) -> FrozenSet[str]:
    """The run type's write set. A ValueError for an unknown run type, and for a write set that holds a path no run
    type may write: a guard against an edit of WRITE_SETS, checked on every call, so the writer, the start check and
    the subscriptions all refuse such a set."""
    if run_type not in WRITE_SETS:
        raise ValueError("run type %r is not one of %s" % (run_type, ", ".join(RUN_TYPES)))
    paths = WRITE_SETS[run_type]
    forbidden = sorted(p for p in paths if never_written(p))
    if forbidden:
        raise ValueError("the write set of %s holds %s, which no run type writes (spec 2.8)" % (run_type, ", ".join(forbidden)))
    return paths


def speed_kmh(v: float) -> float:
    return abs(v) * KMH_PER_MS


def gear_value(name: str) -> int:
    """CurrentGear of a GearReport constant's name (a Refused for any other)."""
    if name.startswith(("DRIVE", "LOW")):
        return 1
    if name.startswith("REVERSE"):
        return -1
    if name in ("NEUTRAL", "PARK", "NONE"):
        return 0
    raise upd.Refused("gear", "not a gear name the mapping knows")


def verdict_items(f: Dict[str, Any]) -> List[Item]:
    items: List[Item] = []
    if f["seq"] != 0:
        if f["verdict"] is not None:
            items += [(CTL + "Verdict", int(f["verdict"])), (CTL + "Reason", int(f["reason"])), (CTL + "LastSeq", int(f["seq"]))]
        for leaf, defined, key in COMMAND_FLOATS:
            value = f[key]
            if value is not None:
                items.append((CC + leaf, float(value)))
            if defined is not None:
                items.append((CC + defined, value is not None))
        items += [(CC + "ProfileId", int(f["profile"])), (CC + "StampInterval", int(f["interval_ms"]))]
    items += [(CTL + leaf, int(f[key])) for leaf, key in COUNTER_LEAVES]
    items.append((CTL + "IsConnected", bool(f["connected"])))
    return items


def map_update(update: Dict[str, Any]) -> List[Item]:
    """[(path, value)] of a checked update; a gear name it does not know is a Refused."""
    topic, f = update["topic"], update["fields"]
    if topic == upd.VELOCITY:
        v = float(f["longitudinal_velocity"])
        return [(LONG_VEL, v), (SPEED, speed_kmh(v)), (YAW, math.degrees(float(f["heading_rate"])))]
    if topic == upd.STEERING:
        return [(STEER_ANGLE, math.degrees(float(f["steering_tire_angle"])))]
    if topic == upd.ACCEL:
        return [(ACCEL_LONG, float(f["ax"]))]
    if topic == upd.GEAR:
        return [(CURRENT_GEAR, gear_value(f["report_name"]))]
    if topic == upd.VERDICT:
        return verdict_items(f)
    raise upd.Refused("topic", "not a topic the feeder takes")
