#!/usr/bin/env bash
# run-reads.sh -- the read-count test: is the frame-size sweep's 64 -> 96 B step on the guest
# path the frame's size, or the endpoint's second read()? Phase 3b / A6, 2026-09-26.
# The owner asked for this run (2026-09-26).
#
# WHERE THIS STARTS. The sweep (record 20260926T-a6-orin-sweep) found the guest path +15.9 us
# slower at 96 B than at 64 B, in 20/20 rounds, where the host path was +1.7 us. Its endpoint
# reads 64 bytes, then the rest: one read() at 64 B, two above. So that step compares one read
# with two as well as 64 bytes with 96. The same record found an unexplained +10.4 us bump at
# 1280 B on the guest path, gone at 1536 B.
#
# THE MANIPULATION. The same endpoint source (ipc-test/qnx-server-net/sweep.c) in three read
# modes, one instance per mode and port, in the guest (qnx-echo-server-reads in
# ifs-reads.bin) and in a network namespace behind br0 (built natively):
#   d  :7120  default  read 64, then S - 64       1 read at 64 B, 2 above
#   g  :7121  greedy   read what is there          1 read per frame that arrived whole
#   s  :7122  split    read 32 + 32, then S - 64  2 reads at 64 B, 3 above
# Every instance prints its frames and read() calls per connection, so the read count of
# every arm is measured, not assumed (M2). Before the prediction was written, the native build
# of each mode echoed one frame of each size 64..4096 B whole on the board's loopback, with
# 21, 11 and 32 reads for the 11 frames (default, greedy, split): a functional check, no
# timing. ifs-reads.bin (d252d298...) was accepted by compare-ifs.py against ifs-stamp.bin.
#
# SIXTEEN ARMS, tag = path, mode, size:
#   Gd64 Gd96 Gg64 Gg96 Gs64            the step, three ways, through the guest
#   Gd1024 Gd1280 Gd1536 Gg1024 Gg1280 Gg1536   the 1280 B bump, with two reads and one
#   Bd64 Bd96 Bg64 Bg96 Bs64            the same step on the host path, the control
# n=1000, 200 warm-up, 2 ms spacing, K=16 rounds in a Williams design over the sixteen arms
# (period 16). Every echoed byte checked (latency_probe.py --frame-bytes). Packet counters
# per arm, as run-sweep.sh. About 256 arms, ~30 min. The host's userspace is not confined:
# these are paired differences at p50.
#
# THE RULE, fixed here before any run (reads_report.py applies it). Per round, the p50 of
# each arm; a difference is two arms' p50s in the same round; per difference, the median
# over rounds with the distribution-free interval of widest coverage >= 95% (d(4)..d(13),
# 97.9%, at K = 16). Reads per frame per arm: the instance's printed read() count over its
# frames, for the connection that served that arm (matched per port, in run order).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: the guest path's 64 -> 96 B step is the endpoint's
# second read(): each extra read() in the guest costs ~14 us (a message to io-sock), and 32
# more bytes cost almost nothing.
#   P1 one read removes the step: Gg96 - Gg64 is within 3 us of 0 (median over rounds).
#   P2 two reads make it at 64 B: Gs64 - Gd64 >= +10 us.
#   P3 the step replicates in the default mode: Gd96 - Gd64 >= +10 us.
#   P4 natively an extra read is cheap: Bs64 - Bd64 <= +3 us, and Bg96 - Bg64 within 3 us
#      of 0.
#   P5 the 1280 B bump replicates in the default mode: Gd1280 - (Gd1024 + Gd1536) / 2
#      >= +5 us.
# Not predicted, reported: the bump in the greedy mode (does it need two reads?), the reads
# per frame at 1536 B (do the requests arrive in two pieces?), packets per exchange.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad
#   M2 the read counts are the design's: reads per frame within 0.02 of 1 (Gd64 Gg64 Gg96
#      Bd64 Bg64 Bg96), 2 (Gd96 Gs64 Bd96 Bs64), for every round
#   M3 every arm has its counters before and after
# The run itself stops on a stall, a broken echo, a governor that moved, a GPU load or a
# leftover server.
#
# What this does NOT test: why a read() costs what it costs in the guest (io-sock, the
# kernel's message pass, a vCPU wake-up); any other socket call; UDP; any spacing but 2 ms;
# another boot; the tail.
#
# NEEDS: the guest running ifs-reads.bin under launch-qnx-kvm-bridged.sh (br0, tap-qnx),
# CONSOLE its console log (the guest instances' read counts are read from it); gcc; sudo
# for the namespace. CSTATE=shallow (set before the library). No load.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
NS="reads"
NS_IP="${NS_IP:-192.168.100.22}"
VETH="veth-rd"
N="${N:-1000}"
K="${K:-16}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_MON="${CORE_MON:-3}"       # the namespace's endpoints
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
SRC="${SRC:-$here/../../ipc-test/qnx-server-net/sweep.c}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
READS_BIN="${READS_BIN:-$HOME/reads/reads-native}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: GR3D is read around every arm instead
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(Gd64 Gd96 Gg64 Gg96 Gs64 Gd1024 Gd1280 Gd1536 Gg1024 Gg1280 Gg1536 Bd64 Bd96 Bg64 Bg96 Bs64)
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
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

port_of() {   # $1 mode letter
	case "$1" in d) echo 7120 ;; g) echo 7121 ;; s) echo 7122 ;; *) die "no mode $1" ;; esac
}

mode_arg() {   # $1 mode letter -> the endpoint's second argument
	case "$1" in d) echo "" ;; g) echo greedy ;; s) echo split ;; esac
}

banner() {   # $1 port
	echo "sweep: echo endpoint listening on 0.0.0.0:$1 (frames 64..4096 bytes, length at [62..63])"
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

# Only an endpoint of this source echoes a 2048-byte frame whole (the guest's banners
# interleave on its console, as the sweep found).
echo_check() {   # $1 host  $2 port  $3 label
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$1" --port "$2" --n 3 --warmup 0 --interval-ms 0 \
		--timeout-s 3 --frame-bytes 2048 --tag "check-$3" --out "$OUT/check-$3.json" >> "$OUT/check.log" 2>&1 \
		|| die "the $3 endpoint on $1:$2 did not echo a 2048-byte frame -- see $OUT/check.log"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" host dev
	case "$a" in G*) host="$GUEST"; dev=tap-qnx ;; B*) host="$NS_IP"; dev="$VETH" ;; esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	counters "$t" "$dev" before
	PROBE_FRAME_BYTES="${a:2}" m_probe "$OUT" "$t" "$host" "$(port_of "${a:1:1}")"
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
[ -z "$(m_pids_of reads-native)" ] || die "a reads-native is already running; stop it first"
sudo ip netns list 2>/dev/null | grep -qE "^(ladder|sweep|$NS)( |$)" && die "a ladder, sweep or reads namespace exists -- a leftover; remove it first"
[ -e "/sys/class/net/$VETH" ] && die "$VETH exists -- a leftover; remove it first"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- is the guest running under launch-qnx-kvm-bridged.sh?"
[ -e /sys/class/net/br0 ] || die "no br0"
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$SRC" "$COMMON/frame.h" "$CONSOLE" "$here/reads_report.py"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes: it predates the sweep"
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

m_prepare_out "${OUT:-}" "$HOME/reads-out"
mkdir -p "$(dirname "$READS_BIN")"
gcc -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I"$COMMON" -o "$READS_BIN" "$SRC" > "$OUT/build-native.log" 2>&1 \
	|| die "could not build $READS_BIN -- see $OUT/build-native.log"
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
for m in d g s; do
	p="$(port_of $m)"
	# shellcheck disable=SC2046
	sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$READS_BIN" "$p" $(mode_arg $m) > "$OUT/reads-ns-$p.log" 2>&1 &
done
sleep 0.5
for m in d g s; do
	p="$(port_of $m)"
	grep -qF "$(banner "$p")" "$OUT/reads-ns-$p.log" || die "the namespace's endpoint on :$p did not start -- see $OUT/reads-ns-$p.log"
done

m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
for m in d g s; do
	p="$(port_of $m)"
	m_reachable "$GUEST" "$p" "the guest's endpoint :$p"
	m_reachable "$NS_IP" "$p" "the namespace's endpoint :$p"
	echo_check "$GUEST" "$p" "guest-$p"
	echo_check "$NS_IP" "$p" "namespace-$p"
done

INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "reads"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"endpoint\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"d": 7120, "g": 7121, "s": 7122}' \
	"\"guest_image\": \"$(basename "$KERNEL")\"" \
	"\"guest_image_sha256\": \"$(_sha "$KERNEL")\"" \
	"\"source_sha256\": \"$(_sha "$SRC")\"" \
	"\"reads_native_sha256\": \"$(_sha "$READS_BIN")\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame, length in payload[46..47], pseudo-random tail; every byte checked"' \
	'"order": "Williams design over the sixteen arms, period 16"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, ${#ARMS[@]} arms, Williams -> $OUT"
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
m_summary "$OUT" Gd64 "${ARMS[@]}"
say "the read count against the frame size, by the rule above"
python3 "$here/reads_report.py" "$OUT" || die "the report could not be made -- see above"
