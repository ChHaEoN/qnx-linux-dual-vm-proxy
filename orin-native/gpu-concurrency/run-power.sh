#!/usr/bin/env bash
# run-power.sh -- the price of halt polling in watts: the board's power rails for
# VMs that block and VMs that poll, idle and under traffic. Phase 3b / A6,
# 2026-09-24; the sixth suggestion of the literature pass (the kernel's halt-polling
# documentation: a large window can drive an otherwise idle CPU to 100%).
#
# WHAT IS KNOWN. halt_poll_ns 5000000 takes 32-36 us off the p50 at 2 ms spacing
# (20260924T-a6-orin-haltpoll), and kept QEMU's two busiest threads ~92% busy,
# against ~6% and ~3% with the default. At 0.2 ms the default window already polls
# (two threads at ~67%). Nothing has measured what that costs in power. Read
# before this harness was written: the rails (VDD_IN, VDD_CPU_GPU_CV, VDD_SOC on the
# INA3221; 512-sample averaging, a new reading every ~140 ms). No power was
# compared.
#
# THE DESIGN is run-haltpoll.sh's: every round boots three VMs (halt_poll_ns 0 N,
# 500000 D, 5000000 B) in a Williams order (period 6). Each boot has three arms,
# in the same order for every boot of a round, rotating by round:
#   idle    no traffic, IDLE_S (10) seconds
#   200us   the probe at 0.2 ms spacing, N200 (24000) exchanges, ~10 s
#   2ms     the probe at 2 ms spacing, N2 (4400) exchanges, ~10 s
# nine arms in all: Nidle N200us N2ms, Didle D200us D2ms, Bidle B200us B2ms.
# power_window.py samples the rails every 20 ms on CORE_AUX; each arm's power is
# the mean inside its own KVM snapshots' window (the same clock). QEMU's threads'
# CPU time comes from the same snapshots. The CPU governor is pinned (performance,
# 1344 MHz), as in every A6 run, so these are not the board's idle-governor watts.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended; if a smoke run contradicts it, the
# record says so. Rail VDD_CPU_GPU_CV (the CPU; the GPU is idle), paired within
# round, median over the k = 6 rounds:
#   P1 2 ms traffic, B - D: median >= +150 mW and above zero in all 6 rounds.
#      REFUTED if <= +30 mW. Between: PARTIAL.
#   P2 idle, B - D: |median| <= 30 mW. The guest's idle wake-ups are ~30 ms
#      apart per vCPU (the rate record's idle counters), longer than even a 5 ms
#      window, so the window stays at zero and nothing spins. FAILED otherwise.
#   P3 0.2 ms traffic, D - N: median >= +100 mW (the default window already
#      spins there). REFUTED if <= +20 mW. Between: PARTIAL.
# NOT PREDICTED: VDD_IN and VDD_SOC, B - D at 0.2 ms, and the latency the power
# buys (reported: us saved per watt).
# THE MANIPULATION CHECKS (a prediction resting on a failed one prints VOID):
#   M1 QEMU's busiest thread's share of the window: B2ms >= 0.8 and D2ms <= 0.2
#      -> P1; D200us >= 0.5 and N200us <= 0.3 -> P3
#   M2 every arm's window holds >= 200 power samples -> P1, P2, P3
# power_report.py applies all of it, and only at k = 6.
#
# NEEDS: no QEMU running; IFS_BIN (ifs-stamp.bin) and DISK. c7 is OFF
# (CSTATE=shallow, set before the library). NO LOAD. A STALL STOPS THE RUN. K a
# multiple of 6.
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
N200="${N200:-24000}"
N2="${N2:-4400}"
N="$N2"                        # m_probe reads N; every probe arm sets its own
IDLE_S="${IDLE_S:-10}"
K="${K:-6}"
WARMUP="${WARMUP:-200}"
PW="${PW:-$here/power_window.py}"
INTERVAL_MS=2                   # the preflight's; every arm sets its own
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/power_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IFS_BIN="${IFS_BIN:?set IFS_BIN to ifs-stamp.bin}"
DISK="${DISK:?set DISK to the guest disk}"
SETTLE_S="${SETTLE_S:-3}"       # after the guest answers, before its first arm
HP_PARAM="${HP_PARAM:-/sys/module/kvm/parameters/halt_poll_ns}"
CFGS=(N D B)
declare -A HP=([N]=0 [D]=500000 [B]=5000000)
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0                 # as run-rate.sh: a 0.2 ms arm is shorter than tegrastats' first line
KVM_STATS=1                     # the manipulation checks
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
ARMS=(Nidle N200us N2ms Didle D200us D2ms Bidle B200us B2ms)
STAMP_ARMS="N200us N2ms D200us D2ms B200us B2ms"
PW_PID=""
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
HP_BEFORE=""; VM_PID=""; BOOTED=0

set_hp() {   # $1 value: write it, and read it back
	echo "$1" | sudo -n tee "$HP_PARAM" > /dev/null || die "could not write $HP_PARAM"
	[ "$(cat "$HP_PARAM")" = "$1" ] || die "$HP_PARAM reads back '$(cat "$HP_PARAM")', not $1"
}

stop_vm() {   # stop the VM this harness booted; true once it is gone
	local i
	[ -n "$VM_PID" ] || return 0
	kill -TERM "$VM_PID" 2>/dev/null
	for i in $(seq 1 30); do [ -d "/proc/$VM_PID" ] || break; sleep 0.5; done
	if [ -d "/proc/$VM_PID" ]; then
		kill -KILL "$VM_PID" 2>/dev/null; sleep 1
	fi
	[ -d "/proc/$VM_PID" ] && return 1
	VM_PID=""
	return 0
}

cleanup() {
	say "cleanup"
	[ -n "$PW_PID" ] && kill "$PW_PID" 2>/dev/null
	# The preflight refused a running QEMU, so once this harness has booted one,
	# every QEMU is its own -- including one whose pid it had not yet read, or a
	# second one (FOUND BY REVIEW: VM_PID could hold two pids, which stop_vm
	# would have reported as stopped).
	if [ "$BOOTED" = 1 ]; then
		for VM_PID in $(m_pids_of qemu-system-aarch64); do
			stop_vm || echo "WARNING: the guest QEMU $VM_PID would not stop" >&2
		done
	fi
	VM_PID=""
	if [ -n "$HP_BEFORE" ]; then
		echo "$HP_BEFORE" | sudo -n tee "$HP_PARAM" > /dev/null 2>&1 \
			&& [ "$(cat "$HP_PARAM")" = "$HP_BEFORE" ] && say "halt_poll_ns restored to $HP_BEFORE" \
			|| echo "WARNING: could not restore $HP_PARAM to $HP_BEFORE" >&2
	fi
	m_sampler_stop; m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

# Every QEMU thread on QEMU_CORES, read back per thread. m_pin_qemu does this AND
# hashes the image and disk; that is done once, at the preflight boot, and every
# later boot is checked to have been given the same two paths.
pin_vm() {
	local t got
	for t in $(ls "/proc/$VM_PID/task"); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1 || [ ! -d "/proc/$VM_PID/task/$t" ] \
			|| die "taskset failed on QEMU thread $t"
		got="$(awk '/^Cpus_allowed_list:/ {print $2}' "/proc/$VM_PID/task/$t/status" 2>/dev/null)"
		[ -z "$got" ] || [ "$(_cpuset "$got")" = "$(_cpuset "$QEMU_CORES")" ] \
			|| die "QEMU thread $t reads back '$got', asked for '$QEMU_CORES'"
	done
}

boot_vm() {   # $1 config  $2 label: boot a VM with that config's halt_poll_ns
	local c="$1" lab="$2" log="$OUT/console-$2.log" i t0 t1 args
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	set_hp "${HP[$c]}"
	BOOTED=1
	t0="$(date +%s%N)"
	# The VM's shape is given, not inherited: an exported IVSHMEM, KICK_SOCK,
	# THREAD_NAMES, SMP, MEM or TAP would otherwise change it silently. And QEMU
	# must not inherit fd 9: a QEMU that outlived the run would hold the lock.
	IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=0 SMP=2 MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	for i in $(seq 1 40); do
		tr -d '\0\r' < "$log" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" && break
		sleep 0.5
	done
	tr -d '\0\r' < "$log" | grep -aqF "stamping replies on :$D_PORT: t_in payload[8..15]" \
		|| die "boot $lab: no stamping monitor on :$D_PORT in $log -- is IFS_BIN ifs-stamp.bin?"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IFS_BIN "*) ;; *) die "boot $lab: QEMU was not given $IFS_BIN" ;; esac
	case "$args" in *"file=$DISK,"*) ;; *) die "boot $lab: QEMU was not given $DISK" ;; esac
	pin_vm
	m_reachable "$GUEST" "$D_PORT" "boot $lab's stamping monitor" > /dev/null
	t1="$(date +%s%N)"
	sleep "$SETTLE_S"
	echo "$lab halt_poll_ns=$(cat "$HP_PARAM") qemu_pid=$VM_PID boot_ms=$(( (t1 - t0) / 1000000 ))" >> "$OUT/boots.log"
}

pw_start() {   # $1 tag: the rail sampler, pinned to the aux core
	rm -f "$OUT/pw-$1.stop"
	taskset -c "$CORE_AUX" python3 "$PW" --out "$OUT/pw-$1.json" --stop-file "$OUT/pw-$1.stop" \
		--max-s $(( IDLE_S + 120 )) > "$OUT/pw-$1.err" 2>&1 &
	PW_PID=$!
	sleep 0.3
	kill -0 "$PW_PID" 2>/dev/null || die "the power sampler did not start -- see $OUT/pw-$1.err"
}

pw_stop() {    # $1 tag
	touch "$OUT/pw-$1.stop"
	wait "$PW_PID" || die "the power sampler failed -- see $OUT/pw-$1.err"
	PW_PID=""
	[ -s "$OUT/pw-$1.json" ] || die "the power sampler wrote nothing for $1"
}

spacing_ms() {   # $1 arm -> the probe's --interval-ms
	case "${1:1}" in
		200us) echo 0.2 ;; 2ms) echo 2 ;;
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
	local a="$1" r="$2"
	local t="$a"_r"$r"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	sleep 2                      # let the last arm's load leave the rails
	pw_start "$t"
	case "$a" in
		*idle)
			m_kvm_snap "$OUT/kvm-$t.json" before
			sleep "$IDLE_S"
			m_kvm_snap "$OUT/kvm-$t.json" after ;;
		*200us)
			N="$N200" INTERVAL_MS=0.2 PROBE_STAMPS=1 m_probe "$OUT" "$t" "$GUEST" "$D_PORT" ;;
		*2ms)
			N="$N2" INTERVAL_MS=2 PROBE_STAMPS=1 m_probe "$OUT" "$t" "$GUEST" "$D_PORT" ;;
		*) die "no arm kind for $a" ;;
	esac
	pw_stop "$t"
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "$r" "$a"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of qemu-system-aarch64)" ] \
	|| die "a QEMU is already running: this harness boots its own guests. Stop it first."
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm (no window sampler: windows are shorter than tegrastats interval)"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight; no window sampler"
fi
m_require_balanced_k "$K" "${#CFGS[@]}"
for f in "$PROBE" "$REPORT" "$PW" "$LAUNCH" "$IFS_BIN" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
case "$IFS_BIN$DISK" in *" "*) die "IFS_BIN and DISK may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q -- '--stamps' "$PROBE" || die "$PROBE has no --stamps: it predates OD15"
[ -r "$HP_PARAM" ] || die "no $HP_PARAM on this host"
HP_BEFORE="$(cat "$HP_PARAM")"
# D is 500000 because that is the value every A6 record ran with. Anything else
# is most likely left behind by a run that was killed before its cleanup, and
# "restoring" it at the end would carry it into every later harness.
[ "$HP_BEFORE" = 500000 ] \
	|| die "$HP_PARAM reads $HP_BEFORE, not the default 500000 -- a killed run may have left it; restore it first"
TIMER="$(sudo -n dmesg 2>/dev/null | grep -o 'arch_timer: cp15 timer(s) running at [0-9.]*MHz' | head -1)"
[ -n "$TIMER" ] || die "no arch_timer frequency in dmesg -- the monitor's ticks could not be counted"
HALT_POLL=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALT_POLL="$HALT_POLL\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo unread)\", "
done
HALT_POLL="{${HALT_POLL%, }}"

python3 -c "import glob,sys; sys.exit(0 if glob.glob('/sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*/in1_label') else 1)" \
	|| die "no INA3221 rails on this host"
m_prepare_out "${OUT:-}" "$HOME/power-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
m_governor_pin
m_cstate_apply

# One preflight boot, at D: it proves the boot path, and m_pin_qemu identifies
# (hashes) the image and disk for the stamp. Stopped before round 1.
boot_vm D preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS='"per arm: see spacings_ms"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "power"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	'"halt_poll_ns_by_config": {"N": 0, "D": 500000, "B": 5000000}' \
	"\"halt_poll_ns_found\": \"$HP_BEFORE\"" \
	"\"kvm_halt_poll_at_preflight\": $HALT_POLL" \
	'"arms_per_boot": {"idle_s": '"$IDLE_S"', "200us": {"n": '"$N200"', "spacing_ms": 0.2}, "2ms": {"n": '"$N2"', "spacing_ms": 2}}' \
	'"boots": "three per round, a Williams order over N D B (period 6); idle, 200us and 2ms per boot, in the same order for every boot of a round, rotating by round; see boots.log"' \
	'"power": "power_window.py, INA3221 rails every 20 ms on the aux core; each arm the mean inside its KVM snapshots"' \
	"\"settle_s\": $SETTLE_S" \
	'"kvm_stats": 1' \
	"\"counter\": \"$TIMER\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"claims": "latency_probe.build_frame on every arm, stamped (OD15)"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${ARMS[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, boots N D B (halt_poll_ns 0 500000 5000000) x arms idle ${IDLE_S}s, 200us n=$N200, 2ms n=$N2 -> $OUT"
: > "$OUT/thermal.log"
for r in $(seq 1 "$K"); do
	order=()
	for i in $(m_williams_row "$r" "${#CFGS[@]}"); do order+=("${CFGS[$i]}"); done
	line="round $r order:"
	for ci in "${!order[@]}"; do
		c="${order[$ci]}"
		# The same spacing order for every boot in the round, alternating across
		# rounds: each configuration gets each order in half the rounds, and every
		# pair across boots is matched by position (FOUND BY REVIEW; see the header).
		# The same arm order for every boot of the round, rotating by round:
		# each order in two of the six rounds.
		case $(( r % 3 )) in 0) sp=(idle 200us 2ms) ;; 1) sp=(200us 2ms idle) ;; 2) sp=(2ms idle 200us) ;; esac
		boot_vm "$c" "${c}_r$r"
		for s in "${sp[@]}"; do run_arm "$c$s" "$r"; line="$line $c$s"; done
		stop_vm || die "the guest of ${c}_r$r would not stop"
	done
	echo "$line" >> "$OUT/order.log"
	say "round $r/$K done"
done

set_hp "$HP_BEFORE"
m_governor_recheck
m_stamp_after "$OUT/stamp.json"
N="$N200" m_require_complete "$OUT" N200us D200us B200us
N="$N2" m_require_complete "$OUT" N2ms D2ms B2ms
for a in Nidle Didle Bidle; do
	for r in $(seq 1 "$K"); do
		[ -s "$OUT/pw-${a}_r$r.json" ] && [ -s "$OUT/kvm-${a}_r$r.json" ] || die "idle arm ${a}_r$r is incomplete"
	done
done
say "summary"
m_summary "$OUT" D2ms N200us N2ms D200us D2ms B200us B2ms
say "round trip, paired within round"
m_pairs "$OUT" B2ms:D2ms D200us:N200us B200us:D200us
say "per arm, medians over rounds; per exchange over $((N + WARMUP)) exchanges; the checks and the predictions"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
