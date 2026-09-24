#!/usr/bin/env bash
# run-haltpoll.sh -- does the guest's 0.2 ms speed-up, and its monitor's halved
# span, follow KVM halt polling or the spacing? An intervention on halt_poll_ns.
# Phase 3b / A6, 2026-09-24; follows 20260924T-a6-orin-rate and -vcpupin.
#
# WHAT IS KNOWN. At 0.2 ms spacing the guest's p50 round trip is 41-48 us shorter
# than at 2 ms, and the stamping monitor's own span is 6 ticks against 12. At
# 0.2 ms, 99% of vCPU halts end in a successful KVM poll; at 2 ms almost none do,
# and the vCPU blocks. So far that is CO-VARIATION: the spacing was changed, and
# the polling changed with it. The vCPU-pinning test ruled out one mechanism for
# the halving, KVM's last_vcpu_ran flush. The spacing itself (the guest's idle
# length) was never separated from the polling.
#
# THE INTERVENTION. halt_poll_ns caps KVM's poll window, and Linux 5.15 copies it
# into a VM when the VM is created (kvm->max_halt_poll_ns; checked in the v5.15
# source). So each value needs its own VM, and every round boots three:
#   N  halt_poll_ns = 0        no polling at all: a halt with nothing pending blocks
#   D  halt_poll_ns = 500000   the default, as in every A6 record
#   B  halt_poll_ns = 5000000  a 5 ms window: a 2 ms idle ends in a poll
# Each boot is timed at both spacings, so six arms:
#   N200us N2ms  D200us D2ms  B200us B2ms   (the stamping monitor, ifs-stamp.bin :7103)
# The boots' order within a round is a Williams design over the three (period 6).
# Within a round, all three boots take their two spacings in the SAME order, and
# that order alternates from round to round. So every scored pair across boots
# compares arms in the same position after their boot. The value stays in force
# for the whole boot (whether a VM reads it live or not), and the found value is
# restored at the end. Pairs across boots within a round carry the boot-to-boot
# variance inside their band.
#
# CHANGED AFTER THE FIRST RECORDED RUN HAD STARTED (2026-09-24), FOUND BY REVIEW.
# Nothing in the prediction block below changed. Four other things did:
#   - The spacing order within a boot was (round + configuration) % 2. That gave
#     N and B one order and D the other in every round, so every scored pair
#     across boots set an arm run first after its boot against one run second.
#     A first-after-boot effect would then eat into the 10/12 counts and C1's
#     bands. It is now round % 2 for all three.
#   - The launcher gets an explicit VM shape, and not the harness's lock.
#   - Cleanup stops every QEMU once the harness has booted one.
#   - A found halt_poll_ns other than 500000 is refused.
# The first run (the committed design) is kept and reported beside this one.
#
# THE PREDICTION, written and committed before any run of this harness, smoke
# runs included. It is not to be amended. If a smoke run contradicts it, the
# record says so. H: both effects are the blocked path's, so they follow the
# polling and not the spacing. Round trip = p50 in us; monitor = p50 in ticks;
# pairs within round, median over the k = 12 rounds.
#   P1  N200us - N2ms, round trip: median >= -15 us (without polling the step is
#       gone). REFUTED if <= -30 us. Between: PARTIAL.
#   P2  B2ms - D2ms, round trip: median <= -30 us (polling at 2 ms brings the
#       step). REFUTED if >= -15 us. Between: PARTIAL.
#   P3a N200us - D200us, monitor: median >= +4 ticks and above zero in >= 10/12
#       rounds (no polling, no halving). REFUTED if the median <= +1.
#   P3b B2ms - D2ms, monitor: median <= -4 ticks and below zero in >= 10/12
#       rounds (polling at 2 ms halves it). REFUTED if the median >= -1.
#   C1  (control) B200us - D200us: |round trip| <= 5 us and |monitor| <= 1 tick.
#       Where D already polls, a longer window should change nothing.
# THE MANIPULATION CHECKS, which make the predictions scoreable at all. They
# come from the VM's own counters (KVM_STATS=1). The report prints VOID instead
# of a verdict for any prediction that rests on a failed check:
#   M1  every N arm: zero attempted polls in every round (the poll really was off)
#       -> P1, P3a
#   M2  B2ms's blocked wake-ups per exchange <= half of D2ms's (the 5 ms window
#       really replaced the blocking) -> P2, P3b, C1
#   M3  D200us's poll success share >= 0.9 and D2ms's <= 0.2 (the default
#       regime replicated) -> P2, P3a, P3b, C1
# haltpoll_report.py applies all of it, and only at k = 12.
#
# NEEDS: no QEMU running (the harness boots every VM, and stops it); the image
# and disk (IFS_BIN, DISK; ifs-stamp.bin). c7 is OFF (CSTATE=shallow, set before
# the library). NO LOAD. A STALL STOPS THE RUN. K a multiple of 6.
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
N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2                   # the preflight's; every arm sets its own
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/haltpoll_report.py}"
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
ARMS=(N200us N2ms D200us D2ms B200us B2ms)
STAMP_ARMS="${ARMS[*]}"
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
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	INTERVAL_MS="$(spacing_ms "$a")" PROBE_STAMPS=1 m_probe "$OUT" "$a"_r"$r" "$GUEST" "$D_PORT"
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
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IFS_BIN" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
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

m_prepare_out "${OUT:-}" "$HOME/haltpoll-out"
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
	'"experiment": "haltpoll"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"port\": $D_PORT" \
	'"halt_poll_ns_by_config": {"N": 0, "D": 500000, "B": 5000000}' \
	"\"halt_poll_ns_found\": \"$HP_BEFORE\"" \
	"\"kvm_halt_poll_at_preflight\": $HALT_POLL" \
	'"spacings_ms": {"200us": 0.2, "2ms": 2}' \
	'"boots": "three per round, a Williams order over N D B (period 6); both spacings per boot, in the same order for every boot of a round, alternating by round; see boots.log"' \
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
say "k=$K rounds, n=$N, warmup=$WARMUP, boots N D B (halt_poll_ns 0 500000 5000000) x spacings 200us 2ms -> $OUT"
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
		if [ $(( r % 2 )) -eq 0 ]; then sp=(200us 2ms); else sp=(2ms 200us); fi
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
m_require_complete "$OUT" "${ARMS[@]}"
say "summary"
m_summary "$OUT" D2ms "${ARMS[@]}"
say "round trip, paired within round"
m_pairs "$OUT" N200us:N2ms D200us:D2ms B200us:B2ms B2ms:D2ms N200us:D200us B200us:D200us N2ms:D2ms
say "per arm, medians over rounds; per exchange over $((N + WARMUP)) exchanges; the checks and the predictions"
python3 "$REPORT" "$OUT" "$N" "$WARMUP" || die "the report could not be made -- see above"
