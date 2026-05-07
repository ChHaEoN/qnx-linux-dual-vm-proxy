#!/usr/bin/env bash
#
# bootstrap-build-host.sh — prepare an x86_64 EC2 instance for QNX SDP 8.0
#
# ============================================================================
# AWS FALLBACK PATH. Per the 2026-05-07 amendment in ../docs/findings.md, the
# primary build path is a local Windows PC running QNX SDP 8.0 natively (see
# scripts/build-qnx-ifs.bat). This script is the EC2 fallback for users who
# do not have a local x86_64 Windows or Linux build host available.
# ============================================================================
#
# Target instance: t3.medium, x86_64, Ubuntu 22.04 LTS, >= 30 GB EBS
# Run as: a sudo-capable user (the default `ubuntu` user works)
#
# Prerequisites:
#   - You launched a t3.medium with Ubuntu 22.04 amd64
#   - You have SSH access
#   - You have a myQNX account and have accepted the QNX Everywhere NCEULA
#
# This script does NOT install QNX itself. The QNX Software Center, the
# SDP, and the license are bound to the QNX Everywhere NCEULA — the user
# must download and install them manually. This script only prepares the
# Linux side so the Software Center will run cleanly when you do.
#
# After QNX SDP 8.0 is installed (manual step), source the SDP env in
# every shell where you intend to build:
#
#     source ~/qnx800/qnxsdp-env.sh
#

set -euo pipefail

echo "[1/4] apt update / upgrade ..."
# TODO: enable after first manual run
# sudo apt-get update
# sudo apt-get upgrade -y

echo "[2/4] Installing build essentials and the QNX Software Center prerequisites ..."
# TODO: enable after first manual run
# sudo apt-get install -y \
#   build-essential \
#   openjdk-17-jre \
#   unzip \
#   curl \
#   wget \
#   git \
#   ca-certificates \
#   libgtk-3-0 \
#   libxtst6

echo "[3/4] Manual step required — install QNX SDP 8.0:"
cat <<'EOF'

  1. Visit https://www.qnx.com/getqnx and create a myQNX account if you
     do not already have one.
  2. Accept the QNX Everywhere NCEULA in your myQNX account settings.
  3. Download the QNX Software Center for Linux x86_64.
  4. Run the installer (./qnx-setup-*.run) and sign in with your myQNX
     credentials.
  5. In Software Center, install:
       - QNX SDP 8.0
       - the aarch64le target packages
       - the QNX Everywhere license
  6. The default install root is ~/qnx800.

  This script will NOT do any of the above — the QNX NCEULA requires
  the user to accept it interactively.

EOF

echo "[4/4] Reminder: source the SDP environment after install"
cat <<'EOF'

  Add this to your shell rc (or run it per-shell):

      source ~/qnx800/qnxsdp-env.sh

  Then verify:

      command -v mkqnximage   # should resolve to ~/qnx800/host/.../mkqnximage
      command -v qcc          # should resolve to ~/qnx800/host/.../qcc

EOF

echo "bootstrap-build-host.sh: complete (reminder mode; no commands ran)."
