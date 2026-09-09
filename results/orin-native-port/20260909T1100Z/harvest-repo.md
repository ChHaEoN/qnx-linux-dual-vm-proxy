# H1 — Repo harvest: what this repo has already established or claimed about a NATIVE (no-QEMU) QNX SDP 8.0 / QNX Hypervisor 8.0 port to the Jetson Orin Nano (Tegra234)

Task H1 of the orin-native-port workflow. Read-only pass over the repo at
commit `e161636` (2026-09-09 12:39 +0200, working tree clean at read time).
No tracked file was modified. Redactions applied: Orin login -> `<user>`,
LAN addresses -> `<orin-ip>`/`<lan-ip>`, Windows account -> `<user>`,
ssh key -> `<orin-key>`, cloud ids -> `<redacted>`.

**Evidence classes** are given *as the repo records them*, mapped onto the
four classes of this workflow:

| Repo tag | Mapped class | Meaning |
|---|---|---|
| `[local]` / a log file / a `[x]` with a log | **VERIFIED** | the repo inspected a local file, built something, or captured a log — and H1 could see the artefact (file:line) |
| `[vendor]`, `[vendor source]`, `[vendor forum]`, `[community]` | **VENDOR_CLAIM** | a document says so (community sources are marked as such in the notes) |
| `[inference]`, "not verified", "assessed", "hypothesised" | **HYPOTHESIS** | reasoned, untested |
| "looked for and not found", "unknown", "未知" | **UNKNOWN** | the repo names it as open |

Where H1 re-checked something locally today (listing-only, no disassembly), it is
noted under "H1 cross-check". Nothing was upgraded without such a check.

Files the task named that **do not exist under those names**:
`skills/jetson/README.md` and `skills/tegra-virt/README.md`. The nearest
files are `skills/jetson-platform/README.md` and
`skills/tegra-virtualization/README.md` (index: `skills/README.md:27-28`);
those were read instead.

---

## 1. Facts table

### A. Boot chain and the exception level the Orin firmware hands the OS — question (a)

| # | Claim (as the repo records it) | Source (file:line) | Class | Notes |
|---|---|---|---|---|
| A1 | The board's own EL2/UEFI boot record exists in the repo and is linked from ADR-003 as "本板 EL2/UEFI 開機證據". | `docs/adr-003-hardware-timed-qhv.md:8-9`; `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt` (2,428 bytes; tracked, added in commit `61ada03`) | VERIFIED | File is real and tracked. H1 did not ssh to the board (out of H1 scope), so the *capture* is the repo's assertion; the *content* was read. |
| A2 | Header: captured 2026-09-09 over ssh, read-only (dmesg, `/proc/device-tree`, `/sys/firmware`); "Previously the repo asserted 'UEFI hands off at EL2 / VHE' for this board from a public AGX Orin dmesg — a test-before-claim gap the ADR-003 research flagged. This is the board itself." | `orin-l4t-boot-el2-uefi-evidence.txt:1-4` | VERIFIED (header text) | Provenance claim is the repo's; internally consistent (MIDR, model string, kernel version all match the Orin Nano). |
| A3 | Kernel `Linux 5.15.148-tegra aarch64`; model `NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super`; compatible `nvidia,p3768-0000+p3767-0005-super nvidia,p3767-0005 nvidia,tegra234`. | `…evidence.txt:12,14,16` | VERIFIED | Matches `docs/orin-port.md:73,81` (L4T R36.4.7, 5.15.148-tegra). |
| A4 | `efi: EFI v2.70 by EDK II`; `/sys/firmware/efi` present (`efivars esrt fw_platform_size systab`). | `…evidence.txt:27,17-21` | VERIFIED | The OS was entered via UEFI on this board. |
| A5 | `psci: PSCIv1.1 detected in firmware`; conduit probed from DT; `SMC Calling Convention v1.2`. | `…evidence.txt:29-33` | VERIFIED | PSCI via SMC — consistent with `orin-port.md:257` (`arm,psci-1.0`, `method = "smc"`). |
| A6 | **`CPU: All CPU(s) started at EL2`** and **`kvm [1]: VHE mode initialized successfully`**. | `…evidence.txt:34,42` | VERIFIED | This is the load-bearing hand-off fact: firmware enters the OS at EL2 with VHE available on this Orin Nano. |
| A7 | `ACPI: Interpreter disabled.`; `pnp: PnP ACPI: disabled`; `EINJ: ACPI disabled.`; `/sys/firmware/acpi/tables` absent. | `…evidence.txt:35-36,43,22-23` | VERIFIED | The shipped firmware booted this board in **device-tree mode**; no ACPI tables were handed to the OS. |
| A8 | `kvm [1]: GICv3: no GICV resource entry`; `disabling GICv2 emulation`; `GIC system register CPU interface enabled`; `vgic interrupt IRQ9`; `IPA Size Limit: 48 bits`. | `…evidence.txt:37-41` | VERIFIED | Included "for the GICv3 story"; matches `orin-port.md:90` ("host does not support in-kernel GICv2 emulation"). Native-port relevance: GIC maintenance PPI 9 (`orin-port.md:255`). |
| A9 | Boot CPU MIDR `0x410fd421` (implementer 0x41, part 0xD42, r0p1). | `…evidence.txt:25` | VERIFIED | Consistent with `cpuid_a78ae.c` MIDR `0x4100D420` "Cortex-A78ae" (`orin-port.md:254`). |
| A10 | TF-A hands BL33 to "the highest available Exception Level (EL2 if available, otherwise EL1)"; Linux `booting.rst` requires non-secure EL2 (recommended) or EL1. | `docs/orin-port.md:204-210`; `docs/adr-003-hardware-timed-qhv.md:51` [b2] | VENDOR_CLAIM | General ARM firmware convention; the board-level fact is A6. |
| A11 | A *public AGX Orin* dmesg (5.10.120-tegra) shows `EFI v2.70 by EDK II`, `All CPU(s) started at EL2`, `PSCIv1.1`, `VHE mode initialized successfully`, `console [ttyTCU0] enabled`; kernel source ties those strings to `is_hyp_mode_available()` / `in_hyp_mode`. | `docs/orin-port.md:211-218` | VENDOR_CLAIM (community log + vendor source) | Was the *only* EL2 evidence before A1-A6 existed. |
| A12 | "EL2 entry on this Orin Nano is verified, not assumed" — resting on step 2's `[x] … dmesg shows VHE mode initialized successfully`. | `docs/orin-port.md:218-220`; `docs/orin-port.md:90` | VERIFIED *now* (via A6); the repo's own ADR flagged that, at the time, it rested on "one ticked sentence" with no retained log | See A13. |
| A13 | ADR-003 says the board's dmesg "沒有留存" (not retained) — "只有 orin-port.md 一個打勾句子；違反 repo 'test before claim'" — and lists capturing it as the first zero-cost gate and as unknown #2. | `docs/adr-003-hardware-timed-qhv.md:52,58,102,129` | STALE TEXT | Contradicted by `adr-003:8-9` and the evidence file, all in the same commit `61ada03`; the gate is closed but three sentences still say it is open. |
| A14 | Boot chain: BootROM -> PSCROM -> MB1 -> MB2 -> UEFI -> kernel; UEFI "replaces CBoot … as the CPUBL"; no TF-A/EL stages named on that page. | `docs/orin-port.md:191-194` | VENDOR_CLAIM | ADR-003 phrases it BootROM -> MB1 -> MB2 -> UEFI (edk2-nvidia) -> L4TLauncher -> kernel (`adr-003:51`). |
| A15 | L4TLauncher is the default OS loader; kernel loaded via its EFI stub; boot from eMMC/SD/UFS/NVMe/USB; Boot Manager via ESC; UEFI shell on by default (Kconfig `default y`); GRUB may replace `BOOTAA64.efi` — i.e. an arbitrary EFI application can be the OS loader. | `docs/orin-port.md:196-203`; `adr-003:51` [b1] | VENDOR_CLAIM | `orin-port.md:202` cites `grub-install --target=arm64-efi`; ADR-003 §5 corrects: that flag "不在 NVIDIA 頁面上" — the page says `grub-install --bootloader-id=Ubuntu` (`adr-003:138`). |
| A16 | edk2-nvidia `t23x_general.defconfig` selects `BuildGeneral.conf`, which does `imply ACPI`, `imply DEVICETREE`, `imply DEFAULT_SMBIOS_ARM`, `imply SELECT_ALL_SHELL_COMMANDS`, `imply DEFAULT_SERIAL_PORT_CONSOLE_TEGRA`; `TEGRA_ACPI depends on SOC_GENERAL \|\| SOC_DATACENTER`. | `docs/orin-port.md:221-231`; `adr-003:51` [b7] | VENDOR_CLAIM (source defaults) | ADR-003 explicitly downgrades: "ACPI/shell「預設開啟」是源碼 imply 預設，**不是** NVIDIA 出貨韌體的證據" (`adr-003:52`). A7 shows the shipped firmware did *not* hand over ACPI on this board. |
| A17 | Whether `SOC_T23X` satisfies the `SOC_GENERAL` gate on `TEGRA_ACPI`: `orin-port.md` says open (`SocT23X.conf` 404); ADR-003 says resolved — `SocT23X.conf` has `imply SOC_GENERAL`. | `docs/orin-port.md:419-421` vs `adr-003:51,151` | VENDOR_CLAIM (ADR-003 later text) | Internal inconsistency; ADR-003 is the corrected one. |
| A18 | NVIDIA's Xavier-era UEFI readme documents an "O/S Hardware Description Selection" (DT/ACPI) menu; ACPI serial console needs `8250_tegra`. Community: Windows 11 ARM booted on AGX Orin with ACPI; Fedora maintainer: ACPI mode gives compute/PCIe/USB/network, no display. | `docs/orin-port.md:231-242` | VENDOR_CLAIM (Xavier doc; community for Orin) | No NVIDIA statement found that the **Orin Nano** UEFI exposes that toggle (`orin-port.md:417-419`; `adr-003:128`). |
| A19 | `hypervisor_init(0)` in `boards/armv8_fm/main.c` "may switch the CPU to EL2&0 for VHE" — the hook a native QHV host needs; "which is why EL2 hand-off in (1) matters". | `docs/orin-port.md:346-348` | VERIFIED ([local] source read) | Ties A6 to the QHV host's needs. |

### B. The TCU console problem — question (b)

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| B1 | Verdict: "the only debug console on the Orin Nano is the SPE-owned Tegra Combined UART, not a CPU-drivable 8250, and NVIDIA says re-purposing it is unsupported." | `docs/orin-port.md:166-168` | VENDOR_CLAIM + HYPOTHESIS (that no other console is usable) | The console is the #1 risk in ADR-003's list (`adr-003:55`). |
| B2 | Upstream DT: `aliases { serial0 = &tcu }`, `stdout-path = "serial0:115200n8"`; `tcu` is `nvidia,tegra234-tcu` over HSP **mailboxes** — no MMIO UART. | `docs/orin-port.md:259`; `adr-003:51` [b3] | VENDOR_CLAIM (upstream DT, fetched and grepped) | |
| B3 | "Not drivable by a polled callout." | `docs/orin-port.md:259` | HYPOTHESIS (repo inference) | Follows from B2 but was not tested. |
| B4 | NVIDIA staff (KevinFFF, Apr 2024): ttyTCU0 on the Orin Nano is "backed by `uartc@c280000`"; on using it as a normal UART: "we don't suggest and support for this use case"; the user's attempt gave no TX signal. | `docs/orin-port.md:259`; `adr-003:51` [b4] | VENDOR_CLAIM (vendor forum) | |
| B5 | TCU muxing runs "in the Sensor Processing Engine (SPE) for Jetson Orin". | `docs/orin-port.md:259` | VENDOR_CLAIM | |
| B6 | Other UARTs in the DT: `uarta` `0x03100000` and `uarte` `0x03140000` — `nvidia,tegra234-uart`,`nvidia,tegra20-uart` (8250-class, SPI 112 / 116), both `okay` on the devkit; `uarti` `0x031d0000` `arm,sbsa-uart` (SPI 285), `okay`, 115200. | `docs/orin-port.md:258`; `adr-003:51` | VENDOR_CLAIM (upstream DT) | These are the CPU-drivable candidates; whether any reaches a connector is B8. |
| B7 | `callout_debug_tegra.S` = "Similar to 8250 uart with 32-bit registers" (2015); `hw_serpl011` / `acpi_spcr_parse` handle SBSA/PL011. | `docs/orin-port.md:258,343-345` | VERIFIED ([local] source read) | SPCR parsing on aarch64 is **PL011/SBSA interface types only** — no 8250/Tegra case (`orin-port.md:344-345`). |
| B8 | Whether a CPU-drivable 8250 UART is on the Orin Nano 40-pin header; whether `uartc@c280000` can be taken over from the SPE ("backed by uartc@c280000" and "TCU muxing runs in the SPE" details "未在抓到的討論串中看到，未驗證"). | `adr-003:52,134`; `docs/orin-port.md:427-428` | UNKNOWN | Named by the repo as open. |
| B9 | ADR-003 gate (2): put the session's UEFI PE on the ESP as `BOOTAA64.efi`; "any serial/TCU output" counts as pass — "但 TCU 輸出仍靠 L4T 韌體側". | `adr-003:58` | HYPOTHESIS (proposed test, not run) | |
| B10 | ADR-003 §4: "工程量與 console 問題讓它成為「數週的 BSP porting 作品集項目」，不是「幾天內拿到數字」". | `adr-003:97` | HYPOTHESIS (effort assessment) | |

### C. SDP-shipped pieces for UEFI / Tegra — question (c)

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| C1 | The 8.0 docs say **no**: `mkifs` page lists `uefi.boot` under x86_64 only; the "How to boot in UEFI mode" KB is x86_64 (SDP 7.x); the building guide says "The BIOS or UEFI (x86) or the ROM monitor (ARM)"; `startup-*` options page has no UEFI/ACPI option for AArch64. | `docs/orin-port.md:307-315`; `adr-003:51,132` [b6] | VENDOR_CLAIM | |
| C2 | The install says otherwise: `target/qnx/aarch64le/boot/sys/uefi.boot` exists (239 bytes: `filter="mkifsf_uefi %a %s %i"`, `vboot=0xffffff8060000000`, "The build file MUST specify load address via the [image=] attribute"). | `docs/orin-port.md:316-320`; `adr-003:51` [a10] | VERIFIED ([local]) | **H1 cross-check today:** file present, 239 bytes, contents as quoted (also `attr="?-bigendian"`, `+rsvd_vaddr`, `len=0x200`, `pagesizes=4k`). Path (redacted): `C:/Users/<user>/qnx800/target/qnx/aarch64le/boot/sys/uefi.boot`. |
| C3 | `mkifsf_uefi.exe` is in `host/win64/x86_64/usr/bin`. | `docs/orin-port.md:321` | VERIFIED ([local]) | **H1 cross-check:** present, 298,662 bytes. |
| C4 | `aarch64le/usr/lib/libstartup.a` (246 members) contains `efi_entry_point.o uefi.o uefi_init.o uefi_io.o is_uefi_boot.o init_raminfo_uefi.o init_raminfo_efi.o efi_tweak_cmdline.o acpi.o acpi_spcr_parse.o board_find_acpi_rsdp.o board_find_acpi_rsdp_uefi.o board_find_efi_smbios.o` plus 20+ `fdt_*.o`, `psci_*.o`, `gic_v3*.o`, `callout_debug_tegra.o`, `callout_interrupt_t18x_*.o`, `cpuid_a78ae.o`, `hw_ser8250*.o`, `hw_serpl011.o`. | `docs/orin-port.md:322-327`; `adr-003:51` | VERIFIED ([local], `ntoaarch64-ar t`) | **H1 cross-check (`ar t`, names only):** 246 members; confirmed present: `efi_entry_point.o`, `uefi.o`, `uefi_init.o`, `uefi_io.o`, `is_uefi_boot.o`, `init_raminfo_uefi.o`, `acpi_spcr_parse.o`, `board_find_acpi_rsdp.o`, `board_find_acpi_rsdp_uefi.o`, `callout_debug_tegra.o`, `callout_interrupt_t18x_msi.o`, `callout_interrupt_t18x_pcie.o`, `callout_interrupt_t18x_pcie_ic6.o`, `cpuid_a78ae.o`, `gic_v3.o`, `gic_v3_its.o`, `gic_v3_dcache_flush_for_its.o`, `callout_interrupt_gic_v3.o`, `callout_sendipi_gic_v3.o`, `fdt_psci_configure.o`, `psci_call.o`, `psci_cpu_id.o`, `psci_smp.o`, `callout_reboot_psci.o`, `hw_ser8250.o`, `hw_ser8250_32b.o`, `hw_ser8250_pci.o`, `hw_serpl011.o`. |
| C5 | `cpuid_a78ae.c`: MIDR `0x4100D420`, "Cortex-A78ae" (2023). | `docs/orin-port.md:254,296`; `adr-003:51` | VERIFIED ([local]) | Board MIDR `0x410fd421` (A9) — same part number. |
| C6 | SDP ships exactly **two** aarch64 startup binaries: `startup-qemu-virt` and `startup-armv8_fm`. | `docs/findings.md:359-362` | VERIFIED | **H1 cross-check:** `boot/sys/` lists exactly those two. |
| C7 | The hypervisor-guest BSP zip `BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip` (452 files) ships `src/hardware/startup/lib/` with **Apache-2.0** headers (BlackBerry 2022/2023; older files under the QNXLicenseC Apache-2.0 header), public headers `hw/uefi.h`, `hw/acpi.h`, `aarch64/gic_v3.h`, `arm/psci.h`, `startup.h`, and one board `boards/armv8_fm/` (ARM FVP; its `main.c` under the older "written license" QNX header). **No `qemu-virt`, no Tegra board.** | `docs/orin-port.md:328-335`; `docs/findings.md:360-362,415-421`; `adr-003:51` [b5] | VERIFIED ([local]) | **H1 cross-check:** the zip is present under `C:/Users/<user>/qnx800/bsp/` (with its x86 sibling). Members not re-listed by H1. |
| C8 | How the UEFI path works, from source: `efi_entry_point(ImageHandle, SystemTable)` takes LoadOptions as the command line, `GetMemoryMap`, `ExitBootServices`, then `cstart()`; alternatively `is_uefi_boot()` validates `boot_regs[0..1]` as ImageHandle/EFI_SYSTEM_TABLE; `uefi_init()` keeps Boot Services alive until `uefi_exit_init()`; `init_raminfo_uefi()` builds the RAM map from the EFI memory map; `board_find_acpi_rsdp_uefi()` finds the RSDP via the EFI configuration table; `acpi_spcr_parse()` picks the debug device from SPCR; `_start.S` only branches to `cstart`, preserving x0-x3 into `boot_regs[]`. | `docs/orin-port.md:336-348` | VERIFIED ([local] source read) | |
| C9 | Toolchain check: a minimal buildfile `[image=0x80000000] [virtual=aarch64le,uefi]` with `startup-armv8_fm` + `procnto-smp-instr` built with SDP 8.0.4 `mkifs` into a 1.77 MB file beginning `MZ`, `e_lfanew = 0x80`, `PE`, machine `0xAA64` — an AArch64 PE32+ despite the x86_64-only docs table. | `docs/orin-port.md:349-355`; `adr-003:51` [b6] | VERIFIED ([local] build) | |
| C10 | **Not verified:** that the PE entry point reaches `efi_entry_point` — `armv8_fm/main.c` never calls `is_uefi_boot()` and treats x0 as an FDT pointer; nothing was booted. | `docs/orin-port.md:355-357,431-433`; `adr-003:52,137` | UNKNOWN / HYPOTHESIS | Repo's own boundary. |
| C11 | Tegra lineage in the public startup library — `callout_debug_tegra.S` (2015), `callout_interrupt_t18x_*.S`, `cpuid_a78ae.c` (2023) — "is evidence of the T18x/Orin BSP heritage, not of a Jetson port". | `docs/orin-port.md:294-297` | VERIFIED ([local]) + HYPOTHESIS (interpretation) | |
| C12 | `callout_interrupt_t18x_{pcie,pcie_ic6,msi}.S` are **T18x** (Parker) callouts — fit for Tegra234 PCIe/MSI unverified. | `docs/orin-port.md:261,428-429`; `adr-003:52,135` | UNKNOWN | |
| C13 | Software Center catalog (cache is 8.0.4-generation) has a "QSC - Partner - NVIDIA Customers" folder with Orin driver packages (`com.qnx.qnx800.target.pci.hw.nvidia` T19x/T23x etc.) but **no NVIDIA BSP / startup**; `com.qnx.qnx800.host.common.fvsp.image_builder` ("build QEMU and Graviton images", FVSP Early Access, experimental) is *unavailable* to this account. | `adr-003:40,51` [a16, a17] | VERIFIED ([local] metadata cache) | Cache path (redacted): `C:/Users/<user>/.qnx/swupdate/cache/metadata/.packages/metadata/…`. H1 did not re-read the cache. |
| C14 | The hypervisor host (`qvm`, EL2 `procnto`) is prebuilt and board-agnostic, so "the missing piece is exactly a board startup plus storage/network drivers — weeks of BSP work with no vendor support". | `docs/orin-port.md:183-187`; `adr-003:54` | HYPOTHESIS (effort/scope assessment) | |
| C15 | Storage: `mmc@3460000` `nvidia,tegra234-sdhci` (SPI 65) — "no QNX driver for it known in the Everywhere install (not checked)"; PCIe C4 `pcie@14160000` (M.2 Key-M x4), C7 `pcie@141e0000`, C1 `pcie@14100000` (Key-E), C8 `pcie@140a0000` (Ethernet). | `docs/orin-port.md:260-261`; `adr-003:52` | UNKNOWN (driver) / VENDOR_CLAIM (DT) | |
| C16 | GICv3: GICD `0x0f400000` (64 KiB), GICR `0x0f440000` (2 MiB, one region), maintenance PPI 9, **no ITS node upstream**; generic timer PPIs 13/14/11/10 `always-on`; Tegra TKE `0x02080000`; PSCI `arm,psci-1.0`, `method = "smc"`. | `docs/orin-port.md:255-257`; `adr-003:51` | VENDOR_CLAIM (upstream DT) | `armv8_fm/main.c` reads `cntfrq_el0` for `timer_freq` ([local]). |
| C17 | "the NISV writeback-store issue above is irrelevant natively (no KVM trap)". | `docs/orin-port.md:255` | HYPOTHESIS (repo inference) | Architecturally sound; not demonstrated. |
| C18 | AWS corroboration: Graviton instances boot UEFI by default, so the QNX OS 8.0 AMI "must enter via UEFI", matching the `efi_entry_point`/ACPI objects; whether it then uses ACPI or FDT is unknown. | `docs/orin-port.md:358-364`; `adr-003:28,116` | HYPOTHESIS (vendor + inference) | |
| C19 | The BSP's own flag set already carries `-fno-store-merging`; `gic_v3.c` rebuilt unmodified with the SDP Windows toolchain (`qcc -Vgcc_ntoaarch64`, gcc 12.2.0) reproduces `str w3,[x0],#4` at GICD+0x420; `-fno-auto-inc-dec` removes all four writeback MMIO stores in that file. | `docs/findings.md:352-465` (esp. 371-411); `docs/orin-port.md:145` | VERIFIED (compile) / HYPOTHESIS (boot effect) | Relevant to a native port only as proof that the startup library **source builds** with the shipped toolchain. |

### D. Licence stance and the owner decision — question (d)

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| D1 | Governing document for Everywhere users: licence matrix -> `nc_qdl` -> **"QNX Development License Agreement (Non-Commercial License)", v7, 2025-12-10**. The older NCEULA v.019 (2018) is superseded but "states the intent plainly": non-commercial developers may use the Software for "extending hardware or peripheral support…" (4.2(a)). | `docs/orin-port.md:368-377`; `adr-003:51,60` [b12] | VENDOR_CLAIM (licence text as read by the research agent) | |
| D2 | **v7 4.1 clause (iii)** grants the right to "access, use, link and compile the Software … on Developer Systems solely in order to develop, evaluate, research, experiment with, test, debug, profile … Non-Commercial Target System(s), which includes rights to modify the Software supplied as Source Code"; "Non-Commercial Target System(s)" has **no hardware list, no supported-board restriction**; custom code is "Experimental Software", as-is. | `docs/orin-port.md:379-391`; `adr-003:51` ("授權 4.1(iii) … 無硬體清單限制") | VENDOR_CLAIM | The repo's basis for "licence allows the port". Note: `orin-port.md` calls it "v7 grant, clause (iii)"; ADR-003 calls it "4.1(iii)". |
| D3 | **v7 4.6 restrictions:** (c) no reverse engineering, decompiling, disassembly "except and only to the extent … prohibited by applicable law"; (d) do not "modify any Software delivered in binary code"; (g) no distribution to third parties; (b) only on systems owned/controlled by the Developer; **(i)** do not "release, publish, and/or otherwise make available to any third party the results of any performance or functional evaluation of the Software" without BlackBerry's prior written approval. | `docs/orin-port.md:392-400`; `adr-003:55,106` | VENDOR_CLAIM | |
| D4 | Two flags "for the Architect / Cyber / Docs agents, not decided here": the 2026-07-28 root cause **disassembled the shipped `startup-qemu-virt`** (4.6(c)); the 2026-09-08 move to the Apache-2.0 `gic_v3.c` source "is the cleaner footing"; **4.6(i) reads on every published latency and boot-time number in this repo**. | `docs/orin-port.md:409-413`; `adr-003:55` (risk 3), `adr-003:106` | HYPOTHESIS (explicitly "研究員的法律解讀，非 BlackBerry 聲明") | ADR-003 risk (4): Apache-headed source inside a QDL-licensed zip — "何者為準未定" (which governs is undetermined) -> UNKNOWN. |
| D5 | CLAUDE.md next action 4: "Decide ADR-003 … Status: Proposed … Two licence clauses flagged there (NC QDL v7 4.6(c) disassembly, 4.6(i) publishing evaluation results) need an owner decision before more numbers are published." | `CLAUDE.md:376-383` | VERIFIED (repo state) | |
| D6 | Repo practice since 2026-07-28: objdump windows of the SDP-shipped startup are **withheld** / replaced by fact summaries before commit; "QDL v7 §4.6(c) remains an open owner decision". | `docs/findings.md:243-246`; `results/gicv3-nisv-debug/20260909T101030Z/summary.md:180,247`; `…/raw/static-ifs-probe.txt:39`; commit `e161636` message | VERIFIED (repo state) | |
| D7 | Interview narrative's stated reason for not patching the binary: "NCEULA covers use, not redistribution, and modifying a vendor's proprietary board-bring-up binary … is a line worth not crossing casually". | `docs/interview-narrative.md:217-224` | VERIFIED (repo stance; cites the older NCEULA, not v7 4.6(d)) | The same document narrates having "disassembled the QNX board bring-up code at that PC" (`interview-narrative.md:165-167`) — the 4.6(c) exposure D4 flags. |
| D8 | Redistribution policy: "Scripts + screenshots + boot logs only. No QNX binaries." | `docs/bsp-selection.md:537-545,569-573` | VERIFIED (repo decision) | |
| D9 | QNX blog: Hypervisor 8.0 is included in the free QNX Everywhere licence; the licence matrix lists AWS as an Authorized Cloud Service Provider and NC/Academic as applicable. The Everywhere EULA text itself was **not** found — the entitlement claim rests on blog / press / README. | `adr-003:39,149`; `docs/bsp-selection.md:340-345` | VENDOR_CLAIM (entitlement) / UNKNOWN (EULA text) | |
| D10 | Precedent: BlackBerry-owned `qnx/bsp_raspberrypi-bcm2711-rpi4` is a source-only SDP 8.0 BSP, "Experimental Software (SQML 1)"; the Everywhere licensing page permits hobbyist/maker builds "provided you do not make a commercial product". | `docs/orin-port.md:401-408` | VENDOR_CLAIM | |
| D11 | **Owner decision (2026-09-09): ADR-003 -> option (B), native Orin Nano port; proceed; consult the supervising professor before publishing any evaluation results (4.6(i)); keep 4.6(c) clean — "source and docs only, never disassembly of a QNX-shipped binary".** Not in the committed history at `e161636` (repo-wide grep for "professor": no hits; `adr-003:3` read "Proposed — decision pending"; `CLAUDE.md:381-383` "need an owner decision"). **It is recorded in uncommitted working-tree edits made by a concurrent agent during H1's run** (`git diff` seen at the end of H1): ADR-003 status line -> "Accepted (2026-09-09) — 選項 (B)" with the professor clause and "Accepted 指的是路線，不是可行性"; CLAUDE.md next action 4 rewritten (Phase 3b, plan doc, Pi 4B route kept as the cheaper alternative); findings.md 2026-09-09 entry gains an "Owner decisions" paragraph (4 items, incl. a git-history rewrite handed to the owner; `backup/pre-history-rewrite-2026-09-09` and `…-readme` branches exist). | working tree at end of H1: `git diff CLAUDE.md docs/adr-003-hardware-timed-qhv.md docs/findings.md` (uncommitted); `git branch` | VERIFIED (working tree, uncommitted) — was UNKNOWN at `e161636` | The referenced `docs/orin-native-port-plan.md` **does not exist yet** (not tracked, not untracked, not ignored) — a dangling link until another agent writes it. |

### E. NVIDIA's position and prior art

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| E1 | NVIDIA staff, three times: 2020-07-27 (Xavier NX) "no plan to do"; 2024-02-29 (AGX Orin) "We don't support QNX on Jetson. It's only available on DRIVE platforms"; 2025-07-17 "There is no plan to support QNX OS on Jetson". | `docs/orin-port.md:266-276`; `adr-003:51` [b8-b10] | VENDOR_CLAIM (vendor forum, staff-authored) | |
| E2 | Third-party hypervisors on Jetson are "not supported on Jetpack release. You may see if there is a method to enable it" — unsupported, not hardware-locked (DaneLLL). | `docs/orin-port.md:277-280` | VENDOR_CLAIM | Date discrepancy: `orin-port.md:279` says 2025-10-30; ADR-003 §5 says it should be 2025-10-20, thread 348348 (`adr-003:151`). |
| E3 | DRIVE OS QNX is obtained via NVONLINE (SDP 7.1 + QOS 2.2.2 EA for DRIVE OS 6.0.6); the DRIVE AGX SDK Developer Program is invitation-only. | `docs/orin-port.md:281-293`; `adr-003:51` [b11]; `CLAUDE.md` (Decision 2026-07-29 paragraph) | VENDOR_CLAIM | |
| E4 | "**QNX on any Jetson generation:** none found" (official or community). | `docs/orin-port.md:294,422`; `adr-003:130` | UNKNOWN | |
| E5 | Non-Linux OSes on Orin via UEFI: Windows 11 ARM on AGX Orin (ACPI, 2023; Hyper-V works, no GPU); Fedora / RHEL 9.3 on AGX Orin; seL4 lists only Jetson TK1; the only Xen Jetson attempt is Nano (2020, no dom0 console); a 2023 FreeBSD ACPI-mode attempt "did not go well". | `docs/orin-port.md:236-242,298-303`; `adr-003:131` | VENDOR_CLAIM (community) | |

### F. The repo's overall verdict on the native port (ADR-003 §2(B), §3, §4)

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| F1 | Verdict: "technically plausible but is a from-scratch BSP bring-up with no vendor path". | `docs/orin-port.md:161-163` | HYPOTHESIS (assessment) | |
| F2 | Established chain (ADR-003 "已確立" row): boot chain + arbitrary EFI app as loader; TF-A -> EL2; Tegra234 register map public; SDP ships `uefi.boot`, `mkifsf_uefi.exe`, the UEFI/ACPI/Tegra/A78AE objects; Apache-2.0 startup source with `armv8_fm` only; `mkifs` emits an AArch64 PE32+; edk2-nvidia general build implies ACPI+DT; NVIDIA said no three times; DRIVE program invitation-only; catalog has NVIDIA driver packages but no BSP; licence 4.1(iii) allows source modification with no hardware list. | `adr-003:51` | mixed — see A/C/D/E rows | |
| F3 | Unknowns row (ADR-003 "未知"): board dmesg not retained (stale, see A13); ACPI/shell defaults are source-only evidence; PE entry reaching `efi_entry_point`; 40-pin 8250 UART; t18x callouts on T234; no known QNX driver for tegra234-sdhci / PCIe; TRM login-gated. | `adr-003:52` | UNKNOWN | |
| F4 | Cost: hardware $0 (owned); time is the main cost. Effort: "數週的無支援 BSP 工作：新 board directory、debug callout、timer/GIC/PSCI 初始化、storage driver；最終為 Experimental Software，無 vendor 路徑". | `adr-003:53-54` | HYPOTHESIS | |
| F5 | Risks: (1) console = SPE-owned TCU; (2) three NVIDIA no-QNX statements; (3) 4.6(c) / 4.6(i) exposure; (4) Apache-vs-QDL precedence undetermined. | `adr-003:55` | mixed (see B, E, D) | |
| F6 | What it could measure if successful: "A78AE 上真 VHE (el2-host) 的 QHV 數字，與 TCG leg 拓撲一致；同時是最強的 BSP-porting 敘事". What it cannot: anything short-term; not a vendor-supported configuration. | `adr-003:56-57` | HYPOTHESIS | |
| F7 | First cheap gates (zero cost, ~1 h): (1) capture and store the board's dmesg [done — A1-A9]; (2) put the session's UEFI PE on the ESP as `BOOTAA64.efi` and see whether UEFI loads it; (3) reproduce the PAUTH abort under `-cpu cortex-a72` / `-cpu max`. | `adr-003:58` | proposed tests, not run (except gate 1) | |
| F8 | Ranking (§3): Orin Nano native is **5th of 5** on accessibility — "理論上最好（A78AE + VHE，與 TCG leg 同拓撲、同 host），實際上是數週無支援 BSP 工作". | `adr-003:84` | HYPOTHESIS | |
| F9 | Recommendation (§4): "Orin native 保留為敘事與長期項目，不作為量測路徑"; every link passes (UEFI EL2 hand-off, AArch64 UEFI startup source, mkifs PE, licence allows source modification) "但工程量與 console 問題讓它成為「數週的 BSP porting 作品集項目」". | `adr-003:92,97` | HYPOTHESIS (recommendation; ADR Status Proposed) | Superseded in intent by the owner decision D11 if/when it is recorded. |
| F10 | Current hypervisor-on-Orin state: the QHV host **and** its guest boot on the Orin Nano under **TCG** with a from-source QEMU v11.1.0 (n=5 median 62,058 ms launch->guest banner); the distro 6.2.0 hang is a verified QEMU EL2 virtual-timer wiring defect (reverted-wiring build reproduces it). | `docs/findings.md:11-251` (esp. 78-84, 99-118, 124-137); `docs/orin-port.md:146`; `scripts/orin/patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch:1-20` | VERIFIED (logs in `logs/sample-boot/orin-qhv-tcg-q111-*`) | This is the topology (VHE el2-host QHV + `armv8_fm` guest) a native port would run on real EL2. |
| F11 | The QHV leg is TCG on both hosts because "QHV needs EL2 for its guest, i.e. nested virtualisation, which ARM KVM does not provide on A78AE" — "a hard architectural requirement, not the GICv3 blockage". | `docs/digital-twin-design.md:45,273`; `CLAUDE.md:333`; `scripts/orin/launch-qhv-on-orin-tcg.sh:25-33`; `docs/findings.md:290-294` | VENDOR_CLAIM-backed inference: kernel docs say nested KVM "Requires at least ARMv8.4 hardware (with FEAT_NV2)" (`docs/bsp-selection.md:497-503`); A78AE is ARMv8.2-A (`bsp-selection.md:167`) | A native port removes this constraint: QHV would *be* the EL2 host. `skills/tegra-virtualization/README.md:16-18` still calls nested virt "fragile" rather than absent — stale wording. |
| F12 | `/dev/kvm` is present and initialises (VHE, GICv3) on this board; a bare vGIC smoke test under KVM ran clean; the QNX IFS under `-enable-kvm` hangs after `FOUND GICv3 ITS` (root-caused NISV); `gic-version=2` unavailable. | `CLAUDE.md:46-49`; `docs/orin-port.md:90,140`; `docs/findings.md:465-492` | VERIFIED (KVM init) / VERIFIED (hang, one logged ftrace) | Native-port relevance: only that the EL2/VHE machinery is live on this silicon (A6). |
| F13 | Cross-vendor: identical hang on AWS `a1.metal` (Graviton1, Cortex-A72), one run; the `a1.metal` log header's instance id was redacted 2026-09-09 (remains in git history). | `docs/findings.md:465-492,246-249`; `logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log:1-4` | VERIFIED (single run) | |
| F14 | The board dropped off the network mid-scp on 2026-09-08 and needed a power cycle; cause unknown (volatile journald); suspected supply brown-out; QEMU build run at `-j4` for this reason. | `docs/orin-port.md:147`; `scripts/orin/build-qemu-on-orin.sh:37-44`; `docs/findings.md:21-24` | HYPOTHESIS (cause) / VERIFIED (event) | Operational risk for any long native-port session on the shared board. |
| F15 | 2026-07-29 decision: a hardware-timed number on Orin is "deferred, not abandoned" — needs DRIVE AGX Orin hardware or paid `c7g.metal` work. | `CLAUDE.md` Phase-status "Decision (2026-07-29)" paragraph | VERIFIED (repo decision) | Predates ADR-003 and the native-port research. |

### G. Skills notes (study artefacts, not certification evidence)

| # | Claim | Source | Class | Notes |
|---|---|---|---|---|
| G1 | `skills/bsp-porting`: four-stage workflow (discovery -> bring-up -> drivers -> validation); scope is the **aarch64 QEMU virt** target; **out of scope: real-silicon bring-up (no JTAG, no logic analyzer access here)** and BL1/BL2/BL31 TF-A customisation. | `skills/bsp-porting/README.md:15-30` | VERIFIED (repo text) | The skill explicitly excludes what a native port is. Its index points to `paradigm.md` (`README.md:33`) which **does not exist** in `skills/bsp-porting/` — dangling reference. |
| G2 | `skills/jetson-platform`: Jetson Orin Nano != DRIVE Orin; shared A78AE CCPLEX validates core-level portability only — not Tegra automotive peripherals, not the DRIVE OS NVIDIA Hypervisor stack, not FSI lockstep / R52 safety cluster, not the SecureBoot fuse chain; "no portfolio project running on consumer Jetson hardware can claim parity". | `skills/jetson-platform/README.md:15-18,35-48` | VERIFIED (repo framing) | Line 25 references `skills/qualcomm-cockpit/` which does not exist — dangling. Nothing about UEFI/EL2/TCU. |
| G3 | `skills/tegra-virtualization`: A78AE virtualisation extensions (VHE, GIC virt, Stage-2) "enable KVM on the project's HW twin"; KVM-on-L4T "nested virt for QHV-on-QEMU experiments" is "fragile"; "The project does not implement a hypervisor of any kind". | `skills/tegra-virtualization/README.md:14-18,40-45` | VERIFIED (repo text) | Stale relative to `digital-twin-design.md:45` (nested virt not provided) and to the QHV leg now booting (F10) — though QHV is QNX's hypervisor, not the project's. |

### H. `scripts/orin/*.sh` headers — none address a native port

| # | Script | What the header says | Source | Class |
|---|---|---|---|---|
| H1 | `bootstrap-orin-l4t.sh` | Phase 3; prepares L4T "to host the QNX guest under QEMU/KVM"; apt steps are commented-out TODOs; checks `/dev/kvm`. | `scripts/orin/bootstrap-orin-l4t.sh:3-45` | VERIFIED (text) |
| H2 | `setup-bridge-orin.sh` | Phase 3; `br0` + `tap-qnx`; no `tap-linux` because L4T is host and Compute side. | `scripts/orin/setup-bridge-orin.sh:3-16` | VERIFIED (text) |
| H3 | `launch-qnx-on-orin.sh` | Phase 3; the `-enable-kvm` variant, kept as "documented, NOT-deleted intent"; mirrors `scripts/launch-qnx-vm.sh` "almost byte-for-byte" — "same IFS, same QEMU args, different host". | `scripts/orin/launch-qnx-on-orin.sh:3-19` | VERIFIED (text) |
| H4 | `launch-qnx-on-orin-tcg.sh` | Phase 3; TCG because of the NISV hang (2026-07-28 decision); rng-device slot-order note. | `scripts/orin/launch-qnx-on-orin-tcg.sh:3-27` | VERIFIED (text) |
| H5 | `launch-qhv-on-orin-tcg.sh` | Phase 4; QHV leg is host-agnostic (only two image files cross to the host); "TCG here is a hard architectural requirement, not a workaround … Do not describe this leg as 'TCG because KVM is broken'"; no host networking; `WITH_RNG` stamps; the host prints **no banner** — three markers used. | `scripts/orin/launch-qhv-on-orin-tcg.sh:3-33,62-75,86-104` | VERIFIED (text) |
| H6 | `build-qemu-on-orin.sh` | Phase 4; builds tagged v11.1.0 into its own prefix; distro 6.2.0 left intact for every prior result; `-j4` because of the unexplained board drop; Ubuntu 22.04 needs `python3-venv` + `python3-tomli`. | `scripts/orin/build-qemu-on-orin.sh:3-44,55-80` | VERIFIED (text) |
| H7 | `patches/qemu-v11.1.0-unwire-ns-el2-virt-timer-irq.patch` | Experiment patch; leaves the NS EL2 virtual-timer output unconnected to reproduce 6.2's hang on 11.1.0; `-machine virt-8.2` is *not* a substitute. | `scripts/orin/patches/…patch:1-20` | VERIFIED (text) |

All seven are QEMU-based; the repo has **no script, buildfile, board directory, or ESP recipe** for a native boot.

### I. `docs/interview-narrative.md` GICv3 section (relevance to the native port)

| # | Claim | Source | Class |
|---|---|---|---|
| I1 | Narrative of the KVM/NISV root cause: ftrace `KVM_EXIT_ARM_NISV`, "I disassembled the QNX board bring-up code at that PC", post-indexed store on a GICv3 distributor priority register, TCG control boot. | `docs/interview-narrative.md:155-171` | VERIFIED (narrative of logged work; the numeric PC was never written down — `findings.md:233-236`) |
| I2 | Three "real paths": file with QNX/BlackBerry; contribute decode-and-emulate to QEMU's KVM backend; `c7g.metal` cross-check. **A native port is not listed as a path** in this section. | `docs/interview-narrative.md:175-190` | VERIFIED (text) |
| I3 | `a1.metal` cross-vendor reproduction paragraph. | `docs/interview-narrative.md:195-213` | VERIFIED (single run) |
| I4 | Licence-scope rationale for not patching the binary (see D7). | `docs/interview-narrative.md:217-224` | VERIFIED (stance) |

---

## 2. Every open unknown the repo names (native-port relevant)

Numbered for reference by later tasks; source in brackets.

**Boot / firmware**
1. Whether the shipped Orin **Nano** UEFI exposes an ACPI / "O/S Hardware Description Selection" toggle, or ships ACPI + UEFI shell enabled at all — evidence is only the source `imply` defaults and AGX Orin community reports [`adr-003:52,128`; `orin-port.md:417-419`]. (A7 shows the *default* boot on this board was DT-only.)
2. Whether the `mkifsf_uefi` AArch64 image's PE entry point actually reaches `efi_entry_point` — `armv8_fm/main.c` never calls `is_uefi_boot()` [`orin-port.md:355-357,431-432`; `adr-003:52,137`].
3. Whether UEFI (L4TLauncher path / Boot Manager) will load an arbitrary `BOOTAA64.efi` that is a QNX PE — ADR-003 gate (2), not run [`adr-003:58`].
4. Whether any `armv8_fm`-derived Tegra234 startup boots at all; whether the QHV host (`qvm` + EL2 `procnto`) then runs natively [`adr-003:137`; `orin-port.md:432-433`].
5. The UEFI spec 2.10/2.11 §2.3.6 (AArch64 calling/EL conventions) text — uefi.org 403; TF-A + `booting.rst` used instead [`adr-003:136`; `orin-port.md:429-430`].
6. `grub --target=arm64-efi` is not on NVIDIA's page (page shows `--bootloader-id=Ubuntu`) — how GRUB is actually installed there is not pinned [`adr-003:138`].

**Console**
7. Whether a CPU-drivable 8250 UART (uarta/uarte) reaches the 40-pin header or any connector [`adr-003:52,134`; `orin-port.md:427`].
8. Whether `uartc@c280000` can be taken over from the SPE; the "backed by uartc@c280000" / "TCU muxing runs in the SPE" details were not seen in the fetched threads [`adr-003:134`].
9. Whether the SBSA `uarti@031d0000` is physically usable as a console (the DT marks it `okay`; nothing in the repo says where it goes) — implicit in B6/B7; not named as an unknown by the repo, but no fact covers it.

**Peripherals / drivers**
10. Whether `callout_interrupt_t18x_{pcie,pcie_ic6,msi}` (Parker) fit Tegra234 PCIe/MSI [`adr-003:52,135`; `orin-port.md:428-429`].
11. No known QNX driver for `tegra234-sdhci`; "not checked" in the Everywhere install [`orin-port.md:260`; `adr-003:52`].
12. No known QNX driver for the Tegra234 PCIe controllers (NVMe path) [`adr-003:52`].
13. Tegra234 TRM content — login-gated (HTTP 403) [`adr-003:52,133`; `orin-port.md:427`].

**Toolchain / packages**
14. Software Center cache is 8.0.4-generation: whether the Hypervisor 8.0.5 group is open to Everywhere accounts, whether any Graviton/AWS packages appear, whether `fvsp.image_builder` is still unavailable [`adr-003:103`].
15. A documented AArch64 UEFI startup in 8.0 (docs say x86_64-only; install contradicts) [`adr-003:132`; `orin-port.md:424-425`].
16. Only `gic_v3.c` was audited for writeback MMIO stores; no whole-`libstartup.a` sweep [`findings.md:407-409`] — KVM-relevant, not native-relevant, but named.

**Guest / PAUTH**
17. The PAUTH contradiction: the project's guest aborts `PE does not support PAUTH feature` under QEMU `-cpu cortex-a57`, while QNX's Pi 4 recipe boots the `startup-armv8_fm` sample guest on Cortex-A72 (also no PAUTH) — same image or not is unverified [`adr-003:66,101`; `bsp-selection.md:315-321`; `logs/sample-boot/orin-qhv-tcg-q62-a57-control.log:49`].

**Licence**
18. NC QDL v7 **4.6(i)** exposure of every published timing number, and **4.6(c)** exposure of the 2026-07-28 disassembly — "Architect/Docs/Cyber 決定，非研究可解" [`adr-003:55,106`; `orin-port.md:409-413`; `CLAUDE.md:381-383`].
19. Which licence governs the Apache-2.0-headed startup source delivered inside the QDL-licensed BSP zip [`adr-003:55` risk (4)].
20. The QNX Everywhere EULA text itself (entitlement to Hypervisor 8.0 rests on blog / press / README) [`adr-003:149`].
21. **The owner decision of 2026-09-09 is recorded only in uncommitted working-tree edits** (ADR-003 status line, CLAUDE.md next action 4, findings.md "Owner decisions" paragraph — see D11); it is not in any commit, and the plan document those edits link to (`docs/orin-native-port-plan.md`) does not exist yet [`git diff` at end of H1; `adr-003:3` at `e161636`]. Whether "consult the supervising professor" has happened, and what the professor's answer is, is not recorded anywhere.

**Prior art**
22. Any QNX port to any Jetson generation (TX1/TX2/Xavier/Orin), official or community [`adr-003:130`; `orin-port.md:294,422`].
23. Any usable seL4 / Xen / Zephyr / FreeBSD port to Orin [`adr-003:131`; `orin-port.md:422-423`].

**Board operations**
24. Cause of the 2026-09-08 network drop / forced power cycle (suspected supply brown-out; journald volatile) [`orin-port.md:147`; `build-qemu-on-orin.sh:37-44`].

---

## 3. Internal inconsistencies H1 noticed (for the Docs agent; not fixed here)

| # | Where | What |
|---|---|---|
| X1 | `adr-003:52,102,129` vs `adr-003:8-9` + evidence file | Three sentences still say the board's EL2 dmesg was never retained; the same commit adds and links it. |
| X2 | `orin-port.md:419-421` vs `adr-003:151` | `SocT23X.conf` gate "open" vs "resolved (`imply SOC_GENERAL`)". |
| X3 | `orin-port.md:279` vs `adr-003:151` | DaneLLL quote dated 2025-10-30 vs "should be 2025-10-20, thread 348348". |
| X4 | `orin-port.md:202` vs `adr-003:138` | `grub-install --target=arm64-efi` attributed to the NVIDIA page vs "not on the page". |
| X5 | `skills/tegra-virtualization/README.md:16-18` vs `digital-twin-design.md:45`, `CLAUDE.md:333` | Nested virt "fragile" vs "not provided on A78AE". |
| X6 | `skills/bsp-porting/README.md:33`; `skills/jetson-platform/README.md:25` | Dangling links to `paradigm.md` and `skills/qualcomm-cockpit/` (neither exists). |
| X7 | `interview-narrative.md:217-224` | Cites "NCEULA" for the no-binary-modification stance; the governing text per the 2026-09-09 research is NC QDL v7 4.6(c)/(d). |

---

## 4. H1 cross-checks performed today (listing-only; no disassembly, no board access)

- `C:/Users/<user>/qnx800/target/qnx/aarch64le/boot/sys/uefi.boot` — present, 239 bytes; text read (build-file attributes only).
- `C:/Users/<user>/qnx800/host/win64/x86_64/usr/bin/mkifsf_uefi.exe` — present, 298,662 bytes.
- `C:/Users/<user>/qnx800/target/qnx/aarch64le/usr/lib/libstartup.a` — 2,661,074 bytes; `ntoaarch64-ar t` -> 246 members; the UEFI/ACPI/PSCI/GICv3/Tegra/A78AE members listed in C4 are all present by name.
- `C:/Users/<user>/qnx800/target/qnx/aarch64le/boot/sys/` — exactly two `startup-*` binaries: `startup-armv8_fm`, `startup-qemu-virt`.
- `C:/Users/<user>/qnx800/bsp/` — `BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip` and its x86 sibling present.
- Repo-wide grep for "professor", "owner decision", "proceed with the port" at the start of H1: no hits outside `findings.md:246` ("open owner decision" re 4.6(c)).
- `git status` clean at `e161636` when H1 began; the three scripts shown modified in the session-start snapshot were already committed. **At the end of H1** the working tree showed uncommitted edits (not by H1) to `CLAUDE.md`, `docs/adr-003-hardware-timed-qhv.md`, `docs/findings.md` recording the owner decision (D11); `docs/orin-native-port-plan.md` referenced by those edits is absent; branches `backup/pre-history-rewrite-2026-09-09` and `backup/pre-history-rewrite-2026-09-09-readme` exist.
- H1 wrote only `results/orin-native-port/20260909T1100Z/harvest-repo.md`; no tracked file was touched by H1.
