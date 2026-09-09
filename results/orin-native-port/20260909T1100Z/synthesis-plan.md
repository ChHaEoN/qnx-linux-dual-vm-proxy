# Orin Nano native QNX SDP 8.0 / QNX Hypervisor 8.0 port — synthesised plan

Synthesiser output, 2026-09-09. Built from the winning design (`orin-nano-native-qnx-volatile-first`, 42/39/44 across three judges) with every graft the judges asked for, every step a judge marked fatal removed or demoted to a labelled alternative, and a handful of corrections found by the synthesiser's own read of the Apache-2.0 BSP source and the H3 board captures.

Evidence classes are used on every load-bearing statement:
`VERIFIED` (seen: file:line, command output, live-board capture), `VENDOR_CLAIM` (a document says so), `HYPOTHESIS` (reasoned, untested), `UNKNOWN`. "VERIFIED (synth)" means the synthesiser re-read it today in `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/` (Apache-2.0 files only) or in `results/orin-native-port/20260909T1100Z/raw/`.

Redaction: `<user>`, `<orin-ip>`, `<orin-key>` throughout. No QNX binary was disassembled; no QNX source, header, binary or IFS is to be copied into the repo.

---

## 1. Goal and non-goals

**Goal.** Boot QNX SDP 8.0 natively on the Jetson Orin Nano Developer Kit (Tegra234, 6x Cortex-A78AE, L4T R36.4.7 / UEFI 36.4.4), reach the QNX Hypervisor 8.0 host at real EL2 (`-Q enable,el2-host`, VHE), boot the **byte-identical** cloud-leg QNX guest under it, and produce the first hardware-timed QHV numbers on this silicon:

- M3: host-clock `qvm` launch -> guest banner (comparable to the twin legs' `qvm_launched -> guest_banner` segment);
- M4: per-exit hypervisor dwell (qvm Class-10 Guest Exit -> next Guest Entry) P50/P99/max in the `scripts/twin/diff-results.sh` CSV schema.

Both feed `docs/digital-twin-design.md` §1a as a **third host bundle** (native Orin / no QEMU / VHE), not as a one-variable diff.

**Non-goals (deliberate).** No storage, network, USB, display, GPU, SMMU or PCIe drivers; no Linux guest on the native leg; no cold-boot number unless the optional UEFI cross-check (M5) happens; no publication of any number or functional log before the licence consultation (§9); no reflash, no QSPI/UEFI-variable/extlinux/ESP writes on the primary path; no KVM work (the GICv3/NISV defect is a separate track).

**Kill criteria.** (a) M0 shows CurrentEL != 2 at kexec entry -> the kexec leg is dead; pivot to the UEFI Shell alternative (§3.5). (b) TCU, uarta, black box and LED all silent -> the port cannot be observed; stop until the adapter arrives. (c) `-T` probe says INTID 28 absent AND `el1-host` also fails to arm -> no hardware-timed QHV number from this board; the finding itself is the deliverable.

---

## 2. What changed relative to the three designs

### 2.1 Steps removed as fatal (never do these)

| # | Step | Why removed | Replacement |
|---|------|-------------|-------------|
| F1 | 64-byte Image header with `text_offset = 0x7FFC0` (Design 3) | Kernel segment lands at `hole+0x7FFC0 = 0x8007FFC0`, not page-aligned; v5.15 `sanity_check_segment_list()` returns `-EADDRNOTAVAIL`, kexec-tools `add_segment_phys_virt()` dies "not page aligned" (VERIFIED by the judges' fetches; consistent with `image_load()` doing `mem += text_offset`) | 4 KiB shim page, `text_offset = 0x80000`, IFS at `[image=0x80081000]` (§3.2) |
| F2 | `efibootmgr -c ... -L QNX` then `-n` as a "one-shot" (Design 2) | `-c` also prepends the entry to `BootOrder` (VERIFIED by judges in rhboot/efibootmgr source); a hanging PE becomes the default boot; every attempt writes the QSPI variable store | Never on the primary path. If the UEFI cross-check is ever run: launch from the FV-embedded UEFI Shell (Boot0007, VERIFIED present) which writes nothing; if a Boot#### is unavoidable, `efibootmgr -C` (create-only) + `-n`, after recording `efibootmgr -o` |
| F3 | `gic_v3_set_paddr(gicd, gicr, its)` (Design 1 as written) | Auto-sizes `gicr_index_limit = board_smp_num_cpu()` (VERIFIED synth gic_v3.c:327-332); the affinity walk `ASSERT(gicr_index < gicr_index_limit)` (VERIFIED synth gic_v3.c:1345-1352) fires for CPU4/5 in frames 6/7 | `gic_v3_set_paddr_range(0x0F400000, 0x0F440000, 0x200000, NULL_PADDR)` -> limit 16 |
| F4 | Library `psci_cpu_id()` unchanged (Designs 1 and 3) | Returns the index verbatim (VERIFIED synth psci_cpu_id.c); `psci_smp_start()` passes it straight to CPU_ON (VERIFIED synth psci_smp.c:37); MPIDR 4/5 do not exist on this SKU | Board `psci_cpu_id()` override mapping index -> {0x0,0x100,0x200,0x300,0x10200,0x10300} from the FDT `cpu@` reg cells |
| F5 | Per-boot startup options via `kexec --append` (Design 1 as written) | `fdt_tweak_cmdline()` only appends `/chosen/bootargs` tokens to a `bootargs_entry` (VERIFIED synth fdt_tweak_cmdline.c:70-105) and `setup_cmdline()` runs before `main()` (VERIFIED synth _main.c:128-146) | Default: rebuild the IFS per option change (seconds). Optional: `main()` parses a `qnx.` token family from `/chosen/bootargs` itself and sets the library globals `max_cpus`, `debug_flag` (VERIFIED synth startup.h:605,614; common_options.c:151-156) and calls `hypervisor_set_options()` (VERIFIED synth cpu_common_options.c:107-120) before `hypervisor_init(0)`/`init_smp()` — mechanism VERIFIED, integration HYPOTHESIS |
| F6 | `-W` "leave the L4T-armed WDT0 counting for free auto-reset" (Design 3 graft) | The live DT has `/bus@0/watchdog@2190000 status = "disabled"` (VERIFIED synth raw/orin-devicetree.txt:432-434) and no `wdt`/`watchdog` line appears in any dmesg capture (VERIFIED synth grep over raw/) — Linux never arms it. NVIDIA's "120 s reset under L4T" is a VENDOR_CLAIM about a different DT state | Shim reads and prints WDT0/WDT1 CR+SR at M0; arming is a shim option that is OFF by default (`shim.wdt=<s>`), HYPOTHESIS until the M0 hang-mode test proves it fires |
| F7 | Design 3 M5 entering UEFI via library `_start -> cstart` then `is_uefi_boot()/init_raminfo_uefi()` | `cstart -> _start_el2_or_el1 -> at_el2` turns off SCTLR_EL2.{M,C,I} and rewrites HCR_EL2 while Boot Services are live (VERIFIED synth _start_el1.S:125-156, cstart.S:70); `init_raminfo_uefi()` calls `GetMemoryMap` live (VERIFIED synth init_raminfo_uefi.c:36-55) | UEFI variant only: board `_start.S` = `b efi_entry_point` (VERIFIED synth efi_entry_point.c:47-94 ordering: ConOut print, map snapshot, ExitBootServices, `cstart()`), `init_raminfo_efi()` over the snapshot, DTB via `uefi_find_config_tbl(DEVICE_TREE_GUID)` (uses the global set at efi_entry_point.c:51; VERIFIED synth uefi.c:35-46), never `is_uefi_boot()/uefi_init()` on that path |

### 2.2 Demoted (kept only as a labelled fallback)

- **Self-relocating shim (memmove to 0x80081000).** Judge 2 notes it can self-clobber when `0 < delta < image size`. Demoted to a build flag `SHIM_RELOCATE=1` with an explicit overlap guard; the default shim prints its PC and `x0`, compares with the link address, and on mismatch prints `BAD-LANDING pc=... expect=...` and PSCI `SYSTEM_RESET`s. Placement is then fixed by rebuilding `[image=]` (kexec_file) or `--mem-min/--mem-max` (kexec_load).
- **`devc-tcu` resource manager.** Off the M1 critical path (M1b). `tcu-cat` (mmap writer) is the M1 output path; the interactive shell first tries the Linux-preconfigured uarta with the stock `devc-ser8250`.
- **Full EL2 normalisation in the shim.** Library `at_el2` already does SCTLR_EL2 M/C/I off + cache flush, HCR_EL2 wholesale = RW|HCD (+API/APK), CPTR_EL2 = 0, CNTHCTL_EL2 = 3, VMPIDR/VPIDR, CNTVOFF/VTTBR = 0, ICC_SRE_EL2 = 0xF (VERIFIED synth _start_el1.S:125-190) and is reached both from `cstart` (cstart.S:70) and from every secondary's `smp_start` (VERIFIED synth smp_start.S:37). The shim keeps only what the library does not touch (§3.3); the full set stays behind `SHIM_FULL_NORMALISE=1` for bisecting.

### 2.3 Facts the synthesiser added

- Secondary CPUs also pass through `at_el2` (smp_start.S:37) -> no board-side normalisation is needed on the secondary path.
- `init_smp()`'s `start_aps()` waits on a 32-bit counter and calls `ap_fail()` when it wraps (VERIFIED synth init_smp.c:66-80) -> a CPU that never starts ends in a startup failure message, not a silent hang.
- `hypervisor_init()` is called from `main()` and validates `CurrentEL == 2` and `ID_AA64MMFR1_EL1.VH` for `el2-host` (VERIFIED synth hypervisor.c:32-58, hypervisor_setup.c:50-66).
- `init_qtime()` = `init_qtime_v8gt(27, 28)` and `qtime->intr = 28` only when the required flags are exactly `ENABLED|EL2_HOST` (VERIFIED synth init_qtime.c:28, init_qtime_v8gt.c:56-60); it also writes `cntv_ctl_el0 = 0` (v8gt.c:66).
- `gic_v3_initialize()` itself writes `GICD_CTLR = 0` + RWP wait, `ICENABLERn/ICPENDRn = 0xFFFFFFFF` for all SPIs, and per-CPU `GICR ICPENDR0/ICENABLER0` + WAKER handling (VERIFIED synth gic_v3.c:980-1000, 1358-1369, 1496-1502) -> the board pre-quiesce (§5.3) is belt-and-braces; the one thing the library does not do is `ICACTIVER` clearing, which the pre-quiesce adds.
- The L4T kernel has a live pstore console zone: `printk: console [ramoops-1] enabled` (VERIFIED synth raw/orin-ttys.txt:67-68) and the DT node is `compatible = "ramoops"`, `reg = 0x2725F0000/0x200000`, `no-map` (VERIFIED synth raw/orin-devicetree.txt:177-185). Zone sizes remain UNKNOWN (§4.6).
- Guest IFS identity for the twin claim: `qhv/guest/output/ifs.bin` = 9,783,916 B, sha256 `968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f` (VERIFIED synth, `sha256sum` today).

---

## 3. Loader

### 3.1 Primary: `kexec_file_load` from the running L4T, 4 KiB shim + raw IFS

Why: every question it raises is inside code we write; nothing persistent is touched (no ESP, no UEFI variables, no extlinux, no QSPI, no `/boot`); recovery is a power cycle to an untouched L4T; iteration is `scp` + two commands; the console the payload inherits is the one Linux is printing on at the hand-off instant.

Board preconditions (all VERIFIED in raw/orin-kexec.txt): `CONFIG_KEXEC=y`, `CONFIG_KEXEC_FILE=y`, `# CONFIG_KEXEC_SIG is not set`, `kexec_load_disabled = 0`, no lockdown, Secure Boot disabled, kexec-tools 2.0.22 installed, `kexec_loaded = 0`.

### 3.2 Payload layout (the F1 fix, both syscalls)

`t234-qnx.kimg` = `[4 KiB shim page]` || `[ifs.bin built with [image=0x80081000] [virtual=aarch64le,raw]]`.

Shim page byte 0 is the 64-byte Linux arm64 Image header: `code0 = b shim_body`, `code1 = nop`, `text_offset = 0x0000_0000_0008_0000`, `image_size = total file size rounded up to 2 MiB`, `flags = 0` (unspecified page size, LE), `magic = "ARM\x64"` at 0x38. The header must be **prefixed**, not overlaid: the shipped raw.boot stub's three instructions occupy bytes 0x00-0x0B, so its third instruction sits where `text_offset` goes, and no shipped IFS carries the magic (VERIFIED raw/ifs-first-64-bytes.txt; opcodes withheld — the repo does not publish machine code of QNX-shipped binaries, QDL v7 4.6(c)).

Placement arithmetic (VERIFIED by the researchers' reads of `arch/arm64/kernel/kexec_image.c` and `horms/kexec-tools`): `kbuf.memsz = image_size + text_offset`, bottom-up from `buf_min = 0`, 2 MiB alignment -> first System RAM range `0x80000000-0xBDFFFFFF` (VERIFIED raw/orin-iomem.txt:180) -> `kernel_segment->mem += text_offset` = `0x80080000`, `memsz = image_size` (page-aligned) -> passes `sanity_check_segment_list()`. Header at `0x80080000`, shim body in the same page, IFS at `0x80081000`. The raw.boot stub reads the 32-bit `startup_vaddr` with a word-sized load (~`0x80081daX`), which fits. HYPOTHESIS: the running system's first hole is exactly `0x80000000` (nothing excludes it: Linux stages kexec segments in kimage pages and copies at exec time, so the running kernel's own use of that RAM does not matter). The shim's PC check catches a wrong landing.

DTB: `kexec_file_load` clones `initial_boot_params`, rewrites `/chosen` (`bootargs`, initrd, kaslr-seed) and places it **top-down** above the image (VERIFIED researcher read of `load_other_segments`) -> far from the 992 MiB window. `startup` still calls `avoid_ram(fdt_paddr, fdt_size)` unconditionally. HYPOTHESIS: `/chosen/linux,uefi-mmap-start/size/desc-size` survive the clone (only initrd/bootargs/elfcorehdr are deleted) — matters only for the optional M3+ EFI-map walk.

### 3.3 Entry contract and shim duties

Entry (VERIFIED by upstream source reading in research-kexec-tcu.md; NVIDIA's 5.15.148-tegra fork NOT read — UNKNOWN whether it diverges): EL2 (VHE kernel -> `is_hyp_nvhe()` false -> direct `br`), MMU/caches off (the `sctlr_el1` write aliases SCTLR_EL2 under E2H), `x0 = DTB PA`, `x1-x3 = 0`, DAIF masked, image cleaned to PoC, exactly one CPU online (others PSCI `CPU_OFF`, `AFFINITY_INFO` polled OFF). Inherited and NOT cleaned by Linux: `HCR_EL2.E2H=1/TGE=1`, stale `VBAR_EL2`, armed EL2 physical timer (Linux's `arch_timer` on INTID 26, VERIFIED raw/orin-firmware-el.txt), live GICD/GICR, `MDCR/HSTR/ICH_HCR_EL2` as Linux left them.

Shim (pure asm, position-independent, no stack, `x0` preserved in `x20`), in order:

1. `VBAR_EL2 = shim vectors`; every vector prints `EXC <n> ESR=.. ELR=.. FAR=..` over the TCU (and into the black box if enabled) then PSCI `SYSTEM_RESET` (SMC `0x84000009`). These vectors stay live through startup because the library writes only `vbar_el1` (VERIFIED synth cstart.S:77-78, smp_start.S:43-44) and `vbar_el2` only under `-Q enable,el1-host` (VERIFIED synth hypervisor_enable.S:38-43).
2. Register bank print, one line: `T234-SHIM EL=<n> HCR=.. SCTLR2=.. MMFR1=.. MPIDR=.. CNTFRQ=.. CNTHCTL=.. CNTHP_CTL=.. MDCR=.. WDT0CR/SR=.. WDT1CR/SR=.. TXMB=<raw 0x0C168000 word before first write> PC=.. X0=.. DTBMAGIC=..`.
3. `CurrentEL != 2` -> print `EL!=2 abort`, `SYSTEM_RESET` (kill criterion (a)).
4. Minimal normalisation of what the library does not touch: with E2H still 1, `CNTP_CTL_EL0 = 0` and `CNTV_CTL_EL0 = 0` (aliases of CNTHP/CNTHV under E2H — kills Linux's armed INTID 26 timer); then `HCR_EL2 = 0x8000_0000` (RW only; E2H=0, TGE=0) + `ISB` (cheap; also guarantees the E2H flip has an ISB before the library's own write at _start_el1.S:161, which has none — HYPOTHESIS that this matters); `CNTHP_CTL_EL2 = 0`, `CNTV_CTL_EL0 = 0`, `CNTP_CTL_EL0 = 0` (EL1 views now); `MDCR_EL2 = 0`; `HSTR_EL2 = 0`; `ICH_HCR_EL2 = 0`. Everything else (SCTLR_EL2, CPTR_EL2, CNTHCTL_EL2, CNTVOFF/VTTBR, ICC_SRE_EL2, VMPIDR/VPIDR, cache flush) is left to `at_el2` (VERIFIED synth) unless `SHIM_FULL_NORMALISE=1`.
5. Optional dead-man: `shim.wdt=<seconds>` arms TKE WDT0 (`WDTUR = 0xC45A` unlock, `WDTCR` period/enables/source TMR7, `WDTCMDR` start; register model VERIFIED from `timer-tegra186.c`). Default OFF (F6). Whether NS-EL2 may arm it and whether it resets the SoC is HYPOTHESIS/UNKNOWN (WDTSCR lock state).
6. Landing check: `adr` of the shim page vs. the baked link address (`0x80080000`); mismatch -> `BAD-LANDING ...` + `SYSTEM_RESET` (or memmove if `SHIM_RELOCATE=1`, with the overlap guard: refuse when the destination range overlaps the shim page or `[x0, x0+fdt_totalsize)`).
7. Modes (`shim.mode=probe|hang|jump`, from a header reserved byte or `/chosen/bootargs` scanned by the shim): `probe` = bank print then `SYSTEM_RESET`; `hang` = bank print, arm WDT if asked, `wfi` loop (tests unattended recovery); `jump` = `mov x0,x20; x1=x2=x3=0; br 0x80081000` into the raw.boot stub (which uses only `x19` before `br startup_vaddr`, VERIFIED first 12 bytes).

### 3.4 Owner command sequence (every step reversible; nothing persistent)

```
# 0. one-time, zero-risk acceptance test (loads into kernel memory, no reboot):
sudo kexec -s -l t234-shim.kimg ; cat /sys/kernel/kexec_loaded ; sudo kexec -u
# 1. hazard check (see below), then quiesce DMA masters:
cat /etc/default/kexec ; systemctl status kexec-load.service kexec.service
sudo systemctl isolate multi-user.target
sudo rmmod nvidia_drm nvidia_modeset nvgpu      # ignore failures
# 2. pin the clock and pre-arm the uarta fallback console (both HYPOTHESIS that they persist):
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq        # record it
sudo stty -F /dev/ttyTHS1 115200 raw ; sleep 100000 < /dev/ttyTHS1 &
# 3. load and go (under setsid nohup so the ssh drop does not kill it):
sudo kexec -s -l t234-qnx.kimg --append='qnx.v=3 qnx.P=1'   # append only if main() parses it
sudo systemctl kexec            # clean unmount of the SD ext4, then kernel_kexec()
```

**kexec-load hazard (Judge 3 addition, HYPOTHESIS until read):** Debian/Ubuntu kexec-tools ships `/etc/default/kexec` (`LOAD_KEXEC=`) and a `kexec-load` shutdown unit that re-runs `kexec -l /boot/vmlinuz...` during shutdown and would silently replace the QNX payload with Linux. If `LOAD_KEXEC=true`, do **not** edit the file (persistent config); use `sudo systemctl mask --runtime kexec-load.service` (evaporates at reboot) for the session, or `sync && sudo kexec -e` directly from `multi-user.target` (accepting an unclean SD unmount, journal replay, not a brick).

Forum precedent (VENDOR_CLAIM, threads 344580/365485): kexec on Orin NX only worked with `nvidia_drm` unloaded (SMMU "Blocked unknown Stream ID" / EMEM errors otherwise) — the module unload is precautionary against live display DMA into memory the payload will own.

### 3.5 Fallbacks

**Fallback A — `kexec_load` via purgatory (same EL, `x0 = dtb`):** `sudo kexec -c -l t234-qnx.kimg --dtb=<edited.dtb> --mem-min=0x80000000 --mem-max=0xBDFFFFFF -i` then `systemctl kexec`. Allows an edited DTB (e.g. add `"arm,psci"` to `/psci/compatible` and a `/memory@80000000` node so unmodified `fdt_psci_configure()`/`init_raminfo_fdt()` could be used) and pins placement; `-i` skips the purgatory SHA-256 pass; `kexec -d` prints segment addresses on this path (VERIFIED kexec-tools options exist).

**Fallback B — UEFI PE launched from the UEFI Shell (explicitly labelled alternative; not on the primary path; also serves as the optional M5 cold-boot cross-check):** build the same IFS with `[image=<addr>] [virtual=aarch64le,uefi]` (mkifsf_uefi emitting an AArch64 PE32+ is REPORTED by two sessions, not reproduced — U15), with the UEFI-variant board `_start.S = b efi_entry_point` (F7), `init_raminfo_efi()`, DTB via `uefi_find_config_tbl(DEVICE_TREE_GUID b1b621d5-f19c-41a5-830b-d9152c69aae0)`. Copy the PE to the ESP as a **new** file only (`EFI/QNX/qnx-orin.efi`; `/boot/efi` = mmcblk0p10, 64 MB, VERIFIED) after backing up `extlinux.conf` and `BOOTAA64.efi`; press ESC on the J14 console at the UEFI banner -> Boot Manager -> UEFI Shell (Boot0007) -> `fs0:\EFI\QNX\qnx-orin.efi`. Zero variable writes. Known open items: relocation-stripped PE only loads at its ImageBase (HYPOTHESIS: `0x80000000` is where the firmware's own DXE/heap lives -> try `0x90000000`-range `[image=]` first; check the PE header for `RELOCS_STRIPPED` with `readelf`/`od`, not disassembly); PE entry reaching `_start` (U2); `M0` signal is the ConOut line `Entering startup...` (VERIFIED synth efi_entry_point.c:49). A LoadImage failure produces a firmware error line in the shell instead of silence — the reason the Shell is preferred over any Boot#### entry.

**Rejected outright:** replacing `EFI/BOOT/BOOTAA64.efi`; GRUB chain-load; any Boot#### created with `efibootmgr -c`; `L4TDefaultBootMode` changes; a default-label `LINUX=` swap in `extlinux.conf`; `kexec -p`; editing `/etc/default/kexec`; any QSPI / BCT / nvbootctrl / A-B slot change; any reflash.

---

## 4. Console strategy

### 4.1 Primary: Tegra Combined UART (TCU) via the HSP shared mailbox, polled

**Addresses (VERIFIED by three independent sources that agree):** TX = AON HSP `hsp@c150000` shared mailbox 1 = `0x0C150000 + 0x10000 + 1*0x8000 = 0x0C168000`; RX = TOP0 HSP `hsp@3c00000` shared mailbox 0 = `0x03C00000 + 0x10000 = 0x03C10000`. Sources: live DT `mboxes = <&hsp_top0 SM 0>, <&hsp_aon SM 0x80000001>` (32-bit SM type, raw/orin-devicetree.txt:288-289, phandles resolved in raw/orin-followup.txt), Linux `tegra-hsp.c` formula `regs + SZ_64K + i*SZ_32K`, edk2-nvidia `Kconfig` defaults `DEBUG_SERIAL_PORT_TCU_TX_MAILBOX 0x0C168000 / RX 0x03C10000` and `NVIDIA.common.dsc.inc` at r36.4.3.

**Word format (VERIFIED, bit-for-bit identical in two BSD-licensed references — edk2-nvidia `TegraCombinedSerialPortLib.c` (BSD-2-Clause-Patent) and TF-A `plat/nvidia/tegra/drivers/spe/shared_console.S` (BSD-3); the GPL `tegra-tcu.c` was used only as a cross-check of the same facts):**
bits 0-23 = up to three data bytes (byte i in bits 8i..8i+7); bits 24-25 = byte count 1..3; bit 26 = Flush; bit 27 = HwFlush; bits 28-30 reserved; bit 31 = FULL / doorbell (set by the writer, cleared by the SPE when consumed).

**Writer:** poll until `[TX] & BIT31 == 0` with a **bounded** spin (CNTPCT-based, ~20 ms; TF-A uses 0xC000 iterations, UEFI spins forever, Linux flushes with 1000 ms — we must never hang on a dead SPE), then `str32 [TX] = BIT31 | BIT26 | (n<<24) | bytes`. One byte per word in the shim and kernel callout (simplest); three per word in `tcu-cat`. On timeout: drop the byte, increment a counter printed later as `TCU drops=<n>`.

**Reader (kernel `poll_key` only, needed for KD/interactive over TCU, M1b):** if `[RX] & BIT31`: n = bits 24-25, bytes = bits 0-23; consume byte 0, stash up to two leftovers in the callout rw area; write `0` to `[RX]` to release. Release-by-zero is HYPOTHESIS (UEFI's `Initialize()` zeroes both mailboxes; its `Read()` body was not quoted) — confirm against the BSD edk2 Read path before writing the callout.

**Access rules:** 32-bit accesses only; device memory (`PROT_NOCACHE` / callout device mapping); TX and RX are in different 4 KiB pages and different HSP blocks, so two mappings.

**Physical side (VENDOR_CLAIM, two NVIDIA sources that disagree on pin direction):** the SPE demuxes the CCPLEX stream onto the J14 12-pin button header, UART2 (DEBUG), 3.3 V, 115200 8N1; Board Automation page says pin 3 = UART2 TXD, carrier spec SP-11324-001 Table 3-4 says pin 4 = UART2_TXD (module output); pin 11 = GND. Wire adapter RX to pin 4 first, swap to 3 if silent. The same header shows the MB1/MB2/UEFI/L4T logs, so the wiring is validated by the L4T boot log before any QNX code exists.

**What is proven and what is not:** address and bit layout VERIFIED; CCPLEX access from EL2 pre-OS VERIFIED (UEFI does exactly this); RX routed to the CCPLEX stream VERIFIED under Linux (`serial-getty@ttyTCU0` holds `/dev/ttyTCU0`, raw/orin-ttys.txt). **HYPOTHESIS: the SPE keeps draining the mailbox after Linux is gone** — the kexec path never touches HSP/SPE/BPMP, the SPE served the same mailbox for MB1/MB2/UEFI before Linux, and Linux prints "Bye!" on this path microseconds before the jump, but nobody has written the mailbox from a non-NVIDIA payload after a kexec. Bounded polls make a dead SPE degrade to silence, never a hang.

### 4.2 Four implementations of the one protocol (all our own code)

1. **Shim asm** (M0): `tcu_putc`, hex printers, the register bank.
2. **`hw_sertcu.c`** (`init_tcu()`/`put_tcu()` for the `struct debug_device` table, VERIFIED synth startup.h:183-190/410) — device string `"0x0C168000,0x03C10000"`; `init_tcu()` sends `\n` with Flush|HwFlush as UEFI's `Initialize()` does.
3. **`callout_debug_tcu.S`** (`display_char_tcu` / `poll_key_tcu` / `break_detect_tcu -> 0`) modelled on the Apache-2.0 `callout_debug_tegra.S` patch/aperture pattern with two patched apertures; procnto's `kprintf`, `display_msg` (goes through `display_char`, VERIFIED local callout_debug.html), kernel crash dumps and KD use it.
4. **`tcu-cat`** (~60 lines C, M1): `mmap_device_memory(0x0C168000, 4096, PROT_READ|PROT_WRITE|PROT_NOCACHE, 0)`, copies stdin to the mailbox with bounded polls; `-m "text"` prints an argument. Pipes `pidin | tcu-cat`, `traceprinter ... | tcu-cat`, `cat /dev/ttyp0 | tcu-cat`, `cksum ... | tcu-cat`. Plus **`stamp`** (~30 lines): reads stdin, prints `ClockCycles()` when a given substring passes through, forwards to stdout. No resource manager anywhere on the M1-M4 path.
5. **`devc-tcu`** (M1b, optional, ~200 lines io-char/resmgr, polled RX at ~1 kHz, publishes `/dev/tcu`) only if an interactive shell over the TCU is wanted and uarta (§4.4) does not work.

Throughput ceiling: the SPE's physical UART at 115200 baud, ~11 KB/s — fine for logs, marginal for traces (M4 filters on-target).

### 4.3 Kernel-debug console in startup and procnto

`select_debug(debug_devices, ...)` with entry 0 = `tcu` (default), 1 = `pl011` @ `0x031D0000` (shipped `hw_serpl011` + `callout_debug_pl011`), 2 = `tegra8250` @ `0x03100000^2` (shipped `hw_ser8250` + `callout_debug_tegra`, LSR at +0x14, THR at +0x00, VERIFIED synth callout_debug_tegra.S read by H2; `^shift` honoured by `hw_ser8250.c`, VERIFIED H2). `-D <name>` selects.

### 4.4 Fallback console: uarta (`serial@3100000`, ttyTHS1) pre-configured by Linux

The 40-pin J12 header carries UART1 = uarta (pins 8 TXD / 10 RXD per the carrier spec Table 3-3 and jetson-gpio; VENDOR_CLAIM — community sources also say 22/32, so try 8/10 first), 3.3 V, SPI 112 = INTID 144, free under L4T (no process holds `/dev/ttyTHS1`, VERIFIED raw/orin-ttys.txt). Register map: 16550 at 4-byte stride (`8250_tegra.c` `UPIO_MEM32`, `regshift 2`; `serial-tegra.c` same helpers — VERIFIED researcher read). Clock/reset are BPMP-owned (`clocks = <&bpmp 0x9b>`, `resets = <&bpmp 0x64>`, VERIFIED DT) — **HYPOTHESIS:** opening `/dev/ttyTHS1` at 115200 from Linux before kexec leaves the port clocked, out of reset and with a valid divisor at hand-off (serial-tegra has no shutdown hook). Then: startup `-D tegra8250`, and in the IFS `devc-ser8250 -e -b115200 -c<clk>/16 0x3100000^2,144` (`port^shift,intr` syntax VERIFIED in the local devc-ser8250 doc), `reopen /dev/ser1`, `[+session] ksh &`. This is the zero-new-code interactive shell for M1b. The SBSA `uarti @0x031D0000` (`ttyAMA0`, no clocks/resets, 115200) is a free experiment with `hw_serpl011`/`devc-serpl011` only if its carrier routing is ever found (UNKNOWN U9).

### 4.5 Secondary sink: RAM black box (zero hardware)

Every shim/`put_tcu` byte can be mirrored into a ring inside the ramoops carveout `0x2725F0000` (2 MiB, `no-map`, VERIFIED). This kernel has an active pstore console zone (`console [ramoops-1] enabled`, VERIFIED synth raw/orin-ttys.txt:68), so a zone written in `persistent_ram` console-zone format (sig `DBGC` = 0x43474244, start/size words, data) should surface as `/sys/fs/pstore/console-ramoops-0` after the next L4T boot. HYPOTHESIS x3: (a) zone offsets — `record_size/console_size/ftrace_size/pmsg_size` are UNKNOWN until `cat /sys/module/ramoops/parameters/*` is read from L4T; (b) DRAM contents survive a PSCI `SYSTEM_RESET`/WDT warm reset on this board (L4T's own ramoops use implies yes); (c) `/dev/mem` readback of a `no-map` range works under `STRICT_DEVMEM` as the fallback readback. All three are pre-tested from L4T with zero risk before M0 (§7 M0 pre-flight, §14). If the layout is unknowable, write plain text into the **last 256 KiB** of the carveout instead and read it back with `dd if=/dev/mem` (HYPOTHESIS (c)).

### 4.6 Last resort: Power LED heartbeat

Green Power LED = module GPIO04 = Tegra PCC.01 on the AON GPIO (VENDOR_CLAIM, NVIDIA staff say software-drivable). Derived registers `0x0C2F1420` (ENABLE_CONFIG), `0x0C2F142C` (OUTPUT_CONTROL), `0x0C2F1430` (OUTPUT_VALUE) from `gpio-tegra186.c` (HYPOTHESIS; polarity, pinmux at hand-off and the AON GPIO "security" aperture's NS-write behaviour UNKNOWN). Behind `shim.led=1`. One bit of information; never load-bearing.

---

## 5. Startup board directory

### 5.1 Location, build, output

`src/hardware/startup/boards/t234-orin-nano/` in a **private** build tree (only our own Apache-2.0-headed files go into the repo), built against the BSP zip's `lib/public` headers (`startup.h`, `aarch64/cpu_startup.h`, `aarch64/gic.h`, `arm/psci.h`, `hw/8250.h` — VERIFIED present in the zip, NOT installed in the SDP) with the zip's `boards/common.mk` unchanged (`LINKER_TYPE=BOOTSTRAP`, `LIBS startup fdt lzo2 ucl drvr`, `CCFLAGS_aarch64 -mgeneral-regs-only -mstrict-align -fno-store-merging -fno-gcse -fno-inline-small-functions`; VERIFIED H2) linking the SDP's `libstartup.a` + `libfdt.a` + `libdrvr.a` + `liblzo2.a` + `libucl.a` (all VERIFIED present). Output `startup-t234-orin-nano`. HYPOTHESIS (never executed): the BSP makefiles run unmodified under the win64 SDP tooling — **first action today** (§14) builds the shipped `armv8_fm` board as-is to settle it.

Templates: Apache-2.0 `armv8_fm` files (`board_smp.c`, `aarch64/init_intrinfo.c`, `aarch64/_start.S`, `init_asinfo.c`, `build`, makefiles) and the public Apache-2.0 Pi 4 BSP `main.c` for the call order (`hypervisor_init()` before `init_smp()`). `armv8_fm/main.c` and `boards/public/aarch64/ls10x6a.h` carry the proprietary QNXLicenseC header (VERIFIED census): read for call order only, never copied.

### 5.2 New files (~9, ~700-900 lines)

| File | Purpose | Grafts applied |
|---|---|---|
| `main.c` | `fdt_init(boot_regs[0])` if DTB magic; **`psci_call = psci_smc; in_hvc = 0;` unconditionally** (`fdt_psci_configure()` matches only `"arm,psci"`, board says `"arm,psci-1.0"` — VERIFIED synth fdt_psci_configure.c:42 + DT); optional `qnx.*` bootargs parse (F5); getopt `COMMON_OPTIONS_STRING "D:W:T"`; `select_debug()`; `wdt_report()` then policy per `-W`; `init_raminfo()`; `avoid_ram(fdt)`; `avoid_ram(shim page 0x80080000, 4096)`; `hypervisor_init(0)`; `init_smp()`; `init_mmu()` if virtual; `init_intrinfo()`; `init_qtime()` (no `timer_freq` override -> CNTFRQ_EL0 31.25 MHz, VERIFIED); `-T` probe; `init_cacheattr/cpuinfo/hwinfo`; `add_typed_string(_CS_MACHINE, "NVIDIA Jetson Orin Nano Developer Kit (Tegra234)")`; `add_callout_array(callouts_reboot_psci_smc)`; `init_system_private()`; `print_syspage()`; landing sanity (PC-relative `_start` vs linked). | F4 conduit, F5 |
| `init_raminfo.c` | **Hard-coded**, not DTB (no `/memory` node in live or on-disk DT, VERIFIED). M0-M2: `add_ram(0x80000000, 0x3E000000)` only (992 MiB, VERIFIED /proc/iomem). M3+: also `add_ram(0x100000000, 0x15E20E000)` (5.4 GiB), never `0xBE000000-0xC1FFFFFF` (owner UNKNOWN), never `0x40000000` SysRAM (BPMP IVC), never the firmware-reserved sub-ranges or carveouts. Optional `-U`: walk `/chosen/linux,uefi-mmap-*` (map copy at `0x25E406018`, VERIFIED) taking `EfiConventionalMemory` only. `alloc_ram(shdr->ram_paddr, shdr->ram_size, 1)`. | |
| `aarch64/init_intrinfo.c` | Pre-quiesce (§5.3); **`gic_v3_set_paddr_range(0x0F400000, 0x0F440000, 0x200000, NULL_PADDR)`** (no ITS: no DT child, no dmesg ITS/LPI line, VERIFIED); `gic_v3_use_mm_reg_callouts(<gicc>, 0)` = system-register callouts (the MMIO IPI path hard-codes `gic_cpu[cpu] = (1<<17)*cpu` "XXX assumes cpu is the same as gicr_index", VERIFIED synth gic_v3.c:1509-1511 — wrong for frames 6/7); `gic_v3_initialize()`; `smp->send_ipi = gic_sendipi`. One SPI intrinfo for 960 SPIs. Maintenance PPI 9 = INTID 25 (VERIFIED DT). | F3 |
| `board_smp.c` | `board_smp_num_cpu() = fdt_num_cpu()` (6) capped by `-P`; `board_smp_init()` records MPIDRs from `/cpus` reg cells into the table `psci_cpu_id()` reads; `board_smp_start() = psci_smp_start()` unconditionally. | |
| `psci_cpu_id.c` | **Board override**: index -> {0x0, 0x100, 0x200, 0x300, 0x10200, 0x10300} (FDT-derived, table fallback). Archive semantics: the board object is linked before `libstartup.a` is scanned, so `psci_smp.o`'s reference resolves to ours and the library member is never pulled (standard `ld`; HYPOTHESIS that common.mk keeps that order — `nm` the result). | F4 |
| `hw_sertcu.c`, `aarch64/callout_debug_tcu.S` | §4.2 (2) and (3); compile-time black-box mirror. | |
| `wdt.c` | Read + `kprintf` WDT0 `0x02190000` / WDT1 `0x021A0000` CR/SR always; `-Wdisable` = `WDTUR 0xC45A` + `WDTCMDR` disable; `-Wkeep` = leave as found; `-Warm=<s>` = arm (for soaks with `wdtkick` from the BSP zip `src/hardware/support/wdtkick`, Apache-2.0). Default `-Wdisable` only if the M0 read showed it counting; else `-Wkeep`. | F6 |
| `init_asinfo.c`, `tweak_cmdline.c` | `fdt_asinfo()` registers the DTB for user space (qvm needs `libfdt.so` + the DTB); board options. | |
| `build`, `Makefile`, `pinfo.mk`, `t234_startup.h` | From the Apache-2.0 `armv8_fm` skeleton. | |
| (UEFI variant only) `aarch64/_start.S` | `b efi_entry_point`. Not built for the kexec image (the library `_start` = `b cstart`, x0-x3 preserved into `boot_regs[]`, VERIFIED synth cstart.S:60-64). | F7 |

User-space companions (in `ipc-test/` style, own Apache-2.0 code): `tcu-cat.c`, `stamp.c`, optional `devc-tcu` (M1b).

### 5.3 GIC pre-quiesce (before `gic_v3_initialize()`)

Linux leaves the distributor enabled and device SPIs (Ethernet, NVMe, USB, display) possibly pending/active across kexec — `irq-gic-v3.c` has no kexec/shutdown hook (VERIFIED researcher read). The library already writes `GICD_CTLR = 0` + RWP, `ICENABLERn/ICPENDRn` for all SPIs and per-CPU `GICR ICPENDR0/ICENABLER0` + WAKER (VERIFIED synth, §2.3), but not `ICACTIVER`. Board pre-quiesce: `GICD_CTLR = 0`, wait RWP; `ICENABLERn = ICPENDRn = ICACTIVERn = 0xFFFFFFFF` for 32..991; boot-CPU `GICR ICENABLER0/ICPENDR0/ICACTIVER0`; `GICR_WAKER.ProcessorSleep` clear + wait `ChildrenAsleep`; `ICC_IGRPEN0/1_EL1 = 0`. Belt-and-braces; costs ~40 lines.

### 5.4 Redistributor geometry (VERIFIED dmesg + DT)

GICD `0x0F400000` (64 KiB), GICR region `0x0F440000` size `0x200000` = 16 frames of `0x20000` (RD+SGI, no VLPI frames), one region. Populated frames: 0-3 = MPIDR 0x0/0x100/0x200/0x300 (`0xF440000..0xF4A0000`), 6 = 0x10200 (`0xF500000`), 7 = 0x10300 (`0xF520000`); frames 4, 5, 8-15 belong to floor-swept cores. `gic_v3_gicc_init()` walks frames by `GICR_TYPER` affinity from frame 0 (VERIFIED synth gic_v3.c:1334-1352), so with limit 16 it reaches frames 6/7; it does **not** check `GICR_TYPER.Last`, and reading an unpopulated frame's TYPER on the way is HYPOTHESIS-safe (Linux does the same walk). 960 SPIs, sysreg CPU interface, split EOI, no ITS, no GICV (VERIFIED).

### 5.5 How `-Q enable,el2-host` is satisfied

1. Entry at EL2 — kexec from the VHE kernel (VERIFIED source reading; confirmed at runtime by the M0 bank, aborted otherwise).
2. `at_el2` hands `cstart` E2H=0/TGE=0/MMU-off (VERIFIED synth); `arch_hypervisor_validate_flags()` finds `CurrentEL == 2` and `ID_AA64MMFR1_EL1.VH != 0` ("Virtualization Host Extensions" detected, VERIFIED dmesg) -> `hyp_enable_el2_host()` prints "Enabling EL2 host hypervisor support (VHE)" (VERIFIED synth hypervisor.c:91-95).
3. Secondaries: PSCI `CPU_ON` returns them at EL2 (this firmware started all six at EL2 for Linux, VERIFIED dmesg; TF-A hands warm-boot cores to the same EL — VENDOR_CLAIM, T234 TF-A source not read) and `smp_start -> _start_el2_or_el1 -> at_el2` normalises them (VERIFIED synth); `hypervisor_init(n)` then requires the same flags as CPU0 or crashes (VERIFIED synth hypervisor_setup.c:56-63).
4. GIC virtualisation exists and is usable (KVM's vgic used IRQ 25, `ICH_*` sysregs; VERIFIED dmesg).
5. The only open hardware question is the **NS-EL2 virtual timer PPI (INTID 28)**: `qtime->intr = 28` unconditionally in el2-host mode (VERIFIED synth init_qtime_v8gt.c:56-60); the L4T DT lists only PPIs 13/14/11/10 and Linux never uses 28; Tegra234 wiring is UNKNOWN. The M1 `-T` probe decides: program `CNTHV_CVAL_EL2/CNTHV_CTL_EL2` to fire, read `GICR_ISPENDR0` bit 28 in CPU0's SGI frame (`0xF450220`), print `HV-timer PPI28: wired|absent`, clear. If absent -> M3 uses `-Q enable,el1-host` (VENDOR_CLAIM: documented, "unusual" but supported; the mode QNX's own Pi 4 walkthrough uses) and every number is labelled "el1-host, not the VHE number".

M1/M2 run `-Q disable` (`drop_to_el1`, VERIFIED synth hypervisor.c:82-87) to separate "QNX runs on Tegra234" from "the VHE host runs on Tegra234"; M1b re-runs M1 with `-Q enable,el2-host -P1`.

### 5.6 DTB usage

The kexec-passed DTB (live L4T tree + overlays, `/chosen` rewritten) is used for `/cpus` (count, MPIDRs), `/psci` (sanity only; conduit forced), `/timer` (sanity), `/chosen/bootargs` (optional `qnx.*` tokens), `/chosen/linux,uefi-mmap-*` (optional `-U`), and is registered via `fdt_asinfo()` for qvm. It is **not** used for RAM (no `/memory` node), GIC bases (hard-coded, cross-checked against DT and edk2 `T234Definitions.h`) or the console (the tcu node has no `reg`).

---

## 6. Minimal images

### 6.1 M0 — shim only, no IFS

`t234-shim.kimg` = the 4 KiB shim page (header + body + vectors + TCU/black-box/LED printers + WDT arm + `SYSTEM_RESET`). Built with `ntoaarch64-as` / `ntoaarch64-ld -Ttext=0x80080000` / `ntoaarch64-objcopy -O binary` (all VERIFIED present in `host/win64/x86_64/usr/bin`, raw/host-tools.txt). Checked with `od`: magic `41 52 4d 64` at 0x38, `text_offset 00 00 08 00 00 00 00 00` at 0x08, non-zero `image_size` at 0x10, file size exactly 4096. Mode selected by a byte in the header's `res2` field (`p`/`h`/`j`) or by the shim scanning `/chosen/bootargs` in the DTB at `x0` for `shim.mode=`.

### 6.2 M1 — `t234-qnx.kimg` = shim || `ifs.bin` from this buildfile (our own text)

```
[image=0x80081000]
[virtual=aarch64le,raw] [+keeplinked]
[-compress]
boot = {
    startup-t234-orin-nano -vvv -P1 -Q disable -m992M -Wkeep -T -Dtcu
    PATH=/proc/boot LD_LIBRARY_PATH=/proc/boot
    [+keeplinked] procnto-smp-instr -v
}
[+script] .script = {
    display_msg "T234 M1: procnto up"            # via display_char_tcu, no driver
    procmgr_symlink ../../proc/boot/ldqnx-64.so.2 /usr/lib/ldqnx-64.so.2
    procmgr_symlink /proc/boot/ksh /bin/sh
    devc-pty
    tcu-cat -m "T234 M1: user space up"
    pidin info | tcu-cat
    pidin | tcu-cat
    cksum /proc/boot/.script | tcu-cat
    # M1b (optional interactive shell over the Linux-preconfigured uarta):
    # devc-ser8250 -e -b115200 -c<clk>/16 0x3100000^2,144 ; reopen /dev/ser1 ; [+session] ksh &
}
[type=link] /usr/lib/ldqnx-64.so.2=/proc/boot/ldqnx-64.so.2
libc.so.6  libgcc_s.so.1
/proc/boot/tcu-cat=tcu-cat
/proc/boot/stamp=stamp
/bin/ksh=ksh  /bin/pidin=pidin  /bin/cksum=cksum  /bin/cat=cat  /bin/ls=ls  /bin/echo=echo  /bin/on=on  /bin/slay=slay  /bin/shutdown=shutdown
/sbin/devc-pty=devc-pty
# optional: /sbin/devc-ser8250=devc-ser8250  /sbin/wdtkick=wdtkick
```

`[-compress]` keeps the image byte-inspectable; `[+keeplinked]` keeps the linked ELFs for `addr2line` on crash PCs. ~10 MB. `dumpifs -v` must show `*.boot` at `0x80081000`, `image_paddr`/`startup_vaddr` inside the window, `compress=0`. Post-step: `cat t234-shim.kimg ifs.bin > t234-qnx.kimg` and re-`od` the header. M2 changes `-P1` -> `-P4` -> `-P6` and (if the WDT was found counting) `-Wdisable`.

### 6.3 M3 — hypervisor host image (adds to M1)

`startup-t234-orin-nano -vvv -P6 -Q enable,el2-host -m6G -Dtcu` (or `el1-host` per the `-T` verdict), plus the hypervisor set exactly as the cloud host's mkqnximage build lists it (VERIFIED synth qhv/host/output/build/system.build:356-372): `sbin/qvm`, `bin/qvm-check`, `lib/dll/vdev-pl011.so`, `vdev-virtio-console.so`, `vdev-shmem.so` (no `vdev-virtio-blk.so` unless M3b), `usr/lib/libfdt.so`, `usr/sbin/tracelogger`, `usr/bin/traceprinter`, `slogger2`/`slog2info`, and `/proc/boot/guest-ifs.bin` = `qhv/guest/output/ifs.bin` (sha256 `968029316b...7cf4f`, byte-identical to the cloud and Orin-TCG legs). `g2.conf` written by the script to `/dev/shmem` = the cloud-leg config minus virtio-blk (VERIFIED synth `qhv/host/local/snippets/post_start.custom`):

```
system mkqnximage-guest
ram 0x80000000,512M
cpu
load /proc/boot/guest-ifs.bin
vdev pl011
 hostdev >-
 loc 0x1c090000
 intr gic:37
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/ptyp0
```

Script: `qvm-check | tcu-cat`; `stamp -s 'QNX qnx-guest' < /dev/ttyp0 | tcu-cat &` (background, after `waitfor /dev/ttyp0`); `T0 = stamp -now`; `qvm @/dev/shmem/g2.conf &`. Optional M3b parity: `disk-qvm` (153,432,576 B) copied into `/dev/shmem` + `devb-loopback` + `vdev virtio-blk` (~175 MB image, inside the 2 MiB-rounded `image_size` and the 992 MiB window). Guest IFS/disk are gitignored build outputs, never committed.

---

## 7. Milestone ladder

### M0 — Sign of life (no QNX code runs)

**Goal.** Prove kexec hands a non-Linux payload control at EL2; prove the TCU (and/or the black box) is a usable console after Linux is gone; measure what Linux left (HCR/SCTLR/timers/WDT); prove the board comes back.

**Pre-flight from L4T (read-only / reversible):** `cat /etc/default/kexec; systemctl status kexec-load kexec`; `ls /sys/fs/pstore; cat /sys/module/ramoops/parameters/*; zcat /proc/config.gz | grep -i 'PSTORE\|RAMOOPS'`; pmsg retention test `echo M0-test | sudo tee /dev/pmsg0; sudo reboot; cat /sys/fs/pstore/pmsg-ramoops-0` (one reboot, no persistent change); the `kexec -s -l` / `kexec_loaded` / `kexec -u` acceptance test with the shim image; record `cpuinfo_cur_freq`.

**Steps.** (1) Build `t234-shim.kimg` on Windows; `od` check. (2) `probe` mode: quiesce, `kexec -s -l t234-shim.kimg`, `systemctl kexec`, under `setsid nohup`. Expect the bank line within ~2 s of Linux's "Bye!" then a `SYSTEM_RESET` and L4T back in ~60 s. (3) `hang` mode with `shim.wdt=60`: does the board come back unattended? (4) `jump`-into-a-deliberate-`brk` variant to prove the vector path prints `EXC` and resets. (5) Repeat (2) once via `kexec -c -l --dtb -i` (purgatory path).

**Verification (pass criteria).** Bank line shows `EL=2`, `DTBMAGIC=D00DFEED`, a sane `HCR` (expect E2H|TGE set — record it), `WDT0CR`/`WDT1CR` values (expect not counting; record), `TXMB` bit 31 clear before the first write and `TCU drops=0`. Either the adapter shows the line or the black box carries it after reset. The `hang` test either returns the board on its own (shim-armed WDT works -> HYPOTHESIS becomes VERIFIED) or needs a manual power cycle (recorded; plan continues). Log into `results/orin-native-port/<ts>/m0/` (redacted, private).

**Risk and recovery.** `kexec_file_load` refuses -> Fallback A. NVIDIA's kernel panics in `kernel_kexec` (SMMU/EMEM from live DMA) -> cold boot, unload more modules, nothing persistent damaged. TCU silent -> black box decides; then uarta/LED. `EL != 2` -> kill criterion (a) -> Fallback B. DRAM not retained -> black box unusable, adapter mandatory. Recovery in every case: power cycle or WDT/PSCI reset -> unchanged L4T from the untouched ESP/QSPI/SD. Hygiene: never `kexec -p`; sessions short (shared board); always `systemctl kexec`, not `kexec -e`, unless the kexec-load hazard forces it.

### M1 — procnto + user space on one CPU (EL1), then M1b at EL2

**Goal.** First QNX kernel natively on Tegra234: startup `-vvv` syspage dump, `display_msg` markers, `pidin` output over the TCU via `tcu-cat`; then the same with `-Q enable,el2-host -P1`.

**Steps.** (1) Board directory (§5) built with `common.mk`; `nm` the result: no `efi_/uefi_/acpi_` symbols; `display_char_tcu`, `init_tcu`, `psci_smc`, `gic_v3_set_paddr_range`, `gic_v3_initialize`, `hyp_enable_el2_host`, board `psci_cpu_id` present and the library `psci_cpu_id.o` **not** pulled. (2) `tcu-cat`, `stamp`. (3) `mkifs` the §6.2 buildfile; `dumpifs -v`; concatenate; `od` check. (4) First boot `-vvv -P1 -Q disable -m992M -Wkeep -T -Dtcu`; on the very first attempt keep the shim in full-normalise mode and print the bank **before and after** normalisation (free bisect of "kexec entry works" vs "normalisation works"). (5) Read the syspage dump: cpuinfo `Cortex-A78ae`, qtime 31,250,000 Hz, asinfo shows the 992 MiB range, intrinfo GICv3 960 SPIs, `HV-timer PPI28: wired|absent`, WDT lines. (6) Iterate on faults with the shim vectors (`EXC` lines with ESR/ELR/FAR + `addr2line` on the `[+keeplinked]` ELFs) and `put_tcu` prints between `init_*` calls. (7) M1b: rebuild `-Q enable,el2-host -P1`; expect "Enabling EL2 host hypervisor support (VHE)" and the same script markers. (8) Optional interactive shell over uarta (§4.4) or `devc-tcu`.

**Verification.** In order on the console: shim bank -> startup banner/`-vvv` -> `print_syspage()` -> `T234 M1: procnto up` -> `T234 M1: user space up` -> `pidin info` (1 CPU, ~950 MB free) -> `pidin` listing `procnto-smp-instr`, `devc-pty`, `tcu-cat` -> a `cksum` line that matches the PC-side value. M1b adds the VHE line. Curated (redacted, private) log `results/orin-native-port/<ts>/m1/orin-native-m1-first-procnto.log`; a findings.md entry with the honest caveats (kexec entry, one CPU, no drivers) — text only, no numbers, pending §9.

**Risk and recovery.** Highest-variance milestone. `cstart`/`drop_to_el1` misbehave on the inherited state -> toggle `SHIM_FULL_NORMALISE`, compare with the QEMU `virtualization=on` path (E2H=0 entry proven there); `gic_v3_initialize()` trips on a stale SPI -> the crash dump names the INTID, extend the pre-quiesce; `init_mmu`/cache-attribute surprise on A78AE -> drop the second RAM window, try `-Q enable,el2-host` early (a second, independently proven EL path); procnto dies before `display_msg` -> KD is available because the callout is the console; blind (no adapter) -> one question per reboot via the black box. Recovery: reset -> L4T. Nothing persistent.

### M2 — SMP: six A78AE cores

**Goal.** All six cores under procnto via PSCI `CPU_ON` over SMC, redistributors matched by affinity, IPIs working; fallback `-P4` (cluster 0, frames 0-3) keeps the measurement alive.

**Steps.** (1) Confirm from source (already done for the two fatal items; re-read `gic_v3_gicc_init()` and `gic_v3_use_mm_reg_callouts()` lines 482-500 for the "no GICC" calling form). (2) Bisect `-P2` (MPIDR 0x100), `-P4`, `-P6` (adds 0x10200/0x10300 in frames 6/7). (3) Per-CPU `cpu N up MPIDR=.. GICR=..` print in the smp entry (via the callout). (4) `pidin info` CPU count; six busy processes with `on -C n`; `tracelogger` 5 s and per-CPU event counts as an IPI/timer sanity check. (5) `shutdown -b` / `slay` -> `reboot_psci_smc` returns the board to L4T.

**Verification.** `pidin info` shows 6 CPUs (or 4, explicitly recorded as degraded); six `cpu N up` lines with the expected MPIDRs and GICR bases `0xF440000/0xF460000/0xF480000/0xF4A0000/0xF500000/0xF520000`; a 60 s six-process soak; a 10-minute idle soak with no spurious interrupt (also proves the WDT is disabled or kicked); `shutdown -b` returns L4T.

**Risk and recovery.** `CPU_ON` returns an error (wrong MPIDR mapping — check the FDT reg cells; core not OFF — kexec polled `AFFINITY_INFO`, so it should be); a secondary picks the wrong frame -> hung secondary, bounded by `start_aps()`'s counter -> `ap_fail()` message; cluster-1 cores need a DSU/L3 wake the firmware normally does (UNKNOWN; `-P4` avoids). Recovery: reset -> L4T. Nothing persistent.

### M3 — QHV host natively at EL2 + byte-identical guest; FIRST hardware-timed number

**Goal.** `qvm` (EL2/VHE procnto) boots the cloud-leg guest IFS with the cloud-leg vdev topology minus virtio-blk; the host clock stamps `qvm` launch -> guest banner; n = 5.

**Steps.** (1) §6.3 image. (2) If M1's `-T` said absent: `-Q enable,el1-host`, record the topology difference. (3) Boot; expect the VHE line, `qvm-check` output, `=== launching qvm` marker, then `QNX qnx-guest ... ARMv8_Foundation_Model` and `Startup complete` from the guest via `/dev/ttyp0 | tcu-cat`. (4) `stamp` prints `ClockCycles()` at launch and at the banner; delta / 31,250,000 = seconds (32 ns tick). (5) Five runs (five kexec rounds from L4T). (6) Run the Phase-2 host-client / guest-server IPC pair over the virtio-console pty exactly as on the cloud leg (15 timed iterations, sentinel frames); print its CSV row over the TCU. (7) Re-run the **TCG** Orin leg with the same no-blk `g2.conf` so the twin table compares like with like (or land M3b parity instead).

**Verification.** Guest banner on 5/5 runs; `results/hw/orin-native-qhv-guest-boot-times.txt` in the existing `qhv-guest-boot-*-times.txt` format (`# host:`, `# devices:`, `# marker: qvm launch -> guest banner`, `run N: <ms> ms`) with startup options, `-Q` mode, guest sha256, CPU MHz (or "clock not verified") stamped; IPC CSV row in the `results/cloud` schema. What this number is NOT: not a per-exit latency (M4), not the twin's full launch -> banner headline (which includes host boot), only its `qvm_launched -> guest_banner` segment (e.g. Windows run 1: 28,740 - 6,184 ms, VERIFIED synth qhv-guest-boot-win-q111-rng-times.txt).

**Risk and recovery.** The biggest technical risk in the plan: qvm fails to arm stage-2/ICH state on real hardware (IPA 48-bit VERIFIED fine; no GICV needed for a sysreg guest — HYPOTHESIS that qvm needs nothing more); INTID 28 absent -> el1-host (labelled); guest `startup-armv8_fm` aborts on ID-register differences (U17 PAUTH contradiction — A78AE implements PAuth, HYPOTHESIS it does not recur); TCU throughput delays the banner but not the host-side stamp. Fallbacks in order: el1-host; 1 vCPU guest; `vdev pl011` only; `-P4`. Recovery: reset -> L4T. Licence: qvm/guest binaries never leave the board and the owner's machines (4.6(g)).

### M4 — The qvm-trace number

**Goal.** Per-exit hypervisor dwell (Class 10 Guest Exit ID 1 -> next Guest Entry ID 0; ID 7 guest `ClockCycles` at_entry/at_exit — VENDOR_CLAIM from the online QHV 8.0 `trace_events` page) on real A78AE EL2, extracted without storage or network.

**Steps.** (1) After the banner: `tracelogger -r -M -S 8M -f /dev/shmem/t.kev -s 20 -c` (ring mode into `/dev/shmem`, VERIFIED local doc) around a defined workload — the guest's own boot tail plus the IPC round-trips from (6) above. (2) `traceprinter -f /dev/shmem/t.kev | grep -E 'QVM|Class 10|GUEST' | tcu-cat`, then `cksum /dev/shmem/t.kev | tcu-cat` and a line count (a few thousand lines, 1-2 min at 11 KB/s; never the whole .kev). Mirror into the black box if enabled. (3) Calibration: startup sets `PMUSERENR_EL0.EN`; a 20-line tool prints `PMCCNTR_EL0` vs `ClockCycles()` over 1 s -> actual core MHz (cpufreq pinned to `performance` before kexec; HYPOTHESIS that it persists). (4) PC-side parser -> per-vCPU exit records -> P50/P99/max in ns (ticks x 32), exits/s -> `results/hw/orin-native-qvm-trace-latest.csv` in the schema `unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes` (VERIFIED synth diff-results.sh:19,57), `cycles_per_sec = 31250000`, `notes = orin-native-el2host-qvm-class10-dwell;clock=<MHz|unverified>`; 5 runs; the identical script on the Orin-TCG leg produces the emulated-time counterpart, labelled as such. (5) Fill `docs/digital-twin-design.md` §1a with the third bundle — text prepared, numbers withheld pending §9.

**Verification.** 5 runs x >= 1,000 Exit/Entry pairs; checksum and line count match on the PC; P50 stable within +/-20 % across runs; exit counts consistent with the workload; `diff-results.sh` consumes the CSV. MHz printed next to every number or "clock not verified".

**Risk and recovery.** Class-10 events absent on 8.0.x -> bound the dwell with kernel INTERRUPT/THREAD events around the qvm vCPU threads; `-instr` kernel overhead -> report as an upper bound (same kernel on the TCG leg); a stall ends the run early -> the sentinel-frame client already survives stalls. Recovery: reset -> L4T. Publication gate per §9.

### M5 (optional) — UEFI Shell cold-boot cross-check

Only after M3/M4, only with the F7 entry style and the §3.5 Fallback-B rules (Shell launch, new ESP file, backups first, never `efibootmgr -c`). PASS = the PE reaches `Entering startup...` (ADR-003 gate (2) passed) and the M3/M4 medians agree with the kexec-entered ones within run-to-run spread; disagreement makes the kexec residual-state caveat a finding in its own right. Worst-case recovery: the NVMe L4T (Boot0008, VERIFIED) or pull the SD and repair `extlinux.conf` from there — no reflash.

---

## 8. Hardware to buy

**Required (~USD 5-15):** one 3.3 V-logic USB-to-TTL serial adapter (FT232RL / CP2102 / CH340 class; never 5 V-only) plus three female jumper wires. J14 12-pin header: adapter RX -> pin 4 (swap to 3 if silent), adapter TX -> the other, GND -> pin 11; **do not connect VCC**. 115200 8N1, terminal with timestamps (`tio --timestamp` / `picocom` / PuTTY logging). Validated the moment the L4T boot log appears — before any QNX code exists. It also serves the UEFI menus / L4TLauncher menu / UEFI Shell for M5 and for any recovery that needs ESC at the firmware banner.

**Recommended (~USD 10-20):** a remotely switchable mains plug or USB-controlled relay on the DC barrel input — every hang without a working WDT is a manual power cycle, and the board already needed one on 2026-09-08 (U24, suspected brown-out; keep the `-j4`-style load discipline). Optional (USD 0-10): a second adapter or moving the one adapter to J12 pins 8/10 (+ GND 6/9) for the uarta interactive shell.

**If the owner buys nothing:** the plan still runs, slowly and blind: the black box (§4.5, three HYPOTHESES pre-tested from L4T) carries the shim/startup/kernel output and is read after a reset; each experiment is one reboot cycle (~2-3 min) answering one question; M1-M4 run as fully scripted boot scripts with outputs mirrored to the black box; no interactive debugging, no KD, no input-driven tests. If the black-box premises fail, the LED is the only zero-cost signal and the adapter becomes effectively mandatory. If the shim-armed WDT does not fire, every hang is a manual power cycle — still a no-reflash recovery.

**Never:** JTAG, a second board, DRIVE hardware, a Pi, NVMe repartitioning, bootloader replacement, QSPI/UEFI update, reflash.

---

## 9. Licence stance

Governing text (VERIFIED PDF text via pdftotext in research-qnx.md; legal effect = the researcher's reading, not a BlackBerry statement): QNX Development License Agreement, Non-Commercial License Class v7, 2025-12-10 (supersedes NCEULA v.019).

**Owner decision (2026-09-09, recorded in uncommitted working-tree edits to ADR-003 / CLAUDE.md / findings.md — U21):** proceed with option (B), the native Orin Nano port; consult the supervising professor before publishing any evaluation results (4.6(i)); keep 4.6(c) clean by using only source and documentation, never disassembly.

How this plan honours it:

- **4.1(iii)** (modify Software supplied as Source Code for a Non-Commercial Target System; no hardware list): the whole board directory and any local patch to the Apache-2.0-headed library sources (e.g. if `gic_v3.c` needs a change) live inside this grant; the result is Experimental Software, as-is, no vendor path. Whether the Apache-2.0 headers or the QDL zip licence governs those files is UNKNOWN (U19); both permit local modification for this use, and 5.1 says the OSS licence prevails for OSS files.
- **4.6(c)** (no disassembly): every fact in this plan comes from Apache-2.0/BSD/GPL **source**, public documents, `ar t` / `nm` name listings, `readelf -h`, `dumpifs`, `od` of the repo's own IFS first bytes, and live-board captures. The 2026-07-28 `startup-qemu-virt` disassembly is not an input and the repo's withholding practice continues. Name-level inspection of shipped binaries stays the ceiling. The UEFI PE header check in Fallback B is a header read (`od`/`readelf`), not code.
- **4.6(d)** (no modification of binary-delivered Software): `startup` is relinked from `libstartup.a` (the standard BSP flow); the shim is **prefixed** to the owner-built IFS as a separate page and alters no procnto/startup bytes; the raw.boot stub is used as shipped. Reading, not a ruling.
- **4.6(g)** (no distribution): the repo receives only our board sources (Apache-2.0 to match the templates), the shim (MIT), `tcu-cat`/`stamp`, buildfiles, scripts, and **redacted** logs/CSVs; never `libstartup.a`, the built startup, procnto, qvm, the guest IFS/disk, the BSP zip, or any SDP header. <= 30-line excerpts of Apache-2.0 files with paths only.
- **4.6(b)**: the owner's own board.
- **4.6(i)** (no release of performance or functional evaluation results without prior written approval): every M0-M4 log, CSV, trace and boot-time file stays in a private results directory / private branch tagged `unpublished pending 4.6(i) consultation` — M0/M1 boot logs and `pidin` listings are functional-evaluation output too, not just M4's timings. Design, source and procedures are publishable (they evaluate nothing). The consultation outcome is recorded in `findings.md` before any number or boot log goes public. The pre-existing published latency/boot numbers are the owner/professor's open item (U18), outside this plan.
- **Hypervisor entitlement:** "QNX Everywhere includes QNX Hypervisor 8.0" rests on QNX's own Pi 4 walkthrough README (VENDOR_CLAIM, U20); running QHV on an unlisted board is Experimental Software ("contact your QNX representative"). NVIDIA side: no licence issue — unsupported, not hardware-locked; a pure-software approach does not affect warranty (VENDOR_CLAIM, staff forum replies). The Tegra234 TRM is login-gated and was not consulted; no bypass.

---

## 10. Effort estimate (single engineer, working days, adapter in hand from M0 step 2)

| Phase | Days | Uncertainty | Dominant driver |
|---|---|---|---|
| P — prep (build flow under win64 SDP tooling, shim toolchain, header checker, pre-flight reads, pmsg test, kexec load/unload test, wiring against the L4T log) | 1-2 | LOW-MED | BSP makefiles never executed on this host (K12) |
| M0 — sign of life | 0.5-3 | HIGH on "TCU alive after Linux", MED on kexec acceptance | SPE behaviour, NVIDIA kernel fork, DMA quiesce hunting |
| M1 — procnto + user space (EL1) and M1b (EL2 host) | 3-7 | HIGH | first QNX instruction ever on Tegra234; EL2/GIC/raminfo interactions; blind debugging doubles it |
| M2 — SMP | 1-2 | LOW-MED | both known pitfalls pre-empted; cluster-1 wake UNKNOWN |
| M3 — QHV host + guest, first number | 2-6 | MED-HIGH | INTID 28 wiring; stage-2/ICH on real silicon; no qvm source, no support |
| M4 — qvm-trace | 1-3 | LOW-MED | transport over 11 KB/s; parser |
| M5 — optional UEFI cross-check | 2-5 | HIGH | PE ImageBase/relocation, mkifsf_uefi behaviour |

**Total to M4: 9-23 working days (median ~13), i.e. 3-6 calendar weeks at part-time cadence on a shared board; +2-5 for M5.** Consistent with ADR-003's "weeks, no vendor path". Not included: the 4.6(i) consultation, the docs consolidation of stale ADR-003 lines (U25), any driver work (out of scope). Stall scenarios no amount of days fixes without outside help: no console at all (SPE not serving, uarta unclocked, no adapter); qvm cannot arm virtualisation on this GIC/timer topology; a firmware-locked watchdog that also survives a kicker (only if one turns out to be counting).

---

## 11. What a fully successful M4 still cannot measure

1. A **firmware-booted** QNX: the payload is entered by kexec from Linux; no UEFI -> QNX boot time, no firmware hand-off timing; residual state (DRAM contents, caches/TLB, BPMP-set CPU/EMC clocks, thermal state, any DMA Linux failed to stop) is inherited; only M5 addresses this.
2. Anything about NVIDIA DRIVE OS / the NVIDIA Hypervisor stack, DRIVE AGX Orin, QNX OS for Safety, ASIL, certified BSPs — Experimental Software on a consumer devkit with no vendor path from either NVIDIA or QNX.
3. Any peripheral or DMA path: no Tegra234 SDHCI/PCIe/NVMe/Ethernet/USB/display/GPU/SMMU work; IPC and trace numbers cover CPU, timer, GIC and hypervisor-mediated virtio/pty paths only; DMA-device containment (`smmuman`, MMU-500) is never exercised.
4. The heterogeneous Safety(QNX) <-> Compute(Linux) topology natively: while the QHV host runs, L4T is gone; the native leg is QNX-host + QNX-guest only; the `br0`/tap IPC numbers remain a KVM/TCG-leg result.
5. Power, thermal, DVFS: clocks stay wherever BPMP/Linux left them (no BPMP client); cycle counts are at an uncontrolled frequency, only *reported* by the PMCCNTR calibration.
6. A true one-variable twin diff: console mechanism, entry path, memory map, guest RAM placement, possibly host mode (el1-host) all differ from the TCG legs; the result is a third bundle, not "same image, host only".
7. Timer resolution below 32 ns (CNTFRQ 31.25 MHz); low-microsecond dwell is quantised to tens of ticks.
8. The no-instrumentation number: `procnto-smp-instr` + `tracelogger` overhead makes absolute values upper bounds (same kernel on the TCG leg keeps the diff fair).
9. Real-world interrupt latency from external devices (only timer PPIs and SGIs are wired); robustness over time (no soak beyond minutes, no thermal management); other SKUs/DRAM sizes (frames 4/5 and the 8 GiB above 4 GiB are barely touched).
10. Anything publishable until the 4.6(i) consultation is recorded.

---

## 12. Open unknowns, ranked by how much they can change the plan

| Rank | Unknown | Class | If it goes the wrong way |
|---|---|---|---|
| 1 | Payload is entered at EL2 by NVIDIA's 5.15.148-tegra `machine_kexec` (fork not read) | HYPOTHESIS (upstream VERIFIED) | Kill criterion (a): the whole kexec leg dies; pivot to Fallback B (UEFI Shell), a different plan with stacked firmware unknowns |
| 2 | The SPE keeps draining the TCU TX mailbox after Linux exits | HYPOTHESIS | No primary console; uarta (needs BPMP clock persistence, HYPOTHESIS) or black box; M1+ slows 2-3x |
| 3 | NS-EL2 virtual timer PPI (INTID 28) is wired on Tegra234 | UNKNOWN | No VHE (el2-host) number; el1-host fallback gives a hardware-timed but differently-labelled number |
| 4 | qvm arms stage-2/ICH/virtual-timer state on real A78AE the way it does under TCG | HYPOTHESIS | M3 stalls; no support path for Everywhere licensees; the finding is the deliverable |
| 5 | `boards/common.mk` builds under the win64 SDP tooling unmodified | HYPOTHESIS | Days of makefile work before any signal (mitigated: shim needs only as/ld/objcopy) |
| 6 | No firmware agent (BPMP/SPE/DCE/PSC) or stale device DMAs into `0x80000000-0xBDFFFFFF` after hand-off | HYPOTHESIS | Irreproducible corruption; escape = higher `[image=]` and the `-U` EFI-map path |
| 7 | pstore/ramoops zone layout on this kernel and DRAM retention across warm reset | UNKNOWN / HYPOTHESIS | Black box unusable; adapter mandatory (it is recommended anyway) |
| 8 | Shim-armed TKE WDT0 resets the SoC from NS-EL2 (lock state) | HYPOTHESIS | No unattended recovery; every hang is a manual power cycle (smart plug) |
| 9 | uarta stays clocked after kexec if opened from Linux | HYPOTHESIS | No zero-code interactive shell; write `devc-tcu` (M1b, +2-3 d) |
| 10 | `gic_v3_gicc_init()` tolerates reading TYPER of unpopulated frames 4/5 on the way to 6/7 | HYPOTHESIS | `-P4` keeps the measurement; a `gic_v3.c` patch under 4.1(iii) restores 6 cores |
| 11 | `/chosen/linux,uefi-mmap-*` survive kexec_file's DTB clone | HYPOTHESIS | Only the optional `-U` RAM path is lost; hard-coded table stands |
| 12 | mkifsf_uefi emits a loadable AArch64 PE; EDK2 honours a relocation-less ImageBase | UNKNOWN (U2/U3/U15) | Only M5 (optional) is lost |
| 13 | Which licence governs the Apache-2.0-headed sources in the QDL zip (U19); Hypervisor entitlement text (U20); consultation outcome (U18) | UNKNOWN | Publication, not the port |

---

## 13. Results hygiene

All outputs under `results/orin-native-port/<ts>/m{0..4}/` (private until §9 clears), redacted before writing (`<user>`, `<orin-ip>`, `<orin-key>`, `<mac>`), with every log stamped: startup options, `-Q` mode, shim build flags, IFS sha256 (sha only), guest IFS sha256, kexec syscall used, `cpuinfo_cur_freq` before kexec, adapter pin assignment. Boot-time files in the existing `qhv-guest-boot-*-times.txt` format; latency/dwell CSVs in the `diff-results.sh` schema.

---

## 14. Zero-cost, zero-risk first actions (today)

Windows, compile-only (no board):

1. Build the shipped `armv8_fm` board from the extracted BSP zip with the win64 SDP tooling (`make` in `boards/armv8_fm`) — settles K12; `nm` names vs. the SDP's `startup-armv8_fm` (names only).
2. Assemble the M0 shim in `probe` mode with `ntoaarch64-as/ld/objcopy`; write the 20-line header checker (`od` at 0x08/0x10/0x38, size = 4096).
3. `mkifs` the §6.2 buildfile with `[image=0x80081000]` against `startup-armv8_fm` as a placeholder; `dumpifs -v` to confirm the layout at the new base; concatenate; re-check.
4. Create `boards/t234-orin-nano/` from the Apache-2.0 skeleton with all §5.2 files stubbed; build; `nm`: `gic_v3_set_paddr_range`, `psci_smc`, `hyp_enable_el2_host`, board `psci_cpu_id`, `display_char_tcu` present; no `efi_/uefi_/acpi_`.
5. Compile `tcu-cat.c`, `stamp.c` with `ntoaarch64-gcc` (userland).
6. Source reads (Apache-2.0): `gic_v3_use_mm_reg_callouts()` (gic_v3.c:482-500) calling form; `hypervisor_enable.S` `hyp_enable_el2_host` register expectations; edk2-nvidia `TegraCombinedSerialPortLib.c` `Read()` for the RX release semantics.
7. Generate the no-blk `g2.conf` and record the guest sha256 (`968029316b...7cf4f`).

Orin, read-only (owner or an authorised session; `sudo -n` reads only):

8. `cat /etc/default/kexec; systemctl status kexec-load.service kexec.service` — the silent-replacement hazard.
9. `ls /sys/fs/pstore; cat /sys/module/ramoops/parameters/*; zcat /proc/config.gz | grep -i 'PSTORE\|RAMOOPS\|STRICT_DEVMEM'`.
10. `cat /sys/devices/system/cpu/cpu0/cpufreq/{scaling_governor,cpuinfo_cur_freq}`; `stty -F /dev/ttyTHS1 -a`.
11. Read-only register peek of WDT0/WDT1 CR/SR (`0x02190000`, `0x021A0000`) and the TX mailbox word (`0x0C168000`) via a root `python3 mmap` on `/dev/mem` (reads only; both are Linux-mapped device ranges) — settles "is anything counting at hand-off" before M0.
12. `sudo efibootmgr -o` and `ls -la /boot/efi/EFI` recorded as the baseline (nothing written).

Not read-only, first board session (owner decision, no reboot, no persistent change): `sudo kexec -s -l t234-shim.kimg; cat /sys/kernel/kexec_loaded; sudo kexec -u`.

Purchase (the only non-zero cost): order the 3.3 V USB-TTL adapter and a switchable plug.
