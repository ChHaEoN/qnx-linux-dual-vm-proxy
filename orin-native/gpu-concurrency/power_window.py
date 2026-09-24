#!/usr/bin/env python3
"""power_window.py -- sample the board's INA3221 power rails until told to stop
(Phase 3b / A6, 2026-09-24; run-power.sh).

  power_window.py --out FILE --stop-file PATH [--interval-ms 20] [--max-s 120]
                  [--hwmon DIR]

Every interval it reads each rail's bus voltage (inN_input, mV) and current
(currN_input, mA) and keeps (CLOCK_MONOTONIC ns, mW per rail). It stops when the
stop file exists, or after --max-s whatever happens, and writes one JSON:
{"rails": [...], "interval_ms": ..., "samples": [[t_ns, mW, mW, ...], ...]}.
The analysis cuts the samples to a window on the same clock (m_kvm_snap's t_ns).

The Orin Nano's INA3221 averages 512 conversions (hwmon `samples`), so its reading
changes only every ~140 ms: a 20 ms loop sees every change, and most reads repeat
the last one. The loop's own cost is a few file reads per interval, on whichever
core it is pinned to.
"""
import argparse
import glob
import json
import os
import sys
import time

DEFAULT_HWMON = "/sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*"


def rails(hwmon):
    """[(label, in_path, curr_path)] for every labelled channel."""
    out = []
    for i in range(1, 8):
        lab = os.path.join(hwmon, "in%d_label" % i)
        vin, cur = os.path.join(hwmon, "in%d_input" % i), os.path.join(hwmon, "curr%d_input" % i)
        if os.path.exists(lab) and os.path.exists(vin) and os.path.exists(cur):
            out.append((open(lab).read().strip(), vin, cur))
    return out


def read_mw(r):
    return int(open(r[1]).read()) * int(open(r[2]).read()) / 1000.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--stop-file", required=True)
    ap.add_argument("--interval-ms", type=float, default=20.0)
    ap.add_argument("--max-s", type=float, default=120.0)
    ap.add_argument("--hwmon", default="")
    a = ap.parse_args(argv)
    dirs = [a.hwmon] if a.hwmon else sorted(glob.glob(DEFAULT_HWMON))
    if not dirs:
        print("power_window: no INA3221 hwmon directory", file=sys.stderr)
        return 2
    rs = rails(dirs[0])
    if not rs:
        print("power_window: no labelled rails in %s" % dirs[0], file=sys.stderr)
        return 2
    samples = []
    t_end = time.monotonic() + a.max_s
    step = a.interval_ms / 1000.0
    while not os.path.exists(a.stop_file) and time.monotonic() < t_end:
        t = time.monotonic_ns()
        samples.append([t] + [round(read_mw(r), 1) for r in rs])
        time.sleep(step)
    with open(a.out, "w") as f:
        json.dump({"rails": [r[0] for r in rs], "interval_ms": a.interval_ms, "hwmon": dirs[0],
                   "samples": samples}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
