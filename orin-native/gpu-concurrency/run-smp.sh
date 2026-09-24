#!/usr/bin/env bash
# run-smp.sh -- remove the guest's two IPI wake-ups: the same image on one vCPU
# against two, blocked and polled, traced. Phase 3b / A6, 2026-09-24; follows
# 20260924T-a6-orin-blockpath and the literature pass behind its first suggestion.
#
# WHAT IS KNOWN. With two vCPUs, a blocked exchange at 2 ms wakes a blocked vCPU
# three times in 83-85% of exchanges: QEMU wakes vCPU 0 for the interrupt, then
# vCPU 0 wakes vCPU 1 twice (the guest's own IPIs). Each wake-up costs ~8.3 us.
# With polling (halt_poll_ns 5000000) none of them blocks, and the round trip is
# ~34 us shorter at 2 ms.
#
# THE INTERVENTION. The same image booted with one vCPU (-smp 1) has no other vCPU
# to hand work to. Before this harness was written, one boot with -smp 1 checked
# that the image boots and answers on :7103; nothing was timed. Four VM
# configurations per round, in a Williams order over them (period 4):
#   2D  two vCPUs, halt_poll_ns 500000   (the A6 default)
#   2B  two vCPUs, halt_poll_ns 5000000  (a 2 ms idle ends in a poll)
#   1D  one vCPU,  halt_poll_ns 500000
#   1B  one vCPU,  halt_poll_ns 5000000
# Each is timed at 0.2 and 2 ms, in the same spacing order for every boot of a
# round, alternating by round: eight arms, 2D200us 2D2ms 2B200us 2B2ms 1D200us
# 1D2ms 1B200us 1B2ms. run-blockpath.sh's trace is on for every arm alike; it
# costs ~9-11 us per exchange (the block-path record).
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: the two extra wake-ups are the guest
# handing work to its other vCPU, so with one vCPU they are gone.
#   P1 (the trace) 1D2ms: the median exchange has exactly 1 blocked halt inside
#      [I, TX] (2D2ms has 3). REFUTED if it has 2 or more.
#   P2 1D2ms - 2D2ms, round trip, paired within round: median <= -10 us.
#      REFUTED if >= -3 us. Between: PARTIAL.
#   P3 polling's benefit shrinks: (2D2ms - 2B2ms) - (1D2ms - 1B2ms), round trip,
#      paired within round: median >= +8 us. REFUTED if <= +2 us. Between: PARTIAL.
# NOT PREDICTED: 1B2ms - 2B2ms and the 0.2 ms arms (with polling, one vCPU doing
# all the work serially may cost as much as the handoff saves), and what is left
# of the guest's slower work after blocking.
# THE MANIPULATION CHECKS. A prediction resting on a failed one prints VOID:
#   M1 1D2ms: the first halt end after the interrupt is a blocked one in >= 90% of
#      exchanges, and 1B2ms: in <= 10% (the D and B regimes hold on one vCPU)
#      -> P1, P2, P3
#   M2 2D2ms: the median exchange has 3 blocked halts in [I, TX] (the two-vCPU
#      pattern replicated) -> P1, P3
# A VM whose threads named "CPU n/KVM" do not number its -smp is refused at boot.
# smp_report.py applies all of it, and only at k = 12.
#
# NEEDS: no QEMU running; IFS_BIN (ifs-stamp.bin) and DISK. c7 is OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN. K a
# multiple of 4.
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
REPORT="${REPORT:-$here/smp_report.py}"
BPT="${BPT:-$here/blockpath_trace.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IFS_BIN="${IFS_BIN:?set IFS_BIN to ifs-stamp.bin}"
DISK="${DISK:?set DISK to the guest disk}"
SETTLE_S="${SETTLE_S:-3}"       # after the guest answers, before its first arm
HP_PARAM="${HP_PARAM:-/sys/module/kvm/parameters/halt_poll_ns}"
CFGS=(2D 2B 1D 1B)
declare -A HP=([2D]=500000 [2B]=5000000 [1D]=500000 [1B]=5000000)
declare -A SMPC=([2D]=2 [2B]=2 [1D]=1 [1B]=1)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: a 0.2 ms arm is shorter than tegrastats' first line
KVM_STATS=1                     # the halt counters, as in the halt-poll run
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(2D200us 2D2ms 2B200us 2B2ms 1D200us 1D2ms 1B200us 1B2ms)
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
	local pid p="" q=""
	# Every thread in this boot's map: QEMU's main thread and one or two vCPUs.
	for pid in $(echo "$VMAP" | tr ',' '\n' | cut -d: -f2); do
		p="${p:+$p || }pid == $pid"
		q="${q:+$q || }next_pid == $pid"
	done
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
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP="${SMPC[$c]}" MEM=1G TAP=tap-qnx \
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
	# (cm, not c: c is this boot's configuration, read again below.)
	local t cm v0="" v1="" nv=0
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU 0/KVM") v0="$t" ;; "CPU 1/KVM") v1="$t" ;; esac
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "${SMPC[$c]}" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp ${SMPC[$c]}"
	if [ "${SMPC[$c]}" = 1 ]; then
		[ -n "$v0" ] || die "boot $lab: no thread named CPU 0/KVM"
		VMAP="m:$VM_PID,v0:$v0"
	else
		[ -n "$v0" ] && [ -n "$v1" ] || die "boot $lab: no threads named CPU 0/KVM and CPU 1/KVM"
		VMAP="m:$VM_PID,v0:$v0,v1:$v1"
	fi
	m_reachable "$GUEST" "$D_PORT" "boot $lab's stamping monitor" > /dev/null
	t1="$(date +%s%N)"
	sleep "$SETTLE_S"
	echo "$lab halt_poll_ns=$(cat "$HP_PARAM") qemu_pid=$VM_PID roles=$VMAP boot_ms=$(( (t1 - t0) / 1000000 ))" >> "$OUT/boots.log"
}

spacing_ms() {   # $1 arm -> the probe's --interval-ms
	case "${1:2}" in
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

m_prepare_out "${OUT:-}" "$HOME/smp-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock" || die "could not set the trace clock to mono"

# One preflight boot, at D: it proves the boot path, and m_pin_qemu identifies
# (hashes) the image and disk for the stamp. Stopped before round 1.
boot_vm 2D preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS='"per arm: see spacings_ms"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "smp"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	'"halt_poll_ns_by_config": {"2D": 500000, "2B": 5000000, "1D": 500000, "1B": 5000000}' \
	'"smp_by_config": {"2D": 2, "2B": 2, "1D": 1, "1B": 1}' \
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
say "k=$K rounds, n=$N, warmup=$WARMUP, boots 2D 2B 1D 1B (-smp 2/2/1/1, halt_poll_ns 500000/5000000/500000/5000000) x spacings 200us 2ms -> $OUT"
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
m_pairs "$OUT" 1D2ms:2D2ms 1B2ms:2B2ms 2D2ms:2B2ms 1D2ms:1B2ms 1D200us:2D200us 1B200us:2B200us
say "the segments per arm, and blocked against polled at each spacing"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
