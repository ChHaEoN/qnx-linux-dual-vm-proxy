# Phase 3b — Native QNX on Jetson Orin Nano: port plan (kick-off 2026-09-09)

**Status: Proposed plan.** [ADR-003](adr-003-hardware-timed-qhv.md) option (B) — native Orin Nano port —
was **accepted by the owner on 2026-09-09**. Licence stance the same day: **proceed**, and **consult the
supervising professor before publishing any evaluation results** (NC QDL v7 4.6(i)); keep 4.6(c) clean by
working from source and documentation only, never disassembly. **No numbers exist yet.** Nothing in this
document has been executed on the board: every milestone below is a proposal, and the only things marked
VERIFIED are compile-only builds on the Windows host and read-only reads of the board as it runs L4T today.

Evidence classes are used on every load-bearing statement: **VERIFIED** (seen — file:line, command output,
live-board capture), **VENDOR_CLAIM** (a document says so), **HYPOTHESIS** (reasoned, untested),
**UNKNOWN**. Redaction throughout: `<user>`, `<orin-ip>`, `<orin-key>`.

Inputs, all under [`../results/orin-native-port/20260909T1100Z/`](../results/orin-native-port/20260909T1100Z/):
`synthesis-plan.md` (the plan this document revises); harvests `harvest-{repo,sdp,orin}.md`; research
`research-{qnx,tegra234,kexec-tcu,uefi,prior-art}.md`; the compile-only results `build-armv8_fm.md` and
`build-m1-placeholder-ifs.md`; the read-only board corrections `board-readonly-corrections.md`; and the raw
captures in `raw/`. Individual files are linked where they carry a specific claim.

---

## 0. What changed since the synthesised plan

Twelve load-bearing claims were put through three independent verification lenses (source / docs / live
board). Four came back materially wrong. The corrections that change the plan, not just its wording:

1. **A hardware watchdog *is* armed and counting** (K9). The synthesis read the wrong device-tree node.
   `/dev/watchdog0` is bound to `2080000.timer`, systemd sets it to **2 min**, and a read-only register peek
   shows `WDT0 @0x02190000 WDTCR=0x00710010, WDTSR=0x00000011`
   ([`board-readonly-corrections.md`](../results/orin-native-port/20260909T1100Z/board-readonly-corrections.md) §1).
   Both directions: unattended recovery is probably **free**, and every experiment has a **~2-minute
   ceiling**. The `-W` policy stops being optional for M3/M4; the shim's WDT-arming code is dropped.
2. **The 992 MiB window is not "the" DRAM, it is the lowest fragment** (K5). `/proc/iomem` shows ~7 disjoint
   System RAM ranges totalling 7.4 GiB; `0x80000000-0xBDFFFFFF` is the lowest, bounded above by an adjacent
   reserved range. Exclusive ownership after `rmmod` remains **HYPOTHESIS**, not a given.
3. **The measurement recipe is a plan, not a validated pipeline** (K11). The QHV Class-10 trace-event IDs are
   still **VENDOR_CLAIM** from an online doc page, and the "filtered listing fits through the TCU in 1-2 min"
   estimate has never been exercised. A zero-cost dry run inside the existing Windows-TCG QHV image must
   happen before M4 is designed around it.
4. **The board-build claim was half right, its symbol gate wrong** (K12). The toolchain question is now
   **settled positively** — the BSP zip's `armv8_fm` board builds unmodified under the win64 SDP 8.0 tooling
   ([`build-armv8_fm.md`](../results/orin-native-port/20260909T1100Z/build-armv8_fm.md), exit 0,
   `startup-armv8_fm` = 632,224 B). But three `uefi_*_f` symbols **are** linked, so the "no `uefi_`" gate is
   wrong; and `display_char_tcu` exists nowhere in the SDP or BSP — we write it.

Two smaller reversals: the `kexec-load` shutdown hazard **does not exist here** (`LOAD_KEXEC=false`), so the
`systemctl mask --runtime` step is dropped; and the governor is `schedutil` at 1,113,600 of 1,344,000 kHz, so
the `performance` pin and the M4 PMCCNTR calibration both stay load-bearing. One inter-lens contradiction was
resolved from the repo's own capture: a live lens reported no VHE/EL2 dmesg lines, but
`raw/orin-firmware-el.txt:32,38` records `CPU: All CPU(s) started at EL2` and `kvm [1]: VHE mode initialized
successfully`. The capture stands.

---

## 1. Goal, non-goals, kill criteria

**Goal.** Boot QNX SDP 8.0 natively on the Jetson Orin Nano Dev Kit (Tegra234, 6× Cortex-A78AE, L4T R36.4.7 /
UEFI 36.4.4), reach the QNX Hypervisor 8.0 host at real EL2 (`-Q enable,el2-host`, VHE), boot the
**byte-identical** cloud-leg QNX guest under it, and produce the first hardware-timed QHV numbers on this
silicon: **M3** host-clock `qvm` launch → guest banner, and **M4** per-exit hypervisor dwell P50/P99/max in
the [`scripts/twin/diff-results.sh`](../scripts/twin/diff-results.sh) CSV schema. Both feed
[`digital-twin-design.md` §1a](digital-twin-design.md) as a **third host bundle** (native Orin / no QEMU /
VHE) — explicitly *not* a one-variable diff (§7).

**Non-goals.** No storage, network, USB, display, GPU, SMMU or PCIe drivers; no Linux guest on the native
leg; no cold-boot number unless the optional M5 UEFI cross-check happens; no publication of any number or
functional log before the licence consultation (§9); no reflash, no QSPI / UEFI-variable / extlinux / ESP
writes on the primary path; no KVM work (the GICv3/NISV defect in [`orin-port.md`](orin-port.md) is a
separate track).

**Kill criteria.** (a) M0 shows `CurrentEL != 2` at kexec entry → the kexec leg is dead; pivot to the UEFI
Shell alternative (§3.4). (b) TCU, uarta, black box and LED all silent → the port cannot be observed; stop
until the adapter arrives. (c) The `-t` probe says INTID 28 absent **and** `el1-host` also fails to arm → no
hardware-timed QHV number from this board; the finding itself becomes the deliverable.

---

## 2. Claims register

Twelve claims, in their **corrected** form. "Settles it" names the cheapest decisive test.

| id | claim (corrected form) | status | strongest evidence | what settles it |
|---|---|---|---|---|
| **K1** | kexec from the L4T VHE kernel enters the payload **at EL2**, MMU off, `x0` = DTB PA, `x1-x3` = 0, DAIF masked, exactly one CPU online; `HCR_EL2.E2H` and a stale `VBAR_EL2` survive uncleaned. That an EL2 **physical timer is armed** is HYPOTHESIS — nothing clears it, but nothing shows it armed either. | SUPPORTED | VERIFIED against **upstream v5.15** `machine_kexec.c` / `cpu-reset.{h,S}` / `relocate_kernel.S`: `el2_switch=0` for a VHE kernel, so `__cpu_soft_restart` branches straight to the relocator at EL2; relocator ends `mov x0,x18; x1-x3=xzr; br x17`. Board is VHE: `raw/orin-firmware-el.txt:32,38` | M0's shim bank line (`EL=`, `HCR=`, `DTBMAGIC=`). NVIDIA's 5.15.148-tegra fork of those three files was **never diffed** — obtain `kernel_src.tbz2` or accept M0 as the test |
| **K2** | `image_probe()` checks **only** the `ARM\x64` magic (no signature/PE/content check, `KEXEC_SIG` unset); `image_load()` sets `memsz = image_size + text_offset`, `buf_min = 0`, bottom-up, 2 MiB align, then `kernel_segment->mem += text_offset`; the DTB is placed **top-down** above it. That the first hole is at `0x80000000` (→ landing at `0x80080000`) is **HYPOTHESIS**. | UNSETTLED | Kernel source VERIFIED (v5.15 `kexec_image.c`, `kexec_file.c`, `machine_kexec_file.c`). Board preconditions VERIFIED (`raw/orin-kexec.txt`: `CONFIG_KEXEC{,_FILE}=y`, `# CONFIG_KEXEC_SIG is not set`, `kexec_load_disabled=0`). IFS side VERIFIED by [`build-m1-placeholder-ifs.md`](../results/orin-native-port/20260909T1100Z/build-m1-placeholder-ifs.md) | `sudo kexec -s -l t234-shim.kimg; cat /sys/kernel/kexec_loaded; sudo kexec -u` (no reboot, nothing persistent), then `kexec -d` for the segment addresses. **Blocking gate for M0 step 2.** |
| **K3** | `at_el2` (`lib/aarch64/_start_el1.S:125-197`, **not** 125-190; the `msr hcr_el2` is at **:156**, not :161) normalises SCTLR_EL2 M/C/I + flush, HCR_EL2 ← RW\|HCD(+API/APK) (clearing E2H/TGE as a side effect, **no ISB after**), CPTR_EL2=0, CNTHCTL_EL2=3, VMPIDR/VPIDR, CNTVOFF/VTTBR=0, ICC_SRE_EL2=0xF. MDCR_EL2 / HSTR_EL2 / ICH_HCR_EL2 are written **nowhere** in the lib → the shim owns them, plus VBAR_EL2 and the armed timers. **E2H is not permanently cleared:** `hyp_enable_el2_host` re-asserts E2H/TGE later for VHE. | UNSETTLED | Source VERIFIED three times over, incl. lib-wide greps: `vbar_el2` written only at `hypervisor_enable.S:43`; `mdcr_el2`/`hstr_el2`/`ich_hcr_el2` absent from `lib/aarch64` entirely | Whether QNX boots from that inherited state **on real VHE silicon** (vs. TCG, where entry is already E2H=0) is HYPOTHESIS — only M1 settles it. Bisect with `SHIM_FULL_NORMALISE=1` |
| **K4** | TX = AON HSP shared mailbox 1 `0x0C168000`, RX = TOP0 `0x03C10000`; word = bytes[23:0], count[25:24], Flush[26], HwFlush[27], FULL/doorbell[31]; **RX release-by-writing-0 is now VERIFIED**, not HYPOTHESIS. That the **SPE keeps demultiplexing after Linux is kexec'd away** stays HYPOTHESIS — and it is the load-bearing half. | UNSETTLED | Addresses agree across three sources (live DT `mboxes`, `tegra-hsp.c` formula, edk2-nvidia Kconfig defaults). Release-by-zero VERIFIED from edk2-nvidia `TegraCombinedSerialPortLib.c` `Read()`. Live idle read VERIFIED: TX and RX both `0x00000000`, bit 31 clear (`raw/orin-readonly-followup-2.txt`) | M0 only: a bank line on the USB-TTL adapter within ~2 s of Linux's "Bye!", `TCU drops=0`. Bounded polls make a dead SPE degrade to silence, never a hang |
| **K5** | RAM must be hard-coded or taken from `/chosen/linux,uefi-mmap-*`, **never** a `/memory` node (none exists). `0x80000000-0xBDFFFFFF` is System RAM — but it is **the lowest of ~7 disjoint System RAM fragments** (7.4 GiB total), bounded above by an adjacent reserved range, not an arbitrary safe window, and it already holds a third child at `0x9d020000` besides kernel code/data (raw/orin-iomem.txt:180,182). **Exclusive ownership after Linux + `rmmod` is HYPOTHESIS.** | **REFUTED** (as originally worded) | VERIFIED: no `/memory` node, `/chosen/linux,uefi-mmap-*` present (`raw/orin-devicetree.txt`); `80000000-bdffffff : System RAM` with only kernel code/data inside (`raw/orin-iomem.txt:180`); no DT carveout lands inside it | `rmmod nvidia_drm nvidia_modeset nvgpu`, then re-read `/proc/iomem` + `dmesg` for SMMU/EMEM faults. **Plan change:** the M3+ second window must be re-derived from `/proc/iomem`, not from the single hard-coded 5.4 GiB line the synthesis proposed |
| **K6** | Plain GICv3: GICD `0x0F400000`, GICR `0x0F440000`/`0x200000` = 16 frames × `0x20000`, populated 0-3 and 6-7, 960 SPIs, sysreg CPU interface, no ITS, no GICV. `gic_v3_set_paddr_range(...,0x200000,NULL_PADDR)` gives `gicr_index_limit=16` so the affinity walk reaches frames 6/7; `gic_v3_initialize()` already zeroes `GICD_CTLR` and all SPI enable/pending (but **not** `ICACTIVER`). | SUPPORTED | Geometry VERIFIED from dmesg (`raw/orin-firmware-el.txt:18-30`). Library mechanics VERIFIED in `gic_v3.c` (`:299-336` limit arithmetic, `:1334-1352` walk with `ASSERT` and no `Last` check, `:980-1000`/`:1496-1502` quiesce, `:1509-1511` MMIO-IPI hardcode) | Caveat the synthesis missed: the **only board source that exists** (`armv8_fm/aarch64/init_intrinfo.c:76`) calls the auto-sizing `gic_v3_set_paddr()` (limit = `board_smp_num_cpu()` = 6 → `ASSERT` at frame 6). Our board **must** call the `_range` form. `-P6` boot at M2 is the test; `-P4` is the fallback |
| **K7** | PSCI `CPU_ON` (SMC64 `0xC4000003`) with a **board** `psci_cpu_id()` returning `{0x0,0x100,0x200,0x300,0x10200,0x10300}` and `psci_call = psci_smc` set explicitly in `main()` (`fdt_psci_configure()` matches the literal `"arm,psci"`; the board DT says `"arm,psci-1.0"`); a CPU that never starts ends in `ap_fail()`, not a silent hang. **Archive link-order override and TF-A returning secondaries at EL2 on T234 are both untested.** | UNSETTLED | Source VERIFIED: `psci.h:40` `PSCI_CPU_ON = 0xc4000003`; `fdt_psci_configure.c` exact-string match; `psci_smp.c` passes `psci_cpu_id(cpu)` straight into CPU_ON; library `psci_cpu_id.c` returns the index verbatim; `init_smp.c` `start_aps()` → `ap_fail()` on counter wrap | Build the board dir and `nm` for **exactly one** `psci_cpu_id` with the board object ahead of `-lstartup`; then M2's six `cpu N up MPIDR=..` lines. TF-A EL2 warm-boot on T234 is VENDOR_CLAIM by analogy with T194 — M2 is the test |
| **K8** | `-Q enable,el2-host` is satisfiable (EL2 entry + `ID_AA64MMFR1_EL1` VH field, checked as `& 0x0f00` at `hypervisor.c:47`); in that mode `init_qtime_v8gt(27,28)` sets `qtime->intr = 28` **unconditionally**. Whether Tegra234 **wires** that NS-EL2 virtual-timer PPI 12 is **UNKNOWN**. | UNSETTLED | Source VERIFIED (`hypervisor.c:32-58,91-95`; `init_qtime.c:28`; `init_qtime_v8gt.c:56-60`). New live evidence: `/proc/device-tree/timer/interrupts` decodes to **exactly four** PPI entries — 13, 14, 11, 10 — no PPI 12. That proves Linux does not use it, **not** that the hardware lacks it | The M1 `-t` probe: arm `CNTHV_CVAL_EL2`/`CNTHV_CTL_EL2`, read `GICR_ISPENDR0` bit 28 at `0xF450220`, print `HV-timer PPI28: wired\|absent`. Must run **before** the M3 image is built. Fallback `-Q enable,el1-host`, every number relabelled |
| **K9** | **A CCPLEX watchdog IS armed at hand-off.** `/dev/watchdog0` → `2080000.timer` (not the `status="disabled"` node `watchdog@2190000` the synthesis looked at); systemd sets 2 min; `WDT0 WDTCR=0x00710010, WDTSR=0x00000011` = counting. WDT1 idle. | CONTESTED → resolved **against** the original claim | VERIFIED twice independently: `raw/orin-readonly-followup-2.txt` register peek + dmesg `Using hardware watchdog 'NVIDIA Tegra186 WDT'` / `Set hardware watchdog to 2min`; a live verification lens reached the same conclusion by a different route (`systemctl show -p RuntimeWatchdogUSec` = `2min`) | Whether systemd **disarms** it on the `kernel_kexec` path or leaves it armed is HYPOTHESIS — M0's `hang` test decides. **Plan changes:** the shim's WDT-arming code (§3.3 step 5 of the synthesis) is **dropped**; startup's `-W` policy becomes **mandatory** for M3/M4; every experiment is assumed to have ~2 min unless proven otherwise |
| **K10** | A zero-hardware black box exists: a live pstore ramoops **console** zone (`printk: console [ramoops-1] enabled`) backed by the 2 MiB `no-map` carveout at `0x2725F0000`, and **retention across a reset is already demonstrated** — `/sys/fs/pstore` holds `console-ramoops-0` (5,571 B) and `dmesg-ramoops-0` (67,970 B) dated 2026-09-08 23:30-23:33, from the board's own drop-off. **No pmsg zone** (`/dev/pmsg0` absent; the DT node carries no `pmsg-size`, so the zone genuinely does not exist). **Upgraded 2026-09-09 after this table was written:** the zone geometry is no longer unknown — DT gives `record-size 0x10000`, `console-size 0x80000`, no ECC, so the console zone sits at `0x2_72770000`, and a root `mmap` of `/dev/mem` reads it despite `STRICT_DEVMEM=y`. The header is three LE words (`sig` = `DBGC` `0x43474244`, `start`, `size`) then data. See [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md). | SUPPORTED | VERIFIED: `raw/orin-ttys.txt:67-68`; DT node `compatible="ramoops"`, `reg=0x2725F0000/0x200000`, `no-map` (`raw/orin-devicetree.txt:177-185`); pstore listing in `raw/orin-readonly-followup-2.txt` | **Zone offsets stay CONTESTED:** the repo's own capture reads `/sys/module/ramoops/parameters/*` as **empty**, while a verification lens reports `mem_address=0x2725f0000, mem_size=2097152, record_size=65536, console_size=524288, ftrace=0, pmsg=0` plus a dmesg `ramoops: using 0x200000@0x2725f0000` line that appears in **no** raw capture. Settle by re-reading both and saving to `raw/`. **Plan change:** the §7 pmsg round-trip pre-flight **cannot be run as written** — drop it. Retention across a **PSCI SYSTEM_RESET / WDT** reset specifically is still HYPOTHESIS (the recovered records came from ordinary resets) |
| **K11** | The measurement **design** is fixed — guest = `qhv/guest/output/ifs.bin`, 9,783,916 B, sha256 `968029…7cf4f` (a gitignored build output, so "byte-identical" is checkable on the owner's machines only, never by a reader of this repo); `cycles_per_sec = 31250000` (32 ns tick); CSV schema per `diff-results.sh:19,57` — but the **pipeline is unvalidated**: Class-10 event IDs (Guest Entry 0, Guest Exit 1, ID 7 at_entry/at_exit) are **VENDOR_CLAIM** only, `ClockCycles()` reading the generic counter is **HYPOTHESIS**, and the "1-2 min at 11 KB/s" throughput estimate has never been exercised. | **REFUTED** (as "well-defined and comparable") | Guest sha256 and CSV schema VERIFIED. CNTFRQ 31.25 MHz / 32 ns VERIFIED from dmesg | The zero-cost dry run: execute the `tracelogger -r -M -S 8M` + `traceprinter \| grep` recipe **inside the existing Windows-TCG QHV host image** and confirm Class-10 IDs 0/1/7 actually appear, plus a 1 s `ClockCycles()` vs `clock_gettime()` comparison. **M4 is blocked on that dry run**, not on the board |
| **K12** | The BSP zip's startup lib **and** the `armv8_fm` board **do** build unmodified under the win64 SDP 8.0 tooling — but the order is lib `make install` **then** board (`make hinstall` alone leaves `asmoff.def` missing), and the symbol gate must be **"no `efi_entry_point`/`uefi_init`/`acpi_`"**, because three `uefi_*_f` symbols (`uefi_exit_boot_services_f`, `uefi_io_resume_f`, `uefi_io_suspend_f`) **are** linked. `display_char_tcu` exists nowhere in the SDP or BSP — we write it. The `t234-orin-nano` board dir does not exist yet. | **REFUTED** (as worded) / toolchain half **VERIFIED** | [`build-armv8_fm.md`](../results/orin-native-port/20260909T1100Z/build-armv8_fm.md): both `make install` steps exit 0; `startup-armv8_fm` = 632,224 B; `gic_v3_set_paddr_range`, `psci_smc`, `hyp_enable_el2_host`, `hypervisor_init`, `fdt_init`, `init_qtime_v8gt`, `cpuid_a78ae` all present (`raw/build-armv8_fm-ours-symbols.txt`) | Whether a **Tegra234** board dir builds and links `display_char_tcu` is still UNKNOWN — first action #4 below. The "P — prep" effort row loses its main uncertainty either way |

Two buildfile syntax corrections also came out of the compile-only work
([`build-m1-placeholder-ifs.md`](../results/orin-native-port/20260909T1100Z/build-m1-placeholder-ifs.md)):
mkifs 8.0 wants `[virtual=aarch64le,raw] .bootstrap = {`, not `boot = {`; and `[+keeplinked]` is a
**per-file** attribute, not a global one.

---

## 3. Loader

### 3.1 Primary: `kexec_file_load` from the running L4T, 8 KiB shim + raw IFS

Everything it raises is inside code we write; nothing persistent is touched (no ESP, no UEFI variables, no
extlinux, no QSPI, no `/boot`); recovery is a power cycle to an untouched L4T; iteration is `scp` + two
commands. Board preconditions VERIFIED in `raw/orin-kexec.txt`: `CONFIG_KEXEC=y`, `CONFIG_KEXEC_FILE=y`,
`# CONFIG_KEXEC_SIG is not set`, `kexec_load_disabled=0`, no lockdown, Secure Boot disabled, kexec-tools
2.0.22, `kexec_loaded=0`.

### 3.2 Payload layout

`t234-qnx.kimg` = `[8 KiB shim page]` ‖ `[ifs.bin built with [image=0x80082000] [virtual=aarch64le,raw]]`.

**Sized 2026-09-09, once the shim was written:** the page is 8 KiB, not 4. `VBAR_EL2` needs a 2 KiB-aligned
vector table that is itself 2 KiB, and the common exception handler has to live clear of all sixteen slots;
with the header, the state-bank printer and its strings that does not fit in 4 KiB. `build-shim.sh` fails
the build if the page is not exactly 8192 bytes, so the two cannot drift apart.

Shim byte 0 is the 64-byte arm64 Image header: `code0 = b shim_body`, `code1 = nop`,
`text_offset = 0x80000`, `image_size` = file size rounded to 2 MiB, `flags = 0`, magic `ARM\x64` at 0x38.
The header must be **prefixed, never overlaid**: the shipped raw.boot stub's three instructions occupy
bytes 0x00-0x0B, so its third instruction sits exactly where the header's `text_offset` field goes, and no
shipped IFS carries the magic (VERIFIED `raw/ifs-first-64-bytes.txt`; opcodes withheld — the repo does not publish machine code of QNX-shipped binaries, QDL v7 4.6(c) — the same rule
applied to the GICv3 report earlier today).

Placement arithmetic per K2 lands the header at `0x80080000`, the shim body and vectors in the same 8 KiB
page, the IFS at `0x80082000` — **HYPOTHESIS on this board until the `kexec -d` check runs.** The IFS half is VERIFIED: at
that base `dumpifs` reports `*.boot` at `0x80082000`, `startup_vaddr = 0x80083800` (a 32-bit value, so the stub's word-sized load of it still works), whole image ending `0x802b1000` — well inside the window with room for M3.

### 3.3 Entry contract and shim duties

Entry per K1. Inherited and **not** cleaned by Linux: `HCR_EL2.E2H/TGE`, stale `VBAR_EL2`, whatever Linux's
`arch_timer` left armed, a live GICD/GICR, `MDCR/HSTR/ICH_HCR_EL2` as-is. Shim (pure asm,
position-independent, no stack, `x0` preserved in `x20`), in order:

1. `VBAR_EL2` = shim vectors; each prints `EXC <n> ESR=.. ELR=.. FAR=..` then PSCI `SYSTEM_RESET`
   (`0x84000009`). These stay live through startup: the library writes only `vbar_el1`
   (`cstart.S:77-78`, `smp_start.S:43-44`) and `vbar_el2` only under `-Q enable,el1-host`
   (`hypervisor_enable.S:38-43`) — all VERIFIED.
2. One bank line: `T234-SHIM EL=.. HCR=.. SCTLR2=.. MMFR1=.. MPIDR=.. CNTFRQ=.. CNTHCTL=.. CNTHP_CTL=..
   MDCR=.. WDT0CR/SR=.. WDT1CR/SR=.. TXMB=<raw word before first write> PC=.. X0=.. DTBMAGIC=..`.
3. `CurrentEL != 2` → print `EL!=2 abort`, `SYSTEM_RESET` (kill criterion (a)).
4. Minimal normalisation of what the library does not touch (K3): with E2H still 1, `CNTP_CTL_EL0 = 0` and
   `CNTV_CTL_EL0 = 0` (CNTHP/CNTHV aliases under E2H); then `HCR_EL2 = 0x8000_0000` + `ISB`; then
   `CNTHP_CTL_EL2 = 0`, `CNTV_CTL_EL0 = 0`, `CNTP_CTL_EL0 = 0` (EL1 views), `MDCR_EL2 = 0`, `HSTR_EL2 = 0`,
   `ICH_HCR_EL2 = 0`. Everything else is left to `at_el2`; `SHIM_FULL_NORMALISE=1` bisects.
   **Note the shim is only clearing E2H for the hand-off** — the library re-asserts it in `hyp_enable_el2_host`.
5. ~~Optional dead-man WDT arming~~ — **dropped (K9)**: WDT0 is already armed and counting at 2 min. The
   shim only *reads and prints* WDT0/WDT1 CR/SR, which it already does in step 2.
6. Landing check: `adr` of the shim page vs. the baked link address; mismatch → `BAD-LANDING pc=..
   expect=..` + `SYSTEM_RESET`. `SHIM_RELOCATE=1` (memmove, with an overlap guard refusing destinations that
   overlap the shim page or `[x0, x0+fdt_totalsize)`) is a labelled fallback only.
7. Modes (`shim.mode=probe|hang|jump`, from a reserved header byte or `/chosen/bootargs`): `probe` = bank +
   reset; `hang` = bank + `wfi` loop (this is now the **watchdog** test: does the un-petted WDT0 return the
   board on its own?); `jump` = `mov x0,x20; x1=x2=x3=0; br` the IFS at the shim's own address + 0x2000, which the landing check
   has just confirmed is `0x80082000`.

### 3.4 Owner command sequence

```
# 0. acceptance test — loads into kernel memory, no reboot, nothing persistent (settles K2):
sudo kexec -s -l t234-shim.kimg ; cat /sys/kernel/kexec_loaded ; kexec -d ; sudo kexec -u
# 1. quiesce DMA masters (forum precedent: Orin NX kexec needed nvidia_drm unloaded):
sudo systemctl isolate multi-user.target
sudo rmmod nvidia_drm nvidia_modeset nvgpu       # ignore failures; then re-read /proc/iomem (K5)
# 2. pin the clock (governor is schedutil, VERIFIED) and pre-arm the uarta fallback (needs sudo, VERIFIED):
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq        # record it
sudo stty -F /dev/ttyTHS1 115200 raw ; sudo sh -c 'sleep 100000 < /dev/ttyTHS1' &
# 3. load and go, under setsid nohup so an ssh drop does not kill it:
sudo kexec -s -l t234-qnx.kimg
sudo systemctl kexec            # clean SD unmount, then kernel_kexec()
```

The synthesis' `systemctl mask --runtime kexec-load.service` step is **removed**: `/etc/default/kexec` has
`LOAD_KEXEC=false` (VERIFIED), so nothing re-loads a Linux kernel over our payload at shutdown.

### 3.5 Fallbacks, and what is rejected outright

**A — `kexec_load` via purgatory:** `sudo kexec -c -l t234-qnx.kimg --dtb=<edited.dtb> --mem-min=0x80000000
--mem-max=0xBDFFFFFF -i`. Allows an edited DTB (e.g. adding `"arm,psci"` and a `/memory@80000000` node) and
pins placement; `kexec -d` prints segment addresses on this path.

**B — UEFI PE launched from the FV-embedded UEFI Shell** (Boot0007, VERIFIED present), also the optional M5
cross-check: same IFS with `[virtual=aarch64le,uefi]`, board `_start.S = b efi_entry_point`,
`init_raminfo_efi()` over the pre-`ExitBootServices` map snapshot, DTB via
`uefi_find_config_tbl(DEVICE_TREE_GUID)`. Copy the PE to the ESP as a **new** file only, after backing up
`extlinux.conf` and `BOOTAA64.efi`. Zero variable writes. Open: a relocation-stripped PE loads only at its
ImageBase (try a `0x90000000`-range `[image=]` first; check the header with `readelf`/`od`, never
disassembly); whether `mkifsf_uefi` emits a loadable AArch64 PE is REPORTED, not reproduced.

**Never:** `efibootmgr -c` (it prepends to `BootOrder` — VERIFIED in the tool's source — so a hanging PE
becomes the default boot, and every attempt writes the QSPI variable store); replacing `BOOTAA64.efi`; GRUB
chain-load; `L4TDefaultBootMode` changes; a default-label `LINUX=` swap in `extlinux.conf`; `kexec -p`;
editing `/etc/default/kexec`; any QSPI/BCT/nvbootctrl/A-B change; any reflash. Entering the library `_start`
→ `cstart` → `at_el2` path while Boot Services are live is also forbidden — it turns off `SCTLR_EL2.{M,C,I}`
and rewrites `HCR_EL2` under the firmware's feet.

---

## 4. Console

### 4.1 Primary: Tegra Combined UART over the HSP mailbox, polled

Addresses and word format per K4. **Writer:** poll `[TX] & BIT31 == 0` with a **bounded** CNTPCT spin
(~20 ms — never hang on a dead SPE), then `str32 [TX] = BIT31|BIT26|(n<<24)|bytes`; on timeout drop the byte
and count it (`TCU drops=<n>`). **Reader** (kernel `poll_key` only): if `[RX] & BIT31`, consume, write `0`
to release. 32-bit accesses only, device memory, two mappings (different HSP blocks).

Physical side (VENDOR_CLAIM, two NVIDIA sources disagree on pin direction): J14 12-pin header, UART2 DEBUG,
3.3 V, 115200 8N1. The two NVIDIA sources split as: the Board Automation page says **pin 3** = UART2 TXD,
the carrier spec SP-11324-001 Table 3-4 says **pin 4** = UART2_TXD (module output). Neither outranks the
other; try adapter RX on pin 4, then pin 3 — a wrong guess costs one swap, not damage. GND pin 11. The same header
carries the MB1/MB2/UEFI/L4T logs, so the wiring is validated by the L4T boot log before any QNX code exists.

### 4.2 Four implementations of the one protocol (all our own code)

1. **Shim asm** (M0) — `tcu_putc`, hex printers, the register bank.
2. **`hw_sertcu.c`** — `init_tcu()`/`put_tcu()` for the `debug_device` table; device string
   `"0x0C168000,0x03C10000"`.
3. **`callout_debug_tcu.S`** — `display_char_tcu` / `poll_key_tcu` / `break_detect_tcu`, on the Apache-2.0
   `callout_debug_tegra.S` two-aperture patch pattern. **This symbol exists nowhere in the SDP or BSP (K12);
   we write it.** procnto's `kprintf`, `display_msg`, crash dumps and KD all ride it.
4. **`tcu-cat`** (~60 lines, `mmap_device_memory` + bounded polls, `-m "text"`) and **`stamp`** (~30 lines,
   prints `ClockCycles()` when a substring passes). No resource manager on the M1-M4 path.
5. **`devc-tcu`** (M1b, optional) only if an interactive shell is wanted and uarta does not work.

Ceiling: the SPE's UART at 115200, ~11 KB/s — fine for logs, marginal for traces (M4 filters on-target).
**That ceiling is now in tension with the ~2-minute watchdog window (K9)** — see M4.

### 4.3 Fallback console and black box

**uarta** (`serial@3100000`, `ttyTHS1`, J12 pins 8/10, SPI 112 = INTID 144, 16550 at 4-byte stride) is free
under L4T but **root-owned** — the "open it before kexec to leave it clocked" step needs `sudo` (the
synthesis omitted this). That the BPMP-owned clock/reset survives the hand-off is HYPOTHESIS. Then startup
`-D tegra8250` + `devc-ser8250 -e -b115200 -c<clk>/16 0x3100000^2,144` is the zero-new-code shell.

**RAM black box** per K10, now a **primary** output path rather than a fallback: mirror every shim /
`put_tcu` byte into the ramoops **console zone at `0x2_72770000`** (carveout + `0x180000`), writing the text
at +12 and setting the `start` and `size` words to the byte count while leaving the `DBGC` signature word
alone; pstore then surfaces it as `/sys/fs/pstore/console-ramoops-0` after the reset. [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md).
Retention across a reset is **demonstrated** (records from 2026-09-08 sit in `/sys/fs/pstore` today), but the
zone offsets are contested; if they stay unknowable, write plain text into the last 256 KiB of the carveout
and read it back with `dd if=/dev/mem` (HYPOTHESIS — `CONFIG_STRICT_DEVMEM=y`, though device ranges did read
during the register peek). **The pmsg round-trip pre-flight is dropped:** no `/dev/pmsg0` on this kernel.
The Power-LED heartbeat (`shim.led=1`) stays a one-bit last resort, never load-bearing.

---

## 5. Startup board directory

`src/hardware/startup/boards/t234-orin-nano/` in a **private** build tree, built against the BSP zip's
`lib/public` headers with `boards/common.mk` unchanged, linking the SDP's `libstartup.a` + `libfdt.a` +
`libdrvr.a` + `liblzo2.a` + `libucl.a`. **Build order is lib `make install` first, then the board** (K12).
Templates: the Apache-2.0 `armv8_fm` files and the public Pi 4 BSP `main.c` for call order. `armv8_fm/main.c`
and `boards/public/aarch64/ls10x6a.h` carry the proprietary licence header — read for call order only, never
copied.

~9 new files, ~700-900 lines:

| file | purpose | correction applied |
|---|---|---|
| `main.c` | `fdt_init(boot_regs[0])`; **`psci_call = psci_smc; in_hvc = 0;` unconditionally** (K7); getopt `COMMON_OPTIONS_STRING "m:W:t"` — **corrected 2026-09-09:** the plan first wrote `"D:W:T"`, but `COMMON_OPTIONS_STRING` is `CPU_COMMON_OPTIONS_STRING "ACc:D:F:f:I:i:K:M:N:o:P:R:S:Tvr:j:ZH"` with `CPU_COMMON_OPTIONS_STRING` = `"Q:E:X:Uu:"` (both VERIFIED in `lib/public/startup.h:163` and `lib/public/aarch64/cpu_startup.h:55`), so **`D` and `T` are already taken** — `-D` is the debug-device selector we want anyway and `-Q` is the hypervisor option. Free letters are `abdeghklmnpqstwxyzBGJLOVWY`; the board takes `-m` (RAM size, as `armv8_fm` does), `-W` (watchdog policy) and lowercase `-t` (the EL2 virtual-timer PPI probe, formerly `-T`); `select_debug()`; **`wdt_report()` then the `-W` policy — now mandatory, not advisory (K9)**; `init_raminfo()`; `avoid_ram(fdt)`; `avoid_ram(0x80080000, 8192)` — the whole shim page, or QNX's allocator could reclaim the live vector table and handler at 0x80081000-0x80081fff, which stay resident through startup; `avoid_ram(x)`; `hypervisor_init(0)`; `init_smp()`; `init_mmu()`; `init_intrinfo()`; `init_qtime()`; the `-t` probe; `add_typed_string(_CS_MACHINE, …)`; `add_callout_array(callouts_reboot_psci_smc)`; `init_system_private()`; `print_syspage()` | K7, K9 |
| `init_raminfo.c` | **Hard-coded, not DTB** (no `/memory` node). M0-M2: `add_ram(0x80000000, 0x3E000000)` only. **M3+: the second window must be re-derived from a fresh `/proc/iomem` read after the `rmmod` step, not hard-coded from the synthesis' single 5.4 GiB line (K5).** Never `0xBE000000-0xC1FFFFFF`, never `0x40000000` SysRAM, never the carveouts | K5 |
| `aarch64/init_intrinfo.c` | Pre-quiesce (adds the `ICACTIVER` clearing the library omits); **`gic_v3_set_paddr_range(0x0F400000, 0x0F440000, 0x200000, NULL_PADDR)`** — *not* the auto-sizing `gic_v3_set_paddr()` the `armv8_fm` template uses (K6); `gic_v3_use_mm_reg_callouts(<gicc>, 0)` for sysreg callouts; `gic_v3_initialize()`; one SPI intrinfo for 960 SPIs | K6 |
| `board_smp.c` | `board_smp_num_cpu() = fdt_num_cpu()` capped by `-P`; records MPIDRs from `/cpus` reg cells; `board_smp_start() = psci_smp_start()` | |
| `psci_cpu_id.c` | Board override, index → `{0x0,0x100,0x200,0x300,0x10200,0x10300}`. **Archive link order must be verified by `nm`, not assumed** (K7) | K7 |
| `hw_sertcu.c`, `aarch64/callout_debug_tcu.S` | §4.2 (2) and (3) — **written from scratch** (K12) | K12 |
| `wdt.c` | Read + `kprintf` WDT0 `0x02190000` / WDT1 `0x021A0000` CR/SR **always**. `-Wdisable` = `WDTUR 0xC45A` unlock + `WDTCMDR` disable; `-Wkeep`; kicker via `wdtkick` (Apache-2.0, in the BSP zip). **Default flips to `-Wdisable` for M3/M4** because WDT0 is armed (K9) | K9 |
| `init_asinfo.c`, `tweak_cmdline.c`, `build`, `Makefile`, `pinfo.mk` | `fdt_asinfo()` registers the DTB for qvm; board options; `armv8_fm` skeleton | |

`nm` gate on the result: `gic_v3_set_paddr_range`, `psci_smc`, `hyp_enable_el2_host`, `display_char_tcu`
present; **exactly one** `psci_cpu_id` (the board's); **no `efi_entry_point`, no `uefi_init`, no `acpi_`** —
note the three `uefi_*_f` symbols are expected and are *not* a failure (K12).

`-Q enable,el2-host` is satisfied by: EL2 entry (K1) → `at_el2` hands `cstart` E2H=0/MMU-off (K3) →
`arch_hypervisor_validate_flags()` finds `CurrentEL == 2` and VH → "Enabling EL2 host hypervisor support
(VHE)". Secondaries come back at EL2 via PSCI and pass through the same `at_el2` (K7). The one open hardware
question is INTID 28 (K8).

---

## 6. Milestone ladder

### M0 — Sign of life (no QNX code runs)

Prove kexec hands a non-Linux payload control at EL2; prove the TCU (or the black box) is usable after Linux
is gone; measure what Linux left; prove the board comes back.

**Pre-flight (read-only, mostly already done):** `/etc/default/kexec` ✓ (`LOAD_KEXEC=false`); pstore listing
✓; WDT/TCU register peek ✓; governor ✓. **Still needed:** the
`kexec -s -l` acceptance test (K2). **The pmsg retention test is dropped** — no `/dev/pmsg0`.

**Steps.** (1) Build `t234-shim.kimg`; `od` check (magic at 0x38, `text_offset` at 0x08, size = 8192 —
`build-shim.sh` does this check itself and fails the build on a mismatch).
(2) `probe` mode: quiesce, load, `systemctl kexec` under `setsid nohup`. Expect the bank line within ~2 s of
Linux's "Bye!", then reset, L4T back in ~60 s. (3) **`hang` mode with no shim WDT code at all** — this now
tests whether the *already-armed* WDT0 returns the board unattended (K9). (4) A deliberate `brk` variant to
prove the vector path prints `EXC` and resets. (5) Repeat (2) once via the purgatory path.

**Pass:** bank shows `EL=2`, `DTBMAGIC=D00DFEED`, a recorded `HCR`, WDT0 CR/SR matching the pre-kexec peek
(or not — either is a finding), `TXMB` bit 31 clear before the first write, `TCU drops=0`; and either the
adapter shows the line or pstore carries it after the reset.

**Recovery in every failure mode:** power cycle or reset → the unchanged L4T from an untouched ESP/QSPI/SD.
Never `kexec -p`. Sessions stay short; the board is shared.

### M1 — procnto + user space on one CPU (EL1), then M1b at EL2

**Steps.** (1) Board directory built; `nm` gate per §5. (2) `tcu-cat`, `stamp`. (3) `mkifs` the M1 buildfile
(`.bootstrap` syntax, per-file `[+keeplinked]`, `[-compress]`); `dumpifs -v`; concatenate; `od`.
(4) First boot `-vvv -P1 -Q disable -m992M -Wkeep -t -Dtcu`; on the very first attempt keep the shim in
full-normalise mode and print the bank **before and after** normalisation — a free bisect of "kexec entry
works" vs "normalisation works". (5) Read the syspage: `Cortex-A78ae`, qtime 31,250,000 Hz, the 992 MiB
range, GICv3 960 SPIs, `HV-timer PPI28: wired|absent`, WDT lines. (6) Iterate on faults via the shim vectors
+ `addr2line` on the `[+keeplinked]` ELFs. (7) M1b: `-Q enable,el2-host -P1`, expect the VHE line.

**Pass:** in order — shim bank → startup banner → `print_syspage()` → `T234 M1: procnto up` → `T234 M1: user
space up` → `pidin info` (1 CPU, ~950 MB) → a `pidin` listing → a `cksum` matching the PC-side value. If the
watchdog stays armed across kexec, each attempt has ~2 min — enough here, not enough later.

### M2 — SMP: six A78AE cores

Bisect `-P2` → `-P4` → `-P6`; per-CPU `cpu N up MPIDR=.. GICR=..` prints; `pidin info` CPU count; six busy
processes; a `tracelogger` sanity check; `shutdown -b` returns L4T. Expected GICR bases `0xF440000 /
0xF460000 / 0xF480000 / 0xF4A0000 / 0xF500000 / 0xF520000`. `-P4` (cluster 0 only) is the documented
degraded fallback and must be **recorded as degraded** if used. An idle soak doubles as the `-W` test: with
WDT0 armed, an un-kicked soak simply resets at ~2 min.

**Pass:** `pidin info` reports 6 CPUs (or 4, recorded as degraded); one `cpu N up` line per core with the
expected MPIDR and GICR base; a 60 s six-process load with no fault; `shutdown -b` returns L4T. **Fail** =
any core that never reports up, or an `ap_fail()` message from `start_aps()`.

### M3 — QHV host natively at EL2 + byte-identical guest; first hardware-timed number

Image adds the hypervisor set exactly as the cloud host's build lists it (`qvm`, `qvm-check`, `vdev-pl011`,
`vdev-virtio-console`, `vdev-shmem`, `libfdt.so`, `tracelogger`/`traceprinter`, slogger2) plus
`/proc/boot/guest-ifs.bin` = the cloud-leg guest (sha256 `968029…7cf4f`), and a `g2.conf` that is the
cloud-leg config **minus virtio-blk**. Startup runs `-Q enable,el2-host` (or `el1-host` per the `-t` verdict,
with every number relabelled) and **`-Wdisable` or a `wdtkick` kicker — mandatory (K9)**: guest boot plus a
trace capture does not fit in 2 minutes. `stamp` prints `ClockCycles()` at `qvm` launch and at the guest
banner; delta / 31,250,000 = seconds; five runs = five kexec rounds. Then the Phase-2 host-client /
guest-server IPC pair over the virtio-console pty, exactly as on the cloud leg, its CSV row printed over the
TCU. **What the number is NOT:** not a per-exit latency (M4), not the twin's full launch→banner headline —
only its `qvm_launched → guest_banner` segment.

**Pass:** the guest banner appears on 5/5 runs; each of the five stamped deltas is recorded with startup
options, `-Q` mode, guest sha256, `-W` policy and CPU MHz (or "clock not verified"); the IPC pair completes
its 15 timed iterations. **Fail** = fewer than 5 banners, or any run whose stamps are missing a field.

### M4 — The qvm-trace number — **blocked on a dry run (K11)**

**Before any board work:** run the `tracelogger -r -M -S 8M -f /dev/shmem/t.kev` +
`traceprinter | grep -E 'QVM|Class 10|GUEST'` recipe **inside the existing Windows-TCG QHV host image** and
confirm Class-10 IDs 0/1/7 actually appear, count the filtered lines, and compare `ClockCycles()` against
`clock_gettime()` over 1 s. Until that runs, the event IDs are VENDOR_CLAIM and the throughput estimate is a
guess. **Fallback if Class-10 events are absent on 8.0.x:** bound the dwell with kernel INTERRUPT/THREAD
events around the qvm vCPU threads, and say so.

On the board: ring-mode capture into `/dev/shmem` around a defined workload, then a filtered listing plus
`cksum` and a line count over the TCU (never the whole `.kev`); PMCCNTR calibration prints actual core MHz.
PC-side parser → `results/hw/orin-native-qvm-trace-latest.csv` in the `diff-results.sh` schema
(`unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes`), `cycles_per_sec = 31250000`,
`notes = orin-native-el2host-qvm-class10-dwell;clock=<MHz|unverified>`. The same script on the Orin-TCG leg
gives the emulated-time counterpart, labelled as such.

**Pass:** the dry run shows Class-10 IDs 0/1/7 present; then 5 board runs of >= 1,000 Exit/Entry pairs each,
`cksum` and line count matching on the PC side, P50 stable within +/-20 % across runs, and `diff-results.sh`
consuming the CSV. **Fail** = no Class-10 events in the dry run (take the INTERRUPT/THREAD fallback and
relabel every number), or P50 spread beyond +/-20 % (report the spread, never average it away).

### M5 (optional) — UEFI Shell cold-boot cross-check

Only after M3/M4, only under the §3.5 Fallback-B rules. PASS = the PE reaches `Entering startup...` and the
M3/M4 medians agree with the kexec-entered ones within run-to-run spread; disagreement makes the
kexec-residual-state caveat a finding in its own right.

---

## 7. What a fully successful M4 still cannot measure

1. A **firmware-booted** QNX: the payload is entered by kexec from Linux — no UEFI→QNX boot time, no firmware
   hand-off timing, and residual state (DRAM, caches/TLB, BPMP-set clocks, thermal, any DMA Linux failed to
   stop) is inherited. Only M5 addresses this.
2. Anything about NVIDIA DRIVE OS, the NVIDIA Hypervisor stack, DRIVE AGX Orin, QNX OS for Safety, ASIL, or
   certified BSPs. This is Experimental Software on a consumer devkit with no vendor path from either side.
3. Any peripheral or DMA path: no SDHCI/PCIe/NVMe/Ethernet/USB/display/GPU/SMMU work; `smmuman` and
   DMA-device containment are never exercised.
4. The heterogeneous Safety(QNX) ↔ Compute(Linux) topology natively — while the QHV host runs, L4T is gone.
   The `br0`/tap numbers in [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv) stay a
   KVM/TCG-leg result.
5. Power, thermal, DVFS: clocks stay wherever BPMP/Linux left them; cycle counts are at an uncontrolled
   frequency, only *reported* by the PMCCNTR calibration.
6. A true one-variable twin diff: console mechanism, entry path, memory map, guest RAM placement and possibly
   host mode (`el1-host`) all differ from the TCG legs. This is a **third bundle**, not "same image, host
   only" — the same honesty §1a already applies to the QHV leg.
7. Timer resolution below 32 ns; low-microsecond dwell is quantised to tens of ticks. And the
   no-instrumentation number: `procnto-smp-instr` + `tracelogger` overhead makes absolute values upper bounds
   (the same kernel on the TCG leg keeps the *diff* fair).
8. Robustness over time: with a 2-minute watchdog window there is no soak beyond minutes unless the watchdog
   is disabled — and disabling it removes the only unattended recovery.
9. Anything publishable until the 4.6(i) consultation is recorded (§9).

---

## 8. Open unknowns, ranked

| # | unknown | class | if it goes the wrong way |
|---|---|---|---|
| 1 | NVIDIA's 5.15.148-tegra `machine_kexec` enters the payload at EL2 (fork never diffed) | HYPOTHESIS (upstream VERIFIED) | Kill criterion (a); pivot to the UEFI Shell, a plan with stacked firmware unknowns |
| 2 | The SPE keeps draining the TCU mailbox after Linux exits | HYPOTHESIS | No primary console; uarta or the black box; M1+ slows 2-3× |
| 3 | NS-EL2 virtual timer PPI 12 / INTID 28 is wired on Tegra234 | UNKNOWN | No VHE number; `el1-host` gives a hardware-timed but differently-labelled one |
| 4 | The watchdog's behaviour across `kernel_kexec` — disarmed by systemd, or still counting | HYPOTHESIS | Either no unattended recovery (manual power cycle, smart plug) **or** a hard 2-min cap on M3/M4 until `-Wdisable`/`wdtkick` works |
| 5 | `qvm` arms stage-2/ICH/virtual-timer state on real A78AE as it does under TCG | HYPOTHESIS | M3 stalls; no support path for Everywhere licensees; the finding is the deliverable |
| 6 | No firmware agent (BPMP/SPE/DCE/PSC) or stale device DMA touches `0x80000000-0xBDFFFFFF` after hand-off | HYPOTHESIS | Irreproducible corruption; escape = a higher `[image=]` and the `-U` EFI-map path |
| 7 | ~~ramoops zone offsets~~ **SETTLED 2026-09-09** — DT gives `record-size 0x10000` / `console-size 0x80000` / no ECC, so the console zone is at `0x2_72770000`; `/dev/mem` reads it despite `STRICT_DEVMEM=y`; the header is `sig 0x43474244` + `start` + `size`. [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md) | VERIFIED | Nothing — this row is closed. Formerly: black box addressable only by the "last 256 KiB + `dd if=/dev/mem`" hack |
| 8 | The `t234-orin-nano` board dir builds and links `display_char_tcu` | UNKNOWN | Makefile work before any signal — but the toolchain itself is now proven (K12) |
| 9 | uarta stays clocked after kexec if opened (as root) from Linux | HYPOTHESIS | No zero-code interactive shell; write `devc-tcu` (+2-3 d) |
| 10 | `gic_v3_gicc_init()` tolerates reading TYPER of unpopulated frames 4/5 en route to 6/7 | HYPOTHESIS | `-P4` keeps the measurement; a `gic_v3.c` patch under 4.1(iii) restores six cores |
| 11 | QHV Class-10 event IDs exist as documented on 8.0.x | VENDOR_CLAIM | M4 falls back to bounding the dwell with kernel INTERRUPT/THREAD events |
| 12 | `mkifsf_uefi` emits a loadable AArch64 PE; EDK2 honours a relocation-less ImageBase | UNKNOWN | Only M5 (optional) is lost |

---

## 9. Licence stance

Governing text: QNX Development License Agreement, Non-Commercial License Class v7 (2025-12-10). The legal
reading below is the project's own, not a BlackBerry statement.

**Owner decision, 2026-09-09:** proceed with ADR-003 option (B); **consult the supervising professor before
publishing any evaluation results** (4.6(i)); keep 4.6(c) clean by using only source and documentation.

- **4.1(iii)** — modifying Source-Code-supplied Software for a Non-Commercial Target System, with no hardware
  list, covers the whole board directory and any local patch to Apache-2.0-headed library sources. The result
  is Experimental Software, as-is, with no vendor path.
- **4.6(c)** — **no disassembly.** Every fact here comes from Apache-2.0 / BSD / GPL **source**, public
  documents, `ar t` / `nm` **name** listings, `readelf -h`, `dumpifs`, and live-board captures. `od` on the
  first 64 bytes of the repo's own IFS images established *where* the shipped stub's instructions sit; the
  opcodes are withheld from every committed file rather than rendered, so no shipped code is reproduced. The 2026-07-28 `startup-qemu-virt` disassembly is not an input. The M5 PE
  header check is a header read, not a code read.
- **4.6(d)** — `startup` is relinked from `libstartup.a` (the standard BSP flow); the shim is **prefixed** to
  the owner-built IFS as a separate page and alters no shipped bytes.
- **4.6(g)** — the repo receives only our own board sources, the shim, `tcu-cat`/`stamp`, buildfiles, scripts
  and **redacted** logs; never `libstartup.a`, the built startup, procnto, qvm, the guest IFS/disk, the BSP
  zip, or any SDP header. ≤ 30-line excerpts of Apache-2.0 files, with paths.
- **4.6(i)** — **no release of performance or functional evaluation results without prior written approval.**
  Every M0-M4 log, CSV, trace and boot-time file stays private, tagged *unpublished pending 4.6(i)
  consultation* — M0/M1 boot logs and `pidin` listings are functional-evaluation output too, not just M4's
  timings. Design, source and procedures evaluate nothing and are publishable. The consultation outcome goes
  into [`findings.md`](findings.md) before any number or boot log goes public; the already-published
  latency/boot numbers are a separate open item for the owner and professor.
- **Hypervisor entitlement** — "QNX Everywhere includes QNX Hypervisor 8.0" rests on QNX's own Pi 4
  walkthrough README (VENDOR_CLAIM); running QHV on an unlisted board is Experimental Software. NVIDIA side:
  unsupported, but not hardware-locked, and a pure-software approach does not affect warranty (VENDOR_CLAIM,
  staff forum replies). The Tegra234 TRM is login-gated and was not consulted; no bypass was attempted.

---

## 10. Effort estimate

Single engineer, working days. These assume the adapter is in hand from M0 step 2; without it the milestones
still run against the black box, at roughly one question per reboot cycle — closer to the high end of each range.

| phase | days | uncertainty | dominant driver |
|---|---|---|---|
| P — prep | **0.5-1** (was 1-2) | LOW | K12 settled: the toolchain and makefiles are proven. Remaining: shim toolchain, header checker, wiring |
| M0 — sign of life | 0.5-3 | HIGH on "TCU alive after Linux" | SPE behaviour, the NVIDIA kernel fork, DMA quiesce hunting |
| M1 — procnto + user space, then M1b | 3-7 | HIGH | First QNX instruction ever on Tegra234; EL2/GIC/raminfo interactions; blind debugging doubles it |
| M2 — SMP | 1-2 | LOW-MED | Both known pitfalls pre-empted; cluster-1 wake UNKNOWN |
| M3 — QHV host + guest, first number | 2-6 | MED-HIGH | INTID 28; stage-2/ICH on real silicon; **plus the watchdog policy, now on the critical path** |
| M4 — qvm-trace | 1-3 | LOW-MED | The dry run first; then 11 KB/s transport and the parser |
| M5 — optional UEFI cross-check | 2-5 | HIGH | PE ImageBase/relocation, `mkifsf_uefi` behaviour |

**Total to M4: 8-22 working days (median ~13)** — 3-6 calendar weeks at part-time cadence on a shared
board; +2-5 for M5. Consistent with ADR-003's "weeks, no vendor path". Not included: the 4.6(i) consultation,
docs consolidation, or any driver work. Stalls no number of days fixes without outside help: no console at
all; `qvm` unable to arm virtualisation on this GIC/timer topology; a watchdog that survives both
`-Wdisable` and a kicker.

---

## 11. First actions today

Windows, compile-only (no board):

- [x] **1. Build the shipped `armv8_fm` board** from the extracted BSP zip with the win64 SDP tooling; `nm`
  the output. **Done — K12's toolchain half VERIFIED**, both `make install` steps exit 0, `startup-armv8_fm`
  = 632,224 B. Order matters: lib **install** (not just `hinstall`) before the board.
  → [`build-armv8_fm.md`](../results/orin-native-port/20260909T1100Z/build-armv8_fm.md)
- [x] **3. `mkifs` a placeholder M1 buildfile** at `[image=0x80082000]`; `dumpifs -v`. **Done — layout
  VERIFIED** (re-run at the 8 KiB base), `*.boot` at `0x80082000`, `startup_vaddr = 0x80083800` (32-bit). Two
  syntax fixes found: `.bootstrap = {`, and per-file `[+keeplinked]`.
  → [`build-m1-placeholder-ifs.md`](../results/orin-native-port/20260909T1100Z/build-m1-placeholder-ifs.md)
- [ ] **2. Write and assemble the M0 shim** (`probe` mode first) with `ntoaarch64-as` / `ntoaarch64-ld
  -Ttext=0x80080000` / `ntoaarch64-objcopy -O binary`, plus the 20-line header checker (`od` at 0x08 / 0x10 /
  0x38, size == 8192). **Drop the WDT-arming code (K9)**; keep the WDT *read* in the register bank.
  **Done 2026-09-09** — `orin-native/shim/t234-shim.S`, all three modes assemble with zero warnings and the
  header checks byte-for-byte; reviewed on four lenses, five findings applied.
- [ ] **4. Create `boards/t234-orin-nano/`** from the Apache-2.0 `armv8_fm` skeleton (never `armv8_fm/main.c`
  or `ls10x6a.h`) with the §5 files stubbed; build; `nm`-check: `gic_v3_set_paddr_range`, `psci_smc`,
  `hyp_enable_el2_host`, `display_char_tcu` present, **exactly one** `psci_cpu_id`, no `efi_entry_point` /
  `uefi_init` / `acpi_` — **expect and allow the three `uefi_*_f` symbols (K12)**.
- [ ] **5. Compile `tcu-cat.c` and `stamp.c`** with `ntoaarch64-gcc`.
- [ ] **6. Source reads only** (Apache-2.0 / BSD): `gic_v3.c:482-500` `gic_v3_use_mm_reg_callouts()` calling
  form with no GICC; `hypervisor_enable.S` `hyp_enable_el2_host` register expectations (and confirm where it
  re-asserts E2H/TGE — K3); edk2-nvidia `TegraCombinedSerialPortLib.c` at r36.4.4 for the RX release
  semantics already VERIFIED on `main`.
- [ ] **7. Generate the no-blk `g2.conf`** and record the guest sha256 (`968029…7cf4f`).
- [ ] **7b. Run the M4 recipe inside the existing Windows-TCG QHV host image** — confirm Class-10 IDs 0/1/7
  appear, count the filtered lines, and compare `ClockCycles()` with `clock_gettime()` over 1 s.
  **This unblocks M4 (K11) and costs nothing.**

Orin, read-only (`sudo -n` reads only):

- [x] **8-11. `/etc/default/kexec`, pstore, watchdog, TCU idle state, governor, uarta ownership.** **Done.**
  Results: `LOAD_KEXEC=false` (hazard gone); pstore black box real with recovered records; **WDT0 armed and
  counting**; TCU TX/RX both `0x00000000`; governor `schedutil`; `/dev/ttyTHS1` root-owned.
  → [`board-readonly-corrections.md`](../results/orin-native-port/20260909T1100Z/board-readonly-corrections.md)
- [x] **11b. ~~Re-read the ramoops zone offsets~~ — DONE 2026-09-09.** The sysfs params are empty; the
  values live in the DT node and the layout was confirmed by reading the memory itself ([blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md)).
  Formerly: two sources disagreed (K10) and the black box's
  addressability depends on it.
- [ ] **11c. After the first `rmmod` session, re-read `/proc/iomem`** and check `dmesg` for SMMU/EMEM faults,
  to convert K5's exclusive-ownership HYPOTHESIS into evidence and to derive the M3+ second RAM window.

First board session, owner decision (not read-only, but no reboot and nothing persistent):

- [ ] **12. `sudo kexec -s -l t234-shim.kimg; cat /sys/kernel/kexec_loaded; kexec -d; sudo kexec -u`** —
  proves the header format and the syscall path, and prints the actual segment addresses. **This is the
  gate on K2**; M0 step 2 should not run before it.

Purchase (the only non-zero cost):

- [ ] **13. A 3.3 V-logic USB-TTL adapter** (FT232RL / CP2102 / CH340, never 5 V-only) + female jumper wires
  for J14 pins 4 / 3 / 11 — do not connect VCC (~USD 5-15) — and a remotely switchable mains plug or relay on
  the DC barrel input (~USD 10-20). The adapter is validated the moment the L4T boot log appears on it.
  **No longer blocking:** with the black box settled ([blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md)) M0 and M1 can run and be read back with
  nothing bought. The adapter buys live output, interactive debugging, the UEFI menus M5 needs, and an end to
  the one-question-per-reboot cadence — a schedule multiplier, not a prerequisite.
  With the watchdog armed (K9), the plug is *probably* redundant — but "probably" is exactly what M0's
  `hang` test is for.

---

## 12. Results hygiene

All outputs under `results/orin-native-port/<ts>/m{0..4}/`, private until §9 clears, redacted before writing
(`<user>`, `<orin-ip>`, `<orin-key>`, `<mac>`), every log stamped with: startup options, `-Q` mode, `-W`
policy, shim build flags, IFS sha256 (sha only), guest IFS sha256, kexec syscall used, `cpuinfo_cur_freq`
before kexec, adapter pin assignment. Boot-time files in the existing `qhv-guest-boot-*-times.txt` format;
CSVs in the `diff-results.sh` schema. Guest IFS and disk images are gitignored build outputs, never committed.

---

## Provenance

Produced by an orchestrated multi-agent workflow on **2026-09-09**: three harvest agents (repo, SDP/BSP,
Orin board — read-only), five research agents (QNX, Tegra234, kexec/TCU, UEFI, prior art), three independent
design agents, three judge agents scoring those designs, one synthesis pass, and a verification pass putting
**12 load-bearing claims through 3 lenses each** (source / docs / live read-only board). This document is the
synthesis revised against those 36 verdicts.

**Nothing here has been executed on the board.** The only VERIFIED items are compile-only builds on the
Windows host and read-only reads of the Orin as it currently runs L4T. No QNX code has run on Tegra234, no
number exists, and no claim in §6 has been demonstrated.
