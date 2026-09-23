#!/usr/bin/env bash
# remote-ladder.sh -- the instance side of a bare-metal AWS ladder session.
# One phase per call, so the operator (drive-metal.sh run PHASE) sees each step:
#
#   setup     unpack, verify the image and disk against inputs.env, bridge, probe,
#             native monitor, KVM counters readable, host facts
#   quiesce   let cloud-init and snap settle, stop the apt timers for the session
#   launch    boot the guest with the ivshmem server and the kick console, and check
#             that its shm services came up
#   ladder    run-ladder.sh with LADDER_ENV (default: the notified-shm ladder of
#             results/orin-native-port/20260922T-a6-orin-kick) and K=12
#   capture   redact on THIS host into pub/, then pack pub.tgz (see capture.py)
#   stop      stop QEMU (a rehearsal on the Orin uses this)
#
# A LIVENESS SESSION (OD14, 2026-09-23) runs two other phases instead of launch
# and ladder, with ifs-live.bin as the image:
#
#   launch-live  boot the guest plainly -- no ivshmem, no kick console -- and
#                check that :7102 runs the 2000 ms deadline mode
#   liveness     liveness-demo.sh (the synthetic demo), then run-live-cost.sh
#                (plain TCP against the deadline mode, K rounds). On a host
#                without Tegra tools the cost run's GPU checks and window
#                sampler are recorded as not applicable (see its header).
#
# A STAMP SESSION (OD15, 2026-09-23), with ifs-stamp.bin as the image:
#
#   launch-stamp  boot the guest plainly and check :7100 (plain) and :7103
#                 (stamping) both came up
#   stamp         run-stamp.sh: plain against stamped, on the guest and on the
#                 native control, K rounds (a multiple of 4)
#
# capture accepts any of these sessions, but only a FINISHED one.
#
# W (default ~/a1) holds repo.tar, inputs.env, remote-ladder.sh, capture.py and
# img/<ifs> + img/disk-qemu.gz. Nothing under W leaves the host except pub.tgz,
# and everything in pub.tgz went through redact-aws.sh or capture.py's check here.
set -euo pipefail
PHASE="${1:?phase: setup|quiesce|launch|ladder|launch-live|liveness|launch-stamp|stamp|capture|stop}"
W="${W:-$HOME/a1}"
R="$W/repo/orin-native/gpu-concurrency"
REC="$W/rec"
LADDER_ENV="${LADDER_ENV:-SHM=1 KICK=1 DB=1 UDP_IN_TCP=1 KVM_STATS=1 ARM_C_PORT=7000 CSTATE=shallow}"
say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { say "FATAL: $*" >&2; exit 1; }
inputs() {
	[ -r "$W/inputs.env" ] || die "no $W/inputs.env (drive-metal.sh upload writes it)"
	# Parsed, not sourced: fixed names, fixed shapes.
	IFS_NAME="$(sed -n 's/^IFS_NAME=\([A-Za-z0-9._-][A-Za-z0-9._-]*\)$/\1/p' "$W/inputs.env")"
	IFS_SHA256="$(sed -n 's/^IFS_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	DISK_SHA256="$(sed -n 's/^DISK_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	RL_SHA256="$(sed -n 's/^REMOTE_LADDER_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	CAP_SHA256="$(sed -n 's/^CAPTURE_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	REPO_COMMIT="$(sed -n 's/^REPO_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' "$W/inputs.env")"
	[ -n "$IFS_NAME" ] && [ -n "$IFS_SHA256" ] && [ -n "$DISK_SHA256" ] \
		&& [ -n "$RL_SHA256" ] && [ -n "$CAP_SHA256" ] || die "inputs.env is malformed"
}

case "$PHASE" in
setup)
	inputs
	[ -e /var/lib/cloud/instance/PROVISIONED ] || [ -n "${REHEARSAL:-}" ] || die "user-data has not finished"
	id -nG | tr ' ' '\n' | grep -qx kvm || [ -w /dev/kvm ] || die "no access to /dev/kvm (log in again after user-data)"
	[ -e "$REC" ] && die "$REC exists -- a leftover; use a fresh W"
	mkdir -p "$REC/ladder"
	rm -rf "$W/repo"; mkdir -p "$W/repo"; tar -xf "$W/repo.tar" -C "$W/repo"
	[ -e "$W/img/disk-qemu" ] || gunzip -k "$W/img/disk-qemu.gz"
	echo "$IFS_SHA256  $W/img/$IFS_NAME" | sha256sum -c --quiet || die "$IFS_NAME hash mismatch"
	echo "$DISK_SHA256  $W/img/disk-qemu" | sha256sum -c --quiet || die "disk-qemu hash mismatch"
	echo "$RL_SHA256  $W/remote-ladder.sh" | sha256sum -c --quiet || die "remote-ladder.sh differs from what was uploaded"
	echo "$CAP_SHA256  $W/capture.py" | sha256sum -c --quiet || die "capture.py differs from what was uploaded"
	say "artefacts verified: $IFS_NAME ${IFS_SHA256:0:16} disk ${DISK_SHA256:0:16}"
	# The record names what actually ran: the instance-side tooling and its inputs.
	mkdir -p "$REC/tooling"
	cp "$W/remote-ladder.sh" "$W/capture.py" "$W/inputs.env" "$REC/tooling/"
	echo "commit ${REPO_COMMIT:-unknown}" > "$REC/tooling/repo-commit.txt"
	if ! ip link show br0 >/dev/null 2>&1 || ! ip link show tap-qnx >/dev/null 2>&1; then
		sudo bash "$W/repo/scripts/setup-bridge.sh"
		# The Orin's bridge (setup-bridge-orin.sh) has tap-qnx only; match it.
		sudo ip link del tap-linux 2>/dev/null || true
	fi
	ip -br addr show br0
	mkdir -p "$HOME/interference"
	cp "$R/latency_probe.py" "$HOME/interference/latency_probe.py"
	bash "$R/build-monitor-native.sh"
	sudo -n true || die "passwordless sudo is required"
	sudo sh -c 'mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug'
	# Every counter m_kvm_snap reads must read as an integer NOW: under kernel
	# lockdown debugfs refuses the 0644 stat files, and the snapshot would store
	# null and fail the doorbell check with a misleading message.
	eval "$(grep '^KVM_COUNTERS=' "$R/lib-measure.sh")"
	for c in $KVM_COUNTERS; do
		v="$(sudo cat "/sys/kernel/debug/kvm/$c" 2>/dev/null || true)"
		case "$v" in ''|*[!0-9]*) die "KVM counter $c unreadable ('$v') -- lockdown: $(cat /sys/kernel/security/lockdown 2>/dev/null)" ;; esac
	done
	say "KVM counters readable: $KVM_COUNTERS"
	F="$REC/host-facts.txt"
	{
		echo "== uname -v"; uname -v
		echo "== uname -r"; uname -r
		echo "== nproc"; nproc
		echo "== lockdown"; cat /sys/kernel/security/lockdown 2>/dev/null || echo absent
		# The root PARTUUID is masked: probably AMI-level, but not confirmed.
		echo "== cmdline"; sed -E 's/PARTUUID=[0-9a-fA-F-]+/PARTUUID=<partuuid>/g' /proc/cmdline
		echo "== transparent_hugepage"; cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo absent
		echo "== br_netfilter"; lsmod | grep -c '^br_netfilter' || true
		echo "== bridge ports (port master)"
		for n in /sys/class/net/*; do m="$(readlink "$n/master" 2>/dev/null || true)"; [ -n "$m" ] && echo "$(basename "$n") $(basename "$m")"; done
		echo "== kvm halt_poll"; for p in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do echo "$p=$(cat /sys/module/kvm/parameters/$p 2>/dev/null || echo NA)"; done
		echo "== qemu package"; dpkg-query -W -f='qemu_pkg=${Version}\n' qemu-system-arm 2>/dev/null || echo "qemu_pkg=none"
		echo "== lscpu -e"; lscpu -e 2>/dev/null || true
		echo "== cache sharing, cpu0-5"
		for c in 0 1 2 3 4 5; do for x in 2 3; do f="/sys/devices/system/cpu/cpu$c/cache/index$x/shared_cpu_list"; [ -r "$f" ] && echo "cpu$c L$x: $(cat "$f")"; done; done
	} > "$F" 2>&1
	grep -A1 -E '== (qemu package|lockdown|nproc)' "$F" | grep -v '^--'
	say "setup done: $(nproc) cores, kernel $(uname -r), $(qemu-system-aarch64 --version | head -1)"
	;;
quiesce)
	# A fresh AMI is busy: cloud-init's tail, snap seeding, apt timers. Settle
	# them for the session, and record the load so a noisy round can be seen.
	cloud-init status --wait >/dev/null 2>&1 || true
	command -v snap >/dev/null && timeout 120 sudo snap wait system seed.loaded 2>/dev/null || true
	sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service 2>/dev/null || true
	for _ in $(seq 1 60); do pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null || break; sleep 5; done
	pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null && die "apt/dpkg/unattended-upgrades still running after 5 min"
	say "quiet: loadavg $(cut -d' ' -f1-3 /proc/loadavg)"
	;;
launch)
	inputs
	cd "$R"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" IVSHMEM=/dev/shm/a6-ivshmem \
		IVSHMEM_SERVER=/tmp/a6-ivshmem.sock KICK_SOCK=/tmp/a6-kick.sock \
		LOG="$REC/ladder/guest-console.log" bash launch-qnx-kvm-bridged.sh \
		> "$REC/ladder/guest-launch.log" 2>&1 || { cat "$REC/ladder/guest-launch.log"; die "launch failed"; }
	cat "$REC/ladder/guest-launch.log"
	# "guest up" means the TCP monitor answers; the shm services start after it.
	# Check them here, so a failure is named here and not in the ladder.
	C="$REC/ladder/guest-console.log"
	for _ in $(seq 1 30); do
		grep -aq 'serving shm on ivshmem' "$C" && grep -aq 'serving shm-kick' "$C" && break
		sleep 1
	done
	grep -aq 'serving shm-kick' "$C" && grep -aq 'serving shm on ivshmem' "$C" \
		|| { tail -20 "$C"; die "the guest's shm services did not start"; }
	grep -a 'shm configured:' "$C" | cut -c1-120
	;;
ladder)
	cd "$R"
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	for w in $LADDER_ENV; do
		[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
	done
	echo "LADDER_ENV=$LADDER_ENV K=${K:-12}" > "$REC/ladder/ladder-env.txt"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/ladder/host-before.txt"
	# shellcheck disable=SC2086  # LADDER_ENV is a list of validated NAME=value words
	env -- $LADDER_ENV OUT="$REC/ladder/raw" K="${K:-12}" bash run-ladder.sh > "$REC/ladder/run.log" 2>&1 \
		|| { tail -30 "$REC/ladder/run.log"; die "run-ladder.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/ladder/host-after.txt"
	tail -5 "$REC/ladder/run.log"
	;;
launch-live)
	inputs
	cd "$R"
	mkdir -p "$REC/liveness"
	C="$REC/liveness/guest-console.log"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$REC/liveness/guest-launch.log" 2>&1 || { cat "$REC/liveness/guest-launch.log"; die "launch failed"; }
	cat "$REC/liveness/guest-launch.log"
	# "guest up" means :7100 answers; the image must also run :7102 in deadline mode.
	B='listening on :7102 (frame=64 bytes, conf_min=60%), liveness deadline 2000 ms'
	for _ in $(seq 1 30); do tr -d '\0\r' < "$C" | grep -aqF "$B" && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aqF "$B" \
		|| { tail -20 "$C"; die "no 2000 ms deadline-mode monitor on :7102 -- is the image ifs-live?"; }
	say "deadline-mode monitor up on :7102"
	;;
liveness)
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/liveness/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-live first"
	E="$W/repo/orin-native/edge-llm"
	[ -r "$E/liveness-demo.sh" ] && [ -r "$E/run-live-cost.sh" ] || die "the repo tarball lacks orin-native/edge-llm"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/liveness/host-before.txt"
	CONSOLE="$C" OUT="$REC/liveness/demo" bash "$E/liveness-demo.sh" > "$REC/liveness/demo.log" 2>&1 \
		|| { tail -20 "$REC/liveness/demo.log"; die "liveness-demo.sh failed"; }
	tail -12 "$REC/liveness/demo.log"
	CONSOLE="$C" OUT="$REC/liveness/cost" K="${K:-12}" bash "$E/run-live-cost.sh" > "$REC/liveness/cost.log" 2>&1 \
		|| { tail -30 "$REC/liveness/cost.log"; die "run-live-cost.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/liveness/host-after.txt"
	tail -8 "$REC/liveness/cost.log"
	;;
launch-stamp)
	inputs
	cd "$R"
	mkdir -p "$REC/stamp"
	C="$REC/stamp/guest-console.log"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$REC/stamp/guest-launch.log" 2>&1 || { cat "$REC/stamp/guest-launch.log"; die "launch failed"; }
	cat "$REC/stamp/guest-launch.log"
	B='stamping replies on :7103: t_in payload[8..15]'
	for _ in $(seq 1 30); do tr -d '\0\r' < "$C" | grep -aqF "$B" && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aqF "$B" \
		|| { tail -20 "$C"; die "no stamping monitor on :7103 -- is the image ifs-stamp?"; }
	say "plain monitor on :7100 and stamping monitor on :7103 up"
	;;
stamp)
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/stamp/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-stamp first"
	[ -r "$R/run-stamp.sh" ] || die "the repo tarball lacks run-stamp.sh"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/stamp/host-before.txt"
	CONSOLE="$C" OUT="$REC/stamp/raw" MON="$W/stamp-monitor-native" K="${K:-12}" \
		bash "$R/run-stamp.sh" > "$REC/stamp/run.log" 2>&1 \
		|| { tail -30 "$REC/stamp/run.log"; die "run-stamp.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/stamp/host-after.txt"
	tail -22 "$REC/stamp/run.log"
	;;
capture)
	# The session must have FINISHED: host-after.txt is written only after the
	# ladder, the liveness phase or the stamp phase returned 0. Without it the
	# run was interrupted, or refused as incomplete, and a partial record must
	# not be packed and fetched as a whole one.
	[ -e "$REC/ladder/host-after.txt" ] || [ -e "$REC/liveness/host-after.txt" ] || [ -e "$REC/stamp/host-after.txt" ] \
		|| die "no host-after.txt under $REC/ladder, $REC/liveness or $REC/stamp -- the session did not finish; there is no complete record to capture"
	RED="$R/redact-aws.sh"
	bash "$RED" selftest >/dev/null || die "redactor selftest failed"
	rm -rf "$W/pub" "$W/pub.sha256"; mkdir -p "$W/pub"
	# USER empty: the login is Ubuntu's public default, "ubuntu", and masking it would
	# rewrite the QEMU package version (1:6.2+dfsg-2ubuntu6.31) in the stamp and logs.
	# A trailing "@ubuntu" prompt is still masked through AWS_SSH_USER.
	USER= python3 "$W/capture.py" "$REC" "$W/pub" "$RED" || die "capture refused"
	tar -czf "$W/pub.tgz" -C "$W/pub" .
	say "captured $(wc -l < "$W/pub.sha256") files into pub.tgz ($(du -h "$W/pub.tgz" | cut -f1))"
	;;
stop)
	sudo pkill -x qemu-system-aar 2>/dev/null || true
	sleep 1
	pgrep -x qemu-system-aar >/dev/null && die "QEMU still running"
	say "stopped"
	;;
*) die "unknown phase $PHASE" ;;
esac
