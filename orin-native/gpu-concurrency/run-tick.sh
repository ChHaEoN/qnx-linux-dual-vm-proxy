#!/usr/bin/env bash
# run-tick.sh -- with the host's userspace confined to cores 3 and 5, what makes the tail
# that is left? The host's own tick, and the work it sets off, on QEMU's and the probe's cores?
# Phase 3b / A6, 2026-09-25; follows 20260925T-a6-orin-natural. The owner asked for this
# test (2026-09-25) knowing it changes systemd settings on the board, at runtime, restored
# after.
#
# WHAT IS KNOWN. Confining the host's userspace to cores 3 and 5 removes most of
# tj-thermal's window, but confined, 194 of the 220 exchanges at or above their round's p99
# start away from every thermal read, and that record does not say what slows them
# (20260925T-a6-orin-natural). Looking at that record afterwards -- an exploration, not a
# test -- every thermal read falls in the first 250 us of a 4 ms grid of the trace's
# monotonic clock: the host's tick (HZ=250). CONFIG_NO_HZ_FULL is not set, so a busy core
# always takes the tick, and without skew_tick every core takes it at the same moment
# (tick_sched_timer fires ~3.5 us after the grid). In 50 us bins of the request's phase the
# slow exchanges are those leaving 150 to 0 us before a tick (+8 to +13 us at the median; the
# bins either side lie within -3..+5 us). That bin, [3850, 4000) us mod 4000, held 62 of the
# confined arm's 194 out-class tail exchanges (32%) against 4.1% of all out-class exchanges
# (7.7x), and was +11.2 us slower at the median. The bin and its edges were chosen after
# looking at that record: this run tests it on new data. Without confinement, the
# host's handlers on QEMU's threads were 12.7% of the tail's excess
# (20260924T-a6-orin-tailhost).
#
# THE RUN. One boot of the stamping guest, one arm of the probe repeated: t2ms, the A6
# default (two vCPUs, halt_poll_ns 500000, 2 ms). k = 40 rounds, n = 1000, 200 warm-up. EVERY
# round is confined as run-natural.sh's confined arm: system.slice, init.scope,
# user@1000.service and every session scope but the harness's own on AllowedCPUs=3,5, QEMU's
# threads pinned back to QEMU_CORES after the switch and checked, the allowed CPUs logged
# before and after each round (confine.log), and everything set back to 0-5, the drop-ins
# removed and systemd reloaded at the end and on any exit. Nothing is injected. Two kinds of
# round, in the pattern light heavy heavy light, repeated:
#   light  the light trace only, as run-natural.sh's (frames into tap-qnx and every thermal
#          zone read; tjphase_trace.py);
#   heavy  the light trace, plus an ftrace instance on QEMU's cores and the probe's only
#          (tracing_cpumask) with sched_switch, irq_handler_entry/exit, softirq_entry/exit,
#          workqueue_execute_start/end, timer_expire_entry and hrtimer_expire_entry
#          (tick_trace.py; tk-t2ms_rN.log), and QEMU's thread ids read before and after the
#          round (qtids-t2ms_rN.txt).
# SSH logins accepted during the rounds are counted from the journal (logins.txt): the run
# is watched from the one session that started it.
#
# THE RULE, fixed here before any run (tick_report.py applies it):
#   - alignment and classes (tj, other, out) are run-natural.sh's; everything below uses
#     the out class only;
#   - an exchange is in the TICK BIN when its request frame's time t0, in us of the trace
#     clock, is in [3850, 4000) mod 4000; it is a TAIL exchange when its round trip is at or
#     above its round's p99 (nearest rank, over all the round's timed exchanges);
#   - light rounds, pooled: the tick bin's tail RATIO is its share of the tail exchanges
#     over its share of all exchanges; its SLOWDOWN is the median round trip of tick-bin
#     exchanges minus that of the others;
#   - heavy rounds: an exchange's FOREIGN time is the time in [t0, t0 + 250 us], summed over
#     QEMU's cores and the probe's, in which the core ran a hard interrupt, a softirq, a work
#     item or any task but QEMU's threads, the probe (python3 on the probe's core) and idle;
#     innermost first, so a softirq is not counted inside a hard interrupt, nor a task under
#     either (tick_trace.Contexts and foreign());
#   - heavy rounds, pooled: DIFF is the median foreign time of tail exchanges minus that of
#     non-tail ones, in the tick bin or outside it; the SHARE of work not in hard interrupts
#     is (the difference in mean softirq + work + task time) over (the difference in mean
#     foreign time), tail minus non-tail in the tick bin.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: the host's tick, landing on QEMU's and the probe's
# cores during an exchange, is the largest identifiable source of the tail confinement
# leaves; what makes a tick-overlapping exchange a tail one is the work the tick sets off
# (softirqs, work items, other tasks), not the interrupt itself; and away from the tick the
# tail is not the host's work on those cores.
#   P1 the tick bin is over-represented in the tail: RATIO >= 3 (light rounds).
#   P2 tick-bin exchanges are slower: SLOWDOWN >= +5 us (light rounds).
#   P3 in the tick bin, tail exchanges carry more foreign time: DIFF >= +10 us (heavy).
#   P4 that extra is mostly not hard interrupts: SHARE >= 0.5, with the difference in mean
#      foreign time > 0 (heavy).
#   P5 outside the tick bin the tail is not the host's work on those cores: DIFF <= +5 us
#      (heavy).
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> all
#   M2 every round confined: udevd, PID 1 and gnome-shell on 3,5 before and after, and
#      QEMU's threads on 0-2 -> all
#   M3 no SSH login was accepted during the rounds -> all
#   M4 the tick is on the grid: >= 90% of the heavy rounds' tick_sched_timer expiries lie
#      within [0, 100) us of a multiple of 4000 us -> all
#   M5 counts: >= 30 tick-bin tail exchanges in the light rounds -> P1 P2; >= 20 tick-bin
#      tail and >= 100 tick-bin non-tail exchanges in the heavy rounds -> P3 P4; >= 20 tail
#      exchanges outside the bin in the heavy rounds -> P5
#   M6 the heavy trace does not distort the exchange: |p50 heavy - p50 light| <= 10 us
#      -> P3 P4 P5
# Scored only at k = 40.
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
K="${K:-40}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
SEED="${SEED:-24}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/tick_report.py}"
TKT="${TKT:-$here/tick_trace.py}"
CONF_CORES="${CONF_CORES:-3,5}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
TK_KB="${TK_KB:-4096}"
INST="$TRACE/instances/tickwork"
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
TKEVENTS="sched/sched_switch irq/irq_handler_entry irq/irq_handler_exit irq/softirq_entry irq/softirq_exit workqueue/workqueue_execute_start workqueue/workqueue_execute_end timer/timer_expire_entry timer/hrtimer_expire_entry"
TZ=""; CONF_TOUCHED=0; UNITS=""; CPAT=(light heavy heavy light); INST_MADE=0; TK_MASK=""
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

allowed() { awk '/^Cpus_allowed_list/ {print $2}' "/proc/$1/status" 2>/dev/null; }

set_units() {   # $1 core list
	local u
	CONF_TOUCHED=1
	for u in $UNITS; do sudo -n systemctl set-property --runtime "$u" "AllowedCPUs=$1" || return 1; done
}

conf_state() {   # one line: udevd, PID 1, gnome-shell and QEMU threads' allowed CPUs
	local g gs q t
	g="$(pgrep -o -x gnome-shell)"
	if [ -n "$g" ]; then gs="$(allowed "$g")"; else gs=none; fi
	q=""
	for t in $(ls "/proc/$QPID/task"); do q="$q$(allowed "$QPID/task/$t") "; done
	echo "udevd=$(allowed "$(pgrep -o -x systemd-udevd)") pid1=$(allowed 1) gnome-shell=$gs qemu=$(echo $q | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/ $//')"
}

repin_qemu() {   # the cpuset changes reset QEMU's own pin; put it back and check it
	local t
	for t in $(ls "/proc/$QPID/task"); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" > /dev/null || return 1
	done
	for t in $(ls "/proc/$QPID/task"); do
		[ "$(_cpuset "$(allowed "$QPID/task/$t")")" = "$(_cpuset "$QEMU_CORES")" ] || return 1
	done
}

cores_of() {   # $1 a core list such as 0-2,4: one core per line
	local x
	for x in ${1//,/ }; do
		case "$x" in *-*) seq "${x%-*}" "${x#*-}" ;; *) echo "$x" ;; esac
	done
}

tk_events() {   # $1 = 0 or 1
	local e cmd="cd '$INST'"
	for e in $TKEVENTS; do cmd="$cmd && echo $1 > events/$e/enable"; done
	tsu "$cmd"
}

tk_start() {
	tsu "cd '$INST' && echo 0 > tracing_on && echo > trace" || die "could not clear $INST"
	tk_events 1 || die "could not enable the tick events"
	tsu "cd '$INST' && echo 1 > tracing_on" || die "could not start the tick trace"
}

tk_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on" || die "could not stop the tick trace after $1"
	tk_events 0 || die "could not disable the tick events after $1"
	tsu "cat '$INST/trace'" | python3 "$TKT" reduce > "$OUT/tk-$1.log" \
		|| die "the tick trace of $1 was refused (see the message above) -- the run stops here"
}

cleanup() {
	say "cleanup"
	if [ "$INST_MADE" = 1 ]; then
		tsu "cd '$INST' && echo 0 > tracing_on" 2>/dev/null
		tk_events 0 2>/dev/null
		tsu "rmdir '$INST'" 2>/dev/null || { sleep 1; tsu "rmdir '$INST'" 2>/dev/null; } \
			|| echo "WARNING: could not remove the ftrace instance $INST" >&2
	fi
	if [ "$CONF_TOUCHED" = 1 ]; then
		set_units 0-5 2>/dev/null
		for u in $UNITS; do sudo -n rm -f "/run/systemd/system.control/$u.d/50-AllowedCPUs.conf"; sudo -n rmdir "/run/systemd/system.control/$u.d" 2>/dev/null; done
		sudo -n systemctl daemon-reload
		[ "$(allowed "$(pgrep -o -x systemd-udevd)")" = 0-5 ] && say "the units are back on 0-5, drop-ins removed" \
			|| echo "WARNING: udevd is not on 0-5 -- restore by hand: sudo systemctl set-property --runtime <unit> AllowedCPUs=0-5 for $UNITS" >&2
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
for f in "$PROBE" "$TJT" "$TKT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
tsu "test -d '$TRACE/instances' && test ! -e '$INST'" || die "no $TRACE/instances, or $INST exists -- someone else is tracing"
for c in $(cores_of "$QEMU_CORES,$CORE_PROBE"); do TK_MASK=$(( ${TK_MASK:-0} | (1 << c) )); done
TK_MASK="$(printf %x "$TK_MASK")"
ME="$(basename "$(cut -d: -f3 /proc/self/cgroup)")"
case "$ME" in session-*.scope) ;; *) die "the harness is not in a session scope ($ME)" ;; esac
UNITS="system.slice init.scope $(systemctl list-units 'user@*.service' --no-legend | awk '{print $1}') $(systemctl list-units --type=scope --state=running --no-legend | awk '{print $1}' | grep '^session-' | grep -vx "$ME")"
for u in $UNITS; do
	case "$(systemctl show -p AllowedCPUs --value "$u")" in ""|0-5) ;; *) die "$u already has AllowedCPUs set -- someone else changed it" ;; esac
done
for s in /proc/[0-9]*/task/[0-9]*/status; do
	c="$(awk '/^Cpus_allowed_list/ {print $2}' "$s" 2>/dev/null)"
	[ -n "$c" ] && [ "$c" != 0-5 ] || continue
	d="${s%/status}"
	cg="$(cut -d: -f3 "$d/cgroup" 2>/dev/null)"
	case "$cg" in /|*"$ME"*|"") ;; *) die "a task in $cg has CPU affinity $c: restoring 0-5 would lose it" ;; esac
done
sudo -n journalctl -n 1 -u ssh > /dev/null || die "sudo -n journalctl does not work: logins could not be counted"
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat "$z/type" 2>/dev/null)" = "$ZONE_TYPE" ] && { TZ="$z"; break; }
done
[ -n "$TZ" ] || die "no thermal zone of type $ZONE_TYPE"
[ -r /sys/kernel/uevent_seqnum ] || die "no /sys/kernel/uevent_seqnum"
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

m_prepare_out "${OUT:-}" "$HOME/tick-out"
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
tsu "cd '$INST' && echo 0 > tracing_on && echo mono > trace_clock && echo $TK_KB > buffer_size_kb && echo $TK_MASK > tracing_cpumask" \
	|| die "could not set up $INST"
[ "$(tsu "cat '$INST/options/overwrite'")" = 1 ] || die "$INST/options/overwrite is not 1: lost events would not show"
for e in $TKEVENTS; do tsu "test -w '$INST/events/$e/enable'" || die "no writable $e event under $INST"; done

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "tick"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"confinement\": \"every round: units $UNITS on AllowedCPUs=$CONF_CORES; nothing injected; zone $ZONE_TYPE ($(basename "$TZ")); rounds in the pattern ${CPAT[*]}\"" \
	"\"tick_trace\": \"instance tickwork on cores $QEMU_CORES,$CORE_PROBE (tracing_cpumask $TK_MASK) in heavy rounds: $TKEVENTS, mono clock, buffer $TK_KB KB per core, reduced by tick_trace.py (sha256 $(_sha "$TKT"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, nothing injected, userspace confined every round ($UNITS), light/heavy trace -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	arm="${CPAT[$(( (r - 1) % ${#CPAT[@]} ))]}"
	echo "round $r arm: $arm" >> "$OUT/order.log"
	set_units "$CONF_CORES" || die "could not set the units for round $r"
	repin_qemu || die "could not pin QEMU back to $QEMU_CORES for round $r"
	sleep 1
	echo "round $r before $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	seq0="$(cat /sys/kernel/uevent_seqnum)"
	if [ "$arm" = heavy ]; then ls "/proc/$QPID/task" > "$OUT/qtids-t2ms_r$r.txt"; tk_start; fi
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	echo "round $r seqnum $seq0 $(cat /sys/kernel/uevent_seqnum)" >> "$OUT/seqnum.log"
	trace_take "t2ms_r$r"
	if [ "$arm" = heavy ]; then
		tk_take "t2ms_r$r"
		ls "/proc/$QPID/task" >> "$OUT/qtids-t2ms_r$r.txt"
	fi
	echo "round $r after $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
set_units 0-5 || die "could not set the units back to 0-5"
for u in $UNITS; do sudo -n rm -f "/run/systemd/system.control/$u.d/50-AllowedCPUs.conf"; sudo -n rmdir "/run/systemd/system.control/$u.d" 2>/dev/null; done
sudo -n systemctl daemon-reload
CONF_TOUCHED=0
[ "$(allowed "$(pgrep -o -x systemd-udevd)")" = 0-5 ] || die "udevd is not back on 0-5 after the run"
say "the units are back on 0-5, drop-ins removed"
tsu "rmdir '$INST'" || { sleep 1; tsu "rmdir '$INST'"; } || die "could not remove the ftrace instance $INST"
INST_MADE=0
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "confined to 3 and 5: is the tail that is left the tick?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
