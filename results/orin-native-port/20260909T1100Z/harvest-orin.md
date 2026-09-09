# TASK H3 — Live Jetson Orin Nano harvest (read-only, over ssh)

Date: 2026-09-09 (board local clock ~15:34–15:41, UTC+2; board uptime 16 h at capture).
Method: five short `ssh ... 'bash -s' < script` sessions plus one inline session, all READ-ONLY.
`sudo -n` was used only for reads: `dmesg`, `/proc/iomem`, `blkid`, `efibootmgr -v`, `ls -laR /boot/efi/EFI`,
ESRT entry files, `nvbootctrl dump-slots-info`, `fuser` on four ttys. No QEMU was started, nothing was
written on the board, no package was installed anywhere.

Redaction applied to every raw file: login name / hostname -> `<user>`, LAN IPs -> `<orin-ip>` / `<lan-ip>`,
ssh key -> `<orin-key>`, Ethernet MAC -> `<mac>`, NVMe serial / EUI -> `<nvme-serial>` / `<nvme-eui>`.

Evidence classes: **VERIFIED** = seen in a raw capture of this run (file:line below, all paths relative to
`raw/`); **VENDOR_CLAIM** = an NVIDIA/ARM file or doc says so; **HYPOTHESIS** = reasoned, untested;
**UNKNOWN** = could not be settled read-only.

Raw files produced by this run (all under `raw/`): `orin-sudo-probe.txt`, `orin-identity.txt`,
`orin-firmware-el.txt`, `orin-ttys.txt`, `orin-kexec.txt`, `orin-running.txt`, `orin-uefi.txt`,
`orin-boot-config.txt`, `orin-iomem.txt`, `orin-devicetree.txt`, `orin-followups.txt`, `orin-header-uart.txt`.
(`raw/orin-bootconfig.txt`, `raw/orin-followup.txt`, `raw/orin-uefi-dmesg.txt` are from an earlier H3 run
at 11:02–11:09 UTC and are not cited here.)

DT cell values below are printed as big-endian 32-bit cells exactly as `od --endian=big -t x4` shows them;
root `#address-cells = 2`, `#size-cells = 2` (`orin-devicetree.txt:9`), so `reg` pairs read as
`<hi lo>` address + `<hi lo>` size.

---

## 1. Fact table

| # | Claim | Evidence (raw/ file:line) | Class |
|---|-------|---------------------------|-------|
| 1 | Passwordless sudo works for the ssh user (`sudo -n true` -> rc 0). | `orin-sudo-probe.txt:3-4` | VERIFIED |
| 2 | Board model string: "NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super"; top-level compatible `nvidia,p3768-0000+p3767-0005-super`, `nvidia,p3767-0005`, `nvidia,tegra234`. | `orin-identity.txt:7,9-11`; `orin-uefi.txt:9`; `orin-devicetree.txt:7` | VERIFIED |
| 3 | Software: L4T R36 rev 4.7 (GCID 42132812, KERNEL_VARIANT oot), kernel `5.15.148-tegra`, Ubuntu 22.04.5 LTS. | `orin-identity.txt:13-14,18,20` | VERIFIED |
| 4 | CPU: 6 cores, ARM implementer 0x41, part 0xd42, variant 0x0, revision 1; MIDR_EL1 = 0x410fd421; `nproc` 6; DT cpu nodes say `arm,cortex-a78`. | `orin-identity.txt:23-25,27,29`; `orin-devicetree.txt:335,337` | VERIFIED |
| 4a | Part 0xD42 is the Cortex-A78AE part number (the DT only says `cortex-a78`). | ARM part-number tables (not captured on the board) | VENDOR_CLAIM |
| 5 | RAM visible to Linux: 7619 MiB total (`free -m`). | `orin-identity.txt:32` | VERIFIED |
| 6 | **EL at kernel entry: EL2** — "CPU: All CPU(s) started at EL2". | `orin-firmware-el.txt:32` | VERIFIED |
| 7 | **VHE is present and used**: "CPU features: detected: Virtualization Host Extensions"; "kvm [1]: VHE mode initialized successfully"; the host `arch_timer` runs on GIC INTID 26 (EL2 physical timer PPI), guest ptimer/vtimer on 30/27. | `orin-uefi.txt:62`; `orin-firmware-el.txt:38,44-46` | VERIFIED |
| 8 | `/dev/kvm` exists (`crw-rw----+ root kvm 10,232`); KVM IPA size limit 48 bits; "GICv3: no GICV resource entry / disabling GICv2 emulation". | `orin-firmware-el.txt:33-34,165` | VERIFIED |
| 9 | **UEFI vendor/version**: kernel sees "EFI v2.70 by EDK II"; SMBIOS `bios_vendor` = EDK II, `bios_version` = 36.4.4-gcid-41062509, `bios_date` 06/16/2025; `nvbootctrl` reports firmware "Current version: 36.4.4", bootloader slot B current+active; ESRT entry0 fw_version 2360324 (= 0x240404 = 36.4.4), fw_type 1. | `orin-firmware-el.txt:7`; `orin-uefi.txt:10,68-71`; `orin-boot-config.txt:369-372`; `orin-followups.txt:62-67` | VERIFIED |
| 9a | The QSPI UEFI (36.4.4) is one point-release behind the rootfs/kernel (36.4.7). | rows 3 and 9 | VERIFIED (observation) |
| 10 | UEFI runtime services are 64-bit (`fw_platform_size` 64); efivars mounted with 56 variables, including L4T-specific `BootChainFwCurrent`, `L4TDefaultBootMode`; config tables published: SMBIOS 3.0 @0x26d220000, ESRT @0x2671e4d98, MEMATTR, TPM event logs, EFI RNG protocol. | `orin-firmware-el.txt:8,182,201,213,215` | VERIFIED |
| 11 | Secure boot is off: "secureboot: Secure boot disabled"; `/chosen/linux,uefi-secure-boot` = 2. | `orin-uefi.txt:13`; `orin-followups.txt:19-20` | VERIFIED |
| 12 | **GICv3 (DT)**: `/bus@0/interrupt-controller@f400000`, compatible `arm,gic-v3`; `reg` = GICD **0x0F40_0000 size 0x1_0000**, GICR region **0x0F44_0000 size 0x20_0000**; `#redistributor-regions = 1`; `#interrupt-cells = 3`; maintenance IRQ `<1 9 0xf04>` (PPI 9 = INTID 25, matches "vgic interrupt IRQ9" / `/proc/interrupts` "GICv3 25 ... vgic"); **no `msi-controller`, no ITS subnode**. The on-disk DTB carries the same `reg` and `#redistributor-regions`. | `orin-devicetree.txt:88-96`; `orin-followups.txt:34-38`; `orin-firmware-el.txt:37,43` | VERIFIED |
| 13 | **GICv3 (runtime)**: 960 SPIs, 0 extended SPIs, 16 PPIs, no Range Selector; "GIC system register CPU interface" (ICC_* sysregs), split EOI/Deactivate; redistributors found at 0x0F44_0000 (CPU0, MPIDR 0), 0x0F46_0000 (0x100), 0x0F48_0000 (0x200), 0x0F4A_0000 (0x300), 0x0F50_0000 (CPU4, MPIDR 0x10200), 0x0F52_0000 (CPU5, MPIDR 0x10300) — i.e. 0x2_0000 per redistributor frame pair. No ITS line appears in dmesg although `CONFIG_ARM_GIC_V3_ITS=y`. | `orin-firmware-el.txt:16-18,20,22-23,26-30`; `orin-kexec.txt:37` | VERIFIED |
| 13a | The address gap between CPU3 (0xF4A0000) and CPU4 (0xF500000) corresponds to two absent MPIDR slots (0x10000, 0x10100) — the fused-off cores of the 6-core Orin Nano SKU; the 0x20_0000 region therefore holds 16 frame pairs. | derived from row 13 | HYPOTHESIS |
| 14 | A second, unrelated GIC exists for the audio cluster: `/bus@0/aconnect@2900000/interrupt-controller@2a40000`, `nvidia,tegra234-agic`, reg 0x02A4_1000/0x1000 + 0x02A4_2000/0x2000, cascaded on SPI 0x91; registered by Linux at 11.75 s. | `orin-devicetree.txt:74-75,81`; `orin-firmware-el.txt:41` | VERIFIED |
| 15 | **Arch timer**: `/timer` compatible `arm,armv8-timer`, `always-on`, interrupts `<1 13 0xf08> <1 14 0xf08> <1 11 0xf08> <1 10 0xf08>` = PPI 13 (secure phys, INTID 29), PPI 14 (non-secure phys, INTID 30), PPI 11 (virtual, INTID 27), PPI 10 (hyp phys, INTID 26); **level-low** on all cores (`0xf08` = IRQ_TYPE_LEVEL_LOW 0x8 with cpumask 0xf; an earlier pass in this file read it as level-high — research-tegra234.md:109 has it right). Counter frequency **31.25 MHz** ("cp15 timer(s) running at 31.25MHz (phys)"). | `orin-devicetree.txt:117-119`; `orin-firmware-el.txt:24` | VERIFIED |
| 16 | Tegra SoC timer block: `/bus@0/timer@2080000`, `nvidia,tegra234-timer`, reg 0x0208_0000 size 0x12_1000, 16 SPIs (0..9, 0x100..0x105), status okay; claimed in `/proc/iomem`. | `orin-devicetree.txt:108-113`; `orin-iomem.txt:15` | VERIFIED |
| 17 | **There is no `/memory@*` node** in the live DT (only `/reserved-memory` and `/bus@0/memory-controller@2c00000` match "mem"), and `dtc` finds no `memory` node / no `device_type = "memory"` in the on-disk DTB either. Linux obtains RAM from the UEFI memory map (`/chosen/linux,uefi-mmap-start` = 0x2_5E40_6018, size 0x840, `linux,uefi-system-table` = 0x2_6D82_0018). | `orin-devicetree.txt:28,30,35,130`; `orin-followups.txt:6-10,31-32` | VERIFIED |
| 18 | **DRAM window**: Linux fakes one NUMA node at 0x0000_8000_0000 – 0x0002_77FF_FFFF (so DRAM base 0x8000_0000, top 0x2_7800_0000, 8 GiB span with holes). System RAM per `/proc/iomem`: 0x8000_0000–0xBDFF_FFFF; 0xC200_0000–0xFFFD_FFFF; 0x1_0000_0000–0x2_5E20_DFFF; 0x2_5E40_0000–0x2_5E40_AFFF; 0x2_5E40_C000–0x2_6B8E_FFFF; 0x2_6D83_0000–0x2_71DF_FFFF; 0x2_7200_0000–0x2_7259_FFFF (entirely reserved). Kernel code at 0x9B29_0000–0x9D01_FFFF. | `orin-uefi.txt:18,25-39`; `orin-iomem.txt:180-215` | VERIFIED |
| 19 | **Reserved regions (DT `/reserved-memory`, `#address/#size-cells 2/2`)**: `linux,cma` shared-dma-pool size 0x1000_0000 (placed at 0x2_4A00_0000, 256 MiB); `ramoops_carveout` reg 0x2_725F_0000 size 0x20_0000, no-map; `pva-carveout` reg 0x2_7318_0000 size 0x28_0000; `camdbg_carveout` (size 0x320_0000, disabled); `vpr-carveout` (no-map, disabled); `framebuffer@0,0` (disabled); `rce-reservation` (iommu-addresses only). Firmware-reserved in iomem in addition: 0xFFFE_0000–0xFFFF_FFFF, 0x2_5E20_E000–0x2_5E3F_FFFF, 0x2_6B8F_0000–0x2_6D82_FFFF, 0x2_71E0_0000–0x2_71FF_FFFF (bl_prof from cmdline), 0x2_72F0_0000–0x2_72FF_FFFF, 0x2_7600_0000–0x2_77FF_FFFF, initrd 0x2_5A91_0000–0x2_5B83_0611. `/tegra-carveouts` (`nvidia,carveouts`) references memory-region phandles 0x376,0x377. | `orin-devicetree.txt:26-27,134,137-205`; `orin-uefi.txt:15`; `orin-iomem.txt:186,188,190-191,202,211,213-215`; `orin-followups.txt:16-18` | VERIFIED |
| 20 | On-chip SRAM: `/sram@40000000` (`nvidia,tegra234-sysram`, `mmio-sram`) reg 0x4000_0000 size 0x8_0000; Linux claims 0x4007_0000/0x4007_1000 sub-ranges. | `orin-followups.txt:23-24`; `orin-devicetree.txt:410`; `orin-iomem.txt:178` | VERIFIED |
| 21 | **TCU is the console.** `/serial` compatible `nvidia,tegra234-tcu`,`nvidia,tegra194-tcu`, status okay, **no `reg`** (mailbox transport only): `mboxes` rx = `<0x121 1 0x0>` -> `/bus@0/hsp@3c00000` (`hsp_top0`), tx = `<0x143 1 0x80000001>` -> `/bus@0/hsp@c150000` (`hsp_aon`); it is `ttyTCU0` (major 239, driver `tegra-tcu`); `aliases/serial0 = /serial`; `chosen/stdout-path = serial0:115200n8`; kernel cmdline `console=ttyTCU0,115200 ... console=tty0`; `/sys/class/tty/console/active` = "ttyTCU0 tty0"; `serial-getty@ttyTCU0` is running and holds the device (pid 968). | `orin-devicetree.txt:25,57,277-289`; `orin-followups.txt:45-47,49,51,54,90,95`; `orin-ttys.txt:12,25,42,46,50,57` | VERIFIED |
| 22 | **UARTA** `/bus@0/serial@3100000`: `nvidia,tegra194-hsuart`, reg **0x0310_0000 size 0x1_0000**, status okay, SPI 0x70 (112) level-high, reset-names `serial`, clock/reset via BPMP phandle 3; alias `serial1`, symbol `uarta`; registered as **`ttyTHS1`** ("ttyTHS1 at MMIO 0x3100000 ... TEGRA_UART", PIO mode); not held by any process. | `orin-devicetree.txt:58,209-219`; `orin-followups.txt:55,92`; `orin-ttys.txt:13,26,43,62`; `orin-iomem.txt:69` | VERIFIED |
| 23 | `/bus@0/serial@3110000`: `nvidia,tegra234-uart`,`nvidia,tegra20-uart` (8250-class), reg 0x0311_0000 size 0x1_0000, SPI 0x71 (113), **status disabled** — no tty is bound to it. | `orin-devicetree.txt:226-231` | VERIFIED |
| 24 | **UARTE** `/bus@0/serial@3140000`: `nvidia,tegra194-hsuart`, reg **0x0314_0000 size 0x1_0000**, okay, SPI 0x74 (116), dma rx/tx; alias `serial2`, symbol `uarte`; registered as **`ttyTHS2`**. | `orin-devicetree.txt:59,243-257`; `orin-followups.txt:56`; `orin-ttys.txt:14,44,63`; `orin-iomem.txt:70` | VERIFIED |
| 25 | **UARTI (SBSA)** `/bus@0/serial@31d0000`: `arm,sbsa-uart`, reg **0x031D_0000 size 0x1_0000**, okay, SPI 0x11d (285), `current-speed` 0x1C200 = 115200; symbol `uarti`; registered as **`ttyAMA0`** ("is a SBSA", PL011 driver, major 204). | `orin-devicetree.txt:260-273`; `orin-followups.txt:57`; `orin-ttys.txt:7,38,41,54`; `orin-iomem.txt:74` | VERIFIED |
| 25a | Where UARTI/`ttyAMA0` is routed physically on the P3768 carrier (if anywhere). | — | UNKNOWN |
| 26 | `ttyS0`–`ttyS3` exist (legacy 8250 driver, "4 ports") but have **no `of_node`** — the only 8250-class node (row 23) is disabled, so these are driver placeholders, not board UARTs. `nvgetty.service` ("UART on ttyTHS0") is inactive and `ttyTHS0` does not exist. | `orin-ttys.txt:8,32,41-44,55`; `orin-followups.txt:87` | VERIFIED (absence); "placeholder" reading = HYPOTHESIS |
| 27 | **40-pin header UART**: the vendor overlay `/boot/tegra234-p3767-0000+p3509-a02-hdr40.dtbo` ("Jetson 40pin Header", compatible list includes `nvidia,p3768-0000+p3767-0005-super`) pins `uart1_tx_pr2`, `uart1_rx_pr3`, `uart1_rts_pr4` (hdr40-pin11), `uart1_cts_pr5` to function **`uarta`** -> UARTA @0x0310_0000 = `ttyTHS1` (row 22). Not electrically verified; the TX/RX pin numbers were not captured in the excerpt. | `orin-header-uart.txt:89-90,99,103,106-108,114-115` | VENDOR_CLAIM |
| 28 | **HSP mailbox blocks**: `hsp@3c00000` (`hsp_top0`, reg 0x03C0_0000/0xA_0000, doorbell SPI 0xB0 + shared0..7 SPI 0x78..0x7F); `hsp@3d00000` (`hsp_top1`, 0x03D0_0000/0xA_0000, shared0..3 SPI 0x80..0x83); `hsp@c150000` (`hsp_aon`, 0x0C15_0000/0x9_0000, shared1..4 SPI 0x85..0x88); `hsp@1600000` (`hsp_top2`, disabled); `/tegra-hsp@b950000` (`hsp_rce`, `nvidia,tegra186-hsp`, 0x0B95_0000). All compatible `nvidia,tegra234-hsp`,`nvidia,tegra194-hsp` except rce. | `orin-devicetree.txt:302-330,424-426`; `orin-followups.txt:49-53`; `orin-iomem.txt:93-94,121,124` | VERIFIED |
| 29 | **PSCI**: `/psci` compatible `arm,psci-1.0`, `method = "smc"`, status okay; firmware reports PSCIv1.1, "Using standard PSCI v0.2 function IDs", SMC Calling Convention v1.2; all 6 `cpu@` nodes have `enable-method = "psci"`. | `orin-devicetree.txt:63-65,70,339`; `orin-firmware-el.txt:11,14` | VERIFIED |
| 30 | Other firmware/SoC nodes (compatible only): `/bpmp` `nvidia,tegra234-bpmp`,`nvidia,tegra186-bpmp` (+ `bpmp/i2c`, `bpmp/thermal`); `/bus@0/bpmp-fabric@d600000`; `/firmware/optee` `linaro,optee-tz` okay; `/firmware/ftpm` `microsoft,ftpm` okay; `/firmware/uefi` (no compatible); `/bus@0/pmc@c360000` `nvidia,tegra234-pmc`; `/bus@0/watchdog@2190000` `nvidia,tegra-wdt-t234` disabled; `/bus@0/pinmux@2430000` `nvidia,tegra234-pinmux` reg 0x0243_0000/0x1_9100 okay; `/bus@0/pinmux@c300000` `nvidia,tegra234-pinmux-aon`. No node named `*header*`/`*j12*` exists in the live tree (header pinmux only arrives via the overlay in row 27). | `orin-devicetree.txt:382-446` | VERIFIED |
| 31 | DT root: `#address-cells 2`, `#size-cells 2`, `interrupt-parent` = phandle 1 (the GICv3); `/bus@0` is `simple-bus` with identity `ranges` 0 -> 0 length 0x100_0000_0000. | `orin-devicetree.txt:6-19` | VERIFIED |
| 32 | **kexec binary**: `/usr/sbin/kexec` from `kexec-tools 1:2.0.22-2ubuntu2.22.04.2`; `efibootmgr 17-1ubuntu2` installed; `grub-common` only as removed-config (`rc`). | `orin-kexec.txt:7,10,12` | VERIFIED |
| 33 | **kexec kernel side**: `CONFIG_KEXEC=y`, `CONFIG_KEXEC_FILE=y`, `CONFIG_KEXEC_SIG` not set, `CONFIG_CRASH_DUMP=y` (config from `/proc/config.gz`); `kernel.kexec_load_disabled = 0`; `/sys/kernel/kexec_loaded = 0`, `kexec_crash_loaded = 0`, crash size 0; no `/sys/kernel/security/lockdown` file (lockdown LSM not exposed). `/boot/Image` is a plain "Linux kernel ARM64 boot executable Image, 4K pages". | `orin-kexec.txt:17,20-23,41,43-44,46,48,50` | VERIFIED |
| 33a | Whether a non-Linux payload (a QNX IFS / startup) can actually be handed over by `kexec -l` / `kexec -s` on this kernel, and at which EL it would be entered. | not tested (read-only) | UNKNOWN (HYPOTHESIS: with VHE the running kernel is at EL2, so a `kexec_load` transfer lands the new image at EL2) |
| 34 | Kernel config relevant to a port: `CONFIG_EFI=y`, `CONFIG_EFI_STUB=y`, `CONFIG_ACPI=y`, `CONFIG_KVM=y`, `CONFIG_SERIAL_8250=y`, `CONFIG_SERIAL_8250_TEGRA=y`, `CONFIG_SERIAL_TEGRA=y`, `CONFIG_SERIAL_TEGRA_TCU=y`, `CONFIG_SERIAL_TEGRA_TCU_CONSOLE=y`, `CONFIG_TEGRA_HSP_MBOX=y`, `CONFIG_ARM_GIC_V3=y`, `CONFIG_ARM_GIC_V3_ITS=y`, `CONFIG_ARM64_4K_PAGES=y`, VA/PA bits 48. No `CONFIG_ARM64_VHE` symbol exists in this 5.15 config (VHE is unconditional there; row 7 verifies it at runtime). | `orin-kexec.txt:17-37` | VERIFIED |
| 35 | **extlinux**: `/boot/extlinux/extlinux.conf`: `TIMEOUT 30`, `DEFAULT primary`, one active entry `LABEL primary` -> `LINUX /boot/Image`, `INITRD /boot/initrd`, `APPEND ${cbootargs} root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 mminit_loglevel=4 console=ttyTCU0,115200 firmware_class.path=/etc/firmware fbcon=map:0 video=efifb:off console=tty0`; **no `FDT` line** (the DTB comes from UEFI / the kernel-dtb partition); a commented-out `backup` entry template; a `.nv-update-extlinux-backup` copy exists. Effective `/proc/cmdline` adds `bl_prof_dataptr=2031616@0x271E10000 bl_prof_ro_ptr=65536@0x271E00000` from `${cbootargs}`. | `orin-boot-config.txt:7-16,23,33-35,133,353` | VERIFIED |
| 36 | `/boot` holds `Image` (43,090,432 B, Sep 19 2025), `initrd` (15,861,265 B), `dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb` (249,353 B, same size as the copy in `/boot`), plus the full set of Tegra234 `.dtb`/`.dtbo` files. | `orin-boot-config.txt:37-48,138` | VERIFIED |
| 37 | **Boot storage & ESP layout**: boot device is the microSD (`mmcblk0`, 238.4 GB; `TEGRA_BOOT_STORAGE mmcblk0`, `TEGRA_CHIPID 0x23`, OTA/GPT device `/dev/mtdblock0` = QSPI). GPT (15 parts): p1 `APP` ext4 root (237 G), p2 `A_kernel` 128 M, p3 `A_kernel-dtb` 768 K, p4 `A_reserved_on_user`, p5 `B_kernel`, p6 `B_kernel-dtb`, p7 `B_reserved_on_user`, p8 `recovery` 80 M, p9 `recovery-dtb` 512 K, **p10 `esp` 64 M vfat (UUID 4EA2-9257) mounted at `/boot/efi`**, p11 `recovery_alt`, p12 `recovery-dtb_alt`, p13 `esp_alt` 64 M, p14 `UDA` 400 M, p15 `reserved` 479.5 M. ESP contents: `EFI/BOOT/BOOTAA64.efi` (110,592 B) and an empty `EFI/UpdateCapsule/`. | `orin-boot-config.txt:157,188,198-201,270,281,322-335,362-366` | VERIFIED |
| 37a | An identically partitioned second L4T install sits on `nvme0n1` (238.5 GB, its own `esp`/`esp_alt`, ext4 `APP`), not mounted; UEFI lists it as `Boot0008`. | `orin-boot-config.txt:210-223,284,351` | VERIFIED |
| 38 | **UEFI boot entries** (`efibootmgr -v`): BootCurrent 0001; Timeout 30 s; BootOrder 0001 (UEFI SD Device, memory-mapped 0x3400000 SDMMC), 0008 (NVMe), 0004/0003/0002/0005 (HTTP/PXE v4/v6), 0007 (UEFI Shell), 0000 (Enter Setup), 0006 (BootManagerMenuApp). | `orin-boot-config.txt:339-351` | VERIFIED |
| 38a | `BOOTAA64.efi` on the ESP carries an mtime equal to the last boot time (Sep 8 23:33), suggesting the L4T UEFI/L4TLauncher rewrites or touches it on every boot. | `orin-boot-config.txt:333`; `orin-running.txt:9` | HYPOTHESIS (mtime VERIFIED) |
| 39 | Board is idle and safe to plan against: uptime 16 h, load 0.03, one X session, **no `qemu` process running**, root fs 26 G / 234 G used (12 %); no separate `/boot` filesystem (`/boot` is on the root ext4). | `orin-running.txt:7-15` | VERIFIED |

---

## 2. What this means for a native (non-QEMU) QNX startup on this board — reasoned, not tested

All items in this section are **HYPOTHESIS** unless they merely restate a row above.

* **Entry level.** Linux is entered at EL2 with VHE (rows 6-7). A payload handed over by `kexec` from this
  kernel would therefore also start at EL2 (row 33a). A startup written for EL1 entry must either drop to
  EL1 itself or be tolerant of EL2 entry — the same question the repo's `startup-qemu-virt` +
  `virtualization=on` runs already exercise under QEMU.
* **Interrupt controller.** GICD 0x0F40_0000 / GICR 0x0F44_0000 (row 12), sysreg CPU interface, no ITS
  in the DT (rows 12-13). A `gic_v3` init that assumes an ITS (or probes `GICD_TYPER`-derived ITS
  addresses) has nothing to find here; the GICR frames are at 0x2_0000 spacing with a hole for the two
  fused cores (row 13a).
* **Timer.** Generic timer at 31.25 MHz; the non-secure EL1 physical PPI is INTID 30, virtual INTID 27,
  EL2 physical INTID 26 (row 15) — the same PPI numbering QEMU `virt` uses, but a different frequency
  (QEMU `virt` uses 62.5 MHz), so any hard-coded `timer_freq` from the `qemu-virt` board files is wrong here.
* **Memory.** The DT has no `/memory` node (row 17); RAM must come from the UEFI memory map, from a
  `kexec`-generated DT (kexec-tools synthesises memory nodes from `/proc/iomem`), or be hard-coded from
  row 18 (base 0x8000_0000). Firmware carve-outs above 0x2_5E20_0000 (row 19) must stay untouched.
* **Console.** The default console is the TCU (row 21), which is a *mailbox* (HSP) device with no MMIO
  UART registers — a `startup` debug driver cannot poll it like a 16550. The MMIO alternatives are UARTA
  @0x0310_0000 (`ttyTHS1`, free, vendor-mapped to the 40-pin header, rows 22 & 27), UARTE @0x0314_0000
  (`ttyTHS2`, row 24) and the SBSA/PL011 UARTI @0x031D_0000 (`ttyAMA0`, row 25, physical routing UNKNOWN).
  Tegra `hsuart` blocks are 8250-register-layout devices with a 4-byte register stride (VENDOR_CLAIM,
  from the `nvidia,tegra20-uart` 8250 compatibility in row 23) — an `8250`-style startup debug driver at
  0x0310_0000 with shift 2 is the obvious first attempt; unverified.
* **PSCI** is `smc`-conduit v1.1 (row 29), so SMP bring-up via `CPU_ON` from EL2/EL1 is available without
  a spin-table.
* **Hand-over mechanisms available read-only today:** `kexec` (binary + `KEXEC`/`KEXEC_FILE`, no
  signature enforcement, not disabled — rows 32-33) and the UEFI boot manager (row 38, ESP is a plain FAT
  with a single `BOOTAA64.efi`, row 37). Both are untested for a non-Linux payload (row 33a).

---

## 3. Unknowns (could not be settled read-only)

1. Whether `kexec` (either syscall) will accept and jump to a non-Linux ARM64 image on this 5.15 L4T kernel,
   and at what EL the payload is entered (row 33a).
2. Physical routing of UARTI/`ttyAMA0` (SBSA UART @0x031D_0000) on the P3768 carrier (row 25a).
3. The header pin numbers for `uart1_tx_pr2`/`uart1_rx_pr3` — the overlay excerpt captured only the RTS
   block's `hdr40-pin11` label (row 27); NVIDIA's pinout doc is needed for TX/RX pin numbers.
4. What `/tegra-carveouts` phandles 0x376/0x377 point to (row 19) — not resolved.
5. Whether the Tegra `hsuart` register map is usable by a plain 8250 driver with 4-byte stride
   (§2 console bullet) — vendor-implied only.
6. Why `BOOTAA64.efi`'s mtime equals the last boot time (row 38a) — firmware behaviour not inspected.
7. The two ESP-less boot paths L4T UEFI actually walks before reading `extlinux.conf` (kernel-dtb partition
   vs `/boot/dtb`) — the harvest shows both DTB copies (row 36) but not which one the firmware loaded.
8. Contents of the `A_kernel`/`A_kernel-dtb` partitions were not read (no block-device reads in this run).

---

## 4. Session hygiene / caveats

* Six ssh sessions total, each under ~20 s; no long-running process left behind; `fuser` showed only the
  getty on `ttyTCU0`.
* The `raw/` directory is shared with other harvest tasks. During file finalisation this run briefly
  prepended a 4-line header to three files of the earlier H3 run (`orin-bootconfig.txt`,
  `orin-followup.txt`, `orin-uefi-dmesg.txt`); the header was removed again and their original first lines
  are back in place. If that earlier run also produced files with any of *this* run's names (listed at the
  top), those would have been overwritten by this run's redirects — this could not be determined afterwards.
