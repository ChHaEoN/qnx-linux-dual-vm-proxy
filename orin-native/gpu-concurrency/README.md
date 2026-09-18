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
