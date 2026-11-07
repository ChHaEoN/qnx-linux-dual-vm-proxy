"""D22's steering shim (sdv/steershim: steershim.py, shim_node.py, README.md): SDV plan Phase 8 WP9b 10.3, spec-2
sections 2.10, 10.3 and 10.4.

What is tested, and how. rclpy, the message packages, Autoware, CARLA and its interface are stand-ins in every test:
nothing here needs ROS installed, a container, a GPU or any network.

- steershim.py's pure functions: C is read by path from sdv/sim/carla010_iso.py (never imported, never held here or in
  the package), and a C that is not one finite number literal in (0, 90), or that any other statement binds in the
  module's namespace as well (a tuple or for target, a nested block, an import, a def or class), is refused; the
  inverse is s* = sign(delta) x min(1, sqrt(|delta_deg| / C)), turned into the CARLA steer that turns the taxi by delta
  (positive right, W9 E18) and
  then into the field value the interface's command conversion turns into that steer, with its sign and its clip at
  full steer; the forward takes the raw report back to the steer the interface applied and reports C x s x |s| in
  radians, positive left, never linear in s; forward after the interface after the inverse gives the command back
  within rounding (and within binary32's when the report is rounded to the message's float32); a non-finite value, and
  a raw report beyond what a full steer gives, are refused; a message is copied whole with only its steer field
  replaced, the input left as it was.
- the interface's constants (its two conversions, the actuation message's type and its steer field) are READ at the
  pinned commit (WP9, 94b8fbd3), each marked on its line, and STAND_INS is empty; the guard stays: shim_node.main refuses
  to start while STAND_INS names any of the four, before rclpy is imported, and the tree as it stands passes that check
  and goes on to import rclpy; a conversion that is zero or not finite is refused too.
- shim_node.py: with stand-ins for rclpy and the two message packages in sys.modules, main subscribes and publishes on
  exactly 2.10's four topics with the two types and this package's QoS, makes the node without parameter services and
  without the context's global arguments, gives rclpy.init the program's name alone, refuses at start a steer field
  the message types lack or hold as no float, turns each message as the pure functions do, publishes the report only
  while the graph shows exactly one publisher on /vehicle/status/steering_status, this node, and keeps no state (each
  output equal to 2.10's formulas computed here for its message alone, in every order; no place in either source to
  keep a message); rclpy and the message packages are imported inside main only, and the package imports with ROS
  absent.
- the package: its three files, no module name shared with another module CI type-checks beside it, no bytecode left
  beside steershim.py by a run of shim_node.py from a writable tree, no claim-path topic and no module of the claim path
  in its sources, and the README's statements (a project node in Autoware's actuation path, what it changes, what the
  publisher guard can see, what rclpy adds on its own, what it does not show).

Every number asserted here is a design value, a constant of the module, a synthetic input, or computed from them; C is
never written in this file: it is read from carla010_iso.py, where it is PROBED (W9 E9) and held once more in
tests/test_sdv_carla010.py. W9's READ max_steer_angle, which the two conversions carry, stands in EXPECTED_READ alone.

What this does NOT show: that the shim runs with the real rclpy and message packages in the shim's own Jazzy container from the
interface's image; that the interface's conversions hold on the real taxi (READ at the pinned commit, given
max_wheel_steer_angle_deg absent and the flat curve; a run's publisher checks read the flattening); that the taxi turns
by Autoware's command (the law is INFERRED, W9 E9; 5a's runs show it or not); that Autoware drives better with it; any
timing.
"""
import ast
import enum
import importlib
import itertools
import math
import re
import shutil
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SHIM_DIR = REPO / "sdv" / "steershim"
SIM_DIR = REPO / "sdv" / "sim"
ISO = SIM_DIR / "carla010_iso.py"
README = SHIM_DIR / "README.md"

# 2.10's four topics, written out here (not the module's constants).
IN_ACTUATION = "/control/command/actuation_cmd"
OUT_ACTUATION = "/sdv/steershim/actuation_cmd"
IN_REPORT = "/sdv/steershim/steering_status_raw"
OUT_REPORT = "/vehicle/status/steering_status"
# The claim path and the topics 2.10 says the shim never touches.
CLAIM_TOPICS = ("/control/command/control_cmd", "/localization/kinematic_state", "/qnx_monitor/verdict", "/diagnostics")
CLAIM_MODULES = {"ctlclient", "ctlframe", "ctlrules", "ctl_claim_node", "ctl_export", "ctlreplay", "ctlsynth", "aw_scenario",
                 "vssframe", "kind4_client", "update", "mapping", "vsswriter", "feeder_node", "kuksa_out"}
ROS_MODULES = ("rclpy", "tier4_vehicle_msgs", "autoware_vehicle_msgs", "autoware_control_msgs", "std_msgs", "builtin_interfaces")
# The interface's side of 2.10 as WP9 read it at the pinned commit: none is a stand-in any more (the interface maps the steer
# linearly, s = -delta / max_steer_angle, and reports s x max_steer_angle, given max_wheel_steer_angle_deg absent, the wheels'
# max_steer_angle as W9 section 5 reads it, and the flat curve; CARLA's steer positive right against the messages' positive
# left). That READ angle is written on the module's two conversion lines and in EXPECTED_READ alone (spec-2 14).
PIN = "94b8fbd3"
STAND_INS = ()
# The four constants of the interface's side, whatever their state: this tuple stays with STAND_INS empty, so a constant that
# leaves STAND_INS in both places while its line still says STAND-IN (or is read while the module still lists it) is found, and
# the refusal below stays tested with no constant a stand-in.
INTERFACE_CONSTANTS = ("ACTUATION_TYPE", "ACTUATION_STEER", "CMD_STEER_PER_FIELD", "REPORT_RAD_PER_STEER")
EXPECTED_READ = {"ACTUATION_TYPE": ("tier4_vehicle_msgs.msg", "ActuationCommandStamped"),
                 "ACTUATION_STEER": ("actuation", "steer_cmd"),
                 "CMD_STEER_PER_FIELD": -1.0 / math.radians(70.0),
                 "REPORT_RAD_PER_STEER": -math.radians(70.0)}
# READ (W4 M5): Autoware's steering report, autoware_vehicle_msgs/msg/SteeringReport, float32 steering_tire_angle [rad,
# positive left].
REPORT_TYPE = ("autoware_vehicle_msgs.msg", "SteeringReport")
REPORT_STEER = ("steering_tire_angle",)


def _import(name, directory):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def sh():
    return _import("steershim", SHIM_DIR)


@pytest.fixture(scope="module")
def node():
    return _import("shim_node", SHIM_DIR)


@pytest.fixture(scope="module")
def iso():
    return _import("carla010_iso", SIM_DIR)


def _f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _c_pattern(c):
    """C's literal as carla010_iso.py writes it, as a pattern that matches it alone (not inside a longer number)."""
    return re.compile(r"(?<![\d.])%s(?![\d])" % re.escape(repr(c)))


# --- message stand-ins on rosidl_generator_py's pattern: slots, a no-argument constructor with defaults, and the class's
# get_fields_and_field_types(); equality field by field.

class _Msg:
    __slots__: tuple = ()
    _FIELDS: tuple = ()

    def __init__(self, **kwargs):
        for name in self._FIELDS:
            setattr(self, name, kwargs.pop(name, self._default(name)))
        assert not kwargs, kwargs

    def _default(self, name):
        return 0.0

    @classmethod
    def get_fields_and_field_types(cls):
        return {name: "stand-in" for name in cls._FIELDS}

    def __eq__(self, other):
        return type(self) is type(other) and all(getattr(self, n) == getattr(other, n) for n in self._FIELDS)

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % (n, getattr(self, n)) for n in self._FIELDS))


class Time(_Msg):
    __slots__ = _FIELDS = ("sec", "nanosec")

    def _default(self, name):
        return 0


class Header(_Msg):
    __slots__ = _FIELDS = ("stamp", "frame_id")

    def _default(self, name):
        return Time() if name == "stamp" else ""


class ActuationCommand(_Msg):
    __slots__ = _FIELDS = ("accel_cmd", "brake_cmd", "steer_cmd")


class ActuationCommandStamped(_Msg):
    __slots__ = _FIELDS = ("header", "actuation")

    def _default(self, name):
        return Header() if name == "header" else ActuationCommand()


class SteeringReport(_Msg):
    __slots__ = _FIELDS = ("stamp", "steering_tire_angle")

    def _default(self, name):
        return Time() if name == "stamp" else 0.0


class ActuationCommandPlus(_Msg):
    """A command with a field more on each level: whatever the pinned commit's type carries is copied."""
    __slots__ = _FIELDS = ("accel_cmd", "brake_cmd", "steer_cmd", "spare")


class ActuationCommandStampedPlus(_Msg):
    __slots__ = _FIELDS = ("header", "actuation", "status")

    def _default(self, name):
        return Header() if name == "header" else ActuationCommandPlus() if name == "actuation" else 0


def _command(steer, accel=0.25, brake=0.5, sec=12, nanosec=345, frame_id="base_link"):
    return ActuationCommandStamped(header=Header(stamp=Time(sec=sec, nanosec=nanosec), frame_id=frame_id),
                                   actuation=ActuationCommand(accel_cmd=accel, brake_cmd=brake, steer_cmd=steer))


def _report(angle, sec=7, nanosec=89):
    return SteeringReport(stamp=Time(sec=sec, nanosec=nanosec), steering_tire_angle=angle)


def _snapshot(msg):
    """The message's values, nested, so a change to the input after a call is seen."""
    if isinstance(msg, _Msg):
        return tuple((n, _snapshot(getattr(msg, n))) for n in msg._FIELDS)
    return msg


def _no_stand_ins(monkeypatch, sh):
    monkeypatch.setattr(sh, "STAND_INS", ())


# =================================================================================================================
# C, read by path from carla010_iso.py (spec-2 2.10, 10.3)
# =================================================================================================================

def test_c_is_read_by_path_from_carla010_iso_and_equals_its_c(sh, iso):
    assert sh.CARLA010_ISO == ISO
    assert sh.load_c(sh.CARLA010_ISO) == iso.C


def test_c_is_written_nowhere_in_the_package_or_in_this_file(iso):
    """carla010_iso.py holds C (PROBED) and tests/test_sdv_carla010.py once more; the shim reads it, so a re-read
    changes those two places and nothing here."""
    pat = _c_pattern(iso.C)
    for f in sorted(SHIM_DIR.glob("*")) + [Path(__file__)]:
        if f.is_file():
            assert not pat.search(f.read_text(encoding="utf-8")), f.name


def test_the_package_never_imports_carla010_iso(sh):
    for f in sorted(SHIM_DIR.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not {x for x in names if "carla010_iso" in x}, f.name


def test_load_c_follows_the_file_it_is_given(sh, tmp_path, iso):
    text = ISO.read_text(encoding="utf-8")
    assert len(re.findall(r"^C = ", text, re.M)) == 1
    other = tmp_path / "carla010_iso.py"
    other.write_text(re.sub(r"^C = .*$", "C = 50.0", text, flags=re.M), encoding="utf-8")
    assert sh.load_c(other) == 50.0 != iso.C


@pytest.mark.parametrize("body", [
    "D = 1.0\n",                                    # no C
    "C = 50.0\nC = 51.0\n",                         # two
    "C: float = 50.0\nC = 50.0\n",                  # two, one annotated
    "C = 50.0\nC += 1.0\n",                         # changed after
    "C = '50.0'\n",                                 # not a number
    "C = True\n",                                   # not a number
    "C = 25.0 * 2\n",                               # not one literal
    "C = 0.0\n",                                    # not in (0, 90)
    "C = -50.0\n",
    "C = 90.0\n",
    "C = 1e400\n",                                  # not finite
    "C = (\n",                                      # not Python
    "class K:\n    C = 50.0\n",                     # no module-level C
    "C = None\n",                                   # not a number
    "C = [50.0]\n",                                 # not a number
], ids=["none", "twice", "annotated-twice", "augmented", "string", "bool", "expression", "zero", "negative", "ninety",
        "infinite", "syntax", "class-only", "none-value", "list"])
def test_load_c_refuses_anything_but_one_finite_literal_in_0_to_90(sh, tmp_path, body):
    p = tmp_path / "iso.py"
    p.write_text('"""doc"""\nimport math\n' + body, encoding="utf-8")
    with pytest.raises(sh.ShimError):
        sh.load_c(p)


# Every other statement that binds (or unbinds) C in the module's namespace counts against the one assignment: a plain
# C = 45.0 that one of these rebinds is refused, and so is a C bound only by one of them.
@pytest.mark.parametrize("body", [
    "C = 45.0\nC, D = 1.0, 2.0\n",                  # a tuple target
    "C = 45.0\nfor C in (1.0,):\n    pass\n",       # a for target
    "C = 45.0\nif True:\n    C = 1.0\n",            # an assignment in a nested block
    "C = 45.0\nfrom math import pi as C\n",         # an import alias
    "C = 45.0\ndef C():\n    return 1.0\n",         # a def name
    "C = 45.0\nclass C:\n    pass\n",               # a class name
    "C = 45.0\nimport C\n",                         # an import
    "C = 45.0\nfrom math import *\n",               # a star import, which may bind it
    "C = 45.0\nwith open(__file__) as C:\n    pass\n",
    "C = 45.0\ntry:\n    pass\nexcept ValueError as C:\n    pass\n",
    "C = 45.0\nwhile False:\n    C = 1.0\nelse:\n    pass\n",
    "C = 45.0\n(C := 1.0)\n",                       # a walrus
    "C = 45.0\nX = [(C := k) for k in (1.0,)]\n",   # a walrus in a comprehension binds in the module
    "C = 45.0\ndef f():\n    global C\n    C = 1.0\n",
    "C = 45.0\ndel C\n",
    "C = 45.0\nmatch 1.0:\n    case C:\n        pass\n",
    "if True:\n    C = 45.0\n",                     # only in a nested block: not a plain module-level assignment
    "C, = (45.0,)\n",                               # only unpacked
    "for C in (45.0,):\n    pass\n",
], ids=["tuple", "for", "if", "import-as", "def", "class", "import", "star-import", "with-as", "except-as", "while",
        "walrus", "walrus-in-comprehension", "global", "del", "match-capture", "if-only", "unpack-only", "for-only"])
def test_load_c_refuses_a_c_that_another_module_level_binding_rebinds(sh, tmp_path, body):
    p = tmp_path / "iso.py"
    p.write_text('"""doc"""\nimport math\n' + body, encoding="utf-8")
    with pytest.raises(sh.ShimError):
        sh.load_c(p)


def test_load_c_takes_an_annotated_c_and_ignores_a_c_inside_a_function(sh, tmp_path):
    p = tmp_path / "iso.py"
    p.write_text("C: float = 42.5\n\ndef f():\n    C = 3.0\n    return C\n", encoding="utf-8")
    assert sh.load_c(p) == 42.5


def test_load_c_ignores_the_names_c_that_bind_in_scopes_of_their_own(sh, tmp_path):
    """A comprehension's loop variable, a parameter, a function's or a class's own C, an attribute and a keyword do not
    bind C in the module; the one plain assignment is taken."""
    p = tmp_path / "iso.py"
    p.write_text("C = 42.5\nX = [C for C in range(3)]\nY = {C: 1 for C in 'ab'}\nZ = dict(C=1.0)\n\n\ndef f(C=3.0):\n"
                 "    C = 4.0\n    return C\n\n\nclass K:\n    C = 2.0\n\n\nL = lambda C: C\nK.C = 5.0\n", encoding="utf-8")
    assert sh.load_c(p) == 42.5


def test_load_c_refuses_a_missing_file(sh, tmp_path):
    with pytest.raises(sh.ShimError):
        sh.load_c(tmp_path / "absent.py")


# =================================================================================================================
# The inverse (2.10): s* = sign(delta) x min(1, sqrt(|delta_deg| / C)), then the field the interface turns into it
# =================================================================================================================

@pytest.mark.parametrize("delta_deg", [0.0, 0.5, 2.5, 10.0, 30.0, -0.5, -2.5, -10.0, -30.0])
def test_s_star_is_2_10s_formula(sh, iso, delta_deg):
    c = iso.C
    assert sh.s_star(delta_deg, c) == math.copysign(min(1.0, math.sqrt(abs(delta_deg) / c)), delta_deg)


@pytest.mark.parametrize("delta_deg", [0.5, 2.5, 10.0, 20.0, 40.0])
def test_the_inverse_keeps_the_sign_left_command_left_turn(sh, iso, delta_deg):
    """A left command (the field positive, the messages' convention) becomes a negative CARLA steer (CARLA's steer is
    positive right, W9 E18), and the law then gives back the command: the taxi turns by delta."""
    c = iso.C
    left, right = sh.inverse(math.radians(delta_deg), c), sh.inverse(math.radians(-delta_deg), c)
    assert left == -right and left != 0.0
    s_left = sh.interface_steer(left)
    assert s_left < 0 < sh.interface_steer(right)
    assert iso.delta_iso_deg(s_left) == pytest.approx(delta_deg, rel=1e-12)
    assert iso.delta_iso_deg(sh.interface_steer(right)) == pytest.approx(-delta_deg, rel=1e-12)


def test_the_inverse_is_the_field_whose_interface_steer_is_minus_s_star(sh, iso):
    c = iso.C
    for delta_deg in (1.0, 7.5, -7.5, 45.0):
        f = sh.inverse(math.radians(delta_deg), c)
        assert sh.interface_steer(f) == pytest.approx(-sh.s_star(delta_deg, c), rel=1e-12)
        assert f == pytest.approx(-sh.s_star(delta_deg, c) / sh.CMD_STEER_PER_FIELD, rel=1e-12)


@pytest.mark.parametrize("delta_rad", [1.05, 1.2, 1.5707963, 3.0, 1e6, -1.05, -1.2, -3.0, -1e6])
def test_the_inverse_clips_at_full_steer_beyond_c(sh, iso, delta_rad):
    c = iso.C
    if abs(math.degrees(delta_rad)) <= c:
        pytest.skip("inside C: not a clip case")
    s = sh.interface_steer(sh.inverse(delta_rad, c))
    assert abs(s) == pytest.approx(1.0, abs=1e-15) and math.copysign(1.0, s) == -math.copysign(1.0, delta_rad)


def test_the_inverse_at_exactly_c_is_full_steer_and_just_inside_is_not(sh, iso):
    c = iso.C
    assert abs(sh.interface_steer(sh.inverse(math.radians(c), c))) == pytest.approx(1.0, abs=1e-15)
    assert abs(sh.interface_steer(sh.inverse(math.radians(c * 0.99), c))) < 1.0


def test_a_zero_command_gives_a_zero_field(sh, iso):
    assert sh.inverse(0.0, iso.C) == 0.0 and sh.inverse(-0.0, iso.C) == 0.0


def test_the_inverse_is_not_the_interfaces_linear_map(sh, iso):
    """Without the shim the interface would steer delta / max_steer_angle (10.4's left column); the inverse sends the
    square root instead, so a small command gets a larger steer."""
    c = iso.C
    f_in = math.radians(5.0)
    s = sh.interface_steer(sh.inverse(f_in, c))
    assert abs(s) == pytest.approx(math.sqrt(5.0 / c), rel=1e-12)
    assert abs(s) != pytest.approx(abs(sh.interface_steer(f_in)), rel=1e-3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "0.1", None, True])
def test_the_inverse_refuses_a_value_that_is_not_a_finite_number(sh, iso, bad):
    with pytest.raises(sh.ShimError):
        sh.inverse(bad, iso.C)


# =================================================================================================================
# The forward (2.10): the raw report gives back the steer the interface applied; the shim reports C x s x |s|
# =================================================================================================================

@pytest.mark.parametrize("s", [0.05, 0.1, 0.25, 0.5, 0.8, 1.0, -0.05, -0.25, -0.5, -1.0])
def test_the_forward_reports_c_s_abs_s_in_radians_positive_left(sh, iso, s):
    c = iso.C
    raw = sh.interface_report(s)
    out = sh.forward(raw, c)
    assert out == pytest.approx(math.radians(-(c * s * abs(s))), rel=1e-12)
    assert out == pytest.approx(math.radians(iso.delta_iso_deg(s)), rel=1e-12)
    assert (out < 0) == (s > 0)              # a right steer (positive in CARLA) is a negative angle in the message


@pytest.mark.parametrize("s", [0.1, 0.25, 0.5, 0.8])
def test_the_forward_is_neither_linear_in_s_nor_the_raw_report(sh, iso, s):
    c = iso.C
    raw = sh.interface_report(s)
    out = sh.forward(raw, c)
    assert out != pytest.approx(raw, rel=1e-3)
    assert abs(out) != pytest.approx(math.radians(c * s), rel=1e-3)
    assert abs(out) != pytest.approx(abs(sh.REPORT_RAD_PER_STEER) * s, rel=1e-3)


def test_the_forward_of_a_zero_report_is_zero(sh, iso):
    assert sh.forward(0.0, iso.C) == 0.0


def test_the_forward_takes_a_binary32_rounded_full_steer_and_refuses_beyond_it(sh, iso):
    c = iso.C
    for s in (1.0, -1.0):
        raw = _f32(sh.interface_report(s))
        assert sh.forward(raw, c) == pytest.approx(math.radians(-(c * s)), rel=1e-6)
        assert abs(sh.forward(raw, c)) <= math.radians(c)
    for s in (1.001, -1.001, 2.0, 1.0 + 3e-6, -1.0 - 3e-6):
        with pytest.raises(sh.ShimError):
            sh.forward(sh.interface_report(s), c)


@pytest.mark.parametrize("s", [1.0 + 5e-7, -1.0 - 5e-7, 1.0 + 1e-12])
def test_a_raw_report_within_rounding_beyond_full_steer_is_full_lock_exactly(sh, iso, s):
    """Within STEER_ROUND_TOL of a full steer the steer is clipped to 1 before the law, so the report never exceeds the
    law's full lock."""
    c = iso.C
    assert sh.forward(sh.interface_report(s), c) == math.radians(-(c * math.copysign(1.0, s)))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "0.1", None, False])
def test_the_forward_refuses_a_value_that_is_not_a_finite_number(sh, iso, bad):
    with pytest.raises(sh.ShimError):
        sh.forward(bad, iso.C)


# =================================================================================================================
# Forward and inverse are inverse within rounding, through the interface's two conversions
# =================================================================================================================

def _loop(sh, f_in, c, round_report=False):
    raw = sh.interface_report(sh.interface_steer(sh.inverse(f_in, c)))
    return sh.forward(_f32(raw) if round_report else raw, c)


@pytest.mark.parametrize("delta_deg", [0.0, 0.3, 1.0, 2.5, 5.0, 15.0, 30.0, 45.0, 57.3, -0.3, -2.5, -15.0, -45.0, -57.3])
def test_forward_after_the_interface_after_the_inverse_gives_the_command_back(sh, iso, delta_deg):
    c = iso.C
    f_in = math.radians(delta_deg)
    assert _loop(sh, f_in, c) == pytest.approx(f_in, rel=1e-12, abs=1e-15)
    assert _loop(sh, f_in, c, round_report=True) == pytest.approx(f_in, rel=1e-6, abs=1e-9)


@pytest.mark.parametrize("factor", [1.015, 1.25, 2.0, -1.015, -2.0])
def test_beyond_c_the_loop_reports_full_lock_with_the_commands_sign(sh, iso, factor):
    """The command is a factor of C beyond it, so a re-probe of C moves the case with it."""
    c = iso.C
    out = _loop(sh, math.radians(factor * c), c)
    assert out == pytest.approx(math.copysign(math.radians(c), factor), rel=1e-12)


# =================================================================================================================
# The interface's constants: READ at the pinned commit (WP9); the node still refuses to start on any stand-in
# =================================================================================================================

def _assignment_lines(path):
    """name -> the source line of its one module-level assignment, with the comment lines right above it."""
    lines = path.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines))
    out = {}
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        for t in targets:
            if isinstance(t, ast.Name):
                k = n.lineno - 1
                above = []
                j = k - 1
                while j >= 0 and lines[j].lstrip().startswith("#"):
                    above.insert(0, lines[j])
                    j -= 1
                assert t.id not in out, "%s assigned twice" % t.id
                out[t.id] = "\n".join(above + lines[k:n.end_lineno])
    return out


def test_the_interfaces_constants_are_the_values_read_at_the_pin_each_marked_on_its_line(sh):
    assert sh.STAND_INS == STAND_INS == ()
    for name, value in EXPECTED_READ.items():
        got = getattr(sh, name)
        if isinstance(value, float):
            assert got == pytest.approx(value, rel=1e-15), name
        else:
            assert got == value, name
    src = _assignment_lines(SHIM_DIR / "steershim.py")
    for name in INTERFACE_CONSTANTS:
        if name in sh.STAND_INS:
            assert "STAND-IN" in src[name] and "WP9" in src[name] and "READ (WP9" not in src[name], name
        else:
            assert "READ (WP9, %s)" % PIN in src[name] and "STAND-IN" not in src[name], name
    for name in ("REPORT_TYPE", "REPORT_STEER"):
        assert "READ (W4 M5" in src[name] and "STAND-IN" not in src[name], name
    assert (sh.REPORT_TYPE, sh.REPORT_STEER) == (REPORT_TYPE, REPORT_STEER)


def test_every_interface_constant_is_either_a_stand_in_or_read_from_wp9(sh):
    src = _assignment_lines(SHIM_DIR / "steershim.py")
    for name in INTERFACE_CONSTANTS:
        assert ("STAND-IN" in src[name]) == (name in sh.STAND_INS), name
        assert ("READ (WP9" in src[name]) == (name not in sh.STAND_INS), name


def test_the_start_check_passes_on_the_tree_as_it_stands(sh):
    assert sh.start_problems() == []


def test_the_start_check_names_every_stand_in(sh, monkeypatch):
    monkeypatch.setattr(sh, "STAND_INS", INTERFACE_CONSTANTS)
    problems = sh.start_problems()
    assert len(problems) == len(INTERFACE_CONSTANTS)
    for name in INTERFACE_CONSTANTS:
        assert [p for p in problems if name in p and "stand-in" in p], name


def test_the_start_check_passes_once_wp9_has_read_every_constant(sh, monkeypatch):
    _no_stand_ins(monkeypatch, sh)
    assert sh.start_problems() == []


@pytest.mark.parametrize("name", ["CMD_STEER_PER_FIELD", "REPORT_RAD_PER_STEER"])
@pytest.mark.parametrize("bad", [0.0, float("nan"), float("inf")])
def test_the_start_check_refuses_a_conversion_that_is_zero_or_not_finite(sh, monkeypatch, name, bad):
    _no_stand_ins(monkeypatch, sh)
    monkeypatch.setattr(sh, name, bad)
    problems = sh.start_problems()
    assert problems and all(name in p for p in problems)


class RosImports:
    """A meta-path hook that refuses (and records) every import of a ROS module."""

    def __init__(self):
        self.tried = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ROS_MODULES:
            self.tried.append(name)
            raise ImportError("blocked by the test: " + name)
        return None


def _without_ros(monkeypatch):
    for name in list(sys.modules):
        if name.split(".")[0] in ROS_MODULES:
            monkeypatch.delitem(sys.modules, name, raising=False)
    hook = RosImports()
    monkeypatch.setattr(sys, "meta_path", [hook] + sys.meta_path)
    return hook


@pytest.mark.parametrize("name", INTERFACE_CONSTANTS)
def test_the_node_refuses_to_start_while_any_constant_is_a_stand_in_before_importing_rclpy(sh, node, monkeypatch, capsys, name):
    monkeypatch.setattr(sh, "STAND_INS", (name,))
    hook = _without_ros(monkeypatch)
    rc = node.main([])
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and name in err
    assert hook.tried == []


def test_the_tree_as_it_stands_passes_the_start_check_and_is_refused_at_the_blocked_import(node, monkeypatch, capsys):
    """STAND_INS empty: main goes past the start check and C, and on to import rclpy, which the hook blocks (2.7)."""
    hook = _without_ros(monkeypatch)
    assert node.main([]) == 2 and hook.tried
    err = capsys.readouterr().err
    assert "rclpy or a message package cannot be imported" in err and "stand-in" not in err
    assert not any(name in err for name in INTERFACE_CONSTANTS)


def test_the_node_refuses_a_c_it_cannot_read_before_importing_rclpy(sh, node, monkeypatch, capsys, tmp_path):
    _no_stand_ins(monkeypatch, sh)
    monkeypatch.setattr(sh, "CARLA010_ISO", tmp_path / "absent.py")
    hook = _without_ros(monkeypatch)
    assert node.main([]) == 2 and hook.tried == []
    assert "refused" in capsys.readouterr().err


def test_the_node_refuses_when_rclpy_or_a_message_package_cannot_be_imported(sh, node, monkeypatch, capsys):
    _no_stand_ins(monkeypatch, sh)
    hook = _without_ros(monkeypatch)
    assert node.main([]) == 2 and hook.tried
    err = capsys.readouterr().err
    assert "refused" in err and "Traceback" not in err


def test_the_node_takes_no_argument(node, monkeypatch):
    _without_ros(monkeypatch)
    with pytest.raises(SystemExit) as e:
        node.main(["--ros-args", "-r", "%s:=/elsewhere" % OUT_REPORT])
    assert e.value.code == 2


# =================================================================================================================
# Topics, types and QoS (2.10)
# =================================================================================================================

def test_the_four_topics_are_2_10s_word_for_word(sh):
    assert (sh.IN_ACTUATION, sh.OUT_ACTUATION, sh.IN_REPORT, sh.OUT_REPORT) == (IN_ACTUATION, OUT_ACTUATION, IN_REPORT, OUT_REPORT)
    assert sh.TOPICS == (IN_ACTUATION, OUT_ACTUATION, IN_REPORT, OUT_REPORT)
    assert sh.IN_REPORT != sh.OUT_REPORT and sh.IN_ACTUATION != sh.OUT_ACTUATION
    assert sh.OUT_ACTUATION.startswith("/sdv/steershim/") and sh.IN_REPORT.startswith("/sdv/steershim/")


def test_no_source_names_a_claim_path_topic_or_imports_a_module_of_the_claim_path():
    for f in sorted(SHIM_DIR.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for topic in CLAIM_TOPICS:
            assert topic not in text, (f.name, topic)
        tree = ast.parse(text)
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not names & CLAIM_MODULES, (f.name, names & CLAIM_MODULES)


class _Info:
    def __init__(self, node_name, node_namespace="/"):
        self.node_name, self.node_namespace = node_name, node_namespace


NOT_CALLED = object()


class FakeRos:
    """rclpy (init, spin, try_shutdown; node.Node with publishers, subscriptions, a logger and the graph's publisher
    infos; qos; executors) and the two message packages as shim_node.main uses them. spin delivers the given (topic,
    message) pairs to the subscribed callbacks in order, then raises KeyboardInterrupt (a Ctrl-C). `others` are the
    publishers besides the shim that the graph shows on each topic. init_args holds what rclpy.init was given and
    node_kwargs the keyword arguments the Node was made with (NOT_CALLED until then)."""

    def __init__(self, deliveries, others=None):
        self.deliveries = deliveries
        self.others = others or {}
        self.subs = []
        self.pubs = []
        self.published = []
        self.logged = []
        self.events = []
        self.timers = []
        self.init_args = NOT_CALLED
        self.node_kwargs = NOT_CALLED

    def modules(self):
        ros = self
        rclpy = types.ModuleType("rclpy")
        node_mod = types.ModuleType("rclpy.node")
        qos = types.ModuleType("rclpy.qos")
        executors = types.ModuleType("rclpy.executors")

        class ExternalShutdownException(Exception):
            pass

        class Publisher:
            def __init__(self, topic):
                self.topic = topic

            def publish(self, msg):
                ros.published.append((self.topic, msg))

        class Logger:
            def error(self, text, **kwargs):
                ros.logged.append(("error", text))

            def warning(self, text, **kwargs):
                ros.logged.append(("warning", text))

            def info(self, text, **kwargs):
                ros.logged.append(("info", text))

        class Node:
            def __init__(self, name, **kwargs):
                ros.node_kwargs = dict(kwargs)
                ros.events.append(("node", name))
                self.name = name
                self.callbacks = {}

            def get_name(self):
                return self.name

            def get_namespace(self):
                return "/"

            def create_publisher(self, msg_type, topic, qos_profile):
                ros.pubs.append((msg_type, topic, qos_profile))
                return Publisher(topic)

            def create_subscription(self, msg_type, topic, callback, qos_profile):
                ros.subs.append((msg_type, topic, qos_profile))
                self.callbacks[topic] = callback

            def create_timer(self, *args, **kwargs):
                ros.timers.append(args)

            def get_publishers_info_by_topic(self, topic):
                own = [_Info(self.name)] if any(t == topic for _m, t, _q in ros.pubs) else []
                return own + [_Info(n) for n in ros.others.get(topic, ())]

            def get_logger(self):
                return Logger()

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
            ros.init_args = args
            ros.events.append(("init",))

        def spin(n):
            for topic, msg in ros.deliveries:
                n.callbacks[topic](msg)
            raise KeyboardInterrupt

        def try_shutdown():
            ros.events.append(("shutdown",))

        rclpy.init, rclpy.spin, rclpy.try_shutdown = init, spin, try_shutdown
        rclpy.node, rclpy.qos, rclpy.executors = node_mod, qos, executors
        t4 = types.ModuleType("tier4_vehicle_msgs.msg")
        t4.ActuationCommandStamped = ActuationCommandStamped
        avm = types.ModuleType("autoware_vehicle_msgs.msg")
        avm.SteeringReport = SteeringReport
        out = {"rclpy": rclpy, "rclpy.node": node_mod, "rclpy.qos": qos, "rclpy.executors": executors,
               "tier4_vehicle_msgs.msg": t4, "autoware_vehicle_msgs.msg": avm}
        for pkg in ("tier4_vehicle_msgs", "autoware_vehicle_msgs"):
            p = types.ModuleType(pkg)
            p.msg = out[pkg + ".msg"]
            out[pkg] = p
        return out


def _run_main(sh, node, monkeypatch, deliveries, others=None, iso_path=None):
    _no_stand_ins(monkeypatch, sh)
    if iso_path is not None:
        monkeypatch.setattr(sh, "CARLA010_ISO", iso_path)
    ros = FakeRos(deliveries, others)
    for name, mod in ros.modules().items():
        monkeypatch.setitem(sys.modules, name, mod)
    rc = node.main([])
    return rc, ros


def test_main_subscribes_and_publishes_exactly_2_10s_four_topics_with_their_types_and_qos(sh, node, monkeypatch):
    rc, ros = _run_main(sh, node, monkeypatch, [])
    assert rc == 0
    assert [(m, t) for m, t, _q in ros.subs] == [(ActuationCommandStamped, IN_ACTUATION), (SteeringReport, IN_REPORT)]
    assert [(m, t) for m, t, _q in ros.pubs] == [(ActuationCommandStamped, OUT_ACTUATION), (SteeringReport, OUT_REPORT)]
    for _m, _t, q in ros.subs:
        assert (q.reliability.name, q.history.name, q.depth, q.durability.name) == ("BEST_EFFORT", "KEEP_LAST", 1, "VOLATILE")
    for _m, _t, q in ros.pubs:
        assert (q.reliability.name, q.history.name, q.depth, q.durability.name) == ("RELIABLE", "KEEP_LAST", 1, "VOLATILE")
    assert ros.timers == []
    assert ros.events[:2] == [("init",), ("node", "sdv_steershim")] and ros.events[-2:] == [("destroy",), ("shutdown",)]
    # no parameter services, and no remap or parameter of the context's global arguments (rclpy's Node defaults both on)
    assert ros.node_kwargs == {"start_parameter_services": False, "use_global_arguments": False}


def test_rclpy_init_is_given_the_programs_name_alone_and_never_the_ros_arguments_on_sys_argv(sh, node, monkeypatch):
    """rclpy.init(args=None) would take sys.argv, and its --ros-args (a remap of 2.10's topics) would reach rcl: main
    passes the program's name alone, whatever sys.argv holds, and the node ignores the context's global arguments."""
    monkeypatch.setattr(sys, "argv", ["shim_node.py", "--ros-args", "-r", OUT_REPORT + ":=/elsewhere", "-p", "use_sim_time:=true"])
    rc, ros = _run_main(sh, node, monkeypatch, [])
    assert rc == 0 and ros.init_args == ["shim_node.py"]
    assert ros.node_kwargs["use_global_arguments"] is False


def test_rclpy_init_gets_an_empty_list_when_sys_argv_is_empty(sh, node, monkeypatch):
    monkeypatch.setattr(sys, "argv", [])
    rc, ros = _run_main(sh, node, monkeypatch, [])
    assert rc == 0 and ros.init_args == []


def test_a_spin_ended_by_rclpys_shutdown_exception_ends_with_exit_0_after_destroy_and_shutdown(sh, node, monkeypatch):
    """rclpy's handling of SIGTERM and SIGINT (a docker stop) ends spin in ExternalShutdownException, not in a
    KeyboardInterrupt: the node is destroyed, rclpy shut down and the exit status is 0, which WP9's harness relies on."""
    _no_stand_ins(monkeypatch, sh)
    ros = FakeRos([])
    mods = ros.modules()

    def spin(_node):
        raise mods["rclpy.executors"].ExternalShutdownException()
    mods["rclpy"].spin = spin
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    assert node.main([]) == 0
    assert ros.events[-2:] == [("destroy",), ("shutdown",)]


def test_a_message_module_without_its_class_is_refused_at_start_before_rclpy_init(sh, node, monkeypatch, capsys):
    """A READ ACTUATION_TYPE with a class name the module lacks (an AttributeError at the import) is a refusal with exit 2,
    as a module that cannot be imported is, not a traceback."""
    _no_stand_ins(monkeypatch, sh)
    ros = FakeRos([])
    mods = ros.modules()
    del mods["tier4_vehicle_msgs.msg"].ActuationCommandStamped
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    assert node.main([]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "Traceback" not in err and ("init",) not in ros.events


@pytest.mark.parametrize("which, path", [
    ("ACTUATION_STEER", ("actuation", "steer")),        # a field the type lacks
    ("ACTUATION_STEER", ("command", "steer_cmd")),
    ("ACTUATION_STEER", ("actuation",)),                # a nested message, not a float
    ("ACTUATION_STEER", ("header", "frame_id")),        # a string
    ("REPORT_STEER", ("steering_angle",)),
    ("REPORT_STEER", ("stamp",)),
    ("REPORT_STEER", ("stamp", "sec")),                 # an integer
], ids=["act-missing", "act-missing-outer", "act-message", "act-string", "rep-missing", "rep-message", "rep-int"])
def test_a_steer_field_the_pinned_type_lacks_or_holds_as_no_float_is_refused_at_start(sh, node, monkeypatch, capsys, which, path):
    """A READ value mistyped is found once, at the start, before rclpy.init: exit 2, not an error line per message."""
    monkeypatch.setattr(sh, which, path)
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_ACTUATION, _command(0.1)), (IN_REPORT, _report(sh.interface_report(0.1)))])
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and path[-1] in err and "Traceback" not in err
    assert ("init",) not in ros.events and ros.published == [] and ros.logged == []


def test_check_steer_field_takes_the_stand_in_types_steer_and_refuses_a_path_they_lack(sh):
    sh.check_steer_field(ActuationCommandStamped, ("actuation", "steer_cmd"))
    sh.check_steer_field(SteeringReport, ("steering_tire_angle",))
    for msg_type, path in ((ActuationCommandStamped, ("actuation", "steer")), (ActuationCommandStamped, ("header",)),
                           (SteeringReport, ("stamp", "nanosec")), (SteeringReport, ())):
        with pytest.raises(sh.ShimError):
            sh.check_steer_field(msg_type, path)


def test_main_turns_each_message_as_the_pure_functions_do(sh, node, iso, monkeypatch):
    c = iso.C
    cmd, rep = _command(math.radians(8.0)), _report(sh.interface_report(-0.3))
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_ACTUATION, cmd), (IN_REPORT, rep)])
    assert rc == 0 and [t for t, _m in ros.published] == [OUT_ACTUATION, OUT_REPORT]
    out_cmd, out_rep = ros.published[0][1], ros.published[1][1]
    assert out_cmd.actuation.steer_cmd == sh.inverse(math.radians(8.0), c)
    assert out_rep.steering_tire_angle == sh.forward(sh.interface_report(-0.3), c)
    assert ros.logged == [] or all(level == "info" for level, _t in ros.logged)


def test_main_reads_c_from_the_file_at_carla010_iso(sh, node, monkeypatch, tmp_path):
    other = tmp_path / "carla010_iso.py"
    other.write_text(re.sub(r"^C = .*$", "C = 50.0", ISO.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
    rep = _report(sh.interface_report(0.5))
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_REPORT, rep)], iso_path=other)
    assert rc == 0 and ros.published[0][1].steering_tire_angle == pytest.approx(math.radians(-(50.0 * 0.25)), rel=1e-12)


def test_the_report_is_not_published_while_another_node_publishes_steering_status(sh, node, monkeypatch):
    """A raw report arrives while another node publishes on /vehicle/status/steering_status (a second interface whose
    report is not remapped, or a planning simulator left running): two publishers there, so the shim publishes no
    report and logs the other."""
    rep = _report(sh.interface_report(0.2))
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_REPORT, rep), (IN_ACTUATION, _command(0.05))],
                        others={OUT_REPORT: ("carla_ros_interface",)})
    assert rc == 0 and [t for t, _m in ros.published] == [OUT_ACTUATION]
    errors = [t for level, t in ros.logged if level == "error"]
    assert len(errors) == 1 and OUT_REPORT in errors[0] and "carla_ros_interface" in errors[0]


def test_a_publisher_on_another_topic_does_not_stop_the_report(sh, node, monkeypatch):
    rep = _report(sh.interface_report(0.2))
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_REPORT, rep)], others={IN_REPORT: ("carla_ros_interface",)})
    assert rc == 0 and [t for t, _m in ros.published] == [OUT_REPORT]


def test_a_second_shim_of_the_same_name_and_namespace_stops_the_report(sh, node, monkeypatch):
    """Two sdv_steershim processes in / (a retried start that left the first alive): the graph shows two publishers on
    /vehicle/status/steering_status, both of this node's name, which is spec-2 13's 'two publishers on steering_status':
    no report is published, and the error line gives the count."""
    rep = _report(sh.interface_report(0.2))
    rc, ros = _run_main(sh, node, monkeypatch, [(IN_REPORT, rep), (IN_ACTUATION, _command(0.05))],
                        others={OUT_REPORT: ("sdv_steershim",)})
    assert rc == 0 and [t for t, _m in ros.published] == [OUT_ACTUATION]
    errors = [t for level, t in ros.logged if level == "error"]
    assert len(errors) == 1 and OUT_REPORT in errors[0] and " 2 " in errors[0]


@pytest.mark.parametrize("names", [(), ("sdv_steershim", "sdv_steershim"), ("sdv_steershim", "sdv_steershim", "sdv_steershim")],
                         ids=["none-yet", "two-of-this-name", "three-of-this-name"])
def test_the_report_callback_publishes_only_while_the_graph_shows_exactly_one_publisher_this_node(sh, node, iso, names):
    """Exactly one publisher on /vehicle/status/steering_status, this node: none (discovery not yet showing the shim's own
    publisher) only delays the report, and more than one, of whatever name, stops it; each refusal is one error line
    with the count."""
    _on_act, on_rep, sent, logged = _callbacks(sh, node, iso.C, infos=[_Info(n) for n in names])
    on_rep(_report(sh.interface_report(0.1)))
    assert sent == [] and len(logged) == 1 and OUT_REPORT in logged[0] and " %d " % len(names) in logged[0]
    _on_act, on_rep, sent, logged = _callbacks(sh, node, iso.C, infos=[_Info("sdv_steershim")])
    on_rep(_report(sh.interface_report(0.1)))
    assert [t for t, _m in sent] == [OUT_REPORT] and logged == []


def test_the_report_callback_asks_the_graph_once_per_report(sh, node, iso):
    asked = []

    def publishers():
        asked.append(1)
        return [_Info("sdv_steershim")]
    on_act, on_rep = node.make_callbacks(iso.C, lambda m: None, lambda m: None, publishers, "sdv_steershim", "/", lambda t: None)
    on_rep(_report(sh.interface_report(0.1)))
    on_act(_command(0.1))
    on_rep(_report(sh.interface_report(0.2)))
    assert len(asked) == 2


def test_other_publishers_names_every_publisher_but_this_node(sh):
    infos = [_Info("sdv_steershim"), _Info("sdv_steershim", "/elsewhere"), _Info("simple_planning_simulator", "/simulation")]
    assert sh.other_publishers(infos, "sdv_steershim", "/") == ["/elsewhere/sdv_steershim", "/simulation/simple_planning_simulator"]
    assert sh.other_publishers([_Info("sdv_steershim")], "sdv_steershim", "/") == []
    assert sh.other_publishers([], "sdv_steershim", "/") == []
    assert sh.other_publishers([_Info("sdv_steershim", "")], "sdv_steershim", "/") == []         # an empty namespace is the root
    assert sh.other_publishers([_Info("x", "/ns/")], "sdv_steershim", "/") == ["/ns/x"]          # a trailing slash is dropped
    assert sh.other_publishers([_Info("sdv_steershim", "/a")], "sdv_steershim", "/a/") == []     # this node, its namespace given with one


# =================================================================================================================
# Only the steer changes (2.10: every other field and the stamps copied unchanged)
# =================================================================================================================

def _callbacks(sh, node, c, others=(), infos=None):
    """The two callbacks with recording stand-ins; the graph shows the shim and `others` on the report topic, or `infos`
    exactly when given."""
    sent, logged = [], []
    graph = list(infos) if infos is not None else [_Info("sdv_steershim")] + [_Info(n) for n in others]
    on_act, on_rep = node.make_callbacks(c, lambda m: sent.append((OUT_ACTUATION, m)), lambda m: sent.append((OUT_REPORT, m)),
                                         lambda: list(graph), "sdv_steershim", "/", logged.append)
    return on_act, on_rep, sent, logged


def test_the_actuation_command_changes_only_its_steer_and_the_input_is_left_as_it_was(sh, node, iso):
    c = iso.C
    on_act, _on_rep, sent, logged = _callbacks(sh, node, c)
    cmd = _command(math.radians(-6.0), accel=0.375, brake=0.125, sec=1700000000, nanosec=999999999, frame_id="base_link")
    before = _snapshot(cmd)
    on_act(cmd)
    assert _snapshot(cmd) == before and logged == []
    [(topic, out)] = sent
    assert topic == OUT_ACTUATION and out is not cmd and out.actuation is not cmd.actuation
    assert type(out) is ActuationCommandStamped and type(out.actuation) is ActuationCommand
    assert out.header == cmd.header and out.header.stamp == Time(sec=1700000000, nanosec=999999999)
    assert out.header.frame_id == "base_link"
    assert (out.actuation.accel_cmd, out.actuation.brake_cmd) == (0.375, 0.125)
    assert out.actuation.steer_cmd == sh.inverse(math.radians(-6.0), c) != cmd.actuation.steer_cmd


def test_the_steering_report_changes_only_its_angle_and_the_input_is_left_as_it_was(sh, node, iso):
    c = iso.C
    _on_act, on_rep, sent, logged = _callbacks(sh, node, c)
    rep = _report(_f32(sh.interface_report(0.4)), sec=42, nanosec=7)
    before = _snapshot(rep)
    on_rep(rep)
    assert _snapshot(rep) == before and logged == []
    [(topic, out)] = sent
    assert topic == OUT_REPORT and out is not rep and type(out) is SteeringReport
    assert out.stamp == Time(sec=42, nanosec=7)
    assert out.steering_tire_angle == sh.forward(rep.steering_tire_angle, c) != rep.steering_tire_angle


def test_every_field_the_pinned_type_carries_is_copied(sh):
    cmd = ActuationCommandStampedPlus(header=Header(stamp=Time(sec=3, nanosec=4), frame_id="x"),
                                      actuation=ActuationCommandPlus(accel_cmd=0.5, brake_cmd=0.25, steer_cmd=0.1, spare=9.0),
                                      status=5)
    before = _snapshot(cmd)
    out = sh.with_field(cmd, ("actuation", "steer_cmd"), -0.2)
    assert _snapshot(cmd) == before
    assert out.status == 5 and out.header == cmd.header and out.actuation.spare == 9.0
    assert (out.actuation.accel_cmd, out.actuation.brake_cmd, out.actuation.steer_cmd) == (0.5, 0.25, -0.2)


@pytest.mark.parametrize("path", [("actuation", "steering"), ("command", "steer_cmd"), ("header", "stamp", "secs"), ()])
def test_with_field_refuses_a_path_the_message_does_not_have(sh, path):
    with pytest.raises(sh.ShimError):
        sh.with_field(_command(0.1), path, 0.0)


def test_field_of_reads_the_steer_at_its_path(sh):
    assert sh.field_of(_command(0.125), ("actuation", "steer_cmd")) == 0.125
    assert sh.field_of(_report(-0.5), ("steering_tire_angle",)) == -0.5
    with pytest.raises(sh.ShimError):
        sh.field_of(_report(-0.5), ("angle",))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_message_whose_steer_is_not_finite_is_refused_logged_and_not_published(sh, node, iso, bad):
    on_act, on_rep, sent, logged = _callbacks(sh, node, iso.C)
    on_act(_command(bad))
    on_rep(_report(bad))
    assert sent == [] and len(logged) == 2 and all("refused" in t for t in logged)


def test_a_raw_report_beyond_full_steer_is_refused_logged_and_not_published(sh, node, iso):
    _on_act, on_rep, sent, logged = _callbacks(sh, node, iso.C)
    on_rep(_report(sh.interface_report(1.5)))
    assert sent == [] and len(logged) == 1 and "refused" in logged[0]


def test_the_report_callback_publishes_nothing_while_another_publisher_is_on_steering_status(sh, node, iso):
    _on_act, on_rep, sent, logged = _callbacks(sh, node, iso.C, others=("simple_planning_simulator",))
    on_rep(_report(sh.interface_report(0.1)))
    assert sent == [] and len(logged) == 1 and OUT_REPORT in logged[0] and "simple_planning_simulator" in logged[0]


# =================================================================================================================
# No state (10.3: one message at a time)
# =================================================================================================================

def _replaced(snap, path, value):
    """A message snapshot with the value at path (field names, outermost first) replaced."""
    return tuple((n, (value if len(path) == 1 else _replaced(v, path[1:], value)) if n == path[0] else v) for n, v in snap)


def _alone(sh, m, c):
    """What the shim must send for m alone, computed here from 2.10's formulas and the module's constants, never through
    the shim's callbacks or functions, so state kept by either module cannot reach this side: m's values with the steer
    replaced, each operation in the order the module performs it (so equal to the last bit)."""
    if isinstance(m, ActuationCommandStamped):
        deg = math.degrees(m.actuation.steer_cmd)
        steer = -math.copysign(min(1.0, math.sqrt(abs(deg) / c)), deg) / sh.CMD_STEER_PER_FIELD
        return _replaced(_snapshot(m), ("actuation", "steer_cmd"), steer)
    s = max(-1.0, min(1.0, m.steering_tire_angle / sh.REPORT_RAD_PER_STEER))
    return _replaced(_snapshot(m), ("steering_tire_angle",), math.radians(-(c * s * abs(s))))


def test_the_shim_keeps_no_state_each_output_depends_on_its_message_alone(sh, node, iso):
    """Every output, in every order the messages come in, equals what 2.10's formulas give for its message alone. The
    expected side is computed apart from the shim (a baseline taken through fresh callbacks of the same module would
    carry the same module-level state as the run it is compared with)."""
    c = iso.C
    cmds = [_command(math.radians(d), sec=k) for k, d in enumerate((3.0, -12.0, 0.0, 40.0, 75.0))]
    reps = [_report(sh.interface_report(s), sec=k) for k, s in enumerate((0.2, -0.7, 0.0, 1.0))]
    alone = {id(m): _alone(sh, m, c) for m in cmds + reps}
    for order in itertools.islice(itertools.permutations(cmds + reps), 0, 2000, 97):
        on_act, on_rep, sent, _logged = _callbacks(sh, node, c)
        for m in order:
            (on_act if isinstance(m, ActuationCommandStamped) else on_rep)(m)
        assert [_snapshot(out) for _t, out in sent] == [alone[id(m)] for m in order]


# What may not appear in either module, as a place to keep something between messages: a module-level value that is a
# mutable container, or is made by a call that makes one; a mutable default argument; a caching decorator.
MUTABLE_NODES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)
MUTABLE_CALLS = {"list", "dict", "set", "bytearray", "deque", "defaultdict", "OrderedDict", "Counter", "ChainMap", "count", "cycle",
                 "array", "Queue", "SimpleQueue", "LifoQueue", "PriorityQueue", "WeakSet", "WeakKeyDictionary",
                 "WeakValueDictionary", "SimpleNamespace"}
CACHE_DECORATORS = {"lru_cache", "cache", "cached_property"}


def _called(node):
    """The name a call or decorator calls (its last attribute), or ''."""
    f = node.func if isinstance(node, ast.Call) else node
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _mutable(value):
    if isinstance(value, ast.Tuple):
        return any(_mutable(e) for e in value.elts)
    return isinstance(value, MUTABLE_NODES) or (isinstance(value, ast.Call) and _called(value) in MUTABLE_CALLS)


def _module_scope(tree):
    """Every node of the module's own scope: its statements, their nested blocks and expressions, not a def's, lambda's
    or class's body."""
    stack = list(tree.body)
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


def _state_places(tree):
    """(what, line) for each place a module's source could keep something between messages: a global or nonlocal
    statement; a module-level value that is a mutable container or is made by a call that makes one; a mutable default
    argument; a caching decorator; an attribute assigned or deleted inside a function (a message kept on a module, a
    function or an object)."""
    out = [("a global or nonlocal statement", n.lineno) for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))]
    out += [("a module-level mutable value", n.lineno) for n in _module_scope(tree)
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and n.value is not None and _mutable(n.value)]
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
    out += [("a mutable default argument", d.lineno) for n in funcs for d in n.args.defaults + [k for k in n.args.kw_defaults if k]
            if _mutable(d)]
    out += [("a caching decorator", d.lineno) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for d in n.decorator_list if _called(d) in CACHE_DECORATORS]
    out += [("an attribute assigned inside a function", a.lineno) for n in funcs for a in ast.walk(n)
            if isinstance(a, ast.Attribute) and not isinstance(a.ctx, ast.Load)]
    return out


def test_the_callbacks_hold_no_mutable_container(sh, node, iso):
    on_act, on_rep, _sent, _logged = _callbacks(sh, node, iso.C)
    for cb in (on_act, on_rep):
        for cell in cb.__closure__ or ():
            assert not isinstance(cell.cell_contents, (list, dict, set, bytearray)), cell.cell_contents
    for f in sorted(SHIM_DIR.glob("*.py")):
        assert _state_places(ast.parse(f.read_text(encoding="utf-8"))) == [], f.name
    # the node sets no attribute at all and reaches no namespace by its dictionary (steershim.with_field sets the fields of
    # the new message it returns, and start_problems reads its own constants)
    tree = ast.parse((SHIM_DIR / "shim_node.py").read_text(encoding="utf-8"))
    assert not [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and _called(n) in ("setattr", "delattr", "vars", "globals")]
    assert not [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "__dict__"]


@pytest.mark.parametrize("source", [
    "_N: List[int] = [0]\n",
    "_SEEN = []\n",
    "_LAST = {}\n",
    "_Q = collections.deque(maxlen=1)\n",
    "_K = itertools.count()\n",
    "_P = (1, [0])\n",
    "if True:\n    _S = set()\n",
    "def f(msg, seen=[]):\n    return msg\n",
    "@functools.lru_cache(maxsize=None)\ndef f(x):\n    return x\n",
    "def f(msg):\n    f.last = msg\n",
    "def f(msg, *, seen={}):\n    return msg\n",
    "def f(msg):\n    global _LAST\n    _LAST = msg\n",
], ids=["annotated-list", "list", "dict", "deque", "count", "tuple-holding-a-list", "nested-set", "default", "lru-cache",
        "function-attribute", "keyword-default", "global"])
def test_the_no_state_check_sees_each_place_to_keep_a_message(source):
    """The check above, on synthetic module sources: each would let a module keep something between messages."""
    assert _state_places(ast.parse(source))


def test_the_no_state_check_takes_immutable_module_values():
    source = ('HERE = Path(__file__).resolve().parent\nTOPICS = ("/a", "/b")\nLIMITS = (0.0, 90.0)\nK = -1.0 / math.radians(2.0)\n'
              'Callback = Callable[[Any], None]\nsys.dont_write_bytecode = True\n\n\ndef f(x, y=None, z=(1, 2)):\n    return [x]\n')
    assert _state_places(ast.parse(source)) == []


# =================================================================================================================
# Imports and the package
# =================================================================================================================

def _imports(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, n) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.append((n.module, n))
    return out


def test_rclpy_and_the_message_packages_are_imported_inside_main_only():
    tree = ast.parse((SHIM_DIR / "shim_node.py").read_text(encoding="utf-8"))
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(mains) == 1
    inside = {id(n) for n in ast.walk(mains[0])}
    ros = [(name, n) for name, n in _imports(tree) if name.split(".")[0] in ROS_MODULES]
    assert ros and all(id(n) in inside for _name, n in ros)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "import_module"]
    assert calls and all(id(n) in inside for n in calls)


def test_steershim_uses_the_standard_library_alone():
    if not hasattr(sys, "stdlib_module_names"):
        pytest.skip("needs Python 3.10 or later (sys.stdlib_module_names)")
    tree = ast.parse((SHIM_DIR / "steershim.py").read_text(encoding="utf-8"))
    mods = {name.split(".")[0] for name, _n in _imports(tree)}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("import_module", "__import__")]


def test_shim_node_imports_the_standard_library_steershim_and_ros_alone():
    if not hasattr(sys, "stdlib_module_names"):
        pytest.skip("needs Python 3.10 or later (sys.stdlib_module_names)")
    tree = ast.parse((SHIM_DIR / "shim_node.py").read_text(encoding="utf-8"))
    mods = {name.split(".")[0] for name, _n in _imports(tree)}
    assert mods <= set(sys.stdlib_module_names) | {"__future__", "steershim"} | set(ROS_MODULES), mods


BLOCKER = r'''
import sys
BLOCKED = %r
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("blocked by the test: " + name)
        return None
sys.meta_path.insert(0, Block())
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import steershim, shim_node
print("imported:", sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED or m == "carla010_iso"))
''' % (ROS_MODULES,)


def test_the_package_imports_with_ros_absent():
    r = subprocess.run([sys.executable, "-I", "-B", "-c", BLOCKER, str(SHIM_DIR)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "imported: []"


def test_a_run_of_shim_node_from_a_writable_tree_leaves_no_bytecode_beside_steershim(tmp_path):
    """The tree is mounted read-only in the container, and a run from a writable one must leave it as it was: -I ignores
    PYTHONDONTWRITEBYTECODE, so only the script's own sys.dont_write_bytecode stops the __pycache__. The copy has no
    carla010_iso.py beside it, so the run ends in a refusal (exit 2) before rclpy is imported, whatever the stand-ins."""
    tree = tmp_path / "sdv" / "steershim"
    shutil.copytree(SHIM_DIR, tree, ignore=shutil.ignore_patterns("__pycache__"))
    r = subprocess.run([sys.executable, "-I", str(tree / "shim_node.py")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "refused" in r.stderr, r.stderr
    assert not list(tmp_path.rglob("__pycache__"))


def test_the_package_holds_its_three_files_and_no_package_marker():
    names = sorted(p.name for p in SHIM_DIR.iterdir() if p.name != "__pycache__")
    assert names == ["README.md", "shim_node.py", "steershim.py"]
    assert not list(SHIM_DIR.rglob("__pycache__"))


def test_no_module_here_shares_a_name_with_a_module_ci_type_checks_beside_it():
    """ci-2.sh type-checks sdv/steershim together with these directories and stops on two top-level modules of one
    name; without a package marker every module here is top-level, so each has a name of its own."""
    mine = {p.stem for p in SHIM_DIR.glob("*.py")}
    others = set()
    for d in ("scripts/ci", "scripts/aws", "scripts/twin", "tests", "sdv/connector", "sdv/cloud", "sdv/ota", "sdv/carla",
              "sdv/feeder", "sdv/ctl", "sdv/rosvss", "sdv/drill", "sdv/arm64", "sdv/sim"):
        if (REPO / d).is_dir():
            others |= {p.stem for p in (REPO / d).rglob("*.py")}
    assert mine == {"steershim", "shim_node"} and not (mine & others), mine & others


# =================================================================================================================
# The README (10.3, 10.4)
# =================================================================================================================

def _readme():
    return re.sub(r"\s+", " ", README.read_text(encoding="utf-8"))


def test_the_readme_says_a_project_node_sits_in_autowares_actuation_path_and_what_it_changes():
    text = _readme()
    assert "a project node sits in autoware's actuation path" in text.lower()
    for topic in (IN_ACTUATION, OUT_ACTUATION, IN_REPORT, OUT_REPORT):
        assert "`%s`" % topic in text, topic
    for phrase in ("only the steer", "no recalibration", "sign(delta) x min(1, sqrt(|delta_deg| / C))", "C x s x |s|",
                   "sdv/sim/carla010_iso.py", "READ (WP9, %s)" % PIN, "refuses to start", "the owner's call"):
        assert phrase in text, phrase
    for topic in CLAIM_TOPICS[:3]:
        assert "`%s`" % topic in text, topic


def test_the_readme_compares_the_two_columns_of_10_4_and_says_what_it_does_not_show():
    text = _readme()
    assert "without the shim" in text and "with the shim" in text
    assert "`s x max_steer_angle`" in text and "`C x (delta / max_steer_angle)^2`" in text
    tail = text[text.lower().index("what this does not demonstrate"):]
    for phrase in ("stand-ins", "5a", "timing"):
        assert phrase in tail, phrase


LAG_SENTENCE = ("the interface applies the command through a first-order lag (`tau` 0.2 s) after the gain, so the inverse holds at "
                "steady state and Autoware's commanded angle reaches the taxi through a lag that is not first-order in the angle; the "
                "same filter sits in the path without the shim; the shim does not model it and `steershim.py` does not change.")


def test_the_readme_holds_the_lag_sentence_in_its_run_section_word_for_word():
    """2.7: the sentence 2.10's text and every 8.5 record take; here in the section that says how the node runs."""
    text = _readme()
    section = text[text.index("## How it runs (WP9)"):text.index("## What the shim changes")]
    assert LAG_SENTENCE.lower() in section.lower()


def test_the_run_section_and_the_node_put_the_shim_in_a_container_of_its_own_from_the_interfaces_image():
    """Item 4: not inside the interface's process container. The README's list of what it does not show says the same."""
    text = _readme()
    section = text[text.index("## How it runs (WP9)"):text.index("## What the shim changes")]
    for where, part in (("README.md, how it runs", section), ("shim_node.py", _node_doc())):
        assert "of its own from the interface's image" in part, where
    tail = text[text.lower().index("what this does not demonstrate"):]
    assert "in the shim's own container from the interface's image" in tail
    assert "in the interface's container" not in text


def test_the_readme_says_a_conversion_that_is_no_fixed_gain_is_a_failed_publisher_check_never_a_shim_change():
    text = _readme()
    assert "is a failed publisher check" in text and "never a shim change" in text
    assert "must not run until the specification says" not in text


def test_the_texts_say_the_constants_are_read_and_no_longer_wait_for_wp9():
    """2.7 and P1's row: the sentences of the node's docstring that waited for WP9, and the module's and the README's."""
    module = re.sub(r"\s+", " ", ast.get_docstring(ast.parse((SHIM_DIR / "steershim.py").read_text(encoding="utf-8"))) or "")
    for where, text in (("README.md", _readme()), ("shim_node.py", _node_doc()), ("steershim.py", module)):
        for stale in ("stand-ins until WP9", "WP9's to read at the pin", "WP9 reads it at the pin", "until WP9 reads", "STAND-IN until",
                      "until then the node", "as the stand-ins say"):
            assert stale not in text, (where, stale)
        assert "94b8fbd3" in text, where
    for where, text in (("README.md", _readme()), ("steershim.py", module)):
        assert "max_wheel_steer_angle_deg" in text and "flat" in text, where


def test_the_readme_says_there_is_no_recalibration_in_a_sentence_of_its_own():
    """'no recalibration' is also the 10.4 row of D22's letter: the statement is the sentence that begins it."""
    assert "There is no recalibration:" in _readme()


def test_the_readme_holds_every_row_of_10_4():
    text = _readme()
    for label in ("**Code**", "**The interface's launch**", "**What Autoware's steering report says**",
                  "**The angle the taxi turns at Autoware's command delta**", "**Kind 2's rule 17 on honest curves**",
                  "**Kind 4**", "**D22's letter, no recalibration first**"):
        assert label in text, label


def _node_doc():
    return re.sub(r"\s+", " ", ast.get_docstring(ast.parse((SHIM_DIR / "shim_node.py").read_text(encoding="utf-8"))) or "")


def test_the_readme_and_the_node_say_what_the_publisher_guard_can_see():
    """The guard is asked when a raw report arrives; an interface whose report is not remapped sends none, so the shim
    never hears of it, and WP9's publisher checks catch it. Neither text may say the guard catches that case."""
    for where, text in (("README.md", _readme()), ("shim_node.py", _node_doc())):
        assert "means the interface's report is not remapped" not in text, where
        for phrase in ("exactly one publisher", "only when a raw report arrives", "WP9's publisher checks"):
            assert phrase in text, (where, phrase)


def test_the_readme_and_the_node_say_what_rclpy_adds_on_its_own():
    """No timer, no service and no parameter of the shim's own; rclpy's Node adds /rosout, /parameter_events and the
    use_sim_time parameter whatever the node asks, which the texts say rather than deny."""
    for where, text in (("README.md", _readme()), ("shim_node.py", _node_doc())):
        assert "no timer, no service and no parameter of its own" in text, where
        for name in ("/rosout", "/parameter_events", "use_sim_time"):
            assert name in text, (where, name)
        assert "nothing else" not in text and "no service, no parameter" not in text, where


def test_the_conversions_angle_is_written_only_on_its_two_lines(sh):
    """W9's READ max_steer_angle, which the two conversions carry, is a READ value: spec-2 14 puts it on its lines alone, here
    the module's two conversion lines and EXPECTED_READ. The README, the node and every other line name it."""
    figure = "%d" % round(math.degrees(abs(sh.REPORT_RAD_PER_STEER)))
    pat = re.compile(r"(?<![\d.])%s(?![\d])" % figure)
    for f in (README, SHIM_DIR / "shim_node.py"):
        assert not pat.search(f.read_text(encoding="utf-8")), f.name
    text = (SHIM_DIR / "steershim.py").read_text(encoding="utf-8")
    lines = _assignment_lines(SHIM_DIR / "steershim.py")
    for name in ("CMD_STEER_PER_FIELD", "REPORT_RAD_PER_STEER"):
        assert pat.search(lines[name]), name
        text = text.replace(lines[name], "")
    assert not pat.search(text), "steershim.py outside its two conversion lines"
    own = Path(__file__).read_text(encoding="utf-8")
    expected = _assignment_lines(Path(__file__))["EXPECTED_READ"]
    assert pat.search(expected) and not pat.search(own.replace(expected, "")), Path(__file__).name


def test_the_files_are_lf_and_ascii():
    for f in sorted(SHIM_DIR.glob("*")) + [Path(__file__)]:
        if f.is_file():
            data = f.read_bytes()
            assert b"\r" not in data and all(b < 128 for b in data), f.name
