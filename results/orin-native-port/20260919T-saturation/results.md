# Where does interference actually start? — CPU saturation, 2026-09-19

The earlier run that day found no measurable GPU interference, but it had one
busy core out of six. Four idle cores is not a contended system. This escalates
the CPU load to find the point where the QNX guest's round trip degrades — and
finds it.

It also found that the earlier baseline was measured on an uncontrolled variable.

## The confound that had to be removed first: DVFS

The governor is `schedutil`. An idle system clocks down to 729 MHz; any load
pushes all cores to 1344 MHz. So every "idle" arm had been measured on a
*slower machine* than every loaded arm. Measured directly, same idle condition:

| governor | idle p50 | idle p99 |
|---|---|---|
| `schedutil` (as found) | 0.319 ms | 0.689 ms |
| `performance` (pinned) | 0.192 ms | 0.518 ms |

**~40% of the "idle" latency was the governor, not the system under test.** Every
arm below is therefore run with the governor pinned to `performance`, and
restored to `schedutil` afterwards (verified on all six cores).

## Result

Per arm, governor pinned, 3000 timed samples each (ms):

| arm | p50 | p90 | p99 | max |
|---|---|---|---|---|
| pidle | 0.190 | 0.221 | 0.487 | 0.694 |
| pidle_r2 | 0.182 | 0.210 | 0.467 | 0.599 |
| pidle_r3 | 0.181 | 0.209 | 0.469 | 0.975 |
| pidle2 | 0.183 | 0.249 | 0.472 | 0.695 |
| **pgpu** | **0.180** | 0.215 | 0.463 | 0.603 |
| pcpu2 | 0.219 | 0.261 | 0.299 | 0.621 |
| pcpu4 | 0.273 | 0.313 | 0.524 | 1.826 |
| pcpu6 | 0.258 | 0.306 | 0.354 | 0.400 |
| pcpu6_r2 | 0.281 | 0.300 | 0.325 | 1.897 |
| pcpu6_r3 | 0.291 | 0.309 | 0.330 | 0.610 |
| pgpu_cpu6 | 0.275 | 0.300 | 0.318 | 0.354 |

Pooled, idle (n=12,000) against cpu6 (n=9,000):

| quantile | idle | cpu6 | delta |
|---|---|---|---|
| p50 | 0.184 | 0.283 | **+53.9%** |
| p90 | 0.217 | 0.306 | **+40.6%** |
| p99 | 0.475 | 0.343 | **−27.9%** |
| p99.9 | 0.586 | 0.374 | **−36.2%** |

### 1. CPU saturation interferes, and it replicates

Per-arm p50 ranges are **disjoint**: idle 0.181–0.190, cpu6 0.258–0.291. Every
loaded arm exceeds every idle arm by at least 38%. The arms were interleaved and
repeated precisely because an earlier +11% p90 reading had dissolved on repeat;
this one did not.

### 2. The tail gets *better* under load

p99 falls 27.9% and p99.9 falls 36.2% under full saturation. The likely mechanism
is that busy cores never enter idle states, so nothing pays a wake-up — the same
effect the DVFS finding exposes, one level down. **This is an observation, not a
demonstrated mechanism: no C-state residency was measured.**

### 3. GPU load alone still shows nothing

`pgpu` p50 0.180 against idle 0.190 — *faster*, i.e. within noise. The earlier
null result survives re-testing under a controlled clock. And `pgpu_cpu6`
(p50 0.275) is indistinguishable from `pcpu6` (0.258–0.291): adding GPU
saturation on top of CPU saturation changes nothing further.

### 4. An unexplained middle

`pcpu4` produced the worst tail in both runs (max 1.826 ms here, 16.5 ms in the
unpinned run) while `pcpu6` produced the best. Only 2 samples of 3000 (0.07%)
exceeded 1 ms, against zero for both idle and cpu6. Partial oversubscription
plausibly causes migration churn that full commitment does not — but n=2 is far
too thin to claim a mechanism, and none is claimed.

## What this does NOT show

- **Not freedom from interference**, and no ISO 26262 or ASIL claim attaches. One
  workload, one board, synthetic load.
- **Not a QNX real-time result.** Nothing here is a bounded-latency guarantee, and
  the guest is not configured for one.
- **Not hypervisor IPC latency.** Under A6 there is no hypervisor: QNX is a KVM
  guest. This is a whole-system round trip — Linux stack, virtio-net, bridge,
  guest `io-sock`, the monitor, the guest's scheduler.
- **Not isolation.** The boundary is KVM, where Linux owns the QNX guest's memory.
- The degradation is what you would expect from oversubscription (6 busy threads
  plus 2 vCPU threads plus the probe on 6 cores) and is **not** evidence of a
  virtualisation-specific effect. No comparison against a native process was run.
- A probe-priority control arm (`cpu6_prio`, unpinned run) came back negative:
  0.285 vs 0.291 p50, so probe-side scheduling delay does not explain the shift.
