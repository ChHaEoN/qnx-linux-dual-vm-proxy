#!/usr/bin/env python3
"""latency_probe.py — round-trip latency of the QNX guest's safety monitor, as a
distribution rather than a liveness yes/no.

  usage: latency_probe.py --host H [--port 7100] [--proto tcp|udp] [--n 2000]
                          [--warmup 200] [--interval-ms 2] [--tag NAME] [--out FILE]
                          [--timeout-s 10] [--stall-out FILE] [--await-recovery S]
                          [--claim mnist|vlm] [--stamps]
         latency_probe.py --proto shm --shm FILE --shm-lib LIB [the same options]
         latency_probe.py --proto shmkick --shm FILE@OFF --kick SOCK --shm-lib LIB [...]
         latency_probe.py --proto shmdb --shm FILE@OFF --kick SOCK --ivshm SOCK --shm-lib LIB [...]
         latency_probe.py --proto kickecho --kick SOCK --shm-lib LIB [...]

THREE TRANSPORTS (OD12). --proto tcp (the default) holds one connection, as
below. --proto udp sends one frame per datagram on a connected socket and reads
one datagram back. --proto shm (2026-09-22) puts the frame in a shared-memory
slot (ipc-test/common/shm_chan.h) in FILE -- across the partition, the /dev/shm
file QEMU backs the guest's ivshmem device with -- and spins for the reply.
The slot is written and read by libshmchan.so (shmchan.c, built by the run),
because its ordering needs store-release/load-acquire, which Python lacks; the
timing stays here, around that call, as it is around send/recv for the others.
The rest of this description applies to all three, except that UDP and shm
have no connection to hold.

NOTIFIED SHARED MEMORY (OD12, 2026-09-22): the same slot, and nobody spins.
--proto shmkick sends one kick byte down --kick (a UNIX socket: a host-side
monitor's, or QEMU's virtio console) and sleeps until a kick byte comes back.
--proto shmdb sends the same kick but sleeps on its own eventfd, which the far
end rings -- in the guest, by a write to the ivshmem Doorbell register that KVM
turns into a write to that eventfd. It joins the ivshmem server --ivshm first,
keeps that connection for the whole arm, and does an untimed handshake before
the warm-up until one doorbell has actually arrived: QEMU learns a new peer
asynchronously and drops a doorbell to one it does not know yet. --proto
kickecho is the bare notification round trip: one byte out, the same byte back,
no slot. Each arm's summary counts what woke the probe, and a reply that was in
the slot with no notification is its own failure ("notification lost", exit 5),
never a stall.

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
P_T_IN, P_T_OUT = 8, 16      # OD15: a stamping monitor's t_in/t_out, uint64 LE ns


def build_frame(seq):
    """A claim the monitor will ACCEPT: class 3, confidence 95, 124 us."""
    hdr = struct.pack("<QQ", seq, 0)
    pay = bytearray(PAYLOAD)
    pay[P_CLASS] = 3
    pay[P_CONF] = 95
    pay[P_INFER_US:P_INFER_US + 4] = struct.pack("<I", 124)
    return hdr + bytes(pay)


# OD13 (2026-09-23): a pre-built kind-1 (vlm) claim, so the verdict round trip
# of a VLM claim can be paired against the mnist claim's with nothing else
# changed. Its values are one honest SmolVLM-500M answer as the 2026-09-23
# characterisation measured it (digit 3, P = 0.9998, 269.484 + 12.548 ms), so
# the monitor ACCEPTs it -- a run whose frames were rejected could not pass the
# completeness gate, and choosing only images that pass would be selection
# bias; a fixed frame needs no choosing. Layout: monitor.c's header.
P_KIND = 24
VLM_PROMPT_US, VLM_GEN_US = 269484, 12548


def build_vlm_frame(seq):
    """A kind-1 claim the monitor will ACCEPT: digit 3, 100%, 282032 us in two parts."""
    hdr = struct.pack("<QQ", seq, 0)
    pay = bytearray(PAYLOAD)
    pay[P_CLASS] = 3
    pay[P_CONF] = 100
    pay[P_INFER_US:P_INFER_US + 4] = struct.pack("<I", VLM_PROMPT_US + VLM_GEN_US)
    pay[P_KIND] = 1                                   # kind: vlm
    pay[P_KIND + 1] = 1                               # model 1: SmolVLM-500M-Instruct Q8_0
    struct.pack_into("<HHIIII", pay, P_KIND + 2, 162, 2, VLM_PROMPT_US, VLM_GEN_US, 309900, 999999)
    return hdr + bytes(pay)


BUILDERS = {"mnist": build_frame, "vlm": build_vlm_frame}


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
        rec = {"stall": {"tag": a.tag, "proto": a.proto, "kind": kind, "at_sample": at, "of": a.warmup + a.n,
                         "warmup": a.warmup, "timeout_s": a.timeout_s, "why": why,
                         "bad": bad, "rejected_by_monitor": rejected, "claim": a.claim, "stamps": a.stamps,
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
            frame = build_frame(1)
            if a.proto in NOTIFIED:
                # Each attempt joins and LEAVES: an attempt that kept its ivshmem
                # peer would leave a phantom peer at QEMU and the monitor.
                kc = KickChannel(a.shm_lib, a.proto, a.shm, a.kick, a.ivshm)
                try:
                    if not kc.ready():
                        raise OSError("no notified server")
                    kc.handshake(within_s=1.0)
                    rc = kc.roundtrip(frame, 1.0)
                    if rc != KickChannel.OK:
                        raise OSError("%s roundtrip rc=%d" % (a.proto, rc))
                    got = frame if a.proto == "kickecho" else kc.rsp.raw
                finally:
                    kc.close()
            elif a.proto == "shm":
                chan = ShmChannel(a.shm_lib, a.shm)
                rc = chan.roundtrip(frame, 1.0)
                if rc != ShmChannel.OK:
                    raise OSError("shm roundtrip rc=%d" % rc)
                got = chan.rsp.raw
            elif a.proto == "udp":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect((a.host, a.port))
                    s.settimeout(1.0)
                    s.send(frame)
                    got = s.recv(2048)
            else:
                with socket.create_connection((a.host, a.port), timeout=1.0) as s:
                    if s.getsockname() == s.getpeername():
                        # A loopback connect can land on its own source port and
                        # echo itself -- seen in the unit tests, never a guest.
                        raise OSError("connected to itself")
                    s.settimeout(1.0)
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


class ShmChannel:
    """The probe's end of a shm_chan.h slot, through libshmchan.so."""
    OK, TIMEOUT, NOTREADY = 0, 1, 2

    def __init__(self, lib_path, spec):
        import ctypes
        self._c = ctypes
        lib = ctypes.CDLL(lib_path)
        lib.shm_map.restype = ctypes.c_void_p
        lib.shm_map.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
                                ctypes.c_char_p, ctypes.c_size_t]
        lib.shmchan_ready.restype = ctypes.c_int
        lib.shmchan_ready.argtypes = [ctypes.c_void_p]
        lib.shmchan_roundtrip.restype = ctypes.c_int
        lib.shmchan_roundtrip.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                          ctypes.POINTER(ctypes.c_char), ctypes.c_uint64]
        size = ctypes.c_size_t(0)
        what = ctypes.create_string_buffer(192)
        base = lib.shm_map(spec.encode(), ctypes.byref(size), what, len(what))
        if not base:
            raise OSError("shm_map(%s) failed -- see stderr" % spec)
        self.lib, self.base, self.what = lib, base, what.value.decode()
        self.rsp = ctypes.create_string_buffer(FRAME_TOTAL)

    def ready(self):
        return bool(self.lib.shmchan_ready(self.base))

    def roundtrip(self, frame, timeout_s):
        """Returns OK, TIMEOUT or NOTREADY; the reply is then in self.rsp.raw."""
        return self.lib.shmchan_roundtrip(self.base, frame, self.rsp, int(timeout_s * 1e9))


NOTIFIED = ("shmkick", "shmdb", "kickecho")
SHM_VIA_KICK, SHM_VIA_DOORBELL, SHM_VIA_BURST = 0, 1, 3


class KickChannel:
    """The probe's end of the notified variant (shm_chan.h), through libshmchan.so."""
    OK, TIMEOUT, NOTREADY, BROKEN, LOST = 0, 1, 2, 3, 4
    COUNT_NAMES = ("exchanges", "wakeups", "early_wakeups", "notifications", "stray", "eagain")

    def __init__(self, lib_path, proto, slot_spec, kick_path, ivshm_path):
        import ctypes
        c = ctypes
        lib = c.CDLL(lib_path)
        lib.shm_map.restype = c.c_void_p
        lib.shm_map.argtypes = [c.c_char_p, c.POINTER(c.c_size_t), c.c_char_p, c.c_size_t]
        lib.shmchan_kick_ready.restype = c.c_int
        lib.shmchan_kick_ready.argtypes = [c.c_void_p]
        lib.shmchan_kick_roundtrip.restype = c.c_int
        lib.shmchan_kick_roundtrip.argtypes = [c.c_void_p, c.c_char_p, c.POINTER(c.c_char), c.c_uint64,
                                               c.c_int, c.c_int, c.c_uint32, c.c_uint32, c.c_uint32]
        lib.shmchan_echo_roundtrip.restype = c.c_int
        lib.shmchan_echo_roundtrip.argtypes = [c.c_int, c.c_uint64]
        lib.shmchan_burst_total.restype = c.c_uint64
        lib.shmchan_burst_total.argtypes = [c.c_int, c.c_uint64, c.c_uint64]
        lib.shmchan_counts.restype = None
        lib.shmchan_counts.argtypes = [c.POINTER(c.c_uint64)]
        lib.shmchan_fd_flags.restype = c.c_int
        lib.shmchan_fd_flags.argtypes = [c.c_int]
        lib.shmchan_ivshm_connect.restype = c.c_void_p
        lib.shmchan_ivshm_connect.argtypes = [c.c_char_p]
        lib.shmchan_ivshm_id.restype = c.c_longlong
        lib.shmchan_ivshm_id.argtypes = [c.c_void_p]
        lib.shmchan_ivshm_efd.restype = c.c_int
        lib.shmchan_ivshm_efd.argtypes = [c.c_void_p]
        lib.shmchan_ivshm_close.restype = None
        lib.shmchan_ivshm_close.argtypes = [c.c_void_p]
        lib.shmchan_drain_quiet.restype = None
        lib.shmchan_drain_quiet.argtypes = [c.c_int, c.c_int]
        lib.shmchan_slot_answered.restype = c.c_int
        lib.shmchan_slot_answered.argtypes = [c.c_void_p]
        self._c, self.lib, self.proto = c, lib, proto
        self.via = SHM_VIA_DOORBELL if proto == "shmdb" else SHM_VIA_KICK
        self.peer, self.efd, self.ivshm, self.slot, self.what = 0, -1, None, None, ""
        self.rsp = c.create_string_buffer(FRAME_TOTAL)
        # The ivshmem server FIRST, then the kick socket: the server tells the
        # far end about this peer before it hands this peer its eventfd, so by
        # the time the first kick lands the far end can already ring it.
        if proto == "shmdb":
            self.ivshm = lib.shmchan_ivshm_connect(ivshm_path.encode())
            if not self.ivshm:
                raise OSError("could not join the ivshmem server %s -- see stderr" % ivshm_path)
            self.peer = lib.shmchan_ivshm_id(self.ivshm)
            self.efd = lib.shmchan_ivshm_efd(self.ivshm)
        if proto != "kickecho":
            path, _, off = slot_spec.rpartition("@")
            if not path:
                path, off = slot_spec, "0"
            if not off.isdigit():
                # a sign would put the slot outside the mapping (FOUND BY CODE REVIEW)
                raise OSError("slot offset %r is not a plain non-negative number" % off)
            size = c.c_size_t(0)
            what = c.create_string_buffer(320)
            base = lib.shm_map(path.encode(), c.byref(size), what, len(what))
            if not base:
                raise OSError("shm_map(%s) failed -- see stderr" % path)
            off = int(off, 0)
            if off % 64 or off + 4096 > size.value:
                raise OSError("slot @%d does not fit %s (%d bytes)" % (off, path, size.value))
            self.slot = base + off
            self.what = "%s, slot @%d" % (what.value.decode(), off)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(kick_path)
        self.kick_fd = self.sock.fileno()
        self.wait_fd = self.efd if proto == "shmdb" else self.kick_fd
        self.flags_start = lib.shmchan_fd_flags(self.wait_fd)

    def ready(self):
        return self.proto == "kickecho" or bool(self.lib.shmchan_kick_ready(self.slot))

    def roundtrip(self, frame, timeout_s, via=None, count=0):
        ns = int(timeout_s * 1e9)
        if self.proto == "kickecho":
            return self.lib.shmchan_echo_roundtrip(self.kick_fd, ns)
        return self.lib.shmchan_kick_roundtrip(self.slot, frame, self.rsp, ns, self.kick_fd, self.efd,
                                               self.via if via is None else via, self.peer, count)

    def handshake(self, within_s=5.0):
        """shmdb only: exchanges until one doorbell has arrived, untimed. Returns
        the number of attempts; raises OSError if none arrives in time.

        A LOST attempt (reply in the slot, doorbell dropped: QEMU had not yet
        registered this peer) is simply retried. A TIMEOUT (no reply yet) is
        waited out before the next attempt, so a slot never has two requests in
        it; and whatever that late reply's doorbell leaves on the eventfd is
        discarded, uncounted, before the arm's first timed exchange."""
        if self.proto != "shmdb":
            return 0
        t0 = time.monotonic()
        attempts = 0
        while time.monotonic() - t0 < within_s:
            attempts += 1
            rc = self.roundtrip(build_frame(1), 0.2)
            if rc == self.OK:
                self.lib.shmchan_drain_quiet(self.efd, 1)
                return attempts
            if rc == self.TIMEOUT:
                while not self.lib.shmchan_slot_answered(self.slot) and time.monotonic() - t0 < within_s:
                    time.sleep(0.01)
                self.lib.shmchan_drain_quiet(self.efd, 1)
            elif rc != self.LOST:
                raise OSError("handshake failed (rc=%d)" % rc)
        raise OSError("no doorbell arrived in %.0f s (%d attempts)" % (within_s, attempts))

    def burst(self, n, timeout_s):
        """One SHM_VIA_BURST exchange: the far end rings n doorbells. Returns
        (rc, doorbells counted)."""
        before = self.counts()["notifications"]
        rc = self.roundtrip(build_frame(1), timeout_s, via=SHM_VIA_BURST, count=n)
        got = self.counts()["notifications"] - before
        if rc == self.OK and got < n:
            got += self.lib.shmchan_burst_total(self.efd, n - got, int(timeout_s * 1e9))
        return rc, got

    def counts(self):
        arr = (self._c.c_uint64 * 6)()
        self.lib.shmchan_counts(arr)
        return dict(zip(self.COUNT_NAMES, (int(v) for v in arr)))

    def nonblocking(self):
        return bool(self.lib.shmchan_fd_flags(self.wait_fd) & os.O_NONBLOCK)

    def close(self):
        """Leave everything this channel joined: the kick stream and the ivshmem
        server (which then tells QEMU or the monitor that this peer is gone)."""
        self.sock.close()
        if self.ivshm:
            self.lib.shmchan_ivshm_close(self.ivshm)
            self.ivshm = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="")
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
    ap.add_argument("--proto", choices=("tcp", "udp", "shm") + NOTIFIED, default="tcp",
                    help="transport; udp sends one frame per datagram on a connected socket, "
                         "shm uses a shared-memory slot in --shm; shmkick, shmdb and kickecho "
                         "are its notified variants")
    ap.add_argument("--kick", default="", help="notified variants: the kick socket")
    ap.add_argument("--ivshm", default="", help="with --proto shmdb: the ivshmem server socket")
    ap.add_argument("--db-burst", type=int, default=0,
                    help="with --proto shmdb, instead of sampling: one exchange whose reply is N "
                         "doorbells, and a count of how many arrived")
    ap.add_argument("--shm", default="", help="with --proto shm: the shared-memory file")
    ap.add_argument("--shm-lib", default="", help="with --proto shm: libshmchan.so, built from shmchan.c")
    ap.add_argument("--claim", choices=sorted(BUILDERS), default="mnist",
                    help="which claim each timed frame carries: the mnist claim every A6 run has "
                         "used (the default, unchanged), or OD13's pre-built vlm claim")
    ap.add_argument("--await-recovery", type=float, default=0.0,
                    help="instead of sampling: seconds to wait for the guest to answer again")
    ap.add_argument("--stamps", action="store_true",
                    help="OD15: the monitor stamps t_in/t_out into payload[8..23] (`monitor PORT "
                         "stamp`); record its own time per sample, and refuse an unstamped reply. "
                         "Without it, a stamped reply is refused: the arm reached the wrong instance")
    a = ap.parse_args()
    if a.proto == "shm":
        if not (a.shm and a.shm_lib):
            ap.error("--proto shm needs --shm and --shm-lib")
    elif a.proto in NOTIFIED:
        if not (a.kick and a.shm_lib) or (a.proto != "kickecho" and not a.shm):
            ap.error("--proto %s needs --kick, --shm-lib and (but for kickecho) --shm" % a.proto)
        if a.proto == "shmdb" and not a.ivshm:
            ap.error("--proto shmdb needs --ivshm")
    elif not a.host:
        ap.error("--host is required for --proto %s" % a.proto)

    if a.db_burst and a.proto != "shmdb":
        ap.error("--db-burst needs --proto shmdb")

    if a.await_recovery > 0:
        return await_recovery(a)

    # UDP (owner decision OD12, 2026-09-21): the same frame, one per datagram,
    # on a CONNECTED socket -- connect() fixes the peer, so a datagram from
    # anywhere else is never read as a reply, and an ICMP port-unreachable comes
    # back as an error instead of a silent timeout. Losses get the TCP rule for
    # the first run (an implementation choice of 2026-09-22, recorded under OD12
    # in the plan): no reply within --timeout-s is recorded as a stall, and on
    # UDP a lost datagram and a stalled guest cannot be told apart from here --
    # the stall record says which transport it was. A reply of the wrong size, a
    # wrong sequence number (a late or duplicate reply) or an ICMP error is a
    # broken stream, exit 5, exactly as on TCP.
    udp = a.proto == "udp"
    shm = a.proto == "shm"
    notified = a.proto in NOTIFIED
    chan = None
    kc = None
    handshake = 0
    counts0 = None
    if notified:
        # Nothing to connect to is "could not connect", exit 2, as for TCP.
        try:
            kc = KickChannel(a.shm_lib, a.proto, a.shm, a.kick, a.ivshm)
        except OSError as e:
            print("FATAL %s: %s" % (a.proto, e))
            return 2
        if not kc.ready():
            print("FATAL %s: no notified server is serving %s (%s)" % (a.proto, a.shm, kc.what))
            return 2
        try:
            handshake = kc.handshake()
        except OSError as e:
            return _broken(a, "doorbell handshake: %s" % e, 0, 1, 0)
        if a.db_burst:
            rc, got = kc.burst(a.db_burst, a.timeout_s)
            rec = {"burst": {"tag": a.tag, "want": a.db_burst, "got": got, "rc": rc,
                             "peer": kc.peer, "handshake_attempts": handshake}}
            print("BURST %s" % json.dumps(rec["burst"]))
            if a.out:
                with open(a.out, "w") as f:
                    json.dump(rec, f)
            return 0 if (rc == KickChannel.OK and got == a.db_burst) else 6
        counts0 = kc.counts()
        s = None
    elif shm:
        # No server (magic not published) is "could not connect", exit 2, as a
        # refused TCP connect is: nothing was sampled, and nothing stalled.
        try:
            chan = ShmChannel(a.shm_lib, a.shm)
        except OSError as e:
            print("FATAL shm: %s" % e)
            return 2
        if not chan.ready():
            print("FATAL shm: no server is serving %s (%s)" % (a.shm, chan.what))
            return 2
        s = None
    elif udp:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((a.host, a.port))
        except OSError as e:
            print("FATAL connect: %s" % e)
            return 2
        s.settimeout(a.timeout_s)
    else:
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
    servers = []        # --stamps: the monitor's own time per timed sample, us, arrival order
    sends = []          # perf_counter() at each timed frame's send, for the achieved period
    bad = 0
    rejected = 0
    seq = 0
    total = a.warmup + a.n
    gap = a.interval_ms / 1000.0

    for i in range(total):
        seq += 1
        if seq >= (1 << 63):          # never reach the sentinel
            seq = 1
        frame = BUILDERS[a.claim](seq)
        if notified:
            t0 = time.perf_counter()
            rc = kc.roundtrip(frame, a.timeout_s)
            t1 = time.perf_counter()
            if rc == KickChannel.TIMEOUT:
                return _abort(a, "sample %d: no reply within %.1f s" % (i, a.timeout_s),
                              i, bad + 1, rejected, "timeout", in_arrival)
            if rc == KickChannel.LOST:
                return _broken(a, "sample %d: notification lost -- the reply was in the slot and "
                               "nothing said so within %.1f s" % (i, a.timeout_s), i, bad + 1, rejected)
            if rc != KickChannel.OK:
                return _broken(a, "sample %d: the kick channel broke (rc=%d)" % (i, rc),
                               i, bad + 1, rejected)
            got = frame if a.proto == "kickecho" else kc.rsp.raw
        elif shm:
            t0 = time.perf_counter()
            rc = chan.roundtrip(frame, a.timeout_s)
            t1 = time.perf_counter()
            if rc == ShmChannel.TIMEOUT:
                # The late reply may still land; the slot cannot be reused
                # until it does, so -- as on TCP -- the arm aborts.
                return _abort(a, "sample %d: no reply within %.1f s" % (i, a.timeout_s),
                              i, bad + 1, rejected, "timeout", in_arrival)
            if rc != ShmChannel.OK:
                return _broken(a, "sample %d: the server stopped serving (rc=%d)" % (i, rc),
                               i, bad + 1, rejected)
            got = chan.rsp.raw
        else:
            t0 = time.perf_counter()
            try:
                if udp:
                    if s.send(frame) != FRAME_TOTAL:
                        return _broken(a, "sample %d: short datagram sent" % i, i, bad + 1, rejected)
                    got = s.recv(2048)
                else:
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
        if a.proto != "kickecho" and got[FRAME_HEADER + P_VERDICT] != 0:
            rejected += 1          # monitor disagreed: a fault, not a timing sample
            continue
        # OD15: a stamping monitor writes t_in/t_out into payload[8..23]; every
        # other one echoes the zeros this probe sends there. Either way round, a
        # mismatch means the arm reached the wrong instance.
        t_in, t_out = struct.unpack_from("<QQ", got, FRAME_HEADER + P_T_IN)
        if a.stamps and (t_in == 0 or t_out < t_in):
            return _broken(a, "sample %d: the reply is not stamped (t_in=%d t_out=%d) -- not a "
                           "`monitor PORT stamp` instance" % (i, t_in, t_out), i, bad + 1, rejected)
        if not a.stamps and (t_in or t_out):
            return _broken(a, "sample %d: the reply is stamped, and --stamps was not given -- a "
                           "stamping instance" % i, i, bad + 1, rejected)
        if i >= a.warmup:
            rtts.append((t1 - t0) * 1000.0)
            sends.append(t0)
            in_arrival.append(rtts[-1])
            if a.stamps:
                servers.append((t_out - t_in) / 1000.0)
        if gap > 0:
            time.sleep(gap)

    if s is not None:
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
        "proto": a.proto,
        "claim": a.claim,
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
    # ADDED 2026-09-24 (the offered-rate sweep): the period this arm actually
    # achieved, from the probe's own clock at each timed send -- the round trip
    # plus the sleep plus the loop's own work, which a bracket around the whole
    # process (start-up, connect, the file write) cannot give. The median of the
    # gaps, so one scheduling hiccup does not move it.
    res["interval_ms"] = a.interval_ms
    if len(sends) > 1:
        gaps = sorted((b - a_) * 1e6 for a_, b in zip(sends, sends[1:]))
        res["period_us"] = {"p50": percentile(gaps, 50), "mean": sum(gaps) / len(gaps)}
    res["stamps"] = a.stamps
    if a.stamps:
        # The split, per sample: the monitor's own time (its clock) and the rest
        # of the round trip (the probe's RTT less it). No clock is synchronised:
        # each interval is taken on one clock only.
        other = [r * 1000.0 - s for r, s in zip(in_order, servers)]
        for key, vals in (("server_us", sorted(servers)), ("other_us", sorted(other))):
            res[key] = {"min": vals[0], "p50": percentile(vals, 50), "p90": percentile(vals, 90),
                        "p99": percentile(vals, 99), "p999": percentile(vals, 99.9), "max": vals[-1]}
    if shm:
        res["shm_region"] = chan.what
    if notified:
        counts1 = kc.counts()
        res["shm_region"] = kc.what
        res["notify"] = {k: counts1[k] - counts0[k] for k in KickChannel.COUNT_NAMES}
        res["wait_fd_nonblock"] = [bool(kc.flags_start & os.O_NONBLOCK), kc.nonblocking()]
        res["ivshm_peer"] = kc.peer
        res["handshake_attempts"] = handshake
    res.update(own_scheduling())
    print("RESULT %s" % json.dumps(res))
    print("  tag=%-12s n=%-5d min=%.3f p50=%.3f p90=%.3f p99=%.3f p99.9=%.3f max=%.3f  bad=%d rej=%d"
          % (res["tag"], res["n"], res["min_ms"], res["p50_ms"], res["p90_ms"],
             res["p99_ms"], res["p999_ms"], res["max_ms"], bad, rejected))

    if a.stamps:
        print("  monitor's own time p50=%.2f us p99=%.2f us; the rest p50=%.2f us p99=%.2f us"
              % (res["server_us"]["p50"], res["server_us"]["p99"], res["other_us"]["p50"], res["other_us"]["p99"]))
    if a.out:
        body = {"summary": res, "samples_ms": rtts, "samples_in_order": in_order}
        if a.stamps:
            body["server_us_in_order"] = servers
        with open(a.out, "w") as f:
            json.dump(body, f)
        print("  wrote %s (%d samples)" % (a.out, len(rtts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
