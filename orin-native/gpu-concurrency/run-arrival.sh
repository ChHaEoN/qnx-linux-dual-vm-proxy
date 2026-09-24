#!/usr/bin/env bash
# run-arrival.sh -- irregular arrivals: the same mean rates as the constant
# spacings every A6 figure used, with exponential gaps. Phase 3b / A6, 2026-09-24;
# the second suggestion of the literature pass.
#
# WHY. The Linux kernel's halt-polling documentation says its adaptive window
# settles well only for wake-ups that come at an approximately constant rate. Every
# A6 run so far spaced its requests evenly: the probe slept the same time after
# every reply. Real traffic is not even. The rate record showed the poll window
# decides ~40 us of the guest's p50, and on this host (halt_poll_ns 500000,
# shrink 0) one idle span longer than the window resets it to zero, after which it
# must grow back from 10 us by doubling.
#
# Six arms, on one boot of the stamping guest (ifs-stamp.bin, :7103) and the same
# monitor.c built natively (:7203), as run-rate.sh:
#   Dc200us Dc2ms   the guest, constant sleep 0.2 / 2 ms after each reply
#   De200us De2ms   the guest, sleep drawn from an exponential distribution with
#                   mean 0.2 / 2 ms (latency_probe.py --arrival exp, seeded per
#                   arm-round, every draw recorded)
#   Ac200us Ae200us the native control, constant and exponential, mean 0.2 ms
# A Williams design over the six (period 6), K a multiple of 6. KVM_STATS=1.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended; if a smoke run contradicts it, the
# record says so. H: irregular gaps keep resetting the poll window, so at a mean
# where constant gaps poll, exponential gaps lose much of the benefit.
#   P1 De200us - Dc200us, p50 round trip, paired within round: median >= +10 us.
#      REFUTED if <= +3 us. Between: PARTIAL.
#   P2 (the VM's counters, blind to every timing) poll success share, median over
#      rounds: De200us <= 0.80 while Dc200us >= 0.90. REFUTED if De200us >= 0.90.
#   P3 De2ms - Dc2ms: |median| <= 5 us (at a 2 ms mean both mostly block).
#      FAILED otherwise.
#   C1 (control) Ae200us - Ac200us: |median| <= 3 us (no polling on the host side;
#      the gaps' shape alone should move little).
# THE MANIPULATION CHECK (a prediction resting on a failed one prints VOID):
#   M1 every exponential arm's recorded sleeps: mean within 10% of the set mean,
#      and sd/mean between 0.8 and 1.2 (an exponential's is 1), in every round
#      -> P1, P2, P3, C1
#   M2 Dc200us's success share >= 0.90 and Dc2ms's <= 0.20 (the constant regimes
#      replicate the rate record) -> P1, P2, P3
# arrival_report.py applies all of it, and only at k = 12.
#
# NOT PREDICTED: the tail, and any exponential arm's p90/p99.
#
# c7 OFF (CSTATE=shallow, set before the library). NO LOAD, as run-rate.sh checks
# it. A STALL STOPS THE RUN. The native monitor goes through
# build-monitor-native.sh's source guard (MON, default $HOME/stamp/monitor-native).
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
D_PORT="${D_PORT:-7103}"
A_PORT="${A_PORT:-7203}"
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2                   # the preflight's; every arm sets its own
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
# NO WINDOW SAMPLER, even on a Tegra. FOUND BY THE FIRST SMOKE RUN: tegrastats
# samples every 500 ms and its first line comes a full interval in, while the
# shortest spacings' windows last ~0.5 s at n = 1000 -- the sampler's "at least
# one line per window" rule would fail them, or pass them by luck. The no-load
# check uses the GR3D readings taken just before and after every arm instead
# (m_thermal), and the stamp says so.
SAMPLE_WINDOW=0
KVM_STATS=1                     # the blind test: the VM's halt-poll counters per arm
CORE_AUX="${CORE_AUX:-5}"       # where m_kvm_snap reads them, off every measured core
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(Dc200us De200us Dc2ms De2ms Ac200us Ae200us)
REPORT="${REPORT:-$here/arrival_report.py}"
STAMP_ARMS="${ARMS[*]}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
MON_PID=""

cleanup() {
	say "cleanup"
	[ -n "$MON_PID" ] && kill "$MON_PID" 2>/dev/null
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

spacing_ms() {   # $1 arm -> the probe's --interval-ms (the mean, for an exponential arm)
	case "${1:2}" in
		200us) echo 0.2 ;; 2ms) echo 2 ;;
		*) die "no spacing for arm $1" ;;
	esac
}

arrival_of() {   # $1 arm -> const or exp
	case "${1:1:1}" in
		c) echo const ;; e) echo exp ;;
		*) die "no arrival kind for arm $1" ;;
	esac
}

# The GR3D readings m_thermal took just before and after an arm must both read 0%.
gpu_idle_around() {   # $1 round  $2 arm
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^r$1 $2 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $2 in round $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $2 in round $1 -- a GPU load ran beside this no-load run"
}

arm_index() {   # $1 arm -> its index in ARMS
	local i
	for i in "${!ARMS[@]}"; do [ "${ARMS[$i]}" = "$1" ] && { echo "$i"; return 0; }; done
	die "no arm $1"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" host port t0 t1
	case "$a" in D*) host="$GUEST"; port="$D_PORT" ;; A*) host=127.0.0.1; port="$A_PORT" ;; esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	t0="$(date +%s%N)"
	# Each arm-round draws its own sleeps: seed = 100 x round + the arm's index.
	INTERVAL_MS="$(spacing_ms "$a")" PROBE_STAMPS=1 PROBE_ARRIVAL="$(arrival_of "$a")" \
		PROBE_SEED=$(( 100 * r + $(arm_index "$a") )) m_probe "$OUT" "$t" "$host" "$port"
	t1="$(date +%s%N)"
	echo "$t arrival=$(arrival_of "$a") mean_ms=$(spacing_ms "$a") frames=$((N + WARMUP)) elapsed_ns=$((t1 - t0))" >> "$OUT/periods.log"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" "$a"
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
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm (no window sampler: windows are shorter than tegrastats interval)"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight; no window sampler"
fi
m_require_balanced_k "$K" "${#ARMS[@]}"
[ -r "$PROBE" ] || die "missing: $PROBE"
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
grep -q -- '--arrival' "$PROBE" || die "$PROBE has no --arrival: it predates the arrival test"
[ -r "$REPORT" ] || die "missing: $REPORT"
[ -r "$CONSOLE" ] || die "missing: $CONSOLE"
tr -d '\0\r' < "$CONSOLE" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
	|| die "the guest console shows no stamping monitor on :$D_PORT -- is this ifs-stamp?"
[ -z "$(m_pids_of monitor-native)" ] \
	|| die "a monitor-native is already running; it could answer an A arm in place of this run's. Stop it first."
OUT="$MON" bash "$here/build-monitor-native.sh" > /dev/null \
	|| die "could not build $MON -- one built from other source is refused: remove it, or use another MON"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"
HALT_POLL=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALT_POLL="$HALT_POLL\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo unread)\", "
done
HALT_POLL="{${HALT_POLL%, }}"

m_prepare_out "${OUT:-}" "$HOME/arrival-out"
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "monitor=$CORE_MON" "probe=$CORE_PROBE" "aux=$CORE_AUX"
taskset -c "$CORE_MON" "$MON" "$A_PORT" stamp > "$OUT/monitor-native-stamp.log" 2>&1 &
MON_PID=$!
sleep 0.5
grep -qF "stamping replies on :$A_PORT:" "$OUT/monitor-native-stamp.log" \
	|| die "the native monitor did not start stamping -- see $OUT/monitor-native-stamp.log"

m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"
m_reachable "$GUEST" "$D_PORT" "the guest's stamping monitor"
m_reachable 127.0.0.1 "$A_PORT" "the native stamping monitor"

INTERVAL_MS='"per arm: see spacings_ms"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "arrival"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"ports\": {\"D\": $D_PORT, \"A\": $A_PORT}" \
	'"arms_mean_ms": {"Dc200us": 0.2, "De200us": 0.2, "Dc2ms": 2, "De2ms": 2, "Ac200us": 0.2, "Ae200us": 0.2}' \
	'"arrivals": "c = constant sleep; e = exponential sleep with that mean, seed 100 x round + arm index"' \
	"\"kvm_halt_poll\": $HALT_POLL" \
	'"kvm_stats": 1' \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"monitor_native_source\": \"$(head -1 "$MON.source-sha256" 2>/dev/null | tr -d '"')\"" \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	'"order": "Williams design over the six arms, period 6"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, arms ${ARMS[*]}, Williams over ${#ARMS[@]} -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/periods.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#ARMS[@]}"); do order+=("${ARMS[$i]}"); done
	echo "round $r order: ${order[*]}" >> "$OUT/order.log"
	for a in "${order[@]}"; do run_arm "$a" "$r"; done
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" Dc2ms "${ARMS[@]}"
say "exponential against constant, paired within round"
m_pairs "$OUT" De200us:Dc200us De2ms:Dc2ms Ae200us:Ac200us Dc200us:Dc2ms
say "per arm, the checks and the predictions"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
