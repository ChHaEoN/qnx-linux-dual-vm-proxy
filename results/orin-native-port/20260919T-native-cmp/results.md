# Is the guest's degradation virtualisation, or a saturated box? — native control, 2026-09-19

The saturation run earlier that day measured the QNX guest's round trip at
**+53.9% p50** (pooled) under six-thread CPU load, and listed in its own
limitations that no comparison against a native process had been run. This is
that comparison.

It asks: **does the degradation the QNX guest shows under CPU saturation
require a virtualisation-specific explanation?** The measurement says no — the
same program, built natively and run on the same board under the same load,
degrades by a comparable amount. That **confirms what the saturation run
predicted**; its committed caveat, that the shift "is **not** evidence of a
virtualisation-specific effect", was an expectation and is now backed by a
control.

What was *not* predicted is the direction, and it is the part to read carefully:
measured as a percentage of each path's own baseline, the native process
degrades **more**. Measured as absolute added milliseconds, the ordering
**reverses**. Both readings are below, because the choice of metric decides the
answer and hiding that would make this record misleading.

## What "the same protocol" means here

The server is `ipc-test/qnx-safety-monitor/monitor.c`, **unmodified**, built
twice:

- cross-compiled into the QNX guest's IFS (`ifs-demo2.bin`), and
- compiled natively on L4T with `gcc -O2 -std=gnu99 -Wall -Wextra -I common`
  → a 13,976-byte aarch64 ELF.

Same 64-byte frame (`ipc-test/common/frame.h`: `uint64 seq`,
`uint64 tstamp_cycles`, 48-byte payload, little-endian), same accept/reject
logic, same port number 7100, same probe
(`orin-native/gpu-concurrency/latency_probe.py`).

One source building for both is a property of the program, not a convenience.
`monitor.c`'s includes are `stdio`, `stdlib`, `string`, `unistd`, `signal`,
`errno`, `sys/socket.h`, `netinet/in.h`, `netinet/tcp.h`, `arpa/inet.h`, plus
`frame.h` and `frame_io.h` — and there is no `ClockCycles`, `devctl`,
`name_attach`, `iofunc`, `dispatch`, `MsgSend`/`MsgReceive`,
`<sys/neutrino.h>` or `<sys/procmgr.h>` anywhere in the code. It is pure POSIX,
so the native arm runs the same program rather than a reimplementation of it.
Without that, any difference between the two columns could be a difference
between two servers.

## Method

**Guest.** QNX under KVM, launched by the board's own `launch-demo-guest.sh` —
verbatim the configuration that produced the earlier figure:
`qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm -smp 2
-m 1G`, virtio-blk with `snapshot=on`, virtio-net on `tap-qnx` bridged to
`br0`, virtio-rng, `-kernel ifs-demo2.bin`. The guest banner confirmed
`QEMU_virt_(aarch64),_KVM_guest`. The disk's sha256 prefix `f326b792486805c9`
was unchanged before and after the run, so `snapshot=on` held.

**Probe.** 3000 timed samples per arm, 200 warm-up samples timed and discarded,
2 ms interval, **one held TCP connection** per arm. The native arm probes
loopback on the host; the guest arm probes the guest over `br0`. Both servers
listen on port 7100 — no conflict, since they sit on different stacks and
addresses.

**Load.** `orin-native/gpu-concurrency/cpuload.c`, 6 threads on 6 cores: the
same control the saturation run used.

**The two arms are not identically loaded, and the asymmetry runs against the
guest.** Under `guest_cpu6` the six cores carry six load threads *plus* the
guest's two vCPU threads *plus* QEMU's I/O thread *plus* the probe; under
`native_cpu6` they carry six load threads plus the server and the probe. The
guest arm is the more oversubscribed of the two. That matters for how the
result is read: it is not a like-for-like contention level.

**Governor.** Pinned to `performance` on all six cores for the whole run,
verified at 1344000 kHz on all six, and restored to `schedutil` on all six
afterwards. Without this the idle arms would be measured on a ~40% slower
machine than the loaded ones (see the harness README).

**Arms, interleaved, two rounds:** `native_idle` → `guest_idle` →
`native_cpu6` → `guest_cpu6`, then repeated. Interleaved because on this board
a single-round difference has already dissolved on repeat once before.

**Conditions.** Board at 47–48 °C, 6119 MB free. `bad=0` and
`rejected_by_monitor=0` in every arm. A native smoke test before the run had
the monitor report `seen=250 accepted=250 rejected=0`.

`run-native-cmp.sh` in this directory is the script that ran; the per-arm
sample sets are the `lat-*.json` files beside it.

## Result

Per arm, n=3000, `bad=0` `rej=0` everywhere (ms):

| arm | p50 | p90 | p99 | p99.9 | max |
|---|---|---|---|---|---|
| native_idle_r1 | 0.044 | 0.047 | 0.076 | 0.133 | 0.285 |
| native_cpu6_r1 | 0.076 | 0.085 | 0.108 | 0.116 | 0.160 |
| guest_idle_r1 | 0.171 | 0.200 | 0.463 | 0.661 | 0.761 |
| guest_cpu6_r1 | 0.247 | 0.268 | 0.288 | 0.561 | 2.939 |
| native_idle_r2 | 0.046 | 0.056 | 0.086 | 0.270 | 0.799 |
| native_cpu6_r2 | 0.103 | 0.107 | 0.116 | 0.185 | 0.205 |
| guest_idle_r2 | 0.173 | 0.253 | 0.460 | 0.535 | 1.176 |
| guest_cpu6_r2 | 0.291 | 0.358 | 0.387 | 0.500 | 2.704 |

The two paths are **not** compared to each other in absolute terms. The guest's
round trip crosses virtio-net, `br0`, the tap, the guest's `io-sock` and the
guest's scheduler putting the monitor on a vCPU; the native one is loopback on
the same host. The guest's idle p50 is ~4× the native one (0.171 vs 0.044 ms)
for those path reasons alone.

### The metric decides the ordering, so both are given

**Relative** — each path against its own idle baseline:

| arm pair | p50 | p90 | p99 |
|---|---|---|---|
| native r1 | **+71.3%** | **+80.7%** | +41.7% |
| guest r1 | **+44.7%** | **+33.9%** | **−37.7%** |
| native r2 | **+123.1%** | **+90.4%** | +34.5% |
| guest r2 | **+68.0%** | **+41.6%** | **−15.7%** |

> **n = 2 rounds. These magnitudes are not estimates.** Between two identical
> rounds native p50 moves +71.3% → +123.1% — a spread wider than the
> native-vs-guest gap the finding rests on. Only the *ordering* replicated. No
> percentage in this table should be quoted as a magnitude.

**Absolute** — the same arms, in added milliseconds:

| arm pair | p50 added | p90 added |
|---|---|---|
| native r1 | +0.031 ms | +0.038 ms |
| guest r1 | **+0.076 ms** | **+0.068 ms** |
| native r2 | +0.057 ms | +0.051 ms |
| guest r2 | **+0.118 ms** | **+0.105 ms** |

The guest absorbs **1.8×–2.4×** more added latency than the native process in
every pairing. A percentage is taken against each path's own baseline, and
those baselines differ ~4× for path reasons, so the ratio mechanically flatters
the slower path. Neither view is "the" answer; the relative one is used as
primary only because two different network paths make absolute latencies
incomparable in the first place.

### 1. The +54% does not require a virtualisation-specific explanation

In relative terms, in both rounds, at both p50 and p90, the native process
degrades at least as much as the guest: +71.3% against +44.7% at p50 in round
1, +123.1% against +68.0% in round 2 — four comparisons, four the same way.

So the saturation run's reading holds: **a plain L4T process on the same
saturated board, running the same server program under the same load, degrades
by a comparable amount.** What that retires is the reading of +53.9% as
evidence *for* a virtualisation cost.

It does **not** show that no virtualisation component exists. This run cannot
exclude one: the comparison is confounded by the ~4× baseline difference above,
the guest arm is the more oversubscribed of the two, and in absolute terms the
guest absorbs about twice the added delay. "Not shown to be
virtualisation-specific" is the claim; "virtualisation contributed nothing" is
not.

Nor does it generalise to "any process". One program, one synthetic load, one
board, two rounds.

### 2. At p99 the two paths move opposite ways; deeper in the tail they do not

Under load the guest's **p99** improves (−37.7%, −15.7%) while the native
**p99** worsens (+41.7%, +34.5%). Both replicate across the two rounds.

**This is a p99 statement only, and one quantile out it dissolves.** At p99.9
the native arms improve too (−12.5%, −31.5%), so tail improvement under load is
*not* specific to the guest path. At the maximum the picture inverts outright:
native max improves sharply (−43.8%, −74.3%) while the guest's max blows out
(+286.5%, +130.0%) — the two largest samples in the whole experiment, 2.939 ms
and 2.704 ms, are both guest arms under load.

**The mechanism was not measured.** The standing hypothesis — busy cores never
enter idle states, so nothing pays a wake-up latency — is carried over from the
saturation run and is **untested here**: no C-state residency, no wake-up
latency and no scheduler tracing were recorded. As stated it would apply to the
native path too, where p99 instead gets worse, so it does not account for the
split. HYPOTHESIS only.

## What this does NOT show

- **Absolute latency is not comparable between the two paths, and is never
  compared here.** The guest round trip crosses virtio-net + `br0` + tap +
  `io-sock` + the guest's scheduler; the native one is loopback on the same
  host. Only each path's degradation against its own baseline is compared.
- **The headline holds under one metric and reverses under the other.** In
  absolute added latency the guest absorbs 1.8×–2.4× more than the native
  process. "Degrades less" is a statement about ratios, and ratios flatter the
  path with the larger baseline.
- **Not a measurement of virtualisation overhead**, and not a KVM-vs-native
  performance claim. No leg anywhere in this repo has a non-KVM control for
  this guest, so no such figure exists to make.
- **Not a partition-isolation, freedom-from-interference or real-time claim of
  any kind — certified or otherwise.** If anything the opposite: host CPU load
  measurably moves the guest's round trip, so what is measured here is
  interference reaching the guest, not evidence against it. Nothing in this
  project is certified, no ISO 26262 or ASIL claim attaches, and under A6 the
  boundary is KVM — Linux owns the QNX guest's memory.
- **The two arms are not identically loaded.** The guest arm additionally
  carries two vCPU threads and QEMU's I/O thread on the same six cores.
- **Not a load, stress or soak test.** Each arm is about 7 s of sampling —
  3,200 frames (200 warm-up + 3,000 timed) at 2 ms spacing, 6.5–7.3 s across
  the eight arms.
- **n = 2 rounds per arm pair.** The rounds agree in *direction*; the
  magnitudes vary substantially. Only the ordering survived repetition.
- **The tail-improvement mechanism is a HYPOTHESIS**, not a finding.
- **Says nothing about the GPU.** No GPU arm was run here.
- One board, one workload, one synthetic load, one direction of traffic.
