#!/usr/bin/env python3
"""shim_node.py -- D22's steering shim as an rclpy node: Autoware's actuation command to CARLA 0.10.0's interface through
the inverse of carla010_iso.py's steering model, and the interface's steering report back through the law (sdv/steershim).
rclpy, in a Jazzy container of its own from the interface's image.

Phase 8 WP9b's steering shim. A thin node around steershim.py's pure functions:

    shim_node.py                          (no options: its topics are 2.10's and are not remapped)

  subscribes to /control/command/actuation_cmd (the actuation command, steershim.ACTUATION_TYPE) and
             /sdv/steershim/steering_status_raw (autoware_vehicle_msgs/msg/SteeringReport, the interface's report
             remapped), each BEST_EFFORT, KEEP_LAST 1, VOLATILE;
  publishes  /sdv/steershim/actuation_cmd (the same type, to the interface, remapped at its launch) and
             /vehicle/status/steering_status (SteeringReport, to Autoware), each RELIABLE, KEEP_LAST 1, VOLATILE;
  no timer, no service and no parameter of its own, never a topic of the claim path. rclpy adds /rosout,
  /parameter_events and the use_sim_time parameter on its own, whatever the node asks. The node is made without the
  parameter services (start_parameter_services=False) and ignores the context's global ROS arguments
  (use_global_arguments=False), and rclpy.init is given the program's name alone (sys.argv[:1]): no remap and no
  parameter from a command line reaches it, whoever calls main.

EACH MESSAGE
  The callback copies the message with its steer replaced (steershim.inverse or steershim.forward, C read once at the
  start from sdv/sim/carla010_iso.py) and publishes the copy; it keeps nothing between messages. A message whose steer
  the pure functions refuse (not finite; a raw report beyond full steer) is logged as an error and not published. A
  report is published only while the graph shows exactly one publisher on /vehicle/status/steering_status, this node.
  The graph is asked only when a raw report arrives, so what the guard can see is a second publisher there while the
  interface's raw reports come in: another simulator, a second interface whose report is not remapped, or a second
  shim of this name; the report is then logged as an error with the count and not published. A count of none
  (discovery not yet showing this node's own publisher) only delays the first reports. An interface whose report is
  not remapped sends no raw report at all, so the shim never hears of it: WP9's publisher checks catch that, not the
  shim.
START (exit 2 on a refusal)
  Before rclpy is imported: any interface constant still a stand-in (steershim.STAND_INS), or a conversion zero or not
  finite; C unreadable or not one finite literal in (0, 90). Then, before rclpy.init: rclpy or a message package that
  cannot be imported; a steer field path (steershim.ACTUATION_STEER, steershim.REPORT_STEER) that its message type
  lacks or holds as no float. When rclpy's signal handling ends spin (KeyboardInterrupt or ExternalShutdownException),
  the node is destroyed and the process exits 0. Any other failure ends in Python's traceback and exit 1.

QoS: a best-effort subscription matches a reliable or a best-effort publisher, so the shim never goes without a
message for the publisher's reliability (READ by WP9 at the pin, 94b8fbd3: the converter's, the interface's report's and
its actuation subscription's are each depth 1, so RELIABLE, VOLATILE, KEEP_LAST 1); a reliable, volatile publisher matches
a reliable or best-effort, volatile subscriber, as W4 G7 read Autoware's vehicle status topics (RELIABLE, KEEP_LAST 1,
VOLATILE). KEEP_LAST 1: only the newest message matters.

DOES NOT DEMONSTRATE: that the node runs with the real rclpy and message packages (the tests use stand-ins); that the
graph check sees every second publisher (only those discovery has shown it); that the real taxi's wheels and curve are
what the interface's conversions are given (READ by WP9 at the pin, 94b8fbd3); any timing.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
# the tree is mounted read-only in the container; a run from a writable tree must leave no __pycache__ beside steershim.py
sys.dont_write_bytecode = True
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import steershim as ss  # noqa: E402

NODE_NAME = "sdv_steershim"
# (reliability, KEEP_LAST depth), both VOLATILE: the subscriptions' and the publishers' QoS (see QoS above)
SUBSCRIPTION_QOS = ("BEST_EFFORT", 1)
PUBLISHER_QOS = ("RELIABLE", 1)

Callback = Callable[[Any], None]


def make_callbacks(c: float, publish_actuation: Callback, publish_report: Callback, report_publishers: Callable[[], Sequence[Any]],
                   node_name: str, namespace: str, log: Callable[[str], None]) -> Tuple[Callback, Callback]:
    """The two subscription callbacks: (on_actuation, on_report). report_publishers() gives the graph's publisher infos
    on /vehicle/status/steering_status, asked once per raw report; a report is published only while they are exactly one,
    this node. log takes one error line. Neither callback keeps anything between messages."""

    def on_actuation(msg: Any) -> None:
        try:
            out = ss.with_field(msg, ss.ACTUATION_STEER, ss.inverse(ss.field_of(msg, ss.ACTUATION_STEER), c))
        except ss.ShimError as err:
            log("steershim: refused an actuation command on %s: %s" % (ss.IN_ACTUATION, err))
            return
        publish_actuation(out)

    def on_report(msg: Any) -> None:
        infos = list(report_publishers())
        others = ss.other_publishers(infos, node_name, namespace)
        if others or len(infos) != 1:
            log("steershim: refused a report: the graph shows %d publishers on %s, not exactly one, this node (of other names: "
                "%s)" % (len(infos), ss.OUT_REPORT, ", ".join(others) or "none"))
            return
        try:
            out = ss.with_field(msg, ss.REPORT_STEER, ss.forward(ss.field_of(msg, ss.REPORT_STEER), c))
        except ss.ShimError as err:
            log("steershim: refused a report on %s: %s" % (ss.IN_REPORT, err))
            return
        publish_report(out)

    return on_actuation, on_report


def argument_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="shim_node.py", description="D22's steering shim (sdv/steershim): Autoware's actuation "
                                   "command to CARLA 0.10.0's interface through the inverse of the steering law, and its "
                                   "steering report back through the law. No options: its topics are spec-2 2.10's.")


def _refuse(why: str) -> int:
    print("steershim: refused: %s" % why, file=sys.stderr, flush=True)
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    argument_parser().parse_args(argv)
    problems: List[str] = ss.start_problems()
    if problems:
        return _refuse("; ".join(problems))
    try:
        c = ss.load_c(ss.CARLA010_ISO)
    except ss.ShimError as err:
        return _refuse(str(err))
    try:
        import rclpy
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        actuation_type = getattr(importlib.import_module(ss.ACTUATION_TYPE[0]), ss.ACTUATION_TYPE[1])
        report_type = getattr(importlib.import_module(ss.REPORT_TYPE[0]), ss.REPORT_TYPE[1])
    except (ImportError, AttributeError) as err:
        return _refuse("rclpy or a message package cannot be imported: %s" % err)
    try:
        ss.check_steer_field(actuation_type, ss.ACTUATION_STEER)
        ss.check_steer_field(report_type, ss.REPORT_STEER)
    except ss.ShimError as err:
        return _refuse("a steer field path is not a float field of its message type: %s" % err)

    def qos(kind: Tuple[str, int]) -> Any:
        return QoSProfile(depth=kind[1], history=HistoryPolicy.KEEP_LAST, reliability=getattr(ReliabilityPolicy, kind[0]),
                          durability=DurabilityPolicy.VOLATILE)

    print("steershim: C %r deg from %s; %s -> %s, %s -> %s" % (c, ss.CARLA010_ISO, ss.IN_ACTUATION, ss.OUT_ACTUATION,
                                                                ss.IN_REPORT, ss.OUT_REPORT), file=sys.stderr, flush=True)
    # the program's name alone, never sys.argv's ROS arguments (rclpy.init takes sys.argv when given None); the node
    # without parameter services and without the context's global arguments (rclpy's Node defaults both on)
    rclpy.init(args=sys.argv[:1])
    node = Node(NODE_NAME, start_parameter_services=False, use_global_arguments=False)
    try:
        pub_actuation = node.create_publisher(actuation_type, ss.OUT_ACTUATION, qos(PUBLISHER_QOS))
        pub_report = node.create_publisher(report_type, ss.OUT_REPORT, qos(PUBLISHER_QOS))
        logger = node.get_logger()
        on_actuation, on_report = make_callbacks(c, pub_actuation.publish, pub_report.publish,
                                                 lambda: node.get_publishers_info_by_topic(ss.OUT_REPORT), node.get_name(),
                                                 node.get_namespace(), logger.error)
        node.create_subscription(actuation_type, ss.IN_ACTUATION, on_actuation, qos(SUBSCRIPTION_QOS))
        node.create_subscription(report_type, ss.IN_REPORT, on_report, qos(SUBSCRIPTION_QOS))
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
