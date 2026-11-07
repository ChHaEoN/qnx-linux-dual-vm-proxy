#!/usr/bin/env python3
"""carla_capture.py -- the Phase 7 CARLA take: drive the ego, read it every step, write the take (sdv/carla).

Phase 7 spec 4 items 1-5, 2.1, 2.2 and 2.4, with the drive of the owner's option (a)
(drive.py). Runs on Windows in E:\\CARLA\\venv312 (CPython 3.12, the carla 0.9.16 wheel, nothing else) against a CARLA
0.9.16 server on the same PC; standard library and this package only, and `carla` imported inside main, so the tests
import this module without it.

    usage: carla_capture.py take --name N --seed S [--frames on|off] [--host H]
           carla_capture.py fwcheck --for windows-client|wsl [--no-tm]

REFUSED BEFORE CONNECTING (exit 2, nothing written): a name that is not <yyyymmdd>-carla-<S>[suffix] (sigsim's rule: the
suffix [a-z][a-z0-9]{0,7}, the whole [a-z0-9][a-z0-9-]{0,47}, a calendar date); on Windows, a host other than
127.0.0.1 and an fwcheck --for windows-client that does not pass (P4 applied: the take runs no Traffic Manager, but the
gate is checked whole); a take directory under TAKE_ROOT, or with --frames on a frame-set directory under FRAMES_ROOT,
that exists or lies inside a git work tree; no generated contract.
REFUSED AFTER CONNECTING (the take records why): client and server versions not both 0.9.16; a second load_world in one
process (one per server life: a second one crashes the server); world settings that do not read back as worldtie.py
ties them; a control the server did not apply.

THE TAKE (TAKE_ROOT/<name>/, a new directory, files in this order): steps.jsonl, one compact JSON object per simulation
step with exactly the keys of spec 2.2, raw: CARLA's axes and units from the actor's own getters (never an
ActorSnapshot's, whose angular velocity is in rad/s); script.jsonl, one object per scripted command; capture.json, written
at the end also after a failure (and once before the cleanup); take.sha256, the three
files in sha256sum form, written last.

THE WORLD TIE AND THE PACING (slice.dbc DESIGN VALUES (2); kind4-spec 5.5; worldtie.py): synchronous mode,
fixed_delta_seconds = CARLA_STEP_MS / 1000 and the physics substep (substepping, max_substep_delta_time
worldtie.SUBSTEP_S, max_substeps covering the step) applied and read back, refused when any read-back differs; the six
read-back settings go into capture.json's world_settings, and whatever apply_settings wrote to the process's stderr (fd 2:
LibCarla's warning about the substep count) into apply_settings_stderr, recorded, not refused. Each step: the commands
(drive.py), world.tick(TICK_TIMEOUT_S) with an explicit timeout (the installed signature defaults to 0.0), the readings,
t_vals; the step becomes current at the later of t_vals and the previous step's t_cur plus FEEDER_PACING_INTERVAL_MS
(sendpolicy.became_current); the next tick only after that; never a catch-up. The clock is time.perf_counter_ns
(QueryPerformanceCounter on Windows); its time.get_clock_info is recorded. RTF, gaps and skipped frames per sendpolicy
(the RTF counts each advance in steps of the generated length, so the server's single-precision step reads as a step;
capture.json's sim_s is the total of those same advances, the simulation time the RTF's mean divides).

THE DRIVE (drive.py): Town01, vehicle.toyota.prius at the spawn point with the longest straight lane ahead, placed on
the route's first point, no other actor and no Traffic Manager (no autopilot call either: without a TM it would start
one); the route controller, then the scripted segments, every command logged. Each control is applied with
Client.apply_batch_sync before the tick, to order it before that tick. A collision sensor rides on the ego; a collision stops the
take. The seed names the take and is kept in its
records; nothing is random in the drive (the server is deterministic in synchronous mode). FRAMES (--frames on): the
camera of spec 2.1 on the ego; on every STRIDE_STEPS-th step the image whose frame is that step's is reduced in the
camera's callback (frameset.py) and only the reduced bytes are kept; it is written as frame-%06d.png under
FRAMES_ROOT/<name>/, an image that never arrives is logged in capture.json, and frames.json is written last, after
take.sha256. The raw buffer is never written, copied to a file or kept past the callback.

CLEANUP (Phase 1b's order without the TM's steps, also on an error or Ctrl-C): sensors stopped and destroyed, tick,
vehicles destroyed, tick, the world back to the settings read at the start.

DOES NOT DEMONSTRATE: vehicle dynamics (CARLA's physics, the route controller and the scripted segments are not a
vehicle or a driver), perception (a simulated frame is not a camera), or any timing: the clock paces the take and the
RTF describes it, nothing more.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _d in (str(HERE), str(REPO / "sdv" / "frame"), str(REPO / "sdv" / "sim")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla_iso  # noqa: E402
import drive  # noqa: E402
import frameset  # noqa: E402
import fwcheck  # noqa: E402
import sendpolicy  # noqa: E402
import vssframe  # noqa: E402
import worldtie  # noqa: E402

TAKE_ROOT = Path(r"E:\CARLA\takes")
FRAMES_ROOT = Path(r"E:\CARLA\frames")
HOST = "127.0.0.1"
PORT = 2000
TOWN = "Town01"
BLUEPRINT = "vehicle.toyota.prius"
CARLA_VERSION = "0.9.16"
CAMERA_TYPE = "sensor.camera.rgb"
COLLISION_TYPE = "sensor.other.collision"
CAMERA_MOUNT = {"x": 1.5, "y": 0.0, "z": 1.6}
FORMAT = 1
# Design values, each with its reason.
CLIENT_TIMEOUT_S = 120.0    # load_world takes far longer than the client's default timeout (Phase 1b used this value)
TICK_TIMEOUT_S = 10.0       # world.tick's timeout, explicit: the installed signature defaults to 0.0, the API page to this
SETTLE_TICKS = 1            # ticks after the spawn, before the physics control is read: the ego is placed by then
STRIDE_STEPS = 20           # one frame per this many steps: one per simulated second at the generated step, the rate a
                            # camera app's file source replays at by default
MAX_FRAMES = 1000           # a set holds at most this many frames; the rest of a longer take is not asked for
IMAGE_WAIT_S = 2.0          # after the last step, how long the capture waits for images still on their way
IMAGE_POLL_S = 0.05
NAME_RE = re.compile(r"(\d{8})-carla-(\d+)([a-z][a-z0-9]{0,7})?")
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
STEP_KEYS = ("i", "frame", "elapsed_s", "t_vals_ns", "t_cur_ns", "seg", "gear", "v", "a", "fwd", "w", "steer", "throttle",
             "brake", "reverse", "wheel_deg")
TAKE_FILES = ("steps.jsonl", "script.jsonl", "capture.json")

_LOADS: List[str] = []      # the load_world calls of this process (at most one)


class CaptureRefused(RuntimeError):
    """The take cannot go on (the record says why)."""


@dataclass(frozen=True)
class Roots:
    takes: Path
    frames: Path


def load_contract() -> Any:
    return vssframe.load_contract()


def _real_date(text: str) -> bool:
    if len(text) != 8 or not (text.isascii() and text.isdigit()):
        return False
    try:
        datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return False
    return True


def name_problem(name: str, seed: int) -> Optional[str]:
    """Why `name` is not this seed's take name (<yyyymmdd>-carla-<seed>[suffix]), or None."""
    m = NAME_RE.fullmatch(name)
    if m is None or not NAME_PATTERN.fullmatch(name):
        return "%r is not <yyyymmdd>-carla-<seed>[suffix] (suffix [a-z][a-z0-9]{0,7}, the whole [a-z0-9][a-z0-9-]{0,47})" % name
    if not _real_date(m.group(1)):
        return "%r: %s is not a calendar date" % (name, m.group(1))
    if m.group(2) != str(seed):
        return "%r does not name seed %d" % (name, seed)
    return None


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_town(client: Any, world: Any) -> Any:
    """The world in TOWN: loaded exactly when the server is in another map, and never a second time in one process."""
    if world.get_map().name.split("/")[-1] == TOWN:
        return world
    if _LOADS:
        raise CaptureRefused("a second load_world in one process is refused (one per server life: a second one crashes it)")
    _LOADS.append(TOWN)
    return client.load_world(TOWN)


def _fd2_text(call: Callable[[], Any]) -> Tuple[Any, str]:
    """call() with the process's file descriptor 2 on a temporary file for its duration: (its result, what was written to
    fd 2 meanwhile). LibCarla's client writes its warnings there, below Python's sys.stderr."""
    try:
        sys.stderr.flush()
        saved = os.dup(2)
    except (OSError, ValueError):
        return call(), "(the process has no file descriptor 2: nothing captured)"
    with tempfile.TemporaryFile() as tmp:
        try:
            os.dup2(tmp.fileno(), 2)
            result = call()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        tmp.seek(0)
        text = tmp.read().decode("utf-8", "replace")
    return result, text


def tie_world(world: Any, step_s: float) -> Tuple[Dict[str, Any], str]:
    """worldtie.py's tie applied and read back, refused unless every setting holds: (the six read-back settings, what
    apply_settings wrote to stderr)."""
    s = world.get_settings()
    for key, value in worldtie.wanted(step_s).items():
        setattr(s, key, value)
    _frame, text = _fd2_text(lambda: world.apply_settings(s))
    got = worldtie.read_back(world.get_settings())
    problems = worldtie.tie_problems(got, step_s)
    if problems:
        raise CaptureRefused("the world settings read back %r: %s" % (got, "; ".join(problems)))
    return got, text


def physics(ego: Any) -> Dict[str, Any]:
    """The ego's wheels (positions in cm, as CARLA gives them), each wheel's max_steer_angle, the front pair's, and the
    wheelbase: the front-axle midpoint to the rear-axle midpoint, in mm rounded to the nearest integer."""
    wheels = list(ego.get_physics_control().wheels)
    if len(wheels) != 4:
        raise CaptureRefused("the ego has %d wheels, not 4" % len(wheels))
    pos = [(float(w.position.x), float(w.position.y), float(w.position.z)) for w in wheels]
    front = [(pos[0][k] + pos[1][k]) / 2 for k in range(3)]
    rear = [(pos[2][k] + pos[3][k]) / 2 for k in range(3)]
    return {"wheels": [{"position_cm": list(p), "max_steer_angle": float(w.max_steer_angle)} for p, w in zip(pos, wheels)],
            "wheelbase_mm": int(math.floor(math.dist(front, rear) * 10.0 + 0.5)),
            "front_max_steer_deg": [float(wheels[0].max_steer_angle), float(wheels[1].max_steer_angle)]}


class Images:
    """The camera's images, matched to steps by frame number. The callback reduces a wanted image at once and keeps only
    the reduced bytes; every other image is dropped where it arrives."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.wanted: Dict[int, int] = {}          # frame -> step index
        self.done: Dict[int, bytes] = {}          # frame -> reduced grey bytes
        self.errors: List[str] = []

    def want(self, frame: int, i: int) -> None:
        with self.lock:
            self.wanted[frame] = i

    def unwant(self, frame: int) -> None:
        with self.lock:
            self.wanted.pop(frame, None)
            self.done.pop(frame, None)

    def callback(self, image: Any) -> None:
        frame = int(image.frame)
        with self.lock:
            if frame not in self.wanted or frame in self.done:
                return
        try:
            grey = frameset.reduce_bgra(bytes(image.raw_data), int(image.width), int(image.height))
        except frameset.FrameSetError as e:
            with self.lock:
                self.errors.append("frame %d: %s" % (frame, e))
            return
        with self.lock:
            if frame in self.wanted:
                self.done[frame] = grey

    def collect(self) -> List[Tuple[int, int, bytes]]:
        """(step index, frame, grey) of every image reduced since the last call."""
        with self.lock:
            out = [(self.wanted.pop(f), f, g) for f, g in self.done.items()]
            self.done.clear()
        return out

    def outstanding(self) -> List[Tuple[int, int]]:
        with self.lock:
            return sorted((i, f) for f, i in self.wanted.items())

    def close(self) -> List[int]:
        """Stop wanting anything; the step indices whose image never arrived."""
        with self.lock:
            missing = sorted(self.wanted.values())
            self.wanted.clear()
            self.done.clear()
        return missing


class Collisions:
    """What the ego's collision sensor reported (its callback runs on the client's sensor thread)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: List[Dict[str, Any]] = []

    def callback(self, event: Any) -> None:
        other = getattr(getattr(event, "other_actor", None), "type_id", None)
        with self.lock:
            self.events.append({"frame": int(event.frame), "other": str(other)})

    def seen(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.events)


def _vec(v: Any) -> List[float]:
    return [float(v.x), float(v.y), float(v.z)]


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def _summarise(rec: Dict[str, Any], rows: List[Dict[str, Any]], pol: Any) -> None:
    """The step record's summary in capture.json: steps, sim_s, rtf, gaps, skipped frames, segments. sim_s is the total
    simulation time the RTF's mean divides by the total wall time: the sum of the per-step advances the RTF counts
    (sendpolicy.advances_ns), in seconds, not the snapshots' raw elapsed difference (steps.jsonl keeps the raw times)."""
    rec["steps"] = len(rows)
    frames = [r["frame"] for r in rows]
    elapsed = [r["elapsed_s"] for r in rows]
    t_cur = [r["t_cur_ns"] for r in rows]
    rec["sim_s"] = sum(sendpolicy.advances_ns(elapsed, pol.step_ns)) / sendpolicy.NS_PER_S
    rec["rtf"] = sendpolicy.rtf_summary(elapsed, t_cur, pol.step_ns) if len(rows) > 1 else None
    rec["gaps"] = sendpolicy.gaps(frames, t_cur, pol.cap_ns)
    rec["skipped_frames"] = sendpolicy.skipped_frames(frames)
    segs: List[List[Any]] = []
    for r in rows:
        if segs and segs[-1][0] == r["seg"]:
            segs[-1][2] = r["i"]
        else:
            segs.append([r["seg"], r["i"], r["i"]])
    rec["segments"] = segs


def take(name: str, seed: int, frames_on: bool, *, carla: Any, rts: Roots, host: str, contract: Any,
         clock_ns: Callable[[], int], sleep: Callable[[float], None], fwcheck_line: str, drv: Any, rv: Any,
         on_current: Optional[Callable[[Dict[str, Any], int, Dict[str, Any]], Optional[bool]]] = None) -> int:
    """One take (the module docstring). Returns 0 when it completed and cleaned up, 1 when it did not, 130 on Ctrl-C.
    on_current (the live sender's hook, sdv/feeder/live.py; none by default): called once per step, once the step became
    current and was written, with a copy of its steps.jsonl row, the clock's reading at which it became current and the
    ego's record; a true return ends the take there, completed. With none the take is the same, byte for byte."""
    pol = sendpolicy.Policy.from_contract(contract)
    stop_speed = float(contract.DBC_HALF_LSB["v"])
    tdir = rts.takes / name
    tdir.mkdir(parents=True, exist_ok=False)
    writer = (frameset.FrameSetWriter(rts.frames, name, seed=seed, stride_steps=STRIDE_STEPS, town=TOWN, blueprint=BLUEPRINT)
              if frames_on else None)
    pend = dict(carla_iso.pending())
    if drive.DRIVE_PENDING_PROBE:
        pend["drive_values"] = drive.values_record(drv, rv)
    info = time.get_clock_info("perf_counter")
    rec: Dict[str, Any] = {
        "format": FORMAT, "name": name, "seed": seed, "spawn_index": None, "client_version": None, "server_version": None,
        "map": None, "blueprint": BLUEPRINT, "world_settings": None, "apply_settings_stderr": None, "tm": None, "ego": None,
        "camera": None, "drive": {"values": asdict(drv), "route_values": asdict(rv), "route": None}, "collisions": [],
        "clock": {"function": "time.perf_counter_ns" if clock_ns is time.perf_counter_ns else "a stand-in for time.perf_counter_ns",
                  "info": {k: getattr(info, k) for k in ("implementation", "monotonic", "adjustable", "resolution")}},
        "steps": 0, "sim_s": 0.0, "rtf": None, "gaps": [], "skipped_frames": [], "segments": [], "fwcheck": fwcheck_line,
        "capture_sha256": _sha256_file(Path(__file__)), "completed": False, "cleanup": "not run", "errors": [],
        "pending_probe": pend}
    if pend:
        print("carla_capture.py: PENDING-PROBE: this take rests on provisional values that wait for WP0's probes: %s"
              % ", ".join(sorted(pend)), file=sys.stderr)
    steps_f = open(tdir / "steps.jsonl", "w", encoding="ascii", newline="\n")
    script_f = open(tdir / "script.jsonl", "w", encoding="ascii", newline="\n")
    rows: List[Dict[str, Any]] = []
    images = Images() if frames_on else None
    hits = Collisions()
    world = original = ego = None
    sensors: List[Any] = []
    interrupted = False
    try:
        client = carla.Client(host, PORT)
        client.set_timeout(CLIENT_TIMEOUT_S)
        rec["client_version"] = client.get_client_version()
        rec["server_version"] = client.get_server_version()
        if rec["client_version"] != CARLA_VERSION or rec["server_version"] != CARLA_VERSION:
            raise CaptureRefused("client %r and server %r are not both %s" % (rec["client_version"], rec["server_version"], CARLA_VERSION))
        world = load_town(client, client.get_world())
        cmap = world.get_map()
        rec["map"] = cmap.name
        original = world.get_settings()
        rec["world_settings"], rec["apply_settings_stderr"] = tie_world(world, pol.step_s)
        lib = world.get_blueprint_library()
        points = list(cmap.get_spawn_points())
        wps = [cmap.get_waypoint(p.location) for p in points]
        rec["spawn_index"] = drive.spawn_choice(wps)
        pts, turns = drive.build_route(wps[rec["spawn_index"]], rv)
        sp = points[rec["spawn_index"]]
        ego = world.spawn_actor(lib.find(BLUEPRINT), carla.Transform(carla.Location(x=pts[0][0], y=pts[0][1], z=float(sp.location.z)),
                                                                     carla.Rotation(yaw=pts[0][2])))
        col = world.spawn_actor(lib.find(COLLISION_TYPE), carla.Transform(), attach_to=ego)
        sensors.append(col)
        col.listen(hits.callback)
        if images is not None:
            bp = lib.find(CAMERA_TYPE)
            bp.set_attribute("image_size_x", str(frameset.WIDTH))
            bp.set_attribute("image_size_y", str(frameset.HEIGHT))
            cam = world.spawn_actor(bp, carla.Transform(carla.Location(**CAMERA_MOUNT)), attach_to=ego)
            sensors.append(cam)
            rec["camera"] = {"type": CAMERA_TYPE, "image_size_x": frameset.WIDTH, "image_size_y": frameset.HEIGHT,
                             "mount": dict(CAMERA_MOUNT), "attributes": {str(k): str(v) for k, v in dict(cam.attributes).items()},
                             "stride_steps": STRIDE_STEPS, "max_frames": MAX_FRAMES, "frames_written": 0, "frames_missing": [],
                             "errors": []}
            cam.listen(images.callback)
        for _k in range(SETTLE_TICKS):
            world.tick(TICK_TIMEOUT_S)
        rec["ego"] = physics(ego)
        wheelbase_m = rec["ego"]["wheelbase_mm"] / 1000.0
        ref = drive.reference(pts, rv, wheelbase_m)
        rec["drive"]["route"] = {"start": list(pts[0]), "points": len(pts), "turns": [list(t) for t in turns],
                                 "planned_rate_max_deg_s": ref.planned_rate_max}
        driver = drive.Driver(drv, rv, ref, turns, pol.step_s, stop_speed, wheelbase_m)
        fl, fr = carla.VehicleWheelLocation.FL_Wheel, carla.VehicleWheelLocation.FR_Wheel
        last_frame = int(world.get_snapshot().frame)
        t0: Optional[int] = None
        prev: Optional[int] = None
        last: Optional[Dict[str, Any]] = None
        asked = 0
        i = 0
        while not driver.done:
            for c in driver.before_step(i, last):
                res = client.apply_batch_sync([carla.command.ApplyVehicleControl(ego, carla.VehicleControl(**c.args))], False)
                errs = [str(r.error) for r in res if r.has_error()]
                if errs:
                    raise CaptureRefused("a control was not applied before step %d: %s" % (i, "; ".join(errs)))
                script_f.write(json.dumps({"i": i, "seg": driver.segment, "cmd": c.cmd, "args": c.args}, separators=(",", ":")) + "\n")
            predicted = None
            if images is not None and i % STRIDE_STEPS == 0 and asked < MAX_FRAMES:
                predicted = last_frame + 1
                images.want(predicted, i)
                asked += 1
            world.tick(TICK_TIMEOUT_S)
            snap = world.get_snapshot()
            vel, acc = ego.get_velocity(), ego.get_acceleration()
            tr = ego.get_transform()
            fwd = tr.get_forward_vector()
            ang, ctl = ego.get_angular_velocity(), ego.get_control()
            wheel = [float(ego.get_wheel_steer_angle(fl)), float(ego.get_wheel_steer_angle(fr))]
            t_vals = clock_ns()
            if t0 is None:
                t0 = t_vals
            t_cur = sendpolicy.became_current(t_vals, prev, pol.interval_ns)
            while True:
                now = clock_ns()
                if now >= t_cur:
                    break
                sleep((t_cur - now) / 1e9)
            prev = t_cur
            frame = int(snap.frame)
            if images is not None and predicted is not None and frame != predicted:
                images.unwant(predicted)
                images.want(frame, i)
            last_frame = frame
            row = {"i": i, "frame": frame, "elapsed_s": float(snap.timestamp.elapsed_seconds), "t_vals_ns": t_vals - t0,
                   "t_cur_ns": t_cur - t0, "seg": driver.segment, "gear": drive.SEGMENT_GEAR[driver.segment], "v": _vec(vel),
                   "a": _vec(acc), "fwd": _vec(fwd), "w": _vec(ang), "steer": float(ctl.steer), "throttle": float(ctl.throttle),
                   "brake": float(ctl.brake), "reverse": bool(ctl.reverse), "wheel_deg": wheel}
            steps_f.write(json.dumps(row, separators=(",", ":")) + "\n")
            rows.append(row)
            if images is not None and writer is not None:
                for si, f, grey in images.collect():
                    writer.add(si, f, grey)
            if hits.seen():
                raise drive.DriveError("the ego collided at step %d: %r" % (i, hits.seen()[:3]))
            if on_current is not None and on_current(dict(row), t_cur, dict(rec["ego"])):
                break
            last = {"v": row["v"], "fwd": row["fwd"], "loc": _vec(tr.location), "yaw": float(tr.rotation.yaw), "steer": row["steer"],
                    "gear": int(ctl.gear)}
            i += 1
        if images is not None and writer is not None:
            deadline = clock_ns() + int(IMAGE_WAIT_S * 1e9)
            while images.outstanding() and clock_ns() < deadline:
                sleep(IMAGE_POLL_S)
                for si, f, grey in images.collect():
                    writer.add(si, f, grey)
            for si, f, grey in images.collect():
                writer.add(si, f, grey)
        rec["completed"] = True
    except KeyboardInterrupt:
        interrupted = True
        rec["errors"].append("KeyboardInterrupt: interrupted")
    except Exception as e:  # noqa: BLE001 - recorded in capture.json; the cleanup and the files follow
        rec["errors"].append("%s: %s" % (type(e).__name__, e))
    finally:
        steps_f.close()
        script_f.close()
        _summarise(rec, rows, pol)
        rec["collisions"] = hits.seen()
        if images is not None and rec["camera"] is not None:
            missing = images.close()
            rec["camera"]["frames_missing"] = missing
            rec["camera"]["frames_written"] = len(writer.frames) if writer is not None else 0
            rec["camera"]["errors"] = list(images.errors)
            if missing:
                print("carla_capture.py: %d image(s) never arrived, at steps %s" % (len(missing), missing[:20]), file=sys.stderr)
        _write_json(tdir / "capture.json", rec)            # before the cleanup, so a failure there still leaves the record
        try:
            for sensor in reversed(sensors):
                sensor.stop()
                sensor.destroy()
            if world is not None:
                world.tick(TICK_TIMEOUT_S)
            if ego is not None:
                ego.destroy()
            if world is not None:
                world.tick(TICK_TIMEOUT_S)
            if world is not None and original is not None:
                world.apply_settings(original)
            rec["cleanup"] = "ok"
        except BaseException as e:  # noqa: BLE001 - the cleanup's error is the record's
            rec["cleanup"] = "%s: %s" % (type(e).__name__, e)
        _write_json(tdir / "capture.json", rec)
        sums = "".join("%s  %s\n" % (_sha256_file(tdir / n), n) for n in TAKE_FILES)
        (tdir / "take.sha256").write_text(sums, encoding="ascii", newline="\n")
        if writer is not None:
            writer.close(hashlib.sha256((tdir / "take.sha256").read_bytes()).hexdigest())
    if interrupted:
        return 130
    return 0 if rec["completed"] and not rec["errors"] and rec["cleanup"] == "ok" else 1


def preflight(name: str, seed: int, frames_on: bool, host: str, rts: Roots, windows: bool,
              fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]], contract: Any) -> Tuple[Any, str]:
    """Every refusal before connecting (the module docstring); returns the contract and fwcheck's line."""
    problem = name_problem(name, seed)
    if problem:
        raise CaptureRefused(problem)
    line = "not run: not Windows"
    if windows:
        if host != HOST:
            raise CaptureRefused("on Windows the client connects to %s only, not %r" % (HOST, host))
        rc, lines = (fwcheck_run or (lambda: fwcheck.run("windows-client")))()
        if rc != 0:
            raise CaptureRefused("fwcheck --for windows-client does not pass: %s" % "; ".join(lines))
        line = lines[0]
    targets = [("take", rts.takes / name)] + ([("frame-set", rts.frames / name)] if frames_on else [])
    for what, d in targets:
        if d.exists():
            raise CaptureRefused("the %s directory %s exists: it is never rewritten" % (what, d))
        if frameset.inside_work_tree(d):
            raise CaptureRefused("the %s directory %s lies inside a git work tree" % (what, d))
    if contract is None:
        try:
            contract = load_contract()
        except vssframe.ContractError as e:
            raise CaptureRefused(str(e)) from e
    return contract, line


def main(argv: Optional[Sequence[str]] = None, *, carla: Any = None, roots: Optional[Roots] = None, windows: Optional[bool] = None,
         fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]] = None, clock_ns: Optional[Callable[[], int]] = None,
         sleep: Optional[Callable[[float], None]] = None, drive_values: Any = None, route_values: Any = None,
         contract: Any = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="drive the ego and write a take (and with --frames on, a frame set)")
    t.add_argument("--name", required=True)
    t.add_argument("--seed", type=int, required=True)
    t.add_argument("--frames", choices=("on", "off"), default="off")
    t.add_argument("--host", default=HOST)
    f = sub.add_parser("fwcheck", help="the firewall predicate of spec 2.5 (read only)")
    f.add_argument("--for", dest="for_", required=True, choices=fwcheck.FOR_CHOICES)
    f.add_argument("--no-tm", action="store_true", help="P4 not applied: for a client that runs no Traffic Manager")
    a = ap.parse_args(argv)
    on_windows = (os.name == "nt") if windows is None else windows
    if a.cmd == "fwcheck":
        return fwcheck.main(["--for", a.for_] + (["--no-tm"] if a.no_tm else []), windows=on_windows)
    if a.seed < 0:
        ap.error("--seed must be a non-negative integer")
    rts = roots or Roots(TAKE_ROOT, FRAMES_ROOT)
    try:
        con, line = preflight(a.name, a.seed, a.frames == "on", a.host, rts, on_windows, fwcheck_run, contract)
    except CaptureRefused as e:
        print("carla_capture.py: refused: %s" % e, file=sys.stderr)
        return 2
    if carla is None:
        try:
            carla = importlib.import_module("carla")
        except ImportError as e:
            print("carla_capture.py: refused: the carla 0.9.16 client is not importable here (%s)" % e, file=sys.stderr)
            return 2
    return take(a.name, a.seed, a.frames == "on", carla=carla, rts=rts, host=a.host, contract=con,
                clock_ns=clock_ns or time.perf_counter_ns, sleep=sleep or time.sleep, fwcheck_line=line,
                drv=drive_values if drive_values is not None else drive.DRIVE,
                rv=route_values if route_values is not None else drive.ROUTE)


if __name__ == "__main__":
    sys.exit(main())
