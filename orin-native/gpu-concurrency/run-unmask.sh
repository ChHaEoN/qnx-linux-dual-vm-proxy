#!/usr/bin/env bash
# run-unmask.sh -- where the doorbell's LPI is unmasked: before the reply (InterruptUnmask as soon as
# InterruptWait returns, as run-bell.sh's arm B) or after it (the next InterruptWait unmasks it,
# _NTO_INTR_WAIT_FLAGS_UNMASK). Phase 3b / A6, 2026-09-29. The owner asked for it (2026-09-29), as
# the doorbell's third follow-up. SDP 8.0 has no ISR (its migration guide: InterruptAttach() is
# removed), and an InterruptAttachEvent SIGEV_INTR waiter is itself the interrupt's IST, so the
# kernel masks the LPI whenever it fires; what the API leaves open is when it is unmasked.
#
# WHAT IS KNOWN. The MSI-X doorbell into the guest against the console kick: 20260929T-a6-orin-bell
# (held locally). Where each way in traps, register by register: 20260929T-a6-orin-mmio (held
# locally). Every way across in one boot: 20260929T-a6-orin-paths (held locally).
#
# THE INSTRUMENTS.
#   guest  ifs-unmask-a.bin and ifs-unmask-b.bin: ifs-bell.bin with qnx-its-probe-2v ("msixcfg 2":
#          ivshmem's MSI-X vectors 0 and 1 -> LPIs 8193 and 8194) and qnx-safety-monitor-unmask,
#          whose kick "msix[1][:defer]" picks the vector and where the unmask happens. Two MSI-X
#          monitors serve, one per vector: slot 8192 on vector 0, slot 12288 on vector 1.
#          ifs-unmask-a unmasks before the reply on vector 0 and defers it on vector 1;
#          ifs-unmask-b swaps them. Both attach the same way (InterruptAttachEvent, SIGEV_INTR,
#          _NTO_INTR_FLAGS_TRK_MSK) and wait the same way (InterruptWait, no lightweight block).
#     U    the unmask before the reply: InterruptWait returns, InterruptUnmask, then the frame is
#          judged and the doorbell rung back.
#     D    the unmask deferred: InterruptWait returns, the frame is judged and the doorbell rung
#          back, and the next InterruptWait unmasks the LPI before it blocks. Its first wait
#          unmasks nothing (nothing has fired yet); boot_vm's untimed exchange on each vector
#          takes it before any timed one.
#   host   latency_probe.py --proto shmbell through libshmchan.so, as run-bell.sh's B, ringing the
#          vector the image gives the arm (--bell-vector); the launcher's VECTORS=2 gives the
#          doorbell device two vectors and the ivshmem server two eventfds per peer.
#   check  A functional check booted each image once before this was committed and made 20
#          exchanges on each vector; the probe's output went to files that were not read, and
#          only the monitors' banners and the probe's counts (answered, bad, notifications) were
#          printed.
#
# THE ARMS: U and D, both in every boot. Rounds boot ifs-unmask-a, a, b, b, a, a, b, b, ...; U
# and D alternate order within each pair of rounds, so each image-and-order pairing comes once in
# every four rounds and the vector is balanced against where the unmask happens. n=1000 after 200
# warm-up at 2 ms, K=16 rounds, one boot per round, -smp 2. QEMU pinned to cores 0-2, the probe
# to core 4, the governor pinned, c7 off, no load. KVM's exit counters around every arm. The
# preflight boots both images. About 12 min.
#
# THE RULE, fixed here before any run (unmask_report.py applies it). Per arm and round the probe's
# p50 and p99, and KVM's exit counters over the arm divided by its exchanges (warm-up included).
# Every difference is D - U, paired within the round; per difference, the median over rounds with
# the distribution-free interval of widest coverage >= 95% (d(4)..d(13), 97.9%, at K = 16).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended. The thresholds were set knowing the records named above; what is blind is this
# paired comparison.
#   H1 the unmask -- a kernel call and the startup library's LPI callout, which reads and writes
#      GITS_CWRITER -- costs the reply its own time when it comes before it; deferred, it does not.
#   P1 median DIFF(p50) D - U <= -2.0 us with the interval's upper end below 0: HELD. The upper end
#      below 0 alone: PARTIAL. Otherwise REFUTED. (HELD asks for the interval too, unlike
#      run-bell.sh's rule: the threshold here is small against a round's noise.)
#   H2 the unmask is moved, not removed: D elides no ITS command and changes no other trapped
#      access (mmio_exit_kernel counts every kernel-handled access, not only the ITS's).
#   P2 |median DIFF(mmio_exit_kernel per exchange) D - U| <= 0.5: HELD. Otherwise REFUTED.
# Not predicted, reported: DIFF at p90, p99 and p99.9; DIFF(p50) within each image (the way's
# effect plus or minus the vector's) and half their difference (the vector's own effect); the
# other KVM counters' differences.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, shmbell on the vector and the
#      slot the round's image gives it, the probe on its core (the report)
#   M2 in every arm-round one doorbell per exchange: the probe's own counts show exchanges ==
#      notifications == warm-up + n, no early wake-up and no stray byte
#   M3 every boot's console maps both vectors (EventID 0 -> LPI 8193, EventID 1 -> LPI 8194) and
#      shows both MSI-X monitors serving with the waits the round's image gives them, and the
#      monitor on the slot each arm used unmasks as that arm says (deferred for D only)
#   M4 KVM's counters were read before and after every arm (P2 only)
#   P1 rests on M1-M3; P2 on M1-M4.
#   M5 (a qualifier, not a gate) |median DIFF(halt_wakeup per exchange) D - U| <= 0.3: if it fails,
#      P1 and P2 print with "H1 not supported: the ways differ in wake-ups".
#
# What this does NOT test: which of the unmask's parts (the kernel call, the callout's trapped
# GITS_CWRITER accesses) carries any difference; a cost the deferred unmask may add to the NEXT
# exchange (at 2 ms spacing it is long done); the lightweight block or InterruptAttachThread (SDP
# 8.0's other IST forms); rates other than 2 ms; the console way in; a1.metal (scripts/aws's
# harness phase gives a harness one IMAGE=, this one boots two, and run-unmask.sh is not in its
# list); a real ITS; QNX's supported MSI path. The startup is ours: not a QNX-supported
# configuration.
#
# NEEDS: no QEMU running; IMG_UA and IMG_UB (ifs-unmask-a.bin, ifs-unmask-b.bin), DISK; tap-qnx
# on br0; gcc (libshmchan.so is built here). CSTATE=shallow (set before the library). No load. K a
# multiple of 4.
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
REPORT="${REPORT:-$here/unmask_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
IMG_UA="${IMG_UA:-$HOME/output/ifs-unmask-a.bin}"
IMG_UB="${IMG_UB:-$HOME/output/ifs-unmask-b.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(U D)
ARM_PROTOS="U=shmbell D=shmbell"
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
VM_PID=""; BOOTED=0; IMG=""

# Which image a round boots, and where each arm sits in it: ifs-unmask-a unmasks before the
# reply (U) on vector 0 at slot 8192 and defers it (D) on vector 1 at slot 12288; ifs-unmask-b
# swaps them. Rounds go a a b b a a b b ..., and U/D alternate within each pair, so every image
# and order pairing comes once in every four rounds.
image_of() {   # $1 round -> a|b
	if [ $(( (($1 - 1) / 2) % 2 )) = 0 ]; then echo a; else echo b; fi
}
vector_of() {   # $1 image  $2 arm -> 0|1
	case "$1$2" in aU|bD) echo 0 ;; *) echo 1 ;; esac
}
slot_of() {   # $1 vector -> the slot's offset
	if [ "$1" = 0 ]; then echo 8192; else echo 12288; fi
}

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

up_check() {   # $1 vector  $2 label: one untimed exchange (handshake included) on that vector's slot
	taskset -c "$CORE_PROBE" python3 "$PROBE" --proto shmbell --shm "$IVSHMEM@$(slot_of "$1")" --bell-vector "$1" \
		--ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB" \
		--n 1 --warmup 0 --interval-ms 0 --timeout-s 3 --tag "check-$2" --out "$OUT/check-$2.json" \
		>> "$OUT/check.log" 2>&1
}

boot_vm() {   # $1 label  $2 image (a|b)
	local lab="$1" log="$OUT/console-$1.log" i args t cm nv=0
	IMG="$IMG_UA"; [ "$2" = b ] && IMG="$IMG_UB"
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	# The last guest's sockets: its server exits with QEMU, and the launcher
	# refuses to start over a socket it finds.
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK"
	BOOTED=1
	IFS_BIN="$IMG" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" VECTORS=2 \
		IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" THREAD_NAMES=1 \
		SMP="$SMP" MEM=1G TAP=tap-qnx MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG "*) ;; *) die "boot $lab: QEMU was not given $IMG" ;; esac
	case "$args" in *"ivshmem-doorbell,chardev=ivsh0,vectors=2"*) ;; *) die "boot $lab: the doorbell device has not 2 vectors" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$SMP" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $SMP"
	for i in $(seq 1 40); do up_check 0 "$lab-v0" && break; sleep 0.5; done
	up_check 0 "$lab-v0" || die "boot $lab: no monitor answering on vector 0 (slot 8192)"
	up_check 1 "$lab-v1" || die "boot $lab: no monitor answering on vector 1 (slot 12288)"
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG") smp=$SMP qemu_pid=$VM_PID" >> "$OUT/boots.log"
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

run_arm() {   # $1 arm (U|D)  $2 round  $3 image
	local a="$1" r="$2" v
	v="$(vector_of "$3" "$a")"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	PROBE_BELL_VECTOR="$v" m_probe "$OUT" "${a}_r$r" "$IVSHMEM@$(slot_of "$v")" "-" "" shmbell "$IVSHMEM_SERVER"
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
[ $(( K % 4 )) = 0 ] || die "K=$K is not a multiple of 4: images and orders would not balance"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_UA" "$IMG_UB" "$DISK" "$here/shmchan.c" "$COMMON/ivshm_client.c"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_UA$IMG_UB$DISK$IVSHMEM$IVSHMEM_SERVER$KICK_SOCK" in *" "*|*,*) die "no spaces or commas in the image, disk or socket paths" ;; esac
grep -q 'shmchan_ivshm_peer_efd_vec' "$here/shmchan.c" || die "$here/shmchan.c has no shmchan_ivshm_peer_efd_vec"
grep -q -- '--bell-vector' "$PROBE" || die "$PROBE has no --bell-vector"
grep -q 'PROBE_BELL_VECTOR' "$LIB" || die "$LIB passes no PROBE_BELL_VECTOR"
grep -q 'VECTORS' "$LAUNCH" || die "$LAUNCH has no VECTORS"

m_prepare_out "${OUT:-}" "$HOME/unmask-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
: > "$OUT/check.log"
m_build_shmchan "$here/shmchan.c" "$COMMON" "$OUT/libshmchan.so"
m_governor_pin
m_cstate_apply

# Both images boot in the preflight, so a broken one stops the run before any timed round.
boot_vm preflight-b b
stop_vm || die "the preflight guest (image b) would not stop"
boot_vm preflight-a a
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "unmask"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"slots": {"vector 0": 8192, "vector 1": 12288}' \
	'"images": {"a": {"U": 0, "D": 1}, "b": {"U": 1, "D": 0}}' \
	'"protos": {"U": "shmbell", "D": "shmbell"}' \
	"\"image_sha256\": {\"a\": \"$(_sha "$IMG_UA")\", \"b\": \"$(_sha "$IMG_UB")\"}" \
	"\"ivshm_client_sha256\": \"$(_sha "$COMMON/ivshm_client.c")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"config\": \"ifs-unmask-a.bin / ifs-unmask-b.bin, -smp $SMP, VECTORS=2\"" \
	"\"smp\": $SMP" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(m_wifi_state)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; images a a b b ...; U and D alternating within each pair of rounds; both images in the preflight; see order.log"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${MODES[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one -smp $SMP boot per round, U and D per boot -> $OUT"
: > "$OUT/thermal.log"
: > "$OUT/order.log"
for r in $(seq 1 "$K"); do
	im="$(image_of "$r")"
	if [ $(( r % 2 )) = 1 ]; then arms=(U D); else arms=(D U); fi
	boot_vm "A_r$r" "$im"
	for a in "${arms[@]}"; do run_arm "$a" "$r" "$im"; done
	stop_vm || die "the guest of round $r would not stop"
	echo "round $r image $im order: ${arms[*]}" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${MODES[@]}"
say "summary"
m_summary "$OUT" U "${MODES[@]}"
say "where the unmask happens, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
