#!/usr/bin/env bash
# drive-metal.sh -- drive ONE bare-metal AWS session for an A6 ladder, from the
# operator's machine (Git Bash on Windows, or Linux; GNU sed and Python 3 needed).
#
#   drive-metal.sh launch        run-instances, self-terminating; root volume read back
#   drive-metal.sh wait          until provisioned; PROVES both self-termination nets are armed
#   drive-metal.sh upload        repo tarball, remote-ladder.sh, capture.py, image, gzipped disk
#   drive-metal.sh run PHASE     remote-ladder.sh PHASE (setup|quiesce|launch|ladder|launch-live|liveness|launch-stamp|stamp|metal|capture)
#   drive-metal.sh fetch         pub.tgz back, hash-verified, then leak-scanned
#   drive-metal.sh terminate     terminate-instances, confirmed
#   drive-metal.sh verify        nothing running|pending, ours shutting-down|terminated, no
#                                available (orphaned) volume -- billing has stopped
#   drive-metal.sh verify-vol    our root volume is gone (once the instance is terminated)
#   drive-metal.sh clear         empty the session state -- only after verify-vol passed
#
# An earlier form of this script drove the 2026-09-22 a1.metal session
# (record `20260922T-a6-a1metal-kick`, held locally); see README.md for what changed.
#
# FAILURE POLICY. From the moment an instance id exists until the safety net is
# proven armed (launch, wait), ANY failure terminates the instance and confirms the
# termination; if the termination cannot be confirmed the script says so loudly. After
# `wait`, a failing step (upload, run, fetch) leaves the instance to the proven
# self-termination, or to `terminate`.
#
# CONFIGURATION, none of it in the repo: METAL_KEY_NAME, METAL_PEM, METAL_SG_NAME, and
# METAL_REPO_TAR / METAL_IFS / METAL_DISK_GZ -- in the environment or in
# scripts/aws/.env.local, which .gitignore keeps out (see .env.example).
#
# SESSION STATE (instance id, volume id, address, known_hosts) lives in METAL_STATE, by
# default outside the repo, and the script refuses a state or fetch directory inside
# the repo. Everything printed, stderr included, goes through red().
#
# THE IMAGE (2026-10-08). The default is Canonical's public Ubuntu 24.04 arm64 server image for
# eu-central-1, pinned by id: its archive gives the QEMU release the Orin runs since its upgrade
# to L4T R39. The image's own kernel is used, whatever its series: `run setup` prints and records
# the kernel release, CONFIG_HZ and the tick handler's name before it checks anything. One
# release is not one package build: user-data installs the day's qemu-system-arm, and the Orin
# keeps the build it has. METAL_QEMU_PKG (optional) is the package version a session expects, the
# other host's on the day: exported for the session, as a session's own METAL_REPO_TAR is, and not
# kept in .env.local, where the last session's value would be the next one's. `launch` refuses a
# value that is not a package version, while nothing is billed; `run setup` carries it to the
# instance, which refuses when dpkg has another, before it makes a record and before any harness.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# METAL_NO_ENV_LOCAL: the tests must not pick up a developer's local configuration.
# The environment wins over the file: every METAL_* value already exported is put back
# after .env.local is read. On 2026-09-25 the file's METAL_REPO_TAR silently replaced
# the one given on the command line, and an older session's repository was uploaded.
if [ -z "${METAL_NO_ENV_LOCAL:-}" ] && [ -r "$HERE/.env.local" ]; then
	declare -A _given=()
	for _v in $(env | sed -n 's/^\(METAL_[A-Z0-9_]*\)=.*/\1/p'); do _given[$_v]="${!_v}"; done
	. "$HERE/.env.local"
	for _v in "${!_given[@]}"; do printf -v "$_v" '%s' "${_given[$_v]}"; export "$_v"; done
	unset _given _v
fi
AWS="${AWS:-aws}"
REGION="${METAL_REGION:-eu-central-1}"
AMI="${METAL_AMI:-ami-0d9429f78b33241cd}"      # ubuntu-noble-24.04-arm64-server-20260923 (public)
TYPE="${METAL_TYPE:-a1.metal}"
SHUTDOWN_MIN_EXPECTED="${SHUTDOWN_MIN_EXPECTED:-90}"   # must match userdata.sh (a test checks it)
# Polling pace and patience; the tests shrink them.
POLL_S="${METAL_POLL_S:-5}"
IP_WAIT_S="${METAL_IP_WAIT_S:-300}"
PROV_WAIT_S="${METAL_PROV_WAIT_S:-900}"
CONFIRM_TRIES="${METAL_CONFIRM_TRIES:-6}"
READBACK_TRIES="${METAL_READBACK_TRIES:-30}"
PHASES="setup quiesce launch ladder launch-live liveness launch-stamp stamp metal someip harness capture"

# Local paths in POSIX form: a pasted C:\... path would make scp and tar read "C:" as
# a host, and sha256sum escape the backslashes in its output.
posix_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s' "$1"; fi; }
STATE="$(posix_path "${METAL_STATE:-$HOME/.cache/qnx-metal-session}")"

# Exact local values that must never reach a transcript, longest first.
red_literals() {
	local v forms=()
	for v in "${METAL_PEM:-}" "$HOME" "$STATE"; do
		[ -n "$v" ] || continue
		forms+=("$v")
		if command -v cygpath >/dev/null 2>&1; then
			forms+=("$(cygpath -u "$v" 2>/dev/null || true)" "$(cygpath -m "$v" 2>/dev/null || true)" "$(cygpath -w "$v" 2>/dev/null || true)")
		fi
	done
	[ -n "${METAL_PEM:-}" ] && forms+=("$(basename "$METAL_PEM")")
	forms+=("${METAL_KEY_NAME:-}" "${METAL_SG_NAME:-}" "${USER:-}" "${USERNAME:-}")
	printf '%s\n' "${forms[@]}" | awk 'length($0) >= 3' | awk '{ print length($0) "\t" $0 }' | sort -rn | cut -f2- | uniq
}
# The literals first, then every AWS shape. THE 12-DIGIT RULE (an account id) takes a run of exactly 12 digits that
# stands alone. A letter or a digit on either side makes the run part of a longer token, and a "." before it makes it
# a fraction: both stay. FOUND 2026-10-04: a letter on either side did not count, so a sha256 that holds 12
# digits in a row (about 1 in 35 does) printed as ab<account>cd... in the inputs.txt upload shows. redact-aws.sh keeps
# the same runs; it also keeps one beside - or _, and the integer part of a decimal, which red() masks: its output is
# a transcript, never data, so masking more costs nothing here.
red() {
	local s lit
	s="$(cat; printf x)"; s="${s%x}"
	while IFS= read -r lit; do
		[ -n "$lit" ] && s="${s//"$lit"/<local>}"
	done < <(red_literals)
	printf '%s' "$s" | sed -E '
		s#[^ :]*[/\\]\.ssh[/\\][^ ]*#<key>#g
		s/ec2-[0-9]+-[0-9]+-[0-9]+-[0-9]+[.][a-z0-9.-]+/<host>/g
		s/ip-[0-9]+-[0-9]+-[0-9]+-[0-9]+([.][a-z0-9.-]+)?/<host>/g
		s/(^|[^A-Za-z0-9])(i|vol|sg|subnet|vpc|eni|r|snap)-[0-9a-f]{8,}/\1<\2-id>/g
		s/arn:aws[^ "]*/<arn>/g
		:a
		s/(^|[^0-9A-Za-z.])[0-9]{12}([^0-9A-Za-z]|$)/\1<account>\2/
		ta
		s/([0-9]{1,3}\.){3}[0-9]{1,3}/<ip>/g
		s/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/<mac>/g
		s/[0-9a-fA-F]{0,4}(:[0-9a-fA-F]{0,4})*::[0-9a-fA-F:]*/<ipv6>/g
		s/([0-9a-fA-F]{1,4}:){5,7}[0-9a-fA-F]{1,4}/<ipv6>/g'
}
say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" | red; }
die() { say "FATAL: $*" >&2; exit 1; }

# Minutes until the scheduled poweroff, from the text of
# /run/systemd/shutdown/scheduled plus a NOW=<epoch> line; fails unless it is a
# poweroff. Pure, so the tests call it directly. Both numbers are read in base ten: a
# leading zero makes an octal number for bash, and its arithmetic stops on "08". A line
# that stands twice is no schedule to count with.
shutdown_left_min() {
	local t usec mode now
	t="$(printf '%s\n' "$1" | tr -d '\r')"     # a CRLF anywhere must not hide an armed poweroff
	usec="$(printf '%s\n' "$t" | sed -n 's/^USEC=\([0-9][0-9]*\)$/\1/p')"
	mode="$(printf '%s\n' "$t" | sed -n 's/^MODE=//p')"
	now="$(printf '%s\n' "$t" | sed -n 's/^NOW=\([0-9][0-9]*\)$/\1/p')"
	[ -n "$usec" ] && [ -n "$now" ] && [ "$mode" = poweroff ] || return 1
	case "$usec$now" in *[!0-9]*) return 1 ;; esac
	echo $(( (10#$usec / 1000000 - 10#$now) / 60 ))
}

# THE TWO NETS (2026-10-10). userdata.sh arms a monotonic timer first, which no step of the
# instance's wall clock can move, and then the wall-clock poweroff above, which is an absolute
# time and so moves against "now" by the size of any step that comes after it. `wait` proves
# both, from ONE command on the instance, so that every number is of one moment and the
# operator's own clock is in none of them. The command is one line: a multi-line argument may
# not survive every ssh. The same command gives the record userdata.sh keeps of each arming
# (wall clock, uptime, synchronised or not) and the same three reads now; `wait` prints them
# before it decides, so a refusal says what the clock did. The two reads that ask systemd over
# a bus are held to some seconds by coreutils' timeout, so one that does not answer cannot
# hold `wait`; and of the record only its first kilobytes are read: user-data writes a few
# hundred bytes, and whatever else the file has become is not the transcript's to carry.
MONO_UNIT=qnx-metal-monotonic.timer
# shellcheck disable=SC2016  # expanded on the instance, not here
ARMING_READ='M=/var/lib/cloud/instance; test -e $M/SHUTDOWN_ARMED && echo ARMED_FILE=yes; test -x /var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh && echo PERBOOT=yes; cat /run/systemd/shutdown/scheduled; echo "NOW=$(date +%s)"; timeout 20 systemctl show -p ActiveState -p NextElapseUSecMonotonic '"$MONO_UNIT"'; read -r up _ < /proc/uptime; echo "UPTIME=${up%%.*}"; timeout 20 timedatectl show -p NTPSynchronized; echo "== arming facts"; head -c 4096 /var/lib/qnx-metal-arming'

# Whole seconds in a time span as `systemctl show` prints one ("1h 30min 41.279004s": systemd's
# format_timespan, parts from years down to microseconds, a fraction only on seconds and
# milliseconds). Fails on anything else, "0" and "infinity" included: those are no time; so is
# a span of two lines (the property said twice). Its words are split by read, not by an
# unquoted expansion, which would also match them against the operator's directory: a file
# called 89min there would have made a time of "??min".
timespan_s() {
	local tok toks n total=0 seen=0
	case "$1" in *$'\n'*) return 1 ;; esac
	read -ra toks <<< "$1"
	for tok in "${toks[@]}"; do
		if [[ "$tok" =~ ^([0-9]+)(y|month|w|d|h|min|us)$ ]] || [[ "$tok" =~ ^([0-9]+)(s|ms)$ ]] \
			|| [[ "$tok" =~ ^([0-9]+)\.[0-9]+(s|ms)$ ]]; then
			n=$((10#${BASH_REMATCH[1]}))
			case "${BASH_REMATCH[2]}" in
				y) total=$((total + n * 31557600)) ;;
				month) total=$((total + n * 2629800)) ;;
				w) total=$((total + n * 604800)) ;;
				d) total=$((total + n * 86400)) ;;
				h) total=$((total + n * 3600)) ;;
				min) total=$((total + n * 60)) ;;
				s) total=$((total + n)) ;;
				*) ;;                       # under a second
			esac
			seen=1
		else
			return 1
		fi
	done
	[ "$seen" = 1 ] || return 1
	echo "$total"
}

# Seconds until the monotonic net fires, from the text of the read above: the time since boot
# at which the timer elapses, less the uptime. Fails unless the unit is active and both are
# there. A timer that has elapsed gives a negative number, for the caller to refuse. Pure.
mono_left_s() {
	local t state next up s
	t="$(printf '%s\n' "$1" | tr -d '\r')"
	state="$(printf '%s\n' "$t" | sed -n 's/^ActiveState=//p')"
	next="$(printf '%s\n' "$t" | sed -n 's/^NextElapseUSecMonotonic=//p')"
	up="$(printf '%s\n' "$t" | sed -n 's/^UPTIME=\([0-9][0-9]*\)$/\1/p')"
	[ "$state" = active ] && [ -n "$up" ] || return 1
	case "$up" in *[!0-9]*) return 1 ;; esac
	s="$(timespan_s "$next")" || return 1
	echo $(( s - 10#$up ))
}

# One number of the text, by its key, in base ten; nothing unless the key stands there once
# with digits alone, fifteen at most. Base ten: a leading zero makes an octal number for bash,
# and its arithmetic stops on "08" -- which discards the whole command it is in, and for a
# caller on its way to an abort that command is the driver. What this prints, bash can count
# with.
arming_num() {   # $1 text  $2 key
	local v
	v="$(printf '%s\n' "$1" | sed -n "s/^$2=\([0-9][0-9]*\)\$/\1/p")"
	case "$v" in ''|*[!0-9]*) return 0 ;; esac
	[ "${#v}" -le 15 ] || return 0
	printf '%s' "$((10#$v))"
}

# The thirteen lines userdata.sh writes into its record, each with the only forms its value
# has: a number of at most eleven digits (epoch seconds have ten, and red() masks a run of
# exactly twelve), or one of a few words. A shape is not enough: key=my-key-name has the shape
# of a fact, and red() masks no such thing.
ARMING_FACT='^((minutes|sync_wait_s|sched_left_min|deadline)=[0-9]{1,11}|(arm|sched)_(wall|uptime)=([0-9]{1,11}|unread)|(arm|sched)_synced=(yes|no|unknown)|arm_net=(monotonic|wall-clock|none)|sched_net=(wall-clock|failed)|sync_wait=(synchronised|bound))$'

# The arming, for the transcript: what the instance recorded and what the same reads say now.
# Of the record only its own lines are shown (ARMING_FACT: numbers and a few words, so no
# identifier); the rest are counted. Wall clocks are epoch seconds, uptimes seconds.
# now_monotonic_elapse is the time since boot at which the timer fires, as systemd prints it,
# with "_" for its spaces: a form this script does not read shows there, and not only as
# "unread". The two step_ lines say how much further the wall clock moved than the uptime:
# from the first arming to the schedule, and from the schedule to now. It is called on the way
# to an abort, so it must never stop its caller: every number it counts with comes through
# arming_num, and `wait` runs it in a subshell all the same.
arming_say() {
	local t head facts line out=() hidden=0 v left mleft state next
	local aw au sw su nw nu s1=unread s2=unread
	t="${1//$'\r'/}"
	if [ -z "${t//[[:space:]]/}" ]; then
		say "the arming: nothing could be read from the instance"
		return 0
	fi
	t=$'\n'"$t"
	head="${t%%$'\n'== arming facts*}"
	facts=""
	case "$t" in *$'\n'"== arming facts"*) facts="${t#*$'\n'== arming facts}" ;; esac
	while IFS= read -r line; do
		[ -n "$line" ] || continue
		if [[ "$line" =~ $ARMING_FACT ]]; then out+=("  $line"); else hidden=$((hidden + 1)); fi
	done <<< "$facts"
	nw="$(arming_num "$head" NOW)"; nu="$(arming_num "$head" UPTIME)"
	v="$(printf '%s\n' "$head" | sed -n 's/^NTPSynchronized=\(yes\|no\)$/\1/p')"
	case "$v" in yes|no) ;; *) v=unknown ;; esac          # said once, or not known
	out+=("  now_wall=${nw:-unread}" "  now_uptime=${nu:-unread}" "  now_synced=$v")
	left="$(shutdown_left_min "$head" || true)"
	state="$(printf '%s\n' "$head" | sed -n 's/^ActiveState=\([a-z-]*\)$/\1/p')"
	# One of the states systemd gives a unit, or "other": a word of any kind is not shown.
	case "$state" in ''|active|reloading|inactive|failed|activating|deactivating|maintenance|refreshing) ;; *) state=other ;; esac
	next="$(printf '%s\n' "$head" | sed -n 's/^NextElapseUSecMonotonic=//p')"
	next="${next// /_}"
	if [ -n "$next" ] && { [[ ! "$next" =~ ^[0-9a-z._]+$ ]] || [ "${#next}" -gt 40 ]; }; then next=unshown; fi
	mleft="$(mono_left_s "$head" || true)"
	[ -z "$mleft" ] || mleft=$(( mleft / 60 ))
	out+=("  now_wallclock_left_min=${left:-none}" "  now_monotonic_state=${state:-absent}"
	      "  now_monotonic_elapse=${next:-absent}" "  now_monotonic_left_min=${mleft:-unread}")
	aw="$(arming_num "$facts" arm_wall)"; au="$(arming_num "$facts" arm_uptime)"
	sw="$(arming_num "$facts" sched_wall)"; su="$(arming_num "$facts" sched_uptime)"
	if [ -n "$aw" ] && [ -n "$au" ] && [ -n "$sw" ] && [ -n "$su" ]; then s1=$(( (sw - aw) - (su - au) )); fi
	if [ -n "$sw" ] && [ -n "$su" ] && [ -n "$nw" ] && [ -n "$nu" ]; then s2=$(( (nw - sw) - (nu - su) )); fi
	out+=("  step_arm_to_sched_s=$s1" "  step_sched_to_now_s=$s2")
	# One pass through red() for the whole block: on Git Bash each pass costs about a second.
	{
		printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "the arming, as the instance recorded it and as it reads now (wall clock in epoch seconds, uptime in seconds):"
		printf '%s\n' "${out[@]}"
		[ "$hidden" = 0 ] || printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$hidden line(s) of the record not shown (not a line userdata.sh writes, or cut by the read)"
	} | red
	return 0
}

# A Python that runs: on Windows `python3` is often the Microsoft Store placeholder,
# which exists as a command and exits 9009.
pick_python() {
	local c
	for c in "${PYTHON:-}" python3 python py; do
		[ -n "$c" ] && command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0)' >/dev/null 2>&1 \
			&& { printf '%s' "$c"; return 0; }
	done
	return 1
}

# A native Windows aws.exe cannot open a Git Bash path.
file_url() { if command -v cygpath >/dev/null 2>&1; then echo "file://$(cygpath -m "$1")"; else echo "file://$1"; fi; }

# Refuse a directory inside the repository: session state and fetched captures
# must never be one `git add` away from being published.
outside_repo() {   # $1 path  $2 what
	local top p
	top="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
	# git missing from PATH must not disarm the guard: a checkout still has .git,
	# and a bare copy of these scripts has no repository to leak into.
	if [ -z "$top" ] && [ -e "$HERE/../../.git" ]; then top="$(cd "$HERE/../.." && pwd)"; fi
	[ -n "$top" ] || return 0
	top="$(posix_path "$top")"
	mkdir -p "$1"
	p="$(cd "$1" && pwd)"
	# Windows opens E:/Project and /e/PROJECT as one directory, so compare the way that
	# filesystem does -- and only there, where the two are not different paths.
	if command -v cygpath >/dev/null 2>&1; then shopt -s nocasematch; fi
	case "$p/" in "$top"/*) die "$2 ($p) is inside the repository; point it elsewhere" ;; esac
	shopt -u nocasematch
}

sha256_hex() {   # sha256 of a file, from stdin so the name is never escaped into the output
	local h
	h="$(sha256sum < "$1" | cut -c1-64)"
	case "$h" in *[!0-9a-f]*|'') die "could not hash $1" ;; esac
	[ "${#h}" -eq 64 ] || die "could not hash $1"
	printf '%s' "$h"
}

main() {
	outside_repo "$STATE" "METAL_STATE"
	chmod 700 "$STATE" 2>/dev/null || true   # a no-op on Git Bash; the profile ACL is what protects it there
	aws_() { "$AWS" "$@" 2> >(red >&2) | tr -d '\r'; }
	iid() { [ -s "$STATE/id" ] || die "no instance recorded in the session state"; cat "$STATE/id"; }
	state_of() { aws_ ec2 describe-instances --region "$REGION" --instance-ids "$(iid)" \
		--query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true; }
	abort() {   # terminate, CONFIRM, and only then record it
		trap - ERR
		say "ABORT: $* -- terminating"
		local st=""
		if [ -s "$STATE/id" ]; then
			# The likely failure here is a throttled call and the loop already sleeps: ask
			# again, rather than only re-reading the state of an instance still running.
			for _ in $(seq 1 "$CONFIRM_TRIES"); do
				aws_ ec2 terminate-instances --region "$REGION" --instance-ids "$(iid)" \
					--query 'TerminatingInstances[0].CurrentState.Name' --output text >/dev/null 2>&1 || true
				st="$(state_of)"
				case "$st" in shutting-down|terminated) break ;; esac
				sleep "$POLL_S"
			done
		fi
		case "$st" in
			shutting-down|terminated)
				date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/terminated"
				die "$* (instance $st)" ;;
			*)
				say "TERMINATE FAILED -- the instance may still be running (state '${st:-unknown}')$([ -e "$STATE/armed" ] && echo ', self-termination was proven armed' || echo ' and its self-termination was NOT proven'). Terminate it by hand in $REGION now."
				exit 3 ;;
		esac
	}
	need() { local v; for v in "$@"; do [ -n "${!v:-}" ] || die "set $v (environment or scripts/aws/.env.local)"; done; }
	# 2026-10-08: METAL_QEMU_PKG, when set, is a Debian version string and nothing else. `launch`
	# asks, so a malformed one is refused before anything is billed, and `run setup` asks again
	# before the value crosses to the instance.
	qemu_pkg_shape() {
		[ -z "${METAL_QEMU_PKG:-}" ] || [[ "$METAL_QEMU_PKG" =~ ^[0-9][A-Za-z0-9.+:~-]*$ ]] \
			|| die "METAL_QEMU_PKG='$METAL_QEMU_PKG' is not a package version"
	}
	armed() { [ -e "$STATE/armed" ] && [ -s "$STATE/ip" ] || die "the safety net was not proven armed (run wait)"; }
	SSHO=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$STATE/known_hosts"
	      -o ConnectTimeout=8 -o ServerAliveInterval=20 -o LogLevel=ERROR)
	[ -n "${METAL_PEM:-}" ] && SSHO=(-i "$(posix_path "$METAL_PEM")" "${SSHO[@]}")
	rsh() { ssh "${SSHO[@]}" "ubuntu@$(cat "$STATE/ip")" "$@" 2>&1 | red; return "${PIPESTATUS[0]}"; }

	case "${1:?step: launch|wait|upload|run|fetch|terminate|verify|verify-vol|clear}" in
	launch)
		need METAL_KEY_NAME METAL_SG_NAME
		qemu_pkg_shape
		mkdir "$STATE/lock" 2>/dev/null || die "another launch holds $STATE/lock (or a stale one; remove it after checking)"
		trap 'rmdir "$STATE/lock" 2>/dev/null || true' EXIT
		local f
		for f in id ip ip.pending vol armed terminated closed known_hosts inputs.txt token; do
			[ -e "$STATE/$f" ] && die "session state is not clean ($f exists): verify-vol, then clear"
		done
		local n m token
		n="$(aws_ ec2 describe-instances --region "$REGION" --filters Name=instance-state-name,Values=running,pending \
			--query 'length(Reservations[].Instances[])' --output text)"
		[ "$n" = 0 ] || die "$n instance(s) already running or pending in $REGION -- not launching beside them"
		# A client token makes a retried or doubled launch return the SAME instance.
		token="qnx-a6-$(date -u +%Y%m%dT%H%M%S)-$$-${RANDOM}"
		echo "$token" > "$STATE/token"
		if ! aws_ ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$TYPE" \
			--key-name "$METAL_KEY_NAME" --security-groups "$METAL_SG_NAME" \
			--client-token "$token" \
			--instance-initiated-shutdown-behavior terminate \
			--user-data "$(file_url "$HERE/userdata.sh")" \
			--block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"DeleteOnTermination":true,"VolumeSize":16,"VolumeType":"gp3"}}]' \
			--tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=qnx-a6-ladder}]' 'ResourceType=volume,Tags=[{Key=Name,Value=qnx-a6-ladder}]' \
			--query 'Instances[0].InstanceId' --output text > "$STATE/id.tmp"; then
			# Did it start anyway? Ask by the token before giving up.
			# describe-instances is eventually consistent: one empty answer straight after a
			# create means nothing, so poll before concluding nothing was started.
			for _ in $(seq 1 "$CONFIRM_TRIES"); do
				aws_ ec2 describe-instances --region "$REGION" --filters "Name=client-token,Values=$token" \
					--query 'Reservations[0].Instances[0].InstanceId' --output text > "$STATE/id.tmp" 2>/dev/null || true
				case "$(cat "$STATE/id.tmp")" in i-*) break ;; esac
				sleep "$POLL_S"
			done
			case "$(cat "$STATE/id.tmp")" in i-*) mv "$STATE/id.tmp" "$STATE/id"; abort "run-instances failed, but an instance exists" ;; esac
			# Nothing started, so nothing is owed -- and the token goes with the id:
			# left behind it refuses the next launch and names a recovery (verify-vol,
			# then clear) that cannot run, because no volume was ever recorded.
			rm -f "$STATE/id.tmp" "$STATE/token"; die "run-instances failed and no instance carries this launch's token"
		fi
		mv "$STATE/id.tmp" "$STATE/id"
		case "$(cat "$STATE/id")" in i-*) ;; *) abort "run-instances returned no instance id" ;; esac
		set -E; trap 'abort "unexpected failure at line $LINENO"' ERR
		date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/launched"
		say "launched $(iid) ($TYPE, $REGION) at $(cat "$STATE/launched")"
		# One mapping, and it is the root, deleted on termination -- read back, not assumed.
		# Right after a launch EC2 may not know the id yet: retry, do not die.
		set --
		for _ in $(seq 1 "$READBACK_TRIES"); do
			m="$(aws_ ec2 describe-instances --region "$REGION" --instance-ids "$(iid)" \
				--query 'Reservations[0].Instances[0].[RootDeviceName, length(BlockDeviceMappings), BlockDeviceMappings[0].DeviceName, BlockDeviceMappings[0].Ebs.DeleteOnTermination, BlockDeviceMappings[0].Ebs.VolumeId]' \
				--output text 2>/dev/null || true)"
			# shellcheck disable=SC2086  # five whitespace-separated fields
			set -- $m
			[ "$#" -eq 5 ] && [ "$5" != None ] && break
			set --
			sleep "$POLL_S"
		done
		[ "$#" -eq 5 ] && [ "$2" = 1 ] && [ "$1" = "$3" ] && [ "$4" = True ] \
			|| abort "block devices not as expected: root=${1:-?} mappings=${2:-?} first=${3:-?} delete_on_term=${4:-?}"
		echo "$5" > "$STATE/vol"
		say "root volume recorded ($1, delete on termination)"
		trap - ERR
		;;
	wait)
		# Past the proof a failure must NOT terminate (FAILURE POLICY, above), and the
		# budget legitimately shrinks as the session runs: re-running must not abort it.
		if [ -e "$STATE/armed" ] && [ -s "$STATE/ip" ]; then say "the safety net is already proven armed"; exit 0; fi
		set -E; trap 'abort "unexpected failure at line $LINENO"' ERR
		local t0 ip="" st="" proof="" said=0 head left mleft mmin
		# The one read of the instance the proof is made on, printed once. Every refusal from the
		# moment an address is known comes through `refuse`, so each says first what the instance
		# recorded of its arming and what the same reads say now. abort itself is unchanged. The
		# printing runs in a subshell: it stands between a refusal and its abort, and whatever
		# goes wrong in it (bash discards the whole running command on an arithmetic error, and
		# `|| true` does not hold that) ends there and not in the driver.
		arming_once() {
			[ "$said" = 0 ] || return 0
			said=1
			proof="$(ssh "${SSHO[@]}" "ubuntu@$ip" "$ARMING_READ" 2>/dev/null || true)"
			( arming_say "$proof" ) || true
		}
		refuse() { arming_once; abort "$@"; }
		t0=$SECONDS
		while [ $((SECONDS - t0)) -lt "$IP_WAIT_S" ]; do
			ip="$(aws_ ec2 describe-instances --region "$REGION" --instance-ids "$(iid)" \
				--query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || true)"
			[ -n "$ip" ] && [ "$ip" != None ] && break
			sleep "$POLL_S"
		done
		[ -n "$ip" ] && [ "$ip" != None ] || abort "no public address after ${IP_WAIT_S}s"
		# The address is only promoted to $STATE/ip once the safety net is proven.
		echo "$ip" > "$STATE/ip.pending"
		t0=$SECONDS
		while [ $((SECONDS - t0)) -lt "$PROV_WAIT_S" ]; do
			st="$(ssh "${SSHO[@]}" "ubuntu@$ip" 'M=/var/lib/cloud/instance; [ -e $M/PROVISION_FAILED ] && echo FAILED; [ -e $M/PROVISIONED ] && echo OK' 2>/dev/null || true)"
			case "$st" in *FAILED*|*OK*) break ;; esac
			sleep "$POLL_S"
		done
		case "$st" in
			*FAILED*) refuse "user-data failed (PROVISION_FAILED)" ;;
			*OK*) say "provisioned after $((SECONDS - t0))s of polling" ;;
			*) refuse "not provisioned after ${PROV_WAIT_S}s" ;;
		esac
		# The proof: one read, printed, then judged. It is printed whether `wait` goes on or
		# not, so a session that passes also says what its clock did.
		arming_once
		head=$'\n'"${proof//$'\r'/}"
		head="${head%%$'\n'== arming facts*}"$'\n'
		# The wall-clock net, as before: the two marks user-data leaves, and a poweroff scheduled.
		case "$head" in *$'\nARMED_FILE=yes\n'*) ;; *) refuse "the self-termination shutdown is NOT armed (or its per-boot re-arm is missing)" ;; esac
		case "$head" in *$'\nPERBOOT=yes\n'*) ;; *) refuse "the self-termination shutdown is NOT armed (or its per-boot re-arm is missing)" ;; esac
		left="$(shutdown_left_min "$head" || true)"
		[ -n "$left" ] || refuse "the self-termination shutdown is NOT armed (or its per-boot re-arm is missing)"
		# The monotonic net: the timer unit active, with no more than the session's minutes left on
		# it, to the second. Its lower end is the wall-clock window's: too little left is no session.
		mleft="$(mono_left_s "$head" || true)"
		[ -n "$mleft" ] || refuse "the monotonic timer is NOT armed ($MONO_UNIT is not active, or its time could not be read)"
		mmin=$(( mleft / 60 ))
		[ "$mmin" -gt $((SHUTDOWN_MIN_EXPECTED - 30)) ] && [ "$mleft" -le $((SHUTDOWN_MIN_EXPECTED * 60)) ] \
			|| refuse "monotonic timer armed for $mmin min ahead, expected $((SHUTDOWN_MIN_EXPECTED - 29))..$SHUTDOWN_MIN_EXPECTED and not a second more"
		[ "$left" -gt $((SHUTDOWN_MIN_EXPECTED - 30)) ] && [ "$left" -le $((SHUTDOWN_MIN_EXPECTED + 1)) ] \
			|| refuse "shutdown armed for $left min ahead, expected $((SHUTDOWN_MIN_EXPECTED - 29))..$((SHUTDOWN_MIN_EXPECTED + 1))"
		mv "$STATE/ip.pending" "$STATE/ip"
		touch "$STATE/armed"
		trap - ERR
		say "self-termination armed: poweroff in $left min by the wall clock and in $mmin min by the monotonic timer, both re-armed on any reboot"
		# Said, not refused: the wall-clock poweroff is right by the clock as it stands, and the
		# monotonic timer holds whatever the clock does next.
		case "$head" in *$'\nNTPSynchronized=yes\n'*) ;; *) say "NOTE: the instance does not call its clock synchronised. A step forward from here brings the wall-clock poweroff, and the session's end, nearer by its size; a step backward cannot move it past the monotonic timer, which holds until a reboot." ;; esac
		;;
	upload)
		armed
		need METAL_REPO_TAR METAL_IFS METAL_DISK_GZ
		local ip tar ifs disk ifs_name ifs_sha disk_sha rl_sha cap_sha
		ip="$(cat "$STATE/ip")"
		tar="$(posix_path "$METAL_REPO_TAR")"; ifs="$(posix_path "$METAL_IFS")"; disk="$(posix_path "$METAL_DISK_GZ")"
		case "$(basename "$disk")" in disk-qemu.gz) ;; *) die "METAL_DISK_GZ must be named disk-qemu.gz" ;; esac
		ifs_name="$(basename "$ifs")"
		case "$ifs_name" in ''|*[!A-Za-z0-9._-]*) die "image name '$ifs_name' has characters this script will not pass on" ;; esac
		ifs_sha="$(sha256_hex "$ifs")"
		disk_sha="$(gunzip -c "$disk" | sha256sum | cut -c1-64)"
		case "$disk_sha" in *[!0-9a-f]*|'') die "could not hash the disk" ;; esac
		# 2026-09-27: METAL_IFS_EXTRA, more images for a harness session, space-separated paths.
		local x xn extra="" extra_paths=()
		for x in ${METAL_IFS_EXTRA:-}; do
			x="$(posix_path "$x")"
			xn="$(basename "$x")"
			case "$xn" in ''|*[!A-Za-z0-9._-]*) die "image name '$xn' has characters this script will not pass on" ;; esac
			[ "$xn" != "$ifs_name" ] || die "METAL_IFS_EXTRA repeats $xn"
			[ -r "$x" ] || die "METAL_IFS_EXTRA: no $x"
			extra="${extra:+$extra }$xn:$(sha256_hex "$x")"
			extra_paths+=("$x")
		done
		rl_sha="$(sha256_hex "$HERE/remote-ladder.sh")"; cap_sha="$(sha256_hex "$HERE/capture.py")"
		{ echo "commit $(git get-tar-commit-id < "$tar" 2>/dev/null || echo unknown)"
		  echo "repo.tar $(sha256_hex "$tar")"
		  echo "remote-ladder.sh $rl_sha"
		  echo "capture.py $cap_sha"
		  echo "ifs $ifs_name $ifs_sha"
		  for x in $extra; do echo "ifs ${x%%:*} ${x#*:}"; done
		  echo "disk $disk_sha"; } > "$STATE/inputs.txt"
		rsh 'mkdir -p ~/a1/img'
		scp "${SSHO[@]}" "$tar" "ubuntu@$ip:a1/repo.tar" 2>&1 | red
		scp "${SSHO[@]}" "$HERE/remote-ladder.sh" "$HERE/capture.py" "ubuntu@$ip:a1/" 2>&1 | red
		scp "${SSHO[@]}" "$ifs" "$disk" "${extra_paths[@]}" "ubuntu@$ip:a1/img/" 2>&1 | red
		# The instance checks everything against these before using it, and copies
		# them into the record, so the record names what actually ran.
		local commit; commit="$(git get-tar-commit-id < "$tar" 2>/dev/null || true)"
		case "$commit" in *[!0-9a-f]*) commit="" ;; esac
		[ "${#commit}" -eq 40 ] || commit=unknown
		rsh "printf 'IFS_NAME=%s\nIFS_SHA256=%s\nDISK_SHA256=%s\nREMOTE_LADDER_SHA256=%s\nCAPTURE_SHA256=%s\nREPO_COMMIT=%s\n' '$ifs_name' '$ifs_sha' '$disk_sha' '$rl_sha' '$cap_sha' '$commit' > ~/a1/inputs.env"
		[ -z "$extra" ] || rsh "printf 'IFS_EXTRA=%s\n' '$extra' >> ~/a1/inputs.env"
		red < "$STATE/inputs.txt"
		# From here the instance holds this session's data: terminate wants a fetch first.
		touch "$STATE/uploaded"
		;;
	run)
		armed
		local phase="${2:?phase: $PHASES}" envs=() w
		case " $PHASES " in *" $phase "*) ;; *) die "unknown phase '$phase' (one of: $PHASES)" ;; esac
		# Only validated NAME=value words cross to the instance, quoted.
		if [ -n "${K:-}" ]; then case "$K" in *[!0-9]*|0*) die "K='$K' is not a round count (digits, no leading zero)" ;; esac; envs+=("K=$K"); fi
		if [ -n "${LADDER_ENV:-}" ]; then
			for w in $LADDER_ENV; do
				[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
			done
			envs+=("LADDER_ENV=$LADDER_ENV")
		fi
		# 2026-10-08: the qemu-system-arm version this session expects, for setup alone, which
		# refuses when dpkg has another. A Debian version string, and nothing else, crosses.
		if [ "$phase" = setup ] && [ -n "${METAL_QEMU_PKG:-}" ]; then
			qemu_pkg_shape
			envs+=("METAL_QEMU_PKG=$METAL_QEMU_PKG")
		fi
		rsh "$(printf '%q ' env "${envs[@]}" bash a1/remote-ladder.sh "$phase")"
		;;
	fetch)
		armed
		local ip out
		ip="$(cat "$STATE/ip")"; out="$(posix_path "${METAL_FETCH_DIR:-$STATE/fetched}")"
		outside_repo "$out" "the fetch directory"
		scp "${SSHO[@]}" "ubuntu@$ip:a1/pub.tgz" "ubuntu@$ip:a1/pub.sha256" "$out/" 2>&1 | red
		rm -rf "$out/pub"; mkdir -p "$out/pub"
		( cd "$out" && tar -xzf pub.tgz -C pub )
		( cd "$out/pub" && sha256sum -c --quiet ../pub.sha256 ) || die "fetched files do not match the instance's hashes"
		say "fetched and verified $(wc -l < "$out/pub.sha256") files"
		# Integrity is not cleanliness: scan for anything identifying before it can be published.
		local lits=()
		mapfile -t lits < <(red_literals)
		local py; py="$(pick_python)" || die "no working Python for the leak scan"
		"$py" "$HERE/leakscan.py" "$out/pub" "${lits[@]}" 2>&1 | red \
			|| die "the capture is NOT publishable -- it is still in $out (pub.tgz and pub/): inspect it, then delete it by hand"
		touch "$STATE/fetched-ok"
		say "capture is in $out/pub"
		;;
	terminate)
		local st
		# 2026-09-27: a terminate run straight after a fetch that had failed lost a billed
		# session's data. Once something was uploaded, terminate wants a fetch that passed,
		# or METAL_DISCARD=1. The instance's own self-termination stays armed either way,
		# and every failure path before the upload still terminates on its own.
		if [ -e "$STATE/uploaded" ] && [ ! -e "$STATE/fetched-ok" ] && [ "${METAL_DISCARD:-0}" != 1 ]; then
			die "nothing was fetched from this session: run fetch first, or set METAL_DISCARD=1 to terminate and lose the instance's data (its self-termination is armed either way)"
		fi
		aws_ ec2 terminate-instances --region "$REGION" --instance-ids "$(iid)" \
			--query 'TerminatingInstances[0].CurrentState.Name' --output text >/dev/null
		# describe-instances lags the terminate it has just accepted; poll as abort does,
		# so a termination that worked is not reported as one to check by hand.
		for _ in $(seq 1 "$CONFIRM_TRIES"); do
			st="$(state_of)"
			case "$st" in shutting-down|terminated) break ;; esac
			sleep "$POLL_S"
		done
		case "$st" in shutting-down|terminated) ;; *) die "terminate requested but the instance is '$st' -- check it by hand" ;; esac
		date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/terminated"
		say "terminate confirmed ($st) at $(cat "$STATE/terminated") (launched $(cat "$STATE/launched" 2>/dev/null || echo ?))"
		;;
	verify)
		local run vol st
		run="$(aws_ ec2 describe-instances --region "$REGION" --filters Name=instance-state-name,Values=running,pending \
			--query 'length(Reservations[].Instances[])' --output text)"
		vol="$(aws_ ec2 describe-volumes --region "$REGION" --filters Name=status,Values=available \
			--query 'length(Volumes)' --output text)"
		st="$(state_of)"
		say "ours: $st | running or pending in region: $run | available volumes: $vol"
		[ "$run" = 0 ] && [ "$vol" = 0 ] && case "$st" in shutting-down|terminated) true ;; *) false ;; esac \
			|| die "teardown NOT verified"
		say "billing stopped (instance $st); run verify-vol once it is terminated"
		;;
	verify-vol)
		local st v
		[ -s "$STATE/vol" ] || die "no root volume recorded"
		st="$(state_of)"
		v="$("$AWS" ec2 describe-volumes --region "$REGION" --volume-ids "$(cat "$STATE/vol")" \
			--query 'Volumes[0].State' --output text 2>&1 | tr -d '\r' | red || true)"
		say "instance: $st | root volume: $v"
		case "$v" in
			*InvalidVolume.NotFound*|deleting|deleted) touch "$STATE/closed"; say "root volume gone -- teardown complete" ;;
			*) die "root volume still present ($v)" ;;
		esac
		;;
	clear)
		# `closed` is the full path: verify-vol passed. A launch that failed before the
		# read-back records no volume for verify-vol to clear, so a confirmed termination
		# -- or no instance at all -- also clears; otherwise the state wedges here.
		if [ ! -e "$STATE/closed" ]; then
			[ -s "$STATE/vol" ] && die "a root volume is recorded and not verified gone; run verify-vol, then clear"
			[ -s "$STATE/id" ] && [ ! -e "$STATE/terminated" ] \
				&& die "an instance is recorded with no confirmed termination; terminate and verify, then clear"
		fi
		# The fetched capture defaults to $STATE/fetched and is the billed session's
		# only artifact: clear the state around it, never through it.
		local f
		for f in "${STATE:?}/"*; do
			case "$(basename "$f")" in fetched) ;; *) rm -rf "$f" ;; esac
		done
		if [ -e "$STATE/fetched" ]; then
			say "session state cleared; the capture stays in $STATE/fetched -- move it into the record before another session fetches over it"
		else
			say "session state cleared"
		fi
		;;
	*) die "unknown step $1" ;;
	esac
}

# Sourced by the tests for red(), shutdown_left_min() and friends; run otherwise.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
