#!/usr/bin/env bash
# run-aw-g1.sh -- one arm of gate G1: Autoware's planning simulator with the claim node beside the QNX guest under KVM, for
# a 20-minute scripted loop, judged against sdv/aw/prereg-g1g2.md (PR), which holds every threshold, arm and counting rule.
# SDV Phase 8 WP8 Step B.
#
# HOW IT RUNS. On the Orin, from the board's helper (`g1-main`, `g1-guest-stopped`) under its runner, after
# `drop_caches`, with the governor pinned by the helper. On a bare-metal host only as remote-ladder.sh's harness phase starts
# it, detached, for the rehearsal described here: LADDER_ENV="HARNESS=run-aw-g1.sh IMAGE=ifs-ctl.bin PLAN=rehearsal
# VSS_HOST=c7g-metal", after run-aw-setup.sh ended status=DONE. It runs from orin-native/gpu-concurrency of the commit's tree.
# Who sets the daemons' AllowedCPUs=3,5, the runtime property behind what the stamp's g1 policy reads: on the Orin the helper's
# g1-setup, and its teardown restores it, and this harness touches neither; under PLAN=rehearsal, which c7g-metal alone takes,
# this harness sets it on docker.service and containerd.service just before the stamp (no ladder phase does)
# and restores every core after the kill unit. PLAN=main refuses at the stamp on a host where the daemons are off {3,5}.
# Its environment:
#   IFS_BIN    ifs-ctl.bin (WP5's image: kind 2 on :7150); DISK the guest disk
#   OUT        the record (every name below); its parent holds host-before.txt and host-after.txt; STATUS the status file
#   VSS_HOME   gen/vss_ctl.py (the generation), aw/map/<map>/ (the staged map); aw-g1-work/, this harness's own working files
#   VSS_HOST   the host's role, `orin` or `c7g-metal` (THE HOST)
#   PLAN       main (the main arm); guest-stopped (PR section 3: only on the owner's word, which the helper checks); or
#              rehearsal (c7g-metal only: the main arm, then the short watchdog kill unit, into OUT/kill)
#   G1_RERUN_OF, G1_RERUN_AFTER  an arm that is a re-run (PR section 5): what of, and reset or not-judged, for the judge's label;
#              another word, or G1_RERUN_AFTER without G1_RERUN_OF, is refused
#   G1_WORK_TAG  a suffix for aw-g1-work: the kill unit's, or a second arm's whose first left files of another uid there
# For the tests, each overriding one file as run-aw-suite.sh's do: QNX_METAL_DEADLINE_FILE, QNX_MEMINFO_FILE, QNX_VMSTAT_FILE,
# QNX_STAT_FILE, QNX_CLOCK_FILE, QNX_L4T_RELEASE_FILE, QNX_DT_COMPATIBLE_FILE; lib-measure.sh's PROC_ROOT and SYS_ROOT;
# QNX_GUEST_HOST the guest's address. G1_REHEARSAL_FLOOR_KB is the rehearsal's one named override of the watchdog's floor,
# refused under VSS_HOST=orin; with it set the watchdog starts just before the first drive, so that containers are there to
# kill, which the floor's first read would otherwise prevent. The deadline is lib-vss-deadline.sh's: the helper writes the
# file at stop_at + 25 minutes.
#
# THE HOST. VSS_HOST=orin only on a host L4T's release file or an NVIDIA device tree marks as a Jetson; VSS_HOST=c7g-metal
# only on any other host; anything else is refused. run-aw-suite.sh's refusal of the Orin stands: G1 does not use it.
#
# PREFLIGHT, in this order; a refusal is status=FAILED at=preflight, exit 1, and nothing has started: an earlier record in
# OUT (never mixed); the host; the deadline file; PLAN; the override's rule; the re-run's words; `id -nG` includes docker; no
# QEMU running (one found is refused, never stopped); IFS_BIN is ifs-ctl.bin (main arm), and it, DISK and the launch script
# readable; the tree's sdv/aw, sdv/ctl and the scenario; vss_ctl.py's DIGEST; the staged map, by the scenario's sha256; the
# image in the store by its digest (sdv/stack/images.json's arm64 manifest); 2.7's DDS file written; no container labelled
# sdv.aw.run, and the label listed; then 2.12's host check before.
#
# THE ORDER:
#   the stamp    m_write_stamp under PLATFORM_POLICY=g1 (lib-measure.sh), before any container, with N, K, WARMUP and
#                INTERVAL_MS 0, which means no ladder; SAMPLE_WINDOW=1; the helper's governor pin read, on every core, and
#                changed by nothing here; under PLAN=rehearsal the daemons' AllowedCPUs set first. A refusal, or a property that
#                cannot be set, is status=FAILED at=stamp, and nothing else starts
#   recorders    on core 4, by this script, before the guest boots, never by a login: sdv/aw/g1_watchdog.py,
#                sdv/aw/g1_sampler.py and m_clock_sampler_start, each ceilinged by the arm's bound. No watchdog series
#                within WD_START_S ends it at=recorders
#   the guest    (main arm) launch-qnx-kvm-bridged.sh; vss-repin.sh boot; oom_score_adj -1000 through `sudo -n tee`, read back;
#                the read with the guest idle; the :7150 exchange (ctlsynth.py --plan late --check: real frames, judged);
#                the console's `ctl rules:` line; the :7100 smoke. A guest that cannot judge ends it at=guest: no container
#                has started
#   containers   /proc/vmstat's oom_kill read, then the first container's start read; aw-sim; the one-clock pair (one action
#                in the container, one on the host); the simulator's services polled, a bound on the wait and no more: one
#                that does not list them goes on to the first drive, which then has no route and ends the loop (PR section
#                5); aw-claim-node (the guest-stopped arm: aw-g1-count); aw-g1-diag. Each labelled sdv.aw.run=g1, --cpuset-cpus
#                3,5, --memory and --memory-swap both 3200m for aw-sim and 256m for each of the others (PR section 4), and
#                under 2.12: the project entrypoint read-only, --user aw, --cap-drop ALL, no-new-privileges, never --privileged,
#                --cap-add or a /proc/sys or /sys mount; --network host, 2.7's single-host form. No sysctl and no lo multicast
#                are ever set here. A `docker run -d` of one of these that exits non-zero read nothing of Autoware: it is the
#                harness's own exit, status=FAILED at=arm, and the judge's NOT JUDGED names it
#   each start   its init pid from docker inspect, its scope from /proc/<pid>/cgroup (appended to the file the watchdog and
#                sampler read), its HostConfig.CpusetCpus and the scope's cpuset.cpus.effective against {3,5} (placement.tsv);
#                vss-repin.sh <name> in the main arm, recorded, G1 not relying on the pin surviving. Off {3,5}: the loop's end
#                `misplaced`, before the loop or at that drive
#   the loop     below; at its end, before any docker stop, each scope's memory.events and /proc/vmstat; then the claim node
#                (or the count recorder), aw-g1-diag, aw-sim and the driver stopped in that order, so that no participant leaves
#                while a frame can still be counted (T6 reads the whole arm), the last stop's time read, the removals
#
# THE LOOP (PR sections 4 and 5). Before each drive: the stop file (watchdog-stop); the deadline's check point (deadline); aw-sim
# by docker inspect (sim-died, only on docker's own answer that it is not running or does not exist, in docker's words read
# without regard to case; an inspect with no answer is recorded as sim_inspect_unanswered and is no death: PR's dated section,
# item 2); the watchdog's pid and its series growing (watchdog-dead). Then one drive. THE DRIVER IS RESIDENT (PR's dated section,
# item 15): one aw-scenario container and one process, aw_scenario.py --serve, on {3,5}, started at the first drive, before its
# route and before the claim node's first Control; it joins once. Each drive begins by a word in the go file, $WORK/serve/go,
# written by a rename (the word is the drive's directory under drives/, and the driver takes it once), and ends with the driver's
# exit number in drives/dNNN/exit, which it writes by a rename as the last thing of that drive. One `docker wait` per drive is
# held open beside it, under its bound (DRIVE_BOUND_S), so that nothing polls docker inside a drive. A non-zero exit does not end
# the loop: T7 has failed, the driver has asked for STOP and cleared the route (drives/dNNN/after-failure.jsonl, never
# scenario.jsonl), the next drive begins and the time counts. Its `docker run -d` exiting non-zero: no drive ran, its row is
# `stopped K docker-run-exit-RC`, not a driver's exit, and the loop ends (docker-run-failed, the harness's own, NOT JUDGED unless
# an item failed by a reading: item 2). Its exit (item 15, which reads item 12): a number in that drive's own file is the driver's
# exit; a line not yet ended is no read. A bound that expires while docker answers that the container runs is the drive's reading,
# exit 124. A container that ended with no number written is that drive's reading with docker's exit code. Either way the
# container is removed and the next drive starts another: nothing of it reaches the next. Anything else read no exit: its row is
# `stopped K docker-wait-exit-RC`, or `stopped K docker-wait-bound-no-answer` for a bound that expired with no answer from docker
# either, and the loop ends (docker-wait-failed, the harness's own, the same). The stop file, if it exists by then, is the end's
# word in both. A driver found ended before a word is written, between two drives, is no drive's reading: recorded as
# driver_ended_between_drives, and started again for that drive. After the first drive, no `route` line of outcome done ends it
# (first-no-route). The drive that ends 1200 s or more after the first route was set, on CLOCK_MONOTONIC, is the last (reached). A
# dead aw-sim is seen between drives and by the drive under way ending at its step's timeout, so the end can lag by up to
# `arrive`'s timeout and the stop's and clear's after it.
#
# THE STATUS LINE, the last one in STATUS, through vss_status. status=DONE: the arm ran to the loop's end, WHATEVER THE
# VERDICT: a FAIL or a NOT JUDGED is a result, and no threshold stops or fails this script (PR section 2).
# status=TIMEOUT at=arm reason=deadline|step-timeout: the deadline ended it, exit 0. status=FAILED
# at=preflight|stamp|recorders|guest|arm|host-check|record|<where it was>: exit 1; at=record: the arm ran to its end, but `aw_g1.py
# judge` could not run or g1.json could not be written, so a DONE would be a record with no verdict. Every stop sweeps first: QEMU
# stopped if this harness launched it, every container labelled sdv.aw.run removed; then the recorders stopped, the host check after,
# m_stamp_after, `aw_g1.py judge`, g1.json, the status line.
#
# guest-console.log and scopes.txt are written in OUT from the start, so that a reset or a killed harness leaves them in the record
# (PR section 5); a re-run removes only its working directory, and one it cannot remove ends it at=preflight.
# THE RECORD, in OUT (aw_g1.py, THE RECORD; each name on capture.py's whitelist under aw-g1/raw): arm.tsv, stamp.json,
# stamp.out, watchdog.log, watchdog.err, watchdog.stop, sampler.jsonl, clk-g1.log, placement.tsv, scopes.txt, repin.txt,
# clock-pairs.txt, guest-idle.txt, guest-console.log, vmstat-before.txt, vmstat-end.txt, memory-events-end.tsv, hc-before.txt,
# hc-after.txt, drives.tsv, drives/dNNN/scenario.jsonl, drives/dNNN/odometry.jsonl, drives/dNNN/exit, drives/dNNN/after-failure.jsonl,
# drives/driver-dNNN.log (each driver container's, named by the first drive it served), claim/run/replies.jsonl, claim-node.log,
# diag/diag.jsonl, count/arrivals.jsonl, verdict.txt, windows.tsv, g1.json; OUT/kill the same under PLAN=rehearsal. Never a
# ROS log directory.
#
# WHAT IS KNOWN when this was written: PR section 2, by record names only, and nothing else; no outcome is predicted here or
# anywhere.
#
# DESIGN VALUES (not measured; PR section 4 holds the gate's own): the simulator's wait (SIM_UP_S 1200 s from its docker run, PR's
# dated section, item 11, polled every SIM_POLL_S 5 s, the time it took in the record as sim_up_s); a drive's bound (DRIVE_BOUND_S
# 600 s: the scenario's four timeouts, 300 s, and the driver's clear and settles, and its stop and clear after a failure, with
# room); the rules line's wait (RULES_WAIT_S 5 s); the look at a drive's exit file (EXIT_POLL_S 1 s); the watchdog's start
# (WD_START_S 10 s) and its series' growth (WD_GROW_S 5 s); the stops (STOP_CLAIM_S 15 s: the claim node drains for at most 1 s;
# STOP_DIAG_S 10 s; STOP_SIM_S 30 s; STOP_DRIVER_S 5 s); the guest's stop (STOP_WAIT_S 10 s, then KILL and 10 s more); the
# recorders' ceiling over the arm's cap (RECORDER_MARGIN_S 120 s).
#
# WHAT IT DOES NOT SHOW: any verdict by itself (`aw_g1.py judge` reads the record against PR); that the design values leave
# Autoware enough; any figure on another boot, map or route; a rehearsal's figures are never G1's and are compared with nothing;
# this script's own processes (docker CLIs, python3 between drives) float over every core, so they are load the record does not
# separate; that a resident driver reads T6 at drop 0, on any host; a container start per drive beside Autoware is no longer in the arm,
# and the driver's memory is there all the time (PR's dated section, item 15); the topic's own rate, any latency, any isolation or
# freedom from interference, any real-time guarantee, that Autoware's commands were safe, nor any safety or certification
# property. The startup that boots the guest under KVM is ours, not a QNX-supported configuration,
# and no timing claim attaches to the boot.
set -u
set -eo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
PLATFORM_POLICY=g1
# shellcheck source=lib-measure.sh
. "$HERE/lib-measure.sh"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || exit 1
: "${IFS_BIN:?no IFS_BIN}" "${DISK:?no DISK}" "${OUT:?no OUT}" "${VSS_HOME:?no VSS_HOME}" "${STATUS:?no STATUS}"

TOOL="$HERE/aw_g1.py"
SETUP_TOOL="$HERE/aw_setup.py"
SUITE_TOOL="$HERE/aw_suite.py"
VSS_TOOL="$HERE/vss_setup.py"
LAUNCH="$HERE/launch-qnx-kvm-bridged.sh"
REPIN="$HERE/vss-repin.sh"
REPO="$(cd "$HERE/../.." && pwd)"
AW="$REPO/sdv/aw"
HC="$AW/hostcheck.sh"
CTL="$REPO/sdv/ctl"
IMAGES="$REPO/sdv/stack/images.json"
SCENARIO=sample-lanelet-102
SCN="$CTL/scenarios/$SCENARIO.json"
WORK="$VSS_HOME/aw-g1-work${G1_WORK_TAG:+-$G1_WORK_TAG}"
MAPS="$VSS_HOME/aw/map"
CONTRACT="$VSS_HOME/gen/vss_ctl.py"
STEM="$(dirname "$OUT")"
CONSOLE="$OUT/guest-console.log"
GUEST="${QNX_GUEST_HOST:-192.168.100.10}"
SCOPES="$OUT/scopes.txt"
SERIES="$OUT/watchdog.log"
STOP="$OUT/watchdog.stop"
LABEL=sdv.aw.run
RUN_LABEL="$LABEL=g1"
CONT_CORES=3,5                  # PR section 4: every container; core 4 the recorders'; QEMU's 0-2 (vss-repin.sh)
RECORDER_CORE=4
MEM_SIM=3200m                   # PR section 4: --memory and --memory-swap of aw-sim
MEM_OTHER=256m                  # PR section 4: of each of the others
LOOP_NS=1200000000000           # PR section 4: drives begin until 1200 s have passed since the first route was set
CLAIM_PORT=7150
READY_TRIES=30; READY_BOUND_S=3
RULES_WAIT_S=5
SIM_UP_S=1200; SIM_POLL_S=5
DRIVE_BOUND_S=600
EXIT_FILE=exit                  # aw_scenario.py's: the driver's answer in a drive's directory
EXIT_POLL_S=1
WD_START_S=10; WD_GROW_S=5
STOP_CLAIM_S=15; STOP_DIAG_S=10; STOP_SIM_S=30; STOP_DRIVER_S=5
STOP_WAIT_S=10
RECORDER_MARGIN_S=120
EXCHANGE_BOUND_S=120
# every container this harness starts; the sweep's names when the label cannot be listed
G1_CONTAINERS=(aw-sim aw-claim-node aw-g1-count aw-g1-diag aw-scenario)
DAEMON_UNITS=(docker.service containerd.service)   # PR section 4's AllowedCPUs; the rehearsal's own, the Orin's helper's
# the services the driver calls first (run-aw-suite.sh's SIM_SERVICES, copied: it is not changed for this harness)
SIM_SERVICES=(/api/localization/initialize /api/routing/set_route_points /api/operation_mode/change_to_autonomous)
HOST_MODE="${VSS_HOST-}"
MEMINFO="${QNX_MEMINFO_FILE:-/proc/meminfo}"
VMSTAT="${QNX_VMSTAT_FILE:-/proc/vmstat}"
L4T_RELEASE="${QNX_L4T_RELEASE_FILE:-/etc/nv_tegra_release}"
DT_COMPATIBLE="${QNX_DT_COMPATIBLE_FILE:-/proc/device-tree/compatible}"
ARM=""; REF=""; DIGEST=""; DDS_ENV=""; MAP_NAME=""
DRIVER_UP=0; DRIVER_FROM=""     # the resident driver's container is there; the first drive it served, which names its log

arm() { printf '%s\t%s\n' "$1" "$2" >> "$OUT/arm.tsv"; }   # one fact of the arm: appended, the last value of a key holds
mono() { local p; p="$(python3 "$TOOL" now)"; printf '%s\n' "${p%% *}"; }
console_size() { stat -c %s "$CONSOLE" 2>/dev/null || echo 0; }

# --- the host (run-aw-suite.sh's on_jetson, copied: it is not changed for this harness) -----------------------------------
on_jetson() {
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
	if on_jetson; then
		[ "$HOST_MODE" = orin ] || echo "VSS_HOST='$shown' on a host L4T marks as a Jetson: this harness takes VSS_HOST=orin there"
	else
		[ "$HOST_MODE" = c7g-metal ] || echo "VSS_HOST='$shown' on a host L4T does not mark as a Jetson: this harness takes" \
			"VSS_HOST=c7g-metal there (the Autoware image runs on the c7g-metal role and the Orin only)"
	fi
}

# --- the host check (2.12, layer 3; run-aw-suite.sh's, with the record's own copies) ----------------------------------------
host_check_before() {
	local out rc=0
	out="$(bash "$HC" 2> "$WORK/hostcheck.err")" || rc=$?
	if [ "$rc" != 0 ]; then
		refuse "the host check cannot be read (sdv/aw/hostcheck.sh exited $rc: $(tr '\n' ' ' < "$WORK/hostcheck.err")):" \
			"2.12's before is not known, so nothing starts"
	fi
	printf '%s\n' "$out" > "$OUT/hc-before.txt"
	{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), before the stem's first container"; printf '%s\n' "$out"; } \
		>> "$STEM/host-before.txt"
	: > "$WORK/state/hc-before"
}
host_check_after() {   # 1 when a setting changed or it cannot be read
	local out rc=0 diff drc=0 ln
	[ -e "$WORK/state/hc-before" ] || return 0
	out="$(bash "$HC" 2> "$WORK/hostcheck.err")" || rc=$?
	if [ "$rc" != 0 ]; then
		{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), after the stem's sweep: cannot be read (exit $rc)"
		  cat "$WORK/hostcheck.err"; } >> "$STEM/host-after.txt"
		say "the host check after the sweep cannot be read (exit $rc): that this arm left the host's four settings as they" \
			"were is not shown"
		return 1
	fi
	printf '%s\n' "$out" > "$OUT/hc-after.txt"
	diff="$(bash "$HC" --compare "$OUT/hc-before.txt" "$OUT/hc-after.txt" 2>&1)" || drc=$?
	{ echo "== 2.12's host check (sdv/aw/hostcheck.sh), after the stem's sweep"; printf '%s\n' "$out"
	  [ -z "$diff" ] || printf '%s\n' "$diff"; } >> "$STEM/host-after.txt"
	[ "$drc" = 0 ] && return 0
	while IFS= read -r ln; do [ -z "$ln" ] || say "host check: $ln"; done <<< "$diff"
	return 1
}

# --- the recorders ----------------------------------------------------------------------------------------------------------
watchdog_start() {   # CEILING: on core 4, in a session of its own (a cap's group signal does not reach it); 1 with no series
	local end
	setsid taskset -c "$RECORDER_CORE" python3 "$AW/g1_watchdog.py" --series "$SERIES" --stop-file "$STOP" --scopes "$SCOPES" \
		--max-s "$1" > "$OUT/watchdog.err" 2>&1 < /dev/null &
	echo "$!" > "$WORK/watchdog.pid"
	end=$((SECONDS + WD_START_S))
	while [ "$SECONDS" -lt "$end" ]; do
		[ ! -s "$SERIES" ] || return 0
		kill -0 "$(cat "$WORK/watchdog.pid")" 2>/dev/null || return 1
		sleep 0.2
	done
	return 1
}
recorders_start() {
	local ceil
	ceil=$(( $(vss_cap_s) + RECORDER_MARGIN_S ))
	: > "$SCOPES"
	arm recorders_ceiling_s "$ceil"
	if [ -z "${G1_REHEARSAL_FLOOR_KB:-}" ] && ! watchdog_start "$ceil"; then
		finish FAILED recorders "the watchdog's series did not begin within $WD_START_S s: no board-safety stop, so nothing" \
			"starts ($(tr '\n' ' ' < "$OUT/watchdog.err"))"
	fi
	setsid taskset -c "$RECORDER_CORE" python3 "$AW/g1_sampler.py" --out "$OUT/sampler.jsonl" --scopes "$SCOPES" --max-s "$ceil" \
		> "$WORK/sampler.err" 2>&1 < /dev/null &
	echo "$!" > "$WORK/sampler.pid"
	m_clock_sampler_start g1 "$ceil"
	: > "$WORK/state/clock-sampler"
	arm arm_pair_start "$(python3 "$TOOL" now)"
}
stop_pidfile() {   # FILE: TERM, waited for, KILL if it lingers
	local pid i
	[ -r "$1" ] || return 0
	pid="$(cat "$1")"
	kill -TERM "$pid" 2>/dev/null || return 0
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
		kill -0 "$pid" 2>/dev/null || return 0
		sleep 0.25
	done
	kill -KILL "$pid" 2>/dev/null || true
}
recorders_stop() {
	stop_pidfile "$WORK/sampler.pid"
	if [ -e "$WORK/state/clock-sampler" ]; then m_sampler_stop || say "the clock sampler survived its stop"; fi
	stop_pidfile "$WORK/watchdog.pid"
}
watchdog_lives() {   # its pid, and its series growing since the last look (one line a second, flushed)
	local pid size end
	pid="$(cat "$WORK/watchdog.pid" 2>/dev/null)" || return 1
	kill -0 "$pid" 2>/dev/null || return 1
	end=$((SECONDS + WD_GROW_S))
	while :; do
		size="$(stat -c %s "$SERIES" 2>/dev/null || echo 0)"
		if [ "$size" -gt "${WD_LAST_SIZE:-0}" ]; then WD_LAST_SIZE="$size"; return 0; fi
		[ "$SECONDS" -lt "$end" ] || return 1
		kill -0 "$pid" 2>/dev/null || return 1
		sleep 0.2
	done
}

# --- the guest --------------------------------------------------------------------------------------------------------------
guest_runs() { pgrep -x qemu-system-aar >/dev/null 2>&1; }
stop_guest() {   # QEMU stopped as run-aw-suite.sh's stop does, KILL if it lingers, waited until gone
	local i
	if ! guest_runs; then arm qemu_stopped true; return 0; fi
	timeout 30 sudo -n pkill -x qemu-system-aar >/dev/null 2>&1 || true
	for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	if guest_runs; then
		timeout 30 sudo -n pkill -KILL -x qemu-system-aar >/dev/null 2>&1 || true
		for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	fi
	if guest_runs; then arm qemu_stopped false; say "QEMU still runs after a KILL"; return 0; fi
	arm qemu_stopped true
}
guest_refuse() {   # WHY: the guest cannot judge; the parent ends the arm at=guest
	printf '%s\n' "$*" > "$WORK/state/guest-refused"
	exit 4
}
repin() {   # TAG: the line in the record; its exit recorded, G1 not relying on the pin
	local rc=0
	bash "$REPIN" "$1" >> "$OUT/repin.txt" 2>&1 || rc=$?
	[ "$rc" = 0 ] || arm "repin_exit_$1" "$rc"
}
guest_idle_read() {
	{ say "the read with the guest idle, before the first container (arm $ARM)"
	  grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree):' "$MEMINFO" || true; } > "$OUT/guest-idle.txt"
}
guest_up() {
	local rc=0 qpid back i out parsed res bad rej
	: > "$WORK/state/launched"
	mkdir -p "$WORK/guest"
	env IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$CONSOLE" bash "$LAUNCH" > "$WORK/guest/launch.out" 2>&1 < /dev/null || rc=$?
	arm launch_exit "$rc"
	[ "$rc" = 0 ] || guest_refuse "the guest did not boot (the launch script exited $rc)"
	repin boot
	qpid="$(pgrep -x qemu-system-aar || true)"
	printf '%s\n' -1000 | sudo -n tee "${PROC_ROOT:-/proc}/$qpid/oom_score_adj" > /dev/null || true
	back="$(cat "${PROC_ROOT:-/proc}/$qpid/oom_score_adj" 2>/dev/null || true)"
	arm oom_score_adj "$back"
	[ "$back" = -1000 ] || guest_refuse "QEMU's oom_score_adj reads back '$back', not -1000: not PR section 3's guest"
	guest_idle_read
	# :7150 by an exchange, never by its banner: real frames, each reply judged. The MISS its close gives falls before the
	# arm's part of the console
	for i in $(seq 1 "$READY_TRIES"); do
		if timeout "$READY_BOUND_S" bash -c "exec 3<>/dev/tcp/$GUEST/$CLAIM_PORT && exec 3>&-" 2>/dev/null; then break; fi
		[ "$i" != "$READY_TRIES" ] || guest_refuse ":7150 did not accept within the bound ($READY_TRIES attempts of ${READY_BOUND_S} s)"
		sleep 1
	done
	rc=0
	timeout "$EXCHANGE_BOUND_S" python3 "$CTL/ctlsynth.py" --plan late --host "$GUEST" --port "$CLAIM_PORT" --contract "$CONTRACT" \
		--console "$CONSOLE" --check --out "$WORK/exchange" > "$WORK/exchange.out" 2>&1 < /dev/null || rc=$?
	arm exchange_7150_exit "$rc"
	[ "$rc" = 0 ] || guest_refuse "the :7150 exchange failed (ctlsynth.py exited $rc): $(tail -n 1 "$WORK/exchange.out" | tr -d '\r')"
	for i in $(seq 1 $((RULES_WAIT_S * 2))); do
		rc=0; python3 "$SUITE_TOOL" rules --console "$CONSOLE" --digest "$G1_DIGEST" --facts "$WORK/facts/guest/ctl_rules" \
			> "$WORK/rules.out" 2>&1 || rc=$?
		[ "$rc" != 0 ] || break
		grep -q "no \`ctl rules:\` line" "$WORK/rules.out" || break
		sleep 0.5
	done
	arm ctl_rules_exit "$rc"
	[ "$rc" = 0 ] || guest_refuse "$(tail -n 1 "$WORK/rules.out")"
	rc=0; out="$(python3 "$HERE/latency_probe.py" --host "$GUEST" --port 7100 --n 20 --warmup 0 2>&1)" || rc=$?
	parsed="$(printf '%s\n' "$out" | python3 "$VSS_TOOL" smoke)"
	res="$(printf '%s\n' "$parsed" | sed -n 's/^result_line //p')"
	bad="$(printf '%s\n' "$parsed" | sed -n 's/^bad //p')"
	rej="$(printf '%s\n' "$parsed" | sed -n 's/^rej //p')"
	arm smoke_7100 "exit=$rc result_line=$res bad=$bad rej=$rej"
	if [ "$rc" != 0 ] || [ "$res" != yes ] || [ "$bad" != 0 ] || [ "$rej" != 0 ]; then
		guest_refuse ":7100's smoke failed (exit $rc, bad $bad, rej $rej)"
	fi
	sleep 1                     # the exchange's MISS (its close, 500 ms) is on the console before the arm's part of it begins
	arm console_arm_from "$(console_size)"
}

# --- the containers ---------------------------------------------------------------------------------------------------------
# PR's dated section, item 2: a `docker run -d` that exits non-zero is the harness's own, as guest_refuse is for the guest.
run_refuse() {   # NAME RC ERRFILE: the parent ends the arm at=arm; nothing of Autoware was read here
	printf 'docker run of %s exited %s: %s\n' "$1" "$2" "$(tail -n 1 "$3" 2>/dev/null | tr -d '\r')" > "$WORK/state/arm-refused"
	exit 4
}
after_start() {   # NAME [ROW]: the read after a container's start (PR section 5), its scope listed, the re-pin; 1 when off {3,5}
	local name="$1" row="${2:-$1}" info req pid state scope="" eff=""
	info="$(timeout 60 docker inspect -f '{{.HostConfig.CpusetCpus}}|{{.State.Pid}}|{{.State.Running}}' "$name" 2>/dev/null)" \
		|| info="||gone"
	IFS='|' read -r req pid state <<< "$info"
	if [ -n "$pid" ] && [ "$pid" != 0 ]; then
		scope="$(_g1_scope_dir "$pid")"
		if [ -n "$scope" ]; then
			printf '%s\t%s\n' "$name" "$scope" >> "$SCOPES"
			eff="$(cat "$scope/cpuset.cpus.effective" 2>/dev/null || true)"
		fi
	fi
	printf '%s\t%s\t%s\t%s\n' "$row" "$req" "$eff" "${state:-gone}" >> "$OUT/placement.tsv"
	[ "$ARM" != main ] || repin "$name"
	# one that has already ended has no scope to read: the row says so, the judge names it, and nothing is stopped for it
	[ "$state" = true ] || return 0
	_g1_on_cores "$req" "$CONT_CORES" && _g1_on_cores "$eff" "$CONT_CORES"
}
sim_lists_services() {
	local s
	for s in "${SIM_SERVICES[@]}"; do grep -qxF "$s" <<< "$1" || return 1; done
}
container_alive() {   # NAME FACT: PR's dated section, item 2: dead only on docker's own answer; its stderr apart, so that a warning beside true is no death
	local out rc=0 err
	out="$(timeout 60 docker inspect -f '{{.State.Running}}' "$1" 2> "$WORK/inspect.err")" || rc=$?
	if [ "$rc" = 0 ]; then [ "$out" = true ]; return; fi
	err="$(cat "$WORK/inspect.err" 2>/dev/null)"
	# docker's words for a container that is not there, in either client's wording and whatever their case; the client's words for a socket file that
	# is gone hold `no such file or directory` and say nothing of a container, so they are no answer
	case "${err,,}" in *"no such object"*|*"no such container"*) return 1 ;; esac
	arm "$2" "exit $rc"
	return 0
}
sim_alive() { container_alive aw-sim sim_inspect_unanswered; }
loop_end() {   # REASON: the loop is over
	arm loop_end "$1"
	arm loop_end_mono_ns "$(mono)"
}
containers_up() {   # sets the array AWC; 1 when one is off {3,5}
	local out t0 end n=0 up=false rc=0 a
	AWC=(--label "$RUN_LABEL" --network host --user aw --group-add "$(id -g)" --cap-drop ALL --security-opt no-new-privileges
		--entrypoint /sdv-aw/aw-entrypoint.sh -v "$AW:/sdv-aw:ro" -v "$WORK/dds:/sdv-dds:ro" --cpuset-cpus "$CONT_CORES"
		-e "ROS_DOMAIN_ID=${G1_DDS%% *}" -e "RMW_IMPLEMENTATION=${G1_DDS#* }" -e CYCLONEDDS_URI=file:///sdv-dds/cyclonedds.xml
		-e ROS_LOG_DIR=/sdv-ros-log -e PYTHONDONTWRITEBYTECODE=1)
	for a in aw-sim aw-claim-node aw-g1-count aw-g1-diag aw-scenario; do install -d -m 0775 "$WORK/ros-log/$a"; done
	cp -f "$VMSTAT" "$OUT/vmstat-before.txt" || arm vmstat_before_read false
	: > "$WORK/state/began"
	t0="$(mono)"
	arm first_container_mono_ns "$t0"
	# the planning simulator
	timeout 120 docker run -d --name aw-sim "${AWC[@]}" --memory "$MEM_SIM" --memory-swap "$MEM_SIM" -v "$WORK/ros-log/aw-sim:/sdv-ros-log" \
		-v "$MAPS:/sdv-map:ro" "$G1_REF" ros2 launch autoware_launch planning_simulator.launch.xml "map_path:=/sdv-map/$G1_MAP" \
		vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit rviz:=false > "$WORK/sim.id" 2> "$WORK/sim.err" < /dev/null || rc=$?
	arm sim_run_exit "$rc"
	[ "$rc" = 0 ] || run_refuse aw-sim "$rc" "$WORK/sim.err"
	after_start aw-sim || return 1
	# the one-clock check: a pair read in one action on each side, so a container's start-up time does not enter it
	{ echo "host $(python3 "$TOOL" now)"
	  echo "container $(timeout 120 docker exec aw-sim python3 -c 'import time; print(time.monotonic_ns(), time.time_ns())' \
		2>/dev/null < /dev/null || true)"; } > "$OUT/clock-pairs.txt"
	# its services: a bound on the wait from its docker run and no more (the first drive is what reads a simulator that is not up)
	end=$(( t0 + SIM_UP_S * 1000000000 ))
	while :; do
		n=$((n + 1))
		out="$(timeout 60 docker exec aw-sim /sdv-aw/aw-entrypoint.sh ros2 service list 2>/dev/null < /dev/null)" || out=""
		if sim_lists_services "$out"; then up=true; break; fi
		sim_alive || break
		[ "$(mono)" -lt "$end" ] || break
		[ ! -e "$STOP" ] || break
		sleep "$SIM_POLL_S"
	done
	arm sim_up "$up"
	arm sim_polls "$n"
	arm sim_up_s "$(( ($(mono) - t0) / 1000000000 ))"
	# the claim node, before the driver sets the route (W4 G2); the guest-stopped arm's count recorder in its place
	rc=0
	if [ "$ARM" = main ]; then
		install -d -m 0775 "$OUT/claim"
		timeout 120 docker run -d --name aw-claim-node "${AWC[@]}" --memory "$MEM_OTHER" --memory-swap "$MEM_OTHER" \
			-v "$WORK/ros-log/aw-claim-node:/sdv-ros-log" -v "$CTL:/sdv/sdv/ctl:ro" -v "$VSS_HOME/gen:/sdv-gen:ro" \
			-v "$OUT/claim:/sdv-claim" "$G1_REF" python3 /sdv/sdv/ctl/ctl_claim_node.py --host "$GUEST" --port "$CLAIM_PORT" \
			--contract /sdv-gen/vss_ctl.py --out /sdv-claim/run > /dev/null 2> "$WORK/claim.err" < /dev/null || rc=$?
		arm claim_run_exit "$rc"
		[ "$rc" = 0 ] || run_refuse aw-claim-node "$rc" "$WORK/claim.err"
		after_start aw-claim-node || return 1
	else
		install -d -m 0775 "$OUT/count"
		timeout 120 docker run -d --name aw-g1-count "${AWC[@]}" --memory "$MEM_OTHER" --memory-swap "$MEM_OTHER" \
			-v "$WORK/ros-log/aw-g1-count:/sdv-ros-log" -v "$OUT/count:/sdv-count" "$G1_REF" \
			python3 /sdv-aw/aw_g1_count.py --out /sdv-count/arrivals.jsonl > /dev/null 2> "$WORK/count.err" < /dev/null || rc=$?
		arm count_run_exit "$rc"
		[ "$rc" = 0 ] || run_refuse aw-g1-count "$rc" "$WORK/count.err"
		after_start aw-g1-count || return 1
	fi
	# the diagnostics recorder (PR section 7)
	rc=0
	install -d -m 0775 "$OUT/diag"
	timeout 120 docker run -d --name aw-g1-diag "${AWC[@]}" --memory "$MEM_OTHER" --memory-swap "$MEM_OTHER" \
		-v "$WORK/ros-log/aw-g1-diag:/sdv-ros-log" -v "$OUT/diag:/sdv-diag" "$G1_REF" \
		python3 /sdv-aw/aw_g1_diag.py --out /sdv-diag/diag.jsonl > /dev/null 2> "$WORK/diag.err" < /dev/null || rc=$?
	arm diag_run_exit "$rc"
	[ "$rc" = 0 ] || run_refuse aw-g1-diag "$rc" "$WORK/diag.err"
	after_start aw-g1-diag || return 1
}

# --- the loop ---------------------------------------------------------------------------------------------------------------
# PR's dated section, item 15: the driver's own file, a whole line of one number, holds its exit; the line's end is what says it is whole
exit_number() {   # FILE: sets DRIVE_RC; 1 when no number stands there yet
	local n=""
	[ -r "$1" ] || return 1
	IFS= read -r n < "$1" || return 1
	[[ "$n" =~ ^[0-9]+$ ]] || return 1
	DRIVE_RC="$n"
}
# One look's wait, with no process started: a builtin read on a pipe nothing writes (the_loop's IDLE_FD) ends by its timeout. This sits inside every
# drive, where the harness is otherwise blocked in one `docker wait`, so a fork per look would be a process a second on the host for the whole arm.
# Where the pipe is not there the read fails at once, so `sleep`: a wait, never a spin
exit_poll_wait() {
	local rc=0
	read -r -t "$EXIT_POLL_S" -u "${IDLE_FD:-}" _ 2>/dev/null || rc=$?
	[ "$rc" -gt 128 ] || sleep "$EXIT_POLL_S"
}
# PR's dated section, item 15, which reads item 12 for a resident driver: sets DRIVE_RC, the driver's exit or the drive's 124 or docker's code for
# a container that ended with no number; DRIVE_GONE 1 when the next drive needs another container; or DRIVE_NO_EXIT, the row's word when no exit
# was read. WAIT_PID is the `docker wait` held open for this drive
read_drive_exit() {   # DNNN
	local file="$OUT/drives/$1/$EXIT_FILE" rc=0 out
	while kill -0 "$WAIT_PID" 2>/dev/null; do
		if exit_number "$file"; then
			kill "$WAIT_PID" 2>/dev/null || true
			wait "$WAIT_PID" 2>/dev/null || true
			return 0
		fi
		exit_poll_wait
	done
	wait "$WAIT_PID" || rc=$?
	if exit_number "$file"; then return 0; fi   # written before the container ended or the bound expired: a number from the driver's file
	out="$(cat "$WORK/wait.out" 2>/dev/null)" || out=""
	if [ "$rc" = 0 ] && [[ "$out" =~ ^[0-9]+$ ]]; then   # it ended, and no number was written: that drive's reading with docker's code
		DRIVE_RC="$out"
		DRIVE_GONE=1
		return 0
	fi
	if [ "$rc" != 124 ]; then
		DRIVE_NO_EXIT="docker-wait-exit-$rc"
		return 0
	fi
	# the bound expired, and a dockerd that hangs rather than exits lands here too: only docker's answer makes this the drive's reading
	out="$(timeout 60 docker inspect -f '{{.State.Running}}' aw-scenario 2>/dev/null)" || out=""
	if [ "$out" = true ]; then
		DRIVE_RC=124
		DRIVE_GONE=1
		return 0
	fi
	if [ "$out" = false ]; then   # it ended under the bound
		out="$(timeout 60 docker inspect -f '{{.State.ExitCode}}' aw-scenario 2>/dev/null)" || out=""
		if [[ "$out" =~ ^[0-9]+$ ]]; then
			DRIVE_RC="$out"
			DRIVE_GONE=1
			return 0
		fi
	fi
	DRIVE_NO_EXIT=docker-wait-bound-no-answer
}
driver_end() {   # its log kept in a directory the login owns (drives/ is the login's; drives/$name the container's user's), and the container removed
	timeout 60 docker logs aw-scenario > "$OUT/drives/driver-$DRIVER_FROM.log" 2>&1 || true
	timeout 120 docker rm -f aw-scenario > /dev/null 2>&1 || true
	DRIVER_UP=0
}
# PR's dated section, item 15: the driver's one start, and item 2's `docker run -d` of a drive is that start. K DNNN: DRIVE_NOT_RUN 1 when it did
# not start, DRIVE_OFF 1 when its container is off {3,5}. A word a driver now gone never took is removed first, or it would start the new one
driver_start() {
	local k="$1" rc=0
	local -a flag=()
	[ "$ARM" != main ] || flag=(--require-claim-node)
	rm -f "$WORK/serve/go"
	timeout 120 docker run -d --name aw-scenario "${AWC[@]}" --memory "$MEM_OTHER" --memory-swap "$MEM_OTHER" \
		-v "$WORK/ros-log/aw-scenario:/sdv-ros-log" -v "$CTL:/sdv/sdv/ctl:ro" -v "$MAPS:/sdv-map:ro" -v "$OUT/drives:/sdv-scn" \
		-v "$WORK/serve:/sdv-serve" "$G1_REF" python3 /sdv/sdv/ctl/aw_scenario.py --scenario "/sdv/sdv/ctl/scenarios/$SCENARIO.json" \
		--map-dir "/sdv-map/$G1_MAP" --out /sdv-scn --serve /sdv-serve/go ${flag[@]+"${flag[@]}"} > /dev/null 2> "$WORK/drive.err" < /dev/null || rc=$?
	if [ "$rc" != 0 ]; then   # PR's dated section, item 2: no driver ran, so this exit is no driver's
		DRIVE_NOT_RUN=1
		printf 'stopped\t%d\tdocker-run-exit-%d\n' "$k" "$rc" >> "$OUT/drives.tsv"
		arm drive_run_err "$(tail -n 1 "$WORK/drive.err" 2>/dev/null | tr -d '\r')"
		timeout 120 docker rm -f aw-scenario > /dev/null 2>&1 || true
		return 0
	fi
	DRIVER_UP=1
	DRIVER_FROM="$2"
	if ! after_start aw-scenario; then
		DRIVE_OFF=1
		printf 'stopped\t%d\t%s\n' "$k" "its container is off {$CONT_CORES}" >> "$OUT/drives.tsv"
		driver_end
	fi
}
# K: one drive; DRIVE_END_NS its end on the harness's clock, DRIVE_OFF 1 when the driver's container was off {3,5}, DRIVE_NOT_RUN 1 when it never
# began, DRIVE_NO_EXIT as read_drive_exit says
drive() {
	local k="$1" name
	name="$(printf 'd%03d' "$k")"
	DRIVE_OFF=0
	DRIVE_NOT_RUN=0
	DRIVE_NO_EXIT=""
	DRIVE_GONE=0
	printf 'begin\t%d\t%s\n' "$k" "$(mono)" >> "$OUT/drives.tsv"
	if [ "$DRIVER_UP" = 1 ] && ! container_alive aw-scenario driver_inspect_unanswered; then
		arm driver_ended_between_drives "$name"
		driver_end
	fi
	if [ "$DRIVER_UP" = 0 ]; then
		driver_start "$k" "$name"
		if [ "$DRIVE_NOT_RUN" = 1 ] || [ "$DRIVE_OFF" = 1 ]; then return 0; fi
	fi
	timeout "$DRIVE_BOUND_S" docker wait aw-scenario > "$WORK/wait.out" 2>/dev/null < /dev/null &
	WAIT_PID=$!
	printf '%s\n' "$name" > "$WORK/serve/go.tmp"
	mv -f "$WORK/serve/go.tmp" "$WORK/serve/go"
	read_drive_exit "$name"
	if [ "$DRIVE_GONE" = 1 ] || [ -n "$DRIVE_NO_EXIT" ]; then driver_end; fi
	timeout 120 sync || true
	DRIVE_END_NS="$(mono)"
	if [ -n "$DRIVE_NO_EXIT" ]; then
		printf 'stopped\t%d\t%s\n' "$k" "$DRIVE_NO_EXIT" >> "$OUT/drives.tsv"
		return 0
	fi
	printf 'end\t%d\t%d\t%s\n' "$k" "$DRIVE_RC" "$DRIVE_END_NS" >> "$OUT/drives.tsv"
}
the_loop() {
	local k=0 first=""
	install -d -m 0775 "$OUT/drives" "$WORK/serve"
	exec {IDLE_FD}<> <(:) || IDLE_FD=""
	if [ -n "${G1_REHEARSAL_FLOOR_KB:-}" ]; then   # the rehearsal's kill unit: containers are there for the floor's first read
		watchdog_start "$(( $(vss_cap_s) + RECORDER_MARGIN_S ))" || arm rehearsal_watchdog_start false
	fi
	while :; do
		if [ -e "$STOP" ]; then loop_end watchdog-stop; return 0; fi
		if vss_past_stop; then loop_end deadline; return 0; fi
		if ! sim_alive; then loop_end sim-died; return 0; fi
		if ! watchdog_lives; then loop_end watchdog-dead; return 0; fi
		k=$((k + 1))
		drive "$k"
		if [ "$DRIVE_OFF" = 1 ]; then loop_end misplaced; return 0; fi
		if [ "$DRIVE_NOT_RUN" = 1 ]; then
			if [ -e "$STOP" ]; then loop_end watchdog-stop; else loop_end docker-run-failed; fi
			return 0
		fi
		if [ -n "$DRIVE_NO_EXIT" ]; then
			if [ -e "$STOP" ]; then loop_end watchdog-stop; else loop_end docker-wait-failed; fi
			return 0
		fi
		if [ "$k" = 1 ]; then
			if ! first="$(python3 "$TOOL" first-route --file "$OUT/drives/d001/scenario.jsonl")"; then
				loop_end first-no-route
				return 0
			fi
			arm first_route_mono_ns "$first"
		fi
		if [ $((DRIVE_END_NS - first)) -ge "$LOOP_NS" ]; then loop_end reached; return 0; fi
	done
}
end_reads() {   # at the loop's end, before any docker stop (PR section 5, T1)
	local name dir n a
	cp -f "$VMSTAT" "$OUT/vmstat-end.txt" || arm vmstat_end_read false
	: > "$OUT/memory-events-end.tsv"
	while IFS=$'\t' read -r name dir; do
		n="$(awk '$1 == "oom_kill" { print $2 }' "$dir/memory.events" 2>/dev/null || true)"
		printf '%s\t%s\n' "$name" "${n:-gone}" >> "$OUT/memory-events-end.tsv"
	done < <(awk '!seen[$0]++' "$SCOPES")
	for a in aw-sim aw-claim-node aw-g1-count aw-g1-diag aw-scenario; do
		# docker's empty line beside its error is no value and must not split the row: `none`, the named value, whenever docker gave none
		n="$(timeout 30 docker inspect -f '{{.State.OOMKilled}}' "$a" 2>/dev/null)" || n=""
		case "$n" in true|false) ;; *) n=none ;; esac
		arm "oomkilled_$a" "$n"
	done
}
stops() {   # the containers stopped, the recorder before the simulator, so that aw-sim's end is no line of its; then the removals
	local rc=0
	if [ "$ARM" = main ]; then
		timeout 120 docker stop -t "$STOP_CLAIM_S" aw-claim-node > /dev/null 2>&1 || rc=$?
		arm claim_stop_exit "$rc"
		timeout 60 docker logs aw-claim-node > "$OUT/claim-node.log" 2>&1 || true
	else
		timeout 120 docker stop -t "$STOP_CLAIM_S" aw-g1-count > /dev/null 2>&1 || rc=$?
		arm count_stop_exit "$rc"
	fi
	rc=0; timeout 120 docker stop -t "$STOP_DIAG_S" aw-g1-diag > /dev/null 2>&1 || rc=$?
	arm diag_stop_exit "$rc"
	rc=0; timeout 120 docker stop -t "$STOP_SIM_S" aw-sim > /dev/null 2>&1 || rc=$?
	arm sim_stop_exit "$rc"
	if [ "$DRIVER_UP" = 1 ]; then   # last: no participant leaves while a frame can still be counted (T6 reads the whole arm)
		rc=0; timeout 120 docker stop -t "$STOP_DRIVER_S" aw-scenario > /dev/null 2>&1 || rc=$?
		arm driver_stop_exit "$rc"
		timeout 60 docker logs aw-scenario > "$OUT/drives/driver-$DRIVER_FROM.log" 2>&1 || true
	fi
	arm last_stop_mono_ns "$(mono)"
	timeout 120 docker rm -f "${G1_CONTAINERS[@]}" > /dev/null 2>&1 || true
}
arm_child() {   # the arm, under its cap: everything from the guest's boot to the last removal
	ARM="$G1_ARM"
	if [ "$ARM" = main ]; then guest_up; else guest_idle_read; arm console_arm_from 0; fi
	if containers_up; then
		the_loop
	else
		loop_end misplaced
	fi
	end_reads
	stops
}

# --- the preflight ----------------------------------------------------------------------------------------------------------
refuse() { finish FAILED preflight "$*"; }
preflight() {
	local groups out f ids rc=0
	case "${PLAN:-}" in
		main|rehearsal) ARM=main ;;
		guest-stopped) ARM=guest-stopped ;;
		*) refuse "PLAN='${PLAN:-}' is not main, guest-stopped or rehearsal" ;;
	esac
	arm plan "$PLAN"
	arm arm "$ARM"
	[ "$PLAN" != rehearsal ] || [ "$HOST_MODE" = c7g-metal ] \
		|| refuse "PLAN=rehearsal is c7g-metal's (spec.md section 7), and VSS_HOST is '$HOST_MODE'"
	if [ -n "${G1_REHEARSAL_FLOOR_KB:-}" ]; then
		[ "$HOST_MODE" != orin ] \
			|| refuse "G1_REHEARSAL_FLOOR_KB is refused under VSS_HOST=orin: the override is the rehearsal's (spec.md section 7)"
		arm rehearsal_floor_kb "$G1_REHEARSAL_FLOOR_KB"
	fi
	case "${G1_RERUN_AFTER:-}" in
		''|reset|not-judged) ;;
		*) refuse "G1_RERUN_AFTER='${G1_RERUN_AFTER}' is not reset or not-judged (aw_g1.py judge's words)" ;;
	esac
	[ -z "${G1_RERUN_AFTER:-}" ] || [ -n "${G1_RERUN_OF:-}" ] \
		|| refuse "G1_RERUN_AFTER='${G1_RERUN_AFTER}' without G1_RERUN_OF: the record's header says what the arm is a re-run of"
	if [ -n "${G1_RERUN_OF:-}" ]; then arm rerun_of "$G1_RERUN_OF"; arm rerun_after "${G1_RERUN_AFTER:-}"; fi
	groups="$(id -nG 2>/dev/null)" || groups=""
	case " $groups " in
		*" docker "*) ;;
		*) refuse "this login is not in the docker group (the helper's g1-setup, or run-vss-setup.sh, adds it for the next login)" ;;
	esac
	if guest_runs; then refuse "a QEMU runs already: the guest this harness boots would be a second one (it is not stopped here)"; fi
	if [ "$ARM" = main ]; then
		[ "$(basename "$IFS_BIN")" = ifs-ctl.bin ] \
			|| refuse "IFS_BIN is $(basename "$IFS_BIN"), not ifs-ctl.bin: G1's guest is WP5's image, which serves kind 2 on :7150"
		[ -r "$IFS_BIN" ] && [ -r "$DISK" ] && [ -r "$LAUNCH" ] || refuse "IFS_BIN, DISK or the launch script is not readable"
	fi
	for f in "$AW/aw-entrypoint.sh" "$HC" "$AW/ros-env.json" "$AW/g1_watchdog.py" "$AW/g1_sampler.py" "$AW/aw_g1_diag.py" \
		"$AW/aw_g1_count.py" "$CTL/ctl_claim_node.py" "$CTL/aw_scenario.py" "$CTL/ctlsynth.py" "$SCN" "$IMAGES"; do
		[ -r "$f" ] || refuse "the tree lacks ${f#"$REPO/"}"
	done
	[ -x "$AW/aw-entrypoint.sh" ] || refuse "sdv/aw/aw-entrypoint.sh is not executable: --entrypoint runs it by its path"
	REF="$(python3 "$SETUP_TOOL" ref --images "$IMAGES" 2>&1)" || refuse "sdv/stack/images.json: $REF"
	DIGEST="$(python3 "$SUITE_TOOL" contract --file "$CONTRACT" --facts "$WORK/facts/preflight" 2>&1)" || refuse "$DIGEST"
	arm ctl_digest "$DIGEST"
	MAP_NAME="$(python3 "$SUITE_TOOL" map-check --map-dir "$MAPS" --scenario "$SCN" --facts "$WORK/facts/preflight/map" 2>&1)" \
		|| refuse "the staged map: $MAP_NAME"
	rc=0; out="$(timeout 120 docker image inspect "$REF" 2>&1)" || rc=$?
	[ "$rc" = 0 ] || refuse "the image $REF is not in the image store (docker image inspect exited $rc): the helper's g1-setup," \
		"or run-aw-setup.sh, pulls it"
	printf '%s\n' "$out" | python3 "$SETUP_TOOL" inspect --ref "$REF" --facts "$WORK/facts/preflight/image" > "$WORK/inspect.why" 2>&1 \
		|| refuse "$(cat "$WORK/inspect.why")"
	arm image "$REF"
	DDS_ENV="$(python3 "$SETUP_TOOL" dds --env "$AW/ros-env.json" --out "$WORK/dds/cyclonedds.xml" 2>&1)" || refuse "$DDS_ENV"
	rc=0; ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
	[ "$rc" = 0 ] || refuse "the containers labelled $LABEL cannot be listed (docker ps exit $rc)"
	# shellcheck disable=SC2086  # the IDs are words
	[ -z "$ids" ] || refuse "a container labelled $LABEL is still there ($(printf '%s ' $ids)): this harness's names would collide"
	host_check_before
	arm graphical_target "$(_unit_word is-active graphical.target)"   # PR section 3: the graphical session as booted, recorded
	say "preflight: PLAN=$PLAN, arm $ARM, host $HOST_MODE, the image $REF in the store, ctl contract $DIGEST"
}

governor_read() {   # WHEN: the helper's pin read on every core (the stamp's fields), changed by nothing here; absent with no cpufreq
	local c now all=performance
	if [ ! -r "$SYSFS_CPU/cpu0/cpufreq/scaling_governor" ]; then GOV_STATE=absent; return 0; fi
	for c in "$SYSFS_CPU"/cpu[0-9]*/cpufreq/scaling_governor; do
		now="$(cat "$c" 2>/dev/null || echo unreadable)"
		[ "$now" = performance ] || all="$now"
	done
	if [ "$1" = before ]; then
		PRE_GOV="$all"; FREQ_BEFORE="$(_freq_list)"
		if [ "$all" = performance ]; then GOV_STATE=pinned; else GOV_STATE="not-pinned"; fi
	else
		GOV_AFTER="$all"; FREQ_AFTER="$(_freq_list)"
	fi
}
rehearsal_confine() {   # PLAN=rehearsal alone, before the stamp reads the daemons; the Orin's helper does this on its host
	local u rc
	[ "${PLAN:-}" = rehearsal ] || return 0
	: > "$WORK/state/confined"
	for u in "${DAEMON_UNITS[@]}"; do
		rc=0; timeout 60 sudo -n systemctl set-property --runtime "$u" "AllowedCPUs=$CONT_CORES" > "$WORK/confine.out" 2>&1 || rc=$?
		arm "rehearsal_confine_exit_$u" "$rc"
		[ "$rc" = 0 ] || finish FAILED stamp "AllowedCPUs=$CONT_CORES could not be set on $u (systemctl set-property exited $rc), so the" \
			"stamp's g1 policy cannot pass here"
	done
}
rehearsal_unconfine() {   # every core back, never an empty value; after the kill unit, which needs the property too
	local u rc all
	[ -e "$WORK/state/confined" ] || return 0
	rm -f "$WORK/state/confined"
	all="0-$(( $(nproc --all) - 1 ))"
	for u in "${DAEMON_UNITS[@]}"; do
		rc=0; timeout 60 sudo -n systemctl set-property --runtime "$u" "AllowedCPUs=$all" > "$WORK/confine.out" 2>&1 || rc=$?
		arm "rehearsal_restore_exit_$u" "$rc"
		[ "$rc" = 0 ] || say "AllowedCPUs=$all could not be restored on $u (systemctl set-property exited $rc)"
	done
}
write_stamp() {   # before any container; a refusal stops everything
	local rc=0 emc=absent
	if sudo -n cat "$EMC_BPMP" > /dev/null 2>&1; then emc=present; fi
	_g1_gpu_node                # the stamp's sampler_paths names the node the clock sampler will read
	governor_read before
	N=0; K=0; WARMUP=0; INTERVAL_MS=0; SAMPLE_WINDOW=1; NCPU="$(nproc 2>/dev/null || echo 0)"
	(
		set +e
		m_write_stamp "$OUT/stamp.json" '"harness": "run-aw-g1.sh"' "\"arm\": \"$ARM\"" "\"vss_host\": \"$HOST_MODE\"" \
			"\"emc_bpmp\": \"$emc\"" '"ladder": "none: n, k, warmup and interval_ms are 0, and 0 means no ladder"'
	) > "$OUT/stamp.out" 2>&1 || rc=$?
	arm stamp_exit "$rc"
	arm stamp_mono_ns "$(mono)"
	if [ "$rc" != 0 ]; then finish FAILED stamp "the stamp refused under PLATFORM_POLICY=g1: $(tail -n 1 "$OUT/stamp.out")"; fi
}

# --- the stops --------------------------------------------------------------------------------------------------------------
sweep() {
	local ids rc=0 left
	if [ -e "$WORK/state/launched" ]; then
		stop_guest
		rm -f "$WORK/state/launched"
	fi
	if [ -e "$WORK/state/began" ]; then
		timeout 120 docker rm -f "${G1_CONTAINERS[@]}" >/dev/null 2>&1 || true
		ids="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null)" || rc=$?
		if [ "$rc" != 0 ]; then
			arm stop_unverified "the containers labelled $LABEL could not be listed (docker ps exit $rc): the names were removed unseen"
		elif [ -n "$ids" ]; then
			# shellcheck disable=SC2086  # the IDs are words
			timeout 120 docker rm -f $ids >/dev/null 2>&1 || true
			left="$(timeout 60 docker ps -aq --filter "label=$LABEL" 2>/dev/null | grep -c . || true)"
			arm containers_left "$left"
			[ "$left" = 0 ] || arm stop_unverified "$left container(s) labelled $LABEL still listed after the removals"
		fi
	fi
}
rehearsal_kill_unit() {   # The rehearsal's short unit under a floor above MemAvailable, to prove the kill path; its figures are nobody's
	local avail="" rc=0
	avail="$(python3 "$SETUP_TOOL" meminfo --file "$MEMINFO" 2>/dev/null)" || avail=""
	if ! [[ "$avail" =~ ^[0-9]+$ ]]; then   # no floor can be set above a value not read; the main arm's verdict stands
		say "the rehearsal's kill unit is refused: MemAvailable cannot be read from $MEMINFO"
		arm kill_unit_refused "MemAvailable cannot be read"
		return 0
	fi
	say "the rehearsal's kill unit: the floor above MemAvailable ($avail kB)"
	env PLAN=main OUT="$OUT/kill" STATUS="$WORK/kill.status" G1_WORK_TAG=kill G1_REHEARSAL_FLOOR_KB="$((avail + 1048576))" \
		bash "$SELF" || rc=$?
	arm kill_unit_exit "$rc"
	arm kill_unit_status "$(tail -n 1 "$WORK/kill.status" 2>/dev/null || echo none)"
}
judge() {   # 1 when aw_g1.py judge could not run
	local rc=0
	local -a a=(--rec "$OUT" --out "$OUT")
	[ -z "$ARM" ] || a+=(--arm "$ARM")
	if [ -n "${G1_RERUN_OF:-}" ]; then
		a+=(--rerun-of "$G1_RERUN_OF")
		case "${G1_RERUN_AFTER:-}" in reset|not-judged) a+=(--rerun-after "$G1_RERUN_AFTER") ;; esac   # another word is the preflight's refusal
	fi
	python3 "$TOOL" judge "${a[@]}" > "$WORK/judge.out" 2>&1 || rc=$?
	[ "$rc" = 0 ] || say "aw_g1.py judge could not run: $(tail -n 1 "$WORK/judge.out")"
	grep -E '^(T[0-9]w? |instrument |verdict:|re-run:)' "$WORK/judge.out"
	return "$rc"
}
to_record_failed() {   # WHY: a DONE that has no verdict or no g1.json is no DONE (run-aw-suite.sh's at=record)
	arm outcome_before_record "$line"
	st=FAILED; at=record; line="status=FAILED at=record"; why="$1"
	arm harness_end "$line"
}
finish() {   # STATUS [AT [REASON]]: the sweep, the recorders, the host check, the stamp's end, the judge, the record, the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line
	trap - EXIT
	set +e
	timeout 120 sync
	sweep
	grep -q '^last_stop_mono_ns	' "$OUT/arm.tsv" 2>/dev/null || [ ! -e "$WORK/state/began" ] || arm last_stop_mono_ns "$(mono)"
	arm arm_pair_end "$(python3 "$TOOL" now)"
	recorders_stop
	case "$st" in
		DONE) line="status=DONE" ;;
		TIMEOUT) line="status=TIMEOUT at=$at reason=$why" ;;
		*) line="status=FAILED at=$at" ;;
	esac
	if ! host_check_after; then
		arm outcome_before_host_check "$line"
		st=FAILED; at=host-check; line="status=FAILED at=host-check"
		why="2.12's host check after the sweep: a setting changed, or it could not be read"
	fi
	governor_read after
	[ ! -s "$OUT/stamp.json" ] || ( m_stamp_after "$OUT/stamp.json" ) >> "$OUT/stamp.out" 2>&1 || say "the stamp's end could not be appended"
	arm harness_end "$line"
	[ -z "$why" ] || arm harness_why "$(printf '%s' "$why" | tr '\n\t' '  ')"
	if ! judge && [ "$st" = DONE ]; then to_record_failed "aw_g1.py judge could not run, so this record has no verdict"; fi
	if ! python3 "$TOOL" record --rec "$OUT" --out "$OUT/g1.json" --status "$st" --status-line "$line" --at "$at" --reason "$why" \
		--host-mode "${HOST_MODE:-unset}" --plan "${PLAN:-}" --work "$WORK"; then
		say "g1.json could not be written"
		if [ "$st" = DONE ]; then to_record_failed "g1.json could not be written"; fi
	fi
	[ "$st" != FAILED ] || say "FAILED at $at: $why"
	if [ "$st" = DONE ] && [ "${PLAN:-}" = rehearsal ]; then rehearsal_kill_unit; fi
	rehearsal_unconfine
	[ -z "${FRESH_WORK:-}" ] || rm -rf "$FRESH_WORK"
	timeout 120 sync   # the record, the verdict and g1.json are written: one more, before the status line
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
	local why rc=0 end=""
	CUR=preflight
	mkdir -p "$OUT"
	if [ -e "$OUT/arm.tsv" ]; then
		say "$OUT already holds an arm's record: refusing to mix runs. Use a new OUT."
		vss_status FAILED at=preflight
		exit 1
	fi
	trap on_exit EXIT
	if ! why="$(rm -rf "$WORK" 2>&1)"; then
		# what is left of it may hold an earlier arm's markers and pids, on which finish must not act: it works from a directory of its own
		FRESH_WORK="$(mktemp -d)"
		WORK="$FRESH_WORK"
		mkdir -p "$WORK/facts" "$WORK/state"
		refuse "the working directory under VSS_HOME cannot be removed (aw-g1-work${G1_WORK_TAG:+-$G1_WORK_TAG}; a container's user may own part of" \
			"it, and the owner decides, or G1_WORK_TAG gives this arm another): $(printf '%s' "$why" | tail -n 1)"
	fi
	mkdir -p "$WORK/facts" "$WORK/state"
	say "run-aw-g1.sh PLAN=${PLAN:-}: one arm of gate G1 under sdv/aw/prereg-g1g2.md"
	why="$(host_refusal)"
	[ -z "$why" ] || refuse "$why"
	if ! vss_deadline_load; then refuse "no readable deadline file (lib-vss-deadline.sh)"; fi
	preflight
	CUR=stamp
	rehearsal_confine
	write_stamp
	CUR=recorders
	recorders_start
	CUR=arm
	if vss_past_stop; then arm loop_end deadline; finish TIMEOUT arm deadline; fi
	rc=0
	vss_capped env G1_ARM="$ARM" G1_REF="$REF" G1_DIGEST="$DIGEST" G1_DDS="$DDS_ENV" G1_MAP="$MAP_NAME" bash "$SELF" _arm < /dev/null \
		|| rc=$?
	if vss_cap_fired "$rc"; then
		grep -q '^loop_end	' "$OUT/arm.tsv" || arm loop_end deadline
		finish TIMEOUT arm step-timeout
	fi
	if [ -e "$WORK/state/guest-refused" ]; then finish FAILED guest "$(cat "$WORK/state/guest-refused")"; fi
	if [ -e "$WORK/state/arm-refused" ]; then finish FAILED arm "$(cat "$WORK/state/arm-refused")"; fi
	[ "$rc" = 0 ] || finish FAILED arm "the arm's child exited $rc"
	end="$(sed -n 's/^loop_end\t//p' "$OUT/arm.tsv" | tail -n 1)"
	[ "$end" != deadline ] || finish TIMEOUT arm deadline
	finish DONE
}

case "${1:-}" in
	_arm) vss_deadline_load || exit 1; arm_child; exit 0 ;;   # the arm, under its cap
esac
main
