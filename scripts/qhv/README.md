# QHV (QNX Hypervisor) — Type-1 hypervisor hosting a guest, on QEMU-TCG

This recipe builds a **QNX Hypervisor (QHV)** host image that boots a **QNX
guest** underneath it, and runs the whole thing under `qemu-system-aarch64` in
**TCG** (pure software emulation). It needs no KVM and no special hardware — it
runs on the local Windows build host.

> **Why TCG and not KVM?** QHV (like KVM) needs the ARM virtualization
> extensions (EL2). AWS **non-metal** Graviton does not expose `/dev/kvm` / EL2
> (proven empirically — see `docs/findings.md`, 2026-06-11), so a hardware-
> accelerated QHV there would need a `*.metal` instance or real silicon (Jetson
> Orin). TCG emulates an EL2-capable CPU in software, which is enough to validate
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
for the full runtime-spike finding chain (tty raw-mode requirement, a
one-time startup byte-injection artifact, a steady-state TCG/virtio-queue
stall needing a pacing gap). The client's printed summary line is captured
verbatim in the serial log; `extract-ipc-result.sh <captured-log>`
transcribes it into `../../results/cloud/cloud-ipc-latest.csv` (the client
cannot write that file itself — it runs inside the QNX image's own
filesystem, with no path back to this checkout).

## What success looks like

Two distinct QNX banners in the log — the partition boundary is real:

```
(no host banner is printed — look for "=== AUTO-START QNX GUEST UNDER QVM"
 and "=== launching qvm @g2.conf" instead)                <- QHV host
QNX qnx-guest 8.0.0 ... ARMv8_Foundation_Model aarch64le   <- guest under qvm
```

The guest sees `ARMv8_Foundation_Model` (the platform QHV synthesises), not the
underlying `QEMU_virt`. A curated capture lives at
`logs/sample-boot/qhv-tcg-host-and-guest-boot.log`.

## Known limitations (this build)

- **Guest networking is disabled.** The stock `start_guest` wires a virtio-net
  peer that needs the host `io-sock` stack, which does not initialise on this
  qemu-virt build (`network stack down` / `Address family not supported`).
  `post_start.custom` therefore launches `qvm` with a console+blk-only config.
- TCG is slow; host+guest boot takes a few minutes.
- Guest is QNX. A **Linux** guest under QHV (the heterogeneous cockpit/compute
  story) is the natural next step and is not yet done.
