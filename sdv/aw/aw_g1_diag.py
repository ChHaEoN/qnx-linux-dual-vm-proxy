#!/usr/bin/env python3
"""aw_g1_diag.py -- gate G1's diagnostics recorder (sdv/aw), the aw-g1-diag container. rclpy, in the Autoware image, under 2.12.
SDV Phase 8 WP8 Step B (sdv/aw/prereg-g1g2.md, PR, section 7).

    aw_g1_diag.py --out FILE

It subscribes to /diagnostics (RELIABLE, depth 50) and writes JSON Lines, each with the node's CLOCK_MONOTONIC as mono_ns:

    {"mono_ns", "first": true|false, "name", "hardware_id", "level", "message"}    a status's first observation; each change of its level
    {"mono_ns", "last_seen": {name: mono_ns}, "values": {name: {key: value}}}      every 5 s: each name's last-seen time, and the
                                                                                    key values of each control_topic_status
    {"mono_ns", "summary": name, "level", "count", "last_ns", "first_ns", "hardware_id"}   at the end, one per name, all with the time
                                                                                    of the close

Every status name is kept, not only the control path's: PR lists every other status that reached WARN or ERROR, and T5's silent
validator needs "other names" to compare with. SIGTERM ends it (docker stop). rclpy and the message package are imported inside main
only, so Recorder runs on any Python.

Does not demonstrate: a status it did not receive (the recorder is one more subscriber, load G1 would not otherwise have; its docker
stats lines are in the record); that a status means what its name says. PR section 7 holds the reading.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import Any, Callable, Dict, List, Optional

TOPIC = "/diagnostics"
QUEUE_DEPTH = 50                        # a whole array's burst, as the spike's recorder
SPACING_NS = 5_000_000_000              # PR section 7
SPIN_S = 0.5
VALUES_OF = "control_topic_status"      # the names whose key values are kept (measured_rate, PR section 6)
MESSAGE_MAX = 200


def level_of(raw: Any) -> int:
    """DiagnosticStatus.level: a byte in rclpy's message, an int on a stand-in."""
    return int.from_bytes(raw, "little") if isinstance(raw, (bytes, bytearray)) else int(raw)


class Recorder:
    """The recorder's state and lines; `write` takes one text line."""

    def __init__(self, write: Callable[[str], Any]) -> None:
        self.write = write
        self.state: Dict[str, Dict[str, Any]] = {}
        self.values: Dict[str, Dict[str, str]] = {}
        self.next_tick: Optional[int] = None

    def _line(self, doc: Dict[str, Any]) -> None:
        self.write(json.dumps(doc) + "\n")

    def seen(self, now: int, statuses: List[Any]) -> None:
        """One /diagnostics message."""
        if self.next_tick is None:
            self.next_tick = now + SPACING_NS
        for s in statuses:
            level = level_of(s.level)
            old = self.state.get(s.name)
            if old is None or old["level"] != level:
                self._line({"mono_ns": now, "first": old is None, "name": s.name, "hardware_id": s.hardware_id, "level": level,
                            "message": str(s.message)[:MESSAGE_MAX]})
            if old is None:
                old = {"count": 0, "first_ns": now, "hardware_id": s.hardware_id}
                self.state[s.name] = old
            old["level"] = level
            old["count"] += 1
            old["last_ns"] = now
            if VALUES_OF in s.name:
                self.values[s.name] = {v.key: v.value for v in s.values}

    def tick(self, now: int, force: bool = False) -> bool:
        """The 5 s line, when it is due or forced (the close's last line, with the time it was written); whether it wrote one. With no
        status ever seen there is nothing to say and none is written."""
        if self.next_tick is None or (now < self.next_tick and not force):
            return False
        self._line({"mono_ns": now, "last_seen": {n: st["last_ns"] for n, st in self.state.items()}, "values": self.values})
        self.next_tick = now + SPACING_NS
        return True

    def close(self, now: int) -> None:
        """The summary lines, one per name, each with NOW, the node's CLOCK_MONOTONIC as read at the close (PR section 7: every line has it)."""
        for name, st in sorted(self.state.items()):
            self._line({"mono_ns": now, "summary": name, **st})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import rclpy
    from diagnostic_msgs.msg import DiagnosticArray
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy

    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    stop: List[int] = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    with open(a.out, "a", buffering=1, encoding="utf-8", newline="\n") as out:
        rec = Recorder(out.write)
        rclpy.init()
        node = Node("aw_g1_diag")
        node.create_subscription(DiagnosticArray, TOPIC, lambda msg: rec.seen(time.monotonic_ns(), msg.status),
                                 QoSProfile(depth=QUEUE_DEPTH, reliability=ReliabilityPolicy.RELIABLE))
        while not stop and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=SPIN_S)
            rec.tick(time.monotonic_ns())
        rec.tick(time.monotonic_ns(), force=True)      # the last line, so the end of the last drive has one after it
        rec.close(time.monotonic_ns())
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
