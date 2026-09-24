#!/usr/bin/env bash
# run-uevent.sh -- is it the uevents? Inject tj-thermal's uevents without its read,
# and its read without the uevents, and see which one brings the slow window.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-tjphase.
#
# WHAT IS KNOWN. Moving tj-thermal's 1024 ms poll moves a ~6 ms slow window with it
# (20260924T-a6-orin-tjphase, all three held): 56% of exchanges starting within
# -0.5..+6 ms of a tj read are in the tail, against 0.60% elsewhere. The host's
# handlers on QEMU's cores are not it (20260924T-a6-orin-tailhost).
#
# WHERE THE PREDICTION COMES FROM (looked at on the board before this was written,
# and stated so it is not mistaken for a blind test):
#   - tj-thermal is the only zone under the user_space governor (the others are
#     step_wise). On every update it emits one uevent per trip: three (TRIP=0,1,2),
#     within ~0.1 ms of the read;
#   - udevd runs its rules for each in turn; `udevadm monitor` saw the three
#     finish at +1.9, +3.2 and +4.5 ms, which is about the slow window;
#   - about twenty processes listen for udev events (a desktop image: gnome-shell,
#     Xorg, NetworkManager, systemd, ...);
#   - writing "change" to the zone's uevent file emits one uevent per write (the
#     seqnum rose by 3 for 3 writes), and reading its temp emits none (+0).
#
# THE MANIPULATION (uevent_inject.py, as root on the aux core, during each round):
# four injections at seeded, jittered times 0.8-2.55 s into the round, two of each
# kind in a seeded order, each three actions back to back as the poll's are:
#   U  write "change" to tj-thermal's uevent file: its three uevents, no read;
#   R  read tj-thermal's temp: the driver's read (the BPMP on Tegra234), no uevent.
# Each is marked in the trace ("tjinj KIND I" to trace_marker) just before it, and
# the uevent seqnum is read around it. Nothing about thermal management is changed:
# no mode, policy, trip or cooling state is written. A synthetic "change" carries no
# TEMP or TRIP, unlike the poll's.
#
# THE RUN. One boot of the stamping guest, one arm repeated: t2ms, the A6 default
# (two vCPUs, halt_poll_ns 500000, 2 ms). The light trace of run-tjphase.sh (frames
# into tap-qnx, every thermal zone read) plus the markers, reduced by
# tjphase_trace.py; the injector's log per round (inj-t2ms_rN.jsonl).
#
# THE RULE, fixed here before any run (uevent_report.py applies it):
#   - a round aligns when its trace holds exactly warmup + n requests (frames of
#     the round's most common length); timed sample j is request warmup + j, and
#     its T0 is that request's time;
#   - a TAIL exchange is at or above its round's p99 round trip;
#   - each timed exchange falls in one class, the first that matches: tj (T0
#     within -0.5..+6 ms of a traced tj-thermal read), U (within -0.5..+8 ms of a
#     U marker), R (within -0.5..+8 ms of an R marker), other (within -0.5..+6 ms
#     of another zone's read), out (none);
#   - each class's tail rate is its tail exchanges over its exchanges, pooled over
#     the aligned rounds.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: the slow window is the uevents'
# handling in userspace, not the temperature read.
#   P1 three uevents alone make the slow window: the U class's tail rate is >= 25%.
#      PARTIAL at 10-25%. REFUTED below 10%.
#   P2 three temperature reads alone do not: the R class's tail rate is below 10%.
#      REFUTED at 10% or more.
#   P3 the poll itself still does, in this run (the control): the tj class's tail
#      rate is >= 25%. PARTIAL at 10-25%. REFUTED below 10%.
#   Why absolute rates and not multiples of the out rate: a ~190-exchange class at
#   the ~0.6% base rate reaches 5x with three chance tail exchanges, as the
#   synthetic test showed before any run; the hot window's rate was 55-68%
#   (tailhost, tailpath, tjphase).
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> P1 P2 P3
#   M2 the manipulation did what it says: >= 90% of U injections raised the uevent
#      seqnum by >= 3, and >= 90% of R injections left it unchanged -> P1 P2
#   M3 >= 90% of the logged injections have their marker in the aligned rounds'
#      traces -> P1 P2
#   M4 the U and R classes hold >= 30 exchanges each -> P1 P2
#   M5 the tj class holds >= 30 exchanges -> P3
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
REPORT="${REPORT:-$here/uevent_report.py}"
INJ="${INJ:-$here/uevent_inject.py}"
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
TZ=""
TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_KB_BEFORE=""; TRACE_TOUCHED=0

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
	[ -n "${IPID:-}" ] && kill "$IPID" 2>/dev/null
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
for f in "$PROBE" "$TJT" "$REPORT" "$INJ" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat "$z/type" 2>/dev/null)" = "$ZONE_TYPE" ] && { TZ="$z"; break; }
done
[ -n "$TZ" ] || die "no thermal zone of type $ZONE_TYPE"
[ -r /sys/kernel/uevent_seqnum ] || die "no /sys/kernel/uevent_seqnum"
tsu "test -w '$TZ/uevent' && test -r '$TZ/temp' && test -w '$TRACE/trace_marker'" \
	|| die "cannot write $TZ/uevent or $TRACE/trace_marker, or read $TZ/temp"
[ "$(tsu "cat '$TRACE/options/markers'")" = 1 ] || die "$TRACE/options/markers is not 1: the injection markers would not be traced"
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

m_prepare_out "${OUT:-}" "$HOME/uevent-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "uevent"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"injector\": \"uevent_inject.py (sha256 $(_sha "$INJ")) on $ZONE_TYPE ($(basename "$TZ")): per round 2 U (3 uevent writes) and 2 R (3 temp reads), slots 0.8 + 0.5 i s + U(0, 0.25) s, seed SEED*100 + round, SEED $SEED\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, 2 U and 2 R injections in each -> $OUT"
: > "$OUT/thermal.log"
IPID=""
for r in $(seq 1 "$K"); do
	echo "round $r order: t2ms" >> "$OUT/order.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	: > "$OUT/inj-t2ms_r$r.jsonl"
	trace_start
	taskset -c "$CORE_AUX" sudo -n python3 "$INJ" --zone "$TZ" --marker "$TRACE/trace_marker" \
		--log "$OUT/inj-t2ms_r$r.jsonl" --seed $((SEED * 100 + r)) &
	IPID=$!
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	wait "$IPID" || die "the injector failed in round $r"
	IPID=""
	[ "$(grep -c . "$OUT/inj-t2ms_r$r.jsonl")" -eq 4 ] || die "the injector logged $(grep -c . "$OUT/inj-t2ms_r$r.jsonl") injections in round $r, not 4"
	trace_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "is it the uevents?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
