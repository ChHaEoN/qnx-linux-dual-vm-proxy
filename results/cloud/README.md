# `results/cloud/` — read this before citing anything in here

**Nothing in this directory was measured on a cloud host.**

`cloud-ipc-latest.csv` was recorded on the owner's local **x86_64 Windows PC**
under QEMU **TCG**. The directory is named after architecture **A1**, which this
project calls "the cloud leg", and that name is the only thing cloud about it.

## Why the name is wrong and still here

A1 was *designed* to run on an AWS Graviton `c7g.large` runtime host. That host
was never built: [ADR-002](../../docs/phase2-topology-decision.md) found in
2026-06 that non-metal Graviton exposes no `/dev/kvm` at all, and once KVM was
off the table nothing required the leg to be in the cloud, so it ran on the
Windows PC instead. `docs/findings.md` records the correction in its own words:

> *"Cloud twin — AWS Graviton (c7g.large)"* — as built, every QHV boot and IPC
> number attributed to "cloud" was produced on the **local Windows host**.

The directory keeps its name because `scripts/twin/diff-results.sh`,
`scripts/ci/claims_gate.py`, the CI workflows and a number of documents all
reference this path, and renaming it would break those references for a cosmetic
gain. A directory name cannot carry a caveat; this file is that caveat.

## What the CSV actually is

| field | value |
|---|---|
| host | local Windows PC, x86_64 |
| acceleration | QEMU TCG (never KVM) |
| transport | `qvm` virtio-console vdev, QNX host ↔ QNX guest |
| samples | **15** |
| provenance | transcribed from a serial log, `qhv-tcg-ipc-benchmark.log` |

Fifteen samples, capped by an unresolved `qvm`/TCG virtio-queue stall that was
never root-caused. It is a **mechanism-alive sanity figure**, not a benchmark.
Against `results/hw/`'s 100,000-iteration Orin run it is not a like-for-like
comparison in any respect: different host, different ISA, different transport,
different OS pair, different sample size. `diff-results.sh` prints that warning
at run time; read it.

## Why it is still TCG, now that a cloud host has KVM

Because what it measures cannot run under KVM. A1 is the QNX Hypervisor (`qvm`)
hosting a QNX guest, and the transport is QHV's own virtio-console vdev. QHV has
to run at EL2. A KVM guest only ever gets EL1, and KVM on `a1.metal`'s
Cortex-A72 offers no nested virtualisation, so KVM can host a QNX *guest* there
but not a QNX *hypervisor*. That left TCG, which emulates EL2, or bare metal,
which is A4 on the Orin (figures unpublished). OD10 (2026-09-20) withdrew the
TCG legs, so this figure is history: it is not re-run, and it never will be
under KVM.

## What has been measured on a cloud host

Three things, all on `a1.metal` under KVM with QNX as a guest (A6), and none
of them is what this directory's CSV measures:

- **Boot timing** (2026-09-20). A byte-identical QNX IFS booted under KVM on
  `a1.metal` and on the Jetson Orin Nano, and both sides were timed — see
  [`results/orin-native-port/20260920T-kvm-twin/`](../orin-native-port/20260920T-kvm-twin/results.md).
- **A6's attribution ladder over TCP** (2026-09-21). The same four arms as on
  the Orin, a 64-byte round trip from the host to the guest's monitor; the
  attribution ladder put it at 224.3 µs at p50 on that instance — see
  [`results/orin-native-port/20260921T-ladder-a1metal/`](../orin-native-port/20260921T-ladder-a1metal/results.md).
  Graviton1 is a Cortex-A72 against the Orin's A78AE, on a different kernel,
  so the pair differs in a bundle of variables, not one.
- **The Orin's notified-shared-memory ladder** (2026-09-22), run again on
  `a1.metal` with the same image, disk, QEMU build and tooling: TCP, the D-udp
  rung, the polled shared-memory slot, and the notified slot with a
  virtio-console kick in and a console reply or an `ivshmem` doorbell out.
  Within each run, the order of the paths and the doorbell's lead over TCP
  replicate: 97 µs on `a1.metal`, 92 µs on the Orin. But TCP in that image pays
  for what the image adds for its kick, most plausibly the guest's virtio console
  driver: 34–38 µs, isolated on the Orin
  ([record](../orin-native-port/20260922T-a6-orin-shift/results.md)). The
  `a1.metal` TCP rungs sat about 76 µs above an earlier `a1.metal` ladder. If that
  is the same cost (not isolated there, and about twice the Orin's), the doorbell
  arm on `a1.metal` is about 21 µs faster than that earlier ladder's TCP, which
  was measured on another instance with another image and script revision.
  The cost of the console reply does not replicate — see
  [`results/orin-native-port/20260922T-a6-a1metal-kick/`](../orin-native-port/20260922T-a6-a1metal-kick/results.md).

No throughput figure has been taken on a cloud host. No figure has been taken
on any cloud host other than `a1.metal`; a `t4g.small` was only probed for
`/dev/kvm`. And no cloud leg in this project's sense — a QHV host plus a guest —
has been built.
