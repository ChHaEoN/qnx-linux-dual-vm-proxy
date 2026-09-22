#!/usr/bin/env python3
"""ivshmem_server.py -- this project's own ivshmem server (A6, OD12, 2026-09-22).

  usage: ivshmem_server.py --socket PATH --shm FILE [--vectors 1] [--ready FILE]
                           [--exit-with-peer ID]

WHAT IT IS FOR. QEMU's `ivshmem-doorbell` device does not open its shared memory
itself: it connects to a server over a UNIX socket, and the server hands it the
memory's file descriptor, a peer id, and one eventfd per interrupt vector for
itself and for every other peer. Any other process that speaks the same
protocol -- the latency probe, a host-side monitor -- becomes a peer the same
way. The guest can then ring a peer by writing (peer id << 16 | vector) to the
device's Doorbell register; with ioeventfd on (QEMU's default), KVM signals
that peer's eventfd without leaving the kernel.

THE PROTOCOL is QEMU 6.2's, as its own reference server
(contrib/ivshmem-server/ivshmem-server.c) and its device
(hw/misc/ivshmem.c, ivshmem_recv_setup / process_msg) implement it. Every
message is one little-endian signed 64-bit integer, optionally carrying one
file descriptor by SCM_RIGHTS. To a new peer, in this order:
  1. the protocol version, 0, no fd;
  2. the peer's own id, no fd;
  3. -1 with the shared memory's fd.
Then, as the reference server does: the new peer's (id, eventfd) for each of
its vectors to every EXISTING peer; every existing peer's (id, eventfd) per
vector to the new peer; and the new peer's own (id, eventfd) per vector to
itself. When a peer goes away, every remaining peer gets (its id) with no fd.

IDS ONLY GO UP, from 1, and are never handed out twice (FOUND BY DESIGN REVIEW,
2026-09-22). QEMU 6.2's device frees a departed peer's eventfd array in
close_peer_eventfds() without clearing the pointer, and on a later connect with
the same id writes into it and registers it as a KVM ioeventfd -- a
use-after-free, then a double free at the next disconnect. The reference server
avoids it only because its counter moves on; a server that reused the lowest
free id would hit it on the second probe of a run. Starting at 1 means QEMU,
the first peer, never has id 0, so a guest that reads 0 from IVPosition knows
its view of the device's registers is wrong. The Doorbell register holds 16
bits, so the counter stops at 65535 and later peers are refused.

EVENTFDS ARE NON-BLOCKING (EFD_NONBLOCK | EFD_CLOEXEC), as the reference's
event_notifier_init() makes them. QEMU sets O_NONBLOCK on every peer eventfd it
receives, and that flag lives on the open file the peers share; creating them
non-blocking here means a peer sees the same flags whether QEMU is present or
not. Peers must still wait only in poll().

READINESS. With --ready, the file is created only after the socket listens, so a
launcher can wait for it before starting QEMU, whose client-mode chardev
connects at once and fails on a socket that is not there yet. With
--exit-with-peer ID, the server exits when that peer (QEMU, id 1) goes away.

WHAT IT IS NOT. Not QEMU's server, and not on any timed path: after a peer's
setup it only waits for connections and hang-ups. The eventfds it creates are
kernel objects that QEMU, KVM and the peers use directly.
"""
import argparse
import os
import select
import signal
import socket
import stat
import struct
import sys

PROTOCOL_VERSION = 0
FIRST_ID = 1
LAST_ID = 65535


def send_msg(sock, value, fd=None):
    data = struct.pack("<q", value)
    if fd is None:
        sock.sendall(data)
    else:
        socket.send_fds(sock, [data], [fd])


class Peer(object):
    def __init__(self, pid, sock, vectors):
        self.id = pid
        self.sock = sock
        self.efds = [os.eventfd(0, os.EFD_NONBLOCK | os.EFD_CLOEXEC) for _ in range(vectors)]

    def close(self):
        for fd in self.efds:
            os.close(fd)
        self.sock.close()


class Server(object):
    def __init__(self, path, shm_fd, vectors, log, exit_with=None):
        self.path = path
        self.shm_fd = shm_fd
        self.vectors = vectors
        self.log = log
        self.exit_with = exit_with
        self.owner_gone = False
        self.peers = {}          # socket fileno -> Peer
        self.next_id = FIRST_ID
        self.lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.lsock.bind(path)
        self.lsock.listen(8)

    def _next_id(self):
        """The next id, never one handed out before (see the header)."""
        if self.next_id > LAST_ID:
            return None
        pid = self.next_id
        self.next_id += 1
        return pid

    def _send_or_drop(self, other, value, fd=None):
        """A send to one peer that fails drops that peer only."""
        try:
            send_msg(other.sock, value, fd)
            return True
        except OSError as e:
            self.log("peer %d unreachable (%s); dropping it" % (other.id, e))
            self.drop(other.sock.fileno())
            return False

    def accept(self):
        sock, _ = self.lsock.accept()
        pid = self._next_id()
        if pid is None:
            self.log("refused a peer: no free id")
            sock.close()
            return
        peer = Peer(pid, sock, self.vectors)
        told = []
        try:
            send_msg(sock, PROTOCOL_VERSION)
            send_msg(sock, pid)
            send_msg(sock, -1, self.shm_fd)
            # Existing peers learn the newcomer BEFORE the newcomer gets its own
            # eventfd. A peer that answers the newcomer relies on this order: by
            # the time the newcomer can ask anything, its eventfd is already
            # queued at every existing peer.
            for other in list(self.peers.values()):
                for fd in peer.efds:
                    if not self._send_or_drop(other, peer.id, fd):
                        break
                else:
                    told.append(other)
            for other in self.peers.values():
                for fd in other.efds:
                    send_msg(sock, other.id, fd)
            for fd in peer.efds:
                send_msg(sock, peer.id, fd)
        except OSError as e:
            # Peers already told about this newcomer must hear that it is gone,
            # or QEMU and the monitor keep its eventfd for the rest of the run.
            self.log("peer %d setup failed: %s" % (pid, e))
            for other in told:
                if other.sock.fileno() in self.peers:
                    try:
                        send_msg(other.sock, pid)
                    except OSError:
                        pass
            peer.close()
            return
        self.peers[sock.fileno()] = peer
        self.log("peer %d connected (%d peers)" % (pid, len(self.peers)))

    def drop(self, fileno):
        peer = self.peers.pop(fileno, None)
        if peer is None:
            return
        for other in list(self.peers.values()):
            try:
                send_msg(other.sock, peer.id)
            except OSError:
                pass          # that peer is going too; its own hang-up drops it
        peer.close()
        self.log("peer %d disconnected (%d peers)" % (peer.id, len(self.peers)))
        if self.exit_with is not None and peer.id == self.exit_with:
            self.owner_gone = True

    def serve(self):
        # No timeout: the server wakes only for a connection or a hang-up, so it
        # adds nothing periodic to the core it is pinned to. SIGTERM ends it by
        # raising out of select().
        while not self.owner_gone:
            socks = [self.lsock] + [p.sock for p in self.peers.values()]
            ready, _, _ = select.select(socks, [], [])
            for s in ready:
                if s is self.lsock:
                    self.accept()
                    continue
                try:
                    data = s.recv(64)
                except OSError:
                    data = b""
                if not data:          # a peer never sends anything; EOF is a hang-up
                    self.drop(s.fileno())

    def close(self):
        for fileno in list(self.peers):
            self.peers.pop(fileno).close()
        self.lsock.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", required=True)
    ap.add_argument("--shm", required=True, help="an existing file, its size a power of two")
    ap.add_argument("--vectors", type=int, default=1)
    ap.add_argument("--ready", default="", help="create this file once the socket listens")
    ap.add_argument("--exit-with-peer", type=int, default=None,
                    help="exit when the peer with this id disconnects (QEMU is id 1)")
    a = ap.parse_args()

    if not 1 <= a.vectors <= 64:
        ap.error("--vectors must be 1..64")
    if os.path.exists(a.socket):
        # A leftover socket may belong to a live server; never take it over.
        print("FATAL %s exists -- another server, or a leftover; remove it first" % a.socket)
        return 2
    try:
        shm_fd = os.open(a.shm, os.O_RDWR | os.O_CLOEXEC)
    except OSError as e:
        print("FATAL shm %s: %s" % (a.shm, e))
        return 2
    st = os.fstat(shm_fd)
    size = st.st_size
    if not stat.S_ISREG(st.st_mode) or size < 4096 or size & (size - 1):
        # QEMU maps it as a PCI BAR, which must be a power of two.
        print("FATAL shm %s is %d bytes; it must be a regular file of a power of two >= 4096" % (a.shm, size))
        return 2

    def log(msg):
        print("ivshmem-server: %s" % msg)
        sys.stdout.flush()

    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    srv = Server(a.socket, shm_fd, a.vectors, log, a.exit_with_peer)
    log("serving %s, %d bytes, %d vector(s), on %s (pid %d)" % (a.shm, size, a.vectors, a.socket, os.getpid()))
    if a.ready:
        with open(a.ready, "w") as f:
            f.write("%d\n" % os.getpid())
    try:
        srv.serve()
    finally:
        srv.close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
