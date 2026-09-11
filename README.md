# qnx-linux-dual-vm-proxy

> **Digital Twin** of NVIDIA DRIVE OS dual-VM partitioning, across **two**
> hosts: a Windows PC and a Jetson Orin Nano. The architecture has been
> replaced several times, and each version keeps its label and its
> measurements as history. On the **cloud / x86 leg** the SDP 8.0 QNX
> Hypervisor (`qvm`) hosts a QNX guest under QEMU TCG — a real EL2/EL1
> partition boundary, but emulated, not hardware-timed. *As built, that leg
> runs on the local Windows build host*: non-metal AWS Graviton exposes no
> `/dev/kvm` ([ADR-002](docs/phase2-topology-decision.md)). The **hardware
> twin** first ran a rebuilt QNX image under TCG that talks to native L4T
> over a bridge, with KVM-accelerated boot blocked by a root-caused GICv3
> defect ([docs/orin-port.md](docs/orin-port.md)). It then booted the cloud
> leg's hypervisor images, unchanged. The current work, **Phase 3b**, runs the
> QNX Hypervisor natively on the Orin with no QEMU. After its remaining
> functional milestones, a Linux guest is added. Then reference architecture
> v1 is frozen, and the measurements run once on it. One of them is the
> **twin diff**: what changes when the host bundle (CPU, OS, TCG backend,
> QEMU build) changes.

![Phase](https://img.shields.io/badge/Phase-3b%20native%20QHV-blue)
![Evidence](https://img.shields.io/badge/evidence-committed%20logs%20%2B%20CSVs-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Arch](https://img.shields.io/badge/arch-aarch64-lightgrey)

This is **not** DRIVE OS and not a certified hypervisor. The QEMU legs are
**software-layer proxies** of DRIVE OS dual-VM partitioning; the cloud leg
is a fast-iteration sandbox. The native leg (Phase 3b) runs the QNX
Hypervisor on the Orin's own cores (Cortex-A78AE, same family as DRIVE
Orin), but as Experimental Software on a consumer dev kit: no certification,
no vendor support path, no quantified freedom from interference. The intent
is to study the *software layer* (BSP bring-up, IPC, kernel/userspace
boundaries, cloud→target portability) that an SE supporting NVIDIA DRIVE OS
customers actually touches — and to be honest about what each leg can and
cannot demonstrate vs. a production DRIVE OS partition.

---

## Architecture (Digital Twin: cloud side ↔ hardware side)

Every QNX image is built on an x86_64 host (QNX SDP 8.0 has Windows and
Linux x86_64 host tools; no arm64, no macOS). Which image runs where depends
on the architecture version. The cloud leg's QHV host and guest images (A1)
boot byte-identical on the Orin too (A3). The Orin plain leg (A2) used a
rebuilt IFS carrying a TCP server. The native leg (A4) boots the
byte-identical cloud-leg guest under its own host image. What stays shared
is the wire protocol and the benchmark harness. The host is always a bundle
(CPU, OS, TCG backend, QEMU build), never a single variable.

The diagram shows the first two legs, A1 and A2, which are now history, and
the native leg that replaced QEMU on the Orin (A4). The architecture versions
are defined in the
[plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

```
                       ┌─────── shared artifacts ────────┐
                       │ • QNX images (per architecture) │
                       │ • IPC client/server source      │
                       │ • Wire protocol (framed echo)   │
                       │ • Test harness + benchmarks     │
                       └────────────────┬────────────────┘
                                        │ same wire protocol + harness
               ┌────────────────────────┴─────────────────────────┐
               │                                                  │
  ┌────────────v───────────┐                         ┌────────────v───────────┐
  │ Cloud / x86 leg (A1)   │                         │ Orin plain leg (A2)    │
  │  build: local Windows  │                         │  host: L4T Ubuntu on   │
  │   PC (x86_64 SDP 8.0)  │                         │   Cortex-A78AE x6      │
  │  run: QHV qvm + one    │                         │  run: QNX guest +      │
  │   QNX guest, QEMU TCG  │  ── compare twin-diff ▶ │   native L4T, QEMU TCG │
  │  as-built host = that  │                         │  KVM boot blocked by   │
  │   same Windows PC      │                         │   GICv3 / NISV defect  │
  │   (Graviton: no KVM)   │                         │  heterogeneous IPC     │
  │  purpose: fast         │                         │   over br0 + tap       │
  │   iterate, sweep       │                         │  purpose: real silicon │
  └────────────────────────┘                         └────────────┬───────────┘
                                                                  │ Phase 3b: QEMU removed
                                                     ┌────────────v───────────┐
                                                     │ Orin native (A4)       │
                                                     │  host: QNX Hypervisor  │
                                                     │   at EL2, no QEMU      │
                                                     │  guest: the cloud-leg  │
                                                     │   QNX guest, unchanged │
                                                     │  next: M4-F, M5-F,     │
                                                     │   Linux guest (S1),    │
                                                     │   then freeze v1       │
                                                     └────────────────────────┘

Reference (production DRIVE OS, not this repo):
  NVIDIA DRIVE OS  →  Type-1 hypervisor (QNX Safety + Linux Compute partitions)
                      vGPU, ASIL-D Safety guest, certified IPC.
This repo is a Digital Twin DESIGN of that architecture, not a reproduction.
```

See [docs/architecture.md](docs/architecture.md) for the detailed
twin-by-twin walkthrough, [docs/digital-twin-design.md](docs/digital-twin-design.md)
for the twin methodology, and [docs/bsp-selection.md](docs/bsp-selection.md)
for why the build/runtime split exists.

---

## Status — Phase 3b (native port), on the path to reference architecture v1

[docs/findings.md](docs/findings.md) is the authoritative, dated ground
truth; this table is a summary that can lag it.

| Phase | Status | Evidence |
|---|---|---|
| **0** — Bootstrap, scaffold, BSP research, twin re-scope | ✅ done | [bsp-selection.md](docs/bsp-selection.md) |
| **1** — Cloud twin bring-up: QHV `qvm` hosting a QNX guest under TCG | ✅ done | [qhv-tcg-host-and-guest-boot.log](logs/sample-boot/qhv-tcg-host-and-guest-boot.log) |
| **2** — Cloud twin IPC + latency | 🟡 **partial** — real P50/P99/Max exist; sample count capped by a `qvm`/TCG virtio-queue stall that is **not root-caused**, but is now *recoverable* (19/19 real stalls recovered). Architecture A1, kept as history: the stall stays open, and the v1 campaign's IPC sample size is fixed at the freeze | [cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv), [qnx-host-client/README.md](ipc-test/qnx-host-client/README.md) |
| **3** — Hardware twin port (Jetson Orin Nano) | 🟡 **substantial, not closed** — architecture A2, history: heterogeneous QNX↔Linux IPC over a real `br0`/tap bridge works (2 × 100 000 iterations, 0 errors) under **TCG**; **KVM boot is blocked** by a root-caused GICv3 / `KVM_EXIT_ARM_NISV` defect, since reproduced on a second ARM vendor **and reproduced from QNX's own BSP source**: the faulting `str w3,[x0],#4` at GICD+0x420 falls out of `gic_v3.c` built with QNX's own flags, and `-fno-auto-inc-dec` removes all four MMIO writeback stores (compile-verified, boot-unverified — the `qemu-virt` board source is not shipped). The KVM/NISV defect is a separate track, outside reference architecture v1 | [orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv), [orin-port.md](docs/orin-port.md), [aws-a1-metal-kvm-nisv-repro.log](logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log) |
| **3b** — Native QNX on the Orin Nano (no QEMU) | 🟡 **M3 met 2026-09-10: the QNX Hypervisor boots a QNX guest natively on the board** — [ADR-003](docs/adr-003-hardware-timed-qhv.md) chose a native port as the route to a *hardware-timed* hypervisor number. The QNX kernel and user space booted on the board, entered by `kexec` from L4T with no QEMU and no NVIDIA BSP, and a stock `pidin` reported Release 8.0.0 on a Cortex-A78ae. The same day all six cores came up under QNX, each secondary entering at EL2 through PSCI `CPU_ON`. Then the host moved to EL2 with VHE on every core, and the QNX Hypervisor booted the unmodified cloud-leg QNX guest on it in five timed runs out of five. On 2026-09-11 dry run 7b passed under TCG, and the M4 board tooling was rehearsed there. The same day the project decided how the numbers are taken. The milestone path finishes as functional passes: M4-F shows the trace instrument working on the board, and M5-F is a UEFI cold boot that reaches startup. S1-F then adds a Linux guest without a GPU. After that, reference architecture v1 is frozen and one measurement campaign runs on it. M3 stands as a functional pass. Its figures are history for this architecture and stay on the local branch `m3-results-unpublished`. | [orin-native-port-plan.md](docs/orin-native-port-plan.md), [orin-native/startup/README.md](orin-native/startup/README.md), [results/orin-native-port/](results/orin-native-port/) |
| **4** — Twin diff + DRIVE OS comparison | 🟡 **history recorded, re-run on v1** — the plain-leg boot diff (A2) and the release-aligned QHV pair (A3) are kept as architecture-version history (TCG throughput, not hardware-timed). The distro QEMU 6.2.0 hang the QHV leg uncovered is a QEMU EL2-timer defect, verified by a reverted-wiring build, not the host. The twin diff runs again in the v1 campaign, and the verdicts in [drive-os-comparison.md](docs/drive-os-comparison.md) wait for it | [digital-twin-design.md](docs/digital-twin-design.md) §1a, §5 |
| **5** — FuSa & Cybersecurity overlay | ⬜ not started as a dedicated phase (a Phase-1-gate FuSa + Cyber pass *did* run) | [docs/fusa/](docs/fusa/), [docs/cyber/](docs/cyber/), [docs/tara/](docs/tara/) |
| **6** — Polish, public README, demo recording | ⬜ not started | — |
| **7** _(stretch)_ — Multi-SoC / domain convergence | ⬜ feasibility frozen, not built | [future-multi-soc.md](docs/future-multi-soc.md) |

**Honest note on the word "cloud":** the QHV-hosted QNX guest and its IPC
benchmark, *as built*, run on the **local Windows host under QEMU TCG** —
not on the c7g.large Graviton instance the design originally called for,
because non-metal Graviton exposes no `/dev/kvm` / EL2
([ADR-002](docs/phase2-topology-decision.md)). AWS still earned its keep
for one thing: an `a1.metal` instance supplied the cross-vendor
reproduction of the KVM GICv3 defect below.

---

## Measured results

Project rule: *never write "it works" without a log, a number, or a diff.*
Every figure below traces to a committed CSV or boot log in this repo.

Every timing and latency figure in this section ran on an earlier
architecture: the A1 cloud leg, the A2 Orin plain leg, or the A3 QHV images
under TCG on both hosts. They are kept with that label and not re-run for
their own sake. The numbers that count are taken once, on reference
architecture v1, after the freeze
([plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

### Boot time — plain-IFS leg, Windows against Orin (A2, history)

Same IFS and disk image, same QEMU machine, CPU and memory arguments, TCG on
both sides; n=5 per host, timed from process launch to the guest's own
`Startup complete` line. The series files do not record the QEMU build,
device set or disk mode, so whether only the host differed cannot be
checked; the QEMU releases likely differed (unverified):

| Host | median | mean | run-to-run spread |
|---|---|---|---|
| Local Windows (x86_64, TCG) | **25,427 ms** | 25,644.8 ms | 25,412–26,515 ms (1,103 ms) |
| Jetson Orin Nano (A78AE, TCG) | **31,758 ms** | 31,702.4 ms | 31,446–31,780 ms (334 ms) |

Δ median **+24.9%** (Orin slower); the mean delta (+23.6%) agrees to within
1.3 percentage points, which shows the series repeats, not what causes the
gap. On
*spread*, be careful: across all five runs Orin looks ~3× tighter, but
Windows' range is dominated by a single cold-start outlier (run 1) — drop it
and Windows' remaining four runs span just **33 ms**. The defensible claim
is that Orin is slower; "more consistent" depends entirely on whether you
count that cold start. Like every twin comparison here, it compares host
bundles, not one variable.

### IPC round-trip latency — sample-size-matched (n=15 per side, 48-byte payload; A1 against A2, history)

| Metric | Cloud (QNX↔QNX, `qvm` virtio-console) | HW (QNX↔Linux, virtio-net + `br0`) | Δ |
|---|---|---|---|
| P50 | 2,002,500 ns | 2,213,370 ns | +10.5% |
| P99 | 2,332,300 ns | 2,596,291 ns | +11.3% |
| Max | 2,332,300 ns | 2,596,291 ns | +11.3% |

⚠️ **Not** a host-only comparison. It mixes host, transport, OS pair and
QEMU build, across two architecture versions (A1 cloud leg, A2 Orin plain
leg), and both are history. Read it as "both mechanisms are alive and land within ~10% of each
other", never as a host-speed result. An earlier *unmatched* 15-vs-100,000
sample comparison read as "HW is 18% **faster**"; that reading did not
survive sample-size matching and should not be quoted. Full derivation and
correction: [digital-twin-design.md](docs/digital-twin-design.md) §5.

### The hypervisor leg — same QHV images on both hosts (A3, history)

The QNX Hypervisor (`qvm`) host image and its guest are host-agnostic: two
image files, everything else inside the emulation. The identical pair
(SHA-256-verified, booted with `-snapshot` so the bytes never drift) runs on
both hosts under the same upstream QEMU release, same accelerator, same
device set — the closest this repo gets to "only the host changes":

| launch → guest banner (n=5, median) | Windows x86_64 | Jetson Orin Nano | ratio |
|---|---|---|---|
| QEMU 11.1.0, rng in slot 3, `-snapshot` | **28,829 ms** (spread 110) | **62,058 ms** (spread 1,231) | **2.15×** |
| host-only segment (no fixed waits) | 6,160 ms | 13,430 ms | 2.18× |

Honest labels, because the review that produced these numbers insisted on
them: "host" is a *bundle* — CPU, OS, TCG code-generation backend
(`tcg/i386` vs `tcg/aarch64`) and the QEMU *build* (a mingw build whose version
string carries a fork tag vs a from-source build of the upstream tag: one
release, two builds) all change together, and every one of
those is stamped into the times files. Same-host control: on the Windows box
alone, the 11.0.50 dev build vs the 11.1.0 release differ by +0.4%, which
bounds the build component. It is a comparison of TCG emulation throughput
on the hypervisor workload, not a hardware-timed virtualisation number —
QHV needs EL2 for its guest, i.e. nested virt, which ARM KVM does not offer
on A78AE, so any QEMU-hosted QHV leg needs TCG on both hosts. The native port
below removes QEMU instead.

The guest disk in this pair is the RQ-2 diagnostic variant, not one
regenerated from committed sources. Whether to regenerate it is decided at the
v1 freeze, and both TCG legs run again in the v1 campaign on v1's images.

**What moving the leg found — a real QEMU-version defect, not a host one.**
Ubuntu 22.04's stock QEMU 6.2.0 hangs the QHV host on the Orin at its first
timeout-wait (`waitfor /dev/random` never times out; with an rng presented,
`io-sock` start instead). The same 6.2.0 (Weilnetz Windows build) **hangs identically on the x86_64 host**, so the effect is host-independent.
Under QEMU 11.1.0 the same image boots on the Orin with and without rng.
Cause, **verified by a reverted-wiring build**: `v6.2.0`'s `virt` board
never wires the EL2 *virtual* timer IRQ (added in QEMU 9.0), and a VHE
hypervisor host's timers are exactly that. QEMU 11.1.0 rebuilt on the Orin
with only that one wire removed
([patch](scripts/orin/patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch))
hangs identically, while unpatched 11.1.0 boots the same image on the same
board; a `-cpu cortex-a57` (no VHE) control on 6.2 gets past the hang point.
One wire, one variable, opposite outcome.
Along the way the leg's own instrument was corrected twice — an rng test in
the wrong virtio-mmio slot, and a "one-variable comparison" claim that the
QEMU version quietly falsified — both recorded in
[docs/findings.md](docs/findings.md) rather than tidied away.

### Mechanism reliability — where the twins actually diverge (A1 and A2, history)

- **HW leg:** two back-to-back **100,000-iteration** runs over a real
  `br0` / `tap-qnx` bridge, **zero errors**
  ([orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv)).
- **Cloud leg:** a non-deterministic `qvm`/TCG virtio-queue stall
  (~1–2% per iteration) still has **no root-cause fix**. It is now
  *survivable*: a kick-safe sentinel frame recovered **19/19 real stalls
  across 4 boots**, zero alignment corruption, recovered iterations
  correctly excluded from the timing statistics.
- **Cloud leg, second transport proven:** a `vdev shmem` host↔guest round
  trip — host writes a pattern, guest reads it byte-exact and writes back,
  and the still-running host sees the write-back — answering ADR-002's RQ-2
  *yes*, in both directions, both ends resolving to the same underlying
  region. Getting there cost one `Bus error`: `qvm`'s MMIO trap decoder
  rejected the wide store `memcpy()` chose for the factory page, so the
  writes had to become byte-at-a-time volatile stores — the same *class* of
  defect as the Orin GICv3 finding, an MMIO emulator that decodes only a
  subset of real instruction encodings.

---

### The native port (Phase 3b) — QNX runs on the board

Every hypervisor number above is TCG emulation throughput. None of them is
hardware-timed, because the QNX Hypervisor needs EL2 for its guest and ARM KVM
does not offer nested virtualisation on this silicon.
[ADR-003](docs/adr-003-hardware-timed-qhv.md) weighed the routes to a real one and
the project took the hardest: run QNX natively on the Jetson Orin Nano, with no
QEMU underneath.

**It runs.** On 2026-09-10 the QNX 8.0.0 kernel and user space booted on the
board, watched live over its debug header. A stock `pidin info` reported:

```
CPU:AARCH64 Release:8.0.0  FreeMem:975MB/992MB
Processes: 3, Threads: 14
Processor1: Cortex-A78ae FPU
```

The loader is `kexec` from the running L4T, which is the point: no firmware, ESP,
boot-partition or UEFI-variable change, so a power cycle always returns an
untouched Linux. An 8 KiB page carrying the `Image` header `kexec` insists on is
prefixed to the QNX image, because a raw IFS cannot host that header itself.
That holds for the kexec path. The planned UEFI cold-boot rung, M5-F, adds a
single file to the ESP after backing up the existing boot files, and still
writes no UEFI variable.

Getting there took two milestones and a review that stopped the first attempt:

- **M0**, the prefixed page alone, ran first and closed the plan's four
  highest-ranked unknowns in one boot — above all, that `kexec` hands over at EL2,
  without which the board could never host a hypervisor at all.
- **A pre-flight review stopped M1 before it ran.** Under the startup mode used
  here the library drops to EL1 early, where its own exception vectors are silent
  infinite loops — and this board's watchdog does not recover a hang. Any fault in
  the first bring-up would have cost the board session and every line of evidence.
  The board now installs its own vectors, which print and reset.
- **M1** then brought up the MMU, re-initialised the interrupt controller Linux had
  left running, set up the timer and the console, and started the kernel. User
  space followed once two image-packaging errors were fixed.

The image also ends itself now. Its last command warm-resets the board back to
Linux, and a RAM log that survives the reset is read on the next boot. In the first
such run that log was the better witness: the live console lost its last lines to
the reset, and the RAM log still had them. A run that ends in a reset no longer
needs anyone at the board. A run that hangs still does.

**All six cores.** The same day, M2 brought up the other five Cortex-A78AE cores,
including the two in the second cluster. Each is started through PSCI `CPU_ON` and
enters at EL2. A small user-space check then pinned a busy process to every core for
60 seconds and confirmed that each ran only where it was pinned, with a working timer:

```
SMPCHECK CENSUS PASS
SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none
```

A second run of the identical image passed the same way. Most of the work was not the
core geometry, which the startup library already had right, but failure handling:
several plausible faults on a secondary core would otherwise have hung the board
silently, and here a hang costs the evidence along with the session.

**The hypervisor host at EL2.** The same evening, M1b ran QNX in the mode its
hypervisor needs. Every core stays at EL2 with the virtualization host extensions
(VHE) on, and the kernel takes its clock from the EL2 virtual timer.

That timer's interrupt is not in the board's device tree, and a missing clock
interrupt does not fail loudly: under emulation such a host came up and then
stalled at its first timed wait. So before the kernel starts, startup now tests the
wiring on every core. It uses the timer Linux itself uses as a control, and it
stops the run with an explanation unless the answer is yes. It was yes on all six:

```
Enabling EL2 host hypervisor support (VHE)
t234: hvtimer cpu 5 verdict=wired reason=ok residue=00000000 qtime_intr=28
SMPCHECK census tick=ok ms=100 rc=0
SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none
```

A repeat of the six-core run passed the same way.

**A guest on the hypervisor.** Later that night, M3 put the QNX Hypervisor itself on the
board. `qvm`, running natively at EL2 on four cores, booted the same QNX guest image the
cloud leg boots under emulation, with its unmodified disk, to its banner. It reached the
banner in all five timed runs, and the host-to-guest message test over a virtual console
completed every round.

Getting there took three fixes that only the real board could reveal:

- The plan's diskless guest configuration never prints the banner.
- The host image was missing libraries the cloud host carries.
- Unloading the GPU driver quietly reset the CPU frequency governor.

M3 is a functional pass. Its timing and latency figures stay on the local branch
`m3-results-unpublished` and count as history for this architecture; the numbers
are taken again, once, on reference architecture v1.

What this is not, stated plainly: the hypervisor has hosted one QNX guest, not Linux,
with no device pass-through, on a host entered from Linux rather than cold-booted. No
per-exit hypervisor number exists. The next rung, M4-F, only has to show the trace
instrument working on the board; its tooling has been rehearsed under TCG. M5-F then
tries a UEFI cold boot, and S1-F a Linux guest without a GPU. The two second-cluster
cores run a busy loop at a fixed, much lower rate whose cause is still open, and the
freeze needs it explained or those cores left out of v1. The M0 to M1b records and
captures are in this repo for now. M3 and later figures, including the campaign's,
stay unpublished until publishing them under the QNX non-commercial licence is
cleared; the code, the plan and the procedure are here.

---

## Known limitations (honest framing)

The whole point of the project is to be precise about what a software-layer
proxy can and cannot demonstrate. This table is the load-bearing part:

| DRIVE OS feature | Limitation in this project |
|---|---|
| NVIDIA Hypervisor (Type-1) | Cloud leg runs the SDP 8.0 QNX Hypervisor (`qvm`) hosting one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (no `/dev/kvm` on cloud) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. The Orin plain leg (A2) was designed for host-mediated KVM, which stays blocked by GICv3/NISV and is outside reference architecture v1, so it ran under TCG too. The native leg (A4) runs the QNX Hypervisor at EL2 on the Orin's own cores with no QEMU. It is a real hypervisor on silicon, but not certified and not NVIDIA's: Experimental Software on a consumer dev kit, with no quantified freedom from interference. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | The cloud leg's as-built runtime CPU is the local x86_64 Windows host (Graviton3 was the design intent). The HW leg *does* run on Tegra234 silicon, but the QNX guest sees QEMU's generic `virt` machine — no Tegra-specific peripherals, no SoC-internal interconnect. The native leg runs the QNX host directly on Tegra234 through this repo's own startup code (console, interrupt controller, timers, CPU bring-up). It has no storage, network, display, GPU, SMMU or PCIe drivers, and its guest sees qvm's virtual devices, not Tegra peripherals. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU virt machine. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | No leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano has an Ampere iGPU but it is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. On the native leg the next guest, S1, is Linux without a GPU. GPU pass-through is a later target, studied on a separate unpublished research track; no GPU stage has started. |
| Real-time guarantees | The QEMU legs are TCG-emulation-bound, not hardware-timed; the Orin plain leg adds observable host-scheduler jitter on top. The native leg runs on real cores, but its timings are unpublished and not yet campaign-grade: the CPU frequency is wherever BPMP and Linux left it, the clock is recorded as unverified, and the numbers wait for the v1 campaign. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg: host↔guest over the `qvm` virtio-console vdev (crosses the EL2/EL1 boundary, but TCG-emulated — the latency measures emulation cost, not transport cost). Orin plain leg (Phase 3, A2): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net — also TCG-emulated, since the KVM path is blocked, so it is **not** hardware-timed either. Native leg (A4): host to guest over virtio-console under qvm on real cores; figures unpublished, re-measured in the v1 campaign. No sourced DRIVE OS IPC figure is in the repo yet, so no gap is quantified here. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. |

These are deliberate. Documenting them precisely is the engineering point.

---

## Setup

Detailed walkthrough is in [scripts/README.md](scripts/README.md). Which
scripts apply depends on the leg, per [ADR-002](docs/phase2-topology-decision.md):

| Leg | Entry points |
|---|---|
| Cloud / x86 (QHV host + QNX guest, TCG) | `scripts/build-qhv.bat` → `scripts/launch-qhv-tcg.ps1`; committed config sources in [`scripts/qhv/`](scripts/qhv/) |
| Hardware (Orin Nano) | [`scripts/orin/`](scripts/orin/): `bootstrap-orin-l4t.sh` → `setup-bridge-orin.sh` → `launch-qnx-on-orin-tcg.sh` |
| Native (Phase 3b) | `orin-native/`: `shim/`, the `startup/` board directory and image builders ([README](orin-native/startup/README.md)), `qhv/` guest configurations, `tools/` on-target helpers, and the `m4dry/` and `m4/` M4 tooling (dry run, TCG rehearsal, board capture and parser); procedures in [the plan](docs/orin-native-port-plan.md) |
| QHV leg on the Orin (Phase 4) | `scripts/twin/sync-qhv.sh` (stage the QHV images, checksum-verified, resumable) → `scripts/orin/build-qemu-on-orin.sh` (QEMU ≥ 9.0 is required: the distro 6.2.0 hangs the QHV host on an EL2 timer defect) → `WITH_RNG=1 scripts/orin/launch-qhv-on-orin-tcg.sh 5`; Windows counterpart `scripts/launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner -WithRng` |
| Twin diff | [`scripts/twin/diff-results.sh`](scripts/twin/diff-results.sh) |

`scripts/setup-bridge.sh` and `scripts/launch-linux-vm.sh` belong to the
**Orin / heterogeneous** path, not the cloud leg — the cloud
dual-VM-over-a-bridge topology they were written for was falsified by
ADR-002 and is kept only for that lineage.

**Hard prerequisite:** the user must obtain their own QNX Everywhere
license (NCEULA, free for personal use) and install QNX SDP 8.0
themselves. This repo does not — and per the NCEULA, cannot — ship any
QNX SDK components or QNX-derived binaries. The native-port plan reads the
governing text as the QNX Development License Agreement, Non-Commercial
License Class v7; its clause 4.6(i) bars releasing evaluation results without
prior written approval, which is why M3 and later figures are not in this repo.

Other prereqs:
- An x86_64 **Windows** build host (primary) or Linux (fallback) for SDP 8.0
  — there is no arm64 and no macOS SDP 8.0 installer
- ~50 GB disk on the build host for the SDP install + IFS output
- A Jetson Orin Nano Dev Kit (JetPack 6 / L4T R36.4.7) for the hardware twin
- For the native port: a 3.3 V-logic USB-TTL adapter on the Orin's J14 debug
  header (never a 5 V-only one), and a way to cut power remotely, because a
  hung run needs a power cycle
- *Optional:* an AWS account + `aws` CLI, only to repeat the `a1.metal` KVM
  probe. The original design's Graviton runtime leg was never built, and the
  as-built cloud leg runs locally — if you do launch an instance, mind the
  hourly billing and the teardown note in [scripts/README.md](scripts/README.md)

---

## Roadmap

- [x] **Phase 0** — Bootstrap, scaffold, narrative, BSP selection, twin re-scope
- [x] **Phase 1** — Cloud twin bring-up (SDP 8.0 QHV `qvm` + one QNX guest under QEMU TCG — no Linux guest on this leg, per [ADR-002](docs/phase2-topology-decision.md))
- [ ] **Phase 2** _(A1, history)_ — Cloud twin IPC + latency benchmark: real P50/P99/Max landed on architecture A1. The `qvm`/TCG stall stays unfixed but recoverable, and the 100k-iteration target is no longer chased: the v1 campaign's IPC sample size is fixed once, at the freeze
- [ ] **Phase 3** _(A2 recorded; KVM track separate)_ — Hardware twin on Jetson Orin Nano: heterogeneous QNX↔Linux IPC done under TCG (architecture A2, history). KVM boot stays blocked by the GICv3/NISV defect, a separate track outside reference architecture v1. What a defect filing still lacks (a numerically recorded fault PC/IPA, one logged run per QEMU variant) is pinned down by the read-only collector [scripts/diagnose-gicv3-nisv.sh](scripts/diagnose-gicv3-nisv.sh) and its reviewed report in [results/gicv3-nisv-debug/](results/gicv3-nisv-debug/20260909T101030Z/summary.md). The route to a hardware-timed hypervisor number is Phase 3b below, chosen in [ADR-003](docs/adr-003-hardware-timed-qhv.md) (Accepted 2026-09-09) and tracked in [orin-native-port-plan.md](docs/orin-native-port-plan.md)
- [ ] **Phase 3b** _(M3 met; M4 rehearsed under TCG)_ — Native QNX on the Orin Nano with no QEMU, the route [ADR-003](docs/adr-003-hardware-timed-qhv.md) chose to a hardware-timed hypervisor number. QNX 8.0.0 kernel and user space ran natively on the board, entered by `kexec` from L4T, then on all six cores, then as the hypervisor host at EL2, and then booted the cloud-leg QNX guest under the QNX Hypervisor. Next come functional rungs only: M4-F (the trace instrument works on the board), M5-F (a UEFI cold boot reaches startup) and S1-F (a Linux guest without a GPU under native qvm). Then reference architecture v1 is frozen and one campaign takes the numbers ([plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11))
- [ ] **Phase 4** _(history recorded; re-run on v1)_ — The boot-time diff (A2) and the QHV hypervisor-leg pair (A3) are kept as architecture-version history, and the stock QEMU 6.2 hang the QHV leg uncovered is written up as a QEMU-side EL2-timer defect. The twin diff runs again once, inside the v1 campaign, and the dimension-by-dimension verdicts in [drive-os-comparison.md](docs/drive-os-comparison.md) wait for that campaign
- [ ] **Phase 5** — FuSa & Cybersecurity overlay (FMEA, ASIL gap, STRIDE)
- [ ] **Phase 6** — Polish, demo recording, public release
- [ ] **Phase 7** _(stretch)_ — Domain-controller extension, two tracks in [future-multi-soc.md](docs/future-multi-soc.md): the original **multi-SoC** idea (a Qualcomm-Cockpit-class proxy alongside the NVIDIA one, inter-SoC IPC) and a newer **NVIDIA-primary single-SoC convergence** track (ADAS + IVI/Cockpit as sibling partitions on one SoC family)

---

## Skills / study artifacts

The `skills/` folder catalogs engineering paradigms studied alongside the build:

- [skills/fmea/](skills/fmea/) — FMEA paradigm, worksheet template, and a
  worked [Phase-1 cloud bring-up FMEA](skills/fmea/examples/phase1-cloud-bringup-fmea.md)
- [skills/iso-26262/](skills/iso-26262/) — ISO 26262 study scope + checklist
- [skills/cybersecurity-21434/](skills/cybersecurity-21434/) — ISO/SAE 21434 TARA paradigm
- [skills/aspice/](skills/aspice/) — Automotive SPICE process areas
- [skills/bsp-porting/](skills/bsp-porting/) — Generic BSP porting workflow
- [skills/digital-twin/](skills/digital-twin/) — twin methodology: what a twin diff can and cannot isolate
- [skills/jetson-platform/](skills/jetson-platform/) — JetPack / L4T platform notes
- [skills/tegra-virtualization/](skills/tegra-virtualization/) — Tegra virtualization background

These are **study artifacts**, not certification evidence.

---

## Interview narrative

A 2-minute spoken version is at [docs/interview-narrative.md](docs/interview-narrative.md).

---

## Repository layout

```
.
├── README.md                       # this file
├── CLAUDE.md                       # working guidance for Claude Code sessions
├── AGENTS.md                       # the same guidance, for non-Claude agents
├── LICENSE                         # MIT (repo source only; QNX components excluded)
├── docs/
│   ├── findings.md                 # append-only, dated — the ground truth
│   ├── architecture.md
│   ├── bsp-selection.md
│   ├── digital-twin-design.md      # twin methodology + the measured twin diffs (§5)
│   ├── phase2-topology-decision.md # ADR-002 — falsified the cloud dual-VM topology
│   ├── phase2-research-spike.md
│   ├── orin-port.md                # Phase 3 plan + KVM/GICv3 risk register
│   ├── adr-003-hardware-timed-qhv.md # ADR-003 (Accepted) — route to a hardware-timed QHV number
│   ├── orin-native-port-plan.md    # Phase 3b — native QNX on Orin Nano: plan, claims register, architecture versions, measurement freeze, M0-M5 and S1
│   ├── drive-os-comparison.md      # Phase 4 gap doc; verdicts wait for the v1 campaign
│   ├── future-multi-soc.md         # Phase 7 / 7-alt feasibility
│   ├── security-model.md           # STRIDE + NCEULA audit
│   ├── interview-narrative.md      # spoken version, incl. the GICv3 debugging story
│   ├── fusa/ cyber/ tara/          # Phase-1-gate FuSa + ISO/SAE 21434 work products
│   └── onboarding-prompt.md
├── agents/                         # long-form sub-prompt templates, one per agent role
├── .claude/agents/                 # the same roles as Claude Code subagent definitions
├── scripts/
│   ├── build-qhv.bat               # cloud leg: build the QHV host + QNX guest images
│   ├── launch-qhv-tcg.ps1          # cloud leg: boot QHV under QEMU TCG
│   ├── diagnose-gicv3-nisv.sh      # read-only evidence collector + report for the KVM/NISV boot hang
│   ├── qhv/                        # committed QHV config sources (g2.conf, post_start, gates)
│   ├── orin/                       # hardware twin: L4T bootstrap, bridge, launch; build-qemu-on-orin.sh; launch-qhv-on-orin-tcg.sh
│   ├── twin/                       # sync.sh + diff-results.sh; sync-qhv.sh (QHV images -> Orin, resumable, checksum-gated)
│   ├── orin/patches/               # one-wire QEMU experiment patch that verified the EL2 virtual-timer mechanism
│   └── bootstrap-*.sh, setup-bridge.sh, launch-*.sh   # EC2 fallback / pre-ADR-002 lineage
├── orin-native/                    # Phase 3b: native port source (our own code only)
│   ├── shim/                       #   M0 shim: arm64 Image header + EL2 vectors + state report
│   ├── startup/                    #   the t234-orin-nano board directory and the M1-M4 image builds
│   ├── qhv/                        #   native guest configurations
│   ├── tools/                      #   on-target helpers (console, stamps, SMP and trace tools)
│   └── m4dry/  m4/                 #   M4 dry run, TCG rehearsal, board capture and parser
├── ipc-test/                       # C99: QNX echo servers, QNX host client, Linux client,
│   │                               #      host + guest vdev-shmem probes, shared frame code
│   └── common/                     # wire protocol (frame.h) + raw-mode console I/O
├── logs/sample-boot/               # curated boot + benchmark logs (the evidence)
├── results/cloud/  results/hw/     # benchmark CSVs, one schema for both twins
├── results/qhv-images-SHA256SUMS.txt  # copy-time SHA-256 of the QHV image pair (values only; images stay out of git)
├── results/gicv3-nisv-debug/       # diagnose-gicv3-nisv.sh runs: PASS/FAIL/BLOCKED matrix, decoded ESR, next commands
├── results/orin-native-port/        # Phase 3b research, compile-only checks, M0-M1b run records, design records (M3's run record is unpublished)
└── skills/                         # study artefacts (FMEA, ISO 26262, 21434, ASPICE, BSP,
                                    #                 digital twin, Jetson, Tegra virt)

Deliberately absent from git, per the QNX NCEULA: the `qnx-safety-vm/` and
`qhv/` mkqnximage build trees, `ifs.bin`, disk images, and every compiled
QNX binary. See `.gitignore` — it is written to make such a commit hard.
```

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
