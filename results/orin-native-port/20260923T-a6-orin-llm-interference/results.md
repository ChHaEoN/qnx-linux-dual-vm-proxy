# 20260923T-a6-orin-llm-interference — a generative load that eats half the memory bus does not move the guest's median round trip

**Phase 3b / A6.** The first interference arm driven by a real workload rather
than a synthetic one. L4T runs an LLM on the GPU it owns; the QNX guest runs
beside it under KVM; the probe measures the guest's TCP round trip.

**The answer: no measurable degradation at the median, and the tail is
unresolved by this design.** Both loads make the median round trip slightly
*faster*, and the LLM is indistinguishable from `fma.cu` despite using a
resource `fma` never touches.

k = 12 interleaved rounds, n = 1000 per arm, 200 warm-up, 2 ms spacing,
Williams-counterbalanced over the two loaded arms. 48 of 48 arms complete,
**0 stalls, 0 bad samples, 0 rejected by the monitor**.

---

## 1. The result

Paired contrasts are the median over the 12 rounds of (arm − idle) measured in
the **same** round; the band is the min and max of those 12 differences.

| percentile | idle (ms) | llm (ms) | gpu (ms) | llm − idle (µs) | gpu − idle (µs) | idle2 − idle (µs) |
|---|---|---|---|---|---|---|
| **p50** | 0.1835 | 0.1786 | 0.1792 | **−5.4 [−8.9, −0.9]** | **−4.4 [−10.0, −1.6]** | +0.2 [−3.6, +3.3] |
| p90 | 0.2211 | 0.2548 | 0.2242 | +13.8 [−261, +189] | −2.0 [−270, +208] | +31.5 [−255, +259] |
| p99 | 0.4970 | 0.4403 | 0.4909 | −64.6 [−131, +93] | −11.5 [−76, +44] | +15.8 [−38, +50] |
| p99.9 | 0.6195 | 0.5635 | 0.5962 | −16.0 [−1244, +1133] | −40.9 [−1037, +21] | +16.1 [−1028, +205] |
| max | 0.7837 | 0.6658 | 0.6399 | −2.4 [−720, +1776] | −85.1 [−890, +93] | −17.1 [−1022, +267] |

Read it in three parts:

- **At the median both loads speed the guest up by about 5 µs (3%)**, and both
  paired bands exclude zero. The `idle2` drift bracket is +0.2 µs [−3.6, +3.3],
  so this is not drift across the round. This is the same direction as the
  unexplained GPU-clock-correlated speed-up the 2026-09-21 interference run
  found; this record reproduces it with a different load and does not explain it.
- **From p90 outwards nothing is distinguishable.** Every band spans zero, and
  at p90 they are ±250 µs — one to two orders of magnitude wider than the median
  effect. This design cannot resolve the tail.
- **`llm` is not distinguishable from `gpu`.** Paired within-round,
  llm − gpu at p50 is **−0.5 µs [−4.4, +3.8]**. At p99 it is −52 µs [−113,
  +102], which spans zero.

The eye-catching single number, the `llm` arm's 2.97 ms maximum in one round, is
not evidence of an LLM-specific tail: `idle` itself reached 1.76 ms, and the
paired max band spans ±1.8 ms.

---

## 2. The control that makes the comparison mean anything

The two loaded arms had to differ in the memory dimension *during the measured
windows*, not merely in a prep session. From this run's own `tegra-*.log`,
median across all 12 windows of each arm:

| arm | GR3D | EMC utilisation | EMC clock |
|---|---|---|---|
| idle | 0% | 0% | 2133 MHz |
| **llm** | **94%** | **46%** | **3199 MHz** |
| **gpu** | **99%** | **0%** | **2133 MHz** |
| idle2 | 0% | 0% | 2133 MHz |

So the `llm` arm held the GPU about as hard as `fma` while also running the
memory controller at 46% and forcing it to its full 3199 MHz, and `fma` left the
memory controller untouched at its idle clock. That is the contrast this
experiment exists to make, and it held throughout the run.

**The EMC clock moved between arms**, which is exactly the confound flagged in
[the prep record](../20260923T-a6-orin-llm-prep/results.md): the `llm` arm is not
only a bandwidth load, it is also a memory-clock change. Nothing here separates
the two, and both live inside the same paired contrast.

---

## 3. What was verified rather than assumed

Per `llm` arm, all four checks, every round:

- the load process alive after its 10 s settle and again at probe end;
- its affinity **read back** as cores 3,5 — off QEMU's 0–2 and off the probe's 4;
- GR3D at or above 50%;
- **the load's log grew across the probe window** — recorded per round in
  `thermal.log` as "llm produced N bytes of tokens", 2000–4000 bytes typically.
  This is the only check of the four that proves tokens were being produced: a
  process can be alive and holding the GPU while generating nothing.

Conditions: governor **pinned** to performance (`schedutil` before, restored and
re-verified after), QEMU pinned to 0–2 and read back, page cache dropped at
preflight, guest `ifs-udp.bin` (the plain socket image, without the console
driver that costs 34–38 µs), `nvpmodel` 25 W mode 1, **c7 left enabled**.

| | |
|---|---|
| model | `SmolVLM-500M-Instruct-Q8_0.gguf`, sha256 `9d4612de…` (Apache-2.0) |
| llama.cpp | `e6ab7c1`, CUDA backend, sm_87 |
| llm args | `-ngl 99 -c 4096 -b 512 -ub 128 -t 2 --ignore-eos --temp 0 --seed 42` |
| guest | `ifs-udp.bin` `853de923f700…`, disk `f326b7924868…`, QEMU 6.2.0, `-snapshot` |
| script | `run-llm-interference.sh` sha256 `f1a237f9…` |

---

## 4. What this does NOT demonstrate

- **Not freedom from interference, and not an isolation claim.** A null result at
  the median on one workload, one transport and one guest image is not a
  property of the partitioning. KVM is not a certified hypervisor, SDP 8.0 is
  not QNX OS for Safety, and the monitor is pure POSIX at default priority.
- **The tail is unresolved, not clean.** p90 bands of ±250 µs mean this design
  cannot see a tail effect smaller than that. A safety argument lives in the
  tail, and this run does not supply one. Resolving it needs more rounds or a
  design aimed at the tail, not this one.
- **The median speed-up is unexplained.** Two different loads produce it; the
  project has seen it before and still has no mechanism for it. It is reported
  because it is what the data says, not because it is understood.
- **The EMC clock change is inseparable** from the bandwidth load, as above.
- **One transport only** — TCP over `br0`/`tap-qnx`. Nothing here says anything
  about the shared-memory or doorbell paths.
- **No figure here pairs arm-for-arm with `20260921T-a6-orin-pinned`**: different
  arms, different Williams order, c7 enabled here, and a different guest image.
- **Nothing about the LLM's own quality.** No accuracy, no benchmark, no task.
  It is a load.

---

## 5. Harness findings, paid for during this session

Three, all now fixed in the committed script, and the first two invalidated an
earlier attempt whose numbers were discarded:

- **An ssh client that times out does not kill what it started on the board.**
  Three copies of the run script ended up running concurrently, each pinning the
  governor, re-pinning QEMU and starting its own GPU load; they were measuring
  each other. The script now takes an `flock` and refuses to start otherwise.
  A `pgrep` guard cannot do this job — the launching `sh -c` wrapper carries the
  script's own path in its command line and matches itself.
- **`llama-cli` does not exit on SIGTERM.** `m_load_stop` sends SIGTERM and then
  `wait`s, which is correct for `fma` and `cpuload`; against llama-cli the
  harness blocked in `wait` forever, one arm into the run. The script now
  escalates: TERM, three seconds, KILL, reap.
- **`set -o pipefail` is wrong for this harness family.** `m_thermal` reads
  `tegrastats | head -1`, whose SIGPIPE on the writer is normal and becomes exit
  141 under pipefail. `run-interference.sh` and `run-ladder.sh` use `set -u`
  alone, deliberately, and this script now matches them.
