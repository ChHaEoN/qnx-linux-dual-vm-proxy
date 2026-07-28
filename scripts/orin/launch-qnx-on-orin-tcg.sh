#!/usr/bin/env bash
#
# Phase 3
# launch-qnx-on-orin-tcg.sh — start the QNX guest under QEMU/TCG on Orin Nano
#                             L4T, bridged onto br0/tap-qnx for the Phase-3
#                             IPC benchmark.
#
# Run on:  Orin Nano L4T, as root (sudo), after:
#   1. sudo ./setup-bridge-orin.sh              (br0 + tap-qnx exist)
#   2. scp output/{ifs.bin,disk-qemu,disk-qemu.vmdk,SHA256SUMS} here
#   3. sha256sum -c SHA256SUMS                  (twin-sync invariant; do NOT skip)
#
# TCG, not KVM: docs/orin-port.md's risk register root-causes a real KVM
# boot hang on this hardware (GICv3 distributor bring-up takes a
# KVM_EXIT_ARM_NISV that QNX's startup has no handler for) and records the
# 2026-07-28 decision to accept TCG as the interim transport. The KVM
# invocation this mirrors (-cpu host -enable-kvm) is left as a documented,
# NOT-deleted intent in launch-qnx-on-orin.sh -- swap -accel tcg for
# -enable-kvm there once/if a QNX-side fix lands.
#
# rng device: startup.sh's devb-virtio/random hardcode fixed virtio-mmio
# slot offsets that only line up if -device args appear in exactly the
# order disk, net, rng (see docs/findings.md's 2026-07-28 "Orin TCG
# networking root-caused and fixed" entry) -- omitting the rng device
# starves io-sock of entropy and it refuses to start at all, which looks
# like a virtio-net bug until you check what's actually running.

set -euo pipefail

ifs="ifs.bin"
disk="disk-qemu"
serial_log="${1:-boot-ipc.log}"

if [[ ! -f "${ifs}" ]]; then
  echo "ERROR: ${ifs} not found in $(pwd)." >&2
  exit 1
fi
if [[ ! -f "${disk}" ]]; then
  echo "ERROR: ${disk} not found in $(pwd)." >&2
  exit 1
fi
if ! ip link show tap-qnx >/dev/null 2>&1; then
  echo "ERROR: tap-qnx interface does not exist. Run: sudo ./setup-bridge-orin.sh" >&2
  exit 1
fi

echo "Launching QNX guest on Orin under TCG (tap-qnx + rng), serial -> ${serial_log} ..."
echo "Host kernel: $(uname -r)  /  CPU: $(awk '/CPU part/{print $4; exit}' /proc/cpuinfo)"

exec qemu-system-aarch64 \
  -machine virt,gic-version=3 \
  -accel tcg \
  -cpu max \
  -smp 2 \
  -m 1G \
  -drive file="${disk}",if=none,id=drv0,format=raw \
  -device virtio-blk-device,drive=drv0 \
  -netdev tap,id=n0,ifname=tap-qnx,script=no,downscript=no \
  -device virtio-net-device,netdev=n0,mac=52:54:00:11:11:11 \
  -object rng-random,filename=/dev/urandom,id=rng0 \
  -device virtio-rng-device,rng=rng0 \
  -kernel "${ifs}" \
  -nographic \
  -serial file:"${serial_log}" \
  -display none \
  -no-reboot \
  -monitor none
