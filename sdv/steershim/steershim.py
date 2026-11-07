"""steershim.py -- D22's steering shim between Autoware and CARLA 0.10.0's interface: the pure functions, one message at
a time, no state (sdv/steershim).

Phase 8 WP9b's steering shim, under the owner's D22 of 2026-10-18: Autoware's steering goes to the taxi through
the inverse of carla010_iso.py's steering model, and Autoware's controller is not recalibrated. shim_node.py is the
rclpy node around these functions. README.md says where it sits and what it changes.

    TOPICS (2.10)
    /control/command/actuation_cmd        Autoware's converter -> the shim (the interface no longer subscribes to it)
    /sdv/steershim/actuation_cmd          the shim -> the interface (remapped at the interface's launch)
    /sdv/steershim/steering_status_raw    the interface (remapped) -> the shim, SteeringReport
    /vehicle/status/steering_status       the shim -> Autoware, SteeringReport

    THE TWO DIRECTIONS (2.10), C read by path from sdv/sim/carla010_iso.py, where it is PROBED (W9 E9)
    inverse  the actuation command's steer field carries Autoware's commanded tire angle delta [rad, positive left];
             s* = sign(delta) x min(1, sqrt(|delta_deg| / C)) is the size of steer whose angle by the law is delta,
             clipped at full steer; CARLA's steer is positive right (W9 E18), so the steer that turns the taxi by delta
             is -s*; the shim sends the field value that the interface's own command conversion turns into that steer.
    forward  the interface's raw report gives back the steer s it applied (by its own synthesis, with the flattened
             curve); the shim reports the law's angle C x s x |s| in radians with the message's sign (positive left),
             that is -(C x s x |s|) in degrees as carla010_iso.delta_iso_deg has it, turned into radians.
    Every other field of each message, the stamps among them, is copied unchanged.

    THE INTERFACE'S SIDE
    Its two conversions (each a gain, sign included: the interface maps and reports the steer linearly, W9 section 8)
    and the actuation message's type and steer field are constants below, each READ by WP9 at the pinned commit (D2,
    94b8fbd3), given max_wheel_steer_angle_deg absent from the interface's launch and its flat steering curve. STAND_INS
    names any that is not READ, none now, and shim_node refuses to start while it names any, or while a steer field path
    is one the imported message type lacks or holds as no float (check_steer_field). Autoware's steering report is READ
    (W4 M5).

DOES NOT SHOW: that the real taxi's wheels and curve are what the two conversions are given (a conversion that is no fixed
gain is a failed publisher check of the run, never a change here); that the taxi turns by Autoware's command (the law is
INFERRED, W9 E9, and 5a's runs show it or not); anything about a speed-dependent steering curve, which the flattened
curve removes (W9 E14) and these constants cannot express; the interface's first-order lag, which the inverse does not
model (README.md).
"""
from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
# C, the law's angle at full steer [deg]: read from this file by path (never imported, never written here).
CARLA010_ISO = HERE.parent / "sim" / "carla010_iso.py"
C_NAME = "C"

# --- 2.10's four topics
IN_ACTUATION = "/control/command/actuation_cmd"
OUT_ACTUATION = "/sdv/steershim/actuation_cmd"
IN_REPORT = "/sdv/steershim/steering_status_raw"
OUT_REPORT = "/vehicle/status/steering_status"
TOPICS = (IN_ACTUATION, OUT_ACTUATION, IN_REPORT, OUT_REPORT)

# --- the interface's side, as WP9 read it at the pinned commit (D2)
# READ (WP9, 94b8fbd3): the actuation command's message module and class, the interface's subscription and the
# converter's publisher at tag 0.52.0 alike.
ACTUATION_TYPE = ("tier4_vehicle_msgs.msg", "ActuationCommandStamped")
# READ (WP9, 94b8fbd3): the actuation command's steer field, a float64 that carries the converter's commanded tire angle
# [rad, positive left].
ACTUATION_STEER = ("actuation", "steer_cmd")
# READ (WP9, 94b8fbd3): the CARLA steer the interface applies per unit of the steer field, before its first-order lag,
# with max_wheel_steer_angle_deg absent and the flattened curve: s = -delta / 70 deg (the wheels' max_steer_angle 70, W9
# section 5; CARLA's steer positive right, the field positive left).
CMD_STEER_PER_FIELD = -1.0 / math.radians(70.0)
# READ (WP9, 94b8fbd3): the raw report's tire angle [rad] per unit of the steer the interface applied, with
# max_wheel_steer_angle_deg absent and the flattened curve: "-s x 70 deg", positive left.
REPORT_RAD_PER_STEER = -math.radians(70.0)
# The interface's constants above that are stand-ins, none since WP9's read; the node refuses to start on any name here.
STAND_INS: Tuple[str, ...] = ()
# READ (W4 M5): Autoware's steering report, autoware_vehicle_msgs/msg/SteeringReport, at autoware_msgs 1.13.0.
REPORT_TYPE = ("autoware_vehicle_msgs.msg", "SteeringReport")
# READ (W4 M5): its float32 steering_tire_angle [rad, "Positive: left"].
REPORT_STEER = ("steering_tire_angle",)

# --- design values, each with its reason
# A raw report may exceed a full steer's by binary32's rounding of the message's float32 field (a relative 6e-8); this
# much is taken as full steer, anything beyond is refused (a conversion constant would then be wrong).
STEER_ROUND_TOL = 1e-6
# C is a wheel angle at full steer [deg]: a value outside (0, 90) is not one.
C_LIMITS = (0.0, 90.0)


class ShimError(ValueError):
    """A value or message the shim refuses: nothing is published for it."""


def _finite(x: Any, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise ShimError("%s %r is not a finite number" % (what, x))
    return float(x)


def _bindings(node: ast.AST, name: str) -> List[ast.AST]:
    """The nodes under node, in the module's own scope, that bind or unbind name there: the name stored or deleted (by
    an assignment of any form, a for or with target, a walrus, a walrus in a comprehension among them, which binds in
    the enclosing scope), an import of it (a star import too, which may bind it), a def or class of that name, an except
    or match capture of it. A def's, lambda's or class's body and a comprehension's loop variables are scopes of their
    own and are not entered; what a def or class evaluates in the module (decorators, defaults, annotations, bases) is."""
    found: List[ast.AST] = []
    if isinstance(node, ast.Name):
        if node.id == name and not isinstance(node.ctx, ast.Load):
            found.append(node)
        return found
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if any(a.name == "*" or (a.asname or a.name.split(".")[0]) == name for a in node.names):
            found.append(node)
        return found
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        if getattr(node, "name", None) == name:
            found.append(node)
        outer: List[ast.AST] = list(getattr(node, "decorator_list", []))
        if isinstance(node, ast.ClassDef):
            outer += node.bases
            outer += node.keywords
        else:
            outer.append(node.args)
            returns = getattr(node, "returns", None)
            if returns is not None:
                outer.append(returns)
        for x in outer:
            found += _bindings(x, name)
        return found
    if isinstance(node, ast.comprehension):
        for x in [node.iter] + node.ifs:
            found += _bindings(x, name)
        return found
    # the captures (named by type: the match nodes are Python 3.10's)
    kind = type(node).__name__
    if kind in ("ExceptHandler", "MatchAs", "MatchStar", "MatchMapping"):
        if getattr(node, "rest" if kind == "MatchMapping" else "name", None) == name:
            found.append(node)
    for child in ast.iter_child_nodes(node):
        found += _bindings(child, name)
    return found


def load_c(path: Any) -> float:
    """C [deg] from the Python file at path, read without running it: its one binding in the module's namespace, a
    plain or annotated module-level assignment of a finite number literal in (0, 90). Every other statement that binds
    C there counts against it (see _bindings; a `global C` anywhere counts too), and so a C rebound later, or bound
    only in a nested block, by an import, a def or a class, is refused, as is anything else."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as err:
        raise ShimError("C cannot be read from %s: %s" % (path, err)) from None
    bindings = _bindings(tree, C_NAME) + [n for n in ast.walk(tree) if isinstance(n, ast.Global) and C_NAME in n.names]
    if len(bindings) != 1:
        raise ShimError("%s binds %s %d times in its module namespace, not once" % (path, C_NAME, len(bindings)))
    expr: Optional[ast.expr] = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(t is bindings[0] for t in n.targets):
            expr = n.value
        elif isinstance(n, ast.AnnAssign) and n.target is bindings[0]:
            expr = n.value
    if expr is None:
        raise ShimError("%s binds %s once, but not by a plain or annotated module-level assignment of a value (line %s)"
                        % (path, C_NAME, getattr(bindings[0], "lineno", "?")))
    try:
        value = ast.literal_eval(expr)
    except (ValueError, TypeError, SyntaxError):
        raise ShimError("%s in %s is not a number literal" % (C_NAME, path)) from None
    c = _finite(value, "%s in %s" % (C_NAME, path))
    if not C_LIMITS[0] < c < C_LIMITS[1]:
        raise ShimError("%s in %s is %r, outside (%g, %g)" % (C_NAME, path, c, C_LIMITS[0], C_LIMITS[1]))
    return c


def start_problems() -> List[str]:
    """Why the node may not start: each interface constant still a stand-in, and a conversion that is zero or not
    finite. Empty when it may."""
    out = ["%s is a stand-in until WP9 reads the interface at the pinned commit (spec-2 2.10)" % name for name in STAND_INS]
    for name in ("CMD_STEER_PER_FIELD", "REPORT_RAD_PER_STEER"):
        value = globals()[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value == 0:
            out.append("%s is %r: a conversion must be a finite number other than zero" % (name, value))
    return out


def s_star(delta_deg: float, c: float) -> float:
    """2.10's s* = sign(delta) x min(1, sqrt(|delta_deg| / C)): the size of steer whose angle by the law is delta, clipped
    at full steer, with delta's sign."""
    return math.copysign(min(1.0, math.sqrt(abs(delta_deg) / c)), delta_deg)


def interface_steer(field: float) -> float:
    """The CARLA steer (positive right) the interface applies for an actuation steer field, with the flattened curve."""
    return CMD_STEER_PER_FIELD * field


def interface_report(steer: float) -> float:
    """The raw report's tire angle [rad] the interface synthesises from the steer it applied, with the flattened curve."""
    return REPORT_RAD_PER_STEER * steer


def inverse(field: Any, c: float) -> float:
    """The actuation steer field to send the interface for the one Autoware sent (its commanded tire angle delta [rad,
    positive left]): the field whose interface steer is -s*, CARLA's steer being positive right."""
    delta_deg = math.degrees(_finite(field, "the commanded steer"))
    return -s_star(delta_deg, c) / CMD_STEER_PER_FIELD


def forward(raw: Any, c: float) -> float:
    """The steering report's tire angle [rad, positive left] for the interface's raw one: the steer s it applied, then
    the law's angle C x s x |s|, negated into the message's sign."""
    s = _finite(raw, "the raw report") / REPORT_RAD_PER_STEER
    if abs(s) > 1.0 + STEER_ROUND_TOL:
        raise ShimError("the raw report %r gives a steer of %r, beyond full steer" % (raw, s))
    s = max(-1.0, min(1.0, s))
    return math.radians(-(c * s * abs(s)))


def _fields(msg: Any) -> List[str]:
    """A message's field names, as its type gives them (rosidl's get_fields_and_field_types); a value that is no message
    is refused."""
    get = getattr(type(msg), "get_fields_and_field_types", None)
    if get is None:
        raise ShimError("%s is not a message" % type(msg).__name__)
    return list(get())


def field_of(msg: Any, path: Sequence[str]) -> Any:
    """The value at path (field names, outermost first) of a message."""
    value = msg
    for name in path:
        if name not in _fields(value):
            raise ShimError("%s has no field %r" % (type(value).__name__, name))
        value = getattr(value, name)
    return value


def check_steer_field(msg_type: Any, path: Sequence[str]) -> None:
    """Refuses a steer field path that a message type lacks, or whose value in a message made with the type's defaults is
    not a float (a nested message, an integer, a string): the node checks its two paths once at the start, so a READ value
    mistyped is refused there and not once per message."""
    where = "%s's field %s" % (getattr(msg_type, "__name__", repr(msg_type)), ".".join(path) or "(an empty path)")
    try:
        value = field_of(msg_type(), path)
    except TypeError as err:
        raise ShimError("%s: the type cannot be made with its defaults: %s" % (where, err)) from None
    except ShimError as err:
        raise ShimError("%s: %s" % (where, err)) from None
    if not isinstance(value, float):
        raise ShimError("%s is %s, not a float" % (where, type(value).__name__))


def with_field(msg: Any, path: Sequence[str], value: Any) -> Any:
    """A new message of msg's type holding every field of msg as it is (the stamps among them) but the one at path,
    which holds value; msg itself is not changed. The fields are the type's own (rosidl's get_fields_and_field_types)."""
    if not path:
        raise ShimError("an empty field path")
    fields = _fields(msg)
    if path[0] not in fields:
        raise ShimError("%s has no field %r" % (type(msg).__name__, path[0]))
    out = type(msg)()
    for name in fields:
        setattr(out, name, getattr(msg, name))
    setattr(out, path[0], value if len(path) == 1 else with_field(getattr(msg, path[0]), path[1:], value))
    return out


def other_publishers(infos: Sequence[Any], node_name: str, namespace: str) -> List[str]:
    """The fully qualified names of the publishers in infos (the graph's endpoint infos of one topic: node_name,
    node_namespace) that are not this node."""
    ns = namespace.rstrip("/")
    out = []
    for i in infos:
        if (i.node_name, i.node_namespace.rstrip("/")) != (node_name, ns):
            out.append("%s/%s" % (i.node_namespace.rstrip("/"), i.node_name))
    return out
