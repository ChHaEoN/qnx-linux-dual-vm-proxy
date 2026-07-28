# Phase 3 — hardware-twin port to Jetson Orin Nano

> **Status:** plan only. Phase 3 starts after Phase 2 (cloud-twin
> IPC + benchmark) lands. This file is the bring-up checklist + risk
> register for that work.

---

## Goal

Run the **same QNX IFS** and the **same ipc-test/ source** that
worked on the cloud twin, on a Jetson Orin Nano Dev Kit, with no
code changes — only configuration deltas. Measurable proof point:
`qnx-server` on QEMU-on-Orin and `linux-client` natively on L4T
exchange messages over `br0`, and a 100k-iteration benchmark
produces a CSV in `results/hw/` with the same column schema as
`results/cloud/`.

---

## Hardware preconditions

| Item | Notes |
|---|---|
| Jetson Orin Nano Dev Kit | 8 GB SKU recommended; 6 GB SKU borderline for L4T + QEMU(QNX, 1 GB) + benchmark |
| microSD or NVMe | NVMe preferred for boot; ≥64 GB |
| USB-C PSU | Match the Dev Kit's bundled supply (do not undervolt — A78AE will throttle) |
| Ethernet | For initial JetPack flash + apt installs |
| Host machine for flashing | x86_64 Linux with NVIDIA SDK Manager (Phase 3 first task is to confirm whether this exists at hand or needs an EC2 throwaway instance) |

SDK Manager officially supports only x86_64 Ubuntu (22.04 LTS or
20.04 LTS) — it does NOT run on Windows. The 2026-05-07 build-host
pivot moves the QNX IFS build to local Windows as the primary path,
which means an x86_64 Linux host is no longer automatically present.
Phase 3 first task is therefore to either (a) spin up a t3.medium
Ubuntu EC2 dedicated to SDK Manager (single-shot, then teardown),
(b) reuse the EC2 fallback build host if it was kept around from
Phase 1, or (c) bring up an existing local Linux box. Honest framing:
the pivot did **not** improve this corner — it removed a convenient
piggyback that the old EC2-build-host path provided. See the
2026-05-07 amendment in [findings.md](findings.md).

---

## Bring-up checklist

### 0. Pre-flight

- [ ] Confirm JetPack 6.x is the right release (matches L4T r36.x; Ubuntu 22.04 base)
- [ ] Stand up an x86_64 Linux host for SDK Manager: Phase 1 EC2 fallback build host if it was retained, otherwise a fresh t3.medium Ubuntu 22.04 (SDK Manager does not run on Windows)
- [ ] On the Phase 1 build host (Windows local primary, or EC2 fallback), retain the existing `output/ifs.bin` from Phase 1 — this is the artefact under test on Orin

### 1. Flash and first boot

- [ ] Flash JetPack 6.x to the Orin Nano via SDK Manager
- [ ] First boot: complete Ubuntu first-run, set hostname, install ssh
- [ ] Confirm `uname -a` reports A78AE / `aarch64`
- [ ] `lscpu` should show 6 × A78AE cores
- [ ] `free -h` should show ≥7 GB usable

### 2. Install QEMU + bridge tooling on L4T

- [ ] `sudo apt-get update`
- [ ] `sudo apt-get install -y qemu-system-arm qemu-utils bridge-utils iproute2 cloud-image-utils`
- [ ] Verify `qemu-system-aarch64 --version`
- [ ] Verify `/dev/kvm` exists — **do NOT assume out-of-the-box.** Per the RQ-5 spike ([phase2-research-spike.md](phase2-research-spike.md)): JetPack 6 compiles KVM in (VHE inits in `dmesg`), but KVM-accelerated QEMU on the Orin family empirically needs a **device-tree GICv3 patch** (`tegra234-soc-minimal.dtsi`) + kernel rebuild — proven on AGX Orin, **unconfirmed on Orin Nano**. NVIDIA: EL2 is software-unsupported, not hardware-locked. Expect: `dmesg | grep -i kvm`, `ls /dev/kvm`, then a `qemu -enable-kvm -M virt,gic-version=3` smoke-boot; fall back to `gic-version=2` (≤8 vCPUs) if vGIC creation fails (`Error(19)`).
- [ ] `sudo usermod -aG kvm $USER` and re-login

### 3. Set up bridge (Orin variant)

- [ ] `sudo scripts/orin/setup-bridge-orin.sh`
- [ ] Verify `br0` (192.168.100.1/24) and `tap-qnx` exist; on Orin the Linux client runs natively so no `tap-linux` is created
- [ ] Verify L4T native userspace can reach `192.168.100.1`

### 4. Transfer the cloud-twin IFS

- [ ] On the Phase 1 build host: `sha256sum output/ifs.bin output/disk-qemu.vmdk > output/SHA256SUMS` (on Windows: use Git Bash, which ships with Git for Windows and provides `sha256sum`; or `Get-FileHash` in PowerShell)
- [ ] `scp output/ifs.bin output/disk-qemu.vmdk output/SHA256SUMS orin:~/output/`
- [ ] On Orin: `sha256sum -c ~/output/SHA256SUMS` — must pass

### 5. Boot the QNX guest under QEMU on Orin

- [ ] `scripts/orin/launch-qnx-on-orin.sh`
- [ ] Capture full boot log to `logs/sample-boot/orin-qnx-bootN.log`
- [ ] Verify QNX prompt; `pidin sysinfo` reports correct cycles_per_sec
- [ ] Confirm QNX virtio-net comes up; static IP 192.168.100.10; ping 192.168.100.1 succeeds

### 6. Run the IPC test natively on L4T against the QEMU-QNX server

- [ ] Build `ipc-test/linux-client/` natively on L4T (gcc, no cross-compile needed)
- [ ] Run 1 000-iteration warm-up; record results
- [ ] Run 100 000-iteration measurement; emit CSV to `results/hw/orin-runN.csv`
- [ ] Compare CSV header / schema to `results/cloud/awsN.csv` — schema must match exactly

### 7. Twin diff sanity check

- [ ] `scripts/twin/diff-results.sh results/cloud/aws1.csv results/hw/orin1.csv` (Phase 4 script)
- [ ] No interpretation in Phase 3 — just confirm the diff runs cleanly and the numbers look "physically plausible" (P50 in tens-to-hundreds of µs, P99 within an order of magnitude of P50, no NaN / no negative deltas)

---

## Risk register (carried from `bsp-selection.md` F6)

| Risk | Mitigation if it bites | Effort |
|---|---|---|
| Same IFS does not boot under QEMU-on-Orin | Tweak QEMU args (mask A78AE-specific feature) | Low |
| Same IFS still does not boot | Rebuild IFS with explicit A78AE flags via mkqnximage options | Medium |
| Still does not boot | Switch HW twin to `joexue/qemu-virt` community BSP for source-level visibility | High |
| **QNX microkernel CPU-feature probe rejects A78AE silently** (MIDR/REVIDR allow-list mismatch — symptom: hang before any boot banner) | First failed boot, capture `qemu -d in_asm,int` trace to distinguish CPU-probe rejection from device-tree mismatch; if confirmed, escalate to "Same IFS still does not boot" branch (rebuild w/ A78AE flags) | Low (just the trace); diagnosis only |
| JetPack 6 ships QEMU without KVM enabled | Build `qemu-system-aarch64` from source on L4T with KVM enabled | Medium |
| **KVM vGIC creation fails on Orin under `gic-version=3`** (`VmCreateGIC … Error(19)`) — empirically hit on AGX Orin; **CONFIRMED NOT REPRODUCED on Orin Nano** (real hardware, 2026-07-28): vGIC creation and MMIO-based GICv3/ITS discovery both succeed on Orin Nano. `gic-version=2` is also not a usable fallback on this Orin Nano's KVM regardless (QEMU refuses it outright: "host does not support in-kernel GICv2 emulation") | N/A on Orin Nano — this specific failure did not occur here. The `tegra234-soc-minimal.dtsi` DTB patch is AGX-specific until/unless separately proven relevant to Orin Nano. | Low (diagnosis only; closed for Orin Nano) |
| **KVM boot hangs silently after `FOUND GICv3 ITS`, zero further output, on real Orin Nano hardware** (2026-07-28, first real-hardware run) — root-caused: `startup`'s GICv3 distributor priority-register init loop (`str w3,[x0],#4`, GICD_IPRIORITYRn offset 0x420, post-indexed store form) takes a Data Abort with `ESR.ISV=0` on real Cortex-A78AE/Tegra234 silicon under KVM (confirmed via `/sys/kernel/debug/tracing/events/kvm` ftrace: `kvm_guest_fault hsr=0x92000045`, `kvm_userspace_exit reason KVM_EXIT_ARM_NISV (28)`, at the exact PC identified via static disassembly of the extracted `startup` executable). KVM's in-kernel vgic-v3 MMIO fast path cannot decode a non-ISV abort and exits to QEMU as `KVM_EXIT_ARM_NISV`; QEMU 6.2.0 cannot complete the emulation for this instruction encoding and falls back to injecting a synthetic external Data Abort into the guest (confirmed via literal error strings compiled into the installed `qemu-system-aarch64` binary: "Data abort exception with no valid ISS generated by guest memory access. KVM unable to emulate faulting instruction..."). QNX's `startup-qemu-virt` EL1 exception-vector table (`VBAR_EL1=0x4008d800`, confirmed via live QEMU-monitor register dump + disassembly) has no real handler for a Synchronous exception taken at Current EL/SP_ELx this early in boot — the vector slot at offset 0x200 is a bare, unconditional `b .` — so the guest parks forever with no further serial output. Reproduced identically at `-smp 1`, `-smp 2`, `gic-version=3`, `gic-version=host`, with/without `its=off`. TCG never hits this because TCG's software MMIO model performs the write directly without ever synthesizing a hardware Data-Abort ISS — there is no ISV=0 case under TCG, which is why the identical `ifs.bin`/`disk-qemu` boots cleanly under `-accel tcg` on this same hardware (see [orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)). **Distinct from the AGX `Error(19)` row above** — that fails at vGIC *device creation* time, before any guest instruction runs; this fails deep into normal GICv3 *distributor bring-up* on real hardware backing, only after ITS discovery and CPU-interface (`ICC_SRE_EL1`/`ICC_PMR_EL1`/`ICC_CTLR_EL1`/…) bring-up already succeeded. Both are plausibly manifestations of a related underlying Tegra234 GIC/KVM-virtualization quirk family (same silicon lineage across AGX Orin / Orin NX / Orin Nano) surfacing differently depending on JetPack/kernel/QEMU version and exact code path — treat as related-but-not-identical; do not assume either "same bug" or "unrelated" | Try a newer upstream QEMU (Ubuntu 22.04 apt ships only the 6.2.x line — no newer candidate available) with improved `kvm_arm_handle_dabt_nisv()` decode coverage for post-indexed load/store forms — plausible but **untested**, not yet attempted. No QEMU-flag-level workaround found (`gic-version=2` unusable on this host's KVM; no `-cpu` alternative to `host`/`max` exists under `-enable-kvm`). Patching QNX's proprietary `startup` binary was ruled out as out of scope (NCEULA / binary-modification risk). | Medium–High — blocks the Phase-3 KVM success criterion entirely until either a QEMU upgrade is proven to fix NISV decode for this instruction form, or QNX/BlackBerry ships a startup fix |
| Orin Nano 8 GB tight on RAM | Reduce QNX guest to 768 MB; benchmark RSS-headroom; if still tight, swap to larger Orin family (Orin NX 16 GB, $599) — narrative cost note | Low if QNX shrinks; doc only otherwise |
| `vhost-net` not enabled in L4T kernel | Live with userspace virtio (slower); document in twin-diff doc | Low |

---

## What success looks like

The Phase 3 deliverable is **not** a benchmark number. It is **proof
of code+artefact portability**: the same `output/ifs.bin` and the
same `ipc-test/` source produced a working IPC channel on a real
Tegra-class SoC with **only configuration changes**. The CSV
schemas matching is the load-bearing evidence — that is what makes
Phase 4's twin diff meaningful.

If we get there, the project's narrative becomes meaningfully
stronger: the cloud twin is a fast iteration sandbox, and the
hardware twin proves it ports to silicon. That is the customer-port
story DRIVE OS SE work actually consists of.
