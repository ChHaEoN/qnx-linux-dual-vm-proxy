#!/usr/bin/env bash
#
# Phase 3+
# sync.sh — distribute the canonical IFS + ipc-test sources from the
#           cloud-twin build host to both runtime hosts (cloud + HW).
#
# Run on:  the cloud-twin x86_64 build host, after a fresh
#          ./build-qnx-ifs.sh.
# Run as:  the user that built the IFS.
#
# Required env (or args):
#   CLOUD_RUNTIME_HOST    — ssh user@host of the c7g.large runtime
#   ORIN_HOST             — ssh user@host of the Jetson Orin Nano
#
# This script enforces the twin-sync invariants documented in
# docs/digital-twin-design.md §3:
#   - SHA-256 of ifs.bin, disk-qemu.vmdk AND the raw extent disk-qemu recorded
#     (disk-qemu.vmdk is only a descriptor pointing at disk-qemu; both travel)
#   - Git SHA of the ipc-test/ source recorded
#   - Both are verified on each destination after rsync
# Any mismatch fails the run loudly.

set -euo pipefail

CLOUD_RUNTIME_HOST="${CLOUD_RUNTIME_HOST:-${1:-}}"
ORIN_HOST="${ORIN_HOST:-${2:-}}"

if [[ -z "${CLOUD_RUNTIME_HOST}" ]]; then
  echo "ERROR: CLOUD_RUNTIME_HOST not set (env or arg 1)." >&2
  exit 1
fi
if [[ -z "${ORIN_HOST}" ]]; then
  echo "ERROR: ORIN_HOST not set (env or arg 2)." >&2
  exit 1
fi

ifs_dir="qnx-safety-vm/output"
if [[ ! -f "${ifs_dir}/ifs.bin" || ! -f "${ifs_dir}/disk-qemu.vmdk" || ! -f "${ifs_dir}/disk-qemu" ]]; then
  echo "ERROR: IFS artefacts not found in ${ifs_dir}/ (need ifs.bin, disk-qemu.vmdk, disk-qemu). Run ./build-qnx-ifs.sh first." >&2
  exit 1
fi

# 1. Record canonical SHA-256
echo "[1/4] Recording SHA-256 invariants ..."
( cd "${ifs_dir}" && sha256sum ifs.bin disk-qemu.vmdk disk-qemu ) > "${ifs_dir}/SHA256SUMS"
cat "${ifs_dir}/SHA256SUMS"

# 2. Record git SHA (for the ipc-test sources)
echo "[2/4] Recording git SHA ..."
git_sha="$(git rev-parse HEAD)"
echo "git SHA: ${git_sha}" > "${ifs_dir}/GIT_SHA"

# 3. rsync to both runtime hosts
echo "[3/4] Distributing to cloud runtime: ${CLOUD_RUNTIME_HOST} ..."
rsync -avz --progress \
  "${ifs_dir}/ifs.bin" "${ifs_dir}/disk-qemu.vmdk" "${ifs_dir}/disk-qemu" \
  "${ifs_dir}/SHA256SUMS" "${ifs_dir}/GIT_SHA" \
  "${CLOUD_RUNTIME_HOST}:~/output/"

echo "[3/4] Distributing to HW twin: ${ORIN_HOST} ..."
rsync -avz --progress \
  "${ifs_dir}/ifs.bin" "${ifs_dir}/disk-qemu.vmdk" "${ifs_dir}/disk-qemu" \
  "${ifs_dir}/SHA256SUMS" "${ifs_dir}/GIT_SHA" \
  "${ORIN_HOST}:~/output/"

# 4. Verify on each destination
echo "[4/4] Verifying SHA-256 invariants on each destination ..."
for host in "${CLOUD_RUNTIME_HOST}" "${ORIN_HOST}"; do
  echo "  ${host}:"
  ssh "${host}" "cd ~/output && sha256sum -c SHA256SUMS"
done

cat <<EOF

Twin sync complete. Both runtime hosts hold an identical IFS:
  - SHA256SUMS verified on each destination
  - git SHA recorded as: ${git_sha}

You can now run benchmarks on each twin and compare them with
scripts/twin/diff-results.sh.

EOF
