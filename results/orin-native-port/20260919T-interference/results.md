# Does the Compute partition's GPU work disturb the Safety partition? — 2026-09-19

Question: under A6 (L4T on the metal owning the GPU, QNX as a KVM guest beside
it), does saturating the GPU on L4T change the QNX guest's responsiveness?

This became askable only on 2026-09-18, when QNX first booted under KVM. Before
that the guest ran under TCG and any latency number would have measured the
emulator.

## Method

One held TCP connection to the QNX guest's `qnx-safety-monitor` on :7100 over the
real `br0`/`tap-qnx` bridge. Each sample sends a valid 64-byte frame
(`ipc-test/common/frame.h`) carrying a claim the monitor ACCEPTS, and times the
round trip with `perf_counter`. 3000 timed samples per arm at 2 ms spacing, after
200 warm-up samples that are timed and discarded.

Four arm types, run as idle → gpu → cpu → idle2, then the gpu/idle pair repeated
interleaved (idle_r2 → gpu_r2 → idle_r3 → gpu_r3):

| arm | load on L4T | why it exists |
|---|---|---|
| idle | none | baseline |
| gpu | `fma.cu`, GR3D 99%, ~1555 GFLOP/s | the question |
| cpu | `cpuload`, one core at 100%, GR3D 0% | **the control that makes the gpu arm interpretable** |
| idle2 | none | drift check — the board heats under load |

The cpu arm is not optional. `fma.cu` drives the GPU from a CPU thread, so "GPU
saturated" and "system busier" arrive together; without a CPU-only arm a latency
change could not be attributed to the GPU.

## Result — no measurable interference

Per arm (ms):

| arm | p50 | p90 | p99 | max |
|---|---|---|---|---|
| idle | 0.298 | 0.347 | 0.646 | 0.842 |
| idle2 | 0.297 | 0.342 | 0.649 | 0.789 |
| idle_r2 | 0.297 | 0.333 | 0.620 | 0.782 |
| idle_r3 | 0.299 | 0.357 | 0.654 | 1.021 |
| gpu | 0.297 | 0.386 | 0.643 | 0.784 |
| gpu_r2 | 0.296 | 0.375 | 0.598 | 0.827 |
| gpu_r3 | 0.288 | 0.326 | 0.575 | 0.739 |
| cpu | 0.293 | 0.348 | 0.630 | 0.831 |

Pooled, idle (n=12000) against gpu (n=9000):

| quantile | idle | gpu | delta |
|---|---|---|---|
| p50 | 0.298 | 0.293 | **−1.5%** |
| p90 | 0.342 | 0.358 | +4.7% |
| p99 | 0.646 | 0.619 | **−4.2%** |
| p99.9 | 0.772 | 0.730 | **−5.3%** |
| max | 1.021 | 0.827 | idle is worse |

**The GPU arms are faster at three of four quantiles, and the worst single sample
in the whole experiment came from an idle arm.** A real interference effect
cannot be negative at p99 and positive at p90. The per-arm p90 ranges overlap
outright (idle 0.333–0.357, gpu 0.326–0.386), and the third gpu arm's p90 (0.326)
is lower than every idle arm. The +4.7% pooled p90 is noise.

An earlier single-run reading showed gpu p90 at +11% against idle. That is why the
arms were repeated interleaved; the repeat dissolved it. It is recorded here
rather than omitted.

Validity: `bad=0` and `rejected_by_monitor=0` in all eight arms; the guest's own
console independently logs eight × `seen=3200 accepted=3200 rejected=0`. idle2
returned to idle (p50 0.297 vs 0.298), so no thermal drift invalidates the run —
the board moved 47.8 → 50.2 → 48.7 °C. `disk-qemu` was byte-identical before and
after all eight arms (`-snapshot`).

## What this does NOT show

- **Not freedom from interference**, and no ISO 26262 or ASIL claim attaches. This
  is one workload, one direction, at one load level, on one board.
- **Not a QNX real-time result.** Nothing here is a bounded-latency guarantee and
  the guest is not configured for one.
- **Not hypervisor IPC latency.** Under A6 there is no hypervisor: QNX is a KVM
  guest. The number is a whole-system round trip — Linux network stack, QEMU
  virtio-net, bridge, guest `io-sock`, the monitor, and the guest's scheduler.
- **Not isolation.** The boundary is KVM, where Linux owns the QNX guest's memory.
- The guest had 2 vCPUs of 6 cores and the loads ran on L4T. A single busy core
  leaves four idle; this says nothing about behaviour under full CPU saturation.
- n=3000 per arm supports p99; p99.9 is reported but is thin at this sample size.
