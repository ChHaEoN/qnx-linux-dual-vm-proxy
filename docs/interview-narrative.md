# Interview narrative — qnx-linux-dual-vm-proxy

> **Status:** v0 draft (Phase 0); cloud topology updated per
> [ADR-002](phase2-topology-decision.md). Refine after Phase 1 with real
> numbers (boot time, cloud `qvm` virtio-console P99 — TCG-bound, not a
> transport benchmark — EC2 cost) and after Phase 3 with the
> comparison-doc findings (Orin virtio-net ran under TCG; the
> hardware-timed route is the native port, measured in the v1 campaign).
> **Length target:** 2 minutes spoken (~250–280 words).
> **Audience:** NVIDIA AVOS / DRIVE OS Software Engineer interview.
>
> **2026-07-29:** added a dedicated Q&A section for the GICv3/NISV KVM
> finding (real bug, real root cause, honestly unresolved) and a
> pivot note for DENSO-PoC-flavored questions pointing at the new
> single-SoC domain-convergence track in
> [future-multi-soc.md](future-multi-soc.md).
>
> **2026-09-11:** corrected the leg descriptions below (the cloud leg ran
> under QEMU TCG on a Windows PC, and the Orin legs under TCG, not KVM) and
> added the native-port update to the GICv3/NISV Q&A.

---

## 30-second elevator version (v0)

> I built a Digital Twin design of NVIDIA DRIVE OS dual-VM partitioning —
> QNX under QEMU TCG on a Windows PC (cloud twin; AWS non-metal Graviton
> had no `/dev/kvm`) and QNX beside Linux on a Jetson Orin Nano dev kit
> (hardware twin) — to study the BSP, IPC,
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
> own Type-1 hypervisor (QHV) hosting a QNX guest under QEMU TCG on a
> Windows PC, because AWS non-metal Graviton has no `/dev/kvm`, with IPC
> between the hypervisor host and its guest across the partition
> boundary; the heterogeneous QNX-Safety / Linux-Compute split I carry
> to a Jetson Orin Nano, where Linux (L4T) is the native host and the
> QNX guest runs under TCG, because a GICv3 defect blocks the KVM boot.
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
> (Windows or Linux), then boot the aarch64 image under QEMU TCG on that
> PC, or on the Orin under TCG or natively. That kind of
> toolchain-constraint
> discovery is the day-to-day of BSP work.
>
> The takeaway for me was concrete intuition for which DRIVE OS
> design choices are hardware-driven versus software-configurable,
> which I think is directly relevant to BSP work on this platform.
>
> One more thing — I designed it as a Digital Twin: the same hypervisor
> images boot on my Windows PC as the cloud twin and on a Jetson Orin
> Nano dev kit as the hardware twin. Orin Nano uses Cortex-A78AE,
> the same core family as DRIVE Orin's CCPLEX, so the hardware twin
> validates the cloud-twin work on real Tegra-class silicon. The
> twin-diff measurement — how latency, jitter, and boot-time change
> when the host bundle changes (CPU, OS, emulator build), re-run once
> the reference architecture is frozen — is the part I think tells the most
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

**Section 2 — Architecture choices (2 min).** Cloud twin runtime
designed for AWS Graviton (c7g.large, KVM-on-arm64); as built it runs
under QEMU TCG on the local Windows PC, because non-metal Graviton has
no `/dev/kvm`. The build host is local Windows
since SDP 8.0 host toolchain is x86_64-only and ships both Linux and
Windows installers (EC2 t3.medium fallback if no local x86_64 host).
Hardware twin on Jetson Orin Nano because A78AE matches DRIVE Orin's
CCPLEX core family. The "same IFS, same IPC code, only host changes"
property was the design's load-bearing claim — walk through why it had
to be restated: the Orin IPC leg used a rebuilt IFS, and "host" is a
bundle (CPU, OS, TCG backend, QEMU build), so the twin diff compares
host bundles and is re-run on reference architecture v1.

**Section 3 — One concrete BSP-engineering story (1.5 min).** SDP 8.0's
x86_64-only host requirement forced the hybrid build/runtime
architecture. Walk through what I tried, what didn't work, what the
fix was, and what that taught me about toolchain-constraint discovery
in customer-port BSP work.

**Section 4 — IPC measurement methodology (1.5 min).** Cloud leg:
host↔guest over the `qvm` virtio-console vdev (single-OS QNX↔QNX, both
ends `ClockCycles()`) — honest caveat that this number is TCG-emulation-
bound, not a transport cost (per [ADR-002](phase2-topology-decision.md)).
Orin leg (Phase 3): heterogeneous QNX↔Linux over virtio-net under TCG
(KVM boot blocked), where the cross-clock time-base normalisation between
QNX `ClockCycles()` and Linux `clock_gettime(CLOCK_MONOTONIC)` re-enters.
The hardware-timed number comes from the native QNX Hypervisor in the v1
campaign. Framed echo protocol; P50/P99/P99.9
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
inter-SoC IPC. Only mention if asked or if time allows. **If the
conversation is DENSO-PoC-flavored specifically** (interviewer asks
about a single-vendor / domain-consolidation angle rather than
multi-vendor inter-SoC integration), pivot to the Phase 7-alt track
instead: one NVIDIA SoC family hosting both ADAS and IVI as sibling
partitions — matches the real "fewer, more powerful SoCs" consolidation
trend better than the multi-vendor story does.

---

## Anticipated technical Q&A — the GICv3/NISV finding (added 2026-07-29)

> This is the strongest "walk me through a real bug" story the project
> has produced so far. Don't bury it as a weakness — a well-told
> root-cause narrative with honest, unresolved next steps demonstrates
> more SE judgment than a clean success would.

**If asked "tell me about a hard technical problem you hit and how you debugged it":**

> On the hardware twin I wanted the QNX guest to boot under
> KVM-accelerated QEMU on the Jetson Orin Nano, so the IPC numbers
> would be hardware-timed instead of TCG-emulation-bound. The same IFS
> that booted cleanly under TCG hung silently after printing "FOUND
> GICv3 ITS" — no crash, no further output, every time.
>
> I traced it with ftrace on the host kernel's `kvm` events and caught
> the exact exit: `KVM_EXIT_ARM_NISV` — the guest had taken a Data
> Abort with no valid instruction syndrome. I disassembled the QNX
> board bring-up code at that PC and found a post-indexed store
> (`str w3,[x0],#4`) writing a GICv3 distributor priority register.
> That instruction form is one ARM's architecture explicitly excludes
> from guaranteeing ISV — it's a real, documented edge case, not
> something QNX did wrong per se. KVM's own design, confirmed against
> the upstream kernel patch that added this handling, is to give up and
> inject a synthetic abort into the guest rather than attempt decode —
> and QNX's exception vector this early in boot has no handler for it,
> so the guest parks forever. I confirmed the isolation by booting the
> identical image under plain TCG on the same hardware — clean boot,
> because TCG never synthesizes that kind of hardware fault in the
> first place.

**If asked "how would you actually fix that" / "what's next":**

> There isn't a clean fix available to me directly, and I think that's
> worth saying plainly rather than inventing one. Three real paths: file
> it with QNX/BlackBerry, since the defect is in their board bring-up
> binary and a different instruction encoding would sidestep it
> entirely; contribute a decode-and-emulate fallback to QEMU's own
> KVM/ARM backend for this exit class — open source, so it doesn't need
> vendor cooperation, though it's a real ARM64-instruction-decoding
> effort, not a quick patch; or spend a bounded amount on AWS
> Graviton3 `c7g.metal` to find out whether this is Tegra234-specific or
> a general real-hardware/KVM limitation, which would change how I'd
> prioritize the other two. Given where the project's time budget
> actually was, I made the call to defer chasing the hardware-timed
> number and ship a working TCG-based validation instead, with the
> finding fully documented. That's the same trade-off call an SE makes
> constantly when supporting a customer — not every defect blocks the
> deliverable, and knowing which one you're looking at is the actual
> skill.

**Update, 2026-07-29 — this got stronger, not weaker.** Provisioned an
AWS `a1.metal` instance (Graviton1, Annapurna Labs SoC, Cortex-A72 —
`c7g.metal`/Graviton3 was the intended cleaner same-generation comparison
but was blocked by this AWS account's 32-vCPU quota) and booted the
identical IFS under the identical `-enable-kvm` invocation. **Same exact
hang** — `FOUND GICv3 ITS`, then nothing, on a completely different
vendor's silicon. If asked "did you validate that beyond the one board":
> Yes — I ran the same boot on AWS Graviton1 bare metal, a completely
> different vendor's silicon from Jetson's Tegra234, and got the
> identical hang at the identical point. That's real evidence this is a
> general defect in QNX's board bring-up code, not something specific to
> one SoC — which changes how I'd prioritize: it's now a stronger case
> to file with QNX/BlackBerry than a Jetson-specific curiosity would be.

**Update, 2026-09-11 — two later steps.** On 2026-09-08 I built QNX's
own BSP startup-library source (`gic_v3.c`) with their own flags and got
the same post-indexed store at the same register offset, and adding one
compiler flag (`-fno-auto-inc-dec`) removes it without changing what the
loop writes. That is compile-verified, not boot-verified: the `qemu-virt`
board source does not ship, so the startup this project boots cannot be
relinked. It also puts the filing on shipped source rather than on
disassembly. Then ADR-003 (2026-09-09) chose a different route to a
hardware-timed hypervisor number: a native QNX port to the Orin Nano.
The QNX Hypervisor host now runs natively on the board, entered by kexec
from L4T, and it booted the cloud-leg QNX guest as a functional pass
(M3). If asked "so did you get the hardware-timed number":
> Not one I can publish yet. I ported QNX natively to the Orin Nano
> instead of waiting on KVM: the QNX Hypervisor runs at EL2 on the board
> and boots the same QNX guest the cloud leg uses. That is a functional
> pass. The timed runs happen once, on a frozen reference architecture,
> and publishing any evaluation result waits on a licence consultation.

**Why this holds up under follow-up questions:** the finding is
reproducible (documented across multiple boots, `docs/orin-port.md`'s
risk register), the root cause is verified at the instruction level
(not "it just hangs"), it's now confirmed across two independent ARM
vendors, and the honest-gap framing — "here's what I can't fix alone,
here's why, here's what would change my answer" — is exactly the
posture DRIVE OS customer support work requires. If pushed
on "why didn't you just patch the QNX binary yourself," the answer is
license scope: NCEULA covers use, not redistribution, and modifying a
vendor's proprietary board-bring-up binary — even for personal,
non-redistributed use — is a line worth not crossing casually; that's
also a real, intentional engineering-judgment answer, not evasion.

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
- **Cost framing:** mention AWS cost discipline (the bare-metal `a1.metal` instance was terminated right after its capture) if interviewer is platform-eng
- **Cert framing:** lean harder on `skills/iso-26262/` if JD emphasizes ASPICE/26262
- **Hypervisor framing:** if JD explicitly says "hypervisor experience," lead with the
  Phase 3 gap analysis instead of the Phase 1 bring-up
