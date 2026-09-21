#!/usr/bin/env python3
"""latency_probe.py — round-trip latency of the QNX guest's safety monitor, as a
distribution rather than a liveness yes/no.

  usage: latency_probe.py --host H [--port 7100] [--n 2000] [--warmup 200]
                          [--interval-ms 2] [--tag NAME] [--out FILE]

WHAT IT MEASURES. One TCP connection is opened and held; each sample writes a
valid 64-byte frame (ipc-test/common/frame.h layout) and waits for the monitor's
reply, timing the round trip with time.perf_counter(). So the number includes:
the Linux network stack, QEMU's virtio-net device, the bridge, the QNX guest's
io-sock, the monitor's own read/verdict/write, and the guest's scheduler putting
it on a vCPU. It is a SYSTEM round trip.

WHAT IT IS NOT. Not hypervisor IPC latency -- there is no hypervisor in A6; QNX
is a KVM guest. Not a partition-isolation or freedom-from-interference metric in
any certified sense. Not a QNX real-time claim: nothing here is a bounded-latency
guarantee, and the guest is not configured for one.

WHY ONE HELD CONNECTION. Opening a socket per sample would measure TCP setup,
not the service. The connection is opened once, drained, and reused; the monitor
serves one client at a time and loops on the same fd.

WHY WARM-UP IS DISCARDED. First frames pay page faults, ARP, and the guest's
first-touch costs. They are timed and thrown away, and the count is reported so
the discard is visible rather than silent.

The sentinel sequence (UINT64_MAX) is never sent: the monitor treats it as a
keepalive carrying no claim, which would not exercise the verdict path.
"""
import argparse
import json
import socket
import struct
import sys
import time

FRAME_TOTAL = 64
FRAME_HEADER = 16
PAYLOAD = 48
P_CLASS, P_CONF, P_INFER_US, P_VERDICT, P_REASON = 0, 1, 2, 6, 7


def build_frame(seq):
    """A claim the monitor will ACCEPT: class 3, confidence 95, 124 us."""
    hdr = struct.pack("<QQ", seq, 0)
    pay = bytearray(PAYLOAD)
    pay[P_CLASS] = 3
    pay[P_CONF] = 95
    pay[P_INFER_US:P_INFER_US + 4] = struct.pack("<I", 124)
    return hdr + bytes(pay)


def percentile(sorted_values, p):
    """Nearest-rank percentile over an ALREADY SORTED list.

    Lifted out of main() unchanged (2026-09-19) so CI can unit-test it; the
    arithmetic is byte-for-byte what every published figure from this probe was
    computed with, and must not be "improved" -- doing so would silently make
    new runs incomparable with the recorded ones.
    """
    k = int(round((p / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[k]


EXIT_DESYNC = 3


def _abort(a, why, at, bad, rejected):
    """Stop the arm on a desynchronised stream, loudly, and write nothing.

    Writing no --out file is deliberate: a partial file with n below the
    requested count is the shape a truncated arm used to take, and a partial
    file can be mistaken for a complete one by anything that only counts files.
    A missing file cannot. The exit code is distinct so a caller can tell
    "the stream broke" from "could not connect" (2) or "nothing survived" (1).
    """
    print("FATAL desync tag=%s at sample %d of %d: %s  (bad=%d rejected=%d)"
          % (a.tag, at, a.warmup + a.n, why, bad, rejected))
    print("      the arm is aborted and no result file is written")
    return EXIT_DESYNC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=7100)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--interval-ms", type=float, default=2.0)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    try:
        s = socket.create_connection((a.host, a.port), timeout=10)
    except OSError as e:
        print("FATAL connect: %s" % e)
        return 2
    s.settimeout(10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    rtts = []
    bad = 0
    rejected = 0
    seq = 0
    total = a.warmup + a.n
    gap = a.interval_ms / 1000.0

    for i in range(total):
        seq += 1
        if seq >= (1 << 63):          # never reach the sentinel
            seq = 1
        frame = build_frame(seq)
        t0 = time.perf_counter()
        try:
            s.sendall(frame)
            got = b""
            while len(got) < FRAME_TOTAL:
                chunk = s.recv(FRAME_TOTAL - len(got))
                if not chunk:
                    break
                got += chunk
        except OSError as e:
            # A timeout here leaves the late reply IN FLIGHT on this socket.
            # Carrying on would read that reply as the next frame's, fail the
            # sequence check, and stay one frame out of phase for the rest of
            # the arm -- every later sample "bad", and the stall itself never
            # entering the timings, so `max` would silently omit the worst
            # event it exists to report. A desynchronised stream cannot be
            # measured on. The arm aborts and writes no result file.
            return _abort(a, "sample %d: %s" % (i, e), i, bad + 1, rejected)
        t1 = time.perf_counter()

        if len(got) != FRAME_TOTAL or got[:8] != frame[:8]:
            # Short read or wrong sequence: the same desynchronisation, found
            # by the framing check instead of the timeout. Same response.
            return _abort(a, "sample %d: framing lost (got %d of %d bytes, seq %s)"
                          % (i, len(got), FRAME_TOTAL,
                             "match" if got[:8] == frame[:8] else "MISMATCH"),
                          i, bad + 1, rejected)
        if got[FRAME_HEADER + P_VERDICT] != 0:
            rejected += 1          # monitor disagreed: a fault, not a timing sample
            continue
        if i >= a.warmup:
            rtts.append((t1 - t0) * 1000.0)
        if gap > 0:
            time.sleep(gap)

    s.close()

    if not rtts:
        print("FATAL no samples survived (bad=%d rejected=%d)" % (bad, rejected))
        return 1

    rtts.sort()

    def pct(p):
        return percentile(rtts, p)

    res = {
        "tag": a.tag,
        "n": len(rtts),
        "warmup_discarded": a.warmup,
        "bad": bad,
        "rejected_by_monitor": rejected,
        "min_ms": rtts[0],
        "p50_ms": pct(50),
        "p90_ms": pct(90),
        "p99_ms": pct(99),
        "p999_ms": pct(99.9),
        "max_ms": rtts[-1],
        "mean_ms": sum(rtts) / len(rtts),
    }
    print("RESULT %s" % json.dumps(res))
    print("  tag=%-12s n=%-5d min=%.3f p50=%.3f p90=%.3f p99=%.3f p99.9=%.3f max=%.3f  bad=%d rej=%d"
          % (res["tag"], res["n"], res["min_ms"], res["p50_ms"], res["p90_ms"],
             res["p99_ms"], res["p999_ms"], res["max_ms"], bad, rejected))

    if a.out:
        with open(a.out, "w") as f:
            json.dump({"summary": res, "samples_ms": rtts}, f)
        print("  wrote %s (%d samples)" % (a.out, len(rtts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
