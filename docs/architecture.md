# Architecture

This document explains the Digital Twin layout, the build/runtime split
on the cloud side, the host-OS split on the hardware side, and exactly
what the IPC path looks like inside each twin.

The twin design is described in detail in
[digital-twin-design.md](digital-twin-design.md); this file covers
the *structural* picture that designs sits on top of.

**Current state (2026-09-13).** The ids below are the rows of the plan's
[architecture table](orin-native-port-plan.md#architecture-versions).
- **History, closed (2026-09-13, owner):** A1, the cloud leg (the QNX
  Hypervisor in QEMU TCG on the Windows PC), and A2, the Orin plain leg (QNX
  in QEMU TCG beside L4T, IPC over `br0`/tap). Neither is redone. Closed does
  not mean target met: A1's reliable runs never reached the 100k-iteration
  target, KVM-accelerated boot on the Orin never worked, and A2's IPC run
  used a rebuilt IFS. Two items stay open outside those phases: the
  `qvm`/TCG stall on A1 is still not root-caused, and the GICv3/NISV KVM
  defect is ~~a separate filing track~~ **(2026-09-18: decided against — the
  owner decided not to report it to QNX/BlackBerry ([findings.md](findings.md)),
  so this is no longer an open action and only the stall above remains open. The
  defect is root-caused: an IFS carrying a `startup-qemu-virt` we rebuilt with
  `-fno-auto-inc-dec` boots under KVM on the Orin, while the shipped binary still
  hangs — not a QNX-supported configuration, no timing claim. Kept as a record.)**
- **History since the 2026-09-11 freeze decision:** A3, the same hypervisor
  images in TCG on both hosts. Its twin legs run again only as v1 campaign
  work. **2026-09-19:** A3 did use TCG on both hosts, and that record stands —
  but it was never a universal limit. On the Windows PC (x86_64) TCG is a
  necessity for an ARM guest, not a defect; on ARM hosts a QNX guest has since
  booted under KVM, on the Orin (2026-09-18) and on a bare-metal AWS `a1.metal`
  (2026-09-19). Neither is a built or measured cloud leg, and no timing was
  taken on either.
- **Current:** A4, the QNX Hypervisor native on the Orin Nano, with no QEMU.
  The same shim has two entry paths. kexec from L4T carried the shim alone in
  M0 and every host image in M1-M4. Once, attended, our own EFI loader,
  launched by hand from the firmware's UEFI Shell, carried only the one-core
  M1b image, with no `qvm` and no guest (M5-F). No `qvm` host image has been
  entered through UEFI. The M path has ended.
- **Next:** ~~S1, the first stage of A5: a Linux guest without a GPU under
  native `qvm`. Then the freeze of reference architecture v1, and one
  measurement campaign on it. v1's two TCG twin legs are campaign work on
  v1, not a reopening of A1-A3.~~ **2026-09-18: settle A6's gate, then one
  campaign on A6.** QNX now boots under KVM, so the architecture is L4T on the
  metal owning the GPU with QNX as a hardware-virtualised guest beside it. v1
  (A4's native QNX Hypervisor host plus S1's Linux guest) is superseded before it
  was ever frozen, for one reason: under v1 no OS can use the GPU — Tegra234's
  iGPU has no SMMU stream and its clock/reset/power go through BPMP, for which
  QNX has no client. A4, A5 and S1 stay valid as their own architectures and are
  not re-run. A6 is the current direction, not a frozen reference architecture.

The cloud-twin and hardware-twin sections below describe A1 and A2 as built.
The Phase 3b section describes A4 and ~~the planned v1~~ **v1 as it was planned
(2026-09-18: superseded by A6 before it was ever frozen; kept as the record of
what v1 was)**.

---

## DRIVE OS reference architecture (the thing being proxied)

DRIVE OS partitions a single Tegra-class SoC across two guests using
NVIDIA's Type-1 hypervisor:

```
NVIDIA DRIVE OS (real hardware: Orin / Thor SoC)
├── NVIDIA Hypervisor (Type-1)          ← partition isolation
│   ├── Safety guest:   QNX OS for Safety (QOS)   ← ASIL-D path
│   │   └── Safety services (FuSa monitors, Cortex-R52 FSI bridge)
│   └── Compute guest:  Linux            ← AVOS / DriveWorks stack
│       └── CUDA, NVDLA, PVA, MIPI camera ingest, vGPU
└── Inter-VM IPC: hypervisor-mediated shared memory + mailbox interrupts
```

What makes that real: a certified Type-1 partitioner enforces
mixed-criticality isolation; the hardware provides FSI lockstep and
camera ingest; the IPC path is shared memory, not a network.

---

## Cloud twin — hybrid build/runtime

**2026-09-13 (owner):** this section describes A1 as built. A1 is closed as
architecture history and will not be redone.

QNX SDP 8.0 does not have an arm64 host toolchain. The build-side
tools (`mkqnximage`, `qcc`, the QNX Software Center) only run on
**x86_64 Linux native** or **Windows native** — no macOS, no arm64
Linux. The runtime side wants arm64 so the `mkqnximage
--arch=aarch64le` IFS executes on the target architecture and the
project narrative stays on-target (Orin / Thor are arm64). Reconciling
those two constraints forces the cloud twin's toolchain across two
hosts: an x86_64 builder and an arm64 runtime.

> **Note (per [ADR-002](phase2-topology-decision.md)):** the cloud
> runtime originally assumed KVM-on-arm64 hardware virtualization, but
> AWS non-metal Graviton exposes **no `/dev/kvm`** — so the cloud leg
> runs under QEMU **TCG** emulation, hosting the SDP 8.0 QHV (`qvm`)
> and a single QNX guest. KVM acceleration was moved to Phase 3 (Orin), but
> ~~KVM boot there is blocked by the GICv3/NISV defect
> ([orin-port.md](orin-port.md) risk register), so that leg runs TCG too.~~
> **2026-09-18:** that leg ran TCG, and KVM boot there is still blocked for the
> SDP's **shipped** `startup-qemu-virt`, which dies 17 bytes in after
> `FOUND GICv3 ITS` (control arm, same host and session). An IFS carrying a
> `startup-qemu-virt` **we rebuilt** from board source written that day
> (`orin-native/startup/qemu-virt/`, startup library compiled
> `-fno-auto-inc-dec`) boots under `-enable-kvm` to procnto and the guest banner
> ([logs/sample-boot/orin-kvm-*.log](../logs/sample-boot/)). Not a QNX-supported
> configuration — QNX ships no such binary — and no timing claim. QHV under KVM
> is unaffected: it needs EL2/nested virt, which ARM KVM lacks on A78AE.
>
> **2026-09-19 — the limit was always "non-metal", never "cloud".** ADR-002 §1
> already said so: *"Any hardware-accelerated partitioner — KVM or QHV — needs
> `*.metal` or real silicon."* The stale part is only the flatter clause beside
> it, "KVM-on-cloud is dead", as repeated downstream without the qualifier. On a
> bare-metal AWS `a1.metal` (Graviton1, Cortex-A72) `/dev/kvm` **is** present, and
> a matched pair ran there, one variable — which IFS boots: the SDP's **shipped**
> `startup-qemu-virt` hung after `FOUND GICv3 ITS` (17 bytes of serial), while an
> IFS carrying the startup **we rebuilt** (`-fno-auto-inc-dec`) reached `Startup
> complete` and the guest banner under `-enable-kvm` (1301 bytes). Capture:
> [aws-a1-metal-kvm-fix-crossvendor.log](../logs/sample-boot/aws-a1-metal-kvm-fix-crossvendor.log);
> [findings.md](findings.md) 2026-09-19. **What it does not change:** non-metal
> Graviton still has no `/dev/kvm` (the t4g.small probe stands), so the paragraph
> above holds as written for the `c7g.large` this leg was designed on; **no cloud
> leg has been built or measured** — one 60 s boot arm is not a leg, and no timing
> of any kind was taken; the cloud leg as built ran on the Windows PC under TCG,
> and A1-A3 are not re-run or re-timed. `c7g.metal`, the closer match, stays
> quota-blocked (64 vCPU against a 32-vCPU account limit). The rebuilt startup is
> **ours** — QNX ships no such binary — so this is not a supported configuration.
> QHV is unaffected either way, for the EL2/nested-virt reason just above.

Per the 2026-05-07 amendment in [findings.md](findings.md), the
primary build host is a **local Windows PC** (the same machine that
serves as the dev driver). The EC2 t3.medium x86_64 Ubuntu instance
is retained as an **explicit fallback** for users without a local
x86_64 Windows or Linux box. The runtime host was designed to stay on
Graviton. As built, the QHV host and its guest run under TCG on the same
Windows PC, and no cloud-leg number came from Graviton
([digital-twin-design.md](digital-twin-design.md) §1).

> **As-built per [ADR-002](phase2-topology-decision.md) (Accepted).** The
> cloud runtime is **not** two co-equal KVM guests over a Linux bridge —
> that topology is falsified (no `/dev/kvm` on ~~cloud Graviton~~
> **non-metal Graviton — 2026-09-19: the limit is non-metal, not cloud; see
> the note above**; no Linux
> guest; host `io-sock` down). The cloud leg is the SDP 8.0 **QHV** host
> `qvm` running a **single QNX guest** under `qemu-system-aarch64 -accel
> tcg` (TCG, **not** KVM), with **no** `br0`/tap. The Linux Compute side
> moved to **Phase 3 / Orin**.

```
┌──────────────────────────────┐         ┌─────────────────────────────────┐
│ Build Host (PRIMARY)         │  scp    │ Runtime (as built: this PC)     │
│ Local Windows PC (x86_64)    │────────▶│ design: Graviton c7g.large      │
│ • QNX SDP 8.0 Windows native │  ifs    │                                 │
│ • mkqnximage --type=qemu     │         │ • qemu-system-aarch64 -accel tcg│
│   --qvm=yes  (QHV host+guest)│         │   (no /dev/kvm: non-metal)      │
│ • produces output\ifs.bin    │         │ • qvm  (QHV host, EL2)          │
│                              │         │ • NO br0/tap (io-sock down)     │
│ Build Host (FALLBACK)        │         │                                 │
│ t3.medium x86_64 Ubuntu EC2  │ ──scp──▶│ ┌─────────────────────────────┐ │
│ • same QNX SDP 8.0 install   │  ifs    │ │ qnx-qhv HOST (EL2)          │ │
│ • same mkqnximage invocation │         │ │  └─ qvm @g2.conf            │ │
└──────────────────────────────┘         │ │      ┌──────────────────┐   │ │
                                         │ │      │ qnx-guest (EL1)  │   │ │
        Linux Compute guest ── moved ──▶ │ │      │ console/blk vdevs│   │ │
        to Phase 3 / Orin (L4T native)   │ │      └──────────────────┘   │ │
                                         │ └─────────────────────────────┘ │
                                         └─────────────────────────────────┘
```

Build host (primary): a developer-class Windows PC. SDP install,
IFS build, and `scp` to the runtime host all run locally; no EC2
build-host hours billed.

Build host (fallback): `t3.medium` (2 vCPU, 4 GB) is enough headroom
for SDP install + IFS build; t3 charges by the hour and can be
stopped between builds.

Runtime host (design): `c7g.large` (2 vCPU Graviton3, 4 GB). Per
[ADR-002](phase2-topology-decision.md), there is **no `/dev/kvm`** on
non-metal Graviton, so the QHV host + single QNX guest run under QEMU
**TCG**. As built they run on the local Windows PC, not on this instance,
so the diagram's `scp` hop to a runtime host does not occur. The Linux
Compute guest moved to Phase 3 / Orin.

**Honest framing:** the Windows-primary pivot removes ssh / X11 /
browser-flow friction and EC2 build-host cost — but it does **not**
demonstrate cross-host build determinism. A Phase-1 check that a
Windows-built IFS matches an EC2-built one was proposed, then withdrawn
on 2026-05-07 as over-specified: the build host changes only build
metadata, not the aarch64 code QNX boots ([findings.md](findings.md),
2026-05-07 amendment; [bsp-selection.md](bsp-selection.md), F5 note).
The EC2 host stays a fallback, not a canonical reference.
And the local Windows host is **not** closer to a real DRIVE OS
customer build environment than EC2 is — production AVOS / DRIVE OS
customer builds run on rented / vendor-provided Linux farms, not
local Windows. The pivot is a friction/cost win, not an
architectural improvement.

---

## Hardware twin — Jetson Orin Nano Dev Kit

**2026-09-13 (owner):** this section describes A2 as built. A2 is closed as
architecture history and will not be redone; the Orin's current leg is the
native one (next section).

The hardware-twin host is a single Jetson Orin Nano Dev Kit
(Cortex-A78AE × 6, Ampere GPU, 8 GB RAM, NVIDIA L4T / JetPack 6).
There is no separate build host: the QNX IFS produced on the cloud
twin's x86_64 build host is **scp'd directly to the Orin Nano** and
booted under QEMU on the A78AE cores.

```
                 Build host (cloud twin) ─── scp (output/ifs.bin) ──┐
                                                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Jetson Orin Nano Dev Kit  (NVIDIA L4T / JetPack 6, TCG; KVM blocked)    │
│                                                                          │
│   L4T (Ubuntu 22.04 base) is BOTH the host OS AND the Compute side       │
│   of the dual-VM pair. QNX runs in QEMU as the Safety side.              │
│                                                                          │
│   ┌────────────────────────┐         ┌───────────────────────────────┐   │
│   │  QNX VM (in QEMU)      │         │  L4T (host, Compute role)     │   │
│   │  rebuilt IFS (TCP srv) │         │  native userspace; ipc-test/  │   │
│   │  ┌──────────────────┐  │         │  linux-client built natively  │   │
│   │  │ qnx-server-net   │  │ virtio  │                               │   │
│   │  │ (TCP listen)     │◄─┼─net────►│  tcp connect to qnx-server-net│   │
│   │  └──────────────────┘  │         │                               │   │
│   └─────────────┬──────────┘         └───────────────────────────────┘   │
│                 │ tap-qnx                                                │
│                 ▼                                                         │
│            host bridge br0                                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key structural difference vs the cloud twin:** the Linux side does
not run inside its own QEMU VM on the hardware twin — L4T is already
the host, so there is no point virtualising another Linux. This is
slightly closer to DRIVE OS reality (Linux runs on Tegra natively;
QNX is the partitioned guest), but is **still not** Type-1: the QNX
guest is hosted by QEMU TCG on L4T (~~KVM boot is blocked; see
[orin-port.md](orin-port.md)~~ **2026-09-18:** KVM boot was blocked, and still is
for the SDP's **shipped** `startup-qemu-virt`; an IFS with a startup **we
rebuilt** (`-fno-auto-inc-dec`) boots under KVM on this board
([logs/sample-boot/orin-kvm-*.log](../logs/sample-boot/)) — not QNX-supported, no
timing claim), which is host-mediated either way. The IPC run used an
IFS rebuilt to stage the TCP server ([orin-port.md](orin-port.md) step 4).

~~**Why this is the right way to use 8 GB:**~~ **2026-09-13: why A2 used the
8 GB this way:** running L4T (≈3 GB) +
QEMU(QNX, 1 GB) leaves ~4 GB headroom for the userspace
benchmark + system overhead. Putting Linux in its own QEMU VM as
well would burn 2 GB extra ~~for no architectural benefit, and would
make the twin diff harder to interpret (it would no longer be
isolating "what changes when only the host changes?")~~.
**2026-09-13:** that was A2's rationale, not the current design. The owner's
target does put Linux in its own guest, under native `qvm` (S1, planned). A
twin diff also never isolated only the host: "host" is a bundle of CPU, OS,
TCG backend and QEMU build ([digital-twin-design.md](digital-twin-design.md)
§1a).

The Orin Nano L4T host ~~is~~ was (**2026-09-13:** on A2) also responsible for **bridge + tap**
provisioning (`scripts/orin/setup-bridge-orin.sh`, an Orin variant of
`setup-bridge.sh`; the cloud script is not used on the as-built cloud leg).

---

## Hardware twin, native — QNX Hypervisor on the Orin Nano (Phase 3b)

*Added 2026-09-11.* The section above ~~runs~~ ran (**2026-09-13:** A2, history) QNX under QEMU on L4T. Phase 3b
runs it on the board with no QEMU at all. The plan's architecture table
calls this **A4**
([orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions)).

```
Jetson Orin Nano Dev Kit, native (A4, as run in M3)
L4T hands over by kexec, then is gone while QNX runs
└── QNX Hypervisor host: procnto at EL2 (VHE), this port's own board startup
    ├── host process: IPC client
    └── qvm
        └── QNX guest: the cloud leg's guest image and disk
            (IPC over the qvm virtio-console vdev)
```

The host image is entered two ways. Both end in the same shim and the same
startup:

```
Entry into the A4 host image, two ways
├── kexec from a running L4T (M0-M4): M0's shim, then every host image through M4
│   └── kexec_file_load, then kexec hands over
│       └── our shim, entered at EL2 → startup → procnto
└── the firmware's UEFI Shell, by hand (M5-F: attended, one session)
    └── cold boot → Boot Manager → UEFI Shell → M5LOAD.EFI (our loader)
        └── copies the payload, exits boot services, branches
            └── the same shim, entered at EL2 → startup → procnto
                (only the unchanged one-core M1b host image: no qvm, no guest)
```

- **What changes against the QEMU twins:** the hypervisor runs on silicon.
  Stage-2 translation, the virtual GIC and the guest timers run on the real
  A78AE, not inside an emulator ([findings.md](findings.md) 2026-09-10).
- **What the UEFI entry does not show** ([m5-design.md](../results/orin-native-port/20260909T1100Z/m5-design.md) §14.7):
  no `qvm` or guest ran under it; no timing, and no comparison with kexec
  entry; one `go` in one session, so no repeatability; not unattended, since
  an operator opened the Shell; not a supported or certified boot; and no
  evidence that the firmware leaves cleaner state than kexec does.
- **What it does not have:** L4T, ~~so no Linux Compute side;~~ no GPU; no
  certified isolation. **2026-09-13:** L4T is gone only while QNX runs. ~~There
  is no Linux side yet: S1's Linux guest is next and has not run.~~
  **2026-09-17: S1-F is met (QNX plus Linux) — the Linux guest booted and held
  for ten minutes under native qvm on the board (B3, B4), and B5 ran it beside
  the QNX guest. 2026-09-18: a rung of A4/A5, not evidence about A6.** No
  unattended or supported boot: kexec needs a running L4T, and the UEFI entry
  needs an operator at the firmware menus. No published timing: its
  measurements wait for the v1 campaign.
- **Status:** M0, M1, M2, M1b and M3 are met. **2026-09-13:** M4-F (met
  2026-09-11: the trace instrument works on the board, with the caveats in
  [m4-design.md](../results/orin-native-port/20260909T1100Z/m4-design.md)
  §14.8-14.9) and M5-F (met 2026-09-13) are met too, so the M path has ended.
  Under the owner's freeze decision its measurements run in the v1 campaign.
  ~~M3's figures are A4 history and stay~~ Figures from M3 on are A4 history
  and stay unpublished, on the local branch `m3-results-unpublished` or in
  git-ignored run records.

**~~Target: reference architecture v1 (not frozen).~~ Superseded 2026-09-18 by
A6; kept here as the record of what v1 was.** A4's native host plus a
Linux guest without a GPU under `qvm` (S1), plus two TCG twin legs that boot
v1's guests in a QHV host image under QEMU. Whether the QNX guest stays beside
the Linux guest is settled at the freeze. GPU pass-through is a later stage,
still research only. Details: the plan's architecture table and freeze gate.

**2026-09-13:** the detail below expands that target. Every item in it is
planned: v1's manifest is not written, and nothing in it has run as a whole.

```
Reference architecture v1, native leg on the Orin Nano (PLANNED)
entry path: kexec, UEFI, or both (settled at the freeze)
└── QNX Hypervisor host: procnto at EL2 (A4's host)
    ├── host RAM: first window at 0x80000000 (992 MiB default in M1-M5; set at the freeze)
    │   plus a second add_ram window, candidate 0x100000000-0x249ffffff
    │   (HYPOTHESIS, K5; no QNX boot with it yet)
    └── qvm
        ├── Linux guest, no GPU (S1): L4T kernel + busybox initrd, console on hvc0
        ├── QNX guest (the cloud leg's): kept or dropped at the freeze
        └── GPU pass-through: a later stage, research only, not in v1

TCG twin legs (PLANNED): a QHV host image carrying v1's guest set, in QEMU
├── on the Windows PC
└── on the Orin, beside L4T
    (one QEMU release on both, each build recorded, v1's device set, -snapshot)
```

- **Host:** A4's native host at EL2 with `qvm`. The core split and each
  guest's pinning are settled at the freeze, including whether the two
  cluster-1 cores are explained or left out.
- **Linux guest (S1):** a stock L4T R36.4.7 kernel `Image` with a small
  busybox initrd, its console on virtio-console. S1-F boots it under the TCG
  QHV host first, after a `qvm` `dryrun` gate, then natively. Not run yet.
- **Second RAM window:** checklist 11c (2026-09-13) found that the `rmmod`
  quiesce frees no RAM window, because the map is fixed at boot. The range
  above held no reservation on any of three boots. That no firmware or BPMP
  user of it exists is still a HYPOTHESIS (K5), and booting the host image
  with it as a second `add_ram` is still owed. A GPU range stays out of every
  `add_ram`.
- **QNX guest:** kept beside the Linux guest or dropped, settled at the
  freeze. The owner's stated target has no QNX guest: the safety functions
  run as QNX processes in the host.
- **GPU pass-through:** a later stage of the research track, outside the
  plan and research only. S1 has no GPU.
- **TCG twin legs:** the same guest set in a QHV host image under QEMU TCG,
  on both hosts. They compare two host bundles, not one variable, and their
  results are labelled emulated time.
- **Then one campaign on v1,** every record stamped `arch=v1;manifest=<sha>`.
  Details: the plan's [architecture table](orin-native-port-plan.md#architecture-versions),
  S1-F block and freeze gate.

---

## Why two hosts (cloud-side)?

**2026-09-13 (owner):** this is A1's design reasoning. A1 is closed as
architecture history and will not be redone; as built, its runtime was the
Windows PC itself. The build-side half still holds: A4's images are also
built on the Windows PC and run on the Orin.

**Constraint 1 — `mkqnximage` is x86_64-only.** The QNX SDP 8.0
host toolchain exists only for x86_64 Linux native and x86_64
Windows native (no macOS, no arm64 Linux). Running it under
qemu-user emulation on an arm64 host is unsupported and not worth
the headache.

**Constraint 2 — runtime should be arm64.** The portfolio narrative is
BSP / customer-port engineering on arm64 silicon (Orin, Thor). An
x86_64-only run would be architecturally off-target. Note (per
[ADR-002](phase2-topology-decision.md)): the cloud runtime *wanted* KVM
too, but non-metal Graviton has no `/dev/kvm`, so the cloud leg ~~runs~~
ran (**2026-09-13:** A1, history) under TCG. (**2026-09-19:** that still holds
for non-metal, which is what this leg was designed on; bare-metal AWS does
expose `/dev/kvm`, and a QNX guest booted under KVM on `a1.metal` — but no
cloud leg was built there and nothing was timed. See the cloud-twin note above.) ~~KVM boot on the Phase-3 Orin twin is blocked too (GICv3/NISV;
[orin-port.md](orin-port.md)), so that leg also~~ **2026-09-18:** KVM boot on the Phase-3 Orin twin was blocked too (GICv3/NISV; [orin-port.md](orin-port.md)), and still is for the SDP's **shipped** `startup-qemu-virt`; an IFS with a `startup-qemu-virt` **we rebuilt** (`-fno-auto-inc-dec`) boots under KVM on that board ([logs/sample-boot/orin-kvm-*.log](../logs/sample-boot/)) — not a QNX-supported configuration, no timing claim. That leg also ~~runs~~ ran (**2026-09-13:** A2, history) TCG. The arm64-on-target
argument still holds (the IFS is aarch64 either way).

**The IFS is arch-agnostic from the build host's perspective.**
`mkqnximage --arch=aarch64le` produces a bootable image whose
internal target architecture is aarch64; the build host's CPU does
not have to match. So x86_64-build → scp → arm64-run is sound.

**The forced toolchain split is itself part of the engineering
narrative.** Discovering "the target architecture's host toolchain
isn't shipped for the host we want" — and routing around it — is
exactly the day-to-day shape of customer-port BSP work.

---

## IPC path detail (cloud leg)

**2026-09-13 (owner):** this section describes A1's IPC path as built. A1 is
closed as architecture history and will not be redone. The same path shape
(host client, `qvm` virtio-console vdev, guest server) later ran natively on
the Orin in M3 (A4).

Per [ADR-002](phase2-topology-decision.md), the cloud-leg IPC path is
**not** a Linux-bridge / virtio-net path between two guests — that
design is falsified. The cloud leg crosses the `qvm` partition boundary
between the QNX *host* and the single QNX *guest*, over the
`virtio-console` vdev already declared in ~~the live~~ A1's (**2026-09-13:** history) `g2.conf`.

```
┌─────────────────────────────────┐        ┌──────────────────────────────┐
│ qnx-qhv  (QHV host, EL2)        │        │ qnx-guest  (EL1 guest)       │
│ ┌─────────────────────────────┐ │        │ ┌──────────────────────────┐ │
│ │ qnx-host-client             │ │        │ │ qnx-server               │ │
│ │ (console initiator + RTT)   │ │        │ │ (console echo endpoint)  │ │
│ └──────────────┬──────────────┘ │        │ └─────────────┬────────────┘ │
│                │ console fd      │        │              │ console fd    │
└────────────────┼────────────────┘        └──────────────┼───────────────┘
                 │       qvm virtio-console vdev           │
                 └─────────── (EL2 ↔ EL1 boundary) ────────┘
```

**Path summary:** host userspace → host console fd → `qvm` virtio-console
vdev (the EL2/EL1 partition boundary) → guest console fd → guest
userspace, and back. This crosses the **real `qvm` Type-1 partition
boundary**, not a host network. It does **not** route through host
`io-sock`, a Linux bridge, or tap devices — all of which are dead on
this leg (no working host network stack; `io-sock` down).

**Honest framing:** this demonstrates IPC across a real EL2↔EL1 `qvm`
boundary, but the cloud leg is **TCG-emulated**, so the latency it
yields is dominated by TCG emulation cost — it does **not** measure
hardware-timed hypervisor IPC. ~~Hardware-timed numbers come from the
native QNX Hypervisor on the Orin (Phase 3b, section above), in the v1
campaign;~~ **2026-09-18: A6 removes the hypervisor from that sentence.** Under
A6 there is no QNX Hypervisor: QNX is a KVM guest of L4T, so any hardware-timed
IPC number would cross a KVM boundary, not an EL2/EL1 `qvm` one — a different
thing, and not a substitute for it. **No such number has been measured**; the
2026-09-18 KVM work is functional only and took no timing at all. The QNX
Hypervisor still cannot run under KVM (it needs EL2, which ARM KVM does not nest
on A78AE), so a hardware-timed *hypervisor* number would still require the
native A4 arrangement; the Phase-3 Orin twin under QEMU ~~runs~~ ran (**2026-09-13:** A2, history) TCG as well. The
heterogeneous QNX↔Linux IPC (the bridged virtio-net path with `tap`/`br0`)
~~is committed to **Phase 3 / Orin**, where it runs natively against L4T~~
ran on **Phase 3 / Orin** against a native L4T client —
see that twin's section above. **2026-09-13:** that path is A2 history
too. v1 has no `br0`/tap path: its planned Linux guest runs under `qvm`,
and neither S1-F nor the planned campaign includes a QNX↔Linux IPC run.

---

## What this is NOT (per twin side)

**2026-09-13 (owner):** the A1 and A2 columns are architecture history,
closed and not redone. The native column is A4 as run, with v1's changes
marked planned.

| Aspect | Real DRIVE OS | Cloud twin, A1 (history; designed on AWS Graviton; as built on a Windows PC) | HW twin, A2 (history; Jetson Orin Nano, QEMU on L4T) | Native, A4 as run (v1 planned) |
|---|---|---|---|---|
| Partitioner | Type-1 NVIDIA Hypervisor | SDP 8.0 QHV (`qvm`) hosting one QNX guest under QEMU **TCG** (no KVM on the ~~cloud~~ **non-metal cloud** host; see [ADR-002](phase2-topology-decision.md). **2026-09-19:** bare-metal AWS does expose `/dev/kvm`, and a QNX guest booted under KVM on `a1.metal` — but no cloud leg was built there and no timing was taken) | QEMU TCG on L4T (KVM boot blocked) running QNX alongside native L4T workload | QNX Hypervisor host (procnto at EL2, `qvm`) on the A78AE, no QEMU; uncertified SDP 8.0, not QNX OS for Safety. v1 (planned) adds a Linux guest |
| Shared SoC | Yes (Tegra Orin / Thor) | No — pure-virt, no shared peripherals | **Same Tegra family** (A78AE, Ampere) but Jetson SKU; no DRIVE-class FuSa peripherals | The Jetson SKU itself, with L4T gone while QNX runs; no DRIVE-class FuSa peripherals |
| Inter-VM IPC | Shared memory + mailbox | host↔guest over `qvm` virtio-console vdev (TCG-emulated EL2 partition boundary; not hardware-timed) | virtio-net through host bridge (Phase 3; heterogeneous QNX↔Linux) | host↔QNX guest over the `qvm` virtio-console vdev on silicon (M3: completion only, figures unpublished); no shared-memory path shown on this leg; no QNX↔Linux IPC run, and none planned in S1-F |
| VM-aware scheduling | Yes (partition scheduler) | No — the host OS scheduler schedules everything | No — L4T CFS schedules QEMU thread alongside L4T processes | `qvm` vCPUs run as host threads under procnto; no partition scheduling shown |
| Real-time | Certified RT path on Safety guest | Best-effort; jitter from host scheduler is observable | Best-effort; A78AE does have hardware RT support but L4T host doesn't expose certified RT | No real-time property measured or claimed; timing waits for the v1 campaign; the two cluster-1 cores run at a fixed low rate, cause open |
| FSI lockstep | Cortex-R52 lockstep cluster | None | None — Jetson SKU has no FSI exposed to user software | None |
| Camera / NVDLA / GPU | Real, vGPU-partitioned | None — the emulated `virt` machine has no NVIDIA accelerators | Real Ampere GPU is present but **out of scope** for this project; not exposed to QNX guest | None; QNX drives no accelerator. v1's Linux guest (planned) has no GPU; pass-through is a later stage, research only |
| Bootloader chain | SecureBoot + measured boot, certified | None | None — JetPack provides UEFI but no chain-of-trust beyond default | None. Entered by kexec from a running L4T (the shim alone in M0, host images in M1-M4), or once, attended, by our own EFI loader from the firmware's UEFI Shell (M5-F: the one-core M1b image only; no qvm or guest); neither is a chain of trust or a supported boot |

The project's value lives in being *honest* about every row of that
table on **each side of the twin**, and using the twin diff to study
the rows that *are* exercised (BSP bring-up, kernel boundaries, IPC
patterns, cloud→target portability).
