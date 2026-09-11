# M5 design: a functional UEFI cold boot of the unchanged M1b kimg on the Jetson Orin Nano, through our own EFI loader

Phase 3b. Architect pass, revision 2, 2026-09-11: revision 1 with the review outcomes in §13 applied. This is a read-and-reason design: nothing in it has been built or run. It follows the structure of [m3-design.md](m3-design.md). Its scope is the owner decision of 2026-09-11 (option B): M5 is functional verification only.

**Path prefixes used below**
- `lib/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/lib/` (Apache-2.0)
- `board/` = `orin-native/startup/t234-orin-nano/`; `startup/` = `orin-native/startup/`; `shim/` = `orin-native/shim/`; `uefi/` = `orin-native/uefi/` (proposed; it does not exist)
- `r/` = `results/orin-native-port/20260909T1100Z/`; `plan` = `docs/orin-native-port-plan.md`
- `NV` = https://github.com/NVIDIA/edk2-nvidia/tree/r36.4.4, the source generation of this board's firmware (r/research-uefi.md:39-43)
- `UP` = https://github.com/tianocore/edk2/tree/edk2-stable202402 (upstream; NVIDIA's fork of these files was not diffed)
- `LX` = https://github.com/torvalds/linux/tree/v5.15 (upstream; NVIDIA's 5.15.148-tegra fork was not diffed, plan:93, K1)
- `L4T` = the local NVIDIA download `downloads/nvidia/l4t-r36.4.4/Jetson_Linux_R36.4.4_aarch64.tbz2`. Two members, `kernel/Image` and `bootloader/BOOTAA64.efi`, were extracted to a scratch directory for a PE header read only.
- `brief` = the M5 synthesis brief of 2026-09-11 (workflow scratch, not tracked). Every citation this design depends on was re-read.

**Evidence classes:** VERIFIED (read in source, a build file, a binary header, a record or a log, or computed on this PC; cited), VENDOR_CLAIM (NVIDIA, Arm, UEFI or QNX documentation or staff statement; URL given), HYPOTHESIS, UNKNOWN. Line numbers marked `~` come from a web fetch of the raw file on 2026-09-11 and were not re-counted.

**Licence status**
- Every log an M5 session produces is evaluation output under NC QDL v7 4.6(i). It stays private until the supervising professor has been consulted. This design quotes no figure from any run.
- No QNX-shipped binary was read for this design. The only binary headers read were NVIDIA's L4TLauncher and the Linux kernel `Image` from the L4T download.
- The EFI file M5 stages embeds the M1b kimg, which carries QNX bytes. It is never committed: `.gitignore:49` (`*.efi`), `:53` (`out/`), `:87` (`*.kimg`).

---

## 0. Summary

**Objective.** Show that a cold boot through the board's UEFI firmware, with no Linux and no kexec in that power cycle, reaches our startup. If it is cheaply reachable in the same attempt, also show procnto up with a stock identity check. Nothing is measured.

**Owner scope (2026-09-11, option B).**
- **Required:** our startup is reached from a UEFI cold boot (tier T2, §5).
- **Attempted and recorded:** procnto up and a stock `pidin info` (T3).
- **Deferred to the post-freeze campaign:** the M3 and M4 medians under UEFI entry against kexec entry (plan:474), and every other timing or residual-state comparison (§5.4).
- **Informs:** the entry-path item of the freeze gate (plan:441). M5 does not decide it (D6).

**Chosen path: option A.** A small EFI application of our own, `M5LOAD.EFI`, is launched from the firmware's built-in UEFI Shell (`Boot0007`). It embeds the unchanged M1b image `m1b-p1.kimg` (sha256 `cf0715ef…bd2f8e`). It checks the firmware memory map, places the kimg at `0x80080000`, exits Boot Services, cleans the data and instruction caches over the image, turns the MMU off and branches to the shim with the kexec entry contract (plan §3.3). From the shim onward, every byte is the byte that ran M1b's R1 (r/m1b-runs.md, R1 row).

**Why A** (§3.2):
1. **One variable.** Shim, startup, IFS and generator stay byte-identical, so the deferred campaign can compare one kimg under two entry paths.
2. **Plan §3.5 holds by construction.** No variable write, one new ESP file, no GRUB or L4TLauncher chain, and the library `_start` → `cstart` path never runs with Boot Services live (plan:205).
3. **Most of its software risks close on the PC.** Both local QEMU builds ship `edk2-aarch64-code.fd` (VERIFIED), so PE acceptance, the hand-over registers and EL, position independence and the map refusals are tested with no board (T0). Cache coherency after the copy is not: QEMU re-translates code the guest writes. So the build gate checks the cache steps statically, and only R1 exercises them (§3.2 item 4).
4. **Nothing irreversible happens before `go`.** The default `check` mode returns to the Shell, and so does every refusal.

**What changes against the plan's M5-F (plan:408-417)**
1. **The pass token.** `Entering startup...` is printed only by the library's `efi_entry_point` (lib/efi_entry_point.c:49), which option A never runs. The equivalent on the TCU is the shim banner, then startup's first line, `t234: WDT0 CR=… SR=…` (board/wdt.c:52). §5 defines the tiers (C5).
2. **"No UEFI variable is written" gets an operational test.** The firmware itself writes variables on every boot (C10). M5 compares the variable set against a control cold boot (§5.2).
3. **The medium is the ESP, with the file in its root.** A USB stick would make the firmware write a new `Boot####` and `BootOrder` when it enumerates the stick (C9).
4. **A wiring change and a new PC tool.** The UEFI menus need the adapter's TX on J14 pin 3 (C13), and a PC terminal that both sends keys and keeps the byte-exact COM3 log (C14).
5. **Plan §8 #12 (`mkifsf_uefi`) no longer gates M5-F.** It gates only option B.

**Pass tiers** (§5):

| Tier | Where | Evidence | Required |
|---|---|---|---|
| T0 | PC, QEMU with edk2 | header gate; `check`; `go` into a contract probe; three refusal cases | before any board session |
| T1 | board, UEFI Shell | `M5L CHECK PASS` over ConOut, then the Shell prompt again | yes |
| T2 | board, after `go` | `T234-SHIM EL=2 … JUMP`, then `t234: WDT0 CR=` | **yes: M5-F** |
| T3 | board | M1b §8's R1 criteria on `m1b-p1`: the VHE line, `verdict=wired`, `T234 M1b -P1: procnto up`, `pidin info` with `Release:8.0.0`, the image's own reset | attempted, recorded |

**Session ladder** (§6.9):

| Step | Where | Purpose |
|---|---|---|
| T0 | PC | Build, header gate, QEMU cases |
| P1 | PC, board read-only, bench; owner present | Pre-flight checklist (§8); TX wire added by or under the owner |
| S1 | L4T | Backups, baseline snapshot S0, stage one file |
| P2 | board | Control cold boot, no key: autoboot survives the TX wire; the file persists; the per-boot variable baseline |
| P3 | board | Cold boot → Shell → `M5LOAD.EFI check` (T1) → `reset` → L4T; state checks |
| R1 | board | Cold boot → Shell → `check` → `go` (T2, T3) → the image's reset → L4T; state checks |
| C | board, bench | TX wire removed; the file removed (D10) |

**What a pass settles**
- On this board and firmware, a UEFI-entered payload reaches our startup at EL2 through the same shim and kimg as kexec entry.
- If T3 is reached: a firmware-entered QNX 8.0 kernel runs on Tegra234 in a power cycle in which Linux never ran.
- The Shell path to it writes no UEFI variable and adds one ESP file, and the board then boots its unchanged L4T.

**What it is not**
- Not a timing of anything, and not the medians comparison.
- Not evidence that UEFI leaves cleaner state than kexec, or that DMA is quiescent.
- Not an unattended entry path: it needs an operator at the UEFI menus.
- Not option B, not A', and not a vendor-shaped QNX UEFI boot.

---

## 1. Inputs and contradictions resolved

**Inputs:** the brief; plan §3.3, §3.5, M5-F, §7 item 1 and §8 #12; r/research-uefi.md; r/harvest-orin.md; r/serial-console-wiring.md; r/blackbox-verified.md; r/m0-hang-watchdog.md; r/m1b-runs.md; r/m1b-design.md §8; the shim, board and library sources as cited; NV and UP sources fetched on 2026-09-11; the L4T header read.

| # | Contradiction or open point | Resolution | Evidence |
|---|---|---|---|
| C1 | Brief C1: does the native QNX UEFI path exit Boot Services before `cstart`? | **Yes.** `efi_entry_point` prints `Entering startup...`, snapshots the map, calls `ExitBootServices`, then `cstart()` (lib/efi_entry_point.c:49, :91-94). The later hook runs only if `uefi_exit_init()` armed it (lib/uefi.c:138-142). So option B stays inside plan:205. It has no exit retry: a failure prints and falls through (lib/efi_entry_point.c:90-98). | VERIFIED |
| C2 | Secure Boot state | **Disabled** (r/harvest-orin.md:44). §8 item 9 reads it again, because enrolling keys would change it. | VERIFIED |
| C3 | `HCR_EL2.E2H` as the firmware leaves it | **UNKNOWN, and harmless.** The shim clears both timer views, then sets `HCR_EL2` to RW only (shim/t234-shim.S:291-304). Its banner prints the inherited value (:168-171). | VERIFIED code; value UNKNOWN |
| C4 | MMU, caches and interrupts at loader entry | **Assumed on and live** (UP ArmMmuLib and DXE core, brief C4). The loader masks DAIF, cleans the data cache, invalidates the instruction cache and clears `SCTLR_EL2.{M,C,I}` either way (§3.3 steps 11-13). | UP source (brief); design |
| C5 | Plan M5-F: the PE "prints `Entering startup...`" (plan:411) | **Under A that string never prints.** Its only source is lib/efi_entry_point.c:49, and A enters startup through the shim. The owner's "or its equivalent on the TCU" is T2: the shim banner, then `t234: WDT0 CR=`, startup's first print after `select_debug` (board/main.c:193, :232; board/wdt.c:52). Appendix A lists the plan text. | VERIFIED |
| C6 | Brief §3 step 8: `x1` = 0 is required, because lib/aarch64/is_uefi_boot.c:28 reads `boot_regs[1]` as a system table | **Moot for startup.** The shim loads `x0` from its saved DTB and zeroes `x1`-`x3` before it branches into the IFS (shim/t234-shim.S:361-364), whatever the loader passed. The loader still sets them to 0 for the arm64 contract the shim assumes. Brief unknown #7 closes. | VERIFIED |
| C7 | Brief §3 step 7: at EL1, skip the EL2 writes and let the shim's kill switch reset | **Changed.** The loader refuses `go` when `CurrentEL` is not 2, and returns to the Shell. The shim would only print `EL!=2 abort` and reset (shim/t234-shim.S:158-164), so exiting Boot Services first gains nothing and loses the Shell. | VERIFIED shim; design |
| C8 | Brief §3: the PE header from `objcopy -O pei-aarch64-little`, or hand-written | **Hand-written, in the shape this firmware already loads on every boot.**<br>- **Upstream rule.** `CoreLoadPeImage` first tries `AllocateAddress` at ImageBase when relocations are stripped, or when `PcdImageLargeAddressLoad` is set and ImageBase is at least `0x100000`. It falls back to any address only when relocations are not stripped (UP `MdeModulePkg/Core/Dxe/Image/Image.c`, `CoreLoadPeImage`; fetched, line numbers not captured).<br>- **So:** a loader linked inside the window could be placed on top of its own target, and a `RELOCS_STRIPPED` header loads only at its ImageBase.<br>- **Precedent, read today.** The L4T kernel `Image`: Characteristics `0x0206`, ImageBase 0, SectionAlignment `0x10000`, Subsystem 10, no base-relocation directory. L4TLauncher: Characteristics `0x002E`, ImageBase 0, SectionAlignment and FileAlignment `0x1000`, Subsystem 10, a `.reloc` section. Neither sets `RELOCS_STRIPPED`. Both have the same sizes as the board's copies (r/harvest-orin.md:72-73).<br>- The flags `objcopy` would emit are UNKNOWN, so that route is not used. | VERIFIED (UP source; L4T header read); identity with the board's files HYPOTHESIS |
| C9 | Brief D3: the ESP or a USB stick; the stick "adds a mapping step" | **The ESP, for a stronger reason.** `EfiBootManagerRefreshAllBootOption` enumerates every removable BlockIo and SimpleFileSystem device, whether or not it holds a boot file, and writes new non-volatile `Boot####` variables and `BootOrder` (UP `MdeModulePkg/Library/UefiBootManagerLib/BmBoot.c` ~2770-2920). NVIDIA's platform boot manager calls the stock refresh (r/research-uefi.md:118-126). A stick would break the pass line on its first boot. The SD card's ESP already has its option, `Boot0001` (r/harvest-orin.md:75), and a new file on it creates none. | VERIFIED UP source; NV fork HYPOTHESIS |
| C10 | Plan M5-F: "no UEFI variable is written" (plan:412) | **Not checkable literally.** `BootChainDxe` writes `BootChainFwCurrent` at every driver initialisation (NV `Silicon/NVIDIA/Drivers/BootChainDxe/BootChainDxe.c` ~508), and every boot-option launch sets the volatile `BootCurrent` (UP `BmBoot.c` ~3022-3028). **Operational test:** §5.2 item 4 compares each snapshot against a control cold boot. | VERIFIED source (fetch) |
| C11 | Brief §4: the Shell disarms the boot manager's 5-minute watchdog | **It does, and the time before the Shell needs a bound too.**<br>- NV `BootWatchdog` arms the UEFI software watchdog at driver start, from `PcdBootWatchdogTime` (minutes) or a device-tree override, and disarms it at ReadyToBoot (NV `Silicon/NVIDIA/Drivers/BootWatchdog/BootWatchdog.c` ~32-85). The PCD's value is UNKNOWN.<br>- ESC starts the application named by `PcdBootManagerMenuFile` (NV `Silicon/NVIDIA/Library/PlatformBootManagerLib/PlatformBm.c` ~1502-1516). The boot manager skips ReadyToBoot for exactly that file, and arms a 5-minute watchdog before starting an image (UP `BmBoot.c` ~3033-3037, ~3106, ~3654).<br>- So time in the menus may run under a software watchdog. §2 rule 5 bounds it.<br>- None of these timers outlives `ExitBootServices`: they are Boot Services timer events. | VERIFIED source (fetch); PCD values UNKNOWN |
| C12 | Brief unknown #9: does UEFI ConOut reach COM3? | **Yes.** The private M3 COM3 captures of 2026-09-10 (`results/orin-native-port/20260910T2100Z/m3/`, cited by name) carry the firmware banner and the three hotkey lines. Their text is in NV `PlatformBm.c` ~1625-1631: ESC for Setup, F11 for the Boot Manager Menu, Enter to continue. One dot is printed per second of `PcdPlatformBootTimeOut` (~1810-1835). The configured `Timeout` is 30 s (r/harvest-orin.md:75). | VERIFIED |
| C13 | M0-M4 wiring is receive-only: "adapter RX to J14 pin 4, adapter GND to J14 pin 7, nothing else" (r/serial-console-wiring.md:82) | **M5 adds the adapter's TX on J14 pin 3**, the board's `UART2_RXD` input at 3.3 V (r/serial-console-wiring.md:71-72, from the carrier specification's Table 3-4).<br>- NVIDIA's Board Automation page labels pin 3 "UART2 TXD" (r/research-uefi.md:318). That is the adapter-side name; the capture on pin 4 settled the direction.<br>- Input reaching UEFI over this UART: VENDOR_CLAIM (the ESC prompt on the serial console) and COMMUNITY (a floating RX line opening a menu on an Orin Nano carrier, https://forums.developer.nvidia.com/t/uefi-waits-in-boot-maintenance-manager-during-boot/298980).<br>- Owner decision D8. | VERIFIED record; input VENDOR_CLAIM |
| C14 | Which PC program sends the keys? | **A new two-way terminal, `uefi/com3-term.ps1`.** COM3 is exclusive (r/m2-runs.md:135-137), and the M4 capture script only receives (orin-native/m4/capture-com3-raw.ps1:1-37). Neither PuTTY nor pyserial is installed on this PC (checked 2026-09-11). Installing PuTTY is the alternative (D7). | VERIFIED |
| C15 | Brief §4 Never: "leave J14 RX floating (autoboot stalls)" | **Refined.** M0-M4 ran with pin 3 unconnected, and every warm reset autobooted L4T (r/m1b-runs.md; r/m2-runs.md). The forum stall was a custom carrier with no pull-up (the thread in C13). The new hazard is the TX wire itself: an adapter unplugged from USB while still wired may hold pin 3 at a level the firmware reads as input (HYPOTHESIS). So the TX wire is connected only while the terminal runs, P2 tests autoboot with it connected, and it comes off at session end (§6.8). | VERIFIED records; hazard HYPOTHESIS |
| C16 | Brief §2 A': a dual-format shim, "Linux-style" | **The precedent is this board's own kernel.** The L4T `Image` starts with `MZ`, carries `ARM\x64` at `0x38` and its PE header at `0x40` (header read today). A' stays a freeze candidate, not an M5 path. | VERIFIED header read |
| C17 | Plan:76 non-goal "no … ESP writes on the primary path", against M5 staging a file | **Consistent.** M5 runs under §3.5 Fallback B's rules, which allow one new ESP file after the backups (plan:197-204). | VERIFIED |

---

## 2. Design rules

1. **One variable: the entry path.**
   - The kimg is `m1b-p1.kimg`, sha256 `cf0715ef7f0e447228d336557772a53b0f822709428a2f03610cfbaec9bd2f8e`, the R1 image of M1b (r/m1b-runs.md, R1 row; re-hashed on 2026-09-11).
   - The loader build refuses any other bytes. Nothing under `shim/`, `startup/` or `board/` is edited or rebuilt.
   - All new code runs before the shim's first instruction.
2. **Nothing irreversible before `go`.**
   - `M5LOAD.EFI` with no argument, or with `check`, never calls `ExitBootServices`. It frees what it allocated and returns to the Shell.
   - Every refusal in `go` before `ExitBootServices` also returns to the Shell.
3. **After `ExitBootServices`, every path ends in a jump or a reset.**
   - A failed exit is retried with a fresh map, then ends in PSCI `SYSTEM_RESET`.
   - A fault in the loader's post-exit code lands in the loader's own `VBAR_EL2` table, which prints over the TCU and resets.
   - Before the branch, the copied kimg is made safe to fetch: the data cache cleaned, the instruction cache invalidated, barriers, then the MMU off. It is the order kexec's relocator uses, and the order edk2 uses for every image it loads (§3.3 steps 12-13).
   - From the shim on, M1b's coverage applies unchanged (m1b-design.md §2).
   - Residual, as in M0-M4: a hang with interrupts masked costs a power cycle.
4. **We write no UEFI variable, and one ESP file.**
   - The Shell is reached only through the existing `Boot0007`. There is no `bcfg`, `efibootmgr` write, `setvar`, "Boot From File", menu setting, key enrolment or capsule.
   - The ESP gains `\M5LOAD.EFI` in its root and nothing else. The root is used so that no directory is created either.
   - The loader writes no file.
5. **Keep pre-ReadyToBoot time short, and never cut power before a boot option starts.**
   - From the first ESC, the `Shell>` prompt is reached within 120 s of operator time. Launching `Boot0007` signals ReadyToBoot, which validates the boot chain (NV `BootChainDxe.c` ~286-293) and disarms NV's boot watchdog (C11).
   - The menus are left only by launching a boot option or `Continue`. Power is never cut between power-on and the start of a boot option (the Shell, or L4T through `Boot0001`), in the menus or outside them. Bootloader slot failover counts unvalidated boots (VENDOR_CLAIM, the forum thread in C13). Its threshold is UNKNOWN, so no count of unvalidated boots is treated as safe.
   - **One exception: a firmware that has stopped.** It applies when all three hold: COM3 has shown no new byte for 10 minutes; its last output is not a menu or a prompt (a menu is left with `Continue`, §7 F3); and L4T has not answered ssh in that time. The operator records the last line, cuts power once and presses nothing, then lets L4T boot to a validated state before any other step. If that boot also stops before a boot option, board work stops and the owner decides. This rule never allows a second cut.
   - A board held in reset or in recovery by a miswired pin (§7 F36) has started no firmware boot, so its power cycle is outside this rule (HYPOTHESIS: MB1 never runs, so no boot attempt is counted).
6. **Key forwarding is disarmed by default.** `com3-term.ps1` sends nothing until the operator arms it, and disarms itself after the Enter that follows `go` (§4.2). An autoboot after a reset must never meet a stray key.
7. **Records, not measurements.**
   - Kept: the raw COM3 byte log, a key log, the pstore black box after a warm reset, and snapshots of board state before and after.
   - Every wait in §6 is a bound, not a result. No duration is reported.
8. **Earlier records stay untouched.** The loader build reads `shim/out/m1b/m1b-p1.kimg` read-only and writes only under `uefi/out/`. No file under `results/` from an earlier milestone, and no `logs/` file, is edited.

### Timeline of one `go` attempt: fault and hang coverage

| Phase | Where | Fault | Hang |
|---|---|---|---|
| Power-on to the hotkey lines | MB1, MB2, UEFI | The firmware's own handling | The firmware's own. A boot that stops before ReadyToBoot is unvalidated. Power is cut only under rule 5's exception |
| Menus to `Shell>` | UEFI, Boot Services | — | Operator bound of 120 s. A software watchdog may reset the board (C11) |
| Shell commands and `M5LOAD.EFI check` | UEFI application, Boot Services live | Returns to the Shell. An edk2 exception dump halts (HYPOTHESIS) | No watchdog, because the Shell disarmed it: power cycle, after a boot already validated |
| `go`, up to `ExitBootServices` | UEFI application | Refusals return to the Shell | As above |
| After the exit, up to the branch | loader, no firmware | The loader's vectors print `M5L-EXC` and reset. An exit failure resets | Unbounded (no watchdog, DAIF masked): power cycle |
| Shim | EL2, MMU off | The shim's vectors print `EXC` and reset. `BAD-LANDING` resets | Unbounded (residual, as in M0-M4) |
| Startup at `-P1 -Q enable,el2-host` | EL2 | The board EL2 vectors print and reset. The `hvtimer` STOP is a named crash (m1b-design.md §2) | M1b's bounds |
| procnto and the IFS script | EL2&0 | procnto's own handling. This kimg has no `-A` (m1b-p1.build:16), so an abnormal kernel termination spins | smpcheck's bounds. The script ends in `shutdown -S reboot` (m1b-p1.build:44) |
| Reset to L4T | firmware | — | Autoboot needs no key. A stop in the menus is handled by hand (§7) |

---

## 3. The boot path

### 3.1 Options

| Option | What | For | Against | Risk | Verdict |
|---|---|---|---|---|---|
| **A** | Our EFI loader, embedding the unchanged kimg | One kimg under both entries; §3.5 holds; T0 closes most software risks off the board, though not cache coherency (§3.2) | New code outside the M ladder; not a vendor-shaped boot; the map check is the only guard against firmware allocations | LOW-MEDIUM | **Chosen (D1)** |
| A' | The shim is also a PE (an `MZ`-compatible first instruction and a PE header inside the 8 KiB page), launched directly | One artefact for both entries; the L4T `Image` is the precedent (C16) | New shim bytes, so no longer M0-M4's; a tight 8 KiB budget; the PE entry must be position-independent | MEDIUM | Freeze candidate (D6) |
| B | A QNX-native UEFI IFS: `[virtual=aarch64le,uefi]`, `mkifsf_uefi`, `efi_entry_point`, `init_raminfo_efi` | The library's own path, with the real firmware map | PE ImageBase, entry RVA and `.reloc` UNKNOWN (plan:705); a stripped PE loads only at its ImageBase (C8); the shim's CPU0 duties move into startup; gates rework; no exit retry (C1); the campaign would compare two images | MEDIUM-HIGH until plan §8 #12 closes | Costed in §4.4, not built |
| C | GRUB, or an L4TLauncher `LINUX=` or GRUB-mode chain | Nothing over A | On plan §3.5's Never list (plan:205). Installing GRUB writes the ESP and boot variables (VENDOR_CLAIM, https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Bootloader/UEFI.html). L4TLauncher decrements the rootfs retry counter and arms a 5-minute watchdog (brief: NV `L4TRootfsValidation.c` ~590-600, ~722-735; `L4TLauncher.c` ~1647) | — | Rejected |

### 3.2 Why A

1. **It is the only option that keeps the M0-M4 bytes.** The deferred comparison means something only if one kimg SHA-256 runs under both entries. A needs no generator variant, no new startup and no new shim.
2. **It needs no unknown about QNX tooling.** Plan §8 #12 can stay open without blocking M5. B's header facts would come from a header read of our own `mkifs` output (plan:723-724), left as parallel desk work (§12 Q8).
3. **Its likely failures are early and soft.** A PE the firmware rejects, and a window the firmware occupies, both show at the Shell before anything irreversible (§7 F7, F13-F16).
4. **Most of its software unknowns close on the PC.** T0 runs the same loader code under upstream edk2 in QEMU (§6.1). It exercises PE acceptance, the hand-over contract's registers and EL, position independence and the map refusals.
   - **What T0 cannot exercise: cache coherency.** QEMU's TCG invalidates translated code whenever the guest writes a page that holds it (VENDOR_CLAIM, https://www.qemu.org/docs/master/devel/tcg.html, section "Self-modifying code and translated code invalidation"). A loader with no instruction-cache step would therefore still pass T0c.
   - The gate checks that step statically (§3.4 item 9). Only R1 exercises it (R33), like the other board-only risks in §9.
5. **It relies only on mechanisms already working on this board.** `Boot0007` is present (r/harvest-orin.md:75). The firmware's image loader starts the Linux kernel, whose header shape the loader copies, on every boot (C8). The shim's contract ran in M0-M4.

### 3.3 The loader, `M5LOAD.EFI`

**Interface**
- Launched from the Shell as `M5LOAD.EFI check` or `M5LOAD.EFI go`. The Shell passes the word as UCS-2 LoadOptions. No argument, or any other word, means `check`.
- Output is ConOut text, one token per line, each line starting `M5L `. After `ExitBootServices`, tokens start `M5L-` and go straight to the TCU TX mailbox `0x0C168000` through the shim's bounded poll (shim/t234-shim.S:420-435), our own code.
- Build constants: the kimg's CRC32 and size; the target `0x80080000`; the window `[0x80000000, 0xBE000000)` (board/t234_startup.h:101-102); the black-box zone `[0x2_72770000, 0x2_727F0000)` (r/blackbox-verified.md:15-20).

**Sequence.** `image_size` comes from the kimg header. It is `0x2a0000` for this kimg (shim/out/m1b/m1b-p1.shim.txt), so the target is `[0x80080000, 0x80320000)`.

1. **Start.** Print `M5L start mode=<check|go> el=<CurrentEL> ctr=<CTR_EL0> self=<ImageBase>+<ImageSize>`. The `self` fields come from `EFI_LOADED_IMAGE_PROTOCOL` and show where the firmware put the loader (C8). `ctr` records the cache line sizes step 12 uses, and the DIC and IDC bits (§12 Q16).
2. **Device tree.** Find configuration table `b1b621d5-f19c-41a5-830b-d9152c69aae0` (r/research-uefi.md:159-162). Refuse unless it is present, its magic reads `d00dfeed` big-endian, and its `totalsize` is at most 16 MiB. Print `M5L fdt addr=… size=…`.
3. **Source check.** `gBS->CalculateCrc32` over the embedded kimg must equal the build constant. Print `M5L crc src=ok|bad`.
4. **Kimg header.** Refuse unless the magic at `0x38` is `ARM\x64`, `text_offset` is `0x80000` and `image_size` equals the build constant.
5. **Reserve the target.** `AllocatePages(AllocateAddress, EfiLoaderData, 0x80080000, image_size / 0x1000)`. On failure, print the status and every map descriptor that overlaps the target, then refuse.
6. **Copy and verify.** Copy the kimg in. The CRC32 of the destination must match. Print `M5L crc dst=ok|bad`. The copy is only data: the kimg never runs with the MMU on, so a no-execute policy on `EfiLoaderData` does not matter.
7. **Map checks.** `GetMemoryMap` into a pool buffer. Print each descriptor that overlaps the window, the zone or the device tree as `M5L map type=<name> start=… pages=… attr=…`. Then:
   - **Window:** every byte of `[0x80000000, 0xBE000000)` lies in LoaderCode, LoaderData, BootServicesCode, BootServicesData or ConventionalMemory. A gap or any other type refuses (`M5L REFUSE window reason=gap|type at=…`). startup claims the whole window (board/init_raminfo.c:43).
   - **Zone:** the descriptor covering the zone is EfiReservedMemoryType, Loader*, BootServices*, ConventionalMemory or ACPIReclaimMemory, or the zone is not in the map. RuntimeServices*, MemoryMappedIO*, UnusableMemory, ACPIMemoryNVS, PalCode, PersistentMemory or UnacceptedMemory refuses. The shim writes the zone unconditionally (shim/t234-shim.S:110-138). The type is printed either way.
   - **Device tree:** `[fdt, fdt + totalsize)` does not overlap the target. Elsewhere in the window is allowed, because startup reserves it (board/main.c:247-248).
8. **`check` ends here.** Print `M5L CHECK PASS`, or `M5L REFUSE <rule>` for the first rule that failed. Free the pages and the pool. Return to the Shell.
9. **`go`: last checks.** Refuse unless every rule passed and `CurrentEL` is 2 (C7). Print `M5L GO`, the last ConOut line.
10. **Exit Boot Services.** Call `GetMemoryMap`, then `ExitBootServices(ImageHandle, MapKey)`, with no call between them. On `EFI_INVALID_PARAMETER`, repeat the pair, up to four attempts in all (the retry shape of lib/uefi.c:103-112). If every attempt fails: mask DAIF, do steps 12-13, write `M5L-EBS FAIL` to the TCU and issue PSCI `SYSTEM_RESET` over SMC.
11. **Take the CPU.** `msr daifset, #0xf`. Install the loader's `VBAR_EL2` table; each entry writes `M5L-EXC ESR=… ELR=…` and resets.
12. **Make the copied kimg safe to fetch as code.** Step 6 wrote it as data and step 14 fetches it as code, so both caches are handled, in this order:
    1. `dc civac` over the target and over the loader's own trampoline, stepping by the data-cache line size in `CTR_EL0`, then `dsb sy`;
    2. `ic iallu`, then `dsb sy` and `isb`.

    **Why.**
    - **The contract.** The arm64 boot contract the shim assumes requires the instruction cache to hold no stale entry for the loaded image, as well as a data-cache clean (VENDOR_CLAIM, https://docs.kernel.org/arch/arm64/booting.html, "Call the kernel image"). `dc civac` acts on the data cache only.
    - **kexec entry already does it.** Linux v5.15's relocator runs `dc ivac` and `dsb sy` over each destination page before copying it. Then, before `br x17`, it runs `dsb nsh`, `ic iallu`, `dsb nsh` and `isb` (LX `arch/arm64/kernel/relocate_kernel.S` ~45-80, fetched). Without this step the two entry paths would differ in cache state, against §3.2 item 1.
    - **The firmware does it for every image it loads.** `CoreLoadPeImage` calls `InvalidateInstructionCacheRange` (UP `MdeModulePkg/Core/Dxe/Image/Image.c` ~1066-1068). That routine cleans data-cache lines and issues a data barrier, then invalidates instruction-cache lines and issues an ISB (UP `ArmPkg/Library/ArmCacheMaintenanceLib/ArmCacheMaintenanceLib.c` ~17-72). UP's whole-cache form is `ic iallu`, `dsb sy`, `isb` (`ArmInvalidateInstructionCache` in UP `ArmPkg/Library/ArmLib/AArch64/AArch64Support.S`).
    - **UEFI entry may need it more than kexec** (HYPOTHESIS). edk2 runs identity-mapped (C4). Firmware code that ran from the window earlier in the boot would have left instruction-cache lines at the very addresses the shim is fetched from. Under kexec, code in those pages ran at Linux's linear-map addresses.
    - **Why `ic iallu`, not per-line `ic ivau`.** It needs no address for the target and covers lines filled from anywhere. kexec's relocator already runs it at EL2 on this board (upstream source; NVIDIA's fork HYPOTHESIS, plan:93).
    - **`dsb sy` already builds and runs here,** in the shim's own cache clean and reset (shim/t234-shim.S:125-130, :386-387), with the toolchain the shim build uses (shim/build-shim.sh:86-94).
13. **MMU off.** From the trampoline, which edk2 identity-maps (UP ArmMmuLib, brief C4), clear `SCTLR_EL2.{M,C,I}`, then `isb`. The same contract asks for the MMU off (VENDOR_CLAIM, https://docs.kernel.org/arch/arm64/booting.html; EBBR, https://arm-software.github.io/ebbr/).
14. **Branch.** Write `M5L-EBS ok` and `M5L-JUMP` to the TCU (device access, MMU off). Set `x0` = FDT and `x1` = `x2` = `x3` = 0, then `br 0x80080000`.

**The loader never:** writes a file or a variable; calls `SetWatchdogTimer`; reads or writes MMIO other than the TCU TX mailbox; touches the GIC, timers, clocks or secondary CPUs; prints between the final `GetMemoryMap` and `ExitBootServices`.

### 3.4 PE layout and the header gate

**Layout.** Our own code, written from the PE/COFF specification. The Linux header (GPL-2.0) is precedent only and is not copied.
- A DOS header whose `e_lfanew` points at the PE header. Machine `0xAA64`. Characteristics `EXECUTABLE_IMAGE | LINE_NUMS_STRIPPED | DEBUG_STRIPPED` (`0x0206`), never `RELOCS_STRIPPED`.
- A PE32+ optional header: ImageBase 0; SectionAlignment and FileAlignment `0x1000`; Subsystem 10 (EFI application); DllCharacteristics 0; six data directories, all zero.
- One `.text` section, read-write-execute, holding the code, strings, the embedded kimg and a zero-filled pool. File offsets equal RVAs.
- Freestanding, position-independent code: PC-relative addressing only, no absolute address constants, no relocation records.

**Gate** (`uefi/m5-gate.py`, run by `uefi/build-m5-loader.sh`; any miss fails the build):
1. `MZ`, `PE\0\0`, Machine `0xAA64`, PE32+ magic `0x20b`, Subsystem 10.
2. Characteristics bit `0x0001` clear. ImageBase 0, so outside the window.
3. SectionAlignment and FileAlignment `0x1000`; one section; `SizeOfHeaders` `0x1000`; `SizeOfImage` page-aligned and covering the section.
4. The entry RVA lies inside `.text`, before the embedded blob.
5. Every data directory is zero.
6. **Position independence, tested.** The linked ELF carries no relocation records, and linking at base 0 and at base `0x100000` produces byte-identical files.
7. The embedded blob's sha256 equals the pinned kimg's. The CRC32 and size constants equal values computed from it (Python `zlib.crc32`, the CRC-32 that UEFI's `CalculateCrc32` defines, VENDOR_CLAIM).
8. The T0 build and the board build differ only in the blob and its two constants (§6.1).
9. **The cache and MMU sequence, read statically.** The gate disassembles our own linked ELF over the trampoline's symbol range only, never over the embedded blob. That range must show, in this order: the `dc civac` loop, `dsb sy`, `ic iallu`, `dsb sy`, `isb`, the `msr sctlr_el2` write, `isb`, then the branch. T0 cannot test this sequence (§3.2 item 4), so the gate checks that it is present.
10. The gate prints the output's sha256, which is the value staged.

### 3.5 After the branch: what the shim and startup see

| Item | kexec entry (M0-M4) | UEFI entry through the loader | Class |
|---|---|---|---|
| Exception level | 2 (plan:93) | 2; the loader refuses otherwise | HYPOTHESIS until P3 |
| `HCR_EL2` | E2H, TGE and RW left by Linux (plan:93) | the firmware's value | UNKNOWN; the T2 banner prints it |
| MMU, caches, DAIF | off, off, masked (kexec relocator) | off, off, masked (loader) | design |
| Instruction cache over the image | invalidated: `ic iallu` before `br x17` (LX relocator, §3.3 step 12) | invalidated: `ic iallu` (loader, §3.3 step 12) | VERIFIED upstream source; NVIDIA's kernel fork HYPOTHESIS; the effect is board-only (R33) |
| Landing | kexec placement, checked by the shim | `AllocateAddress`, checked by the loader and by the shim | design |
| `x0` | kexec's copy of Linux's tree | the firmware tree: the embedded DT plus overlays and patches (NV `DxeDtPlatformDtbKernelLoaderLib.c`, r/research-uefi.md:176-186) | VERIFIED mechanism; content HYPOTHESIS |
| What startup takes from the tree | the CPU list, and the tree for user space (board/main.c:142-150) | the same; PSCI stays hard-coded (board/main.c:158-159) | VERIFIED |
| Secondary cores | offlined by Linux | never started (EBBR §3.2.1, VENDOR_CLAIM); `-P1` starts none | VENDOR_CLAIM |
| GIC | left enabled by Linux, and startup re-initialised it (r/m1-first-procnto.md:41) | quiesced by edk2's GICv3 driver at exit | HYPOTHESIS (driver not re-read) |
| EL2 timers | CNTHP had fired (plan:93) | edk2 stops its timer at exit | HYPOTHESIS; the shim clears them anyway |
| WDT0 | configured by systemd, does not fire (r/m0-hang-watchdog.md) | systemd never ran; the firmware's watchdog is a software timer (C11) | the T2 line prints it |
| Devices and DMA | Linux's shutdown path; no quiesce in M1b | NV DeviceDiscovery power-gates devices at exit (brief) | HYPOTHESIS; cannot be shown (§10) |
| CPU frequency | the Linux governor | the firmware's setting (`TegraCpuFreqDxe` exists at r36.4.4) | UNKNOWN; not recorded |
| TCU | the SPE drains after Linux (plan K4) | the SPE drains after the firmware; L4T's own console works after its EFI stub exits (r/harvest-orin.md:55) | VERIFIED indirectly |

---

## 4. Image and code deltas

### 4.1 Unchanged and pinned

| Artefact | sha256 | Status |
|---|---|---|
| `shim/out/m1b/m1b-p1.kimg` | `cf0715ef7f0e447228d336557772a53b0f822709428a2f03610cfbaec9bd2f8e` | re-hashed 2026-09-11; equals the R1 prefix in r/m1b-runs.md |
| `shim/out/m1b/m1b-p1.ifs` | `24cdd4a15fdd870db879cc09d15c15ac8a10a4dfcd4e200119bc111f885b0be1` | re-hashed |
| `shim/out/m1b/m1b-p1.build` | `29efcfef385cacc6ebe322283d1dbf97bf3d7764aade8f2d28a21898f2e79374` | re-hashed |
| `shim/t234-shim.S` | `48bdde3d3bbe1d4f1a9926ed67de2e6d1da73f03e97ce7ab64e47b8616ebd4ac` | re-hashed |
| `shim/build-shim.sh` | `ae7814d1cf2b63b206c4d3f4dafb5963838db9af84a45e7f28109b933c5c21db` | re-hashed |
| `startup/make-m1b-images.sh` | `9965801504355c97bf0a4d0bf339aee9952cefe037635ace328e7d40abfeb1df` | re-hashed |
| startup build | `90bf724c…61896` | r/m1b-runs.md:27; its bytes are inside the kimg |
| smpcheck build | `f8e2c307…66b0` | r/m1b-runs.md:28; its bytes are inside the kimg |

- **No generator variant and no flag.** The IFS, its buildfile and every M1-M4 image stay exactly as built. No M2, M3 or M4 image is read.
- **Why `m1b-p1`:** it is the smallest image that passed at EL2, with one core, no qvm, and its own reset. `-P6`, M3 and M4 images under UEFI entry are campaign items (D9).

### 4.2 New files (proposed; this design creates none)

All live under `uefi/` = `orin-native/uefi/`, as our own code under MIT, like the shim. Outputs go to `uefi/out/`, which `.gitignore:53` (`out/`) and `:49` (`*.efi`) already ignore.

| File | Role |
|---|---|
| `m5load-head.S` | DOS and PE headers (§3.4), the entry, the post-exit trampoline with the cache and MMU sequence (§3.3 steps 12-13), the `VBAR_EL2` table, the TCU `putc` |
| `m5load.c` | Freestanding C: arguments, device tree, CRC32, allocation, copy, map checks, tokens, `ExitBootServices` |
| `efi-min.h` | The few UEFI types and table offsets used, written from the UEFI specification |
| `m5load.lds` | A single-section link with a fixed layout and the blob last |
| `build-m5-loader.sh` | `KIMG=<path> KIMG_SHA256=<pin> [T0=1]`: builds, runs the gate, prints the output sha256 |
| `m5-gate.py` | The §3.4 gate, including the T0-versus-board comparison and the static trampoline check |
| `t0/contract-probe.S` | The T0 payload: an arm64-headered page linked at `0x80080000` that prints `PROBE EL= X0= X1= X2= X3= MAGIC= SCTLR_EL2= DAIF= PC=` on QEMU's PL011, then powers off |
| `t0/run-t0.ps1` | The QEMU cases T0b-T0f (§6.1), each with its own log and timeout |
| `com3-term.ps1` | The two-way terminal (below) |
| `README.md` | Usage, and §7.4's Never list |

**`com3-term.ps1` requirements**
1. It opens COM3 at 115200 8N1 and writes every received byte unchanged to `-Out`, with the header and end lines of `capture-com3-raw.ps1` (its :16-22).
2. It keeps a separate key log: the UTC time and the bytes of every send.
3. Key forwarding starts **disarmed**. F12 toggles it and is never sent. The console shows the state at all times.
4. When armed, it sends only: ESC as `1b`; the arrows as `1b 5b 41`, `42`, `43`, `44`; Enter as `0d`; Backspace as `08`; printable ASCII as itself.
5. After it sends the `0d` that ends a typed line reading `M5LOAD.EFI go`, it disarms itself.
6. Ctrl+] closes the port and exits. It is launched from PowerShell (r/m2-runs.md:135-137).

### 4.3 Existing files

- **None change for M5.**
- Startup text written for kexec reads oddly under UEFI entry (board/wdt.c:55; board/main.c:10-14; board/init_raminfo.c:12-14). It is left alone, because editing it changes the startup and kimg pins. Appendix A lists it.
- `.gitignore` already covers `uefi/out/` and `*.efi`. T0 and session logs use the `*.log` rule (`.gitignore:57`).

### 4.4 Option B's delta, for costing only (from the brief §2)

- **Buildfile:** `[virtual=aarch64le,uefi]`, a new `[image=]` outside the window, `mkifsf_uefi`.
- **Board:** a `_start` that branches to `efi_entry_point`; `init_raminfo_efi` over the pre-exit map, never `init_raminfo_uefi`, which calls `GetMemoryMap` live; the tree from `efi_get_table()`.
- **The shim's CPU0 duties move into startup:** the EL kill switch, the early `VBAR_EL2`, timer and trap clean-up, and the black-box header.
- **Gates that change** (line numbers from the brief): the landing check, the `image_paddr` gate (startup/make-m3-images.sh:769-780), `T234_SHIM_BASE`, and the build-board.sh symbol gate (:176-182), which today forbids `efi_entry_point`.
- **New startup and kimg pins,** so any comparison with M1-M4 would cross two images.

---

## 5. Tiers, pass and fail

### 5.1 Tier tokens

**T0 (PC).** Cases T0a-T0f in §6.1 each end as stated there.

**T1 (board, `check`).** In one COM3 log, in this order:
- `M5L start mode=check el=2 ctr=… self=…`;
- `M5L fdt addr=… size=…`, `M5L crc src=ok`, `M5L crc dst=ok`;
- the `M5L map` lines;
- `M5L CHECK PASS`, then the Shell prompt.

**T2 (board, `go`; this is M5-F).** After `M5L GO`, in this order. The two `M5L-` lines exist only on COM3; the shim's and startup's lines are also in the pstore black box after a warm reset.
- `M5L-EBS ok`, `M5L-JUMP`;
- the shim bank line `T234-SHIM EL=2`, with `PC=0000000080080000` and `DTBMAGIC=00000000edfe0dd0`, a big-endian `d00dfeed` (shim/t234-shim.S:252-258);
- `NORMALISED`, `TCUDROPS=`, `JUMP`;
- `t234: WDT0 CR=… SR=…` (board/wdt.c:52).
- None of `BAD-LANDING`, `EXC `, `EL!=2`, `M5L-EXC`, `M5L-EBS FAIL`.

**T3 (board, attempted).** M1b §8's criteria for R1 on `m1b-p1` (r/m1b-design.md:814-860): items 1, 3, 4, 5, 6, 7, 8 and 10 at N=1, and item 9's reset. In short:
- `Enabling EL2 host hypervisor support (VHE)`;
- `t234: cpu 0 el2-host EL2 HCR_EL2=…` with E2H and TGE set, and `t234: hvtimer cpu 0 verdict=wired`;
- `Starting next program`, then `T234 M1b -P1: procnto up` (m1b-p1.build:22);
- **the stock identity check:** `pidin info` (m1b-p1.build:28) prints `CPU:AARCH64 Release:8.0.0` and one `Cortex-A78ae` processor line;
- `SMPCHECK CENSUS PASS`, and `SMPCHECK RESULT PASS-DEGRADED cpus=1/6 secs=60 reasons=none`;
- `T234 M1b -P1: resetting so the log can be recovered` (m1b-p1.build:42), the firmware banner, then L4T with a new `boot_id` and PMC `reset_reason` `MAINSWRST`.

The labels say `M1b` because the kimg is byte-identical. That is expected.

### 5.2 M5-F pass

**M5-F is met** when one session shows all of the following:
1. **T1**, in P3 and again in R1.
2. **T2**, in R1.
3. **ESP.** The SHA-256 listing of every file under `/boot/efi` after R1 equals the S0 listing plus exactly `/boot/efi/M5LOAD.EFI` with its staged hash. Hashes, not times: `BOOTAA64.efi`'s mtime follows the boot time (r/harvest-orin.md:76).
4. **Variables.**
   - A snapshot is the set of pairs (name, sha256 of contents) over every file in `/sys/firmware/efi/efivars`. `Δ(X,Y)` is the set of names added, removed or changed from snapshot X to snapshot Y.
   - `Δ(S1,S2)` and `Δ(S2,S3)` add no name and remove none.
   - Every name they change is also changed in `Δ(S0,S1)`, the control cold boot.
   - A name changed only in `Δ(S2,S3)` holds the verdict: take a warm control (§6.7 step 3). If `Δ(S3,S4)` changes the same name, it is per-boot firmware behaviour. If not, M5-F is not met.
   - `efibootmgr -v` equals S0's apart from its `BootCurrent` line.
5. **L4T back unchanged:** a new `boot_id`; `nvbootctrl dump-slots-info` shows S0's current and active bootloader slot; `extlinux.conf` and `BOOTAA64.efi` hash as in S0; `/sys/class/dmi/id/bios_version` reads as in S0.

**Recorded, not required:** T3, and the last T3 token reached.

**Record wording:** "M5-F met (T3 reached)", or "M5-F met, T3 not reached: last token `…`".

### 5.3 Fail and partial outcomes

- **T1 refuses** (§7 F10-F16): M5-F is not met in this session. The printed descriptors are the finding. Under D4 the loader is revised offline and T0 rerun; tolerance is never widened at the board.
- **T2 is not reached after `go`:** M5-F is not met. The last token names the stage.
- **State check 3, 4 or 5 fails:** M5-F is not met, whatever the tiers, until the difference is explained. §7 gives the recovery.
- **If M5-F cannot be met:** v1 keeps kexec as its only entry path, and the campaign drops the M5 comparison. Whether the M path still counts as ended is the owner's call (plan:417).
- **Retries.** An attempt that never reached `go` for an operator or host reason is repeated with the same file and not counted: a missed ESC, a capture that was not running, a file not found. A `go` is recorded as it happened and never replaced.

### 5.4 Deferred to the post-freeze campaign

- The M3 and M4 medians under UEFI entry against kexec entry, on one kimg (plan:474).
- Every residual-state comparison: clocks, CPU frequency, thermal, GIC and timer state, DMA.
- `-P4`, `-P6`, the M3 host and guest, and M4's trace under UEFI entry.
- Any cold-boot or firmware hand-off duration.
- An unattended UEFI launch (§5.5).

### 5.5 What M5 hands the freeze (plan:441)

Facts only. The decision is D6.
- The highest tier reached under UEFI entry.
- The UEFI path as built needs an operator at the firmware menus. Making it unattended needs a persistent `Boot####` or a `startup.nsh`, both on this design's Never list, so the freeze would have to accept one of them explicitly.
- A' would give one artefact for both entries (C16).
- The kexec path's costs are already on record: a running L4T, the quiesce and the governor pin (plan §3.4).

---

## 6. Procedure (owner present from P1 to C)

**Conventions**
- `PC$` is Git Bash on the PC; `PS>` is PowerShell on the PC.
- `L4T$` is the board over ssh, with `-o ServerAliveInterval=3 -o ServerAliveCountMax=2` under `timeout` (r/m2-runs.md:138-140).
- `Shell>` means typed into `com3-term.ps1` with forwarding armed.
- `<user>`, `<orin-ip>` and `<orin-key>` are redacted placeholders.
- `<rec>` is a private record directory `results/orin-native-port/<utc>/m5/`. Every file in it ends in `.log` (`.gitignore:57`).

### 6.1 T0: build and QEMU (PC, no board)

1. **Board build.** `PC$ KIMG=orin-native/shim/out/m1b/m1b-p1.kimg KIMG_SHA256=cf0715ef7f0e447228d336557772a53b0f822709428a2f03610cfbaec9bd2f8e ./orin-native/uefi/build-m5-loader.sh` writes `uefi/out/M5LOAD.EFI`. **T0a:** the gate passes (§3.4).
2. **T0 build.** `PC$ T0=1 ./orin-native/uefi/build-m5-loader.sh` embeds `t0/contract-probe` instead and writes `uefi/out/t0/M5LOAD.EFI`. The gate confirms the two builds differ only in the blob and its constants.
3. **QEMU.** `PS> orin-native\uefi\t0\run-t0.ps1` runs each case below with:
   - `E:/qemu-versions/qemu-11.1.0/qemu-system-aarch64.exe -M virt,virtualization=on,gic-version=3 -cpu max -smp 1`;
   - the pflash pair `share/edk2-aarch64-code.fd` and a scratch copy of `share/edk2-arm-vars.fd` (both present, VERIFIED);
   - a `fat:` drive holding the T0 build (the `vvfat` driver is present, VERIFIED);
   - serial output to a per-case log, and a timeout.

   In QEMU only, a `startup.nsh` on that FAT drive types the Shell commands. **Never on the board** (§7.4). If QEMU's edk2 publishes no device-tree table, the machine gains `acpi=off` (UNKNOWN which is needed).

| Case | Setup | Expected |
|---|---|---|
| T0b | `-m 8G`; `M5LOAD.EFI check` | `M5L CHECK PASS`, then the Shell prompt. A `REFUSE window` here means QEMU's own allocations sit in the window: record it, raise `-m`, rerun |
| T0c | as T0b, then `M5LOAD.EFI go` | `M5L-EBS ok`, `M5L-JUMP`, then `PROBE EL=2`, `X1`-`X3` zero, `MAGIC=ok`, `SCTLR_EL2` with M, C and I clear, DAIF all set, `PC` = `80080000`. If QEMU enters apps at EL1, the loader must refuse instead (`REFUSE el=1`); record "EL2 path not testable in QEMU" |
| T0d | `-m 1536M`, so RAM ends below the window's top | `M5L REFUSE window reason=gap`, then the Shell prompt |
| T0e | a scratch copy of the T0 build with one blob byte flipped | `M5L REFUSE crc src`, then the Shell prompt |
| T0f | `virtualization=off`; `go` | `M5L REFUSE el=1`, then the Shell prompt |

**T0 passes** when T0a-T0f end as stated, or when T0c is recorded as "EL1 in QEMU" and T0f passes. No QNX byte runs in QEMU. A T0 pass says nothing about cache coherency after the copy (§3.2 item 4): the gate's static check (§3.4 item 9) and R1 cover it.

### 6.2 P1: pre-flight

Run §8 in full, with the owner present (§8 item 16).
- Its board items are read-only.
- Its bench items (12-14) include the 3.3 V check and the TX wire onto J14 pin 3. They are the only control against F37 (§7.1), so the owner does them, or someone the owner has authorised does them with the owner present.

### 6.3 S1: staging and baseline (L4T; one ESP file and nothing else)

1. `PC$ sha256sum orin-native/uefi/out/M5LOAD.EFI` equals the value the gate printed.
2. `PC$ scp -i <orin-key> orin-native/uefi/out/M5LOAD.EFI <user>@<orin-ip>:~/M5LOAD.EFI`, then `L4T$ sha256sum ~/M5LOAD.EFI` must match.
3. **Backups** (plan:197-204):
   - `L4T$ mkdir -p ~/m5-backup && cp /boot/extlinux/extlinux.conf ~/m5-backup/ && sudo -n cp /boot/efi/EFI/BOOT/BOOTAA64.efi ~/m5-backup/`
   - `L4T$ sha256sum ~/m5-backup/* /boot/extlinux/extlinux.conf && sudo -n sha256sum /boot/efi/EFI/BOOT/BOOTAA64.efi`
   - `PC$ scp` both backups into `<rec>` and check their hashes on the PC.
4. **Snapshot S0.** Each output goes to `<rec>/s0-*.log`:
   - `L4T$ cat /proc/sys/kernel/random/boot_id; uptime`
   - `L4T$ sudo -n efibootmgr -v`
   - `L4T$ sudo -n sh -c 'cd /sys/firmware/efi/efivars && for f in *; do echo "$(sha256sum < "$f" | cut -c1-64) $f"; done'`
   - `L4T$ sudo -n find /boot/efi -type f -exec sha256sum {} +`
   - `L4T$ sudo -n nvbootctrl dump-slots-info`
   - `L4T$ cat /sys/class/dmi/id/bios_version`
   - `L4T$ sudo -n ls -l /sys/fs/pstore`
5. **Stage.** `L4T$ sudo -n cp ~/M5LOAD.EFI /boot/efi/M5LOAD.EFI && sync && sudo -n sha256sum /boot/efi/M5LOAD.EFI`. The hash must match step 1. Never into `EFI/BOOT/` or `EFI/UpdateCapsule/`, and never under a name ending `.nsh`.

### 6.4 P2: control cold boot (no key)

1. `PS>` stop any capture. Start `com3-term.ps1 -Out <rec>\p2-com3.log -KeyLog <rec>\p2-keys.log`. Forwarding stays disarmed throughout P2.
2. Confirm the adapter's TX is on J14 pin 3 (§8 items 12-13).
3. `L4T$ sudo -n poweroff`. Wait until COM3 has been silent for 30 s, then remove DC power and restore it.
4. Press nothing. **Expect, within 180 s of power-on,** the firmware banner and the hotkey lines, the countdown dots, then `L4TLauncher:` lines and the Linux boot.
5. `PC$` poll ssh until `boot_id` changes. The bound is 10 minutes after power-on.
6. **Snapshot S1,** as S0.
7. **Gate:** L4T booted with no key; `M5LOAD.EFI` is present with its hash; the ESP listing is S0 plus that file; `nvbootctrl` reads as in S0. Record `Δ(S0,S1)`.

### 6.5 P3: menu and Shell rehearsal, and `check` (T1)

1. New terminal logs `p3-com3.log` and `p3-keys.log`. `L4T$ sudo -n poweroff`, wait for 30 s of COM3 silence, cycle DC power.
2. When `ESC   to enter Setup.` appears: F12 to arm, then ESC once, before the dots run out (the configured `Timeout` is 30 s).
   - If `L4TLauncher:` lines follow instead, the key was missed. Let L4T boot fully, then repeat from step 1. Do not cut power while the firmware runs.
3. On the Setup front page, use the arrows to reach `Boot Manager` and press Enter. In Boot Manager, reach `UEFI Shell` and press Enter. If the front page lists `UEFI Shell` itself, select it there.
   - The menu names are VENDOR_CLAIM (the NVIDIA UEFI page); the log records the real text.
   - F11 at the prompt opens the Boot Manager Menu application instead, with the same options. It needs an F11 sequence the firmware decodes (UNKNOWN), so ESC is the primary key.
4. Wait for `Shell>` (bound 60 s). If the Shell prints a start-up script countdown, ignore it: no script exists. **The 120 s rule (§2 rule 5) runs from step 2 to here.**
5. Type each line and press Enter, reading the output before the next:
   1. `ver`
   2. `map -r`
   3. `ls fs0:\M5LOAD.EFI`, then `fs1:`, `fs2:` and so on until one lists the file. Several FAT filesystems can be mapped, for example the SD card's ESP and the NVMe install's (r/harvest-orin.md:74). Then run `ls fsM:\EFI\BOOT` on each other mapped FAT filesystem, and record which one holds a `BOOTAA64.efi`. That is F35's repair route, checked without booting it (R30).
   4. `fsN:`, the one that listed it.
   5. `M5LOAD.EFI check`. Expect T1 within 10 s.
   6. `memmap`. Optional and read-only: a cross-check of the loader's descriptors.
6. Type `reset` and press Enter. Press F12 at once to disarm.
7. Press nothing. L4T autoboots (bound 10 minutes). **Snapshot S2.**
8. **Gate:** T1 present; `Δ(S1,S2)` within `Δ(S0,S1)` as §5.2 item 4 defines; the ESP listing and `nvbootctrl` as in S1. On any `M5L REFUSE …`, stop: R1 does not run (D4, D11).

### 6.6 R1: `go` (T2; T3 attempted)

1. New terminal logs `r1-com3.log` and `r1-keys.log`. Power-on, ESC and Shell as P3 steps 1-4.
2. Type, each followed by Enter: `map -r`; `fsN:`; `M5LOAD.EFI check` (T1 again; stop here on any refusal); then `M5LOAD.EFI go`. The terminal disarms itself after that Enter. Confirm the console shows it disarmed.
3. **Watch.** Bounds count from the Enter after `go`:

| Expect | Bound |
|---|---|
| `M5L GO`, `M5L-EBS ok`, `M5L-JUMP` | 10 s |
| `T234-SHIM EL=2 …`, then `JUMP` | 10 s |
| `t234: WDT0 CR=…` (**T2**) | 20 s |
| `T234 M1b -P1: procnto up` | 60 s |
| `T234 M1b -P1: resetting so the log can be recovered` | 360 s |
| the firmware banner again | 60 s after the line above |
| L4T answers ssh with a new `boot_id` | 10 minutes after the reset line |

   These are wait bounds set for this procedure, not durations anyone measured. The 360 s bound covers the script's own bounds: a 60 s load, a 15 s ready wait and a 90 s collection (m1b-p1.build:32-38).

4. **If the output stops at any stage:** keep capturing until 10 minutes after `go`, in case a reset follows. Then read COM3 for the last token and cut power (§7, class P). The black box of that attempt is lost.
5. **During the firmware countdown after the image's reset, press nothing.**

### 6.7 After the return

1. Read-only, on the board:
   - `L4T$ sudo -n cat /sys/fs/pstore/console-ramoops-0` into `<rec>/r1-blackbox.log`. Look for `T234-SHIM EL=2` and the T3 lines.
   - `L4T$ sudo -n ls -l /sys/fs/pstore`, against S0. A new `dmesg-ramoops-*` record is a Linux Oops; record it.
   - `L4T$ cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason`. `MAINSWRST` is the image's own reset.
2. **Snapshot S3,** as S0.
3. **Judge §5.2 items 3-5.** If a name changes only in `Δ(S2,S3)`, take a warm control: `L4T$ sudo -n reboot`, wait for a new `boot_id`, take snapshot S4, and check whether `Δ(S3,S4)` changes the same name.
4. Copy the COM3 logs, key logs, snapshots and black box into `<rec>`. Write the run note (§6.10).

### 6.8 C: close the session

1. Stop `com3-term.ps1`.
2. Remove the adapter's TX wire from J14 pin 3. Leave RX on pin 4 and GND on pin 7, the wiring every M0-M4 autoboot ran with (r/serial-console-wiring.md:82).
3. **D10 (recommended):** `L4T$ sudo -n rm /boot/efi/M5LOAD.EFI && sync`. The ESP listing must then equal S0's. Delete nothing else.
4. Keep `~/m5-backup` and the PC copies until M5's record is written.

### 6.9 Order and gates

| Step | Pass means | Then | On fail |
|---|---|---|---|
| T0 | §6.1's cases end as stated | P1 | Fix the loader; rerun T0 |
| P1 | Every §8 item ticked | S1 | Stop and fix |
| S1 | All hashes match; S0 taken | P2 | Re-stage |
| P2 | Autoboot with no key; the file persists; `Δ(S0,S1)` recorded | P3 | §7 F1-F3, F6, F31 |
| P3 | T1; state as §6.5 step 8 | R1 | §7. A refusal ends the session (D4, D11) |
| R1 | T2; T3 recorded; §5.2 items 3-5 | C | §7 |
| C | TX wire off; the ESP equals S0 if D10 is taken | Record | — |

P2, P3 and R1 fit one session. A second session is needed only when a gate fails.

### 6.10 Run note (private)

Fields:
- the date, and the UTC time of each power-on;
- `bios_version` and the L4T release;
- the loader's sha256 and the embedded kimg's;
- the T0 record name and the gate output;
- the COM3 and key log names;
- which `fsN:` held the file;
- every `M5L` token;
- the last T2 and T3 tokens reached;
- `reset_reason`;
- the snapshot names and the three Δ sets;
- the recovery class of any failure (§7.2);
- deviations.

No durations. The note is kept like M3's record: private until the 4.6(i) consultation.

---

## 7. Recoverability and failure signatures

### 7.1 Guarantees

**By construction, M5 cannot:**
- write QSPI, the BCT, a partition table, NVRAM or a boot variable. The loader makes no call that could, and the procedure types none (rule 4);
- change which OS the board boots by default. `BootOrder`, `Boot####`, `L4TDefaultBootMode` and `extlinux.conf` are untouched, and the one new ESP file sits outside `EFI/BOOT`;
- run L4TLauncher during an attempt, so an attempt does not touch the rootfs retry counter (§3.1, option C);
- leave anything armed for the next boot. The firmware's watchdogs are Boot Services timers, and the loader arms nothing (C11).

**Residual, as in M0-M4:**
- after `go`, a hang with interrupts masked costs a power cycle and that attempt's black box;
- Linux can Oops in its own shutdown after long uptime (r/m2-runs.md:126-133). Before an attempt, that ends in a watchdog reset, not in a stuck board.

**Designed out: the only paths to a reflash, and the rule that prevents each**
- Bootloader slot failover: §2 rule 5 and §7.4.
- A capsule applied from the ESP: §7.4. The firmware processes an on-disk capsule and resets when its flag is set (NV `PlatformBm.c` ~1773-1800).
- A damaged `BOOTAA64.efi` or ESP: §6.3's backups and hash checks, and staging to the ESP root only.
- Secure Boot keys or a menu password: §7.4.
- Electrical damage to pin 3: §8 item 12, the 3.3 V check, done by or under the owner (§8 item 16).

### 7.2 Recovery classes

- **S, self-recovering:** the board resets by itself, or the Shell returns, and L4T comes back with no key.
- **M, manual without cutting power:** keys at a menu or in the Shell, or a command from L4T.
- **P, power cycle:** read COM3 first, then remove and restore DC power. The black box of that attempt is lost.
- **X, needs reflash:** designed out (§7.1). Each X row names the rule that prevents it, and the recovery to try before any reflash.
  - **Last-resort tooling, checked 2026-09-11 (orchestrator).**
    - **Matching BSP:** the board's QSPI firmware is 36.4.4 and its rootfs is on the SD card. The matching BSP, `downloads/nvidia/l4t-r36.4.4/Jetson_Linux_R36.4.4_aarch64.tbz2`, is on the PC; it is git-ignored, and a full `tar` read of it passes.
    - **Flashing host:** WSL2 `Ubuntu-24.04` with usbipd-win. Extract the BSP inside WSL's ext4, never on NTFS.
    - **Recovery path:** Force Recovery (the BootROM, which no software can overwrite), then usbipd attach, then a QSPI-only flash from WSL. That flash leaves the SD rootfs alone.
    - **Do not use** the R36.5.0 BSP that SDK Manager also left in WSL: it does not match the board's firmware.

### 7.3 Failure-signature table

Each row is keyed on the last distinctive COM3 line, or on a state check.

**Firmware, menus and Shell**

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F1 | No firmware text on COM3 within 180 s of power-on | The capture is not running, the RX wire is off, or the board has no power | S (L4T boots unseen) | Check the terminal and pin 4; retry from L4T |
| F2 | Hotkey lines, ESC sent, then `L4TLauncher:` lines | The key did not arrive: TX wire, logic level, or forwarding disarmed | S | Fix it; retry from a fully booted L4T |
| F3 | An autoboot stops in a menu with no key sent, or a menu shows stray characters | Noise or a held level on pin 3 (C15), or a stray key | M: choose `Continue` | Fix the wire or disarm forwarding before any attempt |
| F4 | No `Boot Manager` or no `UEFI Shell` entry | The firmware is not the one this design read (`Boot0007` gone) | M: `Continue` | Stop; check `bios_version`. M5-F cannot pass on this firmware |
| F5 | The firmware banner reappears while in the menus, with no key sent | A software watchdog fired before ReadyToBoot (C11) | S, but that boot was unvalidated | Let L4T boot. Shorten the menu time. No new attempt until one validated L4T boot |
| F6 | No `fsN:` lists `M5LOAD.EFI` | The ESP is not connected, or the staged file is gone | M: `connect -r`, `map -r`, retry; else `reset` | Re-check the ESP from L4T |
| F7 | The Shell reports a load or unsupported-image error for `M5LOAD.EFI` | The firmware rejects the PE | M: `reset` | Back to T0; compare the header with the L4T `Image` and L4TLauncher (C8) |
| F8 | The Shell reports a security violation or access denied at load | Secure Boot is now enforcing | M: `reset` | Stop. Never enrol keys. Record |
| F9 | Loader output stops, and no Shell prompt within 60 s | The loader or the firmware hung with Boot Services live | P (the Shell launch already validated the boot) | Record the last token; reproduce in T0 |
| F9b | An edk2 exception dump on COM3 | The loader faulted with Boot Services live | P (HYPOTHESIS: edk2 halts after the dump) | As F9 |

**Loader refusals.** Each returns to the Shell. Class M: type `reset`.

| # | Observable | Meaning | Next step |
|---|---|---|---|
| F10 | `M5L REFUSE el=1` | The firmware started the application at EL1 | Stop. M5-F fails; the plan's kill criterion (a) applies to this path too (plan:80) |
| F11 | `M5L REFUSE fdt` | No device-tree table (ACPI selected), or bad magic | Never change the DT/ACPI selection. Record; owner decision |
| F12 | `M5L REFUSE crc src` | The file is corrupted | Re-stage and re-hash |
| F13 | `M5L REFUSE alloc status=…`, with descriptors | The target is in use at Shell time | D4: record; revise the loader offline (§12 Q7) |
| F14 | `M5L REFUSE crc dst` | The copy to the target did not hold | Record; stop |
| F15 | `M5L REFUSE window reason=gap` or `reason=type at=…` | The window is not all free RAM | D4 |
| F16 | `M5L REFUSE zone type=…` | The black-box zone is runtime, MMIO or unusable memory | D4. No `go`, because the shim writes the zone unconditionally |

**After `go`**

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F17 | `M5L GO`, then nothing for 10 minutes | `ExitBootServices` never returned, or a fault came before the loader's vectors | P | Read COM3; cut power; rerun T0c |
| F18 | `M5L-EBS FAIL`, then the firmware banner | The exit failed four times; the loader reset | S | Record; revise the loader |
| F19 | `M5L-EXC ESR=… ELR=…`, then the banner | The loader faulted after the exit | S | Record; revise the loader; rerun T0c |
| F20 | `M5L-JUMP`, then nothing | The shim did not start, or the TCU went quiet | P, unless a reset follows | Wait the 10 minutes; cut power. If a reset came, read pstore |
| F21 | `T234-SHIM EL=…` then `EL!=2 abort`, and a reset | The EL changed after the loader checked it | S | Record |
| F22 | `BAD-LANDING pc=… expect=…`, and a reset | The loader branched to the wrong place | S | Record; revise the loader |
| F23 | Shim `EXC …`, and a reset | The shim faulted on firmware state | S | Record ESR and ELR; compare with M0's normalisation |
| F24 | `JUMP`, then nothing | startup stopped before its console | P, or S if the board vectors reset | Wait; cut power; read pstore if a reset came |

A stale instruction-cache line over the target (R33) has no signature of its own. It can look like F20, F22, F23 or F24, and T0 cannot reproduce it. Before revising the loader for any of those rows, re-run the gate's static sequence check (§3.4 item 9).

**Startup and QNX** (T2 is met from F25 on)

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F25 | `t234: WDT0 …`, then a crash message and a reset | A startup failure under firmware entry | S | T3 not reached. M1b §7 rows. A finding for the campaign |
| F26 | `hvtimer … STOP`, or a verdict other than `wired` | The EL2 virtual timer is not usable from firmware state | S (the stop policy crashes, then resets) | Record. A UEFI-versus-kexec difference for the campaign |
| F27 | T2 reached, then silence and no reset within 10 minutes | A hang with interrupts masked | P | Record; COM3 is the only record |
| F28 | `Starting next program`, then nothing | The kernel did not start | P | Record |
| F29 | `resetting so the log can be recovered`, and no banner within 60 s | The PSCI reset was not reached | P | Record |
| F30 | L4T is back, but pstore holds no `T234-SHIM` | The black box did not survive this path, or power was cut first | — | COM3 is the record; note it |

**State checks after the return**

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F31 | The ESP listing differs beyond `M5LOAD.EFI` | The firmware or L4T wrote the ESP | M | Restore from the backups from L4T; record. M5-F is not met until it is explained |
| F32 | A variable name is added or removed, or changes outside the control set (§5.2 item 4) | A variable was written | M; owner decision, since undoing it may itself need a variable write | Stop; record; the owner decides |
| F33 | `nvbootctrl` shows another current or active bootloader slot | Boot-chain failover | **X**, designed out by §2 rule 5 and §7.4 | Stop all board work. Follow NVIDIA's A/B documentation; reflash only as the last resort |
| F34 | L4T boots its recovery kernel | Rootfs boot failures accumulated | M, or X if it does not recover; designed out, because L4TLauncher never runs during an attempt | Record; follow NVIDIA's rootfs A/B documentation |
| F35 | L4T does not start: `BOOTAA64.efi` missing or corrupt | The ESP was damaged during staging | **X**, designed out by §6.3's hashes and backups | Boot the NVMe install (`Boot0008`) from Boot Manager, and restore the backup from it.<br>- `BootOrder` lists `0008` second (r/harvest-orin.md:75), so the firmware may reach it with no key (HYPOTHESIS).<br>- Checked in advance, read-only: the entry (§8 item 7) and its ESP's `BOOTAA64.efi` (§6.5 step 5).<br>- Not checked: that it boots (R30, D12).<br>If it does not boot, reflash |

**Wiring**

| # | Observable | Meaning | Class | Next step |
|---|---|---|---|---|
| F36 | No firmware output, and the board seems held, after wiring | A wire on pin 8 (`SYS_RESET*`) or pin 10 (`FORCE_RECOVERY*`) (r/serial-console-wiring.md:84) | P: remove the wire, then cycle power | Recount the pins |
| F37 | No output at all after wiring TX, surviving a power cycle | Electrical damage from a 5 V TX line | **X (hardware)**, designed out by §8 item 12 | Stop |

### 7.4 Never

- Enrol PK, KEK or db keys, or set a menu password.
- Write anything under `EFI/UpdateCapsule`, or create any `BOOTAA64.EFI` or `startup.nsh` on a filesystem the board can map.
- Run `bcfg`, `setvar`, `efibootmgr -c`, `-n`, `-o` or `-B`, or `mm` writes, from the Shell or from L4T.
- Run any fuse tool (`odmfuse.sh` or similar), or any NVIDIA flashing tool, as a step of M5. Fuses are irreversible, and a reflash is only the §7.2 last resort, never a planned step.
- Use "Boot From File", which leaves a `Boot####` behind (brief, UP `BmBoot.c` ~3000-3015).
- Change anything in Device Manager or Boot Maintenance Manager: boot mode, DT/ACPI selection, boot order, timeout.
- Cut power between power-on and the start of a boot option, in the menus or outside them. The only exception is rule 5's single cut for a firmware that has stopped, and this rule never allows a second cut (§2 rule 5).
- Power on with a USB storage device inserted (C9).
- Leave the TX wire on pin 3 while the terminal is stopped or the adapter is unplugged (C15).
- Put any wire on J14 pins 8, 10 or 12.
- Type into the terminal during a firmware countdown that should autoboot.

---

## 8. Pre-flight checklist (P1)

**PC**
1. T0 passed. Its record name goes in the run note.
2. `sha256sum orin-native/shim/out/m1b/m1b-p1.kimg` gives `cf0715ef…bd2f8e`.
3. The gate passed on the board build, and its printed sha256 is the value to stage.
4. **`com3-term.ps1` loopback,** with the adapter's TX jumpered to its own RX and nothing wired to the board:
   - armed, ESC logs `1b`, Up logs `1b 5b 41` and Enter logs `0d`, in both logs;
   - disarmed keys send nothing, and F12 is never sent;
   - a typed `M5LOAD.EFI go` line disarms forwarding after its Enter.
5. No other program holds COM3, and no other workflow is using the board.

**Board, read-only (`L4T$`)**
6. L4T uptime is under about 2 h; otherwise reboot it first (r/m2-runs.md:126-133; the threshold is HYPOTHESIS).
7. `sudo -n efibootmgr -v` shows `Boot0007* UEFI Shell`, `Boot0008` (the NVMe install, F35's repair route; r/harvest-orin.md:74-75), and `BootOrder` starting with `0001`. `Timeout` is recorded. If `Boot0008` is missing, F35 has no repair route short of a reflash: stop, and the owner decides whether M5 goes ahead.
8. `cat /sys/class/dmi/id/bios_version` reads `36.4.4-gcid-41062509` (r/harvest-orin.md:41). If it does not, stop: this design's source reads are for r36.4.4.
9. Secure Boot is disabled: the last byte of `/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c` is 0.
10. `sudo -n nvbootctrl dump-slots-info` is recorded: the current and active bootloader slot, and its status.
11. `od -An -tx1 /proc/device-tree/reserved-memory/ramoops_carveout/reg` still gives base `0x2_725F0000` and size `0x200000` (r/blackbox-verified.md:15-20). `df /boot/efi` shows room for the file several times over.

**Bench**
12. The adapter's logic level is 3.3 V: its jumper is set, and a meter on its TX pin reads no more than 3.4 V with the adapter on USB and wired to nothing.
13. Pins counted from J14 pin 1: RX on pin 4 and GND on pin 7, as before; TX onto pin 3 only after item 12 passes. Nothing on pins 8, 10 or 12. No VCC wire.
14. DC power can be removed and restored by hand, within reach (D5).

**Session**
15. M4-F is complete (plan:409).
16. The owner is present from P1 to C (§6), with at least an hour set aside. That is a planning bound, not a measurement. Bench items 12-14 are done by the owner, or by someone the owner has authorised while the owner is present.
17. `<rec>` exists, and its files will end in `.log`.

---

## 9. Risks: every HYPOTHESIS or UNKNOWN the design rests on, and what answers it

| # | Assumption | Class | Answered by |
|---|---|---|---|
| R1 | QEMU's edk2 loads the hand-written header | HYPOTHESIS (the L4T `Image`'s shape, C8) | T0b |
| R2 | This firmware loads it too, at an address outside the window | HYPOTHESIS (the UP rule; NV's fork not diffed) | P3, `self=` in `M5L start` |
| R3 | QEMU's edk2 enters applications at EL2 under `virtualization=on` | UNKNOWN | T0c |
| R4 | This firmware enters applications at EL2 | HYPOTHESIS (Linux starts at EL2 through it, r/harvest-orin.md:38, and an application cannot raise its own EL) | P3, `el=` |
| R5 | The device-tree table is published in the shipped DT mode | VERIFIED mechanism (r/research-uefi.md:159-186); presence at Shell time HYPOTHESIS | P3, `M5L fdt` |
| R6 | The window, target and zone are free enough at Shell time | HYPOTHESIS (Linux's map shows nothing reserved there, r/harvest-orin.md:52-53; where the firmware allocates was not checked) | P3 map lines |
| R7 | ESC, the arrows and typed text reach the firmware through pin 3 and the TCU | VENDOR_CLAIM and COMMUNITY (C13) | P3 |
| R8 | The Setup front page offers `Boot Manager` and `UEFI Shell` by those names | VENDOR_CLAIM (the NVIDIA UEFI page) | P3 |
| R9 | The Shell has `map`, `ls`, `ver`, `memmap`, `reset` and `connect` | VERIFIED at NV `main` (`imply SELECT_ALL_SHELL_COMMANDS`, r/research-uefi.md:202); r36.4.4 HYPOTHESIS | P3 |
| R10 | Menu time stays inside any pre-ReadyToBoot watchdog | UNKNOWN (`PcdBootWatchdogTime`) | P3; F5 |
| R11 | Launching `Boot0007` validates the boot chain | VERIFIED NV ReadyToBoot handler; ReadyToBoot for a normal boot option per UP `BmBoot.c` | `nvbootctrl` after each return |
| R12 | Slot failover needs repeated unvalidated boots | VENDOR_CLAIM (forum); threshold UNKNOWN | Never tested (rule 5) |
| R13 | The Shell path writes no variable | HYPOTHESIS (C10) | S2 against the control |
| R14 | L4T leaves an unknown file in the ESP root alone | HYPOTHESIS | P2 |
| R15 | The TX wire, connected and powered, does not stop autoboot | HYPOTHESIS (C15) | P2 |
| R16 | `ExitBootServices` succeeds within four attempts | HYPOTHESIS (the UEFI retry rule; NV's DeviceDiscovery work at exit) | R1, `M5L-EBS ok` |
| R17 | The trampoline is identity-mapped, so turning the MMU off does not fault | UP source (brief C4); design | T0c; R1, `M5L-JUMP` |
| R18 | The SPE keeps draining the TCU after the firmware exits | VERIFIED indirectly (L4T's `ttyTCU0` after its EFI stub, r/harvest-orin.md:55) | R1, the shim banner |
| R19 | The shim's normalisation works from firmware EL2 state | HYPOTHESIS (M2's secondaries entered from firmware EL2 state, plan:95) | R1, T2 |
| R20 | startup's `fdt_init` accepts the firmware tree | HYPOTHESIS | R1, T3 |
| R21 | The GIC re-initialises from the state the firmware left | HYPOTHESIS | R1, the VHE line and `verdict=wired` |
| R22 | INTID 28 is wired under firmware entry, as under kexec | HYPOTHESIS (hardware wiring, r/m1b-runs.md) | R1, T3 |
| R23 | `shutdown -S reboot` resets, and the board then autoboots L4T | VERIFIED under kexec (r/m1b-runs.md); HYPOTHESIS here | R1, the end |
| R24 | The black box survives the image's reset on this path | VERIFIED under kexec (plan K10); HYPOTHESIS here | §6.7 |
| R25 | The firmware still places the ramoops carveout where the shim writes | VERIFIED under L4T (r/blackbox-verified.md); HYPOTHESIS at Shell time | §8 item 11; P3 zone line |
| R26 | The R36.4.4 L4T binaries read for C8 equal the board's | HYPOTHESIS (same sizes) | Not needed: T0 and P3 test the loader itself |
| R27 | QEMU's edk2 publishes a device-tree table without `acpi=off` | UNKNOWN | T0b |
| R28 | `vvfat` accepts a Windows directory | HYPOTHESIS (the driver is present) | T0b |
| R29 | The adapter's logic is 3.3 V | UNKNOWN until measured | §8 item 12 |
| R30 | The NVMe install boots, as a route to repair the ESP | UNKNOWN (never booted, r/harvest-orin.md:74) | Its entry: §8 item 7. Its ESP's `BOOTAA64.efi`: §6.5 step 5. That it boots: only on F35, or in D12's optional session |
| R31 | Linux does not Oops in the `poweroff` before each cold boot | HYPOTHESIS (§8 item 6) | Each power-off |
| R32 | The operator follows the menus without a stray choice | — | The key logs; the snapshots; §7.4 |
| R33 | After §3.3 step 12, no stale instruction-cache line and no dirty data-cache line covers the target when the shim's first instruction is fetched | Design: the order kexec's relocator and edk2 use (VERIFIED upstream source). HYPOTHESIS that it is enough on this core | Presence and order: the gate's static check (§3.4 item 9). The effect: R1 only, the shim banner. Not T0 (§3.2 item 4) |

---

## 10. Must not be claimed from a pass

- **No timing.** Not a boot time, not a hand-off time, and not a comparison with kexec entry. The medians comparison is deferred (§5.4).
- **Not a cleaner state.** A pass does not show that the firmware leaves clocks, frequency, the GIC, timers or devices in better order than kexec. Plan §7 item 1's caveat (plan:663) stands; the campaign tests it.
- **Not DMA quiescence** (plan §8 #6).
- **Not repeatability** beyond the attempts taken.
- **Not option B or A'.** Nothing about `mkifsf_uefi`, `efi_entry_point` or a dual-format shim.
- **Not unattended.** An operator opened the Shell.
- **Not general.** One board, firmware `36.4.4-gcid-41062509`, one kimg.
- **Not a supported or certified boot,** and nothing about NVIDIA DRIVE OS, DRIVE AGX Orin, QNX OS for Safety or any ASIL property.
- **Not publishable** before the supervising professor is consulted (NC QDL v7 4.6(i)).

---

## 11. Owner decisions

| # | Decision | Options | Recommendation and reason |
|---|---|---|---|
| D1 | Entry mechanism | A; A'; B; C | **A.** No verified artefact changes, plan §3.5 holds, and most of its software risks close on the PC. Cache coherency is board-only (§3.2). Option B's header check can run as desk work in parallel (§12 Q8) without committing to B |
| D2 | Pass bar | T1; T2; T3 | **T2 required, T3 attempted in the same `go`.** This is the owner's scope, and T3 costs no extra step with this kimg |
| D3 | Medium and place | the ESP root; a new ESP directory; a USB stick | **The ESP root.** One new file and nothing else, as the plan's pass line says. A directory adds a second entry. A stick makes the firmware write `Boot####` and `BootOrder` (C9) |
| D4 | The map is not clean at Shell time | refuse and record, then revise offline; tolerate it at the board | **Refuse and record.** The descriptors decide the revision, for example a copy after the exit with an overlap guard, like the shim's labelled relocation fallback (plan §3.3 step 6). Tolerance is never widened at the board |
| D5 | Hang recovery | cutting DC power by hand; J14 pin 8; a switched socket | **By hand.** M5 is attended, and pin 8 sits next to the adapter's ground on pin 7 |
| D6 | Input to the freeze | kexec; UEFI through A or A'; native B | **Not decided in M5.** If T3 is reached, propose evaluating A' for v1. The trade-off is an attended launch, or a persistent `Boot####`, against inherited Linux state and a quiesce (§5.5) |
| D7 | PC terminal | `com3-term.ps1`, new and ours; install PuTTY | **`com3-term.ps1`.** No download, a byte-exact log in the M4 capture's format, and forwarding disarmed by default. Installing PuTTY is the owner's fallback if the script is not ready |
| D8 | TX wiring | TX on pin 3 for the session only; permanently | **For the session only.** Removing it restores the wiring every M0-M4 autoboot ran with (C15) |
| D9 | Images under UEFI entry in M5 | `m1b-p1` only; `m1b-p6` as well | **`m1b-p1` only.** `-P6`, M3 and M4 images under UEFI entry belong to the campaign (§5.4) |
| D10 | `M5LOAD.EFI` after M5 | remove it, returning the ESP to S0; keep it until the freeze | **Remove it** once the record is written. It carries QNX bytes, and the campaign will stage a v1 build anyway |
| D11 | After a refusal in P3 | fix and retry in the same session; a new session | **A new session.** Any loader change reruns T0 first |
| D12 | Proving F35's repair route before M5 | leave it unproven, with its entry and its `BOOTAA64.efi` checked read-only (§8 item 7, §6.5 step 5); boot `Boot0008` once, in its own attended session before P2 | **Leave it unproven for M5.** F35 is designed out by staging to the ESP root with hashes and backups. Booting `Boot0008` starts a second L4T install whose `extlinux.conf`, update services and rootfs state this design has not read. It boots through its own L4TLauncher, which touches rootfs-validation variables (§3.1 option C). If the owner wants the route proven, that session takes its own snapshot pair and is not part of M5 |

---

## 12. Open questions, ranked by cost

**Off the board**

| # | Question | Closes by |
|---|---|---|
| Q1 | Does QEMU's edk2 load the header, and does it enter applications at EL2? | T0b, T0c |
| Q2 | Does QEMU's edk2 need `acpi=off` before it publishes the device-tree table? | T0b |
| Q3 | Do NVIDIA's copies of `CoreLoadPeImage`, `EfiBootManagerRefreshAllBootOption`, `EfiBootManagerBoot` and `CoreExitBootServices` match upstream? | A source diff against NVIDIA's edk2 fork at the r36.4.4 tag |
| Q4 | What do `PcdBootManagerMenuFile`, `PcdBootMenuAppFile` and `PcdBootWatchdogTime` hold in this build, and does opening Setup validate the boot chain? | NV platform `.dsc` and Kconfig files |
| Q5 | Which terminal type does the firmware console use, and does it decode F11? | NV `.dsc`; otherwise P3 |
| Q6 | Does edk2's GICv3 driver quiesce the distributor at exit, and does NVIDIA's timer driver stop its timer? | A UP and NV source read |
| Q7 | If a refusal needs it: the design of a copy after the exit with an overlap guard, and its own T0 case | Design work, only after a refusal |
| Q8 | Option B's PE facts: ImageBase, entry RVA and `.reloc`, from one `mkifs` run of our own buildfile (plan §8 #12; plan:723-724) | A header read only |

**On the board**

| # | Question | Closes by |
|---|---|---|
| Q9 | The descriptor types over the window, the target and the zone at Shell time | P3 |
| Q10 | Whether typed input over pin 3 works, and the real menu labels | P3 |
| Q11 | Which variables change on every cold boot | P2, `Δ(S0,S1)` |
| Q12 | `HCR_EL2`, the rest of `SCTLR_EL2` and `CNTHP_CTL_EL2` as the firmware leaves them | R1, the shim banner |
| Q13 | WDT0's CR and SR after a firmware boot | R1, the T2 line |
| Q14 | Whether the black box survives the image's reset on this path | §6.7 |
| Q15 | Whether startup accepts the firmware tree, and whether INTID 28 is wired under firmware entry | R1, T3 |
| Q16 | `CTR_EL0` on this core: its cache line sizes, and whether its DIC and IDC bits make §3.3 step 12's cache operations unnecessary. The steps stay either way | P3, `ctr=` in `M5L start` |

---

## Appendix A. Stale text to correct later (list only; the orchestrator edits docs and other records)

**`docs/orin-native-port-plan.md`**
- **M5-F pass (plan:411):** "prints `Entering startup...` on the console". Under option A that string never prints; T2's tokens are the equivalent (C5).
- **M5-F prerequisites (plan:409):** "unknown #12 answered by a header read". Under A, #12 gates only option B.
- **M5-F pass (plan:412):** "no UEFI variable is written" needs §5.2 item 4's operational test (C10).
- **§3.5 Fallback B (plan:197-204):** describes option B as "also the optional M5 cross-check". M5 uses option A.
- **§8 #12 (plan:705):** "M5-F fails" if #12 goes the wrong way. Under A it does not.
- **§10, the M5 effort row (plan:756):** its dominant driver names the PE ImageBase and `mkifsf_uefi`. Under A the drivers are the loader, T0 and the board's map at Shell time.
- **Kill criterion (a) (plan:80-81):** "pivot to the UEFI Shell alternative (§3.4)". That alternative is §3.5.

**Other files**
- **`board/wdt.c:55`:** the WDT0 message names the kexec hand-over, and prints the same text under UEFI entry. Change it only together with a new startup pin.
- **`board/main.c:10-14` and `board/init_raminfo.c:12-14`:** kexec-only wording. Same rule.
- **`r/research-uefi.md:318` and `:325`:** "TXD - Pin 3" and "pins 3 (TX) / 4 (RX)" are the adapter-side view. The board transmits on pin 4 (r/serial-console-wiring.md:71-72).
- **The brief** (not tracked): this design's C6, C7, C8, C9 and C11 supersede its §3 steps 7-8, its header route, its reason for D3 and its watchdog note.

---

## 13. Review outcomes (revision 2)

Two reviews read revision 1, and both judged it sound with fixes: two major issues and three minor ones. Each row was checked before its disposition was chosen, against revision 1's own text and:
- Linux v5.15 `arch/arm64/kernel/relocate_kernel.S` and `arch/arm64/kernel/machine_kexec.c` (LX, fetched 2026-09-11);
- UP `MdeModulePkg/Core/Dxe/Image/Image.c`, `ArmPkg/Library/ArmCacheMaintenanceLib/ArmCacheMaintenanceLib.c` and `ArmPkg/Library/ArmLib/AArch64/AArch64Support.S` (fetched);
- https://docs.kernel.org/arch/arm64/booting.html and https://www.qemu.org/docs/master/devel/tcg.html (fetched);
- shim/t234-shim.S and shim/build-shim.sh (read only);
- r/harvest-orin.md rows 37a and 38.

No board was contacted, and no QNX-shipped binary was read.

**What did not change**
- Option A, the kimg and every pin.
- The tiers and the §5.2 pass criteria, apart from a new `ctr=` field in T1's first token.
- The T0 cases, the session ladder's steps and their order, every refusal rule and every wait bound in §6.

| # | Review | Severity | Issue | Disposition | Why |
|---|---|---|---|---|---|
| V1 | Review 1 | major | The §6 heading has the owner present from P1 to C, but §8 item 16 said P2 to C. P1 is not read-only: its bench items put the adapter's TX onto J14 pin 3 and check the 3.3 V level, and §7.1 names that check as the only control against F37. | **Applied as proposed.** §6's stricter bound stands. | **VERIFIED contradiction** between revision 1's §6 heading and its §8 item 16. The session ladder's P1 row says "TX wire added", and §7.1 names §8 item 12 as F37's only control.<br>§8 item 16 now reads P1 to C and says who does items 12-14: the owner, or someone the owner has authorised, with the owner present. §6.2, the ladder's P1 row and §7.1 now say the same. |
| V2 | Review 1 | minor | F35's step before a reflash is to boot the NVMe install (`Boot0008`), which R30 calls UNKNOWN, and no P1 item checks that the entry exists. | **Applied for the read-only checks. Booting `Boot0008` becomes owner decision D12**, recommended outside M5. | **The entry is VERIFIED** in the harvested `efibootmgr -v` (r/harvest-orin.md:74-75). §8 item 7 already runs that command, so the check costs nothing. P3 already walks the mapped FAT filesystems in the Shell, so listing the NVMe ESP's `BOOTAA64.efi` there is read-only too (§6.5 step 5).<br>**Not applied: booting it before M5.** That starts a second L4T install this design has not read, through its own L4TLauncher, which touches rootfs-validation variables (§3.1 option C). It falls outside §3.5's rules and is not cheap, so it is the owner's call.<br>**Found while checking:** `BootOrder` lists `0008` second, so the firmware may reach the NVMe install with no key (HYPOTHESIS). F35 now says so. |
| V3 | Review 1 | minor | The Never list banned cutting power "twice in a row" before a boot option had started, which allowed one cut, while R12 records the failover threshold as UNKNOWN. | **Applied: zero tolerance, with one exception for a firmware that has already stopped.** | **No usable source gives the threshold.** R12's only source is a forum thread, and a board read is out of scope, so "one" had no justification.<br>**The rule:** §2 rule 5 and §7.4 now forbid any cut between power-on and the start of a boot option.<br>**The exception is the one case with no alternative:** COM3 silent for 10 minutes, no menu or prompt showing, and no ssh. It allows one cut, then a hands-off boot to a validated state. If that boot also stops, the owner decides; the rule never allows a second cut. F3's menu case is excluded, because `Continue` leaves a menu.<br>**Nothing in the procedure relied on the old reading.** Every cut the procedure plans or the §7.3 table prescribes comes after a validated L4T boot or after the Shell launch: P2 step 3, P3 step 1, R1 step 4, F9 and F17-F29. F36's power cycle happens before MB1 runs (HYPOTHESIS), and rule 5 now says so. |
| V4 | Review 2 | major | After `ExitBootServices` the loader copied the kimg as data, ran `dc civac`, turned the MMU off and branched. It had no instruction-cache invalidation and no barrier between the clean and the MMU-off write, though the boot contract the design cites forbids stale instruction-cache entries. TCG cannot show this defect, so it would first appear at R1. | **Applied**, using the review's `ic iallu` option with `dsb sy` barriers (§3.3 step 12).<br>**Widened:** a static gate check, a `ctr=` field, R33, a §3.5 row and a §7.3 note. | **The issue holds.** The contract text is VERIFIED (booting.html, "Call the kernel image"), and `dc civac` acts on the data cache only.<br>**The review's premise about kexec is VERIFIED too, but it holds for the relocator, not for `machine_kexec.c` or `cpu-reset.S`.** v5.15's `relocate_kernel.S` runs `dc ivac` and `dsb sy` over each destination page, then `dsb nsh`, `ic iallu`, `dsb nsh` and `isb` before `br x17` (~45-80). `machine_kexec.c` only cleans the data cache over the segments (~161), and flushes the instruction cache over the relocator's own code (~65-72). So revision 1 broke §3.2 item 1's parity as well as the contract.<br>**edk2 applies the same idiom to every image it loads** (Image.c ~1066-1068; ArmCacheMaintenanceLib.c ~17-72).<br>**`dsb sy` builds and runs here:** the shim uses it (shim/t234-shim.S:129, :386).<br>**Why `ic iallu` and not per-line `ic ivau`:** it needs no target address and covers lines filled from anywhere, and kexec's relocator already runs it at EL2 on this board (NVIDIA's fork HYPOTHESIS).<br>**Why the widening:** T0 cannot test the step. So the gate checks its presence and order in our own ELF, over the trampoline only and never over the blob. `ctr=` records whether this core needs the step at all (Q16), and R33 and the §7.3 note record that a failure here has no signature of its own.<br>**Also noted (HYPOTHESIS):** UEFI entry may be more exposed than kexec, because edk2 runs identity-mapped. |
| V5 | Review 2 | minor | §3.2 item 4, "Its unknowns close on the PC", overstates what T0 closes: QEMU/TCG does not model instruction-cache staleness. | **Applied, and widened** to §0's "Why A" item 3, §3.1's option A row and D1, which made the same claim. | **VENDOR_CLAIM:** QEMU's TCG notes say translated code is invalidated when the guest writes a page that holds it, so a missing cache step cannot fail under TCG.<br>The claim now names what T0 does exercise: PE acceptance, the hand-over registers and EL, position independence and the map refusals. Cache coherency is board-only (R33); on the PC the gate's static check stands in for it. §6.1's T0 pass line now says the same. |

**Edited, by row**
- **V1:** the §0 session ladder (P1 row); §6.2; §7.1 (the pin-3 line); §8 item 16.
- **V2:** §6.5 step 5 (item 3); §7.3 F35; §8 item 7; §9 R30; §11 D12.
- **V3:** §2 rule 5 (its title and bullets) and the first row of the timeline; §7.4.
- **V4:** the `LX` path prefix; §0 "Chosen path"; §1 C4; §2 rule 3; §3.3 steps 1, 12 and 13; §3.4 gate item 9 (the old item 9 is now 10); §3.5 (a new row); §4.2 (two rows); §5.1 T1; §7.3 (a note after F24); §9 R17 and the new R33; §12 Q16.
- **V5:** §0 "Why A" item 3; §3.1 option A; §3.2 item 4; §6.1's T0 pass line; §11 D1.
- **Also:** the header.
