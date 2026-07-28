# CLAUDE.md — qnx-linux-dual-vm-proxy

> Guidance for any Claude Code session working in this repo.
> Read this file first; do not assume the project's framing from filenames alone.

---

## Mission (honest framing)

This repo is a **Digital Twin design** of the NVIDIA DRIVE OS dual-VM
partition architecture, running QNX SDP 8.0 (Safety proxy) + Linux aarch64
(Compute proxy):

- **Cloud twin:** QEMU/KVM on AWS Graviton (c7g.large) — fast iteration, regression sweeps.
- **Hardware twin:** QEMU/KVM on **Jetson Orin Nano Dev Kit** (Cortex-A78AE, same Tegra family as DRIVE Orin) — validation on real silicon.

The same QNX IFS and the same IPC client/server source run on both sides
unchanged; the only thing that changes is the host. The **twin diff**
(what actually changes when only the host changes?) is the load-bearing
measurement.

**This is not a real hypervisor.** There is no Type-1 partition isolation,
no ASIL-D guarantee, no certified RTOS, no GPU partitioning. KVM-on-Linux
is host-mediated, not certified Type-1. The value is in studying the
*software layer* — BSP bring-up, IPC patterns, kernel/userspace boundaries,
and cloud→target portability — that an SE supporting DRIVE OS customers
actually touches day-to-day.

The "honest framing" — explicitly documenting what is *not* demonstrated
vs. a real hypervisor — is itself part of the engineering narrative for
the NVIDIA AVOS / DRIVE OS SE role this portfolio targets.

---

## Tech stack

**Cloud twin (AWS):**
- Build host (primary): **local Windows PC** — QNX SDP 8.0 ships a Windows-native installer; `mkqnximage --arch=aarch64le` produces the IFS locally and it is scp'd to the runtime host
- Build host (fallback): t3.medium x86_64 Ubuntu 22.04 — retained for users without a local x86_64 Windows or Linux machine
- Runtime host: c7g.large (Graviton3 Neoverse-V1, Ubuntu 22.04 arm64, KVM-on-arm64)
- Honest framing: the Windows-host pivot is a **friction/cost optimisation only**. The build host runs only `mkqnximage` and host-side QNX tooling (no guests run on it) and produces a target-aarch64 IFS via cross-compilation; per F1's arch-agnostic-IFS argument, host platform (Windows vs Linux x86_64) affects only build metadata (embedded paths, timestamps), not the ARM code QNX boots, so F5 Q2 (any x86_64-built IFS boots on Graviton) is the only verification needed — there is no separate cross-host build-determinism check. The pivot is also NOT closer to a real DRIVE OS customer build environment than EC2 — DRIVE OS customer builds typically sit on rented or vendor-provided Linux hosts, not local Windows.

**Hardware twin (Orin Nano):**
- Jetson Orin Nano Dev Kit ($499) — Ampere GPU, 6× Cortex-A78AE, 8 GB RAM
- Host OS: NVIDIA L4T (JetPack 6, Ubuntu 22.04 base) — also plays the "Compute partition" role
- `/dev/kvm` is present and initializes (VHE, GICv3) on this hardware, but
  booting the actual QNX IFS under `-enable-kvm` hangs on a real,
  root-caused defect (see Phase status below and `docs/orin-port.md`'s
  risk register) — **TCG is the working transport today**, KVM is not.
  Do not assume "KVM enabled on A78AE" means QNX boots under it.

**Common across both twins:**
- VM0 — Safety proxy: QNX SDP 8.0, aarch64 `virt` machine, NCEULA (Everywhere)
- VM1 — Compute proxy: Linux aarch64 — **Phase 3 / Orin only** (L4T native). Per
  [ADR-002](docs/phase2-topology-decision.md) there is **no Linux guest on the
  cloud leg** (the cloud Compute-VM premise was falsified — no `/dev/kvm`, host
  `io-sock` down).
- IPC (cloud leg): QNX-host (`qnx-qhv`) ↔ QNX-guest (`qnx-guest`) over the `qvm`
  `virtio-console` vdev — crosses the real EL2/EL1 partition boundary, TCG-emulated,
  **no** `br0`/tap (host `io-sock` is down). See [ADR-002](docs/phase2-topology-decision.md).
- IPC (Phase 3 / Orin leg): heterogeneous QNX↔Linux over host bridge `br0` + tap
  devices (`tap-qnx` / `tap-linux`) + virtio-net under KVM — this bridged path
  belongs to Orin, **not** the cloud leg.
- Reference architecture: NVIDIA DRIVE OS dual-VM partition design (public docs)

**Dev driver / build host:** local Windows PC (x86_64) — both the
IDE / git / SSH-into-AWS workstation **and**, as of the 2026-05-07
amendment in [docs/findings.md](docs/findings.md), the primary QNX
SDP 8.0 build host. QNX Software Center, SDP install, and IFS build
all run natively on Windows; the resulting `output\ifs.bin` is scp'd
to the c7g.large Graviton runtime host. The EC2 t3.medium x86_64
Ubuntu host stays in the repo as a fallback for users without a
local x86_64 Windows or Linux box. Honest framing: this collapses
two roles (dev driver + build host) onto one machine and removes the
ssh / X11 / browser hops needed to drive the QNX Software Center GUI
on a remote EC2 — but it does **not** demonstrate build-environment
parity with a real DRIVE OS customer's Linux build host, and Phase 1
must still verify Windows-built vs. EC2-built IFS produce equivalent
output before the pivot is treated as fully validated. The Macbook
Pro M1 Max remains usable as a secondary IDE / SSH terminal but
cannot host SDP 8.0 (no macOS installer in 8.0).

---

## Directory structure

```
qnx-linux-dual-vm-proxy/
├── README.md                  # public-facing project overview
├── CLAUDE.md                  # this file (Claude Code guidance)
├── LICENSE                    # MIT (source only; not QNX/Linux binaries)
├── docs/                      # narrative, decisions, findings
├── agents/                    # sub-prompt templates per agent in the roster
├── scripts/                   # cloud-twin scripts (top-level), orin/, twin/
├── ipc-test/                  # Phase 2 cross-VM IPC client/server source
├── results/cloud/             # Phase 2 latency CSVs (AWS twin)
├── results/hw/                # Phase 3 latency CSVs (Orin twin)
├── logs/sample-boot/          # curated boot logs (Phase 1)
├── skills/                    # FuSa, ISO 26262, ASPICE, BSP, QOS, twin, jetson, tegra-virt, 21434
└── .github/workflows/         # CI (added in Phase 1)
```

Each placeholder file carries a `Phase N` tag in its header. Do not strip Phase tags.

---

## Agents (delegate work to these roles)

The roster is modelled on real automotive SDV team roles. Each agent
has a sub-prompt template at `agents/<agent-name>.md`.

| # | Agent | Industry-role mapping | Primary responsibilities |
|---|-------|---|---|
| 1 | 🔍 **Research** | Tech scout / requirements engineer | external research (BSP, license, baselines, Jetson L4T quirks); fills decision-record stubs |
| 2 | 📐 **Architect / Planner** | System architect | architecture diagrams, phase decomposition, risk assessment; arbitrates trade-offs from Research |
| 3 | 🏗️ **Implementation** | Software engineer | scripts, configs, IFS build wrappers, IPC C99 source, infra-as-code |
| 4 | 🧪 **Test / V&V** | Verification & validation engineer | unit + integration tests, latency benchmarks, regression sweeps, **twin-diff** measurements (Phase 4) |
| 5 | 🛡️ **FuSa-Analysis** | FuSa analyst (ISO 26262) | HARA, FMEA, DFA — *finds* hazards and failure modes; produces `skills/fmea/examples/<phase>-fmea.md` |
| 6 | 🛡️ **FuSa-Design** | FuSa architect (ISO 26262) | Safety Concept, Technical Safety Requirements (TSR), safety mechanism design — *designs* mitigations for findings from FuSa-Analysis |
| 7 | 🛡️ **FuSa-Verification** | FuSa V&V engineer (ISO 26262) | FMEDA, fault injection plans, residual-risk argument — *proves* the mitigations work |
| 8 | 🔐 **Cyber-Analysis** | Cybersec analyst (ISO/SAE 21434) | TARA — Threat Analysis and Risk Assessment, asset / threat / damage / attack-feasibility tables; *finds* threats |
| 9 | 🔐 **Cyber-Design** | Cybersec architect (ISO/SAE 21434) | Cybersecurity Concept + Technical Cybersecurity Requirements (TCR), security mechanism selection (mTLS, secure-boot, signing); *designs* mitigations |
| 10 | 🔐 **Cyber-Verification** | Cybersec V&V engineer (ISO/SAE 21434) | Pen-test plans, fuzzing harnesses, vulnerability management process, NCEULA + supply-chain audit checklist; *proves* mitigations work |
| 11 | 📝 **Docs** | Tech writer | README, narrative, findings log, comparison doc; cross-links between artifacts |
| 12 | 📊 **Comparison** | Domain analyst | dimension-by-dimension DRIVE OS gap doc (Phase 4); honest verdicts |
| 13 | 🎓 **Skills** | Knowledge curator | populates `skills/*` paradigm READMEs; worked examples per phase milestone |
| 14 | 🧭 **Twin Sync** (Phase 3+) | Integration engineer | orchestrates AWS↔Orin parity; owns `scripts/twin/sync.sh` |

**Coordination rules:**

- **Forward flow per Phase milestone:** Research → Architect → Implementation → Test.
- **FuSa (3 sub-roles) and Cybersecurity (3 sub-roles) are cross-cutting:** they review at every Phase boundary, not just at the end. Internal flow within each is **Analysis → Design → Verification** (ISO 26262 / 21434 V-model order). The two disciplines pair-review at phase gates for cyber-FuSa interaction analysis.
- **Docs / Comparison / Skills are continuous:** they pull from the work products of the other agents.
- Multiple agents may run in **parallel** only when their work products do not overlap (FuSa worksheet + Cybersecurity threat model: fine; two Implementation agents on the same script: not).
- **Room to grow:** explicit candidates for future addition are Performance, Release / DevOps, and Customer-facing Application Engineer (the latter would role-play DRIVE OS customer-port engagements).

**Where the agent definitions live (two locations, on purpose):**

| Location | Audience | Format | Use |
|---|---|---|---|
| `agents/<name>.md` | Humans (PR reviewers, GitHub readers) | Long-form prose: role, inputs, outputs, handoff, sub-prompt template | Documentation; on-boarding new collaborators |
| `.claude/agents/<name>.md` | Claude Code Task tool | YAML frontmatter (`name`, `description`, `tools`) + concise system prompt | Native subagent invocation: `subagent_type: <name>` |

The `.claude/agents/` files are intentionally thin and refer back to `agents/<name>.md` for full context. Edit both together so they don't drift.

**How to invoke a subagent (in any Claude Code session):**

1. Ask the orchestrator (the main session): _"Run the Research agent on the F6 BSP questions in `docs/bsp-selection.md`."_
2. The orchestrator spawns a Task tool call with `subagent_type: research` and a concrete task description.
3. The subagent reads `CLAUDE.md` + `agents/research.md` + the target phase doc, does its work, returns a summary.
4. The orchestrator integrates the result and decides next agent.

**Phase 1 starting sequence (concrete):**

> **Superseded in part by [ADR-002](docs/phase2-topology-decision.md) (Accepted).**
> Steps 3–5 below assume the falsified cloud topology — KVM + `br0`/tap +
> a dual QNX/Linux VM launch. The as-built cloud leg is the QHV host
> `qvm` + a **single** QNX guest under QEMU **TCG** (no KVM, no
> `br0`/tap, no Linux guest). Treat `setup-bridge.sh` and
> `launch-linux-vm.sh` on the cloud runtime as **not used on cloud**;
> they belong to the Phase-3 Orin heterogeneous path. The live cloud
> bring-up path is `scripts/qhv/` (see [docs/findings.md](docs/findings.md)
> top entries) and the Phase-2 IPC is QNX-host↔QNX-guest over the `qvm`
> virtio-console vdev.

```text
1. research + architect  → complete (commit 072446c — HARA / TARA / F6 verdicts; 2026-05-07 amendment in findings.md — Windows build-host pivot)
2. user (manual)         → install QNX SDP 8.0 on local Windows PC via QNX Software Center (primary path is GUI-only; not scripted)
3. implementation        → scripts/bootstrap-runtime-host.sh on Graviton c7g.large (provision QEMU + bridge tooling). [ADR-002: no KVM on cloud — TCG only] Fallback only: scripts/bootstrap-build-host.sh on a t3.medium EC2 if no local x86_64 host
4. implementation        → scripts/build-qnx-ifs.bat on Windows (or build-qnx-ifs.sh on EC2 fallback) → scp ifs.bin to runtime → boot QHV host + single QNX guest under TCG via scripts/qhv/. [ADR-002 supersedes the old setup-bridge.sh + launch-{qnx,linux}-vm.sh dual-VM-over-bridge step — that is Phase-3/Orin only]
5. test                  → capture boot logs into logs/sample-boot/cloud-{qnx,linux}-boot1.log (cloud is QNX-only per ADR-002); record QNX boot time
6. fusa-analysis         + cyber-analysis (parallel)  →  Phase-1-gate review
7. docs                  → update findings.md with Phase 1 measured numbers
```

Three parallel-friendly handoffs in that flow: step 6 (FuSa-Analysis ∥ Cyber-Analysis) and the eventual Phase-2 IPC implementation can split client / server work between two Implementation agents.

---

## What this project does NOT do

- No Type-1 / Type-2 hypervisor (QEMU + KVM is for OS bring-up, not partition isolation)
- No ASIL-B/D safety claim
- No MISRA-C compliance
- No GPU virtualization or vGPU partitioning
- No certified bootloader chain (no SecureBoot / measured boot)
- No real-time scheduling guarantees across the proxy boundary
- No ISO 26262 / Automotive SPICE process artifacts (study notes only — see `skills/`)

These limitations are deliberate; documenting them precisely *is* the point.

---

## NVIDIA JD mapping — internal working reference (do NOT surface in README)

> **For Claude Code sessions only.** When deciding what to prioritise,
> what to expand, or how to phrase findings, refer to the JD mapping
> as the project's targeting context. The full JD-to-artefact table
> lives at [docs/jd-mapping.md](docs/jd-mapping.md). It is **not**
> linked from README.md (the public face stays focused on the
> engineering work itself).

Quick summary for context:

| JD requirement | Where addressed |
|----------------|-----------------|
| C/C++, QNX and/or Linux OS | Phase 1 bring-up + Phase 2 IPC proxy (C99) |
| OS internals, multi-threading, IPC, memory mgmt | Phase 2 (`ipc/`), Phase 1 BSP work |
| BSP porting and device driver internals | Phase 1 (QNX virt BSP, Linux rootfs) |
| Multicore / heterogeneous SoCs | Graviton3 multi-core; QEMU SMP guest config |
| Customer-facing AVOS/DRIVE OS support | Framing: this proxy IS the kind of software-layer customer environment an SE helps port |
| ECU bring-up, profiling, debug | Phase 1 (boot logs, kernel debug) + Phase 2 (latency profiling) |
| QNX OS for Safety (QOS) — *stand out* | Honest gap: SDP ≠ QOS; framed as "POSIX-realtime proxy" + `skills/qnx-safety/` |
| Hypervisors / virtualization — *stand out* | Phase 3 comparison doc: explicit gap analysis vs. real hypervisor |
| Bootloaders — *stand out* | Phase 1 (U-Boot for Linux guest, IPL for QNX) |
| ASPICE / ISO 26262 — *stand out* | `skills/iso-26262/` + `skills/aspice/` study notes; applied FMEA in `skills/fmea/examples/` |

---

## Working conventions

- **Test before claim**: never write "it works" without a log, a number, or a diff.
- **Honest framing**: every claim is paired with what it does NOT demonstrate.
- **One bundled PR per Phase milestone**, not many tiny PRs.
- **Commit style**: `<phase>: <imperative summary>` (e.g. `phase-0: scaffold repo and add CLAUDE.md`).
- **Secrets**: never commit `.pem`, `.env`, instance IDs, AWS keys. Loaded from `.env` (gitignored).
- **Cost discipline**: run `scripts/ec2/teardown.sh` after every session; document spend in findings docs.
- **`skills/` are study artifacts**, not certification evidence — say so explicitly in any doc that cites them.

---

## Phase status

> **Updated 2026-07-28** — this section had drifted badly out of date
> (it still said "Phase 0 current" after Phases 1–4 had real work and
> real numbers). Treat `docs/findings.md` as the authoritative,
> dated ground truth if this section drifts again — it is updated
> every session real work happens; this section is a summary that can
> lag.

- Phase 0 — Bootstrap / scaffold + Digital Twin re-scope — **done**
- Phase 1 — Cloud twin bring-up — **done**: QHV host + single QNX
  guest boot under QEMU-TCG, demonstrated on the local Windows build
  host (not AWS — Graviton non-metal has no `/dev/kvm`/EL2, see
  [ADR-002](docs/phase2-topology-decision.md)). Curated log:
  [logs/sample-boot/qhv-tcg-host-and-guest-boot.log](logs/sample-boot/qhv-tcg-host-and-guest-boot.log).
- Phase 2 — Cloud twin IPC + latency benchmark — **partial, real
  numbers, honestly capped**: the `qvm` virtio-console `hostdev`
  runtime-spike is resolved (host `/dev/ptyp0`↔`/dev/ttyp0` pty pair,
  guest `devc-virtio`→`/dev/vcon2`); real measured P50/P99/Max exist
  in [results/cloud/cloud-ipc-latest.csv](results/cloud/cloud-ipc-latest.csv).
  **Open:** a non-deterministic `qvm`/TCG virtio-queue stall caps
  reliable runs at ~15–35 iterations, nowhere near the 100k-iteration
  target — root cause not found, not closed. See
  [ipc-test/qnx-host-client/README.md](ipc-test/qnx-host-client/README.md).
- Phase 3 — Hardware twin port to Jetson Orin Nano — **substantial
  progress, not closed**: Orin Nano flashed (JetPack 6/L4T R36.4.7)
  and SSH-reachable; the plain `qnx-safety-vm` IFS boots under
  **TCG** on real hardware. **KVM-accelerated boot is blocked** by a
  real, root-caused defect — a GICv3 distributor bring-up instruction
  takes a `KVM_EXIT_ARM_NISV` Data Abort that neither KVM nor QEMU
  6.2.0 can emulate and QNX's `startup-qemu-virt` has no handler for
  (see `docs/orin-port.md`'s risk register) — TCG is the accepted
  interim transport, not a permanent substitute for the hardware-timed
  KVM number this phase still owes. Networking (`io-sock`/virtio-net)
  was separately root-caused and fixed (a missing `virtio-rng-device`
  in the fixed virtio-mmio slot order, not a virtio-net bug) and
  **heterogeneous QNX↔Linux IPC over a real `br0`/`tap-qnx` bridge is
  working**: two clean 100,000-iteration runs, zero errors — see
  [results/hw/orin-ipc-latest.csv](results/hw/orin-ipc-latest.csv).
  Honest caveat: this used a **rebuilt** IFS (new TCP server code
  staged in), not the byte-identical Phase-1 image — a real deviation
  from a strict zero-code-change portability claim.
- Phase 4 — Twin diff + DRIVE OS comparison — **started**:
  `scripts/twin/diff-results.sh` was rewritten to match the CSV schema
  the benchmarks actually produce (the original assumed a shape no
  real CSV ever had). Two real diffs exist in
  [docs/digital-twin-design.md](docs/digital-twin-design.md) §5: an
  IPC delta (explicitly flagged as confounding host+accel+transport,
  "mechanism-alive vs. heterogeneity" — not a clean host-only
  comparison) and a boot-time delta (the clean host-only comparison,
  n=5 per side: Orin +23–25% slower than Windows, but with a *tighter*
  run-to-run spread). `docs/drive-os-comparison.md` (the broader
  dimension-by-dimension gap doc) is untouched — still open.
- Phase 5 — FuSa & Cybersecurity overlay — not started (Phase-1-gate
  FuSa/Cyber review already happened as a cross-cutting check per the
  coordination rules above, but the dedicated Phase-5 overlay pass has not)
- Phase 6 — Polish, public README, demo recording — not started
- Phase 7 (stretch) — Multi-SoC domain-controller extension — not
  started; feasibility frozen in `docs/future-multi-soc.md`

**Next actions (pick one, they're independent):**
1. Root-cause or route around the Phase-2 `qvm`/TCG virtio-console
   stall (blocks getting past ~35 samples on the cloud leg).
2. File the GICv3/NISV defect with QNX/BlackBerry support, or test
   whether a from-source-built newer QEMU improves `KVM_EXIT_ARM_NISV`
   decode coverage (assessed as unlikely to help — this is the KVM
   backend's deliberate by-design behavior, not a version bug — but
   untested).
3. Write `docs/drive-os-comparison.md`'s dimension-by-dimension
   verdicts now that Phase 2/3/4 have real numbers to cite instead of
   projections.

**Decision (2026-07-29):** getting a real KVM/hardware-timed number on
Orin is **deferred, not abandoned** — it genuinely needs either NVIDIA
DRIVE AGX Orin hardware (gated behind an invitation-only developer
program, not self-serve) or further paid AWS `c7g.metal` investigation,
and neither is worth blocking on right now. In its place: (a) a second
project track opened in [docs/future-multi-soc.md](docs/future-multi-soc.md)
("Phase 7-alt — Single-SoC domain convergence, NVIDIA-primary") that
matches validating a DENSO PoC where one NVIDIA SoC family hosts *both*
ADAS (this project's existing QNX Safety + Linux Compute work) *and*
IVI/Cockpit as sibling partitions — MVP is a lightweight Linux IVI VM
first, Android Automotive as a de-risked stretch after; (b) the
GICv3/NISV finding itself is written up as interview material in
[docs/interview-narrative.md](docs/interview-narrative.md)'s new Q&A
section — it is a strong debugging story on its own, not just a
blocker.
