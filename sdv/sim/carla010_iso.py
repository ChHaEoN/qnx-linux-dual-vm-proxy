"""carla010_iso.py -- CARLA 0.10.0's vehicle axes and steering law onto the slice's ISO 8855 signs (sdv/sim), for Phase 8.

Phase 8 spec-2 2.9: the one place the conversion is written for CARLA 0.10.0 (UE 5.5),
the simulator of Phase 8's closed loop (D17). carla_iso.py stays Phase 7's, for 0.9.16, and nothing here imports it.
slice.dbc carries ISO 8855 signs (X forward, Y left, Z up; steering angle and yaw rate positive left, that is
counterclockwise seen from above); a source in other axes converts before encoding. sdv/carla/follow010.py writes the
0.10.0 take and sdv/carla/encode010.py turns it into a recording through this module.

    CARLA 0.10.0'S CONVENTIONS, AS PHASE 8 WP9a READ THEM (CONVENTIONS below)
    - Axes: left-handed, x forward, y right, z up; positive yaw turns toward the right, clockwise seen from above (E17).
    - carla.VehicleControl.steer in [-1, 1], positive steers right (E18).
    - Actor.get_angular_velocity() and ActorSnapshot.get_angular_velocity() are both in deg/s (E19, E20; the package's
      python_api.md says rad/s for the snapshot, and the read contradicts it), its z positive in a right turn (E18).
    - get_velocity() is world-frame (E21), as get_acceleration(): only their dot products with the forward vector are
      used, so a frame common to the three vectors is all the conversion needs.
    - get_wheel_steer_angle() is not a delta source here: the take carries no wheel angle and the commanded steer
      is the only source.
    - The steering curve reads the client class's default points CURVE_PREFIX first, then the vehicle's own (E11); the
      server applies the vehicle's own points (E12), which the interface's flattening sets to FLAT_CURVE (E14).

    THE STEERING LAW (E8, E9): on the flattened curve the taxi's path curvature over steer x |steer| is constant, so its
    bicycle-equivalent wheel angle is about C x s x |s|, s the applied steer, with C PROBED below; never s x
    max_steer_angle (E10) and never a wheel angle (E7). INFERRED: the law follows from E4's wheelbase and E8's curvature
    by tan(delta) = L x kappa; its error against the arcs over the steer's range lands in profile 5's understeer row when
    WP3c reads the envelope. The law is read on the flattened curve only: with the shipped curve the server attenuates
    the steering with speed (E12), which is why the take is refused unless its own points are FLAT_CURVE.

    ISO 8855 FROM CARLA 0.10.0
    - v [m/s] = v . fwd and a_x [m/s^2] = a . fwd, world-frame vectors (a reversing car's speed negative);
    - delta [deg] = -(C x s x |s|): CARLA's positive-right angle, negated;
    - psi_dot [deg/s] = -w[2]: CARLA's positive-right rate, negated, already in deg/s;
    - gear = get_control()'s gear, by Phase 7's rule (P7s 2.7): reverse set exactly when the gear is -1; a forward gear
      number passes as it is (slice.dbc's CurrentGear carries "positive forward gear number").

DOES NOT SHOW: that the law holds beyond the drives WP9a read it on (the taxi, Town 10, the flattened curve), the
mechanism behind it, or any Ackermann geometry: no wheel angle is reported on 0.10.0.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Sequence, Tuple

CARLA_VERSION = "0.10.0"
# The conventions, named, each with how WP9a read it (READ: a probe or file; LIB: the installed client; INFERRED) and
# the read or source it rests on.
CONVENTIONS: Dict[str, Tuple[str, str, str]] = {
    "axes": ("left-handed: x forward, y right, z up", "LIB", "W9 E17: the installed client's forward vector at yaw 0 and 90"),
    "steer": ("positive right", "READ", "W9 E18: every arc+ window turns to the right vector's side"),
    "yaw": ("clockwise seen from above", "LIB", "W9 E17"),
    "angular_velocity_unit": ("degrees/s", "READ", "W9 E19 (the actor), E20 (the snapshot)"),
    "w_z_turn_sign": ("positive turning right", "READ", "W9 E18: w[2] positive in every arc+ window"),
    "velocity_frame": ("world frame", "READ", "W9 E21: the velocity along the forward vector through every heading"),
    "wheel_steer_angle": ("not used as a delta source", "READ", "W9 E7"),
    "steering_law": ("about C x s x |s| on the flattened curve", "INFERRED", "W9 E8 (READ), E9 (with E4's wheelbase)"),
    "steering_curve": ("the class default's points, then the vehicle's own", "READ", "W9 E11, E12, E14"),
}
# PROBED (Phase 8 WP9a E9): C [deg], the taxi's bicycle-equivalent wheel angle at full steer
# under the law, from E4's wheelbase and E8's curvature over steer x |steer| on the flattened curve.
# The coefficient was fitted locally; the readings are not published.
C = 60.1
# LIB (W9 E11): the client class's default steering curve, read before the vehicle's own points.
CURVE_PREFIX: Tuple[Tuple[float, float], ...] = ((0.0, 1.0), (10.0, 0.5))
# READ (W9 E14; the interface's flattening): the vehicle's own points the law was read on.
FLAT_CURVE: Tuple[Tuple[float, float], ...] = ((0.0, 1.0), (120.0, 1.0))


class ConversionError(ValueError):
    """A 0.10.0 step or reading this module refuses (a steer out of range, a gear against reverse, a curve it cannot read)."""


def _number(x: Any, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise ConversionError("%s %r is not a finite number" % (what, x))
    return float(x)


def longitudinal(vec_world: Sequence[float], forward_world: Sequence[float]) -> float:
    """The component of a world vector along the vehicle's unit forward vector, both in one frame (the mirror into ISO's
    axes preserves the dot product)."""
    return float(sum(a * b for a, b in zip(vec_world, forward_world)))


def yaw_rate_to_iso(omega_z_deg_s: float) -> float:
    """The z component of CARLA 0.10.0's angular velocity [deg/s, positive right] as an ISO 8855 yaw rate [deg/s]."""
    return -float(omega_z_deg_s)


def steer_angle_deg(steer: Any) -> float:
    """The applied steer (-1..1, positive right) as CARLA's effective wheel angle [deg, positive right]: C x s x |s|."""
    s = _number(steer, "steer")
    if not -1.0 <= s <= 1.0:
        raise ConversionError("steer %r outside -1..1" % (steer,))
    return C * s * abs(s)


def delta_iso_deg(steer: Any) -> float:
    """The applied steer as an ISO 8855 single-track steering angle [deg, positive left]: -(C x s x |s|)."""
    return -steer_angle_deg(steer)


def gear_of(gear: Any, reverse: Any) -> int:
    """get_control()'s gear, refused unless it is an integer of -1 or more and reverse is set exactly when it is -1."""
    if isinstance(gear, bool) or not isinstance(gear, int) or gear < -1:
        raise ConversionError("gear %r is not -1, 0 or a forward gear number" % (gear,))
    if not isinstance(reverse, bool) or reverse != (gear == -1):
        raise ConversionError("gear %r with reverse %r: reverse must be set exactly when the gear is -1" % (gear, reverse))
    return int(gear)


def own_curve_points(curve_read: Sequence[Sequence[float]]) -> Tuple[Tuple[float, float], ...]:
    """The vehicle's own steering-curve points: what follows CURVE_PREFIX in the curve as read (W9 E11). A read that does
    not begin with the prefix is refused: its own points cannot be told from it."""
    pts = tuple((float(p[0]), float(p[1])) for p in curve_read)
    if pts[:len(CURVE_PREFIX)] != CURVE_PREFIX:
        raise ConversionError("the steering curve as read %r does not begin with the class default's prefix %r"
                              % (pts, CURVE_PREFIX))
    return pts[len(CURVE_PREFIX):]


def convert(step: Mapping[str, Any]) -> Tuple[float, float, float, float, int]:
    """One 0.10.0 steps.jsonl record (CARLA's axes and units) as the five kind 4 values in ISO 8855:
    (v [m/s], a_x [m/s^2], delta [deg], psi_dot [deg/s], gear)."""
    fwd = step["fwd"]
    return (longitudinal(step["v"], fwd), longitudinal(step["a"], fwd), delta_iso_deg(step["steer"]),
            yaw_rate_to_iso(step["w"][2]), gear_of(step["gear"], step["reverse"]))
