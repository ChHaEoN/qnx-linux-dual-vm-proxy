#!/usr/bin/env python3
"""uevent_inject.py -- run-uevent.sh's injector (Phase 3b / A6, 2026-09-24). Run as root
on the aux core while a probe round runs. At seeded, jittered times it does one of
two things to a thermal zone, three times back to back, as tj-thermal's poll does:

  U   write "change" to the zone's uevent file: three uevents, which udev and every
      listener process as they do the poll's own three -- and no temperature read;
  R   read the zone's temp: the temperature read through the driver (the BPMP on
      Tegra234) -- and no uevent.

Just before each, it writes "tjinj KIND I" to the ftrace marker, so the injection is
on the trace's own clock. Around each it reads /sys/kernel/uevent_seqnum. One JSON
line per injection goes to --log: its index, kind, CLOCK_MONOTONIC ns, the seqnum
before and after, and how long the three actions took.
"""
import argparse
import json
import random
import time


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zone", required=True, help="the zone's sysfs directory")
    ap.add_argument("--marker", required=True, help="the ftrace trace_marker file")
    ap.add_argument("--log", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--kinds", default="U,U,R,R", help="shuffled with the seed")
    ap.add_argument("--start", type=float, default=0.8, help="s after start of the first slot")
    ap.add_argument("--step", type=float, default=0.5, help="s between slots")
    ap.add_argument("--jitter", type=float, default=0.25, help="s, uniform, added to each slot")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--seqnum", default="/sys/kernel/uevent_seqnum")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    kinds = a.kinds.split(",")
    rng.shuffle(kinds)
    offs = [a.start + i * a.step + rng.uniform(0.0, a.jitter) for i in range(len(kinds))]
    t0 = time.monotonic()
    with open(a.log, "w") as log, open(a.marker, "w") as mark:
        for i, (kind, off) in enumerate(zip(kinds, offs)):
            wait = t0 + off - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            s0 = int(open(a.seqnum).read())
            mark.write("tjinj %s %d\n" % (kind, i))
            mark.flush()
            t = time.monotonic_ns()
            for _ in range(a.repeat):
                if kind == "U":
                    with open(a.zone + "/uevent", "w") as f:
                        f.write("change")
                else:
                    with open(a.zone + "/temp") as f:
                        f.read()
            dur = (time.monotonic_ns() - t) / 1000.0
            s1 = int(open(a.seqnum).read())
            log.write(json.dumps({"i": i, "kind": kind, "t_ns": t, "seq_before": s0, "seq_after": s1,
                                  "dur_us": round(dur, 1)}) + "\n")
            log.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
