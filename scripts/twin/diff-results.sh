#!/usr/bin/env bash
#
# Phase 4
# diff-results.sh — compare a cloud-twin benchmark CSV against a HW-twin
#                   benchmark CSV. Validates the schema invariants first
#                   (per docs/digital-twin-design.md §3) and then prints
#                   the percentile + boot-time deltas.
#
# Usage:
#   ./scripts/twin/diff-results.sh results/cloud/aws1.csv results/hw/orin1.csv
#
# CSV header is expected to contain (commented lines beginning with `#`):
#   # ifs_sha256: <64hex>
#   # git_sha:    <40hex>
#   # twin_side:  cloud | hw
#   # host_uname: <output of uname -a>
#   # iterations: <n>
#   # payload:    <bytes>
#
# If ifs_sha256 differs between the two files, the diff fails. That is
# the load-bearing invariant — without it, comparing the two CSVs
# produces comparable-looking-but-incomparable numbers.

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <cloud_csv> <hw_csv>" >&2
  exit 1
fi

cloud_csv="$1"
hw_csv="$2"

if [[ ! -f "${cloud_csv}" ]]; then
  echo "ERROR: cloud CSV not found: ${cloud_csv}" >&2
  exit 1
fi
if [[ ! -f "${hw_csv}" ]]; then
  echo "ERROR: HW CSV not found: ${hw_csv}" >&2
  exit 1
fi

# Extract a labelled comment-header field. Lines look like:  "# field: value"
extract() {
  local file="$1" field="$2"
  awk -v f="${field}:" '/^#/ { for (i=1;i<=NF;i++) if ($i==f) { sub(/^# *[A-Za-z_]+: */,""); print; exit } }' "${file}"
}

cloud_sha="$(extract "${cloud_csv}" ifs_sha256)"
hw_sha="$(extract "${hw_csv}"    ifs_sha256)"

echo "[1/3] Verifying invariants ..."
if [[ -z "${cloud_sha}" || -z "${hw_sha}" ]]; then
  echo "  WARNING: ifs_sha256 missing in one or both CSVs" >&2
fi
if [[ "${cloud_sha}" != "${hw_sha}" ]]; then
  echo "  FAIL: ifs_sha256 mismatch" >&2
  echo "    cloud: ${cloud_sha}" >&2
  echo "    hw   : ${hw_sha}" >&2
  echo "  The two CSVs were produced from DIFFERENT IFS images." >&2
  echo "  Re-run scripts/twin/sync.sh from the build host before comparing." >&2
  exit 2
fi
echo "  OK: ifs_sha256 matches (${cloud_sha:0:12}...)"

cloud_git="$(extract "${cloud_csv}" git_sha)"
hw_git="$(extract "${hw_csv}"    git_sha)"
if [[ "${cloud_git}" != "${hw_git}" ]]; then
  echo "  WARN: git_sha mismatch — ipc-test source differed between runs" >&2
  echo "    cloud: ${cloud_git}"
  echo "    hw   : ${hw_git}"
fi

echo
echo "[2/3] Headers:"
printf "  cloud: %s\n" "$(extract "${cloud_csv}" host_uname)"
printf "  hw   : %s\n" "$(extract "${hw_csv}"    host_uname)"

echo
echo "[3/3] Latency deltas (cloud → hw):"
# CSV body is expected to have these numeric columns:
#   metric,p50_us,p99_us,p999_us,max_us,boot_ms
# We compute per-row delta hw - cloud and percent change.
awk -F, '
  BEGIN { OFS="\t" }
  /^#/ { next }
  FNR==1 { for (i=1;i<=NF;i++) hdr[i]=$i; next }
  ARGIND==1 { for (i=1;i<=NF;i++) cloud[$1,hdr[i]]=$i; next }
  ARGIND==2 {
    metric=$1
    printf "  %-15s", metric
    for (i=2;i<=NF;i++) {
      c = cloud[metric,hdr[i]] + 0
      h = $i + 0
      d = h - c
      pct = (c == 0) ? 0 : (d/c)*100
      printf "  %-7s c=%-8.2f h=%-8.2f Δ=%-+8.2f (%-+5.1f%%)", hdr[i], c, h, d, pct
    }
    printf "\n"
  }
' "${cloud_csv}" "${hw_csv}"

echo
echo "Done. See docs/digital-twin-design.md §4 for the methodology this diff implements."
