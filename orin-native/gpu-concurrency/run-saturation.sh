#!/usr/bin/env bash
# run-saturation.sh — where does interference actually start?
#
# The 2026-09-19 null result had one busy core out of six. Four idle cores is not
# a contended system, so it said nothing about saturation. This escalates the CPU
# load and looks for the point where the QNX guest's round trip degrades.
#
# The guest has 2 vCPUs, which QEMU runs as host threads. As L4T's own load
# approaches the core count, those vCPU threads must compete — so if interference
# exists at all, it should appear here.
#
# ARMS
#   idle        no load                          baseline
#   cpu2        2 busy threads of 6 cores
#   cpu4        4 busy threads
#   cpu6        6 busy threads (fully committed)
#   cpu6_prio   6 busy threads, PROBE AT HIGH PRIORITY
#   gpu_cpu6    6 busy threads + GPU saturated   worst case
#   idle2       no load                          drift check
#
# WHY cpu6_prio EXISTS. Under full saturation the probe process on L4T is itself
# competing for a core, so a plain cpu6 number mixes probe-side scheduling delay
# with anything happening to the guest. Running the same arm with the probe at
# elevated priority removes most of the probe-side component: if cpu6_prio comes
# back near idle, the cpu6 degradation was mostly the PROBE waiting, not the
# guest. That distinction is the difference between a number and a result.
set -u

GUEST=192.168.100.10
PORT=7100
N="${1:-3000}"
WARMUP=200
INTERVAL_MS=2
OUT="$HOME/interference"
mkdir -p "$OUT"
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
tegra() { timeout 3 tegrastats --interval 1000 2>/dev/null | head -1 \
          | grep -oE "CPU \[[^]]*\]|GR3D_FREQ [0-9]*%|cpu@[0-9.]*C" | tr '\n' ' '; echo; }

arm() {   # $1 tag  $2 cpu-threads (0 = none)  $3 gpu (1/0)  $4 prio (1/0)
  local tag="$1" thr="$2" gpu="$3" prio="$4" pids=""
  say "--- ARM ${tag}  (cpu threads=${thr} gpu=${gpu} probe_prio=${prio})"
  echo -n "    before: "; tegra
  if [ "$thr" -gt 0 ]; then
    "$HOME/interference/cpuload" "$SECS" "$thr" > "$OUT/load-${tag}.log" 2>&1 &
    pids="$pids $!"
  fi
  if [ "$gpu" = "1" ]; then
    "$HOME/gpuload/fma" "$SECS" "$tag" > "$OUT/gpu-${tag}.log" 2>&1 &
    pids="$pids $!"
  fi
  [ -n "$pids" ] && sleep 3
  echo -n "    during: "; tegra

  local pre=""
  # chrt needs root; nice -n -20 also does. sudo -n is non-interactive and was
  # verified available. If it is refused the arm still runs, at normal priority,
  # and says so rather than silently measuring something else.
  if [ "$prio" = "1" ]; then
    if sudo -n true 2>/dev/null; then
      pre="sudo -n chrt -f 50"
    else
      echo "    !! sudo unavailable: running at NORMAL priority, arm is not a prio control"
    fi
  fi
  $pre python3 "$HOME/interference/latency_probe.py" --host "$GUEST" --port "$PORT" \
      --n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" \
      --tag "$tag" --out "$OUT/lat-${tag}.json" 2>&1 | tail -2 | sed 's/^/    /'

  for p in $pids; do wait "$p" 2>/dev/null; done
  [ -f "$OUT/gpu-${tag}.log" ] && grep -h SUMMARY "$OUT/gpu-${tag}.log" 2>/dev/null | sed 's/^/    gpu: /'
  echo -n "    after : "; tegra
  echo
}

say "nproc=$(nproc)  each arm ${N} timed samples, loads ${SECS}s"
if ! timeout 3 bash -c "echo > /dev/tcp/$GUEST/$PORT" 2>/dev/null; then
  say "monitor not reachable on :$PORT — stopping"; exit 1
fi

arm idle      0 0 0
arm cpu2      2 0 0
arm cpu4      4 0 0
arm cpu6      6 0 0
arm cpu6_prio 6 0 1
arm gpu_cpu6  6 1 0
arm idle2     0 0 0

say "summary"
for t in idle cpu2 cpu4 cpu6 cpu6_prio gpu_cpu6 idle2; do
  python3 - "$OUT/lat-${t}.json" <<'PY' 2>/dev/null
import json,sys
try: d=json.load(open(sys.argv[1]))["summary"]
except Exception: sys.exit()
print("  %-10s n=%-5d p50=%7.3f p90=%7.3f p99=%8.3f max=%9.3f  bad=%d" %
      (d["tag"], d["n"], d["p50_ms"], d["p90_ms"], d["p99_ms"], d["max_ms"], d["bad"]))
PY
done
