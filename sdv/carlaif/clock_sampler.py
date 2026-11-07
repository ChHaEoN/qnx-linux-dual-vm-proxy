#!/usr/bin/env python3
"""clock_sampler.py -- pairs of (/clock's sim time, CLOCK_MONOTONIC), one a second, so that a drive's wall-clock interval can
be read in sim time (sdv/carlaif; SDV Phase 8 WP9 P2). An rclpy node on the Autoware side, in a container of its own from
the Autoware image (aw-clock), beside the claim node.

The WP9 specification's section 9 item 1 (the project's local design notes; not in this
tree). The claim node stamps its frames with its own CLOCK_MONOTONIC and does not change; this node gives the pairs a
reader maps those stamps to sim time with, by linear interpolation between pairs. It runs in every run of the PC
rehearsal and, unchanged, on the edge.

    clock_sampler.py --out FILE

It subscribes to /clock with its publisher's QoS (the interface's: RELIABLE, VOLATILE, KEEP_LAST 10) and keeps the last
message's sim time with the CLOCK_MONOTONIC at which it arrived (time.monotonic_ns, in the callback). A timer on the
steady clock (CLOCK_MONOTONIC, never sim time) writes each second one line `SIM_NS MONO_RECEIPT_NS MONO_TICK_NS`: the last
pair received and the timer's own CLOCK_MONOTONIC (time.monotonic_ns, in the timer's callback), after a header line
beginning `# clock_sampler 2: `; before the first /clock it writes nothing. When no /clock arrived in a second the line
repeats the last pair beside a later tick, so a clock that stood still shows as lines whose receipt column is equal while
the tick column advances. The pairs to interpolate between are therefore the distinct receipt pairs (SIM_NS,
MONO_RECEIPT_NS) while the clock advances; between a pair's receipt and a line that repeats it, with no later receipt,
the clock stood at that SIM_NS, and a reader holds it there rather than spreading the next step over the stall. FILE is
created, never overwritten (an existing one is refused, exit 2), and each line is flushed as written. The node keeps
its own clock (use_sim_time false as its own parameter override), has no publisher and no parameter services, and
ignores the context's global arguments; rclpy is given the program's name alone. Exit 0 on rclpy's shutdown (Ctrl-C), 2
on a refusal or when rclpy or rosgraph_msgs cannot be imported.

DOES NOT SHOW: that a container's CLOCK_MONOTONIC is the claim node's (it is the host kernel's for every container of one
host, INFERRED); the delay between the interface's publish and this receipt; any timing.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

sys.dont_write_bytecode = True

NODE_NAME = "sdv_clock_sampler"
TOPIC = "/clock"
CLOCK_QOS = ("RELIABLE", 10)          # the interface's /clock publisher: RELIABLE, VOLATILE, KEEP_LAST 10 (READ at the pin)
PERIOD_S = 1.0                        # one line a second, on the steady clock
HEADER = ("# clock_sampler 2: SIM_NS MONO_RECEIPT_NS MONO_TICK_NS, the last /clock received, its CLOCK_MONOTONIC at receipt"
          " and the line's own CLOCK_MONOTONIC, one line a second\n")


def sim_ns(msg: Any) -> int:
    """A rosgraph_msgs/msg/Clock's time in nanoseconds."""
    return int(msg.clock.sec) * 1_000_000_000 + int(msg.clock.nanosec)


class Sampler:
    """The last (sim, mono at receipt) pair received and the line that writes it beside the tick's own mono."""

    def __init__(self) -> None:
        self.last: Optional[Tuple[int, int]] = None

    def on_clock(self, sim: int, mono: int) -> None:
        self.last = (sim, mono)

    def line(self, mono_tick: int) -> Optional[str]:
        return None if self.last is None else "%d %d %d\n" % (self.last[0], self.last[1], mono_tick)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="clock_sampler.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path, help="the file the pairs go to (created; never overwritten)")
    a = ap.parse_args(argv)
    try:
        import rclpy
        from rclpy.clock import Clock, ClockType
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from rosgraph_msgs.msg import Clock as ClockMsg
    except ImportError as err:
        print("clock_sampler: refused: rclpy or rosgraph_msgs cannot be imported: %s" % err, file=sys.stderr, flush=True)
        return 2
    try:
        out = open(a.out, "x", encoding="ascii")
    except OSError as err:
        print("clock_sampler: refused: %s cannot be created: %s" % (a.out, err), file=sys.stderr, flush=True)
        return 2
    sampler = Sampler()
    with out:
        out.write(HEADER)
        out.flush()
        rclpy.init(args=sys.argv[:1])
        node = Node(NODE_NAME, parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, False)],
                    start_parameter_services=False, use_global_arguments=False)
        try:
            def on_clock(msg: Any) -> None:
                sampler.on_clock(sim_ns(msg), time.monotonic_ns())

            def tick() -> None:
                line = sampler.line(time.monotonic_ns())
                if line is not None:
                    out.write(line)
                    out.flush()
            node.create_subscription(ClockMsg, TOPIC, on_clock, QoSProfile(depth=CLOCK_QOS[1], history=HistoryPolicy.KEEP_LAST,
                                                                           reliability=getattr(ReliabilityPolicy, CLOCK_QOS[0]),
                                                                           durability=DurabilityPolicy.VOLATILE))
            node.create_timer(PERIOD_S, tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
            rclpy.spin(node)
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            node.destroy_node()
            rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
