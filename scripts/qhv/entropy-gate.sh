#!/usr/bin/env sh
#
# entropy-gate.sh — seeded-PRNG precondition gate (TCR-ENT-001, fail-secure).
#
# Cybersecurity Goal G-ENT: no key-using service ever runs against an unseeded
# PRNG. This gate is meant to be called by the launch / startup path BEFORE
# sshd or any key-generating/key-using service starts. If the kernel PRNG is
# not seeded to full strength from a usable entropy source, the gate FAILS
# SECURE: it refuses (non-zero exit) so the caller withholds the key-using
# service rather than emitting predictable keys (the Debian-OpenSSL /
# factory-default-host-key damage class — T31).
#
# It emits the `prng-seeded` precondition flag that FuSa AoU-ENTROPY and
# Cyber/FuSa Verification consume (see "FLAG CONTRACT" below).
#
# Two input modes:
#   --log <boot_log>   evaluate a captured serial log (offline / test / CI).
#                      Looks for the negative signatures
#                      ("PRNG is not seeded", "Could not initialize entropy",
#                      "Unable to access /dev/random"); their PRESENCE => UNMET.
#   --live             evaluate the live host the gate runs on: requires a
#                      readable random source AND (where available) a seeded
#                      report. On QNX this is /dev/random; on Linux the runtime
#                      host it is /dev/random + getrandom-style readiness.
#
# FAIL-SECURE: any inconclusive/error condition resolves to REFUSE, never ALLOW.
#
#   study-only ceiling: a real programme roots entropy in a hardware TRNG / RoT
#   (Tegra hardware RNG on Orin, Phase 3) and provisions sshd host keys from an
#   HSM / fused key slot. This gate implements the IMPLEMENTABLE FLOOR only:
#   refuse-when-unseeded. On the as-built TCG image the precondition is UNMET
#   (devr-virtio.so rejected, /dev/random inaccessible), so a run against that
#   state MUST correctly REFUSE — that is the right outcome, not a regression.
#
# FLAG CONTRACT (consumed by FuSa AoU-ENTROPY + Cyber/FuSa Verification):
#   - On PASS: writes the token `prng-seeded=1` to the flag file
#     ($ENT_FLAG_FILE, default ./prng-seeded.flag) and prints
#     "ENT-GATE: prng-seeded=1" to stdout; exit 0.
#   - On REFUSE: writes `prng-seeded=0`, prints
#     "ENT-GATE: PRNG unseeded - sshd withheld (fail-secure)" and
#     "ENT-GATE: prng-seeded=0"; exit 1.
#   The flag file is the machine-checkable precondition; no integrity- or
#   freshness-dependent mechanism may claim effectiveness while it reads 0.
#
# Pure POSIX sh. No bashisms.

set -eu

ENT_FLAG_FILE="${ENT_FLAG_FILE:-./prng-seeded.flag}"

emit() { printf '%s\n' "$*"; }

write_flag() {
  # $1 = 0|1 ; best-effort, never fatal (fail-secure already decided by caller).
  printf 'prng-seeded=%s\n' "$1" > "$ENT_FLAG_FILE" 2>/dev/null || \
    emit "ENT-GATE: WARN could not write flag file $ENT_FLAG_FILE" >&2
}

refuse() {
  emit "ENT-GATE: PRNG unseeded - sshd withheld (fail-secure)"
  emit "ENT-GATE: reason: $1"
  write_flag 0
  emit "ENT-GATE: prng-seeded=0"
  exit 1
}

allow() {
  write_flag 1
  emit "ENT-GATE: prng-seeded=1"
  emit "ENT-GATE: entropy precondition MET - key-using services may start"
  exit 0
}

check_log() {
  boot_log="$1"
  [ -f "$boot_log" ] || refuse "boot log not found: $boot_log"
  # Negative signatures: their presence proves the PRNG was NOT seeded.
  if grep -q -e 'PRNG is not seeded' \
             -e 'Could not initialize entropy' \
             -e 'Unable to access /dev/random' \
             -e 'as an entropy source' -- "$boot_log"; then
    refuse "boot log shows unseeded PRNG / no usable entropy source"
  fi
  # Absence of a negative signature is necessary but, on a log, not sufficient
  # to PROVE a seeded PRNG (the system may simply not have logged it). For the
  # gate to ALLOW on a log it must also see a positive readiness marker; absent
  # that, fail-secure.
  if grep -q -e 'random: seeded' -e 'PRNG seeded' -e 'entropy: ready' -- "$boot_log"; then
    allow
  fi
  refuse "no positive seeded-PRNG evidence in boot log (fail-secure default)"
}

check_live() {
  src=""
  for c in /dev/random; do
    [ -r "$c" ] && { src="$c"; break; }
  done
  [ -n "$src" ] || refuse "no readable entropy source (/dev/random) on live host"
  # Linux: entropy_avail readiness if present; on QNX this path is absent and
  # we fall back to "source readable" only (the QNX random driver gates itself).
  avail_node="/proc/sys/kernel/random/entropy_avail"
  if [ -r "$avail_node" ]; then
    avail=$(cat "$avail_node" 2>/dev/null || echo 0)
    case "$avail" in (*[!0-9]*|'') avail=0;; esac
    [ "$avail" -ge 256 ] || refuse "kernel entropy_avail=$avail below threshold 256"
  fi
  # Non-blocking read must succeed and return data.
  if ! dd if="$src" bs=32 count=1 >/dev/null 2>&1; then
    refuse "could not read 32 bytes from $src"
  fi
  allow
}

usage() {
  cat <<EOF
Usage: $0 --log <boot_log>   evaluate a captured serial/boot log (offline/CI)
       $0 --live             evaluate the live host this runs on
Exit: 0 = PASS (prng-seeded=1), 1 = REFUSE / fail-secure (prng-seeded=0)
Flag file: \$ENT_FLAG_FILE (default $ENT_FLAG_FILE)
EOF
}

main() {
  [ $# -ge 1 ] || { usage >&2; exit 2; }
  case "$1" in
    --log)  [ $# -ge 2 ] || { usage >&2; exit 2; }; check_log "$2";;
    --live) check_live;;
    -h|--help) usage; exit 0;;
    *) emit "ERROR: unknown arg '$1'" >&2; usage >&2; exit 2;;
  esac
}

main "$@"
