#!/usr/bin/env bash
# run-someip.sh -- the SOME/IP arm (OD12): what the SOME/IP wire format, and vsomeip on the Linux
# side, add to a claim's round trip across the partition. Phase 3b / A6, 2026-09-27.
# The owner asked for this run (2026-09-27: "把read收尾然後做some/ip").
#
# WHAT IS KNOWN. The monitor's claim round trip across the partition, TCP and UDP, 2 ms spacing,
# at p50 on this board: the ladder records, 20260923T-a6-orin-stamp and 20260927T-a6-orin-free
# (held locally). OD12 proposed a SOME/IP arm through vsomeip; nothing SOME/IP has run here
# before.
#
# THE INSTRUMENTS.
#   guest  ifs-someip.bin: ifs-stamp.bin plus qnx-someip-monitor on TCP and UDP 30509
#          (ipc-test/qnx-someip/someip.c): method 0x0001 of service 0x5AFE, the monitor's own
#          judgement (it #includes monitor.c), served with the monitor's call pattern: one
#          blocking read per TCP message, one recvfrom per datagram. The TCP and UDP monitors
#          on :7100 and :7101 are unchanged.
#   host   latency_probe.py for every arm. T, U: the 64-byte frame as always. ST, SU: the same
#          frame in a SOME/IP request, the header built by the probe outside the timed span.
#          CT, CU and VT, VU: someip_vprobe (orin-native/someip, C++), which the probe runs:
#          CT, CU with a plain socket and the header by hand, VT, VU through vsomeip 3.4.10
#          (MPL-2.0, built by build-vsomeip.sh, service discovery disabled, the service
#          configured statically; the application hosts vsomeip's routing itself). The two
#          C++ modes share every line but the transport, so VT - CT is vsomeip's own cost.
#
# THE ARMS (all to the same guest, one boot per round, a Williams order over the eight):
#   T  tcp       :7100    U  udp       :7101
#   ST someip    :30509   SU someipu   :30509   (Python, SOME/IP header by hand)
#   CT csomeip   :30509   CU csomeipu  :30509   (C++, SOME/IP header by hand)
#   VT vsomeip   :30509   VU vsomeipu  :30509   (C++, vsomeip; a TCP-only and a UDP-only config)
# n=1000 after 200 warm-up at 2 ms, K=16, -smp 2. QEMU pinned to cores 0-2, every client to
# core 4 (vsomeip's own threads too: they inherit it), the governor pinned, c7 off, no load.
# About 15 min.
#
# THE RULE, fixed here before any run (someip_report.py applies it). Per arm and round the
# probe's p50. Differences are paired within the round; per difference, the median over rounds
# with the distribution-free interval of widest coverage >= 95% (d(4)..d(13), 97.9%, at K = 16).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. A feasibility check came first -- one boot, five exchanges per
# transport -- and only its exit codes, error lines and the guest's per-connection counts were
# read; no timing.
#   H1 the SOME/IP header costs next to nothing on this path: the same socket calls at both
#      ends, 16 more bytes each way.
#   P1 ST - T and SU - U are each within 3 us of 0.
#   H2 vsomeip's own machinery on the Linux side adds a cost, which is small against the
#      partition boundary.
#   P2 VT - CT >= +10 us and VU - CU >= +10 us.
#   P3 VT - CT <= 0.25 x the median of CT's p50, and VU - CU <= 0.25 x the median of CU's p50.
# Not predicted, reported: CT - ST and CU - SU (the C++ client against the Python one), VT - VU,
# and every arm's p99.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own transport, and
#      the client on the probe core (the gate, and the report again)
#   M2 VT's and VU's files name vsomeip 3.4.10; CT's and CU's name none
#   M3 every boot's guest console has one "someip: tcp client done (eof)" line with
#      seen = n + warm-up, rejected = 0 and errors = 0 for each of ST, CT and VT
#
# What this does NOT test: SOME/IP service discovery, events, serialisation, E2E or TP; vsomeip
# on the QNX side (the guest's server is this project's minimal one); CommonAPI; another vsomeip
# version or configuration; vsomeip's threads on cores of their own; the tail beyond p99.
#
# NEEDS: no QEMU running; IMG (ifs-someip.bin), DISK, VPROBE (someip_vprobe, built by
# orin-native/someip/build-vsomeip.sh). CSTATE=shallow (set before the library). No load.
# K a multiple of 8.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

GUEST="${GUEST:-192.168.100.10}"
HOST_IP="${HOST_IP:-192.168.100.1}"
N="${N:-1000}"
K="${K:-16}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/someip_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IMG_S="${IMG_S:-$HOME/output/ifs-someip.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
VPROBE="${VPROBE:-$HOME/vsomeip/3.4.10/bin/someip_vprobe}"
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(T U ST SU CT CU VT VU)
declare -A PORT=([T]=7100 [U]=7101 [ST]=30509 [SU]=30509 [CT]=30509 [CU]=30509 [VT]=30509 [VU]=30509)
declare -A PROTO=([T]=tcp [U]=udp [ST]=someip [SU]=someipu [CT]=csomeip [CU]=csomeipu [VT]=vsomeip [VU]=vsomeipu)
ARM_PROTOS="U=udp ST=someip SU=someipu CT=csomeip CU=csomeipu VT=vsomeip VU=vsomeipu"
if [ -z "${TEGRA:-}" ]; then
	if command -v tegrastats >/dev/null; then TEGRA=1; else TEGRA=0; fi
fi
case "$TEGRA" in 0|1) ;; *) echo "FATAL: TEGRA='$TEGRA' is not 0 or 1" >&2; exit 1 ;; esac
SAMPLE_WINDOW=0
KVM_STATS=0
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

up_check() {   # $1 proto  $2 port  $3 label: one untimed exchange
	taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$GUEST" --port "$2" --proto "$1" --n 1 --warmup 0 \
		--interval-ms 0 --timeout-s 3 --tag "check-$3" --out "$OUT/check-$3.json" >> "$OUT/check.log" 2>&1
}

write_config() {   # $1 tcp|udp: a vsomeip configuration with that endpoint only
	local ep
	if [ "$1" = tcp ]; then ep='"reliable": {"port": "30509", "enable-magic-cookies": "false"}'; else ep='"unreliable": "30509"'; fi
	cat > "$OUT/vsomeip-$1.json" <<EOF
{
  "unicast": "$HOST_IP",
  "logging": {"level": "warning", "console": "true", "file": {"enable": "false"}, "dlt": "false"},
  "applications": [{"name": "someip_vprobe", "id": "0x0200"}],
  "services": [{"service": "0x5afe", "instance": "0x0001", "unicast": "$GUEST", $ep}],
  "routing": "someip_vprobe",
  "service-discovery": {"enable": "false"}
}
EOF
}

boot_vm() {   # $1 label
	local lab="$1" log="$OUT/console-$1.log" i args t cm nv=0
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	BOOTED=1
	IFS_BIN="$IMG_S" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" \
		IVSHMEM= IVSHMEM_SERVER= KICK_SOCK= THREAD_NAMES=1 SMP="$SMP" MEM=1G TAP=tap-qnx \
		MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- \
		|| die "boot $lab failed -- see $OUT/boots.log and $log"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $IMG_S "*) ;; *) die "boot $lab: QEMU was not given $IMG_S" ;; esac
	pin_vm
	for t in $(ls "/proc/$VM_PID/task"); do
		cm="$(cat "/proc/$VM_PID/task/$t/comm" 2>/dev/null)"
		case "$cm" in "CPU "*"/KVM") nv=$((nv + 1)) ;; esac
	done
	[ "$nv" = "$SMP" ] || die "boot $lab: $nv thread(s) named CPU n/KVM for -smp $SMP"
	for i in $(seq 1 40); do up_check someip 30509 "$lab-someip" && break; sleep 0.5; done
	up_check someip 30509 "$lab-someip" || die "boot $lab: no SOME/IP monitor answering on :30509"
	up_check tcp 7100 "$lab-tcp" || die "boot $lab: no monitor answering on :7100"
	up_check udp 7101 "$lab-udp" || die "boot $lab: no monitor answering on :7101"
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$IMG_S") smp=$SMP qemu_pid=$VM_PID" >> "$OUT/boots.log"
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
	local a="$1" r="$2" cfg="$OUT/vsomeip-tcp.json"
	[ "$a" = VU ] && cfg="$OUT/vsomeip-udp.json"
	m_thermal "r$r $a before" >> "$OUT/thermal.log"
	SOMEIP_VPROBE="$VPROBE" VSOMEIP_CONFIGURATION="$cfg" \
		m_probe "$OUT" "$a"_r"$r" "$GUEST" "${PORT[$a]}" "" "${PROTO[$a]}"
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
ip -4 addr show br0 2>/dev/null | grep -q "inet $HOST_IP/" || die "br0 does not carry $HOST_IP, vsomeip's unicast"
if [ "$TEGRA" = 1 ]; then
	GPU_PCT="$(m_gpu_busy_pct)"
	[ "$GPU_PCT" = 0 ] || die "GR3D reads '${GPU_PCT}' at preflight, not 0% -- this run must have no GPU load"
	GPU_NOTE="none: no $LOADS resident at preflight, GR3D 0% at preflight and just before and after every arm"
else
	GPU_NOTE="not applicable: no tegrastats on this host (TEGRA=0); no $LOADS resident at preflight"
fi
m_require_balanced_k "$K" "${#MODES[@]}"
for f in "$PROBE" "$REPORT" "$LAUNCH" "$IMG_S" "$DISK"; do [ -r "$f" ] || die "missing: $f"; done
[ -x "$VPROBE" ] || die "no someip_vprobe at $VPROBE -- run orin-native/someip/build-vsomeip.sh"
case "$IMG_S$DISK" in *" "*) die "the images and the disk may not contain spaces (the boot check reads QEMU's argv)" ;; esac
grep -q 'VPROBE_MODES' "$PROBE" || die "$PROBE has no SOME/IP transports"

m_prepare_out "${OUT:-}" "$HOME/someip-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
write_config tcp
write_config udp
cp "$(dirname "$(dirname "$VPROBE")")/BUILD-INFO" "$OUT/vsomeip-BUILD-INFO" 2>/dev/null || echo "no BUILD-INFO beside $VPROBE" > "$OUT/vsomeip-BUILD-INFO"
m_governor_pin
m_cstate_apply

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "someip"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"T": 7100, "U": 7101, "ST": 30509, "SU": 30509, "CT": 30509, "CU": 30509, "VT": 30509, "VU": 30509}' \
	'"protos": {"T": "tcp", "U": "udp", "ST": "someip", "SU": "someipu", "CT": "csomeip", "CU": "csomeipu", "VT": "vsomeip", "VU": "vsomeipu"}' \
	"\"image_sha256\": \"$(_sha "$IMG_S")\"" \
	"\"vprobe_sha256\": \"$(_sha "$VPROBE")\"" \
	"\"vsomeip_config_sha256\": {\"tcp\": \"$(_sha "$OUT/vsomeip-tcp.json")\", \"udp\": \"$(_sha "$OUT/vsomeip-udp.json")\"}" \
	"\"config\": \"ifs-someip.bin, -smp $SMP\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(cat /sys/class/net/wlP1p1s0/operstate 2>/dev/null || echo none)\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\"" \
	'"boots": "one per round; per boot the eight arms in a Williams order over them (period 8); see order.log"' \
	"\"gpu_load\": \"$GPU_NOTE\"" \
	"\"tegra\": $TEGRA" \
	"\"arms\": [$(printf '"%s", ' "${MODES[@]}" | sed 's/, $//')]"
stop_vm || die "the preflight guest would not stop"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, one -smp $SMP boot per round, eight arms per boot -> $OUT"
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
say "the SOME/IP arm, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
