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
*software-layer proxy* (AWS Graviton) and a hardware-side validation
target (Jetson Orin Nano, same Tegra family as DRIVE Orin) — is
deliberately aligned with the customer-port angle: it represents the
kind of customer-side environment an SE would help bring up, profile,
and debug, *and* the cloud→target portability story that is half of
real customer-port work.

---

## Required ("What we need to see")

| JD verbatim | Repo artifact | Phase |
|---|---|---|
| "Strong knowledge of C/C++, QNX and/or Linux OS" | `ipc/proxy/safety_proxy.c` (QNX, qcc), `ipc/proxy/compute_proxy.c` (Linux, gcc); both C99 | 2 |
| "Understanding of CPU/GPU architectures, data structures, OS internals, multi-threading, **inter-process communications**, memory management techniques" | `ipc/` IPC proxy + benchmark; `docs/findings/phase-2-ipc-latency.md` (memory layout / packet sizing notes) | 2 |
| "Extensive hands-on experience in **BSP porting** and device driver internals" | `scripts/qnx/build-bsp.sh`; QNX virt BSP work (SDP 8.0 or 7.1, see `docs/bsp-selection.md`); `skills/bsp-porting/` paradigm | 1 |
| "Knowledge and experience working in **multicore/heterogenous SoCs**" | Graviton3 multi-core; QEMU SMP guest config in `scripts/qemu/start-*-vm.sh`; documented in `docs/architecture.md` | 1 |
| "Prior experience of working in software development in complex automotive systems" | Honest framing: this is a personal study project, not in-production automotive work. Documented as such in narrative. | — |
| "ECU bring-up, profiling, and debug" | Phase 1 bring-up (boot logs in `docs/findings/phase-1-bringup.md`); Phase 2 latency profiling (`results/`) | 1, 2 |
| "Excellent communication and organization skills, with a logical approach to problem solving" | `docs/interview-narrative.md`; per-phase findings docs; honest-gap section in `docs/nvidia-drive-os-comparison.md` | all |
| "Willingness to support customers/NVIDIA partners onsite" | Soft requirement; addressed in interview, not in code | — |
| "Fundamental knowledge on SoC architectures and on-chip components" | `docs/architecture.md` (Graviton3 SoC overview, QEMU virt machine model) | 1 |

---

## Standout ("Ways to stand out")

| ⭐ JD verbatim | Repo artifact | Phase |
|---|---|---|
| ⭐ "Experience with **QNX OS for Safety (QOS)**" | Honest gap: SDP ≠ QOS. Framed as POSIX-realtime proxy in `skills/qnx-safety/qos-vs-sdp.md` (feature & cert delta) | 0 |
| ⭐ "Exposure in **hypervisors and virtualization**" | `docs/nvidia-drive-os-comparison.md` (Phase 3): explicit gap analysis — QEMU+KVM ≠ Type-1 partition | 3 |
| ⭐ "Knowledge of **bootloaders**" | Phase 1: U-Boot for Linux guest; QNX IPL chain notes in `skills/bsp-porting/paradigm.md` | 1 |
| ⭐ "Experience with Automotive **SPICE** and/or **ISO 26262** standards" | Study notes only: `skills/aspice/`, `skills/iso-26262/`, applied FMEA examples in `skills/fmea/examples/`. **Honest framing: study artifacts, not certification evidence.** | 0–4 |
| ⭐ "Extensively supported customers both onsite and offsite" | Soft requirement; addressed in interview. Customer-port framing of this entire project speaks to the spirit of the bullet. | — |

---

## Honest gaps (not addressable by this portfolio)

The following JD elements **cannot** be demonstrated by a personal portfolio
project and should be addressed in interview, not by overclaiming:

- "5+ years of related work experience in a technical or automotive industry"
  → background-dependent; portfolio supplements but does not substitute
- "Camera/imaging/video/graphics/compute system" experience
  → not in scope for this project (no GPU partition; Graviton has no NVIDIA GPU)
- "Onsite customer support" history
  → behavioral / experiential

---

## Maintenance

When a phase is completed, update the **Repo artifact** column with concrete
links (e.g. `docs/findings/phase-2-ipc-latency.md#p99-results`) and replace
"Phase N" with "Done" in the **Phase** column.

When the target JD is updated (e.g. user pastes a different JD), regenerate
this table by running through the same template:

1. Required → required-table row per bullet
2. Standout → standout-table row per bullet (⭐)
3. Honest gaps → list anything the project structurally can't claim
