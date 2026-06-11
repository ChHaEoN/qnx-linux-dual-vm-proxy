# qnx-linux-dual-vm-proxy

> **Digital Twin** of NVIDIA DRIVE OS dual-VM partitioning, across **two**
> hosts. On the **cloud twin** (AWS Graviton) the SDP 8.0 QNX Hypervisor
> (`qvm`) hosts a QNX guest under QEMU TCG — exercising a real EL2/EL1
> partition boundary, but emulated, not hardware-timed (no `/dev/kvm` on
> non-metal Graviton). The heterogeneous QNX-Safety / Linux-Compute split
> is carried by the **hardware twin** (Jetson Orin Nano), where L4T is the
> native Linux side and KVM works. The same QNX IFS and IPC code run on
> both sides; the **twin diff** (what changes when the host changes) is the
> deliverable. Cloud topology set by [ADR-002](docs/phase2-topology-decision.md).

![Phase](https://img.shields.io/badge/Phase-0%20bootstrap-yellow)
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
                  ┌──────── shared artifacts ────────┐
                  │ • QNX IFS  (mkqnximage virt)     │
                  │ • IPC client/server source       │
                  │ • Wire protocol (framed echo)    │
                  │ • Test harness + benchmarks      │
                  └────────────────┬─────────────────┘
                                   │ same binaries / same code
            ┌──────────────────────┴──────────────────────┐
            │                                             │
  ┌─────────v──────────┐                       ┌──────────v─────────┐
  │ Cloud twin (AWS)   │                       │ HW twin (Orin Nano)│
  │ build: Local       │                       │  host: L4T (Ubuntu)│
  │  Windows PC        │                       │  on A78AE × 6      │
  │  (EC2 fallback)    │                       │                    │
  │  run:  c7g.large   │ ── compare twin-diff ▶│  QEMU/KVM on Tegra;│
  │  QHV/qvm + 1 QNX   │   boot, mechanism,    │  L4T = Compute side│
  │  guest (TCG, no KVM)│  vs. hardware-timed  │  (heterogeneous IPC)│
  │  purpose: fast     │                       │  purpose: validate │
  │   iterate, sweep   │                       │   on real silicon  │
  └────────────────────┘                       └────────────────────┘

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

## Current Phase: 0 — Bootstrap

| Task | Status |
|------|--------|
| Repo scaffold + CLAUDE.md | ✅ |
| README v1 | ✅ (skeleton; refined per Phase) |
| Interview narrative draft | ✅ v0 (`docs/interview-narrative.md`) |
| BSP selection research | ⏳ pending Research Agent |
| `git init` + first commit | ⏳ (init done; commit pending review) |

---

## Known limitations (honest framing)

The whole point of the project is to be precise about what a software-layer
proxy can and cannot demonstrate. This table is the load-bearing part:

| DRIVE OS feature | QEMU proxy limitation |
|---|---|
| NVIDIA Hypervisor (Type-1) | Cloud leg runs the SDP 8.0 QNX Hypervisor (`qvm`) hosting one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (no `/dev/kvm` on cloud) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. Orin uses host-mediated KVM. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | Graviton3 (Neoverse-V1) is the runtime CPU; no Tegra-specific peripherals, no SoC-internal interconnect. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU virt machine. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | Graviton has no NVIDIA GPU; no CUDA, no vGPU partitioning. |
| Real-time guarantees | Cloud timing is TCG-emulation-bound (not hardware-timed); Orin is best-effort under KVM with observable host-scheduler jitter. The "Safety VM" framing is POSIX-realtime, not certified RT. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory latency | Cloud leg: host↔guest over the `qvm` virtio-console vdev (crosses the EL2/EL1 boundary, but TCG-emulated — the latency measures emulation cost, not transport cost). Orin leg (Phase 3): QNX↔Linux virtio-net → tap → bridge → tap → virtio-net, hardware-timed under KVM. Both orders of magnitude off DRIVE OS shared-memory IPC; profiled honestly. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. |

These are deliberate. Documenting them precisely is the engineering point.

---

## Setup

Detailed walkthrough is in [scripts/README.md](scripts/README.md). The
`scripts/bootstrap-*.sh` and `scripts/launch-*.sh` files cover each step.

**Hard prerequisite:** the user must obtain their own QNX Everywhere
license (NCEULA, free for personal use) and install QNX SDP 8.0
themselves. This repo does not — and per the NCEULA, cannot — ship any
QNX SDK components or QNX-derived binaries.

Other prereqs:
- AWS account with EC2 access in a region offering c7g and t3 instances
- `aws` CLI and SSH key configured
- ~50 GB disk on the build host for SDP install + IFS output
- Awareness that the Graviton runtime instance bills by the hour — see
  the cost note in [scripts/README.md](scripts/README.md)

---

## Roadmap

- [x] **Phase 0** — Bootstrap, scaffold, narrative, BSP selection, twin re-scope
- [ ] **Phase 1** — Cloud twin bring-up (SDP 8.0 QHV `qvm` + QNX guest on AWS, QEMU TCG — no Linux guest on cloud per [ADR-002](docs/phase2-topology-decision.md))
- [ ] **Phase 2** — Cloud twin IPC + P50/P99/P99.9 latency benchmark
- [ ] **Phase 3** — Hardware twin port to Jetson Orin Nano (same IFS, same code)
- [ ] **Phase 4** — Twin diff + DRIVE OS gap analysis
- [ ] **Phase 5** — FuSa & Cybersecurity overlay (FMEA, ASIL gap, STRIDE)
- [ ] **Phase 6** — Polish, demo recording, public release
- [ ] **Phase 7** _(stretch)_ — Multi-SoC domain-controller extension: add a Qualcomm-Cockpit-class proxy on AWS and exercise inter-SoC IPC (QC ↔ NV). Feasibility doc: [docs/future-multi-soc.md](docs/future-multi-soc.md)

---

## Skills / study artifacts

The `skills/` folder catalogs engineering paradigms studied alongside the build:

- [skills/fmea/](skills/fmea/) — FMEA paradigm + worksheet template
- [skills/iso-26262/](skills/iso-26262/) — ISO 26262 study scope
- [skills/aspice/](skills/aspice/) — Automotive SPICE process areas
- [skills/bsp-porting/](skills/bsp-porting/) — Generic BSP porting workflow
- [skills/qnx-safety/](skills/qnx-safety/) — QOS vs SDP framing

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
├── LICENSE                         # MIT (repo source only; QNX components excluded)
├── docs/                           # decision records, narrative, comparison docs
│   ├── architecture.md
│   ├── bsp-selection.md
│   ├── digital-twin-design.md      # twin methodology + sync mechanism
│   ├── drive-os-comparison.md
│   ├── findings.md
│   ├── interview-narrative.md
│   ├── orin-port.md                # Phase 3 detailed plan
│   └── security-model.md           # Phase 5 STRIDE + NCEULA audit
├── agents/                         # sub-prompt templates per agent
├── scripts/                        # cloud-twin bootstrap + QEMU scripts
│   ├── README.md
│   ├── bootstrap-build-host.sh
│   ├── bootstrap-runtime-host.sh
│   ├── build-qnx-ifs.sh
│   ├── setup-bridge.sh
│   ├── launch-qnx-vm.sh
│   ├── launch-linux-vm.sh
│   ├── orin/                       # Phase 3 hardware-twin scripts
│   └── twin/                       # Phase 4 cloud↔hw sync + diff scripts
├── ipc-test/                       # Phase 2 cross-VM IPC client/server
├── logs/sample-boot/               # curated boot logs (Phase 1)
├── results/cloud/                  # cloud-twin benchmark CSVs (Phase 2)
├── results/hw/                     # hw-twin benchmark CSVs (Phase 3)
└── skills/                         # study artefacts (existing 5 + 4 new for twin/jetson/tegra/cyber)
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
