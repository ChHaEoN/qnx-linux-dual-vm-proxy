#!/usr/bin/env bash
# run-walks.sh -- is udevd's path walking in sysfs what makes the slow window? Bursts that
# do what udevd does per uevent, without a uevent. Phase 3b / A6, 2026-09-24; follows
# 20260924T-a6-orin-queue.
#
# WHAT IS KNOWN. Holding udevd's exec queue removes ~75% of the uevents' slow window
# (20260924T-a6-orin-queue), so most of it is udevd processing the events. Generic
# compute, broadcast TLB flushes and getppid() on another core make no window; memcpy
# through 64 MB makes a third of one (20260924T-a6-orin-bursts).
#
# WHERE THE PREDICTION COMES FROM (looked at on the board before this was written, with
# no guest running, and stated so it is not mistaken for a blind test):
#   - an ftrace of every core's syscalls, forks, page allocations, block I/O, journal
#     commits and work items, in the 8 ms after three uevents against after an empty
#     marker: udevd makes ~400 syscalls per burst of three (114 openat, 111 close, 108
#     newfstatat, 33 faccessat, a few reads, writes and unlinks), and forks nothing,
#     allocates no pages and does no block I/O;
#   - uprobes on libc's openat, open64, fstatat, faccessat and readlinkat (no kprobe
#     events on this kernel): the opens are systemd's component-by-component path walk
#     (openat(fd, "sys"), "devices", "virtual", "dmi", "id", ... each O_PATH, each
#     followed by fstatat(fd, "", AT_EMPTY_PATH)), and the files are
#     /sys/devices/virtual/dmi/id/sys_vendor (gdm's rules, twice per event), the
#     device's uevent and driver link, and udevd's own files in /run/udev;
#   - built and run by hand on the board, burst_inject.c's P makes 59 such sysfs walks
#     in 3 ms, F 61 through tmpfs, and A 202 reads of sys_vendor.
#
# THE MANIPULATION (burst_inject.c, built on the board, run as root on the aux core,
# CORE_AUX 5, during each round). Five injections per round in a seeded order, at 0.75
# + 0.35 i s + U(0, 0.1) s into the round, each marked in the trace just before:
#   U  three "change" writes to tj-thermal's uevent file (the control)
#   N  nothing (the null control)
#   P  3 ms of udevd's walk to /sys/devices/virtual/dmi/id/sys_vendor, component by
#      component, O_PATH and fstatat as systemd does, again and again
#   F  3 ms of the same walk through tmpfs (/run/tjinj-walk/a/b/c/d, made before the round)
#   A  3 ms of open, read, close of /sys/devices/virtual/dmi/id/sys_vendor
# Nothing on the board is changed but /run/tjinj-walk, which is removed at the end.
#
# THE RUN. As run-bursts.sh: one boot of the stamping guest, t2ms (the A6 default), the
# light trace with the markers, SSH logins counted from the journal.
#
# THE RULE, fixed here before any run (walks_report.py applies it): as run-bursts.sh's,
# with the kinds U N P F A: tj first, then each kind's -0.5..+8 ms window, other, out; a
# class's EXCESS is its median round trip minus the out class's median.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: udevd's walking of sysfs paths is what slows the
# guest, and it is specific to sysfs.
#   P1 the sysfs walk makes a window: P's excess is >= +20 us. PARTIAL at +10 to +20.
#      REFUTED below +10.
#   P2 the same walk on tmpfs does not: F's excess is below +10 us. REFUTED at +10 or
#      more.
#   P3 sysfs attribute reads make a window: A's excess is >= +20 us. PARTIAL at +10 to
#      +20. REFUTED below +10.
#   P4 the uevents still make it (the control): U's excess is >= +20 us. REFUTED below.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of rounds align -> all
#   M2 >= 90% of U injections raised the uevent seqnum by >= 3, and >= 90% of the others
#      left it -> all
#   M3 >= 90% of the logged injections have their marker in the traces -> all
#   M4 >= 50 exchanges in each injection class -> all
#   M5 each burst ran its length: P, F and A have median durations of 2.5-3.6 ms, and
#      every burst did at least one iteration -> P1-P3
#   M6 no SSH login was accepted during the rounds -> all
#   M7 the null windows are quiet: N's excess is within +-10 us -> P1-P3
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
REPORT="${REPORT:-$here/walks_report.py}"
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
	rm -f "$INJ"
	sudo -n rm -rf /run/tjinj-walk
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

m_prepare_out "${OUT:-}" "$HOME/walks-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "walks"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"injector\": \"burst_inject.c (sha256 $(_sha "$INJ_SRC")) on core $CORE_AUX, zone $ZONE_TYPE ($(basename "$TZ")): per round one each of U N P F A, 3 ms bursts, slots 0.75 + 0.35 i s + U(0, 0.1) s, seed SEED*100 + round, SEED $SEED\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds of t2ms, n=$N, warmup=$WARMUP, one each of U N P F A in each -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
IPID=""
for r in $(seq 1 "$K"); do
	echo "round $r order: t2ms" >> "$OUT/order.log"
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	: > "$OUT/inj-t2ms_r$r.jsonl"
	trace_start
	taskset -c "$CORE_AUX" sudo -n "$INJ" --zone "$TZ" --marker "$TRACE/trace_marker" \
		--log "$OUT/inj-t2ms_r$r.jsonl" --seed $((SEED * 100 + r)) --kinds UNPFA \
		--start 0.75 --step 0.35 --jitter 0.1 --burst-ms 3 &
	IPID=$!
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	wait "$IPID" || die "the injector failed in round $r"
	IPID=""
	[ "$(grep -c . "$OUT/inj-t2ms_r$r.jsonl")" -eq 5 ] || die "the injector logged $(grep -c . "$OUT/inj-t2ms_r$r.jsonl") injections in round $r, not 5"
	trace_take "t2ms_r$r"
	m_thermal "r$r t2ms after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" t2ms
	say "round $r/$K done"
done

RUN_T1=$(date +%s)
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "is it udevd's path walking in sysfs?"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
