# DRIVE OS comparison — what this proxy validates vs. reality

This document is the deliverable for **Phase 4**. It catalogues, dimension by
dimension, what this project's legs can *actually* validate against the public
DRIVE OS reference architecture, and where the hard boundaries are.

It is deliberately not a sales pitch. The goal is calibration: a reader should
leave knowing which claims here are real, which are qualitatively suggestive,
and which are off-limits.

> **Status (2026-09-20): the verdicts are written.** They waited on a
> measurement campaign; owner decision **OD10** settled that campaign's shape
> (A6 measures under KVM only, the TCG twin legs are withdrawn) and every A6
> measurement has now run. What remains open is sample sizes, which changes no
> verdict below. Earlier wording and its corrections are in
> [`findings.md`](findings.md); this file states the current reading and does
> not accumulate strike-throughs.

## The short version

**No dimension earns "Validates". Six are Partial and two are Cannot.**

That is the honest result and it is worth stating before the table rather than
leaving a reader to count. The project reproduces the *shape* of most of the
DRIVE OS arrangement and the *substance* of none of it — because substance
here means certification, bounded latency, a root of trust, and a Type-1
hypervisor that owns the machine, and this project has none of those. Two
dimensions are structurally out of reach on any host it will ever have.

The most consequential single fact: **there will never be a QNX Hypervisor
number in this project.** QHV needs EL2 and ARM KVM does not nest on A78AE, so
it cannot run under KVM; OD10 withdrew the TCG legs that were its only emulated
route; and the native A4 figures are unpublished under NC QDL v7 4.6(i). The
hypervisor result is permanently a set of **functional passes with no timing**.

---

## Concept-by-concept comparison

Columns are the project's architecture ids, from the plan's
[architecture table](orin-native-port-plan.md#architecture-versions):

- **A1** — cloud leg: SDP 8.0 QHV (`qvm`) hosting one QNX guest under QEMU
  **TCG**. Designed for AWS Graviton; as built it ran on the owner's local
  x86_64 Windows PC, because non-metal Graviton exposes no `/dev/kvm`
  ([ADR-002](phase2-topology-decision.md)). History.
- **A2** — Orin plain leg: QEMU **TCG** beside L4T, QNX↔Linux IPC over
  `br0`/`tap-qnx`. History. Its IPC run used a *rebuilt* IFS.
- **A4** — the QNX Hypervisor running **natively at EL2** on the Orin's own
  A78AE cores, no QEMU. M0–M5 met functionally; figures unpublished. Superseded
  as a direction on 2026-09-18 because no OS can use the GPU under it. The
  two-guest run (a Linux guest and the QNX guest under one `qvm`) is **S1-F/B5**,
  which the plan assigns to **A5**, not A4.
- **A6** — **current**: L4T on the metal owning the GPU, QNX as a **KVM guest**
  beside it.

| Concept | DRIVE OS | A6 — current (QNX as a KVM guest on the Orin) | Verdict |
|---|---|---|---|
| **VM partitioning** | Type-1 hypervisor on a Tegra SoC, safety-certified | QNX as a KVM guest (`-cpu host -enable-kvm`, 2 of 6 vCPU) beside L4T: a real hardware EL2/EL1 boundary, but **Linux is the supervisor and owns the guest's memory**. No Type-1 layer; QHV cannot run under KVM. | **Partial** — a real Type-1 `qvm` did run at EL2 on A78AE (A4 functional passes; two guests at A5/S1-F, one observation), but it is **uncertified** — SDP 8.0 is not QNX OS for Safety — **no isolation, containment or freedom-from-interference result exists**, and no QHV number exists or ever will (OD10). |
| **Same Tegra silicon family** | Yes (Orin / Thor) | Both partitions on Tegra234: L4T on the metal with the real Ampere iGPU, QNX on 2 of 6 A78AE cores under `-cpu host` — no emulated CPU. The guest still sees QEMU's generic `virt` machine. | **Partial** — the QNX code finally runs on Tegra234's own cores, but on a 6-core Jetson SKU (not DRIVE Orin's 12, and nothing here touches Thor), behind `virt`: no Tegra peripheral, no BPMP, no SMMU, no GPU. **Not a QNX-supported configuration** — every A6 arm boots a `startup-qemu-virt` rebuilt in this repo; the shipped one still hangs. |
| **Dual-OS coexistence** | QNX Safety + Linux Compute on one Tegra, as peers under the HV | L4T on the metal with the GPU (sustained FMA at ~99% GR3D) and QNX as a KVM guest on the same A78AE cores; cross-partition service over a real `br0`/`tap-qnx` bridge and over DDS. | **Partial** — the two OSes do coexist on one Tegra234 and exchange work, but **they are never peers**: on the only measured leg Linux is the host and owns the QNX guest's memory, so there is no Linux Compute *partition*. The leg where they are peers (A5/S1-F) has no GPU and unpublished figures. **No leg has both.** |
| **Asymmetric workload** | Safety FuSa monitors / Compute DriveWorks | L4T holds the iGPU (a TensorRT inference and a synthetic FMA load) while the QNX guest only judges claims — ACCEPT/REJECT over TCP and over DDS. | **Partial** — asymmetric *in kind*, but the rules are legible plausibility checks whose thresholds `monitor.c` itself says were chosen for the demo and **not derived from any hazard analysis**; no ASIL, no RT bound, no DriveWorks-class load. **The privilege is inverted**: Compute owns Safety's memory, and QNX can touch no accelerator on Tegra234 at all. |
| **Inter-VM IPC** | Shared memory + mailbox, sub-µs | First hardware-timed cross-partition round trip: a 64-byte frame from L4T to the guest's monitor over a real bridge under KVM, **p50 0.172 ms, p99 0.461 ms** (n=3000/arm, governor pinned, 2026-09-19). | **Partial** — a real cross-partition round trip is timed on silicon at last, but it is **TCP over virtio-net, not shared memory**, and it is **host↔guest, not VM↔VM**: there is no hypervisor in the path and Linux owns the other side. It is not the quantity DRIVE OS's figure names. No shared-memory or mailbox figure exists at any architecture, and per OD10 none ever will. |
| **Boot sequencing** | HV brings up Safety → Compute with cross-checks | L4T boots first — it is the host — then QNX starts as a KVM guest launched by a shell command from L4T userspace. Bring-up segment-timed, n=5, on two hosts. | **Partial** — a real ordered two-partition bring-up exists, but **the order is inverted** (Compute must be fully up first, because it is the host), nothing enforces it, and there are **no cross-checks, no health gate and no fail-to-safe**. Nothing about *sequencing* was timed: the clock starts at QEMU exec, so the Compute side's own boot is never measured. |
| **Bootloader chain** | SecureBoot → measured boot → HV → guest IPLs | JetPack UEFI with Secure Boot **off** → L4T → QEMU `-kernel` loads the IFS directly. No guest IPL and no HV stage. New in A6: the project owns the startup board stage. | **Cannot** — no root of trust at any stage on any leg: nothing signed, nothing measured, no fuse- or TPM-anchored anchor. A6 has *fewer* stages than DRIVE OS, not more. (The second host in the 2026-09-20 comparison, AWS `a1.metal`, has no JetPack UEFI and no L4T at all — a different pre-QEMU chain entirely.) |
| **Real-time guarantees** | Certified RT on the Safety partition | First hardware-timed QNX latency: idle **p50 0.184 ms, p99 0.475 ms** (governor pinned). Host CPU load moves p50 **+53.9%**; the largest samples run ~10–12× the median. | **Cannot** — no bound, no WCET argument, no deadline, and the guest is **never configured for real time** (`monitor.c` is pure POSIX at default priority, so QNX's priority scheme and FIFO scheduling are untouched by every figure here). Its vCPU threads are scheduled by a general-purpose Linux kernel, and the saturation run measures **interference reaching the Safety partition**, not freedom from it. |

---

## Quantitative data

The reference column is for orientation only and comes from public NVIDIA
material, not from this project.

**Read the IPC rows carefully.** DRIVE OS's inter-VM figure is a VM↔VM round
trip across a Type-1 hypervisor over shared memory. This project has no such
figure and, per OD10, never will — so those rows stay empty rather than being
filled with a number that measures something else. The figure this project does
have is a *host↔guest* round trip over TCP and virtio-net, and it is reported
on its own row against no reference.

| Metric | DRIVE OS reference (public, approximate) | This project (measured) |
|---|---|---|
| QNX guest boot time, to guest banner | n/a — different SoC | **4747.0 ms** (Orin Nano) / **4519.0 ms** (AWS `a1.metal`), median of n=5, under KVM, byte-identical IFS, 2026-09-20. **~89% of each is a fixed software timeout**, not host-dependent work; see [the run record](../results/orin-native-port/20260920T-kvm-twin/results.md). |
| Linux guest boot time | n/a — different SoC | Booted under native `qvm` (S1-F, rungs B3/B4, 2026-09-17) and held ten minutes. **Figures unpublished** under NC QDL v7 4.6(i). |
| Inter-VM IPC P50 (VM↔VM, shared memory) | < 10 µs | **none, and none will exist.** The one shared-memory path (`qvm vdev shmem`, A1) was functional-only, TCG-only and never timed; its notify half was deliberately skipped. OD10 removed the last route to a hypervisor-path figure. |
| Inter-VM IPC P99 (VM↔VM, shared memory) | < 50 µs | none — as above |
| Inter-VM IPC P99.9 (VM↔VM, shared memory) | bounded by RT guarantees | none — as above |
| **Host↔guest round trip under KVM** (this project's own quantity; **no DRIVE OS counterpart**) | — | **p50 0.172 ms, p99 0.461 ms, p99.9 0.598 ms**, n=3000 per arm × 2 arms, governor pinned, 2026-09-19. 64-byte frame, L4T → QNX guest monitor over `br0`/`tap-qnx`/virtio-net. A **whole-system** round trip — Linux stack, bridge, guest `io-sock`, guest scheduler — not a QNX-attributable latency. |
| The same program, natively on L4T (control) | — | **p50 0.045 ms, p99 0.081 ms**, same board, same unmodified `monitor.c`, loopback. The difference is transport *and* partition together, not the partition alone. |
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

**A functional pass is not a result.** M0–M5 and S1-F are real and were hard,
but they show that something *ran*, not how it performed. Where a row rests on
one, it says so.

**The measured numbers are bundles.** The two-host boot comparison differs in
CPU generation, kernel and clock at once; the guest-vs-native latency pair
differs in transport as well as partition. Neither isolates a single variable,
and [`digital-twin-design.md`](digital-twin-design.md) §1a explains why no
comparison in this project ever could.
