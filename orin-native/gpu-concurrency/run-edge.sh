#!/usr/bin/env bash
# run-edge.sh -- a fine map of the guest path from 1448 to 1472 B.
# Phase 3b / A6, 2026-09-26; follows 20260926T-a6-orin-mss.
# The owner asked for this run (2026-09-26).
#
# WHAT IS KNOWN. With one read() per frame, the guest and host paths at 1448, 1449 and 1472 B,
# and their packets each way, are in record 20260926T-a6-orin-mss (held locally). The MSS is
# 1448 B. 1460 -- the MSS the SYN advertises for MTU 1500 before the 12-byte timestamp option
# is taken off -- lies between 1449 and 1472 B. So does every size whose second segment
# (S - 1448) is between 2 and 23 bytes: this map cannot tell "the frame exceeds 1460" from "the
# second segment exceeds 12 bytes", because one determines the other at this MSS.
#
# THE MAP. As run-mss.sh: ifs-reads.bin's greedy endpoint (:7121), one read per frame that
# arrives whole, and the same source natively in a namespace. Fourteen arms:
#   G1448 G1449 G1452 G1456 G1458 G1459 G1460 G1461 G1462 G1464 G1468 G1472   the guest path
#   B1460 B1461                                                               the host path
# n=1000, 200 warm-up, 2 ms spacing, K=14 rounds in a Williams design over the fourteen arms
# (period 14); every echoed byte checked; packet counters and the endpoint's read count per
# arm. About 23 min. The host's userspace is not confined. The LAN is Ethernet since
# 2026-09-26 (the Wi-Fi still up): the stamp records the default route.
#
# THE RULE, fixed here before any run (edge_report.py applies it). As run-mss.sh: per round the
# p50 of each arm, differences paired within the round, per difference the median over rounds
# with the distribution-free interval of widest coverage >= 95% (d(3)..d(12), 98.7%, at
# K = 14); packets per exchange per arm from the device's counters, median over rounds.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the fast path begins where the frame exceeds 1460 B.
#   P1 the edge is at 1460/1461: G1461 - G1460 <= -8 us.
#   P2 flat before it: G1460 - G1449 within 3 us of 0.
#   P3 flat after it: G1472 - G1461 within 3 us of 0.
#   P4 the host path has no edge there: B1461 - B1460 within 2 us of 0.
#   P5 two packets each way at every guest size from 1449 to 1472 B (>= 1.8 per exchange each
#      way), so the edge is not a change in the packet count.
# Not predicted, reported: every adjacent step (where the edge is, if not at 1460), the reads
# per frame above one MSS.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own frame size
#   M2 one read per frame (within 0.02) at G1448, every round (the one arm below the MSS)
#   M3 every arm has its counters before and after
#
# What this does NOT test: what the fast path is (an offload, a coalescing, an ACK, a buffer);
# which of "1460" and "a 13-byte second segment" is the cause; another boot; the tail.
#
# NEEDS: the guest running ifs-reads.bin under launch-qnx-kvm-bridged.sh (br0, tap-qnx), CONSOLE
# its console log; gcc; sudo for the namespace. CSTATE=shallow (set before the library). No load.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
PORT=7121
NS="edge"
NS_IP="${NS_IP:-192.168.100.25}"
VETH="veth-ed"
N="${N:-1000}"
K="${K:-14}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_MON="${CORE_MON:-3}"       # the namespace's endpoint
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
SRC="${SRC:-$here/../../ipc-test/qnx-server-net/sweep.c}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
MSS_BIN="${MSS_BIN:-$HOME/edge/edge-native}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(G1448 G1449 G1452 G1456 G1458 G1459 G1460 G1461 G1462 G1464 G1468 G1472 B1460 B1461)
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
BANNER="sweep: echo endpoint listening on 0.0.0.0:$PORT (frames 64..4096 bytes, length at [62..63])"
NS_MADE=0

cleanup() {
	say "cleanup"
	if [ "$NS_MADE" = 1 ]; then
		sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
		sudo ip netns del "$NS" 2>/dev/null
		sudo ip link del "$VETH" 2>/dev/null
	fi
	m_cstate_restore; m_governor_restore
}

gpu_idle_around() {   # $1 round  $2 arm
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^r$1 $2 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $2 in round $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $2 in round $1 -- a GPU load ran beside this no-load run"
}

counters() {   # $1 tag  $2 device  $3 before|after
	local d="/sys/class/net/$2/statistics" v=""
	for c in rx_packets tx_packets rx_bytes tx_bytes; do v="$v $(cat "$d/$c")" || die "cannot read $d/$c"; done
	echo "$1 $2 $3$v" >> "$OUT/counters.log"
}

echo_check() {   # $1 host  $2 label
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$1" --port "$PORT" --n 3 --warmup 0 --interval-ms 0 \
		--timeout-s 3 --frame-bytes 2048 --tag "check-$2" --out "$OUT/check-$2.json" >> "$OUT/check.log" 2>&1 \
		|| die "the $2 endpoint on $1:$PORT did not echo a 2048-byte frame -- see $OUT/check.log"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" host dev
	case "$a" in G*) host="$GUEST"; dev=tap-qnx ;; B*) host="$NS_IP"; dev="$VETH" ;; esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	counters "$t" "$dev" before
	PROBE_FRAME_BYTES="${a:1}" m_probe "$OUT" "$t" "$host" "$PORT"
	counters "$t" "$dev" after
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" "$a"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of edge-native)" ] || die "an edge-native is already running; stop it first"
sudo ip netns list 2>/dev/null | grep -qE "^(ladder|sweep|reads|mss|rtime|$NS)( |$)" && die "a leftover namespace exists; remove it first"
[ -e "/sys/class/net/$VETH" ] && die "$VETH exists -- a leftover; remove it first"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- is the guest running under launch-qnx-kvm-bridged.sh?"
[ -e /sys/class/net/br0 ] || die "no br0"
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$SRC" "$COMMON/frame.h" "$CONSOLE" "$here/edge_report.py"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes"
grep -q 'sweep: reads :%u %s frames=%llu reads=%llu' "$SRC" || die "$SRC has no read count: it predates the read modes"
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
qp="$(m_pids_of qemu-system-aarch64)"
[ "$(printf '%s\n' "$qp" | grep -c .)" = 1 ] || die "not exactly one qemu-system-aarch64 is running"
KERNEL="$(tr '\0' '\n' < "/proc/$qp/cmdline" | grep -A1 -x -- -kernel | tail -1)"
[ -r "$KERNEL" ] || die "cannot read the guest's -kernel image ($KERNEL)"

m_prepare_out "${OUT:-}" "$HOME/edge-out"
mkdir -p "$(dirname "$MSS_BIN")"
gcc -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I"$COMMON" -o "$MSS_BIN" "$SRC" > "$OUT/build-native.log" 2>&1 \
	|| die "could not build $MSS_BIN -- see $OUT/build-native.log"
[ ! -s "$OUT/build-native.log" ] || die "the native build warned -- see $OUT/build-native.log"
trap cleanup EXIT

m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "endpoint=$CORE_MON" "probe=$CORE_PROBE" "aux=$CORE_AUX"
NS_MADE=1
sudo ip netns add "$NS" || die "ip netns add failed"
sudo ip link add "$VETH" type veth peer name "$VETH-ns" || die "veth create failed"
sudo ip link set "$VETH" master br0 up || die "could not enslave $VETH to br0"
sudo ip link set "$VETH-ns" netns "$NS"
sudo ip netns exec "$NS" ip addr add "$NS_IP/24" dev "$VETH-ns"
sudo ip netns exec "$NS" ip link set "$VETH-ns" up
sudo ip netns exec "$NS" ip link set lo up
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MSS_BIN" "$PORT" greedy > "$OUT/edge-ns.log" 2>&1 &
sleep 0.5
grep -qF "$BANNER" "$OUT/edge-ns.log" || die "the namespace's endpoint did not start -- see $OUT/edge-ns.log"

m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$PORT" "the guest's greedy endpoint"
m_reachable "$NS_IP" "$PORT" "the namespace's greedy endpoint"
echo_check "$GUEST" guest
echo_check "$NS_IP" namespace
for dev in tap-qnx br0 "$VETH"; do
	echo "$dev mtu $(cat /sys/class/net/$dev/mtu)" >> "$OUT/mtu.txt"
	command -v ethtool >/dev/null && ethtool -k "$dev" > "$OUT/offloads-$dev.txt" 2>&1
done

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "edge"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"endpoint\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $PORT" \
	'"mode": "greedy (one read per frame that arrives whole)"' \
	"\"guest_image\": \"$(basename "$KERNEL")\"" \
	"\"guest_image_sha256\": \"$(_sha "$KERNEL")\"" \
	"\"source_sha256\": \"$(_sha "$SRC")\"" \
	"\"edge_native_sha256\": \"$(_sha "$MSS_BIN")\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"mtu\": \"$(tr '\n' ';' < "$OUT/mtu.txt")\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame, length in payload[46..47], pseudo-random tail; every byte checked"' \
	'"order": "Williams design over the fourteen arms, period 14"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, ${#ARMS[@]} arms, greedy, Williams -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/counters.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#ARMS[@]}"); do order+=("${ARMS[$i]}"); done
	echo "round $r order: ${order[*]}" >> "$OUT/order.log"
	for a in "${order[@]}"; do run_arm "$a" "$r"; done
	sync
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
tr -d '\0\r' < "$CONSOLE" > "$OUT/guest-console.log"
say "summary"
m_summary "$OUT" G1460 "${ARMS[@]}"
say "the fast path's edge, by the rule above"
python3 "$here/edge_report.py" "$OUT" || die "the report could not be made -- see above"
