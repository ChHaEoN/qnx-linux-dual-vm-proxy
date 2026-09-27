# QHV (QNX Hypervisor) — Type-1 hypervisor hosting a guest, on QEMU-TCG

This recipe builds a **QNX Hypervisor (QHV)** host image that boots a **QNX
guest** underneath it, and runs the whole thing under `qemu-system-aarch64` in
**TCG** (pure software emulation). It needs no KVM and no special hardware — it
runs on the local Windows build host.

> **Why TCG and not KVM?** QHV (like KVM) needs the ARM virtualization
> extensions (EL2). AWS **non-metal** Graviton does not expose `/dev/kvm` / EL2
> (proven empirically — see `docs/findings.md`, 2026-06-11), so a hardware-
> accelerated QHV there would need a `*.metal` instance or real silicon (Jetson
> Orin). TCG emulates an EL2-capable CPU in software, which is enough to exercise
> the QHV **software** architecture: `qvm` config parsing, vdev instantiation,
> guest isolation, and the EL2/VHE host. It does **not** validate hardware timing
> or acceleration — that is the honest gap.

## Prerequisites

- QNX SDP 8.0 (Windows x86_64) with the **aarch64le** target packages, the
  **`com.qnx.qnx800.target.qemuvirt`** package (provides `startup-qemu-virt`),
  and the QHV host **`com.qnx.qnx800.target.hypervisor.core`** (provides `qvm`).
- QEMU for Windows: `winget install SoftwareFreedomConservancy.QEMU`.

## Build + run

```cmd
scripts\build-qhv.bat
powershell -ExecutionPolicy Bypass -File scripts\launch-qhv-tcg.ps1
```

`build-qhv.bat` builds `ipc-test/` (qcc) first, then does the two-stage
mkqnximage build (guest `--type=qvm`, then host `--type=qemu --qvm=yes
--guest=...`), staging `guest-post_start.custom` + the compiled
`qnx-echo-server` into the guest build tree and `post_start.custom` + the
compiled `qnx-host-client` into the host build tree so both auto-start.
`launch-qhv-tcg.ps1` boots it and captures the serial log.

## Cross-partition IPC benchmark (Phase 2)

The host's `post_start.custom` also runs the `qnx-host-client` <->
`qnx-echo-server` echo benchmark automatically, across the `qvm`
`virtio-console` vdev (host-side endpoint: the `hostdev /dev/ptyp0` pty pair;
guest-side endpoint: `/dev/vcon2`, brought up by `devc-virtio` in
`guest-post_start.custom`). See
[../../ipc-test/qnx-host-client/README.md](../../ipc-test/qnx-host-client/README.md)
for the wiring and for what the client does about the link (raw mode, a
priming frame and drains, a pacing gap, sentinel recovery). The client's
printed summary line is captured verbatim in the serial log;
`extract-ipc-result.sh <captured-log>` transcribes it into
`../../results/cloud/cloud-ipc-latest.csv` (the client cannot write that file
itself — it runs inside the QNX image's own filesystem, with no path back to
this checkout). That CSV is evaluation output and is held locally, not
committed (NC QDL v7 4.6(i)).

## What a run is checked for

The markers the instruments look for, in order:

```
=== AUTO-START QNX GUEST UNDER QVM                           <- QHV host reached post_start
=== launching qvm @g2.conf                                   <- hypervisor invoked
QNX qnx-guest 8.0.0 ... ARMv8_Foundation_Model aarch64le     <- guest under qvm
```

There is no host-banner marker. By configuration the guest sees
`ARMv8_Foundation_Model` (the platform QHV synthesises), not the underlying
`QEMU_virt`. The curated capture of a run (`qhv-tcg-host-and-guest-boot.log`)
is evaluation output and is held locally (NC QDL v7 4.6(i)).

## Known limitations (this build)

- **Guest networking is disabled.** The stock `start_guest` wires a virtio-net
  peer that needs the host `io-sock` stack, whose devices this launch line does
  not provide ([ADR-002](../../docs/phase2-topology-decision.md) §1 and RQ-4).
  `post_start.custom` therefore launches `qvm` with a console+blk-only config.
- TCG is full-system emulation, and slow.
- Guest is QNX. A **Linux** guest under QHV (the heterogeneous cockpit/compute
  story) is the natural next step and is not yet done.
