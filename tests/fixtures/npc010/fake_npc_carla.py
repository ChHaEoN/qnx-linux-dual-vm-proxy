"""fake_npc_carla.py -- a stand-in for the `carla` 0.10.0 client module, for sdv/carla/npc010.py's tests.

No CARLA runs in any test: npc010.py is handed this module in place of `carla`, with a fake
clock. It models only what the NPC's client reads and calls, records every call in order (`sim.calls`), and records and raises
on every call the client must never make (FORBIDDEN), so a test sees one even where the client catches the error.

THE WORLD (this file's own): a level with `spawn_points`, one ego (`ego_vehicle`, unless `egos` says otherwise) ticked by a
fake interface: each wait_for_tick is one frame, advances the elapsed time and calls `on_frame(sim)`, which a test uses to move
the ego or to destroy an actor. As the client is understood (INFERRED, unread), a spawned actor's transform reads all zero until
the first tick after its spawn (the client's snapshot of it does not exist yet). The bounding boxes are this file's design values;
none is a reading of CARLA's.
"""
from __future__ import annotations

import fnmatch
import math
import types
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = "0.10.0"
MAP_NAME = "Carla/Maps/Town10HD_Opt"
EGO_BOX = ((0.1, 0.0, 0.7), (2.5, 1.0, 0.8))     # (location, half extents) of the fake taxi's box
NPC_BOX = ((-0.2, 0.0, 0.7), (2.4, 1.0, 0.7))    # of the fake lincoln's: its centre off the origin, so a gap read between
                                                 # origins differs from one read between boxes
# The calls the client must never make: each is recorded and raises.
FORBIDDEN = ("tick", "apply_settings", "load_world", "reload_world", "get_trafficmanager", "set_autopilot", "on_tick",
             "try_spawn_actor", "apply_physics_control", "set_target_velocity", "apply_batch", "apply_batch_sync",
             "enable_constant_velocity")


class Forbidden(RuntimeError):
    """A call the fake refuses (recorded in sim.calls first)."""


class Location:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x, self.y, self.z = x, y, z


class Rotation:
    def __init__(self, pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0) -> None:
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class Transform:
    def __init__(self, location: Optional[Location] = None, rotation: Optional[Rotation] = None) -> None:
        self.location, self.rotation = location or Location(), rotation or Rotation()


class VehicleControl:
    def __init__(self, throttle: float = 0.0, steer: float = 0.0, brake: float = 0.0, hand_brake: bool = False) -> None:
        self.throttle, self.steer, self.brake, self.hand_brake = throttle, steer, brake, hand_brake


def _box(spec: Tuple[Tuple[float, float, float], Tuple[float, float, float]]) -> Any:
    return types.SimpleNamespace(location=Location(*spec[0]), extent=Location(*spec[1]), rotation=Rotation())


class Actor:
    def __init__(self, sim: "Sim", actor_id: int, type_id: str, role: str, transform: Transform, box: Any, ticked: bool) -> None:
        self.sim, self.id, self.type_id = sim, actor_id, type_id
        self.attributes = {"role_name": role}
        self.transform, self.bounding_box, self.ticked = transform, box, ticked
        self.is_alive = True
        self.control = VehicleControl()

    def get_transform(self) -> Transform:
        self.sim.calls.append("get_transform:%d" % self.id)
        return self.transform if self.ticked else Transform()

    def apply_control(self, control: VehicleControl) -> None:
        self.sim.calls.append("apply_control:%d" % self.id)
        self.sim.controls.append((self.id, control))
        self.control = control

    def get_control(self) -> VehicleControl:
        return self.control

    def destroy(self) -> bool:
        self.sim.calls.append("destroy:%d" % self.id)
        if self.sim.server_gone:
            raise RuntimeError("time-out of the fake server")
        if not self.is_alive:
            return False
        self.is_alive = False
        self.sim.actors.remove(self)
        self.sim.destroyed.append(self.id)
        return not self.sim.destroy_answers_false

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN:
            return self.sim.forbidden(name)
        raise AttributeError(name)


class ActorList(list):
    def filter(self, pattern: str) -> "ActorList":
        return ActorList(a for a in self if fnmatch.fnmatch(a.type_id, pattern))


class Blueprint:
    def __init__(self, sim: "Sim", id_: str) -> None:
        self.sim, self.id = sim, id_
        self.attributes: Dict[str, str] = {}

    def set_attribute(self, key: str, value: str) -> None:
        self.attributes[key] = value


class Library:
    def __init__(self, sim: "Sim") -> None:
        self.sim = sim

    def find(self, id_: str) -> Blueprint:
        self.sim.calls.append("find:%s" % id_)
        if id_ not in self.sim.blueprints:
            raise IndexError("no blueprint " + id_)
        return Blueprint(self.sim, id_)


class Map:
    def __init__(self, sim: "Sim") -> None:
        self.sim, self.name = sim, sim.map_name

    def get_spawn_points(self) -> List[Transform]:
        return list(self.sim.spawn_points)


class World:
    def __init__(self, sim: "Sim") -> None:
        self.sim = sim

    def get_map(self) -> Map:
        return Map(self.sim)

    def get_blueprint_library(self) -> Library:
        return Library(self.sim)

    def get_actors(self) -> ActorList:
        self.sim.calls.append("get_actors")
        return ActorList(self.sim.actors)

    def spawn_actor(self, bp: Blueprint, transform: Transform, *a: Any, **k: Any) -> Actor:
        self.sim.calls.append("spawn_actor:%s" % bp.id)
        self.sim.spawned.append((bp, transform))
        if self.sim.spawn_raises:
            raise RuntimeError("Spawn failed because of collision at spawn position")
        box = self.sim.npc_box if self.sim.npc_box is not None else _box(NPC_BOX)
        actor = Actor(self.sim, 1000 + len(self.sim.spawned), bp.id, bp.attributes.get("role_name", ""), transform, box, False)
        self.sim.actors.append(actor)
        return actor

    def wait_for_tick(self, seconds: float = 10.0) -> Any:
        self.sim.calls.append("wait_for_tick")
        self.sim.tick_timeouts.append(seconds)
        if self.sim.server_gone or self.sim.frames_left == 0:
            raise RuntimeError("time-out while waiting for the simulator")
        if self.sim.interrupt_at is not None and self.sim.frame - self.sim.start_frame >= self.sim.interrupt_at:
            raise KeyboardInterrupt
        self.sim.frames_left -= 1
        self.sim.frame += 1
        self.sim.elapsed += 0.05
        for a in self.sim.actors:
            a.ticked = True
        if self.sim.on_frame is not None:
            self.sim.on_frame(self.sim)
        return types.SimpleNamespace(frame=self.sim.frame, timestamp=types.SimpleNamespace(elapsed_seconds=self.sim.elapsed))

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN:
            return self.sim.forbidden(name)
        raise AttributeError(name)


class Client:
    def __init__(self, sim: "Sim", host: str, port: int) -> None:
        self.sim = sim
        sim.calls.append("connect:%s:%d" % (host, port))

    def set_timeout(self, seconds: float) -> None:
        self.sim.calls.append("set_timeout")
        self.sim.client_timeout = seconds

    def get_client_version(self) -> str:
        return self.sim.client_version

    def get_server_version(self) -> str:
        return self.sim.server_version

    def get_world(self) -> World:
        self.sim.calls.append("get_world")
        return World(self.sim)

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN:
            return self.sim.forbidden(name)
        raise AttributeError(name)


class Sim:
    """What a test sets and reads."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.controls: List[Tuple[int, VehicleControl]] = []
        self.spawned: List[Tuple[Blueprint, Transform]] = []
        self.destroyed: List[int] = []
        self.tick_timeouts: List[float] = []
        self.client_timeout: Optional[float] = None
        self.client_version, self.server_version, self.map_name = VERSION, VERSION, MAP_NAME
        self.blueprints: Sequence[str] = ("vehicle.lincoln.mkz", "vehicle.taxi.ford")
        self.spawn_points = [Transform(Location(10.0 * k, 1.0 * k, 0.6), Rotation(yaw=0.32)) for k in range(60)]
        self.actors: List[Actor] = []
        self.frame = self.start_frame = 4000
        self.elapsed = 12.5
        self.frames_left = 1000        # how many ticks remain, then a tick that never comes, so no hold in a test runs for ever
        self.interrupt_at: Optional[int] = None
        self.server_gone = False
        self.spawn_raises = False
        self.destroy_answers_false = False
        self.npc_box: Any = None
        self.on_frame: Optional[Callable[["Sim"], None]] = None

    def forbidden(self, name: str) -> Callable[..., Any]:
        def call(*a: Any, **k: Any) -> Any:
            self.calls.append(name)
            raise Forbidden(name)
        return call

    def add_ego(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0, role: str = "ego_vehicle",
                type_id: str = "vehicle.taxi.ford", box: Any = None) -> Actor:
        ego = Actor(self, 100 + len(self.actors), type_id, role, Transform(Location(x, y, 0.1), Rotation(yaw=yaw)),
                    box if box is not None else _box(EGO_BOX), True)
        self.actors.append(ego)
        return ego

    def npc(self) -> Actor:
        found = [a for a in self.actors if a.attributes.get("role_name") == "npc"]
        assert len(found) == 1, found
        return found[0]


def make(sim: Optional[Sim] = None) -> Any:
    """The module to hand to npc010.main, its `sim` attribute the Sim."""
    s = sim if sim is not None else Sim()
    return types.SimpleNamespace(sim=s, Client=lambda host, port: Client(s, host, port), VehicleControl=VehicleControl,
                                 Location=Location, Rotation=Rotation, Transform=Transform)


def fake_clock() -> Tuple[Callable[[], float], Callable[[float], None], Dict[str, Any]]:
    """(clock, sleep, state): the sleep advances the clock by what it was asked and records it."""
    state: Dict[str, Any] = {"now": 100.0, "sleeps": []}

    def clock() -> float:
        return state["now"]

    def sleep(s: float) -> None:
        assert s >= 0 and math.isfinite(s), s
        state["sleeps"].append(s)
        state["now"] += s

    return clock, sleep, state
