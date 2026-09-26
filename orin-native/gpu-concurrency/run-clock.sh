#!/usr/bin/env bash
# run-clock.sh -- the intervention on the guest's own timer: the same guest with its QNX tick
# at 1 kHz (the default) or 100 Hz, alternated by guest boot within one board boot. Phase 3b /
# A6, 2026-09-26; follows 20260925T-a6-orin-guesttick. The owner asked for this test
# (2026-09-26), including the new guest image it needs; it changes systemd settings at
# runtime, restored after, and never touches the board's own boot.
#
# WHAT IS KNOWN. With the host's userspace confined, the guest's own timer firing 25-150 us
# into an exchange makes it 16.7x as likely to be in the tail and +12.8 us slower, and with
# the host's tick it covers about half the confined tail (20260925T-a6-orin-guesttick). That
# was observed, not intervened on. QNX OS 8.0 cannot change its clock period at run time
# (ClockPeriod() returns ENOTSUP when asked to set it; checked on this guest 2026-09-26); the
# tick is fixed at boot by procnto -C, and it is the granularity of every ordinary timer.
# So there are two images, identical but for procnto's -C (compare-ifs.py, 2026-09-26):
#   A  ifs-clock.bin     1 kHz, the default (ifs-stamp.bin plus qnx-clockctl, which reads
#                        the period back)
#   B  ifs-clock100.bin  -C 100: a 10 ms tick
# FEASIBILITY, before this was written (not a test, four guest boots, no confinement): with
# the governor pinned and c7 off, the probe at 2 ms saw 422-888 guest-timer events/s with A
# and 0-77 with B -- the manipulation takes -- but B was also SLOWER for the typical exchange:
# p50 254-270 us against 186-190 us. The likely reason, not verified: the 1 kHz tick keeps
# waking the vCPUs, so a request more often finds one still in KVM's halt-poll window; at
# 100 Hz every exchange pays the wake from a blocked halt (32-36 us of p50 on this host,
# 20260924T-a6-orin-haltpoll). So the tick has two effects, and P2 and P3 below were written
# after seeing that feasibility run: they are not blind.
#
# THE RUN. One board boot. The harness boots the guest itself (launch-qnx-kvm-bridged.sh,
# in its own session scope), eight guest boots in the pattern A B B A A B B A, K_PER_GUEST
# (5) rounds each: k = 40 rounds, 20 per arm, n = 1000, 200 warm-up, t2ms, nothing injected.
# Each guest boot: the stamping monitor on :7103 and qnx-clockctl on :7110 checked on its
# console, and qnx-clockctl `get` must read 1000000 ns (A) or 10000000 ns (B) (guests.log).
# Between guest boots: sync, then QEMU is stopped and the next image booted (a kernel panic
# in QEMU's teardown once lost unflushed files, 20260925T-a6-orin-boots2). EVERY round
# confined as run-tick.sh's (system.slice, init.scope, user@1000.service and every session
# scope but the harness's own on AllowedCPUs=3,5; QEMU re-pinned to QEMU_CORES), with the
# light trace, the guest-timer trace of run-guesttick.sh (the "kvm guest vtimer" IRQ and
# kvm_bg_timer_expire, filtered in the kernel) and KVM's halt counters (kvm-*.json).
#
# THE RULE, fixed here before any run (clock_report.py applies it):
#   - alignment and classes are run-tick.sh's; TAIL is at or above the round's p99 over all
#     its timed exchanges; below, out-class exchanges;
#   - GUESTSHARE(arm) = the share of the arm's out-class tail exchanges whose first guest
#     event at or after t0 comes within 150 us, pooled over the arm's rounds;
#   - P50(arm) = the median of the arm's round p50s (all timed exchanges);
#   - POLL(arm) = the median over the arm's rounds of halt_successful_poll /
#     halt_attempted_poll, as counted by KVM during the round (kvm-*.json after - before);
#   - EVENTS(arm) = the median over the arm's rounds of the guest events in the round.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included, and after the feasibility run above. It is not to be amended. H: the guest's
# tick is causal for the part of the tail it coincides with, and it also keeps the vCPUs
# warm: with a 10 ms tick the tail meets it far less, and the typical exchange is slower
# because its vCPUs are found blocked, not polling.
#   P1 the tail meets the guest's timer far less: GUESTSHARE(B) <= 0.5 x GUESTSHARE(A).
#   P2 the typical exchange is slower with the 10 ms tick: P50(B) - P50(A) >= +30 us.
#   P3 because KVM's halt polling succeeds less: POLL(B) <= 0.5 x POLL(A).
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 >= 90% of rounds align -> all
#   M2 every round confined (udevd, PID 1, gnome-shell on 3,5) and QEMU's threads on 0-2,
#      before and after -> all
#   M3 no SSH login during the rounds -> all
#   M4 the manipulation took: every guest boot's qnx-clockctl read its arm's period, and
#      EVENTS(B) <= EVENTS(A) / 3 -> all
#   M5 eight guest boots in the pattern, 20 rounds per arm -> all
# Scored only at k = 40.
#
# NEEDS: NO guest running (the harness boots its own); IMG_A and IMG_B (defaults
# ~/output/ifs-clock.bin and ifs-clock100.bin) and DISK. c7 OFF (CSTATE=shallow, set before
# the library). NO LOAD. A STALL STOPS THE RUN.
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
K_PER_GUEST="${K_PER_GUEST:-5}"
GPAT=(A B B A A B B A)
K=$(( K_PER_GUEST * ${#GPAT[@]} ))
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
SEED="${SEED:-24}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/clock_report.py}"
TKT="${TKT:-$here/tick_trace.py}"
CONF_CORES="${CONF_CORES:-3,5}"
TRACE="${TRACE:-/sys/kernel/tracing}"
TRACE_KB="${TRACE_KB:-2048}"
TK_KB="${TK_KB:-1024}"
INST="$TRACE/instances/guestclock"
IMG_A="${IMG_A:-$HOME/output/ifs-clock.bin}"
IMG_B="${IMG_B:-$HOME/output/ifs-clock100.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
CLOCK_PORT="${CLOCK_PORT:-7110}"
GUEST_ON=0
ZONE_TYPE=tj-thermal
CONSOLE=""   # per guest boot: $OUT/guest-gN.log
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

period_want() { case "$1" in A) echo 1000000 ;; B) echo 10000000 ;; esac; }

clock_get() {   # the guest's clock period, read back by qnx-clockctl
	python3 -c "import socket,sys; s=socket.create_connection((sys.argv[1], int(sys.argv[2])), 5); s.sendall(b'get\\n'); print(s.recv(100).decode().strip())" "$GUEST" "$CLOCK_PORT"
}

guest_start() {   # $1 A|B  $2 guest boot number
	local img got
	case "$1" in A) img="$IMG_A" ;; B) img="$IMG_B" ;; *) die "no arm $1" ;; esac
	CONSOLE="$OUT/guest-g$2.log"
	IFS_BIN="$img" DISK="$DISK" LOG="$CONSOLE" bash "$here/launch-qnx-kvm-bridged.sh" > "$OUT/launch-g$2.log" 2>&1 < /dev/null \
		|| die "the guest (image $1) would not boot -- see $OUT/launch-g$2.log"
	GUEST_ON=1
	m_pin_qemu "$QEMU_CORES"
	m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
	tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
		|| die "guest boot $2 shows no stamping monitor on :$D_PORT"
	tr -d '\0\r' < "$CONSOLE" | grep -aqF "clockctl: listening on :$CLOCK_PORT" || die "guest boot $2 shows no qnx-clockctl"
	got="$(clock_get)" || die "qnx-clockctl did not answer in guest boot $2"
	echo "guest $2 arm $1 image $(basename "$img") sha256 $(sha256sum "$img" | cut -c1-16) clockctl $got want $(period_want "$1")" >> "$OUT/guests.log"
	[ "$got" = "period $(period_want "$1")" ] || die "guest boot $2 ($1) reads '$got', not period $(period_want "$1")"
}

guest_stop() {   # sync first: a panic in QEMU's teardown once lost unflushed files
	local i
	[ "$GUEST_ON" = 1 ] || return 0
	sync
	sudo -n kill "$QPID" 2>/dev/null
	for i in $(seq 1 20); do [ -d "/proc/$QPID" ] || break; sleep 1; done
	[ -d "/proc/$QPID" ] && return 1
	GUEST_ON=0
	sync
}

cleanup() {
	say "cleanup"
	guest_stop || echo "WARNING: QEMU $QPID did not stop" >&2
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
for f in "$PROBE" "$TJT" "$TKT" "$REPORT" "$IMG_A" "$IMG_B" "$DISK" "$here/launch-qnx-kvm-bridged.sh"; do [ -r "$f" ] || die "missing: $f"; done
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a guest is already running -- this harness boots its own"
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

m_prepare_out "${OUT:-}" "$HOME/clock-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
guest_start "${GPAT[0]}" 1
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
	'"experiment": "clock"' \
	"\"images\": {\"A\": \"$(basename "$IMG_A") sha256 $(sha256sum "$IMG_A" | cut -c1-16), 1 kHz\", \"B\": \"$(basename "$IMG_B") sha256 $(sha256sum "$IMG_B" | cut -c1-16), 100 Hz\", \"pattern\": \"${GPAT[*]}\", \"rounds_per_guest\": $K_PER_GUEST}" \
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
say "k=$K rounds of t2ms in guest boots ${GPAT[*]} x $K_PER_GUEST, n=$N, warmup=$WARMUP, userspace confined every round ($UNITS) -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
r=0
for g in $(seq 1 "${#GPAT[@]}"); do
arm="${GPAT[$((g - 1))]}"
if [ "$g" -gt 1 ]; then
	guest_stop || die "QEMU would not stop after guest boot $((g - 1))"
	guest_start "$arm" "$g"
fi
for j in $(seq 1 "$K_PER_GUEST"); do
	r=$((r + 1))
	echo "round $r arm: $arm guest $g" >> "$OUT/order.log"
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
	say "round $r/$K done (guest $g, $arm)"
done
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
say "the guest's tick at 1 kHz and 100 Hz: what changes?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
