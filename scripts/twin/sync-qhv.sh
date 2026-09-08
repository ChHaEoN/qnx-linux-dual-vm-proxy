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
#
#   SSH_OPTS    extra options passed to both ssh and scp. Needed when the board
#               uses a key that is not one of ssh's default names, e.g.
#                 SSH_OPTS="-i ~/.ssh/jetson_orin_nano"
#               (word-split on purpose so multiple flags work; keep paths
#               unquoted-safe, i.e. no spaces).

set -euo pipefail

ORIN_HOST="${ORIN_HOST:-${1:-}}"
SSH_OPTS="${SSH_OPTS:-}"
# shellcheck disable=SC2206  # deliberate word-splitting: SSH_OPTS is a flag list
ssh_opts=(${SSH_OPTS})
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
ssh "${ssh_opts[@]}" "${ORIN_HOST}" "mkdir -p ${remote_dir}"

echo "[3/4] Copying images + launcher ..."
# Per-file, checksum-skipping, retrying transfer.
#
# WHY NOT A PLAIN scp OF ALL FOUR FILES: on 2026-09-08 that died partway
# through disk-qemu ("Connection reset by peer") when the board dropped off
# the network mid-transfer, and scp cannot resume -- a retry would have
# re-sent all ~310 MB including the parts that had already landed. Since the
# images change rarely and the link is the fragile part, compare checksums
# first and send only what is actually missing or wrong. A retry after a
# failure then costs only the unfinished file.
#
# -C compresses on the wire: the raw disk image measured ~40% of its size
# under gzip -1, so this roughly halves time-on-wire and with it the exposure
# to another drop. The keepalives make a stalled link fail in ~1 min instead
# of hanging until the TCP timeout.
xfer_opts=(-C -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

copy_one() {
  local local_path="$1" name
  name="$(basename "${local_path}")"
  local want
  want="$(sha256sum "${local_path}" | cut -d" " -f1)"
  local have
  have="$(ssh "${ssh_opts[@]}" "${ORIN_HOST}" "sha256sum ${remote_dir}/${name} 2>/dev/null | cut -d\" \" -f1" 2>/dev/null || true)"

  if [[ "${have}" == "${want}" ]]; then
    echo "  ${name}: already present and correct — skipping"
    return 0
  fi
  if [[ -n "${have}" ]]; then
    echo "  ${name}: present but WRONG checksum — resending"
  fi

  local attempt
  for attempt in 1 2 3; do
    echo "  ${name}: sending (attempt ${attempt}/3) ..."
    if scp "${ssh_opts[@]}" "${xfer_opts[@]}" -p "${local_path}" "${ORIN_HOST}:${remote_dir}/"; then
      return 0
    fi
    echo "  ${name}: attempt ${attempt} failed." >&2
    if [[ ${attempt} -lt 3 ]]; then
      echo "  waiting 20s for the link (or the board) to come back ..." >&2
      sleep 20
    fi
  done

  echo "ERROR: ${name} could not be transferred after 3 attempts." >&2
  echo "       If the board vanished from the network rather than just the" >&2
  echo "       transfer stalling, suspect power: the Orin Nano browns out on" >&2
  echo "       an underspecced supply when CPU + network + storage load up" >&2
  echo "       together. Re-running this script is safe and cheap — files" >&2
  echo "       that already landed intact are skipped." >&2
  return 1
}

# Small files first, so a failure on the big one does not leave the launcher
# and the checksum manifest missing.
for f in "${src}/SHA256SUMS" "${launcher}" "${src}/ifs.bin" "${src}/disk-qemu"; do
  copy_one "${f}" || exit 1
done

echo
echo "[4/4] Verifying the checksum invariant on the Orin ..."
ssh "${ssh_opts[@]}" "${ORIN_HOST}" "cd ${remote_dir} && chmod +x launch-qhv-on-orin-tcg.sh && sha256sum -c SHA256SUMS"

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
