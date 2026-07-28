# Digital Twin design

This document is the methodology layer that sits underneath the
architecture diagrams in [architecture.md](architecture.md). It
defines what is actually twinned, what is deliberately not, how the
two sides stay in sync, and how the twin diff is measured.

> **Status:** Sections 1–3 are populated as part of Phase 0
> re-scope. Sections 4–6 (twin-diff methodology specifics, results
> interpretation, narrative tie-back) wait for Phase 2 / Phase 4
> measurement so the prose can be backed by numbers.

---

## 1. What is being twinned

The project mirrors the *software-layer behaviour* of an NVIDIA
DRIVE OS dual-VM partition across two physically distinct host
substrates:

- **Cloud twin** — AWS Graviton (c7g.large arm64, Ubuntu 22.04). Note
  per [ADR-002](phase2-topology-decision.md): non-metal Graviton has no
  `/dev/kvm`, so the cloud leg runs the SDP 8.0 QHV (`qvm`) + a single
  QNX guest under QEMU **TCG**, not KVM.
- **Hardware twin** — Jetson Orin Nano Dev Kit (NVIDIA L4T / JetPack 6
  on Cortex-A78AE × 6, Ampere GPU not exercised)

A short table of what crosses the twin boundary:

| Artefact | Twinned? | Notes |
|---|---|---|
| QNX IFS (`output/ifs.bin`) | **Yes — bit-for-bit identical** | Built once on the x86_64 build host (Windows local primary; EC2 fallback); scp'd to both runtime hosts |
| QNX IPC server (`ipc-test/qnx-server`) source | **Yes** | Same C99; compiled with `qcc` inside QNX guest in both twins |
| Linux IPC client (`ipc-test/linux-client`) source | **Phase 3 / Orin only** | Per [ADR-002](phase2-topology-decision.md), there is **no Linux guest on the cloud leg** — the cloud initiator is a QNX-host program (`ipc-test/qnx-host-client`). This client runs on L4T natively on the HW twin only |
| Wire protocol (sequence + timestamp + payload) | **Yes** | Fixed-width binary frame, version-tagged |
| Test harness + benchmark scripts | **Yes** | Same `run-bench.sh`; output CSV format is identical |
| QEMU command line (machine/CPU/mem) | **Mostly** | `-machine virt,gic-version=3 -cpu ... -m 1G` shape is shared; see the accel row for the cloud/Orin split |
| QEMU acceleration | **Different by design** | Per [ADR-002](phase2-topology-decision.md): cloud = `-accel tcg` (no `/dev/kvm` on non-metal Graviton); Orin = `-enable-kvm` (KVM works on A78AE). This was wrongly listed as an invariant before the QHV pivot |
| IPC transport | **Different by design** | Cloud: host↔guest `qvm` virtio-console (single-OS QNX↔QNX); Orin: QNX↔Linux virtio-net over KVM bridge. The legs no longer share an identical topology — see §4 |
| Linux Compute side | **Different by design** | Cloud: **no Linux guest** (single QNX guest under QHV); HW: L4T native (host OS). See §2/§3 |
| Host kernel | **Different by design** | This is exactly the variable being studied |
| Host CPU | **Different by design** | Graviton3 Neoverse-V1 vs Tegra A78AE — same ARMv8 ISA, different micro-architecture and scheduler context |

The rows marked **Yes** / **Mostly** are the **invariant set** — the QNX
IFS, the QNX server source, the wire protocol, the harness, and the
QEMU machine/CPU/mem shape — and anything that differs between twin
sides in those rows is a bug. The rows marked **Different by design**
are the **delta set** — host kernel and host CPU are the variables the
twin diff was meant to isolate, but per [ADR-002](phase2-topology-decision.md)
the QEMU-acceleration, IPC-transport, and Linux-Compute-side rows are
**now also deltas**, not invariants: the cloud leg lost KVM and lost its
Linux guest. §4 explains why the diff must therefore account for more
than host difference alone.

---

## 2. What is deliberately not twinned

Twinning is asymmetric on the Linux Compute side and that is intentional.
Note this section **changed materially** under
[ADR-002](phase2-topology-decision.md): the earlier claim that the cloud
twin ran Linux Compute as a *second QEMU VM* is **falsified** and has
been corrected below.

- **Cloud twin** runs **no Linux Compute guest at all.** The cloud leg
  is the SDP 8.0 QHV host `qvm` hosting a **single QNX guest** under
  QEMU TCG (Phase 1 falsified the original two-co-equal-KVM-guests
  premise — no `/dev/kvm` on non-metal Graviton, and the host `io-sock`
  stack needed for a bridged Linux guest is down). The cloud leg
  therefore demonstrates the **IPC mechanism across a real `qvm` EL2/EL1
  partition boundary** — but it does **not** demonstrate the QNX-safety
  ↔ Linux-compute heterogeneity that is the load-bearing mirror of DRIVE
  OS's dual-OS partitioning. That heterogeneity is twinned on **Orin
  only**.
- **Hardware twin (Orin)** runs Linux Compute as **L4T itself**, the
  native host, and is the **committed home of the heterogeneous QNX↔Linux
  IPC**. This is closer to "real Tegra Linux runs natively"; QNX is the
  one thing being virtualised, and KVM actually works on the A78AE.
  Putting Linux in its own QEMU VM on Orin Nano would burn 2 GB extra
  RAM for no narrative benefit.

This is a calibrated trade-off, not an accident: each twin side
demonstrates what its host can *actually* do — the cloud leg owns the
hypervisor-boundary IPC *mechanism*; Orin owns the *heterogeneous*
dual-OS story. A dual-guest Linux-under-QHV cloud topology (ADR-002
Option B) is a research-gated **Phase 2.5** stretch only, not a claim
made today.

The HW twin therefore can **claim**:
- Real Tegra-family silicon (A78AE matches DRIVE Orin's CCPLEX core family)
- L4T as the actual Compute-side OS (closer to the real DRIVE OS Linux partition than Ubuntu cloudimg)

The HW twin **cannot** claim:
- Type-1 hypervisor partitioning (KVM-on-L4T is host-mediated)
- DRIVE OS-class Safety RT guarantees
- NVDLA / PVA / GPU partitioning (those exist on Orin Nano but are out of scope; QNX guest never sees them)
- Secure-boot chain across partitions

The cloud twin can claim none of the above either, but offers in exchange:
- Fast iteration, regression sweeps, parameter studies
- A **real `qvm` Type-1 partition boundary** (EL2 host ↔ EL1 guest) — the
  strongest hypervisor artefact in the project — exercised by the
  host↔guest IPC, though TCG-emulated, not hardware-timed (per
  [ADR-002](phase2-topology-decision.md))
- A scaling path (instance size up to c7g.16xlarge) for stress testing

What the cloud twin **cannot** claim (corrected under ADR-002): two
co-equal OS guests over KVM — there is one QNX guest under TCG, and the
Linux Compute side is absent (it lives on Orin).

Neither twin is a real DRIVE OS — they are two complementary
imperfect mirrors. The Phase 4 comparison doc holds that line.

---

## 3. Sync mechanism

There are three artefacts that must stay in lockstep across the twin
sides for the comparison to be sound:

1. **The QNX IFS** — built on the x86_64 build host (Windows local primary; EC2 fallback) and
   distributed to both runtime hosts. There is exactly one source of
   truth (the build host's `output/ifs.bin`) and a SHA-256 checksum
   committed to `results/ifs.sha256` in each measurement run so any
   accidental rebuild between runs is caught.
2. **The IPC source code** — under `ipc-test/`, single git tree,
   pinned to the commit SHA used for any given measurement run. The
   benchmark script records the SHA in its output CSV header.
3. **The wire protocol version tag** — a one-byte field at the head
   of every frame. If the cloud twin and the HW twin ever speak
   different protocol versions, the receiver-side benchmark refuses
   to run rather than producing comparable-looking-but-incomparable
   numbers.

The Twin Sync Agent (Phase 3+) owns the script `scripts/twin/sync.sh`
that rsyncs IFS + sources from a known-good build host snapshot to
both runtime hosts and verifies the SHA-256 + git-SHA invariants on
landing.

**Anti-pattern explicitly forbidden:** rebuilding the IFS on each
runtime host independently. Even if the build is reproducible in
theory, debugging a "did the IFS change?" question is harder than
just having one canonical artefact.

---

## 4. Twin-diff methodology

> _Section deferred to Phase 4. Will define what a "twin diff" run
> looks like (one matched pair of measurement runs across cloud +
> HW); the metrics chosen (boot time, P50 / P99 / P99.9 IPC RTT,
> jitter envelope, throughput at 1 KB / 4 KB / 16 KB messages); the
> reporting format; how to interpret a delta._

> **Constraint on the diff design (per [ADR-002](phase2-topology-decision.md)):**
> the original premise — "hold everything identical, change only the
> host, measure the delta" — **no longer holds for IPC**. The cloud and
> Orin legs run **non-identical IPC topologies**: the cloud leg is a
> single-OS QNX↔QNX exchange over a `qvm` virtio-console vdev under
> **TCG**, whereas Orin is a heterogeneous QNX↔Linux exchange over
> virtio-net bridged under **KVM**. The IPC diff therefore confounds at
> least three variables — host (Graviton vs. A78AE), acceleration (TCG
> vs. KVM), and transport+OS-pair (console/QNX↔QNX vs. virtio-net/QNX↔Linux)
> — and the methodology must say so explicitly rather than presenting
> the IPC delta as a host-only effect. The cloud IPC number is
> TCG-emulation-bound (a *mechanism-alive* sanity figure), so only the
> Orin leg yields a hardware-timed transport number; the diff is
> "mechanism vs. heterogeneity", not a clean host-only comparison. The
> **boot-time** diff (same IFS, same QEMU machine shape) remains the
> cleaner near-host-only comparison and is the diff to lead with.

---

## 5. Results interpretation

**First real numbers (2026-07-28)**, produced by
[`scripts/twin/diff-results.sh`](../scripts/twin/diff-results.sh)
(rewritten 2026-07-28 to parse the schema the CSVs actually use — the
original version predated any real CSV and assumed a shape neither leg
ever produced) against
[`results/cloud/cloud-ipc-latest.csv`](../results/cloud/cloud-ipc-latest.csv)
and [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv):

| Metric | Cloud (QNX↔QNX, `qvm` virtio-console, TCG, 15 samples) | HW (QNX↔Linux, virtio-net/`br0`, TCG, 100 000 samples) | Δ (hw − cloud) |
|---|---|---|---|
| P50 | 2,002,500 ns | 1,636,269 ns | −366,231 ns (−18.3%) |
| P99 | 2,332,300 ns | 2,549,813 ns | +217,513 ns (+9.3%) |
| Max | 2,332,300 ns | 4,127,894 ns | +1,795,594 ns (+77.0%) |

**Reading these deltas correctly is the whole point of this section.**
Per §4's constraint, this is not a host-only comparison — it confounds
host, acceleration (matching only incidentally: HW's KVM path is
separately blocked by the GICv3/NISV finding in
[orin-port.md](orin-port.md), not by design), and transport+OS-pair. Two
observations are honestly supportable from this data:

- **Stability, not raw speed, is the striking difference.** The cloud
  leg's virtio-console transport hits a non-deterministic `qvm`/TCG
  virtio-queue stall within single-digit-to-dozens of iterations
  (documented in
  [`ipc-test/qnx-host-client/README.md`](../ipc-test/qnx-host-client/README.md)),
  capping its sample count at 15. The HW leg's virtio-net/`br0` path
  completed **two clean 100,000-iteration runs in a row** with zero
  errors. Read as a mechanism-reliability finding (console vdev framing
  vs. a real socket transport under TCG), not a host-speed finding.
- **The P50/P99/Max numbers themselves are not meaningfully comparable**
  across legs, because they measure different things: cloud's number is
  round-trip time through a `qvm` EL2↔EL1 console vdev between two QNX
  instances; HW's number is round-trip time through a Linux bridge +
  virtio-net between a QNX guest and the native Linux host. Both are
  real, both are TCG-emulation-bound, neither isolates host CPU
  performance — that specific comparison (same transport, same IFS, only
  the host differing) does not exist yet in this repo. It would require
  either a console-based transport on Orin or a virtio-net-based
  transport on cloud, and cloud's Linux-side is deliberately absent per
  [ADR-002](phase2-topology-decision.md).
- **The cleaner host-only comparison remains boot time**, per §4's own
  guidance, and is still not done — `logs/sample-boot/orin-tcg-qnx-boot1.log`
  and the cloud-leg equivalents exist but have not been time-diffed
  against each other in this pass.

**Follow-up, same day: a sample-size-matched re-run corrects the P50
reading above.** The 100k-vs-15 comparison's wildly inconsistent deltas
(P50 −18.3%, Max +77.0%) were suspicious on their face — with n=15,
`P99` and `Max` are mathematically the same sample, so cloud's "tail" was
never a real tail estimate, and comparing it against a 100,000-sample Max
compares extreme-value statistics from two wildly different sample sizes
(Max grows with n for any non-degenerate distribution — more trials, more
chances to hit a rare slow outlier). Re-ran the HW leg with the exact
same 15-iteration / 5-warm-up shape as the cloud run
(`./linux-client 15 192.168.100.10 5`, same guest boot, same bridge) to
remove that confound. Result, appended as a third row in
[`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv):

| Metric | Cloud (n=15) | HW (n=15, matched) | Δ |
|---|---|---|---|
| P50 | 2,002,500 ns | 2,213,370 ns | **+10.5%** |
| P99 | 2,332,300 ns | 2,596,291 ns | +11.3% |
| Max | 2,332,300 ns | 2,596,291 ns | +11.3% |

Two things worth being honest about: (1) **the earlier "-18.3% P50, HW is
faster" reading does not survive a fair, sample-matched comparison** — at
matched n, HW's P50 is actually ~10% *slower*, not faster; the 100k-sample
run's lower P50 reflects a different, much larger sample benefiting from
the law of large numbers, not a directly comparable statistic to cloud's
15-sample P50. Don't quote the earlier −18.3% figure without this
correction attached. (2) The three metrics now move together (all
+10–11%) instead of disagreeing wildly, which is itself evidence the
matched comparison is more trustworthy than the mismatched one — a
consistent small delta across P50/P99/Max is what a real, modest
transport-cost difference should look like; three metrics disagreeing by
an order of magnitude (as in the mismatched comparison) was the tell that
something other than the transport was driving the numbers. The
**stability finding from the first pass still stands and is unaffected**
by any of this: HW ran two clean 100k-iteration passes with zero errors;
cloud has never exceeded ~35 iterations without the still-unresolved
`qvm`/TCG virtio-queue stall (see `ipc-test/qnx-host-client/README.md`).
That asymmetry, not the percentile deltas, remains the most defensible
finding from this pair of legs.

---

## 6. Narrative tie-back

> _Section deferred to Phase 6. Will distill the twin-diff findings
> into the interview narrative's 2-min and 10-min versions, with
> citations to the measured numbers in `results/cloud/` and
> `results/hw/`._
