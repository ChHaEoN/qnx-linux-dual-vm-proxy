# M2 design: SMP on the Jetson Orin Nano (six Cortex-A78AE cores)

Phase 3b. Architect pass, revision 2, 2026-09-10. Revision 2 applies three adversarial reviews: library-correctness, firmware-hardware and evidence-recovery. Every defect was checked against source before it was accepted; §11 lists the outcomes. This is a read-and-reason design: nothing in it has been built or run.

**Path prefixes used below**
- `lib/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/lib/`
- `board/` = `E:/Project/qnx-linux-dual-vm-proxy/orin-native/startup/t234-orin-nano/`
- `repo/` = `E:/Project/qnx-linux-dual-vm-proxy/`
- `sdp/` = `C:/Users/<user>/qnx800/target/qnx/usr/include/`
- Reader reports: ap-entry, gicv3-percpu, timer-el1-percpu, board-audit, firmware-handoff, test-payload.

**Evidence classes:** VERIFIED (read in source or log), VENDOR_CLAIM, HYPOTHESIS, UNKNOWN.

**Licence status:** every log these runs produce is evaluation output under NC QDL v7 4.6(i). Keep it private until the supervising professor has been consulted. No QNX-shipped binary is disassembled anywhere in this design.

---

## 0. Summary

The library plus the board directory already contain the six-core happy path, and all six readers agree it is correct on inspection:
- the PSCI affinity table;
- a GICR frame limit of 16;
- each AP finding its own redistributor by affinity;
- system-register IPI values that reach cluster 1.

None of it has executed yet, because at `-P1` `init_smp()` skips its whole body (lib/init_smp.c:106).

**The risk is failure handling, not geometry.** Walking the AP timeline turns up four places where a plausible failure is a silent hang today. On this board a hang costs a power cycle, and a power cycle wipes the black box.

1. **AP faults before the handshake.** Every AP runs with `VBAR_EL1 = vbar_default`, a branch-to-self (lib/aarch64/smp_start.S:44-45), and `VBAR_EL2` is never set. The fault stays silent until an uncalibrated 2^32-iteration counter wraps (lib/init_smp.c:73-76). Only then does `CPU N start failure` print, and that text is identical to a refused CPU_ON (lib/common_arm/psci_smp.c:37-41, lib/ap_fail.c:27-31). All VERIFIED.
2. **AP dies after the handshake.** A death in `cpu_startnext`, `vstart` or `smp_spin` leaves CPU0 in `transfer_aps`, which has no bound and prints nothing (lib/init_smp.c:39-58). VERIFIED.
3. **Firmware state the shim never touched.** The shim clears MDCR_EL2, HSTR_EL2, ICH_HCR_EL2, the three timer controls and VBAR_EL2 on CPU0 only (repo/orin-native/shim/t234-shim.S:148-149, :291-304). `at_el2` touches none of them (lib/aarch64/_start_el1.S:125-197). What NVIDIA's T234 TF-A leaves there on CPU_ON is UNKNOWN (firmware-handoff).
4. **After `startnext`.** Once procnto owns the cores, there is no board-side bound at all.

**The design adds two things, without patching the library:**
- **Instrumentation and bounds for failure modes 1-3.** Every failure there prints a named line into the black box and ends in a PSCI warm reset. Revision 2 closes three gaps in that net, each found by review and verified:
  - the CPU_ON wait now polls the right polarity;
  - a GICR wake step now runs before the library's own 1000-read WAKER loop;
  - an AP that enters at EL1 now stops the run by name instead of continuing with unverifiable EL2 state.
- **A payload for the kernel phase (failure mode 4).** Exactly one process prints at a time, and every wait is bounded. A live COM3 capture is the evidence channel for the one class the board cannot bound: a kernel hang drains the TCU completely because nothing resets.

**Run ladder:**

| Step | Image | Purpose |
|---|---|---|
| R0 | `-P1` | Regression: the new board code on the path M1 verified |
| R1 | `-P2` | First AP |
| R2 | `-P4` | All of cluster 0 |
| R3 | `-P5` | First cluster-1 core; first read of GICR frames 4 and 5 |
| R4 | `-P6` | M2 pass run |
| R4b | `-P6` | Repeat |
| R5 | `-P6` + tracelogger | Tracelogger sanity check |

Each run's result gates the next.

---

## 1. Contradictions between the reports, and how they are resolved

| # | Contradiction | Resolution | Evidence |
|---|---|---|---|
| C1 | gicv3-percpu says frames 4/5 are first touched at `-P6`; ap-entry, board-audit and firmware-handoff say `-P5`. | **`-P5`.** At `-P5`, `start_aps` starts CPU index 4 (affinity 0x10200), whose walk reads frames 0-6. gicv3-percpu's own per-CPU list ("cpu4 frames 0-6") agrees; only its conclusion is wrong. | lib/init_smp.c:69; lib/aarch64/gic_v3.c:1343-1354; board/psci_cpu_id.c. VERIFIED |
| C2 | A test-payload failure mode derives the GICR limit from the CPU count (6), which would make frame 7 unreachable. | **The limit is 16.** The board calls the `_range` form with 0x200000. | board/aarch64/init_intrinfo.c:41-42; board/t234_startup.h:44-46; lib/aarch64/gic_v3.c:324-333. VERIFIED |
| C3 | The plan's GICR bases (0x0F440000…) differ from the library's `cpuN: Core GICR SGI address` values (0x0F450000…). | **Both are right.** The library prints frame base + 0x10000; the board line prints the frame base, so the plan's numbers are what gets compared. | lib/aarch64/gic_v3.c:1478-1482; M1 log:40. VERIFIED |
| C4 | Where to install EL1 vectors on APs: a `cpu_startup` override (firmware-handoff) or `board_smp_adjust_num` (ap-entry, timer, board-audit). | **`board_smp_adjust_num`.** It already exists and runs on every AP at the entry EL, after smp_start writes VBAR_EL1 and before `hypervisor_init` drops to EL1. main() already does the same VBAR_EL1-at-EL2 write for CPU0. | lib/aarch64/smp_start.S:44-45, :66, :73, :78; board/main.c:174; board/aarch64/vectors_el1.S:47-52. VERIFIED |
| C5 | Where to normalise AP EL2 state: in `board_smp_adjust_num` after `at_el2` (ap-entry, timer), or in an entry trampoline before `at_el2` (board-audit, firmware-handoff). | **Trampoline before `at_el2`, reusing the shim's exact write sequence.** This gives each AP the same ordering CPU0 has (shim writes, then `at_el2`). It captures firmware HCR_EL2 before `at_el2` overwrites it, installs VBAR_EL2 before any other EL2 code runs, and does any E2H flip with an ISB, which `at_el2` lacks. The write sequence is VERIFIED only from CPU0's Linux-dirty kexec state; the AP starting state comes from a CPU_OFF/CPU_ON cycle and has never been measured (see A3). | t234-shim.S:291-304; lib/aarch64/_start_el1.S:156 (no ISB); timer report |
| C6 | AP MDCR_EL2: 0, as the shim writes, or HPMN = PMCR_EL0.N (timer report). | **0 for M2**, matching CPU0's M1 state. HPMN belongs to M4's PMU calibration. | t234-shim.S:301. VERIFIED |
| C7 | test-payload runs six backgrounded printers at once, while board-audit shows `display_char_tcu` is unlocked. | **One printer at a time.** Busy processes write result files silently, and a single collector prints them. | board/aarch64/callout_debug_tcu.S:116-141; procnto serialisation UNKNOWN |
| C8 | test-payload classes the per-AP `Core GICR SGI address` print as HYPOTHESIS. | **VERIFIED.** It sits under `debug_flag > 1` in `gic_v3_gicc_init`, which each AP runs itself. | lib/aarch64/gic_v3.c:1480-1482 |
| C9 | Whether to use the script's internal `waitfor` as a timer. | **Do not use it.** The two QNX documents disagree on its argument order; bounded waits come from `smpcheck` instead. | nto_script.html vs mkifs.html (test-payload, VERIFIED conflict) |
| C10 | Plan claim K7: "a CPU that never starts ends in ap_fail(), not a silent hang". | **Narrowed.** It holds only up to the `cpu_starting` handshake, and only after an uncalibrated wait. The board bounds below replace it. | lib/init_smp.c:39-58, :73-76. VERIFIED |
| C11 | Where AP startup lines appear in the log. | After cpu0's GIC lines and `Loading IFS...done`, and before `Header size=`. | lib/init_system_private.c:163, :305; M1 log:40-43. VERIFIED |
| C12 | board-audit lists the `break_detect_tcu` patcher overrun as a pending fix. Two reviews found it already fixed. | **Already fixed.** Line 208 reads `CALLOUT_START(break_detect_tcu, 0, 0)` with a past-tense comment (commit 1f7a8ac), so M2 carries no change to that file. | board/aarch64/callout_debug_tcu.S:190-211; `git log` on that file. VERIFIED |

---

## 2. Design rules

1. **No library patch.** Everything is a board hook, a board override of a global (`smp_hook_rtn`, `gic_cpu_init`), or a board replacement of the CPU_ON entry point. The only library change remains the existing bounded `wait_for_rwp` in gic.h.
2. **One variable per run.** The startup binary and all startup options are identical across R0-R5 except `-P`. The script differs only in N-dependent lines, plus the trace lines in R5.
3. **Every startup-time wait has a real-time deadline.** Deadlines use CNTVCT_EL0 against `lsp.qtime.p->cycles_per_sec`: CPU0's CNTFRQ, 0x1dcd650, set by init_qtime before any AP starts (lib/aarch64/init_qtime_v8gt.c:55; shim bank). If that value is 0, the constant 0x1dcd650 is used. An AP's own CNTFRQ_EL0 is never trusted for a deadline, because its warm-boot value is UNKNOWN; it is only printed.
4. **APs print only while CPU0 is provably silent.** The window runs from CPU_ON until CPU0 sees `cpu_starting == 0`. CPU0 prints only on a timeout, which is a crash path anyway.
5. **Every fault ends in a warm reset, even when it cannot print.** A nesting guard and an MMU-on guard send the fault straight to PSCI SYSTEM_RESET using constants only, with no memory access.
6. **Fail closed on unverifiable state.** If an AP's EL2 state cannot be checked or normalised (the AP entered at EL1), the run stops by name. It does not continue on guesses.
7. **Make the run answer its own unknowns.** Firmware register values, entry EL, TYPER and WAKER contents, PSCI return codes and affinity state are all printed.

### AP timeline: fault and hang coverage, today vs. with this design

| Phase | CPU / EL / MMU | Today: fault | Today: hang | With design: fault | With design: hang |
|---|---|---|---|---|---|
| CPU0 issues CPU_ON (SMC) | CPU0 EL1, off | n/a | SMC not returning is unbounded | n/a | Still unbounded. The pre-SMC line is on COM3 and in the black box. |
| Trampoline, first instructions (daifset, SPSel, VBAR_EL2) | AP entry EL, off | silent (firmware VBAR_EL2) | 2^32 wrap, then "start failure" | Cannot fault in practice (writes to its own EL's registers) | CPU0's 15 s deadline prints stage 0x10 |
| Trampoline after the VBAR_EL2 install; `at_el2`; `board_smp_adjust_num` | AP EL2, off | silent | wrap | Board EL2 vectors print, then reset | 15 s deadline, stage 0x20/0x21/0x30 |
| AP entered at EL1 | AP EL1, off | silent | wrap | `adjust_num` prints the entry line, then crashes with `entered at EL1` | 15 s backstop, stage 0x30 |
| `hypervisor_init` drop, `cpu_startup`, `init_one_cpuinfo`, GIC init | AP EL1, off | silent (vbar_default) | wrap; the library WAKER loop can ASSERT | Board EL1 vectors print, then reset; wake runs first, bounded | 15 s deadline, stage 0x40-0x43 |
| syspage_available spin | AP EL1, off | n/a | n/a | n/a | covered by the next row |
| release → `cpu_startnext` / `vstart` / `smp_spin` | AP EL1, on | silent loop | **unbounded, no message** | MMU-on guard: direct PSCI reset; the last line names the released CPU | CPU0's 5 s deadline names the CPU |
| procnto | all | procnto's | unbounded | procnto's; EL2 traps hit the board EL2 vectors (A15) | **Unbounded, residual risk.** COM3 is the evidence. |

---

## 3. Ordered code changes

Apply them in this order; each builds on the previous ones. All files are in the repo; nothing in the BSP tree is edited.

### 3.1 `board/t234_startup.h`: shared definitions (C and asm)

- **Per-CPU diagnostic record** `struct t234_ap_diag`, 96 bytes, with fixed offsets `#define`d for the assembler.
  - `u32 stage`, `u32 entry_el`
  - `u64` fields: `mpidr`, `hcr_el2`, `sctlr_el2`, `mdcr_el2`, `hstr_el2`, `ich_hcr_el2`, `cnthp_ctl`, `cntp_ctl`, `cntv_ctl`, `cntfrq`, `waker_fw`
  - `extern struct t234_ap_diag t234_ap_diag[T234_NUM_CPU]` in `.data`
- **Stage constants:**
  - `0x10` CPU_ON issued (CPU0)
  - `0x20` trampoline entered (AP)
  - `0x21` trampoline normalised (AP, EL2 only)
  - `0x30` `board_smp_adjust_num`: EL1 vectors installed (AP)
  - `0x40` GIC wrapper entered; wake step (AP, EL1)
  - `0x41` library `gicc_init` called
  - `0x42` library returned; board checks
  - `0x43` `cpu N up` printed
  - `0x50` handshake seen (CPU0)
  - `0x60` released to smp_spin (CPU0)
  - `0x70` parked; CPU0 saw `pending == 0`
- `T234_AP_START_TIMEOUT_S 15`, `T234_AP_PARK_TIMEOUT_S 5`, `T234_GICR_WAKE_TIMEOUT_S 1`.
- `extern const unsigned t234_cpu_gicr_idx[6]` = {0,1,2,3,6,7}.
- `extern const _Uint64t t234_cpu_sgi1r[6]` = {0x1, 0x10001, 0x20001, 0x30001, 0x100020001, 0x100030001}.
- Inline helpers `t234_deadline(unsigned secs)` and `t234_expired(_Uint64t dl)`, per rule 3.
- Prototypes: `t234_ap_entry`, `t234_transfer_aps`, `t234_gicr_probe`, `t234_gic_cpu_init`, `t234_el2_fault`.

**Rationale:**
- The GICR indices come from the Linux dmesg frame bases (board facts) and the 0x20000 stride (lib/aarch64/gic_v3.c:324).
- The SGI1R values follow the library's own formula (gic_v3.c:1523-1542).
- cpu0's idx 0 and SGI1R 0x1 are VERIFIED at M1 log:41 and :102-103. The other five are HYPOTHESIS until R1-R4 print them.

### 3.2 NEW `board/aarch64/ap_entry.S`: `t234_ap_entry`, the CPU_ON entry point

It runs with the MMU off, at the entry EL, with no stack. Every address is formed with PC-relative `adr`, as smp_start.S does (:57, :63). In order:

1. `msr daifset, #0xf`.
2. `msr spsel, #1`. The stack written in step 4 must land in the banked SP that `_start_el2_or_el1` selects unconditionally at lib/aarch64/_start_el1.S:61. Upstream TF-A already enters with SP_ELx (`SPSR_64(mode, MODE_SP_ELX, ...)` in psci_get_ns_ep_info, VERIFIED upstream, firmware-handoff), so this is normally a no-op. T234's fork is UNKNOWN, and the write costs nothing.
3. `mrs CurrentEL`. If it is EL2: `adr x9, t234_el2_vectors; msr vbar_el2, x9; isb`.
4. `adr x9, t234_ap_stack_top; mov sp, x9`. This is a board 4 KiB `.data` stack, used only by the board EL2 fault handler until smp_start.S:57-58 replaces SP with the library stack. It is safe to share because APs start one at a time.
5. Index = `cpu_starting - 1` (`adr x10, cpu_starting`, as smp_start.S:63-65). If it is not in 1..5, branch to the constant PSCI SYSTEM_RESET path (0x84000009, lib/public/aarch64/psci.h:49).
6. Write `diag[idx]`:
   - `stage = 0x20`, `entry_el = EL`, `mpidr = MPIDR_EL1`;
   - if EL2, raw reads of HCR_EL2, SCTLR_EL2, MDCR_EL2, HSTR_EL2, ICH_HCR_EL2, CNTHP_CTL_EL2, CNTP_CTL_EL0, CNTV_CTL_EL0 and CNTFRQ_EL0. The CNTP/CNTV reads alias the EL2 timers when HCR_EL2.E2H=1; HCR_EL2 is recorded so the print can say which view was read.
7. If EL2, the shim's normalisation, verbatim (t234-shim.S:291-304):
   - `cntp_ctl_el0=0; cntv_ctl_el0=0; isb`;
   - `hcr_el2=0x80000000; isb`;
   - `cnthp_ctl_el2=0; cntp_ctl_el0=0; cntv_ctl_el0=0`;
   - `mdcr_el2=0; hstr_el2=0; ich_hcr_el2=0; isb`;
   - then `stage = 0x21`.
8. `b smp_start`. The library path continues unchanged: `_start_el2_or_el1` / `at_el2` → VBAR_EL1 = vbar_default → cache flush (no stack use, lib/aarch64/aarch64_cache_flush.S:34-74) → library stack → `board_smp_adjust_num` …

**Rationale:**
- Upstream TF-A with HCE=1 writes only SCTLR_EL2 (context_mgmt.c v2.6/v2.8/master, VERIFIED, firmware-handoff), so the other EL2 registers are UNKNOWN on an AP.
- ap-entry and board-audit both list the exact register set the shim gives CPU0 but APs never get.
- If the AP enters at EL1, steps 3 and 7 are skipped and the record says EL1. §3.5(c) then stops the run (rule 6).

### 3.3 `board/aarch64/vectors_el1.S`: guards and an EL2 table

**`t234_el1_common` (shared by CPU0 and APs):**
1. **MMU-on guard:** `mrs x9, sctlr_el1; tbnz x9, #0, t234_fault_reset`. Once `vstart` has turned the MMU on, the TTBR0 map covers only the startup image (lib/aarch64/aarch64_map.c:111-118 comment; lib/aarch64/vstart.S:68-74). TCU and black-box MMIO are probably unmapped (HYPOTHESIS A9), so a print would fault recursively.
2. **Nesting guard:** `adr x9, t234_fault_nest; ldr w10,[x9]; cbnz w10, t234_fault_reset; mov w10,#1; str w10,[x9]`.
3. As today: x0 = vector index, x1 = ESR_EL1, x2 = ELR_EL1, x3 = FAR_EL1, `b t234_el1_fault`. This is still a 4-argument call; MPIDR is read in C (§3.4), so the assembly-to-C ABI is unchanged.

**`t234_fault_reset`:**
- `movz w0,#0x0009; movk w0,#0x8400,lsl #16; mov x1,#0; mov x2,#0; mov x3,#0; smc #0; b .`
- It uses no memory. The SMC reaches EL3 from EL1 because `at_el2` leaves HCR_EL2.TSC=0 (lib/aarch64/_start_el1.S:148-156, VERIFIED), and reaches it from EL2 unconditionally.

**New `t234_el2_vectors`:**
- 16 slots, the same shape as `t234_el1_vectors`.
- The common stub applies the same nesting guard and a `SCTLR_EL2.M` guard. It then passes x0 = index, x1 = ESR_EL2, x2 = ELR_EL2, x3 = FAR_EL2, x4 = SPSR_EL2 and branches to `t234_el2_fault`.
- The shim's vectors cannot be reused, because its `exc_common` needs x21-x23 set up by `shim_body` (board-audit; t234-shim.S:102-138).

**Known limitation:** `t234_fault_nest` is one word shared by all CPUs. If a second CPU faults after the first, it resets without text; the first CPU's text is already in the black box. Accepted to keep the guard free of memory indexing.

### 3.4 `board/el1_fault.c`: widen and attribute

- The fault message becomes `crash("t234: EL1 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L\n", ...)`.
  - MPIDR comes from `aa64_sr_rd64(mpidr_el1)` inside the handler, which runs on the faulting CPU. The macro is defined at sdp/aarch64/inline.h:115 and used by the library at gic_v3.c:1339.
  - The prototype stays `t234_el1_fault(idx, esr, elr, far)`, so no caller changes. The only caller is vectors_el1.S:91 (grep, VERIFIED).
- Why `%L`: today's `%x` takes an `unsigned` in the library kprintf and prints 32 bits (lib/kprintf.c `case 'x'`; board/el1_fault.c:53-54, VERIFIED). A black-box FAR of 0x2_72770000, or any post-MMU virtual ELR, would print wrong.
- Add `t234_el2_fault(idx, esr, elr, far, spsr)`:
  - reads MPIDR the same way;
  - finds the diag index by matching `(mpidr & 0xff00ffffff)` against `t234_cpu_mpidr[]`;
  - prints `t234: EL2 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L SPSR=%L stage=%x`;
  - ends in `crash()` → `crash_done` → PSCI SYSTEM_RESET (board/crash_done.c:37-61).

### 3.5 `board/board_smp.c`: CPU_ON with a return code, a bounded start, the AP entry check, a bounded transfer

**(a) Tables** `t234_cpu_gicr_idx[]` and `t234_cpu_sgi1r[]`, per §3.1, plus `t234_ap_diag[]` in `.data`.

**(b) `board_smp_start(cpu, start)`.** It ignores `start` (smp_start) and uses `t234_ap_entry`. On entry `cpu_starting == cpu + 1`, set by `start_aps` just before this call (lib/init_smp.c:70-72). The AP clears it only after `init_one_cpuinfo` (lib/aarch64/smp_start.S:89-91). All VERIFIED.
1. `aff = psci_cpu_id(cpu)`; `ai = psci_affinity_info(aff, 0)` (lib/public/aarch64/psci.h, inline `psci_affinity_info`, VERIFIED).
2. If `debug_flag > 1`: `kprintf("t234: cpu %d CPU_ON aff=%L entry=%P affinity_info=%x\n")`. This is safe: the previous AP is in a silent loop (smp_start.S:96-99).
3. `diag[cpu].stage = 0x10`; `r = psci_cpu_on(aff, (uintptr_t)t234_ap_entry, 0)`.
4. If `r != PSCI_SUCCESS`: `crash("t234: cpu %d CPU_ON aff=%L entry=%P returned %x (%s)\n")`, naming the code: INVALID_PARAMETERS, DENIED, ALREADY_ON, ON_PENDING, INTERNAL_FAILURE, NOT_PRESENT, INVALID_ADDRESS (psci.h error codes). The library discards this code today (psci_smp.c:37-41, VERIFIED).
5. Wait for the AP to clear the handshake. This is the exact polarity; revision 1's prose was ambiguous here:

   ```c
   _Uint64t const dl = t234_deadline(T234_AP_START_TIMEOUT_S);
   while (cpu_starting != 0) {          /* AP writes 0 at smp_start.S:90 */
       if (t234_expired(dl)) {
           int32_t const ai2 = psci_affinity_info(aff, 0);
           crash("t234: cpu %d start timeout %d s: stage=%x affinity_info=%x\n",
                 cpu, T234_AP_START_TIMEOUT_S, t234_ap_diag[cpu].stage, ai2);
       }
   }
   t234_ap_diag[cpu].stage = 0x50;
   return 1;
   ```

   - Nothing prints while waiting.
   - Because this returns only once `cpu_starting == 0`, the library's counter loop runs one iteration and exits (init_smp.c:73-76, VERIFIED). The uncalibrated `ap_fail` path stays as an unreachable backstop.
- **Why 15 s:** the AP's `-vvv` output is about 1 KB, throttled by the TCU mailbox. A timeout that fires while the AP is still printing can be told apart by its stage (0x43 not reached) and by partial AP lines arriving just before it.
- `extern volatile int cpu_starting, syspage_available;` Both are non-static globals (init_smp.c:30-31, VERIFIED).

**(c) `board_smp_adjust_num(cpu)`.** It runs on the AP at its entry EL, after `_start_el2_or_el1`, on the library stack (smp_start.S:57-66).
1. `t234_install_el1_vectors()`, the same call main() makes for CPU0 (main.c:174).
2. `diag[cpu].stage = 0x30`.
3. If `debug_flag > 0`, print two lines from the record:
   - `t234: cpu %d entry EL%d MPIDR=%L HCR_EL2=%L SCTLR_EL2=%L CNTFRQ=%x`
   - `t234: cpu %d fw MDCR_EL2=%L HSTR_EL2=%L ICH_HCR_EL2=%L CNTHP_CTL=%x CNTP_CTL=%x CNTV_CTL=%x -> normalised`

   The EL2 fields read 0 when the entry EL is 1.
4. **Fail closed on EL1 entry.** If `diag[cpu].entry_el != 2`: `crash("t234: cpu %d entered at EL%d: EL2 trap and vector state cannot be read or normalised from EL1, stopping\n")`.
   - This is not optional: at EL1, `_start_el2_or_el1` returns without writes (lib/aarch64/_start_el1.S:64-66), and `arch_hypervisor_validate_flags` and `arch_hypervisor_init` under -Q disable do nothing at EL1 (lib/aarch64/hypervisor.c:38-44, :80-87). All VERIFIED.
   - Whatever HCR_EL2 routing or trap bits and VBAR_EL2 firmware left would therefore persist unseen.
   - Linux on this board reports all CPUs started at EL2, so EL1 entry for a QNX-issued CPU_ON would itself be a finding.
   - The crash comes from a secondary (A10). If that reset does not happen, CPU0's 15 s deadline reports stage 0x30.
   - Downgrading this to "log and continue" requires reading NVIDIA's T234 TF-A first, plus a rebuild.
5. Return `cpu`.

Printing here is safe because CPU0 is in (b)'s silent wait.

**(d) `t234_transfer_aps(void)`.** A copy of lib `transfer_aps` (init_smp.c:39-58), using the same `SYSPAGE_ENTRY(smp)->pending` expression so its semantics are identical.
1. **Ordering precheck, before any release.** For every i in 1..num_cpu-1: if `diag[i].stage != 0x50`, `crash("t234: transfer hook ran before cpu %d handshake (stage=%x): smp_hook_rtn installed too early\n")`. A misplaced hook would otherwise surface as a misleading `released but pending` timeout (evidence-recovery review).
2. For each i: `*pending = 1`; `mem_barrier()`; `diag[i].stage = 0x60`; an optional `-vv` line `t234: cpu %d -> smp_spin`; `syspage_available = i`.
3. Wait with the same explicit polarity as (b): `while (*pending != 0) { if expired(5 s) crash("t234: cpu %d released but smp.pending still set after %d s (cpu_startnext/vstart/smp_spin) affinity_info=%x\n"); }`. Then `stage = 0x70`.
4. After the loop: `kprintf("t234: all %d cpus parked in smp_spin\n")`.

CPU0 is still in startup with the MMU off and physical console access. APs print nothing in this phase (callout_smp_spin.S:36-76, VERIFIED).

### 3.6 `board/main.c`: install the bounded transfer

**Ordering constraint:** the line below must run after `init_system_private()` has returned and before `main` returns.
- `smp_hook_rtn()` is called twice.
  - The first call is inside `init_system_private()` at lib/init_system_private.c:305 ("Start any AP's"). There `smp_hook_rtn` is still `start_aps` (set by `init_smp`, lib/init_smp.c:118), which starts every AP and, at its end, sets `smp_hook_rtn = transfer_aps` (init_smp.c:83).
  - The second call is from `_main` after `main` returns (lib/_main.c:151-156).
- The override has to sit between the two. Installed any earlier (for example just after `init_smp()`), the first call would run `t234_transfer_aps` instead of `start_aps`, and no AP would ever get CPU_ON. The §3.5(d) precheck turns that mistake into a named crash.

Directly after `init_system_private();` in board/main.c, with a comment stating the constraint:

```c
if (lsp.syspage.p->num_cpu > 1) smp_hook_rtn = t234_transfer_aps;
```

`smp_hook_rtn` is a public global (lib/public/startup.h:624). At `-P1` `num_cpu == 1`, so the hook stays `hook_dummy` and R0 keeps M1's path. All VERIFIED.

### 3.7 `board/aarch64/init_intrinfo.c`: CPU0 GICR probe and the per-CPU wrapper

**(a) `t234_gicr_probe()`, called before `gic_v3_initialize()`.** It runs on CPU0 with board EL1 vectors live since main.c:174.
- With `debug_flag > 1`, print `t234: fdt cpus=%d num_cpu=%d cntvct=%L cps=%L`. This exercises the CNTVCT read at EL1 in R0, before any deadline depends on it.
- Let `F = t234_cpu_gicr_idx[num_cpu-1]`. For frames `f = 0..F`:
  - **Populated frames (0, 1, 2, 3, 6, 7):** read `+0x8` (TYPER low), `+0xC` (TYPER high: the same 32-bit access the library walk uses, gic_v3.c:1345) and `+0x14` (WAKER).
  - **Unpopulated frames 4 and 5:** read `+0x8` and `+0xC` only. That keeps those two frames inside the access set upstream Linux already performs on this board (a 64-bit GICR_TYPER read at +0x8). Linux never reads their WAKER, and neither does the QNX library.
  - Print `t234: gicr frame %d @%x TYPER_hi=%x TYPER_lo=%x WAKER=%x`, with `WAKER=-` for 4 and 5.
- **Checks:**
  - If a frame belongs to a CPU k that will be started and its TYPER_hi differs from `t234_cpu_mpidr[k]`: `crash("t234: gicr frame %d affinity %x != cpu%d %x\n")`.
  - If frame 4 or 5 reads TYPER_hi equal to 0x10200 or 0x10300: crash, because the walk would bind the wrong frame.
- **Frames read per image.** The probe reads the same frames the image's own library walk will read, only earlier, and on the one CPU whose faults are reported:

  | Image | Frames read |
  |---|---|
  | `-P1` | 0 |
  | `-P2` | 0-1 |
  | `-P4` | 0-3 |
  | `-P5` | 0-6 (first read of frames 4 and 5) |
  | `-P6` | 0-7 |

- **What it settles:**
  - From R1 on: whether the 32-bit TYPER-high read returns the affinity at all. M1 could not tell, because cpu0's affinity 0 also matches a register that reads as zero (gicv3-percpu, VERIFIED).
  - At R3: unknown #10.
  - The WAKER state firmware leaves on offlined cores, seen before CPU_ON.
- **What it does not settle:** an asynchronous SError from frames 4/5 would stay pending under DAIF and would not be reported here (residual A5).

**(b) Per-CPU wrapper, installed after `gic_v3_initialize()`:** `t234_lib_gic_cpu_init = gic_cpu_init; gic_cpu_init = t234_gic_cpu_init;`.
- `gic_cpu_init` is a global pointer (lib/public/aarch64/cpu_startup.h:181, lib/aarch64/gic.c:27). `gic_v3_initialize` sets it (gic_v3.c:1096); its only caller is `init_one_cpuinfo` (init_cpuinfo.c:306-308).
- The wrapper runs on CPU0 (main.c init_cpuinfo) and on each AP itself, at EL1 with the MMU off, before `cpu_starting` is cleared (smp_start.S:83-90).

`t234_gic_cpu_init(cpu)` does, in order:

1. **`stage = 0x40`. Wake step, before the library.** This replaces revision 1's post-library-only check. The library's own WAKER code (gic_v3.c:1358-1370, VERIFIED) runs right after the walk:
   - if ProcessorSleep (bit 1) is set, it prints `** CPU N PE is not awake`;
   - it polls at most 1000 reads for ChildrenAsleep (bit 2) to become 1, under `ASSERT(--loop > 0)`;
   - it clears ProcessorSleep and never waits for ChildrenAsleep to return to 0.

   Upstream Linux `gic_enable_redist` and TF-A `mark_core_awake` both clear ProcessorSleep first and then wait for ChildrenAsleep = 0. The board does the same, first:
   - `aff32 = (mpidr & 0xFFFFFF) | ((mpidr >> 8) & 0xFF000000)`, the library's formula (gic_v3.c:1340).
   - `tframe = T234_GICR_BASE + (t234_cpu_gicr_idx[cpu] << 17)`.
   - If `in32(tframe + 0xC) != aff32`: print `t234: cpu %d table frame %d TYPER_hi=%x != aff %x, wake step skipped` and continue. The library walk and step 4's check then decide.
   - Otherwise: `w = in32(tframe + 0x14)`; `diag[cpu].waker_fw = w`.
   - If `w & 0x2`: `out32(tframe + 0x14, w & ~0x2)`, then wait `while (in32(tframe+0x14) & 0x4)` against a `T234_GICR_WAKE_TIMEOUT_S` deadline. On expiry: `crash("t234: cpu %d redistributor wake timeout WAKER=%x fw=%x\n")`.
   - When this step has run, the library's WAKER branch sees ProcessorSleep = 0 and is skipped. Its `:1367` ASSERT stays reachable only when the wake step was skipped.
   - Whether GICR_WAKER is writable from Non-secure EL1 with GICD_CTLR.DS=0 is UNKNOWN (A22). If it is RAZ/WI, this step reads 0 and does nothing.
2. `stage = 0x41`; call the library function; `stage = 0x42`.
3. `idx = lsp.cpu.aarch64_gicr_map.p->gicr_idx[cpu] & 0xffff` (gic_v3.c:1356); `frame = T234_GICR_BASE + (idx << 17)`; `sgi1r = lsp.cpu.aarch64_gic_map.p->gic_cpu[cpu]`.
4. **Post-library WAKER check.** If `in32(frame+0x14) & 0x6`, wait against a 1 s deadline. On expiry: `crash("t234: cpu %d redistributor not awake after gicc_init WAKER=%x\n")`.
5. **Active state.** `act = in32(frame + 0x10000 + 0x300)` (ISACTIVER0). If it is non-zero, write it to ICACTIVER0 at +0x380 and re-read. Linux ran split EOI/Deactivate, and the library clears neither ISACTIVER nor AP1Rn (gicv3-percpu, board-audit; plan §5 promised ICACTIVER clearing that was never added).
6. **Check.** All of the following must hold, else `crash("t234: cpu %d MISMATCH MPIDR=%L/%L idx=%d/%d SGI1R=%L/%L ISENABLER0=%x\n")`:
   - `(mpidr & 0xff00ffffff) == t234_cpu_mpidr[cpu]`
   - `idx == t234_cpu_gicr_idx[cpu]`
   - `sgi1r == t234_cpu_sgi1r[cpu]`
   - `in32(frame+0x10100) & 1` (ISENABLER0, SGI0 enabled)
7. **Print the pass-criterion line:** `t234: cpu %d up MPIDR=%L GICR=%x idx=%d SGI1R=%L WAKER=%x fw=%x ISENABLER0=%x ISACTIVER0=%x(cleared|0) AP1R0=%x`, with `AP1R0 = aa64_sr_rd32(S3_0_C12_C9_0)`. Then `stage = 0x43`.

On cpu 0 this also performs firmware-handoff's recommended check that the kexec boot CPU is affinity 0x0, before any CPU_ON.

### 3.8 `startup/build-board.sh`: symbol gate

- In the list at :110-113, replace `psci_smp_start` (no longer referenced, so possibly not linked) with `t234_ap_entry t234_transfer_aps t234_el2_vectors t234_gic_cpu_init t234_gicr_probe`.
- Keep the `psci_cpu_id` defined-once check (:122-124).
- Add a `crash_done` defined-once check. board/crash_done.c's header says the build script counts its definitions, but the gate at :100-135 counts only `psci_cpu_id` (VERIFIED).

### 3.9 NEW `orin-native/tools/smpcheck.c` and `tools/Makefile`

- Makefile: `TOOLS := tcu-cat stamp smpcheck`, with the same CC/CFLAGS.
- The full specification is in §5. It uses only SDK-declared interfaces that test-payload VERIFIED in headers:
  - `ThreadCtl` `_NTO_TCTL_RUNMASK` and `_RUNMASK_GET_AND_SET_INHERIT` (sys/neutrino.h:432-438)
  - `SchedGetCpuNum` (:865)
  - `ClockCycles` (aarch64/neutrino.h:67-83)
  - `SYSPAGE_ENTRY` / `SYSPAGE_CPU_ENTRY` gic_map and gicr_map (aarch64/syspage.h:79-101)
  - the asinfo entry `gicr`

### 3.10 NEW `startup/m2.build.in` and `startup/make-m2-images.sh`

- The template is m1.build's bootstrap line with `-P@P@`, the script in §4, and m1.build's file list plus `/proc/boot/smpcheck=smpcheck`. The trace variant adds four trace files.
- The script:
  1. Generates `m2-p1/p2/p4/p5/p6/p6t.build`.
  2. Runs `mkifs -r <bsp>/.../t234-orin-nano/aarch64/le -r orin-native/tools m2-pN.build m2-pN.ifs`.
  3. Runs `dumpifs` on each image and fails unless the bootstrap line contains exactly `-P<N>`, because `-P` is baked into the IFS (board-audit, VERIFIED).
  4. Runs `build-shim.sh jump m2-pN.ifs`, then copies `shim/out/t234-qnx.kimg` to `shim/out/m2-pN.kimg`. build-shim writes one fixed name.
  5. Prints `sha256sum` for every .kimg.

### 3.11 Docs, after the runs (not blocking)

In `docs/orin-native-port-plan.md`:
- Narrow K7 (C10).
- Add `-P5` to the M2 ladder.
- Note that the library prints SGI base = frame + 0x10000 (C3).
- Replace "an un-kicked soak resets at ~2 min" (plan :331-332), and board/wdt.c:49-51, which says the same wrong thing: WDT0 does not fire after kexec.
- Update unknown #10 with the R3 result.
- Record the measured AP firmware EL2 values against K3, with the caveat that their provenance (CPU_OFF/CPU_ON) differs from CPU0's (kexec).
- Record the QNX library's WAKER sequence against the Linux and TF-A order (§3.7(b) step 1).

### Deliberately not changed, and why

- **`callout_debug_tcu.S`.** The `break_detect_tcu` patcher overrun is already fixed (commit 1f7a8ac, line 208, C12). Whether any on-board run has used that fix is not recorded here; R0 exercises it either way.
- **No spinlock in `display_char_tcu`.** Whether procnto serialises debug callouts across CPUs is UNKNOWN. A lock needs rw storage and patcher changes in kernel-time code, which is a new failure surface. M2 uses a single-printer payload instead, and a black box that disagrees with COM3 is the detector. If M2 shows garbling, the lock becomes a pre-M3 task.
- **No black-box cap raise.** It stays 64 KiB. R0/R1 measure real sizes, and gate G1 (§6) checks them before R4.
- **No change to `init_qtime`, `QTIME_FLAG_GLOBAL_CLOCKCYCLES`, HPMN or `-Q`.** Each is a separate variable.
- **No library `gic_v3.c` patch.** The walk and its WAKER branch stay as they are; the board wake step runs before them and the wrapper observes the result.
- **No change to the `-P1` send_ipi write in init_intrinfo.c.** At `-P1` it is still M1's verified behaviour; images at `-P2` and up take the valid path (board-audit).

---

## 4. Images

Startup binary: one build of `startup-t234-orin-nano` with §3.1-§3.8, used for every image.

Startup options for all images are identical to M1 except `-P`: `startup-t234-orin-nano -vvv -P<N> -Q disable -m992M -Wkeep -Dtcu`. `-Wkeep` has no effect after kexec, because WDT0 does not fire; it stays only for parity with M1.

| Image | -P | Purpose |
|---|---|---|
| m2-p1 | 1 | R0 regression: new board code (probe, cpu 0 wrapper and wake step, fault stubs) on M1's single-CPU path; smpcheck self-test on one CPU |
| m2-p2 | 2 | First AP (0x100); first real TYPER-high affinity read; firmware EL2 state and entry EL; CPU_ON return code; CNTVCT deadlines |
| m2-p4 | 4 | All of cluster 0. Recorded as **degraded** if it becomes the final state |
| m2-p5 | 5 | First cluster-1 CPU_ON (0x10200); first read of frames 4/5 (unknown #10) |
| m2-p6 | 6 | M2 pass run |
| m2-p6t | 6 | m2-p6 plus a tracelogger capture during the load |

Nothing else is worth a run up front. A `-vv` variant is only a failure-branch tool (§7).

### Script: m2-p6 (other images substitute N and keep only busy lines 0..N-1)

```
[+script] .script = {
    display_msg "T234 M2 -P6: procnto up"
    procmgr_symlink ../../proc/boot/ldqnx-64.so.2 /usr/lib/ldqnx-64.so.2
    procmgr_symlink /proc/boot/ksh /bin/sh
    devc-pty
    pidin info
    smpcheck -i -n 6
    smpcheck -b 60 -C 0 -o /dev/shmem/m2c0 &
    smpcheck -b 60 -C 1 -o /dev/shmem/m2c1 &
    smpcheck -b 60 -C 2 -o /dev/shmem/m2c2 &
    smpcheck -b 60 -C 3 -o /dev/shmem/m2c3 &
    smpcheck -b 60 -C 4 -o /dev/shmem/m2c4 &
    smpcheck -b 60 -C 5 -o /dev/shmem/m2c5 &
    smpcheck -R 6 -p /dev/shmem/m2c -T 15
    pidin -p smpcheck -f abNli
    smpcheck -c 6 -p /dev/shmem/m2c -T 90
    pidin info
    display_msg "T234 M2 -P6: resetting so the log can be recovered"
    smpcheck -z 3
    shutdown -S reboot
}
```

**m2-p6t** is the same, with these lines inserted between `smpcheck -R ...` and `pidin -p ...`:
```
    tracelogger -s 2 -f /dev/shmem/m2.kev &
    smpcheck -z 6
```
and these after `smpcheck -c ...`:
```
    traceprinter -f /dev/shmem/m2.kev -o /dev/shmem/m2.txt
    smpcheck -k /dev/shmem/m2.txt -n 6
```
Its file list adds `tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1`. Their DT_NEEDED lists are UNKNOWN, since reading them would mean inspecting a QNX binary; a missing library shows as `Unable to start ... (83)`.

**Why the script is shaped this way:**
- Only one printer at a time; busy processes print nothing (C7).
- No foreground command can block forever; every wait is `smpcheck` with a `-T` bound.
- tracelogger and traceprinter write only to `/dev/shmem`; only counts reach the console, which protects the black-box budget.
- No `tcu-cat`: its output bypasses the black box (M1 blackbox log:9-11).
- No internal `waitfor` (C9).
- The last command is `shutdown -S reboot` (m1.build:89-94).
- The trace lives in a separate image, so a hang caused by tracelogger cannot cost the core M2 evidence.

---

## 5. `smpcheck` specification

Style follows `tcu-cat.c`: Apache header, getopt, `fflush` after every line, output to stdout only, which reaches the kernel console and the black box. Exit codes: 0 PASS, 1 FAIL, 2 usage, 3 PASS-DEGRADED (expected CPUs < 6). The script ignores exit codes; the printed lines are the record.

- **`-i -n N` (census).**
  - Prints `cps` from qtime (FAIL if 0), `num_cpu` (FAIL if != N), `SYSPAGE_ENTRY_SIZE(smp)` (0 means no SMP section) and `sysconf(_SC_NPROCESSORS_ONLN)` for information.
  - For each CPU i, prints `SMPCHECK cpu i hwid= aff= gic= gicr_idx= gicr= name= ok|MISMATCH`, bounds-checking every section size:
    - `hwid` is cpuinfo[i].smp_hwcoreid, the MPIDR written on CPU i itself (init_cpuinfo.c:161-183);
    - `gicr` is the start of the asinfo `gicr` entry + (idx << 17);
    - `gic` is gic_map[i].
  - Compares against the same tables as the board.
  - Ends with `SMPCHECK CENSUS PASS|FAIL`. This re-proves, from the kernel's syspage copy, what startup printed.
- **`-b S -C c -o PREFIX` (silent busy worker, one process per CPU).**
  1. Set own priority to 9 (SCHED_RR), below the script and collector at 10.
  2. `ThreadCtl(_NTO_TCTL_RUNMASK, (void*)(uintptr_t)(1ull<<c))`; on error, record errno.
  3. Read back with GET_AND_SET_INHERIT (zero masks); only bit c may be set.
  4. Timer check: time `clock_nanosleep(CLOCK_MONOTONIC, 100 ms)` with `ClockCycles`. Pass if it returns within [90 ms, 2 s] and `SchedGetCpuNum() == c` afterwards. QNX 8.0 documents that software timers fire on the core that armed them (VENDOR_CLAIM), so this is the per-CPU timer PPI liveness check.
  5. Write `PREFIX.ready` (one newline-terminated line).
  6. Busy-loop for S s of ClockCycles. Every 65,536 iterations: `samples++`; `misplaced++` if `SchedGetCpuNum() != c`; `backwards++` if ClockCycles went down.
  7. Repeat the timer check.
  8. Write `PREFIX.done`: `cpu= secs= samples= misplaced= backwards= iters= rate= timer0_ms= timer1_ms= pin=ok|err`.
- **`-R N -p PREFIX -T S`.** Waits up to S s for `PREFIX0..N-1.ready`, then prints each line, or `SMPCHECK ready cpu=i MISSING`. Always exits.
- **`-c N -p PREFIX -T S`.** Waits up to S s for the `.done` files, prints each, then `SMPCHECK RESULT PASS|PASS-DEGRADED|FAIL cpus=k/6 secs=S reasons=...`.
  - PASS requires, for each i < N: a done file, pin ok, both timer checks ok, samples > 0, misplaced == 0, backwards == 0, secs ≥ S.
  - Iteration rates are informational only; DVFS is uncontrolled.
- **`-k FILE -n N`.** Counts traceprinter lines per `CPU:NN` (the default format per traceprinter's use text, VERIFIED test-payload). Prints counts plus one sample line per CPU, cut to 80 characters. PASS if every CPU < N has events.
- **`-z S`.** Sleeps S s to let the TCU drain before a reset.

---

## 6. Run procedure

**Build (PC).**
1. Run `orin-native/startup/build-board.sh` and confirm the symbol gate passes.
2. `make -C orin-native/tools`.
3. Run `orin-native/startup/make-m2-images.sh`. It produces `m2-p{1,2,4,5,6,6t}.kimg`, their sha256 and a `dumpifs` bootstrap-line check.
4. Record startup, IFS and kimg sha256 in the run note.

**Each run (one image).**
1. **PC:** start the COM3 capture (115200 8N1, J14 debug header) into `com3-<image>-<utc>.log` **before** kexec, and leave it running until L4T is back.
2. **PC:** `scp shim/out/<image>.kimg <user>@<orin-ip>:~/` with key `~/.ssh/<orin-key>`. The IP is DHCP; scan the /24 if it has moved.
3. **Board:** `sha256sum ~/<image>.kimg` must equal the PC value. Then `cat /proc/sys/kernel/random/boot_id` and record it.
4. **Board:** `sudo -n kexec -s -l ~/<image>.kimg && sudo -n systemctl kexec`.
5. **PC:** poll ssh until it answers **and** `boot_id` differs from step 3. Give up 10 minutes after kexec.
6. **Board:** `sudo cat /sys/fs/pstore/console-ramoops-0 > ~/<image>-blackbox.log` and record its size with `ls -l`. Copy it and the COM3 log to `results/orin-native-port/<utc>/` (private, NC QDL 4.6(i)).
7. **No return within the bound:** read COM3 first; it holds everything up to a hang, because the TCU drains fully when nothing resets. Then a human power cycle; record that the black box was lost.
8. Write the run note: sha256s, bootstrap line, both boot_ids, the last 30 lines of each log, black-box size, and a verdict against §8.

**Order and gates:**

| Run | Image | Pass means | Then | On fail |
|---|---|---|---|---|
| R0 | m2-p1 | M1's milestone lines, plus: `t234: fdt cpus=6 num_cpu=1 cntvct=…`, the frame 0 probe line, `t234: cpu 0 up MPIDR=0000000081000000 GICR=0f440000 idx=0 SGI1R=0000000000000001 …`, census PASS, busy cpu0 ok, `SMPCHECK RESULT PASS-DEGRADED cpus=1/6`, L4T returns | R1 | Board-code regression; fix it before any SMP run, using the fault line or last line |
| R1 | m2-p2 | §8 for N=2, including `cpu 1 entry EL2` | R2 | §7, row by row. No higher -P until -P2 passes |
| R2 | m2-p4 | §8 for N=4 | R3 | §7; the failing CPU index and stage name the step |
| R3 | m2-p5 | §8 for N=5, plus probe frames 4/5 read without fault and without 0x10200/0x10300, and cpu 4 up at idx 6 | G1 | If it fails on cpu4 or frames 4/5 and cannot be fixed at board level: record M2 **degraded (-P4)** citing R2, and open a plan-4.1(iii) item |
| **Gate G1** | — | Desk check: `size(R0) + 5×(size(R1) − size(R0))` + about 2 KB must be < 60,000 bytes (cap 65,520). If not, rebuild p6/p6t at `-vv` and record that deviation | — | — |
| R4 | m2-p6 | **M2 pass** (§8) | R4b | §7; the degraded record is R2 |
| R4b | m2-p6 | A repeat pass, ruling out a first-run fluke; not a reliability claim | R5 | Report as intermittent, with both logs |
| R5 | m2-p6t | §8 plus tracelogger: no `(83)`, tracelogger and traceprinter return, `smpcheck -k` shows events on all 6 CPUs, L4T returns | M2 closed | Core M2 stays passed; the tracelogger item stays open with its signature |

---

## 7. Failure-signature table

Each row is keyed on the last distinctive line in the black box or on COM3.

| Observable | Meaning | Next step |
|---|---|---|
| R0 differs from M1 before `Loading IFS` (probe crash on frame 0, `cpu 0 MISMATCH`, `t234: EL1 …`, wake timeout on cpu 0) | The new board code broke CPU0's path | Fix before any SMP run; resolve ELR with addr2line on the keeplinked startup |
| `t234: cpu 0 MISMATCH MPIDR=…` | kexec entered from a CPU other than affinity 0, or the table is wrong | Compare the shim bank MPIDR (0x81000000); make sure Linux kexecs from CPU0 (kernel/reboot.c reboot_cpu) |
| `t234: gicr frame F affinity X != cpuK Y` (CPU0) | Geometry is not what Linux reported, or the 32-bit TYPER-high read does not return the affinity | Stop. Compare TYPER_lo; re-derive the geometry before any AP depends on it |
| `t234: EL1 data abort on MPIDR=0000000081000000 … FAR=000000000f4c000c` (or 0f4e000c) at R3 | Unknown #10 is false: frames 4/5 fault on a 32-bit read | Record `-P4` degraded; plan-4.1(iii) walk patch that skips frames 4/5 |
| `t234: cpu N CPU_ON … returned fffffffe (INVALID_PARAMETERS)` | Firmware rejects the affinity | Check the table against the DT; bits 31:24 must be 0 (DEN0022E 5.1.4) |
| `… returned fffffffc (ALREADY_ON)` / `fffffffb (ON_PENDING)` | Core never offlined, or still warm-booting | Compare the pre-line `affinity_info`; check Linux's kexec CPU_OFF; retry once |
| `… returned fffffff7 (INVALID_ADDRESS)` | Entry PA outside T234's non-secure window, or bit 0 set | Note `entry=`. Needs T234 TF-A source (atf_src.tbz2, user permission) or an image base move |
| `… returned fffffffd (DENIED)` / `fffffff9 (NOT_PRESENT)` / `fffffffa (INTERNAL_FAILURE)`, cluster 1 only | Firmware policy or power on cluster 1 | Record `-P4` degraded; T234 TF-A research |
| `t234: cpu N start timeout 15 s: stage=00000010 affinity_info=00000000` | CPU_ON accepted and the core reported ON, but `t234_ap_entry` never ran | Entry EL, endianness or address translation at hand-off; T234 TF-A read needed. Stage 0x10 rules out print throttling |
| `… stage=00000010 affinity_info=00000001 or 00000002` | Firmware never finished powering the core | Retry once; firmware-side research |
| `… stage=00000020` (EL2 entry) | Hang, no fault, in the trampoline's normalisation writes | Bisect those writes one by one; report the register |
| `… stage=00000021` | Hang between trampoline and `adjust_num`: `at_el2`, VBAR_EL1 write, cache flush | Compare the SCTLR_EL2 M/C/I branch (_start_el1.S:132-139); rebuild with an extra stage write before `b smp_start` |
| `t234: EL2 … on MPIDR=… EC=18 …` (from an AP) | A sysreg access trapped at EL2 (to EL3) in the trampoline or `at_el2` | addr2line the ELR; drop or reorder that write |
| `t234: cpu N entered at EL1: EL2 trap and vector state cannot be read or normalised from EL1, stopping` | Firmware entered a QNX-issued CPU_ON at EL1, unlike Linux's | Record the entry lines; read T234 TF-A (psci_get_ns_ep_info, SCR_EL3.HCE per context) before allowing EL1 entry |
| Entry lines printed, then `t234: EL1 … on MPIDR=0x8100xxxx …` | AP EL1 fault in `cpu_startup`, `init_one_cpuinfo` or GIC init | Decode EC/ELR. EC 0x18 on ICC_* suggests trap state; EC 0x25 with a GICR FAR suggests a frame problem |
| `…gic_v3.c:1352 -- ASSERT(gicr_index < gicr_index_limit) failed!` | Walk matched no frame in 16 | Compare the AP's `cpuN: MPIDR=` line with the probe TYPER_hi lines |
| `t234: cpu N table frame F TYPER_hi=… != aff …, wake step skipped` | The table frame does not hold this CPU's affinity | Expect a :1352 ASSERT or MISMATCH next; compare with the probe |
| `t234: cpu N redistributor wake timeout WAKER=… fw=…` | ProcessorSleep cleared by the board, but ChildrenAsleep never returned to 0 within 1 s | Firmware or GIC power state; compare `fw=` with the probe WAKER; check GICR power (GICR_PWRR unhandled everywhere) |
| `** CPU N PE is not awake` then `…gic_v3.c:1367 -- ASSERT(--loop > 0) failed!` | The library WAKER loop ran (only possible if the wake step was skipped or WAKER is RAZ/WI to NS) and ChildrenAsleep never read 1 in 1000 reads | Find why the wake step was skipped (previous line); A22 |
| `t234: cpu N redistributor not awake after gicc_init WAKER=…` | Post-library check: sleep bits still set | Same as the wake-timeout row |
| `gic: RWP never cleared at 000000000f4?0000 (bit 00000008)` | That AP's redistributor is not decoding or not awake | Check the probe WAKER and the `fw=` value |
| `t234: cpu N MISMATCH … idx=…/… SGI1R=…/…` | Wrong frame bound, wrong affinity, wrong IPI value, or SGI0 not enabled | Stop; a later kernel hang is likely. Compare the probe and syspage maps |
| `t234: cpu N start timeout … stage=00000040` / `41` / `42` | AP hung without faulting: 0x40 in the wake step's MMIO, 0x41 inside library gicc_init (walk/WAKER/RWP), 0x42 in board checks | 0x41: rerun with R1 probe data; 0x40/0x42: inspect wrapper MMIO for that frame |
| `t234: cpu N start timeout … stage=00000043` with AP `-vvv` lines still arriving | 15 s budget too short over a slow TCU; not a core failure | Raise `T234_AP_START_TIMEOUT_S` or run `-vv`; record TCU throughput |
| `t234: transfer hook ran before cpu N handshake (stage=…)` | `smp_hook_rtn` override installed before `init_system_private()`'s first hook call | Move the line after `init_system_private()` (§3.6) |
| `t234: cpu N released but smp.pending still set after 5 s` | AP died or hung in `cpu_startnext` / `vstart` / `smp_spin` | Check `ttbr1[cpu]`/TCR/MAIR against CPU0's working setup; suspect firmware SCTLR_EL1 residue |
| Last line `t234: cpu N -> smp_spin`, then a reset with no crash text | AP took an MMU-on fault; the guard reset it directly | Same as above; the direct reset is by design |
| `t234: all N cpus parked in smp_spin` + `Starting next program`, then COM3 silent with no reset (power cycle) | procnto hang bringing APs online (IPIs, timer PPI, per-CPU kernel init) | COM3's last kernel lines; rerun one `-P` lower; suspect gic_map, ICACTIVER or firmware PPI config; no board bound exists here |
| `SMPCHECK CENSUS FAIL` with a MISMATCH row | Kernel syspage copy differs from startup's print | Compare with the startup lines and the print_syspage maps |
| `SMPCHECK ready cpu=i MISSING` | CPU i never ran its pinned process, or the pin failed | Check `pidin -p smpcheck -f abNli`; expect a kernel stall; rerun one `-P` lower |
| `timer0_ms` missing or > 2000 for cpu i | Timer PPI 27 not firing on CPU i | Check that CPU's ISENABLER0/ISACTIVER0 in its `cpu N up` line; firmware ICFGR; procnto unmask |
| `misplaced>0` / `backwards>0` | Runmask not honoured, bad per-CPU index, or clock regression | pidin %l/%i; CNTVOFF (at_el2 sets 0) |
| `SMPCHECK RESULT FAIL …` then a clean reset | A criterion failed, fully recorded | Fix per the listed reasons |
| Black box garbled or overwritten while COM3 is intact | Concurrent `display_char_tcu` cursor race | board-audit's callout spinlock, before M3 |
| `console-ramoops-0` about 65,520 bytes and cut off | 64 KiB black-box cap reached | G1 was wrong; run `-vv` or raise the cap |
| `Unable to start "tracelogger" (83)` (R5) | Missing shared library | Add it; rebuild p6t |
| `smpcheck -k` zero events for a CPU (R5) | Capture window or format | Longer `-s`; if there are no `CPU:` lines at all, parse the .kev with `_NTO_TRACE_GETCPU` |
| Two crash texts, the AP's first, then CPU0's `start timeout` | PSCI SYSTEM_RESET from a secondary did not reset | Record as a firmware fact; keep the CPU0 backstop |
| COM3 ends at `t234: cpu N CPU_ON …`, no return | CPU0's CPU_ON SMC never returned (EL3 hang) | Firmware-side; unboundable from the board |

---

## 8. M2 pass criteria (the plan's pass list, made observable)

For `-P6`, all of the following in one run (R4); R4b repeats them.

1. `t234: cpu N up …` for N = 0..5, with no MISMATCH, and:
   - MPIDR & 0xff00ffffff = {0, 0x100, 0x200, 0x300, 0x10200, 0x10300}
   - GICR = {0f440000, 0f460000, 0f480000, 0f4a0000, 0f500000, 0f520000}
   - idx = {0, 1, 2, 3, 6, 7}
   - SGI1R = {1, 10001, 20001, 30001, 100020001, 100030001}

   The library's `cpuN: Core GICR SGI address` lines read base + 0x10000, as corroboration.
2. A `t234: cpu N entry EL2 …` / `fw …` pair for N = 1..5. **Entry EL must be 2.** EL1 entry is a fail by construction (§3.5(c)). The register values are recorded data, not criteria.
3. `t234: all 6 cpus parked in smp_spin`, then `System page at phys:` and `Starting next program`.
4. The syspage dump's gic_map and gicr_map sections have six rows with the values above.
5. `pidin info` shows six Processor lines.
6. `SMPCHECK CENSUS PASS` and `SMPCHECK RESULT PASS cpus=6/6 secs=60`: six pinned 60 s busy processes with no fault, no misplacement and live per-CPU timers.
7. `shutdown -S reboot` returns L4T: a new boot_id, and pstore recovered.
8. None of: `t234: EL1` / `EL2` fault, ASSERT, `CPU N start failure`, `start timeout`, `released but`, `entered at EL1`, `wake timeout`, `not awake`, `transfer hook ran`, `PE is not awake`.

`ap_fail()` remains the library backstop, but with §3.5 the named `t234:` crash lines are the M2 fail signal.

`-P4` passing while `-P5`/`-P6` fail is recorded as **M2 degraded (4 cores)**, never as M2.

---

## 9. Risks: every HYPOTHESIS or UNKNOWN the design rests on, and the run that answers it

| # | Assumption | Class | Answered by / handled how |
|---|---|---|---|
| A1 | A CPU_ON issued by QNX from NS-EL1 enters the AP at EL2 | HYPOTHESIS: PSCI Table 14 and upstream TF-A `psci_get_ns_ep_info` VERIFIED; Linux-issued ones did; T234 fork not read | R1 `entry EL` line. EL1 entry stops the run by name (§3.5(c)) |
| A2 | Firmware EL2 register values on an AP | UNKNOWN | R1 `fw` line; normalised regardless |
| A3 | The shim's write sequence (VERIFIED from CPU0's Linux-dirty kexec state) is safe from an AP's CPU_OFF/CPU_ON starting state, which has never been measured. Whether T234 CPU_OFF power-gates, and whether firmware restores EL2 context, is UNKNOWN | HYPOTHESIS | R1 raw pre-normalisation dump is the first real test; a trap prints via EL2 vectors; a hang leaves stage 0x20 |
| A4 | The 32-bit read of GICR_TYPER+0xC returns the affinity | HYPOTHESIS (untested in M1) | R1 probe frame 1, on CPU0 |
| A5 | Frames 4/5 readable at +0x8/+0xC without an abort | HYPOTHESIS (Linux 64-bit walk evidence; NVIDIA irq-gic-v3.c not read) | R3 probe; an async SError would surface only at kernel time (residual) |
| A6 | AP redistributors awake with no leftover active state after CPU_ON | UNKNOWN | Probe WAKER, wake step (`fw=`), wrapper readbacks; bounded wake and clear |
| A7 | CNTVCT_EL0 readable at EL1 on CPU0 and on APs, without traps | HYPOTHESIS: CNTHCTL_EL2=3 via at_el2 VERIFIED; ECV absent per MMFR0 reading | R0 probe `cntvct=` on CPU0; R1 AP deadlines (a trap prints via EL1 vectors) |
| A8 | AP and CPU0 see each other's MMU-off stores (`diag`, `cpu_starting`) | VERIFIED: the library relies on the same pattern | R1 stage progression |
| A9 | Identity map after `vstart` excludes console MMIO, so the MMU-on guard is needed | HYPOTHESIS | Guard is conservative either way |
| A10 | PSCI SYSTEM_RESET from a secondary resets the board | UNKNOWN | CPU0 backstop; observed if any AP crash happens |
| A11 | 15 s / 5 s / 1 s deadlines are ample | HYPOTHESIS (TCU drain rate unmeasured) | Stage 0x43 timeout signature separates "budget too short" from a real failure |
| A12 | T234 accepts the startup's physical entry address | UNKNOWN (T194 window 0x80000000.. VERIFIED upstream) | R1 CPU_ON return code |
| A13 | Cluster 1 has no extra firmware policy or order constraint | UNKNOWN | R3 |
| A14 | procnto brings APs online, unmasks PPI 27 per CPU, and serialises or tolerates debug callouts | UNKNOWN (binary) | R1+ timer checks; black box vs COM3; **no board bound: residual hang risk, COM3 is the evidence** |
| A15 | Board EL2 vectors and startup memory stay valid for kernel-time EL2 traps on APs | UNKNOWN | Only matters if such a trap occurs |
| A16 | `shutdown -S reboot` completes with a process stuck READY on a dead core | UNKNOWN | If it blocks, COM3 already has the FAIL verdict |
| A17 | tracelogger/traceprinter library set; the script runs as root | UNKNOWN / HYPOTHESIS | R5, `(83)` signature |
| A18 | Black-box budget < 64 KiB at `-P6 -vvv` | HYPOTHESIS | Gate G1 from R0/R1 sizes |
| A19 | The already-landed `break_detect_tcu` null-patcher fix (1f7a8ac) holds on the board | VERIFIED in source; on-board use not recorded here | R0 |
| A20 | Timer check proves per-CPU timer PPI delivery | VENDOR_CLAIM (QNX 8.0 "timers fire on the core that armed them") | Plausible, not proof; stated as such |
| A21 | kexec DTB carries six cpu nodes | HYPOTHESIS (the fallback to 6 covers only 0 or >6) | R0 `fdt cpus=` print |
| A22 | GICR_WAKER is readable and writable from Non-secure EL1 on this GIC (GICD_CTLR.DS unknown) | UNKNOWN (GIC architecture text not read) | If RAZ/WI, the wake step and library branch are no-ops reading 0; `fw=` shows it |
| A23 | The AP enters with SP_ELx selected | VERIFIED upstream TF-A; T234 UNKNOWN | Irrelevant after the trampoline's `msr spsel, #1` |
| A24 | One shared fault-nesting word is enough | Design choice | A second CPU's fault after a first resets without text; the first CPU's text is kept |

---

## 10. Must not be claimed from a pass

- Not isolation, not a hypervisor, no ASIL property: this is `-Q disable`, EL1 only.
- Nothing about `-Q enable` with `-P>1` (M1b/M3). Entry EL and EL2 state were observed only for CPU_ON issued from EL1 under `-Q disable`.
- Not reliability or a soak result: one 60 s load per run, n=2 at `-P6`.
- Not that ClockCycles is synchronised across CPUs. Only per-CPU monotonicity and pinning were checked; CNTVOFF=0 comes from source, not measurement.
- Not that IPIs were verified directly: scheduling and pinning imply them, and no per-IPI count exists.
- Not per-CPU performance parity: rates are informational and DVFS is uncontrolled.
- Not that the kernel-time console is SMP-safe.
- Not that tracelogger content is correct: only that capture and print completed with events on every CPU.
- Not that unknown #10 is closed beyond this SKU, this firmware (L4T R36.4.7) and this access width.
- Not that T234 TF-A matches upstream in general: only the register values, entry EL and return codes observed.
- Not that the AP EL2 normalisation was verified from a known starting state: the raw AP values were first measured in these runs.
- Not that the QNX library's WAKER sequence is wrong on this hardware: the board wake step runs first, so the library branch was not exercised.
- Not that the startup library runs unmodified. The board overrides the CPU_ON entry point, `transfer_aps` (via `smp_hook_rtn`) and `gic_cpu_init` (with a wake step before it), and the gic.h RWP patch remains.
- Not that the kexec round trip is watchdog-recoverable.
- `-P4` alone is not M2; it is M2 degraded.
- Not publishable before the supervising professor is consulted (NC QDL v7 4.6(i)).

---

## 11. Review outcomes (revision 2)

| Lens | Defect | Outcome | Applied where |
|---|---|---|---|
| library-correctness | CPU_ON wait polarity (`cpu_starting != 0` as success) | Accepted | §3.5(b) explicit loop; same pattern in §3.5(d) |
| library-correctness | Board SP written before `msr SPSel,#1` | Partly: SPSel write added; the claim that `aarch64_cache_flush` uses the stack rejected (it does not, aarch64_cache_flush.S:34-74) | §3.2 step 2, A23 |
| library-correctness | callout_debug_tcu.S change already landed | Accepted | C12; change dropped; A19 |
| firmware-hardware | Library WAKER loop runs before the board check | Partly: board wake step moved ahead of the library call; "blocker, can never terminate" and "missing from table" rejected | §3.7(b) step 1, §7 rows, A22 |
| firmware-hardware | EL1 entry accepted as data | Accepted: fail closed | §3.5(c) step 4, §8 criterion 2, rule 6 |
| firmware-hardware | A3 overstates the evidence | Partly: reworded; the "raw POR value" assertion rejected as unverified | C5, A3 |
| evidence-recovery | MPIDR argument never passed from asm | Accepted, fixed by reading MPIDR in C (no ABI change) | §3.3, §3.4 |
| evidence-recovery | callout_debug_tcu.S already fixed | Accepted (duplicate) | C12 |
| evidence-recovery | Hook-ordering constraint unstated | Partly: citation, constraint and a runtime precheck added; the mechanism was already described in revision 1 | §3.6, §3.5(d) step 1 |
| architect self-check | Probe read WAKER on unpopulated frames 4/5, beyond Linux's and the library's access | Accepted | §3.7(a) |
| architect self-check | Wrapper WAKER bound was a read count, against rule 3 | Accepted | §3.7(b) steps 1 and 4 |
| architect self-check | AP deadlines would trust an UNKNOWN AP CNTFRQ_EL0 | Accepted: syspage cps used | Rule 3, §3.1 helpers |
