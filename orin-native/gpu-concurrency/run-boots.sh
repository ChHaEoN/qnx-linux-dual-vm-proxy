#!/usr/bin/env bash
# run-boots.sh -- one boot's rounds of the boot-variation test: how much do A6 figures move
# from one boot of the board to the next, against how much they move between rounds of one
# boot? Phase 3b / A6, 2026-09-25; follows 20260925T-a6-orin-partition. The owner asked for
# this test (2026-09-25); it only reboots the board, changing no setting.
#
# WHAT IS KNOWN. Every A6 record is one boot of the guest, most of them one boot of the
# board, and their uncertainty is between-round (20260924T-a6-stats: rounds are the unit,
# between-round variance dominates sampling 9-500x). In the partition test the two boots of
# the SAME default entry, 25 minutes apart, differed by 10 us at p50 (175.7 and 185.7) and
# ~100 us at p99.9 (240.8 and 337.5), while their tick-bin slowdowns agreed (+11.9, +11.0)
# (20260925T-a6-orin-partition). Nothing says whether that was one odd boot or how boots
# vary in general.
#
# THE DESIGN. BOOTS fresh boots of the default entry (the shipped command line), in a
# row, each rebooted into by the orchestrator (partition_cycle.sh's machinery, no boot
# entry touched), each settled SETTLE_S (600) s before its first round; this harness runs
# one boot's rounds and records the boot's tag (b1..b6) and uptime. In every round, the A6
# default as the published records ran it: QEMU's threads on 0-2 as a set, the probe on
# core 4, c7 off, the governor pinned, nothing confined, nothing injected, the stamping
# guest (ifs-stamp.bin) freshly booted in each board boot; the light trace (frames into
# tap-qnx, thermal reads; tjphase_trace.py) so the tick bin can be read. k = 8 rounds per
# boot, n = 1000, 200 warm-up, t2ms. SSH logins accepted during the rounds are counted
# (logins.txt).
#
# THE RULE, fixed here before any run (boots_report.py applies it to the six boots):
#   - per round: p50 and p99 over its timed exchanges;
#   - per boot: the median of its rounds' p50 (BOOT P50) and of their p99 (BOOT P99);
#   - the variance components of the round p50s, one-way random effects over boots:
#     WITHIN = the mean square within boots; BETWEEN = (the mean square between boots -
#     WITHIN) / k, floored at 0; ICC = BETWEEN / (BETWEEN + WITHIN); the same for p99;
#   - per boot, the tick-bin SLOWDOWN (run-tick.sh's bin, out-class exchanges).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: the boot is a real factor for the level of the
# figures -- the partition test's 10 us was not one odd boot -- while the tick's cost, a
# property of the kernel and the hardware, does not move with it.
#   P1 boots differ at p50: max BOOT P50 - min BOOT P50 >= 5 us.
#   P2 the boot outweighs the round at p50: ICC(p50) >= 0.5.
#   P3 boots differ in the tail too: max BOOT P99 - min BOOT P99 >= 10 us.
#   P4 the tick's cost does not move with the boot: max - min per-boot SLOWDOWN <= 4 us.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of each boot's rounds align -> all
#   M2 six boots b1..b6, each settled (uptime >= 600 s at its first round), each on the
#      shipped command line (no isolcpus=, no irqaffinity=) -> all
#   M3 no SSH login during any boot's rounds -> all
#   M4 every round's QEMU threads on 0-2, before and after (confine.log); the governor is
#      re-checked by the harness itself, which stops if it moved -> all
#   M5 >= 10 tick-bin tail exchanges in every boot -> P4
# Scored only with six boots at k = 8.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log). c7 OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN. BOOT_TAG one of
# b1..b6.
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
K="${K:-8}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
SEED="${SEED:-24}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/boots_report.py}"
BOOT_TAG="${BOOT_TAG:?set BOOT_TAG to b1..b6}"
SETTLE_S="${SETTLE_S:-600}"
CONF_CORES="${CONF_CORES:-3,5}"
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
TZ=""; CONF_TOUCHED=0; UNITS=""; UPTIME0=""
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

cleanup() {
	say "cleanup"
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
for f in "$PROBE" "$TJT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
case "$BOOT_TAG" in b[1-6]) ;; *) die "BOOT_TAG '$BOOT_TAG' is not b1..b6" ;; esac
[ "$(tr ' ' '\n' < /proc/cmdline | grep -cE '^(isolcpus|irqaffinity)=')" = 0 ] || die "this boot is not on the shipped command line"
UPTIME0="$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)"
[ "$UPTIME0" -ge "$SETTLE_S" ] || die "the boot is ${UPTIME0} s old, under SETTLE_S=$SETTLE_S: let it settle"
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

m_prepare_out "${OUT:-}" "$HOME/boots-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "boots"' \
	"\"boot_tag\": \"$BOOT_TAG\"" \
	"\"boot\": \"cmdline isolcpus/irqaffinity: $(tr ' ' '\n' < /proc/cmdline | grep -cE '^(isolcpus|irqaffinity)=') token(s); uptime at preflight ${UPTIME0} s\"" \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"confinement\": \"none: every unit as the boot left it; nothing injected; zone $ZONE_TYPE ($(basename "$TZ"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "boot $BOOT_TAG: k=$K rounds of t2ms, n=$N, warmup=$WARMUP, nothing injected or confined -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	echo "round $r arm: default" >> "$OUT/order.log"
	echo "round $r before $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	seq0="$(cat /sys/kernel/uevent_seqnum)"
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	echo "round $r seqnum $seq0 $(cat /sys/kernel/uevent_seqnum)" >> "$OUT/seqnum.log"
	trace_take "t2ms_r$r"
	echo "round $r after $(conf_state)" >> "$OUT/confine.log"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "boot $BOOT_TAG done; the report needs all six boots: boots_report.py b1 .. b6"
python3 "$REPORT" --one "$OUT" "$N" "$WARMUP" || die "the one-boot report could not be made -- see above"
