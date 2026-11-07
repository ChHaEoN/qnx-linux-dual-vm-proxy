"""fake_carla010.py -- a stand-in for the `carla` 0.10.0 client module, for the 0.10.0 path's tests (sdv/carla).

No CARLA runs in any test: sdv/carla/follow010.py is handed this module in place of
`carla`, with a fake clock, and follows it exactly as it follows the real client. It models only what the follower reads
and calls, records every call in order (`sim.calls`), and records and raises on every call the follower must never make
(FORBIDDEN), so a test sees one even where the follower catches the error.

THE INTERFACE (this file's own, not Autoware's): the world is synchronous at the interface's own settings, applied before
the follower attaches (`settings`). The fake clock's sleep drives it: at every tick instant the sleep passes (the first
TICK_WALL_NS after the clock's start, then one `tick_wall_ns(k)` apart) it ticks once -- the next control of its script
applied to the ego, the model integrated over the step, the frame number one more (two at `frame_jump_at`), the elapsed
time one step more -- and calls every on_tick callback with the world's snapshot, at that instant on the clock. It stops
after `ticks` ticks, so a follower then sees no tick; `ego_gone_at` destroys the ego before that tick's snapshot, and
`settings_at` changes the world's settings at a tick (another client applying them).

THE MODEL (a test's own, not CARLA's physics): a kinematic single-track car in CARLA's axes as WP9a read them --
left-handed, x forward, y right, z up; yaw, steer and the angular velocity's z positive turning right (clockwise seen
from above); degrees, deg/s, m/s. The effective wheel angle is FAKE_LAW_DEG x s x |s| and the yaw rate v tan(angle) /
FAKE_WHEELBASE_M: both this file's design values, chosen near the steering law and the wheelbase profile 5 holds so that
a take of it passes the kind 4 rules under that profile; neither is a measurement. get_wheel_steer_angle always returns
0.0, as WP9a read it on 0.10.0. get_control reports the script's control and the gear of a fake automatic gearbox: 0 at
rest, 1 up to FAKE_SHIFT_MS, 2 above, -1 in reverse (`gear_at` overrides it at a tick, for a gear that disagrees with
reverse). The vehicle physics read back has no wheel position (as WP9a read the 0.10.0 client), each wheel's
max_steer_angle, and the steering curve as the client reads it: the class default's points first, then the vehicle's own
(`curve`, by default the interface's flattening behind that prefix).

Every number here is this file's own design value for a test; none is a measurement.
"""
from __future__ import annotations

import fnmatch
import math
import types
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MS = 1_000_000
TICK_WALL_NS = 50 * MS          # the fake interface's tick on the fake clock: one step of simulation per step of wall time
FAKE_LAW_DEG = 60.0             # the effective wheel angle at full steer [deg], near the law (not the probe's constant)
FAKE_WHEELBASE_M = 2.9          # the model's wheelbase [m], near profile 5's L (not the probe's reading)
FAKE_THROTTLE_ACCEL = 2.0       # m/s^2 at full throttle
FAKE_DRAG = 0.1                 # 1/s: a speed-proportional drag, so a held throttle settles
FAKE_BRAKE_DECEL = 6.0          # m/s^2 at full brake
FAKE_SHIFT_MS = 4.0             # the fake gearbox's 1 -> 2 shift speed [m/s]
FAKE_PREFIX = ((0.0, 1.0), (10.0, 0.5))                  # the class default's points, read before the vehicle's own
FAKE_FLAT = ((0.0, 1.0), (120.0, 1.0))                   # the interface's flattening
FAKE_SHIPPED = ((0.0, 1.0), (20.0, 0.9), (60.0, 0.8), (120.0, 0.7))   # a vehicle's own curve as shipped (this file's)
FAKE_MAX_STEER = (70.0, 70.0, 0.0, 0.0)
FAKE_START_FRAME = 4000
FAKE_START_ELAPSED = 12.5
# The calls the follower must never make (follow010.py's FORBIDDEN, spec-2 10.1 item 1), and the others a passive client
# has no use for; each is recorded and raises.
FORBIDDEN = ("apply_settings", "tick", "load_world", "apply_physics_control", "apply_control", "set_target_velocity",
             "spawn_actor", "get_trafficmanager")
ALSO_REFUSED = ("reload_world", "try_spawn_actor", "set_autopilot", "destroy", "apply_batch", "apply_batch_sync",
                "wait_for_tick", "enable_constant_velocity")


class Forbidden(RuntimeError):
    """A call the fake refuses (recorded in sim.calls first)."""


def default_script(k: int) -> Dict[str, Any]:
    """The fake interface's control at its tick k: a stand, a launch, a weave inside rule 26's window, a stop."""
    if k < 10:
        return {"brake": 1.0}
    if k < 60:
        return {"throttle": 0.6}
    if k < 170:
        return {"throttle": 0.35, "steer": 0.3 * math.sin((k - 60) * 2.0 * math.pi / 110.0)}
    if k < 230:
        return {"brake": 0.4}
    return {"brake": 1.0}


class Vector3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x, self.y, self.z = float(x), float(y), float(z)


class Vector2D:
    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x, self.y = float(x), float(y)


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


class WorldSettings:
    """A fresh 0.10.0 server's substep (WP9a S5), with the interface's synchronous mode and step applied."""

    def __init__(self, synchronous_mode: bool = True, fixed_delta_seconds: Optional[float] = 0.05,
                 no_rendering_mode: bool = False, substepping: bool = True, max_substep_delta_time: float = 0.01,
                 max_substeps: int = 10) -> None:
        self.synchronous_mode, self.fixed_delta_seconds, self.no_rendering_mode = synchronous_mode, fixed_delta_seconds, no_rendering_mode
        self.substepping, self.max_substep_delta_time, self.max_substeps = substepping, max_substep_delta_time, max_substeps

    def copy(self) -> "WorldSettings":
        return WorldSettings(self.synchronous_mode, self.fixed_delta_seconds, self.no_rendering_mode, self.substepping,
                             self.max_substep_delta_time, self.max_substeps)


class WheelPhysicsControl:
    """0.10.0's wheel: no `position` member (WP9a E1)."""

    def __init__(self, max_steer_angle: float) -> None:
        self.max_steer_angle = float(max_steer_angle)


class VehiclePhysicsControl:
    def __init__(self, wheels: List[WheelPhysicsControl], steering_curve: List[Vector2D]) -> None:
        self.wheels = wheels
        self.steering_curve = steering_curve


class Timestamp:
    def __init__(self, frame: int, elapsed_seconds: float, delta_seconds: float) -> None:
        self.frame, self.elapsed_seconds, self.delta_seconds = frame, elapsed_seconds, delta_seconds


class ActorSnapshot:
    def __init__(self, ident: int) -> None:
        self.id = ident


class WorldSnapshot:
    def __init__(self, frame: int, elapsed: float, delta: float, actor_ids: Sequence[int]) -> None:
        self.frame = frame
        self.timestamp = Timestamp(frame, elapsed, delta)
        self._ids = set(actor_ids)

    def find(self, actor_id: int) -> Optional[ActorSnapshot]:
        return ActorSnapshot(actor_id) if actor_id in self._ids else None

    def has_actor(self, actor_id: int) -> bool:
        return actor_id in self._ids


class Actor:
    def __init__(self, sim: "Sim", ident: int, type_id: str, role_name: str) -> None:
        self.sim, self.id, self.type_id = sim, ident, type_id
        self.attributes = {"role_name": role_name, "number_of_wheels": "4", "base_type": "car"}
        self.alive = True

    @property
    def is_alive(self) -> bool:
        return self.alive

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN or name in ALSO_REFUSED:
            def refused(*a: Any, **k: Any) -> Any:
                self.sim.call(name)
                raise Forbidden("fake: %s is a call the follower never makes" % name)
            return refused
        raise AttributeError(name)


class Vehicle(Actor):
    """The ego (or another vehicle, which stands still)."""

    def __init__(self, sim: "Sim", ident: int, type_id: str, role_name: str) -> None:
        super().__init__(sim, ident, type_id, role_name)
        self.x, self.y, self.yaw = 100.0, -50.0, 30.0
        self.v = self.a = self.yaw_rate = 0.0
        self.control = VehicleControl(brake=1.0)
        self.gear = 0

    def _fwd(self) -> Tuple[float, float]:
        y = math.radians(self.yaw)
        return math.cos(y), math.sin(y)

    def get_velocity(self) -> Vector3D:
        self.sim.call("get_velocity")
        f = self._fwd()
        return Vector3D(self.v * f[0], self.v * f[1], 0.0)

    def get_acceleration(self) -> Vector3D:
        self.sim.call("get_acceleration")
        f = self._fwd()
        return Vector3D(self.a * f[0], self.a * f[1], 0.0)

    def get_transform(self) -> Transform:
        self.sim.call("get_transform")
        return Transform(Location(self.x, self.y, 0.2), Rotation(yaw=self.yaw))

    def get_angular_velocity(self) -> Vector3D:
        self.sim.call("get_angular_velocity")
        return Vector3D(0.0, 0.0, self.yaw_rate * self.sim.w_scale)

    def get_control(self) -> VehicleControl:
        self.sim.call("get_control")
        c = self.control
        return VehicleControl(c.throttle, c.steer, c.brake, c.hand_brake, c.reverse, c.manual_gear_shift, self.gear)

    def get_wheel_steer_angle(self, wheel: int) -> float:
        self.sim.call("get_wheel_steer_angle")
        return 0.0                                          # as WP9a read 0.10.0's (E7)

    def get_physics_control(self) -> VehiclePhysicsControl:
        self.sim.call("get_physics_control")
        if self.sim.physics_raises:
            raise RuntimeError("fake: the physics control could not be read")
        pts = [Vector2D(x, y) for x, y in self.sim.curve_read]
        return VehiclePhysicsControl([WheelPhysicsControl(m) for m in self.sim.max_steer], pts)

    def integrate(self, ctl: Dict[str, Any], dt: float, k: int) -> None:
        throttle, steer, brake = float(ctl.get("throttle", 0.0)), float(ctl.get("steer", 0.0)), float(ctl.get("brake", 0.0))
        reverse = bool(ctl.get("reverse", False))
        push = throttle * FAKE_THROTTLE_ACCEL * (-1.0 if reverse else 1.0) - FAKE_DRAG * self.v
        v_new = self.v + push * dt
        if brake > 0.0:
            dec = brake * FAKE_BRAKE_DECEL * dt
            v_new = max(0.0, v_new - dec) if v_new > 0 else min(0.0, v_new + dec)
        self.a = (v_new - self.v) / dt
        self.v = v_new
        angle = FAKE_LAW_DEG * steer * abs(steer)
        self.yaw_rate = math.degrees(self.v * math.tan(math.radians(angle)) / FAKE_WHEELBASE_M)
        self.yaw = (self.yaw + self.yaw_rate * dt + 540.0) % 360.0 - 180.0
        f = self._fwd()
        self.x += self.v * f[0] * dt
        self.y += self.v * f[1] * dt
        if reverse:
            self.gear = -1
        elif abs(self.v) < 1e-9:
            self.gear = 0
        else:
            self.gear = 1 if self.v <= FAKE_SHIFT_MS else 2
        if k in self.sim.gear_at:
            self.gear = self.sim.gear_at[k]
        self.control = VehicleControl(throttle, steer, brake, False, reverse, False, self.gear)


class ActorList(list):
    def filter(self, pattern: str) -> "ActorList":
        return ActorList(a for a in self if fnmatch.fnmatchcase(a.type_id, pattern))

    def find(self, ident: int) -> Optional[Actor]:
        return next((a for a in self if a.id == ident), None)


class Map:
    def __init__(self, name: str) -> None:
        self.name = name


class Sim:
    """The fake simulator's shared state (also the module's `sim` attribute)."""

    def __init__(self, clock: Any, *, client_version: str = "0.10.0", server_version: str = "0.10.0",
                 map_name: str = "Carla/Maps/Town10HD_Opt",
                 actors: Sequence[Tuple[str, str]] = (("vehicle.taxi.ford", "ego_vehicle"), ("vehicle.lincoln.mkz", "autopilot")),
                 settings: Optional[Dict[str, Any]] = None, settings_at: Optional[Dict[int, Dict[str, Any]]] = None,
                 curve: Sequence[Tuple[float, float]] = FAKE_FLAT, curve_read: Optional[Sequence[Tuple[float, float]]] = None,
                 max_steer: Sequence[float] = FAKE_MAX_STEER, ticks: int = 240,
                 tick_wall_ns: Optional[Callable[[int], int]] = None, frame_jump_at: Optional[int] = None,
                 ego_gone_at: Optional[int] = None, script: Callable[[int], Dict[str, Any]] = default_script,
                 gear_at: Optional[Dict[int, int]] = None, w_scale: float = 1.0, physics_raises: bool = False,
                 interrupt_at: Optional[int] = None) -> None:
        self.clock = clock
        self.client_version, self.server_version = client_version, server_version
        self.map_name = map_name
        self.settings = WorldSettings(**(settings or {}))
        self.settings_at = dict(settings_at or {})
        self.curve_read = list(curve_read) if curve_read is not None else list(FAKE_PREFIX) + list(curve)
        self.max_steer = tuple(max_steer)
        self.ticks_planned = ticks
        self.tick_wall_ns = tick_wall_ns or (lambda k: TICK_WALL_NS)
        self.frame_jump_at, self.ego_gone_at = frame_jump_at, ego_gone_at
        self.script = script
        self.gear_at = dict(gear_at or {})
        self.w_scale = w_scale                 # the angular velocity's z times this (a test's fault: another unit)
        self.physics_raises = physics_raises
        self.interrupt_at = interrupt_at       # a Ctrl-C delivered inside that tick
        self.calls: List[str] = []
        self.client_timeout: Optional[float] = None
        self.frame = FAKE_START_FRAME
        self.elapsed = FAKE_START_ELAPSED
        self.ticks = 0
        self.next_tick_ns = clock.now + TICK_WALL_NS
        self.callbacks: Dict[int, Callable[[Any], None]] = {}
        self.next_cb = 1
        self.actors = ActorList()
        for k, (type_id, role) in enumerate(actors):
            self.actors.append(Vehicle(self, 100 + k, type_id, role))
        self.ego = next((a for a in self.actors if a.attributes["role_name"] == "ego_vehicle"), None)

    def call(self, name: str) -> None:
        self.calls.append(name)

    def step_s(self) -> float:
        return float(self.settings.fixed_delta_seconds or 0.05)

    def tick(self) -> None:
        """One tick of the fake interface (THE INTERFACE in the module docstring)."""
        k = self.ticks
        self.ticks += 1
        if k in self.settings_at:
            for key, value in self.settings_at[k].items():
                setattr(self.settings, key, value)
        if self.ego_gone_at is not None and k == self.ego_gone_at and self.ego is not None:
            self.ego.alive = False
        dt = self.step_s()
        self.frame += 2 if self.frame_jump_at is not None and k == self.frame_jump_at else 1
        self.elapsed += dt
        if self.ego is not None and self.ego.alive:
            self.ego.integrate(self.script(k), dt, k)
        if self.interrupt_at is not None and k == self.interrupt_at:
            raise KeyboardInterrupt
        snap = WorldSnapshot(self.frame, self.elapsed, dt, [a.id for a in self.actors if a.alive])
        for cb in list(self.callbacks.values()):
            cb(snap)

    def advance_to(self, end_ns: int) -> None:
        """The fake clock moves to end_ns, ticking the world at every tick instant on the way."""
        while self.ticks < self.ticks_planned and self.next_tick_ns <= end_ns:
            self.clock.now = self.next_tick_ns
            self.tick()
            self.next_tick_ns += int(self.tick_wall_ns(self.ticks))
        self.clock.now = max(self.clock.now, end_ns)


class World:
    def __init__(self, sim: Sim) -> None:
        self.sim = sim

    def get_settings(self) -> WorldSettings:
        self.sim.call("get_settings")
        return self.sim.settings.copy()

    def get_map(self) -> Map:
        self.sim.call("get_map")
        return Map(self.sim.map_name)

    def get_actors(self, ids: Any = None) -> ActorList:
        self.sim.call("get_actors")
        return ActorList(a for a in self.sim.actors if a.alive)

    def get_snapshot(self) -> WorldSnapshot:
        self.sim.call("get_snapshot")
        return WorldSnapshot(self.sim.frame, self.sim.elapsed, self.sim.step_s(), [a.id for a in self.sim.actors if a.alive])

    def on_tick(self, callback: Callable[[Any], None]) -> int:
        self.sim.call("on_tick")
        ident = self.sim.next_cb
        self.sim.next_cb += 1
        self.sim.callbacks[ident] = callback
        return ident

    def remove_on_tick(self, ident: int) -> None:
        self.sim.call("remove_on_tick")
        self.sim.callbacks.pop(ident, None)

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN or name in ALSO_REFUSED:
            def refused(*a: Any, **k: Any) -> Any:
                self.sim.call(name)
                raise Forbidden("fake: %s is a call the follower never makes" % name)
            return refused
        raise AttributeError(name)


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.sim: Sim = _SIM["sim"]
        self.sim.call("connect:%s:%d" % (host, port))

    def set_timeout(self, seconds: float) -> None:
        self.sim.call("set_timeout")
        self.sim.client_timeout = float(seconds)

    def get_client_version(self) -> str:
        self.sim.call("get_client_version")
        return self.sim.client_version

    def get_server_version(self) -> str:
        self.sim.call("get_server_version")
        return self.sim.server_version

    def get_world(self) -> World:
        self.sim.call("get_world")
        return World(self.sim)

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN or name in ALSO_REFUSED:
            def refused(*a: Any, **k: Any) -> Any:
                self.sim.call(name)
                raise Forbidden("fake: %s is a call the follower never makes" % name)
            return refused
        raise AttributeError(name)


_SIM: Dict[str, Sim] = {}


class Clock:
    """A fake monotonic clock in ns: sleep(s) moves it exactly, and the fake interface ticks at the instants it passes."""

    def __init__(self, start_ns: int = 7_000 * MS) -> None:
        self.now = start_ns
        self.sleeps = 0
        self.sim: Optional[Sim] = None

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        end = self.now + max(0, int(math.ceil(seconds * 1e9)))
        if self.sim is not None:
            self.sim.advance_to(end)
        self.now = max(self.now, end)


def make(clock: Optional[Clock] = None, **faults: Any) -> types.ModuleType:
    """A fresh fake `carla` module (its simulator in `.sim`, its clock in `.clock`)."""
    clk = clock if clock is not None else Clock()
    sim = Sim(clk, **faults)
    clk.sim = sim
    _SIM["sim"] = sim
    mod = types.ModuleType("carla")
    for name in ("Client", "Location", "Rotation", "Transform", "VehicleControl", "WorldSettings", "Vector2D", "Vector3D"):
        setattr(mod, name, globals()[name])
    mod.sim = sim            # type: ignore[attr-defined]
    mod.clock = clk          # type: ignore[attr-defined]
    return mod
