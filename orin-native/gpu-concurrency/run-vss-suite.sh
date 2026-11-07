#!/usr/bin/env bash
# KVM here boots our startup-qemu-virt; this is not a QNX-supported
# configuration, and no timing claim attaches to the boot.
# run-vss-suite.sh -- the VSS slice's functional suite on a bare-metal AWS instance: each planned run boots the QNX guest
# (ifs-vss.bin) afresh and makes one step-3 call, judged by the guest's vss monitor on :7160; then the plan's comparisons.
# plan Phase 3 (WP5), 2026-10-03; with VSS_HOST=orin, on
# the Jetson Orin instead (plan Phase 5 WP2, 2026-10-17: THE MODES).
# A functional session: no field of its record is a measurement.
#
# HOW IT RUNS. Only as remote-ladder.sh's harness phase starts it, detached, in a vss session (scripts/aws/README.md, "A
# vss session instead"): LADDER_ENV="HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1|v2" (PLAN=carla with
# IMAGE=ifs-vss-carla.bin, SDV Phase 7 WP3b), once per session, after run-vss-setup.sh ended status=DONE, from a new login
# (the docker group that setup added applies from the next login). The detached runner runs it from $R =
# $W/repo/orin-native/gpu-concurrency with stdout and stderr in
# rec/vss-suite/run.log and SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored (a unit under its cap starts with only SIGPIPE
# of them ignored: remote-ladder.sh, SIGNALS), then reads its last status line. Its environment:
#   W        the session's directory (~/a1): repo/ (the vss tarball), rec/vss-setup (setup's record)
#   IFS_BIN  the session's METAL_IFS, ifs-vss.bin (IMG_S and IMG_B are the same path); DISK the guest disk
#   OUT      rec/vss-suite/raw, where every record below goes; PLAN v1, v2 or carla
#   VSS_HOME $W/sdv, what setup staged: gen/, cache/ (dbc/<sha256>.dbc), venv/, recordings/<name>/; and suite-work/, this
#            harness's own working files (never captured)
#   STATUS   rec/vss-suite/status, the status file (lib-vss-deadline.sh's vss_status writes it)
# VSS_IN, VPROBE and CSTATE come with the phase's environment and are not used here. QNX_METAL_DEADLINE_FILE overrides the
# deadline file for the tests, and names it in the Orin mode.
#
# THE MODES (plan Phase 5 WP2). VSS_HOST unset or a1-metal is the a1.metal path
# this header describes, every stubbed command and every file as before (a test holds an a1.metal run stub call for stub
# call and file for file to the reference harness). VSS_HOST=orin is the Orin mode, the harness started by the board's private
# helper (under `sg docker`, which gives the docker group the preflight asks for). VSS_HOST=c7g-metal (2026-10-17) is the
# a1.metal path on AWS c7g.metal: every step and call as a1-metal's, but step 3's SDV_HOST_ROLE is c7g-metal, the
# preflight takes only a setup.json whose host_mode is c7g-metal (and an a1.metal suite refuses one), suite.json says
# host_mode c7g-metal (container_cpuset null) and run.log names the mode in one line. Any other value, an empty one
# included, is refused before the preflight (status=FAILED at=preflight); so is the a1.metal path, either word, on a
# host L4T marks as a Jetson (run-vss-setup.sh, THE MODES).
#
# ORIN MODE. Before the preflight, run-vss-setup.sh's checks (`vss_suite.py orin-check`, which is vss_setup.py's:
# VSS_REPIN, SDV_CONTAINER_CPUSET, QNX_METAL_DEADLINE_FILE, system.slice's cpuset controller); in it, a setup.json whose
# host_mode is orin (an a1.metal setup records none; the a1.metal path refuses one that records orin). Then:
#   step 3's environment  SDV_HOST_ROLE=orin, and for the stack SDV_CONTAINER_CPUSET (every container it starts placed by
#                         it) and SDV_AFTER_START="$VSS_REPIN" (run after each container start, the container's name
#                         appended)
#   every step-3 call     a run or a compare, under `taskset -c "$SDV_CONTAINER_CPUSET"` inside its cap: its python, the
#                         player and the capture stay off QEMU's cores and the probe's
#   after each boot       its exit 0, and before the readiness, `$VSS_REPIN boot` under the cap: QEMU's threads to their
#                         cores, recorded per run (repin_exit, repin, pinned); a pin that fails is a boot that failed
#                         (boot-failed, booted false, with why), its run skipped. A pin that fails while no run before
#                         it has been pinned (a host reason, such as sudo's rule or no taskset, fails every later pin
#                         too) stops the plan there as a guest not ready does: every later run is listed (skipped,
#                         with why) instead of booted, and suite.json's plan_stopped_after names it
# suite.json says host_mode orin and container_cpuset; its preflight holds setup_host_mode, the cpuset, VSS_REPIN's
# path and the cpuset controller.
#
# PREFLIGHT, in this order; a refusal is the one real failure of this harness: status=FAILED at=preflight, exit 1.
#   the deadline file readable; PLAN v1, v2 or carla; `id -nG` includes docker (a new login); $W/rec/vss-setup has done
#   and its status file's last status= line is exactly status=DONE (the harness phase refuses the suite otherwise too:
#   this is the suite's own guard), and raw/setup.json says DONE; its skip list read (skip_modes, skip); its guest step's
#   verdict (vss_setup.py, THE GUEST RULE): a guest that booted in setup with :7160 not ready, C12b not ok or a catalog
#   that is not the bridge's label is refused, since this suite boots the same image against the same images.json; no
#   QEMU running (one found is refused, never killed); IFS_BIN, DISK, the launch script, sdv/stack/step3.py, images.json
#   and step3-runs.json readable; VSS_HOME's gen/manifest.json, venv/bin/python, a cache/dbc/<sha256>.dbc, and each
#   recording the plan needs (v1 and v2: its sigsim.log, as before); the bridge's arm64 pin read from images.json.
#   PLAN=carla (SDV Phase 7 WP3b; vss_suite.py recordings) wants instead each of the CARLA pair's own
#   log, the one its manifest line names (vss_setup.py's log reading), and its line's profile (3) among the `vss rules:`
#   profiles setup's guest step recorded (setup.json's facts.guest.profiles): a setup whose image lists no 3, or that
#   recorded no list (its guest did not boot), is refused.
#
# STEP 3'S ENVIRONMENT: SDV_HOST_ROLE=a1-metal (c7g-metal in that mode), SDV_GEN=$VSS_HOME/gen,
#   SDV_CACHE=$VSS_HOME/cache,
#   SDV_SIM_VENV=$VSS_HOME/venv, SDV_RUNS=$OUT/runs, SDV_BRIDGE_IMAGE images.json's bridge.arm64.id (read here: an image ID
#   cannot travel in LADDER_ENV), and per run SDV_RECORDING=$VSS_HOME/recordings/<the spec's recording> (honest:
#   20260930-sigsim-1b, injected: 20261002-sigsim-1b-inj4, as step3-runs.json gives each spec's kind; under PLAN=carla
#   20261019-carla-1 and 20261019-carla-1-inj, vss_suite.py's PLAN_RECORDINGS). Every call runs
#   from $W/repo with the venv's python; its stdout and stderr go to run.log. The Orin mode's role and its two more
#   variables are under ORIN MODE.
#
# THE PLANS (vss_suite.py plan), NN the plan's sequence number:
#   v1  01-honest-replay, then 02-honest-broker (information only: read before V2). No compare.
#   v2  broker: honest inject pause-tick pause-both injected-to-end injected-stop (01-06); replay: the same six, then
#       injected-stop once more for the frame comparison (07-13); can: the same six (14-19). Then 20-compare-broker-replay
#       over the broker and replay runs, the exit; and 21-compare-broker-replay-can over all nineteen, only when every can
#       run finished (step 3 returned and left its result.json): a partial can set is coverage, not compared.
#   carla  v2's units and compares, names and order over the CARLA pair (SDV Phase 7 WP3b), on an image
#       whose `vss rules:` lines list profile 3 (ifs-vss-carla.bin).
#   A mode in setup's skip list is listed, not run (state skipped, with setup's reasons): the plan's fallback to replay.
#   A compare over a skipped mode is not run (state not-compared, with why).
#
# A RUN, in this order:
#   the check point     lib-vss-deadline.sh's: now >= stop_at stops the suite here
#   boot                launch-qnx-kvm-bridged.sh (always -snapshot), LOG=$OUT/guest/NN-<spec>-<mode>-console.log, its own
#                       output in guest/NN-<spec>-<mode>-launch.log with "guest up after Ns" losing its N (the boot's whole
#                       seconds go under operational_s). Its exit 0 is the :7100 accept. A boot that fails is recorded
#                       (boot-failed) and its run skipped
#   readiness           vss_suite.py ready: a connect-and-close with no bytes on 192.168.100.10:7160 in one step, never a held
#                       descriptor, retried within a bound, the attempt count recorded; then a settle past the guest's
#                       500 ms deadline and the console's freshness, read as step 3's gate reads it (recorded: step 3
#                       judges it again and refuses a console that fails). A probe closed in time leaves only `client done:
#                       seen=0`, which the gate allows; one held past the deadline leaves `client closed:`, which it
#                       refuses. Never the banner, which can interleave: its presence is recorded as information. No
#                       connect within the bound: not-ready, the run skipped. A run not ready while no run before it
#                       has been ready stops the plan there: every later run is listed (skipped, with why) instead of
#                       booted, and suite.json's plan_stopped_after names it. Once one run was ready, a later not-ready
#                       is recorded and the plan goes on
#   step 3              step3.py run --mode M --spec S --name NN-<spec>-<mode> --images loaded --monitor guest --guest-host
#                       192.168.100.10 --guest-console <the console> --guest-image $IFS_BIN. Each call has its own --name:
#                       step 3's default is step3-<mode>, and it refuses an existing run directory. Its exit status is
#                       recorded; a run that fails its gates (exit 1, any refusal of step 3's included), or that dies
#                       of its own before the cap's end (an OOM kill's 137: lib-vss-deadline.sh's vss_cap_fired), is a
#                       result, and the suite goes on
#   after every boot attempt, a failed one included: sync, then QEMU stopped as the stop phase does (sudo -n pkill -x
#                       qemu-system-aar, waited for, KILL if it lingers) and waited until gone: a failed boot leaves QEMU
#                       running and the next launch refuses a second one. A QEMU that outlives its KILL is recorded
#                       (qemu_stopped false), and the sweep at the stop tries once more. Then the console's sha256 and
#                       step 3's directory and result.json read (vss_suite.py run-facts)
# Each of boot, readiness and step 3 runs under its cap (stop_at + 10 minutes - now) in lib-vss-deadline.sh's call form,
# rc=0; vss_capped CMD... || rc=$?, then vss_cap_fired "$rc".
#
# A COMPARE: the check point, then step3.py compare --name NN-compare-<modes> <the run directories> --modes <modes>, under
# its cap. The run directories come BEFORE --modes, which takes every word after it. The name keeps "compare" in the
# directory, as capture.py's whitelist needs (runs/*compare*/compare.json).
#
# THE STATUS LINE, the last one in STATUS, through vss_status:
#   status=DONE                                   every unit ran or was listed (skipped, not-compared); suite.json first
#   status=TIMEOUT at=<unit> reason=deadline      a check point found now >= stop_at; <unit> and the rest did not run
#   status=TIMEOUT at=<unit> reason=step-timeout  a cap fired in <unit> (its boot, readiness, step 3 or compare)
#   status=FAILED at=preflight                    the preflight refused, or no readable deadline file
#   status=FAILED at=record                       every unit ran or was listed, but suite.json could not be written
#   status=FAILED at=<unit>                       the harness ended without a status line, through its EXIT trap (reason
#                                                 "the harness stopped unexpectedly", at the unit it was in)
# Every FAILED exits 1, a TIMEOUT 0. Every stop sweeps before its record, DONE included: QEMU stopped if this harness
# launched it, and after any step-3 call every container labelled sdv.stack.run removed with docker rm -f (a step 3 cut by
# its cap, or killed by a death of its own, leaves its stack up). When those cannot be listed the sweep says so in run.log,
# records containers_removed false, and removes the stack's own container names (STACK_CONTAINERS: stack.py's CONTAINERS),
# which needs no listing. Its facts go under suite.json's stop. A QEMU that outlives its KILL, containers that cannot be
# listed or a removal that fails records the stop unverified (stop.verified false, with why under stop.unverified) and
# says so in run.log; the status line is not changed. Every stop but DONE syncs first; the units not run go to run.log and
# suite.json, and suite.json is written in every case. Results, not failures: a run that fails its gates, a guest that
# does not boot or answer, a compare that fails are recorded, and the suite ends DONE.
#
# THE RECORD, in OUT (each name on capture.py's vss whitelist): suite.json (written whole, a temporary file then a rename,
# before the status line), guest/ (each run's console and launch log), runs/ (SDV_RUNS: step 3's own directories).
# suite.json holds, per run: NN, name, spec, mode, recording, state, step 3's exit status, ok, the gates of its
# result.json, the console's sha256, the readiness's attempts, freshness and banner, and the boot's and step 3's whole
# seconds under operational_s; per compare its modes, directories, exit status, ok and each group's ok and problems; the
# preflight's facts (setup's guest verdict under setup_guest); the skip list; plan_stopped_after; the sweep's facts under
# stop; the status. Every string is one line, and a record-level note says that no field is a measurement: Docker is
# up and nothing is pre-registered. Docker runs plain here (the docker group); only pkill runs under sudo -n, and in the
# Orin mode vss-repin.sh's taskset.
#
# DESIGN VALUES (not measured): the readiness's attempts, bound, gap and settle (30, 3 s, 1 s, 1 s: the settle is past the
# guest's 500 ms deadline); the guest's stop (10 s, then KILL and 10 s more).
#
# WHAT IT DOES NOT SHOW: any timing (the operational_s values are whole seconds of this session's own units, with Docker up);
# anything step 3's gates do not judge; physical CAN; any isolation or certification. In the Orin mode: that QEMU stays
# on its cores between two re-pins, or that a container stays on its cpuset beyond the flag the stack gives it. That
# step 3 refused or failed a run says what step 3's record says, nothing more.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
: "${W:?run-vss-suite.sh runs from the harness phase (W)}" "${IFS_BIN:?no IFS_BIN}" "${DISK:?no DISK}" "${OUT:?no OUT}"
: "${VSS_HOME:?no VSS_HOME}" "${STATUS:?no STATUS}"

TOOL="$HERE/vss_suite.py"
LAUNCH="$HERE/launch-qnx-kvm-bridged.sh"
REPO="$W/repo"
STACK="$REPO/sdv/stack"
SETUP_REC="$W/rec/vss-setup"
WORK="$VSS_HOME/suite-work"
PY="$VSS_HOME/venv/bin/python"
GUEST=192.168.100.10
GUEST_PORT=7160
READY_TRIES=30; READY_BOUND_S=3; READY_GAP_S=1; READY_SETTLE_S=1
STOP_WAIT_S=10
STACK_LABEL=sdv.stack.run
# stack.py's CONTAINERS, every container a run may start (a test holds the two equal): the sweep's names when the label
# cannot be listed
STACK_CONTAINERS=(sdv-stack-app sdv-stack-bridge sdv-stack-can-provider sdv-stack-connector sdv-stack-databroker
	sdv-stack-mock-provider sdv-stack-recorder sdv-stack-witness)
BRIDGE_PIN=""
STEP3_ENV=()
# THE MODES: VSS_HOST unset (or a1-metal) is the a1.metal path, and so is c7g-metal on c7g.metal (step 3's role
# c7g-metal); orin is the Orin mode; any other value is refused
HOST_MODE="${VSS_HOST-a1-metal}"
SLICE_SUBTREE=/sys/fs/cgroup/system.slice/cgroup.subtree_control
L4T_RELEASE=/etc/nv_tegra_release
DT_COMPATIBLE=/proc/device-tree/compatible
STEP3_ROLE=a1-metal              # step 3's SDV_HOST_ROLE
STEP3_PRE=()                     # what each step-3 call runs under: nothing, or in the Orin mode taskset on the cpuset
if [ "$HOST_MODE" = orin ]; then
	STEP3_ROLE=orin
	STEP3_PRE=(taskset -c "${SDV_CONTAINER_CPUSET:-}")
fi
[ "$HOST_MODE" != c7g-metal ] || STEP3_ROLE=c7g-metal

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

fact() {   # UNIT KEY TYPE VALUE: one fact for suite.json (vss_setup.py, FACTS); a KEY with "/" is a nested object
	local f="$WORK/facts/$1/$2.$3"
	mkdir -p "$(dirname "$f")"
	printf '%s' "$4" > "$f"
}
state_of() { cat "$WORK/facts/$1/state.s" 2>/dev/null || true; }

# --- the modes (THE MODES) -------------------------------------------------------------------------------------------
on_jetson() {   # whether L4T's release file or an NVIDIA device tree marks this host as a Jetson: builtins only, no command
	local c=""
	[ ! -e "$L4T_RELEASE" ] || return 0
	[ -r "$DT_COMPATIBLE" ] || return 1
	IFS= read -r -d '' c < "$DT_COMPATIBLE" || true
	case "$c" in nvidia,*) return 0 ;; esac
	return 1
}
host_refusal() {   # why this mode or host is refused before the preflight, or nothing; the Orin mode's checks write facts
	local out rc
	case "$HOST_MODE" in
		a1-metal)
			if on_jetson; then
				echo "VSS_HOST is unset or a1-metal on a host L4T marks as a Jetson: the a1.metal path neither pins QEMU nor" \
					"places a container; the board takes VSS_HOST=orin"
			fi ;;
		c7g-metal)
			if on_jetson; then
				echo "VSS_HOST=c7g-metal on a host L4T marks as a Jetson: the a1.metal path neither pins QEMU nor" \
					"places a container; the board takes VSS_HOST=orin"
			fi ;;
		orin)
			rc=0; out="$(python3 "$TOOL" orin-check --facts "$WORK/facts/preflight" --default-deadline "$VSS_DEADLINE_FILE_DEFAULT" \
				--subtree "$SLICE_SUBTREE" 2>&1)" || rc=$?
			if [ "$rc" != 0 ]; then out="${out//$'\n'/ }"; echo "${out:-vss_suite.py orin-check exited $rc}"; fi ;;
		*) echo "VSS_HOST='${HOST_MODE//[^A-Za-z0-9._-]/?}' is none of a1-metal, c7g-metal and orin (unset is a1-metal)" ;;
	esac
}

guest_runs() { pgrep -x qemu-system-aar >/dev/null 2>&1; }
stop_guest() {   # UNIT: QEMU stopped as the stop phase does, KILL if it lingers, waited until gone; recorded in UNIT's facts
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
after_boot() {   # UNIT: after every boot attempt, a failed one included: sync, then QEMU stopped and gone. A QEMU that
	# outlived its KILL (qemu_stopped false) keeps state/launched, so the sweep at the stop tries once more
	timeout 120 sync || true
	stop_guest "$1"
	[ "$(cat "$WORK/facts/$1/qemu_stopped.b" 2>/dev/null)" = false ] || rm -f "$WORK/state/launched"
}
remove_containers() {   # UNIT: every container labelled sdv.stack.run removed (a step 3 cut by its cap leaves its stack);
	# when the label cannot be listed, the stack's own names, removed unseen: containers_removed false
	local u="$1" ids rc=0 n
	ids="$(timeout 60 docker ps -aq --filter "label=$STACK_LABEL" 2>/dev/null)" || rc=$?
	fact "$u" containers_list_exit i "$rc"
	if [ "$rc" != 0 ]; then
		say "the containers labelled $STACK_LABEL could not be listed (docker ps exit $rc): removing the stack's own names"
		rc=0; timeout 120 docker rm -f "${STACK_CONTAINERS[@]}" >/dev/null 2>&1 || rc=$?
		fact "$u" containers_fallback_rm_exit i "$rc"
		fact "$u" containers_removed b false
		say "docker rm -f of the stack's ${#STACK_CONTAINERS[@]} names exited $rc; what is left was not listed"
		return 0
	fi
	# shellcheck disable=SC2086  # the IDs are words
	set -- $ids
	n=$#
	fact "$u" containers_found i "$n"
	if [ "$n" -gt 0 ]; then
		rc=0; timeout 120 docker rm -f "$@" >/dev/null 2>&1 || rc=$?
		fact "$u" containers_rm_exit i "$rc"
		say "removed $n container(s) labelled $STACK_LABEL (exit $rc)"
	fi
	fact "$u" containers_removed b "$({ [ "$n" = 0 ] || [ "$rc" = 0 ]; } && echo true || echo false)"
}
skipped_why() {   # MODE: setup's reasons when MODE is in its skip list; nothing (and 1) otherwise
	awk -F'\t' -v m="$1" '$1 == m { print $2; f = 1 } END { exit !f }' "$WORK/skips.tsv" 2>/dev/null
}

# --- the preflight ---------------------------------------------------------------------------------------------------
refuse() { finish FAILED preflight "$1"; }

preflight() {
	local s=preflight groups last out rec dbc skipped mode=()
	case "${PLAN:-}" in
		v1|v2|carla) ;;
		*) refuse "PLAN='${PLAN:-}' is not v1, v2 or carla (the harness phase passes PLAN=v1, v2 or carla)" ;;
	esac
	fact $s plan s "$PLAN"
	groups="$(id -nG 2>/dev/null)" || groups=""
	case " $groups " in
		*" docker "*) fact $s docker_group b true ;;
		*) fact $s docker_group b false
		   refuse "this login is not in the docker group: run-vss-setup.sh adds it, and it applies from the next login (gap 4k)" ;;
	esac
	last="$(grep '^status=' "$SETUP_REC/status" 2>/dev/null | tail -n 1 || true)"
	fact $s setup_status_line s "${last:-none}"
	fact $s setup_done b "$([ -e "$SETUP_REC/done" ] && echo true || echo false)"
	[ -e "$SETUP_REC/done" ] || refuse "$SETUP_REC has no done: run-vss-setup.sh has not finished (wait for it with wait-run)"
	[ "$last" = status=DONE ] || refuse "run-vss-setup.sh's last status line is '${last:-none}', not status=DONE"
	case "$HOST_MODE" in orin|c7g-metal) mode=(--host-mode "$HOST_MODE") ;; esac
	out="$(python3 "$TOOL" setup --setup "$SETUP_REC/raw/setup.json" --skips "$WORK/skips.tsv" --facts "$WORK/facts/$s" \
		${mode[@]+"${mode[@]}"} 2>&1)" || refuse "setup's record: $out"
	fact $s skip_modes lines "$(cut -f1 "$WORK/skips.tsv")"
	if guest_runs; then
		fact $s qemu_running b true
		refuse "a QEMU runs already: the guest this harness boots would be a second one (it is not stopped here)"
	fi
	fact $s qemu_running b false
	[ -r "$IFS_BIN" ] && [ -r "$DISK" ] || refuse "IFS_BIN or DISK is not readable"
	fact $s image s "$(basename "$IFS_BIN")"
	for f in "$LAUNCH" "$STACK/step3.py" "$STACK/images.json" "$STACK/step3-runs.json"; do
		[ -r "$f" ] || refuse "no $f: the repo tarball is not the vss form"
	done
	[ -r "$VSS_HOME/gen/manifest.json" ] || refuse "no VSS_HOME/gen/manifest.json: setup did not stage gen"
	[ -x "$PY" ] || refuse "no VSS_HOME/venv/bin/python: setup did not build the venv"
	dbc="$(find "$VSS_HOME/cache/dbc" -maxdepth 1 -name '*.dbc' 2>/dev/null | head -n 1 || true)"
	[ -n "$dbc" ] || refuse "no VSS_HOME/cache/dbc/<sha256>.dbc: setup did not stage the DBC"
	out="$(python3 "$TOOL" plan --plan "$PLAN" --runs-file "$STACK/step3-runs.json" 2>&1 > "$WORK/plan.tsv")" \
		|| { rm -f "$WORK/plan.tsv"; refuse "the plan: $out"; }
	if [ "$PLAN" = carla ]; then
		# PLAN=carla (SDV Phase 7 WP3b): each recording's own log, by its manifest line, and its line's profile among the
		# `vss rules:` profiles setup recorded (a read of setup.json, not a name check)
		out="$(python3 "$TOOL" recordings --plan-tsv "$WORK/plan.tsv" --recordings "$VSS_HOME/recordings" \
			--setup "$SETUP_REC/raw/setup.json" --facts "$WORK/facts/$s" 2>&1)" || refuse "PLAN=carla: ${out//$'\n'/ }"
	else
		for rec in $(awk -F'\t' '$1 == "run" { print $6 }' "$WORK/plan.tsv" | sort -u); do
			[ -r "$VSS_HOME/recordings/$rec/sigsim.log" ] || refuse "no VSS_HOME/recordings/$rec/sigsim.log: setup did not stage it"
		done
	fi
	BRIDGE_PIN="$(python3 "$TOOL" bridge-pin --images "$STACK/images.json" 2>&1)" || refuse "the bridge's pin: $BRIDGE_PIN"
	fact $s bridge_pin s "$BRIDGE_PIN"
	mkdir -p "$OUT/runs"
	STEP3_ENV=(SDV_HOST_ROLE="$STEP3_ROLE" SDV_GEN="$VSS_HOME/gen" SDV_CACHE="$VSS_HOME/cache" SDV_SIM_VENV="$VSS_HOME/venv"
		SDV_RUNS="$OUT/runs" SDV_BRIDGE_IMAGE="$BRIDGE_PIN")
	if [ "$HOST_MODE" = orin ]; then   # the stack's placement and its re-pin after each container start (ORIN MODE)
		STEP3_ENV+=(SDV_CONTAINER_CPUSET="$SDV_CONTAINER_CPUSET" SDV_AFTER_START="$VSS_REPIN")
	fi
	skipped="$(cut -f1 "$WORK/skips.tsv" | tr '\n' ' ')"
	say "preflight: PLAN=$PLAN, setup DONE; modes in setup's skip list: ${skipped:-none}"
}

# --- a run -----------------------------------------------------------------------------------------------------------
run_unit() {   # NN NAME SPEC MODE RECORDING
	local nn="$1" name="$2" spec="$3" mode="$4" rec="$5" why console launchlog rc t0 ready out
	CUR="$name"
	# Listed, not run: a skipped run takes no time, so no check point stands before it.
	if why="$(skipped_why "$mode")"; then
		fact "$name" state s skipped
		fact "$name" why s "setup's skip list: $why"
		say "unit $nn/$TOTAL $name: skipped ($mode is in setup's skip list: $why)"
		return 0
	fi
	if [ -e "$WORK/state/plan-stopped" ]; then
		fact "$name" state s skipped
		fact "$name" why s "$(cat "$WORK/state/plan-stopped")"
		say "unit $nn/$TOTAL $name: skipped (the plan stopped after $(cat "$WORK/facts/suite/plan_stopped_after.s"))"
		return 0
	fi
	if vss_past_stop; then finish TIMEOUT "$name" deadline; fi
	say "unit $nn/$TOTAL $name: start"
	console="$OUT/guest/$name-console.log"
	launchlog="$OUT/guest/$name-launch.log"
	# The boot: the launch script returns once the guest accepts on :7100, and leaves QEMU running either way.
	: > "$WORK/state/launched"
	t0="$(vss_now)"
	rc=0
	vss_capped env IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$console" bash "$LAUNCH" > "$WORK/launch.out" 2>&1 < /dev/null || rc=$?
	sed -E 's/^guest up after [0-9]+s /guest up /' "$WORK/launch.out" > "$launchlog"
	rm -f "$WORK/launch.out"
	fact "$name" operational_s/boot i "$(( $(vss_now) - t0 ))"
	fact "$name" boot_exit i "$rc"
	if vss_cap_fired "$rc"; then
		fact "$name" state s step-timeout
		after_boot "$name"; run_facts "$name" "$console"
		finish TIMEOUT "$name" step-timeout
	fi
	if [ "$rc" != 0 ]; then
		fact "$name" booted b false
		fact "$name" state s boot-failed
		after_boot "$name"; run_facts "$name" "$console"
		say "unit $nn/$TOTAL $name: end (boot-failed: the launch script exited $rc; QEMU stopped, the run skipped)"
		return 0
	fi
	if [ "$HOST_MODE" = orin ]; then
		# ORIN MODE: QEMU's threads to their cores before the readiness; a pin that fails is a boot that failed
		rc=0
		out="$(vss_capped "$VSS_REPIN" boot 2>&1 < /dev/null)" || rc=$?
		fact "$name" repin_exit i "$rc"
		fact "$name" repin lines "$out"
		if vss_cap_fired "$rc"; then
			fact "$name" state s step-timeout
			after_boot "$name"; run_facts "$name" "$console"
			finish TIMEOUT "$name" step-timeout
		fi
		if [ "$rc" != 0 ]; then
			fact "$name" pinned b false
			fact "$name" booted b false
			fact "$name" state s boot-failed
			fact "$name" why s "VSS_REPIN boot exited $rc: the guest's QEMU is not on its cores, the run skipped as a boot that failed"
			after_boot "$name"; run_facts "$name" "$console"
			say "unit $nn/$TOTAL $name: end (boot-failed: VSS_REPIN boot exited $rc; QEMU stopped, the run skipped)"
			if [ ! -e "$WORK/state/pinned-seen" ]; then
				# No run's QEMU has been pinned yet: a pin that fails for a host reason (sudo's rule, no taskset) would fail
				# after every later boot too, so the rest of the plan is listed instead, as for a guest not ready.
				fact suite plan_stopped_after s "$name"
				printf '%s %s' "not booted: the pin of $name's QEMU failed (VSS_REPIN boot exited $rc) and no run before it" \
					"had been pinned, so the plan stopped there" > "$WORK/state/plan-stopped"
				say "no run's QEMU has been pinned to its cores: the rest of the plan is listed, not booted"
			fi
			return 0
		fi
		: > "$WORK/state/pinned-seen"
		fact "$name" pinned b true
	fi
	fact "$name" booted b true
	# Readiness on :7160: one connect-and-close, retried within a bound; then the console's freshness.
	rc=0
	ready="$(vss_capped python3 "$TOOL" ready --host "$GUEST" --port "$GUEST_PORT" --tries "$READY_TRIES" --bound "$READY_BOUND_S" \
		--gap "$READY_GAP_S" --settle "$READY_SETTLE_S" --console "$console" --facts "$WORK/facts/$name" < /dev/null)" || rc=$?
	if vss_cap_fired "$rc"; then
		fact "$name" state s step-timeout
		after_boot "$name"; run_facts "$name" "$console"
		finish TIMEOUT "$name" step-timeout
	fi
	if [ "$rc" != 0 ] || [ "$ready" != yes ]; then
		fact "$name" state s not-ready
		after_boot "$name"; run_facts "$name" "$console"
		say "unit $nn/$TOTAL $name: end (not-ready: no connect on :$GUEST_PORT within the bound; QEMU stopped, the run skipped)"
		if [ ! -e "$WORK/state/ready-seen" ]; then
			# No run's guest has answered yet: the rest of the plan would boot a guest that does not answer, each until
			# the bound, so it is listed instead.
			fact suite plan_stopped_after s "$name"
			printf '%s %s' "not booted: the guest of $name was not ready on :$GUEST_PORT and no run before it had been," \
				"so the plan stopped there" > "$WORK/state/plan-stopped"
			say "no run's guest has been ready on :$GUEST_PORT: the rest of the plan is listed, not booted"
		fi
		return 0
	fi
	: > "$WORK/state/ready-seen"
	# Step 3: one spec, one fresh boot, its own --name.
	: > "$WORK/state/step3-started"
	t0="$(vss_now)"
	rc=0
	vss_capped ${STEP3_PRE[@]+"${STEP3_PRE[@]}"} env "${STEP3_ENV[@]}" SDV_RECORDING="$VSS_HOME/recordings/$rec" "$PY" \
		"$STACK/step3.py" run --mode "$mode" --spec "$spec" --name "$name" --images loaded --monitor guest --guest-host "$GUEST" \
		--guest-console "$console" --guest-image "$IFS_BIN" < /dev/null || rc=$?
	fact "$name" operational_s/step3 i "$(( $(vss_now) - t0 ))"
	fact "$name" step3_exit i "$rc"
	if vss_cap_fired "$rc"; then
		fact "$name" state s step-timeout
		after_boot "$name"; run_facts "$name" "$console"
		finish TIMEOUT "$name" step-timeout
	fi
	fact "$name" state s ran
	after_boot "$name"
	run_facts "$name" "$console"
	say "unit $nn/$TOTAL $name: end (ran: step 3 exited $rc)"
}

run_facts() {   # UNIT CONSOLE: the console's sha256, step 3's directory and its result.json
	python3 "$TOOL" run-facts --runs "$OUT/runs" --name "$1" --console "$2" --facts "$WORK/facts/$1" > /dev/null 2>&1 \
		|| say "run-facts for $1 failed: recorded as found nothing"
}

can_complete() {   # every can run of the plan ran and left its result.json
	local kind nn name spec mode rec n=0
	while IFS=$'\t' read -r kind nn name spec mode rec; do
		[ "$kind" = run ] && [ "$mode" = can ] || continue
		n=$((n + 1))
		[ "$(state_of "$name")" = ran ] && [ "$(cat "$WORK/facts/$name/result.b" 2>/dev/null)" = true ] || return 1
	done < "$WORK/plan.tsv"
	[ "$n" -gt 0 ]
}

# --- a compare -------------------------------------------------------------------------------------------------------
compare_unit() {   # NN NAME WHEN MODE...
	local nn="$1" name="$2" when="$3" m kind unn uname uspec umode urec d rc t0 skipped="" dirs=() rels=()
	shift 3
	CUR="$name"
	# A compare that cannot run is listed first, as a skipped run is; the check point stands before one that runs.
	for m in "$@"; do
		if skipped_why "$m" > /dev/null; then skipped="$skipped $m"; fi
	done
	if [ -n "$skipped" ]; then
		fact "$name" state s not-compared
		fact "$name" why s "setup's skip list holds$skipped: a compare needs every one of its modes (gap 4s)"
		say "unit $nn/$TOTAL $name: not compared (skipped by setup:$skipped)"
		return 0
	fi
	if [ "$when" = can-complete ]; then
		if can_complete; then fact suite can_complete b true; else
			fact suite can_complete b false
			fact "$name" state s not-compared
			fact "$name" why s "can did not finish all six runs: a partial can set is coverage, not compared (gap 4s)"
			say "unit $nn/$TOTAL $name: not compared (can did not finish all six runs)"
			return 0
		fi
	fi
	while IFS=$'\t' read -r kind unn uname uspec umode urec; do
		[ "$kind" = run ] || continue
		case " $* " in *" $umode "*) ;; *) continue ;; esac
		d="$(cat "$WORK/facts/$uname/dir.s" 2>/dev/null || true)"
		[ -n "$d" ] || continue
		dirs+=("$OUT/$d"); rels+=("$d")
	done < "$WORK/plan.tsv"
	if [ "${#dirs[@]}" = 0 ]; then
		fact "$name" state s not-compared
		fact "$name" why s "no step-3 directory of its modes"
		say "unit $nn/$TOTAL $name: not compared (no step-3 directory)"
		return 0
	fi
	if vss_past_stop; then finish TIMEOUT "$name" deadline; fi
	fact "$name" dirs lines "$(printf '%s\n' "${rels[@]}")"
	say "unit $nn/$TOTAL $name: start (${#dirs[@]} run directories, --modes $*)"
	t0="$(vss_now)"
	rc=0
	# The directories BEFORE --modes: --modes takes every word after it (step3.py's compare).
	vss_capped ${STEP3_PRE[@]+"${STEP3_PRE[@]}"} env "${STEP3_ENV[@]}" "$PY" "$STACK/step3.py" compare --name "$name" \
		"${dirs[@]}" --modes "$@" < /dev/null || rc=$?
	fact "$name" operational_s/compare i "$(( $(vss_now) - t0 ))"
	fact "$name" exit i "$rc"
	if vss_cap_fired "$rc"; then
		fact "$name" state s step-timeout
		finish TIMEOUT "$name" step-timeout
	fi
	fact "$name" state s ran
	python3 "$TOOL" compare-facts --runs "$OUT/runs" --name "$name" --facts "$WORK/facts/$name" > /dev/null 2>&1 \
		|| say "compare-facts for $name failed: recorded as found nothing"
	say "unit $nn/$TOTAL $name: end (ran: step 3's compare exited $rc)"
}

# --- the stops -------------------------------------------------------------------------------------------------------
stop_verdict() {   # REASON...: suite.json's stop.verified, false with the reasons (stop.unverified) when the sweep could
	# not show its removals done; said in run.log, whose last 30 lines wait-run prints. The status line is not changed
	local j
	if [ "$#" = 0 ]; then fact stop verified b true; return 0; fi
	fact stop verified b false
	fact stop unverified lines "$(printf '%s\n' "$@")"
	j="$(printf '%s; ' "$@")"
	say "the stop is unverified: ${j%; }"
}
sweep() {   # the idempotent removals of every stop, DONE included, recorded under suite.json's stop: QEMU stopped if this
	# harness launched it, the stack's containers removed after any step-3 call. A QEMU that outlived its KILL, containers
	# that could not be listed, or a removal that failed makes the stop unverified (stop_verdict)
	local unv=() le
	if [ -e "$WORK/state/launched" ]; then
		stop_guest stop
		rm -f "$WORK/state/launched"
		[ "$(cat "$WORK/facts/stop/qemu_stopped.b" 2>/dev/null)" != false ] || unv+=("QEMU still runs after a KILL")
	fi
	if [ -e "$WORK/state/step3-started" ]; then
		remove_containers stop
		le="$(cat "$WORK/facts/stop/containers_list_exit.i" 2>/dev/null || echo missing)"
		if [ "$le" != 0 ]; then
			unv+=("the containers labelled $STACK_LABEL could not be listed (docker ps exit $le)")
		elif [ "$(cat "$WORK/facts/stop/containers_removed.b" 2>/dev/null)" != true ]; then
			le="$(cat "$WORK/facts/stop/containers_rm_exit.i" 2>/dev/null || echo missing)"
			unv+=("docker rm -f of the containers labelled $STACK_LABEL exited $le")
		fi
	fi
	stop_verdict ${unv[@]+"${unv[@]}"}
}
clean_stop() {   # a stop other than DONE: sync, then the sweep
	say "a clean stop: sync, QEMU stopped if this harness launched it, the stack's containers removed after any step-3 call"
	timeout 120 sync || true
	sweep
}

write_record() {   # STATUS STATUS-LINE AT REASON; the Orin mode's record says so (host_mode, the cpuset), c7g-metal's
	# (host_mode, no cpuset); a1.metal's as before
	local mode=()
	[ "$HOST_MODE" != orin ] || mode=(--host-mode orin --cpuset "${SDV_CONTAINER_CPUSET:-}")
	[ "$HOST_MODE" != c7g-metal ] || mode=(--host-mode c7g-metal)
	python3 "$TOOL" record --work "$WORK" --out "$OUT/suite.json" --setup "$SETUP_REC/raw/setup.json" --plan "${PLAN:-}" \
		--status "$1" --status-line "$2" --at "$3" --reason "$4" ${mode[@]+"${mode[@]}"}
}

finish() {   # STATUS [AT [REASON]]: the record, then the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line kind nn name rest notrun=""
	trap - EXIT
	set +e
	if [ "$st" = DONE ]; then sweep; else clean_stop; fi
	case "$st" in
		DONE) line="status=DONE" ;;
		TIMEOUT) line="status=TIMEOUT at=$at reason=$why" ;;
		*) line="status=FAILED at=$at" ;;
	esac
	if ! write_record "$st" "$line" "$at" "$why"; then
		say "suite.json could not be written"
		if [ "$st" = DONE ]; then st=FAILED; at=record; line="status=FAILED at=record"; fi
	fi
	if [ "$st" != DONE ] && [ -r "$WORK/plan.tsv" ]; then
		while IFS=$'\t' read -r kind nn name rest; do
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
	local kind nn name a b c why
	CUR=preflight
	rm -rf "$WORK"
	mkdir -p "$WORK/facts" "$WORK/state" "$OUT/guest"
	: > "$WORK/skips.tsv"
	trap on_exit EXIT
	say "run-vss-suite.sh PLAN=${PLAN:-}: a functional session, nothing timed"
	why="$(host_refusal)"
	[ -z "$why" ] || refuse "$why"
	[ "$HOST_MODE" != orin ] || say "the Orin mode (VSS_HOST=orin): step 3 on $SDV_CONTAINER_CPUSET, QEMU re-pinned by VSS_REPIN"
	[ "$HOST_MODE" != c7g-metal ] || say "the c7g.metal mode (VSS_HOST=c7g-metal): the a1.metal path, step 3's role c7g-metal"
	if ! vss_deadline_load; then refuse "no readable deadline file (lib-vss-deadline.sh)"; fi
	fact preflight deadline_readable b true
	preflight
	TOTAL="$(grep -c . "$WORK/plan.tsv")"
	cd "$REPO"
	while IFS=$'\t' read -r kind nn name a b c <&3; do
		case "$kind" in
			run) run_unit "$nn" "$name" "$a" "$b" "$c" ;;
			# shellcheck disable=SC2086  # the compare's modes are words
			compare) compare_unit "$nn" "$name" "$a" $b ;;
		esac
	done 3< "$WORK/plan.tsv"
	finish DONE
}

main
