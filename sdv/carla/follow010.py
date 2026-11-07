#!/usr/bin/env python3
"""follow010.py -- the Phase 8 passive take: follow the ego of CARLA 0.10.0 while Autoware's interface ticks (sdv/carla).

Phase 8 spec-2 2.9 and 10.1 item 1 (D17: CARLA 0.10.0). Runs on Windows in
E:\\CARLA\\venv312-010 (CPython 3.12, the carla 0.10.0 win wheel, nothing else) against the 0.10.0 server on the same PC,
while Autoware's CARLA interface drives the ego and ticks the world; standard library and this package only, and `carla`
imported inside main, so the tests import this module without it. carla_capture.py stays Phase 7's 0.9.16 capture.

    usage: follow010.py take --name N [--host H] [--max-frames N]
           follow010.py fwcheck --for windows-client|wsl [--no-tm]       (fwcheck.py --carla 0.10.0)

PASSIVE: the follower changes nothing in the world. It never calls apply_settings, tick, load_world,
apply_physics_control, apply_control, set_target_velocity, spawn_actor or get_trafficmanager (FORBIDDEN): the interface
owns the world's settings, its ticking, the map, the ego and its control. It reads get_physics_control() once, at attach
(a read: WP9a's E13 concerns the apply). It follows every frame through world.on_tick(), since wait_for_tick() reports
only the frames that arrive while it is awaited (the interface's own follower code says so, Phase 8 W: I5); the client's
timeout is set explicitly (CLIENT_TIMEOUT_S), and no call it makes has another timeout to set.

REFUSED BEFORE CONNECTING (exit 2, nothing written): a name that is not <yyyymmdd>-carla010-<n>[suffix] (n a decimal with no
leading zero; the suffix and the whole name as sigsim's rule; a calendar date), a pattern Phase 7's NAME_RE cannot match,
so a 0.10.0 take is never read as a 0.9.16 one; on Windows, a host other than 127.0.0.1 and an fwcheck --carla 0.10.0
--for windows-client that does not pass (P4 applied: the follower runs no Traffic Manager, but the gate is checked
whole); a take directory under TAKE_ROOT that exists or lies inside a git work tree; no generated contract.
REFUSED AFTER CONNECTING (the take is written, marked refused with its reason, and nothing is encoded from it; exit 1):
client and server not both 0.10.0; not exactly one actor whose role_name is ROLE_NAME; that actor not BLUEPRINT; the
world not synchronous, or fixed_delta_seconds not CARLA_STEP_MS / 1000, at attach, at any re-read (every REREAD_FRAMES
frames) or at the end (once more after the last frame, so no frame lies after the last read: the settings are read,
never applied); the vehicle's own steering-curve points (the curve as read, after the client class's default prefix, W9
E11) not the interface's flattening carla010_iso.FLAT_CURVE (W9 E14: so the speed attenuation of the shipped curve, E12,
never enters a take); a frame whose number is not the previous one's plus one, or that is not one step of simulation
(step_problem: its own delta_seconds, and its elapsed time since the previous frame's, each sendpolicy.step_advance_ns of
one CARLA_STEP_MS), so a world whose step changes is refused at the first frame of the new step; a listening socket of
this client's process at the start or the end (no Traffic Manager, W9 S10), or a read of them that fails
(LISTENERS_PS: every listener read, this pid's kept, the cmdlet stopping on any error). The substep is recorded, never
refused (W9 E30). The map is recorded; the encoder refuses another level.

THE TAKE (TAKE_ROOT/<name>/, a new directory: Phase 7 spec 2.2's shape): steps.jsonl, one compact object per frame the
interface ticked, with STEP_KEYS -- Phase 7's keys but wheel_deg (the conversion uses commanded steer): i,
frame, elapsed_s, t_vals_ns (the follower's clock when its tick callback read the frame) and t_cur_ns (when the step
becomes current by the send policy: sendpolicy.became_current, as a live sender would send it; the follower paces
nothing), both in ns from step 0's, which is 0; seg "passive"; gear and the control (steer, throttle, brake, reverse)
from the ego's get_control() of that tick; v, a, fwd, w from the ego's own getters, raw (CARLA's axes and units, w in
deg/s, W9 E19); script.jsonl, empty (the follower commands nothing); capture.json (CAPTURE_KEYS), written at the end, also
after a refusal or a failure; take.sha256, the three files in sha256sum form, written last. capture.json holds the
versions, the map, the blueprint, the role name and the ego's id, world_settings (worldtie.READ_BACK as read, at attach,
at each re-read and at the end, each with the frame it followed), physics_read (each wheel's max_steer_angle, the
steering curve as read and its own points), tm and camera null (no Traffic Manager, no frames), the listener reads, the
clock, sendpolicy's summary (steps, sim_s, rtf, gaps, skipped_frames, segments), how the take ended (end), the fwcheck
line, this file's sha256, completed, refused, errors.

THE END (ENDS): the ego gone from a tick's snapshot (the interface's cleanup destroys it), no frame for IDLE_TIMEOUT_S,
or --max-frames frames: each ends a completed take, once the world settings read at the end hold. A Ctrl-C ends it with
130 and the take is not completed, also one during the end listener read (the record and its sums are still written); no
tick at all within IDLE_TIMEOUT_S of attaching is an error. The cleanup removes the tick callback, and that is all: the
follower spawned nothing and set nothing.

DOES NOT DEMONSTRATE: vehicle dynamics, that Autoware drives the taxi (WP9's 5a shows it or not), or any timing: the clock
stamps the frames as the follower saw them and the send policy schedules them, nothing more. Nor that a world which
leaves the tie and comes back between two reads, with its step unchanged, is seen (asynchronous mode at the same step
changes no frame). Nor what the 0.10.0 server does to its settings when the interface disconnects: the interface leaves
them as they are (W: I6), but were the server to make itself asynchronous then, a take that ends after the disconnect
would be refused at its end read (WP9's first take shows which). The listener read was run on this PC only as a probe,
never from venv312-010 against a server.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _d in (str(HERE), str(REPO / "sdv" / "frame"), str(REPO / "sdv" / "sim")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla010_iso as iso  # noqa: E402
import frameset  # noqa: E402
import fwcheck  # noqa: E402
import sendpolicy  # noqa: E402
import vssframe  # noqa: E402
import worldtie  # noqa: E402

TAKE_ROOT = Path(r"E:\CARLA\takes")
HOST = "127.0.0.1"
PORT = 2000
VERSION = "0.10.0"                     # client and server (W9 W5; the package's VERSION)
MAP = "Carla/Maps/Town10HD_Opt"        # a fresh 0.10.0 server's level (W9 S4)
BLUEPRINT = "vehicle.taxi.ford"        # the ego (D18; W9 S11)
ROLE_NAME = "ego_vehicle"              # the interface's ego_vehicle_role_name default (Phase 8 W: I4, I8; W9 S12)
MODE = "passive"
SEG = "passive"
FORMAT = 1
# Design values, each with its reason.
CLIENT_TIMEOUT_S = 20.0     # the interface's own client timeout (W: I4); the follower calls no load_world
IDLE_TIMEOUT_S = 10.0       # no frame for this long ends the take: Phase 7's tick timeout, far past one step under load
POLL_S = 0.01               # how often the main thread drains what the tick callback read: a fifth of the step
REREAD_FRAMES = 200         # the world settings are read again after every this many frames: ten seconds of simulation
NAME_RE = re.compile(r"(\d{8})-carla010-(0|[1-9]\d*)([a-z][a-z0-9]{0,7})?")
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
STEP_KEYS = ("i", "frame", "elapsed_s", "t_vals_ns", "t_cur_ns", "seg", "gear", "v", "a", "fwd", "w", "steer", "throttle",
             "brake", "reverse")
TAKE_FILES = ("steps.jsonl", "script.jsonl", "capture.json")
CAPTURE_KEYS = ("format", "mode", "name", "client_version", "server_version", "map", "blueprint", "role_name", "ego_id",
                "world_settings", "physics_read", "tm", "camera", "listeners", "clock", "steps", "sim_s", "rtf", "gaps",
                "skipped_frames", "segments", "end", "fwcheck", "follow_sha256", "completed", "refused", "errors")
# The calls a passive follower never makes (spec-2 10.1 item 1); the tests hold this list and the code to it.
FORBIDDEN = ("apply_settings", "tick", "load_world", "apply_physics_control", "apply_control", "set_target_velocity",
             "spawn_actor", "get_trafficmanager")
ENDS = ("ego-gone", "idle", "max-frames")    # how a completed take ends (capture.json's end)
NOT_RUN = "not run: not Windows"
# This process's listening sockets: every listener read and this pid's kept. Not `-OwningProcess <pid>`: the cmdlet writes
# an error when nothing matches its own filter, which is the honest case, and the command then fails; and not
# SilentlyContinue, under which a cmdlet that fails reads as none: it stops, so a read that fails is refused. A host that
# listens nowhere at all would read as failed too, never as none.
LISTENERS_PS = ("Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.OwningProcess -eq %d } | "
                "Select-Object LocalAddress,LocalPort | ConvertTo-Json -Compress")

Listeners = Callable[[], List[Dict[str, Any]]]


class FollowRefused(RuntimeError):
    """The take cannot go on (the record says why)."""


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


def name_problem(name: str) -> Optional[str]:
    """Why `name` is not a 0.10.0 take's name (<yyyymmdd>-carla010-<n>[suffix]), or None."""
    m = NAME_RE.fullmatch(name)
    if m is None or not NAME_PATTERN.fullmatch(name) or not _real_date(m.group(1)):
        return ("%r is not <yyyymmdd>-carla010-<n>[suffix] (a calendar date; n with no leading zero; suffix [a-z][a-z0-9]{0,7};"
                " the whole [a-z0-9][a-z0-9-]{0,47})" % name)
    return None


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def world_problems(settings: Dict[str, Any], step_s: float) -> List[str]:
    """Why world settings as read (worldtie.READ_BACK) are not the interface's tie the take needs: synchronous, at
    fixed_delta_seconds = step_s (within worldtie.FLOAT_TOL, a double read across the RPC). The substep is not judged."""
    out = []
    if settings.get("synchronous_mode") is not True:
        out.append("the world is not synchronous (synchronous_mode %r)" % (settings.get("synchronous_mode"),))
    fd = settings.get("fixed_delta_seconds")
    if isinstance(fd, bool) or not isinstance(fd, (int, float)) or abs(float(fd) - step_s) > worldtie.FLOAT_TOL:
        out.append("fixed_delta_seconds %r, not %r (CARLA_STEP_MS / 1000)" % (fd, step_s))
    return out


def step_problem(frame: int, delta_s: float, elapsed_s: float, prev_elapsed_s: Optional[float], step_ns: int) -> Optional[str]:
    """Why a frame is not one step of simulation, or None: its own delta_seconds, and its elapsed time since the previous
    frame's, each counted in steps by sendpolicy.step_advance_ns (so a step the server keeps in single precision still
    reads as one) and each one step of step_ns."""
    if sendpolicy.step_advance_ns(0.0, delta_s, step_ns) != step_ns:
        return "frame %d's delta_seconds %r is not one step (%r s)" % (frame, delta_s, step_ns / sendpolicy.NS_PER_S)
    if prev_elapsed_s is not None and sendpolicy.step_advance_ns(prev_elapsed_s, elapsed_s, step_ns) != step_ns:
        return "frame %d advances the simulation %d ns after the previous frame, not one step (%d ns)" % (
            frame, sendpolicy.sim_advance_ns(prev_elapsed_s, elapsed_s), step_ns)
    return None


def curve_problems(curve_read: Sequence[Sequence[float]]) -> Tuple[List[str], Optional[List[List[float]]]]:
    """(why the steering curve as read is not the flattened one, the vehicle's own points or None)."""
    try:
        own = iso.own_curve_points(curve_read)
    except (iso.ConversionError, TypeError, ValueError, IndexError) as e:
        return [str(e)], None
    pts = [list(p) for p in own]
    if own != iso.FLAT_CURVE:
        return ["the vehicle's own steering-curve points %r are not the interface's flattening %r" % (pts, list(iso.FLAT_CURVE))], pts
    return [], pts


def own_listeners(runner: Optional[Callable[[List[str]], Tuple[int, str, str]]] = None) -> List[Dict[str, Any]]:
    """This process's listening TCP sockets, read with PowerShell (Windows): [{"LocalAddress", "LocalPort"}, ...]."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", LISTENERS_PS % os.getpid()]
    if runner is None:
        p = subprocess.run(cmd, capture_output=True, timeout=120)
        rc, out, err = p.returncode, (p.stdout or b"").decode("ascii", "replace"), (p.stderr or b"").decode("utf-8", "replace")
    else:
        rc, out, err = runner(cmd)
    if rc != 0:
        raise OSError("the listener read failed (%d): %s" % (rc, err.strip()[-300:]))
    if not out.strip():
        return []
    got = json.loads(out)
    return got if isinstance(got, list) else [got]


def _vec(v: Any) -> List[float]:
    return [float(v.x), float(v.y), float(v.z)]


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Item:
    """What the tick callback read of one frame."""
    frame: int
    elapsed_s: float
    delta_s: float
    t_vals_ns: int
    gear: int
    v: List[float]
    a: List[float]
    fwd: List[float]
    w: List[float]
    steer: float
    throttle: float
    brake: float
    reverse: bool


class Feed:
    """The frames the tick callback read, for the main thread (the callback runs on the client's stream thread)."""

    def __init__(self, ego: Any, clock_ns: Callable[[], int]) -> None:
        self.ego, self.clock_ns = ego, clock_ns
        self.lock = threading.Lock()
        self.items: List[Item] = []
        self.gone = False
        self.closed = False
        self.error: Optional[str] = None

    def on_tick(self, snapshot: Any) -> None:
        t_vals = self.clock_ns()
        with self.lock:
            if self.closed or self.gone or self.error:
                return
        try:
            if snapshot.find(self.ego.id) is None:
                with self.lock:
                    self.gone = True
                return
            ego = self.ego
            v, a, tr, w, ctl = ego.get_velocity(), ego.get_acceleration(), ego.get_transform(), ego.get_angular_velocity(), ego.get_control()
            item = Item(frame=int(snapshot.frame), elapsed_s=float(snapshot.timestamp.elapsed_seconds),
                        delta_s=float(snapshot.timestamp.delta_seconds), t_vals_ns=t_vals,
                        gear=int(ctl.gear), v=_vec(v), a=_vec(a), fwd=_vec(tr.get_forward_vector()), w=_vec(w),
                        steer=float(ctl.steer), throttle=float(ctl.throttle), brake=float(ctl.brake), reverse=bool(ctl.reverse))
        except Exception as e:  # noqa: BLE001 - handed to the main thread, which records it
            with self.lock:
                self.error = "%s: %s" % (type(e).__name__, e)
            return
        with self.lock:
            if not self.closed:
                self.items.append(item)

    def take(self) -> Tuple[List[Item], bool, Optional[str]]:
        with self.lock:
            items, self.items = self.items, []
            return items, self.gone, self.error

    def close(self) -> None:
        with self.lock:
            self.closed = True


def _summarise(rec: Dict[str, Any], rows: List[Dict[str, Any]], pol: Any) -> None:
    """capture.json's summary of the steps by the send policy: steps, sim_s, rtf, gaps, skipped frames, segments."""
    rec["steps"] = len(rows)
    frames = [r["frame"] for r in rows]
    elapsed = [r["elapsed_s"] for r in rows]
    t_cur = [r["t_cur_ns"] for r in rows]
    rec["sim_s"] = sum(sendpolicy.advances_ns(elapsed, pol.step_ns)) / sendpolicy.NS_PER_S
    rec["rtf"] = sendpolicy.rtf_summary(elapsed, t_cur, pol.step_ns) if len(rows) > 1 else None
    rec["gaps"] = sendpolicy.gaps(frames, t_cur, pol.cap_ns)
    rec["skipped_frames"] = sendpolicy.skipped_frames(frames)
    rec["segments"] = [[SEG, 0, len(rows) - 1]] if rows else []


def _listener_record(found: List[Dict[str, Any]]) -> List[str]:
    return ["%s:%s" % (x.get("LocalAddress"), x.get("LocalPort")) for x in found]


def take(name: str, *, carla: Any, take_root: Path, host: str, contract: Any, clock_ns: Callable[[], int],
         sleep: Callable[[float], None], fwcheck_line: str, listeners: Optional[Listeners], max_frames: Optional[int] = None) -> int:
    """One passive take (the module docstring). Returns 0 when it completed, 1 when it was refused or failed, 130 on
    Ctrl-C. listeners: the reader of this process's listening sockets (None: the check is not run, off Windows)."""
    pol = sendpolicy.Policy.from_contract(contract)
    tdir = take_root / name
    tdir.mkdir(parents=True, exist_ok=False)
    info = time.get_clock_info("perf_counter")
    heard: Dict[str, Any] = {"start": NOT_RUN, "end": NOT_RUN} if listeners is None else {"start": None, "end": None}
    rec: Dict[str, Any] = {k: None for k in CAPTURE_KEYS}
    rec.update({
        "format": FORMAT, "mode": MODE, "name": name, "blueprint": BLUEPRINT, "role_name": ROLE_NAME, "world_settings": [],
        "listeners": heard,
        "clock": {"function": "time.perf_counter_ns" if clock_ns is time.perf_counter_ns else "a stand-in for time.perf_counter_ns",
                  "info": {k: getattr(info, k) for k in ("implementation", "monotonic", "adjustable", "resolution")}},
        "steps": 0, "sim_s": 0.0, "gaps": [], "skipped_frames": [], "segments": [], "fwcheck": fwcheck_line,
        "follow_sha256": _sha256_file(Path(__file__)), "completed": False, "errors": []})
    steps_f = open(tdir / "steps.jsonl", "w", encoding="ascii", newline="\n")
    (tdir / "script.jsonl").write_bytes(b"")
    rows: List[Dict[str, Any]] = []
    world: Any = None
    cb_id: Any = None
    feed: Optional[Feed] = None
    interrupted = False

    def read_settings(at: str, after_frame: Optional[int]) -> None:
        got = worldtie.read_back(world.get_settings())
        rec["world_settings"].append({"at": at, "after_frame": after_frame, "settings": got})
        problems = world_problems(got, pol.step_s)
        if problems:
            where = {"attach": "at attach", "end": "at the end, after frame %s" % after_frame}.get(at, "after frame %s" % after_frame)
            raise FollowRefused("the world settings read %s: %s" % (where, "; ".join(problems)))

    def check_listeners(when: str) -> None:
        if listeners is None:
            return
        try:
            found = listeners()
        except Exception as e:  # noqa: BLE001 - a read that fails is never a pass
            rec["listeners"][when] = "could not be read: %s: %s" % (type(e).__name__, e)
            raise FollowRefused("this client's listening sockets could not be read at the %s: %s" % (when, e)) from e
        rec["listeners"][when] = _listener_record(found)
        if found:
            raise FollowRefused("this client listens at the %s on %s (no Traffic Manager may run)" % (when, ", ".join(rec["listeners"][when])))

    try:
        client = carla.Client(host, PORT)
        client.set_timeout(CLIENT_TIMEOUT_S)
        rec["client_version"] = client.get_client_version()
        rec["server_version"] = client.get_server_version()
        if rec["client_version"] != VERSION or rec["server_version"] != VERSION:
            raise FollowRefused("client %r and server %r are not both %s" % (rec["client_version"], rec["server_version"], VERSION))
        world = client.get_world()
        rec["map"] = world.get_map().name
        read_settings("attach", None)
        egos = [x for x in world.get_actors() if dict(x.attributes).get("role_name") == ROLE_NAME]
        if len(egos) != 1:
            raise FollowRefused("%d actors carry role_name %r: exactly one is followed" % (len(egos), ROLE_NAME))
        ego = egos[0]
        rec["ego_id"] = int(ego.id)
        if ego.type_id != BLUEPRINT:
            raise FollowRefused("the actor with role_name %r is %s, not %s" % (ROLE_NAME, ego.type_id, BLUEPRINT))
        pc = ego.get_physics_control()
        curve = [[float(p.x), float(p.y)] for p in pc.steering_curve]
        problems, own = curve_problems(curve)
        rec["physics_read"] = {"max_steer_angle": [float(w.max_steer_angle) for w in pc.wheels], "steering_curve": curve,
                               "own_points": own}
        if problems:
            raise FollowRefused("; ".join(problems))
        check_listeners("start")
        feed = Feed(ego, clock_ns)
        cb_id = world.on_tick(feed.on_tick)
        last_ns = clock_ns()
        prev_frame: Optional[int] = None
        prev_t_cur: Optional[int] = None
        prev_elapsed: Optional[float] = None
        t0 = 0
        end: Optional[str] = None
        while end is None:
            sleep(POLL_S)
            items, gone, error = feed.take()
            if error:
                raise RuntimeError("the tick callback failed: %s" % error)
            for it in items:
                if prev_frame is not None and it.frame != prev_frame + 1:
                    raise FollowRefused("frame %d after frame %d: not the previous plus one" % (it.frame, prev_frame))
                off_step = step_problem(it.frame, it.delta_s, it.elapsed_s, prev_elapsed, pol.step_ns)
                if off_step:
                    raise FollowRefused("%s: the world's step is not CARLA_STEP_MS / 1000" % off_step)
                t_cur = sendpolicy.became_current(it.t_vals_ns, prev_t_cur, pol.interval_ns)
                if prev_t_cur is None:
                    t0 = t_cur
                row = {"i": len(rows), "frame": it.frame, "elapsed_s": it.elapsed_s, "t_vals_ns": it.t_vals_ns - t0,
                       "t_cur_ns": t_cur - t0, "seg": SEG, "gear": it.gear, "v": it.v, "a": it.a, "fwd": it.fwd, "w": it.w,
                       "steer": it.steer, "throttle": it.throttle, "brake": it.brake, "reverse": it.reverse}
                steps_f.write(json.dumps(row, separators=(",", ":")) + "\n")
                rows.append(row)
                prev_frame, prev_t_cur, prev_elapsed, last_ns = it.frame, t_cur, it.elapsed_s, it.t_vals_ns
                if max_frames is not None and len(rows) >= max_frames:
                    end = "max-frames"
                    break
                if len(rows) % REREAD_FRAMES == 0:
                    read_settings("reread", it.frame)
            if end is None and gone:
                end = "ego-gone"
            elif end is None and clock_ns() - last_ns > IDLE_TIMEOUT_S * 1e9:
                if not rows:
                    raise RuntimeError("no tick arrived within %r s of attaching" % IDLE_TIMEOUT_S)
                end = "idle"
        rec["end"] = end
        read_settings("end", rows[-1]["frame"] if rows else None)     # the frames after the last re-read are read too
        rec["completed"] = True
    except FollowRefused as e:
        rec["refused"] = str(e)
    except KeyboardInterrupt:
        interrupted = True
        rec["errors"].append("KeyboardInterrupt: interrupted")
    except Exception as e:  # noqa: BLE001 - recorded in capture.json; the cleanup and the files follow
        rec["errors"].append("%s: %s" % (type(e).__name__, e))
    finally:
        if feed is not None:
            feed.close()
        if cb_id is not None:
            try:
                world.remove_on_tick(cb_id)
            except Exception as e:  # noqa: BLE001 - the cleanup's error is the record's
                rec["errors"].append("remove_on_tick: %s: %s" % (type(e).__name__, e))
        steps_f.close()
        if rec["client_version"] is not None:
            try:
                check_listeners("end")
            except FollowRefused as e:
                rec["refused"] = rec["refused"] or str(e)
            except KeyboardInterrupt:          # a Ctrl-C during the read (a PowerShell run): the record and its sums still follow
                interrupted = True
                rec["listeners"]["end"] = "not read: interrupted"
                rec["errors"].append("KeyboardInterrupt: during the end listener read")
        if rec["refused"] or rec["errors"]:
            rec["completed"] = False
        _summarise(rec, rows, pol)
        _write_json(tdir / "capture.json", rec)
        sums = "".join("%s  %s\n" % (_sha256_file(tdir / n), n) for n in TAKE_FILES)
        (tdir / "take.sha256").write_text(sums, encoding="ascii", newline="\n")
    if rec["refused"]:
        print("follow010.py: refused: %s" % rec["refused"], file=sys.stderr)
    if interrupted:
        return 130
    return 0 if rec["completed"] else 1


def preflight(name: str, host: str, take_root: Path, windows: bool, fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]],
              contract: Any) -> Tuple[Any, str]:
    """Every refusal before connecting (the module docstring); returns the contract and fwcheck's line."""
    problem = name_problem(name)
    if problem:
        raise FollowRefused(problem)
    line = "not run: not Windows"
    if windows:
        if host != HOST:
            raise FollowRefused("on Windows the client connects to %s only, not %r" % (HOST, host))
        rc, lines = (fwcheck_run or (lambda: fwcheck.run("windows-client", carla=VERSION)))()
        if rc != 0:
            raise FollowRefused("fwcheck --carla %s --for windows-client does not pass: %s" % (VERSION, "; ".join(lines)))
        line = lines[0]
    d = take_root / name
    if d.exists():
        raise FollowRefused("the take directory %s exists: it is never rewritten" % d)
    if frameset.inside_work_tree(d):
        raise FollowRefused("the take directory %s lies inside a git work tree" % d)
    if contract is None:
        try:
            contract = load_contract()
        except vssframe.ContractError as e:
            raise FollowRefused(str(e)) from e
    return contract, line


def main(argv: Optional[Sequence[str]] = None, *, carla: Any = None, take_root: Optional[Path] = None, windows: Optional[bool] = None,
         fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]] = None, listeners: Optional[Listeners] = None,
         clock_ns: Optional[Callable[[], int]] = None, sleep: Optional[Callable[[float], None]] = None, contract: Any = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="follow the ego while the interface ticks and write a passive take")
    t.add_argument("--name", required=True)
    t.add_argument("--host", default=HOST)
    t.add_argument("--max-frames", type=int, default=None, help="end the take after this many frames")
    f = sub.add_parser("fwcheck", help="fwcheck.py's predicate for the 0.10.0 exe (read only)")
    f.add_argument("--for", dest="for_", required=True, choices=fwcheck.FOR_CHOICES)
    f.add_argument("--no-tm", action="store_true", help="P4 not applied: for a client that runs no Traffic Manager")
    a = ap.parse_args(argv)
    on_windows = (os.name == "nt") if windows is None else windows
    if a.cmd == "fwcheck":
        return fwcheck.main(["--for", a.for_, "--carla", VERSION] + (["--no-tm"] if a.no_tm else []), windows=on_windows)
    if a.max_frames is not None and a.max_frames < 1:
        ap.error("--max-frames must be a positive integer")
    root = take_root if take_root is not None else TAKE_ROOT
    try:
        con, line = preflight(a.name, a.host, root, on_windows, fwcheck_run, contract)
    except FollowRefused as e:
        print("follow010.py: refused: %s" % e, file=sys.stderr)
        return 2
    if carla is None:
        try:
            carla = importlib.import_module("carla")
        except ImportError as e:
            print("follow010.py: refused: the carla 0.10.0 client is not importable here (%s)" % e, file=sys.stderr)
            return 2
    reader = listeners if listeners is not None else (own_listeners if on_windows else None)
    return take(a.name, carla=carla, take_root=root, host=a.host, contract=con, clock_ns=clock_ns or time.perf_counter_ns,
                sleep=sleep or time.sleep, fwcheck_line=line, listeners=reader, max_frames=a.max_frames)


if __name__ == "__main__":
    sys.exit(main())
