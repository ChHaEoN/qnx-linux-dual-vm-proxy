# M4 design: per-exit hypervisor dwell from qvm Class-10 trace events, natively on the Jetson Orin Nano

Phase 3b. Architect pass, revision 2, 2026-09-11. Two reviews of revision 1 raised two blockers, two majors and four minors; §13 gives each outcome. This is a read-and-reason design: nothing in it has been built or run, on the board or under TCG. It follows the structure and failure-handling rules of [m3-design.md](m3-design.md), whose runs met M3, and it carries forward [m4-dryrun-design.md](m4-dryrun-design.md) §8 and §13 (checklist 7b, done under TCG).

**Path prefixes used below**
- `plan` = `docs/orin-native-port-plan.md`; `D3` = `results/orin-native-port/20260909T1100Z/m3-design.md`; `DD` = `results/orin-native-port/20260909T1100Z/m4-dryrun-design.md`
- `startup/` = `orin-native/startup/`; `tools/` = `orin-native/tools/`; `m4/` = `orin-native/m4/` (new); `m4dry/` = `orin-native/m4dry/`; `qhvconf/` = `orin-native/qhv/`; `shim/` = `orin-native/shim/`
- `qhvh/` = `qhv/host/output/build/`: local, git-ignored, QNX-generated **text** build files (.gitignore:16); only text was read
- `sdp/` = `C:/Users/<user>/qnx800/target/qnx/aarch64le/` (file sizes only, `ls`)
- **The unpublished M3 record** = `m3-runs.md`, and **the unpublished 7b record** = `m4-dryrun-runs.md`, both on the local branch `m3-results-unpublished`, plus the git-ignored logs under `results/orin-native-port/20260910T2307Z/m4-dryrun/`. This design cites them by name and never quotes a figure from them.
- Inputs: a scratch synthesis of three read-only readers (not tracked). Every claim below cites the primary file, not the synthesis.

**Evidence classes:** VERIFIED (read in source, a build file or a log, or computed on this PC; cited), VENDOR_CLAIM (QNX or Arm documentation), HYPOTHESIS, UNKNOWN.

**Licence status (NC QDL v7).** Every log, listing, CSV and statistic these runs produce is evaluation output under 4.6(i): private until the supervising professor has been consulted. This file is design only, and it carries no measured figure. Design constants (bounds, caps, budgets, the 32 ns tick) are not measurements. No QNX-shipped binary is disassembled or inspected (4.6(c)); `strings`, `objdump` and hexdumps of QNX binaries are not used. IFS images, kimgs, `.kev` files and `.sym` files never reach a tracked path.

**QNX documentation cited** (VENDOR_CLAIM, SDP 8.0; base `https://www.qnx.com/developers/docs/8.0/`): [tl] `com.qnx.doc.neutrino.utilities/topic/t/tracelogger.html`; [tp] `…/t/traceprinter.html`; [TE] `com.qnx.doc.hypervisor.user/topic/debug/trace_events.html`; [TSC] `…/debug/tsc.html`; [TR] `…/debug/trace.html`; [GX] `…/perform/guest_exits.html`; [CC] `com.qnx.doc.neutrino.lib_ref/topic/c/clockcycles.html`; [SAT] `com.qnx.doc.sat/topic/kercall_table_Events.html`. [use-tl] and [use-tp] are the tracelogger and traceprinter use texts printed on this PC for 7b (DD:27, VERIFIED as text).

---

## 0. Summary

M4 produces the plan's second hardware-timed QHV number (plan:57-63): the per-exit hypervisor dwell of the cloud-leg QNX guest under native `qvm` at EL2 (`-P4 -Q enable,el2-host`), as P50, P99 and max, in the `diff-results.sh` CSV schema (plan:416-421). It keeps M3's image, guest, configuration and host procedure (D3 §3), and adds a kernel trace around the IPC run, an on-target counter, and a transfer of a capped listing over the TCU to COM3.

**What changes against the plan's M4 text (plan:392-426), and why:**
1. **The listing carries THREAD events, and a C counter classifies on the target.** A pair's class (clean, preempted, blocked, migrated) needs THREAD events, which 7b's `QVM *:` filter dropped (m4dry/m4dry-host.ksh.in:101). The board image has no gawk and no pipes (startup/m3-host.ksh.in:11; DD:1374-1384), so the counter is C (`tools/m4count.c`, new). The listing goes out verbatim at r1 so the PC can check the counter independently, and in a compact per-pair form at r2 once r1 shows the two agree (§5, D2, D3).
2. **Ring sizing comes from the board.** 7b showed that `-k`, not `-S`, sizes a ring, and that only a very large `-k` held the IPC window under TCG (DD:1692-1721). That size must not be copied (DD:1710-1715). r0 measures the board's own buffer fill rate, r1 checks it with qvm running, and a fixed rule turns each rung's record into the next image's parameters (§2.4).
3. **The window is closed with no tail.** The ring only has to hold the events from the start marker to STOP, so the fixed sleep before the start marker costs nothing, and the 2 s tail 7b used after the end marker is removed (§4.2).
4. **The transport is `tcu-cat`, not the console.** Console bytes are mirrored into the black box until its cap and are then dropped without a count (startup/t234-orin-nano/aarch64/callout_debug_tcu.S:122-136). `tcu-cat` writes the TCU mailbox directly and counts drops (tools/tcu-cat.c:59-90, :153-157). It gains a file argument, a timeout abort and a summary line, with its old behaviour unchanged (§5.1).
5. **The COM3 capture is byte-exact,** the harness checks its remaining life against its own longest wait before any kexec, and the PC recomputes md5, POSIX cksum, byte and line counts before it believes a listing (§6, §7.2).
6. **Bounds grow with the work.** The guard is computed from a bound table per image (§8.1); r0 and r1 use 2,700 s, against M3's 900 s.

**Run ladder** (§2):

| Rung | Image | Purpose |
|---|---|---|
| r0 | `m4-r0` | Trace tools natively under `el2-host` at `-P4`, **no qvm**: the path and stop probe, the zero-tail marker test, the counter on fixtures and on a real board listing, the board's idle buffer fill rate, the ring's memory cost, board traceprinter and counter speeds, and the TCU transfer of a capped listing with every check |
| r1 | `m4-r1-k<K1>` | M3's full run (qvm, guest, 15 IPC iterations) inside a ring of `K1` buffers per CPU sized from r0; a verbatim listing (cap 1 MiB) and the counter's compact pair list (cap 512 KiB); the PC compares them pair for pair |
| r2 | `m4-r2-k<K2>-n<N2>` | Q, then T1-T5 on the one kimg: `N2` IPC iterations sized from r1 to reach at least 10,000 eligible clean pairs per run, the compact list plus a 128 KiB verbatim sample |

**What a pass settles:**
- On this board, SDP 8.0's qvm emits Class-10 GUEST_ENTER, GUEST_EXIT and CYCLES events natively at EL2, with the fields the dwell needs.
- The dwell of eligible clean exit/entry pairs has a stated P50, P99 and max at 32 ns resolution in each of five runs, with its run-to-run spread.
- The trace, stop, format, count and transfer pipeline works pipe-free on the board, with every transferred byte checked.

**What it is not** (§12.1): not guest-visible exit latency in general, not free of trace-emission cost (upper bounds, plan:453-455), not at a known CPU frequency, not a one-variable diff against either TCG leg (plan:450-452), and not publishable before the 4.6(i) consultation.

---

## 1. Objective and pass/fail

### 1.1 The plan's pass and fail lines, mapped

The M4 section as amended after 7b (plan:392-426):

| # | Plan text | M4 criterion | Where it is judged |
|---|---|---|---|
| P1 | "the dry run shows Class-10 IDs 0/1/7 present" (plan:423) | Met under TCG by 7b (plan:401-414). **On the board:** r1's counter reports `enter`, `exit` and `cycles` all above zero (`M4C QVM`), confirmed by the PC's independent parse of r1's verbatim listing | r1 (§2.2) |
| P2 | "5 board runs of >= 1,000 Exit/Entry pairs each" (plan:423-424) | T1-T5 each have `eligible_clean` ≥ 1,000 (§1.4, §1.5), from the on-target counter and, where the compact list arrived uncapped, the PC recount | §2.3; §6.4 |
| P3 | "`cksum` and line count matching on the PC side" (plan:424) | For every transferred block of every T-run: md5, POSIX cksum, byte count and line count recomputed on the PC equal the `M4 FLT BEGIN` line in both the black box and COM3 | §6.3 |
| P4 | "P50 stable within +/-20 % across runs" (plan:424) | Each T-run's clean P50 lies within ±20 % of the median of the five clean P50 values | §1.5; §6.5 |
| P5 | "`diff-results.sh` consuming the CSV" (plan:425) | `scripts/twin/diff-results.sh <cloud CSV> <M4 CSV>` exits 0 and prints the M4 row's P50, P99 and Max; the M4 CSV sits at a git-ignored path (§6.4) | §6.5 |
| F1 | "no Class-10 events in the dry run (take the INTERRUPT/THREAD fallback and relabel every number; the zero counts must be verified by an independent parse of the trace, and an unverified zero means a rerun)" (plan:425-426) | 7b did not fail. **On the board:** if r1 counts zero of any of IDs 0, 1, 7 and the PC's parse of the delivered verbatim listing agrees over a complete window, the fallback of §1.7 applies and every number is relabelled. A zero the PC cannot verify (listing capped, damaged or absent) is a rerun of r1, never the fallback | §1.7; §9 |
| F2 | "P50 spread beyond +/-20 % (report the spread, never average it away)" (plan:426) | M4 fails; the record gives all five P50 values, their median and min-max range, and no mean | §1.5 |

**M4 is met** when Q passed and T1-T5 each meet P2 and P3 with the identical kimg, P4 holds across T1-T5, and P5 holds. A failed T-run is never replaced (the M3 validity rule, D3:1062-1064, carried over in §2.3).

### 1.2 The dwell

**Events** (VENDOR_CLAIM, [TE]; the numbering is VERIFIED in `sys/trace.h:286-293`, DD:81). ID 0 GUEST_ENTER carries `guest_ip`. ID 1 GUEST_EXIT carries `status`, the exit reason, `clockcycles_offset`, `guest_ip` and a payload. ID 7 CYCLES carries `at_entry` and `at_exit`, guest clock readings at the entry and exit it describes. [TE] says ID 0's timestamp should not be used for guest time.

**Printed form** (VERIFIED under TCG from 7b's local listings, host traceprinter; the target prints the same layout, DD:1706): `QVM :GUEST_EXIT status:0x… hw_reason:0x… clockcycles_offset:0x… guest_ip:0x… payload:0x…`, `QVM :CYCLES at_entry:0x… at_exit:0x…`, `QVM :GUEST_ENTER guest_ip:0x…`. The printed field names are `hw_reason` and `payload`, as [SAT] and [TSC] spell them, not [TE]'s `reason` and `hw_payload` (DD:122-126). The counter and parser match only `status`, `clockcycles_offset`, `at_entry` and `at_exit`, which every source names alike, and record `hw_reason` when present.

**Triple.** On the vCPU thread, triple *n* is GUEST_ENTER*n*, CYCLES*n*, GUEST_EXIT*n* in that order (DD:1258; m4dry/parse-m4dry.py:840-883). The vCPU thread is the thread running on the event's CPU when CYCLES is emitted (`running[cpu]`, the latest THRUNNING on that CPU, m4dry/parse-m4dry.py:811-818, :842-845). `g2-m3.conf` has one bare `cpu` line (qhvconf/g2-m3.conf:29), so one vCPU thread is expected; the counter reports how many threads emitted CYCLES.

**Definition.** For consecutive complete triples *n* and *n*+1 on that thread:

```
dwell_n = at_entry(n+1) − at_exit(n)        64-bit unsigned subtraction, read as signed
```

It is the guest clock's advance from the exit of *n* to the entry of *n*+1: time the vCPU spent outside the guest, in the hypervisor, in the host kernel or waiting. The offset cancels (m4dry/parse-m4dry.py:903-906; DD:1260-1264).

**Host time** is used only to place a pair in the window and to classify it. With `o_n` = GUEST_EXIT*n*'s `clockcycles_offset` read as signed 64-bit, a guest reading of triple *n* converts as `H_n(g) = g − o_n` modulo 2^64 ([TSC] VENDOR_CLAIM; the conversion held on every in-sequence triple under TCG once 64-bit time was rebuilt, plan:412). Each reading uses the offset of its own triple. The offset is set when qvm starts and not changed afterwards ([TSC]; DD:116), so `o_n = o_n+1` in the expected case; the counter reports the number of distinct offset values, and r1, Q and every T-run require exactly 1 (§2.2 item 3).

**Order check, per triple:** `t(ENTER_n) ≤ H_n(at_entry_n) ≤ H_n(at_exit_n) ≤ t(EXIT_n)`, where `t()` is the event's 64-bit host time (§4.5.3). Under TCG host and guest time run at one rate (plan:412-413); on silicon that is HYPOTHESIS, so the check runs on every triple of every run.

### 1.3 Pair classes

Each pair's host interval is `I_n = [H_n(at_exit_n), H_n+1(at_entry_n+1)]`: each end is converted with its own triple's offset (§1.2). Let `c_x` be the CPU of GUEST_EXIT*n* and `c_e` the CPU of GUEST_ENTER*n*+1. The first rule that matches decides:

| Class | Token | Rule |
|---|---|---|
| migrated | `mig` | `c_e ≠ c_x`, or a THRUNNING of the vCPU thread on a CPU other than `c_x` lies in `I_n` |
| blocked | `blk` | a THREAD-class event of the vCPU thread in `I_n` whose state is neither THRUNNING nor THREADY (THCONDVAR, THMUTEX, THSEM, THRECEIVE, THREPLY, THSEND, THNANOSLEEP, THINTR, or any other TH* name). A guest WFI halt lands here: `exit-on-halt` defaults to enabled (DD:400, [use-qvm]), and the vCPU thread waits for the next interrupt (HYPOTHESIS until r1's records show it) |
| preempted | `pre` | a THREADY of the vCPU thread in `I_n`, or a THRUNNING of any other thread on `c_x` in `I_n` |
| clean | `clean` | none of the above |

INTERRUPT-class events on `c_x` inside `I_n` never change the class: host interrupt handling during a dwell is part of the dwell. They are counted per class (`intr=` on `M4C PAIRS`). 7b's `dwell_preempted` lumped three of these classes and missed migration (m4dry/parse-m4dry.py:909-910); it is not reused.

### 1.4 Eligibility

A pair is **eligible** when all of these hold:

| # | Condition | Why |
|---|---|---|
| E1 | Triples *n* and *n*+1 are complete, in order, consecutive on the vCPU thread, with no broken sequence between them | A reset sequence loses the pairing (m4dry/parse-m4dry.py:757-762) |
| E2 | Both triples pass the order check (§1.2) | A failed order check means the conversion, not the dwell, is in doubt |
| E3 | GUEST_EXIT*n* and GUEST_EXIT*n*+1 both carry `status` 0 | [TSC]: a zero status means the entry succeeded, so the ID 7 values are meaningful (DD:117, VENDOR_CLAIM). Non-zero pairs are counted as `status_nonzero` |
| E4 | `dwell_n ≥ 0` | A negative dwell is a defect, counted as `negative`, never a sample |
| E5 | `I_n` lies inside the marker window: `H_n(at_exit_n) ≥ t(m4-ipc-start)` and `H_n+1(at_entry_n+1) ≤ t(m4-ipc-end)` | The workload is defined by the markers (DD:315-324) |
| E6 | The window is intact: both markers present, `ring=held` (§4.5.4), and each CPU's BUFFER sequence contiguous | A wrapped CPU hides THREAD events that would change a class |
| E7 | Every event used for triples *n*, *n*+1 and the class of `I_n` has a 64-bit time (§4.5.3) and an attributed thread | Unattributed events cannot be classified |
| E8 | The counter's stored-event tables were not capped before `I_n` ended (§4.5.6) | A capped table cannot prove a pair clean |

**Eligible clean pairs** are the headline sample (§1.6). Eligible pairs of the other classes are reported with their own statistics.

### 1.5 Statistics

- **Nearest rank:** for *n* sorted dwells and percentile *p*, the value at 1-based rank `k = ceil(p × n / 100)`, computed as `(p × n + 99) / 100` in integers, clamped to 1..n (m4dry/parse-m4dry.py:180-185). P50 and P99 use it; max is the largest value.
- **Units:** dwells are counted in ticks, 1 tick = 1/`cycles_per_sec`. With `cycles_per_sec = 31,250,000` (CNTFRQ, plan:94, VERIFIED; kept by startup, startup/t234-orin-nano/main.c:278-279), `ns = ticks × 32` exactly. The counter computes `ticks × 10^9 / cps` in 128-bit arithmetic and prints `quantum_ns=32` only when `10^9 mod cps = 0`; otherwise `quantum_ns=inexact`. Values are whole ticks, ±1 tick, and no sub-tick decimal is printed. [GX]'s 3-10 µs exit cost would be 94-313 ticks (VENDOR_CLAIM order of magnitude only).
- **Per-run gates:** at least 1,000 eligible clean pairs (plan:423-424). P99 is **quotable** only with at least 10,000 (`p99_quotable=yes|no`); below that it is still computed and printed, and the CSV row says so (§6.4).
- **Across runs:** the median of the five T-run clean P50 values; each within ±20 % of it. The report always gives all five values, the median and the min-max range. No mean, no standard deviation, no outlier removal, no pooling of runs; Q is reported separately (D3 §4.7).

### 1.6 The headline (decision D4)

- **CSV:** eligible clean pairs only: `samples` = their count; `p50_ns`, `p99_ns`, `max_ns` from them (§6.4).
- **Record:** the same three statistics for `pre`, `blk`, `mig` and `nonblk` (clean plus preempted plus migrated), with counts, for every run.
- **Bias warning.** Clean-only P99 and max are biased low whenever preemption or migration stretches real exits. The counter prints `M4C WARN clean_tail_bias` when preempted plus migrated reach 1 % or more of the eligible non-blocked pairs; the run note then says the clean P99 is not a guest-visible tail.

### 1.7 If the board emits no Class-10 event

Mirroring plan:425-426 and DD:103-111:
- **A verified zero** needs r1's verbatim listing delivered intact (§6.3), with no `capped=1`, covering the whole marker window with `ring=held`, and the PC parse of it also counting zero for that ID. Only then does the fallback apply.
- **The fallback** relabels every M4 number as a **host exit-to-entry bound** fenced by THREAD RUNNING events of the qvm vCPU thread (plan:397-399; DD:205), an upper bound that includes host preemption. It needs a design amendment before r2; nothing in this design implements it.
- **An unverified zero** (listing capped, damaged, absent, or ring not held) is a rerun of r1, after reading the counter's `M4C HIST` and `M4C QVMOTHER` lines for any QVM-like name.

---

## 2. Rungs

### 2.0 Common procedure and exact commands

Every rung uses one loop; only the image name changes. `<utc>` is the session directory, created once per session. `ORIN_HOST` and `ORIN_KEY` come from the operator's environment, never from a file in the repo (startup/m3-board.sh:26-29).

```
# PC, Git Bash, SDP environment sourced (once per tool change)
make -C orin-native/tools                       # tcu-cat (revised) and m4count (new); smpcheck keeps its pin (§3.5)

# PC, Git Bash: build one image (§3)
BSP=C:/Users/<user>/AppData/Local/Temp/orin-native-port-bsp QNX_BASE=/c/Users/<user>/qnx800 \
  ./orin-native/startup/make-m4-images.sh <image> [--from-size FILE]

# PC, Git Bash: stage and pre-flight (§7; M3's §6.2-6.3 unchanged)
M4_RECORD_DIR=results/orin-native-port/<utc>/m4 ./orin-native/startup/m4-board.sh stage <image>
M4_RECORD_DIR=results/orin-native-port/<utc>/m4 ./orin-native/startup/m4-board.sh p0 <image>

# PC, PowerShell (never Git Bash): the COM3 capture, raw bytes, running before the run starts and stopped only after it returns (§6.1)
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\m4\capture-com3-raw.ps1 `
  -Port COM3 -Seconds <capture_s from <image>.params> -Out results\orin-native-port\<utc>\m4\com3-<image>-<run>.log

# PC, Git Bash: one kexec round, records fetched, parser run (§7)
M4_RECORD_DIR=results/orin-native-port/<utc>/m4 M4_COM3_LOG=<that file> M4_RUN_ID=<run> \
  M4_QUIESCE=1 M4_GOVERNOR_PIN=1 ./orin-native/startup/m4-board.sh run <image>

# PC: the next rung's parameters (§2.4)
python orin-native/m4/parse-m4.py size-r1 --r0-parse results/orin-native-port/<utc>/m4/out/<r0 run>-parse.log
python orin-native/m4/parse-m4.py size-r2 --r1-parse results/orin-native-port/<utc>/m4/out/<r1 run>-parse.log --r0-parse results/orin-native-port/<utc>/m4/out/<r0 run>-parse.log
```

`<run>` is `r0`, `r1`, `q`, `t1` … `t5`. `m4-board.sh run` calls the parser itself (§7, step 8b); the same command runs by hand as `python orin-native/m4/parse-m4.py run --params orin-native/shim/out/m4/<image>.params --blackbox <bb> --com3 <com3> --run-id <image>-<run> --out-dir results/orin-native-port/<utc>/m4/out`.

`M4_QUIESCE=1` and `M4_GOVERNOR_PIN=1` are M3's owner decisions O4 and O5 as they ran (D3:1328-1329); M4 keeps them for every rung and run (§7).

### 2.1 r0: trace tools, probe, rate, counter, transfer; no qvm

**Image:** `m4-r0`, mode `trace` (§3.2). It carries everything r1 carries, including qvm, the guest and its disk, so the file list never changes between rungs. It never launches qvm.

**What the host script does** (state order; the script is §4.1):

| State | Action |
|---|---|
| config, preflight, rate_pre, integrity_pre | As M3 (startup/m3-host.ksh.in:48-68) |
| clock | `clkcmp` under `bwait -k 120`; only its `CLK HDR`, `CLK VERDICT`, `CLK SKIP`, `CLK NOTE` and `CLK ERROR` lines are printed (D6(a); tools/clkcmp.c:63-67) |
| fixtures | `m4count -q` on the three synthetic fixtures (§4.5.9), each under `bwait -k 20` |
| disk | M3's copy, `cmp`, devb-loopback and `/dev/qvmdisk0` wait (startup/m3-host.ksh.in:70-83), so the release step below is exercised |
| probe | Ring `tracelogger -r -k 64 -M -S 8M -f /dev/shmem/p.kev`; MEM before and while armed; 2 s settle; marker 30 `m4-probe-start`; 5 s; marker 31 `m4-probe-end`; `trcctl -x` with **no tail**; stop ladder; MEM after |
| l0 | Linear `tracelogger -s 10 -S 32M -f /dev/shmem/l0.kev`, the form W1 ran under TCG (DD:224); 2 s settle; marker 32 `m4-l0-start`; 6 s; marker 33 `m4-l0-end`; wait for its own end |
| release | `slay -f -Q devb-loopback`; `rm -f /dev/shmem/disk-qvm`; MEM |
| format, count (probe) | `traceprinter -n -f /dev/shmem/p.kev -o /dev/shmem/p.txt` under `bwait -k 120`; `m4count` over it, records only |
| format, count (l0) | the same over `l0.kev` under `bwait -k 600`; `m4count` writes the verbatim window selection `/dev/shmem/flt.v`, capped at 262,144 B |
| send | Block `v` over the TCU (§5) |
| rate_post, diag, end | As M3 |

**r0 passes, and gates r1, when the black box and COM3 show all of:**
1. M3's R0 landing and startup criteria at N=4 (D3:1072, "Landing and startup"), then `T234 M4 r0 -P4: procnto up` and `BWAIT guard armed secs=2700`.
2. `M4 STATE` lines in order through `end`, and `M4 FAIL_STATE none`.
3. **Clock:** three `CLK VERDICT` lines, each `agree` or `agree-within-resolution`. A `disagree` is recorded and goes to the owner before r1 (it would say the counter and the kernel's time base disagree on silicon).
4. **Fixtures:** each fixture's `M4C` summary lines equal the expected lines the PC's `selftest` derives independently (§4.5.9, §6.2).
5. **Probe:** `M4 STOP p by=stop`; `M4C MARK start=found end=found`; `M4C RING state=held`; every `M4C BUF` line has `kept` at most 65 (-k 64 plus one trailing buffer, DD:1700) and `gaps=0`; `M4C TIME64 mismatches=0`.
6. **Memory:** `M4 MEM probe_pre`, `probe_armed` and `probe_stopped` lines. The PC derives the ring's cost for 64 buffers per CPU.
7. **Rate:** `M4 STOP l0 by=self`; both L0 markers found; `M4C BUF` for CPUs 0-3 with `gaps=0`; `M4C RATE` lines (§4.5.7).
8. **Speeds:** `BWAIT run prog=traceprinter … killed=0` and `BWAIT run prog=m4count … killed=0` for L0.
9. **Transfer:** `M4 FLT BEGIN name=v …`; the `tcu-cat:` summary with `drops=0 aborted=0 deadline=0 rc=0`; the PC's `flt_v=ok` (§6.3).
10. **Reset:** PMC `reset_reason` `MAINSWRST`; black box under 60,000 B; no §7.3 negative token.

### 2.2 r1: qvm and the IPC window, a small listing cap

**Image:** `m4-r1-k<K1>` (or `m4-r1-lin` under D1(b)), mode `full`, `ITERS=15`, sized by `size-r1` (§2.4).

**What the host script does:** M3's full run (startup/m3-host.ksh.in:48-165) with these changes (§4.1 has the script):
- **ipc:** after the grace wait, `MEM trace_pre` and the memory gate; the ring `tracelogger -r -k K1 -M -S <S>M -f /dev/shmem/t.kev` in the background; 2 s settle; marker 20 `m4-ipc-start`; the client, `qnx-host-client 15 /dev/ttyp0 5`, under `bwait -k 240` with its bwait line redirected; marker 21 `m4-ipc-end`; `trcctl -x` at once; the stop ladder. Nothing prints between the start marker and the end of the ladder.
- **release** after `integrity_post`: `slay -f -Q devb-loopback`, `rm -f /dev/shmem/disk-qvm`, MEM.
- **format** (`bwait -k 600`) and **count**: `m4count` writes `/dev/shmem/flt.v` (verbatim window selection, cap 1,048,576 B) and `/dev/shmem/flt.c` (compact pair list, cap 524,288 B).
- **send:** block `v`, then block `c`.

**r1 passes, and gates r2, when all of:**
1. D3 §8 items 1-11 with M4's names: `T234 M4 r1 -P4`, `M4 CONFIG rung=r1 mode=full …`, `M4 CHECK … ok`, the real banner stamp, the IPC completion rule `samples + sentinel_recoveries = 15` with `rc=0 killed=0`, `md5_post` ok, `MAINSWRST`.
2. `M4 TRACE ARM …`; `M4 STOP t by=stop`; `M4 KEVFILE t path=/dev/shmem/t.kev bytes=…`.
3. **P1 on the board:** `M4C QVM` with `enter`, `exit` and `cycles` above zero; `M4C VCPU threads=1`; `M4C OFFSET distinct=1`; `M4C TRIPLES … order_violated=0`; `M4C TIME64 … mismatches=0` (§4.5.3 says what it guards, and why it is a gate rather than a cross-check field).
4. `M4C RING state=held`.
5. **The two readings agree** (D2, D3): the PC's parse of the delivered block `v` gives the same triples, pairs, classes, eligibility and dwell as the counter's block `c` for every pair wholly inside the delivered range (`xcheck_pairs=match`), and, when `v` is not capped, the same `M4C PAIRS` counts and `M4C STAT` values (`xcheck_stats=match`).
6. `flt_v=ok` and `flt_c=ok`; `M4C END rc=0`.

**On fail:** §9. Specifically: `ring=wrapped` at K1 = 256 → build `m4-r1-k512` and rerun r1 once; at 512 → D1(b), `m4-r1-lin`. `M4 FAIL mem_trace` → halve K1 (not below 64) and rerun; below 64 → owner, M3's O7 memory fallback (D3:1331). Any §1.7 zero → §1.7.

### 2.3 r2: Q and five timed runs on one kimg

**Image:** `m4-r2-k<K2>-n<N2>` (or `m4-r2-lin-n<N2>`), mode `full`, sized by `size-r2` (§2.4). The counter writes block `c` (compact, cap 1,048,576 B) and block `v` (a verbatim sample, cap 131,072 B); `c` is sent first.

| Run | Pass means | On fail |
|---|---|---|
| **Q** | r1's criteria 1-6 at `ITERS=N2`, plus P2 (`eligible_clean` ≥ 1,000) and P3 for both blocks, plus G2-M4 (black box under 60,000 B) | §9; fix, rebuild, rerun Q. Q never counts |
| **T1-T5** | P2 and P3 on each run, with Q's other criteria | Record and stop; never replaced (D3:1062-1064). M4 is not met if any T-run fails P2 or P3 |
| **Series** | P4 over T1-T5, and P5 | M4 fails on P4 (F2); report the spread |

`python orin-native/m4/parse-m4.py series --parse-logs <t1> <t2> <t3> <t4> <t5> --csv <M4 CSV> --cloud-csv results/cloud/cloud-ipc-latest.csv` prints P4 and runs P5 (§6.5).

**Validity rule** (D3:1062-1064, unchanged): a run that never reached QNX (no `T234-SHIM`, a Linux Oops in its own shutdown, `BAD-LANDING`) is retried with the same kimg and recorded as a host-side failure. A run in which QNX started counts.

### 2.4 Sizing rules: one rung's record fixes the next image

The parser's `size-r1` and `size-r2` subcommands implement these rules exactly and print the generator command and the values, which the generator writes into `<image>.params` (§3.3). No parameter is chosen by hand. Constants marked (budget) are design constants, not measurements.

**From r0 to r1**

| Symbol | Source |
|---|---|
| `b0` | max over CPUs *c* of `(bufs_c + 1) / span`, where `bufs_c` counts CONTROL BUFFER events on *c* with a time inside L0's markers, and `span` is the marker interval in seconds (`M4C RATE`) |
| `probe_cost_mb` | `MEM probe_pre` − `MEM probe_armed`, in MB, for 64 buffers per CPU |
| `tp_bps0`, `cnt_bps0` | L0 `.kev` bytes per second of traceprinter's `ms=`; L0 text bytes per second of the counter's `ms=` |
| `tcu_bps0` | `bytes_sent` per second of `ms=` from the `tcu-cat -s` summary of block `v` |

1. `need1 = ceil(16 × b0 × 60) + 2`. The factor 16 (budget, HYPOTHESIS) allows qvm and the IPC run to raise the busiest CPU's buffer rate sixteen-fold over idle. 60 s (budget) covers the settle, the client's start and 1 s priming drain, 20 iterations and four 10 s sentinel recoveries (D3:846-848).
2. `K1 = 256` if `need1 ≤ 256`; `512` if `need1 ≤ 512`; otherwise `lin` (D1(b)).
3. `ring_mb(K) = ceil(K × 16 × 4 / 1024)` ([use-tl]: about 16 KB per buffer, per CPU; DD:1604). `S(K) = ring_mb(K) + 4` MiB, so `-S` always exceeds the ring (DD:1616). `cost(K) = max(ring_mb(K), ceil(probe_cost_mb × K / 64))`. `TRACE_NEED_MB(K) = cost(K) + S(K) + 32` (32 MB margin, budget).
4. If `4 × S(K1) × 1,048,576 / tp_bps0 > 600`, step K1 down (512 → 256); at 256 still over: owner decision (raise TP_BOUND, guard recomputed).
5. `CNT_BOUND1 = 120` if `4 × 5 × S(K1) × 1,048,576 / cnt_bps0 ≤ 120`, else 300. The factor 5 (budget) is text bytes per `.kev` byte, shaped on the unpublished 7b record.
6. `SEND(cap) = ceil(cap / max(0.5 × tcu_bps0, 2000)) + 15` s. If it exceeds 600 s for a block, that block's cap halves until it fits.
7. The guard follows from §8.1; r1's must be at most 2,700 s, else the caps halve.

**From r1 to r2**

| Symbol | Source |
|---|---|
| `seq_max_c` | the highest CONTROL BUFFER sequence kept on CPU *c* in r1 (`M4C BUF last_seq`). R37 (DD:1688, supported on TCG, DD:1701-1704): it counts buffers since tracelogger started, so it includes the settle and is conservative |
| `beta` | `max_c seq_max_c / 20` buffers per iteration (15 timed plus 5 warm-up) |
| `p1` | r1's `eligible_clean / 20` |
| `bpp1` | r1's block `c` bytes per pair line |

1. r1 must have `ring=held`. `p1 = 0` goes to the owner.
2. `N_pairs = max(15, ceil(15000 / p1) − 5)`: 1.5 × 10,000 clean pairs, so that P99 is quotable with margin.
3. `N2 = min(N_pairs, 13200)`. 13,200 keeps `IPC_BOUND2 = 240 + ceil(0.05 × N2)` at most 900 s, with 50 ms per iteration (budget: the client's 20 ms pacing, client.c:317, plus the round trip and recoveries).
4. `K2 = max(256, ceil(1.5 × beta × (N2 + 5)) + 2)`.
5. If `K2 > 512`: `N_ring = floor(510 / (1.5 × beta)) − 5`. If `N_ring × p1 ≥ 1200`, set `N2 = N_ring`, `K2 = 512`, and record `p99_target=ring-limited`. Otherwise D1(b): `m4-r2-lin-n<N2>`, with step 3's `N2`.
6. `TRACE_NEED_MB2 = TRACE_NEED_MB(K2)` with r0's `probe_cost_mb`.
7. `TP_BOUND2 = min(900, max(120, ceil(4 × tp_ms1 / 1000 × S(K2) / S(K1)) + 60))`; `CNT_BOUND2 = min(600, max(60, ceil(4 × cnt_ms1 / 1000 × S(K2) / S(K1)) + 30))`.
8. `CAP_C2 = 1,048,576`; `CAP_V2 = 131,072`. The rule prints `c_capped_predicted=yes` when `1.5 × (pairs_all1 / 20) × (N2 + 5) × bpp1 > CAP_C2`. The on-target statistics stay complete either way; only the PC recount is limited.
9. `SEND_C2`, `SEND_V2` by step 6 above with r1's `tcu_bps`.
10. `GUARD2 = ceil((W(r2) + 125 + 240) / 300) × 300` (§8.1, with its 240 s minimum margin). If it exceeds 3,600 s, N2 drops by 10 % steps until it fits, and K2 is recomputed.
11. **Reachability, with the final `N2`** (review V7). `clean_pred = floor(p1 × (N2 + 5))` is the number of eligible clean pairs per run that r1's yield predicts. `p2_reachable=yes` when `clean_pred ≥ 1200` (step 5's floor), else `no`. `p99_reachable=yes` when `clean_pred ≥ 15000` (step 2's target), `short-margin` from 10,000 up to that target, and `no` below 10,000. Both go to stdout and into the size file. With `p2_reachable=no`, `size-r2` exits 3 and writes no size file, because a T-series predicted to miss P2 goes to the owner. With `p99_reachable=no`, it also exits 3 and writes no size file, unless `--accept-low-n` is given. That flag writes `accept_low_n=1`, the owner's acceptance goes into the run note, and every T-run's CSV row carries `;p99=low-n` (§6.4).

**Contingency images** (built only on their branch):

| Id | Image | When | Record as |
|---|---|---|---|
| C1 | `m4-r1-k512` | r1 at K1 = 256 shows `ring=wrapped` | r1b; r2 sizes from r1b |
| C2 | `m4-r1-lin`, `m4-r2-lin-n<N>` | a rule returns `lin` | D1(b): linear capture; the flush activity is recorded (§4.2) |
| C3 | `m4-r1-k<K1/2>` | `M4 FAIL mem_trace` | memory-limited ring |
| C4 | `m4-r0v` (the `-vv` startup line) | r0's black box is 60,000 B or more | a startup-line deviation, as D3 G1 (D3:877) |

---

## 3. The image: delta from M3, and the generator

### 3.1 File list delta

Everything in `startup/m3.build.in` stays, byte for byte where it is not listed here: the startup line (m3.build.in:45), the libraries (:92-128), the guest pair `[+raw]` (:142-143) and the utilities (:148-173). Sizes are `ls` of the SDP files today (VERIFIED) or of our current builds.

**Added**

| IFS name | Source | Bytes | Why | Provenance |
|---|---|---|---|---|
| `tracelogger` | sdp/usr/sbin/tracelogger | 25,936 | the capture | m2.build.in:200; ran natively in M2 R5 at `-Q disable -P6` (m2-runs.md:62-78) |
| `traceprinter` | sdp/usr/bin/traceprinter | 187,248 | the listing | m2.build.in:201 |
| `libtracelog.so.1` | sdp/lib/libtracelog.so.1 | 38,152 | tracelogger's library | m2.build.in:202 |
| `libtraceparser.so.1` | sdp/usr/lib/libtraceparser.so.1 | 35,432 | traceprinter's library | m2.build.in:203 |
| `trcctl` | tools/trcctl (7b build) | 13,888 | markers and STOP | tools/trcctl.c:22-24; VERIFIED under TCG (DD:1405) |
| `clkcmp` | tools/clkcmp (7b build) | 18,720 | the clock self-consistency check, r0 only | tools/clkcmp.c:84-85 ("the board M4 image can carry it unchanged") |
| `m4count` | tools/m4count (new, §4.5) | ~40,000 (estimate) | the counter | this design |
| `m4-host.ksh` | generated from `startup/m4-host.ksh.in` (§4.1) | ~16,000 (estimate) | replaces `m3-host.ksh` | this design |
| `m4fix-1.txt`, `m4fix-2.txt`, `m4fix-3.txt` | `m4/fixtures/` (new, synthetic text, §4.5.9) | ~4,000 each (estimate) | the counter's on-board self-test | this design |
| `[type=link] cksum=toybox` | toybox applet | link | POSIX cksum of each block | qhvh/system.build:129 |
| `[type=link] rm=toybox` | toybox applet | link | removing the disk copy and the text listing | qhvh/ifs.build:79 |

**Changed:** `tcu-cat`, rebuilt from the revised `tools/tcu-cat.c` (§5.1), about 2 KB larger (estimate).

**Removed:** `m3-host.ksh` and `m3-fake-guest.txt`. M4 has no harness mode.

**Deliberately absent (`ABSENT_NAMES`):** `vpctl`, `vdev-virtio-net.so`, `fs-qnx6.so`, `random`, `io-sock` (all kept from make-m3-images.sh:126); `gawk`, `awk`, `gzip`, `base64` (the board never runs 7b's awk counter or its `.kev` extraction, DD:1316-1347); `m3-host.ksh`, `m3-fake-guest.txt`; every `.sym`. `tracelogger` and `traceprinter` leave the list.

**Net growth** about 0.38 MiB of IFS against M3, inside the `avoid_ram` reservation (D3:293).

### 3.2 The buildfile template (`startup/m4.build.in`)

Markers: `@RUNG@` (`r0`, `r1`, `r2`), `@P@` (4), `@GUARD@` (seconds, §8.1), `@CLIENT@`, `@GUEST_IFS@`, `@GUEST_DISK@` (absolute host paths), `@KSH@`, `@CONF@`, `@FIX1@`, `@FIX2@`, `@FIX3@` (generated or copied files under `shim/out/m4/`). Comment lines are dropped from the generated buildfile, as in M3 (D3:316). The mode lives only in the host script, so every M4 buildfile differs only in `@RUNG@`, `@GUARD@` and `@KSH@`.

```
[image=0x80082000]
[-compress]

[virtual=aarch64le,raw] .bootstrap = {
    startup-t234-orin-nano -vvv -P@P@ -Q enable,el2-host -m992M -Wkeep -A -Dtcu
    PATH=/proc/boot LD_LIBRARY_PATH=/proc/boot
    [+keeplinked] procnto-smp-instr -v
}

[+script] .script = {
    display_msg "T234 M4 @RUNG@ -P@P@: procnto up"
    procmgr_symlink ../../proc/boot/ldqnx-64.so.2 /usr/lib/ldqnx-64.so.2
    procmgr_symlink /proc/boot/ksh /bin/sh
    smpcheck -i -n @P@
    bwait -g @GUARD@ &
    slogger2
    pipe
    devc-pty
    pidin info
    ksh /proc/boot/m4-host.ksh
    display_msg "T234 M4 @RUNG@ -P@P@: resetting so the log can be recovered"
    smpcheck -z 3
    shutdown -S reboot
}

[type=link] /usr/lib/ldqnx-64.so.2=/proc/boot/ldqnx-64.so.2
ldqnx-64.so.2
[-autolink]
<m3.build.in:95-128 verbatim: libc.so.6 … libpci.so.3.0, qcrypto.conf>
libtracelog.so.1
libtraceparser.so.1

/proc/boot/tcu-cat=tcu-cat
/proc/boot/stamp=stamp
/proc/boot/bwait=bwait
/proc/boot/smpcheck=smpcheck
/proc/boot/trcctl=trcctl
/proc/boot/clkcmp=clkcmp
/proc/boot/m4count=m4count
[perms=0555] /proc/boot/qnx-host-client=@CLIENT@
[perms=0444] /proc/boot/m4-host.ksh=@KSH@
[perms=0444] /proc/boot/g2.conf=@CONF@
[perms=0444] /proc/boot/m4fix-1.txt=@FIX1@
[perms=0444] /proc/boot/m4fix-2.txt=@FIX2@
[perms=0444] /proc/boot/m4fix-3.txt=@FIX3@
[+raw perms=0444] /proc/boot/guest-ifs.bin=@GUEST_IFS@
[+raw perms=0444] /proc/boot/disk-qvm=@GUEST_DISK@

<m3.build.in:148-173 verbatim: ksh … [type=link] wc=toybox>
tracelogger
traceprinter
[type=link] cksum=toybox
[type=link] rm=toybox
```

The two `<…verbatim…>` lines stand for the M3 text copied unchanged into the committed template; the generator checks that each copied range still equals `startup/m3.build.in` at those lines (step 9), so the two templates cannot drift apart silently. The script block keeps M3's order (census, then guard, m3.build.in:56-69).

### 3.3 Images and parameters

| Image | Mode | Ring | Iterations | Blocks and caps (B) | Guard (s) | Sized by |
|---|---|---|---|---|---|---|
| `m4-r0` | trace | probe `-r -k 64 -M -S 8M`; L0 linear `-s 10 -S 32M` | — | `v` 262,144 | 2,700 | fixed (this table) |
| `m4-r1-k<K1>` | full | `-r -k K1 -M -S S(K1)M` | 15 | `v` 1,048,576; `c` 524,288 | 2,700 | `size-r1` (§2.4) |
| `m4-r2-k<K2>-n<N2>` | full | `-r -k K2 -M -S S(K2)M` | N2 | `c` 1,048,576; `v` 131,072 | `GUARD2` | `size-r2` (§2.4) |
| `m4-r1-lin`, `m4-r2-lin-n<N>` | full | `-c -S S(512)M` (§4.2, D1(b)) | 15 or N | as r1 or r2 | as r1 or r2 | contingency C2 |

**`<image>.params`** (ASCII `key=value`, one per line, git-ignored beside the kimg), written by the generator and read by `m4-board.sh`, `m4-tloop.ps1` and the parser: `image rung mode p kind k s_mb tl_args tl_bound trace_need_mb fmt_need_mb cnt_need_mb iters ipc_bound banner_bound grace tp_bound cnt_bound hash_bound forms cap_v cap_c send_v send_c send_t_v send_t_c clean_pred p2_reachable p99_reachable accept_low_n ksh_worst_s guard_s return_bound_s capture_s size_file size_sha256 ksh_sha256 kimg_sha256`. The four reachability keys are `-` for r0 and r1. `return_bound_s = guard_s + 300`; `capture_s = return_bound_s + 3000` (review V1). The capture term has two parts. The first is the longest wait `m4-board.sh run` can make once gate A of §7.2 item 3 has passed: 2,180 s, made of the pre-kexec sessions, the kexec session, the one 600 s extension, and 300 s for the operator's no-growth watch. The second is 820 s for the time between starting the capture and starting `run`. The capture is a safety net: it is stopped after `run` returns (§6.1).

**r0's fixed values:** `tp_bound=600` (L0), 120 (probe, in the script); `cnt_bound=120`; `hash_bound=20`; `fmt_need_mb=463` and `cnt_need_mb=303` (§8.2; L0's values, also applied to the smaller probe listing); `send_v=68` (`ceil(262144/5000) + 15`, before any rate is known), `send_t_v=63`; `banner_bound=240`, `grace=90`, `ipc_bound=240` (present, unused in trace mode).

### 3.4 `startup/make-m4-images.sh`: steps and checks

A new file, built by copying `make-m3-images.sh` and applying the changes below; M3's generator is not edited (plan rule; its PO-A step would fail if it were). Usage:

```
BSP=… QNX_BASE=… ./make-m4-images.sh [--generate-only] m4-r0
BSP=… QNX_BASE=… ./make-m4-images.sh [--generate-only] m4-r1 --from-size <size file>
BSP=… QNX_BASE=… ./make-m4-images.sh [--generate-only] m4-r2 --from-size <size file>
```

The image name (`m4-r1-k256`, …) is derived from the size file, never typed. r1 and r2 without `--from-size` are refused. It stops at the first failure with `FAIL: <step>`, with M3's `die`, `STEP` and ERR trap (make-m3-images.sh:143-147).

1. **Output guard.** `OUT="$SHIM/out/m4"`. Die if it resolves into `out/m1b`, `out/m2` or `out/m3` (make-m3-images.sh:285-307, with `out/m3` added). `git check-ignore` must pass for `x.build x.ksh x.ifs x.kimg x.params x.procnto-smp-instr.sym gate/x.conf xtr-x/disk-qvm size-r1.size` under `OUT`.
2. **Snapshot** `git status --porcelain`.
3. **PO-A: earlier milestones' sources unchanged against HEAD.** M3's list (make-m3-images.sh:103-108) plus `startup/m3.build.in`, `startup/m3-host.ksh.in`, `startup/m3-fake-guest.txt`, `startup/make-m3-images.sh`, `startup/m3-board.sh`, `qhvconf/g2-m3.conf`, `qhvconf/g2-m3-diag.conf`, `qhvconf/g2-noblk.conf`, `tools/stamp.c`, `tools/bwait.c`, `tools/smpcheck.c`, `tools/trcctl.c`, `tools/clkcmp.c`. Not `tools/tcu-cat.c`, which M4 revises.
4. **PO-B: pins.** `PIN_STARTUP`, `PIN_SMPCHECK`, `PIN_CLIENT` exactly as make-m3-images.sh:96-98. Record the sha256 of `tcu-cat`, `stamp`, `bwait`, `trcctl`, `clkcmp` and `m4count`.
5. **PO-C: earlier kimgs, read only.** M3's four prefixes (make-m3-images.sh:360-384). For `out/m3/`: print the sha256 of every `*.kimg` present, for the record. If `M4_M3_RAN_SHA256` is set (the kimg M3's T-runs ran, copied by the operator from the unpublished M3 record), `out/m3/m3-r2.kimg` must match it. Nothing under `out/m3/` is written, rebuilt or deleted.
6. **PO-D: the guest pair.** `PIN_GUEST`, `PIN_DISK` (make-m3-images.sh:99-100); md5 values for baking.
7. **PO-E: the configuration.** make-m3-images.sh steps 7.1-7.4 (:424-442) for `g2-m3.conf` only; the stripped file is written to `$OUT/g2-m3.conf`. The configuration is unchanged from M3 (no `trace-*` `set` lines: 7b saw IDs 0, 1 and 7 at the defaults, plan:404, so the `vtwfe` lines of DD:326-330 are not needed).
8. **Parameters.** r0 takes §3.3's fixed values. r1 and r2 read every `.params` key from the size file, check each range (`k` 64-512 or `lin`; `iters` 15-13,200; `tp_bound` 120-900; `cnt_bound` 60-600; each `send_*` 30-600; caps 65,536-1,048,576), recompute `ksh_worst_s` and `guard_s` from §8.1's table and `fmt_need_mb` and `cnt_need_mb` from §8.2's formulas, and die if any of them differs from the size file's value. An r2 size file with `p2_reachable=no` is refused, and one with `p99_reachable=no` is refused unless it carries `accept_low_n=1` (§2.4 step 11).
9. **Generate** `$OUT/<image>.build` from `m4.build.in`, `$OUT/<image>.ksh` from `m4-host.ksh.in`, `$OUT/<image>.params`; copy the three fixtures with CR stripped. Checks:
   - no `@[A-Z0-9_]+@` survives in either file;
   - the two verbatim ranges of §3.2 equal `m3.build.in:95-128` and `:148-173`;
   - the buildfile has exactly one startup line equal to M3's (make-m3-images.sh:204), 13 script lines, and exactly one each of `bwait -g <guard_s> &`, `smpcheck -i -n 4`, `ksh /proc/boot/m4-host.ksh`, `shutdown -S reboot`;
   - **the pipe-free rule** (startup/m3-host.ksh.in:11-15) is checked by `python orin-native/m4/parse-m4.py kshcheck <ksh>`, one implementation shared with §11.2 (review V2). Neither make-m3-images.sh nor build-m4dry-image.ps1 has a static check to copy, and M3's script uses the OR list operator throughout (m3-host.ksh.in:52-55, :81, :98, :131, :135). So the rule is stated in tokens, not characters. The checker reads the file as ksh quotes it:
     - `'…'` is single-quoted;
     - `"…"` is double-quoted, with `\` escaping the next character;
     - elsewhere, `\` escapes one character;
     - a `#` that starts a word begins a comment;
     - quote state carries across lines.

     It dies naming `file:line` on any of these:
     1. **A pipe.** After every `||` is removed, any `|` left outside both kinds of quotes and outside comments. So `||`, a `grep -E '…|…'` pattern and a `|` inside a double-quoted `say` string all pass. A pipeline, `|&` and a case-pattern alternation all fail: without parsing, a case `|` cannot be told from a pipe, so the template has none (§4.1 rule 1).
     2. **A substitution.** `$(` or a backquote outside single quotes; double quotes do not stop a substitution.
     3. **A nested shell or foreign text.** The words `waitfor` and `eval`, `ksh -c`, `sh -c`, and `<<`. A string handed to a nested shell can hold a real pipe that its quotes hide, as 7b's template did (m4dry/m4dry-host.ksh.in:91-103), and a here-document body is not shell text.
   - **the checker's own test, before it gates anything.** `kshcheck --selftest` must accept `a || b`, `grep -E 'x|y' f`, `say "p|q"`, `f=${l#*FreeMem:}` and `x # a | b`. It must reject `a | b`, `a|b`, `a |& b`, `case "$v" in a|b) x ;; esac`, `x=$(y)`, `say "$(y)"`, a backquoted command, `waitfor /dev/x 5`, `eval x`, `ksh -c 'a | b'` and `cat <<E`. Then the generated ksh must pass. Finally, a copy of it under `$OUT/gate/`, with ` | cat` appended to its last command line, must fail naming that line; the copy is then deleted;
   - `bash -n` parses the ksh (a proxy, as make-m3-images.sh:590-591).

   `--generate-only` stops here, after step 19's guard, and needs no SDP.
10. **SDP and inputs** (make-m3-images.sh:634-690): `SDP_FILES` gains `usr/sbin/tracelogger usr/bin/traceprinter lib/libtracelog.so.1 usr/lib/libtraceparser.so.1` (m4dry/build-m4dry-image.ps1:295); the tool check covers `tcu-cat stamp smpcheck bwait trcctl clkcmp m4count`.
11. **Size check before mkifs.** Sum the `ls` sizes of every file the buildfile names (SDP files, tools, client, guest pair, generated files) plus 262,144 B of slack for headers and startup. Die if `0x80082fa0 + sum > 0x8C000000`. Print the sum.
12. **mkifs** (make-m3-images.sh:693-709).
13. **dumpifs `-vv`** (make-m3-images.sh:712-760) with M4's names: 13 script lines; `T234 M4 <rung> -P4`; `bwait -g <guard_s> &`; `ksh /proc/boot/m4-host.ksh`. `IFS_NAMES` = M3's list (:112-124) without `m3-host.ksh m3-fake-guest.txt`, with `trcctl clkcmp m4count m4-host.ksh m4fix-1.txt m4fix-2.txt m4fix-3.txt tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1 cksum rm`, each exactly once. `ABSENT_NAMES` per §3.1 absent; no `.sym`.
14. **Geometry** (make-m3-images.sh:763-786): `image_paddr=0x80082fa0`, end at or below `0x8C000000`.
15. **Startup arguments** (make-m3-images.sh:793-849): `-P4`, `-Q enable,el2-host`, one `-A`, argv equal to the buildfile line.
16. **Byte identity inside the IFS** (make-m3-images.sh:853-884): extract `guest-ifs.bin disk-qvm g2.conf m4-host.ksh m4fix-1.txt m4fix-2.txt m4fix-3.txt`; each sha256 equals its pin or generated file; delete the extraction.
17. **Wrap** (make-m3-images.sh:887-905): kimg = 8,192 B shim page plus this IFS; `image_size` page-rounded.
18. **Stability:** startup, smpcheck, stamp, bwait, trcctl, clkcmp, m4count, tcu-cat and client sha256 unchanged since step 4.
19. **Tracked-path guard** (make-m3-images.sh:600-628) over `$OUT`; `git status --porcelain` equals the snapshot.
20. **Table:** image, rung, mode, IFS and kimg bytes and sha256; the `.params` file's contents; the tool, startup, client, guest and SDP sha256 values (`HASHED_NAMES` = M3's :141 plus `tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1`). Hashes and sizes only.

### 3.5 Other file changes

- **`tools/Makefile`:** `TOOLS := tcu-cat stamp smpcheck bwait clkcmp trcctl m4count`. The pattern rule is unchanged; `smpcheck` must still hash to `PIN_SMPCHECK` after `make` (step 4 enforces it).
- **`.gitignore`:** add `orin-native/tools/m4count` after :94.
- **New, committed text:** `startup/m4.build.in`, `startup/m4-host.ksh.in`, `startup/make-m4-images.sh`, `startup/m4-board.sh`, `tools/m4count.c`, `m4/parse-m4.py`, `m4/capture-com3-raw.ps1`, `m4/m4-tloop.ps1`, `m4/fixtures/m4fix-{1,2,3}.txt`, `m4/build-m4tcg-image.ps1`, `m4/launch-m4tcg.ps1`, `m4/post_start-m4tcg.custom`.
- **Changed, backward-compatible:** `tools/tcu-cat.c` (§5.1).
- **Not changed:** `startup/m3*`, `startup/make-m3-images.sh`, `startup/m2*`, `startup/make-m1b-images.sh`, `startup/t234-orin-nano/`, `shim/`, `qhvconf/`, `tools/{stamp,bwait,smpcheck,trcctl,clkcmp}.c`, `m4dry/`, `ipc-test/`, `scripts/`, the canonical `qhv/host/output` and `qhv/guest/output`, and every earlier record.
- **M3 artefacts:** the kimgs under `shim/out/m3/` are never rebuilt or written. Because M3's generator does not pin `tcu-cat` (make-m3-images.sh:96-100), re-running it after the `tcu-cat` revision would build a kimg that differs from the one M3 ran; that is recorded here as a consequence, and step 5 checks the ran kimg instead.

---

## 4. On-target capture, stop, format and count, without pipes

### 4.1 The host state machine (`startup/m4-host.ksh.in`)

**Rules**, M3's (startup/m3-host.ksh.in:11-15; D3 §2 rules 1, 6, 7) plus two:
1. No pipe, no command substitution, no backquote, no `waitfor`. Also no case-pattern alternation, no `eval`, no `ksh -c` or `sh -c`, and no here-document. The static check of §3.4 step 9 cannot tell a case `|` from a pipe, and cannot see inside a nested shell's string. Arithmetic is never computed in the script: every number is baked by the generator. Redirection, `read -r … < file`, functions, `( … ) &`, `case` and `for` are used, as M3 and 7b ran them (m3-host.ksh.in:30-37, :104-106; m4dry-host.ksh.in:49-68, VERIFIED on the board and under TCG).
2. Every wait is a `bwait` with a bound, and every child that could block runs under `bwait -k` (bwait.c:21-29).
3. **Silence inside a window.** From the start marker to the end of the stop ladder nothing writes to the console: `trcctl` and `bwait` print to stdout (trcctl.c:72, :96; bwait.c:87-116), so each call is redirected to a file and printed afterwards. The TCU console callout busy-polls every character in the writer's context (callout_debug_tcu.S:131-136), which would add host work and events inside the ring.
4. **Records before any listing byte** (§5.3); capped diagnostics after the send.

**Markers the generator replaces** (board value, then the TCG profile's of §11): `@RUNG@`; `@MODE@` (`trace` for r0, `full` otherwise); `@P@` (4; 2); `@CPUS@` (`0 1 2 3`; `0 1`); `@RATES@` (1; 0, no smpcheck under TCG); `@IO_BOUND@` for the md5, copy and compare runs (30; 600, because TCG copies and hashes the 146 MiB disk slowly); `@B@` our tools (`/proc/boot`; `/system/bin`); `@X@` QNX tools (`/proc/boot`; `/system/bin`); `@GUEST_IFS@`, `@GUEST_DISK@`, `@CONF@`, `@CLIENT@` (`/proc/boot/…`; `/data/hypervisor/guest/ifs.bin`, `/data/hypervisor/guest/disk-qvm`, `/system/bin/m4-g2.conf`, `/data/hypervisor/qnx-host-client`); `@STARTUP_LINE@`, `@A@`; the seven hash markers of M3 (make-m3-images.sh:573-578); `@ITERS@`, `@IPC_BOUND@`, `@BANNER_BOUND@`, `@GRACE@`, `@GRACE_WAIT@` (= GRACE + 10); `@KIND@`, `@TL_ARGS@`, `@TL_BOUND@`, `@TRACE_NEED_MB@`; `@FMT_NEED@`, `@CNT_NEED@` (the format and count memory gates, §8.2; the TCG profile's values are in §11.2); `@TP_BOUND@`, `@CNT_BOUND@`, `@HASH_BOUND@`; `@CNT_OUT@` (the counter's output options, §4.5.1); `@FORMS@`; `@SEND_V@`, `@SEND_T_V@`, `@SEND_C@`, `@SEND_T_C@`; `@TRANSPORT@` (`tcu`; `console`); `@FIX@` (the three fixture paths). The generator dies if any `@[A-Z0-9_]+@` survives.

```ksh
# m4-host.ksh: M4 host state machine, generated from m4-host.ksh.in; edit the template.
S=/dev/shmem
B=@B@
X=@X@
RUNG=@RUNG@
MODE=@MODE@
P=@P@
CPUS="@CPUS@"
GUEST_IFS=@GUEST_IFS@
GUEST_DISK=@GUEST_DISK@
CONF=@CONF@
CLIENT=@CLIENT@
FAIL=
LAUNCHED=
TRACED=
MEMFREE=0
STOPBY=none

say()   { echo "M4 $*"; }
state() { echo "M4 STATE $*"; }
hit()   { [ -e "$S/$1.hit" ]; }
show()  { for f in "$@"; do [ -s "$f" ] && cat "$f"; done; }
headc() { [ -s "$2" ] && head -c "$1" "$2"; }
mem() {
	MEMFREE=0
	pidin info > "$S/mem.$1" 2>&1
	while read -r l; do
		case "$l" in
		*FreeMem:*) f=${l#*FreeMem:}; f=${f# }; f=${f%% *}; say "MEM $1 $f"; MEMFREE=${f%%MB*} ;;
		esac
	done < "$S/mem.$1"
	case "$MEMFREE" in '') MEMFREE=0 ;; *[!0-9]*) MEMFREE=0 ;; esac
}
rates() {
	if [ "@RATES@" != 1 ]; then say "RATES $1 skipped"; return; fi
	for c in $CPUS; do
		smpcheck -b 3 -C "$c" -o "$S/${1}c${c}" &
	done
	smpcheck -c "$P" -p "$S/${1}c" -T 20
}
md5ok() {
	if grep -q "^$2 " "$1"; then say "CHECK $4 $3 ok"; else say "FAIL $4 $3"; FAIL=${FAIL:-$4}; fi
}
# arm NAME KEV BOUND ARGS...: tracelogger in the background under a kill bound, silently.
arm() {
	n=$1; k=$2; tb=$3; shift 3
	( bwait -k "$tb" -r "$S/$n.rec" -o "$S/$n.out" -e "$S/$n.err" -- "$X/tracelogger" "$@" -f "$k" > "$S/$n.b" 2>&1; : > "$S/$n.done" ) &
}
# stopladder NAME: STOP, then SIGINT, then SIGKILL; silent (m4-dryrun-design.md D3).
stopladder() {
	STOPBY=none
	if [ -e "$S/$1.done" ]; then STOPBY=early; return; fi
	trcctl -x > "$S/$1.x" 2>&1
	if bwait -p "$S/$1.done" -t 120 > "$S/$1.s1" 2>&1; then STOPBY=stop; return; fi
	slay -f -Q -s INT tracelogger
	if bwait -p "$S/$1.done" -t 30 > "$S/$1.s2" 2>&1; then STOPBY=sigint; return; fi
	slay -f -Q -s KILL tracelogger
	if bwait -p "$S/$1.done" -t 10 > "$S/$1.s3" 2>&1; then STOPBY=kill; fi
}
stopreport() {
	show "$S/$1.m1" "$S/$1.m2" "$S/$1.x" "$S/$1.s1" "$S/$1.s2" "$S/$1.s3" "$S/$1.b"
	headc 512 "$S/$1.out"
	headc 512 "$S/$1.err"
	say "STOP $1 by=$STOPBY"
}
# fmtcount NAME KEV TPBOUND FMTNEED CNTNEED START END [m4count output options]: after the window only.
fmtcount() {
	n=$1; k=$2; tb=$3; fn=$4; cn=$5; ms=$6; me=$7; shift 7
	if [ ! -e "$S/$n.done" ] || [ ! -s "$k" ]; then say "KEVFILE $n path=none"; return; fi
	bwait -k @HASH_BOUND@ -o "$S/$n.kwc" -e "$S/$n.kwc.err" -- "$X/wc" -c "$k" > "$S/$n.kwb" 2>&1
	KB=none
	[ -s "$S/$n.kwc" ] && read -r KB rest < "$S/$n.kwc"
	say "KEVFILE $n path=$k bytes=$KB"
	mem "preformat_$n"
	if [ "$MEMFREE" -lt "$fn" ]; then
		say "FAIL mem_format name=$n step=format free_mb=$MEMFREE need_mb=$fn"; FAIL=${FAIL:-mem_format}; return
	fi
	bwait -k "$tb" -r "$S/$n.tp.rec" -o "$S/$n.tp.out" -e "$S/$n.tp.err" -- "$X/traceprinter" -n -f "$k" -o "$S/$n.txt"
	headc 512 "$S/$n.tp.err"
	bwait -k @HASH_BOUND@ -o "$S/$n.twc" -e "$S/$n.twc.err" -- "$X/wc" -c "$S/$n.txt" > "$S/$n.twb" 2>&1
	TB=none
	[ -s "$S/$n.twc" ] && read -r TB rest < "$S/$n.twc"
	say "TEXT $n bytes=$TB"
	mem "formatted_$n"
	if [ "$MEMFREE" -lt "$cn" ]; then
		say "FAIL mem_format name=$n step=count free_mb=$MEMFREE need_mb=$cn"; FAIL=${FAIL:-mem_format}
		"$X/rm" -f "$S/$n.txt"; return
	fi
	bwait -k @CNT_BOUND@ -r "$S/$n.cnt.rec" -o "$S/$n.cnt" -e "$S/$n.cnt.err" -- "$B/m4count" -i "$S/$n.txt" -w "$n" -s "$ms" -e "$me" "$@"
	show "$S/$n.cnt"
	headc 512 "$S/$n.cnt.err"
	"$X/rm" -f "$S/$n.txt"
}
# send NAME FILE BOUND DEADLINE: the hashes on the console, then the framed body (§5).
send() {
	n=$1; f=$2; sb=$3; st=$4
	if [ ! -s "$f" ]; then say "FLT SKIP name=$n reason=absent-or-empty"; return; fi
	bwait -k @HASH_BOUND@ -o "$S/$n.md5" -e "$S/$n.md5.err" -- "$X/md5sum" "$f" > "$S/$n.h1" 2>&1
	bwait -k @HASH_BOUND@ -o "$S/$n.ck" -e "$S/$n.ck.err" -- "$X/cksum" "$f" > "$S/$n.h2" 2>&1
	bwait -k @HASH_BOUND@ -o "$S/$n.wc" -e "$S/$n.wc.err" -- "$X/wc" -l -c "$f" > "$S/$n.h3" 2>&1
	FM=none; FC=none; FB=none; FL=none; FW=none
	[ -s "$S/$n.md5" ] && read -r FM rest < "$S/$n.md5"
	[ -s "$S/$n.ck" ] && read -r FC FB rest < "$S/$n.ck"
	[ -s "$S/$n.wc" ] && read -r FL FW rest < "$S/$n.wc"
	show "$S/$n.h1" "$S/$n.h2" "$S/$n.h3"
	say "FLT BEGIN name=$n rung=$RUNG lines=$FL bytes=$FB wc_bytes=$FW md5=$FM cksum=$FC"
	bwait -s 1 -c "$S/$n.pause"
	if [ "@TRANSPORT@" = tcu ]; then
		bwait -k 10 -o "$S/$n.t0o" -e "$S/$n.t0e" -- "$B/tcu-cat" -a 50 -s -m "=M4FLT= BEGIN name=$n rung=$RUNG" > "$S/$n.t0" 2>&1
		bwait -k "$sb" -o "$S/$n.t1o" -e "$S/$n.t1e" -- "$B/tcu-cat" -a 50 -T "$st" -s -f "$f" > "$S/$n.t1" 2>&1
		R=$?
		bwait -k 10 -o "$S/$n.t2o" -e "$S/$n.t2e" -- "$B/tcu-cat" -a 50 -s -m "=M4FLT= END name=$n" > "$S/$n.t2" 2>&1
		show "$S/$n.t0" "$S/$n.t0e" "$S/$n.t1" "$S/$n.t1e" "$S/$n.t2" "$S/$n.t2e"
	else
		echo "=M4FLT= BEGIN name=$n rung=$RUNG"
		cat "$f"
		R=$?
		echo "=M4FLT= END name=$n"
	fi
	say "FLT END name=$n rc=$R"
}

state config
say "CONFIG rung=$RUNG mode=$MODE startup='@STARTUP_LINE@' q=el2-host w=keep A=@A@ cpus=$P guest_sha256=@GUEST_SHA256@ disk_sha256=@DISK_SHA256@ conf_sha256=@CONF_SHA256@ client_sha256=@CLIENT_SHA256@ clock=unverified kind=@KIND@ tl_args='@TL_ARGS@' iters=@ITERS@ forms='@FORMS@' trace_need_mb=@TRACE_NEED_MB@ transport=@TRANSPORT@"

state preflight
bwait -p /dev/ptyp1 -t 10 || { say "FAIL preflight /dev/ptyp1"; FAIL=preflight; }
bwait -p /dev/ttyp0 -t 10 || { say "FAIL preflight /dev/ttyp0"; FAIL=preflight; }
bwait -p /dev/slog -t 5 || say "NOTE no /dev/slog"
bwait -p /dev/pipe -t 5 || say "NOTE no /dev/pipe"
mem boot

state rate_pre
rates r0

if [ -z "$FAIL" ]; then
	state integrity_pre
	bwait -k @IO_BOUND@ -o "$S/md5.pre" -e "$S/md5.pre.err" -- "$X/md5sum" "$GUEST_IFS" "$GUEST_DISK" "$CONF"
	show "$S/md5.pre"
	md5ok "$S/md5.pre" @GUEST_MD5@ guest md5_pre
	md5ok "$S/md5.pre" @DISK_MD5@ disk md5_pre
	md5ok "$S/md5.pre" @CONF_MD5@ conf md5_pre
fi

if [ "$MODE" = trace ]; then
	state clock
	bwait -k 120 -o "$S/clk.out" -e "$S/clk.err" -- "$B/clkcmp"
	grep -E '^CLK (HDR|VERDICT|SKIP|NOTE|ERROR)' "$S/clk.out"
	state fixtures
	for fx in @FIX@; do
		bwait -k 20 -o "$S/fix.out" -e "$S/fix.err" -- "$B/m4count" -q -i "$fx" -w fix -s m4-fix-start -e m4-fix-end
		show "$S/fix.out"
		headc 256 "$S/fix.err"
	done
fi

if [ -z "$FAIL" ]; then
	state disk
	bwait -k @IO_BOUND@ -o "$S/cp.out" -e "$S/cp.err" -- "$X/cp" "$GUEST_DISK" "$S/disk-qvm"
	if bwait -k @IO_BOUND@ -o "$S/cmp.out" -e "$S/cmp.err" -- "$X/cmp" "$GUEST_DISK" "$S/disk-qvm"; then
		say "CHECK disk_copy ok"
	else
		say "FAIL disk_copy"; headc 512 "$S/cp.err"; headc 512 "$S/cmp.out"; FAIL=disk_copy
	fi
fi
if [ -z "$FAIL" ]; then
	devb-loopback loopback blksz=512,prefix=qvmdisk,fd=/dev/shmem/disk-qvm
	bwait -p /dev/qvmdisk0 -t 10 || { say "FAIL disk_dev"; FAIL=disk_dev; }
	mem disk
fi

if [ "$MODE" = trace ] && [ -z "$FAIL" ]; then
	state probe
	mem probe_pre
	arm p /dev/shmem/p.kev 300 -r -k 64 -M -S 8M
	bwait -s 2 -c "$S/p.settle"
	mem probe_armed
	trcctl -m 30 m4-probe-start > "$S/p.m1" 2>&1
	bwait -s 5 -c "$S/p.gap"
	trcctl -m 31 m4-probe-end > "$S/p.m2" 2>&1
	stopladder p
	stopreport p
	mem probe_stopped
	state l0
	arm l0 /dev/shmem/l0.kev 150 -s 10 -S 32M
	bwait -s 2 -c "$S/l0.settle"
	trcctl -m 32 m4-l0-start > "$S/l0.m1" 2>&1
	bwait -s 6 -c "$S/l0.gap"
	trcctl -m 33 m4-l0-end > "$S/l0.m2" 2>&1
	if bwait -p "$S/l0.done" -t 130 > "$S/l0.w" 2>&1; then STOPBY=self; else stopladder l0; fi
	show "$S/l0.w"
	stopreport l0
fi

if [ "$MODE" = full ] && [ -z "$FAIL" ]; then
	state hostcheck
	bwait -k 10 -o "$S/qc.out" -e "$S/qc.err" -- "$X/qvm-check"
	headc 1024 "$S/qc.out"; headc 1024 "$S/qc.err"
	state window
	stamp -i /dev/ptyp1 -o "$S/m3.guest" -m 65536 -r "$S/m3.stamps" -h "$S" -s '---> Starting slogger2' -l g_first -s '---> Starting devb' -l g_devb -s '---> Starting Networking' -l g_net -s 'if_up: tries exhausted' -l g_ifup -s '---> Starting sshd' -l g_sshd -s '---> Starting misc' -l g_misc -s 'server: echo endpoint up' -l g_srv -s 'Startup complete' -l g_startup_complete -s 'QNX qnx-guest' -l banner &
	bwait -p "$S/open.hit" -t 5 || { say "FAIL reader"; FAIL=reader; }
fi
if [ "$MODE" = full ] && [ -z "$FAIL" ]; then
	LAUNCHED=1
	bwait -s @GRACE@ -c "$S/grace.hit" &
	( stamp -n -q -l qvm_launch -r "$S/m3.stamps" -x "$X/qvm" "@$CONF" < /dev/null > /dev/ttyp1 2>&1; echo "rc=$?" > "$S/qvm.rc"; : > "$S/qvm_exit.hit" ) &
	bwait -p "$S/banner.hit" -p "$S/qvm_exit.hit" -t @BANNER_BOUND@
	bwait -p "$S/banner.hit" -t 2 > "$S/banner.settle"
	state report
	show "$S/m3.stamps"
	[ -e "$S/qvm.rc" ] && { say "QVM ended before teardown"; show "$S/qvm.rc"; }
	mem banner
	pidin -p qvm -f abNli > "$S/pq.1" 2>&1; head -n 30 "$S/pq.1"
fi

if [ -n "$LAUNCHED" ] && hit banner; then
	state ipc
	bwait -p "$S/grace.hit" -t @GRACE_WAIT@
	mem trace_pre
	if [ "$MEMFREE" -lt @TRACE_NEED_MB@ ]; then
		say "FAIL mem_trace free_mb=$MEMFREE need_mb=@TRACE_NEED_MB@"; FAIL=${FAIL:-mem_trace}
	else
		TRACED=1
		say "TRACE ARM kind=@KIND@ args='@TL_ARGS@' file=/dev/shmem/t.kev bound=@TL_BOUND@"
		arm t /dev/shmem/t.kev @TL_BOUND@ @TL_ARGS@
		bwait -s 2 -c "$S/t.settle"
		trcctl -m 20 m4-ipc-start > "$S/t.m1" 2>&1
	fi
	stamp -n -q -l ipc_start -r "$S/m3.stamps"
	bwait -k @IPC_BOUND@ -r "$S/ipc.bwait" -o "$S/ipc.out" -e "$S/ipc.err" -- "$CLIENT" @ITERS@ /dev/ttyp0 5 > "$S/ipc.b" 2>&1
	stamp -n -q -l ipc_end -r "$S/m3.stamps"
	if [ -n "$TRACED" ]; then
		trcctl -m 21 m4-ipc-end > "$S/t.m2" 2>&1
		stopladder t
	fi
	state report_ipc
	[ -n "$TRACED" ] && stopreport t
	show "$S/ipc.out" "$S/ipc.b"
	headc 2048 "$S/ipc.err"
	pidin -p qvm -f abNli > "$S/pq.2" 2>&1; head -n 30 "$S/pq.2"
fi

state teardown
if [ -n "$LAUNCHED" ]; then
	slay -f -Q qvm
	bwait -p "$S/qvm_exit.hit" -t 15 || { slay -f -Q -s KILL qvm; bwait -p "$S/qvm_exit.hit" -t 5; }
fi
[ -e "$S/qvm.rc" ] && show "$S/qvm.rc"
if [ -n "$LAUNCHED" ]; then
	bwait -p "$S/eof.hit" -t 5 || slay -f -Q stamp
	state integrity_post
	bwait -k @IO_BOUND@ -o "$S/md5.post" -e "$S/md5.post.err" -- "$X/md5sum" "$GUEST_IFS" "$GUEST_DISK"
	show "$S/md5.post"
	md5ok "$S/md5.post" @GUEST_MD5@ guest md5_post
	md5ok "$S/md5.post" @DISK_MD5@ disk md5_post
fi

state release
slay -f -Q devb-loopback
"$X/rm" -f /dev/shmem/disk-qvm
mem released

state rate_post
rates r1

state format
if [ "$MODE" = trace ]; then
	fmtcount p /dev/shmem/p.kev 120 @FMT_NEED@ @CNT_NEED@ m4-probe-start m4-probe-end
	fmtcount l0 /dev/shmem/l0.kev @TP_BOUND@ @FMT_NEED@ @CNT_NEED@ m4-l0-start m4-l0-end @CNT_OUT@
elif [ -n "$TRACED" ]; then
	fmtcount t /dev/shmem/t.kev @TP_BOUND@ @FMT_NEED@ @CNT_NEED@ m4-ipc-start m4-ipc-end @CNT_OUT@
fi

state summary
show "$S/m3.stamps" "$S/ipc.bwait"
[ -s "$S/ipc.out" ] && grep -E '^(samples=|P50=|sentinel_)' "$S/ipc.out"
for n in p l0 t; do
	[ -s "$S/$n.cnt" ] && grep -E '^M4C (QVM|TIME64|TRIPLES|PAIRS|STAT|RING|WARN|END) ' "$S/$n.cnt"
done
say "FAIL_STATE ${FAIL:-none}"

state send
for n in @FORMS@; do
	case "$n" in
	v) send v /dev/shmem/flt.v @SEND_V@ @SEND_T_V@ ;;
	c) send c /dev/shmem/flt.c @SEND_C@ @SEND_T_C@ ;;
	esac
done

state diag
if [ -e "$S/m3.guest" ]; then
	wc -c "$S/m3.guest"
	if [ -n "$LAUNCHED" ] && ! hit banner; then tail -c 1024 "$S/m3.guest"; else head -c 2048 "$S/m3.guest"; fi
fi
bwait -k 15 -o "$S/slog.txt" -e "$S/slog.err" -- "$X/slog2info"
if [ -n "$LAUNCHED" ] && ! hit banner; then headc 6144 "$S/slog.txt"; else headc 1024 "$S/slog.txt"; fi
mem end
say "FAIL_STATE ${FAIL:-none}"
state end
```

`@CNT_OUT@` for r0 is `-v /dev/shmem/flt.v -V 262144`; for r1 `-v /dev/shmem/flt.v -V 1048576 -c /dev/shmem/flt.c -C 524288`; for r2 `-c /dev/shmem/flt.c -C 1048576 -v /dev/shmem/flt.v -V 131072`. `@FORMS@` is `v`, `v c` and `c v` respectively.

**Differences from M3's script, all deliberate:** the `M4` prefix; the paths as variables (for the TCG profile of §11); `mem` also sets `MEMFREE`; the clock, fixtures, probe and L0 states (trace mode only); the IPC client's `bwait` line redirected; the trace around the client; the release state; format, count and send, with a memory gate before traceprinter and another before the counter; guest text capped at 2,048 B and slog at 1,024 B (6,144 B on the no-banner path), and moved after the send (records first).

### 4.2 Capture mode, `-k` sizing and marker placement (decision D1)

**Mode: a ring, stopped by `trcctl -x`** (D1(a)). A ring flushes nothing during the window: tracelogger writes its buffers only at STOP (DD:292-299, VERIFIED under TCG: `by=stop`, DD:1597-1599). A linear capture writes each buffer as it fills, which is host I/O on cpus 0-3 inside the window (HYPOTHESIS about its size, not its existence). The ring's risk is wrap, which `ring=` detects per CPU (§4.5.4) and which §2.4 sizes against.

**`-k` sizes the ring per CPU; `-S` does not** (plan:409-410; DD:1700, VERIFIED under TCG). The rules:
- r1's `K1` comes from r0's board rate (§2.4); r2's `K2` from r1's buffer sequence numbers. A TCG size is never used (DD:1710-1715).
- `-S` is always the ring plus 4 MiB, so an undocumented cut at `-S` cannot hide inside the window (DD:1616; R38 of DD:1689 stays untested).
- **D1(b), a linear window,** replaces the ring only when a rule returns `lin` (K would exceed 512). Its arguments are `-c -S <S(512)>M`, continuous until STOP. That `-c` plus `trcctl -x` ends a linear capture and flushes it is HYPOTHESIS; C2's r1 run tests it before any r2.

**Why the ring only has to hold start marker to STOP.** A ring overwrites its oldest buffers first ([tl], VENDOR_CLAIM; DD:402-404). Every event older than `m4-ipc-start` is dispensable, so the 2 s settle before the start marker costs no window buffer; it exists only so that tracing is enabled before the marker is inserted (7b used the same 2 s and found both markers, DD:1702). What follows the end marker does cost window buffers, so there is **no tail**: `trcctl -x` runs immediately after `m4-ipc-end`. That the end marker, in its CPU's partly filled buffer, is written at STOP is HYPOTHESIS, supported by the trailing buffer STOP wrote under TCG (DD:1600, VERIFIED); r0's probe tests it natively with the same zero tail.

**Marker IDs** (user string events, trcctl.c:22; User class, trace.h:366): 20 `m4-ipc-start`, 21 `m4-ipc-end`, 30 `m4-probe-start`, 31 `m4-probe-end`, 32 `m4-l0-start`, 33 `m4-l0-end`. They print as `USREVENT :EVENT:<id> STR:"<text>", d0:… d1:… d2:… d3:…` (VERIFIED shape under TCG). The counter matches the quoted text exactly.

**Where the fixed sleeps are, and why each stays:** the 2 s settle before each start marker (above); the probe's 5 s gap and L0's 6 s gap (a span long enough to count buffers per CPU at idle); the 1 s pause between the console `M4 FLT BEGIN` line and the first TCU byte (§5.2). No sleep sits between a window's end marker and its STOP.

### 4.3 The stop ladder

From DD:292-299 and m4dry-host.ksh.in:49-68, with M4's silence rule:

| Rung | Action | Bound | `STOP … by=` |
|---|---|---|---|
| 0 | `.done` already exists before STOP: tracelogger ended by itself (failed to start, or its `bwait -k` bound fired) | — | `early` |
| 1 | `trcctl -x` (TraceEvent `_NTO_TRACE_STOP`, trcctl.c:66-75) | 120 s | `stop` |
| 2 | `slay -f -Q -s INT tracelogger` | 30 s | `sigint` |
| 3 | `slay -f -Q -s KILL tracelogger` | 10 s | `kill` |
| — | nothing ended it | — | `none` |

- A `sigint`, `kill`, `none` or `early` window is recorded as not `stop`; `kill` and `none` normally leave no usable `.kev` (DD:299).
- **The kill bound `@TL_BOUND@` of the background tracelogger** ends inside the guard and after the ladder: `TL_BOUND = 2 + (IPC_BOUND + 5) + 160 + 30`. It is a backstop against a tracelogger that survives the whole script, never the normal stop. r1: 437 s.
- L0 is linear and time-bounded (`-s 10`); it ends by itself (`by=self`, as W1 did under TCG, DD:1672), and the ladder runs only if its 130 s wait times out.

### 4.4 Format after teardown and disk-copy removal

Order, after the stop ladder (§4.1): report IPC → teardown qvm → `integrity_post` → **release** (`slay -f -Q devb-loopback`, then `rm -f /dev/shmem/disk-qvm`) → `rate_post` → **format** → **count**.

- **Why after teardown and release.** The text listing is several times the `.kev` (budget ratio 5, §8.2, shaped on the unpublished 7b record), and the guest's 512 MiB, the 146.3 MiB disk copy (D3:295) and the io-blk cache (D3:296) are freed only once qvm and devb-loopback are gone. `md5_post` still reads `/proc/boot` (m3-host.ksh.in:137), which the release does not touch.
- **Command:** `traceprinter -n -f /dev/shmem/<name>.kev -o /dev/shmem/<name>.txt` under `bwait -k TP_BOUND`. `-n` puts each event's arguments on its line ([tp]; DD:266, :1706). `-o` wrote the listing in M2's R5 on this board (m2.build.in:143); with `-n` it is HYPOTHESIS until r0. The default format is kept: 7b's `-p` experience says the counter must classify by printed name (DD:1584, D-a), and the default format prints the target's 64-bit `t:` (DD:1706).
- **Files:** `wc -c` of the `.kev` and of the text, each under `bwait -k 20`, with `read -r` (no substitution), printed as `M4 KEVFILE` and `M4 TEXT`.
- **Memory gates** (review V4; decision N12). The trace window already has a runtime memory gate (`mem_trace`), and this phase needs its own. The text listing, the counter's tables and their growth transient add up to the same order as the ring (§8.2), and `bwait -k` bounds only time, so a starved traceprinter or counter would look like a bound set too low.
  - Before traceprinter, `M4 MEM preformat_<name>` is compared with `FMT_NEED_MB`.
  - Before the counter, `M4 MEM formatted_<name>` is compared with `CNT_NEED_MB`.
  - Both thresholds are baked by the generator (§8.2).
  - A shortfall prints `M4 FAIL mem_format name=<n> step=format` (or `step=count`) with `free_mb=` and `need_mb=`. It then removes the text if it exists and skips the rest of that listing, so nothing is written for it and nothing is sent. The `.kev` stays.
- **Count** (§4.5), then `rm -f` of the text. The `.kev` stays until the reset.

### 4.5 The counter (`tools/m4count.c`, Apache-2.0, new)

Written in C because the board image has neither gawk nor pipes (DD:1377-1381), and kept separate from `smpcheck.c` so smpcheck's pin survives (make-m3-images.sh:97). Its rules are 7b's parser rules (m4dry/parse-m4dry.py:657-916) with 7b's four defects fixed (DD:1580-1591: `%e` not used, both interrupt spellings, INTERRUPT matched by class, 64-bit time) and the classes of §1.3 added. `m4/parse-m4.py` implements the same rules independently in Python (§6.2); the two must agree (§2.2 criterion 5, §11).

#### 4.5.1 Command line

```
m4count -i LISTING -w NAME -s START -e END [-q] [-v VFILE -V VCAP] [-c CFILE -C CCAP] [-P MAXTRIPLES] [-T MAXTHREAD]
```

| Option | Meaning |
|---|---|
| `-i` | a `traceprinter -n` listing in the default format |
| `-w` | the label every record carries (`w=`) |
| `-s`, `-e` | the start and end marker texts, matched against `STR:"<text>"` exactly |
| `-q` | quiet: only `IN`, `TIME64`, `RING`, `TRIPLES`, `PAIRS`, the clean `STAT` and `END` (fixtures) |
| `-v FILE -V CAP` | write the verbatim window selection (§4.5.8), at most CAP bytes |
| `-c FILE -C CAP` | write the compact pair list (§4.5.8), at most CAP bytes |
| `-P` | triple table cap, default 1,000,000 |
| `-T` | THREAD and INTERRUPT event table cap, default 2,000,000 each |

**Exit:** 0 parsed (whatever it found); 1 input error (file unreadable, no event line) or a failed allocation (`reason=nomem`); 2 usage; 3 a table cap was hit (every record is still printed, and E8 applies). Build `-Wall -Wextra -Werror -O2` like the other tools (tools/Makefile:11-12). libc only: `stdio`, `stdlib`, `string`, `inttypes`, `qsort`, POSIX `clock_gettime(CLOCK_MONOTONIC)` for the `ms=` of the `PASS` lines, and `unsigned __int128` for the ns conversion (as tools/clkcmp.c:230). No Tegra, QNX-kernel or trace-library call: it reads text.

#### 4.5.2 Line grammar

**Event line** (VERIFIED shape under TCG from 7b's local listings; the target prints the same default layout, DD:1706; m4dry/parse-m4dry.py:84):

```
t:0x<1-16 hex> <spaces> CPU:<spaces?><decimal> <spaces> <CLASS, padded>:<SUBTYPE> <arguments>
```

- The class is the text between the CPU number and the first `:` after it, trimmed; the subtype runs to the next blank. USREVENT subtypes print as `EVENT:<id>` (VERIFIED shape), so for class `USREVENT` the subtype runs to the next blank, colon included.
- Arguments are `name:0x<hex>`, `name:<decimal>` or `STR:"<text>"`; `intr_id:0x1c(28)` reads as `0x1c`.
- A CPU outside 0-7 counts `cpu_out_of_range` and the event is skipped.
- Every other line is **unformatted**: the traceprinter header, blank lines, comments. Header lines before the first event are kept for the verbatim selection. A header line containing `TRACE_CYCLES_PER_SEC` gives `cps` as its last decimal integer (HYPOTHESIS on the value's layout; the line itself is VERIFIED to exist); without it `cps=31250000 cps_source=default`.
- Lines are read with `fgets` into 1,024 B; a longer line is drained and counted once as `long_lines` (tools/smpcheck.c:1300-1306).

**Names used** (VERIFIED printed forms under TCG, DD:1382-1389): QVM subtypes `GUEST_ENTER`, `GUEST_EXIT`, `CYCLES`, `CREATE_VCPU_THREAD`, `INTR_RAISE` or `RAISE_INTR`, `INTR_LOWER` or `LOWER_INTR` (ID mapping HYPOTHESIS, DD:1686), `TIMER_CREATE`/`CREATE_TIMER`, `TIMER_FIRE`/`FIRE_TIMER` (unseen); CONTROL subtypes `TIME` (`msb:0x… lsb(offset):0x…`) and `BUFFER` (`sequence = N, num_events = M`); THREAD subtypes `THRUNNING`, `THREADY` and every other `TH*` name, with `pid:` and `tid:`; INTERRUPT, every subtype.

#### 4.5.3 64-bit host time

Per CPU, in file order:
1. A CONTROL TIME event sets `msb[cpu]`.
2. If the event's `t:` hex has more than 8 digits, `t = value` (the target's full 64-bit count, DD:1706, VERIFIED under TCG). With `msb[cpu]` known, `value >> 32` must equal `msb[cpu]` or `msb[cpu] + 1`; otherwise `mismatches++`. The event keeps `value`.
3. If it has 8 digits or fewer: with `msb[cpu]` known, `t = msb << 32 | value`; a drop of more than 2^31 against the previous low word on that CPU increments `msb[cpu]` (`wraps++`), a smaller drop counts `backsteps` (m4dry/parse-m4dry.py:677-696). Without `msb[cpu]`, the event has no time (`unknown++`, E7).
4. A 64-bit time lower than the previous one on the same CPU counts `backsteps64`.

`mode` is `t64` when every timed event took step 2, `rebuilt` when every one took step 3, `mixed` otherwise, `none` without events. A value below 2^32 prints in 8 digits either way and gives the same result on both paths, so the rule is exact for both the host's and the target's traceprinter.

**What `mismatches` guards** (review V6). It is counted only on step 2, where `t` is the printed value and never depends on `msb`, so a mismatch cannot move an event. What it shows is that the CONTROL TIME events and the printed high words disagree, which means the counter's model of the listing's time base is wrong somewhere. That is why r1, Q and every T-run require `mismatches=0` (§2.2 item 3), and why §9 holds r2 on it. A step-3 error, a wrap missed or invented, moves events by 2^32 ticks and shows up instead as `backsteps64`, `order_violated` or `out_of_window`. The `TIME64` counts cover the whole listing, while block `v` carries only a selection (§4.5.8), so `TIME64` is not one of the fields the PC's `xcheck_stats` compares (§6.2 step 5).

#### 4.5.4 Buffers, markers and the ring

- **Per CPU:** `first_seq`, `last_seq`, `kept` (BUFFER events), `gaps` (a sequence number that is not the previous plus one), `max_events` (largest `num_events`), and the 64-bit times of the first and last event kept on that CPU.
- **Markers:** the first USREVENT whose `STR:"…"` equals START, and the first equal to END: time, CPU and a duplicate count.
- **Cover:** CPU *c* is `covered` when it has no event at all, or its first kept event is no later than the start marker. Otherwise it `wrapped`: its ring overwrote part of the window.
- **`ring=held`** when both markers are found, the start precedes the end, every CPU is covered and every `gaps` is 0. **`ring=wrapped`** when both markers are found and some CPU wrapped, **or (I22, 2026-09-11) when the end marker is found, the start marker is not, and some CPU's first kept BUFFER sequence is above 1**: the ring overwrote the start marker itself, which is an undersized ring, not a missing marker. **`ring=unknown`** otherwise. Also recorded: `seq1_cpus`, the CPUs whose first kept sequence is 1, which is R37's reading of "nothing overwritten since start" (DD:1688) and is recorded, not gated: the 2 s settle may legitimately be overwritten (§4.2).

#### 4.5.5 Triples and pairs

**Pass 1** (the whole file):
- `running[cpu]` = the (pid, tid) of the latest THRUNNING on that CPU, in that CPU's file order (m4dry/parse-m4dry.py:811-818).
- GUEST_ENTER, CYCLES and GUEST_EXIT are attributed to `running[cpu]`; with none, `unattributed_qvm++`.
- Per (CPU, thread), a triple is assembled as ENTER, then CYCLES, then EXIT, consecutively in that CPU's file order. HYPOTHESIS: a vCPU does not change physical CPU between its entry and its exit, because it is in guest mode throughout; `broken` counts every sequence that does not complete, and each broken fragment keeps its first time.
- The other order, ENTER, EXIT, CYCLES, is counted as `alt_order` and never paired (DD:344, I5).
- Each complete triple stores: `t_enter`, `t_exit` (64-bit host), `at_entry`, `at_exit`, `offset` (signed), `status`, `hw_reason` (or absent), CPU, and the line numbers of its three events.
- The vCPU threads are the threads with at least one CYCLES event; `VCPU threads=` counts them.

**Order check** per triple (§1.2): `ok` or `violated`; a triple with a missing value is `violated`.

**Pairs:** each vCPU thread's triples are sorted by `t_enter`. Consecutive triples *n*, *n*+1 form a pair unless a broken fragment of that thread has a time between `t_exit(n)` and `t_enter(n+1)`; such a gap is counted `broken_between` and yields no pair. For each pair: `dwell = at_entry(n+1) − at_exit(n)` modulo 2^64, read as signed; `I = [H_n(at_exit_n), H_n+1(at_entry_n+1)]` with `H_m(g) = g − offset_m`, so each end uses the offset of the triple it came from (review V8). [TSC] fixes the offset for the life of the qvm instance (VENDOR_CLAIM; DD:116), so the two offsets are equal in the expected case, and `M4C OFFSET distinct=1` checks that precondition on every run (§2.2 item 3). If the precondition ever failed, each end would still sit at its own event's host time, and the dwell, which uses no offset, would be unaffected.

**Pass 2:** store, with 64-bit time, (a) every THRUNNING of any thread, per CPU; (b) every THREAD event of the vCPU threads; (c) every INTERRUPT event, per CPU. Each array is sorted by time (it already is per CPU, unless `backsteps64` is non-zero). A cap stops storing and sets `capped_at` to the time of the last stored event (E8 applies to pairs whose interval reaches past it).

**Classification** of each pair, §1.3's first matching rule, by binary search on the sorted arrays over `I`:
- `mig`: `cpu(ENTER_n+1) ≠ cpu(EXIT_n)`, or a THRUNNING of the vCPU thread on another CPU in `I`;
- `blk`: an event of the vCPU thread in `I` whose subtype is a TH* name other than THRUNNING and THREADY;
- `pre`: a THREADY of the vCPU thread in `I`, or a THRUNNING of another thread on `cpu(EXIT_n)` in `I`;
- `clean` otherwise;
- `unk` when E7 or E8 prevents a decision.

INTERRUPT events on `cpu(EXIT_n)` in `I` are added to `intr_<class>`.

**Eligibility** per §1.4, E1-E8, in that order; the first failing condition names the counter it increments (`broken_between`, `order_violated`, `status_nonzero`, `negative`, `out_of_window`, `not_held`, `untimed`, `capped`).

#### 4.5.6 Statistics on the target

For each of `clean`, `pre`, `blk`, `mig` and `nonblk` (clean, pre and mig together), over eligible pairs of that class: sort the dwell ticks (`qsort`), nearest rank P50 and P99 and the max (§1.5), `ns = ticks × 10^9 / cps` in 128-bit arithmetic, `quantum_ns=32` when `10^9 mod cps = 0` (otherwise `inexact`), `p99_quotable=yes` when *n* ≥ 10,000. The dwell arrays are the triple table's pairs, so no second cap applies. These lines are printed before any transfer and reach the black box (§5.3), so the numbers survive a failed transfer. Each line is flushed as it is printed, and all of them are out before pass 3 starts (§4.5.8), so they also survive a counter killed while it writes its blocks.

#### 4.5.7 Rate records

For each CPU: `bufs_in_window` (BUFFER events with a time inside the markers), `events_in_window`, and the marker span in ticks. r0's L0 rate and r1's sizing use them (§2.4).

#### 4.5.8 Outputs

**Records** are printed once each, in the order below (`M4C ` prefix, `w=<NAME>` on every line; `…` fields are as named in §4.5.3-4.5.7).

**How they are written** (review V3). `bwait -k` hands the counter a regular file as stdout (bwait.c:252, :262), where stdio buffers in blocks, and it ends an overrun with SIGKILL (bwait.c:307), which no handler can flush.
- Every record goes through one function that formats the line and calls `fflush(stdout)`, as smpcheck.c:131-139 does; trcctl.c:73, :97 and clkcmp.c:144 flush the same way.
- `IN` to `WARN` are printed as soon as pass 2 ends, before pass 3 writes any block. `FLT` follows pass 3, and `END` comes last.
- A kill therefore loses at most the line being written, and the last `PASS` line shows how far the counter got.

| Record | Fields |
|---|---|
| `PASS` | `pass= lines= ms=`, one line as each pass ends: passes 1 and 2 before `IN`, pass 3 before `FLT`. Not printed with `-q` |
| `IN` | `path= lines= bytes= events= unformatted= long_lines= cpu_out_of_range= cps= cps_source=` |
| `HIST` | `class= sub= n=`, at most 48 lines, keys in first-seen order |
| `HISTSUM` | `keys= printed=` |
| `QVM` | `enter= exit= cycles= create_vcpu= intr_raise= intr_lower= timer= other= status_nonzero=` |
| `QVMOTHER` | `sub= n=`, at most 8 lines |
| `SAMPLE` | `sub= line="…"`: the first line of each QVM subtype seen, one THRUNNING and one INT_DELIVER, at most 12 lines, each cut at 160 characters, double quotes replaced by `'` |
| `TIME64` | `mode= time_events= mismatches= wraps= backsteps= backsteps64= unknown=` |
| `BUF` | one per CPU with events: `cpu= first_seq= last_seq= kept= gaps= max_events= first_t=0x… last_t=0x…` |
| `MARK` | `start=found|absent start_t=0x… start_cpu= end=found|absent end_t=0x… end_cpu= dup=` |
| `RING` | `state=held|wrapped|unknown wrapped_cpus=<list|none> seq1_cpus=<list|none>` |
| `RATE` | one per CPU: `cpu= bufs_in_window= events_in_window= span_ticks=` |
| `VCPU` | `threads= pid= tid= cycles_events= unattributed_qvm=` (the first vCPU thread; `threads` counts all) |
| `OFFSET` | `distinct= value=0x…` |
| `TRIPLES` | `complete= broken= alt_order= order_ok= order_violated= in_window=` |
| `PAIRS` | `total= eligible= clean= pre= blk= mig= unk= broken_between= order_violated= status_nonzero= negative= out_of_window= not_held= untimed= capped= intr_clean= intr_pre= intr_blk= intr_mig=` |
| `STAT` | one per class: `class= n= p50_ticks= p99_ticks= max_ticks= p50_ns= p99_ns= max_ns= quantum_ns= p99_quotable=` (`-` values when `n=0`) |
| `WARN` | `clean_tail_bias pre_mig= nonblk= permille=`, only when pre plus mig is at least 10 ‰ of eligible non-blocked pairs (§1.6) |
| `FLT` | form `v`: `form=v file= lines= bytes= capped= sel_lines= sel_bytes= last_t=0x… marker_collision= cr_bytes=`; form `c`: `form=c file= lines= bytes= capped= pairs_written= pairs_total=` |
| `END` | `rc= reason=ok|input|nomem|cap-triples|cap-thread|cap-intr` |

**Black-box cost:** about 2,700-4,700 B per listing for r1 (HIST 48 × ~45 B, SAMPLE ≤ 12 × 175 B, four BUF and four RATE lines, three PASS lines, the rest one line each); about 700 B with `-q` (budget, §8.3).

**The verbatim selection (form `v`).** Pass 3 reads the file again and copies lines byte for byte, in file order, when the line is:
1. unformatted and before the first event line (the header, `cps` included);
2. a CONTROL event (TIME, BUFFER), wherever it is;
3. an event whose 64-bit time lies in `[start_t, end_t]`;
4. an **anchor**, found in pass 1: per CPU, the last THRUNNING before `start_t`; the three lines of any triple with `t_enter < start_t ≤ t_exit` or `t_enter ≤ end_t < t_exit`; and, per vCPU thread, the three lines of the first complete triple entered after `end_t` (it carries `at_entry` of the window's last pair).
5. **(I23, 2026-09-11)** the START or END marker event itself, wherever it is. Without it the PC cannot tell a ring that wrapped past the start marker (I22) from one whose markers are missing, and its reading of `v` would disagree with `RING`.

Copying stops before the first line that would take the file past VCAP (`capped=1`); `sel_lines` and `sel_bytes` count the whole selection anyway, and `last_t` is the time of the last event written. A selected line containing `=M4FLT=` is skipped and counted (`marker_collision`; §5.2 needs the framing text to be unique). `cr_bytes` counts CR bytes in the written lines, which must be 0 for the PC to strip CRs safely (§6.3).

**The compact list (form `c`).** One header comment, then one line per pair whose interval starts inside the window, eligible or not, in time order:

```
# m4count compact w=<NAME> start_t=0x<hex> cps=<n> fields=k,class,elig,dwell_ticks,cpu_exit,cpu_entry,hw_reason,dt_start_ticks
c <k> <clean|pre|blk|mig|unk> <1|0> <signed dwell ticks> <cpu_exit> <cpu_entry> <hw_reason hex without 0x, or -> <H(at_exit_n) − start_t, signed ticks>
```

About 45-55 B per line (budget). Copying stops at CCAP (`capped=1`); `pairs_written` and `pairs_total` are printed.

**Bounds inside the tool:** no wait, no retry, no network; three sequential passes over one file; tables and outputs capped as above. Its wall time is bounded from outside by `bwait -k CNT_BOUND`. Memory at the default caps: triples 1,000,000 × about 88 B, thread and interrupt events 2 × 2,000,000 × about 24 B, about 180 MiB worst case. Each table is allocated by doubling from 64 KiB, never past its cap. While a table grows its old and new blocks coexist, so the peak adds at most one more copy of the largest table, the triple table, about 84 MiB. The counter's budget is therefore `CNT_MB = 270` MiB (budget, §8.2; review V4). If an allocation fails, the counter prints the records computed so far, then `M4C END rc=1 reason=nomem`.

#### 4.5.9 Fixtures

Three synthetic listings, `m4/fixtures/m4fix-1.txt` to `-3.txt`, written by hand in the default `-n` layout with invented values. They are test inputs, not traces, and hold no measured figure. Each begins with `# m4fix: synthetic` and one `# expect: <M4C key=value …>` line per checked record, which `m4count` ignores as unformatted.

| Fixture | Built to contain | Expected in essence |
|---|---|---|
| `m4fix-1` | 4 CPUs, 64-bit `t:`, both markers, BUFFER sequences from 1, one vCPU thread; eight triples giving seven pairs: two clean, one preempted by another thread's THRUNNING, one preempted by THREADY, one blocked by THCONDVAR, one migrated (entry on another CPU), one with a non-zero `status` | `mode=t64`, `ring=held`, `clean=2 pre=2 blk=1 mig=1 status_nonzero=1 eligible=6`; the clean STAT with the two invented dwells at P50, P99 and max |
| `m4fix-2` | 32-bit `t:` with `msb:` TIME events and one low-word wrap inside the window; one triple failing the order check; one negative dwell | `mode=rebuilt wraps=1 order_violated=1 negative=1`, and the pairs next to them ineligible |
| `m4fix-3` | CPU 1's first event after the start marker; a BUFFER sequence gap on CPU 2; one unattributed QVM event before any THRUNNING | `ring=wrapped wrapped_cpus=1`, `gaps=1` on CPU 2, `eligible=0`, `unattributed_qvm=1` |

The PC's `parse-m4.py selftest` checks its own reading of each fixture against the `# expect:` lines, and checks the board's `-q` output for the same fixture against them (§6.2). r0 runs them on the board (§2.1) and §11 under TCG.

---

## 5. Transport

### 5.1 `tools/tcu-cat.c`, revised and backward-compatible

**Why not the console.** The console callout mirrors each byte into the black box until its length word reaches 0xfff0, and after that writes the TCU only (callout_debug_tcu.S:116-129). A mailbox that stays full drops the byte after a bounded poll, and nothing counts the drop (:131-136). `tcu-cat` writes the mailbox itself, never the black box, and counts drops (tools/tcu-cat.c:59-90, :153-157).

**Today:** `tcu-cat [-m MESSAGE]`, otherwise copies stdin (tcu-cat.c:105-151). Under `bwait -k` stdin is `/dev/null` (bwait.c:21-22), so it needs a file argument. A stalled word costs one 20 ms poll per 1-3 bytes (tcu-cat.c:52, :59-70, :80-83), so a dead SPE would crawl through a large file for many minutes before `bwait` killed it, and the kill would lose the drop count.

**Revised usage:**

```
tcu-cat [-m MESSAGE] [-a N] [-T SECS] [-s]
tcu-cat [-f FILE] [-a N] [-T SECS] [-s]
```

| Option | Meaning | Default (old behaviour) |
|---|---|---|
| `-m MESSAGE` | unchanged: MESSAGE plus a newline | — |
| `-f FILE` | read FILE instead of stdin; `-f` with `-m` is a usage error | stdin |
| `-a N` | abort after N consecutive words whose mailbox stayed full (N 1-100,000) | never abort |
| `-T SECS` | stop reading at SECS seconds after start by `ClockCycles()` (1-86,400) | no deadline |
| `-s` | one summary line to stderr at the end | the old drop message only (tcu-cat.c:153-156) |

- **Summary line:** `tcu-cat: bytes_in=<n> bytes_sent=<n> drops=<n> timeouts=<n> max_consecutive=<n> aborted=<0|1> deadline=<0|1> ms=<n> rc=<n>`. `bytes_sent` counts bytes in words the mailbox accepted; `ms` is `ClockCycles()` elapsed.
- **Exit:** 0 every byte accepted; 1 drops, or a map or read error (as today); 2 usage; 3 aborted by `-a`; 4 stopped by `-T`.
- **Unchanged:** stdin copy without `-f`; `-m`; the mailbox word format and FULL handshake (tcu-cat.c:21-29, :72-90); the 20 ms poll; exit 1 with the old stderr message on drops when `-s` is absent. `pidin | tcu-cat` still works in M1-M3 images.
- **Implementation notes:** `put_bytes` returns whether the word was accepted; a consecutive-timeout counter resets on each accepted word; `-a` and `-T` are checked after every word; on abort or deadline the rest of the input is not sent. The file is read in the existing 512 B chunks. Still `-Wall -Wextra -Werror` (tools/Makefile:12); make-m3-images.sh needs only its presence (:682-684), so M3's generator still builds.

**The board commands** (§4.1 `send`): `tcu-cat -a 50 -s -m "=M4FLT= BEGIN name=<n> rung=<r>"`, `tcu-cat -a 50 -T <SEND_T> -s -f <file>`, `tcu-cat -a 50 -s -m "=M4FLT= END name=<n>"`. `-a 50` gives up after 1 s of a mailbox that never empties. `SEND_T` is five seconds under the `bwait -k` bound, so the summary line is written before any kill.

**Two writers, one mailbox.** The console callout and `tcu-cat` each test FULL and then write (callout_debug_tcu.S:131-142; tcu-cat.c:59-89). If both write at once, one word can replace another before the SPE takes it, and neither side sees a drop (HYPOTHESIS). The script is silent while a block is sent (§4.1), so the only other console writers are the guard at expiry and kernel fault output. md5, cksum and the line count catch any such loss (§6.3).

### 5.2 Framing, per block

1. **Console:** `M4 FLT BEGIN name=<n> rung=<r> lines=<L> bytes=<B> wc_bytes=<W> md5=<md5> cksum=<crc>`. This goes to the black box and to COM3, and is the reference the PC checks against. `lines` and `wc_bytes` come from toybox `wc -l -c`, `bytes` from toybox `cksum`, which prints the CRC and the length.
2. **Silent:** `bwait -s 1`.
3. **TCU:** `=M4FLT= BEGIN name=<n> rung=<r>` and a newline.
4. **TCU:** the body, byte for byte, ending in a newline.
5. **TCU:** `=M4FLT= END name=<n>` and a newline.
6. **Console:** the three `BWAIT run prog=tcu-cat …` lines and the three `tcu-cat:` summaries, then `M4 FLT END name=<n> rc=<R>`.

`=M4FLT=` occurs in no console line (every console line of M4 starts with `M4 `, `M4C `, `BWAIT `, `TRCCTL `, `STAMP `, `tcu-cat:` or the client's fixed text), and the counter refuses to copy a listing line containing it (§4.5.8). The TCU marker lines and the body never enter the black box.

### 5.3 What reaches the black box before any listing byte

In order, for r1 (r2 is the same with `N2` iterations; r0 replaces the qvm and IPC items with clock, fixtures, probe and L0):
1. The shim, startup, census and `pidin info` lines (M3's, D3 §4.5 row 1).
2. `BWAIT guard armed secs=<guard_s> prio=50`.
3. `M4 CONFIG …`: rung, mode, the startup line, `-Q`, `-W`, `-A`, CPUs, guest, disk, configuration and client sha256, `clock=unverified`, and the trace parameters `kind`, `tl_args`, `iters`, `forms`, `trace_need_mb`, `transport`.
4. Preflight `BWAIT path` lines; `M4 MEM boot`; the pre-run `SMPCHECK done … rate=` lines.
5. `M4 CHECK md5_pre guest|disk|conf ok`; `M4 CHECK disk_copy ok`; `M4 MEM disk`; the qvm-check output.
6. The banner `BWAIT` line, the STAMP lines, `M4 MEM banner`, the first qvm `pidin` listing.
7. The grace `BWAIT` line; `M4 MEM trace_pre`; `M4 TRACE ARM …` (or `M4 FAIL mem_trace …`).
8. *(the silent window)*
9. `M4 STATE report_ipc`; the two `TRCCTL insert … rc= errno=` lines, `TRCCTL stop rc= errno=`, the stop `BWAIT` lines and tracelogger's `BWAIT run` line; `M4 STOP t by=<rung>`.
10. The client's four stdout lines and its `BWAIT run prog=qnx-host-client …` line; the head of its stderr; the second qvm `pidin` listing.
11. qvm's `rc=` line; `M4 CHECK md5_post guest|disk ok`; `M4 MEM released`; the post-run rate lines.
12. `M4 KEVFILE t path=/dev/shmem/t.kev bytes=<n>`; `M4 MEM preformat_t`; traceprinter's `BWAIT run` line; `M4 TEXT t bytes=<n>`; `M4 MEM formatted_t`; the counter's `BWAIT run` line. A shortfall prints an `M4 FAIL mem_format` line in place of the step it gated.
13. The counter's records (§4.5.8), with its `PASS` lines: IDs 0, 1 and 7 counted (`M4C QVM`), `TIME64`, `BUF`, `MARK`, `RING`, `RATE`, `VCPU`, `OFFSET`, `TRIPLES`, `PAIRS`, **the on-target `STAT` lines**, `WARN`, both `FLT` lines, `END`.
14. The summary reprint: STAMP lines, the IPC lines, the key `M4C` lines; `M4 FAIL_STATE <x>`.
15. For the first block: the three hash `BWAIT run` lines, the md5, cksum and wc output, and `M4 FLT BEGIN name=<n> … md5=… cksum=…`.

The first TCU byte follows item 15. The budget (§8.3) keeps items 1-15 well under the 65,520 B cap (callout_debug_tcu.S:122-124; t234_startup.h:118-119); gate G1-M4 (§8.3) rebuilds at `-vv` if a black box reaches 60,000 B.

### 5.4 Listing form and caps (decisions D2 and D7)

| Rung | Blocks, in order | Caps (B) | Budget time at the 115200-baud ceiling | Budget time at the 5,000 B/s floor |
|---|---|---|---|---|
| r0 | `v` (L0 window) | 262,144 | about 23 s | 53 s |
| r1 | `v` (whole window), `c` (all pairs) | 1,048,576; 524,288 | about 91 s; 46 s | 210 s; 105 s |
| r2 | `c` (all pairs), `v` (sample) | 1,048,576; 131,072 | about 91 s; 11 s | 210 s; 27 s |

- **D2:** verbatim at r1, so the PC checks the counter without trusting it; compact at r2, once r1's pair-for-pair check passed. r2 keeps a small verbatim sample so every T-run carries an independent spot check.
- **D7:** 1 MiB at r1; r2's send bounds come from r1's measured `tcu-cat` rate, and a block whose bound would exceed 600 s has its cap halved (§2.4).
- **The rate** is 115200 8N1, about 11.5 KB/s at most (plan:232). That `tcu-cat` reaches it is HYPOTHESIS (plan:94); r0 measures it.
- **D8 (a larger black box):** not implemented. It is considered only if r1's transfer is lossy (§12.3).

---

## 6. PC side

### 6.1 COM3 capture (`m4/capture-com3-raw.ps1`)

```
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\m4\capture-com3-raw.ps1 -Port COM3 -Baud 115200 -Seconds <capture_s> -Out <file>
```

- Opens the port as `capture.ps1` does (8N1, no handshake, DTR and RTS on).
- Writes the header `--- raw capture started on COM3 at 115200, <ISO 8601> epoch=<Unix seconds> seconds=<Seconds> ---` and a LF through a `FileStream`. `epoch` comes from `[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()`, VERIFIED to run under PowerShell 5.1 on this PC. It then loops until the deadline: `$n = $port.BaseStream.Read($buf, 0, 65536)`, catching `TimeoutException` with `ReadTimeout = 500`; writes `$buf[0..n-1]` unchanged; flushes after each write.
- Ends with a LF and `--- raw capture ended <ISO 8601> bytes=<n> ---` and a LF.
- On an open failure it writes `FAILED to open COM3: <message>` and exits 1 (the port is exclusive).
- **Why a new script:** `capture.ps1` reads with `ReadExisting()` into a text `StreamWriter`, which decodes and re-encodes (the untracked `capture.ps1` that M2 and M3 ran). That is safe for ASCII but not byte-exact.
- **Always launched from PowerShell,** never from a Git Bash background job, which receives nothing (m2-runs.md:135-137).
- **Its lifetime is checked, not assumed** (review V1). The capture is a separate process with its own timer, and the harness can wait well past the base return bound. First come the pre-kexec sessions, which run before the bound's clock starts (m3-board.sh:776); then the bound; then one 600 s extension (§7.2 item 5).
  - `capture_s = return_bound_s + 3000` (§3.3).
  - `m4-board.sh run` refuses to start, or to kexec, when the header's `epoch + seconds` leaves too little time (§7.2 item 3).
  - The capture is stopped only after `run` returns, by `m4-tloop.ps1` or by the operator (§10 D).

  Its `-Seconds` is a safety net that the harness's own wait cannot outlast.
- **`m4/m4-tloop.ps1 -Image <image> -Start 1 -End 5 -RecordDir <dir>`** runs T1-T5 back to back, as the untracked `m3-tloop.ps1` did for M3: for each run it stops any older capture (matching `capture-com3-raw.ps1` in the command line), starts a new one with `-Seconds` set to `capture_s` from `<image>.params`, waits up to 20 s for its header, runs `bash orin-native/startup/m4-board.sh run <image>` with `M4_RUN_ID=t<i>` and `M4_COM3_LOG`, stops the capture, and stops the loop at the first run whose parse log lacks `M4PC run_verdict=pass`. `ORIN_HOST` and `ORIN_KEY` are inherited from the caller's environment; no address, user or key path is written in the script.

### 6.2 `m4/parse-m4.py` (Python 3, standard library only)

```
parse-m4.py run --params P --blackbox FILE|none --com3 FILE --run-id ID --out-dir DIR [--csv FILE]
parse-m4.py size-r1 --r0-parse LOG [--out FILE]
parse-m4.py size-r2 --r1-parse LOG --r0-parse LOG [--out FILE]
parse-m4.py series --parse-logs L1 L2 L3 L4 L5 --csv FILE --cloud-csv FILE --out-dir DIR
parse-m4.py selftest --fixtures DIR [--m4c FILE] --out-dir DIR
parse-m4.py regress-7b --listing FILE --out-dir DIR
parse-m4.py kshcheck FILE | --selftest
```

**Output rules.** Every file it writes must satisfy `git check-ignore -q` (a read-only query, as make-m3-images.sh:298-303), must not lie under `results/hw/` or `results/cloud/`, and is refused otherwise (exit 2). Results are `M4PC key=value` lines in `<out-dir>/<run-id>-parse.log`, headed by the sha256 of the parser and of each input. User names become `<user>` (m4dry/parse-m4dry.py:103-123). The default `--out` of `size-r1` and `size-r2` is `orin-native/shim/out/m4/<next image>.size`. `kshcheck` writes no file. It prints `KSHCHECK ok`, or one `KSHCHECK violation file=<f> line=<n> rule=<1-3>` line per finding, and exits 0 or 1 (§3.4 step 9).

**`run`, step by step:**
1. **Read** the black box and the COM3 file as bytes (latin-1 decoding is lossless); drop the capture's own header and end lines. If a `--- raw capture ended` line comes before the last block's END marker, record `com3_ended_early=yes`.
2. **Records:** every `M4 `, `M4C `, `BWAIT `, `TRCCTL `, `STAMP `, `tcu-cat:`, `samples=`, `P50=` and `sentinel_` line of each record, CR stripped. `records_consistency=identical|bb-prefix|differ` compares them in order, with the black box's head allowed to end early (startup/m3-board.sh:977-994).
3. **Blocks** (§6.3).
4. **Independent analysis** of block `v` with §4.5's rules (64-bit time, markers, cover, triples, pairs, classes, eligibility, statistics), written from §4.5, not from `m4count.c`. `v_complete=yes` when the counter's `M4C FLT form=v` line says `capped=0` and `flt_v=ok`.
5. **Cross-checks:**
   - `xcheck_stats`: with `v_complete=yes`, every `M4C TRIPLES`, `PAIRS` and `STAT` field equals the PC's (`match` or `differ(<fields>)`). `TIME64` is not compared, because its counts cover the whole listing and `v` is a selection; it is a gate instead (§4.5.3).
   - `c_stats`: the statistics recomputed from block `c`'s eligible lines equal `M4C STAT` (`match`, `differ`, or `partial(capped)`).
   - `xcheck_pairs`: every pair the PC found in `v` whose interval ends before the counter's `last_t` is matched to the `c` line with the same `dt_start_ticks`; class, eligibility, dwell and both CPUs must agree (`match compared=<n>` or `differ(<n>)`).
   - `p1_zero_verified`: for each of IDs 0, 1, 7 counted zero on the target, `yes` only when `v_complete=yes`, `ring=held` and the PC also counts zero (§1.7).
6. **Verdict:** `run_verdict=pass` or `fail(<criteria>)`, against §2.1, §2.2 or §2.3 for the params file's rung, with every criterion listed as its own `crit_<n>=` line.
7. **CSV** (§6.4), for runs `t1` to `t5` only.

### 6.3 Block checks

For each `M4 FLT BEGIN name=<n>` line (from the black box, else from COM3):
1. In COM3, find the line `=M4FLT= BEGIN name=<n> rung=<r>` after that console line, and the next line `=M4FLT= END name=<n>`. The body is every byte between them.
2. Remove every CR byte (the TCU path may add CRs, startup/m3-board.sh:981). The counter's `cr_bytes=0` shows no CR was in the file (§4.5.8).
3. Recompute: md5; POSIX cksum (CRC-32, polynomial 0x04C11DB7, length appended, inverted; m4dry/parse-m4dry.py:163-172); byte count; line count.
4. Compare all four with the BEGIN line: `flt_<n>=ok`, `mismatch(<fields>)`, `truncated` (no END line), or `absent`.
5. The body's `tcu-cat:` summary: `tcu_<n>=clean` needs `drops=0 aborted=0 deadline=0 rc=0`; otherwise `drops(<k>)`, `aborted`, `deadline` or `rc(<r>)`.
6. The body is written to `<out-dir>/<run-id>-flt-<n>.txt`.

**Never re-derive a listing on the PC from a `.kev`:** the host and target traceprinter builds print different text (DD:1591, D-h; DD:1706). The board never sends its `.kev` (plan:416-417).

### 6.4 The CSV writer

- **Path:** `--csv`, default `<out-dir>/orin-native-qvm-trace-latest.csv`, git-ignored under `out/` (.gitignore:53). `results/hw/orin-native-qvm-trace-latest.csv` (plan:418) is not git-ignored and the repo is public, so the parser never writes there; the orchestrator moves rows to the local branch `m3-results-unpublished` (plan:502-507).
- **Schema** (scripts/twin/diff-results.sh:17-19, :57): headerless rows `unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes`, one per T-run, LF-terminated, no blank line (diff-results.sh:61-64 reads the last line; :74-81 refuse an empty or header-only file).
- **Fields:**
  - `unix_ts`: the COM3 capture's end line as epoch seconds (HYPOTHESIS that this is the intended meaning).
  - `samples`: eligible clean pairs.
  - `payload_bytes`: `0` (decision N2).
  - `p50_ns`, `p99_ns`, `max_ns`: the clean statistics, from the PC's recomputation of block `c` when `c_stats=match`; otherwise the counter's, with `csv_source=target` in the parse log.
  - `cycles_per_sec`: `31250000`, refused if the listing's `cps` differs.
  - `notes`: `orin-native-el2host-qvm-class10-dwell;clock=unverified` (plan:420), plus `;p99=low-n` when `samples` < 10,000 (decision N3). It contains no comma (diff-results.sh:66-69 splits on commas).
- **Written only** when the run passed P2 and P3. A ledger `<out-dir>/csv-rows.log` refuses a second row for the same run id.

### 6.5 The series

`series` reads the five T-run parse logs and requires one kimg sha256 across them.
- **P4:** the median of the five clean `p50_ns`; each run's `|p50 − median| ≤ 0.20 × median`. It prints all five, the median, min and max (`p4=pass|fail`), and never a mean.
- **P5:** it runs `bash scripts/twin/diff-results.sh <cloud CSV> <M4 CSV>` under a 60 s timeout. `p5=pass` when it exits 0 and prints the three delta rows. Its closing warning describes the IPC legs (diff-results.sh:118-134) and mislabels a dwell row; the series log records that, and the script is not changed here.

`selftest` compares each fixture's PC reading with its `# expect:` lines, and with `--m4c` the board's `w=fix` records in order. `regress-7b` runs the PC analysis and parse-m4dry.py's `Analysis` (imported from its file) over one of 7b's host-format listings, a real 32-bit `t:` case, and reports complete triples, `offset_order` counts and the pair dwell multisets side by side, under `qhv/m4tcg/regress/` only.

---

## 7. Harness (`startup/m4-board.sh`)

A new file, copied from `startup/m3-board.sh` with the changes below. `m3-board.sh` is not edited. It runs on the PC in Git Bash and reaches the board over ssh and scp only; it never opens COM3 (m3-board.sh:13-15).

### 7.1 Kept unchanged from M3 (the safeguards)

| Safeguard | M3 source |
|---|---|
| Uptime refusal before a run, `M4_MAX_UPTIME_S` default 7,200 | m3-board.sh:702-704 |
| Governor pin, read-back gate, and re-pin after quiesce with a refusal to kexec unless both policies read `performance` | m3-board.sh:339-355, :710-736 |
| Quiesce gate: four `rmmod rc=0` and no Oops lines, else no kexec | m3-board.sh:739-750 |
| `kexec -s` (or `-c … -i` for K1), `kexec_loaded` check, `systemctl kexec` | m3-board.sh:323-362 |
| boot_id polling with keepalives under `timeout`, and the stuck-Linux stop | m3-board.sh:75-83, :404-445 |
| Black-box copy with sha256 equality, the new-`dmesg-ramoops` check, the validity lines, PMC `reset_reason` | m3-board.sh:370-381, :794-833 |
| Redaction, `check_private`, `.log` records | m3-board.sh:92-192 |
| `stage` (resumable, sha256-gated) and `p0` (acceptance of the kimg) | m3-board.sh:458-580 |

### 7.2 Changes

1. **Names.** `M3_*` variables become `M4_*`; images default to `../shim/out/m4`; `M4_RECORD_DIR` keeps the refusal of `results/cloud` and `results/hw` (m3-board.sh:150).
2. **Parameters.** `resolve_kimg` also reads `<image>.params`, refuses a missing file or a `kimg_sha256` that differs from the kimg's, and sets `M4_RETURN_BOUND_S` to `return_bound_s`. An override lower than that is refused.
3. **COM3** (review V1). `M4_COM3_LOG` must exist, begin with `--- raw capture started`, and carry `epoch=` and `seconds=` in that header. `capture_left_s = epoch + seconds − $(date +%s)`; both values come from the PC's one clock.
   - **Gate A,** at the start of `run`, before any board session: `capture_left_s ≥ return_bound_s + 2180`, else refuse and say to start a fresh capture with `-Seconds <capture_s>`. The 2,180 s is:
     - the four pre-kexec session bounds of `run`, 300 + 60 + 120 + 500 s (m3-board.sh:695, :711, :721, :740);
     - the kexec session, 300 s (:754);
     - the one extension, 600 s (item 5);
     - 300 s for the operator's five-minute no-growth watch (§8.4).
   - **Gate B,** a backstop just before the kexec session: `capture_left_s ≥ return_bound_s + 1200`, the last three of those terms. On failure there is no kexec and the harness exits 3. The board may already be quiesced, so L4T is rebooted before another attempt (m3-board.sh:746).
   - The COM3 file's size is recorded just before `systemctl kexec` and at the return.
4. **Fresh-boot quiesce rule (new gate).** With `M4_QUIESCE=1`, `run` refuses when L4T's uptime is at or above `M4_QUIESCE_MAX_UPTIME_S` (default 1,800) and says to run `m4-board.sh reboot` first. Grounds: Linux faulted in service teardown and in its own shutdown after hours of uptime, three times, one of them in M3's own `isolate` step (m2-runs.md:126-133; m1b-runs.md:54-58; a third, in the quiesce step of an M3 run, is in the operator notes). The 1,800 s threshold is HYPOTHESIS.
5. **Return bound.** From `.params` (r0 and r1: 3,000 s). **At the bound,** if the COM3 file grew during the last 60 s and holds no `--- raw capture ended` line, the bound is extended once by 600 s and the extension is recorded: a slow transfer is not a hang. Gate B (item 3) keeps the capture alive through the whole extension and for 300 s after it. Otherwise the M3 message stands: read COM3 first, then power-cycle (m3-board.sh:787-791).
6. **Step 8 order.** Copy the black box and COM3 to `$RECDIR/<image>-<run>-{blackbox,com3}.log`; run the parser on the raw copies (step 8b); only then run `privacy_scan`, whose redaction could otherwise change a body's bytes.
7. **Step 8b (new).** `timeout 900 python orin-native/m4/parse-m4.py run --params <image>.params --blackbox <bb> --com3 <com3> --run-id <image>-$M4_RUN_ID --out-dir $RECDIR/out`, and the `M4PC run_verdict=` line into the board log. `M4_RUN_ID` is required: `r0`, `r1`, `q`, `t1` to `t5`.
8. **`extract_file`.** The line pattern (m3-board.sh:874) gains `M4 (CONFIG|CHECK|FAIL|MEM|QVM|STATE (end|diag)|TRACE|STOP|KEVFILE|TEXT|FLT)`, `M4C (QVM|TIME64|RING|VCPU|OFFSET|TRIPLES|PAIRS|STAT|WARN|FLT|END)`, `TRCCTL ` and `tcu-cat:`. The STAMP, IPC, MEM and rate extractions stay. The G1 size message uses §8.3's gate.
9. **`NEG_TOKENS`.** M3's list (m3-board.sh:850-857), with `M3 FAIL` matched as `M4 FAIL([^_]|$)`, plus fixed strings `rc=-1` on `TRCCTL` lines, `by=early`, `by=sigint`, `by=kill`, `by=none`, `path=none`, `aborted=1`, `deadline=1`, `state=wrapped`, `state=unknown`, `mem_trace`, `mem_format`, and the patterns `mismatches=[1-9]`, `order_violated=[1-9]`, `drops=[1-9]`, `marker_collision=[1-9]`, `M4C END w=[a-z0-9]+ rc=[13]`. M3's `killed=1` stays.
10. **`consistency_files`.** The compared lines (m3-board.sh:978) gain `M4C .*`, `M4 (TRACE|STOP|KEVFILE|TEXT|FLT) .*`, `TRCCTL .*` and `tcu-cat: .*`.
11. **New subcommands:** `size-r1 LOG` and `size-r2 LOG` (wrappers of `parse-m4.py size-r1|size-r2`), and `series LOG…`.

---

## 8. Bounds, memory and heat

### 8.1 Guard arithmetic

`N+5` is a `bwait -k N` (SIGKILL at N, then up to 5 s, bwait.c:303-311). A `bwait -p` can overrun by one 50 ms poll. Commands outside `bwait` (devb-loopback, `pidin`, `slay`, `rm`, `trcctl`, `stamp -n`, the prints) are bounded only by the guard, as in M3 (D3:625-631).

**Worst case of the ksh, by state** (seconds):

| State | r0 (trace) | r1 (full) | Derivation |
|---|---|---|---|
| preflight | 30 | 30 | 10+10+5+5 |
| rate_pre | 20 | 20 | collector `-T 20` (D3:586) |
| integrity_pre | 35 | 35 | 30+5 |
| clock | 125 | — | 120+5 |
| fixtures | 75 | — | 3 × (20+5) |
| disk | 80 | 80 | (30+5) + (30+5) + 10 |
| probe | 167 | — | settle 2, gap 5, ladder 120+30+10 |
| l0 | 298 | — | settle 2, gap 6, wait 130, ladder 160 |
| hostcheck | — | 15 | 10+5 |
| window | — | 247 | reader 5, banner 240, settle 2 |
| ipc | — | 407 | grace 0 (D3:620), settle 2, client 240+5, ladder 160 |
| teardown, integrity_post | — | 60 | 15+5+5; 30+5 |
| rate_post | 20 | 20 | as rate_pre |
| format and count | 175 + 125 + 655 + 125 | 655 + 125 | per listing: wc 25, traceprinter TP+5, wc 25; counter 120+5. Probe TP = 120; L0 and r1 TP = 600 |
| send | 179 | 336 + 231 | per block: hashes 3 × 25, pause 1, markers 2 × 15, body SEND+5; SEND: r0 68, r1 225 and 120 (the 5,000 B/s floor) |
| diag | 20 | 20 | slog2info 15+5 |
| **ksh total** | **2,129** | **2,281** | |
| outside the ksh | 125 | 125 | M3's allowance for census, daemons, `smpcheck -z 3`, prints and poll overruns (D3:621-624) |
| **guard** | **2,700** | **2,700** | `ceil((ksh total + 125 + 240) / 300) × 300`; margins over the ksh total plus 125 s: 446 s and 294 s |

**r2's guard** follows from its parameters:

```
W(r2)     = 736 + BANNER_BOUND + IPC_BOUND2 + TP_BOUND2 + CNT_BOUND2 + SEND_C2 + SEND_V2
GUARD2    = ceil((W(r2) + 125 + 240) / 300) × 300        at most 3,600
TL_BOUND  = 2 + IPC_BOUND + 5 + 160 + 30
```

The constant 736 is every fixed term of the r1 column (r1: 736 + 240 + 240 + 600 + 120 + 225 + 120 = 2,281). The generator recomputes these and dies on any difference from the size file (§3.4 step 8).

**Minimum margin** (review V5). Every rung's guard leaves at least 240 s over its ksh worst case plus the 125 s allowance. Revision 1 left only what rounding to 300 s happened to leave, which for r2 could be a few seconds. 240 s was chosen below r1's 294 s margin so that r0 and r1 keep their 2,700 s guards; only r2, the rung whose terms vary most, can move.

**PC-side bounds:**
- return bound = guard + 300 s (M3: 900 + 300, m3-board.sh:41);
- COM3 capture = return bound + 3,000 s, with gates A and B on its remaining life (§3.3, §7.2 item 3);
- the parser, 900 s;
- the one-time COM3-growth extension, 600 s (§7.2 item 5).

For r0 and r1: guard 2,700 s, return 3,000 s, capture 6,000 s.

**Typical, not worst:** M3's QNX side took about 200 s (D3:1055-1060). M4 adds the trace window (seconds at r1), the traceprinter and counter passes (UNKNOWN on the board; r0 measures) and the transfer (about 2-4 minutes at r1 at the budget rate).

### 8.2 Memory budget at `-m992M` (design budgets only)

| Item | MiB | Class | Source |
|---|---|---|---|
| M3's committed estimate | 880.5 | HYPOTHESIS | D3:300 |
| M3's measured headroom at the banner | — | VERIFIED, in the unpublished M3 record's `MEM banner` lines (no figure here) | the unpublished M3 record |
| IFS growth (§3.1) | 0.4 | VERIFIED sizes plus estimates | §3.1 |
| Trace ring during the window, `ring_mb(K)` | 16 (K=256), 32 (K=512) | VENDOR_CLAIM: about 16 KB per buffer per CPU ([use-tl], DD:1604) | §2.4 |
| The `-M` object, at most `S(K)` | 20 (K=256), 36 (K=512) | HYPOTHESIS: whether `-M` holds a second copy is UNKNOWN (no source says); budgeted as a full copy | §2.4 |
| Margin in the gate | 32 | budget | §2.4 |
| **`TRACE_NEED_MB`** | **68 (256), 100 (512)** | runtime gate on `M4 MEM trace_pre` | §4.1 |

**After teardown and release,** about 512 (guest), 146.3 (disk copy), 21.8 (io-blk cache) and qvm's 16 MiB return (D3:295-298; HYPOTHESIS that each is freed), about 696 MiB. Then:

| Item | MiB, worst | Class |
|---|---|---|
| The `.kev`, at most `S(K)` | 36 (K=512) | stays until the reset |
| Text listing, 5 × `S(K)` | 180 (K=512) | budget ratio, shaped on the unpublished 7b record |
| Counter, `CNT_MB`: tables at the default caps, plus one more copy of the largest while it grows | 270 | budget (§4.5.8): about 180 plus about 84 |
| Blocks `v` and `c` | 1.6 | caps |
| **Total after release** | **about 490 of about 696 freed** | HYPOTHESIS |

**Format and count gates** (review V4, §4.4). The generator bakes both and recomputes them at §3.4 step 8. Each is checked against a fresh reading taken after the `.kev` exists, so the `.kev` is already inside the free figure:
- `FMT_NEED_MB = 5 × s + CNT_MB + ceil((cap_v + cap_c) / 2^20) + 32`, with `s` the listing's `-S` in MiB. It is checked against `M4 MEM preformat_<n>`: 404 at K=256, 484 at K=512, and 463 at r0 (L0's `-S 32M`, applied to the probe too).
- `CNT_NEED_MB = CNT_MB + ceil((cap_v + cap_c) / 2^20) + 32`. It is checked against `M4 MEM formatted_<n>`, once the text exists: 304 at r1 and r2, 303 at r0.

`M4 MEM` lines at `boot`, `disk`, `banner`, `trace_pre`, `released`, `preformat_<n>`, `formatted_<n>` and `end` (plus `probe_pre`, `probe_armed`, `probe_stopped` at r0) record what really happens. 7b's MB-resolution lines missed a small ring (the unpublished 7b record), which is why r0's probe uses 64 buffers per CPU (about 4 MiB) rather than a smaller ring.

### 8.3 Black-box budget and gate

The cap is 65,520 B, head kept (callout_debug_tcu.S:122-124). M3's estimate was about 27,000 B typical and 38,000 B worst (D3:875, HYPOTHESIS). Changes for M4 (budgets):

| Part | r1 typical (B) | r1 capped worst (B) |
|---|---|---|
| M3's parts (D3:865-875), with the guest text cut from 4,096 to 2,048 B and slog from 2,048 to 1,024 B | ~24,000 | ~35,000 |
| MEM lines (8 more), TRACE and STOP lines, trcctl lines | ~1,500 | ~2,000 |
| KEVFILE, TEXT, traceprinter and counter BWAIT lines | ~500 | ~500 |
| Counter records and PASS lines (§4.5.8) | ~3,200 | ~4,700 |
| Summary reprint of M4C lines, TIME64 included | ~1,300 | ~1,900 |
| Two blocks: hash lines, BEGIN, tcu-cat summaries, END | ~1,600 | ~1,800 |
| **Total** | **~32,100** | **~45,900** |

r0 carries no qvm, stamp or IPC lines but adds clock (~600 B), fixtures (~2,100 B) and three counter runs; its worst case is below r1's (HYPOTHESIS).

**Gate G1-M4:** a black box of 60,000 B or more on r0 or on Q rebuilds every later image at `-vv` (contingency C4), as M3's G1 and G2 (D3:877-878). **COM3 is a mandatory co-record** on every run (D3:879).

### 8.4 Heat

- **After kexec nothing drives the fan:** Linux's PWM fan driver is gone, and the board was seen powered with the fan stopped (m0-hang-watchdog.md:21-26, VERIFIED).
- **Proven so far:** a 60 s six-core busy load natively (plan:350-356) and M3's QNX side of about 200 s per run (D3:1055-1060). No firmware thermal trip has been seen or read (UNKNOWN).
- **M4 is mostly idle,** apart from the IPC window, traceprinter and the counter, but a run can last up to the guard (2,700 s at r0 and r1). The worst case is a hang with a busy vCPU and no reset, which ends only when the owner pulls the power; it is why every M4 board run needs the owner present (plan:454-457).
- **Operator rule:** if the board has not returned by `return_bound_s` and COM3 has not grown for 5 minutes, pull the power (§9, §10).

---

## 9. Failure-signature table

Keyed on the last distinctive line in the black box, COM3, the board log or the parse log. D3 §7's rows (D3:1096-1171) still apply unchanged to startup, qvm, the guest and the IPC pair, and are referenced, not repeated.

**Recovery classes.** **SR-bb:** self-recovering, black box kept (warm reset; PMC `MAINSWRST`, or `BCCPLEXWDT` while Linux still ran). **SR-L4T:** L4T never left; the harness exits 3. **PP:** power pull; the black box is lost, so read COM3 first (m0-hang-watchdog.md; plan:454-457).

| Observable | Meaning | Class | Operator action |
|---|---|---|---|
| `run` refuses: uptime at or above `M4_QUIESCE_MAX_UPTIME_S` | Stale L4T for a quiesce (§7.2 item 4) | SR-L4T | `m4-board.sh reboot`, then run again |
| `run` refuses at gate A, or issues no kexec at gate B: `capture_left_s` too small | The COM3 capture would end before the longest wait the harness can make (§7.2 item 3) | SR-L4T | Start a fresh capture with `-Seconds <capture_s>`; after gate B, reboot L4T first (the board may be quiesced) |
| `GOVERNOR PIN FAILED`, `QUIESCE FAILED`, `kexec NOT issued` | M3's Linux-side gates (m3-board.sh:710-772) | SR-L4T | Reboot L4T; rerun; never kexec part-quiesced |
| No `T234-SHIM`, a new `dmesg-ramoops` Oops, PMC `BCCPLEXWDT` | Linux died in its own shutdown | SR-bb | Not a run (validity rule); fresh L4T; retry the same kimg |
| `BAD-LANDING …`, then reset | Image not at 0x80080000 | SR-bb | Contingency K1 (D3:1085) |
| Black box ends at `JUMP` or any M1b startup row | Startup or kernel | SR-bb if it reset; PP if COM3 stops and nothing resets | D3 §7; if PP: read COM3, pull, record |
| COM3 stops before `BWAIT guard armed`, no reset by the return bound | A hang before the guard | PP | Read the COM3 tail; pull; record the lost black box |
| `Unable to start "tracelogger" (83)` or `"traceprinter"` | A library missing (UNKNOWN dependencies, as D3 §3.1) | SR-bb | Add the library from `qhvh/` lists; rebuild every image; rerun r0 |
| `M4 STOP <n> by=early` with a `spawn-failed` or `killed=1` tracelogger line | tracelogger did not start, or its kill bound fired | SR-bb | Read `<n>.err` in the record; fix; rerun the rung |
| `TRCCTL stop rc=-1 errno=<e>` | STOP refused on the board (TCG accepted it, DD:1597-1599) | SR-bb | Recorded; the ladder falls to SIGINT; owner before r1 if at r0 |
| `M4 STOP <n> by=sigint` | STOP did not end the ring; SIGINT did | SR-bb | Recorded; the window is usable if `KEVFILE` exists; stop reason goes to the run note |
| `M4 STOP <n> by=kill` or `by=none`; `KEVFILE <n> path=none` | No `.kev` | SR-bb | Rung not passed; read `<n>.out`, `<n>.err`; fix before rerun |
| r0 probe `M4C MARK start=absent` or `end=absent` | Markers not captured natively, or the zero-tail end marker was not flushed (§4.2) | SR-bb | Owner: add a 1 s tail (a design amendment) and rerun r0 |
| r0 probe `kept` above 65 on any CPU | `-k` does not size the ring per CPU on the board | SR-bb | Stop; the §2.4 rules are invalid; owner |
| r0 or r1 `M4C RING state=wrapped` | The ring overwrote part of the window | SR-bb | r0: owner. r1: contingency C1, then C2 |
| `M4C RING state=unknown` with both markers and `gaps` above 0 | A BUFFER sequence gap: dropped buffers | SR-bb | Recorded; pairs not eligible; rerun; owner if repeated |
| `M4 FAIL mem_trace free_mb=… need_mb=…` | Not enough RAM for the ring | SR-bb | Contingency C3 (half K); below 64: owner, M3's O7 (D3:1331) |
| `M4 FAIL mem_format name=<n> step=…` | Not enough RAM after release to format or count that listing; nothing was written or sent for it | SR-bb | Read the `MEM` lines. Owner: halve K (C3), or lower `-P`/`-T` with `CNT_MB` recomputed and E8 counting any cap hit; rebuild; rerun |
| `M4C TIME64 … mismatches=` above 0 | The target's `t:` is not the full count, or the msb logic disagrees | SR-bb | Hold r2; compare with the PC's reading of `v`; fix the counter and parser in lockstep |
| `M4C QVM enter=0` (or `exit=0`, `cycles=0`) at r1 | No Class-10 event natively | SR-bb | §1.7: verified zero → fallback amendment; unverified → rerun r1 |
| `M4C VCPU threads=` other than 1 | More than one thread emitted CYCLES | SR-bb | Recorded; pairing is per thread; owner before r2 |
| `M4C OFFSET distinct=` above 1 | The offset changed inside one qvm instance, against [TSC] | SR-bb | Recorded; dwells stand (offset cancels); window placement suspect; owner |
| `M4C TRIPLES … order_violated=` above 0 | Host and guest clocks disagree for those triples on silicon | SR-bb | Recorded; E2 excludes them; if most triples fail, owner before r2 |
| `M4C PAIRS … status_nonzero=` a large share of pairs | E3's reading of `status` is doubtful | SR-bb | Owner decision N5 before r2 |
| `M4C WARN clean_tail_bias …` | Preempted plus migrated at least 1 % | SR-bb | Not a failure; the run note says the clean P99 is not a guest-visible tail |
| `BWAIT run prog=traceprinter … killed=1` | TP bound too small for the board | SR-bb | Rebuild the rung with a larger TP bound (guard recomputed); rerun |
| `BWAIT run prog=m4count … killed=1` or `M4C END … rc=3` | Counter bound or a table cap hit | SR-bb | The last `M4C PASS` line shows how far a killed counter got (none means pass 1 never ended). Raise `CNT_BOUND` from that, or `-P`/`-T` within §8.2; rebuild; rerun |
| `M4C IN … events=0` or `M4C END … rc=1` | The listing is empty or not in the expected layout; with `reason=nomem`, an allocation failed (§4.5.8) | SR-bb | Read `cnt.err` and `M4C SAMPLE`; owner. For `nomem`, as the `mem_format` row |
| `tcu-cat: … drops=` above 0 | Mailbox stayed full for some words | SR-bb | Block fails P3; rerun; if repeated at r1, owner decision D8 |
| `tcu-cat: … aborted=1` | 50 consecutive full-mailbox words: the SPE stopped taking bytes | SR-bb | Block truncated; the on-target STAT lines still stand; rerun once; then owner |
| `tcu-cat: … deadline=1`, or its bwait `killed=1` | Rate below the send bound's floor | SR-bb | Recompute SEND from the measured rate (§2.4 step 6); rebuild; rerun |
| `flt_<n>=mismatch(…)` with `drops=0` | Silent loss: two mailbox writers, or the capture | SR-bb | Rerun; confirm the raw capture was the only COM3 reader; if repeated, owner (D8) |
| `flt_<n>=truncated` | No END marker: the guard fired mid-send, or the capture ended | SR-bb | Check for `BWAIT guard deadline`, and for `com3_ended_early=yes`: gates A and B rule out the capture's own timer, so that means a capture stopped by hand or failed. Fix; rerun |
| `M4C FLT … marker_collision=` or `cr_bytes=` above 0 | Framing or CR stripping unsafe | SR-bb | Fix the counter; rerun |
| Parse log: `records_consistency=differ` | A console-path drop on COM3 or in the capture | — | The black box is the record of the numbers; flag in the run note |
| Parse log: `xcheck_pairs=differ(…)` or `xcheck_stats=differ(…)` at r1 | Counter and parser disagree | — | No r2. Fix the defect in both implementations in lockstep; rerun §11, then r1 |
| Parse log: `c_stats=differ` | Arithmetic defect in one implementation | — | As above |
| `size-r2` exits 3 with `p2_reachable=no` or `p99_reachable=no` | r1's clean-pair yield cannot reach the target within the ring and guard limits (§2.4 step 11) | — | Owner, before any r2 image. For P99: accept a non-quotable P99 (`--accept-low-n`), or look into the low yield first. For P2: no r2 image is built |
| `M4PC series … p4=fail` | P50 spread beyond ±20 % | — | M4 fails (F2); report all five, median, range |
| `M4PC series … p5=fail` | CSV not consumed | — | Fix the writer on the PC; no board run needed |
| `BWAIT guard deadline=<g> expired: sysmgr_reboot`, then reset | A bound missing, or an unbounded command stalled; the last `M4 STATE` names it | SR-bb | Fix before the next run |
| Guard line printed, no reset (R25 of D3) | `sysmgr_reboot()` did not reset | PP | Read COM3; pull; record |
| Not back by `return_bound_s` (+ the one 600 s extension), COM3 not growing for 5 minutes | Hang, possibly with a busy vCPU and no fan | PP | Read the COM3 tail first, pull the power, record the black box as lost, let L4T boot, reboot once more before any next run |
| Kernel `Shutdown[` dump, then a warm reset | Host kernel abnormal termination reset through `-A` | SR-bb | Record the dump; owner |
| Black box 60,000 B or more | G1-M4 | SR-bb | Contingency C4 (`-vv`) for every later image |

---

## 10. Pre-flight checklist for the owner (the first board rung, r0)

**The owner is at the plug for every M4 board run.** A native image that hangs after kexec does not recover: WDT0 does not fire (plan:454-457), and a hung busy loop has no fan (§8.4). No M4 image runs unattended.

**A. The day before, or before leaving the PC (no board contact)**
- [ ] §11 rehearsal passed for all three variants (`r0`, `k512`, `k16`), with `canonical=ok` before and after each.
- [ ] `python orin-native/m4/parse-m4.py selftest --fixtures orin-native/m4/fixtures --out-dir qhv/m4tcg/selftest` passes.
- [ ] `make -C orin-native/tools` in the SDP environment; `sha256sum orin-native/tools/smpcheck` equals `f8e2c307…66b0`.
- [ ] `make-m4-images.sh m4-r0` exits 0; its table printed; note `m4-r0.kimg` sha256 and `capture_s` from `m4-r0.params` (6,000).
- [ ] The table's dumpifs step listed every name once and every `ABSENT_NAMES` entry absent; `kshcheck --selftest` and `kshcheck` on the generated ksh passed; `git status` unchanged.

**B. At the board, morning**
- [ ] L4T freshly booted. If its uptime is 1,800 s or more, `./orin-native/startup/m4-board.sh reboot` and wait for the new boot_id.
- [ ] Shell environment: `ORIN_HOST`, `ORIN_KEY` set (never written to a file); `M4_RECORD_DIR=results/orin-native-port/<utc>/m4` (new); `M4_RUN_ID=r0`; `M4_QUIESCE=1`; `M4_GOVERNOR_PIN=1`.
- [ ] `m4-board.sh stage m4-r0` ends `stage PASS` (the board's sha256 equals the PC's).
- [ ] `m4-board.sh p0 m4-r0` ends `p0 GATE step 4 PASS: rc=0, then 1, then 0`.
- [ ] PowerShell: stop any old capture (the port is exclusive); start `capture-com3-raw.ps1 -Port COM3 -Seconds 6000 -Out results\orin-native-port\<utc>\m4\com3-m4-r0-r0.log`; the file shows `--- raw capture started … seconds=6000 ---` within 20 s. Start `run` soon after: gate A allows 820 s between the two.
- [ ] `M4_COM3_LOG=<that file>` exported in Git Bash.

**C. The run**
- [ ] `./orin-native/startup/m4-board.sh run m4-r0`; note the wall-clock time of `systemctl kexec`.
- [ ] Within about a minute COM3 shows `T234-SHIM`, then `T234 M4 r0 -P4: procnto up` and `BWAIT guard armed secs=2700`, then `M4 STATE` lines advancing.
- [ ] If COM3 stops growing for 5 minutes and the board has not returned, and the harness's return bound (3,000 s, plus one 600 s extension while COM3 grows) has passed: read the COM3 tail, pull the power, record.

**D. After the return**
- [ ] The harness shows `reset_reason=MAINSWRST`, the black box copied with equal sha256, and `M4PC run_verdict=pass` (else the failed `crit_` lines, and §9).
- [ ] Stop the capture.
- [ ] Black box under 60,000 B (the `extract size` line).
- [ ] The board log's `thermal` lines were recorded before kexec; no unexplained new `dmesg-ramoops`.
- [ ] Only then: `./orin-native/startup/m4-board.sh size-r1 <r0 parse log>`, and the owner reviews r0's record before r1 is built.
- [ ] Nothing is committed or pushed; every record stays in git-ignored paths until the orchestrator moves it to `m3-results-unpublished`.

---

## 11. TCG rehearsal

Everything below runs on the Windows PC under QEMU TCG, with no board contact, one QEMU at a time, and the canonical `qhv/host/output` and `qhv/guest/output` only hashed.

### 11.1 What it can rehearse, and what it cannot

| Rehearsed under TCG | Not rehearsable under TCG |
|---|---|
| The generated `m4-host.ksh` under QNX ksh: every construct, the pipe-free rule, `read -r`, functions, `( … ) &` | The TCU mailbox, `tcu-cat -f/-a/-T/-s` against a real SPE, its rate and drops |
| Arm, zero-tail markers, the stop ladder, `ring=held` and `ring=wrapped` | The black box, its cap and G1-M4 |
| Target `traceprinter -n -o` on real target listings | The board's event and buffer rates, so K1 and K2 |
| `m4count` on target listings and on the three fixtures | `el2-host` (VHE) on Cortex-A78AE; the TCG host is `startup-qemu-virt -Q enable` (D3:225) |
| toybox `md5sum`, `cksum`, `wc -l -c` read back without substitution | Four physical CPUs (TCG runs `-smp 2`), `-m992M` headroom, the release step's real gain |
| The framing, over the console instead of the TCU | Board traceprinter and counter speeds, the guard's real margin |
| `parse-m4.py run` on a byte-exact serial file, the block checks, both cross-checks, the CSV writer, `size-r1`, `size-r2`, `selftest`, `regress-7b` | kexec, the quiesce, heat, native exit mix, native dwell values: every TCG figure is emulated and is never a number (DD:1353-1356) |

### 11.2 The variant host (`m4/build-m4tcg-image.ps1`)

```
powershell -ExecutionPolicy Bypass -File orin-native\m4\build-m4tcg-image.ps1 -Variant r0|k512|k16 [-Tag <t>]
```

Derived from `m4dry/build-m4dry-image.ps1` (steps 1-9, :20-34), with only these changes:
- **Root** `qhv/m4tcg/` (git-ignored, .gitignore:16). Every path is refused unless under it, and never under `qhv/host` or `qhv/guest` (build-m4dry-image.ps1:128-137). Build into `host-<variant>[-<tag>]`, refusing a non-empty directory.
- **Canonical checks** before and after, exactly as build-m4dry-image.ps1:141-170.
- **Guest copy** `qhv/m4tcg/guest` through `guest.partial`, with both pins before and after (:173-184, :260-271).
- **Tools:** `make -C orin-native/tools bwait trcctl stamp clkcmp m4count` in the SDP environment, bounded (:275-287). Not `tcu-cat`: under QEMU `virt`, 0x0C168000 is not a TCU mailbox, so it is never run there.
- **Staged files** (LF, no BOM, :104-107): the generated `m4-host.ksh` (§4.1 template, TCG profile below); `m4-g2.conf` = the stripped `qhvconf/g2-m3.conf` with `load /proc/boot/guest-ifs.bin` put back to `load /data/hypervisor/guest/ifs.bin`, which must equal the as-run printf text (the expansion make-m3-images.sh:397-421 computes); the three fixtures; `m4tcg.params`.
- **`system_files.custom` lines** added: `bin/traceprinter=usr/bin/traceprinter`, `lib/libtraceparser.so.1=usr/lib/libtraceparser.so.1` (as :316-317), and `[perms=555]` `bin/bwait`, `bin/trcctl`, `bin/stamp`, `bin/clkcmp`, `bin/m4count`, `bin/m4-host.ksh`; `[perms=444]` `bin/m4-g2.conf`, `bin/m4fix-1.txt`, `bin/m4fix-2.txt`, `bin/m4fix-3.txt`.
- **Snippet** `m4/post_start-m4tcg.custom`: two lines, `ksh /system/bin/m4-host.ksh` and `shutdown -S reboot` (QEMU exits under `-no-reboot`, DD:61).
- **Text checks** after mkqnximage (as :391-429): `post_startup.sh` runs `m4-host.ksh` and has no `qvm @`; `system.build` has every added line plus `bin/tracelogger=usr/sbin/tracelogger` and `lib/libtracelog.so.1`; `system.build` or `ifs.build` provides `md5sum`, `cksum`, `wc`, `cp`, `cmp`, `rm`, `head`, `tail`, `grep`, `cat` (qhvh/system.build:129, :155, :161, :204; qhvh/ifs.build:73, :79-80; the rest checked by name); `data.build` sources the guest from `qhv/m4tcg/guest`.
- **The pipe-free check:** `parse-m4.py kshcheck --selftest`, then `kshcheck` on the generated ksh, the same implementation as §3.4 step 9.

**TCG profile values** for the §4.1 markers: `RUNG=tcg-<variant>`; `MODE=trace` for `r0`, `full` for `k512` and `k16`; `P=2`; `CPUS="0 1"`; `RATES=0`; `B=X=/system/bin`; `GUEST_IFS=/data/hypervisor/guest/ifs.bin`; `GUEST_DISK=/data/hypervisor/guest/disk-qvm`; `CONF=/system/bin/m4-g2.conf`; `CLIENT=/data/hypervisor/qnx-host-client` (m4dry/m4dry-host.ksh.in:15, :237); `IO_BOUND=600`; `ITERS=15`; `IPC_BOUND=600`; `BANNER_BOUND=600`; `GRACE=150`; `GRACE_WAIT=160` (DD:358); `KIND=ring`; `TL_ARGS='-r -k 512 -M -S 36M'` (`k512`, the size that held under TCG, DD:1701-1704) or `'-r -k 16 -M -S 4M'` (`k16`, built to wrap); `TL_BOUND=797`; `TRACE_NEED_MB=100` or `36`; `FMT_NEED=463` (`r0`), `484` (`k512`) or `324` (`k16`), and `CNT_NEED=303` (`r0`) or `304` (§8.2's formulas with the variant's `-S` and caps; the TCG host has `-m 2G`, m4dry/launch-m4dry-tcg.ps1:372); `TP_BOUND=1800`; `CNT_BOUND=900`; `HASH_BOUND=120`; `CNT_OUT` and `FORMS` as r0 (`r0`) or r1 (`k512`, `k16`); `SEND_*=1800` (unused on the console path); `TRANSPORT=console`; `FIX` the three `/system/bin/m4fix-*.txt`; `STARTUP_LINE='tcg-profile'`; `A=0`; the hash markers from the rehearsal's own guest copy and staged configuration. **The `-k` values are TCG-only and are never copied to a board image** (DD:1710-1715).

### 11.3 The launch (`m4/launch-m4tcg.ps1`)

```
powershell -ExecutionPolicy Bypass -File orin-native\m4\launch-m4tcg.ps1 -Attempt <N> -Variant r0|k512|k16 [-Tag <t>]
```

Derived from `m4dry/launch-m4dry-tcg.ps1` (steps 1-11), with these changes:
- The same QEMU argument list (its `-WithRng` list, only the two image paths and the serial file changed), `-WallSeconds` default 7,200, `-MinFreeGB 4`.
- **Refuses to start if any `qemu-system-aarch64` process exists** (one QEMU at a time); stops QEMU in `finally` and confirms it gone with the bounded re-check of DD:1587 (D-e).
- **Writes** `qhv/m4tcg/attempt<N>/serial-raw.log` (QEMU `-serial file:` is byte-exact) and `results/orin-native-port/20260910T2307Z/m4-tcg/attempt<N>-launch.log` (`*.log`, git-ignored).
- **Then runs, bounded by `-ParserSeconds` (default 2,400):** `python orin-native/m4/parse-m4.py run --params qhv/m4tcg/stage-<variant>/m4tcg.params --blackbox none --com3 qhv/m4tcg/attempt<N>/serial-raw.log --com3-format qemu-serial --run-id tcg-<variant>-a<N> --out-dir qhv/m4tcg/attempt<N>/out --csv qhv/m4tcg/attempt<N>/out/rehearsal.csv --rehearsal`. `--com3-format qemu-serial` accepts a file with no capture header; `--rehearsal` marks every board-only criterion `n/a(tcg)`, allows `cps` other than 31,250,000, and writes the CSV row with notes `m4-tcg-rehearsal;emulated;not-a-result`, never to `results/`.
- Canonical hashes after; `survivors=none` after both QEMU and the parser.

**Order:** `r0`, then `k512`, then `k16`. Each question assumes the one before it holds.

### 11.4 Pass criteria

| Variant | Passes when |
|---|---|
| `r0` | `M4 FAIL_STATE none`; three `CLK VERDICT` lines `agree` or `agree-within-resolution`; `selftest --m4c <serial>` matches every fixture's `# expect:` lines; probe `STOP p by=stop`, `MARK start=found end=found`, `RING state=held`, `kept` ≤ 65 on CPUs 0 and 1, `TIME64 mismatches=0`; `STOP l0 by=self`; `flt_v=ok` over the console; `run_verdict=pass` with board-only items `n/a(tcg)` |
| `k512` | The IPC completion rule (15 iterations); `TRACE ARM`, `STOP t by=stop`; `RING state=held`; `QVM` enter, exit and cycles above zero; `VCPU threads=1`; `OFFSET distinct=1`; `TRIPLES … order_violated=0`; `TIME64 mismatches=0`; `flt_v=ok`, `flt_c=ok`; `xcheck_pairs=match` with `compared` above zero; `xcheck_stats=match` when `v` was not capped, else `c_stats=match`; exactly one row in `rehearsal.csv`, and `bash scripts/twin/diff-results.sh results/cloud/cloud-ipc-latest.csv qhv/m4tcg/attempt<N>/out/rehearsal.csv` exits 0 |
| `k16` | `RING state=wrapped` with `wrapped_cpus` not `none`; `PAIRS eligible=0`; the PC's reading of `v` agrees on `ring`, `wrapped_cpus` and `eligible`; `M4C END rc=0` |
| all three | `canonical=ok` before and after; QEMU and parser gone; no `M4 FAIL` other than none |
| PC only | `selftest` passes; `regress-7b` on one of 7b's git-ignored host-format W2 listings reports equal complete-triple and `offset_order` counts between `parse-m4.py` and `parse-m4dry.py`, with any dwell multiset difference explained by time-order against file-order pairing (§4.5.5) |

A failure is fixed in the template, the counter or the parser, and the variant is rebuilt with a new `-Tag` and rerun. r0 on the board waits until all rows pass (§10 A).

---

## 12. Limits, risks and decisions

### 12.1 What M4 cannot show

From plan §7 (plan:436-458), as they bear on M4, plus what this design adds:
1. **Not a firmware-booted QNX.** kexec entry; DRAM, caches, clocks and thermal state are inherited (plan:438-440).
2. **Nothing about DRIVE OS,** the NVIDIA hypervisor stack, DRIVE AGX Orin, QNX OS for Safety, ASIL or certified BSPs (plan:441-442).
3. **No peripheral or DMA path** (plan:443-444). One guest, one vCPU, pl011, virtio-console, virtio-blk and an inert shmem vdev.
4. **Not the heterogeneous QNX-Linux topology natively** (plan:445-447).
5. **Not at a known CPU frequency:** `clock=unverified` plus M3's busy-loop rates (D6(a); plan:448-449).
6. **Not a one-variable twin diff:** a third host bundle (plan:450-452).
7. **Not below the 32 ns quantum, and not uninstrumented:** `procnto-smp-instr`, tracelogger and every emitted event are inside each dwell, so values are upper bounds (plan:453-455; [TE] VENDOR_CLAIM that ID 0's timestamp is not guest time).
8. **Not a long soak** (plan:456-457).
9. **Not publishable** before the 4.6(i) consultation (plan:458).
10. **Not the guest-visible tail:** the headline uses clean pairs only; preempted and migrated exits are reported beside it (§1.6).
11. **Not an exit-reason breakdown:** `hw_reason` is recorded, never interpreted.
12. **Not a complete trace:** a held ring and contiguous buffers show no loss inside the window, not that every exit was traced.
13. **Not the IPC benchmark:** IPC figures taken with tracing active are not Phase-2 or M3 results.
14. **No TCG figure is an M4 number:** §11 validates tooling only.

### 12.2 Risks

| # | Assumption | Class | Answered by |
|---|---|---|---|
| M1 | tracelogger, traceprinter and their libraries start natively under `el2-host` at `-P4` with qvm present | HYPOTHESIS (they ran at `-Q disable -P6`, m2-runs.md:62-78) | r0 |
| M2 | `-M -f /dev/shmem/<name>` lands at the literal path on the board | VERIFIED under TCG (DD:1404); board HYPOTHESIS | r0 probe `KEVFILE` |
| M3 | `trcctl -x` makes a ring write and exit on the board | VERIFIED under TCG (DD:1405); board HYPOTHESIS | r0 probe `by=stop` |
| M4 | `-k` sets buffers per CPU on the board, each about 16 KB | VERIFIED under TCG (DD:1700); VENDOR_CLAIM size | r0 probe `kept`, MEM delta |
| M5 | A zero tail still writes the end marker at STOP | HYPOTHESIS (trailing buffer written under TCG, DD:1600) | r0 probe `MARK end=found` |
| M6 | The ring only needs to hold start marker to STOP; the per-CPU cover test detects wrap | HYPOTHESIS (ring semantics VENDOR_CLAIM, DD:402-404) | r0 probe; §11 `k16` |
| M7 | The 16-fold activity factor sizes r1's ring | HYPOTHESIS | r1 `ring=` and `last_seq` |
| M8 | BUFFER sequence numbers count buffers since tracelogger started (R37) | HYPOTHESIS, supported under TCG (DD:1701-1704) | r1 `first_seq`, `last_seq` against `kept` |
| M9 | The target traceprinter prints `t:` as the full 64-bit count on the board | VERIFIED under TCG (DD:1706); board HYPOTHESIS | `M4C TIME64 mode`, `mismatches` |
| M10 | Printed Class-10 field names on the board are those seen under TCG | HYPOTHESIS | r1 `M4C SAMPLE` |
| M11 | `H = guest − offset` orders every triple on silicon | VERIFIED under TCG only (plan:412) | `order_violated` every run |
| M12 | A vCPU stays on one physical CPU from entry to exit | HYPOTHESIS | `broken`, `alt_order` counts; §11 |
| M13 | `status` 0 marks meaningful ID 7 values (E3) | VENDOR_CLAIM ([TSC], DD:117) | r1 `status_nonzero` |
| M14 | WFI halts show as blocked pairs | HYPOTHESIS (DD:400) | r1 class counts with `hw_reason` |
| M15 | `traceprinter -n -o` writes the listing on the board | HYPOTHESIS (`-o` alone VERIFIED, m2.build.in:143) | r0 `TEXT` bytes |
| M16 | Board traceprinter finishes a ring's `.kev` within 600 s | UNKNOWN | r0 speeds, §2.4 step 4 |
| M17 | Text ≈ 5 × `.kev`; counter memory, growth transient included, within `CNT_MB` (§8.2) | HYPOTHESIS (budget) | `TEXT`, `MEM preformat_<n>` and `formatted_<n>`; no `mem_format`; no `reason=nomem` |
| M18 | Memory is freed by teardown, `slay devb-loopback` and `rm` | HYPOTHESIS | `MEM released` |
| M19 | `tcu-cat` reaches about 11 KB/s and drops nothing on long streams | UNKNOWN (plan:94, :232) | r0 summary, `flt_v` |
| M20 | Two mailbox writers do not collide during a silent send | HYPOTHESIS | `flt_*` md5 every run |
| M21 | The TCU path adds at most CRs to the listing bytes | HYPOTHESIS (m3-board.sh:981 strips CR) | `flt_*`, `cr_bytes=0` |
| M22 | `BaseStream.Read` in PowerShell 5.1 captures COM3 byte-exact | HYPOTHESIS | r0 `flt_v=ok` |
| M23 | toybox `cksum` prints CRC then length, `wc -l -c` prints lines then bytes | VENDOR_CLAIM (applets listed, qhvh/system.build:129, :204) | §11 r0; r0 BEGIN line |
| M24 | The guard at `SCHED_RR` 50 fires on time and resets, qvm present or not | HYPOTHESIS / UNKNOWN (D3 R25, R32) | only on expiry |
| M25 | The fresh-boot quiesce threshold avoids Linux's teardown faults | HYPOTHESIS (three events, §7.2 item 4) | every run's pstore check |
| M26 | No thermal trip within a 2,700 s worst case | UNKNOWN | owner present; `thermal` lines |
| M27 | 50 ms per iteration bounds r2's client | HYPOTHESIS (client.c:317 pacing plus unpublished M3 RTTs) | Q `ms=` |
| M28 | ≥ 10,000 eligible clean pairs are reachable within the ring and guard limits | UNKNOWN | `size-r2`'s `clean_pred` and `p99_reachable`, before any r2 image (§2.4 step 11) |
| M29 | The two implementations of §4.5 are independent enough to catch each other's defects | HYPOTHESIS | fixtures, §11, r1 criterion 5 |
| M30 | The capture's remaining life, read from its header and the PC clock, bounds when it ends | HYPOTHESIS (one clock; the capture's deadline loop, §6.1) | gates A and B; `com3_ended_early` never `yes` |
| M31 | A token-level `kshcheck` accepts every construct the template needs and rejects every pipe | HYPOTHESIS | its self-test; §11 runs the checked ksh under QNX ksh |

### 12.3 Owner decisions

The recommendation is adopted unless the owner says otherwise.

| # | Decision | Options | Recommendation and reason |
|---|---|---|---|
| D1 | Capture mode | (a) ring `-r -k K`, stopped by `trcctl -x`; (b) linear `-c -S` | **(a), with K from the board (§2.4); (b) only when a rule needs K above 512.** A ring flushes nothing inside the window; `-k` sizing is VERIFIED under TCG (DD:1700) |
| D2 | Listing form | (a) verbatim; (b) compact per pair | **(a) at r1, capped at 1 MiB; (b) at r2 once r1's pair-for-pair check passes,** plus a 128 KiB verbatim sample per T-run |
| D3 | Classification site | (a) PC from a listing with THREAD events; (b) counter on target | **(b), with (a) inside r1's cap as the cross-check.** Class needs THREAD events (m4dry-host.ksh.in:101 dropped them) |
| D4 | Headline | clean pairs, or all non-blocked | **Clean pairs in the CSV; all classes in the record; the 1 % warning** (§1.6) |
| D5 | Workload | 15 iterations only; a longer run | **15 at r1; then N2 for ≥ 10,000 eligible clean pairs with 1.5× margin, boot excluded** (§2.4) |
| D6 | Clock | (a) `clock=unverified` plus busy-loop rates; (b) PMCCNTR at EL2 | **(a).** (b) changes the pinned startup (make-m3-images.sh:96) and becomes its own later rung |
| D7 | Listing cap | fixed; derived | **1 MiB at r1; r2's bounds from r1's measured rate, cap halved if a send would exceed 600 s** |
| D8 | Larger black box | a user tool appending compact pairs to the 512 KiB console zone | **Only if r1's transfer is lossy.** Startup maps 64 KiB (t234_startup.h:118-119) |
| D9 | Arm WDT0 after kexec | arm it; defer | **Defer.** It would change the M1b pin and needs its own owner-present hang proof |
| N1 | r0's content | (a) no qvm; (b) qvm with an idle guest | **(a).** One variable per rung (D3 §2 rule 2): trace tools natively first. r1's sequence numbers correct the sizing either way |
| N2 | CSV `payload_bytes` | 0; 48 (the IPC frame) | **0.** A dwell has no payload; `diff-results.sh` will warn that it differs from the cloud row (:99-101), which is true |
| N3 | CSV `notes` below 10,000 samples | plan text only; append `;p99=low-n` | **Append `;p99=low-n`,** so a consumer of the CSV sees that P99 is not quotable |
| N4 | Fresh-boot quiesce gate | none (M3); uptime < 1,800 s | **1,800 s** (§7.2 item 4) |
| N5 | Eligibility E3 (`status` 0) | include; record only | **Include,** on [TSC]'s reading (VENDOR_CLAIM); revisit if r1 shows a large `status_nonzero` |
| N6 | Guard and presence | 2,700 s for r0 and r1, owner at the plug for every M4 run | **Adopt.** The guard follows from §8.1; presence from §8.4 |
| N7 | §11 before r0 | required; optional | **Required.** It catches template and counter defects without a kexec |
| N8 | CSV rows | T1-T5 one row each; one summary row | **One row per T-run,** never Q (§6.4) |
| N9 | COM3 capture | `capture.ps1`; the new raw script | **The raw script** (§6.1) |
| N10 | The M4 image carries `clkcmp` and the fixtures in every rung | yes; r0-only image content | **Yes.** One file list for every rung; the unused files cost about 30 KB |
| N11 | COM3 capture lifetime | revision 1's `return_bound_s + 300`; `return_bound_s + 3000` with gates on its remaining life | **The latter** (§3.3, §7.2 item 3). After gate A the harness can wait the return bound plus 2,180 s, pre-kexec sessions included, and the capture is stopped by hand or by `m4-tloop.ps1` after `run` returns |
| N12 | Memory shortfall before format or count | proceed and risk a starved run; skip the listing with `FAIL mem_format` | **Skip, recorded** (§4.4). A starved traceprinter or counter looks like a bound set too low, and the `.kev` is never sent either way |
| N13 | r2 predicted below 10,000 eligible clean pairs per run | build anyway; refuse unless the owner passes `--accept-low-n` | **Refuse unless accepted** (§2.4 step 11). A prediction below step 5's 1,200-pair floor is refused outright |
| N14 | Guard margin | rounding only (revision 1); at least 240 s over the worst case for every rung | **240 s** (§8.1). r0 and r1 keep 2,700 s; only r2 can move |

### Appendix A. Stale text to correct later (list only; the orchestrator edits other documents)

- **plan:394-399** still shows the `-r -M -S 8M` recipe and the grep; §4.2 and §4.4 replace both.
- **plan:416-417** "a filtered listing plus `cksum` and a line count": M4 sends md5, cksum, bytes and lines, verbatim and compact blocks (§5).
- **plan:417** "PMCCNTR calibration prints actual core MHz": `clock=unverified` under D6(a).
- **plan:418** CSV at `results/hw/…`: not git-ignored in a public repo; the parser writes under `…/m4/out/` (§6.4).
- **plan:94, K11** "1-2 min at 11 KB/s": r0 measures the rate.
- **plan:527** M4 effort row: the transport and parser now have a design.
- **CLAUDE.md, Phase 3b:** "the per-exit number (M4, blocked on dry run 7b)".
- **`tools/tcu-cat.c:16-18`** usage examples with pipes: add `-f`.
- **`m4dry/m4dry-host.ksh.in:276`** still names `QVMBY` (DD:1719-1720).

---

## 13. Review outcomes (revision 2)

Two reviews read revision 1, and both returned "sound with fixes". The first raised three minor issues. The second raised two blockers, two majors and one minor. Every issue was checked against its cited source before an outcome was chosen. All eight are applied and none is rejected; where the fix differs from the reviewer's, the last column says why. Three more issues (S1-S3) were found while applying them.

What did not change:
- No rung, image content, trace setting, transport, framing or CSV rule. The only sizing changes are the guard's minimum margin (V5) and the new reachability step (V7).
- r0's and r1's guards (2,700 s) and return bounds (3,000 s).
- No M1-M3 file, image, generator or pin, and nothing in `m4dry/`. Nothing was built or run for this revision.
- No measured figure. Every number added is a design constant: a bound, a budget or a gate threshold.

| # | Review | Severity | Issue | Outcome | Where, and why it differs |
|---|---|---|---|---|---|
| V1 | 2 | blocker | `capture_s = return_bound_s + 300` was 300 s shorter than the extended return bound. The capture is a separate timer that knows nothing of the extension, so a slow but good transfer could lose its END marker, and the operator's no-growth signal could come from the capture quitting | **Applied, widened** | **VERIFIED:** M3's `wait_new_boot_id` has no COM3-based extension (m3-board.sh:413-445), so the gap is new in M4.<br>**Widened (S3):** the return bound's clock starts only after the kexec session ends (m3-board.sh:776). The capture must therefore also outlast up to 980 s of pre-kexec sessions and the 300 s kexec session (:695, :711, :721, :740, :754), which neither the review nor revision 1 counted. `capture_s = return_bound_s + 3000` (§3.3).<br>**More than a larger number:** the capture header now carries `epoch=` and `seconds=`. The harness checks the capture's remaining life at the start of `run` (gate A) and before the kexec session (gate B), so its end is checked, not assumed (§6.1; §7.2 items 3 and 5). The capture is still stopped after the return, and `-Seconds` stays a safety net.<br>**Also:** §0, §2.0, §6.2 step 1, §8.1, §9 (two rows), §10 A and B, M30, N11 |
| V2 | 2 | blocker | The pipe-free check as worded (a line "contains" the pipe character) would reject the template's own OR lists, and no earlier generator implements such a check that would show the wording works | **Applied, widened** | **VERIFIED:** make-m3-images.sh and build-m4dry-image.ps1 have no pipe check, and M3's script uses OR lists (m3-host.ksh.in:52-55, :81, :98, :131, :135).<br>**Fix:** the check is now `parse-m4.py kshcheck`, one token-level implementation for both builds. It has a self-test of accepted and rejected lines and a negative test on an injected pipe (§3.4 step 9, §11.2).<br>**Implementable, VERIFIED on this PC:** an untracked scratch prototype of exactly this rule accepted and rejected every self-test line as §3.4 step 9 lists them. It passed the revised §4.1 template and failed a pipe injected on that template's last command line, naming that line. It is a prototype of the check, not the committed tool.<br>**Widened (S1, S2):** exempting OR lists alone would still have failed the template, and masking quotes alone would have passed a real pipe inside a nested shell's string |
| V3 | 2 | major | `bwait -k` points the counter's stdout at a file and kills with SIGKILL, and nothing required the counter to flush. A kill could therefore lose records already computed, including the STAT lines §4.5.6 says survive | **Applied, extended** | **VERIFIED:** bwait.c:252 (`O_TRUNC`), :262 (dup2), :307 (SIGKILL).<br>**Fix:** every record is flushed as it is printed, following smpcheck.c:131-139 (§4.5.8).<br>**Extended:**<br>- records `IN` to `WARN` print when pass 2 ends, before pass 3 writes any block;<br>- `PASS` lines mark each pass, so a kill shows how far the counter got, and the §9 row uses them to retune `CNT_BOUND`;<br>- a failed allocation ends with `reason=nomem`.<br>**Also:** §4.5.1, §4.5.6, §5.3, §8.3 |
| V4 | 2 | major | The format and count phase had no runtime memory gate, though its budget is the same order as the ring's, and a doubling allocator briefly needs more than its final tables | **Applied, as two gates** | **Fix:** a gate before traceprinter (`FMT_NEED_MB`, against `MEM preformat_<n>`) and one before the counter (`CNT_NEED_MB`, against the existing `MEM formatted_<n>`). Both are baked and recomputed by the generator. A shortfall prints `M4 FAIL mem_format` with `step=format` or `step=count` and skips that listing (§4.1, §4.4, §8.2).<br>**Differs:** the second gate reads memory after the text exists, which a single gate before traceprinter could not. The counter's budget becomes `CNT_MB = 270` MiB, its tables plus one more copy of the largest while it grows, and doubling now stops at each table's cap (§4.5.8).<br>**Also:** §3.3, §3.4 step 8, §7.2 item 9, §9, §11.2, M17, N12 |
| V5 | 2 | minor | r2's guard was only its worst case rounded up to 300 s, so its margin could be a few seconds, on the rung with the most variable terms | **Applied, differs** | **Differs:** a 240 s minimum margin for every rung, `ceil((W + 125 + 240) / 300) × 300`, instead of adding 300 s to r2 alone. 240 s sits below r1's 294 s margin, so r0 and r1 keep 2,700 s and one rule covers all three rungs. Adding 300 s to every rung would have moved r1 to 3,000 s for no new reason (§2.4 step 10, §8.1, N14) |
| V6 | 1 | minor | r1 and the T-runs did not gate on `M4C TIME64 mismatches=0`, though r0 and its TCG rehearsal did, and the PC/target cross-check did not compare it | **Applied: the gate, plus the reason** | **Fix:** r1's criterion 3 now requires `mismatches=0`, so Q and T1-T5 inherit it. The TCG `k512` row and the summary reprint gained it too. §4.5.3 now says what it guards: it is counted only on the direct 64-bit path, where it cannot move an event, and a rebuild error shows up as `backsteps64`, `order_violated` or `out_of_window`.<br>**Not added to `xcheck_stats`:** its counts cover the whole listing, and block `v` is a selection (§6.2 step 5).<br>**Not used:** the review's argument that the counter exceeds 2^32 ticks before QNX starts. No source read for this design shows whether `ClockCycles()` continues L4T's count across kexec (UNKNOWN), and the gate does not depend on it |
| V7 | 1 | minor | `size-r2` capped N2 at 13,200 without saying when the cap made 10,000 eligible clean pairs unreachable | **Applied, extended** | **Fix:** §2.4 step 11 computes `clean_pred` from r1's yield and the final N2, and prints `p99_reachable` (`yes`, `short-margin` or `no`) and `p2_reachable`. `size-r2` exits 3 on a `no` unless the owner passes `--accept-low-n`, which never overrides a predicted P2 miss. The generator refuses such a size file (§3.4 step 8).<br>**Extended:** the check runs after every step that can lower N2 (steps 5 and 10), not only after the cap.<br>**Also:** §3.3, §9, M28, N13 |
| V8 | 1 | minor | The pair interval converted its entry end with triple n's offset. That is correct only because [TSC] fixes the offset, which §4.5.5 never said | **Applied, differs** | **Differs:** each end now uses its own triple's offset, `[H_n(at_exit_n), H_n+1(at_entry_n+1)]`, which is exact whether or not the offset holds. The text now says that [TSC] fixes the offset and that `OFFSET distinct=1` checks it on every run (§1.2, §1.3, E5, §4.5.5). The dwell never used an offset |
| S1 | found applying V2 | blocker | The template's `mem()` used a case-pattern alternation (empty or non-digit), which a check that exempts only OR lists would still reject | **Applied** | The line is now two case patterns (§4.1), and rule 1 forbids alternation, which a token-level check cannot tell from a pipe |
| S2 | found applying V2 | major | A pipe inside a double-quoted string handed to a nested shell is a real pipe, and 7b's template ran four of them (m4dry/m4dry-host.ksh.in:91-103) | **Applied** | `kshcheck` rejects `ksh -c`, `sh -c`, `eval` and here-documents, so its quote masking is sound (§3.4 step 9, §4.1 rule 1) |
| S3 | found applying V7 | minor | §2.4 step 5's linear branch named `N_pairs`, which step 3 had already capped | **Applied** | Now step 3's `N2` |

**Edited, by row:**
- **V1:** header; §0; §2.0; §3.3; §6.1; §6.2 step 1; §7.2 items 3 and 5; §8.1; §9; §10 A and B; M30; N11.
- **V2, S1, S2:** §3.4 step 9; §4.1 rule 1 and `mem()`; §6.2 usage; §10 A; §11.2; M31.
- **V3:** §4.5.1; §4.5.6; §4.5.8; §5.3 item 13; §8.3; §9.
- **V4:** §3.3; §3.4 step 8; §4.1 `fmtcount`, format state and markers; §4.4; §4.5.8; §5.3 item 12; §7.2 item 9; §8.2; §9; §11.2; M17; N12.
- **V5:** §2.4 step 10; §8.1; N14.
- **V6:** §2.2 item 3; §4.1 summary state; §4.5.3; §6.2 step 5; §11.4.
- **V7, S3:** §2.4 steps 5 and 11; §3.3; §3.4 step 8; §9; M28; N13.
- **V8:** §1.2; §1.3; §1.4 E5; §4.5.5.

---

## 14. Implementation notes and deviations (as built, 2026-09-11)

The files §3.5 lists are written. **Nothing below was compiled, built, run or tested.** Command execution was blocked for the whole implementation session. The auto-mode safety check refused every shell command after the first few read-only ones and did not assess the commands themselves. So there is no qcc build, no host build, no generator run, no kimg, no kshcheck self-test and no parser test. Every claim about the new code is therefore HYPOTHESIS until §14.3's checks run. There was no board contact and no git operation. No QNX binary, image or listing reached a tracked path. No measured figure appears here: the 7b observations in I2 and I4 are stated without counts.

### 14.1 Files

| File | Status |
|---|---|
| `tools/m4count.c` | new (§4.5), with the notes I2-I5, I14, I17 and I18 |
| `tools/tcu-cat.c` | revised (§5.1): `-f`, `-a`, `-T`, `-s`; without them the old stdin copy, `-m`, the drop message and exit 1 are unchanged |
| `tools/Makefile` | `m4count` added to `TOOLS`; the pattern rule is unchanged |
| `.gitignore` | `orin-native/tools/m4count` after `trcctl` |
| `startup/m4.build.in` | new (§3.2); the two verbatim ranges are marked by comment lines, which the generator drops |
| `startup/m4-host.ksh.in` | new (§4.1), with note I6 |
| `startup/make-m4-images.sh` | new (§3.4), with notes I12 and I15 |
| `startup/m4-board.sh` | new (§7), with notes I7, I11 and I19 |
| `m4/parse-m4.py` | new (§6.2-6.5, §2.4, §3.4 step 9), with notes I7-I10 and I15 |
| `m4/fixtures/m4fix-{1,2,3}.txt` | new (§4.5.9), synthetic, with note I3; fixture 1 also exercises I2's trailing restart |
| `m4/capture-com3-raw.ps1`, `m4/m4-tloop.ps1` | new (§6.1) |
| `m4/build-m4tcg-image.ps1`, `m4/launch-m4tcg.ps1`, `m4/post_start-m4tcg.custom` | new (§11.2, §11.3), with note I13 |

The exec bit on `make-m4-images.sh` and `m4-board.sh` is not set (no shell). Both run as `bash <script>`.

### 14.2 Deviations and implementation notes

| # | What | Why | Class |
|---|---|---|---|
| I1 | No build, test or generator run (above) | Command execution was blocked in the session | status |
| I2 | **BUFFER restarts are not gaps.** A kept BUFFER with sequence 1 after the first kept buffer on a CPU counts as `restarts` (a new `BUF` field), not as a gap. `last_seq` stays the last sequence before the first restart. `ring=held` additionally requires every restart to lie after the end marker | In 7b's attempt 2, 3 and 4 W2 listings (git-ignored, `qhv/m4dry/attempt*/w2.n.txt`), every CPU ends with the STOP-time trailing buffer, and its sequence restarts at 1 after higher sequences. DD §13.3 also describes this trailing buffer as one "whose sequence number restarts". Under §4.5.4's gap rule, every ring capture would read `gaps=1` and `ring=unknown`, so no pair would ever be eligible (E6), and r0 criterion 5 could never pass | VERIFIED in the listings (read, no counts kept); the reading of the trailing buffer is HYPOTHESIS |
| I3 | **`-q` also prints `BUF` and `VCPU`** | m4fix-3's expectations are `gaps=1` on CPU 2 and `unattributed_qvm=1` (§4.5.9), and only those two records carry them. The fixtures' `# expect:` lines name only records `-q` prints | design fix |
| I4 | **An E3 switch.** m4count gains `-E status0\|none`, defaulting to the design's `status0`. The parser reads a `.params` key `e3`. `PAIRS` gains `e3=`. The generator adds `-E none` to `@CNT_OUT@` only when a size file says `e3=none`. **Owner decision N5 is now urgent** | In 7b's attempt-4 W2 listing, no GUEST_EXIT event carries `status` 0. The printed statuses look like exit classes, not a success flag. So at E3 = `status0`, every TCG pair is `status_nonzero`, the k512 rehearsal has no eligible clean pair, and its CSV row is skipped (`skipped(no-samples)`). The board may behave the same way. The switch lets the owner decide without a code change | VERIFIED in the listing (no counts kept); the meaning of `status` is UNKNOWN |
| I5 | **Pairing details §4.5.5 leaves open:** an `alt_order` triple is also stored as a fragment, so it blocks a pair across it, like a broken fragment. A fragment without a time is stored at time 0. E1's interval `[t_exit(n), t_enter(n+1)]` is inclusive. E5 is skipped when a marker has no time, and E6 then fails (`not_held`). `unk` counts every pair whose class could not be decided; `clean`, `pre`, `blk` and `mig` count eligible pairs only | Without the first rule, a dwell could span an alternate-order guest run | interpretation, in both implementations |
| I6 | **`show()` loops over `_f`, not `f`** (`startup/m4-host.ksh.in`) | ksh functions declared as `name()` share one scope. `send()` sets `f` to the block file and then calls `show`, so §4.1's text would have sent the `wc` output file in place of the listing | design defect, fixed |
| I7 | **Fixture records (`M4C … w=fix`) are excluded from the negative-token scan,** in `parse-m4.py run` and in `m4-board.sh extract` | m4fix-3 prints `state=wrapped` and m4fix-2 prints `order_violated=`, both on purpose. Otherwise every r0 run fails its own token check | design fix |
| I8 | **`xcheck_stats` compares only the fields a verbatim selection determines:** `TRIPLES in_window`, `PAIRS eligible clean pre blk mig intr_*`, `RING state wrapped_cpus`, `MARK start end start_t end_t`, and every `STAT` field | §6.2 step 5 says every TRIPLES, PAIRS and STAT field. But `complete`, `broken`, `total`, `out_of_window` and similar counts cover the whole listing, and block `v` holds only the window and the CONTROL events, so they could never match | design fix |
| I9 | **`xcheck_pairs` compares PC pairs whose interval lies within `[start_t, min(end_t, last_t)]`.** When the counter says `v` was capped, the PC analysis borrows the counter's `MARK end_t` for E5 and E6 and logs `xcheck_window=counter-end-marker(v-capped)` | A capped `v` has no end marker, so the PC could not decide E5 or E6 at all. Classes, dwells and CPUs stay independent; E5 and E6 then rest on the counter's marker time | design gap, bounded |
| I10 | **Parser additions:** `run --reset-reason` (the harness passes PMC `reset_reason`, which criterion 10 needs) and `--fixtures`. `CLK ` joins the record prefixes, because r0 criterion 3 reads `CLK VERDICT`. Optional `.params` keys `variant`, `profile`, `start_marker`, `end_marker`, `e3` and `transport`. `regress-7b` gains `--start-marker`, `--end-marker` and `--e3`. **`synth-com3`** builds a SYNTHETIC COM3 capture, black box and params from a TCG listing, under `qhv/` only, with the faults `corrupt-v`, `truncate-c`, `crlf` and `bb-cut`. It is a test input for the parser's plumbing, never a record | Test tooling the task asked for; additive | additive |
| I11 | **Harness record names include the UTC time:** `<image>-<run>-<utc>-{board,blackbox,com3}.log`. The parse log is `out/<image>-<run>-parse.log` | A validity retry with the same run id overwrites nothing. The CSV ledger still refuses a second row for a run id | additive |
| I12 | **r0's `.params` values that §3.3 leaves unstated:** `kind=probe k=64 s_mb=8 tl_args=-r -k 64 -M -S 8M tl_bound=300 trace_need_mb=44 cap_c=0 send_c=30 send_t_c=25` (the last three are unused in trace mode), plus `e3=status0 transport=tcu`. The generator recomputes r0's `ksh_worst_s` as `1341 + tp + cnt + send_v`, which gives §8.1's 2,129 s, and dies on any difference from §3.3 | Every marker needs a value that parses, even in an unused branch | fill-in |
| I13 | **TCG profile:** the rehearsal's `system_files.custom` gains `bin/rm=usr/bin/toybox` when the canonical `system.build` has no `bin/rm`. The template calls `$X/rm` with `X=/system/bin`, and the canonical host provides `rm` only in `ifs.build`. `qvm` and `qvm-check` are taken to be `/system/bin/…` from the canonical `/bin/qvm=` and `/bin/qvm-check=` lines (HYPOTHESIS until the rehearsal) | §11.2's single `@X@` assumes every QNX tool is in one directory | fill-in |
| I14 | m4count prints `overflow=` on `HISTSUM` and `OFFSET` when their fixed tables overflow, and ends `reason=output` when a block file cannot be written | Additive fields; otherwise a lost key or a failed write is silent | additive |
| I15 | `size-r1` and `size-r2` refuse (exit 3) a parse log whose `run_verdict` is not `pass`. `size-r2` computes `IPC_BOUND2` in integers, `(5 × N2 + 99) / 100`, as the generator recomputes it | A failed rung must not size the next image; floating-point `ceil` could disagree with the generator's check | fill-in |
| I16 | **Observation, not implemented:** rule 2 of §4.5.8 selects every CONTROL event of the listing, about three lines per kept buffer per CPU. At K2 up to 512 on four CPUs, those lines alone can exceed r2's 128 KiB `CAP_V2`. r2's verbatim sample might then carry no window event, and its `xcheck_pairs` would compare zero pairs (`match compared=0`) | Owner, before r2: raise `CAP_V2`, or restrict rule 2 to the CONTROL events up to the window's end | HYPOTHESIS |
| I17 | `m4count.c` carries `_MSC_VER` guards (`timespec_get`, `_umul128`/`_udiv128`, a binary stdout) so the same file can be built with the Visual Studio 2022 Build Tools found on this PC, for a host test. The qcc build uses `unsigned __int128` and `clock_gettime`, as §4.5.1 says | Portable core for a host test (the task); no build was possible here | additive |
| I18 | m4count's option parser is hand-written, as `bwait.c`'s is, not `getopt` | The MSVC host build has no `getopt` | fill-in |
| I19 | `m4-board.sh size-r2 R1LOG R0LOG` takes both logs; `series` takes five logs and derives the CSV, cloud CSV and output paths from `M4_RECORD_DIR` | §7.2 item 11 names one log | fill-in |

### 14.3 Still to run before §11, in order (no board)

1. `make -C orin-native/tools` in the SDP environment, `-Wall -Wextra -Werror`. Check `sha256sum orin-native/tools/smpcheck` against `PIN_SMPCHECK`. **Back up the pre-M4 `tcu-cat` binary first.** No rebuild ran, so the one M3's kimgs carry is still in place (sha256 `fd96f0b630244e7a8e10a9c3b27d557ab2014bf023247bafa9a0fbfdead5e0f2`). The session's attempt to copy it to the scratchpad was the first command the safety check blocked, so no backup exists.
2. **M3 unchanged:** run `make-m3-images.sh --generate-only` and compare every file under `shim/out/m3/` with a sha256 manifest taken first. The M3 kimgs are never rebuilt (§3.5). The new `tcu-cat` only has to exist for M3's step-9 input check.
3. `python orin-native/m4/parse-m4.py kshcheck --selftest`, then `selftest --fixtures orin-native/m4/fixtures --out-dir qhv/m4tcg/selftest`.
4. A host build of `m4count.c` under `qhv/m4tcg/hostbuild/`. Run it on the three fixtures and pass that output to `selftest --m4c`. Then run it on 7b's `w2.n.txt`, and compare with the parser's reading, with `-E status0` and with `-E none`.
5. `regress-7b` on `qhv/m4dry/attempt4/w2.n.txt`.
6. `synth-com3 --rung r1` (faults `none`, `corrupt-v`, `truncate-c`, `crlf`, `bb-cut`) and `synth-com3 --rung r0`, each followed by `run --rehearsal`. Expected: `none` and `crlf` give `run_verdict=pass`; `corrupt-v` fails `flt_v`; `truncate-c` fails `flt_c`; `bb-cut` gives `records_consistency=bb-prefix`. r0 synthetic fails crit_5, because a TCG listing keeps far more than 65 buffers.
7. `make-m4-images.sh --generate-only m4-r0`, then the full `make-m4-images.sh m4-r0` (build only, never transferred).
8. §11: `build-m4tcg-image.ps1` and `launch-m4tcg.ps1` for `r0`, `k512` and `k16`.

### 14.4 Owner decisions to confirm (recommendations adopted in the code)

- **D1-D9** as §12.3: a ring stopped by `trcctl -x`; verbatim at r1 and compact at r2; the counter on target with the PC cross-check; clean pairs in the CSV; 15 iterations, then N2; `clock=unverified`; a 1 MiB cap at r1; no larger black box; WDT0 deferred.
- **N1-N14** as §12.3.
- **New N15 (I4):** E3. Keep `status0` (the design's rule, the default) or switch to `none`. 7b's listing suggests `status0` makes every pair ineligible. Decide before the k512 rehearsal's CSV check and before r2.
- **New N16 (I2):** accept the restart rule for the STOP-time trailing buffer.
- **New N17 (I16):** r2's verbatim sample cap against the CONTROL-line volume.
- **New N18 (I9):** accept that a capped `v` borrows the counter's end-marker time for the PC's E5 and E6.

### 14.5 Build and test session (2026-09-11, orchestrator, no board)

§14.3 steps run so far. Every result is a pass/fail of our tooling, not a measurement.

- **Step 1.** `make -C orin-native/tools` passes with `-Wall -Wextra -Werror`.
  - Only `tcu-cat` and `m4count` were rebuilt, and `smpcheck` still matches `PIN_SMPCHECK`.
  - The pre-M4 tool binaries were backed up outside the repo first.
- **Step 2, not complete.** The files under `shim/out/m3/` are byte-identical before and after `make-m3-images.sh --generate-only`.
  - The generator still stops at PO-B: the M1b startup build tree no longer exists at the default `BSP` path.
  - The startup is being rebuilt from the BSP zip. It must reproduce `PIN_STARTUP` before steps 2 and 7 can finish; the pin is not to be changed to fit.
- **Step 3.** `kshcheck --selftest` and the fixture self-test pass.
- **Step 4.** A PC build of `m4count.c` (MSVC, `/W4`) ran on the three fixtures, and `selftest --m4c` passes: the C counter and the parser agree on every expectation. MSVC gives only warning C4819, for non-ASCII bytes in a comment.
- **Step 5.** `regress-7b` was run on attempt 4's W2.
  - With `--e3 status0` it finds no eligible pair, because every GUEST_EXIT status is non-zero under TCG. With `--e3 none` every class has eligible pairs. This is the evidence for N15.
  - Complete-triple and pair counts differ slightly from `parse-m4dry.py`. The M4 rules assemble triples per thread and CPU in time order and count broken fragments, while 7b paired in file order. The offset order holds in both.
- **Step 6, after one fix (I20).** The first synthetic runs failed `flt_v` on every fault.
  - Cause: 7b's listings were made on the PC by `traceprinter.exe` and end every line in CRLF. `synth-com3` therefore built a target block with CR bytes that a real target never writes, and the PC's CR strip (§6.2) then broke the md5.
  - Fix: `synth-com3` now converts CRLF to LF before it builds the block. The `crlf` fault still adds CR on the capture side.
  - After the fix every result matches step 6's expectation:
    - `none`, `crlf` and `bb-cut` pass (`bb-cut` with `records_consistency=bb-prefix`);
    - `corrupt-v` fails `flt_v`, and `truncate-c` fails `flt_c`;
    - r0 fails only `crit_5`.
- **Deferred until before the freeze.** Three verification minors, all on rare paths. Each must be fixed in `m4count.c` and the parser together.
  1. At `SEQ_KEEP`, `seq_get` returns NULL. The caller then counts a broken triple without raising a cap flag, so exit 3 never reports that cap.
  2. When a pair's offset is missing, `a` and `b` stay 0, so E5 (`out_of_window`) can win over E7 (`untimed`) in the reason chain.
  3. When triple A's exit is untimed, `frag_between` searches from 0, which can over-match E1.

  Each case needs untimed or offset-less events. r0 and r1 record those counts, and any non-zero count is reviewed before an eligibility figure is trusted. None of them decides a functional r0/r1 gate on its own.
- **Step 8, r0 attempt 1, and a fix (I21).**
  - **What ran:** the r0 TCG rehearsal ran end to end, and QEMU exited by itself with no survivors. The canonical images were unchanged.
  - **Verdict:** crit_2 to crit_9 passed; crit_1 does not apply under TCG. `run_verdict` still failed on `crit_neg`.
  - **Cause:** the TCG host boots through QNX's `startup-qemu-virt`, which prints `** CPU <n> PE is not awake` on every boot. That token is on the board's negative list because only our startup could print it there. The canonical QHV host logs and every 7b attempt carry the same two lines; no board capture does.
  - **Fix:** the parser now drops exactly that line shape before the negative scan, for `--com3-format qemu-serial` only, and records how many lines it dropped in `neg_tcg_startup_ignored`. Board captures are scanned as before.
- **Step 8, k512 and k16 attempts, and a rule fix (I22).**
  - **k512:** the rehearsal passed. The ring held, the listing transfer and PC checks matched, the pair cross-check and statistics matched, and no QEMU or parser process survived.
  - **k16 failed.** The run was built to wrap, and it did: the start marker was overwritten, the end marker was found, and each CPU's first kept BUFFER sequence was well above 1.
  - **The cause was the rule, not the code.** §4.5.4 called a ring wrapped only when both markers were present, so a wrap deep enough to lose the start marker read `unknown`. That contradicts §11.4's k16 expectation, and on the board it would disguise an undersized ring as a missing marker.
  - **Rule change:** §4.5.4 now also says `wrapped` when the end marker is found, the start marker is not, and a CPU's first kept sequence is above 1.
  - **Where it is applied:** in `m4count.c` and the parser, with a new fixture `m4fix-4`. `held` is unchanged. The k16 rehearsal is rerun with the new counter.
- **Step 8, k16 rerun with I22, and a selection fix (I23).**
  - **The rerun:** with the I22 counter, the k16 target counter reported `RING state=wrapped` on both CPUs, and the negative scan passed. `crit_k16` still failed on `pc-agree`: the PC's reading of `v` said `unknown`.
  - **Cause:** §4.5.8 selected CONTROL lines and the marker window, but not the marker events themselves. With the start marker overwritten there is no window, so the end marker never reached the PC.
  - **Fix:** §4.5.8 rule 5 now always selects both marker events, in `m4count.c` and the parser together.
  - **Checks before the next k16 run:** both implementations pass all four fixtures again, and the synthetic COM3 regression matches step 6's expectations exactly as before.

