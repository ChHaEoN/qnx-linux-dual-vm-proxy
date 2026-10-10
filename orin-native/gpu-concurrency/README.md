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
  board with [`build-fma.sh`](build-fma.sh):

  ```
  bash build-fma.sh
  ```

  It compiles `fma.cu` with `nvcc -O3 -arch=sm_87` into `~/gpuload/fma`, using
  the one `nvcc` it finds under `/usr/local/cuda*` (or the one `NVCC=` names),
  under the memory cap of `lib-build.sh`, and it never starts `fma`.

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

Measured results: record `20260918T-kvm-gpu`, held locally under NC QDL v7
4.6(i).

## The interference question (added 2026-09-19)

The harness above asks whether QNX costs the GPU anything. The reverse question —
does the GPU work cost the QNX guest anything? — needs three more pieces:

- **`latency_probe.py`** — the same frame protocol as `probe_qnx.py`, but holding
  one connection and reporting a distribution (p50/p90/p99/max) instead of a
  liveness yes/no. One connection on purpose: opening a socket per sample would
  measure TCP setup, not the service.
- **`cpuload.c`** — N busy threads, optionally pinned one per named core
  (`cpuload SECS N [CORES]`), each pin read back and printed as `(verified)`.
  It was written as a CPU twin of `fma.cu`'s driver thread; it is not used as
  one (records `20260921T-a6-*`, held locally), so it is "busy cores, here",
  not a control for the GPU arm. Build with
  `gcc -O2 -o cpuload cpuload.c -lpthread -lm`.
- **`run-interference.sh`** — per round: idle, then gpu, cpu_q (one thread on a
  QEMU core) and cpu_nq (one thread off QEMU's and the probe's cores) in a
  Williams order, then idle2. The repeated idle arm is the drift check. The
  script header is the current arm list; this page does not repeat it.

Treat any single-run quantile difference here as unproven until the arms are
repeated, interleaved.

Results: record `20260919T-interference`, held locally.

## Pin the CPU governor, or the measurement is not a comparison

**Read this before running any latency arm on this board.** The governor is
`schedutil`: an idle system clocks down and any load pushes all six cores up to
the power mode's cap. So an unloaded baseline is measured on a *slower machine*
than every loaded arm, and the load can look like it improves latency. The
unpinned-against-pinned comparison on this board is in record
`20260919T-saturation` (held locally). The 2026-09-19 interference run above was
taken without this control, so its baseline was not like-for-like.

    for c in $(seq 0 5); do echo performance | sudo tee /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor; done
    # ... run the arms ...
    for c in $(seq 0 5); do echo schedutil   | sudo tee /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor; done

Restore it afterwards and **verify all six cores** — this is a system-wide setting
on someone else's board.

## `run-saturation.sh` — looking for where interference starts

Since 2026-09-21 the arms are named by placement, not count — cpu2_q, cpu2_nq,
cpu3_q, cpu6, cpu6_prio, gpu_cpu6, between idle and idle2 (see the script
header). Before that it escalated unpinned CPU load (2 → 4 → 6 threads of 6
cores), with a GPU arm, a combined arm, and repeated idle arms for drift. It carries one control worth keeping:
`cpu6_prio` reruns full saturation with the probe at elevated priority, because
under saturation the probe is itself competing for a core — if the high-priority
arm returns to idle, the degradation was the probe waiting, not the guest. That
arm can exclude probe-side scheduling as a cause and nothing more; whether the
guest being a guest matters is what the native control below is for.

Results: records `20260919T-saturation` and `20260921T-a6-orin` (§1, which
adds arms with the deep idle state c7 disabled), both held locally.

## `run-native-cmp.sh` — is any of it virtualisation?

Without a native process measured under the same load, a guest-side effect
under CPU saturation cannot be separated from "anything on this board degrades
under CPU saturation". This control compiles the **same** `monitor.c` natively
with `gcc` and runs the **same** probe against both, arms interleaved over two
rounds with the governor pinned. Report relative and absolute changes together,
and state the round count beside them.

The two paths are different (loopback against virtio-net + bridge + the guest's
own stack), so absolute latencies are never compared between them.

Results: record `20260919T-native-cmp`, held locally.
