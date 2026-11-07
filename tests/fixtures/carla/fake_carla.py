"""fake_carla.py -- a stand-in for the `carla` 0.9.16 client module, for the Phase 7 feeder's tests (sdv/carla).

No CARLA runs in any test: sdv/carla/carla_capture.py is handed this module in place of
`carla`, with a fake clock, and drives it exactly as it drives the real client. It models only what the capture
reads and calls, and records every call in order (`sim.calls`) so a test can pin the cleanup order.

THE MODEL (a test's own, not CARLA's physics): a kinematic single-track car in CARLA's axes as WP0's reads give
them -- left-handed, x forward, y right, z up; yaw, steer and the angular velocity's z positive turning right
(clockwise seen from above); angles in degrees, the angular velocity in deg/s. The road-wheel angle is steer x the
front wheels' max_steer_angle, and get_wheel_steer_angle returns it with the steer's sign (as WP0's sign probe read
CARLA's). The yaw rate is v tan(delta) / L with L the distance of the wheel positions' axle midpoints, so a converted
step is consistent with the kind 4 rules' kinematics. Acceleration is dv/dt along the heading: the throttle pushes
(forward only once the gearbox has engaged gear 1, which takes FAKE_GEAR_ENGAGE_S of throttle from gear 0; backward at
once with reverse set), the brake slows toward a standstill. There is no Traffic Manager: get_trafficmanager and
set_autopilot record their call and raise, since the take must start none.

THE MAP: an endless grid of two-way roads, a junction at every FAKE_BLOCK_M along x and y, right-hand traffic with each
lane's centre FAKE_LANE_OFFSET_M right of its road's centreline, and at every junction a left, a straight and a right
connector (quarter circles and a line inside a box of half-width FAKE_JUNCTION_M). Waypoint.next() follows the lanes and
returns one waypoint per branch at a junction's entry. The spawn points are FAKE_SPAWNS (lane, distance along it), and
get_waypoint answers for those points only.

Every number here is this file's own design value for a test, except two: FAKE_WHEELBASE_MM is profile 3's L as WP2
freezes it (a design value of the generation), so a take from this fake meets the encoder's wheelbase check against
WP2's generation, and FAKE_MAX_STEER_DEG is CARLA's WheelPhysicsControl class default. None is a measurement. Faults a
test asks for (keyword arguments of make()): another version, a world that ignores apply_settings or some of its
settings, other settings at the start, a start in another map, a tick that takes a given wall time, a frame number that
jumps, images that arrive late, never, or only while the client idles (as a camera thread delivers after the last
tick), an exception or a Ctrl-C raised inside the drive, a collision, a control the server does not apply, a sensor
that will not stop.

THE STEP: by default each tick advances elapsed_seconds by fixed_delta_seconds as a double holds it. With
float32_step=True it advances it by that value rounded to single precision (single()), still accumulated in a double:
CARLA 0.9.16's server keeps fixed_delta_seconds so, and every step then
reads a little off the generated step.
"""
from __future__ import annotations

import math
import os
import struct
import types
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

FAKE_THROTTLE_ACCEL = 3.0     # m/s^2 at full throttle
FAKE_BRAKE_DECEL = 10.0       # m/s^2 at full brake
FAKE_GEAR_ENGAGE_S = 0.5      # throttle from gear 0 engages gear 1 after this long
FAKE_MAX_STEER_DEG = 70.0     # CARLA's WheelPhysicsControl class default for max_steer_angle
# Wheel positions [cm] (FL, FR, BL, BR) of a car pointing along +x at the origin: a wheelbase of 2819 mm when
# rounded, a front track of 160 cm. The wheelbase is the one profile 3's L takes (the blueprint's; spec 5
# item 1 puts that value in profiles.toml), so a take on this fake meets the frozen profile; the track and heights are
# this file's own.
FAKE_WHEELS_CM = ((141.0, -80.0, 30.0), (141.0, 80.0, 30.0), (-140.9, -80.0, 30.0), (-140.9, 80.0, 30.0))
FAKE_WHEELBASE_MM = 2819
FAKE_BLOCK_M = 100.0          # the grid's block
FAKE_JUNCTION_M = 10.0        # a junction box's half-width
FAKE_LANE_OFFSET_M = 2.0      # a lane's centre right of its road's centreline
FAKE_SPAWN_Z = 0.3
# The client's warning when max_substeps is outside the range it checks (a paraphrase of LibCarla's, spec 4 item 2).
FAKE_SUBSTEP_WARNING = "WARNING: fake LibCarla: synchronous mode and substepping are on, and max_substeps is outside [1, 16]\n"
MS = 1_000_000
_DIRS = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))     # heading k points along _DIRS[k], at yaw 90 k


def _wrap(a: float) -> float:
    return (a + 540.0) % 360.0 - 180.0


def single(x: float) -> float:
    """x rounded to single precision, as a double: the step a float32_step server advances by."""
    return float(struct.unpack("<f", struct.pack("<f", x))[0])


class Vector3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x, self.y, self.z = float(x), float(y), float(z)


class Location(Vector3D):
    pass


class Rotation:
    def __init__(self, pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0) -> None:
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)


class Transform:
    def __init__(self, location: Optional[Location] = None, rotation: Optional[Rotation] = None) -> None:
        self.location = location if location is not None else Location()
        self.rotation = rotation if rotation is not None else Rotation()

    def get_forward_vector(self) -> Vector3D:
        y = math.radians(self.rotation.yaw)
        return Vector3D(math.cos(y), math.sin(y), 0.0)


class VehicleControl:
    def __init__(self, throttle: float = 0.0, steer: float = 0.0, brake: float = 0.0, hand_brake: bool = False,
                 reverse: bool = False, manual_gear_shift: bool = False, gear: int = 0) -> None:
        self.throttle, self.steer, self.brake = float(throttle), float(steer), float(brake)
        self.hand_brake, self.reverse, self.manual_gear_shift, self.gear = hand_brake, reverse, manual_gear_shift, gear


class VehicleWheelLocation:
    FL_Wheel = 0
    FR_Wheel = 1
    BL_Wheel = 2
    BR_Wheel = 3


class WorldSettings:
    """CARLA's defaults for the substep (0.9.16's synchrony page): substepping on, 0.01 s, at most 10."""

    def __init__(self, synchronous_mode: bool = False, fixed_delta_seconds: Optional[float] = None,
                 no_rendering_mode: bool = False, substepping: bool = True, max_substep_delta_time: float = 0.01,
                 max_substeps: int = 10) -> None:
        self.synchronous_mode, self.fixed_delta_seconds, self.no_rendering_mode = synchronous_mode, fixed_delta_seconds, no_rendering_mode
        self.substepping, self.max_substep_delta_time, self.max_substeps = substepping, max_substep_delta_time, max_substeps

    def copy(self) -> "WorldSettings":
        return WorldSettings(self.synchronous_mode, self.fixed_delta_seconds, self.no_rendering_mode, self.substepping,
                             self.max_substep_delta_time, self.max_substeps)


class Timestamp:
    def __init__(self, frame: int, elapsed_seconds: float, delta_seconds: float) -> None:
        self.frame, self.elapsed_seconds, self.delta_seconds = frame, elapsed_seconds, delta_seconds


class WorldSnapshot:
    def __init__(self, frame: int, elapsed: float, delta: float) -> None:
        self.frame = frame
        self.timestamp = Timestamp(frame, elapsed, delta)


class Image:
    """A camera image; its BGRA buffer is made when it is first read (a take reads few of them)."""

    def __init__(self, frame: int, width: int, height: int) -> None:
        self.frame, self.width, self.height = frame, width, height
        self._raw: Optional[bytes] = None

    @property
    def raw_data(self) -> bytes:
        if self._raw is None:
            self._raw = pattern_bgra(self.frame, self.width, self.height)
        return self._raw


class CollisionEvent:
    def __init__(self, frame: int, other: str) -> None:
        self.frame = frame
        self.other_actor = types.SimpleNamespace(type_id=other)


class WheelPhysics:
    def __init__(self, pos: Any, max_steer: float) -> None:
        self.position = Vector3D(*pos)
        self.max_steer_angle = max_steer


class PhysicsControl:
    def __init__(self, wheels: List[WheelPhysics]) -> None:
        self.wheels = wheels


class ActorAttribute:
    def __init__(self, ident: str, value: str) -> None:
        self.id, self._v = ident, value

    def as_str(self) -> str:
        return self._v


class ActorBlueprint:
    def __init__(self, ident: str, attributes: Dict[str, str]) -> None:
        self.id = ident
        self._attrs = dict(attributes)

    def set_attribute(self, key: str, value: str) -> None:
        if key not in self._attrs:
            raise IndexError(key)
        self._attrs[key] = str(value)

    def __iter__(self) -> Any:
        return iter([ActorAttribute(k, v) for k, v in sorted(self._attrs.items())])


# --- the map ------------------------------------------------------------------------------------------------------

class _Road:
    """The straight lane leaving junction (a, b) in heading k, from its box's edge to the next box's."""
    is_junction = False

    def __init__(self, a: int, b: int, k: int) -> None:
        self.a, self.b, self.k = a, b, k % 4
        self.length = FAKE_BLOCK_M - 2 * FAKE_JUNCTION_M

    def point(self, s: float) -> Tuple[float, float, float]:
        d, r = _DIRS[self.k], _DIRS[(self.k + 1) % 4]
        x = self.a * FAKE_BLOCK_M + (FAKE_JUNCTION_M + s) * d[0] + FAKE_LANE_OFFSET_M * r[0]
        y = self.b * FAKE_BLOCK_M + (FAKE_JUNCTION_M + s) * d[1] + FAKE_LANE_OFFSET_M * r[1]
        return x, y, _wrap(90.0 * self.k)

    def successors(self) -> List[Any]:
        d = _DIRS[self.k]
        a, b = self.a + int(d[0]), self.b + int(d[1])
        return [_Connector(a, b, self.k, kind) for kind in ("left", "straight", "right")]


class _Connector:
    """A connector inside junction (a, b)'s box, entering in heading k: a quarter circle left or right, or a line."""
    is_junction = True

    def __init__(self, a: int, b: int, k: int, kind: str) -> None:
        self.a, self.b, self.k, self.kind = a, b, k % 4, kind
        self.radius = {"left": FAKE_JUNCTION_M + FAKE_LANE_OFFSET_M, "right": FAKE_JUNCTION_M - FAKE_LANE_OFFSET_M}.get(kind, 0.0)
        self.length = 2 * FAKE_JUNCTION_M if kind == "straight" else self.radius * math.pi / 2
        self.exit_k = {"left": self.k - 1, "straight": self.k, "right": self.k + 1}[kind] % 4

    def point(self, s: float) -> Tuple[float, float, float]:
        d, r = _DIRS[self.k], _DIRS[(self.k + 1) % 4]
        px = self.a * FAKE_BLOCK_M - FAKE_JUNCTION_M * d[0] + FAKE_LANE_OFFSET_M * r[0]
        py = self.b * FAKE_BLOCK_M - FAKE_JUNCTION_M * d[1] + FAKE_LANE_OFFSET_M * r[1]
        if self.kind == "straight":
            return px + s * d[0], py + s * d[1], _wrap(90.0 * self.k)
        side = _DIRS[(self.k - 1) % 4] if self.kind == "left" else r
        cx, cy = px + self.radius * side[0], py + self.radius * side[1]
        phi = s / self.radius
        x = cx + self.radius * (-side[0] * math.cos(phi) + d[0] * math.sin(phi))
        y = cy + self.radius * (-side[1] * math.cos(phi) + d[1] * math.sin(phi))
        turn = -math.degrees(phi) if self.kind == "left" else math.degrees(phi)
        return x, y, _wrap(90.0 * self.k + turn)

    def successors(self) -> List[Any]:
        return [_Road(self.a, self.b, self.exit_k)]


def _advance(lane: Any, s: float, d: float) -> List["Waypoint"]:
    s2 = s + d
    if s2 <= lane.length + 1e-9:
        return [Waypoint(lane, s2)]
    out: List[Waypoint] = []
    for nxt in lane.successors():
        out += _advance(nxt, 0.0, s2 - lane.length)
    return out


class Waypoint:
    def __init__(self, lane: Any, s: float) -> None:
        self.lane, self.s = lane, s

    @property
    def transform(self) -> Transform:
        x, y, yaw = self.lane.point(self.s)
        return Transform(Location(x, y, 0.0), Rotation(yaw=yaw))

    @property
    def is_junction(self) -> bool:
        return bool(self.lane.is_junction)

    def next(self, distance: float) -> List["Waypoint"]:
        return _advance(self.lane, self.s, distance)


# (lane, metres along it): the fake's spawn points. The second and the fourth have the longest straight ahead (the
# second wins the tie); none is the first point, so a choice that takes the first is seen.
FAKE_SPAWNS = ((_Road(0, 0, 1), 50.0), (_Road(0, 0, 0), 5.0), (_Road(1, 0, 0), 30.0), (_Road(0, 1, 0), 5.0))


class Map:
    def __init__(self, name: str, spawns: Sequence[Tuple[Any, float]] = FAKE_SPAWNS) -> None:
        self.name = name
        self._spawns = [Waypoint(lane, s) for lane, s in spawns]

    def get_spawn_points(self) -> List[Transform]:
        out = []
        for w in self._spawns:
            t = w.transform
            out.append(Transform(Location(t.location.x, t.location.y, FAKE_SPAWN_Z), Rotation(yaw=t.rotation.yaw)))
        return out

    def get_waypoint(self, location: Location) -> Waypoint:
        for w in self._spawns:
            t = w.transform
            if abs(t.location.x - location.x) < 1e-6 and abs(t.location.y - location.y) < 1e-6:
                return Waypoint(w.lane, w.s)
        raise ValueError("fake: get_waypoint answers for the fake's spawn points only")


def pattern_bgra(frame: int, width: int, height: int) -> bytes:
    """A synthetic BGRA image for one frame: a gradient that moves with the frame number, never a photograph. Every
    pixel's alpha is FAKE_ALPHA, so a test can look for a stretch of the raw buffer in any file written."""
    out = bytearray(width * height * 4)
    k = 0
    for row in range(height):
        for col in range(width):
            out[k] = (col + frame) % 256
            out[k + 1] = (row * 3 + frame) % 256
            out[k + 2] = (col * 2 + row) % 256
            out[k + 3] = FAKE_ALPHA
            k += 4
    return bytes(out)


FAKE_ALPHA = 0xA5


class Sim:
    """The fake simulator's shared state (also the module's `sim` attribute)."""

    def __init__(self, clock: Any, *, client_version: str = "0.9.16", server_version: str = "0.9.16",
                 map_name: str = "Carla/Maps/Town10HD_Opt", ignore_apply: bool = False, keep_async: bool = False,
                 ignore_settings: Sequence[str] = (), start_settings: Optional[Dict[str, Any]] = None,
                 tick_ns: Optional[Callable[[int], int]] = None,
                 frame_jump_at: Optional[int] = None, image_lag: int = 0, drop_images: Optional[set] = None,
                 fail_at_tick: Optional[int] = None, collide_at_tick: Optional[int] = None,
                 apply_error_at: Optional[int] = None, wheels_cm: Any = FAKE_WHEELS_CM,
                 max_steer: Any = (FAKE_MAX_STEER_DEG, FAKE_MAX_STEER_DEG, 0.0, 0.0), yaw_scale: float = 1.0,
                 interrupt_at_tick: Optional[int] = None, stop_raises: bool = False, deliver_on_idle_sleep: bool = False,
                 float32_step: bool = False) -> None:
        self.clock = clock
        self.float32_step = float32_step                 # the step in single precision, as CARLA 0.9.16's server keeps it
        self.client_version, self.server_version = client_version, server_version
        self.map_name = map_name
        self.ignore_apply, self.keep_async = ignore_apply, keep_async
        self.ignore_settings = tuple(ignore_settings)
        self.tick_ns = tick_ns or (lambda n: 0)
        self.frame_jump_at = frame_jump_at
        self.image_lag = image_lag
        self.drop_images = set(drop_images or ())
        self.fail_at_tick = fail_at_tick
        self.collide_at_tick = collide_at_tick
        self.apply_error_at = apply_error_at
        self.interrupt_at_tick = interrupt_at_tick       # a Ctrl-C inside that tick
        self.stop_raises = stop_raises                   # Sensor.stop() raises
        self.deliver_on_idle_sleep = deliver_on_idle_sleep
        self.ticks_at_last_sleep = 0
        self.wheels_cm, self.max_steer = wheels_cm, max_steer
        self.yaw_scale = yaw_scale
        self.start_settings = dict(start_settings or {})
        self.settings = WorldSettings(**self.start_settings)
        self.frame = 100
        self.elapsed = 1.25
        self.ticks = 0
        self.applies = 0
        self.calls: List[str] = []
        self.tick_clock: List[int] = []      # the fake clock at each world.tick() call
        self.loads: List[str] = []
        self.spawns: List[Tuple[str, float, float, float, float]] = []   # (type id, x, y, z, yaw) of every spawn_actor
        self.actors: List[Any] = []
        self.pending_images: List[Image] = []

    # the car's wheelbase as the positions give it [m]
    @property
    def wheelbase_m(self) -> float:
        w = self.wheels_cm
        front = [(w[0][k] + w[1][k]) / 2 for k in range(3)]
        rear = [(w[2][k] + w[3][k]) / 2 for k in range(3)]
        return math.dist(front, rear) / 100.0

    def step_s(self) -> float:
        """The step each tick advances elapsed_seconds by (THE STEP in the module docstring)."""
        dt = self.settings.fixed_delta_seconds or 0.05
        return single(dt) if self.float32_step else dt

    def call(self, name: str) -> None:
        self.calls.append(name)

    def vehicles(self) -> List["Vehicle"]:
        return [a for a in self.actors if isinstance(a, Vehicle) and a.alive]

    def sensors(self, type_id: str) -> List["Sensor"]:
        return [a for a in self.actors if isinstance(a, Sensor) and a.alive and a.type_id == type_id]

    def tick(self) -> int:
        self.ticks += 1
        if self.fail_at_tick is not None and self.ticks == self.fail_at_tick:
            raise RuntimeError("fake: the simulator failed at tick %d" % self.ticks)
        if self.interrupt_at_tick is not None and self.ticks == self.interrupt_at_tick:
            raise KeyboardInterrupt
        dt = self.step_s()
        step = 2 if self.frame_jump_at is not None and self.ticks == self.frame_jump_at else 1
        self.frame += step
        self.elapsed += dt * step
        for v in self.vehicles():
            v.integrate(dt * step, self.elapsed)
        self.clock.advance(self.tick_ns(self.ticks))
        if self.collide_at_tick is not None and self.ticks == self.collide_at_tick:
            for col in self.sensors("sensor.other.collision"):
                if col.callback is not None:
                    col.callback(CollisionEvent(self.frame, "static.fence"))
        for cam in self.sensors("sensor.camera.rgb"):
            if cam.callback is not None and self.frame not in self.drop_images:
                self.pending_images.append(Image(self.frame, cam.width, cam.height))
        due = [im for im in self.pending_images if im.frame <= self.frame - self.image_lag]
        self.pending_images = [im for im in self.pending_images if im.frame > self.frame - self.image_lag]
        for im in due:
            for cam in self.sensors("sensor.camera.rgb"):
                if cam.callback is not None:
                    cam.callback(im)
        return self.frame

    def on_sleep(self) -> None:
        """deliver_on_idle_sleep: a sleep with no tick since the client's previous sleep (it is waiting for nothing but its
        images) gives the camera's thread the processor, and every pending image reaches the callback, whatever its lag."""
        idle = self.ticks == self.ticks_at_last_sleep
        self.ticks_at_last_sleep = self.ticks
        if self.deliver_on_idle_sleep and idle:
            due, self.pending_images = self.pending_images, []
            for im in due:
                for cam in self.sensors("sensor.camera.rgb"):
                    if cam.callback is not None:
                        cam.callback(im)


class Actor:
    _next = 1

    def __init__(self, sim: Sim, type_id: str) -> None:
        self.sim, self.type_id = sim, type_id
        self.id = Actor._next
        Actor._next += 1
        self.alive = True
        self.attributes: Dict[str, str] = {}

    def destroy(self) -> bool:
        self.sim.call("destroy:%s" % self.type_id)
        self.alive = False
        return True


class Sensor(Actor):
    def __init__(self, sim: Sim, bp: ActorBlueprint, transform: Transform) -> None:
        super().__init__(sim, bp.id)
        self.attributes = dict(bp._attrs)
        self.width = int(self.attributes.get("image_size_x", 0))
        self.height = int(self.attributes.get("image_size_y", 0))
        self.mount = transform
        self.callback: Optional[Callable[[Any], None]] = None

    def listen(self, cb: Callable[[Any], None]) -> None:
        self.sim.call("listen:%s" % self.type_id)
        self.callback = cb

    def stop(self) -> None:
        self.sim.call("stop:%s" % self.type_id)
        if self.sim.stop_raises:
            raise RuntimeError("fake: the sensor would not stop")
        self.callback = None


class Vehicle(Actor):
    def __init__(self, sim: Sim, bp: ActorBlueprint, transform: Transform) -> None:
        super().__init__(sim, bp.id)
        self.attributes = dict(bp._attrs)
        self.x, self.y = transform.location.x, transform.location.y
        self.yaw = transform.rotation.yaw
        self.v = 0.0
        self.a = 0.0
        self.yaw_rate = 0.0
        self.control = VehicleControl(brake=1.0)
        self.applied = VehicleControl(brake=1.0)
        self.gearbox = 0
        self.engage_s = 0.0
        self.t = 0.0

    # --- what the capture calls
    def apply_control(self, c: VehicleControl) -> None:
        self.sim.call("apply_control")
        self.control = c

    def set_autopilot(self, on: bool, port: int = 8000) -> None:
        self.sim.call("set_autopilot:%s" % bool(on))
        raise RuntimeError("fake: set_autopilot would start a Traffic Manager (the take runs none)")

    def get_velocity(self) -> Vector3D:
        f = self._fwd()
        return Vector3D(self.v * f[0], self.v * f[1], 0.0)

    def get_acceleration(self) -> Vector3D:
        f = self._fwd()
        return Vector3D(self.a * f[0], self.a * f[1], 0.0)

    def get_transform(self) -> Transform:
        return Transform(Location(self.x, self.y, 0.3), Rotation(yaw=self.yaw))

    def get_angular_velocity(self) -> Vector3D:
        return Vector3D(0.0, 0.0, self.yaw_rate)

    def get_control(self) -> VehicleControl:
        c = self.applied
        return VehicleControl(c.throttle, c.steer, c.brake, c.hand_brake, c.reverse, c.manual_gear_shift, self.gearbox)

    def get_wheel_steer_angle(self, wheel: int) -> float:
        if wheel not in (VehicleWheelLocation.FL_Wheel, VehicleWheelLocation.FR_Wheel):
            return 0.0
        return self.applied.steer * self.sim.max_steer[wheel]

    def get_physics_control(self) -> PhysicsControl:
        return PhysicsControl([WheelPhysics(p, m) for p, m in zip(self.sim.wheels_cm, self.sim.max_steer)])

    # --- the model
    def _fwd(self) -> Any:
        y = math.radians(self.yaw)
        return (math.cos(y), math.sin(y))

    def integrate(self, dt: float, elapsed: float) -> None:
        ctl = self.control
        if ctl.reverse:
            self.gearbox, self.engage_s = -1, 0.0
        elif self.gearbox != 1:
            self.gearbox = 0
            self.engage_s = self.engage_s + dt if ctl.throttle > 0.0 else 0.0
            if self.engage_s >= FAKE_GEAR_ENGAGE_S - 1e-9:
                self.gearbox = 1
        push = 0.0
        if ctl.reverse:
            push = -ctl.throttle * FAKE_THROTTLE_ACCEL
        elif self.gearbox == 1:
            push = ctl.throttle * FAKE_THROTTLE_ACCEL
        v_new = self.v + push * dt
        if ctl.brake > 0.0:
            dec = ctl.brake * FAKE_BRAKE_DECEL * dt
            if v_new > 0:
                v_new = max(0.0, v_new - dec)
            elif v_new < 0:
                v_new = min(0.0, v_new + dec)
        self.a = (v_new - self.v) / dt
        self.v = v_new
        delta = ctl.steer * self.sim.max_steer[0]
        self.yaw_rate = self.sim.yaw_scale * math.degrees(self.v * math.tan(math.radians(delta)) / self.sim.wheelbase_m)
        self.yaw = _wrap(self.yaw + self.yaw_rate * dt)
        f = self._fwd()
        self.x += self.v * f[0] * dt
        self.y += self.v * f[1] * dt
        self.applied = ctl


class BlueprintLibrary:
    def __init__(self) -> None:
        self._bps = {
            "vehicle.toyota.prius": {"role_name": "autopilot", "color": "0,0,0"},
            "sensor.camera.rgb": {"image_size_x": "800", "image_size_y": "600", "fov": "90", "sensor_tick": "0.0"},
            "sensor.other.collision": {"role_name": "front"},
        }

    def find(self, ident: str) -> ActorBlueprint:
        return ActorBlueprint(ident, self._bps[ident])


class World:
    def __init__(self, sim: Sim) -> None:
        self.sim = sim

    def get_settings(self) -> WorldSettings:
        return self.sim.settings.copy()

    def apply_settings(self, s: WorldSettings) -> int:
        self.sim.call("apply_settings:%s" % bool(s.synchronous_mode))
        if s.synchronous_mode and s.substepping and not 1 <= int(s.max_substeps) <= 16:
            os.write(2, FAKE_SUBSTEP_WARNING.encode("ascii"))       # the client's warning, below sys.stderr
        if not self.sim.ignore_apply:
            new = s.copy()
            for key in self.sim.ignore_settings:
                setattr(new, key, getattr(self.sim.settings, key))
            if self.sim.keep_async:
                new.synchronous_mode = False
            self.sim.settings = new
        return self.sim.frame

    def tick(self, seconds: float = 0.0) -> int:
        self.sim.call("tick")
        self.sim.tick_clock.append(self.sim.clock())
        if not seconds:
            raise RuntimeError("fake: tick() without an explicit timeout")
        return self.sim.tick()

    def get_snapshot(self) -> WorldSnapshot:
        return WorldSnapshot(self.sim.frame, self.sim.elapsed, self.sim.step_s())

    def get_map(self) -> Map:
        return Map(self.sim.map_name)

    def get_blueprint_library(self) -> BlueprintLibrary:
        return BlueprintLibrary()

    def spawn_actor(self, bp: ActorBlueprint, transform: Transform, attach_to: Any = None) -> Actor:
        self.sim.call("spawn:%s" % bp.id)
        self.sim.spawns.append((bp.id, transform.location.x, transform.location.y, transform.location.z, transform.rotation.yaw))
        actor: Actor
        if bp.id.startswith("sensor."):
            actor = Sensor(self.sim, bp, transform)
        else:
            actor = Vehicle(self.sim, bp, transform)
        self.sim.actors.append(actor)
        return actor


class ApplyVehicleControl:
    """carla.command.ApplyVehicleControl."""

    def __init__(self, actor: Any, control: VehicleControl) -> None:
        self.actor, self.control = actor, control


class Response:
    def __init__(self, error: str = "") -> None:
        self.error = error

    def has_error(self) -> bool:
        return bool(self.error)


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.sim: Sim = _SIM["sim"]
        self.sim.call("connect:%s:%d" % (host, port))

    def set_timeout(self, seconds: float) -> None:
        self.sim.call("set_timeout")

    def get_client_version(self) -> str:
        return self.sim.client_version

    def get_server_version(self) -> str:
        return self.sim.server_version

    def get_world(self) -> World:
        return World(self.sim)

    def load_world(self, name: str) -> World:
        self.sim.call("load_world:%s" % name)
        self.sim.loads.append(name)
        self.sim.map_name = "Carla/Maps/%s" % name
        self.sim.settings = WorldSettings(**self.sim.start_settings)      # a new world starts at the default settings
        return World(self.sim)

    def apply_batch_sync(self, commands: List[Any], do_tick: bool = False) -> List[Response]:
        """The commands applied now, before the next tick (the control lands on that tick)."""
        self.sim.call("apply_batch_sync")
        if do_tick:
            raise RuntimeError("fake: the take ticks the world itself")
        out = []
        for c in commands:
            self.sim.applies += 1
            if self.sim.apply_error_at is not None and self.sim.applies == self.sim.apply_error_at:
                out.append(Response("fake: the actor was not found"))
                continue
            c.actor.control = c.control
            out.append(Response())
        return out

    def get_trafficmanager(self, port: int = 8000) -> Any:
        self.sim.call("get_trafficmanager")
        raise RuntimeError("fake: a Traffic Manager would start here (the take runs none)")


_SIM: Dict[str, Sim] = {}


class Clock:
    """A fake monotonic clock in ns: sleep(s) advances it exactly, a tick advances it by the tick's wall time."""

    def __init__(self, start_ns: int = 5_000 * MS) -> None:
        self.now = start_ns
        self.sleeps: List[float] = []

    def __call__(self) -> int:
        return self.now

    def advance(self, ns: int) -> None:
        self.now += int(ns)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0, int(math.ceil(seconds * 1e9)))


def make(clock: Optional[Clock] = None, **faults: Any) -> types.ModuleType:
    """A fresh fake `carla` module (its simulator in `.sim`, its clock in `.clock`)."""
    clk = clock if clock is not None else Clock()
    sim = Sim(clk, **faults)
    _SIM["sim"] = sim
    if sim.deliver_on_idle_sleep:
        plain_sleep = clk.sleep

        def sleep(seconds: float) -> None:
            plain_sleep(seconds)
            sim.on_sleep()
        clk.sleep = sleep       # type: ignore[method-assign]
    mod = types.ModuleType("carla")
    for name in ("Client", "Location", "Rotation", "Transform", "VehicleControl", "VehicleWheelLocation", "WorldSettings"):
        setattr(mod, name, globals()[name])
    mod.command = types.SimpleNamespace(ApplyVehicleControl=ApplyVehicleControl)   # type: ignore[attr-defined]
    mod.sim = sim            # type: ignore[attr-defined]
    mod.clock = clk          # type: ignore[attr-defined]
    return mod
