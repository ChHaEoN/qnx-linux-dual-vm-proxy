# Measurement design — how the numbers in this repo are produced

> **Status (2026-09-21): ADOPTED as owner decision OD11, run in part.** This is
> the answer to one open question — *what sample size should A6 use?* — and the
> answer turned out to be that sample size was the wrong knob. The design below
> is now A6's, and settling it closed A6's last gate item
> ([the plan](orin-native-port-plan.md#architecture-versions), OD11). **Run** on
> 2026-09-21: the attribution ladder of §3.2 with all four arms, interference
> and saturation at k = 12, and the §3.5 pinning and governor controls — records
> under `results/orin-native-port/20260921T-a6-*`. **Not yet run:** §3.3, §3.4,
> the offered-rate sweep of §3.5, and §3.7. The figures published before OD11
> were taken under the **previous** design (n = 3000, k = 2), described and
> criticised here as the starting point; they keep that label and are not
> re-derived.

## 1. The question, and why it was the wrong one

A6's gate had one item left: sample sizes. The current design is **n = 3000**
timed samples per arm, 200 warm-up discarded, 2 ms spacing, and **k = 2**
repetitions of each arm.

Measured from the committed data in
[`results/orin-native-port/20260919T-native-cmp/`](../results/orin-native-port/20260919T-native-cmp/):

| | within one run (n = 3000) | between two runs of the same arm |
|---|---|---|
| p50 | ±0.2% | **13.3%** |
| p99 | ±2.1% | **12.6%** |

**Run-to-run variation is ~69× the sampling noise at p50 and ~3.4× at p99.**
Adding samples buys almost nothing: 3000 samples pin a run's median to ±0.2%,
and the next run lands 13% away. The `guest_cpu6` arm moved 0.247 → 0.291 ms
between two runs while each run's median was internally certain to ±0.2%.

So the knob is **k**, not **n**:

| design | arms | wall clock | p50 uncertainty | resolves a difference of |
|---|---|---|---|---|
| current (k=2, n=3000) | 2 | 0.3 min | ±9.4% | ~26% |
| k=5, n=1000 | 5 | 0.4 min | ±5.9% | ~17% |
| **k=12, n=1000** | 12 | **1.0 min** | **±3.8%** | **~11%** |
| k=50, n=1000 | 50 | 4.2 min | ±1.9% | ~5% |

Every effect this project currently publishes is far larger than the current
design's ~26% resolution — guest-vs-native p50 is 282%, the load effect 54%, the
two-host first-byte segment 145%. The one exception is the two-host **total**
boot time at 5%, which is the one figure already flagged as ~89% fixed timeout
and not quotable as a host comparison. So the current design is not producing
wrong results; it is producing results with an error bar nobody has stated.

## 2. What the reference papers do

Three papers were used as the reference for experimental practice, all measuring
QNX on real hardware:

- **RTAS 2023** — Becker, Dasari, Casini, *On the QNX IPC: Assessing
  Predictability for Local and Distributed Real-Time Systems*. The closest
  analogue: it measures QNX IPC round-trip latency, local and distributed.
- **RTAS 2022** — Dasari, Becker, Casini, Blaß, *End-to-End Analysis of Event
  Chains under the QNX Adaptive Partitioning Scheduler*.
- **JSA 2024** — Becker, Casini, *The MATERIAL framework*.

All three run on a **Raspberry Pi 4B, 4 cores, 4 GB, QNX 7.1 SDP**.

### Where this project is already stronger, and it should be said plainly

Across all three, these terms occur **zero times**: *median, percentile,
confidence, standard deviation, error bar, warm-up*.

1. **Repetition at the run level is absent.** No batch is repeated anywhere in
   any of the three. RTAS 2023's "50 instances per data-point" is arithmetically
   50 job releases inside *one* 10-second run (T = 200 ms, 10 s / 200 ms = 50),
   not 50 runs; its phrase "several experiment runs" is never resolved into a
   number. So none of them can say whether a headline number reproduces. This
   project measured exactly that axis and found it dominates.
2. **No frequency control.** None mentions DVFS, a governor or thermal
   throttling — on a Pi 4B, which throttles. This project found that ~40% of an
   unpinned idle figure was the governor (idle p50 0.319 ms on `schedutil`
   against 0.192 ms pinned), pins it for every arm and restores it after.
3. **No warm-up.** This project discards 200 samples.
4. **Isolation asserted rather than measured.** RTAS 2023: *"Other threads'
   execution does not affect the presented results thanks to the provided timing
   isolation between partitions."* The mechanism is trusted to provide the
   control. This project refused that move and caught a real confound by
   measuring instead.

**This is not a claim to be better work.** Their measurement is *subordinate to
analysis*: the bound comes from a proof, and measurement only checks it is not
violated and shows it is tight. With the claim carried by the analysis, a small
unrepeated n is a reasonable allocation. **This project has no analysis, so
measurement carries everything** — which is exactly why its repetition
discipline has to be stricter than theirs, not looser.

### What to copy, and it is a lot

1. **The worst-case vocabulary, exactly.** Every measured quantity is *"the
   largest observed value"* or *"observed maximum"*. WCRT, WCET and WCST are
   analysis-side terms only, and the vocabulary never slips — not in captions,
   not in figure legends. Adopt this verbatim.
2. **Sweep a parameter; do not publish a point.** RTAS 2023 sweeps message size
   96–2048 B and the curve reveals a structural jump at 256 B (a kernel copy
   strategy change). MATERIAL §8.5.2 sweeps one interference knob over six
   levels with the isolation mechanism on and off. **A claim resting on the
   shape of two curves needs far less n than one resting on a point estimate.**
3. **Keep the observer off the measured cores.** RTAS 2023: *"the data capture
   utilities are allocated to a core that is not used for the experiments."*
4. **Construct the interference; do not chase a quiet machine.** They allocate a
   budgeted interfering workload rather than trying to silence the system.
5. **Let measurement falsify, not establish.** Measurement's job is to check a
   separately-derived claim, or to bound an apparatus. It never produces the
   claim on its own.

## 3. The design

### 3.1 Budget allocation

**n = 1000 timed samples per run, 200 warm-up discarded, 2 ms spacing, k ≥ 12
interleaved rounds.** At n = 1000 the within-run p50 precision is ±0.4%, still
30× finer than the run-to-run motion it sits inside, so the samples it gives up
cost nothing measurable. Rounds are **interleaved** — every round runs the whole
arm set back to back — so a drift in the machine hits all arms equally instead
of only the arms that happened to run late.

**The rule, stated once so it does not have to be re-derived:** *n is set by the
highest quantile the arm reports; everything left in the budget goes to k.*

### 3.2 The attribution ladder

The present figure is a single blended number: 0.172 ms covers the Linux stack,
virtio-net, the bridge, the tap, the guest's `io-sock`, the guest scheduler and
the monitor's own work, with no way to attribute any of it. The papers can
decompose because they use QNX kernel tracing. This project can decompose more
cheaply, with four arms measured by the same client:

| arm | path | what its difference from the previous arm isolates |
|---|---|---|
| **A** loopback | client → trivial echo server on L4T, `127.0.0.1` | the instrument's own floor |
| **B** bridge, no guest | client → `br0`/`tap` → echo server on L4T | bridge and tap cost |
| **C** guest, null server | client → QNX guest, server replies without judging | the virtualisation crossing |
| **D** guest, full | client → QNX guest, full verdict logic | the monitor's own work |

Arm A alone is worth the hour: **no published latency figure should stand
without its apparatus floor beside it.**

### 3.3 Guest-side timestamps — decomposition for 16 bytes

The wire format already has the room. `ipc-test/common/frame.h` is a 16-byte
header plus a 48-byte payload, and `ipc-test/qnx-safety-monitor/monitor.c`
documents `payload[8..47]` as *"reserved, echoed unchanged"* — 40 free bytes
that already make the round trip. The header's `tstamp_cycles` field is sent as
a literal zero by the current probe.

Write two server-side timestamps into the reserved region:

```
payload[8..15]  : uint64  t_server_in    taken when the frame is read
payload[16..23] : uint64  t_server_out   taken just before the reply is written
```

**This needs no clock synchronisation.** Both are taken on the server's own
clock, so `t_out − t_in` is a valid interval no matter how far the client's
clock has drifted. It yields, per sample:

- server-side processing = `t_out − t_in`
- everything else = `RTT − (t_out − t_in)`

**The primitive must be `clock_gettime(CLOCK_MONOTONIC)`, not `ClockCycles()`.**
`monitor.c` contains zero QNX-specific symbols, and that is the entire reason
the native L4T control is a valid control — one source, two targets, no `#ifdef`
fork. Reaching for the QNX primitive would break the comparison this
decomposition exists to sharpen.

Old clients keep working: the reserved region is already echoed, so a client
that ignores the new fields sees no change.

### 3.4 Frame size sweep

`results/*/header.csv` has carried a **`payload_bytes` column since the schema
was written**, and every run to date has recorded the same value, 48. The schema
anticipated a sweep that was never done.

Sweep **64, 96, 256, 512, 768, 1024, 1280, 1536, 1792, 2048 B** — RTAS 2023's
grid, extended down to the current frame. The project's 64-byte frame sits
*entirely below* the smallest size the paper measured, so it has never probed
the region where the paper found structure.

This is a real question, not a formality: the paper's 256 B jump comes from the
QNX kernel's copy strategy, and **this project's path does not use QNX kernel
IPC at all** — it crosses TCP, virtio-net and a bridge. Whether the jump is
present, absent or somewhere else is informative either way.

The monitor parses fixed offsets 0..7 only, so the verdict logic is unaffected;
only the buffer size and the echo length change.

### 3.5 Controls to add

- **Pin affinity for every moving part**, and print the map into every run
  record: the QEMU vCPU threads on one set of cores, the probe on another, the
  load generator on another. The instrument must not share a core with the thing
  it measures.
- **Keep pinning the governor** and recording it before and after. Already done;
  it is the control the reference papers lack.
- **Sweep the offered rate** — 0.2, 0.5, 1, 2, 5, 10 ms spacing — and treat the
  2 ms spacing as a constant under test rather than a setting.

### 3.6 Reporting

- **Headline: the median of the k run-medians, with the observed min–max band
  across the k runs.** The within-run quantile table stays, below it, as detail.
  A single-run quantile table must not stand as the result.
- **Never print a tail statistic without k beside it.** p99.9 is ±13.6% unstable
  even within a run at n = 3000; publish the per-run maximum as a k-sample set
  — min, median and max *of the k maxima* — rather than a single p99.9 number.
- **"Largest observed value", never "worst case".** Nothing here bounds a tail.
- **A per-arm configuration table** in every run record: frame size, interval, n,
  k, warm-up, guest vCPU count and memory, QEMU version and full launch line,
  virtio/tap/bridge configuration, governor before and after, the pinning map.

### 3.7 One falsification to run

The 2026-09-20 finding that ~89% of the boot metric is a fixed 5-second
`waitfor /dev/hd0` timeout currently rests on the wait being identical to within
1 ms on two vendors' silicon. That is strong, but it is a coincidence argument.
**The direct test is to change the constant**: rebuild with the timeout at two
other values, boot twice at each, and show the metric moves by the predicted
amount. Measurement should falsify a claim, not accumulate agreement with it.

## 4. What this design still cannot do

- **It cannot bound anything.** No WCET, no WCRT, no deadline. The reference
  papers' maxima have an epistemic job because a proof supplies the bound and
  the measurement checks it. This project has no such analysis, so its maxima
  are observations and nothing more.
- **It cannot attribute below the server boundary.** §3.2 and §3.3 split the
  round trip into instrument / bridge / crossing / server work. Splitting the
  crossing itself — virtio-net against the vhost thread against the guest's
  `io-sock` — needs kernel tracing on both sides and is not proposed here.
- **It cannot speak to isolation.** Measuring interference reaching the guest is
  not a freedom-from-interference result; if anything the saturation arm is
  evidence in the opposite direction.
- **It is one board and one AWS instance type.** k fixes run-to-run uncertainty,
  not platform generality.
