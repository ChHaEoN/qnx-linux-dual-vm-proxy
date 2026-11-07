#!/usr/bin/env python3
"""feeder_node.py -- the ROS->VSS feeder: its command line, its subscriptions and their callbacks, in one rclpy process
with the databroker's client (sdv/rosvss; Phase 8 WP3a).

Local branch only (decision 15). Runs in a Jazzy container (WP3b's image): Jazzy's Python 3.12 takes kuksa-client
0.6.0 (which needs 3.11 or later), so rclpy and the databroker's client share one process (D4's Jazzy branch). It is
never the claim node's process, and it is never in the claim path: the kind 2 claim goes from the claim node straight
to the guest (plan 3.2); the feeder only copies what the claim node publishes on /qnx_monitor/verdict, and the
vehicle's state, into the databroker's local branches. rclpy, the message packages and kuksa_out (with kuksa-client)
are imported inside main only, so this module imports with none of them installed.

    feeder_node.py --run-type planning-sim|carla-autoware [--databroker HOST:PORT]

SUBSCRIPTIONS (spec 2.8 and 5)
  planning-sim    /vehicle/status/velocity_status, /vehicle/status/steering_status, /vehicle/status/gear_status
                  (autoware_vehicle_msgs), /localization/acceleration (geometry_msgs AccelWithCovarianceStamped),
                  and /qnx_monitor/verdict (std_msgs String)
  carla-autoware  /qnx_monitor/verdict only (the CAN path writes the vehicle's state in that run type)
  Never /control/command/control_cmd: the claim node is its only subscriber, and the verdict message carries the
  command values as packed. The gear's name is the GearReport class's own constant for its report.
QoS
  the verdict: RELIABLE, KEEP_LAST 10, VOLATILE (spec 2.1, as the claim node publishes it);
  the vehicle topics: KEEP_LAST 1 (spec 5), BEST_EFFORT and VOLATILE. BEST_EFFORT is this file's choice: a best-effort
  subscriber matches a reliable or a best-effort publisher, and the feeder wants only the newest value, so it never
  goes without data because of a publisher's reliability (WP4a reads the real publishers' QoS).
EACH MESSAGE
  The callback builds one update (update.py; recv_ns is CLOCK_REALTIME, as a bag's receive time) and puts it on the
  writer's bounded queue (vsswriter.LatestQueue), and returns: it never waits for the databroker. A message the builder
  refuses is counted by its code and never queued. The writer thread maps, writes inside the run type's write set and
  logs counts as JSON lines on stdout (vsswriter.py).
START (exit 2 on a refusal, before any subscription)
  --databroker must be a loopback address literal with its port (127.0.0.0/8 or [::1]; no name is resolved): the
  databroker binds loopback only (plan 3.7). The databroker must serve every path of the run type's write set with its
  datatype (vsswriter.start_problems). When rclpy's signal handling ends spin (KeyboardInterrupt or
  ExternalShutdownException, both taken; which signals rclpy handles is rclpy's, not read here), the writer finishes the
  write in flight and logs its last counts line, and the process exits 0.
THE WRITER'S END (exit 1)
  The writer's thread starts once rclpy is initialised and the subscriptions are made. Should an exception end it
  (vsswriter's THE WRITER'S END: its log's stream failing, as a closed stdout does), it shuts rclpy down
  (rclpy.try_shutdown), which ends spin, and the process names the exception's type on stderr and exits 1 instead of
  spinning on with nothing written. It exits 1 too when the writer has not stopped STOP_JOIN_S after the stop (no last
  counts line).

DESIGN VALUES
  DEFAULT_DATABROKER = 127.0.0.1:55555: the claim bridge's default, the databroker's port on loopback.
  STOP_JOIN_S = 10 s: the longest wait for the writer at a stop (a write's own wait is 2 s).

DOES NOT DEMONSTRATE: that the feeder runs with the real rclpy, message packages and kuksa-client (the tests use
stand-ins; WP3b builds the image, WP4b runs it); the real publishers' QoS or rates; that VSS makes the monitor more
independent; any timing.
"""
from __future__ import annotations

import argparse
import functools
import importlib
import ipaddress
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import mapping  # noqa: E402
import update as upd  # noqa: E402
import vsswriter as vw  # noqa: E402

DEFAULT_DATABROKER = "127.0.0.1:55555"
NODE_NAME = "ros_vss_feeder"
STOP_JOIN_S = 10.0

# (topic, message module, message class, QoS kind, the run types that subscribe to it)
SUBSCRIPTIONS = (
    (upd.VELOCITY, "autoware_vehicle_msgs.msg", "VelocityReport", "vehicle", (mapping.PLANNING_SIM,)),
    (upd.STEERING, "autoware_vehicle_msgs.msg", "SteeringReport", "vehicle", (mapping.PLANNING_SIM,)),
    (upd.GEAR, "autoware_vehicle_msgs.msg", "GearReport", "vehicle", (mapping.PLANNING_SIM,)),
    (upd.ACCEL, "geometry_msgs.msg", "AccelWithCovarianceStamped", "vehicle", (mapping.PLANNING_SIM,)),
    (upd.VERDICT, "std_msgs.msg", "String", "verdict", mapping.RUN_TYPES),
)
# QoS kind -> (reliability, KEEP_LAST depth)
QOS = {"vehicle": ("BEST_EFFORT", 1), "verdict": ("RELIABLE", 10)}

Subscription = Tuple[str, str, str, str, Tuple[str, ...]]

_HOST_PORT = re.compile(r"^(?:\[([^\]]+)\]|([^:\[\]]+)):([0-9]{1,5})$")


def subscriptions(run_type: str) -> List[Subscription]:
    mapping.write_set(run_type)                      # an unknown run type is a ValueError
    return [s for s in SUBSCRIPTIONS if run_type in s[4]]


def parse_databroker(text: str) -> Tuple[str, int]:
    """(host, port) of a loopback HOST:PORT ([::1]:PORT for IPv6); a ValueError for anything else."""
    m = _HOST_PORT.match(text)
    if m is None:
        raise ValueError("%r is not HOST:PORT ([HOST]:PORT for IPv6)" % text)
    host, port = m.group(1) or m.group(2), int(m.group(3))
    if not 1 <= port <= 65535:
        raise ValueError("%r: the port is not in 1..65535" % text)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("%r: the databroker's host must be a loopback address literal; no name is resolved" % text) from None
    if not ip.is_loopback or getattr(ip, "scope_id", None) is not None:
        raise ValueError("%r is not a loopback address: the databroker binds loopback only" % text)
    return str(ip), port


def _databroker_arg(text: str) -> Tuple[str, int]:
    try:
        return parse_databroker(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from None


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="feeder_node.py", description="The ROS->VSS feeder (sdv/rosvss): copies the vehicle's "
                                "state and the kind 2 verdicts into the databroker's local branches.")
    p.add_argument("--run-type", required=True, choices=mapping.RUN_TYPES, help="the run type, which sets the write set")
    p.add_argument("--databroker", type=_databroker_arg, default=DEFAULT_DATABROKER,
                   help="the databroker's loopback HOST:PORT (default %s)" % DEFAULT_DATABROKER)
    return p.parse_args(argv)


def make_callback(build: Callable[[Any, int], Dict[str, Any]], queue: Any, refuse: Callable[[str], None],
                  clock: Callable[[], int] = time.time_ns) -> Callable[[Any], None]:
    """A subscription callback: build the message's update and put it on the queue (which never blocks); a message the
    builder refuses, or cannot read, is counted and dropped."""

    def callback(msg: Any) -> None:
        try:
            update = build(msg, clock())
        except upd.Refused as err:
            refuse(err.code)
            return
        except (AttributeError, TypeError, ValueError, ArithmeticError):
            refuse("message")
            return
        queue.put(update)

    return callback


def target(host: str, port: int) -> str:
    """HOST:PORT, with an IPv6 host in brackets."""
    return "[%s]:%d" % (host, port) if ":" in host else "%s:%d" % (host, port)


def _refuse_start(why: str) -> int:
    print("feeder: refused: %s" % why, file=sys.stderr)
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    opts = parse_args(argv)
    run_type = opts.run_type
    host, port = opts.databroker
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

    subs = subscriptions(run_type)
    classes = {topic: getattr(importlib.import_module(module), name) for topic, module, name, _kind, _rts in subs}
    builders: Dict[str, Callable[[Any, int], Dict[str, Any]]] = {
        upd.VELOCITY: upd.from_velocity, upd.STEERING: upd.from_steering, upd.ACCEL: upd.from_accel,
        upd.VERDICT: upd.from_verdict}
    if upd.GEAR in classes:
        try:
            names = upd.constant_names(classes[upd.GEAR])
        except ValueError as err:
            return _refuse_start(str(err))
        builders[upd.GEAR] = functools.partial(upd.from_gear, names=names)

    import kuksa_out
    try:
        sink = kuksa_out.KuksaOut(host, port)
    except Exception as err:  # noqa: BLE001 -- any failure to open the client refuses the start
        return _refuse_start("the databroker client did not open: %s" % type(err).__name__)
    write_set = sorted(mapping.write_set(run_type))
    try:
        problems = vw.start_problems(sink.value_types(write_set), run_type)
    except kuksa_out.KuksaOutError as err:
        problems = [str(err)]
    if problems:
        sink.close()
        return _refuse_start("; ".join(problems))

    # The writer's end shuts rclpy down, which ends spin (rclpy.try_shutdown takes a context already shut down).
    writer = vw.Writer(run_type, sink, vw.JsonLog(sys.stdout), on_failure=rclpy.try_shutdown)
    queue = vw.LatestQueue(vw.QUEUE_MAX)
    stop = threading.Event()
    thread = threading.Thread(target=writer.run, args=(queue, stop), name="vss-writer", daemon=True)
    writer.log("start", writer=mapping.WRITER, run_type=run_type, databroker=target(host, port), topics=[s[0] for s in subs],
               write_set=len(write_set), queue_max=vw.QUEUE_MAX)
    node = None
    try:
        rclpy.init()
        node = Node(NODE_NAME)
        for topic, _module, _name, kind, _rts in subs:
            reliability, depth = QOS[kind]
            profile = QoSProfile(depth=depth, history=HistoryPolicy.KEEP_LAST, reliability=getattr(ReliabilityPolicy, reliability),
                                 durability=DurabilityPolicy.VOLATILE)
            node.create_subscription(classes[topic], topic, make_callback(builders[topic], queue, writer.refuse), profile)
        thread.start()                  # once rclpy is initialised, so the writer's end always has a context to shut down
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        stop.set()
        if thread.ident is None:        # never started: rclpy or a subscription failed first
            writer.log_counts(final=True)
        else:
            thread.join(STOP_JOIN_S)
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
        sink.close()
    if writer.died is not None:
        print("feeder: the writer's thread ended on %s: nothing was written after it, and no last counts line came"
              % writer.died, file=sys.stderr)
        return 1
    if thread.is_alive():
        print("feeder: the writer did not stop within %g s of the stop: no last counts line came" % STOP_JOIN_S, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
