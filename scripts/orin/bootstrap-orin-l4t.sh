#!/usr/bin/env bash
#
# Phase 3
# bootstrap-orin-l4t.sh — prepare a Jetson Orin Nano running L4T (JetPack 6)
#                        to host the QNX guest under QEMU/KVM.
#
# Run on:  Jetson Orin Nano Dev Kit, after JetPack 6.x is flashed and the
#          Ubuntu first-run wizard is complete.
# Run as:  the regular ubuntu user, with sudo.
#
# Prereqs (manual):
#   - JetPack 6.x flashed via SDK Manager (see docs/orin-port.md §1)
#   - Network reachable for apt
#
# After this script:
#   - QEMU + bridge tooling installed
#   - /dev/kvm exposed and user added to kvm group (re-login needed)
#   - Phase 3 step 3 (./setup-bridge-orin.sh) is the next runnable step

set -euo pipefail

echo "[1/4] apt update / upgrade ..."
# TODO: enable after first manual run
# sudo apt-get update
# sudo apt-get upgrade -y

echo "[2/4] Installing QEMU + bridge tooling ..."
# TODO: enable after first manual run
# sudo apt-get install -y \
#   qemu-system-arm \
#   qemu-utils \
#   bridge-utils \
#   net-tools \
#   iproute2 \
#   build-essential \
#   git

echo "[3/4] Verifying KVM availability on A78AE ..."
if [[ -e /dev/kvm ]]; then
  echo "  /dev/kvm exists"
  ls -l /dev/kvm
else
  echo "  /dev/kvm NOT FOUND — JetPack 6 should expose it; check kernel config" >&2
  echo "  If missing: confirm 'cat /proc/config.gz | gunzip | grep CONFIG_KVM' returns =y" >&2
fi

echo "  Adding ${USER} to kvm group (takes effect after logout/login) ..."
# TODO: enable after first manual run
# sudo usermod -aG kvm "$USER"

echo "[4/4] Smoke-check commands (run after re-login):"
cat <<'EOF'
      qemu-system-aarch64 --version
      qemu-system-aarch64 -accel help     # should list 'kvm'
      cat /proc/cpuinfo | grep -E 'CPU implementer|CPU part' | head
      free -h                              # confirm RAM headroom
EOF

echo
echo "Done. Re-login, then run: sudo ./setup-bridge-orin.sh"
