#!/usr/bin/env bash
# run-bellrobust.sh -- the doorbell into the guest under conditions the latency runs never make:
# rings with no request, rings while the guest is still booting, more rings than requests, host
# peers that come and go, the MSI-X set-up run twice, the vlm claim, and the deferred unmask under
# spurious and doubled rings. Phase 3b / A6, 2026-09-29. The owner asked for it (2026-09-29), as
# the doorbell's fifth follow-up. A functional test: nothing here is timed. run-bell.sh and
# run-unmask.sh drive the MSI-X monitors only through latency_probe.py, one ring per request.
#
# WHAT IS KNOWN. 20260929T-a6-orin-its, 20260929T-a6-orin-bell, 20260929T-a6-orin-mmio,
# 20260929T-a6-orin-unmask (held locally).
#
# THE INSTRUMENTS.
#   guest  ifs-bell.bin (the MSI-X monitor at slot 8192 on vector 0, unmasking before the reply;
#          the console-kicked one at slot 4096); ifs-robust.bin (ifs-bell.bin with
#          "qnx-its-probe msixcfg" run twice before any monitor); ifs-unmask-a.bin (two vectors: the
#          monitor at slot 12288 on vector 1 defers its unmask to the next wait). A monitor that wakes
#          and finds no new request in its slot answers nothing (monitor.c counts it "stale"); it
#          reads the slot's reply way and client peer afresh for each request it answers.
#   host   latency_probe.py through libshmchan.so, one exchange at a time, each set checked against
#          its own counts (it stops at the first reply it waits for in vain); ivshmem_ring.py, which
#          rings a vector of the guest's device with no request, and with --slot observes that
#          monitor's slot as its client (its own peer id in client_peer, a doorbell as the reply way,
#          req_seq untouched; it waits 0.5 s after writing them, so QEMU knows its peer id before the
#          first ring) and counts the doorbells that come back; KVM's counters (m_kvm_snap) around an
#          idle window as long as the rings' nominal duration, then around the rings.
#   QEMU   6.2's ivshmem under KVM (hw/misc/ivshmem.c: setup_interrupt, ivshmem_enable_irqfd,
#          ivshmem_vector_poll): a ring before the guest enables MSI-X waits, unwatched, in the
#          vector's eventfd, and one while the MSI-X entry is masked is set pending; either way at
#          most one interrupt comes of them when the entry is enabled and unmasked. After that KVM's
#          irqfd sends an MSI when the eventfd is signalled, and while the guest has the LPI masked
#          the GIC holds it pending. So rings before msixcfg can leave at most one interrupt at
#          set-up.
#
# THE SCENARIOS, R=3 repeats, each scenario in a guest boot of its own, in this order per repeat:
#   S1 bell    spurious rings: a check (100 exchanges), then 500 rings of vector 0 at 2 ms with the
#              observer on slot 8192, then a check
#   S2 bell    doubled rings: a check, then 2000 rings of vector 0 at 1 ms, the probe starting 0.5 s
#              into them and making 400 exchanges at 2 ms on it, then a check
#   S3 bell    host peer churn: a check, then 20 probes one after another, 20 exchanges each, then a
#              check
#   S4 bell    early rings: from "peer 1 connected" in the ivshmem server's log (QEMU has joined) the
#              guest's vector 0 is rung every 5 ms, 4000 times, while the guest boots, and the harness
#              notes when msixcfg's success line and the MSI-X monitor's banner are first seen; then a
#              check
#   S5 bell    the vlm claim: a check, then 100 exchanges carrying the vlm claim, then a check
#   S6 robust  msixcfg twice: 100 exchanges on the MSI-X way and 100 on the console way (they show
#              both monitors serving)
#   S7 unmask  spurious rings as S1, on vector 1 and slot 12288 (the deferred unmask)
#   S8 unmask  doubled rings as S2, on vector 1 and slot 12288
# QEMU pinned to cores 0-2, the probe and the ring tool to core 4, the governor pinned, c7 off, no
# load. About 15 min.
#
# THE RULE, fixed here before any run (bellrobust_report.py applies it). An exchange set is clean
# when the probe exited 0 and its file shows the n it asked for, none bad, none rejected, exchanges
# == notifications == n, no early wake-up, no stray byte and no EAGAIN. A ring set is clean when
# the ring tool exited 0 and says it rang its count. A scenario passes in a repeat when every
# exchange set and ring set it names after its opening check is clean and, in S1 and S7, the
# observer counted 0 doorbells. No banner is scored: the monitors start together and their console
# lines can interleave.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs included. It is
# not to be amended.
#   H1 with the unmask before the reply, the MSI-X way into the guest survives spurious rings,
#      doubled rings, rings while the guest boots, host peers joining and leaving one after
#      another, and its own set-up run twice, answering no ring it has no request for; with the
#      unmask deferred, it survives spurious and doubled rings the same way; and the monitor on the
#      MSI-X way judges the vlm claim.
#   P1..P8 each scenario S1..S8 passes in every repeat that is not VOID: HELD. In some: PARTIAL. In
#      none: REFUTED. VOID in every repeat: VOID. A verdict resting on fewer than the three repeats
#      says how many ran.
# Not predicted, reported: per scenario and repeat the detail; the rings' rise of KVM's kernel
# MMIO exits against the idle window's rate; S4's ring window against when msixcfg and the MSI-X
# monitor were first seen; console lines naming an error.
#
# THE CHECKS. M1 and M2 make a repeat VOID outright. M3 to M8 show the scenario's condition was
# really made and every set it names ran, so they make VOID only a repeat that would otherwise
# pass: a failure stands whether or not they held (a doorbell that wedges at the first ring also
# stops the rings' exits and outlasts the ring window):
#   M1 its boot came up: the launcher saw the guest answer on :7100, and QEMU ran the scenario's
#      image with its vector count (boots.log)
#   M2 the opening check (S1-S3, S5, S7, S8) ran and was clean: otherwise the doorbell was already
#      broken
#   M3 S1 and S7: the rings reached the guest -- KVM's kernel MMIO exits over the rings exceeded
#      the idle window's rate, taken over the rings' own duration, by at least 2 per ring. Design
#      basis: the startup library's LPI mask and unmask callouts each issue ITS commands, and KVM
#      emulates the ITS command queue in the kernel
#   M4 S3: the 20 probes had 20 different peer ids (the server never reuses one)
#   M5 S2 and S8: the ring window covered at least 80% of the probe's run
#   M6 S4: msixcfg's success line and the MSI-X monitor's banner were first seen (by short tokens)
#      after the first ring and before the last
#   M7 every set the scenario names ran (its line is in scenarios.log): not so when a run stops
#      part-way, or when S4's rings never started
#   M8 S6: msixcfg's success line was seen at least twice
#
# What this does NOT test: timing; a ring lost and then covered by the next spurious ring in S2 and
# S8 (only a lasting wedge or an extra doorbell is caught there); that S4's early rings reached the
# guest (M6 shows they were sent across the set-up, not delivered) or that none was answered (no
# observer while the guest boots); a first doorbell lost to a host peer that has just joined (S3:
# the probe's handshake absorbs one); that an invalid vlm claim is rejected (S5 sends valid ones);
# the rings' cover of the probe's exchanges as such (M5 measures the probe's process span, start-up
# included, and S2's 0.5 s runs from the ring tool's launch, not its first ring); a peer that
# leaves with a request outstanding; peer id reuse; msixcfg with a monitor attached; the deferred
# unmask under early rings, peer churn or a second set-up; the mnist claim beyond the checks; a
# guest reboot under a live server; a real ITS; QNX's supported MSI path; a1.metal. The startup is
# ours: not a QNX-supported configuration.
#
# NEEDS: no QEMU running; IMG_B (ifs-bell.bin), IMG_R (ifs-robust.bin), IMG_UA (ifs-unmask-a.bin),
# DISK; tap-qnx on br0; gcc (libshmchan.so is built here). CSTATE=shallow (set before the library).
# No load.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

R="${R:-3}"
QEMU_CORES="${QEMU_CORES:-0-2}"
CORE_PROBE="${CORE_PROBE:-4}"
CORE_AUX="${CORE_AUX:-5}"
PROBE="${PROBE:-$here/latency_probe.py}"
RING="${RING:-$here/ivshmem_ring.py}"
REPORT="${REPORT:-$here/bellrobust_report.py}"
LAUNCH="${LAUNCH:-$here/launch-qnx-kvm-bridged.sh}"
COMMON="${COMMON:-$here/../../ipc-test/common}"
IMG_B="${IMG_B:-$HOME/output/ifs-bell.bin}"
IMG_R="${IMG_R:-$HOME/output/ifs-robust.bin}"
IMG_UA="${IMG_UA:-$HOME/output/ifs-unmask-a.bin}"
DISK="${DISK:-$HOME/output/disk-qemu}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
SETTLE_S="${SETTLE_S:-3}"
SMP=2
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOADS="llama-server llama-cli llama-bench fma cpuload"
VM_PID=""; BOOTED=0; REPORTED=0; OUT_READY=0

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

report() {   # once, from the end of the run or from the EXIT trap: an aborted run still gets verdicts
	[ "$REPORTED" = 0 ] && [ "$OUT_READY" = 1 ] || return 0   # never a stale OUT
	REPORTED=1
	say "the doorbell's robustness, by the rule above"
	python3 "$REPORT" "$OUT" || echo "WARNING: the report could not be made" >&2
}

cleanup() {
	say "cleanup"
	local p
	for p in $(jobs -p); do kill "$p" 2>/dev/null; done   # live jobs only: never a reused pid
	if [ "$BOOTED" = 1 ]; then
		for VM_PID in $(m_pids_of qemu-system-aarch64); do
			stop_vm || echo "WARNING: the guest QEMU $VM_PID would not stop" >&2
		done
	fi
	VM_PID=""
	m_cstate_restore; m_governor_restore
	report
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

ns() { date +%s%N; }

# One exchange set: $1 tag  $2 n  $3 slot  $4 proto (shmbell|shmdb)  $5 vector  [$6 claim]
exchanges() {
	local tag="$1" n="$2" slot="$3" proto="$4" vec="$5" claim="${6:-}" extra=() t0
	if [ "$proto" = shmdb ]; then extra=(--kick "$KICK_SOCK"); else extra=(--bell-vector "$vec"); fi
	[ -n "$claim" ] && extra+=(--claim "$claim")
	t0="$(ns)"
	taskset -c "$CORE_PROBE" python3 "$PROBE" --proto "$proto" --shm "$IVSHMEM@$slot" --ivshm "$IVSHMEM_SERVER" \
		--shm-lib "$SHMCHAN_LIB" "${extra[@]}" --n "$n" --warmup 0 --interval-ms 2 --timeout-s 3 \
		--tag "$tag" --out "$OUT/ex-$tag.json" >> "$OUT/probe.log" 2>&1
	echo "$tag rc=$? t0=$t0 t1=$(ns)" >> "$OUT/scenarios.log"
}

# Rings with no request: $1 tag  $2 count  $3 gap ms  $4 vector  [$5 observed slot]
rings() {
	local obs=()
	[ -n "${5:-}" ] && obs=(--slot "$5")
	taskset -c "$CORE_PROBE" python3 "$RING" --socket "$IVSHMEM_SERVER" --count "$2" --gap-ms "$3" \
		--vector "$4" "${obs[@]}" > "$OUT/ring-$1.log" 2>&1
	echo "ring-$1 rc=$?" >> "$OUT/scenarios.log"
}

# Delivery evidence for rings: an idle window, then the rings, each between KVM snapshots.
observed_rings() {   # $1 tag  $2 count  $3 gap ms  $4 vector  $5 slot
	m_kvm_snap "$OUT/kvm-$1-idle.json" before
	sleep "$(awk -v c="$2" -v g="$3" 'BEGIN {printf "%.3f", c * g / 1000}')"
	m_kvm_snap "$OUT/kvm-$1-idle.json" after
	m_kvm_snap "$OUT/kvm-$1-rings.json" before
	rings "$1" "$2" "$3" "$4" "$5"
	m_kvm_snap "$OUT/kvm-$1-rings.json" after
}

# Boot one guest; 0 if it came up (M1), 1 if not -- logged, and the run goes on to the next.
boot_vm() {   # $1 label  $2 image  $3 vectors  [$4 early-ring tag]
	local lab="$1" log="$OUT/console-$1.log" args lpid i rp="" mseen="" bseen=""
	[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is still running before boot $lab"
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK" "$OUT/ivshmem-server.log"
	BOOTED=1
	IFS_BIN="$2" DISK="$DISK" LOG="$log" CORE_AUX="$CORE_AUX" VECTORS="$3" \
		IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" THREAD_NAMES=1 \
		SMP="$SMP" MEM=1G TAP=tap-qnx MAC=52:54:00:11:11:11 QEMU=qemu-system-aarch64 \
		bash "$LAUNCH" >> "$OUT/boots.log" 2>&1 9>&- &
	lpid=$!
	if [ -n "${4:-}" ]; then   # S4: ring while the guest boots, once QEMU (peer 1) has joined the server
		for i in $(seq 1 1200); do grep -q 'peer 1 connected' "$OUT/ivshmem-server.log" 2>/dev/null && break; sleep 0.05; done
		if grep -q 'peer 1 connected' "$OUT/ivshmem-server.log" 2>/dev/null; then
			rings "$4" 4000 5 0 &
			rp=$!
			for i in $(seq 1 1800); do   # when msixcfg and the MSI-X monitor are first seen (M6), by short tokens
				[ -z "$mseen" ] && grep -qaF 'EventID 0 -> LPI 8193' "$log" 2>/dev/null && mseen="$(ns)"
				[ -z "$bseen" ] && grep -qaF 'kick msix (LPI 8193)' "$log" 2>/dev/null && bseen="$(ns)"
				[ -n "$mseen" ] && [ -n "$bseen" ] && break
				kill -0 "$lpid" 2>/dev/null || [ -n "$(m_pids_of qemu-system-aarch64)" ] || break
				sleep 0.05
			done
			echo "$4 msixcfg_seen=${mseen:-never} msix_monitor_seen=${bseen:-never}" >> "$OUT/scenarios.log"
		else
			echo "$4 no 'peer 1 connected' in the server's log within 60 s" >> "$OUT/scenarios.log"
		fi
	fi
	if ! wait "$lpid"; then
		[ -n "$rp" ] && wait "$rp"
		echo "$lab FAILED to come up" >> "$OUT/boots.log"
		for VM_PID in $(m_pids_of qemu-system-aarch64); do stop_vm; done
		cp "$OUT/ivshmem-server.log" "$OUT/ivshmem-server-$lab.log" 2>/dev/null
		return 1
	fi
	[ -n "$rp" ] && wait "$rp"
	VM_PID="$(m_pids_of qemu-system-aarch64)"
	[ -n "$VM_PID" ] && [ "$(printf '%s\n' "$VM_PID" | grep -c .)" = 1 ] || die "boot $lab: not exactly one QEMU"
	args="$(tr '\0' ' ' < "/proc/$VM_PID/cmdline")"
	case "$args" in *"-kernel $2 "*) ;; *) die "boot $lab: QEMU was not given $2" ;; esac
	case "$args" in *"ivshmem-doorbell,chardev=ivsh0,vectors=$3"*) ;; *) die "boot $lab: the doorbell device has not $3 vector(s)" ;; esac
	pin_vm
	sleep "$SETTLE_S"
	echo "$lab image=$(basename "$2") vectors=$3 qemu_pid=$VM_PID" >> "$OUT/boots.log"
	return 0
}

end_boot() {   # $1 label
	local i
	stop_vm || die "the guest of $1 would not stop"
	# The server exits with QEMU and unlinks its socket then: let it, before the next boot makes one
	for i in $(seq 1 50); do [ -e "$IVSHMEM_SERVER" ] || break; sleep 0.1; done
	[ -e "$IVSHMEM_SERVER" ] && die "the ivshmem server of $1 did not exit with its QEMU"
	cp "$OUT/ivshmem-server.log" "$OUT/ivshmem-server-$1.log" 2>/dev/null
}

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for x in $LOADS; do
	[ -z "$(m_pids_of "$x")" ] || die "$x is resident -- this run must have no load"
done
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a QEMU is already running: this harness boots its own guests"
[ -e /sys/class/net/tap-qnx ] || die "no tap-qnx -- run scripts/orin/setup-bridge-orin.sh (a reboot drops it)"
for f in "$PROBE" "$RING" "$REPORT" "$LAUNCH" "$IMG_B" "$IMG_R" "$IMG_UA" "$DISK" "$here/shmchan.c"; do
	[ -r "$f" ] || die "missing: $f"
done
grep -q -- '--slot' "$RING" || die "$RING has no --slot (the observer)"
grep -q -- '--bell-vector' "$PROBE" || die "$PROBE has no --bell-vector"

[ -z "${OUT:-}" ] || [ ! -d "$OUT" ] || [ -z "$(ls -A "$OUT")" ] \
	|| die "$OUT is not empty: a fresh OUT per run (the report reads every file in it)"
m_prepare_out "${OUT:-}" "$HOME/bellrobust-out"
m_check_cores "$QEMU_CORES" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "probe=$CORE_PROBE" "aux=$CORE_AUX"
: > "$OUT/boots.log"; : > "$OUT/probe.log"; : > "$OUT/scenarios.log"; OUT_READY=1
m_build_shmchan "$here/shmchan.c" "$COMMON" "$OUT/libshmchan.so"
m_governor_pin
m_cstate_apply
N=100; K="$R"; WARMUP=0; INTERVAL_MS=2
m_write_stamp "$OUT/stamp.json" \
	'"experiment": "bellrobust"' \
	"\"repeats\": $R" \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"probe\": $CORE_PROBE, \"aux\": $CORE_AUX}" \
	"\"image_sha256\": {\"bell\": \"$(_sha "$IMG_B")\", \"robust\": \"$(_sha "$IMG_R")\", \"unmask\": \"$(_sha "$IMG_UA")\"}" \
	"\"ring_sha256\": \"$(_sha "$RING")\"" \
	"\"shmchan_sha256\": \"$(_sha "$here/shmchan.c")\"" \
	"\"lan_default_route\": \"$(ip route | awk '/^default/ {print $5; exit}')\"" \
	"\"reset_reason_at_start\": \"$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>/dev/null || echo unread)\"" \
	"\"nvpmodel\": \"$(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')\""

# ---------------------------------------------------------------- the run
for r in $(seq 1 "$R"); do
	if boot_vm "S1_r$r" "$IMG_B" 1; then
		exchanges "S1_r$r-pre" 100 8192 shmbell 0
		observed_rings "S1_r$r" 500 2 0 8192
		exchanges "S1_r$r-check" 100 8192 shmbell 0
		end_boot "S1_r$r"
	fi
	if boot_vm "S2_r$r" "$IMG_B" 1; then
		exchanges "S2_r$r-pre" 100 8192 shmbell 0
		rings "S2_r$r" 2000 1 0 &
		rp=$!; sleep 0.5
		exchanges "S2_r$r" 400 8192 shmbell 0
		wait "$rp"
		exchanges "S2_r$r-check" 100 8192 shmbell 0
		end_boot "S2_r$r"
	fi
	if boot_vm "S3_r$r" "$IMG_B" 1; then
		exchanges "S3_r$r-pre" 100 8192 shmbell 0
		for c in $(seq 1 20); do exchanges "S3_r$r-p$c" 20 8192 shmbell 0; done
		exchanges "S3_r$r-check" 100 8192 shmbell 0
		end_boot "S3_r$r"
	fi
	if boot_vm "S4_r$r" "$IMG_B" 1 "S4_r$r"; then
		exchanges "S4_r$r-check" 100 8192 shmbell 0
		end_boot "S4_r$r"
	fi
	if boot_vm "S5_r$r" "$IMG_B" 1; then
		exchanges "S5_r$r-pre" 100 8192 shmbell 0
		exchanges "S5_r$r-vlm" 100 8192 shmbell 0 vlm
		exchanges "S5_r$r-check" 100 8192 shmbell 0
		end_boot "S5_r$r"
	fi
	if boot_vm "S6_r$r" "$IMG_R" 1; then
		exchanges "S6_r$r-msix" 100 8192 shmbell 0
		exchanges "S6_r$r-console" 100 4096 shmdb 0
		end_boot "S6_r$r"
	fi
	if boot_vm "S7_r$r" "$IMG_UA" 2; then
		exchanges "S7_r$r-pre" 100 12288 shmbell 1
		observed_rings "S7_r$r" 500 2 1 12288
		exchanges "S7_r$r-check" 100 12288 shmbell 1
		end_boot "S7_r$r"
	fi
	if boot_vm "S8_r$r" "$IMG_UA" 2; then
		exchanges "S8_r$r-pre" 100 12288 shmbell 1
		rings "S8_r$r" 2000 1 1 &
		rp=$!; sleep 0.5
		exchanges "S8_r$r" 400 12288 shmbell 1
		wait "$rp"
		exchanges "S8_r$r-check" 100 12288 shmbell 1
		end_boot "S8_r$r"
	fi
	say "repeat $r/$R done"
done

m_governor_recheck
report
