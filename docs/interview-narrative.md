# Interview narrative — qnx-linux-dual-vm-proxy

> **Status:** v0 draft (Phase 0); cloud topology updated per
> [ADR-002](phase2-topology-decision.md). Refine after Phase 1 with real
> numbers (boot time, cloud `qvm` virtio-console P99 — TCG-bound, not a
> transport benchmark — EC2 cost) and after Phase 3 with the
> comparison-doc findings (Orin KVM virtio-net is the hardware-timed leg).
> **Length target:** 2 minutes spoken (~250–280 words).
> **Audience:** NVIDIA AVOS / DRIVE OS Software Engineer interview.

---

## 30-second elevator version (v0)

> I built a Digital Twin design of NVIDIA DRIVE OS dual-VM partitioning —
> QNX SDP and Linux running under QEMU on AWS Graviton (cloud twin) and
> on a Jetson Orin Nano dev kit (hardware twin) — to study the BSP, IPC,
> and kernel-boundary work an SE supporting DRIVE OS customers does
> day-to-day. The cloud side is a software-layer proxy for fast iteration;
> the Orin side validates the same artefacts on real Tegra-class silicon.
> I'm explicit about the honest gap vs. a real hypervisor partition; that
> gap analysis is part of what I'm publishing.

---

## 2-minute spoken version

> At DENSO I work on E/E architecture and SDV platform research,
> including hands-on experience with QNX on automotive SoC targets.
> To deepen my understanding of NVIDIA's DRIVE OS architecture —
> specifically the dual-VM partition model — I built a personal
> project across two host substrates. On the cloud leg I run QNX's
> own Type-1 hypervisor (QHV) hosting a QNX guest on AWS Graviton,
> with IPC between the hypervisor host and its guest across the
> partition boundary; the heterogeneous QNX-Safety / Linux-Compute
> split I carry to a Jetson Orin Nano, where Linux (L4T) is the native
> host and KVM actually works.
>
> I want to be upfront about what each leg does and doesn't show. The
> cloud leg crosses a *real* `qvm` EL2/EL1 partition boundary — that's
> the strongest hypervisor artefact in the project — but it runs under
> QEMU TCG emulation because non-metal Graviton exposes no `/dev/kvm`,
> so any latency number there is dominated by emulation cost, not a
> real transport or hardware-timed IPC cost. It also doesn't show OS
> heterogeneity: both ends are QNX on the cloud leg, and the
> QNX-to-Linux story lives on Orin. Either way it's a software-layer
> proxy, not a replica — things like NVDLA, MIPI CSI-2, and FSI R52
> lockstep simply cannot be emulated, and the IPC latency is orders
> of magnitude off from shared-memory between real DRIVE OS VMs. (The
> topology decision and its honest-framing ledger are recorded in
> docs/phase2-topology-decision.md.)
>
> One concrete engineering takeaway from the project setup itself:
> QNX SDP 8.0 doesn't support ARM hosts, so I designed a hybrid
> build/runtime architecture — build the IFS on an x86_64 host
> (Windows or Linux), then scp the image to a Graviton arm64 instance
> for KVM-accelerated execution. That kind of toolchain-constraint
> discovery is the day-to-day of BSP work.
>
> The takeaway for me was concrete intuition for which DRIVE OS
> design choices are hardware-driven versus software-configurable,
> which I think is directly relevant to BSP work on this platform.
>
> One more thing — I designed it as a Digital Twin: the same QNX IFS
> and the same IPC code run on AWS as the cloud twin and on a Jetson
> Orin Nano dev kit as the hardware twin. Orin Nano uses Cortex-A78AE,
> the same core family as DRIVE Orin's CCPLEX, so the hardware twin
> validates the cloud-twin work on real Tegra-class silicon. The
> twin-diff measurement — how latency, jitter, and boot-time change
> when only the host changes — is the part I think tells the most
> honest story about what cloud simulation can and cannot give you
> versus a real-target bring-up. That maps directly to how DRIVE OS
> customers actually do bring-up: develop in the cloud, validate on
> target.

---

## 10-minute deep-dive version

> _Outline. Fleshes out after Phase 4 (twin diff) so each section
> can be backed by measured numbers rather than intuition._

**Section 1 — Why this project exists (1 min).** DENSO E/E architecture
work + QNX hands-on; gap I wanted to close was concrete familiarity with
DRIVE OS partition behaviour from the customer-port perspective. Honest
framing front-loaded: this is a Digital Twin design, not a hypervisor.

**Section 2 — Architecture choices (2 min).** Cloud twin runtime on
AWS Graviton (c7g.large, KVM-on-arm64); build host is local Windows
since SDP 8.0 host toolchain is x86_64-only and ships both Linux and
Windows installers (EC2 t3.medium fallback if no local x86_64 host).
Hardware twin on Jetson Orin Nano because A78AE matches DRIVE Orin's
CCPLEX core family. The "same IFS, same IPC code, only host changes"
property is the design's load-bearing claim — walk through how the
twin diff isolates host-effects from code-effects.

**Section 3 — One concrete BSP-engineering story (1.5 min).** SDP 8.0's
x86_64-only host requirement forced the hybrid build/runtime
architecture. Walk through what I tried, what didn't work, what the
fix was, and what that taught me about toolchain-constraint discovery
in customer-port BSP work.

**Section 4 — IPC measurement methodology (1.5 min).** Cloud leg:
host↔guest over the `qvm` virtio-console vdev (single-OS QNX↔QNX, both
ends `ClockCycles()`) — honest caveat that this number is TCG-emulation-
bound, not a transport cost (per [ADR-002](phase2-topology-decision.md)).
Orin leg (Phase 3): heterogeneous QNX↔Linux over virtio-net under KVM,
where the cross-clock time-base normalisation between QNX `ClockCycles()`
and Linux `clock_gettime(CLOCK_MONOTONIC)` re-enters and the
hardware-timed number appears. Framed echo protocol; P50/P99/P99.9
reporting choice; warm-up exclusion. **Insert real numbers from
`results/cloud/` and `results/hw/` once Phase 2 / 3 land.**

**Section 5 — Twin diff — what actually changes (2 min).** The
results from Phase 4. **Insert measured cloud-vs-hw delta numbers.**
Hypothesis going in is that boot times will diverge meaningfully
(host CPU and scheduler differ) but the IPC-path latency profile
will track each other within a small constant — testing that
hypothesis is the experiment.

**Section 6 — Honest gap to real DRIVE OS (1.5 min).** Walk a few
rows of the comparison table: what validates (concept of co-resident
OSes; IPC framing; tail-latency methodology; cloud→target portability),
what's partial (asymmetric workload shape; boot sequencing), what
cannot validate (Type-1 isolation; certified RT; FSI lockstep; NVDLA;
Secure Boot chain). Lead with what *cannot* validate, not what does —
that's what the customer cares about.

**Section 7 — Optional Phase 7 / multi-SoC extension (0.5 min).** Mention
the future-multi-soc.md design exploration as the upgrade path: same
twin framework, plus a Qualcomm-Cockpit-class proxy on AWS, exercising
inter-SoC IPC. Only mention if asked or if time allows.

---

## JD-aligned vocabulary checklist

Use these terms once each in any longer-form telling:

- **BSP bring-up** (aarch64 virt machine)
- **Device driver internals** (virtio-console on cloud; virtio-net on Orin)
- **Kernel / userspace boundary**
- **`qvm` vdev IPC across the EL2/EL1 partition boundary** (cloud); virtio-net partition-style isolation (Orin)
- **POSIX real-time** (QNX side)
- **Customer port path**
- **Program KPIs**
- **Hypervisor partition reference** (the *thing* this proxies)
- **ASIL / ISO 26262** (only when discussing the gap, never as a claim)

---

## Refinement checklist (per phase)

- [ ] Phase 1: insert real numbers — QHV host + QNX-guest boot time; `qvm` virtio-console channel verified (no virtio-net link on cloud per ADR-002)
- [ ] Phase 2: insert real P50 / P99 / P99.9 round-trip latency
- [ ] Phase 3: insert one-sentence summary of the gap analysis's most-surprising finding
- [ ] Phase 4: re-time spoken version against a stopwatch; trim to 110 sec

---

## Customization slots (when targeting a specific JD)

- **Customer-facing phrasing:** swap "AVOS / DRIVE OS team" for the specific team
- **Cost framing:** mention `c7g.large` cost discipline if interviewer is platform-eng
- **Cert framing:** lean harder on `skills/iso-26262/` if JD emphasizes ASPICE/26262
- **Hypervisor framing:** if JD explicitly says "hypervisor experience," lead with the
  Phase 3 gap analysis instead of the Phase 1 bring-up
