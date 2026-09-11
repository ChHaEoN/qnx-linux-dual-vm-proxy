# DRIVE OS comparison — what this proxy validates vs. reality

This document is the deliverable for **Phase 4**. It is the most
load-bearing artifact in the repo for the interview narrative: it
catalogues, dimension by dimension, what this proxy's legs, emulated
and native, can *actually* validate against the DRIVE OS reference
architecture and where the hard boundaries are.

It is intentionally not a sales pitch for the project. The goal is
calibration: a reader (or interviewer) should leave with a clear
sense of which of the project's claims are real, which are
qualitatively suggestive, and which are off-limits.

> **Status (2026-09-11):** wording corrected; no final verdicts yet.
> The Verdict column is a provisional, qualitative reading of the
> earlier legs. Final verdicts wait for the one measurement campaign
> on reference architecture v1. Measurements taken before v1 are
> architecture-version history
> ([plan, "Architecture versions and the measurement freeze"](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).
> Corrected today: the phase, the cloud host, the KVM wording for the
> HW twin, the silicon-family, workload, IPC, bootloader and real-time
> rows, and the placeholder cells. A native column was added as a
> placeholder.

---

## Concept-by-concept comparison (cloud twin and HW twin)

The "Cloud twin" column is architecture A1: the SDP 8.0 QNX Hypervisor
(`qvm`) hosting a single QNX guest inside QEMU **TCG** on the local
Windows PC. It was designed for AWS Graviton, but non-metal Graviton has
no `/dev/kvm` ([ADR-002](phase2-topology-decision.md);
[digital-twin-design.md](digital-twin-design.md) §1). The "HW twin"
column is A2: QEMU **TCG** beside L4T on the Jetson Orin Nano. Its KVM
boot is blocked by the GICv3/NISV defect ([orin-port.md](orin-port.md)
risk register). The "Native" column is A4, the QNX Hypervisor running
natively on the Orin, and then v1, which adds a Linux guest. Its cells
are placeholders until the v1 campaign. The ids are those of the plan's
[architecture table](orin-native-port-plan.md#architecture-versions).
Verdicts wait for the v1 measurement campaign.

| Concept | DRIVE OS implementation | Cloud twin (Windows PC, A1) | HW twin (Orin Nano, A2) | Native (Orin, A4 then v1) | Verdict |
|---|---|---|---|---|---|
| **VM partitioning** | NVIDIA Type-1 hypervisor on Tegra SoC | SDP 8.0 QHV (`qvm`) hosting **one** QNX guest under QEMU **TCG** (no `/dev/kvm` on cloud; [ADR-002](phase2-topology-decision.md)) | L4T host on A78AE; QEMU **TCG** (QNX) alongside native L4T; KVM boot blocked | _waits for the v1 campaign_ | **Validates** a **real `qvm` Type-1 partition boundary** (EL2↔EL1) on cloud, though TCG-emulated; **cannot** validate certified Type-1 isolation. The HW twin runs TCG, not KVM. |
| **Same Tegra silicon family** | Yes (Orin / Thor) | No — as built, an x86_64 Windows PC emulating `-cpu max` (the design host, Graviton, is Neoverse-V1) | Host **yes** — A78AE is the same family as DRIVE Orin's CCPLEX cores. The QNX side runs on QEMU's emulated `-cpu max` under TCG, not on the A78AE cores | _waits for the v1 campaign_ | Under TCG only the L4T host runs on Tegra-family cores; the QNX code does not. |
| **Dual-OS coexistence** | QNX Safety + Linux Compute on one Tegra | **No Linux on cloud** — QNX host + QNX guest only (heterogeneity moved to Orin per [ADR-002](phase2-topology-decision.md)) | QNX in QEMU + L4T native (host) on one Tegra-family SoC | _waits for the v1 campaign_ | **Validates dual-OS only on the HW twin (Orin)**; the cloud leg validates the partition *mechanism* (QNX↔QNX), not OS heterogeneity. |
| **Asymmetric workload** | Safety FuSa monitors / Compute DriveWorks | Console client/server (`qnx-host-client`, `qnx-server`); no real RT, no accelerators | A different client/server pair (a QNX TCP server and a native Linux client), the QNX side under TCG; A78AE has hardware RT support but L4T host is not RT-certified | _waits for the v1 campaign_ | **Partial** in both twins. Shape reproduced, substance not. |
| **Inter-VM IPC** | Shared memory + mailbox; sub-µs | host↔guest over `qvm` virtio-console vdev (TCG-emulated EL2 boundary; not hardware-timed — [ADR-002](phase2-topology-decision.md)) | virtio-net through `br0` under TCG; heterogeneous QNX↔Linux, with only the Linux client running directly on the silicon | _waits for the v1 campaign_ | The Phase 4 **twin diff** compares **non-identical** IPC paths (console/QNX↔QNX/TCG vs. virtio-net/QNX↔Linux/TCG). It mixes host, transport, OS pair and QEMU build, not host alone. It is architecture-version history; the v1 campaign runs the twin diff again. |
| **Boot sequencing** | HV brings up Safety → Compute with cross-checks | `qvm` host boots, then starts the QNX guest (`qvm @g2.conf`) — a real HV→guest sequence on cloud ([ADR-002](phase2-topology-decision.md)) | Same — L4T is up first (it's the host) and QNX is launched after | _waits for the v1 campaign_ | **Partial** in both — demonstrates workflow without enforcement primitive. |
| **Bootloader chain** | SecureBoot → measured boot → HV → guest IPLs | No Linux guest. QEMU loads the QNX Hypervisor host image directly (`-kernel`), and `qvm` loads the guest IFS from its config | JetPack UEFI for L4T host; QEMU loads the QNX IFS directly (`-kernel`) | _waits for the v1 campaign_ | **Cannot** validate certified chain on either twin. |
| **Real-time guarantees** | Certified RT on Safety partition | QNX RT inside guest; **TCG emulation** dominates timing on cloud (not hardware-timed; [ADR-002](phase2-topology-decision.md)) | QNX RT inside guest, under **TCG**, so this leg is not hardware-timed either ([digital-twin-design.md](digital-twin-design.md)); L4T host scheduler best-effort (A78AE silicon does have RT support) | _waits for the v1 campaign_ | **Cannot** validate end-to-end RT on either twin. |

---

## Quantitative data

> Waits for the v1 campaign. Earlier measurements are listed as
> history in the plan's
> [measurement inventory](orin-native-port-plan.md#measurement-inventory).
> No project figures appear here before then.

| Metric | DRIVE OS reference (public, approximate) | This proxy (measured) |
|---|---|---|
| QNX guest boot time | n/a (different SoC) | _waits for the v1 campaign_ |
| Linux guest boot time | n/a (different SoC) | _waits for the v1 campaign_ |
| Inter-VM IPC P50 round-trip | < 10 µs (shared mem regime) | _waits for the v1 campaign_ |
| Inter-VM IPC P99 round-trip | < 50 µs (shared mem regime) | _waits for the v1 campaign_ |
| Inter-VM IPC P99.9 round-trip | _bounded by RT guarantees_ | _waits for the v1 campaign_ |
| Sustained throughput (1 KB msg) | _hardware-bound_ | _waits for the v1 campaign_ |

The "DRIVE OS reference" column is for orientation only; figures
come from public NVIDIA materials, not from the project itself.

---

## How to read this document

- **"Validates"** means the proxy reproduces the engineering shape of
  the concept faithfully enough to be a useful study target.
- **"Partial"** means structural similarity exists but the substance
  (numbers, certifications, hardware behaviour) does not.
- **"Cannot"** means the concept is structurally outside what this
  proxy can do on any of its hosts, full stop.
  These rows are the most important ones for the interview narrative
  because they define the gap honestly.
