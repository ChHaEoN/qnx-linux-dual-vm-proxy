#!/usr/bin/env bash
# run-aw-suite.sh -- the Autoware session's suite on a bare-metal AWS instance: the QNX guest booted once from the session's
# ifs-ctl.bin and smoked on :7100, then each unit of the plan: Autoware's planning simulator (aw-sim) driven through the
# scenario (aw-scenario), its Control judged by the guest's ctl monitor on :7150 through the claim node (aw-claim-node).
# SDV Phase 8 WP6 9.2. The record describes operational steps; it makes no benchmark claim.
#
# HOW IT RUNS. Only as remote-ladder.sh's harness phase starts it, detached, in an aw session (scripts/aws/README.md, "An
# aw session"): LADDER_ENV="HARNESS=run-aw-suite.sh IMAGE=ifs-ctl.bin PLAN=a1|a2|b1|b2|s VSS_HOST=c7g-metal", once per
# session, after run-aw-setup.sh ended status=DONE, from a new login. The detached runner runs it from $R =
# $W/repo/orin-native/gpu-concurrency with stdout and stderr in rec/aw-suite/run.log and SIGPIPE, SIGHUP, SIGINT and
# SIGQUIT ignored (a unit under its cap starts with only SIGPIPE of them ignored: remote-ladder.sh, SIGNALS), then reads
# its last status line. Its environment:
#   W         the session's directory (~/a1): repo/ (the vss tarball, which carries sdv/aw and sdv/ctl), rec/aw-setup
#   IFS_BIN   the session's METAL_IFS, ifs-ctl.bin (WP5's image: kind 2 on :7150); DISK the guest disk
#   OUT       rec/aw-suite/raw, the record; PLAN a1, a2, b1, b2 or s; STATUS rec/aw-suite/status
#   VSS_HOME  $W/sdv: gen/vss_ctl.py (the generation run-vss-setup.sh staged), aw/map/<map>/ (run-aw-setup.sh's);
#             aw-suite-work/, this harness's own working files (never captured): its facts, 2.7's DDS file, the guest's
#             console, and per unit units/<NN>-<unit>/ with its ROS log directory (ros-log/), the claim node's and the
#             driver's output directories and, for the recording unit, its bag (bag/)
#   VSS_HOST  the host's role, c7g-metal and nothing else (run-aw-setup.sh, THE HOST)
# IMG_S, IMG_B, VPROBE, CSTATE, VSS_IN and AW_IN come with the phase's environment and are not used here. For the tests,
# QNX_METAL_DEADLINE_FILE overrides the deadline file, QNX_MEMINFO_FILE /proc/meminfo, and QNX_L4T_RELEASE_FILE and
# QNX_DT_COMPATIBLE_FILE L4T's release file and the device tree's compatible; for the PC rehearsal QNX_GUEST_HOST the
# guest's address (the native ctl monitor on loopback in its place), which suite.json records as guest_host.
#
# PREFLIGHT, in this order; a refusal is status=FAILED at=preflight, exit 1, and nothing has started:
#   the host (VSS_HOST c7g-metal, not a Jetson) and the deadline file readable; PLAN one of the five; `id -nG` includes
#   docker (a new login); rec/aw-setup has done, its status file's last status= line is exactly status=DONE, and its
#   raw/setup.json says DONE with budget_short false (D7's rule) and host_mode VSS_HOST's, and names the image it pulled
#   by its digest; no QEMU running (one found is refused, never stopped); IFS_BIN is ifs-ctl.bin and readable, DISK and
#   the launch script readable; the tarball's sdv/aw (the project entrypoint, executable; hostcheck.sh; ros-env.json),
#   sdv/ctl's claim node, scenario driver and exporter, and the scenario (SCENARIO); VSS_HOME/gen/vss_ctl.py's DIGEST and
#   COMPILED_PROFILE_IDS, which hold profiles 1 and 2; the staged map, exactly the scenario's files of its sha256; the
#   image in the store (`docker image inspect`, its RepoDigests holding the reference); 2.7's DDS file written; no
#   container labelled sdv.aw.run, and the label listed; then the host check before (run-aw-setup.sh, 2.12 ON A METAL
#   HOST: into the stem's host-before.txt).
# Then the guest, unit 00-guest: the check point, the boot by launch-qnx-kvm-bridged.sh (its exit 0 is the :7100 accept)
# under its cap; :7150's readiness (a connect-and-close with no bytes, retried within a bound), the console's `ctl rules:`
# line (its catalog vss_ctl.py's DIGEST, its profiles holding 1 and 2: aw_suite.py rules) and the :7100 smoke after
# Docker (latency_probe.py; its exit status and its bad and rej counts kept, nothing else), under one cap. A guest that
# does not boot, a :7150 that does not accept, a `ctl rules:` line that is missing or names another contract, or a smoke
# that fails ends the suite status=FAILED at=preflight: no unit could be judged. One guest serves every unit; each unit
# keeps the part of its console written while it ran.
#
# THE UNITS (aw_suite.py, THE PLANS): a1 01-psim; a2 01-honest 02-inject; b1 01-honest (recorded) 02-inject; b2 01-kill
# 02-inject 03-demo; s 01-sizing. Before each, the deadline's check point (now >= stop_at stops here); each runs under its
# cap (stop_at + 10 minutes - now, `timeout --kill-after=30s`) as a child of this script in lib-vss-deadline.sh's call
# form, rc=0; vss_capped CMD... || rc=$?, then vss_cap_fired "$rc". A unit, in this order:
#   aw-sim       `docker run -d` of the planning simulator: `ros2 launch autoware_launch planning_simulator.launch.xml`
#                with the staged map read-only, sample_vehicle, sample_sensor_kit and rviz:=false; then `docker exec aw-sim
#                ... ros2 service list` every SIM_POLL_S until it lists every service the driver calls first
#                (SIM_SERVICES), given up once SIM_UP_S have passed since the `docker run` (a bound on the wait's time,
#                not a count of polls: a poll begun before it runs to its own bound of 60 s). A simulator that does not
#                list them in time, or whose container stops, ends the unit (sim-not-up), recorded; one whose `docker run`
#                fails, sim-failed
#   claim node   (every unit but a1's) `docker run -d` of ctl_claim_node.py --host the guest --port 7150 --contract the
#                generation's vss_ctl.py --out its directory, with the unit's own arguments (b2's demo window, the
#                injections), BEFORE the driver sets the route: no Control flows before one (W4 G2)
#   bag          (b1's 01-honest) `docker exec -d aw-sim ... ros2 bag record` of ctl_export.py's six topics into the unit's
#                bag/ (outside the record)
#   driver       `docker run` of aw_scenario.py --scenario the tarball's --map-dir the staged map --out its directory,
#                with --require-claim-node when a claim node runs; its exit status recorded (0 arrived, 3 a step's
#                timeout, 2 a refusal: each a result). b2's 01-kill runs it in the background, waits until its log says
#                the engage step is done, then kills the controller (W4 G4): controller_node_exe is a composable node in
#                a component container it shares with the gate, so no process bears its name and a process kill would
#                end the gate too; it is unloaded from its container (`ros2 component unload` inside aw-sim), the
#                container and its id read with `ros2 component list` once the simulator is up, before the route. A
#                list without it is recorded (kill_problem), and the drive goes on unkilled
#   after        (the bag) the recorder stopped with SIGINT inside aw-sim, its metadata waited for, then ctl_export.py
#                inside aw-sim into the unit's export.jsonl; the claim node stopped (its SIGTERM ends the spin, and it
#                drains and writes its summary), its log kept, its exit status read; aw-sim stopped
#   sampler      (s's 01-sizing) MemAvailable and `docker stats --no-stream` every SAMPLE_S from the unit's start to its
#                end, by this harness's own processes: never a new login
# Every container: the names of 2.1, labelled sdv.aw.run=aw-suite, under 2.12 (run-aw-setup.sh, 2.12 ON A METAL HOST:
# --entrypoint the tarball's sdv/aw/aw-entrypoint.sh read-only, --user aw, --cap-drop ALL, --security-opt
# no-new-privileges, never --privileged, --cap-add or a /proc/sys or /sys mount; CYCLONEDDS_URI 2.7's file, never the
# image's own cyclonedds.xml), --network host (2.7's single-host form), ROS_LOG_DIR the unit's ros-log/, never captured;
# docker exec runs as the container's own user with its capabilities. After each unit, whatever its end, its three
# containers are removed by name and the label is listed (swept, containers_left), then its records are copied into
# OUT/<NN>-<unit> and its unit.json written. When the unit's own end did not read the claim node's log after the node had
# started (its cap fired, or it failed), the sweep reads it first, as it stands: the node not stopped, so its drained
# summary may be missing (claim_log_at_sweep true; false when it cannot be read).
#
# THE STATUS LINE, the last one in STATUS, through vss_status:
#   status=DONE                                   every unit ran (a drive that timed out, a simulator that did not come
#                                                 up, a claim node that refused: results, recorded); suite.json first
#   status=TIMEOUT at=<unit> reason=deadline      a check point found now >= stop_at; <unit> and the rest did not run
#   status=TIMEOUT at=<unit> reason=step-timeout  <unit>'s cap fired (the guest's boot or checks too, as 00-guest)
#   status=FAILED at=preflight                    the preflight refused, the guest could not judge the plan, or the host
#   status=FAILED at=host-check                   the host check after the sweep found a setting changed, or could not
#                                                 be read (suite.json's host_check.outcome_before_host_check keeps what the
#                                                 suite would have ended with)
#   status=FAILED at=record                       every unit ran, but suite.json could not be written
#   status=FAILED at=<unit>                       the harness ended without a status line, through its EXIT trap (reason
#                                                 "the harness stopped unexpectedly", at the unit it was in)
# Every FAILED exits 1, a TIMEOUT 0. Every stop sweeps before its record, DONE included: QEMU stopped if this harness
# launched it (sudo -n pkill, waited for, KILL if it lingers); once a unit began, the unit's names removed and every
# container labelled sdv.aw.run listed and removed, or, when they cannot be listed, the aw names (AW_CONTAINERS) removed
# unseen. A QEMU that outlives its KILL, a list that fails or a container still listed records the stop unverified
# (stop.verified false, with why) and says so in run.log; the status line is not changed by it. Every stop but DONE syncs
# first. Then the host check after, suite.json written whole, the units not run in run.log, and the status line.
#
# THE RECORD, in OUT (each name on capture.py's whitelist under aw-suite/raw, 2.11): suite.json (the preflight's facts,
# the guest's, each unit with its state and facts, the units not run, the host check, the sweep, the status) and per unit
# <NN>-<unit>/: replies.jsonl (the claim node's reply log), claim-node.log, scenario.jsonl (the driver's), guest-console.log
# (the console's part the unit saw), export.jsonl (the recorded unit only) and unit.json (its facts, the replies counted
# by reason, each step's outcome, the sizing samples). Never ros-log/, a bag directory or ~/.ros. Every string in
# suite.json and unit.json is one line. Docker runs through the docker group; only pkill runs under sudo -n.
#
# DESIGN VALUES (not measured): the readiness's attempts and bound (30, 3 s); the wait for the console's `ctl rules:` line
# (RULES_WAIT_S, 5 s); the simulator's wait (SIM_UP_S 300 s from its `docker run`, polled every SIM_POLL_S 5 s: the
# planning simulator needs time for startup and discovery); the controller kill's wait for the engage step (ENGAGE_WAIT_S
# 210 s: the scenario's localize, route and engage timeouts and 30 s); the bag's close (BAG_CLOSE_S 30 s); the stops
# (STOP_CLAIM_S 15 s: the claim node drains for at most 1 s; STOP_SIM_S 30 s); the sampler's spacing (SAMPLE_S 5 s); the
# guest's stop (10 s, then KILL and 10 s more).
#
# WHAT IT DOES NOT SHOW: any timing (the operational_s values and the sizing samples are this session's own, with Docker
# up); that the monitor is in any control loop (it judges the gate's output after the gate sent it); that Autoware's own
# faults would be caught (the injections come after the gate); that honest traffic passes rules 13, 14 and 16 (it never
# sets their flags, W4 G9); that a host other than this one would behave alike; nor any isolation or certification. The
# startup that boots the guest is ours, not a QNX-supported configuration, and no timing claim attaches to the boot.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
: "${W:?run-aw-suite.sh runs from the harness phase (W)}" "${IFS_BIN:?no IFS_BIN}" "${DISK:?no DISK}" "${OUT:?no OUT}"
: "${VSS_HOME:?no VSS_HOME}" "${STATUS:?no STATUS}"

TOOL="$HERE/aw_suite.py"
SETUP_TOOL="$HERE/aw_setup.py"
VSS_TOOL="$HERE/vss_setup.py"
LAUNCH="$HERE/launch-qnx-kvm-bridged.sh"
REPO="$W/repo"
STACK="$REPO/sdv/stack"
AW="$REPO/sdv/aw"
HC="$AW/hostcheck.sh"
CTL="$REPO/sdv/ctl"
SCENARIO=sample-lanelet-102
SCN="$CTL/scenarios/$SCENARIO.json"
SETUP_REC="$W/rec/aw-setup"
WORK="$VSS_HOME/aw-suite-work"
MAPS="$VSS_HOME/aw/map"
CONTRACT="$VSS_HOME/gen/vss_ctl.py"
STEM="$(dirname "$OUT")"
STEM_NAME=aw-suite
CONSOLE="$WORK/guest/console.log"
GUEST="${QNX_GUEST_HOST:-192.168.100.10}"
CLAIM_PORT=7150
READY_TRIES=30; READY_BOUND_S=3
RULES_WAIT_S=5
SIM_UP_S=300; SIM_POLL_S=5
ENGAGE_WAIT_S=210
BAG_CLOSE_S=30
STOP_CLAIM_S=15; STOP_SIM_S=30
SAMPLE_S=5
STOP_WAIT_S=10
LABEL=sdv.aw.run
# every container an aw harness starts (spec-2 2.1's four and run-aw-setup.sh's smoke): the sweep's names when the label
# cannot be listed; a unit's own are its first three
AW_CONTAINERS=(aw-sim aw-claim-node aw-scenario ros-vss-feeder aw-smoke)
UNIT_CONTAINERS=(aw-sim aw-claim-node aw-scenario)
# the services the driver calls first, which the simulator must list before the claim node and the driver start
SIM_SERVICES=(/api/localization/initialize /api/routing/set_route_points /api/operation_mode/change_to_autonomous)
# the controller (W4 G4: the gate's one source of Control): a composable node, /control/trajectory_follower/<this>, in the
# component container /control/control_container beside the gate. Each kill unit reads its container and id with
# `ros2 component list`; neither is fixed here.
KILL_NODE=controller_node_exe
# ctl_export.py's TOPICS, in its order (a test holds the two equal): what the recording unit's bag holds
BAG_TOPICS=(/control/command/control_cmd /localization/kinematic_state /vehicle/status/velocity_status
	/vehicle/status/steering_status /vehicle/status/gear_status /localization/acceleration)
HOST_MODE="${VSS_HOST-}"
WANT_MODE=c7g-metal
MEMINFO="${QNX_MEMINFO_FILE:-/proc/meminfo}"
L4T_RELEASE="${QNX_L4T_RELEASE_FILE:-/etc/nv_tegra_release}"
DT_COMPATIBLE="${QNX_DT_COMPATIBLE_FILE:-/proc/device-tree/compatible}"
REF=""; DIGEST=""; DDS_ENV=""; MAP_NAME=""

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

fact() {   # UNIT KEY TYPE VALUE: one fact (vss_setup.py, FACTS); a KEY with "/" is a nested object
	local f="$WORK/facts/$1/$2.$3"
	mkdir -p "$(dirname "$f")"
	printf '%s' "$4" > "$f"
}
state_of() { cat "$WORK/facts/$1/state.s" 2>/dev/null || true; }
console_size() { stat -c %s "$CONSOLE" 2>/dev/null || echo 0; }

# --- the host (run-aw-setup.sh, THE HOST) ------------------------------------------------------------------------------
on_jetson() {   # whether L4T's release file or an NVIDIA device tree marks this host as a Jetson: builtins only
	local c=""
	[ ! -e "$L4T_RELEASE" ] || return 0
	[ -r "$DT_COMPATIBLE" ] || return 1
	IFS= read -r -d '' c < "$DT_COMPATIBLE" || true
	case "$c" in nvidia,*) return 0 ;; esac
	return 1
}
host_refusal() {
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
host_check_before() {   # the preflight's last item, before the stem's first container: into host-before.txt
	local out rc=0
	out="$(bash "$HC" 2> "$WORK/hostcheck.err")" || rc=$?
	if [ "$rc" != 0 ]; then
		fact host_check before_read b false
		refuse "the host check cannot be read (sdv/aw/hostcheck.sh exited $rc: $(tr '\n' ' ' < "$WORK/hostcheck.err")):" \
			"2.12's before is not known, so nothing starts"
	fi
	printf '%s\n' "$out" > "$WORK/host-before.check"
	{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), before the stem's first container"; printf '%s\n' "$out"; } \
		>> "$STEM/host-before.txt"
	fact host_check before_read b true
	: > "$WORK/state/hc-before"
}
host_check_after() {   # after the sweep: into host-after.txt, then compared; 1 when a setting changed or it cannot be read
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

# --- the guest -------------------------------------------------------------------------------------------------------
guest_runs() { pgrep -x qemu-system-aar >/dev/null 2>&1; }
stop_guest() {   # UNIT: QEMU stopped as the stop phase does, KILL if it lingers, waited until gone
	local u="$1" i
	if ! guest_runs; then fact "$u" qemu_stopped b true; return 0; fi
	timeout 30 sudo -n pkill -x qemu-system-aar >/dev/null 2>&1 || true
	for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	if guest_runs; then
		timeout 30 sudo -n pkill -KILL -x qemu-system-aar >/dev/null 2>&1 || true
		for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	fi
	if guest_runs; then fact "$u" qemu_stopped b false; say "QEMU still runs after a KILL"; return 0; fi
	fact "$u" qemu_stopped b true
}

guest_checks() {   # the child under its cap: :7150's readiness, the `ctl rules:` line, the :7100 smoke (facts into guest)
	local s=guest i n=0 ready=no out rc=0 parsed res bad rej pass=no
	for i in $(seq 1 "$READY_TRIES"); do
		n="$i"
		if timeout "$READY_BOUND_S" bash -c "exec 3<>/dev/tcp/$GUEST/$CLAIM_PORT && exec 3>&-" 2>/dev/null; then ready=yes; break; fi
		sleep 1
	done
	fact $s ready_7150 b "$([ "$ready" = yes ] && echo true || echo false)"
	fact $s ready_7150_attempts i "$n"
	[ "$ready" = yes ] || return 0
	for i in $(seq 1 $((RULES_WAIT_S * 2))); do
		rc=0; python3 "$TOOL" rules --console "$CONSOLE" --digest "$AWU_DIGEST" --facts "$WORK/facts/$s/ctl_rules" \
			> "$WORK/rules.out" 2>&1 || rc=$?
		[ "$rc" != 0 ] || break
		grep -q "no \`ctl rules:\` line" "$WORK/rules.out" || break
		sleep 0.5
	done
	fact $s ctl_rules_exit i "$rc"
	fact $s ctl_rules_problem s "$([ "$rc" = 0 ] || tail -n 1 "$WORK/rules.out")"   # its refusal; empty on a pass
	rc=0; out="$(python3 "$HERE/latency_probe.py" --host "$GUEST" --port 7100 --n 20 --warmup 0 2>&1)" || rc=$?
	parsed="$(printf '%s\n' "$out" | python3 "$VSS_TOOL" smoke)"
	out=""
	res="$(printf '%s\n' "$parsed" | sed -n 's/^result_line //p')"
	bad="$(printf '%s\n' "$parsed" | sed -n 's/^bad //p')"
	rej="$(printf '%s\n' "$parsed" | sed -n 's/^rej //p')"
	if [ "$rc" = 0 ] && [ "$res" = yes ] && [ "$bad" = 0 ] && [ "$rej" = 0 ]; then pass=yes; fi
	fact $s smoke_7100/exit i "$rc"
	fact $s smoke_7100/result_line b "$([ "$res" = yes ] && echo true || echo false)"
	case "$bad" in ''|*[!0-9]*) fact $s smoke_7100/bad s "${bad:-none}" ;; *) fact $s smoke_7100/bad i "$bad" ;; esac
	case "$rej" in ''|*[!0-9]*) fact $s smoke_7100/rej s "${rej:-none}" ;; *) fact $s smoke_7100/rej i "$rej" ;; esac
	fact $s smoke_7100/pass b "$([ "$pass" = yes ] && echo true || echo false)"
}

guest_unit() {   # 00-guest: the boot under its cap, then guest_checks under its cap; a guest that cannot judge refuses
	local s=guest rc=0 t0 why=""
	CUR=00-guest
	if vss_past_stop; then finish TIMEOUT 00-guest deadline; fi
	say "unit 00-guest: start"
	mkdir -p "$WORK/guest"
	: > "$WORK/state/launched"
	t0="$(vss_now)"
	vss_capped env IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$CONSOLE" bash "$LAUNCH" > "$WORK/guest/launch.out" 2>&1 < /dev/null \
		|| rc=$?
	fact $s operational_s/boot i "$(( $(vss_now) - t0 ))"
	fact $s launch_exit i "$rc"
	if vss_cap_fired "$rc"; then fact $s state s step-timeout; collect_guest; finish TIMEOUT 00-guest step-timeout; fi
	if [ "$rc" != 0 ]; then
		fact $s booted b false
		why="the guest did not boot (the launch script exited $rc): the suite has no guest to judge its units"
	else
		fact $s booted b true
		rc=0; vss_capped env AWU_DIGEST="$DIGEST" bash "$SELF" _guest < /dev/null || rc=$?
		if vss_cap_fired "$rc"; then fact $s state s step-timeout; collect_guest; finish TIMEOUT 00-guest step-timeout; fi
		if [ "$(cat "$WORK/facts/$s/ready_7150.b" 2>/dev/null)" != true ]; then
			why=":7150 did not accept within the bound ($READY_TRIES attempts of ${READY_BOUND_S} s): the guest's ctl monitor"
			why="$why is not serving"
		elif [ "$(cat "$WORK/facts/$s/ctl_rules_exit.i" 2>/dev/null)" != 0 ]; then
			why="$(cat "$WORK/facts/$s/ctl_rules_problem.s" 2>/dev/null)"
		elif [ "$(cat "$WORK/facts/$s/smoke_7100/pass.b" 2>/dev/null)" != true ]; then
			why=":7100's smoke after Docker failed (exit $(cat "$WORK/facts/$s/smoke_7100/exit.i" 2>/dev/null), bad"
			why="$why $(cat "$WORK/facts/$s/smoke_7100/bad."* 2>/dev/null), rej $(cat "$WORK/facts/$s/smoke_7100/rej."* 2>/dev/null))"
		fi
	fi
	if [ -n "$why" ]; then fact $s state s refused; collect_guest; refuse "$why"; fi
	fact $s state s ran
	collect_guest
	say "unit 00-guest: end (booted; :7150 ready; ctl rules $DIGEST; :7100 smoke passed)"
}

collect_guest() {   # 00-guest's record: the console as the boot and the checks left it, and unit.json
	mkdir -p "$OUT/00-guest"
	python3 "$TOOL" slice --console "$CONSOLE" --from 0 --to "$(console_size)" --out "$OUT/00-guest/guest-console.log" || true
	python3 "$TOOL" unit-json --work "$WORK" --name guest --unit-dir "$OUT/00-guest" --plan "${PLAN:-}" \
		--out "$OUT/00-guest/unit.json" || say "unit.json for 00-guest could not be written"
}

# --- a unit (the child, under its cap) -----------------------------------------------------------------------------
sampler() {   # FILE: MemAvailable and docker stats every SAMPLE_S, by this harness's own processes (never a login)
	local t0 m
	t0="$(vss_now)"
	while :; do
		m="$(python3 "$SETUP_TOOL" meminfo --file "$MEMINFO" 2>/dev/null)" || m=unreadable
		echo "== t $(( $(vss_now) - t0 )) mem $m"
		timeout 30 docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null || echo "== stats failed"
		sleep "$SAMPLE_S"
	done >> "$1"
}
sim_lists_services() {   # TEXT: whether `ros2 service list` lists every one of SIM_SERVICES
	local s
	for s in "${SIM_SERVICES[@]}"; do grep -qxF "$s" <<< "$1" || return 1; done
}

unit_child() {   # NN NAME: one unit of plan.tsv; facts into facts/NAME; every container it starts is the parent's to sweep
	local nn="$1" name="$2" row claim kill rec sample args U rc out i up=no n=0 end spid="" dpid killed=no target=""
	local awc simx=() drv
	row="$(awk -F'\t' -v n="$name" '$2 == n' "$WORK/plan.tsv")"
	IFS=$'\t' read -r _ _ claim kill rec sample args <<< "$row"
	U="$WORK/units/$name"
	install -d -m 0775 "$U" "$U/ros-log" "$U/claim" "$U/scn"
	fact "$name" nn s "$nn"
	fact "$name" claim_node b "$([ "$claim" = 1 ] && echo true || echo false)"
	# shellcheck disable=SC2086  # the unit's claim arguments are words (aw_suite.py, THE PLANS)
	fact "$name" claim_args lines "$([ -z "$args" ] || printf '%s\n' $args)"
	fact "$name" kill b "$([ "$kill" = 1 ] && echo true || echo false)"
	fact "$name" record b "$([ "$rec" = 1 ] && echo true || echo false)"
	fact "$name" sample b "$([ "$sample" = 1 ] && echo true || echo false)"
	awc=(--label "$LABEL=$STEM_NAME" --network host --user aw --group-add "$AWU_GID" --cap-drop ALL
		--security-opt no-new-privileges --entrypoint /sdv-aw/aw-entrypoint.sh -v "$AW:/sdv-aw:ro" -v "$WORK/dds:/sdv-dds:ro"
		-e "ROS_DOMAIN_ID=$AWU_DOMAIN" -e "RMW_IMPLEMENTATION=$AWU_RMW" -e CYCLONEDDS_URI=file:///sdv-dds/cyclonedds.xml
		-e ROS_LOG_DIR=/sdv-ros-log -v "$U/ros-log:/sdv-ros-log")
	if [ "$sample" = 1 ]; then
		fact "$name" sample_spacing_s i "$SAMPLE_S"
		sampler "$U/samples.txt" &
		spid=$!
	fi
	if [ "$rec" = 1 ]; then
		install -d -m 0775 "$U/bag"
		simx=(-v "$CTL:/sdv/sdv/ctl:ro" -v "$U/bag:/sdv-bag")
	fi
	# the planning simulator, then its services
	rc=0
	docker run -d --name aw-sim "${awc[@]}" -v "$MAPS:/sdv-map:ro" ${simx[@]+"${simx[@]}"} "$AWU_REF" \
		ros2 launch autoware_launch planning_simulator.launch.xml "map_path:=/sdv-map/$AWU_MAP" vehicle_model:=sample_vehicle \
		sensor_model:=sample_sensor_kit rviz:=false > "$U/sim.id" 2> "$U/sim.err" < /dev/null || rc=$?
	fact "$name" sim_run_exit i "$rc"
	if [ "$rc" != 0 ]; then
		fact "$name" state s sim-failed
		[ -z "$spid" ] || { kill "$spid" 2>/dev/null; wait "$spid" 2>/dev/null; } || true
		return 0
	fi
	end=$(( $(vss_now) + SIM_UP_S ))   # a bound on the wait's time: each poll takes its exec's time as well as the pause
	while :; do
		n=$((n + 1))
		out="$(timeout 60 docker exec aw-sim /sdv-aw/aw-entrypoint.sh ros2 service list 2>/dev/null < /dev/null)" || out=""
		if sim_lists_services "$out"; then up=yes; break; fi
		[ "$(timeout 60 docker inspect -f '{{.State.Running}}' aw-sim 2>/dev/null)" = true ] || break
		[ "$(vss_now)" -lt "$end" ] || break
		sleep "$SIM_POLL_S"
	done
	fact "$name" sim_up b "$([ "$up" = yes ] && echo true || echo false)"
	fact "$name" sim_polls i "$n"
	if [ "$up" != yes ]; then
		fact "$name" state s sim-not-up
		timeout 120 docker stop -t "$STOP_SIM_S" aw-sim > /dev/null 2>&1 || true
		[ -z "$spid" ] || { kill "$spid" 2>/dev/null; wait "$spid" 2>/dev/null; } || true
		return 0
	fi
	# the kill's target, read before the route: the controller is a composable node in a component container it shares
	# with the gate, so it is unloaded from that container, never a process killed (which would end the gate too)
	if [ "$kill" = 1 ]; then
		out="$(timeout 120 docker exec aw-sim /sdv-aw/aw-entrypoint.sh ros2 component list 2>/dev/null < /dev/null)" || out=""
		target="$(printf '%s\n' "$out" | python3 "$TOOL" component --name "$KILL_NODE" 2> "$U/component.why")" || target=""
		if [ -n "$target" ]; then
			fact "$name" kill_container s "${target% *}"
			fact "$name" kill_id s "${target##* }"
		else
			fact "$name" kill_problem s "$(tr '\n' ' ' < "$U/component.why")"
		fi
	fi
	# the claim node, before the driver sets the route (W4 G2)
	if [ "$claim" = 1 ]; then
		rc=0
		# shellcheck disable=SC2086  # the unit's claim arguments are words (aw_suite.py, THE PLANS)
		docker run -d --name aw-claim-node "${awc[@]}" -v "$CTL:/sdv/sdv/ctl:ro" -v "$VSS_HOME/gen:/sdv-gen:ro" \
			-v "$U/claim:/sdv-claim" "$AWU_REF" python3 /sdv/sdv/ctl/ctl_claim_node.py --host "$GUEST" --port "$CLAIM_PORT" \
			--contract /sdv-gen/vss_ctl.py --out /sdv-claim/run $args > /dev/null 2> "$U/claim.err" < /dev/null || rc=$?
		fact "$name" claim_run_exit i "$rc"
	fi
	if [ "$rec" = 1 ]; then
		rc=0; docker exec -d aw-sim /sdv-aw/aw-entrypoint.sh ros2 bag record -o /sdv-bag/bag "${BAG_TOPICS[@]}" < /dev/null \
			> /dev/null 2>&1 || rc=$?
		fact "$name" bag_record_exit i "$rc"
	fi
	# the driver
	drv=(docker run --rm --name aw-scenario "${awc[@]}" -v "$CTL:/sdv/sdv/ctl:ro" -v "$MAPS:/sdv-map:ro" -v "$U/scn:/sdv-scn"
		"$AWU_REF" python3 /sdv/sdv/ctl/aw_scenario.py --scenario "/sdv/sdv/ctl/scenarios/$SCENARIO.json"
		--map-dir "/sdv-map/$AWU_MAP" --out /sdv-scn/run)
	[ "$claim" != 1 ] || drv+=(--require-claim-node)
	rc=0
	if [ "$kill" = 1 ]; then
		"${drv[@]}" > "$U/scenario.log" 2>&1 < /dev/null &
		dpid=$!
		for i in $(seq 1 "$ENGAGE_WAIT_S"); do
			[ -n "$target" ] || break
			if python3 "$TOOL" engaged --file "$U/scn/run/scenario.jsonl"; then
				# shellcheck disable=SC2086  # the container and the component's id: two words
				rc=0; timeout 60 docker exec aw-sim /sdv-aw/aw-entrypoint.sh ros2 component unload $target < /dev/null \
					> "$U/unload.out" 2>&1 || rc=$?
				fact "$name" kill_exit i "$rc"
				[ "$rc" != 0 ] || killed=yes
				break
			fi
			kill -0 "$dpid" 2>/dev/null || break
			sleep 1
		done
		fact "$name" killed b "$([ "$killed" = yes ] && echo true || echo false)"
		rc=0; wait "$dpid" || rc=$?
	else
		"${drv[@]}" > "$U/scenario.log" 2>&1 < /dev/null || rc=$?
	fi
	fact "$name" scenario_exit i "$rc"
	# the bag closed and exported
	if [ "$rec" = 1 ]; then
		rc=0; docker exec aw-sim pkill -INT -f "ros2 bag record -o /sdv-bag/bag" < /dev/null > /dev/null 2>&1 || rc=$?
		fact "$name" bag_stop_exit i "$rc"
		for i in $(seq 1 "$BAG_CLOSE_S"); do [ ! -e "$U/bag/bag/metadata.yaml" ] || break; sleep 1; done
		fact "$name" bag_closed b "$([ -e "$U/bag/bag/metadata.yaml" ] && echo true || echo false)"
		rc=0; docker exec aw-sim /sdv-aw/aw-entrypoint.sh python3 /sdv/sdv/ctl/ctl_export.py --bag /sdv-bag/bag \
			--out /sdv-bag/export.jsonl < /dev/null > "$U/export.log" 2>&1 || rc=$?
		fact "$name" export_exit i "$rc"
	fi
	# the claim node's end, then the simulator's
	if [ "$claim" = 1 ]; then
		rc=0; timeout 120 docker stop -t "$STOP_CLAIM_S" aw-claim-node > /dev/null 2>&1 || rc=$?
		fact "$name" claim_stop_exit i "$rc"
		timeout 60 docker logs aw-claim-node > "$U/claim-node.log" 2>&1 || true
		out="$(timeout 60 docker inspect -f '{{.State.ExitCode}}' aw-claim-node 2>/dev/null)" || out=""
		case "$out" in ''|*[!0-9]*) fact "$name" claim_exit s "${out:-unread}" ;; *) fact "$name" claim_exit i "$out" ;; esac
	fi
	rc=0; timeout 120 docker stop -t "$STOP_SIM_S" aw-sim > /dev/null 2>&1 || rc=$?
	fact "$name" sim_stop_exit i "$rc"
	if [ -n "$spid" ]; then kill "$spid" 2>/dev/null || true; wait "$spid" 2>/dev/null || true; fi
	fact "$name" state s ran
}

# --- the parent: a unit, its sweep and its record ------------------------------------------------------------------
copy_kept() {   # SRC DST: a record file the unit left, when there is one
	[ -f "$1" ] || return 0
	cp -f "$1" "$2" 2>/dev/null || say "$(basename "$1") could not be copied into the record"
}
sweep_unit() {   # NAME: the claim node's log if the unit left it unread, the unit's containers removed by name whatever its
	# end, then the label listed
	local u="$1" rc=0 ids log="$WORK/units/$1/claim-node.log"
	# the claim node's log (2.11), when the unit's own end did not read it after the node started (a cap, a failure): read
	# as it stands, before the removal leaves nothing to read
	if [ "$(cat "$WORK/facts/$u/claim_run_exit.i" 2>/dev/null)" = 0 ] && [ ! -e "$log" ]; then
		if timeout 60 docker logs aw-claim-node > "$log" 2>&1; then fact "$u" claim_log_at_sweep b true
		else rm -f "$log"; fact "$u" claim_log_at_sweep b false; fi
	fi
	timeout 120 docker rm -f "${UNIT_CONTAINERS[@]}" >/dev/null 2>&1 || rc=$?
	fact "$u" unit_rm_exit i "$rc"
	rc=0; ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
	if [ "$rc" != 0 ]; then
		fact "$u" swept_list_exit i "$rc"
		fact "$u" swept b false
		say "unit $u: the containers labelled $LABEL could not be listed after its removals (docker ps exit $rc)"
		return 0
	fi
	fact "$u" containers_left i "$(printf '%s\n' "$ids" | grep -c . || true)"
	fact "$u" swept b "$([ -z "$ids" ] && echo true || echo false)"
}
collect_unit() {   # NAME: the unit's records into OUT/NAME (2.11), the console's part it saw, its unit.json
	local u="$1" U="$WORK/units/$1" D="$OUT/$1" from
	mkdir -p "$D"
	copy_kept "$U/claim/run/replies.jsonl" "$D/replies.jsonl"
	copy_kept "$U/claim-node.log" "$D/claim-node.log"
	copy_kept "$U/scn/run/scenario.jsonl" "$D/scenario.jsonl"
	copy_kept "$U/bag/export.jsonl" "$D/export.jsonl"
	from="$(cat "$WORK/facts/$u/console_from.i" 2>/dev/null || echo 0)"
	fact "$u" console_to i "$(console_size)"
	python3 "$TOOL" slice --console "$CONSOLE" --from "$from" --to "$(console_size)" --out "$D/guest-console.log" || true
	python3 "$TOOL" unit-json --work "$WORK" --name "$u" --unit-dir "$D" --plan "${PLAN:-}" --out "$D/unit.json" \
		|| say "unit.json for $u could not be written"
}

run_unit() {   # NN NAME: the check point, the unit under its cap, its sweep and its record
	local nn="$1" name="$2" rc t0
	CUR="$name"
	if vss_past_stop; then finish TIMEOUT "$name" deadline; fi
	: > "$WORK/state/began"
	say "unit $name: start"
	fact "$name" console_from i "$(console_size)"
	t0="$(vss_now)"
	rc=0
	vss_capped env AWU_REF="$REF" AWU_GID="$(id -g)" AWU_DOMAIN="${DDS_ENV%% *}" AWU_RMW="${DDS_ENV#* }" AWU_MAP="$MAP_NAME" \
		bash "$SELF" _unit "$nn" "$name" < /dev/null || rc=$?
	fact "$name" operational_s/unit i "$(( $(vss_now) - t0 ))"
	fact "$name" unit_exit i "$rc"
	if vss_cap_fired "$rc"; then
		fact "$name" state s step-timeout
		sweep_unit "$name"; collect_unit "$name"
		finish TIMEOUT "$name" step-timeout
	fi
	[ "$rc" = 0 ] || fact "$name" state s failed
	sweep_unit "$name"
	collect_unit "$name"
	say "unit $name: end ($(state_of "$name"), exit $rc)"
}

# --- the preflight -------------------------------------------------------------------------------------------------
refuse() { finish FAILED preflight "$*"; }

preflight() {
	local s=preflight groups last out f ids rc=0
	case "${PLAN:-}" in
		a1|a2|b1|b2|s) ;;
		*) refuse "PLAN='${PLAN:-}' is not a1, a2, b1, b2 or s (the harness phase passes PLAN=a1|a2|b1|b2|s)" ;;
	esac
	fact $s plan s "$PLAN"
	python3 "$TOOL" plan --plan "$PLAN" > "$WORK/plan.tsv" 2> "$WORK/plan.err" || refuse "the plan: $(cat "$WORK/plan.err")"
	groups="$(id -nG 2>/dev/null)" || groups=""
	case " $groups " in
		*" docker "*) fact $s docker_group b true ;;
		*) fact $s docker_group b false
		   refuse "this login is not in the docker group: run-vss-setup.sh adds it, and it applies from the next login" ;;
	esac
	[ -e "$SETUP_REC/done" ] || refuse "rec/aw-setup has no done: run-aw-setup.sh has not finished (wait for it with wait-run)"
	last="$(grep '^status=' "$SETUP_REC/status" 2>/dev/null | tail -n 1 || true)"
	fact $s aw_setup_status_line s "${last:-none}"
	[ "$last" = status=DONE ] || refuse "run-aw-setup.sh's last status line is '${last:-none}', not status=DONE"
	out="$(python3 "$TOOL" setup --setup "$SETUP_REC/raw/setup.json" --host-mode "$HOST_MODE" --facts "$WORK/facts/$s" 2>&1)" \
		|| refuse "$out"
	REF="${out%% *}"
	if guest_runs; then
		fact $s qemu_running b true
		refuse "a QEMU runs already: the guest this harness boots would be a second one (it is not stopped here)"
	fi
	fact $s qemu_running b false
	fact $s image s "$(basename "$IFS_BIN")"
	[ "$(basename "$IFS_BIN")" = ifs-ctl.bin ] \
		|| refuse "IFS_BIN is $(basename "$IFS_BIN"), not ifs-ctl.bin: the suite's guest is WP5's image, which serves kind 2 on :7150"
	[ -r "$IFS_BIN" ] && [ -r "$DISK" ] && [ -r "$LAUNCH" ] || refuse "IFS_BIN, DISK or the launch script is not readable"
	for f in "$AW/aw-entrypoint.sh" "$HC" "$AW/ros-env.json" "$CTL/ctl_claim_node.py" "$CTL/aw_scenario.py" \
		"$CTL/ctl_export.py" "$SCN"; do
		[ -r "$f" ] || refuse "the repo tarball lacks ${f#"$REPO/"}: an aw harness needs the tarball of a commit that has it"
	done
	[ -x "$AW/aw-entrypoint.sh" ] || refuse "sdv/aw/aw-entrypoint.sh is not executable: --entrypoint runs it by its path"
	DIGEST="$(python3 "$TOOL" contract --file "$CONTRACT" --facts "$WORK/facts/$s" 2>&1)" || refuse "$DIGEST"
	MAP_NAME="$(python3 "$TOOL" map-check --map-dir "$MAPS" --scenario "$SCN" --facts "$WORK/facts/$s/map" 2>&1)" \
		|| refuse "the staged map: $MAP_NAME"
	rc=0; out="$(timeout 120 docker image inspect "$REF" 2>&1)" || rc=$?
	[ "$rc" = 0 ] || refuse "the image $REF is not in the image store (docker image inspect exited $rc): run-aw-setup.sh pulls it"
	printf '%s\n' "$out" | python3 "$SETUP_TOOL" inspect --ref "$REF" --facts "$WORK/facts/$s/image" > "$WORK/inspect.why" 2>&1 \
		|| refuse "$(cat "$WORK/inspect.why")"
	DDS_ENV="$(python3 "$SETUP_TOOL" dds --env "$AW/ros-env.json" --out "$WORK/dds/cyclonedds.xml" 2>&1)" || refuse "$DDS_ENV"
	rc=0; ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
	[ "$rc" = 0 ] || refuse "the containers labelled $LABEL cannot be listed (docker ps exit $rc)"
	[ -z "$ids" ] || refuse "a container labelled $LABEL is still there (an earlier aw run's: $(printf '%s ' $ids)): this harness's" \
		"names would collide"
	host_check_before
	say "preflight: PLAN=$PLAN, run-aw-setup.sh DONE as $HOST_MODE, the image $REF in the store, ctl contract $DIGEST"
}

# --- the stops -------------------------------------------------------------------------------------------------------
stop_verdict() {   # REASON...: stop.verified, false with the reasons when the sweep could not show its removals done
	local j
	if [ "$#" = 0 ]; then fact stop verified b true; return 0; fi
	fact stop verified b false
	fact stop unverified lines "$(printf '%s\n' "$@")"
	j="$(printf '%s; ' "$@")"
	say "the stop is unverified: ${j%; }"
}
sweep() {   # the idempotent removals of every stop, DONE included, under suite.json's stop
	local unv=() ids rc=0 rc2=0 n left
	if [ -e "$WORK/state/launched" ]; then
		stop_guest stop
		rm -f "$WORK/state/launched"
		[ "$(cat "$WORK/facts/stop/qemu_stopped.b" 2>/dev/null)" != false ] || unv+=("QEMU still runs after a KILL")
	fi
	if [ -e "$WORK/state/began" ]; then
		timeout 120 docker rm -f "${UNIT_CONTAINERS[@]}" >/dev/null 2>&1 || true
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
	fi
	stop_verdict ${unv[@]+"${unv[@]}"}
}
clean_stop() {   # a stop other than DONE: sync, then the sweep
	say "a clean stop: sync, QEMU stopped if this harness launched it, the containers labelled $LABEL removed"
	timeout 120 sync || true
	sweep
}

write_record() {   # STATUS STATUS-LINE AT REASON
	python3 "$TOOL" record --work "$WORK" --out "$OUT/suite.json" --plan "${PLAN:-}" --status "$1" --status-line "$2" \
		--at "$3" --reason "$4" --host-mode "${HOST_MODE:-unset}" --guest-host "$GUEST"
}

finish() {   # STATUS [AT [REASON]]: the sweep, the host check, the record, then the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line nn name rest notrun=""
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
		say "suite.json could not be written"
		if [ "$st" = DONE ]; then st=FAILED; at=record; line="status=FAILED at=record"; fi
	fi
	if [ "$st" != DONE ] && [ -r "$WORK/plan.tsv" ]; then
		while IFS=$'\t' read -r nn name rest; do
			[ -n "$(state_of "$name")" ] || notrun="$notrun $name"
		done < "$WORK/plan.tsv"
		say "not run:${notrun:- none}"
	fi
	[ "$st" != FAILED ] || say "FAILED at $at: $why"
	# shellcheck disable=SC2086  # the status line's words; vss_status writes the status= itself
	vss_status ${line#status=}
	[ "$st" != FAILED ] || exit 1
	exit 0
}

on_exit() {   # the harness ended without a status line: a FAILED record all the same
	local rc=$?
	finish FAILED "${CUR:-preflight}" "the harness stopped unexpectedly (exit $rc)"
}

main() {
	local nn name rest why
	CUR=preflight
	rm -rf "$WORK"
	mkdir -p "$WORK/facts" "$WORK/state" "$WORK/units" "$OUT"
	trap on_exit EXIT
	say "run-aw-suite.sh PLAN=${PLAN:-}: a functional session; operational steps recorded"
	why="$(host_refusal)"
	[ -z "$why" ] || refuse "$why"
	if ! vss_deadline_load; then refuse "no readable deadline file (lib-vss-deadline.sh)"; fi
	fact preflight deadline_readable b true
	preflight
	guest_unit
	while IFS=$'\t' read -r nn name rest <&3; do
		run_unit "$nn" "$name"
	done 3< "$WORK/plan.tsv"
	finish DONE
}

case "${1:-}" in
	_guest) vss_deadline_load || exit 1; guest_checks; exit 0 ;;          # the guest's checks, under their cap
	_unit) vss_deadline_load || exit 1; unit_child "${2:?}" "${3:?}"; exit 0 ;;   # one unit, under its cap
esac
main
