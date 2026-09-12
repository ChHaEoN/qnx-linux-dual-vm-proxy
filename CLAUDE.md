# CLAUDE.md — qnx-linux-dual-vm-proxy

> Guidance for any Claude Code session working in this repo.
> Read this file first; do not assume the project's framing from filenames alone.

---

## Mission (honest framing)

This repo is a **Digital Twin design** of the NVIDIA DRIVE OS dual-VM
partition architecture, running QNX SDP 8.0 (Safety proxy) + Linux aarch64
(Compute proxy):

- **Cloud twin:** ~~QEMU/KVM on AWS Graviton (c7g.large) — fast iteration, regression sweeps.~~
- **Hardware twin:** ~~QEMU/KVM on~~ **Jetson Orin Nano Dev Kit** (Cortex-A78AE, same Tegra family as DRIVE Orin) — validation on real silicon.

**2026-09-11:** as built, no working leg uses KVM. The cloud leg is the QNX
Hypervisor in QEMU TCG on the Windows PC (A1), because non-metal Graviton has
no `/dev/kvm`. The Orin plain leg ran QEMU TCG beside L4T (A2), because KVM
boot hangs. The same hypervisor images boot in TCG on both hosts (A3). Phase 3b
runs the QNX Hypervisor natively on the Orin (A4). The ids are the rows of the
plan's architecture table
([freeze section](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

~~The same QNX IFS and the same IPC client/server source run on both sides
unchanged; the only thing that changes is the host.~~ The **twin diff**
~~(what actually changes when only the host changes?)~~ is the load-bearing
measurement. **2026-09-11:** the identical-image invariant holds only for the
hypervisor leg (A3). There "host" is a bundle of CPU, OS, TCG backend and QEMU
build, not one variable ([digital-twin-design.md](docs/digital-twin-design.md)
§1a). The Orin IPC run used a rebuilt IFS and a different server program. The
twin diff is re-run once, in the v1 campaign.

~~**This is not a real hypervisor.** There is no Type-1 partition isolation,~~
**2026-09-11:** there is no *certified* Type-1 isolation. The uncertified QNX
Hypervisor runs emulated in TCG (A1, A3) and natively on the Orin (A4); KVM
appears only in the blocked GICv3/NISV track. There is also
no ASIL-D guarantee, no certified RTOS, no GPU partitioning. ~~KVM-on-Linux
is host-mediated, not certified Type-1.~~ The value is in studying the
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
  **no** `br0`/tap (host `io-sock` never comes up because the launch line presents no virtio-net/-rng device — a launch-line omission per ADR-002 RQ-4, not an image property; with the devices presented it does). See [ADR-002](docs/phase2-topology-decision.md).
- IPC (Phase 3 / Orin leg): heterogeneous QNX↔Linux over host bridge `br0` + tap
  devices (`tap-qnx` ~~/ `tap-linux`~~) + virtio-net ~~under KVM~~ — this bridged path
  belongs to Orin, **not** the cloud leg. **2026-09-11:** it ran under TCG, because
  KVM boot is blocked by the GICv3/NISV defect. Only `tap-qnx` exists: the Linux
  client runs natively on L4T ([orin-port.md](docs/orin-port.md) step 3). It is
  A2 history.
- Reference architecture: NVIDIA DRIVE OS dual-VM partition design (public docs)

**Dev driver / build host:** local Windows PC (x86_64) — both the
IDE / git / SSH-into-AWS workstation **and**, as of the 2026-05-07
amendment in [docs/findings.md](docs/findings.md), the primary QNX
SDP 8.0 build host. QNX Software Center, SDP install, and IFS build
all run natively on Windows; the resulting `output\ifs.bin` ~~is scp'd
to the c7g.large Graviton runtime host~~ **(2026-09-11: the images run on the
Windows PC under TCG and are copied to the Orin; no leg ran on the c7g.large,
and the only AWS run was the `a1.metal` KVM hang reproduction)**. The EC2 t3.medium x86_64
Ubuntu host stays in the repo as a fallback for users without a
local x86_64 Windows or Linux box. Honest framing: this collapses
two roles (dev driver + build host) onto one machine and removes the
ssh / X11 / browser hops needed to drive the QNX Software Center GUI
on a remote EC2 — but it does **not** demonstrate build-environment
parity with a real DRIVE OS customer's Linux build host, ~~and Phase 1
must still verify Windows-built vs. EC2-built IFS produce equivalent
output before the pivot is treated as fully validated~~. **2026-09-11:** that
check was withdrawn on 2026-05-07 ([bsp-selection.md](docs/bsp-selection.md)
F5 note), and none is planned. The Macbook
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
├── scripts/                   # cloud-twin scripts (top-level), qhv/, orin/, twin/
├── ipc-test/                  # Phase 2 cross-VM IPC client/server source
├── orin-native/               # Phase 3b native-port source: shim, startup board dir, tools, qvm configs, M4 tooling
├── results/cloud/             # Phase 2 latency CSVs (cloud leg, run on the Windows PC under TCG; A1 history)
├── results/hw/                # Phase 3 latency CSVs (Orin twin)
├── results/orin-native-port/  # Phase 3b plan inputs and run records (later run directories are git-ignored)
├── results/gicv3-nisv-debug/  # GICv3/NISV collector reports
├── logs/sample-boot/          # curated boot logs and captures, all phases
└── skills/                    # FMEA, ISO 26262, ASPICE, BSP-porting, digital-twin, jetson, tegra-virt, 21434
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
| 14 | 🧭 **Twin Sync** (Phase 3+) | Integration engineer | orchestrates ~~AWS↔Orin~~ cloud-leg↔Orin parity; owns `scripts/twin/sync.sh` and `scripts/twin/sync-qhv.sh` (**2026-09-11:** the cloud leg runs on the Windows PC, and the hypervisor images move with `sync-qhv.sh`; `sync.sh` needs `rsync`, which Git Bash lacks) |

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

- ~~No Type-1 / Type-2 hypervisor (QEMU + KVM is for OS bring-up, not partition isolation)~~ **2026-09-11:** no *certified* Type-1 isolation. The uncertified QNX Hypervisor runs in TCG (A1, A3) and natively on the Orin (A4); KVM appears only in the blocked GICv3/NISV track.
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
| OS internals, multi-threading, IPC, memory mgmt | Phase 2 (`ipc-test/`), Phase 1 BSP work |
| BSP porting and device driver internals | Phase 1 (QNX virt BSP, Linux rootfs) |
| Multicore / heterogeneous SoCs | ~~Graviton3 multi-core~~ **2026-09-11:** six Cortex-A78AE cores native (M2, Phase 3b); QEMU SMP guest config |
| Customer-facing AVOS/DRIVE OS support | Framing: this proxy IS the kind of software-layer customer environment an SE helps port |
| ECU bring-up, profiling, debug | Phase 1 (boot logs, kernel debug) + Phase 2 (latency profiling) |
| QNX OS for Safety (QOS) — *stand out* | Honest gap: SDP ≠ QOS; framed as "POSIX-realtime proxy" + the README limitations table + `docs/architecture.md` (a dedicated `skills/qnx-safety/` note is still **unwritten** — do not link it) |
| Hypervisors / virtualization — *stand out* | ~~Phase 3~~ Phase 4 comparison doc: explicit gap analysis vs. real hypervisor. **2026-09-11:** also the QNX Hypervisor host, native on the Orin (Phase 3b) |
| Bootloaders — *stand out* | ~~Phase 1 (U-Boot for Linux guest, IPL for QNX)~~ **2026-09-11:** no leg has run U-Boot or a Linux guest. The bootloader work is the kexec shim (M0) and the planned M5-F UEFI cold boot (Phase 3b) |
| ASPICE / ISO 26262 — *stand out* | `skills/iso-26262/` + `skills/aspice/` study notes; applied FMEA in `skills/fmea/examples/` |

---

## Working conventions

- **Test before claim**: never write "it works" without a log, a number, or a diff.
- **Honest framing**: every claim is paired with what it does NOT demonstrate.
- **One bundled PR per Phase milestone**, not many tiny PRs.
- **Commit style**: `<phase>: <imperative summary>` (e.g. `phase-0: scaffold repo and add CLAUDE.md`).
- **Secrets**: never commit `.pem`, `.env`, instance IDs, AWS keys. Loaded from `.env` (gitignored).
- **Cost discipline**: run ~~`scripts/ec2/teardown.sh`~~ **(2026-09-11: that script is in no commit of this repo; the one AWS run since, the `a1.metal` repro, terminated its instance right after capture)** after every session; document spend in findings docs.
- **`skills/` are study artifacts**, not certification evidence — say so explicitly in any doc that cites them.

---

## Phase status

> **Updated 2026-09-08** — refreshed together with README.md and
> AGENTS.md, both of which had drifted further than this section had
> (README still announced "Phase 0 — Bootstrap" and claimed KVM worked
> on Orin). Treat `docs/findings.md` as the authoritative, dated ground
> truth whenever this section drifts again — findings.md is updated
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
  **Open:** a non-deterministic `qvm`/TCG virtio-queue stall (~1–2%
  per iteration) caps reliable runs well short of the 100k-iteration
  target — root cause still **not** found, not closed. See
  [ipc-test/qnx-host-client/README.md](ipc-test/qnx-host-client/README.md).
  **Two things changed since that was written, neither of them a
  root-cause fix:** (a) a kick-safe sentinel frame
  (`FRAME_SENTINEL_SEQ`, `ipc-test/common/frame.h`) makes the stall
  *survivable* — 19/19 real stalls recovered across 4 boots, zero
  alignment corruption, recovered iterations correctly excluded from
  the timing stats; the underlying hazard rate is unchanged, and the
  committed run size is still 15 timed iterations (raising it is a
  deliberate open decision, not an oversight). (b) ADR-002's RQ-2
  shared-memory transport is **resolved yes, both directions**: host
  and guest attach to the same `vdev shmem` region and exchange bytes
  two-way — see
  [ipc-test/qnx-guest-shmem-probe/README.md](ipc-test/qnx-guest-shmem-probe/README.md).
  The interrupt/notify-driven path was deliberately not attempted.
- Phase 3 — Hardware twin port to Jetson Orin Nano — **substantial
  progress, not closed**: Orin Nano flashed (JetPack 6/L4T R36.4.7)
  and SSH-reachable; the plain `qnx-safety-vm` IFS boots under
  **TCG** on real hardware. **KVM-accelerated boot is blocked** by a
  real, root-caused defect — a GICv3 distributor bring-up instruction
  takes a `KVM_EXIT_ARM_NISV` Data Abort that neither KVM nor QEMU
  6.2.0 can emulate and QNX's `startup-qemu-virt` has no handler for
  (see `docs/orin-port.md`'s risk register) — TCG is the accepted
  interim transport, not a permanent substitute for ~~the hardware-timed
  KVM number this phase still owes~~ a hardware-timed number. **2026-09-11:**
  the hardware-timed route is the native port (Phase 3b, ADR-003), and its
  numbers come from the v1 campaign. KVM stays a defect-filing track.
  **As of 2026-07-29 that defect is
  no longer Tegra-specific:** the identical IFS hangs in the identical
  way (`FOUND GICv3 ITS`, then silence, process alive throughout) on
  AWS `a1.metal` — Graviton1 / Annapurna Labs, Cortex-A72, a different
  vendor and core generation. Log:
  [logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log](logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log).
  One run, not a repeated series — strong single-data-point evidence,
  not a hardened claim — but enough to raise it with QNX/BlackBerry as
  a general `startup-qemu-virt` GICv3 bring-up defect rather than a
  Jetson quirk. Networking (`io-sock`/virtio-net)
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
  comparison) and a boot-time delta (~~the clean host-only comparison,~~
  n=5 per side: Orin +23–25% slower than Windows). **2026-09-11:** that
  boot diff is architecture-version history (A2). Neither times file
  carries a QEMU-build, device-set or disk-mode stamp, so "only the host
  differs" cannot be checked. The owner decided it stays history; the
  experiments are redone after v1 is frozen (the plan's measurement
  inventory). Careful when citing
  the spread: Orin's full-n=5 range is ~3x tighter, but Windows' range
  is dominated by a single cold-start outlier — drop it and Windows'
  other four runs span just 33 ms, so "Orin is more consistent" is
  **not** a defensible claim; "Orin is slower" is.
  `docs/drive-os-comparison.md` (the broader
  dimension-by-dimension gap doc) is untouched — still open.
  **2026-09-08: a second, cleaner twin leg was instrumented.** The QHV
  leg turns out to be host-agnostic (its whole QEMU invocation is
  `-machine virt,virtualization=on,...` plus two image files; `qvm`,
  the guest, the vdevs and even the pty pair live *inside* the
  emulation), so the identical images can boot on Orin unchanged. That
  gives ~~a genuine one-variable comparison~~ **(2026-09-11: a comparison
  of two host bundles, not one variable; §1a)** on the **hypervisor**
  topology rather than on plain boot time — see
  [docs/digital-twin-design.md](docs/digital-twin-design.md) §1a.
  **2026-09-09:** the Orin half was run and first hung under the distro
  QEMU 6.2.0 (a QEMU-side EL2 virtual-timer wiring defect — **verified** by a
  reverted-wiring build of 11.1.0 that reproduces the hang; the host is
  excluded); with QEMU v11.1.0 built from source on the board
  (`scripts/orin/build-qemu-on-orin.sh`) **the QHV host and its guest boot
  on real ARM silicon**. A review the same day found the leg's "one
  variable" claim overclaimed and an entropy test invalid; §1a now defines
  "host" as a bundle (CPU, OS, TCG backend, QEMU build) and both
  instruments stamp QEMU binary, device set (`WITH_RNG`/`-WithRng`: the
  rng in slot 3 removes ~19 s of timeout artefact) and `-snapshot`.
  ~~Windows with rng: n=5 median 29,324 ms (QEMU 11.0.50 fork build). The
  aligned n=5 pair (both hosts, one QEMU release, rng, `-snapshot`) is
  the next deliverable.~~ **2026-09-11:** that Windows series is
  superseded. It predates release alignment: it ran on the 11.0.50 fork
  build without `-snapshot`, and its own header says it can never be
  paired. **Done 2026-09-09:** the release-aligned pair ran (that day's
  [docs/findings.md](docs/findings.md) entry; its Windows column is
  [windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt](logs/sample-boot/windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt)).
  Under the
  2026-09-11 measurement-freeze decision it is architecture-version
  history (A3), and the TCG twin legs run again once, on the frozen
  reference architecture v1. TCG here is a hard requirement (QHV needs EL2 →
  nested virt, which ARM KVM lacks on A78AE), not the GICv3 blockage —
  do not conflate them.
- Phase 3b — **Native QNX on the Orin Nano — M3 met 2026-09-10: the QNX Hypervisor host booted the cloud-leg QNX
  guest natively on the board, the same day M1, M2 and M1b ran.** M1 first: entered by kexec from L4T
  with no QEMU and no NVIDIA BSP, watched live over the J14 debug header, and
  confirmed by a stock `pidin info` reporting Release 8.0.0 on a Cortex-A78ae with
  975 MB free of 992 MB. Before that, M0 (the shim alone) closed the plan's four
  highest-ranked unknowns, starting with whether kexec hands over at EL2. Then M2:
  every secondary entered at EL2 through PSCI CPU_ON, all six cores passed
  smpcheck's pinned 60 s load (run R4, repeated by R4b; R5 added a tracelogger
  capture with events on all six), and the image reset itself
  back to L4T; record in results/orin-native-port/20260909T1100Z/m2-runs.md. Then
  M1b: with `-Q enable,el2-host` every core ran at EL2 with E2H and TGE set. A board probe showed INTID 28 (the EL2
  virtual timer, absent from the device tree) wired on all six before procnto used it as its clock, and one- and
  six-core runs passed (R1, R2, R2b; record in results/orin-native-port/20260909T1100Z/m1b-runs.md). Then M3. Native qvm at EL2 on four cores booted the byte-identical cloud-leg guest, with its disk, to its banner on
  5/5 timed runs, and the IPC pair completed its 15 iterations in every run. The run record, the curated capture and every
  measured figure are on the local, unpushed branch m3-results-unpublished until the 4.6(i) consultation; the repo is public.
  Dry run 7b is done (2026-09-11): inside a rebuilt TCG QHV host image, qvm's Class-10 IDs 0, 1 and 7 are emitted at default settings, and the plan's ring flags turned out to keep only a short tail (-k, not -S, sizes a ring); record unpublished. ~~Still ahead: the per-exit number on the board (M4).~~ **Decision 2026-09-11 (owner, option B):** each design
  change so far replaced the whole architecture (TCG, then QHV inside TCG, then the native QNX Hypervisor), so earlier
  measurements become architecture-version history, kept and not chased. ~~Still ahead, in order: M4 functional (r0 and
  r1: the trace instrument works on the board; the timed r2 waits);~~ **2026-09-11: M4-F met.** r0 and r1 passed
  functionally; r1 needed the I26 sizing fix, and its PC cross-check covered only the delivered part of a capped
  listing (m4-design.md §14.8-14.9). Still ahead, in order: M5 functional (a UEFI cold boot that reaches
  startup; the median comparison waits); S1 functional (a Linux guest without a GPU under native qvm); freeze
  reference architecture v1; then one measurement campaign on it (the M3 and M4 numbers, the M5 comparison, the twin
  diff), every record stamped with the version. ~~Awaiting the owner's confirmation: the M path ends at M5's functional
  pass, which sets when README PR #1 can merge.~~ **2026-09-11 (owner):** confirmed. The M path ends at M5-F's
  functional pass, and README PR #1 can merge then; whether a failed M5-F also ends it is still open. The owner also
  decided three more points: the M0, M1, M2 and M1b records stay public for now; S1-F needs only the qvm `dryrun` gate
  first, with the GPU checks left to the first GPU stage; and the A2 plain-leg boot diff stays history. Details in
  [the plan's freeze section](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).
  The two cluster-1 cores run at a fixed low rate under QNX,
  cause open (a frequency hypothesis is in m3-design.md §4.3; explaining it or leaving cluster 1 out is a freeze-gate
  item). Earlier state, kept for the record: ADR-003 option (B) accepted by the owner: get a hardware-timed
  QHV number from the board itself rather than a Pi 4B or AWS metal. Plan,
  claims register and milestone ladder ~~M0-M4~~ **M0-M5 plus S1 (2026-09-11)** in
  [docs/orin-native-port-plan.md](docs/orin-native-port-plan.md); the harvest,
  research and compile-only results under `results/orin-native-port/`. Two
  things are VERIFIED so far, both compile-only: the BSP zip's startup lib and
  the `armv8_fm` board build unmodified under the win64 SDP tooling (lib
  `make install` first, then the board), and an IFS at `[image=0x80081000]`
  lays out correctly for a kexec-placed payload. Four of the plan's own twelve
  load-bearing claims came back wrong or unproven under adversarial review —
  ~~most importantly a CCPLEX watchdog **is** armed at hand-off (systemd, 2 min),
  which both gives free unattended recovery and caps every experiment at ~2
  minutes unless startup disables or kicks it.~~ **2026-09-11:** the watchdog part
  was disproved by M0's `hang` test. The watchdog does not fire after kexec, so a
  hang needs a power cycle and no experiment is capped. ~~Every log this phase produces is
  evaluation output under NC QDL v7 4.6(i): private until the supervising
  professor is consulted.~~ **2026-09-11 (owner):** the M0, M1, M2 and M1b run
  records and curated captures stay public for now. M3 and later figures stay on
  the local branch m3-results-unpublished until the 4.6(i) consultation (the
  plan's §9).
- Phase 5 — FuSa & Cybersecurity overlay — not started (Phase-1-gate
  FuSa/Cyber review already happened as a cross-cutting check per the
  coordination rules above, but the dedicated Phase-5 overlay pass has not)
- Phase 6 — Polish, public README, demo recording — not started
- Phase 7 (stretch) — Multi-SoC domain-controller extension — not
  started; feasibility frozen in `docs/future-multi-soc.md`

**Next actions (pick one, they're independent):**
1. Decide whether to raise the committed cloud-leg run size now that
   sentinel recovery is proven out to 300 iterations — the cheapest
   remaining Phase-2 win, and it needs a decision, not a discovery.
   Root-causing the `qvm`/TCG stall itself stays open behind it.
   **2026-09-11:** under the measurement-freeze decision the cloud-leg
   (A1) numbers are history. The run-size question is now settled once,
   at the v1 freeze, as the campaign's IPC sample size.
2. File the GICv3/NISV defect with QNX/BlackBerry — **now the strongest
   of the three.** As of 2026-09-08 the filing no longer rests on
   disassembling their shipped binary: their own BSP source
   (`gic_v3.c`), built with their own flags, emits `str w3,[x0],#4` at
   GICD+0x420, and adding `-fno-auto-inc-dec` takes the file's MMIO
   writeback-store count from 4 to 0 with identical semantics. Still
   boot-unverified — `startup-qemu-virt` cannot be relinked without the
   `qemu-virt` board source, which the BSP does not ship. The
   cross-vendor `a1.metal` reproduction remains the other half of the
   evidence. The read-only collector `scripts/diagnose-gicv3-nisv.sh` and
   its reviewed report (`results/gicv3-nisv-debug/20260909T101030Z/summary.md`)
   list exactly which trace fields the filing still lacks (numeric
   `pc=`/`ipa=`, one logged run per `-smp`/`gic-version`/`its` variant) and
   the commands that would capture them.
   (A from-source QEMU v11.1.0 with `--enable-kvm` now exists on the Orin
   for the unrelated TCG/EL2-timer reason; re-running the `qnx-safety-vm`
   IFS under `-enable-kvm` with it is a near-zero-cost check, still
   assessed as unlikely to help — NISV is the KVM backend's deliberate
   behaviour, not a version bug — but no longer untried for want of a
   binary.)
3. ~~Finish the QHV twin diff, now that the Orin boots it: on the Orin
   `WITH_RNG=1 ./launch-qhv-on-orin-tcg.sh 5` (picks `~/qemu-v11.1.0`,
   stamps everything); on Windows install the official QEMU 11.1.0 (user
   decision — it is still a different *build* of the same release) and run
   `launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner -WithRng`; then
   compare the two times files directly (`diff-results.sh` parses the IPC
   CSVs, not boot-time files) after checking their `qemu:`/`devices:`/`disk:`
   stamps match. Regenerating the QHV images from clean sources (the shipped disk
   is the RQ-2 diagnostic variant) is a separate, number-changing step.~~
   **2026-09-11 (owner decision): take Phase 3b to the v1 freeze, then run
   one campaign.** The release-aligned QHV pair this item asked for ran on
   2026-09-09 ([docs/findings.md](docs/findings.md)). It is now A3 history,
   and the twin diff is re-run inside the campaign. In order: ~~M4-F (r0 and
   r1, after m4-design's §11 TCG rehearsal),~~ M4-F (**met 2026-09-11**), M5-F (a UEFI cold boot that
   reaches startup), S1-F (a Linux guest without a GPU under native qvm).
   Then settle the freeze gate and write the v1 manifest. Then run the
   single campaign, native leg and both TCG twin legs, every record stamped
   `arch=v1;manifest=<sha>`. Regenerating the guest disk from clean sources
   is now a freeze-gate item, not a separate later step. The owner
   decisions the freeze needs, and the PR #1 merge timing (~~assumption~~
   **confirmed by the owner 2026-09-11**), are in
   [the plan's freeze section](docs/orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).
4. **ADR-003 is decided (2026-09-09): option (B), a native QNX port to
   the Orin Nano** ([docs/adr-003-hardware-timed-qhv.md](docs/adr-003-hardware-timed-qhv.md),
   Status: Accepted). Licence stance, also decided by the owner: proceed;
   consult the supervising professor before publishing any evaluation
   results (NC QDL v7 4.6(i)); keep 4.6(c) clean — source and docs only,
   never disassembly of a QNX-shipped binary. The port is tracked as
   **Phase 3b** in [docs/orin-native-port-plan.md](docs/orin-native-port-plan.md)
   (kick-off plan + claims register; ~~nothing has booted natively yet~~
   **M0-M3 have been met since, and the 2026-09-11 freeze decision in
   item 3 now shapes the rest**) with
   the zero-cost harvest under `results/orin-native-port/`. The Pi 4B
   route in the ADR stays the documented cheaper alternative, not rejected.
5. Write `docs/drive-os-comparison.md`'s dimension-by-dimension
   verdicts ~~now that Phase 2/3/4 have real numbers to cite instead of
   projections~~. **This is the largest remaining gap in the public
   story** — ~~Phase 4's boot-diff half is done; this half is untouched.~~
   **2026-09-11:** correct the doc's stale statements now. The verdicts
   wait for the v1 campaign, and so does the twin diff; the earlier
   boot diffs are architecture-version history.

**Decision (2026-07-29):** getting a real KVM/hardware-timed number on
Orin is **deferred, not abandoned** — it genuinely needs either NVIDIA
DRIVE AGX Orin hardware (gated behind an invitation-only developer
program, not self-serve) or further paid AWS `c7g.metal` investigation,
and neither is worth blocking on right now. **Partially actioned since:**
`c7g.metal` is still not run — this account's 32-vCPU quota blocks the
64-vCPU launch outright — but an `a1.metal` fallback was run and
reproduced the hang on a second vendor's silicon, which is the more
valuable half of what that investigation was for. In its place: (a) a second
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
