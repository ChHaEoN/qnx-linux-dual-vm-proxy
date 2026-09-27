#!/usr/bin/env bash
# run-trace2.sh -- the kernel-trace test, second question: where, inside the guest, does a TCP
# claim exchange spend any time it costs over a UDP one? Phase 3b / A6, 2026-09-27; follows
# 20260927T-a6-orin-trace. The owner asked for this run (2026-09-27: "照你建議的做").
#
# WHAT IS KNOWN. The monitor's claim round trip over TCP (:7100) and over UDP (:7101) at 2 ms
# spacing: record 20260927T-a6-orin-someip, and on a1.metal record 20260927T-a6-a1metal-someip
# (both held locally). The monitor's own calls are one read and one write per TCP frame, one recvfrom
# and one sendto per datagram: two messages to io-sock per exchange either way. Whether any
# difference is spent in the guest, or on the host (Linux's TCP, QEMU), is the question.
#
# THE INSTRUMENT. The guest's kernel event trace, as in run-trace.sh: ifs-trace.bin, qnx-tracectl
# on :7140, guesttrace.py. Per window, over the span from the monitor's first message to io-sock
# to its last, the running time of every guest thread, in four classes: idle (procnto's idle
# thread), io-sock (every io-sock thread), the monitor, and the rest (procnto's other threads,
# every other process). Per exchange: each class's time divided by the exchanges in the span,
# counted as half the monitor's messages to io-sock. busy = everything but idle.
#
# THE RUN. ifs-trace.bin, -smp 1; K pairs of trace windows, three pairs per guest boot, the pair's
# order T U or U T alternating by pair. Per window one trace of TRACE_S s while the probe sends
# n + warm-up 64-byte frames at 2 ms: T to the TCP monitor (:7100), U to the UDP monitor (:7101).
# QEMU pinned to cores 0-2, the probe to core 4, the trace client to core 5, the governor pinned,
# c7 off, no load. About 10 min.
#
# THE RULE, fixed here before any run (trace2_report.py applies it). Per window the per-exchange
# times above; per pair T - U; per quantity the median over pairs with the distribution-free
# interval of widest coverage >= 95% (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. No format trace was taken for this harness: it counts messages and
# running time, which the first kernel-trace test's format trace already covered.
#   H  the TCP exchange's extra time is guest CPU, spent in io-sock's TCP processing.
#   P1 the guest's busy time per exchange is >= 10 us longer for TCP than for UDP.
#   P2 io-sock's time per exchange accounts for >= 70% of that difference.
# Not predicted, reported: the monitor's and the rest's time per exchange, the trace events per
# exchange, and the traced round trips.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every window's trace is whole: tracectl's three sections rc 0, the trace's buffer
#      sequence contiguous, every event on CPU 0, >= 300 exchanges in the span
#   M2 the premise survives the tracing: the probe's p50 is >= 10 us longer for T than for U
#      (median over pairs of the pair differences)
#   M3 every window's probe: n samples, none rejected, none bad, its transport
#
# What this does NOT test: the host's share of the difference (Linux's TCP, QEMU's virtio-net);
# which io-sock code runs; two vCPUs; the tail. Tracing costs time per event, and TCP makes more
# events, so part of a busy-time difference can be the trace's own cost: the report counts events.
#
# NEEDS: no QEMU running; IMG (ifs-trace.bin), DISK. CSTATE=shallow (set before the library).
# No load. K a multiple of 6.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
N="${N:-500}"
K="${K:-12}"
WARMUP="${WARMUP:-100}"
INTERVAL_MS=2
TRACE_S="${TRACE_S:-3}"
PAIRS_PER_BOOT=3
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
CLIENT="${CLIENT:-$here/tracectl_client.py}"
REPORT="${REPORT:-$here/trace2_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IMG_S="${IMG_S:-$HOME/output/ifs-trace.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
SETTLE_S="${SETTLE_S:-3}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=0
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
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

tracectl_ping() {
	python3 -c 'import socket,sys; s=socket.create_connection((sys.argv[1],7140),timeout=3); s.sendall(b"ping\n"); sys.exit(0 if s.recv(64)==b"tracectl ok\n" else 1)' \
		"$GUEST" 2>> "$OUT/check.log"
}

boot_vm() {   # $1 label
	local lab="$1" log="$OUT/console-$1.log" i args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	BOOTED=1
	IFS_BIN="$IMG_S" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP=1 MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG_S "*) ;; *) die "boot $lab: QEMU was not given $IMG_S" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = 1 ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp 1"
	for i in $(seq 1 40); do echo_check 7122 "$lab-7122" && break; sleep 0.5; done
	echo_check 7122 "$lab-7122" || die "boot $lab: no endpoint echoing on :7122"
	for i in $(seq 1 20); do tracectl_ping && break; sleep 0.5; done
	tracectl_ping || die "boot $lab: no qnx-tracectl answering on :7140"
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG_S") smp=1 qemu_pid=$VM_PID" >> "$OUT/boots.log"
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

run_window() {   # $1 kind (T|U)  $2 pair
	local tag="$1_r$2" f="$OUT/started-$1_r$2" cp i
	rm -f "$f"
	# FIXED after the first run (2026-09-27): the reading takes ~2 s (tegrastats), and taken
	# after "started" it pushed the load late into the trace window. It is taken before the
	# trace starts now; nothing else changed.
	m_thermal "$tag before" >> "$OUT/thermal.log"
	taskset -c "$CORE_AUX" python3 "$CLIENT" "$GUEST" 7140 "$TRACE_S" "$OUT/trace-$tag.txt" "$f" \
		2>> "$OUT/tracectl.err" &
	cp=$!
	for i in $(seq 1 100); do [ -e "$f" ] && break; sleep 0.05; done
	[ -e "$f" ] || { wait "$cp"; die "window $tag: qnx-tracectl never said started -- see tracectl.err"; }
	if [ "$1" = T ]; then
		m_probe "$OUT" "T_r$2" "$GUEST" 7100
	else
		m_probe "$OUT" "U_r$2" "$GUEST" 7101 "" udp
	fi
	m_thermal "$tag after" >> "$OUT/thermal.log"
	gpu_idle_around "$tag"
	wait "$cp" || die "window $tag: the trace client failed -- see tracectl.err"
	sleep 1
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
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every window"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
[ $((K % (2 * PAIRS_PER_BOOT))) = 0 ] || die "K=$K is not a multiple of $((2 * PAIRS_PER_BOOT))"
for f in "$PROBE" "$CLIENT" "$REPORT" "$LAUNCH" "$IMG_S" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_S$DISK" in *" "*) die "the images and the disk may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes"

m_prepare_out "${OUT:-}" "$HOME/trace2-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "trace2"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"T": 7100, "U": 7101, "tracectl": 7140}' \
	"\"trace_s\": $TRACE_S" \
	"\"image_sha256\": \"$(_sha "$IMG_S")\"" \
	'"config": "ifs-trace.bin, -smp 1"' \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	"\"boots\": \"one per $PAIRS_PER_BOOT pairs; a pair's order T U if the pair is odd, U T if even; see order.log\"" \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K pairs, n=$N, $PAIRS_PER_BOOT pairs per one-vCPU boot, a ${TRACE_S} s trace per window -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/order.log"
for p in $(seq 1 "$K"); do
	if [ $(((p - 1) % PAIRS_PER_BOOT)) = 0 ]; then
		boot_vm "b$(((p - 1) / PAIRS_PER_BOOT + 1))"
	fi
	if [ $((p % 2)) = 1 ]; then kinds="T U"; else kinds="U T"; fi
	for kind in $kinds; do run_window "$kind" "$p"; done
	echo "pair $p order: $kinds boot b$(((p - 1) / PAIRS_PER_BOOT + 1))" >> "$OUT/order.log"
	if [ $((p % PAIRS_PER_BOOT)) = 0 ]; then
		stop_vm || die "the guest of pair $p would not stop"
	fi
	say "pair $p/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
UDP_ARMS="U" m_require_complete "$OUT" T U
say "TCP against UDP in the guest's kernel trace, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
