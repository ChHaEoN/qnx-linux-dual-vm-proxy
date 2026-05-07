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

- **Cloud twin** — AWS Graviton (c7g.large arm64 + KVM, Ubuntu 22.04)
- **Hardware twin** — Jetson Orin Nano Dev Kit (NVIDIA L4T / JetPack 6
  on Cortex-A78AE × 6, Ampere GPU not exercised)

A short table of what crosses the twin boundary:

| Artefact | Twinned? | Notes |
|---|---|---|
| QNX IFS (`output/ifs.bin`) | **Yes — bit-for-bit identical** | Built once on the x86_64 build host (Windows local primary; EC2 fallback); scp'd to both runtime hosts |
| QNX IPC server (`ipc-test/qnx-server`) source | **Yes** | Same C99; compiled with `qcc` inside QNX guest in both twins |
| Linux IPC client (`ipc-test/linux-client`) source | **Yes** | Same C99; compiled with `gcc` — on the Linux guest in cloud twin, on L4T natively in HW twin |
| Wire protocol (sequence + timestamp + payload) | **Yes** | Fixed-width binary frame, version-tagged |
| Test harness + benchmark scripts | **Yes** | Same `run-bench.sh`; output CSV format is identical |
| QEMU command line | **Mostly** | `-machine virt,gic-version=3 -cpu host -enable-kvm -m 1G` is the same; **only the host kernel below QEMU differs** |
| Linux Compute side | **Different by design** | Cloud: Ubuntu cloudimg in QEMU; HW: L4T native (host OS). See §3. |
| Host kernel | **Different by design** | This is exactly the variable being studied |
| Host CPU | **Different by design** | Graviton3 Neoverse-V1 vs Tegra A78AE — same ARMv8 ISA, different micro-architecture and scheduler context |

The first six rows are the **invariant set** — anything that differs
between twin sides in those rows is a bug. The last three rows are the
**delta set** — they are what the twin diff measures.

---

## 2. What is deliberately not twinned

Twinning is asymmetric on the Linux Compute side and that is intentional:

- **Cloud twin** runs Linux Compute as a *second QEMU VM* alongside the
  QNX guest. This is closer to the DRIVE OS partition shape (Linux is a
  guest, not the host) but the host underneath is generic Ubuntu, not
  Tegra-aware.
- **Hardware twin** runs Linux Compute as **L4T itself**, the native
  host. This is closer to "real Tegra Linux runs natively"; QNX is the
  one thing being virtualised. Putting Linux in its own QEMU VM on
  Orin Nano would burn 2 GB extra RAM for no narrative benefit.

This is a calibrated trade-off, not an accident: each twin side
optimises for the comparison it can do honestly.

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
- Both VMs are guests, which is structurally closer to "two partitions on a hypervisor"
- A scaling path (instance size up to c7g.16xlarge) for stress testing

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

---

## 5. Results interpretation

> _Section deferred to Phase 4. Will hold the actual measured
> numbers and the interpretive prose tying them back to DRIVE OS
> reality._

---

## 6. Narrative tie-back

> _Section deferred to Phase 6. Will distill the twin-diff findings
> into the interview narrative's 2-min and 10-min versions, with
> citations to the measured numbers in `results/cloud/` and
> `results/hw/`._
