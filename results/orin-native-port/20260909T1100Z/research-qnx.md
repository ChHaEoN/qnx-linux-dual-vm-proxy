# R3 — External research: the QNX SDP 8.0 side of a new AArch64 board startup and QNX Hypervisor 8.0 host

Task R3 of the orin-native-port workflow, run id `20260909T1100Z`, 2026-09-09.
Scope: **what the public QNX 8.0 documentation, QNX's public source repos, NVIDIA's
public DRIVE OS material and the NC QDL v7 licence say** about (1) the AArch64
startup entry contract and UEFI, (2) the board API a startup must implement,
(3) a source-available real-board template, (4) DRIVE OS's QNX version and
NVIDIA's Orin BSP, (5) Hypervisor 8.0 host requirements, (6) licence clauses.

Where a public statement was cross-checked against the Apache-2.0 startup
source that ships in the local BSP zip (`BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip`,
already extracted read-only by task H2 to
`C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/`), the file:line is
given. No QNX binary was disassembled or dumped; binary evidence is limited to
the `ar t` / `nm` name listings that task H2 already produced (`harvest-sdp.md`).
No package was installed; the Orin was not touched by this task (board facts
below cite the H3 harvest files in `raw/`).

Evidence classes: **VERIFIED** (seen this run: file:line, command output, or a
page fetched and read), **VENDOR_CLAIM** (a document says so; a fetch-tool
summary of a page is marked "(fetch summary)"), **HYPOTHESIS** (reasoned,
untested), **UNKNOWN**. External quotes are at most 15 words each.

Redactions: Windows account -> `<user>`; no board login, LAN address, key name
or cloud id appears in this file.

---

## 0. Headline answers

| # | Question | Short answer | Class |
|---|---|---|---|
| 1 | Is AArch64 UEFI boot documented in 8.0? | **No.** The 8.0 `mkifs` page still lists `uefi.boot` under `x86_64` only; the 8.0 GA, 8.0.1, 8.0.2, 8.0.3, 8.0.4 and 8.0.5 release notes contain no UEFI / `mkifsf_uefi` / `uefi.boot` item; the only UEFI release note is SDP 7.0's, and it is x86-only. The install nevertheless ships `aarch64le/boot/sys/uefi.boot` and a full UEFI/ACPI entry path in `libstartup.a` (task H2, VERIFIED) — a **shipped-but-undocumented** capability. | VERIFIED (absence over fetched pages) + VENDOR_CLAIM |
| 1 | What does the `mkifsf_uefi` PE expect? | A standard UEFI application entry: `efi_entry_point(ImageHandle, SystemTable)`; it snapshots the memory map, calls `ExitBootServices`, then `cstart()`. **No DTB in x0.** The lib finds ACPI's RSDP through the EFI configuration table; it has **no** lookup of the DTB GUID. | VERIFIED (source) |
| 1 | Register contract for a non-UEFI (IPL/U-Boot) entry | `_start` must not touch x0–x3; `cstart` saves them to `boot_regs[4]`; the FDT-driven boards (`armv8_fm`, `qemu-virt`) and the documented `-u reg` option treat x0 as the FDT physical address. | VERIFIED (source) + VENDOR_CLAIM (`-u`) |
| 2 | What must a board supply? | `main`, `tweak_cmdline`, `init_raminfo`, `init_intrinfo`, `init_asinfo`, `board_smp_num_cpu/init/start/adjust_num`, optionally `_start`, plus the debug-device table. Everything else (GICv3+ITS bring-up, PSCI CPU_ON, generic-timer qtime, FDT helpers, UEFI/ACPI, EL2/VHE host enable) is library code. | VERIFIED (source + `nm` T/U) |
| 2 | Must startup run at EL2 for `-Q enable,el2-host`? | Yes. If startup finds itself at EL1 with `-Q enable*`, the library calls `crash()`; `el2-host` additionally requires ID_AA64MMFR1_EL1.VH, else `crash()`; without VHE (or with `el1-host`) it silently falls back to an EL1 host. The Orin Nano's UEFI hands off at EL2 (H3 evidence file). | VERIFIED (source; board evidence) |
| 2 | Does 8.0 startup parse a firmware DTB? | Yes — `fdt_init`, `init_raminfo_fdt`, `fdt_num_cpu`, `fdt_get_cpu_freq`, `fdt_psci_configure`, `fdt_asinfo` all ship; `armv8_fm` and `qemu-virt` use them. **Caveat:** `fdt_psci_configure()` matches only `compatible = "arm,psci"`, and the Orin Nano DT says `"arm,psci-1.0"`. | VERIFIED (source; board DT) |
| 2 | What UART does `callout_debug_tegra` target? | A 16550/8250 register map at a 4-byte stride (THR/RBR at +0x00, LSR at +0x14), i.e. the classic Tegra `nvidia,tegra20-uart` block. Upstream Linux drives Tegra234's `uarta`/`uarte` with that very compatible via `8250_tegra.c` (`UPIO_MEM32`, `regshift = 2`). No public BSP naming it was found. | VERIFIED (source) + VENDOR_CLAIM (upstream) |
| 3 | Source-available BSP for a real board? | Yes: `github.com/qnx/bsp_raspberrypi-bcm2711-rpi4` (GitHub, Apache-2.0 LICENSE, "Experimental Software SQML 1"), with `src/hardware/startup/boards/bcm2711/` (`main.c`, `board_smp.c`, `init_intrinfo.c`, callouts). It is **GICv2 + spin-table, no PSCI, no FDT** — a real-board pattern template, not a GICv3/PSCI template. | VERIFIED (fetched files) |
| 4 | Which SDP does DRIVE OS use on Orin? | DRIVE OS 6.0.x: **QNX SDP 7.1 + QNX OS for Safety 2.2.x** (6.0.6 page: "SDP 7.1 and QOS 2.2.2 EA"). DRIVE OS 5.1 (Xavier): SDP 7.0.0. DRIVE OS 7.x / DRIVE AGX Thor: QNX OS for Safety **8** (press release, Aug 2025; 8.0 confirms the Tegra-class port exists at QNX). On DRIVE Orin, QNX runs as a **guest under NVIDIA's hypervisor** ("a single guestOS (linux or QNX)"), not as a documented bare-metal startup. | VENDOR_CLAIM |
| 4 | Public NVIDIA QNX BSP / startup for Orin? | Nothing public beyond the directory name `nvidia-bsp` in the DRIVE OS QNX SDK layout and the patch-set naming `drive-<board>-qnx-<ver>-sdp-patchset.qpkg`. No public `startup-t23x`/`startup-tegra` string; NVIDIA: "There is no plan to have QNX on Jetson platform." | VENDOR_CLAIM / UNKNOWN |
| 5 | Hypervisor 8.0 host minimum | Firmware must boot into **EL2**; **VHE optional** (`el1-host` exists, and the official Pi 4 walkthrough uses it); **GICv2, v3 or v4** all supported (8.0.4: redistributors in one array; 8.0.5: non-contiguous GICR); SMMU needed only for DMA-device containment (`smmuman`, two-stage). Platforms: i.MX8QM, Graviton2/3, TI J784S4; "contact your QNX representative" for other boards. | VENDOR_CLAIM |
| 5 | Timing method | "Most qvm trace events are Class 10 events." — Guest Entry (ID 0), Guest Exit (ID 1), guest ClockCycles at entry/exit (ID 7). | VENDOR_CLAIM |
| 6 | Licence | NC QDL v7 (2025-12-10): 4.1(iii) grants "rights to modify the Software supplied as Source Code"; 4.6(c) forbids "disassemble or otherwise reduce the Software to human-readable form"; 4.6(d) forbids modifying binaries; 4.6(i) forbids publishing "the results of any performance or functional evaluation of the Software" without written approval. Startup lib sources carry Apache-2.0 headers (with a "review this entire file for other proprietary rights" rider); `armv8_fm/main.c` is under the QDL "written license" header. | VERIFIED (PDF text; source headers) |

---

## 1. Startup entry contract on AArch64, and UEFI

### 1.1 What the 8.0 docs say (VENDOR_CLAIM unless noted)

| Item | Text / finding | URL |
|---|---|---|
| Boot chain framing | "The boot process": hardware init "often handled by a bootloader (e.g., BIOS or UEFI for x86, U-Boot for ARM)"; the IPL "transfers control to the startup program in the image". No register-level contract is documented anywhere in the Building guide. | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/intro/intro_startup_sequence.html |
| Startup entry | "The _start() function is the entry point to the startup program" (Source code structure page). The page gives the `main()` skeleton: `add_callout_array()`, `handle_common_option()`, `init_raminfo()`, `init_mmu()` (if virtual), `init_intrinfo()`, `init_qtime()`, `init_cacheattr()`, `init_cpuinfo()`, `init_system_private()`, `print_syspage()`. | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/startup/startup_source_struct.html |
| FDT in x0 | `startup-*` option `-u [reg\|arg]`: "Add a flattened device tree (FDT) to the asinfo" section; `reg` = FDT address in the x0 register, `arg` = passed in memory. This is the only official statement tying x0 to the FDT. | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/s/startup_options.html |
| `-Q` | "Specify whether to enable access to QNX hypervisor features in the QNX OS microkernel"; AArch64 values `disable`, `enable`, `enable,el2-host`, `enable,el1-host`. | same page |
| `uefi.boot` | The `virtual` attribute's bootfile table lists `uefi.boot` with CPU type **`x86_64` only**: "Create an image that's suitable for machines with a Unified Extensible Firmware Interface (UEFI)". `binary.boot`, `elf.boot`, `srec.boot`: aarch64le + x86_64; `raw.boot`: aarch64le. | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html |
| `mkifsf_uefi` | Synopsis `mkifsf_uefi [-e env_entry_num] [-M PE_machine] [-m elf_machine_number] [-s subsystem_number] startup-offset image-file`; `-M` = "WIN PE machine type", `-s` = "WIN PE32+ subsystem". The filter is therefore architecture-parameterised — consistent with the shipped `aarch64le/boot/sys/uefi.boot` invoking it with `%a` (task H2 §1). | same page |
| History | SDP 7.0 release notes: "On x86 and x86_64 targets, Unified Extensible Firmware Interface (UEFI) systems are now supported." and "We've updated the list of bootfiles (see the virtual attribute)." — UEFI entered the product as an x86 feature. | https://www.qnx.com/developers/articles/rel_6423_0.html |
| 8.0.x release notes | SDP 8.0 GA, 8.0.1 (list, kernel, host tools), 8.0.2, 8.0.3, 8.0.4 (rn + kernel), 8.0.5: **no** item mentions UEFI, `uefi.boot`, `mkifsf_uefi`, ACPI, `libstartup`, or an AArch64 UEFI boot path (fetch summaries). The only startup-adjacent items: 8.0.2 "Added framework for future support of Generic Interrupt Controller (GIC) kernel modules"; 8.0.3 `mkqnximage` "now supports the creation of an image for use on a physical (non-virtual) target (e.g., Raspberry Pi)". | https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/about.html and the linked `8.0.x_prod_release_notes/8.0.x_rn.html` pages |
| x86 UEFI KB | "How to boot in UEFI mode" applies to SDP 7.0.0/7.1.0, **x86_64 only**; build line "make x86_64 x86_64-uefi.efi". | https://www.qnx.com/support/knowledgebase.html?id=5015Y0000017eFi |
| Docs index absence | The Startup Library chapter documents 70 functions; **none** of `uefi_*`, `efi_*`, `acpi_*`, `fdt_*`, `psci_*`, `gic_*`, `board_smp_*`, `hypervisor_init`, `select_debug` is documented (VERIFIED: the chapter index was fetched and read). | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/startup_lib/startup_library.html |

**AWS corroboration that an AArch64 UEFI startup exists inside QNX:** the QNX
OS 8.0.5 AMI "runs on the following AWS instance types: c7g, m7g, and r7g on
Graviton 3" and r8g on Graviton 4 (VENDOR_CLAIM,
https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qnxami_prod_release_notes/qnxcloud_sdp805_ami_pu_rn.html);
Graviton instances boot UEFI by default (AWS, cited in `docs/orin-port.md:359`).
Neither AMI release note names the startup or says whether it uses ACPI or a
DTB — **UNKNOWN**. The Hypervisor 8.0.5 note's "64-core Graviton 3 AMIs" tied to
"Support for non-contiguous GIC Redistributor (GICR) regions" shows that
QNX's Graviton startup does full GICv3 discovery on real firmware
(VENDOR_CLAIM,
https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qh8.0_prod_release_notes/hypervisor8.0.5_rn.html).

### 1.2 What the shipped Apache-2.0 source says (VERIFIED)

Paths are under `src/hardware/startup/lib/` in the extracted BSP zip.

* **Non-UEFI entry.** `aarch64/_start.S:37-42` — "Do NOT modify registers X0-X3 before jumping to the cstart label" … "cstart will save them in the boot_regs variable"; the default `_start` is a single `b cstart`. `aarch64/cstart.S:60-64`:

  ```asm
  	 * Save x0-x3 in boot_regs[]
  	ldr		x19, =boot_regs
  	stp		x0, x1, [x19]
  	stp		x2, x3, [x19, #16]
  ```
  then `bl _start_el2_or_el1` (line 70) and a default `vbar_el1` (77-78). The
  identical `_start.S` wording is in the public Pi 4 BSP
  (https://raw.githubusercontent.com/qnx/bsp_raspberrypi-bcm2711-rpi4/main/src/hardware/startup/boards/bcm2711/_start.S, fetched).
  Which register holds what is a **board convention**, not a library contract:
  `armv8_fm/main.c` (QDL-licensed, paraphrased) tests `boot_regs[FDT_REG]`
  (`FDT_REG` is 0 on aarch64, `public/startup.h:556`) and calls `fdt_init()` on it.

* **UEFI entry.** `efi_entry_point.c:47-97`: `efi_entry_point(EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)` — captures `LoadOptions` as the command line (59-61), loops `GetMemoryMap` (69-80), calls `ExitBootServices(ImageHandle, map_key)` (91), then `cstart()` (93-94); on failure prints "ExitBootServices failed" via `ConOut` (97). `aarch64/uefi_init.c:46-47,56`: `efi_image_handle = boot_regs[0]; efi_system_table = boot_regs[1]; … uefi_exit_init()`. `aarch64/is_uefi_boot.c:27-28,47,52,57,70`: same two `boot_regs`, then checks the `EFI_SYSTEM_TABLE`, `EFI_BOOT_SERVICES` and `EFI_RUNTIME_SERVICES` header signatures, returns 0/!0.

* **What UEFI hands over.** Per the UEFI application ABI the two arguments are ImageHandle and SystemTable — so **x0 is not a DTB** on the UEFI path. The lib locates ACPI through the EFI configuration table (`board_find_acpi_rsdp_uefi.c` → `uefi_find_config_tbl()` by GUID, `efi_entry_point.c:174-176` shows the GUID walk). `grep -i 'b1b621d5|DTB|FDT|fdt'` over `public/hw/uefi.h`, `uefi.c`, `efi_entry_point.c`, `aarch64/uefi_init.c`, `init_raminfo_uefi.c` returns **nothing**: there is no lookup of the flattened-device-tree configuration table. (The DTB GUID an EDK2 firmware publishes is `b1b621d5-f19c-41a5-830b-d9152c69aae0` — `DEVICE_TREE_GUID` in Linux `include/linux/efi.h`, VENDOR_CLAIM, https://raw.githubusercontent.com/torvalds/linux/master/include/linux/efi.h.) HYPOTHESIS: a Tegra234 UEFI startup would call `uefi_find_config_tbl()` with that GUID and then `fdt_init()` — both pieces exist, the combination is untested.

* **ACPI console path.** `acpi_spcr_parse.c:29-39` switches on `spcr->Interface_Type` and handles only `ACPI_SPCR_PL011` and `ACPI_SPCR_SBSA`, wiring `init_pl011`/`put_pl011` and the `*_pl011` callouts. No 8250/16550 or Tegra case. On the Orin Nano the shipped firmware booted Linux in **device-tree mode** with "ACPI: Interpreter disabled" (H3 evidence, `harvest-repo.md` A7), so SPCR is moot unless an ACPI toggle exists (UNKNOWN for Orin Nano, see H1 A18).

* **Neither shipped aarch64 startup links the UEFI code** (`nm` on `startup-armv8_fm` / `startup-qemu-virt`: no `efi_entry_point`, `is_uefi_boot`, `uefi_init` — task H2 §5c). The mkifs probe in H2 §6 (`[virtual=aarch64le,uefi]` → PE32+, machine 0xAA64, subsystem 0xA, entry 0x800) therefore wraps a startup whose `_start` will misread ImageHandle as an FDT pointer. HYPOTHESIS: hang or `fdt_check_header` failure before any console output.

---

## 2. The board API, GICv3, timer, SMP/PSCI, `-Q`, FDT, debug callouts

### 2.1 Board-implemented vs library-provided (VERIFIED: `public/startup.h` + `nm` T/U from H2)

`lib/public/startup.h:250-286` (Apache-2.0) declares the board hooks; the
comment above them: "There may be default implementations of these routines in
the startup library that will work for a particular board".

| Board must define | Library defines (default or full) |
|---|---|
| `main()`, `tweak_cmdline()`, `init_raminfo()`, `init_intrinfo()`, `init_asinfo()`, `board_smp_num_cpu()`, `board_smp_init()`, `board_smp_start()`, `board_smp_adjust_num()`; optionally `_start` (default is `b cstart`) | `board_init()` (empty default), `init_qtime()` (ARMv8 generic timer, `init_qtime_v8gt.o`), `init_cacheattr()`, `init_cpuinfo()`, `init_hwinfo()`, `init_mmu()`, `init_smp()`, `init_system_private()`, `board_find_acpi_rsdp()`, all `fdt_*`, `psci_*`, `gic_v3*`, `uefi*`/`efi_*`/`acpi*`, `hypervisor_*`, `smp_start`, `spin_smp*` |

Docs cross-check (VENDOR_CLAIM): the "Hardware initialization" page lists the
board sequence `init_raminfo()`, `init_mmu()`, `init_intrinfo()`,
`init_qtime()`, `init_cacheattr()`, `init_cpuinfo()` with one-line purposes
(https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/startup/startup_hw_init.html);
`init_smp()` is documented only as "Initialize the SMP functionality of the
system, assuming the hardware supports SMP" — the `board_smp_*` hooks it calls
are **undocumented** (https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/startup_lib/init_smp.html).

### 2.2 GICv3 + redistributors (VERIFIED from source, H2 §5b)

`lib/public/aarch64/gic.h:489-519`: `gic_v3_set_paddr(gicd, gicr, gits)`,
`gic_v3_set_paddr_range(gicd, gicr, gicr_size, gits)`,
`gic_v3_use_mm_reg_callouts(gicc, use_mm)`, `gic_v3_initialize()`,
`gic_v3_num_lpis()`, `gic_v3_lpi_add_entry()`, ITS setters. The `armv8_fm`
`aarch64/init_intrinfo.c` pattern (Apache-2.0) is: set paddrs → `gicv_asinfo()`
→ `gic_v3_intr_lpi.num_vectors = gic_v3_num_lpis()` → MMIO-vs-sysreg callout
choice → `gic_v3_initialize()` → `lsp.smp.p->send_ipi = gic_sendipi`. Kernel
callouts for SPI/PPI/LPI in both system-register and memory-mapped flavours
ship in `callout_interrupt_gic_v3.o` / `callout_sendipi_gic_v3.o`.
Tegra234 facts for that call: GICD `0x0f400000` (64 KiB), a **single** GICR
region at `0x0f440000` (2 MiB), `#redistributor-regions = <1>`, no ITS node,
maintenance PPI 9 — VERIFIED from the board DT (`raw/orin-devicetree.txt`) and
matching upstream `tegra234.dtsi` (VENDOR_CLAIM,
https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi).
Note the hypervisor-side constraint: QHV 8.0.4 requires "the redistributors
have to be in a single array" (VENDOR_CLAIM) — satisfied here.

### 2.3 Timer (VERIFIED)

`init_qtime()` = ARMv8 generic timer; it needs `timer_freq`, which `armv8_fm`
takes from `CNTFRQ_EL0`; the `timer_load/value/reload_armv8` callouts live in
`init_qtime_v8gt.o` (H2 §3a). Board DT: `timer` node `compatible =
"arm,armv8-timer"` (VERIFIED, `raw/orin-devicetree.txt`).

### 2.4 SMP: PSCI vs spin table (VERIFIED)

* `common_arm/psci_smp.c` → `psci_smp_start()` issues `CPU_ON`; `psci_call` is a
  function pointer set to `psci_smc`/`psci_hvc`.
* `common_arm/fdt_psci_configure.c:42`:
  `fdt_node_offset_by_compatible(f, -1, "arm,psci")` — the **only** string
  tried. The Orin Nano's live DT (`raw/orin-devicetree.txt`) has
  `compatible = "arm,psci-1.0"` and every `cpu@*` node `enable-method =
  "psci"`; H3's dmesg recorded PSCIv1.1 with the SMC conduit
  (`harvest-repo.md` A5). Consequence (HYPOTHESIS, follows directly from the
  code): on this DT `fdt_psci_configure()` finds no node, so a Tegra234 board
  must set the conduit (`psci_call = psci_smc`) and `psci_cpu_on_cmd` itself,
  exactly as the Pi 4 BSP hard-codes its own SMP method.
* Spin-table alternative: `spin_smp_start`, `spin_smp_init`, `smp_spin`,
  `fdt_smp_spin_start` also ship; `armv8_fm/board_smp.c` chooses
  `psci_smp_start` when `in_hvc` else `spin_smp_start` (paraphrase, H2 §5b).
* `-P max_CPUs` (docs) caps the count; `board_smp_adjust_num()` is the board's
  hook.

### 2.5 `-Q enable,el2-host`: what the source does at each exception level (VERIFIED)

`lib/aarch64/hypervisor.c:33-58` (Apache-2.0):

```c
    int const  current_el = (aa64_sr_rd64(CurrentEL) >> 2);
    if (current_el == 1) {
        // There is nothing we can do unless we are already at EL2
        if (option_flags & HYP_FLAG_ENABLED) {
            crash("Hypervisor support requested but CPU has no EL2 support\n");
        }
        return HYP_FLAG_DISABLED;
    }

    if (option_flags & HYP_FLAG_ENABLED) {
        int const el2_host_supported = (aa64_sr_rd64(id_aa64mmfr1_el1) & 0x0f00);
        int const el2_host_requested = (option_flags & HYP_FLAG_EL2_HOST);
        int const el1_host_requested = (option_flags & HYP_FLAG_EL1_HOST);

        if (el2_host_requested && !el2_host_supported) {
            crash("Hypervisor EL2 Host requested but CPU does not support this\n");
        }
        if (el1_host_requested || !el2_host_supported) {
            return (HYP_FLAG_ENABLED | HYP_FLAG_EL1_HOST);
        }
        return (HYP_FLAG_ENABLED | HYP_FLAG_EL2_HOST);
    }
```

and `arch_hypervisor_init()` (lines 76-112): disabled → `drop_to_el1()`;
`EL2_HOST` → `hyp_enable_el2_host()` ("Enabling EL2 host hypervisor support
(VHE)"); `EL1_HOST` → allocate an EL2 vector table, `hyp_enable_el1_host()`,
`drop_to_el1()`. So: **startup must be entered at EL2** (or drop from EL3
itself, as `armv8_fm`'s custom `_start` does); at EL1 the only outcome of
`-Q enable` is a crash; `el2-host` is the VHE mode and needs
`ID_AA64MMFR1_EL1.VH`. The Orin Nano firmware enters the OS at EL2 with VHE
("All CPU(s) started at EL2", "VHE mode initialized successfully" — H3 evidence
file, VERIFIED per `harvest-repo.md` A6). Docs agree (VENDOR_CLAIM): "el2-host …
Virtualization Host Extensions (VHE)"; "it would be unusual to specify
el1-host for such systems"
(https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/config/hyp.html).

### 2.6 FDT support in the 8.0 startup lib (VERIFIED)

28 `fdt_*.o` members (`fdt_init`, `fdt_asinfo`, `fdt_init_bootopt`,
`init_raminfo_fdt`, `fdt_num_cpu`, `fdt_get_cpu_freq`, `fdt_qtime`,
`fdt_tweak_cmdline`, `fdt_get_reg64_cells`, …; H2 §3a) over a separate
`libfdt.a` (`boards/common.mk` links `fdt`). Users: `armv8_fm` (FDT for RAM,
CPU count, CPU freq, PSCI conduit, asinfo) and `startup-qemu-virt` (`nm` shows
`fdt_init`, `fdt_psci_configure`, `init_raminfo_fdt`). The public Pi 4 BSP uses
**none** of it (§3). The `-u reg|arg` option exports the FDT to the syspage
`asinfo` for drivers (VENDOR_CLAIM; 8.0.3 io-sock `qnx.dtb_path` sysctl is the
consumer side).

### 2.7 Debug callouts (VERIFIED from `ar t` + source)

| Member | Exists | What it drives |
|---|---|---|
| `callout_debug_8250.o` / `_8250_32b.o` | yes | 16550 byte-stride / 32-bit-register variant with patchable LSR offset |
| `callout_debug_pl011.o` | yes | PL011 (also what SPCR PL011/SBSA resolve to) |
| `callout_debug_tegra.o` | yes | see below |
| `callout_debug_sbsa*` | **no** | would be a PL011 subset; HYPOTHESIS that `pl011` callouts suffice for Tegra234 `uarti` (`arm,sbsa-uart`) |
| `hw_ser8250*.o`, `hw_serpl011.o` | yes | startup-side `init_*/put_*`; **no `hw_sertegra`** |

`lib/aarch64/callout_debug_tegra.S` (Apache-2.0, "Copyright 2015, QNX Software
Systems"), lines 20-23 and 71-85:

```asm
/*
 * nVidia Tegra polled serial I/O.
 * Similar to 8250 uart with 32-bit registers.
 */
...
CALLOUT_START(display_char_tegra, 0, patch_debug)
	mov		x7, #0xabcd				// UART base address (patched)
	...
0:	ldr		w2, [x7, #0x14]
	tst		w2, #LSR_TXRDY
	...
	and		w0, w1, #0xff
```
`poll_key_tegra` and `break_detect_tegra` read LSR at `[x7, #0x14]` too
(lines 101, 127). With `hw/8250.h` `REG_TX = REG_RX = 0`, `REG_LS = 5`,
`0x14 = 5 * 4`: this is the standard 8250 map at a 4-byte register stride.
**Public evidence that Tegra234 matches:** upstream `tegra234.dtsi` gives
`uarta`/`uarte` `compatible = "nvidia,tegra234-uart", "nvidia,tegra20-uart"`,
and Linux `drivers/tty/serial/8250/8250_tegra.c` ("Serial Port driver for
Tegra devices", matches `nvidia,tegra20-uart`) sets `port->iotype =
UPIO_MEM32; port->regshift = 2;` (VENDOR_CLAIM,
https://raw.githubusercontent.com/torvalds/linux/master/drivers/tty/serial/8250/8250_tegra.c).
On the board's own L4T DT the picture is: `serial@3100000`/`@3140000` are
`nvidia,tegra194-hsuart` (NVIDIA's `serial-tegra` driver, `/dev/ttyTHS*`),
`serial@3110000` is `nvidia,tegra234-uart`,`nvidia,tegra20-uart` (8250 class),
`serial@31d0000` is `arm,sbsa-uart`, and the console is the mailbox-based
TCU `/serial` (`nvidia,tegra234-tcu`, no `reg`) — VERIFIED,
`raw/orin-devicetree.txt` and `raw/orin-ttys.txt`. HYPOTHESIS: the same silicon
UART block underlies both compatibles, so `callout_debug_tegra` should drive
any of the 8250-class Tegra234 UARTs; which one reaches a connector is the H3
question, not this task's. **Which QNX product ever shipped this callout is
UNKNOWN** — no public BSP, doc or forum post names `callout_debug_tegra` or
`display_char_tegra` (two web searches); the only public QNX–Tegra vendor
datapoint is the 2012 QNX CAR 2 press release ("add support for Tegra to the
latest generation of our automotive platform",
https://www.qnx.com/news/pr_5306_1.html).

---

## 3. A source-available BSP for a real AArch64 board

### 3.1 Raspberry Pi 4 BSP — GitHub, not GitLab (VERIFIED by fetch)

* Repo: https://github.com/qnx/bsp_raspberrypi-bcm2711-rpi4 — `LICENSE` is the
  Apache License 2.0 (raw file fetched); README: source only, needs an SDP 8.0
  licence and the packages in `source.xml`; classified "Experimental Software –
  Software Quality and Maturity Level (SQML) 1". Every source file starts with the
  SQML notice and then the Apache-2.0 header ("Copyright (c) 2020, 2022,
  BlackBerry Limited").
* `src/hardware/startup/boards/bcm2711/`: `Makefile`, `_start.S`,
  `bcm2711_init_board.c`, `bcm2711_init_raminfo.c`, `bcm2711_startup.h`,
  `board_smp.c`, `callout_debug_miniuart.S`, `callout_interrupt_bcm2711_msi.S`,
  `callout_reboot_bcm2711.S`, `hw_ser_miniuart.c`, `init_asinfo.c`,
  `init_board_type.c`, `init_intrinfo.c`, `init_intrinfo.h`, `init_wdt.c`,
  `main.c`, `mbox.c`, `mbox.h`, subdir `rpi4/` (no `init_qtime.c`, no `psci*`,
  `spin*`, `fdt*` files).
* `main.c` call order: `add_callout_array`, `init_board`, `select_debug`,
  `bcm2711_wdt_enable`, `mbox_get_clock_rate`, `bcm2711_init_raminfo`,
  `alloc_ram`, **`hypervisor_init`**, `init_smp`, `init_mmu`, `init_intrinfo`,
  `init_qtime`, `init_cacheattr`, `init_cpuinfo`, `init_hwinfo`,
  `init_system_private`, `print_syspage`; options `COMMON_OPTIONS_STRING "W:"`.
  Debug devices: `miniuart` at `fe215000` and `pl011-3` at `fe201600` (48 MHz),
  callouts `display_char_miniuart` / `display_char_pl011`. No `fdt_*`, no
  `boot_regs` use.
* `board_smp.c`: `board_smp_num_cpu` returns 4 (hard-coded);
  `board_smp_init` sets `smp->send_ipi = (void *)&sendipi_gic_v2` and enables
  mailbox-0 IRQs at `0x40000050 + …`; `board_smp_start` writes the entry to the
  spin table at `0xd8 + cpu*8` and runs `dsb sy; sev`; `board_smp_adjust_num`
  is identity. **No PSCI.**
* `init_intrinfo.c`: `gic_v2_init(0xff841000, 0xff842000)` hard-coded, plus a
  `bcm2711_msi` cascade block (`0x200` base, 32 vectors, `INTR_FLAG_MSI`).
* BSP release notes (VENDOR_CLAIM): Build 484 (2026-01-15), "Startup, I2C,
  Network, SD/MMC, Serial, SPI, PCI HW module, USB OTG host, Watchdog"
  (https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.broadcom.rpi4.bcm2711.html).

**As a template for Tegra234:** it shows the real-board shape (board init,
firmware mailbox, watchdog, MSI cascade, two debug UARTs, `hypervisor_init`
before `init_smp`) but its interrupt and SMP halves are the wrong generation
(GICv2 + spin table). For GICv3 + PSCI + FDT the closer code is the BSP zip's
`armv8_fm` board (`aarch64/init_intrinfo.c` and `board_smp.c` are Apache-2.0;
`main.c` is QDL-licensed and would have to be rewritten rather than copied).
HYPOTHESIS: combine the two.

### 3.2 GitLab (`gitlab.com/qnx`) (partly VERIFIED)

* `https://gitlab.com/qnx` and `https://gitlab.com/qnx/hypervisor` returned 403 /
  no project listing to the fetch tool (cannot enumerate).
* `https://gitlab.com/qnx/hypervisor/getting-started` README (fetched via
  `/-/raw/main/README.md`, VENDOR_CLAIM): QNX Hypervisor 8.0 on a Raspberry Pi 4,
  host built from `startup-bcm2711-rpi4` with **`-Q enable,el1-host`**
  because "there are limitations with the VHE-enabled subsystems on the Pi 4";
  packages `com.qnx.qnx800.target.hypervisor.group` +
  `com.qnx.qnx800.bsp.hw.raspberrypi_bcm2711_rpi4`; "The QNX Everywhere
  license (perpetual non-commercial) includes an entitlement to QNX Hypervisor
  8.0". Also listed by search: `custom-target-image-builds/raspberry-pi-4-qnx-8.0`
  and `quick-start-images/raspberry-pi-qnx-8.0-quick-start-image` (not fetched).
* QNX blog (2026) "Free Access to QNX Hypervisor with QNX Everywhere":
  "create an image running QNX 8.0 with QNX Hypervisor" on a Pi 4B under the
  "free non-commercial QNX Everywhere developer license" (VENDOR_CLAIM,
  https://qnx.software/en/blog/2026/free-access-to-qnx-hypervisor-with-qnx-everywhere).

---

## 4. DRIVE OS: QNX version on Tegra, and what is public about NVIDIA's Orin BSP

| Fact | Class | Source |
|---|---|---|
| DRIVE OS 6.0.6 (DRIVE AGX Orin): "SDP 7.1 and QOS 2.2.2 EA required for DRIVE OS 6.0.6"; the QNX side is delivered as `drive-qnx-[VERSION]-sdp-patchset.qpkg` imported into QNX Software Center; SDK debs `nv-driveos-repo-sdk-qnx-…`; directory layout includes `nvidia-bsp`, `bsp`, `firmware`, `tools`. | VENDOR_CLAIM (fetched) | https://developer.nvidia.com/docs/drive/drive-os/6.0.6/public/drive-os-qnx-installation/common/topics/installation/debian-packages/install-drive-os-qnx.html |
| DRIVE OS 6.0 generally: "Valid licenses for SDP 7.1 and QOS 2.2 are required" (6.0.7/6.0.8 pages, search snippets; the 6.0.8 and 6.0.10 pages themselves returned 403 or no version text). | VENDOR_CLAIM (search snippet) | https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/drive-os-qnx-installation/common/topics/installation/drive-os-qnx-setup/setup-drive-os-qnx.html |
| DRIVE OS QNX 5.1.0.0 (2019, DRIVE AGX Xavier): "QNX Software Development Platform (SDP) 7.0", build `700-SDP_3_build-aarch64-806`; patch set `drive-t186ref-qnx-5.1.0.0-sdp-patchset.qpkg`. | VENDOR_CLAIM (fetched) | https://archive.docs.nvidia.com/sdk-manager/0.9beta11/qsg-drive-qnx/index.html |
| DRIVE OS 7.x / DRIVE AGX Thor: QNX press release 2025-08-27 — "QNX OS for Safety 8 is integrated with NVIDIA DRIVE AGX Thor" (search snippets; three mirrors returned 403/404/timeout, not read directly). The DriveOS 7.0.3 Linux requirements page names only Thor variants and says nothing about QNX. | VENDOR_CLAIM (weak: not fetched) / VERIFIED (absence on the requirements page) | https://www.nasdaq.com/press-release/qnx-os-safety-integrated-nvidia-drive-agx-thor-development-kit-general-availability ; https://developer.nvidia.com/docs/drive/drive-os/7.0.3/public/drive-os-linux-installation/requirements.html |
| The DriveOS 7.x migration guide is indexed with a heading "QNX SDP 8.0 Discontinuation and Deprecation Notice" (search snippet only; the mirror is 403). What it deprecates is **UNKNOWN**. | UNKNOWN | https://manuals.plus/m/4b3163951b680f080903d0cb8a93bdadf45585933af3290a56cea5de8047bfaa |
| On DRIVE AGX Orin, QNX runs as a guest of NVIDIA's hypervisor: SivaRamaKrishnaNV, 2025-06-24: "Currently we support a single guestOS(linux or QNX)." and "Devzone release has only linux guestOS". DriveOS 7.0.3: "Virtualization System (VS) executing on CCPLEX cluster additionally has multiple UART streams" per partition; consoles use "the combined UART protocol". | VENDOR_CLAIM (fetched) | https://forums.developer.nvidia.com/t/driveworks-guest-os-hypervisor-qemu/337056/3 ; https://developer.nvidia.com/docs/drive/drive-os/7.0.3/public/drive-os-linux-sdk/embedded-software-components/DRIVE_AGX_SoC/Virtualization/Virtualized_Debug_UART/tcu_muxer.html |
| Jetson: kayccc (NVIDIA), 2024-03-04: "There is no plan to have QNX on Jetson platform."; 2024-03-05: "For DRIVE platform, there is no QNX supported by default". DRIVE OS QNX access is via an NVIDIA representative (VickNV, 2023-01-05: "Please contact your nvidia representative for this request."). | VENDOR_CLAIM (fetched) | https://forums.developer.nvidia.com/t/qnx-with-jetson-agx-orin-support-limitations/284878 ; https://forums.developer.nvidia.com/t/need-qnx-on-drive-orin-dev-kit/238778 |
| TCU: "The multiplexing is accomplished in the Sensor Processing Engine (SPE)" for Orin; the tcu_muxer "creates pseudo terminals for each SoC cluster". Board: `console=ttyTCU0`, `/serial` = `nvidia,tegra234-tcu` with no `reg`. | VENDOR_CLAIM (fetched) / VERIFIED (board DT) | https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html ; `raw/orin-devicetree.txt` |
| Public `startup-t23x` / `startup-tegra` / `startup-t194` / `startup-nvidia` strings: **none** in three searches over docs.nvidia.com / developer.nvidia.com / forums. | UNKNOWN (absence) | — |

**Reading for feasibility.** The Tegra-class QNX port unquestionably exists at
QNX/NVIDIA (SDP 7.0 on Xavier, SDP 7.1/QOS 2.2 on Orin, QOS 8 on Thor), so
"SDP 8.0-generation QNX on a Tegra CCPLEX" is not a research problem for the
vendors. But every public description places DRIVE OS QNX **inside an NVIDIA
hypervisor partition** whose console is a virtualised TCU stream — none
documents a bare-metal QNX startup on Tegra234, and NVIDIA's own BSP, startup
name and console strategy are NDA-gated. What this project would build has no
public precedent (HYPOTHESIS).

---

## 5. QNX Hypervisor 8.0 host requirements and timing

| Item | Statement | Class | URL |
|---|---|---|---|
| Exception level | "ARM boards require firmware that boots into exception level 2 (EL2)." If not: "you probably have an old board revision that the QNX hypervisor doesn't support". | VENDOR_CLAIM | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/build/boards.html |
| Firmware may disable features | "the firmware on the board may not enable or may even expressly disable" virtualization capabilities. | VENDOR_CLAIM | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/build/build.html |
| VHE | `-Q enable,el2-host` = VHE, host at EL2 "at all times"; `el1-host` = no VHE; "ARMv8.1 and later CPUs support el2-host and VHE". 8.0.4 notes: host "can run at either exception level 1 (EL1) or exception level 2 (EL2)". VHE is therefore **optional** (and the official Pi 4 walkthrough runs `el1-host` on Cortex-A72). | VENDOR_CLAIM | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/config/hyp.html ; https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qh8.0_prod_release_notes/hypervisor8.0.4_rn.html |
| GIC | 8.0.4: supports "GIC versions 2.0, 3.x, and 4.x"; "the redistributors have to be in a single array". 8.0.5: "Support for non-contiguous GIC Redistributor (GICR) regions". `vdev gic` defaults to version 3 (Foundation-Model addresses) and can present v2; KB: a BCM2711 (GICv2) host needed `vdev gic version 2` for a Linux guest, fixed in "Hypervisor 8.0 build 549 (published on June 12, 2025)". A GICv3 vdev caps a guest at 8 vCPUs. **GICv3 is not a host requirement.** | VENDOR_CLAIM | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/vdev_ref/vdev_gic.html ; https://www.qnx.com/support/knowledgebase.html?id=501OI00000PEvha ; https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/vm/cpu.html |
| SMMU | Needed only for DMA-device containment/pass-through: `smmuman` programs "two-stage IOMMU/SMMUs"; ARM guests running `smmuman` must load `libfdt.so`. Not a boot requirement. | VENDOR_CLAIM (search snippets of the smmuman pages) | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/protection/smmuman.html |
| Timers | "no-drift design for virtualized time"; no explicit virtual-timer hardware requirement found in the fetched pages. | VENDOR_CLAIM / UNKNOWN | https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/hypervisor8.0_rn.html |
| Platforms | GA: i.MX8QM, AWS Graviton2, Intel Raptor Lake. 8.0.5: i.MX8QM, "AWS Graviton2, Graviton3", "Texas Instruments (TI) Jacinto 784S4"; x86: Raptor Lake, "AMD Dell Pro Slim QCS1255". "For information about support for specific boards, contact your QNX representative." Raspberry Pi 4 is **not** in the list — it is served through the SQML-1 BSP + GitLab walkthrough instead. | VENDOR_CLAIM | https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qh8.0_prod_release_notes/hypervisor8.0.5_rn.html |
| "Experimental" | Only the AMD SVM package is labelled experimental in 8.0.5; the Pi 4 BSP is "Experimental Software (SQML 1)". No text addresses running the hypervisor on an arbitrary/unsupported board beyond the EL2 rule and "contact your QNX representative". | VENDOR_CLAIM | same |
| Guests | QNX OS 8.0.x, Linux (Ubuntu 22.04), Android via sales. | VENDOR_CLAIM | same |
| Timing method | "Most qvm trace events are Class 10 events." Guest Entry = ID 0, Guest Exit = ID 1, ID 7 = guest `ClockCycles()` `at_entry` / `at_exit`. | VENDOR_CLAIM | https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/debug/trace_events.html |

Tegra234 against that list (VERIFIED board facts, H3): EL2 + VHE at hand-off;
GICv3 with one GICR array; SMMU present but irrelevant to a first boot; generic
timer present. Nothing in the public requirements excludes it; nothing
includes it.

---

## 6. Licence

**Governing text:** "QNX DEVELOPMENT LICENSE AGREEMENT (Non-Commercial
License)", file stamp `BB_QNX_Development_License_Non-Commerical_License_Class_v7_2025-12-10`
(VERIFIED — PDF fetched from the `support7.qnx.com` redirect of
https://www.qnx.com/download/download/51624/BB_QNX_Development_License_Non-Commercial_License_Class_v7_2025-12-10.pdf
and text-extracted; line numbers refer to the `pdftotext -layout` output).

| Clause | Quote (<=15 words) | Effect on this port | Class |
|---|---|---|---|
| 4.1(iii) (l.231-235) | "which includes rights to modify the Software supplied as Source Code" | Writing a Tegra234 `startup-*` from the shipped `src/hardware/startup/lib` and `boards/` sources is within the grant, for a Non-Commercial Target System. | VERIFIED |
| Def. "Non-Commercial Target System(s)" (l.146-148) | "provided the target system is built for Non-Commercial Purpose(s)" | No hardware list; an Orin Nano qualifies. | VERIFIED |
| Def. "Experimental Software" (l.188-191) | "includes all custom code and/or modifications to Commercially Released Software" | Anything written here is Experimental Software (as-is, no support). | VERIFIED |
| Def. "Source Code" (l.193-195) | "Some Software files may be delivered in Source Code format." | The BSP zip's `.c/.S/.h` are that case. | VERIFIED |
| 4.6(c) (l.351-353) | "disassemble or otherwise reduce the Software to human-readable form" | Bars `objdump -d` on shipped binaries (the repo's 2026-07-28 disassembly of `startup-qemu-virt` is the flagged item; the Apache-source route is clean). | VERIFIED |
| 4.6(d) (l.353) | "modify any Software delivered in binary code" | Bars binary-patching `startup-qemu-virt`/`procnto`; a rebuilt startup from source is the permitted path. | VERIFIED |
| 4.6(g) (l.356-357) | "distribute, sell, license or otherwise provide the Software to third parties" | Do not commit QNX binaries, headers or IFS images to the public repo. | VERIFIED |
| 4.6(i) (l.358-360) | "the results of any performance or functional evaluation of the Software" (may not be released "without the prior written approval of BlackBerry") | Reads on every published latency / boot-time number in this repo, native-Orin ones included. Owner decision recorded in ADR-003. | VERIFIED |
| 4.6(b) (l.349-351) | "on systems which are not owned or under the control of Developer" | The Orin Nano must be the developer's own. | VERIFIED |
| 5.1 (l.~400) | "the OSS license shall prevail with respect to the specific third-party Open Source Software" | Where a file is Apache-2.0, Apache-2.0 governs that file. | VERIFIED |
| Exhibit A 1.1(i) (l.795) | "use the Cloud Target System Image in a Cloud Computing Environment" | Cloud/AMI use is a separate, fee-bearing grant — relevant only to the ADR-003 AWS route. | VERIFIED |

**Apache-2.0 headers in the BSP lib (VERIFIED from files):**
`lib/aarch64/gic_v3.c` — "Copyright 2011, 2021 QNX Software Systems" /
"Copyright 2016, Freescale" / "Copyright 2017 NXP", "Licensed under the Apache
License, Version 2.0"; `lib/aarch64/callout_debug_tegra.S` — "Copyright 2015,
QNX Software Systems", Apache-2.0, with the standard rider "review this entire
file for other proprietary rights or license notices" pointing at
`http://licensing.qnx.com/license-guide/`. Task H2's census: 330 Apache-2.0
files, 2 QDL-headed (`boards/armv8_fm/main.c`: "You must obtain a written
license from and pay applicable license fees to QNX", Copyright 2017;
`boards/public/aarch64/ls10x6a.h`), 3 without a header. Public Pi 4 BSP: an
Apache-2.0 `LICENSE` plus the SQML-1 notice in each file.

---

## 7. Consolidated fact table

| # | Claim | Class | Evidence |
|---|---|---|---|
| F1 | 8.0 `mkifs` docs list `uefi.boot` for `x86_64` only | VENDOR_CLAIM | mkifs.html bootfile table (fetched) |
| F2 | No SDP 8.0/8.0.1–8.0.5 release note mentions UEFI, `uefi.boot`, `mkifsf_uefi`, ACPI or an AArch64 UEFI path | VERIFIED (absence, fetch summaries) | sdp8_rn, 8.0.1 list/kernel/host_tools, 8.0.2_rn, 8.0.3_rn, 8.0.4_rn/kernel, 8.0.5_rn |
| F3 | UEFI support entered SDP as an x86/x86_64 feature (7.0) | VENDOR_CLAIM | rel_6423_0.html |
| F4 | `mkifsf_uefi` takes `-M PE_machine` / `-s subsystem` — architecture-parameterised | VENDOR_CLAIM | mkifs.html |
| F5 | The install ships `aarch64le/boot/sys/uefi.boot` and `mkifs` emits a 0xAA64 PE32+ EFI application for `[virtual=aarch64le,uefi]` | VERIFIED (H2 §1, §6, read this run) | `harvest-sdp.md` |
| F6 | `efi_entry_point(ImageHandle, SystemTable)` → LoadOptions → GetMemoryMap → ExitBootServices → `cstart()` | VERIFIED | `lib/efi_entry_point.c:47-97` |
| F7 | `is_uefi_boot()`/`uefi_init()` derive ImageHandle/SystemTable from `boot_regs[0..1]` and validate three table signatures | VERIFIED | `lib/aarch64/is_uefi_boot.c:27-70`, `uefi_init.c:46-56` |
| F8 | The UEFI lib path has no DTB-GUID lookup; ACPI RSDP is found via the EFI configuration table | VERIFIED (grep absence; source) | `board_find_acpi_rsdp_uefi.c`, `efi_entry_point.c:174-176` |
| F9 | EDK2-style firmware publishes the DTB as config table `b1b621d5-f19c-41a5-830b-d9152c69aae0` | VENDOR_CLAIM | Linux `include/linux/efi.h` `DEVICE_TREE_GUID` |
| F10 | `_start` must preserve x0–x3; `cstart` stores them in `boot_regs[]` | VERIFIED | `lib/aarch64/_start.S:37-42`, `cstart.S:60-64`; Pi 4 `_start.S` (GitHub) |
| F11 | `-u reg` documents "FDT address in x0 register" | VENDOR_CLAIM | startup_options.html |
| F12 | SPCR parsing handles PL011/SBSA only | VERIFIED | `lib/acpi_spcr_parse.c:29-39` |
| F13 | Board must supply `main`, `tweak_cmdline`, `init_raminfo`, `init_intrinfo`, `init_asinfo`, `board_smp_*`; lib supplies the rest | VERIFIED | `lib/public/startup.h:250-286`; `nm` T/U (H2) |
| F14 | `board_smp_*`, `fdt_*`, `psci_*`, `gic_*`, `uefi*`, `acpi*`, `hypervisor_init` are undocumented in 8.0's Startup Library chapter | VERIFIED (index read) | startup_library.html |
| F15 | GICv3 bring-up API: `gic_v3_set_paddr[_range]`, `gic_v3_use_mm_reg_callouts`, `gic_v3_initialize`, ITS/LPI setters | VERIFIED | `lib/public/aarch64/gic.h:489-519` (H2) |
| F16 | `fdt_psci_configure()` matches only `"arm,psci"`; the Orin Nano DT says `"arm,psci-1.0"` | VERIFIED | `common_arm/fdt_psci_configure.c:42`; `raw/orin-devicetree.txt` |
| F17 | `-Q enable*` at EL1 → `crash("Hypervisor support requested but CPU has no EL2 support")`; `el2-host` without VH → crash; no VH → EL1 host | VERIFIED | `lib/aarch64/hypervisor.c:33-58` |
| F18 | Orin Nano UEFI enters the OS at EL2 with VHE, DT mode, no ACPI tables | VERIFIED (H3 evidence file) | `harvest-repo.md` A4–A7 |
| F19 | `callout_debug_tegra`: 8250 map at 4-byte stride, LSR at +0x14, THR/RBR at +0 | VERIFIED | `lib/aarch64/callout_debug_tegra.S:20-23,77,101,127`; `hw/8250.h` |
| F20 | Tegra234 `uarta`/`uarte` are `nvidia,tegra20-uart`-compatible; Linux 8250_tegra uses `UPIO_MEM32`, `regshift = 2` | VENDOR_CLAIM | upstream `tegra234.dtsi`, `8250_tegra.c` |
| F21 | Board DT: `serial@3110000` is tegra20-uart class; `@3100000`/`@3140000` are `tegra194-hsuart`; `@31d0000` is `arm,sbsa-uart`; console is mailbox TCU | VERIFIED | `raw/orin-devicetree.txt`, `raw/orin-ttys.txt` |
| F22 | No public artefact names `callout_debug_tegra` / `display_char_tegra` | UNKNOWN (absence) | two web searches |
| F23 | Pi 4 BSP on GitHub: Apache-2.0 LICENSE, SQML 1, full `boards/bcm2711` startup source | VERIFIED | fetched tree, LICENSE, `main.c`, `board_smp.c`, `init_intrinfo.c` |
| F24 | Pi 4 startup is GICv2 + spin table (`0xd8 + cpu*8`, `dsb sy; sev`), 4 CPUs hard-coded, no PSCI, no FDT | VERIFIED | `board_smp.c`, `init_intrinfo.c`, `main.c` (fetched) |
| F25 | Official Hypervisor-on-Pi-4 walkthrough uses `-Q enable,el1-host` ("limitations with the VHE-enabled subsystems on the Pi 4") | VENDOR_CLAIM | gitlab.com/qnx/hypervisor/getting-started README |
| F26 | DRIVE OS 6.0.6: "SDP 7.1 and QOS 2.2.2 EA"; SDK layout has `nvidia-bsp` | VENDOR_CLAIM | developer.nvidia.com 6.0.6 install page |
| F27 | DRIVE OS QNX 5.1.0.0: SDP 7.0.0 (`700-SDP_3_build-aarch64-806`), `drive-t186ref-qnx-…-sdp-patchset.qpkg` | VENDOR_CLAIM | archive.docs.nvidia.com SDK-Manager quickstart |
| F28 | QNX OS for Safety 8 integrated in DRIVE AGX Thor dev kit (2025-08-27) | VENDOR_CLAIM (search snippets only) | press-release mirrors |
| F29 | On DRIVE Orin QNX is a hypervisor guest: "a single guestOS(linux or QNX)" | VENDOR_CLAIM | NVIDIA forum 337056 (2025-06-24) |
| F30 | NVIDIA: no plan for QNX on Jetson; DRIVE QNX via representative | VENDOR_CLAIM | forums 284878, 238778 |
| F31 | QHV host: firmware must boot into EL2; VHE optional; GIC v2/v3/v4; SMMU only for DMA containment | VENDOR_CLAIM | build/boards.html, config/hyp.html, 8.0.4/8.0.5 rn, smmuman pages |
| F32 | QHV 8.0.5 platforms: i.MX8QM, Graviton2/3, TI J784S4, Raptor Lake, AMD Dell Pro Slim; "contact your QNX representative" | VENDOR_CLAIM | hypervisor8.0.5_rn.html |
| F33 | qvm trace: Class 10; Guest Entry/Exit IDs 0/1; ID 7 ClockCycles at entry/exit | VENDOR_CLAIM | debug/trace_events.html |
| F34 | NC QDL v7 4.1(iii), 4.6(b)(c)(d)(g)(i), definitions, 5.1, Exhibit A as quoted in §6 | VERIFIED | PDF text |
| F35 | BSP lib files carry Apache-2.0 headers; `armv8_fm/main.c` carries the QDL header | VERIFIED | file headers (`gic_v3.c`, `callout_debug_tegra.S`, `main.c`) |

---

## 8. Looked for and not found / unknowns

* Any 8.0.x release note or doc page that documents AArch64 UEFI boot (`uefi.boot` for `aarch64le`, `is_uefi_boot`, `uefi_init`, `efi_entry_point`, `init_raminfo_uefi`, `acpi_spcr_parse`). The capability is shipped and used by the AWS AMI product but is undocumented.
* Which startup the QNX OS 8.0.x AMI uses on Graviton, and whether it consumes ACPI or a DTB (AMI release notes say nothing; "QNX Amazon Machine Image Technotes" not reached).
* Any public QNX statement about running the hypervisor on a board outside the reference list (only "contact your QNX representative" and the EL2 rule).
* An explicit virtual-timer / GIC-virtualization-extension hardware requirement for the QHV host (not stated on the fetched pages).
* Any public NVIDIA QNX startup name for Tegra (`startup-t23x` etc.), the contents of `nvidia-bsp`, or how DRIVE OS QNX gets its console (the DRIVE OS 7.0.3 page describes the combined-UART muxer for partitions, not a QNX startup callout).
* Which product ever shipped `callout_debug_tegra` (file is 2015-dated; the only public QNX–Tegra datapoint is the 2012 QNX CAR 2 press release).
* What the DriveOS 7.x migration guide's "QNX SDP 8.0 Discontinuation and Deprecation Notice" heading actually says (mirror 403; official PDF path unknown).
* Whether the Orin Nano UEFI exposes an ACPI hardware-description mode (would make the lib's SPCR/PL011 path usable via `uarti`) — carried over from H1 A18.
* `gitlab.com/qnx` project inventory (403 to the fetch tool); only the hypervisor getting-started README was readable.
* Text of the QOS-8/Thor press release (three mirrors 403/404/timeout; search snippets only).

## 9. URL index

QNX docs: intro_startup_sequence.html, startup/startup_about.html, startup_source_struct.html, startup_source_mod.html, startup_hw_init.html, startup_tasks.html, startup_lib/startup_library.html, startup_lib/init_smp.html, callouts/callout_debug.html, utilities m/mkifs.html, utilities s/startup_options.html, custom_bsp/topic/startup.html — all under https://www.qnx.com/developers/docs/8.0/ ; hypervisor.user: config/hyp.html, build/build.html, build/boards.html, vdev_ref/vdev_gic.html, vm/cpu.html, debug/trace_events.html, virt/arch.html, protection/smmuman.html, about.html.
Release notes: https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/about.html (and sdp8_rn, 8.0.x_prod_release_notes/*, hypervisor8.0_rn, qh8.0_prod_release_notes/hypervisor8.0.4_rn / 8.0.5_rn, qnxcloud_list, qnxami_prod_release_notes/qnxcloud_sdp8_ami_rn / sdp805_ami_pu_rn), https://www.qnx.com/developers/articles/rel_6423_0.html, https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.broadcom.rpi4.bcm2711.html.
KB: https://www.qnx.com/support/knowledgebase.html?id=5015Y0000017eFi ; https://www.qnx.com/support/knowledgebase.html?id=501OI00000PEvha.
Source: https://github.com/qnx/bsp_raspberrypi-bcm2711-rpi4 (+ raw `LICENSE`, `src/hardware/startup/boards/bcm2711/{_start.S,main.c,board_smp.c,init_intrinfo.c}`), https://gitlab.com/qnx/hypervisor/getting-started, https://qnx.software/en/blog/2026/free-access-to-qnx-hypervisor-with-qnx-everywhere, https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi, https://raw.githubusercontent.com/torvalds/linux/master/drivers/tty/serial/8250/8250_tegra.c, https://raw.githubusercontent.com/torvalds/linux/master/include/linux/efi.h.
NVIDIA: https://developer.nvidia.com/docs/drive/drive-os/6.0.6/public/drive-os-qnx-installation/common/topics/installation/debian-packages/install-drive-os-qnx.html, https://archive.docs.nvidia.com/sdk-manager/0.9beta11/qsg-drive-qnx/index.html, https://developer.nvidia.com/docs/drive/drive-os/7.0.3/public/drive-os-linux-installation/requirements.html, https://developer.nvidia.com/docs/drive/drive-os/7.0.3/public/drive-os-linux-sdk/embedded-software-components/DRIVE_AGX_SoC/Virtualization/Virtualized_Debug_UART/tcu_muxer.html, https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html, https://forums.developer.nvidia.com/t/337056/3, https://forums.developer.nvidia.com/t/284878, https://forums.developer.nvidia.com/t/238778, https://www.qnx.com/news/pr_5306_1.html.
Licence: https://www.qnx.com/download/download/51624/BB_QNX_Development_License_Non-Commercial_License_Class_v7_2025-12-10.pdf (302 → support7.qnx.com).
Community (not relied on for any class above VENDOR_CLAIM): https://huangweiliang.github.io/2026/02/03/QNX-Startup/.
