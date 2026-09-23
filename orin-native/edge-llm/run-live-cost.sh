#!/usr/bin/env bash
# run-live-cost.sh -- what does the liveness deadline cost the verdict round trip?
#
# Phase 3b / A6, the liveness deadline (OD14), its cost figure. The same guest
# boot of ifs-live.bin and the same binary, two instances of it:
#
#   tcp   :7100, the original TCP mode (serve_one_client, frameio_read_frame)
#   svc   :7102, the deadline mode, `svc 2000` (serve_svc: poll() before every
#         read, a monotonic clock read per wait and per frame)
#
# The probe sends the pinned mnist frame to both, so the only difference is the
# mode that serves it. AB/BA CROSSOVER over K rounds: odd rounds tcp then svc,
# even rounds svc then tcp. K must be even. The figure is the paired contrast,
# svc - tcp in the same round.
#
# THE DEADLINE FIRES BETWEEN ARMS, NEVER INSIDE ONE. Each svc arm ends with a
# silence, and 2 s later the monitor prints LIVENESS MISS on the serial console
# -- an emulated UART, where every byte is a trap into QEMU. So after each svc
# arm the harness waits until that MISS line has appeared (and requires exactly
# one) before the next arm starts. Each svc arm's first frame prints RESTORED;
# that frame is a warm-up frame, discarded, and the line is printed after its
# reply is sent.
#
# NO LOAD, checked as run-vlm-verdict.sh checks it: no known load process at
# preflight, GR3D 0% at preflight and on every tegrastats line of every window.
# A STALL STOPS THE RUN (STALL_POLICY=refuse).
#
# set -u only, like the rest of this harness family.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
TCP_PORT="${TCP_PORT:-7100}"
SVC_PORT="${SVC_PORT:-7102}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
PROBE="${PROBE:-$here/../gpu-concurrency/latency_probe.py}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
MISS_WAIT_S="${MISS_WAIT_S:-6}"          # the deadline is 2 s; this is how long to wait for its line
SAMPLE_WINDOW=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"

ARMS=(tcp svc)

cleanup() { say "cleanup"; m_sampler_stop; m_cstate_restore; m_governor_restore; }
trap cleanup EXIT

misses() { tr -d '\0\r' < "$CONSOLE" | grep -ac "LIVENESS MISS"; }
restored() { tr -d '\0\r' < "$CONSOLE" | grep -ac "LIVENESS RESTORED"; }
await_miss() {   # $1 the MISS count before; waits for one more, returns the count seen
	local m0="$1" i m
	m="$(misses)"
	for i in $(seq 1 $((MISS_WAIT_S * 10))); do
		[ "$m" -gt "$m0" ] && break
		sleep 0.1
		m="$(misses)"
	done
	echo "$m"
}

# Every tegrastats line of the window must show GR3D, and every one must read 0%.
gpu_idle_in_window() {   # $1 tag
	local log="$OUT/tegra-$1.log"
	grep -qE 'GR3D_FREQ [0-9]+%' "$log" 2>/dev/null \
		|| die "no GR3D reading in $1's window ($log) -- the no-load premise is unverified"
	! grep -qE 'GR3D_FREQ [1-9][0-9]*%' "$log" \
		|| die "GR3D above 0% during $1 -- a GPU load ran beside this no-load run"
}

# Console accounting, by counts rather than by time: an svc arm opens with one
# RESTORED (its first warm-up frame, after a silence already reported) and ends
# with one MISS (its trailing silence, awaited here before the next arm); a
# second RESTORED would mean the stream fell silent for a deadline INSIDE the
# window. A tcp arm prints neither.
run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" port m0 r0 m rr
	port="$TCP_PORT"; [ "$a" = svc ] && port="$SVC_PORT"
	m0="$(misses)"; r0="$(restored)"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	m_probe "$OUT" "$t" "$GUEST" "$port"
	gpu_idle_in_window "$t"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	if [ "$a" = svc ]; then
		m="$(await_miss "$m0")"
		rr="$(restored)"
		[ "$m" -eq $((m0 + 1)) ] \
			|| die "after $t: expected exactly one LIVENESS MISS within ${MISS_WAIT_S} s, saw $((m - m0))"
		[ "$rr" -eq $((r0 + 1)) ] \
			|| die "$t: expected exactly one LIVENESS RESTORED (its first frame), saw $((rr - r0)) -- a silence inside the window?"
	else
		m="$(misses)"; rr="$(restored)"
		[ "$m" -eq "$m0" ] && [ "$rr" -eq "$r0" ] \
			|| die "$t: the deadline-mode monitor printed during a tcp arm (MISS +$((m - m0)), RESTORED +$((rr - r0)))"
	fi
	echo "$t miss+$((m - m0)) restored+$((rr - r0))" >> "$OUT/misses.log"
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
[ -r "$CONSOLE" ] || die "missing: $CONSOLE"
tr -d '\0\r' < "$CONSOLE" | grep -aq "listening on :$SVC_PORT (frame=64 bytes, conf_min=60%), liveness deadline 2000 ms" \
	|| die "the guest console shows no 2000 ms deadline-mode monitor on :$SVC_PORT -- is this ifs-live?"
tr -d '\0\r' < "$CONSOLE" | grep -aq "safety monitor listening on :$TCP_PORT (frame=64 bytes" \
	|| die "the guest console shows no plain TCP monitor on :$TCP_PORT"
command -v tegrastats >/dev/null || die "tegrastats absent -- this experiment is Orin-only"
m_prepare_out "${OUT:-}" "$HOME/live-cost-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_sampler_preflight
m_reachable "$GUEST" "$TCP_PORT" "the plain TCP monitor instance"
m_reachable "$GUEST" "$SVC_PORT" "the deadline-mode monitor instance"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "live-cost"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE}" \
	"\"ports\": {\"tcp\": $TCP_PORT, \"svc\": $SVC_PORT}" \
	'"deadline_ms": 2000' \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on both arms: class 3, conf 95, 124 us, kind 0"' \
	'"order": "AB/BA crossover: odd rounds tcp then svc, even rounds svc then tcp"' \
	'"between_arms": "after each svc arm, exactly one LIVENESS MISS awaited on the console before the next arm"' \
	"\"gpu_load\": \"none: no $LOADS resident at preflight, GR3D 0% at preflight and on every tegrastats line of every window\"" \
	'"arms": ["tcp", "svc"]'

# ---------------------------------------------------------------- prologue
# One claim, then its silence reported: every svc arm then opens the same way,
# whether this boot was armed before (a demo ran) or not.
m0="$(misses)"
python3 - "$GUEST" "$SVC_PORT" "$PROBE" <<'PY' || die "the prologue claim got no reply"
import importlib.util, socket, sys
spec = importlib.util.spec_from_file_location("probe", sys.argv[3])
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=10) as s:
    s.sendall(lp.build_frame(1))
    got = b""
    while len(got) < 64:
        c = s.recv(64 - len(got))
        if not c:
            sys.exit(1)
        got += c
PY
[ "$(await_miss "$m0")" -eq $((m0 + 1)) ] || die "the prologue claim's silence was not reported within ${MISS_WAIT_S} s"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, AB/BA crossover, tcp :$TCP_PORT vs svc :$SVC_PORT -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/misses.log"
for r in $(seq 1 "$K"); do
	if [ $((r % 2)) -eq 1 ]; then order="tcp svc"; else order="svc tcp"; fi
	echo "round $r order: $order" >> "$OUT/order.log"
	for a in $order; do run_arm "$a" "$r"; done
	say "round $r/$K done ($order)"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" tcp "${ARMS[@]}"
