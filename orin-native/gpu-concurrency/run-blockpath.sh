#!/usr/bin/env bash
# run-blockpath.sh -- where the blocked halt's 32-43 us go: the host-side path of
# one exchange, traced and cut into segments, for VMs that block and VMs that
# poll. Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-haltpoll.
#
# WHAT IS KNOWN. The halt_poll_ns intervention showed that a vCPU which blocks
# in a halt, instead of polling, costs the p50 32-36 us at 2 ms spacing and
# 42-43 us at 0.2 ms, and costs the monitor's own span about 7 ticks. It did not
# say where in the path those microseconds go.
#
# THIS IS A DECOMPOSITION, NOT A TEST. No prediction is registered. Before this
# harness was written, one calibration trace of about 25 exchanges was taken on an
# unpinned guest, to learn the event formats. That trace was read, and it showed
# one exchange's sequence: the request into the tap, QEMU raising the interrupt,
# the blocked vCPU woken and scheduled in, that vCPU waking the other one, and
# the transmit notify back to QEMU. So nothing here is blind.
#
# THE DESIGN is run-haltpoll.sh's: every round boots three VMs (halt_poll_ns 0,
# 500000, 5000000), in a Williams order, each timed at both spacings with the same
# spacing order for every boot of the round. The six arms again: N200us N2ms
# D200us D2ms B200us B2ms. The contrasts that matter, both at one spacing:
#   D2ms - B2ms      blocked against polled at 2 ms
#   N200us - D200us  blocked against polled at 0.2 ms
# Two things differ from the halt-poll run. QEMU names its threads (THREAD_NAMES=1),
# so the trace can tell QEMU's main thread from each vCPU. And N=500 with
# WARMUP=100, to keep each arm's trace inside the ring buffer.
#
# THE TRACE, on for every arm alike (mono clock, restored after):
#   net_dev_xmit and netif_receive_skb, filtered to tap-qnx (the frame into and
#   out of the guest); kvm_irq_line; kvm_vcpu_wakeup (every halt's end, blocked or
#   polled); sched_waking and sched_switch, filtered to QEMU's main thread and its
#   two vCPU threads.
# It is reduced on the board by blockpath_trace.py to "seconds core event fields"
# lines, so no other process's name or pid leaves the board. Each exchange is then
# cut into four segments (A: the host and QEMU take the request in; B: the vCPU
# comes out of its halt; C: the guest's work up to its transmit notify; D: QEMU
# hands the reply back). blockpath_trace.py says exactly how. Lost events stop
# the run.
#
# THE CHECK THAT MAKES IT A DECOMPOSITION. If the four segments are the path, the
# blocked-minus-polled difference in their sum should account for the
# blocked-minus-polled difference in the round trip. blockpath_report.py prints
# that share. The untraced remainder (the probe's send and receive through the
# host stack) should not change.
#
# THE TRACE COSTS TIME. Each traced event adds to the path, and a blocked exchange
# has more events than a polled one. So the round trips here are not the
# halt-poll run's, and a difference measured with tracing on is not claimed as
# the untraced one. The event count per exchange is reported beside it.
#
# NEEDS: no QEMU running; IFS_BIN (ifs-stamp.bin) and DISK. c7 is OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN. K a
# multiple of 6.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
D_PORT="${D_PORT:-7103}"
N="${N:-500}"
K="${K:-12}"
WARMUP="${WARMUP:-100}"
INTERVAL_MS=2                   # the preflight's; every arm sets its own
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/blockpath_report.py}"
BPT="${BPT:-$here/blockpath_trace.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IFS_BIN="${IFS_BIN:?set IFS_BIN to ifs-stamp.bin}"
DISK="${DISK:?set DISK to the guest disk}"
SETTLE_S="${SETTLE_S:-3}"       # after the guest answers, before its first arm
HP_PARAM="${HP_PARAM:-/sys/module/kvm/parameters/halt_poll_ns}"
CFGS=(N D B)
declare -A HP=([N]=0 [D]=500000 [B]=5000000)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: a 0.2 ms arm is shorter than tegrastats' first line
KVM_STATS=1                     # the halt counters, as in the halt-poll run
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(N200us N2ms D200us D2ms B200us B2ms)
STAMP_ARMS="${ARMS[*]}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
HP_BEFORE=""; VM_PID=""; BOOTED=0
VMAP=""; TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_TOUCHED=0
TEVENTS="net/net_dev_xmit net/netif_receive_skb kvm/kvm_irq_line kvm/kvm_vcpu_wakeup sched/sched_waking sched/sched_switch"

tsu() {   # $1 = a shell command, run as root on the aux core
	taskset -c "$CORE_AUX" sudo -n sh -c "$1"
}

trace_events() {   # $1 = 0 or 1: every event off (and its filter cleared) or on
	local e cmd="cd '$TRACE'"
	for e in $TEVENTS; do
		if [ "$1" = 0 ]; then cmd="$cmd && echo 0 > events/$e/enable && echo 0 > events/$e/filter"
		else cmd="$cmd && echo 1 > events/$e/enable"; fi
	done
	tsu "$cmd"
}

trace_restore() {   # leave tracing as the preflight found it
	[ "$TRACE_TOUCHED" = 1 ] || return 0
	tsu "cd '$TRACE' && echo 0 > tracing_on" 2>/dev/null
	trace_events 0 2>/dev/null
	tsu "cd '$TRACE' && echo ${TRACE_CLOCK_BEFORE:-local} > trace_clock && echo > trace && echo ${TRACE_ON_BEFORE:-1} > tracing_on" 2>/dev/null \
		|| echo "WARNING: could not restore $TRACE -- events or the trace clock may be left changed" >&2
}

# Filters for this boot's threads, then an empty buffer, then every event on.
trace_start() {
	local m v0 v1 p q
	m="$(echo "$VMAP" | tr ',' '\n' | sed -n 's/^m://p')"
	v0="$(echo "$VMAP" | tr ',' '\n' | sed -n 's/^v0://p')"
	v1="$(echo "$VMAP" | tr ',' '\n' | sed -n 's/^v1://p')"
	p="pid == $m || pid == $v0 || pid == $v1"
	q="next_pid == $m || next_pid == $v0 || next_pid == $v1"
	TRACE_TOUCHED=1
	tsu "cd '$TRACE' && echo 0 > tracing_on && echo > trace && echo 'name == \"tap-qnx\"' > events/net/net_dev_xmit/filter && echo 'name == \"tap-qnx\"' > events/net/netif_receive_skb/filter && echo '$p' > events/sched/sched_waking/filter && echo '$q' > events/sched/sched_switch/filter" \
		|| die "could not set the trace filters"
	trace_events 1 || die "could not enable the trace events"
	tsu "cd '$TRACE' && echo 1 > tracing_on" || die "could not start tracing"
}

trace_take() {   # $1 tag: stop, reduce on this host into bp-$1.log, everything off
	tsu "cd '$TRACE' && echo 0 > tracing_on" || die "could not stop the trace after $1"
	tsu "cat '$TRACE/trace'" | python3 "$BPT" reduce --map "$VMAP" > "$OUT/bp-$1.log" \
		|| die "the trace of $1 was refused (see the message above) -- the run stops here"
	trace_events 0 || die "could not disable the trace events after $1"
}

set_hp() {   # $1 value: write it, and read it back
	echo "$1" | sudo -n tee "$HP_PARAM" > /dev/null || die "could not write $HP_PARAM"
	[ "$(cat "$HP_PARAM")" = "$1" ] || die "$HP_PARAM reads back '$(cat "$HP_PARAM")', not $1"
}

stop_vm() {   # stop the VM this harness booted; true once it is gone
	local i
	[ -n "$VM_PID" ] || return 0
	kill -TERM "$VM_PID" 2>/dev/null
	for i in $(seq 1 30); do [ -d "/proc/$VM_PID" ] || break; sleep 0.5; done
	if [ -d "/proc/$VM_PID" ]; then
		kill -KILL "$VM_PID" 2>/dev/null; sleep 1
	fi
	[ -d "/proc/$VM_PID" ] && return 1
	VM_PID=""
	return 0
}

cleanup() {
	say "cleanup"
	# The preflight refused a running QEMU, so once this harness has booted one,
	# every QEMU is its own -- including one whose pid it had not yet read, or a
	# second one (FOUND BY REVIEW: VM_PID could hold two pids, which stop_vm
	# would have reported as stopped).
	if [ "$BOOTED" = 1 ]; then
		for VM_PID in $(m_pids_of qemu-system-aarch64); do
			stop_vm || echo "WARNING: the guest QEMU $VM_PID would not stop" >&2
		done
	fi
	VM_PID=""
	if [ -n "$HP_BEFORE" ]; then
		echo "$HP_BEFORE" | sudo -n tee "$HP_PARAM" > /dev/null 2>&1 \
			&& [ "$(cat "$HP_PARAM")" = "$HP_BEFORE" ] && say "halt_poll_ns restored to $HP_BEFORE" \
			|| echo "WARNING: could not restore $HP_PARAM to $HP_BEFORE" >&2
	fi
	trace_restore
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

# Every QEMU thread on QEMU_CORES, read back per thread. m_pin_qemu does this AND
# hashes the image and disk; that is done once, at the preflight boot, and every
# later boot is checked to have been given the same two paths.
pin_vm() {
	local t got
	for t in $(ls "/proc/$VM_PID/task"); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1 || [ ! -d "/proc/$VM_PID/task/$t" ] \
			|| die "taskset failed on QEMU thread $t"
		got="$(awk '/^Cpus_allowed_list:/ {print $2}' "/proc/$VM_PID/task/$t/status" 2>/dev/null)"
		[ -z "$got" ] || [ "$(_cpuset "$got")" = "$(_cpuset "$QEMU_CORES")" ] \
			|| die "QEMU thread $t reads back '$got', asked for '$QEMU_CORES'"
	done
}

boot_vm() {   # $1 config  $2 label: boot a VM with that config's halt_poll_ns
	local c="$1" lab="$2" log="$OUT/console-$2.log" i t0 t1 args
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	set_hp "${HP[$c]}"
	BOOTED=1
	t0="$(date +%s%N)"
	# The VM's shape is given, not inherited: an exported IVSHMEM, KICK_SOCK,
	# THREAD_NAMES, SMP, MEM or TAP would otherwise change it silently. And QEMU
	# must not inherit fd 9: a QEMU that outlived the run would hold the lock.
	IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP=2 MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	for i in $(seq 1 40); do
		tr -d '\0\r' < "$log" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" && break
		sleep 0.5
	done
	tr -d '\0\r' < "$log" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
		|| die "boot $lab: no stamping monitor on :$D_PORT in $log -- is IFS_BIN ifs-stamp.bin?"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IFS_BIN "*) ;; *) die "boot $lab: QEMU was not given $IFS_BIN" ;; esac
	case "$args" in *"file=$DISK,"*) ;; *) die "boot $lab: QEMU was not given $DISK" ;; esac
	pin_vm
	# The roles the trace needs: QEMU's main thread and the vCPUs, by the names
	# THREAD_NAMES=1 gives them.
	local t c v0="" v1=""
	for t in $(ls "/proc/$VM_PID/task"); do
		c="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$c" in "CPU 0/KVM") v0="$t" ;; "CPU 1/KVM") v1="$t" ;; esac
	done
	[ -n "$v0" ] && [ -n "$v1" ] || die "boot $lab: no threads named CPU 0/KVM and CPU 1/KVM"
	VMAP="m:$VM_PID,v0:$v0,v1:$v1"
	m_reachable "$GUEST" "$D_PORT" "boot $lab's stamping monitor" > /dev/null
	t1="$(date +%s%N)"
	sleep "$SETTLE_S"
	echo "$lab halt_poll_ns=$(cat "$HP_PARAM") qemu_pid=$VM_PID roles=$VMAP boot_ms=$(( (t1 - t0) / 1000000 ))" >> "$OUT/boots.log"
}

spacing_ms() {   # $1 arm -> the probe's --interval-ms
	case "${1:1}" in
		200us) echo 0.2 ;; 2ms) echo 2 ;;
		*) die "no spacing for arm $1" ;;
	esac
}

# The GR3D readings m_thermal took just before and after an arm must both read 0%.
gpu_idle_around() {   # $1 round  $2 arm
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^r$1 $2 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $2 in round $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $2 in round $1 -- a GPU load ran beside this no-load run"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	trace_start
	INTERVAL_MS="$(spacing_ms "$a")" PROBE_STAMPS=1 m_probe "$OUT" "$a"_r"$r" "$GUEST" "$D_PORT"
	trace_take "$a"_r"$r"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" "$a"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of qemu-system-aarch64)" ] \
	|| die "a QEMU is already running: this harness boots its own guests. Stop it first."
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm (no window sampler: windows are shorter than tegrastats interval)"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight; no window sampler"
fi
m_require_balanced_k "$K" "${#CFGS[@]}"
for f in "$PROBE" "$REPORT" "$BPT" "$LAUNCH" "$IFS_BIN" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IFS_BIN$DISK" in *" "*) die "IFS_BIN and DISK may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
[ -r "$HP_PARAM" ] || die "no $HP_PARAM on this host"
HP_BEFORE="$(cat "$HP_PARAM")"
# D is 500000 because that is the value every A6 record ran with. Anything else
# is most likely left behind by a run that was killed before its cleanup, and
# "restoring" it at the end would carry it into every later harness.
[ "$HP_BEFORE" = 500000 ] \
	|| die "$HP_PARAM reads $HP_BEFORE, not the default 500000 -- a killed run may have left it; restore it first"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"
[ -n "$TIMER" ] || die "no arch_timer frequency in dmesg -- the monitor's ticks could not be counted"
for e in $TEVENTS; do tsu "test -w '$TRACE/events/$e/enable'" || die "no writable $e event under $TRACE"; done
[ "$(tsu "cat '$TRACE/current_tracer'")" = nop ] || die "$TRACE/current_tracer is not nop -- someone else is tracing"
for e in $TEVENTS; do
	[ "$(tsu "cat '$TRACE/events/$e/enable'")" = 0 ] || die "$e is already enabled -- someone else is tracing"
done
[ "$(tsu "cat '$TRACE/options/overwrite'")" = 1 ] || die "$TRACE/options/overwrite is not 1: lost events would not show"
[ "$(tsu "cat '$TRACE/options/record-tgid'")" = 0 ] || die "$TRACE/options/record-tgid is on: the trace lines change shape"
[ -z "$(tsu "cat '$TRACE/set_event_pid' '$TRACE/set_event_notrace_pid' 2>/dev/null")" ] \
	|| die "a pid filter is set in $TRACE: it could hide the threads"
tsu "grep -qw mono '$TRACE/trace_clock'" || die "$TRACE has no mono trace clock"
TRACE_ON_BEFORE="$(tsu "cat '$TRACE/tracing_on'")"
TRACE_CLOCK_BEFORE="$(tsu "cat '$TRACE/trace_clock'" | sed -n 's/.*\[\(.*\)\].*/\1/p')"
[ -n "$TRACE_CLOCK_BEFORE" ] || die "cannot read the current trace clock"
TRACE_BUF_KB="$(tsu "cat '$TRACE/buffer_size_kb'" | tr -d '()' | sed 's/  */ /g')"
HALT_POLL=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALT_POLL="$HALT_POLL\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo unread)\", "
done
HALT_POLL="{${HALT_POLL%, }}"

m_prepare_out "${OUT:-}" "$HOME/blockpath-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock" || die "could not set the trace clock to mono"

# One preflight boot, at D: it proves the boot path, and m_pin_qemu identifies
# (hashes) the image and disk for the stamp. Stopped before round 1.
boot_vm D preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS='"per arm: see spacings_ms"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "blockpath"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	'"halt_poll_ns_by_config": {"N": 0, "D": 500000, "B": 5000000}' \
	"\"halt_poll_ns_found\": \"$HP_BEFORE\"" \
	"\"kvm_halt_poll_at_preflight\": $HALT_POLL" \
	'"spacings_ms": {"200us": 0.2, "2ms": 2}' \
	'"boots": "three per round, a Williams order over N D B (period 6); both spacings per boot, in the same order for every boot of a round, alternating by round; see boots.log"' \
	"\"settle_s\": $SETTLE_S" \
	"\"trace\": \"net_dev_xmit and netif_receive_skb on tap-qnx, kvm_irq_line, kvm_vcpu_wakeup, sched_waking and sched_switch on QEMU's main and vCPU threads; mono clock; reduced on the board by blockpath_trace.py (sha256 $(_sha "$BPT"))\"" \
	"\"trace_buffer_kb\": \"$TRACE_BUF_KB\"" \
	"\"trace_clock\": \"mono for the run (was $TRACE_CLOCK_BEFORE, restored after)\"" \
	'"thread_names": "THREAD_NAMES=1 (-name qnx,debug-threads=on)"' \
	'"kvm_stats": 1' \
	"\"counter\": \"$TIMER\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, boots N D B (halt_poll_ns 0 500000 5000000) x spacings 200us 2ms -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#CFGS[@]}"); do order+=("${CFGS[$i]}"); done
	line="round $r order:"
	for ci in "${!order[@]}"; do
		c="${order[$ci]}"
		# The same spacing order for every boot in the round, alternating across
		# rounds: each configuration gets each order in half the rounds, and every
		# pair across boots is matched by position (FOUND BY REVIEW; see the header).
		if [ $(( r % 2 )) -eq 0 ]; then sp=(200us 2ms); else sp=(2ms 200us); fi
		boot_vm "$c" "${c}_r$r"
		for s in "${sp[@]}"; do run_arm "$c$s" "$r"; line="$line $c$s"; done
		stop_vm || die "the guest of ${c}_r$r would not stop"
	done
	echo "$line" >> "$OUT/order.log"
	say "round $r/$K done"
done

set_hp "$HP_BEFORE"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" D2ms "${ARMS[@]}"
say "round trip, paired within round"
m_pairs "$OUT" D2ms:B2ms N200us:D200us
say "the segments per arm, and blocked against polled at each spacing"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
