# Digital Twin design

This document is the methodology layer that sits underneath the
architecture diagrams in [architecture.md](architecture.md). It
defines what is actually twinned, what is deliberately not, how the
two sides stay in sync, and how the twin diff is measured.

> ~~**Status:** Sections 1–3 are populated as part of Phase 0
> re-scope. Sections 4–6 (twin-diff methodology specifics, results
> interpretation, narrative tie-back) wait for Phase 2 / Phase 4
> measurement so the prose can be backed by numbers.~~
> **2026-09-18:** v1 was superseded before it was ever frozen; A6 (L4T on the
> metal, QNX as a KVM guest beside it) is the current direction and its gate is
> not settled. References to "the v1 campaign" below are the record of what was
> planned, not a current plan.
> **2026-09-20:** §1b is new and is the one section to read first if the
> question is "can a twin be built on the cloud". On AWS `a1.metal` the
> byte-identical IFS `26170cd7…` can be given the same KVM launch line as on
> the Orin, so the identical-image invariant can hold there for the first time
> in this project. §1b is a design; its run's outcome is held locally.
> **2026-09-27:** every measured and functional result this document used to
> quote (§1a, §1b and §5) is held locally under NC QDL v7 4.6(i); what remains
> is the method. Those measurements are architecture-version history. The
> twin diff was to run once, in the v1 campaign
> ([orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).
> §4 now points there. §6 is still deferred.

---

## 1. What is being twinned

The project mirrors the *software-layer behaviour* of an NVIDIA
DRIVE OS dual-VM partition across two physically distinct host
substrates:

- **Cloud / x86 twin** — *designed* as AWS Graviton (c7g.large arm64,
  Ubuntu 22.04); **as built, this leg runs on the local Windows host.**
  Per [ADR-002](phase2-topology-decision.md) non-metal Graviton has no
  `/dev/kvm`, so the leg runs the SDP 8.0 QHV (`qvm`) + a single QNX
  guest under QEMU **TCG** — ~~and once KVM was off the table there was
  nothing left that required the leg to be in the cloud at all.~~
  **2026-09-19:** that last clause was ADR-002 read too broadly. The limit
  ADR-002 found is **non-metal**, not **cloud** — its own words are "Any
  hardware-accelerated partitioner — KVM *or* QHV — needs `*.metal` or real
  silicon". On a bare-metal `a1.metal` that day `/dev/kvm` was present
  (`Hyp mode initialized successfully`), and a QNX guest carrying a
  `startup-qemu-virt` **we rebuilt** (`-fno-auto-inc-dec`, not a
  QNX-supported configuration) was run under `-enable-kvm` there, with the
  SDP's **shipped** `startup-qemu-virt` as the control; the outcome and its
  log (`aws-a1-metal-kvm-fix-crossvendor.log`) are held locally under NC QDL
  v7 4.6(i). So KVM on an ARM cloud host is available again — on `*.metal`
  only. **2026-09-20:** `a1.metal` was the second host in the boot comparison
  of §1b, n=5 timed boots on a byte-identical image (`20260920T-kvm-twin`,
  held locally). On 2026-09-21 the attribution ladder of A6 was run on
  `a1.metal` too, over TCP (`20260921T-ladder-a1metal`, held locally), and on
  2026-09-22 the Orin's notified-shared-memory ladder: TCP, the D-udp rung,
  and polled and notified shared memory (`20260922T-a6-a1metal-kick`, held
  locally). What still does not exist is a cloud *leg* in this
  project's sense, a QHV host plus guest, and QHV cannot run under KVM at all.
  The §5 records stay architecture-version history.
  Non-metal Graviton still has no `/dev/kvm` (the t4g.small probe stands),
  `c7g.metal` — the closer core match — stays quota-blocked at 64 vCPU, and
  `a1.metal` is Cortex-A72 against the Orin's A78AE, so even a revived pair
  would differ in a *bundle*, not in one variable (§1a). Every
  QHV boot and QHV IPC number attributed to the cloud leg (A1) was
  produced on the Windows box; the Phase-4 boot-time table names it
  honestly as "Local Windows (x86_64, TCG)". AWS's remaining real role
  is the KVM *test bed* (`a1.metal`, see
  [findings.md](findings.md) 2026-07-29 and **2026-09-19**), not the
  runtime host.
- **Hardware twin** — Jetson Orin Nano Dev Kit (NVIDIA L4T / JetPack 6
  on Cortex-A78AE × 6, Ampere GPU not exercised)

A short table of what crosses the twin boundary:

| Artefact | Twinned? | Notes |
|---|---|---|
| QNX IFS (`output/ifs.bin`) | **Leg-dependent — was silently broken** | Built once on the x86_64 build host (Windows local primary; EC2 fallback) and scp'd to both runtime hosts. **Honest correction:** this row claimed "bit-for-bit identical" as an unconditional invariant, but the Phase-3 Orin IPC run used a **rebuilt** IFS with new TCP server code staged in — so for that measurement the twin's load-bearing invariant did not hold. It *does* hold for the QHV leg (§1a), where both hosts boot the identical `qhv/host/output/{ifs.bin,disk-qemu}` pair verified by `SHA256SUMS` |
| QNX IPC server (`ipc-test/qnx-server`) source | **Yes** | Same C99; compiled with `qcc` inside QNX guest in both twins |
| Linux IPC client (`ipc-test/linux-client`) source | **Phase 3 / Orin only** | Per [ADR-002](phase2-topology-decision.md), there is **no Linux guest on the cloud leg** — the cloud initiator is a QNX-host program (`ipc-test/qnx-host-client`). This client runs on L4T natively on the HW twin only. **2026-09-14:** "no Linux guest on the cloud leg" is right for A1. It is stale for v1: v1's TCG twin legs boot v1's guest set, S1's Linux guest included, in a QHV host image ([plan](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11), v1 row and campaign item 6) |
| Wire protocol (sequence + timestamp + payload) | **Yes** | Fixed-width binary frame, ~~version-tagged~~ **2026-09-11:** with no version tag (`ipc-test/common/frame.h`; see §3) |
| Test harness + benchmark scripts | ~~**Yes**~~ **CSV schema only** | ~~Same `run-bench.sh`;~~ output CSV format is identical. **2026-09-11:** No `run-bench.sh` exists. The legs use different programs and launchers. Only the CSV schema is shared (`results/cloud/header.csv`, `results/hw/header.csv`) |
| QEMU command line (machine/CPU/mem) | **Mostly** | `-machine virt,gic-version=3 -cpu ... -m 1G` shape is shared; see the accel row for the cloud/Orin split |
| QEMU acceleration | **TCG on both — for two different reasons** | This row previously read "cloud = tcg; Orin = `-enable-kvm` (KVM works on A78AE)". That **should not be quoted**. The A2 leg ran TCG with the SDP's **shipped** `startup-qemu-virt`; the KVM outcomes of that binary and of a `startup-qemu-virt` **we rebuilt** (board source `orin-native/startup/qemu-virt/`, startup library compiled `-fno-auto-inc-dec`; not a QNX-supported configuration — QNX ships no such binary) are held locally (NC QDL v7 4.6(i)). On the **QHV leg** TCG is instead a hard architectural requirement on both sides — QHV needs EL2 for its guest, i.e. nested virtualisation, which ARM KVM does not provide on A78AE. Keep the two apart when reporting: only the QHV leg's TCG-on-both is genuine symmetry. **2026-09-19:** the *cloud* side of this row needs the same care. Its reason is **non-metal**, not "cloud": a bare-metal `a1.metal` exposes `/dev/kvm` (the QNX outcome there is held locally, and **no cloud leg was built or measured**). Non-metal Graviton still has no `/dev/kvm`. As built this leg runs on the **x86_64** Windows PC, which can never use KVM for an ARM guest, so TCG is required there in principle rather than by any defect and a Windows-vs-Orin pair is TCG-on-both by necessity. The QHV sentence above is unaffected: QHV needs EL2 and ARM KVM does not nest on A78AE |
| IPC transport | **Different by design** | Cloud: host↔guest `qvm` virtio-console (single-OS QNX↔QNX); Orin: QNX↔Linux virtio-net ~~over KVM bridge~~ **2026-09-11:** over the `br0` bridge, under TCG. The legs no longer share an identical topology — see §4 |
| Linux Compute side | **Different by design** | Cloud: **no Linux guest** (single QNX guest under QHV); HW: L4T native (host OS). See §2/§3. **2026-09-14:** right for A1, stale for v1: S1 plans a Linux guest under native qvm, and v1's TCG twin legs would boot it in their QHV host image ([plan](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11), v1 row and campaign item 6) |
| Host kernel | **Different by design** | This is exactly the variable being studied |
| Host CPU | **Different by design** | ~~Graviton3 Neoverse-V1 vs Tegra A78AE — same ARMv8 ISA, different micro-architecture and scheduler context~~ **2026-09-11:** As built, an x86_64 Windows PC against the Tegra A78AE, so the ISA differs too (§1, §5). Graviton3 was the design |

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

## 1a. The QHV leg — ~~the twin's one clean host-only comparison~~ **(2026-09-11: a comparison of two host bundles)**

*Added 2026-09-08.* By §1's own rule ("anything that differs between twin
sides in those rows is a bug") the twin was in trouble: the invariant set had
collapsed to **{wire protocol, harness/CSV shape, QEMU machine shape}**. The
IFS was rebuilt on one side, the two legs run different server programs
(`qnx-server` over a console vdev vs. `qnx-server-net` over TCP), the
accelerators differ, the transports differ, and the "cloud" host is a Windows
desktop. A twin diff with almost no invariants is not a twin diff.

The fix does not require rebuilding the project. The **QHV leg is
host-agnostic**, and cheaply so. Its entire QEMU invocation is

```
-machine virt,virtualization=on,gic-version=3 -cpu max -accel tcg \
  -smp 2 -m 2G -drive file=disk-qemu,... -device virtio-blk-device,... \
  -kernel ifs.bin -serial file:<log> -display none -no-reboot
```

and its only host inputs are two files. Everything that makes the leg
interesting — the `qvm` hypervisor, the guest, the virtio-console and
`vdev shmem` wiring, the pty pair (`/dev/ptyp0`↔`/dev/ttyp0`, a *QNX* device
inside the emulated world, not a host one) — lives **inside** the emulation.
Nothing crosses to the host but the image files and a serial log.

So the same two images can be copied to the Orin and booted there unchanged:

| | Windows leg | Orin leg |
|---|---|---|
| `ifs.bin` + `disk-qemu` | identical (SHA256-verified) | identical |
| `qvm` config, guest, vdevs | identical (inside the image) | identical |
| QEMU machine / CPU / mem args | identical | identical |
| Accelerator | TCG | TCG |
| **QEMU binary version** | ~~**11.0.50**~~ | ~~**6.2.0** ← *not* controlled~~ |
| **Host CPU / kernel** | **x86_64, Windows** | **Cortex-A78AE, L4T** |

**2026-09-11:** The QEMU row was later aligned to one release. Both hosts ran
QEMU 11.1.0, in different builds that the times files stamp. That pair is A3
history under the freeze decision. ~~The TCG legs run again in the v1 campaign.~~
**2026-09-20 (owner): the TCG twin legs are withdrawn. A6 measures under KVM only, which means the QNX Hypervisor has no measurable leg anywhere — QHV needs EL2 and ARM KVM does not nest on A78AE, so TCG was its only emulated route. §1a stays as the record of what was measured, and is not re-run. 2026-09-18: v1 is superseded; whether the TCG twin legs survived was one
of A6's open choices.**

> **This table originally omitted the QEMU version row, and that omission
> undermined the leg's whole premise (2026-09-08).** The argument above —
> "only the host CPU differs" — was
> written from the *argument list*, which is identical, and never checked the
> binary producing it. It is not: Windows runs a QEMU 11.0.50 development
> build, the Orin runs Ubuntu 22.04's stock 6.2.0. Five major releases apart,
> and the gap lands squarely on the feature this leg depends on —
> `virt,virtualization=on`, i.e. TCG emulation of EL2, which is what QHV needs
> to exist at all and is among the most heavily changed areas of QEMU across
> those releases. Any number produced from this pairing would confound host
> with QEMU version, which is precisely the error §4 warns about for the IPC
> diff. ~~**The leg is not a valid host-only comparison until both sides run the
> same QEMU.**~~ **2026-09-11:** One QEMU release is needed but not enough. The
> build and the TCG backend still travel with the host, so the leg compares
> host bundles (next paragraph).

It is a comparison on the *hypervisor* topology — the part of this project
that actually resembles a DRIVE OS partition boundary — rather than on plain
boot time alone, and it restores the IFS and the topology to the invariant
set. **It is not, and cannot be, a literal one-variable comparison**, and the
first attempt to treat it as one failed on exactly that point (see the
blockquote above). "Host" here is a *bundle* that
changes together by construction: the CPU and its micro-architecture, the
host OS and scheduler, **the TCG code-generation backend** (`tcg/i386` on the
Windows box vs. `tcg/aarch64` on the Orin — different generated code for the
same guest instructions), and the QEMU *build* (compiler, configure flags,
glib/pixman/slirp versions), which differs even when the release number
matches. The honest claim is therefore "same images, same guest-visible
machine, same accelerator, same device set, same release of QEMU — what
changes when the host bundle changes?", and every one of those "same"s is
stamped into the times files by the instruments so a mismatched pair is
visible to whoever reads them.

**Instruments** (same marker, same method, deliberately duplicated arg lists —
change one, change the other):

- Windows: `scripts/launch-qhv-tcg.ps1 -Runs N -StopOnGuestBanner`
- Orin: `scripts/orin/launch-qhv-on-orin-tcg.sh N`

Both time **launch → the guest's `QNX qnx-guest … ARMv8_Foundation_Model`
banner** and emit `run N: NNNNN ms` lines, matching §5's n=5 methodology.
There is **no host-banner marker**; an earlier version of this paragraph (and
of the June curated log's header) that said to look for one was wrong. A run
counts only if all three markers
that *are* emitted appear, in order: `=== AUTO-START QNX GUEST UNDER QVM`
(host reached post_start), `=== launching qvm @g2.conf` (hypervisor invoked),
and the guest banner (guest came up across EL2/EL1). They fail
distinguishably, and none of them is a timeout.

Three settings are part of the measured configuration and are stamped into
every times file by both instruments (`# qemu:`, `# devices:`, `# disk:`):

- **QEMU binary.** Orin: `QEMU_BIN`, defaulting to the from-source
  `~/qemu-v11.1.0/bin` build if present, never silently `/usr/bin`. That
  silent fallback is what produced the 6.2.0 confound.
- **Device set.** `WITH_RNG=1` / `-WithRng` presents virtio-net (slot filler)
  and virtio-rng in the virtio-mmio order the image's `startup.sh` binds
  (disk, net, rng — rng at `0xa003a00`, the *third* `-device`). The image's
  `startup.sh` waits for `/dev/random` with a timeout, so runs with and
  without rng are not comparable.
- **`-snapshot`.** The raw `disk-qemu` is writable and the guest writes to it
  (rnd-seed, keys, logs); without `-snapshot`, `sha256sum -c` fails after the
  first run and "byte-identical images" holds only at copy time. With it,
  every run boots the copy-time bytes.

**2026-09-11:** Both instruments now also print one segment line per run
(`#   segments run N:`). It gives wall time from launch to four markers: host
post_start, qvm launched, guest startup complete and the guest banner. The
segments separate compute-bound time from fixed waits. The release-aligned
pair and its segment tables used this instrument; they are held locally
(NC QDL v7 4.6(i)) and are A3 history.

**First executions on the Orin (2026-09-08/09).** The byte-identical images
(`sha256sum -c` verified on arrival) were run on the Orin with the identical
argument list, first under the distro QEMU 6.2.0 and then under QEMU 11.1.0
built from source on the board
([build-qemu-on-orin.sh](../scripts/orin/build-qemu-on-orin.sh)). The outcomes,
the QEMU-version investigation that followed (including a reverted-wiring
build, [patch](../scripts/orin/patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch),
and a `-cpu cortex-a57` non-VHE control), their curated logs and the
release-aligned pair of 2026-09-09 are held locally under NC QDL v7 4.6(i).
Under the freeze decision they are A3 history.

Two facts from outside this project bear on any such pairing and stay here.
In QEMU `v6.2.0`, `hw/arm/virt.c` contains no `GTIMER_HYPVIRT` wiring: the
non-secure EL2 *virtual* timer interrupt is not connected to the GIC. It was
added in QEMU 9.0 (`1ec896fe7c`, "hw/arm/virt: Wire up non-secure EL2 virtual
timer IRQ"), and `target/arm` gained a related fix in 10.0 (`5709038aa8`,
"Don't apply CNTVOFF_EL2 for EL2_VIRT timer"). A VHE hypervisor host
programming `CNTV_*` is really programming `CNTHV_*`, so its timeouts depend on
exactly that interrupt. On QEMU 11 the versioned `-machine virt-8.2` compat
flag only stops the IRQ being *described* in the device tree (the source
comment says it is there for an old EDK2 bug); the wiring stays. **So the QEMU
release is part of the measured configuration of this leg, never a detail.**

**One measurement detail that has to be checked per host, not assumed.** The
host's `post_start.custom` contains a hard-coded `sleep 90` boot-grace before
it goes on to the IPC benchmark. That sleep runs on the *host* while the guest
boots in the background, so whether it pads the measurement depends entirely
on where the guest banner lands relative to it. If a slower host pushed the
banner past 90 s the host would already have moved on and the interleaving
would differ, so a run that reports much more than ~90 s should be inspected
rather than plotted.

**What this leg still cannot show:** it is TCG on both sides, so it measures
host emulation throughput on the QHV workload, not hardware-timed
virtualisation cost. ~~No configuration in this repo produces a hardware-timed
QHV number — that needs nested virt, which the hardware does not offer.~~
**2026-09-11:** That holds for every QEMU configuration. The native port (A4,
Phase 3b) places qvm at EL2 on the Orin itself, with no nesting; its records
are held locally. ~~The hardware-timed measurement runs in the v1 campaign
([orin-native-port-plan.md](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).~~
**2026-09-18: v1 is superseded. A4 and A5 stay valid as their own architectures
and are not re-run; A6 has no QNX Hypervisor leg, and no hardware-timed
hypervisor number is published.** The
comparison is honest about *what changes when the host changes*; it is not a
performance claim about QHV.

---

## 1b. The KVM leg — the first pair where the identical-image invariant holds

Written 2026-09-20 as a design, and marked as one throughout. Its run
(2026-09-20) is held locally; see the status at the end of this section.

### Why this section exists

Every twin leg before this one failed the same way, in the row §1's table calls
"**Leg-dependent — was silently broken**": the two sides did not boot the same
image. The A2/Phase-3 Orin IPC run used a **rebuilt** IFS with new TCP server
code staged in, so the twin's load-bearing invariant did not hold for the
measurement that most depended on it. The QHV leg (§1a) did hold it, but only
by making both sides TCG on a host bundle that differed in ISA as well — an
x86_64 Windows PC against Tegra A78AE.

On 2026-09-18 and 2026-09-19 that changed, without anyone setting out to build
a twin:

| | Jetson Orin Nano | AWS `a1.metal` |
|---|---|---|
| IFS | `ifs-kvmfix.bin`, sha256 `26170cd7dc74c216…` | `ifs-kvmfix.bin`, sha256 `26170cd7dc74c216…` |
| QEMU machine | `-machine virt,gic-version=3` | `-machine virt,gic-version=3` |
| CPU / accel | `-cpu host -enable-kvm` | `-cpu host -enable-kvm` |
| Size | `-smp 2 -m 1G` | `-smp 2 -m 1G` |
| QEMU | distro 6.2.0 | distro 6.2.0 |
| Host silicon | Cortex-**A78AE**, Tegra234 | Cortex-**A72**, Graviton1 |

Same bytes, same launch line, KVM on both sides, and only the host silicon
differs. Provenance: record `20260918T-kvm-gpu` (held locally) pins the Orin
side's IFS by that hash; `aws-a1-metal-kvm-fix-crossvendor.log` (held locally)
records the same hash on the AWS side. This is the first cloud↔board pair in
the project where the invariant is checked by hash rather than intended.

What made it possible was the rebuilt `startup-qemu-virt` (§1's accelerator
row), not a change of plan. ADR-002's constraint was **non-metal**, and
`*.metal` was not tried until 2026-09-19.

### What the measurement would be

**Boot to `Startup complete`, with no disk attached, n=5 per host.**

No disk is the deliberate part. The guest disk is the one artefact in this
configuration that is **not pinned and is known to drift**: the 2026-09-18
runs (record `20260918T-kvm-gpu`, held locally) used `disk-qemu` without
`-snapshot`, so the guest wrote to it, and the board's copy now hashes
`f326b792…` against the PC's `fd2ee67d…`. Dropping the disk removes that
confound completely rather than managing it. The cost is scope: this measures
IFS load, startup and procnto init under KVM, and says nothing about the
filesystem, networking or IPC.

### What must be pinned or stamped, or the number is void

1. **CPU governor.** On the Orin, pin `performance` on all six cores. This is
   not optional: `schedutil` clocks the board down when idle, and the
   unpinned-against-pinned comparison on this board is in record
   `20260919T-saturation` (held locally). Whatever `a1.metal` exposes must be
   recorded the same way, and if it cannot be pinned, that is a stated limit,
   not a footnote.
2. **QEMU build**, not just release. §1a already establishes that "host" is a
   bundle; two builds of 6.2.0 are not interchangeable without saying so.
3. **Host kernel.** L4T against `6.8.0-aws`. This is part of the bundle and
   cannot be removed, only declared.
4. **The rebuilt startup is ours.** It is not a QNX-supported configuration.
   Because it is the same binary on both sides the comparison is symmetric and
   still valid, but every figure taken here carries that sentence.

### What such a number could and could not support

It **could** support: a host-to-host comparison of QNX guest bring-up under KVM
where the image really is identical — the thing §1a could only approximate.

It could **not** support: any statement about the QNX Hypervisor, which cannot
run under KVM at all (it needs EL2, and ARM KVM does not nest on A78AE); any
hardware-timed *hypervisor* number, which stays deferred; any claim about A6's
GPU half, since `a1.metal` has no GPU; and any single-variable reading, because
A72 against A78AE is a five-year micro-architectural gap inside a host bundle
that also differs in kernel. `c7g.metal` (Neoverse-V1) would be the closer core
match and stays quota-blocked at 64 vCPU against a 32-vCPU account limit.

### Status: run 2026-09-20

Both legs ran. Record: `20260920T-kvm-twin`, held locally under NC QDL v7
4.6(i); its figures and outcomes are not reproduced here.

The inputs were identical as designed: sha256 `26170cd7…` on the Orin and on
two separately launched `a1.metal` instances, the same launch line, and QEMU
6.2.0 from the *same* Debian package build (`1:6.2+dfsg-2ubuntu6.31`) on both
sides.

One method point carries over to any boot metric here. A fixed software
timeout does not depend on CPU speed, so a boot metric that contains one hides
host differences. The record therefore reports per-segment times as well as the
total, and its final configuration presents the disk, `-snapshot`, and virtio
net and rng in the order this image's `startup.sh` requires.
[measurement-design.md](measurement-design.md) §3.7 is the falsification test
for how much of the metric a timeout is.

The governor was pinned to `performance` on the Orin and restored afterwards.
`a1.metal` exposes no `cpufreq` and no `cpuidle` at all, so the AWS side could
not be pinned — a stated limit, exactly as this section required.

Still true after the run: nothing here is a hypervisor number, the rebuilt
startup is ours and not a QNX-supported configuration, nothing is shown about
networking or IPC, and A6's gate was then unsettled, so this is a candidate for
that campaign rather than part of it.

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
  premise — no `/dev/kvm` on non-metal Graviton). The cloud leg's IPC
  mechanism crosses a **real `qvm` EL2/EL1 partition boundary** — but by
  design it does **not** represent the QNX-safety
  ↔ Linux-compute heterogeneity that is the load-bearing mirror of DRIVE
  OS's dual-OS partitioning. That heterogeneity is twinned on **Orin
  only**. **2026-09-14:** all of this bullet describes A1. It is stale for
  v1: v1's TCG twin legs boot v1's guest set, S1's Linux guest included,
  in a QHV host image under QEMU ([plan](orin-native-port-plan.md#architecture-versions-and-the-measurement-freeze-decided-2026-09-11),
  v1 row and campaign item 6). Under v1 the TCG legs would carry a Linux
  guest too.
- **Hardware twin (Orin)** runs Linux Compute as **L4T itself**, the
  native host, and is the **committed home of the heterogeneous QNX↔Linux
  IPC**. This is closer to "real Tegra Linux runs natively"; QNX is the
  one thing being virtualised. (This sentence originally ended "and KVM actually
  works on the A78AE"; that should not be quoted. The leg ran TCG, and the KVM
  outcomes of the SDP's **shipped** `startup-qemu-virt` and of one **we
  rebuilt** (`-fno-auto-inc-dec`, board source `orin-native/startup/qemu-virt/`,
  not QNX-supported) are held locally. Nothing here says anything about QHV
  under KVM, which still needs nested virt.)
  Putting Linux in its own QEMU VM on Orin Nano would burn 2 GB extra
  RAM for no narrative benefit.

This is a calibrated trade-off, not an accident: each twin side
demonstrates what its host can *actually* do — the cloud leg owns the
hypervisor-boundary IPC *mechanism*; Orin owns the *heterogeneous*
dual-OS story. ~~A dual-guest Linux-under-QHV cloud topology (ADR-002
Option B) is a research-gated **Phase 2.5** stretch only, not a claim
made today.~~ **2026-09-11:** The cloud dual-guest topology is still unbuilt
and is not a claim. Its idea moved to the native leg: a Linux guest without a
GPU under native qvm on the Orin is now S1-F, planned before the v1 freeze.
**2026-09-17: S1-F's rungs were run — B3 and B4 a Linux guest under native
qvm on the board, B5 the Linux guest beside the QNX guest; their records are
held locally under NC QDL v7 4.6(i). 2026-09-18: it is a rung of the
native-hypervisor ladder (A4/A5) and is not evidence about A6.**

The HW twin therefore can **claim**:
- Real Tegra-family silicon (A78AE matches DRIVE Orin's CCPLEX core family)
- L4T as the actual Compute-side OS (closer to the real DRIVE OS Linux partition than Ubuntu cloudimg)

The HW twin **cannot** claim:
- Type-1 hypervisor partitioning (QEMU on L4T is host-mediated, under TCG or KVM alike. The native port, A4, places qvm at EL2 on the board itself: a real `qvm` boundary, not a certified one)
- DRIVE OS-class Safety RT guarantees
- NVDLA / PVA / GPU partitioning (those exist on Orin Nano but are out of scope; QNX guest never sees them)
- Secure-boot chain across partitions

The cloud twin can claim none of the above either, but offers in exchange:
- Fast iteration, regression sweeps, parameter studies
- A **real `qvm` Type-1 partition boundary** (EL2 host ↔ EL1 guest) — the
  strongest hypervisor artefact in the project — exercised by the
  host↔guest IPC, though TCG-emulated, not hardware-timed (per
  [ADR-002](phase2-topology-decision.md))
- ~~A scaling path (instance size up to c7g.16xlarge) for stress testing~~ **2026-09-11:** Not as built. The leg runs on the Windows PC, so no instance size applies (§1)

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
   committed to `results/ifs.sha256` in each measurement run (**not
   implemented as of 2026-09-09** — the SHA256SUMS manifests live only in the
   gitignored build trees; the QHV pair's values are recorded in findings.md
   and in the curated log headers, held locally, instead) so any
   accidental rebuild between runs is caught.
2. **The IPC source code** — under `ipc-test/`, single git tree,
   pinned to the commit SHA used for any given measurement run. ~~The
   benchmark script records the SHA in its output CSV header.~~
3. ~~**The wire protocol version tag** — a one-byte field at the head
   of every frame. If the cloud twin and the HW twin ever speak
   different protocol versions, the receiver-side benchmark refuses
   to run rather than producing comparable-looking-but-incomparable
   numbers.~~

   **2026-09-11:** Neither was implemented. The CSVs carry no SHA; their only
   free-text field is `notes` (schema: `results/cloud/header.csv`,
   `results/hw/header.csv`; the CSVs themselves are held locally). The frame starts with a
   sequence number and has no version byte (`ipc-test/common/frame.h`).
   Under the freeze decision, the v1 manifest records the instrument source
   hashes, `frame.h` included, and every campaign record carries the
   manifest's version stamp
   ([orin-native-port-plan.md](orin-native-port-plan.md#reference-architecture-v1-manifest-contents)).

~~The Twin Sync Agent (Phase 3+) owns the script `scripts/twin/sync.sh`
that rsyncs IFS + sources from a known-good build host snapshot to
both runtime hosts and verifies the SHA-256 + git-SHA invariants on
landing.~~ **2026-09-11:** `sync.sh` is not used from the Windows build host.
It targets the plain IFS, demands a cloud runtime host this leg no longer has,
and needs `rsync`, which Git Bash lacks. The hypervisor images move with
[`scripts/twin/sync-qhv.sh`](../scripts/twin/sync-qhv.sh), which enforces the
checksum invariant on arrival ([findings.md](findings.md) 2026-09-08).

**Anti-pattern explicitly forbidden:** rebuilding the IFS on each
runtime host independently. Even if the build is reproducible in
theory, debugging a "did the IFS change?" question is harder than
just having one canonical artefact.

---

## 4. Twin-diff methodology

> ~~_Section deferred to Phase 4. Will define what a "twin diff" run
> looks like (one matched pair of measurement runs across cloud +
> HW); the metrics chosen (boot time, P50 / P99 / P99.9 IPC RTT,
> jitter envelope, throughput at 1 KB / 4 KB / 16 KB messages); the
> reporting format; how to interpret a delta._~~
> **2026-09-11:** The owner's freeze decision defines the twin diff. ~~It runs
> once, in the v1 campaign: the two TCG legs against each other (two host
> bundles, §1a), and each TCG leg against the native leg.~~ **2026-09-18: v1 was
> superseded before it was ever frozen (A6). 2026-09-20 (OD10): the TCG twin legs
> do not survive — A6 measures under KVM only. 2026-09-21 (OD11): A6's sample
> sizes and campaign content are settled, so A6's gate is closed. The twin diff
> has not been re-run; A1/A2/A3 remain architecture-version history.** A table compares only
> records with the same `arch=` stamp
> ([orin-native-port-plan.md](orin-native-port-plan.md#the-campaign)).

> **Constraint on the diff design (per [ADR-002](phase2-topology-decision.md)):**
> the original premise — "hold everything identical, change only the
> host, measure the delta" — **no longer holds for IPC**. The cloud and
> Orin legs run **non-identical IPC topologies**: the cloud leg is a
> single-OS QNX↔QNX exchange over a `qvm` virtio-console vdev under
> **TCG**, whereas Orin is a heterogeneous QNX↔Linux exchange over
> virtio-net bridged under **TCG** (this paragraph originally said "under
> KVM" — wrong: that A2 leg ran under TCG, with the SDP's shipped
> `startup-qemu-virt`). The IPC diff therefore confounds at
> least three variables — host (as built: a local Windows x86_64 PC vs. A78AE;
> Graviton was the design intent), acceleration (**TCG on both** — this line
> originally said "TCG vs. KVM"), and transport+OS-pair (console/QNX↔QNX vs.
> virtio-net/QNX↔Linux)
> — and the methodology must say so explicitly rather than presenting
> the IPC delta as a host-only effect. Any cloud IPC number is
> TCG-emulation-bound, so **neither** leg yields a hardware-timed transport number (this originally
> claimed the Orin leg did); the diff is
> "mechanism vs. heterogeneity", not a clean host-only comparison. ~~The
> **boot-time** diff (same IFS, same QEMU machine shape) remains the
> cleaner near-host-only comparison and is the diff to lead with.~~
> **2026-09-11:** Not a lead comparison. Its time files carry no QEMU-build
> stamp, so "near-host-only" cannot be checked, and "host" is a bundle (§1a).
> That diff is A2 history.

---

## 5. Results interpretation

> **2026-09-27:** the figures this section held — the A1/A2 twin diff of
> 2026-07-28 from `scripts/twin/diff-results.sh`, the plain-IFS boot-time pair
> and its n=5 repeat, and the sample-matched re-run — are held locally under
> NC QDL v7 4.6(i), with the CSVs they came from. The CSV schema stays public
> (`results/cloud/header.csv`, `results/hw/header.csv`). They are
> architecture-version history (A1 and A2,
> [orin-native-port-plan.md](orin-native-port-plan.md#measurement-inventory))
> and are not re-run for their own sake.

The interpretation rules they taught are method, and stay:

- **The two IPC legs measure different things.** The cloud leg's round trip
  runs through a `qvm` EL2↔EL1 console vdev between two QNX instances; the HW
  leg's runs through a Linux bridge + virtio-net between a QNX guest and the
  native Linux host. Both are TCG-emulation-bound and neither isolates host
  CPU performance (§4). A same-transport, same-IFS, host-only comparison would
  need a console-based transport on Orin or a virtio-net-based transport on
  the cloud leg, whose Linux side is deliberately absent per
  [ADR-002](phase2-topology-decision.md).
- **Compare tail statistics only at matched sample sizes.** With n=15, P99
  and Max are the same sample, and Max grows with n for any non-degenerate
  distribution, so a 15-sample tail against a 100,000-sample tail compares
  extreme-value statistics, not transports. The same holds for a P50 taken
  from wildly different n.
- **A host comparison needs the QEMU build stamped.** The plain-IFS boot
  pair's time files carried no QEMU-build stamp (the Windows QEMU was never
  recorded), and the TCG backend changes with the host (§1a), so host and
  QEMU build are confounded in it.
- **Same-ISA TCG still translates.** QEMU's TCG does full binary translation
  even when host and guest architectures match, so an aarch64 host is not
  spared translation an x86_64 host pays.
- **A single run is an anecdote.** Repeat to n ≥ 5 before reading a
  difference, and name any one-time outlier (a cold disk cache) rather than
  let it set a spread.

---

## 6. Narrative tie-back

> _Section deferred to Phase 6. Will distill the twin-diff findings
> into short and long write-ups, with citations to the measured records
> (held locally under NC QDL v7 4.6(i) until the licence allows
> otherwise)._
