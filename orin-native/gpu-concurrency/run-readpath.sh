#!/usr/bin/env bash
# run-readpath.sh -- where one guest read() goes: the read-count test's ~16 us, traced, on two
# vCPUs against one. Phase 3b / A6, 2026-09-26; follows 20260926T-a6-orin-reads.
# The owner asked for this run (2026-09-26).
#
# WHAT IS KNOWN. One extra socket read() in the guest costs the round trip +16.2 us (64 B read
# as 32 + 32 against 64 in one), natively +1.2 us (the reads record). The second read() finds
# its data already there, so its cost is the call: in QNX a message to io-sock and its reply.
# The block-path record found that a 2 ms exchange wakes a blocked vCPU three times (QEMU wakes
# vCPU 0 for the interrupt, then the guest wakes its other vCPU twice), ~8.3 us each, and the
# SMP record that one vCPU removes the guest's two.
#
# THE INTERVENTION AND THE TRACE. ifs-reads.bin, booted with two vCPUs (the A6 default) and
# with one (-smp 1), halt_poll_ns at its default 500000 throughout. Per boot two arms, both
# 64-byte frames at 2 ms spacing: d64 on :7120 (one read per frame) and s64 on :7122 (two).
# Tags: 2d64 2s64 1d64 1s64. run-blockpath.sh's trace (blockpath_trace.py, the same events and
# segments as the SMP record) is on for every arm alike; it costs ~9-11 us per exchange, the
# same in every arm. Two boots per round in a Williams order over the two configurations
# (period 2); the arms in the same order for both boots of a round, alternating by round.
# n=500, 100 warm-up (the SMP record's, for the trace), K=12. About 16 min.
#
# THE RULE, fixed here before any run (readpath_report.py applies it). Per arm and round: the
# probe's p50, and from the trace the median over exchanges of the blocked halts inside
# [I, TX] (blockpath_trace.segments). Differences are paired within the round; per difference
# the median over rounds, with the distribution-free interval of widest coverage >= 95%
# (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the extra read() hands work to the guest's other vCPU and back
# (io-sock serves it there), so it costs two more blocked-vCPU wake-ups; with one vCPU there is
# no other vCPU to wake.
#   P1 (the trace, two vCPUs) 2s64 has 2 more blocked halts in [I, TX] than 2d64: the median
#      over rounds of the per-round difference of medians is >= 2. REFUTED if it is 0; 1 is
#      PARTIAL.
#   P2 (one vCPU) the extra read is cheap: 1s64 - 1d64, round trip, <= +5 us. REFUTED if
#      >= +10 us; between is PARTIAL.
#   P3 (two vCPUs, replication) 2s64 - 2d64, round trip, >= +10 us.
#   P4 (the trace, one vCPU) 1s64 and 1d64 have the same blocked halts in [I, TX]: the median
#      over rounds of the difference is 0.
# Not predicted, reported: 2d64's own blocked-halt count, the segments A B C D per arm, the
# wake-up and load latencies, 1d64 - 2d64.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 the read counts are the design's: reads per frame within 0.02 of 1 (d64) and 2 (s64),
#      every arm and round, from the guest's own count on its console
#   M2 the trace segmented >= 90% of every arm's requests
#   M3 every arm has K rounds of n samples, none rejected, none bad
# A VM whose threads named "CPU n/KVM" do not number its -smp is refused at boot.
#
# What this does NOT test: which guest thread runs where (the trace sees vCPUs, not QNX
# threads); a write() or any other call; any spacing but 2 ms; halt polling on (the SMP record
# did that for the monitor's path); the tail.
#
# NEEDS: no QEMU running; IFS_BIN (ifs-reads.bin) and DISK. c7 OFF (CSTATE=shallow, set before
# the library). NO LOAD. K a multiple of 2.
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
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/readpath_report.py}"
BPT="${BPT:-$here/blockpath_trace.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IFS_BIN="${IFS_BIN:?set IFS_BIN to ifs-reads.bin}"
DISK="${DISK:?set DISK to the guest disk}"
SETTLE_S="${SETTLE_S:-3}"       # after the guest answers, before its first arm
HP_PARAM="${HP_PARAM:-/sys/module/kvm/parameters/halt_poll_ns}"
CFGS=(2 1)
MODES=(d64 s64)
declare -A PORT=([d64]=7120 [s64]=7122)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1                     # the VM's halt counters per arm, as the SMP record
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(2d64 2s64 1d64 1s64)
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

trace_start() {   # filters for this boot's threads, then an empty buffer, then every event on
	local pid p="" q=""
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

stop_vm() {   # stop the VM this harness booted, syncing first; true once it is gone
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
	trace_restore
	m_sampler_stop; m_cstate_restore; m_governor_restore
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

# Only an endpoint of sweep.c echoes a 2048-byte frame whole (the guest's banners interleave on
# its console, as the sweep found).
echo_check() {   # $1 port  $2 label
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$GUEST" --port "$1" --n 3 --warmup 0 --interval-ms 0 \
		--timeout-s 3 --frame-bytes 2048 --tag "check-$2" --out "$OUT/check-$2.json" >> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 config (vCPUs)  $2 label
	local c="$1" lab="$2" log="$OUT/console-$2.log" i t0 t1 args
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	[ "$(cat "$HP_PARAM")" = 500000 ] || die "$HP_PARAM reads $(cat "$HP_PARAM"), not 500000, before boot $lab"
	BOOTED=1
	t0="$(date +%s%N)"
	IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP="$c" MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IFS_BIN "*) ;; *) die "boot $lab: QEMU was not given $IFS_BIN" ;; esac
	case "$args" in *"file=$DISK,"*) ;; *) die "boot $lab: QEMU was not given $DISK" ;; esac
	pin_vm
	local t cm v0="" v1="" nv=0
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU 0/KVM") v0="$t" ;; "CPU 1/KVM") v1="$t" ;; esac
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$c" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $c"
	if [ "$c" = 1 ]; then
		[ -n "$v0" ] || die "boot $lab: no thread named CPU 0/KVM"
		VMAP="m:$VM_PID,v0:$v0"
	else
		[ -n "$v0" ] && [ -n "$v1" ] || die "boot $lab: no threads named CPU 0/KVM and CPU 1/KVM"
		VMAP="m:$VM_PID,v0:$v0,v1:$v1"
	fi
	for i in $(seq 1 40); do echo_check 7120 "$lab-7120" && break; sleep 0.5; done
	echo_check 7120 "$lab-7120" || die "boot $lab: no sweep endpoint echoing on :7120"
	echo_check 7122 "$lab-7122" || die "boot $lab: no sweep endpoint echoing on :7122"
	t1="$(date +%s%N)"
	sleep "$SETTLE_S"
	echo "$lab smp=$c halt_poll_ns=$(cat "$HP_PARAM") qemu_pid=$VM_PID roles=$VMAP boot_ms=$(( (t1 - t0) / 1000000 ))" >> "$OUT/boots.log"
}

gpu_idle_around() {   # $1 round  $2 arm
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^r$1 $2 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $2 in round $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $2 in round $1 -- a GPU load ran beside this no-load run"
}

run_arm() {   # $1 config  $2 mode  $3 round
	local a="$1$2" r="$3"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	trace_start
	PROBE_FRAME_BYTES=64 m_probe "$OUT" "$a"_r"$r" "$GUEST" "${PORT[$2]}"
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
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
m_require_balanced_k "$K" "${#CFGS[@]}"
for f in "$PROBE" "$REPORT" "$BPT" "$LAUNCH" "$IFS_BIN" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IFS_BIN$DISK" in *" "*) die "IFS_BIN and DISK may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes"
[ -r "$HP_PARAM" ] || die "no $HP_PARAM on this host"
HP_BEFORE="$(cat "$HP_PARAM")"
[ "$HP_BEFORE" = 500000 ] || die "$HP_PARAM reads $HP_BEFORE, not the default 500000 -- a killed run may have left it"
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

m_prepare_out "${OUT:-}" "$HOME/readpath-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock" || die "could not set the trace clock to mono"

boot_vm 2 preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "readpath"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"d64": 7120, "s64": 7122}' \
	'"smp_by_config": {"2": 2, "1": 1}' \
	"\"halt_poll_ns\": \"$HP_BEFORE\"" \
	'"boots": "two per round, a Williams order over the two configurations (period 2); both arms per boot, in the same order for both boots of a round, alternating by round; see boots.log"' \
	"\"settle_s\": $SETTLE_S" \
	"\"trace\": \"net_dev_xmit and netif_receive_skb on tap-qnx, kvm_irq_line, kvm_vcpu_wakeup, sched_waking and sched_switch on QEMU's main and vCPU threads; mono clock; reduced on the board by blockpath_trace.py (sha256 $(_sha "$BPT"))\"" \
	"\"trace_buffer_kb\": \"$TRACE_BUF_KB\"" \
	"\"trace_clock\": \"mono for the run (was $TRACE_CLOCK_BEFORE, restored after)\"" \
	'"thread_names": "THREAD_NAMES=1 (-name qnx,debug-threads=on)"' \
	'"kvm_stats": 1' \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame, 64 bytes, length 64 in payload[46..47]; every byte checked"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, boots -smp 2 and 1, arms d64 (one read) and s64 (two) -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#CFGS[@]}"); do order+=("${CFGS[$i]}"); done
	if [ $(( r % 2 )) -eq 0 ]; then modes=(d64 s64); else modes=(s64 d64); fi
	line="round $r order:"
	for c in "${order[@]}"; do
		boot_vm "$c" "smp${c}_r$r"
		for m in "${modes[@]}"; do run_arm "$c" "$m" "$r"; line="$line $c$m"; done
		stop_vm || die "the guest of smp${c}_r$r would not stop"
	done
	echo "$line" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" 2d64 "${ARMS[@]}"
say "the read's cost and its wake-ups, by the rule above"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
