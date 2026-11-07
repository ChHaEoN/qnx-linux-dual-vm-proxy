#!/usr/bin/env python3
"""ctl_claim_node.py -- the kind 2 claim node: Autoware's gate output to the QNX guest's monitor, one frame per Control
(sdv/ctl). rclpy, in the Jazzy container.

The Phase 8 specification (the project's local design notes, sections 2.1, 2.6 and 4
item 4; not in this tree) defines it. A thin ROS shim around ctlclient.py's core, which does the packing, the
connection rules, the accounting, the reply log and the verdict messages:

    ctl_claim_node.py --host ADDR [--port 7150] [--stamp] [--profile ID] [--demo START_MS:DURATION_MS]
        [--inject SEQ:MODE ...] [--pause AFTER_SEQ:DURATION_MS] [--contract vss_ctl.py] --out DIR

  subscribes to /control/command/control_cmd (autoware_control_msgs/msg/Control) and /localization/kinematic_state
             (nav_msgs/msg/Odometry), each KEEP_LAST 1 (RELIABLE, VOLATILE): a Control the callback never ran for is
             overwritten, never queued, and never counted;
  publishes  2.6's message on /qnx_monitor/verdict (std_msgs/msg/String, RELIABLE, KEEP_LAST 10), once per frame
             outcome and once per connection change, and nothing else: never /diagnostics, whose system diagnostics feed
             Autoware's MRM chain and would turn an advisory verdict into an enforced one.

Each Control is handed to the core with the node's CLOCK_MONOTONIC receive time and the latest odometry with its own
receive time, so b3 is set only for an odometry inside the core's freshness window. The core's client thread owns
the socket; the callbacks only count and pack. The run ends with SIGINT or SIGTERM (rclpy's handlers end the spin),
after which the core drains and writes the reply log's summary; exit 0 when the accounting identity holds, 1 when it
does not, 2 for a refusal at start (made before rclpy is imported, and before the run directory is made).

It imports rclpy and the message packages inside main only, so its pure functions load (and are tested) without ROS.
It imports no KUKSA client, no gRPC, nothing of sdv/frame and not ctlrules: the claim never passes through the
databroker, and the reference judge is CI's (tests/test_sdv_ctl.py holds the import graph).

Does not demonstrate: that the monitor is in the control loop (it is not: the gate's output is observed after the gate
sent it); that Autoware's own faults would be caught (the gate clamps first, and injection happens after it); any
timing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ctlclient as cc  # noqa: E402

NODE_NAME = "ctl_claim_node"
CONTROL_TOPIC = "/control/command/control_cmd"
ODOM_TOPIC = "/localization/kinematic_state"
VERDICT_TOPIC = "/qnx_monitor/verdict"
SUBSCRIPTION_DEPTH = 1                 # KEEP_LAST 1 on both claim topics (the earlier plan's 2.1)
VERDICT_DEPTH = 10                     # RELIABLE, KEEP_LAST 10 (specification 2.1)


def stamp_ns(t: Any) -> int:
    """builtin_interfaces/Time as integer ns."""
    return int(t.sec) * 1_000_000_000 + int(t.nanosec)


def control_from_msg(msg: Any, recv_ns: int) -> cc.Control:
    """autoware_control_msgs/msg/Control (stamp, lateral, longitudinal) as the core's Control."""
    lat, lon = msg.lateral, msg.longitudinal
    return cc.Control(stamp_ns=stamp_ns(msg.stamp), recv_ns=recv_ns, velocity=float(lon.velocity),
                      acceleration=float(lon.acceleration), is_defined_acceleration=bool(lon.is_defined_acceleration),
                      jerk=float(lon.jerk), is_defined_jerk=bool(lon.is_defined_jerk),
                      steering_tire_angle=float(lat.steering_tire_angle),
                      steering_tire_rotation_rate=float(lat.steering_tire_rotation_rate),
                      is_defined_steering_tire_rotation_rate=bool(lat.is_defined_steering_tire_rotation_rate))


def odometry_from_msg(msg: Any, recv_ns: int) -> cc.Odometry:
    """nav_msgs/msg/Odometry's twist.twist.linear.x [m/s], the measured speed of 2.2's p[41..44]."""
    return cc.Odometry(v=float(msg.twist.twist.linear.x), recv_ns=recv_ns)


def argument_parser() -> Any:
    return cc.argument_parser("ctl_claim_node.py", __doc__)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        cfg, contract, run_dir = cc.prepare(args)
    except cc.ClientError as err:
        print("ctl_claim_node: %s" % err, file=sys.stderr, flush=True)
        return 2
    import rclpy
    from autoware_control_msgs.msg import Control as ControlMsg
    from nav_msgs.msg import Odometry as OdometryMsg
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    rclpy.init(args=None)
    node = Node(NODE_NAME)
    verdict_qos = QoSProfile(depth=VERDICT_DEPTH, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.VOLATILE)
    pub = node.create_publisher(String, VERDICT_TOPIC, verdict_qos)
    client = cc.CtlClient(cfg, contract, sink=lambda s: pub.publish(String(data=s)),
                          reply_log=run_dir / cc.REPLY_LOG, mode="node")
    latest: Dict[str, Optional[cc.Odometry]] = {"odom": None}

    def on_odometry(msg: Any) -> None:
        latest["odom"] = odometry_from_msg(msg, client.clock())

    def on_control(msg: Any) -> None:
        client.offer(control_from_msg(msg, client.clock()), latest["odom"])

    sub_qos = QoSProfile(depth=SUBSCRIPTION_DEPTH, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
    node.create_subscription(OdometryMsg, ODOM_TOPIC, on_odometry, sub_qos)
    node.create_subscription(ControlMsg, CONTROL_TOPIC, on_control, sub_qos)
    client.start()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        s = client.stop()
        node.destroy_node()
        rclpy.try_shutdown()
    print(cc.summary_line("ctl_claim_node", s), file=sys.stderr, flush=True)
    return cc.exit_code(s)


if __name__ == "__main__":
    sys.exit(main())
