#!/usr/bin/env bash
# partition_cycle.sh -- reboot the board, then run one board boot's harness in ONE SSH session, for
# each tag in turn: the board-boot machinery of the harnesses that need fresh boots (run-randomise.sh
# by default; run-boots.sh names this script). Run on the PC, by the owner, at the plug. Phase 3b /
# A6; reviewed 2026-10-17 from the local orchestrator the partition test used on R36, which no branch
# held and which was never run on R39.
#
#   HOST=user@address KEY=~/.ssh/<key> REMOTE=<the checkout on the board> OWNER_AT_PLUG=1 \
#       [BOARD_ENV="SCHEDULE=~/a6-randomise/schedule.txt IMG=~/output"] [FIRST_IS_CURRENT=1] \
#       [EXPECT_RESET='<what the smoke boot read>'] [LOGDIR=<a directory outside any work tree>] \
#       bash partition_cycle.sh b0 b1 b2 b3 b4 b5 b6
#
# For each tag (the first one on the current boot when FIRST_IS_CURRENT=1, without a reboot):
#   1. one SSH call: the boot id read; refused (exit 3) while a platform-quiesce stop is outstanding
#      (its marker is still there: the restore must come before every reboot) or a harness holds the
#      run lock; else sync, and `sudo -n systemctl reboot` two seconds after the call returns;
#   2. no login while the board reboots: port 22 is only connected to (PORT_CHECK), every POLL_S
#      seconds, until it closes (at most DOWN_TRIES times) and then until it opens again (at most
#      UP_TRIES times); a board that does not go down, or does not come back, stops the cycle;
#   3. ONE SSH session for the board boot, under SESSION_MAX_S, which first, before anything else
#      runs: reads the boot id, and after a reboot of this cycle stops (exit 6) on the boot the
#      reboot was asked on -- no reboot happened, and the board boot would not be a fresh one; reads
#      reset_reason, then pstore, as root (section 10), archives a non-empty pstore under
#      ~/partition-cycle-pstore on the board, and stops (exit 7) when either cannot be read, when
#      pstore holds a crash record (dmesg-*), or when reset_reason is not the planned reboot's; then
#      the board's own bounded wait until its uptime reaches WAIT_UPTIME_S (SETTLE_TRIES rounds of
#      ten seconds); setup-bridge-orin.sh (a reboot drops br0 and tap-qnx); then BOOT_TAG=<tag> and
#      BOARD_ENV's words before the harness, under the board's own `timeout RUN_MAX_S` (its TERM runs
#      the harness's cleanup, which restores the board).
# THE PLANNED REBOOT'S reset_reason is not known on R39 before the board shows it, so the smoke boot
# settles it: the reset_reason that b0's session reads after a reboot of this cycle is the one every
# later session must read. A later cycle is given it as EXPECT_RESET (printed when b0 settles it). A
# scored board boot (b1 .. b6) is refused before any call while no value is settled or given.
# Any failure stops the cycle with no further reboot: the stop rule -- the owner reads
# reset_reason and pstore and decides. Each call's output goes to LOGDIR on the PC (by default
# ~/partition-cycle/<UTC time>), never into the repository: a LOGDIR inside this script's
# repository, or inside any work tree, is refused before any call (the session logs carry the
# harness's summary, figures included).
#
# WHAT IT NEVER DOES: touch a boot entry, the bootloader, the kernel command line or nvpmodel. It
# reboots into whatever the board boots by default and changes nothing else; the harness checks the
# shipped command line itself (M8). It carries no address, user or key of its own: HOST, KEY and
# REMOTE are given, or it refuses.
#
# THE REVIEW, line by line, of the R36 orchestrator (scratchpad-backup-20261011/partition_cycle.sh):
#   - removed: every call of partition-boot.sh (install, default, remove, status), which switched the
#     boot entry between two kernel command lines, and the restore that switched it back -- this
#     script runs the default entry only;
#   - removed: a hard-coded user, LAN address and key path; they are given at run time;
#   - removed: the run-partition.sh step and its QEMU launch and kill (`pgrep -f` matched its own
#     shell); the harness now launches and stops its own guest;
#   - replaced: the reboot wait (a fixed 90 s sleep, then up to 40 SSH logins 15 s apart) by TCP
#     connects with bounded tries, and a boot id compared, so no login polls a booting board and a
#     reboot that never happened is caught;
#   - kept, bounded: the in-session settle wait (now SETTLE_TRIES rounds) and the per-boot deadline
#     (now RUN_MAX_S on the board and SESSION_MAX_S around the session);
#   - added: the refusal to reboot while a platform-quiesce stop or a harness's run lock is
#     outstanding, and OWNER_AT_PLUG=1, without which nothing is called;
#   - added: the session's first reads (the boot id, reset_reason, pstore) and their stops, before
#     the settle wait, the bridge and the harness; the planned reboot's reset_reason settled on the
#     smoke boot; the logs kept out of every work tree.
# It has run only against the stubs of tests/test_partition_cycle.py and its stand-in board.
set -u

HOST="${HOST:-}"
KEY="${KEY:-}"
REMOTE="${REMOTE:-}"
OWNER_AT_PLUG="${OWNER_AT_PLUG:-}"
BOARD_ENV="${BOARD_ENV:-}"
FIRST_IS_CURRENT="${FIRST_IS_CURRENT:-0}"
HARNESS="${HARNESS:-orin-native/gpu-concurrency/run-randomise.sh}"
POLL_S="${POLL_S:-5}"
DOWN_TRIES="${DOWN_TRIES:-36}"
UP_TRIES="${UP_TRIES:-180}"
WAIT_UPTIME_S="${WAIT_UPTIME_S:-660}"
SETTLE_TRIES="${SETTLE_TRIES:-120}"
RUN_MAX_S="${RUN_MAX_S:-5400}"
SESSION_MAX_S="${SESSION_MAX_S:-9000}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"
LOGDIR="${LOGDIR:-$HOME/partition-cycle/$(date -u +%Y%m%dT%H%M%SZ)}"
PORT_CHECK="${PORT_CHECK:-}"
EXPECT_RESET="${EXPECT_RESET:-}"
RESET_REASON_PATH=/sys/devices/platform/bus@0/c360000.pmc/reset_reason
RESET_RX='^[A-Za-z0-9_.:,=@+ -]+$'      # a reset_reason as it is put, single-quoted, on the board's command line
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
die() { echo "partition_cycle: $*" >&2; exit 1; }

# The absolute form of a path that may not exist yet: its nearest existing ancestor resolved, the rest
# appended.
abs_path() {        # $1 path
	local p="$1" rest=""
	case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
	while [ ! -d "$p" ]; do
		rest="/${p##*/}$rest"
		p="${p%/*}"
		[ -n "$p" ] || p=/
	done
	p="$(cd "$p" && pwd -P)"
	echo "${p%/}$rest"
}

# ---------------------------------------------------------------- refusals, before any call
[ "$OWNER_AT_PLUG" = 1 ] || die "OWNER_AT_PLUG=1 says the owner is at the board's plug for the whole cycle: a reboot can hang, and only a power cycle recovers it"
[[ "$HOST" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.:_-]+$ ]] || die "HOST='$HOST' is not user@address: give the board's login (it is never written into this script)"
[ -n "$KEY" ] && [ -r "$KEY" ] || die "KEY='$KEY' is not a readable key file"
[[ "$REMOTE" =~ ^[~A-Za-z0-9_./-]+$ ]] || die "REMOTE='$REMOTE' is not a path on the board (the deployed checkout; no spaces or quotes)"
[[ "$HARNESS" =~ ^[A-Za-z0-9_./-]+$ ]] || die "HARNESS='$HARNESS' is not a path below REMOTE"
for w in $BOARD_ENV; do
	[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[~A-Za-z0-9_./:@%+,-]*$ ]] \
		|| die "BOARD_ENV word '$w' is not NAME=value of plain characters (it is put on the board's command line)"
	case "$w" in BOOT_TAG=*) die "BOARD_ENV may not set BOOT_TAG: the tags are the arguments" ;; esac
done
for v in DOWN_TRIES UP_TRIES WAIT_UPTIME_S SETTLE_TRIES RUN_MAX_S SESSION_MAX_S; do
	[[ "${!v}" =~ ^[1-9][0-9]*$ ]] || die "$v='${!v}' is not a positive whole number"
done
[[ "$POLL_S" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "POLL_S='$POLL_S' is not a number of seconds"
case "$FIRST_IS_CURRENT" in 0|1) ;; *) die "FIRST_IS_CURRENT='$FIRST_IS_CURRENT' must be 0 or 1" ;; esac
[ $# -gt 0 ] || die "name the board boots to run, e.g. b1 b2 b3 b4 b5 b6"
seen=" "
for t in "$@"; do
	case "$t" in b[0-6]) ;; *) die "'$t' is not a board boot (b0, the smoke, or b1 .. b6)" ;; esac
	case "$seen" in *" $t "*) die "$t is named twice: a board boot is run once" ;; esac
	seen="$seen$t "
done
[ -z "$EXPECT_RESET" ] || [[ "$EXPECT_RESET" =~ $RESET_RX ]] \
	|| die "EXPECT_RESET='$EXPECT_RESET' is not plain text (it is put on the board's command line)"
# A scored board boot needs the planned reboot's reset_reason: given, or settled by b0 after a reboot of
# this cycle, earlier in the list.
if [ -z "$EXPECT_RESET" ]; then
	settled=0; first=1
	for t in "$@"; do
		if [ "$t" = b0 ]; then
			[ "$first" = 1 ] && [ "$FIRST_IS_CURRENT" = 1 ] || settled=1
		elif [ "$settled" = 0 ]; then
			die "$t is a scored board boot, and no reset_reason of a planned reboot is settled: run the smoke b0 first in this cycle, after its reboot, or give EXPECT_RESET=<what the smoke boot read>"
		fi
		first=0
	done
fi
# The logs carry the harness's summary, figures included: never into this repository or any work tree.
case "/$LOGDIR/" in */../*) die "LOGDIR='$LOGDIR' has a '..' in it: give it plainly" ;; esac
LOG_ABS="$(abs_path "$LOGDIR")"
REPO_ROOT="$(cd "$here/../.." && pwd -P)"
if [ -e "$REPO_ROOT/orin-native/gpu-concurrency/partition_cycle.sh" ]; then
	case "$LOG_ABS/" in
		"${REPO_ROOT%/}/"*) die "LOGDIR '$LOGDIR' is inside this script's repository ($REPO_ROOT): results stay out of it -- give one outside, or leave LOGDIR unset for ~/partition-cycle/<time>" ;;
	esac
fi
d="$LOG_ABS"
while [ -n "$d" ] && [ "$d" != / ]; do
	[ ! -e "$d/.git" ] || die "LOGDIR '$LOGDIR' is inside a work tree ($d): results stay out of every repository"
	d="${d%/*}"
done
ADDR="${HOST#*@}"
if [ -n "$PORT_CHECK" ]; then
	say "WARNING: PORT_CHECK overridden to $PORT_CHECK -- test use only"
fi
mkdir -p "$LOGDIR" || die "cannot create $LOGDIR"

SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30)

port_open() {       # a TCP connect to port 22, never a login
	if [ -n "$PORT_CHECK" ]; then "$PORT_CHECK" "$ADDR" 22; return; fi
	timeout 3 bash -c 'exec 3<>"/dev/tcp/$1/22"' _ "$ADDR" 2>/dev/null
}

wait_port() {       # $1 open|closed  $2 tries -> 0 once the port reads $1
	local i
	for ((i = 0; i < $2; i++)); do
		if port_open; then [ "$1" = open ] && return 0; else [ "$1" = closed ] && return 0; fi
		sleep "$POLL_S"
	done
	return 1
}

# The reboot call: the boot id, the refusals, sync, and the reboot after the call has returned.
REBOOT_CMD='set -u
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
m="${XDG_STATE_HOME:-$HOME/.local/state}/platform-quiesce.active"
[ ! -e "$m" ] || { echo "partition_cycle: a platform-quiesce stop is outstanding ($m): restore before any reboot" >&2; exit 3; }
if [ -e "'"$LOCK"'" ] && ! flock -n "'"$LOCK"'" true; then echo "partition_cycle: a harness holds '"$LOCK"'" >&2; exit 3; fi
sync
nohup sh -c "sleep 2; sudo -n systemctl reboot" > /dev/null 2>&1 < /dev/null &
echo reboot-asked'

# The session of a board boot. First, before anything else runs (section 10): the boot id, and the
# stop when it is the one the reboot was asked on; reset_reason, then pstore, as root, pstore archived
# on the board, and the stops on either. Then the settle wait, the bridge and the harness.
session_cmd() {     # $1 tag  $2 the boot id the reboot was asked on ("" when none was)  $3 the planned reboot's reset_reason ("" when not settled)
	printf '%s\n' 'set -u' \
		'id="$(cat /proc/sys/kernel/random/boot_id)"' \
		'echo "boot_id=$id"'
	[ -z "$2" ] || printf '%s\n' \
		"[ \"\$id\" != '$2' ] || { echo \"partition_cycle: this is boot \$id, the boot the reboot was asked on: no reboot happened\" >&2; exit 6; }"
	printf '%s\n' \
		"rr=\"\$(sudo -n cat $RESET_REASON_PATH 2>/dev/null | tr -cd '[:print:]')\"" \
		'echo "reset_reason=$rr"' \
		'[ -n "$rr" ] || { echo "partition_cycle: cannot read reset_reason with sudo -n" >&2; exit 7; }' \
		'p="$(sudo -n ls -A /sys/fs/pstore)" || { echo "partition_cycle: cannot read /sys/fs/pstore with sudo -n" >&2; exit 7; }' \
		'p="$(printf "%s" "$p" | tr "\n" " ")"' \
		'echo "pstore=${p:-empty}"' \
		"if [ -n \"\$p\" ]; then a=\"\$HOME/partition-cycle-pstore/$1-\$(date -u +%Y%m%dT%H%M%SZ)\"; mkdir -p \"\$a\" && sudo -n cp -a /sys/fs/pstore/. \"\$a/\" || { echo \"partition_cycle: pstore could not be archived\" >&2; exit 7; }; echo \"pstore archived in \$a\"; fi" \
		'case " $p " in *" dmesg-"*) echo "partition_cycle: pstore holds a crash record: the stop rule -- the owner reads it and decides" >&2; exit 7 ;; esac'
	[ -z "$3" ] || printf '%s\n' \
		"[ \"\$rr\" = '$3' ] || { echo \"partition_cycle: reset_reason '\$rr' is not the planned reboot's '$3' (settled on the smoke boot): the stop rule -- the owner decides\" >&2; exit 7; }"
	printf '%s\n' 'n=0' \
		"while [ \"\$(cut -d. -f1 /proc/uptime)\" -lt $WAIT_UPTIME_S ]; do" \
		"	n=\$((n + 1)); [ \"\$n\" -le $SETTLE_TRIES ] || { echo \"partition_cycle: the uptime did not reach $WAIT_UPTIME_S s\" >&2; exit 4; }" \
		'	sleep 10' \
		'done' \
		"cd $REMOTE || exit 1" \
		"sudo -n bash scripts/orin/setup-bridge-orin.sh > /tmp/partition-cycle-bridge-$1.log 2>&1 || { tail -5 /tmp/partition-cycle-bridge-$1.log >&2; exit 5; }" \
		"BOOT_TAG=$1${BOARD_ENV:+ $BOARD_ENV} timeout $RUN_MAX_S bash $HARNESS < /dev/null"
}

# ---------------------------------------------------------------- the cycle
last_id=""
expected="$EXPECT_RESET"
first=1
for t in "$@"; do
	rebooted=0
	if [ "$first" = 1 ] && [ "$FIRST_IS_CURRENT" = 1 ]; then
		say "== $t: the current boot, no reboot"
	else
		say "== $t: reboot"
		timeout 60 ssh "${SSH_OPTS[@]}" "$HOST" "$REBOOT_CMD" > "$LOGDIR/$t-reboot.log" 2>&1 \
			|| die "the reboot before $t was refused or failed (see $LOGDIR/$t-reboot.log): stop"
		last_id="$(sed -n 's/^boot_id=//p' "$LOGDIR/$t-reboot.log" | head -1)"
		[[ "$last_id" =~ ^[0-9a-f-]+$ ]] \
			|| die "the reboot before $t was asked, but the boot id it was asked on reads '$last_id': stop -- the owner at the plug decides"
		rebooted=1
		wait_port closed "$DOWN_TRIES" || die "the board did not go down after the reboot before $t was asked: stop"
		say "$t: the board is down; waiting for port 22"
		wait_port open "$UP_TRIES" || die "the board did not come back after the reboot before $t: the owner at the plug decides (reset_reason and pstore first)"
		say "$t: port 22 is open"
	fi
	first=0
	say "$t: one session -- the first reads, settle, bridge, the harness"
	if [ "$rebooted" = 1 ]; then asked="$last_id"; else asked=""; fi
	timeout "$SESSION_MAX_S" ssh "${SSH_OPTS[@]}" "$HOST" "$(session_cmd "$t" "$asked" "$expected")" > "$LOGDIR/$t-session.log" 2>&1
	rc=$?
	id="$(sed -n 's/^boot_id=//p' "$LOGDIR/$t-session.log" | head -1)"
	if [ -n "$asked" ] && [ "$id" = "$asked" ]; then
		die "$t ran on boot $id, the boot the reboot was asked on: no reboot happened -- stop"
	fi
	[ "$rc" != 7 ] || die "board boot $t stopped at its first reads, before the settle wait, the bridge and the harness (reset_reason or pstore; see $LOGDIR/$t-session.log): stop -- the owner reads them and decides; no reboot follows"
	[ "$rc" = 0 ] || die "board boot $t failed (exit $rc; see $LOGDIR/$t-session.log): stop -- the owner reads reset_reason and pstore and decides; no reboot follows"
	if [ -z "$expected" ] && [ "$t" = b0 ] && [ "$rebooted" = 1 ]; then
		expected="$(sed -n 's/^reset_reason=//p' "$LOGDIR/$t-session.log" | head -1)"
		[[ "$expected" =~ $RESET_RX ]] \
			|| die "the smoke boot's reset_reason could not be read from $LOGDIR/$t-session.log ('$expected'): stop"
		say "the planned reboot's reset_reason, settled on the smoke boot: '$expected' (give a later cycle EXPECT_RESET='$expected')"
	fi
	last_id="$id"
	say "$t done"
done
say "cycle done: $*"
