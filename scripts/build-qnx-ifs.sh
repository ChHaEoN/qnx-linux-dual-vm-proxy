#!/usr/bin/env bash
#
# build-qnx-ifs.sh — build the QNX IFS for the Safety-proxy VM
#
# Run on: x86_64 Linux build host, with QNX SDP 8.0 installed and qnxsdp-env.sh sourced.
# Windows users: see scripts/build-qnx-ifs.bat — the primary build path
# since the 2026-05-07 amendment in ../docs/findings.md. This .sh is the
# Linux/EC2 fallback equivalent.
#
# Output:
#   qnx-safety-vm/output/ifs.bin           ← the kernel image fed to qemu -kernel
#   qnx-safety-vm/output/disk-qemu.vmdk    ← ~169-byte VMDK descriptor
#   qnx-safety-vm/output/disk-qemu         ← ~150 MB raw extent (the actual disk)
#
# The .vmdk is only a monolithicFlat descriptor pointing by relative name at
# the raw extent disk-qemu; BOTH must travel to the runtime host together, or
# QEMU cannot open the disk. (twin/sync.sh already copies both.)
#
# These artifacts are gitignored. Do not commit them — the QNX NCEULA
# forbids redistributing QNX-derived binaries. scp them to the runtime
# host and discard the local copy when done.
#
# Reproducibility: this is a thin wrapper around `mkqnximage`, which
# itself is a command-line front-end to QNX's image-building toolchain.
# See `mkqnximage --help` for the full list of options.
#

set -euo pipefail

# ---- Sanity checks -----------------------------------------------------------

if ! command -v mkqnximage >/dev/null 2>&1; then
  echo "ERROR: mkqnximage is not on PATH." >&2
  echo "       Install QNX SDP 8.0 and source the SDP environment first:" >&2
  echo "         source ~/qnx800/qnxsdp-env.sh" >&2
  exit 1
fi

# Build host must be x86_64 (SDP 8.0 host toolchain is x86_64-only)
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: build host must be x86_64. Detected: $(uname -m)" >&2
  echo "       QNX SDP 8.0 host toolchain does not support arm64 hosts." >&2
  echo "       See ../docs/bsp-selection.md for context." >&2
  exit 1
fi

# ---- Build -------------------------------------------------------------------

build_dir="qnx-safety-vm"

echo "[1/2] Preparing build directory: ${build_dir}"
mkdir -p "${build_dir}"
cd "${build_dir}"

echo "[2/2] Running mkqnximage --type=qemu --arch=aarch64le --build ..."
mkqnximage \
  --type=qemu \
  --arch=aarch64le \
  --hostname=qnx-safety \
  --build

echo
echo "Build complete. Artifacts in ${PWD}/output/:"
ls -lh output/ifs.bin output/disk-qemu.vmdk output/disk-qemu 2>/dev/null || true

cat <<'EOF'

Next: scp ALL THREE files (ifs.bin, disk-qemu.vmdk, disk-qemu) to the runtime
host, then run launch-qnx-vm.sh there. The .vmdk is only a descriptor — the raw
extent disk-qemu must travel with it. Do NOT commit them to git (they are
.gitignore'd, but double-check).

EOF
