#!/usr/bin/env sh
#
# extract-ipc-result.sh — transcribe qnx-host-client's printed summary out of
# a captured QHV serial log into results/cloud/cloud-ipc-latest.csv.
#
# qnx-host-client runs INSIDE the QNX host image's own filesystem (a raw disk
# under QEMU-TCG), which has no path back to this Windows checkout, so its
# own attempt to fopen() a CSV via a relative path fails harmlessly (see
# ipc-test/qnx-host-client/client.c) -- the program's STDOUT summary line is
# still captured verbatim in the serial log by launch-qhv-tcg.ps1. This script
# reads that captured, real, already-printed output and writes it into the
# results/cloud/header.csv schema. It never invents a number: every field is
# taken from a value qnx-host-client itself printed.
#
# Usage: extract-ipc-result.sh <boot_log> [csv_out] [notes]
#   csv_out  default results/cloud/cloud-ipc-latest.csv (an empty argument too)
#   notes    the row's notes field, one CSV field: no comma, CR or newline.
#            Default "tcg-qvm-virtio-console;transcribed-from-serial-log:<boot_log
#            basename>", the cloud leg's value, so existing callers are unaffected.
#            The native M3 leg passes its own and writes under
#            results/orin-native-port/, never results/cloud/ (m3-design.md §4.4).
# Exit: 0 = row appended, 1 = summary not found in <boot_log>, 2 = usage/IO error.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

boot_log="${1:-}"
csv_out="${2:-$REPO_ROOT/results/cloud/cloud-ipc-latest.csv}"
notes="${3:-}"

[ -n "$boot_log" ] || { echo "Usage: $0 <boot_log> [csv_out] [notes]" >&2; exit 2; }
[ -f "$boot_log" ] || { echo "extract-ipc-result.sh: not found: $boot_log" >&2; exit 2; }
cr=$(printf '\r')
nl='
'
case "$notes" in
  *,*|*"$cr"*|*"$nl"*)
    echo "extract-ipc-result.sh: notes must not contain a comma, CR or newline (it is one CSV field)" >&2
    exit 2 ;;
esac

summary_line=$(grep -E '^samples=[0-9]+ payload=[0-9]+ cps=[0-9]+$' -- "$boot_log" | tail -n1 || true)
latency_line=$(grep -E '^P50=[0-9]+ ns  P99=[0-9]+ ns  Max=[0-9]+ ns$' -- "$boot_log" | tail -n1 || true)

[ -n "$summary_line" ] || { echo "extract-ipc-result.sh: no 'samples=...' line found in $boot_log" >&2; exit 1; }
[ -n "$latency_line" ] || { echo "extract-ipc-result.sh: no 'P50=...' line found in $boot_log" >&2; exit 1; }

samples=$(printf '%s' "$summary_line" | sed -E 's/^samples=([0-9]+).*/\1/')
payload=$(printf '%s' "$summary_line" | sed -E 's/.*payload=([0-9]+).*/\1/')
cps=$(printf '%s'     "$summary_line" | sed -E 's/.*cps=([0-9]+)$/\1/')
p50=$(printf '%s'  "$latency_line" | sed -E 's/^P50=([0-9]+).*/\1/')
p99=$(printf '%s'  "$latency_line" | sed -E 's/.*P99=([0-9]+).*/\1/')
maxv=$(printf '%s' "$latency_line" | sed -E 's/.*Max=([0-9]+) ns$/\1/')

unix_ts=$(date +%s)
log_base=$(basename -- "$boot_log")

if [ ! -f "$csv_out" ]; then
  echo "extract-ipc-result.sh: $csv_out does not exist; creating from header.csv" >&2
  cp -- "$REPO_ROOT/results/cloud/header.csv" "$csv_out"
fi

[ -n "$notes" ] || notes="tcg-qvm-virtio-console;transcribed-from-serial-log:$log_base"

printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "$unix_ts" "$samples" "$payload" "$p50" "$p99" "$maxv" "$cps" \
  "$notes" \
  >> "$csv_out"

echo "extract-ipc-result.sh: appended row to $csv_out"
