#!/usr/bin/env bash
# run-interference.sh — does saturating the GPU on L4T change the QNX guest's
# responsiveness?
#
# FOUR ARMS, in this order, deliberately:
#
#   A   idle            no load beside the guest          -- baseline
#   B   gpu             fma.cu saturating the iGPU        -- the question
#   C   cpu             cpuload, same CPU footprint, no GPU -- the control that
#                       separates "GPU busy" from "system busy"
#   A2  idle again      no load                           -- drift check
#
# A2 matters: the board starts near 47 C and heats under B and C. Without it, a
# thermal or frequency drift would be indistinguishable from an effect of the
# load. If A2 does not return near A, the run is not interpretable and says so.
#
# Each arm holds ONE TCP connection and times a fixed number of frames, so the
# number is the service round trip, not TCP setup.
set -u

GUEST=192.168.100.10
PORT=7100
N="${1:-2000}"
WARMUP=200
INTERVAL_MS=2
OUT="$HOME/interference"
mkdir -p "$OUT"

say() { echo "[$(date -u +%H:%M:%S)] $*"; }

sample_tegra() {   # $1 = tag ; one line of tegrastats, for the record
	timeout 3 tegrastats --interval 1000 2>/dev/null | head -1 \
		| grep -oE "CPU \[[^]]*\]|GR3D_FREQ [0-9]*%|cpu@[0-9.]*C" | tr '\n' ' '
	echo
}

arm() {            # $1 = tag ; $2 = load command ("" for idle)
	local tag="$1" load="$2"
	say "--- ARM ${tag}"
	echo -n "    before: "; sample_tegra
	if [ -n "$load" ]; then
		( eval "$load" ) > "$OUT/load-${tag}.log" 2>&1 &
		local lp=$!
		sleep 3                      # let the load reach steady state
	fi
	echo -n "    during: "; sample_tegra
	python3 "$HOME/interference/latency_probe.py" --host "$GUEST" --port "$PORT" \
		--n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" \
		--tag "$tag" --out "$OUT/lat-${tag}.json" 2>&1 | sed 's/^/    /'
	if [ -n "$load" ]; then
		wait ${lp} 2>/dev/null
		tail -2 "$OUT/load-${tag}.log" 2>/dev/null | sed 's/^/    load: /'
	fi
	echo -n "    after : "; sample_tegra
	echo
}

# Duration of each load must exceed the probe window: n * interval + warmup.
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))
say "each arm: ${N} timed samples (+${WARMUP} warm-up discarded), load ${SECS}s"

say "guest check"
echo "  qemu=$(pgrep -c '[q]emu-system' 2>/dev/null || echo 0)  br0=$(cat /sys/class/net/br0/operstate 2>/dev/null)"
if ! timeout 3 bash -c "echo > /dev/tcp/$GUEST/$PORT" 2>/dev/null; then
	say "monitor not reachable on :$PORT — stopping"
	exit 1
fi

arm idle ""
arm gpu  "$HOME/gpuload/fma ${SECS} interference"
arm cpu  "$HOME/interference/cpuload ${SECS} 1"
arm idle2 ""

say "summaries"
grep -h RESULT "$OUT"/../interference/lat-*.json >/dev/null 2>&1 || true
for t in idle gpu cpu idle2; do
	python3 - "$OUT/lat-${t}.json" <<'PY' 2>/dev/null
import json,sys
try: d=json.load(open(sys.argv[1]))["summary"]
except Exception: sys.exit()
print("  %-6s n=%-5d p50=%7.3f  p90=%7.3f  p99=%7.3f  max=%8.3f ms" %
      (d["tag"], d["n"], d["p50_ms"], d["p90_ms"], d["p99_ms"], d["max_ms"]))
PY
done
