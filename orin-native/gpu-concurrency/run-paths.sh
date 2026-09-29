#!/usr/bin/env bash
# run-paths.sh -- every way across the partition, in one run: TCP, UDP, SOME/IP over TCP, polled
# shared memory, and notified shared memory with the console kick and with the MSI-X doorbell into
# the guest. Phase 3b / A6, 2026-09-29. The owner asked for it (2026-09-29).
#
# WHAT IS KNOWN. The socket rungs, polled and console-kicked shared memory:
# 20260922T-a6-orin-kick and 20260922T-a6-orin-shm (held locally). What the console costs the
# guest's side: 20260922T-a6-orin-shift (held locally). The SOME/IP header over the plain socket:
# 20260927T-a6-orin-someip (held locally). The doorbell into the guest, one functional unpinned
# run: 20260929T-a6-orin-its (held locally). The MSI-X doorbell against the console kick, on this
# board and on a1.metal: 20260929T-a6-orin-bell and 20260929T-a6-a1metal-bell (held locally). The
# doorbell has never been in the same run as the socket paths.
#
# THE INSTRUMENTS.
#   guest  ifs-paths.bin: ifs-bell.bin plus qnx-someip-monitor (the binary ifs-someip.bin embeds)
#          on TCP+UDP 30509. Every arm is judged by the same judge_frame: the monitor on :7100
#          (T) and :7101 (U), the SOME/IP monitor (S), the polled shm monitor at slot 0 (P), the
#          console-kicked one at slot 4096 (K) and the MSI-X one at slot 8192 (B). One guest
#          serves all six, so every arm runs beside the other five's idle services.
#   host   latency_probe.py for every arm, one 64-byte claim, but NOT one client: T, U and S time
#          Python socket calls (sendall/recv), while P, K and B time one ctypes call into
#          libshmchan.so, which makes the whole round trip in C. So B - T and B - U carry that
#          client difference as well as the path's; S - T, P - B and B - K compare like client
#          code. S is SOME/IP's wire format only: the probe's own 16-byte header (run-someip.sh's
#          ST), no vsomeip, no SD. P: libshmchan.so spins for the reply. K: a kick byte down the
#          console, the reply by doorbell. B: a write to the guest's eventfd, the reply by doorbell.
#
# THE ARMS: T U S P K B, all in every boot, in a Williams order over the six (period 6). n=1000
# after 200 warm-up at 2 ms, K=18 rounds, one boot per round, -smp 2. QEMU pinned to cores 0-2,
# the probe to core 4, the governor pinned, c7 off, no load, no confinement: run-bell.sh's
# pinning, governor, c-state and load conditions, so K and B repeat run-bell.sh's comparison under
# two differences, the image's added SOME/IP monitor and the six-arm order. KVM's counters and
# the vCPU threads' run times around every arm. About 25 min on the Orin, about 15 on a1.metal.
#
# WHY S: OD12 named SOME/IP among the IPC paths; this ladder puts every path already built into
# one run. UDP SOME/IP is left out to keep the arms at six (it is in the someip record's design).
#
# THE RULE, fixed here before any run (paths_report.py applies it). Per arm and round the probe's
# p50 and p99; per arm and round, from KVM's snapshots, the guest vCPU threads' run time and
# KVM's exits over the arm divided by its exchanges (warm-up included), and the vCPUs' busy share
# of the snapshot window. Those columns cover the whole window between the snapshots (the probe's
# start, connect or handshake, and teardown included), and P's window can hold part of the polled
# monitor's spin after its last request. Every difference is paired within the round; per
# difference, the median over rounds with the distribution-free interval of widest coverage
# >= 95%: d(5)..d(14), 96.9%, at K = 18. The rule is fixed at K = 18: the harness refuses any
# other K unless SMOKE=1, and the report prints every prediction UNSCORED under SMOKE=1 or at any
# other K.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended. The thresholds were set knowing the records named above; what is blind is this
# run's paired comparison.
#   H1 as this probe sees them, the doorbell is faster than both socket paths: interrupts both
#      ways, no socket, and the round trip in one C call (see THE INSTRUMENTS).
#   P1 median DIFF(p50) B - T <= -80 us AND B - U <= -60 us: HELD. Both medians below 0 with the
#      intervals' upper ends below 0: PARTIAL. Otherwise REFUTED.
#   H2 polling is faster still, and pays for it in a spinning guest vCPU. At 2 ms spacing the
#      polled monitor spins throughout, so P's vCPU time per exchange is set by the spacing, not
#      by the exchange.
#   P2 median DIFF(p50) P - B <= -15 us: HELD. Below 0 with the interval's upper end below 0:
#      PARTIAL. Otherwise REFUTED. (The vCPU columns are reported beside it, unscored.)
#   H3 the SOME/IP header costs next to nothing on the TCP path (run-someip.sh's H1, re-tested
#      for TCP only). S - T is the header's bytes plus qnx-someip-monitor's own serving code
#      against the TCP monitor's.
#   P3 |median DIFF(p50) S - T| <= 3 us with the interval inside [-3, +3] us: HELD. The median
#      alone inside: PARTIAL. Otherwise REFUTED. (3 us is run-someip.sh's band; the interval
#      condition is new here.)
#   H4 the console is most of the inbound cost (run-bell.sh's H1), re-tested in a boot that also
#      carries the four other paths.
#   P4 median DIFF(p50) B - K <= -40 us: HELD. Below 0 with the interval's upper end below 0:
#      PARTIAL. Otherwise REFUTED.
# Not predicted, reported: every arm's p50/p90/p99/p99.9, U - T, the p99 differences, and per arm
# the guest vCPU run time and KVM's exits per exchange and the vCPUs' busy share.
#
# THE CHECKS (none counts an outcome a prediction is about). A prediction prints VOID when a
# check it rests on fails, and only then:
#   M1 every arm has one round for each of 1..K, each of n samples after the stamp's warm-up,
#      none rejected, none bad, its own transport, the probe on its core (the gate, and the report
#      again). Per arm; a missing round voids every prediction.
#   M2 in the notified arms (K, B), exactly one doorbell per exchange: the probe's own counts show
#      exchanges == notifications == wakeups == warm-up + n, no early wake-up, no stray byte and
#      no EAGAIN. Per arm.
#   M3 every boot's guest console shows msixcfg done and both notified monitors serving, one on
#      /dev/vcon2 and one on "kick msix (LPI 8193)" (run-bell.sh's M3). Per line. S and P prove
#      themselves by M1 (and boot_vm's one exchange per arm per boot), not by a banner.
#   M4 KVM's counters, and the run times of all -smp vCPU threads, were read before and after
#      every arm (the unscored columns only).
#   P1 rests on M1 (T, U, B), M2 (B), M3 (msixcfg, msix). P2 on M1 (P, B), M2 (B), M3 (msixcfg,
#   msix). P3 on M1 (S, T). P4 on M1 (K, B), M2 (K, B), M3 (all three lines).
#
# A STALL (no reply within the probe's timeout) or a path that does not answer at a boot ends the
# run with no verdict (STALL_POLICY=refuse, as on every ladder). It is reported with its arm and
# round, and the run is repeated once. If the repeat ends the same way on the same arm, that
# arm's predictions are REFUTED where the arm is the side predicted faster or equal (B: P1, P4;
# P: P2; S or T: P3) and UNSCORED otherwise.
#
# ON AWS a1.metal (scripts/aws's harness phase) the same rule and thresholds apply, as a
# replication on another host.
#
# What this does NOT test: vsomeip (see the someip records), UDP SOME/IP, more than one vector,
# the reply direction apart from K and B's shared doorbell, rates other than 2 ms (a separate
# run), each arm in a guest of its own, what a compiled socket client would see, the tail beyond
# p99, and anything about the QNX-supported MSI path. The startup is ours: not a QNX-supported
# configuration.
#
# NEEDS: no QEMU running; IMG_P (ifs-paths.bin; IFS_BIN is taken as well, for scripts/aws), DISK;
# tap-qnx on br0; gcc (libshmchan.so is built here). CSTATE=shallow (set before the library). No
# load. K = 18 (SMOKE=1: any multiple of 6, unscored).
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
N="${N:-1000}"
K="${K:-18}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/paths_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
IMG_P="${IMG_P:-${IFS_BIN:-$HOME/output/ifs-paths.bin}}"
DISK="${DISK:-$HOME/output/disk-qemu}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
SLOT_K=4096
SLOT_B=8192
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(T U S P K B)
ARM_PROTOS="T=tcp U=udp S=someip P=shm K=shmdb B=shmbell"
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

up_check() {   # $1 arm  $2 label: one untimed exchange on that arm's path
	local dest=()
	case "$1" in
		T) dest=(--proto tcp --host "$GUEST" --port 7100) ;;
		U) dest=(--proto udp --host "$GUEST" --port 7101) ;;
		S) dest=(--proto someip --host "$GUEST" --port 30509) ;;
		P) dest=(--proto shm --shm "$IVSHMEM" --shm-lib "$SHMCHAN_LIB") ;;
		K) dest=(--proto shmdb --shm "$IVSHMEM@$SLOT_K" --kick "$KICK_SOCK" --ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB") ;;
		B) dest=(--proto shmbell --shm "$IVSHMEM@$SLOT_B" --ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB") ;;
	esac
	taskset -c "$CORE_PROBE" python3 "$PROBE" "${dest[@]}" \
		--n 1 --warmup 0 --interval-ms 0 --timeout-s 3 --tag "check-$2" --out "$OUT/check-$2.json" \
		>> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 label
	local lab="$1" log="$OUT/console-$1.log" i a args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	# The last guest's sockets: its server exits with QEMU, and the launcher
	# refuses to start over a socket it finds.
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK"
	BOOTED=1
	IFS_BIN="$IMG_P" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" THREAD_NAMES=1 \
		SMP="$SMP" MEM=1G TAP=tap-qnx MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG_P "*) ;; *) die "boot $lab: QEMU was not given $IMG_P" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$SMP" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $SMP"
	for i in $(seq 1 40); do up_check B "$lab-B" && break; sleep 0.5; done
	for a in "${MODES[@]}"; do
		up_check "$a" "$lab-$a" || die "boot $lab: arm $a's path does not answer"
	done
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG_P") smp=$SMP qemu_pid=$VM_PID" >> "$OUT/boots.log"
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
	case "$a" in
		T) m_probe "$OUT" "T_r$r" "$GUEST" 7100 "" tcp ;;
		U) m_probe "$OUT" "U_r$r" "$GUEST" 7101 "" udp ;;
		S) m_probe "$OUT" "S_r$r" "$GUEST" 30509 "" someip ;;
		P) m_probe "$OUT" "P_r$r" "$IVSHMEM" "-" "" shm ;;
		K) m_probe "$OUT" "K_r$r" "$IVSHMEM@$SLOT_K" "$KICK_SOCK" "" shmdb "$IVSHMEM_SERVER" ;;
		B) m_probe "$OUT" "B_r$r" "$IVSHMEM@$SLOT_B" "-" "" shmbell "$IVSHMEM_SERVER" ;;
	esac
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
SMOKE="${SMOKE:-0}"
case "$SMOKE" in 0|1) ;; *) die "SMOKE='$SMOKE' is not 0 or 1" ;; esac
[ "$K" = 18 ] || [ "$SMOKE" = 1 ] || die "K=$K: the rule is fixed at K = 18 (SMOKE=1 runs another multiple of 6, unscored)"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_P" "$DISK" "$here/shmchan.c"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_P$DISK$IVSHMEM$IVSHMEM_SERVER$KICK_SOCK" in *" "*|*,*) die "no spaces or commas in the image, disk or socket paths" ;; esac
grep -q 'shmchan_bell_roundtrip' "$here/shmchan.c" || die "$here/shmchan.c has no shmchan_bell_roundtrip"
grep -q '"shmbell"' "$PROBE" || die "$PROBE has no shmbell transport"

m_prepare_out "${OUT:-}" "$HOME/paths-out"
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
	'"experiment": "paths"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"slots\": {\"P\": 0, \"K\": $SLOT_K, \"B\": $SLOT_B}" \
	'"protos": {"T": "tcp", "U": "udp", "S": "someip", "P": "shm", "K": "shmdb", "B": "shmbell"}' \
	'"ports": {"T": 7100, "U": 7101, "S": 30509}' \
	"\"image_sha256\": \"$(_sha "$IMG_P")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"config\": \"ifs-paths.bin, -smp $SMP\"" \
	"\"smp\": $SMP" \
	"\"smoke\": $SMOKE" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; per boot the six arms in a Williams order over them (period 6); see order.log"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${MODES[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one -smp $SMP boot per round, six arms per boot -> $OUT"
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
m_summary "$OUT" T "${MODES[@]}"
say "every way across, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
