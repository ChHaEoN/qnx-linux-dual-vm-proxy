#!/usr/bin/env bash
# platform-quiesce.sh -- stop docker.socket, docker and containerd for a measurement, and
# afterwards start back exactly the ones that were running. Phase 3b / A6, 2026-09-30; the
# owner's S6(a).
#
#   platform-quiesce.sh stop STATEFILE      refuse (stop nothing, write nothing) while a container runs
#                                           or an active unit depends on the three; else record the
#                                           three units' state in STATEFILE, write the marker, stop the
#                                           units, verify each is down within STOP_DEADLINE_S; one line
#                                           per unit
#   platform-quiesce.sh restore STATEFILE   start the units STATEFILE records as active (containerd,
#                                           docker, docker.socket), verify every unit is as
#                                           recorded; one line per unit; STATEFILE and the marker are
#                                           removed only when all of them are, else the exit status
#                                           is 1 and both stay
#
# stdout is exactly one line per unit; everything else (the summary, a failed systemctl call, a
# refusal, restore's report on the containers) goes to stderr.
#
# EXIT STATUS. 0: all as intended. 3 (stop only): stop REFUSED before it wrote or stopped anything -- every
# refusal path; the host is as it was found and there is nothing to undo. 1: not as intended, and for stop
# it MAY HAVE CHANGED THE HOST: a unit NOT STOPPED, or a failure after the record was written. restore exits
# 0 or 1, never 3. 2: wrong usage. A harness reads 3 and 1 differently (HARNESS USE).
#
# WHY. dockerd and containerd are ordinary userspace on whatever cores the scheduler likes -- the
# tail the confinement to cores 3,5 exists to remove -- and docker.socket would start dockerd again
# on the first connection, on any core, mid-run. Owner's S6 (2026-09-30): during A6 measurements all
# three are STOPPED for the run and put back as inventoried afterwards. lib-measure.sh's stamp
# refuses to start while they run outside {3,5} or while the socket is active, activating or
# reloading, and records the state at the start and again at the end.
#
# THE BOARD MUST NOT BE LEFT WORSE THAN IT WAS FOUND. So `stop` refuses, before it writes or stops
# anything, whenever stopping would take down something restore cannot bring back: a running container
# (THE CONTAINERS, below) or an active unit that depends on one of the three (THE DEPENDENTS), and a
# stop that does not end is bounded (THE BOUNDED STOP).
#
# THE RECORD AND THE MARKER ARE THE POINT.
#  - STATEFILE holds `is-enabled` and `is-active` of each unit as found, one line per unit, and one
#    comment line `# containers: ...` (never a unit line). It is written and read back before anything
#    is stopped. Units this host does not have (an a1.metal without Docker) are recorded as
#    `absent absent` and skipped both ways.
#  - The MARKER is one well-known file whatever STATEFILE is:
#    ${XDG_STATE_HOME:-$HOME/.local/state}/platform-quiesce.active, holding STATEFILE's absolute
#    path. `stop` refuses (stops nothing, writes nothing) while the marker exists, and names the path
#    it holds: a second stop would record a host that is already stopped and lose what the first
#    stop found. `stop` writes the marker only after the record is written and read back, and before
#    it stops anything, and never over a marker that appeared since it looked (a marker planted between
#    the check and the write is left as it is, stop's own record is removed, nothing is stopped, and the
#    exit status is 1: the record had been written).
#    `restore` refuses (starts nothing) unless the marker names this STATEFILE, and removes STATEFILE
#    and then the marker only after every unit is as recorded.
#  - The marker's directory is created (mkdir -p) by `stop` before the state file's path is made
#    absolute, after the marker check and before anything is read or stopped, so the recommended fixed
#    path below works on a home that has no ~/.local/state yet. STATEFILE's own directory is created
#    only when it is the marker's directory; otherwise it must exist, or stop refuses. A refused stop can
#    leave the marker's directory behind, empty.
#  - HARNESSES MUST USE A FIXED STATE PATH, NEVER ONE UNDER A PER-RUN $OUT. A record under $OUT is
#    found only by the run that made it: the next run, with another $OUT, would meet the marker
#    naming a file it has no reason to look in. Use one path for every run on the host, for example
#    ${XDG_STATE_HOME:-$HOME/.local/state}/platform-quiesce.state.
#  - A stale marker (its record gone, the host known to be in the state it names) is removed by hand:
#    the refusal says which file. Nothing else removes a marker that restore did not.
#
# HARNESS USE. bash keeps ONE EXIT trap, and every measuring run-*.sh already has `trap cleanup EXIT`
# (governor, C-states, QEMU, confinement); an orchestrator such as run-shift-isolation.sh, which runs
# run-ladder.sh, leaves the quiesce to the harness it runs. So the restore goes INTO that cleanup();
# it does not get a trap of its own. Never `trap - EXIT`: it drops the harness's own cleanup with it.
# Never a second EXIT trap: it replaces the first. A flag is set BEFORE stop is called, cleanup()
# restores when the flag is set, and stop's status says whether the flag stays. QUIESCE_STATE is set
# before the trap is armed, because the harnesses run with nounset; stop_vm and m_governor_restore
# stand for what the harness's cleanup() already does, and S is the fixed state path:
#     S="${XDG_STATE_HOME:-$HOME/.local/state}/platform-quiesce.state"
#     QUIESCE_STATE=""
#     cleanup() {
#         stop_vm
#         [ -z "$QUIESCE_STATE" ] || platform-quiesce.sh restore "$QUIESCE_STATE" \
#             || echo "WARNING: platform-quiesce restore failed (see its lines above)" >&2
#         m_governor_restore
#     }
#     trap cleanup EXIT
#     QUIESCE_STATE="$S"
#     rc=0; platform-quiesce.sh stop "$S" || rc=$?
#     [ "$rc" != 3 ] || QUIESCE_STATE=""
#     [ "$rc" = 0 ] || exit "$rc"
#  - On 3, clear the flag: stop refused before it wrote or stopped anything, so there is nothing to undo,
#    and the marker that made it refuse may belong to ANOTHER run that is still measuring. A harness uses
#    one fixed S, so that other run's record is at this very S: a restore run by this harness's cleanup()
#    would find the marker naming S and start that run's units under it. What keeps two runs from
#    overlapping on S in the first place is the harness's own run lock (flock); this rule covers the
#    moment before it is taken.
#  - On 1, keep the flag: stop may have changed the host (docker stopped and containerd would not, say),
#    and the restore in cleanup() is the way back. Never read a stop that exits 1 as "nothing happened".
#  - On 0, keep the flag: restore at the end of the run is the point of it.
#  - Any status but 0 ends the run (the sketch exits with it, and cleanup() runs on that exit as on any).
#  - The restore goes after QEMU is stopped and before the governor is restored: the units start on a host
#    with no guest left running, and the run's pin stays until they are up. Either order works; the
#    restore does not touch the governor.
#  - Signal a harness's process group, never its PID alone: a stop it is running is its child, and a signal
#    that reaches only the harness runs cleanup() and its restore while that stop still goes on, and the
#    stop can then outlive the cleanup and leave the units down.
# Keeping the flag on a 1 costs nothing when stop did not get as far as writing the marker (a record it
# wrote and took back again, a crash): restore then refuses harmlessly (starts nothing, removes nothing)
# when there is no marker, when the marker names another record, or when there is no record.
#
# BEFORE IT WRITES ANYTHING `stop` refuses (exit 3; no record, no marker, nothing stopped) when
#  - a present unit's `is-active` is anything but exactly `active`, `inactive` or `failed`
#    (`activating`, `deactivating`, `reloading`, `maintenance`, or nothing at all): "unit X is <state>;
#    wait until it settles and rerun". A state read in mid-transition would be recorded as if it were
#    where the unit stays.
#  - a unit's LoadState cannot be read (`systemctl show -p LoadState --value UNIT` gives nothing, an
#    error, or a word outside a safe alphabet; no systemctl at all is the same). A unit is ABSENT
#    only when that answer is exactly `not-found`; any other answer -- `loaded`, `masked`, `error`
#    -- is a unit that is there.
#  - a container is running, or its list cannot be read (THE CONTAINERS).
#  - an active unit depends on a present unit (THE DEPENDENTS).
# The reasons found in one pass are all printed (the unit states first; the dependents and the
# containers after them, and only when the unit states are fine), then stop ends with one refusal.
#
# THE CONTAINERS. Stopping docker takes its containers down with it (unless the host sets
# live-restore), and restore starts units, never containers: they come back only if their restart policy
# says so. So while docker is active, and before anything is stopped, `stop` asks the SYSTEM daemon, and
# only it:
# `timeout 10 env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_CONFIG docker -H unix:///run/docker.sock ps -q --no-trunc`,
# and if that fails the same under `sudo -n`. Every docker call this script makes is that one, and
# lib-measure.sh's containers_running asks the same daemon the same way. Its reason: the daemon this
# script stops is the one docker.service runs, on /run/docker.sock, and a caller's client configuration
# (DOCKER_HOST, DOCKER_CONTEXT, the config directory DOCKER_CONFIG names) could point `docker` at another
# -- a rootless one, a remote one -- whose empty list would read as "no containers" while the system
# daemon runs some. `-H` names the daemon, and the three `-u` keep the caller's environment from
# overriding it.
# The answer goes into the record as `# containers: ID ID ...` (full ids), `# containers: none`, or
# `# containers: unknown` (both calls failed, or a line is no container id). Not active docker is
# not asked -- there is no dockerd, and the question would start it through the socket -- and is
# recorded as `none`. By default stop REFUSES when any container runs, naming how many, and refuses
# `unknown` too: not knowing is not none. ALLOW_CONTAINERS=1 (exactly 1) lets it go on, and records
# them. restore then reports, on stderr, in one line, which recorded containers are running again,
# which are not, and which run now that were not running at stop (`running now, not at stop:
# <ids|none>`), asked once and only when docker is active (never through the socket); it never starts
# one, and a container whose restart policy brings it back may still be starting at that moment.
# Containers that docker does not run (ctr, nerdctl, k3s) are not looked at. A record of `none` gets the
# same report, as `containers at stop: 0; running now, not at stop: <ids|none>; restore starts none`:
# a restart=always container was not running at stop, and docker starts it again with the daemon, which
# restore has just started. When docker is not active at restore, or its list cannot be read, the line
# says `running now, not at stop: not known`. A record with no containers line at all gets no report and
# no question.
#
# THE DEPENDENTS. For each present unit `stop` reads, without sudo, `systemctl show -p RequiredBy
# -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy UNIT` -- Key=Value lines, one per property, in
# systemd's own order, never `--value`, which drops the keys and with them the property a name came
# from -- and refuses, naming them, when a unit it lists is not `inactive` or `failed` (so `active`,
# `activating`, `deactivating`, `reloading` or unreadable count) and is not one of the three: stopping
# one of the three would take that unit down or leave it without what it needs. A *.target is exempt
# ONLY under WantedBy (multi-user.target, sockets.target: a want is weak, stopping a unit does not stop
# the target, and they do not run docker); a target listed under RequiredBy, BoundBy, ConsistsOf or
# RequisiteOf depends on the unit for real and counts like any other dependent, and a target listed under
# WantedBy and under one of those is judged by the second. The order of the lines does not matter. A
# `show` that fails, a line that is not one of the five properties, or a name outside a safe alphabet,
# is a refusal too, not a pass.
#
# A UNIT "REACHED ITS RECORDED STATE" when `is-active` and `is-enabled` both read as recorded, with one
# equivalence: a unit recorded `inactive` or `failed` is as recorded while it is either (stop accepts
# both as down, and systemd keeps a failed unit failed). A recorded-inactive unit that is active at
# restore time is a MISMATCH -- restore never stops anything -- and so is a unit that would not come
# up; either way the record and the marker stay.
#
# STOP AND START ARE NEVER BLOCKING CALLS. restore runs `sudo -n systemctl start --no-block UNIT` and
# polls `is-active` (twice a second) until the unit is active or START_DEADLINE_S seconds have passed,
# unit by unit in the order containerd, docker, docker.socket; a unit not active by then is reported
# MISMATCH. START_DEADLINE_S is a design value, 60 unless the environment says otherwise (a whole
# number of seconds, per unit). Its reason: docker.service ships TimeoutStartSec=0 upstream, that is
# no start timeout at all, so a plain blocking `systemctl start` on a wedged docker would never
# return and would hang an unattended run's cleanup; 60 is generous for a service that normally
# starts in a few seconds, and short enough that the cleanup ends. It is not a measured figure. A
# start call that itself fails (nonzero) is not polled.
#
# THE BOUNDED STOP mirrors it. `stop` runs `sudo -n systemctl stop --no-block UNITS` for the present
# units at once and polls `is-active` (twice a second), unit by unit in the order docker.socket, docker,
# containerd, until the unit reads `inactive` or `failed` or STOP_DEADLINE_S seconds have passed; a
# unit still up by then is reported `NOT STOPPED`, the record and the marker stay, and the exit status is
# 1 (not 3: some units may be down by then). STOP_DEADLINE_S is a design value, 120 unless the environment says otherwise (a whole number of
# seconds, per unit, checked before anything is written). Its reason: systemd's default TimeoutStopSec
# is 90 s, after which it kills the unit (SIGKILL), so a stop that is going to end ends within 90 s, and
# 120 leaves that margin; but a drop-in can set TimeoutStopSec=infinity, and a plain blocking
# `systemctl stop` on such a unit would never return. It is not a measured figure. A stop call that
# itself fails (nonzero) is not polled: each unit is read once, and those still up are NOT STOPPED.
#
# WHAT IT DOES NOT DO.
#  - No persistent change: never enable, disable, mask or unmask. A reboot returns the units to
#    what the host boots with, so after a power cycle mid-run the record is stale, and restore removes
#    it (and the marker) only if, once it has started what the record says was active, the host matches
#    the record -- that is, only if the record matches what the host boots with; otherwise it reports
#    the mismatch and keeps both.
#  - It never starts a container, and it only looks at containers that docker runs.
#  - It does not touch cores, cgroups, nvpmodel, images, volumes or the network.
#  - sudo is used only as `sudo -n`, for `systemctl stop --no-block`, `systemctl start --no-block` and,
#    when the direct call fails, the container list (the same `timeout 10 env -u ... docker -H
#    unix:///run/docker.sock ps -q --no-trunc`); the state is read without it. It never prompts.
#  - It never talks to a docker daemon but the system one, whatever DOCKER_HOST, DOCKER_CONTEXT or
#    DOCKER_CONFIG say.
set -u

UNITS="docker.socket docker containerd"          # the order they are stopped in
RESTORE_ORDER="containerd docker docker.socket"  # the order they are started in
START_DEADLINE_S="${START_DEADLINE_S:-60}"
STOP_DEADLINE_S="${STOP_DEADLINE_S:-120}"
declare -A S_EN S_ACT G_EN G_ACT
ERR=""; MARKER=""; HELD=""; LS=""; REC_CONT=""; RUNNING=""; NRUN=0; BLOCKERS=""

# die: exit 1, "not as intended, and the host may have changed". refuse: exit 3, stop's own, "refused
# before it wrote or stopped anything": stop uses it up to the moment its record is written, die after.
die() { echo "platform-quiesce: $*" >&2; exit 1; }
refuse() { echo "platform-quiesce: $*" >&2; exit 3; }
usage() {
	echo "usage: platform-quiesce.sh stop|restore STATEFILE" >&2
	exit 2
}

# A deadline is a whole number of seconds of at most six digits.
check_deadline() {  # $1 = variable name  $2 = its value  $3 = what was not done  $4 = refuse (stop) | die (restore)
	case "$2" in
		''|*[!0-9]*) "$4" "$1='$2' is not a whole number of seconds: nothing was $3" ;;
	esac
	[ "${#2}" -le 6 ] || "$4" "$1='$2' is more than six digits: nothing was $3"
}

# The first word `systemctl $1 $2` prints, in a safe alphabet. `unknown` for a word outside it (never
# a word with characters silently dropped: `activ"e` must not read as `active`) and for no word at
# all (a unit systemctl has nothing to say about, or no systemctl).
word() {            # $1 = is-enabled|is-active  $2 = unit
	local out w="" rest
	out="$(systemctl "$1" "$2" 2>/dev/null || true)"
	read -r w rest <<< "$out" || true
	case "$w" in ''|*[!A-Za-z0-9._-]*) w=unknown ;; esac
	printf '%s' "$w"
}

enabled_word() { word is-enabled "$1"; }
active_word()  { word is-active "$1"; }

# LS = the unit's LoadState word. Returns 1, leaving LS empty, when it cannot be read: no systemctl,
# an error, no output, or a word outside the safe alphabet. Never guesses `not-found`.
loadstate() {       # $1 = unit
	local out w="" rest
	LS=""
	command -v systemctl >/dev/null 2>&1 || return 1
	out="$(systemctl show -p LoadState --value "$1" 2>/dev/null)" || return 1
	read -r w rest <<< "$out" || true
	[ -n "$w" ] || return 1
	case "$w" in *[!A-Za-z0-9._-]*) return 1 ;; esac
	LS="$w"
}

# RUNNING = the ids of the running containers (full length, blank separated; empty for none), NRUN
# their number. Returns 1, with RUNNING empty, when they cannot be listed: the direct call and the
# sudo one both fail, or a line is not a container id. Asks the SYSTEM daemon only (THE CONTAINERS): the
# caller's DOCKER_HOST, DOCKER_CONTEXT and DOCKER_CONFIG are removed from the call, and -H names it.
list_containers() {
	local out line
	local -a dps=(env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_CONFIG docker -H unix:///run/docker.sock ps -q --no-trunc)
	RUNNING=""; NRUN=0
	if ! out="$(timeout 10 "${dps[@]}" 2>/dev/null)"; then
		out="$(sudo -n timeout 10 "${dps[@]}" 2>/dev/null)" || return 1
	fi
	while IFS= read -r line || [ -n "$line" ]; do
		[ -n "$line" ] || continue
		if ! [[ "$line" =~ ^[0-9a-f]{12,64}$ ]]; then RUNNING=""; NRUN=0; return 1; fi
		RUNNING="$RUNNING${RUNNING:+ }$line"; NRUN=$((NRUN + 1))
	done <<< "$out"
}

# BLOCKERS = the units that systemd lists as depending on $1 (RequiredBy, BoundBy, ConsistsOf,
# RequisiteOf, WantedBy) and that are not one of the three, not exempt and not inactive or failed, each
# as `name (state)`; empty when there is none. Returns 1 when the list cannot be read. The `show` prints
# Key=Value lines in systemd's own order, so the lines are parsed as such (no --value: it drops the keys)
# and a name is judged by the property it came under: a *.target is exempt only under WantedBy.
active_dependents() {   # $1 = unit
	local out line key val n st seen=" " pair
	local -a names=() pairs=()
	local ok='^[A-Za-z0-9_.:@\\][-A-Za-z0-9_.:@\\]*$'    # a unit name: letters, digits and _ . : @ \ -
	BLOCKERS=""
	command -v systemctl >/dev/null 2>&1 || return 1
	out="$(systemctl show -p RequiredBy -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy "$1" 2>/dev/null)" || return 1
	while IFS= read -r line || [ -n "$line" ]; do        # first every line is read, as `Key name`
		[ -n "$line" ] || continue
		case "$line" in *=*) ;; *) return 1 ;; esac
		key="${line%%=*}"; val="${line#*=}"
		case "$key" in RequiredBy|BoundBy|ConsistsOf|RequisiteOf|WantedBy) ;; *) return 1 ;; esac
		read -ra names <<< "$val" || true
		[ "${#names[@]}" -gt 0 ] || continue
		for n in "${names[@]}"; do pairs+=("$key $n"); done
	done <<< "$out"
	[ "${#pairs[@]}" -gt 0 ] || return 0
	for pair in "${pairs[@]}"; do
		key="${pair%% *}"; n="${pair#* }"
		# the exemptions come before the `seen` check: a target skipped under WantedBy must not hide the
		# same target under RequiredBy
		case "$n" in *.target) [ "$key" != WantedBy ] || continue ;; esac
		case "$n" in docker|docker.service|docker.socket|containerd|containerd.service) continue ;; esac
		case "$seen" in *" $n "*) continue ;; esac
		seen="$seen$n "
		if ! [[ "$n" =~ $ok ]]; then
			BLOCKERS="$BLOCKERS ${n//[^[:print:]]/?} (name not readable)"
			continue
		fi
		st="$(active_word "$n")"
		case "$st" in inactive|failed) ;; *) BLOCKERS="$BLOCKERS $n ($st)" ;; esac
	done
}

# MARKER = where the marker lives. Returns 1 (having said why) when there is nowhere to put it.
set_marker_path() {
	local base
	if [ -n "${XDG_STATE_HOME:-}" ]; then
		base="$XDG_STATE_HOME"
	elif [ -n "${HOME:-}" ]; then
		base="$HOME/.local/state"
	else
		echo "platform-quiesce: neither XDG_STATE_HOME nor HOME is set: there is nowhere to put the marker" >&2
		return 1
	fi
	case "$base" in
		/*) ;;
		*) echo "platform-quiesce: the marker directory '$base' is not an absolute path" >&2; return 1 ;;
	esac
	MARKER="${base%/}/platform-quiesce.active"
}

# HELD = the path the marker holds. Returns 0 when it does, 1 when there is no marker, 2 when there is
# one that names nothing readable (empty, a directory, unreadable).
read_marker() {
	HELD=""
	[ -e "$MARKER" ] || [ -L "$MARKER" ] || return 1
	# 2>/dev/null before the `<`: bash applies redirections left to right
	IFS= read -r HELD 2>/dev/null < "$MARKER" || true
	[ -n "$HELD" ] || return 2
}

# The absolute, physical path of a file that need not exist yet: its directory must. Pure bash, so it
# needs no tool. Fails for a path with no file name or whose directory is missing.
abspath() {         # $1 = path
	local p="$1" d b
	case "$p" in
		*/*) d="${p%/*}"; b="${p##*/}" ;;
		*)   d="."; b="$p" ;;
	esac
	[ -n "$d" ] || d=/
	case "$b" in ''|.|..) return 1 ;; esac
	d="$(cd -- "$d" 2>/dev/null && pwd -P)" || return 1
	if [ "$d" = / ]; then printf '/%s' "$b"; else printf '%s/%s' "$d" "$b"; fi
}

# Fills S_EN and S_ACT from a state file, and REC_CONT from its `# containers:` line (empty when the
# file has none; `unreadable` when the line is not one of ours: restore only reports it, so it does not
# make the file refuse). On a file that is not one of ours it sets ERR and returns 1.
read_state() {      # $1 = file
	local line="" u="" en="" act="" extra="" seen_cont=0
	S_EN=(); S_ACT=(); ERR=""; REC_CONT=""
	while IFS= read -r line || [ -n "$line" ]; do
		case "$line" in
			'# containers: '*)
				if [ "$seen_cont" = 1 ]; then REC_CONT=unreadable
				elif [[ "${line#\# containers: }" =~ ^(none|unknown|[0-9a-f]{12,64}( [0-9a-f]{12,64})*)$ ]]; then REC_CONT="${line#\# containers: }"
				else REC_CONT=unreadable; fi
				seen_cont=1; line=""; continue ;;
			''|'#'*) line=""; continue ;;
		esac
		u=""; en=""; act=""; extra=""
		read -r u en act extra <<< "$line" || true
		if [ -z "$u" ] || [ -z "$en" ] || [ -z "$act" ] || [ -n "$extra" ]; then ERR="malformed line '$line'"; return 1; fi
		case " $UNITS " in *" $u "*) ;; *) ERR="unknown unit '$u'"; return 1 ;; esac
		[[ "$en $act" =~ ^[A-Za-z0-9._-]+\ [A-Za-z0-9._-]+$ ]] || { ERR="malformed line '$line'"; return 1; }
		case "$act" in active|inactive|failed|absent) ;; *) ERR="malformed line '$line' (state '$act')"; return 1 ;; esac
		# absent goes with absent and with nothing else
		if [ "$en" = absent ] || [ "$act" = absent ]; then
			[ "$en" = absent ] && [ "$act" = absent ] || { ERR="malformed line '$line'"; return 1; }
		fi
		[ -z "${S_EN[$u]+x}" ] || { ERR="unit '$u' recorded twice"; return 1; }
		S_EN[$u]="$en"; S_ACT[$u]="$act"
		line=""
	done < "$1"
	for u in $UNITS; do
		[ -n "${S_EN[$u]+x}" ] || { ERR="no line for $u"; return 1; }
	done
}

# 0 when a unit now reading $2 is as one recorded $1: the same word, or inactive and failed for each other.
same_active() {     # $1 = recorded  $2 = now
	[ "$1" = "$2" ] && return 0
	case "$1/$2" in inactive/failed|failed/inactive) return 0 ;; esac
	return 1
}

# 0 when the unit reads `active` within START_DEADLINE_S seconds (polled twice a second), else 1.
wait_active() {     # $1 = unit
	local tries=$((10#$START_DEADLINE_S * 2))      # 10#: a leading zero is not octal
	while :; do
		[ "$(active_word "$1")" != active ] || return 0
		[ "$tries" -gt 0 ] || return 1
		sleep 0.5
		tries=$((tries - 1))
	done
}

# 0 when the unit reads `inactive` or `failed` within STOP_DEADLINE_S seconds (polled twice a second), else 1.
wait_down() {       # $1 = unit
	local tries=$((10#$STOP_DEADLINE_S * 2))
	while :; do
		case "$(active_word "$1")" in inactive|failed) return 0 ;; esac
		[ "$tries" -gt 0 ] || return 1
		sleep 0.5
		tries=$((tries - 1))
	done
}

# Exit statuses (EXIT STATUS in the header): every refusal up to the moment the record is written is
# `refuse` (3: nothing written, nothing stopped, nothing for the harness to undo); from the record's
# write on, a failure is `die` or a `return 1` (1: the host may have changed, and the restore in the
# harness's cleanup() is the way back).
cmd_stop() {        # $1 = state file
	local state="$1" abs u en act body present="" bad=0 now rc wrote=0 problems=0 cont mdir queued=0
	check_deadline STOP_DEADLINE_S "$STOP_DEADLINE_S" stopped refuse
	set_marker_path || exit 3
	rc=0; read_marker || rc=$?
	case "$rc" in
		0) refuse "stop refused: an earlier stop is outstanding -- $MARKER names $HELD. Run 'platform-quiesce.sh restore $HELD' first, or remove the marker if you know that record is stale. Nothing was stopped and nothing was written." ;;
		2) refuse "stop refused: $MARKER exists but names no readable path. Remove it if you know no earlier stop is outstanding. Nothing was stopped and nothing was written." ;;
	esac
	if [ -e "$state" ] || [ -L "$state" ]; then
		refuse "$state already exists: it is the record of the state before an earlier stop, and restore needs it. Run restore, or remove it if you know it is stale."
	fi
	# The marker's directory, before abspath needs the state file's: a fixed state path in it then works
	# on a home without ~/.local/state. It is the only directory stop creates.
	mdir="${MARKER%/*}"; [ -n "$mdir" ] || mdir=/
	mkdir -p -- "$mdir" 2>/dev/null || refuse "cannot write the marker $MARKER (its directory could not be created): nothing was stopped, and nothing was written"
	abs="$(abspath "$state")" || refuse "cannot create $state (its directory must exist, and it must be a new file in a writable directory)"
	case "$abs" in *$'\n'*) refuse "the path of $state has a newline in it, which the marker cannot hold" ;; esac

	# Read every unit before anything is written or stopped.
	for u in $UNITS; do
		if ! loadstate "$u"; then
			echo "platform-quiesce: refused: cannot read the LoadState of $u ('systemctl show -p LoadState --value $u' gave no usable answer), so it is not recorded as absent" >&2
			problems=1
			continue
		fi
		if [ "$LS" = not-found ]; then
			G_EN[$u]=absent; G_ACT[$u]=absent
			continue
		fi
		G_EN[$u]="$(enabled_word "$u")"; G_ACT[$u]="$(active_word "$u")"
		present="$present $u"
		case "${G_ACT[$u]}" in
			active|inactive|failed) ;;
			*) echo "platform-quiesce: refused: unit $u is ${G_ACT[$u]}; wait until it settles and rerun" >&2; problems=1 ;;
		esac
	done
	[ "$problems" = 0 ] || refuse "nothing was stopped, no record and no marker was written"

	# What stopping would take down that restore cannot bring back: units that depend on these, and
	# containers. Both only read.
	for u in $present; do
		if ! active_dependents "$u"; then
			echo "platform-quiesce: refused: cannot read what depends on $u ('systemctl show -p RequiredBy -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy $u' failed), so it is not known that nothing does" >&2
			problems=1
		elif [ -n "$BLOCKERS" ]; then
			echo "platform-quiesce: refused: $u has dependents that are not inactive:$BLOCKERS -- stopping it would take them down or leave them without it; stop them yourself first" >&2
			problems=1
		fi
	done
	cont=none
	if [ "${G_ACT[docker]}" = active ]; then
		if list_containers; then
			[ "$NRUN" = 0 ] || cont="$RUNNING"
		else
			cont=unknown
		fi
	fi
	case "$cont" in
		none) ;;
		unknown)
			if [ "${ALLOW_CONTAINERS:-}" = 1 ]; then
				echo "platform-quiesce: ALLOW_CONTAINERS=1: the running containers could not be listed; recorded as unknown, going on" >&2
			else
				echo "platform-quiesce: refused: the running containers cannot be listed ('docker -H unix:///run/docker.sock ps -q --no-trunc' under timeout 10 failed, and so did the same under sudo -n), so it is not known that stopping docker takes none down; ALLOW_CONTAINERS=1 goes on regardless" >&2
				problems=1
			fi ;;
		*)
			if [ "${ALLOW_CONTAINERS:-}" = 1 ]; then
				echo "platform-quiesce: ALLOW_CONTAINERS=1: $NRUN running container(s) are recorded and go down with docker; restore will not start them" >&2
			else
				echo "platform-quiesce: refused: $NRUN running container(s): stopping docker takes them down and restore does not start containers; stop them yourself, or ALLOW_CONTAINERS=1 goes on regardless (they are then recorded)" >&2
				problems=1
			fi ;;
	esac
	[ "$problems" = 0 ] || refuse "nothing was stopped, no record and no marker was written"

	body="# platform-quiesce state, recorded $(date -u +%Y-%m-%dT%H:%M:%SZ) by stop"$'\n'
	body="$body# containers: $cont"$'\n'
	for u in $UNITS; do body="$body$u ${G_EN[$u]} ${G_ACT[$u]}"$'\n'; done
	# noclobber: a file that appeared since the check above is refused, not overwritten
	( set -C; printf '%s' "$body" > "$state" ) 2>/dev/null || refuse "cannot create $state (it must be a new file in a writable directory)"
	sync 2>/dev/null || true
	if ! read_state "$state"; then
		rm -f -- "$state"
		die "$state does not read back as written ($ERR): nothing was stopped, and the record was removed"
	fi
	for u in $UNITS; do
		if [ "${S_EN[$u]}" != "${G_EN[$u]}" ] || [ "${S_ACT[$u]}" != "${G_ACT[$u]}" ]; then
			rm -f -- "$state"
			die "$state does not read back as written ($u differs): nothing was stopped, and the record was removed"
		fi
	done
	if [ "$REC_CONT" != "$cont" ]; then
		rm -f -- "$state"
		die "$state does not read back as written (its containers line differs): nothing was stopped, and the record was removed"
	fi

	# The marker: after the record is written and read back, before anything is stopped. noclobber, so
	# a marker that appeared since the check above (a second stop that got this far at the same moment)
	# is refused, not overwritten, and is not removed either: it is not ours.
	if mkdir -p -- "$mdir" 2>/dev/null && ( set -C; printf '%s\n' "$abs" > "$MARKER" ) 2>/dev/null; then
		wrote=1
		sync 2>/dev/null || true
	fi
	rc=0; read_marker || rc=$?
	if [ "$wrote" != 1 ] || [ "$rc" != 0 ] || [ "$HELD" != "$abs" ]; then
		[ "$wrote" != 1 ] || rm -f -- "$MARKER"
		rm -f -- "$state"
		die "cannot write the marker $MARKER (it must be a new file in a writable directory; it holds '${HELD:-nothing}'): nothing was stopped, and the record was removed"
	fi

	if [ -n "$present" ]; then
		# shellcheck disable=SC2086
		if sudo -n systemctl stop --no-block $present >/dev/null 2>&1; then
			queued=1
		else
			echo "platform-quiesce: 'sudo -n systemctl stop --no-block$present' failed; verifying each unit anyway" >&2
		fi
	fi
	for u in $UNITS; do
		en="${S_EN[$u]}"; act="${S_ACT[$u]}"
		if [ "$en" = absent ]; then
			echo "$u: absent on this host, skipped"
			continue
		fi
		if [ "$queued" = 1 ]; then
			wait_down "$u" || echo "platform-quiesce: $u is not down $STOP_DEADLINE_S s after its stop was queued" >&2
		fi
		now="$(active_word "$u")"
		case "$now" in
			inactive|failed) echo "$u: was $en/$act, now $now ok" ;;
			*) echo "$u: was $en/$act, now $now NOT STOPPED"; bad=1 ;;
		esac
	done
	if [ "$bad" != 0 ]; then
		echo "platform-quiesce: not every unit is down; the record stays in $state and the marker in $MARKER (restore verifies them and removes both)" >&2
		return 1
	fi
	echo "platform-quiesce: recorded in $state (marker $MARKER); restore with: platform-quiesce.sh restore $state" >&2
}

# One stderr line on the containers the record holds: which run again, which do not, and which run now
# that were not running at stop. For a record of `none` the same, with nothing recorded to run again.
# Asks only while docker is active, so the question never starts dockerd through its socket. A record
# with no containers line gets no line. Starts nothing.
report_containers() {
	local id rec="$REC_CONT" up="" gone="" fresh="" n=0
	case "$rec" in
		'') return 0 ;;
		unreadable) echo "platform-quiesce: the record's '# containers:' line is not one of ours; restore cannot say which containers ran, and starts none" >&2; return 0 ;;
		unknown) echo "platform-quiesce: containers at stop: unknown (they could not be listed); restore starts none" >&2; return 0 ;;
		none) rec="" ;;
	esac
	for id in $rec; do n=$((n + 1)); done
	if [ "$(active_word docker)" != active ] || ! list_containers; then
		if [ -z "$rec" ]; then
			echo "platform-quiesce: containers at stop: 0; running now, not at stop: not known; restore starts none" >&2
		else
			echo "platform-quiesce: containers at stop: $n; which of them run again is not known (docker is not active, or its list cannot be read); running now, not at stop: not known; restore starts none" >&2
		fi
		return 0
	fi
	for id in $rec; do
		case " $RUNNING " in *" $id "*) up="$up ${id:0:12}" ;; *) gone="$gone ${id:0:12}" ;; esac
	done
	for id in $RUNNING; do          # running now and not recorded at stop: a report, nothing is done about it
		case " $rec " in *" $id "*) ;; *) fresh="$fresh ${id:0:12}" ;; esac
	done
	if [ -z "$rec" ]; then
		echo "platform-quiesce: containers at stop: 0; running now, not at stop:${fresh:- none}; restore starts none" >&2
	else
		echo "platform-quiesce: containers at stop: $n; running again:${up:- none}; not running:${gone:- none}; running now, not at stop:${fresh:- none}; restore starts none" >&2
	fi
}

cmd_restore() {     # $1 = state file
	local state="$1" abs u en act now_en now_act bad=0 rc
	check_deadline START_DEADLINE_S "$START_DEADLINE_S" started die
	set_marker_path || exit 1
	if [ ! -e "$state" ] && [ ! -L "$state" ]; then
		echo "platform-quiesce: cannot read $state: nothing to restore from" >&2
		rc=0; read_marker || rc=$?
		[ "$rc" != 0 ] || echo "platform-quiesce: $MARKER names $HELD; if that record is gone for good, remove the marker" >&2
		exit 1
	fi
	{ [ -f "$state" ] && [ ! -L "$state" ]; } || die "$state is not a regular file: nothing was started"
	[ -r "$state" ] || die "cannot read $state: nothing to restore from"
	abs="$(abspath "$state")" || die "cannot resolve the path of $state: nothing was started"
	rc=0; read_marker || rc=$?
	case "$rc" in
		1) die "no marker $MARKER: no stop is outstanding, so $state is not a record restore acts on, and nothing was started. If it is the record of a stop whose marker was lost, write the marker back: printf '%s\\n' '$abs' > '$MARKER'" ;;
		2) die "$MARKER exists but names no readable path: nothing was started" ;;
	esac
	[ "$HELD" = "$abs" ] || die "$MARKER names $HELD, not $abs: nothing was started. Restore that record, or remove the marker if you know it is stale."
	read_state "$state" || die "$state is not a record of this script ($ERR): nothing was started"
	for u in $RESTORE_ORDER; do
		[ "${S_EN[$u]}" != absent ] || continue
		[ "${S_ACT[$u]}" = active ] || continue
		if sudo -n systemctl start --no-block "$u" >/dev/null 2>&1; then
			wait_active "$u" || echo "platform-quiesce: $u is not active $START_DEADLINE_S s after its start was queued" >&2
		else
			echo "platform-quiesce: 'sudo -n systemctl start --no-block $u' failed" >&2
		fi
	done
	# Verified after every start: docker pulls its socket in, so a unit's state is only final now.
	for u in $RESTORE_ORDER; do
		en="${S_EN[$u]}"; act="${S_ACT[$u]}"
		if [ "$en" = absent ]; then
			echo "$u: absent when recorded, skipped"
			continue
		fi
		now_en="$(enabled_word "$u")"; now_act="$(active_word "$u")"
		if [ "$now_en" = "$en" ] && same_active "$act" "$now_act"; then
			echo "$u: recorded $en/$act, now $now_en/$now_act ok"
		else
			echo "$u: recorded $en/$act, now $now_en/$now_act MISMATCH"; bad=1
		fi
	done
	report_containers
	if [ "$bad" != 0 ]; then
		echo "platform-quiesce: not every unit is as recorded; $state and $MARKER are kept" >&2
		return 1
	fi
	rm -f -- "$state"
	sync 2>/dev/null || true
	[ ! -e "$state" ] || die "every unit is as recorded but $state could not be removed"
	rm -f -- "$MARKER"
	[ ! -e "$MARKER" ] && [ ! -L "$MARKER" ] || die "every unit is as recorded and $state is removed, but the marker $MARKER could not be removed: remove it by hand"
	echo "platform-quiesce: restored; $state and $MARKER removed" >&2
}

[ $# -eq 2 ] || usage
case "$1" in
	stop)    cmd_stop "$2" ;;
	restore) cmd_restore "$2" ;;
	*)       usage ;;
esac
