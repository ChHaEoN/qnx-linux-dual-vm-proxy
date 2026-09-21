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
		printf '  "qemu_exe": "%s",\n' "$QEXE"
		printf '  "qemu_version": "%s",\n' "$QVER"
		if [ -n "$QPID" ] && [ -r "/proc/$QPID/cmdline" ]; then
			printf '  "qemu_cmdline": "%s",\n' "$(tr '\0' ' ' < "/proc/$QPID/cmdline" | sed 's/"/\\"/g')"
		fi
		printf '  "qemu_threads": %s,\n' "$QTHREADS"
		printf '  "qemu_affinity": "%s",\n' "$QAFF"
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
	$pre taskset -c "$CORE_PROBE" python3 "$PROBE" --host "$host" --port "$port" \
		--n "$N" --warmup "$WARMUP" --interval-ms "$INTERVAL_MS" \
		--tag "$tag" --out "$out/lat-$tag.json" >> "$out/probe.log" 2>&1
	rc=$?
	[ "$rc" -eq 0 ] || die "probe failed on $tag (exit $rc) -- see $out/probe.log; the run stops here"
	[ -s "$out/lat-$tag.json" ] || die "probe exited 0 but wrote no file for $tag"
}

# ------------------------------------------------------------- completeness
# REVIEW FINDING, twice over: counting files proves nothing about which run
# wrote them, and a file that exists proves nothing about what is in it. The
# gate now requires the EXACT set r1..rK, every file newer than this run's
# stamp, and every file's own summary to say it is a full, clean sample: the
# requested n and warm-up, zero bad frames, zero monitor rejections, and the
# tag it is named for.
m_require_complete() {  # $1 = out dir, then arm tags
	local out="$1"; shift
	python3 - "$out" "$K" "$N" "$WARMUP" "$@" <<'PY' || die "the run is incomplete or unclean -- do not publish a median from it"
import json, os, sys
out, k, n, warmup, arms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:]
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
