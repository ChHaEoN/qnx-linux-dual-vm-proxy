# Phase 3 — hardware-twin port to Jetson Orin Nano

> **Status (2026-07-28):** real-hardware work started. Orin Nano is
> flashed (JetPack 6 / L4T R36.4.7) and SSH-reachable. The same
> `qnx-safety-vm/output/ifs.bin` + `disk-qemu` from the cloud-twin
> Phase-1 build boots cleanly under **TCG** on this hardware
> ([orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)).
> **KVM-accelerated boot is blocked** by a real, root-caused ARM/KVM
> limitation (see risk register below) — decision made 2026-07-28 to
> **accept TCG as this stage's interim transport** and continue the
> Phase-3 IFS-port + IPC checklist on TCG rather than block further
> progress on the KVM fix. The success criterion in "What success
> looks like" below is unaffected (portability, not hardware timing);
> the *hardware-timed* KVM number remains open and tracked separately.

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

- [x] Confirm JetPack 6.x is the right release (matches L4T r36.x; Ubuntu 22.04 base) — confirmed: L4T R36.4.7
- [ ] ~~Stand up an x86_64 Linux host for SDK Manager~~ — moot: the Orin Nano at hand was already flashed via another project's workflow, no fresh SDK Manager run was needed for this verification
- [x] Retain the existing Phase-1 `qnx-safety-vm/output/ifs.bin` + `disk-qemu` — used directly, unmodified

### 1. Flash and first boot

- [x] Flash JetPack 6.x to the Orin Nano — already done (pre-existing, shared with another project)
- [x] First boot / hostname / ssh — already done, reachable at `haochen@<orin-ip>` with a dedicated key
- [x] `uname -a` reports `aarch64` (`Linux ... 5.15.148-tegra ... aarch64`)
- [x] `lscpu` shows 6 × Cortex-A78AE cores
- [x] `free -h` shows ~7.4 GB total, ~6.1 GB available

### 2. Install QEMU + bridge tooling on L4T

- [x] `sudo apt-get update`
- [x] `sudo apt-get install -y qemu-system-arm qemu-utils` (bridge-utils/iproute2/cloud-image-utils deferred — not needed yet for the TCG-only path; revisit at step 3 if the IPC test needs `br0`)
- [x] Verified `qemu-system-aarch64 --version` → 6.2.0 (Ubuntu 22.04 apt package)
- [x] **Verified `/dev/kvm` exists AND is usable** — kernel dmesg shows `VHE mode initialized successfully`; a bare vGIC smoke test (`-machine virt,gic-version=3,accel=kvm`, no real IFS) ran cleanly with zero errors. **This resolves the RQ-5 "unconfirmed on Orin Nano" question**: unlike AGX Orin, vGIC creation does NOT fail with `Error(19)` here — `gic-version=3` works at the vGIC-creation level. However, booting the *real* QNX IFS under KVM hangs for a different, deeper reason — see risk register below. `gic-version=2` fallback is **not available** on this host's KVM at all (`qemu-system-aarch64: host does not support in-kernel GICv2 emulation`).
- [ ] `sudo usermod -aG kvm $USER` and re-login — not done; used `sudo qemu-system-aarch64 ...` directly instead (NOPASSWD sudo was available), so this step was bypassed rather than completed

### 3. Set up bridge (Orin variant)

- [ ] `sudo scripts/orin/setup-bridge-orin.sh`
- [ ] Verify `br0` (192.168.100.1/24) and `tap-qnx` exist; on Orin the Linux client runs natively so no `tap-linux` is created
- [ ] Verify L4T native userspace can reach `192.168.100.1`

### 4. Transfer the cloud-twin IFS

- [ ] On the Phase 1 build host: `sha256sum output/ifs.bin output/disk-qemu.vmdk > output/SHA256SUMS` (on Windows: use Git Bash, which ships with Git for Windows and provides `sha256sum`; or `Get-FileHash` in PowerShell)
- [ ] `scp output/ifs.bin output/disk-qemu.vmdk output/SHA256SUMS orin:~/output/`
- [ ] On Orin: `sha256sum -c ~/output/SHA256SUMS` — must pass

### 5. Boot the QNX guest under QEMU on Orin

- [x] Booted — but via a direct `-accel tcg` invocation, **not** `scripts/orin/launch-qnx-on-orin.sh` (that script assumes KVM + the bridge from step 3, neither of which is in play on the accepted TCG-interim path; it needs a TCG-variant sibling analogous to `scripts/launch-qhv-tcg.ps1` before it's usable here — not yet written)
- [x] Captured full boot log: [orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log) — real `Startup complete` / `QNX qnx-safety 8.0.0 ... QEMU_virt aarch64le` banner on real Orin Nano hardware
- [ ] `pidin sysinfo` cycles_per_sec check — not yet done (log capture was `-serial file:...`, non-interactive; would need an interactive session or a scripted probe like the Phase-2 spike's approach)
- [x] QNX virtio-net / static IP — **root-caused and fixed 2026-07-28** (see risk register below and [findings.md](findings.md)'s 2026-07-28 "Orin TCG networking root-caused and fixed" entry): the failure was never a virtio-net/FDT problem — `io-sock` was not starting at all because the QEMU command line was missing a `virtio-rng-device` in the fixed slot order `startup.sh` assumes, so `/dev/random` never became usable and `io-sock` aborted before ever touching the network driver. Fixed with a QEMU command-line change only (`-netdev user,... -device virtio-net-device,...` + `-object rng-random,... -device virtio-rng-device,...`, no IFS rebuild): `vtnet0` comes up, gets a real DHCP lease (`10.0.2.15/24` via QEMU SLIRP), and pings succeed — [orin-tcg-qnx-network1.log](../logs/sample-boot/orin-tcg-qnx-network1.log). **Still open:** this used `-netdev user` (SLIRP), which proves the driver/MMIO wiring but is not the `br0`/tap bridge step 3 needs — bridging is the remaining follow-up before step 6 can use a real host-reachable IP

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
| **KVM boot hangs silently after `FOUND GICv3 ITS`, zero further output, on real Orin Nano hardware** (2026-07-28, first real-hardware run) — root-caused: `startup`'s GICv3 distributor priority-register init loop (`str w3,[x0],#4`, GICD_IPRIORITYRn offset 0x420, post-indexed store form) takes a Data Abort with `ESR.ISV=0` on real Cortex-A78AE/Tegra234 silicon under KVM (confirmed via `/sys/kernel/debug/tracing/events/kvm` ftrace: `kvm_guest_fault hsr=0x92000045`, `kvm_userspace_exit reason KVM_EXIT_ARM_NISV (28)`, at the exact PC identified via static disassembly of the extracted `startup` executable). KVM's in-kernel vgic-v3 MMIO fast path cannot decode a non-ISV abort and exits to QEMU as `KVM_EXIT_ARM_NISV`; QEMU 6.2.0 cannot complete the emulation for this instruction encoding and falls back to injecting a synthetic external Data Abort into the guest (confirmed via literal error strings compiled into the installed `qemu-system-aarch64` binary: "Data abort exception with no valid ISS generated by guest memory access. KVM unable to emulate faulting instruction..."). QNX's `startup-qemu-virt` EL1 exception-vector table (`VBAR_EL1=0x4008d800`, confirmed via live QEMU-monitor register dump + disassembly) has no real handler for a Synchronous exception taken at Current EL/SP_ELx this early in boot — the vector slot at offset 0x200 is a bare, unconditional `b .` — so the guest parks forever with no further serial output. Reproduced identically at `-smp 1`, `-smp 2`, `gic-version=3`, `gic-version=host`, with/without `its=off`. TCG never hits this because TCG's software MMIO model performs the write directly without ever synthesizing a hardware Data-Abort ISS — there is no ISV=0 case under TCG, which is why the identical `ifs.bin`/`disk-qemu` boots cleanly under `-accel tcg` on this same hardware (see [orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)). **Distinct from the AGX `Error(19)` row above** — that fails at vGIC *device creation* time, before any guest instruction runs; this fails deep into normal GICv3 *distributor bring-up* on real hardware backing, only after ITS discovery and CPU-interface (`ICC_SRE_EL1`/`ICC_PMR_EL1`/`ICC_CTLR_EL1`/…) bring-up already succeeded. Both are plausibly manifestations of a related underlying Tegra234 GIC/KVM-virtualization quirk family (same silicon lineage across AGX Orin / Orin NX / Orin Nano) surfacing differently depending on JetPack/kernel/QEMU version and exact code path — treat as related-but-not-identical; do not assume either "same bug" or "unrelated" | **Follow-up research (2026-07-28) downgrades the "try a newer QEMU" lead**: QEMU's KVM-backend handler for this exact case, `kvm_arm_handle_dabt_nisv()` (merged upstream years before QEMU 6.2, via Beata Michalska's patch series, [patchwork.kernel.org](https://patchwork.kernel.org/project/qemu-devel/patch/20200323113227.3169-2-beata.michalska@linaro.org/)), is *designed* to inject an external Data Abort when ISV=0 — it does not attempt instruction decode/emulation for the KVM accelerator, by deliberate upstream design (the kernel KVM/ARM maintainers' stated position: "well-written MMIO drivers shouldn't use writeback-form loads/stores on device registers" — [Linux KVM API docs](https://docs.kernel.org/virt/kvm/api.html)). A QEMU-side software decode-and-emulate fallback for ISV=0 exists only as an RFC for the **HVF** (macOS Hypervisor.framework) accelerator, not KVM. So a QEMU version bump on Linux/KVM is now assessed as **unlikely to help** — this isn't a version-specific bug, it's the KVM backend's permanent architecture. Revised real options: (a) **file this with QNX/BlackBerry support** — the defect is in their proprietary `startup-qemu-virt` binary's GICv3 bring-up code, which uses a post-indexed store on a device register that ARM's own architecture reference excludes from ISV reporting; a newer SDP dot-release may already avoid it. (b) **Accept TCG on Orin for now** (decision made 2026-07-28, see status header) — proceed with the Phase-3 IFS-port + IPC checklist on TCG, and revisit KVM if/when QNX ships a fix. Patching QNX's proprietary `startup` binary remains ruled out (NCEULA / binary-modification risk). | Medium — no longer blocks Phase-3 progress (TCG accepted as interim transport per 2026-07-28 decision); still blocks the *hardware-timed* KVM number specifically, pending a QNX-side fix |
| **Plain `qnx-safety-vm` TCG boot: virtio-net never comes up** (`if_up: network stack down: Bad file descriptor`, `ifconfig: interface vtnet0 does not exist`, first hit 2026-07-28 on real Orin Nano hardware, [orin-tcg-qnx-boot1.log](../logs/sample-boot/orin-tcg-qnx-boot1.log)) — **root-caused 2026-07-28, distinct from and unrelated to the KVM/NISV row above** (this reproduces identically under pure TCG, no KVM in the loop at all): `io-sock` was never running (confirmed via live `pidin` on an interactive boot shell), because it aborts at startup with `Exiting: Cannot open /dev/random` (confirmed via `slog2info`) whenever `/dev/random` isn't usable, and `/dev/random` wasn't usable because `random`'s `devr-virtio.so:mem=0xa003a00` entropy source found no virtio-rng device at that fixed MMIO address. `startup.sh`'s hardcoded `smem=`/`mem=` values assume the exact three-`-device` order (`virtio-blk-device`, `virtio-net-device`, `virtio-rng-device`) that `mkqnximage`'s own `qemu/runimage` template always uses — the TCG boot command in use had only the disk device, leaving the rng slot empty. The virtio-net symptom was a downstream artefact of io-sock never starting at all, not a virtio-net-specific bug | **Fixed — QEMU command-line change only, no IFS rebuild:** add `-netdev user,id=n0 -device virtio-net-device,netdev=n0,mac=...` and `-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-device,rng=rng0` after the existing blk device, in that order. Confirmed on real hardware: `vtnet0` up, real DHCP lease (`10.0.2.15/24`), successful pings — [orin-tcg-qnx-network1.log](../logs/sample-boot/orin-tcg-qnx-network1.log). Full chain in [findings.md](findings.md)'s 2026-07-28 "Orin TCG networking root-caused and fixed" entry. **Still open:** `-netdev user` is SLIRP, not the `br0`/tap bridge step 3 needs — bridging remains a follow-up, now unblocked rather than blocked | Low — closed for the TCG interim transport; bridge wiring for step 3/6 is the remaining follow-up |
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
