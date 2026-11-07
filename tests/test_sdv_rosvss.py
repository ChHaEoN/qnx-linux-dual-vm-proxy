"""The ROS->VSS feeder (sdv/rosvss: update.py, mapping.py, vsswriter.py, feeder_node.py, kuksa_out.py): SDV Phase 8
WP3a.

What is tested, and how (spec sections 2.8 and 5). ROS, rclpy, the message packages, kuksa-client and the databroker
are stand-ins in every test: nothing here needs ROS installed, a container or any network.

- update.py: an update of each topic is taken; an unknown topic, record key, field key or type, a non-finite float, an
  integer out of its range, a verdict message over 1024 bytes (exactly 1024 taken) and one that is not a valid 2.6 object
  (its key set or order, its types and ranges, a float that is not a binary32 value, the verdict and reason pairing, a
  reply on a connection change, non-ASCII, whitespace, a duplicate key, NaN or Infinity) are refused. Messages become
  updates with their own stamps (header.stamp or stamp) through stand-in message classes, and the gear's name comes
  from the message class's own constants, read on rosidl_generator_py's pattern (metaclass properties and the class
  namespace) and on a plain class.
- mapping.py: the two run types' write sets are spec 2.8's, word for word, and no run type writes the hazard light,
  AppState, Monitor.VssClaim or the wheelbase; each mapping, its unit conversion and its sign (heading rate in deg/s
  positive left, INFERRED as the spec says and pinned here; the steering angle in degrees; Vehicle.Speed the magnitude
  in km/h); every gear name of GearReport and the refusal of any other; a null value never written and its Is...Defined
  leaf false; a connection change writes only IsConnected, Reconnects and the counters; LastSeq, Verdict and Reason only
  from a replied frame (the overlay's "last reply received", read from the file); write_set refuses a set that holds a
  path no run type writes. The write sets' leaves and datatypes equal overlay.vspec's
  and overlay-ctl.vspec's, the standard paths' datatypes and units the generated catalogue's (sdv-out/gen; skipped
  without it, failed under SDV_REQUIRE_GEN=1), and sdv/stack/attribution.py (read, never changed) takes WRITER as the
  one writer under Monitor.CtlClaim and has the same five slot paths and the same m/s to km/h factor.
- vsswriter.py: writes inside the run type's set only (anything outside counted and logged once by path), a standard
  signal never in carla-autoware, the counts (updates, refused by code, written per path, dropped), a failing databroker
  counted and gone on from, an update the check or the mapping raises on with no refusal counted as `error` (the type
  name logged, the writer going on), the start check (a write-set path not served, or served with another datatype,
  refuses), and no value of any signal in its log: with a databroker that blocks, the callbacks return at once, the
  queue holds QUEUE_MAX, drops the oldest and counts them, and the newest is written; a dropped update's values stay
  out until a later update writes the same paths, and QUEUE_MAX's reason claims no more.
- feeder_node.py: the databroker only on a loopback address literal; main refuses another before importing rclpy; with
  stand-ins for rclpy, the message packages and kuksa-client in sys.modules, main subscribes to spec 2.8's topics with
  their QoS (never /control/command/control_cmd) and writes what they carry through kuksa_out; when the writer's thread
  ends (its log's stream failing), spin ends and main exits 1, naming the type on stderr with no traceback; the last
  counts line comes also when rclpy does not start.
- kuksa_out.py: kuksa-client's VSSClient set with try_v2=True and the datatypes given; no other module of the package
  imports kuksa-client, rclpy or a message package, and those imports are inside functions only (the package imports
  with all of them blocked).

What this does NOT show: that the feeder runs in Jazzy's container with the real rclpy, message packages and
kuksa-client 0.6.0 (WP3b builds the image, WP4b runs it); the real QoS of Autoware's publishers or GearReport's values
at 1.9.0 (WP4a reads them); that VSS makes the monitor more independent; any timing.
"""
import ast
import enum
import importlib
import importlib.util
import io
import json
import math
import os
import struct
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROSVSS = REPO / "sdv" / "rosvss"
FIX = HERE / "fixtures" / "rosvss"
GEN = REPO / "sdv-out" / "gen"
ATTRIBUTION = REPO / "sdv" / "stack" / "attribution.py"
OVERLAY = REPO / "sdv" / "vss" / "overlay.vspec"
OVERLAY_CTL = REPO / "sdv" / "vss" / "overlay-ctl.vspec"
MODULES = ("update", "mapping", "vsswriter", "feeder_node", "kuksa_out")

VELOCITY = "/vehicle/status/velocity_status"
STEERING = "/vehicle/status/steering_status"
GEAR = "/vehicle/status/gear_status"
ACCEL = "/localization/acceleration"
VERDICT = "/qnx_monitor/verdict"
CONTROL_CMD = "/control/command/control_cmd"

LONG_VEL = "Vehicle.DualVm.Motion.LongitudinalVelocity"
ACC_LONG = "Vehicle.Acceleration.Longitudinal"
STEER_ANGLE = "Vehicle.Chassis.Axle.Row1.SteeringAngle"
YAW = "Vehicle.AngularVelocity.Yaw"
CURRENT_GEAR = "Vehicle.Powertrain.Transmission.CurrentGear"
SPEED = "Vehicle.Speed"
CC = "Vehicle.DualVm.ControlCommand."
CTL = "Vehicle.DualVm.Monitor.CtlClaim."
# Spec 2.8's leaves, written out here (not the module's constants).
CC_LEAVES = ("Velocity", "Acceleration", "IsAccelerationDefined", "Jerk", "IsJerkDefined", "SteeringTireAngle",
             "SteeringTireRotationRate", "IsSteeringTireRotationRateDefined", "ProfileId", "StampInterval")
CTL_LEAVES = ("Verdict", "Reason", "LastSeq", "Packed", "Replied", "Accepted", "Rejected", "Dropped", "LostOnReconnect",
              "Reconnects", "IsConnected")
STANDARD = {LONG_VEL, ACC_LONG, STEER_ANGLE, YAW, CURRENT_GEAR, SPEED}
OVERLAY_PATHS = {CC + leaf for leaf in CC_LEAVES} | {CTL + leaf for leaf in CTL_LEAVES}
COUNTERS = {"Packed": "packed", "Replied": "replied", "Accepted": "accepted", "Rejected": "rejected", "Dropped": "dropped",
            "LostOnReconnect": "lost_on_reconnect", "Reconnects": "reconnects"}


def _mod(name):
    """A module of sdv/rosvss, imported by name with the package's directory on sys.path (as its modules import each
    other), no bytecode written."""
    if str(ROSVSS) not in sys.path:
        sys.path.insert(0, str(ROSVSS))
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


def _attribution():
    """sdv/stack/attribution.py, loaded read-only by path (it is another package's file, never changed here)."""
    name = "_attribution_for_rosvss_tests"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, str(ATTRIBUTION))
        mod = importlib.util.module_from_spec(spec)
        saved = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = saved
        sys.modules[name] = mod
    return sys.modules[name]


def _f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _verdicts():
    return json.loads((FIX / "verdicts.json").read_text(encoding="utf-8"))["messages"]


def _gear_constants():
    return json.loads((FIX / "gear_report.json").read_text(encoding="utf-8"))["constants"]


def _data(obj):
    return json.dumps(obj, separators=(",", ":"))


def _vupdate(obj, recv_ns=1000):
    return {"topic": VERDICT, "recv_ns": recv_ns, "stamp_ns": None, "fields": _mod("update").parse_verdict(_data(obj))}


def _vel(v=2.5, hr=0.5):
    return {"topic": VELOCITY, "recv_ns": 1000, "stamp_ns": 900, "fields": {"longitudinal_velocity": v, "heading_rate": hr}}


def _steer(a=0.125):
    return {"topic": STEERING, "recv_ns": 1000, "stamp_ns": 900, "fields": {"steering_tire_angle": a}}


def _gear(name="DRIVE", report=2):
    return {"topic": GEAR, "recv_ns": 1000, "stamp_ns": 900, "fields": {"report": report, "report_name": name}}


def _accel(ax=-1.5):
    return {"topic": ACCEL, "recv_ns": 1000, "stamp_ns": 900, "fields": {"ax": ax}}


def _vehicle_updates():
    return [_vel(), _steer(), _gear(), _accel()]


def _all_updates():
    return _vehicle_updates() + [_vupdate(obj) for obj in _verdicts().values()]


def _items(update):
    return dict(_mod("mapping").map_update(update))


class FakeSink:
    """The writer's sink as kuksa_out.KuksaOut offers it: publish(items) with (path, value, datatype) triples."""

    def __init__(self, fail=0):
        self.published = []
        self.fail = fail
        self.closed = False

    def publish(self, items):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("the databroker refused the value 777.25 at the first path")
        self.published.append(list(items))

    def paths(self):
        return [p for batch in self.published for p, _v, _t in batch]

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, t=1_000):
        self.t = t

    def __call__(self):
        return self.t


def _writer(run_type="planning-sim", sink=None, clock=None):
    log = []
    sink = sink if sink is not None else FakeSink()
    w = _mod("vsswriter").Writer(run_type, sink, log.append, clock=clock or Clock())
    return w, sink, log


# --- update.py --------------------------------------------------------------------------------------------------

def test_an_update_of_each_topic_of_2_8_is_taken():
    upd = _mod("update")
    for u in _all_updates():
        got = upd.check(u)
        assert got["topic"] == u["topic"] and got["fields"] == u["fields"], u
    assert set(upd.TOPICS) == {VELOCITY, STEERING, GEAR, ACCEL, VERDICT}
    assert CONTROL_CMD not in upd.TOPICS


def _set(u, **kw):
    u = json.loads(json.dumps(u))
    u.update(kw)
    return u


def _setf(u, **kw):
    u = json.loads(json.dumps(u))
    u["fields"].update(kw)
    return u


def _delf(u, key):
    u = json.loads(json.dumps(u))
    del u["fields"][key]
    return u


def _del(u, key):
    u = json.loads(json.dumps(u))
    del u[key]
    return u


BAD_UPDATES = [
    ("the claim topic", lambda: _set(_vel(), topic=CONTROL_CMD)),
    ("odometry", lambda: _set(_vel(), topic="/localization/kinematic_state")),
    ("diagnostics", lambda: _set(_accel(), topic="/diagnostics")),
    ("an extra record key", lambda: _set(_vel(), seq=1)),
    ("a missing record key", lambda: _del(_vel(), "stamp_ns")),
    ("an extra field key", lambda: _setf(_vel(), lateral_velocity=0.0)),
    ("a missing field key", lambda: _delf(_vel(), "heading_rate")),
    ("another topic's fields", lambda: _set(_steer(), fields={"ax": 0.5})),
    ("a float as text", lambda: _setf(_steer(), steering_tire_angle="0.125")),
    ("a float as bool", lambda: _setf(_accel(), ax=True)),
    ("a float as null", lambda: _setf(_vel(), longitudinal_velocity=None)),
    ("NaN", lambda: _setf(_vel(), longitudinal_velocity=float("nan"))),
    ("infinity", lambda: _setf(_steer(), steering_tire_angle=float("inf"))),
    ("minus infinity", lambda: _setf(_accel(), ax=float("-inf"))),
    ("NaN heading rate", lambda: _setf(_vel(), heading_rate=float("nan"))),
    ("a report as float", lambda: _setf(_gear(), report=2.0)),
    ("a report as bool", lambda: _setf(_gear(), report=True)),
    ("a report above u8", lambda: _setf(_gear(), report=256)),
    ("a negative report", lambda: _setf(_gear(), report=-1)),
    ("a report name as int", lambda: _setf(_gear(), report_name=2)),
    ("a negative recv_ns", lambda: _set(_vel(), recv_ns=-1)),
    ("a float recv_ns", lambda: _set(_vel(), recv_ns=1.5)),
    ("a bool recv_ns", lambda: _set(_vel(), recv_ns=True)),
    ("a text stamp_ns", lambda: _set(_vel(), stamp_ns="900")),
    ("a negative stamp_ns", lambda: _set(_vel(), stamp_ns=-1)),
    ("fields as a list", lambda: _set(_vel(), fields=[2.5, 0.5])),
    ("a record as a list", lambda: [VELOCITY, 1000, 900, {}]),
    ("verdict fields with an extra key", lambda: _set(_vupdate(_verdicts()["replied-accept"]),
                                                      fields=dict(_verdicts()["replied-accept"], kind=2))),
    ("verdict fields as text", lambda: _set(_vupdate(_verdicts()["replied-accept"]), fields=_data(_verdicts()["replied-accept"]))),
]
BAD_UPDATES += [("each field: %s %s" % (field, label),
                 (lambda m=make, f=field, v=value: _setf(m(), **{f: v})))  # type: ignore[misc]
                for make, field in ((_vel, "longitudinal_velocity"), (_vel, "heading_rate"), (_steer, "steering_tire_angle"),
                                    (_accel, "ax"))
                for label, value in (("text", "0.5"), ("bool", False), ("null", None), ("NaN", float("nan")), ("inf", float("inf")),
                                     ("-inf", float("-inf")), ("list", [0.5]))]
BAD_UPDATES += [("a float as a 401-digit integer", lambda: _setf(_accel(), ax=10 ** 400))]


@pytest.mark.parametrize("label,make", BAD_UPDATES, ids=[b[0] for b in BAD_UPDATES])
def test_an_unknown_topic_key_or_type_is_refused(label, make):
    upd = _mod("update")
    with pytest.raises(upd.Refused):
        upd.check(make())


def _padded(obj, total):
    """A verdict text of exactly `total` bytes: v_cmd's number padded with zeros after its last digit (still the same
    binary32 value, still compact)."""
    data = _data(obj)
    old = '"v_cmd":%s,' % json.dumps(obj["v_cmd"])
    assert data.count(old) == 1
    pad = total - len(data)
    assert pad > 0
    return data.replace(old, '"v_cmd":%s%s,' % (json.dumps(obj["v_cmd"]), "0" * pad))


def test_a_verdict_of_1024_bytes_is_taken_and_one_of_1025_refused():
    upd = _mod("update")
    obj = _verdicts()["replied-accept"]
    assert upd.VERDICT_MAX_BYTES == 1024
    ok = _padded(obj, 1024)
    assert len(ok.encode("ascii")) == 1024
    assert upd.parse_verdict(ok) == obj
    big = _padded(obj, 1025)
    with pytest.raises(upd.Refused) as err:
        upd.parse_verdict(big)
    assert err.value.code == "verdict-size"


def _obj(**kw):
    o = dict(_verdicts()["replied-accept"])
    o.update(kw)
    return _data(o)


def _swap(a, b):
    o = _verdicts()["replied-accept"]
    keys = list(o)
    i, j = keys.index(a), keys.index(b)
    keys[i], keys[j] = keys[j], keys[i]
    return _data({k: o[k] for k in keys})


def _without(key):
    o = dict(_verdicts()["replied-accept"])
    del o[key]
    return _data(o)


def _conn(**kw):
    o = dict(_verdicts()["connection-change"])
    o.update(kw)
    return _data(o)


def _good():
    return _data(_verdicts()["replied-accept"])


BAD_VERDICTS = [
    ("not JSON", lambda: _good()[:-1]),
    ("not an object", lambda: "[" + _good() + "]"),
    ("NaN", lambda: _good().replace('"v_cmd":2.5', '"v_cmd":NaN')),
    ("Infinity", lambda: _good().replace('"v_cmd":2.5', '"v_cmd":Infinity')),
    ("minus Infinity", lambda: _good().replace('"acc":0.5', '"acc":-Infinity')),
    ("spaces", lambda: json.dumps(_verdicts()["replied-accept"])),
    ("a trailing newline", lambda: _good() + "\n"),
    ("non-ASCII", lambda: _good().replace('{"v":1', '{"é":0,"v":1')),
    ("a duplicate key", lambda: _good().replace('"seq":41', '"seq":41,"seq":41')),
    ("bytes, not text", lambda: _good().encode("ascii")),
    ("two keys swapped", lambda: _swap("v_cmd", "acc")),
    ("verdict and reason swapped", lambda: _swap("verdict", "reason")),
    ("a missing key", lambda: _without("connected")),
    ("an extra key", lambda: _obj(kind=2)),
    ("format 2", lambda: _obj(v=2)),
    ("format true", lambda: _obj(v=True)),
    ("a negative seq", lambda: _obj(seq=-1)),
    ("the sentinel seq", lambda: _obj(seq=2 ** 64 - 1)),
    ("a seq above u64", lambda: _obj(seq=2 ** 64)),
    ("a float seq", lambda: _obj(seq=41.0)),
    ("a profile above u8", lambda: _obj(profile=256)),
    ("a negative profile", lambda: _obj(profile=-1)),
    ("a null profile", lambda: _obj(profile=None)),
    ("v_cmd as text", lambda: _obj(v_cmd="2.5")),
    ("v_cmd as bool", lambda: _obj(v_cmd=True)),
    ("v_cmd not a binary32 value", lambda: _obj(v_cmd=0.1)),
    ("v_cmd beyond binary32", lambda: _obj(v_cmd=1e39)),
    ("acc not a binary32 value", lambda: _obj(acc=0.1)),
    ("steer as text", lambda: _obj(steer="0")),
    ("steer_rate as a list", lambda: _obj(steer_rate=[0.25])),
    ("an interval above u16", lambda: _obj(interval_ms=65536)),
    ("a negative interval", lambda: _obj(interval_ms=-1)),
    ("a null interval", lambda: _obj(interval_ms=None)),
    ("verdict 2", lambda: _obj(verdict=2, reason=0)),
    ("verdict true", lambda: _obj(verdict=True)),
    ("a reason above u8", lambda: _obj(verdict=1, reason=256)),
    ("a verdict with no reason", lambda: _obj(verdict=0, reason=None)),
    ("a reason with no verdict", lambda: _obj(verdict=None, reason=0)),
    ("ACCEPT with a reason", lambda: _obj(verdict=0, reason=8)),
    ("REJECT with reason 0", lambda: _obj(verdict=1, reason=0)),
    ("a reply on a connection change", lambda: _conn(verdict=0, reason=0)),
    ("a negative counter", lambda: _obj(packed=-1)),
    ("a counter above u32", lambda: _obj(dropped=2 ** 32)),
    ("a float counter", lambda: _obj(replied=40.0)),
    ("a null counter", lambda: _obj(reconnects=None)),
    ("connected as 1", lambda: _obj(connected=1)),
    ("connected as null", lambda: _obj(connected=None)),
]
BAD_VERDICTS += [("each counter: %s %s" % (key, label),
                  (lambda k=key, v=value: _obj(**{k: v})))  # type: ignore[misc]
                 for key in ("packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects")
                 for label, value in (("-1", -1), ("2**32", 2 ** 32), ("float", 1.0), ("bool", True), ("null", None))]
BAD_VERDICTS += [("each float: %s %s" % (key, label),
                  (lambda k=key, v=value: _obj(**{k: v})))  # type: ignore[misc]
                 for key in ("v_cmd", "acc", "jerk", "steer", "steer_rate")
                 for label, value in (("text", "1"), ("bool", False), ("not binary32", 0.1), ("beyond binary32", 3.5e38),
                                      ("list", [0.5]), ("object", {"x": 1}))]
BAD_VERDICTS += [("a float key as a 401-digit integer", lambda: _obj(acc=10 ** 400)),
                 ("a lone surrogate", lambda: '{"v":1\ud800}')]


@pytest.mark.parametrize("label,make", BAD_VERDICTS, ids=[b[0] for b in BAD_VERDICTS])
def test_a_verdict_that_is_not_valid_2_6_is_refused(label, make):
    upd = _mod("update")
    with pytest.raises(upd.Refused):
        upd.parse_verdict(make())


def test_every_message_kind_of_the_fixture_is_valid_2_6():
    upd = _mod("update")
    for name, obj in _verdicts().items():
        got = upd.parse_verdict(_data(obj))
        assert got == obj and list(got) == list(upd.VERDICT_KEYS), name
    assert upd.VERDICT_KEYS == ("v", "seq", "profile", "v_cmd", "acc", "jerk", "steer", "steer_rate", "interval_ms", "verdict",
                                "reason", "packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect",
                                "reconnects", "connected")


# Stand-ins for the message classes (autoware_vehicle_msgs, geometry_msgs, std_msgs), with only the fields spec 2.7
# names and the stamps they carry.

class _Time:
    def __init__(self, sec, nanosec):
        self.sec, self.nanosec = sec, nanosec


class _Header:
    def __init__(self, sec, nanosec):
        self.stamp = _Time(sec, nanosec)


class VelocityReport:
    def __init__(self, longitudinal_velocity=0.0, heading_rate=0.0, sec=0, nanosec=0):
        self.header = _Header(sec, nanosec)
        self.longitudinal_velocity, self.lateral_velocity, self.heading_rate = longitudinal_velocity, 9.5, heading_rate


class SteeringReport:
    def __init__(self, steering_tire_angle=0.0, sec=0, nanosec=0):
        self.stamp = _Time(sec, nanosec)
        self.steering_tire_angle = steering_tire_angle


class _GearMeta(type):
    """rosidl_generator_py's pattern: the constants live in the metaclass, reach the class namespace through
    __prepare__, and the class serves them through metaclass properties."""

    _CONSTANTS: dict = {}

    @classmethod
    def __prepare__(mcs, name, bases, **kwargs):
        return dict(mcs._CONSTANTS)


def _constant_property(name):
    return property(lambda self: _GearMeta._CONSTANTS[name])


_GearMeta._CONSTANTS = _gear_constants()
for _n in _GearMeta._CONSTANTS:
    setattr(_GearMeta, _n, _constant_property(_n))


class GearReport(metaclass=_GearMeta):
    SLOT_TYPES = ("builtin_interfaces/Time", "uint8")
    _fields_and_field_types = {"stamp": "builtin_interfaces/Time", "report": "uint8"}

    def __init__(self, report=0, sec=0, nanosec=0):
        self.stamp = _Time(sec, nanosec)
        self.report = report


class AccelWithCovarianceStamped:
    def __init__(self, ax=0.0, sec=0, nanosec=0):
        self.header = _Header(sec, nanosec)
        linear = types.SimpleNamespace(x=ax, y=7.5, z=0.0)
        self.accel = types.SimpleNamespace(accel=types.SimpleNamespace(linear=linear), covariance=[0.0] * 36)


class String:
    def __init__(self, data=""):
        self.data = data


def test_messages_become_updates_with_their_own_stamps():
    upd = _mod("update")
    names = upd.constant_names(GearReport)
    u = upd.from_velocity(VelocityReport(-2.5, 0.25, sec=12, nanosec=345), 99)
    assert u == {"topic": VELOCITY, "recv_ns": 99, "stamp_ns": 12_000_000_345,
                 "fields": {"longitudinal_velocity": -2.5, "heading_rate": 0.25}}
    u = upd.from_steering(SteeringReport(0.125, sec=3, nanosec=4), 98)
    assert u == {"topic": STEERING, "recv_ns": 98, "stamp_ns": 3_000_000_004, "fields": {"steering_tire_angle": 0.125}}
    u = upd.from_gear(GearReport(report=GearReport.REVERSE, sec=5, nanosec=6), 97, names)
    assert u == {"topic": GEAR, "recv_ns": 97, "stamp_ns": 5_000_000_006, "fields": {"report": 20, "report_name": "REVERSE"}}
    u = upd.from_accel(AccelWithCovarianceStamped(-1.5, sec=7, nanosec=8), 96)
    assert u == {"topic": ACCEL, "recv_ns": 96, "stamp_ns": 7_000_000_008, "fields": {"ax": -1.5}}
    obj = _verdicts()["replied-reject"]
    u = upd.from_verdict(String(_data(obj)), 95)
    assert u == {"topic": VERDICT, "recv_ns": 95, "stamp_ns": None, "fields": obj}
    with pytest.raises(upd.Refused):
        upd.from_verdict(String(_data(obj)[:-1]), 95)
    # an integer field from a message (a velocity of 0 sent as an int) is a float in the update
    u = upd.from_velocity(VelocityReport(0, 0, sec=1, nanosec=0), 1)
    assert type(u["fields"]["longitudinal_velocity"]) is float and type(u["fields"]["heading_rate"]) is float


def test_a_report_with_no_constant_gets_a_name_the_mapping_refuses():
    upd = _mod("update")
    names = upd.constant_names(GearReport)
    u = upd.from_gear(GearReport(report=99), 1, names)
    assert u["fields"]["report"] == 99 and u["fields"]["report_name"] not in _gear_constants()
    with pytest.raises(upd.Refused):
        _mod("mapping").map_update(u)


def test_the_gear_names_come_from_the_message_classs_own_constants():
    upd = _mod("update")
    want = {v: k for k, v in _gear_constants().items()}
    assert upd.constant_names(GearReport) == want

    class Plain:
        NONE = 0
        DRIVE = 2
        REVERSE = 20
        SLOT_TYPES = ("uint8",)
        report = 4
        Mixed_Case = 5
        FLAG = True
        NAME = "DRIVE"

    assert upd.constant_names(Plain) == {0: "NONE", 2: "DRIVE", 20: "REVERSE"}

    class Twice:
        DRIVE = 2
        FORWARD = 2

    with pytest.raises(ValueError):
        upd.constant_names(Twice)


# --- mapping.py -------------------------------------------------------------------------------------------------

def test_the_write_sets_are_2_8s():
    m = _mod("mapping")
    assert m.WRITER == "ros-vss-feeder"
    assert m.RUN_TYPES == ("planning-sim", "carla-autoware")
    assert set(m.write_set("planning-sim")) == STANDARD | OVERLAY_PATHS
    assert set(m.write_set("carla-autoware")) == OVERLAY_PATHS
    assert len(m.write_set("planning-sim")) == 27 and len(m.write_set("carla-autoware")) == 21
    assert tuple(m.CONTROL_COMMAND) == tuple(CC + leaf for leaf in CC_LEAVES)
    assert tuple(m.CTL_CLAIM) == tuple(CTL + leaf for leaf in CTL_LEAVES)
    with pytest.raises(ValueError):
        m.write_set("sigsim")


def test_no_standard_signal_is_in_carla_autowares_set():
    m = _mod("mapping")
    assert not set(m.write_set("carla-autoware")) & STANDARD
    assert all(p.startswith(("Vehicle.DualVm.ControlCommand.", "Vehicle.DualVm.Monitor.CtlClaim."))
               for p in m.write_set("carla-autoware"))


NEVER = ("Vehicle.Body.Lights.Hazard.IsSignaling", "Vehicle.Chassis.Wheelbase")
NEVER_PREFIXES = ("Vehicle.DualVm.AppState.", "Vehicle.DualVm.Monitor.VssClaim.")


def test_no_run_type_writes_the_hazard_light_appstate_vssclaim_or_the_wheelbase():
    m = _mod("mapping")
    for rt in m.RUN_TYPES:
        for p in m.write_set(rt):
            assert p not in NEVER and not p.startswith(NEVER_PREFIXES), (rt, p)
    produced = {p for u in _all_updates() for p, _v in m.map_update(u)}
    assert not {p for p in produced if p in NEVER or p.startswith(NEVER_PREFIXES)}
    for rt in m.RUN_TYPES:
        w, sink, _log = _writer(rt)
        for u in _all_updates():
            w.handle(u)
        assert not [p for p in sink.paths() if p in NEVER or p.startswith(NEVER_PREFIXES)]


def test_a_write_set_holding_a_path_no_run_type_writes_is_refused(monkeypatch):
    m = _mod("mapping")
    vw = _mod("vsswriter")
    assert (m.NEVER_WRITTEN, m.NEVER_PREFIXES) == (NEVER, NEVER_PREFIXES)            # the module's list is 2.8's
    for p in NEVER + tuple(prefix + "State" for prefix in NEVER_PREFIXES):
        assert m.never_written(p), p
    for rt in m.RUN_TYPES:
        assert not [p for p in m.write_set(rt) if m.never_written(p)]
    # an edit that put one of them into a write set: every user of the set refuses it
    for bad in ("Vehicle.Body.Lights.Hazard.IsSignaling", "Vehicle.Chassis.Wheelbase",
                "Vehicle.DualVm.AppState.HardBrakeHazard.State", "Vehicle.DualVm.Monitor.VssClaim.Verdict"):
        for rt in m.RUN_TYPES:
            monkeypatch.setitem(m.WRITE_SETS, rt, frozenset(m.WRITE_SETS[rt] | {bad}))
            with pytest.raises(ValueError) as err:
                m.write_set(rt)
            assert bad in str(err.value)
            with pytest.raises(ValueError):
                vw.Writer(rt, FakeSink(), [].append)
            with pytest.raises(ValueError):
                vw.start_problems(dict(m.DATATYPES, **{bad: "boolean"}), rt)
            monkeypatch.undo()


def test_the_writer_writes_inside_the_run_types_set_only():
    w, sink, log = _writer("carla-autoware")
    for u in _vehicle_updates() * 2:
        w.handle(u)
    assert sink.published == []
    c = w.counts()
    assert c["outside_write_set"] == {p: 2 for p in STANDARD}
    lines = [r for r in log if r.get("event") == "outside-write-set"]
    assert sorted(r["path"] for r in lines) == sorted(STANDARD)            # once by path
    w.handle(_vupdate(_verdicts()["replied-reject"]))
    assert sink.published and set(sink.paths()) <= OVERLAY_PATHS
    w, sink, log = _writer("planning-sim")
    for u in _all_updates():
        w.handle(u)
    assert set(sink.paths()) <= STANDARD | OVERLAY_PATHS
    assert w.counts()["outside_write_set"] == {}
    assert not [r for r in log if r.get("event") == "outside-write-set"]


def test_every_path_of_each_write_set_is_written_by_some_update():
    m = _mod("mapping")
    for rt in m.RUN_TYPES:
        w, sink, _log = _writer(rt)
        for u in _all_updates():
            w.handle(u)
        assert set(sink.paths()) == set(m.write_set(rt)), rt
        for batch in sink.published:
            for p, _v, t in batch:
                assert t == m.DATATYPES[p], p


@pytest.mark.parametrize("hr", [0.5, -0.25, 0.0, 1e-3])
def test_heading_rate_goes_to_yaw_in_degrees_per_second_positive_left(hr):
    # Autoware's heading_rate and the overlay's Yaw both count yawing left as positive (INFERRED, spec 2.8): no sign
    # change, rad/s to deg/s.
    got = _items(_vel(hr=hr))[YAW]
    assert got == hr * 180.0 / math.pi or abs(got - hr * 180.0 / math.pi) <= 1e-12 * max(1.0, abs(got))
    assert math.copysign(1.0, got) == math.copysign(1.0, hr)
    if hr:
        assert abs(got / hr - 57.29577951308232) < 1e-9


@pytest.mark.parametrize("a", [0.125, -0.5, 0.0])
def test_the_steering_tire_angle_goes_to_row1_steering_angle_in_degrees_positive_left(a):
    got = _items(_steer(a))[STEER_ANGLE]
    assert abs(got - a * 180.0 / math.pi) <= 1e-12 * max(1.0, abs(got))
    assert math.copysign(1.0, got) == math.copysign(1.0, a)
    if a:
        assert abs(got / a - 57.29577951308232) < 1e-9


@pytest.mark.parametrize("v", [-2.5, 2.5, 0.0, 13.75])
def test_the_longitudinal_velocity_goes_signed_to_motion_and_as_a_magnitude_in_km_h_to_speed(v):
    factor = _attribution().UNIT_FACTORS[("m/s", "km/h")]
    assert factor == 3.6
    got = _items(_vel(v=v))
    assert got[LONG_VEL] == v
    assert got[SPEED] == abs(v) * factor and got[SPEED] >= 0.0


def test_ax_goes_to_the_longitudinal_acceleration_as_it_is():
    assert _items(_accel(-1.5)) == {ACC_LONG: -1.5}
    assert _items(_accel(2.25)) == {ACC_LONG: 2.25}


def _expected_gear(name):
    if name.startswith(("DRIVE", "LOW")):
        return 1
    if name.startswith("REVERSE"):
        return -1
    return {"NEUTRAL": 0, "PARK": 0, "NONE": 0}[name]


@pytest.mark.parametrize("name", sorted(_gear_constants()))
def test_each_gear_report_name_maps_to_current_gear(name):
    got = _items(_gear(name, _gear_constants()[name]))
    assert got == {CURRENT_GEAR: _expected_gear(name)}
    assert type(got[CURRENT_GEAR]) is int


@pytest.mark.parametrize("name", ["", "FORWARD", "PARKING", "NEUTRAL_2", "NONE_1", "drive", " DRIVE", "UNKNOWN_99", "R", "D"])
def test_an_unknown_gear_name_is_refused_and_counted_never_written(name):
    m = _mod("mapping")
    upd = _mod("update")
    with pytest.raises(upd.Refused):
        m.map_update(_gear(name, 2))
    w, sink, _log = _writer()
    w.handle(_gear(name, 2))
    assert sink.published == [] and w.counts()["refused"] == {"gear": 1} and w.counts()["updates"] == 1


def test_a_null_value_is_never_written_and_its_defined_leaf_is_false():
    v = _verdicts()
    got = _items(_vupdate(v["dropped"]))
    for value_leaf, defined_leaf in (("Acceleration", "IsAccelerationDefined"), ("Jerk", "IsJerkDefined"),
                                     ("SteeringTireRotationRate", "IsSteeringTireRotationRateDefined")):
        assert CC + value_leaf not in got
        assert got[CC + defined_leaf] is False
    assert CTL + "Verdict" not in got and CTL + "Reason" not in got
    assert got[CC + "Velocity"] == 3.0
    got = _items(_vupdate(v["injected-nan"]))
    assert CC + "Velocity" not in got and got[CC + "SteeringTireAngle"] == 0.0625
    assert not [p for p, val in _mod("mapping").map_update(_vupdate(v["injected-nan"])) if val is None]
    got = _items(_vupdate(v["replied-reject"]))
    assert got[CC + "Acceleration"] == -1.25 and got[CC + "IsAccelerationDefined"] is True
    assert got[CC + "Jerk"] == 0.75 and got[CC + "IsJerkDefined"] is True
    assert got[CC + "SteeringTireRotationRate"] == 0.25 and got[CC + "IsSteeringTireRotationRateDefined"] is True
    for u in _all_updates():
        assert not [p for p, val in _mod("mapping").map_update(u) if val is None], u


def test_a_connection_change_writes_only_is_connected_reconnects_and_the_counters():
    obj = _verdicts()["connection-change"]
    got = _items(_vupdate(obj))
    assert set(got) == {CTL + "IsConnected"} | {CTL + leaf for leaf in COUNTERS}
    assert got[CTL + "IsConnected"] is True
    for leaf, key in COUNTERS.items():
        assert got[CTL + leaf] == obj[key] and type(got[CTL + leaf]) is int


def test_last_seq_verdict_and_reason_come_from_a_replied_frame_only():
    v = _verdicts()
    got = _items(_vupdate(v["replied-accept"]))
    assert (got[CTL + "LastSeq"], got[CTL + "Verdict"], got[CTL + "Reason"]) == (41, 0, 0)
    got = _items(_vupdate(v["replied-reject"]))
    assert (got[CTL + "LastSeq"], got[CTL + "Verdict"], got[CTL + "Reason"]) == (42, 1, 12)
    for name in ("dropped", "lost", "connection-change"):
        got = _items(_vupdate(v[name]))
        assert not {CTL + "LastSeq", CTL + "Verdict", CTL + "Reason"} & set(got), name


def test_the_first_frame_seq_1_writes_the_command_leaves_and_last_seq():
    obj = dict(_verdicts()["replied-accept"], seq=1, packed=1, replied=1, accepted=1, dropped=0)   # the node's first frame
    got = _items(_vupdate(obj))
    assert got[CC + "Velocity"] == 2.5 and got[CC + "ProfileId"] == 1 and got[CTL + "LastSeq"] == 1


def _vspec_descriptions(path, prefix):
    """{leaf path: description} of the vspec file's one-line descriptions under prefix."""
    out = {}
    cur = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Vehicle."):
            cur = line.rstrip()[:-1] if line.startswith(prefix) and line.rstrip().endswith(":") else None
        elif cur is not None and line.strip().startswith("description:"):
            out[cur] = line.split(":", 1)[1].strip().strip('"')
    return out


def test_last_seq_verdict_and_reason_are_the_overlays_last_reply_received():
    # The mapping writes these three from a replied frame's message only, against spec 2.8's words (LastSeq from every
    # frame's seq), because overlay.vspec defines each as the last reply's. Should the vspec give way instead of the
    # spec, this fails, and mapping.verdict_items has to follow the new definition.
    d = _vspec_descriptions(OVERLAY, CTL)
    for leaf in ("LastSeq", "Verdict", "Reason"):
        assert "of the last reply received" in d[CTL + leaf], (leaf, d.get(CTL + leaf))
    assert "last reply received" in _mod("mapping").__doc__


def test_a_replied_frames_message_writes_every_leaf_with_its_type():
    obj = _verdicts()["replied-reject"]
    got = _items(_vupdate(obj))
    want = {CC + "Velocity": 30.5, CC + "Acceleration": -1.25, CC + "IsAccelerationDefined": True, CC + "Jerk": 0.75,
            CC + "IsJerkDefined": True, CC + "SteeringTireAngle": -0.125, CC + "SteeringTireRotationRate": 0.25,
            CC + "IsSteeringTireRotationRateDefined": True, CC + "ProfileId": 1, CC + "StampInterval": 34,
            CTL + "Verdict": 1, CTL + "Reason": 12, CTL + "LastSeq": 42, CTL + "IsConnected": True}
    want.update({CTL + leaf: obj[key] for leaf, key in COUNTERS.items()})
    assert got == want
    for p, val in got.items():
        dtype = _mod("mapping").DATATYPES[p]
        assert type(val) is {"float": float, "boolean": bool}.get(dtype, int), (p, val, dtype)


def _vspec_leaves(path, prefix):
    """{leaf path: datatype} of the vspec file's nodes under prefix (the files' own `Path:` / `  datatype:` layout)."""
    out = {}
    cur = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix) and line.rstrip().endswith(":"):
            cur = line.rstrip()[:-1]
        elif line.startswith("Vehicle.") or not line.strip():
            if line.startswith("Vehicle."):
                cur = None
        elif cur is not None and line.strip().startswith("datatype:"):
            out[cur] = line.split(":", 1)[1].strip()
    return out


def test_the_overlay_leaves_and_their_datatypes_are_the_vspec_files():
    m = _mod("mapping")
    cc = _vspec_leaves(OVERLAY_CTL, CC)
    ctl = _vspec_leaves(OVERLAY, CTL)
    assert list(cc) == list(m.CONTROL_COMMAND) and set(ctl) == set(m.CTL_CLAIM) and len(ctl) == len(m.CTL_CLAIM)
    for p, dtype in list(cc.items()) + list(ctl.items()):
        assert m.DATATYPES[p] == dtype, p
    assert set(m.DATATYPES) == set(m.write_set("planning-sim"))


def _require_gen():
    if not (GEN / "vss-databroker.json").is_file():
        if os.environ.get("SDV_REQUIRE_GEN") == "1":
            pytest.fail("SDV_REQUIRE_GEN=1 and the generated catalogue is missing: %s" % (GEN / "vss-databroker.json"))
        pytest.skip("needs the generated catalogue in sdv-out/gen (sdv/vss/generate.py)")


def test_the_standard_paths_datatypes_and_units_are_the_generated_catalogues():
    _require_gen()
    m = _mod("mapping")
    nodes = _attribution().leaf_nodes(json.loads((GEN / "vss-databroker.json").read_text(encoding="utf-8")))
    units = {LONG_VEL: "m/s", SPEED: "km/h", YAW: "degrees/s", STEER_ANGLE: "degrees", ACC_LONG: "m/s^2", CURRENT_GEAR: None}
    for p, unit in units.items():
        assert nodes[p].get("unit") == unit, p
        assert m.UNITS[p] == unit, p
    for p in STANDARD | {CTL + leaf for leaf in CTL_LEAVES}:
        assert nodes[p]["datatype"] == m.DATATYPES[p], p
    for p in m.CONTROL_COMMAND:                                       # in the catalogue once WP1b loads overlay-ctl.vspec
        if p in nodes:
            assert nodes[p]["datatype"] == m.DATATYPES[p], p
    assert nodes[SPEED].get("min") == 0


def test_attribution_takes_the_writer_under_ctl_claim_and_the_same_slots():
    attr = _attribution()
    m = _mod("mapping")
    assert tuple(m.SLOT_PATHS) == tuple(attr.SLOT_PATHS)
    assert m.KMH_PER_MS == attr.UNIT_FACTORS[("m/s", "km/h")]
    paths = [CTL + leaf for leaf in CTL_LEAVES]
    cat = {p: {"type": "sensor", "datatype": m.DATATYPES[p]} for p in paths}

    def c5(writer):
        rows = [{"path": p, "node": attr.node_text(cat[p]), "writer": writer, "role": "provider", "ingress": "vss:provide",
                 "cloud": "no"} for p in paths]
        checks = attr.check_rows(rows, cat, {}, {"signal_message": {}, "messages": {}}, {writer: paths}, "hard-brake-hazard")
        return [c for c in checks if c[0] == "C5"][0]

    assert c5(m.WRITER)[1] is True
    assert c5("vss-claim-bridge")[1] is False


# --- vsswriter.py -----------------------------------------------------------------------------------------------

def test_the_writer_counts_updates_refusals_writes_and_drops():
    vw = _mod("vsswriter")
    upd = _mod("update")
    w, sink, log = _writer()
    w.handle(_vel())
    w.handle(_gear("FORWARD"))
    w.handle(_set(_vel(), topic=CONTROL_CMD))
    w.handle(_set(_vel(), topic=CONTROL_CMD))
    w.handle(_vupdate(_verdicts()["connection-change"]))
    w.refuse("verdict-json")
    w.log_counts(final=False)
    c = w.counts()
    assert c["updates"] == 5
    assert c["refused"] == {"gear": 1, "topic": 2, "verdict-json": 1}
    assert c["written"][LONG_VEL] == 1 and c["written"][SPEED] == 1 and c["written"][YAW] == 1
    assert c["written"][CTL + "Reconnects"] == 1 and CTL + "LastSeq" not in c["written"]
    assert len(sink.published) == 2
    refused_lines = [r for r in log if r.get("event") == "refused"]
    assert sorted(r["code"] for r in refused_lines) == ["gear", "topic", "verdict-json"]    # each code logged once
    q = vw.LatestQueue(3)
    for i in range(5):
        q.put(_steer(i * 0.125))
    assert len(q) == 3 and q.dropped == 2
    assert q.get(0.0)["fields"]["steering_tire_angle"] == 0.25                          # the oldest kept is the third
    assert isinstance(upd.Refused("topic", "x"), ValueError)


def test_counts_lines_come_each_period_and_once_more_at_the_stop():
    vw = _mod("vsswriter")
    clock = Clock(0)
    w, sink, log = _writer(clock=clock)
    stop = threading.Event()
    period = int(vw.COUNTS_PERIOD_S * 1e9)

    class Feed:
        """Hands the writer one update per get and moves the clock half a period each time."""

        def __init__(self, n):
            self.n = n
            self.dropped = 0

        def get(self, timeout):
            clock.t += period // 2
            if self.n == 0:
                stop.set()
                return None
            self.n -= 1
            return _vel()

        def __len__(self):
            return 0

    w.run(Feed(6), stop)
    counts = [r for r in log if r.get("event") == "counts"]
    assert [r["final"] for r in counts] == [False, False, False, True]
    assert counts[-1]["updates"] == 6 and counts[-1]["written"][LONG_VEL] == 6 and counts[-1]["dropped"] == 0


def test_a_failing_databroker_is_counted_and_the_writer_goes_on():
    w, sink, log = _writer(sink=FakeSink(fail=2))
    for _ in range(3):
        w.handle(_steer(0.5))
    c = w.counts()
    assert c["write_failed"] == {STEER_ANGLE: 2} and c["written"] == {STEER_ANGLE: 1}
    failed = [r for r in log if r.get("event") == "write-failed"]
    assert len(failed) == 1 and failed[0]["error"] == "RuntimeError" and failed[0]["paths"] == [STEER_ANGLE]


def test_a_sink_failing_with_any_exception_subclass_is_counted_and_the_writer_goes_on():
    class VSSClientError(Exception):                                  # kuksa-client's and grpc's errors are no RuntimeError
        pass

    class Failing(FakeSink):
        def publish(self, items):
            raise VSSClientError("no")

    w, sink, log = _writer(sink=Failing())
    w.handle(_steer(0.5))
    w.handle(_steer(0.5))
    assert w.counts()["write_failed"] == {STEER_ANGLE: 2}
    assert [r["error"] for r in log if r.get("event") == "write-failed"] == ["VSSClientError"]


def test_an_update_the_writer_cannot_take_is_counted_as_an_error_and_the_writer_goes_on(monkeypatch):
    vw = _mod("vsswriter")
    m = _mod("mapping")

    class Fault(Exception):
        pass

    real = m.map_update

    def map_update(update):                                           # a fault of the package's own in the mapping
        if update["topic"] == GEAR:
            raise Fault("the value 777.25 did not map")
        return real(update)

    class Unreadable(dict):                                           # and one in the check: fields it cannot list
        def __iter__(self):
            raise RuntimeError("the value 666.5 cannot be listed")

    monkeypatch.setattr(m, "map_update", map_update)
    w, sink, log = _writer()
    w.handle(_gear())
    w.handle(_gear())
    w.handle({"topic": STEERING, "recv_ns": 1, "stamp_ns": 1, "fields": Unreadable(steering_tire_angle=0.5)})
    w.handle(_steer(0.5))
    c = w.counts()
    assert c["updates"] == 4 and c["refused"] == {"error": 3} and c["written"] == {STEER_ANGLE: 1}
    assert [r["code"] for r in log if r["event"] == "refused"] == ["error"]                  # the code logged once
    assert sorted(r["error"] for r in log if r["event"] == "error") == ["Fault", "RuntimeError"]   # each type once
    assert "777.25" not in json.dumps(log) and "666.5" not in json.dumps(log)              # the type name only
    # in the writer's thread: the update after the fault is written, and the last counts line comes
    stop = threading.Event()

    class Feed:
        def __init__(self, items):
            self.items = list(items)
            self.dropped = 0

        def get(self, timeout):
            if not self.items:
                stop.set()
                return None
            return self.items.pop(0)

        def __len__(self):
            return len(self.items)

    w, sink, log = _writer()
    w.run(Feed([_gear(), _steer(0.25)]), stop)
    final = [r for r in log if r["event"] == "counts"][-1]
    assert final["final"] is True and final["refused"] == {"error": 1} and final["written"] == {STEER_ANGLE: 1}
    assert w.died is None and vw.ERROR_CODE == "error"


def test_the_start_check_refuses_a_path_not_served_or_served_with_another_datatype():
    vw = _mod("vsswriter")
    m = _mod("mapping")
    served = dict(m.DATATYPES)
    assert vw.start_problems(served, "planning-sim") == []
    assert vw.start_problems({p: served[p] for p in m.write_set("carla-autoware")}, "carla-autoware") == []
    missing = dict(served)
    del missing[CC + "StampInterval"]
    problems = vw.start_problems(missing, "planning-sim")
    assert len(problems) == 1 and CC + "StampInterval" in problems[0]
    assert vw.start_problems(missing, "carla-autoware") != []
    wrong = dict(served, **{SPEED: "double"})
    problems = vw.start_problems(wrong, "planning-sim")
    assert len(problems) == 1 and SPEED in problems[0]
    assert vw.start_problems(wrong, "carla-autoware") == []           # Vehicle.Speed is not in its set
    assert vw.start_problems(dict(served, **{CTL + "LastSeq": None}), "carla-autoware") != []


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def test_the_log_holds_no_value_of_any_signal():
    vw = _mod("vsswriter")
    v = _f32(7.123456789)
    acc = _f32(-3.987654321)
    obj = dict(_verdicts()["replied-reject"], seq=987654321, v_cmd=v, acc=acc, jerk=_f32(1.23456789), steer=_f32(0.3456789),
               steer_rate=_f32(0.0987654321), interval_ms=4321, packed=424242, replied=414141, accepted=404040, rejected=10101,
               dropped=10001, lost_on_reconnect=100, reconnects=73, profile=171)
    updates = [_vel(-8.765432101, 0.654321987), _steer(0.4567891234), _accel(-2.345678901), _gear("REVERSE_2", 21),
               _vupdate(obj), _gear("SECRET_GEAR_NAME_XYZ", 22), _setf(_vel(), heading_rate=float("nan"))]
    values = [-8.765432101, 0.654321987, 0.4567891234, -2.345678901, v, acc, obj["jerk"], obj["steer"], obj["steer_rate"]]
    values += [abs(-8.765432101) * 3.6, math.degrees(0.654321987), math.degrees(0.4567891234)]
    ints = [987654321, 4321, 424242, 414141, 404040, 10101, 10001, 73, 171]
    for sink in (FakeSink(), FakeSink(fail=10)):
        log = []
        w = vw.Writer("planning-sim", sink, log.append, clock=Clock(5))
        for u in updates:
            w.handle(u)
        w.log_counts(final=True)
        text = "\n".join(json.dumps(r) for r in log)
        for x in values:
            for form in (repr(x), "%.3f" % x, "%.5g" % x, "%g" % x, repr(_f32(x))):
                assert form not in text, (form, text)
        for n in ints:
            assert str(n) not in text, (n, text)
        assert "SECRET_GEAR_NAME_XYZ" not in text and "777.25" not in text
        assert not [x for r in log for x in _walk(r) if isinstance(x, float)]          # no float anywhere: counts only


class SlowSink(FakeSink):
    """A databroker that does not answer until released."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = threading.Event()

    def publish(self, items):
        self.entered.set()
        self.release.wait(10)
        self.published.append(list(items))


def test_a_slow_databroker_never_blocks_a_callback_and_the_newest_updates_are_kept():
    vw = _mod("vsswriter")
    fn = _mod("feeder_node")
    upd = _mod("update")
    sink = SlowSink()
    log = []
    w = vw.Writer("planning-sim", sink, log.append, clock=Clock())
    q = vw.LatestQueue(vw.QUEUE_MAX)
    stop = threading.Event()
    writer_thread = threading.Thread(target=w.run, args=(q, stop), daemon=True)
    writer_thread.start()
    extra = 50
    angles = [i * 2.0 ** -12 for i in range(vw.QUEUE_MAX + extra + 1)]
    cb = fn.make_callback(upd.from_steering, q, w.refuse, clock=lambda: 5)
    first = threading.Thread(target=cb, args=(SteeringReport(angles[0], sec=1),), daemon=True)
    done = threading.Event()

    def deliver():
        for a in angles[1:]:
            cb(SteeringReport(a, sec=1))
        done.set()

    rest = threading.Thread(target=deliver, daemon=True)
    try:
        first.start()
        assert sink.entered.wait(5)
        first.join(5)
        assert not first.is_alive(), "the first callback blocked on the databroker"
        rest.start()
        assert done.wait(5), "a callback blocked while the databroker was slow"
        assert len(q) == vw.QUEUE_MAX and q.dropped == extra
    finally:
        sink.release.set()
    deadline = time.monotonic() + 20
    while len(sink.published) < vw.QUEUE_MAX + 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    writer_thread.join(10)
    assert not writer_thread.is_alive()
    got = [dict((p, val) for p, val, _t in batch)[STEER_ANGLE] for batch in sink.published]
    assert len(got) == vw.QUEUE_MAX + 1
    assert got[0] == math.degrees(angles[0])
    assert got[1] == math.degrees(angles[extra + 1])                  # the oldest were dropped
    assert got[-1] == math.degrees(angles[-1])                        # the newest was written
    final = [r for r in log if r.get("event") == "counts"][-1]
    assert final["final"] is True and final["dropped"] == extra


def test_a_dropped_update_is_lost_only_until_a_later_update_writes_its_paths():
    vw = _mod("vsswriter")
    # QUEUE_MAX's reason says what dropping the oldest costs, and claims no more
    assert "loses no state" not in vw.__doc__ and "until a later update writes" in vw.__doc__
    v = _verdicts()
    w, sink, _log = _writer()
    q = vw.LatestQueue(vw.QUEUE_MAX)
    q.put(_gear("REVERSE", 20))                                       # the only gear report in the queue
    q.put(_vupdate(v["replied-reject"]))                              # the only verdict message in the queue
    for i in range(vw.QUEUE_MAX):
        q.put(_steer(i * 2.0 ** -12))
    assert q.dropped == 2
    while len(q):
        w.handle(q.get(0.0))
    written = w.counts()["written"]
    assert CURRENT_GEAR not in written and not [p for p in written if p.startswith((CC, CTL))]
    w.handle(_vupdate(v["dropped"]))                                  # the next verdict message: a frame with no reply
    written = w.counts()["written"]
    assert written[CTL + "Packed"] == 1 and written[CC + "Velocity"] == 1
    assert not {CTL + "LastSeq", CTL + "Verdict", CTL + "Reason"} & set(written)
    w.handle(_vupdate(v["replied-accept"]))                           # the next replied frame
    w.handle(_gear("DRIVE", 2))                                       # the gear's next report
    written = w.counts()["written"]
    assert written[CTL + "LastSeq"] == written[CTL + "Verdict"] == written[CTL + "Reason"] == 1
    assert written[CURRENT_GEAR] == 1


def test_a_refused_message_is_counted_by_the_callback_and_never_queued():
    vw = _mod("vsswriter")
    fn = _mod("feeder_node")
    upd = _mod("update")
    w, sink, log = _writer()
    q = vw.LatestQueue(vw.QUEUE_MAX)
    cb = fn.make_callback(upd.from_verdict, q, w.refuse, clock=lambda: 5)
    cb(String("x" * 1025))
    cb(String("{}"))
    cb(String(_data(_verdicts()["lost"])))
    cb(object())                                                      # a message the builder cannot read
    assert len(q) == 1 and w.counts()["refused"] == {"verdict-size": 1, "verdict-keys": 1, "message": 1}
    assert log == []                                                  # a callback does no I/O: the writer logs
    assert q.get(0.0)["fields"]["seq"] == 44
    w.flush_refusals()
    assert sorted(r["code"] for r in log if r["event"] == "refused") == ["message", "verdict-keys", "verdict-size"]


def test_the_callback_counts_a_verdict_holding_a_401_digit_integer():
    # an integer beyond a double in a float key is not valid 2.6: counted, never queued, never raised into rclpy's executor
    vw = _mod("vsswriter")
    fn = _mod("feeder_node")
    upd = _mod("update")
    w, sink, log = _writer()
    q = vw.LatestQueue(vw.QUEUE_MAX)
    cb = fn.make_callback(upd.from_verdict, q, w.refuse, clock=lambda: 5)
    cb(String(_obj(acc=10 ** 400)))
    assert len(q) == 0 and w.counts()["refused"] == {"verdict-value": 1}


def test_the_callback_counts_a_vehicle_message_whose_field_is_an_integer_beyond_a_double():
    # float() of such an integer raises OverflowError inside the builder, an ArithmeticError and no ValueError
    vw = _mod("vsswriter")
    fn = _mod("feeder_node")
    upd = _mod("update")
    w, sink, log = _writer()
    q = vw.LatestQueue(vw.QUEUE_MAX)
    big = 10 ** 400
    for build, msg in ((upd.from_velocity, VelocityReport(big, 0.0, sec=1)), (upd.from_velocity, VelocityReport(0.0, big, sec=1)),
                       (upd.from_steering, SteeringReport(big, sec=1)), (upd.from_accel, AccelWithCovarianceStamped(big, sec=1))):
        fn.make_callback(build, q, w.refuse, clock=lambda: 5)(msg)
    assert len(q) == 0 and w.counts()["refused"] == {"message": 4}


def test_a_message_the_builder_cannot_convert_is_counted_by_the_callback():
    vw = _mod("vsswriter")
    fn = _mod("feeder_node")
    upd = _mod("update")
    w, sink, log = _writer()
    q = vw.LatestQueue(vw.QUEUE_MAX)
    cb = fn.make_callback(upd.from_velocity, q, w.refuse, clock=lambda: 5)
    cb(VelocityReport(None, 0.0, sec=1))                              # float(None): a TypeError
    assert len(q) == 0 and w.counts()["refused"] == {"message": 1}


def test_the_json_log_writes_one_compact_line_per_record_and_flushes_it():
    class Stream(io.StringIO):
        flushes = 0

        def flush(self):
            self.flushes += 1
            super().flush()

    s = Stream()
    log = _mod("vsswriter").JsonLog(s)
    log({"event": "counts", "updates": 1})
    log({"event": "refused", "code": "topic"})
    assert s.getvalue().splitlines() == ['{"event":"counts","updates":1}', '{"code":"topic","event":"refused"}']
    assert s.flushes == 2


# --- feeder_node.py ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [("127.0.0.1:55555", ("127.0.0.1", 55555)), ("127.0.0.2:1", ("127.0.0.2", 1)),
                                       ("[::1]:55555", ("::1", 55555)), ("127.255.255.254:65535", ("127.255.255.254", 65535)),
                                       ("127.0.0.53:55555", ("127.0.0.53", 55555)), ("[0:0:0:0:0:0:0:1]:1", ("::1", 1))])
def test_a_loopback_databroker_is_taken(text, want):
    assert _mod("feeder_node").parse_databroker(text) == want


@pytest.mark.parametrize("text", ["192.0.2.10:55555", "203.0.113.5:55555", "0.0.0.0:55555", "localhost:55555", "[::]:55555",
                                  "::1:55555", "127.0.0.1", "127.0.0.1:", "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:5x",
                                  ":55555", "databroker:55555", "[2001:db8::1]:55555", "127.0.0.1:55555/x", "198.51.100.7:55555",
                                  "[fe80::1]:55555", "127.0.0.1:123456", "[127.0.0.1]:55555x", "127.0.0.1:-1", "[::1%lo]:55555"])
def test_any_other_databroker_is_refused(text):
    with pytest.raises(ValueError):
        _mod("feeder_node").parse_databroker(text)


def test_main_refuses_another_databroker_before_importing_rclpy(monkeypatch, capsys):
    fn = _mod("feeder_node")
    for name in ("rclpy", "rclpy.node", "rclpy.qos", "kuksa_client", "kuksa_client.grpc"):
        monkeypatch.setitem(sys.modules, name, None)          # importing any of these now raises ImportError
    for argv in (["--run-type", "planning-sim", "--databroker", "192.0.2.10:55555"],
                 ["--run-type", "sigsim"], ["--databroker", "127.0.0.1:55555"]):
        with pytest.raises(SystemExit) as err:
            fn.main(argv)
        assert err.value.code == 2, argv
    assert fn.parse_args(["--run-type", "carla-autoware"]).databroker == ("127.0.0.1", 55555)
    assert fn.DEFAULT_DATABROKER == "127.0.0.1:55555"


def test_the_subscriptions_are_2_8s_and_never_the_claim_topic():
    fn = _mod("feeder_node")
    got = {rt: {s[0]: s for s in fn.subscriptions(rt)} for rt in ("planning-sim", "carla-autoware")}
    assert set(got["planning-sim"]) == {VELOCITY, STEERING, GEAR, ACCEL, VERDICT}
    assert set(got["carla-autoware"]) == {VERDICT}
    assert all(CONTROL_CMD not in s[0] for s in fn.SUBSCRIPTIONS)
    assert fn.QOS == {"vehicle": ("BEST_EFFORT", 1), "verdict": ("RELIABLE", 10)}


def _fake_kuksa(served):
    """kuksa_client and kuksa_client.grpc with the names kuksa_out.py takes from kuksa-client 0.6.0."""
    grpc = types.ModuleType("kuksa_client.grpc")

    class DataType(enum.Enum):
        BOOLEAN = 1
        INT8 = 2
        UINT8 = 3
        UINT16 = 4
        UINT32 = 5
        UINT64 = 6
        FLOAT = 7
        DOUBLE = 8

    class Field(enum.Enum):
        VALUE = 1

    class VSSClientError(Exception):
        pass

    class Datapoint:
        def __init__(self, value=None):
            self.value = value

    class Metadata:
        def __init__(self, data_type=None):
            self.data_type = data_type

    class DataEntry:
        def __init__(self, path, value=None, metadata=None):
            self.path, self.value, self.metadata = path, value, metadata

    class EntryUpdate:
        def __init__(self, entry, fields):
            self.entry, self.fields = entry, fields

    class VSSClient:
        instances = []

        def __init__(self, host, port, ensure_startup_connection=True):
            self.host, self.port, self.ensure = host, port, ensure_startup_connection
            self.sets = []
            self.type_calls = []
            self.connected = False
            self.disconnected = False
            VSSClient.instances.append(self)

        def connect(self):
            self.connected = True

        def get_value_types(self, paths, timeout=None, wait_for_ready=None):
            self.type_calls.append((list(paths), timeout, wait_for_ready))
            missing = [p for p in paths if p not in served]
            if missing:
                raise VSSClientError("not found")
            return {p: DataType[served[p].upper()] for p in paths}

        def set(self, updates=None, try_v2=False, timeout=None):
            self.sets.append((list(updates), try_v2, timeout))

        def disconnect(self):
            self.disconnected = True

    for name, obj in (("DataType", DataType), ("Field", Field), ("VSSClientError", VSSClientError), ("Datapoint", Datapoint),
                      ("Metadata", Metadata), ("DataEntry", DataEntry), ("EntryUpdate", EntryUpdate), ("VSSClient", VSSClient)):
        setattr(grpc, name, obj)
    pkg = types.ModuleType("kuksa_client")
    pkg.grpc = grpc
    return {"kuksa_client": pkg, "kuksa_client.grpc": grpc}


def test_kuksa_out_writes_with_set_try_v2_and_the_given_datatypes(monkeypatch):
    m = _mod("mapping")
    mods = _fake_kuksa(dict(m.DATATYPES))
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    ko = _mod("kuksa_out")
    out = ko.KuksaOut("127.0.0.1", 55555)
    client = mods["kuksa_client.grpc"].VSSClient.instances[-1]
    assert (client.host, client.port, client.ensure, client.connected) == ("127.0.0.1", 55555, False, True)
    types_got = out.value_types([SPEED, CTL + "LastSeq", CC + "IsJerkDefined"])
    assert types_got == {SPEED: "float", CTL + "LastSeq": "uint64", CC + "IsJerkDefined": "boolean"}
    assert client.type_calls[-1][1:] == (ko.START_TIMEOUT_S, True)
    out.publish([(SPEED, 9.0, "float"), (CC + "IsJerkDefined", False, "boolean"), (CTL + "LastSeq", 42, "uint64")])
    assert len(client.sets) == 1
    updates, try_v2, timeout = client.sets[0]
    assert try_v2 is True and timeout == ko.WRITE_RPC_TIMEOUT_S
    dt = mods["kuksa_client.grpc"].DataType
    got = [(u.entry.path, u.entry.value.value, u.entry.metadata.data_type, u.fields) for u in updates]
    field = (mods["kuksa_client.grpc"].Field.VALUE,)
    assert got == [(SPEED, 9.0, dt.FLOAT, field), (CC + "IsJerkDefined", False, dt.BOOLEAN, field),
                   (CTL + "LastSeq", 42, dt.UINT64, field)]
    with pytest.raises(ko.KuksaOutError):
        out.value_types(["Vehicle.Not.Served"])
    out.close()
    assert client.disconnected


def test_an_ipv6_loopback_reaches_vssclient_bracketed(monkeypatch):
    m = _mod("mapping")
    mods = _fake_kuksa(dict(m.DATATYPES))
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    _mod("kuksa_out").KuksaOut("::1", 55555)
    assert mods["kuksa_client.grpc"].VSSClient.instances[-1].host == "[::1]"


class FakeRos:
    """rclpy (init, spin, try_shutdown; node.Node; qos; executors) and the three message packages as feeder_node.main
    uses them. spin delivers the given messages to the subscribed callbacks, then waits until `until()` holds, then
    raises KeyboardInterrupt (a Ctrl-C); when try_shutdown is called while it waits (from another thread), it raises
    ExternalShutdownException at once, as rclpy's executor does when the context is shut down under it. init raises
    init_error when one is given."""

    def __init__(self, deliveries, until, init_error=None):
        self.deliveries = deliveries
        self.until = until
        self.init_error = init_error
        self.subs = []
        self.events = []
        self.shut = False
        self.ended_by_shutdown = False

    def modules(self):
        ros = self
        rclpy = types.ModuleType("rclpy")
        node_mod = types.ModuleType("rclpy.node")
        qos = types.ModuleType("rclpy.qos")
        executors = types.ModuleType("rclpy.executors")

        class ExternalShutdownException(Exception):
            pass

        class Node:
            def __init__(self, name):
                ros.events.append(("node", name))
                self.callbacks = {}

            def create_subscription(self, msg_type, topic, callback, qos_profile):
                ros.subs.append((msg_type, topic, qos_profile))
                self.callbacks[topic] = callback

            def destroy_node(self):
                ros.events.append(("destroy",))

        class QoSProfile:
            def __init__(self, depth=None, history=None, reliability=None, durability=None):
                self.depth, self.history, self.reliability, self.durability = depth, history, reliability, durability

        qos.QoSProfile = QoSProfile
        qos.ReliabilityPolicy = enum.Enum("ReliabilityPolicy", "RELIABLE BEST_EFFORT")
        qos.HistoryPolicy = enum.Enum("HistoryPolicy", "KEEP_LAST KEEP_ALL")
        qos.DurabilityPolicy = enum.Enum("DurabilityPolicy", "VOLATILE TRANSIENT_LOCAL")
        executors.ExternalShutdownException = ExternalShutdownException
        node_mod.Node = Node

        def init(args=None):
            ros.events.append(("init",))
            if ros.init_error is not None:
                raise ros.init_error

        def spin(node):
            for topic, msg in ros.deliveries:
                node.callbacks[topic](msg)
            deadline = time.monotonic() + 10
            while not ros.until() and time.monotonic() < deadline:
                if ros.shut:
                    ros.ended_by_shutdown = True
                    raise ExternalShutdownException
                time.sleep(0.01)
            raise KeyboardInterrupt

        def try_shutdown():
            ros.events.append(("shutdown",))
            ros.shut = True

        rclpy.init, rclpy.spin, rclpy.try_shutdown = init, spin, try_shutdown
        rclpy.node, rclpy.qos, rclpy.executors = node_mod, qos, executors
        avm = types.ModuleType("autoware_vehicle_msgs.msg")
        avm.VelocityReport, avm.SteeringReport, avm.GearReport = VelocityReport, SteeringReport, GearReport
        gm = types.ModuleType("geometry_msgs.msg")
        gm.AccelWithCovarianceStamped = AccelWithCovarianceStamped
        sm = types.ModuleType("std_msgs.msg")
        sm.String = String
        out = {"rclpy": rclpy, "rclpy.node": node_mod, "rclpy.qos": qos, "rclpy.executors": executors,
               "autoware_vehicle_msgs.msg": avm, "geometry_msgs.msg": gm, "std_msgs.msg": sm}
        for pkg in ("autoware_vehicle_msgs", "geometry_msgs", "std_msgs"):
            p = types.ModuleType(pkg)
            p.msg = out[pkg + ".msg"]
            out[pkg] = p
        return out


def _run_main(monkeypatch, capsys, run_type, deliveries, served=None, expect_sets=0):
    m = _mod("mapping")
    kuksa = _fake_kuksa(dict(m.DATATYPES) if served is None else served)
    client_cls = kuksa["kuksa_client.grpc"].VSSClient
    client_cls.instances.clear()

    def until():
        return bool(client_cls.instances) and len(client_cls.instances[-1].sets) >= expect_sets

    ros = FakeRos(deliveries, until)
    for name, mod in list(ros.modules().items()) + list(kuksa.items()):
        monkeypatch.setitem(sys.modules, name, mod)
    rc = _mod("feeder_node").main(["--run-type", run_type, "--databroker", "127.0.0.1:55555"])
    out = capsys.readouterr()
    lines = [json.loads(line) for line in out.out.splitlines() if line.strip()]
    return rc, ros, client_cls.instances, lines, out.err


def test_main_subscribes_to_2_8s_topics_with_their_qos_and_writes_what_they_carry(monkeypatch, capsys):
    deliveries = [(VELOCITY, VelocityReport(-2.5, 0.25, sec=1)), (STEERING, SteeringReport(0.125, sec=1)),
                  (GEAR, GearReport(report=GearReport.REVERSE, sec=1)), (ACCEL, AccelWithCovarianceStamped(-1.5, sec=1)),
                  (VERDICT, String(_data(_verdicts()["replied-reject"])))]
    rc, ros, clients, lines, err = _run_main(monkeypatch, capsys, "planning-sim", deliveries, expect_sets=5)
    assert rc == 0, err
    topics = {topic: (msg_type, q) for msg_type, topic, q in ros.subs}
    assert set(topics) == {VELOCITY, STEERING, GEAR, ACCEL, VERDICT} and CONTROL_CMD not in topics
    assert topics[VELOCITY][0] is VelocityReport and topics[GEAR][0] is GearReport
    assert topics[ACCEL][0] is AccelWithCovarianceStamped and topics[VERDICT][0] is String
    for topic, (_t, q) in topics.items():
        if topic == VERDICT:
            assert (q.depth, q.reliability.name, q.history.name) == (10, "RELIABLE", "KEEP_LAST")
        else:
            assert (q.depth, q.reliability.name, q.history.name) == (1, "BEST_EFFORT", "KEEP_LAST")
        assert q.durability.name == "VOLATILE", topic                    # a TRANSIENT_LOCAL subscriber would not match WP2's publisher
    written = {}
    for updates, try_v2, _timeout in clients[-1].sets:
        assert try_v2 is True
        for u in updates:
            written[u.entry.path] = u.entry.value.value
    assert written[CURRENT_GEAR] == -1 and written[LONG_VEL] == -2.5 and written[SPEED] == 9.0
    assert written[ACC_LONG] == -1.5 and written[CTL + "LastSeq"] == 42
    assert lines[0]["event"] == "start" and lines[0]["run_type"] == "planning-sim" and lines[0]["writer"] == "ros-vss-feeder"
    assert lines[-1]["event"] == "counts" and lines[-1]["final"] is True and lines[-1]["updates"] == 5
    assert ("shutdown",) in ros.events and clients[-1].disconnected
    assert ("destroy",) in ros.events


def test_main_in_carla_autoware_subscribes_to_the_verdict_only(monkeypatch, capsys):
    deliveries = [(VERDICT, String(_data(_verdicts()["replied-accept"])))]
    rc, ros, clients, lines, err = _run_main(monkeypatch, capsys, "carla-autoware", deliveries, expect_sets=1)
    assert rc == 0, err
    assert [t for _m, t, _q in ros.subs] == [VERDICT]
    paths = {u.entry.path for updates, _v2, _t in clients[-1].sets for u in updates}
    assert paths and paths <= OVERLAY_PATHS


def test_main_refuses_to_start_when_a_write_set_path_is_not_served(monkeypatch, capsys):
    m = _mod("mapping")
    served = {p: t for p, t in m.DATATYPES.items() if not p.startswith(CC)}
    rc, ros, clients, lines, err = _run_main(monkeypatch, capsys, "carla-autoware", [], served=served)
    assert rc == 2 and ros.subs == [] and "refused" in err
    assert clients[-1].disconnected                                   # the refused start closes the client it opened
    served = dict(m.DATATYPES, **{CTL + "Packed": "uint64"})
    rc, ros, clients, lines, err = _run_main(monkeypatch, capsys, "carla-autoware", [], served=served)
    assert rc == 2 and ros.subs == [] and CTL + "Packed" in err


def _stand_ins(monkeypatch, ros):
    m = _mod("mapping")
    kuksa = _fake_kuksa(dict(m.DATATYPES))
    clients = kuksa["kuksa_client.grpc"].VSSClient.instances
    clients.clear()
    for name, mod in list(ros.modules().items()) + list(kuksa.items()):
        monkeypatch.setitem(sys.modules, name, mod)
    return clients


def test_main_refuses_to_start_when_gear_report_has_two_names_for_one_value(monkeypatch, capsys):
    ros = FakeRos([], lambda: True)
    clients = _stand_ins(monkeypatch, ros)

    class Twice:
        DRIVE = 2
        FORWARD = 2

    monkeypatch.setattr(sys.modules["autoware_vehicle_msgs.msg"], "GearReport", Twice)
    rc = _mod("feeder_node").main(["--run-type", "planning-sim", "--databroker", "127.0.0.1:55555"])
    err = capsys.readouterr().err
    assert rc == 2 and "two constants for one value" in err
    assert clients == [] and ros.subs == [] and ("init",) not in ros.events      # refused before the client opens


def test_main_refuses_to_start_when_the_databroker_client_does_not_open(monkeypatch, capsys):
    ros = FakeRos([], lambda: True)
    _stand_ins(monkeypatch, ros)

    def refuse(self):
        raise ConnectionError("no route for the value 777.25")

    monkeypatch.setattr(sys.modules["kuksa_client.grpc"].VSSClient, "connect", refuse)
    rc = _mod("feeder_node").main(["--run-type", "carla-autoware", "--databroker", "127.0.0.1:55555"])
    err = capsys.readouterr().err
    assert rc == 2 and "did not open: ConnectionError" in err and "777.25" not in err
    assert ros.subs == [] and ("init",) not in ros.events


def test_the_writers_end_ends_spin_and_main_exits_1(monkeypatch, capsys):
    class ClosedPipe(io.StringIO):
        """A stdout as a closed pipe leaves it: the start line goes through, every later line raises."""

        def write(self, s):
            if '"event":"start"' not in s:
                raise BrokenPipeError(32, "Broken pipe")
            return super().write(s)

    # a refused message makes the writer log a line, which kills its thread; spin then ends only when something shuts
    # rclpy down, or after 10 s as a Ctrl-C would end it
    ros = FakeRos([(VERDICT, String("{}")), (VELOCITY, VelocityReport(-2.5, 0.25, sec=1))], lambda: False)
    clients = _stand_ins(monkeypatch, ros)
    out = ClosedPipe()
    saved, sys.stdout = sys.stdout, out
    t0 = time.monotonic()
    try:
        rc = _mod("feeder_node").main(["--run-type", "planning-sim", "--databroker", "127.0.0.1:55555"])
    finally:
        sys.stdout = saved
    took = time.monotonic() - t0
    err = capsys.readouterr().err
    assert rc == 1, err
    assert ros.ended_by_shutdown and took < 5, "spin was not ended by the writer's end (%.1f s)" % took
    assert "BrokenPipeError" in err and "Traceback" not in err                  # the type name only, no traceback
    assert [json.loads(line)["event"] for line in out.getvalue().splitlines()] == ["start"]
    assert not [t for t in threading.enumerate() if t.name == "vss-writer"]
    assert clients[-1].disconnected


def test_main_exits_1_when_the_writer_does_not_stop_in_time(monkeypatch, capsys):
    fn = _mod("feeder_node")
    entered, release = threading.Event(), threading.Event()
    ros = FakeRos([(STEERING, SteeringReport(0.125, sec=1))], entered.is_set)
    clients = _stand_ins(monkeypatch, ros)
    client_cls = sys.modules["kuksa_client.grpc"].VSSClient

    def set_blocking(self, updates=None, try_v2=False, timeout=None):  # a write that outlasts the stop's wait
        entered.set()
        release.wait(20)

    monkeypatch.setattr(client_cls, "set", set_blocking)
    monkeypatch.setattr(fn, "STOP_JOIN_S", 0.2)
    try:
        rc = fn.main(["--run-type", "planning-sim", "--databroker", "127.0.0.1:55555"])
        err = capsys.readouterr().err
    finally:
        release.set()
        for t in threading.enumerate():
            if t.name == "vss-writer":
                t.join(10)
    assert rc == 1 and "did not stop within" in err, err
    assert clients[-1].disconnected


def test_main_logs_its_last_counts_line_when_rclpy_does_not_start(monkeypatch, capsys):
    ros = FakeRos([], lambda: True, init_error=RuntimeError("no context"))
    clients = _stand_ins(monkeypatch, ros)
    with pytest.raises(RuntimeError):
        _mod("feeder_node").main(["--run-type", "carla-autoware", "--databroker", "127.0.0.1:55555"])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [r["event"] for r in lines] == ["start", "counts"] and lines[-1]["final"] is True
    assert ros.subs == [] and clients[-1].disconnected
    assert not [t for t in threading.enumerate() if t.name == "vss-writer"]


# --- imports ----------------------------------------------------------------------------------------------------

THIRD_PARTY_HOMES = {"kuksa_client": "kuksa_out.py", "kuksa": "kuksa_out.py", "grpc": "kuksa_out.py", "rclpy": "feeder_node.py",
                     "std_msgs": "feeder_node.py", "autoware_vehicle_msgs": "feeder_node.py", "geometry_msgs": "feeder_node.py",
                     "kuksa_out": "feeder_node.py"}


def _imports(tree):
    """(top-level module name, inside a function) of every import statement."""
    out = []

    def visit(node, in_func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                out.extend((a.name.split(".")[0], in_func) for a in child.names)
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                out.append((child.module.split(".")[0], in_func))
            visit(child, in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))

    visit(tree, False)
    return out


def test_kuksa_client_rclpy_and_the_messages_are_imported_in_their_one_module_and_inside_functions_only():
    if not hasattr(sys, "stdlib_module_names"):
        pytest.skip("needs Python 3.10 or later (sys.stdlib_module_names)")
    files = sorted(ROSVSS.glob("*.py"))                                # every .py file, WP3b's image tooling included
    assert {name + ".py" for name in MODULES} <= {f.name for f in files}
    siblings = {"update", "mapping", "vsswriter"}
    for f in files:
        for name, in_func in _imports(ast.parse(f.read_text(encoding="utf-8"))):
            if name in sys.stdlib_module_names or name == "__future__" or name in siblings:
                continue
            assert name in THIRD_PARTY_HOMES, (f.name, name)
            assert THIRD_PARTY_HOMES[name] == f.name, "%s imports %s" % (f.name, name)
            assert in_func, "%s imports %s at module level" % (f.name, name)
    # importlib.import_module of a message package: only in feeder_node.py
    for f in files:
        if f.name != "feeder_node.py":
            assert "import_module" not in f.read_text(encoding="utf-8"), f.name


BLOCKER = r'''
import sys
BLOCKED = ("rclpy", "std_msgs", "autoware_vehicle_msgs", "geometry_msgs", "kuksa_client", "kuksa", "grpc", "google")
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("blocked by the test: " + name)
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, sys.argv[1])
import update, mapping, vsswriter, feeder_node, kuksa_out
print("imported:", sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED))
'''


def test_the_package_imports_with_ros_and_kuksa_client_absent():
    r = subprocess.run([sys.executable, "-I", "-B", "-c", BLOCKER, str(ROSVSS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "imported: []"
