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

## Cloud twin — hybrid build/runtime

QNX SDP 8.0 does not have an arm64 host toolchain. The build-side
tools (`mkqnximage`, `qcc`, the QNX Software Center) only run on
**x86_64 Linux native** or **Windows native** — no macOS, no arm64
Linux. The runtime side wants arm64 so the `mkqnximage
--arch=aarch64le` IFS executes on the target architecture and the
project narrative stays on-target (Orin / Thor are arm64). Reconciling
those two constraints forces the cloud twin's toolchain across two
hosts: an x86_64 builder and an arm64 runtime.

> **Note (per [ADR-002](phase2-topology-decision.md)):** the cloud
> runtime originally assumed KVM-on-arm64 hardware virtualization, but
> AWS non-metal Graviton exposes **no `/dev/kvm`** — so the cloud leg
> runs under QEMU **TCG** emulation, hosting the SDP 8.0 QHV (`qvm`)
> and a single QNX guest. KVM acceleration was moved to Phase 3 (Orin), but
> KVM boot there is blocked by the GICv3/NISV defect
> ([orin-port.md](orin-port.md) risk register), so that leg runs TCG too.

Per the 2026-05-07 amendment in [findings.md](findings.md), the
primary build host is a **local Windows PC** (the same machine that
serves as the dev driver). The EC2 t3.medium x86_64 Ubuntu instance
is retained as an **explicit fallback** for users without a local
x86_64 Windows or Linux box. The runtime host was designed to stay on
Graviton. As built, the QHV host and its guest run under TCG on the same
Windows PC, and no cloud-leg number came from Graviton
([digital-twin-design.md](digital-twin-design.md) §1).

> **As-built per [ADR-002](phase2-topology-decision.md) (Accepted).** The
> cloud runtime is **not** two co-equal KVM guests over a Linux bridge —
> that topology is falsified (no `/dev/kvm` on cloud Graviton; no Linux
> guest; host `io-sock` down). The cloud leg is the SDP 8.0 **QHV** host
> `qvm` running a **single QNX guest** under `qemu-system-aarch64 -accel
> tcg` (TCG, **not** KVM), with **no** `br0`/tap. The Linux Compute side
> moved to **Phase 3 / Orin**.

```
┌──────────────────────────────┐         ┌─────────────────────────────────┐
│ Build Host (PRIMARY)         │  scp    │ Runtime (as built: this PC)     │
│ Local Windows PC (x86_64)    │────────▶│ design: Graviton c7g.large      │
│ • QNX SDP 8.0 Windows native │  ifs    │                                 │
│ • mkqnximage --type=qemu     │         │ • qemu-system-aarch64 -accel tcg│
│   --qvm=yes  (QHV host+guest)│         │   (no /dev/kvm on cloud)        │
│ • produces output\ifs.bin    │         │ • qvm  (QHV host, EL2)          │
│                              │         │ • NO br0/tap (io-sock down)     │
│ Build Host (FALLBACK)        │         │                                 │
│ t3.medium x86_64 Ubuntu EC2  │ ──scp──▶│ ┌─────────────────────────────┐ │
│ • same QNX SDP 8.0 install   │  ifs    │ │ qnx-qhv HOST (EL2)          │ │
│ • same mkqnximage invocation │         │ │  └─ qvm @g2.conf            │ │
└──────────────────────────────┘         │ │      ┌──────────────────┐   │ │
                                         │ │      │ qnx-guest (EL1)  │   │ │
        Linux Compute guest ── moved ──▶ │ │      │ console/blk vdevs│   │ │
        to Phase 3 / Orin (L4T native)   │ │      └──────────────────┘   │ │
                                         │ └─────────────────────────────┘ │
                                         └─────────────────────────────────┘
```

Build host (primary): a developer-class Windows PC. SDP install,
IFS build, and `scp` to the runtime host all run locally; no EC2
build-host hours billed.

Build host (fallback): `t3.medium` (2 vCPU, 4 GB) is enough headroom
for SDP install + IFS build; t3 charges by the hour and can be
stopped between builds.

Runtime host (design): `c7g.large` (2 vCPU Graviton3, 4 GB). Per
[ADR-002](phase2-topology-decision.md), there is **no `/dev/kvm`** on
non-metal Graviton, so the QHV host + single QNX guest run under QEMU
**TCG**. As built they run on the local Windows PC, not on this instance,
so the diagram's `scp` hop to a runtime host does not occur. The Linux
Compute guest moved to Phase 3 / Orin.

**Honest framing:** the Windows-primary pivot removes ssh / X11 /
browser-flow friction and EC2 build-host cost — but it does **not**
demonstrate cross-host build determinism. A Phase-1 check that a
Windows-built IFS matches an EC2-built one was proposed, then withdrawn
on 2026-05-07 as over-specified: the build host changes only build
metadata, not the aarch64 code QNX boots ([findings.md](findings.md),
2026-05-07 amendment; [bsp-selection.md](bsp-selection.md), F5 note).
The EC2 host stays a fallback, not a canonical reference.
And the local Windows host is **not** closer to a real DRIVE OS
customer build environment than EC2 is — production AVOS / DRIVE OS
customer builds run on rented / vendor-provided Linux farms, not
local Windows. The pivot is a friction/cost win, not an
architectural improvement.

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
│ Jetson Orin Nano Dev Kit  (NVIDIA L4T / JetPack 6, TCG; KVM blocked)    │
│                                                                          │
│   L4T (Ubuntu 22.04 base) is BOTH the host OS AND the Compute side       │
│   of the dual-VM pair. QNX runs in QEMU as the Safety side.              │
│                                                                          │
│   ┌────────────────────────┐         ┌───────────────────────────────┐   │
│   │  QNX VM (in QEMU)      │         │  L4T (host, Compute role)     │   │
│   │  rebuilt IFS (TCP srv) │         │  native userspace; ipc-test/  │   │
│   │  ┌──────────────────┐  │         │  linux-client built natively  │   │
│   │  │ qnx-server-net   │  │ virtio  │                               │   │
│   │  │ (TCP listen)     │◄─┼─net────►│  tcp connect to qnx-server-net│   │
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
guest is hosted by QEMU TCG on L4T (KVM boot is blocked; see
[orin-port.md](orin-port.md)), which is host-mediated. The IPC run used an
IFS rebuilt to stage the TCP server ([orin-port.md](orin-port.md) step 4).

**Why this is the right way to use 8 GB:** running L4T (≈3 GB) +
QEMU(QNX, 1 GB) leaves ~4 GB headroom for the userspace
benchmark + system overhead. Putting Linux in its own QEMU VM as
well would burn 2 GB extra for no architectural benefit, and would
make the twin diff harder to interpret (it would no longer be
isolating "what changes when only the host changes?").

The Orin Nano L4T host is also responsible for **bridge + tap**
provisioning (`scripts/orin/setup-bridge-orin.sh`, an Orin variant of
`setup-bridge.sh`; the cloud script is not used on the as-built cloud leg).

---

## Hardware twin, native — QNX Hypervisor on the Orin Nano (Phase 3b)

*Added 2026-09-11.* The section above runs QNX under QEMU on L4T. Phase 3b
runs it on the board with no QEMU at all. The plan's architecture table
calls this **A4**
([orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions)).

```
Jetson Orin Nano Dev Kit, native (A4, as run in M3)
L4T hands over by kexec, then is gone while QNX runs
└── QNX Hypervisor host: procnto at EL2 (VHE), this port's own board startup
    ├── host process: IPC client
    └── qvm
        └── QNX guest: the cloud leg's guest image and disk
            (IPC over the qvm virtio-console vdev)
```

- **What changes against the QEMU twins:** the hypervisor runs on silicon.
  Stage-2 translation, the virtual GIC and the guest timers run on the real
  A78AE, not inside an emulator ([findings.md](findings.md) 2026-09-10).
- **What it does not have:** L4T, so no Linux Compute side; no GPU; no
  certified isolation.
- **Status:** M0, M1, M2, M1b and M3 are met. Under the owner's freeze
  decision its measurements run in the v1 campaign. M3's figures are A4
  history and stay on the local branch `m3-results-unpublished`.

**Target: reference architecture v1 (not frozen).** A4's native host plus a
Linux guest without a GPU under `qvm` (S1), plus two TCG twin legs that boot
v1's guests in a QHV host image under QEMU. Whether the QNX guest stays beside
the Linux guest is settled at the freeze. GPU pass-through is a later stage,
still research only. Details: the plan's architecture table and freeze gate.

---

## Why two hosts (cloud-side)?

**Constraint 1 — `mkqnximage` is x86_64-only.** The QNX SDP 8.0
host toolchain exists only for x86_64 Linux native and x86_64
Windows native (no macOS, no arm64 Linux). Running it under
qemu-user emulation on an arm64 host is unsupported and not worth
the headache.

**Constraint 2 — runtime should be arm64.** The portfolio narrative is
BSP / customer-port engineering on arm64 silicon (Orin, Thor). An
x86_64-only run would be architecturally off-target. Note (per
[ADR-002](phase2-topology-decision.md)): the cloud runtime *wanted* KVM
too, but non-metal Graviton has no `/dev/kvm`, so the cloud leg runs
under TCG. KVM boot on the Phase-3 Orin twin is blocked too (GICv3/NISV;
[orin-port.md](orin-port.md)), so that leg also runs TCG. The arm64-on-target
argument still holds (the IFS is aarch64 either way).

**The IFS is arch-agnostic from the build host's perspective.**
`mkqnximage --arch=aarch64le` produces a bootable image whose
internal target architecture is aarch64; the build host's CPU does
not have to match. So x86_64-build → scp → arm64-run is sound.

**The forced toolchain split is itself part of the engineering
narrative.** Discovering "the target architecture's host toolchain
isn't shipped for the host we want" — and routing around it — is
exactly the day-to-day shape of customer-port BSP work.

---

## IPC path detail (cloud leg)

Per [ADR-002](phase2-topology-decision.md), the cloud-leg IPC path is
**not** a Linux-bridge / virtio-net path between two guests — that
design is falsified. The cloud leg crosses the `qvm` partition boundary
between the QNX *host* and the single QNX *guest*, over the
`virtio-console` vdev already declared in the live `g2.conf`.

```
┌─────────────────────────────────┐        ┌──────────────────────────────┐
│ qnx-qhv  (QHV host, EL2)        │        │ qnx-guest  (EL1 guest)       │
│ ┌─────────────────────────────┐ │        │ ┌──────────────────────────┐ │
│ │ qnx-host-client             │ │        │ │ qnx-server               │ │
│ │ (console initiator + RTT)   │ │        │ │ (console echo endpoint)  │ │
│ └──────────────┬──────────────┘ │        │ └─────────────┬────────────┘ │
│                │ console fd      │        │              │ console fd    │
└────────────────┼────────────────┘        └──────────────┼───────────────┘
                 │       qvm virtio-console vdev           │
                 └─────────── (EL2 ↔ EL1 boundary) ────────┘
```

**Path summary:** host userspace → host console fd → `qvm` virtio-console
vdev (the EL2/EL1 partition boundary) → guest console fd → guest
userspace, and back. This crosses the **real `qvm` Type-1 partition
boundary**, not a host network. It does **not** route through host
`io-sock`, a Linux bridge, or tap devices — all of which are dead on
this leg (no working host network stack; `io-sock` down).

**Honest framing:** this demonstrates IPC across a real EL2↔EL1 `qvm`
boundary, but the cloud leg is **TCG-emulated**, so the latency it
yields is dominated by TCG emulation cost — it does **not** measure
hardware-timed hypervisor IPC. Hardware-timed numbers come from the
native QNX Hypervisor on the Orin (Phase 3b, section above), in the v1
campaign; the Phase-3 Orin twin under QEMU runs TCG as well. The
heterogeneous QNX↔Linux IPC (the bridged virtio-net path with `tap`/`br0`)
is committed to **Phase 3 / Orin**, where it runs natively against L4T —
see that twin's section above.

---

## What this is NOT (per twin side)

| Aspect | Real DRIVE OS | Cloud twin (designed on AWS Graviton; as built on a Windows PC) | HW twin (Jetson Orin Nano, QEMU on L4T) |
|---|---|---|---|
| Partitioner | Type-1 NVIDIA Hypervisor | SDP 8.0 QHV (`qvm`) hosting one QNX guest under QEMU **TCG** (no KVM on cloud; see [ADR-002](phase2-topology-decision.md)) | QEMU TCG on L4T (KVM boot blocked) running QNX alongside native L4T workload |
| Shared SoC | Yes (Tegra Orin / Thor) | No — pure-virt, no shared peripherals | **Same Tegra family** (A78AE, Ampere) but Jetson SKU; no DRIVE-class FuSa peripherals |
| Inter-VM IPC | Shared memory + mailbox | host↔guest over `qvm` virtio-console vdev (TCG-emulated EL2 partition boundary; not hardware-timed) | virtio-net through host bridge (Phase 3; heterogeneous QNX↔Linux) |
| VM-aware scheduling | Yes (partition scheduler) | No — the host OS scheduler schedules everything | No — L4T CFS schedules QEMU thread alongside L4T processes |
| Real-time | Certified RT path on Safety guest | Best-effort; jitter from host scheduler is observable | Best-effort; A78AE does have hardware RT support but L4T host doesn't expose certified RT |
| FSI lockstep | Cortex-R52 lockstep cluster | None | None — Jetson SKU has no FSI exposed to user software |
| Camera / NVDLA / GPU | Real, vGPU-partitioned | None — the emulated `virt` machine has no NVIDIA accelerators | Real Ampere GPU is present but **out of scope** for this project; not exposed to QNX guest |
| Bootloader chain | SecureBoot + measured boot, certified | None | None — JetPack provides UEFI but no chain-of-trust beyond default |

The project's value lives in being *honest* about every row of that
table on **each side of the twin**, and using the twin diff to study
the rows that *are* exercised (BSP bring-up, kernel boundaries, IPC
patterns, cloud→target portability).
