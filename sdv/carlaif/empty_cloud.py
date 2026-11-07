#!/usr/bin/env python3
"""empty_cloud.py -- an empty obstacle cloud for Autoware's perception path in the CARLA 0.10.0 closed loop (sdv/carlaif;
SDV Phase 8 WP9 P2). An rclpy node on the Autoware side, in a container of its own from the Autoware image (aw-cloud).

The WP9 specification's section 1 item 11 (the project's local design notes; not in this
tree). Autoware's path planner runs only once it has received an occupancy grid, and its velocity planners accept an empty
cloud; with sensing and perception off nothing gives the upstream grid node its input. So this node publishes, on
/perception/obstacle_segmentation/pointcloud alone, a sensor_msgs/msg/PointCloud2 with no point (height and width 0, no
data), its frame base_link, stamped with sim time, every 0.1 s of sim time (10 Hz, a design value: under the planner's
0.9 s timeout), RELIABLE, KEEP_LAST 1, VOLATILE (a reliable publisher matches a reliable or a best-effort subscriber).
The upstream grid node makes the grid from it; no publisher of a grid stands here. The cloud carries the fields x, y and
z (float32, 12 bytes a point), so a reader that looks its fields up finds them, and no point. No sensor (D21).

    empty_cloud.py                (no options: its one topic is fixed)

The node takes use_sim_time true as its own parameter override (its timer and its stamps then follow /clock and stand
still until /clock arrives), no parameter services, and ignores the context's global arguments; rclpy is given the
program's name alone. A message fill_cloud would make with a point, or another frame, is refused (cloud_problems) and
never published. Exit 0 on rclpy's shutdown (Ctrl-C), 2 when rclpy or sensor_msgs cannot be imported.

DOES NOT SHOW: that the grid node makes a grid from an empty cloud (R0 reads it); that the planners treat this cloud as a
sensor's; any timing.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, List, Optional, Sequence

sys.dont_write_bytecode = True

NODE_NAME = "sdv_empty_cloud"
TOPIC = "/perception/obstacle_segmentation/pointcloud"
FRAME_ID = "base_link"
PERIOD_S = 0.1                       # 10 Hz of sim time (design value)
QOS = ("RELIABLE", 1)                # (reliability, KEEP_LAST depth), VOLATILE
FLOAT32 = 7                          # sensor_msgs/msg/PointField's FLOAT32
FIELDS = (("x", 0), ("y", 4), ("z", 8))
POINT_STEP = 12


def fill_cloud(msg: Any, field_cls: Any, stamp: Any) -> Any:
    """msg (a PointCloud2) made the empty cloud: no point, frame base_link, the stamp given, fields x, y, z."""
    msg.header.stamp = stamp
    msg.header.frame_id = FRAME_ID
    msg.height = 0
    msg.width = 0
    msg.fields = [field_cls(name=name, offset=offset, datatype=getattr(field_cls, "FLOAT32", FLOAT32), count=1) for name, offset in FIELDS]
    msg.is_bigendian = False
    msg.point_step = POINT_STEP
    msg.row_step = 0
    msg.data = []
    msg.is_dense = True
    return msg


def cloud_problems(msg: Any) -> List[str]:
    """Why msg is not the empty cloud: a point (a width or a height, or data), another frame."""
    out: List[str] = []
    if msg.width or msg.height or len(msg.data):
        out.append("the cloud holds a point (width %r, height %r, %d bytes)" % (msg.width, msg.height, len(msg.data)))
    if msg.header.frame_id != FRAME_ID:
        out.append("the cloud's frame is %r, not %s" % (msg.header.frame_id, FRAME_ID))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    argparse.ArgumentParser(prog="empty_cloud.py", description=(__doc__ or "").split("\n\n")[0]).parse_args(argv)
    try:
        import rclpy
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import PointCloud2, PointField
    except ImportError as err:
        print("empty_cloud: refused: rclpy or sensor_msgs cannot be imported: %s" % err, file=sys.stderr, flush=True)
        return 2
    rclpy.init(args=sys.argv[:1])
    node = Node(NODE_NAME, parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
                start_parameter_services=False, use_global_arguments=False)
    try:
        pub = node.create_publisher(PointCloud2, TOPIC, QoSProfile(depth=QOS[1], history=HistoryPolicy.KEEP_LAST,
                                                                    reliability=getattr(ReliabilityPolicy, QOS[0]),
                                                                    durability=DurabilityPolicy.VOLATILE))
        logger = node.get_logger()

        def tick() -> None:
            msg = fill_cloud(PointCloud2(), PointField, node.get_clock().now().to_msg())
            problems = cloud_problems(msg)
            if problems:
                logger.error("empty_cloud: refused to publish: %s" % "; ".join(problems))
                return
            pub.publish(msg)
        node.create_timer(PERIOD_S, tick)
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
