# Findings Log — append-only, newest at top

A running record of empirical findings, surprises, and decisions that
came out of actually running the toolchain. Phase 0 entries point to
their detailed write-ups; Phase 1+ entries will land here directly.

Format: one entry per finding, dated, one-paragraph max plus links.

---

## 2026-06-11 — Milestone (Phase-7 pull-forward): QNX Hypervisor (QHV) boots a QNX guest under QEMU-TCG

Brought the Phase-7 QHV exploration forward and got a **real Type-1 hypervisor
hosting a guest**, entirely on the local Windows build host — no AWS, no KVM.
Chain of findings: (1) AWS non-metal Graviton exposes **no `/dev/kvm`** (proven
empirically on a t4g.small probe — EL2 is not passed through by Nitro), so any
hardware-accelerated hypervisor (KVM *or* QHV) needs `*.metal` or real silicon;
the accessible path to *demonstrate* QHV is QEMU-TCG emulating an EL2-capable
CPU. (2) SDP 8.0.4 already ships the QHV host: `qvm` aarch64 binary
(`target/qnx/aarch64le/sbin/qvm`), `libhyp`, and `target.hypervisor.core` are
installed. (3) Official build path is mkqnximage: `--type=qvm` builds the guest,
`--type=qemu --qvm=yes --guest=<dir>` builds the host that embeds it under
`/data/hypervisor/`. (4) Boot under `qemu-system-aarch64 -machine
virt,virtualization=on -cpu max -accel tcg` so QHV's `el2-host`/VHE comes up.
**Result:** host boots as `qnx-qhv` (machine `QEMU_virt`); `qvm @g2.conf` then
boots a guest that reaches `Startup complete` as `qnx-guest` on machine
`ARMv8_Foundation_Model` — the *virtual* platform QHV synthesises, i.e. the
Type-1 partition boundary is real. Curated log:
[../logs/sample-boot/qhv-tcg-host-and-guest-boot.log](../logs/sample-boot/qhv-tcg-host-and-guest-boot.log).
Gotchas recorded: the stock `start_guest` wires a virtio-net peer that needs the
host io-sock stack, which does **not** initialise on this qemu-virt build
(`network stack down` / `Address family not supported`) — worked around with a
no-network qvm config auto-started via a custom `post_start.custom` snippet;
driving the guest start over the TCG serial console interactively drops
characters, so the start was baked into the image instead. **Honest framing:**
TCG proves the QHV *software* architecture (qvm config, vdev instantiation, guest
isolation, EL2/VHE host) — not hardware timing/acceleration (needs metal/Orin).
Note this supersedes the earlier Track-A framing where the cloud leg ran a QNX
*Neutrino* guest under QEMU/**KVM** on c7g.large — that KVM-on-cloud assumption is
now falsified (see finding chain above); KVM acceleration belongs on Orin (Phase 3).

---

## 2026-06-10 — Phase 1 finding: first QNX aarch64 IFS built on the Windows host (missing `target.qemuvirt` package)

First real `mkqnximage --type=qemu --arch=aarch64le --build` on the local
Windows build host (SDP 8.0.4, install root `C:\Users\andy8\qnx800`) **failed**
with `Host file 'startup-qemu-virt' not available / Failed to create ifs boot
image`. Root cause: a default SDP 8.0.4 install carried the aarch64 kernel
(`procnto-smp-instr`), the `*.boot` prefabs and the aarch64 host toolchain, plus
the **`com.qnx.qnx800.quickstart.qemu`** prebuilt run-image — but **not**
**`com.qnx.qnx800.target.qemuvirt`**, which is the package that installs the
board startup binary `startup-qemu-virt` into
`target\qnx\aarch64le\boot\sys\`. `mkqnximage`'s `--build` needs that startup
binary; `quickstart.qemu` (a ready-to-run image) does not provide it. Fix was
CLI-only, no GUI: `qnxsoftwarecenter_clt.bat -installIU
com.qnx.qnx800.target.qemuvirt` (use `-list` / `-listInstalledRoots` to
inspect). After install the build **succeeded**: `ifs.bin` ~9.3 MB plus a raw
disk. This is a genuine BSP-bring-up flavour finding — an incomplete
package-dependency selection on the build host, exactly the class of issue real
BSP integration hits. **Honest framing:** this is build-host tooling, not a port
— it says nothing about whether the IFS boots on Graviton (still the open
Phase 1 question below). Secondary finding: `mkqnximage` emits a **split VMDK** —
`disk-qemu.vmdk` is only a ~169-byte `monolithicFlat` *descriptor* pointing at the
~150 MB raw extent `disk-qemu`; the repo's scp/README/`twin/sync.sh` instructions
listed only `ifs.bin` + `disk-qemu.vmdk`, which would fail to boot on the runtime
host. Corrected across `scripts/` in the same commit (extent now travels with the
descriptor everywhere; raw-disk alternative documented).

---

## 2026-06-10 — Decision: adopt a two-track hybrid (keep QEMU-IFS BSP track, add QNX-on-AWS AMI runtime)

Triggered by the discovery that AWS Marketplace offers a **QNX OS 8.0 AMI**
(the "QNX Accelerate" / Graviton path), where QNX runs as the EC2 instance OS
directly — no QEMU, no custom IFS, no BSP bring-up. Rather than pivot the whole
project to the AMI (which is far lower-friction but discards the BSP /
bootloader / dual-VM partition story that is this portfolio's strongest DRIVE OS
SE differentiator), the project adopts a **hybrid**: **Track A** keeps the
existing QEMU-guest / self-built-IFS path (dual-VM partition proxy on Graviton +
Orin hardware twin) for the BSP, bootloader, partition-isolation and twin-diff
narrative; **Track B** adds the QNX-on-Graviton AMI as a low-friction *single*
QNX target for the application layer — native IPC / resource-manager / scheduling
demos, cross-compile→S3→run pipeline, GitHub-Actions CI/CD, and a standalone
`docs/virtual-target-analysis.md` writeup. Architectural caveat recorded: the AMI
makes QNX the OS, so the **dual-VM partition model stays on Track A only**; Track B
is single-QNX by construction. Unexpected upside: Track B adds a **third runtime
substrate** (QEMU-guest vs AMI-on-Nitro vs Orin), turning the Phase 4 twin diff
from a 2-point into a 3-point comparison. Build-host decision for Track B: **no
persistent cloud x86 build host** — use GitHub-Actions hosted runners for CI
builds plus the existing local Windows SDP for dev iteration (flagged open risk:
headless SDP install + Everywhere license activation in CI is non-trivial; license
via secrets/SSM, SDP install cached). Track B infra to be Terraform under
`infra/` (one c7g.xlarge from the AMI + restricted SG + S3), AMI ID as a
variable since Marketplace subscription is a human prerequisite; cost estimate
~$15–20/mo + unknown AMI software fee (verify on listing), well under the €100
target. **Status:** decision recorded; Terraform not yet written (awaiting
Marketplace subscribe + software-fee confirmation + explicit apply approval).

---

## Phase 1 — Cyber-Analysis TARA (TBD: gate review)

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**
>
> Starting-point Phase 1 cloud-twin TARA produced by the Cyber-Analysis
> agent before any IPC traffic exists. Full document:
> [tara/phase1-cloud-tara.md](tara/phase1-cloud-tara.md). 21 threat
> scenarios across the QNX guest, Linux guest, host bridge `br0`, and
> IFS build pipeline. Top-3 risk: **T4** Linux→QNX bridge flood
> starving the Safety guest's virtio-net ring (Risk 5, cyber-FuSa
> candidate); **T17** tampered `mkqnximage` build inputs producing a
> malicious IFS booted by both twins (Risk 4, supply-chain cyber-FuSa
> candidate); **T7** tampered Ubuntu cloudimg subverting the Compute
> guest kernel (Risk 4, cyber-FuSa candidate). Thirteen threats are
> flagged as cyber-FuSa interaction candidates (T1, T2, T4, T5, T6,
> T7, T10, T11, T12, T14, T15, T17, T21) for joint review with the
> parallel FuSa-Analysis HARA at the Phase 1 gate — note especially
> the alignment with FuSa's B5 (bridge L2 promiscuity) and K2 (wrong /
> cached IFS) findings. Six open questions handed to Cyber-Design
> (peer authentication, anti-replay primitive, `tap-qnx`
> rate-limiting, build-pipeline integrity controls, KVM-escape
> posture, bridge MAC filtering). §2 of
> [security-model.md](security-model.md) updated with populated
> Likelihood/Impact ratings.

---

## Phase 1 — FuSa-Analysis HARA (TBD: gate review)

> _Study-level only; not certification evidence._
>
> Initial HARA + Design FMEA for the Phase 1 cloud twin (QNX SDP 8.0 +
> Linux aarch64 on Graviton QEMU/KVM) is captured in
> [`skills/fmea/examples/phase1-cloud-bringup-fmea.md`](../skills/fmea/examples/phase1-cloud-bringup-fmea.md).
> Scope is the cloud twin only; Orin / hardware-twin failures are
> deferred to Phase 3. Top hazards at notional integration level:
> HE-02 / HE-03 / HE-06 (loss or stale Safety-partition IPC) score
> ASIL-D under the study's notional vehicle integration; HE-04 / HE-07
> / HE-13 / HE-15 score ASIL-C. Top D-FMEA rows (RPN ≥ 60) are H1
> (KVM trap unbounded latency), Q6 (RT deadline miss from KVM trap),
> B2 (stale tap flap), B5 (bridge L2 promiscuity — also a cyber-FuSa
> interaction candidate), N3 (KVM IRQ tail latency), N1 (silent
> virtio-net drop), and K2 (wrong / cached IFS at runtime). Ten open
> questions are handed to FuSa-Design (FTTI numbers, payload integrity
> layer above virtio-net, freedom-from-interference residual-risk
> argument given the shared host kernel, IFS integrity binding from
> build to runtime). Pair-review with Cyber-Analysis at the Phase-1
> gate to close the five interaction-analysis items called out in the
> worksheet.

---

## Phase 4 — TBD: cloud-vs-HW twin diff

> _Stub. Filled in after the twin-diff measurement run lands. Expected
> contents: P50/P99/P99.9 latency delta, boot-time delta, jitter
> profile delta. Hypothesis going in: IPC-path latency tracks within
> a small constant; boot times diverge meaningfully due to host CPU
> and scheduler differences._

---

## Phase 3 — TBD: hardware twin port to Jetson Orin Nano

> _Stub. Filled in after the same `mkqnximage --type=qemu --arch=aarch64le`
> IFS has been booted on QEMU-on-Orin under L4T. Expected contents:
> (a) does the unmodified IFS boot? (b) JetPack 6 KVM availability;
> (c) RAM headroom on 8 GB; (d) any GICv3 / A78AE quirks._

---

## Phase 2 — TBD: cloud-twin IPC latency baseline

> _Stub. Filled in after the C99 client/server has been run to 100k
> iterations. Expected contents: P50, P99, P99.9 of round-trip on
> Graviton + virtio-net + host bridge; time-base normalisation
> notes; warm-up tail behaviour._

---

## Phase 1 — TBD: cloud-twin bring-up

> _Stub. Filled in after both VMs boot under KVM-on-Graviton. Expected
> contents: virtio-mmio vs virtio-pci default in mkqnximage SDP 8.0;
> whether x86_64-built aarch64 IFS runs under KVM-on-Graviton without
> modification; QNX boot time on Graviton._

---

## 2026-05-07 — Phase 0 amendment: build host pivots to local Windows (EC2 fallback retained)

F1 in [bsp-selection.md](bsp-selection.md) previously asserted "QNX SDP
8.0 host toolchain is x86_64 Linux only." A second pass through the
QNX Software Center download matrix on a QNX Everywhere account
confirmed that SDP 8.0 ships **both** a Linux x86_64 native installer
**and** a Windows native installer; macOS (Intel and Apple Silicon)
remains unsupported. The earlier wording was a partial inspection,
not a complete one, and is being corrected. Consequence: the
build-host role moves from "AWS t3.medium x86_64 Ubuntu (rented EC2)"
to **local Windows PC as the primary path**, with the EC2 x86_64
build host retained as an explicit **fallback** for users without a
local x86_64 Windows or Linux machine. Cost win: removes EC2
build-host hours from the AWS Free Plan budget (~$100 / 98 days
remaining at decision time; existing $80/month budget alert and $5/day
Cost Anomaly Detection unchanged). Friction win: removes ssh / X11 /
browser-flow hops needed to drive the QNX Software Center GUI on a
remote EC2 box. Validation surface unchanged: per F1's existing
arch-agnostic-IFS argument, `mkqnximage --arch=aarch64le` produces
the same blob whether run on Windows or Linux x86_64; runtime side
stays Graviton arm64. Honest-framing caveats: the build host runs only `mkqnximage` and
host-side QNX tooling — no guests run on the build host — and the
IFS it produces is target-aarch64, cross-compiled by SDP 8.0's
host toolchain. Per F1's arch-agnostic-IFS argument, swapping
Windows for Linux x86_64 on the build host affects only build
metadata (embedded paths, timestamps), not the ARM code QNX boots;
F5 Q2 already validates the load-bearing claim that *any*
x86_64-built IFS boots on Graviton, and that question is host-
platform-agnostic. (An earlier wording of this amendment treated
"Windows-built vs EC2-built byte-equivalence" as a separate
Phase 1 verification target — that was over-specified and is
withdrawn in the same commit that corrects it; see the F5 note in
[bsp-selection.md](bsp-selection.md).) A local Windows build host
also **does not** demonstrate any closer parity to a real DRIVE OS
customer build environment than EC2 does — it is purely a
friction/cost optimisation, not an architectural improvement. Cross-link: see F1
in [bsp-selection.md](bsp-selection.md). Implementation agent will
follow up with the actual edits to F1, README.md, CLAUDE.md,
docs/architecture.md, scripts/README.md,
scripts/bootstrap-build-host.sh, agents/research.md,
agents/implementation.md, and a new scripts/build-qnx-ifs.bat.

---

## Apr 2026 — Phase 0 BSP research

QNX SDP 8.0 host toolchain is x86_64-only, which forces a hybrid
build/runtime architecture (x86_64 build host → arm64 runtime host).
Two BSP paths are viable under SDP 8.0: the official `mkqnximage
--type=qemu --arch=aarch64le` (used as the Phase 1 baseline) and the
community MIT-licensed `joexue/qemu-virt` (deferred to Phase 2+
study). KVM acceleration on Graviton works with stock Ubuntu 22.04.
The QNX Everywhere NCEULA covers personal/portfolio/demo use but
forbids redistributing QNX binaries — so the repo ships scripts and
logs only, never IFS images.

Full write-up: [bsp-selection.md](bsp-selection.md).
