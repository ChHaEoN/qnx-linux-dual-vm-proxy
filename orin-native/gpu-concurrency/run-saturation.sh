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
#   idle        no load                           baseline, and the pairing reference
#   cpu2        2 busy threads of 6 cores
#   cpu4        4 busy threads
#   cpu6        6 busy threads (fully committed)
#   cpu6_prio   6 busy threads, PROBE AT REAL-TIME PRIORITY
#   gpu_cpu6    6 busy threads + GPU saturated    worst case
#   idle2       no load                           drift bracket
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
# k ROUNDS, WILLIAMS-COUNTERBALANCED (OD11, 2026-09-21). Five loaded arms need a
# Williams design of period 10 for every ordered pair to be adjacent equally
# often -- reversing the order on alternate rounds, which the first draft did,
# balances position but not carryover, and the imbalance fell on cpu6_prio and
# gpu_cpu6. So K must be a multiple of 10, and defaults to 20 (OD11 asks k>=12).
# idle and idle2 bracket every round.
#
# WHAT IS VERIFIED in every loaded arm: each load process alive after settle and
# still alive when the probe ends; gpu_cpu6 must show GR3D at 50% or more. The
# load stops the moment the probe does.
#
# KNOWN, PRE-EXISTING, RECORDED NOT FIXED: gpu_cpu6 is not a matched-footprint
# control for cpu6. fma's driver thread keeps a core busy, so gpu_cpu6 runs seven
# busy threads against cpu6's six. A difference between them is GPU load plus
# one extra CPU thread, and cannot be attributed to the GPU alone.
#
# COMPARABILITY WITH 2026-09-19 -- none of these figures pairs with that run.
# That run used n=3000 and k=1, pinned the governor by hand, and left the probe
# and QEMU unpinned. Pinning the probe to core 4 while the load threads float
# also means the probe can share its core with a load thread in cpu2 and cpu4,
# not only in cpu6 -- which makes cpu6_prio's control matter in more arms than
# before, and makes cpu2 and cpu4 in particular a different measurement.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$here/lib-measure.sh" ] || { echo "FATAL: lib-measure.sh not found beside $0" >&2; exit 1; }
. "$here/lib-measure.sh"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }
[ $# -eq 0 ] || die "positional arguments are no longer read (set N=, K= in the environment); got: $*"

GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7100}"
N="${N:-1000}"
K="${K:-20}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
PROBE="$HOME/interference/latency_probe.py"
FMA="$HOME/gpuload/fma"
CPULOAD="$HOME/interference/cpuload"
GPU_MIN_PCT="${GPU_MIN_PCT:-50}"
FULL=6        # the arm labels cpu2/cpu4/cpu6 mean "of six"; checked below

ARMS=(idle cpu2 cpu4 cpu6 cpu6_prio gpu_cpu6 idle2)
LOADED=(cpu2 cpu4 cpu6 cpu6_prio gpu_cpu6)
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))

# tag -> "cpu-threads gpu(0/1) prio(0/1)". A case table, not a function that can
# die: the review found the old arm_spec's die ran inside $(...), exited only the
# subshell, and let an unknown arm run UNLOADED under its own label. The arm list
# is validated against this table before round 1 instead.
declare -A SPEC=(
	[idle]="0 0 0"      [idle2]="0 0 0"
	[cpu2]="2 0 0"      [cpu4]="4 0 0"      [cpu6]="6 0 0"
	[cpu6_prio]="6 0 1" [gpu_cpu6]="6 1 0"
)

cleanup() { say "cleanup"; m_load_stop; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

run_arm() {   # $1 tag  $2 round
	local tag="$1" r="$2" t="$1_r$2" thr gpu prio pre=""
	read -r thr gpu prio <<< "${SPEC[$tag]}"
	m_thermal "r$r $tag before" >> "$OUT/thermal.log"
	[ "$thr" -gt 0 ] && m_load_start "$OUT/load-$t.log" "$CPULOAD" "$SECS" "$thr"
	[ "$gpu" = 1 ]   && m_load_start "$OUT/gpu-$t.log"  "$FMA" "$SECS" "$t"
	if [ -n "$LOAD_PIDS" ]; then
		sleep 3
		m_load_require_alive "after its 3 s settle"
	fi
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
[ "$NCPU" -eq "$FULL" ] || die "arm labels assume $FULL cores (cpu6 = fully committed); this host has $NCPU"
sudo -n chrt -f 50 true 2>/dev/null \
	|| die "real-time priority unavailable (sudo -n chrt -f 50); cpu6_prio would not be a priority control"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$PORT" "guest monitor"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "saturation"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"loads\": \"unpinned, deliberately\"}" \
	"\"fma_sha256\": \"$(_sha "$FMA")\"" \
	"\"cpuload_sha256\": \"$(_sha "$CPULOAD")\"" \
	"\"gpu_min_busy_pct\": $GPU_MIN_PCT" \
	'"probe_priority": "SCHED_FIFO 50 in cpu6_prio only, verified before round 1"' \
	"\"load_policy\": \"started, verified alive after 3 s and at probe end, stopped at probe end; ceiling ${SECS}s\"" \
	'"order": "Williams over the five loaded arms (period 10); idle first and idle2 last every round"' \
	'"known_confound": "gpu_cpu6 runs 7 busy threads (6 + fma driver) against cpu6 six; not a matched-footprint control"' \
	'"arms": ["idle", "cpu2", "cpu4", "cpu6", "cpu6_prio", "gpu_cpu6", "idle2"]'

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
