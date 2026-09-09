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

- **Cloud / x86 twin** — *designed* as AWS Graviton (c7g.large arm64,
  Ubuntu 22.04); **as built, this leg runs on the local Windows host.**
  Per [ADR-002](phase2-topology-decision.md) non-metal Graviton has no
  `/dev/kvm`, so the leg runs the SDP 8.0 QHV (`qvm`) + a single QNX
  guest under QEMU **TCG** — and once KVM was off the table there was
  nothing left that required the leg to be in the cloud at all. Every
  QHV boot and IPC number attributed to "cloud" in this repo was
  produced on the Windows box; the Phase-4 boot-time table names it
  honestly as "Local Windows (x86_64, TCG)". AWS's remaining real role
  is the KVM *test bed* (`a1.metal`, see
  [findings.md](findings.md) 2026-07-29), not the runtime host.
- **Hardware twin** — Jetson Orin Nano Dev Kit (NVIDIA L4T / JetPack 6
  on Cortex-A78AE × 6, Ampere GPU not exercised)

A short table of what crosses the twin boundary:

| Artefact | Twinned? | Notes |
|---|---|---|
| QNX IFS (`output/ifs.bin`) | **Leg-dependent — was silently broken** | Built once on the x86_64 build host (Windows local primary; EC2 fallback) and scp'd to both runtime hosts. **Honest correction:** this row claimed "bit-for-bit identical" as an unconditional invariant, but the Phase-3 Orin IPC run used a **rebuilt** IFS with new TCP server code staged in — so for that measurement the twin's load-bearing invariant did not hold. It *does* hold for the QHV leg (§1a), where both hosts boot the identical `qhv/host/output/{ifs.bin,disk-qemu}` pair verified by `SHA256SUMS` |
| QNX IPC server (`ipc-test/qnx-server`) source | **Yes** | Same C99; compiled with `qcc` inside QNX guest in both twins |
| Linux IPC client (`ipc-test/linux-client`) source | **Phase 3 / Orin only** | Per [ADR-002](phase2-topology-decision.md), there is **no Linux guest on the cloud leg** — the cloud initiator is a QNX-host program (`ipc-test/qnx-host-client`). This client runs on L4T natively on the HW twin only |
| Wire protocol (sequence + timestamp + payload) | **Yes** | Fixed-width binary frame, version-tagged |
| Test harness + benchmark scripts | **Yes** | Same `run-bench.sh`; output CSV format is identical |
| QEMU command line (machine/CPU/mem) | **Mostly** | `-machine virt,gic-version=3 -cpu ... -m 1G` shape is shared; see the accel row for the cloud/Orin split |
| QEMU acceleration | **TCG on both — for two different reasons** | This row previously read "cloud = tcg; Orin = `-enable-kvm` (KVM works on A78AE)". That is **no longer true and should not be quoted**: Orin's KVM boot is blocked by the GICv3 / `KVM_EXIT_ARM_NISV` defect ([orin-port.md](orin-port.md)), so the plain `qnx-safety-vm` leg runs TCG there *because KVM is broken*. On the **QHV leg** TCG is instead a hard architectural requirement on both sides — QHV needs EL2 for its guest, i.e. nested virtualisation, which ARM KVM does not provide on A78AE. Keep the two apart when reporting: only the QHV leg's TCG-on-both is genuine symmetry |
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

## 1a. The QHV leg — the twin's one clean host-only comparison

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
| **QEMU binary version** | **11.0.50** | **6.2.0** ← *not* controlled |
| **Host CPU / kernel** | **x86_64, Windows** | **Cortex-A78AE, L4T** |

> **This table originally omitted the QEMU version row, and that omission
> broke the leg's whole premise on first contact with the hardware
> (2026-09-08).** The argument above — "only the host CPU differs" — was
> written from the *argument list*, which is identical, and never checked the
> binary producing it. It is not: Windows runs a QEMU 11.0.50 development
> build, the Orin runs Ubuntu 22.04's stock 6.2.0. Five major releases apart,
> and the gap lands squarely on the feature this leg depends on —
> `virt,virtualization=on`, i.e. TCG emulation of EL2, which is what QHV needs
> to exist at all and is among the most heavily changed areas of QEMU across
> those releases. Any number produced from this pairing would confound host
> with QEMU version, which is precisely the error §4 warns about for the IPC
> diff. **The leg is not a valid host-only comparison until both sides run the
> same QEMU.**

It is a comparison on the *hypervisor* topology — the part of this project
that actually resembles a DRIVE OS partition boundary — rather than on plain
boot time alone, and it restores the IFS and the topology to the invariant
set. **It is not, and cannot be, a literal one-variable comparison**, and the
first attempt to treat it as one failed on exactly that point (see the
blockquote above and the account below). "Host" here is a *bundle* that
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
banner** and emit `run N: NNNNN ms` lines, matching §5's existing n=5
methodology. There is **no host banner** — the QHV host prints none, and an
earlier version of this paragraph (and of the June curated log's header)
that said to look for one was wrong. A run counts only if all three markers
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
  (disk, net, rng — rng at `0xa003a00`, the *third* `-device`). Without it the
  boot spends ~19 s timing out on entropy: on Windows the guest banner moved
  from ~49.2 s to ~29.3 s. Runs with and without rng are not comparable.
- **`-snapshot`.** The raw `disk-qemu` is writable and mutates on every boot
  (rnd-seed, keys, logs); without `-snapshot`, `sha256sum -c` fails after the
  first run and "byte-identical images" holds only at copy time. With it,
  every run boots the copy-time bytes.

**First execution on the Orin: a deterministic hang — attributed to QEMU
6.2, not the host; mechanism hypothesised, not verified (2026-09-08/09).** With the byte-identical images (`sha256sum -c`
verified on arrival) and the identical argument list, the QHV host boots on
the Orin — `FOUND GICv3 ITS`, slogger2, PCI, `devb`, file systems all come up
— and then stops dead at:

```
random: Could not initialize entropy. [random.c(406)]
```

On the Windows host the same image walks straight past that same line to
`Starting Networking` and on to `post_start`, reaching the guest banner at
~49 s. On the Orin the serial log is **419 bytes at 300 s, at 600 s, and after
12 minutes of runtime** — byte-for-byte unchanged, process alive throughout.
That is a hang, not slowness, and the sample-based check was run precisely
because "the ARM host is simply slower" was the cheaper explanation and had to
be excluded before anything else was considered.

What was learned about it, in the order it was learned — including the part
that was wrong for a day:

- **A first "entropy ruled out" test was invalid.** `-device virtio-rng-device`
  was added directly after the block device, i.e. in virtio-mmio slot 2. The
  image probes the rng at slot 3 (`random … devr-virtio.so:mem=0xa003a00`,
  the same binding the `qnx-safety-vm` leg hit on 2026-07-28); the log from
  that test still says `Unable to use devr-virtio.so as an entropy source`.
  An earlier version of this section said entropy was excluded on that
  basis. It was not. (Curated as
  [orin-qhv-tcg-q62-INVALID-rng-in-slot2.log](../logs/sample-boot/orin-qhv-tcg-q62-INVALID-rng-in-slot2.log).)
- **With the rng in the right slot, 6.2 still hangs — one step later.**
  Entropy init succeeds, the boot reaches `---> Starting Networking` and
  stops there (314 bytes at 240 s). So the hang was never about entropy;
  entropy was merely the first thing the boot *waited* on
  ([orin-qhv-tcg-q62-hang-rng-slot3.log](../logs/sample-boot/orin-qhv-tcg-q62-hang-rng-slot3.log)).
- **The line 6.2 never prints is a timeout message.** The image's
  `startup.sh` runs `random …` and then `waitfor /dev/random` (5-second
  default timeout); `Unable to access /dev/random` is `waitfor` giving up.
  On Windows (QEMU 11.0.50), on the plain EL1 IFS on this same board under
  this same 6.2, and on this image under 11.1.0, that timeout fires and the
  boot continues. Under 6.2 with `virtualization=on` it never fires. The QHV
  host runs at EL2 with VHE; the fingerprint is "every interrupt-driven
  device step works, the first timeout-wait never returns".
- **QEMU v11.1.0, built from source on the Orin
  ([build-qemu-on-orin.sh](../scripts/orin/build-qemu-on-orin.sh)), boots
  the QHV host *and* its guest on this board** — guest banner at ~78 s
  without rng, ~63 s with rng in slot 3 (probe timings, 2-second
  granularity; the n=5 instrument numbers are the ones to cite).
  [orin-qhv-tcg-q111-boot-blk-only.log](../logs/sample-boot/orin-qhv-tcg-q111-boot-blk-only.log),
  [orin-qhv-tcg-q111-boot-rng-slot3.log](../logs/sample-boot/orin-qhv-tcg-q111-boot-rng-slot3.log).
  First time the hypervisor and a guest under it ran on real ARM silicon.
- **Attributed cause — a hypothesis from upstream history, not an
  observation.** In `v6.2.0`,
  `hw/arm/virt.c` contains no `GTIMER_HYPVIRT` wiring at all — the
  non-secure EL2 *virtual* timer interrupt is simply not connected to the
  GIC; it was added in QEMU 9.0 (`1ec896fe7c`, "hw/arm/virt: Wire up
  non-secure EL2 virtual timer IRQ"). A VHE hypervisor host programming
  `CNTV_*` is really programming `CNTHV_*`, so its timeouts depend on
  exactly that interrupt. `target/arm` gained a related fix in 10.0
  (`5709038aa8`, "Don't apply CNTVOFF_EL2 for EL2_VIRT timer"). **Which of
  the two is decisive was not bisected**, and one attempt to do it cheaply
  was itself invalid: on QEMU 11 the versioned `-machine virt-8.2` still
  boots this image, but its compat flag only stops the IRQ being *described*
  in the device tree (the source comment says it is there for an old EDK2
  bug) — the wiring stays, so the test could not reproduce 6.2. A real
  bisect means building 8.2 vs 9.0 vs 10.0; it is not needed for the twin's
  purpose and was not done.
- **Non-VHE control (2026-09-09), supporting the host-side mechanism:** the
  same image under the same QEMU 6.2 on the same board with `-cpu cortex-a57`
  (ARMv8.0: EL2 but no VHE) gets *past* the hang point — `waitfor`'s timeout
  fires, networking and post_start run, `qvm` is launched
  ([orin-qhv-tcg-q62-a57-control.log](../logs/sample-boot/orin-qhv-tcg-q62-a57-control.log)).
  Without VHE the host cannot use the E2H timer redirection, which is exactly
  the path an unwired EL2 virtual-timer IRQ would break. The guest then aborts
  with `PE does not support PAUTH feature` — Cortex-A57 lacks Pointer
  Authentication, which the guest's `startup-armv8_fm` requires — a
  CPU-feature mismatch unrelated to timers. One run; it supports the
  mechanism for the host hang, it does not observe register state.

The conclusion that matters for this leg: **the hang is a QEMU-version effect
and is not attributable to the host.** With a modern QEMU the Orin column
exists. What is still owed before a number from this leg may be called a twin
diff is spelled out in the list below.

**One measurement detail that has to be checked per host, not assumed.** The
host's `post_start.custom` contains a hard-coded `sleep 90` boot-grace before
it goes on to the IPC benchmark. That sleep runs on the *host* while the guest
boots in the background, so whether it pads the measurement depends entirely
on where the guest banner lands relative to it. On Windows the banner appears
at ~49 s — comfortably *inside* the sleep — so the sleep contributes nothing
to the number. If a slower host pushed the banner past 90 s the host would
already have moved on and the interleaving would differ, so a run that reports
much more than ~90 s should be inspected rather than plotted.

**What this leg still cannot show:** it is TCG on both sides, so it measures
host emulation throughput on the QHV workload, not hardware-timed
virtualisation cost. No configuration in this repo produces a hardware-timed
QHV number — that needs nested virt, which the hardware does not offer. The
comparison is honest about *what changes when the host changes*; it is not a
performance claim about QHV.

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
  one thing being virtualised. (This sentence originally ended "and KVM actually
  works on the A78AE" — it does not for the QNX IFS: KVM boot hangs on the
  GICv3/NISV defect in [orin-port.md](orin-port.md), and the leg runs TCG.)
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
   committed to `results/ifs.sha256` in each measurement run (**not
   implemented as of 2026-09-09** — the SHA256SUMS manifests live only in the
   gitignored build trees; the QHV pair's values are recorded in findings.md
   and in the curated log headers instead) so any
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
> virtio-net bridged under **TCG** (this paragraph originally said "under
> KVM" — wrong; Orin's KVM boot is blocked, see
> [orin-port.md](orin-port.md)). The IPC diff therefore confounds at
> least three variables — host (as built: a local Windows x86_64 PC vs. A78AE;
> Graviton was the design intent), acceleration (**TCG on both** since the Orin
> KVM boot is blocked — this line originally said "TCG vs. KVM"), and transport+OS-pair (console/QNX↔QNX vs. virtio-net/QNX↔Linux)
> — and the methodology must say so explicitly rather than presenting
> the IPC delta as a host-only effect. The cloud IPC number is
> TCG-emulation-bound (a *mechanism-alive* sanity figure), so **neither** leg yields a hardware-timed transport number (this originally
> claimed the Orin leg did); the diff is
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

**Follow-up, same day: the boot-time comparison, actually run.** No
plain-`qnx-safety-vm` boot had ever been captured on the local Windows
build host with wall-clock timing (`logs/sample-boot/` only had QHV-build
logs for that side). Ran the identical QEMU invocation
(`-machine virt,gic-version=3 -accel tcg -cpu max -smp 2 -m 1G`, same
`ifs.bin`+`disk-qemu`) on both hosts, measuring real wall-clock time from
process launch to the guest's own `Startup complete` line appearing in
the captured serial log:

| Host | Boot time (launch → `Startup complete`) |
|---|---|
| Local Windows (x86_64, TCG) | **26,088 ms** |
| Jetson Orin Nano (aarch64 A78AE, TCG) | **32,125 ms** |

Δ = +6,037 ms (+23.1%), Orin slower. **This is the cleanest host-only
comparison in the repo so far** — same IFS, same disk image, same QEMU
machine/CPU/mem shape, same accelerator (TCG on both, this time by
genuine symmetry rather than incidental blockage), only the host CPU
architecture and micro-architecture differ (x86_64 host translating
aarch64 TCG vs. aarch64 host translating aarch64 TCG). TCG-on-TCG
same-ISA (aarch64 guest on an aarch64 host) still does full binary
translation — QEMU's TCG does not skip translation just because host and
guest architectures match, so the Orin result is not disadvantaged by an
ISA mismatch the Windows result doesn't have; the gap is genuinely about
host micro-architecture/scheduler/storage differences, which is exactly
what a twin diff is supposed to isolate.

**Follow-up, same day: repeated to a real sample (n=5 per side)**, since
a single run per side is not a measurement, it's an anecdote. Five
back-to-back boots on each host, same invocation, `boot-timed.log` reset
between runs:

| Run | Windows (ms) | Orin Nano (ms) |
|---|---|---|
| 1 | 26,515 | 31,753 |
| 2 | 25,445 | 31,758 |
| 3 | 25,412 | 31,775 |
| 4 | 25,427 | 31,780 |
| 5 | 25,425 | 31,446 |
| **median** | **25,427** | **31,758** |
| **mean** | 25,644.8 | 31,702.4 |

Median delta: +6,331 ms (**+24.9%**), mean delta: +6,057.6 ms (+23.6%) —
both close to the original single-run estimate (+23.1%), so that first
run was not a fluke; the repeated measurement mainly adds *confidence*,
not a different conclusion. Two things worth noting in the data itself:
(1) **Orin's five runs are far tighter** (31,446–31,780 ms, a 334 ms
spread) **than Windows' single wide outlier** (run 1 at 26,515 ms vs.
25,412–25,445 ms for runs 2–5, a likely one-time disk-cache-cold-start
effect on the Windows side — excluding run 1, the remaining four Windows
runs span only 33 ms). **Do not read this as "Orin is more consistent"** — an earlier version of
this paragraph did, and README/CLAUDE.md were corrected on 2026-09-08: the
Windows range is one cold-start outlier, and without it the remaining four
Windows runs span 33 ms, tighter than Orin's 334. The defensible claim is
"Orin is slower"; consistency is undetermined at n=5.
(2) The ~24% gap held up essentially unchanged whether measured by median
or mean, which is a good sign the sample size (n=5) is already enough to
trust the headline number — a larger n would tighten the confidence
interval but is unlikely to move the point estimate much given how tight
each side's own spread already is.

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
