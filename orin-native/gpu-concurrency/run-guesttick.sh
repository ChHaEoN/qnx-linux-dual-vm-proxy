#!/usr/bin/env bash
# run-guesttick.sh -- with the host's userspace confined, is the rest of the tail the QNX
# guest's own timer firing while an exchange is in the guest? Phase 3b / A6, 2026-09-25;
# follows 20260925T-a6-orin-tick and -partition. The owner asked for this test (2026-09-25)
# knowing it changes systemd settings on the board, at runtime, restored after.
#
# WHAT IS KNOWN. With the host's userspace confined to cores 3 and 5, a quarter of the tail
# is the host's tick (the TICK BIN: requests leaving [3850, 4000) us mod 4000, the host
# tick's 4 ms grid in the trace clock; 20260925T-a6-orin-tick). Outside that bin, tail
# exchanges carry only +3 us more host work on QEMU's and the probe's cores. Looking
# afterwards at that record's heavy rounds -- an exploration, not a test -- the guest's own
# timer shows up in two host events: the hard IRQ "kvm guest vtimer" (the guest's virtual
# timer firing while its vCPU is loaded) and the hrtimer kvm_bg_timer_expire (the same
# timer for a blocked vCPU). Their intervals cluster at whole milliseconds (2, 3, 4, 7 ms),
# at one phase of a 1 ms grid within a round, a phase that drifts ~150 us from round to
# round against the host's NTP-slewed clock. Outside the tick bin, 41.3% of the tail
# exchanges had such an event in [t0, t0 + 250 us] against 6.8% of the others; when the
# first one fell 50-125 us after t0 the tail share was 10-16%, against 0.50% with none;
# after 150 us it was 0.0-0.7%. Those windows were chosen after looking at that record:
# this run tests them on new data.
#
# THE RUN. One boot of the stamping guest, t2ms (the A6 default: two vCPUs, halt_poll_ns
# 500000, 2 ms), k = 40 rounds, n = 1000, 200 warm-up, nothing injected. EVERY round is
# confined as run-tick.sh's: system.slice, init.scope, user@1000.service and every session
# scope but the harness's own on AllowedCPUs=3,5, QEMU re-pinned to QEMU_CORES and checked,
# the allowed CPUs logged before and after (confine.log), everything restored at the end.
# Every round has the light trace (frames into tap-qnx, thermal reads; tjphase_trace.py)
# and an ftrace instance on QEMU's cores and the probe's with ONLY the guest's timer events,
# filtered in the kernel: irq_handler_entry for the "kvm guest vtimer" IRQ (its number read
# from /proc/interrupts) and hrtimer_expire_entry for kvm_bg_timer_expire (its address read
# from /proc/kallsyms, never recorded); tick_trace.py reduces it (tk-t2ms_rN.log). SSH
# logins accepted during the rounds are counted from the journal (logins.txt).
#
# THE RULE, fixed here before any run (guesttick_report.py applies it):
#   - alignment and classes (tj, other, out) are run-tick.sh's; below, only out-class
#     exchanges OUTSIDE the tick bin count; TAIL is at or above the round's p99 (over all
#     the round's timed exchanges);
#   - a GUEST EVENT is either traced event; an exchange's FIRST guest event is the earliest
#     at or after its request's time t0; by that event's offset the exchange is
#       DURING  in [25, 150) us,   AFTER  in [175, 250) us,   NONE  no event in [0, 250) us
#     (others belong to no class);
#   - pooled over the rounds: a class's TAIL SHARE is its tail exchanges over its exchanges;
#     RATIO(class) is its tail share over NONE's; SLOWDOWN is the median round trip of
#     DURING minus NONE's; COVER is the share of all out-class tail exchanges (in the bin
#     or not) that are in the tick bin or DURING.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: most of the confined tail outside the host's tick
# is the guest's own timer firing while the exchange is inside the guest; the timing is
# what matters, so the same event after the exchange is harmless; the two ticks together
# are a large part of the confined tail.
#   P1 DURING exchanges are over-represented in the tail: RATIO(DURING) >= 5.
#   P2 they are slower: SLOWDOWN >= +5 us.
#   P3 the same event after the exchange is harmless: RATIO(AFTER) <= 2.
#   P4 the two ticks together cover much of the tail: COVER >= 0.4.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> all
#   M2 every round confined (udevd, PID 1, gnome-shell on 3,5) and QEMU's threads on 0-2,
#      before and after -> all
#   M3 no SSH login was accepted during the rounds -> all
#   M4 the guest's timer was traced: >= 500 guest events in every round -> all
#   M5 counts: >= 700 DURING exchanges -> P1 P2 P4; >= 500 AFTER exchanges -> P3 (the
#      classes' sizes, not their tail counts, which would fail exactly when there is no
#      effect)
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
REPORT="${REPORT:-$here/guesttick_report.py}"
TKT="${TKT:-$here/tick_trace.py}"
CONF_CORES="${CONF_CORES:-3,5}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
TK_KB="${TK_KB:-1024}"
INST="$TRACE/instances/guesttick"
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
TKEVENTS="irq/irq_handler_entry timer/hrtimer_expire_entry"   # filtered to the guest's timer
TZ=""; CONF_TOUCHED=0; UNITS=""; INST_MADE=0; TK_MASK=""; VT_IRQ=""
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
	tk_events 1 || die "could not enable the guest's timer events"
	tsu "cd '$INST' && echo 1 > tracing_on" || die "could not start the tick trace"
}

tk_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on" || die "could not stop the tick trace after $1"
	tk_events 0 || die "could not disable the tick events after $1"
	tsu "cat '$INST/trace'" | python3 "$TKT" reduce > "$OUT/tk-$1.log" \
		|| die "the guest timer trace of $1 was refused (see the message above) -- the run stops here"
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
VT_IRQ="$(awk -F: '/kvm guest vtimer/ {gsub(/ /, "", $1); print $1; exit}' /proc/interrupts)"
case "$VT_IRQ" in ''|*[!0-9]*) die "no 'kvm guest vtimer' line in /proc/interrupts" ;; esac
BG="$(sudo -n grep -w kvm_bg_timer_expire /proc/kallsyms | awk '{print $1; exit}')"
case "$BG" in ''|*[!0-9a-f]*) die "no kvm_bg_timer_expire in /proc/kallsyms" ;; esac
tsu "cd '$INST' && echo 'irq == $VT_IRQ' > events/irq/irq_handler_entry/filter && echo 'function == 0x$BG' > events/timer/hrtimer_expire_entry/filter" \
	|| die "could not set the guest timer filters"
[ "$(tsu "cat '$INST/events/irq/irq_handler_entry/filter'")" = "irq == $VT_IRQ" ] || die "the vtimer IRQ filter did not take"
[ "$(tsu "cat '$INST/events/timer/hrtimer_expire_entry/filter'")" = "function == 0x$BG" ] || die "the kvm_bg_timer_expire filter did not take"
BG=""   # the address stays out of every file

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "guesttick"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"confinement\": \"every round: units $UNITS on AllowedCPUs=$CONF_CORES; nothing injected; zone $ZONE_TYPE ($(basename "$TZ"))\"" \
	"\"guest_trace\": \"instance guesttick on cores $QEMU_CORES,$CORE_PROBE (tracing_cpumask $TK_MASK) in every round: irq_handler_entry filtered to irq $VT_IRQ (kvm guest vtimer) and hrtimer_expire_entry filtered to kvm_bg_timer_expire, mono clock, buffer $TK_KB KB per core, reduced by tick_trace.py (sha256 $(_sha "$TKT"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, nothing injected, userspace confined every round ($UNITS), the guest timer traced (irq $VT_IRQ) -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	echo "round $r arm: guest" >> "$OUT/order.log"
	set_units "$CONF_CORES" || die "could not set the units for round $r"
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
say "confined to 3 and 5: is the rest of the tail the guest's own timer?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
