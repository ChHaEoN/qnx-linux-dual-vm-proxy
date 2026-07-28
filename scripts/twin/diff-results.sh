#!/usr/bin/env bash
#
# Phase 4
# diff-results.sh — compare a cloud-twin benchmark CSV against a HW-twin
#                   benchmark CSV.
#
# Usage:
#   ./scripts/twin/diff-results.sh results/cloud/cloud-ipc-latest.csv results/hw/orin-ipc-latest.csv
#
# 2026-07-28 rewrite: the original version of this script assumed a CSV
# shape (comment-header `# ifs_sha256: ...` lines + a `metric,p50_us,...`
# body) that neither results/cloud/ nor results/hw/ has ever actually
# produced — that shape was aspirational (written before any real CSV
# existed) and running the old script against real output silently
# misread the first data row as a header and printed nonsense deltas.
# The real, as-built schema (see results/cloud/header.csv and
# results/hw/header.csv, identical on both legs) is a flat, headerless
# body:
#   unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes
# This version parses that schema. It does NOT re-implement the old
# ifs_sha256/git_sha invariant check — no CSV-writing client on either
# leg (qnx-host-client/client.c, linux-client/client.c) has ever embedded
# those fields, so there was nothing real to check; re-adding it here
# would just be a second aspirational check. If scripts/twin/sync.sh
# grows that capability later, this script should learn to check it then.
#
# Per docs/digital-twin-design.md §4 (already written, not new guidance):
# the cloud and HW legs do NOT currently run the same IPC topology —
# cloud is single-OS QNX<->QNX over a qvm virtio-console vdev under TCG;
# HW is heterogeneous QNX<->Linux over virtio-net/br0 under TCG (KVM is
# separately blocked — see docs/orin-port.md's risk register). A raw
# latency delta therefore confounds host, acceleration, AND
# transport+OS-pair — it is "mechanism-alive vs. heterogeneity", not a
# clean host-only comparison. This script prints the delta (it is still
# real, measured data, worth looking at) but refuses to present it as a
# host-only effect: the warning below is not optional decoration.

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

expected_header="unix_ts,samples,payload_bytes,p50_ns,p99_ns,max_ns,cycles_per_sec,notes"

# Take the LAST data row of a headerless CSV (both files are append-only
# "-latest" logs; the most recent run is the one worth comparing).
last_row() {
  local file="$1"
  tail -n 1 -- "${file}"
}

read_field() {
  local row="$1" idx="$2"
  printf '%s' "${row}" | cut -d, -f"${idx}"
}

cloud_row="$(last_row "${cloud_csv}")"
hw_row="$(last_row "${hw_csv}")"

if [[ -z "${cloud_row}" || "${cloud_row}" == "${expected_header}" ]]; then
  echo "ERROR: ${cloud_csv} has no data row (only a header, or is empty)" >&2
  exit 1
fi
if [[ -z "${hw_row}" || "${hw_row}" == "${expected_header}" ]]; then
  echo "ERROR: ${hw_csv} has no data row (only a header, or is empty)" >&2
  exit 1
fi

c_samples=$(read_field "${cloud_row}" 2); c_payload=$(read_field "${cloud_row}" 3)
c_p50=$(read_field "${cloud_row}" 4);     c_p99=$(read_field "${cloud_row}" 5)
c_max=$(read_field "${cloud_row}" 6);     c_notes=$(read_field "${cloud_row}" 8)

h_samples=$(read_field "${hw_row}" 2); h_payload=$(read_field "${hw_row}" 3)
h_p50=$(read_field "${hw_row}" 4);     h_p99=$(read_field "${hw_row}" 5)
h_max=$(read_field "${hw_row}" 6);     h_notes=$(read_field "${hw_row}" 8)

echo "[1/3] Rows compared (last row of each file):"
printf "  cloud: %s\n" "${cloud_row}"
printf "  hw   : %s\n" "${hw_row}"

echo
echo "[2/3] Transport/notes (this is the load-bearing caveat, read it):"
printf "  cloud: %s\n" "${c_notes}"
printf "  hw   : %s\n" "${h_notes}"
if [[ "${c_payload}" != "${h_payload}" ]]; then
  echo "  WARN: payload_bytes differs (cloud=${c_payload}, hw=${h_payload}) — deltas below are not even same-message-size" >&2
fi

echo
echo "[3/3] Latency deltas (cloud -> hw), nanoseconds:"
awk -v cp50="${c_p50}" -v hp50="${h_p50}" -v cp99="${c_p99}" -v hp99="${h_p99}" -v cmax="${c_max}" -v hmax="${h_max}" '
  function row(label, c, h) {
    d = h - c
    pct = (c == 0) ? 0 : (d / c) * 100
    printf "  %-5s  cloud=%-12.0f hw=%-12.0f delta=%-+13.0f (%-+6.1f%%)\n", label, c, h, d, pct
  }
  BEGIN {
    row("P50", cp50, hp50)
    row("P99", cp99, hp99)
    row("Max", cmax, hmax)
  }
'

cat <<'EOF'

*** NOT a host-only comparison — read before quoting these numbers ***
Per docs/digital-twin-design.md §4, this diff confounds THREE variables
at once, not one:
  1. host          Graviton3 Neoverse-V1 (cloud)  vs.  Tegra234 A78AE (hw)
  2. acceleration  TCG (cloud, no /dev/kvm)        vs.  TCG (hw, KVM blocked
                    by the GICv3/NISV finding in docs/orin-port.md)
  3. transport+OS  single-OS QNX<->QNX console     vs.  heterogeneous
                    QNX<->Linux virtio-net/br0
Variable 2 happens to match today (both TCG) only because HW's KVM path
is separately blocked, not by design. The cloud number is a
mechanism-alive sanity figure (15 samples, capped by an unresolved
qvm/TCG virtio-queue stall); the HW number is a real, stable 100k-sample
run. Read this as "mechanism-alive vs. heterogeneity", not as evidence
about host CPU speed — that comparison does not exist yet in this repo.
EOF

echo
echo "Done. See docs/digital-twin-design.md §4/§5 for the methodology and open caveats."
