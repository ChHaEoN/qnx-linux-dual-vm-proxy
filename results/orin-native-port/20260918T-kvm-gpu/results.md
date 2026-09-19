# Option C concurrency measurement — 2026-09-18, Jetson Orin Nano

Question: with QNX running as a KVM guest, can L4T still use the GPU, and do the
two run concurrently without software emulation?

Setup: L4T R36.4.7 on the metal, holding the GPU natively (CUDA 12.6, sm_87,
8 SMs). QNX SDP 8.0 as a KVM guest (`-enable-kvm -cpu host`, 2 vCPU of 6, 1 GB
of 8 GB), booting the rebuilt `startup-qemu-virt`. No GPU passthrough, no vGPU,
no GPU access from QNX — L4T simply keeps the GPU it already owns.

GPU load: `fma.cu`, sustained FP32 FMA, 512 blocks x 256 threads x 200k iters
per round, 30 s per run. Reported throughput is raw FMA ALU throughput — NOT a
GEMM, inference or TFLOPS-headline figure.

QNX liveness: `probe_qnx.py` sends valid 64-byte frames (ipc-test/common/frame.h
layout) to the guest's echo server via slirp hostfwd 17000->7000 and requires a
byte-exact echo.

## Artefact provenance — read this before citing the table

The IFS is pinned: `ifs-kvmfix.bin`, sha256 `26170cd7dc74c216…`, verified identical
on the PC and the board before the runs, and its marker string proves the rebuilt
`startup-qemu-virt` is the one inside it.

The **guest disk is not pinned, and was never claimed to be.** The runs used
`disk-qemu` **without `-snapshot`**, so the guest wrote to it: on the board it now
hashes `f326b792486805c9406c1a0c6ccd6489bf2714aaf708aabc57f96cf06810ce68`, modified
during today's boots, and that value appears nowhere else in this repo. The PC copy
is `fd2ee67d…` (matching the a1.metal transfer-time hash), and
`qnx-safety-vm/output/SHA256SUMS` lists a third, `f3667fe3…`, which the 2026-09-09
analysis already established as the stale artefact.

None of the figures below depend on the disk's contents: the GPU throughput is
measured on L4T, and guest liveness is a byte-exact frame echo. But a later reader
should not infer a pinned disk from a pinned IFS. Future runs of this harness should
pass `-snapshot` so the disk stops drifting.

## Results

| arm | QNX guest | mean GFLOP/s | GR3D mean | GR3D peak | rounds |
|---|---|---|---|---|---|
| baseline  | none    | 1554.6 | 84% | 99% | 890 |
| baseline2 | none    | 1553.9 | 84% | 99% | 890 |
| concurrent  | live under KVM | 1557.2 | 84% | 99% | 892 |
| concurrent2 | live under KVM | 1558.2 | 84% | 99% | 892 |

Solo spread: 0.7 GFLOP/s across the two baselines. Both concurrent runs sit
~3-4 GFLOP/s ABOVE both solo runs, i.e. the concurrency "cost" is negative,
which is only interpretable as run-to-run noise.

QNX liveness during the runs: ~~16/16 frames byte-exact (3 before load, 5 during,
5 during, 3 after), sub-millisecond,~~ **2026-09-19 correction: 21/21 frames
byte-exact across five connections (3 + 5 + 5 + 3 + 5), per the capture at
`guest-kvm.redacted.log:21-30`. The 16/16 figure was a mid-experiment count,
written before the second concurrent run's probe; it undercounted. "Sub-millisecond"
was also wrong — the range below is the measurement, and 1.55 ms is not
sub-millisecond.** Mean RTT 0.62-1.55 ms. The guest's own
serial log independently corroborates every connection:

    server: client connected from <redacted>:53832
    server: client EOF after 3 frames
    server: client connected from <redacted>:53842
    server: client EOF after 5 frames
    server: client connected from <redacted>:45630
    server: client EOF after 5 frames
    server: client connected from <redacted>:43456
    server: client EOF after 3 frames

## Reading

The concurrent runs are nominally FASTER than the solo baseline. That is the
point: the difference is run-to-run noise, not a concurrency cost. Do not quote
it as a speedup.

## What this does NOT show

- Not a GPU partitioning, isolation or freedom-from-interference result. Nothing
  divides the GPU; L4T owns it outright and QNX never touches it.
- No claim that QNX can use the GPU. It cannot, in this architecture.
- Not a latency measurement. The probe RTTs are a liveness signal: one host,
  slirp NAT, tiny sample, no percentiles.
- Not a load, stress or soak test. 30 s per arm, the guest otherwise idle.
- Small n (2 per arm) and no thermal control; the board was at ~47-48 C.
- The GPU load is synthetic ALU work, not a representative inference workload.
