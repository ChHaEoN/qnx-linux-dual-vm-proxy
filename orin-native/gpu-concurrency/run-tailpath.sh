#!/usr/bin/env bash
# run-tailpath.sh -- where the tail goes: every exchange of the A6 default traced
# and matched to its own round-trip sample, so the slowest ones can be taken apart.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-tail.
#
# WHAT IS KNOWN. At 2 ms spacing with the default halt-poll window, p50 is ~178 us
# and p99.9 ~280 us. The slowest 1% spend ~0.17% of their time in the monitor.
# Moving every device interrupt off QEMU's cores changed nothing; real-time
# priority for QEMU shaved 2-5 us from p50 to p99 and nothing at p99.9
# (20260924T-a6-orin-tail). The block-path trace cut the median exchange into
# four host-side segments; it never looked at the slow ones.
#
# THE RUN. One boot of the stamping guest, launched with THREAD_NAMES=1, and one
# arm repeated: t2ms, the A6 default (two vCPUs, halt_poll_ns 500000, 2 ms), with
# run-blockpath.sh's trace (tap in and out, kvm_irq_line, kvm_vcpu_wakeup, and
# sched_waking/switch of QEMU's threads) on. Every traced exchange carries its index
# (blockpath_trace.py), and when the round's trace holds exactly warmup + n
# requests, the k-th request is the probe's k-th exchange. So each timed sample
# gets its segments A (the request into QEMU's interrupt), B (the vCPU out of its
# halt), C (the guest's work, to its transmit notify), D (QEMU's reply out), and
# rest = its round trip - (A..D): the probe's own send and receive, untraced.
#
# THE RULE, fixed here before any run: a TAIL exchange is one at or above its
# round's p99 round trip. Its EXCESS in a segment is its value there minus the
# round's median of that segment. Pooled over all rounds' tail exchanges:
#   - each segment's median excess, and its share of the summed excess (A..D and
#     rest together add up to the round trip's excess, by construction);
#   - which segment carries the largest excess, exchange by exchange.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: the tail is in the guest's part of
# the path. Every host-side factor tried so far changed nothing, and C holds the
# two IPI wake-ups of the other vCPU, each a scheduling event that can run late.
#   P1 C has the largest median excess of the five, and C's share of the summed
#      excess is >= 50%. REFUTED if another segment's median excess is larger.
#      PARTIAL if C's is the largest but its share is < 50%.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 the trace and the probe align (exactly warmup + n requests) in >= 90% of
#      rounds; unaligned rounds are left out -> P1
#   M2 >= 95% of the aligned rounds' timed exchanges are segmented -> P1
# tailpath_report.py applies it, and scores only at k = 24.
#
# CHANGED AFTER THE SMOKE RUN, BEFORE THE RECORDED ONE (2026-09-24): a request is
# now a frame into the tap of the round's most common length (the probe's 130
# bytes), not any frame of 100 bytes or more. The smoke run's round 3 traced a
# 101-byte frame that was not the probe's, and could not be aligned. The rule and
# the prediction above are unchanged.
#
# The trace costs ~9-11 us per exchange (the block-path record), on every exchange
# alike. The ring buffer is raised to TRACE_KB (4096) per core for the run and
# restored after; lost events stop the run.
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
REPORT="${REPORT:-$here/tailpath_report.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-4096}"
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
VMAP=""; TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_KB_BEFORE=""; TRACE_TOUCHED=0

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

cleanup() {
	say "cleanup"
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
for f in "$PROBE" "$BPT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
grep -q '"k": k' "$BPT" || die "$BPT does not index its exchanges: it predates run-tailpath.sh"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for e in $TEVENTS; do tsu "test -w '$TRACE/events/$e/enable'" || die "no writable $e event under $TRACE"; done
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

m_prepare_out "${OUT:-}" "$HOME/tailpath-out"
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
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "tailpath"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"vcpu_threads\": \"$VMAP\"" \
	"\"trace\": \"run-blockpath.sh's six events, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by blockpath_trace.py (sha256 $(_sha "$BPT"))\"" \
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
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	trace_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "the tail, taken apart"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
