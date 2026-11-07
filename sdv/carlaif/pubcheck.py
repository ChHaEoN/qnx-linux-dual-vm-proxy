#!/usr/bin/env python3
"""pubcheck.py -- the publisher checks of the CARLA 0.10.0 closed loop: who publishes what in the ROS graph, read once after
every container of a run is up and before its first route, and again after its last drive (sdv/carlaif; SDV Phase 8 WP9
P2). An rclpy node in a container of the interface's image (aw-pubcheck), judging with the pure functions below.

The WP9 specification's 2.6 (the project's local design notes; not in this tree).

    pubcheck.py --log FILE [--capture FILE] [--settle-s S] [--out FILE]

--log is `docker logs aw-carlaif` as text (the runbook keeps it in the run directory; it never enters a record); --capture
is a take's capture.json as sdv/carla/follow010.py writes it when the take ends, judged as the file given, and the read
after the last drive is made without it (a take that completes ends with the ego gone and the interface out of the graph,
so the runbook takes that take's half of item 5 from follow010.py's exit 0 and encode010.py's acceptance of the take,
which apply the same curve and settings rules). The node waits --settle-s seconds (a design value, 5: discovery on one
host's loopback) while spinning, reads every topic's publishers and subscriptions and the nodes, and judges:

  item 1  exactly one publisher on each of ONE_PUBLISHER's nine topics, the node named beside it where the project names
          that node: Autoware's actuation command (the converter), the shim's command (the shim), the interface's raw
          report (the interface), Autoware's steering report (the shim alone), the kinematic state and /clock (the
          interface alone), the acceleration (twist2accel), the obstacle cloud (empty_cloud.py) and the occupancy grid
          (the upstream grid node);
  item 2  every endpoint of the two actuation topics of one type, tier4_vehicle_msgs/msg/ActuationCommandStamped, which
          is the steering shim's ACTUATION_TYPE (sdv/steershim/steershim.py, loaded by its file);
  item 3  the interface's node, autoware_carla_interface, present, subscribed to the shim's command and not to
          Autoware's;
  item 4  no publisher on any topic under /sensing/lidar or /sensing/camera (a subscriber is no sensor), no node whose
          name begins with rviz;
  item 5  the interface's flat-curve line in the log and no line saying the flattening failed; with --capture, the take
          as follow010.py wrote it: not refused; its first world settings read, at attach, synchronous at TAKE_STEP_S
          (the launch's fixed_delta_seconds, CARLA_STEP_MS / 1000; the substep recorded in the take and copied into this
          record, not judged); and the vehicle's own steering-curve points equal to the interface's flattening,
          carla010_iso.FLAT_CURVE (sdv/sim/carla010_iso.py, loaded by its file), from both sources: what follows the
          client class's default prefix (0,1),(10,0.5) in physics_read.steering_curve, the curve as read (W9 E11, E14;
          carla010_iso.own_curve_points, which refuses a read without the prefix), and physics_read.own_points, the
          points follow010 recorded. That is follow010's own rule: it refuses a take whose world is not synchronous at
          the step at attach, at any re-read or at the end, or whose own points are not the flattening, and marks it
          refused, so a refused take never passes;
  item 6  exactly one publisher on the detection objects, the interface.

Each problem is printed as `item N: ...`, then one JSON record (also to --out); exit 0 when there is none, 1 when there is
one (the runbook then stops the run before any drive: status=FAILED at=pubcheck), 2 when the log or the take cannot be
read (a take that is not a JSON object is one), rclpy cannot be imported, rclpy cannot start or the graph cannot be read
(no item is judged then), or the record cannot be written. No timer, no publisher of its own, no parameter services;
rclpy is given the program's name alone, and the node ignores the context's global arguments.

DOES NOT SHOW: an endpoint discovery has not shown by the end of the settle; that a publisher publishes (a count of
endpoints, not of messages); that the grid is made from the cloud; any timing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
STEERSHIM_FILE = HERE.parent / "steershim" / "steershim.py"
ISO_FILE = HERE.parent / "sim" / "carla010_iso.py"
# the tree is mounted read-only in the container; a run from a writable tree must leave no __pycache__
sys.dont_write_bytecode = True

NODE_NAME = "sdv_pubcheck"
INTERFACE_NODE = "autoware_carla_interface"                 # sdv_carla.launch.xml names the interface's node so (the pin's launch does)
CONVERTER_NODE = "autoware_raw_vehicle_cmd_converter"       # and the converter's
SHIM_NODE = "sdv_steershim"                                 # sdv/steershim/shim_node.py's NODE_NAME
CLOUD_NODE = "sdv_empty_cloud"                              # empty_cloud.py's NODE_NAME
# item 1: (topic, the node that must be its one publisher, or None where no file of the project names that node)
ONE_PUBLISHER: Tuple[Tuple[str, Optional[str]], ...] = (
    ("/control/command/actuation_cmd", CONVERTER_NODE),
    ("/sdv/steershim/actuation_cmd", SHIM_NODE),
    ("/sdv/steershim/steering_status_raw", INTERFACE_NODE),
    ("/vehicle/status/steering_status", SHIM_NODE),
    ("/localization/kinematic_state", INTERFACE_NODE),
    ("/clock", INTERFACE_NODE),
    ("/localization/acceleration", None),
    ("/perception/obstacle_segmentation/pointcloud", CLOUD_NODE),
    ("/perception/occupancy_grid_map/map", None),
)
IN_ACTUATION = "/control/command/actuation_cmd"            # Autoware's converter -> the shim
OUT_ACTUATION = "/sdv/steershim/actuation_cmd"             # the shim -> the interface
ACTUATION_TOPICS = (IN_ACTUATION, OUT_ACTUATION)
ACTUATION_TYPE_NAME = "tier4_vehicle_msgs/msg/ActuationCommandStamped"
FORBIDDEN_PREFIXES = ("/sensing/lidar", "/sensing/camera")
OBJECTS_TOPIC = "/perception/object_recognition/detection/objects"
FLAT_CURVE_LINE = "INFO: Applied a flat steering curve to the ego vehicle."     # the pin's carla_autoware.py, a bare print
FLAT_CURVE_FAILED = "WARNING: Failed to flatten the steering curve"
SETTLE_S = 5.0
TAKE_STEP_S = 0.05          # sdv_carla.launch.xml's fixed_delta_seconds, CARLA_STEP_MS / 1000 (a test holds the three equal)
STEP_TOL = 1e-9             # sdv/carla/worldtie.py's FLOAT_TOL: a double read back across the RPC

Graph = Dict[str, Any]


def _by_file(key: str, path: Path) -> Any:
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _steershim() -> Any:
    return _by_file("_sdv_steershim_for_pubcheck", STEERSHIM_FILE)


def _iso() -> Any:
    return _by_file("_sdv_carla010_iso_for_pubcheck", ISO_FILE)


def type_name(module_class: Sequence[str]) -> str:
    """('pkg.msg', 'Class') as the graph names the type: 'pkg/msg/Class'."""
    return "%s/%s" % (module_class[0].replace(".", "/"), module_class[1])


def fq(ep: Dict[str, str]) -> str:
    """An endpoint's node as /namespace/name."""
    ns = ep.get("namespace") or "/"
    return ns.rstrip("/") + "/" + ep["node"]


def _names(eps: Sequence[Dict[str, str]]) -> str:
    return ", ".join(fq(e) for e in eps) or "none"


def judge(graph: Graph, log_text: str, capture: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every problem with the graph (publishers and subscriptions by topic, each endpoint {node, namespace, type}; the nodes
    as [name, namespace]), the interface's log and, when given, the take's capture, each as `item N: ...`."""
    out: List[str] = []
    pubs: Dict[str, List[Dict[str, str]]] = graph.get("publishers") or {}
    subs: Dict[str, List[Dict[str, str]]] = graph.get("subscriptions") or {}
    for topic, who in ONE_PUBLISHER:
        eps = pubs.get(topic, [])
        if len(eps) != 1:
            out.append("item 1: %d publishers on %s (%s), not exactly one" % (len(eps), topic, _names(eps)))
        elif who is not None and fq(eps[0]) != "/" + who:
            out.append("item 1: the publisher on %s is %s, not /%s" % (topic, fq(eps[0]), who))
    shim_type = type_name(_steershim().ACTUATION_TYPE)
    if shim_type != ACTUATION_TYPE_NAME:
        out.append("item 2: the steering shim's ACTUATION_TYPE is %s, not %s" % (shim_type, ACTUATION_TYPE_NAME))
    for topic in ACTUATION_TOPICS:
        eps = pubs.get(topic, []) + subs.get(topic, [])
        types = sorted({e["type"] for e in eps})
        if types != [ACTUATION_TYPE_NAME]:
            out.append("item 2: the endpoints of %s are of %s, not of the one type %s" % (topic, types or "no type", ACTUATION_TYPE_NAME))
    nodes = [(str(n[0]), str(n[1])) for n in graph.get("nodes") or []]
    if (INTERFACE_NODE, "/") not in nodes:
        out.append("item 3: no node /%s in the graph" % INTERFACE_NODE)
    else:
        if not [e for e in subs.get(OUT_ACTUATION, []) if fq(e) == "/" + INTERFACE_NODE]:
            out.append("item 3: /%s does not subscribe to %s" % (INTERFACE_NODE, OUT_ACTUATION))
        if [e for e in subs.get(IN_ACTUATION, []) if fq(e) == "/" + INTERFACE_NODE]:
            out.append("item 3: /%s subscribes to %s" % (INTERFACE_NODE, IN_ACTUATION))
    for topic in sorted(pubs):
        if pubs[topic] and any(topic == p or topic.startswith(p + "/") for p in FORBIDDEN_PREFIXES):
            out.append("item 4: a publisher on %s (%s)" % (topic, _names(pubs[topic])))
    for name, ns in nodes:
        if name.startswith("rviz"):
            out.append("item 4: a node %s" % (ns.rstrip("/") + "/" + name))
    lines = [ln.strip() for ln in log_text.splitlines()]
    if not [ln for ln in lines if ln.endswith(FLAT_CURVE_LINE)]:
        out.append("item 5: the interface's log has no line %r" % FLAT_CURVE_LINE)
    failed = [ln for ln in lines if FLAT_CURVE_FAILED in ln]
    if failed:
        out.append("item 5: the interface's log says the flattening failed: %s" % failed[0])
    if capture is not None:
        out.extend("item 5: " + p for p in take_problems(capture))
    eps = pubs.get(OBJECTS_TOPIC, [])
    if len(eps) != 1 or fq(eps[0]) != "/" + INTERFACE_NODE:
        out.append("item 6: the publishers on %s are %s, not the interface alone" % (OBJECTS_TOPIC, _names(eps)))
    return out


def attach_settings(capture: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The settings of the take's first world settings read when that read is follow010's at attach, else None."""
    reads = capture.get("world_settings")
    first = reads[0] if isinstance(reads, list) and reads and isinstance(reads[0], dict) else {}
    settings = first.get("settings") if first.get("at") == "attach" else None
    return settings if isinstance(settings, dict) else None


def take_problems(capture: Dict[str, Any]) -> List[str]:
    """Item 5's second source, the take as follow010.py wrote it (capture.json): every reason it does not show the
    interface's flattening under the tie, each without its item number."""
    iso = _iso()
    flat = [list(p) for p in iso.FLAT_CURVE]
    out: List[str] = []
    if capture.get("refused"):
        out.append("the take was refused by follow010.py: %s" % capture["refused"])
    settings = attach_settings(capture)
    if settings is None:
        out.append("the take holds no world settings read at attach first")
    else:
        sync, fd = settings.get("synchronous_mode"), settings.get("fixed_delta_seconds")
        if sync is not True or isinstance(fd, bool) or not isinstance(fd, (int, float)) or not abs(float(fd) - TAKE_STEP_S) <= STEP_TOL:
            out.append("the world settings read at attach (synchronous_mode %r, fixed_delta_seconds %r) are not synchronous at %r s"
                       % (sync, fd, TAKE_STEP_S))
    phys = capture.get("physics_read")
    phys = phys if isinstance(phys, dict) else {}
    curve = phys.get("steering_curve")
    try:
        own_read: Optional[List[List[float]]] = [list(p) for p in iso.own_curve_points(curve if isinstance(curve, list) else [])]
    except (iso.ConversionError, TypeError, ValueError, IndexError):
        own_read = None
    if own_read != flat:
        out.append("the vehicle's own steering-curve points in the curve as read, %r (what follows the client class's default "
                   "prefix %r; None: the read does not begin with it), are not the interface's flattening %r"
                   % (own_read, [list(p) for p in iso.CURVE_PREFIX], flat))
    if phys.get("own_points") != flat:
        out.append("the vehicle's own steering-curve points follow010.py recorded, %r, are not the interface's flattening %r"
                   % (phys.get("own_points"), flat))
    return out


def read_graph(node: Any) -> Graph:
    """The graph as judge takes it, from an rclpy node: every topic's publishers and subscriptions (topics with none left
    out) and the nodes."""
    def eps(infos: Any) -> List[Dict[str, str]]:
        return [{"node": str(i.node_name), "namespace": str(i.node_namespace), "type": str(i.topic_type)} for i in infos]
    pubs: Dict[str, List[Dict[str, str]]] = {}
    subs: Dict[str, List[Dict[str, str]]] = {}
    for topic, _types in node.get_topic_names_and_types():
        p, s = eps(node.get_publishers_info_by_topic(topic)), eps(node.get_subscriptions_info_by_topic(topic))
        if p:
            pubs[topic] = p
        if s:
            subs[topic] = s
    return {"publishers": pubs, "subscriptions": subs, "nodes": [[str(n), str(ns)] for n, ns in node.get_node_names_and_namespaces()]}


def _refuse(why: str) -> int:
    print("pubcheck: refused: %s" % why, file=sys.stderr, flush=True)
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="pubcheck.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--log", required=True, type=Path, help="`docker logs aw-carlaif` as text")
    ap.add_argument("--capture", type=Path, help="a take's capture.json as follow010.py writes it when the take ends"
                    " (the read after the last drive is made without it)")
    ap.add_argument("--settle-s", type=float, default=SETTLE_S, help="seconds of discovery before the graph is read")
    ap.add_argument("--out", type=Path, help="also write the JSON record here")
    a = ap.parse_args(argv)
    try:
        log_text = a.log.read_text(encoding="utf-8", errors="replace")
        capture = json.loads(a.capture.read_text(encoding="utf-8")) if a.capture is not None else None
    except (OSError, ValueError) as err:
        return _refuse("the log or the take cannot be read: %s" % err)
    if a.capture is not None and not isinstance(capture, dict):      # a list, a number, a string, or null (which reads as no take)
        return _refuse("the take is not a JSON object")
    try:
        import rclpy
        from rclpy.node import Node
    except ImportError as err:
        return _refuse("rclpy cannot be imported: %s" % err)
    try:
        rclpy.init(args=sys.argv[:1])
        try:
            node = Node(NODE_NAME, start_parameter_services=False, use_global_arguments=False)
            try:
                end = time.monotonic() + max(0.0, a.settle_s)
                while time.monotonic() < end:
                    rclpy.spin_once(node, timeout_sec=0.1)
                graph = read_graph(node)
            finally:
                node.destroy_node()
        finally:
            rclpy.try_shutdown()
    except Exception as err:  # noqa: BLE001 - no item was judged: a refusal, never the 1 of a failed item
        return _refuse("rclpy could not start or the graph could not be read: %s: %s" % (type(err).__name__, err))
    problems = judge(graph, log_text, capture)
    for p in problems:
        print(p, flush=True)
    record = {"format": 1, "ok": not problems, "problems": problems,
              "one_publisher": {t: [fq(e) for e in graph["publishers"].get(t, [])] for t, _w in ONE_PUBLISHER + ((OBJECTS_TOPIC, None),)},
              "nodes": len(graph["nodes"]), "capture_judged": capture is not None,
              "take_attach_settings": attach_settings(capture) if capture is not None else None}
    text = json.dumps(record, sort_keys=True)
    print(text, flush=True)
    if a.out is not None:
        try:
            a.out.write_text(text + "\n", encoding="utf-8")
        except OSError as err:
            return _refuse("the record cannot be written: %s" % err)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
