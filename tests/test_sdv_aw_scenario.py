"""Phase 8 WP4b 7.1 (the Phase 8 specification's 2.8): sdv/ctl/aw_scenario.py, the scenario driver, and its first
scenario, tested without ROS.

The driver checks the scenario's map files by sha256, then drives Autoware's AD API: localize, route, engage, arrive,
clear, each step waiting on its READ state (W4 section 5), and writes scenario.jsonl. What is tested, and how:

- The step machine against a stand-in for the AD API on a fake clock (FakeAutoware: services that answer after a
  short call, the three state topics, every message kept with a receive sequence number, the latched states delivered
  only by the first spin or call after their discovery, as rclpy delivers them): the honest drive; each state's
  wait (a step never concludes on an intermediate state, nor on a state beyond the target: the route's CHANGING and
  ARRIVED, the mode's LOCAL and REMOTE; and a withheld target ends in its step's timeout, exit 3);
  each other timeout (a service that never appears, a reply that never comes), each over its own step's budget; a
  reply with `success` false (exit 2, the step and the reply named, no later call); the engage only after the route
  is SET and autonomous is available; a state that was already the target before the step's request (a latched
  message delivered within the settle bound, or one an earlier step left) never concluding the step, and the limit
  the module states (a latched state delivered after that bound can); a silent state topic holding a request back by
  the settle bound only; every state message after a request looked at, so a state that lasted less than one poll is
  still seen; the claim-node check under --require-claim-node (exit 2 with no route set; a late subscriber within the
  wait accepted, and the route asked within one poll of its appearing); each state value and field name read from its
  one constant.
- The AD API's names and state values equal W4's (READ, held below) and each name written once in the module; rclpy
  and the message packages imported inside main only (statically, and in a fresh interpreter); no module of WP2's
  imported; the claim node's name and the topic it subscribes equal to ctl_claim_node.py's, read from its source.
- The scenario file's form (its ranges inclusive: a yaw of -pi or pi, a timeout of exactly MAX_TIMEOUT_S) and every
  refusal (a file that cannot be read too), its sha256 taken over its bytes as written, the map check (every byte of a
  file hashed, one larger than a read too; a hidden file in the directory refused as unlisted) and the output
  directory (outside every work tree, empty, its parent a directory, not a dangling link), each refused before any
  import of a ROS module is even tried (an import hook records every attempt) and before anything is made.
- main against stand-ins for rclpy, autoware_adapi_v1_msgs and geometry_msgs in sys.modules: the node's
  subscriptions and their QoS, its four clients, the requests' fields, the lines it writes and its exit codes; a
  latched target state delivered by the first spin never concluding localize; two state messages one spin delivers
  both looked at; RosApi's numbering, the number a mark returns, its messages after a mark and what a mark forgets;
  every line's ros_ns read from the node's clock; a service that never appears ending in exit 3 with no request sent;
  a reply with success false carried through RosApi as a refusal (its code and message kept, exit 2, no later
  request); each wait for a service given what is left of its step's budget; each wait for a reply given what is left
  of it too, a number and never None, and a request sent once the budget is spent given 0 s and never a negative time
  (rclpy waits without a bound for either, so the step would hang where it must end in exit 3); every spin positive and
  at most one poll; the map line saying whether the claim node was required; a scenario log made after the output
  check never overwritten; an empty --out made before the run (a runbook's mount) used as it is; rclpy that cannot be
  imported and an output directory that cannot be made each a refusal (exit 2) with nothing made.
- The fresh odometry: localize's wait, after INITIALIZED, for an odometry taken after the request within 1 m of the start in x and y, inside
  localize's budget, in every mode; the odometry at the route's request in its own file; its node spun only where it is read.
- The resident driver (--serve, off by default): one word, one drive, one exit file written by a rename and last; one init, one map check; a
  second drive in one process reading nothing of the first; the serve loop's STOP then clear after a non-zero exit, never after exit 0, its
  answers in their own file, and a failure of either no end of the loop.
- The availability wait before the route: against a stand-in whose operation-mode state is published only when it changes and whose
  availability follows the routing status as a timer samples it on a fixed grid, a clear and the next route inside one sample engage with
  the wait and time out at the engage without it, and a gap that holds a sample engages either way; a driver that has never asked for a route
  goes on at once; an availability that never turns False is the route step's timeout, the wait named, with no route asked and no engage; a
  real refusal of the engage stays the engage's; the wait after the claim node's wait (a claim node gone is the refusal, not the wait's
  timeout); a route asked and never answered counted as asked; a drive that ended before its route leaving the next no wait, and the one-shot
  form never waiting; the note in availability.jsonl, its line's form, its rename and its absence from scenario.jsonl, and a write of it
  that the disk will not take ending nothing.
- The first scenario: W4 G11's drive on lanelet 102, its poses as WP4a's pose_from_map.py prints them (lanelet 102 at
  s 0.3 and 0.9, held below), its map files' sha256 as WP4a's map-manifest.txt holds them, its timeouts the design
  values the README gives reasons for. The driver's own three bounds (30 s for the clear, 10 s for the claim node's
  discovery, 5 s for a state topic's first message) are held to the reasons the README gives for them.

What this does NOT show: that the driver drives a real Autoware (WP4b 7.2's runs); that the stand-ins behave as
Autoware's AD API does beyond the names, types, states and QoS W4 read; that the timeouts suit a loaded host; any
timing (the fake clock only orders events).
"""
import ast
import errno
import hashlib
import importlib
import importlib.abc
import json
import math
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CTL_DIR = REPO / "sdv" / "ctl"
SCENARIOS = CTL_DIR / "scenarios"
DRIVER = CTL_DIR / "aw_scenario.py"
FIRST = SCENARIOS / "sample-lanelet-102.json"
S = 1_000_000_000

# The AD API names, message types, state constants and fields the driver uses.
# These reference strings keep the driver and its stand-ins on the same interface.
READ = {
    "LOCALIZE_SERVICE": "/api/localization/initialize",
    "LOCALIZE_SRV": "autoware_adapi_v1_msgs/srv/InitializeLocalization",
    "LOCALIZATION_STATE_TOPIC": "/api/localization/initialization_state",
    "LOCALIZATION_STATE_MSG": "autoware_adapi_v1_msgs/msg/LocalizationInitializationState",
    "ROUTE_SERVICE": "/api/routing/set_route_points",
    "ROUTE_SRV": "autoware_adapi_v1_msgs/srv/SetRoutePoints",
    "ROUTING_STATE_TOPIC": "/api/routing/state",
    "ROUTING_STATE_MSG": "autoware_adapi_v1_msgs/msg/RouteState",
    "ENGAGE_SERVICE": "/api/operation_mode/change_to_autonomous",
    "ENGAGE_SRV": "autoware_adapi_v1_msgs/srv/ChangeOperationMode",
    "OPERATION_MODE_TOPIC": "/api/operation_mode/state",
    "OPERATION_MODE_MSG": "autoware_adapi_v1_msgs/msg/OperationModeState",
    "CLEAR_SERVICE": "/api/routing/clear_route",
    "CLEAR_SRV": "autoware_adapi_v1_msgs/srv/ClearRoute",
    "POSE_COV_MSG": "geometry_msgs/msg/PoseWithCovarianceStamped",
    "POSE_MSG": "geometry_msgs/msg/Pose",
    "CONTROL_TOPIC": "/control/command/control_cmd",
    "STOP_SERVICE": "/api/operation_mode/change_to_stop",       # the stop the serve mode asks for after a failed drive
    "ODOMETRY_TOPIC": "/localization/kinematic_state",          # the mission planner's own input
    "ODOMETRY_MSG": "nav_msgs/msg/Odometry",
    "INITIALIZED": 3,
    "SET": 2,
    "ARRIVED": 3,
    "AUTONOMOUS": 2,
    "STATE_FIELD": "state",
    "MODE_FIELD": "mode",
    "AVAILABLE_FIELD": "is_autonomous_mode_available",
}
NAMES = [k for k, v in READ.items() if isinstance(v, str) and "/" in v]
STATES = ("INITIALIZED", "SET", "ARRIVED", "AUTONOMOUS")
FIELDS = ("STATE_FIELD", "MODE_FIELD", "AVAILABLE_FIELD")
LINE_KEYS = ["step", "outcome", "success", "code", "message", "state", "detail", "mono_ns", "ros_ns"]
STEPS = ["localize", "route", "engage", "arrive", "clear"]
WP2_MODULES = {"ctlclient", "ctlframe", "ctlrules", "ctl_claim_node", "ctl_export", "ctlreplay"}
ROS_MODULES = ("rclpy", "autoware_adapi_v1_msgs", "geometry_msgs", "nav_msgs", "std_msgs", "builtin_interfaces")
ODOMETRY = READ["ODOMETRY_TOPIC"]
STOP_SERVICE = READ["STOP_SERVICE"]

# WP4a's pose_from_map.py on the sample map, lanelet 102 at s 0.3 (the start) and 0.9 (the goal), as it prints them.
POSE_FROM_MAP = {
    "initial_pose": {"x": 3645.437, "y": 73528.763, "z": 18.780, "yaw": 1.697499},
    "goal": {"x": 3637.127, "y": 73594.000, "z": 18.780, "yaw": 1.697499},
    "qz": 0.750454411, "qw": 0.660922217,
}
# WP4a's map-manifest.txt: the four extracted files of sample-map-planning and their sha256.
MAP_MANIFEST = {
    "lanelet2_map.osm": "4fe358f2d1e182dc76de296e5619086f8d8ad2fcab3e6d8f99f6e3d724a84e6d",
    "map_config.yaml": "c7f8caeaad3559d2bc924a0683f36673f72c9e15f315c2e95f371c9ccceb7e39",
    "map_projector_info.yaml": "9753eba4724aa6d41ffa2cc03e8da2d82e9f317dd14da837b0e96a7705e72bfa",
    "pointcloud_map.pcd": "2da791365627241513c56a88a78baaf17d86b5e90febcb8987ec92c9e99ad2c6",
}
# The first scenario's timeouts: design values (their reasons are in sdv/aw/README.md), never a run's figure.
TIMEOUTS = {"localize": 60, "route": 60, "engage": 60, "arrive": 120}


# ============================================================ loading the module

def _import(name):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(CTL_DIR) not in sys.path:
            sys.path.insert(0, str(CTL_DIR))
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def aw():
    return _import("aw_scenario")


# ============================================================ a synthetic scenario and map

def scenario_dict(**over):
    d = {"format": 1, "name": "test-drive",
         "map": {"name": "sample-map-planning", "files": {"a.osm": hashlib.sha256(b"lanelets").hexdigest(),
                                                          "b.yaml": hashlib.sha256(b"projector").hexdigest()}},
         "initial_pose": {"x": 10.0, "y": 20.0, "z": 1.0, "yaw": 0.5},
         "goal": {"x": 10.0, "y": 80.0, "z": 1.0, "yaw": 0.5},
         "timeouts_s": {"localize": 10, "route": 20, "engage": 30, "arrive": 40}}
    d.update(over)
    return d


def write_scenario(tmp_path, d=None, name="scenario.json"):
    p = tmp_path / name
    p.write_text(json.dumps(scenario_dict() if d is None else d), encoding="utf-8")
    return p


def write_map(tmp_path, files=None):
    m = tmp_path / "map"
    m.mkdir()
    for name, data in (files or {"a.osm": b"lanelets", "b.yaml": b"projector"}).items():
        (m / name).write_bytes(data)
    return m


@pytest.fixture
def sc(aw, tmp_path):
    return aw.load_scenario(write_scenario(tmp_path))


# ============================================================ the AD API on a fake clock

class FakeAutoware:
    """The AD API as the step machine sees it (aw_scenario's Api), on a fake clock in ns. The latched states (a fresh
    planning simulator's, or `latched`: a topic left out of it has none) reach the driver `latch_s` after the start and
    are delivered by the first spin or call that passes that time, never before, as rclpy delivers a TRANSIENT_LOCAL
    publisher's sample only once discovery has matched the subscription and a spin takes it. A call takes CALL_S and,
    when it succeeds, schedules its effects (delay after the call, topic, fields). Each message delivered gets the next
    receive sequence number and is kept (`received`). `replies` maps a service to its Reply, or None for no reply at
    all; `down` holds services that never appear; `subscribers` the names on the control topic, `late` one more
    (delay_s, name). The simulator applies a localize's pose: an odometry there reaches the driver ODOM_S after a call
    that succeeds, unless `follow` is False, and publish_at(t_s, ODOMETRY, odometry(x, y, z)) is any other one."""
    CALL_S = 0.05
    LATCH_S = 0.01
    ODOM_S = 0.045
    MAX_ADVANCES = 500_000              # the most a test spins or calls the stand-in: a driver loop with no bound fails here and does not hang

    def __init__(self, aw, replies=None, effects=None, down=(), subscribers=(), late=None, latched=None, latch_s=LATCH_S, follow=True):
        self.aw = aw
        self.follow = follow
        self.t = 0
        self.seq = 0
        self.n = 0
        self.state = {}
        self.kept = {}
        self.queue = []
        self.calls = []
        self.service_waits = []
        self.odometry_spins = []
        self.advances = 0
        self.subscriber_reads = 0
        self.replies = dict(replies or {})
        self.effects = honest_effects(aw)
        self.effects.update(effects or {})
        self.down = set(down)
        self.subs = list(subscribers)
        self.late = late
        for topic, fields in (initial_states(aw) if latched is None else latched).items():
            self.publish_at(latch_s, topic, fields)

    # -- the Api
    def mono_ns(self):
        return self.t

    def ros_ns(self):
        return 7 * 10 ** 17 + self.t

    def mark(self):
        return self.seq

    def latest(self, topic):
        return self.state.get(topic)

    def received(self, topic, after):
        return [m for m in self.kept.get(topic, []) if m[0] > after]

    def spin(self, timeout_s):
        self._advance(timeout_s)

    def wait_for_service(self, service, timeout_s):
        self.service_waits.append((service, self.t))
        if service in self.down:
            self._advance(timeout_s)
            return False
        return True

    def call(self, service, fields, timeout_s):
        snapshot = {t: dict(vars(m)) for t, (_s, m) in self.state.items()}
        self.calls.append(types.SimpleNamespace(service=service, fields=fields, t=self.t, states=snapshot))
        reply = self.replies.get(service, self.aw.Reply(True, 0, ""))
        if reply is None:
            self._advance(timeout_s)
            return None
        if reply.success:
            for delay, topic, f in self.effects.get(service, []):
                self._at(self.t + int(round(delay * S)), topic, f)
            if self.follow and service == READ["LOCALIZE_SERVICE"]:
                at = fields["pose"][0]["pose"]["pose"]["position"]
                self._at(self.t + int(round(self.ODOM_S * S)), ODOMETRY, odometry(at["x"], at["y"], at["z"]))
        self._advance(self.CALL_S)
        return reply

    def spin_odometry(self, timeout_s):
        self.odometry_spins.append((self.t, timeout_s))
        self._advance(timeout_s)

    def subscribers(self, topic):
        self.subscriber_reads += 1
        if topic != self.aw.CONTROL_TOPIC:
            return []
        names = list(self.subs)
        if self.late is not None and self.t >= int(self.late[0] * S):
            names.append(self.late[1])
        return names

    # -- the stand-in's own clock and topics
    def publish_at(self, t_s, topic, fields):
        """A message that reaches the driver at t_s on the fake clock: the next spin or call that passes it delivers it."""
        self._at(int(round(t_s * S)), topic, fields)

    def _at(self, due_ns, topic, fields):
        self.n += 1
        self.queue.append((due_ns, self.n, topic, fields))

    def _deliver(self, topic, fields):
        self.seq += 1
        self.state[topic] = (self.seq, types.SimpleNamespace(**fields))
        self.kept.setdefault(topic, []).append(self.state[topic])

    def _advance(self, dt_s):
        self.advances += 1
        assert self.advances <= self.MAX_ADVANCES, "the stand-in was advanced %d times: a wait of the driver's that has no end" % self.advances
        end = self.t + int(round(dt_s * S))
        self.queue.sort()
        while self.queue and self.queue[0][0] <= end:
            due, _n, topic, fields = self.queue.pop(0)
            self.t = max(self.t, due)
            self._deliver(topic, fields)
        self.t = end

    def services(self):
        return [c.service for c in self.calls]


def odometry(x, y, z=1.0):
    """A nav_msgs/Odometry as far as the driver reads one."""
    ns = types.SimpleNamespace
    return {"pose": ns(pose=ns(position=ns(x=x, y=y, z=z)))}


def initial_states(aw):
    return {aw.LOCALIZATION_STATE_TOPIC: {aw.STATE_FIELD: 1}, aw.ROUTING_STATE_TOPIC: {aw.STATE_FIELD: 1},
            aw.OPERATION_MODE_TOPIC: {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: False}}


def honest_effects(aw):
    """What Autoware's AD API publishes after each request, as W4 G11 saw the states move (the delays made up)."""
    loc, route, mode = aw.LOCALIZATION_STATE_TOPIC, aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    st, md, av = aw.STATE_FIELD, aw.MODE_FIELD, aw.AVAILABLE_FIELD
    return {
        aw.LOCALIZE_SERVICE: [(0.01, loc, {st: 2}), (0.04, loc, {st: aw.INITIALIZED})],
        aw.ROUTE_SERVICE: [(0.2, route, {st: aw.SET}), (1.0, mode, {md: 1, av: True})],
        aw.ENGAGE_SERVICE: [(0.3, mode, {md: aw.AUTONOMOUS, av: False}), (20.0, route, {st: aw.ARRIVED}),
                            (25.0, mode, {md: 1, av: False})],
        aw.CLEAR_SERVICE: [(0.1, route, {st: 1})],
        STOP_SERVICE: [(0.1, mode, {md: 1, av: False})],
    }


def without(effects, topic, field, value):
    return [e for e in effects if not (e[1] == topic and e[2].get(field) == value)]


def drive(aw, sc, require=False, **kw):
    fake = FakeAutoware(aw, **kw)
    lines = []
    rc = aw.run(fake, sc, require, lines.append)
    return rc, lines, fake


# ============================================================ the step machine

def test_the_honest_drive_localizes_routes_engages_arrives_and_clears(aw, sc):
    rc, lines, fake = drive(aw, sc)
    assert rc == aw.EXIT_ARRIVED == 0
    assert fake.services() == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE]
    assert [(x["step"], x["outcome"]) for x in lines] == [(s, "done") for s in STEPS]
    assert all(list(x) == LINE_KEYS for x in lines)
    assert [x["state"] for x in lines] == [aw.INITIALIZED, aw.SET, aw.AUTONOMOUS, aw.ARRIVED, None]
    for x in lines:
        if x["step"] == "arrive":
            assert (x["success"], x["code"], x["message"]) == (None, None, None)
        else:
            assert (x["success"], x["code"], x["message"]) == (True, 0, "")
    monos = [x["mono_ns"] for x in lines]
    assert monos == sorted(monos) and len(set(monos)) == len(monos)
    assert all(isinstance(x["ros_ns"], int) and x["ros_ns"] - x["mono_ns"] == 7 * 10 ** 17 for x in lines)
    assert fake.calls[0].fields == aw.initialize_request(sc.initial_pose)
    assert fake.calls[1].fields == aw.route_request(sc.goal)
    assert fake.calls[2].fields == {} and fake.calls[3].fields == {}
    assert fake.subscriber_reads == 0                         # no claim-node check unless asked


@pytest.mark.parametrize("step", ["localize", "route", "engage-available", "engage-mode", "arrive"])
def test_a_step_waits_for_its_state_and_ends_in_its_timeout_without_it(aw, sc, step):
    """The target state withheld (intermediate states still published): the step keeps waiting over its whole budget,
    then the driver exits 3 naming it and makes no later call."""
    e = honest_effects(aw)
    loc, route, mode = aw.LOCALIZATION_STATE_TOPIC, aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    service, cut, name = {
        "localize": (aw.LOCALIZE_SERVICE, (loc, aw.STATE_FIELD, aw.INITIALIZED), "localize"),
        "route": (aw.ROUTE_SERVICE, (route, aw.STATE_FIELD, aw.SET), "route"),
        "engage-available": (aw.ROUTE_SERVICE, (mode, aw.AVAILABLE_FIELD, True), "engage"),
        "engage-mode": (aw.ENGAGE_SERVICE, (mode, aw.MODE_FIELD, aw.AUTONOMOUS), "engage"),
        "arrive": (aw.ENGAGE_SERVICE, (route, aw.STATE_FIELD, aw.ARRIVED), "arrive"),
    }[step]
    rc, lines, fake = drive(aw, sc, effects={service: without(e[service], *cut)})
    assert rc == aw.EXIT_TIMEOUT == 3
    assert lines[-1]["step"] == name and lines[-1]["outcome"] == "timeout" and lines[-1]["detail"]
    assert [x["step"] for x in lines[:-1]] == STEPS[:STEPS.index(name)]
    later = {"localize": aw.ROUTE_SERVICE, "route": aw.ENGAGE_SERVICE, "engage": aw.CLEAR_SERVICE, "arrive": aw.CLEAR_SERVICE}
    assert later[name] not in fake.services()
    start = lines[-2]["mono_ns"] if len(lines) > 1 else 0
    budget = sc.timeouts[name] * S
    assert budget <= lines[-1]["mono_ns"] - start < budget + S


def test_an_intermediate_state_never_concludes_localize(aw, sc):
    loc = aw.LOCALIZATION_STATE_TOPIC
    rc, lines, fake = drive(aw, sc, effects={aw.LOCALIZE_SERVICE: [(0.01, loc, {aw.STATE_FIELD: 2})]})
    assert rc == 3 and lines[-1]["state"] == 2 and fake.services() == [aw.LOCALIZE_SERVICE]


@pytest.mark.parametrize("case", ["route CHANGING", "route ARRIVED", "engage LOCAL", "engage REMOTE"])
def test_a_state_beyond_the_target_never_concludes_its_step(aw, sc, case):
    """A state above the one a step waits for is not that state (W4 section 5: the route's CHANGING 4 and ARRIVED 3 above SET
    2; the mode's LOCAL 3 and REMOTE 4 above AUTONOMOUS 2): the route or the engage keeps waiting over its whole budget and
    the driver exits 3 naming it, with no later call; a wait for `state >= target` would end them done."""
    e = honest_effects(aw)
    route, mode = aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    st, md, av = aw.STATE_FIELD, aw.MODE_FIELD, aw.AVAILABLE_FIELD
    step, value = {"route CHANGING": ("route", 4), "route ARRIVED": ("route", 3),
                   "engage LOCAL": ("engage", 3), "engage REMOTE": ("engage", 4)}[case]
    if step == "route":
        effects = {aw.ROUTE_SERVICE: [(0.2, route, {st: value}), (1.0, mode, {md: 1, av: True})]}
    else:
        effects = {aw.ENGAGE_SERVICE: [(0.3, mode, {md: value, av: False})] + e[aw.ENGAGE_SERVICE][1:]}
    rc, lines, fake = drive(aw, sc, effects=effects)
    assert rc == aw.EXIT_TIMEOUT == 3 and lines[-1]["step"] == step and lines[-1]["outcome"] == "timeout"
    assert {"route": aw.ENGAGE_SERVICE, "engage": aw.CLEAR_SERVICE}[step] not in fake.services()


@pytest.mark.parametrize("step", ["localize", "route", "engage", "clear"])
@pytest.mark.parametrize("kind", ["service never appears", "no reply"])
def test_a_service_that_never_appears_or_never_replies_ends_in_its_steps_timeout(aw, sc, step, kind):
    service = {"localize": aw.LOCALIZE_SERVICE, "route": aw.ROUTE_SERVICE, "engage": aw.ENGAGE_SERVICE,
               "clear": aw.CLEAR_SERVICE}[step]
    kw = {"down": {service}} if kind == "service never appears" else {"replies": {service: None}}
    rc, lines, fake = drive(aw, sc, **kw)
    assert rc == 3 and lines[-1]["step"] == step and lines[-1]["outcome"] == "timeout"
    assert service in lines[-1]["detail"]
    budget = (aw.CLEAR_TIMEOUT_S if step == "clear" else sc.timeouts[step]) * S
    start = lines[-2]["mono_ns"] if len(lines) > 1 else 0
    assert budget <= lines[-1]["mono_ns"] - start < budget + S
    if kind == "service never appears":
        assert service not in fake.services()


@pytest.mark.parametrize("step", ["localize", "route", "engage", "clear"])
def test_a_reply_with_success_false_ends_the_drive_as_a_refusal_naming_it(aw, sc, step):
    service = {"localize": aw.LOCALIZE_SERVICE, "route": aw.ROUTE_SERVICE, "engage": aw.ENGAGE_SERVICE,
               "clear": aw.CLEAR_SERVICE}[step]
    rc, lines, fake = drive(aw, sc, replies={service: aw.Reply(False, 7, "not now")})
    assert rc == aw.EXIT_REFUSED == 2
    last = lines[-1]
    assert (last["step"], last["outcome"], last["success"], last["code"], last["message"]) == (step, "refused", False, 7, "not now")
    assert fake.services()[-1] == service                      # no call after it
    assert [x["step"] for x in lines[:-1]] == STEPS[:STEPS.index(step)]


def test_a_reply_with_success_false_is_not_taken_as_done_even_when_the_state_arrives(aw, sc):
    """Autoware's state moving anyway does not make a refused request done."""
    loc = aw.LOCALIZATION_STATE_TOPIC
    fake = FakeAutoware(aw, replies={aw.LOCALIZE_SERVICE: aw.Reply(False, 1, "busy")})
    fake.publish_at(aw.POLL_S + FakeAutoware.CALL_S / 2, loc, {aw.STATE_FIELD: aw.INITIALIZED})   # during the call
    lines = []
    assert aw.run(fake, sc, False, lines.append) == 2 and fake.services() == [aw.LOCALIZE_SERVICE]


def test_the_engage_waits_for_the_route_and_for_autonomous_to_be_available(aw, sc):
    rc, lines, fake = drive(aw, sc)
    engage = fake.calls[2]
    assert engage.service == aw.ENGAGE_SERVICE
    assert engage.states[aw.ROUTING_STATE_TOPIC][aw.STATE_FIELD] == aw.SET
    assert engage.states[aw.OPERATION_MODE_TOPIC][aw.AVAILABLE_FIELD] is True


def test_a_late_availability_holds_the_engage_back(aw, sc):
    e = honest_effects(aw)
    mode = aw.OPERATION_MODE_TOPIC
    route_effects = without(e[aw.ROUTE_SERVICE], mode, aw.AVAILABLE_FIELD, True) + \
        [(8.0, mode, {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True})]
    rc, lines, fake = drive(aw, sc, effects={aw.ROUTE_SERVICE: route_effects})
    assert rc == 0 and fake.calls[2].t - fake.calls[1].t >= 8 * S


def test_an_availability_read_before_the_route_never_lets_the_engage_through(aw, sc):
    """Autonomous already available (latched) before any route, and the route never SET: no engage."""
    latched = initial_states(aw)
    latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True}
    e = honest_effects(aw)
    rc, lines, fake = drive(aw, sc, latched=latched,
                            effects={aw.ROUTE_SERVICE: without(e[aw.ROUTE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.SET)})
    assert rc == 3 and lines[-1]["step"] == "route" and aw.ENGAGE_SERVICE not in fake.services()


@pytest.mark.parametrize("step", ["localize", "route", "engage-available", "engage-mode", "arrive"])
def test_a_state_reached_before_the_steps_request_never_concludes_the_step(aw, sc, step):
    """Each target state made the latest message before its step's request (latched at start, or published by an
    earlier step) and not published again: the step times out instead of taking it."""
    e = honest_effects(aw)
    latched = initial_states(aw)
    loc, route, mode = aw.LOCALIZATION_STATE_TOPIC, aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    st, md, av = aw.STATE_FIELD, aw.MODE_FIELD, aw.AVAILABLE_FIELD
    effects = {}
    if step == "localize":
        latched[loc] = {st: aw.INITIALIZED}
        effects[aw.LOCALIZE_SERVICE] = []
    elif step == "route":
        latched[route] = {st: aw.SET}
        effects[aw.ROUTE_SERVICE] = [(1.0, mode, {md: 1, av: True})]
    elif step == "engage-available":
        effects[aw.LOCALIZE_SERVICE] = e[aw.LOCALIZE_SERVICE] + [(0.02, mode, {md: 1, av: True})]
        effects[aw.ROUTE_SERVICE] = [(0.2, route, {st: aw.SET})]
    elif step == "engage-mode":
        effects[aw.ROUTE_SERVICE] = without(e[aw.ROUTE_SERVICE], mode, av, True) + [(1.0, mode, {md: aw.AUTONOMOUS, av: True})]
        effects[aw.ENGAGE_SERVICE] = without(e[aw.ENGAGE_SERVICE], mode, md, aw.AUTONOMOUS)
    else:
        effects[aw.ROUTE_SERVICE] = e[aw.ROUTE_SERVICE] + [(0.5, route, {st: aw.ARRIVED})]
        effects[aw.ENGAGE_SERVICE] = without(e[aw.ENGAGE_SERVICE], route, st, aw.ARRIVED)
    rc, lines, fake = drive(aw, sc, latched=latched, effects=effects)
    assert rc == 3, lines
    assert lines[-1]["step"] == step.split("-")[0] and lines[-1]["outcome"] == "timeout"


def _latched_initialized(aw):
    latched = initial_states(aw)
    latched[aw.LOCALIZATION_STATE_TOPIC] = {aw.STATE_FIELD: aw.INITIALIZED}
    return latched


@pytest.mark.parametrize("latch_s", [0.01, 1.0, 4.5])
def test_a_latched_state_discovery_delivers_within_the_settle_bound_never_concludes_localize(aw, sc, latch_s):
    """INITIALIZED latched by an earlier drive and delivered some time into the run, as discovery matches (never before
    the first spin), with nothing new published: the driver takes it before its request, so localize times out."""
    rc, lines, fake = drive(aw, sc, latched=_latched_initialized(aw), latch_s=latch_s, effects={aw.LOCALIZE_SERVICE: []})
    assert rc == 3 and [(x["step"], x["outcome"]) for x in lines] == [("localize", "timeout")]
    assert fake.calls[0].t >= latch_s * S                       # the request waited for the latched state
    assert latch_s < aw.SETTLE_S                                # each case within the bound


def test_a_latched_state_delivered_after_the_settle_bound_can_still_conclude_localize(aw, sc):
    """The limit the module states: a latched state that reaches the driver later than SETTLE_S into the step comes
    after the request and concludes it."""
    rc, lines, fake = drive(aw, sc, latched=_latched_initialized(aw), latch_s=aw.SETTLE_S + 1.0,
                            effects={aw.LOCALIZE_SERVICE: []})
    assert rc == 0 and (lines[0]["step"], lines[0]["state"]) == ("localize", aw.INITIALIZED)
    assert aw.SETTLE_S * S <= fake.calls[0].t < (aw.SETTLE_S + aw.POLL_S) * S


@pytest.mark.parametrize("silent", ["localization", "routing", "operation mode"])
def test_a_silent_state_topic_holds_its_steps_request_back_by_the_settle_bound_only(aw, sc, silent):
    """A topic with nothing latched: the first request whose step reads it waits SETTLE_S for its first message, then
    goes ahead, and the drive arrives. Localize reads the localization state; the route's mark serves the routing state
    and the availability, so the route settles both."""
    topic = {"localization": aw.LOCALIZATION_STATE_TOPIC, "routing": aw.ROUTING_STATE_TOPIC,
             "operation mode": aw.OPERATION_MODE_TOPIC}[silent]
    latched = initial_states(aw)
    del latched[topic]
    rc, lines, fake = drive(aw, sc, latched=latched)
    assert rc == 0 and [x["step"] for x in lines] == STEPS
    held = 0 if silent == "localization" else 1
    start = 0 if held == 0 else lines[0]["mono_ns"]
    assert aw.SETTLE_S * S <= fake.calls[held].t - start < (aw.SETTLE_S + aw.POLL_S) * S
    if held == 1:
        assert fake.calls[0].t < aw.SETTLE_S * S                # localize was not held back by another step's topic


def test_every_state_message_after_the_request_is_looked_at_so_a_brief_state_is_seen(aw, sc):
    """AUTONOMOUS 0.30 s after the engage and STOP 0.31 s after it, both delivered by one spin: the engage still sees
    AUTONOMOUS, where a look at the latest message alone would see STOP and time out."""
    mode, route = aw.OPERATION_MODE_TOPIC, aw.ROUTING_STATE_TOPIC
    md, av = aw.MODE_FIELD, aw.AVAILABLE_FIELD
    effects = {aw.ENGAGE_SERVICE: [(0.30, mode, {md: aw.AUTONOMOUS, av: False}), (0.31, mode, {md: 1, av: False}),
                                   (20.0, route, {aw.STATE_FIELD: aw.ARRIVED})]}
    rc, lines, fake = drive(aw, sc, effects=effects)
    assert rc == 0, lines
    assert [x["state"] for x in lines] == [aw.INITIALIZED, aw.SET, aw.AUTONOMOUS, aw.ARRIVED, None]


# ============================================================ the claim-node check

def test_the_route_is_refused_without_the_claim_node_subscribed(aw, sc):
    rc, lines, fake = drive(aw, sc, require=True, subscribers=["vehicle_cmd_gate_listener"])
    assert rc == 2
    assert [(x["step"], x["outcome"]) for x in lines] == [("localize", "done"), ("route", "refused")]
    assert aw.CLAIM_NODE_NAME in lines[-1]["detail"] and aw.CONTROL_TOPIC in lines[-1]["detail"]
    assert fake.services() == [aw.LOCALIZE_SERVICE]            # no route was set
    assert lines[-1]["mono_ns"] - lines[0]["mono_ns"] >= aw.CLAIM_NODE_WAIT_S * S


@pytest.mark.parametrize("name", ["", "ctl_claim_node_2", "claim_node", "CTL_CLAIM_NODE"])
def test_a_subscriber_of_another_name_is_not_the_claim_node(aw, sc, name):
    rc, lines, fake = drive(aw, sc, require=True, subscribers=[name])
    assert rc == 2 and aw.ROUTE_SERVICE not in fake.services()


def test_the_route_is_set_with_the_claim_node_subscribed(aw, sc):
    rc, lines, fake = drive(aw, sc, require=True, subscribers=["simple_planning_simulator", aw.CLAIM_NODE_NAME])
    assert rc == 0 and fake.subscriber_reads >= 1


def test_a_claim_node_discovered_within_the_wait_is_accepted_and_the_route_waits_for_it(aw, sc):
    rc, lines, fake = drive(aw, sc, require=True, late=(3.0, aw.CLAIM_NODE_NAME))
    assert rc == 0 and fake.calls[1].service == aw.ROUTE_SERVICE and fake.calls[1].t >= 3 * S


def test_the_routes_budget_starts_once_the_claim_node_is_there(aw, tmp_path):
    """A route timeout shorter than the claim node's discovery: the route still gets its whole budget after it."""
    d = scenario_dict()
    d["timeouts_s"]["route"] = 5
    s = aw.load_scenario(write_scenario(tmp_path, d))
    rc, lines, fake = drive(aw, s, require=True, late=(8.0, aw.CLAIM_NODE_NAME))
    assert rc == 0 and fake.calls[1].service == aw.ROUTE_SERVICE and fake.calls[1].t >= 8 * S


def test_a_claim_node_discovered_after_the_wait_is_too_late(aw, sc):
    rc, lines, fake = drive(aw, sc, require=True, late=(aw.CLAIM_NODE_WAIT_S + 5.0, aw.CLAIM_NODE_NAME))
    assert rc == 2 and aw.ROUTE_SERVICE not in fake.services()


def test_the_claim_nodes_name_is_ctl_claim_nodes(aw):
    """Its name and the topic it subscribes, each read from ctl_claim_node.py's own module-level constant: the topic is held
    to the claim node's, not only to W4's value, so a change on WP2's side is seen here and not as every run refused."""
    tree = ast.parse((CTL_DIR / "ctl_claim_node.py").read_text(encoding="utf-8"))
    names = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
             and any(isinstance(t, ast.Name) and t.id == "NODE_NAME" for t in n.targets)]
    topics = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
              and any(isinstance(t, ast.Name) and t.id == "CONTROL_TOPIC" for t in n.targets)]
    assert names == [aw.CLAIM_NODE_NAME] == ["ctl_claim_node"]
    assert topics == [aw.CONTROL_TOPIC]


# ============================================================ the names and values, once each

def test_the_api_names_states_and_fields_are_w4s(aw):
    for key, value in READ.items():
        assert getattr(aw, key) == value, key
        assert type(getattr(aw, key)) is type(value), key


def test_each_api_name_is_written_once_in_the_module():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for key in NAMES:
        assert strings.count(READ[key]) == 1, key


@pytest.mark.parametrize("name", STATES)
def test_each_state_value_is_read_from_its_one_constant(aw, sc, monkeypatch, name):
    """The constant moved to a value no state has: a drive whose AD API publishes the moved value arrives, and one that
    publishes the old value does not (the step that waits on it times out)."""
    old_fake = FakeAutoware(aw)
    monkeypatch.setattr(aw, name, 77)
    assert drive(aw, sc)[0] == 0
    lines = []
    assert aw.run(old_fake, sc, False, lines.append) == 3


@pytest.mark.parametrize("name", FIELDS)
def test_each_state_field_is_read_from_its_one_constant(aw, sc, monkeypatch, name):
    monkeypatch.setattr(aw, name, "moved_" + READ[name])
    assert drive(aw, sc)[0] == 0


# ============================================================ imports

def _imports(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, n) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.append((n.module, n))
    return out


def test_ros_is_imported_inside_main_only():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(mains) == 1
    inside = {id(n) for n in ast.walk(mains[0])}
    ros = [(name, n) for name, n in _imports(tree) if name.split(".")[0] in ROS_MODULES]
    assert ros and all(id(n) in inside for _name, n in ros)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("import_module", "__import__")]


def test_the_module_loads_without_ros_and_imports_nothing_of_wp2():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    assert not {name.split(".")[0] for name, _n in _imports(tree)} & WP2_MODULES
    code = ("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r); import aw_scenario; "
            "print(' '.join(sorted(sys.modules)))" % str(CTL_DIR))
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    loaded = {m.split(".")[0] for m in out.stdout.split()}
    assert not loaded & (set(ROS_MODULES) | WP2_MODULES)


# ============================================================ the scenario file

def test_a_scenario_loads_with_its_values(aw, tmp_path):
    p = write_scenario(tmp_path)
    s = aw.load_scenario(p)
    assert s.name == "test-drive" and s.map_name == "sample-map-planning"
    assert s.map_files == scenario_dict()["map"]["files"]
    assert (s.initial_pose.x, s.initial_pose.y, s.initial_pose.z, s.initial_pose.yaw) == (10.0, 20.0, 1.0, 0.5)
    assert (s.goal.x, s.goal.y) == (10.0, 80.0)
    assert s.timeouts == {"localize": 10, "route": 20, "engage": 30, "arrive": 40}
    assert s.sha256 == hashlib.sha256(p.read_bytes()).hexdigest()


def test_the_scenarios_sha256_is_of_its_bytes_as_written(aw, tmp_path):
    """The file written with indentation, as a person would keep it: its sha256 is of those bytes, never of a re-dump."""
    p = tmp_path / "pretty.json"
    p.write_text(json.dumps(scenario_dict(), indent=2) + "\n", encoding="utf-8")
    assert aw.load_scenario(p).sha256 == hashlib.sha256(p.read_bytes()).hexdigest()


def _bad(case):
    d = scenario_dict()
    if case == "unknown key":
        d["note"] = "x"
    elif case == "missing goal":
        del d["goal"]
    elif case == "format 2":
        d["format"] = 2
    elif case == "format true":
        d["format"] = True
    elif case == "format 1.0":
        d["format"] = 1.0
    elif case == "empty name":
        d["name"] = ""
    elif case == "name with a slash":
        d["name"] = "a/b"
    elif case == "map key":
        d["map"]["extra"] = 1
    elif case == "no map files":
        d["map"]["files"] = {}
    elif case == "map file with a slash":
        d["map"]["files"] = {"../a.osm": "0" * 64}
    elif case == "map file hidden":
        d["map"]["files"] = {".a": "0" * 64}
    elif case == "short sha256":
        d["map"]["files"] = {"a.osm": "0" * 63}
    elif case == "upper-case sha256":
        d["map"]["files"] = {"a.osm": "A" * 64}
    elif case == "pose key":
        d["goal"]["w"] = 1.0
    elif case == "pose missing yaw":
        del d["initial_pose"]["yaw"]
    elif case == "pose string":
        d["goal"]["x"] = "10"
    elif case == "pose bool":
        d["goal"]["z"] = False
    elif case == "yaw beyond pi":
        d["goal"]["yaw"] = 3.2
    elif case == "timeout key":
        d["timeouts_s"]["clear"] = 5
    elif case == "timeout missing":
        del d["timeouts_s"]["arrive"]
    elif case == "timeout zero":
        d["timeouts_s"]["route"] = 0
    elif case == "timeout negative":
        d["timeouts_s"]["route"] = -1
    elif case == "timeout over an hour":
        d["timeouts_s"]["arrive"] = 3601
    elif case == "timeout bool":
        d["timeouts_s"]["engage"] = True
    elif case == "initial_pose not an object":
        d["initial_pose"] = [1, 2, 3, 0]
    elif case == "map not an object":
        d["map"] = "sample-map-planning"
    elif case == "map files not an object":
        d["map"]["files"] = ["a.osm"]
    elif case == "name not a string":
        d["name"] = 7
    elif case == "map name with a slash":
        d["map"]["name"] = "maps/sample"
    elif case == "timeouts not an object":
        d["timeouts_s"] = 60
    elif case == "yaw below -pi":
        d["initial_pose"]["yaw"] = -3.2
    elif case == "timeout string":
        d["timeouts_s"]["localize"] = "60"
    elif case == "sha256 not a string":
        d["map"]["files"] = {"a.osm": 5}
    return d


BAD_CASES = ["unknown key", "missing goal", "format 2", "format true", "format 1.0", "empty name", "name with a slash",
             "map key", "no map files", "map file with a slash", "map file hidden", "short sha256", "upper-case sha256",
             "pose key", "pose missing yaw", "pose string", "pose bool", "yaw beyond pi", "timeout key", "timeout missing",
             "timeout zero", "timeout negative", "timeout over an hour", "timeout bool", "initial_pose not an object",
             "map not an object", "map files not an object", "name not a string", "map name with a slash", "timeouts not an object",
             "yaw below -pi", "timeout string", "sha256 not a string"]


@pytest.mark.parametrize("case", BAD_CASES)
def test_a_scenario_not_in_the_form_is_refused(aw, tmp_path, case):
    with pytest.raises(aw.ScenarioError):
        aw.load_scenario(write_scenario(tmp_path, _bad(case)))


@pytest.mark.parametrize("text", ['{"format": 1, "format": 1}', '{"format": NaN}', "[1]", "not json", ""])
def test_a_scenario_file_that_is_not_one_strict_json_object_is_refused(aw, tmp_path, text):
    p = tmp_path / "s.json"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(aw.ScenarioError):
        aw.load_scenario(p)


def test_a_scenario_with_a_key_twice_is_refused_even_when_either_value_would_do(aw, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(scenario_dict())[:-1] + ', "name": "other-drive"}', encoding="utf-8")
    with pytest.raises(aw.ScenarioError, match="twice"):
        aw.load_scenario(p)


def test_a_non_finite_pose_value_is_refused(aw, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(scenario_dict()).replace('"x": 10.0', '"x": Infinity', 1), encoding="utf-8")
    with pytest.raises(aw.ScenarioError):
        aw.load_scenario(p)


# ============================================================ main: the refusals before anything starts

class RosImports(importlib.abc.MetaPathFinder):
    """An import hook first on sys.meta_path: it records every attempt to import a ROS module and refuses it, as an
    interpreter without them would (so no test depends on whether rclpy happens to be installed)."""

    def __init__(self):
        self.tried = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in ROS_MODULES:
            self.tried.append(fullname)
            raise ModuleNotFoundError("No module named %r (refused by the test)" % fullname, name=fullname)
        return None


def _without_ros(monkeypatch):
    for name in list(sys.modules):
        if name.split(".")[0] in ROS_MODULES:
            monkeypatch.delitem(sys.modules, name, raising=False)
    hook = RosImports()
    monkeypatch.setattr(sys, "meta_path", [hook] + sys.meta_path)
    return hook


def _ros_free_main(aw, monkeypatch, argv):
    """main where no ROS module can be imported; the refusals it is used for come before any import is even tried."""
    hook = _without_ros(monkeypatch)
    rc = aw.main(argv)
    assert hook.tried == [] and not [m for m in sys.modules if m.split(".")[0] in ROS_MODULES]
    return rc


def _argv(scenario, map_dir, out, *extra):
    return ["--scenario", str(scenario), "--map-dir", str(map_dir), "--out", str(out)] + list(extra)


@pytest.mark.parametrize("fault", ["wrong hash", "missing file", "extra file", "a directory", "no map dir"])
def test_the_map_is_checked_before_anything_else_and_a_mismatch_refused(aw, tmp_path, monkeypatch, capsys, fault):
    m = write_map(tmp_path)
    if fault == "wrong hash":
        (m / "b.yaml").write_bytes(b"projector, edited")
    elif fault == "missing file":
        (m / "a.osm").unlink()
    elif fault == "extra file":
        (m / "pointcloud_map_metadata.yaml").write_bytes(b"x")
    elif fault == "a directory":
        (m / "b.yaml").unlink()
        (m / "b.yaml").mkdir()
    else:
        m = tmp_path / "absent"
    out = tmp_path / "out"
    rc = _ros_free_main(aw, monkeypatch, _argv(write_scenario(tmp_path), m, out))
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and not out.exists()
    if fault in ("wrong hash", "a directory"):
        assert "b.yaml" in err
    if fault == "extra file":
        assert "pointcloud_map_metadata.yaml" in err


def test_check_map_returns_every_files_sha256(aw, tmp_path, sc):
    assert aw.check_map(sc, write_map(tmp_path)) == scenario_dict()["map"]["files"]


def _work_tree(tmp_path):
    wt = tmp_path / "wt"
    (wt / "sub").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    return wt


@pytest.mark.parametrize("where", ["in the repo", "in a work tree", "through a link into a work tree", "not empty", "a file",
                                   "missing parent", "a dangling link"])
def test_the_output_must_be_an_empty_directory_outside_every_work_tree(aw, tmp_path, monkeypatch, capsys, where):
    """Also: its parent must be a directory (a missing bind mount is refused, never made), and a dangling link is no
    empty directory."""
    out = tmp_path / "out"
    if where == "in the repo":
        out = REPO / "sdv-out" / "refused-scenario-run"
    elif where == "in a work tree":
        out = _work_tree(tmp_path) / "sub" / "run"
    elif where == "through a link into a work tree":
        wt = _work_tree(tmp_path)
        link = tmp_path / "link"
        try:
            link.symlink_to(wt / "sub", target_is_directory=True)
        except OSError:
            pytest.skip("no symbolic links here")
        out = link / "run"
    elif where == "not empty":
        out.mkdir()
        (out / "keep").write_text("x", encoding="utf-8")
    elif where == "a file":
        out.write_text("x", encoding="utf-8")
    elif where == "missing parent":
        out = tmp_path / "absent" / "run"
    else:
        try:
            out.symlink_to(tmp_path / "nowhere", target_is_directory=True)
        except OSError:
            pytest.skip("no symbolic links here")
    rc = _ros_free_main(aw, monkeypatch, _argv(write_scenario(tmp_path), write_map(tmp_path), out))
    assert rc == 2 and "refused" in capsys.readouterr().err
    if where in ("in the repo", "in a work tree", "through a link into a work tree"):
        assert not out.exists()
    if where == "not empty":
        assert sorted(p.name for p in out.iterdir()) == ["keep"]
    if where == "missing parent":
        assert not (tmp_path / "absent").exists()
    if where == "a dangling link":
        assert out.is_symlink() and not (tmp_path / "nowhere").exists()


def test_a_bad_scenario_is_refused_by_main_before_anything_is_made(aw, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    rc = _ros_free_main(aw, monkeypatch, _argv(write_scenario(tmp_path, _bad("format 2")), write_map(tmp_path), out))
    assert rc == 2 and "refused" in capsys.readouterr().err and not out.exists()


# ============================================================ the requests

def _leaves(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, path + "." + k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _leaves(v, "%s[%d]" % (path, i))
    else:
        yield path, x


def test_the_initialize_request_carries_the_pose_in_the_map_frame(aw, sc):
    r = aw.initialize_request(sc.initial_pose)
    assert list(r) == ["pose"] and len(r["pose"]) == 1
    p = r["pose"][0]
    assert p["header"] == {"frame_id": "map"}
    assert p["pose"]["pose"]["position"] == {"x": 10.0, "y": 20.0, "z": 1.0}
    q = p["pose"]["pose"]["orientation"]
    assert q == {"x": 0.0, "y": 0.0, "z": math.sin(0.25), "w": math.cos(0.25)}
    cov = p["pose"]["covariance"]
    assert len(cov) == 36 and cov[0] == cov[7] == 0.25 and cov[35] == (math.pi / 12) ** 2
    assert sum(1 for c in cov if c) == 3


def test_the_route_request_carries_the_goal_unmodified_and_no_waypoint(aw, sc):
    r = aw.route_request(sc.goal)
    assert list(r) == ["header", "option", "goal", "waypoints"]
    assert r["header"] == {"frame_id": "map"} and r["option"] == {"allow_goal_modification": False}
    assert r["goal"]["position"] == {"x": 10.0, "y": 80.0, "z": 1.0} and r["waypoints"] == []


def test_every_number_in_a_request_is_a_float_as_rclpy_requires(aw, tmp_path):
    d = scenario_dict()
    d["initial_pose"] = {"x": 10, "y": 20, "z": 1, "yaw": 0}
    d["goal"] = {"x": 10, "y": 80, "z": 1, "yaw": 0}
    s = aw.load_scenario(write_scenario(tmp_path, d))
    for r in (aw.initialize_request(s.initial_pose), aw.route_request(s.goal)):
        for path, v in _leaves(r):
            assert isinstance(v, (float, str, bool)) and (isinstance(v, bool) or not isinstance(v, int)), path


def test_the_quaternion_from_yaw_agrees_with_pose_from_maps(aw):
    q = aw.quaternion(POSE_FROM_MAP["initial_pose"]["yaw"])
    assert abs(q["z"] - POSE_FROM_MAP["qz"]) < 1e-6 and abs(q["w"] - POSE_FROM_MAP["qw"]) < 1e-6


class Msg:
    """A message stand-in whose nested fields come into being when read, as a ROS message's default-made ones are."""
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        child = Msg()
        object.__setattr__(self, name, child)
        return child


def test_fill_writes_nested_fields_lists_and_elements(aw):
    class Element(Msg):
        pass
    m = aw.fill(Msg(), {"a": {"b": 1.5}, "pose": [{"c": "x"}], "cov": [0.0, 1.0], "none": []}, {"pose": Element})
    assert m.a.b == 1.5 and m.cov == [0.0, 1.0] and m.none == []
    assert len(m.pose) == 1 and isinstance(m.pose[0], Element) and m.pose[0].c == "x"


# ============================================================ main, against stand-ins for rclpy and the messages

def fake_ros(monkeypatch, aw, replies=None, effects=None, subscribers=None, down=(), latched=None, follow=True):
    """Stand-ins for rclpy, autoware_adapi_v1_msgs, geometry_msgs and nav_msgs in sys.modules. The latched states (a fresh
    planning simulator's, or `latched`) wait from each subscription's creation and reach it only through a spin, as
    rclpy delivers them once discovery has matched. spin_once delivers one waiting message (rclpy's runs at most one
    callback); a call completes inside spin_until_future_complete with its Reply, after its effects (topic, fields) are
    queued behind whatever waits and every one is delivered. Real time passes only in the waits. The odometry is the
    simulator's pose: a reader that keeps the newest sample, taken only by a spin of the node that holds its subscription
    (rec.pose: a localize's request sets it, an engage's success the route's goal; None or follow False: no sample), every
    spin counted by node in rec.spins, the odometry node's messages in rec.odometry_taken."""
    rec = types.SimpleNamespace(subscriptions=[], clients={}, requests=[], inits=0, shutdowns=0, destroyed=False,
                                node_name=None, node_names=[], node_kw={}, pending=[], ros_ns=10 ** 18, pose=None, goal=None, spins=[],
                                odometry_taken=0, ok=True, idle=None, looks=0)
    loc, route, mode = aw.LOCALIZATION_STATE_TOPIC, aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    st, md, av = aw.STATE_FIELD, aw.MODE_FIELD, aw.AVAILABLE_FIELD
    honest = {aw.LOCALIZE_SERVICE: [(loc, {st: 2}), (loc, {st: aw.INITIALIZED})],
              aw.ROUTE_SERVICE: [(route, {st: aw.SET}), (mode, {md: 1, av: True})],
              aw.ENGAGE_SERVICE: [(mode, {md: aw.AUTONOMOUS, av: False}), (route, {st: aw.ARRIVED})],
              aw.CLEAR_SERVICE: [(route, {st: 1})], STOP_SERVICE: [(mode, {md: 1, av: False})]}
    honest.update(effects or {})
    replies = replies or {}
    latched = initial_states(aw) if latched is None else latched

    def deliver(at_most=None):
        n = 0
        while rec.pending and (at_most is None or n < at_most):
            topic, fields = rec.pending.pop(0)
            n += 1
            for s in rec.subscriptions:
                if s.topic == topic:
                    s.cb(types.SimpleNamespace(**fields))

    def take_odometry(node):
        """The newest sample, to a subscription of this node alone; 1 when one was taken."""
        got = 0
        if rec.pose is not None and follow:
            for s in rec.subscriptions:
                if s.topic == ODOMETRY and s.node is node:
                    x, y, z = rec.pose
                    s.cb(types.SimpleNamespace(**odometry(x, y, z)))
                    rec.odometry_taken += 1
                    got = 1
        return got

    class Future:
        def __init__(self, service):
            self.service, self._result = service, None

        def done(self):
            return self._result is not None

        def result(self):
            return self._result

    class Client:
        def __init__(self, srv_type, service):
            self.srv_type, self.service = srv_type, service

        def wait_for_service(self, timeout_sec=None):
            if self.service in down:
                time.sleep(timeout_sec or 0)
                return False
            return True

        def call_async(self, req):
            rec.requests.append((self.service, req))
            return Future(self.service)

    class Node:
        def __init__(self, name, **kw):
            rec.node_name = rec.node_name or name
            rec.node_names.append(name)
            rec.node_kw[name] = kw
            self.name = name

        def create_subscription(self, msg_type, topic, cb, qos):
            rec.subscriptions.append(types.SimpleNamespace(msg_type=msg_type, topic=topic, cb=cb, qos=qos, node=self))
            if topic in latched:
                rec.pending.append((topic, latched[topic]))
            return object()

        def create_client(self, srv_type, service):
            rec.clients[service] = Client(srv_type, service)
            return rec.clients[service]

        def get_subscriptions_info_by_topic(self, topic):
            return [types.SimpleNamespace(node_name=n, node_namespace="/") for n in (subscribers or {}).get(topic, [])]

        def get_clock(self):
            def now():
                rec.ros_ns += 1000
                return types.SimpleNamespace(nanoseconds=rec.ros_ns)
            return types.SimpleNamespace(now=now)

        def destroy_node(self):
            rec.destroyed = True

    def spin_once(node, timeout_sec=None):
        rec.spins.append((node.name, timeout_sec))
        if rec.idle is not None:
            rec.idle(node)
        if take_odometry(node):
            return
        if rec.pending:
            deliver(at_most=1)
        else:
            time.sleep(min(timeout_sec or 0, 0.01))

    def spin_until_future_complete(node, future, timeout_sec=None):
        reply = replies.get(future.service, aw.Reply(True, 0, ""))
        if reply is None:
            time.sleep(timeout_sec or 0)
            return
        if reply.success:
            rec.pending.extend(honest.get(future.service, []))
            req = rec.requests[-1][1]
            if future.service == aw.LOCALIZE_SERVICE:
                at = req.pose[0].pose.pose.position
                rec.pose = (at.x, at.y, at.z)
            elif future.service == aw.ROUTE_SERVICE:
                rec.goal = (req.goal.position.x, req.goal.position.y, req.goal.position.z)
            elif future.service == aw.ENGAGE_SERVICE:
                rec.pose = rec.goal
        deliver()
        future._result = types.SimpleNamespace(status=types.SimpleNamespace(success=reply.success, code=reply.code,
                                                                             message=reply.message))

    def init(args=None):
        rec.inits += 1

    def try_shutdown():
        rec.shutdowns += 1

    class ExternalShutdownException(Exception):
        pass

    rclpy = types.ModuleType("rclpy")
    rclpy.init, rclpy.try_shutdown, rclpy.shutdown = init, try_shutdown, try_shutdown
    rclpy.spin_once, rclpy.spin_until_future_complete = spin_once, spin_until_future_complete
    def ok():
        rec.looks += 1
        assert rec.looks <= 200_000, "the serve loop asked %d times whether to go on: it never spins, so nothing in a test can end it" % rec.looks
        return rec.ok
    rclpy.ok = ok
    mods = {"rclpy": rclpy, "rclpy.node": types.ModuleType("rclpy.node"), "rclpy.qos": types.ModuleType("rclpy.qos"),
            "rclpy.executors": types.ModuleType("rclpy.executors")}
    mods["rclpy.node"].Node = Node
    mods["rclpy.executors"].ExternalShutdownException = ExternalShutdownException
    rec.ExternalShutdownException = ExternalShutdownException
    rclpy.executors = mods["rclpy.executors"]

    class QoSProfile:
        def __init__(self, depth=None, history=None, reliability=None, durability=None):
            self.depth, self.history, self.reliability, self.durability = depth, history, reliability, durability

    q = mods["rclpy.qos"]
    q.QoSProfile = QoSProfile
    q.HistoryPolicy = types.SimpleNamespace(KEEP_LAST="keep_last", KEEP_ALL="keep_all")
    q.ReliabilityPolicy = types.SimpleNamespace(RELIABLE="reliable", BEST_EFFORT="best_effort")
    q.DurabilityPolicy = types.SimpleNamespace(VOLATILE="volatile", TRANSIENT_LOCAL="transient_local")
    rclpy.node, rclpy.qos = mods["rclpy.node"], q
    srv, msg, geo = (types.ModuleType("autoware_adapi_v1_msgs.srv"), types.ModuleType("autoware_adapi_v1_msgs.msg"),
                     types.ModuleType("geometry_msgs.msg"))
    for name in ("InitializeLocalization", "SetRoutePoints", "ChangeOperationMode", "ClearRoute"):
        setattr(srv, name, type(name, (), {"Request": type(name + "_Request", (Msg,), {})}))
    for name in ("LocalizationInitializationState", "RouteState", "OperationModeState"):
        setattr(msg, name, type(name, (), {}))
    for name in ("PoseWithCovarianceStamped", "Pose"):
        setattr(geo, name, type(name, (Msg,), {}))
    nav = types.ModuleType("nav_msgs.msg")
    nav.Odometry = type("Odometry", (), {})
    top, gtop, ntop = types.ModuleType("autoware_adapi_v1_msgs"), types.ModuleType("geometry_msgs"), types.ModuleType("nav_msgs")
    top.srv, top.msg, gtop.msg, ntop.msg = srv, msg, geo, nav
    mods.update({"autoware_adapi_v1_msgs": top, "autoware_adapi_v1_msgs.srv": srv, "autoware_adapi_v1_msgs.msg": msg,
                 "geometry_msgs": gtop, "geometry_msgs.msg": geo, "nav_msgs": ntop, "nav_msgs.msg": nav})
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    rec.srv, rec.msg, rec.geo, rec.nav = srv, msg, geo, nav
    return rec


def _lines(out):
    raw = (out / "scenario.jsonl").read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    return [json.loads(x, parse_constant=lambda c: pytest.fail("non-strict JSON: " + c)) for x in raw.decode("utf-8").splitlines()]


def test_main_drives_the_scenario_through_rclpy(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw)
    p, out = write_scenario(tmp_path), tmp_path / "run"
    rc = aw.main(_argv(p, write_map(tmp_path), out))
    assert rc == 0
    assert rec.inits == 1 and rec.shutdowns >= 1 and rec.destroyed and rec.node_name == "aw_scenario"
    # the second node's cost kept small: no parameter services, no rosout
    assert rec.node_kw == {"aw_scenario": {}, "aw_scenario_odometry": {"start_parameter_services": False, "enable_rosout": False}}
    subs = {s.topic: s for s in rec.subscriptions}
    states = (aw.LOCALIZATION_STATE_TOPIC, aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC)
    assert sorted(subs) == sorted(states + (ODOMETRY,))
    assert subs[aw.LOCALIZATION_STATE_TOPIC].msg_type is rec.msg.LocalizationInitializationState
    assert subs[aw.ROUTING_STATE_TOPIC].msg_type is rec.msg.RouteState
    assert subs[aw.OPERATION_MODE_TOPIC].msg_type is rec.msg.OperationModeState
    for t in states:            # reliable and transient-local as the AD API's publishers offer them (W4's graph reads);
        # the last ten kept, so state changes that arrive between two looks are not dropped to the newest
        s = subs[t]
        assert (s.qos.depth, s.qos.history, s.qos.reliability, s.qos.durability) == (10, "keep_last", "reliable", "transient_local")
        assert s.node.name == "aw_scenario"
    o = subs[ODOMETRY]
    assert o.msg_type is rec.nav.Odometry and o.node.name != "aw_scenario"  # its own node: spun only while the driver reads it
    assert (o.qos.depth, o.qos.history, o.qos.reliability, o.qos.durability) == (1, "keep_last", "reliable", "volatile")
    assert {k: c.srv_type for k, c in rec.clients.items()} == {
        aw.LOCALIZE_SERVICE: rec.srv.InitializeLocalization, aw.ROUTE_SERVICE: rec.srv.SetRoutePoints,
        aw.ENGAGE_SERVICE: rec.srv.ChangeOperationMode, aw.CLEAR_SERVICE: rec.srv.ClearRoute,
        STOP_SERVICE: rec.srv.ChangeOperationMode}
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE]
    init_req, route_req = rec.requests[0][1], rec.requests[1][1]
    assert isinstance(init_req, rec.srv.InitializeLocalization.Request)
    assert len(init_req.pose) == 1 and isinstance(init_req.pose[0], rec.geo.PoseWithCovarianceStamped)
    pose = init_req.pose[0]
    assert pose.header.frame_id == "map"
    assert (pose.pose.pose.position.x, pose.pose.pose.position.y, pose.pose.pose.position.z) == (10.0, 20.0, 1.0)
    assert (pose.pose.pose.orientation.z, pose.pose.pose.orientation.w) == (math.sin(0.25), math.cos(0.25))
    assert len(pose.pose.covariance) == 36
    assert isinstance(route_req, rec.srv.SetRoutePoints.Request)
    assert route_req.header.frame_id == "map" and route_req.option.allow_goal_modification is False
    assert (route_req.goal.position.x, route_req.goal.position.y) == (10.0, 80.0) and route_req.waypoints == []
    lines = _lines(out)
    assert [x["step"] for x in lines] == ["map"] + STEPS
    assert all(x["outcome"] == "done" for x in lines)
    first = lines[0]
    assert first["files"] == scenario_dict()["map"]["files"] and first["scenario_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert first["scenario"] == "test-drive" and first["ros_ns"] is None
    assert all(isinstance(x["ros_ns"], int) for x in lines[1:])


def test_main_exits_3_naming_the_step_that_timed_out(aw, tmp_path, monkeypatch, capsys):
    d = scenario_dict()
    d["timeouts_s"] = {"localize": 5, "route": 5, "engage": 5, "arrive": 0.3}
    fake_ros(monkeypatch, aw, effects={aw.ENGAGE_SERVICE: [(aw.OPERATION_MODE_TOPIC, {aw.MODE_FIELD: aw.AUTONOMOUS,
                                                                                       aw.AVAILABLE_FIELD: False})]})
    out = tmp_path / "run"
    rc = aw.main(_argv(write_scenario(tmp_path, d), write_map(tmp_path), out))
    assert rc == 3 and "arrive" in capsys.readouterr().err
    assert _lines(out)[-1]["step"] == "arrive" and _lines(out)[-1]["outcome"] == "timeout"


def test_main_refuses_the_route_without_the_claim_node_and_writes_why(aw, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aw, "CLAIM_NODE_WAIT_S", 0.2)
    rec = fake_ros(monkeypatch, aw, subscribers={aw.CONTROL_TOPIC: ["simple_planning_simulator"]})
    out = tmp_path / "run"
    rc = aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out, "--require-claim-node"))
    assert rc == 2 and "ctl_claim_node" in capsys.readouterr().err
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE]
    assert _lines(out)[-1]["outcome"] == "refused" and rec.destroyed and rec.shutdowns >= 1


def test_main_routes_with_the_claim_node_subscribed(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw, subscribers={aw.CONTROL_TOPIC: ["ctl_claim_node"]})
    rc = aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), tmp_path / "run", "--require-claim-node"))
    assert rc == 0 and len(rec.requests) == 4


def test_main_refuses_a_second_run_into_the_same_output(aw, tmp_path, monkeypatch):
    fake_ros(monkeypatch, aw)
    argv = _argv(write_scenario(tmp_path), write_map(tmp_path), tmp_path / "run")
    assert aw.main(argv) == 0
    assert aw.main(argv) == 2


def test_main_never_overwrites_a_scenario_log_made_after_the_check(aw, tmp_path, monkeypatch):
    """A scenario.jsonl that appears between the output check and the open (another run into the same directory): the
    open fails, the run is refused (exit 2) and the other run's log is as it was."""
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    out.mkdir()
    real = aw.check_out

    def late(path):
        d = real(path)
        (d / "scenario.jsonl").write_text("kept\n", encoding="utf-8")
        return d
    monkeypatch.setattr(aw, "check_out", late)
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 2
    assert (out / "scenario.jsonl").read_text(encoding="utf-8") == "kept\n"


def test_main_writes_the_nodes_ros_time(aw, tmp_path, monkeypatch):
    """Each step line's ros_ns is read from the node's clock (the stand-in's counts up from 10**18 in steps of 1000), never
    from the wall clock."""
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    stamps = [x["ros_ns"] for x in _lines(out)[1:]]
    assert stamps == sorted(set(stamps)) and len(stamps) == len(STEPS)
    assert all(10 ** 18 < t < 10 ** 18 + 10 ** 9 and (t - 10 ** 18) % 1000 == 0 for t in stamps)


def test_main_ends_in_3_when_the_service_never_appears(aw, tmp_path, monkeypatch):
    """Through the real adapter: a service that never appears within the localize budget is that step's timeout (exit 3,
    the line saying the service did not appear) and no request is sent."""
    rec = fake_ros(monkeypatch, aw, down={aw.LOCALIZE_SERVICE})
    out = tmp_path / "run"
    d = scenario_dict()
    d["timeouts_s"]["localize"] = 0.2
    assert aw.main(_argv(write_scenario(tmp_path, d), write_map(tmp_path), out)) == 3
    assert rec.requests == [] and _lines(out)[-1]["detail"].startswith("the service")


def _short(**timeouts):
    d = scenario_dict()
    d["timeouts_s"].update(timeouts)
    return d


def test_main_never_takes_a_latched_state_delivered_by_the_first_spin(aw, tmp_path, monkeypatch, capsys):
    """INITIALIZED latched before the run (a reused simulator) and delivered by the node's first spin, as rclpy delivers
    a TRANSIENT_LOCAL sample, with nothing new published: the driver takes it before its request, so localize times
    out instead of ending done."""
    latched = _latched_initialized(aw)
    rec = fake_ros(monkeypatch, aw, latched=latched, effects={aw.LOCALIZE_SERVICE: []})
    out = tmp_path / "run"
    rc = aw.main(_argv(write_scenario(tmp_path, _short(localize=0.3)), write_map(tmp_path), out))
    assert rc == 3 and "localize" in capsys.readouterr().err
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE]
    assert [(x["step"], x["outcome"]) for x in _lines(out)] == [("map", "done"), ("localize", "timeout")]


def test_main_looks_at_every_state_message_one_spin_delivers(aw, tmp_path, monkeypatch):
    """AUTONOMOUS and then STOP delivered by the engage's one spin: the engage is done on AUTONOMOUS."""
    mode, route = aw.OPERATION_MODE_TOPIC, aw.ROUTING_STATE_TOPIC
    md, av = aw.MODE_FIELD, aw.AVAILABLE_FIELD
    fake_ros(monkeypatch, aw, effects={aw.ENGAGE_SERVICE: [(mode, {md: aw.AUTONOMOUS, av: False}), (mode, {md: 1, av: False}),
                                                           (route, {aw.STATE_FIELD: aw.ARRIVED})]})
    out = tmp_path / "run"
    rc = aw.main(_argv(write_scenario(tmp_path, _short(engage=0.3, arrive=0.3)), write_map(tmp_path), out))
    assert rc == 0 and [x["state"] for x in _lines(out)[1:]] == [aw.INITIALIZED, aw.SET, aw.AUTONOMOUS, aw.ARRIVED, None]


def test_rosapi_numbers_every_message_keeps_those_after_the_mark_and_forgets_the_rest(aw, monkeypatch):
    rec = fake_ros(monkeypatch, aw, latched={})
    modules = {"autoware_adapi_v1_msgs/msg": rec.msg, "autoware_adapi_v1_msgs/srv": rec.srv, "geometry_msgs/msg": rec.geo, "nav_msgs/msg": rec.nav}
    node_cls = sys.modules["rclpy.node"].Node
    api = aw.RosApi(sys.modules["rclpy"], node_cls("t"), modules, None, node_cls("o"), None)
    on = {s.topic: s.cb for s in rec.subscriptions}
    route, mode = aw.ROUTING_STATE_TOPIC, aw.OPERATION_MODE_TOPIC
    m = [types.SimpleNamespace(n=i) for i in range(4)]
    assert api.latest(route) is None and api.received(route, 0) == []
    on[route](m[0])
    assert api.latest(route) == (1, m[0]) and api.received(route, 0) == [(1, m[0])]
    mark = api.mark()
    assert mark == 1 and api.received(route, 0) == [] and api.latest(route) == (1, m[0])   # forgotten; still the latest
    on[route](m[1])
    on[mode](m[2])
    on[route](m[3])
    assert api.received(route, mark) == [(2, m[1]), (4, m[3])] and api.received(mode, mark) == [(3, m[2])]
    assert api.received(route, 2) == [(4, m[3])] and api.latest(route) == (4, m[3]) and api.mark() == 4


def test_rosapi_numbers_each_message_and_marks_the_latest(aw):
    """RosApi built bare, so that only its numbering is under test: a message received before a mark is numbered at most the
    mark and one received after it above it, so a wait that looks only after the mark never takes the earlier one."""
    api = aw.RosApi.__new__(aw.RosApi)
    api._seq, api._latest, api._kept = 0, {}, {aw.ROUTING_STATE_TOPIC: []}
    on_route = api._receiver(aw.ROUTING_STATE_TOPIC)
    on_route(object())
    mark = api.mark()
    assert api.latest(aw.ROUTING_STATE_TOPIC)[0] <= mark
    on_route(object())
    assert api.latest(aw.ROUTING_STATE_TOPIC)[0] > mark


def test_rosapi_numbers_an_odometry_sample_past_the_mark_it_followed(aw):
    """The odometry has its own callback; a sample taken after a mark is numbered above it, or the wait for a fresh one would never take it."""
    api = aw.RosApi.__new__(aw.RosApi)
    api._seq, api._latest, api._kept = 0, {}, {aw.ROUTING_STATE_TOPIC: []}
    api._receiver(aw.ROUTING_STATE_TOPIC)(object())
    mark = api.mark()
    api._on_odometry(object())
    assert api.latest(aw.ODOMETRY_TOPIC)[0] > mark


def test_main_refuses_when_rclpy_cannot_be_imported_and_makes_nothing(aw, tmp_path, monkeypatch, capsys):
    """The driver started where rclpy or a message package is missing: a refusal (exit 2) once the checks have passed,
    with nothing made, never Python's traceback and exit 1."""
    hook = _without_ros(monkeypatch)
    out = tmp_path / "run"
    rc = aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out))
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and "rclpy" in err and hook.tried
    assert not out.exists()


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() == 0,
                    reason="needs a POSIX user that a read-only directory stops")
def test_main_refuses_an_output_directory_it_cannot_make(aw, tmp_path, monkeypatch, capsys):
    rec = fake_ros(monkeypatch, aw)
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        rc = aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), ro / "run"))
    finally:
        ro.chmod(0o755)
    err = capsys.readouterr().err
    assert rc == 2 and "refused" in err and str(ro / "run") in err
    assert not (ro / "run").exists() and rec.inits == 0


# ============================================================ the first scenario

def test_the_first_scenario_is_w4_g11s_drive_on_lanelet_102(aw):
    s = aw.load_scenario(FIRST)
    d = json.loads(FIRST.read_text(encoding="utf-8"))
    assert list(d) == ["format", "name", "map", "initial_pose", "goal", "timeouts_s"]
    assert s.name == FIRST.stem == "sample-lanelet-102" and s.map_name == "sample-map-planning"
    assert d["initial_pose"] == POSE_FROM_MAP["initial_pose"] and d["goal"] == POSE_FROM_MAP["goal"]
    assert d["map"]["files"] == MAP_MANIFEST
    assert d["timeouts_s"] == TIMEOUTS
    ahead = math.hypot(d["goal"]["x"] - d["initial_pose"]["x"], d["goal"]["y"] - d["initial_pose"]["y"])
    assert 60 < ahead < 70                                   # the chosen goal is ahead on the same lanelet
    heading = math.atan2(d["goal"]["y"] - d["initial_pose"]["y"], d["goal"]["x"] - d["initial_pose"]["x"])
    assert abs(heading - d["goal"]["yaw"]) < 0.01            # the goal lies straight ahead along the start's yaw


def test_every_scenario_file_loads_and_is_named_by_its_stem(aw):
    files = sorted(SCENARIOS.iterdir())
    assert [f.name for f in files] == ["sample-lanelet-102.json", "town10-t1.json", "town10-t3.json", "town10-t4.json", "town10-t5.json"]
    for f in files:
        assert aw.load_scenario(f).name == f.stem


def test_the_package_leaves_no_carriage_return_and_no_bytecode():
    for p in [DRIVER, Path(__file__)] + sorted(SCENARIOS.iterdir()):
        assert b"\r" not in p.read_bytes(), p
    assert not (CTL_DIR / "__pycache__").exists() and not (SCENARIOS / "__pycache__").exists()


# ============================================================ the real adapter, the claim wait, the map line, the output's parent

def test_main_carries_a_refused_reply_through_rclpy_as_a_refusal(aw, tmp_path, monkeypatch):
    """Through the real adapter: the route's reply success false, code 5, message "no lane" ends the drive in exit 2 with
    the reply on the route's line, and no engage is asked (a refusal is never taken as an accepted request)."""
    rec = fake_ros(monkeypatch, aw, replies={aw.ROUTE_SERVICE: aw.Reply(False, 5, "no lane")})
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path, _short(route=0.3)), write_map(tmp_path), out)) == 2
    last = _lines(out)[-1]
    assert (last["step"], last["outcome"], last["success"], last["code"], last["message"]) == ("route", "refused", False, 5, "no lane")
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE]


def test_main_gives_each_service_wait_what_is_left_of_its_steps_budget(aw, tmp_path, monkeypatch):
    """Through the real adapter: each wait for a service is given what is left of its step's budget (a new node finds a
    service only while it waits), never no time at all."""
    fake_ros(monkeypatch, aw)
    node_cls = sys.modules["rclpy.node"].Node
    made = node_cls.create_client
    waits = []

    def create_client(self, srv_type, service):
        client = made(self, srv_type, service)
        real = client.wait_for_service

        def wait_for_service(timeout_sec=None):
            waits.append((service, timeout_sec))
            return real(timeout_sec=timeout_sec)
        client.wait_for_service = wait_for_service
        return client
    monkeypatch.setattr(node_cls, "create_client", create_client)
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), tmp_path / "run")) == 0
    budgets = {aw.LOCALIZE_SERVICE: 10, aw.ROUTE_SERVICE: 20, aw.ENGAGE_SERVICE: 30, aw.CLEAR_SERVICE: aw.CLEAR_TIMEOUT_S}
    assert [s for s, _t in waits] == list(budgets)
    for service, t in waits:
        assert budgets[service] - 1 < t <= budgets[service], (service, t)


def test_main_spins_for_a_bounded_positive_time(aw, tmp_path, monkeypatch):
    """Every spin of the state topics' node waits more than nothing and at most POLL_S: never a busy loop, never a long sleep.
    The odometry's node is spun for at most POLL_S too, or for 0 s to take the sample that waits (never None, never negative:
    rclpy waits without a bound for either)."""
    fake_ros(monkeypatch, aw)
    rclpy_mod = sys.modules["rclpy"]
    real = rclpy_mod.spin_once
    spins = []

    def spin_once(node, timeout_sec=None):
        spins.append((node.name, timeout_sec))
        return real(node, timeout_sec=timeout_sec)
    monkeypatch.setattr(rclpy_mod, "spin_once", spin_once)
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), tmp_path / "run")) == 0
    assert spins and all(0 < t <= aw.POLL_S for n, t in spins if n == "aw_scenario"), spins
    assert all(0 <= t <= aw.POLL_S for n, t in spins if n != "aw_scenario"), spins


@pytest.mark.parametrize("required", [False, True])
def test_the_map_line_records_whether_the_claim_node_was_required(aw, tmp_path, monkeypatch, required):
    """The first line of scenario.jsonl says whether --require-claim-node was given, as the run's record of its own rule."""
    fake_ros(monkeypatch, aw, subscribers={aw.CONTROL_TOPIC: [aw.CLAIM_NODE_NAME]})
    out = tmp_path / "run"
    extra = ["--require-claim-node"] if required else []
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out, *extra)) == 0
    assert _lines(out)[0]["require_claim_node"] is required


def test_the_route_is_asked_within_one_poll_of_the_claim_node_appearing(aw, sc):
    """The claim-node wait looks again at least every POLL_S, so the route follows the claim node's discovery at once."""
    rc, lines, fake = drive(aw, sc, require=True, late=(3.0, aw.CLAIM_NODE_NAME))
    assert rc == 0 and 3 * S <= fake.calls[1].t < (3 + 2 * aw.POLL_S) * S


def test_an_output_directory_whose_parent_is_a_file_is_refused_before_any_import(aw, tmp_path, monkeypatch, capsys):
    """A parent that exists but is not a directory is no parent: refused before a ROS import is tried, as a missing one is."""
    (tmp_path / "afile").write_text("x", encoding="utf-8")
    out = tmp_path / "afile" / "run"
    rc = _ros_free_main(aw, monkeypatch, _argv(write_scenario(tmp_path), write_map(tmp_path), out))
    assert rc == 2 and "parent is not a directory" in capsys.readouterr().err


# ============================================================ the reply's bound, the empty --out, the map check, the bounds

def test_main_waits_for_each_reply_at_most_what_is_left_of_its_steps_budget(aw, tmp_path, monkeypatch):
    """Through the real adapter: each wait for a reply is given what is left of its step's budget, a number and never None
    (rclpy waits without a bound for None or a negative time), so a reply that never comes still ends the step in exit 3."""
    fake_ros(monkeypatch, aw)
    rclpy_mod = sys.modules["rclpy"]
    real = rclpy_mod.spin_until_future_complete
    waits = []

    def spin_until_future_complete(node, future, timeout_sec=None):
        waits.append((future.service, timeout_sec))
        return real(node, future, timeout_sec=timeout_sec)
    monkeypatch.setattr(rclpy_mod, "spin_until_future_complete", spin_until_future_complete)
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), tmp_path / "run")) == 0
    budgets = {aw.LOCALIZE_SERVICE: 10, aw.ROUTE_SERVICE: 20, aw.ENGAGE_SERVICE: 30, aw.CLEAR_SERVICE: aw.CLEAR_TIMEOUT_S}
    assert [s for s, _t in waits] == list(budgets)
    for service, t in waits:
        assert isinstance(t, float) and budgets[service] - 1 < t <= budgets[service], (service, t)


def test_a_request_sent_once_its_budget_is_spent_is_given_no_time_never_a_negative_one(aw, tmp_path):
    """The localization state silent and localize's budget shorter than SETTLE_S, on a host whose spins return a little
    late: the settle spends the whole budget, and the request is then given 0 s, never a negative time (which rclpy takes
    as no bound at all), so the step still ends in its timeout (exit 3) when no reply comes."""
    s = aw.load_scenario(write_scenario(tmp_path, _short(localize=2)))
    latched = initial_states(aw)
    del latched[aw.LOCALIZATION_STATE_TOPIC]
    given = []

    class LateSpins(FakeAutoware):
        def spin(self, timeout_s):
            self._advance(timeout_s + 0.001)

        def call(self, service, fields, timeout_s):
            given.append((service, timeout_s))
            return super().call(service, fields, timeout_s)
    fake = LateSpins(aw, replies={aw.LOCALIZE_SERVICE: None}, latched=latched)
    lines = []
    assert aw.run(fake, s, False, lines.append) == 3
    assert given == [(aw.LOCALIZE_SERVICE, 0.0)]
    assert (lines[-1]["step"], lines[-1]["outcome"]) == ("localize", "timeout") and "no reply" in lines[-1]["detail"]


def test_main_writes_into_an_empty_output_directory_made_before_it_starts(aw, tmp_path, monkeypatch):
    """2.8's empty --out: a runbook or harness makes the run's directory (writable for aw) and mounts it before the driver
    starts, so an existing empty directory is used as it is, never refused."""
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    out.mkdir()
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    assert [x["step"] for x in _lines(out)] == ["map"] + STEPS and sorted(p.name for p in out.iterdir()) == ["odometry.jsonl", "scenario.jsonl"]


def test_the_map_check_hashes_every_byte_of_a_file_larger_than_one_read(aw, tmp_path):
    """A file's sha256 covers every chunk, so a file equal to the scenario's in
    its first MiB and different after it is refused."""
    big = bytes(range(256)) * (3 * 4096 + 1)                   # 3 MiB and 256 bytes
    d = scenario_dict()
    d["map"]["files"]["a.osm"] = hashlib.sha256(big).hexdigest()
    s = aw.load_scenario(write_scenario(tmp_path, d))
    assert aw.check_map(s, write_map(tmp_path, {"a.osm": big, "b.yaml": b"projector"}))["a.osm"] == hashlib.sha256(big).hexdigest()
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.osm").write_bytes(big[:-1] + b"\x00")
    (other / "b.yaml").write_bytes(b"projector")
    with pytest.raises(aw.ScenarioError, match="a.osm"):
        aw.check_map(s, other)


def test_a_hidden_file_in_the_map_directory_is_refused_as_unlisted(aw, tmp_path, sc):
    """The map directory must hold exactly the scenario's files: a hidden file is one of its files too."""
    m = write_map(tmp_path)
    (m / ".lanelet2_map.osm.swp").write_bytes(b"x")
    with pytest.raises(aw.ScenarioError, match=r"\.lanelet2_map\.osm\.swp"):
        aw.check_map(sc, m)


def test_a_scenario_file_that_cannot_be_read_is_a_refusal_before_anything(aw, tmp_path, monkeypatch, capsys):
    """An absent scenario file is a bad argument: exit 2 with the reason, before any import is tried and with nothing made,
    never Python's traceback."""
    out = tmp_path / "out"
    rc = _ros_free_main(aw, monkeypatch, _argv(tmp_path / "absent.json", write_map(tmp_path), out))
    assert rc == 2 and "absent.json" in capsys.readouterr().err and not out.exists()


def test_the_drivers_own_bounds_are_the_ones_the_readme_gives_reasons_for(aw):
    """sdv/aw/README.md gives the reasons for the driver's own bounds (30 s for the clear, 10 s for the claim node's
    discovery, 5 s for a state topic's first message before a request): a change in one place is seen in the other."""
    flat = " ".join((REPO / "sdv" / "aw" / "README.md").read_text(encoding="utf-8").split())
    assert "30 s for the clear, 10 s for the claim node's discovery, 5 s for a state topic's first message before a request" in flat
    assert (aw.CLEAR_TIMEOUT_S, aw.CLAIM_NODE_WAIT_S, aw.SETTLE_S) == (30.0, 10.0, 5.0)


def test_the_forms_bounds_are_inclusive(aw, tmp_path):
    """A yaw of -pi or pi and a timeout of exactly MAX_TIMEOUT_S are in the form, as scenario_problems states its ranges."""
    d = scenario_dict()
    d["initial_pose"]["yaw"], d["goal"]["yaw"] = -math.pi, math.pi
    d["timeouts_s"]["arrive"] = aw.MAX_TIMEOUT_S
    s = aw.load_scenario(write_scenario(tmp_path, d))
    assert (s.initial_pose.yaw, s.goal.yaw, s.timeouts["arrive"]) == (-math.pi, math.pi, aw.MAX_TIMEOUT_S)


# ============================================================ the fresh odometry (the WP8 fix, section 2 item 1)

def _start(sc):
    return sc.initial_pose.x, sc.initial_pose.y, sc.initial_pose.z


def test_the_route_waits_for_a_fresh_odometry_at_the_start(aw, sc):
    """INITIALIZED says nothing of the simulator's pose: the route is not asked before an odometry at the start has come."""
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(3.0, ODOMETRY, odometry(*_start(sc)))
    lines = []
    assert aw.run(fake, sc, False, lines.append) == 0
    route = next(c for c in fake.calls if c.service == aw.ROUTE_SERVICE)
    assert route.t >= 3 * S, route.t
    localize = lines[0]
    assert (localize["step"], localize["outcome"], localize["state"]) == ("localize", "done", aw.INITIALIZED)
    assert localize["mono_ns"] >= 3 * S


def test_no_fresh_odometry_is_localizes_timeout_and_names_it_inside_localizes_budget(aw, sc):
    rc, lines, fake = drive(aw, sc, follow=False)
    assert rc == aw.EXIT_TIMEOUT
    last = lines[-1]
    assert [x["step"] for x in lines] == ["localize"] and last["outcome"] == "timeout" and last["state"] == aw.INITIALIZED
    assert "odometry" in last["detail"] and "1 m" in last["detail"]
    assert aw.ROUTE_SERVICE not in fake.services()
    budget = sc.timeouts["localize"] * S
    assert budget <= last["mono_ns"] < budget + S


def test_an_odometry_after_localizes_budget_is_too_late(aw, sc):
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(sc.timeouts["localize"] + 2.0, ODOMETRY, odometry(*_start(sc)))
    lines = []
    assert aw.run(fake, sc, False, lines.append) == aw.EXIT_TIMEOUT and lines[-1]["step"] == "localize"


def test_an_odometry_from_before_the_request_never_counts(aw, sc):
    """At the start, and taken before the initial-pose request: nothing shows the simulator has applied this request."""
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(0.005, ODOMETRY, odometry(*_start(sc)))         # before the settle's spin ends, so before the request
    lines = []
    assert aw.run(fake, sc, False, lines.append) == aw.EXIT_TIMEOUT
    assert lines[-1]["step"] == "localize" and "odometry" in lines[-1]["detail"]
    assert fake.calls[0].states[ODOMETRY] and aw.ROUTE_SERVICE not in fake.services()


def test_an_odometry_numbered_exactly_at_the_requests_mark_never_counts(aw, sc):
    """The newest message before the request, and it is the odometry, so the mark is its number: "newer than the request" excludes the mark."""
    fake = FakeAutoware(aw, follow=False, latched={})
    fake.publish_at(0.005, ODOMETRY, odometry(*_start(sc)))
    marks = []
    real = fake.mark

    def mark():
        marks.append(real())
        return marks[-1]
    fake.mark = mark
    lines = []
    assert aw.run(fake, sc, False, lines.append) == aw.EXIT_TIMEOUT
    assert lines[-1]["step"] == "localize" and "odometry" in lines[-1]["detail"]
    assert fake.state[ODOMETRY][0] == marks[0], (fake.state[ODOMETRY][0], marks)


def test_the_sample_waiting_when_the_request_goes_is_taken_before_its_mark(aw, sc):
    """The reader keeps the newest sample until a spin of its node takes it: one that waits is taken before the request's mark, so an old
    pose left waiting there is numbered before the request and counts for nothing."""
    fake = FakeAutoware(aw)
    lines = []
    assert aw.run(fake, sc, False, lines.append) == 0
    first = fake.calls[0].t
    assert any(t <= first and d == 0.0 for t, d in fake.odometry_spins), fake.odometry_spins


@pytest.mark.parametrize("dx, dy, rc", [(0.0, 0.0, 0), (1.0, 0.0, 0), (0.0, -1.0, 0), (1.001, 0.0, 3), (0.0, 1.001, 3), (0.8, 0.8, 3),
                                        (65.8, 0.0, 3)],
                         ids=["at", "1m-x", "1m-y", "over-x", "over-y", "over-planar", "at-the-goal"])
def test_only_an_odometry_within_1_m_in_x_and_y_counts(aw, sc, dx, dy, rc):
    """1 m is a design value: the plane's distance from the start, inclusive."""
    x, y, z = _start(sc)
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(0.5, ODOMETRY, odometry(x + dx, y + dy, z))
    lines = []
    assert aw.run(fake, sc, False, lines.append) == rc
    assert (aw.ROUTE_SERVICE in fake.services()) is (rc == 0)


def test_the_wait_does_not_compare_z(aw, sc):
    """A CARLA spawn settles from above: z is no part of the wait."""
    x, y, z = _start(sc)
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(0.5, ODOMETRY, odometry(x, y, z + 30.0))
    lines = []
    assert aw.run(fake, sc, False, lines.append) == 0


def test_an_odometry_still_at_the_last_goal_holds_the_route_back_until_one_at_the_start(aw, sc):
    """The simulator late: the planner would take the old pose as arrived, so the route waits."""
    x, y, z = _start(sc)
    fake = FakeAutoware(aw, follow=False)
    fake.publish_at(0.2, ODOMETRY, odometry(sc.goal.x, sc.goal.y, z))
    fake.publish_at(0.4, ODOMETRY, odometry(sc.goal.x, sc.goal.y, z))
    fake.publish_at(2.0, ODOMETRY, odometry(x, y, z))
    lines = []
    assert aw.run(fake, sc, False, lines.append) == 0
    assert next(c for c in fake.calls if c.service == aw.ROUTE_SERVICE).t >= 2 * S


def test_a_route_line_never_holds_the_odometry_and_its_form_is_unchanged(aw, sc):
    rc, lines, _fake = drive(aw, sc)
    assert rc == 0 and all(list(x) == LINE_KEYS for x in lines) and [x["step"] for x in lines] == STEPS


def test_the_odometry_at_the_route_request_goes_to_its_own_note(aw, sc):
    fake = FakeAutoware(aw)
    lines, notes = [], []
    assert aw.run(fake, sc, False, lines.append, notes.append) == 0
    assert len(notes) == 1, notes
    n = notes[0]
    assert (n["at"], n["x"], n["y"], n["z"]) == ("route", sc.initial_pose.x, sc.initial_pose.y, sc.initial_pose.z)
    assert n["to_start_m"] == 0.0 and n["to_goal_m"] == 60.0
    route = next(c for c in fake.calls if c.service == aw.ROUTE_SERVICE)
    assert n["mono_ns"] <= route.t
    assert not any("to_goal_m" in x for x in lines)


def _odometry_lines(out):
    raw = (out / "odometry.jsonl").read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    return [json.loads(x) for x in raw.decode("utf-8").splitlines()]


def test_main_writes_the_odometry_at_the_route_to_its_own_file_never_to_scenario_jsonl(aw, tmp_path, monkeypatch):
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    got = _odometry_lines(out)
    assert len(got) == 1 and got[0]["at"] == "route" and (got[0]["x"], got[0]["y"]) == (10.0, 20.0), got
    lines = _lines(out)
    assert [x["step"] for x in lines] == ["map"] + STEPS
    assert not any("to_goal_m" in x or "to_start_m" in x for x in lines), lines
    assert all(list(x) == LINE_KEYS for x in lines[1:])


def test_the_note_holds_the_newest_odometry_at_the_routes_request_not_the_one_localize_took(aw, tmp_path, monkeypatch):
    """The pose moves between localize's wait and the route's request: odometry.jsonl says what the route was asked from."""
    rec = fake_ros(monkeypatch, aw)
    seen = {"n": 0}

    def idle(node):
        if node.name != "aw_scenario" and rec.pose is not None:
            seen["n"] += 1
            if seen["n"] == 2:              # the first was localize's wait, which took the start; this one is the route's
                rec.pose = (10.5, 20.25, 1.0)
    rec.idle = idle
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    assert seen["n"] == 2, seen
    got = _odometry_lines(out)
    assert (got[0]["x"], got[0]["y"]) == (10.5, 20.25), got


def _stale_states(rec, aw, n, available=True):
    """n messages of the operation mode, published before the route's request, that wait on the state topics' node while the odometry's wait spins
    only its own."""
    state = {"queued": False}
    fields = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: available}

    def idle(node):
        if node.name != "aw_scenario" and rec.pose is not None and not state["queued"]:
            state["queued"] = True
            rec.pending.extend((aw.OPERATION_MODE_TOPIC, dict(fields)) for _ in range(n))
    rec.idle = idle
    return state


@pytest.mark.parametrize("n", [1, 5, 30])
def test_a_state_that_waited_through_the_odometrys_wait_is_numbered_before_the_routes_mark(aw, tmp_path, monkeypatch, n):
    """An availability from before the route, unspun while only the odometry's node was: it never lets the engage through."""
    route_only = {aw.ROUTE_SERVICE: [(aw.ROUTING_STATE_TOPIC, {aw.STATE_FIELD: aw.SET})]}
    rec = fake_ros(monkeypatch, aw, effects=route_only)
    state = _stale_states(rec, aw, n)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path, _short(engage=0.2)), write_map(tmp_path), out)) == 3
    assert state["queued"] and not rec.pending
    last = _lines(out)[-1]
    assert (last["step"], last["outcome"]) == ("engage", "timeout"), last
    assert aw.ENGAGE_SERVICE not in [s for s, _r in rec.requests]


def test_an_availability_after_the_route_still_counts_with_a_stale_one_taken_before_it(aw, tmp_path, monkeypatch):
    """The other direction: a real reading is not lost to the drain."""
    rec = fake_ros(monkeypatch, aw)
    _stale_states(rec, aw, 3, available=False)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    assert [x["step"] for x in _lines(out)] == ["map"] + STEPS


def test_the_drain_before_the_routes_mark_has_a_bound_and_each_spin_waits(aw, sc):
    """A topic that never falls silent ends the drain at its bound, three readers' depth, and the route is still asked; a spin of it waits more
    than nothing (the state topics' node is never spun in a busy loop)."""
    class Chatty(FakeAutoware):
        chatty = False
        spins = ()

        def call(self, service, fields, timeout_s):
            self.chatty = service == READ["LOCALIZE_SERVICE"]
            return super().call(service, fields, timeout_s)

        def spin(self, timeout_s):
            if self.chatty:
                self.spins += (timeout_s,)
                assert len(self.spins) <= 3 * aw.DRAIN_SPINS, "the drain has no bound"
                self._deliver(READ["OPERATION_MODE_TOPIC"], {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: False})
            super().spin(timeout_s)
    fake = Chatty(aw)
    aw.run(fake, sc, False, [].append)
    assert aw.ROUTE_SERVICE in fake.services()
    assert aw.DRAIN_SPINS == 3 * aw.STATE_DEPTH and len(fake.spins) == aw.DRAIN_SPINS, fake.spins
    assert all(0 < t <= aw.POLL_S for t in fake.spins), fake.spins


def test_the_drain_ends_at_the_first_spin_that_takes_nothing(aw, sc):
    """Nothing waits: one spin, and so one DRAIN_SPIN_S, in a drive that does not otherwise stop for it."""
    class Counts(FakeAutoware):
        spins = ()

        def spin(self, timeout_s):
            self.spins += (timeout_s,)
            super().spin(timeout_s)
    fake = Counts(aw)
    assert aw.run(fake, sc, False, [].append) == 0
    assert fake.spins.count(aw.DRAIN_SPIN_S) == 1, fake.spins


def test_main_spins_the_odometrys_node_only_while_it_reads_the_odometry(aw, tmp_path, monkeypatch):
    """No wake-up per sample through a drive: the driver reads the odometry at localize and at the route's request, and its node is not
    spun between those reads."""
    mode = {aw.MODE_FIELD: aw.AUTONOMOUS, aw.AVAILABLE_FIELD: False}
    rec = fake_ros(monkeypatch, aw, effects={aw.ENGAGE_SERVICE: [(aw.OPERATION_MODE_TOPIC, mode)]})     # no ARRIVED: its wait spins
    at_route = {}

    class Mark(list):
        def append(self, item):
            at_route.setdefault(item[0], len(rec.spins))
            list.append(self, item)
    rec.requests = Mark()
    assert aw.main(_argv(write_scenario(tmp_path, _short(arrive=0.2)), write_map(tmp_path), tmp_path / "run")) == 3
    late = rec.spins[at_route[aw.ROUTE_SERVICE]:]
    assert late and not [n for n, _t in late if n != "aw_scenario"], late
    assert [n for n, _t in rec.spins if n != "aw_scenario"], rec.spins


def test_main_refuses_when_nav_msgs_cannot_be_imported_and_makes_nothing(aw, tmp_path, monkeypatch, capsys):
    fake_ros(monkeypatch, aw)
    monkeypatch.setitem(sys.modules, "nav_msgs", None)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 2
    assert "cannot be imported" in capsys.readouterr().err and not out.exists()


# ============================================================ the resident driver (the WP8 fix, section 2 items 2 and 3)

def _serve(aw, tmp_path, words, fake=None, require=False, sc=None, between=None, **kw):
    """aw.serve over a stand-in AD API: each word goes into the go file when the one before it has been answered, and the loop ends once the
    last is. `between(i)` runs before word i goes (a change of the stand-in's world between two drives)."""
    root = tmp_path / "drives"
    root.mkdir(exist_ok=True)
    go = tmp_path / "go"
    if sc is None:
        sc = aw.load_scenario(write_scenario(tmp_path))
    fake = fake if fake is not None else FakeAutoware(aw, **kw)
    state = {"i": 0}
    files = {"a.osm": "x"}

    def ended():
        i = state["i"]
        if i == len(words):
            return True
        if between is not None:
            between(i)
        go.write_text(words[i] + "\n", encoding="ascii")
        state["i"] = i + 1
        return False
    aw.serve(fake, sc, files, root, go, require, ended)
    return fake, root, go, sc


def _exit_of(aw, root, word):
    return (root / word / aw.EXIT_FILE).read_text(encoding="ascii")


def _jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


def test_serve_gives_each_word_one_drive_with_its_own_lines_directory_and_exit(aw, tmp_path):
    fake, root, go, _sc = _serve(aw, tmp_path, ["d001", "d002"])
    assert not go.exists()
    for w in ("d001", "d002"):
        assert _exit_of(aw, root, w) == "0\n"
        lines = _jsonl(root / w / "scenario.jsonl")
        assert [x["step"] for x in lines] == ["map"] + STEPS and all(x["outcome"] == "done" for x in lines)
        assert list(lines[1]) == LINE_KEYS
        assert lines[0]["files"] == {"a.osm": "x"} and lines[0]["require_claim_node"] is False and lines[0]["scenario"] == "test-drive"
        assert len(_jsonl(root / w / "odometry.jsonl")) == 1
        assert sorted(p.name for p in (root / w).iterdir()) == ["availability.jsonl", "exit", "odometry.jsonl", "scenario.jsonl"]
    assert fake.services() == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE] * 2


def test_the_map_line_of_a_served_drive_has_the_one_shots_keys(aw, tmp_path, monkeypatch):
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    p = write_scenario(tmp_path)
    assert aw.main(_argv(p, write_map(tmp_path), out)) == 0
    one_shot = _lines(out)[0]
    other = tmp_path / "other"
    other.mkdir()
    _fake, root, _go, _sc = _serve(aw, other, ["d001"], sc=aw.load_scenario(p))
    served = _jsonl(root / "d001" / "scenario.jsonl")[0]
    assert list(served) == list(one_shot) and served["detail"] == "1 files, each with the scenario's sha256"


def test_take_go_reads_a_word_once_and_only_when_it_is_whole(aw, tmp_path):
    go = tmp_path / "go"
    assert aw.take_go(go) is None
    go.write_text("d00", encoding="ascii")                         # a writer that has not ended its line
    assert aw.take_go(go) is None and go.exists()
    go.write_text("d001\n", encoding="ascii")
    assert aw.take_go(go) == "d001" and not go.exists()
    assert aw.take_go(go) is None


def _looks(n):
    seen = {"n": 0}

    def ended():
        seen["n"] += 1
        return seen["n"] > n
    return ended


def test_one_word_starts_one_drive_however_many_times_the_loop_looks(aw, tmp_path):
    root = tmp_path / "drives"
    root.mkdir()
    go = tmp_path / "go"
    go.write_text("d001\n", encoding="ascii")
    fake = FakeAutoware(aw)
    aw.serve(fake, aw.load_scenario(write_scenario(tmp_path)), {}, root, go, False, _looks(40))
    assert fake.services().count(aw.LOCALIZE_SERVICE) == 1 and sorted(p.name for p in root.iterdir()) == ["d001"]


@pytest.mark.parametrize("word", ["../up", "a/b", ".hidden", "", "d 1", "d001\n"], ids=["up", "slash", "hidden", "empty", "space", "newline"])
def test_a_word_that_is_no_plain_name_starts_nothing_and_makes_nothing(aw, tmp_path, capsys, word):
    root = tmp_path / "drives"
    root.mkdir()
    go = tmp_path / "go"
    go.write_text(word + "\n", encoding="ascii")
    fake = FakeAutoware(aw)
    aw.serve(fake, aw.load_scenario(write_scenario(tmp_path)), {}, root, go, False, _looks(3))
    assert aw.LOCALIZE_SERVICE not in fake.services() and not list(root.iterdir()) and not go.exists()
    assert "refused" in capsys.readouterr().err


def test_a_word_for_a_drive_already_answered_runs_nothing_and_keeps_its_exit(aw, tmp_path, capsys):
    root = tmp_path / "drives"
    (root / "d001").mkdir(parents=True)
    (root / "d001" / aw.EXIT_FILE).write_text("0\n", encoding="ascii")
    fake = FakeAutoware(aw)
    assert aw.serve_drive(fake, aw.load_scenario(write_scenario(tmp_path)), {}, root, "d001", False) == aw.EXIT_REFUSED
    assert not fake.calls and _exit_of(aw, root, "d001") == "0\n"
    assert "refused" in capsys.readouterr().err


def test_a_served_drive_refused_before_it_ran_still_answers_with_2(aw, tmp_path, capsys):
    """Its directory there and not empty, with no exit in it: the same refusal as the one-shot form's, and the harness gets its number."""
    root = tmp_path / "drives"
    (root / "d001").mkdir(parents=True)
    (root / "d001" / "stray").write_text("x", encoding="ascii")
    fake = FakeAutoware(aw)
    assert aw.serve_drive(fake, aw.load_scenario(write_scenario(tmp_path)), {}, root, "d001", False) == aw.EXIT_REFUSED
    assert not fake.calls and _exit_of(aw, root, "d001") == "2\n"


not_root_on_unix = pytest.mark.skipif(sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() == 0,
                                      reason="needs a directory this user cannot write")


@not_root_on_unix
def test_a_served_drive_with_no_directory_to_answer_in_ends_the_process_with_2(aw, tmp_path, capsys):
    """A root the container's user cannot write: a driver that goes on idling is a drive that never answers, the whole bound and a 124. Docker's
    code carries the refusal at once, as the one-shot form's exit did (PR's dated section, item 15)."""
    root = tmp_path / "drives"
    root.mkdir()
    go = tmp_path / "go"
    go.write_text("d001\n", encoding="ascii")
    fake = FakeAutoware(aw)
    os.chmod(root, 0o555)
    try:
        with pytest.raises(SystemExit) as ended:
            aw.serve(fake, aw.load_scenario(write_scenario(tmp_path)), {}, root, go, False, _looks(5))
    finally:
        os.chmod(root, 0o755)
    assert ended.value.code == aw.EXIT_REFUSED and not list(root.iterdir()) and not go.exists() and not fake.calls
    assert "refused: the drive d001" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["scenario.jsonl", "odometry.jsonl"])
def test_a_served_drive_whose_file_cannot_be_opened_answers_2_and_the_next_word_is_taken(aw, tmp_path, monkeypatch, capsys, name):
    """Its directory is made, then an open fails (a full or read-only mount): the refusal is the drive's own, its exit file says 2 and the process is
    not the one that ends, so the next drive runs."""
    real = open

    def opener(file, *args, **kwargs):
        if Path(file).parent.name == "d001" and Path(file).name == name:
            raise OSError(errno.EROFS, "read-only file system")
        return real(file, *args, **kwargs)
    monkeypatch.setattr(aw, "open", opener, raising=False)
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"])
    assert _exit_of(aw, root, "d001") == "2\n" and _exit_of(aw, root, "d002") == "0\n"
    assert fake.services() == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE], "only d002 ran"
    assert "refused: the drive d001" in capsys.readouterr().err


def test_a_served_drive_whose_refusal_cannot_be_written_ends_the_process_with_2(aw, tmp_path, monkeypatch, capsys):
    """Its directory there, and the answer does not go in (a full disk): the same, and no OSError's traceback and exit 1 in its place."""
    root = tmp_path / "drives"
    (root / "d001").mkdir(parents=True)
    (root / "d001" / "stray").write_text("x", encoding="ascii")

    def full(_out, _rc):
        raise OSError(errno.ENOSPC, "no space left")
    monkeypatch.setattr(aw, "write_exit", full)
    with pytest.raises(SystemExit) as ended:
        aw.serve_drive(FakeAutoware(aw), aw.load_scenario(write_scenario(tmp_path)), {}, root, "d001", False)
    assert ended.value.code == aw.EXIT_REFUSED
    assert "refused: the drive d001" in capsys.readouterr().err


def test_the_exit_file_appears_whole_or_not_at_all(aw, tmp_path, monkeypatch):
    out = tmp_path / "d001"
    out.mkdir()
    seen = []
    real = os.replace

    def replace(a, b):
        seen.append((Path(b).name, (out / aw.EXIT_FILE).exists(), Path(a).read_text(encoding="ascii")))
        return real(a, b)
    monkeypatch.setattr(aw.os, "replace", replace)
    aw.write_exit(out, 3)
    assert seen == [(aw.EXIT_FILE, False, "3\n")]
    assert sorted(p.name for p in out.iterdir()) == [aw.EXIT_FILE] and _exit_of(aw, tmp_path, "d001") == "3\n"


def test_the_exit_is_the_last_thing_a_failed_drive_writes(aw, tmp_path, monkeypatch):
    """Exit last: when the harness reads it the clear has been asked and answered, so the next word finds the driver ready."""
    real = aw.write_exit
    seen = {}

    def spy(out, rc):
        seen["after"] = (Path(out) / aw.AFTER_FAILURE_LOG).read_text(encoding="utf-8")
        return real(out, rc)
    monkeypatch.setattr(aw, "write_exit", spy)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], replies={aw.ROUTE_SERVICE: aw.Reply(False, 1, "no")})
    assert [x["step"] for x in map(json.loads, seen["after"].splitlines())] == ["stop", "clear"]
    assert _exit_of(aw, root, "d001") == "2\n"


def test_a_second_drive_in_one_process_reads_nothing_of_the_first(aw, tmp_path):
    """Every state of the first drive in the stand-in's memory and the second's withheld: the second waits over its own budgets and ends in
    its own timeout, from its own marks."""
    e = honest_effects(aw)
    fake = FakeAutoware(aw)

    def between(i):
        if i == 1:
            fake.effects[aw.ROUTE_SERVICE] = without(e[aw.ROUTE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.SET)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert _exit_of(aw, root, "d001") == "0\n" and _exit_of(aw, root, "d002") == "3\n"
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"]) == ("route", "timeout")
    assert aw.ENGAGE_SERVICE not in fake.services()[4:]


@pytest.mark.parametrize("cut", ["localize", "arrive"])
def test_a_second_drive_takes_no_state_of_the_first_at_any_step(aw, tmp_path, cut):
    e = honest_effects(aw)
    fake = FakeAutoware(aw)

    def between(i):
        if i != 1:
            return
        if cut == "localize":
            fake.effects[aw.LOCALIZE_SERVICE] = without(e[aw.LOCALIZE_SERVICE], aw.LOCALIZATION_STATE_TOPIC, aw.STATE_FIELD, aw.INITIALIZED)
        else:
            fake.effects[aw.ENGAGE_SERVICE] = without(e[aw.ENGAGE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.ARRIVED)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"]) == (cut, "timeout") and _exit_of(aw, root, "d002") == "3\n"


def test_a_second_drive_takes_no_odometry_of_the_first(aw, tmp_path):
    """The first drive's odometry at the start stands in the stand-in's memory: the second's wait wants one newer than its own request."""
    fake = FakeAutoware(aw)

    def between(i):
        fake.follow = i == 0
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"]) == ("localize", "timeout") and "odometry" in last["detail"]


def test_a_non_zero_exit_asks_for_stop_then_clear_writes_each_answer_apart_and_is_ready(aw, tmp_path):
    """An arrive that timed out: AUTONOMOUS still. STOP first, since a route in use cannot be cleared; the clear only once the mode says STOP."""
    e = honest_effects(aw)
    cut = without(e[aw.ENGAGE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.ARRIVED)
    fake = FakeAutoware(aw, effects={aw.ENGAGE_SERVICE: [x for x in cut if x[2].get(aw.MODE_FIELD) != 1]})

    def between(i):
        if i == 1:
            fake.effects[aw.ENGAGE_SERVICE] = e[aw.ENGAGE_SERVICE]
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert _exit_of(aw, root, "d001") == "3\n" and _exit_of(aw, root, "d002") == "0\n"
    first = fake.services()[:5]
    assert first == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, STOP_SERVICE, aw.CLEAR_SERVICE], fake.services()
    assert fake.calls[4].states[aw.OPERATION_MODE_TOPIC][aw.MODE_FIELD] == 1, "the clear was asked with the mode not yet STOP"
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert [(x["step"], x["outcome"], x["success"]) for x in after] == [("stop", "done", True), ("clear", "done", True)]
    assert all(list(x) == LINE_KEYS for x in after)
    lines = _jsonl(root / "d001" / "scenario.jsonl")
    assert (lines[-1]["step"], lines[-1]["outcome"]) == ("arrive", "timeout"), "the drive's last line is the drive's"
    assert not any(x["step"] in ("stop", "clear") for x in lines)


def test_a_mode_already_stopped_costs_the_clear_no_wait(aw, tmp_path):
    """A route that failed before any engage: STOP changes nothing, no new mode message comes, and the clear is asked at once."""
    fake, _root, _go, _sc = _serve(aw, tmp_path, ["d001"], replies={aw.ROUTE_SERVICE: aw.Reply(False, 1, "already")}, effects={STOP_SERVICE: []})
    stop, clear = fake.calls[2], fake.calls[3]
    assert (stop.service, clear.service) == (STOP_SERVICE, aw.CLEAR_SERVICE)
    assert clear.t - stop.t <= 2 * FakeAutoware.CALL_S * S


def test_a_stop_whose_mode_never_says_so_is_written_and_the_clear_still_asked(aw, tmp_path):
    e = honest_effects(aw)
    cut = without(e[aw.ENGAGE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.ARRIVED)
    fake = FakeAutoware(aw, effects={aw.ENGAGE_SERVICE: [x for x in cut if x[2].get(aw.MODE_FIELD) != 1], STOP_SERVICE: []})
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], fake=fake)
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert [(x["step"], x["outcome"]) for x in after] == [("stop", "timeout"), ("clear", "done")]
    assert _exit_of(aw, root, "d001") == "3\n"


def test_a_stop_is_read_back_even_when_no_mode_has_ever_been_read(aw, tmp_path):
    """The operation mode's topic is silent: with no mode on record the STOP is not known to have been taken, and the read-back waits for it."""
    latched = {aw.LOCALIZATION_STATE_TOPIC: {aw.STATE_FIELD: 1}, aw.ROUTING_STATE_TOPIC: {aw.STATE_FIELD: 1}}
    fake = FakeAutoware(aw, latched=latched, replies={aw.ROUTE_SERVICE: aw.Reply(False, 1, "no")}, effects={STOP_SERVICE: []})
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], fake=fake)
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert [(x["step"], x["outcome"]) for x in after] == [("stop", "timeout"), ("clear", "done")]


def test_exit_0_asks_for_no_stop_and_no_serve_loop_clear(aw, tmp_path):
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"])
    assert STOP_SERVICE not in fake.services() and fake.services().count(aw.CLEAR_SERVICE) == 1
    assert not (root / "d001" / aw.AFTER_FAILURE_LOG).exists()


@pytest.mark.parametrize("kind", ["refused", "no-reply", "down"])
def test_a_clear_that_fails_is_written_and_the_next_drive_begins(aw, tmp_path, kind):
    kw = {"replies": {aw.ROUTE_SERVICE: aw.Reply(False, 1, "no")}}
    if kind == "refused":
        kw["replies"][aw.CLEAR_SERVICE] = aw.Reply(False, 9, "in use")
    elif kind == "no-reply":
        kw["replies"][aw.CLEAR_SERVICE] = None
    else:
        kw["down"] = {aw.CLEAR_SERVICE}
    fake = FakeAutoware(aw, **kw)

    def between(i):
        if i == 1:
            fake.replies.clear()
            fake.down.clear()
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert after[-1]["step"] == "clear" and after[-1]["outcome"] == ("refused" if kind == "refused" else "timeout")
    assert _exit_of(aw, root, "d001") == "2\n" and _exit_of(aw, root, "d002") == "0\n"
    assert not any(x["step"] == "clear" for x in _jsonl(root / "d001" / "scenario.jsonl"))


def test_a_stop_that_fails_is_written_and_the_clear_is_still_asked(aw, tmp_path):
    replies = {aw.ROUTE_SERVICE: aw.Reply(False, 1, "no"), STOP_SERVICE: aw.Reply(False, 2, "no stop")}
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], replies=replies)
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert [(x["step"], x["outcome"]) for x in after] == [("stop", "refused"), ("clear", "done")] and fake.services()[-1] == aw.CLEAR_SERVICE


class ChainingAutoware(FakeAutoware):
    """The mission planner as the diagnosis read it: a route that is set refuses the next route until a clear."""
    route_set = False

    def call(self, service, fields, timeout_s):
        if service == READ["ROUTE_SERVICE"]:
            self.replies[service] = self.aw.Reply(False, 1, "The route is already set.") if self.route_set else self.aw.Reply(True, 0, "")
            self.route_set = True
        if service == READ["CLEAR_SERVICE"]:
            self.route_set = False
        return super().call(service, fields, timeout_s)


def test_one_failed_drive_no_longer_refuses_the_rest(aw, tmp_path):
    """The arrive of d001 times out with its route set; the clear after it leaves d002 a route that can be set, and T7 has failed all the same."""
    e = honest_effects(aw)
    cut = without(e[aw.ENGAGE_SERVICE], aw.ROUTING_STATE_TOPIC, aw.STATE_FIELD, aw.ARRIVED)
    fake = ChainingAutoware(aw, effects={aw.ENGAGE_SERVICE: cut})

    def between(i):
        if i == 1:
            fake.effects[aw.ENGAGE_SERVICE] = e[aw.ENGAGE_SERVICE]
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002", "d003"], fake=fake, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002", "d003")] == ["3\n", "0\n", "0\n"]


def test_an_exception_from_rclpy_during_a_served_drive_is_its_exit_1_and_the_loop_goes_on(aw, tmp_path, capsys):
    class Breaks(FakeAutoware):
        broken = True

        def call(self, service, fields, timeout_s):
            if self.broken and service == READ["ROUTE_SERVICE"]:
                self.broken = False
                raise RuntimeError("the stand-in's rclpy error")
            return super().call(service, fields, timeout_s)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=Breaks(aw))
    assert _exit_of(aw, root, "d001") == "1\n" and _exit_of(aw, root, "d002") == "0\n"
    assert "the stand-in's rclpy error" in capsys.readouterr().err
    assert [x["step"] for x in _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)] == ["stop", "clear"]


def test_an_exception_in_the_clear_after_a_failed_drive_is_written_and_the_exit_still_comes(aw, tmp_path):
    class Breaks(FakeAutoware):
        def call(self, service, fields, timeout_s):
            if service == STOP_SERVICE:
                raise RuntimeError("the stand-in's rclpy error")
            return super().call(service, fields, timeout_s)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], fake=Breaks(aw, replies={aw.ROUTE_SERVICE: aw.Reply(False, 1, "no")}))
    after = _jsonl(root / "d001" / aw.AFTER_FAILURE_LOG)
    assert [(x["step"], x["outcome"]) for x in after] == [("stop", "exception"), ("clear", "done")]
    assert "the stand-in's rclpy error" in after[0]["detail"] and _exit_of(aw, root, "d001") == "2\n"


def test_the_driver_is_joined_before_the_first_drive_even_with_its_word_already_there(aw, tmp_path):
    """The routing state reaches the driver only at 3 s: the first request waits for every state topic, so what the join costs falls before the
    first route. A state topic silent past the bound is accepted, as before any request."""
    latched = {aw.LOCALIZATION_STATE_TOPIC: {aw.STATE_FIELD: 1}, aw.OPERATION_MODE_TOPIC: {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: False}}
    fake = FakeAutoware(aw, latched=latched)
    fake.publish_at(3.0, aw.ROUTING_STATE_TOPIC, {aw.STATE_FIELD: 1})
    _serve(aw, tmp_path, ["d001"], fake=fake)
    assert aw.ROUTING_STATE_TOPIC in fake.calls[0].states and fake.calls[0].t >= 3 * S
    silent = FakeAutoware(aw, latched={aw.LOCALIZATION_STATE_TOPIC: {aw.STATE_FIELD: 1}})
    other = tmp_path / "other"
    other.mkdir()
    _serve(aw, other, ["d001"], fake=silent, sc=aw.load_scenario(write_scenario(tmp_path)))
    assert silent.calls[0].t <= (aw.SETTLE_S + 2 * aw.POLL_S) * S


def _serve_argv(scenario, map_dir, root, go, *extra):
    return ["--scenario", str(scenario), "--map-dir", str(map_dir), "--out", str(root), "--serve", str(go)] + list(extra)


def _script(rec, go, root, exit_name, words):
    """The harness's side, from inside the stand-in's spin: the next word once the last was answered; after the last, rclpy says it is over."""
    state = {"i": 0}

    def idle(_node):
        i = state["i"]
        if i and not (root / words[i - 1] / exit_name).exists():
            return
        if i == len(words):
            rec.ok = False
            return
        go.write_text(words[i] + "\n", encoding="ascii")
        state["i"] = i + 1
    rec.idle = idle


def test_main_serve_runs_many_drives_on_one_init_one_process_and_one_map_check(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw, subscribers={aw.CONTROL_TOPIC: ["ctl_claim_node"]})
    root, go = tmp_path / "drives", tmp_path / "go"
    root.mkdir()
    checks = []
    real = aw.check_map
    monkeypatch.setattr(aw, "check_map", lambda s, d: checks.append(d) or real(s, d))
    _script(rec, go, root, aw.EXIT_FILE, ["d001", "d002", "d003"])
    assert aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go, "--require-claim-node")) == 0
    assert rec.inits == 1 and len(rec.node_names) == 2 and len(checks) == 1
    assert rec.destroyed and rec.shutdowns >= 1
    for w in ("d001", "d002", "d003"):
        assert _exit_of(aw, root, w) == "0\n"
        lines = _lines(root / w)
        assert [x["step"] for x in lines] == ["map"] + STEPS and lines[0]["require_claim_node"] is True
        assert len(_odometry_lines(root / w)) == 1
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE] * 3


def test_main_serve_has_joined_before_it_reads_its_first_word(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw)
    root, go = tmp_path / "drives", tmp_path / "go"
    root.mkdir()
    real = aw.take_go
    seen = []

    def take_go(path):
        seen.append((rec.inits, len(rec.node_names), len(rec.spins)))
        rec.ok = False
        return real(path)
    monkeypatch.setattr(aw, "take_go", take_go)
    assert aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go)) == 0
    assert seen and seen[0][0] == 1 and seen[0][1] == 2 and seen[0][2] > 0, seen


def test_main_serve_ends_on_an_external_shutdown_as_the_claim_node_does(aw, tmp_path, monkeypatch):
    """SIGTERM of `docker stop`: rclpy's handlers end the spin."""
    rec = fake_ros(monkeypatch, aw)
    root, go = tmp_path / "drives", tmp_path / "go"
    root.mkdir()
    n = {"spins": 0}

    def idle(_node):
        n["spins"] += 1
        if n["spins"] > 5:
            raise rec.ExternalShutdownException()
    rec.idle = idle
    assert aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go)) == 0
    assert rec.destroyed and rec.shutdowns >= 1


def test_main_serve_ends_with_2_and_its_nodes_destroyed_when_a_drive_has_nowhere_to_answer(aw, tmp_path, monkeypatch, capsys):
    rec = fake_ros(monkeypatch, aw)
    root, go = tmp_path / "drives", tmp_path / "go"
    root.mkdir()
    go.write_text("d001\n", encoding="ascii")
    n = {"spins": 0}

    def idle(_node):                        # a bound, so that a driver that goes on idling fails this and does not hang it
        n["spins"] += 1
        rec.ok = n["spins"] < 50
    rec.idle = idle

    def no_disk(_d):
        raise OSError(errno.EIO, "the mount went away")
    monkeypatch.setattr(aw, "check_out", no_disk)
    with pytest.raises(SystemExit) as ended:
        aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go))
    assert ended.value.code == aw.EXIT_REFUSED and rec.destroyed and rec.shutdowns >= 1 and not rec.requests
    assert "the mount went away" in capsys.readouterr().err


@not_root_on_unix
@pytest.mark.parametrize("which", ["root", "go directory"])
def test_serve_refuses_a_directory_it_cannot_write_before_any_import_of_ros(aw, tmp_path, monkeypatch, capsys, which):
    """A mount's permissions are named in the driver's log before the join, not found out by the first word."""
    root, sdir = tmp_path / "drives", tmp_path / "serve"
    root.mkdir()
    sdir.mkdir()
    shut = root if which == "root" else sdir
    os.chmod(shut, 0o555)
    try:
        rc = _ros_free_main(aw, monkeypatch, _serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, sdir / "go"))
    finally:
        os.chmod(shut, 0o755)
    assert rc == 2
    err = capsys.readouterr().err
    assert "refused" in err and str(shut) in err and "write" in err


@pytest.mark.parametrize("fault", ["no go directory", "no root", "root is a file", "root in a work tree"])
def test_serve_refuses_before_any_import_of_ros(aw, tmp_path, monkeypatch, capsys, fault):
    root, go = tmp_path / "drives", tmp_path / "go"
    if fault == "no go directory":
        root.mkdir()
        go = tmp_path / "nowhere" / "go"
    elif fault == "root is a file":
        root.write_text("x", encoding="ascii")
    elif fault == "root in a work tree":
        root = _work_tree(tmp_path) / "drives"
        root.mkdir()
    assert _ros_free_main(aw, monkeypatch, _serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go)) == 2
    assert "refused" in capsys.readouterr().err


def test_a_served_root_may_hold_earlier_drives(aw, tmp_path, monkeypatch):
    """The root is no empty directory: it holds the drives, and a restarted driver starts on a root with earlier ones in it."""
    rec = fake_ros(monkeypatch, aw)
    root, go = tmp_path / "drives", tmp_path / "go"
    (root / "d001").mkdir(parents=True)
    _script(rec, go, root, aw.EXIT_FILE, ["d002"])
    assert aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go)) == 0
    assert _exit_of(aw, root, "d002") == "0\n"


def test_the_serve_mode_is_off_by_default_and_the_one_shot_argv_stands(aw, tmp_path, monkeypatch):
    a = aw.argument_parser().parse_args(_argv("s", "m", "o"))
    assert a.serve is None
    fake_ros(monkeypatch, aw)
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 0
    assert (out / "scenario.jsonl").exists() and not (out / aw.EXIT_FILE).exists()


def test_the_one_shot_form_answers_by_its_exit_and_asks_for_no_stop(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw, replies={aw.ROUTE_SERVICE: aw.Reply(False, 1, "no")})
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path), write_map(tmp_path), out)) == 2
    assert sorted(p.name for p in out.iterdir()) == ["odometry.jsonl", "scenario.jsonl"]
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE]


def test_serve_mode_stays_in_the_one_file_the_boards_lists_name():
    """The board helper and the day package list sdv/ctl/aw_scenario.py as the one driver file,
    so serve mode adds no file under sdv/ctl."""
    text = DRIVER.read_text(encoding="utf-8")
    assert "--serve" in text and "def serve(" in text


# ============================================================ the availability wait before the route (the WP8 second fix)

NOTE_KEYS = ["at", "available", "waited", "start_mono_ns", "end_mono_ns"]


class TickingAutoware(FakeAutoware):
    """The AD API with its availability as Autoware's own graph gives it: the operation mode's state is published only when its mode or its
    availability changes, and the availability follows the routing status as a timer samples it, once every TICK_S on a fixed grid from
    `phase_s`, published AGG_S after the sample: a route SET or ARRIVED at a sample makes autonomous available, UNSET makes it not. So a clear
    and the next route that both fall between two samples leave the availability True, with no message between them. The engage is refused
    while autonomous is not available. The vehicle arrives `arrive_after_s` after the first sample at least DRIVE_S after the engage, so the
    clear falls at the same place against the samples on every drive. TICK_S and AGG_S stand for the image's configuration (the routing
    status's diagnostic period, the aggregator's rate), DRIVE_S and MODE_S for a made-up drive and mode change: none of them is a reading."""
    TICK_S = 1.0
    AGG_S = 0.1
    MODE_S = 0.15
    DRIVE_S = 20.0

    def __init__(self, aw, phase_s=0.0, arrive_after_s=0.0, available=False, route=1, **kw):
        st, md, av = aw.STATE_FIELD, aw.MODE_FIELD, aw.AVAILABLE_FIELD
        self.mode, self.available, self.route_state = 1, available, route
        self.published = (1, available)
        self.tick_ns = int(round(self.TICK_S * S))
        self.next_tick = int(round(phase_s * S))
        self.phase_ns = self.next_tick
        self.arrive_after_ns = int(round(arrive_after_s * S))
        self.refused = 0
        self.samples = []
        kw.setdefault("latched", {aw.LOCALIZATION_STATE_TOPIC: {st: 1}, aw.ROUTING_STATE_TOPIC: {st: route},
                                  aw.OPERATION_MODE_TOPIC: {md: 1, av: available}})
        effects = {aw.ROUTE_SERVICE: [(0.2, aw.ROUTING_STATE_TOPIC, {st: aw.SET})], aw.ENGAGE_SERVICE: [],
                   aw.CLEAR_SERVICE: [(0.1, aw.ROUTING_STATE_TOPIC, {st: 1})], STOP_SERVICE: []}
        effects.update(kw.pop("effects", {}))
        super().__init__(aw, effects=effects, **kw)

    def call(self, service, fields, timeout_s):
        aw, t = self.aw, self.t
        if service == aw.ENGAGE_SERVICE and service not in self.replies and not self.available:
            self.refused += 1                       # Autoware's own answer: the target mode is not available
            self.replies[service] = aw.Reply(False, 1, "the target mode is not available")
            try:
                return super().call(service, fields, timeout_s)
            finally:
                del self.replies[service]
        reply = self.replies.get(service, aw.Reply(True, 0, ""))
        if reply is not None and reply.success:
            if service == aw.ENGAGE_SERVICE:
                self._at(t + int(round(self.MODE_S * S)), "_mode", {"mode": aw.AUTONOMOUS})
                earliest = t + int(round(self.DRIVE_S * S)) - self.phase_ns - self.arrive_after_ns
                self._at(self.phase_ns + -(-earliest // self.tick_ns) * self.tick_ns + self.arrive_after_ns, aw.ROUTING_STATE_TOPIC,
                         {aw.STATE_FIELD: aw.ARRIVED})
            elif service in (aw.CLEAR_SERVICE, STOP_SERVICE):
                self._at(t + int(round(0.1 * S)), "_mode", {"mode": 1})
        return super().call(service, fields, timeout_s)

    def _deliver(self, topic, fields):
        if topic == "_mode":
            self.mode = fields["mode"]
        elif topic == "_available":
            self.available = fields["present"]
        else:
            if topic == self.aw.ROUTING_STATE_TOPIC:
                self.route_state = fields[self.aw.STATE_FIELD]
            super()._deliver(topic, fields)
            return
        if (self.mode, self.available) != self.published:      # published only when it changes
            self.published = (self.mode, self.available)
            super()._deliver(self.aw.OPERATION_MODE_TOPIC, {self.aw.MODE_FIELD: self.mode, self.aw.AVAILABLE_FIELD: self.available})

    def _advance(self, dt_s):
        self.advances += 1
        assert self.advances <= self.MAX_ADVANCES, "the stand-in was advanced %d times: a wait of the driver's that has no end" % self.advances
        end = self.t + int(round(dt_s * S))
        while True:
            self.queue.sort()
            due = self.queue[0][0] if self.queue else None
            if self.next_tick <= end and (due is None or self.next_tick < due):
                self.t = max(self.t, self.next_tick)
                present = self.route_state in (self.aw.SET, self.aw.ARRIVED)
                self.samples.append((self.t, present))
                self._at(self.t + int(round(self.AGG_S * S)), "_available", {"present": present})
                self.next_tick += self.tick_ns
            elif due is not None and due <= end:
                due, _n, topic, fields = self.queue.pop(0)
                self.t = max(self.t, due)
                self._deliver(topic, fields)
            else:
                break
        self.t = end


def _ticking(aw, tmp_path, between=None, words=("d001", "d002"), **kw):
    fake = TickingAutoware(aw, **kw)
    _fake, root, _go, sc = _serve(aw, tmp_path, list(words), fake=fake, between=between)
    return fake, root, sc


def _service_calls(fake, service):
    return [c for c in fake.calls if c.service == service]


def _samples_in(fake, after, before):
    return [t for t, _p in fake.samples if after < t < before]


def _no_wait(aw, monkeypatch):
    """The wait taken out (on a tree without it, nothing to take out): what a driver without it does."""
    monkeypatch.setattr(aw._Step, "wait_until_unavailable", lambda self, *a, **k: None, raising=False)


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75], ids=["phase-0", "phase-0.25", "phase-0.5", "phase-0.75"])
def test_a_clear_and_the_next_route_inside_one_sample_engage_with_the_wait(aw, tmp_path, phase):
    """The resident driver's short gap: d001's clear lands just after a sample and d002 would ask its route before the next, so Autoware never
    sees the route go away and publishes no state after d002's request. The wait holds the route back until a state says autonomous is not
    available; the route's mark falls while it is False, and the engage takes the True this route's SET caused, which Autoware accepts."""
    fake, root, _sc = _ticking(aw, tmp_path, phase_s=phase)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "0\n"], _jsonl(root / "d002" / "scenario.jsonl")[-1]
    clear = _service_calls(fake, aw.CLEAR_SERVICE)[0]
    second = _service_calls(fake, aw.ROUTE_SERVICE)[1]
    localized = _jsonl(root / "d002" / "scenario.jsonl")[1]["mono_ns"]
    assert not _samples_in(fake, clear.t, localized), "the gap holds a sample: not the case under test"
    assert _samples_in(fake, clear.t, second.t), "the route was asked inside the same sample as the clear"
    assert second.states[aw.OPERATION_MODE_TOPIC][aw.AVAILABLE_FIELD] is False, "the wait was not over before the route's request"
    assert fake.refused == 0 and len(_service_calls(fake, aw.ENGAGE_SERVICE)) == 2
    assert not [t for t, d in fake.odometry_spins if localized < t < second.t and d > 0], "the wait spun the odometry's node"
    assert [(x["step"], x["outcome"]) for x in _jsonl(root / "d002" / "scenario.jsonl")[1:]] == [(s, "done") for s in STEPS]


@pytest.mark.parametrize("phase", [0.0, 0.25, 0.5, 0.75], ids=["phase-0", "phase-0.25", "phase-0.5", "phase-0.75"])
def test_without_the_wait_the_same_gap_times_out_at_the_engage(aw, tmp_path, monkeypatch, phase):
    """What the wait is for, in the stand-in: the same gap with the wait taken out, and d002's engage waits out its whole budget with no
    operation-mode state taken after the route's request (its line's state null), though Autoware would have taken the engage."""
    _no_wait(aw, monkeypatch)
    fake, root, sc = _ticking(aw, tmp_path, phase_s=phase)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "3\n"]
    lines = _jsonl(root / "d002" / "scenario.jsonl")
    last = lines[-1]
    assert (last["step"], last["outcome"], last["state"]) == ("engage", "timeout", None), last
    assert sc.timeouts["engage"] * S <= last["mono_ns"] - lines[-2]["mono_ns"] < (sc.timeouts["engage"] + 1) * S
    assert fake.available is True and len(_service_calls(fake, aw.ENGAGE_SERVICE)) == 1


@pytest.mark.parametrize("wait", ["with the wait", "without it"])
def test_a_gap_that_holds_a_sample_engages_either_way(aw, tmp_path, monkeypatch, wait):
    """The harness's own look between drives made longer than a sample: Autoware sees UNSET, says autonomous is not available before the
    route, and both drives engage, with the wait or without it. With it, the newest state already says False, so it costs nothing."""
    if wait == "without it":
        _no_wait(aw, monkeypatch)
    holder = {}

    def between(i):
        if i == 1:
            holder["fake"].spin(1.2)
    fake = TickingAutoware(aw)
    holder["fake"] = fake
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "0\n"]
    assert fake.refused == 0
    if wait == "with the wait":
        note = _jsonl(root / "d002" / aw.AVAILABILITY_LOG)
        assert [(x["available"], x["waited"]) for x in note] == [(False, False)], note
        assert note[0]["end_mono_ns"] == note[0]["start_mono_ns"]


@pytest.mark.parametrize("held", [True, None], ids=["available", "silent"])
def test_a_driver_that_has_never_asked_for_a_route_goes_on_at_once(aw, tmp_path, held):
    """The first drive: no route of the driver's own can have left a stale True, so neither a True nor a topic still silent holds its route
    back (the settle alone bounds a silent one, as before any request), and its note says it did not wait."""
    latched = initial_states(aw)
    if held is None:
        del latched[aw.OPERATION_MODE_TOPIC]
    else:
        latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True}
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"], latched=latched)
    assert _exit_of(aw, root, "d001") == "0\n"
    note = _jsonl(root / "d001" / aw.AVAILABILITY_LOG)
    assert [(x["available"], x["waited"]) for x in note] == [(held, False)], note
    route = _service_calls(fake, aw.ROUTE_SERVICE)[0]
    localized = _jsonl(root / "d001" / "scenario.jsonl")[1]["mono_ns"]
    settle = aw.SETTLE_S if held is None else 0.0
    assert route.t - localized <= (settle + 2 * aw.POLL_S) * S, (route.t, localized)


def _stays_available(aw):
    """Autonomous still available after d001: no state of the stand-in's ever says otherwise before d002's route."""
    mode, route = aw.OPERATION_MODE_TOPIC, aw.ROUTING_STATE_TOPIC
    return {aw.ENGAGE_SERVICE: [(0.3, mode, {aw.MODE_FIELD: aw.AUTONOMOUS, aw.AVAILABLE_FIELD: True}), (20.0, route, {aw.STATE_FIELD: aw.ARRIVED})]}


def test_an_availability_that_never_turns_false_fails_the_route_step_naming_the_wait(aw, tmp_path):
    """Inside the route's own budget: its line is the route's timeout in the line's own form, its detail names the availability wait, no route
    is asked and no engage, exit 3; the clear after a failed drive follows, as for any non-zero exit."""
    fake, root, _go, sc = _serve(aw, tmp_path, ["d001", "d002"], effects=_stays_available(aw))
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "3\n"]
    lines = _jsonl(root / "d002" / "scenario.jsonl")
    assert [(x["step"], x["outcome"]) for x in lines[1:]] == [("localize", "done"), ("route", "timeout")]
    last = lines[-1]
    assert list(last) == LINE_KEYS and (last["success"], last["code"], last["message"], last["state"]) == (None, None, None, None)
    assert "availability wait" in last["detail"] and aw.OPERATION_MODE_TOPIC in last["detail"] and aw.AVAILABLE_FIELD in last["detail"], last
    assert sc.timeouts["route"] * S <= last["mono_ns"] - lines[1]["mono_ns"] < (sc.timeouts["route"] + 1) * S
    assert fake.services()[4:] == [aw.LOCALIZE_SERVICE, STOP_SERVICE, aw.CLEAR_SERVICE], fake.services()
    note = _jsonl(root / "d002" / aw.AVAILABILITY_LOG)
    assert [(x["available"], x["waited"]) for x in note] == [(True, True)], note
    assert note[0]["end_mono_ns"] - note[0]["start_mono_ns"] >= sc.timeouts["route"] * S


def test_a_driver_that_has_asked_for_a_route_waits_out_a_silent_topic_too(aw, sc):
    """No state at all is no state saying False: a driver that has asked for a route before waits for one, and without it the route step ends
    in its timeout naming the wait."""
    latched = initial_states(aw)
    del latched[aw.OPERATION_MODE_TOPIC]
    fake = FakeAutoware(aw, latched=latched)
    lines, notes = [], []
    rc = aw.run(fake, sc, False, lines.append, availability=notes.append, memory=aw.Memory(route_asked=True))
    assert rc == 3 and (lines[-1]["step"], lines[-1]["outcome"]) == ("route", "timeout") and "availability wait" in lines[-1]["detail"]
    assert aw.ROUTE_SERVICE not in fake.services() and [(x["available"], x["waited"]) for x in notes] == [(None, True)]


def test_without_the_claim_node_the_drive_is_its_refusal_before_any_availability_wait(aw, tmp_path):
    """The order in run(): the claim node's wait comes before the availability wait, so a driver that has asked for a route and still holds
    autonomous available is refused for the claim node (exit 2, no route asked, no note), never timed out in the availability wait."""
    fake = FakeAutoware(aw, subscribers=[aw.CLAIM_NODE_NAME], effects=_stays_available(aw))

    def between(i):
        if i == 1:
            fake.subs = []
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, require=True, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "2\n"]
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"]) == ("route", "refused") and aw.CLAIM_NODE_NAME in last["detail"], last
    assert not (root / "d002" / aw.AVAILABILITY_LOG).exists()
    assert len(_service_calls(fake, aw.ROUTE_SERVICE)) == 1


def test_the_claim_nodes_refusal_comes_before_the_availability_wait(aw, tmp_path):
    """--require-claim-node, the claim node gone before d002 and autonomous still available after d001: d002 is the claim node's refusal
    (exit 2, no route set), not the availability wait's timeout, since the wait follows the claim node's wait and runs on the budget that
    starts once the claim node is there; and it writes no note, the drive having ended before the wait."""
    fake = FakeAutoware(aw, effects=_stays_available(aw), subscribers=[aw.CLAIM_NODE_NAME])

    def between(i):
        if i == 1:
            fake.subs = []
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, require=True, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "2\n"]
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"]) == ("route", "refused") and aw.CLAIM_NODE_NAME in last["detail"], last
    assert not (root / "d002" / aw.AVAILABILITY_LOG).exists()
    assert len(_service_calls(fake, aw.ROUTE_SERVICE)) == 1


def test_a_real_refusal_of_the_engage_stays_the_engages_reading(aw, tmp_path):
    """The other direction: after the wait and the route, Autoware refusing the engage is the engage's refusal, exit 2 with its reply on the
    engage's line, never a timeout of the route step."""
    fake = TickingAutoware(aw)

    def between(i):
        if i == 1:
            fake.replies[aw.ENGAGE_SERVICE] = aw.Reply(False, 5, "refused by the stand-in")
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "2\n"]
    last = _jsonl(root / "d002" / "scenario.jsonl")[-1]
    assert (last["step"], last["outcome"], last["success"], last["code"]) == ("engage", "refused", False, 5), last
    assert len(_service_calls(fake, aw.ROUTE_SERVICE)) == 2
    assert [(x["available"], x["waited"]) for x in _jsonl(root / "d002" / aw.AVAILABILITY_LOG)] == [(True, True)], "the wait was not exercised"


def test_a_route_asked_but_never_answered_counts_as_asked_so_the_next_drive_waits(aw, tmp_path):
    """Autoware took d001's route request and set the route, and the reply was lost: d001 is the route step's timeout (no reply), the clear
    after the failure clears the route, and d002, whose driver counts the request as asked whatever the reply, waits for the sample that says
    autonomous is not available and engages. A driver that counted only answered requests would ask d002's route on the stale True and time
    out at the engage."""
    fake = TickingAutoware(aw)
    lost = {"route": True}

    def call(service, fields, timeout_s, real=fake.call):
        if service == aw.ROUTE_SERVICE and lost.pop("route", False):
            fake.calls.append(types.SimpleNamespace(service=service, fields=fields, t=fake.t, states={}))
            fake._at(fake.t + int(round(0.2 * S)), aw.ROUTING_STATE_TOPIC, {aw.STATE_FIELD: aw.SET})
            fake._advance(timeout_s)
            return None
        return real(service, fields, timeout_s)
    fake.call = call
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["3\n", "0\n"], _jsonl(root / "d002" / "scenario.jsonl")[-1]
    last1 = _jsonl(root / "d001" / "scenario.jsonl")[-1]
    assert (last1["step"], last1["outcome"]) == ("route", "timeout") and "no reply" in last1["detail"], last1
    clear = _service_calls(fake, aw.CLEAR_SERVICE)[0]
    localized = _jsonl(root / "d002" / "scenario.jsonl")[1]["mono_ns"]
    assert not [t for t, present in fake.samples if clear.t < t < localized and not present], "a sample saw the clear: not the case under test"
    second = _service_calls(fake, aw.ROUTE_SERVICE)[1]
    assert second.states[aw.OPERATION_MODE_TOPIC][aw.AVAILABLE_FIELD] is False, "the wait was not over before the route's request"
    assert [(x["available"], x["waited"]) for x in _jsonl(root / "d002" / aw.AVAILABILITY_LOG)] == [(True, True)]
    assert fake.refused == 0 and len(_service_calls(fake, aw.ENGAGE_SERVICE)) == 1


@pytest.mark.parametrize("asked, held, waited", [(False, False, False), (False, True, False), (True, False, False), (True, True, True)])
def test_the_note_holds_the_availability_before_the_wait_whether_it_waited_and_its_stamps(aw, sc, asked, held, waited):
    """One line, in the form odometry.jsonl uses: the availability the driver held before the wait, whether it waited, and its monotonic
    stamps at the wait's start and end; the route asked only after that end."""
    latched = initial_states(aw)
    latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: held}
    fake = FakeAutoware(aw, latched=latched)
    fake.publish_at(3.0, aw.OPERATION_MODE_TOPIC, {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: False})
    lines, odometries, notes = [], [], []
    assert aw.run(fake, sc, False, lines.append, odometries.append, availability=notes.append, memory=aw.Memory(route_asked=asked)) == 0
    assert len(notes) == 1 and list(notes[0]) == NOTE_KEYS, notes
    n = notes[0]
    assert (n["at"], n["available"], n["waited"]) == ("route", held, waited)
    assert all(type(n[k]) is int for k in ("start_mono_ns", "end_mono_ns"))
    route = _service_calls(fake, aw.ROUTE_SERVICE)[0]
    assert lines[0]["mono_ns"] <= n["start_mono_ns"] <= n["end_mono_ns"] <= route.t
    if waited:
        assert n["end_mono_ns"] >= 3 * S and route.states[aw.OPERATION_MODE_TOPIC][aw.AVAILABLE_FIELD] is False
    else:
        assert n["end_mono_ns"] == n["start_mono_ns"] and route.t < 3 * S
    assert not any(set(NOTE_KEYS[1:]) & set(x) for x in lines + odometries)


def test_a_route_asked_is_remembered_for_the_next_drive_and_only_that(aw, sc):
    """The one thing a drive leaves the next: that it asked for a route. A drive that ended before its route leaves nothing of the kind."""
    m = aw.Memory()
    assert m.route_asked is False
    fake = FakeAutoware(aw, follow=False)
    assert aw.run(fake, sc, False, [].append, memory=m) == 3 and m.route_asked is False
    fake = FakeAutoware(aw)
    assert aw.run(fake, sc, False, [].append, memory=m) == 0 and m.route_asked is True


def test_a_driver_started_again_on_a_root_with_earlier_drives_takes_the_wait(aw, tmp_path):
    """PR's dated section, item 16 (b): the arm's driver started again after one that ended between drives. The earlier process's last clear
    left autonomous available with no sample since; its drives' directories are in the root, so the new process's first drive is not a first
    drive of the arm: it waits for the sample, and engages."""
    (tmp_path / "drives" / "d001").mkdir(parents=True)
    fake = TickingAutoware(aw, phase_s=0.9, available=True)
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d002"], fake=fake)
    assert _exit_of(aw, root, "d002") == "0\n", _jsonl(root / "d002" / "scenario.jsonl")[-1]
    note = _jsonl(root / "d002" / aw.AVAILABILITY_LOG)
    assert [(x["available"], x["waited"]) for x in note] == [(True, True)], note
    assert _service_calls(fake, aw.ROUTE_SERVICE)[0].t > fake.samples[0][0], "the route was asked before the first sample after the clear"


def test_a_root_that_cannot_be_read_counts_as_holding_earlier_drives(aw, tmp_path):
    assert aw._earlier_drives(tmp_path / "absent") is True
    (tmp_path / "empty").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "driver-d001.log").write_text("x", encoding="ascii")
    assert aw._earlier_drives(tmp_path / "empty") is False and aw._earlier_drives(tmp_path / "logs") is False
    (tmp_path / "logs" / "d001").mkdir()
    assert aw._earlier_drives(tmp_path / "logs") is True


def test_main_serve_writes_the_note_to_its_own_file_never_to_scenario_jsonl(aw, tmp_path, monkeypatch):
    rec = fake_ros(monkeypatch, aw)
    root, go = tmp_path / "drives", tmp_path / "go"
    root.mkdir()
    _script(rec, go, root, aw.EXIT_FILE, ["d001", "d002"])
    assert aw.main(_serve_argv(write_scenario(tmp_path), write_map(tmp_path), root, go)) == 0
    for w in ("d001", "d002"):
        raw = (root / w / aw.AVAILABILITY_LOG).read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 1
        note = json.loads(raw)
        assert list(note) == NOTE_KEYS and note["at"] == "route" and note["waited"] is False, note
        lines = _lines(root / w)
        assert [x["step"] for x in lines] == ["map"] + STEPS and all(list(x) == LINE_KEYS for x in lines[1:])
        assert not any("waited" in x or "start_mono_ns" in x for x in lines)
        assert len(_odometry_lines(root / w)) == 1
    assert not list(root.glob("*/*.tmp"))


class _Stamped(list):
    """fake_ros's `requests` with the monotonic time each request was made, for a test that reads when the route was asked."""

    def __init__(self):
        super().__init__()
        self.stamps = []

    def append(self, item):
        self.stamps.append(time.monotonic_ns())
        super().append(item)


def test_the_one_shot_form_never_waits_for_the_availability(aw, tmp_path, monkeypatch):
    """A one-shot run has no earlier drive of its own, so main gives run() no memory that has asked: with the operation-mode state latched
    available and never turning False before the route, the route is asked at once (within a poll of the localize line) and no
    availability.jsonl is written. A one-shot form that waited would end in the route step's timeout on that True."""
    latched = initial_states(aw)
    latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True}
    rec = fake_ros(monkeypatch, aw, latched=latched)
    rec.requests = _Stamped()
    d = scenario_dict()
    d["timeouts_s"] = {"localize": 5, "route": 2, "engage": 5, "arrive": 5}
    out = tmp_path / "run"
    assert aw.main(_argv(write_scenario(tmp_path, d), write_map(tmp_path), out)) == 0, _lines(out)[-1]
    assert [s for s, _r in rec.requests] == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE]
    localized = _lines(out)[1]
    assert localized["step"] == "localize" and rec.requests.stamps[1] - localized["mono_ns"] <= aw.POLL_S * S, (rec.requests.stamps, localized)
    assert sorted(p.name for p in out.iterdir()) == ["odometry.jsonl", "scenario.jsonl"]


def test_the_note_is_written_by_a_rename_whole_or_not_at_all(aw, tmp_path, monkeypatch):
    seen = []
    real = os.replace

    def replace(a, b):
        seen.append((Path(b).name, Path(b).exists(), Path(a).read_text(encoding="ascii")))
        return real(a, b)
    monkeypatch.setattr(aw.os, "replace", replace)
    _fake, root, _go, _sc = _serve(aw, tmp_path, ["d001"])
    notes = [x for x in seen if x[0] == aw.AVAILABILITY_LOG]
    assert len(notes) == 1 and notes[0][1] is False and notes[0][2].endswith("\n") and notes[0][2].count("\n") == 1, seen
    assert json.loads(notes[0][2]) == _jsonl(root / "d001" / aw.AVAILABILITY_LOG)[0]
    assert [x[0] for x in seen] == [aw.AVAILABILITY_LOG, aw.EXIT_FILE], "the exit is still the last thing the drive writes"


def test_a_served_drive_that_never_reached_its_route_writes_no_note(aw, tmp_path):
    fake = FakeAutoware(aw, follow=False)

    def between(i):
        fake.follow = i == 1
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["3\n", "0\n"]
    assert not (root / "d001" / aw.AVAILABILITY_LOG).exists() and (root / "d002" / aw.AVAILABILITY_LOG).exists()


@pytest.mark.parametrize("held", [True, None], ids=["available", "silent"])
def test_a_drive_that_never_reached_its_route_leaves_the_next_drive_no_wait(aw, tmp_path, held):
    """What one drive leaves the next is that it asked for a route, and a drive that ended at localize asked for none: d002 goes on at once,
    on a True nothing has cleared or on a topic still silent, and its note says it did not wait. A driver that counted every drive as asked
    would hold d002's route back for a state that never comes and end in the route step's timeout."""
    latched = initial_states(aw)
    if held is None:
        del latched[aw.OPERATION_MODE_TOPIC]
    else:
        latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True}
    fake = FakeAutoware(aw, latched=latched, follow=False, effects={STOP_SERVICE: []})

    def between(i):
        fake.follow = i == 1
    _f, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], fake=fake, between=between)
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["3\n", "0\n"], _jsonl(root / "d002" / "scenario.jsonl")[-1]
    first = _jsonl(root / "d001" / "scenario.jsonl")[-1]
    assert (first["step"], first["outcome"]) == ("localize", "timeout"), first
    assert not (root / "d001" / aw.AVAILABILITY_LOG).exists()
    assert [(x["available"], x["waited"]) for x in _jsonl(root / "d002" / aw.AVAILABILITY_LOG)] == [(held, False)]
    routes = _service_calls(fake, aw.ROUTE_SERVICE)
    localized = _jsonl(root / "d002" / "scenario.jsonl")[1]["mono_ns"]
    settle = aw.SETTLE_S if held is None else 0.0
    assert len(routes) == 1 and routes[0].t - localized <= (settle + 2 * aw.POLL_S) * S, (routes, localized)


NOTE_FAULTS = {"open": "no space left on device", "rename": "input/output error"}


def _note_fault(aw, monkeypatch, fault, drive):
    """A fault of the harness's own disk on the note of `drive` alone: its file cannot be made (`open`), or its rename is refused once its line
    is beside it (`rename`). Every other file of every drive is written as usual."""
    if fault == "open":
        real_open = open

        def opener(file, *args, **kwargs):
            if Path(file).parent.name == drive and Path(file).name.startswith(aw.AVAILABILITY_LOG):
                raise OSError(errno.ENOSPC, NOTE_FAULTS[fault])
            return real_open(file, *args, **kwargs)
        monkeypatch.setattr(aw, "open", opener, raising=False)
    else:
        real_replace = os.replace

        def replace(a, b):
            if Path(b).parent.name == drive and Path(b).name == aw.AVAILABILITY_LOG:
                raise OSError(errno.EIO, NOTE_FAULTS[fault])
            return real_replace(a, b)
        monkeypatch.setattr(aw.os, "replace", replace)


@pytest.mark.parametrize("fault", sorted(NOTE_FAULTS))
def test_a_note_the_disk_will_not_take_is_said_on_stderr_and_the_drive_goes_on(aw, tmp_path, monkeypatch, capsys, fault):
    """No item reads the note, so a fault of the harness's own disk on it must not read as T7's (an exception of the drive, exit 1, a FAIL by
    a reading that is never run again): it is said on stderr, leaves no part of the note behind, and the drive goes on, its steps Autoware's to
    answer. The next drive, whose note the disk takes, writes its own."""
    _note_fault(aw, monkeypatch, fault, "d001")
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"])
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "0\n"], _jsonl(root / "d001" / "scenario.jsonl")[-1]
    assert [(x["step"], x["outcome"]) for x in _jsonl(root / "d001" / "scenario.jsonl")[1:]] == [(s, "done") for s in STEPS]
    assert sorted(p.name for p in (root / "d001").iterdir()) == ["exit", "odometry.jsonl", "scenario.jsonl"]
    assert len(_jsonl(root / "d002" / aw.AVAILABILITY_LOG)) == 1
    assert fake.services() == [aw.LOCALIZE_SERVICE, aw.ROUTE_SERVICE, aw.ENGAGE_SERVICE, aw.CLEAR_SERVICE] * 2
    err = capsys.readouterr().err
    assert "d001/" + aw.AVAILABILITY_LOG in err and NOTE_FAULTS[fault] in err and "Traceback" not in err, err


@pytest.mark.parametrize("fault", sorted(NOTE_FAULTS))
def test_a_note_the_disk_will_not_take_leaves_the_waits_timeout_the_route_steps(aw, tmp_path, monkeypatch, capsys, fault):
    """The same fault on the note of a drive whose availability wait times out: the drive is still the route step's timeout naming the wait
    (exit 3, no route asked, the clear after a failed drive), never an exception of the drive that ends it at its localize line and hides what
    the wait read."""
    _note_fault(aw, monkeypatch, fault, "d002")
    fake, root, _go, _sc = _serve(aw, tmp_path, ["d001", "d002"], effects=_stays_available(aw))
    assert [_exit_of(aw, root, w) for w in ("d001", "d002")] == ["0\n", "3\n"]
    lines = _jsonl(root / "d002" / "scenario.jsonl")
    assert [(x["step"], x["outcome"]) for x in lines[1:]] == [("localize", "done"), ("route", "timeout")]
    assert "availability wait" in lines[-1]["detail"], lines[-1]
    assert fake.services()[4:] == [aw.LOCALIZE_SERVICE, STOP_SERVICE, aw.CLEAR_SERVICE], fake.services()
    assert sorted(p.name for p in (root / "d002").iterdir()) == [aw.AFTER_FAILURE_LOG, "exit", "odometry.jsonl", "scenario.jsonl"]
    err = capsys.readouterr().err
    assert "d002/" + aw.AVAILABILITY_LOG in err and NOTE_FAULTS[fault] in err and "Traceback" not in err, err


def test_the_readme_says_what_the_availability_wait_does_and_why():
    """sdv/aw/README.md's driver section, in its own voice: the wait, the topic and field it reads, why (a state published only when it
    changes), and the note's file."""
    flat = " ".join((REPO / "sdv" / "aw" / "README.md").read_text(encoding="utf-8").split())
    for words in ("availability wait", "is_autonomous_mode_available", "only when it changes", "availability.jsonl", "never asked for a route"):
        assert words in flat, words


def test_the_availability_waits_timeout_falls_at_the_routes_budget_never_a_poll_past_it(aw, tmp_path):
    """The wait spins at most what is left of the route's budget: with a budget that is no whole number of polls, its timeout, its line and
    the note's end fall at the budget itself, never a poll past it."""
    d = scenario_dict()
    d["timeouts_s"]["route"] = 20.05
    sc = aw.load_scenario(write_scenario(tmp_path, d))
    latched = initial_states(aw)
    latched[aw.OPERATION_MODE_TOPIC] = {aw.MODE_FIELD: 1, aw.AVAILABLE_FIELD: True}
    fake = FakeAutoware(aw, latched=latched)
    lines, notes = [], []
    assert aw.run(fake, sc, False, lines.append, availability=notes.append, memory=aw.Memory(route_asked=True)) == 3
    assert (lines[-1]["step"], lines[-1]["outcome"]) == ("route", "timeout") and "availability wait" in lines[-1]["detail"], lines[-1]
    budget = int(round(20.05 * S))
    assert notes[0]["end_mono_ns"] - notes[0]["start_mono_ns"] == budget == lines[-1]["mono_ns"] - lines[0]["mono_ns"], (notes, lines)


def test_a_route_step_whose_service_never_appeared_asked_for_no_route(aw, sc):
    """A route counts as asked from just before its request goes out: a route step that ended before it (the service never there) asked for
    none, so the next drive's availability wait does not apply."""
    m = aw.Memory()
    fake = FakeAutoware(aw, down=[aw.ROUTE_SERVICE])
    lines = []
    assert aw.run(fake, sc, False, lines.append, memory=m) == 3 and (lines[-1]["step"], lines[-1]["outcome"]) == ("route", "timeout")
    assert m.route_asked is False and aw.ROUTE_SERVICE not in fake.services()
