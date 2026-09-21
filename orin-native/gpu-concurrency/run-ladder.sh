#!/usr/bin/env bash
# run-ladder.sh -- the attribution ladder of docs/measurement-design.md §3.2.
#
# WHY A LADDER. The published figure is one blended number: it covers the Linux
# stack, virtio-net, the bridge, the tap, the guest's io-sock, the guest
# scheduler and the monitor's own work, with no way to attribute any of it. The
# reference papers decompose with QNX kernel tracing; this does it with three
# arms of the SAME client against the SAME server program, changing only the
# path.
#
#   A  loopback   client -> 127.0.0.1        the instrument's own floor
#   B  bridge     client -> br0 -> veth/netns  bridge datapath cost
#   D  guest      client -> br0 -> tap -> virtio-net -> QNX guest
#
# B USES A NETWORK NAMESPACE ON PURPOSE. Sending to br0's own address
# (192.168.100.1) does NOT cross the bridge: Linux routes a local address via
# loopback and short-circuits the datapath, so that arm would have measured the
# same thing as A while looking like it measured the bridge. A veth peer inside
# a namespace is on the far side of br0, so the traffic is really bridged.
#
# WHY k, NOT n. Measured on this board (results/.../20260919T-native-cmp):
# within one run of 3000 samples the median is pinned to +/-0.2%, but between
# two runs of the same arm it moves 13.3%. Run-to-run variation is ~69x the
# sampling noise at p50. So n drops to 1000 and the budget goes to k rounds,
# interleaved -- every round runs the whole arm set back to back, so drift hits
# all arms equally instead of only the ones that ran late.
#
# The governor is pinned for the run and restored afterwards: unpinned, ~40% of
# an idle figure on this board is DVFS.
set -u

N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
PORT="${PORT:-7100}"
GUEST="${GUEST:-192.168.100.10}"
NS="ladder"
NS_IP="192.168.100.20"
OUT="${OUT:-$HOME/ladder-out}"

CORE_MON=3          # native monitor, host side and namespace side
CORE_PROBE=4        # the instrument, off the measured cores
QEMU_CORES="0-2"    # guest vCPUs + QEMU I/O thread

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
mkdir -p "$OUT"

# ---------------------------------------------------------------- teardown
cleanup() {
	say "cleanup"
	for p in $(pgrep -f "[m]onitor-nativ" 2>/dev/null); do kill "$p" 2>/dev/null; done
	sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
	sudo ip netns del "$NS" 2>/dev/null
	sudo ip link del veth-l 2>/dev/null
	if [ -n "${PRE_GOV:-}" ]; then
		for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
			echo "$PRE_GOV" | sudo tee "$c" >/dev/null
		done
		say "governor restored: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
	fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- controls
PRE_GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)
for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
	echo performance | sudo tee "$c" >/dev/null
done
say "governor: $PRE_GOV -> $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"

QPID=$(pgrep -f "[q]emu-system-aarch64" | head -1)
if [ -z "$QPID" ]; then echo "no guest running" >&2; exit 1; fi
for t in $(ls "/proc/$QPID/task"); do sudo taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1; done
say "qemu pid=$QPID pinned to cores $QEMU_CORES ($(ls /proc/$QPID/task | wc -l) threads)"

# ---------------------------------------------------------------- arm B setup
sudo ip netns del "$NS" 2>/dev/null
sudo ip link del veth-l 2>/dev/null
sudo ip netns add "$NS"
sudo ip link add veth-l type veth peer name veth-ns
sudo ip link set veth-l master br0 up
sudo ip link set veth-ns netns "$NS"
sudo ip netns exec "$NS" ip addr add "$NS_IP/24" dev veth-ns
sudo ip netns exec "$NS" ip link set veth-ns up
sudo ip netns exec "$NS" ip link set lo up
say "netns $NS up at $NS_IP behind br0"

# one native monitor on the host (serves arm A via 127.0.0.1; INADDR_ANY),
# one inside the namespace (serves arm B). Same binary, same source as the
# guest's -- one source, two targets, no #ifdef fork.
taskset -c "$CORE_MON" "$HOME/ladder/monitor-native" "$PORT" \
	> "$OUT/monitor-host.log" 2>&1 &
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$HOME/ladder/monitor-native" "$PORT" \
	> "$OUT/monitor-ns.log" 2>&1 &
sleep 2

for probe in "127.0.0.1 A-loopback" "$NS_IP B-bridge" "$GUEST D-guest"; do
	set -- $probe
	if timeout 3 bash -c "echo > /dev/tcp/$1/$PORT" 2>/dev/null; then
		say "reachable: $2 ($1:$PORT)"
	else
		echo "UNREACHABLE: $2 ($1:$PORT)" >&2; exit 1
	fi
done

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, interleaved"
for r in $(seq 1 "$K"); do
	for arm in "A-loopback 127.0.0.1" "B-bridge $NS_IP" "D-guest $GUEST"; do
		set -- $arm
		tag="$1_r$r"
		taskset -c "$CORE_PROBE" python3 "$HOME/interference/latency_probe.py" \
			--host "$2" --port "$PORT" --n "$N" --warmup "$WARMUP" \
			--interval-ms "$INTERVAL_MS" --tag "$tag" --out "$OUT/lat-$tag.json" \
			>> "$OUT/probe.log" 2>&1 || echo "  ARM FAILED: $tag" >&2
	done
	say "round $r/$K done"
done

say "wrote $(ls "$OUT"/lat-*.json 2>/dev/null | wc -l) arm files to $OUT"
