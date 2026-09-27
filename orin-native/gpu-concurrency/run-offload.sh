#!/usr/bin/env bash
# run-offload.sh -- the receive-offload test: does the guest's read of network-delivered data cost
# more than a loopback read because of how the offloaded receive path holds the data?
# Phase 3b / A6, 2026-09-27; follows 20260927T-a6-orin-spin.
# The owner asked for this run (2026-09-26, to go on overnight unattended: KVM guests only).
#
# WHAT IS KNOWN. On one vCPU, what the endpoint's second read() of a network-delivered 64-byte
# frame costs in the guest, with and without a wait before it: record 20260927T-a6-orin-spin
# (held locally); what a read of loopback data already in a socket costs: record
# 20260927T-a6-orin-pin (held locally). The
# guest's vtnet0 negotiates receive offloads with QEMU: LRO (the host may hand it aggregated,
# unsegmented TCP data: tap-qnx's TSO) and receive checksum offload (the host may hand it data
# with the checksum unverified or partial: tap-qnx's tx-checksumming).
#
# THE MANIPULATION. Two images, one line apart (compare-ifs.py: against ifs-pina.bin only the
# startup script, build/ifs.build and build.date differ):
#   ifs-offon.bin   ifs-pina.bin plus `ifconfig vtnet0` (prints the options; nothing changed)
#   ifs-offoff.bin  ifs-pina.bin plus `ifconfig vtnet0 -lro -rxcsum`, then the same print
# Both boot with ONE vCPU (the difference to explain is a one-vCPU figure: the spin record):
#   N1  ifs-offon.bin    receive offloads on (the A6 default)
#   F1  ifs-offoff.bin   LRO and receive checksum offload off
# Before this was written each image was booted once, nothing timed, to check the endpoints,
# the benchmark and the offloads each configuration lists; what that showed is held locally.
#
# THE RUN. Per boot two probe arms, 64-byte frames at 2 ms, n=1000 after 200 warm-up: d64 on
# :7120 (one read per frame) and s64 on :7122 (two), in an order alternating by round, then one
# benchmark run (n=300). Tags N1d64 N1s64 F1d64 F1s64. Boots in a Williams order (period 2),
# K=12. QEMU pinned to cores 0-2, the probe to core 4, the governor pinned, c7 off, no load.
# About 15 min.
#
# THE RULE, fixed here before any run (offload_report.py applies it). Per arm and round: the
# probe's p50, and the endpoint's printed medians (r2, w, svc) for the connection that served
# the arm, from that boot's console. Differences are paired within the round; per difference,
# the median over rounds with the distribution-free interval of widest coverage >= 95%
# (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the read of network-delivered data costs more than a loopback read
# because of how the offloaded receive path holds the data; with the receive offloads off it
# costs what a loopback read costs.
#   P1 turning the receive offloads off shortens the second read: r2(F1s64) - r2(N1s64) <= -3 us.
#   P2 without them the read is as cheap as a loopback read: r2(F1s64) <= 8.5 us.
#   P3 the round trip's step follows: (F1s64 - F1d64) - (N1s64 - N1d64) <= -3 us.
# Not predicted, reported: the round-trip levels (without offloads each frame is checksummed
# twice), w and svc, the benchmark per configuration.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, 64-byte frames
#   M2 every arm's connection printed its reads and timing as designed
#   M3 the offloads were what each configuration says, every boot: N1's console lists vtnet0
#      with RXCSUM and LRO and tap-qnx has TSO on; F1's lists neither and tap-qnx has TSO off
#   M4 every boot's benchmark completed with no "fail"
#
# What this does NOT test: which of LRO and checksum offload matters, if either does; two vCPUs;
# what the offloaded path does in io-sock; another boot; the tail.
#
# NEEDS: no QEMU running; IMG_N (ifs-offon.bin), IMG_F (ifs-offoff.bin), DISK; ethtool.
# CSTATE=shallow (set before the library). No load. K a multiple of 2.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
BENCH_N=300
GAP_US=2000
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
CLIENT="${CLIENT:-$here/ipcbench_client.py}"
REPORT="${REPORT:-$here/offload_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IMG_N="${IMG_N:-$HOME/output/ifs-offon.bin}"
IMG_F="${IMG_F:-$HOME/output/ifs-offoff.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
SETTLE_S="${SETTLE_S:-3}"
CFGS=(N1 F1)
declare -A IMG=([N1]="$IMG_N" [F1]="$IMG_F")
declare -A SMPC=([N1]=1 [F1]=1)
declare -A PORT=([d64]=7120 [s64]=7122)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(N1d64 N1s64 F1d64 F1s64)
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
VM_PID=""; BOOTED=0

stop_vm() {   # sync first: a panic in QEMU's teardown once lost unflushed files
	local i
	[ -n "$VM_PID" ] || return 0
	sync
	kill -TERM "$VM_PID" 2>/dev/null
	for i in $(seq 1 30); do [ -d "/proc/$VM_PID" ] || break; sleep 0.5; done
	if [ -d "/proc/$VM_PID" ]; then
		kill -KILL "$VM_PID" 2>/dev/null; sleep 1
	fi
	[ -d "/proc/$VM_PID" ] && return 1
	VM_PID=""
	sync
	return 0
}

cleanup() {
	say "cleanup"
	if [ "$BOOTED" = 1 ]; then
		for VM_PID in $(m_pids_of qemu-system-aarch64); do
			stop_vm || echo "WARNING: the guest QEMU $VM_PID would not stop" >&2
		done
	fi
	VM_PID=""
	m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

pin_vm() {   # every QEMU thread on QEMU_CORES, read back per thread
	local t got
	for t in $(ls "/proc/$VM_PID/task"); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1 || [ ! -d "/proc/$VM_PID/task/$t" ] \
			|| die "taskset failed on QEMU thread $t"
		got="$(awk '/^Cpus_allowed_list:/ {print $2}' "/proc/$VM_PID/task/$t/status" 2>/dev/null)"
		[ -z "$got" ] || [ "$(_cpuset "$got")" = "$(_cpuset "$QEMU_CORES")" ] \
			|| die "QEMU thread $t reads back '$got', asked for '$QEMU_CORES'"
	done
}

echo_check() {   # $1 port  $2 label: only a sweep.c endpoint echoes a 2048-byte frame whole
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$GUEST" --port "$1" --n 3 --warmup 0 --interval-ms 0 \
		--timeout-s 3 --frame-bytes 2048 --tag "check-$2" --out "$OUT/check-$2.json" >> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 config  $2 label
	local c="$1" lab="$2" log="$OUT/console-$2.log" i args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	BOOTED=1
	IFS_BIN="${IMG[$c]}" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP="${SMPC[$c]}" MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel ${IMG[$c]} "*) ;; *) die "boot $lab: QEMU was not given ${IMG[$c]}" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "${SMPC[$c]}" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp ${SMPC[$c]}"
	for i in $(seq 1 40); do echo_check 7120 "$lab-7120" && break; sleep 0.5; done
	echo_check 7120 "$lab-7120" || die "boot $lab: no endpoint echoing on :7120"
	echo_check 7122 "$lab-7122" || die "boot $lab: no endpoint echoing on :7122"
	m_reachable "$GUEST" 7130 "boot $lab's ipcbench" > /dev/null
	echo "$lab tap-qnx $(ethtool -k tap-qnx | grep -E '^(tx-checksumming|tcp-segmentation-offload):' | tr '\n' ' ')" >> "$OUT/offloads.log"
	sleep "$SETTLE_S"
	echo "$lab config=$c image=$(basename "${IMG[$c]}") smp=${SMPC[$c]} qemu_pid=$VM_PID" >> "$OUT/boots.log"
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

run_arm() {   # $1 config  $2 mode (d64|s64)  $3 round
	local a="$1$2" r="$3"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	PROBE_FRAME_BYTES=64 m_probe "$OUT" "$a"_r"$r" "$GUEST" "${PORT[$2]}"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "r$r $a"
}

run_bench() {   # $1 config  $2 round
	local f="$OUT/bench-$1_r$2.txt"
	taskset -c "$CORE_PROBE" python3 "$CLIENT" "$GUEST" 7130 run "$BENCH_N" "$GAP_US" $(( ($2 - 1) % 6 )) > "$f" 2>&1 \
		|| die "the benchmark of $1 in round $2 failed -- see $f"
	grep -q '^done$' "$f" || die "the benchmark of $1 in round $2 did not finish -- see $f"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is already running: this harness boots its own guests"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- run scripts/orin/setup-bridge-orin.sh (a reboot drops it)"
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
m_require_balanced_k "$K" "${#CFGS[@]}"
for f in "$PROBE" "$CLIENT" "$REPORT" "$LAUNCH" "$IMG_N" "$IMG_F" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_N$IMG_F$DISK" in *" "*) die "the images and the disk may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes"
command -v ethtool > /dev/null || die "no ethtool: the offloads could not be checked"

m_prepare_out "${OUT:-}" "$HOME/offload-out"
: > "$OUT/offloads.log"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply

boot_vm N1 preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "offload"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"d64": 7120, "s64": 7122, "bench": 7130}' \
	"\"image_n_sha256\": \"$(_sha "$IMG_N")\"" \
	"\"image_f_sha256\": \"$(_sha "$IMG_F")\"" \
	'"configs": {"N1": "ifs-offon.bin (receive offloads on), -smp 1", "F1": "ifs-offoff.bin (ifconfig vtnet0 -lro -rxcsum), -smp 1"}' \
	"\"bench\": {\"n\": $BENCH_N, \"gap_us\": $GAP_US}" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "two per round, a Williams order over N1 F1 (period 2); per boot d64 and s64 in an order alternating by round, then the benchmark; see boots.log and offloads.log"' \
	'"kvm_stats": 1' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, boots N1 F1 (one vCPU, receive offloads on/off) in a Williams order, arms d64 s64 and a benchmark per boot -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#CFGS[@]}"); do order+=("${CFGS[$i]}"); done
	if [ $(( r % 2 )) -eq 0 ]; then modes=(d64 s64); else modes=(s64 d64); fi
	line="round $r order:"
	for c in "${order[@]}"; do
		boot_vm "$c" "${c}_r$r"
		for m in "${modes[@]}"; do run_arm "$c" "$m" "$r"; line="$line $c$m"; done
		run_bench "$c" "$r"
		stop_vm || die "the guest of ${c}_r$r would not stop"
	done
	echo "$line" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" N1d64 "${ARMS[@]}"
say "the receive offloads, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
