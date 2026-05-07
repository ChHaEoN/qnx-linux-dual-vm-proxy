# Findings Log — append-only, newest at top

A running record of empirical findings, surprises, and decisions that
came out of actually running the toolchain. Phase 0 entries point to
their detailed write-ups; Phase 1+ entries will land here directly.

Format: one entry per finding, dated, one-paragraph max plus links.

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
