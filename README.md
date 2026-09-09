# qnx-linux-dual-vm-proxy

> **Digital Twin** of NVIDIA DRIVE OS dual-VM partitioning, across **two**
> hosts. On the **cloud / x86 twin** the SDP 8.0 QNX Hypervisor (`qvm`) hosts
> a QNX guest under QEMU TCG — exercising a real EL2/EL1 partition boundary,
> but emulated, not hardware-timed. *As built, that leg runs on the local
> Windows build host*: non-metal AWS Graviton exposes no `/dev/kvm`
> ([ADR-002](docs/phase2-topology-decision.md)). The heterogeneous
> QNX-Safety / Linux-Compute split is carried by the **hardware twin**
> (Jetson Orin Nano), where L4T is the native Linux side — also under TCG,
> because KVM-accelerated boot is blocked by a root-caused GICv3 defect
> ([docs/orin-port.md](docs/orin-port.md)). The same QNX IFS and IPC code run
> on both sides; the **twin diff** (what changes when only the host changes)
> is the deliverable.

![Phase](https://img.shields.io/badge/Phase-4%20twin--diff-blue)
![Evidence](https://img.shields.io/badge/evidence-committed%20logs%20%2B%20CSVs-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Arch](https://img.shields.io/badge/arch-aarch64-lightgrey)

This is **not** a real hypervisor — KVM-on-Linux is host-mediated, not a
certified Type-1 partitioner. The cloud twin is a **software-layer proxy**
of DRIVE OS dual-VM partitioning, used as a fast-iteration sandbox; the
hardware twin validates the same artefacts on real Tegra-class silicon
(Cortex-A78AE, same family as DRIVE Orin). The intent is to study the
*software layer* (BSP bring-up, IPC, kernel/userspace boundaries,
cloud→target portability) that an SE supporting NVIDIA DRIVE OS customers
actually touches — and to be honest about what each twin side can and
cannot demonstrate vs. a real hypervisor partition.

---

## Architecture (Digital Twin: cloud side ↔ hardware side)

The same QNX IFS and IPC source run on both twin sides. Only the host
changes. The build of the QNX IFS happens once on an x86_64 host (QNX
SDP 8.0 toolchain is x86_64 Linux + Windows; no arm64, no macOS) and
the resulting binary is reused across both twins.

```
                        ┌────── shared artifacts ───────┐
                        │ • QNX IFS  (mkqnximage virt)  │
                        │ • IPC client/server source    │
                        │ • Wire protocol (framed echo) │
                        │ • Test harness + benchmarks   │
                        └───────────────┬───────────────┘
                                        │ same binaries / same code
               ┌────────────────────────┴─────────────────────────┐
               │                                                  │
  ┌────────────v───────────┐                         ┌────────────v───────────┐
  │ Cloud / x86 twin       │                         │ HW twin (Orin Nano)    │
  │  build: local Windows  │                         │  host: L4T Ubuntu on   │
  │   PC (x86_64 SDP 8.0)  │                         │   Cortex-A78AE x6      │
  │  run: QHV qvm + one    │                         │  run: QNX guest +      │
  │   QNX guest, QEMU TCG  │  ── compare twin-diff ▶ │   native L4T, QEMU TCG │
  │  as-built host = that  │                         │  KVM boot blocked by   │
  │   same Windows PC      │                         │   GICv3 / NISV defect  │
  │   (Graviton: no KVM)   │                         │  heterogeneous IPC     │
  │  purpose: fast         │                         │   over br0 + tap       │
  │   iterate, sweep       │                         │  purpose: real silicon │
  └────────────────────────┘                         └────────────────────────┘

Reference (real hypervisor, not this repo):
  NVIDIA DRIVE OS  →  Type-1 hypervisor (QNX Safety + Linux Compute partitions)
                      vGPU, ASIL-D Safety guest, certified IPC.
This repo is a Digital Twin DESIGN of that architecture, not a reproduction.
```

See [docs/architecture.md](docs/architecture.md) for the detailed
twin-by-twin walkthrough, [docs/digital-twin-design.md](docs/digital-twin-design.md)
for the twin methodology, and [docs/bsp-selection.md](docs/bsp-selection.md)
for why the build/runtime split exists.

---

## Status — Phase 4 (twin diff) in progress

[docs/findings.md](docs/findings.md) is the authoritative, dated ground
truth; this table is a summary that can lag it.

| Phase | Status | Evidence |
|---|---|---|
| **0** — Bootstrap, scaffold, BSP research, twin re-scope | ✅ done | [bsp-selection.md](docs/bsp-selection.md) |
| **1** — Cloud twin bring-up: QHV `qvm` hosting a QNX guest under TCG | ✅ done | [qhv-tcg-host-and-guest-boot.log](logs/sample-boot/qhv-tcg-host-and-guest-boot.log) |
| **2** — Cloud twin IPC + latency | 🟡 **partial** — real P50/P99/Max exist; sample count capped by a `qvm`/TCG virtio-queue stall that is **not root-caused**, but is now *recoverable* (19/19 real stalls recovered) | [cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv), [qnx-host-client/README.md](ipc-test/qnx-host-client/README.md) |
| **3** — Hardware twin port (Jetson Orin Nano) | 🟡 **substantial, not closed** — heterogeneous QNX↔Linux IPC over a real `br0`/tap bridge works (2 × 100 000 iterations, 0 errors) under **TCG**; **KVM boot is blocked** by a root-caused GICv3 / `KVM_EXIT_ARM_NISV` defect, since reproduced on a second ARM vendor **and reproduced from QNX's own BSP source**: the faulting `str w3,[x0],#4` at GICD+0x420 falls out of `gic_v3.c` built with QNX's own flags, and `-fno-auto-inc-dec` removes all four MMIO writeback stores (compile-verified, boot-unverified — the `qemu-virt` board source is not shipped) | [orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv), [orin-port.md](docs/orin-port.md), [aws-a1-metal-kvm-nisv-repro.log](logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log) |
| **4** — Twin diff + DRIVE OS comparison | 🟡 **started** — boot-time twin diff done (n=5 per side); the QHV hypervisor leg now boots on the Orin under a from-source QEMU 11.1.0 (the distro 6.2.0 hangs it — a QEMU EL2-timer defect, verified by a reverted-wiring build, not the host); the release-aligned n=5 pair is measured (2.15× Orin/Windows, TCG throughput, not a hardware-timed number — routes to one are in [ADR-003](docs/adr-003-hardware-timed-qhv.md), Proposed); [drive-os-comparison.md](docs/drive-os-comparison.md) still open | [digital-twin-design.md](docs/digital-twin-design.md) §1a, §5 |
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

### Boot time — the clean host-only twin diff

Same IFS, same disk image, same QEMU machine/CPU/memory shape, TCG on both
sides; n=5 per host, timed from process launch to the guest's own
`Startup complete` line:

| Host | median | mean | run-to-run spread |
|---|---|---|---|
| Local Windows (x86_64, TCG) | **25,427 ms** | 25,644.8 ms | 25,412–26,515 ms (1,103 ms) |
| Jetson Orin Nano (A78AE, TCG) | **31,758 ms** | 31,702.4 ms | 31,446–31,780 ms (334 ms) |

Δ median **+24.9%** (Orin slower); the mean delta (+23.6%) agrees to within
1.3 percentage points, so n=5 is already enough to trust the headline. On
*spread*, be careful: across all five runs Orin looks ~3× tighter, but
Windows' range is dominated by a single cold-start outlier (run 1) — drop it
and Windows' remaining four runs span just **33 ms**. The defensible claim
is that Orin is slower; "more consistent" depends entirely on whether you
count that cold start. Until the hypervisor leg below, this was the only comparison in the repo
where *only the host* differs — every other number confounds at least two
variables.

### IPC round-trip latency — sample-size-matched (n=15 per side, 48-byte payload)

| Metric | Cloud (QNX↔QNX, `qvm` virtio-console) | HW (QNX↔Linux, virtio-net + `br0`) | Δ |
|---|---|---|---|
| P50 | 2,002,500 ns | 2,213,370 ns | +10.5% |
| P99 | 2,332,300 ns | 2,596,291 ns | +11.3% |
| Max | 2,332,300 ns | 2,596,291 ns | +11.3% |

⚠️ **Not** a host-only comparison — it confounds host, transport and
OS-pair. Read it as "both mechanisms are alive and land within ~10% of each
other", never as a host-speed result. An earlier *unmatched* 15-vs-100,000
sample comparison read as "HW is 18% **faster**"; that reading did not
survive sample-size matching and should not be quoted. Full derivation and
correction: [digital-twin-design.md](docs/digital-twin-design.md) §5.

### The hypervisor leg — same QHV images on both hosts

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
(`tcg/i386` vs `tcg/aarch64`) and the QEMU *build* (a mingw release build vs
a from-source build of the same tag) all change together, and every one of
those is stamped into the times files. Same-host control: on the Windows box
alone, the 11.0.50 dev build vs the 11.1.0 release differ by +0.4%, which
bounds the build component. It is a comparison of TCG emulation throughput
on the hypervisor workload, not a hardware-timed virtualisation number —
QHV needs EL2 for its guest, i.e. nested virt, which ARM KVM does not offer
on A78AE, so TCG is a hard requirement on both sides.

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

### Mechanism reliability — where the twins actually diverge

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

## Known limitations (honest framing)

The whole point of the project is to be precise about what a software-layer
proxy can and cannot demonstrate. This table is the load-bearing part:

| DRIVE OS feature | QEMU proxy limitation |
|---|---|
| NVIDIA Hypervisor (Type-1) | Cloud leg runs the SDP 8.0 QNX Hypervisor (`qvm`) hosting one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (no `/dev/kvm` on cloud) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. Orin's leg is host-mediated KVM *by design*, but KVM boot is currently blocked (GICv3/NISV), so that leg runs under TCG too. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | The cloud leg's as-built runtime CPU is the local x86_64 Windows host (Graviton3 was the design intent). The HW leg *does* run on Tegra234 silicon, but the QNX guest sees QEMU's generic `virt` machine — no Tegra-specific peripherals, no SoC-internal interconnect. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU virt machine. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | Neither leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano has an Ampere iGPU but it is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. |
| Real-time guarantees | Cloud timing is TCG-emulation-bound (not hardware-timed); Orin is TCG-bound as well (its KVM path is blocked), with observable host-scheduler jitter on top. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg: host↔guest over the `qvm` virtio-console vdev (crosses the EL2/EL1 boundary, but TCG-emulated — the latency measures emulation cost, not transport cost). Orin leg (Phase 3): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net — also TCG-emulated, since the KVM path is blocked, so it is **not** hardware-timed either. Both orders of magnitude off DRIVE OS shared-memory IPC; profiled honestly. See [ADR-002](docs/phase2-topology-decision.md). |
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
| QHV leg on the Orin (Phase 4) | `scripts/twin/sync-qhv.sh` (stage the QHV images, checksum-verified, resumable) → `scripts/orin/build-qemu-on-orin.sh` (QEMU ≥ 9.0 is required: the distro 6.2.0 hangs the QHV host on an EL2 timer defect) → `WITH_RNG=1 scripts/orin/launch-qhv-on-orin-tcg.sh 5`; Windows counterpart `scripts/launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner -WithRng` |
| Twin diff | [`scripts/twin/diff-results.sh`](scripts/twin/diff-results.sh) |

`scripts/setup-bridge.sh` and `scripts/launch-linux-vm.sh` belong to the
**Orin / heterogeneous** path, not the cloud leg — the cloud
dual-VM-over-a-bridge topology they were written for was falsified by
ADR-002 and is kept only for that lineage.

**Hard prerequisite:** the user must obtain their own QNX Everywhere
license (NCEULA, free for personal use) and install QNX SDP 8.0
themselves. This repo does not — and per the NCEULA, cannot — ship any
QNX SDK components or QNX-derived binaries.

Other prereqs:
- An x86_64 **Windows** build host (primary) or Linux (fallback) for SDP 8.0
  — there is no arm64 and no macOS SDP 8.0 installer
- ~50 GB disk on the build host for the SDP install + IFS output
- A Jetson Orin Nano Dev Kit (JetPack 6 / L4T R36.4.7) for the hardware twin
- *Optional:* an AWS account + `aws` CLI, only if you want the Graviton
  runtime leg or to repeat the `a1.metal` KVM probe. The as-built cloud leg
  runs locally, so AWS is no longer on the critical path — if you do launch
  an instance, mind the hourly billing and the teardown note in
  [scripts/README.md](scripts/README.md)

---

## Roadmap

- [x] **Phase 0** — Bootstrap, scaffold, narrative, BSP selection, twin re-scope
- [x] **Phase 1** — Cloud twin bring-up (SDP 8.0 QHV `qvm` + one QNX guest under QEMU TCG — no Linux guest on this leg, per [ADR-002](docs/phase2-topology-decision.md))
- [ ] **Phase 2** _(in progress)_ — Cloud twin IPC + latency benchmark: real P50/P99/Max landed; the 100k-iteration target is still blocked by an unfixed — though now recoverable — `qvm`/TCG stall
- [ ] **Phase 3** _(in progress)_ — Hardware twin on Jetson Orin Nano: heterogeneous QNX↔Linux IPC done under TCG; a hardware-timed KVM number is still owed, blocked on the GICv3/NISV defect. What the defect filing still lacks (a numerically recorded fault PC/IPA, one logged run per QEMU variant) is pinned down by the read-only collector [scripts/diagnose-gicv3-nisv.sh](scripts/diagnose-gicv3-nisv.sh) and its reviewed report in [results/gicv3-nisv-debug/](results/gicv3-nisv-debug/20260909T101030Z/summary.md); the route to a *genuinely* hardware-timed hypervisor number was chosen in [ADR-003](docs/adr-003-hardware-timed-qhv.md) (Accepted 2026-09-09): a **native QNX port to the Orin Nano**, tracked as Phase 3b in [orin-native-port-plan.md](docs/orin-native-port-plan.md) — kicked off, nothing booted natively yet; two compile-only results are verified and a read-only board pass already refuted four of the plan's own load-bearing claims
- [ ] **Phase 4** _(in progress)_ — Twin diff done for boot time **and for the QHV hypervisor leg** (same images on both hosts, one QEMU release, 2.15× Orin/Windows; the stock QEMU 6.2 hang it uncovered is a QEMU-side EL2-timer defect, written up honestly); the dimension-by-dimension [drive-os-comparison.md](docs/drive-os-comparison.md) is still open
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
│   ├── orin-native-port-plan.md    # Phase 3b — native QNX on Orin Nano: plan, claims register, M0-M4
│   ├── drive-os-comparison.md      # Phase 4 gap doc (still open)
│   ├── future-multi-soc.md         # Phase 7 / 7-alt feasibility
│   ├── security-model.md           # STRIDE + NCEULA audit
│   ├── interview-narrative.md      # spoken version, incl. the GICv3 debugging story
│   ├── fusa/ cyber/ tara/          # Phase-1-gate FuSa + ISO/SAE 21434 work products
│   └── jd-mapping.md, onboarding-prompt.md
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
├── ipc-test/                       # C99: QNX echo servers, QNX host client, Linux client,
│   │                               #      host + guest vdev-shmem probes, shared frame code
│   └── common/                     # wire protocol (frame.h) + raw-mode console I/O
├── logs/sample-boot/               # curated boot + benchmark logs (the evidence)
├── results/cloud/  results/hw/     # benchmark CSVs, one schema for both twins
├── results/qhv-images-SHA256SUMS.txt  # copy-time SHA-256 of the QHV image pair (values only; images stay out of git)
├── results/gicv3-nisv-debug/       # diagnose-gicv3-nisv.sh runs: PASS/FAIL/BLOCKED matrix, decoded ESR, next commands
├── results/orin-native-port/        # Phase 3b harvest, research and compile-only verifications
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
