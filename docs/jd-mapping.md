# NVIDIA JD mapping — AVOS / DRIVE OS Software Engineer (customer-facing)

> Each row maps a verbatim JD requirement to a concrete repo artifact
> (file, folder, or planned phase deliverable). Standout-bullets (the
> "Ways to stand out" section of the JD) are flagged ⭐.

---

## Role context

> "NVIDIA is looking for a highly motivated Software Engineer to join its
> dynamic, collaborative and fast-paced **customer interfacing** organization.
> AVOS is an adaptation of DRIVE OS for Nvidia autonomous vehicle application
> stack. In this role, you will be supporting our customers closely to adapt
> NVIDIA's AVOS or DRIVE OS software stack to the program requirements."

This portfolio's framing — a **Digital Twin design** with a cloud-side
*software-layer proxy* (designed for AWS Graviton; as built, QEMU TCG on
a local Windows PC) and a hardware-side validation
target (Jetson Orin Nano, same Tegra family as DRIVE Orin) — is
deliberately aligned with the customer-port angle: it represents the
kind of customer-side environment an SE would help bring up, profile,
and debug, *and* the cloud→target portability story that is half of
real customer-port work.

---

## Required ("What we need to see")

| JD verbatim | Repo artifact | Phase |
|---|---|---|
| "Strong knowledge of C/C++, QNX and/or Linux OS" | `ipc-test/` — QNX server and host-client source (qcc) and `ipc-test/linux-client/` (Linux, gcc); C99 | 2, 3 |
| "Understanding of CPU/GPU architectures, data structures, OS internals, multi-threading, **inter-process communications**, memory management techniques" | `ipc-test/` IPC client/server and benchmark, including the `vdev shmem` probes; IPC findings in `docs/findings.md` | 2, 3 |
| "Extensive hands-on experience in **BSP porting** and device driver internals" | `scripts/build-qnx-ifs.bat`; the native Tegra234 startup board directory `orin-native/startup/t234-orin-nano/` (Phase 3b); `docs/bsp-selection.md`; `skills/bsp-porting/` paradigm | 1, 3b |
| "Knowledge and experience working in **multicore/heterogenous SoCs**" | Native SMP bring-up on the Orin's Cortex-A78AE cores (M2, `docs/orin-native-port-plan.md`); QEMU SMP guest config in `scripts/launch-qhv-tcg.ps1` and `scripts/orin/launch-qhv-on-orin-tcg.sh` | 1, 3b |
| "Prior experience of working in software development in complex automotive systems" | Honest framing: this is a personal study project, not in-production automotive work. Documented as such in narrative. | — |
| "ECU bring-up, profiling, and debug" | Phase 1 bring-up (curated boot logs in `logs/sample-boot/`, findings in `docs/findings.md`); Phase 2 latency profiling (`results/`); Phase 3b native bring-up (`docs/orin-native-port-plan.md`) | 1, 2, 3b |
| "Excellent communication and organization skills, with a logical approach to problem solving" | `docs/interview-narrative.md`; per-phase findings docs; honest-gap section in `docs/drive-os-comparison.md` | all |
| "Willingness to support customers/NVIDIA partners onsite" | Soft requirement; addressed in interview, not in code | — |
| "Fundamental knowledge on SoC architectures and on-chip components" | `docs/architecture.md` (DRIVE OS partition model and the twin topology); Tegra234 GIC, PSCI and memory-map claims in `docs/orin-native-port-plan.md` §2 | 1, 3b |

---

## Standout ("Ways to stand out")

| ⭐ JD verbatim | Repo artifact | Phase |
|---|---|---|
| ⭐ "Experience with **QNX OS for Safety (QOS)**" | Honest gap: SDP ≠ QOS. Framed as a POSIX-realtime proxy in the README limitations table and `docs/architecture.md`; a dedicated QOS-vs-SDP study note is not written yet | 0 |
| ⭐ "Exposure in **hypervisors and virtualization**" | The QNX Hypervisor (an uncertified Type-1), emulated under QEMU TCG (cloud leg, ADR-002) and running natively on the Orin (Phase 3b, `docs/orin-native-port-plan.md`); gap analysis against DRIVE OS in `docs/drive-os-comparison.md` (Phase 4) | 1, 3b, 4 |
| ⭐ "Knowledge of **bootloaders**" | Phase 3b: the kexec entry shim from L4T and the planned M5-F UEFI Shell cold boot (`docs/orin-native-port-plan.md` §3 and M5); no U-Boot and no Linux guest boot chain yet | 3b |
| ⭐ "Experience with Automotive **SPICE** and/or **ISO 26262** standards" | Study notes only: `skills/aspice/`, `skills/iso-26262/`, applied FMEA examples in `skills/fmea/examples/`. **Honest framing: study artifacts, not certification evidence.** | 0–4 |
| ⭐ "Extensively supported customers both onsite and offsite" | Soft requirement; addressed in interview. Customer-port framing of this entire project speaks to the spirit of the bullet. | — |

---

## Honest gaps (not addressable by this portfolio)

The following JD elements **cannot** be demonstrated by a personal portfolio
project and should be addressed in interview, not by overclaiming:

- "5+ years of related work experience in a technical or automotive industry"
  → background-dependent; portfolio supplements but does not substitute
- "Camera/imaging/video/graphics/compute system" experience
  → not in scope for this project (no GPU partition; the Orin's GPU is not exercised, and GPU pass-through is research only)
- "Onsite customer support" history
  → behavioral / experiential

---

## Maintenance

When a phase is completed, update the **Repo artifact** column with concrete
links (e.g. a dated entry in `docs/findings.md`) and replace
"Phase N" with "Done" in the **Phase** column.

When the target JD is updated (e.g. user pastes a different JD), regenerate
this table by running through the same template:

1. Required → required-table row per bullet
2. Standout → standout-table row per bullet (⭐)
3. Honest gaps → list anything the project structurally can't claim
