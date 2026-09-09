# R1 — External research: booting a non-Linux payload through NVIDIA UEFI on the Jetson Orin Nano

Date: 2026-09-09. Task R1 of the `orin-native-port` study. Read-only; no board
access was used by this task — live-board lines are quoted from the sibling H3
captures in `raw/` (already redacted: `<user>`, `<orin-ip>`, `<orin-key>`).

Evidence classes, used per line:

| Tag | Meaning |
|---|---|
| **VERIFIED** | seen this session: a source file at a URL/tag, a command output, or a live-board capture in `raw/` |
| **VENDOR_CLAIM** | an NVIDIA / TF-A / edk2 document or NVIDIA-staff forum post says so |
| **COMMUNITY** | a non-vendor forum/blog says so |
| **HYPOTHESIS** | reasoned from the above, not tested |
| **UNKNOWN** | looked for, not found, or the page could not be fetched |

Quotes from external pages are kept under 15 words. Nothing QNX-shipped was
disassembled or dumped for this task.

---

## 0. Baseline: what this Orin Nano actually runs (VERIFIED, `raw/`)

| Fact | Source |
|---|---|
| Firmware is EDK II, version string `36.4.4-gcid-41062509`, build date 06/16/2025; product `NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super` | `raw/orin-uefi-dmesg.txt:107,118` (`/sys/class/dmi/id`) |
| Kernel sees `efi: EFI v2.70 by EDK II`; config tables printed: RTPROP, TPMFinalLog, SMBIOS, SMBIOS 3.0, MEMATTR, ESRT, TPMEventLog, RNG, MEMRESERVE — **no `ACPI=`** entry | `raw/orin-firmware-el.txt` `[b]` |
| `CPU: All CPU(s) started at EL2`; `kvm [1]: VHE mode initialized successfully`; `psci: PSCIv1.1 detected in firmware`, `SMC Calling Convention v1.2` | `raw/orin-firmware-el.txt`; also `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt:27-42` |
| ESP = `mmcblk0p10` (vfat, 64 MB, GPT type ESP `c12a7328-…`), mounted `/boot/efi`; contains `EFI/BOOT/BOOTAA64.efi` (110,592 B) and `EFI/UpdateCapsule/` | `raw/orin-bootconfig.txt:196-254` |
| `efibootmgr -v`: `Boot0000* Enter Setup`, `Boot0001* UEFI SD Device` (= BootCurrent), `Boot0006* BootManagerMenuApp`, `Boot0007* UEFI Shell` (both FV-embedded, FvVol `49a79a15-8f69-4be7-a30c-a172f44abce7`), plus NVMe/PXE/HTTP entries | `raw/orin-bootconfig.txt:266-282`, `raw/orin-boot-config.txt:339-351` |
| `/boot/extlinux/extlinux.conf`: `LINUX /boot/Image`, `INITRD /boot/initrd`, `APPEND ${cbootargs} … console=ttyTCU0,115200 …` | `raw/orin-bootconfig.txt:7-17` |
| `/chosen` carries `linux,uefi-system-table`, `linux,uefi-mmap-*`, `linux,uefi-secure-boot`, `stdout-path = "serial0:115200n8"`, `serial0 = /serial` (the TCU node) | `raw/orin-devicetree.txt:22-58` |
| Console: `/sys/class/tty/console/active` = `ttyTCU0 tty0`; `ttyTCU0` ↔ `/serial` compatible `nvidia,tegra234-tcu`; `ttyTHS1` ↔ `serial@3100000` (`nvidia,tegra194-hsuart`); `ttyTHS2` ↔ `serial@3140000`; `ttyAMA0` ↔ `serial@31d0000` (`arm,sbsa-uart`) | `raw/orin-ttys.txt` |

Note the FvVol GUID `49a79a15-8f69-4be7-a30c-a172f44abce7` in the boot entries is
exactly `CONFIG_PLATFORM_GUID` in edk2-nvidia `t23x_general.defconfig` (§2.3) —
a direct tie between the shipped firmware and the public source tree. VERIFIED.

The edk2-nvidia repository carries tags `r36.4.0`, `r36.4.3`, `r36.4.4`,
`r36.4.5`, `r36.5`, `r36.5.1` (no `r36.4.7`); the firmware on the board reports
`36.4.4`, so **`r36.4.4` is the matching source generation** (VERIFIED via
`https://api.github.com/repos/NVIDIA/edk2-nvidia/tags`). Where a file was read
at `main` and also checked at `r36.4.3` this is stated.

---

## 1. Ways to replace or extend the OS loader

### 1.1 Replace `BOOTAA64.efi` on the ESP (vendor-documented)

- **VENDOR_CLAIM** — R36.4.4 Developer Guide "UEFI Adaptation": L4TLauncher is
  "the default OS Loader for the UEFI"; to use GRUB, back up
  `BOOTAA64.efi` to `Backup_BOOTAA64.efi`, then
  `sudo grub-install --bootloader-id=Ubuntu --efi-directory=/boot/efi --target=arm64-efi`;
  to revert, `efibootmgr -c -d /dev/mmcblk0 -p 10 -L "L4TLauncher" -l "\EFI\BOOT\Backup_BOOTAA64.efi"`.
  https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Bootloader/UEFI.html
- **VERIFIED** — the board matches the doc's layout exactly (`-p 10` = `mmcblk0p10`,
  `/boot/efi/EFI/BOOT/BOOTAA64.efi`), §0.
- **COMMUNITY** — OE4T/meta-tegra (Feb–May 2024): GRUB "not currently
  implemented" in meta-tegra, but a user got it working by populating the ESP
  and adding a UEFI boot option from the UEFI shell; default remains
  UEFI + L4TLauncher + extlinux. https://github.com/OE4T/meta-tegra/discussions/1480

**What this means:** the vendor path installs a *third-party* AArch64 EFI
application (`grubaa64.efi`) as the default loader; nothing in the procedure is
GRUB-specific. The doc never says "any EFI application" (UNKNOWN as a vendor
statement); the source in §1.4 shows there is no filter.

### 1.2 L4TLauncher boot modes (`L4TDefaultBootMode`)

- **VENDOR_CLAIM** — UEFI variable `L4TDefaultBootMode`: `0` = Boot GRUB,
  `1` = "Boot normal kernel and DTB in filesystem" (extlinux), `2` = kernel/DTB
  from partitions, `3` = recovery kernel/DTB from partitions (same page as 1.1).
- **VERIFIED (source)** — `Silicon/NVIDIA/Application/L4TLauncher/L4TLauncher.h`
  (`main`): `GRUB_PATH L"EFI\\BOOT\\grubaa64.efi"`,
  `EXTLINUX_CONF_PATH L"boot\\extlinux\\extlinux.conf"`, and command-line
  overrides `bootmode=direct|grub|bootimg|recovery`; variables
  `BootChainFwCurrent` / `BootChainOsCurrent`; `MAX_CBOOTARG_SIZE 256`.
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Application/L4TLauncher/L4TLauncher.h
  So "Direct Boot" in the source (`NVIDIA_L4T_BOOTMODE_DIRECT`) is the
  extlinux path (mode 1 in the doc); "BOOTIMG" is the partition path.
- **VERIFIED (source)** — `L4TLauncher.c`, SPDX `BSD-2-Clause-Patent`:
  GRUB mode does `gBS->LoadImage(FALSE, ImageHandle, FullDevicePath, NULL, 0, &Handle)`
  then `gBS->StartImage(...)` on `GRUB_PATH` — a plain EFI chain-load.
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Application/L4TLauncher/L4TLauncher.c

### 1.3 The extlinux `LINUX=` line is itself an EFI-application launch (source)

**VERIFIED (source, `L4TLauncher.c` at `main`)** — in the extlinux path:

1. `LINUX=` file: read with `OpenAndReadFileToBuffer` (no decompression); then
   **unencrypted** → `gBS->LoadImage(FALSE, ImageHandle, KernelDevicePath, NULL, 0, &KernelHandle)`
   (file device path); **encrypted** → `LoadImage(TRUE, …, KernelBase, KernelSize, …)` (memory buffer).
2. `APPEND=` → `ImageInfo->LoadOptions = NewArgs; LoadOptionsSize = StrLen(NewArgs) * sizeof(CHAR16)` — **UCS-2 LoadOptions**.
3. `FDT=` → read, `FdtOpenInto(...)` into a 4× buffer, `OVERLAYS=` applied via
   `gL4TSupportProtocol->ApplyTegraDeviceTreeOverlay(...)`, then
   `gBS->InstallConfigurationTable(&gFdtTableGuid, ExpandedFdtBase)`.
4. `INITRD=` → exposed through `gEfiLoadFile2ProtocolGuid` on a
   `LINUX_EFI_INITRD_MEDIA_GUID` device path (the EFI-stub initrd protocol).
5. Watchdog 5 min, then `gBS->StartImage(KernelHandle, NULL, NULL)`.
6. **No image-type check** (no PE/`ARM64` magic test); if `LoadImage` fails the
   launcher falls through to the next mode (BOOTIMG).

**HYPOTHESIS** — therefore an arbitrary AArch64 PE32+ named in `LINUX=` is
`LoadImage`d/`StartImage`d with (a) the DTB already installed under
`gFdtTableGuid`, (b) the `APPEND` string as UCS-2 LoadOptions, (c) Boot
Services still live. That matches what QNX's `efi_entry_point` expects
(`harvest-sdp.md:67`: takes LoadOptions as the command line, snapshots the
memory map, `ExitBootServices`, `cstart`). Untested; the `LINUX=` file must be
on the rootfs partition the launcher enumerates.

### 1.4 UEFI Boot Manager, Setup, UEFI Shell

- **VENDOR_CLAIM** — ESC at "Press ESCAPE for boot options" → Boot Manager /
  Boot Maintenance Manager; the UEFI shell "is a command-line interface
  environment"; NVIDIA "strongly recommend" disabling the shell for production
  (UEFI Adaptation page, §1.1 URL).
- **VERIFIED (source)** — `PlatformBootManagerLib/PlatformBm.c` (`main`, BSD-2-Clause-Patent):
  `PlatformRegisterFvBootOption(&gUefiShellFileGuid, L"UEFI Shell", LOAD_OPTION_ACTIVE, …)`;
  ESC mapped via `Esc.ScanCode = SCAN_ESC` to `EfiBootManagerGetBootManagerMenu`;
  boot options come from stock `EfiBootManagerRefreshAllBootOption()`. The only
  launch filters found are PCI option-ROM blocks (`PciOpRomDisabled…`) and UEFI
  Secure Boot; there is no allow-list of EFI applications. A
  `PcdSingleBootApplicationGuid` / `CONFIG_SINGLE_BOOT_L4T_LAUNCHER` mode exists
  that bypasses enumeration and runs L4TLauncher from the FV.
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Library/PlatformBootManagerLib/PlatformBm.c
- **VERIFIED (board)** — `Boot0007* UEFI Shell` and `Boot0006* BootManagerMenuApp`
  are present in this board's `efibootmgr -v` (§0): the shipped `36.4.4` build
  is *not* the single-boot variant and the shell is enabled.
- **UNKNOWN** — the value of `linux,uefi-secure-boot` on this board (property
  exists in `/chosen`, value not captured). If Secure Boot were enforcing, an
  unsigned QNX PE would be refused at `LoadImage`.

### 1.5 Exception level at hand-off

| Claim | Class | Source |
|---|---|---|
| BL31 jumps to BL33 "at the highest available Exception Level (EL2 if available, otherwise EL1)" — §5.4.1.5.5 "BL33 (Non-trusted Firmware) execution" | VENDOR_CLAIM (generic TF-A) | https://trustedfirmware-a.readthedocs.io/en/latest/design/firmware-design.html |
| Upstream TF-A Tegra common code only copies `bl33_image_ep_info = *arg_from_bl2->bl33_ep_info` — the SPSR/EL is chosen by the *previous* NVIDIA stage (MB2), not in TF-A common code | VERIFIED (source, upstream t186/t194/t210 lineage — T234 not upstream) | https://github.com/ARM-software/arm-trusted-firmware/blob/master/plat/nvidia/tegra/common/tegra_bl31_setup.c |
| ATF *is* used on Orin; T234 TF-A source ships only in the Jetson `public_sources` → `atf_src.tbz2` (JerryChang, 2024-01-31; nagesh_accord / JerryChang, 2025-03-28/31) | VENDOR_CLAIM (staff forum) | https://forums.developer.nvidia.com/t/arm-trusted-firmware-fork/280681 ; https://forums.developer.nvidia.com/t/whether-the-arm-trust-firmware-is-used-on-nvidia-agx-orin-platform/328642 |
| Jetson boot flow page: BootROM → PSCROM → MB1 → MB2 → UEFI → kernel; UEFI "replaces CBoot … as the CPUBL"; page does not name TF-A/EL | VENDOR_CLAIM | https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AR/BootArchitecture/JetsonOrinSeriesBootFlow.html |
| OP-TEE page: "The Jetson Linux monitor implementation is based on ATF"; OP-TEE runs at S-EL1, TAs at S-EL0 | VENDOR_CLAIM | https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/Security/OpTee.html |
| ProventusNova (2026-06-09): TF-A "Passes control to UEFI at EL2" | COMMUNITY | https://proventusnova.com/blog/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel |
| edk2-nvidia `TegraPlatformInfoLib/AArch64/TegraPlatformInfo.S` reads no `CurrentEL`; it uses `smc #0` (`SMCCC_ARCH_SOC_ID`) — no EL manipulation found in the NVIDIA layer; `L4TLauncher.c` has no EL1/EL2/HCR references | VERIFIED (source, absence) | https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Library/TegraPlatformInfoLib/AArch64/TegraPlatformInfo.S |
| UEFI spec §2.3.6 (AArch64 calling convention / EL rules) | UNKNOWN — uefi.org returned HTTP 403 for 2.10 and 2.10_A | — |
| **On this board the OS is entered at EL2 through this UEFI**: `All CPU(s) started at EL2` + `VHE mode initialized successfully` | VERIFIED (board) | §0 |

Net: EL2 entry of the OS loader is **verified empirically** on the Orin Nano
and consistent with TF-A's documented rule; the *source-level* proof for T234
sits in `atf_src.tbz2` (not fetched — no downloads permitted) and in MB2's
entry-point parameters (closed).

---

## 2. What UEFI hands the OS

### 2.1 Device tree via the FDT configuration table

- **VERIFIED (source)** — GUID `b1b621d5-f19c-41a5-830b-d9152c69aae0`
  (`DEVICE_TREE_GUID` in Linux `include/linux/efi.h`; the edk2 `.dec` was
  truncated by the fetch tool, so the value is cited from Linux).
  https://github.com/torvalds/linux/blob/master/include/linux/efi.h
- **VERIFIED (source)** — edk2 `EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.c`
  installs `gBS->InstallConfigurationTable(&gFdtTableGuid, Dtb)` **only when**
  the HII preference is `DT_ACPI_SELECT_DT`; when ACPI is selected it instead
  installs `gEdkiiPlatformHasAcpiGuid` to unlock the ACPI drivers — the two are
  mutually exclusive. Default comes from `PcdDefaultDtPref` (`EmbeddedPkg.dec`:
  `PcdDefaultDtPref|TRUE`, i.e. DT).
  https://github.com/tianocore/edk2/blob/master/EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.c ;
  https://github.com/tianocore/edk2/blob/master/EmbeddedPkg/EmbeddedPkg.dec
- **VERIFIED (source)** — `NVIDIA.common.dsc.inc` (checked at `r36.4.3` and `main`):
  `!ifdef CONFIG_DEVICETREE` → `DtPlatformDxe` if `CONFIG_ACPI` else NVIDIA's
  `DtOnlyPlatformDxe`; `DtPlatformDtbLoaderLib` = NVIDIA
  `DxeDtPlatformDtbKernelLoaderLib`.
  https://github.com/NVIDIA/edk2-nvidia/blob/r36.4.3/Platform/NVIDIA/NVIDIA.common.dsc.inc
- **VERIFIED (source)** — `DxeDtPlatformDtbKernelLoaderLib.c` (`main`): the DTB
  it installs is the **UEFI-embedded** one (`UefiDtb = GetDTBBaseAddress()`), with
  `ApplyTegraDeviceTreeOverlay(...)` overlays plus patches (`AddBoardProperties`,
  `UpdateRamOopsMemory`, `UpdatePvaFwMemory`, `ProcessDsuPmu`, OP-TEE/Trusty
  nodes); no partition lookup, no fallback.
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Library/DxeDtPlatformDtbLoaderLib/DxeDtPlatformDtbKernelLoaderLib.c
- **VERIFIED (source)** — L4TLauncher later *replaces* that table with the
  extlinux `FDT=`/partition DTB + overlays (§1.3).
- **VERIFIED (board)** — the running kernel's `/chosen` has the
  `linux,uefi-*` properties the EFI stub adds to the DTB it took from the
  config table (§0) — the mechanism is live on this board.

**Consequence for a payload launched straight from the Boot Manager (no
L4TLauncher):** it *does* receive an FDT config table (the firmware's own DTB,
overlaid/patched), not the `A_kernel-dtb` partition contents. HYPOTHESIS: for a
QNX startup that only needs GIC/timer/PSCI/UART/memory nodes this is
sufficient; whether the firmware DTB's PSCI compatible string is exactly
`"arm,psci"` (the only string QNX `fdt_psci_configure` matches, `harvest-sdp.md:91`)
is **UNKNOWN** — the board's `/psci` node compatible was not captured.

### 2.2 ACPI on the Orin Nano

| Claim | Class | Source |
|---|---|---|
| `Platform/NVIDIA/Kconfig` (`main`): `config ACPI bool "ACPI support"`; `TEGRA_ACPI depends on SOC_GENERAL \|\| SOC_DATACENTER, default y`; `DEVICETREE bool` | VERIFIED (source) | https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/Kconfig |
| `KconfigIncludes/SocT23X.conf` (`main`): `config SOC_T23X … imply SOC_GENERAL, imply SUPPORTS_TCU_DEBUG_SERIAL_PORT, imply DEFAULT_DEBUG_SERIAL_PORT_TCU` — so the `SOC_GENERAL` gate on `TEGRA_ACPI` **is** satisfied for T23x (closes the open question in `docs/orin-port.md` "Looked for and not found") | VERIFIED (source) | https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/KconfigIncludes/SocT23X.conf |
| `KconfigIncludes/BuildGeneral.conf` (`main`): `imply ACPI`, `imply DEVICETREE`, `imply DEFAULT_SERIAL_PORT_CONSOLE_TEGRA`, `imply SELECT_ALL_SHELL_COMMANDS`, `imply L4T`, `imply DEFAULT_RCM_BOOT_L4T_LAUNCHER` | VERIFIED (source) | https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/KconfigIncludes/BuildGeneral.conf |
| `Tegra/DefConfigs/t23x_general.defconfig` (`main`): `CONFIG_SOC_T23X=y`, `CONFIG_BUILD_GENERAL=y`, `CONFIG_PLATFORM_GUID="49a79a15-…"` (= the FvVol GUID in this board's boot entries) | VERIFIED (source + board) | https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/Tegra/DefConfigs/t23x_general.defconfig |
| r36.4.x generation: `Platform/NVIDIA/Kconfig` at `r36.4.3` has `ACPI … default y`, `SHELL default y`, `SOC_ORIN selects SOC_JETSON`; `Platform/NVIDIA/Jetson/Jetson.defconfig` at `r36.4.5` sets `CONFIG_SOC_ORIN=y`, `CONFIG_DEVICETREE=y`, `CONFIG_L4T=y`, `CONFIG_SERIAL_PORT_CONSOLE_TEGRA=y` and does **not** disable ACPI (so `default y` applies) | VERIFIED (source) | https://github.com/NVIDIA/edk2-nvidia/blob/r36.4.3/Platform/NVIDIA/Kconfig ; https://github.com/NVIDIA/edk2-nvidia/blob/r36.4.5/Platform/NVIDIA/Jetson/Jetson.defconfig |
| `NVIDIA.common.dsc.inc` at `r36.4.3`: `!ifdef CONFIG_ACPI` → `AmlGenerationDxe`, `AmlPatchDxe`, `AcpiTableDxe`, `AcpiDtbSsdtGenerator` | VERIFIED (source) | see §2.1 |
| **Shipped behaviour on this board: DT mode** — ACPI interpreter disabled, `/sys/firmware/acpi/tables` absent, no `ACPI=` config table | VERIFIED (board) | `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt:6-7,22`; §0 |
| The "Device Manager → O/S Hardware Description Selection" menu is documented for the Xavier-era UEFI; on JetPack 6 AGX Orin the Windows-11 and Fedora reports used it | VENDOR_CLAIM (Xavier readme) + COMMUNITY (AGX Orin) | https://developer.download.nvidia.com/embedded/L4T/UEFI_Readme_side_car.html ; https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/246176 |
| Whether the **Orin Nano** `36.4.4` firmware exposes that menu / ACPI tables | UNKNOWN — no vendor or community page found saying so for P3768; the source says the ACPI drivers are compiled in, the board says DT is selected |  |
| In ACPI mode the Linux console is `console=ttyAMA0,115200` (nullr0ute, Dec 2023, JetPack 6) — i.e. the firmware's SPCR points at the **SBSA UART** | COMMUNITY | https://nullr0ute.com/2023/12/any-linux-distro-on-nvidia-jetson-orin-with-jetpack-6/ |

**HYPOTHESIS worth testing** (cheap, needs the board): if ACPI mode can be
selected on the Orin Nano, QNX's `acpi_spcr_parse` (PL011/SBSA only,
`harvest-sdp.md:76`) would pick `serial@31d0000` (`arm,sbsa-uart`, present on
this board — `raw/orin-ttys.txt`) as the debug device *without* any Tegra code.
Where `uarti` @ `0x031d0000` is physically routed on P3768 is **UNKNOWN**
(on AGX Orin it appears on the debug micro-USB per nullr0ute; P3768 has no such
port — §4).

---

## 3. The UEFI console on Orin: TCU over HSP shared mailboxes

### 3.1 The library (candidate clean-room reference)

- Path: `Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c`
  (INF: `TegraCombinedSerialPortLib.inf`, wrapper `TegraCombinedSerialPortWrapper.inf`).
  https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c
- **VERIFIED (source, `main` and `r36.4.3`)** — `SPDX-License-Identifier: BSD-2-Clause-Patent`;
  `Copyright (c) 2018-2021, NVIDIA CORPORATION & AFFILIATES.` plus Apple
  (2008-2010), ARM (2012-2016), Intel (2015) headers. Same struct and loop at
  both refs.
- Functions: `IsDataPresent`, `TegraCombinedSerialPortInitialize`, `…Write`,
  `…Read`, `…Poll`, `…SetControl` (unsupported), `…GetControl`,
  `…SetAttributes` (unsupported), `…GetObject`.

Excerpt (29 lines, BSD-2-Clause-Patent, from the file above):

```c
typedef struct {
  UINT8      Data[3];
  UINT8      NumberOfBytes : 2;
  BOOLEAN    Flush         : 1;
  BOOLEAN    HwFlush       : 1;
  UINT8      Reserved      : 3;
  BOOLEAN    Interrupt     : 1;
} TEGRA_COMBINED_UART_PIO;

typedef union {
  UINT32                     RawValue;
  TEGRA_COMBINED_UART_PIO    Pio;
} TEGRA_COMBINED_UART;

/* TegraCombinedSerialPortWrite, inner loop */
  while (Buffer < Final) {
    while (IsDataPresent (TxMailbox) == TRUE) {
    }
    CombinedUartData.Pio.NumberOfBytes = 0;
    CombinedUartData.Pio.Reserved      = 0;
    CombinedUartData.Pio.Flush         = TRUE;
    while ((Buffer < Final) && (CombinedUartData.Pio.NumberOfBytes < 3)) {
      CombinedUartData.Pio.Data[CombinedUartData.Pio.NumberOfBytes] = *Buffer;
      CombinedUartData.Pio.NumberOfBytes++;
      Buffer++;
    }
    CombinedUartData.Pio.Interrupt = TRUE;
    MmioWrite32 (TxMailbox, CombinedUartData.RawValue);
    while (IsDataPresent (TxMailbox) == TRUE) {
    }
  }
```

`IsDataPresent` is `MmioRead32(Mailbox)` → return bit `Interrupt`.
`Initialize` writes `0` to both mailboxes, then one word with `Data[0]='\n'`,
`NumberOfBytes=1`, `Flush=HwFlush=Interrupt=TRUE`, and spins until it drains.

### 3.2 Register protocol (VERIFIED by three independent sources)

| Element | Value | Sources |
|---|---|---|
| Word layout (little-endian bit-fields) | bits 0-23 = up to 3 data bytes, byte 0 in bits 0-7; bits 24-25 = byte count (0-3); bit 26 = Flush; bit 27 = HwFlush; bits 28-30 reserved; **bit 31 = "Interrupt" = the HSP shared-mailbox FULL bit** | edk2 struct above; Linux `tegra-tcu.c`: `TCU_MBOX_BYTE(i,x) ((x) << (i*8))`, `TCU_MBOX_NUM_BYTES(x) ((x) << 24)`, `…_V(x) (((x)>>24)&0x3)`; Linux `tegra-hsp.c`: `HSP_SM_SHRD_MBOX 0x0`, `HSP_SM_SHRD_MBOX_FULL BIT(31)`, `tegra_hsp_sm_send32` ORs in FULL |
| Bytes per write | ≤ 3 | edk2 loop; Linux `tegra_tcu_write_one` |
| Ready test / handshake | spin while bit 31 set (receiver — the SPE — clears it when consumed); **no timeout** in edk2 | edk2 `IsDataPresent`; Linux uses `mbox_flush(tcu->tx, 1000)` |
| "TAG" register | only for 128-bit "type1" mailboxes: `TYPE1_TAG 0x40`, `DATA0..3 0x48..0x54` — **not used by TCU** (board DT `mboxes` cell type is `0x1` = `TEGRA_HSP_MBOX_TYPE_SM` without the `SM_128BIT` bit 8) | Linux `tegra-hsp.c`; `include/dt-bindings/mailbox/tegra186-hsp.h`; `raw/orin-devicetree.txt:288` |
| TX mailbox address | `0x0C168000` = AON HSP `hsp@c150000` + `0x10000` + 1 × `0x8000` → **AON shared mailbox 1** | edk2 Kconfig default `DEBUG_SERIAL_PORT_TCU_TX_MAILBOX 0x0C168000` (`main`); `NVIDIA.common.dsc.inc` @ `r36.4.3`: `PcdTegraCombinedUartTxMailbox\|0x0C168000`; Linux `tegra-hsp.c`: `mb->channel.regs = hsp->regs + SZ_64K + i * SZ_32K`; board DT `hsp@c150000 reg 0x0c150000 0x90000` |
| RX mailbox address | `0x03C10000` = TOP0 HSP `hsp@3c00000` + `0x10000` → **TOP0 shared mailbox 0** | Kconfig default `…_RX_MAILBOX 0x03C10000`; dsc.inc @ `r36.4.3` `…RxMailbox\|0x03C10000`; board DT `hsp@3c00000 reg 0x03c00000 0xa0000` |
| DT description | `tcu: serial { compatible "nvidia,tegra234-tcu","nvidia,tegra194-tcu"; mbox-names "rx","tx"; mboxes = <&hsp_top0 SM 0>, <&hsp_aon SM TX(1)> }` | binding example (`nvidia,tegra194-tcu.yaml`); board: `mboxes = <0x121 0x1 0x0>, <0x143 0x1 0x80000001>` (`TEGRA_HSP_SM_TX(1)` = `0x80000001`) — phandle→node identity of `0x121`/`0x143` not in the capture (HYPOTHESIS: top0/aon, consistent with the addresses) |
| Who multiplexes | "in the Sensor Processing Engine (SPE) for NVIDIA Jetson Orin" | VENDOR_CLAIM https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html |

URLs: https://github.com/torvalds/linux/blob/master/drivers/tty/serial/tegra-tcu.c (GPL-2.0 — read for cross-check only);
https://github.com/torvalds/linux/blob/master/drivers/mailbox/tegra-hsp.c (GPL-2.0);
https://github.com/torvalds/linux/blob/master/include/dt-bindings/mailbox/tegra186-hsp.h ;
https://github.com/torvalds/linux/blob/master/Documentation/devicetree/bindings/serial/nvidia,tegra194-tcu.yaml ;
https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/Kconfig ;
https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/NVIDIA.common.dsc.inc

**Licence fit:** the edk2-nvidia file is BSD-2-Clause-Patent (permissive,
with an explicit patent grant); the QNX BSP startup sources in the hypervisor-guest
zip carry Apache-2.0 headers (`harvest-repo.md` C7). A callout written from the
edk2 file's *protocol facts* — or even carrying its 2-line union — is
licence-compatible; the Linux driver is GPL-2.0 and should stay a cross-check
only. HYPOTHESIS, not legal advice.

**Risks for a QNX debug callout (HYPOTHESIS):** (1) it depends on the SPE
firmware being alive and routing CCPLEX SM1 to the debug UART — true while
UEFI/Linux use it, unknown after a foreign OS has run for a while;
(2) the no-timeout spin hangs the startup forever if the SPE stops draining;
(3) the `[RCE] TCU debug prints will be routed to traces` line in dmesg
(`raw/orin-ttys.txt`) shows other engines share the same mux.

---

## 4. P3768 Orin Nano Developer Kit carrier: where the UARTs are

### 4.1 J14 12-pin button header — the debug console (UART2)

| Claim | Class | Source |
|---|---|---|
| "connect 3.3V UART-to-USB adapter to pins on the J14 button header"; `Jetson UART2 TXD - Pin 3`, `Jetson UART2 RXD - Pin 4`, `GND - Pin 11`, `Pin 8 - System Reset`, `Pin 10 - Fore Recovery` [sic], `Pin 12 - Power button` | **VENDOR_CLAIM** (Developer Guide, Board Automation, Orin Nano section) | https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/AT/BoardAutomation.html |
| Silkscreen on J14 reads "UART2 (DEBUG)" pins 3/4; NVIDIA (Trumany, 2024-04-01): "Just keep it as debug only." | VENDOR_CLAIM (staff forum) | https://forums.developer.nvidia.com/t/uart2-on-j14/287429 |
| Module UART2 = SODIMM pins 236 (`UART2_TXD`) / 238 (`UART2_RXD`); it is the debug UART carrying MB1/MB2/FSI/UEFI output; KevinFFF (2026-05-18/19): repurposing is "unsupported and unverified"; UARTC is intentionally absent from `tegra234.dtsi` | VENDOR_CLAIM (staff forum) | https://forums.developer.nvidia.com/t/using-debug-uart-dev-ttytcu0-as-normal-dev-ttyths0-uart/370278 |
| `ttyTCU0` on the Orin Nano is backed by `uartc@c280000` (KevinFFF, Apr 2024) | VENDOR_CLAIM (staff forum, already in `docs/orin-port.md`) | https://forums.developer.nvidia.com/t/enabling-ttytcu0-as-regular-uart-on-orin-nano/287340 |
| RidgeRun: pins 3/4 RX/TX, 115200, `/dev/ttyUSB0` on the host, shows "the full output of the startup process … including the bootloader debug" | COMMUNITY | https://developer.ridgerun.com/wiki/index.php/NVIDIA_Jetson_Orin_Nano/In_Board/Getting_in_Board/Serial_Console |
| Board: `serial@3110000` exists in the DT (`nvidia,tegra234-uart`), and `serial@c280000` (uartc) does **not** — matching KevinFFF | VERIFIED (board) | `raw/orin-devicetree.txt:226-241,295-299` |

So the TCU/firmware console **physically appears on J14 pins 3 (TX) / 4 (RX) / 11 (GND)** as a 3.3 V logic UART; a **3.3 V USB-TTL adapter is required** (vendor wording). There is **no micro-USB debug port on P3768**: the user guide's USB-C port offers a "USB Serial device for serial terminal access" — that is the Linux USB gadget (`g_serial` → `/dev/ttyGS*`, host `/dev/ttyACM*`, `raw/orin-ttys.txt`), which exists only after Linux boots and is useless for firmware/startup output (VENDOR_CLAIM for the port's function: https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/hardware_layout.html ; the rest is VERIFIED from the tty driver list).

### 4.2 J12 40-pin expansion header — UART1 (CPU-drivable 8250-class)

| Claim | Class | Source |
|---|---|---|
| Pin 8 = `UART1_TX`, pin 10 = `UART1_RX`, pin 11 = `UART1_RTS`, pin 36 = `UART1_CTS`; 3.3 V logic | COMMUNITY (JetsonHacks pinout) | https://jetsonhacks.com/nvidia-jetson-orin-nano-gpio-header-pinout/ |
| UART1 (pins 8/10) is `3100000.serial` (`TEGRA_UART`, irq 112); works after setting the baud (`stty -F /dev/ttyTHS0 115200`) — KevinFFF, June 2024 | VENDOR_CLAIM (staff forum) | https://forums.developer.nvidia.com/t/jetson-orin-nano-developer-board-did-not-see-outputs-from-uart1-dev-ttyths0/295276 |
| On this board `serial@3100000` is `ttyTHS1` (alias `serial1`), `nvidia,tegra194-hsuart`, reg `0x03100000` size `0x10000`, irq 112 | VERIFIED (board) | `raw/orin-ttys.txt`; `raw/orin-devicetree.txt:58,209-224` |
| Upstream: `uarta` `0x03100000`, `uarte` `0x03140000` = `nvidia,tegra234-uart`,`nvidia,tegra20-uart` (8250-class); `uarti` `0x031d0000` = `arm,sbsa-uart` | VERIFIED (source) | https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi |
| The vendor "Jetson Orin Nano Developer Kit Carrier Board Specification" (referenced by the user guide for "pin assignments, voltage levels, and electrical limits") and the Orin NX/Nano Design Guide (Mouser mirror) | UNKNOWN — download-center login / PDF fetch timed out twice; not read | https://www.mouser.com/pdfDocs/Jetson_Orin_NX_Series_and_Orin_Nano_Series_Design_Guide_DG-10931-001_v11.pdf |

**HYPOTHESIS:** UART1 on J12 8/10 (SoC `uarta` @ `0x03100000`, 8250-style
32-bit-stride registers — cf. QNX `callout_debug_tegra.S`, `docs/orin-port.md`)
is the natural first console for a native startup because the CPU drives it
directly, unlike the TCU. Open: whether its clock/reset/pinmux are already
enabled at UEFI hand-off (Linux re-initialises them through BPMP; a QNX startup
has no BPMP client). A 3.3 V USB-TTL adapter is needed there too (header logic
level, COMMUNITY).

---

## 5. NVIDIA statements and new evidence of non-Linux payloads

The three "not supported" statements (2020 Xavier NX, 2024 AGX Orin, 2025
Orin) are already in `docs/orin-port.md` §(3) and are not repeated.

New or sharpened items:

| Item | Class | Source |
|---|---|---|
| **Windows 11 ARM Insider ISO on an Orin Nano Developer Kit** (May 2024): user booted the ISO from SD and got as far as "missing Jetson drivers"; NVIDIA (kayccc, DaveYYY): "We don't support Windows so there is no such driver". How far the Windows boot manager actually ran is not stated. | COMMUNITY (+ VENDOR_CLAIM for the "no support" line) | https://forums.developer.nvidia.com/t/windows-11-arm-insider-iso-for-jetson-orin-nano-developer-kit/294353 |
| Fedora / RHEL 9.3+ install via their own shim/GRUB on JetPack 6 UEFI; author lists Orin AGX/NX/Nano; ACPI-mode console `ttyAMA0` | COMMUNITY (Linux, but a third-party EFI loader chain) | https://nullr0ute.com/2023/12/any-linux-distro-on-nvidia-jetson-orin-with-jetpack-6/ |
| Red Hat Device Edge on Jetson Orin / Orin Nano / Orin NX / IGX with JetPack 6.0 firmware | VENDOR_CLAIM (Red Hat; Linux) | https://developers.redhat.com/learn/rhel/install-red-hat-device-edge-nvidia-jetson-orin-and-igx-orin |
| GRUB chain-loaded on Orin Nano via UEFI shell + ESP population (meta-tegra user, Feb 2024) | COMMUNITY | https://github.com/OE4T/meta-tegra/discussions/1480 |
| seL4 supported-hardware page lists Jetson TK1, TX1, TX2 only — **no Xavier/Orin/Tegra234** | VERIFIED (page) | https://docs.sel4.systems/Hardware/ |
| Xen ARM hardware wiki | UNKNOWN — page blocked (Anubis "Access Denied") | https://wiki.xenproject.org/wiki/Xen_ARM_with_Virtualization_Extensions |
| FreeBSD/OpenBSD/NetBSD, ESXi-Arm, Zephyr, Genode, Xvisor on Orin via UEFI | UNKNOWN — searches found nothing for Orin/Tegra234 | — |
| Third-party hypervisors "not supported on Jetpack release" but not hardware-locked (DaneLLL, 2025-10-30) — already in repo | VENDOR_CLAIM | https://forums.developer.nvidia.com/t/clarification-on-jetson-orin-hypervisor-support-hardware-lock-or-only-unsupported/348348 |

Net for (5): the **only** non-Linux OS anyone reports launching through the
Jetson UEFI is Windows 11 ARM (AGX Orin 2023 with ACPI; Orin Nano 2024,
outcome vague). No microkernel/hypervisor/BSD report for Orin was found.

---

## 6. Implications for the QNX native-port plan (short)

1. **Three injection routes exist, none needs firmware changes:** (a) replace
   `\EFI\BOOT\BOOTAA64.efi` on `mmcblk0p10`; (b) drop the PE in as
   `\EFI\BOOT\grubaa64.efi` and set `L4TDefaultBootMode=0`; (c) name it in
   `extlinux.conf` `LINUX=` (mode 1) and get the DTB config table + `APPEND`
   LoadOptions + LoadFile2 initrd for free (§1.3). Route (c) is the closest
   fit to `efi_entry_point`'s expectations. All HYPOTHESIS until booted.
2. **EL2 entry is real on this board** (§1.5), which is what a native QHV host
   (`hypervisor_init` → EL2&0) would need.
3. **Console:** first output should target the TCU TX mailbox at
   `0x0C168000` using the protocol in §3.2 (3 bytes/word, count in bits 24-25,
   set bit 31, poll bit 31) — output lands on J14 pins 3/4 with a 3.3 V adapter,
   the same place UEFI's own log appears. Second option: `uarta` @ `0x03100000`
   on J12 pins 8/10 (8250-class, CPU-owned). Third, if ACPI mode is
   selectable: the SBSA UART @ `0x031d0000` via QNX's existing SPCR path —
   physical routing on P3768 UNKNOWN.
4. **Before any of that:** capture `linux,uefi-secure-boot`'s value and the
   `/psci` node compatible string on the board (both UNKNOWN, both cheap).

---

## Looked for and not found

- The UEFI 2.10 spec text for §2.3.6 (uefi.org 403 twice).
- A vendor page saying the Orin Nano firmware exposes the ACPI/DT selection
  menu (only AGX Orin community reports and the Xavier readme).
- The physical routing of `uarti` (`0x031d0000`, SBSA) on P3768.
- The P3768 carrier board specification / Orin NX-Nano design guide text
  (login-gated / PDF fetch timeouts).
- Any non-Linux, non-Windows OS booted on Orin via UEFI.
- The T234 TF-A platform source (only inside `atf_src.tbz2`; downloads were out of scope).
- `gFdtTableGuid` in `EmbeddedPkg.dec` itself (fetch truncated; value taken from Linux `efi.h`).

## Source list (all fetched 2026-09-09)

- https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Bootloader/UEFI.html
- https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AR/BootArchitecture/JetsonOrinSeriesBootFlow.html
- https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html
- https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/AT/BoardAutomation.html
- https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/Security/OpTee.html
- https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html (P3768-0000 / P3767 part numbers only)
- https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/hardware_layout.html
- https://trustedfirmware-a.readthedocs.io/en/latest/design/firmware-design.html
- https://github.com/ARM-software/arm-trusted-firmware/blob/master/plat/nvidia/tegra/common/tegra_bl31_setup.c
- https://github.com/NVIDIA/edk2-nvidia (tags API; `main`, `r36.4.3`, `r36.4.5` refs as cited above)
- https://github.com/tianocore/edk2 (`EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.c`, `EmbeddedPkg/EmbeddedPkg.dec`)
- https://github.com/torvalds/linux (`drivers/tty/serial/tegra-tcu.c`, `drivers/mailbox/tegra-hsp.c`, `include/dt-bindings/mailbox/tegra186-hsp.h`, `include/linux/efi.h`, `Documentation/devicetree/bindings/serial/nvidia,tegra194-tcu.yaml`, `arch/arm64/boot/dts/nvidia/tegra234.dtsi`)
- https://forums.developer.nvidia.com/t/uart2-on-j14/287429
- https://forums.developer.nvidia.com/t/using-debug-uart-dev-ttytcu0-as-normal-dev-ttyths0-uart/370278
- https://forums.developer.nvidia.com/t/jetson-orin-nano-developer-board-did-not-see-outputs-from-uart1-dev-ttyths0/295276
- https://forums.developer.nvidia.com/t/windows-11-arm-insider-iso-for-jetson-orin-nano-developer-kit/294353
- https://forums.developer.nvidia.com/t/arm-trusted-firmware-fork/280681
- https://forums.developer.nvidia.com/t/whether-the-arm-trust-firmware-is-used-on-nvidia-agx-orin-platform/328642
- https://github.com/OE4T/meta-tegra/discussions/1480
- https://nullr0ute.com/2023/12/any-linux-distro-on-nvidia-jetson-orin-with-jetpack-6/
- https://developers.redhat.com/learn/rhel/install-red-hat-device-edge-nvidia-jetson-orin-and-igx-orin
- https://developer.ridgerun.com/wiki/index.php/NVIDIA_Jetson_Orin_Nano/In_Board/Getting_in_Board/Serial_Console
- https://jetsonhacks.com/nvidia-jetson-orin-nano-gpio-header-pinout/
- https://proventusnova.com/blog/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel
- https://docs.sel4.systems/Hardware/
- Local: `raw/orin-*.txt` (H3 captures), `harvest-sdp.md`, `harvest-repo.md`, `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt`, `docs/orin-port.md`
