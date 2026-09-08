#!/usr/bin/env bash
#
# Phase 4
# sync-qhv.sh — stage the QHV host images (and their launcher) from the
#               Windows build host to the Orin Nano, with the twin-sync
#               checksum invariant enforced on arrival.
#
# WHY THIS EXISTS SEPARATELY FROM sync.sh
# ---------------------------------------
# sync.sh predates the QHV leg and does not fit it in three ways:
#   1. it distributes qnx-safety-vm/output, not qhv/host/output;
#   2. it requires CLOUD_RUNTIME_HOST as well as ORIN_HOST -- but per
#      docs/digital-twin-design.md §1 the "cloud" leg as built *is* this
#      Windows box, so there is no second host to push to;
#   3. it uses rsync, which is not present in Git Bash on the Windows build
#      host, so it cannot actually run from where the images now live.
# Rather than overload a working script with a second mode, this one does the
# QHV leg only. sync.sh is left alone for the qnx-safety-vm leg.
#
# WHAT THE CHECKSUM IS FOR
# ------------------------
# The entire value of the QHV twin leg is that both hosts boot *the same*
# images (docs/digital-twin-design.md §1a). If the copies diverge, the diff
# stops measuring the host and starts measuring the images, silently. So the
# checksum is verified on the destination and a mismatch fails loudly here
# rather than producing a plausible-looking number later.
#
# RUN ON: the Windows build host, from the repo root, in Git Bash, after
#         scripts\build-qhv.bat has produced qhv/host/output/.
#
# USAGE
#   ORIN_HOST=user@orin ./scripts/twin/sync-qhv.sh [remote_dir]
#   ./scripts/twin/sync-qhv.sh user@orin [remote_dir]
#     remote_dir  destination on the Orin, relative to $HOME (default: qhv-output)

set -euo pipefail

ORIN_HOST="${ORIN_HOST:-${1:-}}"
# No leading ~ : scp/ssh resolve a relative remote path against the remote
# home, whereas a literal "~" here would be escaped and taken as a directory
# actually named "~".
remote_dir="${2:-qhv-output}"

if [[ -z "${ORIN_HOST}" ]]; then
  echo "ERROR: ORIN_HOST not set (env or arg 1). Example:" >&2
  echo "       ORIN_HOST=nvidia@192.168.178.56 ./scripts/twin/sync-qhv.sh" >&2
  exit 1
fi

src="qhv/host/output"
launcher="scripts/orin/launch-qhv-on-orin-tcg.sh"

for f in "${src}/ifs.bin" "${src}/disk-qemu" "${launcher}"; do
  if [[ ! -f "${f}" ]]; then
    echo "ERROR: ${f} not found." >&2
    echo "       Run scripts\\build-qhv.bat first (from the repo root)." >&2
    exit 1
  fi
done

echo "[1/4] Recording SHA-256 invariant over the images ..."
# Only the two files QEMU actually consumes. disk-qemu.vmdk is a descriptor
# for VMware and is not used by this leg (-drive ... format=raw), so it is
# deliberately not part of the invariant.
( cd "${src}" && sha256sum ifs.bin disk-qemu ) > "${src}/SHA256SUMS"
cat "${src}/SHA256SUMS"

echo
echo "[2/4] Creating ~/${remote_dir} on ${ORIN_HOST} ..."
ssh "${ORIN_HOST}" "mkdir -p ${remote_dir}"

echo "[3/4] Copying images + launcher (~310 MB; first copy is the slow one) ..."
scp -p \
  "${src}/ifs.bin" \
  "${src}/disk-qemu" \
  "${src}/SHA256SUMS" \
  "${launcher}" \
  "${ORIN_HOST}:${remote_dir}/"

echo
echo "[4/4] Verifying the checksum invariant on the Orin ..."
ssh "${ORIN_HOST}" "cd ${remote_dir} && chmod +x launch-qhv-on-orin-tcg.sh && sha256sum -c SHA256SUMS"

cat <<EOF

QHV leg staged. Both hosts now hold identical ifs.bin + disk-qemu.

Next, to produce the twin diff (docs/digital-twin-design.md §1a):

  on the Orin:
      cd ~/${remote_dir} && ./launch-qhv-on-orin-tcg.sh 5

  on this Windows host:
      scripts\\launch-qhv-tcg.ps1 -Runs 5 -StopOnGuestBanner

Both emit 'run N: NNNNN ms' lines timed to the same guest banner. Only the
host differs -- same images, same qvm config, same QEMU args, same TCG
accelerator. Copy the Orin's qhv-orin-boot-times.txt back and compare it
against qhv/qhv-guest-boot-times.txt.

EOF
