#!/usr/bin/env bash
# run-someip0.sh -- the SOME/IP arm's follow-up: vsomeip without its nPDU retention. Phase 3b / A6,
# 2026-09-27; follows 20260927T-a6-orin-someip.
# The owner asked for this run (2026-09-27: the SOME/IP arm, "剩下都可以直接預設進行").
#
# WHAT IS KNOWN. What vsomeip 3.4.10, as configured in run-someip.sh, adds to a request's round
# trip against the same C++ client on a plain socket: record 20260927T-a6-orin-someip (held
# locally). vsomeip's source: outgoing messages
# ride "trains" (nPDU); a lone request boards an empty train that departs at now + the maximum
# retention time, by a timer; the default is 5 ms (VSOMEIP_DEFAULT_NPDU_MAXIMUM_RETENTION_NANO,
# with VSOMEIP_DEFAULT_NPDU_DEBOUNCING_NANO 2 ms, internal.hpp.in at 3.4.10). That run's
# configurations set no npdu-default-timings.
#
# THE MANIPULATION. The same client and guest; vsomeip's configuration with and without
# "npdu-default-timings": {"debounce-time-request": "0", "debounce-time-response": "0",
# "max-retention-time-request": "0", "max-retention-time-response": "0"} (milliseconds).
#   CT  csomeip   plain socket, TCP              CU  csomeipu  plain socket, UDP
#   VT  vsomeip   the run-someip.sh config, TCP  VU  vsomeipu  the run-someip.sh config, UDP
#   VT0 vsomeip   the same, timings 0, TCP       VU0 vsomeipu  the same, timings 0, UDP
# All to :30509 of ifs-someip.bin, one -smp 2 boot per round, a Williams order over the six
# arms, n=1000 after 200 warm-up at 2 ms, K=12. QEMU pinned to cores 0-2, every client to core 4,
# the governor pinned, c7 off, no load. About 15 min.
#
# THE RULE, fixed here before any run (someip0_report.py applies it). Per arm and round the
# probe's p50. Differences are paired within the round; per difference, the median over rounds
# with the distribution-free interval of widest coverage >= 95% (d(3)..d(10), 96.1%, at K = 12).
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included.
# It is not to be amended. P1 is not blind: it was written after run-someip.sh's result and
# after reading vsomeip's source. P2 and P3 are about the configuration no run has measured.
#   H  the ~5 ms is vsomeip's default nPDU retention; without it, vsomeip's own cost is small
#      against the partition boundary.
#   P1 VT - VT0 and VU - VU0 each lie in [4800, 5200] us.
#   P2 VT0 - CT >= +10 us and VU0 - CU >= +10 us.
#   P3 VT0 - CT <= 0.25 x the median of CT's p50, and VU0 - CU <= 0.25 x the median of CU's p50
#      (run-someip.sh's P3, asked again of the configuration without the retention).
# Not predicted, reported: VT - CT and VU - CU (run-someip.sh's P2 and P3 again), and every
# arm's p99.
#
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every arm has K rounds of n samples, none rejected, none bad, its own transport, and
#      the client on the probe core (the gate, and the report again)
#   M2 VT, VU, VT0 and VU0 name vsomeip 3.4.10; CT and CU name none
#   M3 every boot's guest console has one "someip: tcp client done (eof)" line with
#      seen = n + warm-up, rejected = 0 and errors = 0 for each of CT, VT and VT0
#   M4 the four configurations are as described: the two "0" ones carry the four timings at
#      "0", the other two carry none
#
# What this does NOT test: which nPDU setting a real deployment should use (0 turns batching
# off); vsomeip's threads on cores of their own; SOME/IP-SD, events, E2E, TP; vsomeip on QNX;
# the tail beyond p99.
#
# NEEDS: no QEMU running; IMG (ifs-someip.bin), DISK, VPROBE (someip_vprobe, built by
# orin-native/someip/build-vsomeip.sh). CSTATE=shallow (set before the library). No load.
# K a multiple of 6.
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
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS=2
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
REPORT="${REPORT:-$here/someip0_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
IMG_S="${IMG_S:-$HOME/output/ifs-someip.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
VPROBE="${VPROBE:-$HOME/vsomeip/3.4.10/bin/someip_vprobe}"
SETTLE_S="${SETTLE_S:-3}"
SMP=2
MODES=(CT VT VT0 CU VU VU0)
declare -A PORT=([CT]=30509 [VT]=30509 [VT0]=30509 [CU]=30509 [VU]=30509 [VU0]=30509)
declare -A PROTO=([CT]=csomeip [VT]=vsomeip [VT0]=vsomeip [CU]=csomeipu [VU]=vsomeipu [VU0]=vsomeipu)
declare -A CFG=([CT]=tcp [VT]=tcp [VT0]=tcp0 [CU]=udp [VU]=udp [VU0]=udp0)
ARM_PROTOS="CT=csomeip VT=vsomeip VT0=vsomeip CU=csomeipu VU=vsomeipu VU0=vsomeipu"
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

write_config() {   # $1 tcp|udp|tcp0|udp0: a vsomeip configuration with that endpoint only; *0 with npdu timings 0
	local ep npdu=""
	case "$1" in
		tcp*) ep='"reliable": {"port": "30509", "enable-magic-cookies": "false"}' ;;
		*) ep='"unreliable": "30509"' ;;
	esac
	case "$1" in
		*0) npdu='  "npdu-default-timings": {"debounce-time-request": "0", "debounce-time-response": "0", "max-retention-time-request": "0", "max-retention-time-response": "0"},
' ;;
	esac
	cat > "$OUT/vsomeip-$1.json" <<EOF
{
  "unicast": "$HOST_IP",
$npdu  "logging": {"level": "warning", "console": "true", "file": {"enable": "false"}, "dlt": "false"},
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
	local a="$1" r="$2" cfg="$OUT/vsomeip-${CFG[$1]}.json"
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

m_prepare_out "${OUT:-}" "$HOME/someip0-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"
for c in tcp udp tcp0 udp0; do write_config "$c"; done
cp "$(dirname "$(dirname "$VPROBE")")/BUILD-INFO" "$OUT/vsomeip-BUILD-INFO" 2>/dev/null || echo "no BUILD-INFO beside $VPROBE" > "$OUT/vsomeip-BUILD-INFO"
m_governor_pin
m_cstate_apply

boot_vm preflight
m_pin_qemu "$QEMU_CORES"
INTERVAL_MS=2 m_write_stamp "$OUT/stamp.json" \
	'"experiment": "someip0"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	'"ports": {"CT": 30509, "VT": 30509, "VT0": 30509, "CU": 30509, "VU": 30509, "VU0": 30509}' \
	'"protos": {"CT": "csomeip", "VT": "vsomeip", "VT0": "vsomeip", "CU": "csomeipu", "VU": "vsomeipu", "VU0": "vsomeipu"}' \
	'"configs": {"CT": "tcp", "VT": "tcp", "VT0": "tcp0", "CU": "udp", "VU": "udp", "VU0": "udp0"}' \
	"\"image_sha256\": \"$(_sha "$IMG_S")\"" \
	"\"vprobe_sha256\": \"$(_sha "$VPROBE")\"" \
	"\"vsomeip_config_sha256\": {\"tcp\": \"$(_sha "$OUT/vsomeip-tcp.json")\", \"udp\": \"$(_sha "$OUT/vsomeip-udp.json")\", \"tcp0\": \"$(_sha "$OUT/vsomeip-tcp0.json")\", \"udp0\": \"$(_sha "$OUT/vsomeip-udp0.json")\"}" \
	"\"config\": \"ifs-someip.bin, -smp $SMP\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"wifi_state\": \"$(m_wifi_state)\"" \
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
m_summary "$OUT" CT "${MODES[@]}"
say "vsomeip without its nPDU retention, by the rule above"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
