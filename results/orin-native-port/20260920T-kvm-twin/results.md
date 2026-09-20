# The KVM twin, measured — 2026-09-20

First measurement of the pairing described in
[`docs/digital-twin-design.md` §1b](../../../docs/digital-twin-design.md). The
byte-identical IFS boots under KVM on a Jetson Orin Nano and on an AWS
`a1.metal`, so for the first time in this project a cloud↔board comparison
actually holds the identical-image invariant rather than intending to.

## The headline is not the number, it is that the obvious number is mostly an artefact

Timing the boot to `Startup complete` — the natural metric, and the one §1b
proposed — makes the two hosts look 3.6% apart. **That figure is 92% a fixed
timeout.** With no disk attached, QNX's boot script waits for `/dev/hd0` and
gives up after five seconds, and that five seconds is identical on both hosts:

| host | wait between `xpt_configure` and `Unable to access /dev/hd0` |
|---|---|
| Orin Nano (Cortex-A78AE) | **5001.3 ms** |
| AWS `a1.metal` (Cortex-A72) | **5000.3 ms** |

One millisecond apart, on two different vendors' silicon, five years of
micro-architecture apart. Line traces: [`orin-linetrace.txt`](orin-linetrace.txt),
[`aws-linetrace.txt`](aws-linetrace.txt). A second pair of traces taken earlier
in the same session read 5001.0 ms and 5000.7 ms.

So the metric §1b proposed is a poor discriminator, and quoting "+3.6%" as a
host comparison would have been misleading. It is recorded here in full anyway,
because the correction is the result.

## What was measured

| | Jetson Orin Nano | AWS `a1.metal` (inst. 1) | AWS `a1.metal` (inst. 2) |
|---|---|---|---|
| host CPU | Cortex-A78AE, Tegra234 | Cortex-A72, Graviton1 | Cortex-A72, Graviton1 |
| host kernel | 5.15.148-tegra | 6.8.0-1063-aws | 6.8.0-1063-aws |
| QEMU | 6.2.0 `Debian 1:6.2+dfsg-2ubuntu6.31` | *same package build* | *same package build* |
| IFS sha256 | `26170cd7dc74c216…` | *identical* | *identical* |
| governor | pinned `performance`, 1344 MHz | no cpufreq exposed | no cpufreq exposed |
| **to `Startup complete`**, median of n=5 | **5412.27 ms** | **5225.89 ms** | **5225.49 ms** |
| min / max | 5408.84 / 5423.26 | 5225.38 / 5226.45 | 5225.15 / 5226.42 |
| spread (n=5) | 14.42 ms | 1.07 ms | 1.27 ms |
| **to first serial byte**, median of n=5 | **362.01 ms** | **166.09 ms** | **165.51 ms** |
| serial bytes captured | 621 | 621 | 621 |

Launch line, byte-identical on both sides, no disk:

```
qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm \
                    -smp 2 -m 1G -kernel ifs-kvmfix.bin -nographic
```

Raw records: [`orin-nano.json`](orin-nano.json),
[`aws-a1metal.json`](aws-a1metal.json),
[`aws-a1metal-instance2.json`](aws-a1metal-instance2.json). Each carries its own
host, kernel, QEMU version, IFS hash, governor state before and after, and every
individual run.

## What the numbers say once the timeout is removed

Subtracting the measured `/dev/hd0` wait from the line traces leaves the work
that actually depends on the host:

| | Orin Nano | `a1.metal` | ratio |
|---|---|---|---|
| trace: `Startup complete` minus the hd0 wait | 463.1 ms | 224.4 ms | **2.06×** |
| n=5: time to first serial byte | 362.01 ms | 166.09 ms | **2.18×** |

The Orin takes about twice as long to get the guest talking. **This is not a
per-core performance claim.** That interval covers QEMU process start, KVM
setup, loading a 9.77 MB IFS into guest memory and the guest's own early
startup, and the two hosts differ in clock (the Orin pinned at 1344 MHz under
the 25 W nvpmodel profile; Graviton1's A72 is firmware-clocked with no OS
control), in kernel, and in memory subsystem. It is a host-bundle difference, as
[§1a](../../../docs/digital-twin-design.md) requires all of these comparisons to
be read.

The variance is the other observation worth keeping. `a1.metal` repeated to
within 1.3 ms across five runs and to within **0.4 ms across two separately
launched instances** (medians 5225.89 and 5225.49). The Orin's spread is 13×
wider at 14.42 ms, on a pinned governor. Not explained here; no scheduler or
interrupt tracing was done.

## What this does not show

- **Nothing about the QNX Hypervisor.** It cannot run under KVM at all — it
  needs EL2, and ARM KVM does not nest on A78AE. No hardware-timed *hypervisor*
  number exists, and this is not one.
- **Not a QNX-supported configuration.** The `startup-qemu-virt` inside this IFS
  was rebuilt in this repo with `-fno-auto-inc-dec`; QNX ships no such binary,
  and the SDP's own startup still hangs under KVM on both hosts.
- **Nothing about filesystems, networking or IPC.** No disk was attached, on
  purpose — the guest disk is the one artefact known to drift, and the
  2026-09-18 record says its runs wrote to it without `-snapshot`. This measures
  IFS load, startup and procnto init and stops there.
- **Nothing about A6's GPU half.** `a1.metal` has no GPU.
- **Not a single-variable comparison.** A72 against A78AE is five years of
  micro-architecture inside a bundle that also differs in kernel and clock.
  `c7g.metal` (Neoverse-V1) would be the closer core match and stays
  quota-blocked at 64 vCPU against a 32-vCPU account limit.
- **The governor is pinned on one side only.** `a1.metal` exposes no
  `cpufreq` and no `cpuidle` at all, so nothing there could be pinned. That is a
  stated limit, not a controlled variable.
- **n=5 per arm.** Small. The `a1.metal` figures replicate across two instances;
  the Orin's do not have a second-board check and cannot have one.

## Method notes

Timing is taken by [`scripts/twin/time-kvm-boot.py`](../../../scripts/twin/time-kvm-boot.py)
**on the host being measured**, from its own monotonic clock, so nothing crosses
a network before the timestamp. Each arm ran one discarded warm-up then five
timed boots. The Orin's governor was pinned to `performance` for the run and
restored to `schedutil` afterwards, verified in the record's `cpu_before` and
`cpu_after` fields.

Both AWS instances were launched with
`--instance-initiated-shutdown-behavior terminate` plus a `shutdown -h +45`
safety net, terminated immediately after capture, and verified to leave no
running instance and no orphaned volume. Host names, instance ids, account ids
and IP addresses are redacted in every file here, at capture time.
