# N15: what GUEST_EXIT `status` means on aarch64, and the E3 rule for the freeze

Phase 3b, M4. A research note for owner decision N15, option (c), 2026-09-11. It serves [m4-design.md](m4-design.md) §14.7. It is read-and-reason only: no board contact, no QEMU run, and no change to code, fixtures or the generator.

**Evidence classes:** VERIFIED (read in a header, a source file or a log, or computed on this PC; cited), VENDOR_CLAIM (QNX or Arm documentation), HYPOTHESIS, UNKNOWN.

**Licence and publication.** This file is tracked, so it carries no measured figure and no functional outcome: no count, share, time, trace value or reading of a trace.
- It names a `status` value, an `hw_reason` value or a bit position only where QNX documentation or an SDP header gives it.
- The TCG evidence behind §3 is in `qhv/m4tcg/n15/status-evidence.log`, written by `qhv/m4tcg/n15/n15_status_evidence.py`. Both are git-ignored. The log is evaluation output under NC QDL v7 4.6(i): private until the supervising professor is consulted.
- No QNX-shipped binary was disassembled, dumped or string-searched (4.6(c)).

**Sources**
- QNX documentation, SDP 8.0 unless marked (VENDOR_CLAIM; base `https://www.qnx.com/developers/docs/8.0/`):
  - [TE] `com.qnx.doc.hypervisor.user/topic/debug/trace_events.html`
  - [TSC] `…/debug/tsc.html`; [TSC71] the same page under `https://www.qnx.com/developers/docs/7.1/`
  - [SAT] `com.qnx.doc.sat/topic/kercall_table_Events.html`
  - [TEN] `…/debug/trace_enable.html`
  - [TR] `…/debug/trace.html`; [GX] `…/perform/guest_exits.html`; [GIX] `…/perform/guest_init_exits.html`
  - [VAPI] `com.qnx.doc.hypervisor.vdev.api/topic/guest_h_defines.html` and `…/about_guest_8h.html`
  - [ERR] `…/debug/errcodes.html`
  - [TE], [TSC], [TSC71], [SAT], [TEN], [TR] and [GX] were fetched for this note. [GIX], [VAPI] and [ERR] were read in the same day's documentation pass and not fetched again.
- `inc/` = `C:/Users/<user>/qnx800/target/qnx/usr/include/`, the SDP 8.0 text headers on this PC.
- `m4/` = `orin-native/m4/`; `tools/` = `orin-native/tools/`; `startup/` = `orin-native/startup/`.
- Code is cited by function name. These files have uncommitted edits, so line numbers move.

---

## 1. The question and the owner decision

- **E3** ([m4-design.md](m4-design.md) §1.4) counts a pair only when both GUEST_EXIT events carry `status` 0.
  - Its basis is one sentence in [TSC]: a zero status means the entry succeeded, so the CYCLES values `at_entry` and `at_exit` are meaningful.
  - That basis is VENDOR_CLAIM (m4-design.md §12.2 M13, §12.3 N5).
- **What the TCG rehearsal recorded for `status`** is held locally (m4-design.md §14.2 I4, §14.5 step 5); it is what raised the question.
- **The question.**
  - What does `status` encode on aarch64?
  - Which value, if any, marks an entry whose CYCLES values can be trusted?
  - Which E3 rule should the one measurement campaign use?
- **Owner decision, 2026-09-11** (m4-design.md §14.7):
  - **(b) now.** The functional rungs run with E3 = `none`. Every GUEST_EXIT's `status` is recorded, so the freeze can choose from the board's own values.
  - **(c) in parallel.** Research what the field and its bits mean. This note is that research.
  - **At the freeze** the owner picks the final E3, before the campaign. No functional rung is a measurement.

## 2. What the documentation and headers say

### 2.1 QNX documentation (VENDOR_CLAIM)

- **[TE], event ID 1 (GUEST_EXIT).** The fields are `status`, `reason`, `clockcycles_offset`, `guest_ip` and `hw_payload`. `status`, `reason` and `hw_payload` are each described only as architecture-specific.
- **[TE], x86 only.** A non-zero `status` means the entry was aborted before the guest ran, and `clockcycles_offset` is then stale. [TE] gives no such rule for ARM.
- **[TE], for ARM and x86 alike.** The guest ran only if ID 7 (CYCLES) events appear between ID 0 and ID 1. With no ID 7 event, the guest did not run.
- **[TSC].**
  - Its sample GUEST_EXIT shows `status:0x00000000` and `hw_reason:0x07e00000`.
  - The page says the zero status means the entry succeeded, so `at_entry` and `at_exit` are meaningful.
  - It says nothing about a non-zero status, and it does not name the sample's architecture.
- **[TSC71].** The 7.1 page has the same sample and the same sentence. Which release and host produced the sample is UNKNOWN.
- **[SAT].**
  - The GUEST_EXIT layout is `status(32), hw_reason(32), clockcycles_offset(64), guest_ip(64), payload(64)`.
  - Its note says the *reason* might show that the attempt was aborted. It says nothing of the kind about `status`.
  - GUEST_ENTER's note says the guest might not run if tasks are pending.
  - CYCLES is described as emitted when the guest has run successfully for a period.
- **[TEN].** The `qvm_events.xml` format for GUEST_EXIT is `"%4u1x status %4u1x reason %8u1x cc_offset %8u1x guest_ip %8u1x payload"`. It gives widths, not meanings.
- **No definition of `status` or `reason` was found.**
  - Not in [TR], [GX], [GIX] or [VAPI].
  - [ERR] covers qvm process exit codes, which are a different thing.
  - Two web searches found no other QNX page that defines them.
- **The field names differ by source.** [TE] says `reason` and `hw_payload`. [SAT] and [TSC] say `hw_reason` and `payload`, which is what traceprinter prints (m4-design.md §1.2).

### 2.2 [TSC]'s sample, decoded with QNX's own macros

- **Decode.** With `AARCH64_ESR_EC_SHIFT` and `AARCH64_ESR_IL` (§2.3), `0x07e00000` is exception class `AARCH64_ESR_EC_WFI` with the IL bit set (VERIFIED arithmetic).
- **Likely source.** The value decodes cleanly as an Arm exception syndrome, so the sample probably came from an ARM host (HYPOTHESIS).
- **The question it raises.** If it did, [TSC] shows an ARM WFI exit with `status` 0. Whether SDP 8.0 on aarch64 uses the same encoding is what §3 compares against our own traces (readings held locally).

### 2.3 SDP 8.0 headers (VERIFIED)

- **`inc/sys/trace.h`.**
  - Lines 285-293 give `_NTO_TRACE_QVM_GUEST_ENTER` 0, `_NTO_TRACE_QVM_GUEST_EXIT` 1, and so on up to `_NTO_TRACE_QVM_CYCLES` 7.
  - Line 370 gives `_TRACE_QVM_C`, class 0xa.
  - There is no macro for `status` or `reason`.
- **`inc/aarch64/cpu.h`, ESR macros.**
  - `AARCH64_ESR_EC_SHIFT` is 26 (:148), and the exception-class values are at :150-186.
  - `AARCH64_ESR_IL` is bit 25 (:191).
  - The abort ISS fields `AARCH64_ESR_ABT_*` are at :201-212.
- **The classes this note names:**
  - `AARCH64_ESR_EC_WFI` 0x01 (:151)
  - `AARCH64_ESR_EC_SVC_32` 0x11 (:161)
  - `AARCH64_ESR_EC_SVC_64` 0x15 (:164)
  - `AARCH64_ESR_EC_SYS_64` 0x18 (:167)
  - `AARCH64_ESR_EC_DABT_EL0` 0x24 (:172). The name takes an EL1 kernel's view. Taken at EL2, the same class is a data abort from the guest (HYPOTHESIS). Linux `arch/arm64/include/asm/esr.h` calls it `ESR_ELx_EC_DABT_LOW`; that is a secondary source, not fetched again here.
- **`inc/sys/hyp.h`.**
  - `HCO_FORCE_GUEST_EXIT` (:109) is a control-page operation that forces a guest exit.
  - `init_status` (:152), "0 = success", belongs to the hypervisor init reply, not to exits.
- **Unrelated status codes that are easy to confuse with this one:**
  - `VRS_*`: the vdev read/write return status (`inc/qvm/vdev-core.h:74-88`).
  - `GTC_*`: guest termination causes, which become the qvm exit status (`inc/qvm/guest.h:173-195`).
  - `GIT_ARM_*`: the instruction-trap types for vdev callbacks (`inc/qvm/guest.h:140-146`).
- **Search.** A case-insensitive grep of all of `inc/` for `guest_exit`, `hw_reason` and `exit_reason` matches only `sys/trace.h` and `sys/hyp.h`. No header mentions `ESR_EL2`.

### 2.4 What the sources settle

- **Settled (VENDOR_CLAIM).** On ARM and x86 alike, an entry with no ID 7 event between ID 0 and ID 1 did not run.
- **Not settled (UNKNOWN):**
  - what `status` encodes on aarch64;
  - whether any value means success there;
  - whether [TSC]'s zero-status sentence applies to SDP 8.0 on aarch64.
- Only QNX can settle these. The public documentation does not.

## 3. What our TCG traces show (TCG shape only)

**Scope.** QEMU TCG runs of the QHV host and its guest on this PC, not the board. The inputs:
- the 7b listings `qhv/m4dry/attempt1..4/{w1,w2}.n.txt`, printed by the SDP host traceprinter;
- the M4 TCG rehearsal serial logs `qhv/m4tcg/attempt2..6/serial-raw.log`;
- the counter's verbatim selection `qhv/m4tcg/attempt2/out/tcg-k512-a2-flt-v.txt`.

**Method.** The evidence script imports `m4/parse-m4.py`'s event parser, its time rebuild and its `Listing` class with E3 off, so its triples and pairs are the parser's own.

**Readings.** What the traces show — `status` values against the exception class of `hw_reason`, which classes decode as hardware syndromes and which do not, CYCLES values against `status`, and the pairs — is evaluation output of QNX software under NC QDL v7 4.6(i). It is held locally, in `qhv/m4tcg/n15/status-evidence.log`, until the supervising professor is consulted. Sections 3.1 to 3.5 are kept as headings only, so that references to them stay valid.

### 3.1 Status values and exception classes

Held locally (NC QDL v7 4.6(i)).

### 3.2 Classes that decode as real syndromes

Held locally (NC QDL v7 4.6(i)).

### 3.3 Classes that do not look like hardware syndromes

Held locally (NC QDL v7 4.6(i)).

### 3.4 CYCLES values against `status`

Held locally (NC QDL v7 4.6(i)).

### 3.5 Pairs

- The pair readings under TCG are held locally (NC QDL v7 4.6(i)).
- **Negative dwells.** E4 refuses them as `negative`.
- **A cross-pair chain.** `a ≤ t(EXIT_n) ≤ t(ENTER_n+1) ≤ b`, with `a` and `b` the ends of m4-design.md §1.3's interval.
  - No E rule tests it (VERIFIED by reading `Listing._pairs` and the pair loop in `tools/m4count.c`).
  - Whether a pair that fails it can reach the clean class is UNKNOWN.

### 3.6 What E3 = `none` already refuses (VERIFIED by reading; no fixture covers it)

- **An entry with no CYCLES leaves a fragment.** In both implementations, an EXIT that follows an ENTER with no CYCLES leaves a broken fragment at that ENTER's time.
  - In `m4/parse-m4.py`: `Listing._event` and `Listing._break`.
  - In `tools/m4count.c`: `on_enter`, `on_cycles`, `on_exit_event` and `seq_break`.
- **The fragment refuses the pair.** A pair whose `[t(EXIT_n), t(ENTER_n+1)]` holds such a fragment fails E1 as `broken_between` (`Listing._frag_between`, `frag_between`). E1 is tested before E3.
- **So E3 = `none` never admits a pair across an entry where the guest did not run.** [TE]'s rule for both architectures is enforced through E1.
- **No fixture exercises this path.** m4fix-1 to m4fix-3 expect no broken triple, no alternate-order triple and no `broken_between` pair. m4fix-4 has no GUEST_EXIT.

### 3.7 Caveat

- This is TCG with emulated EL2. qvm and procnto write the encoding, so it may carry over to the board unchanged (HYPOTHESIS until r1).
- On silicon the real syndromes, the asynchronous exits and the mix of classes will differ.

## 4. What only the board can show

**What r1 records** (m4-design.md §14.7). `startup/make-m4-images.sh` gives r1 and r2 `e3=none` unless a size file names `e3`, and gives r0 `status0` (VERIFIED).
- **`M4C STATUS`:** each distinct `status` value in first-seen order, up to `STATUS_PRINT` (16) lines, with its count over the listing and inside the marker window.
- **`M4C STATUSSUM`:** the distinct, printed, other and missing counts, the in-window remainders, and an overflow count past `STATUS_KEEP` (64).
- **`M4C QVM status_nonzero`:** the GUEST_EXIT events with a non-zero `status`, whatever E3 is.
- **The verbatim listing** (block `v`, cap 1 MiB): the marker window's events, unless capped.
  - On it the PC can repeat every §3 check: `status` against class, IL, `payload`, the resume address, CYCLES presence, host interrupts inside triples, and the chain.
  - The evidence script already reads a counter selection block (it read attempt 2's under TCG). Pointing it at r1's block `v` is a small change.

**A discrepancy to fix before r1 is read (VERIFIED by reading both implementations).**
- **What §14.7 says:** `PAIRS status_nonzero` still counts, under E3 = `none`, the pairs that `status0` would refuse.
- **What the code does:** `status_nonzero` is a pair *reason*, set only when E3 is `status0` (`Listing._pairs`; the `opt_e3_status0` branch in `tools/m4count.c`). Under `-E none` the field always reads 0.
- **The consequence.** At r1 nothing records how many pairs `status0` would refuse. The per-exit `QVM status_nonzero` and the `STATUS` records are still recorded.
- **Fix, for the orchestrator.** Correct the §14.7 text, or add a pair counter that works under both settings. Either way, change the counter and the parser together, with a fixture expectation.

**What r1 can settle, once parsed:**
- whether any board GUEST_EXIT carries `status` 0, and in which classes;
- whether `status` still holds the exception class of `hw_reason`, and which extra bits appear;
- whether an aborted-entry pattern exists on the board, and whether E1 catches each such exit;
- whether the order check (m4-design.md §12.2 M11) and the chain hold for every `status` value on silicon;
- whether negative dwells or chain failures cluster in any `status` class there.

**What r1 cannot settle:**
- **What QNX means by the field.** Consistency on the board is evidence, not a definition. The meaning stays UNKNOWN until QNX says.
- **Events outside the window.** Only in-window events reach the PC. A class seen only outside the window shows in the `STATUS` counts and nowhere else.
- **A long value list.** If the board prints more than `STATUS_PRINT` distinct values, the rest fold into `other`. They are then visible only in block `v`, and only inside the window.
- **`status` at r2.**
  - r2's compact pair list carries `hw_reason` but not `status` (the `fields=` line of m4-design.md §4.5.8, in both implementations).
  - If the freeze picks a rule on `status` bits, the PC can recheck it only through r2's 128 KiB verbatim sample.
  - m4-design.md §14.2 I16 warns that sample may hold no window event.
- **Figures.** r1 is functional under owner decision (b). It measures nothing.

## 5. Candidate E3 rules for the freeze

| Rule | What it refuses | For | Against |
|---|---|---|---|
| **(a) `status0`**, the design's rule | Any pair with a non-zero `status` on either exit | The only rule with a vendor sentence behind it ([TSC]). The strictest rule | [TSC] names no architecture or release. [TE] gives the non-zero rule for x86 only. How it behaves on our TCG traces is held locally (§3) |
| **(b) `none`**, the functional rungs today | Nothing for `status`. E1 still refuses pairs across an entry with no CYCLES, and E4 refuses negative dwells | Follows the one rule [TE] gives for both architectures (an ID 7 event present), which E1 already enforces. Refuses nothing on an undocumented field. `QVM status_nonzero` and the `STATUS` records keep the values visible | Rests "the guest ran" on the ID 7 rule alone. If QNX deems some ARM entries invalid despite a CYCLES event, they are admitted unseen. The E1 path has no fixture. A stale-ENTER pair with a non-negative dwell can pass E1, E2 and E4, because the chain is not a rule |
| **(c) a documented bit mask** | Pairs whose `status` has a bit that QNX documents as "entry not valid" | Would encode the vendor's meaning exactly, with nothing guessed | No such mask is documented (UNKNOWN). A mask read off TCG bits is HYPOTHESIS: it puts our reading in place of a definition. It needs a new `-E` mode in both implementations, with a fixture. Worth doing only once QNX answers |
| **(d) exclude exception classes** | Pairs whose opening exit's `hw_reason` class is on a list, such as classes that do not decode as hardware syndromes | Uses the class field, whose layout Arm defines and QNX's header names. Targets exits whose `hw_reason` is not a real syndrome | It is not a validity test: it changes what "per-exit dwell" samples, so the headline must name the classes kept. Which classes are synthetic is HYPOTHESIS. On the board, asynchronous exits may be common and long (host interrupt work), so dropping them biases the tail low. For entries where the guest did not run, E1 already does the job (§3.6) |

**Recommendation, for the owner at the freeze.**
1. **Keep E3 = `none` for the campaign,** unless item 2 or 3 applies.
   - It matches the only documented test that covers both architectures, and E1 already enforces that test.
2. **If QNX documents an aarch64 meaning before the freeze,** adopt (c) with the documented mask. Label it VENDOR_CLAIM, and add the `-E` mode and a fixture in lockstep.
3. **If r1 shows `status` 0 on ordinary board exits,** re-open (a). Compare both settings on r1's records before choosing.
4. **Do not adopt (d) as an eligibility rule.** Report dwell by `hw_reason` class instead. The PC can do that from the compact list, which already carries `hw_reason`.
5. **Before the freeze, whatever E3 is chosen:**
   - add a fixture with an entry that has no CYCLES, expecting `broken_between`;
   - fix the `PAIRS status_nonzero` discrepancy (§4);
   - decide separately whether the cross-pair chain becomes an eligibility rule.

## 6. Open questions

1. **For QNX support.** What do the aarch64 `status` bits mean in SDP 8.0? Does any value mark an entry whose CYCLES values are not valid?
2. **For QNX support.** Which release, architecture and host produced [TSC]'s sample? Does its zero-status sentence apply to 8.0 on aarch64?
3. **For QNX support.** What do `hw_reason` values that do not decode as hardware syndromes mean? Any such values are in the evidence log, not here.
4. **For QNX support.** Does [SAT]'s note, that the reason might show an aborted attempt, refer to `hw_reason`, to `status`, or to both?
5. **Board, r1.** Does the board print the same layout, and does any exit carry `status` 0?
6. **Board, r1.** If the board shows an asynchronous exit class, what triggers it: forced exits, host interrupts or something else? Can the trace tell them apart?
7. **Design.** Should the cross-pair chain become an E rule? Can a pair that fails it reach the clean class today?
8. **Design.** Should r2's compact list carry `status`, so that a `status`-based rule chosen at the freeze can be rechecked beyond the verbatim sample?
9. **Design.** Which gets fixed, §14.7's `PAIRS status_nonzero` statement or the code (§4)?
10. **Owner, publication.** After the professor is consulted, may `status` and `hw_reason` values from our traces appear in tracked files? May a question to QNX support quote them?
