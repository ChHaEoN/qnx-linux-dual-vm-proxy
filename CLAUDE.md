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
- Build host: t3.medium x86_64 Ubuntu 22.04 (QNX SDP 8.0 host toolchain is x86_64-only)
- Runtime host: c7g.large (Graviton3 Neoverse-V1, Ubuntu 22.04 arm64, KVM-on-arm64)

**Hardware twin (Orin Nano):**
- Jetson Orin Nano Dev Kit ($499) — Ampere GPU, 6× Cortex-A78AE, 8 GB RAM
- Host OS: NVIDIA L4T (JetPack 6, Ubuntu 22.04 base) — also plays the "Compute partition" role
- KVM enabled on A78AE; QEMU runs the QNX guest on bare arm64 silicon

**Common across both twins:**
- VM0 — Safety proxy: QNX SDP 8.0, aarch64 `virt` machine, NCEULA (Everywhere)
- VM1 — Compute proxy: Linux aarch64 (Ubuntu 22.04 cloudimg on AWS; L4T on Orin)
- IPC: virtio-net via host bridge `br0` + tap devices (`tap-qnx` / `tap-linux`)
- Reference architecture: NVIDIA DRIVE OS dual-VM partition design (public docs)

**Dev driver:** Macbook Pro M1 Max (arm64 macOS) — used purely as the
local IDE / git / SSH-into-AWS workstation. The toolchain is **not**
expected to run on the Mac; QNX install, IFS build, and all VM
validation live on AWS (build = t3.medium x86_64; runtime = c7g.large
arm64). This keeps the validation surface single-sourced and avoids
opening a Rosetta-2 / x86-VM-on-Mac side quest.

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

```text
1. research              → close out F6 BSP questions in docs/bsp-selection.md (Rosetta-2 and IFS-on-Orin claims)
2. architect             → review research findings; lock Phase 1 plan or trigger fallback (F6 risk register)
3. implementation        → run scripts/bootstrap-build-host.sh + scripts/bootstrap-runtime-host.sh end-to-end
4. implementation        → scripts/build-qnx-ifs.sh (build host) + setup-bridge.sh + launch-{qnx,linux}-vm.sh
5. test                  → capture boot logs into logs/sample-boot/cloud-{qnx,linux}-boot1.log; record QNX boot time
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

## NVIDIA JD mapping (AVOS / DRIVE OS Software Engineer, customer-facing)

Full table: [docs/jd-mapping.md](docs/jd-mapping.md). Summary:

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

- **Phase 0** — Bootstrap / scaffold + Digital Twin re-scope ← *current*
- Phase 1 — Cloud twin bring-up (QNX + Linux booting on AWS QEMU/KVM)
- Phase 2 — Cloud twin IPC + latency benchmark
- Phase 3 — Hardware twin port (same IFS / same code on Jetson Orin Nano)
- Phase 4 — Twin diff + DRIVE OS comparison
- Phase 5 — FuSa & Cybersecurity overlay (FMEA, ASIL gap, STRIDE threat model)
- Phase 6 — Polish, public README, demo recording
- Phase 7 (stretch) — Multi-SoC domain-controller extension: add a
  Qualcomm-Cockpit-class proxy on AWS, exercise inter-SoC IPC (QC ↔ NV).
  Feasibility frozen in `docs/future-multi-soc.md`; not started until Phase 6 lands.

Next action after scaffold: invoke 🔍 **Research Agent** on the open
empirical questions in `docs/bsp-selection.md` (chiefly: same IFS
portability to QEMU-on-Orin; JetPack 6 KVM availability).
