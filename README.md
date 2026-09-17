# qnx-linux-dual-vm-proxy

![Phase](https://img.shields.io/badge/Phase-3b%20native%20QHV-blue)
![Evidence](https://img.shields.io/badge/evidence-committed%20logs%20%2B%20CSVs-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Arch](https://img.shields.io/badge/arch-aarch64-lightgrey)

A **Digital Twin design** of NVIDIA DRIVE OS dual-VM partitioning — a QNX
safety side beside a Linux general-purpose side — built on a Jetson Orin Nano
dev kit and a Windows PC instead of DRIVE hardware. Nothing in it is certified.

[docs/findings.md](docs/findings.md) is the authoritative, dated ground truth;
everything below is a summary that can lag it. Ids such as A4, M5-F and S1-F
are explained under [Reading the ids](#reading-the-ids).

---

## At a glance

- **What it is.** A study of the *software layer* under DRIVE OS-style
  partitioning: BSP bring-up, hypervisor host and guest, IPC patterns, and
  cloud→target portability. Not a reproduction of DRIVE OS, and not a
  certified hypervisor.

- **What works now.** The QNX Hypervisor (`qvm`) runs **natively at EL2 on the
  Orin's own cores, with no QEMU** (architecture A4), and boots the cloud-leg
  QNX guest image and disk unchanged. The milestone path M0–M5 is complete and
  every rung is a functional pass. On 2026-09-17 a stock Linux kernel booted as
  a guest of that hypervisor **on the board**, reached a shell that answered the
  host, and held for ten minutes with the hypervisor alive and memory canaries
  intact. Later the same day both guests ran at once for the first time: the
  QNX guest reached its banner and completed its IPC beside the Linux guest,
  so **S1-F is met (QNX plus Linux)**. That rung is a boot and a completion,
  not a hold — the ten minutes is the Linux guest alone.

- **What has been measured.** Every *published* figure comes from the earlier,
  emulated architectures (A1–A3, kept as history), **none hardware-timed**. The
  IPC comparison mixes host, transport, OS pair and QEMU build across two
  architecture versions — read it as "both mechanisms are alive", never as a
  host-speed result. Figures from M3 onward are unpublished pending the
  licence consultation, and the numbers that count are taken once, on
  reference architecture v1, after the freeze.

- **What it cannot show.** No certified Type-1 isolation, no quantified freedom
  from interference, no real-time guarantee, no safety certification, no GPU,
  camera or accelerator path. **No vision or AI workload has run on any leg.**
  The ten-minute run carried **one guest** and was idle apart from a heartbeat,
  so it is not a load, stress or soak test, and it is still the longest run this
  project has made; the two-guest rung was a boot, not a hold. Whether the
  guest's memory came from the second window is not shown: no host-side view of
  those addresses exists. See [Known limitations](#known-limitations-honest-framing).

- **What is next.** Freeze reference architecture v1, then run one measurement
  campaign on it, including the **twin diff**: what changes when the host
  bundle (CPU, OS, TCG backend, QEMU build) changes. **No board rung is
  outstanding**, but the freeze is not a formality: it still needs the manifest
  written, the emulated-CPU count for the twin legs settled, two missing
  sample-size rules, and the licence consultation, which gates publication
  rather than the campaign. GPU pass-through is the owner's target, on a
  research track outside the current plan; no GPU stage has started.

This is **not** DRIVE OS and not a certified hypervisor. The QEMU legs were
software-layer proxies and are now history. The current native leg runs the
QNX Hypervisor on the Orin's own Cortex-A78AE cores — the same core family as
DRIVE Orin — but as Experimental Software on a consumer dev kit, with no
vendor support path, no certification, and no quantified freedom from
interference. Documenting that gap precisely is the engineering point.

---

## Known limitations (honest framing)

The whole point of the project is to be precise about what a software-layer
proxy can and cannot demonstrate. This table is the load-bearing part:

| DRIVE OS feature | Limitation in this project |
|---|---|
| NVIDIA Hypervisor (Type-1) | The cloud leg (A1, history) ran the SDP 8.0 QNX Hypervisor (`qvm`) hosting one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (no `/dev/kvm` on cloud) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. The Orin plain leg (A2) was designed for host-mediated KVM, which stays blocked by GICv3/NISV and is outside reference architecture v1, so it ran under TCG too. The native leg (A4) runs the QNX Hypervisor at EL2 on the Orin's own cores with no QEMU. It is a real hypervisor on silicon, but not certified and not NVIDIA's: Experimental Software on a consumer dev kit, with no quantified freedom from interference. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | The cloud leg's as-built runtime CPU was the local x86_64 Windows host (Graviton3 was the design intent). The Orin plain leg (A2, history) *did* run on Tegra234 silicon, but its QNX guest saw QEMU's generic `virt` machine — no Tegra-specific peripherals, no SoC-internal interconnect. The native leg runs the QNX host directly on Tegra234 through this repo's own startup code (console, interrupt controller, timers, CPU bring-up). It has no storage, network, display, GPU, SMMU or PCIe drivers, and its guest sees qvm's virtual devices, not Tegra peripherals. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU virt machine. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | No leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano has an Ampere iGPU but it is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. On the native leg the S1 guest that has now run is Linux without a GPU. GPU pass-through is a later target, studied on a separate unpublished research track; no GPU stage has started. |
| Real-time guarantees | The QEMU legs (A1 to A3, history) were TCG-emulation-bound, not hardware-timed, and the Orin plain leg added observable host-scheduler jitter on top; v1's two TCG twin legs will measure emulated time too. The native leg runs on real cores, but its timings are unpublished and not yet campaign-grade: the CPU frequency is wherever BPMP and Linux left it, the clock is recorded as unverified, and the numbers wait for the v1 campaign. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg (A1, history): host↔guest over the `qvm` virtio-console vdev (crosses the EL2/EL1 boundary, but TCG-emulated — the latency measures emulation cost, not transport cost). Orin plain leg (Phase 3, A2, history): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net — also TCG-emulated, since the KVM path is blocked, so it is **not** hardware-timed either. Native leg (A4): host to guest over virtio-console under qvm on real cores; figures unpublished, re-measured in the v1 campaign. No sourced DRIVE OS IPC figure is in the repo yet, so no gap is quantified here. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. The native leg's UEFI cold boot (M5-F) is an EFI loader of ours launched by hand from the firmware's Shell: not a supported, certified or unattended boot path. |

These are deliberate. Documenting them precisely is the engineering point.

---

## Architecture

Every QNX image is built on an x86_64 host (SDP 8.0 has Windows and Linux
x86_64 host tools; no arm64, no macOS). The architecture has been replaced
several times, and **every record keeps the id of the version it ran on**.
Three QEMU versions are closed as history and will not be redone. Closed does
not mean their targets were met: A1 never reached its 100k-iteration target,
and KVM boot on the Orin never worked. The `qvm`/TCG stall (still not
root-caused) and the GICv3/NISV KVM defect stay open as separate items.

```
 HISTORY (closed, kept as architecture-version history, not redone)
   A1  cloud leg      Windows PC, QEMU TCG: QHV qvm + one QNX guest
                      closed; the TCG virtio-queue stall stays open
   A2  Orin plain leg L4T host, QEMU TCG: QNX guest, br0/tap IPC to a
                      native Linux client; closed; KVM boot blocked
   A3  same images    A1's images unchanged, in TCG on both hosts; closed
                            │
                            v  Phase 3b: QEMU gone, hypervisor on silicon
 CURRENT  A4: native on the Jetson Orin Nano, no QEMU
   QNX Hypervisor host at EL2 (VHE) on the Orin's own cores
   entry (1) kexec from L4T (M1b-M4)   ──> qvm ──> QNX guest, unchanged
   entry (2) firmware UEFI Shell, by hand, then our EFI loader (M5-F):
             the one-core M1b host image only, attended, no qvm, no guest
   S1-F met: Linux guest, then B5 ran QNX + Linux together, 2026-09-17
                            │
                            v  freeze
 NEXT  reference architecture v1, fixed by a manifest, then one campaign
   native leg (Orin) + TCG twin leg (Windows) + TCG twin leg (Orin)
   twin diff sets the two TCG legs against each other and against native

 Reference (production DRIVE OS, not this repo):
   Type-1 hypervisor, QNX Safety + Linux Compute partitions, vGPU,
   ASIL-D Safety guest, certified IPC.
 This repo is a Digital Twin DESIGN of that architecture, not a reproduction.
```

Every twin pair compares **whole bundles** (CPU, OS, TCG backend, QEMU
build), never a single variable.

Detail: [architecture.md](docs/architecture.md) (twin-by-twin walkthrough),
[digital-twin-design.md](docs/digital-twin-design.md) (twin methodology and
the measured diffs, §1a and §5), [bsp-selection.md](docs/bsp-selection.md)
(why the build/runtime split exists), and
[the plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)
(architecture versions and the measurement freeze).

### Reading the ids

- **A0–A5, v1** — architecture versions; every record keeps the id it ran on.
- **M0–M5** — the native port's milestones. An **-F** suffix (M4-F, M5-F,
  S1-F) marks a *functional* rung, which passes or fails on what appears,
  never on a figure.
- **S0–S5** — stages of the GPU pass-through research track; S1 is a Linux
  guest without a GPU, and S2–S5 stay outside the plan.
- **N** and **I** — owner decisions and implementation notes, local to
  [m4-design.md](results/orin-native-port/20260909T1100Z/m4-design.md).

---

## Status

| Phase | Status | Evidence |
|---|---|---|
| **0** — Bootstrap, BSP research, twin re-scope | ✅ done | [bsp-selection.md](docs/bsp-selection.md) |
| **1** — Cloud twin bring-up: QHV `qvm` + QNX guest under TCG | ✅ done | [boot log](logs/sample-boot/qhv-tcg-host-and-guest-boot.log) |
| **2** — Cloud twin IPC + latency | ✅ **closed as A1 history** — real P50/P99/Max exist, but the 100k target was never reached; the `qvm`/TCG stall that capped it is recoverable, **not root-caused**, and stays open | [cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv) |
| **3** — Hardware twin port (Orin Nano) | ✅ **closed as A2 history** — QNX↔Linux IPC over a real `br0`/tap bridge ran under **TCG**, 2 × 100,000 iterations, zero errors, **using a rebuilt IFS with new TCP server code, not the byte-identical Phase-1 image**. KVM boot never worked; the root-caused GICv3/`KVM_EXIT_ARM_NISV` defect (reproduced on a second ARM vendor; compile-verified from QNX's own BSP source, boot-unverified) stays open outside v1 | [orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv), [orin-port.md](docs/orin-port.md) |
| **3b** — Native QNX on the Orin (no QEMU) | 🟡 **M path complete (2026-09-13); S1-F met (QNX plus Linux) 2026-09-17** — the two-guest rung (B5) ran once and passed: the QNX guest's banner and IPC completed beside the Linux guest. One observation, not a series. What remains is the v1 freeze and the one campaign on it — see [The native port](#the-native-port-phase-3b) | [ADR-003](docs/adr-003-hardware-timed-qhv.md), [the plan](docs/orin-native-port-plan.md) |
| **4** — Twin diff + DRIVE OS comparison | 🟡 **history recorded; re-run inside the v1 campaign** — all earlier diffs ran under TCG, none hardware-timed; the verdicts in [drive-os-comparison.md](docs/drive-os-comparison.md) wait for it | [digital-twin-design.md](docs/digital-twin-design.md) §1a, §4, §5 |
| **5** — FuSa & Cybersecurity overlay | ⬜ not started as a dedicated phase (a Phase-1-gate pass did run) | [fusa/](docs/fusa/), [cyber/](docs/cyber/) |
| **6** — Polish, public README, demo | ⬜ not started | — |
| **7** _(stretch)_ — Multi-SoC / domain convergence | ⬜ feasibility frozen, not built | [future-multi-soc.md](docs/future-multi-soc.md) |

**On the word "cloud":** the QHV-hosted QNX guest and its IPC benchmark, *as
built*, ran on the **local Windows host under QEMU TCG** — not on the
Graviton instance the design called for, because non-metal Graviton exposes
no `/dev/kvm`/EL2 ([ADR-002](docs/phase2-topology-decision.md)). AWS earned
its keep for one thing: an `a1.metal` instance supplied the cross-vendor
reproduction of the KVM GICv3 defect.

---

## Measured results

Project rule: *never write "it works" without a log, a number, or a diff.*
Every figure traces to a committed CSV or boot log here. **Every figure below
ran on an earlier architecture and is kept with that label, not re-run for its
own sake.** The numbers that count are taken once, on v1, after the freeze.

| What | Result | Read it with |
|---|---|---|
| **Boot time**, plain IFS, Windows vs Orin (A2) | Orin **+24.9%** median (mean delta agrees to 1.3 pp) | "Orin is slower" is defensible; **"more consistent" is not** — Windows' spread is dominated by one cold-start outlier; drop it and its other four runs span 33 ms. The files record no QEMU build, device set or disk mode, so "only the host differed" **cannot be checked** |
| **IPC round-trip**, n=15/side (A1 vs A2) | P50 +10.5%, P99 +11.3% | **Not** a host-only comparison: it mixes host, transport, OS pair and QEMU build across two architecture versions. At n=15 **P99 and Max are the same sample**. An earlier unmatched 15-vs-100,000 comparison read as "18% faster"; that did not survive sample-size matching and **should not be quoted** |
| **Hypervisor leg**, same QHV images both hosts (A3) | Orin **2.15×** slower to guest banner | "Host" is a *bundle* — CPU, OS, TCG backend and QEMU build all change together; all are stamped in the times files. Same-host control bounds the build component at +0.4%. This is TCG **emulation throughput**, not a hardware-timed virtualisation number |
| **Mechanism reliability** (A1, A2) | HW leg: 2 × 100,000 iterations, zero errors. Cloud leg: a `qvm`/TCG virtio-queue stall, ~1–2%/iteration | The HW runs used a **rebuilt IFS with new TCP server code**, not the byte-identical Phase-1 image — a real deviation from a zero-code-change portability claim. The stall has **no root-cause fix**; it is only *survivable*, via a kick-safe sentinel frame that recovered 19/19 real stalls with recovered iterations excluded from the statistics |

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
it was recorded. In findings.md, CLAUDE.md and the plan, statements later
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

QNX runs on the Orin's own cores with no QEMU. The host is entered by `kexec`
from L4T — a shim carrying an arm64 `Image` header hands over at EL2 — or,
on one attended session, by our own EFI loader launched by hand from the
firmware's UEFI Shell.

| Rung | What it showed |
|---|---|
| **M0** | `kexec` hands over at EL2; the shim's own vectors report state |
| **M1** | QNX boots natively; stock `pidin` reports Release 8.0.0 on a Cortex-A78ae |
| **M2** | All six cores enter at EL2 through PSCI `CPU_ON` and pass a pinned load |
| **M1b** | The VHE host runs at EL2 with E2H/TGE on every core |
| **M3** | Native `qvm` boots the byte-identical cloud-leg QNX guest to its banner |
| **M4-F** | The trace instrument works on the board |
| **M5-F** | A UEFI cold boot reaches startup and procnto, attended, one session |
| **S1-F** | A Linux guest without a GPU boots and holds ten minutes on its own; in the two-guest rung (B5) the QNX guest's banner and IPC complete beside it — met (QNX plus Linux) 2026-09-17 |

**What this is not.** On the board the hypervisor has hosted a QNX guest and,
since 2026-09-17, a Linux guest that booted and held for ten minutes **while
idle apart from a heartbeat** — not a load, stress or soak test, and the
longest run this project has made. That hold carried the **Linux guest alone**.
**Both guests at once, once:** on 2026-09-17 the two-guest rung (B5) ran for
the first time and passed — the QNX guest reached its banner and completed
its IPC beside the running Linux guest, with the memory canaries verified
before and after. It is a boot and a completion, not a hold: **nothing is
shown about duration with two guests**, no timing or latency claim follows
from it (the figures are unpublished under the licence), and one observation
is not a series — no isolation, containment or freedom-from-interference
claim. No device pass-through. The host is entered from Linux in every timed
rung; the cold boot carried only the one-core M1b host image, without `qvm` or
a guest, times nothing, and has not been repeated. Whether the guest's RAM came
from the second window is **not shown**: no host-side view of those addresses
exists. No per-exit hypervisor number is judged or published.

**M4-F is narrower than it sounds.** Its two runs passed under different
instrument versions, and the PC's cross-check covered only the early part of
the window because the listing it compared was capped. On 2026-09-17 the first
rung was re-run on the board under the frozen instruments and passed — the
first time that counter had run on real silicon — so the two rungs now share
a *parser* version, **but still not a counter binary**. The capped cross-check
stands as an accepted, recorded limit.

**The native port is not a way around the GICv3/NISV defect.** That defect
blocks KVM-accelerated boot and stays open on its own filing track, outside
v1. The native port removes QEMU instead of working around it.

Three things this port cost that are worth naming: a pre-flight review stopped
M1 before it ran, because the startup library drops to EL1 where its own
vectors are **silent infinite loops** and no watchdog fires after `kexec` — a
hang needs someone at the board with a way to cut power. `GUEST_EXIT`'s
`status` field has no documented aarch64 meaning. And the UEFI path needed
`acpi=off` so the firmware hands over a device tree rather than ACPI tables.

The two second-cluster cores run a busy loop at a fixed, much lower rate whose
cause is still open; the freeze needs it explained or those cores left out.
The M0–M1b records and captures are in this repo; the M3–M5 and S1 run records
and every figure from M3 on stay unpublished until releasing them is cleared —
the code, the plan and the procedure are here.

Detail: [the plan](docs/orin-native-port-plan.md),
[orin-native/startup/README.md](orin-native/startup/README.md),
[results/orin-native-port/](results/orin-native-port/).

---

## Setup

Walkthrough: [scripts/README.md](scripts/README.md). Which scripts apply
depends on the leg, per [ADR-002](docs/phase2-topology-decision.md):

| Leg | Entry points |
|---|---|
| Cloud / x86 (A1, history) | `scripts/build-qhv.bat` → `scripts/launch-qhv-tcg.ps1`; configs in [`scripts/qhv/`](scripts/qhv/) |
| Orin plain leg (A2, history) | [`scripts/orin/`](scripts/orin/): `bootstrap-orin-l4t.sh` → `setup-bridge-orin.sh` → `launch-qnx-on-orin-tcg.sh` |
| Native (A4, current) | [`orin-native/`](orin-native/): shim, board directory, image builders, guest configs, M4/M5 tooling; procedures in [the plan](docs/orin-native-port-plan.md) |
| QHV leg on the Orin (A3, history) | `scripts/twin/sync-qhv.sh` → `scripts/orin/build-qemu-on-orin.sh` (**QEMU ≥ 9.0 required**: the distro 6.2.0 hangs on the EL2 timer defect) → `launch-qhv-on-orin-tcg.sh` |
| Twin diff | [`scripts/twin/diff-results.sh`](scripts/twin/diff-results.sh) |

⚠️ `scripts/setup-bridge.sh` and `scripts/launch-linux-vm.sh` belong to the
**Orin / heterogeneous** path, **not** the cloud leg — the cloud
dual-VM-over-a-bridge topology they were written for was falsified by ADR-002
and is kept only for that lineage.

**Hard prerequisite:** you must obtain your own QNX Everywhere licence (free
for personal use) and install QNX SDP 8.0 yourself. This repo does not — and
per the licence, cannot — ship any QNX SDK component or QNX-derived binary.
The governing text's clause 4.6(i) bars releasing evaluation results without
prior written approval, which is why M3 and later figures are not here.

Other prerequisites: an x86_64 **Windows** (primary) or Linux (fallback)
build host, ~50 GB free for the SDP install and IFS output; a Jetson Orin Nano
Dev Kit (**JetPack 6 / L4T R36.4.7**); for the native port a **3.3 V-logic**
USB-TTL adapter on the Orin's J14 header (never a 5 V-only one), with its TX
on **J14 pin 3 only during an M5 session**, while the terminal runs, removed
afterwards — and a way to cut power remotely, because a hung run needs a
power cycle. AWS is optional and only repeats the `a1.metal` KVM probe; the
Graviton runtime leg was never built.

---

## Roadmap

- [x] M0–M3 — the kexec shim, QNX natively, all six cores, the EL2 host, and
      the QNX Hypervisor booting a QNX guest natively (2026-09-09 → 09-10)
- [x] M4-F — the trace instrument works on the board (2026-09-11; its first
      rung re-run under the frozen instruments and passed, 2026-09-17)
- [x] M5-F — a UEFI cold boot reaches startup; the M path ends (2026-09-13)
- [x] S1-F — a Linux guest without a GPU under native `qvm`: booted, held ten
      minutes, and on the same day the two-guest rung (B5) ran the QNX guest
      beside it to banner and IPC completion — **met (QNX plus Linux)**
      (2026-09-17). Nothing ran under load, and the ten minutes is the Linux
      guest alone
- [ ] Freeze reference architecture v1
- [ ] One measurement campaign on v1
- [ ] **Phase 7** _(stretch)_ — domain-controller extension, two tracks in
      [future-multi-soc.md](docs/future-multi-soc.md)

---

## Repository layout

| Path | What |
|---|---|
| [`docs/`](docs/) | narrative, decisions, findings — see the index below |
| [`orin-native/`](orin-native/) | Phase 3b native-port source (our own code only): shim, board directory, tools, guest configs, M4/M5 tooling |
| [`ipc-test/`](ipc-test/) | C99 IPC: QNX echo servers, host client, Linux client, shmem probes, shared frame code |
| [`scripts/`](scripts/) | cloud-twin and Orin bring-up, QHV configs, twin sync and diff |
| [`logs/sample-boot/`](logs/sample-boot/) | curated boot and benchmark logs — the evidence |
| [`results/`](results/) | benchmark CSVs, GICv3 reports, Phase 3b records (M3–M5 and S1 run records unpublished) |
| [`skills/`](skills/) | study artefacts: FMEA, ISO 26262, ISO/SAE 21434, ASPICE, BSP porting, digital twin, Jetson, Tegra virtualisation. **Study artefacts, not certification evidence** |
| [`agents/`](agents/), [`.claude/agents/`](.claude/agents/) | agent role definitions, long-form and as subagent definitions |

**docs/ index.** [findings.md](docs/findings.md) — append-only, dated, the
ground truth · [architecture.md](docs/architecture.md) ·
[digital-twin-design.md](docs/digital-twin-design.md) — twin methodology and
the measured diffs (§5) · [bsp-selection.md](docs/bsp-selection.md) ·
[phase2-topology-decision.md](docs/phase2-topology-decision.md) — ADR-002,
falsified the cloud dual-VM topology · [orin-port.md](docs/orin-port.md) —
Phase 3 plan and the KVM/GICv3 risk register ·
[adr-003-hardware-timed-qhv.md](docs/adr-003-hardware-timed-qhv.md) ·
[orin-native-port-plan.md](docs/orin-native-port-plan.md) — Phase 3b plan,
claims register, architecture versions, the measurement freeze ·
[drive-os-comparison.md](docs/drive-os-comparison.md) — verdicts wait for the
v1 campaign · [future-multi-soc.md](docs/future-multi-soc.md) ·
[security-model.md](docs/security-model.md) — STRIDE and licence audit ·
[fusa/](docs/fusa/), [cyber/](docs/cyber/), [tara/](docs/tara/).

Deliberately absent from git, per the QNX licence: the `qnx-safety-vm/` and
`qhv/` build trees, `ifs.bin`, disk images, and every compiled QNX binary.
`.gitignore` is written to make such a commit hard.

---

## Author

Hao Chen — Research Engineer at DENSO Automotive Deutschland GmbH.
Personal project; no DENSO IP.

---

## License

[MIT](LICENSE) for source code, scripts, and documentation in this repo.
QNX SDP, QNX Everywhere, and Linux distributions referenced are subject to
their respective licenses; this repo neither redistributes nor relicenses them.
The user supplies their own QNX SDP 8.0 install under the QNX NCEULA.
