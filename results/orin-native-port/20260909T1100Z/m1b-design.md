# M1b design: the QNX host at EL2 with VHE on the Jetson Orin Nano (`-Q enable,el2-host`)

Phase 3b. Architect pass, revision 2, 2026-09-10: revision 1 with the review outcomes in §12 applied. This is a read-and-reason design: nothing in it has been built or run. It follows the structure and failure-handling rules of [m2-design.md](m2-design.md), whose ladder passed with no failure signature ([m2-runs.md](m2-runs.md)).

**Path prefixes used below**
- `lib/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/lib/` (Apache-2.0; the tree carries the repo's `patches/gic-bounded-rwp.patch`)
- `board/` = `orin-native/startup/t234-orin-nano/`
- `startup/` = `orin-native/startup/`, `tools/` = `orin-native/tools/`, `shim/` = `orin-native/shim/`
- `bsp-le/` = `C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp/src/hardware/startup/boards/t234-orin-nano/aarch64/le/`, where build-board.sh stages the board (:71-74) and builds it (:102-104). Board objects, the linked startup and its map live here; the repo's `board/aarch64/le/` holds only a Makefile.
- `sdp/` = `C:/Users/<user>/qnx800/target/qnx/usr/include/`
- `m2log` = `logs/sample-boot/orin-native-m2-six-cores.log` (run R4)
- `plan` = `docs/orin-native-port-plan.md`
- Reader reports: LIBRARY (library under el2-host), BOARD (board audit), PROBE (INTID 28 probe). All three were supplied; none was null.

**Evidence classes:** VERIFIED (read in source, in a log, or measured on this PC; cited), VENDOR_CLAIM (Arm, GIC or QNX documentation), HYPOTHESIS, UNKNOWN.

**Licence status:** every log these runs produce is evaluation output under NC QDL v7 4.6(i). Keep it private until the supervising professor has been consulted. No QNX-shipped binary is disassembled anywhere in this design. The only disassembly used is of our own objects and of a throwaway assembler test in the session scratch directory. The objects are `bsp-le/main.o`, our `shim/out/t234-shim.elf`, and `lib/aarch64/a.le/_main.o`, our own compile of the library's Apache-2.0 `_main.c`. That last one is byte-identical to the `_main.o` member of `install/aarch64le/usr/lib/libstartup.a`, the archive the startup links (`bsp-le/startup-t234-orin-nano.map:3`); the BSP's `prebuilt/` archive was not opened.

---

## 0. Summary

M1b re-runs the M2 payload with `-Q enable,el2-host`, so that QNX never leaves EL2: `hyp_enable_el2_host` sets `HCR_EL2.E2H` and `TGE` on every core (lib/aarch64/hypervisor.c:88-93, lib/aarch64/hypervisor_enable.S:24-34), and procnto is entered at EL2 in the EL2&0 translation regime. The plan's purpose for it (plan:320): expect the library's VHE line, settle INTID 28 (plan §8 unknown #3), and show the host kernel and user space working at EL2 on one CPU, then on six. It gates M3 (qvm and a guest), which is not part of M1b.

**Where the risk is.** The library needs nothing from the board to run el2-host. Only four places in it branch on EL or hypervisor flags (LIBRARY Q9-01, checked by grep). Two things around it, however, turn plausible failures into a silent power cycle:

1. **CPU0 has no working EL2 fault handler under el2-host.** VERIFIED; this is the orchestrator's seed observation, confirmed and widened.
   - The shim installs its own vectors in VBAR_EL2 (shim/t234-shim.S:146-150), and nothing on CPU0 replaces them. The library writes VBAR_EL2 only on the el1-host path (lib/aarch64/hypervisor_enable.S:43, reached from lib/aarch64/hypervisor.c:94-110).
   - The shim handler prints through x21, x22 and x23 (t234-shim.S:404-435). The library assembly from `cstart` to `_main` leaves them alone, but `_main`, the first C code, overwrites x22 and x21 before it calls `board_init`. Our objdump of `_main.o` shows `adrp x22, boot_args` at 0x14, `add x21, x22` at 0x18 and `bl board_init` at 0x70 (§1 C5). Our own `main()` then reuses all three (objdump of our `main.o`: `stp x21,x22` at +0x10, `mov x21,x1` at +0x14, `adrp x22` at +0x5c, `adrp/ldr x23` at +0x6c/+0x70).
   - Once `vstart` turns the MMU on (lib/aarch64/vstart.S:86-90, redirected to SCTLR_EL2 under E2H=1), the shim page 0x80080000-0x80081fff lies outside the only low mapping. That mapping is the startup image [0x80082000, 0x800af000) (lib/aarch64/init_mmu.c:159-161; `shim/out/m2/m2-p6.dumpifs.txt:8-9` gives `image_paddr=0x80082fa0 startup_size=0x2b148`). The vector fetch itself would fault, again and again.
   - Under `-Q disable` this window closed when CPU0 dropped to EL1 in `hypervisor_init`. Under el2-host it runs from `_main` to procnto.
2. **Nothing checks INTID 28 before procnto is handed its clock on it.**
   - Under el2-host, `qtime->intr` becomes 28 unconditionally (lib/aarch64/init_qtime_v8gt.c:56-57). The Tegra234 device tree lists no hyp-virt timer PPI (research-tegra234.md:40, :109).
   - The `-t` probe is a stub that only prints (board/wdt.c:97-113).
   - The only in-project evidence of what an unwired EL2 virtual timer does to this procnto is from QEMU. A QHV el2-host image ran user space and then stalled at its first timed wait (`logs/sample-boot/orin-qhv-tcg-q111-nohypvirt-control.log:1-7`; docs/findings.md:203-212). On the board that means a hang, a power cycle and an empty black box.

**What changes** (all board-side or tool-side; no library patch beyond the existing RWP bound, no shim change):
- **CPU0 EL2 vectors from the first board hook.** A board `board_init()` override installs `t234_el2_vectors` on CPU0 in every `-Q` mode. `_main` calls `board_init` before anything else (lib/_main.c:126), with cstart's stack already set (lib/aarch64/cstart.S:88-90).
  - That table sits inside the identity-mapped startup image, and its MMU-on guard resets without touching memory (board/aarch64/vectors_el1.S:162-164, :180-188).
  - `main()` writes a CPU0 boot stage before each startup step, so an EL2 fault line names the step. The fault line also gains HCR_EL2.
- **An automatic INTID 28 probe on every core under el2-host, fail-closed** (§4).
  - It runs inside the existing GIC wrapper, after the library's per-CPU GIC init and after that core's own `hypervisor_init`. The core is then at EL2 with E2H=1 and TGE=1, the register view procnto will use.
  - It arms the EL2 physical timer (INTID 26, the one Linux uses at EL2) as a positive control, then the EL2 virtual timer (INTID 28), and watches `GICR_ISPENDR0` without ever taking an interrupt.
  - Any verdict other than `wired` stops the run with a named `crash()`, which is a warm reset that keeps the black box.
  - `-t` becomes a policy switch: `stop` (the default), `continue`, `off`. No ladder image passes it.
- **A per-core el2-host self-check.** Each core prints its HCR_EL2 and stops by name unless it is at EL2 with E2H and TGE set.
- **smpcheck census additions.**
  - It prints `qtime_intr` and `hypinfo_flags` from the kernel's system page.
  - It proves CPU0's kernel clock ticks within a 2 s bound before any worker starts. If the clock is dead it calls `sysmgr_reboot()` instead of stalling in the script's first sleep.
- **A new image generator `startup/make-m1b-images.sh`.**
  - `m2.build.in` and `make-m2-images.sh` stay untouched.
  - Every build re-proves that the M2 buildfiles regenerate byte for byte against pinned sha256 values.
  - It derives the M1b buildfiles by exactly two substitutions: the `-Q` token and the `display_msg` label.
- **Stale text is corrected.** This covers the watchdog wording (a print and several comments) and every comment that says CPU0 keeps the shim's vectors or that startup always ends at EL1.

**Run ladder** (§6):

| Step | Image | Purpose |
|---|---|---|
| R0 | `reg-p6` (`-Q disable -P6`, buildfile byte-identical to `m2-p6`) | Regression: the new startup and smpcheck on M2's proven path |
| R1 | `m1b-p1` (`-Q enable,el2-host -P1`) | The plan's M1b: VHE line, INTID 28 on CPU0, procnto and user space at EL2 on one core |
| R2 | `m1b-p6` (`-Q enable,el2-host -P6`) | Six cores at EL2 with VHE: probe per core, CPU_ON issued from EL2, per-core timers under the host |
| R2b | `m1b-p6` | Repeat, ruling out a first-run fluke |
| Built, run only on a branch | `reg-p1`, `m1b-p2`, `m1b-p4`, `el1h-p1`, `el1h-p6` | Bisects, cluster-1 degraded fallback, and the el1-host contingency if INTID 28 is not usable |

**What a pass settles:**
- INTID 28 is wired to the NS EL2 virtual timer on each core the run brought up, in the NS view.
- `startup-t234-orin-nano` brings every core up at EL2 with E2H and TGE set.
- procnto 8.0 runs at EL2 on this silicon.
- Its clock ticks on CPU0, and per-core timers fire on each core, with `qtime->intr = 28`.
- Six pinned 60 s loads complete at EL2.
- `shutdown -S reboot` still returns L4T.

It does not settle anything about qvm, stage 2, a guest or timing (§10).

---

## 1. Inputs and contradictions resolved

All three reader reports arrived. Every item this design uses was checked against source, a log or our own objects; items that could not be checked keep the reader's class and say so. Seven reader items were rejected or changed (C4, C7-C9, C13, C15 and the probe's `early` term in §4); the rest are applied with corrected citations.

| # | Contradiction or defect | Resolution | Evidence |
|---|---|---|---|
| C1 | Where CPU0's EL2 table goes. BOARD B1: a `board_init()` override. PROBE E1: in `main()` after `select_debug`. LIBRARY Q1-10: either `t234_el2_vectors` or `t234_install_el1_vectors` called after `hypervisor_init`, landing in VBAR_EL2 through the E2H alias. | **`board_init()`, installing `t234_el2_vectors`, in every `-Q` mode.** It is the earliest board hook with a stack. It also covers `setup_cmdline`, `cpu_startup`, `init_syspage_memory` and option parsing. A fault before `select_debug` cannot print, because `print_char` is still `dummy_print_char`, but it still resets: `crash_done` calls `psci_call`, which is initialised to `psci_smc`. The EL1-table alias is rejected: its text says "EL1" for EL2 faults, and it would be live only after `hypervisor_init`. | lib/_main.c:126 (only caller of `board_init`, grep) vs :145; lib/board_init.c:28-34; lib/aarch64/cstart.S:88-90; lib/kprintf.c:28; lib/aarch64/psci_call.S:35; board/crash_done.c:46-50. VERIFIED |
| C2 | Probe placement. BOARD B2: CPU0 only, in `main()` after `init_cpuinfo`. PROBE E3: in the GIC wrapper on every core. PROBE E4: an optional report-only prep run under `-Q disable -t` at E2H=0. | **The GIC wrapper, on every core, under el2-host only; no prep run.** The wrapper runs after each core's own `hypervisor_init` and after the library's per-CPU GIC init. CPU0 reaches it before any CPU_ON, and each AP while CPU0 is silent. PPI wiring is per-core, and this SKU splits its cores across two clusters and non-contiguous frames. The prep run rests on PROBE A4, that CNTHV asserts with E2H=0 (HYPOTHESIS), and it costs a run; the fail-closed E2H=1 probe answers the same question and ends in a warm reset either way. | lib/aarch64/smp_start.S:73, :84; lib/aarch64/init_cpuinfo.c:306-308; main.c:210, :217, :222; board/board_smp.c:186-198 (CPU0 silent wait). VERIFIED |
| C3 | BOARD B2 expects `GICR_IGROUPR0` bits 26 and 28 to read 1 after the library's write. PROBE C1: `IGROUPR0` is RAZ/WI to Non-secure software when `GICD_CTLR.DS=0`. | **Print it raw; never judge on it.** Security is told apart by the priority readback rule (§4.4), with 26 as the reference. Neither reader measured it. | lib/aarch64/gic_v3.c:1484-1486; GICv3 spec §12.11.12 (PROBE). VENDOR_CLAIM |
| C4 | BOARD B3(a): replace the sleeps in smpcheck's `wait_files`, `drain_sleep` and the worker watchdog with a `ClockCycles()` poll plus `sched_yield()`, so waits hold with no tick. | **Rejected for the collectors.** A collector pinned to cpu 0 at priority 10 that never blocks starves worker 0, which is pinned to cpu 0 at priority 9; at `-P1` every worker is on cpu 0. `sched_yield` yields only to equal priority (VENDOR_CLAIM, POSIX). **Replaced by** a bounded tick check inside the census, which runs before any worker starts, and a reboot if the tick is dead. Once cpu 0's tick is proven, M2's watchdog thread already bounds a dead timer on an AP. | tools/smpcheck.c:100-101, :214-224, :941-947, :811-862, :1014-1043; startup/m2.build.in:112, :118. VERIFIED |
| C5 | Where CPU0's shim fault printer stops working. LIBRARY Q1-03: intact at least through the library assembly. BOARD B1 and the seed: from `_main` or `main()` onward. | **Inside `_main`, before `board_init` runs.** LIBRARY Q1-03 holds for the assembly: cstart writes x19, x0 and sp and nothing else. `_start_el2_or_el1`/`at_el2` keeps LR in x20 and otherwise writes x0, x1 and, through `is_pauth_supported`, x9. `aarch64_cache_flush` writes x0-x5, x7-x11, x16 and x17. None of them writes x21-x23. `_start_el1`, whose `mov x21, x30` is at :225, has no caller in the library or the board (grep); it is linked only because it shares an object with `_start_el2_or_el1` (map :131-132). The C code is where they go: `_main` writes x22 at object offset 0x14 and x21 at 0x18, both before `bl board_init` at 0x70; x23 is not written there. The mkifs preboot stub (`*.boot`, 0xfa0 B at 0x80082000) is a QNX binary, so whether it preserves them is UNKNOWN. **Consequence, derived from source and not observed:** a fault in `_main` after 0x18 and before `board_init` reaches the shim's `putc` with x22 below x23, so the unsigned bound skips the black box. Its mailbox poll then reads, and may overwrite, `boot_args` instead of the TCU. Nothing appears on either channel before the shim's reset. This assumes x23 survived the stub. Separately, the shim's cursor is stale once `select_debug` has run, even with intact registers: `put_tcu` appends through its own `bb_len`, while the shim's `putc` rewrites start and size from x22. | lib/aarch64/cstart.S:53-90; lib/aarch64/_start_el1.S:52-66, :125-197, :223-232, :247-260; lib/aarch64/aarch64_cache_flush.S:34-75; objdump of `lib/aarch64/a.le/_main.o` (byte-identical to the linked member, sha256 f09f6557…); `bsp-le/startup-t234-orin-nano.map:3`, :27, :131-132; `shim/out/m2/m2-p6.dumpifs.txt:2`; shim/t234-shim.S:47-54, :404-413, :424-434; board/hw_sertcu.c:72-83, :121-131. VERIFIED, except the stub (UNKNOWN) |
| C6 | Outcome of a CPU0 fault through the shim vectors. LIBRARY Q1-05: probably a warm reset with no text, possibly recursion. BOARD B1 and PROBE E1: a silent loop. | **Before `vstart`, either can happen (HYPOTHESIS: it depends on what the registers hold). After `vstart`, a re-fault loop is certain (VERIFIED).** C5 narrows one slice: in `_main` before `board_init` the registers are known, and the handler resets without text (derived). The design treats the whole window as a power-cycle hazard and closes it. | t234-shim.S:385-392, :528-547; `shim/out/t234-shim.elf` (nm): `vectors` 0x80080800, `exc_common` 0x80081000, `_shim_end` 0x80082000; lib/aarch64/init_mmu.c:159-161. VERIFIED |
| C7 | BOARD m11: a per-AP pre-check of `ID_AA64MMFR1_EL1.VH`, because the library's mismatch crash prints a garbage CPU number. | **Not added.** All six cores report the same `AA64MMFR1:0000000010212122`. The AP's own `t234: cpu N entry EL2` lines print just before its `hypervisor_init`, so they already name the core. | m2log:210, :219, :228, :237, :246, :255; lib/hypervisor_setup.c:60-62; board/board_smp.c:226-234. VERIFIED |
| C8 | BOARD m2: guard `t234_install_el1_vectors` against E2H=1. | **Not added.** Both call sites precede `hypervisor_init` by construction; comments state the ordering. | board/main.c:174 vs :202; lib/aarch64/smp_start.S:66 vs :73. VERIFIED |
| C9 | Name of the probe override. PROBE G2 leaves it open but says not `-T`. BOARD M4 says drop `-t` or make it a no-op. | **`-t` takes an argument: `stop` (default), `continue`, `off`.** `t` is not in the common set, and `T` is. | lib/public/startup.h:163; lib/public/aarch64/cpu_startup.h:55; board/main.c:134. VERIFIED |
| C10 | PROBE cites `t234_startup.h:299`, `:363-372`, `:380-390`, `:191-197`, `:215-230`, `:290`; `ap_entry.S:370`, `:382-384`, `:463-472`; `crash_done.c:134-158`. None exist at those lines. | **The claims hold; the line numbers do not.** Correct lines: `t234_startup.h` has 304 lines, with the CNTFRQ fallback at :186, `t234_cps` at :250-259 and the deadlines at :267-277. `ap_entry.S` has 171 lines, with VBAR_EL2 at :58-64 and the normalisation at :143-156. `crash_done.c` resets at :46-50. This design cites only lines re-read. | the files. VERIFIED |
| C11 | Expected HCR_EL2 under el2-host. BOARD M2: `00000004a8000000`, or `00000304a8000000` with pauth. LIBRARY Q2-02: `0x304A8000000`. | **`00000304a8000000`.** `is_pauth_supported` tests `ID_AA64ISAR1_EL1 & 0xff0`, which is 0x030 on this part, so API and APK are set. Only E2H (bit 34) and TGE (bit 27) are criteria; the value is recorded. | lib/aarch64/_start_el1.S:151-156, :248-250; m2log:208; lib/aarch64/hypervisor_enable.S:29-33. VERIFIED computation, value HYPOTHESIS until printed |
| C12 | BOARD m1 lists seven SDP `libc.a` routines in the startup link. | **The link holds more.** Twenty distinct members: `memchr`, `memcmp`, `memset`, `strchr`, `strcmp`, `strlcpy`, `strlen`, `strnlen`, `strrchr`, `strtoull`, `strncmp`, `getsubopt`, `xstoint`, `xctype`, `__progname` and three `hwi_*`, plus the stack-protector objects `_ssp` and `__stack_chk_guard`. Whether any uses FP/SIMD stays UNKNOWN (no inspection); an EC 0x07 trap is named (§7). | `bsp-le/startup-t234-orin-nano.map:251-290`. VERIFIED |
| C13 | LIBRARY Q7-02: test `-F0x10000` (`AARCH64_CPU_FLAG_VHE`), which the library never sets. | **Not in any ladder image.** It stays a failure-branch decision for the owner. The cloud-leg QHV host ran procnto at el2-host without `-F`: its startup line is `startup-qemu-virt -Q enable` on `-cpu max`, and plain `enable` resolves to el2-host when VH≠0. Whether `startup-qemu-virt`'s own board code sets the flag is UNKNOWN; it is a shipped binary with no board source. | `qhv/host/output/build/ifs.build:17` (a local, git-ignored build output, .gitignore:16); scripts/launch-qhv-tcg.ps1:150-151; lib/aarch64/hypervisor.c:47-58; sdp/aarch64/syspage.h:57; lib/init_system_private.c:116-140. VERIFIED |
| C14 | CPU0's `GICR_ISPENDR0` address: plan K8 and synthesis-plan.md say `0xF450220`. | **`0x0F450200`** (frame 0x0F440000 + SGI base 0x10000 + 0x200). Code derives it from the frame the library bound, never from a literal. | plan:91; synthesis-plan.md:209; lib/public/aarch64/gic_v3.h:74, :95; m2log:52. VERIFIED |
| C15 | `board/wdt.c:108-110` and `startup/README.md:58-63` say "if the hypervisor comes up and its timeouts work, INTID 28 is wired", the same answer by a slower route. BOARD B2 calls this wrong. | **Wrong as a plan.** The QEMU evidence shows a host whose EL2 virtual timer is unwired still runs user space, then stalls at its first timed wait. "Comes up" proves nothing, and "timeouts work" is observed only when it does not hang; a hang costs the power cycle and the black box. | orin-qhv-tcg-q111-nohypvirt-control.log:1-7, :9-20; docs/findings.md:203-212 (TCG, not hardware). VERIFIED under emulation |

**Reader items applied** (with corrected citations where C10 applies): LIBRARY Q1-01..Q1-09, Q2-01..Q2-09, Q3-01..Q3-04, Q4-01..Q4-03, Q5-01, Q5-02 (as HYPOTHESIS), Q6-01..Q6-06, Q7-01, Q7-03, Q7-04, Q8-01, Q8-02, Q9-01..Q9-06; BOARD B1, B2, B3(b), M1, M2, M4, m1 (partly), m3, m5, m6, m7, m8, m9, m10; PROBE A1-A3, A5, B1, B2, C1-C3, D1, E1, E3, E5, F1, G1-G3, H1, I1 (formats adjusted), X1, X2. BOARD M3 is applied in a different shape (a new generator rather than markers in the M2 template; §5 gives the reason).

---

## 2. Design rules

1. **No library patch.** Every change is a board hook, a board override (`board_init`, `crash_done`), a board wrapper of a public pointer (`gic_cpu_init`, `smp_hook_rtn`), or tool code. The only library change stays the existing bounded `wait_for_rwp` (startup/build-board.sh:57-69).
2. **No shim change.** `shim/t234-shim.S` is not edited in M1b, so the shim page and its bytes stay those every M2 kimg carried (build-shim.sh patches only the image size). Its stale comments are listed in §11.
3. **One variable per rung.**
   - One startup build and one smpcheck build serve every M1b image; the generator records both sha256 values and fails if either changes during a build (as make-m2-images.sh:334-351 does).
   - `reg-pN.build` is byte-identical to the `m2-pN.build` that ran.
   - `m1b-pN.build` differs from `reg-pN.build` only in the `-Q` token of the startup line and the label inside the two `display_msg` strings. `el1h-pN.build` differs the same way.
   - Comment lines are removed from derived buildfiles. mkifs does not compile comments into the script: `shim/out/m2/m2-p6.dumpifs.txt` shows the two `display_msg` lines and none of the template's `#` lines. VERIFIED.
   - Between rungs of the same `-Q` mode, only `-P` differs.
4. **M2's record is immutable.**
   - Nothing writes under `shim/out/m2/`.
   - `startup/m2.build.in` and `startup/make-m2-images.sh` are not edited.
   - The six M2 buildfiles and six kimg prefixes are pinned in the new generator and re-checked on every build (§5.3).
5. **Every wait has a real-time deadline.** Startup waits use the generic counter against `t234_cps()` (board/t234_startup.h:250-277); the probe adds an iteration cap as a second bound. smpcheck's census tick check bounds itself with `ClockCycles()` and never sleeps in the thread that judges.
6. **No path from `board_init` to procnto's own vector install may fault-loop or hang silently, on any CPU, in any `-Q` mode.** Every fault ends in PSCI SYSTEM_RESET. Before `select_debug` it resets without text; before `vstart` it prints a named line first; after `vstart` it resets directly from the MMU-on guard. The residual windows, which the board cannot close, are listed in the timeline below and in §9.
7. **Fail closed under el2-host.** A core that cannot show EL2 with E2H and TGE set, or cannot show INTID 28 wired, stops the run by name before procnto (default `-t` policy). Continuing on unverifiable state needs an explicit `-tcontinue`, and only the owner authorises that.
8. **Secondary cores print only while CPU0 is provably silent** (unchanged; board/board_smp.c:179-198).
9. **The `-Q disable` path keeps M2's observable behaviour** except for the intentional text changes listed in §6's R0 row. R0 checks it before any el2-host run.
10. **Each run answers its own unknowns.** Printed: each core's HCR_EL2 and GIC security view; the EL2 timers' state as found; the INTID 26 and 28 pending traces; the entry state of a CPU_ON issued from EL2 (existing lines); `qtime_intr`; `hypinfo_flags`; the measured tick.

### CPU0 timeline under `-Q enable,el2-host`: fault and hang coverage, today vs. with this design

| Phase | EL / E2H / MMU | Today: fault | Today: hang | With design: fault | With design: hang |
|---|---|---|---|---|---|
| kexec jump → mkifs preboot stub (`*.boot`) → `cstart` → `_start_el2_or_el1`/`at_el2` → `_main` before its x22/x21 writes | EL2, E2H=0, off | shim vectors. x21-x23 hold the shim's values at the jump (t234-shim.S:107-113, :138, :358-366), and the library assembly writes none of them; the stub is UNKNOWN (§1 C5). If they survive, the shim prints `EXC …` and resets | unbounded | **Unchanged (residual).** The same code and state as every M1/M2 run, which never faulted here. | unbounded (residual, same as M2) |
| `_main` from its x22/x21 writes (object offsets 0x14/0x18) up to `board_init` | EL2, 0, off | shim vectors with x21 = `&boot_args` and x22 = its page (VERIFIED, §1 C5): no text on either channel, then the shim's reset (derived) | unbounded | **Unchanged (residual)**, as in the row above | unbounded (residual, same as M2) |
| `board_init` → `setup_cmdline`, `cpu_startup`, `init_syspage_memory`, `main` options, `select_debug` | EL2, 0, off | shim vectors with clobbered registers: stray stores or a loop | unbounded | `t234_el2_vectors`: reset **without text** (`print_char` is still the dummy) | unbounded (no loops here in source) |
| `select_debug` → `hypervisor_init` | EL2, 0, off | same as above | — | board EL2 line with stage 0x02/0x03, then reset | — |
| `hyp_enable_el2_host` → `init_smp`, `init_mmu`, `init_intrinfo`, `init_qtime`, `init_cacheattr`, `init_cpuinfo` (GIC wrapper, el2-host check, probe), `init_hwinfo`, `init_system_private` (CPU_ON, 15 s waits), `print_syspage` | EL2, **1**, off | same | M2's bounded waits | board EL2 line with stage and HCR_EL2, then reset; probe STOP is a named crash | M2's bounds, plus the probe's 100 ms/20 ms bounds |
| `write_syspage_memory`, `t234_transfer_aps` (N>1), `startnext` → `cpu_startnext` → `vstart` before `SCTLR.M` | EL2, 1, off | same | M2's 5 s park deadline | board EL2 line, reset | unchanged |
| `vstart` after `SCTLR_EL2.M=1` → procnto installs its own VBAR_EL2 | EL2, 1, **on** | **vector fetch at 0x8008xxxx faults (unmapped) → endless re-entry → power cycle** | — | `t234_el2_vectors` is in the identity-mapped startup image; the guard sees `SCTLR_EL2.M` and resets with no memory access, no text | — |
| procnto, before its own EL2 vectors if it removes the identity map first | EL2, 1, on | UNKNOWN (binary) | unbounded | **residual**: a fault cannot fetch the board vector either | **residual**; COM3 is the evidence |
| user space with a dead clock interrupt | EL0/EL2, on | — | stall at the first timed wait (QEMU evidence, C15) | — | census tick check: `tick=dead`, then `sysmgr_reboot()`, **if** the script reaches `smpcheck -i` (after `devc-pty` and `pidin info`) |

### Secondary-core timeline under el2-host (only what differs from M2's AP table, m2-design.md §2)

| Phase | EL / E2H / MMU | With design: fault | With design: hang |
|---|---|---|---|
| CPU_ON issued by CPU0 **from EL2 with E2H=1, TGE=1** (SMC) | CPU0 EL2 | n/a | the SMC not returning is unbounded, as in M2 |
| `t234_ap_entry` → `at_el2` → `board_smp_adjust_num` | AP EL2, E2H=0, off | board EL2 vectors (M2) | CPU0's 15 s deadline, stage 0x20/0x21/0x30 |
| `hypervisor_init` (el2-host) → `cpu_startup` → `init_one_cpuinfo`: GIC wrapper, then **el2-host check and probe** | AP EL2, **1**, off | board EL2 vectors now read the EL2 registers directly (no drop); line has HCR_EL2 and stage 0x40-0x45 | CPU0's 15 s deadline, stage 0x44 = inside the probe |
| `syspage_available` → `cpu_startnext` → `vstart` → `smp_spin` | AP EL2, 1, on after `vstart` | MMU-on guard: direct reset (M2) | CPU0's 5 s park deadline (M2) |

---

## 3. Ordered code changes

Apply in this order. All files are in the repo; nothing in the BSP tree or the SDP is edited. New board sources need no Makefile change: the M2 commit added `aarch64/ap_entry.S`, `board_smp.c` and others and touched no board Makefile (`git show --stat 12c8b2c`: only `tools/Makefile`). VERIFIED.

### 3.1 `board/t234_startup.h`: constants and prototypes

**New CPU0 boot stages**, written by CPU0 into `t234_ap_diag[0].stage`. They are below 0x10 so they can never be mistaken for an AP stage:

| Code | Name | Written |
|---|---|---|
| 0x01 | `T234_STAGE_BOOT_VECTORS` | `board_init`: board EL2 vectors installed |
| 0x02 | `T234_STAGE_BOOT_OPTIONS` | `main`, after `select_debug` |
| 0x03 | `T234_STAGE_BOOT_HYP` | before `hypervisor_init(0)` |
| 0x04 | `T234_STAGE_BOOT_SMP` | before `init_smp` |
| 0x05 | `T234_STAGE_BOOT_MMU` | before `init_mmu` |
| 0x06 | `T234_STAGE_BOOT_INTR` | before `init_intrinfo` |
| 0x07 | `T234_STAGE_BOOT_QTIME` | before `init_qtime` |
| 0x08 | `T234_STAGE_BOOT_CPUINFO` | before `init_cacheattr`; `init_cpuinfo` then runs the GIC wrapper, which writes 0x40-0x45 for cpu 0 |
| 0x09 | `T234_STAGE_BOOT_SYSPRIV` | before `init_system_private` (CPU_ON for every AP happens inside) |
| 0x0a | `T234_STAGE_BOOT_PRINT` | before `print_syspage` |

**New wrapper stages**, for every core:
- `0x44` `T234_STAGE_HVT`: the el2-host check passed and the probe is running.
- `0x45` `T234_STAGE_HVT_DONE`: the probe returned and the policy allowed the core to continue.

Rewrite the comment above the stage list (:159-160): cpu 0 writes 0x01-0x0a and passes 0x40-0x45 during `init_cpuinfo`, so its numbers are not monotonic; a secondary passes 0x10-0x70, with 0x44/0x45 only under el2-host.

**New definitions:**
- `T234_HCR_E2H (1ull << 34)` and `T234_HCR_TGE (1ull << 27)`, citing lib/aarch64/hypervisor_enable.S:30-31.
- `T234_HVT_STOP 0`, `T234_HVT_CONTINUE 1`, `T234_HVT_OFF 2`.
- Verdict codes `T234_HVT_WIRED 0`, `T234_HVT_ABSENT 1`, `T234_HVT_INCONCLUSIVE 2`.

**Declarations** (C only):
- `extern int t234_hvt_policy;` (defined in main.c, initialised to `T234_HVT_STOP` so it lives in `.data`)
- `void t234_install_el2_vectors(void);`
- `int t234_hvt_probe(unsigned cpu, paddr_t sgi);`

**Remove** the `t234_probe_hv_timer` prototype (:283).

**Comment corrections** (text only):
- **:78-84, watchdog.** "WDT0 is configured by systemd at two minutes when Linux hands over, but the M0 hang test showed it does not fire after the kexec hand-over (results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md): a hang needs a power cycle, which also empties the black box. -W stays as insurance and for parity."
- **:106-109.** The black box survives "a PSCI reset, which every board fault handler ends in", not "an exception the shim's vectors turn into one".
- **:119-121.** "kexec places our 8 KiB page here. Its EL2 vectors are live on CPU0 from the jump until board_init replaces them (main.c), so the range must never be handed to the RAM allocator."
- **:261-266.** "at_el2 zeroes CNTVOFF_EL2 (lib/aarch64/_start_el1.S:180), so this reads the physical count. At EL1 (-Q disable) CNTHCTL_EL2=3 (:167-168) lets it through; at EL2 (el2-host) the counter never traps. That holds on CPU0 and on every secondary."

### 3.2 `board/aarch64/vectors_el1.S`: CPU0 install routine, comments

**Add**, next to `t234_install_el1_vectors`:

```
/*
 * void t234_install_el2_vectors(void)
 *
 * Called from board_init on CPU0, first thing in _main (lib/_main.c:126),
 * with cstart's stack in place (lib/aarch64/cstart.S:88-90). Replaces the
 * shim's EL2 vectors. Their printer depends on x21-x23
 * (orin-native/shim/t234-shim.S:404-435), and _main's own code has already
 * reused x21 and x22 by the time it calls board_init. Their page also leaves
 * the only low mapping once vstart turns the MMU on
 * (lib/aarch64/init_mmu.c:159-161).
 * At EL1 (never on this board: kexec enters at EL2) it does nothing.
 */
	.globl	t234_install_el2_vectors
t234_install_el2_vectors:
	mrs	x9, CurrentEL
	cmp	x9, #(2 << 2)
	b.ne	1f
	adr	x9, t234_el2_vectors
	msr	vbar_el2, x9
	isb
1:	ret
```

`t234_el2_vectors` is in the startup's `.text`, 2 KiB aligned. `objdump -t` of our linked startup gives `.text 0x3000` for it and `.text 0x0` for `t234_ap_entry`, and `.text` is aligned 2**11. M2 printed `t234_ap_entry` at PA 0x80083800 (m2log:56), so the table sat at 0x80086800, inside [0x80082000, 0x800af000). VERIFIED for the M2 build; the property, not the address, carries to the new build. The generator's `nm` gate (§3.10) confirms the symbol is linked.

**No code change** to the guards, the nesting word or `t234_fault_reset`.

**Comment corrections:**
- **Header :15-21, :32-36.** Split the story by `-Q` mode:
  - `-Q disable` and el1-host: CPU0 and each AP drop to EL1 in `hypervisor_init`, and faults land in `t234_el1_vectors`.
  - el2-host: no core ever runs at EL1; every startup fault on every core lands in `t234_el2_vectors`, and VBAR_EL1 is written but never used.
- **:54-59.** "The EL2 table is installed on every secondary by t234_ap_entry, and on CPU0 by board_init in every -Q mode. Nothing in this file has run on CPU0 at EL2." Keep "has not run" only where it is still true.
- **:127-134.** "SP_EL2 is cstart's stack on CPU0 and the library AP stack on a secondary; under el2-host it stays the live stack until procnto."
- **:163-164.** "SCTLR_EL2.M set: under el2-host vstart's sctlr_el1 write lands here through E2H (lib/aarch64/vstart.S:86-90). TTBR0 then maps only the startup image (lib/aarch64/init_mmu.c:159-161), so MMIO is unmapped: reset without printing."

### 3.3 `board/el1_fault.c`: attribute CPU0, show HCR

- **`t234_ec_name`.** Add `0x07` "FP/SIMD access trap", `0x18` "system register trap" and `0x3c` "BRK".
  - `0x07` is the one CPTR_EL2 can produce at EL2 once E2H=1. at_el2 wrote CPTR_EL2=0 (lib/aarch64/_start_el1.S:161), and `init_one_cpuinfo` writes `cpacr_el1=0` (lib/aarch64/init_cpuinfo.c:320). Under E2H=1 that means FPEN=00, which traps (VENDOR_CLAIM, Arm ARM).
- **Stage lookup.** Factor the MPIDR match (:86-91) into `static unsigned t234_stage_of(_Uint64t mpidr)` and use it in both handlers.
- **`t234_el1_fault`.** The format becomes `"t234: EL1 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L stage=%x\n"`. The prefix is unchanged, so M2's failure rows still match.
- **`t234_el2_fault`.** Read `_Uint64t const hcr = aa64_sr_rd64(hcr_el2);`. The handler only ever runs at EL2, and the name assembles at the SDP's default `-march` (it is used in ap_entry.S:116). The format becomes `"t234: EL2 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L SPSR=%L HCR_EL2=%L stage=%x\n"`.
  - A fault with E2H clear (`HCR_EL2` bit 34 = 0) came before that core's `hypervisor_init`. With E2H and TGE set, it came in the VHE host.
- **Comments :69-76.** "Reached on a secondary from t234_ap_entry onward, and on CPU0 from board_init onward, in every -Q mode. Under el2-host it is the only fault handler any core has until procnto. On CPU0 the stage is a boot stage below 0x10, or a wrapper stage 0x40-0x45 during init_cpuinfo."

### 3.4 `board/main.c`: `board_init`, `-t` policy, stages, comments

**(a) Add before `main`:**

```c
/*
 * First board code in _main (lib/_main.c:126, its only caller), overriding
 * the library's empty version (lib/board_init.c:28-34) by archive order, as
 * crash_done does. Installs the board EL2 vectors on CPU0 in every -Q mode;
 * see aarch64/vectors_el1.S. A fault before select_debug cannot print yet
 * (lib/kprintf.c:28) but still resets, because crash_done's psci_call is
 * already psci_smc (lib/aarch64/psci_call.S:35).
 */
void
board_init(void)
{
	t234_install_el2_vectors();
	t234_ap_diag[0].stage = T234_STAGE_BOOT_VECTORS;
}
```

**(b) Options.**
- Replace `int probe_hv` (:110) with the global `int t234_hvt_policy = T234_HVT_STOP;` and a local `const char *hvt_arg = NULL;`.
- The option string (:134) becomes `COMMON_OPTIONS_STRING "m:W:t:"`.
- The `'t'` case (:150-152) sets `hvt_arg = optarg` and maps `"stop"`, `"continue"` and `"off"` to the policy. Anything else: `crash("t234: -t%s is not stop, continue or off\n", optarg);`.

**(c) Stages.** Immediately after `select_debug` (:159), write stage 0x02. Before each call, write 0x03 (`hypervisor_init`, :202), 0x04 (`init_smp`, :203), 0x05 (`init_mmu`, inside the `if` at :205-207), 0x06 (`init_intrinfo`, :209), 0x07 (`init_qtime`, :210), 0x08 (`init_cacheattr`, :216), 0x09 (`init_system_private`, :222) and 0x0a (`print_syspage`, :245). Each write is `t234_ap_diag[0].stage = T234_STAGE_BOOT_...;`.

**(d)** Delete the probe call (:212-214).

**(e) `-t` outside el2-host.** After `hypervisor_init(0)`:

```c
if (hvt_arg != NULL &&
    hypervisor_get_required_flags() != (HYP_FLAG_ENABLED | HYP_FLAG_EL2_HOST)) {
	kprintf("t234: -t%s has no effect: the INTID 28 probe runs only under -Q enable,el2-host\n", hvt_arg);
}
```

`hypervisor_get_required_flags` is declared at lib/public/startup.h:591. `HYP_FLAG_EL2_HOST` comes from lib/public/aarch64/cpu_startup.h:86, which startup.h includes at :121.

**(f) Comment corrections:**
- **:16.** "M1 and M2 ran this file on the board under -Q disable; nothing here has run under -Q enable."
- **:146-147.** "-W: keep | disable. keep is the default for parity; the watchdog does not fire after kexec (m0-hang-watchdog.md)."
- **:161-174.** State that the EL1 table matters under `-Q disable` and el1-host only. Under el2-host CPU0 never reaches EL1, and faults land in the EL2 table from `board_init`.
- **:176-180.** "Report both watchdogs. WDT0 arrives configured, but it did not fire after the kexec hand-over in the M0 hang test."
- **:186-194.** "Keep the shim's page: its vectors are live on CPU0 from the kexec jump until board_init replaces them. Under -Q disable CPU0 leaves EL2 inside hypervisor_init; under el2-host it never does, which is why board_init installs the board EL2 table rather than relying on the shim's."

### 3.5 `board/aarch64/init_intrinfo.c`: el2-host check and probe gate in the wrapper

**Where it goes.** In `t234_gic_cpu_init`, after step 7 (the `cpu N up` line and `d->stage = T234_STAGE_UP`, :267-270), add step 8. It is placed after the up line so that 0x43 keeps M2's meaning and the stages stay in time order.

```c
/*
 * 8. el2-host only: prove this core is the VHE host procnto will run on, and
 * that the clock interrupt the library gave procnto is wired to it. Runs
 * after this core's own hypervisor_init (CPU0: main.c; a secondary:
 * lib/aarch64/smp_start.S:73 before :84), so E2H and TGE are set and every
 * CNTV_* access procnto makes lands on CNTHV_*_EL2, whose PPI the library
 * named INTID 28 (lib/aarch64/init_qtime_v8gt.c:56-57) without checking it.
 */
if (hypervisor_get_required_flags() == (HYP_FLAG_ENABLED | HYP_FLAG_EL2_HOST)) {
	unsigned const el = (unsigned)(aa64_sr_rd64(CurrentEL) >> 2) & 3u;
	_Uint64t       hcr;
	int            v;

	if (el != 2) {
		crash("t234: cpu %d el2-host requested but running at EL%d, stopping\n", cpu, el);
	}
	hcr = aa64_sr_rd64(hcr_el2);
	if ((hcr & T234_HCR_E2H) == 0 || (hcr & T234_HCR_TGE) == 0) {
		crash("t234: cpu %d el2-host requested but HCR_EL2=%L: E2H and TGE must both be set, stopping\n", cpu, hcr);
	}
	kprintf("t234: cpu %d el2-host EL2 HCR_EL2=%L\n", cpu, hcr);

	d->stage = T234_STAGE_HVT;
	if (t234_hvt_policy == T234_HVT_OFF) {
		kprintf("t234: hvtimer cpu %d probe off (-toff): clock INTID %d not checked\n",
		        cpu, (int)lsp.qtime.p->intr);
	} else {
		v = t234_hvt_probe(cpu, sgi);
		if (v != T234_HVT_WIRED) {
			if (t234_hvt_policy == T234_HVT_CONTINUE) {
				kprintf("t234: hvtimer cpu %d continuing despite verdict=%s (-tcontinue)\n",
				        cpu, t234_hvt_verdict_name(v));
			}
			/* under -tstop the probe has already crashed, naming its reason (§4.6) */
		}
	}
	d->stage = T234_STAGE_HVT_DONE;
}
```

**How STOP and CONTINUE are split.** `t234_hvt_probe` crashes itself on a non-wired verdict when the policy is `stop` (§4.6), so that the crash text can carry the reason token. The wrapper only handles `off` and `continue`. `t234_hvt_verdict_name` is a small static helper exported from hvtimer.c.

**`lsp.qtime.p->intr`.** `init_qtime` runs before `init_cpuinfo` on CPU0 (main.c:210 vs :217) and long before any AP starts, so the section is allocated. The field exists: lib/print_sysp.c:216.

**Comment corrections:**
- **:67-68.** "on CPU0, before any secondary depends on them" (drop "the one CPU whose faults are reported").
- **:139-143.** "at EL1 under -Q disable, or at EL2 with E2H and TGE set under el2-host, MMU off in both".
- **:297.** "CPU0's fault vectors are live: the board EL1 table under -Q disable, the board EL2 table under el2-host (main.c)".

### 3.6 NEW `board/aarch64/hvtimer.c`: the INTID 28 probe

Specified in §4. It includes `t234_startup.h` and `<aarch64/gic_v3.h>`, like init_intrinfo.c:36-37, and carries the Apache-2.0 header in the house style. It exports `t234_hvt_probe` and `t234_hvt_verdict_name`.

### 3.7 `board/wdt.c`: remove the stub, fix the print

- **Delete** `t234_probe_hv_timer` and its comment (:83-113).
- **Replace the second print** (:49-51) with:
  `kprintf("t234: WDT0 is configured, but it did not fire after the kexec hand-over (M0 hang test): a hang from here needs a power cycle\n");`
- **Rewrite the header** (:10-21):
  - systemd configures WDT0 at two minutes.
  - The M0 hang test (m0-hang-watchdog.md) showed it does not fire after `systemctl kexec`, most likely because systemd hands the device back on its way out (HYPOTHESIS, from that note).
  - `-W` is kept as insurance against the opposite finding on another hand-over path, and for parity.
- Keep the `-W` logic unchanged (:54-81).

### 3.8 `board/board_smp.c` and `board/aarch64/ap_entry.S`: comments only

**No code change.** Each AP's el2-host check and probe run inside the GIC wrapper (§3.5), and the existing trampoline, entry-EL check and deadlines are EL-agnostic (BOARD m5, re-read: ap_entry.S:50-64, :143-156; board_smp.c:186-198, :245-248, :303-315).

**board_smp.c:**
- **:34.** "M2 ran this file on six cores under -Q disable; nothing here has run with CPU_ON issued from EL2."
- **:204-207, :214-218, :236-244.** Name both modes. Under -Q disable this core drops to EL1 in its own `hypervisor_init`. Under el2-host it stays at EL2, VBAR_EL1 is unused, and its fault path is the EL2 table `t234_ap_entry` installed.

**ap_entry.S:**
- **:34.** "Ran on every secondary in M2 (CPU_ON issued from EL1); not yet with CPU_ON issued from EL2."

### 3.9 `startup/build-board.sh`: symbol gate

- **Presence list** (:115-120): add `t234_install_el2_vectors t234_hvt_probe board_init`.
- **Defined exactly once**, with the same awk as :137-138: add a `board_init` count. If the library's empty member won instead, CPU0 would silently keep the shim's vectors, and the only symptom would be a silent hang under el2-host.
- **Must be absent:** `t234_probe_hv_timer`, so a stale `wdt.o` cannot put back the stub that prints "not implemented".
- **Informational, not a failure:** print the `libc.a` members named in the link map, e.g. `grep -o 'libc\.a([^)]*)' "$MAP" | sort -u`. A new SDP libc dependency then shows at build time (BOARD m1; §9 R8). `$MAP` is `startup-$BOARD.map` beside `$OUT`, where the M2 build left it.

### 3.10 `tools/smpcheck.c`: census tick check and hypervisor fields

**Add** `#include <sys/sysmgr.h>`. `sysmgr_reboot` is declared at sdp/sys/sysmgr.h:38.

**(a) Hypervisor fields**, in `census()` after the per-CPU rows (:436-485) and before the verdict line:
- `intr` = `SYSPAGE_ENTRY(qtime)->intr`, bounds-checked like `syspage_cps` (:172-180).
- `flags` = `SYSPAGE_ENTRY(hypinfo)->flags` when `SYSPAGE_ENTRY_SIZE(hypinfo) >= sizeof(struct hypinfo_entry)`, otherwise printed as `-`. The struct and section are user-visible: sdp/sys/syspage.h:464-467 and the generic `SYSPAGE_ENTRY` at :537.
- Print `SMPCHECK census hyp qtime_intr=%u hypinfo_flags=0x%llx`.
- **Informational only**, not a PASS/FAIL input: hypinfo does not tell el1-host from el2-host (lib/hypervisor_setup.c:86-90), and the census line must stay identical across `-Q` modes.

**(b) Tick check `tick_check()`**, run next:
1. If `cps == 0`, print `SMPCHECK census tick=unknown (no cycles_per_sec)`. The census has already failed on cps.
2. `pin_waiter()`. The calling thread stays at the script's inherited priority.
3. Create one thread with default attributes (it inherits the priority). It pins itself to cpu 0 with `pin_self(0)`, then:
   - records `ClockCycles()`
   - calls `sleep_ms(TIMER_SLEEP_MS)`
   - records `ClockCycles()` and the return code
   - sets a `volatile` done flag and exits.
4. The caller polls until the flag is set or `ClockCycles() >= start + 2*cps`, calling `sched_yield()` between polls. Both threads are pinned to cpu 0 at one priority, so the yield lets the woken sleeper run. This poll is bounded by the counter and does not depend on the tick.
5. **Outcomes:**
   - flag set with `TIMER_MIN_MS <= ms <= TIMER_MAX_MS` (:103-105): print `SMPCHECK census tick=ok ms=%llu rc=%d` and join the thread.
   - flag set but out of range: `tick=bad ms=... rc=...`, census FAIL, script continues.
   - bound expired: print `SMPCHECK census tick=dead ms>2000: the kernel clock on cpu 0 did not fire`, then `SMPCHECK CENSUS FAIL`, then `SMPCHECK tick dead: calling sysmgr_reboot so the log can be recovered`, then call `sysmgr_reboot()`.
   - if `sysmgr_reboot()` returns: print `SMPCHECK sysmgr_reboot returned %d errno=%d` and exit 1.
   - thread creation fails: `tick=error errno=%d`, census FAIL, script continues. M2 created threads without error.

**(c) Header comment** (:31-39). "cpu 0 is the only core QNX has run on so far (M1)" becomes: "cpu 0's clock is the one qtime names; the census proves it ticks before any waiter relies on it (-i)".

**(d) Usage text** (:1233). "census: kernel system page against the board tables, the hypervisor fields, and a bounded cpu 0 tick check".

**Nothing else changes.** Collectors, workers, `-z` and exit codes stay as they are. The census runs third in the script, after `devc-pty` and `pidin info` (m2.build.in:104-112), which is residual R9 in §9.

### 3.11 NEW `startup/make-m1b-images.sh`

Specified in §5.

### 3.12 `startup/README.md`: the `-t` paragraph (:58-63)

This is text only, in the board directory's README (not the repo root README, and not `docs/`). Replace the paragraph with a description of the automatic el2-host probe, its `-t stop|continue|off` policy and its output lines, and delete the "slower route" claim (C15). Owner decision if this file is out of scope for the implementer.

---

## 4. The INTID 28 probe (`board/aarch64/hvtimer.c`)

### 4.1 What it must answer, and why at this point

Under el2-host, procnto is told its clock is INTID 28 (lib/aarch64/init_qtime_v8gt.c:56-57). The library pairs 27 with 28 and disables the `CNTV` timer through the `cntv_ctl_el0` name (:66). With E2H=1 at EL2, that name reaches `CNTHV_CTL_EL2`, the NS EL2 virtual timer (VENDOR_CLAIM, Arm register XML via PROBE A3). INTID 28 is its BSA-recommended PPI (VENDOR_CLAIM).

Two further points:
- **Linux did not use it.** The only in-use timer PPI Linux shows at EL2 on this board is INTID 26 (`raw/orin-firmware-el.txt:46`: `GICv3 26 Level arch_timer`), and the device tree lists no hyp-virt entry (research-tegra234.md:109). VERIFIED.
- **Silicon can leave it unconnected.** BCM2712 is known prior art (PROBE G3, VENDOR_CLAIM).

**The question per core:** does asserting `CNTHV`'s output make INTID 28 pending at this core's redistributor, in the Non-secure view procnto has?

**Why the probe runs here.** It runs inside `t234_gic_cpu_init`, under el2-host only, on every core. At that point:
- the core is at EL2 with E2H=1 and TGE=1 (checked just before, §3.5);
- the MMU is off;
- DAIF is masked (lib/aarch64/_start_el1.S:62; CPU0 also lib/aarch64/cstart.S:57);
- the redistributor is awake (wrapper step 4, init_intrinfo.c:223-234);
- the library has put every SGI/PPI in Group 1 NS, with priority 0xA0, pending cleared, and all disabled except SGI0 (lib/aarch64/gic_v3.c:1484-1500).

INTIDs 26 and 28 are therefore disabled at the redistributor. A pending one is never forwarded, and nothing is taken (VENDOR_CLAIM, GICv3 §12.11.5, PROBE B1).

### 4.2 Register names and encodings (VERIFIED on this PC)

The SDP assembler (`aarch64-unknown-nto-qnx8.0.0-as`, binutils 2.43, default `-march=armv8-a`), run on a scratch file:
- **rejects** `mrs x0, cnthv_ctl_el2`: "selected processor does not support system register name 'cnthv_ctl_el2'";
- **accepts** `cnthp_ctl_el2`, `cnthp_cval_el2`, `cntvoff_el2`, `cntpct_el0`, `daif`, `hcr_el2` and `CurrentEL`, and assembles `S3_4_C14_C3_1` / `S3_4_C14_C3_2`, which disassemble as `cnthv_ctl_el2` (`d53ce320` / `d51ce320`) and `cnthv_cval_el2` (`d51ce340`).

The SDP macros paste the name into `mrs`/`msr` (sdp/aarch64/inline.h:98-127). Hence:

```c
/* The EL2 virtual timer has no name at the SDP's default -march; the
 * encodings are the Arm ones (op0=3 op1=4 CRn=14 CRm=3), as the library
 * spells ICC_SRE_EL2 at lib/aarch64/_start_el1.S:190. */
#define T234_CNTHV_CTL   S3_4_C14_C3_1   /* CNTHV_CTL_EL2  */
#define T234_CNTHV_CVAL  S3_4_C14_C3_2   /* CNTHV_CVAL_EL2 */
#define CNT_ENABLE   1u
#define CNT_IMASK    2u
#define CNT_ISTATUS  4u
#define B26          (1u << 26)          /* NS EL2 physical timer, Linux's arch_timer at EL2 */
#define B28          (1u << 28)          /* NS EL2 virtual timer, qtime->intr under el2-host */
```

**The EL2 physical timer** is used by name: `cnthp_ctl_el2`, `cnthp_cval_el2`.

**Access conditions:**
- Both EL2 timers are directly accessible at NS EL2 whatever E2H is (VENDOR_CLAIM, PROBE A2); at EL1 they are UNDEFINED. The probe runs only at EL2.
- Both compare against the physical count, with the virtual offset treated as 0 under {E2H,TGE}={1,1} (VENDOR_CLAIM). `at_el2` zeroes `CNTVOFF_EL2` anyway (lib/aarch64/_start_el1.S:180, VERIFIED).
- `CVAL = CNTPCT_EL0 + delta` is therefore right for both.

**GIC offsets** (lib/public/aarch64/gic_v3.h), all from `sgi` = the wrapper's frame + `ARM_GICR_SGI_BASE_OFFSET` (init_intrinfo.c:218-220). The wrapper has already checked that frame against the board table (step 6).

| Register | Offset | Header line |
|---|---|---|
| `IGROUPR0` | +0x080 | :92 |
| `ISENABLER0` | +0x100 | :93 |
| `ISPENDR0` | +0x200 | :95 |
| `ICPENDR0` | +0x280 | :96 |
| `ISACTIVER0` | +0x300 | :97 |
| `IPRIORITYR6` | +0x418 | :106 |
| `IPRIORITYR7` | +0x41C | :107 |
| `ICFGR1` | +0xC04 | :109 |

- **GICD registers:** `GICD_CTLR` at 0x0F400000 + 0 (:39) and `GICD_TYPER` at +4 (:45). SecurityExtn is `GICD_TYPER` bit 10 (:220; the library branches on it at lib/aarch64/gic_v3.c:1043).
- **Edge bits:** `edge(n) = (ICFGR1 >> (2*(n-16)+1)) & 1`, i.e. bit 21 for INTID 26 and bit 25 for INTID 28 (VENDOR_CLAIM, GICv3 §12.11.8).

All accesses are MMIO `in32`/`out32` at physical addresses with the MMU off, as the wrapper's own reads are.

### 4.3 Steps (one core; every wait bounded by the counter and by an iteration cap)

`cps = t234_cps()`, which is valid on every core after CPU0's `init_qtime`.

1. **Guards.** Each failed guard gives verdict `inconclusive` with the reason in brackets, and no timer is touched:
   - `(aa64_sr_rd64(daif) & 0xc0) != 0xc0` → [`daif`];
   - `in32(frame + ARM_GICR_WAKER) & 0x6` → [`asleep`].
2. **Context (read only).**
   - GIC: `gicd_ctlr = in32(GICD+0)`, `sec = (in32(GICD+4) >> 10) & 1`, `igroupr0`, `isen`, `isact`, `cfg1`.
   - Priorities: `prio26 = (in32(sgi+0x418) >> 16) & 0xff` and `prio28 = in32(sgi+0x41C) & 0xff`.
   - Timers: `cntvoff = CNTVOFF_EL2`; `hpctl0`, `hvctl0` and both CVALs, saved as found. On a secondary `hvctl0` is the first reading of what CPU_ON leaves in `CNTHV_CTL_EL2`, which nothing else writes on an AP (LIBRARY Q2-09).
   - Print the context line (§4.5, `-vv`).
3. **Quiesce.**
   - Write `cnthp_ctl_el2 = 0` and `T234_CNTHV_CTL = 0`, then `isb`. Both outputs deassert.
   - Poll until `ISPENDR0 & (B26|B28)` is 0, for at most `cps/50` counter ticks (20 ms) and 2^20 iterations.
   - For each still-set bit k that is edge-configured, not enabled and not active, write `ICPENDR0 = k` and re-read.
   - If a bit is still set: `inconclusive` [`stuck`].
   - `base = ISPENDR0 & (B26|B28)`.
4. **Positive control on INTID 26** (`run_hp`):
   1. `t0 = CNTPCT_EL0`.
   2. Write `cnthp_cval_el2 = t0 + cps/500` (2 ms ahead), then `cnthp_ctl_el2 = CNT_ENABLE`, then `isb`. IMASK is 0, so the output is enabled.
   3. `pre = (cnthp_ctl_el2 & CNT_ISTATUS) != 0` and `early = in32(sgi+0x200)`, both recorded.
   4. Wait while ISTATUS is clear, until `t0 + cps/10` (100 ms) or 2^28 iterations. Then `istatus` = final ISTATUS and `t_ms = (CNTPCT − t0) × 1000 / cps`.
   5. If `istatus`: poll `ISPENDR0` until bit 26 sets, at most `cps/50`; `on` = last read. Otherwise `on = in32(sgi+0x200)`.
   6. Write `cnthp_ctl_el2 = CNT_ENABLE | CNT_IMASK`, then `isb`. The output deasserts; ISTATUS stays valid because ENABLE=1 (VENDOR_CLAIM, PROBE D1).
   7. Poll until bit 26 clears, at most `cps/50`; `mask` = last read.
   8. Write `cnthp_ctl_el2 = 0`, then `isb`; `off = in32(sgi+0x200)`.
   9. **Derived values:**
      - `rose26 = (on & B26) && !(base & B26)`
      - `fell26 = !(mask & B26)`
      - `ctl_ok = istatus && rose26 && (fell26 || edge(26))`
      - `moved = on & ~base & ~mask` (bits that rose with the output and fell on IMASK)
5. **Security discriminator, before arming CNTHV.** After the library's NS write of 0xA0 to every SGI/PPI priority (gic_v3.c:1488-1493):
   - a Non-secure Group 1 field reads back non-zero;
   - a Group 0 or Secure Group 1 field is RAZ/WI to NS software (VENDOR_CLAIM, GICv3 §12.11.19, PROBE C1/C3).
   - INTID 26 is NS on this firmware, because Linux at NS-EL2 took it. So:
     - `sec == 1 && prio26 == 0` → `inconclusive` [`prio`] (the readback rule does not behave as specified; CNTHV not armed);
     - `sec == 1 && prio28 == 0` → `absent` [`secure-group`] (CNTHV not armed: arming a Secure PPI firmware may have enabled could reach EL3, HYPOTHESIS).
6. **Test on INTID 28** (`run_hv`). Identical to step 4, with `T234_CNTHV_CVAL` / `T234_CNTHV_CTL` and bit 28. The two runs are two literal code paths that differ only in register names (a register name cannot be a variable).
   - Derived: `rose28`, `fell28` and `moved_hv` as in step 4.9.
   - `wired28 = hv.istatus && rose28 && (fell28 || edge(28))`.
7. **Restore.**
   - Write both CTLs = 0 and both CVALs = their saved values, then `isb`. No timer is left enabled: the same state the library leaves (hyp_enable_el2_host zeroes CNTHP_CTL at lib/aarch64/hypervisor_enable.S:26; init_qtime zeroes CNTHV on CPU0 through the alias at init_qtime_v8gt.c:66).
   - For bit 26 and bit 28: if pending, edge-configured, not enabled and not active, write `ICPENDR0`.
   - `residue = in32(sgi+0x200) & (B26|B28)`, printed only; a level PPI with CTL=0 should read 0.
8. **Never written:** `ISENABLER0`, `ICENABLER0`, `ICFGR1`, `IGROUPR0`, any `IPRIORITYR`, DAIF. **Never read:** `ICC_IAR*`. Nothing is acknowledged, unmasked or enabled.

**Cost.** A healthy core takes about 2 ms per timer plus MMIO. The worst case, with every bound hit, is 2 × (100 + 20 + 20) + 20 ms ≈ 0.3 s. That is far inside the 15 s AP start deadline (board/t234_startup.h:177).

### 4.4 Verdicts (evaluated in this order)

| Condition | Verdict | Reason |
|---|---|---|
| a step-1 guard failed | inconclusive | `daif` / `asleep` |
| step-3 bit still pending | inconclusive | `stuck` |
| `sec==1 && prio26==0` | inconclusive | `prio` |
| `sec==1 && prio28==0` | absent | `secure-group` |
| `!hv.istatus` (CNTHV never met its condition in 100 ms) | inconclusive | `hv-istatus` |
| `wired28` | **wired** | `ok` if `ctl_ok`, else `control-failed` |
| `rose28 && !fell28 && !edge(28)` | inconclusive | `no-deassert` |
| `!ctl_ok` | inconclusive | `control` |
| `moved_hv & ~B28` non-zero | absent | `ppiNN` (NN = lowest such bit, decimal) |
| otherwise | absent | `no-ppi` |

**Rationale:**
- Positive evidence for 28 does not need the control.
- `absent` is emitted only when the control has just shown, on the same core, that the readback mechanism works: frame, awake redistributor, NS-visible pending bits, CVAL arithmetic and level tracking with forwarding off. That removes the false-absent modes.
- A disabled level PPI that shows pending is VENDOR_CLAIM (GICv3), and the control is what validates it on this GIC-600.

Verdict tokens: `wired`, `absent`, `inconclusive`; none is a prefix of another. Reason tokens: `ok`, `control-failed`, `secure-group`, `ppiNN`, `no-ppi`, `hv-istatus`, `no-deassert`, `control`, `prio`, `stuck`, `asleep`, `daif`.

### 4.5 Output lines (one `kprintf` each, every format ends in `\n`)

`%x` prints 32 bits, `%L` 64 bits and `%d` decimal (lib/kprintf.c:68-92). The prefix `t234: hvtimer` is unique in the tree (grep).

| When | Format |
|---|---|
| `debug_flag > 1` | `t234: hvtimer cpu %d ctx gicd_ctlr=%x sec=%d igroupr0=%x isen=%x isact=%x cfg1=%x prio26=%x prio28=%x cntvoff=%L hpctl=%x hvctl=%x` |
| `debug_flag > 1` | `t234: hvtimer cpu %d CNTHP ppi=26 pre=%d base=%x early=%x on=%x mask=%x off=%x istatus=%d t_ms=%d moved=%x` |
| `debug_flag > 1` | the same with `CNTHV ppi=28`, or `t234: hvtimer cpu %d CNTHV ppi=28 not armed (%s)` with `secure-group` or `prio` |
| always | `t234: hvtimer cpu %d verdict=%s reason=%s residue=%x qtime_intr=%d` |
| policy `stop`, verdict not `wired` | `crash("t234: hvtimer STOP cpu %d verdict=%s reason=%s: el2-host gives procnto its clock on INTID %d, which this core has not shown wired; stopping before procnto (fallback: -Q enable,el1-host, images el1h-p*)\n")` |
| policy `continue`, verdict not `wired` | `t234: hvtimer cpu %d continuing despite verdict=%s (-tcontinue)` (from the wrapper, §3.5) |
| policy `off` | `t234: hvtimer cpu %d probe off (-toff): clock INTID %d not checked` (from the wrapper) |

**Size.** About 550 bytes per core at `-vvv`, plus the 50-byte `el2-host` line, which is ~3.6 KB at `-P6`. M2's R4 black box was 19,239 B (m2-runs.md:28) against the 65,520 B limit (t234_startup.h:116-117). Gate G1 in §6 re-checks it from R0.

**Greps** on `console-ramoops-0`:
- `t234: hvtimer cpu [0-5] verdict=` for results;
- `t234: hvtimer cpu [0-5] CNTH[PV] ` for raw traces;
- `t234: hvtimer STOP` for the stop, which the verdict pattern cannot match.

### 4.6 What startup does on each verdict, and on which CPUs

- **CPUs:** every core that runs `t234_gic_cpu_init` under el2-host.
  - CPU0 runs it inside `init_cpuinfo` (main.c:217), after `init_qtime` and before any CPU_ON.
  - Each secondary runs it inside its own `init_one_cpuinfo` (lib/aarch64/smp_start.S:84), after its `hypervisor_init` (:73) and while CPU0 waits silently (board_smp.c:186-198).
  - Under `-Q disable` and el1-host it never runs, and it prints nothing.
- **`wired`:** continue. The stage goes 0x44 → 0x45; the core prints nothing more from the probe.
- **Anything else, policy `stop` (default):** `crash()` from inside `t234_hvt_probe`, which prints, then warm-resets through PSCI.
  - **On CPU0** this happens before any secondary exists.
  - **On a secondary** the crash comes from that secondary. Whether PSCI SYSTEM_RESET from a secondary resets the board is still UNKNOWN (m2-design A10). If it does not, CPU0's 15 s deadline prints `t234: cpu N start timeout 15 s: stage=00000044 …` and resets from CPU0.
- **Policy `continue`:** print and continue; the stage reaches 0x45. Used only with the owner's approval: an unwired clock then risks a hang and a power cycle.
- **Policy `off`:** no probe, one line, continue.

---

## 5. Images and generator

### 5.1 Why a new generator rather than markers in the M2 template

BOARD M3 proposed adding `@Q@`, `@MS@`, `@M2@` and `@M1B@` markers to `m2.build.in` and teaching `make-m2-images.sh` about them, with a byte gate on the output. This design keeps the byte gate but leaves both M2 files untouched:
- **The record stays exact.** They are the exact sources of the images M2 ran, and a byte gate proves the output identical but not that the record itself is unchanged.
- **Stale comments go away.** About twenty comment lines of the template are M2-specific: the header table, "-P … the only option that differs", "-Q disable drop to EL1 … says nothing about -Q enable", "M2 is a report". Those would need parallel marker variants. Derived M1b buildfiles instead drop comment lines entirely, which mkifs does not compile into the image (§2 rule 3), and carry a generated header.
- **One-variable is visible at a glance.** A plain `diff` of an M1b buildfile against its `reg` twin shows the difference.

The cost is duplicating the IFS build, check and wrap functions of `make-m2-images.sh` (:198-315). Each copy cites its origin lines.

### 5.2 Images

All images use one startup build (§3) and one smpcheck build (§3.10). The script is M2's `-PN` script (m2.build.in:99-174; `N` busy workers, `-R`/`-c` collectors, `-z 3`, `shutdown -S reboot`) with no trace lines. All outputs go to `shim/out/m1b/`, which is git-ignored under `orin-native/shim/out/` (.gitignore:83).

| Image | Startup line (exact) | `display_msg` label | Buildfile | Role |
|---|---|---|---|---|
| `reg-p1` | `startup-t234-orin-nano -vvv -P1 -Q disable -m992M -Wkeep -Dtcu` | `T234 M2 -P1` | byte-identical to `m2-p1.build` | bisect only |
| `reg-p6` | `startup-t234-orin-nano -vvv -P6 -Q disable -m992M -Wkeep -Dtcu` | `T234 M2 -P6` | byte-identical to `m2-p6.build` | **R0** |
| `m1b-p1` | `startup-t234-orin-nano -vvv -P1 -Q enable,el2-host -m992M -Wkeep -Dtcu` | `T234 M1b -P1` | derived from `reg-p1` | **R1** |
| `m1b-p2` | `startup-t234-orin-nano -vvv -P2 -Q enable,el2-host -m992M -Wkeep -Dtcu` | `T234 M1b -P2` | derived from `m2-p2` | bisect only |
| `m1b-p4` | `startup-t234-orin-nano -vvv -P4 -Q enable,el2-host -m992M -Wkeep -Dtcu` | `T234 M1b -P4` | derived from `m2-p4` | cluster-1 degraded fallback |
| `m1b-p6` | `startup-t234-orin-nano -vvv -P6 -Q enable,el2-host -m992M -Wkeep -Dtcu` | `T234 M1b -P6` | derived from `reg-p6` | **R2, R2b** |
| `el1h-p1` | `startup-t234-orin-nano -vvv -P1 -Q enable,el1-host -m992M -Wkeep -Dtcu` | `T234 M1b-el1host -P1` | derived from `reg-p1` | contingency C1 |
| `el1h-p6` | `startup-t234-orin-nano -vvv -P6 -Q enable,el1-host -m992M -Wkeep -Dtcu` | `T234 M1b-el1host -P6` | derived from `reg-p6` | contingency C2 |

Notes on the table:
- **Why `reg-*` keep the label `T234 M2`.** Those buildfiles are M2's, byte for byte. The run note names the image `reg-pN` and records the new startup sha256; the black box's `M2` label plus the new `t234: WDT0 is configured, but …` wording tell the two apart.
- **No `-t`.** No image passes it, so the default `stop` applies under el2-host, and under `-Q disable` and el1-host the probe never runs.
- **The el1-host contingency.**
  - `Enabling EL1 host hypervisor support` is printed. An asinfo `hypervisor_vector` entry is added. Every core drops to EL1 after writing VBAR_EL2 to a RAM table the library allocated (lib/aarch64/hypervisor.c:94-110), and `qtime->intr` is 27 (init_qtime_v8gt.c:58-59).
  - It is **labelled el1-host everywhere, never "VHE"**.
- **`-P5`.** Not built: M2 closed frames 4 and 5 and cluster-1 CPU_ON (m2-runs.md:90-93), and nothing in M1b touches that geometry.

### 5.3 `startup/make-m1b-images.sh`: steps, checks and proof obligations

`BSP=… QNX_BASE=… ./make-m1b-images.sh [--generate-only] [image ...]`, with the same environment handling as make-m2-images.sh:140-186. It stops at the first failure with `FAIL: <step>`, like :45-48.

1. **Refuse the M2 directory.** `OUT="$SHIM/out/m1b"`. Die if `OUT`, resolved, equals `$SHIM/out/m2` or lies under it. Never call `make-m2-images.sh`.
2. **PO-1, M2 source unchanged.** `git diff --quiet -- orin-native/startup/m2.build.in orin-native/startup/make-m2-images.sh` must succeed. It is read-only; die otherwise.
3. **PO-2, M2 expansion reproduces byte for byte.**
   - Expand `m2.build.in` for `m2-p1 m2-p2 m2-p4 m2-p5 m2-p6 m2-p6t` into `$OUT/gate/`, with the awk copied verbatim from make-m2-images.sh:88-99, with `n` and `trace` set as `cpus_of`/`trace_of` at :69-70.
   - sha256 of each must equal the pinned value below (computed 2026-09-10 from `shim/out/m2/*.build`, generated 12:28, whose kimgs match m2-runs.md; VERIFIED). Die on any mismatch.

     | Buildfile | sha256 |
     |---|---|
     | `m2-p1.build` | `040824e3272e7f18b25e7153ff0042d0f5314eb1981efb3d3176a2f0a999443a` |
     | `m2-p2.build` | `8a4d8b5816ad9bb8012e959e4e3dab27352555cc80342020f5df81953c82c99e` |
     | `m2-p4.build` | `2213045eed2d4a78d889b536120635ba407d915e401b5181a582ab4f08592cb7` |
     | `m2-p5.build` | `c268682d67137bb35afcab5ecf7b8459eef16a13f803cd252a8b8168ce38b10c` |
     | `m2-p6.build` | `1830b690ce2722d27c319a2357f5189c3819250f84def58ae2fd610bd3acc7a8` |
     | `m2-p6t.build` | `9cfe1653aeee829ffaf4b100a23b618fc9793662d4d1aca3ca8a233694cb5dff` |

4. **PO-3, the M2 kimgs that ran are still in place (read-only).** If `shim/out/m2/<img>.kimg` exists, the first 24 hex characters of its sha256 must equal m2-runs.md:23-30:

   | kimg | sha256 prefix |
   |---|---|
   | `m2-p1` | `1f5f1331bd2dd11d5799e82d` |
   | `m2-p2` | `6e2ce6b76de95eac8d5260ec` |
   | `m2-p4` | `0a4e20c2c54b1002a4a3d044` |
   | `m2-p5` | `ca5839e104c160594b196f5a` |
   | `m2-p6` | `5cae65e821edcdb9c2355310` |
   | `m2-p6t` | `ffbf7a08eedc8f967fb22de0` |

   A mismatch means something rebuilt M2's images: die and name the file. VERIFIED today.
5. **`reg-pN`.** `cp $OUT/gate/m2-pN.build $OUT/reg-pN.build`, and re-check its sha256 against the pin.
6. **Derive `m1b-pN` and `el1h-pN`** from `$OUT/gate/m2-pN.build`, in one awk pass:
   1. Drop every line whose first non-blank character is `#`.
   2. On the one line whose first field is `startup-t234-orin-nano`, replace the field `disable` that follows `-Q` with `enable,el2-host` (or `enable,el1-host`). Die unless exactly one line has exactly one `-Q disable`.
   3. In lines whose first field is `display_msg`, replace `"T234 M2 -P` with `"T234 M1b -P` (or `"T234 M1b-el1host -P`). Die unless exactly two replacements happen.
   4. Prepend a generated header of `#` lines:
      - the image name and role;
      - "derived from m2-pN.build (sha256 …) by make-m1b-images.sh: comments removed, -Q and the display_msg label changed, nothing else";
      - "per-line rationale: orin-native/startup/m2.build.in";
      - "No image generated from this has run on the board";
      - the design reference `results/orin-native-port/20260909T1100Z/m1b-design.md`.
7. **One-variable gate** for each derived image against its `reg`/`m2` source:
   - Normalise both files: drop comment lines; replace the `-Q` argument with `<Q>`; replace `"T234 <label> -P` with `"T234 <MS> -P`.
   - The normalised streams must be byte-identical (`cmp`).
   - Separately, the raw non-comment `diff` must list exactly three changed lines: the startup line and the two `display_msg` lines.
8. **Checks per image, after mkifs**, copied from make-m2-images.sh and adapted:
   - `mkifs` into `$OUT/<img>.ifs`; keep `procnto-smp-instr.sym` per image (:198-215).
   - `dumpifs -vv` checks as :217-240: uncompressed, one `smpcheck -i -n N`, N busy workers, trace files absent. Add a check that exactly two `display_msg` lines carry the expected label.
   - Startup-argument check as :250-293, plus: exactly one `-Q` argument, equal to the image's expected value, and argv equal to the buildfile's startup line.
9. **Wrap.** `build-shim.sh jump` with `OUT_DIR="$SHIM/out"`, then copy `t234-qnx.kimg` to `$OUT/<img>.kimg` and check that it is 8192 B of shim plus exactly this IFS (as :296-315).
10. **Input stability and table.** The startup and smpcheck sha256 must not change during the run (as :347-351). Print a table of image, `-P`, `-Q`, kimg bytes and sha256, IFS sha256, and the startup and smpcheck sha256.
11. **Symbol precondition.** Before mkifs, `ntoaarch64-nm` on the startup must show `t234_hvt_probe`, `t234_install_el2_vectors` and exactly one defined `board_init`. That repeats §3.9, so an image cannot be built from a startup that skipped the gate.

`--generate-only` runs steps 1-7 only; it needs no SDP beyond git and sha256sum.

---

## 6. Run ladder and procedure

### 6.1 Build (PC)

1. `BSP=C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp QNX_BASE=/c/Users/<user>/qnx800 ./orin-native/startup/build-board.sh`. The symbol gate must pass, including the new `board_init` count, and the libc member list is recorded.
2. `make -C orin-native/tools` in the SDP environment (tools/Makefile).
3. `./orin-native/startup/make-m1b-images.sh` with the same `BSP` and `QNX_BASE`. It builds all eight images, and PO-1..PO-3 must pass.
4. Record in the run note:
   - the startup sha256 and smpcheck sha256, which are the same for every rung (rule 3);
   - each kimg sha256;
   - the PO results.

### 6.2 Each run (one image), the loop M2 used

1. **PC.** Stop any previous COM3 capture, because COM3 is exclusive. Start a new capture **from PowerShell** (115200 8N1, J14 debug header) into `com3-<image>-<utc>.log` before kexec, and keep it running until L4T is back. A Git Bash background capture received nothing during M2 (m2-runs.md:135-137).
2. **PC.** `scp shim/out/m1b/<image>.kimg <user>@<orin-ip>:~/` with `~/.ssh/<orin-key>`. The IP is DHCP; scan the /24 if it has moved.
3. **Board, before kexec:**
   - `sha256sum ~/<image>.kimg` must equal the PC value.
   - Record `cat /proc/sys/kernel/random/boot_id`.
   - Record `uptime`. If L4T has been up for about two hours or more, reboot it first: Linux faulted in its own kexec shutdown at 2 h 25 min during M2 (m2-runs.md:126-133). The threshold is a HYPOTHESIS from one event.
4. **Board.** `sudo -n kexec -s -l ~/<image>.kimg && sudo -n systemctl kexec`.
5. **PC.** Poll ssh with `-o ServerAliveInterval=3 -o ServerAliveCountMax=2` under `timeout`, until it answers **and** `boot_id` differs from step 3. Give up 10 minutes after kexec.
6. **Board, after return:**
   - `sudo -n cat /sys/fs/pstore/console-ramoops-0 > ~/<image>-blackbox.log`, and record its size.
   - Read `/sys/devices/platform/bus@0/c360000.pmc/reset_reason`: `MAINSWRST` is the image's own reset, `BCCPLEXWDT` the watchdog.
   - Check for `T234-SHIM` in the black box and for new `dmesg-ramoops-*` records. No shim text plus a new Oops or Panic means Linux died before the jump: retry from a fresh boot and do not judge the image.
   - Copy the black box and the COM3 log to `results/orin-native-port/<utc>/` (private, NC QDL 4.6(i)).
7. **No return within the bound.** Read COM3 first: with nothing resetting, the TCU drains fully. Then a human power cycle. Record that the black box was lost.
8. **Run note:**
   - sha256s, the startup line as the IFS carries it, both `boot_id`s;
   - the last 30 lines of each log, black-box size, PMC reason;
   - every `t234: hvtimer` verdict line and every `el2-host` line;
   - a verdict against §8.

### 6.3 Order and gates

| Run | Image | Pass means | Then | On fail |
|---|---|---|---|---|
| **R0** | `reg-p6` | **`-Q disable` regression.** M2's §8 criteria 1-8 as in R4 (m2-runs.md:40-60), plus: `SMPCHECK census hyp qtime_intr=27 hypinfo_flags=0x0`; `SMPCHECK census tick=ok ms=` in [90, 2000]; `t234: WDT0 is configured, but it did not fire …`; **no** `t234: hvtimer` line and **no** `el2-host` line; L4T returns with `MAINSWRST`. | G1 | Regression in the new board or smpcheck code. Run `reg-p1` to bisect -P, fix, rebuild all images. No el2-host run until R0 passes. |
| **G1** | desk | `size(R0) + 6 × 700 + 1,000 < 60,000` bytes (cap 65,520, t234_startup.h:116-117). | R1 | Rebuild the M1b images at `-vv` and record the deviation (a second variable; owner decision). |
| **R1** | `m1b-p1` | §8 for N=1. This is the plan's M1b: VHE line, `hvtimer cpu 0 verdict=wired`, `intr:28`, procnto and user space at EL2, `tick=ok`, one worker's timer checks. | R2 | §7. An `absent` or `secure-group` verdict on cpu 0 settles unknown #3 as not usable: record it, then run **C1**. `inconclusive`: §7 row, owner decision on a `-tcontinue` run. A hang after `Starting next program`: COM3, then §7. |
| **R2** | `m1b-p6` | §8 for N=6 (§8 criterion 2 adds five `entry EL2` pairs; the first CPU_ON issued from EL2). | R2b | §7. A named secondary: its row. A `STOP` on cpu 4 or 5 only: run **C4**, `m1b-p4`. A procnto-time hang with no CPU named: run **C3**, `m1b-p2`. |
| **R2b** | `m1b-p6` | The same as R2 with the identical image: a repeat that rules out a first-run fluke, not a reliability claim. | **M1b met** | Report as intermittent, with both logs. |

**Contingencies** (built, not run unless the named branch occurs):

| Run | Image | When | Pass means | Record as |
|---|---|---|---|---|
| C1 | `el1h-p1` | INTID 28 not usable on cpu 0 (R1 `STOP` with `absent`) | `Enabling EL1 host hypervisor support`, `intr:27`, hypinfo `flags:…1`, M2's -P1 criteria, `tick=ok` | "M1b el1-host (not VHE)", then C2 |
| C2 | `el1h-p6` | C1 passed | M2 §8 for N=6 plus the C1 lines | **M1b degraded: el1-host, every later number relabelled** (plan K8 fallback). If it fails too, plan kill criterion (c) (plan:73-74) |
| C3 | `m1b-p2` | R2 hangs after `Starting next program` without naming a core | §8 for N=2 | Bisect result only |
| C4 | `m1b-p4` | R2 stops on cluster 1 only (cpu 4 or 5) | §8 for N=4 | "M1b degraded (4 cores, el2-host)": owner decision against C2 |
| C5 | `reg-p1` | R0 fails | M2's R0 criteria (m2-design.md §6) plus R0's new lines for N=1 | Bisect result only |

Each run takes about 150 s from kexec to L4T (m2-runs.md:24-30). The required ladder is four runs.

---

## 7. Failure-signature table (el2-host, and R0 regressions)

Each row is keyed on the last distinctive line in the black box or on COM3. M2's own rows (m2-design.md §7) still apply to the secondary path and are not repeated; the rows below are the new or changed ones.

**Before and around `hypervisor_init` (CPU0)**

| Observable | Meaning | Next step |
|---|---|---|
| Black box ends at the shim's `JUMP`, then a warm reset (PMC `MAINSWRST`), with no startup text | A fault between `board_init` and `select_debug`: the board EL2 table reset without printing. Or a fault in `_main` before `board_init`, where the shim's handler runs with x21 and x22 overwritten and prints to neither channel (§1 C5, derived). Or a fault in the preboot stub, `cstart` or `at_el2`, if the stub did not preserve x21-x23 (UNKNOWN) | The path up to `board_init` is identical to M1/M2; reproduce with `reg-p1`. If `reg-p1` passes, suspect the new `board_init` or option parsing (`-t` crash text cannot print that early either). addr2line is impossible without an ELR, so bisect by removing the stage writes |
| Black box ends at `JUMP`, then the shim's `EXC 000000000000000N ESR=… ELR=… FAR=…`, then a warm reset | A fault after the jump and before `_main` overwrote x21/x22: in `cstart`, `_start_el2_or_el1`/`at_el2` or `aarch64_cache_flush`, or in the preboot stub, which then preserved x21-x23 (§1 C5) | The same code as every M1/M2 run; reproduce with `reg-p1`. An ELR inside the startup: addr2line on the keeplinked startup. An ELR inside the image's `*.boot` preboot stub (M2: [0x80082000, 0x80082fa0), `shim/out/m2/m2-p6.dumpifs.txt:2`; an M1b image's own dumpifs gives its range): record the address only, because the stub is a QNX binary and is never disassembled |
| Black box ends at `JUMP`, no reset, power cycle needed | Hang before `board_init` (shim vectors live). A fault loop there needs the preboot stub to have left x21-x23 pointing somewhere that faults (UNKNOWN); with `_main`'s values the handler resets (§1 C5) | Residual R19. COM3's last bytes; compare with M2 R4's first startup lines |
| `t234: -tX is not stop, continue or off` | Buildfile typo in `-t` | Fix the buildfile; no ladder image passes `-t` |
| `Unrecognized hypervisor option flag` | `-Q` string not one of the four the library knows (lib/aarch64/cpu_common_options.c:107-118) | Generator step 8 should have caught it; check the image's startup arguments |
| `Hypervisor support requested but CPU has no EL2 support` | CPU0 not at EL2 at `hypervisor_init` | Compare the shim bank `EL=` and the stage (0x03); something between the jump and `hypervisor_init` dropped EL, which no source path does |
| `Hypervisor EL2 Host requested but CPU does not support this` | `ID_AA64MMFR1_EL1.VH` read 0 on CPU0 | Contradicts M2's `MMFR1=0000000010212122` (m2log:21, :210); record the bank; C1 |
| `t234: EL2 FP/SIMD access trap on MPIDR=0000000081000000 … EC=00000007 … HCR_EL2=00000304a8000000 stage=0000000N` | FP/SIMD instruction at EL2 after E2H=1 (CPTR_EL2.FPEN=00): most likely an SDP `libc.a` routine (§1 C12) | addr2line ELR on the keeplinked startup and name the function from the map. Enabling FPEN would be a new state variable, so that is an owner decision. Never disassemble the libc routine |
| `t234: EL2 system register trap … EC=00000018 … stage=…` (CPU0) | A system-register access trapped to EL2, or from EL2 to EL3, in startup at E2H=1 | addr2line ELR; the stage names the step. Compare with the same step under `-Q disable` (R0) |
| `t234: EL2 data abort … HCR_EL2=…4a8000000 stage=0000000N` | Startup C fault in the VHE host; stage 0x04-0x0a names the step | addr2line ELR; FAR names the address |
| `t234: EL2 … HCR_EL2=…a0000000 stage=00000002/03` (E2H clear) | Fault before `hypervisor_init` | The same code runs under `-Q disable`; compare with R0 |

**The el2-host check and the probe (any core)**

| Observable | Meaning | Next step |
|---|---|---|
| `t234: cpu N el2-host requested but running at ELx, stopping` | That core is not at EL2 after its `hypervisor_init` | For a secondary, compare its `entry EL` line; record. The library should have crashed first (lib/aarch64/hypervisor.c:38-44) |
| `t234: cpu N el2-host requested but HCR_EL2=…: E2H and TGE must both be set, stopping` | `hyp_enable_el2_host`'s write did not take, or something cleared it | Record HCR; firmware trapping HCR writes is UNKNOWN; owner decision (C1) |
| `t234: hvtimer cpu 0 verdict=wired reason=ok …` | INTID 28 wired on CPU0 (NS view) | Continue |
| `t234: hvtimer cpu N verdict=wired reason=control-failed …` | 28 proven wired, but the INTID 26 control did not show the expected rise/fall | Continue. Record the CNTHP line as an anomaly: 26 is Linux's own EL2 timer, so the anomaly concerns the control, not 28 |
| `t234: hvtimer STOP cpu 0 verdict=absent reason=no-ppi` | CNTHV's condition was met and the control passed, but no PPI rose: **INTID 28 is not wired on CPU0** | Settles unknown #3 as absent. Record verbatim, run C1 then C2 |
| `… verdict=absent reason=ppiNN` | CNTHV drives INTID NN, not 28 | Record: a finding in itself. procnto would still be told 28. C1/C2; whether to override `qtime->intr` is an owner decision, outside M1b |
| `… verdict=absent reason=secure-group` | 28's priority reads 0 from NS while 26's does not: firmware left 28 Secure | Record; unusable from NS EL2 either way. C1/C2 |
| `… verdict=inconclusive reason=hv-istatus` | CNTHV never met its condition within 100 ms: timer not counting or CVAL wrong | Compare with the CNTHP line; if CNTHP's `istatus=1`, the EL2 virtual timer itself is suspect. Owner decision: `-tcontinue` run (hang risk) or C1 |
| `… reason=control` | Neither the control nor 28 showed a pending rise | The readback mechanism is unproven on this core (frame, NS visibility of pending, GIC-600 level tracking). Record raw lines; owner decision |
| `… reason=no-deassert` | 28 rose but stayed pending after IMASK on a level PPI | Record; possible second source on 28. Owner decision |
| `… reason=prio` / `stuck` / `asleep` / `daif` | Guard failed | `prio`: the priority rule does not match the spec on this GIC, so record `ctx`. `stuck`: pending left from firmware or Linux, see the `base=` value. `asleep`: see the wrapper's WAKER. `daif`: a code-path bug |
| `t234: hvtimer STOP cpu 4` or `cpu 5` only (after cpu 0-3 `wired`) | Cluster 1 differs | C4 (`m1b-p4`); owner decision |
| `t234: cpu N start timeout 15 s: stage=00000044 …` after the secondary's `hvtimer … STOP` | PSCI SYSTEM_RESET from a secondary did not reset (M2 A10); CPU0's backstop fired | Record as a firmware fact; the probe line above is the result |
| `t234: cpu N start timeout 15 s: stage=00000044` with no hvtimer verdict for N | Secondary hung inside the probe (a sysreg access or MMIO) | Last printed `t234: hvtimer cpu N` line names the step; owner decision on a `-toff` run to separate the probe from the rest |
| `Hypervisor setup: cpu <garbage>, does not match cpu 0 capability` | A secondary's VH field differs from CPU0's | The preceding `t234: cpu N entry EL2` lines name the core (C7); record MMFR1 |

**Secondaries under el2-host (changed or new)**

| Observable | Meaning | Next step |
|---|---|---|
| `t234: cpu N entry EL2 … HCR_EL2=` value other than `0000000080000000`, or `SCTLR_EL2`/`MDCR_EL2` differing from M2 (m2log:57-58) | Firmware entry state for a CPU_ON **issued from EL2** differs from one issued from EL1 | Record as data; `ap_entry.S` normalises anyway. Stop only if a later row fails |
| `t234: cpu N entered at EL1 …` | Firmware entered a CPU_ON issued from EL2 at EL1 | As M2's row: stop, record, read T234 TF-A before allowing it |
| `t234: EL2 … on MPIDR=0x810xxxxx … HCR_EL2=…4a8000000 stage=0000004x` | Secondary EL2 fault in the VHE host during the GIC wrapper or probe | addr2line ELR; the stage names the step |
| `t234: cpu N released but smp.pending still set after 5 s` | Secondary died in `cpu_startnext`/`vstart`/`smp_spin` at EL2 (EL2&0 MMU enabled through E2H redirection) | Compare with M2 (EL1); suspect the SCTLR_EL2/TCR_EL2 layout under E2H (LIBRARY Q4-02, VENDOR_CLAIM) |

**Kernel and user space**

| Observable | Meaning | Next step |
|---|---|---|
| `Starting next program`, then a warm reset with no text | A core faulted after `vstart` and the board EL2 table's MMU-on guard reset it | COM3's last lines; one run lower in `-P` (C3); nothing more is observable |
| `Starting next program` (+/- `syspage::hypinfo::flags=0x00000001`), then silence, no reset, power cycle | procnto hang at EL2 before user space: clock, per-CPU data (TPIDR, R5), its own EL2 vectors | COM3 tail. If R1 (N=1): owner decision on a `-F0x10000` failure-branch rebuild (one variable), then C1. If R2 only: C3 |
| `syspage::hypinfo::flags=0x00000000` under an M1b image | procnto did not see the hypervisor flag | Check the image's `-Q` and startup's hypinfo print; wrong image |
| `T234 M1b -PN: procnto up`, then silence before any `SMPCHECK census` line | User space stalled before the census, e.g. `devc-pty` or `pidin info` on a dead tick (residual R9) | COM3; power cycle; treat as `tick=dead` and follow that row |
| `SMPCHECK census hyp qtime_intr=27 …` under `m1b-*` | The image did not run el2-host | Check the startup args in the run note and generator step 8 |
| `SMPCHECK census tick=dead …`, then `SMPCHECK tick dead: calling sysmgr_reboot …`, then a reset | **procnto's clock on CPU0 never fired although the probe showed INTID 28 wired**: the kernel's EL2 timer path (which register it programs, or whether it unmasks 28) | Record verbatim. Owner decision: a `-F0x10000` failure-branch rebuild, or C1. If no reset follows, `sysmgr_reboot` needs a tick too: power cycle, and record that |
| `SMPCHECK sysmgr_reboot returned …` | The reboot request was refused | Record errno; power cycle |
| `SMPCHECK census tick=bad ms=…` | The clock fires, but a 100 ms sleep is out of [90, 2000] ms | Record; compare `cps` in the census line with `CPS:` in the syspage |
| `SMPCHECK ready cpu=i … timer0_ms=` missing or over 2000, for a secondary i only | Per-core timer not delivered on that core under the VHE host, with CPU0's clock fine | Suspect the PPI unmask path (TPIDR_EL1-indexed callouts, R5). Record which cores; C3/C4 |
| `SMPCHECK RESULT FAIL …` then a clean reset | A criterion failed, fully recorded | Per its reasons, as in M2 |
| `shutdown -S reboot` printed, then no reset | Reboot callout at EL2 did not reach PSCI | COM3; power cycle; `reboot_psci_smc` issues an SMC that EL2 cannot trap (lib/aarch64/callout_reboot_psci.S:42-58), so suspect procnto's path to the callout |
| R0 (`-Q disable`) differs from M2 R4 anywhere except the lines listed in §6.3 | A regression in the new code on the proven path | Fix before any el2-host run; C5 |

---

## 8. M1b pass criteria (observable in the black box)

**R1 (`m1b-p1`, N=1)** and **R2/R2b (`m1b-p6`, N=6)** pass when all of the following appear in one run, and nothing from §7's failure rows does.

1. **VHE line.** `Enabling EL2 host hypervisor support (VHE)`, once (CPU0; lib/aarch64/hypervisor.c:89-91). `Hypervisor support disabled` must not appear.
2. **Secondary entry (N=6 only).** For N = 1..5, a `t234: cpu N entry EL2 …` and `t234: cpu N fw …` pair.
   - The entry EL must be 2.
   - The register values are recorded data, the first measurement of a CPU_ON issued from EL2, not criteria.
3. **Per core, for every N in 0..N-1, in this order:**
   - `t234: cpu N up MPIDR=… GICR=… idx=… SGI1R=…` with M2's values (m2-design.md §8 criterion 1) and no `MISMATCH`;
   - `t234: cpu N el2-host EL2 HCR_EL2=%L` with bit 34 (E2H) and bit 27 (TGE) set. Expected `00000304a8000000` (C11); any other value with both bits set is recorded, not a fail;
   - `t234: hvtimer cpu N verdict=wired reason=ok residue=… qtime_intr=28`. `reason=control-failed` is accepted as wired and recorded as an anomaly.
4. **Syspage dump:**
   - qtime section `… intr:28` (lib/print_sysp.c:211-216);
   - hypinfo section `flags:0000000000000001` (lib/print_sysp.c:351; lib/hypervisor_setup.c:86-87);
   - cpuinfo `flg:` recorded; it is expected to equal M2's `c0f08c7a` (m2log:141), since nothing sets `AARCH64_CPU_FLAG_VHE`.
5. **Hand-off.**
   - For N=6: `t234: all 6 cpus parked in smp_spin`.
   - For every N: `System page at phys:`, then `Starting next program`.
   - Corroboration, not a criterion: `syspage::hypinfo::flags=0x00000001`. It is printed between `Starting next program` and the script and is not in the library or board source (grep), so it is HYPOTHESIS that procnto prints it.
6. **Kernel and user space up.** `T234 M1b -PN: procnto up`; `pidin info` with N Processor lines.
7. **Census:**
   - `SMPCHECK census hyp qtime_intr=28 hypinfo_flags=0x1`;
   - `SMPCHECK census tick=ok ms=` with ms in [90, 2000];
   - the M2 rows `SMPCHECK cpu i … ok`;
   - `SMPCHECK CENSUS PASS`.
8. **Load.**
   - N=6: `SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`.
   - N=1: `SMPCHECK RESULT PASS-DEGRADED cpus=1/6 secs=60 reasons=none`, the same shape as M2's R0.
   - Every `SMPCHECK ready` line shows `timer0_ms` within [90, 2000] on the worker's own core.
9. **Reset.** `T234 M1b -PN: resetting so the log can be recovered`, then L4T answers with a new `boot_id`, PMC `reset_reason` is `MAINSWRST`, and the black box is intact.
10. **None of these tokens:**
    - fault and stop lines: `t234: EL1`, `t234: EL2`, `hvtimer STOP`, `el2-host requested but`, `continuing despite`, `probe off`;
    - library and startup failures: `ASSERT`, `start failure`, `start timeout`, `released but`, `entered at EL1`, `wake timeout`, `not awake`, `transfer hook ran`, `PE is not awake`, `does not match cpu 0`;
    - smpcheck failures: `tick=dead`, `tick=bad`, `CENSUS FAIL`, `RESULT FAIL`.

**M1b is met** when R1, R2 and R2b pass.

**Other outcomes are recorded as:**
- R1 passes and R2 fails on cluster 1 only, while C4 passes: **M1b degraded (4 cores, el2-host)**.
- INTID 28 is not usable on CPU0 and C1/C2 pass: **M1b degraded: el1-host, not VHE**.
- Neither records as M1b.

**R0 passes** on M2's §8 criteria 1-8 (as in R4) plus exactly the lines in §6.3's R0 row. Any other difference from `m2log` is a regression. Timestamps, counters, addresses that depend on the startup's size, and the new WDT0 wording are expected.

---

## 9. Risks: every HYPOTHESIS or UNKNOWN the design rests on, and the run that answers it

| # | Assumption | Class | Answered by / handled how |
|---|---|---|---|
| R1 | INTID 28 is wired to CNTHV on each core | UNKNOWN (plan §8 #3; no DT entry; prior art of silicon without it, PROBE G3) | R1 on cpu 0, R2 on all six; the probe stops the run by name otherwise |
| R2 | A disabled level-sensitive PPI shows pending in `GICR_ISPENDR0` while its input is asserted, and clears when it deasserts | VENDOR_CLAIM (GICv3 §4.1.2, §12.11.5) | INTID 26 control in the same probe; `reason=control` if not |
| R3 | NS priority readback of 0 means Group 0 or Secure Group 1 | VENDOR_CLAIM (§12.11.19) | Printed `prio26`/`prio28`; the rule is applied only when `prio26 ≠ 0` |
| R4 | CNTHV and CNTHP count and assert at EL2 with E2H=1 against CNTPCT with offset 0 | VENDOR_CLAIM (Arm register XML; PROBE A2, A3, D1) | CNTHP `istatus`/`t_ms` in the probe; `hv-istatus` otherwise |
| R5 | procnto at EL2 keeps the per-CPU GICR index encoding in TPIDR_EL1, which the PPI mask/unmask callouts read | UNKNOWN (lib/aarch64/callout_interrupt_gic_v3.S:187, :238; procnto is a binary) | R2's per-worker `timer0_ms` on cpus 1-5; the §7 row names it |
| R6 | procnto attaches its clock through `qtime->intr` and programs the timer through the `CNTV_*` names (so CNTHV at EL2) | HYPOTHESIS (the library's 27/28 pairing, init_qtime_v8gt.c:56-66; QEMU reverted-wiring evidence, docs/findings.md:203-212) | Census `tick=ok` in R1; `tick=dead` with `wired` refutes it |
| R7 | procnto at el2-host needs no `AARCH64_CPU_FLAG_VHE` (`-F0x10000`) | HYPOTHESIS (cloud QHV host ran `-Q enable` on `-cpu max` without `-F`; whether `startup-qemu-virt` sets the flag itself is UNKNOWN) | R1 reaching user space; failure branch in §7 |
| R8 | No SDP `libc.a` routine linked into startup uses FP/SIMD while FPEN=00 at EL2 | UNKNOWN (not inspectable; C12) | R1/R2 run through; EC 0x07 is named |
| R9 | With a dead tick, the script still reaches `smpcheck -i` (after `devc-pty`, `pidin info`) | HYPOTHESIS (QEMU: user space ran until its first timed wait, nohypvirt log:9-20) | Only observable if the tick is dead; COM3 otherwise |
| R10 | `sysmgr_reboot()` resets without a working tick | UNKNOWN | Only if `tick=dead`; power cycle otherwise |
| R11 | PSCI SYSTEM_RESET issued from a secondary resets the board | UNKNOWN (m2-design A10, still unobserved) | Any secondary `STOP`; CPU0's 15 s backstop covers it |
| R12 | A CPU_ON issued from EL2 with E2H=1 enters the secondary at EL2 with the M2 register state | HYPOTHESIS (upstream TF-A picks the entry EL from SCR_EL3, not the caller; T234 fork unread) | R2 `entry EL2`/`fw` lines; EL1 entry stops by name |
| R13 | Under E2H=1, vstart's EL1-named writes produce a working EL2&0 MMU from the same values | VENDOR_CLAIM (Arm ARM redirection; LIBRARY Q4-02); prior art: the cloud QHV host with the same library under TCG | R1 `Starting next program` followed by procnto output; the MMU-on guard resets otherwise |
| R14 | The library's GIC CPU-interface writes (`ICC_*_EL1`) configure the physical interface used by NS EL2, including EOImode and group enable | VENDOR_CLAIM (LIBRARY Q6-03) | R1 tick and IPIs (R2 load) |
| R15 | procnto installs its own VBAR_EL2 before it removes the TTBR0 identity map | UNKNOWN (binary) | Not observable except as a reset-without-text after `Starting next program`; residual |
| R16 | `shutdown -S reboot` reaches the reboot callout at EL2 | HYPOTHESIS (SMC from EL2 always reaches EL3, VENDOR_CLAIM; callout source VERIFIED) | R1 criterion 9 |
| R17 | Black-box budget at `-vvv -P6` with the probe lines | HYPOTHESIS (~24 KB estimate) | Gate G1 from R0 |
| R18 | EL0 `CNTVCT_EL0` stays readable under E2H=1: `cntkctl_el1=2` lands in CNTHCTL_EL2 as EL0VCTEN (lib/aarch64/init_cpuinfo.c:225) | VENDOR_CLAIM (field layout, LIBRARY Q2-05) | R1: smpcheck uses `ClockCycles()` from its first line |
| R19 | The mkifs preboot stub and `_main` before `board_init` do not fault or loop | HYPOTHESIS: the same code and entry state ran in every M1 and M2 run that reached QNX without a fault here; the stub is a QNX binary and is never inspected. If one does fault, §1 C5 predicts the black box: the shim's `EXC …` before `_main`'s x22/x21 writes (if the stub preserved them), no text after | Residual; §7's first three rows |
| R20 | `t234_el2_vectors` stays inside the startup identity map in the new build | VERIFIED for M2's build (§3.2); the new build keeps it in `.text` | build-board.sh presence gate; nothing more is needed |
| R21 | Under el1-host (C1/C2), no EL2 exception occurs between `hyp_enable_el1_host` (VBAR_EL2 set to uninitialised RAM, lib/aarch64/hypervisor.c:101-108) and procnto | HYPOTHESIS (no HVC in any board or library path used; `psci_smc` only) | C1 only; a silent hang would name it |
| R22 | The 2 h uptime precaution avoids Linux's kexec-shutdown panic | HYPOTHESIS (one event) | Shim text absent plus a new Oops, per §6.2 step 6 |
| R23 | A generated M1b buildfile without comments compiles to the same script as the M2 one, apart from the labels | VERIFIED for comments (`m2-p6.dumpifs.txt` shows no `#` lines); the label change is checked by generator step 8 | Build time |

---

## 10. Must not be claimed from a pass

**What did not run or was not observed**
- **No hypervisor workload.** Nothing about qvm, a guest, stage-2 translation, a virtual GIC, guest timers, HVC or world switches. `HCR_EL2.HCD` stays set and `VTTBR_EL2` stays 0 (lib/aarch64/_start_el1.S:152, :181). All of that is M3.
- **No safety property.** Not isolation, not an ASIL property, not a certified or production configuration.
- **Not which PPI served each secondary's timer.** A pass shows `qtime->intr = 28`, CPU0's kernel clock ticking, and 100 ms sleeps returning on each worker's own core. That procnto uses INTID 28 on cpus 1-5 is inferred, not observed.
- **Not SMP-safety of the kernel-time console.**

**Limits of the INTID 28 result**
- **Only the NS view, this SKU, this firmware.** Not that INTID 28 is wired in the Secure view, on other Tegra234 SKUs, or on firmware other than L4T R36.4.7.
- **Only bits 0-31 were watched.** Not that CNTHV reaches no other interrupt: only SGI/PPI bits 0-31 of this core's `ISPENDR0` were watched.

**Measurement limits**
- **No timing or performance figure.** The tick `ms`, `t_ms` and busy rates are uncontrolled (DVFS, and the cluster-1 rate open since M2).
- **Not reliability or a soak.** One 60 s load per run, n=2 at `-P6`.
- **Not that the CPU_ON entry state generalises.** The state for a CPU_ON issued from EL2 holds only for this firmware and this path.

**What the startup is, and what it changed**
- **Not that the library runs unmodified.** The board overrides `board_init`, the CPU_ON entry point, `transfer_aps` (through `smp_hook_rtn`) and `gic_cpu_init`, and the RWP patch remains.
- **Not that startup leaves the EL2 timers untouched.** The probe arms and disarms both EL2 timers on every core. It restores both CVALs and leaves both controls 0, but procnto inherits a system that ran the probe.
- **Not that `AARCH64_CPU_FLAG_VHE` is unnecessary in general.** A pass shows only that this workload ran without it.
- **Not VHE if the el1-host contingency was used.** Every number from `el1h-*` is an el1-host number.

**Recovery coverage**
- **Not that every failure is recoverable.** The windows before `board_init` and after procnto takes over are residual (R15, R19), and a hang still costs a power cycle.
- **Not that the kexec round trip is watchdog-recoverable.**

**Publication.** Not publishable before the supervising professor is consulted (NC QDL v7 4.6(i)).

---

## 11. Stale text to correct later (list only; the orchestrator edits docs)

**`docs/orin-native-port-plan.md`**

Watchdog wording:
- **§0 item 1 (plan:31-32).** "every experiment has a ~2-minute ceiling. The `-W` policy stops being optional for M3/M4". The later sentence in the same item already says it does not fire.
- **K9 (plan:92).** "startup's `-W` policy becomes mandatory for M3/M4; every experiment is assumed to have ~2 min unless proven otherwise".
- **§3.3 step 5 (plan:152-153).** "WDT0 is already armed and counting at 2 min".
- **§4.1 (plan:233).** "That ceiling is now in tension with the ~2-minute watchdog window (K9)".
- **M1 pass (plan:324).** "If the watchdog stays armed across kexec, each attempt has ~2 min".
- **M3 (plan:354-356).** "`-Wdisable` or a `wdtkick` kicker — mandatory (K9): guest boot plus a trace capture does not fit in 2 minutes".
- **§7 item 8 (plan:415-416).** "with a 2-minute watchdog window there is no soak".
- **§8 #4 row (plan:428).** Consequence column "or a hard 2-min cap on M3/M4".

The INTID 28 probe:
- **K8 (plan:91).** `GICR_ISPENDR0 bit 28 at 0xF450220` should read `0x0F450200`; the `-t` probe and the `HV-timer PPI28: wired|absent` token are replaced by the automatic el2-host probe and its `t234: hvtimer cpu N verdict=` line (§4.5).
- **M1 step 5 (plan:319).** `HV-timer PPI28: wired|absent` (same replacement).
- **Kill criterion (c) (plan:73-74).** "The `-t` probe says INTID 28 absent" should become the el2-host probe verdict.
- **M3 (plan:354).** "or `el1-host` per the `-t` verdict" becomes "per the M1b probe verdict".

The shim vectors and the M1b step:
- **§3.3 step 1 (plan:140-143).** The shim vectors "stay live through startup". Wrong: their printer needs registers C code reuses, and after this design CPU0 replaces them in `board_init`.
- **M1 step 6 (plan:319-320).** "Iterate on faults via the shim vectors"; step 7, M1b as "`-Q enable,el2-host -P1`" only, becomes the R0-R2b ladder with the M2 payload.

**`results/orin-native-port/20260909T1100Z/synthesis-plan.md`** (historical input; correct or annotate):
- :23, :182, :209, :232, :261 name the probe option `-T` (the code uses `-t`, and `T` is a common option);
- :209 gives `0xF450220`.

**Non-docs files kept as historical records in M1b** (rule 2 keeps the shim unedited):
- `orin-native/startup/m1.build:29-31`: "M1b re-runs the identical image with -Q enable,el2-host". M1b uses a new startup and the M2 payload.
- `orin-native/startup/m1.build:34-35`: "-Wkeep … the only thing that returns the board unattended, and M1 fits inside two minutes".
- `orin-native/shim/t234-shim.S`:
  - :208-210, :370-373 and :416-419: the two-minute watchdog;
  - :497-500: vectors "stay installed all the way through QNX startup … an early fault inside startup still prints here".

  Correct these with the next shim rebuild that happens for another reason.

---

## 12. Review outcomes (revision 2)

Three review lenses read revision 1. ARCH_SPEC and RUNNABILITY approved it with no issues. FAILURE_HANDLING approved it with one minor change. Each row below was checked against library source, our own objects or the link map before its disposition was chosen. No run in the ladder (§6.3), no pass criterion (§8), no image (§5.2) and no probe step (§4) changed.

| # | Lens | Severity | Issue | Disposition | Why |
|---|---|---|---|---|---|
| V1 | FAILURE_HANDLING | minor | C5 and the §2 CPU0 timeline row 1 misstate when the shim's printer registers x21-x23 stop being valid. The review asks for the pre-`_main` part to be VERIFIED rather than HYPOTHESIS, citing `lib/aarch64/_start_el1.S:225` (`mov x21, x30`) as reached inside `_start_el2_or_el1`/`at_el2` before `_main`, and gives cstart's path as `orin-native/startup/t234-orin-nano/aarch64/cstart.S`. | **Applied, on corrected evidence.** The `:225` sub-claim and the cstart path are **rejected**. | **The conclusion holds.** `_main`, the first C code, writes x22 (`adrp x22, boot_args`, object offset 0x14) and x21 (`add x21, x22`, 0x18) before `bl board_init` (0x70). Source: objdump of `lib/aarch64/a.le/_main.o`, our compile of Apache-2.0 source and byte-identical to the linked member (sha256 f09f6557…, extracted with `ar x`). So the `_main` part of §1 C5 is now VERIFIED, and the shim's printer cannot be relied on from 0x18 up to `board_init`. **The cited evidence does not hold.** `_start_el1.S:225` is the first instruction of `_start_el1` (:223-232), and `_start_el1` has no caller in the library or the board (grep). cstart calls `_start_el2_or_el1` (lib/aarch64/cstart.S:70), as does smp_start.S:37. That routine keeps LR in x20 (:54, :196). Together with `at_el2`, `is_pauth_supported` (:247-260) and `aarch64_cache_flush` (aarch64_cache_flush.S:34-75), it writes none of x21-x23. `_start_el1` is linked only as a co-member of that object (`bsp-le/startup-t234-orin-nano.map:131-132`). So "x21 is lost before `_main` or any C code runs" is wrong for the library assembly; only the QNX preboot stub is UNKNOWN. The path `orin-native/startup/t234-orin-nano/aarch64/cstart.S` does not exist (listing): the startup links `lib/aarch64/cstart.S` (map :27). **Beyond the requested fix:** splitting the window changes how a silent trace reads. A fault before `_main`'s writes prints the shim's `EXC` line if the stub preserved the registers; revision 1's §7 had no row for that. A fault after them prints nothing (derived from t234-shim.S:404-408, :424-434). |
| S1 | verification (self-found while checking V1; not raised by a reviewer) | minor | Revision 1 cited `board/aarch64/le/main.o` and `board/aarch64/le/startup-t234-orin-nano.map:251-287`. C12's libc list also omitted `xctype` and `__progname`. | **Applied** | build-board.sh stages the board into the BSP tree (:71-74) and builds there (:102-104). The repo's `board/aarch64/le/` holds only a Makefile (listing). The libc archive-member lines run :251-290, and `xctype` is at :289-290. A `bsp-le/` prefix was added and the licence line and C12 corrected. Revision 1's `main.o` offsets (+0x10, +0x14, +0x5c, +0x6c/+0x70) were re-read against the current build and are unchanged. §3.9's "`$MAP` beside `$OUT`" was already right (build-board.sh:104). |

**Edited for V1:** the header; §0 item 1 (second bullet); §1 C5 and C6; §2 CPU0 timeline (first row split in two); the §3.2 install-routine comment; §7's first rows (the no-text row widened, a new shim-`EXC` row, and the no-reset row reworded); §9 R19. **Edited for S1:** the path prefixes, the licence line, §1 C12.
