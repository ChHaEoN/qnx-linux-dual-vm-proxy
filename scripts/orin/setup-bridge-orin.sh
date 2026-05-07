#!/usr/bin/env bash
#
# Phase 3
# setup-bridge-orin.sh — create br0 + tap-qnx on the Orin Nano L4T host.
#
# Run on:  Orin Nano L4T, as root (sudo).
#
# Topology produced:
#
#     br0    192.168.100.1/24   (host side)
#     └── tap-qnx                ← attached to QEMU(QNX) via -netdev tap,ifname=tap-qnx
#
# Note vs the cloud-twin setup-bridge.sh: there is NO tap-linux on the
# HW twin, because L4T is the host AND plays the Compute side. The
# Linux client runs natively on L4T and reaches QNX at 192.168.100.10
# directly through br0.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: this script must be run as root (use sudo)." >&2
  exit 1
fi

target_user="${SUDO_USER:-${USER}}"
if [[ -z "${target_user}" || "${target_user}" == "root" ]]; then
  echo "ERROR: cannot determine non-root invoker; run with sudo as a regular user." >&2
  exit 1
fi

bridge="br0"
tap_qnx="tap-qnx"
bridge_cidr="192.168.100.1/24"

echo "[1/3] Creating bridge ${bridge} (${bridge_cidr}) ..."
ip link add name "${bridge}" type bridge 2>/dev/null || \
  echo "  ${bridge} already exists; continuing"
ip addr add "${bridge_cidr}" dev "${bridge}" 2>/dev/null || \
  echo "  ${bridge_cidr} already on ${bridge}; continuing"
ip link set "${bridge}" up

echo "[2/3] Creating tap ${tap_qnx} owned by ${target_user} ..."
ip tuntap add dev "${tap_qnx}" mode tap user "${target_user}" 2>/dev/null || \
  echo "  ${tap_qnx} already exists; continuing"
ip link set "${tap_qnx}" master "${bridge}"
ip link set "${tap_qnx}" up

echo "[3/3] Final state:"
ip -br addr show "${bridge}"
ip -br link show "${tap_qnx}"

cat <<EOF

Bridge ready on Orin Nano.
  Host side : ${bridge} = 192.168.100.1   (L4T native; runs the Linux client)
  QNX guest : will get static 192.168.100.10 (configured per VM)

EOF

# Teardown reference (commented):
# ip link set tap-qnx down  && ip tuntap del dev tap-qnx mode tap
# ip link set br0     down  && ip link    del          br0 type bridge
