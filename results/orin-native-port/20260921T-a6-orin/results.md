# A6 campaign on the Orin — ladder, interference, saturation — 2026-09-21

Three experiments on a Jetson Orin Nano (Tegra234, 6× Cortex-A78AE), QNX SDP
8.0 as a KVM guest beside L4T, **each run twice**: once with the board's CPU
idle states as found, and once with the deep state disabled. The second set
exists to test a confound found in the first; it lives in
[`../20260921T-a6-orin-c7off/`](../20260921T-a6-orin-c7off/).

| directory | idle states | ladder | interference | saturation |
|---|---|---|---|---|
| `20260921T-a6-orin/` | **as found** — state1 `c7` enabled | k=12 | k=12 | k=20 |
| `20260921T-a6-orin-c7off/` | **c7 disabled** (`CSTATE=shallow`) | k=12 | k=12 | k=20 |

n = 1000 timed samples per round, 200 warm-up discarded, 2 ms spacing,
interleaved rounds (owner decision OD11); loaded arms Williams-counterbalanced;
governor pinned to `performance` and restored; QEMU on cores 0–2, probe on
core 4. Guest image `ifs-demo2.bin` and disk `disk-qemu` are byte-identical to
the ones that ran on AWS `a1.metal` the same day, as is the QEMU build
(`6.2.0 Debian 1:6.2+dfsg-2ubuntu6.31`). Every run passed the completeness
gate: the exact round set, every file newer than the run's start, n and
warm-up as requested, zero bad frames, zero monitor rejections.

**Every figure below is paired**: the median over rounds of (arm − reference)
measured in the same round, with the min–max band across rounds.

---

## 1. The deep idle state is the cause of a slow mode — tested, not inferred

With idle states as found, every **unloaded** guest arm carried a discrete
slow mode: a copy of the main distribution shifted about **+292 µs**, holding
a median of ~11% of samples. Host-native arms (ladder A, B) never had it. Full
CPU load removed it, and one busy thread on core 0 removed it in 4 of 4 rounds.

The Orin exposes cpuidle `state1`, named `c7`, declared exit latency 5000 µs,
enabled. The governor pin controls frequency and never touched it. **Disabling
it removed the slow mode from every unloaded arm in every experiment**:

| arm | slow-mode share, c7 on | c7 off |
|---|---|---|
| ladder D-guest | 12.80% | **0.00%** |
| ladder C-null | 6.25% | **0.00%** |
| interference idle | 12.50% | **0.00%** |
| saturation idle | 9.45% | **0.00%** |

(samples in 0.40–0.60 ms; median of k rounds; every C7-off round ≤ 0.2%.)

**What it changes.** At the median, little: the undisturbed guest path went
from 178.2–179.7 µs to **174.7–175.6 µs**, about 2%. In the tail, a lot: idle
p99 went from **502–508 µs to 226–235 µs**, more than halved.

**The saturation p99 "improvement" was this artifact, and it reverses.** With
c7 on, cpu6's p99 was 196 µs *lower* than idle's in 20 of 20 rounds — full load
appeared to improve the tail. That was the idle reference carrying the slow mode
that load suppresses. With c7 off the sign flips:

| p99, paired vs idle | c7 on | c7 off |
|---|---|---|
| cpu6 | **−195.6 µs** [−250, −132], 0/20 positive | **+68.4 µs**, 18/20 positive |
| cpu6_prio | −196.0 µs, 2/20 | +83.3 µs, 18/20 |
| gpu_cpu6 | −191.8 µs, 1/20 | +82.3 µs, 18/20 |
| cpu4 | −3.8 µs, 9/20 | +94.4 µs, 18/20 |

With the confound removed, load worsens the tail, as it physically should.

**What is not shown.** The slow mode costs ~0.29 ms per affected sample, far
below the 5000 µs the state declares; the declared figure is a bound the idle
governor works with, not a measured wake cost, and no sample anywhere shows a
5 ms wake. *Which* core's wake-up is paid — a vCPU, QEMU's I/O thread, the
network softirq core — is not shown; core 0 is the leading candidate, a
HYPOTHESIS. The probe stored samples sorted, so whether the mode is periodic,
bursty or tied to a tick could not be examined here (it now saves arrival
order as well).

---

## 2. The undisturbed guest path is stable — within one boot and one window

| group | c7 on | c7 off |
|---|---|---|
| ladder D-guest | 178.2 µs | 174.7 µs |
| interference idle | 178.2 | 174.8 |
| interference idle2 | 178.9 | 175.1 |
| saturation idle | 179.3 | 175.5 |
| saturation idle2 | 179.7 | 175.6 |

p50, median of k run-medians. With c7 on the groups agree to about **2%**
(bootstrap interval on the largest difference roughly −1 to +4 µs), not the
0.8% the spread of medians alone suggests. With c7 off they agree within
0.9 µs, and the bands tighten — part of the c7-on run-to-run motion was the
slow mode's hit rate.

**Not shown**: boot-to-boot or day-to-day reproducibility. All six runs shared
one guest boot and one QEMU process. p90 does not reproduce with c7 on — it is
bimodal, reporting only whether the slow-mode share crossed 10%.

---

## 3. The ladder — and arm C on the Orin itself

| paired | c7 on | c7 off |
|---|---|---|
| bridge, B − A | +3.2 µs [+2.5, +4.0] | +3.6 µs [+2.2, +4.2] |
| guest crossing, D − B | +122.9 µs [+120.5, +126.2] | +119.0 µs [+117.3, +120.7] |
| transport, C − B | +121.4 µs | +117.7 µs |
| **monitor's own work, D − C** | **+0.7 µs [−3.5, +6.8]** | **+1.4 µs [−0.8, +4.4]** |

**The monitor's own read, verdict and write are not distinguishable from zero
on the Orin**, in both conditions — D > C in 7 of 12 rounds with c7 on. Until
this run that was an a1.metal result applied to the Orin by inference; the
Orin's ladder record said its crossing "still formally contains an unmeasured
monitor component". It is now measured on this board. The slow mode already
appears in C-null (a verbatim echo server), so it is not the monitor's code.

The bridge is +3.2 µs here and +3.2 µs on a1.metal, paired — the same to a
tenth of a microsecond on two vendors.

---

## 4. CPU load raises the median — but placement, not count, decides how much

At full commitment the rise is robust in both conditions: cpu6 − idle is
**+70.5 µs** (c7 on) and **+74.2 µs** (c7 off), positive in 20 of 20 rounds
each, and the floor rises too.

**It is not a monotone function of load.** The load threads were unpinned, and
where the scheduler put them decided the cost. Read from one tegrastats sample
per arm, before the probe started (so correlational, a HYPOTHESIS):

- In cpu4, the 7 rounds with load on two of QEMU's three cores cost **+158 to
  +177 µs** — *more than cpu6*. The 13 rounds with one QEMU core loaded cost
  +27 to +52 µs.
- One thread in interference cost ~0 on core 3, +2 to +14 µs on cores 0–1,
  and +35 to +53 µs on core 2.

So the cost follows load on QEMU's cores — where the vCPU threads, QEMU's
userspace virtio-net/tap thread, the host's receive-path softirq and its
idle-state and KVM halt handling all run. These data cannot apportion it among
them. **Placement was not controlled, so the cpu2 → cpu4 → cpu6 sequence is a
placement lottery, not a load sweep.**

**cpu6_prio is uninformative in these runs.** SCHED_FIFO 50 left the median
shift where it was (cpu6_prio − cpu6: 0.0 µs with c7 on, −3.8 µs with c7 off,
bands spanning zero). But that FIFO was in effect is established by procedure —
`chrt` exits non-zero on failure and the harness aborts — never by measurement.
The run shows neither that the priority worked nor that it failed.

---

## 5. GPU load speeds the fast path up slightly — robustly, mechanism unknown

| paired vs idle | c7 on | c7 off |
|---|---|---|
| gpu, p50 (interference) | **−5.0 µs** [−14.0, −0.3], **12/12** lower | **−3.8 µs** [−8.5, −0.3], **12/12** lower |

It persists at full CPU commitment (gpu_cpu6 vs cpu6: lower in 16 of 20 rounds
at p50, 18 of 20 at p05), and it **survives disabling c7** — so it is not the
GPU load keeping a core out of the deep idle state. That had been one of two
hypotheses; the other, stronger now, is that the memory-controller (EMC) clock
rises under GPU load. **EMC was not recorded in these runs, so that is an
untested HYPOTHESIS.** Nothing assigns the saving to the guest rather than the
host; it is a whole-system round trip. No effect on the tail is shown.

**fma's host thread does not load a CPU.** During all 12 gpu arms no core
exceeded 1% while GR3D sat at 99% — it blocks in `cudaDeviceSynchronize`. So:
the interference `cpu` arm is **not** the footprint twin of the gpu arm it was
designed to be; and gpu_cpu6 vs cpu6 is *close to* a matched GPU control.

---

## 6. No drift at the median

idle2 − idle: −0.3 µs (interference) and −0.3 µs (saturation) with c7 on,
+0.6 µs and −0.1 µs with c7 off, bands spanning zero. Drifts up to ~2 µs are
not excluded. **In the tail it does not hold**: with c7 on, saturation's idle2
exceeded idle's largest observed value in 14 of 20 rounds, and all 10 samples
above 1 ms fell in idle2. Whether the counterbalancing cancelled any carryover
among loaded arms is neither shown nor ruled out.

---

## What this does not show

- **Boot-to-boot or day-to-day reproducibility.** One boot, one QEMU process.
- **Any isolation, freedom-from-interference, determinism or real-time
  claim.** These are round trips under a light, synthetic load.
- **A virtualisation-specific cost under load.** There is no native control
  under load.
- **A bound on anything.** "Largest observed value", never worst case; the
  largest single samples here were 6–16 ms, and multi-millisecond stalls
  occurred on the host-native bridge arm too — they are not specific to load
  or to virtualisation.
- **The mechanism of any effect above**: which core pays the c7 wake, whether
  EMC drives the GPU speed-up, where under load the extra ~70 µs is spent.

## Record-keeping notes

- **A false stamp field.** Both saturation stamps (c7 on and c7 off) carry
  `"known_confound": "gpu_cpu6 runs 7 busy threads (6 + fma driver)..."`. It is
  wrong — see §5 — and was corrected in the tooling after these runs; the stamps
  are left as written.
- **Provenance.** The c7-off runs' library and scripts are in git exactly as
  run (commit `c518768`). The c7-on ladder ran on library `62931898…`, which no
  commit holds; it is `4ce9876`'s library with its GR3D block taken verbatim
  from `65f7011`, reconstructed and verified byte-for-byte. The ladder never
  calls the GPU check, so that one function cannot have affected it.
- **Two refused runs**, not included and not read: a first ladder the gate
  refused because of a freshness-check bug, and a first interference run
  refused because the GPU-load check misread "GR3D". Both were re-run.
- **Independent analysis.** Every figure here was re-derived from the raw files
  by a separate analysis, and each interpretive claim adversarially challenged;
  claims that did not survive as first stated are worded as they survived.

## Files

`{ladder,interference,saturation}/raw/` in each directory: `lat-<arm>_r<round>.json`
(summary plus every sample, sorted), `stamp.json`, `probe.log`, `order.log`,
and for the loaded experiments `thermal.log` and the per-arm load logs. Result
files are copied byte for byte and verified against the board's hashes; logs
and stamps passed through the capture-time redactor, and no username, LAN
address or hostname appears in any of them.
