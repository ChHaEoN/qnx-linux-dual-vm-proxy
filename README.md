# qnx-linux-dual-vm-proxy

A **Digital Twin design** of NVIDIA DRIVE OS dual-VM partitioning — a QNX
safety side beside a Linux general-purpose side — built on a Jetson Orin Nano
dev kit and a Windows PC instead of DRIVE hardware. Nothing in it is certified.

**This repository publishes no measured or functional results.** The QNX
licence does not allow it without the rights holder's written approval; the
results are kept locally. See [Results are held locally](#results-are-held-locally).

[docs/findings.md](docs/findings.md) is the authoritative, dated record;
everything below is a summary that can lag it. Ids such as A4, M5-F, OD11 and
P1 are explained under [Reading the ids](#reading-the-ids).

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
  partitioning: BSP bring-up, hypervisor host and guest, IPC patterns,
  kernel/userspace boundaries, host→target portability. Not a reproduction of
  DRIVE OS, and not a certified hypervisor.

- **The current arrangement (A6).** L4T on the metal owning the Ampere GPU,
  with QNX SDP 8.0 as a **KVM guest** beside it on the Orin's own Cortex-A78AE
  cores. The guest's `startup-qemu-virt` is one this repo rebuilds from board
  source, not the binary QNX ships — it is ours, so this is **not a
  QNX-supported configuration**.

- **What came before (A1–A5).** Emulated legs under QEMU TCG, then the QNX
  Hypervisor natively at EL2 on the Orin's own cores with a QNX and a Linux
  guest. That native direction was superseded, not withdrawn: **under a native
  QNX Hypervisor on Tegra234 no OS can use the GPU** — the iGPU has no SMMU
  stream ID, and its clock, reset and power go through BPMP, for which QNX has
  no client driver.

- **What was built.** The partition itself, a guest-side safety monitor and
  its claim protocol, six IPC paths across the boundary, an edge-AI service on
  the Linux side, a native-port toolchain, a measurement method with
  pre-registered tests and about fifty harnesses, bare-metal AWS tooling, and a
  CI gate over the repo's own prose. See [What was built](#what-was-built).

- **What it cannot show.** No certified Type-1 isolation, no freedom from
  interference, no real-time guarantee, no safety certification, no
  accelerator path for QNX. **No hardware-timed *hypervisor* number exists or
  ever will**: QHV needs EL2, ARM KVM does not nest on A78AE, and the TCG legs
  that were its only emulated route were withdrawn on 2026-09-20. See
  [Known limitations](#known-limitations-honest-framing) and
  [drive-os-comparison.md](docs/drive-os-comparison.md).

---

## Results are held locally

QNX SDP 8.0 is used here under the QNX Development License Agreement
(Non-Commercial/Academic Licence Class, v7). Its clause **4.6(i)** bars making
the results of any performance or functional evaluation of the software
available to any third party without BlackBerry's prior written approval.
That approval has not been obtained.

So this repository publishes **no measured or functional results** — no
latencies, boot times, rates, counts or pass/fail outcomes, on any leg or
host — and no conclusions drawn from them. The run records, CSVs and logs are
kept locally. What is published is the design, the source, the tooling, the
measurement method, the pre-registered predictions, and the limitations. Where
a document refers to a run, it names the run's record directory (for example
`20260921T-a6-orin-pinned`) and says that it is held locally.

---

## What was built

**The A6 partition.** QEMU with KVM on L4T hosts the QNX guest on two vCPUs
([`launch-qnx-kvm-bridged.sh`](orin-native/gpu-concurrency/launch-qnx-kvm-bridged.sh));
the host bridge `br0` and `tap-qnx` connect it to L4T
([`setup-bridge-orin.sh`](scripts/orin/setup-bridge-orin.sh)). The guest's
`startup-qemu-virt` is rebuilt here from board source
([`orin-native/startup/`](orin-native/startup/)), with the startup library
compiled `-fno-auto-inc-dec`. Every guest image is built with the SDP's
Windows-hosted tools, and each variant has its own build file and its own
monitor binary name, so no two images can be confused in a record.

**The guest's safety monitor**
([`monitor.c`](ipc-test/qnx-safety-monitor/monitor.c)). Pure POSIX with no
QNX-specific symbol, so the same source also builds natively on L4T as the
control for every guest arm. It judges claims carried in a fixed 64-byte frame
(a 16-byte header and a 48-byte payload,
[`frame.h`](ipc-test/common/frame.h)): kind 0 is an image-classification
claim, kind 1 a vision-language-model verdict. Modes add a liveness deadline
(armed by the first claim, one MISS per silence, RESTORED at the next claim,
stalled connections closed) and guest-side timestamps taken with
`clock_gettime(CLOCK_MONOTONIC)` into the reserved payload, which need no clock
synchronisation.

**IPC paths across the boundary** (owner decision OD12):

| Path | How it crosses |
|---|---|
| TCP | L4T client → `br0` → `tap-qnx` → virtio-net → the guest's `io-sock` |
| UDP | the same route, datagrams |
| Polled shared memory | one slot in QEMU's `ivshmem`, both ends polling; the guest maps the BARs itself through ECAM (`shmcfg`), with no PCI server |
| Notified shared memory | the host kicks the guest over a virtio console (`devc-virtio`); the guest answers over the console or through the `ivshmem` doorbell, which KVM handles in the kernel (ioeventfd) |
| Notified shared memory, by MSI-X | the host writes the guest's `ivshmem` eventfd, which QEMU or KVM turns into the device's MSI-X message, a write to the GIC ITS; the guest's startup sets the ITS up (`startup-qemu-virt-its`), `qnx-its-probe msixcfg` maps the vector to an LPI, and the monitor waits on it (`shmkick ivshmem@OFF msix`); the guest answers through the `ivshmem` doorbell as above |
| SOME/IP | a SOME/IP method in the guest (`qnx-someip-monitor`, TCP and UDP, the monitor's own judgement); on L4T a Python client, a C++ client, and the same C++ client through vsomeip 3.4.10 |

The doorbell *into* the guest exists as code. QEMU's `ivshmem` interrupts a
guest by MSI-X only, and this guest runs no PCI server, so the MSI-X path is
programmed by hand: [`startup-qemu-virt-its`](orin-native/startup/qemu-virt-its/)
sets up the GIC ITS in the startup, [`qnx-its-probe`](ipc-test/qnx-its-probe/)
maps the device's vector to an LPI,
[`ifs-bell.build`](ipc-test/qnx-safety-monitor/ifs-bell.build) is the build file
of an image that carries it, and
[`ivshmem_ring.py`](orin-native/gpu-concurrency/ivshmem_ring.py) rings the guest
from the host. It rests on a startup that is ours, so it is
not a QNX-supported configuration, and no result of it is published. A Cyclone
DDS variant of the monitor is in
[`ipc-test/qnx-dds-monitor/`](ipc-test/qnx-dds-monitor/), with notes in
[cyclonedds-qnx80.md](docs/middleware/cyclonedds-qnx80.md). vsomeip
(MPL-2.0) is built on the board by
[`build-vsomeip.sh`](orin-native/someip/build-vsomeip.sh) and never committed.
AUTOSAR CAPI is not used.

**An edge-AI service on the Linux side** (OD13, OD14,
[`orin-native/edge-llm/`](orin-native/edge-llm/)). A resident
vision-language model on L4T's GPU produces verdicts that travel to the QNX
guest as kind-1 claims; the monitor judges each against a fixed bound and,
in deadline mode, reports a missed deadline when the service falls silent. An
LLM load drives the GPU and the memory controller for interference arms. The
models are Apache-2.0, fetched and hash-pinned by script, and never committed;
no camera frame is ever kept.

**The native port** (A4, A5), in [`orin-native/`](orin-native/): a `kexec`
shim carrying an arm64 `Image` header that hands over at EL2; our own startup
board directory for Tegra234 (console, interrupt controller, timers, CPU
bring-up); an EFI loader for an attended entry from the firmware's UEFI Shell;
`qvm` configurations for a QNX guest and a stock Linux guest; and a trace
instrument. See [The native port](#the-native-port-phase-3b).

**A measurement method**, adopted as OD11 and written up in
[measurement-design.md](docs/measurement-design.md):

- **Budget.** n = 1000 timed samples per run after 200 warm-up, and k ≥ 12
  interleaved rounds — every round runs the whole arm set back to back, so
  drift in the machine hits every arm alike. The rule: n is set by the highest
  quantile an arm reports; the rest of the budget goes to k.
- **Reporting.** The headline is the median of the k round medians with the
  min–max band across rounds; an effect is the median of *paired* within-round
  differences, never a difference of medians. A tail statistic is never printed
  without k beside it, and the largest value is "largest observed", never
  "worst case".
- **Attribution.** A ladder of arms measured by one client — loopback on L4T,
  the bridge with no guest, the guest with a null server, the guest with the
  full monitor — so each rung isolates one segment. Guest-side timestamps split
  the monitor's own time from the rest; a frame-size sweep and an offered-rate
  sweep treat frame size and spacing as variables rather than settings; the
  guest's own kernel trace (`qnx-tracectl`, `guesttrace.py`) looks inside it.
- **Controls.** The CPU governor pinned and recorded before and after; QEMU's
  threads, the probe and every load pinned to named cores, with the map in the
  record; the memory-controller clock sampled per window under any GPU load;
  `nvpmodel`, the L4T release and the kernel's `CONFIG_HZ` stamped; the page
  cache dropped before GPU memory work; no SSH polling of the board during a
  run.

**Pre-registration.** Each hypothesis-driven harness states its question, its
predictions with thresholds (P1, P2, …) and its validity checks (M1, …) in its
own header, and is committed before any run of it, smoke runs included; the
predictions are not amended afterwards, and the record says when a smoke run
contradicted one. A demo and a latency run are always separate runs. The
harnesses are mostly `run-*.sh` / `*_report.py` pairs in
[`orin-native/gpu-concurrency/`](orin-native/gpu-concurrency/), their reporting
unit-tested on synthetic data under [`tests/`](tests/): the attribution ladder, interference and
saturation, UDP and shared memory, halt polling and vCPU placement, arrival
processes, tail decomposition (host ticks, the guest's timer, thermal-zone
polling, udev event handling, CPU confinement, kernel isolation), boot-to-boot
variance, frame size and socket reads, guest kernel traces, and SOME/IP.

**Bare-metal AWS tooling** ([`scripts/aws/`](scripts/aws/)). AWS is a test bed,
never a runtime host. Sessions on an `a1.metal` instance (Graviton1, with
`/dev/kvm`) are launched self-terminating with a shutdown timer as a safety
net, rehearsed on the Orin first, captured so that a lost SSH connection loses
nothing, and redacted at capture time; `terminate` refuses to run after an
upload until a fetch has passed. A6 ladder and harness sessions ran on
`a1.metal` from 2026-09-21 as a second host; their records are held locally.

**Safety and security study material** under [`docs/fusa/`](docs/fusa/),
[`docs/cyber/`](docs/cyber/) and [`docs/tara/`](docs/tara/): a Phase-1-gate
HARA/FMEA, safety concept, cybersecurity concept and TARA. Study-level work
products, not certification evidence.

---

## What is machine-checked

"Never write *it works* without a log, a number, or a diff" catches a figure
that was never measured. It does not catch one that was true when written and
drifted — two figures once published here were found wrong that way, by hand.
CI closes that class, and since results were withdrawn it also holds this file
to quoting none.

**Fails the build:** a number with a unit anywhere in this README unless a
claim in [`claims_gate.py`](scripts/ci/claims_gate.py) re-derives it from
committed data — and since no result data is committed, that is any figure at
all; asserted claims the record does not support, against a reviewable
[denylist](scripts/ci/claim-denylist.txt) matched per sentence so denials stay
legal; the same denylist over `scripts/**`, `orin-native/**` and
`ipc-test/**`, whose files are instructions a reader executes; a
strike-through in this file, which states current state and is rewritten
rather than annotated; the Phase badge against the Status table; and the
GitHub "About" field against its pin in
[docs/repo-description.md](docs/repo-description.md). The
[results guard](scripts/ci/results_guard.py) adds the routes this file's check
cannot see: a run record, CSV or boot log anywhere in the tree; a figure a
change adds to a harness's pre-registration ("what is known" cites records by
name, never quotes them), to `docs/` or to a README below the root; and a
figure in a pushed commit message. Design values it would otherwise question
are listed, each with its reason, in
[figure-allowlist.txt](scripts/ci/figure-allowlist.txt). The same guard runs
before a push as a [pre-push hook](scripts/githooks/pre-push), which is the
check that prevents rather than reports.

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
quantified, it is named as unquantified rather than left out. With every
result held locally, this README calls nothing working at all: it says what
was built and run, never what came of it.

This table is the load-bearing part:

| DRIVE OS feature | Limitation in this project |
|---|---|
| NVIDIA Hypervisor (Type-1) | The cloud leg (A1, history) is the SDP 8.0 QNX Hypervisor (`qvm`) with one QNX guest — a *real* EL2/EL1 partition boundary, but TCG-emulated (non-metal Graviton exposes no `/dev/kvm`; `*.metal` instances do) and **not** certified Type-1; no quantified freedom-from-interference, no mixed-criticality guarantees. The Orin plain leg (A2, history) is under TCG too. The native leg (A4) put the QNX Hypervisor at EL2 on the Orin's own cores with no QEMU — a real hypervisor on silicon, but not certified and not NVIDIA's: Experimental Software on a consumer dev kit. **Under A6, the current architecture, there is no Type-1 layer at all**: the partitioner is KVM and Linux — the largest TCB on the board — owns the QNX guest's memory, and the guest's startup is one this repo rebuilt, not a QNX-supported configuration. See [ADR-002](docs/phase2-topology-decision.md). |
| Orin SoC (Tegra234) | The cloud leg's as-built runtime CPU was the local x86_64 Windows host (Graviton3 was the design intent). On the Orin, a QEMU guest (A2, A6) sees QEMU's generic `virt` machine — no Tegra-specific peripherals, no SoC-internal interconnect. The native leg puts the QNX host directly on Tegra234 through this repo's own startup code (console, interrupt controller, timers, CPU bring-up); it has no storage, network, display, GPU, SMMU or PCIe drivers, and its guests see qvm's virtual devices, not Tegra peripherals. |
| NVDLA / PVA | Not emulated. Deep-learning and vision accelerators have no QEMU model. |
| MIPI CSI-2 (camera ingest) | Not emulated. No camera serial-link model in QEMU's virt machine; the edge-AI service's camera is a USB camera on L4T. |
| FSI R52 lockstep | Not emulated. No Cortex-R52 lockstep cluster, no Functional Safety Island. |
| GPU (Ampere CUDA / vGPU) | No leg passes a GPU to a guest. The cloud host has no NVIDIA GPU at all; the Orin Nano's Ampere iGPU belongs to L4T and is never exposed to the QNX guest — no in-guest CUDA, no vGPU partitioning. The native leg's S1 guest is Linux without a GPU. GPU pass-through is a later target, studied on a separate unpublished research track; no GPU stage has started. |
| Real-time guarantees | The QEMU-TCG legs (A1 to A3, history) were emulation-bound, not hardware-timed. **The TCG twin legs were withdrawn by owner decision on 2026-09-20; A6 measures under KVM only.** On A6 the guest is **never configured for real time** — the monitor is pure POSIX at default priority — and its vCPU threads are scheduled by a general-purpose Linux kernel beside every other host load. The "Safety VM" framing is POSIX-realtime, not certified RT. Nothing here bounds a tail: there is no WCET or WCRT analysis. |
| ASIL-D certification | None. SDP 8.0 ≠ QNX OS for Safety (QOS); no safety case, no MISRA-C, no ISO 26262 evidence. |
| Inter-VM shared memory | A1 (history): host↔guest over the `qvm` virtio-console vdev — it crosses the EL2/EL1 boundary, but TCG-emulated, so any latency there measures emulation cost, not transport cost. A2 (history): QNX↔Linux virtio-net → tap → bridge, also TCG-emulated. A6 crosses on real silicon under KVM, over TCP and UDP and over host↔guest shared memory in QEMU's `ivshmem`, polled and notified. None of the shared-memory paths is DRIVE OS's VM↔VM shared memory and mailbox, and the doorbell into the guest is QEMU's MSI-X through a GIC ITS that this repo's own startup sets up, not a hypervisor mailbox. What cannot exist under KVM is a figure for the `qvm` shared-memory path, because that path belongs to the QNX Hypervisor and QHV cannot run under KVM at all. **No hardware-timed *hypervisor* number exists on any leg and none ever will.** No sourced DRIVE OS IPC figure is in the repo, so no gap is quantified here. See [ADR-002](docs/phase2-topology-decision.md). |
| Certified bootloader chain | No SecureBoot, no measured boot, no chain-of-trust. The native leg's UEFI entry (M5-F) is an EFI loader of ours launched by hand from the firmware's Shell: not a supported, certified or unattended boot path. |

One limit sits outside the table because it is not a DRIVE OS feature: no
result of this project is published on any leg (see
[Results are held locally](#results-are-held-locally)), so nothing in this
repository lets a reader check one against data.

These are deliberate. Documenting them precisely is the engineering point.

---

## Architecture

The ids A1–A6 are the rows of the plan's
[architecture table](docs/orin-native-port-plan.md#architecture-versions).
Every earlier arrangement is history and is not re-run.

| id | arrangement | state |
|---|---|---|
| A1 | cloud leg: QHV (`qvm`) hosting one QNX guest under QEMU **TCG**, built on the local Windows PC rather than the AWS Graviton host the design called for | history |
| A2 | Orin plain leg: QNX under QEMU **TCG** beside L4T, QNX↔Linux IPC over `br0`/`tap-qnx` | history |
| A3 | the same QHV images under TCG on both hosts, the Windows PC and the Orin | history |
| A4 | the QNX Hypervisor **natively at EL2** on the Orin's own cores, entered by `kexec` from L4T, no QEMU | superseded as a direction |
| A5 | A4 plus a stock Linux guest under `qvm` (S1-F) | superseded with A4 |
| A6 | L4T on the metal with the GPU, QNX as a **KVM guest** | **current** |

**A6.** Linux is on the metal and keeps the GPU; QNX is a KVM guest beside it.
The partition boundary is real hardware EL2/EL1, but the supervisor is Linux —
there is no Type-1 layer, because QHV needs EL2 and ARM KVM does not nest on
A78AE.

```
 Jetson Orin Nano — Tegra234, six Cortex-A78AE cores, Ampere iGPU
 ┌──────────────────────────────────────────────────────────────────┐
 │  L4T / JetPack 7  — owns the machine                             │
 │                                                                  │
 │   CUDA / llama-server ────────────► Ampere iGPU                  │
 │                                       QNX never touches it       │
 │                                                                  │
 │   latency probe / service client on L4T                          │
 │        │ 64-byte frame: TCP, UDP, SOME/IP          ivshmem       │
 │        ▼                                    (polled / notified)  │
 │   br0 ── tap-qnx                                     │           │
 │        │ virtio-net                                  │           │
 │        ▼                                             ▼           │
 │  ┌────────────────────────────────────────────────────┐          │
 │  │ QEMU + KVM  — two vCPUs                            │          │
 │  │  ┌──────────────────────────────────────────────┐  │          │
 │  │  │  QNX SDP 8.0 guest — EL1, on A78AE           │  │          │
 │  │  │  procnto · io-sock · qnx-safety-monitor      │  │          │
 │  │  │  startup-qemu-virt rebuilt here:             │  │          │
 │  │  │  not a QNX-supported configuration           │  │          │
 │  │  └──────────────────────────────────────────────┘  │          │
 │  └────────────────────────────────────────────────────┘          │
 └──────────────────────────────────────────────────────────────────┘
```

The diagram names the release the board runs now. Every Orin record this
repository names was taken earlier, when the board ran JetPack 6.

**Why not a Type-1 hypervisor here.** A4 put the QNX Hypervisor natively at
EL2 on these cores. It is not withdrawn — it is simply no longer the
direction, because **under it no OS can use the GPU** on Tegra234: the iGPU has
no SMMU stream ID, and its clock, reset and power go through BPMP, for which
QNX has no client driver. Earlier architectures are closed and not redone;
each record keeps the id of the version it ran on.

Every QNX image is built on an x86_64 host — SDP 8.0 ships Windows and Linux
x86_64 host tools, no arm64 and no macOS.

Detail: [architecture.md](docs/architecture.md) ·
[digital-twin-design.md](docs/digital-twin-design.md) ·
[drive-os-comparison.md](docs/drive-os-comparison.md).

---

## Status

✅ closed · 🟡 in progress · ⬜ not started. Closed means the phase's work
stopped; it never meant the phase's original target was met.

| Phase | Status | Where to read |
|---|---|---|
| **0** — Bootstrap, BSP research, twin re-scope | ✅ closed | [bsp-selection.md](docs/bsp-selection.md) |
| **1** — Cloud twin bring-up: QHV `qvm` + QNX guest under TCG | ✅ closed as A1 history; results held locally | [ADR-002](docs/phase2-topology-decision.md) |
| **2** — Cloud twin IPC + latency | ✅ closed as A1 history; results held locally | [digital-twin-design.md](docs/digital-twin-design.md) |
| **3** — Hardware twin port (Orin Nano) | ✅ closed as A2 history (runs 2026-07-28 → 07-29, under TCG); results held locally; not re-run | [orin-port.md](docs/orin-port.md) |
| **3b** — Native QNX on the Orin, then A6 | 🟡 in progress — native rungs M0 → M5-F run 2026-09-09 → 09-13 and S1-F on 2026-09-17; A6's gate settled 2026-09-21 (OD10, OD11) and its campaign run 2026-09-21 → 09-27; results held locally, none published | [ADR-003](docs/adr-003-hardware-timed-qhv.md), [the plan](docs/orin-native-port-plan.md), [measurement-design.md](docs/measurement-design.md) |
| **4** — Twin diff + DRIVE OS comparison | ✅ closed 2026-09-20 — the twin diff was run under KVM on the Orin and on AWS `a1.metal` with a byte-identical image, its results held locally; the gap analysis is written | [digital-twin-design.md](docs/digital-twin-design.md), [drive-os-comparison.md](docs/drive-os-comparison.md) |
| **5** — FuSa & Cybersecurity overlay | ⬜ not started as a dedicated phase (a Phase-1-gate pass is committed) | [fusa/](docs/fusa/), [cyber/](docs/cyber/) |
| **6** — Polish, public README, demo | ⬜ not started | — |
| **7** _(stretch)_ — Multi-SoC / domain convergence | ⬜ feasibility frozen, not built | [future-multi-soc.md](docs/future-multi-soc.md) |

**On the word "cloud":** the QHV-hosted QNX guest and its IPC benchmark, *as
built*, ran on the **local Windows host under QEMU TCG** — not on the
Graviton instance the design called for, because non-metal Graviton exposes
no `/dev/kvm`/EL2 ([ADR-002](docs/phase2-topology-decision.md)). AWS never
hosted a leg. A bare-metal `a1.metal` instance, which does expose `/dev/kvm`,
was used as a second host: for KVM boot captures (2026-07-29, 2026-09-19), the
Phase 4 twin diff (2026-09-20), and A6 ladder and harness sessions from
2026-09-21. Every record from it is held locally.

**What is next** is not decided. Open: Phases 5 and 6; the Phase 7 stretch in
[future-multi-soc.md](docs/future-multi-soc.md), no longer held back behind
Phase 4; and publication of any result, which needs BlackBerry's written
approval first.

---

## The native port (Phase 3b)

QNX on the Orin's own cores with no QEMU, entered by `kexec` from L4T — a
shim carrying an arm64 `Image` header hands over at EL2 — or, in one attended
session, by our own EFI loader from the firmware's UEFI Shell. Each rung has a
design record and a pre-stated target:

| Rung | What it targets |
|---|---|
| **M0** | `kexec` from L4T hands over at EL2 |
| **M1** | QNX natively on the Orin, with the SDP's stock userspace |
| **M2** | all six cores brought up through PSCI `CPU_ON`, under a pinned load |
| **M1b** | the VHE host at EL2 with E2H/TGE on every core |
| **M3** | native `qvm` with the byte-identical cloud-leg QNX guest |
| **M4-F** | a trace instrument on the board |
| **M5-F** | a UEFI cold boot through our own loader, attended |
| **S1-F** | a stock Linux guest under native `qvm`, then both guests at once |

The rungs were run between 2026-09-09 and 2026-09-17; their records are held
locally, and **no hardware-timed hypervisor number exists or ever will.**
Each design record from M1b to S1 carries a review section, and an independent
review narrowed M4-F's claim before it was recorded.

Procedures, claims register and every owner decision: [the
plan](docs/orin-native-port-plan.md).

---

## Reading the ids

- **A1–A6** — architecture versions, in the table under
  [Architecture](#architecture).
- **M0–M5-F, S1-F** — rungs of the native port, above.
- **OD1–OD15** — owner decisions, each in full in
  [the plan](docs/orin-native-port-plan.md).
- **P1, P2, … / M1, M2, …** — a harness's pre-registered predictions and its
  validity checks, stated in that harness's header.
- **`2026MMDDT-…`** — a run's record directory, named by date, architecture,
  host and experiment; every one is held locally.

---

## Setup

Walkthrough: [scripts/README.md](scripts/README.md). Which scripts apply
depends on the leg, per [ADR-002](docs/phase2-topology-decision.md):
`scripts/qhv/` for A1, `scripts/orin/` for A2 and A6, `orin-native/` for the
native port and A6's harnesses, `scripts/twin/` for the diff, `scripts/aws/`
for bare-metal sessions.

⚠️ `scripts/setup-bridge.sh` and `scripts/launch-linux-vm.sh` belong to the
**Orin** path, not the cloud leg: the cloud dual-VM-over-a-bridge topology they
were written for was falsified by ADR-002 and is kept only for that lineage.

**Hard prerequisite:** you must obtain your own QNX licence and install QNX
SDP 8.0 yourself. This repo does not — and per the licence, cannot — ship any
QNX SDK component or QNX-derived binary, and it publishes no evaluation result
of the software (see [Results are held locally](#results-are-held-locally)).

Board work needs a 3.3 V USB-TTL adapter on the Orin's J14 header (never a
5 V-only one) and someone at the plug: do not rely on the CCPLEX watchdog
after `kexec` — a hung run needs a physical power cycle.

---

## Repository layout

| Path | What |
|---|---|
| [`docs/`](docs/) | narrative, decisions, the dated record, the measurement design |
| [`orin-native/`](orin-native/) | native-port source (shim, board directory, EFI loader, guest configs), A6's harnesses, the edge-AI service, SOME/IP tooling |
| [`ipc-test/`](ipc-test/) | C99 IPC: the guest's safety monitor and its variants, echo and benchmark servers, host and Linux clients, shared-memory probes, the shared frame |
| [`scripts/`](scripts/) | bring-up, QHV configs, twin sync and diff, AWS bare-metal tooling, the CI claims gate |
| [`results/`](results/) | the results CSV schema and the native port's design and research records; run records are held locally |
| [`tests/`](tests/) | unit tests for the harnesses' reporting and for the CI gate, on synthetic data |

**Start here:** [findings.md](docs/findings.md) is append-only, dated, and the
record when anything else disagrees with it.
[drive-os-comparison.md](docs/drive-os-comparison.md) is the calibration — what
this can and cannot say about DRIVE OS.
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
The user supplies their own QNX SDP 8.0 install under its own licence. Under
clause 4.6(i) of the QNX Development License Agreement
(Non-Commercial/Academic Licence Class, v7), no result of evaluating that
software is published here.
