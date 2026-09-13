# qnx-linux-dual-vm-proxy

> **Digital Twin** of NVIDIA DRIVE OS dual-VM partitioning, across **two**
> hosts: a Windows PC and a Jetson Orin Nano. The architecture has been
> replaced several times, and each version keeps its label and its
> measurements as history. On the **cloud / x86 leg** the SDP 8.0 QNX
> Hypervisor (`qvm`) hosted a QNX guest under QEMU TCG — a real EL2/EL1
> partition boundary, but emulated, not hardware-timed. *As built, that leg
> ran on the local Windows build host*: non-metal AWS Graviton exposes no
> `/dev/kvm` ([ADR-002](docs/phase2-topology-decision.md)). The **hardware
> twin** first ran a rebuilt QNX image under TCG that talked to native L4T
> over a bridge, with KVM-accelerated boot blocked by a root-caused GICv3
> defect ([docs/orin-port.md](docs/orin-port.md)). It then booted the cloud
> leg's hypervisor images, unchanged. Those three QEMU legs are closed as
> history. The current work, **Phase 3b**, runs the
> QNX Hypervisor natively on the Orin with no QEMU. Its M path is complete,
> ending at M5-F's functional pass. A Linux guest is added next (S1-F, also a
> functional rung). Then reference architecture v1 is frozen, and the
> measurements run once on it. One of them is the
> **twin diff**: what changes when the host bundle (CPU, OS, TCG backend,
> QEMU build) changes.

![Phase](https://img.shields.io/badge/Phase-3b%20native%20QHV-blue)
![Evidence](https://img.shields.io/badge/evidence-committed%20logs%20%2B%20CSVs-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Arch](https://img.shields.io/badge/arch-aarch64-lightgrey)

This is **not** DRIVE OS and not a certified hypervisor. The QEMU legs
were **software-layer proxies** of DRIVE OS dual-VM partitioning, with the
cloud leg as a fast-iteration sandbox; they are now history. The current,
native leg (Phase 3b) runs the QNX Hypervisor on the Orin's own cores
(Cortex-A78AE, same family as DRIVE Orin), but as Experimental Software on a
consumer dev kit: no certification,
no vendor support path, no quantified freedom from interference. The intent
is to study the *software layer* (BSP bring-up, IPC, kernel/userspace
boundaries, cloud→target portability) that an SE supporting NVIDIA DRIVE OS
customers actually touches — and to be honest about what each leg can and
cannot demonstrate vs. a production DRIVE OS partition.

---

## Architecture (Digital Twin: history, the current native leg, v1)

Every QNX image is built on an x86_64 host (QNX SDP 8.0 has Windows and
Linux x86_64 host tools; no arm64, no macOS). The architecture has been
replaced several times, and every record keeps the id of the version it ran
on. Three QEMU versions are closed as history and will not be redone: the
cloud leg (A1), the Orin plain leg (A2, a rebuilt IFS talking to a native
Linux client), and A1's hypervisor images booted unchanged under TCG on both
hosts (A3). Closed does not mean their targets were met: A1 never reached
its 100k-iteration target, and KVM boot on the Orin never worked. The
`qvm`/TCG stall (still not root-caused) and the GICv3/NISV KVM defect stay
open as separate items. The current leg, A4, runs the QNX Hypervisor
natively on the Orin with no QEMU and boots the byte-identical cloud-leg QNX
guest. Its `qvm` host images have only been entered by `kexec` from L4T. The
EL2 host has a second proven entry path: our own EFI loader, launched by hand
from the firmware's UEFI Shell, which has carried only the one-core M1b host
image, without `qvm` or a guest.

The diagram reads top to bottom: history, the current native leg, and the
next steps, none of which has run. S1-F adds a Linux guest without a GPU
under native `qvm`. Reference architecture v1 is then frozen: the native host
with that guest, plus two TCG twin legs that boot v1's guests in a QHV host
image under QEMU, on the Windows PC and on the Orin. One measurement
campaign runs on v1. Its twin diff sets the two TCG legs against each other
and each against the native leg. Every such pair compares whole bundles
(for the TCG pair: CPU, OS, TCG backend, QEMU build), never a single
variable. The architecture versions are defined in the
[plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

```
  HISTORY  closed; records kept as architecture-version history, not redone
  ┌──────────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────────┐
  │ A1  cloud leg            │ │ A2  Orin plain leg       │ │ A3  same QHV images      │
  │ Windows PC, QEMU TCG:    │ │ L4T host, QEMU TCG: QNX  │ │ A1's images unchanged,   │
  │ QHV qvm + one QNX guest  │ │ guest, br0/tap IPC to a  │ │ in TCG on the Windows    │
  │ closed; the TCG stall    │ │ native Linux client      │ │ PC and on the Orin       │
  │ stays open               │ │ closed; KVM boot blocked │ │ closed                   │
  └──────────────────────────┘ └────────────┬─────────────┘ └──────────────────────────┘
                                            │ Phase 3b: QEMU gone, hypervisor on silicon
  ┌─────────────────────────────────────────v──────────────────────────────────────────┐
  │ CURRENT  A4: native on the Jetson Orin Nano, no QEMU                               │
  │                                                                                    │
  │ entry path:                          ┌──────────────────────────────────────────┐  │
  │ (1) kexec from L4T (M1b-M4) ────────>│ QNX Hypervisor host at EL2 (VHE)         │  │
  │ (2) firmware UEFI Shell, by hand,    │ on the Orin's own cores, no QEMU         │  │
  │     then our EFI loader (M5-F) ─────>│ M5-F: the one-core M1b host image only   │  │
  │     attended, one session;           │                                          │  │
  │     no qvm, no guest                 │ kexec entry only:                        │  │
  │                                      │ qvm ──> QNX guest: the cloud-leg         │  │
  │                                      │         guest and disk, unchanged        │  │
  │                                      │ M3: guest boots to its banner            │  │
  │                                      │ M4-F: trace instrument works             │  │
  │                                      └──────────────────────────────────────────┘  │
  └─────────────────────────────────────────┬──────────────────────────────────────────┘
                                            │ next: add a Linux guest
  ┌─────────────────────────────────────────v──────────────────────────────────────────┐
  │ NEXT  planned, not run                                                             │
  │                                                                                    │
  │ S1-F, the first stage of A5: A4's host, qvm, and a Linux guest without a GPU       │
  │                                         │                                          │
  │                                         v freeze                                   │
  │ reference architecture v1, fixed by a manifest; entry path, or both, chosen at     │
  │ the freeze                                                                         │
  │                                                                                    │
  │ ┌────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐ │
  │ │ native leg (Orin)      │  │ TCG twin leg: Windows  │  │ TCG twin leg: Orin     │ │
  │ │ A4's host at EL2       │  │ a QHV host image in    │  │ the same images in     │ │
  │ │ + the S1 Linux guest   │  │ QEMU TCG boots v1's    │  │ QEMU TCG, beside L4T   │ │
  │ │ QNX guest kept or      │  │ guests on the PC       │  │                        │ │
  │ │ dropped at the freeze  │  │                        │  │                        │ │
  │ └───────────┬────────────┘  └───────────┬────────────┘  └───────────┬────────────┘ │
  │             └──────── twin diff ────────┴───────────────────────────┘              │
  │ then one measurement campaign on v1: the M3 and M4 numbers, the twin diff and,     │
  │ if v1 keeps both entry paths, the M5 comparison; each record stamped with the      │
  │ architecture version                                                               │
  └────────────────────────────────────────────────────────────────────────────────────┘

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
| **2** — Cloud twin IPC + latency | ✅ **closed: architecture A1 history** — real P50/P99/Max exist, but the 100k-iteration target was never reached. The `qvm`/TCG virtio-queue stall that capped it is recoverable, not root-caused, and stays open. The v1 campaign's IPC sample size is set once, at the freeze | [cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv), [qnx-host-client/README.md](ipc-test/qnx-host-client/README.md) |
| **3** — Hardware twin port (Jetson Orin Nano) | ✅ **closed: architecture A2 history** — heterogeneous QNX↔Linux IPC over a real `br0`/tap bridge ran under **TCG** (2 × 100 000 iterations, 0 errors). KVM boot never worked: the root-caused GICv3 / `KVM_EXIT_ARM_NISV` defect, reproduced on a second ARM vendor and at compile level from QNX's own BSP source (compile-verified, boot-unverified: the `qemu-virt` board source is not shipped), stays open as a separate filing track, outside reference architecture v1 | [orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv), [orin-port.md](docs/orin-port.md), [aws-a1-metal-kvm-nisv-repro.log](logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log) |
| **3b** — Native QNX on the Orin Nano (no QEMU) | 🟡 **M path complete (2026-09-13); next S1-F** — the QNX Hypervisor runs natively at EL2 on the Orin (architecture A4): M0 showed `kexec` hands over at EL2, and M1 to M3 brought up QNX, all six cores, the EL2 host and native `qvm` booting the unmodified cloud-leg QNX guest. M4-F showed the trace instrument working on the board, with a partial cross-check and its two rungs under different instrument versions (both freeze-gate items). M5-F entered the one-core M1b host image (no `qvm`, no guest) through a UEFI cold boot in one attended session. Every rung is a functional pass; figures from M3 on stay unpublished, and the numbers are taken once, in the v1 campaign, after S1-F (a Linux guest without a GPU) and the v1 freeze | [ADR-003](docs/adr-003-hardware-timed-qhv.md), [orin-native-port-plan.md](docs/orin-native-port-plan.md), [orin-native/startup/README.md](orin-native/startup/README.md), [results/orin-native-port/](results/orin-native-port/) |
| **4** — Twin diff + DRIVE OS comparison | 🟡 **history recorded; re-run inside the v1 campaign** — the plain-leg boot diff (A2), the A1-against-A2 IPC diff and the release-aligned QHV pair (A3) are kept as architecture-version history, all under TCG and none hardware-timed. The twin diff runs again in the v1 campaign, and the verdicts in [drive-os-comparison.md](docs/drive-os-comparison.md) wait for it | [digital-twin-design.md](docs/digital-twin-design.md) §1a, §4, §5 |
| **5** — FuSa & Cybersecurity overlay | ⬜ not started as a dedicated phase (a Phase-1-gate FuSa + Cyber pass *did* run) | [docs/fusa/](docs/fusa/), [docs/cyber/](docs/cyber/), [docs/tara/](docs/tara/) |
| **6** — Polish, public README, demo recording | ⬜ not started | — |
| **7** _(stretch)_ — Multi-SoC / domain convergence | ⬜ feasibility frozen, not built | [future-multi-soc.md](docs/future-multi-soc.md) |

**Honest note on the word "cloud":** the QHV-hosted QNX guest and its IPC
benchmark, *as built*, ran on the **local Windows host under QEMU TCG** —
not on the c7g.large Graviton instance the design originally called for,
because non-metal Graviton exposes no `/dev/kvm` / EL2
([ADR-002](docs/phase2-topology-decision.md)). AWS still earned its keep
for one thing: an `a1.metal` instance supplied the cross-vendor
reproduction of the KVM GICv3 defect (the Phase 3 row above).

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
(SHA-256-verified, booted with `-snapshot` so the bytes never drift) ran on
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
That holds for the kexec path. The UEFI cold-boot rung, M5-F (below), added a
single file to the ESP after backing up the existing boot files, changed no UEFI
variable beyond the one the firmware changes on every boot, and removed the file
at the end.

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
cloud leg booted under emulation, with its unmodified disk, to its banner. It reached the
banner in all five timed runs, and the host-to-guest message test over a virtual console
completed every round.

Getting there took three fixes that only the real board could reveal:

- The plan's diskless guest configuration never prints the banner.
- The host image was missing libraries the cloud host carries.
- Unloading the GPU driver quietly reset the CPU frequency governor.

M3 is a functional pass. Its timing and latency figures stay on the local branch
`m3-results-unpublished` and count as history for this architecture; the numbers
are taken again, once, on reference architecture v1.

**The trace instrument.** On 2026-09-11, M4-F showed the tracing the campaign will rely
on working on the board. One run traced the EL2 host alone. The other put a trace window
around M3's full run: qvm's hypervisor trace events were emitted and paired, both
listings crossed the debug console intact, and the image reset itself. The pass is
narrower than it sounds. The two runs passed under different instrument versions, and
the PC's cross-check covered only the early part of the window, because the listing it
compared was capped. Both are items for the freeze gate.

**A cold boot through the firmware.** On 2026-09-13, M5-F entered M1b's unchanged one-core
EL2 host image with no Linux and no `kexec` in that power cycle. The firmware's built-in
UEFI Shell, reached by hand through its menus, launched an EFI loader of our own. The
loader carried the unchanged M1b image, left the firmware and branched to it with the entry
contract `kexec` uses. The image reached startup at EL2, went on to `procnto` and a stock
`pidin` on the single core that image uses, and reset itself; the board then booted its
unchanged L4T. Across the session the ESP gained only the loader file, removed at the end,
and the only UEFI variable that changed is one the firmware also changes on a control boot
with no key pressed. The Shell rehearsal needed a second attempt, and that attempt departed
from the procedure in three ways. Power was cut before L4T had finished shutting down,
after a helper reported the board ready too early (fixed before the loader run). More than
one ESC was sent where the procedure asks for one. The operator bound was overrun. The
loader run also sent more than one ESC, but it reached the Shell inside the bound, and
every token arrived inside the design's time bounds. All of these are recorded deviations. It is a functional pass from one attended
session on one board. It times nothing, it was not repeated, and it does not show that the
firmware leaves cleaner state than `kexec`; the comparison between the two entry paths waits
for the campaign ([m5-design.md](results/orin-native-port/20260909T1100Z/m5-design.md) §10,
and §14 for the session).

What this is not, stated plainly: the hypervisor has hosted one QNX guest, not Linux,
with no device pass-through, and only on a host entered from Linux; the cold boot ran
the one-core M1b host image without `qvm` or a guest. No per-exit hypervisor number is judged or
published. With M5-F the M path is complete. Next is S1-F, a Linux guest without a GPU
under native `qvm`, then the v1 freeze and one measurement campaign. The two
second-cluster cores run a busy loop at a fixed, much lower rate whose cause is still
open, and the freeze needs it explained or those cores left out of v1. The M0 to M1b
records and captures are in this repo for now. The M3 to M5 run records and every figure
from M3 on, including the campaign's, stay unpublished until publishing them under the
QNX non-commercial licence is cleared; the code, the plan and the procedure are here.

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
| GPU (Ampere CUDA / vGPU) | No leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano has an Ampere iGPU but it is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. On the native leg the next guest, S1, is Linux without a GPU. GPU pass-through is a later target, studied on a separate unpublished research track; no GPU stage has started. |
| Real-time guarantees | The QEMU legs (A1 to A3, history) were TCG-emulation-bound, not hardware-timed, and the Orin plain leg added observable host-scheduler jitter on top; v1's two TCG twin legs will measure emulated time too. The native leg runs on real cores, but its timings are unpublished and not yet campaign-grade: the CPU frequency is wherever BPMP and Linux left it, the clock is recorded as unverified, and the numbers wait for the v1 campaign. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg (A1, history): host↔guest over the `qvm` virtio-console vdev (crosses the EL2/EL1 boundary, but TCG-emulated — the latency measures emulation cost, not transport cost). Orin plain leg (Phase 3, A2, history): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net — also TCG-emulated, since the KVM path is blocked, so it is **not** hardware-timed either. Native leg (A4): host to guest over virtio-console under qvm on real cores; figures unpublished, re-measured in the v1 campaign. No sourced DRIVE OS IPC figure is in the repo yet, so no gap is quantified here. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. The native leg's UEFI cold boot (M5-F) is an EFI loader of ours launched by hand from the firmware's Shell: not a supported, certified or unattended boot path. |

These are deliberate. Documenting them precisely is the engineering point.

---

## Setup

Detailed walkthrough is in [scripts/README.md](scripts/README.md). Which
scripts apply depends on the leg, per [ADR-002](docs/phase2-topology-decision.md):

| Leg | Entry points |
|---|---|
| Cloud / x86 (A1, history: QHV host + QNX guest, TCG) | `scripts/build-qhv.bat` → `scripts/launch-qhv-tcg.ps1`; committed config sources in [`scripts/qhv/`](scripts/qhv/) |
| Orin plain leg (A2, history) | [`scripts/orin/`](scripts/orin/): `bootstrap-orin-l4t.sh` → `setup-bridge-orin.sh` → `launch-qnx-on-orin-tcg.sh` |
| Native (Phase 3b, A4, current) | `orin-native/`: `shim/`, the `startup/` board directory and image builders ([README](orin-native/startup/README.md)), `qhv/` guest configurations, `tools/` on-target helpers, the `m4dry/` and `m4/` M4 tooling (dry run, TCG rehearsal, board capture and parser), and `uefi/`, the M5 UEFI loader with its QEMU rehearsal and the board-session terminal; procedures in [the plan](docs/orin-native-port-plan.md) |
| QHV leg on the Orin (A3, history; the method v1's TCG twin legs reuse) | `scripts/twin/sync-qhv.sh` (stage the QHV images, checksum-verified, resumable) → `scripts/orin/build-qemu-on-orin.sh` (QEMU ≥ 9.0 is required: the distro 6.2.0 hangs the QHV host on an EL2 timer defect) → `WITH_RNG=1 scripts/orin/launch-qhv-on-orin-tcg.sh 5`; Windows counterpart `scripts/launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner -WithRng` |
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
  header (never a 5 V-only one), with its TX on J14 pin 3 only during an M5
  session, while the terminal runs, and removed afterwards, and a way to cut
  power remotely, because a hung run needs a power cycle
- *Optional:* an AWS account + `aws` CLI, only to repeat the `a1.metal` KVM
  probe. The original design's Graviton runtime leg was never built, and the
  as-built cloud leg ran locally — if you do launch an instance, mind the
  hourly billing and the teardown note in [scripts/README.md](scripts/README.md)

---

## Roadmap

- [x] **Phase 0** — Bootstrap, scaffold, narrative, BSP selection, twin re-scope
- [x] **Phase 1** — Cloud twin bring-up (SDP 8.0 QHV `qvm` + one QNX guest under QEMU TCG — no Linux guest on this leg, per [ADR-002](docs/phase2-topology-decision.md))
- [x] **Phase 2** _(closed: architecture A1 history)_ — Cloud twin IPC + latency: real P50/P99/Max on A1, but the 100k-iteration target was never reached. The `qvm`/TCG stall is recoverable, not root-caused, and the v1 campaign's IPC sample size is set once, at the freeze ([qnx-host-client](ipc-test/qnx-host-client/README.md))
- [x] **Phase 3** _(closed: architecture A2 history)_ — Hardware twin on the Orin Nano: QNX↔Linux IPC over the bridge ran under TCG; KVM boot stays blocked by the GICv3/NISV defect, now a separate filing track ([orin-port.md](docs/orin-port.md), [collector](scripts/diagnose-gicv3-nisv.sh) and [report](results/gicv3-nisv-debug/20260909T101030Z/summary.md))
- [ ] **Phase 3b** — Native QNX on the Orin Nano, no QEMU ([ADR-003](docs/adr-003-hardware-timed-qhv.md); [plan](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11))
  - [x] M0 — the kexec shim runs at EL2 (2026-09-09)
  - [x] M1 — QNX boots natively (2026-09-10)
  - [x] M2 — all six cores (2026-09-10)
  - [x] M1b — EL2 host with VHE (2026-09-10)
  - [x] M3 — the QNX Hypervisor boots a QNX guest natively (2026-09-10)
  - [x] M4-F — the trace instrument works on the board (2026-09-11)
  - [x] M5-F — a UEFI cold boot reaches startup; the M path ends (2026-09-13)
  - [ ] S1-F — a Linux guest without a GPU under native qvm (RAM-window check run 2026-09-13; design in progress)
  - [ ] Freeze reference architecture v1
  - [ ] One measurement campaign on v1
- [ ] **Phase 4** — Twin diff + DRIVE OS comparison: earlier diffs kept as A1-A3 history; the twin diff and the verdicts come from the v1 campaign ([digital-twin-design.md](docs/digital-twin-design.md))
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
│   ├── m4dry/  m4/                 #   M4 dry run, TCG rehearsal, board capture and parser
│   └── uefi/                       #   M5 UEFI loader, its QEMU rehearsal, the board-session terminal
├── ipc-test/                       # C99: QNX echo servers, QNX host client, Linux client,
│   │                               #      host + guest vdev-shmem probes, shared frame code
│   └── common/                     # wire protocol (frame.h) + raw-mode console I/O
├── logs/sample-boot/               # curated boot + benchmark logs (the evidence)
├── results/cloud/  results/hw/     # benchmark CSVs, one schema for both twins
├── results/qhv-images-SHA256SUMS.txt  # copy-time SHA-256 of the QHV image pair (values only; images stay out of git)
├── results/gicv3-nisv-debug/       # diagnose-gicv3-nisv.sh runs: PASS/FAIL/BLOCKED matrix, decoded ESR, next commands
├── results/orin-native-port/        # Phase 3b research, compile-only checks, M0-M1b run records, design records (the M3-M5 run records are unpublished)
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
