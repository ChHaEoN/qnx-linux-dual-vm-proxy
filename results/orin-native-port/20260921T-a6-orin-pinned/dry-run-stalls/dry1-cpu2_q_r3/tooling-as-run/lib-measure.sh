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
}

m_reachable() {     # $1 host  $2 port  $3 label
	timeout 3 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null \
		|| die "UNREACHABLE: $3 ($1:$2)"
	say "reachable: $3 ($1:$2)"
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
m_round_order() {   # $1 round, then: first  middle...  last
	local r="$1"; shift
	local first="$1"; shift
	local n=$(( $# - 1 )) last="${!#}"
	local mid=("${@:1:$n}")
	local base period row idx rev i out=("$first") seq=()
	read -r -a base <<< "$(_williams_base "$n")"
	period="$(m_williams_period "$n")"
	row=$(( (r - 1) % period ))
	rev=0
	if [ "$row" -ge "$n" ]; then rev=1; row=$(( row - n )); fi
	for i in "${base[@]}"; do seq+=( $(( (i + row) % n )) ); done
	if [ "$rev" -eq 1 ]; then
		for ((i=${#seq[@]}-1; i>=0; i--)); do out+=("${mid[${seq[i]}]}"); done
	else
		for idx in "${seq[@]}"; do out+=("${mid[$idx]}"); done
	fi
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
		printf '  "sample_window": %s,\n' "${SAMPLE_WINDOW:-0}"
		if [ "${SAMPLE_WINDOW:-0}" = 1 ]; then
			printf '  "sampler_paths": {"emc_bpmp": "%s", "emc_ccf": "%s", "gpu_devfreq": "%s"},\n' \
				"$EMC_BPMP" "$EMC_CCF" "$GPU_DEVFREQ"
		fi
		printf '  "fifo_arms": "%s",\n' "${FIFO_ARMS:-}"
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
m_probe() {         # $1 out-dir  $2 tag  $3 host  $4 port  [$5 prefix command]
	local out="$1" tag="$2" host="$3" port="$4" pre="${5:-}" rc
	rm -f "$out/lat-$tag.json"
	# The window sampler brackets exactly the probe, when the script asked for
	# it (SAMPLE_WINDOW=1). Off by default: the ladder's numbers are the
	# headline, and a new process running beside them is a new perturbation.
	[ "${SAMPLE_WINDOW:-0}" = 1 ] && m_sampler_start "$tag"
	$pre taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$host" --port "$port" \
		--n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" \
		--tag "$tag" --out "$out/lat-$tag.json" >> "$out/probe.log" 2>&1
	rc=$?
	if [ "${SAMPLE_WINDOW:-0}" = 1 ]; then
		m_sampler_stop || die "the window sampler for $tag would not stop -- it would run on into the next arm"
	fi
	[ "$rc" -eq 0 ] || die "probe failed on $tag (exit $rc) -- see $out/probe.log; the run stops here"
	[ -s "$out/lat-$tag.json" ] || die "probe exited 0 but wrote no file for $tag"
	[ "${SAMPLE_WINDOW:-0}" = 1 ] && m_sampler_require "$tag"
	return 0
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
m_require_complete() {  # $1 = out dir, then arm tags
	local out="$1"; shift
	[ -n "${CORE_PROBE:-}" ] || die "m_require_complete needs CORE_PROBE to check the probe's affinity"
	MP_CORE="$CORE_PROBE" MP_FIFO="${FIFO_ARMS:-}" \
	python3 - "$out" "$K" "$N" "$WARMUP" "$@" <<'PY' || die "the run is incomplete or unclean -- do not publish a median from it"
import json, os, sys
out, k, n, warmup, arms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:]
probe_core = int(os.environ["MP_CORE"])
fifo_arms = set(os.environ.get("MP_FIFO", "").split())
if not os.path.exists(os.path.join(out, "stamp.json")):
    print("INCOMPLETE: no stamp.json", file=sys.stderr); sys.exit(1)
# The reference is the run's START marker, written once by m_prepare_out and
# never rewritten -- not stamp.json, which m_stamp_after rewrites at the end.
start = os.path.join(out, ".run-start")
if not os.path.exists(start):
    print("INCOMPLETE: no .run-start marker -- was the directory made by m_prepare_out?", file=sys.stderr); sys.exit(1)
t0 = os.path.getmtime(start)
problems = []
for a in arms:
    for r in range(1, k + 1):
        tag = "%s_r%d" % (a, r)
        p = os.path.join(out, "lat-%s.json" % tag)
        if not os.path.exists(p):
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
        # The probe's own report of how it ran.
        if a in fifo_arms:
            sched_want = (("sched_policy", "SCHED_FIFO"), ("sched_priority", 50))
        else:
            sched_want = (("sched_policy", "SCHED_OTHER"),)
        for key, want in sched_want + (("cpu_affinity", [probe_core]),):
            if s.get(key) != want:
                problems.append("%s: %s=%r, expected %r (the probe's own report)"
                                % (tag, key, s.get(key), want))
    extra = [f for f in os.listdir(out)
             if f.startswith("lat-%s_r" % a) and f.endswith(".json")
             and f[len("lat-%s_r" % a):-5].isdigit()
             and not (1 <= int(f[len("lat-%s_r" % a):-5]) <= k)]
    for f in extra:
        problems.append("%s: round outside 1..%d" % (f, k))
for p in problems:
    print("INCOMPLETE: " + p, file=sys.stderr)
sys.exit(1 if problems else 0)
PY
	say "complete and clean: ${#@} arm(s) x $K round(s), every file this run's"
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
print("  %-11s %3s  %24s  %24s  %s" % ("arm", "k", "p50 ms: median [band]",
                                        "paired vs %s: med [band]" % ref, "max ms: min/med/max of k"))
for a in arms:
    d = data[a]
    if not d:
        print("  %-11s   0  (no data)" % a); continue
    p50 = [s["p50_ms"] for s in d.values()]; mx = [s["max_ms"] for s in d.values()]
    if a != ref and ref in data:
        diffs = [d[r]["p50_ms"] - data[ref][r]["p50_ms"] for r in d if r in data[ref]]
        pair = "%+7.3f [%+.3f,%+.3f]" % (st.median(diffs), min(diffs), max(diffs))
    else:
        pair = "(reference)"
    print("  %-11s %3d  %7.3f [%6.3f-%6.3f]  %24s  %.3f / %.3f / %.3f"
          % (a, len(d), st.median(p50), min(p50), max(p50), pair, min(mx), st.median(mx), max(mx)))
print("  headline = median of the k run-medians. 'paired' = median over rounds of (arm - %s) in the SAME round." % ref)
print("  'max' is the largest OBSERVED value in each round, never a bound.")
PY
}

# ------------------------------------------------------------- the window sampler
# ADDED 2026-09-21 to close two gaps an independent analysis named. Load
# placement was read from ONE tegrastats sample taken before each probe
# started, and could change once it began -- identical sampled placements gave
# both cost regimes. And the memory-controller (EMC) clock, the leading
# hypothesis for why a GPU load speeds the guest up, was never recorded at all.
# So each probe window is now traced continuously, every 500 ms:
#   tegra-<tag>.log  tegrastats: per-core CPU % and MHz, GR3D, temperatures
#   clk-<tag>.log    EMC rate from BOTH sources that disagree on this board --
#                    BPMP debugfs said 2133 MHz, the kernel clock framework said
#                    204 MHz, when first read; BPMP owns the clocks on Tegra234,
#                    but neither is picked silently -- plus the GPU devfreq clock.
# tegrastats on this JetPack build has no EMC field, hence the debugfs reads,
# which need root: one `sudo -n` for the whole loop, not one per sample.
#
# WHAT THE SAMPLER COSTS, stated rather than assumed away: tegrastats, which
# reads dozens of sysfs files per interval, plus a root shell loop -- both
# UNPINNED, so they run wherever the scheduler puts them, which differs by arm
# and in the cpu6 arms means on a loaded core. The loop reads with shell
# builtins and forks only `sleep`, once per 500 ms; its first draft forked five
# processes per sample. Every window's logs must hold at least one complete
# reading, or the run stops: a recorder that can go quiet mid-run would only
# move the gap, not close it.
SAMPLER_PIDS=""; SAMPLER_ROOT=""
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
	ceil=$(( (${N:-1000} + ${WARMUP:-200}) * ${INTERVAL_MS:-2} / 1000 + 120 ))
	timeout "$ceil" tegrastats --interval 500 > "$OUT/tegra-$t.log" 2>/dev/null &
	SAMPLER_PIDS="$SAMPLER_PIDS $!"
	# FOUND ON THE BOARD, 2026-09-21, by the first smoke test -- the unit tests'
	# sudo stub could not show it. The loop used to run as a background
	# `sudo -n timeout ...` and be stopped with `sudo -n kill <sudo's pid>`. Real
	# sudo does not relay a signal sent from its command's own process group, and
	# both sudos sat in the script's group: the stop was ignored, `wait` blocked
	# until the 122 s ceiling, and the loop wrote on through it. Now a short sudo
	# starts `timeout` in the background and prints its pid. timeout leads its own
	# process group and forwards a TERM to all of it, so it is signalled directly.
	root="$(sudo -n bash -c 'timeout "$1" env LC_ALL=C bash -c "$2" _ "$3" "$4" "$5" > "$6" 2>/dev/null & echo $!' \
		_ "$ceil" "$SAMPLER_LOOP" "$EMC_BPMP" "$EMC_CCF" "$GPU_DEVFREQ" "$OUT/clk-$t.log" 2>/dev/null)"
	SAMPLER_ROOT="$SAMPLER_ROOT $root"
}
# Returns non-zero if a sampler survived, and never dies: it also runs from the
# cleanup trap, where a die would skip restoring the governor and idle states.
m_sampler_stop() {
	local p i rc=0
	for p in $SAMPLER_PIDS; do kill "$p" 2>/dev/null; done
	for p in $SAMPLER_PIDS; do wait "$p" 2>/dev/null; done
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
				echo "WARNING: clock sampler $p is still running after TERM and KILL" >&2; rc=1
			fi
		fi
	done
	SAMPLER_PIDS=""; SAMPLER_ROOT=""
	return "$rc"
}
# One window's trace must hold at least one COMPLETE clock line -- all three
# values present -- and one per-core CPU line, or the run stops. Checked after
# every probe, not only in the preflight: sudo's cached credential or a debugfs
# node can go away mid-run.
m_sampler_require() {  # $1 = tag
	local t="$1"
	grep -qE '^[0-9.]+ emc_bpmp_hz=[0-9]+ emc_ccf_hz=[0-9]+ gpu_hz=[0-9]+$' "$OUT/clk-$t.log" \
		|| die "the clock sampler recorded no complete reading during $t (see $OUT/clk-$t.log) -- the window went unrecorded"
	grep -q 'CPU \[' "$OUT/tegra-$t.log" \
		|| die "tegrastats recorded no per-core CPU line during $t -- the window went unrecorded"
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
	m_sampler_require preflight
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
