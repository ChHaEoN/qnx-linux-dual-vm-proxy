#!/usr/bin/env bash
#
# launch-linux-vm.sh — start the Linux Compute-proxy VM on the runtime host
#
# Run on: arm64 runtime host (Graviton), after:
#   1. ./bootstrap-runtime-host.sh                 (and re-login for kvm group)
#   2. sudo ./setup-bridge.sh                      (br0 + tap-linux exist)
#   3. Ubuntu cloud image present in CWD
#
# Obtaining the cloud image:
#
#     wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-arm64.img \
#         -O ubuntu-22.04-server-cloudimg-arm64.img
#
# First-boot setup:
#   Cloud images expect cloud-init metadata. The simplest approach is a
#   seed ISO carrying user-data (sets a password, installs ssh keys):
#
#     cat > user-data <<EOF
#     #cloud-config
#     password: ubuntu
#     chpasswd: { expire: False }
#     ssh_pwauth: True
#     EOF
#     touch meta-data
#     cloud-localds seed.iso user-data meta-data
#
#   Then add: -drive file=seed.iso,if=virtio,format=raw,readonly=on
#
# UEFI firmware:
#   QEMU_EFI.fd is shipped by the qemu-efi-aarch64 package. If your distro
#   places it elsewhere, adjust the -bios path below.
#

set -euo pipefail

img="ubuntu-22.04-server-cloudimg-arm64.img"
firmware="/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"

if [[ ! -f "${img}" ]]; then
  echo "ERROR: ${img} not found." >&2
  echo "       Download it with:" >&2
  echo "         wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-arm64.img -O ${img}" >&2
  exit 1
fi
if [[ ! -f "${firmware}" ]]; then
  echo "ERROR: UEFI firmware not found at ${firmware}." >&2
  echo "       Install with: sudo apt-get install -y qemu-efi-aarch64" >&2
  exit 1
fi
if ! ip link show tap-linux >/dev/null 2>&1; then
  echo "ERROR: tap-linux interface does not exist. Run: sudo ./setup-bridge.sh" >&2
  exit 1
fi

echo "Launching Linux VM (Ctrl-A X to quit, Ctrl-A C for QEMU monitor) ..."

exec qemu-system-aarch64 \
  -machine virt,gic-version=3 \
  -cpu host \
  -enable-kvm \
  -smp 2 \
  -m 2G \
  -bios "${firmware}" \
  -drive if=none,file="${img}",id=hd0 \
  -device virtio-blk-device,drive=hd0 \
  -netdev tap,id=n0,ifname=tap-linux,script=no,downscript=no \
  -device virtio-net-device,netdev=n0,mac=52:54:00:22:22:22 \
  -nographic
