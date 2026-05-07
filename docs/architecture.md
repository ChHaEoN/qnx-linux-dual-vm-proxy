# Architecture

This document explains the Digital Twin layout, the build/runtime split
on the cloud side, the host-OS split on the hardware side, and exactly
what the IPC path looks like inside each twin.

The twin design is described in detail in
[digital-twin-design.md](digital-twin-design.md); this file covers
the *structural* picture that designs sits on top of.

---

## DRIVE OS reference architecture (the thing being proxied)

DRIVE OS partitions a single Tegra-class SoC across two guests using
NVIDIA's Type-1 hypervisor:

```
NVIDIA DRIVE OS (real hardware: Orin / Thor SoC)
├── NVIDIA Hypervisor (Type-1)          ← partition isolation
│   ├── Safety guest:   QNX OS for Safety (QOS)   ← ASIL-D path
│   │   └── Safety services (FuSa monitors, Cortex-R52 FSI bridge)
│   └── Compute guest:  Linux            ← AVOS / DriveWorks stack
│       └── CUDA, NVDLA, PVA, MIPI camera ingest, vGPU
└── Inter-VM IPC: hypervisor-mediated shared memory + mailbox interrupts
```

What makes that real: a certified Type-1 partitioner enforces
mixed-criticality isolation; the hardware provides FSI lockstep and
camera ingest; the IPC path is shared memory, not a network.

---

## Cloud twin — hybrid build/runtime on AWS

QNX SDP 8.0 does not have an arm64 host toolchain. The build-side
tools (`mkqnximage`, `qcc`, the QNX Software Center) only run on
x86_64. The runtime side wants arm64 + KVM so the `mkqnximage
--arch=aarch64le` IFS executes natively under hardware virtualization
and the project narrative stays on the target architecture
(Orin / Thor are arm64). Reconciling those two constraints forces
the cloud twin's toolchain across two hosts.

The local dev driver (Macbook Pro M1 Max) is **not** part of the
toolchain — it is the IDE / git / SSH terminal only. All QNX install,
build, and validation lives on AWS, which keeps the validation
surface single-sourced.

```
┌──────────────────────────────┐         ┌─────────────────────────────────┐
│ Build Host (x86_64 EC2)      │  scp    │ Runtime Host (Graviton arm64)   │
│ t3.medium, Ubuntu 22.04      │────────▶│ c7g.large, Ubuntu 22.04 + KVM   │
│                              │  ifs    │                                 │
│ • QNX SDP 8.0 (NCEULA)       │         │ • qemu-system-aarch64 (KVM)     │
│ • mkqnximage --type=qemu     │         │ • Bridge br0 + tap-qnx,tap-linux│
│   --arch=aarch64le           │         │                                 │
│ • produces output/ifs.bin    │         │ ┌──────────┐  ┌──────────────┐  │
│                              │         │ │ QNX VM   │  │ Linux aarch64│  │
└──────────────────────────────┘         │ │ (Safety  │  │ VM (Compute  │  │
                                         │ │ proxy)   │  │ proxy)       │  │
                                         │ └────┬─────┘  └──────┬───────┘  │
                                         │      └────virtio-net┘           │
                                         └─────────────────────────────────┘
```

Build host: `t3.medium` (2 vCPU, 4 GB) is enough headroom for
SDP install + IFS build; t3 charges by the hour and can be stopped
between builds.

Runtime host: `c7g.large` (2 vCPU Graviton3, 4 GB, KVM-on-arm64).
Both VMs run on this single instance.

---

## Hardware twin — Jetson Orin Nano Dev Kit

The hardware-twin host is a single Jetson Orin Nano Dev Kit
(Cortex-A78AE × 6, Ampere GPU, 8 GB RAM, NVIDIA L4T / JetPack 6).
There is no separate build host: the QNX IFS produced on the cloud
twin's x86_64 build host is **scp'd directly to the Orin Nano** and
booted under QEMU on the A78AE cores.

```
                 Build host (cloud twin) ─── scp (output/ifs.bin) ──┐
                                                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Jetson Orin Nano Dev Kit  (NVIDIA L4T / JetPack 6, KVM enabled)         │
│                                                                          │
│   L4T (Ubuntu 22.04 base) is BOTH the host OS AND the Compute side       │
│   of the dual-VM pair. QNX runs in QEMU as the Safety side.              │
│                                                                          │
│   ┌────────────────────────┐         ┌───────────────────────────────┐   │
│   │  QNX VM (in QEMU)      │         │  L4T (host, Compute role)     │   │
│   │  same IFS as cloud twin│         │  native userspace; ipc-test/  │   │
│   │  ┌──────────────────┐  │         │  linux-client built natively  │   │
│   │  │ qnx-server       │  │ virtio  │                               │   │
│   │  │ (TCP listen)     │◄─┼─net────►│  tcp connect to qnx-server    │   │
│   │  └──────────────────┘  │         │                               │   │
│   └─────────────┬──────────┘         └───────────────────────────────┘   │
│                 │ tap-qnx                                                │
│                 ▼                                                         │
│            host bridge br0                                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key structural difference vs the cloud twin:** the Linux side does
not run inside its own QEMU VM on the hardware twin — L4T is already
the host, so there is no point virtualising another Linux. This is
slightly closer to DRIVE OS reality (Linux runs on Tegra natively;
QNX is the partitioned guest), but is **still not** Type-1: the QNX
guest is hosted by KVM-on-L4T, which is host-mediated.

**Why this is the right way to use 8 GB:** running L4T (≈3 GB) +
QEMU(QNX, 1 GB) leaves ~4 GB headroom for the userspace
benchmark + system overhead. Putting Linux in its own QEMU VM as
well would burn 2 GB extra for no architectural benefit, and would
make the twin diff harder to interpret (it would no longer be
isolating "what changes when only the host changes?").

The Orin Nano L4T host is also responsible for **bridge + tap**
provisioning (same `setup-bridge.sh` shape as on AWS, with an Orin
variant in `scripts/orin/`).

---

## Why two hosts (cloud-side)?

**Constraint 1 — `mkqnximage` is x86_64-only.** The QNX SDP 8.0
host toolchain exists only for x86_64 Linux and macOS. Running it
under qemu-user emulation on an arm64 host is unsupported and not
worth the headache.

**Constraint 2 — runtime should be arm64 + KVM.** The portfolio
narrative is BSP / customer-port engineering on arm64 silicon (Orin,
Thor). An x86_64-only run would use QEMU TCG (no hardware
acceleration on arm64 targets) and would be architecturally off-target.

**The IFS is arch-agnostic from the build host's perspective.**
`mkqnximage --arch=aarch64le` produces a bootable image whose
internal target architecture is aarch64; the build host's CPU does
not have to match. So x86_64-build → scp → arm64-run is sound.

**The forced toolchain split is itself part of the engineering
narrative.** Discovering "the target architecture's host toolchain
isn't shipped for the host we want" — and routing around it — is
exactly the day-to-day shape of customer-port BSP work.

---

## IPC path detail

```
┌──────────────────┐                              ┌──────────────────┐
│ QNX guest        │                              │ Linux guest      │
│ ┌──────────────┐ │                              │ ┌──────────────┐ │
│ │ qnx-server   │ │                              │ │ linux-client │ │
│ │ (TCP listen) │ │                              │ │ (TCP connect)│ │
│ └──────┬───────┘ │                              │ └──────┬───────┘ │
│        │         │                              │        │         │
│  virtio-net guest│                              │  virtio-net guest│
│        │         │                              │        │         │
└────────┼─────────┘                              └────────┼─────────┘
         │ tap-qnx                                         │ tap-linux
         │                                                 │
         └────────────────── br0 (192.168.100.1/24) ───────┘
                                  │
                            Linux host kernel (Graviton, Ubuntu 22.04)
```

**Path summary:** guest userspace → guest virtio-net driver →
host tap device → host bridge `br0` → host tap device → guest
virtio-net driver → guest userspace. Six context boundaries plus
two virtio rings.

**MAC addresses:** locally-administered, stable across runs:
- QNX VM: `52:54:00:11:11:11`
- Linux VM: `52:54:00:22:22:22`

**Bridge IP `192.168.100.1/24`** is the host side; guests get
addresses in `192.168.100.0/24` (statically configured per VM
during Phase 1 to keep the path deterministic).

---

## What this is NOT (per twin side)

| Aspect | Real DRIVE OS | Cloud twin (AWS Graviton) | HW twin (Jetson Orin Nano) |
|---|---|---|---|
| Partitioner | Type-1 NVIDIA Hypervisor | KVM + Linux host kernel scheduling two QEMU processes | KVM-on-L4T scheduling QEMU(QNX) alongside native L4T workload |
| Shared SoC | Yes (Tegra Orin / Thor) | No — pure-virt, no shared peripherals | **Same Tegra family** (A78AE, Ampere) but Jetson SKU; no DRIVE-class FuSa peripherals |
| Inter-VM IPC | Shared memory + mailbox | virtio-net through host bridge | virtio-net through host bridge (same path; same code) |
| VM-aware scheduling | Yes (partition scheduler) | No — host CFS schedules everything | No — L4T CFS schedules QEMU thread alongside L4T processes |
| Real-time | Certified RT path on Safety guest | Best-effort; jitter from host scheduler is observable | Best-effort; A78AE does have hardware RT support but L4T host doesn't expose certified RT |
| FSI lockstep | Cortex-R52 lockstep cluster | None | None — Jetson SKU has no FSI exposed to user software |
| Camera / NVDLA / GPU | Real, vGPU-partitioned | None — Graviton has no NVIDIA accelerators | Real Ampere GPU is present but **out of scope** for this project; not exposed to QNX guest |
| Bootloader chain | SecureBoot + measured boot, certified | None | None — JetPack provides UEFI but no chain-of-trust beyond default |

The project's value lives in being *honest* about every row of that
table on **each side of the twin**, and using the twin diff to study
the rows that *are* exercised (BSP bring-up, kernel boundaries, IPC
patterns, cloud→target portability).
