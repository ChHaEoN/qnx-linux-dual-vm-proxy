#!/usr/bin/env bash
#
# bootstrap-runtime-host.sh — prepare an EC2 instance to run QEMU+KVM.
#
# !! THIS HOST WAS NEVER BUILT AND THIS PATH CANNOT WORK AS WRITTEN. !!
# The c7g.large below is NON-METAL Graviton, which exposes no /dev/kvm at all
# (Nitro does not pass EL2 through; proven on a t4g.small probe). The
# "-enable-kvm" promise two lines down cannot be kept on this instance type,
# and no cloud-leg figure was ever taken on AWS. See ADR-002 in
# docs/phase2-topology-decision.md. Only *.metal instances expose /dev/kvm.
# The as-built cloud leg runs under QEMU TCG on the local Windows PC; the live
# bring-up path is scripts/qhv/. Kept as the record of a falsified design, and
# as a starting point for a *.metal host.
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
  echo "  /dev/kvm NOT FOUND — this is EXPECTED on c7g.* and on every other" >&2
  echo "  non-metal Graviton: Nitro does not pass EL2 through, so no /dev/kvm" >&2
  echo "  appears. Proven on a t4g.small probe; see ADR-002 in" >&2
  echo "  docs/phase2-topology-decision.md. Only *.metal instances expose it." >&2
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
