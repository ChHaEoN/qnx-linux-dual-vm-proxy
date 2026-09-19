# GPU / QNX concurrency harness (Phase 3b)

Two small programs that together answer one question on the Jetson Orin Nano:

> With QNX running as a KVM guest, does L4T still get the GPU at full
> throughput, and is the QNX guest genuinely alive while it does?

This exists because the architecture chosen here (ADR-003 option C shape) gives
the GPU to **L4T on the metal** and runs QNX as a KVM guest beside it. There is
no GPU pass-through and no vGPU: QNX never touches the GPU. The thing worth
measuring is therefore not "how fast is QNX's GPU" — it has none — but whether
putting a hardware-virtualised QNX beside the GPU owner costs the GPU anything.

## The two halves

- **`fma.cu`** — sustained FP32 FMA load, 512 blocks x 256 threads x 200k
  iterations per round, reporting GFLOP/s per round and a mean. Build on the
  board with:

  ```
  /usr/local/cuda/bin/nvcc -O3 -arch=sm_87 -o fma fma.cu
  ```

  A `if (x == 12345.678f)` guard that is never true keeps the compiler from
  deleting the loop. Pair it with `tegrastats` to confirm `GR3D_FREQ` actually
  rises — a CPU-bound loop that never reaches the GPU would otherwise look like
  a result.

- **`probe_qnx.py`** — sends valid 64-byte frames (the `ipc-test/common/frame.h`
  layout: `uint64 seq`, `uint64 tstamp_cycles`, 48-byte payload, little-endian)
  to the QNX guest's echo server and requires a **byte-exact** echo. It never
  sends `UINT64_MAX`, which is the server's sentinel sequence. Reach the guest
  through slirp port forwarding, which needs no host network changes:

  ```
  -netdev user,id=n0,hostfwd=tcp::17000-:7000
  ```

## Why a byte-exact echo, and not a process check

`pgrep` proving a qemu process exists would show only that a process exists. An
echo that comes back byte-identical shows the guest booted, its stack is up, its
server is scheduled and it is doing work *during* the GPU load. The guest's own
serial log independently records each connection (`client connected from ...`,
`client EOF after N frames`), so both ends can be cross-checked.

## What results from this may NOT be quoted as

- **Not a GPU partitioning, isolation or freedom-from-interference result.**
  Nothing here divides the GPU. L4T owns it outright.
- **Not a claim that QNX can use the GPU.** In this architecture it cannot.
- **Not a latency measurement.** The probe round-trip times are a liveness
  signal — one host, slirp NAT, a handful of frames, no percentiles.
- **Not a load, stress or soak test.** 30 s arms with the guest otherwise idle.
- **Not a TFLOPS headline.** The load is raw FMA ALU throughput, not GEMM and
  not inference.

Measured results live under `results/orin-native-port/20260918T-kvm-gpu/`.

## The interference question (added 2026-09-19)

The harness above asks whether QNX costs the GPU anything. The reverse question —
does the GPU work cost the QNX guest anything? — needs three more pieces:

- **`latency_probe.py`** — the same frame protocol as `probe_qnx.py`, but holding
  one connection and reporting a distribution (p50/p90/p99/max) instead of a
  liveness yes/no. One connection on purpose: opening a socket per sample would
  measure TCP setup, not the service.
- **`cpuload.c`** — **the control that makes the GPU arm interpretable.** `fma.cu`
  drives the GPU from a CPU thread, so "GPU saturated" and "system busier" arrive
  together; without a CPU-only arm at the same footprint, a latency change cannot
  be attributed to the GPU. Build with `gcc -O2 -o cpuload cpuload.c -lpthread -lm`.
- **`run-interference.sh`** — runs idle → gpu → cpu → idle2. The repeated idle arm
  is the drift check: the board heats under load, and without it a thermal effect
  would be indistinguishable from an effect of the load.

A first run showed the GPU arm's p90 about 11% above idle. Repeating the arms
interleaved dissolved it — across three GPU arms the p90 range (0.326-0.386 ms)
overlaps the idle range (0.333-0.357 ms) outright. Treat any single-run quantile
difference here as unproven until the arms are repeated.

Results: `results/orin-native-port/20260919T-interference/`.

## Pin the CPU governor, or the measurement is not a comparison

**Read this before running any latency arm on this board.** The governor is
`schedutil`: an idle system clocks down to 729 MHz and any load pushes all six
cores to 1344 MHz. So an unloaded baseline is measured on a *slower machine* than
every loaded arm, and the load looks like it improves latency. Measured directly,
same idle condition:

| governor | idle p50 | idle p99 |
|---|---|---|
| `schedutil` (as found) | 0.319 ms | 0.689 ms |
| `performance` (pinned) | 0.192 ms | 0.518 ms |

~40% of the "idle" latency was the governor. The 2026-09-19 interference run above
was taken without this control; its GPU conclusion survived re-testing, but its
baseline was not like-for-like.

    for c in $(seq 0 5); do echo performance | sudo tee /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor; done
    # ... run the arms ...
    for c in $(seq 0 5); do echo schedutil   | sudo tee /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor; done

Restore it afterwards and **verify all six cores** — this is a system-wide setting
on someone else's board.

## `run-saturation.sh` — where interference actually starts

Escalates CPU load (2 → 4 → 6 threads of 6 cores), with a GPU arm, a combined
arm, and repeated idle arms for drift. It carries one control worth keeping:
`cpu6_prio` reruns full saturation with the probe at elevated priority, because
under saturation the probe is itself competing for a core — if the high-priority
arm returns to idle, the degradation was the probe waiting, not the guest. It came
back negative (0.285 vs 0.291 p50), which is what makes the p50 shift attributable
to the guest side.

Findings: CPU saturation moves p50 by **+54%** (disjoint per-arm ranges, replicated),
the **tail improves** under load (p99 −28%, busy cores never idle), and GPU load
alone still shows nothing even under a pinned clock.

Results: `results/orin-native-port/20260919T-saturation/`.
