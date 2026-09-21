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
# ARM C IS OPT-IN AND COSTS NOTHING EXTRA. Without it, D-B is reported as "the
# crossing" when it is really the crossing PLUS the monitor's own read, verdict
# and write inside the guest. The guest image already runs a verbatim echo
# server on :7000 alongside the monitor on :7100, so arm C is one more probe
# target, not one more program. Set ARM_C_PORT=7000 to include it. It is opt-in
# rather than default because not every image starts that server, and an arm
# that silently disappears is worse than one that is absent by choice.
#
# B USES A NETWORK NAMESPACE ON PURPOSE. Sending to br0's own address
# (192.168.100.1) does NOT cross the bridge: Linux routes a local address via
# loopback and short-circuits the datapath, so that arm would have measured the
# same thing as A while looking like it measured the bridge. A veth peer inside
# a namespace is on the far side of br0, so the traffic is really bridged.
#
# WHY k, NOT n. Measured on the Orin (results/.../20260921T-ladder): within one
# run of 3000 samples the median is pinned to +/-0.2%, but between two runs of
# the same arm it moves 13.3%. Run-to-run variation is ~69x the sampling noise
# at p50. So n is 1000 and the budget goes to k rounds, interleaved -- every
# round runs the whole arm set back to back, so drift hits all arms equally
# instead of only the ones that ran late. Owner decision OD11, 2026-09-21.
#
# THIS SCRIPT WRITES A RUN STAMP, and that is not decoration. The first ladder
# run produced 36 arm files and no configuration record at all: no governor
# observation, no QEMU version, no launch line, no image hashes, no confirmation
# the pinning was applied. Its own results.md has to say it cannot be exactly
# reproduced. A second host compared against a partially specified first host is
# a weak comparison, so the stamp is a precondition for comparing, not a nicety.
set -u

N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
PORT="${PORT:-7100}"
ARM_C_PORT="${ARM_C_PORT:-}"
GUEST="${GUEST:-192.168.100.10}"
NS="ladder"
NS_IP="192.168.100.20"
OUT="${OUT:-$HOME/ladder-out}"

CORE_MON="${CORE_MON:-3}"     # native monitor, host side and namespace side
CORE_PROBE="${CORE_PROBE:-4}" # the instrument, off the measured cores
QEMU_CORES="${QEMU_CORES:-0-2}"  # guest vCPUs + QEMU I/O thread

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
die() { echo "FATAL: $*" >&2; exit 1; }
mkdir -p "$OUT"

# ---------------------------------------------------------------- teardown
cleanup() {
	say "cleanup"
	for p in $(pgrep -f "[m]onitor-nativ" 2>/dev/null); do kill "$p" 2>/dev/null; done
	sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
	sudo ip netns del "$NS" 2>/dev/null
	sudo ip link del veth-l 2>/dev/null
	if [ "${GOV_STATE:-}" = "pinned" ] && [ -n "${PRE_GOV:-}" ]; then
		for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
			echo "$PRE_GOV" | sudo tee "$c" >/dev/null
		done
		say "governor restored: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
	fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- cores
# The literal core numbers were written for a 6-core board. They are checked
# rather than trusted: on a host with fewer cores taskset would fail per-call
# and the run would continue unpinned, which is the same silent-invalidation
# failure the governor block used to have.
NCPU="$(nproc)"
for c in "$CORE_MON" "$CORE_PROBE"; do
	[ "$c" -lt "$NCPU" ] || die "core $c requested but this host has $NCPU (0-$((NCPU-1)))"
done
QC_HI="${QEMU_CORES##*-}"
[ "$QC_HI" -lt "$NCPU" ] || die "QEMU_CORES=$QEMU_CORES exceeds $NCPU cores"
say "cores: $NCPU total; qemu=$QEMU_CORES monitor=$CORE_MON probe=$CORE_PROBE"

# ---------------------------------------------------------------- governor
# DETECT, RECORD, OR FAIL -- never skip silently. An arm measured with the
# governor pinned against an arm measured without it is not a comparison, and
# on bare-metal EC2 there is no cpufreq sysfs at all, so the old unconditional
# `cat` left PRE_GOV empty, pinned nothing, and said nothing.
GOV_STATE="unknown"
PRE_GOV=""
if [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
	PRE_GOV="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
	for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
		echo performance | sudo tee "$c" >/dev/null
	done
	now="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
	[ "$now" = "performance" ] || die "governor is present but would not pin (still '$now')"
	GOV_STATE="pinned"
	say "governor: $PRE_GOV -> performance (will restore)"
else
	GOV_STATE="absent"
	say "governor: NO cpufreq on this host -- nothing to pin, recorded as absent"
fi
CPUIDLE="absent"
[ -d /sys/devices/system/cpu/cpu0/cpuidle ] && CPUIDLE="present"

# ---------------------------------------------------------------- the guest
# Exactly one, or the pgrep picked an arbitrary process and the pinning went to
# the wrong one.
QPIDS="$(pgrep -f "[q]emu-system-aarch64" || true)"
QN="$(printf '%s\n' "$QPIDS" | grep -c . || true)"
[ "$QN" -eq 1 ] || die "expected exactly 1 qemu-system-aarch64, found $QN -- start the guest with launch-qnx-kvm-bridged.sh"
QPID="$QPIDS"
for t in $(ls "/proc/$QPID/task"); do sudo taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1; done
QTHREADS="$(ls "/proc/$QPID/task" | wc -l)"
QAFF="$(taskset -pc "$QPID" 2>/dev/null | sed 's/.*: //')"
[ -n "$QAFF" ] || die "could not read qemu affinity back -- pinning unverified"
say "qemu pid=$QPID pinned to $QEMU_CORES (readback '$QAFF', $QTHREADS threads)"

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

# one native monitor on the host (serves arm A via 127.0.0.1; INADDR_ANY),
# one inside the namespace (serves arm B). Same binary, same source as the
# guest's -- one source, two targets, no #ifdef fork.
MON="$HOME/ladder/monitor-native"
[ -x "$MON" ] || die "$MON missing -- run build-monitor-native.sh on this host"
taskset -c "$CORE_MON" "$MON" "$PORT" > "$OUT/monitor-host.log" 2>&1 &
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MON" "$PORT" \
	> "$OUT/monitor-ns.log" 2>&1 &
sleep 2

# ---------------------------------------------------------------- arm set
ARMS=("A-loopback 127.0.0.1 $PORT" "B-bridge $NS_IP $PORT")
[ -n "$ARM_C_PORT" ] && ARMS+=("C-null $GUEST $ARM_C_PORT")
ARMS+=("D-guest $GUEST $PORT")

for a in "${ARMS[@]}"; do
	set -- $a
	if timeout 3 bash -c "echo > /dev/tcp/$2/$3" 2>/dev/null; then
		say "reachable: $1 ($2:$3)"
	else
		die "UNREACHABLE: $1 ($2:$3)"
	fi
done

# ---------------------------------------------------------------- the stamp
STAMP="$OUT/stamp.json"
{
	printf '{\n'
	printf '  "utc": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf '  "machine": "%s",\n' "$(uname -m)"
	printf '  "kernel": "%s",\n' "$(uname -r)"
	printf '  "ncpu": %s,\n' "$NCPU"
	printf '  "governor_state": "%s",\n' "$GOV_STATE"
	printf '  "governor_before": "%s",\n' "$PRE_GOV"
	printf '  "cpuidle": "%s",\n' "$CPUIDLE"
	printf '  "qemu_version": "%s",\n' "$(qemu-system-aarch64 --version 2>/dev/null | head -1)"
	printf '  "qemu_cmdline": "%s",\n' "$(tr '\0' ' ' < "/proc/$QPID/cmdline" | sed 's/"/\\"/g')"
	printf '  "qemu_threads": %s,\n' "$QTHREADS"
	printf '  "qemu_affinity": "%s",\n' "$QAFF"
	printf '  "pin": {"qemu": "%s", "monitor": %s, "probe": %s},\n' "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE"
	printf '  "monitor_native_sha256": "%s",\n' "$(sha256sum "$MON" | cut -d' ' -f1)"
	printf '  "n": %s, "k": %s, "warmup": %s, "interval_ms": %s,\n' "$N" "$K" "$WARMUP" "$INTERVAL_MS"
	printf '  "arms": ['
	sep=""
	for a in "${ARMS[@]}"; do set -- $a; printf '%s"%s"' "$sep" "$1"; sep=", "; done
	printf ']\n}\n'
} > "$STAMP"
say "stamp written: $STAMP"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, ${#ARMS[@]} arms, interleaved"
for r in $(seq 1 "$K"); do
	for a in "${ARMS[@]}"; do
		set -- $a
		tag="$1_r$r"
		taskset -c "$CORE_PROBE" python3 "$HOME/interference/latency_probe.py" \
			--host "$2" --port "$3" --n "$N" --warmup "$WARMUP" \
			--interval-ms "$INTERVAL_MS" --tag "$tag" --out "$OUT/lat-$tag.json" \
			>> "$OUT/probe.log" 2>&1 || echo "  ARM FAILED: $tag" >&2
	done
	say "round $r/$K done"
done

# ---------------------------------------------------------------- completeness
# A missing arm file shifts the median instead of failing: the arms differ by
# up to 6.4% between rounds, so k-1 files still produce a plausible number.
bad=0
for a in "${ARMS[@]}"; do
	set -- $a
	got="$(ls "$OUT"/lat-"$1"_r*.json 2>/dev/null | wc -l)"
	if [ "$got" -ne "$K" ]; then
		echo "INCOMPLETE: arm $1 has $got/$K rounds" >&2
		bad=1
	fi
done
[ "$bad" -eq 0 ] || die "the run is incomplete -- do not publish a median from it"

say "wrote $(ls "$OUT"/lat-*.json | wc -l) arm files and a stamp to $OUT"
