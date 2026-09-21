#!/usr/bin/env bash
# run-ladder.sh -- the attribution ladder of docs/measurement-design.md §3.2.
#
# WHY A LADDER. The published figure is one blended number: it covers the Linux
# stack, virtio-net, the bridge, the tap, the guest's io-sock, the guest
# scheduler and the monitor's own work, with no way to attribute any of it. The
# reference papers decompose with QNX kernel tracing; this does it with arms of
# the SAME client against the SAME server program, changing only the path.
#
#   A  loopback   client -> 127.0.0.1               the instrument's own floor
#   B  bridge     client -> br0 -> veth/netns       bridge datapath cost
#   C  null       client -> guest, echo server      guest path, no judging
#   D  guest      client -> guest, safety monitor   the published path
#
# ARM C IS OPT-IN (ARM_C_PORT=7000). Without it, D-B is reported as "the
# crossing" when it is really the crossing PLUS the monitor's own read, verdict
# and write inside the guest. On a1.metal on 2026-09-21, C and D landed 0.04 us
# apart: the monitor's own work is not measurable against the transport.
#
# B USES A NETWORK NAMESPACE ON PURPOSE. Sending to br0's own address
# (192.168.100.1) does NOT cross the bridge: Linux routes a local address via
# loopback and short-circuits the datapath, so that arm would have measured the
# same thing as A while looking like it measured the bridge. A veth peer inside
# a namespace is on the far side of br0, so the traffic is really bridged.
#
# WHY k, NOT n (OD11). Within one run of 3000 samples the median is pinned to
# +/-0.2%, but between two runs of the same arm it moves 13.3%. So n is 1000 and
# the budget goes to k interleaved rounds. These arms carry no load, so unlike
# run-interference.sh and run-saturation.sh they need no counterbalancing.
#
# A LEFTOVER SERVER IS REFUSED. Arm A reaches 127.0.0.1:7100 by address, so an
# old monitor-native still running from an earlier session would answer it --
# the new one would fail to bind, and the reachability check would pass against
# the wrong process. Found by review, pre-existing; now checked before start.
#
# The shared controls live in lib-measure.sh, one copy for all three scripts.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$here/lib-measure.sh" ] || { echo "FATAL: lib-measure.sh not found beside $0" >&2; exit 1; }
. "$here/lib-measure.sh"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }
[ $# -eq 0 ] || die "positional arguments are not read (set N=, K= in the environment); got: $*"

N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
PORT="${PORT:-7100}"
ARM_C_PORT="${ARM_C_PORT:-}"
GUEST="${GUEST:-192.168.100.10}"
NS="ladder"
NS_IP="192.168.100.20"
PROBE="$HOME/interference/latency_probe.py"
MON="$HOME/ladder/monitor-native"

CORE_MON="${CORE_MON:-3}"        # native monitor, host side and namespace side
CORE_PROBE="${CORE_PROBE:-4}"    # the instrument, off the measured cores
QEMU_CORES="${QEMU_CORES:-0-2}"  # guest vCPUs + QEMU I/O thread

cleanup() {
	say "cleanup"
	for p in $(pgrep -f "[m]onitor-nativ" 2>/dev/null); do kill "$p" 2>/dev/null; done
	sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
	sudo ip netns del "$NS" 2>/dev/null
	sudo ip link del veth-l 2>/dev/null
	m_governor_restore
}

# ---------------------------------------------------------------- preflight
# Checked BEFORE the trap is set, so a refusal here cannot kill a server this
# run did not start.
pgrep -f "[m]onitor-nativ" >/dev/null \
	&& die "a monitor-native is already running; it would answer arm A in place of this run's. Stop it first."
[ -x "$MON" ] || die "$MON missing -- run build-monitor-native.sh on this host"
[ -r "$PROBE" ] || die "missing: $PROBE"
trap cleanup EXIT

m_prepare_out "${OUT:-}" "$HOME/ladder-out"
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE"
say "cores: $NCPU total; qemu=$QEMU_CORES monitor=$CORE_MON probe=$CORE_PROBE"
m_governor_pin
m_pin_qemu "$QEMU_CORES"

# ---------------------------------------------------------------- arm B setup
sudo ip netns del "$NS" 2>/dev/null
sudo ip link del veth-l 2>/dev/null
sudo ip netns add "$NS" || die "ip netns add failed"
sudo ip link add veth-l type veth peer name veth-ns || die "veth create failed"
sudo ip link set veth-l master br0 up || die "could not enslave veth-l to br0 -- does br0 exist?"
sudo ip link set veth-ns netns "$NS"
sudo ip netns exec "$NS" ip addr add "$NS_IP/24" dev veth-ns
sudo ip netns exec "$NS" ip link set veth-ns up
sudo ip netns exec "$NS" ip link set lo up
say "netns $NS up at $NS_IP behind br0"

# one native monitor on the host (arm A, INADDR_ANY), one in the namespace
# (arm B). Same source as the guest's -- one source, two targets, no #ifdef.
taskset -c "$CORE_MON" "$MON" "$PORT" > "$OUT/monitor-host.log" 2>&1 &
MON_HOST=$!
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MON" "$PORT" \
	> "$OUT/monitor-ns.log" 2>&1 &
sleep 2
kill -0 "$MON_HOST" 2>/dev/null || die "host monitor-native exited -- see $OUT/monitor-host.log (port in use?)"

# ---------------------------------------------------------------- arm set
ARMS=("A-loopback 127.0.0.1 $PORT" "B-bridge $NS_IP $PORT")
[ -n "$ARM_C_PORT" ] && ARMS+=("C-null $GUEST $ARM_C_PORT")
ARMS+=("D-guest $GUEST $PORT")
TAGS=(); ARMJSON=""; sep=""
for a in "${ARMS[@]}"; do
	set -- $a
	m_reachable "$2" "$3" "$1"
	TAGS+=("$1"); ARMJSON="$ARMJSON$sep\"$1\""; sep=", "
done

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "ladder"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE}" \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"arms\": [$ARMJSON]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, ${#ARMS[@]} arms, interleaved -> $OUT"
for r in $(seq 1 "$K"); do
	for a in "${ARMS[@]}"; do
		set -- $a
		m_probe "$OUT" "$1_r$r" "$2" "$3"
	done
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${TAGS[@]}"
m_summary "$OUT" "${TAGS[0]}" "${TAGS[@]}"
