# M4 dry run (checklist 7b): the qvm trace recipe inside a Windows-TCG QHV host image

Phase 3b. Architect pass, revision 2, 2026-09-11: revision 1 plus the fixes from two design reviews, each listed with its outcome in §12. It follows the structure and claim discipline of [m3-design.md](m3-design.md).

**Revision 3, 2026-09-11.** Revision 2 was built and ran as attempt 1 (§2.3). §13 records the outcome, the defects that run exposed, the fixes to the tooling, the ring finding and what attempts 2 and later test. Sections 1 to 12 keep revision 2's text. Where a fix changed what they describe, they point to §13.

**Path prefixes used below**
- `plan` = `docs/orin-native-port-plan.md`
- `tools/` = `orin-native/tools/`; `m4dry/` = `orin-native/m4dry/` (new)
- `qhvh/` = `qhv/host/output/build/`; `qhvg/` = `qhv/guest/output/build/`. These are local, git-ignored, QNX-generated **text** build files; only text was read.
- `sdp/` = `C:/Users/<user>/qnx800/target/qnx/aarch64le/`; `sdpinc/` = `C:/Users/<user>/qnx800/target/qnx/usr/include/`; `sdphost/` = `C:/Users/<user>/qnx800/host/win64/x86_64/usr/bin/`
- `run/` = `qhv/m4dry/` (new; git-ignored through `/qhv/`, .gitignore:16)
- `out/` = `results/orin-native-port/20260910T2307Z/m4-dryrun/` (new; `*.log` files only, git-ignored by .gitignore:57)

**Evidence classes:** VERIFIED (read in source, a header, a generated build file, a use text or a log; cited), VENDOR_CLAIM (QNX or QEMU documentation; cited), HYPOTHESIS, UNKNOWN.

**Licence status:** everything the dry run prints is evaluation output under NC QDL v7 4.6(i).
- Figures go only to `out/attempt<N>-*.log` or under `run/`. Figures means counts, sizes, rates, clock values and timings. This document, the scripts and the C source carry none.
- No QNX-shipped binary is disassembled, string-dumped or dependency-listed. SDP files are handled as opaque files: copied into our own image, hashed, and run.
- `.kev` traces, images and `.sym` files stay under `run/` or the variant build tree, both inside the git-ignored `/qhv/`.

**Documentation cited** (VENDOR_CLAIM, QNX SDP 8.0, fetched 2026-09-11; base `https://www.qnx.com/developers/docs/8.0/`):
- [tracelogger] `com.qnx.doc.neutrino.utilities/topic/t/tracelogger.html`
- [trace] `com.qnx.doc.hypervisor.user/topic/debug/trace.html`; [trace_events] `…/debug/trace_events.html`; [tsc] `…/debug/tsc.html`
- [traceevent] `com.qnx.doc.neutrino.lib_ref/topic/t/traceevent.html`; [clockcycles] `…/c/clockcycles.html`
- [sat-events] `com.qnx.doc.sat/topic/kercall_table_Events.html`
- Use texts, printed on this PC with `sdphost/use.exe` (VERIFIED as text): [use-tl] `sdp/usr/sbin/tracelogger`; [use-tp] `sdp/usr/bin/traceprinter`; [use-qvm] `sdp/sbin/qvm`. [mkq-help] is `mkqnximage --help`.

---

## 0. Summary

Checklist 7b (plan:550) asks for one thing before M4 touches the board: run the M4 trace recipe (plan:394-398) inside the Windows-TCG QHV host and find out whether qvm's Class-10 events are real. K11 (plan:94) lists what is unproven:
- event IDs 0, 1 and 7 (VENDOR_CLAIM);
- `ClockCycles()` reading the generic counter (HYPOTHESIS);
- the transport estimate (never exercised).

**The design, in seven decisions:**
1. **A variant host image, built in a new directory** (`run/host-<variant>/`).
   - It is built from a copy of the canonical host's `local/` and a copy of the canonical guest tree.
   - It adds traceprinter, libtraceparser, three of our tools and one host script.
   - The guest is byte-identical. That is checked on the PC before and after the build, and on the target before qvm starts.
   - The canonical images are only read, and hashed before and after every build and every launch (§4).
2. **Two trace windows in one boot.**
   - **W1** is a linear, time-bounded capture that starts before qvm launches. It is the simple documented baseline. It also catches IDs 2 and 5, which occur only when qvm starts ([trace_events]).
   - **W2** is the plan's ring capture, placed around the IPC run. It exercises what M4 will actually run (§3).
3. **A path-and-stop probe before either window.** A tiny ring capture with the plan's own flags shows two things: where `-M -f /dev/shmem/…` lands, and which stop method gets a ring written. W2 uses the path the probe found (§2, D2 and D3).
4. **The ring is stopped by `TraceEvent(_NTO_TRACE_STOP)`**, from our own `trcctl`.
   - SIGINT is the second rung and SIGKILL the last. The rung that worked is recorded.
   - A background job may inherit SIGINT as ignored, and `bwait` does not reset it: it spawns with NULL attributes (bwait.c:276).
5. **Counts on the target, verdict on the PC.**
   - The host script prints per-ID counts, payload checks, the plan's literal filter count, a corrected filter count and a class/subtype histogram.
   - The counter classifies each event twice, by its printed subtype name and by its numeric event ID, and reports every disagreement (§5.4). Revision 3 classifies by printed name only: `%e` turned out to be an event sequence index (§13, D-a).
   - The PC parser decides the verdict. A zero count is trusted only when the PC recount of the extracted `.kev` agrees. Without that recount a FAIL is `FAIL (unverified)`, which triggers none of the plan's fail actions (§1.2).
6. **The raw `.kev` also comes out.** After qvm is stopped, it is gzip'd, base64'd and sent over the serial console, capped and md5-checked. The PC decodes it into `run/` and parses it again with the SDP's host `traceprinter.exe`. That:
   - cross-checks the on-target filter;
   - gives the thread-level fallback characterisation;
   - gives an offset-order check (§6).
7. **A new launcher and a new parser.** `scripts/launch-qhv-tcg.ps1` is not touched.
   - The launcher records the QEMU PID, bounds the run, and always stops QEMU.
   - The image ends itself with `shutdown -S reboot`, under `-no-reboot` (§5).

**What a pass settles.**
- On QNX SDP 8.0's qvm under this TCG host, the Class-10 events GUEST_ENTER (0), GUEST_EXIT (1) and CYCLES (7) are emitted. That holds at the default qvm settings and the default tracelogger classes.
- M4 also learns four things:
  - where the ring file lands;
  - which stop writes it;
  - whether the default ring holds the IPC window;
  - the shape, never the value, of the filtered listing's size.

**What it is not:** an M4 number, a dwell figure, a board result or a transport time (§7).

---

## 1. Objective, pass and fail

### 1.1 What is being settled

| # | Question | Source | Class today | Settled by |
|---|---|---|---|---|
| Q1 | qvm emits Class-10 events with IDs 0, 1 and 7 on SDP 8.0 | plan:94, :394-396, :550 | Numbering VERIFIED (sdpinc/sys/trace.h:286-293; the class constant at :370). Emission VENDOR_CLAIM ([trace_events]) | Per-ID counts (§1.2) |
| Q2 | ID 7 carries `at_entry` and `at_exit` | [trace_events], [sat-events] | VENDOR_CLAIM | Payload checks (§1.3) |
| Q3 | ID 1 carries `clockcycles_offset`, constant for one qvm instance | [tsc] | VENDOR_CLAIM | Payload checks (§1.3) |
| Q4 | The plan's filter counts what M4 needs | plan:394-395 | HYPOTHESIS: the pattern is untested | The literal count against the histogram and the PC listing (§2, D1) |
| Q5 | `ClockCycles()` and `clock_gettime(CLOCK_MONOTONIC)` agree over 1 s | plan:396; K11 | Source VERIFIED: the inline reads `cntvct_el0` (sdpinc/aarch64/neutrino.h:70-79). Agreement untested | §1.4 |
| Q6 | The fallback can be characterised: kernel THREAD and INTERRUPT events around the qvm vCPU threads | plan:397-398 | Untested | §1.5, recorded whatever Q1's outcome |
| Q7 | Where the ring file lands, which stop writes it, and whether the default ring holds the workload | plan:394; [tracelogger] | Path rule and stop methods VENDOR_CLAIM; the rest UNKNOWN | §2 (D2, D3); §3 |
| Q8 | Filtered-listing size per exit pair, the input to the transport estimate | plan:94, :400-401 | Never exercised | Shape only (§7) |

### 1.2 The 7b verdict (plan:408-410)

**A window is usable** when all three hold:
1. its `.kev` exists and is non-empty (the `M4D KEVFILE` line);
2. traceprinter parsed it, on the target or on the PC: no loader error, and some output;
3. the histogram holds at least one event of a class other than QVM. The target's histogram is used, or the PC recount's when the target's is missing. That proves the capture works, so zero QVM events means something.

**Where the counts come from.**
- Per-ID counts come from the on-target counter (§5.4). The PC recount from the extracted `.kev` (§5.7 step 6) cross-checks them.
- **A count above zero** can rest on the target alone. The counter quotes up to three raw lines for every ID it counts (`M4D SAMPLE`), so the events themselves can be read in the log.
- **A zero cannot.** The on-target counter is untested (D1). A zero for an ID is **verified** only when every usable window has a complete PC recount that also shows zero for that ID (§5.7 step 6 defines complete).
- **When the recount is missing,** a zero from the target alone is **unverified**. That happens whenever the extraction is skipped (over the cap), damaged (md5 mismatch, truncated) or never reached (a kill mid-dump), or the host traceprinter pass fails.

| Verdict | Condition | Meaning for M4 |
|---|---|---|
| **PASS** | In at least one usable window: ID 0 ≥ 1, ID 1 ≥ 1 and ID 7 ≥ 1 | The plan's pass (plan:408). IDs 0, 1 and 7 move from VENDOR_CLAIM to VERIFIED: emitted, on this host, with this SDP. K11's first condition no longer blocks M4. The parser records `xcheck=` beside it; a PC count of zero for an ID the target counted is reported, never used to downgrade |
| **PASS (pc-only)** | The target counts are zero or missing, but the PC recount shows all three IDs | The events exist, and the on-target filter is broken. M4 must fix its filter before the board |
| **PARTIAL** | At least one, but not all, of IDs 0, 1 and 7 in the usable windows, and every absent ID's zero is verified | See §1.6. Not a pass |
| **PARTIAL (unverified)** | As PARTIAL, but at least one absent ID's zero rests on the target counter alone | Not a pass, and none of §1.6's actions yet. Rerun with the extraction working (§9) |
| **FAIL** | At least one usable window, and zero ID 0, 1 and 7 events in every usable window, with all three zeros verified | The plan's fail (plan:409): take the INTERRUPT/THREAD fallback and relabel every M4 number. Before accepting it, run the `vtwfe` variant once (§4.2, §1.6) |
| **FAIL (unverified)** | As FAIL, but at least one usable window has no complete PC recount | **Not** the plan's fail: no fallback, and nothing is relabelled. Someone reads that window's complete `M4D HIST` (`hist_printed` equal to `hist_keys`), `M4D QVMBY`, `M4D SAMPLE` and `M4D DISAGREE` lines (revision 3: `M4D HIST`, `M4D QVMOTHER` and `M4D SAMPLE`, §13) for any class, subtype or event ID that could be Class 10, then reruns with the extraction working. The plan's fail action waits for a verified FAIL, or for the owner's recorded decision (O6) |
| **INCONCLUSIVE** | No usable window | The capture failed, which says nothing about Class 10. Fix it (§9) and rerun |

### 1.3 Payload checks (a separate verdict, `fields=`)

- **ID 7:** at least one event classified as ID 7 (CYCLES; the classification is §5.4's) carries both `at_entry:` and `at_exit:`, and both are non-zero.
- **ID 1:** at least one event classified as ID 1 (GUEST_EXIT) carries `clockcycles_offset:`, and one qvm instance shows exactly one distinct offset, compared as values rather than as printed text (§5.4). [tsc] says the offset is set at qvm startup and not changed afterwards (VENDOR_CLAIM).
- **Status, recorded only.** The count of GUEST_EXIT events whose `status` is zero. [tsc] says a zero status means the entry succeeded, so the ID 7 values are meaningful.
- **Offset order, on the PC only** (§5.7 step 7).

`fields=OK` when the ID 7 and ID 1 checks both hold; otherwise `fields=MISSING(<which>)`. A PASS with `fields` other than OK unblocks exit counting only. The dwell metric M4 plans to take from ID 7 stays unvalidated.

**Field names.** The sources disagree on ID 1:
- [trace_events] lists `status, reason, clockcycles_offset, guest_ip, hw_payload`.
- [sat-events] and [tsc]'s example use `hw_reason` and `payload` instead.

Every check therefore matches only on `clockcycles_offset`, `at_entry`, `at_exit` and `status`, which every source uses.

### 1.4 The clock comparison (plan:396)

**One sample** (`clkcmp`, §5.1):
1. Take a bracket: `m0 = clock_gettime(CLOCK_MONOTONIC)`, then `c0 = ClockCycles()`, then `m1 = clock_gettime(CLOCK_MONOTONIC)`.
2. Sleep to `m1 + 1 s` with `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)`.
3. Take a second bracket: `m2`, `c1`, `m3`.

`cps` is the system page's `cycles_per_sec`.

**Derived values** (64-bit integers; the product in 128 bits):
- `cc_ns = (c1 − c0) × 10^9 / cps`
- `mono_ns = (m2 + m3)/2 − (m0 + m1)/2`
- `err_ns = cc_ns − mono_ns`
- `wA = m1 − m0` and `wB = m3 − m2`, the bracket widths
- `q = ceil(10^9 / cps)`, one counter quantum in ns

**Agreement.**
- **Usable:** both brackets ran on the intended CPU, and `wA` and `wB` are each at most `wide_ns` (1 ms).
- **Strict:** `|err_ns| ≤ (wA + wB)/2 + 4q`. The counter reading lies inside its bracket, so each mid-point estimate is off by at most half its bracket, plus a quantum or so of reading resolution.
- **Within resolution:** the same bound plus `2 × clock_getres(CLOCK_MONOTONIC)`.

**Modes.** Three, five repetitions each:
- both brackets on CPU 0;
- both brackets on CPU 1;
- bracket A on CPU 0 and bracket B on CPU 1.

The cross-CPU mode tests the claim that the counter is synchronised across processors ([clockcycles]). It matters because a vCPU's `at_entry` and `at_exit` may be read on different physical CPUs.

**Per-mode verdict:**
- `agree`: at least 3 usable samples, and every usable sample agrees strictly.
- `agree-within-resolution`: at least 3 usable samples, all within resolution, and at least one not strict.
- `disagree`: any usable sample outside the resolution bound.
- `unusable`: fewer than 3 usable samples.

**It runs three times,** labelled by `run=` (§5.7 step 8):
- `pre`: before W1, on an idle host;
- `load`: in the background during W1, started straight after qvm. tracelogger is logging and qvm is starting the guest, the heaviest TCG load of the run, which is the condition M4's capture runs under;
- `post`: after teardown.

**Under load,** a bracket is more likely to be preempted or migrated. So `unusable` is a legitimate `load` outcome, recorded and not a failure. A `load` run that disagrees while `pre` and `post` agree is a finding in its own right.

**Why W1 and not W2.** The `load` run's own thread events land in the trace of the window it runs in. W1's role (§3.2) tolerates that. W2 sizes the ring for M4 (§8 item 4) and brackets the plan's workload, so it stays free of them.

**What agreement means.** It is a self-consistency check. QNX derives system time from `ClockCycles()` at `cycles_per_sec` ([clockcycles]).
- **Agreement shows** that three things are consistent on every CPU: the user-space counter read, the system page's rate, and the kernel's time base.
- **It does not show** that the counter runs at a real-time rate.

**External reference (characterisation only).**
- `clkcmp -e 10` prints a start line and an end line, ten monotonic seconds apart. The launcher timestamps each line's first appearance in the serial file with its own Stopwatch.
- The parser reports target seconds against PC seconds as `clock_ext`.
- It is coarse, because each end carries the poll interval plus serial and file latency. It can catch an emulated clock running at a grossly wrong rate. It cannot calibrate anything.

**What stays unsettled.** K11's "`ClockCycles()` reads the generic counter" is settled at source level (neutrino.h:79); [clockcycles] says the same. The board's counter rate is not settled, because the TCG host's `cps` is not the board's; both values are in private logs. That stays with M4's PMCCNTR calibration (plan:401).

### 1.5 Fallback characterisation (recorded whatever Q1's outcome)

The plan takes the fallback only when Class 10 is absent (plan:397-398). The dry run characterises it every time, so M4 knows in advance whether the fallback could work.

**On the target:**
- the qvm pid and threads (`pidin -p qvm -f abNli`), taken twice;
- per window, the histogram's THREAD-class and INTERRUPT-class counts;
- per window, the THRUNNING count for each qvm thread (tid).

**On the PC, from the extracted `.kev`** (§5.7 step 7):
- which vCPU thread each event belongs to, taken from the last THRUNNING on its CPU;
- running intervals per vCPU tid;
- INTERRUPT events that fall while a vCPU tid is running;
- how many exit-to-entry intervals had another thread running on that CPU, which is preemption inside a would-be dwell.

**Recorded as** `fallback=characterised`, `fallback=partial(no-extraction)` or `fallback=impossible(<reason>)`. `impossible` means there were no THREAD events, or no identifiable qvm thread.

### 1.6 What a partial outcome means

Every row assumes the absent IDs' zeros are verified (§1.2). An unverified partial first gets a rerun with the extraction working.

| Seen | Meaning | Action |
|---|---|---|
| IDs 0 and 1 but no 7 | Exits are traced but guest time is not. Dwell from ID 7 is impossible, and ID 0 and 1 timestamps include host preemption ([trace_events]) | M4 relabels its number as a host exit-to-entry interval, an upper bound, fenced by THREAD RUNNING events (§1.5). Record it |
| ID 7 without ID 0 or ID 1 | More likely a naming or filter mismatch than genuine absence | Check the PC listing and the histogram's names. INCONCLUSIVE until explained |
| Only IDs 2 to 6 | qvm emits Class-10 events, but its exit events are absent at the default settings | Run `vtwfe` (§4.2), which sets `trace-vtimer` and `trace-wfe` on ([use-qvm]). If exits are still absent: FAIL |
| IDs 0, 1 and 7 in W1, none in W2 | Class 10 is real; W2's capture or window failed | The PASS stands. W2's defect is carried into M4's recipe (§8) |

---

## 2. The recipe as it will run

### 2.1 Plan text and the commands that replace it

**Plan text** (plan:394-395): `tracelogger -r -M -S 8M -f /dev/shmem/t.kev` + `traceprinter | grep -E 'QVM|Class 10|GUEST'`.

**Commands as the host script runs them.** §5.3 has the full script. `K` is the window's `.kev` file. The tools are in `/system/bin`, which is on PATH (qhvh/ifs.build:20).

1. **Probe.**
   - Start `tracelogger -r -M -S 1M -f /dev/shmem/p.kev` in the background: the plan's flags, at a small size.
   - After 3 s run `trcctl -m 1 m4d-probe`; after 1 s more, `trcctl -x`.
   - Then see where the file is, and whether the marker is in it.
2. **W1.** Before qvm launches, start `tracelogger -s 60 -S 32M -f /dev/shmem/w1.kev` in the background. It is linear and time-bounded, with all classes enabled.
3. **W2.** After the IPC grace, start `tracelogger -r [-k 64] -M -S 8M -f <W2F>` in the background. `<W2F>` is chosen by the probe (D2). `-k 64` appears only in the `k64` variant. Revision 3 makes the size a parameter, `-r [-k K] -M -S S`: `plan` and `k64` keep `S = 8M`, and the new `k512` variant uses `-k 512 -S 32M` (§13.3).
4. **W2 stop.** `trcctl -x`, then `slay -f -Q -s INT tracelogger`, then `slay -f -Q -s KILL tracelogger`. Each rung runs only if the previous one did not end tracelogger within its bound (D3).
5. **Literal filter, per window.** This is the plan's own count, kept verbatim for the record:
   ```
   traceprinter -f K | grep -E 'QVM|Class 10|GUEST' | wc -l -c
   ```
6. **Counter, per window.** Produces the histogram, per-ID counts, payload checks and per-tid THRUNNING counts. Each event is classified by its subtype name and by its event ID (D1, §5.4):
   ```
   traceprinter -n -p 'M4H|%C|%Z|%z|%e|' -f K | gawk -F'|' -v w=<window> -v qpid=<pid> -f /system/bin/m4dry-count.awk
   ```
   Revision 3 drops `%e` and classifies by printed name only (§13, D-a):
   ```
   traceprinter -n -p 'M4H|%C|%Z|%z|' -f K | gawk -F'|' -v w=<window> -v qpid=<pid> -f /system/bin/m4dry-count.awk
   ```
7. **Corrected filter, per window.** One line per event, arguments included (D1, D7):
   ```
   traceprinter -n -f K | grep -E 'QVM *:' | wc -l -c
   ```
   For W2 the matching lines are also kept in `/dev/shmem/w2.flt`, which becomes the listing block (§6).

   Revision 3 follows each of steps 5 to 7 with `reap`, which kills any pipeline stage that outlived its bound and records whether one did (§13, D-f).

### 2.2 Deviations from the plan text

| # | Plan text | Change | Grounds |
|---|---|---|---|
| D1 | `grep -E 'QVM\|Class 10\|GUEST'` (plan:395) | The literal count is kept. The verdict uses the counter over `-n` output. The corrected filter is `grep -E 'QVM *:'` over `-n` output | See D1 below |
| D2 | `-M -S 8M -f /dev/shmem/t.kev` (plan:394) | The probe decides W2's `-f` path, and every file is looked for in both places | See D2 below |
| D3 | The plan does not say how the ring is stopped | Stop ladder: `trcctl -x`, then SIGINT, then SIGKILL, with the rung that worked recorded. A `.kev` must exist before any FAIL | See D3 below |
| D4 | One ring capture | A linear W1 is added before qvm launch, and the plan's ring becomes W2 around the IPC run | See D4 below |
| D5 | "inside the existing Windows-TCG QHV host image" (plan:394, :550) | A variant image: same guest bytes, same SDP install, same mkqnximage options | See D5 below and §4 |
| D6 | "compare `ClockCycles()` against `clock_gettime()` over 1 s" (plan:396) | `CLOCK_MONOTONIC`, bracketed, repeated, on three CPU modes, plus a coarse external reference; labelled self-consistency | §1.4 |
| D7 | "count the filtered lines" (plan:395) | Lines **and** bytes, for both filters, per window. For W2, the listing itself is sent with md5 and cksum, rehearsing the board's transport (plan:400-401) | §3, §6 |
| D8 | Not in the plan | User string markers bracket the workload and detect ring wrap | See D8 below |
| D9 | Not in the plan | qvm's `trace-*` settings are recorded; an optional variant turns two of them on | See D9 below |
| D10 | Not in the plan (the board never sends the whole `.kev`, plan:400-401) | Raw `.kev` extraction over serial, for this dry run only | §6 |
| D11 | Fallback only if Class 10 is absent (plan:397-398) | Fallback characterised on every run | §1.5 |

**D1: the filter pattern.**
- **The problem.** traceprinter prints class *names*, not class numbers. Its default format is `t:0x%08c CPU:%02C %-16Z:%-18z` ([use-tp]), and [tsc]'s sample prints the class as `QVM`.
  - So `Class 10` can never match. That is HYPOTHESIS until it runs.
  - Without `-n`, argument lines are separate lines ([use-tp], `-n`). The plan's filter would therefore drop `at_entry:`, `at_exit:` and `clockcycles_offset:`, and an ID could look present while carrying no values.
  - `GUEST` can also match unrelated text.
- **The change.** The plan's count is still taken, verbatim. The verdict uses the counter over `-n` output: a histogram by class and subtype, per-ID counts and payload checks. The corrected filter is `grep -E 'QVM *:'` over `-n` output.
- **Two classifications, not one.** The counter does not rest on the printed subtype name alone.
  - [use-tp] lists `%e` as the event ID. Its own second example prints a SYSTEM event's `%e` as a small zero-padded decimal (VENDOR_CLAIM).
  - That fits the within-class event number, the low ten bits of the event header (`_NTO_TRACE_GETEVENT`, sdpinc/sys/trace.h:239). For Class 10 that number is 0-7 (:286-293).
  - The counter reads `%e` as decimal or `0x` hex. It also accepts the class-coded form, with class 10 in bits 10-14 (:237, :370).
  - It counts by name and by number separately, and prints every disagreement (§5.4).
- **Still HYPOTHESIS:** that the class prints as `QVM`, what `%e` prints for a Class-10 event, and that `-n` combines with `-p`. The histogram shows the actual names and IDs, and the PC cross-check catches a broken on-target counter.
- **Outcome (attempt 1, VERIFIED).** The class prints as `QVM`, and `-n` combines with `-p`. `%e` prints an event sequence index, one higher for each printed event, not the event ID. The numeric classification produced a false hit and made every histogram key unique. Revision 3 removes it (§13, D-a). The plan's literal filter matched exactly the QVM header lines, and `Class 10` never matched.

**D2: the `-M` path.**
- **The doc.** [tracelogger] says that with `-M`, the `-f` name is placed under `/dev/shmem`: its example turns `/var/tracebuffer.kev` into `/dev/shmem/var/tracebuffer.kev`.
- **The problem.** Read literally, the plan's path becomes `/dev/shmem/dev/shmem/t.kev` (HYPOTHESIS). The doc does not say whether an existing `/dev/shmem` prefix is kept.
- **The change:** the probe decides W2's path.

  | Where the probe's file landed | W2 uses | Recorded as |
  |---|---|---|
  | `/dev/shmem/p.kev` | the plan's path, `-f /dev/shmem/t.kev` | `probe-literal` |
  | `/dev/shmem/dev/shmem/p.kev` | `-f /t.kev` | `probe-doubled` |
  | somewhere else under `/dev/shmem` | the plan's path | `probe-elsewhere` |
  | nowhere under `/dev/shmem` | the plan's path | `probe-none` |

  Every file is looked for in the two expected places first, then by name anywhere under `/dev/shmem` (`kevpath`, §5.3). [tracelogger] places a `-M` object under `/dev/shmem`, so the search covers every placement the doc allows.
- **Runbook rule.** Whenever `PROBE path=none` appears, the operator reads the probe's printed `find` output and its stderr head before accepting an unusable W2 or an INCONCLUSIVE verdict. The automated path logic cannot cover a placement the doc does not describe.

**D3: stopping the ring.**
- **The doc.** [tracelogger] says ring mode writes its events only on SIGINT, or when an application calls `TraceEvent(_NTO_TRACE_STOP)`, and that tracelogger then exits (VENDOR_CLAIM).
- **The problem.** A background job in a non-interactive shell may start with SIGINT ignored (HYPOTHESIS, general POSIX shell behaviour). `bwait` passes signal dispositions through unchanged (bwait.c:276).
- **The ladder:**
  1. `trcctl -x`. Control commands need the `PROCMGR_AID_TRACE` ability ([traceevent]), which root is allowed (sdpinc/sys/procmgr.h:138, :232).
  2. SIGINT.
  3. SIGKILL.
- **What is recorded.** The rung that ended tracelogger. A killed ring leaves no file, so the window becomes unusable. It never produces a FAIL.

**D4: two windows.**
- **Why W1 is added.**
  - IDs 2 and 5 occur once, at qvm start, so tracing must already be running to see them ([trace_events]).
  - Guest boot guarantees guest entries inside W1.
  - A linear capture needs no stop signal, so a W2 stop problem cannot erase the verdict.
- **Open detail.** `-s` (timed) and the default iterations mode (32 buffers) are separate modes ([use-tl], [tracelogger]). Whether `-s` alone can still stop at 32 buffers is UNKNOWN. The record carries tracelogger's run time and the file size, and W1 serves its purpose either way.

**D5: the image.**
- **The existing image falls short in three ways:**
  - It has tracelogger (qhvh/system.build:74) and libtracelog (:50), but not traceprinter or libtraceparser.
  - Under its launcher (`-serial file:`) it has no input channel.
  - It must not change.
- **Instead:** a variant image with the same guest bytes, the same SDP install and the same mkqnximage options (§4).

**D8: markers.**
- `trcctl -m` inserts user string events: `_NTO_TRACE_INSERTUSRSTREVENT` (sdpinc/sys/trace.h:63), with IDs 0-1023 (:163-164). [traceevent] says inserting one needs no ability. That is a permission; whether tracelogger captures the events is a separate question.
- **Their class.** User events belong to the User class, `_TRACE_USER_C` (trace.h:366).
  - That is not the Security class, `_TRACE_SEC_C` (:369), the only class [use-tl] says needs `-a`.
  - [use-tl]'s `-F` list has no entry that disables the User class. Its numbers are not trace.h's class numbers: it lists 5 as unused and 6 as the Communication class (VERIFIED as use text).
  - [tracelogger] says a tracelogger not in plain daemon mode enables every class except Security (VENDOR_CLAIM). So the markers should be captured at the plan's flags.
- **Checked per run, not assumed:** by the probe's `marker=` result, and by the marker events' own key in `M4D HIST`.
- **`-a` is not added.** It would change the plan's flags and add Security events to both windows, for a question the probe already answers.
- There are three in-window markers: W1 start, IPC start and IPC end.
- They bracket the workload and detect ring wrap. `m4d-ipc-end` present with `m4d-ipc-start` absent means the ring overwrote the start of the window. If the probe's file was non-empty but its marker was absent, marker capture is unproven, and `ring=` is forced to `unknown` (§3.2).

**D9: qvm trace settings.**
- **The doc.** [use-qvm] says `trace-vtimer`, `trace-wfe` and `trace-spectre-workaround` default to off. While they are off, the guest exit, cycles and re-entry events for those operations do not appear.
- **The default image** records `trace_set=defaults`.
- **The optional `vtwfe` variant** adds `set trace-vtimer on` and `set trace-wfe on`, using the syntax `set <variable_name> <value>` ([use-qvm]).
- **M4** must state which setting it used.

### 2.3 Implementation deviations from this design (as built 2026-09-11; run as attempt 1 the same day)

The files of §5 were written and the `plan` variant was built. Where this design was inconsistent or silent, the choice below was made. None of them changes a verdict rule of §1.2 or §1.3.

**Run.** This build ran as attempt 1 (`out/attempt1-*.log`): `VERDICT7B=PASS fields=OK`. The run exposed the defects §13.2 lists. The tooling was fixed after it and is built as the `r3`-tagged variants (§13.3). The table below describes the build that ran.

| # | Design text | As built | Why |
|---|---|---|---|
| I1 | §5.5 rules: native commands run as `cmd /c '... 2>&1'` with `$LASTEXITCODE` checked; step 6: mkqnximage killed at 1800 s | Each native step is written to a generated `.cmd` file in `run/stage-<variant>/` and started with `Start-Process`, with stdout and stderr going to `.log` files beside it. It is waited on with a bound and killed as a tree with `taskkill /T /F`; the exit code is the process's `ExitCode`. `make` gets the same treatment, with its own bound | A synchronous `cmd /c` cannot be killed at a bound, so the two rules conflict |
| I2 | §5.5 step 5: `data_files.custom` "kept as copied" | Kept, and checked to be exactly the canonical client line after LF normalisation; a difference stops the build | The design states the content as a fact; the check makes it one |
| I3 | §5.1: `SchedGetCpuNum()` after the bracket | Checked just before and just after each bracket. Bracket B's pin is set before the sleep, and a pin that has not moved the thread yet gets one 1 ms nap before its bracket. A failed pin prints `CLK NOTE pin`; a failed clock call prints `CLK ERROR <call> errno=` and exits 1 | §1.4 calls a sample usable when "both brackets ran on the intended CPU", which needs both ends checked. The nap avoids a busy-wait |
| I4 | §1.4 per-mode verdicts, order not stated | First match wins, in clkcmp and the parser alike: `disagree`, then `unusable`, then `agree`, then `agree-within-resolution` | A mode with fewer than three usable samples, one of them outside the resolution bound, fits both `disagree` and `unusable`. A disagreement is a finding, and exit 1 already outranks exit 3 |
| I5 | §5.7 step 7: triples in the order GUEST_ENTER, CYCLES, GUEST_EXIT; interrupts matched by subtype | Unchanged, plus two reporting-only counts: `triples_enter_exit_cycles` (the other order, never paired) and `intr_class_or_subtype` | The event order and the interrupt naming are HYPOTHESIS. A zero `triples` beside a non-zero alternative count names the cause without another boot |
| I6 | §1.2 `PASS (pc-only)`: "the target counts are zero or missing" | Any usable window where, for each of IDs 0, 1 and 7, the larger of the target and PC counts is at least one, when `PASS` does not hold | Covers the mixed case, where the target shows some IDs and the PC the rest. A count above zero may rest on either side (§1.2) |
| I7 | §5.7 step 7: ring from the target's `M4D MARKERS` first, the PC listing otherwise | The PC listing is used when the target's line shows neither marker | Under `-p`, whether traceprinter prints a user event's text is unknown (R10), so a target zero does not show the markers are absent |
| I8 | §5.6 step 8: MARK names not given | `state:<name>`, `clk_ext_start`, `clk_ext_end`, `qvm_launch`, `echo_up`, `guest_banner`, `samples`, `kev_begin:<name>`, `kev_end:<name>`. The launch log also carries `poll_ms=` and `qemu_version=` lines for the parser | The parser reads them (§5.7 steps 8 and 9) |
| I9 | §5.6 | The launcher refuses a QEMU argument that contains a space, and repeats the QEMU and parser stops in an outer `finally` | PS 5.1 `Start-Process -ArgumentList` joins its arguments on spaces; the outer `finally` also covers Ctrl+C outside the poll loops |

---

## 3. The trace window

### 3.1 Timeline of one boot

- **States.** Each state prints `M4D STATE <name>` as it starts.
- **Bounds.** Bounds are design constants, not measurements. T0 is the line `=== launching qvm @g2.conf (background) ===`.
- **Constants.** `W1_SECS = 60`. `GRACE = 150` s, counted from T0. `W1_SECS` and `GRACE` are build parameters (§5.5).
- **Outer bounds.** An in-image guard of 4900 s, and a launcher wall bound of 5500 s. The worst case of every bounded term is about 4,400 s (§5.3). Revision 2 added the `load` clock run's wait, and raised both outer bounds by the same amount.

| # | State | What happens | Bound |
|---|---|---|---|
| S0 | `guard` | `bwait -g 4900 &` | none: this is the guard |
| S1 | `config` | CONFIG line, `uname -a`, free memory; a traceprinter start check | 30 s |
| S2 | `preflight` | `/dev/ptyp0` present; md5 of the guest IFS, guest disk and client against the build's pins | 180 s |
| S3 | `clock_pre` | `clkcmp`, then `clkcmp -e 10` | 120 s, then 10 s by construction |
| S4 | `probe` | The D2/D3 probe; `find /dev/shmem -name '*.kev'`; marker round trip | 600 s kill bound (never reached before the ladder), 160 s ladder, 120 s print |
| S5 | `disk` | devb-loopback; `/dev/qvmdisk0`; write `g2.conf` | 10 s |
| S6 | `w1` | W1 starts; 2 s settle; marker `m4d-w1-start` | none |
| S7 | `qvm` | T0 line; qvm in a subshell that records its exit; grace timer | none |
| S7a | `clock_load` | `clkcmp` in the background under `bwait -k 120`, straight after qvm (§1.4) | 120 s kill; the wait is in S8 |
| S8 | `w1_wait` | Wait for W1 to exit, stop ladder if late; the `load` clock result; `pidin -p qvm` snapshot 1; qvm pid | `W1_SECS` + 120 s, then 160 s, then 130 s |
| S9 | `grace_wait` | Wait for the grace timer or qvm's exit | `GRACE` + 30 s |
| S10 | `w2` | W2 starts; 2 s settle; marker `m4d-ipc-start` | none |
| S11 | `ipc` | `qnx-host-client 15 /dev/ttyp0 5` under `bwait -k 600`; marker `m4d-ipc-end`; 2 s tail | 600 s |
| S12 | `w2_stop` | The stop ladder | 120 + 30 + 10 s |
| S13 | `report_ipc` | Client output; `pidin -p qvm` snapshot 2 | none |
| S14 | `teardown` | `slay -f -Q qvm`, SIGKILL if needed | 15 + 5 s |
| S15 | `clock_post` | `clkcmp` again | 120 s |
| S16 | `process_w1`, `process_w2` | Literal filter, counter and corrected filter for each window; W2's listing kept in `/dev/shmem`. Revision 3: `reap` after each pass (§13, D-f) | 300 s per pass |
| S17 | `summary` | Record lines reprinted | none |
| S18 | `flt` | The W2 filtered-listing block | 20,000-line cap |
| S19 | `kev` | The W2 `.kev` block, then W1's | 180 s per gzip; a 16 MiB gzip cap each |
| S20 | `end` | `FAIL_STATE`; `M4D STATE end`; `shutdown -S reboot` | none |

If S2 or S5 sets a failure, S6-S14 are skipped and the script goes straight to S15.

### 3.2 Why each window contains guest entries and exits

**W1, by construction.**
- W1 is running before qvm is launched: tracelogger has started, and a 2 s settle has passed. It stays in timed mode for `W1_SECS`.
- qvm creates its vCPU threads and enters the guest after launch, and no guest output can exist without guest entries.
- So W1's first `W1_SECS` after T0 contain qvm startup and the start of guest boot. The one exception is qvm failing to start; `qvm.rc` then appears early and no guest line exists.
- Linear mode writes buffers as they fill, so W1 depends on no stop signal.
- Whether W1 also covers the guest banner is checked per run (`w1_covers_banner=`), not gated.

**W2, by construction.**
- W2 is running before the client opens the link (S10 precedes S11).
- Every echoed frame requires the guest's echo server to run, so a client that prints `samples=` proves the guest executed inside W2.
- After the client, the guest keeps running for a 2 s tail. An idle guest waits in WFI, and `exit-on-halt` defaults to enabled ([use-qvm]). That this WFI exit produces visible events at the default trace settings is HYPOTHESIS.

**Ring overwrite.**
- A ring keeps the most recent events. [traceevent] says the capture time without history being overwritten is set by the number of allocated buffers.
- The per-CPU ring is `-k` times about 16 KB ([use-tl], [tracelogger]). What `-M -S` changes about that is UNKNOWN.
- STOP comes straight after the tail, so the ring always holds the window's last events. Those include guest exits, if any exist.
- Whether it holds the whole IPC run is read from the markers (D8):

  | Markers found | Recorded |
  |---|---|
  | both | `ring=held` |
  | only `m4d-ipc-end` | `ring=wrapped` |
  | any other combination | `ring=unknown` |

  If the probe's file was non-empty and its marker absent, `ring=unknown` whatever W2's markers show (D8).

**Flush on stop.**
- The ring is written only at STOP or SIGINT (D3).
- The script checks that the file exists and is non-empty before counting anything.
- A missing file is recorded as `KEVFILE w2 path=none`, and W2 becomes unusable.

**No processing inside a window.**
- While qvm runs, nothing heavier than `pidin`, `trcctl` and the `load` clock run runs. All traceprinter work waits until after teardown (S16).
- The `load` clock run is the one deliberate exception (§1.4). It sleeps between brackets, runs during W1, and has ended or been killed before W2 starts (S8).
- So the trace never records our own parsing load, and the guest is not starved during the IPC run.

### 3.3 How the dry run's host behaviour differs from the canonical host's

| Canonical host (qhvh/post_startup.sh) | Dry run | Why |
|---|---|---|
| An RQ-2 host-half block (:40-44). The binary was never staged: the as-run log prints the skip (`qhv/qhv-guest-boot-rng-snap1.log:15`) | Omitted | The block only prints a skip line. The guest half skipped too (the same log, :36-37) |
| `g2.conf` with pl011, virtio-console, virtio-blk and shmem (:50) | The identical text. `vtwfe` adds two `set` lines | It is the as-run configuration, and the board's `orin-native/qhv/g2-m3.conf:27-44` has the same four vdevs |
| `qvm @g2.conf &` | The same command, in a subshell that records its exit code. stdin is `/dev/null`; stdout is still the console | Exit detection, without moving the guest console off the serial log |
| `waitfor /dev/ttyp0 10`, then `sleep 90` | A 150 s grace timer from T0 | Tracing slows guest boot by an unknown amount. The parser checks that the echo server's line and the guest banner both come before `M4D STATE ipc` |
| The client runs unbounded | `bwait -k 600` | Every wait is bounded |
| post_startup.sh goes on to io-usb-otg and the host banner | `shutdown -S reboot` at the end | QEMU exits under `-no-reboot` |

---

## 4. Image strategy

### 4.1 The choice: (a), a variant host image

**Option (a): a variant image in `run/host-<variant>/`.**
- **For:**
  - It is deterministic, fully scripted and ends itself.
  - traceprinter, libtraceparser and our tools are baked in.
  - W1 can start before qvm does.
  - The launch line is the twin leg's, apart from the image paths.
- **Against:** it is a rebuilt host IFS and disk, not the canonical bytes.

**Option (b): the canonical image driven over serial.**
- **For:** it runs the canonical host bytes.
- **Against:**
  - traceprinter and libtraceparser are missing. The image carries only the logger side (qhvh/system.build:50, :74).
  - `launch-qhv-tcg.ps1` gives no input channel, because it uses `-serial file:`.
  - `scripts/qhv/launch-qhv-tcg-interactive.ps1` hardcodes the canonical output directory and has no `-snapshot`, so running it would change `disk-qemu` and break `SHA256SUMS`.
  - Getting traceprinter in at run time would need a network path or a second disk, and `/dev/shmem` is noexec (qhvh/ifs.build:49).
  - The canonical post_start launches qvm before any shell could start tracelogger. IDs 2 and 5 are lost, and the window timing would depend on typing.

**Chosen: (a).** The honest record, printed in the CONFIG line and every log:
- It is a **rebuilt** QHV host image: a new IFS and a new disk.
- It carries the **byte-identical** guest IFS and guest disk.
- It was built by the same SDP install, with the canonical host's mkqnximage options and snippet placeholders.
- It is **not** the canonical host's bytes.

That every other host file matches the canonical image is HYPOTHESIS, and it is not checked: the canonical disk is never opened. None of this affects 7b, which asks about qvm and the SDP trace tools, not about host image bytes. It would matter for a timing comparison, and the dry run makes none.

### 4.2 Layout (all under the git-ignored `/qhv/`)

- **`run/guest/`:** a copy of the whole `qhv/guest/` tree, `local/` and `output/`. It mirrors the canonical layout, so `--guest=` points at a directory of the same shape. The canonical `qhv/guest/` is never passed to mkqnximage.
- **`run/host-<variant>/`:** the variant host's build directory.
  - Before the build it holds only `local/`, as `qhv/host/` did before its first build.
  - So `--force` is not needed; [mkq-help] says mkqnximage refuses a non-empty directory without it.
- **`run/stage-<variant>/`:** the generated `m4dry-host.ksh` and `m4dry-count.awk`, with LF line endings and no BOM.
- **`run/build-<variant>.log`:** the build record.
- **`run/attempt<N>/`:** the raw serial log, the decoded `.kev` files and the host-side listings.

**Variants.** Only `plan` is needed for 7b.

| Variant | W2 | g2.conf |
|---|---|---|
| `plan` (default) | Exactly the plan's flags, with D2 applied by the probe | As run |
| `k64` | Adds `-k 64` | As run |
| `k512` (revision 3) | `-k 512` with `-S 32M` (§13.3) | As run |
| `vtwfe` | As `plan` | Adds `set trace-vtimer on` and `set trace-wfe on` |

**Tags (revision 3).** `build-m4dry-image.ps1 -Tag <tag>` builds a variant into `run/host-<variant>-<tag>/`, with `run/stage-<variant>-<tag>/` and `run/build-<variant>-<tag>.log`. `launch-m4dry-tcg.ps1 -Tag <tag>` boots that build. A rebuilt image therefore never needs an earlier attempt's directory renamed, and attempt 1's untagged `run/host-plan/` stays as it ran.

### 4.3 Canonical protection (the build script and the launcher both)

1. **Path refusal.**
   - Resolve every target directory to a full path, case-insensitive, with separators normalised.
   - Refuse if it equals, or lies under, `<repo>/qhv/host` or `<repo>/qhv/guest`.
   - Refuse if it does not lie under `<repo>/qhv/m4dry/`.
   - Refuse a non-empty `run/host-<variant>/`. The owner renames it; no script deletes a directory.
2. **Hashes before.**
   - `qhv/host/output/SHA256SUMS` must pass; `results/qhv-images-SHA256SUMS.txt:5-6` carries the same pair.
   - `qhv/guest/output/ifs.bin` must hash to `968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f` (K11).
   - `qhv/guest/output/disk-qvm` must hash to `cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b` (m3-design.md §0).
   - Any mismatch stops the script: the baseline is not the one this design assumes.
3. **Hashes after.** The same checks run after the build and after every launch. A changed canonical hash stops all further work and is reported to the owner. Nothing is repaired automatically.
4. **Never run:**
   - `scripts/build-qhv.bat`;
   - mkqnximage with its working directory, or `--guest=`, inside `qhv/host` or `qhv/guest`.

   No script in this design contains those paths as a target.

### 4.4 How the guest is checked in the variant

1. **PC, before the build:** `run/guest/output/ifs.bin` and `run/guest/output/disk-qvm` hash to the two pins.
   - A mismatch means a stale or damaged copy from an earlier build. The build stops before anything is staged or built, with exit 1 and `guest_copy_pre=MISMATCH` in the build log.
   - Nothing is repaired automatically. The owner renames `run/guest` by hand, in line with the rule that no script deletes a directory (§4.3 step 1). The next build copies it afresh (§5.5 step 3).
2. **PC, the generated text.** The variant's `output/build/data.build` must name `run/guest/output/ifs.bin` and `run/guest/output/disk-qvm` as the sources of `hypervisor/guest/ifs.bin` and `hypervisor/guest/disk-qvm`. That is the form of the canonical file (qhvh/data.build:85-86). No other source for either name may appear.
3. **PC, after the build:** the copy still hashes to the pins. That mkqnximage never writes into the guest directory is HYPOTHESIS; this check closes it for each build. A mismatch marks the variant invalid and exits 1. It is handled like step 1: the owner renames `run/guest` and the variant directory, and builds again.
4. **Target, before qvm.**
   - `md5sum /data/hypervisor/guest/ifs.bin /data/hypervisor/guest/disk-qvm /data/hypervisor/qnx-host-client` must equal the md5 of the same PC files. The build substitutes those md5s into the script.
   - md5, not sha256, because toybox has md5sum and no sha256sum (qhvh/system.build:161; m3-design.md §2 rule 3).
   - A mismatch prints `M4D FAIL md5_pre_<file>`. qvm is not launched, and the run is INCONCLUSIVE.

The guest writes to its disk during the run, and `-snapshot` discards those writes when QEMU exits. So the md5 check runs only before launch.

---

## 5. Files to create or change

| Path | What | Section |
|---|---|---|
| `orin-native/tools/clkcmp.c` | New tool: the clock comparison | §5.1 |
| `orin-native/tools/trcctl.c` | New tool: trace markers and stop | §5.2 |
| `orin-native/tools/Makefile` | `TOOLS := tcu-cat stamp smpcheck bwait clkcmp trcctl`. The pattern rule (:15-16) builds both new tools, and the existing targets are unchanged | — |
| `.gitignore` | Add `orin-native/tools/clkcmp` and `orin-native/tools/trcctl` after :92 | — |
| `orin-native/m4dry/post_start-m4dry.custom` | The host snippet | §5.3 |
| `orin-native/m4dry/m4dry-host.ksh.in` | The host script template | §5.3 |
| `orin-native/m4dry/m4dry-count.awk` | The on-target counter | §5.4 |
| `orin-native/m4dry/build-m4dry-image.ps1` | Builds a variant image | §5.5 |
| `orin-native/m4dry/launch-m4dry-tcg.ps1` | The launcher | §5.6 |
| `orin-native/m4dry/parse-m4dry.py` | The PC parser | §5.7 |

**Line endings.** `.gitattributes` gives the new `.c` files LF by their own rule (:31), and the `.in`, `.awk`, `.custom` and `.py` files LF by the default rule `* text=auto eol=lf` (:12). The `.ps1` files get CRLF (:18). The build script writes every file that enters the image with LF anyway (§5.5 step 5).

**Not changed:**
- `scripts/launch-qhv-tcg.ps1`, `scripts/build-qhv.bat` and `scripts/qhv/*`;
- `tools/stamp.c`, `tools/bwait.c`, `tools/smpcheck.c` and `tools/tcu-cat.c`;
- `orin-native/startup/*`, including `make-m3-images.sh` (§8);
- any image, and any earlier record.

### 5.1 `tools/clkcmp.c` (Apache-2.0, like the other tools)

```
clkcmp [-n REPS] [-i MS] [-w NS]
clkcmp -e SECS
```

**Setup.**
- `cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec`. If it is 0: print `CLK ERROR cps=0`, exit 1.
- The CPU count comes from `_syspage_ptr->num_cpu`. With one CPU, the CPU-1 and cross-CPU modes are skipped, each with a `CLK SKIP` line.
- The resolution comes from `clock_getres(CLOCK_MONOTONIC)`.
- Defaults: `REPS=5`, `MS=1000`, `NS=1000000`.

**Pinning.**
- Before each bracket: `ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)(1u << cpu))`.
- After the bracket, `SchedGetCpuNum()` must equal the target CPU. Otherwise the sample is unusable, with `why=migrated`.

**Sample.** As §1.4.

**Output.** One line per sample, then one per mode:
```
CLK HDR cps=<u64> ncpu=<n> reps=<r> interval_ms=<i> wide_ns=<w> res_ns=<u64>
CLK S mode=<same0|same1|cross> rep=<k> cpuA=<a> cpuB=<b> c0=<u64> c1=<u64> m0=<u64> m1=<u64> m2=<u64> m3=<u64> cc_ns=<u64> mono_ns=<u64> err_ns=<i64> wA=<u64> wB=<u64> tol_ns=<u64> tolres_ns=<u64> usable=<0|1> strict=<0|1> res=<0|1> why=<ok|wide|migrated>
CLK VERDICT mode=<same0|same1|cross> usable=<n> strict=<n> res=<n> result=<agree|agree-within-resolution|disagree|unusable>
```

**`-e SECS`.**
1. Pin to CPU 0, take a reading, print `CLK EXT start c=<u64> mono_ns=<u64> cps=<u64>`, and `fflush`.
2. `clock_nanosleep` to an absolute time `SECS` after the start reading.
3. Take a reading, print `CLK EXT end c=<u64> mono_ns=<u64> dcc=<u64> dmono_ns=<u64>`, and `fflush`.

**Arithmetic.**
- All values are unsigned 64-bit, and the product goes through `unsigned __int128`.
- Mid-points are computed as `a/2 + b/2 + (a%2 + b%2)/2`, so they cannot overflow.
- `err_ns` is signed.

**Exit codes:**

| Exit | When |
|---|---|
| 0 | Every mode that ran is `agree` or `agree-within-resolution` |
| 1 | Any mode is `disagree` |
| 3 | Any mode is `unusable` and none disagrees |
| 2 | Usage error |

**Not done:** no busy-wait, no averaging, and no judgement about real time. There is no Tegra-specific code, so the board M4 image can carry the tool unchanged. Build with `-Wall -Wextra -Werror`, as tools/Makefile:10 does.

### 5.2 `tools/trcctl.c` (Apache-2.0)

```
trcctl -m ID TEXT
trcctl -x
```

- **`-m`:** `TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, ID, TEXT)`.
  - The constant is at sdpinc/sys/trace.h:63; the prototype at sdpinc/sys/neutrino.h:946.
  - ID must be 0-1023 (trace.h:163-164), and TEXT 1-63 bytes.
  - Prints `TRCCTL insert id=<n> text=<t> rc=<r> errno=<e>`.
- **`-x`:** `TraceEvent(_NTO_TRACE_STOP)` (trace.h:42). Prints `TRCCTL stop rc=<r> errno=<e>`.
- **Exit:** 0 when `rc != -1`, 1 otherwise, 2 on usage. No retry and no wait: the caller bounds the wait for tracelogger to exit.
- **Marker IDs:**

  | ID | Text |
  |---|---|
  | 1 | `m4d-probe` |
  | 10 | `m4d-w1-start` |
  | 20 | `m4d-ipc-start` |
  | 21 | `m4d-ipc-end` |

- **Why a tool, not a signal:** D3. It is also the bracket M4 will need around its own board workload (§8).

### 5.3 The host snippet and `m4dry/m4dry-host.ksh.in`

**As run in attempt 1.** The template below is revision 2's. The committed `m4dry-host.ksh.in` differs from it as §13.2 lists:
- the counter's `-p` format (D-a);
- `reap` after each pass (D-f);
- the probe's `M4D TPFMT` lines (D-h);
- the `@W2_S@` marker (§13.3).

From attempt 2 on, the committed file is authoritative.

**`m4dry/post_start-m4dry.custom`** is the whole snippet:
```
# post_start-m4dry.custom: Phase 3b checklist 7b dry run (m4-dryrun-design.md).
# mkqnximage appends this to the variant host's post_startup.sh. Everything the
# dry run does is in /system/bin/m4dry-host.ksh; this line only runs it.
/proc/boot/ksh /system/bin/m4dry-host.ksh
```
`/proc/boot/ksh` exists (qhvh/ifs.build:29).

**Rules for the script.**
1. **Every wait is bounded.** It is either a `bwait` with a bound, or a finite pipeline over a RAM file. The 4900 s guard covers the rest.
2. **Quiet while qvm runs.** Nothing heavier than `pidin`, `trcctl` and the `load` clock run runs while qvm is up (§3.2).
3. **Records first.** Record lines print as soon as they exist, and the summary reprints the key ones. The bulk blocks come last.
4. **Absolute paths for spawned programs.** Every program `bwait -k` spawns is named by absolute path (bwait.c:21-22). Inside `ksh -c`, and in plain calls, commands are found through PATH `/proc/boot:/system/bin` (qhvh/ifs.build:20).
5. **Pipes and command substitution are allowed here.** The TCG host starts `pipe` (qhvh/startup.sh:41), and its post_startup.sh already uses both (qhvh/post_startup.sh:79). The board image forbids both (m3-host.ksh.in:11); see §8.

**Worst case.** Adding up every bounded term (§3.1, with 300 s per traceprinter pass, 180 s per gzip and the `load` clock run's 130 s wait) comes to about 4,400 s. The dump output on top of that is finite but unbounded, so the guard is 4900 s and the launcher's wall bound is 5500 s.

**The template.** The build substitutes every `@X@` marker (§5.5 step 5):

```ksh
## m4dry-host.ksh.in: the checklist 7b host script template (Phase 3b).
##
## Byte for byte the script in results/orin-native-port/20260909T1100Z/
## m4-dryrun-design.md §5.3 (revision 2), below these ## lines, which
## build-m4dry-image.ps1 drops. Markers: @VARIANT@ @BUILD_UTC@ @TRACE_SET@
## @SET_LINES@ @W2_K@ @W1_SECS@ @GRACE@ @GUEST_MD5@ @DISK_MD5@ @CLIENT_MD5@.
## The build fails if any @[A-Z0-9_]+@ survives. TCG host only: this script
## uses pipes and command substitution, which the board image forbids.
# m4dry-host.ksh: generated from m4dry-host.ksh.in; edit the template.
S=/dev/shmem
T=/system/bin
D=/data/hypervisor
G=$D/guest
VARIANT=@VARIANT@
W1_SECS=@W1_SECS@
GRACE=@GRACE@
W2_K=@W2_K@
W2F=/dev/shmem/t.kev
FAIL=
LAUNCHED=
QPID=

say()   { echo "M4D $*"; }
state() { echo "M4D STATE $*"; }
fail()  { say "FAIL $*"; FAIL=${FAIL:-$1}; }
nbytes() { wc -c < "$1" | tr -d ' '; }
mem() {
	pidin info > $S/mem.$1 2>&1
	while read -r l; do
		case "$l" in
		*FreeMem:*) f=${l#*FreeMem:}; say "MEM $1 ${f%% *}" ;;
		esac
	done < $S/mem.$1
}
# kevpath NAME: the first non-empty of the two places -M may put NAME (D2),
# then of every file named NAME anywhere under /dev/shmem.
kevpath() {
	for p in $S/$1 $S/dev/shmem/$1 $(find $S -name "$1" 2>/dev/null); do
		if [ -s "$p" ]; then echo "$p"; return 0; fi
	done
	echo none
	return 1
}
# stopladder W: end the background tracelogger whose subshell creates $S/W.done (D3).
stopladder() {
	by=none
	if [ -e $S/$1.done ]; then
		by=self
	else
		$T/trcctl -x
		if bwait -p $S/$1.done -t 120; then
			by=stop
		else
			slay -f -Q -s INT tracelogger
			if bwait -p $S/$1.done -t 30; then
				by=sigint
			else
				slay -f -Q -s KILL tracelogger
				bwait -p $S/$1.done -t 10 && by=kill
			fi
		fi
	fi
	say "STOP $1 by=$by"
}
# process W NAME: the three passes of §2.1 steps 5-7 over one window's .kev.
process() {
	w=$1
	K=$(kevpath $2)
	if [ "$K" = none ]; then say "KEVFILE $w path=none"; return 1; fi
	km=$(md5sum $K); kc=$(cksum $K)
	say "KEVFILE $w path=$K bytes=$(nbytes $K) md5=${km%% *} cksum=${kc% *}"
	bwait -k 300 -o $S/$w.plan -e $S/$w.plan.err -- /proc/boot/ksh -c "$T/traceprinter -f $K | grep -E 'QVM|Class 10|GUEST' | wc -l -c"
	read -r L B < $S/$w.plan
	say "PLANFILTER $w lines=$L bytes=$B"
	head -c 256 $S/$w.plan.err
	bwait -k 300 -o $S/$w.cnt -e $S/$w.cnt.err -- /proc/boot/ksh -c "$T/traceprinter -n -p 'M4H|%C|%Z|%z|%e|' -f $K | gawk -F'|' -v w=$w -v qpid=${QPID:-none} -f $T/m4dry-count.awk"
	cat $S/$w.cnt
	head -c 256 $S/$w.cnt.err
	if [ "$w" = w2 ]; then
		bwait -k 300 -o $S/$w.corr -e $S/$w.corr.err -- /proc/boot/ksh -c "$T/traceprinter -n -f $K | grep -E 'QVM *:' > $S/w2.flt; wc -l -c < $S/w2.flt"
	else
		bwait -k 300 -o $S/$w.corr -e $S/$w.corr.err -- /proc/boot/ksh -c "$T/traceprinter -n -f $K | grep -E 'QVM *:' | wc -l -c"
	fi
	read -r L B < $S/$w.corr
	say "CORRFILTER $w lines=$L bytes=$B"
	head -c 256 $S/$w.corr.err
	slay -f -Q -s KILL traceprinter
	return 0
}
# kevblock W NAME: send one .kev as gzip + base64, capped (§6).
kevblock() {
	K=$(kevpath $2)
	if [ "$K" = none ]; then say "KEV SKIP name=$1 reason=absent"; return; fi
	bwait -k 180 -o $S/$1.gz -e $S/$1.gz.err -- $T/gzip -c $K
	gb=$(nbytes $S/$1.gz)
	if [ "$gb" -gt 16777216 ]; then
		say "KEV SKIP name=$1 reason=over-cap gz_bytes=$gb"
	else
		km=$(md5sum $K); gm=$(md5sum $S/$1.gz)
		say "KEV BEGIN name=$1 bytes=$(nbytes $K) md5=${km%% *} gz_bytes=$gb gz_md5=${gm%% *} enc=gzip-base64"
		base64 $S/$1.gz
		say "KEV END name=$1"
	fi
	rm -f $S/$1.gz
}

state guard
bwait -g 4900 &

state config
say "CONFIG variant=$VARIANT build_utc=@BUILD_UTC@ image=rebuilt-host guest=byte-identical trace_set=@TRACE_SET@ w2_k=${W2_K:-plan} w1_secs=$W1_SECS grace=$GRACE guest_md5=@GUEST_MD5@ disk_md5=@DISK_MD5@ client_md5=@CLIENT_MD5@ plan_w2='-r -M -S 8M -f /dev/shmem/t.kev'"
uname -a
mem boot
bwait -k 30 -o $S/tp0.out -e $S/tp0.err -- $T/traceprinter -f $S/absent.kev
head -c 512 $S/tp0.out
head -c 512 $S/tp0.err

state preflight
bwait -p /dev/ptyp0 -t 10 || fail preflight_pty
bwait -k 180 -o $S/md5.pre -e $S/md5.pre.err -- $T/md5sum $G/ifs.bin $G/disk-qvm $D/qnx-host-client
cat $S/md5.pre
grep -q "^@GUEST_MD5@ " $S/md5.pre && say "CHECK md5_pre ifs.bin ok" || fail md5_pre_ifs.bin
grep -q "^@DISK_MD5@ " $S/md5.pre && say "CHECK md5_pre disk-qvm ok" || fail md5_pre_disk-qvm
grep -q "^@CLIENT_MD5@ " $S/md5.pre && say "CHECK md5_pre client ok" || fail md5_pre_client

state clock_pre
bwait -k 120 -o $S/clk.pre -e $S/clk.pre.err -- $T/clkcmp
cat $S/clk.pre
head -c 256 $S/clk.pre.err
$T/clkcmp -e 10

state probe
( bwait -k 600 -o $S/p.out -e $S/p.err -- $T/tracelogger -r -M -S 1M -f /dev/shmem/p.kev; : > $S/p.done ) &
sleep 3
$T/trcctl -m 1 m4d-probe
sleep 1
stopladder p
head -c 512 $S/p.out
head -c 512 $S/p.err
find /dev/shmem -name '*.kev'
PK=$(kevpath p.kev)
if [ "$PK" != none ]; then
	bwait -k 120 -o $S/p.txt -e $S/p.txt.err -- $T/traceprinter -n -f $PK
	PM=absent
	grep -q m4d-probe $S/p.txt && PM=found
	say "PROBE path=$PK bytes=$(nbytes $PK) marker=$PM"
else
	say "PROBE path=none bytes=0 marker=absent"
fi
case "$PK" in
$S/p.kev)           W2F=/dev/shmem/t.kev; WHY=probe-literal ;;
$S/dev/shmem/p.kev) W2F=/t.kev; WHY=probe-doubled ;;
none)               W2F=/dev/shmem/t.kev; WHY=probe-none ;;
*)                  W2F=/dev/shmem/t.kev; WHY=probe-elsewhere ;;
esac
say "W2F path=$W2F reason=$WHY"
rm -f $S/p.txt $S/p.kev $S/dev/shmem/p.kev
[ "$PK" != none ] && rm -f "$PK"

if [ -z "$FAIL" ]; then
	state disk
	devb-loopback loopback blksz=512,prefix=qvmdisk,fd=$G/disk-qvm
	bwait -p /dev/qvmdisk0 -t 10 || fail disk_dev
	printf 'system mkqnximage-guest\n@SET_LINES@ram 0x80000000,512M\ncpu\nload /data/hypervisor/guest/ifs.bin\nvdev pl011\n hostdev >-\n loc 0x1c090000\n intr gic:37\nvdev virtio-console\n loc 0x20000000\n intr gic:42\n hostdev /dev/ptyp0\nvdev virtio-blk\n loc 0x1c0d0000\n intr gic:41\n hostdev /dev/qvmdisk0\n name vblk0\nvdev shmem\n loc 0x1c0f0000\n intr gic:43\n allow phase2-rq2-probe\n' > $G/g2.conf
	cat $G/g2.conf
fi

if [ -z "$FAIL" ]; then
	state w1
	( bwait -k $((W1_SECS + 600)) -o $S/w1.out -e $S/w1.err -- $T/tracelogger -s $W1_SECS -S 32M -f /dev/shmem/w1.kev; : > $S/w1.done ) &
	sleep 2
	$T/trcctl -m 10 m4d-w1-start
	state qvm
	echo "=== launching qvm @g2.conf (background) ==="
	( qvm @$G/g2.conf < /dev/null; echo "rc=$?" > $S/qvm.rc; : > $S/qvm_exit.hit ) &
	bwait -s $GRACE -c $S/grace.hit &
	LAUNCHED=1
	state clock_load
	( bwait -k 120 -o $S/clk.load -e $S/clk.load.err -- $T/clkcmp; : > $S/clkl.done ) &
	state w1_wait
	if bwait -p $S/w1.done -t $((W1_SECS + 120)); then say "STOP w1 by=self"; else stopladder w1; fi
	head -c 512 $S/w1.out
	head -c 512 $S/w1.err
	CL=no; [ -e $S/clkl.done ] && CL=yes
	say "CLKLOAD done_at_w1_stop=$CL"
	bwait -p $S/clkl.done -t 130 || say "CLKLOAD wait=timeout"
	cat $S/clk.load
	head -c 256 $S/clk.load.err
	pidin -p qvm -f abNli > $S/pq.1 2>&1
	head -n 40 $S/pq.1
	QPID=$(pidin -p qvm -f a 2>/dev/null | grep -E '^ *[0-9]+ *$' | head -n 1 | tr -d ' ')
	say "QPID ${QPID:-unknown}"
	mem w1
fi

if [ -n "$LAUNCHED" ]; then
	state grace_wait
	bwait -p $S/grace.hit -p $S/qvm_exit.hit -t $((GRACE + 30))
	if [ -e $S/qvm_exit.hit ]; then
		fail qvm_exited_early
		cat $S/qvm.rc
	else
		state w2
		( bwait -k 1800 -o $S/w2.out -e $S/w2.err -- $T/tracelogger -r ${W2_K:+-k $W2_K} -M -S 8M -f $W2F; : > $S/w2.done ) &
		sleep 2
		$T/trcctl -m 20 m4d-ipc-start
		state ipc
		bwait -k 600 -r $S/ipc.bwait -o $S/ipc.out -e $S/ipc.err -- $D/qnx-host-client 15 /dev/ttyp0 5
		$T/trcctl -m 21 m4d-ipc-end
		sleep 2
		state w2_stop
		stopladder w2
		head -c 512 $S/w2.out
		head -c 512 $S/w2.err
		state report_ipc
		cat $S/ipc.out
		head -c 2048 $S/ipc.err
		pidin -p qvm -f abNli > $S/pq.2 2>&1
		head -n 40 $S/pq.2
		mem ipc
	fi
	state teardown
	slay -f -Q qvm
	bwait -p $S/qvm_exit.hit -t 15 || { slay -f -Q -s KILL qvm; bwait -p $S/qvm_exit.hit -t 5; }
	[ -e $S/qvm.rc ] && cat $S/qvm.rc
fi

state clock_post
bwait -k 120 -o $S/clk.post -e $S/clk.post.err -- $T/clkcmp
cat $S/clk.post

state process_w1
process w1 w1.kev
state process_w2
if [ -e $S/w2.done ]; then process w2 t.kev; else say "KEVFILE w2 path=none reason=not-run"; fi
mem processed

state summary
for c in pre load post; do
	[ -e $S/clk.$c ] || continue
	while read -r l; do
		case "$l" in "CLK VERDICT "*) say "CLKSUM run=$c ${l#CLK VERDICT }" ;; esac
	done < $S/clk.$c
done
[ -e $S/ipc.out ] && grep -E '^(samples=|P50=|sentinel_)' $S/ipc.out
[ -e $S/ipc.bwait ] && cat $S/ipc.bwait
grep -h -E '^M4D (QVM|QVMBY|QVMFIELDS|MARKERS) ' $S/w1.cnt $S/w2.cnt
say "FAIL_STATE ${FAIL:-none}"

state flt
if [ -s $S/w2.flt ]; then
	head -n 20000 $S/w2.flt > $S/w2.fltc
	fm=$(md5sum $S/w2.fltc); fc=$(cksum $S/w2.fltc)
	say "FLT BEGIN name=w2 lines=$(wc -l < $S/w2.fltc | tr -d ' ') of=$(wc -l < $S/w2.flt | tr -d ' ') bytes=$(nbytes $S/w2.fltc) md5=${fm%% *} cksum=${fc% *}"
	cat $S/w2.fltc
	say "FLT END name=w2"
else
	say "FLT SKIP name=w2 reason=absent-or-empty"
fi

state kev
kevblock w2 t.kev
kevblock w1 w1.kev

state end
mem end
say "FAIL_STATE ${FAIL:-none}"
sleep 1
shutdown -S reboot
```

**Notes on the script.**
- **Background wrappers.** Both trace windows and the probe run tracelogger under `bwait -k`, inside a subshell that creates `<W>.done` when bwait returns. The wait therefore never depends on when bwait writes a record file.
- **Kill bounds.** The `-k` bound always exceeds the wait plus the full ladder. bwait can never SIGKILL tracelogger while the ladder is still working.
- **Placement of the g2.conf check.** `cat $G/g2.conf` prints the configuration qvm actually read. With `@SET_LINES@` empty (the `plan` and `k64` variants), the `printf` text equals the canonical one (qhvh/post_startup.sh:50) byte for byte.
- **Where `.kev` names resolve.** W1's `-f /dev/shmem/w1.kev` has no `-M`, so the file is `/dev/shmem/w1.kev`. `kevpath t.kev` covers both predicted W2 outcomes, `/dev/shmem/t.kev` and `/dev/shmem/dev/shmem/t.kev` (the literal path under doubling), and then any file named `t.kev` under `/dev/shmem`.
- **The `load` clock run** starts after qvm and is waited for only after W1 has stopped. Its `-k 120` bound means the 130 s wait always outlasts it, so it has ended before W2 starts.
- **The FLT cap is by lines,** so the block never ends mid-line and `M4D FLT END` always starts a line.

### 5.4 `m4dry/m4dry-count.awk`

**As run in attempt 1.** The rules and listing below are revision 2's. The committed counter and the parser's port of it follow §13.2 instead:
- no `%e`, and classification by printed class and subtype name only (D-a);
- both spellings of the interrupt subtypes, and both word orders of the timer subtypes (D-b);
- unrecognised QVM subtypes listed on `M4D QVMOTHER`;
- `M4D HIST` keyed by class and subtype;
- `M4D QVMBY` and `M4D DISAGREE` removed.

From attempt 2 on, the committed files are authoritative.

- **What it reads:** the output of `traceprinter -n -p 'M4H|%C|%Z|%z|%e|'`. With `-F'|'`, field 1 is `M4H`, then come CPU, class, subtype and event id, then the argument text.
- **What it prints:** only `M4D` lines. It needs gawk, which the host has (qhvh/system.build:83): it uses gawk's `and()` and `strtonum()`.
- **If the combined format fails:** a missing `-n` join or `-p` layout shows as `unformatted_lines` above `events`, with `cycles_zero_or_missing` counting every event classified 7. The parser then marks the on-target counter `suspect(format)` and relies on the PC recount.
- **How it classifies an event.** Twice, independently (D1):
  - **by name:** the printed subtype, against the suffixes of the `_NTO_TRACE_QVM_*` constants (trace.h:286-293);
  - **by number:** only when the printed class looks like Class 10, the `%e` field read as a Class-10 event number. A bare number must be 0-7. A class-coded number must carry class 10 in bits 10-14 (trace.h:237) and an event number of 0-7 in bits 0-9 (:239).
- **The class test** matches `QVM` or `HYP`, and also a class printed as `Class 10`, the form the plan's own pattern expects (plan:395). No source shows traceprinter printing that form (HYPOTHESIS). An event whose subtype name matches is counted even when its class does not.
- **The pass-relevant count** (`M4D QVM idN=`) counts each event once: under its name's ID when the name is known, otherwise under its number's ID. When both are known and differ, the name wins and `conflict` rises.
- **Both classifications, separately,** go on `M4D QVMBY`, with `agree`, `name_only`, `num_only` and `conflict`. The first three disagreeing lines are quoted as `M4D DISAGREE`.
- **Payload checks follow the classification,** not the name. ID 7's check runs on every event classified 7, and ID 1's on every event classified 1.
- **Offsets are compared as values.** Each `clockcycles_offset` is lower-cased and stripped of leading zeros before it enters the distinct-offset set. A width or case difference in traceprinter's formatting therefore cannot look like a changed offset.
- **The histogram is printed in full up to 4096 keys.** `hist_printed` beside `hist_keys` says whether it was complete. Inspecting a `FAIL (unverified)` needs the two to be equal (§1.2).
- **Samples** are keyed by classified ID (`id0` to `id7`), or by subtype for anything unclassified, three of each.

```awk
# m4dry-count.awk: per-window counts over
#   traceprinter -n -p 'M4H|%C|%Z|%z|%e|' -f <kev>
# Run as: gawk -F'|' -v w=<window> -v qpid=<pid|none> -f m4dry-count.awk
# Prints only M4D lines. gawk only: uses and() and strtonum().
# Each event is classified twice (m4-dryrun-design.md §5.4):
#  - by name: the subtype against the suffixes of the _NTO_TRACE_QVM_*
#    constants (sys/trace.h:286-293);
#  - by number: when the class looks like Class 10 (QVM, HYP or "Class 10"),
#    %e as an event number 0-7, bare or with class 10 in bits 10-14
#    (sys/trace.h:237-239, :370).
# How traceprinter prints the class, the subtype and %e is HYPOTHESIS, so the
# two classifications are counted separately and disagreements are reported.
# Payloads are matched by field name only.
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function hexval(name) {
	if (match($0, name ":0x[0-9a-fA-F]+"))
		return substr($0, RSTART + length(name) + 3, RLENGTH - length(name) - 3)
	return ""
}
function nonzero(h) { return h ~ /[1-9a-fA-F]/ }
# canon: one spelling per hex value, so formatting cannot fake a new offset.
function canon(h) { h = tolower(h); sub(/^0+/, "", h); return h == "" ? "0" : h }
# evnum: the Class-10 event number that %e carries, or -1.
# 31744 = 0x1f<<10 (the class bits), 10240 = 10<<10, 1023 = 0x3ff (the event bits).
function evnum(s,   v) {
	if (s ~ /^0[xX][0-9a-fA-F]+$/) v = strtonum(s)
	else if (s ~ /^[0-9]+$/) v = s + 0
	else return -1
	if (v <= 7) return v
	if (and(v, 31744) == 10240 && and(v, 1023) <= 7) return and(v, 1023)
	return -1
}
BEGIN {
	id["GUEST_ENTER"] = 0; id["GUEST_EXIT"] = 1; id["CREATE_VCPU_THREAD"] = 2
	id["RAISE_INTR"] = 3; id["LOWER_INTR"] = 4; id["TIMER_CREATE"] = 5
	id["TIMER_FIRE"] = 6; id["CYCLES"] = 7
}
/m4d-w1-start/  { mk_w1++ }
/m4d-ipc-start/ { mk_is++ }
/m4d-ipc-end/   { mk_ie++ }
$1 != "M4H"     { unformatted++; next }
{
	events++
	cls = trim($3); st = trim($4); ev = trim($5)
	hist[cls "|" st "|" ev]++
	isq = (toupper(cls) ~ /QVM|HYP|CLASS[ _]*0*10([^0-9]|$)/)
	byname = (st in id) ? id[st] : -1
	bynum = isq ? evnum(ev) : -1
	if (isq || byname >= 0) {
		qvm++
		if (byname >= 0) nname[byname]++
		if (bynum >= 0) nnum[bynum]++
		if (byname >= 0 && bynum >= 0) { if (byname == bynum) agree++; else conflict++ }
		else if (byname >= 0) name_only++
		else if (bynum >= 0) num_only++
		cid = (byname >= 0) ? byname : bynum
		if (cid >= 0) n[cid]++; else qother++
		if (byname != bynum && ndis++ < 3)
			print "M4D DISAGREE " w " name=" byname " num=" bynum " " substr($0, 1, 200)
		if (cid == 7) {
			e = hexval("at_entry"); x = hexval("at_exit")
			if (e != "" && x != "" && nonzero(e) && nonzero(x)) cyc_ok++; else cyc_bad++
		}
		if (cid == 1) {
			o = hexval("clockcycles_offset")
			if (o != "") { off_seen++; offs[canon(o)] = 1 }
			s = hexval("status")
			if (s != "" && !nonzero(s)) status0++
		}
		sk = (cid >= 0) ? "id" cid : "sub=" st
		if (qsample[sk]++ < 3) print "M4D SAMPLE " w " " sk " " substr($0, 1, 200)
	} else {
		nonqvm++
		if (st ~ /THRUNNING|INT_ENTR|INT_EXIT/ && ksample[st]++ < 2) print "M4D SAMPLE " w " sub=" st " " substr($0, 1, 200)
	}
	if (qpid != "none" && st ~ /THRUNNING/ && match($0, /pid:[0-9]+/)) {
		p = substr($0, RSTART + 4, RLENGTH - 4)
		if (p == qpid && match($0, /tid:[0-9]+/)) thr[substr($0, RSTART + 4, RLENGTH - 4)]++
	}
}
END {
	nk = 0; np = 0
	for (h in hist) { nk++; if (np < 4096) { np++; print "M4D HIST " w " " h " " hist[h] } }
	printf "M4D QVM %s id0=%d id1=%d id2=%d id3=%d id4=%d id5=%d id6=%d id7=%d qvm_other=%d qvm_total=%d non_qvm=%d events=%d unformatted_lines=%d hist_keys=%d hist_printed=%d\n", w, n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7], qother, qvm, nonqvm, events, unformatted, nk, np
	printf "M4D QVMBY %s name=%d,%d,%d,%d,%d,%d,%d,%d num=%d,%d,%d,%d,%d,%d,%d,%d agree=%d name_only=%d num_only=%d conflict=%d\n", w, nname[0], nname[1], nname[2], nname[3], nname[4], nname[5], nname[6], nname[7], nnum[0], nnum[1], nnum[2], nnum[3], nnum[4], nnum[5], nnum[6], nnum[7], agree, name_only, num_only, conflict
	d = 0; for (o in offs) d++
	printf "M4D QVMFIELDS %s cycles_both_nonzero=%d cycles_zero_or_missing=%d exit_with_offset=%d offsets_distinct=%d exit_status_zero=%d\n", w, cyc_ok, cyc_bad, off_seen, d, status0
	t = 0; for (i in thr) if (t++ < 32) print "M4D QVMTID " w " tid=" i " thrunning=" thr[i]
	printf "M4D MARKERS %s w1_start=%d ipc_start=%d ipc_end=%d\n", w, mk_w1, mk_is, mk_ie
}
```

**The PASS-relevant fields.**
- The verdict reads `id0`, `id1` and `id7` from the `M4D QVM` line (§1.2).
- The parser marks the counter `suspect(classify)` when `M4D QVMBY` shows `conflict` above zero, or when its name and number columns disagree about whether ID 0, 1 or 7 is present at all. The PC recount then decides.
- `fields=` reads `cycles_both_nonzero`, `exit_with_offset` and `offsets_distinct` (§1.3).
- W1 holds a single qvm instance, so `offsets_distinct` should be 1 there. The same holds for W2.

**Formats this rests on.** The `pid:`/`tid:` layout of THRUNNING lines, and the printed names of the INTERRUPT events, are HYPOTHESIS ([sat-events] gives the payload names pid, tid, priority and policy). The samples show the real layout, and the PC analysis does not depend on this script.

### 5.5 `m4dry/build-m4dry-image.ps1`

```
build-m4dry-image.ps1 [-Variant plan|k64|vtwfe] [-W1Secs 60] [-Grace 150]
```

**Rules.**
- Windows PowerShell 5.1. Native commands run as `cmd /c '... 2>&1'`, with `$LASTEXITCODE` checked.
- It exits 0 only if every check passed.
- It never deletes a directory.
- It writes only under `run/` and `orin-native/tools/`. The tool binaries are git-ignored.

1. **Parameters.**

   | Variant | `@W2_K@` | `@TRACE_SET@` | `@SET_LINES@` |
   |---|---|---|---|
   | `plan` | empty | `defaults` | empty |
   | `k64` | `64` | `defaults` | empty |
   | `vtwfe` | empty | `vtimer-wfe` | the literal text `set trace-vtimer on\nset trace-wfe on\n`, with backslash-n kept, because it lands inside the script's `printf` format |

   `@W1_SECS@` and `@GRACE@` come from `-W1Secs` and `-Grace`, and `@BUILD_UTC@` from the clock.
2. **Canonical checks:** §4.3 steps 1 and 2.
3. **The guest copy.**
   - If `run/guest.partial` exists, refuse: an earlier copy was interrupted, and the owner renames it.
   - If `run/guest` is absent, copy `qhv/guest` recursively to `run/guest.partial`, then rename that to `run/guest`. A present `run/guest` is therefore always a completed copy.
   - Then run §4.4 step 1. A mismatch stops the build here, before step 4, with exit 1 (§9).
4. **Tools.** In the SDP environment (`call "%USERPROFILE%\qnx800\qnxsdp-env.bat"`, as `build-qhv.bat:34` does), run `make -C orin-native/tools bwait clkcmp trcctl`.
   - Record the sha256 of all three binaries.
   - The IPC client is not rebuilt. Record its sha256 and compare it with the value M3 pinned (m3-design.md §8 item 3). A difference is recorded, not refused.
5. **Stage the build directory.** Copy `qhv/host/local` to `run/host-<variant>/local`. Then:
   - **Snippets.** Replace the files in `local/snippets/`:
     - `post_start.custom` ← `m4dry/post_start-m4dry.custom`;
     - `data_files.custom`, `ifs_files.custom`, `ifs_start.custom` and `profile.custom`: kept as copied. The first is exactly the canonical client line (qhvh/data.build:82); the other three are placeholders;
     - `system_files.custom`: the canonical placeholder, plus seven lines:
       ```
       bin/traceprinter=usr/bin/traceprinter
       lib/libtraceparser.so.1=usr/lib/libtraceparser.so.1
       [perms=555] bin/bwait=<repo>/orin-native/tools/bwait
       [perms=555] bin/clkcmp=<repo>/orin-native/tools/clkcmp
       [perms=555] bin/trcctl=<repo>/orin-native/tools/trcctl
       [perms=555] bin/m4dry-host.ksh=<repo>/qhv/m4dry/stage-<variant>/m4dry-host.ksh
       [perms=444] bin/m4dry-count.awk=<repo>/qhv/m4dry/stage-<variant>/m4dry-count.awk
       ```
       The first two follow the form of qhvh/system.build:50 and :74. `<repo>` is written with forward slashes, as `build-qhv.bat:50-51` notes mkqnximage needs.
   - **Options.** Rewrite only the `OPT_GUEST=` line of `local/options`, to `<repo>/qhv/m4dry/guest`.
   - **Script.** Generate `run/stage-<variant>/m4dry-host.ksh` from `m4dry/m4dry-host.ksh.in`: drop the `##` lines, substitute the markers, and fail if any `@[A-Z0-9_]+@` survives.
   - **Awk.** Copy `m4dry-count.awk` into the stage directory.
   - **Line endings.** Write the script, the awk file and every snippet with LF endings and no BOM. PowerShell's `Set-Content` would write CRLF, so use `[IO.File]::WriteAllText(path, text.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))`.
6. **Build.** From `run/host-<variant>`, inside `cmd /c`, after `qnxsdp-env.bat`:
   ```
   mkqnximage --type=qemu --arch=aarch64le --hostname=qnx-qhv --qvm=yes --guest=<repo>/qhv/m4dry/guest --build < NUL
   ```
   - This is `build-qhv.bat:102`'s host command with only `--guest` changed.
   - Output is appended to the build log, and the build is killed at 1800 s.
   - If it exits non-zero and the output mentions `ssh-ident` or a prompt, rerun it once with `--ssh-ident=none`. Record `ssh_ident=none (differs from canonical; the dry run uses no ssh)`. [mkq-help]: `prompt` is the default, and `--noprompt` makes a required prompt fail rather than wait.
7. **Check the generated text** (reading our own build files):
   - `output/build/post_startup.sh` contains `/system/bin/m4dry-host.ksh` and does not contain `qvm @`.
   - `output/build/system.build` contains the seven lines of step 5, plus `bin/tracelogger=usr/sbin/tracelogger` and `lib/libtracelog.so.1`.
   - `output/build/ifs.build` boots `procnto-smp-instr`. [tracelogger] requires an instrumented kernel; the canonical one is at qhvh/ifs.build:22.
   - `output/build/data.build` passes §4.4 step 2.
   - `output/ifs.bin` and `output/disk-qemu` exist.
8. **Hashes after:** §4.4 step 3 and §4.3 step 3. Then write `output/M4DRY-SHA256SUMS` for the variant's `ifs.bin` and `disk-qemu`.
9. **Build log.** Record in `run/build-<variant>.log`:
   - the UTC time, the variant and its parameters;
   - the mkqnximage command and its exit code;
   - every sha256 above, and the md5 pins substituted into the script;
   - the sha256 of the SDP files the dry run depends on, as opaque hashes only: `sdp/sbin/qvm`, `sdp/usr/sbin/tracelogger`, `sdp/lib/libtracelog.so.1`, `sdp/usr/bin/traceprinter` and `sdp/usr/lib/libtraceparser.so.1`.

### 5.6 `m4dry/launch-m4dry-tcg.ps1`

```
launch-m4dry-tcg.ps1 -Attempt <N> [-Variant plan] [-QemuPath <exe>] [-WallSeconds 5500]
                     [-EndGraceSeconds 90] [-PollMs 50] [-MinFreeGB 4] [-ParserSeconds 2400]
```

1. **Paths.**
   - The image directory is `run/host-<variant>/output`.
   - Refuse it per §4.3 step 1.
   - `M4DRY-SHA256SUMS` must exist and pass.
2. **Canonical checks before:** §4.3 step 2. Record `canonical_pre=ok`.
3. **Output.**
   - Create `out/` if it is absent.
   - Refuse if any `out/attempt<N>-*` file exists, or if `run/attempt<N>/` exists. Nothing is ever overwritten.
   - Create `run/attempt<N>/`.
4. **PC memory.** Read free physical memory (`Win32_OperatingSystem`). Refuse below `-MinFreeGB`, and record the value.
5. **Provenance.** Write the following to `out/attempt<N>-launch.log`. Every occurrence of the Windows user name and the profile path is replaced by `<user>`.
   - the UTC time, the Windows version and the CPU;
   - the first line of `qemu --version`, captured the way launch-qhv-tcg.ps1:115 does, plus the QEMU path;
   - the full QEMU argument list;
   - `devices: virtio-blk + virtio-net(slirp) + virtio-rng(builtin)` and `disk: -snapshot`;
   - the variant, and the variant image's sha256 lines.

   Copy `run/build-<variant>.log` to `out/attempt<N>-build.log`, redacted the same way.
6. **QEMU command.** The argument list of launch-qhv-tcg.ps1:146-158 with `-WithRng`, changing only the two image paths and the serial file:
   ```
   -machine virt,virtualization=on,gic-version=3 -cpu max -accel tcg -smp 2 -m 2G -snapshot
   -drive file=<image dir>/disk-qemu,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0
   -netdev user,id=n0 -device virtio-net-device,netdev=n0
   -object rng-builtin,id=rng0 -device virtio-rng-device,rng=rng0
   -kernel <image dir>/ifs.bin -serial file:<run>/attempt<N>/serial-raw.log -display none -no-reboot
   ```
   - **Which QEMU.** By default, `C:\Program Files\qemu\qemu-system-aarch64.exe`, the build `launch-qhv-tcg.ps1` picks by default (:64-67). `-QemuPath` selects another. The choice is stamped, and nothing in the verdict depends on it, because no timing is a result here.
   - **Why the rng.** It removes the entropy timeout (launch-qhv-tcg.ps1:138-143).
7. **Start QEMU** with `Start-Process -PassThru -NoNewWindow`. Read the process object's `Handle` property once, straight away, as a precaution against the empty `ExitCode` Windows PowerShell 5.1 can report for a process whose handle was never read. Write `QEMU_PID=<pid> started_utc=<t>` to the launch log at once.
8. **Poll, inside `try`/`finally`.**
   - **Read incrementally.** Every `-PollMs`, read only the bytes appended since the last read: open with `FileShare.ReadWrite`, keep the offset, and carry an incomplete last line over to the next read. The file grows by megabytes during the dump, so it is never re-read from the start.
   - **Marks.** For each new line, write `MARK <name> pc_ms=<Stopwatch ms>` on the first sight of:
     - each distinct `M4D STATE <name>`;
     - `CLK EXT start` and `CLK EXT end`;
     - `=== launching qvm @g2.conf`;
     - `server: echo endpoint up` and `QNX qnx-guest`;
     - `samples=`;
     - each `M4D KEV BEGIN` and `M4D KEV END`.
   - **The run ends when any of these happens:**
     - QEMU exits, which is the expected end after `shutdown -S reboot`;
     - `-EndGraceSeconds` have passed since `M4D STATE end`;
     - `-WallSeconds` have passed.
   - **`finally`.**
     - If QEMU is alive, `Stop-Process -Force`, then `Wait-Process -Timeout 15`.
     - Confirm that `Get-Process -Id <pid>` now fails.
     - Write `QEMU_STOPPED how=<exited|end-grace-kill|wall-kill|interrupted> exit=<code|none> alive_after=<no|yes>`.
     - Ctrl+C also lands here.
9. **After the run.**
   - Canonical checks again: `canonical_post=ok`, or `CHANGED`, which stops everything (§4.3 step 3).
   - `M4DRY-SHA256SUMS` again; `-snapshot` keeps it valid.
   - Free memory again.
10. **Parser, bounded the way QEMU is.**
    - Resolve `python` to its full path first, and record it with the user name redacted.
    - Start the parser with `Start-Process -PassThru -NoNewWindow`, reading `Handle` at once (step 7). Its stdout and stderr go to `run/attempt<N>/parser-stdout.log` and `run/attempt<N>/parser-stderr.log`:
      ```
      python orin-native/m4dry/parse-m4dry.py --attempt <N> --serial <run>/attempt<N>/serial-raw.log --launch <out>/attempt<N>-launch.log --run-dir <run>/attempt<N> --out-dir <out> --traceprinter <sdphost>/traceprinter.exe
      ```
    - Write `PARSER_PID=<pid> started_utc=<t> bound_s=<ParserSeconds>` to the launch log at once.
    - **Poll** once a second, inside its own `try`/`finally`, until the parser exits or `-ParserSeconds` have passed. The default sits above the sum of the parser's internal bounds, six host traceprinter passes of 300 s each (§5.7 step 6), with 600 s left for its own work.
    - **`finally`:**
      - First list the parser's descendant processes, recursively by `ParentProcessId` (`Get-CimInstance Win32_Process`). On Windows, stopping a parent does not stop its children, and a launcher shim can put the interpreter itself one level down, so a hung `traceprinter.exe` could otherwise outlive the kill.
      - If the parser or any listed descendant is alive, `Stop-Process -Force` each, then `Wait-Process -Timeout 15`.
      - Confirm that `Get-Process -Id` now fails for the parser and for every listed descendant.
      - Write `PARSER_STOPPED how=<exited|timeout-kill|interrupted> exit=<code|none> descendants_killed=<n> alive_after=<no|yes>`.
    - **A timeout leaves no verdict, and loses nothing.** Every input stays under `run/attempt<N>/`, so the parser can be rerun by hand under the same bound.
11. **Final.**
    - Confirm that no `qemu-system-aarch64` process with the recorded PID remains, and that neither the parser's PID nor any recorded descendant remains. List the files written.
    - Nothing but `.log` files is ever written into `out/`.
    - Exit 0 if QEMU ended by itself or at the end grace and the parser ended `how=exited` with exit 0; otherwise exit 1.

### 5.7 `m4dry/parse-m4dry.py` (Python 3, standard library only; Python 3.12 is on this PC)

```
parse-m4dry.py --attempt N --serial FILE --launch FILE --run-dir DIR --out-dir DIR [--traceprinter EXE]
```

1. **Read.** Read the raw serial log as bytes and decode it as latin-1, which is lossless. Split it into lines and strip the trailing `\r` the console adds.
2. **Elided copy** to `out/attempt<N>-serial.log`.
   - The base64 lines between each `M4D KEV BEGIN` and `M4D KEV END` become a single line: `[parse-m4dry: <k> base64 lines elided; decoded to qhv/m4dry/attempt<N>/<name>.kev]`.
   - The user name becomes `<user>`.
   - Everything else is copied verbatim.
3. **KEV blocks.**
   1. Join the payload lines and base64-decode them, ignoring whitespace.
   2. Check the md5 against `gz_md5`.
   3. gunzip, and check the size and md5 against `bytes` and `md5`.
   4. Write `run/attempt<N>/<name>.kev`.

   **Status per block:** `ok`, `truncated` (no END line), `gz-md5-mismatch`, `md5-mismatch`, `skipped(<reason>)` or `absent`.
4. **FLT block.**
   - Rebuild the listing with `\n` line ends. Compute its md5, its POSIX `cksum` (CRC with the length appended, as toybox `cksum` prints it) and its line count.
   - Compare all three with the BEGIN line: `flt=ok`, `mismatch(<which>)`, `truncated` or `absent`.
   - Write the rebuilt listing to `run/attempt<N>/w2.flt`, never to `out/`.
5. **Records.** Parse every `M4D`, `CLK`, `TRCCTL`, `BWAIT`, `samples=`, `P50=`, `sentinel_` and `rc=` line, keyed by window where one applies. Keep the line position of each `M4D STATE`, `M4D STOP`, `=== launching qvm`, `server: echo endpoint up` and `QNX qnx-guest` line.

   **Derived from those positions:**
   - `w1_covers_banner`: the banner comes before `M4D STOP w1`;
   - `ipc_after_guest_ready`: both the server line and the banner come before `M4D STATE ipc`;
   - `ipc`:
     - `ok`: the client's BWAIT line reads `rc=0 killed=0`, and `samples` plus `sentinel_recoveries` equals 15, M3's completion rule (m3-design.md §8 item 8);
     - `failed`: the client ran, and either of those conditions fails;
     - `skipped`: the client never ran.
6. **Host cross-check.** Runs only with `--traceprinter` and at least one block decoded `ok`.
   - **Three passes per decoded block,** each through `subprocess.run` with a 300 s timeout, which kills the child when it expires. Each takes an argument list and no shell, so `|` and `%` reach traceprinter literally:
     - `traceprinter.exe -f <kev> -o run/attempt<N>/<name>.txt`;
     - `traceprinter.exe -n -f <kev> -o run/attempt<N>/<name>.n.txt`;
     - `traceprinter.exe -n -p "M4H|%C|%Z|%z|%e|" -f <kev> -o run/attempt<N>/<name>.p.txt`, the target counter's own format.
   - If `QNX_HOST` and `QNX_TARGET` are unset, set them in the child's environment from the executable's location.
   - Normalise CRLF to LF.
   - **Recompute:**
     - the literal filter on `<name>.txt`: lines matching `QVM|Class 10|GUEST`, and bytes as the sum of line length plus one;
     - the corrected filter on `<name>.n.txt`: lines matching `QVM *:`;
     - on `<name>.p.txt`, with exactly §5.4's rules: the per-ID counts, both classifications, the payload checks and the offset canonicalisation;
     - a second, name-only reading of the per-ID counts on `<name>.n.txt`'s default format. It does not depend on `-n` combining with `-p`.
   - **The PC count for an ID** is the larger of the two readings.
   - **Completeness, per window, for §1.2:**
     - `complete`: the block decoded `ok`, and the `.p.txt` pass exited 0 within its bound with `events` above zero and `unformatted_lines` no more than `events`;
     - `name-only`: only the `.n.txt` reading succeeded;
     - `none(<why>)`: anything else, including every block that did not decode `ok`.

     Only `complete` can verify a zero, and only when the PC count for that ID is zero as well.
   - Write `xcheck_<name>_<field>=match` or `differ(target=<a>,pc=<b>)`, and `pc_recount_<name>=<complete|name-only|none(<why>)>`. A difference is reported, never corrected: the host and target traceprinter are different builds.
7. **PC-only analysis** on `<name>.n.txt`. Every figure it produces carries `tcg_shape_only=1`.
   - **Events.** Parse each event into:
     - host cycles (`t:0x…`);
     - CPU, class and subtype;
     - its `key:0x…` argument pairs.
   - **Thread attribution.** Keep `running[cpu]`, the pid and tid of the latest THRUNNING on each CPU. Every QVM event is attributed to `running[cpu]` at its position.
     - The vCPU threads are the threads that emitted CYCLES.
     - The qvm pid is `M4D QPID` if it was printed; otherwise it is the pid those threads share.
   - **Sequence.** Per vCPU thread, count the triples GUEST_ENTER, CYCLES, GUEST_EXIT that appear in that order, and count the events that are out of order.
   - **Offset order.** For each triple, apply [tsc]'s conversion: host equals guest minus offset, with 64-bit wrap and the offset read as signed. Check `t(ENTER) ≤ at_entry − offset ≤ at_exit − offset ≤ t(EXIT)`. Report `offset_order ok=<n> violated=<n>`. This directly tests the conversion M4 would use. Revision 3 takes `t(ENTER)` and `t(EXIT)` from the 64-bit host time, rebuilt per CPU from CONTROL TIME events, never from the 32-bit `t:` word (§13, D-c).
   - **Pairs.** Consecutive complete triples on the same vCPU thread form a pair. Report:
     - `pairs=<n>`, and `pairs_between_markers=<n>` for W2;
     - for each pair, `dwell_guest_cycles = at_entry(next) − at_exit(this)`;
     - the count of negative values;
     - the minimum, P50, P99 and maximum, in cycles and in ns (using `cps` from `CLK HDR`).
   - **Preemption inside a dwell.** For each pair, whether another thread's THRUNNING appears on that CPU between the exit and the next entry. Report `dwell_preempted=<n>`.
   - **Fallback characterisation** (§1.5). Per vCPU tid:
     - the THRUNNING count;
     - running cycles, from each THRUNNING to the next THREAD-class event for that tid, or to another thread's THRUNNING on the same CPU;
     - INTERRUPT events on that CPU while the tid runs (subtypes matching `INT_ENTR|INT_EXIT|INTERRUPT`). Revision 3 matches the INTERRUPT class and reports each subtype, because attempt 1's only subtype, `INT_DELIVER`, missed the pattern (§13, D-d).

     Result: `fallback=characterised`, `partial(no-extraction)` or `impossible(<reason>)`.
   - **Transport shape.** `flt_bytes_per_pair`, from W2's corrected-filter bytes and W2's pairs; and `flt_bytes_per_s`, over the span between the W2 markers.
   - **Ring.** `ring=held`, `wrapped` or `unknown` from the W2 markers (§3.2), forced to `unknown` when the probe's file was non-empty and its marker absent (D8). The target's `M4D MARKERS` line is used first, the PC listing otherwise.
8. **Clock.**
   - **Which run a `CLK` line belongs to:** `pre` after `M4D STATE clock_pre`, `load` after `M4D CLKLOAD`, and `post` after `M4D STATE clock_post`. `CLK` lines after `M4D STATE summary` are not assigned; the summary's `M4D CLKSUM run=` lines are compared with the recomputed verdicts instead.
   - **Recompute** `err_ns`, `tol_ns`, `tolres_ns` and each verdict from the `CLK S` fields, per run. The tool's own verdict is never trusted; a disagreement is flagged as `clkcmp_selfcheck=differs`.
   - **The `load` run** is reported beside the other two, with `done_at_w1_stop=` from `M4D CLKLOAD`. If it never ran, `clock_load=not-run`.
   - **External reference.** Target seconds from `CLK EXT end`'s `dmono_ns`, PC seconds from the launcher's two MARK lines. Printed as `clock_ext=<ratio> resolution_ms=<2 × PollMs>` and labelled coarse.
9. **Verdict,** per §1.2 and §1.3, in one line:
   ```
   M4D-PC VERDICT7B=<PASS|PASS(pc-only)|PARTIAL|PARTIAL(unverified)|FAIL|FAIL(unverified)|INCONCLUSIVE> fields=<...> pc_recount=<w1:...,w2:...> ring=<...> probe=<path,reason> stop_w2=<...> ontarget_counter=<ok|suspect(format)|suspect(classify)|timeout> clock_pre=<...> clock_load=<...> clock_post=<...> clock_ext=<...> ipc=<ok|failed|skipped> fallback=<...> trace_set=<...> variant=<...> qemu=<version line>
   ```
   `ontarget_counter` is:
   - `suspect(format)` when `unformatted_lines` exceeds `events`, when `events` is zero, or when every event classified 7 failed the payload check while the PC recount passes;
   - `suspect(classify)` per §5.4's rule on `M4D QVMBY`. Revision 3 replaces it with `suspect(xcheck)`: some per-ID count on the target differs from a complete PC recount of that window (§13, D-a);
   - `timeout` when any counter pass was killed (`killed=1`).

   A `FAIL(unverified)` or `PARTIAL(unverified)` verdict is followed by `M4D-PC ACTION inspect-hist-then-rerun windows=<names>`, naming the windows that have no complete PC recount (§1.2).
10. **Output.**
    - Every result is a `M4D-PC key=value` line in `out/attempt<N>-parse.log`, headed by the sha256 of the parser itself and of each input file.
    - It never writes `.csv` or `.txt` into `out/`: neither extension is git-ignored.
    - It never writes to `results/hw/`: the dry run produces no CSV for `diff-results.sh`.
    - Exit 0 when parsing completed, whatever the verdict; exit 1 on an input error.

---

## 6. Output, and extracting the raw `.kev`

### 6.1 Where everything goes

| File | Location | Holds figures | Tracked |
|---|---|---|---|
| `attempt<N>-build.log` | `out/` | yes | no (`*.log`, .gitignore:57) |
| `attempt<N>-launch.log` | `out/` | yes | no |
| `attempt<N>-serial.log`: the serial log with base64 elided | `out/` | yes | no |
| `attempt<N>-parse.log` | `out/` | yes | no |
| `serial-raw.log`, `w1.kev`, `w2.kev`, `w1.txt`, `w1.n.txt`, `w1.p.txt`, `w2.txt`, `w2.n.txt`, `w2.p.txt`, `w2.flt`, `parser-stdout.log`, `parser-stderr.log` | `run/attempt<N>/` | yes | no (`/qhv/`, .gitignore:16) |
| `build-<variant>.log`, the variant image, `stage-<variant>/` | `run/` | yes | no |

- **Attempt numbers.** `<N>` increases by one per launch and is never reused; a failed attempt keeps its number.
- **No CSV.** The dry run writes no `.csv` or `.txt` file anywhere under `results/`, and nothing under `results/hw/`.

### 6.2 Decision: extract the raw `.kev`

**What.** The `.kev` goes out over the serial console, gzip'd and base64'd:
- after qvm has stopped;
- capped at 16 MiB of gzip per window;
- W2 first, as the workload window, then W1;
- md5-checked on the PC, and decoded into `run/attempt<N>/`.

**Why.**
1. **The verdict must not rest on an untested on-target filter** (D1). A second, independent parse with the SDP's host `traceprinter.exe` turns "zero matches" into either true absence or a filter defect, which is `PASS (pc-only)`. Without it a zero stays unverified, and a FAIL becomes `FAIL (unverified)`, which triggers none of the plan's fail actions (§1.2).
2. **Some analysis needs the full event stream, including THREAD events:** thread attribution, the offset-order check, pairing and the fallback characterisation. Doing that on the target is slow under TCG, and the board image has no gawk (§8).
3. **Iteration without reboots.** A new analysis runs on the saved `.kev` instead of costing another boot.
4. **The channel adds nothing new.**
   - No device and no launch-line change.
   - toybox `gzip` and `base64` are in the image (qhvh/system.build:153, :121).
   - md5 catches transfer errors.
   - The dump starts only after qvm has stopped, so guest output cannot interleave with it. That matters because the guest's pl011 is bound to the host console (`hostdev >-`, qhvh/post_startup.sh:50).

**Alternatives rejected.**
- **A second raw QEMU drive kept under `/qhv/`.**
  - The launch line's `-snapshot` covers every drive. Keeping one drive writable would need per-drive snapshot options, whose interaction with the global flag is UNKNOWN here.
  - The host would also need a second `devb-virtio` at a virtio-mmio slot nobody has checked; the image binds its devices by fixed address (qhvh/startup.sh:26, :39).
- **The network: slirp, plus `curl` to a listener on the PC.** It depends on host `io-sock` and DHCP coming up, and on a PC-side server. That is more moving parts than the answer is worth.

**Costs.**
- **Console time.** Unknown under TCG. It is bounded by the caps, the guard and the wall bound.
- **Order.** The dump comes last, so a kill in mid-dump loses only the dump. That costs the verification of any zero count (§1.2), not the target counts themselves.

**Licence.**
- The `.kev` is our own evaluation output, and it stays under `/qhv/`.
- `traceprinter.exe` is an SDP host tool, used for its documented purpose.
- Nothing is disassembled.
- The elided serial copy in `out/` carries no trace bytes.

**Board.** The board never does this. M4 sends only the filtered listing (plan:400-401).

---

## 7. What the dry run cannot show

1. **No M4 number.** TCG emulates the CPU, EL2, the GIC and the timers, so exits happen where the emulator traps, not where Cortex-A78AE silicon would. Every dwell, rate, pair count and exit mix from this run is therefore emulated:
   - it is not an M4 number;
   - it is not a prediction for the board;
   - it never goes into the `diff-results.sh` schema.
2. **Not the board's counter.** The TCG host's `cycles_per_sec` differs from the board's (K11). The clock check is self-consistency on an emulated counter (§1.4).
3. **Transport, shape only.** The dry run gives filtered bytes per pair and the shape of the listing's size.
   - The board's TCU console path, its per-character cost and its black-box limit are all different.
   - K11's transport estimate is not validated. Only the structure of its input is.
4. **Not the board's exit mix.** Not that the board shows exits in the same proportions, nor that the exits hidden by default (D9) are the same share.
5. **Not a complete trace.**
   - A linear capture can overrun and drop events (VENDOR_CLAIM, the SAT guide's buffer-overrun topic, from the research brief).
   - A ring can overwrite (§3.2).
   - A PASS says the events exist, not that every exit was recorded.
6. **Not the canonical host image** (§4.1), and not an input to the Phase-4 twin diff.
7. **Not tracing overhead on the board.** `procnto-smp-instr` plus `tracelogger` under TCG says nothing about their cost on silicon (plan §7 item 7).
8. **Not the IPC benchmark.** The IPC figures come from a variant image with tracing active. They are not Phase-2 results, and they are not comparable with the cloud-leg CSV.
9. **Out of scope:** the KVM/GICv3 NISV track, a supported QHV platform, NVIDIA DRIVE OS, and any ASIL or isolation property.
10. **Not publishable** before the supervising professor is consulted (NC QDL v7 4.6(i)).

---

## 8. Carry-over to the board M4 image (noted, not implemented now)

1. **Trace files.** `orin-native/startup/make-m3-images.sh:126` lists `tracelogger` and `traceprinter` in `ABSENT_NAMES`. The M4 generator must:
   - take both out of that list;
   - add `tracelogger`, `traceprinter`, `libtracelog.so.1` and `libtraceparser.so.1`, M2's set (m2.build.in:200-203; m2-design.md:421);
   - add `trcctl` and `clkcmp`.
2. **No gawk, no pipes.**
   - The board script rules forbid pipes and command substitution (m3-host.ksh.in:11), and M3's file list has no awk (make-m3-images.sh:120-124).
   - So the §5.4 counter has to become C, or M4 adds gawk plus a pipe-free wrapper. The M4 design decides which.
   - The rules of §5.4 and §5.7 carry over unchanged, both classifications included. This run's `M4D QVMBY` and `M4D HIST` lines show which forms the class, the subtype and `%e` actually take, so the board's counter is written against observed output.
   - **Now observed (attempt 1, VERIFIED; §13.2).** The rules carry over as §13 amends them, with classification by printed name only.
     - The class prints as `QVM`.
     - GUEST_ENTER, GUEST_EXIT, CREATE_VCPU_THREAD and CYCLES print as trace.h's suffixes.
     - The interrupt events print as `INTR_RAISE` and `INTR_LOWER`, the reverse word order of trace.h's `RAISE_INTR` and `LOWER_INTR`. Their mapping to IDs 3 and 4 is HYPOTHESIS.
     - No timer event appeared, so their spelling is UNKNOWN.
     - `%e` is an event sequence index, not the event ID, so no counter may classify by it.
     - `-n` combines with `-p`. THRUNNING prints `pid:` and `tid:`, and the kernel's interrupt events print as `INT_DELIVER`.
     - The target traceprinter probably prints `t:` as the full 64-bit cycle count, while the host build prints its low 32 bits (§13, D-h: HYPOTHESIS until attempt 2's `M4D TPFMT` lines). A PC recount of the board's listing bytes must therefore use the target's format.
3. **TCU transport.**
   - The console callout busy-polls every character (m3-design.md §2 rule 6), and the black box keeps only its first 65,520 B (§2 rule 7).
   - So the filtered listing goes over the live console to COM3, with md5, `cksum` and a line count checked on the PC (plan:400-401). It never goes into the black box.
   - This dry run's FLT block rehearses the check, not the transport time.
4. **The ring recipe is fixed from this run's records:**
   - the `-f` path from `PROBE` and `W2F`;
   - the stop from `STOP w2 by=`;
   - `-k` from `ring=`. If the ring wrapped, M4 sizes `-k` from W2's marker span; the `k64` variant gives a second point.

   The markers carry over to bracket the board's workload.

   **From attempt 1's records (§13.1, §13.3):**
   - **Path, VERIFIED.** `probe-literal`: `-M -f /dev/shmem/<name>` writes the literal path, so the plan's `-f /dev/shmem/t.kev` stands.
   - **Stop, VERIFIED.** `TraceEvent(_NTO_TRACE_STOP)` from a separate process (`trcctl -x`) made tracelogger write the ring and exit, for both the probe and W2 (`by=stop`). SIGINT was never needed.
   - **Size.** At the plan's flags the ring wrapped. It kept only a short tail per CPU, and both IPC markers and every Class-10 event were overwritten (VERIFIED).
     - The use text says `-k` sets the kernel buffers per CPU, and `-S` caps the output file. So `-k`, not `-S`, is expected to size the ring (HYPOTHESIS until `k64` runs).
     - `k512` tests whether a ring can hold the whole IPC window on this host.
     - The board must size `-k` from its own event rate and within its own RAM (§13.3). A size copied from TCG is not enough.
5. **Trace settings.** M4 states its `trace-*` settings (D9). If this run needed `vtwfe`, the board's `g2-m3.conf` needs the same two `set` lines.
6. **Workload length.** M4 needs at least 1,000 exit/entry pairs per run (plan:408-409). TCG pair counts cannot say whether 15 IPC iterations reach that on the board (§7 item 1). The M4 design chooses the workload.
7. **Clock.**
   - The board's `cycles_per_sec` is K11's. PMCCNTR calibration still prints the actual MHz (plan:401).
   - `clkcmp` runs unchanged on the board as the same self-consistency check. There the cross-CPU mode also covers both clusters.
8. **The M4 parser.** Its CSV writer (plan:402-405) builds on §5.7's pairing and offset rules, but only if this run shows `offset_order` holding and `fields=OK`. Attempt 1 shows both, once host time is rebuilt to 64 bits from CONTROL TIME events (§13, D-c). That holds on emulated time only (§7 item 1).

---

## 9. Failure-signature table

Each row is keyed on the last distinctive line in `out/attempt<N>-*.log`.

**Build**

| Observable | Meaning | Next step |
|---|---|---|
| A canonical hash mismatch before the build | The canonical baseline is not the one this design assumes | Stop and tell the owner. Build nothing |
| mkqnximage exits non-zero, mentioning ssh-ident or a prompt | A prompt was needed | One rerun with `--ssh-ident=none`, recorded (§5.5 step 6) |
| `post_startup.sh` does not call `m4dry-host.ksh` | The snippet was not picked up | Compare `output/option_files/` with `local/snippets/`; the canonical tree shows the two can differ. Fix the staging, and build in a new variant directory |
| `data.build` names another guest source | `--guest` did not take effect | Stop. Rebuild in a new directory |
| `guest_copy_pre=MISMATCH`: the guest copy fails the pins before the build (§4.4 step 1) | A stale or damaged `run/guest` from an earlier build | The build stopped before staging. The owner renames `run/guest`, and the next build copies it afresh |
| `run/guest.partial` exists | An earlier copy was interrupted | Refused. The owner renames it, and the next build copies afresh |
| The guest copy's hash changed after the build | mkqnximage wrote into the guest directory | The variant is invalid; record it. The owner renames `run/guest` and the variant directory, and the next build copies afresh. Nothing is refreshed in place |

**Run**

| Observable | Meaning | Next step |
|---|---|---|
| No `M4D STATE config` | The host never reached post_start, or the snippet did not run | Read the serial log for startup errors, against a canonical boot log |
| `not found`, `Could not load library` or `(83)` in `tp0.err` or any later stderr head | A tool or library is missing | Add it to `system_files.custom` and rebuild |
| `M4D FAIL md5_pre_…` | The image does not carry the pinned guest or client | INCONCLUSIVE. Read the build log |
| `STOP p by=stop` with `PROBE path=none` | STOP ended tracelogger, but no file of that name exists anywhere under `/dev/shmem` | Read the printed `find` output and the probe's stderr head before accepting an unusable W2 or an INCONCLUSIVE verdict (D2's runbook rule). W2 decides. Carry to M4 (§8 item 4) |
| `W2F path=… reason=probe-elsewhere` | `-M` put the file somewhere the doc's rule does not predict | W2's file is still found by name. Record the path for M4's recipe (§8 item 4) |
| `STOP p by=kill` | Neither STOP nor SIGINT ended the ring | The ring recipe is unproven. W1 still gives the verdict |
| `TRCCTL stop rc=-1 errno=<e>` | The control call was refused | Record errno. The ladder falls through to SIGINT |
| `M4D FAIL disk_dev` | devb-loopback did not create `/dev/qvmdisk0` | Check the guest disk path, as on the canonical host |
| `M4D FAIL qvm_exited_early` with `rc=` | qvm failed to arm or run | Read qvm's console text against the canonical run; the printed `g2.conf` shows what qvm read |
| No `QNX qnx-guest` while qvm stays alive | Guest boot is slow under tracing, or failed | Check `ipc_after_guest_ready`. If needed, build a variant with a larger `-Grace` |
| The client's BWAIT shows `killed=1`, or `unrecoverable stall` | The Phase-2 stall hazard | `ipc=failed`. W2 still holds the tail; rerun only if ring sizing needs a full window |
| `KEVFILE w1 path=none` | W1's capture failed | Read `w1.err`. INCONCLUSIVE if W2 is unusable too |
| Empty `lines=` or `bytes=`, or `killed=1` on a counter pass | A traceprinter pass exceeded 300 s | The PC recount decides. Raise the bound in a later variant only if extraction also failed |
| `unformatted_lines` above `events` | `-n` and `-p` do not combine | `ontarget_counter=suspect(format)`; the PC recount decides |
| `M4D QVMBY` with `conflict` above zero, or name and number columns that disagree about ID 0, 1 or 7 | The two classifications disagree | `ontarget_counter=suspect(classify)`; the PC recount decides. Record the printed forms for M4's counter (§8 item 2) |
| Revision 3: `ontarget_counter=suspect(xcheck)` | A per-ID count on the target differs from the complete PC recount | The PC recount decides. Read `M4D QVMOTHER`, `M4D HIST` and `M4D SAMPLE` for the printed forms, and fix the counter's name table in the awk and the parser together (§8 item 2) |
| Revision 3: an `M4D QVMOTHER` line, or `pc_qvm_other_names_<w>` other than `none` | A QVM subtype the name table does not know | Add the name to both tables. Its ID mapping stays HYPOTHESIS until a source names it |
| Revision 3: `M4D REAP <w> <pass> left=` other than `none` | A pipeline stage outlived its bounded pass and was killed (D-f) | Recorded. Read that pass's stderr head; raise its bound in a later variant only if its output is also empty |
| `KEV SKIP … reason=over-cap` | The `.kev` is too big to send | Counts above zero still stand on the target's counts; a zero is unverified (§1.2). For the PC recount, build a variant with a smaller `-W1Secs`, and rerun |
| `kev_<w>=md5-mismatch` or `truncated` | The transfer was damaged, or killed mid-dump | Counts above zero still stand on the target's counts; a zero is unverified (§1.2). Check the launcher's `how=`, and rerun for the PC recount |
| `VERDICT7B=FAIL(unverified)` or `PARTIAL(unverified)` | A zero rests on the untested on-target counter | Take none of the plan's fail actions, and relabel nothing. Read the named windows' complete `M4D HIST` (`hist_printed` equal to `hist_keys`), `M4D QVMBY`, `M4D SAMPLE` and `M4D DISAGREE` lines (revision 3: `M4D QVMOTHER` and `M4D SAMPLE`) for anything that could be Class 10. Then rerun with the extraction working. If it cannot be made to work, the owner decides (O6) |
| `clock_load=unusable` | Brackets were preempted or migrated under load (R31) | Recorded, not a failure. `pre` and `post` still carry the check |
| `BWAIT guard deadline` or `QEMU_STOPPED how=wall-kill` | A bound upstream failed | The last `M4D STATE` line names the state |
| `canonical_post=CHANGED` | Something wrote to the canonical images | Stop everything and tell the owner |
| `PARSER_STOPPED how=timeout-kill` | The parser, or a host traceprinter pass under it, hung | No verdict. The inputs stay under `run/attempt<N>/`; rerun the parser by hand under the same bound |
| `alive_after=yes` on `QEMU_STOPPED` or `PARSER_STOPPED` | A process survived `Stop-Process` | Kill it by the recorded PID, record that, and tell the owner. Revision 3 decides `alive_after` only after a bounded re-check (`gone_wait_ms=`, §13, D-e). Attempt 1's `alive_after=yes` came before that fix, and its `survivors=none` stands |

---

## 10. Risks: every HYPOTHESIS, VENDOR_CLAIM or UNKNOWN the design rests on

| # | Assumption | Class | Answered by |
|---|---|---|---|
| R1 | mkqnximage builds from a copied `local/` with only the snippets and `OPT_GUEST` changed, without `--force` | HYPOTHESIS | Build steps 6-7 |
| R2 | mkqnximage does not write into the `--guest` directory | HYPOTHESIS | §4.4 step 3, every build |
| R3 | `system_files.custom` lines with absolute sources land under `/system` | HYPOTHESIS. The same form is VERIFIED for data files (qhvh/data.build:82) | Build step 7; the S1 start check |
| R4 | traceprinter starts with only libtraceparser added, libtracelog already being present | HYPOTHESIS. The four-file set is VERIFIED on the board (m2-runs.md R5) | S1 `tp0.err` |
| R5 | `-M` places `-f` under `/dev/shmem` | VENDOR_CLAIM ([tracelogger]) | `PROBE path=` |
| R6 | `TraceEvent(_NTO_TRACE_STOP)` from another process makes a ring tracelogger write and exit | VENDOR_CLAIM ([tracelogger]) | `STOP p by=stop` with a non-empty probe file |
| R7 | A background tracelogger has SIGINT ignored | HYPOTHESIS | Only if STOP fails: `by=sigint` or `by=kill` |
| R8 | `-s` timed mode ends W1 by itself | VENDOR_CLAIM ([use-tl]) | `STOP w1 by=self` |
| R9 | The class prints as `QVM` and the subtypes as trace.h's suffixes | HYPOTHESIS ([tsc]'s sample). No longer load-bearing on its own: the numeric classification backs it (§5.4) | `M4D HIST`; `M4D QVMBY` |
| R10 | `-n` and `-p` combine | HYPOTHESIS | `unformatted_lines`; the PC recount |
| R11 | THRUNNING lines print `pid:` and `tid:` | HYPOTHESIS ([sat-events] payload names) | `M4D SAMPLE` |
| R12 | tracelogger's default class set includes Class 10 | VENDOR_CLAIM: [tracelogger] enables all classes unless `-F`; [use-tl] lists `-F 8` for the hypervisor class | The verdict |
| R13 | An idle guest's WFI exits are visible at the default settings | HYPOTHESIS | W2's tail |
| R14 | 150 s of grace is enough for the echo server under tracing | HYPOTHESIS | `ipc_after_guest_ready` |
| R15 | `W1_SECS = 60` covers the banner | HYPOTHESIS | `w1_covers_banner` (recorded, not gated) |
| R16 | Host RAM holds W1, W2, the listing and a gzip copy once the guest has stopped | HYPOTHESIS | `M4D MEM` lines |
| R17 | toybox `gzip`, `base64`, `md5sum`, `cksum` and `wc -l -c` behave as standard | VENDOR_CLAIM (applets listed, qhvh/system.build:121-204) | Decode md5; FLT cksum |
| R18 | The console delivers the dump intact, and nothing interleaves after qvm stops | HYPOTHESIS | md5 on decode |
| R19 | `shutdown -S reboot` makes QEMU exit under `-no-reboot` | VENDOR_CLAIM (QEMU's `-no-reboot`) | `QEMU_STOPPED how=exited` |
| R20 | The guard's `sysmgr_reboot` ends QEMU on TCG | HYPOTHESIS | Only on expiry; the wall bound stands behind it |
| R21 | `pidin -p qvm -f a` prints a bare pid line | HYPOTHESIS | `M4D QPID` |
| R22 | QNX ksh supports every construct used: `$(…)`, `${x:+…}`, `case` on variable patterns, `for` over a command substitution, `while read`, `continue`, functions, `( … ) &` | HYPOTHESIS | S1-S4 output; the `CLKSUM` lines |
| R23 | `ClockCycles()` and `CLOCK_MONOTONIC` share a time base, so agreement is expected | VENDOR_CLAIM ([clockcycles]) | The clock verdicts; a disagreement is itself a finding |
| R24 | The runmask holds for a whole bracket | HYPOTHESIS | The `why=migrated` count |
| R25 | `clockcycles_offset`, `at_entry` and `at_exit` are named the same in every source | VENDOR_CLAIM (three pages) | `M4D QVMFIELDS` |
| R26 | The host `traceprinter.exe` parses a target `.kev` | HYPOTHESIS | `xcheck_*` |
| R27 | `-snapshot` leaves the variant image unchanged across attempts | VERIFIED for the canonical series (launch-qhv-tcg.ps1:152; results/qhv-images-SHA256SUMS.txt) | `M4DRY-SHA256SUMS` after each launch |
| R28 | mkqnximage with stdin from `NUL` does not wait forever | HYPOTHESIS | The 1800 s kill |
| R29 | `%e` prints a Class-10 event's number, bare (0-7) or class-coded, in decimal or `0x` hex | HYPOTHESIS. [use-tp]'s example prints a SYSTEM event's `%e` as a small decimal (VENDOR_CLAIM); the header layout is VERIFIED (trace.h:237-239, :370) | `M4D QVMBY`; `M4D DISAGREE`; `M4D HIST` |
| R30 | The User string markers are captured at the plan's flags | VENDOR_CLAIM ([tracelogger]: every class but Security by default). The User and Security class constants are VERIFIED (trace.h:366, :369) | `PROBE … marker=`; the markers' `M4D HIST` key |
| R31 | `clkcmp` gets usable brackets while tracelogger and qvm load the host | HYPOTHESIS | `clock_load`; `unusable` is recorded, not a failure |
| R32 | Stopping the parser and its listed descendants leaves no `python` or `traceprinter.exe` running | HYPOTHESIS | `PARSER_STOPPED … alive_after=`; §5.6 step 11 |
| R33 | `find /dev/shmem -name` lists the shared-memory objects `-M` creates | HYPOTHESIS | S4's `find` print against `PROBE path=` |
| R34 | The image's gawk provides `and()` and `strtonum()` | HYPOTHESIS: both are gawk extensions, and the image carries gawk (qhvh/system.build:83), version not read | `M4D QVMBY` present; the counter's stderr head |

---

## 11. Owner decisions (the recommendation is adopted unless the owner says otherwise)

| # | Decision | Options | Recommendation and reason |
|---|---|---|---|
| O1 | Image | (a) a variant image; (b) the canonical image, driven interactively | **(a)** (§4.1). Accepting it means 7b runs inside a rebuilt Windows-TCG QHV host image carrying the byte-identical guest, not "the existing image" (plan:550) |
| O2 | Raw `.kev` extraction | (a) gzip plus base64 over serial, into `/qhv/`; (b) none | **(a)** (§6.2). Please confirm that encoding our own trace for transfer, and parsing it with the SDP's host traceprinter, fits the licence stance. No QNX binary is inspected |
| O3 | `trace-*` settings | (a) defaults, and `vtwfe` only after a PARTIAL or FAIL; (b) both variants up front | **(a).** 7b's question is the default behaviour; (b) doubles the build and run cost for a question that may not arise |
| O4 | QEMU build | (a) the launcher's default, stamped; (b) the official 11.1.0 | **(a).** No timing is a result of this run |
| O5 | ssh-ident fallback | (a) one rerun with `--ssh-ident=none`, recorded; (b) stop and ask | **(a).** The dry run never uses ssh |
| O6 | A zero the PC recount cannot verify (`FAIL (unverified)`, `PARTIAL (unverified)`) | (a) no plan fail action: inspect the complete histogram, rerun with the extraction working, and only if it cannot be made to work does the owner decide, after reading the histogram; (b) accept the on-target counter's zero | **(a)** (§1.2). The fail action relabels every M4 number, and a transport problem should not be able to trigger it |

---

## Appendix A. Stale text to correct later (list only; the orchestrator edits other documents)

- **plan:394-395, the M4 recipe.** Add the grep pattern and `-M` path corrections (D1, D2), and the stop method (D3), once the run has its results.
- **plan:550, checklist 7b.** "inside the existing Windows-TCG QHV host image" should become the variant image (D5, O1).
- **plan:94, K11.**
  - The Class-10 ID numbering is VERIFIED in `sys/trace.h:286-293`, independently of the docs.
  - `ClockCycles()` reading `cntvct_el0` is VERIFIED at source level (`aarch64/neutrino.h:79`).
  - The emission status changes only after the run.
- **plan:408, the M4 pass line.** Say which window counts, and that the payload checks (`fields=`) are a separate verdict.
- **plan:409, the M4 fail line.** Say that a fail needs zero counts verified by an independent parse of the trace, and that an unverified zero triggers a rerun, not the fallback (§1.2, O6).
- **`orin-native/startup/make-m3-images.sh:126`.** `ABSENT_NAMES` for the M4 image (§8 item 1).
- **CLAUDE.md, Phase 3b, "blocked on dry run 7b".** Update once the run lands.

---

## 12. Review outcomes

Two reviews of revision 1 returned nine issues: two major and four minor from the first, and one major and two minor from the second. Neither raised a blocker. Every issue is applied, and none is rejected. Where the fix differs from the one a reviewer suggested, the last column gives the reason.

| # | Review | Severity | Issue | Outcome | Where, and why it differs |
|---|---|---|---|---|---|
| 1 | 1 | major | FAIL put "no extraction" in the same bucket as "the PC recount agrees", so a transport failure plus a bug in the untested counter could trigger the plan's costly fail action | **Applied** | §1.2 now separates verified zeros from unverified ones. `FAIL (unverified)` triggers no fail action; someone inspects the complete histogram, and the run is repeated with the extraction working. Also §0, §1.6, §5.7 steps 6 and 9, §6.2, §9, O6 and Appendix A. **Extended** to PARTIAL, whose §1.6 actions rest on zeros in the same way |
| 2 | 1 | major | The counter parsed `%e` but classified by subtype name alone, so a spelling mismatch could manufacture a false PARTIAL or FAIL | **Applied** | §5.4: each event is classified by name and by number. `M4D QVMBY` and `M4D DISAGREE` report both, payload checks follow the classification, and `suspect(classify)` flags a disagreement. The PC recount runs the same format (§5.7 step 6). New risks R29 and R34. **Differs:** the review assumed `%e` prints the raw 0-7 code, which no source confirms. [use-tp]'s own example fits the within-class number, so the counter accepts both that and the class-coded form (trace.h:237-239) |
| 3 | 1 | minor | `offsets_distinct` was keyed on the raw hex string | **Applied** | §5.4: offsets are lower-cased and stripped of leading zeros first. §1.3 says so |
| 4 | 1 | minor | D8 justified capturing the markers with a permission claim, and never stated their class | **Applied** | D8 now states the User class (trace.h:366), apart from Security (:369). [use-tl]'s `-F` list has no User entry. Every run checks capture through `PROBE marker=` and `M4D HIST`, and `ring=` is forced to `unknown` when capture is unproven (§3.2, R30). **Not taken:** the alternative of adding `-a`. It would change the plan's flags and put Security events into both windows, for a question the probe already answers |
| 5 | 1 | minor | `clkcmp` never ran while tracelogger and qvm were loading the host | **Applied** | A third run, `load` (§1.4, S7a, S8, §5.3, §5.7 step 8, §9, R31). **Differs:** it runs in W1, not W2. W1 meets the review's condition: tracelogger is logging and qvm is starting the guest, under the run's heaviest load. W2 sizes M4's ring (§8 item 4) and brackets the plan's workload, so it stays free of our own events. The guard and the wall bound each rose by the added wait |
| 6 | 1 | minor | The probe's path selection knew only two landing places | **Applied** | `kevpath` also searches `/dev/shmem` by name, with a new `probe-elsewhere` reason (D2, §5.3, R33). D2 and §9 now carry the runbook rule: read the `find` output before accepting `path=none` |
| 7 | 2 | major | The parser ran unbounded, with no PID and no way to stop it | **Applied** | §5.6 step 10: `Start-Process`, the PID logged, a `-ParserSeconds` bound, `try`/`finally`, descendants listed recursively and stopped, and a `PARSER_STOPPED` line. Step 11 checks all of them; §9 and R32 cover the failure. **Differs in one bound:** each host traceprinter pass drops from 900 s to 300 s. The cross-check now runs three passes per block, and the outer bound must stay above the sum of the inner ones |
| 8 | 2 | minor | A stale `run/guest` made the build skip the copy, and a pre-build hash mismatch had no action | **Applied** | §4.4 steps 1 and 3, §5.5 step 3: a mismatch stops the build before staging. The copy goes through `run/guest.partial` and a rename. Two new §9 rows. **Differs:** the build refuses rather than refreshing automatically. Refreshing would overwrite a copy in place, and this design leaves every rename or removal to the owner (§4.3 step 1) |
| 9 | 2 | minor | Two `.gitattributes` line citations were off by one | **Applied** | §5 now cites :12 for the default LF rule and :18 for `.ps1`, and adds :31 for `.c`, which has its own rule |

---

## 13. Attempt 1 outcome and fixes

**Revision 3, 2026-09-11.**

**The run.** Attempt 1 ran the `plan` variant, built from the tooling committed at 3dbf0e3.
- **Records:** `out/attempt1-{build,launch,serial,parse,verify,canonical-recheck}.log`. The verify log is an independent recount by a scratch verifier.
- **Re-parse:** the fixed parser, run on attempt 1's unchanged inputs, wrote `out/attempt1-reparse.log` (§13.4).
- **Figures:** every one stays in those logs and under `run/`. This section carries none.

**More use texts** (printed with `sdphost/use.exe`, VERIFIED as text): [use-slay] is `sdp/bin/slay`. [use-tl] and [use-tp] are re-read for §13.2 and §13.3.

### 13.1 Outcome

| # | Outcome | Evidence |
|---|---|---|
| Q1 | **VERIFIED.** On SDP 8.0's qvm under this TCG host, GUEST_ENTER (0), GUEST_EXIT (1) and CYCLES (7) are emitted, at the default qvm trace settings and tracelogger's default classes. W1 holds them; W2 holds none (§13.3). CREATE_VCPU_THREAD (2) and the two interrupt events appear too | `VERDICT7B=PASS fields=OK` in `attempt1-parse.log` and `attempt1-reparse.log`, both PC recounts `complete`; `attempt1-verify.log` |
| Q2 | VERIFIED: the CYCLES events carry non-zero `at_entry` and `at_exit` | `fields_w1`; `xcheck_w1_cycles_both_nonzero=match` |
| Q3 | VERIFIED: GUEST_EXIT carries `clockcycles_offset`, with one distinct value for the qvm instance | `fields_w1`; `xcheck_w1_offsets_distinct=match` |
| Q3, the conversion | VERIFIED, on emulated time only. With host time rebuilt to 64 bits, `t(ENTER) ≤ at_entry − offset ≤ at_exit − offset ≤ t(EXIT)` holds for every complete triple, with none violated and none missing. The attempt-1 parse reported every triple violated; that was defect D-c, not qvm | `offset_order_w1` in the re-parse; the verify log's per-CPU check agrees |
| Q4 | The plan's literal filter matched exactly the QVM header lines, the same lines as the corrected filter, on the target and on the PC. `Class 10` never matched. Without `-n` the payload is on separate lines that neither pattern matches (D1 held) | `PLANFILTER`, `CORRFILTER`; `xcheck_w1_*filter_lines=match` |
| Q5 | `agree` in all three modes, in each of the `pre`, `load` and `post` runs. The external reference is coarse and recorded | `clock_pre`, `clock_load`, `clock_post`, `clkcmp_selfcheck=ok`, `clock_ext` |
| Q6 | `fallback=characterised` in both windows. The INTERRUPT counts inside the vCPU thread's running intervals appear only after D-d's fix | `fallback_w1_*`, `fallback_w2_*`, `intr_subtypes_*` in the re-parse |
| Q7 | Path: `probe-literal`. Stop: `TraceEvent(_NTO_TRACE_STOP)` from `trcctl`, for the probe and for W2. Ring: overwritten at the plan's flags (§13.3). The parser printed `ring=unknown`, because §3.2's marker rule needs at least `m4d-ipc-end`, and that marker was overwritten too | `PROBE`, `W2F`, `STOP p by=stop`, `STOP w2 by=stop`; `ring_w2_kept` and `buffers_w2_cpu<N>` in the re-parse |
| Q8 | Not reached: W2 held no Class-10 event, so there was no filtered listing to size | `FLT SKIP`; `flt_bytes_per_pair=n/a` |

### 13.2 Defects, and what changed

Each defect was VERIFIED by the run agent and by an independent verifier. None changed the verdict.

| # | What attempt 1 showed | Fix (files) |
|---|---|---|
| D-a | `%e` in a `-p` format prints an event sequence index, one higher for each printed event, not the event ID (VERIFIED, `run/attempt1/w1.p.txt`). The numeric reading failed for most events and produced a false hit: an `INTR_LOWER` event counted as ID 2 (`M4D SAMPLE w1 id2`). It also made every `M4D HIST` key unique, so the histogram hit its cap and was useless | `%e` is dropped from every `-p` format: the host template, the counter's header and the parser's `P_FORMAT`. Events are classified by printed class and subtype name only. `M4D HIST` is keyed by class and subtype, so it is small and complete. `M4D QVMBY` and `M4D DISAGREE` are removed. `ontarget_counter=suspect(classify)` becomes `suspect(xcheck)`, meaning any per-ID count differs from a complete PC recount. The re-parse flags attempt 1's own counter this way, as it should (`m4dry-count.awk`, `m4dry-host.ksh.in`, `parse-m4dry.py`) |
| D-b | The interrupt events printed as `INTR_RAISE` and `INTR_LOWER`. trace.h:289-290 names them `RAISE_INTR` and `LOWER_INTR`, so they fell into `qvm_other` unnamed. No timer event appeared at the defaults, so how IDs 5 and 6 print is UNKNOWN | Both interrupt spellings map to IDs 3 and 4 (the mapping is HYPOTHESIS, labelled in both files), and both word orders are accepted for the timer events. Unrecognised QVM subtypes are listed by name and count, as `M4D QVMOTHER` on the target and `pc_qvm_other_names_<w>` on the PC, never hidden in `qvm_other` (`m4dry-count.awk`, `parse-m4dry.py`, kept in lockstep) |
| D-c | `offset_order` and `running_cycles` compared traceprinter's 32-bit `t:` word with 64-bit payload values, so every triple looked violated. Rebuilding host time from the CONTROL TIME events' `msb:` makes the conversion hold (VERIFIED, verify log and re-parse) | The parser rebuilds 64-bit host cycles per CPU from each CONTROL TIME event's `msb:`. A low word that drops by more than half its range between two events on one CPU also counts as a wrap, as a safety net. Offset order, running cycles, marker spans and the ring span all use the rebuilt time. `time64_<w>` reports the TIME events, inferred wraps, backsteps and events seen before a CPU's first TIME event. No `-p` token helps on the PC: [use-tp] lists `%c` as the 64-bit cycle count, but the host `traceprinter.exe` prints only the low 32 bits, even under `%016c` (VERIFIED on this PC against attempt 1's `w2.kev`; that listing stays under `run/`) |
| D-d | The parser's INTERRUPT pattern (`INT_ENTR\|INT_EXIT\|INTERRUPT`, matched against the subtype) missed `INT_DELIVER`, the only subtype that appeared, so every fallback line said no interrupts | Interrupts are matched by class. `intr_subtypes_<w>` gives the window's counts per subtype, and each fallback line gives `intr` plus `intr_subtypes` for its tid. `intr_class_or_subtype` is removed (`parse-m4dry.py`) |
| D-e | The launcher logged `alive_after=yes` straight after QEMU had exited. `Test-Alive` only asked whether the PID was still listed, and an exiting process can stay listed briefly. The later `survivors=none` was authoritative | `Test-Alive` treats an exited process as not alive. `Wait-Gone` re-checks for up to 15 s, and `QEMU_STOPPED` now carries `alive_after=` with `gone_wait_ms=`. The parser's stop uses the same re-check. `survivors=` stays authoritative (`launch-m4dry-tcg.ps1`) |
| D-f | In `process()`, each pipeline ran under `bwait -k 300` through a nested `ksh -c`. bwait's SIGKILL reaches only that ksh, so a hung `gawk`, `grep`, `wc` or `traceprinter` would have survived its bound | `reap <w> <pass>` runs after each of the three passes. It sends SIGKILL by name, with `slay -f -Q -s KILL`, to `traceprinter`, `gawk`, `grep`, `wc` and `toybox`, and prints `M4D REAP <w> <pass> left=<name:count,…\|none>` from slay's exit status, the number of processes slain [use-slay]. `toybox` covers an applet that runs under the toybox name (HYPOTHESIS: which name slay matches for a hard link). Nothing else runs these programs during `process()`. `bwait.c` is unchanged. The parser reports `reap_<w>` (`m4dry-host.ksh.in`, `parse-m4dry.py`) |
| D-g | **Not a defect.** The `echo_up` marker, `server: echo endpoint up`, did match in attempt 1: the serial log has the line and the launch log has `MARK echo_up`. The guest's echo server prints it for `/dev/vcon2` (ipc-test/qnx-server/server.c:61), the endpoint the client reaches through `/dev/ttyp0`, and M3 stamps the same line (m3-host.ksh.in:97). It is half of `ipc_after_guest_ready` | Kept. The launcher and the parser now say in a comment where the line comes from and which check uses it |
| D-h | The target's byte counts for both filters exceed the PC's by the same amount, while the line counts match | **Finding: HYPOTHESIS, exact to the byte.** Recompute the PC's byte count for each filter as if `t:` printed the whole 64-bit host time at `%08` minimum width. Both counts then equal the target's (`xcheck_w1_{plan,corr}filter_bytes_if_t64=match` in the re-parse). That fits the default format `t:0x%08c` and [use-tp]'s `%c`, the 64-bit cycle count: the target build prints the whole value, and the host build its low 32 bits, which is VERIFIED on the host side. **Direct check from attempt 2:** the probe prints its first few default-format event lines as `M4D TPFMT`, and the parser reports `target_tp_time_field` (`m4dry-host.ksh.in`, `parse-m4dry.py`) |

### 13.3 The ring finding, and the variants that test it

**What attempt 1 showed** (VERIFIED from W2's listing and records):
- W2 ran with exactly the plan's flags, `-r -M -S 8M` with no `-k`. The stop worked, and tracelogger wrote the ring and exited.
- The ring kept only a short tail, a small fraction of tracelogger's own run in W2 (`ring_w2_kept` in the re-parse). Both IPC markers and every Class-10 event were overwritten. The tail kept is shorter than the pause between `m4d-ipc-end` and the stop.
- Per CPU, the file held the number of kernel buffers that `-k`'s documented default predicts, plus one short trailing buffer whose sequence number restarts (`buffers_w2_cpu<N>`).
- The probe's `-S 1M` file and W2's `-S 8M` file came out nearly the same size (`PROBE bytes=`, `KEVFILE w2 bytes=`), so `-S` did not set the ring's size.

**What the documentation says:**
- [use-tl] gives `-k` as the number of buffers allocated in the kernel per CPU, with a default of 8, each of about 16 KB. It gives `-S` as the maximum size of the output file, and says `-M` requires `-S`.
- [tracelogger] says the same for `-k`, and calls `-S` the maximum size of the log file or memory object.
- Neither says how the ring is sized in `-r` mode, or what happens when the ring holds more than `-S`.

**Reading (HYPOTHESIS until `k64` runs).** In ring mode, `-k` sets the ring's size per CPU, and `-S` only caps the output. At the default the ring is `-k` × about 16 KB per CPU, far less than the IPC window's trace on this host.

**The variants** (all tagged `r3` and built from the fixed tooling with `build-m4dry-image.ps1 -Variant <v> -Tag r3`):

| Variant | W2 | Question |
|---|---|---|
| `plan` | `-r -M -S 8M` | Regression of every §13.2 fix on the target, and a second data point for the default ring |
| `k64` | `-r -k 64 -M -S 8M` | (i) Does `-k` set the ring's size in ring mode? Only `-k` changes. The ring, 64 × 2 CPUs × about 16 KB ≈ 2 MB, fits under `8M`, so `-S` cannot cap it |
| `k512` | `-r -k 512 -M -S 32M` | (ii) Does this ring hold the whole IPC window, markers and Class-10 events included? `-S` rises with `-k`, so an undocumented limit at `-S` cannot be what cuts the ring |
| `vtwfe` | as `plan` | Unchanged; only after a PARTIAL or FAIL (O3) |

**Why `k512`, and the memory arithmetic.**
- **Choice.** 512 exceeds, on both CPUs, the buffer sequence numbers W2 had reached when it stopped (`buffers_w2_cpu<N>`, `seq_max`). That reads the sequence as counting the buffers filled since that tracelogger started. It is HYPOTHESIS, supported by W1's buffers and W2's trailing buffer both restarting at 1.
- **TCG host.** The kernel ring is 512 × 2 CPUs (`-smp 2`, the launch line) × about 16 KB ≈ 16 MB, and the `-M` object is at most `32M`, about 48 MB together. The host has `-m 2G`, and its guest takes `ram 0x80000000,512M` (g2.conf). The processing states run after qvm has stopped and released the guest's RAM. They add W1's file (capped by its own `-S 32M`), the listings, and one gzip copy at a time. That fits, and the `M4D MEM` lines record the actual headroom.
- **Board, for M4 only; nothing here builds it.** At M3's `-P4` (m3-design.md O2), the same `-k 512` is 512 × 4 × about 16 KB ≈ 32 MB of kernel buffers. Add an `-M` object at least that large, and the total is 64 MB or more inside `-m992M`, beside the same 512M guest. That is more than half of the headroom m3-design.md §3.5 estimates, and the estimate is itself HYPOTHESIS. So the board's `-k` must come from the board's own event rate, with a `k64`-style point on the board, not from this TCG size.
- **Not built:** a larger TCG point. `k1024` would need about 32 MB of ring plus a `64M` object, past anything the board could reuse. The sequence numbers above do not call for it either.

### 13.4 Re-parse of attempt 1

**The run.**
- Inputs: attempt 1's unchanged `run/attempt1/serial-raw.log` and `out/attempt1-launch.log`.
- Outputs: `--run-dir run/attempt1-reparse`, `--parse-log attempt1-reparse.log` and `--serial-copy none`.
- Nothing attempt 1 wrote changed: `out/attempt1-parse.log`, `out/attempt1-serial.log` and `run/attempt1/` keep their files.

**What it shows** (VERIFIED, lines in the log):
- `VERDICT7B=PASS fields=OK`, as before.
- `offset_order_w1`: ok for every complete triple, with none violated and none missing (D-c).
- `fallback_w1_*` and `fallback_w2_*`: interrupts are now counted, all of them `INT_DELIVER` (D-d).
- `xcheck_w1_{plan,corr}filter_bytes_if_t64=match` (D-h).
- `ontarget_counter=suspect(xcheck)`. It flags attempt 1's revision-2 counter correctly: that counter's ID 2, 3 and 4 counts differ from the PC's, as do its `qvm_other` and `hist_keys` (D-a, D-b).
- `pc_qvm_other_names_w1=none`: every QVM subtype attempt 1 printed is now known.

The re-parse's `input_launch` sha256 differs from the one in attempt 1's parse log. That is expected: the launcher appended its closing lines after its own parser run had read the file. The parser uses only the `MARK`, `poll_ms`, `qemu_version` and `QEMU_STOPPED` lines, and all of them come before those closing lines.

### 13.5 What attempts 2 and later test

**Procedure.** One boot per attempt: `launch-m4dry-tcg.ps1 -Attempt <N> -Variant <v> -Tag r3`. Attempt numbers continue from 2. The order is `plan`, `k64`, `k512`, because each question assumes the one before it holds.

**Attempt 2, `plan`: are the fixes right on the target?**
- `VERDICT7B=PASS`, `fields=OK` and `ontarget_counter=ok`, with every `xcheck_<w>_id<N>` matching.
- No `M4D QVMOTHER` line, or only names that are then added to both tables.
- `hist_printed` equal to `hist_keys`.
- An `M4D REAP` line for every pass. Any `left=` other than `none` is a finding.
- `target_tp_time_field=64bit` makes D-h VERIFIED. `low32-or-msb0` refutes it, and D-h returns to UNKNOWN.
- `QEMU_STOPPED … alive_after=no gone_wait_ms=…`.
- W2 is expected to be overwritten again, as at the default ring in attempt 1.

**Attempt 3, `k64`: question (i).**
- VERIFIED that `-k` sets the ring's size in ring mode if W2's `buffers_w2_cpu<N>` records follow `-k`, and `KEVFILE w2 bytes` grows by roughly the `-k` ratio over attempt 2's.
- Otherwise `-k` does not size the ring here. Then the series stops, and M4 needs a different capture: a linear window, bounded by the markers.

**Attempt 4, `k512`: question (ii).** The ring holds the window when all of these hold:
- `ring=held`;
- `pairs_between_markers_w2` above zero;
- the FLT block present, with `flt=ok`;
- `ring_w2_kept` covering tracelogger's run.

If it is overwritten anyway, the buffer sequence numbers say how far short the ring fell. Any larger point needs §13.3's arithmetic redone first.

**Unchanged:** O1 to O6, the verdict rules of §1.2 and §1.3, W1, the probe and the stop ladder.

### 13.6 Risks attempt 1 settled, and new ones

**Settled** (VERIFIED unless stated):
- R5 (`probe-literal`), R6 (`by=stop`) and R8 (`STOP w1 by=self`). R7 was never exercised, because STOP worked.
- R9: the class and four of the eight names as trace.h spells them. The interrupt names are reversed, and the timer names are unseen.
- R10, R11 and R12.
- R13 is still UNKNOWN. W2's tail held no Class-10 event. Whether an idle guest emits none at the defaults, or only none in so short a tail, is not settled.
- R14, R15, R16 (at the plan's sizes), R17, R18, R19, R21, R22, R26 and R27.
- R29 is **REFUTED**: `%e` is a sequence index.
- R30 holds for the probe (`marker=found`). W2's markers were overwritten.
- R31, R32, R33.
- R34 is moot, because revision 3 no longer uses `and()` or `strtonum()`.

**New:**

| # | Assumption | Class | Answered by |
|---|---|---|---|
| R35 | `INTR_RAISE` and `INTR_LOWER` are IDs 3 and 4 | HYPOTHESIS (the name pairs match with the words reversed) | A source that names the printed form, or `%e`-free class-coded output if one exists |
| R36 | `slay` matches `grep` or `wc` by the name they run under, or under `toybox` | HYPOTHESIS | `M4D REAP` only if a stage ever survives |
| R37 | The BUFFER sequence number counts buffers since that tracelogger started | HYPOTHESIS (W1 and W2's trailing buffer start at 1) | `k64`'s and `k512`'s `buffers_w2_cpu<N>` |
| R38 | A ring larger than `-S` would be cut, not grown or refused | UNKNOWN (no source says) | Not tested: `k512` sizes `-S` above its ring |
| R39 | The target traceprinter prints `t:` as the full 64-bit count | HYPOTHESIS (exact byte match, D-h) | Attempt 2's `target_tp_time_field` |

### 13.7 Attempts 2 to 4, and verification of the fixes

**Outcome.** VERIFIED from the raw serial and parse logs. The figures are only in the git-ignored run logs and the unpublished record.
- **All three attempts** gave `VERDICT7B=PASS fields=OK` with `ontarget_counter=ok`:
  - every per-ID target count equals the PC recount in both windows;
  - there is no `QVMOTHER` line;
  - every `REAP` line says `left=none`.
- **Attempt 2 (`plan`):** W2 wrapped again at the default ring, as expected, and both IPC markers were overwritten.
- **Attempt 3 (`k64`):** the buffers kept per CPU followed `-k` (k plus one trailing buffer), and with `-S` unchanged the file grew by about the `-k` ratio. **Question (i) is answered: `-k` sizes the ring in ring mode** (TCG). The IPC window was still overwritten.
- **Attempt 4 (`k512`):**
  - The ring never filled. Both IPC markers are inside W2 (`ring=held`), with guest entry, exit and CYCLES triples between them.
  - The FLT block arrived with a matching md5.
  - **Question (ii): only this setting kept the window on this host.**
  - R37 is supported: the first kept buffer is sequence 1. R38 stays untested, because the ring stayed below `-S`.
- **R39 / D-h is VERIFIED.** The target traceprinter prints `t:` as the full 64-bit count (`target_tp_time_field=64bit`). Every remaining byte difference reconciles at that width (`_if_t64=match`).
- **Still open:** R35 (the interrupt names as IDs 3 and 4) stays HYPOTHESIS, and IDs 5 and 6 were not seen.
- **Offsets:** `offset_order` holds on every in-sequence triple in both windows, and an independent 64-bit check agrees.

**What it means for M4 (§8 item 4).**
- Do not copy `k512` to the board.
- The ring must hold every buffer from tracelogger's start to its stop, and non-QVM kernel events dominate that count.
- The fixed sleeps around the markers cost buffers too.
- The board sizes `-k` from its own event rate at `-P4`, starting with a `k64`-style point, or it uses a linear window bounded by the markers.

**Verification of the fixes.**
- **Evidence recount: confirmed.** One note: the `CONFIG` line's `plan_w2=` field quotes the plan's text, not the variant's flags. Those are in `w2_k=` and `w2_s=`. The field is kept and noted here.
- **Code review: confirmed with corrections.**
  - *Rejected (major):* "the plain-pass `Clock64` can never see `msb:`". The host traceprinter's plain listing does print `msb:` on its CONTROL TIME lines (attempt 2's `w1.txt` and `w2.txt`), and the `_if_t64` reconciliations matched in attempts 2 to 4.
  - *Known, cosmetic:* the state-summary `grep` in `m4dry-host.ksh.in` still names `QVMBY`, which no longer exists. The same lines reach the log through `process()`, so no record is lost. It is left as run, so the template matches the images built from it.
  - D-a to D-f are fixed in lockstep between the awk counter and the parser. The verdict rules are unchanged, and no identifier leaked.
