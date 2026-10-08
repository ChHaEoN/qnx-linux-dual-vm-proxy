# lib-build.sh -- what the builds on the board share: the job count, the memory cap, the state of
# a detached run, the search for nvcc and BUILD-INFO's common lines (Phase 3b / A6, 2026-10-05).
#
#   Sourced, not executed:   . "<this directory>/lib-build.sh"
#   Callers must then check: [ "${BUILD_LIB_LOADED:-}" = 1 ] || exit 1
#   Run by itself it builds nothing. It answers one question for a person,
#     bash lib-build.sh status NAME            where a build stands (NAME as b_begin was given it)
#   and is what the functions below start inside a capped scope:
#     bash lib-build.sh memory-max FILE ROOT        the memory limit of the cgroup it runs in
#     bash lib-build.sh step FILE ROOT OUT CMD...   run CMD, then write to OUT what that cgroup
#                                                   says of it: memory.peak, oom_kill and oom
#
# WHO SOURCES IT. orin-native/someip/build-vsomeip.sh, ipc-test/qnx-dds-monitor/
# build-cyclonedds-l4t.sh, orin-native/edge-llm/build-llama.sh and build-fma.sh beside this file.
#
# WHY ONE LIBRARY. These builds run on a board with under 8 GB of memory and no swap. A parallel
# C++ or CUDA build that pushes such a board into reclaim looks like a hang, and a hang there is
# ended at the plug. The rules that keep a build from doing that are the same for all four, so
# they are written once, and a script cannot have its own weaker copy.
#
#   THE JOB COUNT. JOBS defaults to 2 on a host with under 8 GB and no swap, and to 4 elsewhere
#   (b_jobs). A JOBS in the environment wins. A /proc/meminfo that cannot be read gets 2.
#
#   THE MEMORY CAP. Every configure, compile, link and install step runs as
#       systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0 <command>
#   (capped, through b_step), so a build that outgrows the cap is killed inside its own cgroup
#   and the rest of the system keeps its memory. 4G is a first value, not a measured one; MEM_MAX
#   replaces it. Before anything is fetched or built, b_cap_check starts one such scope around a
#   command that reads the scope's own memory.max back. If systemd-run refuses, or the limit read
#   back is not the one asked for, the script stops and says so. NOTHING IS BUILT UNCAPPED: there
#   is no fallback and no switch. No argument handed to systemd-run holds a dollar sign: systemd
#   255 warns that a later release will expand one in a scope's command line.
#     A CAP THE HOST CANNOT BACK IS NO CAP. The kernel takes any limit and reads it back as it
#   was asked for, one above the host's memory too; under such a limit an over-large build is
#   not ended inside its own cgroup, and what ends it is the system-wide killer, or nothing.
#   So before the scope is asked for, MEM_MAX must be below MemTotal less MEM_REST_KB, which is
#   what everything on the host that is not the build keeps (a first value, like the cap). Where
#   MemTotal cannot be read, nothing above the default is taken.
#
#   WHAT A STEP COST, AND WHETHER THE CAP ENDED IT. A scope is gone when its command ends, so
#   each step's command is started by this file's `step` mode inside the scope, which afterwards
#   reads the scope's memory.peak and, from its memory.events, the oom_kill and the oom count. A
#   failed step's message then says whether the kernel killed something in it for memory, in
#   place of a guess from the compiler's last line; a step whose command ended well although
#   something in it was killed is a failed step too (a configure check that was killed reads as
#   a missing feature); and BUILD-INFO records the largest peak of the build's steps, so that
#   the cap and the job count can be chosen from what a build needed. A kernel without those
#   two files gives `unread`, which fails nothing.
#     oom_kill counts every process of the cgroup that the kernel killed for memory, whoever's
#   limit it was; that the scope's own limit was reached is its oom count. So a kill with an
#   oom count of 0 is said as what it is: not this scope's cap, but the system-wide killer or
#   a limit on a cgroup above the scope, for which fewer jobs is not the remedy. A kernel that
#   gives no oom line leaves the two untold, and the kill is then read as the cap's.
#     The user manager does not leave a scope alone after such a kill: with its default
#   OOMPolicy=stop it stops the whole scope, TERM to every process in it, the `step` mode's
#   shell among them. So that shell holds TERM off until its command has ended (by a handler,
#   which the command does not inherit; an ignored TERM it would), and then reads the counts
#   and writes them. What it cannot outlast is a KILL: the one the manager sends when a scope's
#   processes do not end in time, and the one a manager whose policy is `kill` sends the whole
#   scope at once. The step's message then says that the counts could not be read and that its
#   shell was killed outright, which is not "the cap was not hit". A step's log that ends in
#   `Terminated` says only that the step's processes got TERM; the count in the message says
#   whether a kill came first.
#
#   A DETACHED RUN. A long build must not die with the SSH session that started it, so it is
#   started as
#       setsid nohup bash <script> > build.log 2>&1 < /dev/null &
#   and read in a later session. b_begin takes a lock, says what an earlier run left behind, and
#   makes the script write a done-file with its exit status however it ends: a refusal, a failed
#   step, a TERM. Under $BUILD_STATE (~/builds):
#       NAME.lock      held while the script, or anything it started, is alive
#       NAME.started   when this run began, and the script's pid
#       NAME.done      line 1 the exit status, line 2 when it ended
#   So a later session tells the cases apart, and `bash lib-build.sh status NAME` does it:
#   the lock held: something of a run is alive (2) -- the script itself, or, when a done-file
#   is there as well, a run in its first or last moments or a process a run started and left
#   behind, and the line says which of the two it found; a done-file and the lock free: ended,
#   with that status (exit 0, or 1 for any other status); neither, and a start: it died, killed
#   outright or with the board (3); nothing at all: no run found (4). A second run while the
#   lock is held starts nothing and exits 75. To stop a detached build, signal its process
#   group (kill -TERM -- -<pid>); setsid made the script the group's leader, and `status`
#   gives the pid of a running one.
#
#   BUILD-INFO IS WRITTEN LAST, AND WHAT A SCRIPT CHECKS AT ITS END IS THIS RUN'S. Before its
#   first build step a script removes the BUILD-INFO of an earlier build and the outputs it
#   will look for at its end (each script names them), and it writes its own BUILD-INFO when
#   every output is there again. A run that is refused before its first build step leaves an
#   earlier build, and its BUILD-INFO, as they were.
#     The outputs go first because of a run that was cut in its last link, by a power loss or a
#   KILL: a linker writes its output in place, so the cut file is not empty and is newer than
#   its objects, make has nothing to do for it, and the next run would hash it into BUILD-INFO
#   under its own commit. WHAT THIS DOES NOT REACH is the build directory behind those outputs:
#   an object or a library that was cut the same way stays there, newer than its source, and
#   make keeps it. A linker that reads such a file says so; nothing here does. So AFTER A RUN
#   THAT DIED (`status` says DIED) the build directory is removed by hand before the next run.
#
#   GIT CANNOT WAIT FOR EVER, AND CANNOT ASK. A clone, and the checkout of a partial clone, which
#   fetches the files' contents, go through b_git: a transfer that stays under a floor for a
#   minute is ended, where git by itself waits for as long as TCP does, with the build's lock
#   held. GIT_TERMINAL_PROMPT=0 is set at the start of every script: a git that wants a user
#   name fails, and does not wait at a terminal for one. A checkout whose HEAD names no commit
#   is said as what it is, a clone that did not finish, with what to remove.
#
# NOTHING BUILT IS RUN, AND NOTHING NEEDS ROOT. No script that sources this starts what it built,
# not for a version string either; the one exception is named in build-cyclonedds-l4t.sh. None
# calls another user's privileges, and none installs a package.
#
# WHAT THIS DOES NOT SHOW. The cap bounds the build's own cgroup: it does not bound what else
# runs on the board, and it is a kill, not a slow-down. That a given board's user manager takes
# the two properties is what b_cap_check finds out when it runs there; this file does not know
# it. A scope under the user manager lives as long as that manager: whether it outlives the last
# session of a login is decided by logind, not here, and the done-file is how a build that was
# ended that way is seen.

BUILD_LIB_LOADED=1
B_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-build.sh"

# The four paths below exist so that tests can point this file at made-up trees. On the board
# they must be the real ones, so an override is said out loud by b_begin.
MEMINFO_DEFAULT=/proc/meminfo
MEMINFO="${MEMINFO:-$MEMINFO_DEFAULT}"
SELF_CGROUP_DEFAULT=/proc/self/cgroup
SELF_CGROUP="${SELF_CGROUP:-$SELF_CGROUP_DEFAULT}"
CGROUP_FS_DEFAULT=/sys/fs/cgroup
CGROUP_FS="${CGROUP_FS:-$CGROUP_FS_DEFAULT}"
CUDA_BASE_DEFAULT=/usr/local
CUDA_BASE="${CUDA_BASE:-$CUDA_BASE_DEFAULT}"

MEM_MAX="${MEM_MAX:-4G}"
# What a cap leaves of the host's memory to everything that is not the build, in kB (1.5 GiB).
# Not taken from the environment: a first value, and the owner's to change here.
MEM_REST_KB=1572864

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
die() { echo "FATAL: $*" >&2; exit 1; }

# ------------------------------------------------------------- a run's state
# b_begin NAME: the lock, what an earlier run left, and the done-file this run will write.
b_begin() {
	local v now was
	B_NAME="$1"
	B_STATE="${BUILD_STATE:-$HOME/builds}"
	B_DONE="$B_STATE/$B_NAME.done"
	B_STARTED="$B_STATE/$B_NAME.started"
	B_LOCK="$B_STATE/$B_NAME.lock"
	B_STEPS=0; B_PEAK=0; B_OOM=0; B_UNREAD=0; B_STEP_NOTE=""; B_STEP_OOM=unread
	# No git may wait at a terminal for a user name: it fails instead, here and in a detached run.
	export GIT_TERMINAL_PROMPT=0
	command -v flock >/dev/null || die "no flock: a second run could not be kept out of the first one's tree"
	mkdir -p "$B_STATE" || die "cannot make $B_STATE"
	exec 9>> "$B_LOCK" || die "cannot open $B_LOCK"
	if ! flock -n 9; then
		# Before the trap is set: the done-file is the running build's to write, not this one's.
		echo "FATAL: another $B_NAME is running, or something one started is still alive (it holds $B_LOCK). This one starts nothing." >&2
		exit 75
	fi
	trap 'b_end $?' EXIT
	trap 'exit 129' HUP
	trap 'exit 130' INT
	trap 'exit 141' PIPE
	trap 'exit 143' TERM
	if [ -e "$B_DONE" ]; then
		IFS= read -r v < "$B_DONE" || true
		say "found: an earlier $B_NAME ended with exit status $v ($B_DONE); this run writes its own"
	elif [ -e "$B_STARTED" ]; then
		IFS= read -r v < "$B_STARTED" || true
		say "found: an earlier $B_NAME started $v and wrote no done-file: it died or was killed"
	else
		say "found: no earlier $B_NAME under $B_STATE"
	fi
	rm -f "$B_DONE" "$B_DONE.tmp" "$B_STATE/$B_NAME.step"
	{ date -u +%FT%TZ; echo "pid $$"; } > "$B_STARTED"
	for v in MEMINFO SELF_CGROUP CGROUP_FS CUDA_BASE; do
		now="${!v}"; was="${v}_DEFAULT"
		[ "$now" = "${!was}" ] || echo "WARNING: $v=$now replaces ${!was} (a test's setting; never on the board)" >&2
	done
}

# The EXIT trap: the done-file first, then the line that says so. Nothing here may stop it.
b_end() {
	local rc="$1"
	trap - EXIT
	trap '' HUP INT PIPE TERM
	if { printf '%s\n' "$rc"; printf '%s ended %s\n' "$B_NAME" "$(date -u +%FT%TZ)"; } > "$B_DONE.tmp" 2>/dev/null \
		&& mv -f "$B_DONE.tmp" "$B_DONE" 2>/dev/null; then
		echo "[$B_NAME] exit status $rc, written to $B_DONE" || true
	else
		echo "[$B_NAME] exit status $rc; the done-file $B_DONE could NOT be written" >&2 || true
	fi
	exit "$rc"
}

# status NAME: one line, and 0 ended with status 0, 1 ended otherwise, 2 something of a run is
# alive, 3 died, 4 no run found. The lock is asked first: a done-file beside a held lock is not
# yet the whole answer.
b_status() {
	local name="$1" state="${BUILD_STATE:-$HOME/builds}" rc when pid
	if [ -e "$state/$name.lock" ] && ! flock -n "$state/$name.lock" true; then
		{ IFS= read -r when; IFS= read -r pid; } < "$state/$name.started" 2>/dev/null || true
		if [ -e "$state/$name.done" ]; then
			{ IFS= read -r rc; IFS= read -r when; } < "$state/$name.done" 2>/dev/null || true
			echo "$name: a done-file says exit status ${rc:-unread} (${when:-no second line}), and something still holds $state/$name.lock: a run in its first or last moments, or a process a run started and left alive (the script that started last: ${pid:-pid not written}). A new run starts nothing while that is so."
			return 2
		fi
		echo "$name: running since ${when:-a time that was not written}, ${pid:-pid not written} (something holds $state/$name.lock)"
		return 2
	fi
	if [ -e "$state/$name.done" ]; then
		{ IFS= read -r rc; IFS= read -r when; } < "$state/$name.done" || true
		echo "$name: ended with exit status ${rc:-unread} (${when:-no second line} in $state/$name.done)"
		[ "${rc:-}" = 0 ] || return 1
		return 0
	fi
	if [ -e "$state/$name.started" ]; then
		IFS= read -r when < "$state/$name.started" || true
		echo "$name: DIED -- started ${when:-at a time that was not written}, no done-file, and nothing holds the lock"
		return 3
	fi
	echo "$name: no run found under $state"
	return 4
}

# ------------------------------------------------------------- the job count
b_jobs() {
	local mem swap
	if [ -n "${JOBS:-}" ]; then
		[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "JOBS='$JOBS' is not a job count"
		B_JOBS_WHY="JOBS given"
		say "jobs: $JOBS ($B_JOBS_WHY)"
		return 0
	fi
	mem="$(sed -n 's/^MemTotal:[[:space:]]*\([0-9][0-9]*\) kB[[:space:]]*$/\1/p' "$MEMINFO" 2>/dev/null)" || mem=""
	swap="$(sed -n 's/^SwapTotal:[[:space:]]*\([0-9][0-9]*\) kB[[:space:]]*$/\1/p' "$MEMINFO" 2>/dev/null)" || swap=""
	if ! [[ "$mem" =~ ^[0-9]+$ && "$swap" =~ ^[0-9]+$ ]]; then
		JOBS=2
		B_JOBS_WHY="the default where memory and swap could not be read from $MEMINFO"
	elif [ "$mem" -lt 8388608 ] && [ "$swap" -eq 0 ]; then
		JOBS=2
		B_JOBS_WHY="the default on a host with under 8 GB and no swap"
	else
		JOBS=4
		B_JOBS_WHY="the default"
	fi
	say "jobs: $JOBS ($B_JOBS_WHY)"
}

# ------------------------------------------------------------- the memory cap
capped() { systemd-run --user --scope -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 "$@"; }

b_cap_check() {
	local n want want_kb got mem
	[[ "$MEM_MAX" =~ ^[1-9][0-9]{0,8}[KMGT]$ ]] \
		|| die "MEM_MAX='$MEM_MAX' is not a cap this script takes: a whole number above 0, of nine digits at most, with K, M, G or T"
	command -v systemd-run >/dev/null || die "no systemd-run. Nothing is built without the memory cap."
	n="${MEM_MAX%?}"
	case "$MEM_MAX" in
		*K) want_kb=$n ;;
		*M) want_kb=$((n * 1024)) ;;
		*G) want_kb=$((n * 1024 * 1024)) ;;
		*T) want_kb=$((n * 1024 * 1024 * 1024)) ;;
	esac
	# A cap the host cannot back is no cap: the kernel takes it and reads it back as asked, and
	# an over-large build under it is ended by the system-wide killer, or by nothing. Asked
	# before the scope is: MemTotal as b_jobs reads it, less what the rest of the host keeps.
	mem="$(sed -n 's/^MemTotal:[[:space:]]*\([0-9][0-9]*\) kB[[:space:]]*$/\1/p' "$MEMINFO" 2>/dev/null)" || mem=""
	if [[ "$mem" =~ ^[0-9]+$ ]]; then
		[ "$want_kb" -lt $((mem - MEM_REST_KB)) ] \
			|| die "MEM_MAX=$MEM_MAX is not a cap this host can back: MemTotal is $mem kB ($MEMINFO), $MEM_REST_KB kB of it stay with everything that is not the build, so a cap here is below $((mem - MEM_REST_KB)) kB. Under a larger one an over-large build is not ended inside its own cgroup."
	else
		[ "$want_kb" -le 4194304 ] \
			|| die "MEM_MAX=$MEM_MAX is above the default 4G, and MemTotal could not be read from $MEMINFO: a larger cap is taken only where the host's memory is known to hold it."
	fi
	want=$((want_kb * 1024))
	# One scope, around a command that reads the scope's own limit back from the kernel.
	got="$(capped bash "$B_LIB" memory-max "$SELF_CGROUP" "$CGROUP_FS")" \
		|| die "systemd-run refused the capped scope, or the scope's limit could not be read (the message is above). Nothing is built without the memory cap."
	[[ "$got" =~ ^[0-9]+$ ]] && [ "$got" -gt 0 ] && [ "$got" -le "$want" ] \
		|| die "systemd-run made the scope, but its memory.max reads '$got', not $want ($MEM_MAX): the cap is not in force. Nothing is built without the memory cap."
	B_CAP_READ="$got"
	say "memory cap: MemoryMax=$MEM_MAX MemorySwapMax=0 on every build step; a scope's memory.max reads $got"
}

# b_try LOG CMD...: one build step in a capped scope of its own, its output in LOG. Returns the
# command's status and leaves in B_STEP_NOTE what the scope's cgroup said of it, and in
# B_STEP_OOM its oom_kill count (or `unread`).
b_try() {
	local log="$1" rc=0 stats="$B_STATE/$B_NAME.step" k v peak=unread oom=unread own=unread
	shift
	rm -f "$stats"
	capped bash "$B_LIB" step "$SELF_CGROUP" "$CGROUP_FS" "$stats" "$@" > "$log" 2>&1 || rc=$?
	if [ -r "$stats" ]; then
		while read -r k v; do
			case "$k" in peak) peak="$v" ;; oom_kill) oom="$v" ;; oom) own="$v" ;; esac
		done < "$stats"
	fi
	rm -f "$stats"
	B_STEP_OOM="$oom"
	B_STEPS=$((B_STEPS + 1))
	if [[ "$peak" =~ ^[0-9]+$ && "$oom" =~ ^[0-9]+$ ]]; then
		[ "$peak" -le "$B_PEAK" ] || B_PEAK="$peak"
		B_OOM=$((B_OOM + oom))
	else
		B_UNREAD=$((B_UNREAD + 1))
	fi
	if ! [[ "$oom" =~ ^[0-9]+$ ]]; then
		B_STEP_NOTE="What the step's cgroup counted could not be read, so whether the memory cap ended it is not known."
		# 137 is a KILL of the shell that was to write the counts. Nothing here can tell whose.
		if [ "$rc" = 137 ]; then
			B_STEP_NOTE="$B_STEP_NOTE The step's shell was killed outright (status 137): a user manager whose policy is to kill a whole scope after a kill in it ends a step this way, and so does the KILL that follows a stop the step did not obey in time."
		fi
	elif [ "$oom" -gt 0 ]; then
		# oom_kill counts every kill for memory in the cgroup; `oom` says that the cgroup's own
		# limit was reached. A kill with that at 0 came from outside the scope's cap.
		if [ "$own" = 0 ]; then
			B_STEP_NOTE="The step's cgroup counts $oom oom_kill and no oom of its own: the kernel killed in it for memory, and not because this scope reached its cap ($MEM_MAX). That is the system-wide killer, or a limit on a cgroup above the scope: something outside the build took the memory. Fewer jobs would not have helped; find what else ran before this is run again."
		else
			B_STEP_NOTE="The step's cgroup counts $oom oom_kill: the memory cap ($MEM_MAX) was hit."
			if [ "${JOBS:-1}" = 1 ]; then
				B_STEP_NOTE="$B_STEP_NOTE It ran one job at a time: a larger MEM_MAX is the owner's to give."
			else
				B_STEP_NOTE="$B_STEP_NOTE Run again with JOBS=1; a larger MEM_MAX is the owner's to give."
			fi
		fi
		# A command can end well with a process of its own killed under it: a configure check
		# that was killed reads as "this feature is not there". Such a step is not taken.
		if [ "$rc" = 0 ]; then
			rc=137
			B_STEP_NOTE="Its command ended well all the same, and what it left is not trusted. $B_STEP_NOTE"
		fi
	else
		B_STEP_NOTE="The step's cgroup counts no oom_kill: the memory cap did not end it."
	fi
	return "$rc"
}

# b_step LOG WHAT CMD...: the same, and a failed step ends the script.
b_step() {
	local log="$1" what="$2"
	shift 2
	b_try "$log" "$@" || die "$what failed -- see $log. $B_STEP_NOTE"
}

# ------------------------------------------------------------- git, nvcc, BUILD-INFO
# b_git ARGS...: git for a call that can reach the network -- a clone, and the checkout of a
# partial clone, which fetches the files' contents. A transfer that stays under 1000 bytes a
# second for a minute is ended; without the two words git waits for as long as TCP does.
b_git() { git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 "$@"; }

# b_head DIR WHAT: the commit DIR's HEAD names, into B_HEAD. A checkout that has no HEAD is what
# a clone leaves that was cut before it had fetched anything (`git init` is a clone's first
# step): every later run finds the directory and does not clone again, so the message says
# what to remove. git's own line is not hidden.
b_head() {
	B_HEAD="$(git -C "$1" rev-parse HEAD)" \
		|| die "no HEAD in $1 (git's own line is above): a clone that did not finish, or no checkout of $2 at all. Remove $1 and run again."
}

# b_require_head DIR COMMIT WHAT: the checkout is at the pinned commit, or the script stops.
b_require_head() {
	b_head "$1" "$3"
	[ "$B_HEAD" = "$2" ] || die "$1 is at $B_HEAD, not the pinned $2 for $3"
}

# How many tracked files differ from the commit: BUILD-INFO names a commit, and a tree somebody
# patched to make it build would otherwise carry that name unchanged. Counted, not refused.
b_tracked_changes() {
	local out
	if out="$(git -C "$1" status --porcelain --untracked-files=no 2>/dev/null)"; then
		if [ -n "$out" ]; then printf '%s\n' "$out" | grep -c .; else echo 0; fi
	else
		echo unread
	fi
}

# The one nvcc under /usr/local/cuda*, or NVCC from the environment. Sets NVCC and NVCC_REAL.
b_find_nvcc() {
	local c r seen="" found="" best="" n=0
	if [ -n "${NVCC:-}" ]; then
		# cmake is handed these words as they are and reads them from its own directory.
		case "$NVCC" in /*) ;; *) die "NVCC='$NVCC' is not an absolute path" ;; esac
		[ -f "$NVCC" ] && [ -x "$NVCC" ] || die "NVCC='$NVCC' is not an executable file"
	else
		# /usr/local/cuda is usually a link to the versioned directory beside it: one file under
		# several names is one nvcc. The longest of its names is kept, which is the versioned
		# one, and which does not depend on the order the shell's locale lists them in.
		for c in "$CUDA_BASE"/cuda*/bin/nvcc; do
			[ -f "$c" ] && [ -x "$c" ] || continue
			r="$(readlink -f "$c" 2>/dev/null)" || r="$c"
			case "|$seen|" in
				*"|$r|"*)
					[ "${#c}" -le "${#best}" ] || best="$c"
					continue ;;
			esac
			seen="${seen:+$seen|}$r"
			found="${found:+$found, }$c"
			best="$c"
			n=$((n + 1))
		done
		[ "$n" -ge 1 ] || die "no nvcc under $CUDA_BASE/cuda*/bin: the CUDA compiler is not installed (scripts/orin/provision-orin-r39.sh apply cuda installs it)"
		[ "$n" -eq 1 ] || die "more than one nvcc under $CUDA_BASE/cuda*: $found -- name the one to use with NVCC=<path>"
		NVCC="$best"
	fi
	NVCC_REAL="$(readlink -f "$NVCC" 2>/dev/null)" || NVCC_REAL="$NVCC"
	say "nvcc: $NVCC ($NVCC_REAL)"
}

b_nvcc_line() {   # for BUILD-INFO: where it is and what it says it is
	local v
	v="$("$NVCC" --version 2>/dev/null | grep -i 'release' | head -n 1)" || true
	echo "nvcc $NVCC ($NVCC_REAL): ${v:-no release line in its --version}"
}

b_sha() { sha256sum < "$1" | cut -d' ' -f1; }

b_drop_info() {   # $1 a BUILD-INFO of an earlier build: it must not describe what this run leaves
	if [ -e "$1" ]; then
		say "found: $1 of an earlier build; removed now, written again when this build has ended well"
		rm -f "$1"
	fi
}

b_info_common() {
	local unread=""
	[ "$B_UNREAD" = 0 ] || unread="; unread for $B_UNREAD of them"
	echo "jobs $JOBS ($B_JOBS_WHY)"
	echo "memory cap MemoryMax=$MEM_MAX MemorySwapMax=0 by systemd-run --user --scope; the scope's memory.max read back as $B_CAP_READ"
	echo "build steps $B_STEPS, each in a scope of its own; the largest memory.peak $B_PEAK bytes; oom_kill $B_OOM$unread"
}

# ------------------------------------------------------------- run by itself
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	# The cgroup this process is in, by its cgroup v2 line: its directory under ROOT, or nothing.
	own_cgroup() {
		local line=""
		IFS= read -r line < "$1" || [ -n "$line" ] || return 1
		case "$line" in 0::/*) printf '%s' "$2${line#0::}" ;; *) return 1 ;; esac
	}
	case "${1:-}" in
		status)
			[ "$#" = 2 ] || { echo "usage: lib-build.sh status NAME" >&2; exit 64; }
			command -v flock >/dev/null || { echo "no flock: cannot tell a running build from a dead one" >&2; exit 64; }
			b_status "$2"
			exit ;;
		memory-max)
			[ "$#" = 3 ] || { echo "usage: lib-build.sh memory-max FILE ROOT" >&2; exit 64; }
			cg="$(own_cgroup "$2" "$3")" \
				|| { echo "the first line of $2 is not a cgroup v2 line: which cgroup this is cannot be told" >&2; exit 1; }
			cat "$cg/memory.max"
			exit ;;
		step)
			[ "$#" -ge 5 ] || { echo "usage: lib-build.sh step FILE ROOT OUT CMD..." >&2; exit 64; }
			self="$2"; root="$3"; out="$4"
			shift 4
			# The user manager stops a scope in which the kernel has killed for memory: TERM to
			# every process of it, this shell too. With a handler this shell waits for its
			# command and then writes what the cgroup counted, which is how the kill is known
			# at all. A handler, not `trap ''`: the command must not start with TERM ignored.
			trap : TERM
			rc=0
			"$@" || rc=$?
			peak=unread; oom=unread; own=unread
			if cg="$(own_cgroup "$self" "$root")"; then
				if [ -r "$cg/memory.peak" ]; then IFS= read -r peak < "$cg/memory.peak" || true; fi
				if [ -r "$cg/memory.events" ]; then
					while read -r k v; do
						case "$k" in oom_kill) oom="$v" ;; oom) own="$v" ;; esac
					done < "$cg/memory.events"
				fi
			fi
			printf 'peak %s\noom_kill %s\noom %s\n' "$peak" "$oom" "$own" > "$out" 2>/dev/null || true
			exit "$rc" ;;
	esac
	echo "lib-build.sh is sourced by the build scripts. Run by itself it takes: status NAME | memory-max FILE ROOT | step FILE ROOT OUT CMD..." >&2
	exit 64
fi
