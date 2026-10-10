#!/bin/bash
# User-data for one bare-metal A6 ladder session: it arms the session's two self-termination
# nets before anything else, then installs what the run needs.
# --instance-initiated-shutdown-behavior terminate turns a poweroff from inside the instance
# into a termination, which bounds the bill if the operator is gone.
#
# TWO NETS (2026-10-10). A scheduled shutdown is a wall-clock time, and the wall clock of a
# freshly booted instance may still be stepped: a step after the schedule is made moves the
# time left by the size of the step. So:
#   1. A MONOTONIC timer, first: a transient systemd timer that powers the instance off when
#      the time since boot reaches the uptime now plus the session's minutes. No step of the
#      wall clock moves it, in either direction. It is --on-boot, an absolute time since
#      boot, and not --on-active: systemd takes "now" as the base of an on-active timer again
#      whenever the manager re-reads its units (timer.c: timer_coldplug, then the
#      TIMER_ACTIVE case of timer_enter_waiting), so a daemon-reload, which a package's
#      install script may run, would start that one counting afresh.
#   2. The WALL-CLOCK poweroff that drive-metal.sh `wait` has always read: logind keeps one
#      scheduled shutdown, as an absolute time, in /run/systemd/shutdown/scheduled. It is
#      scheduled only after a bounded wait for the kernel to call its clock synchronised, for
#      what is then left of the session's minutes, and the deadline goes to disk from the
#      same read. Scheduled before that, it would be moved by the step that sets the clock.
#      The wait is bounded three ways: by the seconds slept, by the uptime spent, and each
#      read of the clock's state by coreutils' timeout (it asks systemd over a bus).
# If systemd-run is missing or refuses, the wall-clock poweroff is scheduled at once, as this
# script did before it had two nets, so the instance never has less of a net than it had;
# after the wait it is scheduled again, and a second schedule replaces the first in logind
# with no moment between them without one. `wait` then refuses the session: it goes on only
# if SHUTDOWN_ARMED exists, the timer unit is active with no more than the session's minutes
# left, the scheduled poweroff is 61-91 minutes ahead and the per-boot re-arm is installed;
# otherwise it terminates the instance.
#
# SURVIVES A REBOOT. Both nets live in memory: a pending shutdown in /run, which a reboot
# empties, and the transient timer in the service manager. User-data runs once per instance
# -- so on a kernel that reboots when it panics (kernel.panic not 0; panic=-1 on the command
# line sets it) a host panic would reboot into an unbounded instance. So the deadline is
# written to disk as an absolute time, and a per-boot script arms both nets again for the
# remainder, or powers off at once if the deadline has passed or cannot be read. Both are
# written right after the first net, before anything is asked of the system that could stand
# still: that is where they stood before there were two nets. In cloud-init's final stage
# the per-boot scripts run BEFORE user-data (cloud.cfg: scripts_per_boot, then
# scripts_user), so on the first boot the script is not there yet when its turn comes, and
# nothing is armed twice. The deadline on disk is itself a wall-clock time: a clock that is
# wrong at a reboot and is not set lets that boot run past the session's end, by the size of
# the error and never by more than the session's minutes. What neither net can bound is a
# kernel that hangs without rebooting, which is also what a panic is where kernel.panic is
# 0; README.md says both. Which of the two this image's kernel does is not assumed here:
# remote-ladder.sh's setup reads it, prints it, and records it in host-facts.txt.
#
# EVIDENCE. $FACTS records the wall clock, the uptime and whether the kernel calls its clock
# synchronised, at the first arming and again at the schedule; `wait` prints it beside the
# same reads taken then, whether it goes on or refuses.
#
# The 90 here and SHUTDOWN_MIN_EXPECTED in drive-metal.sh must agree
# (tests/test_aws_tooling.py checks it).
M=/var/lib/cloud/instance
MIN=90
NET=qnx-metal-monotonic
FACTS=/var/lib/qnx-metal-arming
DEADLINE=/var/lib/qnx-metal-deadline
PERBOOT=/var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh
SYNC_WAIT_S=60
SYNC_POLL_S=3
SYNC_READ_S=10
UP=$(</proc/uptime)
UP=${UP%%[!0-9]*}
if systemd-run --quiet --unit="$NET" --on-boot=$(( ${UP:-0} + MIN * 60 )) --timer-property=AccuracySec=1s systemctl poweroff; then
	echo monotonic > "$M/SHUTDOWN_ARMED"
else
	shutdown -h +$MIN "auto-terminate: A6 ladder session budget" && echo wall-clock > "$M/SHUTDOWN_ARMED"
fi

# Reboot safety next, before anything is asked of the system that could stand still: the
# deadline as this first read of the wall clock gives it, and the per-boot script. An instance
# that dies or reboots from here on is bounded by them; the deadline is written again after
# the wait below, from the later read.
WALL=$(date +%s)
echo $(( ${WALL:-0} + MIN * 60 )) > "$DEADLINE"
mkdir -p "${PERBOOT%/*}"
printf '#!/bin/sh\nMAX=%s\n' "$MIN" > "$PERBOOT"
cat >> "$PERBOOT" <<'EOS'
# Written by user-data, with MAX the session's minutes. After a reboot nothing of the first
# arming is left in memory, so both nets are armed again for what is left of the deadline on
# disk: the wall-clock poweroff for that remainder (an absolute time, the deadline as
# written), and the monotonic timer for the same, but never for more than the session's
# minutes: a wall clock that is behind at this boot must not lengthen it. A deadline that
# has passed powers off at once. So does a deadline, or a clock, that is not a plain number
# of seconds (missing, empty, a leading zero, too long): user-data wrote the deadline before
# this script existed, so it was lost, and such a text never reaches the arithmetic below,
# which would stop on it with nothing armed.
now=$(date +%s)
d=$(cat /var/lib/qnx-metal-deadline 2>/dev/null)
for v in "$now" "$d"; do
	case "$v" in
		''|*[!0-9]*|0?*|???????????*) shutdown -h now "auto-terminate: no readable session deadline or clock"; exit 0 ;;
	esac
done
left=$(( (d - now) / 60 ))
if [ "$left" -le 0 ]; then
	shutdown -h now "auto-terminate: session deadline passed"
	exit 0
fi
mono=$left
[ "$mono" -le "$MAX" ] || mono=$MAX
read -r up _ < /proc/uptime
up=${up%%[!0-9]*}
systemd-run --quiet --unit=qnx-metal-monotonic --on-boot=$(( ${up:-0} + mono * 60 )) --timer-property=AccuracySec=1s systemctl poweroff
shutdown -h +"$left" "auto-terminate: session deadline, re-armed after a reboot"
EOS
chmod 755 "$PERBOOT"

# The facts of this arming: the wall clock and the uptime read above, and synced: what the
# kernel says of its clock (adjtimex, which systemd-timedated reads for NTPSynchronized),
# whichever service disciplines it. timedatectl is systemd's own and timeout coreutils', so no
# package is needed; without timeout, or with a read it has to cut, the answer is "unknown".
synced() {
	case "$(timeout "$SYNC_READ_S" timedatectl show -p NTPSynchronized 2>/dev/null)" in
		NTPSynchronized=yes) echo yes ;;
		NTPSynchronized=no) echo no ;;
		*) echo unknown ;;
	esac
}
SYNCED=$(synced)
ARMED=$(<"$M/SHUTDOWN_ARMED")
printf '%s\n' "minutes=$MIN" "arm_wall=${WALL:-unread}" "arm_uptime=${UP:-unread}" "arm_synced=$SYNCED" \
	"arm_net=${ARMED:-none}" > "$FACTS"

# A bounded wait for the clock to be synchronised: by the seconds slept, and by the uptime
# spent, so that a read that is slow to answer cannot stretch it either (and timeout holds
# each read to SYNC_READ_S).
SLEPT=0
T=$UP
while [ "$SYNCED" != yes ] && [ "$SLEPT" -lt "$SYNC_WAIT_S" ] && [ $(( ${T:-0} - ${UP:-0} )) -lt "$SYNC_WAIT_S" ]; do
	sleep "$SYNC_POLL_S"
	SLEPT=$(( SLEPT + SYNC_POLL_S ))
	SYNCED=$(synced)
	T=$(</proc/uptime)
	T=${T%%[!0-9]*}
done

# Synchronised or not: the wall-clock poweroff, for the session's minutes less the time
# already spent since the monotonic net was armed (rounded up, so that it is never the later
# of the two), and the deadline on disk from the same read of the wall clock.
WALL=$(date +%s)
T=$(</proc/uptime)
T=${T%%[!0-9]*}
SPENT=$SLEPT
[ -n "$UP" ] && [ -n "$T" ] && SPENT=$(( T - UP ))
LEFT=$(( MIN - (SPENT + 59) / 60 ))
[ "$LEFT" -ge 1 ] || LEFT=1
[ "$LEFT" -le "$MIN" ] || LEFT=$MIN
if shutdown -h +$LEFT "auto-terminate: A6 ladder session budget"; then
	[ "$ARMED" = wall-clock ] || echo wall-clock >> "$M/SHUTDOWN_ARMED"
	NETW=wall-clock
else
	NETW=failed
fi
echo $(( ${WALL:-0} + LEFT * 60 )) > "$DEADLINE.new" && mv "$DEADLINE.new" "$DEADLINE"
printf '%s\n' "sched_wall=${WALL:-unread}" "sched_uptime=${T:-unread}" "sched_synced=$SYNCED" \
	"sync_wait=$([ "$SYNCED" = yes ] && echo synchronised || echo bound)" "sync_wait_s=$SLEPT" \
	"sched_left_min=$LEFT" "deadline=$(( ${WALL:-0} + LEFT * 60 ))" "sched_net=$NETW" >> "$FACTS"

# Everything the run needs, installed before the operator logs in. A failure is
# written down, never papered over with a readiness file.
#
# ipxe-qemu (2026-10-08) is named because qemu-system-arm only recommends it and
# nothing recommended is installed here. With it the instance and the Orin carry
# the same three QEMU packages: qemu-system-arm, qemu-utils, ipxe-qemu. Not the
# same set: the Orin also has qemu-efi-aarch64, another recommended package,
# which a guest started with -kernel does not use.
set -e
trap 'touch "$M/PROVISION_FAILED"' ERR
export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=300 update -y
apt-get -o DPkg::Lock::Timeout=300 install -y --no-install-recommends \
  qemu-system-arm qemu-utils ipxe-qemu bridge-utils iproute2 \
  build-essential python3 net-tools gawk
usermod -aG kvm ubuntu
touch "$M/PROVISIONED"
