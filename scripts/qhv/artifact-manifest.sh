#!/usr/bin/env sh
#
# artifact-manifest.sh — per-extent sha256 manifest for the QHV boot media
# (TSR-PKG-001(b) / TCR-IMG-001 implementable floor).
#
# The runtime disk is a split VMDK: a ~169-byte monolithicFlat *descriptor*
# (disk-qemu.vmdk) that points by relative name at a separate ~150 MB raw
# *extent* (disk-qemu). BOTH must travel to the runtime host together and BOTH
# must be integrity-bound — a missing or corrupted extent boots the wrong (or
# no) image. This tool hashes every boot artefact, descriptor AND extent as
# SEPARATE checksum targets, plus ifs.bin and any embedded guest image, so a
# pre-launch verify catches a missing extent / corrupted-but-bootable image.
#
#   This is the FLOOR: a hash manifest is TAMPER-EVIDENT, not tamper-proof.
#   study-only ceiling: a real programme signs the manifest against a key
#   chained to a hardware root-of-trust (Tegra fuses / measured boot, Phase 3)
#   so it becomes tamper-PROOF. No RoT exists on the TCG leg; this tool does
#   NOT establish a signing trust root and must not pretend to (TCR-SB-001).
#
# Usage:
#   artifact-manifest.sh gen    <artifact_dir> [> manifest.sha256]
#   artifact-manifest.sh verify <artifact_dir> <manifest.sha256>
# Exit: 0 ok, 1 mismatch/missing extent, 2 usage/input error.
#
# Pure POSIX sh. Uses sha256sum (Linux runtime host) or shasum -a 256 (fallback).

set -eu

emit() { printf '%s\n' "$*"; }

# Artefacts that, when present in the dir, are integrity-bound. The split-VMDK
# descriptor AND its raw extent are listed SEPARATELY on purpose.
ARTIFACTS="ifs.bin disk-qemu.vmdk disk-qemu guest/ifs.bin guest/disk-qvm"

sha_cmd() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$@"
  else emit "ERROR: no sha256sum / shasum available" >&2; exit 2; fi
}

gen_manifest() {
  dir="$1"
  [ -d "$dir" ] || { emit "ERROR: artifact dir not found: $dir" >&2; exit 2; }
  found=0
  for rel in $ARTIFACTS; do
    f="$dir/$rel"
    if [ -f "$f" ]; then
      # Emit "<sha256>  <relative-path>" so verify is dir-relative / portable.
      h=$(sha_cmd "$f" | awk '{print $1}')
      printf '%s  %s\n' "$h" "$rel"
      found=$((found + 1))
    fi
  done
  [ "$found" -gt 0 ] || { emit "ERROR: no known boot artefacts found under $dir" >&2; exit 2; }
  return 0
}

verify_manifest() {
  dir="$1"; manifest="$2"
  [ -d "$dir" ]      || { emit "ERROR: artifact dir not found: $dir" >&2; exit 2; }
  [ -f "$manifest" ] || { emit "ERROR: manifest not found: $manifest" >&2; exit 2; }
  fail=0; checked=0
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    case "$line" in \#*) continue;; esac
    want=$(printf '%s' "$line" | awk '{print $1}')
    rel=$(printf '%s' "$line" | sed -e 's/^[0-9a-fA-F]*[[:space:]]*//')
    f="$dir/$rel"
    if [ ! -f "$f" ]; then
      emit "PKG-GATE: MISSING extent/artefact: $rel  (BLOCK launch)"
      fail=$((fail + 1)); continue
    fi
    got=$(sha_cmd "$f" | awk '{print $1}')
    checked=$((checked + 1))
    if [ "$got" = "$want" ]; then
      emit "PKG-GATE: OK    $rel"
    else
      emit "PKG-GATE: MISMATCH $rel  want=$want got=$got  (BLOCK launch)"
      fail=$((fail + 1))
    fi
  done < "$manifest"
  if [ "$fail" -gt 0 ]; then
    emit "PKG-GATE: FAIL — $fail integrity failure(s) across $checked checked; launch MUST be blocked."
    exit 1
  fi
  emit "PKG-GATE: PASS — $checked artefact(s) verified (descriptor + extent integrity-bound)."
  emit "PKG-GATE: NOTE manifest is tamper-evident only; RoT-rooted signing is study-only (TCR-SB-001)."
  exit 0
}

usage() { emit "Usage: $0 {gen|verify} <artifact_dir> [manifest.sha256]"; }

main() {
  [ $# -ge 2 ] || { usage >&2; exit 2; }
  cmd="$1"; shift
  case "$cmd" in
    gen)    gen_manifest "$1";;
    verify) [ $# -ge 2 ] || { usage >&2; exit 2; }; verify_manifest "$1" "$2";;
    -h|--help) usage;;
    *) emit "ERROR: unknown subcommand '$cmd'" >&2; usage >&2; exit 2;;
  esac
}

main "$@"
