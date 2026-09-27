#!/usr/bin/env bash
# run-free.sh -- the last-byte test: is the guest's costly read of network data the one that takes
# the frame's last byte? Phase 3b / A6, 2026-09-27; follows 20260927T-a6-orin-offload.
# The owner asked for this run (2026-09-26, to go on overnight unattended: KVM guests only).
#
# WHAT IS KNOWN. On one vCPU the guest's second read() of a network-delivered 64-byte frame takes
# ~12.8 us, against ~7.0 us for a read of loopback data; not the other vCPU (pin), not a wait for
# left-over work (spin), not the receive offloads (offload). In every timed case so far the second
# read took the frame's last bytes, so it may also have released the received buffer: a cluster
# from vtnet's receive ring for network data, a small buffer for loopback data.
#
# THE MANIPULATION. The frame's size, with the endpoint's read pattern fixed per port
# (ifs-pina.bin's timed endpoint on vCPU 0; one vCPU):
#   d64  :7120  64 B, one read                                  no second read
#   d96  :7120  96 B, read 64 then 32: the second takes the last 32 bytes
#   s64  :7122  64 B, read 32 then 32: the second takes the last 32 bytes
#   s96  :7122  96 B, read 32, 32, 32: the second leaves 32 bytes in the socket
# So s96's second read is the only one that does not take the frame's last byte.
#
# THE RUN. One guest boot per round (ifs-pina.bin, -smp 1), the four arms in a Williams order
# over them (period 4), K=12. 64/96-byte frames at 2 ms, n=1000 after 200 warm-up. QEMU pinned to
# cores 0-2, the probe to core 4, the governor pinned, c7 off, no load. About 10 min. The
# endpoint and image are the pin record's, so nothing new was booted before this was written.
#
# THE RULE, fixed here before any run (free_report.py applies it). Per arm and round: the probe's
# p50, and the endpoint's printed medians (r2, w, svc) for the connection that served the arm --
# per port, the boot's connections of n + warm-up frames in the order its arms ran (order.log).
# Differences are paired within the round; per difference, the median over rounds with the
# distribution-free interval of widest coverage >= 95% (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the second read costs more than a loopback read because it takes
# the frame's last byte and so releases the received buffer.
#   P1 a second read that leaves bytes behind is cheaper: r2(s96) - r2(s64) <= -3 us.
#   P2 it is as cheap as a loopback read: r2(s96) <= 8.5 us.
#   P3 two second reads that both take the last bytes cost the same: r2(d96) - r2(s64) within
#      2 us of 0.
# Not predicted, reported: the round trips (s96 makes three reads), w and svc.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own frame size
#   M2 every arm's connection printed reads and timing as designed: reads per frame 1 (d64),
#      2 (d96, s64), 3 (s96), a second read in every frame but d64's
#
# What this does NOT test: what the release costs, if it does; two vCPUs; another boot pattern;
# the tail.
#
# NEEDS: no QEMU running; IMG (ifs-pina.bin), DISK. CSTATE=shallow (set before the library). No
# load. K a multiple of 4.
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
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/free_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IMG_S="${IMG_S:-$HOME/output/ifs-pina.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
SETTLE_S="${SETTLE_S:-3}"
CFGS=(U1)
declare -A IMG=([U1]="$IMG_S")
declare -A SMPC=([U1]=1)
MODES=(d64 d96 s64 s96)
declare -A PORT=([d64]=7120 [d96]=7120 [s64]=7122 [s96]=7122)
declare -A SIZE=([d64]=64 [d96]=96 [s64]=64 [s96]=96)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(U1d64 U1d96 U1s64 U1s96)
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

run_arm() {   # $1 config  $2 arm (d64|d96|s64|s96)  $3 round
	local a="$1$2" r="$3"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	PROBE_FRAME_BYTES="${SIZE[$2]}" m_probe "$OUT" "$a"_r"$r" "$GUEST" "${PORT[$2]}"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "r$r $a"
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
m_require_balanced_k "$K" "${#MODES[@]}"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_S" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_S$DISK" in *" "*) die "the images and the disk may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes"

m_prepare_out "${OUT:-}" "$HOME/free-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply

boot_vm U1 preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "free"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"d64": 7120, "d96": 7120, "s64": 7122, "s96": 7122}' \
	'"sizes": {"d64": 64, "d96": 96, "s64": 64, "s96": 96}' \
	"\"image_sha256\": \"$(_sha "$IMG_S")\"" \
	'"configs": {"U1": "ifs-pina.bin, -smp 1"}' \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; per boot the four arms in a Williams order over them (period 4); see order.log"' \
	'"kvm_stats": 1' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one one-vCPU boot per round, four arms per boot -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#CFGS[@]}"); do order+=("${CFGS[$i]}"); done
	modes=()
	for i in $(m_williams_row "$r" "${#MODES[@]}"); do modes+=("${MODES[$i]}"); done
	line="round $r order:"
	for c in "${order[@]}"; do
		boot_vm "$c" "${c}_r$r"
		for m in "${modes[@]}"; do run_arm "$c" "$m" "$r"; line="$line $c$m"; done
		stop_vm || die "the guest of ${c}_r$r would not stop"
	done
	echo "$line" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" U1s64 "${ARMS[@]}"
say "the last byte, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
