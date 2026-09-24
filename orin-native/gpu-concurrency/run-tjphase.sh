#!/usr/bin/env bash
# run-tjphase.sh -- does the slow window move with tj-thermal's poll? Move the poll
# to a new phase before every round, and see whether the tail follows it.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-tailhost.
#
# WHAT IS KNOWN. Exploratory, from 20260924T-a6-orin-tailhost and the tailpath
# record (the same boot): an exchange that starts in the ~6 ms after jiffy 8 (mod
# 256) is slow 55-68% of the time, against 0.7% elsewhere, and that window holds
# 29-37% of the tail (>= the round's p99). The one thermal zone read at that jiffy
# is tj-thermal, every 1024 ms. The other zones are read together elsewhere in the
# cycle, where the tail is normal. The host's handlers on QEMU's cores are not what
# makes it slow (P2 there refuted). That is a coincidence in time; this run is the
# test of it.
#
# THE MANIPULATION. Writing "disabled" then "enabled" to the zone's mode cancels its
# poll and re-arms it from that moment, so the next read comes ~1 s after the write
# and the poll keeps the new phase. Before each round the harness waits a delay
# drawn from 0-1023 ms (bash RANDOM, seeded by SEED), toggles the zone, and only
# then starts the round. The zone is enabled again within the same shell command;
# it is checked after every toggle and at the end, and the run stops if it is not
# enabled. Nothing else about thermal management is touched. The zone stays at
# the last round's phase after the run (a phase, not a setting).
#
# THE RUN. One boot of the stamping guest, one arm repeated: t2ms, the A6 default
# (two vCPUs, halt_poll_ns 500000, 2 ms). A light trace, top-level buffer: frames
# into tap-qnx (net_dev_xmit, filtered) and every thermal zone read
# (thermal_temperature), reduced by tjphase_trace.py. Before the first toggle, the
# reads alone are traced for 2.2 s (tp-before.log): that is the OLD phase.
#
# THE RULE, fixed here before any run (tjphase_report.py applies it):
#   - a round aligns when its trace holds exactly warmup + n requests (frames of
#     the round's most common length); timed sample j is request warmup + j, and
#     its T0 is that request's time;
#   - a TAIL exchange is at or above its round's p99 round trip;
#   - each timed exchange falls in one class, the first that matches: tj (T0
#     within -0.5..+6 ms of a traced tj-thermal read in its round), old (within
#     -0.5..+6 ms of the old phase, extended every 1024 ms), other (within
#     -0.5..+6 ms of another zone's read), out (none);
#   - each class's tail rate is its tail exchanges over its exchanges, pooled over
#     the aligned rounds.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: tj-thermal's read causes the slow
# window. Move the poll and the window moves with it.
#   P1 the tail follows the moved poll: the tj class's tail rate is >= 10x the out
#      class's. PARTIAL at 3-10x. REFUTED below 3x.
#   P2 the other zones' reads do not carry it: the other class's tail rate is
#      below 10%. REFUTED at 10% or more.
#   P3 the old phase goes quiet once the poll has left it: the old class's tail
#      rate is below 10%. REFUTED at 10% or more -- then something at the old
#      phase, not the read, makes the window.
#   Why 10% and not a multiple of the out rate: each of these classes holds only
#   ~140 exchanges at a ~0.7% base rate, so one or two chance tail exchanges
#   would double it; the hot window's rate was 55-68%. (Set before any run,
#   when the synthetic test showed a 2x bound failing by chance.)
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> P1 P2 P3
#   M2 a tj-thermal read falls inside the timed span in >= 90% of aligned rounds,
#      and the tj class holds >= 30 exchanges -> P1
#   M3 the old phase is known (>= 2 reads before the first toggle, within 1 ms of
#      each other in the 1024 ms cycle); in >= 80% of aligned rounds every
#      tj-thermal read is >= 32 ms from it; the old class holds >= 30 exchanges
#      -> P1 P3
#   M4 another zone's read falls inside the timed span in >= 90% of aligned rounds,
#      and the other class holds >= 30 exchanges -> P2
# Scored only at k = 24.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log). c7 OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN.
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
SEED="${SEED:-24}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/tjphase_report.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
ZONE_TYPE=tj-thermal
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
TEVENTS="net/net_dev_xmit thermal/thermal_temperature"
TZ=""; TZ_TOUCHED=0
TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_KB_BEFORE=""; TRACE_TOUCHED=0

tsu() {   # $1 = a shell command, run as root on the aux core
	taskset -c "$CORE_AUX" sudo -n sh -c "$1"
}

tz_mode() { cat "$TZ/mode" 2>/dev/null; }

tz_toggle() {   # $1 label; the zone is disabled and enabled again in one command
	TZ_TOUCHED=1
	tsu "echo disabled > '$TZ/mode'; echo enabled > '$TZ/mode'" \
		|| { tsu "echo enabled > '$TZ/mode'"; die "the toggle of $ZONE_TYPE failed at $1"; }
	[ "$(tz_mode)" = enabled ] || { tsu "echo enabled > '$TZ/mode'"; die "$ZONE_TYPE is not enabled after the toggle at $1"; }
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
	tsu "cd '$TRACE' && echo 0 > tracing_on && echo > trace && echo 'name == \"tap-qnx\"' > events/net/net_dev_xmit/filter" \
		|| die "could not set the trace filter"
	trace_events 1 || die "could not enable the trace events"
	tsu "cd '$TRACE' && echo 1 > tracing_on" || die "could not start tracing"
}

trace_take() {   # $1 tag
	tsu "cd '$TRACE' && echo 0 > tracing_on" || die "could not stop the trace after $1"
	tsu "cat '$TRACE/trace'" | python3 "$TJT" reduce > "$OUT/tp-$1.log" \
		|| die "the trace of $1 was refused (see the message above) -- the run stops here"
	trace_events 0 || die "could not disable the trace events after $1"
}

cleanup() {
	say "cleanup"
	if [ "$TZ_TOUCHED" = 1 ] && [ "$(tz_mode)" != enabled ]; then
		tsu "echo enabled > '$TZ/mode'"
		[ "$(tz_mode)" = enabled ] && say "$ZONE_TYPE re-enabled" \
			|| echo "WARNING: $ZONE_TYPE ($TZ) is NOT enabled -- enable it by hand: echo enabled > $TZ/mode" >&2
	fi
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
for f in "$PROBE" "$TJT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat "$z/type" 2>/dev/null)" = "$ZONE_TYPE" ] && { TZ="$z"; break; }
done
[ -n "$TZ" ] || die "no thermal zone of type $ZONE_TYPE"
[ "$(tz_mode)" = enabled ] || die "$ZONE_TYPE ($TZ) is not enabled at preflight -- someone else changed it"
for e in $TEVENTS; do tsu "test -w '$TRACE/events/$e/enable'" || die "no writable $e event under $TRACE"; done
[ "$(tsu "cat '$TRACE/current_tracer'")" = nop ] || die "$TRACE/current_tracer is not nop -- someone else is tracing"
for e in $TEVENTS; do
	[ "$(tsu "cat '$TRACE/events/$e/enable'")" = 0 ] || die "$e is already enabled -- someone else is tracing"
done
[ "$(tsu "cat '$TRACE/options/overwrite'")" = 1 ] || die "$TRACE/options/overwrite is not 1: lost events would not show"
[ -z "$(tsu "cat '$TRACE/set_event_pid' '$TRACE/set_event_notrace_pid' 2>/dev/null")" ] || die "a pid filter is set in $TRACE"
tsu "grep -qw mono '$TRACE/trace_clock'" || die "$TRACE has no mono trace clock"
TRACE_ON_BEFORE="$(tsu "cat '$TRACE/tracing_on'")"
TRACE_CLOCK_BEFORE="$(tsu "cat '$TRACE/trace_clock'" | sed -n 's/.*\[\(.*\)\].*/\1/p')"
[ -n "$TRACE_CLOCK_BEFORE" ] || die "cannot read the current trace clock"
TRACE_KB_BEFORE="$(tsu "cat '$TRACE/buffer_size_kb'" | sed -n 's/.*expanded: \([0-9]*\).*/\1/p; s/^\([0-9][0-9]*\)$/\1/p' | head -1)"
[ -n "$TRACE_KB_BEFORE" ] || die "cannot read the trace buffer size"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"

m_prepare_out "${OUT:-}" "$HOME/tjphase-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "tjphase"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"zone\": \"$ZONE_TYPE ($(basename "$TZ")), toggled disabled/enabled before every round after a delay of 0-1023 ms (bash RANDOM, SEED $SEED)\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "the old phase: the zones' reads for 2.2 s, before any toggle"
trace_start
sleep 2.2
trace_take before
[ "$(grep -c " T $ZONE_TYPE\$" "$OUT/tp-before.log")" -ge 2 ] || die "fewer than 2 $ZONE_TYPE reads in 2.2 s before the first toggle"

say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, the zone moved before each -> $OUT"
RANDOM="$SEED"
: > "$OUT/thermal.log"
: > "$OUT/toggles.log"
for r in $(seq 1 "$K"); do
	echo "round $r order: t2ms" >> "$OUT/order.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	d=$((RANDOM % 1024))
	sleep "$(printf '%d.%03d' $((d / 1000)) $((d % 1000)))"
	tz_toggle "round $r"
	echo "round $r: delay ${d} ms, toggled, mode $(tz_mode)" >> "$OUT/toggles.log"
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	trace_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done
[ "$(tz_mode)" = enabled ] || die "$ZONE_TYPE is not enabled at the end of the run"
echo "end: $ZONE_TYPE mode $(tz_mode)" >> "$OUT/toggles.log"

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "does the slow window move with the poll?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
