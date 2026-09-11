# Phase 3b — Native QNX on Jetson Orin Nano: port plan (kick-off 2026-09-09)

**Status: Proposed plan.** [ADR-003](adr-003-hardware-timed-qhv.md) option (B) — native Orin Nano port —
was **accepted by the owner on 2026-09-09**. Licence stance the same day: **proceed**, and **consult the
supervising professor before publishing any evaluation results** (NC QDL v7 4.6(i)); keep 4.6(c) clean by
working from source and documentation only, never disassembly. ~~**No numbers exist yet.** Nothing in this
document has been executed on the board: every milestone below is a proposal, and the only things marked
VERIFIED are compile-only builds on the Windows host and read-only reads of the board as it runs L4T today.~~
**2026-09-11: that was the kick-off state.** M0, M1, M2, M1b and M3 have since run on the board, and dry run 7b
under TCG. The owner has also decided how the rest is measured. The M path finishes as functional passes, a Linux
guest follows, and then one campaign runs on a frozen reference architecture v1. See
[Architecture versions and the measurement freeze](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).

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
   **Corrected 2026-09-09 by running it: unattended recovery is NOT free.** The `hang` test sat there for six and a half minutes against a two-minute watchdog and needed the power pulled; the owner found the board powered, green LED lit, fan stopped — a core parked in `wfi` with nothing able to wake it. Most likely systemd hands the watchdog back on its own shutdown path, which `systemctl kexec` is. So the remaining direction is the one that costs: every experiment has a **~2-minute
   ceiling**. The `-W` policy stops being optional for M3/M4; the shim's WDT-arming code is dropped. **(Corrected 2026-09-10: those two sentences do not follow from the test just described. WDT0 does not fire once the kexec'd payload runs, so there is no two-minute ceiling, and `-W` is insurance.)** **2026-09-10: a run that ends in a reset now recovers on its own.** M1's `shutdown -S reboot` warm-resets the board back to L4T in about 80 s from launch, and the black box survives it ([m1-first-procnto.md](../results/orin-native-port/20260909T1100Z/m1-first-procnto.md), Run 3). A hang still needs the power pulled.
2. **The 992 MiB window is not "the" DRAM, it is the lowest fragment** (K5). `/proc/iomem` shows ~7 disjoint
   System RAM ranges totalling 7.4 GiB; `0x80000000-0xBDFFFFFF` is the lowest, bounded above by an adjacent
   reserved range. Exclusive ownership after `rmmod` remains **HYPOTHESIS**, not a given.
3. **The measurement recipe is a plan, not a validated pipeline** (K11). ~~The QHV Class-10 trace-event IDs are
   still **VENDOR_CLAIM** from an online doc page, and the~~ The "filtered listing fits through the TCU in 1-2 min"
   estimate has never been exercised. ~~A zero-cost dry run inside the existing Windows-TCG QHV image must
   happen before M4 is designed around it.~~ **2026-09-11:** dry run 7b is done. Class-10 IDs 0, 1 and 7 are
   VERIFIED emitted under TCG, and the run corrected the recipe (§6, M4). The board is unconfirmed; M4-F's r1 checks it.
4. **The board-build claim was half right, its symbol gate wrong** (K12). The toolchain question is now
   **settled positively** — the BSP zip's `armv8_fm` board builds unmodified under the win64 SDP 8.0 tooling
   ([`build-armv8_fm.md`](../results/orin-native-port/20260909T1100Z/build-armv8_fm.md), exit 0,
   `startup-armv8_fm` = 632,224 B). But three `uefi_*_f` symbols **are** linked, so the "no `uefi_`" gate is
   wrong; and `display_char_tcu` exists nowhere in the SDP or BSP — we write it.

Two smaller reversals: the `kexec-load` shutdown hazard **does not exist here** (`LOAD_KEXEC=false`), so the
`systemctl mask --runtime` step is dropped; and the governor is `schedutil` at 1,113,600 of 1,344,000 kHz, so
the `performance` pin ~~and the M4 PMCCNTR calibration both stay~~ stays load-bearing **(2026-09-11: m4-design.md's
decision D6(a) records `clock=unverified` instead of calibrating with PMCCNTR; PMCCNTR is a freeze-gate choice, §6)**.
One inter-lens contradiction was
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
VHE) — explicitly *not* a one-variable diff (§7). **2026-09-11 (owner decision):** those numbers are no longer
what the M path delivers. M3 stands, and M4 and M5 finish as functional passes. S1 then adds a Linux guest. The M3
and M4 numbers come from one campaign on the frozen reference architecture v1, and they still feed §1a as a third
bundle ([§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

**Non-goals.** No storage, network, USB, display, GPU, SMMU or PCIe drivers; ~~no Linux guest on the native
leg~~ **(2026-09-11: S1 adds one, without a GPU; §6)**; ~~no cold-boot number unless the optional M5 UEFI
cross-check happens~~ **(2026-09-11: M5 is on the M path as a functional UEFI cold boot; any cold-boot comparison
belongs to the v1 campaign)**; no publication of any number or
functional log before the licence consultation (§9) **(2026-09-11, owner: the M0, M1, M2 and M1b records already
public stay public for now)**; no reflash, no QSPI / UEFI-variable / extlinux / ESP
writes on the primary path; no KVM work (the GICv3/NISV defect in [`orin-port.md`](orin-port.md) is a
separate track).

**Kill criteria.** (a) M0 shows `CurrentEL != 2` at kexec entry → the kexec leg is dead; pivot to the UEFI
Shell alternative (§3.4). (b) TCU, uarta, black box and LED all silent → the port cannot be observed; stop
until the adapter arrives. (c) ~~The INTID 28 probe says absent **and** `el1-host` also fails to arm~~ (ruled out 2026-09-10: M1b found INTID 28 wired on every core) → no
hardware-timed QHV number from this board; the finding itself becomes the deliverable.

---

## 2. Claims register

Twelve claims, in their **corrected** form. "Settles it" names the cheapest decisive test.

| id | claim (corrected form) | status | strongest evidence | what settles it |
|---|---|---|---|---|
| **K1** | kexec from the L4T VHE kernel enters the payload **at EL2**, MMU off, `x0` = DTB PA, `x1-x3` = 0, DAIF masked, exactly one CPU online; `HCR_EL2.E2H` and a stale `VBAR_EL2` survive uncleaned. That an EL2 **physical timer is armed** is HYPOTHESIS — nothing clears it, but nothing shows it armed either. | **CONFIRMED ON THE BOARD 2026-09-09** — the shim reported `EL=2`, `HCR=0x4_8800_0000` (E2H|RW|TGE), `SCTLR2` with M, C and I clear, and a valid device tree in `x0`. The armed-EL2-timer part is confirmed and was worse than hypothesised: `CNTHP_CTL_EL2` read `0x5`, so the timer had not merely been armed, it had already fired. [m0-first-run.md](../results/orin-native-port/20260909T1100Z/m0-first-run.md) | VERIFIED against **upstream v5.15** `machine_kexec.c` / `cpu-reset.{h,S}` / `relocate_kernel.S`: `el2_switch=0` for a VHE kernel, so `__cpu_soft_restart` branches straight to the relocator at EL2; relocator ends `mov x0,x18; x1-x3=xzr; br x17`. Board is VHE: `raw/orin-firmware-el.txt:32,38` | M0's shim bank line (`EL=`, `HCR=`, `DTBMAGIC=`). NVIDIA's 5.15.148-tegra fork of those three files was **never diffed** — obtain `kernel_src.tbz2` or accept M0 as the test |
| **K2** | `image_probe()` checks **only** the `ARM\x64` magic (no signature/PE/content check, `KEXEC_SIG` unset); `image_load()` sets `memsz = image_size + text_offset`, `buf_min = 0`, bottom-up, 2 MiB align, then `kernel_segment->mem += text_offset`; the DTB is placed **top-down** above it. That the first hole is at `0x80000000` (→ landing at `0x80080000`) is **HYPOTHESIS**. | **SETTLED on the board 2026-09-09** — both syscalls accept the shim (`rc=0`, `kexec_loaded=1`, unloaded again; the board never rebooted), and `kexec -d` on the `kexec_load` path puts segment 0 at **`0x80080000`**, the address the landing check expects, so the placement is no longer a hypothesis. What stays open is everything that needs the image to actually run. [m0-kexec-acceptance.md](../results/orin-native-port/20260909T1100Z/m0-kexec-acceptance.md) | Kernel source VERIFIED (v5.15 `kexec_image.c`, `kexec_file.c`, `machine_kexec_file.c`). Board preconditions VERIFIED (`raw/orin-kexec.txt`: `CONFIG_KEXEC{,_FILE}=y`, `# CONFIG_KEXEC_SIG is not set`, `kexec_load_disabled=0`). IFS side VERIFIED by [`build-m1-placeholder-ifs.md`](../results/orin-native-port/20260909T1100Z/build-m1-placeholder-ifs.md) | `sudo kexec -s -l t234-shim.kimg; cat /sys/kernel/kexec_loaded; sudo kexec -u` (no reboot, nothing persistent), then `kexec -d` for the segment addresses. **Blocking gate for M0 step 2.** |
| **K3** | `at_el2` (`lib/aarch64/_start_el1.S:125-197`, **not** 125-190; the `msr hcr_el2` is at **:156**, not :161) normalises SCTLR_EL2 M/C/I + flush, HCR_EL2 ← RW\|HCD(+API/APK) (clearing E2H/TGE as a side effect, **no ISB after**), CPTR_EL2=0, CNTHCTL_EL2=3, VMPIDR/VPIDR, CNTVOFF/VTTBR=0, ICC_SRE_EL2=0xF. MDCR_EL2 / HSTR_EL2 / ICH_HCR_EL2 are written **nowhere** in the lib → the shim owns them, plus VBAR_EL2 and the armed timers. **E2H is not permanently cleared:** `hyp_enable_el2_host` re-asserts E2H/TGE later for VHE. | ~~UNSETTLED~~ **2026-09-11: VERIFIED with the shim's normalisation** (M1 at EL1 and M1b at EL2 both print `NORMALISED`, then boot). Entry without that normalisation: UNKNOWN | Source VERIFIED three times over, incl. lib-wide greps: `vbar_el2` written only at `hypervisor_enable.S:43`; `mdcr_el2`/`hstr_el2`/`ich_hcr_el2` absent from `lib/aarch64` entirely | Whether QNX boots from that inherited state **on real VHE silicon** (vs. TCG, where entry is already E2H=0) is HYPOTHESIS — only M1 settles it. Bisect with `SHIM_FULL_NORMALISE=1`. **2026-09-10 (M2), measured on the secondaries:** they enter through `CPU_ON` with firmware EL2 state `HCR_EL2=0x80000000` (RW only, not VHE), `SCTLR_EL2=0x30c50830`, `MDCR_EL2=0x6`, `HSTR_EL2`/`ICH_HCR_EL2`/timer controls 0 and `CNTFRQ_EL0` programmed, identical on all five cores. The board's `ap_entry.S` applies the shim's CPU0 normalisation to each before `at_el2` ([m2-runs.md](../results/orin-native-port/20260909T1100Z/m2-runs.md)) |
| **K4** | TX = AON HSP shared mailbox 1 `0x0C168000`, RX = TOP0 `0x03C10000`; word = bytes[23:0], count[25:24], Flush[26], HwFlush[27], FULL/doorbell[31]; **RX release-by-writing-0 is VERIFIED from BSD source** (2026-09-09): the whole 32-bit word is written, never a single-bit clear, and a literal zero is the release. NVIDIA's reference implementation does that only on the call that drains the word's last byte, using the register as its own scratch buffer in between — a callout that copies its shape without understanding it would write back a word that never releases. Read the word once, buffer all one to three bytes, write zero. [board-dir-source-reads.md](../results/orin-native-port/20260909T1100Z/board-dir-source-reads.md). That the **SPE keeps demultiplexing after Linux is kexec'd away** stays HYPOTHESIS — and it is the load-bearing half. | ~~UNSETTLED~~ **2026-09-11: VERIFIED** (M0: `TCUDROPS=0` after Linux left; M1: the console captured live over J14) | Addresses agree across three sources (live DT `mboxes`, `tegra-hsp.c` formula, edk2-nvidia Kconfig defaults). Release-by-zero VERIFIED from edk2-nvidia `TegraCombinedSerialPortLib.c` `Read()`. Live idle read VERIFIED: TX and RX both `0x00000000`, bit 31 clear (`raw/orin-readonly-followup-2.txt`) | M0 only: a bank line on the USB-TTL adapter within ~2 s of Linux's "Bye!", `TCU drops=0`. Bounded polls make a dead SPE degrade to silence, never a hang |
| **K5** | RAM must be hard-coded or taken from `/chosen/linux,uefi-mmap-*`, **never** a `/memory` node (none exists). `0x80000000-0xBDFFFFFF` is System RAM — but it is **the lowest of ~7 disjoint System RAM fragments** (7.4 GiB total), bounded above by an adjacent reserved range, not an arbitrary safe window, and it already holds a third child at `0x9d020000` besides kernel code/data (raw/orin-iomem.txt:180,182). **Exclusive ownership after Linux + `rmmod` is HYPOTHESIS.** | **REFUTED** (as originally worded) | VERIFIED: no `/memory` node, `/chosen/linux,uefi-mmap-*` present (`raw/orin-devicetree.txt`); `80000000-bdffffff : System RAM` with only kernel code/data inside (`raw/orin-iomem.txt:180`); no DT carveout lands inside it | `rmmod nvidia_drm nvidia_modeset nvgpu`, then re-read `/proc/iomem` + `dmesg` for SMMU/EMEM faults. **Plan change:** the M3+ second window must be re-derived from `/proc/iomem`, not from the single hard-coded 5.4 GiB line the synthesis proposed |
| **K6** | Plain GICv3: GICD `0x0F400000`, GICR `0x0F440000`/`0x200000` = 16 frames × `0x20000`, populated 0-3 and 6-7, 960 SPIs, sysreg CPU interface, no ITS, no GICV. `gic_v3_set_paddr_range(...,0x200000,NULL_PADDR)` gives `gicr_index_limit=16` so the affinity walk reaches frames 6/7; `gic_v3_initialize()` already zeroes `GICD_CTLR` and all SPI enable/pending (but **not** `ICACTIVER`). | ~~SUPPORTED~~ **2026-09-11: VERIFIED** (M2 at `-P6` bound frames 6 and 7) | Geometry VERIFIED from dmesg (`raw/orin-firmware-el.txt:18-30`). Library mechanics VERIFIED in `gic_v3.c` (`:299-336` limit arithmetic, `:1334-1352` walk with `ASSERT` and no `Last` check, `:980-1000`/`:1496-1502` quiesce, `:1509-1511` MMIO-IPI hardcode) | Caveat the synthesis missed: the **only board source that exists** (`armv8_fm/aarch64/init_intrinfo.c:76`) calls the auto-sizing `gic_v3_set_paddr()` (limit = `board_smp_num_cpu()` = 6 → `ASSERT` at frame 6). Our board **must** call the `_range` form. `-P6` boot at M2 is the test; `-P4` is the fallback |
| **K7** | PSCI `CPU_ON` (SMC64 `0xC4000003`) with a **board** `psci_cpu_id()` returning `{0x0,0x100,0x200,0x300,0x10200,0x10300}` and `psci_call = psci_smc` set explicitly in `main()` (`fdt_psci_configure()` matches the literal `"arm,psci"`; the board DT says `"arm,psci-1.0"`); a CPU that never starts ends in `ap_fail()`, not a silent hang. **Archive link-order override and TF-A returning secondaries at EL2 on T234 are both untested.** | ~~UNSETTLED~~ **2026-09-11: VERIFIED** (M2; see this row's M2 note) | Source VERIFIED: `psci.h:40` `PSCI_CPU_ON = 0xc4000003`; `fdt_psci_configure.c` exact-string match; `psci_smp.c` passes `psci_cpu_id(cpu)` straight into CPU_ON; library `psci_cpu_id.c` returns the index verbatim; `init_smp.c` `start_aps()` → `ap_fail()` on counter wrap | Build the board dir and `nm` for **exactly one** `psci_cpu_id` with the board object ahead of `-lstartup`; then M2's six `cpu N up MPIDR=..` lines. TF-A EL2 warm-boot on T234 is VENDOR_CLAIM by analogy with T194 — M2 is the test. **2026-09-10 (M2): settled on the board.** The override links exactly once (symbol gate), every `CPU_ON` returned success, and all five secondaries entered at EL2 on both clusters. One part of this row was too strong: a CPU that never starts ends in `ap_fail()` only up to the start handshake; the library's later hand-off to the kernel's spin loop had no bound at all, and the board now bounds it itself |
| **K8** | `-Q enable,el2-host` is satisfiable (EL2 entry + `ID_AA64MMFR1_EL1` VH field, checked as `& 0x0f00` at `hypervisor.c:47`); in that mode `init_qtime_v8gt(27,28)` sets `qtime->intr = 28` **unconditionally**. Whether Tegra234 **wires** that NS-EL2 virtual-timer PPI 12 is **UNKNOWN**. | **SETTLED 2026-09-10: wired** on all six cores, Non-secure view ([m1b-runs.md](../results/orin-native-port/20260909T1100Z/m1b-runs.md)) | Source VERIFIED (`hypervisor.c:32-58,91-95`; `init_qtime.c:28`; `init_qtime_v8gt.c:56-60`). New live evidence: `/proc/device-tree/timer/interrupts` decodes to **exactly four** PPI entries — 13, 14, 11, 10 — no PPI 12. That proves Linux does not use it, **not** that the hardware lacks it | The probe as built for M1b (`aarch64/hvtimer.c`): under `-Q enable,el2-host` every core arms CNTHP (INTID 26, the control) and then CNTHV, and watches `GICR_ISPENDR0` at SGI frame + 0x200 (`0x0F450200` on CPU0; the `0xF450220` written here earlier was wrong). It prints `t234: hvtimer cpu N verdict=`. It ran before any M3 image, as required, and said `wired` on every core, so the `-Q enable,el1-host` fallback and its relabelling are not needed |
| **K9** | **A CCPLEX watchdog IS armed at hand-off.** `/dev/watchdog0` → `2080000.timer` (not the `status="disabled"` node `watchdog@2190000` the synthesis looked at); systemd sets 2 min; `WDT0 WDTCR=0x00710010, WDTSR=0x00000011` = counting. WDT1 idle. | CONTESTED → resolved **against** the original claim | VERIFIED twice independently: `raw/orin-readonly-followup-2.txt` register peek + dmesg `Using hardware watchdog 'NVIDIA Tegra186 WDT'` / `Set hardware watchdog to 2min`; a live verification lens reached the same conclusion by a different route (`systemctl show -p RuntimeWatchdogUSec` = `2min`) | Whether systemd **disarms** it on the `kernel_kexec` path or leaves it armed is HYPOTHESIS — M0's `hang` test decides. **Plan changes:** the shim's WDT-arming code (§3.3 step 5 of the synthesis) is **dropped**; startup's `-W` policy becomes **mandatory** for M3/M4; every experiment is assumed to have ~2 min unless proven otherwise. **Corrected by M0's `hang` test:** WDT0 does not fire after the kexec hand-over, so there is no two-minute cap and `-W` is insurance, not a requirement; a hang still needs a power cycle |
| **K10** | A zero-hardware black box exists: a live pstore ramoops **console** zone (`printk: console [ramoops-1] enabled`) backed by the 2 MiB `no-map` carveout at `0x2725F0000`, and **retention across a reset is already demonstrated** — `/sys/fs/pstore` holds `console-ramoops-0` (5,571 B) and `dmesg-ramoops-0` (67,970 B) dated 2026-09-08 23:30-23:33, from the board's own drop-off. **No pmsg zone** (`/dev/pmsg0` absent; the DT node carries no `pmsg-size`, so the zone genuinely does not exist). **Bounded 2026-09-09 by running it:** the zone survives a PSCI reset — the probe run's 419 bytes came back through pstore — but **not a cold power cycle**, after which `/sys/fs/pstore` was empty, including records from days earlier. So the black box carries evidence out of a fault or a deliberate reset, and carries nothing out of a hang. **2026-09-10:** a whole QNX run's 7,252 bytes came back the same way after the image's own `shutdown -S reboot`, including lines the live console lost at the reset ([m1-first-procnto.md](../results/orin-native-port/20260909T1100Z/m1-first-procnto.md), Run 3). [m0-hang-watchdog.md](../results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md) **Upgraded earlier the same day:** the zone geometry is no longer unknown — DT gives `record-size 0x10000`, `console-size 0x80000`, no ECC, so the console zone sits at `0x2_72770000`, and a root `mmap` of `/dev/mem` reads it despite `STRICT_DEVMEM=y`. The header is three LE words (`sig` = `DBGC` `0x43474244`, `start`, `size`) then data. See [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md). | SUPPORTED | VERIFIED: `raw/orin-ttys.txt:67-68`; DT node `compatible="ramoops"`, `reg=0x2725F0000/0x200000`, `no-map` (`raw/orin-devicetree.txt:177-185`); pstore listing in `raw/orin-readonly-followup-2.txt` | ~~**Zone offsets stay CONTESTED:** the repo's own capture reads `/sys/module/ramoops/parameters/*` as **empty**, while a verification lens reports `mem_address=0x2725f0000, mem_size=2097152, record_size=65536, console_size=524288, ftrace=0, pmsg=0` plus a dmesg `ramoops: using 0x200000@0x2725f0000` line that appears in **no** raw capture. Settle by re-reading both and saving to `raw/`.~~ **Plan change:** the §7 pmsg round-trip pre-flight **cannot be run as written** — drop it. ~~Retention across a **PSCI SYSTEM_RESET / WDT** reset specifically is still HYPOTHESIS (the recovered records came from ordinary resets)~~ **2026-09-11:** the offsets were settled on 2026-09-09 ([blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md); §8 row 7). Retention was seen across a PSCI reset (M0's probe run), across the image's own warm reset (M1, Run 3) and across a watchdog reset after a Linux panic (M2). A cold power cycle clears the zone (M0's `hang` test). |
| **K11** | The measurement **design** is fixed — guest = `qhv/guest/output/ifs.bin`, 9,783,916 B, sha256 `968029…7cf4f` (a gitignored build output, so "byte-identical" is checkable on the owner's machines only, never by a reader of this repo); `cycles_per_sec = 31250000` (32 ns tick); CSV schema per `diff-results.sh:19,57` — but the **pipeline is unvalidated**: Class-10 event IDs (Guest Entry 0, Guest Exit 1, ID 7 at_entry/at_exit) ~~are **VENDOR_CLAIM** only, `ClockCycles()` reading the generic counter is **HYPOTHESIS**,~~ and the "1-2 min at 11 KB/s" throughput estimate has never been exercised. **2026-09-11:** the ID numbering is VERIFIED in `sys/trace.h`, and `ClockCycles()` reading `cntvct_el0` is VERIFIED at source level (both per [m4-dryrun-design.md](../results/orin-native-port/20260909T1100Z/m4-dryrun-design.md) Appendix A). Emission is VERIFIED under TCG by dry run 7b; the board is unconfirmed. | **REFUTED** (as "well-defined and comparable") | Guest sha256 and CSV schema VERIFIED. CNTFRQ 31.25 MHz / 32 ns VERIFIED from dmesg | The zero-cost dry run: execute the `tracelogger -r -M -S 8M` + `traceprinter \| grep` recipe **inside the existing Windows-TCG QHV host image** and confirm Class-10 IDs 0/1/7 actually appear, plus a 1 s `ClockCycles()` vs `clock_gettime()` comparison. ~~**M4 is blocked on that dry run**, not on the board~~ **Dry run done 2026-09-11 (checklist 7b): IDs 0, 1 and 7 VERIFIED emitted under TCG; M4 no longer waits on it** |
| **K12** | The BSP zip's startup lib **and** the `armv8_fm` board **do** build unmodified under the win64 SDP 8.0 tooling — but the order is lib `make install` **then** board (`make hinstall` alone leaves `asmoff.def` missing), and the symbol gate must be **"no `efi_entry_point`/`uefi_init`/`acpi_`"**, because three `uefi_*_f` symbols (`uefi_exit_boot_services_f`, `uefi_io_resume_f`, `uefi_io_suspend_f`) **are** linked. `display_char_tcu` exists nowhere in the SDP or BSP — we write it. ~~The `t234-orin-nano` board dir does not exist yet.~~ **2026-09-11: it exists (§11 action 4).** | **REFUTED** (as worded) / toolchain half **VERIFIED** | [`build-armv8_fm.md`](../results/orin-native-port/20260909T1100Z/build-armv8_fm.md): both `make install` steps exit 0; `startup-armv8_fm` = 632,224 B; `gic_v3_set_paddr_range`, `psci_smc`, `hyp_enable_el2_host`, `hypervisor_init`, `fdt_init`, `init_qtime_v8gt`, `cpuid_a78ae` all present (`raw/build-armv8_fm-ours-symbols.txt`) | ~~Whether a **Tegra234** board dir builds and links `display_char_tcu` is still UNKNOWN — first action #4 below.~~ **2026-09-11: closed.** The board directory builds and passes the symbol gate (§11 action 4, 2026-09-09), and M1 printed through its TCU callout on the board (2026-09-10). The "P — prep" effort row loses its main uncertainty either way |

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
page, the IFS at `0x80082000` — **VERIFIED on this board 2026-09-09**: `kexec -d` reports segment 0 at `0x80080000`, size `0x2000`. [m0-kexec-acceptance.md](../results/orin-native-port/20260909T1100Z/m0-kexec-acceptance.md). The IFS half is VERIFIED: at
that base `dumpifs` reports `*.boot` at `0x80082000`, `startup_vaddr = 0x80083800` (a 32-bit value, so the stub's word-sized load of it still works), whole image ending `0x802b1000` — well inside the window with room for M3.

### 3.3 Entry contract and shim duties

Entry per K1. Inherited and **not** cleaned by Linux: `HCR_EL2.E2H/TGE`, stale `VBAR_EL2`, whatever Linux's
`arch_timer` left armed, a live GICD/GICR, `MDCR/HSTR/ICH_HCR_EL2` as-is. Shim (pure asm,
position-independent, no stack, `x0` preserved in `x20`), in order:

1. `VBAR_EL2` = shim vectors; each prints `EXC <n> ESR=.. ELR=.. FAR=..` then PSCI `SYSTEM_RESET`
   (`0x84000009`). These stay live through startup: the library writes only `vbar_el1`
   (`cstart.S:77-78`, `smp_start.S:43-44`) and `vbar_el2` only under `-Q enable,el1-host`
   (`hypervisor_enable.S:38-43`) — all VERIFIED. **Corrected 2026-09-10 (M1b design §1 C5):** they cannot print once startup's C code runs. Their printer uses registers `_main` and `main()` reuse, and after `vstart` the shim page is outside the identity map. Startup now installs its own EL2 table on CPU0 from `board_init`.
2. One bank line: `T234-SHIM EL=.. HCR=.. SCTLR2=.. MMFR1=.. MPIDR=.. CNTFRQ=.. CNTHCTL=.. CNTHP_CTL=..
   MDCR=.. WDT0CR/SR=.. WDT1CR/SR=.. TXMB=<raw word before first write> PC=.. X0=.. DTBMAGIC=..`.
3. `CurrentEL != 2` → print `EL!=2 abort`, `SYSTEM_RESET` (kill criterion (a)).
4. Minimal normalisation of what the library does not touch (K3): with E2H still 1, `CNTP_CTL_EL0 = 0` and
   `CNTV_CTL_EL0 = 0` (CNTHP/CNTHV aliases under E2H); then `HCR_EL2 = 0x8000_0000` + `ISB`; then
   `CNTHP_CTL_EL2 = 0`, `CNTV_CTL_EL0 = 0`, `CNTP_CTL_EL0 = 0` (EL1 views), `MDCR_EL2 = 0`, `HSTR_EL2 = 0`,
   `ICH_HCR_EL2 = 0`. Everything else is left to `at_el2`; `SHIM_FULL_NORMALISE=1` bisects.
   **Note the shim is only clearing E2H for the hand-off** — the library re-asserts it in `hyp_enable_el2_host`.
5. ~~Optional dead-man WDT arming~~ — **dropped (K9)**: WDT0 is already armed and counting at 2 min while Linux runs (it does not fire after the kexec hand-over; M0 `hang` test). The
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
the carrier spec SP-11324-001 Table 3-4 says **pin 4** = UART2_TXD (module output). ~~Neither outranks the
other; try adapter RX on pin 4, then pin 3 — a wrong guess costs one swap, not damage.~~ **2026-09-11:** settled on
2026-09-10 in favour of pin 4; the M1 and M2 captures name it in their headers
([serial-console-wiring.md](../results/orin-native-port/20260909T1100Z/serial-console-wiring.md)). GND pin 11. The same header
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
~~That ceiling is now in tension with the ~2-minute watchdog window (K9)~~ — no longer: WDT0 does not fire after the kexec hand-over, so there is no two-minute window.

### 4.3 Fallback console and black box

**uarta** (`serial@3100000`, `ttyTHS1`, J12 pins 8/10, SPI 112 = INTID 144, 16550 at 4-byte stride) is free
under L4T but **root-owned** — the "open it before kexec to leave it clocked" step needs `sudo` (the
synthesis omitted this). That the BPMP-owned clock/reset survives the hand-off is HYPOTHESIS. Then startup
`-D tegra8250` + `devc-ser8250 -e -b115200 -c<clk>/16 0x3100000^2,144` is the zero-new-code shell.

**RAM black box** per K10, now a **primary** output path rather than a fallback: mirror every shim /
`put_tcu` byte into the ramoops **console zone at `0x2_72770000`** (carveout + `0x180000`), writing the text
at +12 and setting the `start` and `size` words to the byte count while leaving the `DBGC` signature word
alone; pstore then surfaces it as `/sys/fs/pstore/console-ramoops-0` after the reset. [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md).
Retention across a reset is **demonstrated** (records from 2026-09-08 sit in `/sys/fs/pstore` today), ~~but the
zone offsets are contested; if they stay unknowable, write plain text into the last 256 KiB of the carveout
and read it back with `dd if=/dev/mem` (HYPOTHESIS — `CONFIG_STRICT_DEVMEM=y`, though device ranges did read
during the register peek)~~. **2026-09-11:** the offsets were settled on 2026-09-09, so that fallback is not
needed; a cold power cycle clears the zone (K10). **The pmsg round-trip pre-flight is dropped:** no `/dev/pmsg0` on this kernel.
The Power-LED heartbeat (`shim.led=1`) stays a one-bit last resort, never load-bearing.

---

## 5. Startup board directory

`src/hardware/startup/boards/t234-orin-nano/` in a **private** build tree, built against the BSP zip's
`lib/public` headers with `boards/common.mk` unchanged, linking the SDP's `libstartup.a` + `libfdt.a` +
`libdrvr.a` + `liblzo2.a` + `libucl.a`. **Build order is lib `make install` first, then the board** (K12).
Templates: the Apache-2.0 `armv8_fm` files and the public Pi 4 BSP `main.c` for call order. `armv8_fm/main.c`
and `boards/public/aarch64/ls10x6a.h` carry the proprietary licence header — read for call order only, never
copied. **2026-09-11:** the board sources are our own code and are public in `orin-native/startup/t234-orin-nano/`.
`build-board.sh` stages them into the private BSP tree for the build, and nothing from the BSP comes back.

~9 new files, ~700-900 lines:

| file | purpose | correction applied |
|---|---|---|
| `main.c` | `fdt_init(boot_regs[0])`; **`psci_call = psci_smc; in_hvc = 0;` unconditionally** (K7); getopt `COMMON_OPTIONS_STRING "m:W:t"` — **corrected 2026-09-09:** the plan first wrote `"D:W:T"`, but `COMMON_OPTIONS_STRING` is `CPU_COMMON_OPTIONS_STRING "ACc:D:F:f:I:i:K:M:N:o:P:R:S:Tvr:j:ZH"` with `CPU_COMMON_OPTIONS_STRING` = `"Q:E:X:Uu:"` (both VERIFIED in `lib/public/startup.h:163` and `lib/public/aarch64/cpu_startup.h:55`), so **`D` and `T` are already taken** — `-D` is the debug-device selector we want anyway and `-Q` is the hypervisor option. Free letters are `abdeghklmnpqstwxyzBGJLOVWY`; the board takes `-m` (RAM size, as `armv8_fm` does), `-W` (watchdog policy) and lowercase `-t` (the EL2 virtual-timer PPI probe, formerly `-T`); `select_debug()`; **`wdt_report()` then the `-W` policy** ~~— now mandatory, not advisory (K9)~~ **(2026-09-11: insurance only, per M0's `hang` test)**; `init_raminfo()`; `avoid_ram(fdt)`; `avoid_ram(0x80080000, 8192)` — the whole shim page, or QNX's allocator could reclaim the live vector table and handler at 0x80081000-0x80081fff, which stay resident through startup; `avoid_ram(x)`; `hypervisor_init(0)`; `init_smp()`; `init_mmu()`; `init_intrinfo()`; `init_qtime()`; the `-t` probe; `add_typed_string(_CS_MACHINE, …)`; `add_callout_array(callouts_reboot_psci_smc)`; `init_system_private()`; `print_syspage()` | K7, K9 |
| `init_raminfo.c` | **Hard-coded, not DTB** (no `/memory` node). M0-M2: `add_ram(0x80000000, 0x3E000000)` only. **M3+: the second window must be re-derived from a fresh `/proc/iomem` read after the `rmmod` step, not hard-coded from the synthesis' single 5.4 GiB line (K5).** Never `0xBE000000-0xC1FFFFFF`, never `0x40000000` SysRAM, never the carveouts | K5 |
| `aarch64/init_intrinfo.c` | Pre-quiesce (adds the `ICACTIVER` clearing the library omits); **`gic_v3_set_paddr_range(0x0F400000, 0x0F440000, 0x200000, NULL_PADDR)`** — *not* the auto-sizing `gic_v3_set_paddr()` the `armv8_fm` template uses (K6); `gic_v3_use_mm_reg_callouts(<gicc>, 0)` for sysreg callouts; `gic_v3_initialize()`; one SPI intrinfo for 960 SPIs | K6 |
| `board_smp.c` | `board_smp_num_cpu() = fdt_num_cpu()` capped by `-P`; records MPIDRs from `/cpus` reg cells; `board_smp_start() = psci_smp_start()` | |
| `psci_cpu_id.c` | Board override, index → `{0x0,0x100,0x200,0x300,0x10200,0x10300}`. **Archive link order must be verified by `nm`, not assumed** (K7) | K7 |
| `hw_sertcu.c`, `aarch64/callout_debug_tcu.S` | §4.2 (2) and (3) — **written from scratch** (K12) | K12 |
| `wdt.c` | Read + `kprintf` WDT0 `0x02190000` / WDT1 `0x021A0000` CR/SR **always**. `-Wdisable` = `WDTUR 0xC45A` unlock + `WDTCMDR` disable; `-Wkeep`; kicker via `wdtkick` (Apache-2.0, in the BSP zip). ~~**Default flips to `-Wdisable` for M3/M4** because WDT0 is armed (K9)~~ **2026-09-11:** the premise failed. WDT0 does not fire after kexec (M0's `hang` test), so the `-W` policy is insurance | K9 |
| `init_asinfo.c`, `tweak_cmdline.c`, `build`, `Makefile`, `pinfo.mk` | `fdt_asinfo()` registers the DTB for qvm; board options; `armv8_fm` skeleton | |

`nm` gate on the result: `gic_v3_set_paddr_range`, `psci_smc`, `hyp_enable_el2_host`, `display_char_tcu`
present; **exactly one** `psci_cpu_id` (the board's); **no `efi_entry_point`, no `uefi_init`, no `acpi_`** —
note the three `uefi_*_f` symbols are expected and are *not* a failure (K12).

`-Q enable,el2-host` is satisfied by: EL2 entry (K1) → `at_el2` hands `cstart` E2H=0/MMU-off (K3) →
`arch_hypervisor_validate_flags()` finds `CurrentEL == 2` and VH → "Enabling EL2 host hypervisor support
(VHE)". Secondaries come back at EL2 via PSCI and pass through the same `at_el2` (K7). ~~The one open hardware
question is INTID 28 (K8).~~ **2026-09-11:** M1b found INTID 28 wired on all six cores (K8).

---

## 6. Milestone ladder

### Architecture versions and the measurement freeze (decided 2026-09-11)

**The decision.** On 2026-09-11 the owner chose option B for how this project takes its measurements. The owner's reasons:
- A design change here has never adjusted one architecture; each one replaced the whole of it. The cloud leg went from a plain QNX guest under TCG to the QNX Hypervisor inside TCG, and this plan now runs the QNX Hypervisor natively.
- Many cloud-leg measurements were hard to test, because the hardware integration was not finished.
- Some earlier measurements now need redoing only because the architecture changed under them.

The work now runs in this order:
1. **Finish the M path as functional verification only.** M4 becomes r0 and r1: the trace instrument works on the board. Its timed runs (r2) wait. M5 becomes a UEFI cold boot that reaches startup. Its comparison of medians waits.
2. **Then S1:** a Linux guest without a GPU under native qvm, taken from the GPU pass-through research track.
3. **Then freeze reference architecture v1,** fixed by the manifest below.
4. **Then run one measurement campaign on v1:** the M3 and M4 numbers, the M5 comparison and the twin diff. Every record carries the architecture version.

Measurements taken before the freeze become architecture-version history. They are kept, labelled with the architecture they ran on, and not chased.

This section carries no figures. Public figures stay where the inventory below points. Figures from M3 and from dry run 7b stay on the local branch `m3-results-unpublished` (§9).

~~**Awaiting owner confirmation.** This section assumes the M path ends at M5's functional pass. That sets when README PR #1 can merge: after M5-F, without waiting for S1, the freeze or the campaign. Until the owner confirms, PR #1 is not merged.~~
**2026-09-11 (owner):** confirmed. The M path ends at M5-F's functional pass, and README PR #1 can merge then, without waiting for S1, the freeze or the campaign. Still open: whether a failed M5-F also ends the M path (M5-F, "If it fails").

#### Architecture versions

Records made before v1 keep the id of the architecture they ran on. None of them is rewritten.

| id | architecture | dates | what changed | sources |
|---|---|---|---|---|
| A0 | Original design. Cloud: two co-equal QEMU/KVM guests, QNX Safety and Linux Compute, on a Graviton host, with IPC over `br0`/tap virtio-net. Hardware twin: a QEMU/KVM QNX guest beside L4T. Never built. | Apr-May 2026; falsified by 2026-06-11 (non-metal Graviton has no `/dev/kvm`) | The starting design | [ADR-002](phase2-topology-decision.md) §1; [findings.md](findings.md), "Apr 2026 — Phase 0 BSP research" |
| A0′ | Track B: the QNX OS AMI on Graviton, one QNX with no guests. Never built. | decided 2026-06-10 | A second runtime track beside A0 | [findings.md](findings.md), 2026-06-10 two-track decision |
| A1 | Cloud leg per ADR-002. The Windows PC runs QEMU-TCG with `virtualization=on`. Inside it the QHV host runs one QNX guest, with IPC over the qvm virtio-console pty pair. No Linux guest, no `br0`. | first boot and acceptance 2026-06-11 | No KVM and no Linux guest; the hypervisor runs inside the emulation | [ADR-002](phase2-topology-decision.md) §3; [findings.md](findings.md), 2026-06-11 QHV milestone; [digital-twin-design.md](digital-twin-design.md) §1 |
| A2 | Orin plain leg. L4T is the host and plays Compute. The distro QEMU under TCG runs the plain `qnx-safety-vm` IFS, rebuilt with a TCP server. IPC path: virtio-net, `tap-qnx`, `br0`, a native Linux client. The plain IFS was also timed under TCG on Windows. The same leg under KVM hangs on the GICv3/NISV defect. | 2026-07-28/29 | Heterogeneous QNX↔Linux IPC moves to the hardware twin, under TCG | [findings.md](findings.md), 2026-07-28 and 2026-07-29 entries; [orin-port.md](orin-port.md) risk register |
| A3 | Host-agnostic QHV in TCG. A1's images boot unchanged on Windows and on the Orin. "Host" is a bundle of CPU, OS, TCG backend and QEMU build. Each series records its QEMU build, device set and disk mode in its file. | designed 2026-09-08; boots on the Orin, and the release-aligned pair ran, 2026-09-09 | The twin compares the hypervisor topology across two host bundles | [digital-twin-design.md](digital-twin-design.md) §1a; [findings.md](findings.md), 2026-09-08 and 2026-09-09 entries |
| A4 | Native QHV on the Orin (this plan). Entered by kexec from L4T, no QEMU. M1 and M2 run at EL1. M1b runs the VHE host at EL2 on six cores. M3 runs native qvm on four cores with the byte-identical cloud-leg guest and its disk, IPC over virtio-console. L4T is gone while QNX runs. | ADR-003 accepted 2026-09-09; M0 2026-09-09; M1, M2, M1b and M3 2026-09-10 | QEMU is gone; the hypervisor runs on silicon | [ADR-003](adr-003-hardware-timed-qhv.md); M0-M3 below; [findings.md](findings.md), 2026-09-10 entries |
| A5 | Owner target. The native QHV host at EL2 plus a Linux guest under qvm: first without a GPU (S1), GPU pass-through later. It descends from ADR-002 Option B. | planned; on 2026-09-11 S1 was placed before the freeze | Adds a Linux guest, a second RAM window and a new core split | [ADR-002](phase2-topology-decision.md) Option B; the research track, summarised under S1-F below |
| **v1** | Reference architecture v1: A4's native host with S1's Linux guest, fixed by the manifest below, plus two TCG twin legs that boot v1's guests in a QHV host image under QEMU, as A3 does | not frozen | Every measurement from here on is stamped with it | this section |

#### Measurement inventory

Status words: **history** = valid for its architecture, kept, not re-run for its own sake; **superseded** = replaced by a later series on the same architecture; **deferred to the campaign** = measured on v1 only; **not a measurement** = a functional or diagnostic record. Log files named below are in [`../logs/sample-boot/`](../logs/sample-boot/).

**Boot time**

| measurement | arch | record | status |
|---|---|---|---|
| Plain-IFS boot time, Windows against Orin: single runs, then a five-run series per host (2026-07-28); and the boot diff derived from it | A2 | [digital-twin-design.md](digital-twin-design.md) §5; `windows-tcg-qnx-boot-times-n5.txt`, `orin-tcg-qnx-boot-times-n5.txt` | **history.** The two files carry no QEMU-build, device-set or disk-mode stamp, so §5's reading that only the host differs cannot be checked. The QEMU releases likely differed (HYPOTHESIS). ~~Not in the campaign unless the owner adds the plain leg to v1~~ **2026-09-11 (owner):** it stays history. Experiments are redone after the architecture is confirmed |
| QHV boot time on Windows, QEMU 11.0.50 build: blk-only (2026-09-08), then rng in slot 3 (2026-09-09), both without `-snapshot` | A3, Windows | [findings.md](findings.md), 2026-09-08 and 2026-09-09; `windows-qhv-tcg-boot-times-n5.txt`, `windows-qhv-tcg-rng-slot3-boot-times-n5.txt` | **superseded.** The first carries an entropy-timeout artefact. The second ran on a changing disk, and its own header says it can never be paired |
| QHV boot time on the Orin, QEMU 11.1.0 built from source: single probes (blk-only, rng) and a five-run rng and `-snapshot` series without segment markers (2026-09-09) | A3, Orin | [findings.md](findings.md), 2026-09-09; `orin-qhv-tcg-q111-boot-*.log`, `orin-qhv-tcg-q111-rng-snapshot-boot-times-n5.txt` | **superseded** by the Orin segment series below, whose header says so |
| QHV boot time with segment markers on Windows, QEMU 11.0.50 build, rng, `-snapshot` (2026-09-09) | A3, Windows | [findings.md](findings.md), 2026-09-09; `windows-qhv-tcg-rng-snapshot-segments-boot-times-n5.txt` | **history:** the same-host QEMU-build control for the pair below |
| Release-aligned QHV pair with segment markers: Orin on 11.1.0 from source, Windows on an 11.1.0 release build, rng, `-snapshot` (2026-09-09); and the segment and ratio tables derived from it | A3 | [findings.md](findings.md), 2026-09-09; `orin-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt`, `windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt` | **history.** Its guest disk is the RQ-2 diagnostic variant. The TCG twin legs run again in the campaign, on v1's images |
| QEMU version-by-host matrix and cause controls: 6.2.0 on both hosts, a Cortex-A57 control, 11.1.0 with the EL2 timer interrupt unwired, and the invalid slot-2 rng test (2026-09-08/09) | A3 | [findings.md](findings.md), 2026-09-09; [digital-twin-design.md](digital-twin-design.md) §1a; the `q62`, `a57` and `nohypvirt` logs | **not a measurement** (boot or hang outcomes; still valid) |

**IPC**

| measurement | arch | record | status |
|---|---|---|---|
| Cloud-leg IPC: host client to guest server over the qvm virtio-console pty pair (2026-07-28) | A1 | [`results/cloud/cloud-ipc-latest.csv`](../results/cloud/cloud-ipc-latest.csv); [findings.md](findings.md), 2026-07-28 runtime-spike entry; `qhv-tcg-ipc-benchmark.log` | **history** |
| Virtio-console stall characterisation: pacing, timeout and long-run trials on uncommitted diagnostic variants (2026-07-28) | A1 | [findings.md](findings.md), 2026-07-28 stall entry; [qnx-host-client README](../ipc-test/qnx-host-client/README.md) | **history** (specific to A1's console vdev under TCG) |
| Sentinel recovery: stalls and recoveries counted over several boots (2026-07-28) | A1 | [qnx-host-client README](../ipc-test/qnx-host-client/README.md), sentinel section; [findings.md](findings.md), 2026-07-28 sentinel entry; `qhv-tcg-sentinel-recovery-*.log` | **history** |
| Orin `br0` IPC: QNX guest server to a native Linux client, rebuilt IFS; a smoke run, then two long runs (2026-07-28) | A2 | [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv), first two rows; [findings.md](findings.md), 2026-07-28 IPC benchmark entry; `orin-tcg-qnx-ipc-*.log` | **history.** No L4T runs beside a native QNX host (§7 item 4) |
| Orin IPC rerun at the cloud leg's sample shape (2026-07-28); and the twin IPC diffs derived from both legs | A2; the diffs mix A1 and A2 | [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv), third row; [digital-twin-design.md](digital-twin-design.md) §5 | **history.** The diffs mix host, transport, OS pair and QEMU build |

**KVM and other functional records**

| record | arch | record location | status |
|---|---|---|---|
| Orin KVM GICv3/NISV hang (2026-07-28) and its `a1.metal` reproduction (2026-07-29) | A2 under KVM | [orin-port.md](orin-port.md) risk register; [findings.md](findings.md), 2026-07-29; `aws-a1-metal-kvm-nisv-repro.log` | **not a measurement.** Outside v1, which does no KVM work (§1) |
| GICv3 writeback-store compile count (2026-09-08) and the NISV collector runs (2026-09-09) | compile only; a read-only collection on the Windows PC about A2 under KVM, with nothing booted | [findings.md](findings.md), 2026-09-08 GICv3 entry; [`results/gicv3-nisv-debug/`](../results/gicv3-nisv-debug/) | **not a measurement** |
| First QHV boot; RQ-2 shared-memory probes; Orin network pings; the L4T EL2 and UEFI capture | A1; A1; A2; the board as shipped | [findings.md](findings.md), 2026-06-11 and 2026-07-28 entries; `qhv-tcg-host-and-guest-boot.log`, `qhv-tcg-rq2-*.log`, `orin-tcg-qnx-network1.log`, `orin-l4t-boot-el2-uefi-evidence.txt` | **not a measurement** |

**Native (A4) and the dry run**

| measurement | arch | record | status |
|---|---|---|---|
| M0: kexec acceptance, first run, hang test (2026-09-09) | A4, shim only | [findings.md](findings.md), the M0 paragraphs of the 2026-09-09 QHV-leg entry; `m0-*.md` in [`20260909T1100Z/`](../results/orin-native-port/20260909T1100Z/) | **not a measurement.** Return times and black-box sizes are harness bookkeeping |
| M1: one core at EL1 (2026-09-10) | A4 | [m1-first-procnto.md](../results/orin-native-port/20260909T1100Z/m1-first-procnto.md); `orin-native-m1-*.log` | **not a measurement** |
| M2: six cores at EL1, including the cluster-1 busy-loop rate (2026-09-10) | A4 | [m2-runs.md](../results/orin-native-port/20260909T1100Z/m2-runs.md); `orin-native-m2-six-cores.log` | **not a measurement.** The busy-loop rate was read at an uncontrolled CPU frequency; it stays as history |
| M1b: the VHE host at EL2 on six cores (2026-09-10) | A4 | [m1b-runs.md](../results/orin-native-port/20260909T1100Z/m1b-runs.md); `orin-native-m1b-el2-host.log` | **not a measurement** (the same note on the busy-loop rate) |
| M3: qvm launch to guest banner over five kexec rounds plus a qualification run, and the IPC pair in each run (2026-09-10) | A4 | local branch `m3-results-unpublished`; described in [findings.md](findings.md), 2026-09-10 M3 entry | **The functional pass stands. Its figures are A4 history; the measurement is deferred to the campaign** |
| Dry run 7b: Class-10 event counts, and `ClockCycles()` against `clock_gettime()`, in a rebuilt variant of the A3 Windows host image (2026-09-11) | A3 variant image, TCG | local branch `m3-results-unpublished`; design [m4-dryrun-design.md](../results/orin-native-port/20260909T1100Z/m4-dryrun-design.md) | **not a measurement** (a TCG self-consistency check; every clock is emulated) |

**Not yet measured**

| measurement | arch | record | status |
|---|---|---|---|
| M4 per-exit dwell: r2, that is Q and T1-T5 | v1 | none | **deferred to the campaign** |
| M5: the M3 and M4 medians under UEFI entry against kexec entry | v1 | none | **deferred to the campaign** |
| S1: a CPU-only baseline of the small model inside the Linux guest | v1 | none | **deferred to the campaign** |

Publication is unchanged by this section. §9's open item on already-published numbers covers every public record above. ~~One inconsistency predates this section and is left to the owner. The M0, M1, M2 and M1b rows link run records and captures, although §9's 4.6(i) bullet keeps every M0-M4 log private, and m1b-runs.md closes by saying nothing in it is publishable before the consultation. Whether those records stay in the public tree or join M3's on the local branch is part of that open item.~~ **2026-09-11 (owner):** the M0, M1, M2 and M1b run records and curated captures stay public for now. M3 and later figures stay on the local branch `m3-results-unpublished`. §9's 4.6(i) bullet now says so. m1b-runs.md's closing line is in `results/` and is left as written.

#### The revised ladder

M0, M1, M2, M1b and M3 (met) → **M4-F** → **M5-F** → **S1-F** → **freeze v1** → **campaign**.

Every rung up to the freeze is functional: it passes or fails on what appears, never on a figure. A rung still keeps what its instruments print, but those figures are not judged, not reported and not carried into the campaign.

**M4-F: the trace instrument works on the board (r0, r1).** The rungs are defined in [m4-design.md](../results/orin-native-port/20260909T1100Z/m4-design.md) §2.
- **Before r0:** m4-design's §11 TCG rehearsal passes (its decision N7).
- **r0** runs the trace tools under the EL2 host with no qvm. It passes on the ten gates of m4-design §2.1: landing and startup, the state sequence, the clock verdicts, the counter fixtures, the probe stop, the memory lines, the rate lines, the tool bounds, the TCU transfer and the reset. The memory, rate and speed lines feed r1's image parameters (m4-design §2.4). Their values are sizing inputs, not results.
- **r1** runs M3's full run inside that ring. It passes on the six gates of m4-design §2.2:
  - M3's pass criteria, including the banner and the completed IPC pair;
  - the trace arm, stop and file lines;
  - Class-10 IDs 0, 1 and 7 counted above zero on the board, with one vCPU thread, one offset, and no order violations or time mismatches;
  - a ring that held;
  - the on-target counter and the PC's parse agreeing pair for pair;
  - both transfer checks.

  The banner stamp and the IPC statistics are produced, but not judged.
- **Fail:** as m4-design §1.7 defines it. If r1 counts zero of any of the three IDs, and the PC's parse agrees over a complete window, M4 takes the INTERRUPT/THREAD fallback and every later number is relabelled. A zero the PC cannot verify means a rerun.
- **Deferred to the campaign:** r2 (Q and T1-T5), m4-design's P2-P5, r2's sizing, the PMCCNTR rung (its decision D6(b)) and the emulated Orin-TCG counterpart.
- **Sizing caveat:** m4-design sizes each rung from the record of the one before (§2.4). If v1 changes the host image, the CPU set or the guest set, r0's and r1's sizing records go stale. The campaign then runs its own sizing rungs on v1.

**M5-F: a UEFI cold boot reaches startup.** It replaces the optional M5 below and runs under §3.5 Fallback B's rules.
- **Prerequisites:** M4-F; unknown #12 answered by a header read only (`readelf`, `od`), never a code read (§9, 4.6(c)); the J14 console, for the UEFI Shell.
- **Pass,** all of:
  - the PE, launched from the firmware's built-in UEFI Shell, prints `Entering startup...` on the console;
  - no UEFI variable is written;
  - the ESP gains one new file and nothing else, after `extlinux.conf` and `BOOTAA64.efi` are backed up;
  - the board then boots its unchanged L4T.
- **Recorded, not required:** the image reaches `procnto up`.
- **Deferred to the campaign:** the M3 and M4 medians under UEFI entry against kexec entry, the residual-state comparison, and any cold-boot time.
- **If it fails:** v1 keeps kexec as its only entry path, and the campaign drops the M5 comparison. Whether the M path still counts as ended then is for the owner.

**S1-F: a Linux guest without a GPU under native qvm.** S1 comes from the GPU pass-through research track, an unpushed branch described here in words. That track stages the owner's target from S0, a desk feasibility study, to S5, a small model on a passed-through GPU. S1 is its first stage, and it has no GPU. S2-S5 stay outside this plan.
- **What runs:** a stock L4T R36.4.7 kernel `Image` with a small busybox initrd, its console on virtio-console. It runs on the TCG QHV host first, then natively.
- **Prerequisites:**
  - M5-F. This is the owner's order, not a technical dependency.
  - Checklist 11c: after the `rmmod` quiesce, `/proc/iomem` shows a second RAM window free. The host image then boots with it as a second `add_ram` (K5; §5, `init_raminfo.c`). A GPU range stays out of every `add_ram`.
  - A qvm `dryrun` of the guest configuration, with its device tree dumped, on the TCG QHV host and with no GPU overlay.
  - The research track also gates S1 on a GPU stream-ID check and on the owner accepting an uncontained GPU. This plan leaves both before the first GPU stage, because S1 has no GPU. **2026-09-11 (owner):** confirmed. Of the research track's gates, S1-F needs only the qvm `dryrun` gate first; the GPU checks wait for the first GPU stage.
- **Pass,** all of:
  1. Under TCG, `dryrun` accepts the configuration, and the guest then boots to a shell on `hvc0`.
  2. The same configuration, unchanged, reaches a shell on `hvc0` under native qvm on the board.
  3. If v1 keeps the QNX guest beside it, that guest prints its banner and the IPC pair completes. Completion only.
  4. A ten-minute run ends with qvm alive and the host's memory canaries intact.
  5. Every run is stamped with the kernel, initrd, device-tree and configuration hashes, the CPU pinning and the RAM windows.
- **Kill conditions, from the research track:** no second window can be shown free after `rmmod`, which leaves the guest too little RAM for S1 in this layout; or qvm boots no arm64 Linux, and QNX support cannot fix it.
- **Deferred to the campaign:** the research track's own S1 exit criterion, a CPU-only baseline of the small model in the guest; any boot time; IPC statistics; any Linux-guest latency.
- **Scope:** S1 crosses §1's non-goal "no Linux guest on the native leg", now struck through there. The GPU non-goals stay.

#### Freeze gate

v1 is frozen when all of these are settled and written into the manifest:
1. **Rungs:** M4-F, M5-F and S1-F have passed, or M5-F's failure is recorded and v1 is kexec-only.
2. **Guest set:** Linux only, or QNX plus Linux. The research track's S1 runs Linux beside the QNX guest. The owner's stated target has no QNX guest: the safety functions run as QNX processes in the host.
3. **Entry path:** kexec, with its quiesce and governor-pin sequence, or UEFI; and whether the other path stays as the declared M5 comparison.
4. **CPUs:** the startup `-P` value and each guest's pinning. Either the cluster-1 cores' low busy-loop rate is explained, or cluster 1 is left out.
5. **Frequency policy:** implement the PMCCNTR rung, or accept `clock=unverified` as a property of v1.
6. **Memory map:** the first window, the second window, and the GPU range kept out.
7. **Guest device sets,** chosen so that no fixed guest wait falls inside a timed interval. [digital-twin-design.md](digital-twin-design.md) §1a shows the rng device's effect under TCG.
8. **Guest disk:** the RQ-2 diagnostic variant, or one regenerated from clean sources.
9. **Instruments:** frozen at their source hashes, rehearsed under TCG, parser self-tests passing.
10. **TCG twin legs:** the QEMU release and build on each side, the device set, and `-snapshot`.
11. **Sample sizes** for every campaign measurement, including the IPC iteration count, and the rules that derive them (m4-design §2.4 for the dwell).
12. **Stamping and re-runs:** the version stamp and the re-run rule below.
13. **Licence:** the state of the 4.6(i) consultation is recorded. It gates publication, not the campaign.

#### Reference architecture v1: manifest contents

One file, written at the freeze. It holds hashes and configuration, not a single measured figure, so §9 treats it as design. Its sha256 is the version stamp.
- **Images:** shim, startup, host IFS and kimg; the TCG legs' host IFS; guest IFS and disk; the Linux `Image`, initrd and device tree. For each, its sha256 and the commit that generated it.
- **Startup and kernel lines:** `-P`, `-Q`, `-W`, `-m`, `-A`, `-D`; the procnto variant.
- **Guest set:** each guest's RAM, vCPUs and CPU pinning.
- **vdev configuration:** each guest configuration file's text and hash; addresses and interrupts; `hostdev`; the shared-memory `allow` list.
- **Entry path:** the kexec syscall and the quiesce module list, or the UEFI PE and its ImageBase.
- **Memory:** the `add_ram` windows, the `avoid_ram` ranges, and how the second window was derived.
- **CPU frequency policy:** the governor sequence, the fields [m3-design.md](../results/orin-native-port/20260909T1100Z/m3-design.md) §4.3 records, PMCCNTR yes or no, and the thermal and nvpmodel state.
- **Instruments:** source hashes of `stamp`, `bwait`, `m4count`, `tcu-cat`, `clkcmp`, `trcctl`, `qnx-host-client` (with `frame.h`), `parse-m4.py`, `diff-results.sh` and both QHV launchers; the SDP build of tracelogger and traceprinter; both QEMU builds.
- **Board and capture:** firmware and L4T version, the capture method, and §12's stamp list.

#### The campaign

One campaign, run on v1 after the freeze.

**Native leg (v1 on the Orin)**
1. **Guest boot:** qvm launch to guest banner for each guest in v1, with M3's instrument. A qualification run, then five timed runs on one image.
2. **IPC:** the Phase-2 pair over virtio-console, if the QNX guest stays, at the sample size fixed at the freeze.
3. **Per-exit dwell:** M4 as m4-design defines it. Sizing rungs on v1 first, then r2 (Q, T1-T5), judged by P2-P5 and F1-F2 (m4-design §1.1).
4. **Entry path:** M5's comparison, if M5-F passed and v1 keeps both entries: the M3 and M4 medians under UEFI entry against kexec entry. A disagreement makes the kexec residual-state caveat a finding in its own right.
5. **Linux guest:** the CPU-only baseline of the small model, if the Linux guest is in v1.

**TCG twin legs**

6. **Boot:** a QHV host image carrying v1's guest set, guest images and vdev configuration, booted on Windows and on the Orin. Both sides use one QEMU release, with each build recorded, v1's device set and `-snapshot`. The segment-marker boot instrument runs a five-run series on each host.
7. **IPC and trace:** the same IPC run on each TCG leg, and the M4 script on the Orin-TCG leg. Their results are labelled emulated time.

**Twin diff**

8. The two TCG legs against each other (two host bundles, [digital-twin-design.md](digital-twin-design.md) §1a), and each against the native leg (a third bundle, §7 item 6). A table only compares records with the same `arch=` stamp.

**Version stamp.** Every run-record header, boot-time file header, curated capture header and CSV `notes` field carries `arch=v1;manifest=<sha256 prefix>`. A record without it is not a campaign record.

**Re-run rule.**
- **A manifest change makes a new version.** Changing any manifest field after the freeze creates v2. v1's records stay as v1 history; they are not edited, relabelled or mixed into v2 tables.
- **No piecemeal repair.** A campaign is not patched run by run. Whether v2 gets its own campaign is the owner's decision.
- **A blocked campaign stops.** If a measurement can only continue after a manifest change, the campaign stops there. Its records so far stay v1, and the change starts v2.
- **Retries.** A run that never reached QNX is retried on the same image under M3's validity rule, and that is not a version change. A timed run that reached QNX and failed is never replaced (m4-design §2.3).
- **Changes outside the manifest,** such as a capture restart, are written in the run note and leave the version alone.

**Publication.** Campaign figures are evaluation output under 4.6(i). Like M3's, they stay out of the public repo until the consultation is recorded (§9).

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
range, GICv3 960 SPIs, WDT lines (the `HV-timer PPI28: wired|absent` token planned here became M1b's automatic `t234: hvtimer cpu N verdict=` probe). (6) Iterate on faults via the board's own vectors
(the shim's cannot print once C code runs) + `addr2line` on the `[+keeplinked]` ELFs. (7) M1b: `-Q enable,el2-host`, run as the R0-R2b ladder below with M2's payload; expect the VHE line.

**Pass:** in order — shim bank → startup banner → `print_syspage()` → `T234 M1: procnto up` → `T234 M1: user
space up` → `pidin info` (1 CPU, ~950 MB) → a `pidin` listing → a `cksum` matching the PC-side value. If the
watchdog stays armed across kexec, each attempt has ~2 min — enough here, not enough later. (It does not: M0's `hang` test.)

**M1b met 2026-09-10.** Run on M2's payload rather than M1's, as the ladder in [m1b-design.md](../results/orin-native-port/20260909T1100Z/m1b-design.md) §6.3:
- **R0** re-ran M2's six-core image (`-Q disable`) with the new startup. Masked of numbers, it differed from M2's R4 in exactly the three intended lines.
- **R1** (`-Q enable,el2-host -P1`), **R2** (`-P6`) and **R2b** (the same image) each met every criterion:
  - the library's `Enabling EL2 host hypervisor support (VHE)`;
  - `HCR_EL2=0000030488000000` (E2H and TGE set) on every core;
  - `t234: hvtimer cpu N verdict=wired` on every core;
  - qtime `intr:28` and hypinfo flags 1;
  - procnto and user space at EL2 with the clock ticking on INTID 28;
  - `SMPCHECK RESULT PASS cpus=6/6` at `-P6`;
  - the image's own warm reset.
- **The probe** armed the EL2 physical timer as a control (INTID 26 pending), then the EL2 virtual timer (INTID 28 pending, cleared when masked), without taking an interrupt. It would have stopped the run by name otherwise.
- **Secondaries** started by a `CPU_ON` issued from EL2 entered in the same state as M2's.

Record: [m1b-runs.md](../results/orin-native-port/20260909T1100Z/m1b-runs.md); curated capture: [orin-native-m1b-el2-host.log](../logs/sample-boot/orin-native-m1b-el2-host.log).

### M2 — SMP: six A78AE cores

Bisect `-P2` → `-P4` → `-P5` → `-P6` (`-P5` added 2026-09-10 so the first cluster-1 wake and the first read of frames 4 and 5 fail alone); per-CPU `cpu N up MPIDR=.. GICR=..` prints; `pidin info` CPU count; six busy
processes; a `tracelogger` sanity check; `shutdown -S reboot` returns L4T (not `-b`, which halts; corrected 2026-09-10). Expected GICR bases `0xF440000 /
0xF460000 / 0xF480000 / 0xF4A0000 / 0xF500000 / 0xF520000` (the library's own `cpuN: Core GICR SGI address` lines print the SGI frame, base + 0x10000). `-P4` (cluster 0 only) is the documented
degraded fallback and must be **recorded as degraded** if used. ~~An idle soak doubles as the `-W` test~~: **wrong, corrected 2026-09-10.** WDT0 does not fire once the
kexec'd payload runs (the M0 hang test). It did fire in M2's first attempt, but only because Linux panicked in its own kexec
shutdown before the jump; that watchdog reset preserved pstore.

**Pass:** `pidin info` reports 6 CPUs (or 4, recorded as degraded); one `cpu N up` line per core with the
expected MPIDR and GICR base; a 60 s six-process load with no fault; `shutdown -S reboot` returns L4T. **Fail** =
any core that never reports up, or an `ap_fail()` message from `start_aps()`.

**Met 2026-09-10.** Run R4 (`-P6`) met every criterion above in one run: all five secondaries entered at EL2 through
`CPU_ON`; six `t234: cpu N up` lines carried the expected MPIDR, frame (0-3, 6, 7), index and IPI value; `pidin info` listed
six processors; six pinned 60 s busy workers passed with no misplacement; and the image warm-reset itself back to L4T. R4b
repeated it with the identical image, and R5's tracelogger capture recorded events on all six cores. The
ladder ran `-P1` (regression), `-P2`, `-P4`, `-P5`, `-P6`, each passing before the next. Both cluster-1 cores ran the busy
loop at one fixed rate in every run, roughly a tenth of cluster 0's, which varied between runs; the cause is open. Runs, firmware EL2 values and two host-side problems (a Linux
panic in its own kexec shutdown, and a serial capture that received nothing) are in
[m2-runs.md](../results/orin-native-port/20260909T1100Z/m2-runs.md); curated capture:
[orin-native-m2-six-cores.log](../logs/sample-boot/orin-native-m2-six-cores.log).

### M3 — QHV host natively at EL2 + byte-identical guest; ~~first hardware-timed number~~ **a functional pass (2026-09-11)**

Image adds the hypervisor set exactly as the cloud host's build lists it (`qvm`, `qvm-check`, `vdev-pl011`,
`vdev-virtio-console`, `vdev-shmem`, `libfdt.so`, `tracelogger`/`traceprinter`, slogger2) plus
`/proc/boot/guest-ifs.bin` = the cloud-leg guest (sha256 `968029…7cf4f`), and a `g2.conf` that is the
cloud-leg config **minus virtio-blk** (corrected 2026-09-10: without its disk the guest never prints its banner and never starts the echo server, so M3 ran the as-run four-vdev configuration with the disk carried in the image; [m3-design.md](../results/orin-native-port/20260909T1100Z/m3-design.md) §1). Startup runs `-Q enable,el2-host`. M1b's probe found INTID 28 wired on every core, so the el1-host
fallback and its relabelling are not needed. `-Wdisable` or a `wdtkick` kicker is insurance only: the "mandatory (K9)
because guest boot plus a trace capture does not fit in 2 minutes" written here assumed a limit that M0's `hang` test disproved. `stamp` prints `ClockCycles()` at `qvm` launch and at the guest
banner; delta / 31,250,000 = seconds; five runs = five kexec rounds. Then the Phase-2 host-client /
guest-server IPC pair over the virtio-console pty, exactly as on the cloud leg, its CSV row printed over the
TCU. **What the number is NOT:** not a per-exit latency (M4), not the twin's full launch→banner headline —
only its `qvm_launched → guest_banner` segment.

**Pass:** the guest banner appears on 5/5 runs; each of the five stamped deltas is recorded with startup
options, `-Q` mode, guest sha256, `-W` policy and CPU MHz (or "clock not verified"); the IPC pair completes
its 15 timed iterations. **Fail** = fewer than 5 banners, or any run whose stamps are missing a field.

**M3 met 2026-09-10.**
- **What ran.** Native `qvm` on four Cortex-A78AE cores at EL2 (`-P4 -Q enable,el2-host`) booted the byte-identical cloud-leg guest to its banner on 5/5 timed runs. The guest IFS was `968029…7cf4f`, with the unmodified disk `cf5b06d0…216b`.
- **IPC.** The pair completed its 15 iterations in each run.
- **The qualification run** passed the same way.
- **The pass fields.** Every field the pass line asks for was recorded in every run, with CPU MHz as `clock not verified`.
- **Deviations.**
  - The guest disk went back in (above).
  - R0's first attempt failed on `libz.so.2`, so five libraries and `qcrypto.conf` from the cloud host IFS were added.
  - The governor is pinned again after the GPU-module quiesce.
- **Unpublished.** The measured interval and the IPC figures are evaluation output under NC QDL v7 4.6(i). They stay in an unpublished local record (branch `m3-results-unpublished`) until the supervising professor has been consulted.

**2026-09-11 (owner decision, [the freeze section](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)):** M3 stands as a functional pass. Its figures are history for architecture A4, not the hardware-timed number. The M3 measurement runs again in the v1 campaign.

### M4 — The qvm-trace number — ~~blocked on a dry run (K11)~~ **dry run done 2026-09-11; board runs next**

**2026-09-11 (owner decision): M4 is now functional only, as M4-F (r0 and r1) in [the freeze section](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).** The dry-run text below stands. The board recipe and the pass line are superseded as marked.

**Before any board work:** run the `tracelogger -r -M -S 8M -f /dev/shmem/t.kev` +
`traceprinter | grep -E 'QVM|Class 10|GUEST'` recipe **inside the existing Windows-TCG QHV host image** and
confirm Class-10 IDs 0/1/7 actually appear, count the filtered lines, and compare `ClockCycles()` against
`clock_gettime()` over 1 s. Until that runs, the event IDs are VENDOR_CLAIM and the throughput estimate is a
guess. **Fallback if Class-10 events are absent on 8.0.x:** bound the dwell with kernel INTERRUPT/THREAD
events around the qvm vCPU threads, and say so.

**Dry run done 2026-09-11 (checklist 7b; record unpublished, 4.6(i)).** Four TCG attempts passed. They ran inside a rebuilt variant of the
Windows-TCG QHV host image carrying the byte-identical guest; the canonical images were only hashed. Design and deviations:
[m4-dryrun-design.md](../results/orin-native-port/20260909T1100Z/m4-dryrun-design.md). What it changes for the board recipe:
- **The events are real.** Class-10 IDs 0 (GUEST_ENTER), 1 (GUEST_EXIT) and 7 (CYCLES) are emitted at qvm's default settings.
  - traceprinter prints the class as `QVM` and the events by name.
  - `%e` in its format is a sequence index, so the counter classifies by name.
- **The grep above keeps only headers.** Plain traceprinter output puts arguments on separate lines, so the filter runs over `traceprinter -n` output.
- **The ring flags as written keep only a short tail before the stop,** and lost the whole workload.
  - `-S` does not size a ring; `-k` does.
  - The board sizes `-k` from its own event rate, or a linear window bounded by markers replaces the ring.
- **Stopping.** `TraceEvent(_NTO_TRACE_STOP)`, sent by our `trcctl`, makes a ring capture write its file and exit. `-M -f` writes to the literal path.
- **Offsets.** Host time = guest time − `clockcycles_offset` held on every in-sequence triple, once 64-bit time is rebuilt from the CONTROL TIME events.
- **Clocks.** `ClockCycles()` and `clock_gettime()` agreed over 1 s in all three CPU modes. This is a self-consistency check only: both clocks are emulated under TCG.
- **Failing.** A fail needs zero counts verified by an independent parse of the trace. An unverified zero means a rerun, not the fallback.

On the board: ring-mode capture into `/dev/shmem` around a defined workload, then a filtered listing plus
`cksum` and a line count over the TCU (never the whole `.kev`); ~~PMCCNTR calibration prints actual core MHz~~.
PC-side parser → ~~`results/hw/orin-native-qvm-trace-latest.csv`~~ **a git-ignored CSV (2026-09-11)** in the `diff-results.sh` schema
(`unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes`), `cycles_per_sec = 31250000`,
`notes = orin-native-el2host-qvm-class10-dwell;clock=<MHz|unverified>`. The same script on the Orin-TCG leg
gives the emulated-time counterpart, labelled as such. **Superseded 2026-09-11 where
[m4-design.md](../results/orin-native-port/20260909T1100Z/m4-design.md) differs.** The clock is recorded as
`clock=unverified` (its decision D6(a)) rather than calibrated by PMCCNTR, and the CSV goes to a git-ignored path (its
§6.4). Under the owner decision only r0 and r1 run before the freeze. The timed runs and the Orin-TCG counterpart
belong to the v1 campaign.

~~**Pass:** the dry run shows Class-10 IDs 0/1/7 present; then 5 board runs of >= 1,000 Exit/Entry pairs each,
`cksum` and line count matching on the PC side, P50 stable within +/-20 % across runs, and `diff-results.sh`
consuming the CSV. **Fail** = no Class-10 events in the dry run (take the INTERRUPT/THREAD fallback and
relabel every number; the zero counts must be verified by an independent parse of the trace, and an unverified zero means a rerun), or P50 spread beyond +/-20 % (report the spread, never average it away).~~
**Superseded 2026-09-11 (owner decision):** M4 is met once **M4-F** in
[the freeze section](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11) passes, that is, when r0
and r1 pass on the board. The dry run's part of this line was met on 2026-09-11. The timed board runs, their block checks, the P50
stability check and `diff-results.sh` consuming the CSV move to the v1 campaign. The rule for a verified zero count
carries over unchanged.

### M5 ~~(optional)~~ — UEFI Shell cold-boot cross-check **(on the M path as M5-F, 2026-09-11)**

~~Only after M3/M4,~~ **After M4-F (2026-09-11),** only under the §3.5 Fallback-B rules. ~~PASS = the PE reaches `Entering startup...` and the
M3/M4 medians agree with the kexec-entered ones within run-to-run spread; disagreement makes the
kexec-residual-state caveat a finding in its own right.~~ **Superseded 2026-09-11 (owner decision):** M5 is
functional, as **M5-F** in [the freeze section](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11).
PASS = the PE reaches `Entering startup...`, no UEFI variable is written, the ESP gains only one new file, and the
unchanged L4T comes back afterwards. The median comparison moves to the v1 campaign. There, a disagreement still makes
the kexec-residual-state caveat a finding in its own right.

---

## 7. What a fully successful M4 still cannot measure

1. A **firmware-booted** QNX: the payload is entered by kexec from Linux — no UEFI→QNX boot time, no firmware
   hand-off timing, and residual state (DRAM, caches/TLB, BPMP-set clocks, thermal, any DMA Linux failed to
   stop) is inherited. ~~Only M5 addresses this.~~ **2026-09-11:** only the campaign's M5 comparison addresses this,
   and only if M5-F passes.
2. Anything about NVIDIA DRIVE OS, the NVIDIA Hypervisor stack, DRIVE AGX Orin, QNX OS for Safety, ASIL, or
   certified BSPs. This is Experimental Software on a consumer devkit with no vendor path from either side.
3. Any peripheral or DMA path: no SDHCI/PCIe/NVMe/Ethernet/USB/display/GPU/SMMU work; `smmuman` and
   DMA-device containment are never exercised.
4. The heterogeneous Safety(QNX) ↔ Compute(Linux) topology natively — while the QHV host runs, L4T is gone.
   The `br0`/tap numbers in [`results/hw/orin-ipc-latest.csv`](../results/hw/orin-ipc-latest.csv) stay a
   ~~KVM/TCG-leg~~ TCG-leg result **(corrected 2026-09-11: that leg never ran under KVM;
   [digital-twin-design.md](digital-twin-design.md) §5)**. **2026-09-11:** S1 brings a Linux side back as a qvm guest
   of the native host. That is not the `br0` topology.
5. Power, thermal, DVFS: clocks stay wherever BPMP/Linux left them; cycle counts are at an uncontrolled
   frequency, only *reported* by the PMCCNTR calibration. **(2026-09-11: m4-design.md's decision D6(a) records
   `clock=unverified` instead; the frequency policy is a freeze-gate item, §6.)**
6. A true one-variable twin diff: console mechanism, entry path, memory map, guest RAM placement ~~and possibly
   host mode (`el1-host`)~~ all differ from the TCG legs **(2026-09-10: M1b settled the native host mode as `el2-host`)**. This is a **third bundle**, not "same image, host
   only" — the same honesty §1a already applies to the QHV leg.
7. Timer resolution below 32 ns; low-microsecond dwell is quantised to tens of ticks. And the
   no-instrumentation number: `procnto-smp-instr` + `tracelogger` overhead makes absolute values upper bounds
   (the same kernel on the TCG leg keeps the *diff* fair).
8. Robustness over time: ~~with a 2-minute watchdog window there is no soak beyond minutes unless the watchdog
   is disabled.~~ **2026-09-11:** struck; there is no such window after kexec (M0's `hang` test). **2026-09-09: there is no unattended recovery to remove** — the watchdog did not fire after `systemctl kexec`, so `-Wdisable` protects a measurement against a timer that was not counting anyway. It stays as insurance against the opposite finding on a different hand-over path. [m0-hang-watchdog.md](../results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md)
9. Anything publishable until the 4.6(i) consultation is recorded (§9).

---

## 8. Open unknowns, ranked

| # | unknown | class | if it goes the wrong way |
|---|---|---|---|
| 1 | ~~Payload entered at EL2 by NVIDIA's kernel fork~~ **CLOSED 2026-09-09: it is.** The shim reported `EL=2` on the board. [m0-first-run.md](../results/orin-native-port/20260909T1100Z/m0-first-run.md) | **VERIFIED** | Nothing — this row is closed, and it was the one that could have ended the kexec approach. |
| 2 | ~~The SPE keeps draining the TCU mailbox after Linux exits~~ **CLOSED 2026-09-09: it does.** ~330 characters went out with `TCUDROPS=0`. [m0-first-run.md](../results/orin-native-port/20260909T1100Z/m0-first-run.md) | **VERIFIED** (mailbox) | ~~The wire itself is still unobserved — no adapter attached — so a silent console would now point at the wiring, not the mechanism.~~ **2026-09-11:** the wire is observed too: M1 was captured live over J14 with a USB-TTL adapter. |
| 3 | ~~NS-EL2 virtual timer PPI 12 / INTID 28 is wired on Tegra234~~ **CLOSED 2026-09-10: it is.** M1b's probe saw the EL2 virtual timer raise INTID 28 on all six cores, with INTID 26 as a passing control, and procnto's clock ticked on it. [m1b-runs.md](../results/orin-native-port/20260909T1100Z/m1b-runs.md) | **VERIFIED** (Non-secure view, this SKU and firmware) | Nothing for M3: the VHE host is available. Formerly: no VHE number; `el1-host` gives a hardware-timed but differently-labelled one |
| 4 | ~~The watchdog's behaviour across `kernel_kexec`~~ **CLOSED 2026-09-09: it does not fire.** Six and a half minutes of `wfi` against a two-minute watchdog, recovered only by pulling the power. [m0-hang-watchdog.md](../results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md) | **VERIFIED** (does not recover) | Either no unattended recovery (manual power cycle, smart plug) **or** a hard 2-min cap on M3/M4 until `-Wdisable`/`wdtkick` works |
| 5 | ~~`qvm` arms stage-2/ICH/virtual-timer state on real A78AE as it does under TCG~~ **CLOSED 2026-09-10: it does, for this guest.** Native `qvm` at EL2 booted the cloud-leg QNX guest to its banner on 5/5 timed runs (record unpublished, 4.6(i)) | **VERIFIED** (one guest, one board) | Nothing for M3. Formerly: M3 stalls; no support path for Everywhere licensees; the finding is the deliverable |
| 6 | No firmware agent (BPMP/SPE/DCE/PSC) or stale device DMA touches `0x80000000-0xBDFFFFFF` after hand-off | HYPOTHESIS | Irreproducible corruption; escape = a higher `[image=]` and the `-U` EFI-map path |
| 7 | ~~ramoops zone offsets~~ **SETTLED 2026-09-09** — DT gives `record-size 0x10000` / `console-size 0x80000` / no ECC, so the console zone is at `0x2_72770000`; `/dev/mem` reads it despite `STRICT_DEVMEM=y`; the header is `sig 0x43474244` + `start` + `size`. [blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md) | VERIFIED | Nothing — this row is closed. Formerly: black box addressable only by the "last 256 KiB + `dd if=/dev/mem`" hack |
| 8 | ~~The `t234-orin-nano` board dir builds and links `display_char_tcu`~~ **CLOSED 2026-09-10: it does.** It builds and passes the symbol gate (§11 action 4, 2026-09-09), and M1 printed through its TCU callout on the board | ~~UNKNOWN~~ **VERIFIED** | Nothing — this row is closed. Formerly: Makefile work before any signal — but the toolchain itself is now proven (K12) |
| 9 | uarta stays clocked after kexec if opened (as root) from Linux | HYPOTHESIS | No zero-code interactive shell; write `devc-tcu` (+2-3 d) |
| 10 | `gic_v3_gicc_init()` tolerates reading TYPER of unpopulated frames 4/5 en route to 6/7 | **CLOSED 2026-09-10** | Frames 4 and 5 read without fault from CPU0 at EL1 with the library's 32-bit access. They hold affinities `0x10000` and `0x10100`, the two cluster-1 cores this SKU lacks, so the walk passes them and binds frames 6 and 7. No patch needed |
| 11 | ~~QHV Class-10 event IDs exist as documented on 8.0.x~~ **CLOSED 2026-09-11 for TCG:** IDs 0, 1 and 7 are emitted at qvm's default settings (dry run 7b; the board is unconfirmed) | **VERIFIED** (TCG) | Nothing for the dry run. Formerly: M4 falls back to bounding the dwell with kernel INTERRUPT/THREAD events |
| 12 | `mkifsf_uefi` emits a loadable AArch64 PE; EDK2 honours a relocation-less ImageBase | UNKNOWN | ~~Only M5 (optional) is lost~~ **2026-09-11:** M5-F fails; v1 keeps kexec as its only entry path, and the campaign drops the M5 comparison |

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
  ~~Every M0-M4 log, CSV, trace and boot-time file stays private, tagged *unpublished pending 4.6(i)
  consultation*~~ — M0/M1 boot logs and `pidin` listings are functional-evaluation output too, not just M4's
  timings. **2026-09-11 (owner):** even so, the M0, M1, M2 and M1b run records and curated captures stay public
  for now, under the open item on already-published results below. M3, M4 and every campaign figure stay private
  until the consultation is recorded. Design, source and procedures evaluate nothing and are publishable. The consultation outcome goes
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
| M1 — procnto + user space, then M1b | 3-7 | HIGH | First QNX instruction ever on Tegra234; EL2/GIC/raminfo interactions; blind debugging doubles it. **M1 and M1b met 2026-09-10** |
| M2 — SMP | 1-2 | LOW-MED | Both known pitfalls pre-empted; cluster-1 wake UNKNOWN. **Met 2026-09-10** |
| M3 — QHV host + guest, ~~first number~~ | 2-6 | MED-HIGH | ~~INTID 28~~ (wired, M1b); stage-2/ICH on real silicon; ~~plus the watchdog policy, now on the critical path~~ (WDT0 does not fire after kexec). **Met 2026-09-10.** **2026-09-11: a functional pass; its measurement moves to the v1 campaign ([§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11))** |
| M4 — ~~qvm-trace~~ **M4-F: r0, r1 (2026-09-11)** | 1-3 | LOW-MED | The dry run (done 2026-09-11); then ~~11 KB/s transport and the parser~~ **the transport and parser that m4-design.md specifies, exercised by r0 and r1. r2's timed runs move to the campaign (2026-09-11, [§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11))** |
| M5 — ~~optional UEFI cross-check~~ **M5-F: UEFI cold boot to startup (2026-09-11)** | 2-5 | HIGH | PE ImageBase/relocation, `mkifsf_uefi` behaviour. **The median comparison moves to the campaign (2026-09-11, [§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11))** |
| S1-F — Linux guest, no GPU, native qvm **(added 2026-09-11)** | 1-3 weeks after M3 (the research track's estimate, HYPOTHESIS) | not rated | qvm's handling of an arm64 kernel, its device tree and PSCI; ownership of the second RAM window ([§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)) |
| Freeze v1 **(added 2026-09-11)** | not estimated | UNKNOWN | The owner's settings for the freeze gate; writing the manifest |
| Campaign on v1 **(added 2026-09-11)** | not estimated | UNKNOWN | Board time for the native leg; TCG time for both twin legs |

**Total to M4: 8-22 working days (median ~13)** — 3-6 calendar weeks at part-time cadence on a shared
board; +2-5 for M5. **2026-09-11:** "to M4" now means to M4-F, and M5-F is on the path rather than an add-on. No
total runs to the campaign: S1-F's row is the research track's estimate, and the freeze and the campaign are not
estimated yet. Consistent with ADR-003's "weeks, no vendor path". Not included: the 4.6(i) consultation,
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
- [x] **2. Write and assemble the M0 shim** (`probe` mode first) with `ntoaarch64-as` / `ntoaarch64-ld
  -Ttext=0x80080000` / `ntoaarch64-objcopy -O binary`, plus the 20-line header checker (`od` at 0x08 / 0x10 /
  0x38, size == 8192). **Drop the WDT-arming code (K9)**; keep the WDT *read* in the register bank.
  **Done 2026-09-09** — `orin-native/shim/t234-shim.S`; all three modes assemble with zero warnings under `-Wall -Wa,--fatal-warnings`, the page is exactly 8192 bytes and the header checks field by field. Reviewed on four lenses, five findings applied ([shim-review.md](../results/orin-native-port/20260909T1100Z/shim-review.md)).
- [x] **4. Create `boards/t234-orin-nano/`** from the Apache-2.0 `armv8_fm` skeleton (never `armv8_fm/main.c`
  or `ls10x6a.h`) with the §5 files stubbed; build; `nm`-check: `gic_v3_set_paddr_range`, `psci_smc`,
  `hyp_enable_el2_host`, `display_char_tcu` present, **exactly one** `psci_cpu_id`, no `efi_entry_point` /
  `uefi_init` / `acpi_` — **expect and allow the three `uefi_*_f` symbols (K12)**. **Done 2026-09-09** — orin-native/startup/t234-orin-nano/, nine files, builds to a 552 KB linked startup with no warnings via build-board.sh, which also runs the symbol gate: every required symbol present, exactly one psci_cpu_id so the board override won, and no EFI or ACPI code beyond the three weak hook pointers the library always carries. ~~The -t probe is stubbed and says so rather than guessing.~~ **2026-09-11:** implemented for M1b as `aarch64/hvtimer.c`; it found INTID 28 wired.
- [x] **5. Compile `tcu-cat.c` and `stamp.c`** with `ntoaarch64-gcc`. **Done 2026-09-09** — `orin-native/tools/{tcu-cat,stamp}.c` plus a Makefile; both compile clean under `-Wall -Wextra -Werror` for `gcc_ntoaarch64le` and link to AArch64 ELF64. Note the target name: `-Vgcc_ntoaarch64le`, not `gcc_ntoaarch64`, which the SDP rejects.
- [x] **6. Source reads only** (Apache-2.0 / BSD): `gic_v3.c:482-500` `gic_v3_use_mm_reg_callouts()` calling
  form with no GICC; `hypervisor_enable.S` `hyp_enable_el2_host` register expectations (and confirm where it
  re-asserts E2H/TGE — K3); edk2-nvidia `TegraCombinedSerialPortLib.c` at r36.4.4 for the RX release
  semantics already VERIFIED on `main`. **Done 2026-09-09, all three determinable** [board-dir-source-reads.md](../results/orin-native-port/20260909T1100Z/board-dir-source-reads.md). Three things the board code now rests on rather than assumes: `gic_v3_set_paddr` is a wrapper that derives the redistributor limit from the CPU count, which cannot reach this SKU's frames 6 and 7, and the walk asserts rather than hangs when it runs out; `hyp_enable_el2_host` only ORs TGE and E2H onto the baseline `at_el2` leaves, and `hypervisor_init(0)` must precede `init_smp`, `init_mmu` and `init_qtime` for reasons the library enforces with a crash; and the TCU receive mailbox is released by writing a literal zero to the whole word, which NVIDIA's own reference implementation does only on the call that drains the last byte.
- [x] **7. Generate the no-blk `g2.conf`** and record the guest sha256 (`968029…7cf4f`). **Done 2026-09-09** — `orin-native/qhv/g2-noblk.conf`, diffed against the configuration the cloud leg generates at boot (`scripts/qhv/post_start.custom`): it differs in exactly the two intended ways, the guest image path and the removed `virtio-blk` vdev, and is otherwise identical line for line. The guest sha256 was re-checked against the local image and matches K11's value.
- [x] **7b. Run the M4 recipe inside the existing Windows-TCG QHV host image** — confirm Class-10 IDs 0/1/7
  appear, count the filtered lines, and compare `ClockCycles()` with `clock_gettime()` over 1 s.
  **This unblocks M4 (K11) and costs nothing.** **Done 2026-09-11**, in a rebuilt variant of that host image carrying the byte-identical guest (the canonical images were only hashed). Class-10 IDs 0/1/7 appear, the filtered lines were counted, and the clock comparison agreed. See the M4 section and [m4-dryrun-design.md](../results/orin-native-port/20260909T1100Z/m4-dryrun-design.md). Record unpublished (4.6(i)).

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
  **2026-09-11: now a prerequisite of S1-F ([§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).**

First board session, owner decision (not read-only, but no reboot and nothing persistent):

- [x] **12. ~~`sudo kexec -s -l t234-shim.kimg; cat /sys/kernel/kexec_loaded; kexec -d; sudo kexec -u`~~ — DONE 2026-09-09: both syscalls accept, segment 0 at `0x80080000`, board never rebooted ([m0-kexec-acceptance.md](../results/orin-native-port/20260909T1100Z/m0-kexec-acceptance.md)).** Formerly:
  proves the header format and the syscall path, and prints the actual segment addresses. **This is the
  gate on K2**; M0 step 2 should not run before it.

Purchase (the only non-zero cost):

- [ ] **13. A 3.3 V-logic USB-TTL adapter** (FT232RL / CP2102 / CH340, never 5 V-only) + female jumper wires
  for J14 pins 4 / 3 / 11 — do not connect VCC (~USD 5-15) — and, **now necessary rather than recommended, because the watchdog turned out not to recover the board ([m0-hang-watchdog.md](../results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md))**, a remotely switchable mains plug or relay on
  the DC barrel input (~USD 10-20). The adapter is validated the moment the L4T boot log appears on it.
  **No longer blocking:** with the black box settled ([blackbox-verified.md](../results/orin-native-port/20260909T1100Z/blackbox-verified.md)) M0 and M1 can run and be read back with
  nothing bought. The adapter buys live output, interactive debugging, the UEFI menus M5 needs, and an end to
  the one-question-per-reboot cadence — a schedule multiplier, not a prerequisite.
  ~~With the watchdog armed (K9), the plug is *probably* redundant — but "probably" is exactly what M0's
  `hang` test is for.~~ **2026-09-11:** the adapter half is done: an FT232R on J14 has captured the console since M1.
  Whether a switchable plug was bought is UNKNOWN, so the box stays unticked.

---

## 12. Results hygiene

~~All outputs under `results/orin-native-port/<ts>/m{0..4}/`, private until §9 clears,~~ redacted before writing
(`<user>`, `<orin-ip>`, `<orin-key>`, `<mac>`), every log stamped with: startup options, `-Q` mode, `-W`
policy, shim build flags, IFS sha256 (sha only), guest IFS sha256, kexec syscall used, `cpuinfo_cur_freq`
before kexec, adapter pin assignment. ~~Boot-time files in the existing `qhv-guest-boot-*-times.txt` format;~~
CSVs in the `diff-results.sh` schema. **2026-09-11:** the M0-M1b records are flat files in `20260909T1100Z/` and stay
public (owner, §9). Later run directories under `results/orin-native-port/` are git-ignored, and M3's figures sit on
the local branch `m3-results-unpublished`. No `qhv-guest-boot-*` file exists; the tracked boot-time files use the
`*-boot-times-n5.txt` naming. Guest IFS and disk images are gitignored build outputs, never committed.
**2026-09-11:** campaign records on reference architecture v1 also carry `arch=v1;manifest=<sha256 prefix>` in every
header and every CSV `notes` field ([§6](#architecture-versions-and-the-measurement-freeze-decided-2026-09-11)).

---

## Provenance

Produced by an orchestrated multi-agent workflow on **2026-09-09**: three harvest agents (repo, SDP/BSP,
Orin board — read-only), five research agents (QNX, Tegra234, kexec/TCU, UEFI, prior art), three independent
design agents, three judge agents scoring those designs, one synthesis pass, and a verification pass putting
**12 load-bearing claims through 3 lenses each** (source / docs / live read-only board). This document is the
synthesis revised against those 36 verdicts.

~~**Nothing here has been executed on the board.** The only VERIFIED items are compile-only builds on the
Windows host and read-only reads of the Orin as it currently runs L4T. No QNX code has run on Tegra234, no
number exists, and no claim in §6 has been demonstrated.~~ **2026-09-11:** true when written on 2026-09-09. M0-M3
have run on the board since, and dry run 7b under TCG (§6).
