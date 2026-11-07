#!/usr/bin/env python3
"""npc010.py -- one stopped NPC on CARLA 0.10.0, for the drive whose ego must stop behind it (sdv/carla).

The Phase 8 WP9 specification's section 1 item 9 and section 4's P1 row (the project's local
design notes; not in this tree). Runs on Windows in E:\\CARLA\\venv312-010 against the 0.10.0 server on the same PC, after
Autoware's interface has attached and before the first route; standard library and this directory only, and `carla` imported
inside main, so the tests import this module without it.

    usage: npc010.py place --spawn N --out FILE [--host H] [--hold-s S]
           npc010.py destroy [--host H]

REFUSED BEFORE CONNECTING (exit 2, nothing written), by either command: a host other than 127.0.0.1; fwcheck.py --carla 0.10.0
--for windows-client not passing, or not run (off Windows the gate cannot run, and this client has no other place). By place: a
spawn that is no index from 0 up, a hold that is no positive time, a --out that exists or lies inside a git work tree.

PLACE. Client and server must both be 0.10.0, the level Carla/Maps/Town10HD_Opt, exactly one actor must carry role_name
ego_vehicle (so the interface has attached) and none role_name npc; else it is refused with exit 1 and nothing placed, as is a
spawn index the level lacks, a blueprint it lacks, a spawn that fails, and a bounding box with no size (the gap would then read
between origins). It spawns one actor, BLUEPRINT vehicle.lincoln.mkz with role_name npc (never ego_vehicle, so follow010.py's
one-ego rule holds), at the level's spawn point N as the level gives it; no sensor. It applies brake 1.0 and hand brake once and
never again: a car that later moves was pushed, and its transform says so. No world.tick (the interface ticks), no
apply_settings, load_world or get_trafficmanager, no autopilot (FORBIDDEN).

THE HOLD. Then it waits for a tick through wait_for_tick, which reads and never advances the world (INFERRED, not read: a spawned
actor's transform may read zero until the tick after its spawn, so the first sample follows one), and each WRITE_PERIOD_S writes
one line to --out, flushed: its transform, its control, the ego's transform and the gap. Lines of JSON, ASCII: kind placed (the
spawn, both bounding boxes), kind sample (t_s since the placing, the frame and elapsed_s of that tick, npc, control, ego, gap_m),
kind end (reason, npc_destroyed_here). An ego that is gone gives ego and gap_m null and the hold goes on. The transforms are
CARLA's: x, y, z, roll, pitch, yaw, metres and degrees.

THE GAP (bumper_gap_m), the bumper-to-bumper distance from each actor's bounding box, on the plane: each box's four corners placed
by its own centre, half extents and its actor's transform, projected on the NPC's forward direction; the NPC's rearmost corner
less the ego's foremost. Never between origins. Positive with the ego behind; zero or negative once the boxes overlap along the
road, whether by contact, alongside or having passed.

THE END. destroy, from a second process, takes every actor of role_name npc and no other, and exits 0 when it destroyed one and
the server said so, 1 otherwise; place sees it at its next sample and exits 0 (end reason destroyed). place also ends on a hold
past --hold-s (hold-limit), a tick that does not come within TICK_TIMEOUT_S (no-tick), a failed read (error), a failed write
(error) and a Ctrl-C (interrupted): it destroys its NPC, says on the last line whether it could, and exits 1, or 130 for the
Ctrl-C. Should the end line's own write fail as well, the OSError leaves main (a traceback, exit 1), the NPC destroyed before it.
A Ctrl-C between the spawn and the hold destroys the NPC too and exits 130, stderr saying so as there is no end line. One that
lands in a destroy is said on the end line (destroy_error, exit 130) and not retried, and one inside the spawn_actor call leaves
this client no actor to destroy: either can leave the NPC, so the run's end runs destroy whatever place said (with none left its
exit 1 says so).

Design values, each with its reason, are beside their names below.

DOES NOT SHOW: that the server spawns the blueprint at that point or that the hand brake holds it; that the 0.10.0 models'
bounding boxes are the cars' size; that the real client's is_alive turns false on a destroy from a second process (the end by
destroy rests on it); that Autoware stops behind it, or how it would meet a moving NPC (a moving NPC needs a Traffic Manager or a
client that drives it, neither taken here); the gap away from the plane or with a box that is rotated on its actor; any timing:
a line's time is when this client read it.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import frameset  # noqa: E402
import fwcheck  # noqa: E402

HOST = "127.0.0.1"
PORT = 2000
VERSION = "0.10.0"                     # client and server (follow010.py's)
MAP = "Carla/Maps/Town10HD_Opt"        # a fresh 0.10.0 server's level (follow010.py's)
BLUEPRINT = "vehicle.lincoln.mkz"      # a design value of item 9
ROLE_NAME = "npc"                      # never EGO_ROLE_NAME: follow010.py follows the one actor of that role
EGO_ROLE_NAME = "ego_vehicle"
# Design values, each with its reason.
CLIENT_TIMEOUT_S = 20.0     # the interface's own client timeout, as follow010.py's
TICK_TIMEOUT_S = 60.0       # no tick for this long: the interface is gone or held up, far past one step under load
WRITE_PERIOD_S = 1.0        # the specification's "each second"
HOLD_S_DEFAULT = 1800.0     # well over a drive's four timeouts in sum (town10.py's); a run that dies leaves no client behind
CONTROL = {"throttle": 0.0, "steer": 0.0, "brake": 1.0, "hand_brake": True}
# The calls this client never makes; the tests hold the source to them.
FORBIDDEN = ("tick", "apply_settings", "load_world", "reload_world", "get_trafficmanager", "set_autopilot", "on_tick", "try_spawn_actor",
             "apply_physics_control", "set_target_velocity", "apply_batch", "apply_batch_sync", "enable_constant_velocity")

Pose = Tuple[float, float, float]          # x, y, yaw [deg]
Box = Tuple[Tuple[float, float], Tuple[float, float]]    # the centre's x, y on the actor; half length, half width
FwcheckRun = Callable[[], Tuple[int, List[str]]]


class NpcRefused(RuntimeError):
    """A refusal: said on stderr, and nothing is left on the server."""


class NoTick(RuntimeError):
    """A tick that did not come within TICK_TIMEOUT_S, or a server gone."""


def _corners(pose: Pose, box: Box) -> List[Tuple[float, float]]:
    """A box's four corners on the plane, in CARLA's axes (x forward, y right, yaw positive turning right)."""
    (x, y, yaw), ((cx, cy), (hx, hy)) = pose, box
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    out = []
    for px, py in ((cx + hx, cy + hy), (cx + hx, cy - hy), (cx - hx, cy + hy), (cx - hx, cy - hy)):
        out.append((x + px * c - py * s, y + px * s + py * c))
    return out


def bumper_gap_m(ego: Pose, ego_box: Box, npc: Pose, npc_box: Box) -> float:
    """The NPC's rearmost corner less the ego's foremost, along the NPC's forward direction (the module's THE GAP)."""
    ux, uy = math.cos(math.radians(npc[2])), math.sin(math.radians(npc[2]))
    return min(px * ux + py * uy for px, py in _corners(npc, npc_box)) - max(px * ux + py * uy for px, py in _corners(ego, ego_box))


def _box_of(actor: Any, what: str) -> Box:
    b = actor.bounding_box
    extent = (float(b.extent.x), float(b.extent.y))
    if not all(math.isfinite(v) and v > 0 for v in extent):
        raise NpcRefused("the %s's bounding box has no size (half extents %r): the gap would read between origins" % (what, extent))
    return ((float(b.location.x), float(b.location.y)), extent)


def _box_doc(box: Box) -> Dict[str, List[float]]:
    return {"location": list(box[0]), "extent": list(box[1])}


def _transform_doc(t: Any) -> Dict[str, float]:
    return {"x": t.location.x, "y": t.location.y, "z": t.location.z, "roll": t.rotation.roll, "pitch": t.rotation.pitch, "yaw": t.rotation.yaw}


def _pose(t: Any) -> Pose:
    return (t.location.x, t.location.y, t.rotation.yaw)


def _of_role(world: Any, role: str) -> List[Any]:
    return [a for a in world.get_actors() if dict(a.attributes).get("role_name") == role]


def _connect(carla: Any, host: str) -> Any:
    client = carla.Client(host, PORT)
    client.set_timeout(CLIENT_TIMEOUT_S)
    return client


def preflight(host: str, fwcheck_run: Optional[FwcheckRun], windows: bool, out: Optional[Path]) -> str:
    """Every refusal before connecting (the module docstring); returns fwcheck's line."""
    if host != HOST:
        raise NpcRefused("the client connects to %s only, not %r" % (HOST, host))
    if not windows:
        raise NpcRefused("fwcheck reads the Windows firewall and gates this client, so it runs on Windows only")
    rc, lines = (fwcheck_run or (lambda: fwcheck.run("windows-client", carla=VERSION)))()
    if rc != 0:
        raise NpcRefused("fwcheck --carla %s --for windows-client does not pass: %s" % (VERSION, "; ".join(lines)))
    if out is not None:
        if out.exists():
            raise NpcRefused("--out %s exists: it is never rewritten" % out)
        if not out.absolute().parent.is_dir():
            raise NpcRefused("--out %s: its parent is not a directory" % out)
        if frameset.inside_work_tree(out):
            raise NpcRefused("--out %s lies inside a git work tree" % out)
    return lines[0]


def _spawn(carla: Any, world: Any, index: int) -> Tuple[Any, Box]:
    """The refusals that need the level, then the one actor and its one control. Nothing stays on a refusal."""
    points = world.get_map().get_spawn_points()
    if index >= len(points):
        raise NpcRefused("the level has %d spawn points, not an index %d" % (len(points), index))
    try:
        bp = world.get_blueprint_library().find(BLUEPRINT)
    except (IndexError, RuntimeError) as e:
        raise NpcRefused("the level has no blueprint %s: %s" % (BLUEPRINT, e)) from e
    bp.set_attribute("role_name", ROLE_NAME)
    try:
        npc = world.spawn_actor(bp, points[index])
    except RuntimeError as e:
        raise NpcRefused("the spawn at index %d failed: %s" % (index, e)) from e
    try:
        box = _box_of(npc, "NPC")
        npc.apply_control(carla.VehicleControl(**CONTROL))
    except (NpcRefused, RuntimeError):
        npc.destroy()
        raise
    except KeyboardInterrupt:
        _finish(npc, "interrupted", None)
        raise
    return npc, box


def _line(f: TextIO, doc: Dict[str, Any]) -> None:
    f.write(json.dumps(doc) + "\n")
    f.flush()


def _sample(snapshot: Any, npc: Any, npc_box: Box, ego: Any, ego_box: Box, t_s: float) -> Dict[str, Any]:
    transform = npc.get_transform()
    control = npc.get_control()
    doc: Dict[str, Any] = {"kind": "sample", "t_s": t_s, "frame": snapshot.frame, "elapsed_s": snapshot.timestamp.elapsed_seconds,
                           "npc": _transform_doc(transform), "control": {"brake": control.brake, "hand_brake": control.hand_brake},
                           "ego": None, "gap_m": None}
    if ego.is_alive:
        et = ego.get_transform()
        doc["ego"] = _transform_doc(et)
        doc["gap_m"] = bumper_gap_m(_pose(et), ego_box, _pose(transform), npc_box)
    return doc


def _hold(world: Any, npc: Any, npc_box: Box, ego: Any, ego_box: Box, f: TextIO, hold_s: float, clock: Callable[[], float],
          sleep: Callable[[float], None]) -> str:
    """The samples until the hold ends: its reason."""
    t0 = clock()
    k = 0
    while True:
        try:
            snapshot = world.wait_for_tick(TICK_TIMEOUT_S)
        except RuntimeError as e:
            raise NoTick(str(e)) from e
        if not npc.is_alive:
            return "destroyed"
        _line(f, _sample(snapshot, npc, npc_box, ego, ego_box, clock() - t0))
        k += 1
        if clock() - t0 >= hold_s:
            return "hold-limit"
        sleep(max(0.0, t0 + k * WRITE_PERIOD_S - clock()))


def place(carla: Any, host: str, index: int, out: Path, hold_s: float, clock: Callable[[], float], sleep: Callable[[float], None],
          fwcheck_line: str) -> int:
    """The refusals after connecting, the one actor, the hold and its end. A refusal raises NpcRefused with nothing placed."""
    client = _connect(carla, host)
    versions = (client.get_client_version(), client.get_server_version())
    if versions != (VERSION, VERSION):
        raise NpcRefused("client and server are %s and %s, not both %s" % (versions[0], versions[1], VERSION))
    world = client.get_world()
    level = world.get_map().name
    if level != MAP:
        raise NpcRefused("the level is %s, not %s" % (level, MAP))
    egos = _of_role(world, EGO_ROLE_NAME)
    if len(egos) != 1:
        raise NpcRefused("%d actors carry role_name %r: place after the interface has attached, beside exactly one" % (len(egos), EGO_ROLE_NAME))
    if _of_role(world, ROLE_NAME):
        raise NpcRefused("an actor already carries role_name %r: never a second" % ROLE_NAME)
    ego, ego_box = egos[0], _box_of(egos[0], "ego")
    npc, npc_box = _spawn(carla, world, index)
    try:
        return _record(world, index, npc, npc_box, ego, ego_box, out, hold_s, clock, sleep, fwcheck_line)
    except KeyboardInterrupt:           # outside the hold's own handling: the end line, if any, is not there to say it
        end = _finish(npc, "interrupted", None)
        print("npc010.py: interrupted with no end line; NPC destroyed by this step: %s" % end["npc_destroyed_here"], file=sys.stderr)
        return 130


def _record(world: Any, index: int, npc: Any, npc_box: Box, ego: Any, ego_box: Box, out: Path, hold_s: float, clock: Callable[[], float],
            sleep: Callable[[float], None], fwcheck_line: str) -> int:
    """The file, its placed line, the hold and the end line."""
    reason, error, rc = "destroyed", None, 0
    try:
        f = open(out, "x", encoding="ascii", newline="\n")
    except OSError as e:
        npc.destroy()
        raise NpcRefused("--out %s cannot be made: %s" % (out, e)) from e
    with f:
        try:
            _line(f, {"kind": "placed", "spawn": index, "blueprint": BLUEPRINT, "role_name": ROLE_NAME, "spawn_transform":
                      _transform_doc(world.get_map().get_spawn_points()[index]), "npc_id": npc.id, "ego_id": ego.id,
                      "npc_box": _box_doc(npc_box), "ego_box": _box_doc(ego_box), "control": CONTROL, "fwcheck": fwcheck_line})
            reason = _hold(world, npc, npc_box, ego, ego_box, f, hold_s, clock, sleep)
            if reason != "destroyed":
                rc = 1
        except KeyboardInterrupt:
            reason, rc = "interrupted", 130
        except NoTick as e:
            reason, error, rc = "no-tick", str(e), 1
        except (RuntimeError, OSError) as e:
            reason, error, rc = "error", str(e), 1
        end = _finish(npc, reason, error)
        _line(f, end)
    return 130 if end["reason"] == "interrupted" else rc


def _finish(npc: Any, reason: str, error: Optional[str]) -> Dict[str, Any]:
    """The end line, the NPC destroyed here unless it is already gone."""
    doc: Dict[str, Any] = {"kind": "end", "reason": reason, "npc_destroyed_here": False}
    if error is not None:
        doc["error"] = error
    try:
        if npc.is_alive:
            doc["npc_destroyed_here"] = bool(npc.destroy())
    except RuntimeError as e:
        doc["destroy_error"] = str(e)
    except KeyboardInterrupt:
        doc["reason"], doc["destroy_error"] = "interrupted", "a Ctrl-C during the destroy"
    return doc


def destroy(carla: Any, host: str) -> int:
    client = _connect(carla, host)
    found = _of_role(client.get_world(), ROLE_NAME)
    if not found:
        print("npc010.py: no actor carries role_name %r" % ROLE_NAME, file=sys.stderr)
        return 1
    done = [bool(a.destroy()) for a in found]
    print("npc010.py: destroyed %d of %d actors of role_name %r" % (sum(done), len(found), ROLE_NAME))
    return 0 if all(done) else 1


def _index(text: str) -> int:
    v = int(text)
    if v < 0:
        raise ValueError(text)
    return v


def _positive(text: str) -> float:
    v = float(text)
    if not (math.isfinite(v) and v > 0):
        raise ValueError(text)
    return v


def main(argv: Optional[Sequence[str]] = None, *, carla: Any = None, windows: Optional[bool] = None, fwcheck_run: Optional[FwcheckRun] = None,
         clock: Optional[Callable[[], float]] = None, sleep: Optional[Callable[[float], None]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place", help="spawn the stopped NPC, hold it and write its lines")
    p.add_argument("--spawn", required=True, type=_index, help="the level's spawn point index")
    p.add_argument("--out", required=True, type=Path, help="the lines' file, new, outside every work tree")
    p.add_argument("--host", default=HOST)
    p.add_argument("--hold-s", type=_positive, default=HOLD_S_DEFAULT, help="end the hold after this long")
    d = sub.add_parser("destroy", help="destroy the NPC")
    d.add_argument("--host", default=HOST)
    a = ap.parse_args(argv)
    on_windows = (os.name == "nt") if windows is None else windows
    try:
        line = preflight(a.host, fwcheck_run, on_windows, a.out if a.cmd == "place" else None)
        if carla is None:
            try:
                carla = importlib.import_module("carla")
            except ImportError as e:
                raise NpcRefused("the carla 0.10.0 client is not importable here (%s)" % e) from e
    except NpcRefused as e:
        print("npc010.py: refused: %s" % e, file=sys.stderr)
        return 2
    try:
        if a.cmd == "destroy":
            return destroy(carla, a.host)
        return place(carla, a.host, a.spawn, a.out, a.hold_s, clock or time.monotonic, sleep or time.sleep, line)
    except NpcRefused as e:
        print("npc010.py: refused: %s" % e, file=sys.stderr)
    except RuntimeError as e:
        print("npc010.py: the client failed: %s" % e, file=sys.stderr)
    except KeyboardInterrupt:
        print("npc010.py: interrupted", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
