# R4 — Tegra234 (Jetson Orin Nano devkit) hardware facts a native QNX `startup-*` needs

Date: 2026-09-09 (run id `20260909T1100Z`). External research task, **public sources only**.
No board access in this task (the live-board facts below come from the sibling H3
harvest already in `raw/` next to this file, captured read-only on 2026-09-09 and
redacted there). No QNX binary was disassembled; QNX facts are taken from the sibling
`harvest-sdp.md` (symbol names / Apache-2.0 source only).

Evidence classes, used per row: **VERIFIED** (seen this session: a fetched source
file, a command output, or a `raw/` harvest line), **VENDOR_CLAIM** (an NVIDIA doc,
datasheet, forum answer by NVIDIA staff, or a firmware log posted by a user),
**HYPOTHESIS** (derived / reasoned, untested on the board), **UNKNOWN**.
"VERIFIED (code)" means the fact is a line in a public driver/firmware source I
fetched; it is not a hardware measurement.

The Tegra234 TRM was **not** consulted: it sits behind a developer login (the repo's
`docs/orin-port.md` already records HTTP 403 on it) and no attempt was made to
bypass that. Two vendor PDFs (carrier-board spec, module datasheet) were fetched by
`WebFetch` and text-extracted locally with `pdftotext`; page-level citations refer to
the printed page numbers.

External quotes are kept under 15 words each.

---

## 0. One-screen summary (what the startup must know)

| Item | Value | Class |
|---|---|---|
| CPU | 6x Cortex-A78AE, MIDR `0x410fd421` (masked `0x4100d420`, part `0xd42`, var 0, rev 1) | VERIFIED (`raw/orin-identity.txt`, `raw/orin-firmware-el.txt`) |
| MPIDR / clusters | `0x000 0x100 0x200 0x300` (cluster 0) + `0x10200 0x10300` (cluster 1, cores 2-3); Aff0 always 0 | VERIFIED (`raw/orin-devicetree.txt` cpus node, dmesg) |
| Entry EL from UEFI | EL2 (VHE present); TF-A stays at EL3; OP-TEE present | VERIFIED (dmesg) |
| PSCI | `arm,psci-1.0`, `method = "smc"`, firmware reports PSCI 1.1, SMCCC 1.2; CPU_ON brought up all 5 secondaries under Linux | VERIFIED |
| GICD | `0x0f400000`, 64 KiB | VERIFIED (DT, edk2 `T234Definitions.h`) |
| GICR | `0x0f440000`, 2 MiB, one region, **16 frames of 0x20000** (GICv3 RD+SGI frames, no VLPI) | VERIFIED (DT, dmesg, edk2 `T234_GIC_REDISTRIBUTOR_INSTANCES 16`) |
| GICR frame used per CPU | CPU0..3 -> frames 0..3 (`0xf440000`..`0xf4a0000`); MPIDR `0x10200` -> frame **6** (`0xf500000`); `0x10300` -> frame 7 (`0xf520000`). Frames 4,5,8..15 belong to floor-swept / absent cores | VERIFIED (dmesg) |
| GIC features | 960 SPIs, 16 PPIs, no ESPI ("no Range Selector"), maintenance IRQ PPI 9, system-register CPU interface | VERIFIED (dmesg) |
| ITS | none in DT, no LPI/MSI in dmesg; hardware presence | VERIFIED absent from DT / UNKNOWN in silicon |
| GIC IP (GIC-600?) | not stated in any public source found | UNKNOWN |
| Generic timer PPIs | 13 sec-phys, 14 phys, 11 virt, 10 hyp; all level-low (`0xf08`); no hyp-virt entry; `always-on` | VERIFIED (DT) |
| CNTFRQ | **31.25 MHz** (`31250000`) | VERIFIED (dmesg `arch_timer ... 31.25MHz`) |
| DRAM base / size | `0x80000000`; 8 GiB module; Linux sees `0x80000000`..`0x277ffffff` with holes | VERIFIED (`raw/orin-iomem.txt`, dmesg) |
| Must-avoid RAM | `0xbe000000-0xc1ffffff` (64 MiB) and `0x278000000-0x27fffffff` (128 MiB) are **not** presented as RAM; plus every `reserved` sub-range in `/proc/iomem` (UEFI/ACPI tables, ramoops `0x2725f0000`, PVA `0x273180000`, etc.) | VERIFIED (iomem) — identity of the holes UNKNOWN |
| Authoritative RAM map | the UEFI memory map (QNX `init_raminfo_uefi` / `efi_walk_map`) — not a hard-coded 8 GiB | HYPOTHESIS (recommended practice; matches how L4T gets its map) |
| SysRAM | `0x40000000`, 512 KiB; BPMP IVC channels at `+0x70000`/`+0x71000` — do not touch | VERIFIED (DT) |
| Debug UART physically on J14 (12-pin) | J14 pin 4 = `UART2_TXD (DEBUG)` (module pin 236), pin 3 = `UART2_RXD (DEBUG)` (module pin 238), 3.3 V. This is the **Tegra Combined UART**, owned by the SPE; the physical UART behind it is AON `uartc @ 0x0c280000` | VENDOR_CLAIM (carrier spec Table 3-4; KevinFFF; edk2 `PcdSerialRegisterBase|0x0C280000`) |
| Way to print on J14 without a UART driver | write to the TCU **TX mailbox `0x0c168000`** (hsp_aon shared mailbox 1): poll bit 31 clear, write `(1<<31) | (nbytes<<24) | up to 3 bytes` | VERIFIED (code: Linux `tegra-tcu.c`/`tegra-hsp.c`, edk2 `TegraCombinedSerialPortLib.c`, Kconfig default `0x0C168000`) — untested from QNX: HYPOTHESIS |
| UART on the 40-pin header (J12) | pins 8/10 = `UART1_TXD/RXD` = module pins 203/205 = SoC pads `PR.02/PR.03` = `uarta @ 0x03100000` (Linux `ttyTHS1`), 8250-class, 32-bit regs, `reg-shift 2`, SPI 112; clock/reset are **BPMP-owned** | VENDOR_CLAIM (carrier spec) + VERIFIED (DT) |
| SBSA UART | `uarti @ 0x031d0000`, `arm,sbsa-uart`, 115200, SPI 285, no clocks/resets in DT, enabled and probed as `ttyAMA0`; **pins on this devkit UNKNOWN** | VERIFIED (DT, dmesg) / UNKNOWN routing |
| HSP top0 | `0x03c00000`, 0xa0000; doorbell SPI 176, shared 0-7 = SPI 120-127 | VERIFIED |
| HSP AON | `0x0c150000`, 0x90000; shared 1-4 = SPI 133-136 | VERIFIED |
| Watchdog | TKE WDT0 at `0x02190000` (TKE `0x02080000`); L4T arms it (120 s, `nvidia,enable-on-init`); MB1 arms then disables its own WDT; UEFI's watchdog is a 5-min **software** timer that dies at ExitBootServices; **no evidence a HW WDT is running when a UEFI payload gets control — not board-verified** | VERIFIED (code, DT) / VENDOR_CLAIM (logs, staff) / UNKNOWN at handoff |
| PMC | `0x0c360000` (pmc), `0x0c370000` (wake), `0x0c380000` (aotag), `0x0c390000` (scratch: bootloader params + reboot-reason bits); reset only via PSCI `SYSTEM_RESET` | VERIFIED (iomem, edk2) |
| Clocks/resets | every `clocks`/`resets` in the DT points at `&bpmp`; there is no CPU-visible CAR node — a startup cannot enable a UART clock without BPMP MRQ | VERIFIED (DT) |
| SMMU | three Arm **MMU-500 (SMMUv2)** instances (`nvidia,smmu-500`), not SMMUv3; MB2 runs "SMMU external bypass disable" + "SMMU init"; bypass state at handoff | VERIFIED (DT/iomem) / VENDOR_CLAIM (log) / UNKNOWN |
| On-board LED a GPIO can drive | green **Power LED DS1** = module `GPIO04` (pin 127) = Tegra **`PCC.01`** (AON GPIO, Linux gpio 329); derived registers `0x0c2f1420` (ENABLE_CONFIG), `0x0c2f142c` (OUTPUT_CONTROL), `0x0c2f1430` (OUTPUT_VALUE) | VENDOR_CLAIM (forum, spec) + HYPOTHESIS (addresses derived from `gpio-tegra186.c`) |

---

## 1. CPU complex, MPIDR layout, exception level

| # | Fact | Source | Class |
|---|---|---|---|
| 1.1 | 6 CPUs, all `implementer 0x41 part 0xd42 variant 0 revision 1`; `midr_el1 = 0x00000000410fd421` | `raw/orin-identity.txt` (`/proc/cpuinfo`, `nproc`), `raw/orin-firmware-el.txt` | VERIFIED |
| 1.2 | Masking variant/revision gives `0x4100d420` = the QNX `cpuid_a78ae` table entry (`{ .midr = 0x4100D420, .name = "Cortex-A78ae" }`), already linked into both shipped startups | `harvest-sdp.md` §3a (nm + Apache-2.0 source) | VERIFIED |
| 1.3 | DT `cpus`: six `cpu@` nodes `reg = <0x0> <0x100> <0x200> <0x300> <0x10200> <0x10300>`, `compatible = "arm,cortex-a78"`, `enable-method = "psci"`; `cpu-map` = cluster0 {core0..3}, cluster1 {core0 = cpu@10200, core1 = cpu@10300}; per-core 64 KiB I/D L1, 256 KiB L2, two 2 MiB L3 nodes | `raw/orin-devicetree.txt` cpus dump | VERIFIED |
| 1.4 | dmesg: `Booted secondary processor 0x0000000100 ... 0x0000010200 ... 0x0000010300 [0x410fd421]` — the affinity values Linux passed to PSCI `CPU_ON` | `raw/orin-followup.txt` | VERIFIED |
| 1.5 | Reading: Aff0 is always 0, Aff1 = core-in-cluster, Aff2 = cluster (the DSU "MT" MPIDR layout). Cluster 1 exposes cores 2 and 3 only: cores 0/1 are floor-swept on the 6-core SKU | reasoning over 1.3/1.4 | HYPOTHESIS (values VERIFIED, naming inferred) |
| 1.6 | Upstream `tegra234.dtsi` (v5.19 and master) describes the full 12-core Tegra234: `cpu@0..cpu@300`, `cpu@10000..cpu@10300`, `cpu@20000..cpu@20300`, three clusters. The Orin Nano floor-sweeping is applied by firmware, not by upstream `tegra234-p3767.dtsi` (no `/delete-node/` there) | https://raw.githubusercontent.com/torvalds/linux/v5.19/arch/arm64/boot/dts/nvidia/tegra234.dtsi ; .../master/.../tegra234-p3767.dtsi | VERIFIED (source) |
| 1.7 | Module datasheet: "Six-core ... Cortex A78AE ARMv8.2 (64-bit)", one quad-core + one dual-core cluster, 256 KB L2 per core, 2 MB L3 per cluster, 4 MB system cache; 40-bit PA | DS-11105-001 v1.1 pp. 1, 6 (digikey mirror, see §12) | VENDOR_CLAIM |
| 1.8 | Firmware hands the OS EL2 with VHE: `CPU: All CPU(s) started at EL2`, `CPU features: detected: Virtualization Host Extensions`; KVM `VHE mode initialized successfully` | `raw/orin-firmware-el.txt`, `raw/orin-uefi-dmesg.txt` | VERIFIED |
| 1.9 | Third-party boot-flow write-up: MB1 (BPMP) -> MB2 -> TF-A (EL3, resident) -> UEFI at EL2 -> kernel | https://proventusnova.com/blog/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel | VENDOR_CLAIM (third party) |
| 1.10 | QNX consequence: `_start_el2_or_el1` / `drop_to_el1` (harvest-sdp §3a) must expect EL2 entry; `hypervisor_init()` could keep EL2 (QHV host case) | harvest-sdp §3a | HYPOTHESIS |

## 2. PSCI, TF-A, OP-TEE

| # | Fact | Source | Class |
|---|---|---|---|
| 2.1 | DT `psci { compatible = "arm,psci-1.0"; method = "smc"; status = "okay"; }` | `raw/orin-devicetree.txt` | VERIFIED |
| 2.2 | dmesg: `psci: PSCIv1.1 detected in firmware`, `Using standard PSCI v0.2 function IDs`, `SMC Calling Convention v1.2`, `Trusted OS migration not required` | `raw/orin-firmware-el.txt` | VERIFIED |
| 2.3 | `CPU_ON` for every core: Linux (enable-method `psci`) booted CPUs 1-5; there is no spin-table | 1.4 | VERIFIED |
| 2.4 | `firmware/optee { compatible = "linaro,optee-tz"; method = "smc"; }`, `firmware/ftpm { compatible = "microsoft,ftpm"; }` — SMCs also reach OP-TEE/fTPM through TF-A | `raw/orin-followup.txt` | VERIFIED |
| 2.5 | TF-A + OP-TEE sources for T234 ship in the Jetson Linux "Driver Package (BSP) Sources" as `atf_src.tbz2` and `nvidia-jetson-optee-source.tbz2` with `atf_and_optee_README.txt` (JerryChang, 2024-01-31) | https://forums.developer.nvidia.com/t/arm-trusted-firmware-fork/280681 | VENDOR_CLAIM |
| 2.6 | An R35.5 Orin NX log shows `NOTICE: BL31: v2.6(release):l4t-r35.5.0`; the BL31 version on this R36.4.7 board was not captured | https://github.com/orgs/OE4T/discussions/1714 | VENDOR_CLAIM (posted log) / UNKNOWN for this board |
| 2.7 | **QNX gotcha:** `fdt_psci_configure()` in libstartup matches only `compatible = "arm,psci"` (harvest-sdp §3a, VERIFIED in source); the Orin DT says `"arm,psci-1.0"` -> the board `main.c` must set `psci_call = psci_smc` and the `CPU_ON` function id itself, not rely on the FDT helper | harvest-sdp §3a + 2.1 | VERIFIED (both halves) -> consequence HYPOTHESIS |
| 2.8 | The PSCI target id must carry the full affinity word (`0x10200`), which `psci_cpu_id()` (MPIDR -> id) presumably does; `board_smp_num_cpu()` must return 6 (or read `fdt_num_cpu()` = 6 from the UEFI-supplied FDT) | harvest-sdp §3a | HYPOTHESIS |

## 3. GICv3

| # | Fact | Source | Class |
|---|---|---|---|
| 3.1 | Board DT `interrupt-controller@f400000 { compatible = "arm,gic-v3"; reg = <0 0xf400000 0 0x10000>, <0 0xf440000 0 0x200000>; #redistributor-regions = <1>; interrupts = <1 9 0xf04>; }` (maintenance IRQ = PPI 9, level-high) — no child nodes | `raw/orin-devicetree.txt`, `raw/orin-followup.txt` | VERIFIED |
| 3.2 | Upstream master and v5.19 `tegra234.dtsi` carry the same node (`GICD 0x0f400000/0x10000`, `GICR 0x0f440000/0x200000`) | https://raw.githubusercontent.com/torvalds/linux/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi | VERIFIED (source) |
| 3.3 | edk2-nvidia `T234Definitions.h`: `T234_GIC_DISTRIBUTOR_BASE 0X0F400000`, `T234_GIC_REDISTRIBUTOR_BASE 0X0F440000`, `T234_GIC_REDISTRIBUTOR_INSTANCES 16`; platform DSC: `PcdGicDistributorBase|0X0F400000`, `PcdGicRedistributorsBase|0X0F440000` | https://raw.githubusercontent.com/NVIDIA/edk2-nvidia/main/Silicon/NVIDIA/Include/Tegra/T234/T234Definitions.h ; https://raw.githubusercontent.com/NVIDIA/edk2-nvidia/main/Platform/NVIDIA/NVIDIA.common.dsc.inc | VERIFIED (source) |
| 3.4 | Redistributor stride is **0x20000** (RD_base + SGI_base, 64 KiB each — GICv3 layout, no GICv4 VLPI frames): dmesg `CPU0: found redistributor 0 region 0:0x000000000f440000`, CPU1 `100` -> `0xf460000`, CPU2 `200` -> `0xf480000`, CPU3 `300` -> `0xf4a0000`, CPU4 `10200` -> `0xf500000`, CPU5 `10300` -> `0xf520000` | `raw/orin-firmware-el.txt` | VERIFIED |
| 3.5 | 2 MiB / 0x20000 = 16 frames = edk2's 16 instances; frame i <-> (cluster*4 + core). Frames 4 and 5 (`0x10000`, `0x10100`) and 8-15 have no live CPU. **A startup must walk GICR frames and match `GICR_TYPER.Affinity` to each CPU's MPIDR (stopping at `GICR_TYPER.Last`), not assume frame == cpu index.** The QNX `gic_v3_set_paddr_range(gicd, gicr, gicr_size, gits)` API (harvest-sdp §5a) takes a range, which suggests it scans; whether it tolerates unpopulated frames is untested | 3.3, 3.4, harvest-sdp | VERIFIED numbers; scanning requirement HYPOTHESIS |
| 3.6 | `GICv3: 960 SPIs implemented`, `0 Extended SPIs`, `Distributor has no Range Selector support`, `16 PPIs implemented`, `GIC: Using split EOI/Deactivate mode`, `CPU features: detected: GIC system register CPU interface` | `raw/orin-firmware-el.txt` | VERIFIED |
| 3.7 | KVM at boot: `GICv3: no GICV resource entry`, `disabling GICv2 emulation` — there is no GICv2-compat (GICV) frame; irrelevant natively | same | VERIFIED |
| 3.8 | ITS: no `its`/`msi-controller` node anywhere in the live DT, no `ITS`/`LPI`/`MSI` line in dmesg; upstream `tegra234.dtsi` has no ITS child either. Whether the silicon contains an unused ITS is not stated publicly | `raw/orin-followup.txt`; upstream dtsi | VERIFIED (absent from DT) / UNKNOWN (silicon) |
| 3.9 | Whether the block is Arm GIC-600: no public NVIDIA page or DT string says so (the DT is generic `arm,gic-v3`); the 64 KiB GICD + 128 KiB GICR frames + 960 SPIs are consistent with a GIC-600 configured without ITS/VLPI but that is not proof | web search, no hit | UNKNOWN |
| 3.10 | MB2 programs the GIC before handing off: firmware log task `I> Task: Program GICv3 registers (0x50029034)` (after `SMMU init`) — i.e. security/group configuration is done by firmware; the startup only needs the non-secure-visible init (as QEMU `virt`) | https://github.com/orgs/OE4T/discussions/1714 (R35.5.0 Orin NX log) | VENDOR_CLAIM |
| 3.11 | Secondary `nvidia,tegra234-agic` (GIC-400-class, `0x2a41000`/`0x2a42000`) serves the audio processor only — not the CPU GIC | `raw/orin-devicetree.txt` | VERIFIED |
| 3.12 | The NISV writeback-store hazard in QNX `gic_v3.c` (repo's Phase-3 finding) is a **KVM-trap** artefact; it cannot occur on bare metal, so it is not a blocker for a native port | `docs/orin-port.md` risk register | VERIFIED (repo) |

## 4. Generic timer and Tegra TKE

| # | Fact | Source | Class |
|---|---|---|---|
| 4.1 | `timer { compatible = "arm,armv8-timer"; interrupts = <1 13 0xf08>, <1 14 0xf08>, <1 11 0xf08>, <1 10 0xf08>; always-on; }` -> PPI 13 secure-phys, 14 non-secure phys, 11 virt, 10 hyp-phys; flags `0xf08` = level-low, CPU mask 0xff; **no hyp-virt (PPI 12) entry** | `raw/orin-devicetree.txt` | VERIFIED |
| 4.2 | `/proc/interrupts`: `GICv3 26 Level arch_timer` (INTID 26 = PPI 10, Linux at EL2 uses the EL2 physical timer), `GICv3 30 kvm guest ptimer` (PPI 14), `GICv3 27 kvm guest vtimer` (PPI 11), `GICv3 25 vgic` (PPI 9) | `raw/orin-iomem.txt` | VERIFIED |
| 4.3 | `arch_timer: cp15 timer(s) running at 31.25MHz (phys)`; `sched_clock: 56 bits at 31MHz, resolution 32ns` -> **CNTFRQ_EL0 = 31,250,000 Hz** as programmed by firmware (a 32 ns tick) | `raw/orin-firmware-el.txt` | VERIFIED |
| 4.4 | QNX `init_qtime()`/`init_qtime_v8gt` reads `CNTFRQ_EL0` for `timer_freq` (the armv8_fm board does exactly this); nothing Tegra-specific is needed for the OS tick. Which PPI QNX uses depends on the EL it runs at (EL1: PPI 14 phys or 11 virt; EL2 host: PPI 10) | harvest-sdp §3a/§5b | HYPOTHESIS |
| 4.5 | Tegra TKE `timer@2080000 { compatible = "nvidia,tegra234-timer"; reg = <0 0x02080000 0 0x00121000>; }` — 16 x 29-bit timers + 2 watchdogs + TSC; `/proc/iomem 02080000-021a0fff : 2080000.timer` | upstream dtsi; binding `nvidia,tegra186-timer.yaml`; `raw/orin-iomem.txt` | VERIFIED |
| 4.6 | The system counter is initialised by MB1 (`I> Task: TSC init`) | OE4T #1714 / forum 210971 logs | VENDOR_CLAIM |
| 4.7 | Upstream `timer-tegra186.c`: TMR i base = `0x10000 + i*0x10000`; WDT j base = `0x10000 + num_timers*0x10000 + j*0x10000`; tegra234 `num_timers = 16`, `num_wdts = 2` -> WDT0 = `0x02080000 + 0x110000` = **`0x02190000`** (matches the L4T node, §9) | https://raw.githubusercontent.com/torvalds/linux/master/drivers/clocksource/timer-tegra186.c | VERIFIED (code + arithmetic) |

## 5. Memory: base, 8 GiB layout, carve-outs, SysRAM

| # | Fact | Source | Class |
|---|---|---|---|
| 5.1 | DRAM starts at `0x80000000`; edk2 `PcdSystemMemoryBase|0X80000000`; `NUMA: Faking a node at [mem 0x80000000-0x277ffffff]` | `raw/orin-uefi-dmesg.txt`; NVIDIA.common.dsc.inc | VERIFIED |
| 5.2 | Linux "System RAM" ranges (`/proc/iomem`): `0x80000000-0xbdffffff`, `0xc2000000-0xfffdffff`, `0x100000000-0x25e20dfff`, `0x25e400000-0x25e40afff`, `0x25e40c000-0x26b8effff`, `0x26d830000-0x271dfffff`, `0x272000000-0x27259ffff`; everything else up to `0x277ffffff` is `reserved`; nothing above `0x277ffffff` | `raw/orin-iomem.txt`, dmesg "Early memory node ranges" | VERIFIED |
| 5.3 | Therefore not usable by a payload: the 64 MiB hole `0xbe000000-0xc1ffffff`, the 128 KiB `0xfffe0000-0xffffffff`, the ~126 MiB `0x25f200000-0x266ffffff`, `0x26b8f0000-0x26d82ffff`, `0x271e00000-0x271ffffff` (bootloader profiling buffers per the kernel cmdline `bl_prof_*`), `0x272f00000-0x272ffffff`, `0x276000000-0x277ffffff`, and the top 128 MiB `0x278000000-0x27fffffff` that the map does not present at all. Who owns each (BPMP, SPE, TZDRAM/OP-TEE, GSC, UEFI runtime, DCE...) is **not** derivable from public data | 5.2 | VERIFIED (ranges) / UNKNOWN (owners) |
| 5.4 | `free -m` total 7619 MiB (~573 MiB of the 8 GiB is outside Linux) | `raw/orin-identity.txt` | VERIFIED |
| 5.5 | DT `reserved-memory`: `ramoops_carveout reg = <0x2 0x725f0000 0x0 0x200000>` (okay, no-map); `pva-carveout reg = <0x2 0x73180000 0x0 0x280000>` (okay, nomap); `linux,cma size 0x10000000` (256 MiB, placed at `0x24a000000`); `vpr-carveout`, `camdbg_carveout`, `framebuffer@0,0` disabled; `rce-reservation` (IOVA only); top-level `tegra-carveouts { compatible = "nvidia,carveouts"; memory-region = ...; }` | `raw/orin-devicetree.txt`, `raw/orin-uefi-dmesg.txt` | VERIFIED |
| 5.6 | NVIDIA names for MB1/MB2-BCT carveouts on Orin Nano/NX: `CARVEOUT_DCE` (32 MB), `CARVEOUT_DISP_EARLY_BOOT_FB` (34 MB), `CARVEOUT_CAMERA_TASKLIST` (32 MB), `CARVEOUT_RCE` (1 MB), `CARVEOUT_DCE_TSEC` (1 MB), `CARVEOUT_TSEC_DCE` (1 MB); configured in `tegra234-mb1-bct-misc-p3767-0000.dts` / `tegra234-mb2-bct-common.dtsi` | https://developer.nvidia.com/blog/maximizing-memory-efficiency-to-run-bigger-models-on-nvidia-jetson/ | VENDOR_CLAIM |
| 5.7 | MB1 log tasks `Carveout allocate`, `Carveout setup` — carveouts are placed by MB1 and described to UEFI through the CPU-BL parameter blob (edk2 `T234_BL_CARVEOUT_OFFSET_V0/V1/V2 = 0x588/0x10F8/0x11B8`, `DramCarveoutLib`), which UEFI turns into its memory map | OE4T #1714, forum 210971; `T234Definitions.h`; edk2 Library listing | VENDOR_CLAIM (logs) / VERIFIED (edk2 names) / mechanism HYPOTHESIS |
| 5.8 | **Recommendation:** the startup should take RAM from the UEFI memory map (`init_raminfo_uefi` + `efi_walk_map`, present in libstartup per harvest-sdp §3a) and treat everything not `EfiConventionalMemory` as `avoid_ram`, instead of `add_ram(0x80000000, 8 GiB)`. `init_raminfo_fdt` is a fallback only if UEFI also passes the FDT (`linux,uefi-*` chosen props show it does) | 5.2-5.7, harvest-sdp | HYPOTHESIS (design guidance) |
| 5.9 | `sram@40000000 { compatible = "nvidia,tegra234-sysram", "mmio-sram"; reg = <0 0x40000000 0 0x80000>; }` with `cpu_bpmp_tx = sram@70000`, `cpu_bpmp_rx = sram@71000` (BPMP IVC rings, 4 KiB each) | `raw/orin-followup.txt` (reg hex, `__symbols__`); upstream v5.19 dtsi | VERIFIED |
| 5.10 | UEFI tables live in reserved DRAM: `RTPROP=0x26d82f198 ... SMBIOS 3.0=0x26d220000 MEMATTR=0x2671a6018 ESRT=0x2671e4d98 RNG=0x25a900018 MEMRESERVE=0x25e40ac18`; `linux,uefi-system-table = <0x2 0x6d820018>` | dmesg, chosen node | VERIFIED |

## 6. UARTs

### 6.1 Controllers present in the live DT (all others are absent from this DT)

| Node | Label | compatible (live) | reg | IRQ | clocks / resets | status | Linux |
|---|---|---|---|---|---|---|---|
| `serial@3100000` | `uarta` | `nvidia,tegra194-hsuart` | `0x03100000` 64 KiB | SPI 112 (`0x70`) | `<&bpmp 0x9b>` / `<&bpmp 0x64>` | okay | `ttyTHS1` (`TEGRA_UART`, irq 112) |
| `serial@3110000` | (uartb) | `nvidia,tegra234-uart`,`nvidia,tegra20-uart` | `0x03110000` | SPI 113 (`0x71`) | `<&bpmp 0x9c>` / `<&bpmp 0x65>` | **disabled** | — |
| `serial@3140000` | `uarte` | `nvidia,tegra194-hsuart` (+ `dmas`) | `0x03140000` | SPI 116 (`0x74`) | `<&bpmp 0x9f>` / `<&bpmp 0x68>` | okay | `ttyTHS2` |
| `serial@31d0000` | `uarti` | `arm,sbsa-uart`, `current-speed = <115200>` | `0x031d0000` | SPI 285 (`0x11d`) | none | okay | `ttyAMA0` (PL011 SBSA, irq 117) |
| `/serial` | `tcu` | `nvidia,tegra234-tcu`,`nvidia,tegra194-tcu` | none (mailboxes) | — | — | okay | `ttyTCU0` = **console** |

Source: `raw/orin-devicetree.txt`, `raw/orin-ttys.txt`, `raw/orin-followup.txt` — VERIFIED.
Upstream `tegra234.dtsi` (master) describes only `uarta`, `uarte` (`nvidia,tegra234-uart`,
`nvidia,tegra20-uart`, SPI 112 / 116, `TEGRA234_CLK_UARTA/E`, `TEGRA234_RESET_UARTA/E`)
and `uarti` (`arm,sbsa-uart`, SPI 285) — VERIFIED (source). Addresses for uartc/d/f/g/h
were **not** found in any public DT; the "0x03100000 ... 0x031d0000" family in the task
brief is therefore only partly confirmed (a/b/e/i) — the rest is UNKNOWN. Note uartc is
*not* in that range: it is the AON UART at `0x0c280000` (6.4).

### 6.2 Register model and QNX callouts

| # | Fact | Source | Class |
|---|---|---|---|
| 6.2.1 | `nvidia,tegra20-uart` = 16550-class with 32-bit registers at 4-byte stride: upstream `8250_tegra.c` sets `port->iotype = UPIO_MEM32; port->regshift = 2; port->type = PORT_TEGRA;` and enables `devm_clk_get()` + `reset_control_deassert()` at probe | https://raw.githubusercontent.com/torvalds/linux/master/drivers/tty/serial/8250/8250_tegra.c | VERIFIED (code) |
| 6.2.2 | QNX `callout_debug_tegra.o` (`display_char_tegra`, `poll_key_tegra`, `break_detect_tegra`; source comment "Similar to 8250 uart with 32-bit registers", THR at `+0x00`, LSR at `+0x14` = `5 << 2`) matches that model; there is no `hw_sertegra` init, so pair it with `init_8250_32b`-style init or trust the firmware/previous-boot line settings | harvest-sdp §3a | VERIFIED (names/source) / pairing HYPOTHESIS |
| 6.2.3 | `uarti` is an SBSA Generic UART (PL011 register subset, baud fixed by firmware — no `clocks`/`resets` in the DT, `current-speed` only); Linux probed it (`31d0000.serial: ttyAMA0 at MMIO 0x31d0000 ... is a SBSA`). QNX `callout_debug_pl011` / `hw_serpl011` should drive it **if** the SPE/firmware left it clocked; that is not verified, and there is no `callout_debug_sbsa` in libstartup | `raw/orin-ttys.txt`; harvest-sdp §3a | VERIFIED (probe) / HYPOTHESIS (QNX use) |
| 6.2.4 | **Clock/reset dependency:** `uarta`/`uarte` clocks and resets are BPMP-provided (`&bpmp` = phandle `0x03`; ids 0x9b/0x64 and 0x9f/0x68). There is no CPU-side clock controller node in the DT. Whether MB2/UEFI leave `uarta` clocked and out of reset when a non-Linux payload starts is not documented; Linux enables it itself. Options: (a) implement BPMP MRQ_CLK/MRQ_RESET over IVC (SysRAM + hsp_top0 doorbell — sizeable), (b) rely on residual state, (c) use `uarti` or the TCU mailbox (§7), which need no clock work | DT; 6.2.1 | VERIFIED (dependency) / UNKNOWN (state at handoff) |
| 6.2.5 | edk2-nvidia's 16550 fallback for T234 is `PcdSerialRegisterBase|0x0C280000` — i.e. UEFI's own "raw UART" path targets the AON debug UART (`uartc`), not `uarta` | NVIDIA.common.dsc.inc | VERIFIED (source) |
| 6.2.6 | ACPI `SPCR` is not available on this DT-booted board (no ACPI tables in `/sys/firmware`), so QNX `acpi_spcr_parse` (PL011-only) cannot be used to discover the console | `raw/orin-firmware-el.txt` (`ls /sys/firmware/efi` only) | VERIFIED (absence) |

### 6.3 Physical routing on the P3768 carrier (SP-11324-001 v1.0, March 2023)

| Header / connector | Signal | Module pin | SoC pad | SoC controller | Source | Class |
|---|---|---|---|---|---|---|
| **J12 40-pin** pin 8 | `UART1_TXD` (3.3 V) | 203 | `PR.02` (`GP70_UART1_TXD_BOOT2_STRAP`) | `uarta @ 0x03100000` (`ttyTHS1`; DT alias `serial1 = uarta`) | carrier spec Table 3-3 (p. 21-22); jetson-gpio table; DT aliases | VENDOR_CLAIM (pad) + VERIFIED (alias) |
| J12 pin 10 | `UART1_RXD` | 205 | `PR.03` (`GP71_UART1_RXD`) | `uarta` | same | VENDOR_CLAIM |
| J12 pin 11 / 36 | `UART1_RTS*` / `UART1_CTS*` | 207 / 209 | `PR.04` / `PR.05` | `uarta` | same | VENDOR_CLAIM |
| **J14 12-pin button header** pin 4 | `UART2_TXD (DEBUG)` (3.3 V) | 236 | not printed; the module's debug UART | **Tegra Combined UART** (SPE-muxed; physical `uartc @ 0x0c280000`) | carrier spec Table 3-4 (p. 24); KevinFFF 2025-09-30 (thread 346157): J14 is the debug/Combined UART; KevinFFF 2026-05-18 (thread 370278): no `uartc: serial@c280000` in JP6 source; 6.2.5 | VENDOR_CLAIM |
| J14 pin 3 | `UART2_RXD (DEBUG)` | 238 | — | TCU | same | VENDOR_CLAIM |
| J14 pins 7/8, 9/10, 11/12 | GND/`SYS_RESET*`(239), GND/`FORCE_RECOVERY*`(214), GND/`SLEEP/WAKE*`(240); pins 1/2 `PC_LED-/+` (external sleep/wake LED, 5 V); pins 5/6 auto-power-on disable | — | — | — | carrier spec Table 3-4 | VENDOR_CLAIM |
| **M.2 Key E (J10)** pins 22/32/34/36 | `UART0_RXD/TXD/CTS*/RTS*` (1.8 V) | 101/99/105/103 | — | UNKNOWN (plausibly `uarte`/`ttyTHS2`, the DMA-capable one used for Bluetooth) | carrier spec §2.4 (p. 12-13) | VENDOR_CLAIM (routing) / HYPOTHESIS (controller) |
| `uarti` (SBSA) | — | — | — | enabled and probed, but no carrier-spec signal maps to it. On AGX Orin, UARTI goes to the micro-USB debug port (ghaf docs); on Orin Nano its pins are **unknown** — a search-engine summary said UARTI/UARTJ are pin-muxed with UARTE/UARTC, unverified | https://ghaf.tii.ae/ghaf/dev/technologies/nvidia_uarti_net_vm/ ; https://forums.developer.nvidia.com/t/uart-ttyama0/238108 (not fetched) | UNKNOWN |

Naming caveats: NVIDIA's *Board Automation* doc (r36.4.4) describes the same J14 pins
3/4 as "Jetson UART2 TXD/RXD" and calls the console "physically connected to UART3 (the
debug UART)" — module-signal numbering (UART2) and SoC pad-group numbering (UART3) differ;
I take "UART3" to be the AON `PCC.*` pad group = `uartc`, but that is HYPOTHESIS.
KevinFFF's 2023-10-03 answer in thread 267944 ("only one UART (UART1) on 40-pin header")
also states UART2 goes to M.2 Key E, which contradicts the carrier spec (UART0 -> M.2 E,
UART2 -> J14); the spec is the primary document and is used here.

## 7. HSP mailboxes and the Tegra Combined UART (TCU)

| # | Fact | Source | Class |
|---|---|---|---|
| 7.1 | `hsp_top0 = hsp@3c00000`: `nvidia,tegra234-hsp`,`nvidia,tegra194-hsp`; `reg = <0 0x03c00000 0 0xa0000>`; `#mbox-cells = 2`; interrupts `doorbell` = SPI 176 (`0xb0`), `shared0..7` = SPI 120..127 (`0x78..0x7f`), all level-high | `raw/orin-devicetree.txt`, `raw/orin-followup.txt` (raw hex) | VERIFIED |
| 7.2 | `hsp_aon = hsp@c150000`: same compatibles; `reg = <0 0x0c150000 0 0x90000>`; `shared1..4` = SPI 133..136 (`0x85..0x88`). Also `hsp_top1 @ 0x03d00000` (0xa0000, okay), `hsp_top2 @ 0x01600000` (disabled), `hsp_rce = tegra-hsp@b950000` (`nvidia,tegra186-hsp`, 0x90000) | same | VERIFIED |
| 7.3 | TCU node `mboxes = <&hsp_top0 1 0x0>, <&hsp_aon 1 0x80000001>; mbox-names = "rx", "tx"` -> RX = hsp_top0 **shared mailbox 0**, TX = hsp_aon **shared mailbox 1** (type `TEGRA_HSP_MBOX_TYPE_SM = 1`, `TEGRA_HSP_SM_FLAG_TX = 1<<31`, from the on-board `dt-bindings/mailbox/tegra186-hsp.h`) | `raw/orin-followup.txt` | VERIFIED |
| 7.4 | Upstream v5.19 `tegra234.dtsi` spells it `mboxes = <&hsp_top0 TEGRA_HSP_MBOX_TYPE_SM TEGRA_HSP_SM_RX(0)>, <&hsp_aon TEGRA_HSP_MBOX_TYPE_SM TEGRA_HSP_SM_TX(1)>` | https://raw.githubusercontent.com/torvalds/linux/v5.19/arch/arm64/boot/dts/nvidia/tegra234.dtsi | VERIFIED (source) |
| 7.5 | Linux `tegra-hsp.c`: shared mailbox *i* registers at `hsp->regs + SZ_64K + i * SZ_32K`; `HSP_SM_SHRD_MBOX 0x0`, `HSP_SM_SHRD_MBOX_FULL BIT(31)`, `..._FULL_INT_IE 0x04`, `..._EMPTY_INT_IE 0x08`; 32-bit send = `value |= HSP_SM_SHRD_MBOX_FULL; writel(value, HSP_SM_SHRD_MBOX)`; flush polls until `(value & FULL) == 0` with `udelay(1)`; `HSP_INT_DIMENSIONING 0x380` gives nSM/nSS/nAS/nDB/nSI (4-bit fields at shifts 0/4/8/12/16); doorbells at `(1 + nSM/2 + nSS + nAS) * SZ_64K + index * 0x100`; tegra234 soc data `has_128_bit_mb = true`, `has_per_mb_ie = false` (128-bit path uses `TYPE1_TAG 0x40`, `DATA0..3 0x48..0x54`; the TCU uses the 32-bit path) | https://raw.githubusercontent.com/torvalds/linux/master/drivers/mailbox/tegra-hsp.c | VERIFIED (code) |
| 7.6 | Hence TX mailbox = `0x0c150000 + 0x10000 + 1*0x8000` = **`0x0c168000`**; RX mailbox = `0x03c00000 + 0x10000 + 0` = **`0x03c10000`** | arithmetic on 7.2/7.3/7.5 | VERIFIED (derivation) |
| 7.7 | Independent confirmation: edk2-nvidia `Platform/NVIDIA/Kconfig` `DEBUG_SERIAL_PORT_TCU_TX_MAILBOX default 0x0C168000`, `DEBUG_SERIAL_PORT_TCU_RX_MAILBOX default 0x03C10000`, fed into `PcdTegraCombinedUartTxMailbox`/`RxMailbox` (`NVIDIA.dec` tokens 0x2/0x1, `UINT64`) | https://raw.githubusercontent.com/NVIDIA/edk2-nvidia/main/Platform/NVIDIA/Kconfig ; NVIDIA.common.dsc.inc ; Silicon/NVIDIA/NVIDIA.dec | VERIFIED (source) |
| 7.8 | Word format, Linux `tegra-tcu.c`: `TCU_MBOX_BYTE(i,x) = x << (i*8)`, `TCU_MBOX_NUM_BYTES(x) = x << 24` (2-bit count, max 3 bytes per word); driver converts `\n` to `\r\n`, sends via `mbox_send_message()` then `mbox_flush(tx, 1000)`; the HSP driver adds bit 31 | https://raw.githubusercontent.com/torvalds/linux/master/drivers/tty/serial/tegra-tcu.c | VERIFIED (code) |
| 7.9 | Word format, UEFI `TegraCombinedSerialPortLib.c`: `struct { UINT8 Data[3]; UINT8 NumberOfBytes:2; BOOLEAN Flush:1; BOOLEAN HwFlush:1; UINT8 Reserved:3; BOOLEAN Interrupt:1; }` unioned with a `UINT32 RawValue`; writer packs up to 3 bytes, `MmioWrite32(TxMailbox, RawValue)`, then `while (IsDataPresent(TxMailbox) == TRUE) {}` where `IsDataPresent` returns the `Interrupt` bit (bit 31) — a busy-wait with **no timeout** | https://raw.githubusercontent.com/NVIDIA/edk2-nvidia/main/Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c | VERIFIED (code) |
| 7.10 | Who consumes it: NVIDIA TCU doc — the multiplexing runs in the Sensor Processing Engine (SPE, the AON Cortex-R5) on Orin; `nv_tcu_demuxer` on the host splits the streams. The SPE owns the physical UART; the CCPLEX never touches `uartc` | https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html ; module datasheet p. 13 (SPE = AON Cortex-R5) | VENDOR_CLAIM |
| 7.11 | **Proposed polled QNX callout (untested):** map `0x0c168000` (4 KiB is enough), then per chunk: spin while `bit31` set; write `(1u<<31) | (n<<24) | b0 | b1<<8 | b2<<16` (n = 1..3). UEFI does precisely this from EL2 pre-OS, so the CCPLEX has write access through the firewall and the SPE is already forwarding at handoff. Risks: (a) a hang if the SPE stops draining (UEFI has no timeout either — QNX should add one), (b) firmware log noise is interleaved by design, (c) polling RX at `0x03c10000` for input is undocumented beyond the Linux driver | 7.5-7.10; harvest-sdp §3a (`callout_debug_*` shape) | HYPOTHESIS |
| 7.12 | Using `ttyTCU0`/J14 as a *normal* UART is unsupported: KevinFFF, 2024-04 (thread 287340) and 2026-05-18 (thread 370278): the debug UART carries MB1/MB2/UEFI/BPMP logs, and the `uartc` node was removed from JP6 sources | https://forums.developer.nvidia.com/t/enabling-ttytcu0-as-regular-uart-on-orin-nano/287340 ; https://forums.developer.nvidia.com/t/using-debug-uart-dev-ttytcu0-as-normal-dev-ttyths0-uart/370278 | VENDOR_CLAIM |
| 7.13 | BPMP IPC on the same HSP: `bpmp { mboxes = <&hsp_top0 TEGRA_HSP_MBOX_TYPE_DB TEGRA_HSP_DB_MASTER_BPMP>; shmem = <&cpu_bpmp_tx>, <&cpu_bpmp_rx>; }` — a startup that never rings that doorbell leaves the BPMP untouched (safe); one that wants clocks must implement IVC + MRQ | upstream v5.19 dtsi; board `bpmp` node has `mboxes`, `shmem` | VERIFIED |

## 8. PMC, reset, and other "do not touch" paths

| # | Fact | Source | Class |
|---|---|---|---|
| 8.1 | `pmc@c360000 { compatible = "nvidia,tegra234-pmc"; }`; upstream `reg` = five 64 KiB windows `0x0c360000` (pmc), `0x0c370000` (wake), `0x0c380000` (aotag), `0x0c390000` (scratch), `0x0c3a0000`; `/proc/iomem` maps the first four under those names | upstream dtsi; `raw/orin-iomem.txt` | VERIFIED |
| 8.2 | edk2: `T234_SCRATCH_BASE 0x0C390000`, `T234_BL_VERSION_OFFSET 64`, `T234_BL_CARVEOUT_OFFSET_V0/1/2` — UEFI reads bootloader hand-off data through PMC scratch. Do not write scratch | `T234Definitions.h` | VERIFIED (source) |
| 8.3 | Linux `pmc.c` reboot-reason bits in `scratch0`: `PMC_SCRATCH0_MODE_RECOVERY BIT(31)`, `PMC_SCRATCH0_MODE_BOOTLOADER BIT(30)`, `PMC_SCRATCH0_MODE_RCM BIT(1)` (`tegra_pmc_program_reboot_reason`); whether the tegra234 SoC data routes through this was cut off by the fetch size limit | https://raw.githubusercontent.com/torvalds/linux/master/drivers/soc/tegra/pmc.c (truncated) | VERIFIED (bits) / UNKNOWN (t234 wiring) |
| 8.4 | Reset/off should go through PSCI `SYSTEM_RESET`/`SYSTEM_OFF` (TF-A owns the PMC/BPMP reset path); QNX has `reboot_psci_smc` | harvest-sdp §3a; 2.1 | VERIFIED (callout exists) / HYPOTHESIS (policy) |
| 8.5 | Clocks/resets/power domains: all `clocks = <&bpmp ...>`, `resets = <&bpmp ...>`, `power-domains = <&bpmp ...>`; no CAR node visible to the CPU -> never poke clock/reset registers directly | `raw/orin-devicetree.txt` (chosen framebuffer, serial nodes, mc) | VERIFIED |
| 8.6 | SysRAM `0x40070000-0x40071fff` (BPMP IVC), MCE ARI apertures `tegra_mce@e100000` (12 x 64 KiB at `0x0e100000 + n*0x10000`, node disabled), memory controller `0x02c00000..`, fabrics (`cbb-fabric@13a00000`, `aon-fabric@c600000`, `bpmp-fabric@d600000`...), `misc@100000` (chip id/straps), `fuse@3810000` — leave untouched | `raw/orin-followup.txt` (mce reg hex), iomem | VERIFIED (existence) |
| 8.7 | MB1/MB2 BCT knobs that change firmware behaviour (`enable_wdt`, `disable_wdt_globally`, carveouts, pinmux) are flashed — out of scope for a payload; do not reflash for this port (repo rule) | KevinFFF 2026-07-02 thread 374551 | VENDOR_CLAIM |

## 9. Watchdog

| # | Fact | Source | Class |
|---|---|---|---|
| 9.1 | L4T public DT (`nv-soc/tegra234-soc-overlay.dtsi`, branch `patches-rel-36`): `watchdog@2190000 { compatible = "nvidia,tegra-wdt-t234"; reg = <0x0 0x02190000 0x0 0x10000> /* WDT0 */, <0x0 0x02090000 0x0 0x10000> /* TMR0 */, <0x0 0x02080000 0x0 0x10000> /* TKE */; interrupts = <0 7 0x4 0 8 0x4>; nvidia,watchdog-index = <0>; nvidia,timer-index = <7>; nvidia,enable-on-init; nvidia,extend-watchdog-suspend; timeout-sec = <120>; nvidia,disable-debug-reset; status = "disabled"; }` | https://raw.githubusercontent.com/OE4T/t23x-public-dts/patches-rel-36/nv-soc/tegra234-soc-overlay.dtsi | VERIFIED (source) |
| 9.2 | The live board DT has `bus@0/watchdog@2190000`; its `status` was not captured by H3 | `raw/orin-devicetree.txt` (bus@0 child list) | VERIFIED (node) / UNKNOWN (status) |
| 9.3 | KevinFFF, 2024-02-06 (Orin Nano thread): watchdog enabled by default, fires after 120 s; `/dev/watchdog` (10,130), driver `tegra_wdt_t18x` | https://forums.developer.nvidia.com/t/device-stuck-after-several-weeks-watchdog/281074 | VENDOR_CLAIM |
| 9.4 | Register model (upstream `timer-tegra186.c`, same IP): per-WDT `WDTCR 0x0` (period, local/remote IRQ, system POR/debug reset enables, timer source), `WDTSR 0x4` (expiry count), `WDTCMDR 0x8` (start / disable), `WDTUR 0xc` unlock pattern `0x0000c45a`; `TKEIE(x) = 0x100 + 4x` at the TKE base; period programmed as timeout/5, reset on the 5th expiry; default 120 s, max 255 s; the driver reserves "the first accessible WDT" for the kernel; no firmware pre-arming is mentioned in the code | https://raw.githubusercontent.com/torvalds/linux/master/drivers/clocksource/timer-tegra186.c | VERIFIED (code) |
| 9.5 | Firmware behaviour from posted MB1/MB2 logs: `I> Task: Enable WDT 5th expiry`, later `Task: Disable WDT globally`, `Task: Disable/Reload WDT` — MB1 arms a WDT for its own run and disables/reloads it before handing off | https://github.com/orgs/OE4T/discussions/1714 ; https://forums.developer.nvidia.com/t/the-system-stops-between-mb2-and-uefi/210971 | VENDOR_CLAIM (posted logs, R35.x AGX/NX) |
| 9.6 | MB1 BCT: `enable_wdt=1` makes MB1 explicitly program the watchdog; `disable_wdt_globally = <1>` exists; a "Re-Enabling WDT" message shows something is armed before MB1 (KevinFFF 2026-07-02) | https://forums.developer.nvidia.com/t/watchdog-configuration-in-mb1-mb2/374551 | VENDOR_CLAIM |
| 9.7 | UEFI: the default boot watchdog is a **software** timer (`BootWatchdog.c`, UEFI events) with `CONFIG_BOOT_WATCHDOG_TIMEOUT default 5` (minutes); the CCPLEX HW WDT at `0x02190000` is not mapped by UEFI by default and `GenericWatchdogDxe` (SBSA) is incompatible with it (KevinFFF 2026-07-01) | https://forums.developer.nvidia.com/t/uefi-watchdog/374662 ; Platform/NVIDIA/Kconfig | VENDOR_CLAIM / VERIFIED (Kconfig default) |
| 9.8 | edk2 DXE core `CoreExitBootServices()` executes `gTimer->SetTimerPeriod (gTimer, 0);` ("Disable Timer") — the UEFI event-driven watchdog cannot fire after ExitBootServices | https://raw.githubusercontent.com/tianocore/edk2/master/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c | VERIFIED (code) |
| 9.9 | Net: no public evidence that a CCPLEX hardware WDT is counting when a UEFI-loaded, non-Linux payload starts; the 120 s reset seen under L4T is the **kernel driver's** own arming. Not verified on this board. Cheapest check: read `WDTCR`/`WDTSR` at `0x02190000` (and WDT1 at `0x021a0000`) early in `startup` before touching anything; if armed, either kick (QNX BSP ships `wdtkick`, harvest-sdp §5) or write `WDTUR=0xc45a` then `WDTCMDR` disable — note the L4T DT sets `nvidia,disable-debug-reset`, and a firmware-locked WDT (`WDTSCR`) cannot be disabled from NS-EL1/EL2 | 9.1-9.8 | HYPOTHESIS / UNKNOWN |
| 9.10 | Reset-source `0x13` is read by users as a WDT reset (Orin NX thread, Sept 2026); NVIDIA did not confirm | https://forums.developer.nvidia.com/t/jetson-orin-nx-randomly-resets-sys-reset-n-during-docker-yolo-inference-workload-hardware-watchdog-suspected/376440 (search summary only) | UNKNOWN |

## 10. SMMU

| # | Fact | Source | Class |
|---|---|---|---|
| 10.1 | The task brief's "SMMUv3s" premise is wrong for Tegra234: upstream `smmu_niso1: iommu@8000000 { compatible = "nvidia,tegra234-smmu", "nvidia,smmu-500"; reg = <0x8000000 0x1000000>, <0x7000000 0x1000000>; }`, `smmu_iso: iommu@10000000` (same compatible), and `iommu@12000000` (`0x11000000` + `0x12000000` in iomem) — three Arm **MMU-500 (SMMUv2)** instances, two of them programmed as a pair (`nvidia,smmu-500` binding) | upstream `tegra234.dtsi`; `raw/orin-iomem.txt`; kernel binding `arm,smmu.yaml` (search) | VERIFIED |
| 10.2 | MB2 runs `Task: SMMU external bypass disable`, `Task: SMMU init` before `Program GICv3 registers` (R35.5 Orin NX log) | OE4T #1714 | VENDOR_CLAIM |
| 10.3 | Bypass state for a stream that no OS driver has mapped (e.g. `uarte` DMA, PCIe) at handoff: not public. UEFI drives eMMC/NVMe/Ethernet before Linux, so either they are bypassed or UEFI programs the SMMU (edk2-nvidia has an `SmmuLib`) — unresolved. Irrelevant for a CPU-only, PIO-UART first boot | edk2 Library listing | UNKNOWN |

## 11. Sign-of-life without a UART: LEDs and the 40-pin GPIOs

### 11.1 On-board LED

| # | Fact | Source | Class |
|---|---|---|---|
| 11.1.1 | The carrier has one software-relevant LED: **DS1 "Power LED (Green)"** (top-view placement figure; feature list "LEDs: Power"); the block diagram powers it from the `GS7116S5 LDO 3V3_AO` rail. The red `VDD_IN` LED is a supply indicator. Ethernet jack LEDs are PHY-driven | carrier spec pp. 3-5, 31 | VENDOR_CLAIM |
| 11.1.2 | The power LED is controlled by module signal **`GPIO04`** = module pin **127** ("GPIO #4", CMOS 1.8 V) = Tegra **`PCC.01`**, an AON GPIO (`tegra234-gpio-aon`), Linux sysfs gpio **329**; NVIDIA (KevinFFF, 2023-11-10) confirmed it can be driven from sysfs; third-party summary calls it "Baseboard Power LED Control", LED near the USB ports | https://forums.developer.nvidia.com/t/how-to-use-the-orin-dev-kit-power-led-as-a-gpio/271991 ; module datasheet Table (p. 27, pin 127); https://nvidia-jetson.piveral.com/... (search summary) | VENDOR_CLAIM |
| 11.1.3 | AON GPIO controller: `gpio@c2f0000 { compatible = "nvidia,tegra234-gpio-aon"; reg = <0x0c2f0000 0x1000> /* security */, <0x0c2f1000 0x1000> /* gpio */; }`; iomem `0c2f1000-0c2f1fff : c2f0000.gpio gpio` | upstream dtsi; `raw/orin-iomem.txt` | VERIFIED |
| 11.1.4 | Upstream `gpio-tegra186.c`: `tegra234_aon_ports[] = { AA(0,4,8), BB(0,5,4), CC(0,2,8), DD(0,3,3), EE(0,0,8), GG(0,1,1) }` as `(bank, port, npins)`; pin base = `gpio_base + bank*0x1000 + port*0x200 + pin*0x20`; registers `ENABLE_CONFIG 0x00` (bit0 ENABLE, bit1 OUT), `DEBOUNCE 0x04`, `INPUT 0x08`, `OUTPUT_CONTROL 0x0c` (bit0 FLOATED), `OUTPUT_VALUE 0x10` (bit0 HIGH), `INTERRUPT_CLEAR 0x14` | https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpio/gpio-tegra186.c | VERIFIED (code) |
| 11.1.5 | Derived `PCC.01`: offset `0*0x1000 + 2*0x200 + 1*0x20 = 0x420` -> `ENABLE_CONFIG @ 0x0c2f1420`, `OUTPUT_CONTROL @ 0x0c2f142c`, `OUTPUT_VALUE @ 0x0c2f1430`. To drive: `ENABLE_CONFIG = 0x3` (enable + output), `OUTPUT_CONTROL = 0` (driven), toggle `OUTPUT_VALUE` bit 0. Linux gpio 329 = aon chip base 316 + port order (AA 0-7, BB 8-11, CC 12-19 -> CC.01 = 13) — consistent | arithmetic on 11.1.3/11.1.4 | HYPOTHESIS (untested) |
| 11.1.6 | Unknowns: LED polarity (whether 1 = on), whether the pinmux leaves PCC.01 in GPIO function at handoff (the LED is lit through boot, so *something* drives it high — plausibly the MB1 pinmux/GPIO default), and whether the AON GPIO "security" aperture restricts NS-EL1 writes (Linux at EL2 writes it fine) | — | UNKNOWN |

### 11.2 J14 external-LED pins (not software-drivable)

Pins 1/2 `PC_LED-/PC_LED+` are a 5 V sleep/wake indicator output from the carrier's
button/power logic ("Off when system in sleep mode"), not a CPU GPIO — carrier spec
Table 3-4 (VENDOR_CLAIM).

### 11.3 J12 40-pin header — GPIO-capable pins (carrier spec Table 3-3, cross-checked with NVIDIA `jetson-gpio`)

All header signals are 3.3 V (level-shifted from the module's 1.8 V pads). Main GPIO
controller `gpio@2200000` = `<0x02200000 0x10000>` (security) + `<0x02210000 0x10000>`
(gpio), `nvidia,tegra234-gpio`; per-pin registers as in 11.1.4 with
`tegra234_main_ports` `(bank, port)`: `G(4,0) H(4,1) I(4,2) N(2,1) P(2,2) Q(2,3) R(2,4)
Y(1,1) Z(1,2) AC(0,1)` (VERIFIED code). Pad names/ module pins: VENDOR_CLAIM.

| J12 pin | Signal | Module pin | Tegra pad | Default | Alt |
|---|---|---|---|---|---|
| 7 | GPIO09 | 211 | PAC.06 | pd | AUD_MCLK |
| 8 / 10 | UART1_TXD / RXD | 203 / 205 | PR.02 / PR.03 | pd | uarta |
| 11 / 36 | UART1_RTS* / CTS* | 207 / 209 | PR.04 / PR.05 | pd | uarta flow control |
| 12 | I2S0_SCLK | 199 | PH.07 | pd | |
| 13 | SPI1_SCK | 106 | PY.00 | pd | |
| 15 | GPIO12 | 218 | PN.01 | z | PWM1 (`3280000.pwm`) |
| 16 | SPI1_CS1* | 112 | PY.04 | z | |
| 18 | SPI1_CS0* | 110 | PY.03 (jetson-gpio; the spec's "PZ.06" here looks like a typo — PZ.06 is pin 24) | z | |
| 19 / 21 / 23 | SPI0_MOSI / MISO / SCK | 89 / 93 / 91 | PZ.05 / PZ.04 / PZ.03 | pd | |
| 22 | SPI1_MISO | 108 | PY.01 | pd | |
| 24 / 26 | SPI0_CS0* / CS1* | 95 / 97 | PZ.06 / PZ.07 | z / pu | |
| 27 / 28 | I2C0_SDA / SCL | 187 / 185 | PDD.00 / PCC.07 (AON) | 1.5 k PU | open-drain, i2c |
| 3 / 5 | I2C1_SDA / SCL | 191 / 189 | PDD.02 / PDD.01 (AON) | 2.2 k PU | open-drain |
| 29 | GPIO01 | 118 | PQ.05 | pd | generic clock 0 |
| 31 | GPIO11 | 216 | PQ.06 | pd | generic clock 1 |
| 32 | GPIO07 | 206 | PG.06 | z | PWM7 (`32e0000.pwm`) |
| 33 | GPIO13 | 228 | PH.00 | z | PWM5 (`32c0000.pwm`) |
| 35 / 38 / 40 | I2S0_FS / DIN / DOUT | 197 / 195 / 193 | PI.02 / PI.01 / PI.00 | pd | |
| 37 | SPI1_MOSI | 104 | PY.02 | pd | |
| 1, 17 / 2, 4 / 6, 9, 14, 20, 25, 30, 34, 39 | 3.3 V / 5 V / GND | — | — | — | — |

Sources: carrier spec Table 3-3 (pp. 21-22); https://raw.githubusercontent.com/NVIDIA/jetson-gpio/master/lib/python/Jetson/GPIO/gpio_pin_data.py (`JETSON_ORIN_NX_PIN_DEFS`, reused for Orin Nano). A bare-metal blink on e.g. pin 29 (`PQ.05`: `0x02210000 + 2*0x1000 + 3*0x200 + 5*0x20 = 0x022126a0`) is a HYPOTHESIS-level derivation like 11.1.5; it also assumes the pinmux BCT left the pad in GPIO function (the spec says all header pins default to GPIO — VENDOR_CLAIM).

## 12. Sources

Repo / sibling harvest (all redacted): `raw/orin-identity.txt`, `raw/orin-firmware-el.txt`,
`raw/orin-devicetree.txt`, `raw/orin-iomem.txt`, `raw/orin-ttys.txt`, `raw/orin-followup.txt`,
`raw/orin-uefi-dmesg.txt`, `raw/orin-bootconfig.txt`; `harvest-sdp.md`; `harvest-repo.md`;
`docs/orin-port.md`.

Upstream Linux (torvalds/linux, raw.githubusercontent.com):
`arch/arm64/boot/dts/nvidia/tegra234.dtsi` (master; the fetch tool truncates it, so the
tail nodes were read from the `v5.19` tag), `tegra234-p3767.dtsi`,
`tegra234-p3768-0000+p3767.dtsi`, `tegra234-p3768-0000+p3767-0000.dts`,
`drivers/mailbox/tegra-hsp.c`, `drivers/tty/serial/tegra-tcu.c`,
`drivers/tty/serial/8250/8250_tegra.c`, `drivers/clocksource/timer-tegra186.c`,
`Documentation/devicetree/bindings/timer/nvidia,tegra186-timer.yaml`,
`drivers/gpio/gpio-tegra186.c`, `drivers/soc/tegra/pmc.c` (truncated).

edk2 / edk2-nvidia: `tianocore/edk2 MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c`;
`NVIDIA/edk2-nvidia` `Silicon/NVIDIA/Include/Tegra/T234/T234Definitions.h`,
`Platform/NVIDIA/NVIDIA.common.dsc.inc`, `Platform/NVIDIA/Kconfig`,
`Silicon/NVIDIA/NVIDIA.dec`,
`Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.{c,inf}`,
directory listings via `api.github.com`.

L4T public DT mirror: `OE4T/t23x-public-dts` branch `patches-rel-36`:
`nv-soc/tegra234-soc-overlay.dtsi`, `nv-soc/tegra234-overlay.dtsi`,
`nv-platform/tegra234-p3768-0000+p3767-xxxx-nv-common.dtsi`,
`nv-platform/tegra234-p3767-0000.dtsi`, `nv-platform/tegra234-p3768-0000.dtsi`.

NVIDIA documents: *Jetson Orin Nano Developer Kit Carrier Board Specification*
SP-11324-001_v1.0 (March 2023; mirror https://gzhls.at/blob/ldb/d/a/7/6/f487430a9edf313e0aea8393ee3caf5a805c.pdf);
*Jetson Orin Nano Series Data Sheet* DS-11105-001_v1.1 (April 2023; mirror
https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/5380/Jetson_Orin_Nano_Series_DS-11105-001_v1.1.pdf);
https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html ;
https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/BoardAutomation.html ;
https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/hardware_layout.html ;
https://developer.nvidia.com/blog/maximizing-memory-efficiency-to-run-bigger-models-on-nvidia-jetson/ ;
https://raw.githubusercontent.com/NVIDIA/jetson-gpio/master/lib/python/Jetson/GPIO/gpio_pin_data.py .

NVIDIA developer forums (staff answers by KevinFFF / JerryChang unless noted):
https://forums.developer.nvidia.com/t/enabling-ttytcu0-as-regular-uart-on-orin-nano/287340 ;
https://forums.developer.nvidia.com/t/orin-nano-uart2-with-dev-kit-carrier-board/267944 ;
https://forums.developer.nvidia.com/t/jetson-orin-nano-devkit-no-data-on-dev-ttyths2-uart2-at-j14/346157 ;
https://forums.developer.nvidia.com/t/using-debug-uart-dev-ttytcu0-as-normal-dev-ttyths0-uart/370278 ;
https://forums.developer.nvidia.com/t/how-to-use-the-orin-dev-kit-power-led-as-a-gpio/271991 ;
https://forums.developer.nvidia.com/t/watchdog-configuration-in-mb1-mb2/374551 ;
https://forums.developer.nvidia.com/t/device-stuck-after-several-weeks-watchdog/281074 ;
https://forums.developer.nvidia.com/t/uefi-watchdog/374662 ;
https://forums.developer.nvidia.com/t/orin-reset-by-wdt/381888 ;
https://forums.developer.nvidia.com/t/arm-trusted-firmware-fork/280681 ;
https://forums.developer.nvidia.com/t/the-system-stops-between-mb2-and-uefi/210971 (posted MB1 log).

Third-party: https://github.com/orgs/OE4T/discussions/1714 (posted R35.5 MB1/MB2/BL31/UEFI log);
https://proventusnova.com/blog/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel ;
https://developerwiki.proventusnova.com/How_to_NVIDIA_Jetson_Orin_Nano_UART_Console ;
https://ghaf.tii.ae/ghaf/dev/technologies/nvidia_uarti_net_vm/ ;
https://jetsonhacks.com/nvidia-jetson-orin-nano-gpio-header-pinout/ ;
https://developer.ridgerun.com/wiki/index.php/NVIDIA_Jetson_Orin_Nano/In_Board/Getting_in_Board/Serial_Console .

Not reachable / not attempted: Tegra234 TRM (login-gated, not attempted);
https://uefi.org/specs/UEFI/2.10/07_Services_Boot_Services.html returned HTTP 403 (the
ExitBootServices watchdog point was taken from the edk2 DXE core source instead).

## 13. Open unknowns (carried into the structured output)

1. Whether any CCPLEX hardware watchdog (TKE WDT0/WDT1) is armed at the moment UEFI hands
   control to a non-Linux payload. Public logs show MB1 arming then disabling its own;
   UEFI's is software-only. Needs a read of `0x02190000` on the board.
2. Owner and exact extent of the DRAM holes (`0xbe000000-0xc1ffffff`, top 128 MiB) — use
   the UEFI memory map instead of guessing.
3. Whether `uarta`'s BPMP clock/reset are left enabled at handoff (no doc); the TCU
   mailbox and `uarti` are the clock-free alternatives.
4. Physical pins (if any) of `uarti` on the P3768 carrier.
5. SoC controller behind the module's `UART0` -> M.2 Key E (probably `uarte`).
6. GIC implementation identity (GIC-600?) and whether an ITS exists in silicon.
7. SMMU bypass state for unmapped streams at handoff.
8. Power-LED polarity and pinmux function of `PCC.01` at handoff; AON GPIO security
   aperture behaviour for NS-EL1.
9. Whether QNX `gic_v3_set_paddr_range()` tolerates the unpopulated GICR frames 4-5 and
   8-15 (needs a code read of the Apache-2.0 `gic_v3.c` — not done in this task).
10. TF-A (BL31) version shipped with R36.4.7 on this board.
