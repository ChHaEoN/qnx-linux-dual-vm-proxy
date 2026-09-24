#!/usr/bin/env bash
# run-vcpupin.sh -- why the guest monitor's own time halves at 0.2 ms spacing:
# a test of KVM's per-core TLB and I-cache flush, made by pinning each vCPU to its
# own core. Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-rate, section 5.
#
# THE OBSERVATION. In the offered-rate sweep the stamping monitor's userspace span
# in the guest was 6 ticks (32 ns each) at p50 at 0.2 ms spacing, and 12 at every
# spacing from 0.5 ms. Natively it never moved. At 0.2 ms the vCPUs almost never
# block (KVM halt polling). From 0.5 ms they block, and are woken on nearly every
# exchange.
#
# THE HYPOTHESIS UNDER TEST. Linux 5.15's kvm_arch_vcpu_load() keeps, per
# physical core, the id of this VM's vCPU that last ran there (last_vcpu_ran).
# When a DIFFERENT vCPU is loaded, it flushes that core's TLB and I-cache for the
# VM (__kvm_flush_cpu_context). QEMU's threads are pinned to cores 0-2 as a set,
# so a vCPU woken from a blocked halt may resume on a core where the other vCPU
# ran last. The monitor then runs with its translations and code cold. A vCPU
# that polls never leaves its core. Pinning each vCPU to its own core makes the
# flush impossible, without stopping the blocking.
#
# Four arms, all on the guest's stamping monitor (ifs-stamp.bin, :7103). In every
# arm QEMU's other threads stay on QEMU_CORES (0-2) as a set. The vCPU threads:
#   S200us S2ms   both on the cores of VCPU_CORES (1 and 2) as a SET: either may
#                 run on either, so they can swap cores
#   O200us O2ms   "CPU n/KVM" alone on the n-th core of VCPU_CORES: they cannot
# So S and O give the vCPUs the same cores, and differ only in whether a vCPU
# is bound to its own. FOUND BY REVIEW, before any run: the first design left the
# S arms' vCPUs on 0-2, as in every A6 record. The O arms would then also have
# taken core 0 away from them, and core 0 takes most of this host's device
# interrupts. That is a second change, which could shorten the monitor's span for
# its own reasons. The price is that the S arms are not the rate run's exact
# configuration, so S200us - S2ms is a replication of its step on a slightly
# different placement, not of the same one. The affinity is re-applied, and read
# back per thread, before every arm.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. If a smoke run contradicts it, the
# record says so.
#   P1 (primary). The monitor's p50 span in ticks, O2ms - S2ms paired within
#      round: median <= -4 ticks, and below zero in at least 10 of 12 rounds.
#      REFUTED if the median is >= -1 tick. Anything between: a part of the
#      halving is the flush, and the rest is something else.
#   P2 (control). O200us - S200us: |median| <= 1 tick. At 0.2 ms the vCPUs barely
#      block, so pinning has nothing to prevent.
#   P3 (the trace, blind to every timing). The flush condition -- a vCPU switched
#      in on a core where the other vCPU was the last one switched in -- occurs at
#      least 0.5 times per exchange in S2ms, and fewer than 0.1 times in S200us.
#      In the O arms it must be 0: that is a check of the pinning, not a test.
# NOT PREDICTED: the round trip. A vCPU pinned alone can no longer wake on
# another idle core when its own is busy, which can cost as well as save. The
# round trip is reported, not scored.
#
# THE TRACE. sched_switch, filtered to the two vCPU threads as next_pid, is on for
# every arm, S and O alike, so it cannot explain a difference between them. It
# is reduced at capture time to "seconds core vcpu" lines (switch_trace.py), so
# no other process's name leaves the board. A switch-in stands for KVM's
# vcpu_load; switch_trace.py says why that is an approximation. The trace clock
# is set to "mono" for the run, so every count is taken inside the same window
# as the KVM counters (m_kvm_snap's t_ns). Lost events stop the run. So does a
# trace that cannot vouch for itself (switch_trace.py check, after every arm):
# fewer switch-ins than half the KVM wake-ups, or in an O arm any migration. A
# dead trace would otherwise read as "no flush". The preflight refuses a tracer
# other than nop, a pid filter, record-tgid, and overwrite off. The trace clock
# and the event are restored at the end. The ring buffer stays expanded to its
# default size (1408 KB per core here) until reboot, as after any use of it.
#
# SCORING. vcpupin_report.py applies the thresholds above, and only at k = 12:
# P1's "10 of 12" means nothing at another k, so a smoke run prints its numbers
# unscored.
#
# NEEDS: the guest launched with THREAD_NAMES=1 (launch-qnx-kvm-bridged.sh), so
# that QEMU names its vCPU threads "CPU n/KVM". A guest without them is refused.
# c7 is OFF (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE
# RUN. A WILLIAMS DESIGN over the four arms (period 4), so K must be a multiple
# of 4.
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
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2                   # the preflight's; every arm sets its own
QEMU_CORES="${QEMU_CORES:-0-2}"
VCPU_CORES="${VCPU_CORES:-1 2}" # vCPU n alone on the n-th of these, in the O arms
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"       # the KVM counter reads and every trace command
PROBE="${PROBE:-$here/latency_probe.py}"
SWT="${SWT:-$here/switch_trace.py}"
REPORT="${REPORT:-$here/vcpupin_report.py}"
TRACE="${TRACE:-/sys/kernel/tracing}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: a 0.2 ms arm is shorter than tegrastats' first line
KVM_STATS=1                     # the halt-poll counters, to show the S arms reproduce the rate run
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(S200us S2ms O200us O2ms)
STAMP_ARMS="${ARMS[*]}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
VCPU_SET="$(echo $VCPU_CORES | tr ' ' ',')"
VMAP=""; FILTER=""; TRACE_ON_BEFORE=""; TRACE_CLOCK_BEFORE=""; TRACE_TOUCHED=0

tsu() {   # $1 = a shell command, run as root on the aux core
	taskset -c "$CORE_AUX" sudo -n sh -c "$1"
}

trace_restore() {   # leave the tracing state as the preflight found it
	[ "$TRACE_TOUCHED" = 1 ] || return 0
	tsu "cd '$TRACE' && echo 0 > events/sched/sched_switch/enable && echo 0 > events/sched/sched_switch/filter && echo ${TRACE_CLOCK_BEFORE:-local} > trace_clock && echo > trace && echo ${TRACE_ON_BEFORE:-1} > tracing_on" 2>/dev/null \
		|| echo "WARNING: could not restore $TRACE -- sched_switch or the trace clock may be left changed" >&2
}

pin_all_to_set() {   # cleanup: every QEMU thread back on QEMU_CORES, as found
	local t
	[ -n "${QPID:-}" ] && [ -d "/proc/$QPID/task" ] || return 0
	for t in $(ls "/proc/$QPID/task" 2>/dev/null); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1 \
			|| echo "WARNING: could not return QEMU thread $t to $QEMU_CORES" >&2
	done
}

cleanup() {
	say "cleanup"
	trace_restore
	pin_all_to_set
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

spacing_ms() {   # $1 arm -> the probe's --interval-ms
	case "${1:1}" in
		200us) echo 0.2 ;; 2ms) echo 2 ;;
		*) die "no spacing for arm $1" ;;
	esac
}

vcpu_index() {   # $1 comm -> n for "CPU n/KVM", else nothing
	local c="$1" n
	case "$c" in "CPU "*"/KVM") n="${c#CPU }"; n="${n%/KVM}" ;; *) return 0 ;; esac
	case "$n" in ''|*[!0-9]*) return 0 ;; esac
	echo "$n"
}

# The vCPUs: in an O arm vCPU n alone on the n-th core of VCPU_CORES, in an S arm
# both on VCPU_CORES as a set. Every other thread on QEMU_CORES. Read back from
# each thread's own status, not from the process's.
pin_arm() {   # $1 S|O  $2 round  $3 arm
	local mode="$1" t c n want got cores=($VCPU_CORES)
	for t in $(ls "/proc/$QPID/task"); do
		c="$(cat "/proc/$QPID/task/$t/comm" 2>/dev/null)" || continue   # a worker that just exited
		want="$QEMU_CORES"
		n="$(vcpu_index "$c")"
		if [ -n "$n" ]; then
			if [ "$mode" = O ]; then want="${cores[$n]}"; else want="$VCPU_SET"; fi
		fi
		if ! sudo -n taskset -pc "$want" "$t" >/dev/null 2>&1; then
			[ -d "/proc/$QPID/task/$t" ] || continue                     # it exited meanwhile
			die "taskset $want failed on QEMU thread $t ($c)"
		fi
		got="$(awk '/^Cpus_allowed_list:/ {print $2}' "/proc/$QPID/task/$t/status" 2>/dev/null)"
		[ -n "$got" ] || [ -d "/proc/$QPID/task/$t" ] || continue
		[ "$(_cpuset "$got")" = "$(_cpuset "$want")" ] \
			|| die "QEMU thread $t ($c) reads back '$got', asked for '$want'"
		echo "r$2 $3 $t $got $c" >> "$OUT/pin.log"
	done
}

trace_start() {   # an empty buffer, then sched_switch into the vCPU threads only
	TRACE_TOUCHED=1
	tsu "cd '$TRACE' && echo 0 > tracing_on && echo 0 > events/sched/sched_switch/enable && echo > trace && echo '$FILTER' > events/sched/sched_switch/filter && echo 1 > events/sched/sched_switch/enable && echo 1 > tracing_on" \
		|| die "could not start the sched_switch trace in $TRACE"
}

trace_take() {    # $1 tag: stop, then reduce on this host into sw-$1.log
	tsu "cd '$TRACE' && echo 0 > tracing_on" || die "could not stop the trace after $1"
	tsu "cat '$TRACE/trace'" | python3 "$SWT" reduce --map "$VMAP" > "$OUT/sw-$1.log" \
		|| die "the trace of $1 was refused (see the message above) -- the run stops here"
	tsu "cd '$TRACE' && echo 0 > events/sched/sched_switch/enable && echo 0 > events/sched/sched_switch/filter" \
		|| die "could not disable sched_switch after $1"
}

# The GR3D readings m_thermal took just before and after an arm must both read 0%.
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
	pin_arm "${a:0:1}" "$r" "$a"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	trace_start
	INTERVAL_MS="$(spacing_ms "$a")" PROBE_STAMPS=1 m_probe "$OUT" "$t" "$GUEST" "$D_PORT"
	trace_take "$t"
	{ printf '%s ' "$t"; python3 "$SWT" check --sw "$OUT/sw-$t.log" --kvm "$OUT/kvm-$t.json" --mode "${a:0:1}"; } \
		>> "$OUT/trace-check.log" || die "the trace of $t cannot vouch for itself (see above) -- the run stops here"
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
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm (no window sampler: windows are shorter than tegrastats interval)"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight; no window sampler"
fi
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$SWT" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
tsu "test -w '$TRACE/events/sched/sched_switch/enable'" || die "no writable sched_switch event under $TRACE"
[ "$(tsu "cat '$TRACE/current_tracer'")" = nop ] || die "$TRACE/current_tracer is not nop -- someone else is tracing"
[ "$(tsu "cat '$TRACE/events/sched/sched_switch/enable'")" = 0 ] \
	|| die "sched_switch is already enabled -- someone else is tracing"
[ "$(tsu "cat '$TRACE/options/overwrite'")" = 1 ] \
	|| die "$TRACE/options/overwrite is not 1: lost events would not show in the header"
[ "$(tsu "cat '$TRACE/options/record-tgid'")" = 0 ] || die "$TRACE/options/record-tgid is on: the trace lines change shape"
[ -z "$(tsu "cat '$TRACE/set_event_pid' '$TRACE/set_event_notrace_pid' 2>/dev/null")" ] \
	|| die "a pid filter is set in $TRACE: it could hide the vCPU threads"
tsu "grep -qw mono '$TRACE/trace_clock'" || die "$TRACE has no mono trace clock"
TRACE_ON_BEFORE="$(tsu "cat '$TRACE/tracing_on'")"
TRACE_CLOCK_BEFORE="$(tsu "cat '$TRACE/trace_clock'" | sed -n 's/.*\[\(.*\)\].*/\1/p')"
[ -n "$TRACE_CLOCK_BEFORE" ] || die "cannot read the current trace clock"
TRACE_BUF_KB="$(tsu "cat '$TRACE/buffer_size_kb'" | tr -d '()' | sed 's/  */ /g')"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"
# The predictions are in counter ticks: without the frequency nothing can be scored,
# so refuse now rather than after 48 arms (FOUND BY REVIEW).
[ -n "$TIMER" ] || die "no arch_timer frequency in dmesg -- the monitor's ticks could not be counted"
HALT_POLL=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALT_POLL="$HALT_POLL\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo unread)\", "
done
HALT_POLL="{${HALT_POLL%, }}"

m_prepare_out "${OUT:-}" "$HOME/vcpupin-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX" $VCPU_CORES
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
for c in $VCPU_CORES; do
	case " $(_cpuset "$QEMU_CORES") " in *" $c "*) ;; *) die "VCPU_CORES core $c is not in QEMU_CORES ($QEMU_CORES)" ;; esac
done
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"

# The vCPU threads, by the names THREAD_NAMES=1 gives them: exactly one per core
# in VCPU_CORES, indexed 0..n-1.
VN=0; want_n="$(echo $VCPU_CORES | wc -w)"
for t in $(ls "/proc/$QPID/task"); do
	n="$(vcpu_index "$(cat "/proc/$QPID/task/$t/comm" 2>/dev/null)")"
	[ -n "$n" ] || continue
	[ "$n" -lt "$want_n" ] || die "vCPU thread $t is CPU $n/KVM, but VCPU_CORES has only $want_n core(s)"
	VMAP="${VMAP:+$VMAP,}$t:$n"
	FILTER="${FILTER:+$FILTER || }next_pid == $t"
	VN=$((VN + 1))
done
[ "$VN" -gt 0 ] || die "no QEMU thread is named 'CPU n/KVM' -- launch the guest with THREAD_NAMES=1"
[ "$VN" = "$want_n" ] || die "found $VN vCPU thread(s) ($VMAP), VCPU_CORES names $want_n core(s)"
[ "$(printf '%s\n' "${VMAP//,/$'\n'}" | cut -d: -f2 | sort -u | wc -l)" = "$VN" ] \
	|| die "two vCPU threads carry the same index: $VMAP"
say "vCPU threads (tid:index): $VMAP; S arms put them on $VCPU_SET as a set, O arms vCPU n alone on the n-th of '$VCPU_CORES'"
TRACE_TOUCHED=1
tsu "cd '$TRACE' && echo mono > trace_clock" || die "could not set the trace clock to mono"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"

INTERVAL_MS='"per arm: see spacings_ms"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "vcpupin"' \
	"\"pin\": {\"qemu_other_threads\": \"$QEMU_CORES\", \"vcpus_S_as_a_set\": \"$VCPU_SET\", \"vcpus_O_each_alone\": \"$VCPU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"vcpu_threads\": \"$VMAP\"" \
	"\"port\": $D_PORT" \
	'"spacings_ms": {"S200us": 0.2, "S2ms": 2, "O200us": 0.2, "O2ms": 2}' \
	"\"kvm_halt_poll\": $HALT_POLL" \
	'"kvm_stats": 1' \
	"\"trace\": \"sched_switch filtered to the vCPU threads as next_pid, on for every arm, reduced at capture by switch_trace.py (sha256 $(_sha "$SWT"))\"" \
	"\"trace_buffer_kb\": \"$TRACE_BUF_KB\"" \
	"\"trace_clock\": \"mono for the run (was $TRACE_CLOCK_BEFORE, restored after)\"" \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	'"order": "Williams design over the four arms, period 4"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, arms ${ARMS[*]}, Williams over ${#ARMS[@]} -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/pin.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#ARMS[@]}"); do order+=("${ARMS[$i]}"); done
	echo "round $r order: ${order[*]}" >> "$OUT/order.log"
	for a in "${order[@]}"; do run_arm "$a" "$r"; done
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" S2ms "${ARMS[@]}"
say "round trip, paired within round"
m_pairs "$OUT" O2ms:S2ms O200us:S200us S200us:S2ms O200us:O2ms
say "per arm, medians over rounds; per exchange over $((N + WARMUP)) exchanges; and the three predictions"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
