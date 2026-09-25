#!/usr/bin/env bash
# run-partition.sh -- one boot's rounds of the partition test: does partitioning the kernel
# (isolcpus=managed_irq,domain,0-2,4 irqaffinity=3,5) take part of the host's tick off the
# exchange? Phase 3b / A6, 2026-09-25; follows 20260925T-a6-orin-tick. The owner asked for
# this test (2026-09-25), which reboots the board into a second boot entry and back
# (partition-boot.sh) and changes systemd settings at runtime, all restored after.
#
# WHAT IS KNOWN. With the host's userspace confined to cores 3 and 5, exchanges whose
# request leaves 150 to 0 us before the host's tick (a 4 ms grid, every core at once) are
# +11.2 us slower at the median and hold a quarter of the tail. Per QEMU core the tick brings
# its timer interrupt (~4 us) and a SCHED softirq, the scheduler's periodic load balancing
# (2-5 us); tail ones add TIMER softirqs and the kernel work they release
# (20260925T-a6-orin-tick). This kernel has CPU_ISOLATION but not NO_HZ_FULL or
# RCU_NOCB_CPU: the tick cannot be stopped, but isolcpus=domain takes the isolated cores
# out of the scheduler's domains, so no load balancing runs there, and gives unbound work
# queues and init (so all of userspace) the housekeeping cores 3 and 5; managed_irq and
# irqaffinity=3,5 keep device interrupts off 0-2 and 4. Per-CPU work (vmstat_update, the
# per-CPU timers) and the tick's interrupt stay.
#
# THE DESIGN. Two ARMS, one per boot entry: default (LABEL primary, as shipped) and
# partition (LABEL partition, the same plus PARAMS). Four boots in the order A1 B1 B2 A2
# (A default, B partition), each a fresh reboot; this harness runs one boot's rounds and
# refuses a boot whose command line does not match its BOOT_TAG. In every boot and round:
#   - the host's userspace confined as run-tick.sh's: system.slice, init.scope,
#     user@1000.service and every session scope but the harness's own on AllowedCPUs=3,5,
#     restored to 0-5 and the drop-ins removed at the end (confine.log);
#   - QEMU's threads pinned ONE PER CORE, in both arms: vCPU n ("CPU n/KVM") alone on the
#     n-th core of VCPU_CORES (1 2), every other QEMU thread on OTHER_CORES (0), read back
#     per thread before and after every round (pin.log). The isolated cores get no load
#     balancing, so a set pin could leave two threads on one core for good; the default arm
#     gets the same layout so that only the boot entry differs. This is not the set pin
#     (0-2) of every earlier A6 record: 20260924T-a6-orin-vcpupin found the two alike;
#   - the probe on core 4, the light trace (frames into tap-qnx, thermal reads), and
#     /proc/softirqs and /proc/interrupts read before and after the round (irq-*.txt);
#   - the rounds start only once the boot is SETTLE_S (600) s old: a freshly started desktop
#     session is heavy for minutes (20260924T-a6-orin-headless).
# k = 16 rounds per boot, n = 1000, 200 warm-up, t2ms (the A6 default: two vCPUs,
# halt_poll_ns 500000, 2 ms), nothing injected. SSH logins accepted during the rounds are
# counted from the journal (logins.txt); each boot's run is watched from the one session
# that started it.
#
# THE RULE, fixed here before any run (partition_report.py applies it to the four boots):
#   - alignment, classes and the TICK BIN are run-tick.sh's: out-class exchanges whose
#     request left in [3850, 4000) us mod 4000; TAIL is at or above the round's p99;
#   - per arm, pooled over its two boots: SLOWDOWN is the median round trip of tick-bin
#     exchanges minus that of the other out-class exchanges; RATIO is the tick bin's share
#     of the tail over its share of the exchanges; p50 over every timed exchange;
#   - per boot, the same SLOWDOWN, for P4.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: partitioning the kernel takes the load balancing
# off QEMU's and the probe's cores and with it a clear part of what the tick costs an
# exchange; the tick's own interrupt and per-CPU work stay, so part of the cost stays too;
# the typical exchange does not change.
#   P1 the tick costs less: partition SLOWDOWN <= 0.75x default's.
#   P2 not all of it goes: partition SLOWDOWN >= +3 us.
#   P3 fewer tick-bin exchanges reach the tail: partition RATIO <= 0.75x default's.
#   P4 every boot agrees: both partition boots' SLOWDOWN below both default boots'.
#   P5 the typical exchange does not change: |p50 partition - p50 default| <= 3 us.
# THE CHECKS (a prediction resting on a failed one prints VOID):
#   M1 >= 90% of each boot's rounds align -> all
#   M2 every round confined (udevd, PID 1, gnome-shell on 3,5) and every QEMU thread on its
#      own pin, before and after -> all
#   M3 no SSH login during any boot's rounds -> all
#   M4 the arms are what they say: each boot's command line has PARAMS (partition) or
#      neither isolcpus= nor irqaffinity= (default), /sys/devices/system/cpu/isolated reads
#      0-2,4 or nothing, and the SCHED softirqs on cores 0-2 and 4 per round in the
#      partition boots are <= 5% of the default boots' -> all
#   M5 four boots, A1 B1 B2 A2, each settled (uptime >= 600 s at its first round) -> all
#   M6 >= 25 tick-bin tail exchanges per arm -> P1 P3
# Scored only with all four boots at k = 16.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log), launched with
# THREAD_NAMES=1. c7 OFF (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS
# THE RUN. BOOT_TAG one of A1 B1 B2 A2.
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
K="${K:-16}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
SEED="${SEED:-24}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
TJT="${TJT:-$here/tjphase_trace.py}"
REPORT="${REPORT:-$here/partition_report.py}"
BOOT_TAG="${BOOT_TAG:?set BOOT_TAG to A1, B1, B2 or A2}"
SETTLE_S="${SETTLE_S:-600}"
PARAMS="${PARAMS:-isolcpus=managed_irq,domain,0-2,4 irqaffinity=3,5}"
VCPU_CORES="${VCPU_CORES:-1 2}"
OTHER_CORES="${OTHER_CORES:-0}"
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
TZ=""; CONF_TOUCHED=0; UNITS=""; ARM=""; UPTIME0=""
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

vcpu_index() {   # $1 comm -> n for "CPU n/KVM", else nothing
	local c="$1" n
	case "$c" in "CPU "*"/KVM") n="${c#CPU }"; n="${n%/KVM}" ;; *) return 0 ;; esac
	case "$n" in ''|*[!0-9]*) return 0 ;; esac
	echo "$n"
}

pin_want() {   # $1 comm -> the core list its thread belongs on
	local n cores=($VCPU_CORES)
	n="$(vcpu_index "$1")"
	if [ -n "$n" ]; then echo "${cores[$n]}"; else echo "$OTHER_CORES"; fi
}

pin_threads() {   # every QEMU thread on its own pin; the cpuset changes reset QEMU's
	local t c want
	for t in $(ls "/proc/$QPID/task"); do
		c="$(cat "/proc/$QPID/task/$t/comm" 2>/dev/null)" || continue
		want="$(pin_want "$c")"
		[ -n "$want" ] || return 1
		sudo -n taskset -pc "$want" "$t" > /dev/null 2>&1 || [ ! -d "/proc/$QPID/task/$t" ] || return 1
	done
}

pin_log() {   # $1 round  $2 before|after: one line per thread, "round R W tid want got"
	local t c
	for t in $(ls "/proc/$QPID/task"); do
		c="$(cat "/proc/$QPID/task/$t/comm" 2>/dev/null)" || continue
		echo "round $1 $2 $t $(pin_want "$c") $(allowed "$QPID/task/$t")"
	done >> "$OUT/pin.log"
}

irq_snap() {   # $1 round  $2 before|after
	{ echo "== round $1 $2 softirqs"; cat /proc/softirqs; echo "== round $1 $2 interrupts"; cat /proc/interrupts; } >> "$OUT/irq-t2ms_r$1.txt"
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
ISO="$(cat /sys/devices/system/cpu/isolated 2>/dev/null)"
HAS=""
for p in $PARAMS; do tr ' ' '\n' < /proc/cmdline | grep -qxF -- "$p" && HAS="$HAS+" || HAS="$HAS-"; done
ANY="$(tr ' ' '\n' < /proc/cmdline | grep -cE '^(isolcpus|irqaffinity)=')"
if [ "${HAS//+/}" = "" ] && [ "$ISO" = 0-2,4 ]; then ARM=partition
elif [ "$ANY" = 0 ] && [ -z "$ISO" ]; then ARM=default
else die "this boot is neither arm: cmdline tokens $HAS, isolcpus/irqaffinity tokens $ANY, isolated '$ISO'"; fi
case "$BOOT_TAG:$ARM" in A1:default|A2:default|B1:partition|B2:partition) ;;
	*) die "BOOT_TAG $BOOT_TAG does not match this boot's arm ($ARM)" ;; esac
HK=0-5; [ "$ARM" = partition ] && HK=3,5   # the affinity every userspace task inherits from init
UPTIME0="$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)"
[ "$UPTIME0" -ge "$SETTLE_S" ] || die "the boot is ${UPTIME0} s old, under SETTLE_S=$SETTLE_S: let it settle"
ME="$(basename "$(cut -d: -f3 /proc/self/cgroup)")"
case "$ME" in session-*.scope) ;; *) die "the harness is not in a session scope ($ME)" ;; esac
UNITS="system.slice init.scope $(systemctl list-units 'user@*.service' --no-legend | awk '{print $1}') $(systemctl list-units --type=scope --state=running --no-legend | awk '{print $1}' | grep '^session-' | grep -vx "$ME")"
for u in $UNITS; do
	case "$(systemctl show -p AllowedCPUs --value "$u")" in ""|0-5) ;; *) die "$u already has AllowedCPUs set -- someone else changed it" ;; esac
done
for s in /proc/[0-9]*/task/[0-9]*/status; do
	c="$(awk '/^Cpus_allowed_list/ {print $2}' "$s" 2>/dev/null)"
	[ -n "$c" ] && [ "$c" != 0-5 ] && [ "$c" != "$HK" ] || continue
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

m_prepare_out "${OUT:-}" "$HOME/partition-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock && echo $TRACE_KB > buffer_size_kb" || die "could not set the trace clock and buffer"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "partition"' \
	"\"arm\": \"$ARM\"" \
	"\"boot_tag\": \"$BOOT_TAG\"" \
	"\"boot\": \"cmdline isolcpus/irqaffinity: $(tr ' ' '\n' < /proc/cmdline | grep -E '^(isolcpus|irqaffinity)=' | tr '\n' ' '); isolated '$ISO'; default_smp_affinity $(cat /proc/irq/default_smp_affinity); uptime at preflight ${UPTIME0} s\"" \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"vcpus\": \"$VCPU_CORES\", \"qemu_other\": \"$OTHER_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	"\"confinement\": \"every round: units $UNITS on AllowedCPUs=$CONF_CORES; QEMU vCPU n alone on the n-th of '$VCPU_CORES', other threads on $OTHER_CORES; nothing injected; zone $ZONE_TYPE ($(basename "$TZ"))\"" \
	"\"trace\": \"$TEVENTS, net_dev_xmit filtered to tap-qnx, mono clock, buffer $TRACE_KB KB per core (was $TRACE_KB_BEFORE), reduced by tjphase_trace.py (sha256 $(_sha "$TJT"))\"" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["t2ms"]'

# ---------------------------------------------------------------- the run
say "boot $BOOT_TAG ($ARM): k=$K rounds of t2ms, n=$N, warmup=$WARMUP, nothing injected, userspace confined ($UNITS), QEMU one thread per core -> $OUT"
RUN_T0=$(date +%s)
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	echo "round $r arm: $ARM" >> "$OUT/order.log"
	set_units "$CONF_CORES" || die "could not set the units for round $r"
	pin_threads || die "could not pin QEMU's threads one per core for round $r"
	sleep 1
	echo "round $r before $(conf_state)" >> "$OUT/confine.log"
	pin_log "$r" before
	irq_snap "$r" before
	m_thermal "r$r t2ms before" >> "$OUT/thermal.log"
	seq0="$(cat /sys/kernel/uevent_seqnum)"
	trace_start
	PROBE_STAMPS=1 m_probe "$OUT" "t2ms_r$r" "$GUEST" "$D_PORT"
	echo "round $r seqnum $seq0 $(cat /sys/kernel/uevent_seqnum)" >> "$OUT/seqnum.log"
	irq_snap "$r" after
	trace_take "t2ms_r$r"
	echo "round $r after $(conf_state)" >> "$OUT/confine.log"
	pin_log "$r" after
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
echo "accepted=$(sudo -n journalctl -u ssh -u sshd --since "@$RUN_T0" --until "@$RUN_T1" -o cat 2>/dev/null | grep -c '^Accepted ')" > "$OUT/logins.txt"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "boot $BOOT_TAG ($ARM) done; the report needs all four boots: partition_report.py A1 B1 B2 A2"
python3 "$REPORT" --one "$OUT" "$N" "$WARMUP" || die "the one-boot report could not be made -- see above"
