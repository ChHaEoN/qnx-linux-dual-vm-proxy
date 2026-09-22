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
# UDP ARMS (owner decision OD12, 2026-09-21), opt-in with UDP=1. The same four
# rungs over UDP, beside the TCP rungs in the SAME run: A-udp and B-udp against
# the native monitor in UDP mode (port PORT_UDP, default 7101) on the host and
# in the namespace, D-udp against the guest's monitor in UDP mode, and C-udp
# against the guest's echo server in UDP mode (ARM_C_UDP_PORT, default unset).
# Distinct ports on purpose: a TCP/UDP mix-up must fail, not answer with the
# other transport's figure. The guest must run an image that starts both UDP
# servers; the run refuses if a UDP rung does not answer. Which transport goes
# first alternates by round, so position in the round is not folded into
# UDP - TCP. The summary pairs each UDP rung with its TCP rung.
#
# A UDP stall stops the ladder like a TCP one (STALL_POLICY=refuse, set below),
# and on UDP a lost datagram cannot be told from a stalled guest: the first run
# keeps the TCP rule (an implementation choice of 2026-09-22, recorded under
# OD12). If it bites, the evidence is probe.log's "FATAL desync" line for that
# -udp tag. UDP=1 needs an even K, so that each transport goes first equally
# often; an odd K is refused rather than recorded as balanced.
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
UDP="${UDP:-0}"
PORT_UDP="${PORT_UDP:-7101}"
ARM_C_UDP_PORT="${ARM_C_UDP_PORT:-}"
STALL_POLICY=refuse              # the ladder's figures are headlines: any stall stops it
case "$UDP" in 0|1) ;; *) die "UDP='$UDP' must be 0 or 1" ;; esac
case "$PORT_UDP" in ''|*[!0-9]*) die "PORT_UDP='$PORT_UDP' is not a port number" ;; esac
case "$ARM_C_UDP_PORT" in *[!0-9]*) die "ARM_C_UDP_PORT='$ARM_C_UDP_PORT' is not a port number" ;; esac
if [ "$UDP" = 1 ] && [ $((K % 2)) -ne 0 ]; then
	die "UDP=1 needs an even K so each transport goes first equally often; K=$K"
fi
GUEST="${GUEST:-192.168.100.10}"
NS="ladder"
NS_IP="192.168.100.20"
PROBE="$HOME/interference/latency_probe.py"
MON="$HOME/ladder/monitor-native"

CORE_MON="${CORE_MON:-3}"        # native monitor, host side and namespace side
CORE_PROBE="${CORE_PROBE:-4}"    # the instrument, off the measured cores
FIFO_ARMS=""                     # every arm runs the probe at SCHED_OTHER; the gate checks it
SAMPLE_WINDOW=0                  # no window sampler: these are the headline numbers, and a
                                 # sampler running beside them would be a new perturbation
QEMU_CORES="${QEMU_CORES:-0-2}"  # guest vCPUs + QEMU I/O thread

cleanup() {
	say "cleanup"
	# By argv[0], never by pattern: see m_pids_of in lib-measure.sh.
	for p in $(m_pids_of monitor-native); do kill "$p" 2>/dev/null; sudo kill "$p" 2>/dev/null; done
	sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
	sudo ip netns del "$NS" 2>/dev/null
	sudo ip link del veth-l 2>/dev/null
	m_cstate_restore
	m_governor_restore
}

# ---------------------------------------------------------------- preflight
# Checked BEFORE the trap is set, so a refusal here cannot kill a server this
# run did not start.
[ -n "$(m_pids_of monitor-native)" ] \
	&& die "a monitor-native is already running; it would answer arm A in place of this run's. Stop it first."
[ -x "$MON" ] || die "$MON missing -- run build-monitor-native.sh on this host"
[ -r "$PROBE" ] || die "missing: $PROBE"
trap cleanup EXIT

m_prepare_out "${OUT:-}" "$HOME/ladder-out"
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "monitor=$CORE_MON" "probe=$CORE_PROBE"
say "cores: $NCPU total; qemu=$QEMU_CORES monitor=$CORE_MON probe=$CORE_PROBE"
m_governor_pin
m_cstate_apply
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
if [ "$UDP" = 1 ]; then
	taskset -c "$CORE_MON" "$MON" "$PORT_UDP" udp > "$OUT/monitor-host-udp.log" 2>&1 &
	MON_HOST_UDP=$!
	sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MON" "$PORT_UDP" udp \
		> "$OUT/monitor-ns-udp.log" 2>&1 &
fi
sleep 2
kill -0 "$MON_HOST" 2>/dev/null || die "host monitor-native exited -- see $OUT/monitor-host.log (port in use?)"
if [ "$UDP" = 1 ]; then
	kill -0 "$MON_HOST_UDP" 2>/dev/null \
		|| die "host monitor-native (udp) exited -- see $OUT/monitor-host-udp.log (port in use?)"
	# Positive check, not only liveness: a monitor-native built before OD12
	# ignores "udp", listens on TCP, and stays alive.
	for l in "$OUT/monitor-host-udp.log" "$OUT/monitor-ns-udp.log"; do
		grep -q ":$PORT_UDP/udp" "$l" \
			|| die "$(basename "$l" .log) did not start in UDP mode -- rebuild $MON with build-monitor-native.sh (a pre-OD12 binary ignores 'udp' and serves TCP)"
	done
fi

# ---------------------------------------------------------------- arm set
ARMS=("A-loopback 127.0.0.1 $PORT tcp" "B-bridge $NS_IP $PORT tcp")
[ -n "$ARM_C_PORT" ] && ARMS+=("C-null $GUEST $ARM_C_PORT tcp")
ARMS+=("D-guest $GUEST $PORT tcp")
UARMS=()
UDP_ARMS=""
if [ "$UDP" = 1 ]; then
	UARMS=("A-udp 127.0.0.1 $PORT_UDP udp" "B-udp $NS_IP $PORT_UDP udp")
	[ -n "$ARM_C_UDP_PORT" ] && UARMS+=("C-udp $GUEST $ARM_C_UDP_PORT udp")
	UARMS+=("D-udp $GUEST $PORT_UDP udp")
fi
TAGS=(); ARMJSON=""; sep=""
for a in "${ARMS[@]}" "${UARMS[@]}"; do
	set -- $a
	if [ "$4" = udp ]; then
		m_reachable_udp "$2" "$3" "$1"
		UDP_ARMS="$UDP_ARMS $1"
	else
		m_reachable "$2" "$3" "$1"
	fi
	TAGS+=("$1"); ARMJSON="$ARMJSON$sep\"$1\""; sep=", "
done
UDP_ARMS="${UDP_ARMS# }"

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "ladder"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE}" \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"udp\": {\"enabled\": $UDP, \"port\": $PORT_UDP, \"arm_c_port\": \"$ARM_C_UDP_PORT\"}" \
	'"order": "fixed A, B, C, D within a transport; with UDP=1 the transport that goes first alternates by round (tcp first in odd rounds)"' \
	"\"arms\": [$ARMJSON]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, ${#TAGS[@]} arms, interleaved -> $OUT"
for r in $(seq 1 "$K"); do
	if [ $((r % 2)) -eq 1 ]; then ROUND=("${ARMS[@]}" "${UARMS[@]}"); else ROUND=("${UARMS[@]}" "${ARMS[@]}"); fi
	order=""
	for a in "${ROUND[@]}"; do
		set -- $a
		m_probe "$OUT" "$1_r$r" "$2" "$3" "" "$4"
		order="$order $1"
	done
	echo "round $r order:$order" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${TAGS[@]}"
m_summary "$OUT" "${TAGS[0]}" "${TAGS[@]}"
if [ "$UDP" = 1 ]; then
	say "UDP rungs paired with their TCP rungs, and each transport's crossing"
	PAIRS=("A-udp:A-loopback" "B-udp:B-bridge")
	[ -n "$ARM_C_UDP_PORT" ] && [ -n "$ARM_C_PORT" ] && PAIRS+=("C-udp:C-null")
	PAIRS+=("D-udp:D-guest" "D-guest:B-bridge" "D-udp:B-udp")
	m_pairs "$OUT" "${PAIRS[@]}"
fi
