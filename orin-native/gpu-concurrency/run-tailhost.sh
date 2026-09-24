#!/usr/bin/env bash
# run-tailhost.sh -- is the tail the host's own work? The tail decomposition run
# again, with a second trace of what the host itself runs on QEMU's cores, charged
# exchange by exchange. Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-tailpath.
#
# WHAT IS KNOWN. In the tail (the slowest 1% at 2 ms spacing, the A6 default) the
# guest's work and QEMU's receive and transmit processing all run slower at once,
# and the scheduling waits barely move (20260924T-a6-orin-tailpath). QEMU's main
# thread is never switched in more often in a tail exchange than in any other (2.00
# switch-ins per exchange in both), so it is not preempted and resumed. Moving
# every device interrupt off QEMU's cores changed nothing (20260924T-a6-orin-tail).
#
# WHERE THE PREDICTION COMES FROM. Exploratory, and stated so it is not mistaken for
# a blind test:
#   - in the tailpath record's own data the tail exchanges are phase-locked at
#     32 ms (R 0.456 against a random-subset p99 of 0.118) and at 16 ms, and they
#     cluster: 79 of 264 are followed by another tail exchange, where ~3 would be
#     by chance;
#   - a 10 s trace of the idle host in the same boot put the timer wheel's batched
#     callbacks (delayed_work_timer_fn), the function-call IPIs and vmstat's work
#     at 29-31 ms of the same 32 ms phase; the tail sat at 30.8 ms.
# At HZ=250 the timer wheel's second level has a granularity of 8 jiffies, 32 ms:
# every timer set 256 ms to 2 s ahead fires at a jiffy that is a multiple of 8, in
# one batch, and the work it queues follows. So P1 is a replication on new data,
# and P2 and P3 are new.
#
# THE RUN. One boot of the stamping guest, launched with THREAD_NAMES=1, and one
# arm repeated: t2ms, the A6 default (two vCPUs, halt_poll_ns 500000, 2 ms), with
# run-tailpath.sh's trace unchanged in the top-level buffer, and a second ftrace
# instance on QEMU's cores only (tracing_cpumask) with the host's own activity:
# interrupt, softirq and IPI handlers (entry and exit), every sched_switch, and
# every timer_list callback with its jiffy (hostact_trace.py). Alignment, the
# segments and the tail are run-tailpath.sh's: a request is a frame of the round's
# most common length, a round aligns when its trace holds exactly warmup + n
# requests, and a TAIL exchange is at or above its round's p99 round trip.
#
# THE RULE, fixed here before any run:
#   - an exchange's WINDOW is its T0 (request into the tap) to its reply out, the
#     traced span A..D;
#   - its CHARGE H is the host's handler time (interrupt, softirq, IPI) on any core
#     while one of QEMU's threads holds that core, plus the time QEMU's main thread
#     or a vCPU thread spent preempted (switched out runnable), inside the window;
#     time nested in another handler is counted once, as the inner one's (on
#     arm64 an IPI arrives inside an interrupt named IPI) (hostact_trace.py);
#   - the EXCESS of a tail exchange is its value minus its round's median, for H,
#     for each class of H, and for the traced span.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: the tail is the host's timer-wheel
# batch: every 8 jiffies the kernel runs its batched timer callbacks and the work
# they raise, and where that lands on a core running one of QEMU's threads, the
# exchange in flight waits for it.
#   P1 the tail is phase-locked to the host's timers at 32 ms: the tail exchanges'
#      T0 have a Rayleigh R at 32 ms above the p99 of 1000 random subsets of the
#      timed exchanges of the same size (seed 1), and their mean phase is within
#      2 ms of the traced timer callbacks' mean phase. REFUTED if R is not above
#      the p99. PARTIAL if it is, but the phases are more than 2 ms apart.
#   P2 the host's charge is most of the tail: H's summed excess over the tail
#      exchanges is >= 50% of their summed traced-span excess. PARTIAL if 20-50%.
#      REFUTED if < 20% -- then the work runs slower for a reason that is not
#      host code on QEMU's cores (memory, caches or firmware).
#   P3 of H's summed excess, softirq time is the largest of the four classes (irq,
#      softirq, ipi, preempted). REFUTED if another class is larger. Not scored if
#      P2 is REFUTED.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 the trace and the probe align (exactly warmup + n requests) in >= 90% of
#      rounds; unaligned rounds are left out -> P1 P2 P3
#   M2 >= 95% of the aligned rounds' timed exchanges are segmented -> P1 P2 P3
#   M3 every aligned round has its host-activity trace -> P1 P2 P3
#   M4 >= 99% of segmented windows start after every traced core has a known
#      current task (a sched_switch seen on it) -> P2 P3
#   M5 the timer callbacks' own R at 32 ms is >= 0.1: the grid is there -> P1
# tailhost_report.py applies it, and scores only at k = 24.
#
# Both traces cost time on every exchange alike; the second one's cost is not
# measured here beyond the medians, which the record compares with tailpath's.
# Each ring buffer is set for the run and restored (the instance is removed);
# lost events in either stop the run.
#
# NEEDS: the guest running with THREAD_NAMES=1 (ifs-stamp.bin; CONSOLE its console
# log). c7 OFF (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS
# THE RUN.
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
N="${N:-1000}"
K="${K:-24}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
BPT="${BPT:-$here/blockpath_trace.py}"
HAT="${HAT:-$here/hostact_trace.py}"
REPORT="${REPORT:-$here/tailhost_report.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-4096}"
HACT_KB="${HACT_KB:-8192}"
INST="$TRACE/instances/tailhost"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(t2ms)
STAMP_ARMS="t2ms"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
TEVENTS="net/net_dev_xmit net/netif_receive_skb kvm/kvm_irq_line kvm/kvm_vcpu_wakeup sched/sched_waking sched/sched_switch"
HEVENTS="irq/irq_handler_entry irq/irq_handler_exit irq/softirq_entry irq/softirq_exit ipi/ipi_entry ipi/ipi_exit sched/sched_switch timer/timer_expire_entry"
VMAP=""; HMAP=""; TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_KB_BEFORE=""; TRACE_TOUCHED=0; INST_MADE=0

tsu() {   # $1 = a shell command, run as root on the aux core
	taskset -c "$CORE_AUX" sudo -n sh -c "$1"
}

trace_events() {   # $1 = 0 or 1
	local e cmd="cd '$TRACE'"
	for e in $TEVENTS; do
		if [ "$1" = 0 ]; then cmd="$cmd && echo 0 > events/$e/enable && echo 0 > events/$e/filter"
		else cmd="$cmd && echo 1 > events/$e/enable"; fi
	done
	tsu "$cmd"
}

trace_restore() {
	[ "$TRACE_TOUCHED" = 1 ] || return 0
	tsu "cd '$TRACE' && echo 0 > tracing_on" 2>/dev/null
	trace_events 0 2>/dev/null
	tsu "cd '$TRACE' && echo ${TRACE_CLOCK_BEFORE:-local} > trace_clock && echo ${TRACE_KB_BEFORE:-1408} > buffer_size_kb && echo > trace && echo ${TRACE_ON_BEFORE:-1} > tracing_on" 2>/dev/null \
		|| echo "WARNING: could not restore $TRACE -- events, clock or buffer size may be left changed" >&2
}

trace_start() {
	local pid p="" q=""
	for pid in $(echo "$VMAP" | tr ',' '\n' | cut -d: -f2); do
		p="${p:+$p || }pid == $pid"
		q="${q:+$q || }next_pid == $pid"
	done
	tsu "cd '$TRACE' && echo 0 > tracing_on && echo > trace && echo 'name == \"tap-qnx\"' > events/net/net_dev_xmit/filter && echo 'name == \"tap-qnx\"' > events/net/netif_receive_skb/filter && echo '$p' > events/sched/sched_waking/filter && echo '$q' > events/sched/sched_switch/filter" \
		|| die "could not set the trace filters"
	trace_events 1 || die "could not enable the trace events"
	tsu "cd '$TRACE' && echo 1 > tracing_on" || die "could not start tracing"
}

trace_take() {   # $1 tag
	tsu "cd '$TRACE' && echo 0 > tracing_on" || die "could not stop the trace after $1"
	tsu "cat '$TRACE/trace'" | python3 "$BPT" reduce --map "$VMAP" > "$OUT/bp-$1.log" \
		|| die "the trace of $1 was refused (see the message above) -- the run stops here"
	trace_events 0 || die "could not disable the trace events after $1"
}

cores_mask() {   # $1 core spec -> hex mask
	local c m=0
	for c in $(_cpuset "$1"); do m=$((m | (1 << c))); done
	printf '%x\n' "$m"
}

hact_events() {   # $1 = 0 or 1
	local e cmd="cd '$INST'"
	for e in $HEVENTS; do cmd="$cmd && echo $1 > events/$e/enable"; done
	tsu "$cmd"
}

hact_start() {
	tsu "cd '$INST' && echo 0 > tracing_on && echo > trace" || die "could not clear the host-activity trace"
	hact_events 1 || die "could not enable the host-activity events"
	tsu "cd '$INST' && echo 1 > tracing_on" || die "could not start the host-activity trace"
}

hact_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on" || die "could not stop the host-activity trace after $1"
	tsu "cat '$INST/trace'" | python3 "$HAT" reduce --map "$HMAP" > "$OUT/ha-$1.log" \
		|| die "the host-activity trace of $1 was refused (see the message above) -- the run stops here"
	hact_events 0 || die "could not disable the host-activity events after $1"
}

hact_remove() {
	[ "$INST_MADE" = 1 ] || return 0
	tsu "cd '$INST' && echo 0 > tracing_on" 2>/dev/null
	hact_events 0 2>/dev/null
	tsu "rmdir '$INST'" 2>/dev/null || { sleep 1; tsu "rmdir '$INST'" 2>/dev/null; } \
		|| echo "WARNING: could not remove the ftrace instance $INST" >&2
}

cleanup() {
	say "cleanup"
	hact_remove
	trace_restore
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

gpu_idle_around() {   # $1 round  $2 arm
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^r$1 $2 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $2 in round $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $2 in round $1 -- a GPU load ran beside this no-load run"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every round"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
for f in "$PROBE" "$BPT" "$HAT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
grep -q '"k": k' "$BPT" || die "$BPT does not index its exchanges: it predates run-tailpath.sh"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for e in $TEVENTS $HEVENTS; do tsu "test -w '$TRACE/events/$e/enable'" || die "no writable $e event under $TRACE"; done
tsu "test -d '$TRACE/instances' && test ! -e '$INST'" || die "no $TRACE/instances, or $INST exists -- someone else is tracing"
[ "$(tsu "cat '$TRACE/current_tracer'")" = nop ] || die "$TRACE/current_tracer is not nop -- someone else is tracing"
for e in $TEVENTS; do
	[ "$(tsu "cat '$TRACE/events/$e/enable'")" = 0 ] || die "$e is already enabled -- someone else is tracing"
done
[ "$(tsu "cat '$TRACE/options/overwrite'")" = 1 ] || die "$TRACE/options/overwrite is not 1: lost events would not show"
[ "$(tsu "cat '$TRACE/options/record-tgid'")" = 0 ] || die "$TRACE/options/record-tgid is on"
[ -z "$(tsu "cat '$TRACE/set_event_pid' '$TRACE/set_event_notrace_pid' 2>/dev/null")" ] || die "a pid filter is set in $TRACE"
tsu "grep -qw mono '$TRACE/trace_clock'" || die "$TRACE has no mono trace clock"
TRACE_ON_BEFORE="$(tsu "cat '$TRACE/tracing_on'")"
TRACE_CLOCK_BEFORE="$(tsu "cat '$TRACE/trace_clock'" | sed -n 's/.*\[\(.*\)\].*/\1/p')"
[ -n "$TRACE_CLOCK_BEFORE" ] || die "cannot read the current trace clock"
TRACE_KB_BEFORE="$(tsu "cat '$TRACE/buffer_size_kb'" | sed -n 's/.*expanded: \([0-9]*\).*/\1/p; s/^\([0-9][0-9]*\)$/\1/p' | head -1)"
[ -n "$TRACE_KB_BEFORE" ] || die "cannot read the trace buffer size"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"

m_prepare_out "${OUT:-}" "$HOME/tailhost-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
v0=""; v1=""
for t in $(ls "/proc/$QPID/task"); do
	case "$(cat "/proc/$QPID/task/$t/comm" 2>/dev/null)" in "CPU 0/KVM") v0="$t" ;; "CPU 1/KVM") v1="$t" ;; esac
done
[ -n "$v0" ] && [ -n "$v1" ] || die "no threads named CPU 0/KVM and CPU 1/KVM -- launch the guest with THREAD_NAMES=1"
VMAP="m:$QPID,v0:$v0,v1:$v1"
HMAP="$VMAP"
for t in $(ls "/proc/$QPID/task"); do
	case "$t" in "$QPID"|"$v0"|"$v1") ;; *) HMAP="$HMAP,q:$t" ;; esac
done
QMASK="$(cores_mask "$QEMU_CORES")"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"
tsu "mkdir '$INST'" || die "could not create the ftrace instance $INST"
INST_MADE=1
tsu "cd '$INST' && echo 0 > tracing_on && echo mono > trace_clock && echo $HACT_KB > buffer_size_kb && echo $QMASK > tracing_cpumask" \
	|| die "could not set up the ftrace instance $INST"
[ "$(tsu "cat '$INST/options/overwrite'")" = 1 ] || die "$INST/options/overwrite is not 1: lost events would not show"
tsu "grep -qF '[mono]' '$INST/trace_clock'" || die "the instance's trace clock is not mono"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "tailhost"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"vcpu_threads\": \"$VMAP\"" \
	"\"trace\": \"run-blockpath.sh's six events, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by blockpath_trace.py (sha256 $(_sha "$BPT"))\"" \
	"\"host_activity\": \"instance tailhost on cores $QEMU_CORES (mask $QMASK): $HEVENTS; mono clock, buffer $HACT_KB KB per core, reduced by hostact_trace.py (sha256 $(_sha "$HAT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, traced -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	echo "round $r order: t2ms" >> "$OUT/order.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	hact_start
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	trace_take "t2ms_r$r"
	hact_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "the tail, against the host's own work"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
