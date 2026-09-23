#!/usr/bin/env bash
# run-vlm-verdict.sh -- what does judging a VLM claim cost, against an mnist one?
#
# Phase 3b / A6, the VLM service arm, Figure A (OD13). The same monitor
# instance, the same transport, the same guest boot; the only thing that
# differs between the two arms is the claim each timed frame carries:
#
#   mnist   latency_probe.py's pinned frame, the one every A6 run has used
#   vlm     its pre-built kind-1 claim: one honest SmolVLM-500M answer as the
#           2026-09-23 characterisation measured it
#
# Both are ACCEPTed by construction, so the gate's rejected_by_monitor == 0
# holds without choosing which claims to send -- a run that sent real claims and
# kept only the accepted ones would be selection bias. The VLM claim goes
# through check_claim()'s kind dispatch and check_vlm()'s six checks, one of
# them a 64-bit sum; the mnist claim through the unchanged check_mnist().
#
# AB/BA CROSSOVER over K rounds: odd rounds mnist then vlm, even rounds vlm then
# mnist, so each order runs K/2 times and carryover cancels over the run. K must
# be even. The figure is the paired contrast, vlm - mnist in the same round.
#
# NO GPU LOAD. The model is not running: this asks what the verdict costs, not
# what a VLM beside the guest does (that was the interference record). Checked
# twice, because a load of any name spoils it: no known load process at
# preflight, and GR3D at 0% on every tegrastats line of every window.
#
# A STALL STOPS THE RUN (STALL_POLICY=refuse, as run-ladder.sh's headlines). With
# no load there is nothing a stall could be an outcome of, and a round lost to
# one leaves the two orders unequal, so the crossover no longer cancels.
#
# The guest must be ifs-svc (the claim-kind monitor); the probe targets the
# service's instance on TCP 7102 by default.
#
# set -u only, like the rest of this harness family; see run-llm-interference.sh.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7102}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
PROBE="${PROBE:-$here/../gpu-concurrency/latency_probe.py}"
CONSOLE="${CONSOLE:-}"                   # the guest console log, to confirm ifs-svc
SAMPLE_WINDOW=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS="vlm"
# Shared with vlm-characterize.sh and vlm-demo.sh, the two other users of the
# service's llama-server and guest. Not with every board harness: the GR3D check
# below is what catches a load started by one that takes no lock.
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"

ARMS=(mnist vlm)

cleanup() { say "cleanup"; m_sampler_stop; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

# Every tegrastats line of the window must show GR3D, and every one must read 0%.
gpu_idle_in_window() {   # $1 tag
	local log="$OUT/tegra-$1.log"
	grep -qE 'GR3D_FREQ [0-9]+%' "$log" 2>/dev/null \
		|| die "no GR3D reading in $1's window ($log) -- the no-load premise is unverified"
	! grep -qE 'GR3D_FREQ [1-9][0-9]*%' "$log" \
		|| die "GR3D above 0% during $1 -- a GPU load ran beside this no-load run"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	PROBE_CLAIM="$a" m_probe "$OUT" "$t" "$GUEST" "$PORT"
	gpu_idle_in_window "$t"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
GPU_PCT="$(m_gpu_busy_pct)"
[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
[ $((K % 2)) -eq 0 ] || die "K=$K is odd; the AB/BA crossover needs an even K"
[ -r "$PROBE" ] || die "missing: $PROBE"
grep -q -- '--claim' "$PROBE" || die "$PROBE has no --claim: it predates OD13"
if [ -n "$CONSOLE" ]; then
	tr -d '\0\r' < "$CONSOLE" | grep -aq "claim kinds: 0 mnist" \
		|| die "the guest console shows no claim-kind monitor -- is this ifs-svc?"
	# Every mode prints the claim-kind line, so it cannot tell ifs-svc from
	# ifs-live (OD14), whose :7102 runs the deadline mode. Refuse that by name.
	tr -d '\0\r' < "$CONSOLE" | grep -aq "safety monitor listening on :$PORT (" \
		|| die "the guest console shows no plain TCP monitor on :$PORT -- is this ifs-svc?"
fi
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
m_prepare_out "${OUT:-}" "$HOME/vlm-verdict-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_sampler_preflight
m_reachable "$GUEST" "$PORT" "the service's monitor instance"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "vlm-verdict"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE}" \
	"\"service_port\": $PORT" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": {"mnist": "latency_probe.build_frame: class 3, conf 95, 124 us, kind 0", "vlm": "latency_probe.build_vlm_frame: class 3, conf 100, 282032 us = 269484 + 12548, kind 1, model 1"}' \
	'"order": "AB/BA crossover: odd rounds mnist then vlm, even rounds vlm then mnist"' \
	"\"gpu_load\": \"none: no $LOADS resident at preflight, GR3D 0% at preflight and on every tegrastats line of every window\"" \
	'"arms": ["mnist", "vlm"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, AB/BA crossover, port $PORT -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	if [ $((r % 2)) -eq 1 ]; then order="mnist vlm"; else order="vlm mnist"; fi
	echo "round $r order: $order" >> "$OUT/order.log"
	for a in $order; do run_arm "$a" "$r"; done
	say "round $r/$K done ($order)"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" mnist "${ARMS[@]}"
