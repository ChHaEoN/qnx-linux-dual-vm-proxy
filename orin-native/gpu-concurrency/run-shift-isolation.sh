#!/usr/bin/env bash
# run-shift-isolation.sh -- which change raised the guest's socket rungs?
#
# WHY. Between the Orin's UDP run and its notified-shm run (both 2026-09-22) the
# guest's TCP rungs rose 32-38 us while the host-only rungs moved a few us; on
# AWS a1.metal the same kind of change raised them ~76 us. Several things
# changed at once, so the notified-shm records could only state it. This
# separates three of them, on one host, in one session:
#
#   A  ifs-udp.bin, no extra devices                  (the UDP run's guest)
#   B  ifs-udp.bin + ivshmem-doorbell + virtio console (+ the ivshmem server):
#      the devices and the host-side server, but a guest that ignores them
#   C  ifs-kick.bin + the same devices                 (the notified-shm run's guest)
#
# and, inside every boot, the ladder twice: KVM_STATS=0 and KVM_STATS=1 (the
# per-arm KVM snapshot with sudo and a 100 ms pause), in alternating order.
# So B - A is the devices and the server, C - B the image, KVM1 - KVM0 the
# snapshots. The level of a rung is only comparable ACROSS boots, so boots run
# A B C C B A by default: a linear drift over the session cancels in each
# difference.
#
# and, to split C - B once it was known to be the image (the second session):
#
#   S  ifs-shm.bin + the same devices                  (the polled monitor only)
#   N  ifs-kick-nomon.bin + the same devices           (ifs-kick minus the shmkick
#                                                       monitor: devc-virtio stays)
#
# so S - B is the polled monitor, N - S devc-virtio (and the one-shot shmcfg),
# C - N the notified monitor reading /dev/vcon2.
#
# The ladder is the TCP group with D-udp in it (UDP_IN_TCP=1) and arm C
# (ARM_C_PORT=7000): no shm arm. The guest's shm monitors are never asked
# anything, but they are not silent: the polled monitor, 50 ms after its last
# request, sleeps in 10 ms steps -- a ~100 Hz wake-up source in every S, N and C
# guest, visible in the KVM counters of each boot's kvm-A-loopback files.
#
# EACH BOOT IS CHECKED for the services its image should run (from the guest's
# console), so a monitor that failed to start cannot pass as a condition:
#   A, B: neither shm service   S: the polled one   N: shmcfg + polled   C: both
#
# WHAT THIS DOES NOT CONTROL, stated: only the TCP group runs, while the
# notified-shm ladders interleaved shm/kick/db groups, fired a doorbell burst and
# ran host-side shm monitors and a second ivshmem server; each image embeds its
# own build of the monitor and echo server, so S - B is the polled monitor PLUS
# any other difference between ifs-shm.bin and ifs-udp.bin; two boots per
# condition; and K=4 by default is a diagnostic, not OD11's k >= 12.
#
#   OUTBASE=<dir> [IMG=~/output] [K=4] [SEQ="A B C C B A"] [SNAP=both|1] bash run-shift-isolation.sh
#   SNAP=1 runs only the KVM_STATS=1 ladder in each boot (the snapshots were shown
#   not to matter, and they record the idle guest's KVM activity).
#   DRY=1 ... prints the plan and exits (what the tests check)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
OUTBASE="${OUTBASE:?set OUTBASE to a fresh directory}"
IMG="${IMG:-$HOME/output}"
K="${K:-4}"
SEQ="${SEQ:-A B C C B A}"
DRY="${DRY:-0}"
SNAP="${SNAP:-both}"
IVSHMEM=/dev/shm/a6-ivshmem
IVSHMEM_SERVER=/tmp/a6-ivshmem.sock
KICK_SOCK=/tmp/a6-kick.sock
say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { say "FATAL: $*" >&2; exit 1; }

case "$K" in ''|*[!0-9]*) die "K='$K' is not a round count" ;; esac
for c in $SEQ; do case "$c" in A|B|C|S|N) ;; *) die "SEQ holds '$c'; conditions are A, B, C, S, N" ;; esac; done
case "$SNAP" in both|1) ;; *) die "SNAP='$SNAP' must be both or 1" ;; esac
# Drift cancels only in a mirrored sequence (A B C C B A, not A B C).
fwd="$(echo $SEQ)"
rev="$(printf '%s\n' $SEQ | tac | tr '\n' ' ')"
[ "${rev% }" = "$fwd" ] || [ "${ALLOW_UNBALANCED:-0}" = 1 ] \
	|| die "SEQ '$SEQ' is not a palindrome, so a linear drift would not cancel (ALLOW_UNBALANCED=1 to run it anyway)"

image_of() {
	case "$1" in
		A|B) echo "$IMG/ifs-udp.bin" ;;
		C) echo "$IMG/ifs-kick.bin" ;;
		S) echo "$IMG/ifs-shm.bin" ;;
		N) echo "$IMG/ifs-kick-nomon.bin" ;;
	esac
}
devices_of() { case "$1" in A) echo none ;; *) echo "ivshmem-doorbell+virtconsole" ;; esac; }
snap_order() {   # $1 boot index
	if [ "$SNAP" = 1 ]; then echo 1
	elif [ $(( $1 % 2 )) -eq 1 ]; then echo "0 1"
	else echo "1 0"; fi
}

# Plan: boot i, its condition, and the KVM_STATS order (0 first on odd boots).
plan() {
	local i=0 c
	for c in $SEQ; do
		i=$((i + 1))
		kv="$(snap_order "$i")"
		printf 'boot %d cond %s image %s devices %s kvm_stats %s\n' \
			"$i" "$c" "$(basename "$(image_of "$c")")" "$(devices_of "$c")" "$kv"
	done
}
if [ "$DRY" = 1 ]; then plan; exit 0; fi

[ -e "$OUTBASE" ] && die "$OUTBASE exists; use a fresh directory"
for c in $SEQ; do [ -r "$(image_of "$c")" ] || die "missing $(image_of "$c")"; done
[ -r "$IMG/disk-qemu" ] || die "missing $IMG/disk-qemu"
pgrep -x qemu-system-aar >/dev/null && die "a QEMU is already running; this script boots its own"
mkdir -p "$OUTBASE"
plan > "$OUTBASE/plan.txt"
for c in $SEQ; do image_of "$c"; done | sort -u | while IFS= read -r f; do sha256sum "$f"; done > "$OUTBASE/images.sha256"
sha256sum "$IMG/disk-qemu" >> "$OUTBASE/images.sha256"

stop_guest() {
	pkill -x qemu-system-aar 2>/dev/null || true
	for _ in $(seq 1 50); do pgrep -x qemu-system-aar >/dev/null || break; sleep 0.2; done
	pgrep -x qemu-system-aar >/dev/null && die "QEMU did not stop"
	# The ivshmem server exits with its peer 1 (QEMU); give it a moment, then check.
	for _ in $(seq 1 25); do [ -e "$IVSHMEM_SERVER" ] || break; sleep 0.2; done
	[ -e "$IVSHMEM_SERVER" ] && die "the ivshmem server outlived QEMU ($IVSHMEM_SERVER)"
	rm -f "$IVSHMEM" "$IVSHMEM_SERVER.ready" "$KICK_SOCK"
}
trap 'stop_guest || true' EXIT

# "guest up" means :7100 answers; the shm services start after it. Wait for the
# ones the image should run, then make sure no others did.
check_services() {   # $1 condition  $2 boot dir
	local c="$1" log="$2/guest-console.log" want got have
	case "$c" in A|B) want="" ;; S) want="shm" ;; N) want="cfg shm" ;; C) want="cfg shm kick" ;; esac
	have() {
		local x=""
		tr -d '\0' < "$log" | grep -aq 'shm configured:' && x="$x cfg"
		tr -d '\0' < "$log" | grep -aq 'serving shm on ivshmem' && x="$x shm"
		tr -d '\0' < "$log" | grep -aq 'serving shm-kick' && x="$x kick"
		echo "${x# }"
	}
	for _ in $(seq 1 30); do [ "$(have)" = "$want" ] && break; sleep 1; done
	got="$(have)"
	echo "want '$want' got '$got'" > "$2/services.txt"
	[ "$got" = "$want" ] || die "boot $2: services '$got', condition $c needs '$want'"
}

i=0
for c in $SEQ; do
	i=$((i + 1))
	d="$OUTBASE/b$i-$c"
	mkdir -p "$d"
	say "boot $i: condition $c ($(basename "$(image_of "$c")"), $(devices_of "$c"))"
	if [ "$(devices_of "$c")" = none ]; then
		( cd "$here" && IFS_BIN="$(image_of "$c")" DISK="$IMG/disk-qemu" LOG="$d/guest-console.log" \
			bash launch-qnx-kvm-bridged.sh ) > "$d/guest-launch.log" 2>&1 || { cat "$d/guest-launch.log"; die "boot $i failed"; }
	else
		( cd "$here" && IFS_BIN="$(image_of "$c")" DISK="$IMG/disk-qemu" LOG="$d/guest-console.log" \
			IVSHMEM="$IVSHMEM" IVSHMEM_SERVER="$IVSHMEM_SERVER" KICK_SOCK="$KICK_SOCK" \
			bash launch-qnx-kvm-bridged.sh ) > "$d/guest-launch.log" 2>&1 || { cat "$d/guest-launch.log"; die "boot $i failed"; }
	fi
	check_services "$c" "$d"
	for kv in $(snap_order "$i"); do
		say "  ladder, KVM_STATS=$kv"
		( cd "$here" && OUT="$d/kvm$kv" KVM_STATS="$kv" UDP_IN_TCP=1 ARM_C_PORT=7000 CSTATE=shallow K="$K" \
			bash run-ladder.sh ) > "$d/run-kvm$kv.log" 2>&1 || { tail -20 "$d/run-kvm$kv.log"; die "ladder failed in boot $i"; }
	done
	stop_guest
done
trap - EXIT
say "done: $(echo $SEQ | wc -w) boots under $OUTBASE"
