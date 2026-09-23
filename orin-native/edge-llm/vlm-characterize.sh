#!/usr/bin/env bash
# vlm-characterize.sh -- the VLM as a SERVICE on L4T, beside the running QNX guest.
#
# Phase 3b / A6, the VLM service arm, step 2 of the plan. Before the QNX
# monitor can judge a VLM's claim it needs a bound on how long an honest one
# takes, and that bound has to come from a measured distribution, not a guess:
# a bound set too low makes an honest but slow claim "implausible" and confuses
# lateness with nonsense. This measures that distribution, with the model
# resident the way the service will run it.
#
# WHAT IT DOES, in order:
#   1. refuses to start if another run holds the lock or any llama-server is
#      already resident (a leftover server silently loads every later "idle")
#   2. pins the governor, drops the page cache (cudaMalloc does not reclaim it)
#   3. a functional smoke probe of the guest monitor on :7100 -- nothing resident
#   4. starts ONE llama-server with the vision encoder, pinned off QEMU's cores
#      and the probe's, and reads the pin back
#   5. REQS requests: every MNIST digit, REPS times per round, ROUNDS rounds, the
#      first WARMUP marked and excluded; tegrastats across the whole window
#   6. the same smoke probe again, the server still resident
#   7. stops the server (TERM, then KILL -- do not trust TERM alone), confirms it
#      is gone, restores the governor
#
# WHAT IT IS NOT. The smoke probes are FUNCTIONAL: they show the guest monitor
# still answers, with rejected_by_monitor == 0, while a vision model is resident
# beside it. They are not an interference figure -- no k rounds, no pairing, no
# load running during them. And the request timings are the model's own on
# L4T; nothing here crosses the partition.
#
# set -u only, like the rest of this harness family; see run-llm-interference.sh.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

OUT="${OUT:-$HOME/vlm-characterize-out/$(date -u +%Y%m%dT%H%M%SZ)}"
GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7100}"
NO_GUEST="${NO_GUEST:-0}"
SRV_PORT="${SRV_PORT:-8089}"
CORE_SRV="${CORE_SRV:-3,5}"            # off QEMU (0-2) and off the probe (4)
SRV_THREADS="${SRV_THREADS:-2}"
BIN="${LLAMA_BIN:-$HOME/llama.cpp/build/bin}"
MODELS="${LLAMA_MODELS:-$HOME/models}"
MODEL="${MODEL:-SmolVLM-500M-Instruct-Q8_0.gguf}"
MMPROJ="${MMPROJ:-mmproj-SmolVLM-500M-Instruct-Q8_0.gguf}"
CTX="${CTX:-2048}"
BATCH="${BATCH:-512}"
UBATCH="${UBATCH:-128}"
REPS="${REPS:-20}"
ROUNDS="${ROUNDS:-5}"
WARMUP="${WARMUP:-10}"
IMAGES="${IMAGES:-/usr/src/tensorrt/data/mnist}"
PROBE="${PROBE:-$HOME/interference/latency_probe.py}"
SMOKE_N="${SMOKE_N:-200}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"

SRV_PID=""
SRV_ARGV=(taskset -c "$CORE_SRV" "$BIN/llama-server"
	-m "$MODELS/$MODEL" --mmproj "$MODELS/$MMPROJ"
	-ngl 99 -c "$CTX" -b "$BATCH" -ub "$UBATCH" -t "$SRV_THREADS" -np 1
	--host 127.0.0.1 --port "$SRV_PORT")

ts_stop() {   # tegrastats runs as root: kill every match as root, never wait on it
	local p
	for p in $(pgrep -f '[t]egrastats --interval' || true); do sudo -n kill "$p" 2>/dev/null || true; done
	sleep 1
}

srv_stop() {
	[ -n "$SRV_PID" ] || return 0
	local i
	kill -TERM "$SRV_PID" 2>/dev/null
	for i in 1 2 3 4 5 6; do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.5; done
	kill -KILL "$SRV_PID" 2>/dev/null
	wait "$SRV_PID" 2>/dev/null
	SRV_PID=""
}

cleanup() { say "cleanup"; ts_stop; srv_stop; m_governor_restore; }
trap cleanup EXIT

smoke() {   # $1 tag -- functional only: the guest monitor answers, and accepts
	local tag="$1"
	[ "$NO_GUEST" = 1 ] && { echo "smoke $tag: skipped (NO_GUEST=1)" >> "$OUT/smoke.log"; return 0; }
	taskset -c 4 python3 "$PROBE" --host "$GUEST" --port "$PORT" --n "$SMOKE_N" --warmup 20 \
		--interval-ms 2 --tag "smoke-$tag" --out "$OUT/smoke-$tag.json" >> "$OUT/smoke.log" 2>&1 \
		|| die "smoke probe $tag failed -- see $OUT/smoke.log"
	python3 - "$OUT/smoke-$tag.json" "$SMOKE_N" <<'PY' || die "smoke probe $tag is not clean"
import json, sys
s = json.load(open(sys.argv[1]))
s = s.get("summary", s)
ok = s.get("n") == int(sys.argv[2]) and s.get("rejected_by_monitor") == 0 and s.get("bad") == 0
print("smoke %s: n=%s rejected=%s p50_ms=%.4f %s" % (s.get("tag"), s.get("n"), s.get("rejected_by_monitor"),
      s.get("p50_ms", float("nan")), "ok" if ok else "NOT CLEAN"))
sys.exit(0 if ok else 1)
PY
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another characterisation holds $LOCK"
# By argv[0] (m_pids_of), never pgrep -f: the first launch of this script died
# on its own guard because the ssh session that started it had the words
# "llama-server" in its command line, and pgrep -f matched that.
if [ -n "$(m_pids_of llama-server)" ]; then
	die "a llama-server is already resident -- it would load every 'idle' of any later run; stop it first"
fi
for f in "$BIN/llama-server" "$MODELS/$MODEL" "$MODELS/$MMPROJ" "$here/vlm_request.py" "$PROBE"; do
	[ -r "$f" ] || die "missing: $f"
done
for d in 0 1 2 3 4 5 6 7 8 9; do [ -r "$IMAGES/$d.pgm" ] || die "missing: $IMAGES/$d.pgm"; done
mkdir -p "$OUT" || die "cannot create $OUT"
[ -e "$OUT/requests.jsonl" ] && die "$OUT already holds a run"
: > "$OUT/smoke.log"
if [ "$NO_GUEST" != 1 ]; then
	m_reachable "$GUEST" "$PORT" "guest monitor"
	[ -n "$(m_pids_of qemu-system-aarch64)" ] || die "the guest monitor answers but no QEMU is running here"
fi
m_governor_pin
sync
sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || die "cannot drop the page cache"
free -m | sed -n 2p > "$OUT/mem-before.txt"
say "page cache dropped: $(cat "$OUT/mem-before.txt")"

smoke before

# ---------------------------------------------------------------- the server
"${SRV_ARGV[@]}" > "$OUT/server.log" 2>&1 < /dev/null &
SRV_PID=$!
up=0
for _ in $(seq 1 90); do
	kill -0 "$SRV_PID" 2>/dev/null || die "llama-server exited during load -- see $OUT/server.log"
	curl -s "http://127.0.0.1:$SRV_PORT/health" 2>/dev/null | grep -q '"ok"' && { up=1; break; }
	sleep 1
done
[ "$up" = 1 ] || die "llama-server did not report healthy in 90 s"
aff="$(taskset -pc "$SRV_PID" 2>/dev/null | sed 's/.*: //')"
[ "$(_cpuset "$aff")" = "$(_cpuset "$CORE_SRV")" ] \
	|| die "llama-server is on cores '$aff', not '$CORE_SRV'"
free -m | sed -n 2p > "$OUT/mem-resident.txt"
say "server resident on cores $aff: $(cat "$OUT/mem-resident.txt")"

# ---------------------------------------------------------------- the requests
sudo -n tegrastats --interval 500 > "$OUT/ts-requests.log" 2>/dev/null &
sleep 1
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/requests.start"
taskset -c 5 python3 "$here/vlm_request.py" --server "http://127.0.0.1:$SRV_PORT" --characterize \
	--images "$IMAGES" --reps "$REPS" --rounds "$ROUNDS" --warmup "$WARMUP" \
	--out "$OUT/requests.jsonl" > "$OUT/summary.txt" 2>&1 \
	|| die "the request run failed -- see $OUT/summary.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/requests.end"
ts_stop
kill -0 "$SRV_PID" 2>/dev/null || die "llama-server died during the run -- see $OUT/server.log"

smoke after

srv_stop
[ -n "$(m_pids_of llama-server)" ] && die "a llama-server is still resident after the stop"
free -m | sed -n 2p > "$OUT/mem-after.txt"
m_governor_restore

# ---------------------------------------------------------------- the stamp
# A separate Python file fed by the environment, not a heredoc: this harness has
# lost backslashes to heredocs before, and the stamp must record exactly what ran.
BIN="$BIN" MODELS="$MODELS" MODEL="$MODEL" MMPROJ="$MMPROJ" CORE_SRV="$CORE_SRV" \
	REPS="$REPS" ROUNDS="$ROUNDS" WARMUP="$WARMUP" IMAGES="$IMAGES" NO_GUEST="$NO_GUEST" \
	SRV_ARGV_STR="${SRV_ARGV[*]}" python3 "$here/vlm_stamp.py" "$OUT" || die "stamp failed"

say "done -> $OUT"
cat "$OUT/summary.txt"
cat "$OUT/smoke.log" | grep '^smoke' || true
