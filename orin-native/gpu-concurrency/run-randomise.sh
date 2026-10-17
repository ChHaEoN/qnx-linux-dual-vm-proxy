#!/usr/bin/env bash
# run-randomise.sh -- one board boot of the A6 setup randomisation: do the attribution ladder's paired
# contrasts move when setup factors that should not matter are randomised instead of held at one value,
# and is the guest's level re-drawn at every VM boot or only at every board boot? Phase 3b / A6,
# 2026-10-17. The owner adopted the design's decisions D1-D12 as recommended (2026-10-17); its source is
# the setup-randomisation item of the design suggestions (Mytkowicz et al., ASPLOS 2009). It runs on L4T
# R39 as A7's dimensioning experiment, labelled as such: no figure it records is an R39 baseline, and
# none is set beside an R36 record.
#
# The text from "1. The question" to the end of "7. Analysis", and "12. What it would NOT show", is the
# design's own text (only lines too long for this header are wrapped, and the markdown heading marks
# dropped). Sections 5 to 7 (D11) and 12 are copied word for word. Sections 1, 3 and 4 are copied word for
# word but for the departures below, each made so that this header states no outcome of any record: a
# pre-registration's WHAT IS KNOWN names records only, and no measured or functional result is published.
#   - Section 2 is replaced by WHAT IS KNOWN below, which names the design's records and notes by topic
#     and states nothing that any of them found.
#   - Section 1: Q2's first sentence, which stated a record's outcome, is dropped.
#   - Section 3: H2's first sentence names the share that P4's phi estimates, where it named a record's
#     outcome.
#   - Section 4.2: the "why" cells of the board boot, spacing, role placement and guest image rows give
#     the design's reason without a record's outcome, and the role placement row names the confinement.
#   - Section 4.3: the fallback image's devices are named as gate2-smoke.sh's G4 step presents them, and
#     the sentence on what that step did is dropped.
#   - Section 4.6: the confinement's heading names it without saying what it removes; the halt-polling
#     bullet on a blocked halt says that a contrast can include its cost; and the last Docker bullet,
#     which said where this code lived before this commit, now says that this commit ports it (D5).
# It is written and committed, with the schedule's hash below, before any run of this harness, smoke runs
# included. It is not to be amended.
#
# 1. The question
#
# Every A6 conclusion is a paired difference between arms measured in one setup. That setup includes:
#
# - one arm order;
# - one memory layout of the probe, of the host-side endpoints and of QEMU;
# - one placement of QEMU's threads;
# - one boot of the board and one boot of the VM.
#
# Mytkowicz et al. showed that setup factors which should not matter, such as the size of the UNIX
# environment and the link order, can bias a conclusion. They showed too that the bias on one machine does
# not predict the bias on another. Their remedy is to randomise such factors across runs and to see whether
# the conclusion survives the resulting distribution of setups.
#
# This design asks three things of the A6 attribution ladder (loopback, bridge, guest echo, guest monitor):
#
# - **Q1, robustness.** Do the ladder's paired contrasts move when setup factors that should not matter are
#   randomised instead of held at one value? The contrasts are the crossing, the monitor's own work and the
#   bridge. The factors are the arm order, the host-side processes' memory layout, QEMU's memory layout and
#   the vCPUs' core assignment.
# - **Q2, where the level lives.** Is the p50 level re-drawn at every VM boot, or only at every board boot?
#   The answer decides whether a later campaign can sample the level's variance with VM relaunches, or must
#   reboot the board, which needs the owner at the plug.
# - **Q3, which factor.** If anything moves, which recorded factor goes with it? This part is unscored and
#   exploratory.
#
# It is a robustness and dimensioning experiment. It is not a re-baseline, and its level figures are not
# an R39 baseline (D1).
#
# WHAT IS KNOWN, by topic, records and notes only: every one held locally, the records on
# `a6-results-unpublished`, and all known when the thresholds were set. The resolution and run-to-run
# variation: 20260919T-native-cmp. The statistical second look: 20260924T-a6-stats. The boot and the level:
# 20260925T-a6-orin-boots, 20260925T-a6-orin-boots2. Guest images with and without extra services:
# 20260922T-a6-orin-shift. Arm order in the ladder: no record. Arm order in the loaded harnesses:
# 20260921T-a6-orin, 20260921T-a6-orin-pinned, 20260924T-a6-orin-rate. A review of the spacing order between
# two runs: 20260924T-a6-orin-haltpoll. Placement: 20260921T-a6-orin-pinned, 20260924T-a6-orin-vcpupin,
# 20260924T-a6-orin-tail. Spacing and halt polling: 20260924T-a6-orin-rate, 20260924T-a6-orin-haltpoll,
# 20260924T-a6-orin-blockpath, 20260924T-a6-orin-smp, 20260924T-a6-orin-power. The arrival process:
# 20260924T-a6-orin-arrival. The c7 idle state: 20260921T-a6-orin, 20260921T-a6-orin-c7off. Confinement:
# 20260925T-a6-orin-confine, 20260925T-a6-orin-natural. The host's tick: 20260925T-a6-orin-tick,
# 20260925T-a6-orin-partition. The guest's timer: 20260925T-a6-orin-guesttick. The tail under confinement, and
# the Wi-Fi: 20260929T-a6-orin-residual, 20260929T-a6-orin-irqconf, 20260929T-a6-orin-wifi. Confinement on a
# server host: 20260925T-a6-a1metal-natural. Docker and the R36 records: the findings entry of 2026-09-30.
# Gate 2's smokes on R39: the Gate 2 note of 2026-10-10. The board's configuration on R39: the R39 inventory
# note. An A6 timing on R39: no record. The ladder on a second host: 20260921T-ladder-a1metal,
# 20260923T-a6-a1metal-ladder.
#
# 3. Hypotheses
#
# - **H1.** The ladder's paired contrasts belong to the path, not to the setup. Arm order, the host-side
#   processes' layout, QEMU's layout and the vCPUs' core assignment move them by no more than the margin in
#   section 5.
# - **H2.** At least half of the level's variance between boots, the VM boots' and the board boots' together,
#   is re-drawn by a VM boot with the setup held fixed. The guest's memory placement, the virtio rings'
#   placement and QEMU's own state are new at every VM boot. With transparent huge pages set to `always` on
#   R39, the guest's physical placement against the physically indexed caches is re-drawn too.
#
# H2's direction is a stated guess. Section 5's scoring makes either outcome informative.
#
# 4. The design
#
# 4.1 Hierarchy and counts
#
# ```
# board boot  b = 1..6        (D2; each one a fresh boot of the shipped entry, settled 600 s)
#   VM boot   v = 1..4        (VM setup S: F R R F in odd board boots, R F F R in even ones)
#     round   r = 0..4        (r = 0 a settling round, discarded; r = 1..4 one round per cell (O, L), in a
#     drawn order)
#       arm   A B C D         (in the order cell O gives)
#         200 warm-up + 1000 timed exchanges, 2 ms spacing
# ```
#
# - **Totals:** 24 VM boots and 96 scored rounds.
# - **Per regime:** 12 VM boots in each regime of S.
# - **Per cell:** 24 rounds in each (O, L) cell. The fully fixed setup (S = F, O = fixed, L = fixed) has 12
#   rounds. It is the design's own reference.
# - **Whether the first board boot runs F R R F or R F F R** is drawn in the schedule (section 4.5).
#
# 4.2 The factors: randomised, held fixed, recorded
#
# | factor | level of the hierarchy | fixed (F) | randomised (R) | why |
# |---|---|---|---|---|
# | **O, arm order** | round | A B C D every round, the ladder's order | a uniformly random permutation of the
#     four arms, drawn per round | The ladder never varied it, and its header asserts that unloaded arms need
#     no balancing. Under the fixed order, B always runs just before C, so a position or carry-over effect
#     would sit inside C − B. |
# | **L, host-side layout** (the probe, and both native monitors) | per launch: the probe per arm-round, the
#     monitors per round | `setarch -R` (ADDR_NO_RANDOMIZE, per process); `env -i` with a fixed variable list;
#     `PYTHONHASHSEED=0` for the probe | ASLR as found (the kernel draws); the same fixed list plus `A6PAD` of
#     E bytes, E drawn uniformly from 0, 16, ..., 4080; `PYTHONHASHSEED` drawn | These are Mytkowicz's two
#     factors. The probe's hash seed is the Python analogue of ASLR. See the note below this table. |
# | **S, VM setup** (QEMU's layout, and the vCPUs' core assignment) | VM boot | QEMU under `setarch -R`, `env
#     -i` with a fixed list; threads pinned one group per core: vCPU 0 on core 1, vCPU 1 on core 2, every
#     other QEMU thread on core 0 | QEMU with ASLR as found and `A6PAD` of a drawn E; the three thread groups
#     pinned by a permutation onto cores 0, 1 and 2, drawn per VM boot from the six | A VM boot can re-draw
#     both. F holds them at one arbitrary point, which is exactly the setup Mytkowicz warns about. |
# | **board boot** | board boot | none | every boot is a fresh draw of what the host's boot sets: KASLR,
#     physical layout, driver and interrupt state | P4 sets the board boot against the VM boot as a level of
#     the hierarchy. Six boots sample it (D2). |
# | **spacing** | none | 2 ms, constant, every arm | not randomised | By KVM's source, an idle gap shorter
#     than `halt_poll_ns` can end in a poll, so spacing selects a halt-polling regime and is not a nuisance.
#     Randomising it would mix regimes. |
# | **arrival process** | none | constant sleep after each reply | not randomised (D7) | The probe sleeps
#     after each reply, so an exchange's phase against the host's 4 ms tick drifts by the round trip at every
#     exchange. A start-phase draw would buy nothing. The shape of the arrival process at the A6 mean is a
#     record already. |
# | **role placement** (which cores QEMU, the probe and the monitors use) | none | QEMU on 0–2, the probe on
#     4, both native monitors on 3, the userspace confined to 3 and 5, the auxiliary reader on 5 | not
#     randomised (D6) | This is the A6 confinement's layout, which the A6 harnesses use. On R39, cores 0–3
#     and cores 4–5 share an L3 each, so moving a role changes the path. |
# | **guest image** | none | one image for every VM boot, identified by hash in every stamp | not randomised |
#     An image's services could move the rungs, so one image, identified by hash, holds that factor fixed. |
# | **code layout** (link order, text alignment) | none | the binaries as built | not randomised (D8) | See
#     D8. |
#
# **ASLR and the environment.** By the Linux source (`arch/arm64/kernel/process.c`, `arch_align_stack`),
# a process with ASLR on gets a random sub-page offset of its initial stack. So under ASLR the environment
# pad adds nothing to the stack's alignment, and the pad matters as an alignment factor only with
# `setarch -R`. R keeps the pad anyway: it costs nothing, and it makes R's environment differ from launch
# to launch as Mytkowicz's did. The analysis treats R's layout as one draw and does not try to separate
# the pad from ASLR (U4).
#
# **Why `env -i` in F.** Without it, the environment of a launch carries the SSH session's variables. The
# client's port, for one, is new at every login, so in a `setarch -R` launch the layout would change with
# every board boot's login.
#
# **Why the monitors are relaunched every round in both regimes.** The relaunch is then not confounded with
# L.
#
# 4.3 Arms
#
# These are the TCP ladder's four rungs, as `run-ladder.sh` defines them, with the probe on core 4 and
# `latency_probe.py` as the instrument:
#
# - **A, loopback.** probe → 127.0.0.1:7100 → the native monitor on core 3. This is the instrument's
#   floor, and it is the arm most exposed to the probe's own layout.
# - **B, bridge.** probe → br0 → veth → the network namespace → the native monitor on core 3.
# - **C, null.** probe → br0 → tap-qnx → the guest's echo server on :7000.
# - **D, guest.** probe → the guest's monitor on :7100, the plain monitor, unstamped.
#
# The outcomes are the p50 of each arm-round and three contrasts per round:
#
# - `K1 = C − B`, the virtualisation crossing;
# - `K2 = D − C`, the monitor's own work;
# - `K3 = B − A`, the bridge.
#
# The level is `Lv = p50(D)`, and the floor is `p50(A)`.
#
# **The image.**
#
# - Use `ifs-stamp.bin` if its build file starts the echo server on :7000 beside the plain monitor on
#   :7100. The boots records used it, so the boot question continues on the same image.
# - Otherwise use `ifs-kick.bin` with its devices presented exactly as `gate2-smoke.sh`'s G4 step presents
#   them.
# - Confirming which of the two applies belongs to the harness specification. It is not an owner decision.
#   Either way, one image serves every VM boot.
#
# **The native monitor.** Use Gate 2's native monitor (`~/gate2/bin/20261009T221811Z/`, with its source
# hash), checked against `monitor.c` at the harness's commit. A fresh build is allowed only before the
# session, and a reboot must follow it (the R39 rule).
#
# 4.4 Rounds and samples (OD11 as adopted)
#
# - n = 1000 timed samples per arm-round, 200 warm-up discarded, 2 ms spacing.
# - Every round runs all four arms back to back.
# - The round is the unit; samples inside an arm-round are never treated as independent.
# - k is the lever:
#   - P1 and P2 have k = 24 VM boots, each a block of the four cells;
#   - P3 has k = 12 adjacent F–R pairs;
#   - the fully fixed reference cell has k = 12 rounds;
#   - every comparison meets OD11's k ≥ 12.
# - **The settling round r = 0** follows each VM boot's readiness check and a 30 s pause. It runs the four
#   arms in the fixed order with the fixed layout and is discarded. Its job is to keep the scored rounds off
#   the guest's first exchanges after boot.
#
# 4.5 The randomisation schedule: drawn before the run
#
# One master seed generates every draw, and the draws are written to a schedule file before the session:
#
# - each board boot's S pattern;
# - the cell order in each VM boot;
# - the arm order of every O-random round;
# - every `A6PAD` length and every `PYTHONHASHSEED`;
# - each R VM boot's permutation and pad;
# - the bootstrap seed.
#
# The schedule's sha256 goes into the harness header's commit together with the predictions (D5). The
# harness only executes the schedule, and the report checks that `order.log`, the stamps and the read-backs
# match it, line for line.
#
# 4.6 Platform controls
#
# **The confinement.**
#
# - **Applied in every round of both regimes.** The units `system.slice`, `init.scope`, `user@1000.service`,
#   every other `user@` service (the greeter's, on R39), and every session scope except the harness's own
#   are set to `AllowedCPUs=3,5`.
# - **When.** It is set once per board boot, after the bridge, quiesce, governor and c7 steps and before the
#   first VM boot. Restoring sets `0-5` explicitly, then removes the drop-ins and reloads systemd.
# - **Re-pinning.** Turning the cpuset controller on resets affinities in the scopes. So QEMU is launched
#   only after confinement is in place, and it is pinned after launch.
# - **Read-back.** The allowed CPUs of udevd, PID 1, gnome-shell or the greeter, and every QEMU thread are
#   read before and after every round.
# - **Not changed.** There is no `isolcpus`; the shipped command line is used.
# - **The native monitors' core.** They run on core 3, a confinement core, as the ladder places them. So
#   arms A and B share core 3 with the confined userspace (D6).
#
# **The governor.**
#
# - `m_governor_pin` sets `performance` on every core. R39 has two cpufreq policies, 0–3 and 4–5, and the
#   pin covers both.
# - It is re-checked at the end of every VM boot and restored at the end of every board boot.
# - nvpmodel stays in mode 1. The stamp asserts that, and the harness never switches it.
#
# **Idle states.** `CSTATE=shallow` is set before the library loads, which disables c7 (still present and
# enabled by default on R39, per the inventory). It is read back, and restored at the end of each board
# boot.
#
# **Docker (S6(a), and the owner's S6 for R39 of 2026-10-17).**
#
# - `platform-quiesce.sh stop` runs at each board boot's start, from a fixed state path. Docker 29.1.3 and
#   containerd are enabled and idle there.
# - The stamp refuses to start while dockerd or containerd runs outside {3, 5}, or while `docker.socket` is
#   active, activating or reloading. The stamp records the platform state at the start and at the end.
# - **`restore` runs before every reboot.** Its marker is in `~/.local/state` and survives the reboot, so a
#   skipped restore makes the next board boot's `stop` refuse.
# - Ported to `main` by this harness's commit (D5).
#
# **Halt polling.**
#
# - Nothing changes it. `halt_poll_ns` and its three companions are read at each VM boot's start and end,
#   and must be unchanged.
# - `KVM_STATS=1` takes the VM's KVM counters and QEMU's per-thread schedstat around every arm-round in
#   every cell, so the sudo snapshot and its pause are the same everywhere.
# - At 2 ms spacing a contrast can include the cost of a blocked halt. A factor that changed how often
#   halts end in a successful poll would show in the counters (U5).
# - On R39 the 6.8 source reads the module value on each halt, unless a per-VM override applies. That has
#   not been tried on the board. This design changes nothing there, so it does not depend on it.
#
# **The EMC clock.**
#
# - No GPU load, camera or model runs. `SAMPLE_WINDOW=0`, as in the ladder: no sampler runs beside the
#   timed windows.
# - Both EMC debugfs nodes are read between arm-rounds, outside every timed window (M7).
# - The GPU's busy level is read at VM-boot boundaries.
# - `m_thermal` runs only at VM-boot boundaries. It takes about 2 s and is never inside a timed window.
#
# **Recorded as found, not changed.**
#
# - the Wi-Fi radio (D9);
# - `net.bridge.bridge-nf-call-iptables` and its companions, and the size of the nf_tables ruleset (R39 loads
#   `br_netfilter` at boot; R36 did not);
# - `kernel.randomize_va_space` (D12);
# - `CONFIG_HZ` and the tick handler;
# - `/proc/interrupts`, at each board boot's start and end;
# - THP;
# - the scheduler, EEVDF on 6.8.
#
# 5. Predictions, with thresholds, fixed before any data
#
# They are written here and copied into the harness header, which is committed before any run, smoke runs
# included. They are not to be amended. A smoke run's data is never scored.
#
# 5.1 Margin and scoring
#
# - **The margin is m = 3 µs** for every contrast and for the floor.
#   - Earlier A6 pre-registrations used ±2 µs at p50 for "does not change" in a level within one boot
#     (`run-confine.sh` P4, `run-metal.sh` P4).
#   - A contrast is the difference of two arm-round p50s, so its round noise is about √2 times a level's.
#     ±2 × √2 rounds up to ±3.
# - **The intervals.** Each is distribution-free over the k unit values of the effect:
#   - **I95**, the narrowest symmetric order-statistic pair with coverage of at least 95%:
#     - k = 12: d(3)–d(10), 96.1%;
#     - k = 24: d(7)–d(18), 97.7%.
#   - **I999**, the narrowest pair with coverage of at least 99.9%:
#     - k = 12: d(1)–d(12), the min–max band, 99.95%;
#     - k = 24: d(4)–d(21), 99.97%.
# - **The verdicts.**
#   - **HELD:** I95 lies wholly inside [−m, +m].
#   - **REFUTED:** I999 lies wholly outside [−m, +m].
#   - **UNRESOLVED:** neither. The median and both intervals are printed.
#   - So a HELD is an equivalence claim at the I95 level. Under the intersection–union principle, it needs
#     no adjustment when all the cells must hold.
#   - A REFUTED needs the strict interval. The scored family is twelve cells (P1 and P2 four each, P3 three,
#     C1 one), each missing at most 0.05%, so by Bonferroni a false REFUTED anywhere has a chance under 1%.
#
# 5.2 The predictions
#
# - **P1, arm order (H1).** For each of `p50(A)`, K1, K2 and K3, the order effect is within ±3 µs.
#   - The order effect is the median over the k = 24 VM boots of ½[(K_RF + K_RR) − (K_FF + K_FR)].
#   - The subscripts are (O, L).
#   - Scored per outcome, four verdicts.
# - **P2, host-side layout (H1).** The same, for the layout effect ½[(K_FR + K_RR) − (K_FF + K_RF)].
#   Four verdicts.
# - **P3, VM setup (H1).** For each of K1, K2 and K3, the S effect is within ±3 µs.
#   - The S effect is the median, over the k = 12 adjacent F–R pairs (VM boots 1–2 and 3–4 of every board
#     boot), of V(R) − V(F).
#   - V is the mean of a VM boot's four scored rounds. They are one per cell, so the cells balance.
#   - The board boot's shift cancels within a pair.
#   - Three verdicts.
# - **C1, control (scored, not a gate).** The S effect on `p50(A)` is within ±3 µs. Arm A does not touch
#   the VM.
#   - A REFUTED C1 means something that changes between VM boots reaches a path without the guest: drift,
#     or the R VM boots disturbing the host. It is reported beside P3.
#   - It does not void P3.
# - **P4, where the level lives (H2).**
#   - φ = σ²_vm / (σ²_vm + σ²_board) for `Lv`, estimated from the **F** VM boots only. Those are VM boots
#     whose controllable setup is identical, so σ²_vm there is what a relaunch alone re-draws. The rule is
#     in section 7.4.
#   - **HELD** if the bootstrap's 2.5% bound is at least 0.5. **REFUTED** if its 97.5% bound is below 0.5.
#     **UNRESOLVED** otherwise.
#   - With six board boots, φ resolves only if one level clearly dominates (section 11). An UNRESOLVED P4 is
#     reported as such and not re-thresholded.
#
# 6. Checks
#
# The checks are about the manipulation and the platform, never about an outcome. A prediction that rests
# on a failed check prints VOID.
#
# **The rule from the campaign item.** A prediction is never guarded by a check that fails when the
# prediction is false.
#
# - Nothing here checks a contrast, a level, a tail or a variance component.
# - The `-boots` record's void P4 (a tail count guarding a median) is the mistake this rules out.
# - There is deliberately no check of the form "the fixed reference reproduces" or "K2 is near zero".
#
# | check | what it reads | guards |
# |---|---|---|
# | M1 | Every scored arm-round complete (1000 timed after 200 warm-up), and no stall: a stall stops the run,
#     as in the ladder. | all |
# | M2 | Every launch's personality read back (ADDR_NO_RANDOMIZE set in fixed-layout launches, clear in random
#     ones), its `/proc/PID/environ` size equal to the schedule's, and `startstack` (`/proc/PID/stat` field
#     28) recorded. | P2, P3 |
# | M3 | `order.log` and the cell order equal the schedule for every round. | P1, P2 |
# | M4 | Every QEMU thread's affinity, by name (`THREAD_NAMES=1`), equals its VM boot's assignment before and
#     after every round; and thread-CPU samples taken between arm-rounds show no thread off its core. | P3, P4
#     |
# | M5 | Platform: governor `performance` and re-checked, c7 disabled, the confinement read back, Docker's
#     three units stopped and the stamp's platform object clean, `halt_poll_ns` and companions unchanged,
#     nvpmodel mode 1, the GPU idle, the same image hash in every VM boot. | all |
# | M6 | No SSH login accepted during any round (the journal; `logins.txt`). | all |
# | M7 | EMC: every between-arm-round read equals the first read of that board boot. A differing arm-round is
#     flagged and kept. If more than 5% of arm-rounds are flagged, all predictions are VOID. | all |
# | M8 | Each board boot: `reset_reason` and pstore read first; uptime of at least 600 s at the first VM boot;
#     the shipped command line (no `isolcpus=`, no `irqaffinity=`). | all |
# | M9 | The schedule file's sha256 equals the committed one. | all |
#
# **On M2 and the set-user-ID trap.** By the Linux source (`PER_CLEAR_ON_SETID`), a set-user-ID exec
# clears ADDR_NO_RANDOMIZE. So in the namespace monitor's chain, `setarch -R` must come after `sudo` and
# `ip netns exec`, never before them. M2 is what catches it if this is got wrong.
#
# 7. Analysis
#
# The rules are fixed here and applied by the report script.
#
# 7.1 Per arm-round and per round
#
# - Per arm-round: p50, p99 and max of the 1000 timed samples.
# - Per round: K1, K2, K3, `Lv` and `p50(A)` from that round's four arm-rounds.
# - Round r = 0 is never used.
#
# 7.2 P1 and P2
#
# - Per VM boot, the four cells' values give the order effect, the layout effect and their interaction
#   (½[(K_RR − K_RF) − (K_FR − K_FF)], unscored).
# - The k = 24 values per effect and outcome give the median, I95, I999 and the min–max band.
#
# 7.3 P3 and C1
#
# - Per adjacent pair, V(R) − V(F). Then the median, I95, I999 and the min–max band over the 12 pairs.
# - Half of the pairs have F first and half R first. The position-in-pair difference is reported, unscored.
#
# 7.4 P4
#
# 1. **Data.** `Lv` per round in the 12 F VM boots (2 per board boot, 4 rounds each).
# 2. **Remove the cells' fixed effects.** Subtract from each round its cell's deviation: the cell's median
#    over these rounds minus their overall median.
# 3. **Balanced nested ANOVA by moments.** Board boots (df 5) contain VM boots (df 6), which contain rounds
#    (df 36):
#    - σ²_round = MS_round;
#    - σ²_vm = max(0, (MS_vm − MS_round) / 4);
#    - σ²_board = max(0, (MS_board − MS_vm) / 8);
#    - φ as in P4.
#    This is `boots_report.py`'s method, extended by one level.
# 4. **Interval.** Resample the six board boots with replacement, whole, with their VM boots and rounds;
#    10 000 resamples from the schedule's seed; the 2.5% and 97.5% percentiles. This resamples at the top
#    level only, as the nested structure requires.
# 5. **Undefined resamples.** A resample with σ²_vm = σ²_board = 0 is undefined. Such resamples are counted
#    and excluded. If more than 10% are undefined, P4 is UNRESOLVED.
# 6. **A known weakness, stated in advance.** The F VM boots are positions 1 and 4 in F R R F board boots
#    and positions 2 and 3 in R F F R ones. Drift within a board boot's session inflates σ²_vm in the
#    first kind. The split by pattern is reported (U1).
#
# 7.5 What "resolved" rests on
#
# - A P1–P3 or C1 verdict rests on I95 (HELD) or I999 (REFUTED), with the stated coverage for its k.
# - P4 rests on the board-boot bootstrap's 95% percentile interval.
# - The min–max band is printed beside every effect, for comparability with the records, and is named as
#   what it is. At k = 12 it is the 99.95% interval, and it is the same as I999.
# - A result printed without its interval and its k is not a result of this design.
#
# 7.6 Unscored (reported, never decisive)
#
# - **U1. Variance components.** The section 7.4 decomposition for R VM boots, and for K1–K3, in each
#   regime. Does setup randomisation add variance at the VM level? Also the split by S pattern (7.4, step
#   6).
# - **U2. Position effects in O-random rounds.** For each arm and position 1–4: the median over those rounds
#   of (the arm's p50 at that position minus its mean in that VM boot).
# - **U3. Placement among R VM boots.** K1 and `Lv` by which thread group sat on core 0: vCPU 0, vCPU 1 or
#   the rest. This is 12 VM boots and descriptive only.
# - **U4. Layout against outcome in L-random rounds.** `p50(A)` and K1–K3 against E mod 64, E mod 4096 and
#   `startstack`'s offset within its page, as rank correlations. This is Mytkowicz's periodicity check.
# - **U5. KVM.** The halt-poll success share, blocked wake-ups per exchange, and each QEMU thread's run time,
#   per cell and regime.
# - **U6. Tails.** Per arm and cell: p99 and the per-round maximum as k-sample sets (min, median and max of
#   the k maxima), and the tail's share of variance at the board and VM levels.
# - **U7. Autocorrelation.** Lag-1 and lag-10 rank autocorrelation within arm-rounds, by regime.
# - **U8. Spread.** The round-to-round median absolute deviation of K1–K3 in the all-fixed cell against the
#   all-random cell. Does one fixed setup understate the spread?
#
# 7.7 Reporting
#
# - Follow `docs/measurement-design.md` §3.6:
#   - the headline is the median of the k round values with the min–max band, the quantile tables below
#     it;
#   - no tail statistic without its k;
#   - "largest observed value", never "worst case";
#   - a per-arm configuration table.
# - Every page carries this label: *L4T R39, kernel 6.8.12-1021-tegra, QEMU 8.2.2, a robustness experiment;
#   no figure here is comparable with any R36 record or is an R39 baseline*.
# - The record goes to `a6-results-unpublished`, never to `main`.
#
# 12. What it would NOT show
#
# - **No R39 baseline.** It is not a re-baseline of A6, and no level here is comparable with any R36 record.
#   Its F cells are the design's reference, not "the A6 figure on R39".
# - **Not the A6 default's levels.** Every VM boot pins QEMU one thread group per core, where the A6 records
#   pinned the threads as a set (D4). Robustness of the contrasts under one pinning style is not shown for
#   the other.
# - **Not why a boot sets the level.** P4 can place it at the VM boot or the board boot, and nothing more.
#   KASLR, DRAM training, physical placement and driver state stay unseparated.
# - **S's two parts are aliased.** S bundles QEMU's layout with the vCPUs' assignment, so a moved P3 cannot
#   be pinned on either one. U3 and U4 only hint.
# - **No code layout.** Link order and text alignment of the native and guest monitors are left out (D8).
#   Nor is the guest's own layout: the IFS is fixed.
# - **Robust only within the ranges varied:**
#   - pads of 0 to 4080 bytes;
#   - ASLR as this kernel draws it;
#   - six permutations;
#   - one confinement layout;
#   - one arm set over TCP.
# - **No other regime.** No other spacing (the polled 0.2 ms regime), path (UDP, shared memory, the
#   doorbell, SOME/IP), load arm, or arrival process.
# - **No tail claim.** Tails are described (U6), never predicted.
# - **A HELD means "within ±3 µs at the stated interval".** It does not mean zero.
# - **A Python instrument.** Layout effects on `latency_probe.py` need not match those on the C++
#   `someip_vprobe`.
# - **No isolation result** and no freedom-from-interference, real-time or safety claim. SDP 8.0 is not
#   QNX OS for Safety, and the KVM boot uses our startup, which is not a QNX-supported configuration.
# - **One board.** One host. A second host's bias need not match this one's, which is Mytkowicz's own
#   finding.
#
# THE SCHEDULE. Every draw of section 4.5 comes from the master seed 979784927940495478, drawn once with
# Python's secrets.randbelow(2**63) on 2026-10-17, before this header was committed:
#     python3 randomise_schedule.py --seed 979784927940495478 --out schedule.txt
# writes the schedule file, whose sha256 is
#     0da177e5aaeadc77511bf1927de5fa0017133bc83863a9679875adf3712119b9
# This harness refuses any other file (M9): it re-derives the file from its own seed and compares the hash
# before it reads a line of it. The report checks the hash again, and order.log, the stamps and the
# read-backs against the file, line for line. The smoke board boot is b0 in the same file (one VM boot
# per regime, two rounds each, never scored); b1 .. b6 are the scored board boots.
#
# THE IMAGE, confirmed from its build file as section 4.3 asks: ifs-stamp.bin. Its build file
# (ipc-test/qnx-safety-monitor/ifs-stamp.build) starts the plain monitor on :7100 in the image's own
# startup script and stages qnx-echo-server-net, which the disk's post_start.custom
# (scripts/orin/qnx-safety-vm-post_start.custom) starts on TCP :7000. That is also how ifs-kick.bin gets
# its :7000: neither build file starts the echo server itself. So both serve arm C alike, and
# ifs-stamp.bin is the one used: the boots records ran it, and it needs no ivshmem device or virtio
# console. Its other services (the UDP rungs and the stamping monitor on :7103) run alike in every VM
# boot and are asked nothing. The harness refuses an IFS_BIN by any other name, and the stamp of every VM
# boot holds the image's hash.
#
# THE NATIVE MONITOR is Gate 2's, ~/gate2/bin/20261009T221811Z/monitor-native: its
# monitor-native.source-sha256 must equal the hash of the monitor's sources at this harness's commit,
# computed as build-monitor-native.sh computes it, or the run refuses. A fresh build is allowed only
# before the session, and a reboot follows it.
#
# THE HARNESS runs ONE board boot (BOOT_TAG b0 .. b6); partition_cycle.sh reboots the board between
# board boots, with the owner at the plug, and never touches a boot entry. Its session for a board boot
# reads the boot id, reset_reason and pstore first, before the settle wait, the bridge and this harness,
# and stops on the boot the reboot was asked on, on a crash record in pstore, and on a reset_reason
# other than the planned reboot's, which the smoke boot b0 settles. In order:
#   1. reset_reason and pstore are read first, as root, and pstore is archived outside the record;
#      an unreadable one refuses; a dmesg-* record (an oops or a panic) in /sys/fs/pstore, or one in
#      systemd's archive that the last board boot's end did not mark seen (with no mark yet, any one:
#      a crash on the reboot into this boot is archived there at boot), stops the run;
#   2. everything that can refuse is checked before anything is changed: the schedule, a settled boot
#      (uptime >= 600 s) on the shipped command line that no board boot under OUT_BASE was recorded on
#      (each one a fresh boot, section 4.1), no oops in the kernel log, nvpmodel mode 1, the GPU idle,
#      no load, no QEMU, no monitor-native, no namespace, br0 and tap-qnx, the units free;
#   3. platform-quiesce.sh stop (a fixed state path), the governor pinned, c7 disabled, arm B's
#      namespace, then the confinement of section 4.6, then the harness itself onto core 5, the
#      auxiliary reader's core, and the board boot's first EMC read;
#   4. each VM boot in the schedule's order: QEMU through launch-qnx-kvm-bridged.sh with the VM
#      boot's layout (QEMU_LAYOUT, QEMU_PAD), started on the REST core, and its thread groups pinned
#      by name (QEMU_PIN, THREAD_NAMES=1), read back; the readiness check and the 30 s pause; round 0
#      and the scored rounds, each with both native monitors relaunched and read back, the arms in the
#      round's order, each probe launch read back during its warm-up, and between arm-rounds the KVM
#      snapshot, the QEMU thread-CPU sample and the EMC read; the governor re-checked; sync; QEMU
#      stopped;
#   5. every setting restored and read back before the run ends (and on any exit): the confinement
#      to 0-5 with its drop-ins removed, the namespace, c7, the governor, then platform-quiesce.sh
#      restore, the restore that must come before every reboot; the board boot is complete only once
#      the governor and the idle states read as they were before the pin and no drop-in is left.
# The record's files are listed in randomise_report.py's docstring; the report applies sections 5 to 7.
#
# DECIDED HERE, where the design leaves a choice:
#   - the fixed list for env -i is PATH=/usr/sbin:/usr/bin:/sbin:/bin and LC_ALL=C, nothing else, so a
#     launch's environment size is known from the schedule alone; A6PAD's value is E bytes of the
#     letter x; a drawn PYTHONHASHSEED is uniform over 0 .. 4294967295;
#   - each launch draws its own pad: the two monitors of a round each, and each probe launch;
#   - round 0 is tagged _s0 (lat-<arm>_s0.json), so no completeness check can count it;
#   - a launch's read-back is taken once its exec chain has reached the program, from core 5, as
#     root: for the probe that is meant to fall in its warm-up, outside the timed window; the report
#     flags a probe read-back that ended later than 200 x 2 ms = 400 ms after its launch, the earliest
#     the warm-up can end, and keeps it: a flag voids nothing;
#   - M4's thread-CPU sample is every QEMU thread's last CPU (/proc stat field 39) after every
#     arm-round. It must be its group's core for both vCPU threads, and for every other thread whose
#     schedstat run time rose in that arm-round's KVM snapshot (kvm-<arm>_r<k>.json; a thread born
#     during the arm-round counts from zero): a thread that slept from its pin through the arm-round
#     keeps the CPU it had before the pin, and it ran nowhere. A thread off its core with no entry at
#     the snapshot's end has no run-time record and fails M4. QEMU is started on the REST core, so a
#     thread is born on its group's core or is a vCPU's. M7's read is after every arm-round, and its
#     5% is of the scored arm-rounds, one flagged when its read differs from the board boot's first or
#     is missing; M6 counts the journal's accepted logins inside each round's window;
#   - M5 also fails on a test hook in force: boot.json records every path the host is read through,
#     and TEGRA ("hooks"), and a value other than the board's own fails it, as does a stamp whose tegra
#     is not 1 or whose proc and sys roots are not /proc and /sys; and on a stamp whose kernel, QEMU or
#     L4T release is not the label's (section 7.7). M8 also needs each board boot's boot id recorded,
#     and the six distinct;
#   - M1 also needs boot.json's complete, which this harness writes only once the restores are judged:
#     a board boot that stopped after its last VM boot stopped as a stalled one does. Each stamp's
#     s_regime, qemu_pad and qemu_pin must equal its schedule line (section 4.5): the pad under M2, the
#     pin under M4, and the regime, which names both of S's parts, under both;
#   - a percentile of P4's bootstrap is the nearest rank, x[ceil(p/100 * m)] of the m defined
#     resamples; each resample recomputes the whole estimator of 7.4, the cells' deviations (step 2)
#     included; a resample draws its board boots as int(random() * 6) from random.Random(the
#     schedule's bootstrap seed), so no Python version changes the interval;
#   - C1 is guarded by the checks whose row says "all": M2's and M4's rows name P2, P3 and P3, P4;
#   - U4 sets each outcome against the layout of the probe launch of the arm it adds (A for p50(A),
#     C for K1, D for K2, B for K3); "by regime" in U5 and U7 is S's;
#   - the stop rule's oops is a kernel log line with "Internal error: ", "Unable to handle kernel ",
#     "kernel BUG at" or "BUG: ", read at the start and at every VM boot's end;
#   - the run refuses when kernel.randomize_va_space is not 2, or when the harness's own shell runs
#     without ASLR (every launch inherits its personality): either would leave R's layout not random
#     with no read-back to show it. The setting is read, never changed (D12).
#
# USAGE, from the one SSH session that drives the board boot (the bridge set up after the reboot):
#     BOOT_TAG=b1 SCHEDULE=~/a6-randomise/schedule.txt bash run-randomise.sh
#     DRY=1 BOOT_TAG=b1 SCHEDULE=... bash run-randomise.sh     the board boot's plan, then exit
# OUT_BASE (default ~/a6-randomise) holds one directory per board boot, which must not exist yet.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE=shallow                  # before the library, which reads it when sourced: c7 off (section 4.6)
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

# The committed schedule (THE SCHEDULE above; M9).
MASTER_SEED=979784927940495478
SCHEDULE_SHA256=0da177e5aaeadc77511bf1927de5fa0017133bc83863a9679875adf3712119b9

# The design's values (sections 4.1-4.6). Not taken from the environment: a pre-registered harness
# runs what its header says.
N=1000
WARMUP=200
INTERVAL_MS=2
PORT=7100
ARM_C_PORT=7000
GUEST=192.168.100.10
NS=a6rand
NS_IP=192.168.100.20
VETH=veth-a6r
QEMU_CORES=0-2
CORE_MON=3
CORE_PROBE=4
CORE_AUX=5
CONF_CORES=3,5
SETTLE_S=600
READY_PAUSE_S=30
KVM_STATS=1                     # the VM's counters and QEMU's schedstat around every arm-round
SAMPLE_WINDOW=0                 # no sampler beside the timed windows
STALL_POLICY=refuse             # a stall stops the run, as in the ladder
FIFO_ARMS=""
PROBE_TIMEOUT_S=10
OOPS_RX='Internal error: |Unable to handle kernel |kernel BUG at|BUG: '
declare -A ARM_NAME=([A]=A-loopback [B]=B-bridge [C]=C-null [D]=D-guest)

BOOT_TAG="${BOOT_TAG:-}"
SCHEDULE="${SCHEDULE:-$HOME/a6-randomise/schedule.txt}"
OUT_BASE="${OUT_BASE:-$HOME/a6-randomise}"
IMG="${IMG:-$HOME/output}"
IFS_BIN="${IFS_BIN:-$IMG/ifs-stamp.bin}"
DISK="${DISK:-$IMG/disk-qemu}"
MON="${MON:-$HOME/gate2/bin/20261009T221811Z/monitor-native}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/randomise_report.py}"
GENERATOR="${GENERATOR:-$here/randomise_schedule.py}"
LAUNCHER="${LAUNCHER:-$here/launch-qnx-kvm-bridged.sh}"
QUIESCE="${QUIESCE:-$here/platform-quiesce.sh}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
QUIESCE_PATH="$STATE_HOME/platform-quiesce.state"   # one fixed path for every run (platform-quiesce.sh)
PSTORE_MARK="$STATE_HOME/a6-randomise.pstore-seen"  # the archived crash records at the last board boot's end
PSTORE_ARCHIVE="${PSTORE_ARCHIVE:-$HOME/a6-randomise-pstore}"   # outside the record: pstore may name access points
PSTORE_VAR="${PSTORE_VAR:-/var/lib/systemd/pstore}"
RESET_REASON="${RESET_REASON:-${SYS_ROOT:-/sys}/devices/platform/bus@0/c360000.pmc/reset_reason}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
DRY="${DRY:-0}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi

DROPIN_ROOT=/run/systemd/system.control     # where systemctl set-property --runtime writes its drop-ins
BOOT_DIR=""; VM_DIR=""; VM=""; VM_PID=""; QUIESCE_STATE=""; CONF_TOUCHED=0; NS_TOUCHED=0
MON_HOST_PID=""; MON_NS_PID=""; UNITS=""; ME=""; FIRST_VM=1
RESET_TEXT=""; PSTORE_SYS=""; PSTORE_LIST=""; BOOT_ID=""
declare -A GOV_WANT=() CST_WANT=()          # what the governor and idle-state restores must read back

# ---------------------------------------------------------------- the schedule
# The one line of the schedule that starts with $1, printed; 1 when there is not exactly one.
sched_line() {      # $1 = the line's first words, e.g. "probe b3 v2 r1 C "
	local got
	got="$(awk -v p="$1" 'index($0, p) == 1' "$SCHEDULE")"
	[ -n "$got" ] && [ "$got" = "${got%%$'\n'*}" ] || return 1
	printf '%s\n' "$got"
}
# The value of key=value token $2 on line $1.
kv() {              # $1 = line  $2 = key
	local t
	for t in $1; do
		case "$t" in "$2="*) printf '%s\n' "${t#*=}"; return 0 ;; esac
	done
	return 1
}

# ---------------------------------------------------------------- reading the host
allowed() { awk '/^Cpus_allowed_list:/ {print $2; exit}' "${PROC_ROOT:-/proc}/$1/status" 2>/dev/null; }
ms_since() { echo $(( ($(date +%s%N) - $1) / 1000000 )); }

# "udevd=L pid1=L shells=L;L|none": the confinement read-back of section 4.6.
conf_state() {
	local u s list="" p
	u="$(pgrep -o -x systemd-udevd)"
	for p in $(pgrep -x gnome-shell); do list="${list:+$list;}$(allowed "$p")"; done
	s="${list:-none}"
	echo "udevd=$(allowed "$u") pid1=$(allowed 1) shells=$s"
}

# One line per launch into readback.log: who, round, pid, the read-back, ms from launch.
readback_line() {   # $1 who  $2 round (r<k> or r-)  $3 pid  $4 launch time (ns)
	local ok=0
	m_launch_readback "$3" || ok=1
	echo "$1 $2 pid=$3 $RB t_ms=$(ms_since "$4")" >> "$VM_DIR/readback.log"
	[ "$ok" = 0 ] || say "WARNING: the read-back of $1 $2 has an unread field ($RB): M2 will fail"
	return 0
}

emc_line() {        # one line: "bpmp=HZ ccf=HZ", read as root on the auxiliary core
	local v
	v="$(taskset -c "$CORE_AUX" sudo -n sh -c 'a=$(cat "$1" 2>/dev/null); b=$(cat "$2" 2>/dev/null); echo "bpmp=${a:-unread} ccf=${b:-unread}"' \
		_ "$EMC_BPMP" "$EMC_CCF" 2>/dev/null)" || v=""
	echo "${v:-bpmp=unread ccf=unread}"
}

halt_line() {
	local p out=""
	for p in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
		out="$out $p=$(cat "${SYS_ROOT:-/sys}/module/kvm/parameters/$p" 2>/dev/null || echo NA)"
	done
	echo "${out# }"
}

gpu_pct() {
	if [ "$TEGRA" = 1 ]; then m_gpu_busy_pct; else echo 0; fi
}

oops_count() {      # kernel log lines of an oops; "unread" when the log cannot be read
	local t
	t="$(sudo -n dmesg 2>/dev/null)" || { echo unread; return 0; }
	printf '%s\n' "$t" | grep -cE "$OOPS_RX" || true
}

# ---------------------------------------------------------------- the launches (sections 4.2, 4.3)
CMD=()
# The command of a launch, from its schedule line ($1), for who $2 and the program and arguments that
# follow. LAYOUT_ENV_BYTES must equal the line's env=, or the schedule and the library disagree.
build() {           # $1 schedule line  $2 who  then: the program and its arguments
	local line="$1" who="$2" norand pad hs="-" env
	shift 2
	norand="$(kv "$line" norand)" && pad="$(kv "$line" pad)" && env="$(kv "$line" env)" \
		|| die "schedule line '$line' has no norand, pad or env"
	case "$who" in probe-*) hs="$(kv "$line" hashseed)" || die "schedule line '$line' has no hashseed" ;; esac
	m_layout_cmd "$norand" "$pad" "$hs"
	[ "$LAYOUT_ENV_BYTES" = "$env" ] \
		|| die "the schedule gives $who an environment of $env bytes, the library builds $LAYOUT_ENV_BYTES: they disagree"
	case "$who" in
		mon-host) CMD=(taskset -c "$CORE_MON" "${LAYOUT_CMD[@]}" "$@") ;;
		# setarch last, after sudo and ip netns exec: a set-user-ID exec clears ADDR_NO_RANDOMIZE
		mon-ns) CMD=(sudo -n ip netns exec "$NS" taskset -c "$CORE_MON" "${LAYOUT_CMD[@]}" "$@") ;;
		probe-*) CMD=(taskset -c "$CORE_PROBE" "${LAYOUT_CMD[@]}" "$@") ;;
		*) die "build: no launch '$who'" ;;
	esac
}

arm_dest() {        # $1 arm -> "host port"
	case "$1" in
		A) echo "127.0.0.1 $PORT" ;;
		B) echo "$NS_IP $PORT" ;;
		C) echo "$GUEST $ARM_C_PORT" ;;
		D) echo "$GUEST $PORT" ;;
	esac
}

arm_tag() {         # $1 arm  $2 round: round 0 is _s0, so no completeness check counts it
	if [ "$2" = 0 ]; then echo "${ARM_NAME[$1]}_s0"; else echo "${ARM_NAME[$1]}_r$2"; fi
}

probe_cmd() {       # $1 vm  $2 round  $3 arm  $4 the directory the result goes to
	local line dest host port tag
	line="$(sched_line "probe $BOOT_TAG v$1 r$2 $3 ")" || die "no schedule line for probe $BOOT_TAG v$1 r$2 $3"
	dest="$(arm_dest "$3")"; host="${dest% *}"; port="${dest#* }"
	tag="$(arm_tag "$3" "$2")"
	build "$line" "probe-$3" python3 "$PROBE" --host "$host" --port "$port" --n "$N" --warmup "$WARMUP" \
		--interval-ms "$INTERVAL_MS" --timeout-s "$PROBE_TIMEOUT_S" --proto tcp --tag "$tag" --out "$4/lat-$tag.json"
}

mon_cmd() {         # $1 vm  $2 round  $3 host|ns
	local line
	line="$(sched_line "mon $BOOT_TAG v$1 r$2 $3 ")" || die "no schedule line for mon $BOOT_TAG v$1 r$2 $3"
	build "$line" "mon-$3" "$MON" "$PORT"
}

# The launcher's environment words for a VM boot: its layout and its thread groups by name.
LAUNCH_ENV=()
vm_env() {          # $1 vm  $2 the console log
	local line s pad pin
	line="$(sched_line "vm $BOOT_TAG v$1 ")" || die "no schedule line for vm $BOOT_TAG v$1"
	s="$(kv "$line" S)" && pad="$(kv "$line" pad)" && pin="$(kv "$line" pin)" || die "schedule line '$line' is not whole"
	LAUNCH_ENV=("IFS_BIN=$IFS_BIN" "DISK=$DISK" "LOG=$2" THREAD_NAMES=1 SMP=2 "QEMU_PIN=$pin")
	if [ "$s" = F ]; then LAUNCH_ENV+=(QEMU_LAYOUT=fixed); else LAUNCH_ENV+=(QEMU_LAYOUT=random "QEMU_PAD=$pad"); fi
}

# For DRY=1 and the logs: a command with a pad shown by its length.
show() {
	local w out=""
	for w in "$@"; do
		case "$w" in A6PAD=*) w="A6PAD=x{$(( ${#w} - 6 ))}" ;; esac
		out="$out $w"
	done
	echo "${out# }"
}

# ---------------------------------------------------------------- the monitors and the probe
pid_alive() { [ -n "$1" ] && [ -d "/proc/$1" ]; }

mon_stop() {
	local i
	[ -n "$MON_HOST_PID" ] && kill "$MON_HOST_PID" 2>/dev/null
	[ -n "$MON_NS_PID" ] && sudo -n kill "$MON_NS_PID" 2>/dev/null
	for i in $(seq 1 50); do
		pid_alive "$MON_HOST_PID" || pid_alive "$MON_NS_PID" || break
		sleep 0.1
	done
	if pid_alive "$MON_HOST_PID" || pid_alive "$MON_NS_PID"; then
		echo "WARNING: a native monitor would not stop (host ${MON_HOST_PID:-none}, namespace ${MON_NS_PID:-none})" >&2
		return 1
	fi
	MON_HOST_PID=""; MON_NS_PID=""
	return 0
}

# Both native monitors, relaunched with round $2's layout and read back (section 4.2: relaunched every
# round in both regimes), then reached by a connection each.
mon_start() {       # $1 vm  $2 round
	local t0 p a0 i ok
	mon_stop || die "the round-$2 monitors cannot start: the last ones would not stop"
	mon_cmd "$1" "$2" host
	t0="$(date +%s%N)"
	"${CMD[@]}" > "$VM_DIR/monitor-host-r$2.log" 2>&1 &
	MON_HOST_PID=$!
	m_await_exec "$MON_HOST_PID" monitor-native || die "the host monitor's launch never reached monitor-native (see $VM_DIR/monitor-host-r$2.log)"
	readback_line mon-host "r$2" "$MON_HOST_PID" "$t0"
	mon_cmd "$1" "$2" ns
	t0="$(date +%s%N)"
	"${CMD[@]}" > "$VM_DIR/monitor-ns-r$2.log" 2>&1 &
	for i in $(seq 1 50); do
		for p in $(sudo -n ip netns pids "$NS" 2>/dev/null); do
			a0=""; IFS= read -r -d '' a0 2>/dev/null < "/proc/$p/cmdline" || true
			[ "${a0##*/}" = monitor-native ] && { MON_NS_PID="$p"; break 2; }
		done
		sleep 0.1
	done
	[ -n "$MON_NS_PID" ] || die "the namespace monitor never appeared in $NS (see $VM_DIR/monitor-ns-r$2.log)"
	readback_line mon-ns "r$2" "$MON_NS_PID" "$t0"
	for p in "127.0.0.1" "$NS_IP"; do
		ok=0
		for i in $(seq 1 50); do
			if timeout 1 bash -c "echo > /dev/tcp/$p/$PORT" 2>/dev/null; then ok=1; break; fi
			sleep 0.1
		done
		[ "$ok" = 1 ] || die "the native monitor at $p:$PORT does not answer in round $2"
	done
}

# One arm-round: the probe launched with its layout, read back once its exec chain reaches python3
# (during the warm-up), the KVM snapshot around it; afterwards the thread-CPU sample and the EMC read.
# Any probe failure, a stall included, stops the run (STALL_POLICY=refuse, as in the ladder).
arm_round() {       # $1 vm  $2 round  $3 arm
	local tag pid rc t0
	tag="$(arm_tag "$3" "$2")"
	probe_cmd "$1" "$2" "$3" "$VM_DIR"
	rm -f "$VM_DIR/lat-$tag.json" "$VM_DIR/stall-$tag.json"
	m_kvm_snap "$VM_DIR/kvm-$tag.json" before
	t0="$(date +%s%N)"
	"${CMD[@]}" >> "$VM_DIR/probe.log" 2>&1 &
	pid=$!
	if m_await_exec "$pid" python3; then
		readback_line "probe-$3" "r$2" "$pid" "$t0"
	else
		echo "probe-$3 r$2 pid=$pid personality=unread environ=unread startstack=unread maps=unread stack=unread t_ms=$(ms_since "$t0")" >> "$VM_DIR/readback.log"
	fi
	wait "$pid"; rc=$?
	m_kvm_snap "$VM_DIR/kvm-$tag.json" after
	[ "$rc" -eq 0 ] || die "probe failed on $tag (exit $rc) -- see $VM_DIR/probe.log; the run stops here"
	[ -s "$VM_DIR/lat-$tag.json" ] || die "probe exited 0 but wrote no file for $tag"
	m_qemu_threads "$QPID" | sed "s/^/round $2 after-$3 /" >> "$VM_DIR/cpu.log"
	echo "round $2 after-$3 $(emc_line)" >> "$VM_DIR/emc.log"
}

threads_line() {    # $1 round  $2 before|after
	m_qemu_threads "$QPID" | sed "s/^/round $1 $2 /" >> "$VM_DIR/threads.log"
	echo "round $1 $2 $(conf_state)" >> "$VM_DIR/confine.log"
}

# ---------------------------------------------------------------- the VM boot
vm_stop() {         # sync first: a panic in QEMU's teardown once lost unflushed files
	local i
	[ -n "$VM_PID" ] || return 0
	sync
	kill -TERM "$VM_PID" 2>/dev/null
	for i in $(seq 1 30); do pid_alive "$VM_PID" || break; sleep 0.5; done
	if pid_alive "$VM_PID"; then kill -KILL "$VM_PID" 2>/dev/null; sleep 1; fi
	if pid_alive "$VM_PID"; then echo "WARNING: QEMU $VM_PID would not stop" >&2; return 1; fi
	VM_PID=""
	sync
	return 0
}

# ---------------------------------------------------------------- the confinement (section 4.6)
set_units() {       # $1 core list
	local u
	CONF_TOUCHED=1
	for u in $UNITS; do sudo -n systemctl set-property --runtime "$u" "AllowedCPUs=$1" || return 1; done
}

conf_restore() {    # 0-5 explicitly, the drop-ins removed, systemd reloaded, udevd read back
	local u
	[ "$CONF_TOUCHED" = 1 ] || return 0
	set_units 0-5 2>/dev/null
	for u in $UNITS; do
		sudo -n rm -f "$DROPIN_ROOT/$u.d/50-AllowedCPUs.conf"
		sudo -n rmdir "$DROPIN_ROOT/$u.d" 2>/dev/null
	done
	sudo -n systemctl daemon-reload
	CONF_TOUCHED=0
	if [ "$(allowed "$(pgrep -o -x systemd-udevd)")" = 0-5 ]; then
		say "the units are back on 0-5, drop-ins removed"
	else
		echo "WARNING: udevd is not on 0-5 -- restore by hand: sudo systemctl set-property --runtime <unit> AllowedCPUs=0-5 for $UNITS" >&2
		return 1
	fi
}

ns_up() {
	NS_TOUCHED=1
	sudo -n ip netns add "$NS" || return 1
	sudo -n ip link add "$VETH" type veth peer name "$VETH-ns" || return 1
	sudo -n ip link set "$VETH" master br0 up || return 1
	sudo -n ip link set "$VETH-ns" netns "$NS" || return 1
	sudo -n ip netns exec "$NS" ip addr add "$NS_IP/24" dev "$VETH-ns" || return 1
	sudo -n ip netns exec "$NS" ip link set "$VETH-ns" up || return 1
	sudo -n ip netns exec "$NS" ip link set lo up
}

ns_down() {
	local p
	[ "$NS_TOUCHED" = 1 ] || return 0
	for p in $(sudo -n ip netns pids "$NS" 2>/dev/null); do sudo -n kill "$p" 2>/dev/null; done
	sudo -n ip netns del "$NS" 2>/dev/null
	sudo -n ip link del "$VETH" 2>/dev/null
	NS_TOUCHED=0
}

# boot.json, the board boot's own record: one key set to a JSON value.
bj() {              # $1 key  $2 JSON value
	python3 - "$BOOT_DIR/boot.json" "$1" "$2" <<'PY' || die "could not write $1 into boot.json"
import json, os, sys
p, k, v = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(p)) if os.path.exists(p) else {}
d[k] = json.loads(v)
tmp = p + ".tmp"
json.dump(d, open(tmp, "w"), indent=1, sort_keys=True)
os.replace(tmp, p)
PY
}
jstr() { python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }

# boot.json's "hooks": every path the host is read through, and TEGRA. The report fails M5 on any value
# other than the board's own: a figure read through a test's stand-in is not the board's.
record_hooks() {
	bj hooks "{\"proc_root\": $(jstr "${PROC_ROOT:-/proc}"), \"sys_root\": $(jstr "${SYS_ROOT:-/sys}"), \"reset_reason\": $(jstr "$RESET_REASON"), \"pstore_var\": $(jstr "$PSTORE_VAR"), \"emc_bpmp\": $(jstr "$EMC_BPMP"), \"emc_ccf\": $(jstr "$EMC_CCF"), \"sysfs_cpu\": $(jstr "$SYSFS_CPU"), \"kvm_debugfs\": $(jstr "$KVM_DEBUGFS"), \"tegra\": $TEGRA}"
}

# What the governor and idle-state restores must read back: each value the pin and c7 changed, as it
# was. Taken right after both are applied (the library clears its own copies when it restores).
remember_restores() {
	local k
	for k in "${!GOV_ORIG[@]}"; do GOV_WANT["$k"]="${GOV_ORIG[$k]}"; done
	for k in "${!CSTATE_ORIG[@]}"; do CST_WANT["$k"]="${CSTATE_ORIG[$k]}"; done
	return 0
}

# Section 10: the board reads as found before any reboot. 0 when every governor and idle state reads
# as it was before the pin and no confinement drop-in is left; 1 with every miss named.
restores_judged() {
	local k now u want bad=0
	for k in "${!GOV_WANT[@]}" "${!CST_WANT[@]}"; do
		now="$(cat "$k" 2>/dev/null)"
		if [ -n "${GOV_WANT[$k]+x}" ]; then want="${GOV_WANT[$k]}"; else want="${CST_WANT[$k]}"; fi
		[ "$now" = "$want" ] || { echo "NOT RESTORED: $k reads '$now', was '$want'" >&2; bad=1; }
	done
	for u in $UNITS; do
		[ ! -e "$DROPIN_ROOT/$u.d/50-AllowedCPUs.conf" ] \
			|| { echo "NOT RESTORED: the drop-in $DROPIN_ROOT/$u.d/50-AllowedCPUs.conf is still there" >&2; bad=1; }
	done
	return "$bad"
}

cleanup() {
	# Only the harness restores the board: a group signal that lands in a child's fork-to-exec window can
	# run the inherited trap, and this, in the forked copy as well.
	[ "$BASHPID" = "$$" ] || return 0
	say "cleanup"
	mon_stop
	vm_stop
	ns_down
	conf_restore
	m_cstate_restore
	# After QEMU is stopped and before the governor is restored (platform-quiesce.sh, HARNESS USE).
	if [ -n "$QUIESCE_STATE" ]; then
		bash "$QUIESCE" restore "$QUIESCE_STATE" >> "${BOOT_DIR:-/tmp}/quiesce.log" 2>&1 \
			|| echo "WARNING: platform-quiesce restore failed (see ${BOOT_DIR:-/tmp}/quiesce.log): restore before any reboot" >&2
		QUIESCE_STATE=""
	fi
	m_governor_restore
}

# Tests source the functions above and stop here; a run never sets this.
if [ "${A6R_LIB_ONLY:-0}" = 1 ]; then
	return 0 2>/dev/null
	die "A6R_LIB_ONLY=1 is for sourcing this harness's functions in a test, never for a run"
fi

# ---------------------------------------------------------------- preflight: what needs no board
[ $# -eq 0 ] || die "positional arguments are not read (set BOOT_TAG=, SCHEDULE= in the environment); got: $*"
case "$BOOT_TAG" in b[0-6]) ;; *) die "BOOT_TAG='$BOOT_TAG' is not a board boot of the schedule (b0, the smoke, or b1 .. b6)" ;; esac
case "$DRY" in 0|1) ;; *) die "DRY='$DRY' must be 0 or 1" ;; esac
case "$TEGRA" in 0|1) ;; *) die "TEGRA='$TEGRA' is not 0 or 1" ;; esac
[ -r "$SCHEDULE" ] || die "the schedule $SCHEDULE is not readable: write it with randomise_schedule.py --seed $MASTER_SEED"
[ -r "$GENERATOR" ] || die "missing: $GENERATOR"
got="$(python3 "$GENERATOR" --verify "$SCHEDULE" 2>&1)" || die "the schedule does not re-derive from its own seed: $got"
[ "${got%% *}" = "$SCHEDULE_SHA256" ] \
	|| die "the schedule's sha256 is ${got%% *}, the committed one is $SCHEDULE_SHA256 (M9): it is not this harness's schedule"
[ "$(sed -n 's/^env //p' "$SCHEDULE")" = "${M_FIXED_ENV[*]}" ] || die "the schedule's fixed list is not the library's"
BOOT_LINE="$(sched_line "boot $BOOT_TAG ")" || die "the schedule has no board boot $BOOT_TAG"
read -r _w _t KIND PATTERN <<< "$BOOT_LINE"
VMS="$(awk -v p="vm $BOOT_TAG " 'index($0, p) == 1 {print substr($3, 2)}' "$SCHEDULE" | tr '\n' ' ')"
VMS="${VMS% }"
[ "${#PATTERN}" = "$(echo $VMS | wc -w)" ] || die "the schedule's board boot $BOOT_TAG is not whole"
BOOT_DIR="$OUT_BASE/$BOOT_TAG"

if [ "$DRY" = 1 ]; then
	echo "plan: board boot $BOOT_TAG ($KIND), S pattern $PATTERN, schedule sha256 $SCHEDULE_SHA256"
	for v in $VMS; do
		vd="$BOOT_DIR/v$v"
		vm_env "$v" "$vd/guest-console.log"
		echo "plan: v$v launch: $(show "${LAUNCH_ENV[@]}") bash $LAUNCHER"
		for r in $(awk -v p="round $BOOT_TAG v$v " 'index($0, p) == 1 {print substr($4, 2)}' "$SCHEDULE"); do
			line="$(sched_line "round $BOOT_TAG v$v r$r ")"
			echo "plan: v$v r$r $(kv "$line" cell) order $(kv "$line" order)"
			for who in host ns; do
				mon_cmd "$v" "$r" "$who"
				echo "plan: v$v r$r mon-$who env=$LAYOUT_ENV_BYTES: $(show "${CMD[@]}")"
			done
			for a in $(kv "$line" order | tr ',' ' '); do
				probe_cmd "$v" "$r" "$a" "$vd"
				echo "plan: v$v r$r probe-$a env=$LAYOUT_ENV_BYTES: $(show "${CMD[@]}")"
			done
		done
	done
	exit 0
fi

# ---------------------------------------------------------------- preflight: the first reads
# reset_reason and pstore before anything else runs (M8), as root; pstore is archived outside the
# record, because its files may name access points.
RESET_TEXT="$(sudo -n cat "$RESET_REASON" 2>/dev/null | tr -cd '[:print:]')" || RESET_TEXT=""
# Each read's own status, never a pipeline's: an unreadable pstore is not an empty one.
PSTORE_OK=1; VAR_OK=1
PSTORE_SYS="$(sudo -n ls -A "${SYS_ROOT:-/sys}/fs/pstore" 2>/dev/null)" || PSTORE_OK=0
PSTORE_SYS="$(printf '%s' "$PSTORE_SYS" | tr '\n' ' ')"
if [ -e "$PSTORE_VAR" ]; then           # systemd makes its archive when it first archives a record
	PSTORE_LIST="$(sudo -n find "$PSTORE_VAR" -mindepth 1 -maxdepth 2 -printf '%P\n' 2>/dev/null)" || VAR_OK=0
	PSTORE_LIST="$(printf '%s\n' "$PSTORE_LIST" | sort | tr '\n' ' ')"
	PSTORE_LIST="${PSTORE_LIST% }"
fi
[ -n "$RESET_TEXT" ] || die "cannot read reset_reason ($RESET_REASON) with sudo -n: M8 needs it read first"
[ "$PSTORE_OK" = 1 ] || die "cannot read ${SYS_ROOT:-/sys}/fs/pstore with sudo -n: M8 needs pstore read first, and an unreadable one is not an empty one"
[ "$VAR_OK" = 1 ] || die "cannot read systemd's pstore archive $PSTORE_VAR with sudo -n: a crash record archived there would go unseen"
say "reset_reason: $RESET_TEXT; pstore: ${PSTORE_SYS:-empty}; archived crash records: $(echo $PSTORE_LIST | wc -w)"
# Every record is archived. A dmesg-* record -- what the kernel writes on an oops or a panic; a
# console-* record can be left by any boot -- stops the run, here or new in systemd's archive since
# the last board boot ended.
if [ -n "$PSTORE_SYS" ]; then
	a="$PSTORE_ARCHIVE/$BOOT_TAG-$(date -u +%Y%m%dT%H%M%SZ)"
	mkdir -p "$a" && sudo -n cp -a "${SYS_ROOT:-/sys}/fs/pstore/." "$a/" 2>/dev/null
	say "pstore held $PSTORE_SYS: archived in $a"
	for f in $PSTORE_SYS; do
		case "$f" in dmesg-*) die "pstore holds a crash record ($f), archived in $a: the stop rule -- the owner reads it and decides" ;; esac
	done
fi
if [ -r "$PSTORE_MARK" ]; then
	for f in $PSTORE_LIST; do
		case "${f##*/}" in dmesg-*) ;; *) continue ;; esac
		grep -qxF -- "$f" "$PSTORE_MARK" \
			|| die "a crash record appeared in $PSTORE_VAR since the last board boot ended ($f): the stop rule -- the owner reads it and decides"
	done
else
	# No board boot has marked the archive seen yet, so a record there cannot be told old from new: a
	# crash on the reboot into this boot is archived at boot, not left in /sys/fs/pstore.
	for f in $PSTORE_LIST; do
		case "${f##*/}" in
			dmesg-*) die "systemd's archive $PSTORE_VAR holds a crash record ($f), and no board boot has marked the archive seen ($PSTORE_MARK is absent): a crash on the reboot into this boot is archived there at boot, so it stops the run -- the owner reads it and decides; to go on, mark what is there seen: sudo find $PSTORE_VAR -mindepth 1 -maxdepth 2 -printf '%P\n' | sort > $PSTORE_MARK" ;;
		esac
	done
fi

# ---------------------------------------------------------------- preflight: what can refuse
UPTIME0="$(cut -d' ' -f1 "${PROC_ROOT:-/proc}/uptime" | cut -d. -f1)"
case "$UPTIME0" in ''|*[!0-9]*) die "cannot read the uptime" ;; esac
[ "$UPTIME0" -ge "$SETTLE_S" ] || die "the boot is ${UPTIME0} s old, under $SETTLE_S s: let it settle (M8)"
TOKENS="$(tr ' ' '\n' < "${PROC_ROOT:-/proc}/cmdline" | grep -cE '^(isolcpus|irqaffinity)=')" || true
[ "$TOKENS" = 0 ] || die "this boot is not on the shipped command line ($TOKENS isolcpus=/irqaffinity= token(s)) (M8)"
# R's layout is ASLR as the kernel draws it: read, never changed (D12). With it off system-wide, or
# off for this shell (a personality is inherited by every launch), R would not be random at all and
# no read-back of a personality bit could show it.
RVA="$(cat "${PROC_ROOT:-/proc}/sys/kernel/randomize_va_space" 2>/dev/null)"
[ "$RVA" = 2 ] || die "kernel.randomize_va_space is '${RVA:-unread}', not 2: the random layout would not be random (it is read, never changed)"
PERS="$(cat "${PROC_ROOT:-/proc}/self/personality" 2>/dev/null)"
case "$PERS" in ''|*[!0-9a-fA-F]*) die "cannot read this shell's personality" ;; esac
[ $(( 16#$PERS & 0x0040000 )) -eq 0 ] || die "this shell runs without ASLR (personality $PERS): every launch would inherit it; start it without setarch -R"
[ ! -e "$BOOT_DIR" ] || die "$BOOT_DIR exists: a board boot is recorded once (a lost one is re-run under a fresh OUT_BASE)"
# Each board boot is a fresh boot (section 4.1): a boot another board boot was recorded on refuses.
BOOT_ID="$(tr -cd '0-9a-f-' 2>/dev/null < "${PROC_ROOT:-/proc}/sys/kernel/random/boot_id")" || BOOT_ID=""
[ -n "$BOOT_ID" ] || die "cannot read this boot's id: a board boot must be told from the others (section 4.1)"
for f in "$OUT_BASE"/b[0-6]/boot.json; do
	[ -e "$f" ] || continue
	[ -r "$f" ] || die "cannot read $f: whether it was recorded on this boot cannot be told"
	! grep -qF "\"boot_id\": \"$BOOT_ID\"" "$f" \
		|| die "board boot $(basename "$(dirname "$f")") was recorded on this boot ($BOOT_ID): each board boot is a fresh boot (section 4.1) -- reboot first"
done
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for f in "$PROBE" "$REPORT" "$LAUNCHER" "$QUIESCE" "$IFS_BIN" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
[ "${IFS_BIN##*/}" = ifs-stamp.bin ] || die "IFS_BIN is ${IFS_BIN##*/}: the image confirmed for this design is ifs-stamp.bin (THE IMAGE)"
[ -x "$MON" ] || die "$MON missing -- Gate 2's native monitor (THE NATIVE MONITOR)"
SRC_ROOT="$here/../../ipc-test"
MON_SRC="$(cat "$SRC_ROOT/qnx-safety-monitor/monitor.c" "$SRC_ROOT/common/shm_map_posix.c" "$SRC_ROOT/common/ivshm_client.c" \
	"$SRC_ROOT/common/frame.h" "$SRC_ROOT/common/frame_io.h" "$SRC_ROOT/common/shm_chan.h" "$SRC_ROOT/common/shm_map.h" \
	"$SRC_ROOT/common/ivshm_client.h" 2>/dev/null | sha256sum | cut -d' ' -f1)"
[ "$(cat "$MON.source-sha256" 2>/dev/null)" = "$MON_SRC" ] \
	|| die "$MON was not built from the monitor's sources at this commit ($MON.source-sha256 vs ${MON_SRC:0:16}): rebuild before the session, then reboot"
NVP="$(sudo -n nvpmodel -q 2>/dev/null | tr -d '\r' | awk 'NF {last=$NF} END {print last}')"
[ "$NVP" = 1 ] || die "nvpmodel reads mode '${NVP:-unread}', not 1: this harness never switches it (section 4.6)"
for x in $LOADS; do [ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this design runs no load"; done
[ "$(gpu_pct)" = 0 ] || die "GR3D is not 0% at preflight -- nothing may touch the GPU"
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a qemu-system-aarch64 is already running; this harness launches its own"
[ -z "$(m_pids_of monitor-native)" ] || die "a monitor-native is already running; it would answer arm A in place of this run's"
! ip netns list 2>/dev/null | grep -qw "$NS" || die "the namespace $NS exists -- a leftover; remove it first"
! ip link show "$VETH" >/dev/null 2>&1 || die "$VETH exists -- a leftover; remove it first"
ip link show br0 >/dev/null 2>&1 || die "br0 does not exist: run scripts/orin/setup-bridge-orin.sh after the reboot"
ip link show tap-qnx 2>/dev/null | grep -q 'master br0' || die "tap-qnx is not enslaved to br0: run setup-bridge-orin.sh"
[ -r /dev/kvm ] || die "/dev/kvm is not readable: the guest cannot run under KVM (is the login in the kvm group?)"
O="$(oops_count)"
[ "$O" = 0 ] || die "the kernel log holds $O oops line(s), or cannot be read: the stop rule -- the owner decides"
sudo -n journalctl -n 1 -u ssh > /dev/null || die "sudo -n journalctl does not work: logins could not be counted (M6)"
[ -r "${SYS_ROOT:-/sys}/module/kvm/parameters/halt_poll_ns" ] || die "halt_poll_ns is not readable"
ME="$(basename "$(cut -d: -f3 /proc/self/cgroup)")"
case "$ME" in session-*.scope) ;; *) die "the harness is not in a session scope ($ME)" ;; esac
UNITS="system.slice init.scope $(systemctl list-units 'user@*.service' --no-legend | awk '{print $1}') $(systemctl list-units --type=scope --state=running --no-legend | awk '{print $1}' | grep '^session-' | grep -vx "$ME")"
UNITS="$(echo $UNITS)"
for u in $UNITS; do
	case "$(systemctl show -p AllowedCPUs --value "$u")" in ""|0-5) ;; *) die "$u already has AllowedCPUs set -- someone else changed it" ;; esac
done
for s in /proc/[0-9]*/task/[0-9]*/status; do
	c="$(awk '/^Cpus_allowed_list/ {print $2}' "$s" 2>/dev/null)"
	[ -n "$c" ] && [ "$c" != 0-5 ] || continue
	d="${s%/status}"
	cg="$(cut -d: -f3 "$d/cgroup" 2>/dev/null)"
	case "$cg" in /|*"$ME"*|"") ;; *) die "a task in $cg has CPU affinity $c: restoring 0-5 would lose it" ;; esac
done
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "monitor=$CORE_MON" "probe=$CORE_PROBE" "aux=$CORE_AUX"

# ---------------------------------------------------------------- the board boot's changes
# A signal ends the run through the EXIT trap. An SSH session without a pty that drops sends no HUP: the
# next write gets SIGPIPE, and cleanup's own first line would meet the same broken pipe, so what is left
# to write goes to a file first.
trap cleanup EXIT
trap 'exit 143' TERM; trap 'exit 129' HUP; trap 'exit 130' INT
trap 'exec >> "$HOME/a6-randomise-hangup.log" 2>&1; exit 141' PIPE
mkdir -p "$BOOT_DIR" || die "cannot create $BOOT_DIR"
bj experiment '"randomise"'
bj boot_tag "$(jstr "$BOOT_TAG")"
bj kind "$(jstr "$KIND")"
bj pattern "$(jstr "$PATTERN")"
bj schedule_sha256 "$(jstr "$SCHEDULE_SHA256")"
bj master_seed "$MASTER_SEED"
bj reset_reason "$(jstr "$RESET_TEXT")"
bj pstore "{\"sys\": $(python3 -c 'import json, sys; print(json.dumps(sys.argv[1].split()))' "$PSTORE_SYS"), \"archive\": $(python3 -c 'import json, sys; print(json.dumps(sys.argv[1].split()))' "$PSTORE_LIST")}"
bj first_reads true
bj uptime_preflight_s "$UPTIME0"
bj cmdline_tokens "$TOKENS"
bj boot_id "$(jstr "$BOOT_ID")"
bj units "$(jstr "$UNITS")"
bj vms "[${VMS// /, }]"
record_hooks

QUIESCE_STATE="$QUIESCE_PATH"
rc=0; bash "$QUIESCE" stop "$QUIESCE_PATH" >> "$BOOT_DIR/quiesce.log" 2>&1 || rc=$?
[ "$rc" != 3 ] || QUIESCE_STATE=""
[ "$rc" = 0 ] || die "platform-quiesce.sh stop exited $rc (see $BOOT_DIR/quiesce.log)"
m_governor_pin
m_cstate_apply
remember_restores
ns_up || die "arm B's namespace could not be set up"
set_units "$CONF_CORES" || die "could not confine the units to $CONF_CORES"
sleep 1
# The harness is the auxiliary reader: core 5, set after the confinement (turning the cpuset
# controller on resets the affinity of the tasks in the user's scopes).
taskset -pc "$CORE_AUX" $$ > /dev/null || die "could not move the harness onto core $CORE_AUX"
[ "$(_cpuset "$(allowed $$)")" = "$CORE_AUX" ] || die "the harness reads $(allowed $$), not core $CORE_AUX"
EMC0="$(emc_line)"
case "$EMC0" in *unread*) die "the EMC clock cannot be read ($EMC0): M7 needs it" ;; esac
bj emc_first "{\"bpmp\": \"$(echo "$EMC0" | sed 's/^bpmp=\([^ ]*\).*/\1/')\", \"ccf\": \"$(echo "$EMC0" | sed 's/.*ccf=//')\"}"
cat /proc/interrupts > "$BOOT_DIR/interrupts-start.txt" 2>/dev/null
REC="{\"randomize_va_space\": $(jstr "$(cat /proc/sys/kernel/randomize_va_space 2>/dev/null)"), \"thp_enabled\": $(jstr "$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null)"), \"thp_defrag\": $(jstr "$(cat /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null)")"
for b in bridge-nf-call-iptables bridge-nf-call-ip6tables bridge-nf-call-arptables; do
	REC="$REC, \"$b\": $(jstr "$(cat "/proc/sys/net/bridge/$b" 2>/dev/null || echo absent)")"
done
REC="$REC, \"nft_ruleset_lines\": $(jstr "$(sudo -n nft list ruleset 2>/dev/null | wc -l)")"
REC="$REC, \"tick_handler\": $(jstr "$(sudo -n cat /proc/timer_list 2>/dev/null | grep -m1 -oE 'tick_nohz_highres_handler|tick_sched_timer|tick_nohz_handler')")"
REC="$REC, \"kernel\": $(jstr "$(uname -r)"), \"confinement_at_start\": $(jstr "$(conf_state)")}"
bj recorded "$REC"
say "board boot $BOOT_TAG ($KIND, $PATTERN): quiesced, governor pinned, c7 off, namespace up, units on $CONF_CORES"

# ---------------------------------------------------------------- the VM boots
for v in $VMS; do
	VM="$v"
	m_prepare_out "$BOOT_DIR/v$v" "$BOOT_DIR"
	VM_DIR="$OUT"
	vline="$(sched_line "vm $BOOT_TAG v$v ")"
	R_LIST="$(awk -v p="round $BOOT_TAG v$v " 'index($0, p) == 1 {print substr($4, 2)}' "$SCHEDULE" | tr '\n' ' ')"
	K=$(( $(echo $R_LIST | wc -w) - 1 ))
	echo "start $(halt_line)" > "$VM_DIR/halt.log"
	echo "start $(gpu_pct)" > "$VM_DIR/gpu.log"
	m_thermal "v$v start" > "$VM_DIR/thermal.log"
	vm_env "$v" "$VM_DIR/guest-console.log"
	say "v$v: launching QEMU ($(show "${LAUNCH_ENV[@]}"))"
	t_launch="$(date +%s%N)"
	env "${LAUNCH_ENV[@]}" bash "$LAUNCHER" > "$VM_DIR/launch.log" 2>&1 < /dev/null; lrc=$?
	VM_PID="$(sed -n 's/^qemu pid: \([0-9][0-9]*\)$/\1/p' "$VM_DIR/launch.log" | tail -1)"
	[ "$lrc" = 0 ] && [ -n "$VM_PID" ] && grep -q '^guest up after ' "$VM_DIR/launch.log" \
		|| die "the launcher failed for v$v (exit $lrc) -- see $VM_DIR/launch.log"
	[ "$(m_pids_of qemu-system-aarch64)" = "$VM_PID" ] || die "the running QEMU is not the one the launcher started"
	if [ "$FIRST_VM" = 1 ]; then
		bj uptime_first_vm_s "$(cut -d' ' -f1 "${PROC_ROOT:-/proc}/uptime" | cut -d. -f1)"
		FIRST_VM=0
	fi
	m_qemu_identify "$VM_PID"
	readback_line qemu r- "$VM_PID" "$t_launch"
	m_reachable "$GUEST" "$PORT" "the guest's plain monitor (arm D)"
	m_reachable "$GUEST" "$ARM_C_PORT" "the guest's echo server (arm C)"
	m_write_stamp "$VM_DIR/stamp.json" \
		'"experiment": "randomise"' \
		"\"boot_tag\": \"$BOOT_TAG\"" \
		"\"vm\": $v" \
		"\"s_regime\": \"$(kv "$vline" S)\"" \
		"\"qemu_pin\": \"$(kv "$vline" pin)\"" \
		"\"qemu_pad\": \"$(kv "$vline" pad)\"" \
		"\"schedule_sha256\": \"$SCHEDULE_SHA256\"" \
		"\"master_seed\": $MASTER_SEED" \
		"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
		"\"monitor_source_sha256\": \"$MON_SRC\"" \
		"\"pin\": {\"qemu\": \"by name, $(kv "$vline" pin) as vCPU 0, vCPU 1, the rest\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
		"\"confinement\": \"units $UNITS on AllowedCPUs=$CONF_CORES for the whole board boot\"" \
		"\"kvm_stats\": $KVM_STATS" \
		"\"kvm_halt_poll_start\": \"$(halt_line)\"" \
		"\"tegra\": $TEGRA" \
		'"order": "per round as order.log, from the schedule; round 0 the settling round, tagged _s0"' \
		'"arms": ["A-loopback", "B-bridge", "C-null", "D-guest"]'
	sleep "$READY_PAUSE_S"      # the readiness check, the pause, then round 0 (section 4.4)
	for r in $R_LIST; do
		line="$(sched_line "round $BOOT_TAG v$v r$r ")"
		threads_line "$r" before
		mon_start "$v" "$r"
		t_start="$(date +%s)"
		order=""
		for a in $(kv "$line" order | tr ',' ' '); do
			arm_round "$v" "$r" "$a"
			order="$order $a"
		done
		t_end="$(date +%s)"
		echo "round $r start=$t_start end=$t_end" >> "$VM_DIR/rounds.log"
		threads_line "$r" after
		echo "round $r cell=$(kv "$line" cell) order:$order" >> "$VM_DIR/order.log"
		say "v$v round $r ($(kv "$line" cell)) done"
	done
	mon_stop || die "the native monitors would not stop at the end of v$v"
	m_governor_recheck
	echo "end $(halt_line)" >> "$VM_DIR/halt.log"
	echo "end $(gpu_pct)" >> "$VM_DIR/gpu.log"
	m_thermal "v$v end" >> "$VM_DIR/thermal.log"
	O="$(oops_count)"
	[ "$O" = 0 ] || die "the kernel log holds $O oops line(s) after v$v: the stop rule -- the owner decides"
	m_stamp_after "$VM_DIR/stamp.json"
	m_require_complete "$VM_DIR" A-loopback B-bridge C-null D-guest
	vm_stop || die "QEMU of v$v would not stop"
	say "v$v done"
done

# ---------------------------------------------------------------- the board boot's end
cat /proc/interrupts > "$BOOT_DIR/interrupts-end.txt" 2>/dev/null
T0="$(head -1 "$BOOT_DIR/v${VMS%% *}/rounds.log" | sed 's/.*start=\([0-9]*\).*/\1/')"
sudo -n journalctl -u ssh -u sshd --since "@$T0" -o short-unix 2>/dev/null | grep ' Accepted ' | awk '{print $1, "Accepted"}' > "$BOOT_DIR/logins-journal.txt"
jrc=${PIPESTATUS[0]}
python3 - "$BOOT_DIR" "$jrc" $VMS <<'PY' || die "could not count the logins"
import os, sys
d, jrc, vms = sys.argv[1], sys.argv[2], sys.argv[3:]
times = []
for ln in open(os.path.join(d, "logins-journal.txt")):
    try:
        times.append(float(ln.split()[0]))
    except (ValueError, IndexError):
        pass
out, total = [], 0
for v in vms:
    for ln in open(os.path.join(d, "v%s" % v, "rounds.log")):
        r, s, e = ln.split()[1], int(ln.split()[2][6:]), int(ln.split()[3][4:])
        n = sum(1 for t in times if s <= t <= e + 1)
        total += n
        out.append("v%s r%s accepted=%s" % (v, r, n if jrc == "0" else "unread"))
out.append("total accepted=%s" % (total if jrc == "0" else "unread"))
open(os.path.join(d, "logins.txt"), "w").write("\n".join(out) + "\n")
PY
ns_down
conf_restore || die "the confinement was not restored"
m_cstate_restore
if [ -n "$QUIESCE_STATE" ]; then
	bash "$QUIESCE" restore "$QUIESCE_STATE" >> "$BOOT_DIR/quiesce.log" 2>&1 \
		|| die "platform-quiesce restore failed (see $BOOT_DIR/quiesce.log): restore by hand before any reboot"
	QUIESCE_STATE=""
fi
m_governor_restore
FINAL="governor $(cat "$SYSFS_CPU/cpu0/cpufreq/scaling_governor" 2>/dev/null); udevd $(allowed "$(pgrep -o -x systemd-udevd)"); qemu $(m_pids_of qemu-system-aarch64 | grep -c .); monitor-native $(m_pids_of monitor-native | grep -c .); namespace $(ip netns list 2>/dev/null | grep -cw "$NS")"
bj final "$(jstr "$FINAL")"
restores_judged || die "the board is not as found: a restore did not hold (above) -- put it right before any reboot"
# Section 10: the board reads as found before any reboot -- no QEMU, no native monitor, no namespace,
# the governor, the idle states and udevd as they were, no drop-in left (judged above and in conf_restore).
[ -z "$(m_pids_of qemu-system-aarch64)" ] && [ -z "$(m_pids_of monitor-native)" ] \
	&& ! ip netns list 2>/dev/null | grep -qw "$NS" \
	|| die "the board is not as found after the board boot ($FINAL): put it right before any reboot"
mkdir -p "$STATE_HOME" && printf '%s\n' $PSTORE_LIST > "$PSTORE_MARK"
bj complete true
say "board boot $BOOT_TAG done: $FINAL"
python3 "$REPORT" --one --schedule "$SCHEDULE" "$BOOT_DIR" || die "the one-board-boot summary could not be made"
