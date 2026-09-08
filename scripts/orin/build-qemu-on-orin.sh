#!/usr/bin/env bash
#
# Phase 4
# build-qemu-on-orin.sh — build a modern QEMU from source on Orin Nano L4T,
#                         installed to its own prefix, leaving the distro
#                         QEMU untouched.
#
# WHY
# ---
# The QHV twin leg (docs/digital-twin-design.md §1a) compared a Windows host
# running QEMU 11.0.50 against this board running Ubuntu 22.04's stock 6.2.0
# and hung deterministically at "random: Could not initialize entropy". Five
# major releases apart, on the TCG EL2-emulation path (`virt,virtualization=on`)
# that QHV exists to use. Until both sides run the same QEMU, that hang cannot
# be attributed to the host and no timing number from the pair means anything.
#
# This script closes the version gap from the side that is behind.
#
# WHY A TAGGED RELEASE, NOT master
# --------------------------------
# The Windows binary reports v11.0.0-12631-g54e84cdc7a, and that commit is not
# reachable in upstream qemu.git — it is a fork build, so an exact commit match
# is not available. Rather than build "something recent" and call it close
# enough (the same reasoning that produced the confound in the first place),
# this builds a NAMED, REPRODUCIBLE upstream release. The matching official
# 11.1.0 build can then be installed on the Windows side, putting both hosts on
# one identifiable version.
#
# WHY ITS OWN PREFIX
# ------------------
# The distro's 6.2.0 stays exactly where it is. Every existing result on the
# qnx-safety-vm leg — the TCG boot logs, the 100k-iteration IPC runs, the
# GICv3/NISV KVM reproduction — was produced against 6.2.0. Replacing the
# system QEMU would quietly invalidate the reproducibility of all of it, and
# rolling back would stop being a path change.
#
# WHY -j4 AND NOT -j6
# -------------------
# This board dropped off the network entirely mid-file-transfer on 2026-09-08
# and had to be power-cycled; the cause was never established (journald here is
# volatile, so the previous boot left no record). A multi-core compile is a far
# heavier and much longer sustained load than that transfer was. Until the
# cause is known, saturating all six cores is a gamble whose downside is a
# half-finished build plus an ambiguous failure. Override with JOBS=6 if you
# have since ruled power out.
#
# RUN ON: Orin Nano L4T. Needs passwordless sudo only for the apt step.
#
# USAGE
#   ./build-qemu-on-orin.sh [version-tag] [install-prefix]
#     version-tag     default v11.1.0
#     install-prefix  default $HOME/qemu-<tag>
#   JOBS=n            parallel compile jobs (default 4)

set -euo pipefail

tag="${1:-v11.1.0}"
prefix="${2:-$HOME/qemu-${tag}}"
jobs="${JOBS:-4}"
src="$HOME/qemu-src"
build="$HOME/qemu-build-${tag}"
log="$HOME/qemu-build-${tag}.log"

echo "tag=${tag}  prefix=${prefix}  jobs=${jobs}"
echo "source=${src}  build=${build}"
echo

echo "[1/5] Build dependencies ..."
sudo -n apt-get install -y -q \
  git build-essential ninja-build meson pkg-config python3 \
  libglib2.0-dev libpixman-1-dev zlib1g-dev libslirp-dev >/dev/null
echo "  ok"

echo "[2/5] Source tree ..."
if [[ ! -d "${src}/.git" ]]; then
  # Blobless partial clone: full history (so any tag can be checked out) but
  # file contents fetched on demand. Much faster than a full clone here.
  git clone --filter=blob:none --quiet https://gitlab.com/qemu-project/qemu.git "${src}"
fi
cd "${src}"
git fetch --tags --quiet origin
if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  echo "ERROR: tag ${tag} not found upstream." >&2
  echo "       Available recent tags:" >&2
  git tag --list 'v*' --sort=-creatordate | head -10 >&2
  exit 1
fi
git checkout -q "${tag}"
echo "  checked out ${tag} ($(git rev-parse --short HEAD))"

echo "[3/5] Configure ..."
rm -rf "${build}"
mkdir -p "${build}"
cd "${build}"
# aarch64-softmmu only: this is the sole target either twin leg boots, and
# building every target would multiply the compile time on this board for no
# benefit. --enable-kvm is kept because the qnx-safety-vm leg still owes a
# hardware-timed KVM number if the GICv3/NISV defect is ever resolved.
"${src}/configure" \
  --target-list=aarch64-softmmu \
  --prefix="${prefix}" \
  --enable-kvm \
  --disable-docs \
  --disable-werror \
  > configure.log 2>&1 || { echo "ERROR: configure failed; see ${build}/configure.log" >&2; tail -25 configure.log >&2; exit 1; }
echo "  ok"

echo "[4/5] Compiling with -j${jobs} (this is the long part) ..."
make -j"${jobs}"

echo "[5/5] Installing to ${prefix} ..."
make install

echo
echo "=== built ==="
"${prefix}/bin/qemu-system-aarch64" --version | head -1
echo
echo "The distro QEMU is untouched:"
/usr/bin/qemu-system-aarch64 --version | head -1
echo
cat <<EOF
To use the new build for the QHV leg, put it first on PATH:

    PATH="${prefix}/bin:\$PATH" ./launch-qhv-on-orin-tcg.sh 1

launch-qhv-on-orin-tcg.sh stamps the QEMU version into its times file, so a
run made with this build is self-identifying. Remember that a comparison is
only valid against a Windows run whose 'qemu:' line matches — installing the
matching official ${tag} build there is the other half of this.
EOF
