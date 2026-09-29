#!/usr/bin/env bash
# run-wifi.sh -- with the host's userspace confined, is part of the remaining tail the Wi-Fi?
# Phase 3b / A6, 2026-09-29; follows 20260929T-a6-orin-irqconf. The owner asked for this test
# (2026-09-29) knowing it switches the board's Wi-Fi radio off and on at runtime, restored
# after; the LAN and this harness's own SSH are on the Ethernet.
#
# WHAT IS KNOWN. Confined, part of the tail meets neither the host tick bin nor a guest timer
# during the exchange: record 20260925T-a6-orin-guesttick (held locally). In record
# 20260929T-a6-orin-irqconf (held locally) that residual went with device interrupts on
# QEMU's cores on new data, and read afterwards (unscored) most of that association was the
# Wi-Fi's rtl88x2ce; moving every movable interrupt off QEMU's and the probe's cores barely
# changed the tail. So where the Wi-Fi's interrupt runs is not the lever; whether its
# activity is, is untested. The Wi-Fi is up but carries no LAN traffic: the Ethernet is the
# default route since 2026-09-26.
#
# THE RUN. One boot of the stamping guest (ifs-stamp.bin, :7103). k = 40 rounds. Each round
# confines the host's userspace as run-guesttick.sh does (system.slice, init.scope,
# user@1000.service and every session scope but the harness's own on AllowedCPUs=3,5, QEMU
# re-pinned to QEMU_CORES and checked, the allowed CPUs logged before and after), then runs
# two arms of t2ms (two vCPUs, halt_poll_ns 500000, 2 ms spacing, n = 1000 after 200
# warm-up), in AB/BA order: odd rounds on then off, even rounds off then on.
#   on   the Wi-Fi radio unblocked and NetworkManager connected; after unblocking, the
#        harness waits for the connection and then SETTLE_ON seconds before the arm
#   off  the Wi-Fi's rfkill switch soft-blocked (the kernel downs the interface), then
#        SETTLE_OFF seconds before the arm
# The radio changes only when the next arm needs the other state, so once per round.
# Interrupt affinities are left alone. Every arm has the light trace (frames into tap-qnx,
# thermal reads; tjphase_trace.py) and an ftrace instance on QEMU's and the probe's cores
# with irq_handler_entry (every hard interrupt, unfiltered) and hrtimer_expire_entry
# filtered to kvm_bg_timer_expire (its address read from /proc/kallsyms, never recorded),
# reduced by tick_trace.py. The Wi-Fi interrupt's per-core counts and the radio's state are
# read just before and after every arm. SSH logins accepted during the rounds are counted
# from the journal. The radio is unblocked and reconnected at the end.
#
# THE RULE, fixed here before any run (wifi_report.py applies it):
#   - per arm-round: p50, p99 and p99.9 of its n timed exchanges; DIFF(q) is off minus on in
#     the same round, and a verdict uses the median of DIFF over the rounds;
#   - EXCESS is the share of off's exchanges, pooled over the rounds, at or above the pooled
#     p99 of on's (on's own share is about 1% by construction);
#   - in on arms only: alignment and the out-class are run-tick.sh's; RESIDUAL is an
#     out-class exchange outside the tick bin whose first guest timer event at or after t0
#     is not in [25, 150) us after it (run-guesttick.sh's DURING); TAIL is at or above its
#     arm-round's p99; a residual exchange is WIFI when the Wi-Fi's hard interrupt starts on
#     QEMU's or the probe's cores in [t0 - 500 us, t0 + its round trip]; LIFT is WIFI's share
#     among residual tail exchanges over its share among the other residual exchanges.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: confined, part of the remaining tail is the Wi-Fi's
# activity; with its radio off that part goes and the median stays.
#   P1 p99 falls: median DIFF(p99) <= -3 us. REFUTED if >= 0; between, PARTIAL.
#   P2 fewer slow exchanges: EXCESS <= 0.8%. REFUTED if >= 1.0%; between, PARTIAL.
#   P3 (control) the median does not move: |median DIFF(p50)| <= 2 us.
#   P4 (irqconf's association, on new data) in on, the Wi-Fi's interrupt goes with the
#      residual tail: LIFT >= 3. REFUTED if <= 1.5; between, PARTIAL.
# NOT PREDICTED: DIFF(p99.9), printed.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 every arm-round complete (m_require_complete), and >= 90% of on arm-rounds align -> all
#   M2 every round confined (udevd, PID 1, gnome-shell on 3,5) and QEMU's threads on 0-2,
#      before and after -> all
#   M3 no SSH login was accepted during the rounds -> all
#   M4 the switch took: every off arm-round soft-blocked before and after, with the Wi-Fi's
#      interrupt firing at most twice in all on any core; every on arm-round connected before
#      and after, the interrupt firing, median >= 5 per arm-round -> all
#   M5 sizes: >= 100 residual tail exchanges and >= 50 WIFI residual exchanges in on (the
#      classes' sizes, not the tail's composition, which is what P4 measures) -> P4
# Scored only at k = 40.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log). c7 OFF
# (CSTATE=shallow, set before the library). NO LOAD. This SSH session NOT on the Wi-Fi. A
# STALL STOPS THE RUN.
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
SEED="${SEED:-29}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
WIFI_IF="${WIFI_IF:-wlP1p1s0}"
SETTLE_ON="${SETTLE_ON:-20}"
SETTLE_OFF="${SETTLE_OFF:-3}"
CONNECT_S="${CONNECT_S:-90}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/wifi_report.py}"
TKT="${TKT:-$here/tick_trace.py}"
CONF_CORES="${CONF_CORES:-3,5}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
TK_KB="${TK_KB:-2048}"
INST="$TRACE/instances/wifi"
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
ARMS=(on off)
STAMP_ARMS="on off"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
TEVENTS="net/net_dev_xmit thermal/thermal_temperature"
TKEVENTS="irq/irq_handler_entry timer/hrtimer_expire_entry"
TZ=""; CONF_TOUCHED=0; UNITS=""; INST_MADE=0; TK_MASK=""
TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_KB_BEFORE=""; TRACE_TOUCHED=0
RFK=""; WIFI_IRQ=""; WIFI_NAME=""; RADIO=""; RADIO_TOUCHED=0

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

nm_state() {   # the Wi-Fi device's NetworkManager state, e.g. connected, unavailable
	nmcli -t -f DEVICE,STATE device status 2>/dev/null | awk -F: -v d="$WIFI_IF" '$1 == d { print $2; exit }'
}

soft_state() {   # "yes" or "no": the Wi-Fi's rfkill soft block
	cat "/sys/class/rfkill/$RFK/soft" 2>/dev/null | sed 's/^1$/yes/; s/^0$/no/'
}

radio_line() {   # one line for wifi-state.log
	echo "rfkill_soft=$(soft_state) nm=$(nm_state)"
}

radio() {   # $1 = on or off: switch the radio if it is not there already, and wait
	local i
	[ "$RADIO" = "$1" ] && return 0
	RADIO_TOUCHED=1
	if [ "$1" = off ]; then
		sudo -n rfkill block "${RFK#rfkill}" || die "could not soft-block $RFK"
		[ "$(soft_state)" = yes ] || die "$RFK does not read back soft-blocked"
		for i in $(seq 1 20); do
			case "$(nm_state)" in connected*) sleep 1 ;; *) break ;; esac
		done
		case "$(nm_state)" in connected*) die "$WIFI_IF is still connected with its radio blocked" ;; esac
		sleep "$SETTLE_OFF"
	else
		sudo -n rfkill unblock "${RFK#rfkill}" || die "could not unblock $RFK"
		[ "$(soft_state)" = no ] || die "$RFK does not read back unblocked"
		for i in $(seq 1 "$CONNECT_S"); do
			[ "$(nm_state)" = connected ] && break
			sleep 1
		done
		[ "$(nm_state)" = connected ] || die "$WIFI_IF did not reconnect within ${CONNECT_S}s of unblocking"
		sleep "$SETTLE_ON"
	fi
	RADIO="$1"
}

wifi_counts() {   # $1 = file: "irq c0 c1 c2 c3 c4 c5" for the Wi-Fi's interrupt
	awk -v k="$WIFI_IRQ:" '$1 == k { print k, $2, $3, $4, $5, $6, $7 }' /proc/interrupts > "$1"
}

tk_events() {   # $1 = 0 or 1
	local e cmd="cd '$INST'"
	for e in $TKEVENTS; do cmd="$cmd && echo $1 > events/$e/enable"; done
	tsu "$cmd"
}

tk_start() {
	tsu "cd '$INST' && echo 0 > tracing_on && echo > trace" || die "could not clear $INST"
	tk_events 1 || die "could not enable the interrupt and guest timer events"
	tsu "cd '$INST' && echo 1 > tracing_on" || die "could not start the interrupt trace"
}

tk_take() {   # $1 tag
	tsu "cd '$INST' && echo 0 > tracing_on" || die "could not stop the interrupt trace after $1"
	tk_events 0 || die "could not disable the interrupt events after $1"
	tsu "cat '$INST/trace'" | python3 "$TKT" reduce > "$OUT/tk-$1.log" \
		|| die "the interrupt trace of $1 was refused (see the message above) -- the run stops here"
}

cleanup() {
	say "cleanup"
	local i
	if [ "$RADIO_TOUCHED" = 1 ] && [ -n "$RFK" ]; then
		sudo -n rfkill unblock "${RFK#rfkill}" 2>/dev/null
		for i in $(seq 1 "$CONNECT_S"); do [ "$(nm_state)" = connected ] && break; sleep 1; done
		say "the Wi-Fi radio is unblocked again: $(radio_line)"
		[ "$(nm_state)" = connected ] || echo "WARNING: $WIFI_IF has not reconnected -- check it: nmcli device status" >&2
	fi
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

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2"
	radio "$a"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	echo "round $r $a before $(radio_line)" >> "$OUT/wifi-state.log"
	wifi_counts "$OUT/wifi-$t.before"
	tk_start
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "$t" "$GUEST" "$D_PORT"
	trace_take "$t"
	tk_take "$t"
	wifi_counts "$OUT/wifi-$t.after"
	echo "round $r $a after $(radio_line)" >> "$OUT/wifi-state.log"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" "$a"
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
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$TJT" "$TKT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
command -v rfkill > /dev/null && command -v nmcli > /dev/null || die "rfkill and nmcli are both needed"
[ -d "/sys/class/net/$WIFI_IF/phy80211" ] || die "$WIFI_IF is not a wireless interface"
PHY="$(cat "/sys/class/net/$WIFI_IF/phy80211/name")"
for d in /sys/class/rfkill/rfkill*; do
	[ "$(cat "$d/name" 2>/dev/null)" = "$PHY" ] && { RFK="$(basename "$d")"; break; }
done
[ -n "$RFK" ] || die "no rfkill switch named $PHY for $WIFI_IF"
[ "$(cat "/sys/class/rfkill/$RFK/hard" 2>/dev/null)" = 0 ] || die "$RFK is hard-blocked"
[ "$(soft_state)" = no ] || die "$RFK is already soft-blocked: the Wi-Fi is off before the run"
[ "$(nm_state)" = connected ] || die "$WIFI_IF is not connected (NetworkManager: '$(nm_state)')"
RADIO=on
WIFI_NAME="$(basename "$(readlink -f "/sys/class/net/$WIFI_IF/device/driver")")"
WIFI_IRQ="$(awk -v n="$WIFI_NAME" '$NF == n { sub(":", "", $1); print $1; exit }' /proc/interrupts)"
case "$WIFI_IRQ" in ''|*[!0-9]*) die "no interrupt named $WIFI_NAME in /proc/interrupts" ;; esac
SSH_SERVER_IP="$(echo "${SSH_CONNECTION:-}" | awk '{print $3}')"
[ -n "$SSH_SERVER_IP" ] || die "not started over SSH: the check that this session is not on the Wi-Fi cannot run"
ip -4 -o addr show dev "$WIFI_IF" | grep -qw "$SSH_SERVER_IP" && die "this SSH session arrives on $WIFI_IF: switching its radio off would cut it"
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

m_prepare_out "${OUT:-}" "$HOME/wifi-out"
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
BG="$(sudo -n grep -w kvm_bg_timer_expire /proc/kallsyms | awk '{print $1; exit}')"
case "$BG" in ''|*[!0-9a-f]*) die "no kvm_bg_timer_expire in /proc/kallsyms" ;; esac
tsu "cd '$INST' && echo 0 > events/irq/irq_handler_entry/filter && echo 'function == 0x$BG' > events/timer/hrtimer_expire_entry/filter" \
	|| die "could not set the instance's filters"
[ "$(tsu "cat '$INST/events/irq/irq_handler_entry/filter'")" = none ] || die "irq_handler_entry has a filter left in $INST"
[ "$(tsu "cat '$INST/events/timer/hrtimer_expire_entry/filter'")" = "function == 0x$BG" ] || die "the kvm_bg_timer_expire filter did not take"
BG=""   # the address stays out of every file

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "wifi"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"wifi\": {\"interface\": \"$WIFI_IF\", \"driver\": \"$WIFI_NAME\", \"irq\": $WIFI_IRQ, \"rfkill\": \"$RFK\", \"settle_on_s\": $SETTLE_ON, \"settle_off_s\": $SETTLE_OFF}" \
	"\"confinement\": \"every round: units $UNITS on AllowedCPUs=$CONF_CORES; zone $ZONE_TYPE ($(basename "$TZ"))\"" \
	"\"order\": \"AB/BA: odd rounds on then off, even rounds off then on\"" \
	"\"irq_trace\": \"instance wifi on cores $QEMU_CORES,$CORE_PROBE (tracing_cpumask $TK_MASK) in every arm: irq_handler_entry unfiltered and hrtimer_expire_entry filtered to kvm_bg_timer_expire, mono clock, buffer $TK_KB KB per core, reduced by tick_trace.py (sha256 $(_sha "$TKT"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["on", "off"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of on and off, n=$N, warmup=$WARMUP, userspace confined every round ($UNITS), the Wi-Fi ($WIFI_IF, irq $WIFI_IRQ) soft-blocked in off -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
: > "$OUT/wifi-state.log"
for r in $(seq 1 "$K"); do
	if [ $((r % 2)) = 1 ]; then order="on off"; else order="off on"; fi
	echo "round $r order: $order" >> "$OUT/order.log"
	set_units "$CONF_CORES" || die "could not set the units for round $r"
	repin_qemu || die "could not pin QEMU back to $QEMU_CORES for round $r"
	sleep 1
	echo "round $r before $(conf_state)" >> "$OUT/confine.log"
	for a in $order; do run_arm "$a" "$r"; done
	echo "round $r after $(conf_state)" >> "$OUT/confine.log"
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
radio on
RADIO_TOUCHED=0
say "the Wi-Fi radio is on again: $(radio_line)"
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
say "confined: is part of the remaining tail the Wi-Fi?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
