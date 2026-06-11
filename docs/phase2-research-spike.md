# Phase-2 Research Spike — ADR-002 open questions (RQ-1…RQ-5)

> **Study-level research record.** Resolves the five research questions
> [ADR-002](phase2-topology-decision.md) §5 handed to Research. Evidence is
> tagged **[EMPIRICAL]** (found in the local SDP 8.0.4 install at
> `C:\Users\andy8\qnx800`), **[VENDOR]** (QNX/NVIDIA official docs — a *claim*,
> not independently verified here), or **[SPIKE]** (cannot be settled without a
> runtime/hardware spike). Per the honest-framing rule, vendor claims are not
> upgraded to facts.

- **Date:** 2026-06-11
- **Method:** read-only inspection of the local SDP install (`qvm`, vdev `.so`s,
  `mkqnximage` source, QHV help docs) + primary-source web research.
- **Bottom line:** Option B (dual-guest, QNX + Linux under QHV) is **not blocked**
  on feasibility — both gating unknowns (RQ-1 Linux guest, RQ-3 inter-guest
  channel) resolve positive. The cloud `io-sock` failure (RQ-4) is a fixable
  launch-line omission, not a missing package. Orin KVM (RQ-5) is achievable but
  needs a DTB patch and is unconfirmed on the Orin *Nano* SKU specifically.

---

## RQ-1 — Does `qvm`/`mkqnximage` host an aarch64 **Linux** guest? — **FEASIBLE** (qvm: yes; mkqnximage: no)

| Claim | Tag | Evidence |
|---|---|---|
| QHV 8.0 officially supports **Linux Ubuntu 22.04** as an aarch64 guest (alongside QNX OS 8.0 / QOS 8.0.4) | [VENDOR] | [Supported guest OSs](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/virt/support.html) |
| `mkqnximage` is **QNX-guest-only** — `--type` ∈ {qemu, qvm, vbox, vmware, rasppi}; no `linux`. `--guest=<path>` only embeds another mkqnximage QNX `output/ifs.bin` + `disk-qvm` | [EMPIRICAL] | `host/common/mkqnximage/opt_scripts/opt_guest`, `.../inputs/qvmconf-aarch64le`, `.../qvm.cfg` |
| To include a non-QNX guest you hand-edit `local/data_files.custom` and author the `g2.conf` yourself (verbatim from `opt_guest` help) | [EMPIRICAL] | `opt_guest` help text |
| `qvm`'s `load` directive is image-agnostic (nothing ties it to QNX) | [EMPIRICAL] | as-built `g2.conf` `load …/ifs.bin` in `scripts/qhv/post_start.custom` |
| Exact Linux `g2.conf` shape (kernel `load` addr, dtb, virtio-blk rootfs, ram/cpu) | [SPIKE] | not in the local VM-config reference; QNX ships a worked example → [vdev-shmem Linux example (GitLab)](https://gitlab.com/qnx/hypervisor/working-with-guests/shared-memory-device-example-for-linux-vdev-shmem) |

**Verdict:** the Linux-guest path is real and vendor-supported, but **entirely
hand-rolled** — no tooling produces it. Cost = authoring/building an aarch64
Ubuntu kernel+rootfs and its `g2.conf`, then booting under TCG.

---

## RQ-2 — Richer host↔guest channel than virtio-console, **without** `io-sock`? — **FEASIBLE** (shared-memory vdev)

| Claim | Tag | Evidence |
|---|---|---|
| `vdev-shmem.so` ships for aarch64 — "inter-VM shared memory device", pkg `target.hypervisor.core` 8.0.4 | [EMPIRICAL] | `target/qnx/aarch64le/lib/dll/vdev-shmem.so` |
| It is a `qvm` vdev mediated in EL2 (`create <name>,<size>`, `loc`/`intr` MMIO+doorbell, `sched` notify pulse, allow/deny ACLs) — **no io-sock, no host TCP** | [EMPIRICAL]+[VENDOR] | vdev help; [Using the shmem vdev](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/share/share_mem_vdevshmem.html) |
| **No `virtio-vsock` vdev exists** in SDP 8.0. aarch64 vdev catalogue: `pl011, ser8250, virtio-console, virtio-blk, virtio-net, virtio-entropy, shmem, smmu, wdt-sp805, pci-dummy, progress` | [EMPIRICAL] | vdev `.so` enumeration; vendor support page shows no vsock |

**Verdict:** the Option-A stretch transport (past byte-stream console framing) is
the **shared-memory vdev** (`vdev shmem … loc/intr` in `g2.conf`), not vsock. If
adopted, it must be added to `scripts/qhv/g2.conf.allow` + `vdev.manifest` (a
reviewed config-surface change, per the Phase-1 gate).

---

## RQ-3 — Inter-**guest** channel with host `io-sock` **down**? — **FEASIBLE** (shmem; vdevpeer needs a spike)

| Claim | Tag | Evidence |
|---|---|---|
| `vdev-shmem` is explicitly **guest↔guest** ("all connections … are peers; first attach creates the region"); doorbell fires "when another guest notifies this one" — needs only `qvm` + the shmem vdev in each `g2.conf`, **io-sock-independent** | [EMPIRICAL]+[VENDOR] | shmem vdev help |
| virtio-net between guests rides `qvm_vdevpeer` (`/dev/vdevpeers/vp0`, a native QNX `ConnectAttach` channel) | [EMPIRICAL] | `target/qnx/usr/include/qvm/vdevpeer.h`, `mods-vdevpeer-net.so` |
| …but mkqnximage's `start_guest` wires `vp0` via `ifconfig vp0 create` + `vpctl` — i.e. through the **host io-sock NIC**, exactly what's down on this leg. Whether back-to-back guest↔guest virtio-net can bind peer-to-peer without io-sock is unproven | [SPIKE] | `start_guest`; boot-log `network stack down` |

**Verdict:** **the RQ-3 blocker is removed** — `vdev-shmem` is an io-sock-free
inter-guest channel. So **Option B is gated only by RQ-1's hand-rolled
Linux-guest build effort, not by any missing channel.**

---

## RQ-4 — Can the host `io-sock` / network-stack failure be fixed? — **FIXABLE-CONFIG** (launch-line omission, not a missing package)

The host boot log's `network stack down: Bad file descriptor`,
`vtnet0 does not exist`, `Address family not supported`, **and** the entropy
failure (`Could not initialize entropy` / `PRNG is not seeded`) share **one
root cause**: the QHV-host QEMU command line does not present the virtio devices
the host IFS (built by `mkqnximage --type=qemu`) was provisioned to discover.

| Claim | Tag | Evidence |
|---|---|---|
| The launch line presents only `virtio-blk` — no NIC, no RNG | [EMPIRICAL] | `scripts/launch-qhv-tcg.ps1:38-45` (no `-netdev`/`virtio-net-device`/`virtio-rng`) |
| The host IFS starts `io-sock … -m fdt -d vtnet_mmio`, expecting a virtio-net MMIO NIC discovered via FDT; driver `devs-vtnet_mmio.so` **is present** | [EMPIRICAL] | `…/mkqnximage/inputs/startup.sh:106-108`; `…/snippets/definitions.type_qemu`; driver at `target/qnx/aarch64le/lib/dll/` |
| No virtio-net node in QEMU's FDT → io-sock comes up but finds no interface → the exact logged symptoms | [EMPIRICAL] | symptom-cause match |
| Entropy is a **parallel, independent** failure: `startup.sh:92` runs `random … -l devr-virtio.so:mem=0xa003a00` (a virtio-entropy device at fixed MMIO); the launch presents none → `/dev/random` never appears. **io-sock does NOT depend on the PRNG** — both are the same "missing virtio device" class | [EMPIRICAL] | `startup.sh:92`; `qemu/opt_scripts/qemu:35` |

**Concrete fix:** add `-netdev user,id=n0 -device virtio-net-device,netdev=n0`
and a virtio-rng/virtio-entropy device (at the expected MMIO `loc`) to the
QHV-host QEMU args, matching what `mkqnximage --type=qemu` baked in.
**[SPIKE] caveat:** the exact MMIO `loc`/IRQ for FDT discovery and the
`mem=0xa003a00` entropy binding may need an FDT-dump pass to align on this
`virt,gic-version=3` machine. Same *spirit* as the 2026-06-10 `target.qemuvirt`
finding (provisioning), but here nothing is missing from the install — it is a
launch-script omission.

> **Cross-link — this re-frames the Phase-1 gate entropy finding (FuSa NF-5 /
> Cyber T31 / `TCR-ENT-001`).** The unseeded PRNG is *not* an inherent QNX/TCG
> limitation; it is the absence of a virtio-entropy device on the launch line.
> The fail-secure `entropy-gate.sh` posture remains correct, but the *remediation*
> is now known and cheap (present the RNG device), which should be noted when
> Cyber-Design revisits `TCR-ENT-001`'s provisioning side. This does **not** change
> the ADR-002 topology decision — the `qvm` vdev path is preferred regardless —
> but it re-opens host-routed transports as a Phase-2 comparison point and is
> required for any future Linux-guest networking.

---

## RQ-5 — Orin Nano Phase-3 readiness (committed home of heterogeneous IPC) — **LIKELY, AT-RISK on the *Nano* SKU**

| Claim | Tag | Evidence |
|---|---|---|
| Hypervisor/EL2 on Orin is **software-unsupported, not hardware-locked** ("if it is pure software approach, it does not impact warranty") | [VENDOR] (favourable, untested by NVIDIA SQA) | [NVIDIA forum: Orin hypervisor support](https://forums.developer.nvidia.com/t/clarification-on-jetson-orin-hypervisor-support-hardware-lock-or-only-unsupported/348348) |
| KVM works on **AGX Orin** after a kernel rebuild + `tegra234-soc-minimal.dtsi` GICv3 patch (stock attempt failed `VmCreateGIC … Error(19)`; patched → Ubuntu guest booted under KVM). `gic-version=2` works for ≤8 vCPUs without the patch | [EMPIRICAL] (AGX, not Nano) | [cloudkernels/Nubificus: Boot a VM on AGX Orin](https://blog.cloudkernels.net/posts/orin-vm/); [GICv3 vgic forum](https://forums.developer.nvidia.com/t/jetson-agx-orin-devkit-34-1-1-gicv3-vgic-creation-failed/216192) |
| Stock JetPack 6 kernel has KVM compiled in (VHE initialized in `dmesg`) → missing piece is vGIC/DTB wiring, not a KVM-less kernel | [EMPIRICAL] (community) | forum reports |
| KVM-accelerated QEMU on an Orin **Nano** under JetPack 6 — **no public confirmation** | [SPIKE] | absence of evidence; `tegra234` is shared across the Orin family so the DTB patch *should* transfer, but unverified on this SKU |

**Verdict: GO, conditionally.** No hard wall like the Graviton `/dev/kvm`
dead-end (EL2 is not fused off; KVM works on the Orin family with a known,
source-available patch). But since ADR-002 rests the *entire* dual-OS DRIVE OS
story on Orin, the unconfirmed-on-Nano status is the top risk.

**Corrections owed to `docs/orin-port.md`:** its "verify `/dev/kvm` exists … out
of the box" / "L4T exposes KVM out of the box" assumption is optimistic — change
to **"expect to rebuild kernel + patch DTB GICv3"**, and widen the "JetPack 6
ships QEMU without KVM" risk row to cover the vGIC/device-tree patch.
**Recommended:** pull a small Phase-3 smoke spike *before Phase 2 closes* —
flash JetPack 6, `dmesg | grep -i kvm`, `ls /dev/kvm`,
`qemu -enable-kvm -M virt,gic-version=3` boot — so an Orin-Nano GICv3 surprise
surfaces on schedule, not mid-Phase-3.

---

## Decisions / downstream actions this spike forces

1. **Option B (Phase-2.5 stretch) is feasibility-GREEN** — gated on build effort
   + TCG two-guest performance ([SPIKE]), not on a missing capability. ADR-002 §5
   RQ-1/RQ-3 close positive.
2. **Option-A stretch transport = `vdev-shmem`** (not vsock). If adopted, extend
   `scripts/qhv/g2.conf.allow` + `vdev.manifest` (gated change).
3. **RQ-4:** add virtio-net + virtio-rng to `launch-qhv-tcg.ps1`; re-frame the
   `TCR-ENT-001` provisioning side (entropy device, not inherent gap).
4. **RQ-5:** update `docs/orin-port.md` risk register (DTB GICv3 patch); schedule
   the Orin-Nano KVM smoke spike before Phase 2 closes.

> **Honest framing:** vendor support pages and forum posts are *claims/community
> reports*; the only things proven on hardware here are the contents of the local
> SDP install. Every "FEASIBLE" above that rests on [VENDOR]/[SPIKE] tags is a
> *go-ahead to attempt*, not a demonstration that it works.
