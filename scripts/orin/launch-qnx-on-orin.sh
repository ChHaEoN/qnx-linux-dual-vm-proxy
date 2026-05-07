#!/usr/bin/env bash
#
# Phase 3
# launch-qnx-on-orin.sh — start the QNX guest under QEMU/KVM on Orin Nano L4T.
#
# Run on:  Orin Nano L4T, after:
#   1. ./bootstrap-orin-l4t.sh                (and re-login for kvm group)
#   2. sudo ./setup-bridge-orin.sh            (br0 + tap-qnx exist)
#   3. scp output/ifs.bin and output/disk-qemu.vmdk from the cloud-twin build host
#   4. sha256sum -c ~/output/SHA256SUMS       (twin-sync invariant; do NOT skip)
#
# This script intentionally mirrors scripts/launch-qnx-vm.sh almost
# byte-for-byte. The QEMU args are identical; the only thing that
# differs is the host (Orin Nano L4T instead of Graviton + Ubuntu).
# That is the load-bearing twin claim — same IFS, same QEMU args,
# different host.

set -euo pipefail

ifs="output/ifs.bin"
disk="output/disk-qemu.vmdk"

if [[ ! -f "${ifs}" ]]; then
  echo "ERROR: ${ifs} not found." >&2
  echo "       scp it from the cloud-twin build host." >&2
  exit 1
fi
if [[ ! -f "${disk}" ]]; then
  echo "ERROR: ${disk} not found." >&2
  exit 1
fi
if [[ ! -f "output/SHA256SUMS" ]]; then
  echo "WARNING: output/SHA256SUMS not found — twin-sync invariant unverified." >&2
  echo "         Strongly recommend running build-host -> sha256sum > SHA256SUMS, scp, then sha256sum -c here." >&2
fi
if ! ip link show tap-qnx >/dev/null 2>&1; then
  echo "ERROR: tap-qnx interface does not exist. Run: sudo ./setup-bridge-orin.sh" >&2
  exit 1
fi

echo "Launching QNX VM on Orin (Ctrl-A X to quit, Ctrl-A C for QEMU monitor) ..."
echo "Host kernel: $(uname -r)  /  CPU: $(awk '/CPU part/{print $4; exit}' /proc/cpuinfo)"

exec qemu-system-aarch64 \
  -machine virt,gic-version=3 \
  -cpu host \
  -enable-kvm \
  -smp 2 \
  -m 1G \
  -drive file="${disk}",if=none,id=drv0 \
  -device virtio-blk-device,drive=drv0 \
  -netdev tap,id=n0,ifname=tap-qnx,script=no,downscript=no \
  -device virtio-net-device,netdev=n0,mac=52:54:00:11:11:11 \
  -kernel "${ifs}" \
  -nographic \
  -serial mon:stdio
