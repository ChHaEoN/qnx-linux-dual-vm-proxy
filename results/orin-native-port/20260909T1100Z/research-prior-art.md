# R5 — Prior art: non-Linux kernels / hypervisors natively on Jetson Orin (and Xavier), plus TCU implementations outside Linux

Task R5 of the 2026-09-09 native-port sweep. Research agent output; read-only towards
the repo, no board writes, no package installs. All web sources accessed 2026-09-09.

Evidence classes used throughout:

- **VERIFIED** — I saw it: a source file line, a live-board capture in `raw/`, a directory listing fetched today.
- **VENDOR_CLAIM** — a vendor doc, project README, forum staff reply, or press item says so; not reproduced here.
- **HYPOTHESIS** — reasoned from the above, untested.
- **UNKNOWN** — looked, found nothing usable; absence of evidence, not evidence of absence.

Method limits (declare up front): `gh` is not installed on this host, so GitHub **code**
search was unavailable — repository-level web search only. `patchwork.kernel.org`,
`lore.kernel.org` and `wiki.freebsd.org` are behind Anubis (HTTP 403) and could not be
read; xen-devel content came from `lists.xenproject.org` / `mail-archive.com` mirrors.
NVIDIA's `nv-tegra` gitiles (nv-optee) did not respond. YouTube searches for
Xen/seL4/Zephyr/bare-metal on Orin returned nothing on-topic. Quotes are kept to
fewer than 15 words per external page.

---

## 0. Bottom line

1. **No one has publicly demonstrated a non-Linux kernel or a non-KVM hypervisor
   booting natively on any Jetson Orin (Tegra234).** Every Orin item below is a claim
   without a log (meta-xen), a failed attempt with a log (Jailhouse on AGX Orin), or a
   proprietary OS that reaches the board through the generic UEFI/ACPI path (Windows
   11 ARM on AGX Orin; Fedora/RHEL). Nothing at all for Orin **Nano** beyond
   auto-generated troubleshooting pages.
2. **The closest real prior art is one generation back:** Xen (2016–2017, dom0 +
   guests on TK1/TX1/Pixel C, never merged), seL4 (TX1/TX2 supported, CAmkES VMs on
   TX2), Bao (TX2 platform in tree), Jailhouse (TX1/TX2 configs in tree). All of them
   use **U-Boot** as loader and the **8250-class UART at `0x03100000`** as console —
   never the TCU. None reaches Xavier in tree; two Jailhouse forks *claim* Xavier.
3. **QNX on Jetson:** NVIDIA has said "no" in writing at least six times
   (2019, 2020, 2023, 2024, 2025, 2026-02). QNX does run natively on Tegra234-class
   silicon — but only as DRIVE OS QNX for DRIVE AGX Orin, obtained through an NVIDIA
   representative, single guest OS, BSP not public. No student/university/GitHub QNX
   port to any Jetson was found.
4. **TCU outside Linux — two licence-clean implementations exist and agree on the
   protocol:** edk2-nvidia `TegraCombinedSerialPortLib` (BSD-2-Clause-Patent, TX+RX,
   per-platform PCD mailbox addresses) and TF-A `plat/nvidia/tegra/drivers/spe/shared_console.S`
   (BSD-3-Clause, TX only, t194). The live Orin Nano DT shows the TCU node bound to
   **32-bit shared mailboxes** (RX index 0 on one HSP block, TX index 1 on another),
   i.e. the same word format both BSD sources implement. This is the one genuinely
   reusable asset this sweep found for the console problem.
5. **Loader path is proven for foreign PE images on AGX Orin** (Windows `bootmgfw.efi`
   via UEFI + ACPI, Hyper-V working ⇒ Windows got EL2). Not proven on Orin Nano.
   GRUB-as-BOOTAA64.efi is community-proven on Orin Nano (Linux payload).

---

## 1. Jetson Orin (Tegra234) — every item found

| # | Project / OS | Board | Loader | Console | EL obtained | What worked | What broke | Evidence | Licence of reusable code | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| O1 | **Xen 4.18 via Yocto `meta-xen`** (KPGURAV10) | Orin Nano (README) | extlinux entry read by L4TLauncher, "UEFI (Recommended)" option also described | `dtuart=serial8250,mmio,0x3100000` — i.e. **uarta**, not the TCU; dom0 `console=hvc0` | not stated | **Nothing evidenced.** README is instructional; no boot log, no dom0 output, no `xl info` | No failure reported either — because no run is reported | **VENDOR_CLAIM (README)**; repo facts VERIFIED: 2 commits, both "Add files via upload", 2025-05-20, 7 stars, MIT | MIT (layer only; contains `xen_%.bbappend`, `xen-tools_%.bbappend`, a `xen-tegra-boot-fix.bb` recipe with `files/`; no Xen source patch visible in the listing) | https://github.com/KPGURAV10/meta-xen |
| O2 | **Jailhouse on AGX Orin** (carzacc gist, "Kernel hacking project notes") | AGX Orin devkit 32 GB | extlinux config (gist summary says U-Boot; on Orin that is L4TLauncher reading `extlinux.conf` — HYPOTHESIS) | micro-USB debug port, `minicom -D /dev/ttyACM0` (host side; that port is the TCU on AGX Orin) | Linux itself at EL2 (see O6); Jailhouse never got control | L4T 5.10.104 kernel + `jailhouse-enabling/5.10` patches compiled (needed `CONFIG_MODVERSIONS` off); hypervisor memory reserved at `0x80000000` size `0x04000000` | `jailhouse enable` → "Bad mode in Synchronous Abort handler … HVC (AArch64)" on every CPU → kernel panic. Last update 2023-10-03, incomplete | **VERIFIED (gist text)** for the crash; cause is HYPOTHESIS: Jailhouse's enable path uses the kernel hyp-stub and expects Linux at EL1 — under VHE Linux *is* EL2, so HVC has no stub to land in (a `kvm-arm.mode=nvhe`/`id_aa64mmfr1.vh=0`-style boot would be the thing to try, untested) | GPL-2.0 (Jailhouse) | https://gist.github.com/carzacc/0fb09a00daef98e974a253e8624c1753 |
| O3 | **Windows 11 ARM on AGX Orin** (community, "out of the box in the latest UEFI") | AGX Orin | **UEFI direct**: Windows ARM installer ISO on USB (Rufus) → install to NVMe; "enable ACPI for the OS" in UEFI settings | not stated (display presumably) | **Hyper-V works** ⇒ Windows was entered at EL2 (reasoned, HYPOTHESIS from "Hyper-V works") | Boots, installs, Hyper-V + WSL/WSA run | No GPU acceleration, no nested virtualisation; NVIDIA: "We have not tried this yet" (2023-03-16). Jan 2025 follow-up asking how to enable ACPI got "never tried that" from NVIDIA and no answer | **VENDOR_CLAIM (forum user)**; NVIDIA replies VERIFIED-as-quoted | n/a (proprietary OS; proves the loader path only) | https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/246176 ; follow-up https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/319587 |
| O4 | Windows 11 ARM on **Orin Nano** | Orin Nano devkit | (SD card with ISO) | — | — | — | "missing drivers" | **UNKNOWN** — the only page is an auto-generated template (placeholder text, no log, no source thread) | — | https://nvidia-jetson.piveral.com/jetson-orin-nano/windows-11-arm-insider-iso-boot-issues-on-jetson-orin-nano-dev-board/ (do not cite as evidence) |
| O5 | **Fedora / RHEL 9.3+ on Orin via JetPack 6 UEFI** (nullr0ute, Fedora ARM maintainer) | AGX (commands given), NX/Nano "adjust the device variable" | UEFI direct, generic distro installer / image | `console=ttyAMA0,115200` "runs off the microUSB port" (AGX Orin) — an **SBSA/PL011-class** UART reachable from the CPU, not the TCU | not stated | Upstream kernels + generic distros boot; "developer preview, AKA public Beta" | Not detailed (ACPI gaps discussed only for Xavier in a 2021 post) | **VENDOR_CLAIM (blog, 2023-12-07)** | Linux — irrelevant for QNX except as a UEFI-path proof and the ttyAMA0 lead (see §5) | https://nullr0ute.com/2023/12/any-linux-distro-on-nvidia-jetson-orin-with-jetpack-6/ |
| O6 | **KVM (Linux at EL2) on Orin** — baseline, not a port | Orin Nano (this repo's board) | UEFI → L4TLauncher | ttyTCU0 | **EL2, VHE** | `CPU: All CPU(s) started at EL2`, `kvm [1]: VHE mode initialized successfully`, `efi: EFI v2.70 by EDK II` | (QNX guest under KVM hangs on the GICv3/NISV defect — repo, out of scope here) | **VERIFIED** — `raw/orin-firmware-el.txt` L10/L35/L41; `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt` | — | repo |
| O7 | NVIDIA "hypervisor mode" DT property (`tegra234-soc-virt.dtsi`, L4T 35.3.1) | AGX Orin | — | — | — | User found the file, set `hypervisor-mode`, ran QEMU/KVM; hvc "always return … -1" | NVIDIA (DaneLLL, 2023-07-27): "The setting is for DRIVE platforms. We don't support hypervisor mode on Jetson" | **VENDOR_CLAIM** | — | https://forums.developer.nvidia.com/t/nvidia-jetson-agx-orin-vm-in-hypervisor-mode/261056 |
| O8 | NVIDIA position, Oct 2025: hardware lock or just unsupported? | AGX Orin | — | — | — | NVIDIA (DaneLLL): not supported "on Jetpack release. You may see if there is a method"; pure-software approaches don't void warranty; "not tested in SQA coverage" | — | **VENDOR_CLAIM** — reads as *software/BSP-level* unsupported, not a fuse/firmware lock | — | https://forums.developer.nvidia.com/t/clarification-on-jetson-orin-hypervisor-support-hardware-lock-or-only-unsupported/348348 |
| O9 | **FreeBSD on Orin** | AGX Orin devkit (owned by poster) | (UEFI, FDT) | — | — | Intent only: "If FreeBSD boots on it, then I can start working on bhyve" (Rebecca Cran, 2023-05); notes booting Linux with ACPI "didn't go well" | No boot report followed that I could find; FreeBSD wiki unreachable (403) | **UNKNOWN** | BSD-2-Clause (FreeBSD) — but there is no Tegra234 code to reuse | https://lists.freebsd.org/archives/freebsd-arm/2023-May/002572.html |
| O10 | **QNX on any Jetson** (NVIDIA statements) | Nano / Xavier NX / AGX Orin / Orin | — | — | — | — | 2019-10 Nano: "We never tested with QNX on Jetson Nano"; 2020: "no plan to do" [b8]; 2024: "We don't support QNX on Jetson … DRIVE platforms" [b9]; 2025: "no plan to support QNX OS on Jetson" [b10]; **2026-02-05 Nano: "We do not have QNX OS for Jetson platform"** | **VENDOR_CLAIM** (staff replies) | — | https://forums.developer.nvidia.com/t/nvidia-jetson-nano-with-qnx-os-and-python/83486 ; https://forums.developer.nvidia.com/t/qnx-for-nvidia-jetson-nano/359720 ; [b8]–[b10] as cited in `docs/adr-003-hardware-timed-qhv.md` |
| O11 | **QNX on Tegra234-class silicon — DRIVE AGX Orin (DRIVE OS QNX)** | DRIVE AGX Orin (not Jetson) | NVIDIA's own chain (not UEFI/L4TLauncher) | (not stated; DRIVE uses the TCU + `tcu_muxer`, vendor doc) | (QNX Hypervisor host is part of DRIVE OS — QNX docs; not verified here) | NVIDIA 2024-08-14: QNX-based DRIVE OS 6.0.10 exists for DRIVE AGX Orin; "contact your NVIDIA representative"; Linux DRIVE OS "includes hypervisor"; **"multiple guest OS is not supported"** on Devzone | BSP / startup binaries are not public; DRIVE AGX SDK program is invitation-only [b11] | **VENDOR_CLAIM** | Proprietary (NVIDIA + QNX QDL) | https://forums.developer.nvidia.com/t/can-we-install-qnx-with-hypervisor-on-drive-orin/303321 |
| O12 | **Any RTOS on CCPLEX** (FreeRTOS / Azure RTOS request) | AGX Xavier (2023-09), applies to Orin per NVIDIA | — | — | — | NVIDIA: porting a new OS to CCPLEX is "a too huge task"; use PREEMPT_RT, or FreeRTOS **on the SPE** | — | **VENDOR_CLAIM** | FreeRTOS-on-SPE reference is MIT (FreeRTOS) but runs on the Cortex-R5 SPE, not the A78AE cluster | https://forums.developer.nvidia.com/t/porting-rtos-on-jetson-agx-xavier/266905 |
| O13 | seL4, Zephyr, RTEMS, NetBSD, Bao, Xvisor, Hafnium, Xen-upstream — **platform lists** | Orin | — | — | — | — | **All absent**: seL4 supported-hardware page lists TK1/TK1-SOM/TX1/TX2 only; Zephyr `boards/nvidia` → 404; RTEMS AArch64 BSPs = Qemu A53/A72, RPi 4B/5, Xen, Versal, ZynqMP, RK3399; NetBSD/evbarm Tegra = K1 + X1 (page last edited 2019-10-04); Bao `src/platform` has `tx2` only; Xvisor `arch/arm/dts` has no nvidia dir; Xen `xen/arch/arm/platforms` has no tegra file; Hafnium on Jetson is documented by NVIDIA for **AGX Thor only** | **VERIFIED (listings fetched 2026-09-09)**; Hafnium item VENDOR_CLAIM | GPL-2.0 (seL4, Xen, Xvisor), Apache-2.0 (Zephyr, Bao), BSD (RTEMS 2-clause, NetBSD, Hafnium) | https://docs.sel4.systems/Hardware/ ; https://github.com/zephyrproject-rtos/zephyr/tree/main/boards ; https://docs.rtems.org/docs/main/user/bsps/bsps-aarch64.html ; https://wiki.netbsd.org/ports/evbarm/tegra/ ; https://github.com/bao-project/bao-hypervisor/tree/main/src/platform ; https://github.com/xvisor/xvisor/tree/master/arch/arm/dts ; https://github.com/xen-project/xen/tree/master/xen/arch/arm/platforms ; https://docs.nvidia.com/jetson/archives/r38.4/DeveloperGuide/SD/Security/Hafnium.html |
| O14 | Android / AOSP / LineageOS on Orin | — | — | — | — | — | Nothing found for Orin (LineageOS 18.1 exists for Jetson **Nano**/Tegra210 only) | **UNKNOWN** | — | (search only) |
| O15 | Commercial separation kernels / hypervisors (LynxSecure, PikeOS, VxWorks, INTEGRITY, RTS) on Orin | — | — | — | — | — | No Orin/Xavier announcement found; the only "RTOS for Orin" press is Concurrent RedHawk **Linux** (2022) | **UNKNOWN** | — | https://militaryembedded.com/avionics/software/linux-rtos-from-concurrent-real-time-launches-to-support-jetson-agx-orin-platform |
| O16 | Academic papers / theses on hypervisors for Tegra234 (2024–2025) | — | — | — | — | — | None found (arXiv hits are Xavier/other SoC static-partitioning surveys, or Orin ML benchmarking) | **UNKNOWN** | — | (search only) |

Loader-path corollaries for Orin (Linux payloads, but they prove the mechanism):

- **GRUB as `BOOTAA64.efi` replacing L4TLauncher on Orin Nano** — meta-tegra
  discussion #1480: a contributor got GRUB working; maintainer says U-Boot has no
  Orin support and GRUB "not currently implemented" in the layer; a custom edk2
  bootloader "without l4tlauncher" was being explored. **VENDOR_CLAIM (community).**
  https://github.com/OE4T/meta-tegra/discussions/1480
- **kexec** on the Orin Nano: outside R5's remit; the sibling capture is
  `raw/orin-kexec.txt`.

---

## 2. Jetson AGX Xavier (Tegra194) — every item found

| # | Project | Loader | Console | EL | Worked | Broke | Evidence | Licence | Source |
|---|---|---|---|---|---|---|---|---|---|
| X1 | **KVM on AGX Xavier** (`b-man/Xavier-KVM`, L4T r32.3.1) — Linux, but establishes the EL2 handoff on Xavier | cboot (L4T r32 era) → kernel | (not stated) | **EL2/VHE** — expected output includes "VHE mode initialized successfully" | KVM after a DT patch (`0001-Enable-KVM-support-for-t194.patch`) + kernel-4.9 patches + `config-4.9.140-tegra-virt` | — | **VENDOR_CLAIM (README)**; no licence file shown | GPL-2.0 (kernel patches) | https://github.com/b-man/Xavier-KVM |
| X2 | **Jailhouse on AGX Xavier** — Minervasys fork (cache colouring, bandwidth regulation) and DanieleOttaviano "Omnivisor" fork both state "tested on NVIDIA Jetson AGX Xavier" | (not stated) | (not stated) | (Jailhouse runs at EL2 by design) | README claim only | **No Xavier/tegra194 config file exists in `configs/arm64` of either fork's default branch** — only `jetson-tx1*.c`, `jetson-tx2*.c` (VERIFIED listing). The Xavier config must live on another branch or privately | **VENDOR_CLAIM (README)** / **VERIFIED-absent (configs)** | GPL-2.0 | https://github.com/Minervasys/jailhouse ; https://github.com/DanieleOttaviano/jailhouse |
| X3 | Xen / seL4 / Bao / Zephyr / FreeBSD / NetBSD on Xavier | — | — | — | — | Nothing found. NVIDIA 2019-05-01: "We haven't test with any Hypervisor on Jetson AGX Xavier" | **UNKNOWN** / VENDOR_CLAIM | — | https://forums.developer.nvidia.com/t/hypervisor-support-on-nvidia-jetson-agx-xavier/73976 |
| X4 | UEFI ACPI on Xavier (NVIDIA "UEFI features supported only on Jetson AGX Xavier" readme) | UEFI → menu **Device Manager → "O/S Hardware Description Selection" → Device Tree / ACPI** | Under ACPI "you don't get display output"; serial console via the **Tegra 8250** driver (`8250_tegra.c`); SPCR/DBG2 "sub-type 5" entries added | — | Generic distro (Fedora) installers boot | Display, accelerators | **VENDOR_CLAIM** (readme is Xavier-scoped; whether the same menu exists on the shipped Orin **Nano** firmware is UNKNOWN — cf. `docs/orin-port.md` §Research sweep B) | — | https://developer.nvidia.com/downloads/uefi-readme-826 (search snippet; page itself Xavier-only) |

---

## 3. Older Jetson (TK1 / TX1 / TX2 / Nano) — the established non-Linux-at-EL2 prior art on Tegra

These are one to three generations old (GICv2, U-Boot, no TCU), so they transfer to
Orin only as *patterns*, not as code — but they are the only cases where a non-Linux
kernel demonstrably owned EL2 on a Jetson.

| # | Project | Board | Loader | Console | EL | Worked | Broke | Evidence | Licence | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 | **Xen "Initial Tegra platform support" series** (Chris Patterson & Kyle Temkin, Assured Information Security, posted 2017-04-06, 6 patches) | TK1, TX1, Pixel C tested in earlier revisions; the posted set tested on TX1 | U-Boot (HYPOTHESIS — TK1/TX1 L4T of that era shipped U-Boot) | **ns16550 at MMIO** (added an Rx-timeout-interrupt quirk to Xen's ns16550 driver; also an earlyprintk config) | EL2 (Xen) | 2016-05-16 (Temkin): "dom0 and guests booting on the Jetson TK1, Jetson TX1, and the Google Pixel C" | Tegra's **Legacy Interrupt Controller (LIC/ictlr)** sits in front of the GICv2 and needs platform IRQ-routing hooks (patch 4/6); TX UART "transmit ready" fires continuously. **Never merged** — Xen `platforms/` has no tegra file today (VERIFIED) | **VENDOR_CLAIM (mailing list)** for the boot claim; merge status VERIFIED-absent | GPL-2.0 (Xen) — protocol knowledge only, no copying into QNX | https://www.mail-archive.com/xen-devel@lists.xen.org/msg68079.html ; series index https://lore.kernel.org/all/1491508074-31647-1-git-send-email-cjp256@gmail.com/T/ (403 today; title/date from search index) |
| L2 | Xen 4.9.1 on **TX2** (Tegra186, P2771-0000) | TX2 | U-Boot 2016.07 | `dtuart=/serial@3100000`, dom0 `console=hvc0` | EL2 (Xen banner) | Xen boots, GICv2 (384 lines, 8 CPUs "secure mode"), SMMU quirk logged | **dom0 kernel load hangs**; nobody in the 2017 NVIDIA threads reports dom0 up | **VENDOR_CLAIM (list / forum)** | GPL-2.0 | https://lists.xenproject.org/archives/html/xen-devel/2017-12/msg01521.html ; https://forums.developer.nvidia.com/t/booting-xen-on-tx2/52069 |
| L3 | Xen 4.8.5 on **Jetson Nano** (Tegra210), July 2020 | Nano | U-Boot (meta-tegra issue #320 — Xen built into `/boot`, "missing pieces are booting xen from u-boot") | (8250) | EL2 (Xen boots) | Xen up, dom0 scheduled on pCPU0; had to "hack the 'interrupt-controller' node" for GICv2 | dom0 **instruction abort at entry**, stage-2 translation faults; Julien Grall advised `earlycon=xenboot` + a page-walk dump patch. No resolution posted | **VENDOR_CLAIM (list)** | GPL-2.0 | https://lists.xenproject.org/archives/html/xen-devel/2020-07/msg01256.html ; https://github.com/OE4T/meta-tegra/issues/320 |
| L4 | **seL4 on TX1 / TX2** (supported platforms) | TX1 (AArch64 verified), TX2 (AArch64 verified; "SoM only in 64-bit mode") | **U-Boot uImage** produced by the seL4 build | `serial0 = "/serial@3100000"`, compatible `nvidia,tegra20-uart`,`nvidia,tegra186-hsuart`, `reg-shift = <2>` (32-bit-stride 8250) — VERIFIED in `tools/dts/tx2.dts`; kernel/elfloader devices = serial0, GICv2 `@3881000`, IOMMU `@12000000`, timer (VERIFIED `overlay-tx2.dts`) | **EL2** on TX2 — CAmkES VM examples list TX2 with 64-bit guests, SMP and multi-VM working; TX1 64-bit guest SMP working, virtio untested | seL4 + VMs run | TX2 Denver cores: 40-bit PA vs 44-bit on A57 (comment in `config.cmake`); boot CPU forced to `cpu@2` | **VERIFIED (source)** for config; **VENDOR_CLAIM (README)** for VM status | GPL-2.0-only (kernel + DTS); read for protocol only | https://docs.sel4.systems/Hardware/JetsonTX2.html ; https://github.com/seL4/seL4/blob/master/src/plat/tx2/overlay-tx2.dts ; https://github.com/seL4/camkes-vm-examples |
| L5 | **Bao hypervisor on TX2** | TX2 | TF-A → **U-Boot**: `fatload mmc 1 0xa0000000 bao.bin; go 0xa0000000` | UART `0x03100000` (J21 pins P23/P24, 115200) — VERIFIED in `tx2_desc.c`; GICD `0x03881000`, GICC `0x03882000`, GICH/GICV; SMMU `0x12000000`; 2 clusters (2+4) | EL2 (static-partitioning type-1; by design) | Demos boot | TF-A must be rebuilt to control SMMU stream IDs for DMA passthrough | **VERIFIED (source)** / **VENDOR_CLAIM (demo README)** | **Apache-2.0** (SPDX in `tx2_desc.c`) — copyable | https://github.com/bao-project/bao-hypervisor/blob/main/src/platform/tx2/tx2_desc.c ; https://github.com/bao-project/bao-demos/blob/master/platforms/tx2/README.md |
| L6 | **Jailhouse upstream configs** | TX1, TX2 (`jetson-tx1.c`, `jetson-tx2.c`, inmate/linux demos) | Linux root cell (U-Boot era) | 8250 | EL2 | ERIKA3 RTOS as a Jailhouse guest on TX1/TX2 (HERCULES project) | NVIDIA 2018-01: "We do not currently support a hypervisor on Jetson DevKit"; a TX2 4.4.38 attempt stalled on CPU offlining (missing IPI_WAKEUP) | **VERIFIED (listing)** / VENDOR_CLAIM | GPL-2.0 | https://github.com/siemens/jailhouse/tree/master/configs/arm64 ; https://www.erika-enterprise.com/wiki/index.php/Nvidia_Jetson_TX1_and_TX2 ; https://forums.developer.nvidia.com/t/hypervisor-support-for-jetson-tx2-4-4-38-kernel/56758 |
| L7 | NetBSD/evbarm | Jetson TK1 (NetBSD 8.0), TX1 (NetBSD 9.0) | U-Boot | `com(4)` (8250) | EL1 (OS) | Runs | Nothing newer than X1; page last edited 2019 | **VENDOR_CLAIM** | BSD-2-Clause | https://wiki.netbsd.org/ports/evbarm/tegra/ |
| L8 | FreeBSD on Jetson TK1 (2015, gonzo) | TK1 | U-Boot | 8250 | EL1 | Ran | No Tegra newer than K1 in tree; Nano needs a hand-built U-Boot, "not in the ports tree" | **VENDOR_CLAIM** | BSD-2-Clause | https://kernelnomicon.org/?p=628 ; https://forums.freebsd.org/threads/can-i-install-freebsd-on-jetson-nano.82928/ |

Pattern that transfers: every successful non-Linux-at-EL2 case on Tegra used (a) a
loader that hands off at EL2 (U-Boot then; UEFI/edk2 now — VERIFIED at O6), (b) a
plain CPU-owned 8250 UART for the console, (c) a hypervisor/kernel that already had a
generic GIC + PSCI + arch-timer path and needed only a *platform quirk* file. On Orin,
(a) holds, (c) is what `libstartup.a` already provides (see `harvest-sdp.md`), and (b) is
the open question this sweep's §5 addresses.

---

## 4. TCU / "combined UART" implementations **outside** Linux

| Where | File | Licence (SPDX) | What it implements | Protocol as written in the source | RX? | Base-address source | Evidence |
|---|---|---|---|---|---|---|---|
| **edk2-nvidia** (UEFI) | `Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c` (+ `.inf`, LIBRARY_CLASS `TegraCombinedSerialPortLib`) | **BSD-2-Clause-Patent** | Full `SerialPortLib` over two HSP shared mailboxes (TX + RX). `SetControl`/`SetAttributes` return `EFI_UNSUPPORTED` | 32-bit mailbox word = union `TEGRA_COMBINED_UART`: `Data[3]` (bytes 0–2) + control byte: `NumberOfBytes` (2 bits), `Flush` (1 bit), `HwFlush` (1 bit), reserved (3 bits), `Interrupt` (top bit). Writer polls until the TX mailbox's top bit clears (`IsDataPresent()==FALSE`) before writing the next word; reader takes up to 3 bytes per RX word | **Yes** | PCDs `gNVIDIATokenSpaceGuid.PcdTegraCombinedUartTxMailbox` / `...RxMailbox` (UINT64, **default 0** in `Silicon/NVIDIA/NVIDIA.dec`; the T234 values are set per platform in a dsc/dec not located today — UNKNOWN) | **VERIFIED (source read)** |
| **TF-A** (upstream) | `plat/nvidia/tegra/drivers/spe/shared_console.S` | **BSD-3-Clause** (ARM + NVIDIA 2017–2020) | Boot-time console "for SoCs after Tegra186", TX only, AArch64 asm | Bits 0–7 = byte; `CONSOLE_NUM_BYTES_SHIFT 24` (=1 byte); `CONSOLE_FLUSH_DATA_TO_PORT` = bit 26; bit 31 = `CONSOLE_IS_BUSY` when polling / `CONSOLE_RING_DOORBELL` when writing; spin with `CONSOLE_TIMEOUT 0xC000` (~50 ms) | **No** (`console_spe_getc` returns -1) | `TEGRA_CONSOLE_SPE_BASE` (t194 `tegra_def.h`), registered when `ENABLE_CONSOLE_SPE` is set, else `console_16550_register(tegra194_uart_addresses[id])` — VERIFIED in `soc/t194/plat_setup.c`. **Upstream has no `soc/t234`** (listing VERIFIED); L4T ships a `t234` TF-A as `atf_src.tbz2` in the BSP sources (VENDOR_CLAIM, NVIDIA forum), and one user's rebuilt `tos` image failed to boot (Feb 2024, community) | **VERIFIED (source read)** |
| **Xen** | (2017 unmerged series) | GPL-2.0 | ns16550 only — **no TCU** | — | — | — | VERIFIED-absent (see L1) |
| **seL4 / Bao / Jailhouse** | TX2 platform files | GPL-2.0 / Apache-2.0 / GPL-2.0 | 8250 at `0x03100000` only — **no TCU** (TX2 predates the TCU) | — | — | — | VERIFIED (L4–L6) |
| **U-Boot** | — | GPL-2.0 | No Tegra194/234 board support found; NVIDIA states U-Boot is not supported on Orin | — | — | — | UNKNOWN (mailing-list search only) |
| **OP-TEE (nv-optee, L4T)** | `nvidia-jetson-optee-source.tbz2` → built with `optee_src_build.sh -p t234` | BSD-2-Clause (OP-TEE core) | Unknown whether it has a combined-UART console; NVIDIA gitiles did not respond | — | — | — | **UNKNOWN** |
| **Hafnium** | NVIDIA doc | BSD-3-Clause | Only documented for **AGX Thor** (S-EL2 SPMC); no TCU mention | — | — | — | VENDOR_CLAIM |
| **Linux** (reference, not reusable) | `drivers/tty/serial/tegra-tcu.c`, `tegra-tcu-earlycon.c` (+ `tegra-hsp.c` mailbox) | GPL-2.0 | Full driver over the mailbox framework; upstream since 5.1; earlycon added 2021 | Same 3-bytes-per-word framing | Yes | DT `mboxes` | VENDOR_CLAIM (LWN/patch archives) — **read for the register protocol only** |

**Cross-check of the two BSD sources (VERIFIED, independent):** edk2's control byte
{count bits 0–1, flush bit 2, interrupt bit 7} at byte 3 of the word is bit-for-bit
TF-A's {`NUM_BYTES_SHIFT 24`, flush bit 26, doorbell/busy bit 31}. Two licence-clean
implementations agree on the CPU-side protocol.

**What the live Orin Nano DT says (VERIFIED, `raw/orin-devicetree.txt` L278–289):**
`/serial` is `nvidia,tegra234-tcu`,`nvidia,tegra194-tcu` with
`mboxes = <0x121 0x1 0x0>, <0x143 0x1 0x80000001>`, `mbox-names = "rx","tx"`.
Cell 2 = `0x1` = `TEGRA_HSP_MBOX_TYPE_SM` (the **32-bit** shared mailbox type, not the
`SM_128BIT` flag), RX index 0, TX index 1 with the TX flag (bit 31). Upstream
`tegra234.dtsi` binds those to `hsp_top0` (`0x03c00000`) for RX and `hsp_aon`
(`0x0c150000`) for TX — phandle-to-node mapping is **HYPOTHESIS** here (phandles were
not resolved in the capture); both HSP blocks are present in `raw/orin-iomem.txt`
(L93, L124). Console active is `ttyTCU0` (`raw/orin-ttys.txt`).

**Consequences for a QNX startup (HYPOTHESIS, reasoned):**

1. A polled `display_char` callout over the TX shared mailbox is small (write one
   32-bit word, spin on bit 31) and the two BSD sources give a clean-room-free path to
   it — no GPL code needs to be read. The SPE firmware that demuxes the stream is
   already running by the time UEFI hands off (UEFI itself prints through it —
   edk2-nvidia builds the TCU library for Tegra; which serial lib the shipped Orin
   Nano firmware actually selects is governed by `PcdSerialTypeConfig`/`PcdSerialPortConfig`
   and was not verified).
2. The exact TX/RX mailbox **register addresses** for T234 are the missing constant
   (edk2 PCD defaults are 0). They can be derived from the HSP block base + the SM
   index using the HSP register layout (Linux `tegra-hsp.c` documents it; GPL — read
   only) or found in an edk2-nvidia platform `.dsc` — not located today.
3. The other CPU-owned UARTs on this board are `serial@3100000` (`nvidia,tegra194-hsuart`,
   Linux `ttyTHS1`; the UART meta-xen's `dtuart=…0x3100000` targets) and
   `serial@31d0000` (`arm,sbsa-uart`, Linux `ttyAMA0`) — both VERIFIED present in the
   live DT. nullr0ute reports `console=ttyAMA0` reaching the **AGX Orin** micro-USB;
   whether `serial@31d0000` reaches any Orin **Nano** connector is UNKNOWN and is the
   cheapest thing to test next (a write to the device, so outside this read-only task).
   `harvest-sdp.md` already notes `callout_debug_pl011`/`hw_serpl011` (for the SBSA
   UART) and `callout_debug_tegra`/`callout_debug_8250_32b` (for `uarta`) exist in
   `libstartup.a`.
4. Header pins (community, **not verified against the carrier spec**): the Orin Nano
   devkit debug console is on the 12-pin J14 button header, pins 3 (RX) / 4 (TX) —
   that is the TCU stream; the 40-pin header carries a "UART1" pair (pin numbers
   differ between sources: 8/10 vs 22/32) which is the `uarta`/`ttyTHS1` device.
   Sources: https://developer.ridgerun.com/wiki/index.php/NVIDIA_Jetson_Orin_Nano/In_Board/Getting_in_Board/Serial_Console ,
   https://developerwiki.proventusnova.com/How_to_NVIDIA_Jetson_Orin_Nano_UART_Console . UNKNOWN until checked against the
   *Jetson Orin Nano Developer Kit Carrier Board Specification*.

Licence note for reuse (researcher's reading, not legal advice): BSD-2-Clause-Patent
(edk2-nvidia) and BSD-3-Clause (TF-A) permit copying into an Apache-2.0 QNX BSP
startup with attribution; GPL-2.0 sources (Linux `tegra-tcu.c`/`tegra-hsp.c`, Xen,
seL4, Jailhouse) may inform the register protocol but must not be copied. The QNX
side (NC QDL v7 4.1(iii) modify-source permission; 4.6(c)/(i) restrictions) is as
recorded in `docs/adr-003-hardware-timed-qhv.md` [b12].

---

## 5. "Talk slide" vs "code merged" — explicit tally

| Claim | Slide/README/forum only | Code in a public tree | Boot log public |
|---|---|---|---|
| Xen on Orin Nano (meta-xen) | yes (README) | Yocto layer only; no Xen patch seen | **no** |
| Jailhouse on AGX Orin | gist | patches are Siemens' generic `jailhouse-enabling/5.10` | crash log yes; success **no** |
| Windows on AGX Orin | forum post | n/a | screenshots/none; NVIDIA did not reproduce |
| Fedora/RHEL on Orin (UEFI) | blog + NVIDIA "Any distro" support | upstream kernel | vendor-endorsed |
| Xen on TK1/TX1/Pixel C | mailing list | posted 2017, **never merged** | no |
| Xen on TX2 / Nano | forum / list | none | partial (Xen banner; dom0 fails) |
| seL4 on TX1/TX2 | docs | **merged** (`src/plat/tx2`) | project CI (not fetched) |
| Bao on TX2 | README | **merged** (`src/platform/tx2`) | demo README |
| Jailhouse on TX1/TX2 | — | **merged** configs | ERIKA project |
| Jailhouse on Xavier | README claim (2 forks) | **no config found** | no |
| QNX on DRIVE AGX Orin | NVIDIA staff | proprietary | n/a |
| QNX on any Jetson | — | **none found** | none |
| TCU driver, BSD | — | **merged** in edk2-nvidia and TF-A | UEFI console on every Orin is the live proof (VENDOR_CLAIM for which lib the shipped build uses) |

---

## 6. Unknowns this sweep could not close

- T234 TCU TX/RX mailbox absolute addresses as used by edk2-nvidia (PCD values) —
  need the platform `.dsc`/`.dec` for Jetson T234 or an HSP register-map derivation.
- Whether the shipped Orin Nano UEFI (R36.4.4, `bvr36.4.4-gcid-41062509` per
  `raw/orin-uefi-dmesg.txt`) exposes the "O/S Hardware Description Selection" (ACPI)
  menu; only Xavier-era readme and AGX Orin community reports say so.
- Whether `serial@31d0000` (SBSA UART, `ttyAMA0`) reaches any external connector on
  the Orin Nano devkit.
- Whether any Xen/Jailhouse/seL4 work on Orin exists in private/academic repos not
  indexed by web search (GitHub code search was unavailable).
- The 2017 Xen Tegra cover letter body (lore/patchwork 403) — tested-board list taken
  from the search index and the 2016 list post.
- Whether the L4T `atf_src.tbz2` for t234 carries the `spe/shared_console.S`
  driver (it is NVIDIA's fork; not fetched).
- nv-optee console driver for t234.
- Jailhouse-on-Xavier configs (claimed, not found).
- Any FreeBSD/NetBSD/Android boot on Orin.

## 7. Source index (accessed 2026-09-09)

Orin: https://github.com/KPGURAV10/meta-xen · https://gist.github.com/carzacc/0fb09a00daef98e974a253e8624c1753 ·
https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/246176 ·
https://forums.developer.nvidia.com/t/nvidia-jetson-orin-agx-can-boot-windows-out-of-the-box-in-the-latest-uefi/319587 ·
https://nullr0ute.com/2023/12/any-linux-distro-on-nvidia-jetson-orin-with-jetpack-6/ ·
https://forums.developer.nvidia.com/t/nvidia-jetson-agx-orin-vm-in-hypervisor-mode/261056 ·
https://forums.developer.nvidia.com/t/clarification-on-jetson-orin-hypervisor-support-hardware-lock-or-only-unsupported/348348 ·
https://lists.freebsd.org/archives/freebsd-arm/2023-May/002572.html ·
https://forums.developer.nvidia.com/t/qnx-for-nvidia-jetson-nano/359720 ·
https://forums.developer.nvidia.com/t/nvidia-jetson-nano-with-qnx-os-and-python/83486 ·
https://forums.developer.nvidia.com/t/can-we-install-qnx-with-hypervisor-on-drive-orin/303321 ·
https://forums.developer.nvidia.com/t/porting-rtos-on-jetson-agx-xavier/266905 ·
https://github.com/OE4T/meta-tegra/discussions/1480 ·
https://docs.nvidia.com/jetson/archives/r38.4/DeveloperGuide/SD/Security/Hafnium.html

Xavier: https://github.com/b-man/Xavier-KVM · https://github.com/Minervasys/jailhouse ·
https://github.com/DanieleOttaviano/jailhouse · https://forums.developer.nvidia.com/t/hypervisor-support-on-nvidia-jetson-agx-xavier/73976

Older Jetson: https://www.mail-archive.com/xen-devel@lists.xen.org/msg68079.html ·
https://lists.xenproject.org/archives/html/xen-devel/2017-12/msg01521.html ·
https://lists.xenproject.org/archives/html/xen-devel/2020-07/msg01256.html ·
https://github.com/OE4T/meta-tegra/issues/320 · https://forums.developer.nvidia.com/t/booting-xen-on-tx2/52069 ·
https://forums.developer.nvidia.com/t/hypervisor-support-for-jetson-tx2-4-4-38-kernel/56758 ·
https://docs.sel4.systems/Hardware/ · https://docs.sel4.systems/Hardware/JetsonTX2.html ·
https://github.com/seL4/seL4/blob/master/src/plat/tx2/config.cmake · https://github.com/seL4/seL4/blob/master/src/plat/tx2/overlay-tx2.dts ·
https://github.com/seL4/seL4/blob/master/tools/dts/tx2.dts · https://github.com/seL4/camkes-vm-examples ·
https://github.com/bao-project/bao-hypervisor/blob/main/src/platform/tx2/tx2_desc.c ·
https://github.com/bao-project/bao-demos/blob/master/platforms/tx2/README.md ·
https://github.com/siemens/jailhouse/tree/master/configs/arm64 · https://wiki.netbsd.org/ports/evbarm/tegra/ ·
https://kernelnomicon.org/?p=628

Platform-list absences: https://github.com/zephyrproject-rtos/zephyr/tree/main/boards ·
https://docs.rtems.org/docs/main/user/bsps/bsps-aarch64.html · https://github.com/xvisor/xvisor/tree/master/arch/arm/dts ·
https://github.com/xen-project/xen/tree/master/xen/arch/arm/platforms · https://github.com/bao-project/bao-hypervisor/tree/main/src/platform

TCU: https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c ·
https://github.com/NVIDIA/edk2-nvidia/blob/main/Silicon/NVIDIA/NVIDIA.dec ·
https://github.com/ARM-software/arm-trusted-firmware/blob/master/plat/nvidia/tegra/drivers/spe/shared_console.S ·
https://github.com/ARM-software/arm-trusted-firmware/blob/master/plat/nvidia/tegra/soc/t194/plat_setup.c ·
https://github.com/ARM-software/arm-trusted-firmware/tree/master/plat/nvidia/tegra/soc ·
https://forums.developer.nvidia.com/t/arm-trusted-firmware-fork/280681 ·
https://forums.developer.nvidia.com/t/flashing-atf-from-driver-package-bsp-sources/282130 ·
https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html ·
https://lwn.net/Articles/753842/

Repo-local (VERIFIED): `raw/orin-firmware-el.txt`, `raw/orin-uefi-dmesg.txt`, `raw/orin-ttys.txt`,
`raw/orin-devicetree.txt`, `raw/orin-iomem.txt`, `harvest-sdp.md`, `logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt`,
`docs/adr-003-hardware-timed-qhv.md`, `docs/orin-port.md` (Research sweep B).
