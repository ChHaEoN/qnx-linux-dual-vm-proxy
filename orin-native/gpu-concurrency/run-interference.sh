#!/usr/bin/env bash
# run-interference.sh -- does saturating the GPU on L4T change the QNX guest's
# responsiveness?
#
# ARMS, per round:
#
#   idle    no load beside the guest              -- baseline, and the pairing reference
#   gpu     fma.cu saturating the iGPU            -- the question
#   cpu     cpuload, same CPU footprint, no GPU   -- the control that separates
#                                                   "GPU busy" from "system busy"
#   idle2   no load                               -- drift bracket
#
# k ROUNDS (owner decision OD11, 2026-09-21). The first run of this experiment
# measured each arm once. On this board the between-run spread of a p50 is ~69x
# its within-run sampling noise, so a single pass could not tell a load effect
# from run-to-run motion. Every figure is now the median of k round-medians with
# its band, and the effect to cite is the PAIRED column: the median over rounds
# of (arm - idle) measured in the same round.
#
# COUNTERBALANCED. gpu and cpu carry heat into whatever runs next. With two
# loaded arms a Williams design is simply alternation -- gpu,cpu then cpu,gpu --
# so each inherits the other's heat equally often; K must be even.
#
# WHAT IS VERIFIED, NOT ASSUMED, in every loaded arm: the load process is alive
# after its settle time and still alive when the probe finishes, and the gpu arm
# must show GR3D at 50% or more. Any failure stops the run. Before 2026-09-21 a
# CUDA load that failed to start left an idle measurement filed under "gpu".
# The load is stopped the moment the probe ends, so it does not go on heating
# the board into the next arm.
#
# COMPARABILITY WITH 2026-09-19 -- none of these figures pairs with that run.
# That run used n=3000 and k=1, did not pin the probe or QEMU, let each load run
# its full duration, and pinned the governor by hand. This one pins all three by
# script, stops each load at the end of its window, and uses n=1000 at k>=12.
#
# PINNING. QEMU on 0-2 and the probe on 4, per measurement-design §3.5. The load
# generators are LEFT UNPINNED on purpose: where they land is part of what is
# being measured. That choice is in the stamp. Orin only: needs the GPU,
# tegrastats and the CUDA load generator.
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

ARMS=(idle gpu cpu idle2)
LOADED=(gpu cpu)
# Generous ceiling only: the load is stopped as soon as the probe finishes.
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))

cleanup() { say "cleanup"; m_load_stop; m_governor_restore; }
trap cleanup EXIT

run_arm() {   # $1 tag  $2 round
	local tag="$1" r="$2" t="$1_r$2"
	m_thermal "r$r $tag before" >> "$OUT/thermal.log"
	case "$tag" in
		gpu) m_load_start "$OUT/load-$t.log" "$FMA" "$SECS" "$t" ;;
		cpu) m_load_start "$OUT/load-$t.log" "$CPULOAD" "$SECS" 1 ;;
	esac
	if [ -n "$LOAD_PIDS" ]; then
		sleep 3
		m_load_require_alive "after its 3 s settle"
	fi
	if [ "$tag" = gpu ]; then
		m_require_gpu_busy "$GPU_MIN_PCT"
		echo "r$r $tag GR3D ${GPU_PCT}% (verified >= ${GPU_MIN_PCT}%)" >> "$OUT/thermal.log"
	fi
	m_thermal "r$r $tag during" >> "$OUT/thermal.log"
	m_probe "$OUT" "$t" "$GUEST" "$PORT"
	[ -n "$LOAD_PIDS" ] && m_load_require_alive "when the probe finished"
	m_load_stop
	m_thermal "r$r $tag after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
for f in "$PROBE" "$FMA" "$CPULOAD"; do [ -r "$f" ] || die "missing: $f"; done
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
m_require_balanced_k "$K" "${#LOADED[@]}"
m_prepare_out "${OUT:-}" "$HOME/interference-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_governor_pin
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$PORT" "guest monitor"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "interference"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"loads\": \"unpinned, deliberately\"}" \
	"\"fma_sha256\": \"$(_sha "$FMA")\"" \
	"\"cpuload_sha256\": \"$(_sha "$CPULOAD")\"" \
	"\"gpu_min_busy_pct\": $GPU_MIN_PCT" \
	"\"load_policy\": \"started, verified alive after 3 s and at probe end, stopped at probe end; ceiling ${SECS}s\"" \
	'"order": "Williams over the loaded arms (period 2: gpu,cpu / cpu,gpu); idle first and idle2 last every round"' \
	'"arms": ["idle", "gpu", "cpu", "idle2"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, Williams-counterbalanced -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order="$(m_round_order "$r" "${ARMS[@]}")"
	echo "round $r order: $order" >> "$OUT/order.log"
	for tag in $order; do run_arm "$tag" "$r"; done
	say "round $r/$K done ($order)"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" idle "${ARMS[@]}"
