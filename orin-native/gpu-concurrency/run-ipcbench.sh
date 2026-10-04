#!/usr/bin/env bash
# run-ipcbench.sh -- what one call costs inside the guest, by kind: a kernel call, a QNX message
# pass, a read of /dev/zero, and an io-sock loopback read. Phase 3b / A6, 2026-09-26; follows
# 20260926T-a6-orin-readtime. The owner asked for this run (2026-09-26).
#
# WHAT IS KNOWN. What a socket read() that finds its 32 bytes already there takes inside the
# guest, against the native one, is in record 20260926T-a6-orin-readtime; its vCPU run time and
# VM exits on one vCPU, in 20260926T-a6-orin-readpath (both held locally). A QNX read() is a
# message to the server behind the fd, so its time could be the kernel's message pass, the
# kernel entry, or the server's -- io-sock's -- own code.
#
# THE INSTRUMENT. ipc-test/qnx-ipcbench (qnx-ipcbench in ifs-bench.bin, a TCP-triggered service
# on :7130; the same source built natively with gcc, without the QNX-only ops). Each op is a
# pair: one untimed call, then one call timed on CLOCK_MONOTONIC, as the endpoint's second read
# follows its first. Ops: clock (the clock itself), kcall (SchedGet on QNX, getppid natively),
# zero (read 32 B of /dev/zero: on QNX a message to procnto), msg (MsgSend of 32 B to a server
# process on the same CPU, and its reply), msgx (the same to a server on the other CPU), sock (a
# TCP loopback pair inside the OS: the untimed call writes 64 B and reads 32, the timed call
# reads the other 32, already there -- on QNX, io-sock). Regimes: "tight" (pairs back to back)
# and "spaced" (2 ms before each pair, as the A6 exchange). The calling thread runs on CPU 0 (the
# guest's vCPU 0; natively the probe's core, by taskset). Per op, regime and run: n = 500 timed
# calls, reported as p10/p50/p90/mean.
#
# THE RUN. K=12 rounds; per round the guest's run (G) and the native run (N), in an order
# alternating by round; the ops' order rotated by round. QEMU pinned to cores 0-2, the governor
# pinned, c7 off, no load. One guest boot. Before this was written, the bench's "check" command
# (it prints no timing) was run once natively and once in the guest.
#
# THE RULE, fixed here before any run (ipcbench_report.py applies it). Per side, op, regime and
# round, the run's p50; per side, op and regime, the median over rounds with the distribution-
# free interval of widest coverage >= 95% (d(3)..d(10), 96.1%, at K = 12). Values are raw: each
# includes the cost of one clock read, which the clock op measures.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the read's time in the guest is io-sock's own socket-read path;
# the kernel's message pass and its entry are cheap in the guest.
#   P1 the guest's message pass is cheap: msg, spaced, <= 5 us.
#   P2 a read served by procnto is cheap: zero, spaced, <= 5 us.
#   P3 an io-sock read is not: sock, spaced, >= 10 us.
#   P4 a kernel call is cheap: kcall, spaced, <= 2 us.
# Not predicted, reported: msgx (the other CPU), the tight regime, the native values, the clock.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every round has both sides' results for every op and regime, n = 500, and no "fail"
#
# What this does NOT test: what inside io-sock takes the time, if it does; whether a loopback
# read costs what a read of network-delivered data costs (the readtime record timed the
# latter); any guest but this one; the monitor.
#
# NEEDS: the guest running ifs-bench.bin under launch-qnx-kvm-bridged.sh; gcc. CSTATE=shallow
# (set before the library). No load.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
PORT=7130
N="${N:-500}"
K="${K:-12}"
GAP_US=2000
WARMUP=0                        # the common stamp's field: the bench's only warm-up is each pair's untimed call
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
SRC="${SRC:-$here/../../ipc-test/qnx-ipcbench/ipcbench.c}"
CLIENT="${CLIENT:-$here/ipcbench_client.py}"
BENCH_BIN="${BENCH_BIN:-$HOME/ipcbench/ipcbench-native}"
NOPS_G=6
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"

cleanup() {
	say "cleanup"
	m_cstate_restore; m_governor_restore
}

gpu_idle_around() {   # $1 label
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^$1 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $1 -- a GPU load ran beside this no-load run"
}

run_side() {   # $1 G|N  $2 round
	local s="$1" r="$2" rot=$(( ($2 - 1) % NOPS_G )) f="$OUT/bench-$1_r$2.txt"
	m_thermal "$s-r$r before" >> "$OUT/thermal.log"
	if [ "$s" = G ]; then
		taskset -c "$CORE_PROBE" python3 "$CLIENT" "$GUEST" "$PORT" run "$N" "$GAP_US" "$rot" > "$f" 2>&1 \
			|| die "the guest's run in round $r failed -- see $f"
	else
		taskset -c "$CORE_PROBE" "$BENCH_BIN" local run "$N" "$GAP_US" "$rot" > "$f" 2>&1 \
			|| die "the native run in round $r failed -- see $f"
	fi
	grep -q '^done$' "$f" || die "the $s run in round $r did not finish -- see $f"
	! grep -q '^fail ' "$f" || die "an op failed in the $s run of round $r -- see $f"
	m_thermal "$s-r$r after" >> "$OUT/thermal.log"
	gpu_idle_around "$s-r$r"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
for f in "$SRC" "$CLIENT" "$here/ipcbench_report.py"; do [ -r "$f" ] || die "missing: $f"; done
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every run"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
qp="$(m_pids_of qemu-system-aarch64)"
[ "$(printf '%s\n' "$qp" | grep -c .)" = 1 ] || die "not exactly one qemu-system-aarch64 is running"
KERNEL="$(tr '\0' '\n' < "/proc/$qp/cmdline" | grep -A1 -x -- -kernel | tail -1)"
[ -r "$KERNEL" ] || die "cannot read the guest's -kernel image ($KERNEL)"

m_prepare_out "${OUT:-}" "$HOME/ipcbench-out"
mkdir -p "$(dirname "$BENCH_BIN")"
gcc -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -o "$BENCH_BIN" "$SRC" > "$OUT/build-native.log" 2>&1 \
	|| die "could not build $BENCH_BIN -- see $OUT/build-native.log"
[ ! -s "$OUT/build-native.log" ] || die "the native build warned -- see $OUT/build-native.log"
trap cleanup EXIT

m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$PORT" "the guest's ipcbench"
taskset -c "$CORE_PROBE" python3 "$CLIENT" "$GUEST" "$PORT" check > "$OUT/check-G.txt" 2>&1 || die "the guest's check failed -- see $OUT/check-G.txt"
taskset -c "$CORE_PROBE" "$BENCH_BIN" local check > "$OUT/check-N.txt" 2>&1 || die "the native check failed -- see $OUT/check-N.txt"
! grep -q '^fail ' "$OUT/check-G.txt" "$OUT/check-N.txt" || die "an op failed its check -- see $OUT/check-*.txt"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "ipcbench"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $PORT" \
	"\"gap_us\": $GAP_US" \
	"\"guest_image\": \"$(basename "$KERNEL")\"" \
	"\"guest_image_sha256\": \"$(_sha "$KERNEL")\"" \
	"\"source_sha256\": \"$(_sha "$SRC")\"" \
	"\"bench_native_sha256\": \"$(_sha "$BENCH_BIN")\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(m_wifi_state)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"order": "per round the guest run and the native run, alternating by round; the ops rotated by round"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N per op and regime, gap ${GAP_US} us, the guest and native -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	if [ $(( r % 2 )) -eq 1 ]; then sides=(G N); else sides=(N G); fi
	echo "round $r order: ${sides[*]} rot $(( (r - 1) % NOPS_G ))" >> "$OUT/order.log"
	for s in "${sides[@]}"; do run_side "$s" "$r"; done
	sync
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
say "one call's cost by kind, by the rule above"
python3 "$here/ipcbench_report.py" "$OUT" || die "the report could not be made -- see above"
