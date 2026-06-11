#!/usr/bin/env sh
#
# verify-bringup.sh — host-side QHV bring-up verifier (Phase-1 gate).
#
# Consumes a captured serial/boot log from the QHV-on-TCG launch path and
# turns the previously-SILENT degraded bring-up states into explicit,
# annunciated PASS / FLAG / BLOCK outcomes. Implements the FuSa Phase-1-gate
# Technical Safety Requirements:
#
#   assert_config_applied  -> TSR-CFG-001  (BLOCK on unapplied config directive)
#   reconcile_vdevs        -> TSR-VDEV-001 (FLAG on missing manifested vdev)
#   assert_rmgrs_armed     -> TSR-RMGR-001 (BLOCK/FLAG per rmgr-policy.table)
#   check_pe_online        -> TSR-PE-001   (FLAG on awake-PE shortfall vs -smp)
#   annunciate_net_state   -> TSR-NET-001  (FLAG net-degraded; set flag)
#
# Dev-twin fail policy (FuSa §6): BLOCK (exit non-zero) on TSR-CFG-001 /
# TSR-RMGR-001 (block-policy rmgrs). ANNUNCIATE-and-continue (degraded flag,
# non-blocking) on TSR-NET-001 / TSR-VDEV-001 / TSR-PE-001 and degrade-policy
# rmgrs. The SAME conditions would BLOCK on any leg asserting a safety claim.
#
# HONEST FRAMING: this is a study-level bring-up CHECKPOINT gate wrapping a
# QEMU-TCG study leg. It detects the catalogued cause at bring-up; it is NOT a
# continuous online safety monitor, makes NO timing/FFI claim (TSR-TIM-001),
# and is NOT certification evidence.
#
# Pure POSIX sh; runs on the Linux runtime host. No bashisms.
#
# Outcome accounting: every check appends one token per finding (PASS/FLAG/
# BLOCK) to $RESULTS, which is tallied at the end. This avoids the
# subshell-cannot-mutate-parent pitfall entirely.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

VDEV_MANIFEST="${VDEV_MANIFEST:-$SCRIPT_DIR/vdev.manifest}"
RMGR_MANIFEST="${RMGR_MANIFEST:-$SCRIPT_DIR/rmgr.manifest}"
RMGR_POLICY="${RMGR_POLICY:-$SCRIPT_DIR/rmgr-policy.table}"
G2_ALLOW="${G2_ALLOW:-$SCRIPT_DIR/g2.conf.allow}"

RESULTS=$(mktemp 2>/dev/null || echo "/tmp/verify-bringup.$$.results")
NET_DEGRADED=0
trap 'rm -f "$RESULTS"' EXIT INT TERM

emit() { printf '%s\n' "$*"; }
pass()  { emit "  PASS  [$1] $2"; printf 'PASS\n'  >> "$RESULTS"; }
flag()  { emit "  FLAG  [$1] $2"; printf 'FLAG\n'  >> "$RESULTS"; }
block() { emit "  BLOCK [$1] $2"; printf 'BLOCK\n' >> "$RESULTS"; }
note()  { emit "  NOTE  [$1] $2"; }

# Strip comments / trailing whitespace / blank lines from a manifest file.
strip_comments() {
  sed -e 's/#.*$//' -e 's/[[:space:]]*$//' -- "$1" | grep -v '^[[:space:]]*$' || true
}

# Count matches without tripping set -e when grep finds none.
count_matches() { grep -c -- "$1" "$2" 2>/dev/null || true; }
has_match()     { grep -q -- "$1" "$2" 2>/dev/null; }

need_file() {
  if [ ! -f "$1" ]; then
    emit "ERROR: required input not found: $1" >&2
    exit 2
  fi
}

# --- TSR-CFG-001 -------------------------------------------------------------
# A config directive that did not take effect ("Failed to arm a resource
# manager: Function not implemented") means qvm is running a silently divergent
# resource set. BLOCK. The g2.conf path is optional cross-check context.
assert_config_applied() {
  g2_conf="$1"; boot_log="$2"
  need_file "$boot_log"
  matched=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    block "TSR-CFG-001" "unapplied directive: $line"
    matched=1
  done <<EOF
$(grep -n 'Failed to arm a resource manager' -- "$boot_log" 2>/dev/null || true)
EOF
  [ "$matched" -eq 1 ] || pass "TSR-CFG-001" "no unapplied config directives in $boot_log"
  if [ -n "$g2_conf" ] && [ "$g2_conf" != "-" ] && [ ! -f "$g2_conf" ]; then
    flag "TSR-CFG-001" "g2.conf not found for cross-check: $g2_conf (log-only check performed)"
  fi
}

# --- TSR-VDEV-001 ------------------------------------------------------------
# Reconcile DECLARED manifest vdevs vs. guest-side presence tokens in the log.
# Missing / unverifiable presence -> FLAG (annunciate, non-nominal), not BLOCK.
reconcile_vdevs() {
  vdev_manifest="$1"; boot_log="$2"
  need_file "$vdev_manifest"; need_file "$boot_log"
  while read -r vid token; do
    [ -n "$vid" ] || continue
    if [ -z "${token:-}" ] || [ "$token" = "-" ]; then
      # presence-unknown is INDETERMINATE, not a detected defect: record as a
      # NOTE so it does not by itself force a DEGRADED verdict. A genuinely
      # absent manifested token (else branch) IS a FLAG.
      note "TSR-VDEV-001" "vdev '$vid' presence unverifiable from serial log (presence-unknown)"
    elif has_match "$token" "$boot_log"; then
      pass "TSR-VDEV-001" "vdev '$vid' present (token '$token')"
    else
      flag "TSR-VDEV-001" "vdev '$vid' manifested but token '$token' absent -> non-nominal"
    fi
  done <<EOF
$(strip_comments "$vdev_manifest")
EOF
}

# --- TSR-RMGR-001 ------------------------------------------------------------
# Each manifested rmgr must have STARTED (host startup section). Per-rmgr
# policy (block/degrade/ignore) decides BLOCK vs FLAG vs tolerate. Default for
# an rmgr absent from the policy table is BLOCK (fail-loud).
# Policy-table entries are "<name...> <policy>" where <name> may contain
# spaces (e.g. "PCI Services") and <policy> is the final field. Match on name.
rmgr_policy_for() {
  tok="$1"; ptbl="$2"; result=""
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    policy=${entry##* }
    name=${entry% *}
    if [ "$name" = "$tok" ]; then result="$policy"; break; fi
  done <<EOF
$(strip_comments "$ptbl")
EOF
  printf '%s' "$result"
}

assert_rmgrs_armed() {
  rmgr_manifest="$1"; boot_log="$2"; policy_table="$3"
  need_file "$rmgr_manifest"; need_file "$boot_log"; need_file "$policy_table"
  # Restrict to the host startup section (above the guest split marker) so a
  # guest-side "Starting sshd" does not mask a host-side miss.
  host_section=$(mktemp 2>/dev/null || echo "/tmp/vb-host.$$")
  if has_match 'GUEST booting inside the qvm' "$boot_log"; then
    sed -n '1,/GUEST booting inside the qvm/p' -- "$boot_log" > "$host_section"
  else
    cat -- "$boot_log" > "$host_section"
  fi

  while IFS= read -r tok _rest; do
    [ -n "$tok" ] || continue
    policy=$(rmgr_policy_for "$tok" "$policy_table")
    [ -n "$policy" ] || policy="block"
    if has_match "Starting $tok" "$host_section"; then
      pass "TSR-RMGR-001" "rmgr '$tok' started (policy=$policy)"
    else
      case "$policy" in
        block)   block "TSR-RMGR-001" "rmgr '$tok' did not arm -> BLOCK (policy=block)";;
        degrade) flag  "TSR-RMGR-001" "rmgr '$tok' did not arm -> degraded (policy=degrade)";;
        ignore)  note  "TSR-RMGR-001" "rmgr '$tok' not armed; tolerated by reviewed exception (policy=ignore)";;
        *)       block "TSR-RMGR-001" "rmgr '$tok' did not arm; unknown policy '$policy' -> BLOCK";;
      esac
    fi
  done <<EOF
$(strip_comments "$rmgr_manifest")
EOF
  rm -f "$host_section"
}

# --- TSR-PE-001 --------------------------------------------------------------
# Online-PE count vs configured -smp. Shortfall ("CPU N PE is not awake")
# -> FLAG; any capacity claim assuming -smp is invalidated. Never BLOCK (this
# is an enabling check; no timing claim is made on TCG — TSR-TIM-001).
check_pe_online() {
  expected_smp="$1"; boot_log="$2"
  need_file "$boot_log"
  case "$expected_smp" in (*[!0-9]*|'') emit "ERROR: expected_smp must be an integer: '$expected_smp'" >&2; exit 2;; esac
  not_awake=$(count_matches 'PE is not awake' "$boot_log")
  [ -n "$not_awake" ] || not_awake=0
  online=$((expected_smp - not_awake))
  [ "$online" -ge 0 ] || online=0
  if [ "$not_awake" -gt 0 ]; then
    flag "TSR-PE-001" "PE shortfall: -smp=$expected_smp, $not_awake not awake -> online=$online (capacity claims @ $expected_smp INVALID)"
  else
    pass "TSR-PE-001" "all $expected_smp configured PEs report awake"
  fi
}

# --- TSR-NET-001 -------------------------------------------------------------
# Host net stack down -> annunciate net-degraded (FLAG, non-blocking). Any
# future host-mediated channel must treat this flag as "dead on arrival".
annunciate_net_state() {
  boot_log="$1"
  need_file "$boot_log"
  if has_match 'network stack down' "$boot_log" || has_match 'Address family not supported' "$boot_log"; then
    NET_DEGRADED=1
    flag "TSR-NET-001" "host network stack down -> net-degraded (host-mediated channels dead on arrival)"
  else
    pass "TSR-NET-001" "host network stack initialised (net-nominal)"
  fi
}

usage() {
  cat <<EOF
Usage: $0 --log <boot_log> [--smp N] [--g2conf <g2.conf>]
          [--vdev-manifest F] [--rmgr-manifest F] [--rmgr-policy F]

Runs all Phase-1 bring-up TSR checks against <boot_log> and prints a
structured PASS/FLAG/BLOCK summary. Exit codes:
  0  bring-up nominal (no FLAG, no BLOCK)
  1  bring-up BLOCKED (>=1 TSR-CFG-001/TSR-RMGR-001 block)  [hard fail]
  3  bring-up DEGRADED (FLAGs only, no BLOCK)               [dev-twin allow]
  2  usage / input error
EOF
}

main() {
  boot_log=""; smp="2"; g2conf="-"
  while [ $# -gt 0 ]; do
    case "$1" in
      --log)            boot_log="$2"; shift 2;;
      --smp)            smp="$2"; shift 2;;
      --g2conf)         g2conf="$2"; shift 2;;
      --vdev-manifest)  VDEV_MANIFEST="$2"; shift 2;;
      --rmgr-manifest)  RMGR_MANIFEST="$2"; shift 2;;
      --rmgr-policy)    RMGR_POLICY="$2"; shift 2;;
      -h|--help)        usage; exit 0;;
      *)                emit "ERROR: unknown arg '$1'" >&2; usage >&2; exit 2;;
    esac
  done
  [ -n "$boot_log" ] || { emit "ERROR: --log is required" >&2; usage >&2; exit 2; }
  need_file "$boot_log"
  : > "$RESULTS"

  emit "=== QHV bring-up verification (Phase-1 gate, study-level / TCG) ==="
  emit "log: $boot_log   smp: $smp"
  emit "--- TSR-CFG-001 (config applied) ---";           assert_config_applied "$g2conf" "$boot_log"
  emit "--- TSR-RMGR-001 (resource managers armed) ---"; assert_rmgrs_armed "$RMGR_MANIFEST" "$boot_log" "$RMGR_POLICY"
  emit "--- TSR-VDEV-001 (vdev reconciliation) ---";     reconcile_vdevs "$VDEV_MANIFEST" "$boot_log"
  emit "--- TSR-PE-001 (online PE count) ---";           check_pe_online "$smp" "$boot_log"
  emit "--- TSR-NET-001 (host net state) ---";           annunciate_net_state "$boot_log"

  block_count=$(grep -c '^BLOCK$' "$RESULTS" 2>/dev/null || true); [ -n "$block_count" ] || block_count=0
  flag_count=$(grep -c '^FLAG$'  "$RESULTS" 2>/dev/null || true); [ -n "$flag_count" ]  || flag_count=0

  emit ""
  emit "=== bring-up summary ==="
  emit "  net-degraded flag : $NET_DEGRADED"
  emit "  FLAG  (degraded)  : $flag_count"
  emit "  BLOCK (hard fail) : $block_count"
  if [ "$block_count" -gt 0 ]; then
    emit "RESULT: BLOCK — bring-up MUST NOT proceed (>=1 blocking TSR failure)."
    exit 1
  elif [ "$flag_count" -gt 0 ]; then
    emit "RESULT: DEGRADED — annunciated, dev-twin allowed to continue (NOT nominal)."
    exit 3
  fi
  emit "RESULT: PASS — bring-up nominal."
  exit 0
}

case "${0##*/}" in
  verify-bringup.sh) main "$@";;
esac
