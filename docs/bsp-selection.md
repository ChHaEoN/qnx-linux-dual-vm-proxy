# BSP selection — Phase 0 findings & decision

> **Status:** Phase 0 research complete. Findings 1–4 below are decided;
> Finding 5 lists empirical questions that move into Phase 1 validation.

---

## Findings

### F1. QNX SDP 8.0 does not support ARM hosts

The SDP 8.0 host toolchain ships for x86_64 Linux and macOS only.
`mkqnximage`, `qcc`, and the QNX Software Center will not run on Graviton
arm64. Confirmed via the SDP 8.0 release notes and the QNX Software
Center supported-host matrix.

**Consequence — hybrid build/runtime architecture:**

```
x86_64 build host (t3.medium)  ──ifs.bin / disk-qemu.vmdk──▶  Graviton runtime host (c7g.large)
SDP 8.0 + mkqnximage                  scp                     qemu-system-aarch64 + KVM
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

- [ ] Does the cloud-twin IFS boot unchanged under QEMU-on-Orin
      (KVM enabled, GICv3, A78AE host CPU)? **Load-bearing.**
- [ ] Does JetPack 6 ship `qemu-system-aarch64` with KVM support
      enabled out of the box, or does it need a custom build?
- [ ] Does the Orin Nano's 8 GB RAM accommodate L4T (~3 GB) +
      QEMU(QNX, 1 GB) + benchmark workload comfortably?
- [ ] Is the L4T kernel's `vhost-net` path enabled? (Affects
      virtio-net latency on the hardware twin.)

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
