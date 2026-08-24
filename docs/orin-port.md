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

- [x] `sudo scripts/orin/setup-bridge-orin.sh` — ran clean (script needed no changes; only a CRLF-strip on the transferred copy, a Windows-checkout artifact, not a script bug)
- [x] Verified `br0` (192.168.100.1/24) and `tap-qnx` exist; on Orin the Linux client runs natively so no `tap-linux` is created
- [x] Verified L4T native userspace can reach the QNX guest at `192.168.100.10` (not `192.168.100.1` — that's the bridge's own address; the guest is the far side) — real `ping` RTTs, 0% loss

### 4. Transfer the cloud-twin IFS

- [x] **Rebuilt, not the untouched Phase-1 IFS** — see the 2026-07-28 status header: `qnx-safety-vm` was rebuilt from the same baseline `local/options` via `mkqnximage --type=qemu --arch=aarch64le --hostname=qnx-safety --build` (invoked from the Windows build host; had to go through `cmd.exe //c ...`, not plain bash — see the "Windows/MSYS gotcha" note below) with two new `local/snippets/*.custom` files staging `qnx-server-net`'s binary and forcing the static IP. Honest deviation from "same IFS, zero changes": the *code* (`ipc-test/`) is new/additive as scoped, and this rebuild is the config-and-staging mechanism that carries it — not a change to Phase-1's boot/BSP behaviour. **Reproducibility note:** `qnx-safety-vm/` is entirely gitignored (mkqnximage-derived), so the two `local/snippets/*.custom` files staged directly during this pass would NOT survive in git on their own. [`scripts/build-qnx-ifs-orin.bat`](../scripts/build-qnx-ifs-orin.bat) (new, mirrors `build-qhv.bat`'s staging pattern for `build-qnx-ifs.bat`) is the committed, reproducible recipe: it builds `ipc-test`, stages [`scripts/orin/qnx-safety-vm-post_start.custom`](../scripts/orin/qnx-safety-vm-post_start.custom) (the committed source of truth for the static-IP + auto-start logic) plus a freshly-generated `ifs_files.custom` (one line, an absolute host path, regenerated every run — not committed, same as `build-qhv.bat`'s own `ifs_files.custom`/`data_files.custom`), then calls `build-qnx-ifs.bat`. Not re-run after being written (the already-verified rebuild from the manual steps stands); a future session should use this script rather than repeat the manual `local/snippets/` edit.
- [x] `sha256sum output/ifs.bin output/disk-qemu output/disk-qemu.vmdk > output/SHA256SUMS` (Git Bash on the Windows build host)
- [x] `scp output/{ifs.bin,disk-qemu,disk-qemu.vmdk,SHA256SUMS} haochen@<orin-ip>:~/qnx-orin-test/`
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
