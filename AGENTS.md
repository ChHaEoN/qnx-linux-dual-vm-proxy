# AGENTS.md — qnx-linux-dual-vm-proxy

> Guidance for any Codex session working in this repo.
> Read this file first; do not assume the project's framing from filenames alone.

---

## Mission (honest framing)

This repo is a **Digital Twin design** of the NVIDIA DRIVE OS dual-VM
partition architecture, running QNX SDP 8.0 (Safety proxy) + Linux aarch64
(Compute proxy):

- **Cloud twin:** designed as QEMU/KVM on AWS Graviton (c7g.large), for fast iteration and regression sweeps. As built, it runs the QNX Hypervisor host and one QNX guest under QEMU TCG on the local Windows PC, because non-metal Graviton has no `/dev/kvm` (ADR-002). **2026-09-19:** that limit is *non-metal*, not *cloud* — on a bare-metal `a1.metal` `/dev/kvm` is present and a QNX guest boots under KVM (see the Tech stack note below). The as-built leg above is unchanged: no cloud leg has been built and nothing was timed, and the QHV host itself still cannot run under KVM anywhere (it needs EL2, which ARM KVM does not nest).
- **Hardware twin:** **Jetson Orin Nano Dev Kit** (Cortex-A78AE, same Tegra family as DRIVE Orin) — validation on real silicon. QEMU runs there under TCG, because KVM boot of an IFS carrying the SDP's ~~QNX IFS hangs~~ **shipped `startup-qemu-virt` hangs** on the GICv3/NISV defect (**2026-09-18:** an IFS carrying a `startup-qemu-virt` we rebuilt with `-fno-auto-inc-dec` does boot under KVM on this board, to procnto and the guest banner; the TCG legs were not re-run or re-timed under it, no timing was taken, it is not a QNX-supported configuration, and the QNX Hypervisor still cannot run under KVM anywhere — it needs EL2, which ARM KVM does not nest on A78AE). Since Phase 3b the QNX Hypervisor also runs natively on the board.

The design had the same QNX IFS and the same IPC client/server source run
on both sides unchanged, with only the host changing. As built, the Orin
IPC leg used a rebuilt IFS, and "host" is a bundle of CPU, OS, TCG backend
and QEMU build (`docs/digital-twin-design.md` §1a). The **twin diff**
(what changes when the host bundle changes?) is still the load-bearing
measurement. It is re-run once on ~~reference architecture v1~~ **A6**
(`docs/orin-native-port-plan.md`, freeze section). **2026-09-18:** v1 — the
native QNX Hypervisor as host — was superseded before it was ever frozen,
because no OS can use the GPU under it; A6 puts L4T on the metal with the GPU
and runs QNX as a KVM guest. A6's gate is not settled, so whether the TCG twin
legs survive is itself still open.

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
- Runtime host (design): c7g.large (Graviton3 Neoverse-V1, Ubuntu 22.04 arm64). **As built, no cloud-leg number was ever produced there** — non-metal Graviton has no `/dev/kvm` (ADR-002), so the QHV host + guest and every cloud-leg measurement run on the local Windows PC under TCG; AWS's remaining role is the `a1.metal` KVM test bed. See `docs/digital-twin-design.md` §1. **2026-09-19:** that test bed answered the question ADR-002 left open, and the qualifier matters. ADR-002's reasoning was right — its own words are "any hardware-accelerated partitioner — KVM *or* QHV — needs `*.metal` or real silicon", which predicted this result; only the flatter "KVM-on-cloud is dead" clause was stale. On a fresh bare-metal `a1.metal` (Graviton1, Cortex-A72, eu-central-1) `/dev/kvm` is present and the kernel reports "Hyp mode initialized successfully", and a QNX guest boots under `-enable-kvm` — a matched pair, one variable: control = the SDP's shipped `startup-qemu-virt` → 17 bytes, `FOUND GICv3 ITS`, hang; test = a `startup-qemu-virt` **we rebuilt** with `-fno-auto-inc-dec` → 1301 bytes, "Startup complete" + banner (`logs/sample-boot/aws-a1-metal-kvm-fix-crossvendor.log`; findings.md 2026-09-19). So the limit was always **non-metal**, never **cloud**. What has *not* changed: non-metal Graviton still has no `/dev/kvm` (the t4g.small probe stands); **no cloud leg has been built and no timing, latency or throughput number was taken** — one 60 s boot arm is not a leg; the twin diff is not re-run and A1/A2/A3 stay history; `c7g.metal` stays quota-blocked (64 vCPU vs a 32-vCPU account limit); the rebuilt startup is **ours**, so this is not a QNX-supported configuration; and the QNX Hypervisor still cannot run under KVM anywhere (EL2/nested virt).
- Honest framing: the Windows-host pivot is a **friction/cost optimisation only**. The build host runs only `mkqnximage` and host-side QNX tooling (no guests run on it) and produces a target-aarch64 IFS via cross-compilation; per F1's arch-agnostic-IFS argument, host platform (Windows vs Linux x86_64) affects only build metadata (embedded paths, timestamps), not the ARM code QNX boots, so F5 Q2 (any x86_64-built IFS boots on Graviton) is the only verification needed — there is no separate cross-host build-determinism check. The pivot is also NOT closer to a real DRIVE OS customer build environment than EC2 — DRIVE OS customer builds typically sit on rented or vendor-provided Linux hosts, not local Windows.

**Hardware twin (Orin Nano):**
- Jetson Orin Nano Dev Kit ($499) — Ampere GPU, 6× Cortex-A78AE, 8 GB RAM
- Host OS: NVIDIA L4T (JetPack 6, Ubuntu 22.04 base) — also plays the "Compute partition" role
- `/dev/kvm` is present on A78AE, and ~~KVM boot of the QNX IFS hangs on the
  GICv3/NISV defect~~ **2026-09-18: that holds for the SDP's *shipped*
  `startup-qemu-virt`, which still stops after `FOUND GICv3 ITS` (17 bytes) on
  the same host and launch line, reproduced as a control arm. An IFS carrying a
  `startup-qemu-virt` we rebuilt (`-fno-auto-inc-dec`; board source at
  `orin-native/startup/qemu-virt/`) boots under `-enable-kvm` to procnto and the
  guest banner (`logs/sample-boot/orin-kvm-*.log`). Not a QNX-supported
  configuration, no timing claim, and nothing about the QNX Hypervisor under
  KVM** (`docs/orin-port.md`); the measured legs ran under **TCG**
  on this board — for the QHV leg TCG is a hard requirement anyway (nested
  virt), and it needs QEMU ≥ 9.0 there (EL2 virtual-timer IRQ; 6.2 hangs)

**Common across both twins:**
- VM0 — Safety proxy: QNX SDP 8.0, aarch64 `virt` machine, NCEULA (Everywhere)
- VM1 — Compute proxy: Linux aarch64 — **Phase 3 / Orin only** (L4T native). Per
  [ADR-002](docs/phase2-topology-decision.md) there is **no Linux guest on the
  cloud leg** (the cloud Compute-VM premise was falsified — no `/dev/kvm`, host
  `io-sock` down; **2026-09-19:** falsified *on non-metal* — bare metal does
  expose `/dev/kvm`, and a QNX guest booted under KVM on `a1.metal`, but no
  cloud leg and no Linux guest has ever been built or run there).
- IPC (cloud leg): QNX-host (`qnx-qhv`) ↔ QNX-guest (`qnx-guest`) over the `qvm`
  `virtio-console` vdev — crosses the real EL2/EL1 partition boundary, TCG-emulated,
  **no** `br0`/tap (host `io-sock` never comes up because the launch line presents no virtio-net/-rng device — a launch-line omission per ADR-002 RQ-4, not an image property; with the devices presented it does). See [ADR-002](docs/phase2-topology-decision.md).
- IPC (Phase 3 / Orin leg): heterogeneous QNX↔Linux over host bridge `br0` + tap
  devices (`tap-qnx` / `tap-linux`) + virtio-net under TCG (~~KVM boot is blocked~~ **KVM boot was blocked when this ran; 2026-09-18: blocked for the SDP's shipped `startup-qemu-virt` only — an IFS carrying a `startup-qemu-virt` we rebuilt with `-fno-auto-inc-dec` boots under KVM on the board. This path was not re-run under it and nothing was timed**; `docs/orin-port.md`) — this bridged path
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

**2026-09-19:** the tree above is now mirrored from `CLAUDE.md`'s. What was
corrected: `scripts/` omitted `qhv/`, which is the live cloud bring-up path
this file itself names in the Phase-1 sequence below; `orin-native/`,
`results/orin-native-port/` and `results/gicv3-nisv-debug/` were missing, all
three present on disk; `logs/sample-boot/` holds curated captures from every
phase, not Phase 1 only; and the row `~~└── .github/workflows/ # CI (added in
Phase 1)~~` was removed — no `.github/` directory exists, none is in any
commit, and no CI was ever added.

Each placeholder file carries a `Phase N` tag in its header. Do not strip Phase tags.

---

## How work is delegated

Work is delegated ad hoc: the orchestrator describes a concrete task and hands
it to a subagent or a workflow, and integrates the result. There is no fixed
roster.

There used to be one — fourteen role definitions modelled on an automotive SDV
team, under `agents/` and `.claude/agents/`. It was removed from the repo on
2026-09-21 because the work did not follow it: 11 of 257 commits mention an
agent, and the delegation that actually happened was task-shaped, not
role-shaped. A document asserting an organisational structure the repo cannot
evidence is the same class of problem the claims gate exists to catch, so it was
held to the same standard as any other claim here.

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
| OS internals, multi-threading, IPC, memory mgmt | Phase 2 (`ipc-test/`), Phase 1 BSP work |
| BSP porting and device driver internals | Phase 1 (QNX virt BSP, Linux rootfs) |
| Multicore / heterogeneous SoCs | ~~Graviton3 multi-core~~ **2026-09-11:** six Cortex-A78AE cores native (M2, Phase 3b); QEMU SMP guest config |
| Customer-facing AVOS/DRIVE OS support | Framing: this proxy IS the kind of software-layer customer environment an SE helps port |
| ECU bring-up, profiling, debug | Phase 1 (boot logs, kernel debug) + Phase 2 (latency profiling) |
| QNX OS for Safety (QOS) — *stand out* | Honest gap: SDP ≠ QOS; framed as "POSIX-realtime proxy" + the README limitations table + `docs/architecture.md` (a dedicated `skills/qnx-safety/` note is still **unwritten** — do not link it) |
| Hypervisors / virtualization — *stand out* | ~~Phase 3~~ Phase 4 comparison doc: explicit gap analysis vs. real hypervisor. **2026-09-11:** also the QNX Hypervisor host, native on the Orin (Phase 3b) |
| Bootloaders — *stand out* | ~~Phase 1 (U-Boot for Linux guest, IPL for QNX)~~ **2026-09-11:** no leg has run U-Boot or a Linux guest. The bootloader work is the kexec shim (M0) and ~~the planned M5-F UEFI cold boot~~ **2026-09-13:** the M5-F UEFI cold boot, which ran and passed: our own EFI loader, launched from the firmware's UEFI Shell, hands the unchanged M1b image to the same shim (Phase 3b) |
| ASPICE / ISO 26262 — *stand out* | `skills/iso-26262/` + `skills/aspice/` study notes; applied FMEA in `skills/fmea/examples/` |

---

## Working conventions

- **Test before claim**: never write "it works" without a log, a number, or a diff.
- **Honest framing**: every claim is paired with what it does NOT demonstrate.
- **One bundled PR per Phase milestone**, not many tiny PRs.
- **Commit style**: `<phase>: <imperative summary>` (e.g. `phase-0: scaffold repo and add AGENTS.md`).
- **Secrets**: never commit `.pem`, `.env`, instance IDs, AWS keys. Loaded from `.env` (gitignored).
- **Cost discipline**: run ~~`scripts/ec2/teardown.sh`~~ **(2026-09-11: that script is in no commit of this repo; the one AWS run since, the `a1.metal` repro, terminated its instance right after capture)** after every session; document spend in findings docs.
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
  guest on the cloud leg**. **2026-09-19:** the `/dev/kvm` half still holds
  for *non-metal*; `a1.metal` does expose it and booted a plain QNX guest
  under KVM. That is not this leg — the QHV host needs EL2 and still cannot
  run under KVM anywhere, no cloud leg was built, and nothing was timed.
- Phase 2 — Cloud twin IPC + latency — **~~partial,~~ real numbers,
  honestly capped; 2026-09-13 (owner): closed as A1 history, target not
  met**: measured P50/P99/Max in
  `results/cloud/cloud-ipc-latest.csv`. A non-deterministic `qvm`/TCG
  virtio-queue stall is still **not root-caused**; it is now
  *survivable* via a kick-safe sentinel frame (19/19 real stalls
  recovered across 4 boots). ADR-002's RQ-2 `vdev shmem` transport is
  separately resolved **yes**, host to guest and back. Reliable runs
  never reached the 100k-iteration target; the phase will not be redone.
  The `qvm`/TCG virtio-queue stall stays open and is still not
  root-caused, but is no longer tracked under this phase.
- Phase 3 — Hardware twin (Jetson Orin Nano) — **~~substantial, not
  closed~~ 2026-09-13 (owner): closed as A2 history, target not met**:
  heterogeneous QNX to Linux IPC over a real `br0`/`tap-qnx`
  bridge works — two clean 100,000-iteration runs, zero errors
  (`results/hw/orin-ipc-latest.csv`). **KVM boot ~~is~~ was blocked** (**2026-09-18:** for the SDP's shipped `startup-qemu-virt` it still is — it dies after `FOUND GICv3 ITS` on the same launch line — but an IFS carrying a `startup-qemu-virt` we rebuilt with `-fno-auto-inc-dec`, from board source written at `orin-native/startup/qemu-virt/`, boots under `-enable-kvm`. This phase's runs were not re-run or re-timed under KVM, and it is not a QNX-supported configuration) by a
  root-caused GICv3 / `KVM_EXIT_ARM_NISV` defect, since reproduced on
  AWS `a1.metal` (a second ARM vendor), so TCG is the interim
  transport. Honest caveat: that IPC run used a **rebuilt** IFS, not
  the byte-identical Phase-1 image. KVM-accelerated boot never worked for
  this phase and the IPC run used a rebuilt IFS; the phase will not be
  redone.
- Phase 3b — Native QNX on the Orin Nano (ADR-003 option B) — **M0, M1,
  M2, M1b and M3 met**; **2026-09-11 / 09-13 / 09-17: M4-F, M5-F and
  S1-F (QNX plus Linux) met as well — rungs of the native-hypervisor
  ladder, met and staying met *for A4/A5*, and not evidence about A6**.
  Entered by kexec from L4T, with no QEMU, the QNX
  Hypervisor host runs at EL2 and booted the cloud-leg QNX guest (M3,
  2026-09-10). M3's figures stay on the local branch
  `m3-results-unpublished` until the 4.6(i) consultation. **Decision
  2026-09-11 (owner, option B):** M4-F, then M5-F, then S1-F (a Linux
  guest without a GPU under native qvm), then ~~freeze reference
  architecture v1, then one measurement campaign~~ **2026-09-18: settle
  A6's gate, then one campaign on A6 — v1 was superseded before it was
  ever frozen, and A6's gate is not settled**. Earlier measurements
  are architecture-version history. See `docs/orin-native-port-plan.md`.
- Phase 4 — Twin diff + DRIVE OS comparison — **started**: boot-time
  twin diff done on the plain leg (n=5 per side; Orin +23–25% slower
  than Windows; now A2 history). A second leg on the *hypervisor*
  topology (QHV host + guest, same images on both hosts) boots on the
  Orin under a from-source QEMU 11.1.0 (the distro 6.2.0 hangs on an
  EL2/VHE timer defect — QEMU-side, not host). The release-aligned pair
  ran on 2026-09-09 and is now A3 history; the twin diff is re-run in
  the ~~v1~~ **A6** campaign (**2026-09-18:** v1 was superseded before it
  was ever frozen; A6's gate is not settled) — see CLAUDE.md Phase 4 and
  `docs/digital-twin-design.md` §1a. `docs/drive-os-comparison.md`'s
  verdicts wait for that campaign.
- Phase 5 — FuSa & Cybersecurity overlay — not started as a dedicated
  phase (a Phase-1-gate FuSa + Cyber pass did run).
- Phase 6 — Polish, public README, demo recording — not started.
- Phase 7 (stretch) — Domain-controller extension, two tracks frozen in
  `docs/future-multi-soc.md`: the original multi-SoC idea (a
  Qualcomm-Cockpit-class proxy alongside the NVIDIA one) and a newer
  NVIDIA-primary single-SoC convergence track.

Next actions: `CLAUDE.md`'s Phase status section carries what is open
(2026-09-20: it no longer holds a long "Next actions" list — phase state lives
in `README.md`'s Status table, and dated detail in `docs/findings.md`). Since the 2026-09-11 owner decision the Phase 3b order
leads: M4-F, M5-F, S1-F, ~~freeze reference architecture v1, then one
measurement campaign~~ **2026-09-18: settle A6's gate, then one campaign on A6**
(`docs/orin-native-port-plan.md`, freeze section). M4-F, M5-F and S1-F are met
and stay met **for A4/A5**; they are rungs of the native-hypervisor ladder and
are not evidence about A6.
