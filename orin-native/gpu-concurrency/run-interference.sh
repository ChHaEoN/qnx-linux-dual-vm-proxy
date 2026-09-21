#!/usr/bin/env bash
# run-interference.sh -- does saturating the GPU on L4T change the QNX guest's
# responsiveness?
#
# ARMS, per round:
#
#   idle    no load beside the guest              -- baseline, and the pairing reference
#   gpu     fma.cu saturating the iGPU            -- the question
#   cpu_q   ONE busy core, PINNED to core 0       -- on one of QEMU's cores
#   cpu_nq  ONE busy core, PINNED to core 5       -- off QEMU's cores and the probe's
#   idle2   no load                               -- drift bracket
#
# cpu_q AND cpu_nq REPLACE AN UNPINNED "cpu" ARM (2026-09-21). An independent
# analysis of the first runs found the single unpinned thread's cost followed
# the core the scheduler happened to pick, read from one sample before each
# probe. With c7 enabled: ~0 on core 3, +2 to +14 us on cores 0-1, +35 to +53
# us on core 2. With c7 disabled: +18 to +22 us on any of QEMU's cores 0-2, and
# -2 to +3 us on cores 3-5. An arm named by count alone was a placement lottery.
# Same count, stated placement, one pair: if the cost follows QEMU's cores,
# cpu_q - cpu_nq is where it shows. cpuload pins each thread at creation, reads
# it back, and exits non-zero if the pin did not take; the harness then checks
# cpuload's own "(verified)" lines, which a stale unpinned binary cannot print.
#
# THE WINDOW IS TRACED (SAMPLE_WINDOW=1): per-core CPU, GR3D, the memory
# controller's utilisation and clock (tegrastats EMC_FREQ, as root), both debugfs
# EMC readings and the GPU clock, every 500 ms across each probe -- so placement
# is observed during the measurement rather than once before it, and the memory
# system, the open hypothesis for the gpu arm's speed-up, is finally recorded.
#
# k ROUNDS (owner decision OD11, 2026-09-21). The first run of this experiment
# measured each arm once. On this board the between-run spread of a p50 is ~69x
# its within-run sampling noise, so a single pass could not tell a load effect
# from run-to-run motion. Every figure is now the median of k round-medians with
# its band, and the effect to cite is the PAIRED column: the median over rounds
# of (arm - idle) measured in the same round.
#
# THE cpu ARMS, AND WHAT THEY ARE NOT. The one-thread CPU load was designed as a
# "faithful CPU twin of fma.cu's driver thread", so that gpu - cpu would
# separate "GPU busy" from "system busy". That premise is false: during all 12
# gpu arms on 2026-09-21 no core exceeded 1% CPU -- fma's host thread blocks in
# cudaDeviceSynchronize. So the gpu arm adds a GPU load and essentially no CPU,
# while cpu_q and cpu_nq each add one full busy core, and gpu - cpu mixes two
# different things. Read cpu_q and cpu_nq as "one busy core, here", not as a
# control for the gpu arm.
#
# STALLS ARE RECORDED, NOT FATAL (owner decision, 2026-09-21). A board dry run
# of this tooling found that with two of QEMU's three cores loaded the guest can
# stop answering for longer than the probe's 10 s timeout, then
# recover. So STALL_POLICY=record: a stalled round leaves stall-<tag>.json (the
# samples before it, where it happened, the probe's own scheduling report) in
# place of lat-<tag>.json, the load is stopped, the time until the guest answers
# again goes to recovery-<tag>.json, and the run goes on. Every other failure
# still stops the run. A stalled round has no median, so the summary reports
# stalls per arm beside k, and k counts complete rounds only.
#
# COUNTERBALANCED. Loaded arms carry heat into whatever runs next. Three loaded
# arms need a Williams design of period 6 for every ordered pair to be adjacent
# equally often, so K must be a multiple of 6; the default of 12 is.
#
# WHAT IS VERIFIED, NOT ASSUMED, in every loaded arm: the load process is alive
# after its settle time and still alive when the probe finishes, a cpu arm's
# thread confirmed its own pin, the gpu arm shows GR3D at 50% or more, and every
# window's trace holds at least half the samples its length calls for. Any
# failure stops the run, except a stall (above). Before 2026-09-21 a CUDA load
# that failed to start left an idle measurement filed under "gpu".
# The load is stopped the moment the probe ends, so it does not go on heating
# the board into the next arm.
#
# COMPARABILITY -- none of these figures pairs with an earlier run. 2026-09-19
# used n=3000 and k=1, did not pin the probe or QEMU, let each load run its full
# duration, and pinned the governor by hand. The first 2026-09-21 runs had one
# unpinned "cpu" arm where cpu_q and cpu_nq now stand, and ran no window
# sampler. The sampler (tegrastats plus a root shell loop, both unpinned) runs
# during every probe here, idle arms included, so even idle and gpu are not
# strictly the same condition as before. Compare within this run, by pairing.
#
# PINNING. QEMU on 0-2 and the probe on 4, per measurement-design §3.5, and each
# cpuload thread on the core its arm names. fma is not pinned: its host thread
# was measured at <=1% CPU, so there is no busy thread to place. Orin only:
# needs the GPU, tegrastats and the CUDA load generator.
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
CORE_Q="${CORE_Q:-0}"      # a QEMU core, for cpu_q
CORE_NQ="${CORE_NQ:-5}"    # off QEMU (0-2) and off the probe (4), for cpu_nq
SAMPLE_WINDOW=1           # trace every probe window; see lib-measure.sh
FIFO_ARMS=""              # no arm here runs the probe at real-time priority
STALL_POLICY=record       # a stall is an outcome; see the header

ARMS=(idle gpu cpu_q cpu_nq idle2)
LOADED=(gpu cpu_q cpu_nq)
# Generous ceiling only: the load is stopped as soon as the probe finishes.
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 + PROBE_TIMEOUT_S ))

cleanup() { say "cleanup"; m_sampler_stop; m_load_stop; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

run_arm() {   # $1 tag  $2 round
	local tag="$1" r="$2" t="$1_r$2" prc
	m_thermal "r$r $tag before" >> "$OUT/thermal.log"
	case "$tag" in
		gpu) m_load_start "$OUT/load-$t.log" "$FMA" "$SECS" "$t" ;;
		cpu_q)  m_load_start "$OUT/load-$t.log" "$CPULOAD" "$SECS" 1 "$CORE_Q" ;;
		cpu_nq) m_load_start "$OUT/load-$t.log" "$CPULOAD" "$SECS" 1 "$CORE_NQ" ;;
	esac
	if [ -n "$LOAD_PIDS" ]; then
		sleep 3
		m_load_require_alive "after its 3 s settle"
	fi
	case "$tag" in
		cpu_q)  m_load_require_pinned "$OUT/load-$t.log" "$CORE_Q" ;;
		cpu_nq) m_load_require_pinned "$OUT/load-$t.log" "$CORE_NQ" ;;
	esac
	if [ "$tag" = gpu ]; then
		m_require_gpu_busy "$GPU_MIN_PCT"
		echo "r$r $tag GR3D ${GPU_PCT}% (verified >= ${GPU_MIN_PCT}%)" >> "$OUT/thermal.log"
	fi
	m_thermal "r$r $tag during" >> "$OUT/thermal.log"
	m_probe "$OUT" "$t" "$GUEST" "$PORT"; prc=$?
	[ -n "$LOAD_PIDS" ] && m_load_require_alive "when the probe finished"
	m_load_stop
	[ "$prc" -eq 3 ] && m_await_recovery "$OUT" "$t" "$GUEST" "$PORT"
	m_thermal "r$r $tag after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
m_build_cpuload "$here/cpuload.c" "$CPULOAD"
for f in "$PROBE" "$FMA" "$CPULOAD"; do [ -r "$f" ] || die "missing: $f"; done
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
m_require_balanced_k "$K" "${#LOADED[@]}"
m_prepare_out "${OUT:-}" "$HOME/interference-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
# cpu_q must land on a QEMU core and cpu_nq must not, or the pair tests nothing.
[[ " $(_cpuset "$QEMU_CORES") " == *" $CORE_Q "* ]] || die "CORE_Q=$CORE_Q is not one of the QEMU cores ($QEMU_CORES)"
[[ " $(_cpuset "$QEMU_CORES") $CORE_PROBE " != *" $CORE_NQ "* ]] || die "CORE_NQ=$CORE_NQ is a QEMU or probe core"
m_sampler_preflight
m_reachable "$GUEST" "$PORT" "guest monitor"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "interference"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"loads\": \"cpuload pinned per thread and read back; fma unpinned (host thread measured <=1% CPU)\"}" \
	"\"fma_sha256\": \"$(_sha "$FMA")\"" \
	"\"cpuload_sha256\": \"$(_sha "$CPULOAD")\"" \
	"\"cpuload_c_sha256\": \"$(_sha "$here/cpuload.c")\"" \
	"\"gpu_min_busy_pct\": $GPU_MIN_PCT" \
	"\"load_policy\": \"started, verified alive after 3 s and at probe end, stopped at probe end; ceiling ${SECS}s\"" \
	'"order": "Williams over the three loaded arms (period 6); idle first and idle2 last every round"' \
	"\"load_placement\": {\"cpu_q\": [$CORE_Q], \"cpu_nq\": [$CORE_NQ]}" \
	'"sampler": "root tegrastats (per-core CPU, EMC_FREQ, GR3D) + EMC rate (bpmp and ccf debugfs) + GPU devfreq, every 500 ms nominal across each probe window; at least half that rate required per window"' \
	'"arms": ["idle", "gpu", "cpu_q", "cpu_nq", "idle2"]'

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
