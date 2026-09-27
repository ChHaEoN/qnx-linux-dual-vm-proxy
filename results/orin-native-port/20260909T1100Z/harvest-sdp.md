# H2 — Local QNX SDP 8.0 inventory for a Tegra234 native `startup-*` port

Date: 2026-09-09, run id `20260909T1100Z`. Read-only inventory of the local
Windows SDP install (`C:/Users/<user>/qnx800`) and the shipped
`BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip`.

**Provenance.** Two passes of H2 ran today. The first (13:13) produced the
original version of this file plus `raw/bsp-startup-*-files.txt`,
`raw/bsp-grep-uefi-acpi-fdt-tegra-psci.txt`,
`raw/sdp-include-grep-tegra-hsp-tcu.txt`, `raw/sdp-listings.txt`,
`raw/bsp-zip-listing-x86.txt`. The second pass (15:30–15:45) independently
re-derived every claim below from the SDP and the zip, added the raw files listed
in section 10, and **supersedes** the first version. Where the first pass reported
something this pass could not reproduce, that is said explicitly (section 6, 10).

**Method / limits.** Nothing in the repo was rebuilt and no `mkifs` was run in this
pass. No QNX binary was disassembled. Both passes also listed archive members,
symbol names, ELF headers, version strings and leading image bytes of
QNX-shipped binaries; that output, and every claim that rested on it, was
withdrawn from this file on 2026-09-27 under NC QDL v7 clause 4.6(c) ("reduce
the Software to human-readable form"). What remains rests on file listings and
sizes, package metadata, the local docs and the BSP zip's Apache-2.0 source.
Section 3's library contents were re-read from that source on 2026-09-28, when
the listing-based evidence was withdrawn. BSP sources were extracted only to
`C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/` and are quoted at
most 30 lines at a time, from Apache-2.0-headed files only.

Evidence classes: **VERIFIED** (seen in this pass: file:line, command output),
**VENDOR_CLAIM** (a QNX doc/comment/package descriptor says so), **HYPOTHESIS**
(reasoned, untested), **UNKNOWN**.

Redactions: Windows account → `<user>`; no board access in H2 (the one
board-side cross-reference in section 5e reads H3's already-redacted capture).

---

## 0. Bottom line

1. **The generic startup library already provides every architecture-level piece a
   Tegra234 (Cortex-A78AE) startup needs** — UEFI entry + memory map +
   ExitBootServices, ACPI RSDP/table walker + SPCR, FDT parsing, PSCI (SMC/HVC)
   `CPU_ON`/reset, GICv3 + ITS bring-up with system-register *and* MMIO callouts,
   ARMv8 generic-timer `qtime`, spin-table and PSCI SMP, `cpuid_a78ae`, and an
   NVIDIA-Tegra polled-UART debug callout. Its source is the BSP zip's
   `src/hardware/startup/lib` (287 files), which builds `libstartup.a`
   (VERIFIED from source, sections 3, 5).
2. **What QNX does *not* ship:** any Tegra234/T23x/T19x board directory, any
   HSP/TCU (mailbox console) code, any Tegra register header, any NVIDIA PCI
   hardware module, the `qemu-virt` board source, and the board-API headers
   (`startup.h`, `aarch64/cpu_startup.h`, `hw/uefi.h`, `aarch64/callout.ah`)
   outside the BSP zip (VERIFIED absent, sections 4, 8).
3. **The only ARM board template is `boards/armv8_fm`** (ARM Foundation Model,
   FDT-driven). Its `main.c` carries the proprietary `$QNXLicenseC` "written
   license" header, **not** Apache-2.0; the other 11 board files and 333 of the
   338 source files in the zip are Apache-2.0 (VERIFIED by per-file census,
   `raw/bsp-src-licence-census.txt`).
4. **The `armv8_fm` board is FDT-driven, not UEFI-aware.** Its source takes
   x0 as the FDT physical address (section 5b), and a from-source build of it
   links none of the UEFI entry code
   ([build-armv8_fm.md](build-armv8_fm.md)). A check of the shipped startup
   binaries themselves was withdrawn on 2026-09-27 (4.6(c)).
5. **The repo's plain IFS is built as a raw image** (`[virtual=aarch64le,raw]`:
   `raw.boot`, which the mkifs docs describe as an instruction sequence at the
   image's start that jumps to `startup_vaddr`), so it has no Linux arm64
   `Image` header; the `qhv/guest` IFS is built `[virtual=aarch64le,elf]`. An
   aarch64le `uefi.boot` (`mkifsf_uefi`) bootfile exists although the local doc
   lists `uefi.boot` as x86_64-only (VERIFIED presence; acceptance of
   `[virtual=aarch64le,uefi]` was **not** exercised in this pass — section 6).
6. **Concrete fit problems found by reading source against the Orin Nano's live
   DT:** QNX's `fdt_psci_configure()` matches only `compatible = "arm,psci"` and
   reads a `cpu_on` property; the board's node is `"arm,psci-1.0"`, `method =
   "smc"`, no `cpu_on` — so a Tegra234 `main()` must set `psci_call = psci_smc`
   itself (VERIFIED source + H3 capture, section 5e).

---

## 1. `target/qnx/aarch64le/boot/sys/` — VERIFIED (`ls -l`, `raw/sdp-listings.txt`)

| file | bytes | what it is |
|---|---:|---|
| `startup-armv8_fm` | 1,623,920 | ARMv8 Foundation-Model startup. Delivered by package `com.qnx.qnx800.target.driver.virtio.startup` 0.1.0 build 21 (2024-11-23), "startup binaries for use with QNX guests of any supporting hypervisor" (VENDOR_CLAIM, `ResourceDescriptor.afd`). |
| `startup-qemu-virt` | 1,599,632 | QEMU `virt` startup used by every IFS this repo builds. Delivered by `com.qnx.qnx800.target.qemuvirt` 0.2.1 build 87 (2025-07-24); its `buildinfo` names the upstream repo `qnx/products/bsp/startup_boards.git` — the board source exists at QNX but is **not shipped** (VERIFIED metadata; the not-shipped part is VERIFIED by the zip listing). |
| `procnto-smp-instr` | 63,955,552 | the only kernel variant installed |
| `kdumper` | 1,374,248 | kernel dumper |
| `libmod_contextid.a` | 373,596 | procnto module |
| `uefi.boot` | 239 | `[attr="?-bigendian" +rsvd_vaddr vboot=0xffffff8060000000 len=0x200 filter="mkifsf_uefi %a %s %i" pagesizes=4k]`; comment: build file MUST give `[image=]` |
| `elf.boot` / `elf64k.boot` | 238 / 252 | `filter="mkifsf_elf %a %s %i"` — what `qhv/guest` uses |
| `raw.boot` / `raw64k.boot` | 14,832 / 14,840 | the raw-image bootfile the repo's plain IFS uses; per the mkifs docs it puts "an instruction sequence at its beginning" that jumps to `startup_vaddr` (VENDOR_CLAIM, `mkifs.html`) |
| `binary.boot` / `binary64k.boot` | 275 / 289 | plain binary, no stub |
| `srec.boot` / `srec64k.boot` | 234 / 248 | S-record |

`find qnx800 -iname 'startup-*'` → exactly these two aarch64le startups plus
`x86_64/boot/sys/startup-apic`, `startup-x86` and the two x86 doc pages. **No
Tegra/NVIDIA startup is installed** (VERIFIED). `target/qnx/aarch64le/boot/build/`
(example build files) does not exist (VERIFIED).

## 2. Host tools — VERIFIED (`raw/host-tools.txt`)

Present in `host/win64/x86_64/usr/bin`: `mkifs.exe`, `mkxfs.exe`, `mkefs.exe`,
`mkrec.exe`, `mkimage.exe`, `dumpifs.exe`, filters `mkifsf_bswap / coff / elf /
openbios / srec / uefi / vmware .exe`, toolchain `ntoaarch64-{ar,nm,objcopy,
objdump,readelf,strings,ld,ld.bfd,as,gcc-12.2.0,g++,gdb-14.2,addr2line,...}`
(binutils 2.43.0) and the `aarch64-unknown-nto-qnx8.0.0-objcopy` alias.
`mkifs.exe -h` without `QNX_TARGET` only prints "QNX_TARGET environment variable
must be set". Documented `mkifsf_uefi` options: `-e env_entry_mode`, `-M
PE_machine` ("the WIN PE machine type"), `-m elf_machine_number`, `-s
subsystem_number`, args `startup-offset image-file` (VENDOR_CLAIM, local
`mkifs.html`). The aarch64le `uefi.boot` passes **none** of `-M/-m/-s`, so the
PE machine it stamps by default is not established here (UNKNOWN in this pass;
see section 6).

## 3. `libstartup.a` — the reusable startup library

`target/qnx/aarch64le/usr/lib/libstartup.a`: 2,661,074 bytes, package
`com.qnx.qnx800.target.base.libstartup` 1.0.0 build 600 (2025-07-30). The BSP zip
carries a second copy, `prebuilt/aarch64le/usr/lib/libstartup.a` (3,283,336
bytes), and the library's source, `src/hardware/startup/lib` (287 files,
`raw/bsp-startup-lib-files.txt`), which builds `libstartup.a` unmodified
([build-armv8_fm.md](build-armv8_fm.md)). What follows is read from that source.
A listing of the shipped archives' members and symbols was withdrawn on
2026-09-27 (4.6(c)).

### 3a. What each requested piece provides (VERIFIED from the Apache-2.0 source)

Paths are under `src/hardware/startup/lib/`.

| source file(s) | defines | reading |
|---|---|---|
| `efi_entry_point.c` | `efi_entry_point`, `efi_get_table`, `efi_walk_map`, `efi_convert_command_line` | PE/COFF entry `EFI_STATUS efi_entry_point(EFI_HANDLE, EFI_SYSTEM_TABLE*)`: prints "Entering startup..." via ConOut, captures `LoadOptions` as the command line, snapshots the memory map, then continues into `cstart` (`lib/efi_entry_point.c:47-70` read; Copyright 2023 BlackBerry, Apache-2.0). |
| `efi_tweak_cmdline.c` | `efi_tweak_cmdline` | LoadOptions → startup `argv`. |
| `uefi.c` | globals `efi_image_handle`, `efi_system_table`, `efi_boot_services`, `efi_runtime_services`; `uefi_exit_init`, `uefi_find_config_tbl` | Config-table lookup by GUID; ref-counted `ExitBootServices` trampoline (`lib/uefi.c:29-80`). |
| `aarch64/uefi_init.c` | `uefi_init` | Takes `boot_regs[0]` = ImageHandle, `boot_regs[1]` = SystemTable, sets the service pointers, arms `uefi_exit_init()` (`lib/aarch64/uefi_init.c:37-57`). |
| `aarch64/is_uefi_boot.c` | `is_uefi_boot` | Validates `EFI_SYSTEM_TABLE`/`BOOT_SERVICES`/`RUNTIME_SERVICES` signatures from `boot_regs[0..1]`; memoised (`lib/aarch64/is_uefi_boot.c:22-60`). |
| `uefi_io.c` | `uefi_io_init`, `uefi_io_flush`, `uefi_print_char`, `uefi_print_str` | Debug console through `EFI_SIMPLE_TEXT_OUTPUT` before ExitBootServices — **a console path that needs no UART knowledge at all**, relevant to the TCU problem. |
| `init_raminfo_uefi.c` / `init_raminfo_efi.c` | `init_raminfo_uefi` / `init_raminfo_efi` | RAM map from `GetMemoryMap` (live BootServices call, `lib/init_raminfo_uefi.c:25-50`) / from the map saved by `efi_entry_point`. |
| `init_raminfo_fdt.c` | `init_raminfo_fdt` | RAM from FDT `/memory` + reserved-memory (`lib/init_raminfo_fdt.c:27-45`). |
| `acpi.c`, `acpi_spcr_parse.c` | `acpi_find_table`, `acpi_find_table_next`, `add_acpi_table`; `acpi_spcr_parse` | Generic RSDP→XSDT walker; SPCR parser that configures a **PL011** debug device (`init_pl011`/`put_pl011` and the `*_pl011` callouts, `lib/acpi_spcr_parse.c:35-37` — no 8250/Tegra variant wired). |
| `board_find_acpi_rsdp.c`, `aarch64/board_find_acpi_rsdp.c`, `aarch64/board_find_acpi_rsdp_uefi.c`, `aarch64/board_find_efi_smbios.c` | `board_find_acpi_rsdp[_uefi]`, `board_find_efi_smbios_table`, `board_find_efi_smbios_by_type`, `get_smbios_string` | RSDP/SMBIOS via the EFI configuration table. |
| `aarch64/callout_debug_tegra.S` | `display_char_tegra`, `poll_key_tegra`, `break_detect_tegra` | Source comment: "nVidia Tegra polled serial I/O. Similar to 8250 uart with 32-bit registers." Maps 0x1000 bytes at a patched base; TX: spin on `LSR` at `+0x14` for `LSR_TXRDY`, `strb` to `+0x00`; RX: `LSR_RXRDY` then `ldrb` from `+0x00`; `break_detect` always returns 0 (`lib/aarch64/callout_debug_tegra.S:20-140`, Copyright 2015 QNX, Apache-2.0). I.e. 8250 registers at a fixed 4-byte stride. Declared in `lib/public/aarch64/cpu_startup.h:244-250` under "nVidia Tegra UART support". **No matching `hw_sertegra` init/put** — pair with `init_8250`/`put_8250` (which honour a `^shift` field in the debug-device string, `lib/hw_ser8250.c:47,85`) or write one. |
| `aarch64/callout_debug_8250.S`, `_8250_32b.S`, `callout_debug_pl011.S` | `display_char/poll_key/break_detect_{8250,8250_32b,pl011}` | Byte-register 8250, 32-bit-register 8250, PL011. |
| `callout_debug_sbsa*` | — | **No such source file** (VERIFIED, `raw/bsp-startup-lib-files.txt`). |
| `aarch64/callout_interrupt_gic_v3.S` | `interrupt_id_gic_v3_{ppi_sr,ppi_mm,spi,lpi}`, `interrupt_eoi_gic_v3_{ppi,spi,lpi}` in `_sr` and `_mm` flavours, `interrupt_{mask,unmask}_gic_v3_{ppi,spi}`, LPI `_direct`/`_its` mask and unmask variants, `interrupt_config_gic_v3_ppi` | Kernel-side GICv3 callouts, system-register and memory-mapped-GICC, with ITS and direct-LPI. |
| `aarch64/callout_sendipi_gic_v3.S`, `aarch64/gic.c` | `sendipi_gic_v3_sr/_mm`; `gic_gicd/gicr/gicc` (+`_vaddr`), `gic_gicr_shift`, `gic_cpu_init`, `gic_sendipi` | IPI callouts and shared GIC globals. |
| `aarch64/gic_v3.c` | `gic_v3_initialize` (`gic_v3.c:940`), `gic_v3_set_paddr` / `_set_paddr_range` (`:299`), `gic_v3_use_mm_reg_callouts` (`:482`), `gic_v3_num_spis/lpis`, `gic_v3_set_intr_trig_mode`, `gic_v3_lpi_uses_its`, `gic_v3_spi_add_entry` (`:626`), `gic_v3_lpi_add_entry` (`:766`), LPI table setters, `gic_get_arch_version/impl_id/impl_version/impl_productid` | Startup-time distributor/redistributor bring-up. Source `lib/aarch64/gic_v3.c` (Copyright 2011/2021 QNX, 2016 Freescale, 2017 NXP; Apache-2.0) — the file the repo's NISV analysis already builds. |
| `aarch64/gic_v3_its.c`, `aarch64/gic_v3_dcache_flush_for_its.c` | `gic_v3_its_initialize` (`gic_v3_its.c:85`), `_set_paddr`, `_mapc`, `_set_{dt,ct,cmd_q}_*`, `_base_vaddr`, `_cmd_q_*` | ITS command queue / device & collection tables. |
| `aarch64/psci_call.S`, `common_arm/psci_cpu_id.c`, `common_arm/psci_smp.c`, `aarch64/callout_reboot_psci.S` | `psci_call` (function pointer, `psci_smc` by default), `psci_hvc`, `psci_smc`; `psci_cpu_id`; `psci_smp_start`, `psci_cpu_on_cmd` (initialised to -1); `reboot_psci_smc/_hvc` | Conduit selection, MPIDR→target id, `CPU_ON` (`lib/common_arm/psci_smp.c:30-40`), `SYSTEM_RESET` callouts. Inline wrappers for every PSCI call in `lib/public/aarch64/psci.h:81-190`. |
| `common_arm/fdt_psci_configure.c` | `fdt_psci_configure` | `fdt_node_offset_by_compatible(f, -1, "arm,psci")` then reads the `cpu_on` property and (further down) `method` to pick `psci_smc`/`psci_hvc` (`lib/common_arm/fdt_psci_configure.c:31-50`). **Exact match on `"arm,psci"` only** — see 5e. |
| `aarch64/smp_start.S`, `init_smp.c`, `common_arm/spin_smp.c`, `aarch64/spin_smp_init.S`, `aarch64/callout_smp_spin.S`, `common_arm/spin_bootstrap_id.c`, `fdt_smp_spin_start.c`, `aarch64/spin_shim_rtn.S` | `smp_start`; `init_smp`, `cpu_starting`, `smp_spin_vaddr`, `syspage_available`; `spin_smp_start`, `spin_smp_num_cpu`, `spin_num_cpu`, `spin_start_addr`; `spin_smp_init`; `smp_spin`; `spin_bootstrap_id`; `fdt_smp_spin_start`; `spin_shim_*` | Generic SMP driver (calls the board-supplied `board_smp_*` hooks) with both spin-table and PSCI secondary start. |
| `board_smp*` | — | **Not in the library source**; the four `board_smp_*` hooks are declared in `lib/public/startup.h:268-271`, referenced from `init_smp.c`, `aarch64/gic_v3.c`, `aarch64/smp_start.S` and `aarch64/spin_smp_init.S`, defined in no lib file, and come from `boards/<board>/board_smp.c`. |
| `fdt_*.c`, `common_arm/fdt_*.c`, `init_raminfo_fdt.c` (24 files) | `fdt_init`, `fdt_asinfo`, `fdt_init_bootopt`, `fdt_find_node`, `fdt_num_cpu`, `fdt_get_cpu_freq`, `fdt_qtime`, `fdt_tweak_cmdline`, `fdt_get_{int,intr,intr_cells,num64,reg32,reg64,reg64_cells,reg_addr,reg_int,str,u32,u64}`, `fdt_node_offset_by_nodename`, globals `fdt`, `fdt_paddr`, `fdt_size`, `fdt_boot_option` | Startup-side DT helpers on top of libfdt. **libfdt is not part of the lib source** (only `public/sys/libfdt_private.h`); it is `aarch64le/usr/lib/libfdt.a` (375,770 B, VERIFIED) and `boards/common.mk` adds `LIBS_aarch64 = fdt`. `fdt_init()` maps the header, `fdt_check_header()`s it, then maps the whole blob (`lib/fdt_init.c:21-38`). |
| `aarch64/cpuid_a78ae.c` | `cpuid_a78ae` (data) | `struct aarch64_cpuid cpuid_a78ae = { .midr = 0x4100D420, .name = "Cortex-A78ae" }` (`lib/aarch64/cpuid_a78ae.c:24-27`). Registered in the table `aarch64_cpuid[]` (`lib/aarch64/aarch64_cpuid.c:26-45`, file carries "Copyright 2018, NVIDIA CORPORATION" among others, Apache-2.0) together with NVIDIA Denver `cpuid_d15`/`cpuid_d20`. |
| `aarch64/init_qtime.c`, `aarch64/init_qtime_v8gt.c` | `init_qtime`; `init_qtime_v8gt` | Default `init_qtime()` = ARMv8 generic timer; `init_qtime_v8gt(vcnt_intr, hvcnt_intr)` reads `CNTFRQ_EL0` when `timer_freq == 0` (`lib/aarch64/init_qtime_v8gt.c:34-50`). **No `callout_timer*` source file exists**; the `timer_load/value/reload_armv8` callouts are declared in `cpu_startup.h:239-241` and defined in no lib source file; `init_qtime_v8gt.c` has its own static `timer_start_v8gt`/`timer_diff_v8gt` (`:24-33`). |
| `aarch64/hypervisor.c`, `aarch64/hypervisor_enable.S`, `hypervisor_setup.c` | `arch_hypervisor_init`, `hyp_enable_el1_host`, `hyp_enable_el2_host`, `hypervisor_init`, `hypervisor_set_options`, ... | EL2/VHE host enablement — what the QHV host image uses (`main.c` calls `hypervisor_init(0)`). |
| `aarch64/_start.S`, `aarch64/_start_el1.S`, `aarch64/cstart.S`, `_main.c`, `aarch64/vstart.S`, `startnext.c`, `load_ifs.c` | `_start`; `_start_el1`, `_start_el2_or_el1`, `drop_to_el1`; `cstart`, `boot_args`, `stack*`; `_main`, `uefi_{io_suspend,io_resume,exit_boot_services}_f` (fn-ptr globals, NULL by default, `_main.c:56-58`); `vstart`; `startnext`; `load_ifs` | The fixed spine. `lib/aarch64/_start.S:37-39`: "Do NOT modify registers X0-X3 before jumping to the cstart label — cstart will save them in the boot_regs variable". `_main.c:126-158`: `board_init()` → `setup_cmdline()` → `cpu_startup()` → `init_syspage_memory()` → **`main()`** → `write_syspage_memory()` → `smp_hook_rtn()` → `startnext()`; `startnext()` calls `uefi_exit_boot_services()` (a no-op unless `uefi_init()` armed it) before `cpu_startnext()` (`lib/startnext.c:29-45`). |
| `aarch64/callout_interrupt_t18x_msi.S`, `_t18x_pcie.S`, `_t18x_pcie_ic6.S` | `interrupt_{id,eoi,mask,unmask}_t18x_{msi,pcie,pcie_ic6}` | **Tegra X2 (T18x) PCIe/MSI cascade callouts**, register offsets `0xB4/0xB8/0xC8` (`lib/aarch64/callout_interrupt_t18x_pcie.S:25-33`). The only other Tegra-specific code in the SDP; not obviously applicable to Tegra234's DesignWare PCIe (HYPOTHESIS). |
| `hw_ser8250.c`, `hw_ser8250_32b.c`, `hw_ser8250_pci.c`, `common_arm/hw_serpl011.c`, `hw_serdummy.c` | `init_8250`, `init_8250_common`, `put_8250`, ...; `init_pl011`, `put_pl011` | Pre-kernel UART init/put for the `debug_device` table. |
| `board_init.c`, `board_cpuconfig1.c`, `board_cpuconfig2.c` | `board_init`, `board_cpuconfig1/2` | Empty library defaults a board may override. |

### 3b. Pieces that would matter for Tegra234 but are absent from the lib source — VERIFIED absent (`raw/bsp-startup-lib-files.txt`)

`callout_debug_sbsa*`, `callout_timer*`, `board_smp*`, libfdt (a private header only),
`hw_sertegra*`, `init_intrinfo*` (board-side), and anything named `hsp`, `tcu`,
`t19x`, `t23x`, `t234`, `nvidia`.

## 4. SDP headers — VERIFIED

* `grep -rlE 'tegra|TEGRA' usr/include` returns ~330 files — **all false positives on
  "in*tegra*l"** (C++/ICU/Python headers). Word-bounded
  `grep -rliE '\btegra|nvidia|\bt23x|\bt19x'` returns 7: `devs/include_aarch64/
  machine/cpu.h`, `devs/qnx-gen/usbdevs.h` (USB vendor id), `elfdefinitions.h`
  (`EM_CUDA`), `pci/pci_id.h` (PCI vendor id), and three Vulkan headers. `grep
  -rlwE 'hsp|HSP|tcu|TCU'` returns **nothing**. **No HSP, no TCU, no Tegra register
  header.**
* `target/qnx/aarch64le/` has **no `include` directory** (`find -type d -iname
  include` → empty).
* Startup-lib board-API headers are **not** installed in the SDP: no
  `usr/include/startup.h`, `aarch64/cpu_startup.h`, `aarch64/callout.ah`,
  `hw/uefi.h`. Present: `usr/include/sys/startup.h` (the on-disk startup
  header/trailer format), `aarch64/{gic_v3.h, gic_its.h, gic_v2.h, psci.h,
  syspage.h}`, `hw/{8250.h, acpi.h}`, `fdt.h`, `libfdt.h`, `libfdt_env.h`. So a
  board `main.c` **cannot be compiled against the bare SDP**; it needs the BSP
  zip's `src/hardware/startup/lib/public` tree (section 5).

## 5. BSP zip `BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip` — VERIFIED

Location `C:/Users/<user>/qnx800/bsp/` (11,519,604 B; x86 sibling
`BSP_hyp-guest-x86_be-800_*.zip` beside it; nothing else named `BSP_*` under
`qnx800`, `E:/` (depth 4) or `Downloads`). `unzip -l` → `raw/bsp-zip-listing.txt`
(452 entries). Package `com.qnx.qnx800.bsp.hypervisor_guest_arm` 0.2.0 build 323
(2025-07-25).

`source.xml` (VENDOR_CLAIM): id `hypervisor-guest-arm`, "Hypervisor guest for
generic ARM virtual machines", `<license>QDL and Apache II</license>`,
`<startup>startup-armv8_fm</startup>`, maturity "Development Build",
`<qnxTargetCPU variant="*">`. `readme.txt`: SVN 1018940, build 323. **No top-level
LICENSE/NOTICE file** — licensing is per-file header.

Layout (VERIFIED): `Makefile` (builds `src`, installs to `install/`, links example
build files into `images/`), `manifest`, `images/{guest-1,guest-2}/` (`.build` +
`.qvmconf`), `prebuilt/aarch64le/{boot/sys/startup-armv8_fm (307,992 B —
a different build from the SDP's 1,623,920 B one; sha256 differ),
usr/lib/libstartup.a, sbin/{shmem-guest,wdtkick}}`,
`prebuilt/usr/include/aarch64/asmoff.def`, `binary_files_with_symbols/`, and:

```
src/hardware/startup/boards/armv8_fm/   the ONLY board directory (12 files)
src/hardware/startup/boards/public/     46 SoC headers: imx8m*, ls10xx/ls20xx, rk3588, bcm2711, s32v, a1000, omap, dm6446... — no Tegra
src/hardware/startup/lib/               287 files: 159 top-level, aarch64/ 87, common_arm/ 9, public/ 30 headers
src/hardware/support/wdtkick/           watchdog kicker
src/apps/hypervisor/demos/shmem-guest/  the RQ-2 shmem demo source
```

**Licence census** over every `.c/.h/.S/.ci/.ah/.def` under `src/` (338 files,
`raw/bsp-src-licence-census.txt`): **333 Apache-2.0** (BlackBerry / QNX / NXP /
Freescale / NVIDIA copyright lines), **2 proprietary `$QNXLicenseC` "written
license / pay applicable license fees"** — `boards/armv8_fm/main.c` (Copyright
2017) and `boards/public/aarch64/ls10x6a.h` — and 3 with no header
(`lib/aarch64/cpuid_{a720,x4,x925}.c`). Consequence: `main.c`, the file a port
would naturally copy from, is **not** Apache-2.0; it is paraphrased in 5b, not
quoted.

`grep -lE 'uefi|efi_|acpi|fdt_|tegra|hsp|tcu|psci'` hits 56 files in `lib` and 4 in
`boards` (`raw/bsp-src-file-lists.txt`); word-bounded `\btegra|t18x|t23x|t19x|nvidia`
hits 8 (`aarch64_cpuid.c`, `callout_debug_tegra.S`, three `callout_interrupt_t18x_*.S`,
`cpuid_d15.c`, `cpuid_d20.c`, `public/aarch64/cpu_startup.h`); word-bounded
`hsp|tcu|sbsa|combined_uart|smmu` hits **nothing**.

### 5a. Board API a `main.c` must satisfy — `lib/public/startup.h` (Apache-2.0, 735 lines)

`startup.h:249-276`:
```c
//These are board specific routines that need to be implemented. There
//may be more syspage sections that need to be implemented for a
//particular CPU. Check the appropriate cpu_startup.h. There may be
//default implementations of these routines in the startup library that
//will work for a particular board, or set of boards.
//
void init_raminfo(void);
void init_intrinfo(void);
void init_qtime(void);
void init_cacheattr(void);
void init_cpuinfo(void);
void init_hwinfo(void);
void init_asinfo(unsigned mem);
void init_nanospin(void);
void init_mitigation_mem(void);

// Only needed for SMP systems
void init_smp(void);
unsigned board_smp_num_cpu(void);
void board_smp_init(struct smp_entry *, unsigned num_cpus);
int board_smp_start(unsigned cpu, void (*start)(void));
unsigned board_smp_adjust_num(unsigned);
extern void	(*smp_spin_vaddr)(void);
int cpu_cluster_add(const char *name, uint64_t cpumask);

// Only needed on systems with an MMU.
void init_mmu(void);
```

Other board-facing declarations, same file: `void board_init(void);` (L705,
called from `_main` before `cpu_startup`), `void tweak_cmdline(struct
bootargs_entry *, const char *);` (L396), `void handle_common_option(int);` (L393),
`void select_debug(const struct debug_device *, unsigned);` (L410; `struct
debug_device` at L183), `add_callout_array` / `void *add_callout(unsigned offset,
const struct callout_rtn *)` (L348-349), RAM `avoid_ram`/`add_ram`/`alloc_ram`
(L375-378), `int init_raminfo_uefi(void);` (L383), FDT `fdt_init(paddr_t)`,
`fdt_asinfo`, `init_raminfo_fdt`, `fdt_tweak_cmdline` (L561-568; `#define FDT_REG 0`
on aarch64, L556), `void hypervisor_init(unsigned cpunum);` + `extern int in_hvc;`
(L589-597), ACPI `acpi_find_table`, `board_find_acpi_rsdp`, `acpi_spcr_parse`
(L430-435), globals `cpu_freq`, `timer_freq`, `max_cpus`, `fdt_paddr`, `fdt_size`
(L610-633). GICv3 API in `lib/public/aarch64/gic.h:489-497`
(`gic_v3_set_paddr(gicd, gicr, gits)`, `gic_v3_initialize()`), `gic_v2_init` and
`gicv_asinfo` in `cpu_startup.h:184-185`, `boot_regs[4]` ("x0-x3 at time of entry
to _start") at `cpu_startup.h:107`.

Library-defined vs board-supplied (VERIFIED from the lib source, re-read
2026-09-28): library — `init_qtime`, `init_cacheattr`, `init_cpuinfo`,
`init_hwinfo`, `init_mmu`, `init_smp`, `init_system_private`, `board_init`
(empty), `board_cpuconfig1/2`, `board_find_acpi_rsdp`, `tweak_cmdline` (a default
that calls `cpu_tweak_cmdline()`, `tweak_cmdline.c:28-35`; `armv8_fm`'s `main.c`
overrides it), `_start` (one-instruction `b cstart`); board — `main`,
`init_raminfo`, `init_intrinfo`, `init_asinfo`, `board_smp_num_cpu`,
`board_smp_init`, `board_smp_start`, `board_smp_adjust_num`, none of which any
lib file defines (armv8_fm also overrides `_start` with EL3/GIC setup).

### 5b. What `boards/armv8_fm` does

`main.c` (226 lines, proprietary header — paraphrased, VERIFIED by reading):
(1) if `boot_regs[FDT_REG]` ≠ 0: `fdt_init()` then `fdt_psci_configure()`;
(2) `getopt` over `COMMON_OPTIONS_STRING "m:23b"` (`-m` memsize, `-2`/`-3` force
GIC version, `-b` force MMIO GICC callouts); (3) `select_debug()` with one
`debug_device` "pl011" at `0x1c090000`/`0x1c0A0000` using `init_pl011`/`put_pl011`
and the three `*_pl011` callouts; (4) reboot callout = `reboot_psci_hvc` or
`reboot_psci_smc` depending on which conduit `fdt_psci_configure()` set in
`psci_call`, else a board fallback; (5) `cpu_freq` from `-f`, else
`fdt_get_cpu_freq()`, else 100 MHz; `timer_freq` from `CNTFRQ_EL0`; (6) RAM:
`init_raminfo_fdt()` + `fdt_asinfo()` if an FDT exists, else `add_ram(0x80000000,
memsize)` (comment: "FIXME_AARCH64: need to figure out how to get RAM size"); then
`alloc_ram(shdr->ram_paddr, shdr->ram_size, 1)`; (7) `hypervisor_init(0)`,
`init_smp()`, `init_mmu()` if `STARTUP_HDR_FLAGS1_VIRTUAL`, `init_intrinfo_fm(gic_version,
use_mm)`, `init_qtime()`, `init_cacheattr()`, `init_cpuinfo()`, `init_hwinfo()`,
`add_typed_string(_CS_MACHINE, "ARMv8 Foundation Model")`, `init_system_private()`,
`print_syspage()`. This matches the vendor doc's canonical order
(`startup_hw_init.html`: `init_raminfo → init_mmu → init_intrinfo → init_qtime →
init_cacheattr → init_cpuinfo`, VENDOR_CLAIM).

`aarch64/init_intrinfo.c` (Apache-2.0, 89 lines) hard-codes Foundation-Model GIC
bases and, for v3, does exactly this (`:71-87`):
```c
	} else {
		gic_v3_set_paddr(GICD_V3PADDR, GICR_V3PADDR, GICT_V3PADDR);
		gicv_asinfo(0x2c02f000, 0x2c010000, NULL_PADDR, 0, 0);

		gic_v3_intr_lpi.num_vectors = gic_v3_num_lpis();

		gic_v3_use_mm_reg_callouts(GICC_V3PADDR, (unsigned)use_mm);
		gic_v3_initialize();
		struct smp_entry *const smp  = lsp.smp.p;
		if(smp != NULL) {
			// We didn't know the correct IPI routine to use before this point
			smp->send_ipi = (void *)gic_sendipi;
		}
	}
```

`board_smp.c` (Apache-2.0, 70 lines) — the SMP hooks a Tegra board would clone
(`:24-63`):
```c
unsigned
board_smp_num_cpu()
{
	unsigned num;

	num = fdt_num_cpu();
	if(num == 0) {
		...
			num = spin_smp_num_cpu();
		} else if(max_cpus != ~0u) {
			num = max_cpus;
		} else {
			num = 1;
		}
	}
	return num;
}
...
int
board_smp_start(unsigned cpu, void (*start)(void))
{
	if(in_hvc) {
		return psci_smp_start(cpu, start);
	}
	return spin_smp_start(cpu, start);
}
```
`init_asinfo()` is empty. `aarch64/_start.S` (Apache-2.0, 3,993 B) documents that
on the Foundation Model all cores start in EL3, sets up minimal EL2/EL3 state,
switches to EL1, cpu0 → `cstart`, others spin until `board_smp_start`. `build`:
`[+keeplinked] [image=0x80000000] [virtual=aarch64le,elf]`, `startup-armv8_fm -vv
-P2`, `devc-serpl011 -F -e 0x1c090000,37`.

### 5c. Build recipe — VERIFIED

`boards/common.mk`: `LINKER_TYPE=BOOTSTRAP`, `INSTALLDIR = boot/sys`, `NAME =
startup-$(BOARD)`, `LIBS_aarch64 = fdt`, `LIBS += startup lzo2 ucl drvr`,
`CCFLAGS_aarch64 += -mgeneral-regs-only -mstrict-align -fno-store-merging -fno-gcse
-fno-inline-small-functions`, `LDFLAGS ... --undefined=__ssp_fail`, `NEEDS_FDT = yes`
in `pinfo.mk`. `lib/common.mk`: `-O2 -fomit-frame-pointer -fno-PIE`,
`CCFLAGS_aarch64 += -mgeneral-regs-only -mstrict-align -fno-store-merging` — **no
`-fno-auto-inc-dec`**. All four extra
link inputs exist in the SDP: `libfdt.a` 375,770 B, `libdrvr.a` 392,140 B,
`liblzo2.a` 1,474,022 B, `libucl.a` 354,686 B.

### 5d. UEFI entry path — how the pieces fit (VERIFIED from source)

* `efi_entry_point()` sets `efi_system_table`, captures `LoadOptions`, snapshots the
  memory map, then continues into `cstart`; `cstart` saves x0-x3 into `boot_regs[]`
  (`cstart.S:60-62`); `is_uefi_boot()` / `uefi_init()` re-derive
  ImageHandle/SystemTable from `boot_regs[0..1]`; `init_raminfo_uefi()` builds the
  RAM map; `board_find_acpi_rsdp_uefi()` → `acpi_find_table()` → `acpi_spcr_parse()`
  picks a (PL011) console; `startnext()` finally calls `uefi_exit_boot_services()`.
* **The `armv8_fm` board does not use it.** Its source is FDT-only, expecting
  x0 = FDT physical address (5b), and a from-source build of it links none of
  the UEFI entry code ([build-armv8_fm.md](build-armv8_fm.md)). A check of the
  shipped startup binaries, made on 2026-09-09, was withdrawn on 2026-09-27
  (4.6(c)).
* Therefore a Tegra234 port needs its own board `main.c` (and probably `_start`)
  that routes `boot_regs[0..1]` through `is_uefi_boot()` → `uefi_init()` →
  `init_raminfo_uefi()` → ACPI/SPCR or a hard-coded UART — every callee already
  exists in the lib source (VERIFIED, section 3). Whether an `mkifsf_uefi`-wrapped image's PE
  entry lands on `_start` or on `efi_entry_point` is not determined here (UNKNOWN;
  `uefi.boot` reserves `len=0x200` for a header, and `mkifsf_uefi` takes `-e
  env_entry_mode`, VENDOR_CLAIM).

### 5e. Fit against the Orin Nano's live device tree — source VERIFIED, DT from H3's capture

Cross-read against `raw/orin-devicetree.txt` (H3's read-only ssh capture, already
redacted; not re-captured by H2):

| lib behaviour (VERIFIED in source) | board DT (H3 capture) | consequence |
|---|---|---|
| `fdt_psci_configure()` matches only `compatible = "arm,psci"` and reads `cpu_on` (`fdt_psci_configure.c:39-48`) | `/psci`: `compatible = "arm,psci-1.0"`, `method = "smc"`, **no `cpu_on`** | returns 0 → `psci_call` conduit never set from DT; `psci_smp_start` still defaults `psci_cpu_on_cmd = PSCI_CPU_ON` (`psci_smp.c:32-34`). A Tegra234 `main()` must assign `psci_call = psci_smc` explicitly. VERIFIED (source) / consequence HYPOTHESIS until run. |
| `callout_debug_tegra`: 8250 regs at 4-byte stride, base patched | `serial@3100000` = `"nvidia,tegra234-uart","nvidia,tegra20-uart"` (alias `serial1`); `serial@3110000/3140000` = `tegra194-hsuart`; `serial@31d0000` = `"arm,sbsa-uart"`; `stdout-path = serial0` = `/serial` = `nvidia,tegra234-tcu` (HSP mailbox, no MMIO UART) | the Tegra callout is the right *shape* for `serial@3100000` (HYPOTHESIS: register stride/ownership unverified); the PL011 callout is the candidate for the sbsa-uart (HYPOTHESIS); **the firmware console (TCU) has no QNX support at all** (VERIFIED absent). |
| `cpuid_a78ae` MIDR `0x4100D420` | cpus `enable-method = "psci"` (6×) | matches Orin's cores (HYPOTHESIS that the board's MIDR is 0x4100D42x — H3's identity capture, not re-read here). |

## 6. IFS entry format — build attributes VERIFIED, format VENDOR_CLAIM

| image | build attr (`output/build/ifs.build`) | format |
|---|---|---|
| `qnx-safety-vm/output/ifs.bin` (9,771,456 B) | `[image=0x40080000] [virtual=aarch64le,raw]`, `startup-qemu-virt` | **Raw image**: `raw.boot` puts "an instruction sequence at its beginning" that jumps to `startup_vaddr` (VENDOR_CLAIM, `mkifs.html`). No mkifs bootfile is documented to emit a Linux arm64 `Image` header. |
| `qhv/host/output/ifs.bin` (9,761,056 B) | `[virtual=aarch64le,raw]`, `startup-qemu-virt -Q enable` | raw image, same bootfile |
| `qhv/guest/output/ifs.bin` (9,783,916 B) | `[image=0x80000000] [virtual=aarch64le,elf]`, `startup-armv8_fm -H` | ELF image, "an image that looks like an ELF executable" (VENDOR_CLAIM, `mkifs.html`) — what `qvm` loads |

A byte listing of these images' leading bytes and a `dumpifs` header listing of
the plain image, both made on 2026-09-09, were withdrawn on 2026-09-27 under
clause 4.6(c): a raw image's leading bytes are the QNX-shipped bootfile's code.

**Does this `mkifs` accept `[virtual=aarch64le,uefi]`?** Established here:
`aarch64le/boot/sys/uefi.boot` and `mkifsf_uefi.exe` are present (VERIFIED); the
local doc's bootfile table lists `uefi.boot` under **x86_64 only** and `raw.boot`
under aarch64le (VENDOR_CLAIM, `mkifs.html`). The task said not to rebuild, so
this pass ran no `mkifs`. The first pass reported a scratchpad-only probe that
produced an `MZ`/`PE` file with machine `0xAA64`, PE32+, subsystem 0xA (EFI
application), and `docs/orin-port.md:349-355` records the same outcome from an
earlier session — but the first pass's `raw/uefi-probe.txt` was **never written**,
so in this run the acceptance is **reported, not reproduced: HYPOTHESIS (two
prior reports, no retained transcript)**. Even if accepted, 5d applies: a PE
wrapper does not make an FDT-driven startup such as `armv8_fm` UEFI-aware.

## 7. Local docs — VERIFIED

Docs are **local** Eclipse-help HTML: 5,140 `.html` files under `qnx800`
(5,136 under `target/qnx/usr/help/eclipse/plugins/`, 35 books), including
`com.qnx.doc.neutrino.building` (`startup/`, `startup_lib/`, `callouts/`, `ipl/`,
`bsp/`), `com.qnx.doc.neutrino.custom_bsp` (`startup.html`: "takes over after the
first-stage bootloader (BIOS, UEFI, U-boot, or IPL)"; porting checklist: DRAM size,
CPU/peripheral clocks, pinmux/GPIO, memory mapping, kernel callouts — VENDOR_CLAIM),
`com.qnx.doc.qh` (hypervisor), `com.qnx.doc.neutrino.utilities` (`m/mkifs.html`;
`s/startup-apic.html`, `s/startup-x86.html` — **no page for `startup-armv8_fm` or
`startup-qemu-virt`**). `startup_lib/` has pages for `init_intrinfo`, `init_qtime`,
`init_raminfo`, `init_smp`, `add_callout[_array]`, `alloc_qtime` but **none for the
UEFI/ACPI/FDT/PSCI/GIC helpers** — those are documented only by their Apache-2.0
source. `startup_hw_init.html` gives the canonical `main()` order and a GICv2
`init_intrinfo` example ("Enable distributor - cpu interface is initialised via
init_cpuinfo()"). Files whose *names* match `*tegra*`/`*nvidia*` are all
"integral"/"integrator" false positives; doc *contents* matching `\btegra|nvidia|
jetson|orin` are USB-launcher vendor lists, HAM examples and glossary entries —
no Tegra board guidance.

## 8. NVIDIA / Tegra-named files, packages, PCI modules — VERIFIED

* `find qnx800 -iname '*tegra*' -o -iname '*nvidia*' -o -iname '*t23x*' -o -iname
  '*t19x*'` → only "integral"/"integrator" false positives (C++ headers, security
  docs). **No NVIDIA-named file.**
* Installed packages (`.packages/metadata`, 228 ids): none mentions nvidia/tegra/
  orin/jetson. Hypervisor-related ones present: `target.hypervisor.{core,extras,
  group,libhyp,vdev.devel}`, `bsp.hypervisor_guest_{arm,x86}`, `target.qemuvirt`,
  `target.driver.virtio.{devb,devc,startup}`, `quickstart.qemu`.
* `aarch64le/lib/dll/` (190 entries): `mods-pci.so`, `vdev-pci-dummy.so`,
  `devs-vtnet_pci.so`, `mods-fdt.so`, `mods-phy_fdt.so`; `lib/dll/pci/` holds the
  generic server/cap modules and exactly one hardware module, **`pci_hw-fdt.so`** —
  no `pci_hw-nvidia*`.

## 9. Consolidated table — piece | path | what it provides | evidence class

| piece | path (under `C:/Users/<user>/qnx800/` unless noted) | what it provides for a Tegra234 startup | class |
|---|---|---|---|
| `startup-armv8_fm` | `target/qnx/aarch64le/boot/sys/` | FDT+PSCI+GICv2/v3 aarch64 startup; its board source in the BSP zip is FDT-driven, not UEFI-aware (5b) | VERIFIED (source) |
| `startup-qemu-virt` | same | the startup every repo IFS uses; board source not shipped (upstream repo named in package `buildinfo`) | VERIFIED |
| `uefi.boot` + `mkifsf_uefi.exe` | `boot/sys/`, `host/win64/x86_64/usr/bin/` | UEFI bootfile + PE filter (`-M PE_machine`, `-s subsystem`) | VERIFIED (present) / HYPOTHESIS (AArch64 PE accepted — see 6) |
| `raw.boot`, `elf.boot` | `boot/sys/` | the two bootfile types the repo actually uses | VERIFIED |
| `libstartup.a` | `target/qnx/aarch64le/usr/lib/` | the whole startup spine + UEFI/ACPI/FDT/GICv3/PSCI/SMP helpers, built from the BSP zip's lib source | VERIFIED (source) |
| `efi_entry_point.c`, `uefi.c`, `uefi_init.c`, `uefi_io.c`, `is_uefi_boot.c`, `init_raminfo_uefi.c`, `init_raminfo_efi.c`, `efi_tweak_cmdline.c` | BSP zip `lib/` | EFI entry, ExitBootServices (armed by `uefi_init`, fired in `startnext`), memory map → RAM, EFI text console, LoadOptions → argv | VERIFIED |
| `acpi.c`, `acpi_spcr_parse.c`, `board_find_acpi_rsdp*.c`, `board_find_efi_smbios.c` | BSP zip `lib/` | RSDP via EFI config table, table walker, SPCR → PL011 debug device only | VERIFIED |
| `gic_v3.c`, `gic_v3_its.c`, `gic_v3_dcache_flush_for_its.c`, `callout_interrupt_gic_v3.S`, `callout_sendipi_gic_v3.S`, `gic.c` | BSP zip `lib/aarch64/` (Apache-2.0) | GICv3/ITS bring-up and kernel callouts (SR and MMIO variants) | VERIFIED |
| `psci_call.S`, `psci_smp.c`, `psci_cpu_id.c`, `fdt_psci_configure.c`, `callout_reboot_psci.S` | BSP zip `lib/` | SMC/HVC conduit, `CPU_ON`, `SYSTEM_RESET`; FDT match string is exactly `"arm,psci"` — Orin's is `"arm,psci-1.0"` | VERIFIED (source) / HYPOTHESIS (runtime effect) |
| `smp_start.S`, `init_smp.c`, `spin_smp*`, `callout_smp_spin.S` | BSP zip `lib/` | generic SMP; needs board `board_smp_*` | VERIFIED |
| `fdt_*.c` (24 files with `init_raminfo_fdt.c`) + `libfdt.a` | BSP zip `lib/` + `aarch64le/usr/lib/libfdt.a` | DT parsing; libfdt is a separate archive | VERIFIED |
| `cpuid_a78ae.c` | BSP zip `lib/aarch64/` | MIDR `0x4100D420` "Cortex-A78ae" | VERIFIED |
| `init_qtime.c`, `init_qtime_v8gt.c` | BSP zip `lib/aarch64/` | ARMv8 generic-timer qtime; the timer callouts are declared in `cpu_startup.h`, and no `callout_timer*` source exists | VERIFIED |
| `callout_debug_tegra.S` | BSP zip `lib/aarch64/` (Apache-2.0) | polled 8250-at-4-byte-stride UART callouts (THR/RBR +0x00, LSR +0x14); no matching `hw_sertegra` init | VERIFIED (exists) / HYPOTHESIS (fits `serial@3100000`) |
| `callout_debug_8250_32b.S`, `hw_ser8250*.c`, `callout_debug_pl011.S`, `hw_serpl011.c` | BSP zip `lib/` | alternatives for the 8250-class and sbsa-uart ports | VERIFIED (exist) / HYPOTHESIS (fit) |
| `callout_interrupt_t18x_*.S` | BSP zip `lib/aarch64/` | Tegra X2 PCIe/MSI cascade callouts — legacy | VERIFIED (exist) / HYPOTHESIS (not for T234) |
| `hypervisor*` | BSP zip `lib/` | EL2/VHE host enable (QHV) | VERIFIED |
| BSP zip `src/hardware/startup/lib` (287 files) | `bsp/BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip` | full source of the above; 333/338 files Apache-2.0 | VERIFIED |
| BSP zip `lib/public/{startup.h, aarch64/*.h, hw/uefi.h, hw/acpi.h, aarch64/callout.ah}` | same zip | the board-API headers the SDP does **not** install | VERIFIED |
| BSP zip `boards/armv8_fm/` | same zip | the only board template: `main.c` (**proprietary header**), `board_smp.c`, `aarch64/init_intrinfo.c`, `aarch64/_start.S`, `init_asinfo.c`, `build` (Apache-2.0 except `main.c`) | VERIFIED |
| BSP zip `boards/common.mk`, `lib/common.mk` | same zip | link recipe (`startup fdt lzo2 ucl drvr`, `LINKER_TYPE=BOOTSTRAP`) and compile flags (no `-fno-auto-inc-dec`) | VERIFIED |
| `libdrvr.a`, `liblzo2.a`, `libucl.a`, `libfdt.a` | `target/qnx/aarch64le/usr/lib/` | the four extra link inputs `boards/common.mk` needs — all present | VERIFIED |
| `pci_hw-fdt.so` | `aarch64le/lib/dll/pci/` | only PCI hardware module; no NVIDIA one | VERIFIED |
| Local docs (5,140 HTML) | `target/qnx/usr/help/eclipse/plugins/` | Building Embedded Systems (startup, callouts, startup_lib), custom_bsp porting checklist, mkifs, qh | VERIFIED |
| Tegra / HSP / TCU headers, packages, board dirs | anywhere under `qnx800` and in the zip | **none** | VERIFIED (absent) |
| `callout_debug_sbsa*`, `callout_timer*`, `hw_sertegra`, `board_smp*`, `init_intrinfo*` in the lib | BSP zip `lib/` | **absent** — board must supply | VERIFIED (absent) |

## 10. Raw files (`raw/`)

Written by this (second) pass, all redacted:
* `bsp-zip-listing.txt` — `unzip -l` of the arm BSP zip
* `bsp-src-file-lists.txt` — `lib`/`boards` file lists and the greps
* `bsp-src-licence-census.txt` — per-file licence class for all 338 sources
* `host-tools.txt`

Left from the first pass (re-redacted where the owner column leaked the account
name): `bsp-zip-listing-x86.txt`, `bsp-startup-lib-files.txt`,
`bsp-startup-boards-files.txt`, `bsp-grep-uefi-acpi-fdt-tegra-psci.txt`,
`sdp-include-grep-tegra-hsp-tcu.txt`, `sdp-listings.txt`. The first pass also
listed `uefi-probe.txt` (**never existed**; see section 6).
`orin-*.txt` files in the same directory belong to H3 (board harvest).

Both passes also wrote listings of QNX-shipped binaries (archive members, symbol
names, ELF headers, leading image bytes, a `dumpifs` header). They were withdrawn
on 2026-09-27 under NC QDL v7 clause 4.6(c).

## 11. Unknowns / not established here

* Whether `mkifs` with this SDP accepts `[virtual=aarch64le,uefi]` and which PE
  machine/entry `mkifsf_uefi` stamps by default — reported by two earlier sessions,
  not reproduced (no retained transcript).
* Whether a `mkifsf_uefi` image's PE entry reaches `efi_entry_point` or `_start`.
* Whether `callout_debug_tegra`'s fixed 4-byte stride and `+0x14` LSR match
  Tegra234 `serial@3100000`, and whether the CPU (not the SPE/firmware) owns that
  UART on the Orin Nano dev kit.
* Whether Orin's UEFI (edk2-nvidia) exposes ACPI tables (SPCR/MADT/GTDT) to a
  non-Linux EFI application, and whether SPCR would describe a PL011-compatible
  port (the lib's SPCR path only knows PL011).
* Exact runtime effect of `fdt_psci_configure()` not matching `"arm,psci-1.0"`
  (analysed from source only).
* What the BSP-prebuilt `libstartup.a` (3,283,336 B) and the SDP one (2,661,074 B)
  differ in — the two archives were not compared.
* Contents of `boards/qemu-virt` (upstream `startup_boards.git`, not shipped).
