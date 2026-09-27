# `results/cloud/` — read this before citing anything in here

**The data this directory held is kept locally, not in the public repository.**

`cloud-ipc-latest.csv` — the one CSV this directory held — is the result of a
performance evaluation of QNX software (the QNX Hypervisor and a QNX guest).
The QNX licence, NC QDL v7 clause 4.6(i), forbids making "the results of any
performance or functional evaluation of the Software" available to any third
party without BlackBerry's prior written approval, which has not been obtained.
On 2026-09-27 the owner decided that measurement results stay local, so the CSV
was removed from the public tree. Only the schema, `header.csv`, stays.
`results/hw/` is in the same state: its `orin-ipc-latest.csv` is held locally and
its `header.csv` stays.

## The schema

`header.csv` is shared with `results/hw/header.csv`; both legs wrote one flat row
per run, with no header row of their own:

| column | meaning |
|---|---|
| `unix_ts` | when the run's summary was recorded |
| `samples` | timed samples in the run, warm-up excluded |
| `payload_bytes` | the frame's payload size (48 for every run to date) |
| `p50_ns`, `p99_ns`, `max_ns` | round-trip time quantiles and the largest observed value, in ns |
| `cycles_per_sec` | the QNX clock rate used to convert `ClockCycles()` to ns; a nominal `1000000000` placeholder on the Linux side, which times with `clock_gettime` |
| `notes` | free text; the only place a run can say anything the columns cannot |

The QNX host program `ipc-test/qnx-host-client` prints the summary line, and
`scripts/qhv/extract-ipc-result.sh` transcribes it from a captured serial log
into this schema; it never invents a number.

## Nothing here was ever measured on a cloud host

The removed CSV was recorded on the owner's local **x86_64 Windows PC** under
QEMU **TCG**. The directory is named after architecture **A1**, which this
project calls "the cloud leg", and that name is the only thing cloud about it.

A1 was *designed* to run on an AWS Graviton `c7g.large` runtime host. That host
was never built: [ADR-002](../../docs/phase2-topology-decision.md) found in
2026-06 that non-metal Graviton exposes no `/dev/kvm` at all, and once KVM was
off the table nothing required the leg to be in the cloud, so it ran on the
Windows PC instead.

The directory keeps its name because `scripts/twin/diff-results.sh`,
`scripts/ci/claims_gate.py`, the CI workflows and a number of documents all
reference this path, and renaming it would break those references for a cosmetic
gain. A directory name cannot carry a caveat; this file is that caveat.

What the removed CSV was, as configuration: a local Windows PC (x86_64), QEMU
TCG (never KVM), the `qvm` virtio-console vdev between a QNX host and a QNX
guest, transcribed from the serial log `qhv-tcg-ipc-benchmark.log` (also held
locally). Against `results/hw/`'s Orin run it is not a like-for-like comparison
in any respect: different host, different ISA, different transport, different
OS pair, different sample size. `diff-results.sh` prints that warning at run
time.

## Why that leg is TCG

A1 is the QNX Hypervisor (`qvm`) hosting a QNX guest, and the transport is QHV's
own virtio-console vdev. QHV has to run at EL2. A KVM guest only ever gets EL1,
and KVM on `a1.metal`'s Cortex-A72 offers no nested virtualisation, so KVM can
host a QNX *guest* there but not a QNX *hypervisor*. That left TCG, which
emulates EL2, or bare metal, which is A4 on the Orin. OD10 (2026-09-20) withdrew
the TCG legs, so that record is history: it is not re-run, and it never will be
under KVM.

## What has been run on a cloud host

Three things, all on `a1.metal` under KVM with QNX as a guest (A6), none of them
what this directory's CSV was, and all held locally under NC QDL v7 4.6(i):

- **Boot timing** (2026-09-20): a byte-identical QNX IFS under KVM on `a1.metal`
  and on the Jetson Orin Nano — record `20260920T-kvm-twin`.
- **A6's attribution ladder over TCP** (2026-09-21): the same four arms as on
  the Orin, a 64-byte round trip from the host to the guest's monitor — record
  `20260921T-ladder-a1metal`. Graviton1 is a Cortex-A72 against the Orin's
  A78AE, on a different kernel, so the pair differs in a bundle of variables,
  not one.
- **The Orin's notified-shared-memory ladder** (2026-09-22), run again on
  `a1.metal` with the same image, disk, QEMU build and tooling: TCP, the D-udp
  rung, the polled shared-memory slot, and the notified slot with a
  virtio-console kick in and a console reply or an `ivshmem` doorbell out —
  record `20260922T-a6-a1metal-kick`.

No throughput figure has been taken on a cloud host. No figure has been taken
on any cloud host other than `a1.metal`; a `t4g.small` was only probed for
`/dev/kvm`. And no cloud leg in this project's sense — a QHV host plus a guest —
has been built.
