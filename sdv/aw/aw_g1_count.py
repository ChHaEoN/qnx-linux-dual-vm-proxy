#!/usr/bin/env python3
"""aw_g1_count.py -- gate G1's count recorder (sdv/aw), the aw-g1-count container of the guest-stopped arm, where no monitor answers
and the claim node does not run. rclpy, in the Autoware image, under 2.12. SDV Phase 8 WP8 Step B
(sdv/aw/prereg-g1g2.md, PR, sections 3 and 6).

    aw_g1_count.py --out FILE

A small node with the claim node's subscription QoS on /control/command/control_cmd (RELIABLE, KEEP_LAST 1, VOLATILE). It keeps only
arrival times, one JSON line per callback {"seq", "mono_ns"} with the node's CLOCK_MONOTONIC, and at the end {"summary": {"arrivals"}};
aw_g1.py judge reads them by the same rule as the claim node's frames. SIGTERM ends it. rclpy and the message package are imported
inside main only.

Does not demonstrate: the main arm's T4. Its callback is lighter than the claim node's, so this is not the same instrument and the two
are never subtracted (PR section 3); nothing about a guest, which is stopped in this arm.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import List, Optional

CONTROL_TOPIC = "/control/command/control_cmd"
SUBSCRIPTION_DEPTH = 1                  # KEEP_LAST 1, as ctl_claim_node.py's: a Control the callback never ran for is never counted
SPIN_S = 0.5


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import rclpy
    from autoware_control_msgs.msg import Control
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    stop: List[int] = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    n = [0]
    with open(a.out, "a", buffering=1, encoding="ascii", newline="\n") as out:
        def seen(_msg: object) -> None:
            n[0] += 1
            out.write(json.dumps({"seq": n[0], "mono_ns": time.monotonic_ns()}) + "\n")

        rclpy.init()
        node = Node("aw_g1_count")
        node.create_subscription(Control, CONTROL_TOPIC, seen,
                                 QoSProfile(depth=SUBSCRIPTION_DEPTH, history=HistoryPolicy.KEEP_LAST,
                                            reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE))
        while not stop and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=SPIN_S)
        out.write(json.dumps({"summary": {"arrivals": n[0]}}) + "\n")
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
