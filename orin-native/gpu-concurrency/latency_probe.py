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
import os
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


EXIT_DESYNC = 3          # a STALL: no reply (or no connect) within --timeout-s
EXIT_NOT_RECOVERED = 4
EXIT_BROKEN = 5          # the stream broke: reset, broken pipe, lost framing -- never a stall

_POLICY_NAMES = {getattr(os, n): n for n in
                 ("SCHED_OTHER", "SCHED_FIFO", "SCHED_RR", "SCHED_BATCH", "SCHED_IDLE")
                 if hasattr(os, n)}


def own_scheduling():
    """This process's scheduling policy, priority and CPU affinity, as it runs.

    Added 2026-09-21. The saturation cpu6_prio arm runs the probe through
    `sudo -n chrt -f 50 taskset -c 4`, and whether SCHED_FIFO was actually in
    effect was established only BY PROCEDURE -- chrt exits non-zero on failure,
    and the harness aborts on a non-zero exit -- never by measurement. An
    independent analysis called the priority control "uninformative" for exactly
    that reason. So the instrument now reports its own state, read from inside
    the process that took the samples, and the completeness gate checks it per
    arm. Reading it here rather than with `chrt -p` from outside avoids a race
    against a process that lives two seconds.

    Returns None for each field on a platform without the call (the unit tests
    run on Windows), so a missing reading is visible as null, not as a guess.
    """
    out = {"sched_policy": None, "sched_priority": None, "cpu_affinity": None}
    if hasattr(os, "sched_getscheduler"):
        pol = os.sched_getscheduler(0)
        out["sched_policy"] = _POLICY_NAMES.get(pol, str(pol))
        out["sched_priority"] = os.sched_getparam(0).sched_priority
    if hasattr(os, "sched_getaffinity"):
        out["cpu_affinity"] = sorted(os.sched_getaffinity(0))
    return out


def _broken(a, why, at, bad, rejected):
    """The stream broke without a timeout: a reset, a broken pipe, a short read.

    FOUND BY REVIEW, 2026-09-21: these used to leave through the same door as a
    timeout, so with stall recording on, a connection the guest dropped would
    have been filed as a 10 s stall and the run would have gone on. It is not a
    stall and it is not an outcome: no stall record, a distinct exit code, and
    the harness stops the run.
    """
    print("FATAL broken stream tag=%s at sample %d of %d: %s  (bad=%d rejected=%d)"
          % (a.tag, at, a.warmup + a.n, why, bad, rejected))
    print("      the arm is aborted and no result or stall file is written")
    return EXIT_BROKEN


def _abort(a, why, at, bad, rejected, kind, before):
    """Stop the arm on a STALL, loudly, and write no --out file.

    Writing no --out file is deliberate: a partial file with n below the
    requested count is the shape a truncated arm used to take, and a partial
    file can be mistaken for a complete one by anything that only counts files.
    A missing file cannot. The exit code is distinct so a caller can tell
    "the stream broke" from "could not connect" (2) or "nothing survived" (1).

    ADDED 2026-09-21: with --stall-out, the stall itself is written down as an
    OUTCOME, in a file of its own that no reader can take for a result: where
    it happened, what kind it was, the timed samples that came before it in
    arrival order, and the probe's own scheduling report. A board dry run found
    the guest can stop answering for more than the timeout under one load
    placement; that is a finding to record, not only a reason to stop. Only a
    timeout is a stall -- on a reply ("timeout") or on the connect itself
    ("connect": the guest stopped answering before the arm's first frame).
    """
    print("FATAL desync tag=%s at sample %d of %d: %s  (bad=%d rejected=%d)"
          % (a.tag, at, a.warmup + a.n, why, bad, rejected))
    print("      the arm is aborted and no result file is written")
    if a.stall_out:
        rec = {"stall": {"tag": a.tag, "kind": kind, "at_sample": at, "of": a.warmup + a.n,
                         "warmup": a.warmup, "timeout_s": a.timeout_s, "why": why,
                         "bad": bad, "rejected_by_monitor": rejected,
                         "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
               "samples_before_ms": before}
        rec["stall"].update(own_scheduling())
        with open(a.stall_out, "w") as f:
            json.dump(rec, f)
        print("      stall record written: %s (%d timed samples before it)" % (a.stall_out, len(before)))
    return EXIT_DESYNC


def await_recovery(a):
    """After a stall: how long until the guest answers one framed echo again.

    Each attempt is a fresh connection with a 1 s budget, retried every 0.2 s,
    so the figure is resolved to about a second, not to the microsecond. A reply
    the monitor rejects still counts as the guest answering. Writes --out when
    given, recovered or not, and exits EXIT_NOT_RECOVERED on the deadline.
    """
    t0 = time.monotonic()
    attempts = 0
    last = ""
    while time.monotonic() - t0 < a.await_recovery:
        attempts += 1
        try:
            with socket.create_connection((a.host, a.port), timeout=1.0) as s:
                s.settimeout(1.0)
                frame = build_frame(1)
                s.sendall(frame)
                got = b""
                while len(got) < FRAME_TOTAL:
                    chunk = s.recv(FRAME_TOTAL - len(got))
                    if not chunk:
                        break
                    got += chunk
            if len(got) == FRAME_TOTAL and got[:8] == frame[:8]:
                after = time.monotonic() - t0
                print("RECOVERED after %.2f s (attempts=%d)" % (after, attempts))
                if a.out:
                    with open(a.out, "w") as f:
                        json.dump({"tag": a.tag, "recovered": True, "after_s": after,
                                   "attempts": attempts}, f)
                return 0
            last = "framing lost (%d bytes)" % len(got)
        except OSError as e:
            last = str(e)
        time.sleep(0.2)
    print("NOT RECOVERED within %.0f s (attempts=%d, last: %s)" % (a.await_recovery, attempts, last))
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"tag": a.tag, "recovered": False, "within_s": a.await_recovery,
                       "attempts": attempts, "last": last}, f)
    return EXIT_NOT_RECOVERED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=7100)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--interval-ms", type=float, default=2.0)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--out", default="")
    ap.add_argument("--timeout-s", type=float, default=10.0,
                    help="per-connect and per-reply limit; a reply later than this is a stall")
    ap.add_argument("--stall-out", default="",
                    help="on a stall, write a stall record here (the arm still exits %d)" % EXIT_DESYNC)
    ap.add_argument("--await-recovery", type=float, default=0.0,
                    help="instead of sampling: seconds to wait for the guest to answer again")
    a = ap.parse_args()

    if a.await_recovery > 0:
        return await_recovery(a)

    try:
        s = socket.create_connection((a.host, a.port), timeout=a.timeout_s)
    except socket.timeout as e:
        # FOUND BY REVIEW: the load starts ~5 s before the probe connects, so a
        # stall can already be under way. Without this it exited 2 and the run
        # stopped, while the same stall one frame later was recorded.
        if a.stall_out:
            return _abort(a, "connect: %s" % e, 0, 0, 0, "connect", [])
        print("FATAL connect: %s" % e)
        return 2
    except OSError as e:
        print("FATAL connect: %s" % e)
        return 2
    s.settimeout(a.timeout_s)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    rtts = []
    in_arrival = []     # the timed samples in arrival order, for a stall record
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
        except socket.timeout as e:
            # A timeout here leaves the late reply IN FLIGHT on this socket.
            # Carrying on would read that reply as the next frame's, fail the
            # sequence check, and stay one frame out of phase for the rest of
            # the arm -- every later sample "bad", and the stall itself never
            # entering the timings, so `max` would silently omit the worst
            # event it exists to report. A desynchronised stream cannot be
            # measured on. The arm aborts and writes no result file.
            return _abort(a, "sample %d: %s" % (i, e), i, bad + 1, rejected, "timeout", in_arrival)
        except OSError as e:
            return _broken(a, "sample %d: %s" % (i, e), i, bad + 1, rejected)
        t1 = time.perf_counter()

        if len(got) != FRAME_TOTAL or got[:8] != frame[:8]:
            # Short read or wrong sequence without a timeout: the peer closed
            # or garbled the stream. Broken, not stalled.
            return _broken(a, "sample %d: framing lost (got %d of %d bytes, seq %s)"
                           % (i, len(got), FRAME_TOTAL,
                              "match" if got[:8] == frame[:8] else "MISMATCH"),
                           i, bad + 1, rejected)
        if got[FRAME_HEADER + P_VERDICT] != 0:
            rejected += 1          # monitor disagreed: a fault, not a timing sample
            continue
        if i >= a.warmup:
            rtts.append((t1 - t0) * 1000.0)
            in_arrival.append(rtts[-1])
        if gap > 0:
            time.sleep(gap)

    s.close()

    if not rtts:
        print("FATAL no samples survived (bad=%d rejected=%d)" % (bad, rejected))
        return 1

    # Keep the TIME ORDER before sorting. Until 2026-09-21 only the sorted list
    # was saved, and an idle-state slow mode (~11% of samples, +0.29 ms) could
    # then not be examined for periodicity, bursts or a tick: the order it
    # arrived in was gone. `samples_ms` stays sorted, because existing tools
    # read it that way; `samples_in_order` is the same values in arrival order.
    in_order = list(rtts)
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
    res.update(own_scheduling())
    print("RESULT %s" % json.dumps(res))
    print("  tag=%-12s n=%-5d min=%.3f p50=%.3f p90=%.3f p99=%.3f p99.9=%.3f max=%.3f  bad=%d rej=%d"
          % (res["tag"], res["n"], res["min_ms"], res["p50_ms"], res["p90_ms"],
             res["p99_ms"], res["p999_ms"], res["max_ms"], bad, rejected))

    if a.out:
        with open(a.out, "w") as f:
            json.dump({"summary": res, "samples_ms": rtts, "samples_in_order": in_order}, f)
        print("  wrote %s (%d samples)" % (a.out, len(rtts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
