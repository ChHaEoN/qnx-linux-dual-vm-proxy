# M2: QNX on all six cores of the Jetson Orin Nano

2026-09-10. The M2 design ([m2-design.md](m2-design.md)) was implemented, reviewed and then run on the board as a ladder
of images that differ only in `-P`. Every run used the same loop:

1. Stage the image and check its hash on the board.
2. Open the COM3 capture.
3. `kexec`.
4. Wait for L4T to come back with a new `boot_id`.
5. Read the black box from pstore.

**M2 is met.** Run R4 (`-P6`) passed every criterion in the design's section 8 in one run. R4b repeated it with the
identical image. R5 added a tracelogger capture, which recorded events on all six cores. Curated capture of R4:
[logs/sample-boot/orin-native-m2-six-cores.log](../../../logs/sample-boot/orin-native-m2-six-cores.log).

## The runs

All images use one startup build and one smpcheck build. Only `-P`, the busy-worker lines and R5's trace lines differ.
Times are UTC.

| Run | Image | kimg sha256 prefix | Launch | Back after | Black box | Result |
|---|---|---|---|---|---|---|
| R0, first attempt | m2-p1 | 1f5f1331bd2dd11d5799e82d | 10:33:41 | 193 s | Linux only | **Did not run.** Linux panicked in its own kexec shutdown (below) |
| R0 | m2-p1 | 1f5f1331bd2dd11d5799e82d | 10:42:40 | 147 s | 7,169 B | `SMPCHECK RESULT PASS-DEGRADED cpus=1/6`; M1's path unchanged |
| R1 | m2-p2 | 6e2ce6b76de95eac8d5260ec | 10:46:43 | 149 s | 9,604 B | `PASS-DEGRADED cpus=2/6`; first secondary core |
| R2 | m2-p4 | 0a4e20c2c54b1002a4a3d044 | 10:50:09 | about 130 s | 14,340 B | `PASS-DEGRADED cpus=4/6`; all of cluster 0 |
| R3 | m2-p5 | ca5839e104c160594b196f5a | 10:59:11 | 149 s | 16,876 B | `PASS-DEGRADED cpus=5/6`; first cluster-1 core, first read of frames 4 and 5 |
| **R4** | **m2-p6** | **5cae65e821edcdb9c2355310** | **11:02:37** | **149 s** | **19,239 B** | **`SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`** |
| **R4b** | **m2-p6** | **5cae65e821edcdb9c2355310** | **11:06:21** | **148 s** | **19,239 B** | **`SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`** |
| **R5** | **m2-p6t** | **ffbf7a08eedc8f967fb22de0** | **11:10:33** | **155 s** | **20,085 B** | **`PASS cpus=6/6`; `SMPCHECK TRACE PASS cpus=6/6`** |

Every run that reached QNX ended in the image's own `shutdown -S reboot`. Its `resetting so the log can be recovered`
line is in the black box, and the PMC reported the reset as `MAINSWRST` (software reset), level L1. R2's "back after"
comes from the board's own uptime, because the run script stalled (below).

## What R4 shows, against the pass criteria

R4b and R5 showed the same on every point.

1. `t234: cpu N up` for N = 0..5, with no `MISMATCH`:

   | Core | MPIDR | Redistributor frame | idx | SGI1R |
   |---|---|---|---|---|
   | 0 | 0x81000000 | 0x0f440000 | 0 | 0x1 |
   | 1 | 0x81000100 | 0x0f460000 | 1 | 0x10001 |
   | 2 | 0x81000200 | 0x0f480000 | 2 | 0x20001 |
   | 3 | 0x81000300 | 0x0f4a0000 | 3 | 0x30001 |
   | 4 | 0x81010200 | 0x0f500000 | 6 | 0x100020001 |
   | 5 | 0x81010300 | 0x0f520000 | 7 | 0x100030001 |

   On every core, the library's own `cpuN: Core GICR SGI address` line reads base + 0x10000, as the design predicted.
2. Cores 1 to 5 each printed `entry EL2` and their firmware register values.
3. `t234: all 6 cpus parked in smp_spin` was followed by `System page at phys:` and `Starting next program`.
4. The kernel's `gic_map` and `gicr_map` sections hold the same six rows.
5. `pidin info` lists Processor1 to Processor6.
6. `SMPCHECK CENSUS PASS` was printed. Six pinned 60 s busy workers had zero misplaced samples and zero clock regressions,
   and both 100 ms timer checks ran on each worker's own core. The result line was
   `SMPCHECK RESULT PASS cpus=6/6 secs=60 reasons=none`.
7. `shutdown -S reboot` returned L4T with a new `boot_id` and the black box intact.
8. None of the design's failure signatures appear in the black box.

## R5: the tracelogger check

R5 ran the same load with `tracelogger -s 2 -f /dev/shmem/m2.kev` started alongside it. It then ran `traceprinter` into
`/dev/shmem`, and only counts reached the console. Both programs started with the four files the image added, and the
load passed as in R4. smpcheck counted 200,997 trace lines, 199,710 of them attributed to a CPU:

| CPU | Events |
|---|---|
| 0 | 46,254 |
| 1 | 46,216 |
| 2 | 45,878 |
| 3 | 45,884 |
| 4 | 7,747 |
| 5 | 7,731 |

The verdict was `SMPCHECK TRACE PASS cpus=6/6`. This shows that capture and printing completed with events on every
core. It does not show that the trace is correct or complete.

## Unknowns the runs answered

- **A QNX-issued `CPU_ON` enters the secondary at EL2 on both clusters.** QNX calls it from EL1; Linux's calls came from
  EL2.
- **Firmware leaves the same EL2 state on every secondary.** It was identical on all five cores and in every run:
  - `HCR_EL2=0x80000000`: RW only, not the VHE state CPU0 inherits from Linux.
  - `SCTLR_EL2=0x30c50830` and `MDCR_EL2=0x6`.
  - `HSTR_EL2`, `ICH_HCR_EL2` and the three timer controls are 0.
  - `CNTFRQ_EL0=0x1dcd650` is already programmed.
  - `AFFINITY_INFO` read OFF before every `CPU_ON`.
- **The 32-bit read of `GICR_TYPER` + 0xC returns the affinity.** M1 could not tell, because CPU0's affinity is 0.
- **Ranked unknown #10 is closed.** Frames 4 and 5 read without fault. They hold affinities 0x10000 and 0x10100, the two
  cluster-1 cores this SKU does not have, so the library walk passes them and binds frames 6 and 7.
- **Cluster 1 wakes with no extra firmware step.** `CPU_ON` at 0x10200 and 0x10300 returned success.
- **The kexec device tree carries six cpu nodes.** The counter is readable at EL1 at 31.25 MHz, which the deadlines use.
- **Every populated redistributor was already awake before its `CPU_ON`.** `WAKER` read 0, so the board's wake step never
  had to act, and no SGI or PPI was left active.
- **R0 left CPU0's M1 path unchanged** under the `break_detect_tcu` fix and the new board code.

## Observed, not a criterion: cluster 1 runs the busy loop at a fixed low rate

smpcheck's busy loop is informational only, because CPU frequency is not controlled in these runs. Its rates, in
iterations per second:

| Run | Cluster 0, per core | Cluster 1, per core |
|---|---|---|
| R0 | 363 million | not started |
| R1 | 363 million | not started |
| R2 | 401 million | not started |
| R3 | 439 million | 57.0 million (core 4) |
| R4 | 477 million | 57.1 million (cores 4 and 5) |
| R4b | 666 million | 57.1 million (cores 4 and 5) |
| R5 | 666 million | 57.0 million (cores 4 and 5) |

- **Cluster 1 held one rate while cluster 0 varied.** Both cluster-1 cores ran at the same rate in every run. Against
  cluster 0's varying rate, that works out to between about a tenth and an eighth.
- **Linux's last frequency settings do not explain the gap.** Just before R4's kexec, `schedutil` had cluster 0 at
  1,267,200 kHz and cluster 1 at 1,036,800 kHz, a ratio of about 0.82.
- **R5's trace rules out one explanation.** Each cluster-1 core logged about a sixth as many kernel events as a cluster-0
  core, not more, so there is no interrupt storm on those cores. The trace does not show what does explain the gap. A
  clock held at a fixed low setting after `CPU_OFF` and `CPU_ON` fits the constant rate, but the frequency was never
  measured.
- **It matters later.** Any hardware-timed number taken on cluster 1 would carry this factor.

## Three host-side problems, none of them in the QNX port

- **Linux panicked in its own kexec shutdown.** R0's first attempt never reached QNX:
  - At 2 h 25 min of uptime, network namespace teardown faulted in `tcp_metrics_flush_all+0x68` ("Unable to handle
    kernel paging request").
  - With `panic_on_oops=1` that became a panic, and `kernel.panic=0` means no automatic reboot.
  - systemd's two-minute hardware watchdog, no longer fed, reset the board (PMC: `BCCPLEXWDT`, level L1).
  - pstore kept both the Oops and the Panic dump. The black-box zone was untouched, because the shim never ran.

  The retry, from a freshly booted Linux, worked, and so did every later run. This also shows that a hang *before* the
  payload is recovered unattended, unlike a hang after it.
- **A serial capture started from a Git Bash background job received nothing.** One started from PowerShell received the
  same board output at once, and every run from R0's retry on used a PowerShell capture. A second capture cannot open
  COM3 while the previous one holds it; that aborted R1's first launch at the header check, before any `kexec`.
- **An SSH poll hung during R2.** It connected while Linux was shutting down and never returned, because a connect timeout
  does not bound an established session. The board had already come back; the run script only resumed minutes later.
  Later runs used keepalives and a hard timeout on every poll.

## Not shown

- **Anything under `-Q enable`.** Every core ran at EL1 with no hypervisor host. That is M1b and M3.
- **That the kernel's console callout is SMP-safe.** The payload kept one printer at a time and never tested it.
- **IPI delivery, measured directly.** Scheduling and pinning imply it.
- **That the tracelogger trace is correct or complete.**
- **Any timing or performance figure.** The rates above are uncontrolled.
- **Repeatability beyond R4, R4b and R5.**
