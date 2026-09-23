#!/usr/bin/env bash
# run-llm-interference.sh -- does a real generative workload on the GPU owner
# disturb the safety partition, where a synthetic FMA load did not?
#
# ARMS, per round:
#
#   idle    no load beside the guest          -- baseline, and the pairing reference
#   llm     llama.cpp decoding continuously   -- the question
#   gpu     fma.cu saturating the iGPU        -- the reference load, already characterised
#   idle2   no load                           -- drift bracket
#
# WHY A SEPARATE SCRIPT, not another arm in run-interference.sh: adding an arm
# changes the Williams order, so nothing here would be comparable arm-for-arm
# with 20260921T-a6-orin-pinned anyway, and that record's tooling stays
# byte-identical to what produced it.
#
# WHY THE llm ARM IS NOT THE gpu ARM AGAIN. Measured on this board on
# 2026-09-23 (results/orin-native-port/20260923T-a6-orin-llm-prep): at matched
# GPU occupancy fma.cu holds EMC utilisation at 0% with the memory clock at its
# idle 2133 MHz, while LLM decode drives EMC to 44-49% and forces 3199 MHz. The
# two loads differ in the resource the QNX guest's vCPUs also need.
#
# TWO LOADED ARMS, so the Williams period is 2 and the default K=12 is balanced.
#
# THE MODEL IS THE SMALL ONE, deliberately. SmolVLM-500M demands the same
# ~42.7 GB/s as the 4B while holding 0.42 GB instead of 2.50 GB, and the guest
# wants 1 GB of the same DRAM. The 4B repeatedly failed to allocate on this
# board once the page cache was warm.
#
# THE PAGE CACHE IS DROPPED AT PREFLIGHT. cudaMalloc does not reclaim it here: a
# warm cache is how the 4B failed, and a load that cannot start would file a
# quiet arm as a measurement.
#
# WHAT IS VERIFIED, NOT ASSUMED, in the llm arm: the process is alive after its
# settle and at probe end; GR3D is at least GPU_MIN_PCT; the load's affinity
# reads back as the cores asked for; and the load log GREW across the probe
# window, which is the only one of these that proves tokens were actually being
# produced rather than a process sitting in a failed state.
# set -u ONLY, matching run-interference.sh and run-ladder.sh. Do not add -e or
# -o pipefail: lib-measure.sh is written for this regime and dies explicitly, and
# m_thermal reads `tegrastats | head -1`, whose SIGPIPE on the writer is normal
# and becomes exit 141 under pipefail. That killed the first dry run here.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7100}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_LLM="${CORE_LLM:-3,5}"          # off QEMU (0-2) and off the probe (4)
PROBE="${PROBE:-$HOME/interference/latency_probe.py}"
FMA="${FMA:-$HOME/gpuload/fma}"
LLAMA="${LLAMA:-$HOME/llama.cpp/build/bin/llama-cli}"
MODEL="${MODEL:-$HOME/models/SmolVLM-500M-Instruct-Q8_0.gguf}"
GPU_MIN_PCT="${GPU_MIN_PCT:-50}"
LLM_CTX="${LLM_CTX:-4096}"
LLM_BATCH="${LLM_BATCH:-512}"
LLM_UBATCH="${LLM_UBATCH:-128}"
LLM_THREADS="${LLM_THREADS:-2}"
LLM_SETTLE_S="${LLM_SETTLE_S:-10}"
LLM_PROMPT="${LLM_PROMPT:-Describe what a memory controller does, in detail.}"
SAMPLE_WINDOW=1
FIFO_ARMS=""
STALL_POLICY=record

ARMS=(idle llm gpu idle2)
LOADED=(llm gpu)
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 + PROBE_TIMEOUT_S ))

# stop_loads, NOT m_load_stop. m_load_stop sends SIGTERM and then waits, which is
# right for fma and cpuload -- they die on it. This build's llama-cli is a chat
# REPL: SIGTERM ends the current turn, and the REPL then reads end-of-input and
# prints its "> " prompt forever instead of exiting. That blocked the harness in
# `wait` one arm into the 2026-09-23 run, and wrote ~634,000 "> " lines per arm
# into that run's load logs before the KILL. LLM_ARGV now passes -st
# (single-turn), with which TERM makes it exit cleanly (verified on the board);
# the TERM, three seconds, KILL, reap escalation stays as the backstop.
stop_loads() {
	local p i alive
	for p in $LOAD_PIDS; do kill -TERM "$p" 2>/dev/null; done
	for i in 1 2 3 4 5 6; do
		alive=0
		for p in $LOAD_PIDS; do kill -0 "$p" 2>/dev/null && alive=1; done
		[ "$alive" = 0 ] && break
		sleep 0.5
	done
	for p in $LOAD_PIDS; do kill -KILL "$p" 2>/dev/null; done
	for p in $LOAD_PIDS; do wait "$p" 2>/dev/null; done
	LOAD_PIDS=""
}

cleanup() { say "cleanup"; m_sampler_stop; stop_loads; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

# The llm load as an ARRAY, not a string a function echoes: the prompt contains
# spaces, and an unquoted expansion would split it into stray arguments that
# llama-cli would reject -- leaving a dead load and an arm measured unloaded.
# --ignore-eos so it never stops early, and stdbuf -oL so the log grows while it
# runs, which is what proves it is decoding. -st (single-turn) because this
# build's llama-cli is a chat REPL even with -p and -n: without it, the stopped
# load spins on end-of-input printing "> " (see stop_loads). There is no -no-cnv
# in this build. An earlier comment here claimed -p plus -n ran one-shot; the
# 2026-09-23 run's logs showed that was wrong.
LLM_ARGV=(taskset -c "$CORE_LLM" stdbuf -oL "$LLAMA"
	-m "$MODEL" -ngl 99 -c "$LLM_CTX" -b "$LLM_BATCH" -ub "$LLM_UBATCH"
	-t "$LLM_THREADS" -n 1000000 --ignore-eos --temp 0 --seed 42 -st
	-p "$LLM_PROMPT")

llm_require_pinned() {   # $1 = cores asked for
	local p got
	for p in $LOAD_PIDS; do
		got="$(taskset -pc "$p" 2>/dev/null | sed 's/.*: //')"
		[ -n "$got" ] || die "could not read the llm load's affinity back -- pinning unverified"
		[ "$(_cpuset "$got")" = "$(_cpuset "$1")" ] \
			|| die "llm load is on cores '$got', not '$1' -- an unpinned load is a placement lottery"
	done
}

# The check the others cannot make: a process can be alive, hold the GPU from a
# previous allocation and produce nothing. Bytes in the log are tokens.
llm_require_decoding() {   # $1 log  $2 bytes at the start of the window
	local now
	now="$(stat -c %s "$1" 2>/dev/null || echo 0)"
	[ "$now" -gt "$2" ] \
		|| die "the llm load produced no output across the probe window ($2 -> $now bytes) -- the arm would be measured unloaded"
	echo "$((now - $2))"
}

run_arm() {   # $1 tag  $2 round
	local tag="$1" r="$2" t="$1_r$2" prc log0=0 grew=""
	m_thermal "r$r $tag before" >> "$OUT/thermal.log"
	case "$tag" in
		gpu) m_load_start "$OUT/load-$t.log" "$FMA" "$SECS" "$t" ;;
		llm) m_load_start "$OUT/load-$t.log" "${LLM_ARGV[@]}" ;;
	esac
	# The llm arm settles longer than the others on purpose: fma is decoding
	# nothing and is at 99% GR3D within a second, while llama-cli must read the
	# model, upload it and run a warm-up before the first token. A 3 s settle
	# caught it at 0% GR3D and failed the arm.
	local settle=3
	[ "$tag" = llm ] && settle="$LLM_SETTLE_S"
	if [ -n "$LOAD_PIDS" ]; then
		sleep "$settle"
		m_load_require_alive "after its ${settle} s settle"
	fi
	if [ "$tag" = llm ]; then
		llm_require_pinned "$CORE_LLM"
		log0="$(stat -c %s "$OUT/load-$t.log" 2>/dev/null || echo 0)"
	fi
	if [ "$tag" = gpu ] || [ "$tag" = llm ]; then
		m_require_gpu_busy "$GPU_MIN_PCT"
		echo "r$r $tag GR3D ${GPU_PCT}% (verified >= ${GPU_MIN_PCT}%)" >> "$OUT/thermal.log"
	fi
	m_thermal "r$r $tag during" >> "$OUT/thermal.log"
	m_probe "$OUT" "$t" "$GUEST" "$PORT"; prc=$?
	[ -n "$LOAD_PIDS" ] && m_load_require_alive "when the probe finished"
	if [ "$tag" = llm ]; then
		grew="$(llm_require_decoding "$OUT/load-$t.log" "$log0")"
		echo "r$r llm produced $grew bytes of tokens across the window" >> "$OUT/thermal.log"
	fi
	stop_loads
	[ "$prc" -eq 3 ] && m_await_recovery "$OUT" "$t" "$GUEST" "$PORT"
	m_thermal "r$r $tag after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
# ONE AT A TIME, enforced with a lock rather than a pgrep. An ssh client that
# times out does not kill what it started on the board: three copies of this
# script ran concurrently on 2026-09-23, each pinning the governor, re-pinning
# QEMU and starting its own GPU load, and the numbers they produced were of each
# other. A pgrep guard cannot do this job -- the launching `sh -c` wrapper
# carries the script's path in its own command line and matches too.
LOCK="${LOCK:-/tmp/run-llm-interference.lock}"
exec 9>"$LOCK" || die "cannot open the lock file $LOCK"
flock -n 9 || die "another run holds $LOCK -- two runs would measure each other; stop it first"
for f in "$PROBE" "$FMA" "$LLAMA" "$MODEL"; do [ -r "$f" ] || die "missing: $f"; done
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
command -v stdbuf >/dev/null || die "stdbuf absent -- the llm liveness check needs line buffering"
m_require_balanced_k "$K" "${#LOADED[@]}"
m_prepare_out "${OUT:-}" "$HOME/llm-interference-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "llm=$CORE_LLM"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_sampler_preflight
m_reachable "$GUEST" "$PORT" "guest monitor"

sync
sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null \
	|| die "cannot drop the page cache; cudaMalloc does not reclaim it and the llm arm may fail to allocate"
say "page cache dropped: $(free -m | sed -n 2p)"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "llm-interference"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"llm\": \"$CORE_LLM\", \"loads\": \"llm pinned at exec and read back; fma unpinned (host thread measured <=1% CPU)\"}" \
	"\"fma_sha256\": \"$(_sha "$FMA")\"" \
	"\"llama_cli_sha256\": \"$(_sha "$LLAMA")\"" \
	"\"model\": \"$(basename "$MODEL")\"" \
	"\"model_sha256\": \"$(_sha "$MODEL")\"" \
	"\"llm_args\": \"-ngl 99 -c $LLM_CTX -b $LLM_BATCH -ub $LLM_UBATCH -t $LLM_THREADS --ignore-eos --temp 0 --seed 42 -st\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	"\"gpu_min_busy_pct\": $GPU_MIN_PCT" \
	'"page_cache": "dropped at preflight; cudaMalloc does not reclaim it on this board"' \
	"\"load_policy\": \"started, verified alive after its settle (3 s; ${LLM_SETTLE_S} s for llm) and at probe end, llm additionally verified pinned and PRODUCING OUTPUT across the window, stopped at probe end\"" \
	'"order": "Williams over the two loaded arms (period 2); idle first and idle2 last every round"' \
	'"arms": ["idle", "llm", "gpu", "idle2"]'

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
