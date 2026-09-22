#!/usr/bin/env bash
#
# setup-bridge.sh — create br0 + tap-qnx + tap-linux on the runtime host
#
# The Graviton RUNTIME HOST it was written for was never built: non-metal
# Graviton exposes no /dev/kvm (ADR-002: docs/phase2-topology-decision.md), so no
# cloud leg exists. It does run on a bare-metal a1.metal TEST BED, where
# scripts/aws/remote-ladder.sh uses it (and then removes tap-linux, to match the
# Orin's bridge) for the A6 ladders -- a QNX guest under KVM, which is still not
# a cloud leg in this project's sense (QHV cannot run under KVM). The bridged
# QNX<->Linux topology of A2 exists only on the Orin, via scripts/orin/.
#
# Run on: an arm64 host with /dev/kvm (bare metal), as root (sudo).
#
# Topology produced:
#
#     br0    192.168.100.1/24   (host side, no DHCP)
#      ├── tap-qnx        ← attached to QNX VM via -netdev tap,ifname=tap-qnx
#      └── tap-linux      ← attached to Linux VM via -netdev tap,ifname=tap-linux
#
# Both tap devices are owned by the calling user so QEMU does not need
# to be run as root.
#
# This is the only script in this repo that touches host networking.
# It is real (not a stub) because it does not depend on QNX in any way.
#

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: this script must be run as root (use sudo)." >&2
  exit 1
fi

# Determine the user that invoked sudo, so taps are owned by them.
target_user="${SUDO_USER:-${USER}}"
if [[ -z "${target_user}" || "${target_user}" == "root" ]]; then
  echo "ERROR: cannot determine non-root invoker; run with sudo as a regular user." >&2
  exit 1
fi

bridge="br0"
tap_qnx="tap-qnx"
tap_linux="tap-linux"
bridge_cidr="192.168.100.1/24"

echo "[1/4] Creating bridge ${bridge} (${bridge_cidr}) ..."
ip link add name "${bridge}" type bridge 2>/dev/null || \
  echo "  ${bridge} already exists; continuing"
ip addr add "${bridge_cidr}" dev "${bridge}" 2>/dev/null || \
  echo "  ${bridge_cidr} already on ${bridge}; continuing"
ip link set "${bridge}" up

echo "[2/4] Creating tap ${tap_qnx} owned by ${target_user} ..."
ip tuntap add dev "${tap_qnx}" mode tap user "${target_user}" 2>/dev/null || \
  echo "  ${tap_qnx} already exists; continuing"
ip link set "${tap_qnx}" master "${bridge}"
ip link set "${tap_qnx}" up

echo "[3/4] Creating tap ${tap_linux} owned by ${target_user} ..."
ip tuntap add dev "${tap_linux}" mode tap user "${target_user}" 2>/dev/null || \
  echo "  ${tap_linux} already exists; continuing"
ip link set "${tap_linux}" master "${bridge}"
ip link set "${tap_linux}" up

echo "[4/4] Final state:"
ip -br addr show "${bridge}"
ip -br link show "${tap_qnx}"
ip -br link show "${tap_linux}"

cat <<EOF

Bridge ready.
  Host side : ${bridge} = 192.168.100.1
  QNX guest : will get a static address in 192.168.100.0/24 (configured per VM)
  Linux gst : will get a static address in 192.168.100.0/24 (configured per VM)

Suggested guest IPs (no DHCP):
  QNX   192.168.100.10
  Linux 192.168.100.20

EOF

# ---------------------------------------------------------------------------
# Teardown reference (commented; run manually if you want to fully reset):
#
# ip link set tap-qnx     down  && ip tuntap del dev tap-qnx     mode tap
# ip link set tap-linux   down  && ip tuntap del dev tap-linux   mode tap
# ip link set br0         down  && ip link    del          br0   type bridge
#
# ---------------------------------------------------------------------------
