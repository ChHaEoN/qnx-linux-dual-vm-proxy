"""carla_iso.py -- CARLA's vehicle axes onto the slice's ISO 8855 signs (sdv/sim), for the Phase 7 feeder.

Local branch only (decision 15). slice.dbc carries ISO 8855 signs (X forward, Y left, Z up; steering
angle and yaw rate positive left, that is counterclockwise seen from above), and a source that works
in other axes converts before encoding. The Phase 7 feeder (sdv/carla) reads CARLA 0.9.16, whose
world is left-handed; this module is the one place its conversion is written (Phase 7 spec 2.7).

    CARLA'S CONVENTIONS, AS PHASE 7 WP0 READ THEM (the local facts table, wp0-facts.md F2, F3, 5.2)
    - Axes: left-handed, x forward, y right, z up, for the world and a vehicle's frame; metres and
      degrees. READ (CARLA's coordinate page and its carla.Rotation entry).
    - carla.VehicleControl.steer in [-1, 1], positive steers right. READ (the package's lateral
      controller and manual_control.py's steering keys; WP0's sign probe, probe 2).
    - Yaw positive turns clockwise seen from above (toward the right). LIB (the installed client's
      Transform.get_forward_vector at yaw 0 and 90).
    - Actor.get_angular_velocity() is in deg/s (an ActorSnapshot's is in rad/s, which the capture
      never reads). READ (the Python API reference).
    - Its z component is positive in a right turn. READ (WP0's sign probe, probe 2, against the
      transform's yaw change; local notes).
    - get_wheel_steer_angle() has the steer's sign: positive steering right. READ (WP0's sign probe).
    - get_velocity() and get_acceleration() are world-frame vectors in those axes. READ (WP0's sign
      probe: the velocity lies along the forward vector on a straight). Only their dot products with
      the forward vector are used, so a frame common to all three vectors is all the conversion needs.

    ISO 8855 FROM CARLA
    - a vector (x, y, z) -> (x, -y, z): the mirror y -> -y turns the left-handed frame right-handed;
    - a signed angle or rate about z (steering, yaw, yaw rate) -> its negative;
    - a longitudinal component (speed or acceleration along the vehicle's forward vector) is a dot
      product of two vectors in the same frame, which the mirror preserves: no sign change, and a
      reversing vehicle's speed is negative (never the vector's length);
    - the gear is the step's segment gear (-1, 0, 1), and carla.VehicleControl.reverse must be set
      exactly when it is -1: a step where they differ is refused.

    PROBED (WP0's probes settled both values; each is one constant below, wp0-facts 3.1)
    - DELTA_SOURCE, the single-track steering angle of a car with two steered front wheels (F3):
      "wheel", the mean of get_wheel_steer_angle of the two front wheels (the physics angle), as the
      ISO 8855 delta -(FL + FR) / 2. WP0's probe 3 picked it by spec F3's rule: of the two candidates,
      the one with the smaller worst rule-26 residual on its drives. The other candidate, "commanded"
      (steer x the front wheels' max_steer_angle), is taken only when a caller names it.
    - WHEEL_STEER_POSITIVE, the sign of get_wheel_steer_angle (F2): "right", as steer (probe 2).
    PENDING_PROBE names any value a probe owes again (none now); while the wheel sign is in it, the
    "wheel" source is refused. pending() names what is pending, and the capture and the encoder
    record it in every take and recording and say it on stderr.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

# The conventions, named, each with how WP0 read it (READ or LIB) and where.
CARLA_AXES = "left-handed: x forward, y right, z up"
CARLA_STEER_POSITIVE = "right"
CARLA_YAW_POSITIVE = "clockwise seen from above"
CARLA_ANGULAR_VELOCITY_UNIT = "degrees/s"
CONVENTIONS: Dict[str, Tuple[str, str, str]] = {
    "axes": (CARLA_AXES, "READ", "CARLA 0.9.16 coordinate page; carla.Rotation"),
    "steer": (CARLA_STEER_POSITIVE, "READ", "PythonAPI agents/navigation/controller.py; examples/manual_control.py"),
    "yaw": (CARLA_YAW_POSITIVE, "LIB", "the installed client's Transform.get_forward_vector at yaw 0 and 90"),
    "angular_velocity_unit": (CARLA_ANGULAR_VELOCITY_UNIT, "READ", "Python API: Actor.get_angular_velocity"),
    "w_z_turn_sign": ("positive turning right", "READ", "WP0's sign probe (probe 2), against the transform's yaw change"),
    "wheel_steer_sign": ("positive turning right, as steer", "READ", "WP0's sign probe (probe 2)"),
    "velocity_frame": ("world frame", "READ", "WP0's sign probe (probe 2): the velocity along the forward vector"),
}

DELTA_SOURCES = ("commanded", "wheel")
# PROBED (F3, WP0 probe 3; wp0-facts 3.1): the delta source, the front wheels' physics angle.
DELTA_SOURCE = "wheel"
# PROBED (F2, WP0 probe 2; wp0-facts 3.1): the sign of get_wheel_steer_angle, positive right as steer.
WHEEL_STEER_POSITIVE = "right"
# The values above that wait for a probe (none: WP0's probes settled both); a reopened one would go back in.
PENDING_PROBE: Tuple[str, ...] = ()

Vec3 = Tuple[float, float, float]


class ConversionError(ValueError):
    """A CARLA step this module refuses to convert (a gear against reverse, an ambiguous or pending delta)."""


def pending() -> Dict[str, Any]:
    """The values of this module that still wait for WP0's probes, by name, with their provisional values."""
    values = {"delta_source": DELTA_SOURCE, "wheel_steer_sign": WHEEL_STEER_POSITIVE}
    return {k: values[k] for k in PENDING_PROBE}


def vector_to_iso(vec: Sequence[float]) -> Vec3:
    """A position, velocity or acceleration vector in CARLA's axes, in ISO 8855's (mirror y)."""
    x, y, z = vec
    return (float(x), -float(y), float(z))


def angle_to_iso(angle_deg: float) -> float:
    """A signed angle about z in CARLA's sense (positive right / clockwise from above), ISO 8855's."""
    return -float(angle_deg)


def yaw_rate_to_iso(omega_z_deg_s: float) -> float:
    """The z component of CARLA's angular velocity [deg/s] as an ISO 8855 yaw rate [deg/s]."""
    return -float(omega_z_deg_s)


def steer_to_iso_deg(steer: float, max_steer_deg: float) -> float:
    """carla.VehicleControl.steer (-1..1, positive right) and the vehicle's maximum road-wheel angle
    [deg] as an ISO 8855 single-track steering angle [deg] (positive left)."""
    if not -1.0 <= steer <= 1.0:
        raise ValueError("steer %r outside -1..1" % (steer,))
    if not max_steer_deg > 0:
        raise ValueError("max_steer_deg must be > 0")
    return angle_to_iso(steer * max_steer_deg)


def longitudinal(vec_world: Sequence[float], forward_world: Sequence[float]) -> float:
    """The component of a world vector along the vehicle's unit forward vector, both in one frame
    (CARLA's or ISO's: the mirror preserves the dot product)."""
    return float(sum(a * b for a, b in zip(vec_world, forward_world)))


def front_max_steer(front_max_steer_deg: Sequence[float]) -> float:
    """The front wheels' max_steer_angle [deg] as one value: the two must be equal and positive (a single-track model
    has one maximum)."""
    if len(front_max_steer_deg) != 2:
        raise ConversionError("two front wheels' max_steer_angle expected, got %r" % (front_max_steer_deg,))
    fl, fr = (float(x) for x in front_max_steer_deg)
    if fl != fr or not fl > 0:
        raise ConversionError("the front wheels' max_steer_angle %r, %r are not one positive value" % (fl, fr))
    return fl


def wheel_to_iso_deg(wheel_deg: Sequence[float]) -> float:
    """The mean of the two front wheels' get_wheel_steer_angle [deg] as an ISO 8855 steering angle, by
    WHEEL_STEER_POSITIVE. Refused while that sign waits for WP0's probe."""
    if "wheel_steer_sign" in PENDING_PROBE:
        raise ConversionError("the wheel source needs the sign of get_wheel_steer_angle, which is PENDING-PROBE (F2)")
    mean = (float(wheel_deg[0]) + float(wheel_deg[1])) / 2.0
    return angle_to_iso(mean) if WHEEL_STEER_POSITIVE == "right" else mean


def delta_iso(steer: float, wheel_deg: Sequence[float], front_max_steer_deg: Sequence[float], source: Any = None) -> float:
    """The single-track steering angle [deg, ISO 8855] of one step from the source DELTA_SOURCE names (another source only
    by an explicit `source`, for the probes' comparison)."""
    src = DELTA_SOURCE if source is None else source
    if src == "commanded":
        return steer_to_iso_deg(steer, front_max_steer(front_max_steer_deg))
    if src == "wheel":
        front_max_steer(front_max_steer_deg)
        return wheel_to_iso_deg(wheel_deg)
    raise ConversionError("unknown delta source %r (one of %s)" % (src, ", ".join(DELTA_SOURCES)))


def gear_of(gear: Any, reverse: Any) -> int:
    """The step's gear (-1, 0 or 1), refused unless reverse is set exactly when it is -1."""
    if isinstance(gear, bool) or gear not in (-1, 0, 1):
        raise ConversionError("gear %r is not -1, 0 or 1" % (gear,))
    if not isinstance(reverse, bool) or reverse != (gear == -1):
        raise ConversionError("gear %r with reverse %r: reverse must be set exactly when the gear is -1" % (gear, reverse))
    return int(gear)


def convert(step: Mapping[str, Any], front_max_steer_deg: Sequence[float]) -> Tuple[float, float, float, float, int]:
    """One steps.jsonl record of the capture (spec 2.2, CARLA's axes and units) as the five kind 4 values in ISO 8855:
    (v [m/s], a_x [m/s^2], delta [deg], psi_dot [deg/s], gear)."""
    fwd = step["fwd"]
    return (longitudinal(step["v"], fwd), longitudinal(step["a"], fwd),
            delta_iso(step["steer"], step["wheel_deg"], front_max_steer_deg), yaw_rate_to_iso(step["w"][2]),
            gear_of(step["gear"], step["reverse"]))
