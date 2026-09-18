#!/usr/bin/env python3
"""probe_qnx.py <port> <n> — is the QNX guest actually serving, right now?

Sends n valid 64-byte frames to the echo server (forwarded from the KVM guest)
and checks each comes back byte-identical. Frame layout, from
ipc-test/common/frame.h: uint64 seq | uint64 tstamp_cycles | 48-byte payload,
little-endian. UINT64_MAX is the server's sentinel and is never sent here.

This exists so "QNX ran concurrently with the GPU load" rests on the guest
answering, not on a host process merely existing. It reports round-trip times,
but those are a liveness signal, not a latency measurement: one host, slirp
NAT, tiny sample.
"""
import socket
import struct
import sys
import time

FRAME_TOTAL = 64
PAYLOAD = 48


def frame(seq):
    return struct.pack("<QQ", seq, int(time.monotonic_ns())) + bytes(
        (seq + i) & 0xFF for i in range(PAYLOAD)
    )


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 17000
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    ok = 0
    bad = 0
    rtts = []
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
    except OSError as e:
        print("PROBE connect_failed err=%s" % e)
        return 2
    s.settimeout(10)

    for i in range(1, n + 1):
        sent = frame(i)
        t0 = time.monotonic()
        try:
            s.sendall(sent)
            got = b""
            while len(got) < FRAME_TOTAL:
                chunk = s.recv(FRAME_TOTAL - len(got))
                if not chunk:
                    break
                got += chunk
        except OSError as e:
            print("  frame=%d err=%s" % (i, e))
            bad += 1
            continue
        rtt = (time.monotonic() - t0) * 1000.0

        # The server echoes the frame; the seq must survive intact. The
        # timestamp field is the client's own, so compare seq + payload only.
        if len(got) == FRAME_TOTAL and got[:8] == sent[:8] and got[16:] == sent[16:]:
            ok += 1
            rtts.append(rtt)
            print("  frame=%d echo=byte-exact rtt_ms=%.2f" % (i, rtt))
        else:
            bad += 1
            print("  frame=%d echo=MISMATCH got=%d bytes" % (i, len(got)))

    s.close()
    mean = sum(rtts) / len(rtts) if rtts else 0.0
    print("PROBE ok=%d bad=%d mean_rtt_ms=%.2f" % (ok, bad, mean))
    return 0 if ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
