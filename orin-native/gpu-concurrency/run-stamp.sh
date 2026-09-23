#!/usr/bin/env bash
# run-stamp.sh -- guest-side timestamps (OD15; measurement-design 3.3): what the
# stamp itself costs, and the round trip split into the monitor's own time and
# everything else.
#
# Phase 3b / A6. Four arms, the probe's pinned mnist frame on every one:
#
#   D-plain   the guest's plain TCP monitor, :7100            (ifs-stamp.bin)
#   D-stamp   the guest's stamping monitor, :7103             PROBE_STAMPS=1
#   A-plain   the same monitor.c built natively on this host, plain TCP, over
#             loopback -- the control the decomposition sharpens
#   A-stamp   the native monitor stamping, over loopback       PROBE_STAMPS=1
#
# A WILLIAMS DESIGN over the four (lib-measure.sh; period 4), so K must be a
# multiple of 4 and every ordered pair of arms is adjacent equally often.
#
# THE FIGURES. First the instrument's own cost, paired within round: D-stamp -
# D-plain and A-stamp - A-plain -- two clock reads and two stores per frame. The
# `if (stamp)` tests run in both arms of each pair and cancel. D-plain is this
# image's binary, not the one behind the published D-guest figures, so it pairs
# only within this run. Then, for each stamp arm, the split per sample:
# the monitor's own time (t_out - t_in, on its own clock, so no clock is
# synchronised with anyone's) and the rest (the probe's RTT less it), at every
# percentile. The probe records both; this script prints their medians over
# rounds, and the record's analysis takes them further.
#
# c7 OFF ON THE ORIN (OD15): CSTATE defaults to shallow, so the tail is not the
# 2026-09-21 idle-state slow mode. A host with no cpuidle has nothing to disable
# (recorded as absent). CSTATE="" asks for idle states as found, explicitly.
#
# NO LOAD, checked as run-live-cost.sh checks it: GR3D on a Tegra, not
# applicable elsewhere (TEGRA=0 forces that path, for a rehearsal). A STALL
# STOPS THE RUN (STALL_POLICY=refuse).
#
# The native monitor is built by build-monitor-native.sh to its OWN path
# (MON, default $HOME/stamp/monitor-native) -- never the ladder's, whose source
# guard would refuse, and whose arms must stay what they were built as.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# BEFORE the library: it runs CSTATE="${CSTATE:-}" when sourced, and after that a
# default here would see an empty-but-set CSTATE and keep it -- idle states as
# found. FOUND BY THE FIRST SMOKE RUN: c7 stayed on under a harness that said off.
CSTATE="${CSTATE-shallow}"
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
D_PORT="${D_PORT:-7100}"
D_STAMP_PORT="${D_STAMP_PORT:-7103}"
A_PORT="${A_PORT:-7200}"
A_STAMP_PORT="${A_STAMP_PORT:-7203}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_MON="${CORE_MON:-3}"
CORE_PROBE="${CORE_PROBE:-4}"
PROBE="${PROBE:-$here/latency_probe.py}"
MON="${MON:-$HOME/stamp/monitor-native}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW="$TEGRA"
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
STAMP_ARMS="D-stamp A-stamp"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"

ARMS=(D-plain D-stamp A-plain A-stamp)
MON_PIDS=""

cleanup() {
	say "cleanup"
	local p
	for p in $MON_PIDS; do kill "$p" 2>/dev/null; done
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

# Every tegrastats line of the window must show GR3D, and every one must read 0%.
gpu_idle_in_window() {   # $1 tag
	[ "$TEGRA" = 1 ] || return 0                    # no GPU on this host: not applicable
	local log="$OUT/tegra-$1.log"
	grep -qE 'GR3D_FREQ [0-9]+%' "$log" 2>/dev/null \
		|| die "no GR3D reading in $1's window ($log) -- the no-load premise is unverified"
	! grep -qE 'GR3D_FREQ [1-9][0-9]*%' "$log" \
		|| die "GR3D above 0% during $1 -- a GPU load ran beside this no-load run"
}

arm_dest() {   # $1 arm -> "host port"
	case "$1" in
		D-plain) echo "$GUEST $D_PORT" ;;
		D-stamp) echo "$GUEST $D_STAMP_PORT" ;;
		A-plain) echo "127.0.0.1 $A_PORT" ;;
		A-stamp) echo "127.0.0.1 $A_STAMP_PORT" ;;
		*) die "unknown arm $1" ;;
	esac
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" host port stamps=0
	read -r host port <<< "$(arm_dest "$a")"
	case "$a" in *-stamp) stamps=1 ;; esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	PROBE_STAMPS="$stamps" m_probe "$OUT" "$t" "$host" "$port"
	gpu_idle_in_window "$t"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and on every tegrastats line of every window"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight; no window sampler"
fi
m_require_balanced_k "$K" 4
[ -r "$PROBE" ] || die "missing: $PROBE"
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
[ -r "$CONSOLE" ] || die "missing: $CONSOLE"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_STAMP_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_STAMP_PORT -- is this ifs-stamp?"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "safety monitor listening on :$D_PORT (frame=64 bytes" \
	|| die "the guest console shows no plain TCP monitor on :$D_PORT"
[ -z "$(m_pids_of monitor-native)" ] \
	|| die "a monitor-native is already running; it could answer an A arm in place of this run's. Stop it first."
# ALWAYS through the builder: it rebuilds from this tree's source, or refuses a
# MON built from other source (its guard; FORCE=1 overrides). FOUND BY REVIEW:
# the first version reused an existing MON unchecked -- any binary that printed
# the stamp banner would have passed as this run's control.
OUT="$MON" bash "$here/build-monitor-native.sh" > /dev/null \
	|| die "could not build $MON -- one built from other source is refused: remove it, or use another MON"
# The counter behind every stamp: CLOCK_MONOTONIC advances in its ticks (Tegra234:
# 31.25 MHz, 32 ns), and a KVM guest inherits the host's. Recorded, not assumed.
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"

m_prepare_out "${OUT:-}" "$HOME/stamp-out"
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE"
m_require_disjoint "qemu=$QEMU_CORES" "monitor=$CORE_MON" "probe=$CORE_PROBE"

# The native control: the same monitor.c, both modes, pinned to their own core.
taskset -c "$CORE_MON" "$MON" "$A_PORT" > "$OUT/monitor-native-plain.log" 2>&1 &
MON_PIDS="$MON_PIDS $!"
taskset -c "$CORE_MON" "$MON" "$A_STAMP_PORT" stamp > "$OUT/monitor-native-stamp.log" 2>&1 &
MON_PIDS="$MON_PIDS $!"
sleep 0.5
grep -qF "safety monitor listening on :$A_PORT (" "$OUT/monitor-native-plain.log" \
	|| die "the native plain monitor did not start -- see $OUT/monitor-native-plain.log"
grep -qF "stamping replies on :$A_STAMP_PORT:" "$OUT/monitor-native-stamp.log" \
	|| die "the native monitor did not start stamping -- is $MON built from the OD15 monitor.c? (see $OUT/monitor-native-stamp.log)"

m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
[ "$SAMPLE_WINDOW" = 1 ] && m_sampler_preflight
for a in "${ARMS[@]}"; do
	read -r host port <<< "$(arm_dest "$a")"
	m_reachable "$host" "$port" "$a"
done

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "stamp"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE}" \
	"\"ports\": {\"D-plain\": $D_PORT, \"D-stamp\": $D_STAMP_PORT, \"A-plain\": $A_PORT, \"A-stamp\": $A_STAMP_PORT}" \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"monitor_native_source\": \"$(cat "$MON.source-sha256" 2>/dev/null | head -1 | tr -d '"')\"" \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm: class 3, conf 95, 124 us, kind 0"' \
	'"order": "Williams design over the four arms, period 4"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	'"arms": ["D-plain", "D-stamp", "A-plain", "A-stamp"]'

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, Williams over 4 arms -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" 4); do order+=("${ARMS[$i]}"); done
	echo "round $r order: ${order[*]}" >> "$OUT/order.log"
	for a in "${order[@]}"; do run_arm "$a" "$r"; done
	say "round $r/$K done (${order[*]})"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" D-plain "${ARMS[@]}"
say "the stamp's own cost, and the boundary with it off and on"
m_pairs "$OUT" D-stamp:D-plain A-stamp:A-plain D-plain:A-plain D-stamp:A-stamp
say "the split, per stamp arm: medians over rounds of each round's percentile (us)"
python3 - "$OUT" <<'PY'
import glob, json, statistics as st, sys
out = sys.argv[1]
for arm in ("D-stamp", "A-stamp"):
    rows = [json.load(open(f))["summary"] for f in sorted(glob.glob("%s/lat-%s_r*.json" % (out, arm)))]
    for part in ("server_us", "other_us"):
        cells = []
        for p in ("p50", "p90", "p99", "p999", "max"):
            cells.append("%s %.2f" % (p, st.median(r[part][p] for r in rows)))
        print("  %-8s %-10s k=%d  %s" % (arm, "monitor" if part == "server_us" else "the rest", len(rows),
                                        "  ".join(cells)))
PY
