#!/usr/bin/env bash
# run-sweep.sh -- the frame-size sweep (measurement-design.md section 3.4): how the round
# trip grows with the frame, through the guest and on the host alone. Phase 3b / A6,
# 2026-09-26; the last item of the OD11 campaign. The owner asked for this run (2026-09-26).
#
# WHY. Every A6 figure used one 64-byte frame. RTAS 2023 found a jump at 256 B in QNX's
# kernel message passing (its copy strategy), and this project's frame sits below the
# smallest size it measured. The design doc said this path "does not use QNX kernel IPC at
# all"; that is not quite right -- the guest's socket read() and write() are messages to
# io-sock -- but the round trip also crosses TCP, virtio-net, QEMU and a bridge, so whether
# any 256 B structure survives to it, and at what size segmentation begins to cost, is the
# question.
#
# THE ENDPOINT IS AN ECHO, NOT THE MONITOR. FRAME_TOTAL_BYTES stays 64 (the shm slot's copy
# is unchecked), so the sweep uses its own program, ipc-test/qnx-server-net/sweep.c: the
# frame's length in payload[46..47], S bytes read and S echoed. The monitor's own time is
# 0.21% of the round trip on this host (the stamp record), so an echo loses nothing
# measurable and leaves every monitor constraint untouched.
#
# TWENTY ARMS: ten sizes, S = 64 96 256 512 768 1024 1280 1536 1792 2048 B, on two paths:
#   G<S>  client -> br0 -> tap-qnx -> QEMU -> the guest's sweep endpoint :7120 (ifs-sweep.bin)
#   B<S>  client -> br0 -> veth -> a network namespace -> the same source built natively,
#         on the far side of the bridge as the ladder's arm B, so the host's own stack and
#         bridge are measured and the crossing is G - B.
# Every exchange's echo is checked byte for byte (latency_probe.py --frame-bytes). n=1000,
# 200 warm-up, 2 ms spacing, K=20 rounds in a Williams design over the twenty arms (period
# 20), so every arm follows every other equally often. About 400 arms, ~55 min.
#
# SEGMENTATION IS COUNTED, NOT TRACED. Before and after every arm the harness reads the
# packet and byte counters of the device the arm crosses (tap-qnx for G, the veth's host end
# for B): tx is the requests' direction, rx the replies'. Packets per exchange show whether a
# frame over one MSS crossed as one (offloaded) packet or as segments. The MTUs and the
# devices' offload settings (ethtool -k) are recorded before and after the run.
#
# THE RULE, fixed here before any run (sweep_report.py applies it). Per round r and path X:
# p50 of each arm; d_X(S) = p50(X_S) - p50(X_64), paired within the round. Per path: the
# median over rounds of d_X(S), with the distribution-free 96% interval d(6)..d(15) at
# K = 20. "Below one segment" is S <= 1280 (the MSS at MTU 1500 is 1448 with timestamps).
# The line is the least-squares fit of d_X(S) against S over the seven sizes below one
# segment; a residual is a size's median d_X(S) minus the line. Per-round slopes are the
# same fit to one round's d_X(S).
#
# CONFIGURATION, read before the prediction was written (2026-09-26): ifs-sweep.bin booted
# once, the offloads read and one frame of each size echoed and compared -- no timing and
# no counter was read. tap-qnx and br0: MTU 1500; tcp-segmentation-offload on
# (tx-tcp-segmentation on), generic-segmentation-offload on, tx-checksumming on. A tap's
# offloads are what QEMU set from the guest's negotiated virtio-net features, so the guest
# accepts large (TSO) packets: a request over one MSS can reach it as one packet. Whether
# the guest SENDS large packets (its own TSO) cannot be read from the host side. The
# endpoint echoed 64..4096 B, every byte identical. Also found: the endpoint's banner
# interleaves on the guest console with the UDP echo server's, started at the same moment,
# so the harness checks the guest endpoint by a 2048-byte echo, not by its banner.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: below one segment the round trip grows linearly
# with the frame and the guest adds per-byte cost of its own (QEMU's and the guest's
# copies); with offloads on, crossing one MSS changes nothing, because nothing is
# segmented.
#   P1 no step below one segment, on either path: every size 64..1280 B lies within 3 us of
#      its path's line (the median d_X(S) minus the line). This is where RTAS's 256 B jump
#      would show, if it survives to this path at 3 us or more.
#   P2 the per-byte cost is small and larger through the guest: the median per-round slope
#      of G below one segment is <= 10 ns/B, and the per-round slope G - B has its 96%
#      interval above 0.
#   P3 no step at one segment on the guest path: the median over rounds of G's d(1536)
#      minus its round's line is within 5 us of 0.
#   P4 no segmentation on the guest path: at 1536, 1792 and 2048 B the tap carries <= 1.2
#      packets per exchange in each direction (median over rounds). Refuted, it cannot say
#      whether the extra packets are segments or immediate ACKs: the counters see packets,
#      not their payloads, and this board has no tcpdump.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad
#   M2 every arm's summary records its own frame size
#   M3 every arm has its counters before and after
# The run itself stops on a stall, a broken echo, a governor that moved, a GPU load or a
# leftover server, so none of those reaches the report.
#
# What this does NOT test: QNX kernel message passing on its own (a sub-3 us step in it
# would not show here); UDP or shared memory; any spacing but 2 ms; frames over 2048 B; the
# monitor's own work at other sizes; another boot (the levels are the boot's -- only paired
# differences are reported).
#
# The host's userspace is NOT confined (as the ladder, the stamp and the rate records):
# these are paired differences at p50, not tail figures.
#
# NEEDS: the guest running ifs-sweep.bin under launch-qnx-kvm-bridged.sh (br0, tap-qnx);
# gcc; sudo for the namespace. CSTATE=shallow (set before the library). No load.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
PORT="${PORT:-7120}"
NS="sweep"
NS_IP="${NS_IP:-192.168.100.21}"
VETH="veth-sw"
N="${N:-1000}"
K="${K:-20}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_MON="${CORE_MON:-3}"       # the namespace's endpoint
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
SRC="${SRC:-$here/../../ipc-test/qnx-server-net/sweep.c}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
SWEEP_BIN="${SWEEP_BIN:-$HOME/sweep/sweep-native}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: GR3D is read around every arm instead
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
SIZES=(64 96 256 512 768 1024 1280 1536 1792 2048)
ARMS=()
for s in "${SIZES[@]}"; do ARMS+=("G$s"); done
for s in "${SIZES[@]}"; do ARMS+=("B$s"); done
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

offloads() {   # $1 before|after
	local dev
	for dev in tap-qnx br0 "$VETH"; do
		echo "$dev mtu $(cat /sys/class/net/$dev/mtu)" >> "$OUT/mtu-$1.txt"
		if command -v ethtool >/dev/null; then
			ethtool -k "$dev" > "$OUT/offloads-$dev-$1.txt" 2>&1
		fi
	done
}

# The guest's banner is not grepped: it interleaves on the console with the UDP echo
# server's (see CONFIGURATION). Only a sweep endpoint echoes a 2048-byte frame whole.
echo_check() {   # $1 host  $2 label
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$1" --port "$PORT" --n 3 --warmup 0 --interval-ms 0 \
		--timeout-s 3 --frame-bytes 2048 --tag "check-$2" --out "$OUT/check-$2.json" >> "$OUT/check.log" 2>&1 \
		|| die "the $2 endpoint on $1:$PORT did not echo a 2048-byte frame -- is it the sweep endpoint? see $OUT/check.log"
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
# Checked BEFORE the trap is set, so a refusal here cannot remove a namespace this run did
# not make.
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of sweep-native)" ] || die "a sweep-native is already running; stop it first"
sudo ip netns list 2>/dev/null | grep -qE "^(ladder|$NS)( |$)" && die "a ladder or sweep namespace exists -- a leftover; remove it first"
[ -e "/sys/class/net/$VETH" ] && die "$VETH exists -- a leftover; remove it first"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- is the guest running under launch-qnx-kvm-bridged.sh?"
[ -e /sys/class/net/br0 ] || die "no br0"
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$SRC" "$COMMON/frame.h"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes: it predates the sweep"
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

m_prepare_out "${OUT:-}" "$HOME/sweep-out"
mkdir -p "$(dirname "$SWEEP_BIN")"
gcc -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I"$COMMON" -o "$SWEEP_BIN" "$SRC" > "$OUT/build-native.log" 2>&1 \
	|| die "could not build $SWEEP_BIN -- see $OUT/build-native.log"
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
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$SWEEP_BIN" "$PORT" > "$OUT/sweep-ns.log" 2>&1 &
sleep 0.5
grep -qF "$BANNER" "$OUT/sweep-ns.log" || die "the namespace's endpoint did not start -- see $OUT/sweep-ns.log"

m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$PORT" "the guest's sweep endpoint"
m_reachable "$NS_IP" "$PORT" "the namespace's sweep endpoint"
echo_check "$GUEST" guest
echo_check "$NS_IP" namespace
offloads before

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "sweep"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"endpoint\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $PORT" \
	"\"sizes\": [$(printf '%s, ' "${SIZES[@]}" | sed 's/, $//')]" \
	"\"guest_image\": \"$(basename "$KERNEL")\"" \
	"\"guest_image_sha256\": \"$(_sha "$KERNEL")\"" \
	"\"sweep_source_sha256\": \"$(_sha "$SRC")\"" \
	"\"sweep_native_sha256\": \"$(_sha "$SWEEP_BIN")\"" \
	"\"mtu\": \"$(tr '\n' ';' < "$OUT/mtu-before.txt")\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame, length in payload[46..47], pseudo-random tail; every byte checked"' \
	'"order": "Williams design over the twenty arms, period 20"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, sizes ${SIZES[*]}, guest and namespace, Williams over ${#ARMS[@]} -> $OUT"
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

offloads after
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" G64 "${ARMS[@]}"
say "the frame size against 64 B, and the crossing, by the rule above"
python3 "$here/sweep_report.py" "$OUT" || die "the report could not be made -- see above"
