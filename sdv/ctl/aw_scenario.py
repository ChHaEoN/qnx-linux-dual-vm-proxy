#!/usr/bin/env python3
"""aw_scenario.py -- drive one scenario through Autoware's AD API: localize, route, engage, arrive, clear (sdv/ctl).
rclpy, in the Autoware image.

Phase 8 WP4b's driver for the planning simulator, with the claim node beside it
judging the gate's output. Its scenario files are sdv/ctl/scenarios/<name>.json; their provenance and the reasons for their
timeouts are in sdv/aw/README.md.

    aw_scenario.py --scenario FILE --map-dir DIR --out DIR [--require-claim-node] [--serve GO_FILE]

The scenario (2.8): {"format": 1, "name", "map": {"name", "files": {file: sha256}}, "initial_pose": {"x", "y", "z",
"yaw"}, "goal": {"x", "y", "z", "yaw"}, "timeouts_s": {"localize", "route", "engage", "arrive"}}, the poses in the map
frame (MGRS for the sample map), yaw in rad, each timeout in s. Every file of --map-dir is checked against the
scenario's sha256 before anything else, and the directory must hold exactly the files the scenario names. Then each
step, bounded by its timeout, waits on its state as WP4a read the AD API (W4 section 5):

  localize  /api/localization/initialize with the initial pose, until /api/localization/initialization_state
            is INITIALIZED (3), then until an odometry taken after the request (/localization/kinematic_state) lies
            within START_TOLERANCE_M of the start in x and y: INITIALIZED says nothing of the simulator's pose, and a
            route set while the mission planner's odometry is still at the last goal goes SET then ARRIVED at once. z is
            not compared (a CARLA spawn settles from above). All of it inside localize's budget; a timeout's detail
            names the odometry;
  route     with --require-claim-node, first a subscriber named ctl_claim_node on /control/command/control_cmd (else a
            refusal: no route is set); then THE AVAILABILITY WAIT, below; then /api/routing/set_route_points to the goal,
            until /api/routing/state is SET (2);
  engage    until /api/operation_mode/state says autonomous is available, then /api/operation_mode/change_to_autonomous,
            until the mode is AUTONOMOUS (2);
  arrive    until /api/routing/state is ARRIVED (3);
  clear     /api/routing/clear_route.

A state counts only when the driver took its message after the step's request was sent (the availability: after the
route's), and every message taken since then is looked at in order, so a state that lasted less than one poll is still
seen. Before each request the driver spins until each state topic read against that request (the route's: the routing
state and the availability) has delivered a message, for at most SETTLE_S and never past the step's budget: DDS
delivers a publisher's latched state only once discovery has matched the driver's subscription, so this takes it
before the request, and neither a latched message nor one an earlier step left concludes the step. A topic still
silent at the bound is accepted (it may hold nothing latched yet), and the limit is this: a latched message that
reaches the driver only after the first settle that waited for its topic has ended, or that comes from a publisher
matched only after its topic's first message, is taken after
a request and can conclude that step. A reply with success false ends the drive at once. The claim node is started
before the driver (W4 G2: no Control flows before a route), so a run's first frame is the first Control after
set_route_points. The odometry is on a node of its own in the same process and participant, spun only where the driver reads it (the
wait above, and once at the route's request), so its samples wake nothing through a drive. What waited on the state topics while only that
node was spun is taken in just before the route's mark, up to DRAIN_SPINS spins, a spin that takes nothing ending them, so it is numbered
before the route and never concludes a wait that looks after it.

THE AVAILABILITY WAIT. Before the route's request, a driver that has asked for a route before (Memory: in the serve mode, an earlier
drive of the same process, or drives already in --out, the arm's driver before this process) spins until the newest
/api/operation_mode/state it holds says is_autonomous_mode_available False, inside the route's budget; a timeout is the route step's, its
detail naming the wait, and no route is asked. Autoware publishes that state only when it changes, and its availability follows the
routing status as Autoware's own timer samples it; a clear and the next route that both fall between two samples leave it True with no
message between them, and an engage that wants a message taken after the route's request would then wait out its whole budget, a
harness's failure read as Autoware's. With the route's mark taken while the newest state says False, the only True the engage can take is
a new message, which this route's SET caused. Where the newest state says False already, and in a driver that has never asked for a route
(an arm's first drive, every one-shot run), it goes on at once, and a topic still silent there is left to the settle as before. The wait
only holds the route back or ends the step: no state it reads concludes any step, and the engage's own rule is unchanged. Its one line,
through `availability` ({"at": "route", "available", "waited", "start_mono_ns", "end_mono_ns"}: the availability held before it, null for
none, whether it waited, and CLOCK_MONOTONIC at its start and end), is in no line of scenario.jsonl.

It writes scenario.jsonl into --out, an empty directory outside the repo and every other work tree, made if absent
(its parent must exist: a missing mount is refused, never made): a first line for the map check (the scenario's name
and sha256, each map file's sha256), then one line per step:

    {"step", "outcome": "done"|"timeout"|"refused", "success", "code", "message", "state", "detail", "mono_ns", "ros_ns"}

success, code and message are the step's reply (null for arrive, which sends none), state the state read after its
request, mono_ns CLOCK_MONOTONIC and ros_ns the node's ROS clock when the step ended. Beside it, and never in it,
odometry.jsonl holds the odometry last read at the route's request ({"at": "route", "x", "y", "z", "to_start_m",
"to_goal_m", "mono_ns", "ros_ns"}). Exit 0 arrived (and the route cleared), 3 a step's timeout (the step named: a
service that never appeared, no reply, or the state never reached), 2 a refusal: a bad argument, a scenario not in the
form, a map file's mismatch or an output directory refused (each before rclpy is imported and before anything is made);
rclpy or a message package that cannot be imported, or an output directory that cannot be made or written (each before
anything is made in it); a reply with success false, or no claim node. Any other failure, an exception from rclpy during
the drive, ends in Python's traceback and exit 1, which a harness counts as a failure as it does every code but 0, 2 and
3.

THE SERVE MODE (--serve GO_FILE, off unless given; gate G1's resident driver, PR's dated section, item 15,
sdv/aw/prereg-g1g2.md). One process, one rclpy participant, many drives: the join falls before the first route and never
again. Everything above holds for a drive; what differs is this. --out is the directory that holds the drives (it may
hold earlier ones, and is never made here; it and GO_FILE's directory are refused before the join if this process cannot
write them), and the map is checked once, before the join; each drive's map line carries
that check. The process spins until every state topic has delivered (or SETTLE_S has passed) before it looks for a word,
and spins between drives, so a state left over is taken before the next mark. Each drive starts from one word in
GO_FILE, a plain name and its newline: taken once (read whole, then removed), and its directory is --out/<word>, with
the one-shot form's scenario.jsonl and odometry.jsonl, and AVAILABILITY_LOG, the availability wait's one line, written by
a rename once the drive reaches the wait (the one-shot form writes none); no item reads it, so a write of it the disk will
not take is said on stderr and ends nothing (the drive goes on, or keeps its step's own end). Its answer is the exit file
there, EXIT_FILE, the same exit number as the one-shot form's, one line, by a rename and the last thing the drive writes. run() works from
its own marks, so nothing Autoware said in one drive concludes a step of the next; what one drive leaves the next is only
that it asked for a route (one Memory for the process, which also counts drives already in --out), which makes the next
one's availability wait apply. After a non-zero exit, before the answer: STOP
(/api/operation_mode/change_to_stop), the mode's state read back if it was not STOP, then /api/routing/clear_route, each
answer on a line of AFTER_FAILURE_LOG in the line form above, never in scenario.jsonl, whose last line section 6 reads.
A stop or a clear that fails is written and the next word is waited for: T7 has failed anyway, and the route being clear
keeps the loop's load (a set route refuses the next). After exit 0 there is none: the drive's own clear was its last
step. An exception from rclpy in a drive is its exit 1, with the traceback on stderr. A drive refused before it ran answers 2 in
its directory; where there is no directory that takes that answer the process ends with exit 2, so that docker's code carries the
refusal at once (item 15) and not the bound's 124 of a driver that never answered. SIGTERM ends the process (rclpy's handlers end the
spin, as in the claim node).

rclpy, autoware_adapi_v1_msgs, geometry_msgs and nav_msgs are imported inside main only, and nothing else of sdv/ctl at all; the
step machine runs on any Python against a stand-in for the AD API (tests/test_sdv_aw_scenario.py).

Does not demonstrate: that Autoware drives well, or anything about the claim (the claim node and the monitor judge the
gate's output); that SETTLE_S covers discovery on a loaded host; that the odometry's wait closes the race, since the
mission planner is another subscriber than this one; that a resident driver holds no state in rclpy or below it between
drives; that the availability follows the routing status on another image or host than the one the wait was written for;
any timing: the times it writes order the steps, nothing more.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# --- the AD API as WP4a read it (W4 section 5: Autoware 1.9.0, autoware_adapi_v1_msgs 1.9.2), each name and state once
LOCALIZE_SERVICE = "/api/localization/initialize"
LOCALIZE_SRV = "autoware_adapi_v1_msgs/srv/InitializeLocalization"
LOCALIZATION_STATE_TOPIC = "/api/localization/initialization_state"
LOCALIZATION_STATE_MSG = "autoware_adapi_v1_msgs/msg/LocalizationInitializationState"
INITIALIZED = 3                        # of UNKNOWN 0, UNINITIALIZED 1, INITIALIZING 2, INITIALIZED 3
ROUTE_SERVICE = "/api/routing/set_route_points"
ROUTE_SRV = "autoware_adapi_v1_msgs/srv/SetRoutePoints"
ROUTING_STATE_TOPIC = "/api/routing/state"
ROUTING_STATE_MSG = "autoware_adapi_v1_msgs/msg/RouteState"
SET = 2                                # of UNKNOWN 0, UNSET 1, SET 2, ARRIVED 3, CHANGING 4
ARRIVED = 3
ENGAGE_SERVICE = "/api/operation_mode/change_to_autonomous"
ENGAGE_SRV = "autoware_adapi_v1_msgs/srv/ChangeOperationMode"
OPERATION_MODE_TOPIC = "/api/operation_mode/state"
OPERATION_MODE_MSG = "autoware_adapi_v1_msgs/msg/OperationModeState"
AUTONOMOUS = 2                         # of UNKNOWN 0, STOP 1, AUTONOMOUS 2, LOCAL 3, REMOTE 4
CLEAR_SERVICE = "/api/routing/clear_route"
CLEAR_SRV = "autoware_adapi_v1_msgs/srv/ClearRoute"
STOP_SERVICE = "/api/operation_mode/change_to_stop"     # ENGAGE_SRV's type; the serve mode's, after a failed drive
STOP_MODE = 1
ODOMETRY_TOPIC = "/localization/kinematic_state"        # the mission planner's own input, RELIABLE and VOLATILE
ODOMETRY_MSG = "nav_msgs/msg/Odometry"
STATE_FIELD = "state"                  # the two state messages' field, as WP4a's echoes show it
MODE_FIELD = "mode"                    # OperationModeState's fields, as WP4a's echoes show them
AVAILABLE_FIELD = "is_autonomous_mode_available"
POSE_COV_MSG = "geometry_msgs/msg/PoseWithCovarianceStamped"    # InitializeLocalization's pose[<=1]
POSE_MSG = "geometry_msgs/msg/Pose"                             # SetRoutePoints' goal and waypoints[]
CONTROL_TOPIC = "/control/command/control_cmd"
CLAIM_NODE_NAME = "ctl_claim_node"     # ctl_claim_node.py's NODE_NAME (read, not imported: no module of WP2's is)
# The three state topics' publishers offer RELIABLE, KEEP_LAST 1, TRANSIENT_LOCAL (WP4a's graph reads); the driver's
# subscriptions ask RELIABLE and TRANSIENT_LOCAL too, so the current state arrives once discovery matches, and the
# freshness rule keeps it from concluding a step. They keep the last ten (a design value): state changes that arrive
# between two looks are all kept, where a depth of 1 would drop them to the newest.
STATE_DEPTH = 10
ODOMETRY_DEPTH = 1                     # the newest sample is all the driver reads, and all a reader left unspun should hold

# --- design values, each with its reason
MAP_FRAME = "map"                      # the poses' frame (2.8), as WP4a's initialisation and route requests named it
ALLOW_GOAL_MODIFICATION = False        # the goal is the scenario's, exactly, as WP4a's route request set it
# x and y variance 0.25 m^2 (0.5 m) and yaw variance (pi/12)^2 rad^2, the rest 0: what RViz's 2D Pose Estimate sends
# and WP4a's initialisation sent. A design input, not a reading.
INITIAL_POSE_COVARIANCE = tuple(0.25 if i in (0, 7) else (math.pi / 12) ** 2 if i == 35 else 0.0 for i in range(36))
CLEAR_TIMEOUT_S = 30.0                 # one service call with no state to wait for (2.8 gives clear no timeout key)
CLAIM_NODE_WAIT_S = 10.0               # the claim node runs before the driver starts; this bounds only its discovery
START_TOLERANCE_M = 1.0                # the odometry's distance from the start in x and y, inclusive: the planner's own lateral
                                       # arrival limit in its parameter file, and a scenario's goal lies tens of metres off
POLL_S = 0.1                           # the longest spin between two looks at a state; the AD API's states change at most
                                       # on 10 Hz timers (the transition manager's frequency_hz 10.0, W4 P10)
DRAIN_SPINS = 3 * STATE_DEPTH          # before the route's mark, the most spins to take what waited: one per message three readers hold
DRAIN_SPIN_S = 0.001                   # the wait of each: a spin that waits more than nothing, and only the last of them waits it out
SETTLE_S = 5.0                         # before a request, the longest wait for a state topic's first message (its latched
                                       # state, which DDS delivers once discovery matches): a bound, not a reading; a topic
                                       # still silent then may hold nothing latched yet, and the request goes ahead
MAX_TIMEOUT_S = 3600.0                 # no step of a scenario needs an hour; a larger value is a typo
NODE_NAME = "aw_scenario"
ODOMETRY_NODE_NAME = "aw_scenario_odometry"
SCENARIO_LOG = "scenario.jsonl"
ODOMETRY_LOG = "odometry.jsonl"
EXIT_FILE = "exit"                     # the serve mode's answer in the drive's directory
AFTER_FAILURE_LOG = "after-failure.jsonl"
AVAILABILITY_LOG = "availability.jsonl"   # the serve mode's: the availability wait's one line, beside odometry.jsonl
SCENARIO_FORMAT = 1
EXIT_ARRIVED, EXIT_FAILED, EXIT_REFUSED, EXIT_TIMEOUT = 0, 1, 2, 3
SCENARIO_KEYS = ("format", "name", "map", "initial_pose", "goal", "timeouts_s")
MAP_KEYS = ("name", "files")
POSE_KEYS = ("x", "y", "z", "yaw")
TIMEOUT_KEYS = ("localize", "route", "engage", "arrive")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ScenarioError(RuntimeError):
    """A refusal before anything starts: nothing is made and rclpy is not imported."""


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    yaw: float


@dataclass(frozen=True)
class Scenario:
    name: str
    map_name: str
    map_files: Dict[str, str]
    initial_pose: Pose
    goal: Pose
    timeouts: Dict[str, float]
    sha256: str


@dataclass(frozen=True)
class Reply:
    """A service's ResponseStatus."""
    success: bool
    code: int
    message: str


@dataclass
class Memory:
    """What a driver carries from one drive to the next, and only this: whether it has ever asked for a route (the serve mode keeps one for
    the process, asked already where --out holds earlier drives). Nothing Autoware said is in it, so no step concludes on it; it decides only
    whether the availability wait applies (a driver that has never asked for a route has left no route of its own behind to keep autonomous
    available)."""
    route_asked: bool = False


# --- the scenario file ------------------------------------------------------------------------------------------------

def _object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("the key %r twice" % k)
        out[k] = v
    return out


def _constant(name: str) -> Any:
    raise ValueError("%s is not strict JSON" % name)


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _keys(obj: Any, keys: Sequence[str], what: str) -> List[str]:
    if not isinstance(obj, dict):
        return ["%s is not an object" % what]
    out = []
    missing = [k for k in keys if k not in obj]
    unknown = sorted(k for k in obj if k not in keys)
    if missing:
        out.append("%s lacks %s" % (what, ", ".join(missing)))
    if unknown:
        out.append("%s has unknown keys %s" % (what, ", ".join(unknown)))
    return out


def scenario_problems(doc: Any) -> List[str]:
    """Every way the document fails 2.8's form (an empty list: it is a scenario)."""
    problems = _keys(doc, SCENARIO_KEYS, "the scenario")
    if problems:
        return problems
    if type(doc["format"]) is not int or doc["format"] != SCENARIO_FORMAT:
        problems.append("format is %r, not %d" % (doc["format"], SCENARIO_FORMAT))
    if not isinstance(doc["name"], str) or not NAME_RE.match(doc["name"]):
        problems.append("name %r is not a plain name" % (doc["name"],))
    m = doc["map"]
    found = _keys(m, MAP_KEYS, "map")
    if found:
        problems += found
    else:
        if not isinstance(m["name"], str) or not NAME_RE.match(m["name"]):
            problems.append("map name %r is not a plain name" % (m["name"],))
        files = m["files"]
        if not isinstance(files, dict) or not files:
            problems.append("map files is not a non-empty object")
        else:
            for f, h in files.items():
                if not NAME_RE.match(f):
                    problems.append("map file %r is not a plain file name" % f)
                if not isinstance(h, str) or not SHA256_RE.match(h):
                    problems.append("map file %s: %r is not a lower-case sha256" % (f, h))
    for key in ("initial_pose", "goal"):
        found = _keys(doc[key], POSE_KEYS, key)
        if found:
            problems += found
            continue
        for k in POSE_KEYS:
            if not _number(doc[key][k]):
                problems.append("%s.%s %r is not a finite number" % (key, k, doc[key][k]))
        if _number(doc[key]["yaw"]) and not -math.pi <= doc[key]["yaw"] <= math.pi:
            problems.append("%s.yaw %r is outside [-pi, pi]" % (key, doc[key]["yaw"]))
    found = _keys(doc["timeouts_s"], TIMEOUT_KEYS, "timeouts_s")
    if found:
        problems += found
    else:
        for k in TIMEOUT_KEYS:
            v = doc["timeouts_s"][k]
            if not _number(v) or not 0 < v <= MAX_TIMEOUT_S:
                problems.append("timeouts_s.%s %r is not a number in (0, %g]" % (k, v, MAX_TIMEOUT_S))
    return problems


def _pose(d: Mapping[str, Any]) -> Pose:
    return Pose(float(d["x"]), float(d["y"]), float(d["z"]), float(d["yaw"]))


def load_scenario(path: Any) -> Scenario:
    """The scenario file, strict JSON in 2.8's form, or ScenarioError."""
    p = Path(path)
    try:
        raw = p.read_bytes()
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except (OSError, UnicodeDecodeError, ValueError) as err:
        raise ScenarioError("refused: the scenario %s: %s" % (p, err)) from err
    problems = scenario_problems(doc)
    if problems:
        raise ScenarioError("refused: the scenario %s: %s" % (p, "; ".join(problems)))
    return Scenario(name=doc["name"], map_name=doc["map"]["name"], map_files=dict(doc["map"]["files"]),
                    initial_pose=_pose(doc["initial_pose"]), goal=_pose(doc["goal"]),
                    timeouts={k: float(doc["timeouts_s"][k]) for k in TIMEOUT_KEYS}, sha256=hashlib.sha256(raw).hexdigest())


# --- the map and the output directory -----------------------------------------------------------------------------------

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_map(sc: Scenario, map_dir: Any) -> Dict[str, str]:
    """Each file of the map directory with its sha256, or ScenarioError: the directory must hold exactly the scenario's
    files, each a regular file whose sha256 is the scenario's."""
    d = Path(map_dir)
    if not d.is_dir():
        raise ScenarioError("refused: the map directory %s is not a directory" % d)
    present = set(os.listdir(d))
    problems = []
    missing = sorted(set(sc.map_files) - present)
    unlisted = sorted(present - set(sc.map_files))
    if missing:
        problems.append("missing from %s: %s" % (d, ", ".join(missing)))
    if unlisted:
        problems.append("in %s but not in the scenario: %s" % (d, ", ".join(unlisted)))
    found: Dict[str, str] = {}
    for name in sorted(set(sc.map_files) & present):
        p = d / name
        if not p.is_file():
            problems.append("%s is not a regular file" % name)
            continue
        found[name] = file_sha256(p)
        if found[name] != sc.map_files[name]:
            problems.append("%s has sha256 %s, not the scenario's %s" % (name, found[name], sc.map_files[name]))
    if problems:
        raise ScenarioError("refused: the map: %s" % "; ".join(problems))
    return found


def work_tree_of(path: Path) -> Optional[Path]:
    """The repo, or any git work tree, that holds this path (a .git entry in it or an ancestor), else None. Symbolic
    links are followed first (a part that is absent is taken as it stands): a link into a work tree is inside it."""
    p = Path(path).expanduser().resolve()
    for d in (p,) + tuple(p.parents):
        if d == REPO or (d / ".git").exists():
            return d
    return None


def check_out(path: Any) -> Path:
    """The output directory as an absolute path, or ScenarioError: never inside the repo or another work tree, its
    parent a directory (a missing mount is refused, never made), and empty if it exists (a dangling link is not an
    empty directory). Nothing is made here."""
    d = Path(path).expanduser().absolute()
    wt = work_tree_of(d)
    if wt is not None:
        raise ScenarioError("refused: the output directory %s is inside the work tree %s" % (d, wt))
    if not d.parent.is_dir():
        raise ScenarioError("refused: the output directory %s: its parent is not a directory" % d)
    if os.path.lexists(d) and (not d.is_dir() or any(d.iterdir())):
        raise ScenarioError("refused: %s exists and is not an empty directory" % d)
    return d


# --- the requests, as plain fields --------------------------------------------------------------------------------------

def quaternion(yaw: float) -> Dict[str, float]:
    """A rotation by yaw [rad] about the map's z axis."""
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2.0), "w": math.cos(yaw / 2.0)}


def pose_fields(p: Pose) -> Dict[str, Any]:
    return {"position": {"x": float(p.x), "y": float(p.y), "z": float(p.z)}, "orientation": quaternion(float(p.yaw))}


def initialize_request(p: Pose) -> Dict[str, Any]:
    """InitializeLocalization's request: one PoseWithCovarianceStamped in the map frame (an empty list would ask for
    GNSS, which the planning simulator has not)."""
    return {"pose": [{"header": {"frame_id": MAP_FRAME},
                      "pose": {"pose": pose_fields(p), "covariance": list(INITIAL_POSE_COVARIANCE)}}]}


def route_request(goal: Pose) -> Dict[str, Any]:
    """SetRoutePoints' request: the goal in the map frame, not to be modified, and no waypoint."""
    return {"header": {"frame_id": MAP_FRAME}, "option": {"allow_goal_modification": ALLOW_GOAL_MODIFICATION},
            "goal": pose_fields(goal), "waypoints": []}


def fill(msg: Any, fields: Mapping[str, Any], elements: Mapping[str, Any]) -> Any:
    """Write plain fields into a ROS message: a dict into the nested message already there, a list of dicts as new
    elements of the type `elements` names for that field, anything else as it is. Returns the message."""
    for key, value in fields.items():
        if isinstance(value, dict):
            fill(getattr(msg, key), value, elements)
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            setattr(msg, key, [fill(elements[key](), v, elements) for v in value])
        else:
            setattr(msg, key, value)
    return msg


# --- the step machine ---------------------------------------------------------------------------------------------------

class Api(Protocol):
    """What the step machine needs of the AD API (RosApi in the image; a stand-in in the tests)."""

    def mono_ns(self) -> int: ...

    def ros_ns(self) -> int: ...

    def mark(self) -> int: ...                      # the receive sequence number of the latest state message so far;
                                                    # what came up to it may be forgotten (every wait looks after the latest)

    def latest(self, topic: str) -> Optional[Tuple[int, Any]]: ...   # (its sequence number, the message), or None

    def received(self, topic: str, after: int) -> List[Tuple[int, Any]]: ...   # every (number, message) taken after `after`

    def spin(self, timeout_s: float) -> None: ...   # take in what arrives, for at most timeout_s

    def spin_odometry(self, timeout_s: float) -> None: ...   # take in the newest odometry, for at most timeout_s (nothing else does)

    def wait_for_service(self, service: str, timeout_s: float) -> bool: ...

    def call(self, service: str, fields: Dict[str, Any], timeout_s: float) -> Optional[Reply]: ...   # None: no reply

    def subscribers(self, topic: str) -> List[str]: ...                 # the subscribing nodes' names


class _Stop(Exception):
    """Ends the drive with an exit code; the step's line says why."""

    def __init__(self, code: int, outcome: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.outcome, self.detail = code, outcome, detail


class _Step:
    """One step: its deadline, the reply it got and the state it read after its request."""

    def __init__(self, api: Api, name: str, timeout_s: float) -> None:
        self.api, self.name = api, name
        self.deadline = api.mono_ns() + int(round(timeout_s * 1e9))
        self.reply: Optional[Reply] = None
        self.state: Any = None

    def remaining_s(self) -> float:
        return max(0.0, (self.deadline - self.api.mono_ns()) / 1e9)

    def settle(self, topics: Sequence[str]) -> None:
        """Spins until each topic has delivered a message, for at most SETTLE_S and never past the step's deadline, so a
        publisher's latched state is taken before the request; a topic still silent then is accepted."""
        end = min(self.deadline, self.api.mono_ns() + int(round(SETTLE_S * 1e9)))
        while any(self.api.latest(t) is None for t in topics):
            rem = (end - self.api.mono_ns()) / 1e9
            if rem <= 0.0:
                return
            self.api.spin(min(POLL_S, rem))

    def call(self, service: str, fields: Dict[str, Any], settle: Sequence[str] = (), before: Optional[Callable[[], None]] = None) -> int:
        """The request sent once the service is there and the topics `settle` names have settled; returns the receive
        mark taken just before it was sent. `before` runs just before that mark."""
        if not self.api.wait_for_service(service, self.remaining_s()):
            raise _Stop(EXIT_TIMEOUT, "timeout", "the service %s did not appear" % service)
        self.settle(settle)
        if before is not None:
            before()
        mark = self.api.mark()
        reply = self.api.call(service, fields, self.remaining_s())
        if reply is None:
            raise _Stop(EXIT_TIMEOUT, "timeout", "no reply from %s" % service)
        self.reply = reply
        if not reply.success:
            raise _Stop(EXIT_REFUSED, "refused", "%s replied with success false" % service)
        return mark

    def wait(self, topic: str, field: str, value: Any, after: int) -> None:
        """Until a message on the topic taken after the mark `after` has the field at the value. Every such message is
        looked at, in the order taken, so a state that lasted less than one poll is still seen."""
        while True:
            for seq, msg in self.api.received(topic, after):
                after = seq
                self.state = getattr(msg, field)
                if self.state == value:
                    return
            rem = self.remaining_s()
            if rem <= 0.0:
                raise _Stop(EXIT_TIMEOUT, "timeout", "%s never had %s %r after the request" % (topic, field, value))
            self.api.spin(min(POLL_S, rem))

    def wait_for_start(self, start: Pose, after: int) -> None:
        """Until the newest odometry, taken after the mark `after`, lies within START_TOLERANCE_M of the start in x and y."""
        while True:
            got = self.api.latest(ODOMETRY_TOPIC)
            if got is not None and got[0] > after and _distance(got[1], start) <= START_TOLERANCE_M:
                return
            rem = self.remaining_s()
            if rem <= 0.0:
                raise _Stop(EXIT_TIMEOUT, "timeout", "no odometry newer than the initial-pose request within %g m of the start in x "
                            "and y on %s" % (START_TOLERANCE_M, ODOMETRY_TOPIC))
            self.api.spin_odometry(min(POLL_S, rem))

    def wait_until_unavailable(self, asked: bool, note: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """The availability wait (the module's text says why): where the driver has asked for a route before and the newest operation-mode
        state it holds does not say autonomous is unavailable, spins until it does, inside this step's budget. Its one line goes through
        `note`, whether it ended or timed out."""
        start = self.api.mono_ns()
        got = self.api.latest(OPERATION_MODE_TOPIC)
        held = None if got is None else bool(getattr(got[1], AVAILABLE_FIELD))
        waits = asked and held is not False
        try:
            while waits and not _unavailable(self.api.latest(OPERATION_MODE_TOPIC)):
                rem = self.remaining_s()
                if rem <= 0.0:
                    raise _Stop(EXIT_TIMEOUT, "timeout", "the availability wait: %s never said %s False before the route's request"
                                % (OPERATION_MODE_TOPIC, AVAILABLE_FIELD))
                self.api.spin(min(POLL_S, rem))
        finally:
            if note is not None:
                note({"at": "route", "available": held, "waited": waits, "start_mono_ns": start, "end_mono_ns": self.api.mono_ns()})


def _unavailable(got: Optional[Tuple[int, Any]]) -> bool:
    """A held operation-mode state that says autonomous is not available (no state at all says nothing)."""
    return got is not None and not getattr(got[1], AVAILABLE_FIELD)


def _distance(odometry: Any, p: Pose) -> float:
    """An odometry's distance from a pose in the map's x and y."""
    at = odometry.pose.pose.position
    return math.hypot(at.x - p.x, at.y - p.y)


def await_claim_node(api: Api) -> None:
    """Until the control topic has a subscriber of the claim node's name, else a refusal: no route without it."""
    deadline = api.mono_ns() + int(round(CLAIM_NODE_WAIT_S * 1e9))
    while CLAIM_NODE_NAME not in api.subscribers(CONTROL_TOPIC):
        rem = (deadline - api.mono_ns()) / 1e9
        if rem <= 0.0:
            raise _Stop(EXIT_REFUSED, "refused", "no subscriber named %s on %s within %g s, so no route is set (the claim "
                        "node is started before the route)" % (CLAIM_NODE_NAME, CONTROL_TOPIC, CLAIM_NODE_WAIT_S))
        api.spin(min(POLL_S, rem))


def _line(api: Api, step: _Step, outcome: str, detail: str) -> Dict[str, Any]:
    r = step.reply
    return {"step": step.name, "outcome": outcome, "success": None if r is None else r.success,
            "code": None if r is None else r.code, "message": None if r is None else r.message, "state": step.state,
            "detail": detail, "mono_ns": api.mono_ns(), "ros_ns": api.ros_ns()}


def take_waiting_states(api: Api) -> None:
    """What waited on the state topics' node while only the odometry's was spun, taken in so that it is numbered before the mark that follows:
    a spin that takes nothing ends it, and DRAIN_SPINS is all the three readers can hold."""
    for _ in range(DRAIN_SPINS):
        seen = api.mark()
        api.spin(DRAIN_SPIN_S)
        if api.mark() == seen:
            return


def run(api: Api, sc: Scenario, require_claim_node: bool, log: Callable[[Dict[str, Any]], None],
        note: Optional[Callable[[Dict[str, Any]], None]] = None, *, availability: Optional[Callable[[Dict[str, Any]], None]] = None,
        memory: Optional[Memory] = None) -> int:
    """The five steps in order, one line each through `log`, the odometry at the route's request through `note`, the availability wait's
    line through `availability`; the exit code. Every wait looks after a mark this call took: nothing an earlier call of it left in `api`
    concludes a step. `memory` is the process's (a new one, a driver that has never asked for a route, where none is given)."""
    t = sc.timeouts
    memory = Memory() if memory is None else memory

    def take_waiting_sample() -> None:      # the reader's newest sample is numbered before the mark, so an old pose never counts
        api.spin_odometry(0.0)

    def at_route_request() -> None:
        memory.route_asked = True           # from here on Autoware may hold a route of this driver's
        api.spin_odometry(0.0)
        take_waiting_states(api)
        got = api.latest(ODOMETRY_TOPIC)
        if note is not None and got is not None:
            at = got[1].pose.pose.position
            note({"at": "route", "x": at.x, "y": at.y, "z": at.z, "to_start_m": _distance(got[1], sc.initial_pose),
                  "to_goal_m": _distance(got[1], sc.goal), "mono_ns": api.mono_ns(), "ros_ns": api.ros_ns()})

    step = _Step(api, "localize", t["localize"])
    try:
        mark = step.call(LOCALIZE_SERVICE, initialize_request(sc.initial_pose), (LOCALIZATION_STATE_TOPIC,), take_waiting_sample)
        step.wait(LOCALIZATION_STATE_TOPIC, STATE_FIELD, INITIALIZED, mark)
        step.wait_for_start(sc.initial_pose, mark)
        log(_line(api, step, "done", ""))

        step = _Step(api, "route", t["route"])
        if require_claim_node:
            await_claim_node(api)
            step = _Step(api, "route", t["route"])          # the route's budget starts once the claim node is there
        step.wait_until_unavailable(memory.route_asked, availability)
        # the route's mark also serves the engage's wait for availability, so both topics settle before it
        route_mark = step.call(ROUTE_SERVICE, route_request(sc.goal), (ROUTING_STATE_TOPIC, OPERATION_MODE_TOPIC), at_route_request)
        step.wait(ROUTING_STATE_TOPIC, STATE_FIELD, SET, route_mark)
        log(_line(api, step, "done", ""))

        step = _Step(api, "engage", t["engage"])
        step.wait(OPERATION_MODE_TOPIC, AVAILABLE_FIELD, True, route_mark)
        mark = step.call(ENGAGE_SERVICE, {}, (OPERATION_MODE_TOPIC, ROUTING_STATE_TOPIC))
        step.wait(OPERATION_MODE_TOPIC, MODE_FIELD, AUTONOMOUS, mark)
        log(_line(api, step, "done", ""))

        step = _Step(api, "arrive", t["arrive"])
        step.wait(ROUTING_STATE_TOPIC, STATE_FIELD, ARRIVED, mark)
        log(_line(api, step, "done", ""))

        step = _Step(api, "clear", CLEAR_TIMEOUT_S)
        step.call(CLEAR_SERVICE, {})
        log(_line(api, step, "done", ""))
    except _Stop as stop:
        log(_line(api, step, stop.outcome, stop.detail))
        return stop.code
    return EXIT_ARRIVED


# --- the ROS side -------------------------------------------------------------------------------------------------------

def ros_type(modules: Mapping[str, Any], type_name: str) -> Any:
    """The class of a type named package/kind/Name, from the imported package modules keyed package/kind."""
    package, kind, name = type_name.split("/")
    return getattr(modules[package + "/" + kind], name)


class RosApi:
    """The AD API through rclpy, as the step machine needs it: the three state topics, each message numbered as it is
    taken and kept until the next mark; the odometry on its own node, numbered and only the newest kept; and the five services.
    Built in main once rclpy and the message packages are imported."""

    def __init__(self, rclpy: Any, node: Any, modules: Mapping[str, Any], qos: Any, odometry_node: Any, odometry_qos: Any) -> None:
        self._rclpy, self._node, self._odometry_node = rclpy, node, odometry_node
        self._seq = 0
        self._latest: Dict[str, Tuple[int, Any]] = {}
        self._kept: Dict[str, List[Tuple[int, Any]]] = {}
        for topic, type_name in ((LOCALIZATION_STATE_TOPIC, LOCALIZATION_STATE_MSG), (ROUTING_STATE_TOPIC, ROUTING_STATE_MSG),
                                 (OPERATION_MODE_TOPIC, OPERATION_MODE_MSG)):
            self._kept[topic] = []
            node.create_subscription(ros_type(modules, type_name), topic, self._receiver(topic), qos)
        odometry_node.create_subscription(ros_type(modules, ODOMETRY_MSG), ODOMETRY_TOPIC, self._on_odometry, odometry_qos)
        self._clients: Dict[str, Any] = {}
        self._requests: Dict[str, Any] = {}
        for service, type_name in ((LOCALIZE_SERVICE, LOCALIZE_SRV), (ROUTE_SERVICE, ROUTE_SRV), (ENGAGE_SERVICE, ENGAGE_SRV),
                                   (CLEAR_SERVICE, CLEAR_SRV), (STOP_SERVICE, ENGAGE_SRV)):
            srv = ros_type(modules, type_name)
            self._clients[service] = node.create_client(srv, service)
            self._requests[service] = srv.Request
        self._elements = {"pose": ros_type(modules, POSE_COV_MSG), "waypoints": ros_type(modules, POSE_MSG)}

    def _receiver(self, topic: str) -> Callable[[Any], None]:
        def on_message(msg: Any) -> None:
            self._seq += 1
            self._latest[topic] = (self._seq, msg)
            self._kept[topic].append(self._latest[topic])
        return on_message

    def _on_odometry(self, msg: Any) -> None:
        self._seq += 1
        self._latest[ODOMETRY_TOPIC] = (self._seq, msg)

    def mono_ns(self) -> int:
        return time.monotonic_ns()

    def ros_ns(self) -> int:
        return int(self._node.get_clock().now().nanoseconds)

    def mark(self) -> int:
        """The receive number of the latest message so far; every message kept up to it is dropped, since every wait
        looks only after the latest mark (the latest message of each topic stays readable through `latest`)."""
        for kept in self._kept.values():
            kept.clear()
        return self._seq

    def latest(self, topic: str) -> Optional[Tuple[int, Any]]:
        return self._latest.get(topic)

    def received(self, topic: str, after: int) -> List[Tuple[int, Any]]:
        return [m for m in self._kept[topic] if m[0] > after]

    def spin(self, timeout_s: float) -> None:
        self._rclpy.spin_once(self._node, timeout_sec=timeout_s)

    def spin_odometry(self, timeout_s: float) -> None:
        self._rclpy.spin_once(self._odometry_node, timeout_sec=timeout_s)

    def wait_for_service(self, service: str, timeout_s: float) -> bool:
        return bool(self._clients[service].wait_for_service(timeout_sec=timeout_s))

    def call(self, service: str, fields: Dict[str, Any], timeout_s: float) -> Optional[Reply]:
        future = self._clients[service].call_async(fill(self._requests[service](), fields, self._elements))
        self._rclpy.spin_until_future_complete(self._node, future, timeout_sec=timeout_s)
        if not future.done() or future.result() is None:
            return None
        status = future.result().status
        return Reply(bool(status.success), int(status.code), str(status.message))

    def subscribers(self, topic: str) -> List[str]:
        return [str(i.node_name) for i in self._node.get_subscriptions_info_by_topic(topic)]


# --- main ---------------------------------------------------------------------------------------------------------------

def dumps(obj: Any) -> str:
    """One compact, strict JSON line (no NaN, no Infinity), ASCII."""
    return json.dumps(obj, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def _writer(f: Any) -> Callable[[Dict[str, Any]], None]:
    def write(line: Dict[str, Any]) -> None:
        f.write(dumps(line) + "\n")
        f.flush()
    return write


def _renamed(path: Path) -> Callable[[Dict[str, Any]], None]:
    """A note of one line, whole or not at all: the line written beside it, then a rename. No item reads the note, so a write the disk will
    not take (its file not made, its line not written, its rename refused) is said on stderr, leaves no part of it behind and ends nothing:
    a fault of the harness's own disk there never becomes the drive's exit, and a step's own end (a timeout) stays its line."""
    def write(line: Dict[str, Any]) -> None:
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="ascii", newline="\n") as f:
                f.write(dumps(line) + "\n")
            os.replace(tmp, path)
        except OSError as err:
            print("aw_scenario: %s/%s was not written (no item reads it, so nothing ends on it): %s" % (path.parent.name, path.name, err),
                  file=sys.stderr, flush=True)
            try:
                os.unlink(tmp)
            except OSError:
                pass                        # never made, or not a file: nothing of the note to take back
    return write


def _map_line(sc: Scenario, files: Mapping[str, str], require_claim_node: bool) -> Dict[str, Any]:
    return {"step": "map", "outcome": "done", "success": None, "code": None, "message": None, "state": None,
            "detail": "%d files, each with the scenario's sha256" % len(files), "mono_ns": time.monotonic_ns(),
            "ros_ns": None, "scenario": sc.name, "scenario_sha256": sc.sha256, "files": dict(files),
            "require_claim_node": bool(require_claim_node)}


# --- the serve mode (the module's text says what it is) -----------------------------------------------------------------

def take_go(go: Path) -> Optional[str]:
    """The go file's word, once: None when there is none or its line has not ended; read whole, then removed, so one word
    starts one drive."""
    try:
        text = go.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.endswith("\n"):
        return None
    os.unlink(go)
    return text[:-1]


def write_exit(out: Path, rc: int) -> None:
    """The drive's answer, whole or not at all: a file beside it, then a rename."""
    tmp = out / (EXIT_FILE + ".tmp")
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write("%d\n" % rc)
    os.replace(tmp, out / EXIT_FILE)


def clear_after_failure(api: Api, log: Callable[[Dict[str, Any]], None]) -> None:
    """After a non-zero exit: STOP, since a route in use cannot be cleared, then the clear, each answer through `log`. Each is asked
    whatever the one before it answered, and none of it ends anything."""
    for name, service in (("stop", STOP_SERVICE), ("clear", CLEAR_SERVICE)):
        step = _Step(api, name, CLEAR_TIMEOUT_S)
        try:
            mark = step.call(service, {})
            if service == STOP_SERVICE:
                got = api.latest(OPERATION_MODE_TOPIC)
                if got is None or getattr(got[1], MODE_FIELD) != STOP_MODE:
                    step.wait(OPERATION_MODE_TOPIC, MODE_FIELD, STOP_MODE, mark)
            log(_line(api, step, "done", ""))
        except _Stop as stop:
            log(_line(api, step, stop.outcome, stop.detail))
        except Exception as err:    # rclpy's: the drive's exit still has to reach the harness
            log(_line(api, step, "exception", "%s: %s" % (type(err).__name__, err)))


def serve_drive(api: Api, sc: Scenario, files: Mapping[str, str], root: Path, word: str, require_claim_node: bool,
                memory: Optional[Memory] = None) -> int:
    """One drive of the serve mode, into root/word: its lines, what follows a failure, and last its answer. The exit number. `memory` is the
    process's, the one thing one drive leaves the next."""
    if not NAME_RE.fullmatch(word):         # the whole word: `$` also stands before a trailing newline
        print("aw_scenario: refused: the word %r is no plain name" % word, file=sys.stderr, flush=True)
        return EXIT_REFUSED
    d = root / word
    try:
        out = check_out(d)
        out.mkdir(exist_ok=True)
        f = open(out / SCENARIO_LOG, "x", encoding="utf-8", newline="\n")
        o = open(out / ODOMETRY_LOG, "x", encoding="utf-8", newline="\n")
    except (ScenarioError, OSError) as err:
        print("aw_scenario: refused: the drive %s: %s" % (word, err), file=sys.stderr, flush=True)
        try:
            if not (d / EXIT_FILE).exists():
                write_exit(d, EXIT_REFUSED)
        except OSError:             # nowhere to answer: a driver that goes on idling would read as the drive's 124, a whole bound later
            raise SystemExit(EXIT_REFUSED) from None
        return EXIT_REFUSED
    with f, o:
        log = _writer(f)
        log(_map_line(sc, files, require_claim_node))
        try:
            rc = run(api, sc, require_claim_node, log, _writer(o), availability=_renamed(out / AVAILABILITY_LOG), memory=memory)
        except Exception:           # rclpy's: the one-shot form's traceback and exit 1
            traceback.print_exc()
            rc = EXIT_FAILED
    if rc != EXIT_ARRIVED:
        with open(out / AFTER_FAILURE_LOG, "x", encoding="utf-8", newline="\n") as after:
            clear_after_failure(api, _writer(after))
    write_exit(out, rc)
    print("aw_scenario: %s exit %d" % (word, rc), file=sys.stderr, flush=True)
    return rc


def _earlier_drives(root: Path) -> bool:
    """Whether the drives' directory already holds a drive's directory. A driver started again after one that ended (PR's dated section,
    item 16) is the same arm's driver, and those drives asked for routes (one that ended with exit 0 did; one that did not has failed T7
    already), so its first drive takes the availability wait as any later one does. A directory that cannot be read counts as holding one."""
    try:
        return any(p.is_dir() for p in root.iterdir())
    except OSError:
        return True                         # unread: the wait applies, which costs nothing where the newest state says False


def serve(api: Api, sc: Scenario, files: Mapping[str, str], root: Path, go: Path, require_claim_node: bool, ended: Callable[[], bool]) -> None:
    """Joined first (each state topic delivered, or SETTLE_S gone), then one drive per word, spinning between them, until `ended`. One
    Memory for the process: a route asked in one drive makes the next one's availability wait apply, and so do the drives of the arm's
    driver before this process, where there were any."""
    memory = Memory(route_asked=_earlier_drives(root))
    deadline = api.mono_ns() + int(round(SETTLE_S * 1e9))
    while any(api.latest(t) is None for t in (LOCALIZATION_STATE_TOPIC, ROUTING_STATE_TOPIC, OPERATION_MODE_TOPIC)):
        rem = (deadline - api.mono_ns()) / 1e9
        if rem <= 0.0:
            break
        api.spin(min(POLL_S, rem))
    while not ended():
        word = take_go(go)
        if word is None:
            api.spin(POLL_S)
        else:
            serve_drive(api, sc, files, root, word, require_claim_node, memory)


def check_serve(root: Any, go: Any) -> Tuple[Path, Path]:
    """The drives' directory and the go file as absolute paths, or ScenarioError: the first a directory outside every work tree that may
    hold earlier drives, the second's directory there, each one this process can write (a word is removed from the one, a drive made in the
    other). Nothing is made here."""
    r, g = Path(root).expanduser().absolute(), Path(go).expanduser().absolute()
    wt = work_tree_of(r)
    if wt is not None:
        raise ScenarioError("refused: the drives' directory %s is inside the work tree %s" % (r, wt))
    if not r.is_dir():
        raise ScenarioError("refused: the drives' directory %s is not a directory" % r)
    if not g.parent.is_dir():
        raise ScenarioError("refused: the go file %s: its directory is not a directory" % g)
    for what, d in (("the drives' directory", r), ("the go file's directory", g.parent)):
        if not os.access(d, os.W_OK | os.X_OK):
            raise ScenarioError("refused: %s %s: this process cannot write there" % (what, d))
    return r, g


def argument_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aw_scenario.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, help="the scenario file (sdv/ctl/scenarios/<name>.json)")
    ap.add_argument("--map-dir", required=True, help="the map directory Autoware loads, every file of it named in the scenario")
    ap.add_argument("--out", required=True, help="the run directory for scenario.jsonl (outside every work tree; empty); with --serve, the "
                    "directory that holds each drive's")
    ap.add_argument("--require-claim-node", action="store_true",
                    help="refuse to set the route unless %s subscribes to %s" % (CLAIM_NODE_NAME, CONTROL_TOPIC))
    ap.add_argument("--serve", metavar="GO_FILE", help="stay resident: one drive per word in this file, answered in the drive's directory")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        if args.serve is None:
            out = check_out(args.out)
        else:
            root, go = check_serve(args.out, args.serve)
        sc = load_scenario(args.scenario)
        files = check_map(sc, args.map_dir)
    except ScenarioError as err:
        print("aw_scenario: %s" % err, file=sys.stderr, flush=True)
        return EXIT_REFUSED
    try:
        import rclpy
        from autoware_adapi_v1_msgs import msg as adapi_msg
        from autoware_adapi_v1_msgs import srv as adapi_srv
        from geometry_msgs import msg as geometry_msg
        from nav_msgs import msg as nav_msg
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    except ImportError as err:
        print("aw_scenario: refused: rclpy or the message packages cannot be imported: %s" % err, file=sys.stderr, flush=True)
        return EXIT_REFUSED
    modules = {"autoware_adapi_v1_msgs/msg": adapi_msg, "autoware_adapi_v1_msgs/srv": adapi_srv,
               "geometry_msgs/msg": geometry_msg, "nav_msgs/msg": nav_msg}

    def ros_api() -> Tuple[Any, Any, RosApi]:
        rclpy.init(args=None)
        node = Node(NODE_NAME)
        odometry_node = Node(ODOMETRY_NODE_NAME, start_parameter_services=False, enable_rosout=False)
        qos = QoSProfile(depth=STATE_DEPTH, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        odometry_qos = QoSProfile(depth=ODOMETRY_DEPTH, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)
        return node, odometry_node, RosApi(rclpy, node, modules, qos, odometry_node, odometry_qos)

    if args.serve is not None:
        node, odometry_node, api = ros_api()
        try:
            serve(api, sc, files, root, go, bool(args.require_claim_node), lambda: not rclpy.ok())
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            odometry_node.destroy_node()
            node.destroy_node()
            rclpy.try_shutdown()
        return EXIT_ARRIVED
    try:
        out.mkdir(exist_ok=True)
        f = open(out / SCENARIO_LOG, "x", encoding="utf-8", newline="\n")
        o = open(out / ODOMETRY_LOG, "x", encoding="utf-8", newline="\n")
    except OSError as err:
        print("aw_scenario: refused: the output directory %s: %s" % (out, err), file=sys.stderr, flush=True)
        return EXIT_REFUSED
    last: Dict[str, Any] = {}
    with f, o:
        write = _writer(f)

        def log(line: Dict[str, Any]) -> None:
            last.clear()
            last.update(line)
            write(line)

        log(_map_line(sc, files, bool(args.require_claim_node)))
        node, odometry_node, api = ros_api()
        try:
            rc = run(api, sc, bool(args.require_claim_node), log, _writer(o))
        finally:
            odometry_node.destroy_node()
            node.destroy_node()
            rclpy.try_shutdown()
    if rc == EXIT_ARRIVED:
        print("aw_scenario: %s arrived and its route cleared" % sc.name, file=sys.stderr, flush=True)
    else:
        print("aw_scenario: %s in step %s: %s" % (last.get("outcome"), last.get("step"), last.get("detail")), file=sys.stderr,
              flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
