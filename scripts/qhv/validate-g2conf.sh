#!/usr/bin/env sh
#
# validate-g2conf.sh — validate an auto-generated qvm g2.conf against a
# locked-down allow-list before `qvm @g2.conf` (TCR-CFG-001, fail-closed).
#
# The post_start.custom snippet emits g2.conf at host boot. Before qvm
# consumes it, this validator checks every directive's leading keyword against
# g2.conf.allow. Any keyword NOT on the allow-list (an unknown/forbidden
# directive, an extra vdev beyond least-vdev, etc.) makes validation FAIL
# CLOSED: the caller must NOT launch qvm. This implements the IMPLEMENTABLE
# FLOOR (validate-against-locked-template).
#
#   study-only ceiling: a real programme would additionally verify a
#   cryptographic SIGNATURE over g2.conf against a key in a hardware-backed
#   store (TCR-CFG-001 / TCR-SB-001). No RoT exists on the TCG leg, so signing
#   is NOT implemented here; do not fake a trust root that does not exist.
#
# Usage:
#   validate-g2conf.sh <g2.conf> [allow-list]
#     allow-list defaults to ./g2.conf.allow next to this script.
# Exit: 0 = valid (safe to launch qvm), 1 = REJECTED (fail-closed), 2 = usage.
#
# Pure POSIX sh. No bashisms.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

emit() { printf '%s\n' "$*"; }

main() {
  [ $# -ge 1 ] || { emit "Usage: $0 <g2.conf> [allow-list]" >&2; exit 2; }
  g2conf="$1"
  allow="${2:-$SCRIPT_DIR/g2.conf.allow}"
  [ -f "$g2conf" ] || { emit "CFG-GATE: ERROR g2.conf not found: $g2conf" >&2; exit 2; }
  [ -f "$allow" ]  || { emit "CFG-GATE: ERROR allow-list not found: $allow" >&2; exit 2; }

  # Build the set of permitted keywords (strip comments/blanks).
  allowed=$(sed -e 's/#.*$//' -e 's/[[:space:]]*$//' -- "$allow" | grep -v '^[[:space:]]*$' || true)
  [ -n "$allowed" ] || { emit "CFG-GATE: ERROR empty allow-list: $allow" >&2; exit 2; }

  # Required-directive floor (TCR-CFG-001, finding CV-1): the allow-list bounds
  # WHICH directives may appear (forbidden-absence), but on its own it accepts a
  # contentless/truncated g2.conf because an empty file has no forbidden
  # directive. A qvm guest cannot boot without a memory region, a cpu, a loaded
  # IFS and at least one boot vdev — and a truncate-to-empty attack must NOT
  # pass validate-before-use. So a valid g2.conf MUST also contain each of these
  # mandatory keywords, plus >=1 'vdev'. This makes the gate fail CLOSED on an
  # empty/incomplete config rather than fail open.
  REQUIRED="system ram cpu load"
  seen=""
  vdev_count=0

  violations=0
  lineno=0
  # Read each g2.conf line; the directive keyword is the first token after
  # leading whitespace (g2.conf uses indentation for nested directives).
  while IFS= read -r raw || [ -n "$raw" ]; do
    lineno=$((lineno + 1))
    # drop comments and surrounding whitespace
    line=$(printf '%s' "$raw" | sed -e 's/#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    [ -n "$line" ] || continue
    kw=$(printf '%s' "$line" | awk '{print $1}')
    # Record presence for the required-directive floor (checked after the loop).
    case " $seen " in *" $kw "*) ;; *) seen="$seen $kw";; esac
    [ "$kw" = "vdev" ] && vdev_count=$((vdev_count + 1))
    if printf '%s\n' "$allowed" | grep -qx -- "$kw"; then
      # Enforce least-vdev at the TYPE level too: a 'vdev <type>' line must
      # name an allowed vdev type, else a forbidden device (e.g. passthru)
      # would slip through on the allowed 'vdev' keyword alone.
      if [ "$kw" = "vdev" ]; then
        vtype=$(printf '%s' "$line" | awk '{print $2}')
        if printf '%s\n' "$allowed" | grep -qx -- "vdev:$vtype"; then
          :
        else
          emit "CFG-GATE: REJECT line $lineno: forbidden vdev type '$vtype'  -> '$line'"
          violations=$((violations + 1))
        fi
      fi
    else
      emit "CFG-GATE: REJECT line $lineno: forbidden directive '$kw'  -> '$line'"
      violations=$((violations + 1))
    fi
  done < "$g2conf"

  # Required-directive floor: every mandatory keyword must have appeared, and
  # at least one vdev must be declared. A missing keyword is a fail-CLOSED
  # violation just like a forbidden one (CV-1: empty/truncated config).
  for req in $REQUIRED; do
    case " $seen " in
      *" $req "*) ;;
      *) emit "CFG-GATE: REJECT missing required directive '$req' (incomplete/empty g2.conf)"
         violations=$((violations + 1));;
    esac
  done
  if [ "$vdev_count" -eq 0 ]; then
    emit "CFG-GATE: REJECT no 'vdev' declared (a guest needs >=1 boot vdev)"
    violations=$((violations + 1))
  fi

  if [ "$violations" -gt 0 ]; then
    emit "CFG-GATE: FAIL-CLOSED — $violations policy violation(s) (forbidden and/or missing-required); qvm MUST NOT be launched."
    exit 1
  fi
  emit "CFG-GATE: PASS — all directives within locked-down allow-list ($allow)."
  emit "CFG-GATE: NOTE signature verification is study-only (no RoT on TCG leg)."
  exit 0
}

main "$@"
