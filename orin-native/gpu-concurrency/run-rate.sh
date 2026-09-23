#!/usr/bin/env bash
# run-rate.sh -- the offered-rate sweep (measurement-design 3.5): the 2 ms spacing
# every A6 figure used, treated as a constant under test rather than a setting.
#
# Phase 3b / A6. Twelve arms: the same monitor, stamping (OD15), at six spacings,
# in the guest and natively:
#
#   D200us D500us D1ms D2ms D5ms D10ms   the guest's stamping monitor, :7103
#                                        (ifs-stamp.bin)
#   A200us A500us A1ms A2ms A5ms A10ms   the same monitor.c built natively on this
#                                        host, stamping, over loopback -- no KVM
#
# The spacing is the probe's sleep AFTER each reply, so the achieved period is the
# round trip plus it (plus the loop's own work). The probe measures that period
# from its own send times (summary "period_us"); periods.log keeps the wall time
# around each whole probe call only as an upper bound. Every arm stamps, so every
# spacing also splits into the monitor's own time and the rest. KVM_STATS=1: the
# VM's own halt-poll counters are read before and after every arm.
#
# THE PREDICTION, AND HOW IT CHANGED. Recorded in full because the second version
# is not blind.
#
# As first written (2026-09-24, before any run): KVM halt-polls on both hosts
# (halt_poll_ns = 500000), so the guest round trip would be faster below 0.5 ms
# spacing than at 1 ms and above, "with the step between 0.5 and 1 ms"; the
# native control would show no step; the change would lie in "the rest", not in
# the monitor's own time.
#
# What happened next, in order:
#   - A smoke run (n = 50) put the guest's step between 0.2 and 0.5 ms. It also
#     showed the monitor's own time falling at 0.2 ms.
#   - The review, reading only the code, found the first version inconsistent
#     with its own mechanism. The vCPU idles through the sleep PLUS both transits,
#     so at 0.5 ms spacing its idle gap is always over 500 us. With
#     halt_poll_ns_shrink = 0 (5.15), KVM then resets that vCPU's poll window to 0.
#     So halt polling predicts the step between 0.2 and 0.5 ms.
#
# The amended prediction below therefore agrees with data already seen. The
# recorded run REPLICATES it at n = 1000; it does not test it blind.
#
# AMENDED (before the recorded run): the guest is fast at 0.2 ms and slow at 0.5 ms
# and above (D500us belongs with D1ms), and the native control shows no step.
# Refuted by: a guest-only step between 0.5 and 1 ms, with D500us fast; or D200us
# fast while its idle gap (period minus round trip) exceeds 500 us. Only one arm
# lies on the polled side, so the run can show a difference, not tell a step
# from a slope.
#
# THE BLIND TEST, which no earlier run could see: the VM's halt-poll counters. If
# halt polling is the mechanism, successful polls end most halts at D200us and
# almost none at D500us and above. The A arms, with the guest idle, give the
# background. A step without that signature is not credited to halt polling.
#
# Whether any of this bears on the load speed-up in the interference records is
# NOT tested here.
#
# A WILLIAMS DESIGN over the twelve (period 12), so K must be a multiple of 12.
# c7 OFF by default (CSTATE=shallow, set before the library; OD15's lesson); a
# host with no cpuidle has nothing to disable. NO LOAD, as run-stamp.sh checks
# it. A STALL STOPS THE RUN. The native monitor always goes through
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
SPACINGS=(200us 500us 1ms 2ms 5ms 10ms)
ARMS=()
for s in "${SPACINGS[@]}"; do ARMS+=("D$s"); done
for s in "${SPACINGS[@]}"; do ARMS+=("A$s"); done
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

spacing_ms() {   # $1 arm -> the probe's --interval-ms
	case "${1:1}" in
		200us) echo 0.2 ;; 500us) echo 0.5 ;; 1ms) echo 1 ;;
		2ms) echo 2 ;; 5ms) echo 5 ;; 10ms) echo 10 ;;
		*) die "no spacing for arm $1" ;;
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

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2" t="$1_r$2" host port t0 t1
	case "$a" in D*) host="$GUEST"; port="$D_PORT" ;; A*) host=127.0.0.1; port="$A_PORT" ;; esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	t0="$(date +%s%N)"
	INTERVAL_MS="$(spacing_ms "$a")" PROBE_STAMPS=1 m_probe "$OUT" "$t" "$host" "$port"
	t1="$(date +%s%N)"
	echo "$t spacing_ms=$(spacing_ms "$a") frames=$((N + WARMUP)) elapsed_ns=$((t1 - t0))" >> "$OUT/periods.log"
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

m_prepare_out "${OUT:-}" "$HOME/rate-out"
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
	'"experiment": "rate"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"ports\": {\"D\": $D_PORT, \"A\": $A_PORT}" \
	'"spacings_ms": [0.2, 0.5, 1, 2, 5, 10]' \
	"\"kvm_halt_poll\": $HALT_POLL" \
	'"kvm_stats": 1' \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"monitor_native_source\": \"$(head -1 "$MON.source-sha256" 2>/dev/null | tr -d '"')\"" \
	"\"counter\": \"${TIMER:-unread}\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	'"order": "Williams design over the twelve arms, period 12"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, spacings ${SPACINGS[*]}, guest and native, Williams over ${#ARMS[@]} -> $OUT"
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
m_summary "$OUT" D2ms "${ARMS[@]}"
say "each spacing against 2 ms, paired within round"
pairs=()
for s in 200us 500us 1ms 5ms 10ms; do pairs+=("D$s:D2ms"); done
for s in 200us 500us 1ms 5ms 10ms; do pairs+=("A$s:A2ms"); done
m_pairs "$OUT" "${pairs[@]}"
say "per arm, medians over rounds: round trip, monitor, the rest and period (us); halt polls per exchange"
python3 - "$OUT" "$N" "$WARMUP" "${ARMS[@]}" <<'PY'
import glob, json, statistics as st, sys
out, n, warm, arms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]
ex = n + warm
def kvm(a):
    """Per round: the VM's halt counters' change per exchange across the arm."""
    rows = []
    for f in sorted(glob.glob("%s/kvm-%s_r*.json" % (out, a))):
        d = json.load(open(f))
        b, e = d["before"]["counters"], d["after"]["counters"]
        dd = {k: (e[k] - b[k]) for k in ("halt_attempted_poll", "halt_successful_poll", "halt_wakeup")
              if isinstance(e.get(k), int) and isinstance(b.get(k), int)}
        rows.append(dd)
    return rows
print("  %-7s %-4s %9s %8s %9s %9s %9s  %10s %10s %8s" % ("arm", "k", "rtt", "monitor", "rest", "period",
      "idle gap", "poll ok/ex", "attempt/ex", "ok share"))
for a in arms:
    rows = [json.load(open(f))["summary"] for f in sorted(glob.glob("%s/lat-%s_r*.json" % (out, a)))]
    rtt = st.median(r["p50_ms"] * 1000.0 for r in rows)
    per = st.median(r["period_us"]["p50"] for r in rows)
    ks = kvm(a)
    ok = st.median(k["halt_successful_poll"] / ex for k in ks) if ks else float("nan")
    att = st.median(k["halt_attempted_poll"] / ex for k in ks) if ks else float("nan")
    share = st.median((k["halt_successful_poll"] / k["halt_attempted_poll"]) if k["halt_attempted_poll"] else 0.0
                      for k in ks) if ks else float("nan")
    print("  %-7s %-4d %9.2f %8.2f %9.2f %9.1f %9.1f  %10.3f %10.3f %8.2f"
          % (a, len(rows), rtt, st.median(r["server_us"]["p50"] for r in rows),
             st.median(r["other_us"]["p50"] for r in rows), per, per - rtt, ok, att, share))
print("  idle gap = period - round trip (both medians): the time from a reply to the next request.")
print("  polls are the VM's counters (all its vCPUs); the A arms, with the guest idle, are the background.")
PY
