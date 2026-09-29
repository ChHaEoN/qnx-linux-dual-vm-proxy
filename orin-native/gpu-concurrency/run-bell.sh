#!/usr/bin/env bash
# run-bell.sh -- the two ways into the guest's notified shared memory: the console kick every
# notified arm has used since OD12, against the ivshmem doorbell INTO the guest (MSI-X through the
# GIC ITS to an LPI). Phase 3b / A6, 2026-09-29. The owner asked for it (2026-09-29, after the
# doorbell into the guest was built: continue with the comparison).
#
# WHAT IS KNOWN. The notified arm with the console kick in and the doorbell out, and what the
# console costs the guest's side: 20260922T-a6-orin-kick and 20260922T-a6-orin-shift (held
# locally). The doorbell into the guest works, from one functional, unpinned run whose round trips
# are orientation only: 20260929T-a6-orin-its (held locally).
#
# THE INSTRUMENTS.
#   guest  ifs-bell.bin: ifs-its.bin (startup-qemu-virt-its, qnx-its-probe msixcfg) with
#          qnx-safety-monitor-bell and two notified monitors on the one ivshmem device: shmkick at
#          slot 4096 on the virtio console (arm K) and shmkick at slot 8192 on the MSI-X LPI
#          (arm B). Both judge with judge_frame and reply through the ivshmem Doorbell.
#   host   latency_probe.py through libshmchan.so. K: --proto shmdb, one kick byte down the
#          console's socket, then a wait on the probe's own eventfd. B: --proto shmbell, a write to
#          the guest's vector-0 eventfd, then the same wait. The same loop, frame, handshake and
#          wait primitive; only the inbound notification differs.
#
# THE ARMS: K and B, both in every boot, AB/BA by round (a Williams order over the two). n=1000
# after 200 warm-up at 2 ms, K=16 rounds, one boot per round, -smp 2. QEMU pinned to cores 0-2,
# the probe to core 4, the governor pinned, c7 off, no load. KVM's exit counters around every arm.
# About 12 min.
#
# THE RULE, fixed here before any run (bell_report.py applies it). Per arm and round: the probe's
# p50 and p99, and KVM's mmio_exit_user and mmio_exit_kernel over the arm divided by its exchanges
# (warm-up included). Every difference is B - K, paired within the round; per difference, the
# median over rounds with the distribution-free interval of widest coverage >= 95% (d(4)..d(13),
# 97.9%, at K = 16).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended. The thresholds were set knowing the functional run's orientation-only round
# trips (20260929T-a6-orin-its); what is blind is this paired comparison under the OD11 design.
#   H1 the console is most of the inbound cost. B drops QEMU's main thread, the virtio console and
#      the guest's devc-virtio resource manager, and adds an irqfd-injected LPI and two ITS command
#      batches (the kernel's mask and unmask of the LPI).
#   P1 median DIFF(p50) <= -40 us: HELD. Below 0 with the interval's upper end below 0: PARTIAL.
#      Otherwise REFUTED.
#   P2 the tail follows. Median DIFF(p99) < 0 with the interval's upper end below 0: HELD. Median
#      below 0 alone: PARTIAL. Otherwise REFUTED.
#   H2 B leaves QEMU's userspace and trades it for the ITS in KVM's kernel: the LPI's mask and
#      unmask callouts each read and write GITS_CWRITER, and every ITS register traps.
#   P3 median DIFF(mmio_exit_user per exchange) <= -1.0, and median DIFF(mmio_exit_kernel per
#      exchange) >= +2.0. Both: HELD. One: PARTIAL. Neither: REFUTED.
# Not predicted, reported: the p90 and p99.9 differences, each arm's medians, and the halt-poll
# counters per exchange.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own transport (shmdb,
#      shmbell), the probe on its core (the gate, and the report again)
#   M2 in every arm-round exactly one doorbell per exchange: the probe's own counts show
#      exchanges == notifications == warm-up + n, no early wake-up and no stray byte
#   M3 every boot's guest console shows msixcfg done and both notified monitors serving, one on
#      /dev/vcon2 and one on "kick msix (LPI 8193)"
#   M4 KVM's counters were read before and after every arm (P3 only)
#
# What this does NOT test: more than one vector or one device; a real ITS (KVM keeps translations
# in the kernel); QNX's supported MSI path (the PCI server); the reply direction (both arms reply
# by the same doorbell); a1.metal (the same harness runs there through scripts/aws's harness
# phase); the tail beyond p99.
#
# NEEDS: no QEMU running; IMG_B (ifs-bell.bin), DISK; tap-qnx on br0; gcc (libshmchan.so is built
# here). CSTATE=shallow (set before the library). No load. K a multiple of 2.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

N="${N:-1000}"
K="${K:-16}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/bell_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
IMG_B="${IMG_B:-$HOME/output/ifs-bell.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
SLOT_K=4096
SLOT_B=8192
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(K B)
ARM_PROTOS="K=shmdb B=shmbell"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=1
FIFO_ARMS=""
STALL_POLICY=refuse
VLM_ARMS=""
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
VM_PID=""; BOOTED=0

stop_vm() {   # sync first: a panic in QEMU's teardown once lost unflushed files
	local i
	[ -n "$VM_PID" ] || return 0
	sync
	kill -TERM "$VM_PID" 2>/dev/null
	for i in $(seq 1 30); do [ -d "/proc/$VM_PID" ] || break; sleep 0.5; done
	if [ -d "/proc/$VM_PID" ]; then
		kill -KILL "$VM_PID" 2>/dev/null; sleep 1
	fi
	[ -d "/proc/$VM_PID" ] && return 1
	VM_PID=""
	sync
	return 0
}

cleanup() {
	say "cleanup"
	if [ "$BOOTED" = 1 ]; then
		for VM_PID in $(m_pids_of qemu-system-aarch64); do
			stop_vm || echo "WARNING: the guest QEMU $VM_PID would not stop" >&2
		done
	fi
	VM_PID=""
	m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

pin_vm() {   # every QEMU thread on QEMU_CORES, read back per thread
	local t got
	for t in $(ls "/proc/$VM_PID/task"); do
		sudo -n taskset -pc "$QEMU_CORES" "$t" >/dev/null 2>&1 || [ ! -d "/proc/$VM_PID/task/$t" ] \
			|| die "taskset failed on QEMU thread $t"
		got="$(awk '/^Cpus_allowed_list:/ {print $2}' "/proc/$VM_PID/task/$t/status" 2>/dev/null)"
		[ -z "$got" ] || [ "$(_cpuset "$got")" = "$(_cpuset "$QEMU_CORES")" ] \
			|| die "QEMU thread $t reads back '$got', asked for '$QEMU_CORES'"
	done
}

up_check() {   # $1 arm  $2 label: one untimed exchange (handshake included) on that arm's path
	local dest=()
	if [ "$1" = K ]; then
		dest=(--proto shmdb --shm "$IVSHMEM@$SLOT_K" --kick "$KICK_SOCK")
	else
		dest=(--proto shmbell --shm "$IVSHMEM@$SLOT_B")
	fi
	taskset -c "$CORE_PROBE" python3 "$PROBE" "${dest[@]}" --ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB" \
		--n 1 --warmup 0 --interval-ms 0 --timeout-s 3 --tag "check-$2" --out "$OUT/check-$2.json" \
		>> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 label
	local lab="$1" log="$OUT/console-$1.log" i args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	# The last guest's sockets: its server exits with QEMU, and the launcher
	# refuses to start over a socket it finds.
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK"
	BOOTED=1
	IFS_BIN="$IMG_B" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" THREAD_NAMES=1 \
		SMP="$SMP" MEM=1G TAP=tap-qnx MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG_B "*) ;; *) die "boot $lab: QEMU was not given $IMG_B" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$SMP" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $SMP"
	for i in $(seq 1 40); do up_check B "$lab-B" && break; sleep 0.5; done
	up_check B "$lab-B" || die "boot $lab: no monitor answering on the MSI-X path (slot $SLOT_B)"
	up_check K "$lab-K" || die "boot $lab: no monitor answering on the console path (slot $SLOT_K)"
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG_B") smp=$SMP qemu_pid=$VM_PID" >> "$OUT/boots.log"
}

gpu_idle_around() {   # $1 label
	[ "$TEGRA" = 1 ] || return 0
	local lines
	lines="$(grep -E "^$1 (before|after) " "$OUT/thermal.log")"
	[ "$(echo "$lines" | grep -cE 'GR3D_FREQ [0-9]+%')" -eq 2 ] \
		|| die "no GR3D reading before and after $1 -- the no-load premise is unverified"
	! echo "$lines" | grep -qE 'GR3D_FREQ [1-9][0-9]*%' \
		|| die "GR3D above 0% around $1 -- a GPU load ran beside this no-load run"
}

run_arm() {   # $1 arm  $2 round
	local a="$1" r="$2"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	if [ "$a" = K ]; then
		m_probe "$OUT" "K_r$r" "$IVSHMEM@$SLOT_K" "$KICK_SOCK" "" shmdb "$IVSHMEM_SERVER"
	else
		m_probe "$OUT" "B_r$r" "$IVSHMEM@$SLOT_B" "-" "" shmbell "$IVSHMEM_SERVER"
	fi
	m_thermal "r$r $a after" >> "$OUT/thermal.log"
	gpu_idle_around "r$r $a"
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is already running: this harness boots its own guests"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- run scripts/orin/setup-bridge-orin.sh (a reboot drops it)"
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
m_require_balanced_k "$K" "${#MODES[@]}"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_B" "$DISK" "$here/shmchan.c"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_B$DISK$IVSHMEM$IVSHMEM_SERVER$KICK_SOCK" in *" "*|*,*) die "no spaces or commas in the image, disk or socket paths" ;; esac
grep -q 'shmchan_bell_roundtrip' "$here/shmchan.c" || die "$here/shmchan.c has no shmchan_bell_roundtrip"
grep -q '"shmbell"' "$PROBE" || die "$PROBE has no shmbell transport"

m_prepare_out "${OUT:-}" "$HOME/bell-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
: > "$OUT/check.log"
m_build_shmchan "$here/shmchan.c" "$COMMON" "$OUT/libshmchan.so"
m_governor_pin
m_cstate_apply

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "bell"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"slots\": {\"K\": $SLOT_K, \"B\": $SLOT_B}" \
	'"protos": {"K": "shmdb", "B": "shmbell"}' \
	"\"image_sha256\": \"$(_sha "$IMG_B")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"config\": \"ifs-bell.bin, -smp $SMP\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; per boot K and B in a Williams order over them (period 2); see order.log"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${MODES[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one -smp $SMP boot per round, K and B per boot -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/order.log"
for r in $(seq 1 "$K"); do
	arms=()
	for i in $(m_williams_row "$r" "${#MODES[@]}"); do arms+=("${MODES[$i]}"); done
	boot_vm "A_r$r"
	for a in "${arms[@]}"; do run_arm "$a" "$r"; done
	stop_vm || die "the guest of round $r would not stop"
	echo "round $r order: ${arms[*]}" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${MODES[@]}"
say "summary"
m_summary "$OUT" K "${MODES[@]}"
say "the two ways in, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
