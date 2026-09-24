#!/usr/bin/env bash
# run-headless.sh -- does the uevent window, and the background tail, need the
# desktop? The same rounds with the board's desktop running and stopped.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-listeners.
#
# WHAT IS KNOWN. Three uevents on tj-thermal make a slow window of a few ms
# (20260924T-a6-orin-uevent). In it, systemd-udevd does ~87% of the extra CPU work and
# gnome-shell ~13%, and where udevd runs does not matter
# (20260924T-a6-orin-listeners; the 87% is unscored, after leaving out three windows
# the operator's SSH logins had filled). The L4T image on this board runs a full
# desktop: gdm, gnome-shell, Xorg, and services that stop with it.
#
# THE MANIPULATION. `systemctl isolate multi-user.target` stops the desktop and the
# services only graphical.target wants (listed on the board before this was written:
# gdm and the owner's graphical session, accounts-daemon, bluetooth, colord, geoclue,
# nvidia-pva-allowd, packagekit, polkit, power-profiles-daemon, rtkit-daemon,
# switcheroo-control, udisks2, upower); `isolate graphical.target` brings them back.
# udevd, NetworkManager, ssh, nvfancontrol, the user manager and the session scope the
# guest runs in are not stopped. Rounds run in three blocks: the first quarter with the
# desktop (G), the middle half without (H), the last quarter with it again (G), so a
# drift that is linear in time weighs the same on both states. After every switch the
# harness waits for gnome-shell and Xorg to be gone (H) or back (G), then settles (30 s
# after stopping, 90 s after starting: a new session starts its own services), and
# checks the guest still answers. The desktop is brought back at the end and on any
# exit. The owner agreed to this knowing it closes the board's graphical session.
#
# THE RUN. One boot of the stamping guest, one arm of the probe repeated: t2ms, the A6
# default (two vCPUs, halt_poll_ns 500000, 2 ms). In every round uevent_inject.py makes
# three U bursts (three "change" writes to tj-thermal's uevent) and one R (three reads
# of its temp), marked in the light trace of run-uevent.sh (tjphase_trace.py).
# gnome-shell and Xorg are counted before and after every round (states.log). SSH logins
# accepted between the first round's start and the last round's end are counted from
# the journal (logins.txt, a count only): the run must be watched from one session
# opened before it starts.
#
# THE RULE, fixed here before any run (headless_report.py applies it):
#   - alignment and the classes tj, U, R, other, out are run-uevent.sh's;
#   - a class's EXCESS in a state is the median round trip of its exchanges minus the
#     median of that state's out class, pooled over the state's aligned rounds;
#   - a state's BACKGROUND TAIL is the p99 of its out class, pooled.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: udevd, not the desktop, makes the uevent
# window, so it survives without the desktop; the desktop's own background work adds
# to the rest of the tail.
#   P1 the uevent window survives: H's U excess is >= 0.5x G's. REFUTED below.
#   P2 the background tail is lower without the desktop: H's out p99 is <= 0.9x G's.
#      REFUTED above.
#   P3 the poll's own window survives too: H's tj excess is >= 0.5x G's. REFUTED
#      below.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> P1 P2 P3
#   M2 >= 90% of U injections raised the uevent seqnum by >= 3, and >= 90% of R left
#      it -> P1
#   M3 every round's gnome-shell and Xorg counts fit its state, before and after
#      (both > 0 in G, both 0 in H) -> P1 P2 P3
#   M4 the window is there with the desktop: G's U excess is >= +15 us -> P1
#   M5 >= 60 U and >= 40 tj exchanges in each state -> P1 P3
#   M6 no SSH login was accepted during the rounds -> P1 P2 P3
# Scored only at k = 24.
#
# CHANGED AFTER THE SMOKE RUN, BEFORE THE RECORDED ONE (2026-09-24): every isolate
# re-runs the oneshot services multi-user.target wants, nvpmodel.service among them,
# and nvpmodel re-applies power mode 1, which sets the governor back to schedutil. The
# smoke run's end-of-run check caught it ("governor drifted"). So after every switch
# and its settle, the harness now re-pins the governor to performance on every core and
# re-disables the deep idle states it disabled at the start, logs what had drifted
# (switches.log), and stops unless the power mode and cpu0's maximum frequency are
# what they were at the start. Before and after every round it stops unless the
# governor and idle states are still as set. The rule, the checks and the predictions
# are unchanged.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log), the desktop
# running at the start. c7 OFF (CSTATE=shallow, set before the library). NO LOAD.
# A STALL STOPS THE RUN.
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
REPORT="${REPORT:-$here/headless_report.py}"
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
TZ=""; STATE_TOUCHED=0; SETTLE_H="${SETTLE_H:-30}"; SETTLE_G="${SETTLE_G:-90}"
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

desktop_counts() {
	echo "gnome-shell=$(pgrep -c -x gnome-shell || true) xorg=$(pgrep -c -x Xorg || true)"
}

desktop_up() { [ "$(pgrep -c -x gnome-shell || true)" -gt 0 ] && [ "$(pgrep -c -x Xorg || true)" -gt 0 ]; }
desktop_gone() { [ "$(pgrep -c -x gnome-shell || true)" -eq 0 ] && [ "$(pgrep -c -x Xorg || true)" -eq 0 ]; }

set_state() {   # $1 G or H
	local i
	STATE_TOUCHED=1
	if [ "$1" = H ]; then
		say "stopping the desktop (isolate multi-user.target)"
		sudo -n systemctl isolate multi-user.target || die "isolate multi-user.target failed"
		for i in $(seq 1 60); do desktop_gone && break; sleep 1; done
		desktop_gone || die "the desktop is still running 60 s after isolate multi-user.target"
	else
		say "starting the desktop (isolate graphical.target)"
		sudo -n systemctl isolate graphical.target || die "isolate graphical.target failed"
		for i in $(seq 1 120); do desktop_up && break; sleep 1; done
		desktop_up || die "the desktop is not back 120 s after isolate graphical.target"
	fi
	if [ "$1" = H ]; then sleep "$SETTLE_H"; else sleep "$SETTLE_G"; fi
	reapply_conditions "the switch to $1"
	[ -d "/proc/$QPID" ] || die "QEMU ($QPID) is gone after the switch to $1"
	m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor, after the switch to $1"
	say "state $1: $(desktop_counts)"
}

conditions_ok() {
	local c d
	for c in "${!GOV_ORIG[@]}"; do [ "$(cat "$c")" = performance ] || return 1; done
	for d in "${!CSTATE_ORIG[@]}"; do [ "$(cat "$d")" = 1 ] || return 1; done
}

reapply_conditions() {   # $1 label
	local c d now found=""
	for c in "${!GOV_ORIG[@]}"; do
		now="$(cat "$c")"
		[ "$now" = performance ] || found="$found ${c#/sys/devices/system/cpu/}=$now"
		echo performance | sudo tee "$c" > /dev/null
		[ "$(cat "$c")" = performance ] || die "could not re-pin $c after $1"
	done
	for d in "${!CSTATE_ORIG[@]}"; do
		now="$(cat "$d")"
		[ "$now" = 1 ] || found="$found ${d#/sys/devices/system/cpu/}=$now"
		echo 1 | sudo tee "$d" > /dev/null
		[ "$(cat "$d")" = 1 ] || die "could not re-disable $d after $1"
	done
	[ "$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ')" = "$NVP0" ] || die "the power mode changed after $1"
	[ "$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq)" = "$MAXF0" ] || die "cpu0's maximum frequency changed after $1"
	echo "$1: re-pinned and re-disabled; drifted:${found:- nothing}" >> "$OUT/switches.log"
	say "$1: conditions re-applied (drifted:${found:- nothing})"
}

cleanup() {
	say "cleanup"
	[ -n "${IPID:-}" ] && kill "$IPID" 2>/dev/null
	if [ "$STATE_TOUCHED" = 1 ] && ! desktop_up; then
		sudo -n systemctl isolate graphical.target 2>/dev/null
		for i in $(seq 1 120); do desktop_up && break; sleep 1; done
		desktop_up && say "the desktop is back" \
			|| echo "WARNING: the desktop is not back -- start it by hand: sudo systemctl isolate graphical.target" >&2
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
for f in "$PROBE" "$TJT" "$REPORT" "$INJ" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat "$z/type" 2>/dev/null)" = "$ZONE_TYPE" ] && { TZ="$z"; break; }
done
[ -n "$TZ" ] || die "no thermal zone of type $ZONE_TYPE"
[ -r /sys/kernel/uevent_seqnum ] || die "no /sys/kernel/uevent_seqnum"
desktop_up || die "the desktop is not running at preflight ($(desktop_counts)) -- this run starts with it"
[ "$(systemctl is-active graphical.target)" = active ] || die "graphical.target is not active at preflight"
sudo -n systemctl --version > /dev/null || die "sudo -n systemctl does not work"
sudo -n journalctl -n 1 -u ssh > /dev/null || die "sudo -n journalctl does not work: logins could not be counted"
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

m_prepare_out "${OUT:-}" "$HOME/headless-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
NVP0="$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ')"
[ -n "$NVP0" ] || die "cannot read the power mode"
MAXF0="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq)"
: > "$OUT/switches.log"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "headless"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"injector\": \"uevent_inject.py (sha256 $(_sha "$INJ")) on $ZONE_TYPE ($(basename "$TZ")): per round 3 U (3 uevent writes) and 1 R (3 temp reads), slots 0.8 + 0.5 i s + U(0, 0.25) s, seed SEED*100 + round, SEED $SEED\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	"\"states\": \"G = graphical.target (desktop), H = multi-user.target; first quarter G, middle half H, last quarter G; settle $SETTLE_H s after stopping and $SETTLE_G s after starting the desktop\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, 3 U and 1 R injections in each, desktop G/H/G -> $OUT"
prev=G
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
IPID=""
for r in $(seq 1 "$K"); do
	pos=$(( (r - 1) * 4 / K ))
	case "$pos" in 0|3) state=G ;; *) state=H ;; esac
	[ "$state" = "$prev" ] || { set_state "$state"; prev="$state"; }
	echo "round $r state: $state" >> "$OUT/order.log"
	conditions_ok || die "the governor or idle states drifted before round $r"
	echo "round $r before $(desktop_counts)" >> "$OUT/states.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	: > "$OUT/inj-t2ms_r$r.jsonl"
	trace_start
	taskset -c "$CORE_AUX" sudo -n python3 "$INJ" --zone "$TZ" --marker "$TRACE/trace_marker" \
		--log "$OUT/inj-t2ms_r$r.jsonl" --seed $((SEED * 100 + r)) --kinds U,U,U,R &
	IPID=$!
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	wait "$IPID" || die "the injector failed in round $r"
	IPID=""
	[ "$(grep -c . "$OUT/inj-t2ms_r$r.jsonl")" -eq 4 ] || die "the injector logged $(grep -c . "$OUT/inj-t2ms_r$r.jsonl") injections in round $r, not 4"
	trace_take "t2ms_r$r"
	conditions_ok || die "the governor or idle states drifted during round $r"
	echo "round $r after $(desktop_counts)" >> "$OUT/states.log"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
desktop_up || set_state G
conditions_ok || reapply_conditions "the end of the run"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "does it need the desktop?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
