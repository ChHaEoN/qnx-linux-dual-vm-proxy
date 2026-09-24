#!/usr/bin/env bash
# run-queue.sh -- does the slow window need udevd to PROCESS the uevents, or is the kernel
# emitting them enough? Hold udevd's exec queue through half the rounds.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-bursts.
#
# WHAT IS KNOWN. tj-thermal's uevents make a slow window of a few ms, and three written
# by hand make one too (20260924T-a6-orin-uevent). Generic compute, broadcast TLB
# maintenance and syscalls on another core make none, and heavy memory traffic makes a
# third of one (20260924T-a6-orin-bursts). A uevent's path has two halves: the kernel
# emits it and udevd receives it; then udevd runs its rules in a worker and passes the
# result on to its listeners. Which half makes the window is not known.
#
# THE MANIPULATION. `udevadm control --stop-exec-queue` makes udevd queue the events it
# receives without processing them, until `--start-exec-queue`. Checked on the board
# before this was written: while held, a "change" uevent is emitted and waits
# (/run/udev/queue exists); on release it is processed, and the queue file goes after
# `udevadm settle`. One ARM per round, in the pattern run hold hold run, repeated: run
# (the queue as usual) or hold (held from before the round's trace starts until after it
# ends, then released and settled before the next round). Events are delayed a few
# seconds in hold rounds and none is lost. The queue is released on any exit.
# burst_inject.c makes four injections per round in a seeded order, at 0.75 + 0.4 i s +
# U(0, 0.1) s: three U (tj-thermal's three uevents written by hand) and one N (nothing).
# In hold rounds tj-thermal's own polls are held the same way: its read happens, its
# uevents are emitted, and nothing processes them during the round.
#
# THE RUN. One boot of the stamping guest, one arm of the probe repeated: t2ms, the A6
# default (two vCPUs, halt_poll_ns 500000, 2 ms). The light trace of run-uevent.sh
# (frames into tap-qnx, every thermal zone read, the markers; tjphase_trace.py). At the
# end of every round, before any release, whether udevd's queue holds events goes to
# queue.log (in run rounds after a settle). SSH logins accepted during the rounds are
# counted from the journal (logins.txt): the run is watched from the one session that
# started it.
#
# THE RULE, fixed here before any run (queue_report.py applies it):
#   - alignment and classes are run-bursts.sh's: tj (-0.5..+6 ms of a tj-thermal read),
#     then U and N (-0.5..+8 ms of the marker), other, out;
#   - a class's EXCESS in an arm is its median round trip minus that arm's out median,
#     pooled over the arm's aligned rounds.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: the window needs udevd to process the events;
# the kernel emitting them, and udevd receiving them, is not enough.
#   P1 held, the injected uevents make no window: hold's U excess is below +10 us.
#      REFUTED at +10 or more.
#   P2 held, the poll's own uevents make none either: hold's tj excess is below +10 us.
#      REFUTED at +10 or more.
#   P3 running, the injected uevents still make one (the control): run's U excess is
#      >= +20 us. REFUTED below.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> all
#   M2 >= 90% of U injections raised the uevent seqnum by >= 3 -> P1 P3
#   M3 every round's queue at its end fits its arm: held rounds have events waiting,
#      run rounds an empty queue -> all
#   M4 >= 50 U and >= 40 tj exchanges in each arm -> all
#   M5 no SSH login was accepted during the rounds -> all
#   M6 the null windows are quiet in both arms: N's excess within +-10 us -> all
# Scored only at k = 24.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log), gcc. c7 OFF
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
REPORT="${REPORT:-$here/queue_report.py}"
INJ_SRC="${INJ_SRC:-$here/burst_inject.c}"
INJ="/tmp/burst_inject.$$"
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
TZ=""; QUEUE_TOUCHED=0; QPAT=(run hold hold run)
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
	rm -f "$INJ"
	if [ "$QUEUE_TOUCHED" = 1 ]; then
		sudo -n udevadm control --start-exec-queue && sudo -n udevadm settle --timeout=30 \
			&& say "udevd's queue released and settled" \
			|| echo "WARNING: udevd's queue may still be held -- release it by hand: sudo udevadm control --start-exec-queue" >&2
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
for f in "$PROBE" "$TJT" "$REPORT" "$INJ_SRC" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
command -v gcc > /dev/null || die "no gcc to build $INJ_SRC"
sudo -n udevadm settle --timeout=10 || die "udevd's queue does not settle at preflight"
[ ! -e /run/udev/queue ] || die "udevd's queue is not empty at preflight"
gcc -O2 -Wall -o "$INJ" "$INJ_SRC" || die "could not build $INJ_SRC"
sudo -n journalctl -n 1 -u ssh > /dev/null || die "sudo -n journalctl does not work: logins could not be counted"
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

m_prepare_out "${OUT:-}" "$HOME/queue-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "queue"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"injector\": \"burst_inject.c (sha256 $(_sha "$INJ_SRC")) on core $CORE_AUX, zone $ZONE_TYPE ($(basename "$TZ")): per round three U and one N, slots 0.75 + 0.4 i s + U(0, 0.1) s; udevd's exec queue run or held per round in the pattern ${QPAT[*]}, seed SEED*100 + round, SEED $SEED\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, three U and one N in each, udevd's queue run/hold -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
IPID=""
for r in $(seq 1 "$K"); do
	arm="${QPAT[$(( (r - 1) % ${#QPAT[@]} ))]}"
	echo "round $r arm: $arm" >> "$OUT/order.log"
	if [ "$arm" = hold ]; then
		QUEUE_TOUCHED=1
		sudo -n udevadm control --stop-exec-queue || die "could not hold udevd's queue for round $r"
	fi
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	: > "$OUT/inj-t2ms_r$r.jsonl"
	trace_start
	taskset -c "$CORE_AUX" sudo -n "$INJ" --zone "$TZ" --marker "$TRACE/trace_marker" \
		--log "$OUT/inj-t2ms_r$r.jsonl" --seed $((SEED * 100 + r)) --kinds UUUN \
		--start 0.75 --step 0.4 --jitter 0.1 --burst-ms 3 &
	IPID=$!
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	wait "$IPID" || die "the injector failed in round $r"
	IPID=""
	[ "$(grep -c . "$OUT/inj-t2ms_r$r.jsonl")" -eq 4 ] || die "the injector logged $(grep -c . "$OUT/inj-t2ms_r$r.jsonl") injections in round $r, not 4"
	trace_take "t2ms_r$r"
	if [ "$arm" = hold ]; then
		if [ -e /run/udev/queue ]; then q=held; else q=empty; fi
		echo "round $r end: queue $q" >> "$OUT/queue.log"
		sudo -n udevadm control --start-exec-queue || die "could not release udevd's queue after round $r"
		sudo -n udevadm settle --timeout=30 || die "udevd's queue did not settle after round $r"
		QUEUE_TOUCHED=0
	else
		sudo -n udevadm settle --timeout=30 || die "udevd's queue did not settle after round $r"
		if [ -e /run/udev/queue ]; then q=held; else q=empty; fi
		echo "round $r end: queue $q" >> "$OUT/queue.log"
	fi
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "does the window need udevd to process the events?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
