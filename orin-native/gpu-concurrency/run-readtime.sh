#!/usr/bin/env bash
# run-readtime.sh -- time the extra read() inside the guest: is its cost spent in the call?
# Phase 3b / A6, 2026-09-26; follows 20260926T-a6-orin-readpath.
# The owner asked for this run (2026-09-26).
#
# WHAT IS KNOWN. What one extra socket read() in the guest costs the round trip: record
# 20260926T-a6-orin-reads; on one vCPU, with the vCPU thread's run time and the VM's exits per
# exchange: record 20260926T-a6-orin-readpath (both held locally). The host cannot see which
# guest code runs. The endpoint can time its own calls.
#
# THE INSTRUMENT. sweep.c built with -DSWEEP_TIMING (qnx-echo-server-timed, in ifs-timed.bin;
# natively in a namespace as before). Per connection it prints the medians, on its own OS's
# CLOCK_MONOTONIC, of: r2 = each frame's second read() that returned data, from call to
# return; w = the frame's write; svc = from the return of the frame's first read to the return
# of its write (the frame's service time once it has arrived). The first read waits for the
# frame and is not timed as a cost. A default build compiles none of this. The timing adds two
# clock reads per call, so the arm with one more read carries two more (a small bias against
# H in the round trip; none in r2 itself beyond the reads' own).
#
# SIX ARMS, tag = path, mode, size (ports as run-reads.sh: d :7120, g :7121, s :7122):
#   Gd64 Gd96 Gs64 Gg64     through the guest: one read, two (32 B more), two (32 + 32), one
#   Bd64 Bs64               natively in the namespace: one read, two
# n=1000, 200 warm-up, 2 ms spacing, K=12 rounds in a Williams design over the six arms (period
# 6); every echoed byte checked; one guest boot. The host's userspace is not confined. The LAN
# is Ethernet since 2026-09-26 (the Wi-Fi still up): the stamp records the default route.
#
# THE RULE, fixed here before any run (readtime_report.py applies it). Per arm and round, the
# probe's p50 and the endpoint's printed medians for the connection that served the arm
# (matched per port, in run order, frames = n + warm-up). Differences are paired within the
# round; per quantity, the median over rounds with the distribution-free interval of widest
# coverage >= 95% (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. H: the extra read's cost is spent inside the read() call itself.
#   P1 the guest's second read is long: Gs64's r2 and Gd96's r2 (median over rounds) are each
#      >= 8 us.
#   P2 it shows in the guest's service time: svc(Gs64) - svc(Gd64) >= +8 us.
#   P3 the write does not depend on the read mode: w(Gs64) - w(Gd64) within 2 us of 0.
#   P4 the round trip replicates: Gs64 - Gd64 >= +10 us.
# Not predicted, reported: the native arms' r2, w and svc -- a functional check of the timed
# build on the board's loopback printed native medians before this was written (11 frames,
# governor unpinned; held locally), so a native prediction would not be blind;
# how much of the round trip's difference svc accounts for; Gg64 and Gd96's svc.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own frame size
#   M2 the read counts are the design's: reads per frame within 0.02 of 1 (Gd64 Gg64 Bd64) and
#      2 (Gd96 Gs64 Bs64), every round
#   M3 every arm's connection printed its timing, with a second read in every frame where the
#      design has one (r2_n = frames: Gd96 Gs64 Bs64) and in none where it has not (Gd64 Gg64
#      Bd64)
#
# What this does NOT test: what inside the read() takes the time (the message pass to io-sock,
# io-sock's socket code, a switch between address spaces under stage-2 translation); another
# boot; any spacing but 2 ms; the tail.
#
# NEEDS: the guest running ifs-timed.bin under launch-qnx-kvm-bridged.sh (br0, tap-qnx), CONSOLE
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
NS="rtime"
NS_IP="${NS_IP:-192.168.100.24}"
VETH="veth-rt"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_MON="${CORE_MON:-3}"       # the namespace's endpoints
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
SRC="${SRC:-$here/../../ipc-test/qnx-server-net/sweep.c}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
READS_BIN="${READS_BIN:-$HOME/rtime/rtime-native}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: GR3D is read around every arm instead
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(Gd64 Gd96 Gs64 Gg64 Bd64 Bs64)
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

# Only an endpoint of this source echoes a 2048-byte frame whole, so an endpoint is checked by
# an exchange, never by its banner on the guest's console.
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
[ -z "$(m_pids_of rtime-native)" ] || die "an rtime-native is already running; stop it first"
sudo ip netns list 2>/dev/null | grep -qE "^(ladder|sweep|reads|mss|$NS)( |$)" && die "a leftover namespace exists; remove it first"
[ -e "/sys/class/net/$VETH" ] && die "$VETH exists -- a leftover; remove it first"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- is the guest running under launch-qnx-kvm-bridged.sh?"
[ -e /sys/class/net/br0 ] || die "no br0"
m_require_balanced_k "$K" "${#ARMS[@]}"
for f in "$PROBE" "$SRC" "$COMMON/frame.h" "$CONSOLE" "$here/readtime_report.py"; do [ -r "$f" ] || die "missing: $f"; done
grep -q -- '--frame-bytes' "$PROBE" || die "$PROBE has no --frame-bytes: it predates the sweep"
grep -q 'sweep: timing :%u %s frames=%llu r2_n=%llu r2_p50_ns=%lld w_p50_ns=%lld svc_p50_ns=%lld' "$SRC" || die "$SRC has no timing: it predates -DSWEEP_TIMING"
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

m_prepare_out "${OUT:-}" "$HOME/rtime-out"
mkdir -p "$(dirname "$READS_BIN")"
gcc -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -DSWEEP_TIMING -I"$COMMON" -o "$READS_BIN" "$SRC" > "$OUT/build-native.log" 2>&1 \
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
	'"experiment": "readtime"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"endpoint\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"d": 7120, "g": 7121, "s": 7122}' \
	"\"guest_image\": \"$(basename "$KERNEL")\"" \
	"\"guest_image_sha256\": \"$(_sha "$KERNEL")\"" \
	"\"source_sha256\": \"$(_sha "$SRC")\"" \
	"\"rtime_native_sha256\": \"$(_sha "$READS_BIN")\"" \
	'"native_build": "gcc -DSWEEP_TIMING"' \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame, length in payload[46..47], pseudo-random tail; every byte checked"' \
	'"order": "Williams design over the six arms, period 6"' \
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
say "the read timed inside the endpoint, by the rule above"
python3 "$here/readtime_report.py" "$OUT" || die "the report could not be made -- see above"
