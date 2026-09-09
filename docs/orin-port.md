# Phase 3 — hardware-twin port to Jetson Orin Nano

> **Status (2026-07-28, updated):** the Phase-3 IPC benchmark is
> **done end-to-end, on TCG, over a real `br0` bridge.** A new QNX
> guest-side TCP echo server
> ([`ipc-test/qnx-server-net/server.c`](../ipc-test/qnx-server-net/server.c))
> and a new native-Linux client
> ([`ipc-test/linux-client/client.c`](../ipc-test/linux-client/client.c))
> were written (the Phase-2 `qnx-server`/`qnx-host-client` stay
> untouched — they are a different transport, virtio-console, for the
> cloud leg). `qnx-safety-vm` was **rebuilt** (still `mkqnximage
> --type=qemu --arch=aarch64le`, same baseline options) with
> `local/snippets/{ifs_files,post_start}.custom` staging the new server
> binary and forcing `vtnet0`'s static IP, so the guest comes up with
> the TCP server already listening, no manual/interactive step needed.
> Booted via [`scripts/orin/launch-qnx-on-orin-tcg.sh`](../scripts/orin/launch-qnx-on-orin-tcg.sh)
> (TCG + `tap-qnx` + the virtio-rng fix) on real Orin Nano hardware,
> bridged to `br0`, with the native L4T `linux-client` completing a
> full **100 000-iteration + 1 000-warm-up run twice in a row with zero
> errors** (~2m40s each) — see
> [orin-tcg-qnx-ipc-boot1.log](../logs/sample-boot/orin-tcg-qnx-ipc-boot1.log) /
> [orin-tcg-qnx-ipc-client1.log](../logs/sample-boot/orin-tcg-qnx-ipc-client1.log)
> and [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv).
> This is a real improvement over the Phase-2 cloud leg's
> non-deterministic virtio-console stall (~15 samples) — TCP over
> `br0`/virtio-net under TCG did not stall at all. **KVM-accelerated
> boot is still blocked** by the same root-caused ARM/KVM limitation
> below; TCG remains the accepted interim transport, and the
> *hardware-timed* KVM number stays open and tracked separately.

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
- [x] First boot / hostname / ssh — already done, reachable at `<user>@<orin-ip>` with a dedicated key
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

- [x] `sudo scripts/orin/setup-bridge-orin.sh` — ran clean (script needed no changes; only a CRLF-strip on the transferred copy, a Windows-checkout artifact, not a script bug)
- [x] Verified `br0` (192.168.100.1/24) and `tap-qnx` exist; on Orin the Linux client runs natively so no `tap-linux` is created
- [x] Verified L4T native userspace can reach the QNX guest at `192.168.100.10` (not `192.168.100.1` — that's the bridge's own address; the guest is the far side) — real `ping` RTTs, 0% loss

### 4. Transfer the cloud-twin IFS

- [x] **Rebuilt, not the untouched Phase-1 IFS** — see the 2026-07-28 status header: `qnx-safety-vm` was rebuilt from the same baseline `local/options` via `mkqnximage --type=qemu --arch=aarch64le --hostname=qnx-safety --build` (invoked from the Windows build host; had to go through `cmd.exe //c ...`, not plain bash — see the "Windows/MSYS gotcha" note below) with two new `local/snippets/*.custom` files staging `qnx-server-net`'s binary and forcing the static IP. Honest deviation from "same IFS, zero changes": the *code* (`ipc-test/`) is new/additive as scoped, and this rebuild is the config-and-staging mechanism that carries it — not a change to Phase-1's boot/BSP behaviour. **Reproducibility note:** `qnx-safety-vm/` is entirely gitignored (mkqnximage-derived), so the two `local/snippets/*.custom` files staged directly during this pass would NOT survive in git on their own. [`scripts/build-qnx-ifs-orin.bat`](../scripts/build-qnx-ifs-orin.bat) (new, mirrors `build-qhv.bat`'s staging pattern for `build-qnx-ifs.bat`) is the committed, reproducible recipe: it builds `ipc-test`, stages [`scripts/orin/qnx-safety-vm-post_start.custom`](../scripts/orin/qnx-safety-vm-post_start.custom) (the committed source of truth for the static-IP + auto-start logic) plus a freshly-generated `ifs_files.custom` (one line, an absolute host path, regenerated every run — not committed, same as `build-qhv.bat`'s own `ifs_files.custom`/`data_files.custom`), then calls `build-qnx-ifs.bat`. Not re-run after being written (the already-verified rebuild from the manual steps stands); a future session should use this script rather than repeat the manual `local/snippets/` edit.
- [x] `sha256sum output/ifs.bin output/disk-qemu output/disk-qemu.vmdk > output/SHA256SUMS` (Git Bash on the Windows build host)
- [x] `scp output/{ifs.bin,disk-qemu,disk-qemu.vmdk,SHA256SUMS} <user>@<orin-ip>:~/qnx-orin-test/`
- [x] On Orin: `sha256sum -c SHA256SUMS` — **all three OK**, byte-identical transfer confirmed

**Windows/MSYS gotcha hit during the rebuild:** invoking `cmd.exe /c "..."` from Git Bash silently no-ops — Git Bash's MSYS path-mangling rewrites the bare `/c` flag into a Windows path (`C:/`) before `cmd.exe` ever sees it, so the whole command line is swallowed and you get an interactive banner and nothing else, with exit code 0 (looks like success). Fix: `cmd.exe //c "..."` (doubled slash defeats the MSYS rewrite). Cost about 10 minutes of "why did nothing happen" before being caught by explicitly checking `where mkqnximage` output was missing from the log.

### 5. Boot the QNX guest under QEMU on Orin

- [x] Booted via [`scripts/orin/launch-qnx-on-orin-tcg.sh`](../scripts/orin/launch-qnx-on-orin-tcg.sh) (new script, written this pass) — TCG + `tap-qnx` + the virtio-rng fix, superseding the ad hoc direct invocation from the previous entry. `scripts/orin/launch-qnx-on-orin.sh` (the `-enable-kvm` variant) is left untouched/unfixed, still documenting the eventual KVM target once/if the NISV issue is resolved upstream.
- [x] Captured full boot log: [orin-tcg-qnx-ipc-boot1.log](../logs/sample-boot/orin-tcg-qnx-ipc-boot1.log) — real `Startup complete` / `QNX qnx-safety 8.0.0 ... QEMU_virt aarch64le` banner, plus the new server's `listening on 0.0.0.0:7000` line and four real client-connection records, all on real Orin Nano hardware
- [ ] `pidin sysinfo` cycles_per_sec check — still not done; not needed for this leg (the Linux client's RTT uses `clock_gettime`, not `ClockCycles()`) but left open for a future QNX-side timing investigation
- [x] QNX virtio-net / **static IP over the real `br0` bridge** — the SLIRP-only gap noted in the previous entry is now closed: `post_start.custom` runs `ifconfig vtnet0 192.168.100.10 netmask 255.255.255.0 up` unconditionally (OPT_IP=dhcp's `dhcpcd` never gets a lease on `br0` — no DHCP server there — so it doesn't conflict), and the Orin host pings `192.168.100.10` successfully over `br0`/`tap-qnx`

### 6. Run the IPC test natively on L4T against the QEMU-QNX server

- [x] Wrote and built `ipc-test/qnx-server-net/server.c` (new, qcc, `-lsocket`; Phase-2's `qnx-server/` is untouched) — TCP echo endpoint on `:7000`, staged into the IFS and auto-started (step 4/5)
- [x] Wrote and built `ipc-test/linux-client/client.c` natively on L4T (`gcc (Ubuntu 11.4.0)`, zero warnings, no cross-compile) — see [`ipc-test/linux-client/`](../ipc-test/linux-client/)
- [x] Ran a 1 000-iteration warm-up + 1 000 timed smoke run first (per the pacing guidance from the Phase-2 spike) — completed cleanly in ~4.7s, no stall
- [x] Ran the full 100 000-iteration + 1 000-warm-up measurement **twice in a row**, both clean, no echo-seq mismatches, no I/O errors (~2m40s each) — a real improvement over the Phase-2 cloud leg's non-deterministic virtio-console stall (~15 samples): TCP over `br0`/virtio-net under TCG did not exhibit the same stall at all. CSV: [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv); client-side log: [orin-tcg-qnx-ipc-client1.log](../logs/sample-boot/orin-tcg-qnx-ipc-client1.log)
- [x] Compared CSV schema to `results/cloud/header.csv` — **matches exactly** (`unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes`); the hw CSV's `cycles_per_sec` column is a nominal `1000000000` placeholder (Linux side times with `clock_gettime`, already in ns, no real hardware cycle rate) — called out in the `notes` field so it's never mistaken for a real cycle rate

### 7. Twin diff sanity check

- [x] `scripts/twin/diff-results.sh results/cloud/cloud-ipc-latest.csv results/hw/orin-ipc-latest.csv` — runs without crashing, exit 0
- [ ] **Not a real sanity check — the script's assumed schema doesn't match either CSV.** `diff-results.sh` (Phase 4, pre-existing, not written this pass) expects `# ifs_sha256:`/`# git_sha:` comment-header lines and a `metric,p50_us,p99_us,p999_us,max_us,boot_ms` body keyed by metric name; both `cloud-ipc-latest.csv` and `orin-ipc-latest.csv` actually use the flat `header.csv` row schema with no header row of their own. The script silently misreads the first data row as a header and prints nonsense deltas (e.g. "payload_bytes Δ=+48.00") rather than failing loudly. This is a **pre-existing Phase-4 tooling gap** (predates this pass; the cloud CSV had the identical shape already), out of scope to fix here per this task's brief — flagging for Phase 4 rather than silently leaving it looking like a passed check.

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
| **Cross-vendor validation (2026-07-29): the `FOUND GICv3 ITS` hang reproduces identically on AWS EC2 `a1.metal` (Graviton1, Annapurna Labs SoC, 16× Cortex-A72)** — a completely different vendor and core generation from Orin's Tegra234/Cortex-A78AE. Same `ifs.bin`/`disk-qemu`, same `-machine virt,gic-version=3 -cpu host -enable-kvm` invocation: `FOUND GICv3 ITS` printed, then zero further output for the full 60s capture, `qemu-system-aarch64` still alive (killed only by the external timeout). A bare vGIC smoke test (`-kernel /dev/null`) on the same instance ran clean, same as on Orin — vGIC *creation* is not the failure point there either. `c7g.metal` (Graviton3, same generation as this project's `c7g.large` cloud leg) was the intended cleaner comparison but was blocked by this AWS account's 32-vCPU quota (`c7g.metal` needs 64); `a1.metal` was the quota-fitting fallback. Full capture: [aws-a1-metal-kvm-nisv-repro.log](../logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log). **This is one run, not a repeated series** (contrast with this doc's n=5 boot-time methodology) — treat as strong single-data-point evidence, not statistically hardened. | This upgrades the finding from "possibly Tegra234-specific" to "reproduced across at least two independent ARM vendors" — strengthens the case for filing with QNX/BlackBerry (option (a) in the row above) since it is now evidenced as a general `startup-qemu-virt` defect, not a Jetson-specific quirk. Does not change the recommended near-term posture (TCG remains the working interim transport). A `c7g.metal` run (same Graviton3 generation as the rest of the cloud leg) remains a real, not-yet-executed follow-up if/when the vCPU quota is raised. | Low (diagnosis only) — raises confidence on the vendor-escalation option above, does not itself unblock anything |
| **COMPILE-VERIFIED (2026-09-08): the faulting instruction is reproducible from SDP's own BSP source, and one flag removes it** — `$SDP/bsp/BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip` ships `src/hardware/startup/lib/aarch64/gic_v3.c`. Built unmodified with the SDP Windows toolchain (`qcc -Vgcc_ntoaarch64`, gcc 12.2.0), `gic_v3.o` contains `str w3,[x0],#4` at GICD base **+0x420** inside `gic_v3_initialize` — the same instruction form at the same offset this row's neighbour root-caused from ftrace + disassembly of the shipped binary, so the strength-reduction theory is **confirmed, not inferred**. Four MMIO writeback stores exist in that object (GICD priority `0x1a68`, GICD clear `0x1a90`, GICR priority `0x1b0`, 64-bit `0x1af0`); recompiling with `-fno-auto-inc-dec` takes that count to **zero**, the loop becoming `add x0,x0,#4` + `stur w3,[x0,#-4]` — identical addresses/values/iterations, non-writeback, so ISS is valid and KVM's vgic MMIO path can decode it. QNX already ships `-fno-store-merging` in these flags for the same class of reason. | **Still boot-unverified:** nothing has been booted, and `startup-qemu-virt` cannot be relinked because the BSP ships `boards/armv8_fm/` but **not** `boards/qemu-virt/` — `libstartup.a` rebuilds, the binary that consumes it does not. Only `gic_v3.c` was audited, not the whole library. Routes forward: (a) file with QNX/BlackBerry — this makes the report concrete enough for them to verify cheaply; (b) request the `qemu-virt` board source; (c) adapt `armv8_fm` to QEMU `virt`'s memory map and boot the result under KVM on `a1.metal`, which already reproduces the hang. | Low to reproduce (done); High to reach a bootable rebuilt startup |
| **QHV host image hangs on the Orin under the distro QEMU 6.2.0 TCG** (2026-09-08): boots to file-system mount, then never returns from the first timeout-wait (`waitfor /dev/random`; with an rng presented, `io-sock` start instead). **Attributed to the QEMU version, not the host** (2026-09-09; the host is excluded as a sufficient cause by the 11.1.0 boot on the same board — the timer mechanism below is hypothesised, not observed): `v6.2.0`'s `hw/arm/virt.c` has no NS-EL2 virtual-timer IRQ wiring (added in 9.0, `1ec896fe7c`); a VHE hypervisor's timers are `CNTHV_*`. `target/arm` also gained `5709038aa8` (10.0). Not bisected between them. A `-cpu cortex-a57` (no VHE) control on the same 6.2 gets past the host hang point (timeouts fire, `qvm` launches), supporting the VHE/EL2-virtual-timer mechanism for the host; the guest then aborts on a PAUTH feature check the A57 model cannot pass — unrelated. **Verified 2026-09-09:** 11.1.0 rebuilt with only that wire removed hangs identically; the wire is the cause. The plain EL1 IFS is unaffected (`CNTV`, INTID 27, always wired). | `scripts/orin/build-qemu-on-orin.sh` builds a tagged QEMU (v11.1.0) into its own prefix — the QHV host **and guest boot** with it (~63–78 s to guest banner). Distro 6.2.0 kept intact for every prior `qnx-safety-vm` result. `launch-qhv-on-orin-tcg.sh` now selects the binary explicitly and stamps it. | Low (done); the from-source build also gives a `--enable-kvm` QEMU for a cheap NISV re-check |
| **Board dropped off the network entirely mid-scp and needed a power cycle** (2026-09-08: no ping, no SSH anywhere on the /24; back ~19 min later with a fresh boot). Cause **unknown** — journald on this L4T image is volatile, so the previous boot left no record. Suspected but unproven: supply brown-out under CPU + Wi-Fi + storage load (the Dev Kit's USB-C path is marginal under sustained draw). | Transfers are now resumable and checksum-gated (`sync-qhv.sh`); the QEMU build was run at `-j4` rather than `-j6` for this reason; every measurement re-verifies `SHA256SUMS` before and after. To close it: enable persistent journald (`mkdir /var/log/journal`) so the *next* drop leaves a record, and check the supply against the Dev Kit's 5 V/4 A barrel-jack recommendation. | Medium while unexplained — a drop mid-series would produce plausible-looking garbage rather than a failure |

## Research sweep B (2026-09-09) — native QNX on the Orin Nano (Tegra234): verdict and citations

> Input to **ADR-003** (where a hardware-timed *hypervisor* number could
> come from). Research-agent output: findings and citations, **not a
> decision** — the Architect arbitrates. Evidence tags: **[local]** =
> inspected in the SDP 8.0.4 install on this machine or built with its
> toolchain this session; **[vendor]** = primary NVIDIA / QNX / upstream
> source; **[community]** = forum or blog; **[inference]** = reasoned from
> the above, not observed.

### Verdict (one paragraph)

A native QNX port to the Orin Nano is **technically plausible but is a
from-scratch BSP bring-up with no vendor path**. (1) The JetPack 6 UEFI is
a standard edk2 build that boots arbitrary AArch64 EFI applications, hands
the OS off at **EL2**, and (for the "general" T23x build) is configured
with both Device Tree and ACPI. (2) Every register-level fact a first-cut
startup needs is in upstream `tegra234.dtsi` — but the only debug
console on the Orin Nano is the SPE-owned Tegra Combined UART, not a
CPU-drivable 8250, and NVIDIA says re-purposing it is unsupported.
(3) NVIDIA has said three times (2020, 2024, 2025) that QNX on Jetson is
not supported and not planned; QNX exists only on DRIVE, behind NVONLINE
and an invitation-only partner program. (4) The public SDP 8.0 startup
library and the Apache-2.0 BSP source shipped with it already contain a
UEFI entry (`efi_entry_point`), an ACPI/SPCR path, a Tegra 8250-style
debug callout, T18x PCIe/MSI callouts and a Cortex-A78AE cpuid, and
`mkifs` emits an AArch64 PE image today (toolchain-verified) even though
the 8.0 docs list `uefi.boot` as x86_64-only. (5) The governing licence
for Everywhere users is the **Non-Commercial QDL v7 (2025-12-10)**: it
grants the right to modify source-delivered Software for a Non-Commercial
Target System with **no hardware restriction**, forbids modifying or
reverse-engineering binary-delivered Software, and — a project-wide
finding — forbids publishing "the results of any performance or
functional evaluation of the Software" without written approval from
BlackBerry (4.6(i)). What a port would *not* remove: the hypervisor host
(`qvm`, EL2 `procnto`) is prebuilt and board-agnostic, so the missing
piece is exactly a board startup plus storage/network drivers — weeks of
BSP work with no vendor support, and the result is still a
personal-licence experiment.

### (1) JetPack 6 / L4T R36 boot chain on the Orin Nano

- **Chain:** BootROM → PSCROM → MB1 → MB2 → UEFI → kernel; "UEFI ...
  replaces CBoot in the Jetson boot flow as the CPUBL for Jetson Linux
  devices." The page names no TF-A/EL stages. **[vendor]**
  https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AR/BootArchitecture/JetsonOrinSeriesBootFlow.html
- **UEFI behaviour (R36.4.3 "UEFI Adaptation"):** "L4tLauncher ... the
  default OS Loader for the UEFI"; the kernel is loaded through its EFI
  stub ("EFI stub: Booting Linux Kernel..."); "OS boot is supported from
  eMMC/SD/UFS/NvME/USB (T234 only)"; Boot Manager via ESC; the UEFI shell
  is on by default (Kconfig `default y`; "We strongly recommend that you
  disable the UEFI shell for production devices"); GRUB may replace
  `BOOTAA64.efi` via `grub-install --target=arm64-efi` — i.e. an
  arbitrary EFI application can be the OS loader. **[vendor]**
  https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/Bootloader/UEFI.html
- **Exception level at hand-off = EL2.** TF-A: BL31 jumps to BL33 "at
  the highest available Exception Level (EL2 if available, otherwise
  EL1)" **[vendor]**
  https://trustedfirmware-a.readthedocs.io/en/latest/design/firmware-design.html ;
  Linux `booting.rst`: "The CPU must be in non-secure state, either in
  EL2 (RECOMMENDED ...) or in EL1" **[vendor]**
  https://raw.githubusercontent.com/torvalds/linux/master/Documentation/arch/arm64/booting.rst ;
  a public AGX Orin dmesg (5.10.120-tegra) shows `efi: EFI v2.70 by EDK
  II`, `CPU: All CPU(s) started at EL2`, `psci: PSCIv1.1 detected in
  firmware`, `kvm [1]: VHE mode initialized successfully`, `console
  [ttyTCU0] enabled` **[community log]**
  https://linux-hardware.org/?log=dmesg&probe=d1de28c1b6 . Kernel source
  ties the strings to the mode: `smp.c` prints "All CPU(s) started at
  EL2" iff `is_hyp_mode_available()`; v5.15 `arm.c` prints "VHE mode
  initialized successfully" only when `in_hyp_mode`. The dmesg of this
  board already shows the VHE line (step 2 above), so **EL2 entry on this
  Orin Nano is verified, not assumed** **[local + vendor source]**.
- **DT vs ACPI:** edk2-nvidia `Platform/NVIDIA/Kconfig` defines `config
  ACPI bool "ACPI support"` (and `TEGRA_ACPI depends on SOC_GENERAL ||
  SOC_DATACENTER`); `KconfigIncludes/BuildGeneral.conf` — the build type
  chosen by `Tegra/DefConfigs/t23x_general.defconfig` (`CONFIG_SOC_T23X=y`,
  `CONFIG_BUILD_GENERAL=y`) — does `imply ACPI`, `imply DEVICETREE`,
  `imply DEFAULT_SMBIOS_ARM`, `imply SELECT_ALL_SHELL_COMMANDS`,
  `imply DEFAULT_SERIAL_PORT_CONSOLE_TEGRA`. **[vendor source]**
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/Kconfig ,
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/KconfigIncludes/BuildGeneral.conf ,
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/Tegra/DefConfigs/t23x_general.defconfig .
  The NVIDIA UEFI readme documents the "O/S Hardware Description Selection"
  menu (Device Tree / ACPI) for the Xavier-era mainline UEFI and notes
  that an ACPI serial console needs the `8250_tegra` driver. **[vendor,
  Xavier]** https://developer.nvidia.com/w/embedded/L4T/UEFI_Readme.html .
  Community: Windows 11 ARM installed on AGX Orin from USB with ACPI
  enabled in UEFI (Mar 2023; Hyper-V works, no GPU; NVIDIA: "We have not
  tried this yet") **[community]**
  https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/246176 ;
  the Fedora ARM maintainer on JetPack 6 UEFI: "In ACPI you get compute
  (cpu/memory/virt etc), PCIe, USB, network ... no display or accelerator
  support as yet. The Device-Tree mode is more feature full." **[community]**
  https://nullr0ute.com/tag/jetson/ .

### (2) Tegra234 facts a board startup needs

All from upstream `arch/arm64/boot/dts/nvidia/tegra234.dtsi` and
`tegra234-p3768-0000+p3767.dtsi` (Orin Nano Developer Kit), fetched and
grepped this session **[vendor source]**
https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi
https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/nvidia/tegra234-p3768-0000%2Bp3767.dtsi

| Block | Upstream DT fact | QNX-side note |
|---|---|---|
| CPU | `compatible = "arm,cortex-a78ae"` | `cpuid_a78ae.c`: MIDR `0x4100D420`, "Cortex-A78ae" **[local]** |
| GICv3 | GICD `0x0f400000` (64 KiB), GICR `0x0f440000` (2 MiB, one region), maintenance PPI 9; **no ITS node upstream** | `gic_v3.c` / `gic_v3_its.c` in libstartup.a; the NISV writeback-store issue above is irrelevant natively (no KVM trap) |
| Generic timer | `arm,armv8-timer` PPIs 13/14/11/10, `always-on`; Tegra TKE at `0x02080000` (`nvidia,tegra234-timer`) | `armv8_fm/main.c` reads `cntfrq_el0` for `timer_freq` |
| PSCI | `arm,psci-1.0`, `method = "smc"` (dmesg: PSCIv1.1) | `fdt_psci_configure()`, `psci_smc`, `reboot_psci_smc`, `psci_smp.o` all present |
| UARTs | `uarta` `0x03100000` and `uarte` `0x03140000` — `nvidia,tegra234-uart`,`nvidia,tegra20-uart` (8250-class, SPI 112 / 116), both `okay` on the devkit; `uarti` `0x031d0000` `arm,sbsa-uart` (SPI 285), `okay`, 115200 | `callout_debug_tegra.S` = "Similar to 8250 uart with 32-bit registers" (2015); `hw_serpl011` / `acpi_spcr_parse` handle SBSA/PL011 |
| Console | `aliases { serial0 = &tcu }`, `stdout-path = "serial0:115200n8"`; `tcu` is `nvidia,tegra234-tcu` over HSP **mailboxes** — no MMIO UART | Not drivable by a polled callout. NVIDIA (KevinFFF, Apr 2024): ttyTCU0 on the Orin Nano is backed by `uartc@c280000`; "we don’t suggest and support for this use case" of using it as a normal UART; the attempt by the user gave no TX signal **[vendor forum]** https://forums.developer.nvidia.com/t/enabling-ttytcu0-as-regular-uart-on-orin-nano/287340 . TCU muxing runs "in the Sensor Processing Engine (SPE) for Jetson Orin" **[vendor]** https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html |
| SD | `mmc@3460000` `nvidia,tegra234-sdhci`,`nvidia,tegra186-sdhci` (SPI 65) | no QNX driver for it known in the Everywhere install (not checked) |
| NVMe / PCIe | C4 `pcie@14160000` (M.2 Key-M, x4), C7 `pcie@141e0000` (Key-M, x2), C1 `pcie@14100000` (Key-E), C8 `pcie@140a0000` (Ethernet) | `callout_interrupt_t18x_{pcie,pcie_ic6,msi}.S` are **T18x** (Parker) callouts — fit for T234 unverified |
| TRM | "Jetson Orin Series SoC Technical Reference Manual" (~7,100 pp) via the Jetson Download Center; developer registration may be required **[community]** https://jetsonhacks.com/2022/03/23/jetson-orin-documents-available/ — the direct page returned HTTP 403 to this agent | — |

### (3) Prior art

- **NVIDIA position, three times, staff-authored [vendor forum]:**
  kayccc, 2020-07-27 (Xavier NX): "We do not have QNX support for Jetson
  Xavier NX platform, and no plan to do."
  https://forums.developer.nvidia.com/t/qnx-board-support-package-for-jetson-xavier-nx/144240 ;
  DaveYYY, 2024-02-29 (AGX Orin): "We don’t support QNX on Jetson. It’s
  only available on DRIVE platforms." / "L4T ... is the only OS supported
  on Jetson."
  https://forums.developer.nvidia.com/t/board-support-package-for-qnx-os/284463 ;
  kayccc, 2025-07-17: "There is no plan to support QNX OS on Jetson" —
  use DRIVE AGX Orin.
  https://forums.developer.nvidia.com/t/is-it-possible-to-port-qnx-os-to-nvidia-jetson-orin/339232 .
  Third-party hypervisors are "not supported on Jetpack release. You may
  see if there is a method to enable it" — unsupported, not hardware-locked
  (DaneLLL, 2025-10-30)
  https://forums.developer.nvidia.com/t/clarification-on-jetson-orin-hypervisor-support-hardware-lock-or-only-unsupported/348348 .
- **DRIVE OS QNX, who gets it [vendor]:** "import the qpkg corresponding
  to SDP 7.1 and QOS 2.2.2 EA required for DRIVE OS 6.0.6"; "Log into
  NVONLINE (partners.nvidia.com), and find the DRIVE OS 6.0.6 QNX SDK
  group"
  https://developer.nvidia.com/docs/drive/drive-os/6.0.6/public/drive-os-qnx-installation/common/topics/installation/debian-packages/install-drive-os-qnx.html .
  The DRIVE AGX SDK Developer Program is "available to companies and
  research institutions who have the appropriate agreements on file with
  NVIDIA and have been invited to participate"; "Login with a corporate
  or university email address"
  https://developer.nvidia.com/drive/agx-sdk-program — consistent with
  the CLAUDE.md "invitation-only" wording. (The 2022 blog says "generally
  available" but still requires program membership:
  https://developer.nvidia.com/blog/now-available-drive-agx-orin-with-drive-os-6/ .)
- **QNX on any Jetson generation:** none found. The QNX public startup
  library carries Tegra *DRIVE* lineage — `callout_debug_tegra.S` (2015),
  `callout_interrupt_t18x_*.S`, `cpuid_a78ae.c` (2023) — which is
  evidence of the T18x/Orin BSP heritage, not of a Jetson port **[local]**.
- **Non-Linux OSes on Orin via UEFI:** Windows 11 ARM on AGX Orin (ACPI,
  community, 2023); Fedora / RHEL 9.3 on AGX Orin (JetPack 6 UEFI,
  community). seL4 lists only Jetson TK1; the only Xen Jetson attempt is
  Nano (2020, no dom0 console); a 2023 freebsd-arm post reports that an
  ACPI-mode boot attempt did not go well — nothing conclusive for Orin.
  **[community]**

### (4) SDP 8.0 startup-library evidence

- **Docs say no:** the 8.0 `mkifs` page lists `uefi.boot` under x86_64
  only; the KB "How to boot in UEFI mode" is x86_64 (SDP 7.0/7.1); the
  8.0 building guide says "The BIOS or UEFI (x86) or the ROM monitor
  (ARM)"; the `startup-*` options page has no UEFI/ACPI option for
  AArch64. **[vendor]**
  https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html ,
  https://www.qnx.com/support/knowledgebase.html?id=5015Y0000017eFi ,
  https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/startup/startup_about.html ,
  https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/s/startup_options.html .
- **The install says otherwise [local]:**
  `target/qnx/aarch64le/boot/sys/uefi.boot` exists (239 bytes:
  `filter="mkifsf_uefi %a %s %i"`, `vboot=0xffffff8060000000`, "The
  build file MUST specify load address via the [image=] attribute");
  `mkifsf_uefi.exe` is in `host/win64/x86_64/usr/bin`;
  `aarch64le/usr/lib/libstartup.a` (246 members) contains
  `efi_entry_point.o uefi.o uefi_init.o uefi_io.o is_uefi_boot.o
  init_raminfo_uefi.o init_raminfo_efi.o efi_tweak_cmdline.o acpi.o
  acpi_spcr_parse.o board_find_acpi_rsdp.o board_find_acpi_rsdp_uefi.o
  board_find_efi_smbios.o` plus 20+ `fdt_*.o`, `psci_*.o`, `gic_v3*.o`,
  `callout_debug_tegra.o`, `callout_interrupt_t18x_*.o`, `cpuid_a78ae.o`,
  `hw_ser8250*.o`, `hw_serpl011.o`.
- **Source for all of it ships [local]:** the hypervisor-guest BSP zip
  (`BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip`, 452 files) carries
  `src/hardware/startup/lib/` with **Apache-2.0** headers (BlackBerry
  2022/2023; older QNX files under the QNXLicenseC Apache-2.0 header),
  public headers `lib/public/hw/uefi.h`, `hw/acpi.h`, `aarch64/gic_v3.h`,
  `arm/psci.h`, `startup.h`, and one board, `boards/armv8_fm/` (ARM FVP;
  its `main.c` is under the older "written license" QNX header). No
  `qemu-virt`, no Tegra board.
- **How the UEFI path works (from source) [local]:**
  `efi_entry_point(ImageHandle, SystemTable)` takes LoadOptions as the
  command line, `GetMemoryMap`, `ExitBootServices`, then `cstart()`;
  alternatively `is_uefi_boot()` validates `boot_regs[0..1]` as
  ImageHandle/EFI_SYSTEM_TABLE, `uefi_init()` keeps Boot Services alive
  until `uefi_exit_init()`; `init_raminfo_uefi()` builds the RAM map from
  the EFI memory map; `board_find_acpi_rsdp_uefi()` finds the RSDP via the
  EFI configuration table; `acpi_spcr_parse()` picks the debug device from
  SPCR — **PL011/SBSA interface types only** on aarch64 (no 8250/Tegra
  case). `_start.S` only branches to `cstart`, preserving x0–x3 into
  `boot_regs[]`. `hypervisor_init(0)` in `armv8_fm/main.c` "may switch the
  CPU to EL2&0 for VHE" — the hook a native QHV host needs, which is why
  EL2 hand-off in (1) matters.
- **Toolchain check (this session) [local]:** a minimal buildfile
  `[image=0x80000000] [virtual=aarch64le,uefi]` with `startup-armv8_fm`
  and `procnto-smp-instr` built with SDP 8.0.4 `mkifs` into a 1.77 MB
  file beginning `4d 5a` (`MZ`), `e_lfanew = 0x80`, then `50 45 00 00`
  (`PE`) and machine `64 aa` = **0xAA64 (AArch64)**. So the toolchain
  produces an AArch64 PE32+ container despite the x86_64-only table in the
  docs. **Not verified:** that its entry point reaches `efi_entry_point`
  (`armv8_fm/main.c` never calls `is_uefi_boot()`; it treats x0 as an FDT
  pointer) — nothing was booted.
- **AWS corroboration [vendor + inference]:** EC2 docs: "Default boot
  modes for instance types: Graviton instance types: UEFI"
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ami-boot.html — so
  the QNX OS 8.0 AMI (Graviton2) must enter via UEFI, matching the
  `efi_entry_point`/ACPI objects; whether it then uses ACPI or an FDT is
  unknown (the AMI release-notes page returned 404 / connection refused),
  and that startup is not in the public BSP list.

### (5) Licence: is personal-use porting to unsupported hardware permitted?

- **Governing document [vendor]:** the licence matrix
  (https://www.qnx.com/legal/licensing/document_archive/current_matrix.pdf)
  lists for SDP 8.0 a "Development License Agreement
  (Non-commercial/Academic)" → http://www.qnx.com/nc_qdl → **"QNX
  Development License Agreement (Non-Commercial License)", v7,
  2025-12-10**
  (https://www.qnx.com/download/download/51624/BB_QNX_Development_License_Non-Commercial_License_Class_v7_2025-12-10.pdf).
  The older NCEULA v.019 (2018) is superseded but states the intent
  plainly: non-commercial developers may use the Software for "extending
  hardware or peripheral support for the QNX Neutrino RTOS" (4.2(a)).
- **v7 grant, clause (iii):** "access, use, link and compile the Software
  (including Runtime Subsystems and authorized derivative works of
  Software) on Developer Systems solely in order to develop, evaluate,
  research, experiment with, test, debug, profile, maintain, support,
  demonstrate and discuss uses of Non-Commercial Applications and/or
  Non-Commercial Target System(s), **which includes rights to modify the
  Software supplied as Source Code** and to install and use Runtime
  Subsystems on or in connection with the ... Non-Commercial Target
  System(s) developed". "Non-Commercial Target System(s)" is "any
  product, device, component, or system (containing software or software
  and hardware components) in which Runtime Subsystems operate ...
  provided the target system is built for Non-Commercial Purpose(s)" —
  **no hardware list, no supported-board restriction.** Custom code is
  "Experimental Software", provided as-is.
- **v7 restrictions, 4.6:** (c) no reverse engineering, decompiling,
  disassembly "except and only to the extent any foregoing restriction is
  prohibited by applicable law"; (d) do not "modify any Software delivered
  in binary code"; (g) no distribution to third parties; (b) only on
  systems owned or controlled by the Developer; **(i) do not "release,
  publish, and/or otherwise make available to any third party the results
  of any performance or functional evaluation of the Software without the
  prior written approval of BlackBerry"**. The BSP startup sources
  additionally carry their own Apache-2.0 headers **[local]**.
- **Precedent [vendor]:** the BlackBerry-owned
  https://github.com/qnx/bsp_raspberrypi-bcm2711-rpi4 — a source-only SDP
  8.0 BSP for driver development, "Experimental Software (SQML 1)"; the
  QNX Everywhere page names only Raspberry Pi as ready-made hardware
  (https://qnx.software/en/developers/get-started/qnx-everywhere); the
  licensing page permits hobbyist/maker builds "provided you do not make a
  commercial product"
  (https://qnx.software/en/developers/get-started/qnx-everywhere/licensing).
- **Two flags for the Architect / Cyber / Docs agents, not decided here:**
  the 2026-07-28 root cause disassembled the shipped `startup-qemu-virt`
  binary (4.6(c)); the 2026-09-08 move to the Apache-2.0 `gic_v3.c` source
  is the cleaner footing. And 4.6(i) reads on every published latency and
  boot-time number in this repo.

### Looked for and not found

- Any NVIDIA statement that the **Orin Nano** UEFI exposes the ACPI /
  "O/S Hardware Description" toggle (evidence is AGX Orin community
  reports plus the Kconfig `imply ACPI` for the T23x general build); the
  `KconfigIncludes/SocT23X.conf` file (404 at the guessed paths), so
  whether `SOC_T23X` satisfies the `SOC_GENERAL` gate on `TEGRA_ACPI` is open.
- Any QNX port to any Jetson generation; any working seL4 / Xen / Zephyr /
  FreeBSD port to Orin.
- A documented AArch64 UEFI startup in 8.0 (docs say `uefi.boot` is
  x86_64-only); the QNX OS 8.0 AMI release notes (404 / refused); how the
  AMI startup enters.
- Tegra234 TRM contents (login-gated, HTTP 403); which physical UART is on
  the Orin Nano 40-pin header; whether `callout_interrupt_t18x_*` fits
  T234 PCIe/MSI; UEFI spec 2.3.6 text (uefi.org 403 — TF-A and Linux
  `booting.rst` used instead).
- **Requires running/booting to confirm:** that the `mkifsf_uefi` AArch64
  image entry point reaches `efi_entry_point`; that a Tegra234 startup
  written against `armv8_fm` boots at all.

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
