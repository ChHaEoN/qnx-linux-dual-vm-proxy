# Pre-registration: gates G1 and G2 (SDV Phase 8)

DRAFT, 2026-11-01, after three independent re-checks' fixes. It takes effect when it is committed on `sdv-local` as
`sdv/aw/prereg-g1g2.md`, before any G1 arm runs (a copy stays here, `P:phase8\prereg-g1g2.md`). After that commit a threshold,
an arm or a counting rule moves only by a new dated section below, written before the run it applies to, and never after a
run has been read.

Local only (decision 15): `sdv-local` is never pushed, and no gate result leaves the private records (4.6(i); the owner,
2026-09-27). Sources: `P:phase8\prep.md` D8, D9, D10, D11, D15; the earlier plan `OP` lines 505-543, 599; the specification
`P:phase8\wp8\spec.md`.

## 1. The question

G1: with the QNX guest running beside it under KVM, does Autoware's planning simulator with the claim node stay inside the
thresholds below on the Orin Nano's 8 GB, for a 20-minute scripted loop? It is a memory gate first. G2 (section 8) asks the
same with CARLA as the simulator.

A pass says "this configuration, this loop, this boot, these design values". A fail decides nothing by itself: D11 sends it to
the owner (Phase H, whose boards and prices are read again then).

## 2. WHAT IS KNOWN when this is written (record names only)

- Autoware's arm64 image on an ARM host, judged by the guest: `1d7c10b4`, `ad37f81e`, `c6588573`, `de0ce9de` (c7g.metal).
- Session S, the sizing pre-screen: `584776c2` (c7g.metal). D7 says it cannot replace G1, and nothing from another host's
  CPU transfers to the A78AE.
- The judged PC runs: `2100ef63`.
- `ifs-ctl.bin` on the Orin, guest only: `12623e00`.
- Containers beside a guest on the Orin, none of them Autoware, each under the stack's small memory limit: `72261c6b`, `86eebccf`.

**Disclosed:** the author read S's samples and one `MemAvailable` read of the 2026-10-31 day before fixing the design values
in section 4. D10's thresholds (T1-T3, T4's rate, T5, T6) date from 2026-10-17 and did not move for them. Autoware has never
run on the Orin; nothing here has been run under G1's form.

No outcome is predicted. The gate reads thresholds, and any verdict it gives is a result: the harness ends DONE on a FAIL, and
no check anywhere fails or stops a run because a threshold was missed. Only the watchdog stops anything, and it stops on a
board-safety floor, which is a gate item when it fires.

## 3. Arms (D10)

- **Main arm (one):** the guest (`ifs-ctl.bin`, the launcher's defaults of 2 vCPUs and 1 GiB; the harness pins QEMU's threads to
  cores 0-2 with `vss-repin.sh` and sets its `oom_score_adj` to -1000), Autoware's planning simulator, the claim node on :7150, the scenario driver and the diagnostics
  recorder (all containers on cores 3,5); the graphical session as booted, and recorded. Run once on the day.
- **Guest-stopped arm:** only if the main arm's verdict is FAIL, and on the owner's word on the day. The same loop with the
  guest stopped. There is no monitor to answer, so the claim node does not run, the count recorder of section 6 replaces it, and
  the driver runs without `--require-claim-node`. It reads the same memory, OOM, rate and diagnostics items; drop and lost do not
  apply. The recorder's callback is lighter than the claim node's, so its T4 is not the same instrument as the main arm's and the
  two are never subtracted. It says whether the fail remains without the guest and changes the main arm's verdict in no way.
- **Not arms:** "G1 + platform" (the feeder, the databroker, the stack; `P:sdv-alignment-plan.md`:642), the containers on 3-5 (OP's sizing control,
  which D10 left out), a repeat of the main arm to get a different answer.

One boot, one main arm: this is one observation, with no spread and no rate of passing. Nothing here supports a claim
about another boot.

## 4. Design values (not measured, not results; fixed before the run)

| value | what | why |
|---|---|---|
| 1200 s | the loop: drives begin until this much wall clock (counted on CLOCK_MONOTONIC) has passed since the first route was set, then the drive under way finishes. A first drive with no `route` line of outcome `done` ends the loop | D10 |
| cores 3,5 | every container by `--cpuset-cpus`; dockerd and containerd by `AllowedCPUs` at runtime (a container's scope is no child of `docker.service`, so the property does not reach it) | D8 |
| core 4 | the sampler, the watchdog and the clock sampler on the host | none of QEMU's cores or the containers' |
| 3200 MiB | `--memory` and `--memory-swap` of `aw-sim` | a backstop against a runaway; depending on the day's headroom the watchdog may bite first (`spec.md` section 2), and either way the arm fails |
| 256 MiB | `--memory` and `--memory-swap` of each of the others | as above; none of them holds Autoware |
| 716800 kB (700 MiB) | the watchdog's floor on `MemAvailable`: below it the containers are killed | under G1's threshold (D10, design point j) |
| 1 s | the watchdog's spacing (`MemAvailable` only) | the gate's minimum is read from this series |
| 5 s | the sampler's spacing (`meminfo`, `vmstat`, per-core CPU, `docker stats`, each running scope's `memory.events`, each with its own time). Information only: no item reads it, and a gap in it is reported and is no instrument's failure | S's spacing; never a login |
| 10 s | the rate's windows, [start, start + 10 s) and consecutive from each drive's first frame; a window that would end after the drive's interval is dropped | OP: the node's per-window counts |
| 0.5 s | a clock sampler on `lib-measure.sh`'s `SAMPLER_LOOP` form (`emc_bpmp_hz`, wall clock), running for the whole arm under the arm's own bound, not `m_sampler_start` (whose ceiling comes from a ladder's N and interval, and which starts `tegrastats` as well); a CLOCK_MONOTONIC and wall-clock pair is read at the arm's start and end to place it against the rate's windows | `SAMPLE_WINDOW=1`'s reading; G1 has no ladder windows |
| `drop_caches` 3 | once before each arm, `buff/cache` read before and after (D10) | |
| nvpmodel mode 1, the governor pinned, `SAMPLE_WINDOW=1` | never changed; stamped | prep's list of the Orin's days (G1) |
| none | sysctls and `lo` multicast: G1 sets none, and the four settings of 2.12 are read before and after and must be equal | 2.12; the PC and c7g.metal ran without them |

## 5. Thresholds (D10, with OP:527-532; T4w and T7 added here, each named as an addition in `spec.md` section 9)

The main arm **PASSES** only if every item holds:

| item | threshold | read from |
|---|---|---|
| T1 no OOM kill | `oom_kill` in `/proc/vmstat` unchanged (host-wide; this counts a cgroup's kills and a node killed inside a living container), and `memory.events` `oom_kill` 0 in each scope that still exists. A scope gone by then is T7's, T6's or the positive control's matter and not T1's, whose kills the host-wide counter already shows | the harness's own reads, before the first container and at the loop's end before any stop. `OOMKilled` is recorded as information only |
| T2 no watchdog stop | the watchdog's log holds no stop | the watchdog's own file |
| T3 lowest `MemAvailable` | at least 1048576 kB (1 GiB), the lowest value of the 1 s series from the first container's start to the last one's stop | the watchdog's series |
| T4 the `control_cmd` rate | at least 30.0 per second (90 % of 1/0.03 s), by wall clock (counted on CLOCK_MONOTONIC, as against G2's sim time): section 6 | the reply log |
| T4w no stalled window | no 10 s window under 150 frames (half of T4's 300 per window): section 6 | the reply log |
| T5 no validator timeout | section 7 | the diagnostics recorder |
| T6 drop and lost | `drop` 0 and `lost_on_reconnect` 0 in the claim node's summary, and its identity holds | the reply log's last line |
| T7 every drive | every drive that began ended with the driver's exit 0, at the goal, its route cleared; the loop reached 1200 s | `scenario.jsonl`, the driver's exits |

**Verdicts:**
- **FAIL:** any item fails. A loop that did not reach 1200 s fails T7, whatever ended it but for the next bullet's cases. A reset, a
  hang or an oops during the arm is a FAIL with its cause not assigned, whatever else was read; the readings it prevented (T7's 1200 s,
  T1's end read, T6's summary, the last drive's line) are not readings, so its one failing reason is the reset.
- **NOT JUDGED:** no item failed by a reading, and either one of the harness's own instruments gave no reading (the list below) or
  the harness itself exited before the loop's end, or stopped it for a dead watchdog or a misplaced container. The verdict names which.
- **PASS:** all items hold and every instrument below gave its reading.

**The instruments (each one missing is NOT JUDGED, naming it):** the 1 s series covers the span from the first container's start to
the loop's end, with no gap over 5 s between consecutive readings and none between its last reading and the loop's end (a gap is
reported with the lowest value on each side of it where both exist, and is itself evidence of pressure, not only an absence); the stamp
was written under `PLATFORM_POLICY=g1` and did not refuse, which checks the daemons and records the socket, the stamp being written
before any container starts; the harness's read after each container's start found it on {3,5} by both its request and its effective
cpus; every frame line of the reply log has its outcome, one per seq; the `ctl rules:` digest equals `vss_ctl.py`'s; section 7's
positive control holds; the four settings of 2.12 are equal before and after; the harness's one-clock check held (section 6).

**A dead instrument does not stop the loop, with two exceptions.** The harness goes on and records the gap; the reply log goes on.
Nothing in the gate reads the 5 s sampler. **The exceptions:** the watchdog is the only board-safety stop, so the harness checks that
it lives and that its series grows before each drive, and if not it stops the loop and the containers; and a container found off
{3,5} stops the run before the loop, since no reading could then be judged. Neither is a threshold's stop.

**A re-run:** a NOT JUDGED arm, or an arm whose one failing reason is a reset, a hang or an oops, may be run again on the owner's
word on a later boot. Every arm and its partial readings stay in the record, and a pass after such a reset is reported only as that:
passed on a later boot after a reset of unassigned cause, never as a plain PASS (the record's header says the arm is a re-run, and of
what; `aw_g1.py judge` takes it as an argument and prints this label). An arm with any item failed by a reading is never re-run for a
verdict.

A driver's non-zero exit does not end the loop: it is recorded, T7 has already failed, the next drive begins, and the time still
counts, so the memory series goes on. The loop ends early only when `aw-sim` has died, when the watchdog's stop file exists, by the two
exceptions above, or when a first drive had no `route` line of outcome `done`.

## 6. The counting rule

- **Clock:** each frame's `tstamp_ns` (bytes 8-15 of the hex in `replies.jsonl`, the client's clock when it packed the frame), and
  `mono_ns` of each step in `scenario.jsonl`. Both read CLOCK_MONOTONIC on one host. The harness checks that at the start: a
  (CLOCK_MONOTONIC, wall clock) pair read in one action inside a container and another on the host, their offsets within 1 s, so a
  container's start-up time does not enter it; a failed check is NOT JUDGED. The outcome's `mono_ns` is not used for placing a
  frame: it comes after the reply and can be late by the reply timeout.
- **What counts:** a frame whose outcome is `replied`, `drop` or `lost`. A Control the claim node's callback never ran for is never
  counted, so this is **the rate the claim node took, on cores 3,5**, not the topic's own rate. A shortfall can come from CPU as well
  as from Autoware; the gate does not tell them apart. `control_topic_status` carries its own `measured_rate` (the spike's S3), which
  the recorder keeps every 5 s and the record shows beside T4: it is the topic monitor's own reading, ungated, and a third subscriber's.
- **A drive's frames:** those with `tstamp_ns` after its `route` line of outcome `done` and at or before its last `scenario.jsonl`
  line's `mono_ns`, whatever that line's outcome. A frame outside every drive (a Control that came before SET was seen, or between drives
  if Control does not stop at `clear_route`) enters no interval; the count of them is recorded, and T6 still reads them. This rule
  holds whichever way the spike answers about Control after `clear_route`.
- **A drive's interval:** from the first of its frames to its last line's `mono_ns`. The wait from SET to the first Control (planning
  must produce a trajectory first: W4 G2) is outside it and recorded. A drive with no `route` line of outcome `done`, or no frame, has no
  interval, and T7 has failed. A drive killed before it wrote a last line ends at the last line it wrote. With no interval in the whole
  arm, T4 and T4w print "no reading" (T7 has failed).
- **T4's figure:** all frames inside drive intervals divided by the sum of those intervals; one number for the arm. The
  silence between drives counts in neither direction. The bound of this form, stated so that nobody reads more into it: it alone
  would pass a complete stall of up to 10 % of the driven time, which is why T4w exists.
- **T4w's figure:** each window's count, the windows as section 4 says. Its bound: a stall of up to about 11 s can pass when it straddles
  a window boundary, and a drive under 10 s has no window; its frames still enter T4.
- **Recorded, not gated:** the distribution of the windows, each window's `emc_bpmp_hz`, the number of drives, the sum of the
  intervals.
- **Verdicts are recorded and are not gate items.** Control has not been seen to stop between drives on one `aw-sim` (the spike's
  S1, the PC), so no MISS or reason 11 is expected at a drive boundary. Any REJECT, and any MISS, wherever it falls, is a finding, never
  a moved limit, and is in the record with its seq and its place against the drives.

The count recorder of the guest-stopped arm is a small rclpy node with the claim node's subscription QoS (RELIABLE KEEP_LAST 1
VOLATILE). It keeps only arrival times, read by the same rule, its clock the node's CLOCK_MONOTONIC.

## 7. T5, "no validator timeout"

The earlier plan names the item and not its signal, and this image has no status that is a validator's timeout. The list below was
settled from the image's own run on the PC (the spike's S1, `spec.md` section 3); it is this pre-registration's reading of OP's words,
named as such in `spec.md` section 9. `S:sdv/aw` gains a small recorder (`aw_g1_diag.py`, the `aw-g1-diag` container) that
subscribes to `/diagnostics` and writes the first observation of each status name of the control path, each change of its
level, and every 5 s each name's last-seen time, every line with the node's CLOCK_MONOTONIC.

**The list:** `topic_state_monitor_control_command_control_cmd: control_topic_status`,
`topic_state_monitor_trajectory_follower_control_cmd: control_topic_status`, and `controller_node_exe: incoming_message_timeout`.

**T5 fails** when a status on the list that has been OK reaches ERROR, or when one has not been OK by the end of the first drive. Each
is at ERROR before the first route by design (Control has not begun), so the wait before it counts for nothing.

**Not on the list, recorded:** `control_validator: control_validation_latency`. It is a check against a nominal latency, not a timeout,
and it left OK repeatedly in S1, a healthy run on a far faster host, so it would fail T5 by design. Its entries and its time away from OK
are in the record. `timeout_output` of `control_command_gate` is in the image's `control.yaml` and was never published in S1.

**A silent validator:** a validator that dies never reaches ERROR, because `control_validator` is a side checker and Control flows on
without it. So T5 also fails when, at a 5 s line inside any drive interval, the time since any `control_validator` status was last seen
is over 10 s while the recorder was still seeing other names.

**The positive control:** at least one observation of a `control_validator` status at OK in the arm, and the recorder still seeing
some name at the end of every drive; without either, NOT JUDGED.

Every other status that reached WARN or ERROR is listed and is not a gate item. The recorder's subscriber is load G1 would
not otherwise have: its `docker stats` lines are recorded, and the record says it ran (the plan's Phase 8 item 4, for an added
subscriber).

## 8. G2 (run under WP9; thresholds fixed here)

As G1 (OP:599), on the Orin as the edge in the same form (D9), with CARLA on the PC reaching the board over the Wi-Fi: T1, T2,
T3, T4w, T5, T6, T7 as written. T4 by **sim time** (`use_sim_time` true there), with the RTF and the wall-clock rate recorded beside
it. One main arm; a guest-stopped arm only if it fails. WP9's specification adds the instruments (the RTF's source, the window's
sim-time clock, the interface's memory on the board) by a dated section here before G2 runs. It may add items, and it moves
no threshold above.

## 9. What neither gate can show, whatever it reads

That the Nano runs a full Autoware (perception and localization are off; G1 is a planning simulator); any figure on another
boot, map or route; CARLA (G1); the topic's rate as Autoware published it (T4 is what the claim node took); any isolation or freedom
from interference (the guest shares memory bandwidth, and Linux owns its memory); any real-time guarantee, or any latency (the rate
is a count over a wall clock, not a timing of the path); that Autoware's commands were safe or correct; any safety or certification
property. The `startup-qemu-virt` that boots under KVM is ours, not a QNX-supported configuration, and no timing claim attaches to
the boot.

## Dated sections (added before a run; nothing above changes)

### 2026-11-01: readings where the sections above give no rule, or two (the orchestrator; before any arm, no arm has run)

No threshold moves here. Each item says how a case the text above leaves open is read, so that the code's choice is this document's and
not the code's. Items 1, 2, 6, 8, 12 and 13 keep a harness or instrument failure from being read as a reading of Autoware, because a FAIL by a
reading is never re-run; none of them can turn a FAIL by a reading into a PASS.

1. **T5 when the recorder saw nothing at the first drive's end.** A status not yet OK then has no reading, and is not T5's fail. The
   positive control (section 7) is missing, so the arm is NOT JUDGED unless another item failed by a reading. A first drive that never
   ended has no end for "by the end of the first drive" to name: that clause is not read. A listed status that reached ERROR after OK,
   and a silent validator, still stand in both cases.
2. **A container that could not be created, and a docker that does not answer.** A `docker run -d` exiting non-zero is the harness's
   own. An arm's standing containers end the arm `status=FAILED at=arm`; a drive's ends the loop as `docker-run-failed`, with the end
   reads taken and `status=DONE`. Both are NOT JUDGED ("the harness itself exited before the loop's end"). "`aw-sim` has died" (section
   5) needs docker's own answer that it is not running or does not exist. A `docker inspect` that gets no answer is recorded
   (`sim_inspect_unanswered`) and is no death; a dockerd really gone reaches the next `docker run`.
3. **"Any `control_validator` status" (section 7)** is each of the validator's names, not the newest of them: one name unseen for over
   10 s at a 5 s line inside a drive interval fails T5. "Still seeing other names" is some name not of the validator's seen within the
   same 10 s of that line. The span is the drive's interval (section 6), so the wait from SET to the first Control is outside it.
4. **"At the end of every drive" (section 7, the positive control)** is a 5 s line within 10 s of the drive's end, some name of it seen
   within 10 s of that line.
5. **T7 in the guest-stopped arm:** read there too, since section 3 gives it "the same loop".
6. **A reset's unequal tails.** Neither `replies.jsonl` nor `scenario.jsonl` is fsynced, and the harness syncs after each drive. With a
   reset, a hang or an oops, a drive with no `end` row enters no interval: T4, T4w and the silent validator read the drives that ended.
   Its frames stay in the record. This extends section 5's "the last drive's line" to what that line bounds.
7. **A status at STALE (level 3)** is no T5 fail: section 7 says ERROR. A listed status that reached it is named on T5's line.
8. **An item with no reading that no instrument explains** (T1's reads lost with the harness alive, say) is NOT JUDGED, naming the item.
   PASS needs every item to hold and FAIL needs a reading.
9. **A container already ended at the read after its start:** recorded, nothing stopped, the placement instrument missing for it.
10. **The one MISS when the claim node stops after the last drive,** with the guest still running, is a finding under section 6 as any
    MISS is, named in the record by its place. No gate item reads it.
11. **The simulator's wait** (a design value, not a threshold) is 1200 s from its `docker run`, in place of the 600 s first coded. The
    harness polls and goes on as soon as the services list, so a longer bound costs nothing on a simulator that comes up, and too short
    a bound on these two cores would read as `first-no-route`, a FAIL that is never re-run. The rehearsal's other CPU cannot read this
    value for the Orin. The time it took is in the record; the arm's deadline allows for the bound.
12. **A `docker wait` on a drive.** An exit number from docker is the driver's exit. A bound that expires while docker still answers
    that the container is running is the drive's reading: exit 124, and T7 has failed. Anything else read no exit: a `docker wait` that
    exits non-zero, or a bound that expires with no answer from docker either. That drive's row is `stopped`, the loop ends as
    `docker-wait-failed`, and the arm is NOT JUDGED ("the harness itself ... stopped it"). Item 2 holds for the same reason.
13. **The claim node's summary when the harness's `docker stop` got no answer:** the node was never signalled, so its missing summary
    is T6 with no reading, NOT JUDGED naming T6. A missing summary after a `docker stop` that answered stays T6's FAIL.
14. **Item 13's last sentence is about a loop that reached its end.** Where the loop ended by a word of the harness's own (`deadline`,
    `watchdog-dead`, `misplaced`, `docker-run-failed`, `docker-wait-failed`), a missing summary is T6 with no reading whatever the
    `docker stop` answered. The arm is NOT JUDGED already, and a stop's answer does not show that the node was still alive to be signalled:
    a dockerd that went down and took the node with it, then answered, is this case. It must not read as Autoware's.

### 2026-11-02: the driver is resident (the orchestrator; before any arm, no arm has run)

15. **No threshold, arm or counting rule moves.** Known when this is written: the rehearsal `f809cf90` and the
    private diagnosis `phase8\wp8-diag\` (record names only). The scenario driver is one container and one process for the whole arm, started
    before the first route, on {3,5}. Each drive begins by the harness's word and ends with the driver's exit number in a file in that
    drive's directory. So: section 5's placement instrument reads that container's one start. Item 2's `docker run -d` of a drive is that
    one start: its failure is the harness's own, as item 2 says. Item 12: a number from the driver's file is the driver's exit; a bound that
    expires while docker answers that the container runs is the drive's reading, exit 124; a container that ended with no number written is
    that drive's reading with docker's exit code, and the harness starts it again for the next drive; anything else read no exit, the row is
    `stopped`, the loop ends as `docker-wait-failed`. After a drive with a non-zero exit the driver asks for STOP, clears the route and writes
    that to its own file, never to `scenario.jsonl`: T7 has already failed, and the next drive begins on a route that is clear, so the memory
    series goes on with the loop's load. T6 still reads the whole arm, frames outside drives included, and T6 at drop 0 stays a bound on the
    claim path; a fail on the board after this is a reading. What this gives up: a container start beside Autoware at each drive is no longer in the arm,
    and the driver's memory is there all the time, not only during drives.

### 2026-11-03: item 15's words, and two cases it already rules (the orchestrator; before any arm, no arm has run)

16. **No threshold, arm or counting rule moves.** Item 15's known-clause and its last sentence were reworded in place on this date so that
    they hold record names only, as section 2 asks of what is known; what item 15 rules is unchanged. Two cases item 15 already rules are
    said here so that they are not read as gaps. (a) A driver that ends with no number written is that drive's reading with docker's exit
    code, whatever the reason, a fault of the harness's own included (a directory it cannot write, a word it cannot remove, a rename that
    fails): the driver refuses a directory it cannot write before it joins, and the day's checks before the arm read the disk and the
    deploy. (b) A driver found ended between drives is started again for the next drive, which is a second join; T6 still reads the whole
    arm, frames after that start included. Either case in the second rehearsal goes to the owner before the Orin day.
