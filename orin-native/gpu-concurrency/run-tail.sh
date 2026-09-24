#!/usr/bin/env bash
# run-tail.sh -- the tail, with the host's device interrupts moved off QEMU's cores
# and QEMU's threads made real-time. Phase 3b / A6, 2026-09-24; the fourth
# suggestion of the literature pass (Li et al., "Tales of the Tail", SoCC 2014:
# interrupt processing on application cores and non-FIFO scheduling inflate the
# tail).
#
# WHAT IS KNOWN. No A6 design has resolved the tail: p99 and above move by tens or
# hundreds of us between rounds. On this board every device interrupt (Wi-Fi,
# SD card, audio, the BPMP mailbox) is delivered to core 0 -- the masks say 0-5,
# and the GIC takes the lowest -- and core 0 is one of QEMU's three cores (0-2).
# Every host task may also run on those cores, beside QEMU's threads, at the same
# priority. (Read before this harness was written: /proc/interrupts over 5 s, and
# the affinities. No latency was looked at.)
#
# A 2 x 2 within one boot of the stamping guest (ifs-stamp.bin, :7103), 2 ms
# spacing, each factor switched before every arm and read back:
#   base  device interrupts where they are; QEMU's threads SCHED_OTHER
#   irq   every movable device interrupt on core IRQ_CORE (3), which no arm uses
#   fifo  QEMU's threads (main, vCPUs, workers) SCHED_FIFO at FIFO_PRIO (50)
#   iso   both
# A Williams design over the four (period 4). n = 3000 per arm-round: a p99.9 needs
# samples. Found at preflight and restored at the end: every IRQ's affinity, every
# QEMU thread's policy.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended; if a smoke run contradicts it, the
# record says so. H: interrupts on core 0 and host tasks at QEMU's priority are
# part of the tail. Paired within round, iso - base, median over the k = 12 rounds:
#   P1 p99: median <= -5 us, and below zero in >= 9/12 rounds. REFUTED if the
#      median >= 0. Between: PARTIAL.
#   P2 p99.9: median < 0 and below zero in >= 8/12 rounds. REFUTED if the median
#      >= 0. Between: PARTIAL.
#   P3 (control) p50: |median| <= 3 us. The median exchange meets neither an
#      interrupt nor a competing task, so isolation should not move it.
# NOT PREDICTED: which factor does it (irq - base, fifo - base), the max, and
# whether a tail sample's time is the monitor's or the rest's (it is stamped).
# THE MANIPULATION CHECK (a prediction resting on a failed one prints VOID):
#   M1 in every irq and iso arm-round, the moved interrupts fired at most twice in
#      all on cores 0-2 (/proc/interrupts around the arm) -> P1, P2, P3
# The policy of every QEMU thread is read back before every arm; a mismatch stops
# the run.
# tail_report.py applies all of it, and only at k = 12.
#
# NEEDS: the guest running (ifs-stamp.bin; CONSOLE its console log). c7 OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN. K a
# multiple of 4.
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
N="${N:-3000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
IRQ_CORE="${IRQ_CORE:-3}"
FIFO_PRIO="${FIFO_PRIO:-50}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/tail_report.py}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # the GR3D check is m_thermal's, before and after every arm
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(base irq fifo iso)
STAMP_ARMS="${ARMS[*]}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
declare -A IRQ_ORIG=()          # irq -> its smp_affinity_list at preflight, for every movable one
MOVABLE=""                      # the irqs this run moves and restores
QEMU_TOUCHED=0

irq_set() {   # $1 = "move" or "restore": every movable irq to IRQ_CORE, or back; read back
	local i want got
	for i in $MOVABLE; do
		if [ "$1" = move ]; then want="$IRQ_CORE"; else want="${IRQ_ORIG[$i]}"; fi
		echo "$want" | sudo -n tee "/proc/irq/$i/smp_affinity_list" > /dev/null 2>&1 \
			|| die "irq $i: could not write smp_affinity_list $want"
		got="$(cat "/proc/irq/$i/smp_affinity_list" 2>/dev/null)"
		[ "$(_cpuset "$got")" = "$(_cpuset "$want")" ] || die "irq $i reads back '$got', asked for '$want'"
	done
}

qemu_policy() {   # $1 = "fifo" or "other": every QEMU thread, read back
	local t pol
	QEMU_TOUCHED=1
	for t in $(ls "/proc/$QPID/task"); do
		if [ "$1" = fifo ]; then
			sudo -n chrt -f -p "$FIFO_PRIO" "$t" > /dev/null 2>&1 || [ ! -d "/proc/$QPID/task/$t" ] \
				|| die "chrt -f $FIFO_PRIO failed on QEMU thread $t"
		else
			sudo -n chrt -o -p 0 "$t" > /dev/null 2>&1 || [ ! -d "/proc/$QPID/task/$t" ] \
				|| die "chrt -o failed on QEMU thread $t"
		fi
		pol="$(chrt -p "$t" 2>/dev/null | sed -n 's/.*scheduling policy: //p')"
		[ -z "$pol" ] && [ ! -d "/proc/$QPID/task/$t" ] && continue
		case "$1:$pol" in
			fifo:SCHED_FIFO|other:SCHED_OTHER) ;;
			*) die "QEMU thread $t reads back policy '$pol', asked for $1" ;;
		esac
	done
}

irq_counts() {   # $1 = file: per-CPU counts of the movable irqs, "irq c0 c1 c2 c3 c4 c5" per line
	local i
	for i in $MOVABLE; do
		awk -v k="$i:" '$1 == k { print k, $2, $3, $4, $5, $6, $7 }' /proc/interrupts
	done > "$1"
}

cleanup() {
	say "cleanup"
	local i t
	for i in $MOVABLE; do
		echo "${IRQ_ORIG[$i]}" | sudo -n tee "/proc/irq/$i/smp_affinity_list" > /dev/null 2>&1 \
			|| echo "WARNING: could not restore irq $i to ${IRQ_ORIG[$i]}" >&2
	done
	[ -n "$MOVABLE" ] && say "irq affinities restored ($(echo $MOVABLE | wc -w) irqs)"
	if [ "$QEMU_TOUCHED" = 1 ] && [ -n "${QPID:-}" ] && [ -d "/proc/$QPID/task" ]; then
		for t in $(ls "/proc/$QPID/task"); do
			sudo -n chrt -o -p 0 "$t" > /dev/null 2>&1 || echo "WARNING: could not return QEMU thread $t to SCHED_OTHER" >&2
		done
		say "QEMU threads returned to SCHED_OTHER"
	fi
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

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
	case "$a" in base|fifo) irq_set restore ;; irq|iso) irq_set move ;; esac
	case "$a" in base|irq) qemu_policy other ;; fifo|iso) qemu_policy fifo ;; esac
	sleep 1
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	irq_counts "$OUT/irq-$t.before"
	PROBE_STAMPS=1 m_probe "$OUT" "$t" "$GUEST" "$D_PORT"
	irq_counts "$OUT/irq-$t.after"
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
for f in "$PROBE" "$REPORT" "$CONSOLE"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
command -v chrt > /dev/null || die "no chrt on this host"
[ -z "$(m_pids_of irqbalance)" ] || die "irqbalance is running: it would move the interrupts back mid-run"
case " $(_cpuset "$QEMU_CORES") $CORE_PROBE $CORE_AUX " in *" $IRQ_CORE "*) die "IRQ_CORE $IRQ_CORE is a measured core" ;; esac
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"
RT_RUNTIME="$(cat /proc/sys/kernel/sched_rt_runtime_us 2>/dev/null)"
[ "$RT_RUNTIME" != -1 ] || die "RT throttling is off (sched_rt_runtime_us -1): a spinning FIFO thread could starve its core"

# The movable interrupts: those whose affinity can be written. Tried once here,
# written back at once, and every one is restored at the end.
for d in /proc/irq/[0-9]*; do
	i="${d##*/}"
	orig="$(cat "$d/smp_affinity_list" 2>/dev/null)" || continue
	[ -n "$orig" ] || continue
	if echo "$IRQ_CORE" | sudo -n tee "$d/smp_affinity_list" > /dev/null 2>&1; then
		# Registered before the restore is tried, so the cleanup restores it
		# even if this write fails and the run stops.
		IRQ_ORIG[$i]="$orig"
		MOVABLE="$MOVABLE $i"
		echo "$orig" | sudo -n tee "$d/smp_affinity_list" > /dev/null 2>&1 || die "irq $i: could not restore $orig"
	fi
done
[ -n "$MOVABLE" ] || die "no interrupt on this host could be moved"

m_prepare_out "${OUT:-}" "$HOME/tail-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX" "$IRQ_CORE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX" "irq=$IRQ_CORE"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
for i in $MOVABLE; do echo "$i ${IRQ_ORIG[$i]} $(awk -v k="$i:" '$1 == k { $1=""; print }' /proc/interrupts | awk '{ $1=$2=$3=$4=$5=$6=""; print }' | sed 's/^ *//')"; done > "$OUT/irqs.txt"

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "tail"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX, \"irqs_moved_to\": $IRQ_CORE}" \
	"\"port\": $D_PORT" \
	"\"fifo_prio\": $FIFO_PRIO" \
	"\"sched_rt_runtime_us\": \"$RT_RUNTIME\"" \
	"\"movable_irqs\": $(echo $MOVABLE | wc -w)" \
	'"kvm_stats": 1' \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	'"order": "Williams design over the four arms, period 4"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, arms ${ARMS[*]}; $(echo $MOVABLE | wc -w) movable irqs -> core $IRQ_CORE in irq/iso; FIFO $FIFO_PRIO in fifo/iso -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#ARMS[@]}"); do order+=("${ARMS[$i]}"); done
	echo "round $r order: ${order[*]}" >> "$OUT/order.log"
	for a in "${order[@]}"; do run_arm "$a" "$r"; done
	say "round $r/$K done"
done
irq_set restore
qemu_policy other

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" base "${ARMS[@]}"
say "each arm against base, paired within round (p50)"
m_pairs "$OUT" iso:base irq:base fifo:base
say "the tail, the check and the predictions"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
