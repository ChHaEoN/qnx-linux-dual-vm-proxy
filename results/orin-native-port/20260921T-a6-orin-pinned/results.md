# A6 on the Orin — pinned loads, traced windows, verified priority — 2026-09-21

The third campaign of the day on the Jetson Orin Nano (Tegra234, 6× Cortex-A78AE),
QNX SDP 8.0 as a KVM guest beside L4T. It closes the three gaps the first campaign
([`../20260921T-a6-orin/`](../20260921T-a6-orin/results.md)) left open, and changes
the arms to do it: **load threads are pinned and arms are named by placement**, every
probe window is **traced**, and the probe **reports its own scheduling**.

| experiment | k | arms (idle first, idle2 last, loaded arms Williams-ordered, period 6) |
|---|---|---|
| interference | 12 | idle · gpu · cpu_q (1 thread, core 0) · cpu_nq (1 thread, core 5) · idle2 |
| saturation | 12 | idle · cpu2_q (0,1) · cpu2_nq (3,5) · cpu3_q (0,1,2) · cpu6 (0–5) · cpu6_prio · gpu_cpu6 · idle2 |

n = 1000 timed samples per round, 200 warm-up discarded, 2 ms spacing; governor pinned
to `performance`, deep idle state `c7` disabled (`CSTATE=shallow`), both restored and
verified afterwards; QEMU on cores 0–2, probe on core 4; all six cores at 1344 MHz in
every tegrastats sample of every arm. Both experiments ran against the same QEMU process
(pid 14449, in `*/run.log`); that it is also the process of the two earlier campaigns
rests on the operator's account — those runs recorded no pid or boot id. **Every round
is complete — no stall in any of the 156 windows** — and every file passed the gate.

**Every figure below is paired**: the median over rounds of (arm − reference) in the
same round, with the min–max band and how many rounds lie above zero. All at p50 unless
marked.

**Provenance.** Run as committed in `a3f20ac`: every script, library and probe hash in
both stamps names a file of that commit (`run-interference.sh 7d8d31f9`,
`run-saturation.sh beb2b8bd`, `lib-measure.sh b0fb3e8f`, `latency_probe.py 11c8d142`).
cpuload was built by the run itself from `cpuload.c 9a1ca8f5`, and both hashes are
stamped. **fma is not**: it is a hand-built binary identified only by its own hash
(`ef0188d7`, the same in all three campaigns), and no stamp ties it to `fma.cu`. Result
JSONs were copied byte-for-byte; logs and stamps were redacted at capture.

---

## What changed, and how each gap is now closed

| gap in the first campaign | now |
|---|---|
| SCHED_FIFO in cpu6_prio was established by procedure only | the probe reports its own policy, priority and affinity; the gate required **SCHED_FIFO 50 in 12 of 12 cpu6_prio files** and SCHED_OTHER on core 4 in all 144 others — it got them |
| EMC and GPU clocks never recorded; placement sampled once, before the probe | root `tegrastats` (per-core CPU, EMC_FREQ, GR3D) plus both debugfs EMC readings and the GPU clock, every 500 ms across every window: **5–6 tegrastats and 6–7 clock samples per window** |
| load threads unpinned — "cpu4" was a placement lottery | each cpuload thread pinned at creation and read back; the trace shows every pinned core at **100%** in every loaded arm. QEMU's own four threads are still pinned only as a set to 0–2 (see *What this does not show*) |

---

## 1. Loading QEMU's cores costs; loading cores 3 and 5 barely does

| contrast, paired p50 | median | band | rounds above 0 |
|---|---|---|---|
| interference: cpu_q (core 0) − idle | **+19.9 µs** | [+17.6, +31.9] | 12/12 |
| interference: cpu_nq (core 5) − idle | +0.4 µs | [−2.1, +9.8] | 8/12 |
| **interference: cpu_q − cpu_nq** | **+20.0 µs** | [+17.1, +31.4] | **12/12** |
| saturation: cpu2_nq (3,5) − idle | +2.1 µs | [+0.5, +7.2] | 12/12 |
| **saturation: cpu2_q (0,1) − cpu2_nq (3,5)** | **+161.3 µs** | [+149.4, +166.7] | **12/12** |

The same busy thread costs ~20 µs on core 0 and ~0 on core 5; the same two threads cost
~160 µs more on cores 0,1 than on 3,5. **What this design does not separate:** every `_q`
arm includes core 0 and no `_nq` arm does, so "QEMU's cores" is not distinguished from
"core 0" here; and in interference the contrast also swaps clusters (core 5 sits beside
the probe's core 4). Core 3, which shares QEMU's cluster, costs +2.1 µs when loaded with
core 5 — so cluster sharing alone does not produce the cost. The earlier unpinned runs,
with core 0 free and cores 1 and 2 loaded, point the same way but are correlational.

**At p99 the picture is less one-sided:** loads off QEMU's cores are not negligible in
the tail — cpu2_nq +36.2 µs (12/12), cpu_nq +16.6 µs (10/12) — and the single-thread
on/off contrast at p99 is +16.6 µs, 9 of 12.

## 2. Two loaded QEMU cores is the worst placement measured — and the trace does not say why

| paired p50 vs idle | median | band |
|---|---|---|
| cpu2_q — 2 of QEMU's 3 cores loaded | **+164.2 µs** | [+153.2, +170.0] |
| cpu3_q — all 3 of QEMU's cores | +57.9 µs | [+54.9, +112.1] |
| cpu6 — all six cores | +77.3 µs | [+72.1, +131.7] |

cpu3_q − cpu2_q is **−105.6 µs, lower in 12 of 12 rounds**, and cpu2_q − cpu6 is
**+80.6 µs, 12 of 12**: loading two of QEMU's cores costs more than loading all six. p99
agrees (cpu2_q +157 µs vs idle, cpu3_q +42 µs).

The arm was designed around the hypothesis that with one QEMU core left free, QEMU's
threads pile onto it. The window trace shows the free core 2 at **17–23% per window**
(single samples 10–32%) — about four times its idle ~5%, and about the whole footprint
that QEMU's three cores carry together at idle (12–17%). Cores 3 and 5 stay near zero.
So QEMU's work does move onto core 2, and core 2 is never saturated. That rules out
core 2 being CPU-bound; it does **not** rule out QEMU's threads sharing core 2 and waiting
on each other at microsecond scale, which a 500 ms utilisation figure cannot resolve.
Why this placement is the worst is open. Note also that {0,1} was never the placement
the first campaign's unpinned cpu4 fell into — its two-core rounds had {1,2} or {0,2} —
so this is a finding of this run, not a replication.

## 3. The priority control: the probe's own wait adds nothing detectable

cpu6_prio − cpu6 is **+0.9 µs [−50.9, +51.4], 7 of 12 rounds above**, with SCHED_FIFO 50
**verified in all 12 cpu6_prio files** by the probe's own report. The wide band comes from
rounds where one of the two arms, not the other, sat at a ~+50 µs higher level (§ *What
this does not show*); in the six rounds where both sat at their usual level, cpu6_prio −
cpu6 was −2.1 to +8.9 µs. So the probe's run-queue wait for core 4 under full load adds
nothing detectable.

That does **not** place cpu6's +77 µs beyond the probe. Most of it is already present in
cpu3_q (+58 µs), where the probe's core is unloaded; the remaining ~+20 µs (cpu6 − cpu3_q
+19.6 µs, 11/12) appears only when cores 3–5, the probe's among them, are loaded, and
FIFO does not remove it. Costs on core 4 that the probe's priority does not touch —
softirq work deferred to ksoftirqd, preemption of a running thread instead of waking an
idle core — are not tested and not excluded.

## 4. GPU load lowers latency slightly — the EMC clock is ruled out for this run

| paired p50 | median | band | rounds below 0 |
|---|---|---|---|
| interference: gpu − idle | −3.0 µs | [−7.6, +3.7] | 11/12 |
| saturation: gpu_cpu6 − cpu6 | **−9.4 µs** | [−61.3, −2.6] | **12/12** |

The direction is the same as before: gpu − idle was −5.0 and −3.8 µs (12/12 each) in the
two earlier campaigns, and at full CPU load it is now 12 of 12 (16 of 20 and 15 of 20
before). The −9.4 µs median also carries cpu6's higher-level rounds, which gpu_cpu6 never
entered; in the 7 rounds where cpu6 sat at its usual level, gpu_cpu6 − cpu6 is −6.7 µs
[−9.8, −2.6].

**The EMC-clock hypothesis is falsified for this run:** the effect is present with the
memory controller at **2133 MHz in every window of every arm** (BPMP debugfs and root
tegrastats agree). EMC was not recorded in the earlier runs. fma's kernel is a
register-only `fmaf` loop and generates essentially no DRAM traffic by construction.
tegrastats' EMC utilisation read 0% in every sample of every arm, idle included — an
integer percentage that never moved, so it adds no evidence either way. What does change
under fma is the GPU clock (918 MHz vs 306, devfreq) and GR3D itself; the CPU clock does
not (1344 MHz throughout). The mechanism remains open. (The kernel clock framework's EMC
reading stayed at 204 MHz throughout: it does not track the BPMP-owned clock and is
recorded, not used.)

## 5. Stalls: none here, two in dry runs

No round of this campaign stalled. Two board dry runs of the same tooling did:

| dry run | arm | what the files show | tooling |
|---|---|---|---|
| 1 (K=6, N=1000) | cpu2_q r3 | no reply for ≥10 s from sample 391 of 1200; core 2 at 100% from the 3rd of 21 trace samples to the end of the window; the arm aborted, and **no recovery was recorded** | an intermediate version: its script, library and probe hashes name the files kept in `dry1-cpu2_q_r3/tooling-as-run/` |
| 2 (K=6, N=1000) | cpu6 r6 | no reply for ≥10 s from sample 507; stall record written; after the harness stopped the load, the guest answered **about 1 s later (≥0.99 s), on the first attempt** | exactly `a3f20ac` |

Dry run 1's stall is why the tooling now records a stall as an outcome instead of
stopping (owner decision); dry run 2, on that tooling, recorded one. Two stalls in 89
loaded dry-run windows (both in saturation arms), none in the campaign's 108 loaded
windows (156 in all). Both were under load; whether load is required is not shown from
two events. Neither needed a restart of the guest or QEMU — after dry run 1 this is
inferred from the later runs reaching the same guest, not recorded. Recovery under
continuing load is not shown. Rate, trigger and mechanism are not measured. Evidence:
[`dry-run-stalls/`](dry-run-stalls/).

## 6. Consistency

The undisturbed path: idle p50 **175.9 µs** (interference) and **175.8 µs**
(saturation), idle2 176.2 / 176.0 µs — against 174.7–175.6 µs in the c7-off campaign
earlier the same day, with the window sampler now running beside every probe. The drift
brackets (idle2 − idle) are +0.2 and +0.3 µs with bands spanning zero.

---

## What this does not show

- **A second level persists with the loads pinned.** The round's samples sit at one of
  two levels about 50 µs apart (cpu6: ~253 vs ~303 µs). cpu6 was at the higher one in 5
  of 12 rounds (wholly or in part), cpu6_prio in 3, cpu3_q in 1, gpu_cpu6 in none; the
  level lasts for seconds and can switch mid-window (cpu6 r12 falls from ~302 to ~252 µs
  across the window, cpu6_prio r6 in its last quarter). QEMU's four threads are pinned only
  as a set to cores 0–2 and their placement within it is not recorded, so a placement
  lottery remains — on QEMU's side. The bands of every contrast with cpu6 are set by these
  switches.
- **Why** QEMU's cores matter — which thread waits, and where; and whether it is QEMU's
  cores or core 0 (§1). The trace resolves cores at 500 ms, not threads at microseconds.
- **Why two loaded QEMU cores are worse than three.** Core 2 is not saturated; contention
  on it at microsecond scale is neither shown nor excluded.
- **Where cpu6's cost sits.** Not in the probe's run-queue wait; beyond that, not located.
- **What the GPU speed-up is.** The EMC clock is excluded for this run; nothing else is
  tested.
- **Stall rate or mechanism.** Two observations in dry runs, none in the campaign.
- **Reproducibility across boots or days.**
- **Comparability with earlier runs.** The arms changed (pinned, placement-named) and the
  sampler — root tegrastats plus a root shell loop, unpinned — runs in every window,
  idle included. Compare within this run, by pairing.
- **Any real-time or safety property.** SDP 8.0 is not QNX OS for Safety; the guest runs
  at default priority; nothing here is an isolation or freedom-from-interference result.
- **Arm-level tails.** max is the largest observed value per round, never a bound
  (single-sample maxima up to 10.9 ms occur, e.g. cpu3_q; idle itself reached 7.0 ms).

## Files

`interference/raw/`, `saturation/raw/` — per round: `lat-<arm>_r<k>.json` (summary incl.
the probe's scheduling report, samples sorted and in arrival order), `tegra-*.log`,
`clk-*.log`, `load-*.log` (cpuload's pin confirmations; fma's log for the interference
gpu arm), `gpu-gpu_cpu6_r<k>.log` (fma's log for saturation gpu_cpu6); per run:
`stamp.json`, `order.log`, `thermal.log`, `probe.log`. `*/run.log` — the scripts' own
output. `chain.status` — both exits. `dry-run-stalls/` — the two dry-run stalls (§5).
