#!/usr/bin/env bash
# run-bellrate.sh -- the MSI-X doorbell against the console kick at a fast spacing and with
# exponential arrivals, beside the 2 ms spacing run-bell.sh used: does halt polling take part of the
# difference? Phase 3b / A6, 2026-09-29. The owner asked for it (2026-09-29), as the doorbell's
# fourth follow-up.
#
# WHAT IS KNOWN. The two ways in at run-bell.sh's spacing: 20260929T-a6-orin-bell, and on a1.metal
# 20260929T-a6-a1metal-bell. Where each traps: 20260929T-a6-orin-mmio. Every way across in one
# boot: 20260929T-a6-orin-paths. Where the doorbell's LPI is unmasked: 20260929T-a6-orin-unmask.
# The spacing sweep, halt polling and the arrival test on the TCP rung: 20260924T-a6-orin-rate,
# 20260924T-a6-orin-haltpoll, 20260924T-a6-orin-arrival. A blocked vCPU's wake:
# 20260924T-a6-orin-blockpath. All held locally, and all known when the thresholds were set.
#
# THE INSTRUMENTS. As run-bell.sh: ifs-bell.bin, shmkick on the virtio console at slot 4096 (K)
# and on the MSI-X LPI at slot 8192 (B, which unmasks its LPI before the reply, as run-bell.sh's B),
# both replying through the ivshmem Doorbell; latency_probe.py through libshmchan.so, --proto shmdb
# (K) and shmbell (B). KVM applies an ITS command inside the guest's GITS_CWRITER write (Linux
# 5.15, arch/arm64/kvm/vgic/vgic-its.c: vgic_mmio_write_its_cwriter calls
# vgic_its_process_commands), so no ITS work is left queued between exchanges at any rate on this
# kernel. KVM counts halt_wakeup only when it wakes a vCPU that was sleeping in a halt, never after
# a successful poll (Linux 5.15, virt/kvm/kvm_main.c, kvm_vcpu_wake_up). halt_poll_ns must read
# 500000 (the harness refuses otherwise), and it and its grow, grow_start and shrink are stamped.
#
# THE ARMS, six in every boot, in a Williams order over the six (period 6):
#   K2 B2   2 ms constant spacing after each reply, as run-bell.sh
#   Kf Bf   0.2 ms constant spacing: the vCPU's idle gap should then be under halt_poll_ns, so
#           KVM's halt polling can end a halt without a sleep (the mechanism run-rate.sh and
#           run-haltpoll.sh test); M5 checks that it did
#   Ke Be   exponential spacing with a 2 ms mean (PROBE_ARRIVAL=exp), the same seed for both arms
#           in a round, so the two see the same sleeps. About 22% of such sleeps are under 0.5 ms
#           (1 - e^-0.25), so these arms carry some polling too; the median sleep is about 1.4 ms.
# n=1000 after 200 warm-up, K=12 rounds, one boot per round, -smp 2. QEMU pinned to cores 0-2, the
# probe to core 4, the governor pinned, c7 off, no load. KVM's exit and halt-poll counters around
# every arm. A poll window an f arm grows is reset by the first idle span over halt_poll_ns in the
# seconds between arms (a shrink of 0, stamped), and the next arm's warm-up regrows it. About 20
# min.
#
# THE RULE, fixed here before any run (bellrate_report.py applies it). Per arm and round the probe's
# p50 and p99, and KVM's counters over the arm divided by its exchanges (warm-up included). For a
# spacing x, S(x) = B - K at p50 and W(x) = halt_wakeup per exchange of K minus that of B, both
# paired within the round; every difference below is of these, paired within the round; per
# difference, the median over rounds with the distribution-free interval of widest coverage >= 95%
# (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended. The thresholds were set knowing the records named above; what is blind is these
# paired comparisons.
#   H1 if the two ways in differ in how often an exchange ends a vCPU's sleeping halt, that part of
#      S depends on how halts end: where halt polling ends them without a sleep, it goes.
#   P1 median of S(0.2 ms) - S(2 ms) >= +3.0 us with the interval's lower end above 0: HELD. The
#      lower end above 0 alone: PARTIAL. The median above 0 with the lower end not above 0:
#      UNRESOLVED. Otherwise REFUTED.
#   P3 (H1's signature, from KVM's counters, which see no time) median of W(2 ms) - W(0.2 ms) > 0
#      with the interval's lower end above 0: HELD. Otherwise REFUTED.
#   H2 at the same mean rate, how regular the arrivals are changes S by little. Not independent of
#      H1: the exponential arms' short sleeps are partly polled.
#   P2 median of S(exp) - S(2 ms) within +-5.0 us with the whole interval within it: HELD. The
#      median alone within it: PARTIAL. Otherwise REFUTED.
# Not predicted, reported: S and W at each spacing, every arm's p50/p90/p99/p99.9, S at p99, and per
# arm the idle gap (the achieved period minus the p50 round trip) and KVM's halt_wakeup,
# halt_attempted_poll, halt_successful_poll and exits per exchange.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own transport, the probe
#      on its core (the gate checks these; the report again), and its spacing and arrival kind, and
#      for Ke and Be draws == warm-up + n, a mean sleep within 10% of 2 ms and sd/mean 0.8-1.2 (the
#      report only)
#   M2 in every arm-round one doorbell per exchange: the probe's own counts show exchanges ==
#      notifications == wakeups == warm-up + n, no early wake-up, no stray byte and no EAGAIN
#   M3 every boot's guest console shows msixcfg done and both notified monitors serving, one on
#      /dev/vcon2 and one on "kick msix (LPI 8193)" (run-bell.sh's M3)
#   M4 KVM's counters were read before and after every arm
#   P1 and P2 rest on M1-M3; P3 on M1-M4.
#   M5 (a qualifier, not a gate; it rests on M4) H1's premise: for each way X, the median of
#      [halt_successful_poll per exchange at 0.2 ms - at 2 ms] >= 0.5, and Kf's and Bf's median
#      idle gap under 450 us. Failed: P1 prints with "H1's premise not met"; not evaluable: with
#      "H1's premise not evaluated".
#   M6 (a qualifier) P1 reads a rise of S as a shrink of the difference only if S(2 ms) < 0: if the
#      S(2 ms) interval's upper end is not below 0, P1 prints with "S(2 ms) not below 0".
#
# What this does NOT test: that halt polling causes any change in S (the spacing changes and the
# polling with it -- co-variation, as run-haltpoll.sh says; halt_poll_ns is not varied here); spacings
# between 0.2 and 2 ms; other arrival shapes; the unmask deferred (B here unmasks before the reply);
# the tail beyond p99; everything run-bell.sh does not test (one vector and one device, no real ITS,
# QNX's supported MSI path, the reply direction). a1.metal (scripts/aws's harness phase lists this
# harness): a run there is a replication on another kernel, whose vgic-its.c and halt-poll defaults
# were not read for this header (the stamp records its halt-poll parameters). The startup is ours:
# not a QNX-supported configuration.
#
# NEEDS: no QEMU running; IMG_B (ifs-bell.bin), DISK; tap-qnx on br0; gcc (libshmchan.so is built
# here); halt_poll_ns at 500000. CSTATE=shallow (set before the library). No load. K a multiple of
# 6.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/bellrate_report.py}"
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
MODES=(K2 B2 Kf Bf Ke Be)
ARM_PROTOS="K2=shmdb B2=shmbell Kf=shmdb Bf=shmbell Ke=shmdb Be=shmbell"
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
	[ "$(cat /sys/module/kvm/parameters/halt_poll_ns 2>/dev/null)" = 500000 ] \
		|| die "boot $lab: halt_poll_ns is not 500000 (KVM copies it into the VM it creates)"
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

run_arm() {   # $1 arm  $2 round: the way in from the first letter, the spacing from the second
	local a="$1" r="$2" iv=2 arr="" seed=""
	case "$a" in
		?2) ;;
		?f) iv=0.2 ;;
		?e) arr=exp; seed="$((r * 10))" ;;   # Ke and Be of a round see the same sleeps
		*) die "no such arm: $a" ;;
	esac
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	case "$a" in
		K?) INTERVAL_MS="$iv" PROBE_ARRIVAL="$arr" PROBE_SEED="$seed" \
			m_probe "$OUT" "${a}_r$r" "$IVSHMEM@$SLOT_K" "$KICK_SOCK" "" shmdb "$IVSHMEM_SERVER" ;;
		B?) INTERVAL_MS="$iv" PROBE_ARRIVAL="$arr" PROBE_SEED="$seed" \
			m_probe "$OUT" "${a}_r$r" "$IVSHMEM@$SLOT_B" "-" "" shmbell "$IVSHMEM_SERVER" ;;
		*) die "no way in for $a" ;;
	esac
	# fail fast on a wrong spacing or arrival kind (the report checks them again, M1)
	python3 - "$OUT/lat-${a}_r$r.json" "$iv" "${arr:-const}" <<'PY' || die "$a r$r: the probe ran the wrong spacing or arrival"
import json, sys
s = json.load(open(sys.argv[1]))["summary"]
kind = (s.get("arrival") or {}).get("kind", "const")
sys.exit(0 if abs(float(s["interval_ms"]) - float(sys.argv[2])) < 1e-9 and kind == sys.argv[3] else 1)
PY
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
[ "$(cat /sys/module/kvm/parameters/halt_poll_ns 2>/dev/null)" = 500000 ] \
	|| die "halt_poll_ns is not 500000 -- a killed run-haltpoll.sh may have left it; the header names the default"
HALT_POLL=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALT_POLL="$HALT_POLL\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo unread)\", "
done
HALT_POLL="{${HALT_POLL%, }}"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_B" "$DISK" "$here/shmchan.c"; do [ -r "$f" ] || die "missing: $f"; done
case "$IMG_B$DISK$IVSHMEM$IVSHMEM_SERVER$KICK_SOCK" in *" "*|*,*) die "no spaces or commas in the image, disk or socket paths" ;; esac
grep -q 'shmchan_bell_roundtrip' "$here/shmchan.c" || die "$here/shmchan.c has no shmchan_bell_roundtrip"
grep -q '"shmbell"' "$PROBE" || die "$PROBE has no shmbell transport"

m_prepare_out "${OUT:-}" "$HOME/bellrate-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
: > "$OUT/check.log"
m_build_shmchan "$here/shmchan.c" "$COMMON" "$OUT/libshmchan.so"
m_governor_pin
m_cstate_apply

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS='"per arm: see spacings"' m_write_stamp "$OUT/stamp.json" \
	'"experiment": "bellrate"' \
	'"seeds": "Ke and Be of round r both PROBE_SEED = 10 r; the constant arms none"' \
	"\"kvm_halt_poll\": $HALT_POLL" \
	'"spacings": {"K2": "2 ms", "B2": "2 ms", "Kf": "0.2 ms", "Bf": "0.2 ms", "Ke": "exp, mean 2 ms", "Be": "exp, mean 2 ms"}' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"slots\": {\"K\": $SLOT_K, \"B\": $SLOT_B}" \
	'"protos": {"K2": "shmdb", "B2": "shmbell", "Kf": "shmdb", "Bf": "shmbell", "Ke": "shmdb", "Be": "shmbell"}' \
	"\"image_sha256\": \"$(_sha "$IMG_B")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"config\": \"ifs-bell.bin, -smp $SMP\"" \
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
m_summary "$OUT" K2 "${MODES[@]}"
say "the two ways in at three spacings, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
