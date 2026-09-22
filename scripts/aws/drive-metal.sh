#!/usr/bin/env bash
# drive-metal.sh -- drive ONE bare-metal AWS session for an A6 ladder, from the
# operator's machine (Git Bash on Windows, or Linux; GNU sed and Python 3 needed).
#
#   drive-metal.sh launch        run-instances, self-terminating; root volume read back
#   drive-metal.sh wait          until provisioned; PROVES the shutdown safety net is armed
#   drive-metal.sh upload        repo tarball, remote-ladder.sh, capture.py, image, gzipped disk
#   drive-metal.sh run PHASE     remote-ladder.sh PHASE (setup|quiesce|launch|ladder|capture)
#   drive-metal.sh fetch         pub.tgz back, hash-verified, then leak-scanned
#   drive-metal.sh terminate     terminate-instances, confirmed
#   drive-metal.sh verify        nothing running|pending, ours shutting-down|terminated, no
#                                available (orphaned) volume -- billing has stopped
#   drive-metal.sh verify-vol    our root volume is gone (once the instance is terminated)
#   drive-metal.sh clear         empty the session state -- only after verify-vol passed
#
# An earlier form of this script drove the 2026-09-22 a1.metal session
# (results/orin-native-port/20260922T-a6-a1metal-kick); see README.md for what changed.
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
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# METAL_NO_ENV_LOCAL: the tests must not pick up a developer's local configuration.
[ -z "${METAL_NO_ENV_LOCAL:-}" ] && [ -r "$HERE/.env.local" ] && . "$HERE/.env.local"
AWS="${AWS:-aws}"
REGION="${METAL_REGION:-eu-central-1}"
AMI="${METAL_AMI:-ami-02153ae97d7504246}"      # ubuntu-jammy-22.04-arm64-server-20260904 (public)
TYPE="${METAL_TYPE:-a1.metal}"
SHUTDOWN_MIN_EXPECTED="${SHUTDOWN_MIN_EXPECTED:-90}"   # must match userdata.sh (a test checks it)
# Polling pace and patience; the tests shrink them.
POLL_S="${METAL_POLL_S:-5}"
IP_WAIT_S="${METAL_IP_WAIT_S:-300}"
PROV_WAIT_S="${METAL_PROV_WAIT_S:-900}"
CONFIRM_TRIES="${METAL_CONFIRM_TRIES:-6}"
READBACK_TRIES="${METAL_READBACK_TRIES:-30}"
PHASES="setup quiesce launch ladder capture"

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
		s/(^|[^0-9.])[0-9]{12}([^0-9]|$)/\1<account>\2/
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
# poweroff. Pure, so the tests call it directly.
shutdown_left_min() {
	local t usec mode now
	t="$(printf '%s\n' "$1" | tr -d '\r')"     # a CRLF anywhere must not hide an armed poweroff
	usec="$(printf '%s\n' "$t" | sed -n 's/^USEC=\([0-9][0-9]*\)$/\1/p')"
	mode="$(printf '%s\n' "$t" | sed -n 's/^MODE=//p')"
	now="$(printf '%s\n' "$t" | sed -n 's/^NOW=\([0-9][0-9]*\)$/\1/p')"
	[ -n "$usec" ] && [ -n "$now" ] && [ "$mode" = poweroff ] || return 1
	echo $(( (usec / 1000000 - now) / 60 ))
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
	armed() { [ -e "$STATE/armed" ] && [ -s "$STATE/ip" ] || die "the safety net was not proven armed (run wait)"; }
	SSHO=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$STATE/known_hosts"
	      -o ConnectTimeout=8 -o ServerAliveInterval=20 -o LogLevel=ERROR)
	[ -n "${METAL_PEM:-}" ] && SSHO=(-i "$(posix_path "$METAL_PEM")" "${SSHO[@]}")
	rsh() { ssh "${SSHO[@]}" "ubuntu@$(cat "$STATE/ip")" "$@" 2>&1 | red; return "${PIPESTATUS[0]}"; }

	case "${1:?step: launch|wait|upload|run|fetch|terminate|verify|verify-vol|clear}" in
	launch)
		need METAL_KEY_NAME METAL_SG_NAME
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
		local t0 ip="" st="" sched left
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
			*FAILED*) abort "user-data failed (PROVISION_FAILED)" ;;
			*OK*) say "provisioned after $((SECONDS - t0))s of polling" ;;
			*) abort "not provisioned after ${PROV_WAIT_S}s" ;;
		esac
		sched="$(ssh "${SSHO[@]}" "ubuntu@$ip" 'test -e /var/lib/cloud/instance/SHUTDOWN_ARMED && test -x /var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh && cat /run/systemd/shutdown/scheduled && echo "NOW=$(date +%s)"' 2>/dev/null || true)"
		left="$(shutdown_left_min "$sched" || true)"
		[ -n "$left" ] || abort "the self-termination shutdown is NOT armed (or its per-boot re-arm is missing)"
		[ "$left" -gt $((SHUTDOWN_MIN_EXPECTED - 30)) ] && [ "$left" -le $((SHUTDOWN_MIN_EXPECTED + 1)) ] \
			|| abort "shutdown armed for $left min ahead, expected $((SHUTDOWN_MIN_EXPECTED - 29))..$((SHUTDOWN_MIN_EXPECTED + 1))"
		mv "$STATE/ip.pending" "$STATE/ip"
		touch "$STATE/armed"
		trap - ERR
		say "self-termination armed: poweroff in $left min, re-armed on any reboot"
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
		rl_sha="$(sha256_hex "$HERE/remote-ladder.sh")"; cap_sha="$(sha256_hex "$HERE/capture.py")"
		{ echo "commit $(git get-tar-commit-id < "$tar" 2>/dev/null || echo unknown)"
		  echo "repo.tar $(sha256_hex "$tar")"
		  echo "remote-ladder.sh $rl_sha"
		  echo "capture.py $cap_sha"
		  echo "ifs $ifs_name $ifs_sha"
		  echo "disk $disk_sha"; } > "$STATE/inputs.txt"
		rsh 'mkdir -p ~/a1/img'
		scp "${SSHO[@]}" "$tar" "ubuntu@$ip:a1/repo.tar" 2>&1 | red
		scp "${SSHO[@]}" "$HERE/remote-ladder.sh" "$HERE/capture.py" "ubuntu@$ip:a1/" 2>&1 | red
		scp "${SSHO[@]}" "$ifs" "$disk" "ubuntu@$ip:a1/img/" 2>&1 | red
		# The instance checks everything against these before using it, and copies
		# them into the record, so the record names what actually ran.
		local commit; commit="$(git get-tar-commit-id < "$tar" 2>/dev/null || true)"
		case "$commit" in *[!0-9a-f]*) commit="" ;; esac
		[ "${#commit}" -eq 40 ] || commit=unknown
		rsh "printf 'IFS_NAME=%s\nIFS_SHA256=%s\nDISK_SHA256=%s\nREMOTE_LADDER_SHA256=%s\nCAPTURE_SHA256=%s\nREPO_COMMIT=%s\n' '$ifs_name' '$ifs_sha' '$disk_sha' '$rl_sha' '$cap_sha' '$commit' > ~/a1/inputs.env"
		red < "$STATE/inputs.txt"
		;;
	run)
		armed
		local phase="${2:?phase: $PHASES}" envs=() w
		case " $PHASES " in *" $phase "*) ;; *) die "unknown phase '$phase' (one of: $PHASES)" ;; esac
		# Only validated NAME=value words cross to the instance, quoted.
		if [ -n "${K:-}" ]; then case "$K" in *[!0-9]*) die "K='$K' is not a round count" ;; esac; envs+=("K=$K"); fi
		if [ -n "${LADDER_ENV:-}" ]; then
			for w in $LADDER_ENV; do
				[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
			done
			envs+=("LADDER_ENV=$LADDER_ENV")
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
		say "capture is in $out/pub"
		;;
	terminate)
		local st
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
