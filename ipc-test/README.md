# ipc-test — Phase 2 cross-VM IPC

This is the Phase 2 deliverable: a small client/server pair, one on
each VM, used to measure round-trip latency over the bridged
virtio-net path.

> **Status:** scaffold. Sources live under `qnx-server/` and
> `linux-client/`; both directories are placeholders until Phase 2.

---

## Plan

**Topology.** The QNX VM runs the server (TCP listen on
`192.168.100.10:5555`); the Linux VM runs the client (connects to
the server's address via the host bridge `br0`). Both VMs use
virtio-net; no vsock, no ivshmem in the baseline.

**Echo protocol.** The client sends a small framed message
containing a monotonic timestamp; the server echoes the payload back
unmodified. The client measures wall-clock RTT on receipt. Frame
format is fixed-width binary (8-byte sequence + 8-byte timestamp +
N-byte payload) to keep parsing overhead off the latency path.

**Iteration count and reporting.** 100 000 iterations per run,
warm-up the first 1 000 (discarded). Report:

- **P50** — median, sanity check that the link is alive
- **P99** — primary metric (the load-bearing tail)
- **Max** — worst-case outlier per run

**Time-base normalisation.** The two OSes do not share a clock, and
this matters for any cross-VM measurement:

- QNX side uses `ClockCycles()` for fine-grain timestamps (and
  `SYSPAGE_ENTRY(qtime)->cycles_per_sec` to convert to ns).
- Linux side uses `clock_gettime(CLOCK_MONOTONIC)`.

For the round-trip number itself the **client measures locally on
both ends of the RTT**, so cross-clock skew does not enter the
result. The normalisation is needed only when annotating server-side
processing time inside the trace.

---

## Honest framing

This is **not** a like-for-like benchmark vs. DRIVE OS shared-memory
IPC. The expected difference is orders of magnitude:

| Mechanism | Approximate P50 RTT |
|---|---|
| DRIVE OS shared memory + mailbox interrupt | < 10 µs |
| This proxy: virtio-net via host bridge | _TBD; expected hundreds of µs to low ms_ |

What the measurement *is* useful for:

- Establishing that the path is correctly wired and stable
- Showing that the client/server framing, time-base handling, and
  P99/tail methodology are sound
- Producing a number to compare against alternate paths (vsock,
  ivshmem) in a Phase 2.5 follow-up if curiosity warrants it

---

## Layout

```
ipc-test/
├── README.md           # this file
├── qnx-server/         # C99, qcc-built; QNX TCP listen
└── linux-client/       # C99, gcc-built; Linux TCP connect + RTT measurement
```

Each side will land as a single-translation-unit C file with a tiny
Makefile in Phase 2. Build instructions will live in their respective
sub-directories at that point.
