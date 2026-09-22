# lib-measure.sh -- the controls every A6 latency measurement shares.
#
#   Sourced, not executed:   . "$(dirname "$0")/lib-measure.sh"
#   Callers must then check: [ "${MEASURE_LIB_LOADED:-}" = 1 ] || exit 1
#
# WHY ONE LIBRARY. run-ladder.sh, run-interference.sh and run-saturation.sh
# need the same governor handling, the same QEMU pinning, the same run stamp
# and the same completeness check. Until 2026-09-21 only the ladder had them,
# and the other two had none -- including the governor pin that
# docs/measurement-design.md §3.5 describes as "already done". It was done by
# hand before the run, and a script that depends on a manual step is a trap for
# whoever runs it next. One copy, so the three cannot drift apart.
#
# THE RULE THIS FILE EXISTS TO ENFORCE: a control is either APPLIED AND
# VERIFIED, RECORDED AS ABSENT, or the run REFUSES. Never skipped in silence.
# Every serious measurement-tooling bug this project has found had the same
# shape: a guard that failed quietly and let the run go on measuring something
# other than what its files claimed. An adversarial review on 2026-09-21 found
# 40 instances of that shape in the first draft of this file and the scripts on
# it; the comments below name the ones it caught.

MEASURE_LIB_LOADED=1

# SYSFS_CPU exists so tests can point the governor code at a fake tree. In a real
# run it must be the real one, so an override is RECORDED in the stamp and warned
# about -- otherwise the governor control could be redirected with no trace.
SYSFS_CPU_DEFAULT="/sys/devices/system/cpu"
SYSFS_CPU="${SYSFS_CPU:-$SYSFS_CPU_DEFAULT}"

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
die() { echo "FATAL: $*" >&2; exit 1; }

# ------------------------------------------------------------- run directory
# REVIEW FINDING: the completeness gate counted files by glob, and OUT was a
# fixed path that nothing cleared. A probe that failed left the PREVIOUS run's
# file for that (arm, round) in place, the count still came to k, and the
# summary took a median over eleven new files and one old one -- possibly from
# a different n, governor state or image -- while stamp.json described only the
# new run. Reproduced. So: every run gets its own directory, and a directory
# that already holds results is refused rather than reused.
#
# SETS THE GLOBAL `OUT` rather than echoing it. A function called as
# `x="$(f)"` runs in a subshell, so a `die` inside it exits only the subshell and
# the script carries on with x empty -- the exact defect the review reproduced in
# run-saturation.sh's arm_spec. Any function here that can die is called
# directly, never inside $(...).
m_prepare_out() {   # $1 = requested OUT (may be empty)  $2 = base for a fresh one
	local want="$1" base="$2"
	if [ -z "$want" ]; then
		want="$base/$(date -u +%Y%m%dT%H%M%SZ)"
	fi
	if [ -d "$want" ] && compgen -G "$want/lat-*.json" >/dev/null; then
		die "$want already holds lat-*.json from an earlier run; refusing to mix runs. Use a new OUT."
	fi
	mkdir -p "$want" || die "cannot create $want"
	: > "$want/probe.log"
	: > "$want/order.log"
	# The freshness reference for m_require_complete. It is written ONCE, here,
	# and never touched again. The first version compared against stamp.json's
	# mtime -- but m_stamp_after rewrites the stamp at the end to append the
	# after-state, so its mtime became the END of the run and every result file
	# looked older than it. The first real run on the Orin, 2026-09-21, was
	# refused for exactly that; the unit tests had missed it because they never
	# ran m_stamp_after before the check.
	: > "$want/.run-start"
	OUT="$want"
}

# ------------------------------------------------------------- the governor
# DETECT, RECORD, OR FAIL. On the Orin an unpinned idle baseline is measured on
# a slower machine than a loaded arm (schedutil clocks idle down to 729 MHz),
# which made ~40% of an "idle" figure the governor and inverted the comparison.
# On bare-metal EC2 there is no cpufreq at all, and the honest record is
# "absent", not an empty string.
#
# REVIEW FINDING: a pin that failed part-way died without restoring the cores it
# had already changed, and the next run then recorded "performance" as the prior
# governor. So each core's original value is remembered as it is changed, and
# restore puts back exactly those.
GOV_STATE="unknown"; PRE_GOV=""; GOV_AFTER=""; FREQ_BEFORE=""; FREQ_AFTER=""
declare -A GOV_ORIG=()

_freq_list() {
	local f out=""
	for f in "$SYSFS_CPU"/cpu[0-9]*/cpufreq/scaling_cur_freq; do
		[ -r "$f" ] && out="$out $(cat "$f")"
	done
	echo "${out# }"
}

m_governor_pin() {
	local g0="$SYSFS_CPU/cpu0/cpufreq/scaling_governor" c now
	[ "$SYSFS_CPU" = "$SYSFS_CPU_DEFAULT" ] \
		|| say "WARNING: SYSFS_CPU overridden to $SYSFS_CPU -- recorded in the stamp"
	if [ ! -r "$g0" ]; then
		GOV_STATE="absent"
		say "governor: NO cpufreq on this host -- nothing to pin, recorded as absent"
		return 0
	fi
	PRE_GOV="$(cat "$g0")"
	FREQ_BEFORE="$(_freq_list)"
	for c in "$SYSFS_CPU"/cpu[0-9]*/cpufreq/scaling_governor; do
		GOV_ORIG["$c"]="$(cat "$c")"
		echo performance | sudo tee "$c" >/dev/null
		now="$(cat "$c")"
		[ "$now" = "performance" ] || die "governor present but $c would not pin (still '$now')"
	done
	GOV_STATE="pinned"
	say "governor: $PRE_GOV -> performance on every core (will restore)"
}

# A governor verified once at the start says nothing about the end of a 30-minute
# loaded run. Re-read it; record the after-state and the clocks.
m_governor_recheck() {
	local c now
	[ "$GOV_STATE" = "pinned" ] || return 0
	for c in "$SYSFS_CPU"/cpu[0-9]*/cpufreq/scaling_governor; do
		now="$(cat "$c")"
		[ "$now" = "performance" ] || die "governor drifted during the run: $c is '$now' at the end"
	done
	GOV_AFTER="performance"
	FREQ_AFTER="$(_freq_list)"
	say "governor: still performance on every core at the end"
}

m_governor_restore() {
	local c now bad=0
	[ "${#GOV_ORIG[@]}" -gt 0 ] || return 0
	for c in "${!GOV_ORIG[@]}"; do
		echo "${GOV_ORIG[$c]}" | sudo tee "$c" >/dev/null
		now="$(cat "$c" 2>/dev/null)"
		if [ "$now" != "${GOV_ORIG[$c]}" ]; then
			echo "WARNING: $c restored to '$now', expected '${GOV_ORIG[$c]}'" >&2; bad=1
		fi
	done
	[ "$bad" -eq 0 ] && say "governor restored and verified on ${#GOV_ORIG[@]} core(s)"
	GOV_ORIG=()
}

# ------------------------------------------------------------- CPU idle states
# FOUND IN THE FIRST ORIN CAMPAIGN, 2026-09-21. The governor pin controls
# FREQUENCY. It never touched IDLE STATES, and the Orin exposes state1 "c7",
# declared exit latency 5000 us, enabled. The stamp said only "cpuidle":
# "present", which is how it went unnoticed; it now records every state a run
# was exposed to.
#
# WHAT WAS SEEN, THEN TESTED. Unloaded guest arms carried a separate slow mode:
# a copy of the main distribution shifted about +292 us, holding a median ~11%
# of samples. Host-native arms never had it; full load removed it; one busy
# thread on core 0 removed it in 4 of 4 rounds. That made saturation's p99 look
# ~196 us LOWER than idle's -- the mode disappearing, not load improving a tail.
# The first version of this comment asserted c7 as the cause before any test.
# The test was to change the variable: with state1 disabled, the slow mode fell
# from 12.8% to 0.0% of D-guest samples, and 6.25% to 0.0% of C-null, in every
# one of 12 rounds. So disabling state1 removes it.
#
# WHAT IS NOT SHOWN. The slow mode costs ~0.29 ms per affected sample, far below
# the 5000 us the state declares -- the declared figure is a bound the idle
# governor works with, not a measured wake cost, and no sample shows 5 ms. Which
# core's wake-up is paid (a vCPU, QEMU's I/O thread, the network softirq core)
# is not shown; core 0 is the leading candidate, a HYPOTHESIS. The probe stored
# its samples sorted until 2026-09-21, so time order -- periodic, bursty, tied
# to a tick -- could not be examined in these runs.
#
# Two policies, and both are legitimate measurements of different things:
#   CSTATE=""        (default) leave idle states as found -- the realistic,
#                    power-managed system. Recorded, not controlled.
#   CSTATE=shallow   disable every state whose exit latency exceeds
#                    CSTATE_MAX_US (default 10) -- isolates load contention.
# The difference between the two IS the idle-state effect, which is how the c7
# hypothesis gets tested rather than argued from distribution shapes.
CSTATE="${CSTATE:-}"
CSTATE_MAX_US="${CSTATE_MAX_US:-10}"
CSTATE_STATE="unknown"; CSTATE_EXPOSED=""; CSTATE_DISABLED=""
declare -A CSTATE_ORIG=()

_cstate_list() {   # one line per distinct state on cpu0: "name latency_us enabled|disabled"
	local s out=""
	for s in "$SYSFS_CPU"/cpu0/cpuidle/state[0-9]*; do
		[ -r "$s/latency" ] || continue
		out="$out $(cat "$s/name"):$(cat "$s/latency")us:$([ "$(cat "$s/disable")" = 0 ] && echo on || echo off)"
	done
	echo "${out# }"
}

m_cstate_apply() {
	local s d lat now
	if [ ! -d "$SYSFS_CPU/cpu0/cpuidle" ]; then
		CSTATE_STATE="absent"
		say "idle states: NO cpuidle on this host -- nothing to control, recorded as absent"
		return 0
	fi
	case "$CSTATE" in
		"")
			CSTATE_STATE="as-found"
			CSTATE_EXPOSED="$(_cstate_list)"
			say "idle states: left AS FOUND (realistic, power-managed): $CSTATE_EXPOSED"
			;;
		shallow)
			for d in "$SYSFS_CPU"/cpu[0-9]*/cpuidle/state[0-9]*/disable; do
				s="${d%/disable}"
				lat="$(cat "$s/latency")"
				[ "$lat" -gt "$CSTATE_MAX_US" ] || continue
				CSTATE_ORIG["$d"]="$(cat "$d")"
				echo 1 | sudo tee "$d" >/dev/null
				now="$(cat "$d")"
				[ "$now" = 1 ] || die "idle state $s would not disable (still '$now')"
			done
			CSTATE_STATE="shallow"
			CSTATE_EXPOSED="$(_cstate_list)"
			CSTATE_DISABLED="${#CSTATE_ORIG[@]} state(s) with exit latency > ${CSTATE_MAX_US} us"
			say "idle states: SHALLOW -- disabled $CSTATE_DISABLED; now $CSTATE_EXPOSED (will restore)"
			;;
		*) die "CSTATE='$CSTATE' is not a policy; use empty (as found) or 'shallow'" ;;
	esac
}

m_cstate_restore() {
	local d now bad=0
	[ "${#CSTATE_ORIG[@]}" -gt 0 ] || return 0
	for d in "${!CSTATE_ORIG[@]}"; do
		echo "${CSTATE_ORIG[$d]}" | sudo tee "$d" >/dev/null
		now="$(cat "$d" 2>/dev/null)"
		[ "$now" = "${CSTATE_ORIG[$d]}" ] || { echo "WARNING: $d restored to '$now', expected '${CSTATE_ORIG[$d]}'" >&2; bad=1; }
	done
	[ "$bad" -eq 0 ] && say "idle states restored and verified (${#CSTATE_ORIG[@]} state(s))"
	CSTATE_ORIG=()
}

# ------------------------------------------------------------- cores
m_check_cores() {   # $@ = core numbers or ranges like 0-2
	NCPU="$(nproc)"
	local spec hi
	for spec in "$@"; do
		hi="${spec##*-}"
		[ "$hi" -lt "$NCPU" ] || die "core spec '$spec' exceeds this host's $NCPU cores (0-$((NCPU-1)))"
	done
}

# Expand "0-2,5" to "0 1 2 5", sorted, de-duplicated. REVIEW FINDING: the first
# draft compared affinity readback as an exact string, and taskset can print a
# two-CPU set as "0,1" where "0-1" was asked for -- which would kill a valid run.
_cpuset() {
	local spec="$1" part a b i out=()
	for part in ${spec//,/ }; do
		if [[ "$part" == *-* ]]; then
			a="${part%-*}"; b="${part#*-}"
			for ((i=a; i<=b; i++)); do out+=("$i"); done
		else
			out+=("$part")
		fi
	done
	printf '%s\n' "${out[@]}" | sort -n | uniq | tr '\n' ' ' | sed 's/ $//'
}

# ------------------------------------------------------------- finding processes
# PIDs whose argv[0] basename is EXACTLY $1. Found live on the Orin, 2026-09-21:
# `pgrep -f "[m]onitor-nativ"` matched the invoking shell. The bracket trick
# only stops a pattern matching ITSELF; it does nothing when the unbracketed
# name appears anywhere else on the same command line -- and a `bash -c` sent
# over ssh carries its whole script as one argument. run-ladder.sh used that
# pattern both to REFUSE a run and, in cleanup, to KILL, so invoked the wrong way
# it would have refused falsely or killed its own caller.
#
# Not `pgrep -x` either: that matches `comm`, which the kernel truncates to 15
# characters, so qemu-system-aarch64 reads as "qemu-system-aar" and never
# matches. argv[0] is not truncated, and a shell's argv[0] is the shell.
#
# Safe under `set -euo pipefail` (launch-qnx-kvm-bridged.sh runs that way): no
# pipeline and no subshell per process. A process can vanish between the /proc
# glob and the read, and a `tr | head` pipeline could also SIGPIPE when head
# closed early -- under pipefail either would have exited the caller. `read -d ''`
# is a builtin that stops at argv[0]'s NUL; a vanished process or a kernel thread
# (empty cmdline) just reads as empty. Always returns 0.
m_pids_of() {       # $1 = executable basename
	local want="$1" d a0
	for d in /proc/[0-9]*; do
		a0=""
		IFS= read -r -d '' a0 < "$d/cmdline" 2>/dev/null || true
		if [ -n "$a0" ] && [ "${a0##*/}" = "$want" ]; then echo "${d#/proc/}"; fi
	done
	return 0
}

# ------------------------------------------------------------- the guest
QPID=""; QTHREADS=0; QAFF=""; QEXE=""; QVER=""
QSTART=""; GUEST_IFS=""; GUEST_IFS_SHA=""; GUEST_DISK=""; GUEST_DISK_SHA=""
PROC_ROOT="${PROC_ROOT:-/proc}"   # overridable for tests only, like SYSFS_CPU
m_pin_qemu() {      # $1 = core spec for every QEMU thread
	local want="$1" pids n t
	pids="$(m_pids_of qemu-system-aarch64)"
	n="$(printf '%s\n' "$pids" | grep -c . || true)"
	[ "$n" -eq 1 ] || die "expected exactly 1 qemu-system-aarch64, found $n"
	QPID="$pids"
	for t in $(ls "/proc/$QPID/task"); do
		sudo taskset -pc "$want" "$t" >/dev/null 2>&1 || die "taskset failed on qemu thread $t"
	done
	QTHREADS="$(ls "/proc/$QPID/task" | wc -l)"
	QAFF="$(taskset -pc "$QPID" 2>/dev/null | sed 's/.*: //')"
	[ -n "$QAFF" ] || die "could not read QEMU affinity back -- pinning unverified"
	[ "$(_cpuset "$QAFF")" = "$(_cpuset "$want")" ] \
		|| die "QEMU affinity reads back '$QAFF', asked for '$want'"
	# REVIEW FINDING: the version was taken from whatever qemu-system-aarch64
	# is first on PATH, which need not be the binary that is actually running.
	QEXE="$(readlink -f "/proc/$QPID/exe" 2>/dev/null)"
	QVER="$("$QEXE" --version 2>/dev/null | head -1)"
	say "qemu pid=$QPID pinned to $want (readback '$QAFF', $QTHREADS threads) exe=$QEXE"
	_guest_identity
}
# ADDED 2026-09-22. The stamp named QEMU but not the GUEST: which image it
# booted, from which disk, and when that QEMU process started. The 2026-09-21
# ladder record could not say which image it ran, and "the same guest boot as the
# earlier campaigns" rested on the operator's word. OD12's UDP arms need a new
# image, so the image is now identified by hash in every stamp, read from the
# running process's own command line rather than from a path someone typed.
#
# REVIEW FINDINGS, 2026-09-22: a path QEMU was given relative is resolved against
# QEMU's own working directory, not this script's; the disk is taken only from
# the argument after -drive; and a file that cannot be read, or that changed
# after QEMU started, refuses the run -- its hash would name a different image
# from the one that booted.
_guest_identity() {
	local a prev="" ticks btime cwd start_epoch f m
	[ "$PROC_ROOT" = /proc ] || say "WARNING: PROC_ROOT overridden to $PROC_ROOT -- test use only"
	GUEST_IFS=""; GUEST_DISK=""
	while IFS= read -r -d '' a; do
		[ "$prev" = "-kernel" ] && GUEST_IFS="$a"
		if [ "$prev" = "-drive" ]; then
			case "$a" in *if=pflash*) ;; *file=*) GUEST_DISK="${a#*file=}"; GUEST_DISK="${GUEST_DISK%%,*}" ;; esac
		fi
		prev="$a"
	done < "$PROC_ROOT/$QPID/cmdline"
	cwd="$(readlink -f "$PROC_ROOT/$QPID/cwd" 2>/dev/null)"
	case "$GUEST_IFS" in /*|[A-Za-z]:/*|"") ;; *) GUEST_IFS="$cwd/$GUEST_IFS" ;; esac
	case "$GUEST_DISK" in /*|[A-Za-z]:/*|"") ;; *) GUEST_DISK="$cwd/$GUEST_DISK" ;; esac
	[ -n "$GUEST_IFS" ] || die "the running QEMU has no -kernel argument -- the guest image cannot be identified"
	GUEST_IFS_SHA="$(_sha "$GUEST_IFS")"
	[ "$GUEST_IFS_SHA" != unreadable ] || die "cannot read the guest image QEMU booted: $GUEST_IFS"
	if [ -n "$GUEST_DISK" ]; then
		GUEST_DISK_SHA="$(_sha "$GUEST_DISK")"
		[ "$GUEST_DISK_SHA" != unreadable ] || die "cannot read the guest disk QEMU was given: $GUEST_DISK"
	else
		GUEST_DISK_SHA="absent"
	fi
	ticks="$(awk '{print $22}' "$PROC_ROOT/$QPID/stat" 2>/dev/null)"
	btime="$(awk '/^btime/ {print $2}' "$PROC_ROOT/stat" 2>/dev/null)"
	if [ -n "$ticks" ] && [ -n "$btime" ]; then
		start_epoch=$(( btime + ticks / $(getconf CLK_TCK) ))
		QSTART="$(date -u -d "@$start_epoch" +%Y-%m-%dT%H:%M:%SZ)"
		for f in "$GUEST_IFS" "$GUEST_DISK"; do
			[ -n "$f" ] || continue
			m="$(stat -c %Y "$f" 2>/dev/null)"
			[ -z "$m" ] || [ "$m" -le "$start_epoch" ] \
				|| die "$f changed after QEMU started ($QSTART) -- its hash would not be the image that booted"
		done
	fi
	say "guest image ${GUEST_IFS##*/} $(printf %.12s "$GUEST_IFS_SHA"), disk ${GUEST_DISK##*/} $(printf %.12s "$GUEST_DISK_SHA"), qemu started ${QSTART:-unknown}"
}

m_reachable() {     # $1 host  $2 port  $3 label
	timeout 3 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null \
		|| die "UNREACHABLE: $3 ($1:$2)"
	say "reachable: $3 ($1:$2)"
}
# UDP has no connection to open, so "reachable" means one framed datagram came
# back: the probe's own recovery exchange, with a short deadline. A port with no
# server answers with ICMP unreachable or nothing, and both fail this.
m_reachable_udp() { # $1 host  $2 port  $3 label
	local log=/dev/null rc
	[ -n "${OUT:-}" ] && log="$OUT/probe.log"
	python3 "$PROBE" --host "$1" --port "$2" --proto udp --await-recovery 5 >> "$log" 2>&1
	rc=$?
	case "$rc" in
		0) say "reachable: $3 ($1:$2/udp)" ;;
		4) die "UNREACHABLE: $3 ($1:$2/udp) -- no framed reply in 5 s" ;;
		*) die "the UDP check for $3 could not run (probe exit $rc) -- is $PROBE older than --proto? see $log" ;;
	esac
}
# A shm slot (OD12, 2026-09-22) likewise: "reachable" means one framed round
# trip through it completed. A slot with no server behind it -- no magic, or a
# magic left by a server that died -- fails this within 5 s.
m_reachable_shm() { # $1 shm file  $2 label
	local log=/dev/null rc
	[ -n "${OUT:-}" ] && log="$OUT/probe.log"
	[ -n "${SHMCHAN_LIB:-}" ] || die "m_reachable_shm: SHMCHAN_LIB unset -- call m_build_shmchan first"
	python3 "$PROBE" --proto shm --shm "$1" --shm-lib "$SHMCHAN_LIB" --tag "$2" --await-recovery 5 >> "$log" 2>&1
	rc=$?
	case "$rc" in
		0) say "reachable: $2 ($1, shm)" ;;
		4) die "UNREACHABLE: $2 ($1, shm) -- no framed reply in 5 s" ;;
		*) die "the shm check for $2 could not run (probe exit $rc) -- see $log" ;;
	esac
}
# The notified variants (OD12, 2026-09-22): one framed round trip through the
# slot and the kick channel -- for shmdb after the probe's doorbell handshake --
# or, for kickecho, one echoed byte.
m_reachable_notified() {  # $1 label  $2 proto  $3 slot spec (or -)  $4 kick socket  [$5 ivshmem server]
	local log=/dev/null rc args=(--proto "$2" --kick "$4" --shm-lib "${SHMCHAN_LIB:?SHMCHAN_LIB unset -- call m_build_shmchan first}")
	[ -n "${OUT:-}" ] && log="$OUT/probe.log"
	[ "$2" != kickecho ] && args+=(--shm "$3")
	[ "$2" = shmdb ] && args+=(--ivshm "${5:?m_reachable_notified: shmdb needs the ivshmem server}")
	python3 "$PROBE" "${args[@]}" --tag "$1" --await-recovery 5 >> "$log" 2>&1
	rc=$?
	case "$rc" in
		0) say "reachable: $1 ($2 via $4)" ;;
		4) die "UNREACHABLE: $1 ($2 via $4) -- no notified reply in 5 s" ;;
		*) die "the $2 check for $1 could not run (probe exit $rc) -- see $log" ;;
	esac
}

# ------------------------------------------------------------- counterbalance
# A WILLIAMS DESIGN over the loaded middle arms, with idle fixed first and
# idle2 fixed last in every round.
#
# Loaded arms carry heat into whatever runs next. In a fixed order, the same arm
# always inherits the same neighbour's heat, and k repetitions of that bias give
# a tight band around a wrong number. REVIEW FINDING: the first draft reversed
# the middle arms on alternate rounds. That balances POSITION -- every arm's
# average slot in the round is the same, cancelling a linear drift across the
# round -- and for two arms it also balances carryover. For five it does NOT:
# which arm precedes which stays uneven, and the imbalance fell on cpu6_prio and
# gpu_cpu6. A Williams design makes every ordered pair of distinct arms adjacent
# equally often, which is what first-order carryover balance means.
#
# Construction: base row 0, 1, n-1, 2, n-2, ...; row i adds i mod n. For odd n
# the reversal of every row is added too, so the PERIOD is n for even n and 2n
# for odd n. K must be a multiple of the period, or the balance is broken and the
# stamp's claim is false -- m_require_balanced_k refuses otherwise.
_williams_base() {  # $1 n
	local n="$1" lo=1 hi=$(( $1 - 1 )) t=1 out=(0)
	while [ "${#out[@]}" -lt "$n" ]; do
		if [ "$t" -eq 1 ]; then out+=("$lo"); lo=$((lo+1)); else out+=("$hi"); hi=$((hi-1)); fi
		t=$((1-t))
	done
	echo "${out[@]}"
}
m_williams_period() {   # $1 n
	if [ $(( $1 % 2 )) -eq 0 ]; then echo "$1"; else echo $(( 2 * $1 )); fi
}
m_require_balanced_k() {  # $1 k  $2 n loaded arms
	local p; p="$(m_williams_period "$2")"
	[ $(( $1 % p )) -eq 0 ] \
		|| die "K=$1 is not a multiple of $p, the Williams period for $2 loaded arms; carryover would not be balanced"
}
# The Williams row for round r over n items, as indices 0..n-1. Lifted out of
# m_round_order on 2026-09-22 so the ladder can order its TRANSPORTS with the
# same design; m_round_order's output is unchanged (the tests pin it).
m_williams_row() {  # $1 round  $2 n
	local r="$1" n="$2" base period row rev i seq=()
	read -r -a base <<< "$(_williams_base "$n")"
	period="$(m_williams_period "$n")"
	row=$(( (r - 1) % period ))
	rev=0
	if [ "$row" -ge "$n" ]; then rev=1; row=$(( row - n )); fi
	for i in "${base[@]}"; do seq+=( $(( (i + row) % n )) ); done
	if [ "$rev" -eq 1 ]; then
		for ((i=${#seq[@]}-1; i>=0; i--)); do printf '%s ' "${seq[i]}"; done
	else
		printf '%s ' "${seq[@]}"
	fi
	echo
}
m_round_order() {   # $1 round, then: first  middle...  last
	local r="$1"; shift
	local first="$1"; shift
	local n=$(( $# - 1 )) last="${!#}"
	local mid=("${@:1:$n}")
	local idx out=("$first")
	for idx in $(m_williams_row "$r" "$n"); do out+=("${mid[$idx]}"); done
	out+=("$last")
	echo "${out[@]}"
}

# ------------------------------------------------------------- the stamp
# $1 = output path; remaining args = extra "key": value lines.
# Hashes every binary that produced a number -- REVIEW FINDING: the first draft
# hashed none of the probe or the load generators, so the stamp could not say
# which instrument measured the run. The python3 that sudo resolves is recorded
# separately because cpu6_prio runs the probe through sudo and may get another.
_sha() { [ -r "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo "unreadable"; }
m_write_stamp() {
	local out="$1"; shift
	{
		printf '{\n'
		printf '  "utc": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		printf '  "script": "%s",\n' "$(basename "$0")"
		printf '  "script_sha256": "%s",\n' "$(_sha "$0")"
		printf '  "lib_sha256": "%s",\n' "$(_sha "${BASH_SOURCE[0]}")"
		printf '  "probe_sha256": "%s",\n' "$(_sha "${PROBE:-}")"
		printf '  "python3": "%s",\n' "$(command -v python3)"
		printf '  "python3_under_sudo": "%s",\n' "$(sudo -n sh -c 'command -v python3' 2>/dev/null || echo unavailable)"
		printf '  "machine": "%s",\n' "$(uname -m)"
		printf '  "kernel": "%s",\n' "$(uname -r)"
		printf '  "ncpu": %s,\n' "${NCPU:-0}"
		printf '  "sysfs_cpu": "%s",\n' "$SYSFS_CPU"
		printf '  "governor_state": "%s",\n' "$GOV_STATE"
		printf '  "governor_before": "%s",\n' "$PRE_GOV"
		printf '  "cur_freq_khz_before": "%s",\n' "$FREQ_BEFORE"
		printf '  "cpuidle": "%s",\n' "$([ -d "$SYSFS_CPU/cpu0/cpuidle" ] && echo present || echo absent)"
		printf '  "cstate_policy": "%s",\n' "$CSTATE_STATE"
		printf '  "cstate_exposed": "%s",\n' "$CSTATE_EXPOSED"
		printf '  "cstate_disabled": "%s",\n' "$CSTATE_DISABLED"
		printf '  "qemu_exe": "%s",\n' "$QEXE"
		printf '  "qemu_version": "%s",\n' "$QVER"
		if [ -n "$QPID" ] && [ -r "/proc/$QPID/cmdline" ]; then
			printf '  "qemu_cmdline": "%s",\n' "$(tr '\0' ' ' < "/proc/$QPID/cmdline" | sed 's/"/\\"/g')"
		fi
		printf '  "qemu_threads": %s,\n' "$QTHREADS"
		printf '  "qemu_affinity": "%s",\n' "$QAFF"
		printf '  "qemu_pid": "%s", "qemu_started": "%s",\n' "$QPID" "$QSTART"
		printf '  "guest_ifs": "%s", "guest_ifs_sha256": "%s",\n' "$GUEST_IFS" "$GUEST_IFS_SHA"
		printf '  "guest_disk": "%s", "guest_disk_sha256": "%s",\n' "$GUEST_DISK" "$GUEST_DISK_SHA"
		printf '  "udp_arms": "%s",\n' "${UDP_ARMS:-}"
		printf '  "sample_window": %s,\n' "${SAMPLE_WINDOW:-0}"
		if [ "${SAMPLE_WINDOW:-0}" = 1 ]; then
			printf '  "sampler_paths": {"emc_bpmp": "%s", "emc_ccf": "%s", "gpu_devfreq": "%s"},\n' \
				"$EMC_BPMP" "$EMC_CCF" "$GPU_DEVFREQ"
		fi
		printf '  "fifo_arms": "%s",\n' "${FIFO_ARMS:-}"
		printf '  "stall_policy": "%s", "probe_timeout_s": %s, "recover_max_s": %s,\n' \
			"${STALL_POLICY:-refuse}" "$PROBE_TIMEOUT_S" "$RECOVER_MAX_S"
		local kv; for kv in "$@"; do printf '  %s,\n' "$kv"; done
		printf '  "n": %s, "k": %s, "warmup": %s, "interval_ms": %s\n' "$N" "$K" "$WARMUP" "$INTERVAL_MS"
		printf '}\n'
	} > "$out"
	python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null \
		|| die "stamp is not valid JSON: $out"
	say "stamp written and parsed: $out"
}

# Appended after the run, so the stamp records the END state as well as the start.
m_stamp_after() {   # $1 = stamp path
	python3 - "$1" "$GOV_AFTER" "$FREQ_AFTER" <<'PY' || die "could not append the after-state to the stamp"
import json, sys
p, gov, freq = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(p))
d["governor_after"] = gov or None
d["cur_freq_khz_after"] = freq or None
json.dump(d, open(p, "w"), indent=2)
PY
}

# ------------------------------------------------------------- the probe call
# REVIEW FINDING: the scripts wrapped the probe in `|| echo "ARM FAILED"` and
# kept going. A failed arm is a failed run. The probe now aborts on a
# desynchronised stream and writes no file (see latency_probe.py), and any
# non-zero exit here stops the run.
#
# ONE EXCEPTION, decided by the owner on 2026-09-21: a STALL. A board dry run
# found that with QEMU's threads squeezed onto one core, the guest can stop
# answering for longer than the probe's timeout -- and then recover. Under the
# rule above that stopped the whole campaign at the first stall, and the finding
# would have produced no data at all. With STALL_POLICY=record, a probe that
# exits EXIT_DESYNC (3) AND wrote its stall record is an OUTCOME: m_probe
# returns 3, the caller stops the load and calls m_await_recovery, and the run
# goes on. Only a TIMEOUT is a stall -- no reply, or no connect, within
# PROBE_TIMEOUT_S. A reset, a broken pipe or lost framing exits 5 with no
# record and stops the run like any other failure (found by review: they used
# to be filed as stalls). So does a stall without a record. The ladder does not
# set STALL_POLICY: its figures are headlines, and a stall there is a failure.
PROBE_TIMEOUT_S="${PROBE_TIMEOUT_S:-10}"
RECOVER_MAX_S="${RECOVER_MAX_S:-120}"
# KVM COUNTERS (OD12, 2026-09-22; FOUND BY DESIGN REVIEW). A record may say an
# access or a doorbell stays in the kernel only if it can SHOW it. Around every
# arm, with KVM_STATS=1: the VM's debugfs counters (exits, mmio_exit_kernel,
# mmio_exit_user, halt polling, wakeups -- VM-wide, so background included) and
# each QEMU thread's schedstat (run time, run-queue wait), with CLOCK_MONOTONIC
# at each snapshot so deltas can be normalised by time. Read as root from core
# CORE_AUX, never the measured cores. "before" waits 100 ms first, longer than
# the polled monitor's 50 ms spin tail, so one arm's tail is not charged to the
# next. Exactly one debugfs directory must match the running QEMU.
KVM_DEBUGFS="${KVM_DEBUGFS:-/sys/kernel/debug/kvm}"   # overridable for tests only
KVM_COUNTERS="exits mmio_exit_kernel mmio_exit_user halt_wakeup wfi_exit_stat wfe_exit_stat signal_exits halt_attempted_poll halt_successful_poll halt_poll_invalid halt_poll_success_ns halt_poll_fail_ns halt_wait_ns"
m_kvm_snap() {       # $1 json file  $2 before|after
	local qp dirs raw
	qp="${KVM_QEMU_PID:-$(m_pids_of qemu-system-aarch64)}"    # KVM_QEMU_PID: tests only
	# m_pids_of prints one pid per LINE; count lines, not spaces (FOUND BY CODE REVIEW).
	[ -n "$qp" ] && [ "$(printf '%s\n' "$qp" | grep -c .)" = 1 ] \
		|| die "m_kvm_snap: need exactly one qemu-system-aarch64 (have: $(printf '%s' "$qp" | tr '\n' ' '))"
	[ "$2" = before ] && sleep 0.1
	dirs="$(sudo -n sh -c "ls -d $KVM_DEBUGFS/${qp}-* 2>/dev/null")"
	[ -n "$dirs" ] && [ "$(printf '%s\n' "$dirs" | wc -l)" = 1 ] \
		|| die "m_kvm_snap: expected one $KVM_DEBUGFS/${qp}-* directory, found: '$dirs'"
	# taskset OUTSIDE sudo: the reader inherits the affinity either way.
	raw="$(taskset -c "${CORE_AUX:-5}" sudo -n sh -c 'cd "$1"; shift; for f in "$@"; do printf "%s %s\n" "$f" "$(cat "$f" 2>/dev/null || echo NA)"; done' _ "$dirs" $KVM_COUNTERS)" \
		|| die "m_kvm_snap: could not read $dirs"
	KS_RAW="$raw" KS_QP="$qp" KS_WHEN="$2" KS_PROC="$PROC_ROOT" python3 - "$1" <<'PY' || die "m_kvm_snap: could not write $1"
import glob, json, os, sys, time
path, when = sys.argv[1], os.environ["KS_WHEN"]
snap = {"t_ns": time.monotonic_ns(), "qemu_pid": int(os.environ["KS_QP"]), "counters": {}, "threads": {}}
for line in os.environ["KS_RAW"].splitlines():
    k, _, v = line.partition(" ")
    snap["counters"][k] = int(v) if v.strip().lstrip("-").isdigit() else None
proc = os.environ["KS_PROC"]
for f in glob.glob("%s/%s/task/*/schedstat" % (proc, os.environ["KS_QP"])):
    tid = os.path.basename(os.path.dirname(f))
    try:
        run_ns, wait_ns, slices = (int(x) for x in open(f).read().split())
        comm = open("%s/%s/task/%s/comm" % (proc, os.environ["KS_QP"], tid)).read().strip()
    except (OSError, ValueError):
        continue
    snap["threads"][tid] = {"comm": comm, "run_ns": run_ns, "wait_ns": wait_ns, "slices": slices}
doc = {}
if when == "after":
    doc = json.load(open(path))
    if doc.get("before", {}).get("qemu_pid") != snap["qemu_pid"]:
        sys.exit("QEMU changed during the arm")
doc[when] = snap
json.dump(doc, open(path, "w"))
PY
}
# THE DOORBELL PROOF (OD12, 2026-09-22): read a --db-burst result and the KVM
# snapshots around it, print the stamp fragment, and succeed only if all WANT
# doorbells arrived, the VM's mmio_exit_kernel rose by at least WANT (a KVM
# ioeventfd caught them in the kernel) and mmio_exit_user by less than a tenth
# of WANT (they did not take QEMU's userspace path). In the library, not inline
# in the ladder, so a test can hold it to that (FOUND BY CODE REVIEW).
m_db_proof() {      # $1 out dir (db-burst.json, db-burst-kvm.json)  $2 WANT
	python3 - "$1" "$2" <<'PY'
import json, sys
out, want = sys.argv[1], int(sys.argv[2])
try:
    b = json.load(open(out + "/db-burst.json"))["burst"]
    k = json.load(open(out + "/db-burst-kvm.json"))
    d = {}
    for c in ("mmio_exit_kernel", "mmio_exit_user", "exits"):
        x, y = k["before"]["counters"].get(c), k["after"]["counters"].get(c)
        d[c] = None if x is None or y is None else y - x
except Exception as e:
    print('"run": 1, "ok": false, "error": "%s"' % str(e).replace('"', "'"))
    sys.exit(1)
ok = (b.get("got") == want and d["mmio_exit_kernel"] is not None and d["mmio_exit_user"] is not None
      and d["mmio_exit_kernel"] >= want and d["mmio_exit_user"] * 10 < want)
print('"run": 1, "want": %d, "got": %s, "d_mmio_exit_kernel": %s, "d_mmio_exit_user": %s, "d_exits": %s, "ok": %s'
      % (want, json.dumps(b.get("got")), json.dumps(d["mmio_exit_kernel"]), json.dumps(d["mmio_exit_user"]),
         json.dumps(d["exits"]), "true" if ok else "false"))
sys.exit(0 if ok else 1)
PY
}
m_probe() {         # $1 out-dir  $2 tag  $3 host  $4 port  [$5 prefix command]  [$6 tcp|udp|shm|shmkick|shmdb|kickecho]  [$7 ivshmem server]
	local out="$1" tag="$2" host="$3" port="$4" pre="${5:-}" proto="${6:-tcp}" rc t0 t1 ms stall=() dest
	# shm (OD12, 2026-09-22): "host" is the shared-memory file, and the port is unused.
	# The notified variants: "host" is the slot (FILE@OFFSET, unused by kickecho),
	# "port" the kick socket, and $7 the ivshmem server for shmdb.
	case "$proto" in
		shm|shmkick|shmdb|kickecho)
			[ -n "${SHMCHAN_LIB:-}" ] || die "m_probe $tag: SHMCHAN_LIB unset -- call m_build_shmchan first"
			dest=(--shm-lib "$SHMCHAN_LIB")
			[ "$proto" != kickecho ] && dest+=(--shm "$host")
			[ "$proto" != shm ] && dest+=(--kick "$port")
			[ "$proto" = shmdb ] && dest+=(--ivshm "${7:?m_probe $tag: shmdb needs the ivshmem server}")
			;;
		*) dest=(--host "$host" --port "$port") ;;
	esac
	rm -f "$out/lat-$tag.json" "$out/stall-$tag.json"
	[ "${STALL_POLICY:-refuse}" = record ] && stall=(--stall-out "$out/stall-$tag.json")
	# The window sampler brackets exactly the probe, when the script asked for
	# it (SAMPLE_WINDOW=1). Off by default: the ladder's numbers are the
	# headline, and a new process running beside them is a new perturbation.
	[ "${SAMPLE_WINDOW:-0}" = 1 ] && m_sampler_start "$tag"
	[ "${KVM_STATS:-0}" = 1 ] && m_kvm_snap "$out/kvm-$tag.json" before
	t0="$(date +%s%N)"
	$pre taskset -c "$CORE_PROBE" python3 "$PROBE" "${dest[@]}" \
		--n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" --timeout-s "$PROBE_TIMEOUT_S" --proto "$proto" \
		"${stall[@]}" --tag "$tag" --out "$out/lat-$tag.json" >> "$out/probe.log" 2>&1
	rc=$?
	t1="$(date +%s%N)"
	[ "${KVM_STATS:-0}" = 1 ] && m_kvm_snap "$out/kvm-$tag.json" after
	ms=$(( (t1 - t0) / 1000000 ))
	if [ "${SAMPLE_WINDOW:-0}" = 1 ]; then
		m_sampler_stop || die "the window sampler for $tag would not stop -- it would run on into the next arm"
	fi
	if [ "$rc" -eq 3 ] && [ "${STALL_POLICY:-refuse}" = record ]; then
		[ -s "$out/stall-$tag.json" ] || die "probe stopped on $tag (exit 3) but wrote no stall record -- see $out/probe.log"
		[ -e "$out/lat-$tag.json" ] && die "probe wrote both a result and a stall record for $tag"
		[ "${SAMPLE_WINDOW:-0}" = 1 ] && m_sampler_require "$tag" "$ms"
		echo "$tag stalled after ${ms} ms: $(grep -E '^FATAL desync tag='"$tag"' ' "$out/probe.log" | tail -1)" >> "$out/stalls.log"
		say "STALL on $tag: no reply within ${PROBE_TIMEOUT_S} s -- recorded as an outcome; the run goes on"
		return 3
	fi
	[ "$rc" -eq 0 ] || die "probe failed on $tag (exit $rc) -- see $out/probe.log; the run stops here"
	[ -s "$out/lat-$tag.json" ] || die "probe exited 0 but wrote no file for $tag"
	[ "${SAMPLE_WINDOW:-0}" = 1 ] && m_sampler_require "$tag" "$ms"
	return 0
}
# After a stall, with the arm's load already stopped: time until the guest
# answers one framed echo again, written to recovery-<tag>.json. A guest that
# does not answer within RECOVER_MAX_S stops the run -- the next arm would be
# measuring a guest that is not there.
m_await_recovery() {  # $1 out-dir  $2 tag  $3 host  $4 port  [$5 tcp|udp|shm]
	local out="$1" tag="$2" rc dest=(--host "$3" --port "$4")
	[ "${5:-tcp}" = shm ] && dest=(--shm "$3" --shm-lib "${SHMCHAN_LIB:?SHMCHAN_LIB unset}")
	taskset -c "$CORE_PROBE" python3 "$PROBE" "${dest[@]}" --tag "$tag" --proto "${5:-tcp}" \
		--await-recovery "$RECOVER_MAX_S" --out "$out/recovery-$tag.json" >> "$out/probe.log" 2>&1
	rc=$?
	echo "$tag recovery: $(tail -1 "$out/probe.log")" >> "$out/stalls.log"
	[ "$rc" -eq 0 ] || die "the guest did not answer within ${RECOVER_MAX_S} s after the $tag stall -- see $out/stalls.log"
	say "$tag: guest answering again ($(tail -1 "$out/probe.log"))"
}

# ------------------------------------------------------------- completeness
# REVIEW FINDING, twice over: counting files proves nothing about which run
# wrote them, and a file that exists proves nothing about what is in it. The
# gate now requires the EXACT set r1..rK, every file newer than this run's
# stamp, and every file's own summary to say it is a full, clean sample: the
# requested n and warm-up, zero bad frames, zero monitor rejections, and the
# tag it is named for.
#
# ADDED 2026-09-21: every file must also carry the probe's OWN report of how it
# was scheduled. An arm in FIFO_ARMS must say SCHED_FIFO at priority 50, every
# other arm SCHED_OTHER, and every arm's affinity must be exactly CORE_PROBE.
# Before this, cpu6_prio's real-time priority was established only by procedure,
# and an independent analysis rightly called the control uninformative.
# CORE_PROBE unset is a refusal, not a skip.
#
# STALLS (2026-09-21): with STALL_POLICY=record, a round may hold a stall record
# INSTEAD of a result -- never both, never neither -- and the record must carry
# the same scheduling report and be followed by a recovery record that says the
# guest answered again. Without that policy a stall record is itself a refusal.
m_require_complete() {  # $1 = out dir, then arm tags
	local out="$1"; shift
	[ -n "${CORE_PROBE:-}" ] || die "m_require_complete needs CORE_PROBE to check the probe's affinity"
	MP_CORE="$CORE_PROBE" MP_FIFO="${FIFO_ARMS:-}" MP_STALL="${STALL_POLICY:-refuse}" MP_UDP="${UDP_ARMS:-}" \
	MP_SHM="${SHM_ARMS:-}" MP_KICK="${KICK_ARMS:-}" MP_DB="${DB_ARMS:-}" MP_ECHO="${ECHO_ARMS:-}" \
	MP_KVM="${KVM_STATS:-0}" \
	MP_TIMEOUT="$PROBE_TIMEOUT_S" \
	python3 - "$out" "$K" "$N" "$WARMUP" "$@" <<'PY' || die "the run is incomplete or unclean -- do not publish a median from it"
import json, os, sys
out, k, n, warmup, arms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:]
probe_core = int(os.environ["MP_CORE"])
fifo_arms = set(os.environ.get("MP_FIFO", "").split())
udp_arms = set(os.environ.get("MP_UDP", "").split())
shm_arms = set(os.environ.get("MP_SHM", "").split())
kick_arms = set(os.environ.get("MP_KICK", "").split())
db_arms = set(os.environ.get("MP_DB", "").split())
echo_arms = set(os.environ.get("MP_ECHO", "").split())
want_kvm = os.environ.get("MP_KVM") == "1"
record_stalls = os.environ.get("MP_STALL") == "record"
timeout_s = float(os.environ["MP_TIMEOUT"])
stalls = {}
if not os.path.exists(os.path.join(out, "stamp.json")):
    print("INCOMPLETE: no stamp.json", file=sys.stderr); sys.exit(1)
# The reference is the run's START marker, written once by m_prepare_out and
# never rewritten -- not stamp.json, which m_stamp_after rewrites at the end.
start = os.path.join(out, ".run-start")
if not os.path.exists(start):
    print("INCOMPLETE: no .run-start marker -- was the directory made by m_prepare_out?", file=sys.stderr); sys.exit(1)
t0 = os.path.getmtime(start)
problems = []
def proto_problems(tag, a, s):
    """ADDED 2026-09-22 (OD12): each file says which transport carried it. An arm
    in UDP_ARMS must say udp and every other arm tcp -- a UDP arm silently run
    over TCP would pair two copies of the same path and report a difference of
    zero as a finding. 2026-09-22: likewise shm for an arm in SHM_ARMS."""
    want = ("udp" if a in udp_arms else "shm" if a in shm_arms else "shmkick" if a in kick_arms
            else "shmdb" if a in db_arms else "kickecho" if a in echo_arms else "tcp")
    if s.get("proto") != want:
        return ["%s: proto=%r, expected %r" % (tag, s.get("proto"), want)]
    return []
def sched_problems(tag, a, s):
    """The probe's own report of how it ran, from a result or a stall record."""
    if a in fifo_arms:
        want = (("sched_policy", "SCHED_FIFO"), ("sched_priority", 50))
    else:
        want = (("sched_policy", "SCHED_OTHER"),)
    return ["%s: %s=%r, expected %r (the probe's own report)" % (tag, key, s.get(key), w)
            for key, w in want + (("cpu_affinity", [probe_core]),) if s.get(key) != w]
for a in arms:
    for r in range(1, k + 1):
        tag = "%s_r%d" % (a, r)
        p = os.path.join(out, "lat-%s.json" % tag)
        sp = os.path.join(out, "stall-%s.json" % tag)
        have, stalled = os.path.exists(p), os.path.exists(sp)
        if have and stalled:
            problems.append("%s: both a result and a stall record" % tag); continue
        if stalled:
            if not record_stalls:
                problems.append("%s: stall record, but STALL_POLICY is not 'record'" % tag); continue
            if os.path.getmtime(sp) < t0:
                problems.append("%s: stall record older than this run's start" % tag); continue
            try:
                st = json.load(open(sp))["stall"]
            except Exception as e:
                problems.append("%s: stall record unreadable (%s)" % (tag, e)); continue
            for key, want in (("tag", tag), ("warmup", warmup), ("of", warmup + n), ("timeout_s", timeout_s)):
                if st.get(key) != want:
                    problems.append("%s: stall %s=%r, expected %r" % (tag, key, st.get(key), want))
            if st.get("kind") not in ("timeout", "connect"):
                problems.append("%s: stall kind=%r" % (tag, st.get("kind")))
            problems.extend(sched_problems(tag, a, st))
            problems.extend(proto_problems(tag, a, st))
            rp = os.path.join(out, "recovery-%s.json" % tag)
            try:
                rec = json.load(open(rp))
                if rec.get("recovered") is not True or rec.get("tag") != tag:
                    problems.append("%s: recovery record does not say the guest answered again" % tag)
            except Exception as e:
                problems.append("%s: no readable recovery record (%s)" % (tag, e))
            stalls.setdefault(a, []).append(r)
            continue
        if not have:
            problems.append("%s: missing" % tag); continue
        if os.path.getmtime(p) < t0:
            problems.append("%s: older than this run's start" % tag); continue
        try:
            s = json.load(open(p))["summary"]
        except Exception as e:
            problems.append("%s: unreadable (%s)" % (tag, e)); continue
        for key, want in (("tag", tag), ("n", n), ("warmup_discarded", warmup),
                          ("bad", 0), ("rejected_by_monitor", 0)):
            if s.get(key) != want:
                problems.append("%s: %s=%r, expected %r" % (tag, key, s.get(key), want))
        problems.extend(sched_problems(tag, a, s))
        problems.extend(proto_problems(tag, a, s))
        if a in kick_arms or a in db_arms or a in echo_arms:
            # ADDED 2026-09-22 (OD12): a notified arm measured what it claims only if
            # every exchange ended on exactly one notification and nothing else woke
            # the probe. Counted by the probe itself, after its handshake.
            nt = s.get("notify") or {}
            ex = nt.get("exchanges")
            if ex != n + warmup:
                problems.append("%s: notify.exchanges=%r, expected %d" % (tag, ex, n + warmup))
            for key in ("notifications", "wakeups"):
                if nt.get(key) != ex:
                    problems.append("%s: notify.%s=%r, expected one per exchange (%r)" % (tag, key, nt.get(key), ex))
            for key in ("early_wakeups", "stray", "eagain"):
                if nt.get(key) != 0:
                    problems.append("%s: notify.%s=%r, expected 0" % (tag, key, nt.get(key)))
        if want_kvm:
            try:
                kv = json.load(open(os.path.join(out, "kvm-%s.json" % tag)))
                if not ("before" in kv and "after" in kv):
                    problems.append("%s: KVM snapshot lacks before or after" % tag)
            except Exception as e:
                problems.append("%s: no readable KVM snapshot (%s)" % (tag, e))
    for prefix in ("lat-", "stall-"):
        pre = "%s%s_r" % (prefix, a)
        for f in os.listdir(out):
            if (f.startswith(pre) and f.endswith(".json") and f[len(pre):-5].isdigit()
                    and not (1 <= int(f[len(pre):-5]) <= k)):
                problems.append("%s: round outside 1..%d" % (f, k))
for p in problems:
    print("INCOMPLETE: " + p, file=sys.stderr)
for a in arms:
    if a in stalls:
        print("STALLED: %s in %d of %d rounds (r%s) -- recorded, each followed by recovery"
              % (a, len(stalls[a]), k, ",r".join(str(r) for r in stalls[a])))
sys.exit(1 if problems else 0)
PY
	say "complete: ${#@} arm(s) x $K round(s), each round a clean result or a recorded stall, every file this run's"
}

# ------------------------------------------------------------- the summary
# measurement-design §3.6: the headline is the MEDIAN OF THE k RUN-MEDIANS with
# the observed min-max band, and a tail is never printed without k beside it.
#
# REVIEW FINDING: the first draft printed only per-arm medians, which throws
# away the within-round pairing that interleaving exists to provide. The paired
# column is the median, over rounds, of (arm - reference) measured in the SAME
# round -- the comparison that cancels between-round drift. It is not the same
# number as the difference of the two medians, and it is the one to cite for an
# effect.
m_summary() {       # $1 = out dir  $2 = reference arm for pairing, then arm tags
	local out="$1" ref="$2"; shift 2
	python3 - "$out" "$K" "$ref" "$@" <<'PY'
import glob, json, statistics as st, sys
out, k, ref, arms = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4:]
def load(a):
    d = {}
    for f in glob.glob("%s/lat-%s_r*.json" % (out, a)):
        s = json.load(open(f))["summary"]
        d[int(s["tag"].rsplit("_r", 1)[1])] = s
    return d
data = {a: load(a) for a in arms}
stalled = {a: len(glob.glob("%s/stall-%s_r*.json" % (out, a))) for a in arms}
print("  %-11s %3s  %24s  %24s  %s" % ("arm", "k", "p50 ms: median [band]",
                                        "paired vs %s: med [band]" % ref, "max ms: min/med/max of k"))
for a in arms:
    d = data[a]
    if not d:
        print("  %-11s   0  (no data)%s" % (a, "  STALLED in %d round(s)" % stalled[a] if stalled[a] else "")); continue
    p50 = [s["p50_ms"] for s in d.values()]; mx = [s["max_ms"] for s in d.values()]
    if a != ref and ref in data:
        diffs = [d[r]["p50_ms"] - data[ref][r]["p50_ms"] for r in d if r in data[ref]]
        pair = "%+7.3f [%+.3f,%+.3f]" % (st.median(diffs), min(diffs), max(diffs))
    else:
        pair = "(reference)"
    print("  %-11s %3d  %7.3f [%6.3f-%6.3f]  %24s  %.3f / %.3f / %.3f%s"
          % (a, len(d), st.median(p50), min(p50), max(p50), pair, min(mx), st.median(mx), max(mx),
             "  + STALLED in %d round(s), not in k" % stalled[a] if stalled[a] else ""))
print("  headline = median of the k run-medians. 'paired' = median over rounds of (arm - %s) in the SAME round." % ref)
print("  'max' is the largest OBSERVED value in each round, never a bound.")
if any(stalled.values()):
    print("  k counts complete rounds only. A stalled round has no median: the guest did not answer within")
    print("  the probe's timeout, so every figure for that arm is conditional on the guest answering.")
PY
}

# Paired contrasts between named arms (OD12): for each "arm:ref", the median
# over rounds of (arm p50 - ref p50) in the SAME round, its band, and how many
# rounds lie above zero -- the estimator the records cite. m_summary pairs every
# arm against ONE reference; the UDP rungs need each paired with its own TCP
# rung, which m_summary cannot express.
m_pairs() {         # $1 = out dir, then arm:ref ...
	local out="$1"; shift
	python3 - "$out" "$@" <<'PY'
import glob, json, statistics as st, sys
out, pairs = sys.argv[1], sys.argv[2:]
def load(a):
    d = {}
    for f in glob.glob("%s/lat-%s_r*.json" % (out, a)):
        s = json.load(open(f))["summary"]
        d[int(s["tag"].rsplit("_r", 1)[1])] = s["p50_ms"] * 1000.0
    return d
print("  %-24s %4s  %26s  %s" % ("paired p50, arm - ref", "k", "median us [band]", "rounds above 0"))
for pr in pairs:
    a, r = pr.split(":", 1)
    x, y = load(a), load(r)
    rounds = sorted(set(x) & set(y))
    if not rounds:
        print("  %-24s    0  (no round where both completed)" % pr); continue
    d = [x[k] - y[k] for k in rounds]
    print("  %-24s %4d  %+8.1f [%+7.1f, %+7.1f]  %d/%d" % (
        a + " - " + r, len(d), st.median(d), min(d), max(d), sum(v > 0 for v in d), len(d)))
PY
}

# ------------------------------------------------------------- the window sampler
# ADDED 2026-09-21 to close two gaps an independent analysis named. Load
# placement was read from ONE tegrastats sample taken before each probe
# started, and could change once it began -- identical sampled placements gave
# both cost regimes. And the memory-controller (EMC) clock, the leading
# hypothesis for why a GPU load speeds the guest up, was never recorded at all.
# So each probe window is now traced continuously, every 500 ms:
#   tegra-<tag>.log  tegrastats AS ROOT: per-core CPU % and MHz, EMC_FREQ
#                    (memory-controller utilisation % and clock), GR3D % and
#                    clock, temperatures
#   clk-<tag>.log    EMC rate from BOTH debugfs sources, which disagree on this
#                    board -- BPMP said 2133 MHz, the kernel clock framework
#                    204 MHz; tegrastats' own EMC clock agrees with BPMP -- plus
#                    the GPU devfreq clock.
# tegrastats prints EMC_FREQ and the GR3D clock only when it runs as root. The
# first draft ran it as the user and concluded "this JetPack build has no EMC
# field"; a review asked, and one board command showed the field is there under
# root. m_thermal and m_gpu_busy_pct still run it as the user, which is enough
# for per-core CPU and GR3 busy.
#
# WHAT THE SAMPLER COSTS, stated rather than assumed away: root tegrastats,
# which reads dozens of sysfs and debugfs files per interval, plus a root shell
# loop -- both UNPINNED, so they run wherever the scheduler puts them, which
# differs by arm and in the cpu6 arms means on a loaded core. The loop reads
# with shell builtins and forks only `sleep`, once per 500 ms; its first draft
# forked five processes per sample. Each window must hold at least half the
# samples its length calls for, from both, or the run stops: a recorder that can
# go quiet mid-run would only move the gap, not close it.
SAMPLER_ROOT=""
# Overridable for tests only. A real run uses the defaults; an override is
# announced, and every path actually read is written to the stamp.
EMC_BPMP_DEFAULT="/sys/kernel/debug/bpmp/debug/clk/emc/rate"
EMC_CCF_DEFAULT="/sys/kernel/debug/clk/emc/clk_rate"
DEVFREQ_ROOT_DEFAULT="/sys/class/devfreq"
EMC_BPMP="${EMC_BPMP:-$EMC_BPMP_DEFAULT}"
EMC_CCF="${EMC_CCF:-$EMC_CCF_DEFAULT}"
DEVFREQ_ROOT="${DEVFREQ_ROOT:-$DEVFREQ_ROOT_DEFAULT}"
GPU_DEVFREQ=""
# Each value is cleared before it is read, so a read that fails mid-run leaves
# the field EMPTY rather than repeating the previous sample. LC_ALL=C because
# the board's locale writes a decimal comma into the timestamp.
SAMPLER_LOOP='while :; do
	a= b= c=
	read -r a < "$1"; read -r b < "$2"; read -r c < "$3"
	printf "%s emc_bpmp_hz=%s emc_ccf_hz=%s gpu_hz=%s\n" "${EPOCHREALTIME:-$(date +%s.%N)}" "$a" "$b" "$c"
	sleep 0.5
done'
m_sampler_start() {  # $1 = tag
	local t="$1" ceil root
	# The ceiling follows the probe's nominal length plus a wide margin: long
	# enough that a slow probe cannot outlast its sampler, short enough that a
	# dead run cannot leave one behind for long.
	ceil=$(( (${N:-1000} + ${WARMUP:-200}) * ${INTERVAL_MS:-2} / 1000 + ${PROBE_TIMEOUT_S:-10} + 120 ))
	# FOUND ON THE BOARD, 2026-09-21, by the first smoke test -- the unit tests'
	# sudo stub could not show it. The loop used to run as a background
	# `sudo -n timeout ...` and be stopped with `sudo -n kill <sudo's pid>`. sudo
	# before 1.9.13 -- the board has 1.9.9 -- does not relay a signal sent from a
	# process in sudo's OWN process group, and the script, both sudos and the
	# kill all shared it: the stop was ignored, `wait` blocked until the 122 s
	# ceiling, and the loop wrote on through it. Now a short sudo starts
	# `timeout` in the background and prints its pid. timeout leads its own
	# process group and forwards a TERM to all of it, so it is signalled directly.
	root="$(sudo -n bash -c 'timeout "$1" tegrastats --interval 500 > "$2" 2>/dev/null & echo $!' \
		_ "$ceil" "$OUT/tegra-$t.log" 2>/dev/null)"
	SAMPLER_ROOT="$SAMPLER_ROOT $root"
	root="$(sudo -n bash -c 'timeout "$1" env LC_ALL=C bash -c "$2" _ "$3" "$4" "$5" > "$6" 2>/dev/null & echo $!' \
		_ "$ceil" "$SAMPLER_LOOP" "$EMC_BPMP" "$EMC_CCF" "$GPU_DEVFREQ" "$OUT/clk-$t.log" 2>/dev/null)"
	SAMPLER_ROOT="$SAMPLER_ROOT $root"
}
# Returns non-zero if a sampler survived, and never dies: it also runs from the
# cleanup trap, where a die would skip restoring the governor and idle states.
m_sampler_stop() {
	local p i rc=0
	for p in $SAMPLER_ROOT; do
		sudo -n kill -TERM "$p" 2>/dev/null
		for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
			[ -d "/proc/$p" ] || break
			sleep 0.1
		done
		if [ -d "/proc/$p" ]; then
			sudo -n kill -KILL -- "-$p" 2>/dev/null
			sleep 0.2
			if [ -d "/proc/$p" ]; then
				echo "WARNING: window sampler $p is still running after TERM and KILL" >&2; rc=1
			fi
		fi
	done
	SAMPLER_ROOT=""
	return "$rc"
}
# One window's trace must hold COMPLETE clock lines -- all three values present
# -- and tegrastats lines with per-core CPU and EMC_FREQ, at least HALF as many
# as the window's length calls for at 2 per second (tegrastats one fewer: its
# first line comes a full interval in), and never fewer than one. Checked after
# every probe, not only in the preflight: sudo's cached credential or a debugfs
# node can go away mid-run, and one sample at the start of a 3 s window is not
# "traced across the window". FOUND BY REVIEW: the first version asked for one.
m_sampler_require() {  # $1 = tag  [$2 = window length in ms]
	local t="$1" ms="${2:-0}" need clk tg
	need=$(( ms / 1000 )); [ "$need" -ge 1 ] || need=1
	clk="$(grep -cE '^[0-9.]+ emc_bpmp_hz=[0-9]+ emc_ccf_hz=[0-9]+ gpu_hz=[0-9]+$' "$OUT/clk-$t.log" 2>/dev/null)"
	tg="$(grep -cE 'CPU \[.*EMC_FREQ [0-9]+%@[0-9]+' "$OUT/tegra-$t.log" 2>/dev/null)"
	[ "${clk:-0}" -ge "$need" ] \
		|| die "the clock sampler recorded ${clk:-0} complete reading(s) during $t, fewer than $need for a ${ms} ms window (see $OUT/clk-$t.log)"
	[ "${tg:-0}" -ge $(( need > 1 ? need - 1 : 1 )) ] \
		|| die "tegrastats recorded ${tg:-0} line(s) with per-core CPU and EMC_FREQ during $t, too few for a ${ms} ms window -- is it running as root?"
}
# Run both samplers for ~1.5 s before round 1 and refuse the run if any source
# produced nothing usable, naming which one.
m_sampler_preflight() {
	local d v
	for v in EMC_BPMP EMC_CCF DEVFREQ_ROOT; do
		d="${v}_DEFAULT"
		[ "${!v}" = "${!d}" ] || say "WARNING: $v overridden to ${!v} -- recorded in the stamp"
	done
	GPU_DEVFREQ=""
	for d in "$DEVFREQ_ROOT"/*; do
		case "$(cat "$d/name" 2>/dev/null)$(basename "$d")" in *gpu*) GPU_DEVFREQ="$d/cur_freq"; break ;; esac
	done
	[ -n "$GPU_DEVFREQ" ] || die "no GPU devfreq node found -- the GPU clock would go unrecorded"
	m_sampler_start "preflight"
	sleep 1.6
	m_sampler_stop || die "the window sampler would not stop -- it would run on through the run"
	grep -qE 'emc_bpmp_hz=[0-9]+ ' "$OUT/clk-preflight.log" \
		|| die "EMC sampler produced no BPMP reading (sudo -n denied, or $EMC_BPMP absent)"
	grep -qE 'emc_ccf_hz=[0-9]+ ' "$OUT/clk-preflight.log" \
		|| die "EMC sampler produced no clock-framework reading ($EMC_CCF absent or unreadable)"
	grep -qE 'gpu_hz=[0-9]+$' "$OUT/clk-preflight.log" \
		|| die "GPU clock sampler produced no reading from $GPU_DEVFREQ"
	grep -qE 'EMC_FREQ [0-9]+%@[0-9]+' "$OUT/tegra-preflight.log" \
		|| die "tegrastats printed no EMC_FREQ -- it only does as root (sudo -n denied?)"
	m_sampler_require preflight 1600
	say "window sampler verified: $(grep -c . "$OUT/clk-preflight.log") clock and $(grep -c . "$OUT/tegra-preflight.log") tegrastats sample(s) in 1.6 s"
}

# measurement-design §3.5: the instrument must not share a core with the thing
# it measures. FOUND BY REVIEW, 2026-09-21: nothing enforced it, so overriding
# CORE_PROBE onto a QEMU core would have run every arm, idle included, with the
# probe beside a vCPU. Each argument is label=spec; a core named twice refuses.
m_require_disjoint() {  # $@ = label=spec ...
	local kv label c
	local -A owner=()
	for kv in "$@"; do
		label="${kv%%=*}"
		for c in $(_cpuset "${kv#*=}"); do
			[ -z "${owner[$c]:-}" ] \
				|| die "core $c is both ${owner[$c]}'s and $label's -- the instrument must not share a core with what it measures"
			owner[$c]="$label"
		done
	done
}

# ------------------------------------------------------------- loads
# BUILT BY THE RUN, NOT BY HAND (2026-09-21). cpuload used to be compiled once,
# manually, and the stamp hashed whatever binary sat in ~/interference -- which
# ties a run to a binary but not to any source. Now the run builds it from the
# cpuload.c beside the script, warnings as errors, and the stamp records both
# hashes. A stale unpinned binary was already refused by m_load_require_pinned;
# this also refuses a stale pinned one built from different source.
# The probe's end of the shm transport (OD12, 2026-09-22), built by the run from
# committed source like cpuload, and published to m_probe through SHMCHAN_LIB.
m_build_shmchan() {  # $1 = shmchan.c  $2 = ipc-test/common  $3 = library to write
	command -v gcc >/dev/null || die "gcc absent -- cannot build $3 from $1"
	[ -r "$2/shm_chan.h" ] && [ -r "$2/shm_map_posix.c" ] && [ -r "$2/ivshm_client.c" ] || die "shm sources missing under $2"
	gcc -O2 -Wall -Wextra -Werror -shared -fPIC -I "$2" -o "$3" "$1" "$2/shm_map_posix.c" "$2/ivshm_client.c" \
		|| die "libshmchan did not build from $1"
	SHMCHAN_LIB="$3"
	say "libshmchan built from $1 ($(_sha "$1" | cut -c1-12)) + shm_map_posix.c ($(_sha "$2/shm_map_posix.c" | cut -c1-12)) + ivshm_client.c ($(_sha "$2/ivshm_client.c" | cut -c1-12))"
}
m_build_cpuload() {  # $1 = source  $2 = binary to write
	command -v gcc >/dev/null || die "gcc absent -- cannot build $2 from $1"
	gcc -O2 -Wall -Wextra -Werror -o "$2" "$1" -lpthread -lm || die "cpuload did not build from $1"
	say "cpuload built from $1 ($(_sha "$1" | cut -c1-12))"
}
# REVIEW FINDING, reproduced: nothing checked that a load generator started,
# stayed up, or outlasted the probe. A failed fma turned a "gpu" arm into an idle
# arm with a gpu label; a load that exited early left part of the window
# unloaded. Now a loaded arm is verified at both ends of its probe window, and a
# GPU arm must SHOW the GPU busy, not just have a process alive.
#
# REVIEW FINDING: the load used to run its full duration -- ~17 s against a ~5 s
# settle-plus-probe window -- then be waited for, so each loaded arm went on
# heating a passively cooled board for ~10 s after measurement ended, and that
# heat landed on the next arm. The load is now stopped as soon as the probe
# finishes. Its duration argument stays generous only so it cannot run out
# before the probe does.
LOAD_PIDS=""
m_load_start() {    # $1 log path, then the command and its arguments
	local log="$1"; shift
	"$@" > "$log" 2>&1 &
	LOAD_PIDS="$LOAD_PIDS $!"
}
m_load_require_alive() {   # $1 = when, for the message
	local p
	for p in $LOAD_PIDS; do
		kill -0 "$p" 2>/dev/null || die "load pid $p is not running $1 -- the arm would be measured unloaded"
	done
}
# ADDED 2026-09-21. A pinned arm must SHOW its pins, not just have a process
# alive: cpuload prints one "thread i pinned to core c (verified)" line per
# thread after reading its own affinity back. This is the check a stale binary
# fails -- a cpuload built before CORES existed ignores the third argument, runs
# unpinned, stays alive, and would pass every other check in this file.
m_load_require_pinned() {  # $1 load log  $2 comma-separated cores, thread i on the i-th
	local log="$1" cores="$2" i=0 c
	for c in ${cores//,/ }; do
		grep -qxF "cpuload: thread $i pinned to core $c (verified)" "$log" \
			|| die "cpuload did not confirm thread $i on core $c (see $log) -- a stale binary ignores CORES and runs unpinned"
		i=$((i + 1))
	done
	[ "$(grep -c ' (verified)$' "$log")" -eq "$i" ] \
		|| die "cpuload confirmed a different number of pins than the $i asked for (see $log)"
}
m_load_stop() {
	local p
	for p in $LOAD_PIDS; do kill "$p" 2>/dev/null; done
	for p in $LOAD_PIDS; do wait "$p" 2>/dev/null; done
	LOAD_PIDS=""
}
# GR3D busy percentage from one tegrastats line, or -1 if it cannot be read.
#
# FOUND ON THE FIRST REAL RUN, 2026-09-21: the first version piped the match
# through `grep -oE '[0-9]+'`, which on "GR3D_FREQ 99%" also matches the 3
# INSIDE "GR3D" -- so it returned "3" and "99" on two lines, the integer test
# failed, and a GPU loaded to 99% was reported as unreadable. It refused the run,
# which is the right direction to fail, but a check that can never pass blocks
# every run. The number is now taken as the field AFTER the label, and anything
# that is not a single integer is rejected by name.
m_gpu_busy_pct() {
	local v
	v="$(timeout 3 tegrastats --interval 1000 2>/dev/null | head -1 \
		| grep -oE 'GR3D_FREQ [0-9]+' | awk '{print $2}' | head -1)"
	echo "${v:--1}"
}
# Sets the global GPU_PCT; never call this inside $(...) -- see m_prepare_out.
GPU_PCT=""
m_require_gpu_busy() {     # $1 = minimum percent
	GPU_PCT="$(m_gpu_busy_pct)"
	[[ "$GPU_PCT" =~ ^-?[0-9]+$ ]] || die "GPU arm, but the GR3D reading is not an integer: '$GPU_PCT'"
	[ "$GPU_PCT" -ge 0 ] || die "GPU arm, but tegrastats gave no GR3D reading -- load unverified"
	[ "$GPU_PCT" -ge "$1" ] || die "GPU arm, but GR3D is ${GPU_PCT}% (need >= $1%) -- the GPU is not loaded"
}
# One tegrastats line for the per-round thermal record. REVIEW FINDING: this
# could not fail, so an empty record looked like a quiet board. It now says so.
m_thermal() {       # $1 = label
	local line
	line="$(timeout 3 tegrastats --interval 1000 2>/dev/null | head -1 \
		| grep -oE 'CPU \[[^]]*\]|GR3D_FREQ [0-9]*%|cpu@[0-9.]*C|gpu@[0-9.]*C' | tr '\n' ' ')"
	echo "$1 ${line:-NO-READING}"
}
