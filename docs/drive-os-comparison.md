# DRIVE OS comparison — what this proxy validates vs. reality

This document is the deliverable for **Phase 3**. It is the most
load-bearing artifact in the repo for the interview narrative: it
catalogues, dimension by dimension, what the QEMU dual-VM proxy can
*actually* validate against the DRIVE OS reference architecture and
where the hard boundaries are.

It is intentionally not a sales pitch for the project. The goal is
calibration: a reader (or interviewer) should leave with a clear
sense of which of the project's claims are real, which are
qualitatively suggestive, and which are off-limits.

> **Status:** scaffold. Verdicts will harden as Phase 1 and Phase 2
> measurements come in. Quantitative numbers below are placeholders.

---

## Concept-by-concept comparison (cloud twin and HW twin)

The "Cloud twin" column is QEMU/KVM on AWS Graviton; the "HW twin"
column is QEMU/KVM on Jetson Orin Nano. Verdicts are filled in
during Phase 4 once both twins have been measured.

| Concept | DRIVE OS implementation | Cloud twin (AWS) | HW twin (Orin Nano) | Verdict |
|---|---|---|---|---|
| **VM partitioning** | NVIDIA Type-1 hypervisor on Tegra SoC | KVM + Linux host on Graviton; two QEMU processes | KVM + L4T host on A78AE; QEMU(QNX) alongside native L4T | **Validates** concept of co-resident OSes; **cannot** validate certified Type-1 isolation. HW twin is structurally closer because L4T = real Tegra-family Linux. |
| **Same Tegra silicon family** | Yes (Orin / Thor) | No — Graviton is Neoverse-V1 | **Yes** — A78AE is the same family as DRIVE Orin's CCPLEX cores | HW twin **uniquely validates** SoC-family parity that the cloud twin cannot. |
| **Dual-OS coexistence** | QNX Safety + Linux Compute on one Tegra | QNX in QEMU + Ubuntu in QEMU on one host | QNX in QEMU + L4T native (host) on one Tegra-family SoC | **Validates** in both twins; HW twin is closer to "Linux on real Tegra" reality. |
| **Asymmetric workload** | Safety FuSa monitors / Compute DriveWorks | Same client/server code, no real RT, no accelerators | Same client/server code on real silicon; A78AE has hardware RT support but L4T host is not RT-certified | **Partial** in both twins. Shape reproduced, substance not. |
| **Inter-VM IPC** | Shared memory + mailbox; sub-µs | virtio-net through `br0`; hundreds of µs to low ms expected | virtio-net through `br0`; **same code path** but host CPU + scheduler differ | Phase 4 **twin diff** is the load-bearing measurement here — what changes when only the host changes? |
| **Boot sequencing** | HV brings up Safety → Compute with cross-checks | Independent QEMU processes; ordering enforced by launch scripts | Same — L4T is up first (it's the host) and QNX is launched after | **Partial** in both — demonstrates workflow without enforcement primitive. |
| **Bootloader chain** | SecureBoot → measured boot → HV → guest IPLs | UEFI for Linux guest; QNX IPL via mkqnximage | JetPack UEFI for L4T host; QNX IPL via mkqnximage same as cloud | **Cannot** validate certified chain on either twin. |
| **Real-time guarantees** | Certified RT on Safety partition | QNX RT inside guest; KVM host scheduler best-effort | QNX RT inside guest; L4T host scheduler best-effort (A78AE silicon does have RT support) | **Cannot** validate end-to-end RT on either twin. |

---

## Quantitative data

> Numbers will be filled in after Phase 1 (boot times) and Phase 2
> (round-trip latency benchmarks). Empty placeholders left here so
> the table layout stays stable.

| Metric | DRIVE OS reference (public, approximate) | This proxy (measured) |
|---|---|---|
| QNX guest boot time | n/a (different SoC) | _TBD Phase 1_ |
| Linux guest boot time | n/a (different SoC) | _TBD Phase 1_ |
| Inter-VM IPC P50 round-trip | < 10 µs (shared mem regime) | _TBD Phase 2_ |
| Inter-VM IPC P99 round-trip | < 50 µs (shared mem regime) | _TBD Phase 2_ |
| Inter-VM IPC P99.9 round-trip | _bounded by RT guarantees_ | _TBD Phase 2_ |
| Sustained throughput (1 KB msg) | _hardware-bound_ | _TBD Phase 2_ |

The "DRIVE OS reference" column is for orientation only; figures
come from public NVIDIA materials, not from the project itself.

---

## How to read this document

- **"Validates"** means the proxy reproduces the engineering shape of
  the concept faithfully enough to be a useful study target.
- **"Partial"** means structural similarity exists but the substance
  (numbers, certifications, hardware behaviour) does not.
- **"Cannot"** means the concept is structurally outside what a
  software-layer proxy on a non-Tegra arm64 host can do, full stop.
  These rows are the most important ones for the interview narrative
  because they define the gap honestly.
