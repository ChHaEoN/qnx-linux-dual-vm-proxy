# The KVM twin, measured — 2026-09-20

First measurement of the pairing described in
[`docs/digital-twin-design.md` §1b](../../../docs/digital-twin-design.md): the
byte-identical IFS boots under KVM on a Jetson Orin Nano and on an AWS
`a1.metal`, so for the first time in this project a cloud↔board comparison
actually holds the identical-image invariant rather than intending to.

**The result is a method finding, not a performance headline.** Timed end to
end, the two hosts look 5% apart. Almost all of that boot is fixed waits that do
not depend on the host at all, and the only segment that genuinely separates
them differs by **2.45×**. Three separate constants had to be found and removed
before the comparison said anything.

## What was identical

| | value |
|---|---|
| IFS | `ifs-kvmfix.bin`, sha256 `26170cd7dc74c216…` — verified on both hosts after transfer |
| guest disk | `disk-qemu`, sha256 `f326b792486805c9…` — verified on both, and **unchanged after every run** |
| QEMU | 6.2.0, `Debian 1:6.2+dfsg-2ubuntu6.31` — the *same package build* on both |
| launch | `-machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G` |
| devices | `virtio-blk`, `virtio-net` (SLIRP, fixed MAC), `virtio-rng` — **in that order** |

The device order is load-bearing. QEMU's `virt` machine hands its fixed
virtio-mmio slots to `-device` arguments strictly in command-line order, and
this image's `startup.sh` binds absolute addresses (`devb-virtio` at
`smem=0xa003e00`, `devr-virtio.so` at `mem=0xa003a00`). Present them in another
order, or omit one, and the rng slot is empty, entropy never initialises, and
`io-sock` refuses to start — which looks exactly like a virtio-net bug
(findings.md, 2026-07-28). SLIRP rather than a tap, so the device set does not
depend on a local bridge.

`-snapshot` is used on both sides and is not optional: the 2026-09-18 record
states its runs used this disk *without* it, so the guest wrote to the backing
file and the board's copy drifted away from the PC's. With `-snapshot` the
before/after hash is identical on every run, on both hosts.

## The three constants

Each was found by timestamping every serial line, and each one had been hiding
inside the end-to-end number:

| wait | Orin (A78AE) | `a1.metal` (A72) | cause |
|---|---|---|---|
| `waitfor /dev/hd0` | 5001.3 ms | 5000.3 ms | no disk attached; the stock `startup.sh` has no timeout argument, so it takes QNX's 5 s default |
| `waitfor /dev/random` | 5006.1 ms | — | no `virtio-rng` presented; entropy never initialises |
| network bring-up | 4218.8 ms | 4219.4 ms | `---> Starting Networking` to `Startup complete`, with the full device set |

Every one of them agrees across the two hosts to within about a millisecond.
That is the point: **a software timeout does not care how fast the CPU is**, so
any metric containing one makes two different machines look similar. The
diskless configuration was 92% artefact; adding only the disk made it *worse*
(24.7 s, because the boot then got far enough to hit the entropy wait).

## The measurement, segment by segment

Medians of n=5 timed boots per host, one discarded warm-up, full device set:

| segment | Orin A78AE | `a1.metal` A72 | ratio |
|---|---|---|---|
| QEMU exec → first serial byte | **410.7 ms** | **167.8 ms** | **2.45×** |
| first byte → mounting file systems | 57.1 ms | 60.1 ms | 0.95× |
| mounting → starting networking | 65.8 ms | 66.0 ms | 1.00× |
| networking → `Startup complete` | 4218.8 ms | 4219.4 ms | 1.00× |
| `Startup complete` → guest banner | 3.8 ms | 5.6 ms | 0.67× |
| **total: exec → guest banner** | **4747.0 ms** | **4519.0 ms** | **1.05×** |

One segment separates the hosts and it is the first one. Everything after the
guest starts talking is either equal within noise or a constant. Quoting the
total — 1.05× — as a host comparison would be wrong by a factor of two in the
wrong direction.

**What the 2.45× segment is.** QEMU process start, KVM setup, loading a 9.77 MB
IFS into guest memory, and the guest's own execution up to its first serial
write. It is **not** a per-core performance claim: the hosts differ in clock
(the Orin pinned at 1344 MHz under the 25 W `nvpmodel` profile; Graviton1's A72
is firmware-clocked with no OS control), in kernel, and in memory subsystem — a
host *bundle* difference in the sense
[§1a](../../../docs/digital-twin-design.md) requires.

## Variance

| | n=5 spread on `Startup complete` |
|---|---|
| Orin Nano, governor pinned to `performance` | 35.51 ms |
| `a1.metal` | 2.16 ms |

The AWS host is **16× more repeatable**, and in the earlier diskless
configuration two *separately launched* `a1.metal` instances agreed to 0.4 ms on
the median. The Orin's spread is wider despite a pinned governor. Not explained
here — no scheduler or interrupt tracing was done, and the Orin is running a
full L4T desktop while the AWS host is a fresh minimal image.

## Records

| file | what |
|---|---|
| [`orin-nano-full-devices.json`](orin-nano-full-devices.json) | the measurement above, Orin side |
| [`aws-a1metal-full-devices.json`](aws-a1metal-full-devices.json) | the measurement above, AWS side |
| [`orin-full-devices-linetrace.txt`](orin-full-devices-linetrace.txt) | per-line timestamps, Orin |
| [`aws-full-devices-linetrace.txt`](aws-full-devices-linetrace.txt) | per-line timestamps, AWS |
| [`orin-nano.json`](orin-nano.json), [`aws-a1metal.json`](aws-a1metal.json), [`aws-a1metal-instance2.json`](aws-a1metal-instance2.json) | the diskless control that found the first constant |
| [`orin-linetrace.txt`](orin-linetrace.txt), [`aws-linetrace.txt`](aws-linetrace.txt) | per-line timestamps, diskless |

Every record carries its own host, kernel, QEMU version, IFS and disk hashes,
device set, governor state before and after, and each individual run.

## What this does not show

- **Nothing about the QNX Hypervisor.** It cannot run under KVM at all — it
  needs EL2, and ARM KVM does not nest on A78AE. **No hardware-timed
  *hypervisor* number exists and this is not one.**
- **Not a QNX-supported configuration.** The `startup-qemu-virt` in this IFS was
  rebuilt in this repo with `-fno-auto-inc-dec`; QNX ships no such binary, and
  the SDP's own startup still hangs under KVM on both hosts.
- **Not a per-core or per-vendor performance claim.** See the bundle note above.
- **Nothing about A6's GPU half.** `a1.metal` has no GPU.
- **Not a single-variable comparison.** Cortex-A72 against Cortex-A78AE is five
  years of micro-architecture inside a bundle that also differs in kernel and
  clock. `c7g.metal` (Neoverse-V1) would be the closer core match and stays
  quota-blocked at 64 vCPU against a 32-vCPU account limit.
- **The governor is pinned on one side only.** `a1.metal` exposes no `cpufreq`
  and no `cpuidle` at all, so nothing there could be pinned. A stated limit, not
  a controlled variable.
- **Not a throughput, latency or IPC measurement.** This is boot only. The guest
  reaches its echo server listening on `:7000`, and nothing was sent to it.
- **n=5 per arm.** Small. The AWS side replicated across two separately launched
  instances in the diskless control; the Orin side has no second board.

## Method

Timing is taken by [`scripts/twin/time-kvm-boot.py`](../../../scripts/twin/time-kvm-boot.py)
**on the host being measured**, from its own monotonic clock, so nothing crosses
a network before the timestamp. One discarded warm-up then five timed boots per
arm. The Orin's governor was pinned to `performance` for each run and restored
to `schedutil` afterwards, recorded in every record's `cpu_before`/`cpu_after`.

Three `a1.metal` instances were used across the session, each launched with
`--instance-initiated-shutdown-behavior terminate` plus a `shutdown -h +45`
safety net, terminated immediately after capture, and verified to leave no
running instance and no orphaned volume. Host names, instance ids, account ids
and IP addresses are redacted in every file here, at capture time.
