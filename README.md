# qnx-linux-dual-vm-proxy

A **Digital Twin design** of NVIDIA DRIVE OS dual-VM partitioning — a QNX
safety side beside a Linux general-purpose side — built on a Jetson Orin Nano
dev kit and a Windows PC instead of DRIVE hardware. Nothing in it is certified.

[docs/findings.md](docs/findings.md) is the authoritative, dated ground truth;
everything below is a summary that can lag it. Ids such as A4, M5-F and S1-F
are explained under [Reading the ids](#reading-the-ids).

<!-- The Phase badge is GENERATED from the Status table by
     scripts/ci/render_badges.py and checked on every push by
     .github/workflows/claims-gate.yml. Do not hand-edit it: change the
     Status table and re-run `python scripts/ci/render_badges.py --write`.
     It names the phase only. Architecture ids (A1-A6) move independently
     and belong in the body, which is OVERWRITE-ONLY: replace the sentence,
     never annotate it -- the gate fails this file on a strike-through. That
     separation is why the badge once went stale advertising "native QHV"
     after that architecture had been superseded. -->
![Phase](https://img.shields.io/badge/Phase-3b-blue)
[![tooling](https://github.com/ChHaEoN/qnx-linux-dual-vm-proxy/actions/workflows/tooling.yml/badge.svg)](https://github.com/ChHaEoN/qnx-linux-dual-vm-proxy/actions/workflows/tooling.yml)
[![claims-gate](https://github.com/ChHaEoN/qnx-linux-dual-vm-proxy/actions/workflows/claims-gate.yml/badge.svg)](https://github.com/ChHaEoN/qnx-linux-dual-vm-proxy/actions/workflows/claims-gate.yml)
![License](https://img.shields.io/badge/License-MIT-blue)
![Arch](https://img.shields.io/badge/arch-aarch64-lightgrey)

---

## At a glance

- **What it is.** A study of the *software layer* under DRIVE OS-style
  partitioning: BSP bring-up, hypervisor host and guest, IPC, host→target
  portability. Not a reproduction of DRIVE OS, and not a certified hypervisor.

- **What runs now (A6).** L4T on the metal owning the Ampere GPU, with QNX SDP
  8.0 as a **KVM guest** beside it on the Orin's own Cortex-A78AE cores. The
  guest boots only with a `startup-qemu-virt` rebuilt in this repo — the one
  QNX ships hangs under KVM — so it is **not a QNX-supported configuration**.

- **What was achieved and superseded (A4, A5).** The QNX Hypervisor ran
  natively at EL2 with no QEMU, hosting a QNX guest and a stock Linux kernel.
  Every rung is a functional pass and none is timed. It is not withdrawn: it
  stopped being the direction because **under it no OS can use the GPU**.

- **What has been measured.** A1–A3 IPC figures are TCG throughout — read them
  as "both mechanisms are alive", never as a host-speed result. A6 figures are
  on real silicon with QNX as a KVM guest: GPU concurrency, interference and
  saturation, a two-host boot comparison against AWS `a1.metal`, and an
  attribution ladder that splits the 182 µs cross-partition round trip into
  53 µs of instrument, 3 µs of bridge and **126 µs of guest crossing**. That
  ladder ran before the idle-state control existed, with the CPU's deep idle
  state at its default (enabled, not recorded); in a later pair of runs,
  disabling it moved the round trip's median about 2% and more than halved the
  idle p99 ([record](results/orin-native-port/20260921T-a6-orin/results.md)).
  With that state disabled, every CPU-load thread pinned per core and QEMU
  pinned as a set to cores 0–2 (k = 12, paired within rounds), one busy thread
  costs **20 µs** more at p50 on QEMU's core 0 than on core 5, and loading
  QEMU's cores 0 and 1 costs **164 µs** over idle — more than loading all three
  of its cores (**58 µs**) or all six cores (**77 µs**). This design does not
  separate QEMU's cores from core 0, and which thread waits, and why cores 0
  and 1 cost more than all three, is not resolved. Over UDP, on the ladder's
  rungs plus a null-echo rung, beside TCP in one run on a new guest image and
  boot (2026-09-22, k = 12, paired), the round trip to the guest's monitor is
  **20 µs** faster at p50 and the guest crossing itself **8 µs** faster —
  against that run's own TCP rungs, not the 182 and 126 µs above
  ([record](results/orin-native-port/20260922T-a6-orin-udp/results.md)). The
  8 µs is net of the Linux side's change, how it divides between QNX's stack
  and the virtio path is not resolved, and the tail shows no resolved
  difference. Through shared memory — QEMU's `ivshmem`, one slot, both ends
  polling (2026-09-22, k = 12, paired, beside TCP and UDP on another new image
  and boot) — the round trip to the guest's monitor takes **5 µs** at p50,
  **180 µs** less than over TCP in the same run, and crossing into the guest
  adds nothing measurable to it (paired against the same kind of slot between two
  host processes: **0 µs** to the nearest microsecond, band ±0.3 µs). It is
  a polling path: each end holds a core or a vCPU while it waits, so it is not
  a like-for-like comparison with the interrupt-driven socket paths, and it is
  host↔guest, not VM↔VM
  ([record](results/orin-native-port/20260922T-a6-orin-shm/results.md)).
  Notified instead of polled, so that both ends sleep as over TCP, the round
  trip to the guest's monitor takes **125 µs** when the guest answers through
  `ivshmem`'s doorbell, **92 µs** less than TCP's 217 µs on that boot, and the
  doorbell is **37 µs** faster than answering over the console. The guest is
  kicked awake over a virtio console: QEMU 6.2's doorbell interrupts a guest only
  by MSI-X, which nothing here enables in this guest. Before measuring, the run
  checks that KVM handles the doorbell in the kernel rather than in QEMU's
  userspace (10 000 doorbells, 4 userspace exits). Pairing does not remove three
  things from these contrasts: KVM's halt polling ended 18% of the guest's halts
  in the doorbell arm against 3% over TCP, QEMU's main thread queued 4.6 µs per
  exchange in the doorbell arm only, and TCP ran 32–38 µs slower on that boot
  than on the two before it, so the 92 µs may include up to that much
  ([record](results/orin-native-port/20260922T-a6-orin-kick/results.md)).

- **What it cannot show.** No certified Type-1 isolation, no freedom from
  interference, no real-time guarantee, no safety certification, no accelerator
  path for QNX. **No hardware-timed *hypervisor* number exists or ever will**:
  QHV needs EL2, ARM KVM does not nest on A78AE, and the TCG legs that were its
  only emulated route were withdrawn on 2026-09-20. See
  [Known limitations](#known-limitations-honest-framing) and
  [drive-os-comparison.md](docs/drive-os-comparison.md), whose verdicts are six
  Partial, two Cannot and no Validates.

- **What is next.** Other IPC paths across the same boundary (owner decision
  OD12): UDP and shared memory over `ivshmem`, polled and notified, have run
  (above). A doorbell into the guest would need MSI-X in the guest, which was not
  attempted, and a SOME/IP arm is proposed, not decided. The A6 campaign adopted on 2026-09-21
  ([measurement-design.md](docs/measurement-design.md): k ≥ 12 repetitions
  rather than more samples, because run-to-run variation here is ~69× the
  sampling noise at p50) has run in part — the ladder, interference and
  saturation. Still to run from it, not yet scheduled: guest-side timestamps,
  the frame-size and offered-rate sweeps, and the boot-timeout falsification.

---

## What is machine-checked

"Never write *it works* without a log, a number, or a diff" catches a figure
that was never measured. It does not catch one that was true when written and
drifted — two published figures here were already found wrong that way, by
hand. CI closes that class.

**Fails the build:** every figure this README quotes, re-derived from the
committed data in `logs/` and `results/` through the project's own
`scripts/twin/delta.awk`; units, separately from values; asserted claims the
data does not support, against a reviewable
[denylist](scripts/ci/claim-denylist.txt) matched per sentence so denials stay
legal; the same denylist over `scripts/**`, `orin-native/**` and
`ipc-test/**`, whose files are instructions a reader executes; a strike-through in this file, which states current state and
is rewritten rather than annotated; the Phase badge against the Status table;
and the GitHub "About" field against its pin in
[docs/repo-description.md](docs/repo-description.md).

**Reported, never fails:** the same denylist over `docs/**` and `results/**`,
which carry the project's superseded record on purpose.

**Never done:** CI measures nothing and gates on no absolute number. A shared
public runner cannot produce a meaningful timing for this target. Nothing QNX
is built, linked or booted there.

---

## Known limitations (honest framing)

The whole point of the project is to be precise about what a software-layer
proxy can and cannot demonstrate.

**The honest-framing rule**, which documents here cite by name: every claim
is paired with what it does *not* demonstrate, and nothing is called working
without a log, a number or a diff behind it. Where a limit is known but not
quantified, it is named as unquantified rather than left out.

This table is the load-bearing part:

| DRIVE OS feature | Limitation in this project |
|---|---|
| NVIDIA Hypervisor (Type-1) | The cloud leg (A1, history) ran the SDP 8.0 QNX Hypervisor (`qvm`) hosting one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (non-metal Graviton exposes no `/dev/kvm`; `*.metal` does, since 2026-09-19) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. The Orin plain leg (A2) was designed for host-mediated KVM, which GICv3/NISV blocked when it ran, so it ran under TCG too; an IFS whose `startup-qemu-virt` this repo rebuilt does boot under `-enable-kvm` now, but A2 is not re-run, nothing was timed, and that rebuild is not a QNX-supported configuration. The native leg (A4) ran the QNX Hypervisor at EL2 on the Orin's own cores with no QEMU — a real hypervisor on silicon, but not certified and not NVIDIA's: Experimental Software on a consumer dev kit. **Under A6, the current architecture, there is no Type-1 layer at all**: the partitioner is KVM and Linux — the largest TCB on the board — owns the QNX guest's memory. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | The cloud leg's as-built runtime CPU was the local x86_64 Windows host (Graviton3 was the design intent). The Orin plain leg (A2, history) *did* run on Tegra234 silicon, but its QNX guest saw QEMU's generic `virt` machine — no Tegra-specific peripherals, no SoC-internal interconnect. The native leg runs the QNX host directly on Tegra234 through this repo's own startup code (console, interrupt controller, timers, CPU bring-up). It has no storage, network, display, GPU, SMMU or PCIe drivers, and its guest sees qvm's virtual devices, not Tegra peripherals. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU virt machine. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | No leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano has an Ampere iGPU but it is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. On the native leg the S1 guest that has now run is Linux without a GPU. GPU pass-through is a later target, studied on a separate unpublished research track; no GPU stage has started. |
| Real-time guarantees | The QEMU-TCG legs (A1 to A3, history) were emulation-bound, not hardware-timed, and the Orin plain leg added observable host-scheduler jitter on top. **The TCG twin legs were withdrawn by owner decision on 2026-09-20; A6 measures under KVM only.** The native leg's timings are unpublished and not campaign-grade: the CPU frequency is wherever BPMP and Linux left it and the clock is recorded as unverified. On A6 the guest is **never configured for real time** — the monitor is pure POSIX at default priority — and its vCPU threads are scheduled by a general-purpose Linux kernel, so host CPU load measurably moves its round trip. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg (A1, history): host↔guest over the `qvm` virtio-console vdev — it crosses the EL2/EL1 boundary, but TCG-emulated, so the latency measures emulation cost, not transport cost. Orin plain leg (A2, history): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net, also TCG-emulated, so not hardware-timed either; these numbers stand exactly as recorded and are not re-run. **A6 does have hardware-timed cross-partition IPC**: a 64-byte frame from L4T to the guest's `qnx-safety-monitor` over a real `br0`/`tap-qnx` bridge, governor pinned — p50 0.172 ms under the earlier n = 3000 / k = 2 design; an attribution ladder (2026-09-21, k = 12) puts a 182 µs round trip at 126 µs guest crossing, 3 µs bridge and 53 µs instrument. Since 2026-09-22 A6 also has shared-memory figures over QEMU's `ivshmem`, host↔guest: polled, 4.5 µs at p50 from L4T to the guest's monitor; and notified, with the guest kicked over a virtio console and answering through the `ivshmem` doorbell, 125 µs. Neither is DRIVE OS's VM↔VM shared memory and mailbox, and no doorbell reaches this guest (QEMU 6.2 would need MSI-X in it for that). What does **not** exist under KVM is an IPC figure over *this row's* transport, the `qvm` shared-memory/virtio-console path, because that path belongs to the QNX Hypervisor and QHV cannot run under KVM at all. Native leg (A4): host to guest over virtio-console under `qvm` on real cores; figures unpublished. **No hardware-timed *hypervisor* number exists on any leg and none ever will.** No sourced DRIVE OS IPC figure is in the repo, so no gap is quantified here. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. The native leg's UEFI cold boot (M5-F) is an EFI loader of ours launched by hand from the firmware's Shell: not a supported, certified or unattended boot path. |

These are deliberate. Documenting them precisely is the engineering point.

---

## Architecture

**A6, the current arrangement.** Linux is on the metal and keeps the GPU; QNX
is a KVM guest beside it. The partition boundary is real hardware EL2/EL1, but
the supervisor is Linux — there is no Type-1 layer, because QHV needs EL2 and
ARM KVM does not nest on A78AE.

```
 Jetson Orin Nano — Tegra234, 6 x Cortex-A78AE, Ampere iGPU
 ┌──────────────────────────────────────────────────────────────────┐
 │  L4T / JetPack 6  — EL1, owns the machine                        │
 │                                                                  │
 │   TensorRT / CUDA ────────────────► Ampere iGPU                  │
 │                                       QNX never touches it       │
 │                                                                  │
 │   latency probe on L4T                                           │
 │        │ 64-byte frame, TCP :7100                                │
 │        ▼                                                         │
 │   br0 ── tap-qnx                                                 │
 │        │ virtio-net                                              │
 │        ▼                                                         │
 │  ┌────────────────────────────────────────────────────┐          │
 │  │ QEMU + KVM  — 2 of 6 vCPU, 1 GB                    │          │
 │  │  ┌──────────────────────────────────────────────┐  │          │
 │  │  │  QNX SDP 8.0 guest — EL1, on A78AE           │  │          │
 │  │  │  procnto · io-sock · qnx-safety-monitor      │  │          │
 │  │  │  boots only with a startup we rebuilt        │  │          │
 │  │  └──────────────────────────────────────────────┘  │          │
 │  └────────────────────────────────────────────────────┘          │
 └──────────────────────────────────────────────────────────────────┘

 measured round trip, L4T to the guest and back — 182 us at p50
   53 us  rung A: probe + host server, loopback
    3 us  br0
  126 us  the crossing: tap, virtio-net, io-sock, scheduler, monitor
```

**Why not a Type-1 hypervisor here.** The QNX Hypervisor did run natively at
EL2 on these cores, hosting a QNX guest and a stock Linux kernel. That
arrangement is not withdrawn — it is simply no longer the direction, because
**under it no OS can use the GPU** on Tegra234: the iGPU has no SMMU stream ID,
and its clock, reset and power go through BPMP, for which QNX has no client
driver. Earlier architectures are closed and not redone; each record keeps the
id of the version it ran on.

Two items stay open on their own: the `qvm`/TCG virtio-queue stall, never
root-caused and only survivable; and the GICv3/NISV defect, open in QNX's
**shipped** binary only, which the owner decided not to file.

Every QNX image is built on an x86_64 host — SDP 8.0 ships Windows and Linux
x86_64 host tools, no arm64 and no macOS.

Detail: [architecture.md](docs/architecture.md) ·
[digital-twin-design.md](docs/digital-twin-design.md) ·
[drive-os-comparison.md](docs/drive-os-comparison.md).

---

## Status

| Phase | Status | Evidence |
|---|---|---|
| **0** — Bootstrap, BSP research, twin re-scope | ✅ done | [bsp-selection.md](docs/bsp-selection.md) |
| **1** — Cloud twin bring-up: QHV `qvm` + QNX guest under TCG | ✅ done | [boot log](logs/sample-boot/qhv-tcg-host-and-guest-boot.log) |
| **2** — Cloud twin IPC + latency | ✅ **closed as A1 history** — real P50/P99/Max exist, but the 100k target was never reached; the `qvm`/TCG stall that capped it is recoverable, **not root-caused**, and stays open | [cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv) |
| **3** — Hardware twin port (Orin Nano) | ✅ **closed as A2 history** — QNX↔Linux IPC over a real `br0`/tap bridge ran under **TCG**, 2 × 100,000 iterations with no echo-sequence mismatch or I/O error reported, **using a rebuilt IFS with new TCP server code, not the byte-identical Phase-1 image**. KVM boot never worked **with the SDP's shipped `startup-qemu-virt`**, and the root-caused GICv3/`KVM_EXIT_ARM_NISV` defect stays open in that shipped binary. It is **boot-verified as of 2026-09-18**: an IFS whose `startup-qemu-virt` this repo rebuilt with `-fno-auto-inc-dec`, from board source the SDP does not ship (`orin-native/startup/qemu-virt/`), booted under `-enable-kvm` to `Startup complete` and the guest banner, while the shipped startup on the same launch line, host and session hung after `FOUND GICv3 ITS` as before. The rebuilt arm's captures were byte-identical on QEMU 6.2.0 and 11.1.0. Nothing was timed, it is not a QNX-supported configuration, and the owner decided not to file the defect. | [orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv), [orin-port.md](docs/orin-port.md), [orin-kvm-*.log](logs/sample-boot/) |
| **3b** — Native QNX on the Orin (no QEMU) | 🟡 **M path complete (2026-09-13); S1-F met (QNX plus Linux) 2026-09-17** — the two-guest rung (B5) ran once and passed: the QNX guest's banner and IPC completed beside the Linux guest. One observation, not a series. A6's gate was settled on 2026-09-21 and its campaign has run in part; v1 was superseded before it was ever frozen — see [The native port](#the-native-port-phase-3b) | [ADR-003](docs/adr-003-hardware-timed-qhv.md), [the plan](docs/orin-native-port-plan.md) |
| **4** — Twin diff + DRIVE OS comparison | ✅ **done 2026-09-20** — both deliverables exist. The twin diff is the KVM pair: a byte-identical IFS timed under KVM on the Orin and on AWS `a1.metal` ([§1b](docs/digital-twin-design.md)); the earlier TCG diffs stay history and are not re-run (OD10 withdrew the TCG legs). The verdicts in [drive-os-comparison.md](docs/drive-os-comparison.md) are written: **six Partial, two Cannot, no Validates**. Done does not mean the gap closed — it means it is now measured and stated | [digital-twin-design.md](docs/digital-twin-design.md) §1a, §4, §5 |
| **5** — FuSa & Cybersecurity overlay | ⬜ not started as a dedicated phase (a Phase-1-gate pass did run) | [fusa/](docs/fusa/), [cyber/](docs/cyber/) |
| **6** — Polish, public README, demo | ⬜ not started | — |
| **7** _(stretch)_ — Multi-SoC / domain convergence | ⬜ feasibility frozen, not built | [future-multi-soc.md](docs/future-multi-soc.md) |

**On the word "cloud":** the QHV-hosted QNX guest and its IPC benchmark, *as
built*, ran on the **local Windows host under QEMU TCG** — not on the
Graviton instance the design called for, because non-metal Graviton exposes
no `/dev/kvm`/EL2 ([ADR-002](docs/phase2-topology-decision.md)). AWS earned
its keep three times over. An `a1.metal` instance supplied the cross-vendor
reproduction of the defect (2026-07-29); on 2026-09-19 a matched pair there
reproduced both the defect (shipped startup, 17 bytes) and its removal (rebuilt
startup, 1301 bytes, `Startup complete` + banner), refuting Hypothesis 7; and on
2026-09-20 it was the second host in the boot comparison of
[`§1b`](docs/digital-twin-design.md). H-C stays open — no trace was taken
there — and the 2026-09-19 arms are one run each with nothing timed.

---

## Measured results

Project rule: *never write "it works" without a log, a number, or a diff.*
Every figure traces to a committed CSV or boot log here. **Every figure below
ran on an earlier architecture and is kept with that label, not re-run for its
own sake.** The numbers that count are taken on A6; its campaign records are
under `results/orin-native-port/*T-a6-*/`. A6 is the current direction,
not a frozen reference architecture.

| What | Result | Read it with |
|---|---|---|
| **Boot time**, plain IFS, Windows vs Orin (A2) | Orin **+24.9%** median (mean delta agrees to 1.3 pp) | "Orin is slower" is defensible; **"more consistent" is not** — Windows' spread is dominated by one cold-start outlier; drop it and its other four runs span 33 ms. The files record no QEMU build, device set or disk mode, so "only the host differed" **cannot be checked** |
| **IPC round-trip**, n=15/side (A1 vs A2) | P50 +10.5%, P99 +11.3% | **Not** a host-only comparison: it mixes host, transport, OS pair and QEMU build across two architecture versions. At n=15 **P99 and Max are the same sample**. An earlier unmatched 15-vs-100,000 comparison read as "18% faster"; that did not survive sample-size matching and **should not be quoted** |
| **Hypervisor leg**, same QHV images both hosts (A3) | Orin **2.15×** slower to guest banner | "Host" is a *bundle* — CPU, OS, TCG backend and QEMU build all change together; all are stamped in the times files. Same-host control bounds the build component at +0.4%. This is TCG **emulation throughput**, not a hardware-timed virtualisation number |
| **Mechanism reliability** (A1, A2) | HW leg: 2 × 100,000 iterations, no echo-sequence mismatch or I/O error reported in the run's capture. Cloud leg: a `qvm`/TCG virtio-queue stall at **0.98–2.62% of attempted iterations** — 3, 8 and 7 recoveries in 305 attempts across the three diagnostic runs, so two of the three exceed 2% | The HW runs used a **rebuilt IFS with new TCP server code**, not the byte-identical Phase-1 image — a real deviation from a zero-code-change portability claim. The stall has **no root-cause fix**; it is only *survivable*, via a kick-safe sentinel frame that recovered 19/19 real stalls with recovered iterations excluded from the statistics |

Full derivations, all caveats and the correction history:
[digital-twin-design.md](docs/digital-twin-design.md) §5 and §1a,
[findings.md](docs/findings.md).

**Two things the move to the Orin found**, both recorded rather than tidied
away: QEMU 6.2.0 hangs the QHV host because its `virt` board never wires the
EL2 *virtual* timer IRQ (added in 9.0) — **verified by a one-wire reverted
build** that reproduces the hang, while unpatched 11.1.0 boots the same image
on the same board; and `qvm`'s MMIO trap decoder rejected the wide store
`memcpy()` chose for a shared-memory page, the same *class* of defect as the
GICv3 finding: an emulator that decodes only a subset of real encodings.

**How claims are checked.** Each Phase 3b design record from M1b to S1 carries
a review-outcomes section; an independent review narrowed M4-F's claim before
it was recorded. In findings.md and the plan, statements later
shown wrong are **struck through in place with a dated note rather than
deleted**, and [ADR-002](docs/phase2-topology-decision.md) records how Phase 1
falsified the original KVM cloud topology.

The guest disk in the A3 pair was the RQ-2 diagnostic variant, not one
regenerated from committed sources. That was settled on 2026-09-16 and executed
on 2026-09-17: the host and guest were rebuilt from clean sources, and the
as-run configuration now equals the committed one. The figures above were
measured against the older artefacts and stay exactly as recorded.

---

## The native port (Phase 3b)

QNX ran on the Orin's own cores with no QEMU, entered by `kexec` from L4T — a
shim carrying an arm64 `Image` header hands over at EL2 — or, on one attended
session, by our own EFI loader from the firmware's UEFI Shell.

| Rung | What it showed |
|---|---|
| **M0** | `kexec` hands over at EL2 |
| **M1** | QNX boots natively; stock `pidin` reports Release 8.0.0 on a Cortex-A78ae |
| **M2** | All six cores enter at EL2 through PSCI `CPU_ON` and pass a pinned load |
| **M1b** | The VHE host runs at EL2 with E2H/TGE on every core |
| **M3** | Native `qvm` boots the byte-identical cloud-leg QNX guest to its banner |
| **M4-F** | The trace instrument works on the board |
| **M5-F** | A UEFI cold boot reaches startup and procnto — attended, one session |
| **S1-F** | A Linux guest boots and holds ten minutes; in the two-guest rung (B5) the QNX guest's banner and IPC complete beside it — met (QNX plus Linux) |

**Every rung is a functional pass, and none of them is timed.** The ten-minute
hold carried the **Linux guest alone** and was idle apart from a heartbeat —
not a load, stress or soak test. The two-guest rung ran **once**: a boot and a
completion, not a hold, and nothing is shown about duration with two guests.
Whether a guest's memory came from the intended second window is not shown.
Figures from these rungs are unpublished under NC QDL v7 4.6(i), and **no
hardware-timed hypervisor number exists or ever will.**

Procedures, claims register and every owner decision: [the
plan](docs/orin-native-port-plan.md).

---

## Setup

Walkthrough: [scripts/README.md](scripts/README.md). Which scripts apply
depends on the leg, per [ADR-002](docs/phase2-topology-decision.md):
`scripts/qhv/` for A1, `scripts/orin/` for A2 and A6, `orin-native/` for the
native port, `scripts/twin/` for the diff.

⚠️ `scripts/setup-bridge.sh` and `scripts/launch-linux-vm.sh` belong to the
**Orin** path, not the cloud leg: the cloud dual-VM-over-a-bridge topology they
were written for was falsified by ADR-002 and is kept only for that lineage.

**Hard prerequisite:** you must obtain your own QNX Everywhere licence (free
for personal use) and install QNX SDP 8.0 yourself. This repo does not — and
per the licence, cannot — ship any QNX SDK component or QNX-derived binary.
Clause 4.6(i) of the governing text bars releasing evaluation results without
consulting the supervising academic, which is why the A4 and A5 figures are
unpublished.

Board work needs a 3.3 V USB-TTL adapter on the Orin's J14 header (never a
5 V-only one) and a way to cut power remotely: the CCPLEX watchdog does not
fire after `kexec`, so a hung run needs a physical power cycle.

---

## Roadmap

- [x] **M0–M5** — the kexec shim, QNX natively on six cores, the EL2 host, a
      QNX guest under native `qvm`, the trace instrument, and a UEFI cold boot
      (2026-09-09 → 09-13)
- [x] **S1-F** — a Linux guest under native `qvm`, and both guests at once
      (2026-09-17)
- [x] **Phase 4** — the twin diff and the DRIVE OS verdicts: six Partial, two
      Cannot, no Validates (2026-09-20)
- [x] **Settle A6's gate** — sample sizes and campaign content adopted
      (2026-09-21); the design is in
      [measurement-design.md](docs/measurement-design.md)
- [x] **A6 campaign, first part** — the ladder, interference and saturation at
      k ≥ 12, CPU loads pinned per core (2026-09-21)
- [x] **UDP beside TCP on A6** (OD12) — the four ladder rungs over both, paired
      (2026-09-22)
- [x] **Shared memory over `ivshmem` on A6** (OD12) — one polled slot, beside TCP
      and UDP in one run, paired (2026-09-22)
- [x] **Notified shared memory on A6** (OD12) — a virtio-console kick in, a console
      kick or an `ivshmem` doorbell out, beside TCP, UDP and the polled slot (2026-09-22)
- [ ] **A6 campaign, the rest** — guest-side timestamps, the frame-size and
      offered-rate sweeps, the boot-timeout falsification
- [ ] **Phase 7** _(stretch)_ — domain-controller extension, two tracks in
      [future-multi-soc.md](docs/future-multi-soc.md)

---

## Repository layout

| Path | What |
|---|---|
| [`docs/`](docs/) | narrative, decisions, findings |
| [`orin-native/`](orin-native/) | native-port source: shim, board directory, tools, guest configs |
| [`ipc-test/`](ipc-test/) | C99 IPC: QNX servers, host and Linux clients, shmem probes, the shared frame |
| [`scripts/`](scripts/) | bring-up, QHV configs, twin sync and diff, the CI claims gate |
| [`logs/sample-boot/`](logs/sample-boot/) | curated boot and benchmark logs — the evidence |
| [`results/`](results/) | benchmark CSVs, GICv3 reports, run records (A4/A5 unpublished; A6 published) |

**Start here:** [findings.md](docs/findings.md) is append-only, dated, and the
ground truth when anything else disagrees with it.
[drive-os-comparison.md](docs/drive-os-comparison.md) is the calibration — what
this validates against DRIVE OS and what it cannot.
[orin-native-port-plan.md](docs/orin-native-port-plan.md) holds the milestone
ladder and every owner decision. The Phase-1 gate material sits apart from
those three, under [`docs/fusa/`](docs/fusa/), [`docs/cyber/`](docs/cyber/)
and [`docs/tara/`](docs/tara/) — study-level work products, not certification
evidence.

---

## Author

Hao Chen — Research Engineer at DENSO Automotive Deutschland GmbH.
Personal project, built on my own time and hardware.

---

## License

[MIT](LICENSE) for source code, scripts, and documentation in this repo.
QNX SDP, QNX Everywhere, and Linux distributions referenced are subject to
their respective licenses; this repo neither redistributes nor relicenses them.
The user supplies their own QNX SDP 8.0 install under the QNX NCEULA.
