#!/usr/bin/env bash
#
# launch-qnx-vm.sh — start the QNX Safety-proxy VM on the runtime host
#
# Run on: arm64 runtime host (Graviton), after:
#   1. ./bootstrap-runtime-host.sh                 (and re-login for kvm group)
#   2. sudo ./setup-bridge.sh                      (br0 + tap-qnx exist)
#   3. scp output/ifs.bin and output/disk-qemu.vmdk from the build host
#
# Paths assume `output/ifs.bin` and `output/disk-qemu.vmdk` are in the CWD
# (i.e. you're in the directory you scp'd them into). Adjust if needed.
#
# QEMU args reference (kept as a here-doc for grep-ability):
#
#     qemu-system-aarch64 \
#       -machine virt,gic-version=3 \
#       -cpu host \
#       -enable-kvm \
#       -smp 2 \
#       -m 1G \
#       -drive file=output/disk-qemu.vmdk,if=none,id=drv0 \
#       -device virtio-blk-device,drive=drv0 \
#       -netdev tap,id=n0,ifname=tap-qnx,script=no,downscript=no \
#       -device virtio-net-device,netdev=n0,mac=52:54:00:11:11:11 \
#       -kernel output/ifs.bin \
#       -nographic \
#       -serial mon:stdio
#

set -euo pipefail

ifs="output/ifs.bin"
disk="output/disk-qemu.vmdk"

if [[ ! -f "${ifs}" ]]; then
  echo "ERROR: ${ifs} not found." >&2
  echo "       Build it on the x86_64 build host (./build-qnx-ifs.sh) and scp it here." >&2
  exit 1
fi
if [[ ! -f "${disk}" ]]; then
  echo "ERROR: ${disk} not found." >&2
  echo "       Build it on the x86_64 build host (./build-qnx-ifs.sh) and scp it here." >&2
  exit 1
fi
if ! ip link show tap-qnx >/dev/null 2>&1; then
  echo "ERROR: tap-qnx interface does not exist. Run: sudo ./setup-bridge.sh" >&2
  exit 1
fi

echo "Launching QNX VM (Ctrl-A X to quit, Ctrl-A C for QEMU monitor) ..."

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
