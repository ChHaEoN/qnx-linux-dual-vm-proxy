#!/usr/bin/env bash
# run-mmio.sh -- where the two ways into the guest's notified shared memory trap: every MMIO
# access the guest makes over an arm, counted by device and register from KVM's own tracepoint,
# for the console kick (K) and the MSI-X doorbell (B). Phase 3b / A6, 2026-09-29. The owner asked
# for it (2026-09-29): run-bell.sh counted KVM's MMIO exits per exchange; this names them.
#
# WHAT IS KNOWN. The two ways in, their latencies and KVM's MMIO exit counters per exchange on
# this board and on a1.metal: 20260929T-a6-orin-bell and 20260929T-a6-a1metal-bell (held
# locally). The same arms beside four other paths: 20260929T-a6-orin-paths (held locally).
#
# THE INSTRUMENTS.
#   guest  ifs-bell.bin, as run-bell.sh boots it: shmkick at slot 4096 on the virtio console
#          (K, /dev/vcon2 on the virtio-mmio transport at 0x0a003800) and shmkick at slot 8192 on
#          the MSI-X LPI (B). Both reply through the ivshmem Doorbell (BAR0 + 0xc, a KVM
#          ioeventfd).
#   host   latency_probe.py through libshmchan.so, as run-bell.sh; and ftrace with two events,
#          kvm:kvm_mmio (on Linux 5.15, arch/arm64/kvm/mmio.c traces every MMIO abort it
#          decodes before it knows who handles it) and kvm:kvm_userspace_exit, in the mono trace
#          clock. mmio_trace.py reduces each window on the board to accesses per guest-physical
#          address, and marks an access as handled in userspace when the same thread's next KVM
#          event is a KVM_EXIT_MMIO exit to QEMU. The raw trace is kept as text: its lines carry
#          QEMU's vCPU thread names and ids, the CPU, a timestamp, the address and the value
#          (a UART write's value is guest console text, already in console-*.log).
#   check  A format trace was taken over one boot of ifs-bell.bin before this was committed,
#          with no K or B exchange in it, to learn the two events' line shapes and to check
#          mmio_trace.py's parsing, its kernel/userspace marking and its read pairing. Only line
#          shapes with every number masked were printed, and yes/no answers computed by a filter
#          over the reducer's output: no count, address or value was looked at.
#
# THE ARMS: K, B and I (idle: the same wall time as n + warm-up exchanges, no exchange), all in
# every boot, in a Williams order over the three (period 6). n=1000 after 200 warm-up at 2 ms,
# K=6 rounds, one boot per round, -smp 2. QEMU pinned to cores 0-2, the probe to core 4, the
# trace's reader to core 5, the governor pinned, c7 off, no load. One trace window per arm, from
# before KVM's first counter snapshot to after its last; each window's length is recorded. About
# 8 min. Tracing costs time per event, so no latency here is a figure: the run's product is
# counts.
#
# THE RULE, fixed here before any run (mmio_report.py applies it). Per window, the accesses by
# region: GICD 0x08000000 (64 KiB), GITS 0x08080000 (128 KiB), GICR 0x080a0000, the console's
# virtio-mmio transport 0x0a003800 (0x200), other virtio-mmio 0x0a000000-0x0a003fff, the UART
# 0x09000000, ivshmem BAR0 and BAR1 (their addresses read from the boot's console, the
# "shm configured" and "msixcfg" lines), PCI ECAM, and anything else; each split into reads and
# writes, into handled in the kernel and in userspace, and by register. The background is taken
# out within the round: for any count, the I window's count per ns of I's window, times the K or
# B window's length, is subtracted before dividing by the arm's exchanges (warm-up included).
# Every scored quantity is the median over rounds of that net count per exchange; the
# distribution-free interval of widest coverage >= 95% (d(1)..d(6), 96.9%, at K = 6) is printed
# beside each, and beside K - B per region, and is not scored.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended. The thresholds were set knowing the records named above; what is blind is where
# the accesses fall.
#   H1 each way in masks and unmasks its interrupt through KVM's in-kernel model of the GIC: K's
#      SPI (the console's) at the distributor, B's LPI through the ITS's command queue; neither
#      needs QEMU for it.
#   P1 per exchange, K's GICD accesses >= 2.0 and B's <= 0.2; B's GITS accesses >= 2.0 and K's
#      <= 0.2. All four: HELD. The GICD pair or the GITS pair alone: PARTIAL. Neither: REFUTED.
#   H2 the console's userspace exits are its virtio-mmio transport's interrupt handling.
#   P2 per exchange, K's userspace-handled reads of the console transport's InterruptStatus
#      (+0x60) and writes of its InterruptACK (+0x64) each >= 0.9, together at least 90% of K's
#      userspace-handled accesses (the median of the per-round shares); B's accesses to that
#      transport <= 0.2. All: HELD. Otherwise REFUTED.
# Not predicted, reported: every region's accesses per exchange by read/write and kernel/user,
# the registers within GICD, GITS and the console's transport, K - B per region, the I windows'
# background per 2 ms, and each boot's LPI setup line from the startup's console output.
#
# THE CHECKS (none counts an outcome a prediction is about). A prediction prints VOID when a
# check fails, and every prediction rests on all of M1-M4:
#   M1 K and B have one round for each of 1..K of n samples after the warm-up, none rejected, none
#      bad, their own transport, the probe on its core; in each, the probe's own counts show
#      exchanges == notifications == warm-up + n, no early wake-up and no stray byte; every round
#      has an I window with KVM's snapshots; every window's length was recorded
#   M2 every window's trace is whole and only the two events: the entries-in-buffer/entries-written
#      header equal, no LOST line, every line parsed and their number equal to the buffer's
#      entries, at most one (per vCPU) userspace MMIO exit without its access and read without
#      its completion (a window's edges)
#   M3 the instrument sees in-kernel MMIO: in every K and B window the reply doorbell, writes to
#      BAR0 + 0xc, count 0.98-1.05 per exchange, and all of them are handled in the kernel; every
#      boot's console gives one BAR0 and one BAR1 (the harness stops a run whose boot does not)
#   M4 the trace sees every MMIO exit: per K and B window, the traced accesses are >= the rise of
#      KVM's mmio_exit_kernel + mmio_exit_user over the arm and exceed it by <= 2% + 20, and the
#      traced userspace-handled accesses likewise against mmio_exit_user
#
# What this does NOT test: the time any access costs (the trace slows every one); that an untraced
# run makes the same accesses (M4 compares the trace with KVM's counters only within the traced
# window); which interrupt a GICD or GITS access concerns (the report keeps no value); the other
# direction beyond the shared doorbell; ICC system-register traffic (not MMIO); what QEMU does
# after a userspace exit; anything about the QNX-supported MSI path. a1.metal: a replication
# there (scripts/aws's harness phase lists this harness) is a separate run on another kernel,
# where M3 and M4 re-establish what the trace sees. The startup is ours: not a QNX-supported
# configuration.
#
# NEEDS: no QEMU running; IMG_B (ifs-bell.bin; IFS_BIN is taken as well, for scripts/aws), DISK;
# tap-qnx on br0; gcc (libshmchan.so is built here); tracefs with kvm:kvm_mmio and
# kvm:kvm_userspace_exit, the mono clock, every CPU in tracing_cpumask, no other event enabled,
# nobody else tracing. CSTATE=shallow (set before the library). No load. K a multiple of 6.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

N="${N:-1000}"
K="${K:-6}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/mmio_report.py}"
REDUCE="${REDUCE:-$here/mmio_trace.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
IMG_B="${IMG_B:-${IFS_BIN:-$HOME/output/ifs-bell.bin}}"
DISK="${DISK:-$HOME/output/disk-qemu}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_BUF_KB_RUN="${TRACE_BUF_KB_RUN:-8192}"
TEVENTS="kvm/kvm_mmio kvm/kvm_userspace_exit"
SLOT_K=4096
SLOT_B=8192
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(K B I)
ARM_PROTOS="K=shmdb B=shmbell"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
VM_PID=""; BOOTED=0; TRACE_TOUCHED=0; KVM_DIR=""

tsu() {   # $1 = a shell command, run as root on the aux core
	taskset -c "$CORE_AUX" sudo -n sh -c "$1"
}

trace_events() {   # $1 = 0 or 1
	local e cmd="cd '$TRACE'"
	for e in $TEVENTS; do cmd="$cmd && echo $1 > events/$e/enable"; done
	tsu "$cmd"
}

trace_restore() {   # leave tracing as the preflight found it
	[ "$TRACE_TOUCHED" = 1 ] || return 0
	tsu "cd '$TRACE' && echo 0 > tracing_on" 2>/dev/null
	trace_events 0 2>/dev/null
	tsu "cd '$TRACE' && echo > trace && echo ${TRACE_CLOCK_BEFORE:-local} > trace_clock && echo ${TRACE_BUF_KB_BEFORE:-1408} > buffer_size_kb && echo ${TRACE_ON_BEFORE:-1} > tracing_on" 2>/dev/null \
		|| echo "WARNING: could not restore $TRACE -- events, the clock or the buffer size may be left changed" >&2
}

# The window's edges. KVM's two MMIO exit counters are read in the SAME root shell that turns
# tracing on (after it) and off (before it), with the time: every ms between a window's edge and
# a counter read is background the trace sees and the counters do not (M4), and a separate
# snapshot process (m_kvm_snap) takes tens of ms each way. Prints "t_ns kernel user".
edge() {   # $1 on|off
	local on off
	[ -n "$KVM_DIR" ] || die "no KVM debugfs directory for this boot"
	on="echo 1 > '$TRACE/tracing_on' && date +%s%N && cat '$KVM_DIR/mmio_exit_kernel' '$KVM_DIR/mmio_exit_user'"
	off="cat '$KVM_DIR/mmio_exit_kernel' '$KVM_DIR/mmio_exit_user' && date +%s%N && echo 0 > '$TRACE/tracing_on'"
	if [ "$1" = on ]; then
		tsu "$on" | tr '\n' ' ' | awk 'NF == 3 {print $1, $2, $3}'
	else
		tsu "$off" | tr '\n' ' ' | awk 'NF == 3 {print $3, $1, $2}'
	fi
}

trace_start() {   # an empty buffer, the two events on; then tracing on and the window's start
	TRACE_TOUCHED=1
	tsu "cd '$TRACE' && echo 0 > tracing_on && echo > trace" || die "could not clear the trace"
	trace_events 1 || die "could not enable the trace events"
	EDGE_ON="$(edge on)"
	[ -n "$EDGE_ON" ] || die "could not start tracing and read KVM's counters"
}

trace_take() {   # $1 tag: the window's end and tracing off; the raw trace as text, reduced into mmio-$1.json
	local off
	off="$(edge off)"
	[ -n "$off" ] || die "could not read KVM's counters and stop the trace after $1"
	trace_events 0 || die "could not disable the trace events after $1"
	set -- "$1" $EDGE_ON $off
	printf '{"t0_ns": %s, "t1_ns": %s, "clock": "realtime"}\n' "$2" "$5" > "$OUT/window-$1.json"
	printf '{"before": {"t_ns": %s, "qemu_pid": %s, "counters": {"mmio_exit_kernel": %s, "mmio_exit_user": %s}}, "after": {"t_ns": %s, "qemu_pid": %s, "counters": {"mmio_exit_kernel": %s, "mmio_exit_user": %s}}}\n' \
		"$2" "$VM_PID" "$3" "$4" "$5" "$VM_PID" "$6" "$7" > "$OUT/kvm-$1.json"
	tsu "cat '$TRACE/trace'" > "$OUT/trace-$1.txt" || die "could not read the trace of $1"
	python3 "$REDUCE" reduce < "$OUT/trace-$1.txt" > "$OUT/mmio-$1.json" \
		|| die "the trace of $1 was refused (see the message above) -- the run stops here"
}

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
	trace_restore
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

up_check() {   # $1 arm  $2 label: one untimed exchange (handshake included) on that arm's path
	local dest=()
	if [ "$1" = K ]; then
		dest=(--proto shmdb --shm "$IVSHMEM@$SLOT_K" --kick "$KICK_SOCK")
	else
		dest=(--proto shmbell --shm "$IVSHMEM@$SLOT_B")
	fi
	taskset -c "$CORE_PROBE" python3 "$PROBE" "${dest[@]}" --ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB" \
		--n 1 --warmup 0 --interval-ms 0 --timeout-s 3 --tag "check-$2" --out "$OUT/check-$2.json" \
		>> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 label
	local lab="$1" log="$OUT/console-$1.log" i args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	# The last guest's sockets: its server exits with QEMU, and the launcher
	# refuses to start over a socket it finds.
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK"
	BOOTED=1
	IFS_BIN="$IMG_B" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" THREAD_NAMES=1 \
		SMP="$SMP" MEM=1G TAP=tap-qnx MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG_B "*) ;; *) die "boot $lab: QEMU was not given $IMG_B" ;; esac
	pin_vm
	KVM_DIR="$(sudo -n sh -c "ls -d $KVM_DEBUGFS/${VM_PID}-*" 2>/dev/null)"
	[ -n "$KVM_DIR" ] && [ "$(printf '%s\n' "$KVM_DIR" | grep -c .)" = 1 ] \
		|| die "boot $lab: expected one $KVM_DEBUGFS/${VM_PID}-* directory, found '$KVM_DIR'"
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$SMP" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $SMP"
	for i in $(seq 1 40); do up_check B "$lab-B" && break; sleep 0.5; done
	up_check B "$lab-B" || die "boot $lab: no monitor answering on the MSI-X path (slot $SLOT_B)"
	up_check K "$lab-K" || die "boot $lab: no monitor answering on the console path (slot $SLOT_K)"
	grep -qaE 'shm configured: .*BAR0 0x[0-9a-fA-F]+ \([0-9]+ bytes\)' "$log" \
		&& grep -qaE 'its: msixcfg: .*BAR1 0x[0-9a-fA-F]+ \([0-9]+ B\)' "$log" \
		|| die "boot $lab: the console gives no readable BAR0 or BAR1 line -- the run stops here (M3)"
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG_B") smp=$SMP qemu_pid=$VM_PID" >> "$OUT/boots.log"
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

run_arm() {   # $1 arm  $2 round: one trace window around the arm
	local a="$1" r="$2" idle_s
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	# KVM's counters are read at the trace window's edges (trace_start, trace_take), not by
	# m_probe: see edge().
	trace_start
	case "$a" in
		K) KVM_STATS=0 m_probe "$OUT" "K_r$r" "$IVSHMEM@$SLOT_K" "$KICK_SOCK" "" shmdb "$IVSHMEM_SERVER" ;;
		B) KVM_STATS=0 m_probe "$OUT" "B_r$r" "$IVSHMEM@$SLOT_B" "-" "" shmbell "$IVSHMEM_SERVER" ;;
		I) idle_s="$(awk -v n="$N" -v w="$WARMUP" -v i="$INTERVAL_MS" 'BEGIN {printf "%.3f", (n + w) * i / 1000}')"
		   sleep "$idle_s" ;;
	esac
	trace_take "${a}_r$r"
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
m_require_balanced_k "$K" "${#MODES[@]}"
for f in "$PROBE" "$REPORT" "$REDUCE" "$LAUNCH" "$IMG_B" "$DISK" "$here/shmchan.c"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_B$DISK$IVSHMEM$IVSHMEM_SERVER$KICK_SOCK" in *" "*|*,*) die "no spaces or commas in the image, disk or socket paths" ;; esac
grep -q 'shmchan_bell_roundtrip' "$here/shmchan.c" || die "$here/shmchan.c has no shmchan_bell_roundtrip"
grep -q '"shmbell"' "$PROBE" || die "$PROBE has no shmbell transport"
for e in $TEVENTS; do tsu "test -w '$TRACE/events/$e/enable'" || die "no writable $e event under $TRACE"; done
[ "$(tsu "cat '$TRACE/current_tracer'")" = nop ] || die "$TRACE/current_tracer is not nop -- someone else is tracing"
for e in $TEVENTS; do
	[ "$(tsu "cat '$TRACE/events/$e/enable'")" = 0 ] || die "$e is already enabled -- someone else is tracing"
	[ "$(tsu "cat '$TRACE/events/$e/filter'")" = none ] || die "$e has a filter set -- it could hide accesses"
done
[ "$(tsu "cat '$TRACE/options/overwrite'")" = 1 ] || die "$TRACE/options/overwrite is not 1: lost events would not show"
[ "$(tsu "cat '$TRACE/options/record-tgid'")" = 0 ] || die "$TRACE/options/record-tgid is on: the trace lines change shape"
[ -z "$(tsu "cat '$TRACE/set_event_pid' '$TRACE/set_event_notrace_pid' 2>/dev/null")" ] \
	|| die "a pid filter is set in $TRACE: it could hide the vCPU threads"
[ -z "$(tsu "cat '$TRACE/set_event'")" ] || die "other trace events are enabled in $TRACE -- someone else is tracing"
tsu "grep -qw mono '$TRACE/trace_clock'" || die "$TRACE has no mono trace clock"
TRACE_CLOCK_BEFORE="$(tsu "cat '$TRACE/trace_clock'" | sed -n 's/.*\[\(.*\)\].*/\1/p')"
[ -n "$TRACE_CLOCK_BEFORE" ] || die "cannot read the current trace clock"
CPUMASK="$(tsu "cat '$TRACE/tracing_cpumask'" | tr -d ',')"
NCPU="$(nproc --all)"
[ "$(( 16#$CPUMASK & ((1 << NCPU) - 1) ))" = "$(( (1 << NCPU) - 1 ))" ] \
	|| die "$TRACE/tracing_cpumask is $CPUMASK: not every one of the $NCPU CPUs is traced"
TRACE_ON_BEFORE="$(tsu "cat '$TRACE/tracing_on'")"
TRACE_BUF_RAW="$(tsu "cat '$TRACE/buffer_size_kb'")"
case "$TRACE_BUF_RAW" in
	*expanded:*) TRACE_BUF_KB_BEFORE="$(printf '%s' "$TRACE_BUF_RAW" | sed -n 's/.*expanded: *\([0-9][0-9]*\).*/\1/p')" ;;
	''|*[!0-9]*) die "$TRACE/buffer_size_kb reads '$TRACE_BUF_RAW' (per-CPU sizes differ?) -- it could not be restored" ;;
	*) TRACE_BUF_KB_BEFORE="$TRACE_BUF_RAW" ;;
esac
[ -n "$TRACE_BUF_KB_BEFORE" ] || die "cannot read $TRACE/buffer_size_kb ('$TRACE_BUF_RAW')"

m_prepare_out "${OUT:-}" "$HOME/mmio-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
: > "$OUT/check.log"
m_build_shmchan "$here/shmchan.c" "$COMMON" "$OUT/libshmchan.so"
m_governor_pin
m_cstate_apply
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo $TRACE_BUF_KB_RUN > buffer_size_kb && echo mono > trace_clock" \
	|| die "could not size the trace buffer or set the mono clock"

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "mmio"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"slots\": {\"K\": $SLOT_K, \"B\": $SLOT_B}" \
	'"protos": {"K": "shmdb", "B": "shmbell"}' \
	"\"image_sha256\": \"$(_sha "$IMG_B")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"reducer_sha256\": \"$(_sha "$REDUCE")\"" \
	"\"config\": \"ifs-bell.bin, -smp $SMP\"" \
	"\"smp\": $SMP" \
	"\"trace\": {\"events\": \"$TEVENTS\", \"clock\": \"mono (was $TRACE_CLOCK_BEFORE, restored after)\", \"cpumask\": \"$CPUMASK\", \"buffer_kb_per_cpu\": $TRACE_BUF_KB_RUN, \"buffer_kb_before\": $TRACE_BUF_KB_BEFORE, \"buffer_before_raw\": \"$TRACE_BUF_RAW\"}" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; per boot K, B and I in a Williams order over them (period 6); see order.log"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${MODES[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one -smp $SMP boot per round, K, B and I per boot, each in a trace window -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/order.log"
for r in $(seq 1 "$K"); do
	arms=()
	for i in $(m_williams_row "$r" "${#MODES[@]}"); do arms+=("${MODES[$i]}"); done
	boot_vm "A_r$r"
	for a in "${arms[@]}"; do run_arm "$a" "$r"; done
	stop_vm || die "the guest of round $r would not stop"
	echo "round $r order: ${arms[*]}" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" K B
say "summary"
m_summary "$OUT" K K B
say "where the two ways in trap, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
