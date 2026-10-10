# DRIVE OS comparison — what this proxy validates vs. reality

This document is the deliverable for **Phase 4**. It catalogues, dimension by
dimension, what this project's legs can *actually* validate against the public
DRIVE OS reference architecture, and where the hard boundaries are.

It is deliberately not a sales pitch. The goal is calibration: a reader should
leave knowing which claims here are real, which are qualitatively suggestive,
and which are off-limits.

> **Status (2026-09-27): measured and functional results are held locally.**
> NC QDL v7 clause 4.6(i) forbids making the results of any performance or
> functional evaluation of the QNX software available to a third party without
> BlackBerry's prior written approval, which has not been obtained. Every
> figure, every functional outcome and every verdict that rests on one has
> therefore been withdrawn from this public file; the verdicts and their
> evidence are kept locally. What remains is the design: what DRIVE OS does,
> what this project built, and the verdicts that follow from design alone.
> OD10 (2026-09-20) settled the campaign's shape (A6 measures under KVM only,
> the TCG twin legs are withdrawn) and OD11 (2026-09-21) its sample sizes.

## The short version

**No dimension earns "Validates". Two are "Cannot" by design; the verdicts on
the other six, and their evidence, are held locally.**

The project reproduces, at most, the *shape* of the DRIVE OS arrangement and
the *substance* of none of it — because substance here means certification,
bounded latency, a root of trust, and a Type-1 hypervisor that owns the
machine, and this project has none of those by design. Two dimensions are
structurally out of reach on any host it will ever have.

The most consequential single fact: **there will never be a QNX Hypervisor
number in this project.** QHV needs EL2 and ARM KVM does not nest on A78AE, so
it cannot run under KVM; OD10 withdrew the TCG legs that were its only emulated
route; and the native A4 records are unpublished under NC QDL v7 4.6(i). The
hypervisor work carries **no timing figure**, and its functional record is held
locally.

---

## Concept-by-concept comparison

Columns are the project's architecture ids, from the plan's
[architecture table](orin-native-port-plan.md#architecture-versions):

- **A1** — cloud leg: SDP 8.0 QHV (`qvm`) hosting one QNX guest under QEMU
  **TCG**. Designed for AWS Graviton; as built it was set up on the owner's
  local x86_64 Windows PC, because non-metal Graviton exposes no `/dev/kvm`
  ([ADR-002](phase2-topology-decision.md)). History.
- **A2** — Orin plain leg: QEMU **TCG** beside L4T, QNX↔Linux IPC over
  `br0`/`tap-qnx`. History. Its IPC run used a *rebuilt* IFS.
- **A4** — the QNX Hypervisor running **natively at EL2** on the Orin's own
  A78AE cores, no QEMU. Milestones M0–M5; their records are held locally.
  Superseded as a direction on 2026-09-18 because no OS can use the GPU under
  it (the iGPU has no SMMU stream ID, and its clock, reset and power go through
  BPMP, for which QNX has no client driver). The two-guest arrangement (a Linux
  guest and the QNX guest under one `qvm`) is **S1-F/B5**, which the plan
  assigns to **A5**, not A4.
- **A6** — **current**: L4T on the metal owning the GPU, QNX as a **KVM guest**
  beside it.

| Concept | DRIVE OS | A6 — current (QNX as a KVM guest on the Orin) | Verdict |
|---|---|---|---|
| **VM partitioning** | Type-1 hypervisor on a Tegra SoC, safety-certified | QNX as a KVM guest (`-cpu host -enable-kvm`, 2 of 6 vCPU) beside L4T: a hardware EL2/EL1 boundary, but **Linux is the supervisor and owns the guest's memory**. No Type-1 layer; QHV cannot run under KVM. | **Verdict and evidence held locally.** Whatever it is, the arrangement is **uncertified** — SDP 8.0 is not QNX OS for Safety — **no isolation, containment or freedom-from-interference result exists**, and no QHV number exists or ever will (OD10). |
| **Same Tegra silicon family** | Yes (Orin / Thor) | Both partitions on Tegra234: L4T on the metal with the real Ampere iGPU, QNX on 2 of 6 A78AE cores under `-cpu host` — no emulated CPU. The guest still sees QEMU's generic `virt` machine. | **Verdict and evidence held locally.** By design the board is a 6-core Jetson SKU (not DRIVE Orin's 12, and nothing here touches Thor), and the guest sits behind `virt`: no Tegra peripheral, no BPMP, no SMMU, no GPU. **Not a QNX-supported configuration** — every A6 arm uses a `startup-qemu-virt` rebuilt in this repo, not the one QNX ships. |
| **Dual-OS coexistence** | QNX Safety + Linux Compute on one Tegra, as peers under the HV | L4T on the metal with the GPU and QNX as a KVM guest on the same A78AE cores; the cross-partition paths built are a `br0`/`tap-qnx` bridge and a DDS variant of the monitor. | **Verdict and evidence held locally.** By design **the two OSes are never peers** under A6: Linux is the host and owns the QNX guest's memory, so there is no Linux Compute *partition*. The leg where they are peers (A5/S1-F) has no GPU, and its records are held locally. **No leg has both.** |
| **Asymmetric workload** | Safety FuSa monitors / Compute DriveWorks | L4T holds the iGPU (a TensorRT inference and a synthetic FMA load) while the QNX guest only judges claims — ACCEPT/REJECT over TCP and over DDS. | **Partial** — asymmetric *in kind*, but the rules are legible plausibility checks whose thresholds `monitor.c` itself says were chosen for the demo and **not derived from any hazard analysis**; no ASIL, no RT bound, no DriveWorks-class load. **The privilege is inverted**: Compute owns Safety's memory, and QNX can touch no accelerator on Tegra234 at all. |
| **Inter-VM IPC** | Shared memory + mailbox, sub-µs | Cross-partition round trips from L4T to the guest's monitor, 64-byte frame: over TCP on a bridge under KVM (record `20260919T-native-cmp`, held locally); through one shared-memory slot in QEMU's `ivshmem`, both ends polling (`20260922T-a6-orin-shm`, held locally); and through the same slot notified — the guest kicked over a virtio console, answering through the `ivshmem` doorbell (`20260922T-a6-orin-kick`, held locally). | **Verdict and evidence held locally.** By design all of these are **host↔guest, not VM↔VM**: there is no hypervisor in the path and Linux owns the other side. The first is **TCP over virtio-net**; the second is shared memory with both ends spinning, holding a core or a vCPU; the third is shared memory notified by a doorbell **in one direction only** — QEMU's `ivshmem` interrupts a guest by MSI-X alone, which that arrangement does not enable in the guest, so the host reaches it through a virtio console. A second way in, MSI-X through the GIC ITS, exists as code for separate images (the startup `startup-qemu-virt-its`, the probe `qnx-its-probe` and the build file `ifs-bell.build`; this guest runs no PCI server, so the vector is mapped to an LPI by hand), and no result of it is published. None is the quantity DRIVE OS's figure names. No VM↔VM or mailbox figure exists at any architecture, and per OD10 no hypervisor-path figure ever will. |
| **Boot sequencing** | HV brings up Safety → Compute with cross-checks | L4T boots first — it is the host — then QNX starts as a KVM guest launched by a shell command from L4T userspace. The bring-up was segment-timed on two hosts (record `20260920T-kvm-twin`, held locally). | **Verdict and evidence held locally.** By design **the order is inverted** (Compute must be fully up first, because it is the host), nothing enforces it, and there are **no cross-checks, no health gate and no fail-to-safe**. The timing design starts its clock at QEMU exec, so the Compute side's own boot is never measured. |
| **Bootloader chain** | SecureBoot → measured boot → HV → guest IPLs | JetPack UEFI with Secure Boot **off** → L4T → QEMU `-kernel` loads the IFS directly. No guest IPL and no HV stage. New in A6: the project owns the startup board stage. | **Cannot** — no root of trust at any stage on any leg: nothing signed, nothing measured, no fuse- or TPM-anchored anchor. A6 has *fewer* stages than DRIVE OS, not more. (The second host used on 2026-09-20, AWS `a1.metal`, has no JetPack UEFI and no L4T at all — a different pre-QEMU chain entirely.) |
| **Real-time guarantees** | Certified RT on the Safety partition | QNX latency under host load was measured on hardware with the governor pinned (records `20260919T-saturation` and `20260919T-native-cmp`, held locally). | **Cannot** — no bound, no WCET argument, no deadline, and the guest is **never configured for real time** (`monitor.c` is pure POSIX at default priority, so QNX's priority scheme and FIFO scheduling are untouched by every measurement here). Its vCPU threads are scheduled by a general-purpose Linux kernel, and the saturation run is designed to measure **interference reaching the Safety partition**; it cannot show freedom from it. |

---

## Quantitative data

The reference column is for orientation only and comes from public NVIDIA
material, not from this project. This project's own figures are held locally
(NC QDL v7 4.6(i)); the column names the record each one lives in.

**Read the IPC rows carefully.** DRIVE OS's inter-VM figure is a VM↔VM round
trip across a Type-1 hypervisor over shared memory. This project has no such
figure and, per OD10, never will — so those rows stay empty rather than being
filled with a number that measures something else. The quantities this project
does have are *host↔guest* round trips — over TCP and virtio-net, and
(2026-09-22) through a shared-memory slot in QEMU's `ivshmem`, polled and
notified — and they sit on their own rows against no reference.

| Metric | DRIVE OS reference (public, approximate) | This project |
|---|---|---|
| QNX guest boot time, to guest banner | n/a — different SoC | Timed on the Orin Nano and on AWS `a1.metal` under KVM with a byte-identical IFS, 2026-09-20: record `20260920T-kvm-twin`, held locally. |
| Linux guest boot time | n/a — different SoC | Linux guest under native `qvm` (S1-F, rungs B3/B4, 2026-09-17): record held locally under NC QDL v7 4.6(i). |
| Inter-VM IPC P50 (VM↔VM, shared memory) | < 10 µs | **none.** The hypervisor's shared-memory path (`qvm vdev shmem`, A1) was TCG-only and never timed; its notify half was deliberately skipped. OD10 removed the last route to a hypervisor-path figure. A VM↔VM figure under KVM, with two guests on one `ivshmem` file, has not been built, and the host↔guest `ivshmem` quantities below are not this quantity. |
| Inter-VM IPC P99 (VM↔VM, shared memory) | < 50 µs | none — as above |
| Inter-VM IPC P99.9 (VM↔VM, shared memory) | bounded by RT guarantees | none — as above |
| **Host↔guest round trip under KVM** (this project's own quantity; **no DRIVE OS counterpart**) | — | Record `20260919T-native-cmp`, held locally. 64-byte frame, L4T → QNX guest monitor over `br0`/`tap-qnx`/virtio-net. A **whole-system** round trip — Linux stack, bridge, guest `io-sock`, guest scheduler — not a QNX-attributable latency. |
| **Host↔guest shared memory under KVM, polled** (this project's own quantity; **no DRIVE OS counterpart**) | — | Record `20260922T-a6-orin-shm`, held locally. One 64-byte slot in QEMU's `ivshmem`, L4T → QNX guest monitor, both ends spinning. No notification, no hypervisor, and a core and a vCPU held while waiting. |
| **Host↔guest shared memory under KVM, notified** (this project's own quantity; **no DRIVE OS counterpart**) | — | Record `20260922T-a6-orin-kick`, held locally. The same slot, the guest kicked awake over a virtio console and answering through the `ivshmem` doorbell, which KVM turns into an eventfd write in the kernel. In this arrangement the doorbell runs guest→host only; host→guest is the console. |
| The same program, natively on L4T (control) | — | Record `20260919T-native-cmp`, held locally. Same board, same unmodified `monitor.c`, loopback. The difference is transport *and* partition together, not the partition alone. |
| Sustained throughput (1 KB message) | hardware-bound | **never measured**, on any leg. |

---

## How to read this document

- **"Validates"** — the proxy reproduces the engineering shape of the concept
  faithfully enough to be a useful study target. **No dimension currently earns
  this.**
- **"Partial"** — structural similarity exists but the substance (numbers,
  certifications, hardware behaviour) does not.
- **"Cannot"** — structurally outside what this proxy can do on any host, full
  stop. These rows matter most: they define the gap honestly.

Two closing cautions, because they apply to every row above.

**A functional pass is not a performance result.** Milestones M0–M5 and S1-F
show at most that something *ran*, not how it performed; their records are
held locally either way.

**The comparisons are bundles.** The two-host boot comparison differs in CPU
generation, kernel and clock at once; the guest-vs-native latency pair differs
in transport as well as partition. Neither isolates a single variable, and
[`digital-twin-design.md`](digital-twin-design.md) §1a explains why no
comparison in this project ever could.
