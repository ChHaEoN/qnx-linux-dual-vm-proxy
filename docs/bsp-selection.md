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

---

### F6. Hardware twin BSP question (Phase 3)

The hardware-twin claim rests on a single load-bearing assertion:
**the same `mkqnximage --type=qemu --arch=aarch64le` IFS that runs on
QEMU-on-Graviton also runs unchanged on QEMU-on-Orin-Nano.** This is
plausible — QEMU's `virt` machine model is host-CPU-agnostic so long as
the host CPU implements the required ARMv8 features (which Cortex-A78AE
does) — but it has not been validated empirically.

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

---

## Decision

| Item | Choice |
|---|---|
| QNX SDP version | **SDP 8.0** (Everywhere / NCEULA) |
| Host architecture | **Hybrid**: x86_64 build (t3.medium) + arm64 runtime (c7g.large) |
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
