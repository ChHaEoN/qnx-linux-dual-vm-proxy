# BSP selection — Phase 0 findings & decision

> **Status:** Phase 0 research complete. Findings 1–4 below are decided;
> Finding 5 lists empirical questions that move into Phase 1 validation.

---

## Findings

### F1. QNX SDP 8.0 host toolchain is x86_64 Linux native + Windows native (no macOS)

The SDP 8.0 host toolchain ships for **x86_64 Linux native** *and*
**Windows native**; macOS (Intel and Apple Silicon) remains
unsupported in 8.0. Empirically confirmed 2026-05 by a re-inspection
of the QNX Software Center download matrix on a QNX Everywhere
account: both a Linux x86_64 installer and a Windows installer are
offered. An earlier pass through the matrix recorded "Linux x86_64
only" — that was a partial inspection and is corrected here. See the
2026-05-07 amendment in [findings.md](findings.md) for the
build-host-pivot decision that follows from this correction.

`mkqnximage`, `qcc`, and the QNX Software Center therefore will not run on:
- Graviton arm64
- Apple Silicon macOS (M1 / M2 / M3)
- Intel macOS (no installer offered for any macOS variant in 8.0)
- arm64 Linux (no installer offered)

**Consequence — hybrid build/runtime architecture:**

```
x86_64 build host (Windows local primary; EC2 t3.medium fallback)  ──ifs.bin / disk-qemu.vmdk──▶  Graviton runtime host (c7g.large)
SDP 8.0 + mkqnximage                                                       scp                     qemu-system-aarch64 + KVM
```

The IFS (`ifs.bin`) produced by `mkqnximage --arch=aarch64le` is an
arch-agnostic binary blob from the host's perspective: it boots the QNX
microkernel for whichever target architecture it was built for, and the
build host's CPU does not have to match. Therefore building on x86_64
and running on Graviton is sound — the empirical "does it actually
boot under KVM-on-arm64" question is what F5 below tracks.

> **2026-09-11 (as built):** no IFS ever ran on Graviton. Non-metal
> Graviton exposes no `/dev/kvm` (F3 note below). The x86_64-built
> images booted under QEMU TCG on the Windows PC and on the Orin, and the
> cloud-leg guest booted under native `qvm` on the Orin (M3,
> [findings.md](findings.md) 2026-09-10). The cross-build argument held;
> the Graviton runtime host and its KVM line are design-time only.

---

### F2. Two BSP paths under SDP 8.0

| Path | Source | License | Status |
|---|---|---|---|
| **`mkqnximage --type=qemu --arch=aarch64le`** | Bundled with SDP 8.0 | NCEULA (Everywhere covers personal use) | Official; used as Phase 1 baseline |
| **`joexue/qemu-virt`** | <https://github.com/joexue/qemu-virt> | MIT | Community BSP; tested under SDP 8.0.0; PCI listed as TODO. Phase 2+ study target. |

Phase 1 uses `mkqnximage` because it is the lowest-friction path to
"QNX boots on QEMU virt." The community BSP is more interesting from
a BSP-engineering perspective (visible source, modifiable, MIT) and is
the right artifact to engage with in Phase 2 once Phase 1 has
validated the toolchain end-to-end.

---

### F3. KVM acceleration on Graviton works with stock Ubuntu 22.04

> **2026-09-11: falsified on 2026-06-11.** Non-metal Graviton exposes no
> `/dev/kvm`; EL2 is not passed through (a t4g.small probe;
> [findings.md](findings.md) 2026-06-11 QHV milestone;
> [ADR-002](phase2-topology-decision.md) §1). KVM on AWS needs a `*.metal`
> instance. The `a1.metal` run on 2026-07-29 hangs the QNX IFS
> under KVM on the GICv3/NISV defect ([findings.md](findings.md)
> 2026-07-29). The Phase 0 text below is kept as written.

Graviton instances expose `/dev/kvm` to userspace. The QEMU invocation
that activates KVM on aarch64 hosts is:

```
qemu-system-aarch64 \
  -M virt,gic-version=3 \
  -cpu host \
  -enable-kvm \
  ...
```

`gic-version=3` is required for Graviton3's GICv3 interrupt controller.
`-cpu host` passes the Graviton3 (Neoverse-V1) CPU model through to
the guest. No custom kernel modules, no DKMS, no Ubuntu HWE tricks
needed.

---

### F4. QNX Everywhere (NCEULA) license — what this repo can and cannot ship

**Allowed (per the QNX Everywhere NCEULA):**
- Personal projects and self-education
- Extending hardware support / writing BSPs
- Demonstrating to others (including interview demos)
- Publishing build scripts, Makefiles, configuration files
- Publishing screenshots and boot logs

**Not allowed (red lines for this repo):**
- Redistributing the QNX SDK or any portion of it
- Committing compiled QNX binaries (`ifs.bin`, `disk-qemu.vmdk`, kernel images, qcc-built ELFs)
- Commercial distribution

**Repo policy:** the user must obtain their own QNX Everywhere license
and install SDP 8.0 themselves. `.gitignore` is conservative
(`*.bin`, `*.img`, `*.vmdk`, `output/`, `qnx800/`) to make accidental
commits of QNX-derived artifacts very hard.

---

### F5. Open empirical questions for Phase 1 (cloud twin)

These are not blockers — they are validation items that will be
answered by running the cloud-twin toolchain end-to-end in Phase 1.

- [ ] Does `mkqnximage` SDP 8.0 default to **virtio-mmio** or **virtio-pci**
      transports? Affects the Linux-side device-tree / QEMU args.
- [ ] Does an aarch64 IFS built on x86_64 boot under KVM-on-Graviton without
      modification? (Theoretically yes per F1; Phase 1 confirms.)
- [ ] What is the QNX boot time on Graviton under KVM? (Establishes a
      baseline for any later real-time / latency framing.)
- [ ] Does `joexue/qemu-virt`'s missing PCI support matter for Phase 2 IPC
      (virtio-net-mmio is sufficient if so)?

> **2026-09-11 outcomes.** Transport (the first question): virtio-mmio.
> The `mkqnximage --type=qemu` image expects its virtio devices at fixed
> virtio-mmio slots, assigned in `-device` order
> ([findings.md](findings.md) 2026-07-28, Orin TCG networking entry).
> Q2 and Q3 (boot and boot time on Graviton under KVM): moot as asked,
> since no IFS ran on Graviton (F3). The x86_64-built IFS boots under TCG
> on the Windows PC and on the Orin, and its boot time was measured under
> TCG on both ([digital-twin-design.md](digital-twin-design.md) §5, now
> architecture A2 history). Q4 (community-BSP PCI): UNKNOWN. No recorded
> run used `joexue/qemu-virt`, and Phase 2 IPC ran over the `qvm`
> virtio-console vdev instead ([ADR-002](phase2-topology-decision.md) §3.1).

**Note — there is no separate Windows-vs-EC2 build-equivalence
question.** An earlier draft of this section had one (and the
2026-05-07 amendment in [findings.md](findings.md) called for one);
both were over-specified. The IFS target is aarch64; `mkqnximage`
cross-compiles to it from any supported x86_64 host; the build host
itself does not run any guest. Per F1's arch-agnostic-IFS argument,
swapping Windows for Linux x86_64 on the build host affects only
build metadata (embedded paths, timestamps), not the ARM code QNX
boots. Q2 above already validates that *any* x86_64-built IFS boots
on Graviton — that question is host-platform-agnostic and covers the
load-bearing claim. The 2026-05-07 [findings.md](findings.md) caveat
is corrected in the same commit that drops this question. **(2026-09-11:
Q2 never ran on Graviton; the evidence that an x86_64-built IFS boots is
from TCG on the Windows PC and the Orin, per the outcomes note above.)**

---

### F6. Hardware twin BSP question (Phase 3)

The hardware-twin claim rests on a single load-bearing assertion:
**the same `mkqnximage --type=qemu --arch=aarch64le` IFS that runs on
QEMU-on-Graviton also runs unchanged on QEMU-on-Orin-Nano.** This is
plausible — QEMU's `virt` machine model is host-CPU-agnostic so long as
the host CPU implements the required ARMv8 features (which Cortex-A78AE
does) — but it has not been validated empirically.

> **2026-09-11 outcome (2026-07-28).** Validated under TCG: the unchanged
> Phase-1 `ifs.bin` and `disk-qemu` booted on the Orin
> ([orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)),
> so no fallback below was needed for that boot. Under KVM the same pair
> hangs after `FOUND GICv3 ITS` on the GICv3/NISV defect
> ([orin-port.md](orin-port.md) risk register). The Orin IPC run then used
> a rebuilt IFS ([orin-port.md](orin-port.md) step 4).

Phase 3 first task is to verify this end-to-end. If it works, Phases
3 and 4 proceed as planned. If it does not, the fallback options in
order of effort are:

1. **Tweak QEMU args on Orin** to mask any A78AE-specific feature the
   IFS does not expect. Cheap if it works.
2. **Rebuild the IFS** with explicit Cortex-A78AE-aware flags via
   `mkqnximage` options. Moderate effort; still on the official
   toolchain path.
3. **Switch the hardware twin** to the `joexue/qemu-virt` community BSP
   (already on the Phase 2+ study path), which gives source-level
   visibility into any platform-specific patches needed. Highest effort
   but also highest learning value — and a real BSP-engineering story.

Open empirical questions for Phase 3:

> **Research note (2026-05-07, re-fetch pass):** WebFetch / WebSearch
> tools were available this session and the four citations below were
> re-validated against primary sources. Q2 (JetPack 6 = Ubuntu 22.04 +
> kernel 5.15) and Q3 (Orin Nano Dev Kit = 8 GB LPDDR5) are now
> empirically confirmed from NVIDIA docs. Q1 architecture claims
> (A78AE = ARMv8.2-A) are confirmed from public Arm/Wikipedia sources,
> but the QEMU virt master docs **do not** word-for-word back the
> "host-CPU-agnostic under KVM" wording the prior agent used —
> verdict caveated below. Q4 stays "leans no" but is now backed by an
> NVIDIA developer-forum thread showing a JetPack 6.2 user manually
> turning on VHOST_NET via menuconfig (a stronger signal than upstream
> Kconfig defaults). Empirical-check steps for Phase 3 are unchanged.

- **Q1 — Does the cloud-twin IFS boot unchanged under QEMU-on-Orin
  (KVM enabled, GICv3, A78AE host CPU)? Load-bearing.**
  **Verdict: likely, with one specific risk to watch.** QEMU's `virt`
  machine model is host-CPU-agnostic when run under KVM as long as the
  host implements ARMv8.0-A + GICv3 + EL2; Cortex-A78AE is ARMv8.2-A
  with GICv3/v4 and EL2, which is a strict superset. The Graviton3
  (Neoverse-V1, ARMv8.4-A) and Orin's A78AE both pass `-cpu host` to
  the same `mkqnximage` IFS, and the IFS only sees the QEMU virt
  device tree, not the host CPU's microarchitectural details. The one
  realistic risk is QNX's microkernel CPU-feature probe rejecting an
  unfamiliar MIDR/REVIDR pair from the A78AE (QNX SDP 8.0 was
  validated against a small set of reference CPUs). Note: QEMU's
  master `virt` machine doc does not phrase the cross-host claim as
  "host-CPU-agnostic" word-for-word — it documents `-cpu host` support
  under KVM but warns it is not migration-stable; Phase 3 step 5 is
  still the empirical proof, not the doc. Citations:
  [Arm Cortex-A78AE TRM — ARMv8.2-A, GICv3, EL2 support](https://developer.arm.com/documentation/101779/latest/)
  **[verified 2026-05-07 via developer.arm.com + en.wikipedia.org/wiki/ARM_Cortex-A78 cross-check: A78 family = ARMv8.2-A; arm.com product page confirms Armv8-A CPU, GIC-600AE compatible (GICv3/v4), EL2 hypervisor support]**;
  [QEMU virt machine docs — `-cpu host` supported under KVM/HVF](https://www.qemu.org/docs/master/system/arm/virt.html)
  **[verified 2026-05-07 via qemu.org; doc supports `-cpu host` under KVM but does not assert host-CPU portability — caveat above]**.
  **Empirical confirmation:** Phase 3 step 5 — `scripts/orin/launch-qnx-on-orin.sh`
  with the cloud-twin `output/ifs.bin`; pass if QNX reaches its
  shell prompt and `pidin sysinfo` reports a sane `cycles_per_sec`.
  **Outcome (2026-07-28; noted 2026-09-11): not under KVM.** The IFS
  hangs after `FOUND GICv3 ITS`: a post-indexed store on a GICv3
  distributor register takes a `KVM_EXIT_ARM_NISV` exit that neither KVM
  nor QEMU emulates. That is not the MIDR/REVIDR risk named above
  ([orin-port.md](orin-port.md) risk register), and the same hang
  reproduced on `a1.metal` ([findings.md](findings.md) 2026-07-29). Under
  TCG the unchanged IFS boots
  ([orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)).
  The `pidin sysinfo` check was not done ([orin-port.md](orin-port.md)
  step 5).

- **Q2 — Does JetPack 6 ship `qemu-system-aarch64` with KVM support
  enabled out of the box, or does it need a custom build?**
  **Verdict: likely yes — stock Ubuntu 22.04 QEMU is sufficient.**
  JetPack 6 is built on an Ubuntu 22.04 base userspace. Ubuntu's
  upstream `qemu-system-arm` package (`qemu-system-aarch64`) is
  compiled with KVM acceleration enabled for arm64 hosts; nothing
  Jetson-specific gates that. The KVM enablement question on Jetson
  is at the *kernel* layer (CONFIG_KVM, EL2 boot) rather than the
  QEMU-package layer. Citations:
  [Ubuntu ARM64/QEMU wiki — `-enable-kvm` example for arm64 host](https://wiki.ubuntu.com/ARM64/QEMU)
  **[verified 2026-05-07 via wiki.ubuntu.com; documents the `-enable-kvm` invocation on arm64 hosts running Ubuntu 20.04+, which covers jammy. Note: the `packages.ubuntu.com/jammy/qemu-system-arm` page itself does not surface KVM build flags in its visible metadata, so this Ubuntu-server wiki is the closer primary source]**;
  [NVIDIA JetPack 6.0 release notes — Ubuntu 22.04 + kernel 5.15](https://docs.nvidia.com/jetson/archives/jetpack-archived/jetpack-60/release-notes/index.html)
  **[verified 2026-05-07 via docs.nvidia.com; quote: "JetPack 6.0 production release includes Jetson Linux 36.3 which packs Linux Kernel 5.15 and Ubuntu 22.04 based root file system." The current `developer.nvidia.com/embedded/jetpack` landing page now advertises JetPack 7 / Ubuntu 24.04, so the archived 6.0 release notes are the authoritative cite for this project's Orin twin]**.
  **Empirical confirmation:** Phase 3 step 2 — after
  `apt-get install qemu-system-arm`, run
  `qemu-system-aarch64 -accel help` and confirm `kvm` is listed; then
  `qemu-system-aarch64 -M virt,accel=kvm -cpu host -smp 1 -m 256 -nographic`
  starts without "KVM not available" errors.
  **Outcome (2026-07-28; noted 2026-09-11): yes.** The stock
  `qemu-system-aarch64` is 6.2.0, `/dev/kvm` is usable, and a bare vGIC
  smoke test ran clean ([orin-port.md](orin-port.md) step 2). The later
  QHV-in-TCG leg needed a from-source QEMU for an unrelated EL2
  virtual-timer defect ([orin-port.md](orin-port.md) risk register).

- **Q3 — Does the Orin Nano's 8 GB RAM accommodate L4T (~3 GB) +
  QEMU(QNX, 1 GB) + benchmark workload comfortably?**
  **Verdict: likely yes, but tight; expect ~3 GB headroom not 4 GB.**
  NVIDIA's own JetPack 6 documentation reports L4T idle RSS at
  roughly 2.5–3.5 GB depending on whether the desktop session is
  running (headless reduces this by ~800 MB). With QEMU configured at
  1 GB for the QNX guest (plus ~200 MB QEMU overhead) and the
  `linux-client` benchmark binary's RSS measured in tens of MB, total
  steady-state usage should be ~4.5 GB, leaving ~3.5 GB free — enough
  for kernel buffers and the network bridge but not enough to also
  run a desktop session and a browser. The mitigation already noted
  in the risk register (`scripts/orin/launch-qnx-on-orin.sh` boots
  QNX with `-m 768` if needed) is sound. Note: the L4T r36.3 release
  notes PDF re-fetched on 2026-05-07 does **not** publish an idle-RSS
  figure — the 2.5–3.5 GB number above is community-folklore-level and
  must be measured empirically in Phase 3 step 1, not cited as a vendor
  baseline. Citations:
  [Jetson Orin Nano Super Developer Kit product page — 8 GB 128-bit LPDDR5 / 102 GB/s](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/nano-super-developer-kit/)
  **[verified 2026-05-07 via nvidia.com; quote: "8GB 128-bit LPDDR5 102 GB/s". The original `developer.nvidia.com/embedded/jetson-orin-nano-developer-kit` URL now returns 404 — replaced with this nvidia.com product-page URL which carries the same spec]**;
  [JetPack 6 / L4T r36.3 release notes (PDF)](https://docs.nvidia.com/jetson/archives/r36.3/ReleaseNotes/Jetson_Linux_Release_Notes_r36.3.pdf)
  **[contradicts prior agent claim: re-fetched 2026-05-07 — the r36.3 release notes do NOT contain idle-RSS / system-memory-footprint guidance. The figure must be measured in Phase 3 step 1, not cited as vendor data]**.
  **Empirical confirmation:** Phase 3 step 1 — `free -h` after a
  fresh boot to a headless tty (target ≥4.5 GB free), then `free -h`
  again with QNX QEMU running and the 100k-iteration benchmark in
  flight (target ≥1 GB free, no swap usage).
  **Outcome (noted 2026-09-11): partly checked.** A `free -h` reading
  was recorded at Phase 3 step 1 ([orin-port.md](orin-port.md)), and the
  long Orin IPC runs completed without errors (step 6). A reading with
  QEMU running and the benchmark in flight was not recorded (UNKNOWN).

- **Q4 — Is the L4T kernel's `vhost-net` path enabled? (Affects
  virtio-net latency on the hardware twin.)**
  **Verdict: uncertain — leans no; budget for a custom kernel module
  or live with userspace virtio.** The mainline JetPack 6 kernel
  config historically does *not* enable `CONFIG_VHOST_NET=m` by
  default — NVIDIA's L4T defconfig is tuned for the embedded /
  inference workload, not for hosting Linux VMs, and `vhost_net` is
  not on the validated module list in r36.x. It is enabled in
  upstream Linux defconfig and is straightforward to build as an
  out-of-tree module against the L4T kernel sources, but the
  user-friction is non-trivial (kernel header install + kernel
  rebuild). This will likely manifest as a measurable but not
  catastrophic latency delta in the twin diff (userspace virtio adds
  ~20–50 µs per round-trip vs. vhost-net based on published
  comparisons). Citations:
  [NVIDIA developer forum — JetPack 6.2 user enabling VHOST_NET via kernel rebuild](https://forums.developer.nvidia.com/t/network-driver-error-when-recompiling-the-kernel-on-jetpack-6-2/328693)
  **[verified 2026-05-07 via forums.developer.nvidia.com; the thread shows a JetPack 6.2 user manually flipping `<M> Host kernel accelerator for virtio net` in menuconfig, which is the strongest available signal that VHOST_NET is not on by default in the L4T tegra_defconfig. Direct gitweb browsing of `linux-nvidia.git` defconfig was attempted but the URL is not WebFetch-friendly — the forum thread is the cleanest primary indirect proof]**;
  [Linux kernel `drivers/vhost/Kconfig` — VHOST_NET upstream default](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/vhost/Kconfig)
  **[verified pattern from upstream — unchanged from prior pass]**.
  **Empirical confirmation:** Phase 3 step 2 — on the Orin after
  flashing, `zcat /proc/config.gz | grep -E 'VHOST_NET|VHOST='` (or
  inspect `/boot/config-$(uname -r)`); if absent, `modprobe vhost_net`
  fails and the twin-diff doc records this as a known gap.
  **Outcome (noted 2026-09-11): UNKNOWN.** No check of `vhost-net` on the
  board is recorded; the [orin-port.md](orin-port.md) risk-register row
  has no outcome.

---

### F7. Real-EL2 QNX Hypervisor time — Sweep C for ADR-003 (other credible routes, and the measurement side)

> **Research note (2026-09-09, Sweep C for ADR-003; read-only, no
> purchases / AWS calls / ssh).** Context: the QHV leg boots only under
> QEMU TCG (emulated EL2) on two hosts (findings.md 2026-09-09), so it
> cannot yield a hardware-timed hypervisor number. Sweeps A (Marketplace
> AMI / Graviton metal) and B (native Orin port) are covered elsewhere;
> this section answers "what *else* is credible for an Everywhere-licence
> user with an Orin Nano and a 32-vCPU AWS account, and how would QNX
> itself measure it". Facts taken as given from the repo and not
> re-derived: the local SDP 8.0 install ships only the two
> `hypervisor_guest_arm/x86` BSPs; `mkqnximage` has no AWS target; QHV 8.0
> lists NXP i.MX8QM, AWS Graviton2 and Intel Raptor Lake as supported
> host platforms with "contact your QNX representative" for others;
> non-metal Graviton has no `/dev/kvm`; `a1.metal` gave real EL2/KVM
> once; the 32-vCPU quota blocks 64-vCPU metal types. Everything below
> is **asserted by vendor / docs** unless marked *verified empirically*;
> nothing here was run.

- **Q1 — Which other aarch64 platforms can an Everywhere-licence user
  actually buy and boot QNX Hypervisor 8.0 on, natively (real EL2)?**
  **Verdict: exactly one officially documented, Everywhere-licensed path
  exists — Raspberry Pi 4 Model B — and it is the non-VHE (`el1-host`)
  topology, not the VHE one the TCG leg runs.** QNX’s own
  `gitlab.com/qnx/hypervisor/getting-started` (created 2025-12-01,
  "Getting started with Hypervisor 8.0 on Raspberry Pi 4") states:
  "The QNX Everywhere license (perpetual non-commercial) includes an
  entitlement to QNX Hypervisor 8.0"; "At this time, the QNX-supplied Pi 4
  BSP does not include a hypervisor build file variant", so the guide
  edits the stock BSP build file — its boot line is
  `startup-bcm2711-rpi4 -v -D miniuart -W 2500 -u reg -r 0,4096,1 -Q enable,el1-host`
  — and explains: "In the above configuration we are running the
  hypervisor host in EL1 (non-VHE). The QNX Hypervisor supports VHE mode
  (el2-host) but there are limitations with the VHE-enabled subsystems on
  the Pi 4. Therefore, we are running in non-VHE on this hardware."
  (Cortex-A72 is ARMv8.0-A, which has no VHE at all — QNX’s phrasing is
  softer than the architecture.) Per the QNX `startup-*` reference,
  `-Q enable,el1-host` = "enable hypervisor features and run the host at
  EL1", `-Q enable,el2-host` = "force Virtualization Host Extensions (VHE)
  support ... If the hardware does not support EL2-Host virtualization,
  startup is aborted"; the hypervisor itself occupies hardware EL2 in
  either mode, so a Pi 4 number is a genuine hardware-EL2 number — but of
  a different topology from the leg measured so far (findings.md
  2026-09-09 attributes the QEMU 6.2 hang to the VHE timer path, and the
  `-cpu cortex-a57` non-VHE control behaved differently). The guide boots
  a QNX 8.0 guest from the `hypervisor_guest_arm` BSP samples
  (`qnx800-guest-1.ifs` + `.qvmconf`, `startup-armv8_fm`) and a Linux
  guest. An independent community repo (EhabMagdyy/QNX-Hypervisor) shows
  the same recipe reaching "Welcome to QNX 8.0.0 on ARMv8_Foundation_Model!"
  on a Pi 4B — cross-check, not vendor. Candidate table:

  | Platform | QHV 8.0 host status | Everywhere BSP / package | Price and availability (2026-09-09) |
  |---|---|---|---|
  | **Raspberry Pi 4 Model B** (BCM2711, 4x Cortex-A72, ARMv8.0, no VHE) | Official QNX guide; `-Q enable,el1-host` | `com.qnx.qnx800.bsp.hw.raspberrypi_bcm2711_rpi4`, build 484 (2026-01-15); 1 GB variant explicitly unsupported | Raspberry Pi list price 2025-12-01: 4 GB **$60**, 8 GB **$85** (memory-driven rise; resellers seen at $120–190) |
  | **Raspberry Pi 5** (BCM2712, 4x Cortex-A76, ARMv8.2, VHE-capable) | **No QNX hypervisor documentation found**; blog / press name only the Pi 4B for QHV | `com.qnx.qnx800.bsp.hw.raspberrypi_bcm2712_rpi5`, build 381 (2026-01-15); Screen / Mesa packages cover "Raspberry Pi 4 and 5" | Raspberry Pi list price 2025-12-01: 4 GB $70, 8 GB $95, 16 GB $145; "in production until at least January 2036" |
  | **NXP i.MX 8QuadMax MEK** (MCIMX8QM-CPU) | The *only* buyable board on the official QHV 8.0 supported list | `com.qnx.qnx800.bsp.hw.nxp_imx8qm_mek`, build 489 (2026-01-28); release notes say nothing about hypervisor; whether the Everywhere-visible zip carries a `*-hypervisor.build` (`make hyp`) variant is **unverified** | NXP list **$1,206.35**, status "Pending Stock" |
  | Toradex Apalis iMX8QM + Ixora | Same SoC as the MEK; not on the QHV list by name | `com.qnx.qnx800.bsp.hw.apalis_imx8qm`, build 365 (2026-01-28); no hypervisor mention | Price not extracted (only 2018 press figures found) |
  | NXP i.MX 8M Plus EVK (8MPLUSLPD4-EVK) | Not on the QHV 8.0 list | `com.qnx.qnx800.bsp.hw.nxp_imx8mp` exists; no hypervisor mention | NXP list $683.20, "Pending Stock" |
  | AWS Graviton2 (c6g / m6g) | On the official QHV 8.0 list | **No Graviton BSP in the public 8.0 BSP catalogue**; the "QNX Software in the Cloud" notes cover the *QNX OS 8.0* AMI only, hypervisor not mentioned | See Sweep A and Q4 |
  | Jetson Orin Nano (Tegra234, A78AE) | Not on the list; no BSP for Everywhere users | — | See Sweep B |

  **Guest-compatibility flag (needs the toolchain):** findings.md
  2026-09-09 records the `hypervisor_guest_arm` guest aborting with
  `PE does not support PAUTH feature` under `-cpu cortex-a57` (no PAUTH),
  yet the QNX Pi 4 guide and the community log boot that same
  `startup-armv8_fm` guest on Cortex-A72, which also lacks PAUTH. Either
  the check is specific to the QEMU `cortex-a57` model, or the sample
  guest build differs from the project’s; unresolved without running it.
  Citations:
  [QNX getting-started: Hypervisor 8.0 on Raspberry Pi 4 (README, rpi4-hypervisor.build)](https://gitlab.com/qnx/hypervisor/getting-started)
  **[verified 2026-09-09 via gitlab.com raw README + build file line 11; quotes above verbatim]**;
  [QNX blog 2026 — Free Access to QNX Hypervisor with QNX Everywhere](https://qnx.software/en/blog/2026/free-access-to-qnx-hypervisor-with-qnx-everywhere)
  **[verified 2026-09-09; names only "a Raspberry Pi 4B"; no date on the page — the 2026-01-06 press release below dates it]**;
  [QNX press release 2026-01-06 — "free access to QNX SDP 8.0 and QNX Hypervisor 8.0 for non-commercial use"](https://qnx.software/en/press-release/2026/qnx-everywhere-expands-global-developer-ecosystem-through-education-innovation-and-open-collaboration)
  **[verified 2026-09-09]**;
  [startup-* options — -Q enable / enable,el1-host / enable,el2-host](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/s/startup_options.html)
  and [Configuring the hypervisor host](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/config/hyp.html)
  **[verified 2026-09-09; "el2-host ... the host runs at EL2 at all times"; "el1-host ... runs the host OS at EL1"; "ARMv8.1 and later CPUs support el2-host"]**;
  [QHV 8.0 GA release notes — supported platforms](https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/hypervisor8.0_rn.html)
  **[verified 2026-09-09; AArch64: NXP i.MX8QM, AWS Graviton2; x86-64: Intel Raptor Lake; "For information about support for specific boards, contact your QNX representative"]**;
  BSP release notes: [Pi 4](https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.broadcom.rpi4.bcm2711.html),
  [Pi 5](https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.broadcom.rpi5.bcm2712.html),
  [i.MX8QM MEK](https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.nxp.i.mx8qm.cpu.html),
  [Apalis iMX8QM](https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.apalis.imx8qm.html)
  **[all verified 2026-09-09; none mentions hypervisor / qvm / EL2]**;
  [NXP MCIMX8QM-CPU product page](https://www.nxp.com/design/design-center/development-boards-and-designs/i-mx-evaluation-and-development-boards/i-mx-8quadmax-multisensory-enablement-kit-mek:MCIMX8QM-CPU)
  **[verified 2026-09-09; $1,206.35, "Pending Stock"; lists "QNX SDP 8.0 BSP for NXP i.MX 8 QuadMax MEK" as a partner offering]**;
  [Raspberry Pi news 2025-12-01 — memory-driven price rises](https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/)
  **[verified 2026-09-09; secondary press (tomshardware.com) reports a further 2026 rise — not confirmed on raspberrypi.com]**;
  [EhabMagdyy/QNX-Hypervisor — community Pi 4B run](https://github.com/EhabMagdyy/QNX-Hypervisor)
  **[independent cross-check of the vendor guide]**.
  **Empirical confirmation:** buy a Pi 4B (4 or 8 GB), install
  `com.qnx.qnx800.target.hypervisor.group` + the Pi 4 BSP, build the
  guide’s `rpi4-hypervisor.build`, boot; pass if the host comes up with
  hypervisor features enabled and `qvm` launches the sample guest; then
  re-point the project’s `qnx-guest` IFS at it and record whether the
  PAUTH abort reproduces on real A72.

- **Q2 — Does QNX ship hypervisor *host* packages to Everywhere users at
  all, and under what names?**
  **Verdict: yes, since 2026-01-06 — but there is no BSP_hyp-* product
  line in 8.0; host support is a startup flag plus the hypervisor group
  package, and board-specific "hypervisor variant" build files exist only
  inside some (unenumerated) board BSPs.** Software Center packages named
  in primary sources: group `com.qnx.qnx800.target.hypervisor.group` (the
  GA notes say the group install delivers "Hypervisor Core
  (com.qnx.qnx800.target.hypervisor.core)" and "Hypervisor Extras
  (com.qnx.qnx800.target.hypervisor.extras)"), plus the guest BSPs
  `com.qnx.qnx800.bsp.hypervisor_guest_arm` / `_x86` (the two the local
  install already shows — they "do not contain host support"). QNX build
  docs: "QNX provides some BSPs that contain a hypervisor variant of the
  buildfile" (built with `make hyp`; a search excerpt names
  `imx8qm-cpu-mek-hypervisor.build` as the example — excerpt only, not
  re-read on the page), and "If there is no QNX-supplied BSP that
  contains a hypervisor buildfile variant and is compatible with your
  target hardware, you must modify one of the buildfiles that comes with
  the BSP that supports your hardware to include the hypervisor
  components." Which 8.0 BSPs carry the variant is not listed anywhere
  public; the Pi 4 one explicitly does not. The QNX Everywhere release
  notes (through 0.4.0, 2026-06-19) list SDP 8.0.4, Quick Start images
  for "Raspberry Pi 4 and 5" and QEMU x86_64, and do not mention the
  hypervisor as a component — the entitlement is stated in the blog,
  press release and README, not in the Everywhere notes. Citations:
  [QHV 8.0 GA release notes](https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/hypervisor8.0_rn.html)
  **[verified 2026-09-09]**;
  [QHV 8.0 product-update notes (build 549, 2025-06-12)](https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qh8.0_prod_release_notes/qh8.0_updates.html)
  **[verified 2026-09-09; no new host platforms named]**;
  [Methods of building a QNX Hypervisor system](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/build/build_methods.html)
  and [Building the host](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/build/build_host.html)
  **[verified 2026-09-09; host build needs qvm, per-VM *.qvmconf, vdev-*.so, SMMU service + libs]**;
  [QNX Everywhere release notes](https://www.qnx.com/developers/docs/qnxeverywhere/rel_notes.html)
  **[verified 2026-09-09]**.
  **Empirical confirmation:** in QNX Software Center, Available →
  "QNX Hypervisor > Products", install the 8.0 group package, then
  `unzip -l` each installed board BSP and grep for `-hypervisor.build` —
  the only way to enumerate which BSPs carry a host variant.

- **Q3 — What does QNX itself document for measuring hypervisor overhead
  / guest latency, so the number is one QNX engineers would recognise?**
  **Verdict: the documented instrument is the QNX kernel trace of the
  `qvm` process (Class 10 events) analysed with tracelogger / System
  Profiler, and the documented methodology is a native-vs-virtual
  benchmark delta plus a full hypervisor-event recording — there is no
  qvm statistics switch in the docs.** Specifics, all from the QHV 8.0
  User’s Guide: (1) "Most qvm trace events are Class 10 events"; IDs 0
  Guest Entry, 1 Guest Exit, 2 Create vCPU Thread, 3 / 4 Assert /
  De-assert Interrupt, 5 / 6 Create / Trigger Virtual Timer, **7 Guest
  Clock Cycles** ("Guest clock cycle values at guest entry and exit").
  (2) "the timestamp for the ID 0 event should *not* be used to calculate
  the time spent in the guest" (the vCPU thread can be preempted between
  exit and re-entry); use the ID 7 `at_entry` / `at_exit` values, convert
  with `clockcycles_offset` from the ID 1 event ("set during qvm startup
  and never changes"; Host TSC = Guest TSC - clockcycles_offset), and
  compute **% time in guest = time in guest / total vCPU-thread RUNNING
  time**. (3) The trace, per the doc, does not and cannot show what is
  going on inside the guest — guest-internal latency needs the guest’s
  own tracelogger (the project’s `ipc-test` timing stays guest-side).
  (4) Performance-tuning chapter: top-down = "compare performance
  benchmarks from a native system (N) against the same benchmark running
  in a VM (V)" then vary the VM configuration; bottom-up = "record every
  hypervisor event over a specific time interval". (5) Cost anchors: a
  hypervisor → guest NOP → hypervisor round trip is "three to ten
  microseconds, depending on the SoC"; "when a hardware device asserts an
  interrupt for a guest, the hypervisor must always intervene"; "accessing
  privileged or device registers requires guest exits, and thus incurs
  significant additional overhead". (6) The QNX "Hypervisor Benchmarking"
  white paper is gated behind a registration form and was **not** read;
  its landing page lists virtual-vs-native core performance, vCPU
  migration consistency, jitter in host and guest, and para-virtualized
  driver impact as its themes. (7) The Pi 4 sample build file installs
  `[+optional] /bin/qvm-check` — no documentation for it was found. So a
  QNX-recognisable measurement set is: guest-exit count and per-exit cost
  from the Class 10 trace; the N-vs-V delta of one benchmark run natively
  on the host and again in a guest; and the existing IPC round trip
  re-run with the host trace active so host time and guest time are
  attributed separately. Citations:
  [Getting hypervisor trace information](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/debug/trace.html),
  [Hypervisor trace events](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/debug/trace_events.html),
  [Comparing guest and host timelines](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/debug/tsc.html),
  [Overhead in a virtualized environment](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/perform/overhead.html),
  [Guest exits](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/perform/guest_exits.html),
  [Interrupts](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/perform/irqs.html),
  [Performance Tuning (chapter index)](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/perform/perform.html)
  **[all verified 2026-09-09; quotes verbatim]**;
  [Hypervisor Benchmarking white paper (gated)](https://qnx.software/en/wp/hypervisor-benchmarking)
  **[landing page only]**.
  **Empirical confirmation:** on any real-EL2 host, run tracelogger with
  Class 10 enabled while the guest executes the IPC benchmark, then
  confirm in System Profiler that ID 7 events carry non-zero
  `at_entry` / `at_exit` and that the % time-in-guest formula reproduces.
  Under TCG this same trace can be captured today for a *shape* baseline
  (it cannot give a hardware time).

- **Q4 — AWS: cheapest Graviton *metal* types, vCPU counts vs the 32-vCPU
  quota, how to raise it, eu-central-1 prices — and is nested KVM a
  route?**
  **Verdict: `a1.metal` (16 vCPU, Graviton1 / Cortex-A72, about $0.47/h
  in Frankfurt) is the only Graviton metal type that fits a 32-vCPU
  quota; every newer Graviton metal is 64 vCPU or more and needs the
  quota roughly doubled; nested KVM on c7g / c8g metal is
  hardware-possible but experimental and would not be a bare-metal number
  anyway.** Data (Linux On-Demand, USD/h, EU (Frankfurt), from the AWS
  price feed dated 2026-09-09 unless marked):

  | Type | CPU | vCPU | Frankfurt $/h | us-east-1 $/h | Fits 32-vCPU quota? |
  |---|---|---|---|---|---|
  | a1.metal | Graviton1, Cortex-A72 (ARMv8.0, no VHE, no NV) | 16 | **0.466** (secondary: aws-pricing.com, instances.vantage.sh; the a1 family is absent from the AWS current-generation feed) | 0.408 | **yes** |
  | c6g.metal | Graviton2, Neoverse N1 (ARMv8.2) | 64 | 2.4832 | 2.1760 | no |
  | c7g.metal | Graviton3, Neoverse V1 (ARMv8.4) | 64 | 2.6384 | 2.3200 | no |
  | m6g.metal / m7g.metal | Graviton2 / 3 | 64 | 2.9440 / 3.1283 | 2.4640 / 2.6112 | no |
  | c8g.metal-24xl | Graviton4, Neoverse V2 (ARMv9.0) | 96 | 4.3536 | 3.8285 | no |
  | c8g.metal-48xl | Graviton4 | 192 | 8.7072 | 7.6570 | no |

  The AWS compute-optimized and general-purpose instance-type tables show
  **no Graviton bare-metal size below 64 vCPUs** other than a1.metal; a1
  is listed as available in eu-central-1 (Previous Generation). The quota
  is "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances"
  (code **L-1216C47A**), counted in vCPUs "regardless of the instance
  type" (default 5; this account’s 32 is already an increase); increase
  via Service Quotas console → EC2 → filter "On-Demand" → "Request quota
  increase", or the CLI per the Service Quotas User Guide; a c7g.metal
  needs the quota at 64 or more. **Nested KVM:** upstream
  `kvm-arm.mode=nested` is "VHE-based mode with support for nested
  virtualization. Requires at least ARMv8.4 hardware (with FEAT_NV2)" and
  is "experimental and should be used with extreme caution";
  `KVM_ARM_VCPU_HAS_EL2` boots "the guest from EL2 instead of EL1" with
  E2H RES1 (VHE) unless `KVM_ARM_VCPU_HAS_EL2_E2H0`. The Arm TRMs confirm
  the silicon side: Neoverse V1 `ID_AA64MMFR2_EL1.NV = 0x2` ("The VNCR_EL2
  register and the HCR_EL2.{AT,NV,NV1,NV2} bits are implemented") and
  Neoverse V2 `NV = 0b0010`; Graviton1 (A72) and Graviton2 (N1, ARMv8.2)
  have no NV. So c7g.metal / c8g.metal could in principle host QHV as an
  L1 hypervisor under a new-enough Linux — but that is a *nested*,
  trapped-EL2 number, needs the quota raise and a kernel that ships the
  mode, and would inherit the same startup GICv3 / NISV exposure under
  KVM that blocks the plain guest today (findings.md 2026-07-29).
  Citations:
  [AWS price feed, EU (Frankfurt), Linux on-demand (JSON, publication 2026-09-09)](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/EU%20(Frankfurt)/Linux/index.json)
  **[verified 2026-09-09 by download + grep; a1 not present]**;
  [aws-pricing.com a1.metal](https://aws-pricing.com/a1.metal.html) and
  [instances.vantage.sh a1.metal](https://instances.vantage.sh/aws/ec2/a1.metal)
  **[secondary; both 0.466 for eu-central-1]**;
  [EC2 compute-optimized specs (c6g / c7g / c8g metal)](https://docs.aws.amazon.com/ec2/latest/instancetypes/co.html),
  [general-purpose specs (m6g / m7g / m8g metal)](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html),
  [instance types by Region (a1 in eu-central-1)](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html)
  **[verified 2026-09-09]**;
  [EC2 instance type quotas (L-1216C47A)](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html),
  [On-Demand quotas and increase requests](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html),
  [Amazon EC2 service quotas](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html)
  **[verified 2026-09-09]**;
  [Linux kernel-parameters.txt — kvm-arm.mode=nested](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/admin-guide/kernel-parameters.txt)
  and [KVM API — KVM_ARM_VCPU_HAS_EL2](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/virt/kvm/api.rst)
  **[verified 2026-09-09 by download + grep]**;
  [Arm Neoverse V1 TRM r1p2 (ID_AA64MMFR2_EL1.NV)](https://documentation-service.arm.com/static/64be968738511951cb7a087a)
  and [Neoverse V2 TRM r0p2 mirror](https://www.scs.stanford.edu/~zyedidia/docs/arm/neoverse_v2_trm.pdf)
  **[verified 2026-09-09 by pdftotext + grep]**.
  **Empirical confirmation:** none needed for prices / quota (read from
  AWS); for nested KVM, on a c7g.metal booted with `kvm-arm.mode=nested`
  on a kernel that has it, check dmesg for the nested-mode line — but
  this sits behind the quota raise and is *not* recommended as the
  ADR-003 answer.

- **Looked for and not found (Sweep C):** any QNX statement that the
  hypervisor runs on Raspberry Pi 5; a public list of which 8.0 BSPs
  carry a `*-hypervisor.build` variant; a Graviton or AWS entry in the
  public 8.0 BSP catalogue; any hypervisor mention in the QNX OS 8.0 AMI
  ("QNX Software in the Cloud") release notes; the a1 family in the AWS
  current-generation price feed (only third-party mirrors give the
  Frankfurt rate); documentation for `qvm-check`; the content of the QNX
  Hypervisor Benchmarking white paper (registration-gated); a qvm
  statistics / monitoring option in the qvm reference; current Toradex
  Apalis iMX8QM pricing; the publication date on the QNX blog post itself
  (dated by the 2026-01-06 press release instead).

---

## Decision

| Item | Choice |
|---|---|
| QNX SDP version | **SDP 8.0** (Everywhere / NCEULA) |
| Host architecture | **Hybrid**: x86_64 build (Windows local primary; EC2 t3.medium fallback) + arm64 runtime (c7g.large) |
| Phase 1 BSP | **`mkqnximage --type=qemu --arch=aarch64le`** |
| Phase 2+ BSP study | **`joexue/qemu-virt`** (community, MIT) |
| Repo redistribution policy | **Scripts + screenshots + boot logs only.** No QNX binaries. |
| Phase 2 IPC mechanism (default) | **virtio-net via host bridge** (re-evaluate after F5 measurements) |

---

## Rationale

**Why hybrid hosts instead of an x86_64-only setup:** the role this
portfolio targets is BSP / customer-port engineering on **arm64**
silicon (Orin, Thor). Running the runtime side on Graviton arm64 +
KVM is what gives the project narrative authenticity; an x86_64-only
QEMU TCG run would be slower and architecturally off-target. The
build-side x86_64 host is a forced-by-toolchain detail, not a
narrative choice — and that toolchain-constraint discovery is itself
the kind of thing customer-port BSP work surfaces every day.

**Why `mkqnximage` first, community BSP second:** Phase 1's
deliverable is "QNX boots." The lowest-friction official path makes
sense as the baseline. Once boot is validated, Phase 2's BSP-study
work has a known-good reference to compare against, which makes the
community BSP study more grounded.

**Why "scripts + logs" instead of binary distribution:** the NCEULA's
red lines are clear, and a public portfolio has zero appetite for
license risk. Build scripts plus boot logs are sufficient to make the
work reproducible by anyone with their own QNX license.
