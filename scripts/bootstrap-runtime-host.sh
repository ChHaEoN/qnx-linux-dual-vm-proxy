#!/usr/bin/env bash
#
# bootstrap-runtime-host.sh — prepare a Graviton EC2 instance to run QEMU+KVM
#
# Target instance: c7g.large, arm64 (Graviton3), Ubuntu 22.04 LTS, >= 30 GB EBS
# Run as: a sudo-capable user (the default `ubuntu` user works)
#
# After this script, the runtime host can:
#   - run qemu-system-aarch64 with -enable-kvm
#   - host a Linux bridge with two tap devices for the dual VMs
#
# This script does NOT install QNX (the runtime host does not need the
# SDP — it only needs the IFS image, which is scp'd in from the build
# host). Per the QNX NCEULA, no QNX SDK component is installed here.
#
# Note: you will need to log out and back in after this script for
# kvm group membership to take effect.
#

set -euo pipefail

echo "[1/4] apt update / upgrade ..."
# TODO: enable after first manual run
# sudo apt-get update
# sudo apt-get upgrade -y

echo "[2/4] Installing QEMU and bridge tooling ..."
# TODO: enable after first manual run
# sudo apt-get install -y \
#   qemu-system-arm \
#   qemu-utils \
#   bridge-utils \
#   net-tools \
#   iproute2 \
#   cloud-image-utils \
#   wget \
#   curl

echo "[3/4] Verifying KVM availability ..."
if [[ -e /dev/kvm ]]; then
  echo "  /dev/kvm exists"
  ls -l /dev/kvm
else
  echo "  /dev/kvm NOT FOUND — confirm the instance type supports KVM (c7g.* should)" >&2
fi

echo "  Adding ${USER} to the kvm group (takes effect after logout/login) ..."
# TODO: enable after first manual run
# sudo usermod -aG kvm "$USER"

echo "  Quick KVM smoke checks (run after logging back in):"
cat <<'EOF'
      qemu-system-aarch64 --version
      kvm-ok            # if cpu-checker is installed
      cat /proc/cpuinfo | grep -E 'CPU implementer|CPU part' | head
EOF

echo "[4/4] Done. Log out and back in so 'kvm' group membership takes effect."
echo "      After that, set up the bridge with: sudo ./setup-bridge.sh"
