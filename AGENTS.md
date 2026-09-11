# AGENTS.md — qnx-linux-dual-vm-proxy

> Guidance for any Codex session working in this repo.
> Read this file first; do not assume the project's framing from filenames alone.

---

## Mission (honest framing)

This repo is a **Digital Twin design** of the NVIDIA DRIVE OS dual-VM
partition architecture, running QNX SDP 8.0 (Safety proxy) + Linux aarch64
(Compute proxy):

- **Cloud twin:** designed as QEMU/KVM on AWS Graviton (c7g.large), for fast iteration and regression sweeps. As built, it runs the QNX Hypervisor host and one QNX guest under QEMU TCG on the local Windows PC, because non-metal Graviton has no `/dev/kvm` (ADR-002).
- **Hardware twin:** **Jetson Orin Nano Dev Kit** (Cortex-A78AE, same Tegra family as DRIVE Orin) — validation on real silicon. QEMU runs there under TCG, because KVM boot of the QNX IFS hangs on the GICv3/NISV defect. Since Phase 3b the QNX Hypervisor also runs natively on the board.

The design had the same QNX IFS and the same IPC client/server source run
on both sides unchanged, with only the host changing. As built, the Orin
IPC leg used a rebuilt IFS, and "host" is a bundle of CPU, OS, TCG backend
and QEMU build (`docs/digital-twin-design.md` §1a). The **twin diff**
(what changes when the host bundle changes?) is still the load-bearing
measurement. It is re-run once on reference architecture v1
(`docs/orin-native-port-plan.md`, freeze section).

**This is not a certified hypervisor stack.** The QNX Hypervisor (`qvm`)
that the project runs is a Type-1 hypervisor, but it runs uncertified:
emulated under QEMU TCG, and natively on a consumer devkit as Experimental
Software (Phase 3b). There is no demonstrated partition isolation (no SMMU
work, no fault injection), no ASIL-D guarantee, no certified RTOS, no GPU
partitioning. KVM-on-Linux, where used, is host-mediated, not certified
Type-1. The value is in studying the
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
- Runtime host (design): c7g.large (Graviton3 Neoverse-V1, Ubuntu 22.04 arm64). **As built, no cloud-leg number was ever produced there** — non-metal Graviton has no `/dev/kvm` (ADR-002), so the QHV host + guest and every cloud-leg measurement run on the local Windows PC under TCG; AWS's remaining role is the `a1.metal` KVM test bed. See `docs/digital-twin-design.md` §1.
- Honest framing: the Windows-host pivot is a **friction/cost optimisation only**. The build host runs only `mkqnximage` and host-side QNX tooling (no guests run on it) and produces a target-aarch64 IFS via cross-compilation; per F1's arch-agnostic-IFS argument, host platform (Windows vs Linux x86_64) affects only build metadata (embedded paths, timestamps), not the ARM code QNX boots, so F5 Q2 (any x86_64-built IFS boots on Graviton) is the only verification needed — there is no separate cross-host build-determinism check. The pivot is also NOT closer to a real DRIVE OS customer build environment than EC2 — DRIVE OS customer builds typically sit on rented or vendor-provided Linux hosts, not local Windows.

**Hardware twin (Orin Nano):**
- Jetson Orin Nano Dev Kit ($499) — Ampere GPU, 6× Cortex-A78AE, 8 GB RAM
- Host OS: NVIDIA L4T (JetPack 6, Ubuntu 22.04 base) — also plays the "Compute partition" role
- `/dev/kvm` is present on A78AE, but KVM boot of the QNX IFS hangs on the
  GICv3/NISV defect (`docs/orin-port.md`); QEMU runs the guest under **TCG**
  on this board — for the QHV leg TCG is a hard requirement anyway (nested
  virt), and it needs QEMU ≥ 9.0 there (EL2 virtual-timer IRQ; 6.2 hangs)

**Common across both twins:**
- VM0 — Safety proxy: QNX SDP 8.0, aarch64 `virt` machine, NCEULA (Everywhere)
- VM1 — Compute proxy: Linux aarch64 — **Phase 3 / Orin only** (L4T native). Per
  [ADR-002](docs/phase2-topology-decision.md) there is **no Linux guest on the
  cloud leg** (the cloud Compute-VM premise was falsified — no `/dev/kvm`, host
  `io-sock` down).
- IPC (cloud leg): QNX-host (`qnx-qhv`) ↔ QNX-guest (`qnx-guest`) over the `qvm`
  `virtio-console` vdev — crosses the real EL2/EL1 partition boundary, TCG-emulated,
  **no** `br0`/tap (host `io-sock` never comes up because the launch line presents no virtio-net/-rng device — a launch-line omission per ADR-002 RQ-4, not an image property; with the devices presented it does). See [ADR-002](docs/phase2-topology-decision.md).
- IPC (Phase 3 / Orin leg): heterogeneous QNX↔Linux over host bridge `br0` + tap
  devices (`tap-qnx` / `tap-linux`) + virtio-net under TCG (KVM boot is blocked; `docs/orin-port.md`) — this bridged path
  belongs to Orin, **not** the cloud leg.
- Reference architecture: NVIDIA DRIVE OS dual-VM partition design (public docs)

**Dev driver / build host:** local Windows PC (x86_64) — both the
IDE / git / SSH-into-AWS workstation **and**, as of the 2026-05-07
amendment in [docs/findings.md](docs/findings.md), the primary QNX
SDP 8.0 build host. QNX Software Center, SDP install, and IFS build
all run natively on Windows; the resulting `output\ifs.bin` is scp'd
to the runtime host: the c7g.large Graviton by design; as built, the
cloud leg boots the images locally under QEMU TCG and they are copied to
the Orin (ADR-002; `docs/orin-port.md` step 4). The EC2 t3.medium x86_64
Ubuntu host stays in the repo as a fallback for users without a
local x86_64 Windows or Linux box. Honest framing: this collapses
two roles (dev driver + build host) onto one machine and removes the
ssh / X11 / browser hops needed to drive the QNX Software Center GUI
on a remote EC2 — but it does **not** demonstrate build-environment
parity with a real DRIVE OS customer's Linux build host. A separate
Windows-built vs. EC2-built equivalence check was planned and then
withdrawn as over-specified (`docs/findings.md` 2026-05-07 amendment;
`docs/bsp-selection.md` F5 note). The Macbook
Pro M1 Max remains usable as a secondary IDE / SSH terminal but
cannot host SDP 8.0 (no macOS installer in 8.0).

---

## Directory structure

```
qnx-linux-dual-vm-proxy/
├── README.md                  # public-facing project overview
├── AGENTS.md                  # this file (Codex guidance)
├── LICENSE                    # MIT (source only; not QNX/Linux binaries)
├── docs/                      # narrative, decisions, findings
├── agents/                    # sub-prompt templates per agent in the roster
├── scripts/                   # cloud-twin scripts (top-level), orin/, twin/
├── ipc-test/                  # Phase 2 cross-VM IPC client/server source
├── results/cloud/             # Phase 2 latency CSVs (cloud leg, run on the Windows PC)
├── results/hw/                # Phase 3 latency CSVs (Orin twin)
├── logs/sample-boot/          # curated boot logs (Phase 1)
├── skills/                    # FMEA, ISO 26262, ASPICE, BSP-porting, digital-twin, jetson, tegra-virt, 21434
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
| `.codex/agents/<name>.toml` | Codex Task tool | TOML (`name`, `description`, `developer_instructions`) with a concise system prompt | Native subagent invocation: `subagent_type: <name>` |

The `.codex/agents/` files are intentionally thin and refer back to `agents/<name>.md` for full context. Edit both together so they don't drift.

**How to invoke a subagent (in any Codex session):**

1. Ask the orchestrator (the main session): _"Run the Research agent on the F6 BSP questions in `docs/bsp-selection.md`."_
2. The orchestrator spawns a Task tool call with `subagent_type: research` and a concrete task description.
3. The subagent reads `AGENTS.md` + `agents/research.md` + the target phase doc, does its work, returns a summary.
4. The orchestrator integrates the result and decides next agent.

**Phase 1 starting sequence (concrete):**

> **Superseded in part by [ADR-002](docs/phase2-topology-decision.md) (Accepted).**
> Steps 3–5 below assume the falsified cloud topology — KVM + `br0`/tap +
> a dual QNX/Linux VM launch. The as-built cloud leg is the QHV host
> `qvm` + a **single** QNX guest under QEMU **TCG** (no KVM, no
> `br0`/tap, no Linux guest). Treat `setup-bridge.sh` and
> `launch-linux-vm.sh` on the cloud runtime as **not used on cloud**;
> they belong to the Phase-3 Orin heterogeneous path. The live cloud
> bring-up path is `scripts/qhv/` (first booted 2026-06-11; see that day's
> QHV milestone in [docs/findings.md](docs/findings.md)) and the Phase-2
> IPC is QNX-host↔QNX-guest over the `qvm` virtio-console vdev.

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

- No certified Type-1 hypervisor: the QNX Hypervisor runs uncertified, emulated under QEMU TCG and natively on a consumer devkit (Phase 3b); QEMU and KVM serve OS bring-up, not partition isolation
- No ASIL-B/D safety claim
- No MISRA-C compliance
- No GPU virtualization or vGPU partitioning
- No certified bootloader chain (no SecureBoot / measured boot)
- No real-time scheduling guarantees across the proxy boundary
- No ISO 26262 / Automotive SPICE process artifacts (study notes only — see `skills/`)

These limitations are deliberate; documenting them precisely *is* the point.

---

## NVIDIA JD mapping — internal working reference (do NOT surface in README)

> **For Codex sessions only.** When deciding what to prioritise,
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
| QNX OS for Safety (QOS) — *stand out* | Honest gap: SDP ≠ QOS; framed as "POSIX-realtime proxy" + the README limitations table + `docs/architecture.md` (a dedicated `skills/qnx-safety/` note is still **unwritten** — do not link it) |
| Hypervisors / virtualization — *stand out* | Phase 3 comparison doc: explicit gap analysis vs. real hypervisor |
| Bootloaders — *stand out* | Phase 1 (U-Boot for Linux guest, IPL for QNX) |
| ASPICE / ISO 26262 — *stand out* | `skills/iso-26262/` + `skills/aspice/` study notes; applied FMEA in `skills/fmea/examples/` |

---

## Working conventions

- **Test before claim**: never write "it works" without a log, a number, or a diff.
- **Honest framing**: every claim is paired with what it does NOT demonstrate.
- **One bundled PR per Phase milestone**, not many tiny PRs.
- **Commit style**: `<phase>: <imperative summary>` (e.g. `phase-0: scaffold repo and add AGENTS.md`).
- **Secrets**: never commit `.pem`, `.env`, instance IDs, AWS keys. Loaded from `.env` (gitignored).
- **Cost discipline**: run `scripts/ec2/teardown.sh` after every session; document spend in findings docs.
- **`skills/` are study artifacts**, not certification evidence — say so explicitly in any doc that cites them.

---

## Phase status

> **Updated 2026-09-08; Phase 3b, Phase 4 and next actions refreshed 2026-09-11.** This section had drifted badly — it still said
> "Phase 0 ← current" long after Phases 1–4 had real work and real
> numbers. `docs/findings.md` is the authoritative, dated ground truth;
> `CLAUDE.md`'s Phase-status section carries the same content in more
> detail. Treat both as summaries that can lag findings.md.

- Phase 0 — Bootstrap / scaffold + Digital Twin re-scope — **done**
- Phase 1 — Cloud twin bring-up — **done**: QHV host + a single QNX
  guest under QEMU **TCG**, demonstrated on the local Windows build
  host, *not* AWS — non-metal Graviton has no `/dev/kvm`/EL2
  (ADR-002, `docs/phase2-topology-decision.md`). There is **no Linux
  guest on the cloud leg**.
- Phase 2 — Cloud twin IPC + latency — **partial, real numbers,
  honestly capped**: measured P50/P99/Max in
  `results/cloud/cloud-ipc-latest.csv`. A non-deterministic `qvm`/TCG
  virtio-queue stall is still **not root-caused**; it is now
  *survivable* via a kick-safe sentinel frame (19/19 real stalls
  recovered across 4 boots). ADR-002's RQ-2 `vdev shmem` transport is
  separately resolved **yes**, host to guest and back.
- Phase 3 — Hardware twin (Jetson Orin Nano) — **substantial, not
  closed**: heterogeneous QNX to Linux IPC over a real `br0`/`tap-qnx`
  bridge works — two clean 100,000-iteration runs, zero errors
  (`results/hw/orin-ipc-latest.csv`). **KVM boot is blocked** by a
  root-caused GICv3 / `KVM_EXIT_ARM_NISV` defect, since reproduced on
  AWS `a1.metal` (a second ARM vendor), so TCG is the interim
  transport. Honest caveat: that IPC run used a **rebuilt** IFS, not
  the byte-identical Phase-1 image.
- Phase 3b — Native QNX on the Orin Nano (ADR-003 option B) — **M0, M1,
  M2, M1b and M3 met**: entered by kexec from L4T, with no QEMU, the QNX
  Hypervisor host runs at EL2 and booted the cloud-leg QNX guest (M3,
  2026-09-10). M3's figures stay on the local branch
  `m3-results-unpublished` until the 4.6(i) consultation. **Decision
  2026-09-11 (owner, option B):** M4-F, then M5-F, then S1-F (a Linux
  guest without a GPU under native qvm), then freeze reference
  architecture v1, then one measurement campaign. Earlier measurements
  are architecture-version history. See `docs/orin-native-port-plan.md`.
- Phase 4 — Twin diff + DRIVE OS comparison — **started**: boot-time
  twin diff done on the plain leg (n=5 per side; Orin +23–25% slower
  than Windows; now A2 history). A second leg on the *hypervisor*
  topology (QHV host + guest, same images on both hosts) boots on the
  Orin under a from-source QEMU 11.1.0 (the distro 6.2.0 hangs on an
  EL2/VHE timer defect — QEMU-side, not host). The release-aligned pair
  ran on 2026-09-09 and is now A3 history; the twin diff is re-run in
  the v1 campaign — see CLAUDE.md Phase 4 and
  `docs/digital-twin-design.md` §1a. `docs/drive-os-comparison.md`'s
  verdicts wait for that campaign.
- Phase 5 — FuSa & Cybersecurity overlay — not started as a dedicated
  phase (a Phase-1-gate FuSa + Cyber pass did run).
- Phase 6 — Polish, public README, demo recording — not started.
- Phase 7 (stretch) — Domain-controller extension, two tracks frozen in
  `docs/future-multi-soc.md`: the original multi-SoC idea (a
  Qualcomm-Cockpit-class proxy alongside the NVIDIA one) and a newer
  NVIDIA-primary single-SoC convergence track.

Next actions: see the identically-named list in `CLAUDE.md`'s Phase
status section. Since the 2026-09-11 owner decision the Phase 3b order
leads: M4-F, M5-F, S1-F, freeze reference architecture v1, then one
measurement campaign (`docs/orin-native-port-plan.md`, freeze section).
