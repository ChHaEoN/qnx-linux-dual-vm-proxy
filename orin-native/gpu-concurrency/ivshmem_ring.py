#!/usr/bin/env python3
"""ivshmem_ring.py -- ring the QNX guest through ivshmem-doorbell's MSI-X (A6, 2026-09-29).

  usage: ivshmem_ring.py --socket PATH [--count N] [--gap-ms G] [--echo]
                         [--timeout-ms T] [--guest-peer 1] [--vector 0] [--join-wait-s 0]
                         [--slot OFF] [--json FILE]

WHAT IT IS FOR. The host-to-guest half of the ivshmem doorbell, which QEMU 6.2
delivers to a guest by MSI-X only. It joins ivshmem_server.py as one more peer
(the protocol is that file's header), and a write to the GUEST's vector-0
eventfd -- peer 1 is QEMU, whose eventfds the server hands every peer -- is
what makes QEMU (or KVM, through an irqfd) send the device's MSI-X message. In
the guest, ipc-test/qnx-its-probe (msixcfg) has pointed that message at the GIC
ITS and mapped it to an LPI, and `qnx-its-probe msixwait` waits on the LPI.

WITH --echo it also puts its own peer id at ECHO_OFF in the shared memory,
where msixwait reads it and rings this peer back through the Doorbell register
(a KVM ioeventfd on this peer's eventfd). Each exchange then crosses the
boundary twice, by interrupt both ways, with no console on the path, and this
prints how many came back within --timeout-ms. Without --echo it only rings,
and what arrived is read from the guest's console.

WITH --slot OFF (2026-09-29, the robustness matrix) it observes a notified shm monitor's slot
at OFF while it rings with no request there: it puts its own peer id in the slot's client_peer
and SHM_VIA_DOORBELL in its reply_via, never touches req_seq, waits OBSERVER_SETTLE_S so QEMU
knows its peer id, and counts the doorbells that reach it. A monitor that answers a ring it did not find a new request for would ring this peer; one
that does not, rings no one. The slot's two fields are put back as they were when it leaves. It
must not run while a client of that slot is active.

It always prints the wall-clock times of its first and last ring (time.time_ns), so a harness
can place the ring window against other events.

WHAT IT IS NOT. A functional probe, not a latency harness: no governor pinning,
no rounds, no warm-up. Whatever it prints, and the --json samples, are local
records (NC QDL v7 4.6(i)). It clears its id from ECHO_OFF when it leaves.
"""
import argparse
import json
import mmap
import os
import select
import socket
import struct
import sys
import time

ECHO_OFF = 65536     # its_probe.c ECHO_OFF: the host peer id, uint32 LE, in BAR2
OFF_REPLY_VIA, OFF_CLIENT_PEER, VIA_DOORBELL = 72, 76, 1   # ipc-test/common/shm_chan.h
OBSERVER_SETTLE_S = 0.5


def recv_msg(sock):
    """One server message: a little-endian int64, and the fd that came with it or None."""
    data, fds, _flags, _addr = socket.recv_fds(sock, 8, 1)
    if len(data) != 8:
        raise OSError("the ivshmem server closed the connection or sent %d bytes" % len(data))
    return struct.unpack("<q", data)[0], (fds[0] if fds else None)


def join(path, guest_peer, vector=0):
    """Join the server; return (sock, own_id, shm_fd, guest_fd, own_fd). guest_fd is the guest's
    eventfd for `vector` (2026-09-29: a device may have two)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    version, _ = recv_msg(sock)
    if version != 0:
        raise OSError("protocol version %d, expected 0" % version)
    own, _ = recv_msg(sock)
    minus1, shm_fd = recv_msg(sock)
    if minus1 != -1 or shm_fd is None:
        raise OSError("expected -1 with the shared memory's fd, got %d" % minus1)
    fds = {}
    while own not in fds:
        pid, fd = recv_msg(sock)
        if fd is None:
            fds.pop(pid, None)          # a peer left
            continue
        fds.setdefault(pid, []).append(fd)
    if own == guest_peer:
        sock.close()
        raise SystemExit("ring: this peer got id %d, the guest's -- joined before QEMU did; refusing to ring "
                         "itself (and every other peer would now take it for the guest)" % own)
    if guest_peer not in fds:
        raise OSError("peer %d (the guest's QEMU) is not connected to the server" % guest_peer)
    if vector >= len(fds[guest_peer]):
        raise OSError("peer %d has %d vector(s), not %d" % (guest_peer, len(fds[guest_peer]), vector + 1))
    return sock, own, shm_fd, fds[guest_peer][vector], fds[own][0]


def drain(fd):
    try:
        os.read(fd, 8)
    except BlockingIOError:
        pass


def pct(sorted_ns, p):
    if not sorted_ns:
        return float("nan")
    i = min(len(sorted_ns) - 1, int(round(p / 100.0 * (len(sorted_ns) - 1))))
    return sorted_ns[i] / 1000.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--socket", required=True, help="ivshmem_server.py's socket")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--gap-ms", type=float, default=100.0)
    ap.add_argument("--echo", action="store_true", help="wait for the guest's doorbell after each ring")
    ap.add_argument("--timeout-ms", type=float, default=1000.0)
    ap.add_argument("--guest-peer", type=int, default=1)
    ap.add_argument("--vector", type=int, default=0, help="the guest device's MSI-X vector to ring (2026-09-29)")
    ap.add_argument("--join-wait-s", type=float, default=0.0,
                    help="retry joining for this long while the server or the guest's QEMU is not there yet "
                         "(2026-09-29: to ring a guest that is still booting)")
    ap.add_argument("--slot", type=int, default=-1,
                    help="observe a notified monitor's slot at this offset: own peer id as its client, "
                         "count the doorbells that come back (2026-09-29)")
    ap.add_argument("--json", default="", help="write the echo round trips (ns) here")
    a = ap.parse_args()

    deadline = time.monotonic() + a.join_wait_s
    while True:
        try:
            sock, own, shm_fd, guest_fd, own_fd = join(a.socket, a.guest_peer, a.vector)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    shm = mmap.mmap(shm_fd, os.fstat(shm_fd).st_size)
    if len(shm) < ECHO_OFF + 4:
        sys.exit("the shared memory (%d B) has no room for the echo id at %d" % (len(shm), ECHO_OFF))
    print("ring: joined as peer %d; ringing peer %d vector %d, %d times, %.1f ms apart%s"
          % (own, a.guest_peer, a.vector, a.count, a.gap_ms, ", waiting for echoes" if a.echo else ""))
    if a.slot >= 0 and (a.echo or a.slot % 64 or a.slot + 4096 > len(shm)):
        sys.exit("--slot needs a 64-byte aligned slot inside the shared memory, and no --echo")
    struct.pack_into("<I", shm, ECHO_OFF, own if a.echo else 0)
    saved = None
    if a.slot >= 0:
        saved = struct.unpack_from("<II", shm, a.slot + OFF_REPLY_VIA)
        struct.pack_into("<II", shm, a.slot + OFF_REPLY_VIA, VIA_DOORBELL, own)
        # QEMU learns a new peer's eventfds from the server asynchronously, and drops a doorbell
        # to a peer it does not know yet: let it catch up before the first ring.
        time.sleep(OBSERVER_SETTLE_S)
    drain(own_fd)
    os.set_blocking(own_fd, False)
    poller = select.poll()
    poller.register(own_fd, select.POLLIN)
    rtts, timeouts, answered = [], 0, 0
    first = last = 0

    def count_answers():
        try:
            return struct.unpack("<Q", os.read(own_fd, 8))[0]
        except BlockingIOError:
            return 0

    try:
        for i in range(a.count):
            t0 = time.perf_counter_ns()
            os.write(guest_fd, struct.pack("<Q", 1))
            last = time.time_ns()
            if i == 0:
                first = last
            if a.echo:
                if poller.poll(a.timeout_ms):
                    t1 = time.perf_counter_ns()
                    drain(own_fd)
                    rtts.append(t1 - t0)
                else:
                    timeouts += 1
            elif a.slot >= 0:
                answered += count_answers()
            time.sleep(a.gap_ms / 1000.0)
        if a.slot >= 0:
            time.sleep(0.2)                  # a late answer to the last ring still counts
            answered += count_answers()
    finally:
        struct.pack_into("<I", shm, ECHO_OFF, 0)
        if saved is not None:
            struct.pack_into("<II", shm, a.slot + OFF_REPLY_VIA, *saved)
        shm.close()
        sock.close()
    print("ring: window %d %d (time_ns of the first and last ring)" % (first, last))
    if a.slot >= 0:
        print("ring: observer: %d doorbell(s) came back to this peer from slot %d" % (answered, a.slot))
    if a.echo:
        s = sorted(rtts)
        print("ring: %d rung, %d echoed, %d timed out (%.0f ms)" % (a.count, len(rtts), timeouts, a.timeout_ms))
        if s:
            print("ring: echo round trip us: p50 %.1f  p90 %.1f  max %.1f"
                  % (pct(s, 50), pct(s, 90), s[-1] / 1000.0))
        if a.json:
            with open(a.json, "w") as f:
                json.dump({"own_peer": own, "rung": a.count, "timeouts": timeouts, "rtt_ns": rtts}, f)
    else:
        print("ring: %d rung; read the guest's console for what arrived" % a.count)
    return 0 if (not a.echo or timeouts == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
