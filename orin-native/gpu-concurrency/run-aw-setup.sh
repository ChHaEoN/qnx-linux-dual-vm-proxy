#!/usr/bin/env bash
# run-aw-setup.sh -- bring a bare-metal AWS instance up for the Autoware session's suite (run-aw-suite.sh): the aw inputs
# checked, the scenario's map staged, the Autoware arm64 image pulled by its digest and read back, its SIGILL smoke under
# the project entrypoint, MemAvailable around them and D7's 30-minute rule. SDV Phase 8 WP6 9.2.
# The record describes operational steps; it makes no benchmark claim.
#
# HOW IT RUNS. Only as remote-ladder.sh's harness phase starts it, detached, in an aw session (scripts/aws/README.md, "An
# aw session"): LADDER_ENV="HARNESS=run-aw-setup.sh IMAGE=ifs-ctl.bin VSS_HOST=c7g-metal", once per session, after
# run-vss-setup.sh ended status=DONE with VSS_HOST=c7g-metal, from a later login than that setup's (the docker group it
# added applies from it). The detached runner runs it from $R = $W/repo/orin-native/gpu-concurrency with stdout and stderr
# in rec/aw-setup/run.log and SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored (a step under its cap starts with only SIGPIPE of
# them ignored: remote-ladder.sh, SIGNALS), then reads its last status line. Its environment:
#   W         the session's directory (~/a1): inputs.env, repo.tar and repo/ (the vss tarball, which carries sdv/aw),
#             rec/vss-setup (run-vss-setup.sh's record)
#   AW_IN     $W/aw-in, the aw inputs (aw_setup.py, THE AW INPUTS): aw-inputs.json, aw-scan.json, aw-map.tar. They come
#             in METAL_FILES beside the upload bundle, and remote-ladder.sh's setup moves every aw-* file from in/ to here
#             once its hash is checked, since run-vss-setup.sh's `bundle.py verify` refuses a file in in/ that bundle.json
#             does not list
#   OUT       rec/aw-setup/raw, the record; STATUS rec/aw-setup/status (lib-vss-deadline.sh's vss_status writes it)
#   VSS_HOME  $W/sdv: aw/map/<map>/, the staged map the suite mounts; aw-setup-work/, this harness's own working files
#             (never captured): its facts, 2.7's DDS file, the smoke's output and ROS log directory
#   VSS_HOST  the host's role, c7g-metal and nothing else
#   IFS_BIN   the session's METAL_IFS, which must be named ifs-ctl.bin (the suite's guest): only its name is read here
# IMG_S, IMG_B, DISK, VPROBE, CSTATE and VSS_IN come with the phase's environment and are not used here. For the tests,
# QNX_METAL_DEADLINE_FILE overrides the deadline file, QNX_MEMINFO_FILE /proc/meminfo, and QNX_L4T_RELEASE_FILE and
# QNX_DT_COMPATIBLE_FILE L4T's release file and the device tree's compatible.
#
# THE HOST. VSS_HOST must be c7g-metal: the owner took the a1-metal role off the Autoware image's hosts on 2026-10-24 (after
# 9.1's A72 scan of the image), and the Orin's days are WP8's helper's. Any other value, unset or empty included, is
# refused before step 1 (status=FAILED at=preflight), and so is c7g-metal on a host that L4T's release file or an NVIDIA
# device tree marks as a Jetson. Nothing here names an instance type, a core count or a core list.
#
# 2.12 ON A METAL HOST (the image's own entrypoint changes host network settings when it may). The one container this
# harness starts, the smoke, runs with --entrypoint the tarball's sdv/aw/aw-entrypoint.sh (mounted read-only at /sdv-aw),
# --user aw, --cap-drop ALL and --security-opt no-new-privileges, and never --privileged, --cap-add or a /proc/sys or /sys
# mount; CYCLONEDDS_URI names 2.7's file (sdv/aw/ros-env.json's XML, written to aw-setup-work/dds and mounted read-only),
# never the image's own cyclonedds.xml; ROS_DOMAIN_ID and RMW_IMPLEMENTATION are ros-env.json's, ROS_LOG_DIR a directory
# under aw-setup-work. Its output directory is made writable for aw by the login's group (--group-add, the directory 0775),
# never by mode 777. The host check: the four settings hostcheck.sh prints are read in the preflight, before the first
# container, and appended to the stem's host-before.txt (after what the harness phase wrote there); read again after the
# sweep and appended to host-after.txt (before what the detached runner appends), then compared by `hostcheck.sh
# --compare`: a difference, or an after-read that fails, ends the stem status=FAILED at=host-check with each changed
# setting named in run.log, setup.json and host-after.txt. Nothing reverts it.
#
# THE STEPS, in this order. Before each, the deadline's check point (lib-vss-deadline.sh: now >= stop_at stops here);
# each runs under its cap (stop_at + 10 minutes - now, `timeout --kill-after=30s`) as a child of this script, called in
# the library's set -e form, rc=0; vss_capped CMD... || rc=$?, then vss_cap_fired "$rc". Each step's UTC start and end
# and its whole seconds go into setup.json.
#   1 preflight  first, before any effect, IFS_BIN named ifs-ctl.bin: run-aw-suite.sh boots WP5's image alone and refuses
#                any other, so a setup for another would spend the session's pull on a suite that cannot run (refused in
#                the suite's words); the login in the docker group (`id -nG`); rec/vss-setup has done, its status file's
#                last status= line is exactly status=DONE, and its raw/setup.json says DONE with host_mode VSS_HOST's
#                (aw_setup.py vss-setup);
#                the tarball's sdv/aw/aw-entrypoint.sh (executable), hostcheck.sh and ros-env.json, sdv/stack/images.json
#                and the scenario (SCENARIO); the aw inputs (aw_setup.py inputs: aw-inputs.json and every file it lists of
#                its sha256 and in FILES, nothing else in AW_IN, its commit the repo tarball's), which writes inputs.txt;
#                aw-scan.json's image_digest the digest to pull (its verdict recorded, not required: the owner's decision of
#                2026-10-24); 2.7's DDS
#                file written; no container labelled sdv.aw.run (an earlier aw run's would collide on the names);
#                MemAvailable read; then the host check before
#   2 stage      aw-map.tar into VSS_HOME/aw/map/<map>/, exactly the scenario's map files, each of its sha256
#                (aw_setup.py stage-map); a map that is not the scenario's is a real failure
#   3 pull       `docker pull autoware.repo@autoware.arm64.manifest_digest` (images.json's; never a tag) and its whole
#                seconds (the pull's wall time, a fact of the record); then `docker image inspect` read back (the ID,
#                RepoDigests, Os and Architecture: never the raw inspect), which must hold the reference in RepoDigests,
#                and the image store's driver-type
#   4 smoke      the SIGILL smoke: `ros2 --help` in the pulled image on this host's cores, under 2.12, with --network none:
#                its exit status and its stderr's last 20 lines. An exit other than 0 is a real failure: the image does not
#                start here (132 is SIGILL)
#   5 budget     MemAvailable read again; D7's rule: when less than 30 minutes are left before stop_at after the pull and
#                the smoke, budget_short is true, which the suite's preflight refuses (setup still ends DONE)
#   6 close      the image, the smoke's verdict and budget_short said in run.log, whose last 30 lines wait-run prints
# Then the sweep (below), the host check after, setup.json written whole, and the status line.
#
# THE STATUS LINE, the last one in STATUS, through vss_status:
#   status=DONE                                  every step ran; setup.json written first (a temporary file, a rename)
#   status=TIMEOUT at=<step> reason=deadline     a check point found now >= stop_at; <step> and the rest did not run
#   status=TIMEOUT at=<step> reason=step-timeout <step>'s cap fired: it was cut, the rest did not run
#   status=FAILED at=preflight                   the preflight refused, or the host, or no readable deadline file
#   status=FAILED at=host-check                  the host check after the sweep found a setting changed, or could not
#                                                be read: whatever the stem would have ended with is under setup.json's
#                                                facts.host_check.outcome_before_host_check
#   status=FAILED at=<step>                      a real failure: the stage, the pull or its read-back, the smoke; also a
#                                                step that exits non-zero for any other reason, and a parent that ends
#                                                without a status line, through its EXIT trap ("the harness stopped
#                                                unexpectedly", at the step it was in)
#   status=FAILED at=close                       every step ran, but setup.json could not be written
# Every FAILED exits 1, a TIMEOUT 0. Every stop sweeps before its record once the preflight has passed, DONE included: the
# smoke's container removed by name, then every container labelled sdv.aw.run listed and removed; when they cannot be
# listed, the aw names (AW_CONTAINERS) are removed unseen. A list that fails or a container still listed records the stop
# unverified (facts.stop.verified false, with why) and says so in run.log; the status line is not changed by it. Every stop
# but DONE syncs first; the steps not run go to run.log and setup.json, and setup.json is written in every case.
#
# THE RECORD, in OUT (each name on capture.py's whitelist under aw-setup/raw, 2.11): setup.json (the steps, those not run,
# the image pulled and the ID read back, budget_short, and every fact: the inputs' checks, the scan's verdict and counts,
# the map, the pull, the store's type, the smoke's exit and stderr, MemAvailable before and after, the host check, the
# sweep) and inputs.txt (each aw input's sha256 and its check, the two commits). The stem's run.log, status,
# host-before.txt and host-after.txt hold the rest. Every string in setup.json is one line. Docker runs through the
# docker group (the preflight asks for it), never under sudo; nothing here needs root.
#
# DESIGN VALUES (not measured): the 30-minute rule's threshold (D7); the smoke's stderr kept to its last 20 lines; the
# sweep's bounds (60 s a listing or a removal by name, 120 s a removal or a sync).
#
# WHAT IT DOES NOT SHOW: that the suite will pass, or that Autoware runs on this host beyond `ros2 --help`'s start-up; any
# timing (the operational_s values are whole seconds of this session's own steps); that the image would run on the A72;
# that the four host settings are the only ones a container could change (they are the ones the image's own entrypoint
# changes).
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
: "${W:?run-aw-setup.sh runs from the harness phase (W)}" "${OUT:?no OUT}" "${AW_IN:?no AW_IN}" "${VSS_HOME:?no VSS_HOME}"
: "${STATUS:?no STATUS}"

TOOL="$HERE/aw_setup.py"
VSS_TOOL="$HERE/vss_setup.py"
REPO="$W/repo"
STACK="$REPO/sdv/stack"
AW="$REPO/sdv/aw"
HC="$AW/hostcheck.sh"
SCENARIO=sample-lanelet-102
SCN="$REPO/sdv/ctl/scenarios/$SCENARIO.json"
SETUP_REC="$W/rec/vss-setup"
WORK="$VSS_HOME/aw-setup-work"
MAP_DEST="$VSS_HOME/aw/map"
STEM="$(dirname "$OUT")"
STEM_NAME=aw-setup
STEPS=(preflight stage pull smoke budget close)
NSTEPS=${#STEPS[@]}
RULE_LEFT_S=1800                 # D7: the 30-minute rule
STDERR_LINES=20
LABEL=sdv.aw.run
# every container an aw harness starts (spec-2 2.1's four and this harness's smoke): the sweep's names when the label
# cannot be listed
AW_CONTAINERS=(aw-sim aw-claim-node aw-scenario ros-vss-feeder aw-smoke)
HOST_MODE="${VSS_HOST-}"
WANT_MODE=c7g-metal
MEMINFO="${QNX_MEMINFO_FILE:-/proc/meminfo}"
L4T_RELEASE="${QNX_L4T_RELEASE_FILE:-/etc/nv_tegra_release}"
DT_COMPATIBLE="${QNX_DT_COMPATIBLE_FILE:-/proc/device-tree/compatible}"

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

fact() {   # STEP KEY TYPE VALUE: one fact for setup.json (vss_setup.py, FACTS); a KEY with "/" is a nested object
	local f="$WORK/facts/$1/$2.$3"
	mkdir -p "$(dirname "$f")"
	printf '%s' "$4" > "$f"
}
die_step() {   # STEP WHY...: a real failure, WHY's words joined by spaces; the parent writes the record
	local why="${*:2}"
	fact "$1" failure s "$why"
	say "FAILED in $1: $why" >&2
	exit 1
}

# --- the host (THE HOST) ---------------------------------------------------------------------------------------------
on_jetson() {   # whether L4T's release file or an NVIDIA device tree marks this host as a Jetson: builtins only
	local c=""
	[ ! -e "$L4T_RELEASE" ] || return 0
	[ -r "$DT_COMPATIBLE" ] || return 1
	IFS= read -r -d '' c < "$DT_COMPATIBLE" || true
	case "$c" in nvidia,*) return 0 ;; esac
	return 1
}
host_refusal() {   # why this host is refused before step 1, or nothing
	local shown="<unset>"
	[ "${VSS_HOST+set}" != set ] || shown="${HOST_MODE//[^A-Za-z0-9._-]/?}"
	if [ "$HOST_MODE" != "$WANT_MODE" ]; then
		echo "VSS_HOST='$shown' is not $WANT_MODE: the Autoware image runs on the $WANT_MODE role and the Orin only (the" \
			"owner, 2026-10-24), and the Orin's days are its own helper's"
	elif on_jetson; then
		echo "VSS_HOST=$WANT_MODE on a host L4T marks as a Jetson: the board's days are its own helper's"
	fi
}

# --- the host check (2.12, layer 3) -------------------------------------------------------------------------------
host_check_before() {   # in the preflight, before the stem's first container: into host-before.txt; a read that fails
	# refuses, since a before that is not known could show no change
	local out rc=0
	out="$(bash "$HC" 2> "$WORK/hostcheck.err")" || rc=$?
	if [ "$rc" != 0 ]; then
		fact host_check before_read b false
		die_step preflight "the host check cannot be read (sdv/aw/hostcheck.sh exited $rc: $(tr '\n' ' ' < "$WORK/hostcheck.err")):" \
			"2.12's before is not known, so nothing starts"
	fi
	printf '%s\n' "$out" > "$WORK/host-before.check"
	{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), before the stem's first container"; printf '%s\n' "$out"; } \
		>> "$STEM/host-before.txt"
	fact host_check before_read b true
	: > "$WORK/state/hc-before"
}
host_check_after() {   # after the sweep, when the preflight read the before: into host-after.txt, then compared.
	# Returns 1 when a setting changed or the after cannot be read, each said in run.log
	local out rc=0 diff drc=0 ln
	[ -e "$WORK/state/hc-before" ] || return 0
	out="$(bash "$HC" 2> "$WORK/hostcheck.err")" || rc=$?
	if [ "$rc" != 0 ]; then
		fact host_check after_read b false
		fact host_check same b false
		{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), after the stem's sweep: cannot be read (exit $rc)"
		  cat "$WORK/hostcheck.err"; } >> "$STEM/host-after.txt"
		say "the host check after the sweep cannot be read (sdv/aw/hostcheck.sh exited $rc): that this stem left the" \
			"host's four settings as they were is not shown"
		return 1
	fi
	printf '%s\n' "$out" > "$WORK/host-after.check"
	fact host_check after_read b true
	diff="$(bash "$HC" --compare "$WORK/host-before.check" "$WORK/host-after.check" 2>&1)" || drc=$?
	{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), after the stem's sweep"; printf '%s\n' "$out"
	  [ -z "$diff" ] || printf '%s\n' "$diff"; } >> "$STEM/host-after.txt"
	fact host_check changed lines "$(printf '%s\n' "$diff" | grep '^changed ' || true)"
	fact host_check compare_exit i "$drc"
	if [ "$drc" = 0 ]; then fact host_check same b true; return 0; fi
	fact host_check same b false
	while IFS= read -r ln; do [ -z "$ln" ] || say "host check: $ln"; done <<< "$diff"
	return 1
}

# --- the steps ----------------------------------------------------------------------------------------------------
step_preflight() {
	local s=preflight groups last f out rc=0 ids mem ifs
	# first, before any effect: the suite boots WP5's ifs-ctl.bin alone and refuses any other image, so a setup for another
	# would spend the session's one run-aw-setup.sh and its pull on a suite that cannot run (the suite's words)
	ifs="$(basename -- "${IFS_BIN:-<unset>}")"
	ifs="${ifs//[^A-Za-z0-9._<>-]/?}"
	fact $s ifs_bin s "$ifs"
	[ "$ifs" = ifs-ctl.bin ] || die_step $s "IFS_BIN is $ifs, not ifs-ctl.bin: the suite's guest is WP5's image, which serves" \
		"kind 2 on :7150 (run-aw-suite.sh refuses any other, so nothing is pulled for it)"
	groups="$(id -nG 2>/dev/null)" || groups=""
	case " $groups " in
		*" docker "*) fact $s docker_group b true ;;
		*) fact $s docker_group b false
		   die_step $s "this login is not in the docker group: run-vss-setup.sh adds it, and it applies from the next login" ;;
	esac
	[ -e "$SETUP_REC/done" ] || die_step $s "rec/vss-setup has no done: run-vss-setup.sh has not finished (wait for it with wait-run)"
	last="$(grep '^status=' "$SETUP_REC/status" 2>/dev/null | tail -n 1 || true)"
	fact $s vss_setup_status_line s "${last:-none}"
	[ "$last" = status=DONE ] || die_step $s "run-vss-setup.sh's last status line is '${last:-none}', not status=DONE"
	out="$(python3 "$TOOL" vss-setup --setup "$SETUP_REC/raw/setup.json" --host-mode "$HOST_MODE" --facts "$WORK/facts/$s" \
		2>&1)" || die_step $s "$out"
	for f in "$AW/aw-entrypoint.sh" "$HC" "$AW/ros-env.json" "$STACK/images.json" "$SCN"; do
		[ -r "$f" ] || die_step $s "the repo tarball lacks ${f#"$REPO/"}: an aw harness needs the tarball of a commit that has it"
	done
	[ -x "$AW/aw-entrypoint.sh" ] || die_step $s "sdv/aw/aw-entrypoint.sh is not executable: --entrypoint runs it by its path"
	out="$(python3 "$TOOL" inputs --aw-in "$AW_IN" --inputs-env "$W/inputs.env" --repo-tar "$W/repo.tar" \
		--facts "$WORK/facts/$s" --txt "$OUT/inputs.txt" 2>&1)" || die_step $s "the aw inputs: $out"
	out="$(python3 "$TOOL" scan --scan "$AW_IN/aw-scan.json" --images "$STACK/images.json" --facts "$WORK/facts/$s" \
		--txt "$OUT/inputs.txt" 2>&1)" || die_step $s "$out"
	out="$(python3 "$TOOL" dds --env "$AW/ros-env.json" --out "$WORK/dds/cyclonedds.xml" 2>&1)" || die_step $s "$out"
	ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
	[ "$rc" = 0 ] || die_step $s "the containers labelled $LABEL cannot be listed (docker ps exit $rc)"
	[ -z "$ids" ] || die_step $s "a container labelled $LABEL is still there (an earlier aw run's: $(printf '%s ' $ids)): this" \
		"harness's names would collide"
	if mem="$(python3 "$TOOL" meminfo --file "$MEMINFO")"; then fact $s mem_available_kb i "$mem"
	else fact $s mem_available_kb s unreadable; fi
	host_check_before
	say "preflight: run-vss-setup.sh DONE as $HOST_MODE, the aw inputs checked, the scan of the digest to pull, the host check read"
}

step_stage() {
	local s=stage out
	out="$(python3 "$TOOL" stage-map --tar "$AW_IN/aw-map.tar" --scenario "$SCN" --dest "$MAP_DEST" --facts "$WORK/facts/$s" \
		2>&1)" || die_step $s "the map: $out"
	say "stage: the scenario's map staged in VSS_HOME/aw/map, each file of the scenario's sha256"
}

step_pull() {
	local s=pull ref rc=0 t0 out ds dt
	ref="$(python3 "$TOOL" ref --images "$STACK/images.json" 2>&1)" || die_step $s "$ref"
	fact $s ref s "$ref"
	t0="$(vss_now)"
	out="$(docker pull "$ref" 2>&1 < /dev/null)" || rc=$?
	fact $s operational_s/pull i "$(( $(vss_now) - t0 ))"
	fact $s pull_exit i "$rc"
	fact $s pull_tail lines "$(printf '%s\n' "$out" | tail -n 3)"
	[ "$rc" = 0 ] || die_step $s "docker pull $ref exited $rc"
	rc=0; out="$(docker image inspect "$ref" 2> "$WORK/inspect.err")" || rc=$?
	[ "$rc" = 0 ] || die_step $s "docker image inspect $ref exited $rc"
	printf '%s\n' "$out" | python3 "$TOOL" inspect --ref "$ref" --facts "$WORK/facts/$s" > "$WORK/inspect.why" 2>&1 \
		|| die_step $s "$(cat "$WORK/inspect.why")"
	ds="$(docker info -f '{{json .DriverStatus}}' 2>&1)" || die_step $s "docker info (its DriverStatus) failed"
	dt="$(printf '%s\n' "$ds" | python3 "$VSS_TOOL" driver-type)"
	fact $s store s "${dt:-none}"
	say "pull: $ref pulled by its digest and read back (image store ${dt:-none})"
}

step_smoke() {
	local s=smoke ref env rc=0 gid
	ref="$(python3 "$TOOL" ref --images "$STACK/images.json" 2>&1)" || die_step $s "$ref"
	env="$(python3 "$TOOL" dds --env "$AW/ros-env.json" --out "$WORK/dds/cyclonedds.xml" 2>&1)" || die_step $s "$env"
	gid="$(id -g)"
	install -d -m 0775 "$WORK/smoke-ros-log"
	: > "$WORK/state/containers-started"
	fact $s probe lines "ros2 --help (the image's own start-up, through the project entrypoint, with --network none)"
	docker run --rm --name aw-smoke --label "$LABEL=$STEM_NAME" --network none --user aw --group-add "$gid" \
		--cap-drop ALL --security-opt no-new-privileges --entrypoint /sdv-aw/aw-entrypoint.sh \
		-v "$AW:/sdv-aw:ro" -v "$WORK/dds:/sdv-dds:ro" -e "ROS_DOMAIN_ID=${env%% *}" -e "RMW_IMPLEMENTATION=${env#* }" \
		-e CYCLONEDDS_URI=file:///sdv-dds/cyclonedds.xml -e ROS_LOG_DIR=/sdv-ros-log -v "$WORK/smoke-ros-log:/sdv-ros-log" \
		"$ref" ros2 --help > "$WORK/smoke.out" 2> "$WORK/smoke.err" < /dev/null || rc=$?
	fact $s exit i "$rc"
	fact $s sigill b "$([ "$rc" = 132 ] && echo true || echo false)"
	fact $s stderr lines "$(tail -n "$STDERR_LINES" "$WORK/smoke.err")"
	fact $s stdout_lines i "$(grep -c '' "$WORK/smoke.out" || true)"
	if [ "$rc" = 0 ]; then
		fact $s pass b true
		say "smoke: ros2 --help exited 0 in the image on this host, under 2.12"
	else
		fact $s pass b false
		die_step $s "ros2 --help exited $rc in the image under the project entrypoint$([ "$rc" != 132 ] || echo " (SIGILL)"): the" \
			"image does not start on this host (its stderr is in setup.json)"
	fi
}

step_budget() {
	local s=budget left mem
	if mem="$(python3 "$TOOL" meminfo --file "$MEMINFO")"; then fact $s mem_available_kb i "$mem"
	else fact $s mem_available_kb s unreadable; fi
	left=$((VSS_STOP_AT - $(vss_now)))
	fact $s operational_s/left_to_stop_at i "$left"
	if [ "$left" -lt "$RULE_LEFT_S" ]; then
		fact $s budget_short b true
		say "D7's rule: under 30 minutes are left before stop_at after the pull: budget_short, and the suite refuses this setup"
	else
		fact $s budget_short b false
	fi
}

step_close() {
	local ref smoke short
	ref="$(cat "$WORK/facts/pull/ref.s" 2>/dev/null || echo none)"
	smoke="$(cat "$WORK/facts/smoke/pass.b" 2>/dev/null || echo none)"
	short="$(cat "$WORK/facts/budget/budget_short.b" 2>/dev/null || echo none)"
	say "close: image $ref; smoke passed $smoke; budget_short $short"
	if [ "$short" = false ]; then say "run-aw-suite.sh takes this setup"; else say "run-aw-suite.sh will refuse this setup"; fi
}

# --- the parent: check points, caps, the stops -----------------------------------------------------------------------
stop_verdict() {   # REASON...: facts.stop.verified, false with the reasons when the sweep could not show its removals done
	local j
	if [ "$#" = 0 ]; then fact stop verified b true; return 0; fi
	fact stop verified b false
	fact stop unverified lines "$(printf '%s\n' "$@")"
	j="$(printf '%s; ' "$@")"
	say "the stop is unverified: ${j%; }"
}
sweep() {   # the idempotent removals of every stop once the preflight has passed, DONE included, under facts.stop
	local unv=() ids rc=0 rc2=0 n left
	if [ ! -e "$WORK/state/began" ]; then stop_verdict; return 0; fi
	timeout 60 docker rm -f aw-smoke >/dev/null 2>&1 || true
	ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
	fact stop containers_list_exit i "$rc"
	if [ "$rc" != 0 ]; then
		timeout 120 docker rm -f "${AW_CONTAINERS[@]}" >/dev/null 2>&1 || rc2=$?
		fact stop containers_fallback_rm_exit i "$rc2"
		unv+=("the containers labelled $LABEL could not be listed (docker ps exit $rc): the aw names were removed unseen")
	else
		# shellcheck disable=SC2086  # the IDs are words
		set -- $ids
		n=$#
		fact stop containers_found i "$n"
		left=0
		if [ "$n" -gt 0 ]; then
			timeout 120 docker rm -f "$@" >/dev/null 2>&1 || true
			rc=0; ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
			if [ "$rc" != 0 ]; then
				unv+=("the containers labelled $LABEL could not be listed after the removals (docker ps exit $rc)")
			else
				left="$(printf '%s\n' "$ids" | grep -c . || true)"
			fi
		fi
		fact stop containers_left i "$left"
		[ "$left" = 0 ] || unv+=("$left container(s) labelled $LABEL still listed after the removals")
	fi
	stop_verdict ${unv[@]+"${unv[@]}"}
}
clean_stop() {   # a stop other than DONE: sync, then the sweep
	say "a clean stop: sync, the containers labelled $LABEL removed"
	timeout 120 sync || true
	sweep
}

write_record() {   # STATUS STATUS-LINE AT REASON
	python3 "$TOOL" record --work "$WORK" --out "$OUT/setup.json" --status "$1" --status-line "$2" --at "$3" \
		--reason "$4" --steps "${STEPS[*]}" --host-mode "${HOST_MODE:-unset}"
}

finish() {   # STATUS [AT [REASON]]: the sweep, the host check, the record, then the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line i notrun=""
	trap - EXIT
	set +e
	if [ "$st" = DONE ]; then sweep; else clean_stop; fi
	case "$st" in
		DONE) line="status=DONE" ;;
		TIMEOUT) line="status=TIMEOUT at=$at reason=$why" ;;
		*) line="status=FAILED at=$at" ;;
	esac
	if ! host_check_after; then
		fact host_check outcome_before_host_check s "$line"
		st=FAILED; at=host-check; line="status=FAILED at=host-check"
		why="2.12's host check after the sweep: a setting changed, or it could not be read"
	fi
	if ! write_record "$st" "$line" "$at" "$why"; then
		say "setup.json could not be written"
		if [ "$st" = DONE ]; then st=FAILED; at=close; line="status=FAILED at=close"; fi
	fi
	if [ "$st" != DONE ]; then
		for i in "${STEPS[@]}"; do
			awk -F'\t' -v s="$i" '$2 == s { f = 1 } END { exit !f }' "$WORK/steps.tsv" 2>/dev/null || notrun="$notrun $i"
		done
		say "not run:${notrun:- none}"
		[ "$st" != FAILED ] || say "FAILED at $at: $why"
	fi
	# shellcheck disable=SC2086  # the status line's words; vss_status writes the status= itself
	vss_status ${line#status=}
	[ "$st" != FAILED ] || exit 1
	exit 0
}

on_exit() {   # the parent ended without a status line: a FAILED record all the same
	local rc=$?
	finish FAILED "${CUR:-preflight}" "the harness stopped unexpectedly (exit $rc)"
}

run_step() {   # N NAME: the check point, then the step under its cap in the documented call form
	local n="$1" name="$2" s0 t0 rc outcome=ok
	CUR="$name"
	if vss_past_stop; then finish TIMEOUT "$name" deadline; fi
	[ "$name" = preflight ] || : > "$WORK/state/began"
	s0="$(date -u +%FT%TZ)"; t0="$(vss_now)"
	say "step $n/$NSTEPS $name: start"
	rc=0; vss_capped bash "$SELF" _step "$name" || rc=$?
	if vss_cap_fired "$rc"; then outcome=step-timeout; elif [ "$rc" != 0 ]; then outcome=failed; fi
	printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$n" "$name" "$s0" "$(date -u +%FT%TZ)" "$(( $(vss_now) - t0 ))" "$rc" "$outcome" \
		>> "$WORK/steps.tsv"
	say "step $n/$NSTEPS $name: end ($outcome, exit $rc)"
	case "$outcome" in
		step-timeout) finish TIMEOUT "$name" step-timeout ;;
		failed) finish FAILED "$name" "$(cat "$WORK/facts/$name/failure.s" 2>/dev/null || echo "exit $rc")" ;;
	esac
}

main() {
	local i why
	CUR=preflight
	rm -rf "$WORK"
	mkdir -p "$WORK/facts" "$WORK/state" "$OUT"
	: > "$WORK/steps.tsv"
	trap on_exit EXIT
	say "run-aw-setup.sh: $NSTEPS steps; a functional session; operational steps recorded"
	why="$(host_refusal)"
	[ -z "$why" ] || finish FAILED preflight "$why"
	if ! vss_deadline_load; then finish FAILED preflight "no readable deadline file (lib-vss-deadline.sh)"; fi
	fact preflight deadline_readable b true
	for i in "${!STEPS[@]}"; do run_step "$((i + 1))" "${STEPS[$i]}"; done
	finish DONE
}

if [ "${1:-}" = _step ]; then   # one step, as the parent runs it under its cap
	vss_deadline_load || exit 1
	case "${2:-}" in
		preflight) step_preflight ;;
		stage) step_stage ;;
		pull) step_pull ;;
		smoke) step_smoke ;;
		budget) step_budget ;;
		close) step_close ;;
		*) echo "run-aw-setup.sh: no step '${2:-}'" >&2; exit 2 ;;
	esac
	exit 0
fi
main
