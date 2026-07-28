# ipc-test — Phase 2 cross-partition IPC

This is the Phase 2 deliverable: a small client/server pair used to
measure round-trip latency across the QHV partition boundary on the
cloud leg.

The cloud-leg topology here is set by **ADR-002**
([../docs/phase2-topology-decision.md](../docs/phase2-topology-decision.md),
Status: Accepted). It supersedes the original "QNX TCP server + Linux
TCP client over `br0`/virtio-net" plan, which Phase 1 falsified: there
is no `/dev/kvm` on cloud Graviton and no Linux guest on the cloud leg,
and the host `io-sock` stack is down — so every `br0`/tap/host-TCP
transport is presumed broken there.

> **Status (2026-07-28):** the qvm/TCG console-wiring runtime spike is
> **resolved and running end to end** — `qnx-server/server.c` (guest,
> `/dev/vcon2`) and `qnx-host-client/client.c` (host, `/dev/ttyp0`) exchange
> real framed echoes across the `qvm` `virtio-console` vdev on the as-built
> QHV/TCG boundary, producing this repo's first real measured numbers
> (P50/P99/Max below). Getting a byte-exact round trip took two more fixes
> beyond the `hostdev` wiring itself (a tty canonical-mode deadlock, a
> one-time startup byte-injection artifact); a third finding — a
> non-deterministic TCG/virtio-queue stall after a small, boot-dependent
> number of back-to-back iterations — is only partially mitigated, **not
> resolved**, and bounds the sample count that reliably completes to a
> small one (15). See `qnx-host-client/README.md` for the full chain of
> findings and `../docs/findings.md` (2026-07-28 entry) for the honest
> account. `linux-client/` stays a Phase-3 placeholder.

---

## Plan

**Topology (cloud leg).** Both IPC ends are QNX. The QNX *host*
(`qnx-qhv`, the `qvm` QHV host) runs the initiator (`qnx-host-client/`);
the QNX *guest* (`qnx-guest`) runs the echo endpoint (`qnx-server/`).
They exchange the framed echo over the **`qvm` `virtio-console` vdev**
that is already declared in the live `g2.conf` — the same channel the
guest banner already prints over. This crosses the **real `qvm` EL2/EL1
partition boundary**; it does **not** route through host `io-sock`, a
Linux bridge, or tap devices (all of which are dead on this leg).

```
┌─────────────────────────────────┐        ┌──────────────────────────────┐
│ qnx-qhv  (QHV host, EL2)        │        │ qnx-guest  (EL1 guest)       │
│ ┌─────────────────────────────┐ │        │ ┌──────────────────────────┐ │
│ │ qnx-host-client             │ │        │ │ qnx-server               │ │
│ │ (console initiator + RTT)   │ │        │ │ (console echo endpoint)  │ │
│ └──────────────┬──────────────┘ │        │ └─────────────┬────────────┘ │
│                │ console fd      │        │               │ console fd   │
└────────────────┼────────────────┘        └───────────────┼──────────────┘
                 │            qvm virtio-console vdev       │
                 └──────────── (EL2 ↔ EL1 boundary) ────────┘
```

Heterogeneous **QNX-safety ↔ Linux-compute** IPC is *not* on the cloud
leg — it is committed to **Phase 3 / Orin**, where KVM works and L4T
natively *is* the Linux side. A dual-guest **Linux-under-QHV** topology
(Option B in ADR-002) is a research-gated **Phase 2.5** stretch only.

**Echo protocol.** Unchanged from the original design — only the
transport changes (a console fd, not a TCP socket). The initiator sends
a small framed message containing a monotonic timestamp; the endpoint
echoes the payload back unmodified; the initiator measures RTT on
receipt. Frame format is fixed-width binary (8-byte sequence + 8-byte
timestamp + N-byte payload) to keep parsing overhead off the latency
path.

**Iteration count and reporting.** 100 000 iterations per run, warm-up
the first 1 000 (discarded). Report:

- **P50** — median, sanity check that the link is alive
- **P99** — primary metric (the load-bearing tail)
- **Max** — worst-case outlier per run

**Time-base normalisation.** On the cloud leg both ends are QNX, so this
is now a **single-OS** measurement: both the host and the guest use
`ClockCycles()` (with `SYSPAGE_ENTRY(qtime)->cycles_per_sec` to convert
to ns). There is no cross-clock skew to handle on this leg. The
cross-OS skew problem (`ClockCycles()` on QNX vs.
`clock_gettime(CLOCK_MONOTONIC)` on Linux) **only re-enters at Phase 3**,
when the Linux Compute end appears on Orin.

---

## Honest framing

This is **not** a like-for-like benchmark vs. DRIVE OS shared-memory
IPC, and on the cloud leg it is **not even a transport benchmark**. The
cloud number is a `virtio-console` exchange across a **TCG-emulated**
`qvm` boundary, so it is dominated by **TCG emulation overhead**, not by
any meaningful transport cost. Read the cloud P50/P99 as a
*mechanism-alive* sanity number — proof the IPC path is wired and stable
across a real partition boundary — and nothing more.

| Mechanism | Approximate P50 RTT |
|---|---|
| DRIVE OS shared memory + mailbox interrupt | < 10 µs |
| This proxy (cloud leg): virtio-console over a **TCG-emulated** `qvm` boundary | **~2.0 ms measured** (P50=2,002,500 ns, P99=Max=2,332,300 ns, 15 samples — [`results/cloud/cloud-ipc-latest.csv`](../results/cloud/cloud-ipc-latest.csv), captured [`logs/sample-boot/qhv-tcg-ipc-benchmark.log`](../logs/sample-boot/qhv-tcg-ipc-benchmark.log)); TCG-emulation-bound, not a transport cost. A larger sample count hits a non-deterministic `qvm`/TCG stall — see `qnx-host-client/README.md` |
| This proxy (Phase 3 / Orin): hardware-timed over KVM | _TBD; the real transport-vs-transport number_ |

What the cloud measurement *is* useful for:

- Establishing that the IPC path is correctly wired and stable across a
  **real `qvm` Type-1 partition boundary** (EL2 host ↔ EL1 guest)
- Showing that the framing, single-OS time-base handling, and P99/tail
  methodology are sound
- Surviving the host `io-sock` failure — the `qvm` vdev does not route
  through the host TCP/IP stack

What the cloud measurement explicitly **does NOT** demonstrate (per the
ADR-002 §6 ledger):

- It does **not** measure hypervisor IPC cost — it measures TCG
  emulation cost. Hardware-timed numbers come from **Phase 3 (Orin /
  KVM)**.
- It does **not** demonstrate certified Type-1 isolation, ASIL-D, or
  quantified freedom-from-interference.
- It does **not** demonstrate QNX-safety ↔ Linux-compute heterogeneity
  on the cloud leg — that lives on Orin.

**RQ-2 stretch (within the committed deliverable).** If byte-stream
console framing proves too coarse, the transport can upgrade to a
shared-memory vdev or a `virtio-vsock`-style channel between host and
guest — but only if ADR-002's research question **RQ-2** comes back
affirmative. virtio-console is the guaranteed floor and is sufficient
for the committed Phase-2 deliverable; the richer channel is not
required.

---

## Layout

```
ipc-test/
├── README.md           # this file
├── Makefile            # builds both QNX sides (qcc); skips linux-client (Phase 3)
├── common/             # shared wire contract + IO/timing helpers (both QNX sides)
│   ├── frame.h         # fixed-width frame (8B seq + 8B tstamp + N-byte payload) + LE pack/unpack
│   └── console_io.h    # full-frame byte-stream read/write loop + ClockCycles() helpers
├── qnx-server/         # Phase 2 (cloud): C99, qcc-built; QNX-guest virtio-console echo endpoint
├── qnx-host-client/    # Phase 2 (cloud): C99, qcc-built; qnx-qhv host console initiator + RTT
│   ├── g2.conf.proposed  # minimal hostdev wiring for the console vdev (passes Phase-1 gate)
│   └── README.md         # build/run + host<->guest wiring proposal + runtime-spike unknowns
└── linux-client/       # Phase 3 (Orin): C99, gcc-built; Linux Compute end of QNX↔Linux IPC over KVM/virtio-net
```

The shared frame contract lives once in `common/frame.h` so the two ends
cannot drift; `common/console_io.h` carries the partial-read/partial-write
loop (virtio-console fds are byte-streams) and the single-OS
`ClockCycles()` timing. Both QNX sides cross-compile with
`make` after sourcing the SDP env (`qnxsdp-env.bat` / `. qnxsdp-env.sh`);
build/run detail and the host<->guest wiring proposal are in
`qnx-host-client/README.md`. Note that `linux-client/` is **Phase 3
only** — it does not build or run on the cloud leg (there is no Linux
guest there).
