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

`build-qhv.bat` does the two-stage mkqnximage build (guest `--type=qvm`, then
host `--type=qemu --qvm=yes --guest=...`) and stages `post_start.custom` so the
guest auto-starts. `launch-qhv-tcg.ps1` boots it and captures the serial log.

## What success looks like

Two distinct QNX banners in the log — the partition boundary is real:

```
QNX qnx-qhv   8.0.0 ... QEMU_virt              aarch64le   <- QHV host
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
