# delta.awk -- the ONE place the cloud->hw percentage delta is computed.
#
# Extracted from diff-results.sh (2026-09-19) so that CI can re-derive the
# published IPC deltas without a second copy of the formula. Per the project's
# CI constraint: extract a function, never fork the toolchain per runner.
# diff-results.sh and scripts/ci/claims_gate.py now call THIS file, so a change
# to the formula moves both at once and cannot silently diverge.
#
# Inputs (awk -v): cp50 hp50 cp99 hp99 cmax hmax   -- cloud/hw values, ns.
# MODE (awk -v):   unset -> the human report diff-results.sh has always printed,
#                           byte-for-byte unchanged.
#                  "csv" -> machine-readable "label,cloud,hw,delta,pct" for CI.
#
# The program is BEGIN-only on purpose: awk exits without reading stdin.

function twin_pct(c, h) {
    return (c == 0) ? 0 : ((h - c) / c) * 100
}

function twin_row(label, c, h,    d, pct) {
    d = h - c
    pct = twin_pct(c, h)
    if (MODE == "csv")
        printf "%s,%.0f,%.0f,%.0f,%.10f\n", label, c, h, d, pct
    else
        printf "  %-5s  cloud=%-12.0f hw=%-12.0f delta=%-+13.0f (%-+6.1f%%)\n", label, c, h, d, pct
}

BEGIN {
    twin_row("P50", cp50, hp50)
    twin_row("P99", cp99, hp99)
    twin_row("Max", cmax, hmax)
}
