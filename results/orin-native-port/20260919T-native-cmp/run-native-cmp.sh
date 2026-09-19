#!/usr/bin/env bash
# run-native-cmp.sh — is the QNX guest's degradation under CPU saturation
# virtualisation-specific, or is it what any process on a saturated box shows?
#
# THE SAME PROTOCOL, BY CONSTRUCTION. Both servers are monitor.c, unmodified:
# one cross-compiled into the QNX guest's IFS, one built with gcc on L4T. Same
# 64-byte frame, same accept/reject logic, same probe, same port number.
#
# WHAT IS AND IS NOT COMPARABLE. The two network paths differ -- the guest's
# round trip crosses virtio-net + br0 + tap + io-sock, the native one does not.
# So ABSOLUTE latency is not comparable and is never compared here. The
# comparable quantity is EACH PATH'S DEGRADATION AGAINST ITS OWN IDLE BASELINE.
# The QNX guest showed +54% p50 under 6-thread saturation. If native shows the
# same, the degradation is oversubscription, not virtualisation.
#
# ARMS, INTERLEAVED. native_idle, guest_idle, native_cpu6, guest_cpu6, twice.
# Interleaved because on this board a single-round difference has already
# dissolved on repeat; a difference that survives interleaving is worth keeping.
set -u

GUEST_HOST=192.168.100.10
NATIVE_HOST=127.0.0.1
PORT=7100
N="${1:-3000}"
ROUNDS="${2:-2}"
WARMUP=200
INTERVAL_MS=2
OUT="$HOME/native-cmp"
mkdir -p "$OUT"
SECS=$(( (N + WARMUP) * INTERVAL_MS / 1000 + 15 ))

say() { echo "[$(date -u +%H:%M:%S)] $*"; }

arm() {   # $1 tag  $2 host  $3 cpu-threads
  local tag="$1" host="$2" thr="$3" pids=""
  say "--- ARM ${tag}  host=${host} cpu_threads=${thr}"
  if [ "$thr" -gt 0 ]; then
    "$HOME/interference/cpuload" "$SECS" "$thr" > "$OUT/load-${tag}.log" 2>&1 &
    pids="$pids $!"
    sleep 3
  fi
  python3 "$HOME/interference/latency_probe.py" --host "$host" --port "$PORT" \
      --n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" \
      --tag "$tag" --out "$OUT/lat-${tag}.json" 2>&1 | tail -1 | sed 's/^/    /'
  for p in $pids; do wait "$p" 2>/dev/null; done
  echo
}

# Both servers must answer before any arm runs, or a missing one would look
# like a result instead of a setup error.
for hp in "$NATIVE_HOST" "$GUEST_HOST"; do
  if ! timeout 3 bash -c "echo > /dev/tcp/$hp/$PORT" 2>/dev/null; then
    say "monitor unreachable at ${hp}:${PORT} -- stopping"; exit 1
  fi
done
say "both monitors reachable; nproc=$(nproc), ${N} timed samples/arm, ${ROUNDS} rounds"
echo -n "  governor: "; for c in 0 1 2 3 4 5; do printf "%s " "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)"; done; echo

for r in $(seq 1 "$ROUNDS"); do
  say "=== ROUND $r"
  arm "native_idle_r${r}"  "$NATIVE_HOST" 0
  arm "guest_idle_r${r}"   "$GUEST_HOST"  0
  arm "native_cpu6_r${r}"  "$NATIVE_HOST" 6
  arm "guest_cpu6_r${r}"   "$GUEST_HOST"  6
done

say "summary"
for r in $(seq 1 "$ROUNDS"); do
  for t in native_idle native_cpu6 guest_idle guest_cpu6; do
    python3 - "$OUT/lat-${t}_r${r}.json" <<'PY' 2>/dev/null
import json,sys
try: d=json.load(open(sys.argv[1]))["summary"]
except Exception: sys.exit()
print("  %-18s n=%-5d p50=%7.3f p90=%7.3f p99=%8.3f max=%9.3f  bad=%d rej=%d" %
      (d["tag"], d["n"], d["p50_ms"], d["p90_ms"], d["p99_ms"], d["max_ms"],
       d["bad"], d.get("rejected_by_monitor", 0)))
PY
  done
done
