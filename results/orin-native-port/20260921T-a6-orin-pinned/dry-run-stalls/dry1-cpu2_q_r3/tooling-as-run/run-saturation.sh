#!/usr/bin/env bash
# run-saturation.sh -- where does interference actually start?
#
# The 2026-09-19 null result had one busy core out of six. Four idle cores is not
# a contended system, so it said nothing about saturation. This escalates the CPU
# load and looks for the point where the QNX guest's round trip degrades.
#
# The guest has 2 vCPUs, which QEMU runs as host threads. As L4T's own load
# approaches the core count, those vCPU threads must compete -- so if
# interference exists at all, it should appear here.
#
# ARMS, per round
#   idle        no load                               baseline, and the pairing reference
#   cpu2_q      2 threads PINNED to 0,1   (two of QEMU's three cores)
#   cpu2_nq     2 threads PINNED to 3,5   (off QEMU's cores and off the probe's)
#   cpu3_q      3 threads PINNED to 0,1,2 (all of QEMU's cores)
#   cpu6        6 threads PINNED to 0-5   (fully committed, one per core)
#   cpu6_prio   cpu6, PROBE AT REAL-TIME PRIORITY
#   gpu_cpu6    cpu6 + GPU saturated
#   idle2       no load                               drift bracket
#
# PLACEMENT IS THE VARIABLE NOW, NOT COUNT (2026-09-21). The arms used to be
# cpu2/cpu4/cpu6 with the threads unpinned, and an independent analysis of the
# first runs found where the scheduler put them went with the cost. cpu4 had two
# regimes, ~+35 us and ~+165 us -- the second MORE than cpu6 -- and 12 of the
# 13 high rounds had two of QEMU's cores loaded in the one tegrastats sample
# taken before the probe. But 5 of the 17 rounds sampled that way were low, and
# one high round sampled one QEMU core. So one sample before the probe could
# not decide it; the window sampler now traces the whole probe. The count sweep
# was a placement lottery. So:
#   cpu2_q vs cpu2_nq   same count, on vs off QEMU's cores -- does the cost
#                       follow QEMU's cores at all?
#   cpu2_q vs cpu3_q    two of three QEMU cores loaded vs all three -- the
#                       packing HYPOTHESIS: with one QEMU core free, QEMU's
#                       threads pile onto it, and that is worse than no free one
# cpuload pins each thread at creation and reads it back, exiting non-zero if
# the pin did not take; the window sampler records per-core load across each
# probe, so the placement is observed as well as asked for.
#
# cpu6_prio's REAL-TIME PRIORITY IS NOW MEASURED, NOT ASSUMED. The probe reports
# its own scheduling policy, priority and affinity from inside the process, and
# the completeness gate refuses the run unless every cpu6_prio file says
# SCHED_FIFO 50 and every other file says SCHED_OTHER. Before this, the analysis
# rightly called the control uninformative: FIFO was established by procedure.
#
# WHY cpu6_prio EXISTS. Under full saturation the probe on L4T is itself
# competing for a core, so a plain cpu6 number mixes probe-side scheduling delay
# with anything happening to the guest. The same arm with the probe at elevated
# priority removes most of the probe-side component: if cpu6_prio comes back
# near idle, the cpu6 degradation was mostly the PROBE waiting, not the guest.
#
# cpu6_prio REFUSES RATHER THAN DOWNGRADES. It used to fall back to normal
# priority when sudo was refused. Under k rounds that could flip part-way through
# and leave an arm that is half a priority control and half not, under one label.
# Real-time priority is checked once, before round 1, and the run stops without it.
#
# k ROUNDS, WILLIAMS-COUNTERBALANCED (OD11, 2026-09-21). Every ordered pair of
# loaded arms must be adjacent equally often -- reversing the order on
# alternate rounds, which a first draft did, balances position but not
# carryover. Six loaded arms give a Williams period of 6, so K must be a
# multiple of 6 and defaults to 12 (OD11 asks k>=12). idle and idle2 bracket
# every round.
#
# WHAT IS VERIFIED in every loaded arm: each load process alive after settle and
# still alive when the probe ends; every cpuload thread confirmed its own pin;
# gpu_cpu6 must show GR3D at 50% or more; every window's trace holds a complete
# clock reading; and after the run, every arm file reports the probe's own
# scheduling policy and core. The load stops the moment the probe does.
#
# gpu_cpu6 IS CLOSE TO A MATCHED-FOOTPRINT CONTROL FOR cpu6 -- the opposite of
# what this header said until 2026-09-21. It claimed fma's driver thread keeps a
# core busy, making gpu_cpu6 seven busy threads against six. Measured: during
# all 12 interference gpu arms no core exceeded 1% CPU while GR3D sat at 99%;
# fma's host thread blocks in cudaDeviceSynchronize. So gpu_cpu6 - cpu6 isolates
# the GPU load about as well as this design can. The claim came from a review
# finding repeated here without being checked against the data. Stamps written
# before the correction still carry the false "known_confound" line.
#
# COMPARABILITY -- none of these arms pairs with an earlier run. 2026-09-19 used
# n=3000, k=1 and unpinned everything; the first 2026-09-21 runs pinned QEMU and
# the probe but let the load threads float, and named arms by count (cpu2, cpu4).
# Here every cpuload thread is pinned too and arms are named by placement (fma,
# in gpu_cpu6, is not pinned: its host thread was measured at <=1% CPU). Only cpu6,
# cpu6_prio and gpu_cpu6 keep their names, and even they now place exactly one
# thread per core instead of leaving six threads to the scheduler. The window
# sampler also runs during every probe here, idle arms included, which no
# earlier run did. Compare within this run, by pairing. Where the probe's own
# core carries load: cpu6, cpu6_prio and gpu_cpu6 only.
#
# The core lists are fixed in SPEC, so the names are checked against the pins
# before round 1: the probe must be off QEMU's cores (m_require_disjoint), every
# _q core must be one of QEMU's, every _nq core must be off QEMU's cores and off
# the probe's. Overriding QEMU_CORES or CORE_PROBE so that a label -- including
# "only the cpu6 arms load the probe's core" -- stops being true refuses the run
# instead of mislabelling it.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$here/lib-measure.sh" ] || { echo "FATAL: lib-measure.sh not found beside $0" >&2; exit 1; }
. "$here/lib-measure.sh"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }
[ $# -eq 0 ] || die "positional arguments are no longer read (set N=, K= in the environment); got: $*"

GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7100}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
PROBE="$HOME/interference/latency_probe.py"
FMA="$HOME/gpuload/fma"
CPULOAD="$HOME/interference/cpuload"
GPU_MIN_PCT="${GPU_MIN_PCT:-50}"
FULL=6        # cpu6 pins one thread to every core, and the SPEC names cores 0-5

ARMS=(idle cpu2_q cpu2_nq cpu3_q cpu6 cpu6_prio gpu_cpu6 idle2)
LOADED=(cpu2_q cpu2_nq cpu3_q cpu6 cpu6_prio gpu_cpu6)
SAMPLE_WINDOW=1           # trace every probe window; see lib-measure.sh
FIFO_ARMS="cpu6_prio"     # the gate requires SCHED_FIFO 50 here, SCHED_OTHER elsewhere
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))

# tag -> spec. A case table, not a function that can
# die: the review found the old arm_spec's die ran inside $(...), exited only the
# subshell, and let an unknown arm run UNLOADED under its own label. The arm list
# is validated against this table before round 1 instead.
#
# Fields: threads, cores ("-" for none), gpu (0/1), probe real-time priority (0/1).
declare -A SPEC=(
	[idle]="0 - 0 0"                  [idle2]="0 - 0 0"
	[cpu2_q]="2 0,1 0 0"              [cpu2_nq]="2 3,5 0 0"
	[cpu3_q]="3 0,1,2 0 0"            [cpu6]="6 0,1,2,3,4,5 0 0"
	[cpu6_prio]="6 0,1,2,3,4,5 0 1"   [gpu_cpu6]="6 0,1,2,3,4,5 1 0"
)

cleanup() { say "cleanup"; m_sampler_stop; m_load_stop; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

run_arm() {   # $1 tag  $2 round
	local tag="$1" r="$2" t="$1_r$2" thr cores gpu prio pre=""
	read -r thr cores gpu prio <<< "${SPEC[$tag]}"
	m_thermal "r$r $tag before" >> "$OUT/thermal.log"
	[ "$thr" -gt 0 ] && m_load_start "$OUT/load-$t.log" "$CPULOAD" "$SECS" "$thr" "$cores"
	[ "$gpu" = 1 ]   && m_load_start "$OUT/gpu-$t.log"  "$FMA" "$SECS" "$t"
	if [ -n "$LOAD_PIDS" ]; then
		sleep 3
		m_load_require_alive "after its 3 s settle"
	fi
	[ "$thr" -gt 0 ] && m_load_require_pinned "$OUT/load-$t.log" "$cores"
	if [ "$gpu" = 1 ]; then
		m_require_gpu_busy "$GPU_MIN_PCT"
		echo "r$r $tag GR3D ${GPU_PCT}% (verified >= ${GPU_MIN_PCT}%)" >> "$OUT/thermal.log"
	fi
	m_thermal "r$r $tag during" >> "$OUT/thermal.log"
	[ "$prio" = 1 ] && pre="sudo -n chrt -f 50"
	m_probe "$OUT" "$t" "$GUEST" "$PORT" "$pre"
	[ -n "$LOAD_PIDS" ] && m_load_require_alive "when the probe finished"
	m_load_stop
	m_thermal "r$r $tag after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
for a in "${ARMS[@]}"; do [ -n "${SPEC[$a]:-}" ] || die "arm '$a' has no load spec"; done
for f in "$PROBE" "$FMA" "$CPULOAD"; do [ -r "$f" ] || die "missing: $f"; done
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
m_require_balanced_k "$K" "${#LOADED[@]}"
m_prepare_out "${OUT:-}" "$HOME/saturation-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE"
[ "$NCPU" -eq "$FULL" ] || die "arm labels assume $FULL cores (cpu6 = fully committed); this host has $NCPU"
sudo -n chrt -f 50 true 2>/dev/null \
	|| die "real-time priority unavailable (sudo -n chrt -f 50); cpu6_prio would not be a priority control"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
qset=" $(_cpuset "$QEMU_CORES") "
for a in "${LOADED[@]}"; do
	read -r _thr cores _gpu _prio <<< "${SPEC[$a]}"
	for c in ${cores//,/ }; do
		case "$a" in
			*_q)  [[ "$qset" == *" $c "* ]] || die "$a names core $c, which is not a QEMU core ($QEMU_CORES)" ;;
			*_nq) [[ "$qset $CORE_PROBE " != *" $c "* ]] || die "$a names core $c, a QEMU or probe core" ;;
		esac
	done
done
m_sampler_preflight
m_reachable "$GUEST" "$PORT" "guest monitor"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "saturation"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"loads\": \"cpuload pinned per thread and read back; fma unpinned (host thread measured <=1% CPU)\"}" \
	'"load_placement": {"cpu2_q": [0,1], "cpu2_nq": [3,5], "cpu3_q": [0,1,2], "cpu6": [0,1,2,3,4,5], "cpu6_prio": [0,1,2,3,4,5], "gpu_cpu6": [0,1,2,3,4,5]}' \
	"\"fma_sha256\": \"$(_sha "$FMA")\"" \
	"\"cpuload_sha256\": \"$(_sha "$CPULOAD")\"" \
	"\"gpu_min_busy_pct\": $GPU_MIN_PCT" \
	'"probe_priority": "SCHED_FIFO 50 in cpu6_prio only; reported by the probe itself in every arm file and checked by the gate"' \
	"\"load_policy\": \"started, verified alive after 3 s and at probe end, stopped at probe end; ceiling ${SECS}s\"" \
	'"order": "Williams over the six loaded arms (period 6); idle first and idle2 last every round"' \
	'"gpu_footprint": "fma host thread measured at <=1% CPU (it blocks in cudaDeviceSynchronize); gpu_cpu6 vs cpu6 is close to matched"' \
	'"sampler": "tegrastats + EMC (bpmp and ccf debugfs) + GPU devfreq, every 500 ms across each probe window"' \
	'"arms": ["idle", "cpu2_q", "cpu2_nq", "cpu3_q", "cpu6", "cpu6_prio", "gpu_cpu6", "idle2"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, Williams-counterbalanced -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order="$(m_round_order "$r" "${ARMS[@]}")"
	echo "round $r order: $order" >> "$OUT/order.log"
	for tag in $order; do run_arm "$tag" "$r"; done
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" idle "${ARMS[@]}"
