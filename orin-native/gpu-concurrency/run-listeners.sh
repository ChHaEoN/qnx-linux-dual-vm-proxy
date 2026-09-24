#!/usr/bin/env bash
# run-listeners.sh -- which listener makes tj-thermal's slow window, and does it
# matter where it runs? Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-uevent.
#
# WHAT IS KNOWN. Three uevents on tj-thermal, with no temperature read, make a slow
# window of ~5 ms (37.4% of exchanges in it are in the tail, against 0.56%); three
# reads with no uevent do not (2.2%) (20260924T-a6-orin-uevent, all three held).
# Host code on QEMU's own cores is not it (20260924T-a6-orin-tailhost).
#
# WHERE THE PREDICTION COMES FROM (looked at on the board before this was written,
# and stated so it is not mistaken for a blind test):
#   - with no guest running, a trace of every core's switches after three uevent
#     bursts on tj-thermal: systemd-udevd ran 13.7 ms of CPU in the 8 ms after
#     them (on cores 4 and 5 there), gnome-shell 1.9 ms, and nothing else of note;
#     after three read bursts, nothing but the injector;
#   - udevd's affinity is 0-5, so it can run beside QEMU;
#   - cores 0-3 share one 2 MB L3 (QEMU runs on 0-2), cores 4-5 another (the
#     probe runs on 4, the aux core is 5).
#
# THE MANIPULATIONS.
#   1. uevent_inject.py as in run-uevent.sh, with three U injections and one R per
#      round (kinds U,U,U,R), seeded order and times 0.8-2.55 s into the round.
#   2. One ARM per round, in a rotation (free c3 c5, c3 c5 free, c5 free c3, ...):
#      free  every systemd-udevd process keeps its own affinity (as found);
#      c3    every systemd-udevd process pinned to core 3 (QEMU's L3, not its cores);
#      c5    every systemd-udevd process pinned to core 5 (the other L3).
#      Pinned with taskset -a before the round and read back; a worker udevd forks
#      inherits it. Every udevd process gets its original affinity back at the end
#      (and on any exit). Nothing else is changed.
#
# THE RUN. One boot of the stamping guest, one arm of the probe repeated: t2ms, the
# A6 default (two vCPUs, halt_poll_ns 500000, 2 ms). Two traces: the light one of
# run-uevent.sh (frames into tap-qnx, every thermal zone read, the markers;
# tjphase_trace.py), and an ftrace instance with every core's sched_switch
# (listeners_trace.py: who ran where, by comm and pid). QEMU's thread ids go to
# qemu-tids.txt.
#
# THE RULE, fixed here before any run (listeners_report.py applies it):
#   - alignment, the tail and the classes tj, U, R, other, out are run-uevent.sh's;
#   - the ATTRIBUTION: each task's CPU time inside [marker, marker + 8 ms] of each
#     U and R marker, from the switch trace, leaving out the idle task, QEMU's
#     threads, the probe and the injector (comm python3, sudo). A task's CLASS is
#     "udevd" for systemd-udevd and its workers, else its comm up to any "/". Its
#     EXCESS is its mean CPU per U window minus its mean per R window, in the free
#     arm; the excess total is the sum of the positive excesses.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. H: udevd is the listener that matters,
# and its work slows the guest by sharing QEMU's L3.
#   P1 which: udevd's excess is >= 50% of the free arm's excess total. REFUTED below.
#   P2 where: the U class's tail rate with udevd on core 3 is >= 25% and >= 2x the
#      rate with udevd on core 5. REFUTED if the core-3 rate is below 1.25x the
#      core-5 rate. PARTIAL otherwise.
#   P3 the free arm still shows the window (the control): its U class's tail rate
#      is >= 25%. REFUTED below.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> P1 P2 P3
#   M2 >= 90% of U injections raised the uevent seqnum by >= 3, and >= 90% of R
#      injections left it -> P1 P2 P3
#   M3 the pinning held: in each pinned arm, >= 95% of udevd's CPU in U windows is
#      on its core, and udevd ran >= 0.5 ms per U window there -> P2
#   M4 >= 30 exchanges in the U class in every arm, and >= 5 R windows in the free
#      arm -> P1 P2 P3
#   M5 every aligned round has its switch trace -> P1 P2
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
REPORT="${REPORT:-$here/listeners_report.py}"
LST="${LST:-$here/listeners_trace.py}"
INJ="${INJ:-$here/uevent_inject.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
SW_KB="${SW_KB:-8192}"
INST="$TRACE/instances/listeners"
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
TZ=""; INST_MADE=0; UDEV_AFF=""; UDEV_TOUCHED=0
ROT=(free c3 c5 c3 c5 free c5 free c3)
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

udev_pids() { pgrep -x systemd-udevd; pgrep -x '(udev-worker)'; }

udev_pin() {   # $1 core spec for every udevd process
	local p
	UDEV_TOUCHED=1
	for p in $(udev_pids); do
		sudo -n taskset -a -pc "$1" "$p" > /dev/null 2>&1 || [ ! -d "/proc/$p" ] || return 1
	done
	for p in $(udev_pids); do
		[ "$(_cpuset "$(taskset -pc "$p" 2>/dev/null | sed 's/.*: //')")" = "$(_cpuset "$1")" ] || [ ! -d "/proc/$p" ] || return 1
	done
}

sw_start() {
	tsu "cd '$INST' && echo 0 > tracing_on && echo > trace && echo 1 > events/sched/sched_switch/enable && echo 1 > tracing_on" \
		|| die "could not start the switch trace"
}

sw_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on && echo 0 > events/sched/sched_switch/enable" || die "could not stop the switch trace after $1"
	tsu "cat '$INST/trace'" | python3 "$LST" reduce > "$OUT/sw-$1.log" \
		|| die "the switch trace of $1 was refused (see the message above) -- the run stops here"
}

cleanup() {
	say "cleanup"
	[ -n "${IPID:-}" ] && kill "$IPID" 2>/dev/null
	if [ "$UDEV_TOUCHED" = 1 ]; then
		udev_pin "$UDEV_AFF" && say "udevd's affinity restored to $UDEV_AFF" \
			|| echo "WARNING: udevd's affinity may not be restored -- set it by hand: taskset -a -pc $UDEV_AFF <each systemd-udevd pid>" >&2
	fi
	if [ "$INST_MADE" = 1 ]; then
		tsu "cd '$INST' && echo 0 > tracing_on && echo 0 > events/sched/sched_switch/enable" 2>/dev/null
		tsu "rmdir '$INST'" 2>/dev/null || { sleep 1; tsu "rmdir '$INST'" 2>/dev/null; } \
			|| echo "WARNING: could not remove the ftrace instance $INST" >&2
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
for f in "$PROBE" "$TJT" "$REPORT" "$INJ" "$LST" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
UDEV_MAIN="$(pgrep -o -x systemd-udevd)"
[ -n "$UDEV_MAIN" ] || die "no systemd-udevd running"
UDEV_AFF="$(taskset -pc "$UDEV_MAIN" | sed 's/.*: //')"
[ -n "$UDEV_AFF" ] || die "cannot read udevd's affinity"
for p in $(udev_pids); do
	[ "$(_cpuset "$(taskset -pc "$p" 2>/dev/null | sed 's/.*: //')")" = "$(_cpuset "$UDEV_AFF")" ] || [ ! -d "/proc/$p" ] \
		|| die "udevd process $p has an affinity other than the main one's ($UDEV_AFF) -- someone changed it"
done
tsu "test -d '$TRACE/instances' && test ! -e '$INST'" || die "no $TRACE/instances, or $INST exists -- someone else is tracing"
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

m_prepare_out "${OUT:-}" "$HOME/listeners-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"
tsu "mkdir '$INST'" || die "could not create the ftrace instance $INST"
INST_MADE=1
tsu "cd '$INST' && echo 0 > tracing_on && echo mono > trace_clock && echo $SW_KB > buffer_size_kb" || die "could not set up $INST"
[ "$(tsu "cat '$INST/options/overwrite'")" = 1 ] || die "$INST/options/overwrite is not 1: lost events would not show"
ls "/proc/$QPID/task" > "$OUT/qemu-tids.txt"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "listeners"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"injector\": \"uevent_inject.py (sha256 $(_sha "$INJ")) on $ZONE_TYPE ($(basename "$TZ")): per round 3 U (3 uevent writes) and 1 R (3 temp reads), slots 0.8 + 0.5 i s + U(0, 0.25) s, seed SEED*100 + round, SEED $SEED\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	"\"switches\": \"instance listeners: sched/sched_switch on every core, mono clock, buffer $SW_KB KB per core, reduced by listeners_trace.py (sha256 $(_sha "$LST"))\"" \
	"\"udevd\": \"arms free (affinity $UDEV_AFF, as found), c3 (pinned to 3), c5 (pinned to 5), one per round in the rotation ${ROT[*]}\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, 3 U and 1 R injections in each, udevd free/c3/c5 -> $OUT"
: > "$OUT/thermal.log"
IPID=""
for r in $(seq 1 "$K"); do
	arm="${ROT[$(( (r - 1) % ${#ROT[@]} ))]}"
	case "$arm" in free) spec="$UDEV_AFF" ;; c3) spec=3 ;; c5) spec=5 ;; esac
	udev_pin "$spec" || die "could not pin udevd to $spec for round $r"
	echo "round $r arm: $arm" >> "$OUT/order.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	: > "$OUT/inj-t2ms_r$r.jsonl"
	trace_start
	sw_start
	taskset -c "$CORE_AUX" sudo -n python3 "$INJ" --zone "$TZ" --marker "$TRACE/trace_marker" \
		--log "$OUT/inj-t2ms_r$r.jsonl" --seed $((SEED * 100 + r)) --kinds U,U,U,R &
	IPID=$!
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	wait "$IPID" || die "the injector failed in round $r"
	IPID=""
	[ "$(grep -c . "$OUT/inj-t2ms_r$r.jsonl")" -eq 4 ] || die "the injector logged $(grep -c . "$OUT/inj-t2ms_r$r.jsonl") injections in round $r, not 4"
	trace_take "t2ms_r$r"
	sw_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

udev_pin "$UDEV_AFF" || die "could not restore udevd's affinity to $UDEV_AFF"
UDEV_TOUCHED=0
say "udevd's affinity restored to $UDEV_AFF"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "which listener, and where?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
