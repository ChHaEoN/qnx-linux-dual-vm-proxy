# CLAUDE.md — qnx-linux-dual-vm-proxy

> Guidance for any Claude Code session working in this repo.
> Read this file first; do not assume the project's framing from filenames alone.

**This file is CURRENT STATE ONLY, and that is enforced.** It says what is true
now. It carries no strike-throughs and no stacked dated amendments: when
something changes, the old sentence is *deleted* and the new one written in its
place. `scripts/ci/claims_gate.py` fails the build if `~~` appears here.

It got that rule the hard way. Phase status had grown to 464 of 768 lines and
42 struck segments — a per-phase log living inside a briefing — so answering
"what is true now" cost a full read and failed silently when one line was
missed. History has two homes that do this properly: **`docs/findings.md`**
(append-only, dated, never rewritten) and git. Neither is here.

**When this file and `docs/findings.md` disagree, findings.md wins.** It is
updated every session real work happens; this file is a summary that can lag it.
Check it before acting on anything here that looks load-bearing.

---

## Mission (honest framing)

A study of the **software layer** under NVIDIA DRIVE OS-style dual-VM
partitioning — BSP bring-up, hypervisor host and guest, IPC patterns,
kernel/userspace boundaries, host-to-target portability — with QNX SDP 8.0 as
the Safety proxy and Linux aarch64 as the Compute proxy. The reference is
NVIDIA's public DRIVE OS dual-VM design. This is not a reproduction of it.

**Current architecture: A6.** L4T on the metal owning the GPU, with QNX SDP 8.0
running as a **KVM guest** beside it on a Jetson Orin Nano (Tegra234, six
Cortex-A78AE cores). A6 is a direction, not a frozen reference architecture;
its sample sizes are still the owner's to choose.

Architecture ids **A1–A6** are the rows of the plan's
[architecture table](docs/orin-native-port-plan.md#architecture-versions).
Every earlier leg is history and is not re-run:

| id | what it was | status |
|---|---|---|
| A1 | cloud leg: QHV (`qvm`) + one QNX guest under QEMU **TCG**. Designed for AWS Graviton; as built it ran on the local Windows PC | history |
| A2 | Orin plain leg: QEMU **TCG** beside L4T, QNX↔Linux IPC over `br0`/`tap-qnx` | history |
| A3 | the same QHV images in TCG on both hosts | history |
| A4 | the QNX Hypervisor **natively at EL2** on the Orin's own cores, no QEMU | met functionally; figures unpublished; superseded as a direction |
| A5 | A4 plus a Linux guest under `qvm` (S1-F) | met functionally; figures unpublished |
| A6 | **current** — L4T on the metal with the GPU, QNX as a KVM guest | measurements run; gate open on sample sizes |

**Why A4 was superseded (2026-09-18).** Under a native QNX Hypervisor on
Tegra234 **no OS can use the GPU**: the iGPU has no SMMU stream ID, and its
clock, reset and power go through BPMP, for which QNX has no client driver. A4
is not withdrawn and its milestone passes are real — it is simply no longer the
direction.

**What is real.** A real `qvm` Type-1 arrangement ran at EL2 on A78AE silicon
with two guests. A QNX guest boots under KVM on the Orin and on AWS `a1.metal`.
Cross-partition IPC is timed on hardware. Cyclone DDS runs inside the QNX guest.

**What is not.** Nothing here is certified: SDP 8.0 is **not** QNX OS for
Safety. There is no ASIL claim, no isolation or freedom-from-interference
result, no GPU partitioning, and no real-time guarantee. Pairing every claim
with what it does *not* demonstrate is itself part of the engineering narrative
this portfolio is for.

**There will never be a QNX Hypervisor number in this project** (owner decision
OD10, 2026-09-20). QHV needs EL2 and ARM KVM does not nest on A78AE, so it
cannot run under KVM; OD10 withdrew the TCG legs that were its only emulated
route; and A4's native figures are unpublished. The hypervisor result is
permanently a set of **functional passes with no timing**.

---

## Tech stack

**Build host: the local Windows PC** (x86_64), which is also the dev driver.
QNX SDP 8.0 ships a Windows-native installer; QNX Software Center, the SDP
install and `mkqnximage --arch=aarch64le` all run there, and the resulting
`output\ifs.bin` is copied to the Orin or run locally under QEMU TCG. No guest
runs on the build host itself beyond the TCG legs.

Honest framing: this collapses two roles onto one machine and removes the
ssh/X11 hops needed to drive the SDP's GUI on a remote EC2. It does **not**
demonstrate parity with a real DRIVE OS customer's Linux build host — those are
typically rented or vendor-provided Linux. A Windows-vs-EC2 build-equivalence
check was withdrawn on 2026-05-07 ([bsp-selection.md](docs/bsp-selection.md) F5)
and none is planned. An EC2 t3.medium fallback stays in the repo for users with
no local x86_64 machine. The MacBook Pro M1 Max is a usable IDE/SSH terminal but
cannot host SDP 8.0 (no macOS installer in 8.0).

**Target: Jetson Orin Nano Dev Kit** — Ampere iGPU, 6× Cortex-A78AE, 8 GB RAM,
NVIDIA L4T (JetPack 6, Ubuntu 22.04 base). L4T is the host and plays the
Compute-partition role.

**KVM on this board works, with one caveat that matters.** The SDP's *shipped*
`startup-qemu-virt` hangs after 17 bytes of serial (`FOUND GICv3 ITS`) under
`-enable-kvm`. A `startup-qemu-virt` **we rebuilt** — board source at
`orin-native/startup/qemu-virt/`, startup library compiled `-fno-auto-inc-dec`,
which removes a writeback MMIO store at GICD+0x420 that reports ISV=0 and so
cannot be emulated — boots to procnto and, with virtio blk/net/rng presented in
the order the image's `startup.sh` requires, to the guest banner. **This is not
a QNX-supported configuration**: QNX ships no such binary.

**AWS** is a test bed, never a runtime host. Non-metal Graviton exposes no
`/dev/kvm` at all ([ADR-002](docs/phase2-topology-decision.md)), so no cloud leg
was ever built there. Bare metal is different: `a1.metal` has `/dev/kvm`, the
same rebuilt startup boots a QNX guest under KVM there, and on 2026-09-20 it
provided the second host for a boot-time comparison against the Orin on a
byte-identical image. **No IPC, latency or throughput figure has ever been taken
on any cloud host.** `c7g.metal` stays quota-blocked (64 vCPU against a 32-vCPU
account limit).

**IPC paths, by leg.** A1: QNX host ↔ QNX guest over the `qvm` virtio-console
vdev, crossing a real EL2/EL1 boundary under TCG. A2 and A6: heterogeneous
QNX↔Linux over host bridge `br0` + `tap-qnx` + virtio-net. Only `tap-qnx`
exists — the Linux client runs natively on L4T.

**Reference architecture:** NVIDIA DRIVE OS dual-VM partition design, public
docs. The dimension-by-dimension gap analysis is
[drive-os-comparison.md](docs/drive-os-comparison.md).

---

## Directory structure

```
qnx-linux-dual-vm-proxy/
├── README.md                  # public-facing project overview; its Status table is authoritative
├── CLAUDE.md                  # this file (Claude Code guidance) — current state only
├── LICENSE                    # MIT (source only; not QNX/Linux binaries)
├── docs/                      # narrative, decisions, findings
├── agents/                    # sub-prompt templates per agent in the roster
├── scripts/                   # bring-up scripts (top-level), ci/, qhv/, orin/, twin/
├── ipc-test/                  # cross-VM IPC client/server source
├── orin-native/               # Phase 3b native-port source: shim, startup board dir, tools, qvm configs
├── results/cloud/             # A1 latency CSV — recorded on the WINDOWS PC, not a cloud host; see its README
├── results/hw/                # A2 latency CSVs (Orin twin)
├── results/orin-native-port/  # Phase 3b and A6 run records (per-milestone subdirectories are git-ignored)
├── results/gicv3-nisv-debug/  # GICv3/NISV collector reports
├── logs/sample-boot/          # curated boot logs and captures, all phases
└── skills/                    # FMEA, ISO 26262, ASPICE, BSP-porting, digital-twin, jetson, tegra-virt, 21434
```

Each placeholder file carries a `Phase N` tag in its header. Do not strip Phase tags.

---

## Agents (delegate work to these roles)

The roster is modelled on real automotive SDV team roles. Each agent has a
sub-prompt template at `agents/<agent-name>.md`.

| # | Agent | Industry-role mapping | Primary responsibilities |
|---|-------|---|---|
| 1 | 🔍 **Research** | Tech scout / requirements engineer | external research (BSP, license, baselines, Jetson L4T quirks); fills decision-record stubs |
| 2 | 📐 **Architect / Planner** | System architect | architecture diagrams, phase decomposition, risk assessment; arbitrates trade-offs from Research |
| 3 | 🏗️ **Implementation** | Software engineer | scripts, configs, IFS build wrappers, IPC C99 source, infra-as-code |
| 4 | 🧪 **Test / V&V** | Verification & validation engineer | unit + integration tests, latency benchmarks, regression sweeps, twin-diff measurements |
| 5 | 🛡️ **FuSa-Analysis** | FuSa analyst (ISO 26262) | HARA, FMEA, DFA — *finds* hazards and failure modes; produces `skills/fmea/examples/<phase>-fmea.md` |
| 6 | 🛡️ **FuSa-Design** | FuSa architect (ISO 26262) | Safety Concept, Technical Safety Requirements (TSR), safety mechanism design — *designs* mitigations |
| 7 | 🛡️ **FuSa-Verification** | FuSa V&V engineer (ISO 26262) | FMEDA, fault injection plans, residual-risk argument — *proves* the mitigations work |
| 8 | 🔐 **Cyber-Analysis** | Cybersec analyst (ISO/SAE 21434) | TARA — asset / threat / damage / attack-feasibility tables; *finds* threats |
| 9 | 🔐 **Cyber-Design** | Cybersec architect (ISO/SAE 21434) | Cybersecurity Concept + Technical Cybersecurity Requirements, mechanism selection; *designs* mitigations |
| 10 | 🔐 **Cyber-Verification** | Cybersec V&V engineer (ISO/SAE 21434) | Pen-test plans, fuzzing harnesses, vulnerability management, NCEULA + supply-chain audit; *proves* mitigations work |
| 11 | 📝 **Docs** | Tech writer | README, findings log, comparison doc; cross-links between artifacts |
| 12 | 📊 **Comparison** | Domain analyst | dimension-by-dimension DRIVE OS gap doc; honest verdicts |
| 13 | 🎓 **Skills** | Knowledge curator | populates `skills/*` paradigm READMEs; worked examples per phase milestone |
| 14 | 🧭 **Twin Sync** | Integration engineer | cloud-leg↔Orin parity; owns `scripts/twin/sync-qhv.sh` (`sync.sh` needs `rsync`, which Git Bash lacks) |

**Coordination rules:**

- **Forward flow per Phase milestone:** Research → Architect → Implementation → Test.
- **FuSa (3 sub-roles) and Cybersecurity (3 sub-roles) are cross-cutting:** they review at every Phase boundary, not just at the end. Internal flow within each is **Analysis → Design → Verification** (ISO 26262 / 21434 V-model order). The two disciplines pair-review at phase gates for cyber-FuSa interaction analysis.
- **Docs / Comparison / Skills are continuous:** they pull from the work products of the other agents.
- Multiple agents may run in **parallel** only when their work products do not overlap (FuSa worksheet + Cybersecurity threat model: fine; two Implementation agents on the same script: not).
- **Room to grow:** candidates for future addition are Performance, Release / DevOps, and a Customer-facing Application Engineer who would role-play DRIVE OS customer-port engagements.

**Where the agent definitions live (two locations, on purpose):**

| Location | Audience | Format | Use |
|---|---|---|---|
| `agents/<name>.md` | Humans (PR reviewers, GitHub readers) | Long-form prose: role, inputs, outputs, handoff, sub-prompt template | Documentation; on-boarding new collaborators |
| `.claude/agents/<name>.md` | Claude Code Task tool | YAML frontmatter (`name`, `description`, `tools`) + concise system prompt | Native subagent invocation: `subagent_type: <name>` |

The `.claude/agents/` files are intentionally thin and refer back to
`agents/<name>.md` for full context. Edit both together so they don't drift.

**How to invoke a subagent:** ask the orchestrator (the main session) in plain
words — *"Run the Research agent on the F6 BSP questions in
`docs/bsp-selection.md`."* It spawns a Task call with `subagent_type: research`,
the subagent reads `CLAUDE.md` + `agents/research.md` + the target phase doc,
and returns a summary the orchestrator integrates.

---

## What this project does NOT do

- **No certified Type-1 isolation.** The QNX Hypervisor here is uncertified. It
  ran emulated in TCG (A1, A3) and natively at EL2 on the Orin (A4, A5). Under
  A6 there is no Type-1 layer at all: the partitioner is KVM, and Linux — the
  largest TCB on the board — owns the QNX guest's memory.
- **No ASIL-B/D safety claim.** SDP 8.0 is not QNX OS for Safety.
- **No MISRA-C compliance.**
- **No GPU virtualization or vGPU partitioning.** QNX never touches an
  accelerator on Tegra234 in any leg.
- **No certified bootloader chain** — no SecureBoot, no measured boot, no root
  of trust at any stage on any leg.
- **No real-time guarantee** across the proxy boundary. The guest is never even
  configured for real time: the monitor is pure POSIX at default priority.
- **No ISO 26262 / Automotive SPICE process artifacts** — study notes only, see
  `skills/`.

These limitations are deliberate; documenting them precisely *is* the point.

---

## NVIDIA JD mapping — internal working reference (do NOT surface in README)

> **For Claude Code sessions only.** Use the JD mapping as targeting context
> when deciding what to prioritise or how to phrase findings. The full table is
> at [docs/jd-mapping.md](docs/jd-mapping.md). It is **not** linked from
> README.md — the public face stays focused on the engineering work itself.

| JD requirement | Where addressed |
|----------------|-----------------|
| C/C++, QNX and/or Linux OS | bring-up plus the IPC proxy (C99) in `ipc-test/` |
| OS internals, multi-threading, IPC, memory mgmt | `ipc-test/`, the BSP work, the native port |
| BSP porting and device driver internals | the QNX `virt` BSP; the rebuilt `startup-qemu-virt`; the native board directory |
| Multicore / heterogeneous SoCs | six Cortex-A78AE cores brought up natively (M2); QEMU SMP guest config |
| Customer-facing AVOS/DRIVE OS support | framing: this proxy *is* the kind of software-layer customer environment an SE helps port |
| ECU bring-up, profiling, debug | boot logs, serial bring-up over J14, the GICv3/NISV root-cause |
| QNX OS for Safety (QOS) — *stand out* | honest gap: SDP ≠ QOS. See the README limitations table and `docs/architecture.md`. A `skills/qnx-safety/` note is **unwritten** — do not link it |
| Hypervisors / virtualization — *stand out* | [drive-os-comparison.md](docs/drive-os-comparison.md); the QNX Hypervisor running natively at EL2 on the board |
| Bootloaders — *stand out* | the kexec shim (M0) and the M5-F UEFI cold boot: our own EFI loader, launched from the firmware's UEFI Shell, handing the unchanged image to the same shim |
| ASPICE / ISO 26262 — *stand out* | `skills/iso-26262/` + `skills/aspice/` study notes; applied FMEA in `skills/fmea/examples/` |

---

## Working conventions

- **Test before claim**: never write "it works" without a log, a number, or a diff.
- **Honest framing**: every claim is paired with what it does NOT demonstrate.
- **Overwrite, do not annotate.** In a current-state file, delete the old
  sentence and write the new one. `docs/findings.md` and git keep the history.
  The gate enforces this for the files listed in `OVERWRITE_ONLY`.
- **One bundled PR per Phase milestone**, not many tiny PRs.
- **Commit style**: `<phase>: <imperative summary>` (e.g. `phase-0: scaffold repo and add CLAUDE.md`).
- **Secrets**: never commit `.pem`, `.env`, instance IDs, AWS keys, LAN
  addresses, MACs, SSIDs or the board hostname. Redact **at capture time**, not
  afterwards — a committed instance id once needed a history rewrite to remove.
- **Cost discipline**: terminate every AWS instance immediately after capture
  and verify nothing is `running|pending` and no volume is orphaned. Launch
  self-terminating (`--instance-initiated-shutdown-behavior terminate` plus a
  `shutdown -h` safety net). Document spend in findings.
- **Licence**: QNX SDP 8.0 and any QNX-derived binary must never enter the repo
  or CI (NCEULA). NC QDL v7 **4.6(c)**: never disassemble a QNX-shipped binary
  — work from source. **4.6(i)**: evaluation output is gated on consulting the
  supervising professor; A4/A5 figures stay on the unpushed local branch
  `m3-results-unpublished`.
- **`skills/` are study artifacts**, not certification evidence — say so
  explicitly in any doc that cites them.
- **The repo is public.** Pushing is publishing. `M0`, `M1`, `M2` and `M1b`
  records are public by owner decision; **everything from M3 onward** — M4-F,
  M5-F, the dry runs and every S1 board rung — stays on the unpushed local
  branch `m3-results-unpublished` until the 4.6(i) consultation.
- **Phrasing rule, every time KVM comes up:** the `startup-qemu-virt` that boots
  is **ours**, so it is *not a QNX-supported configuration*, and **no timing
  claim** attaches to the boot itself. A2's numbers are TCG numbers; the 2026-09-18
  KVM boot does not re-validate or re-time any of them.
- **Closing a phase never meant its target was met.** Phase 2's reliable runs
  never reached 100k iterations; Phase 3's KVM-accelerated boot never worked at
  the time and its IPC run used a *rebuilt* IFS. Neither will be redone.

### Settled — do not re-raise

- **The GICv3/NISV defect is not being filed** with QNX/BlackBerry (owner,
  2026-09-18). It was root-caused and cleared at the source instead. Kept as
  project history and interview material, not as an open action.
- **Git history will not be rewritten** to remove `docs/interview-narrative.md`
  from earlier commits (owner, 2026-09-20). The reasoning, so it is not
  re-derived: the file entered at the repo's first commit, so a rewrite changes
  all 222 SHAs and breaks 62 commit references across `docs/`. See
  `.gitignore` for the full note.
- **Cluster 1 is left out** (OD3, 2026-09-16): `-P4` goes in the manifest, **no
  explanation of the cluster-1 rate is owed**, and no `-P6` diagnostic run is
  scheduled. The frequency-grid fit in `m3-design.md` §4.3 is an un-adopted
  hypothesis, never the account.

### Board sessions — safety rules paid for in hardware

- **A hang needs a physical power cycle.** M0's hang test established that the
  CCPLEX watchdog does **not** fire after kexec. Never schedule an unattended
  board run that can hang; the owner has to be at the plug.
- **COM3 is exclusive.** One program at a time, and captures are sized per rung
  — an oversized capture once blocked the port and had to be stopped by hand.
- **Pin the CPU governor before any latency measurement** and restore it after.
  On `schedutil` the board clocks down when idle, so an unpinned idle baseline
  is measured on a slower machine than the loaded arm it is compared against.

---

## Phase status

**Phase state lives in [README.md](README.md)'s Status table.** Do not restate
it here. `scripts/ci/render_badges.py --check` keeps that table and the Phase
badge consistent on every push, and two hand-maintained copies of one fact is
exactly how the badge came to advertise a superseded architecture.

Per-phase detail is in **[docs/findings.md](docs/findings.md)** (dated,
append-only) and, for the native port,
**[docs/orin-native-port-plan.md](docs/orin-native-port-plan.md)** — which also
holds every owner decision **OD1–OD10** in full.

### What governs future work

- **A6 is the direction and is not frozen.** Its sample sizes are open. Nothing
  else about its gate is.
- **OD10 (2026-09-20): the TCG twin legs are withdrawn; A6 measures under KVM
  only.** Consequence: no QNX Hypervisor number will ever exist here.
- **Earlier architectures are history and are not re-run.** Closing a phase
  never meant its original target was met — Phase 2's reliable runs never
  reached 100k iterations, and Phase 3's KVM boot never worked at the time.
- **A4/A5 figures are unpublished** under 4.6(i) and stay on the local branch.

### Open

1. **A6 sample sizes** — the last gate item, and an owner decision. Current
   arms are n=3000 per latency arm and n=5 per boot arm.
2. **The `qvm`/TCG virtio-queue stall** (A1) was never root-caused. It is
   survivable via the sentinel frame, not fixed, and is tracked outside any
   phase.
3. **Phase 5** has not started *as a dedicated phase*, but a Phase-1-gate FuSa
   and Cyber pass did run and is committed under `docs/fusa/`, `docs/cyber/` and
   `docs/tara/` — do not describe it as untouched. **Phase 6** (polish, demo)
   has not started. **Phase 7** is frozen as feasibility in
   [docs/future-multi-soc.md](docs/future-multi-soc.md), which held it back
   until Phase 4 was delivered; Phase 4 closed on 2026-09-20, so that particular
   constraint is now released.
4. **The 4.6(i) consultation** with the supervising professor, which gates
   publishing everything from M3 onward.
