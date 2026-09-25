#!/usr/bin/env bash
# run-metal.sh -- the natural-state confinement test and the tick bin, on a host that is not
# the Orin: AWS a1.metal (16 Cortex-A72, Ubuntu, no desktop, no thermal zone that emits
# uevents). Does the host's tick cost a mid-exchange request there too, and does confining
# the host's userspace change the tail there? Phase 3b / A6, 2026-09-25; follows
# 20260925T-a6-orin-natural and -tick. The owner asked for this session (2026-09-25).
#
# WHAT IS KNOWN, ON THE ORIN. Confining the host's userspace to cores 3 and 5 cut the p99 of
# every exchange from 229.1 to 207.8 us and the p99.9 from 331.6 to 274.9, mostly by moving
# the handling of tj-thermal's uevents (udevd, the desktop) off the exchange's cores
# (20260925T-a6-orin-natural). With everything confined, exchanges whose request left 150
# to 0 us before the host's tick (HZ=250, every core at once) held a quarter of the tail and
# were +11.2 us slower at the median; the tick brings its interrupt and a load-balancing
# softirq to each QEMU core (20260925T-a6-orin-tick). On a1.metal the tail has been far
# quieter than the Orin's (20260923T-a6-a1metal-liveness: the cost resolved through p99.9).
#
# THE MANIPULATION. run-natural.sh's, on this host's cores: one ARM per round, in the pattern
# open confined confined open, repeated;
#   confined  `systemctl set-property --runtime UNIT AllowedCPUs=CONF` for system.slice,
#             init.scope, user@1000.service and every session scope but the harness's own,
#             CONF being every online core but QEMU's and the probe's (on a1.metal 3,5-15);
#   open      the same units on every online core (ALL, on a1.metal 0-15).
# The guest must run in the harness's own session scope (remote-ladder.sh's confine phase
# boots it in the same session), or confining the other scopes would confine QEMU. After
# every switch QEMU's threads are pinned back to QEMU_CORES and checked; the allowed CPUs of
# udevd, PID 1 and QEMU's threads are logged before and after every round (confine.log);
# everything is set back to ALL, the drop-ins removed and systemd reloaded at the end and on
# any exit. Nothing is injected.
#
# THE RUN. One boot of the stamping guest (ifs-stamp.bin), t2ms: two vCPUs, halt_poll_ns as
# the host has it (recorded), 2 ms. k = 40 rounds (20 per arm), n = 1000, 200 warm-up. The
# light trace: frames into tap-qnx, and thermal reads where the host has the event. A second
# ftrace instance on QEMU's cores and the probe's records hrtimer expiries only, for the
# tick's times (tick_trace.py). The tick PERIOD is 1e6/HZ us, HZ read from the running
# kernel's config and recorded. SSH logins accepted during the rounds are counted from the
# journal (logins.txt).
#
# THE RULE, fixed here before any run (metal_report.py applies it):
#   - alignment is run-natural.sh's; exchanges near a thermal read (if any) are left out as
#     there, the rest are the out class;
#   - an out-class exchange is in the TICK BIN when its request's time t0 is in
#     [PERIOD - 150, PERIOD) us mod PERIOD, and TAIL when at or above its round's p99;
#   - pooled over both arms: the bin's tail RATIO (its share of the tail over its share of
#     the exchanges) and SLOWDOWN (its median round trip minus the other exchanges');
#   - per arm, pooled: p50 and p99 over every timed exchange.
#
# THE PREDICTION, written and committed before any run of this harness, rehearsals and
# smoke runs included. It is not to be amended. H: what the tick costs an exchange is a
# property of KVM on arm64 and the host's tick work, so it shows on a1.metal too; what
# confinement gained on the Orin came from a desktop board's uevent handling, which a
# server host does not have, so it gains little here.
#   P1 the tick bin is over-represented in the tail: RATIO >= 2.
#   P2 tick-bin exchanges are slower: SLOWDOWN >= +3 us.
#   P3 confinement changes the tail little: |p99 confined - p99 open| <= 5% of open's.
#   P4 the typical exchange does not change: |p50 confined - p50 open| <= 2 us.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> all
#   M2 every round's allowed CPUs fit its arm: udevd and PID 1 on CONF when confined and
#      on ALL when open, before and after -> all
#   M3 every QEMU thread on QEMU_CORES in every round -> all
#   M4 no SSH login was accepted during the rounds -> all
#   M5 the tick is on the grid: >= 90% of the tick_sched_timer expiries lie within
#      [0, 100) us of a multiple of PERIOD -> P1 P2
#   M6 >= 30 tick-bin tail exchanges -> P1 P2
# Scored only at k = 40.
#
# NEEDS: the guest running in this session's scope (ifs-stamp.bin; CONSOLE its console
# log). c7 OFF where the host has it (CSTATE=shallow, set before the library). NO LOAD.
# A STALL STOPS THE RUN. Rehearse it on the Orin first (TEGRA=0).
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
REPORT="${REPORT:-$here/metal_report.py}"
TKT="${TKT:-$here/tick_trace.py}"
ALL="$(cat /sys/devices/system/cpu/online)"
CONF_CORES="${CONF_CORES:-}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
TK_KB="${TK_KB:-1024}"
INST="$TRACE/instances/metaltick"
ZONE_TYPE="${ZONE_TYPE-}"   # none by default: the tick bin needs no zone
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
TEVENTS="net/net_dev_xmit"   # plus thermal/thermal_temperature where the host has it
TZ=""; CONF_TOUCHED=0; UNITS=""; CPAT=(open confined confined open); INST_MADE=0; TK_MASK=""; HZ=""
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

tk_start() {
	tsu "cd '$INST' && echo 0 > tracing_on && echo > trace && echo 1 > events/timer/hrtimer_expire_entry/enable && echo 1 > tracing_on" \
		|| die "could not start the tick trace"
}

tk_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on && echo 0 > events/timer/hrtimer_expire_entry/enable" || die "could not stop the tick trace after $1"
	tsu "cat '$INST/trace'" | python3 "$TKT" reduce > "$OUT/tk-$1.log" \
		|| die "the tick trace of $1 was refused (see the message above) -- the run stops here"
}

cleanup() {
	say "cleanup"
	if [ "$INST_MADE" = 1 ]; then
		tsu "cd '$INST' && echo 0 > tracing_on && echo 0 > events/timer/hrtimer_expire_entry/enable" 2>/dev/null
		tsu "rmdir '$INST'" 2>/dev/null || { sleep 1; tsu "rmdir '$INST'" 2>/dev/null; } \
			|| echo "WARNING: could not remove the ftrace instance $INST" >&2
	fi
	if [ "$CONF_TOUCHED" = 1 ]; then
		set_units "$ALL" 2>/dev/null
		for u in $UNITS; do sudo -n rm -f "/run/systemd/system.control/$u.d/50-AllowedCPUs.conf"; sudo -n rmdir "/run/systemd/system.control/$u.d" 2>/dev/null; done
		sudo -n systemctl daemon-reload
		[ "$(allowed "$(pgrep -o -x systemd-udevd)")" = "$ALL" ] && say "the units are back on $ALL, drop-ins removed" \
			|| echo "WARNING: udevd is not on $ALL -- restore by hand: sudo systemctl set-property --runtime <unit> AllowedCPUs=$ALL for $UNITS" >&2
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
[ -n "$ALL" ] || die "cannot read the online cores"
if [ -z "$CONF_CORES" ]; then
	CONF_CORES="$(comm -23 <(cores_of "$ALL" | sort) <(cores_of "$QEMU_CORES,$CORE_PROBE" | sort) | sort -n | tr '\n' ',' | sed 's/,$//')"
fi
[ -n "$CONF_CORES" ] || die "no core is left to confine the host's userspace to"
for c in $(cores_of "$QEMU_CORES,$CORE_PROBE"); do TK_MASK=$(( ${TK_MASK:-0} | (1 << c) )); done
TK_MASK="$(printf %x "$TK_MASK")"
HZ="$( { zcat /proc/config.gz 2>/dev/null || cat "/boot/config-$(uname -r)" 2>/dev/null; } | sed -n 's/^CONFIG_HZ=\([0-9]*\)$/\1/p' | head -1)"
case "$HZ" in ''|*[!0-9]*) die "cannot read CONFIG_HZ of the running kernel" ;; esac
tsu "test -d '$TRACE/instances' && test ! -e '$INST'" || die "no $TRACE/instances, or $INST exists -- someone else is tracing"
ME="$(basename "$(cut -d: -f3 /proc/self/cgroup)")"
case "$ME" in session-*.scope) ;; *) die "the harness is not in a session scope ($ME)" ;; esac
UNITS="system.slice init.scope $(systemctl list-units 'user@*.service' --no-legend | awk '{print $1}') $(systemctl list-units --type=scope --state=running --no-legend | awk '{print $1}' | grep '^session-' | grep -vx "$ME")"
for u in $UNITS; do
	case "$(systemctl show -p AllowedCPUs --value "$u")" in ""|"$ALL") ;; *) die "$u already has AllowedCPUs set -- someone else changed it" ;; esac
done
for s in /proc/[0-9]*/task/[0-9]*/status; do
	c="$(awk '/^Cpus_allowed_list/ {print $2}' "$s" 2>/dev/null)"
	[ -n "$c" ] && [ "$c" != "$ALL" ] || continue
	d="${s%/status}"
	cg="$(cut -d: -f3 "$d/cgroup" 2>/dev/null)"
	case "$cg" in /|*"$ME"*|"") ;; *) die "a task in $cg has CPU affinity $c: restoring $ALL would lose it" ;; esac
done
sudo -n journalctl -n 1 -u ssh > /dev/null || die "sudo -n journalctl does not work: logins could not be counted"
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
if [ -n "$ZONE_TYPE" ]; then
	for z in /sys/class/thermal/thermal_zone*; do
		[ "$(cat "$z/type" 2>/dev/null)" = "$ZONE_TYPE" ] && { TZ="$z"; break; }
	done
	[ -n "$TZ" ] || die "no thermal zone of type $ZONE_TYPE"
fi
tsu "test -w '$TRACE/events/thermal/thermal_temperature/enable'" && TEVENTS="$TEVENTS thermal/thermal_temperature"
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

m_prepare_out "${OUT:-}" "$HOME/metal-out"
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
tsu "test -w '$INST/events/timer/hrtimer_expire_entry/enable'" || die "no hrtimer_expire_entry event under $INST"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "metal"' \
	"\"host\": {\"all\": \"$ALL\", \"conf\": \"$CONF_CORES\", \"hz\": $HZ, \"kernel\": \"$(uname -r)\", \"halt_poll_ns\": \"$(cat /sys/module/kvm/parameters/halt_poll_ns 2>/dev/null)\"}" \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"confinement\": \"nothing injected; zone ${ZONE_TYPE:-none}; units $UNITS set to AllowedCPUs=$CONF_CORES (confined) or $ALL (open) per round in the pattern ${CPAT[*]}\"" \
	"\"tick_trace\": \"instance metaltick on cores $QEMU_CORES,$CORE_PROBE (tracing_cpumask $TK_MASK): timer/hrtimer_expire_entry only, mono clock, buffer $TK_KB KB per core, reduced by tick_trace.py (sha256 $(_sha "$TKT"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, nothing injected, userspace on $CONF_CORES or $ALL ($UNITS), HZ $HZ -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	arm="${CPAT[$(( (r - 1) % ${#CPAT[@]} ))]}"
	echo "round $r arm: $arm" >> "$OUT/order.log"
	if [ "$arm" = confined ]; then set_units "$CONF_CORES"; else set_units "$ALL"; fi || die "could not set the units for round $r"
	repin_qemu || die "could not pin QEMU back to $QEMU_CORES for round $r"
	sleep 1
	echo "round $r before $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	seq0="$(cat /sys/kernel/uevent_seqnum)"
	tk_start
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	echo "round $r seqnum $seq0 $(cat /sys/kernel/uevent_seqnum)" >> "$OUT/seqnum.log"
	trace_take "t2ms_r$r"
	tk_take "t2ms_r$r"
	echo "round $r after $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
set_units "$ALL" || die "could not set the units back to $ALL"
for u in $UNITS; do sudo -n rm -f "/run/systemd/system.control/$u.d/50-AllowedCPUs.conf"; sudo -n rmdir "/run/systemd/system.control/$u.d" 2>/dev/null; done
sudo -n systemctl daemon-reload
CONF_TOUCHED=0
[ "$(allowed "$(pgrep -o -x systemd-udevd)")" = "$ALL" ] || die "udevd is not back on $ALL after the run"
say "the units are back on $ALL, drop-ins removed"
tsu "rmdir '$INST'" || { sleep 1; tsu "rmdir '$INST'"; } || die "could not remove the ftrace instance $INST"
INST_MADE=0
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "this host: the tick bin, and what confinement changes"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
