# Architecture

The structural picture: what is being proxied, how the current arrangement is
put together, and what the IPC path physically is on each one.

- The **verdicts** — what this validates against DRIVE OS and what it cannot —
  are in [drive-os-comparison.md](drive-os-comparison.md). There is one
  comparison table in this repo and it lives there.
- The **twin methodology** is in [digital-twin-design.md](digital-twin-design.md).
- The **architecture table**, with dates and sources for every version, is in
  [the plan](orin-native-port-plan.md#architecture-versions).
- [findings.md](findings.md) is append-only and dated, and wins if anything
  here disagrees with it.

---

## What is being proxied

DRIVE OS partitions a single Tegra-class SoC across two guests under NVIDIA's
Type-1 hypervisor:

```
 NVIDIA DRIVE OS  (Orin / Thor silicon)  --  none of this is in this project
 ├── NVIDIA Hypervisor (Type-1)           <- certified partition isolation
 │   ├── Safety guest   QNX OS for Safety (QOS)        <- ASIL-D path
 │   │                  FuSa monitors, Cortex-R52 FSI bridge
 │   └── Compute guest  Linux                          <- AVOS / DriveWorks
 │                      CUDA, NVDLA, PVA, MIPI camera, vGPU
 └── Inter-VM IPC       hypervisor-mediated shared memory + mailbox interrupts
```

Three things make that real and are absent here: a **certified** Type-1
partitioner enforcing mixed-criticality isolation, **FSI lockstep and camera
ingest** in the hardware, and an IPC path that is **shared memory between VMs,
with a notification mechanism, not a network**. (A6's `ivshmem` slot, 2026-09-22,
is host↔guest and polled.)

---

## A6 — the current arrangement

Linux is on the metal and keeps the GPU. QNX is a KVM guest beside it. The
boundary is real hardware EL2/EL1, but **the supervisor is Linux**: there is no
Type-1 layer, because QHV needs EL2 and ARM KVM does not nest on A78AE.

```
 Jetson Orin Nano — Tegra234, 6 × Cortex-A78AE, Ampere iGPU
 ┌─────────────────────────────────────────────────────────┐
 │  L4T / JetPack 6 — EL1, owns the machine                │
 │                                                         │
 │    TensorRT / CUDA ─────► Ampere iGPU                   │
 │                            QNX never touches it         │
 │                                                         │
 │    latency probe                                        │
 │         │ 64-byte frame, TCP :7100                      │
 │         ▼                                               │
 │    br0 ── tap-qnx   192.168.100.1                       │
 │         │ virtio-net                                    │
 │         ▼                                               │
 │    ┌─────────────────────────────────────────────────┐  │
 │    │  QEMU + KVM — 2 of 6 vCPU, 1 GB                 │  │
 │    │                                                 │  │
 │    │   ┌──────────────────────────────────────────┐  │  │
 │    │   │  QNX SDP 8.0 guest — EL1, on A78AE       │  │  │
 │    │   │  procnto · io-sock · qnx-safety-monitor  │  │  │
 │    │   │  192.168.100.10                          │  │  │
 │    │   └──────────────────────────────────────────┘  │  │
 │    └─────────────────────────────────────────────────┘  │
 └─────────────────────────────────────────────────────────┘
```

**The guest boots only with a `startup-qemu-virt` rebuilt in this repo.** The
one QNX ships stops after 17 bytes of serial (`FOUND GICv3 ITS`) under
`-enable-kvm`; a rebuild with `-fno-auto-inc-dec` removes a writeback MMIO
store at GICD+0x420 that reports ISV=0 and so cannot be emulated. That rebuild
is **not a QNX-supported configuration**.

**Measured, 2026-09-21.** The round trip above is 182 µs at p50, and the
attribution ladder splits it: 53 µs is rung A, the probe and a host-side server
over loopback TCP (not the probe alone: through shared memory the same probe's loop
measures 4.5 µs, 2026-09-22),
3 µs is `br0`, and **126 µs is the crossing** — tap, virtio-net, the guest's
`io-sock`, its scheduler and the monitor. Method and sample sizes:
[measurement-design.md](measurement-design.md).

---

## A4 and A5 — the hypervisor on silicon, and why it is not the direction

The QNX Hypervisor ran **natively at EL2 on the board's own cores, with no
QEMU**, entered by `kexec` from L4T or, once, by an EFI loader of ours from the
firmware's UEFI Shell. It hosted the byte-identical cloud-leg QNX guest (M3),
then a stock Linux kernel (S1-F), then both at once (B5).

```
 QNX Hypervisor host — procnto at EL2, VHE (E2H + TGE), no QEMU anywhere
 ┌──────────────────────────────────────────────────────────┐
 │    ┌────────────────────────┐   ┌─────────────────────┐  │
 │    │  QNX guest (EL1)       │   │  Linux guest (EL1)  │  │
 │    │  the cloud-leg image,  │   │  stock L4T kernel,  │  │
 │    │  byte-identical        │   │  no GPU             │  │
 │    └────────────┬───────────┘   └─────────────────────┘  │
 │                 │ qvm virtio-console vdev                │
 │                 ▼ a real EL2/EL1 partition boundary      │
 └──────────────────────────────────────────────────────────┘
```

**Every rung is a functional pass and none is timed**, and the figures are
unpublished under NC QDL v7 4.6(i). It is not withdrawn — it stopped being the
direction because **under it no OS can use the GPU** on Tegra234: the iGPU has
no SMMU stream ID, and its clock, reset and power go through BPMP, for which
QNX has no client driver.

Consequence, decided 2026-09-20: the TCG legs that were QHV's only other route
are withdrawn, so **no hardware-timed hypervisor number exists in this project
and none ever will.**

---

## The hypervisor IPC path (A1, A3, A4 — history)

The one path in this project that crosses a **real Type-1 partition boundary**.
It is not a network: no bridge, no tap, no `io-sock`.

```
 ┌───────────────────────────┐     ┌─────────────────────────┐
 │  QHV host (EL2)           │     │  QNX guest (EL1)        │
 │  qnx-host-client          │     │  qnx-server             │
 │  console initiator + RTT  │     │  console echo endpoint  │
 └─────────────┬─────────────┘     └────────────┬────────────┘
               │ console fd                     │ console fd
               └─── qvm virtio-console vdev ────┘
                  the EL2 / EL1 partition boundary
```

Under A1 and A3 this ran inside QEMU **TCG**, so its latency measures emulation
cost, not transport cost. Under A4 it ran on silicon, and that run is a
completion, not a timing. **No hypervisor shared-memory or mailbox figure exists
on any architecture**: the `vdev shmem` path was functional-only, TCG-only, never
timed, and its notify half was deliberately skipped. (A6's `ivshmem` figure of
2026-09-22 is host↔guest under KVM, polled, with no notification path.)

---

## Earlier architectures

Closed, not redone; each record keeps the id of the version it ran on. Dates and
sources are in [the plan's table](orin-native-port-plan.md#architecture-versions).

| id | what it was |
|---|---|
| **A1** | cloud leg: QHV `qvm` + one QNX guest under QEMU TCG. Designed for AWS Graviton, built on the local Windows PC, because non-metal Graviton exposes no `/dev/kvm` |
| **A2** | Orin plain leg: QEMU TCG beside L4T, QNX↔Linux IPC over `br0`/tap to a native Linux client |
| **A3** | A1's images unchanged, in TCG on both hosts — the twin comparison on the hypervisor topology |

Closing a phase never meant its target was met: A1's reliable runs never reached
the 100k-iteration target, A2's IPC run used a **rebuilt** IFS rather than the
byte-identical image, and KVM-accelerated boot never worked at the time.

Two items stay open on their own. The `qvm`/TCG virtio-queue stall is still not
root-caused and is only *survivable*, via a kick-safe sentinel frame. The
GICv3/NISV defect is open in QNX's **shipped** binary only; it was root-caused
and cleared at the source by the rebuilt startup, and the owner decided not to
report it.

---

## Build hosts

Every QNX image is built on an **x86_64 host** — SDP 8.0 ships Windows and
Linux x86_64 host tools, and no arm64 or macOS ones. In practice that is the
owner's Windows PC, which is also the dev driver; an EC2 t3.medium stays
documented as a fallback. The build host runs `mkqnximage` and host-side
tooling only; no guest runs on it beyond the historical TCG legs.

This is **not** parity with a real DRIVE OS customer's build environment, which
is typically a rented or vendor-provided Linux host. A Windows-vs-EC2
build-equivalence check was withdrawn on 2026-05-07 and none is planned.

---

## AWS

A test bed, never a runtime host. Non-metal Graviton exposes no `/dev/kvm` at
all ([ADR-002](phase2-topology-decision.md)), so the `c7g.large` runtime host
the design called for was never built. Bare metal is different: `a1.metal` has
`/dev/kvm`, the same rebuilt startup boots a QNX guest under KVM there, and on
2026-09-20 it was the second host in a two-host boot comparison on a
byte-identical image.

**No IPC, latency or throughput figure has ever been taken on any cloud host.**
`c7g.metal`, the closer core match, stays quota-blocked at 64 vCPU against a
32-vCPU account limit.
