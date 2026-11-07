#!/usr/bin/env bash
# KVM here boots our startup-qemu-virt; this is not a QNX-supported
# configuration, and no timing claim attaches to the boot.
# run-vss-setup.sh -- bring a bare-metal AWS instance up for the VSS slice's suite: Docker, the slice's images, the
# host's Python venv, vcan and the staged inputs; the QNX guest booted and smoked on :7100 before and after Docker; and a
# SIGILL probe of every image. plan Phase 3 (WP4),
# 2026-10-03; with VSS_HOST=orin, the Jetson Orin beside its guest instead (plan Phase 5 WP2, 2026-10-17: THE MODES). A
# functional session: no field of its record is a measurement.
#
# HOW IT RUNS. Only as remote-ladder.sh's harness phase starts it, detached, in a vss session (scripts/aws/README.md, "A
# vss session instead"): LADDER_ENV="HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin", once per session, after setup and
# quiesce. The detached runner runs it from $R = $W/repo/orin-native/gpu-concurrency with stdout and stderr in
# rec/vss-setup/run.log and SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored (a step under its cap starts with only SIGPIPE
# of them ignored: remote-ladder.sh, SIGNALS), then reads its last status line. Its environment:
#   W        the session's directory (~/a1): inputs.env, repo/ (the vss tarball), in/
#   IFS_BIN  the session's METAL_IFS, ifs-vss.bin (IMG_S and IMG_B are the same path)
#   DISK     the guest disk; OUT = rec/vss-setup/raw, where every record below goes
#   VSS_IN   $W/in, the upload bundle (sdv/stack/bundle.py's members and bundle.json)
#   VSS_HOME $W/sdv, where this harness puts what the suite runs on: gen/, recordings/<name>/, cache/dbc/<sha256>.dbc,
#            py312/ (python-build-standalone), venv/; and setup-work/, its own working files (never captured)
#   STATUS   rec/vss-setup/status, the status file (lib-vss-deadline.sh's vss_status writes it)
# VPROBE and CSTATE come with the phase's environment and are not used here. QNX_METAL_DEADLINE_FILE overrides the
# deadline file for the tests, and names it in the Orin mode.
#
# THE MODES (plan Phase 5 WP2). VSS_HOST unset or a1-metal is the a1.metal path
# this header describes, every stubbed command and every file as before (a test holds an a1.metal run stub call for stub
# call and file for file to the reference harness). VSS_HOST=orin is the Orin mode: the Jetson Orin on L4T R39 beside its QNX
# guest, the harness started by the board's private helper. VSS_HOST=c7g-metal (2026-10-17) is the a1.metal path on AWS
# c7g.metal, another bare-metal host the harness phase starts it on (its VSS_HOST= word): every step, call and file as
# a1-metal's, but setup.json says host_mode c7g-metal (the suite's preflight reads it) and run.log names the mode in one
# line. Any other value, an empty one included, is refused before step 1 (status=FAILED at=preflight); so is the a1.metal
# path, either word, on a host that L4T's release file (/etc/nv_tegra_release) or an NVIDIA device tree marks as a
# Jetson, read with builtins alone, since that path writes daemon.json and installs packages.
#
# ORIN MODE. Its environment adds VSS_REPIN (the re-pin, vss-repin.sh: an absolute path of an executable file, one
# shlex word) and SDV_CONTAINER_CPUSET (a CPU list N[,N...] that holds none of 0, 1, 2 and 4: vss_setup.py, CPUSET
# RULE), and QNX_METAL_DEADLINE_FILE must be set and must not be the library's default (that file is an AWS
# instance's). Before step 1, `vss_setup.py orin-check` refuses any of those that does not hold, and a system.slice
# whose cgroup.subtree_control lacks cpuset (turning it on is a host change, and it must be on before the guest).
# Then the steps below, with these differences:
#   3 guest     after the launcher's exit 0, `$VSS_REPIN boot` pins QEMU's threads to their cores, its exit status and
#               its line recorded (repin_exit, repin, pinned); a failed pin is a guest that did not boot (booted false:
#               QEMU stopped, no smoke, setup goes on)
#   4 docker    Docker as the host has it: no daemon.json written, no apt-get, no apt-cache. daemon.json's sha256 read
#               under sudo -n, never its content (daemon_json_sha256; a read that fails is a real failure), whether the
#               login was in docker before (docker_group_before, `id -nG <login>`), then usermod -aG docker as on a1.metal
#               (the helper removes it at the day's end); the same asserts of the server;
#               docker-facts.txt without the apt-cache lines
#   6 vcan      no apt: lsmod first (modules_loaded_before: which of vcan, can and can_raw were loaded, so that the helper
#               unloads only what this setup loaded), modinfo -F filename and -F vermagic, then sudo -n modprobe -a vcan
#               can can_raw. No module (modinfo fails), a failed modprobe, or an lsmod that cannot be read first (then no
#               modprobe) puts broker and can into the skip list
#  11 probes    each probe container also gets --cpuset-cpus "$SDV_CONTAINER_CPUSET" (cpuset in probes.json). A QEMU still
#               listed as the step begins (step 5's stop, KILL included, did not end it) gets no container beside it,
#               since this step re-pins nothing: each image is recorded not started (started false, with why)
#               and its modes go into the skip list; the host venv's probe, which starts no container, still runs
#  13 close     daemon.json's sha256 read again: a difference, or a read that fails, is status=FAILED at=close with its
#               own reason, never passed over
# setup.json says host_mode orin; facts.preflight holds the cpuset, VSS_REPIN's path and the cpuset controller,
# facts.docker the first hash and the group fact, facts.close the second hash, facts.vcan the modules loaded before,
# facts.probes whether a QEMU was listed at step 11 (qemu_listed).
#
# THE STEPS, in this order. Before each, the deadline's check point (lib-vss-deadline.sh: now >= stop_at stops here);
# each runs under its cap (stop_at + 10 minutes - now, `timeout --kill-after=30s`) as a child of this script, called in
# the library's set -e form, rc=0; vss_capped CMD... || rc=$?, then vss_cap_fired "$rc". Each step's UTC start and end and
# its whole seconds go into setup.json.
#   1 preflight     the deadline file readable; $W/repo/sdv present; IFS_BIN and DISK readable; no QEMU running;
#                   `bundle.py verify --in $VSS_IN` with the system python3; bundle.json's commit equal to inputs.env's
#                   REPO_COMMIT; `df -h /` and `free -m` into df.txt
#   2 net-before    net-before.txt: sysctl net.ipv4.ip_forward; the policy line of `sudo -n iptables -S FORWARD`; the
#                   br_netfilter lines of lsmod; sysctl net.bridge.bridge-nf-call-iptables (absent is expected); the -A
#                   rules per table of `sudo -n iptables-save` (counts, never the rules). Each command's exit status is
#                   written after it, and a non-zero one marks that item FAILED-to-read, never a value. A value is read
#                   from the command's stdout alone; a warning on its stderr is kept apart (its first line, as a
#                   `stderr:` line and the fact <key>_stderr), never taken for the value
#   3 guest         ifs-vss.bin booted by launch-qnx-kvm-bridged.sh (console guest/00-setup-console.log, its own output
#                   guest/00-setup-launch.log, whose "guest up after Ns" loses its N: the boot's whole seconds go under
#                   operational_s). Then a connect-and-close with no bytes on 192.168.100.10:7160 in one step, retried
#                   within a bound (the readiness; never the banner, which can interleave); the console's `vss rules:`
#                   lines read with NUL and CR removed: how many parse, whether all that parse agree, the catalog, the
#                   profile list they agree on (profiles; SDV Phase 7 WP3b: run-vss-suite.sh's PLAN=carla reads it), and
#                   whether the :7160 banner was seen, all information; then smoke 1 on :7100. A guest
#                   that does not boot is recorded and stopped, and setup goes on. Setup goes on whatever the guest
#                   answers; run-vss-suite.sh refuses a setup whose guest booted without :7160, C12b and the bridge's
#                   catalog (step 13 says so)
#   4 docker        /etc/docker/daemon.json first ({"features": {"containerd-snapshotter": true}}: the package starts
#                   dockerd at install); apt-get update; a candidate for docker.io in apt-cache policy; docker.io
#                   installed alone (apt.log); usermod -aG docker for this user (from its next login); the server
#                   answering; docker-facts.txt (dpkg-query, apt-cache policy's package and source lines, the server's
#                   version, storage driver and image store driver-type, never a raw `docker info`). The driver-type
#                   must be io.containerd.snapshotter.v1 and the server's major version 29
#   5 after-docker  net-after.txt as step 2, each item compared with net-before (same, changed, or unreadable when
#                   either read failed); smoke 2 on the same guest; sync; the guest stopped as the stop phase does
#                   (sudo -n pkill -x qemu-system-aar, then waited for; KILL if it lingers)
#   6 vcan          linux-modules-extra-$(uname -r): its apt-cache policy lines into docker-facts.txt, then its own
#                   apt-get install (apt.log), so a missing package cannot fail the Docker install; `sudo -n modprobe -a
#                   vcan can can_raw` (without -a modprobe takes can can_raw as vcan's parameters); lsmod's vcan, can and
#                   can_raw lines; `modinfo -F filename vcan` and `modinfo -F vermagic vcan` only (the whole modinfo has
#                   sig_key, colon-separated hex that leakscan's IPv6 rule flags). No candidate (2026-10-17: an AMI's
#                   kernel can have no extra package in the archive and still hold vcan in its own modules): vcan from the
#                   running kernel instead, as the Orin mode takes it (lsmod first, modinfo -F filename and -F vermagic,
#                   then sudo -n modprobe -a vcan can can_raw; no apt-get install, no apt.log line), with facts.vcan.source
#                   running-kernel, a fact the package path never writes, and modules_loaded_before as the Orin mode's. A
#                   failed install or a failed modprobe puts broker and can into the skip list, and so does no candidate
#                   when the kernel's way fails too (no module, a failed modprobe, or an lsmod that cannot be read
#                   first), its reason naming both: replay needs no vcan
#   7 load          `sudo -n docker load -i sdv-arm64-images.tar`, then `bundle.py verify --in $VSS_IN --loaded --docker
#                   'sudo -n docker'` (the docker group applies only from the next login)
#   8 pulls         `sudo -n docker pull repo@index_digest` for the four upstream images of images.json, each under its
#                   own cap in the same call form (a pull's cap fired is the step's: step-timeout), then `bundle.py
#                   verify-upstream --docker 'sudo -n docker'` with the system python3
#   9 venv          python-build-standalone unpacked to $VSS_HOME/py312, `python3 -m venv $VSS_HOME/venv`, then `pip
#                   install --require-hashes --no-deps -r sdv/sim/requirements.aarch64.lock`; venv.txt holds the
#                   version, pip's output and `pip freeze`. pip runs without --no-cache-dir, so it keeps its download
#                   cache in the session user's ~/.cache/pip: outside OUT and VSS_HOME, never captured
#  10 stage         gen to $VSS_HOME/gen, each recording to $VSS_HOME/recordings/<name>, the DBC to
#                   $VSS_HOME/cache/dbc/<sha256>.dbc (where stack.py's resolve_dbc looks), never over an existing one. Each
#                   rec-<name>.tar must hold the log its manifest line names (`vss_setup.py log`: sigsim.log, or a CARLA
#                   recording's carla.log; SDV Phase 7 WP3b), never a fixed name; a line that pairs a generator with
#                   another log, or none, is a real failure
#  11 probes        each image's start-up, with `sudo -n docker run --rm --network none`: the databroker with the
#                   stack's arguments until `Listening on 127.0.0.1:55555`, then a settle, then `docker stop -t 5` (its
#                   exit status after the stop is recorded apart from its verdict); the can- and csv-providers --help;
#                   the mock-provider's numpy, scipy and grpc; the app's and the recorder's imports; the bridge's `check`
#                   with a read-only root; then the host venv's imports and a load of the staged DBC. Each container's
#                   bound is kept by removing it (docker rm -f), never by a signal into it: a container's PID 1 with
#                   no handler ignores TERM. Whether its `sudo -n docker run` still runs is read from /proc, never by
#                   a signal into sudo. A probe passes with an exit status below 124 (an unknown flag's 2 still
#                   shows the binary ran its start-up; 124 is the host venv's bound, 125-127 docker's own failures,
#                   132 SIGILL, 128 and up a signal), within its bound, and with no kernel line matching `undefined
#                   instruction` logged since it began, read with `sudo -n dmesg`, of which only the matching lines are
#                   kept; a read that fails makes the probe "kernel log unreadable", never a pass. The kernel logs such
#                   a line only when it logs a user-space SIGILL at all (arm64: only with debug.exception-trace set,
#                   whose value is recorded, read and never set): exit 132 is the detector that does not depend on it.
#                   A probe that does not pass is recorded, and its image's modes go into the skip list (the
#                   databroker, the providers, the app and the recorder: broker; the bridge and the host venv: broker,
#                   replay and can). probes.json is rewritten whole after each probe
#  12 30min-rule    left = stop_at - now. Under 30 minutes: status=TIMEOUT at=30min-rule reason=30min-rule, and the
#                   harness phase then refuses the suite
#  13 close         `df -h /` and `sudo -n du -sh /var/lib/docker /var/lib/containerd` into df.txt; the guest's verdict
#                   (step 3) and the smokes, whether run-vss-suite.sh takes this setup's guest or will refuse it
#                   (vss_setup.py, THE GUEST RULE), and the skip list, said in run.log, whose last 30 lines wait-run
#                   prints; then the sweep (below), setup.json written whole, and status=DONE
#
# THE STATUS LINE, the last one in STATUS, through vss_status:
#   status=DONE                                  every step ran; setup.json written first (a temporary file, a rename)
#   status=TIMEOUT at=<step> reason=deadline     a check point found now >= stop_at; <step> and the rest did not run
#   status=TIMEOUT at=<step> reason=step-timeout <step>'s cap fired: it was cut, the rest did not run
#   status=TIMEOUT at=30min-rule reason=30min-rule
#   status=FAILED at=<step>                      a real failure: the preflight, the Docker install or its
#                                                store or version, the load, the pulls or their verification, the venv
#                                                or the staging. Also a step that exits non-zero for any other reason
#                                                (its reason is its exit status), and a parent that ends without a
#                                                status line, through its EXIT trap (reason "the harness stopped
#                                                unexpectedly", at the step it was in)
#   status=FAILED at=preflight                   as above, and also with no readable deadline file, before any step
#   status=FAILED at=close                       every step ran, but setup.json could not be written; or, in the Orin
#                                                mode, the close found daemon.json changed, or could not hash it
# Every FAILED exits 1, a TIMEOUT 0. Every stop sweeps before its record, DONE included: the guest stopped if this harness
# booted it and it runs, the probe containers removed by name, then those still labelled sdv.setup.probe=1 counted, all
# recorded under facts.stop (a container that a wedged daemon kept, or a stack a death the cap did not cause left, shows
# there). A QEMU that outlives its KILL, a list that fails or a probe container still listed records the stop unverified
# (facts.stop.verified false, with why under facts.stop.unverified) and says so in run.log; the status line is not
# changed. Every stop but DONE syncs first; the steps not run go to run.log and setup.json, and setup.json is written in
# every case.
# Everything else is recorded and setup goes on: a net item that cannot be read, a guest that does not boot, a smoke
# that fails, vcan that cannot be had, a probe that does not pass.
#
# THE RECORD, in OUT (each name on capture.py's vss whitelist): setup.json (the steps, the steps not run, the skip list
# as skip_modes and skip, and every fact), net-before.txt, net-after.txt, docker-facts.txt, probes.json, venv.txt,
# smoke-1.txt, smoke-2.txt, df.txt, apt.log (not in the Orin mode), guest/00-setup-console.log and
# guest/00-setup-launch.log. Every string in setup.json and probes.json is one line: vss_setup.py writes a multi-line
# output as an array of lines. Nothing else is written outside OUT, STATUS and VSS_HOME but /etc/docker/daemon.json
# (never in the Orin mode) and pip's download cache, ~/.cache/pip (step 9; what apt-get, docker and modprobe keep for
# themselves is theirs). Every docker call, bundle.py's included, every iptables, dmesg, modprobe, apt-get, usermod,
# pkill and du runs under sudo -n, and so do the Orin mode's sha256sum of daemon.json and vss-repin.sh's taskset. A
# smoke keeps latency_probe.py's exit status and the bad and rej counts of its RESULT line, nothing else of its output.
#
# DESIGN VALUES (not measured): the readiness connect's bound and attempts (3 s, 30); the wait for five `vss rules:` lines
# (5 s); the wait for dockerd (60 s); the databroker's wait for its Listening line (60 s, stack.py's START_TIMEOUT_S) and
# its settle after it (2 s); any other probe's bound (600 s), and a removed probe's wait (30 s, then TERM to its sudo and
# 10 s, then KILL); the guest's stop (10 s, then KILL and 10 s more); and the 30-minute rule's threshold.
#
# WHAT IT DOES NOT SHOW: that the suite will pass; any timing (the operational_s values are whole seconds of this
# session's own steps, not of the guest); anything about the A72 beyond the paths the probes run; that a probe's exit
# below 124 means the image works, only that its start-up did not die by a signal; physical CAN. In the Orin mode: that
# QEMU stays on its cores after the re-pin's line, that a probe container stayed on its cpuset beyond the flag it was
# given, or that the host is as it was beyond daemon.json's hash (the helper's before and after read the rest).
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
: "${W:?run-vss-setup.sh runs from the harness phase (W)}" "${IFS_BIN:?no IFS_BIN}" "${DISK:?no DISK}" "${OUT:?no OUT}"
: "${VSS_IN:?no VSS_IN}" "${VSS_HOME:?no VSS_HOME}" "${STATUS:?no STATUS}"

TOOL="$HERE/vss_setup.py"
REPO="$W/repo"
STACK="$REPO/sdv/stack"
WORK="$VSS_HOME/setup-work"
GUEST=192.168.100.10
STEPS=(preflight net-before guest docker after-docker vcan load pulls venv stage probes 30min-rule close)
NSTEPS=${#STEPS[@]}
STORE=io.containerd.snapshotter.v1
MAJOR=29
RULE_LEFT_S=1800                 # the 30-minute rule
READY_TRIES=30; READY_BOUND_S=3
RULES_WAIT_S=5
DOCKERD_WAIT_S=60
LISTEN_BOUND_S=60; LISTEN_SETTLE_S=2
PROBE_BOUND_S=600
STOP_WAIT_S=10
IMAGES_TAR=sdv-arm64-images.tar
PROBE_IMPORT="import kuksa_client, grpc, google.protobuf, websockets, wcwidth"
PROBE_MOCK="import numpy, scipy.linalg, grpc; numpy.linalg.inv(numpy.eye(4))"
PROBE_VENV="import cantools, can, bitstruct, wrapt"
PROBE_DBC="import cantools, sys; cantools.database.load_file(sys.argv[1])"
POLICY_LINES='^[^ ].*:$|^ +(Installed|Candidate):|^ +(\*\*\* )?[^ ]+ [0-9]+$|^ +[0-9]+ '
# THE MODES: VSS_HOST unset (or a1-metal) is the a1.metal path, and so is c7g-metal on c7g.metal; orin is the Orin mode;
# any other value is refused
HOST_MODE="${VSS_HOST-a1-metal}"
DAEMON_JSON=/etc/docker/daemon.json
SLICE_SUBTREE=/sys/fs/cgroup/system.slice/cgroup.subtree_control
L4T_RELEASE=/etc/nv_tegra_release
DT_COMPATIBLE=/proc/device-tree/compatible
PROBE_CPUSET=()                  # what each probe container is placed by: nothing, or in the Orin mode its cpuset
if [ "$HOST_MODE" = orin ]; then PROBE_CPUSET=(--cpuset-cpus "${SDV_CONTAINER_CPUSET:-}"); fi
REPIN_RC=0

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

fact() {   # STEP KEY TYPE VALUE: one fact for setup.json (vss_setup.py, FACTS); a KEY with "/" is a nested object
	local f="$WORK/facts/$1/$2.$3"
	mkdir -p "$(dirname "$f")"
	printf '%s' "$4" > "$f"
}
pfact() { local n="$1"; shift; fact "../probes/$n" "$@"; }   # NAME KEY TYPE VALUE: one fact of probes.json
skip_modes() {   # STEP REASON MODE...: modes the suite skips, each with its reason on one line
	local step="$1" why="$2" m
	shift 2
	why="${why//$'\r'/ }"; why="${why//$'\n'/ }"; why="${why//$'\t'/ }"
	for m in "$@"; do printf '%s\t%s\t%s\n' "$m" "$step" "$why" >> "$WORK/skip.tsv"; done
}
die_step() {   # STEP WHY: a real failure; the parent writes the record
	fact "$1" failure s "$2"
	say "FAILED in $1: $2" >&2
	exit 1
}

# --- the modes (THE MODES) -------------------------------------------------------------------------------------------
on_jetson() {   # whether L4T's release file or an NVIDIA device tree marks this host as a Jetson: builtins only, no command
	local c=""
	[ ! -e "$L4T_RELEASE" ] || return 0
	[ -r "$DT_COMPATIBLE" ] || return 1
	IFS= read -r -d '' c < "$DT_COMPATIBLE" || true
	case "$c" in nvidia,*) return 0 ;; esac
	return 1
}
host_refusal() {   # why this mode or host is refused before step 1, or nothing; the Orin mode's checks write its facts
	local out rc
	case "$HOST_MODE" in
		a1-metal)
			if on_jetson; then
				echo "VSS_HOST is unset or a1-metal on a host L4T marks as a Jetson: the a1.metal path writes $DAEMON_JSON and" \
					"installs packages; the board takes VSS_HOST=orin"
			fi ;;
		c7g-metal)
			if on_jetson; then
				echo "VSS_HOST=c7g-metal on a host L4T marks as a Jetson: the a1.metal path writes $DAEMON_JSON and" \
					"installs packages; the board takes VSS_HOST=orin"
			fi ;;
		orin)
			rc=0; out="$(python3 "$TOOL" orin-check --facts "$WORK/facts/preflight" --default-deadline "$VSS_DEADLINE_FILE_DEFAULT" \
				--subtree "$SLICE_SUBTREE" 2>&1)" || rc=$?
			if [ "$rc" != 0 ]; then out="${out//$'\n'/ }"; echo "${out:-vss_setup.py orin-check exited $rc}"; fi ;;
		*) echo "VSS_HOST='${HOST_MODE//[^A-Za-z0-9._-]/?}' is none of a1-metal, c7g-metal and orin (unset is a1-metal)" ;;
	esac
}
daemon_json_sha256() {   # the host's daemon.json's sha256, read under sudo -n, never its content; fails when unreadable
	local out
	out="$(sudo -n sha256sum "$DAEMON_JSON" 2>/dev/null)" || return 1
	out="${out%% *}"
	[[ "$out" =~ ^[0-9a-f]{64}$ ]] || return 1
	printf '%s\n' "$out"
}
repin_after_boot() {   # STEP: the Orin mode's `VSS_REPIN boot` after the launcher's exit 0 (QEMU's threads to their cores),
	# recorded in STEP's facts; returns 1, with its exit status in REPIN_RC, when it failed
	local out
	REPIN_RC=0; out="$("$VSS_REPIN" boot 2>&1 < /dev/null)" || REPIN_RC=$?
	fact "$1" repin_exit i "$REPIN_RC"
	fact "$1" repin lines "$out"
	if [ "$REPIN_RC" = 0 ]; then fact "$1" pinned b true; return 0; fi
	fact "$1" pinned b false
	return 1
}

guest_runs() { pgrep -x qemu-system-aar >/dev/null 2>&1; }
stop_guest() {   # STEP: stop QEMU as the stop phase does, KILL if it lingers; recorded in STEP's facts
	local step="$1" i
	if ! guest_runs; then fact "$step" guest_was_running b false; return 0; fi
	fact "$step" guest_was_running b true
	timeout 30 sudo -n pkill -x qemu-system-aar >/dev/null 2>&1 || true
	for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	if guest_runs; then
		timeout 30 sudo -n pkill -KILL -x qemu-system-aar >/dev/null 2>&1 || true
		for i in $(seq 1 $((STOP_WAIT_S * 2))); do guest_runs || break; sleep 0.5; done
	fi
	if guest_runs; then fact "$step" guest_stopped b false; say "QEMU still runs after a KILL"; return 0; fi
	fact "$step" guest_stopped b true
}

# --- the net records (steps 2 and 5) ------------------------------------------------------------------------------
net_item() {   # FILE STEP KEY KIND LABEL CMD...: one item, its exit status after it; a non-zero one is FAILED-to-read.
	# The value is read from the command's stdout alone: a warning on its stderr is never the value. On success, stderr's
	# first line is kept apart (a `stderr:` line, the fact KEY_stderr); on a failure it is what FAILED-to-read shows
	local f="$1" s="$2" k="$3" kind="$4" label="$5" out err why e="$WORK/net-item.err" rc=0 val=""
	shift 5
	out="$("$@" 2> "$e")" || rc=$?
	err="$(cat "$e" 2>/dev/null || true)"
	rm -f "$e"
	case "$kind" in
		line) val="${out%%$'\n'*}" ;;
		brnf) val="$(printf '%s\n' "$out" | grep -c '^br_netfilter ' || true)" ;;
		counts) val="$(printf '%s\n' "$out" | python3 "$TOOL" iptables-counts)" ;;
	esac
	why="${err%%$'\n'*}"; [ -n "$why" ] || why="${out%%$'\n'*}"
	{
		echo "== $label"
		if [ "$rc" = 0 ]; then
			printf '%s\n' "$val"
			[ -z "$err" ] || printf 'stderr: %s\n' "${err%%$'\n'*}"
		else
			printf 'FAILED-to-read: %s\n' "$why"
		fi
		echo "== exit $rc"
	} >> "$f"
	if [ "$rc" = 0 ]; then fact "$s" "$k" s "$val"; else fact "$s" "$k" s "FAILED-to-read (exit $rc)"; fi
	fact "$s" "${k}_exit" i "$rc"
	if [ "$rc" = 0 ] && [ -n "$err" ]; then fact "$s" "${k}_stderr" s "${err%%$'\n'*}"; fi
}
NET_KEYS="ip_forward forward_policy br_netfilter bridge_nf_call_iptables rule_counts"
net_record() {   # FILE STEP
	local f="$1" s="$2"
	echo "== $s: the forwarding and netfilter state; each command's exit status follows it, and a non-zero one marks that item FAILED-to-read, never a value" > "$f"
	net_item "$f" "$s" ip_forward line "sysctl net.ipv4.ip_forward" sysctl net.ipv4.ip_forward
	net_item "$f" "$s" forward_policy line "sudo -n iptables -S FORWARD: its first line, the policy" sudo -n iptables -S FORWARD
	net_item "$f" "$s" br_netfilter brnf "lsmod: its br_netfilter lines, counted" lsmod
	net_item "$f" "$s" bridge_nf_call_iptables line \
		"sysctl net.bridge.bridge-nf-call-iptables (absent while br_netfilter is not loaded)" sysctl net.bridge.bridge-nf-call-iptables
	net_item "$f" "$s" rule_counts counts "sudo -n iptables-save: its -A rules per table, counted" sudo -n iptables-save
}

# --- the smokes (steps 3 and 5) -------------------------------------------------------------------------------------
run_smoke() {   # N: latency_probe.py on :7100; kept: its exit status and its RESULT line's bad and rej
	local n="$1" f="$OUT/smoke-$1.txt" out rc=0 parsed res bad rej pass=no
	out="$(python3 "$HERE/latency_probe.py" --host "$GUEST" --port 7100 --n 20 --warmup 0 2>&1)" || rc=$?
	parsed="$(printf '%s\n' "$out" | python3 "$TOOL" smoke)"
	out=""
	res="$(printf '%s\n' "$parsed" | sed -n 's/^result_line //p')"
	bad="$(printf '%s\n' "$parsed" | sed -n 's/^bad //p')"
	rej="$(printf '%s\n' "$parsed" | sed -n 's/^rej //p')"
	if [ "$rc" = 0 ] && [ "$res" = yes ] && [ "$bad" = 0 ] && [ "$rej" = 0 ]; then pass=yes; fi
	{
		echo "smoke $n: latency_probe.py --host $GUEST --port 7100 --n 20 --warmup 0 (prep gap 4m)"
		echo "exit $rc"
		echo "result line: $res"
		echo "bad $bad"
		echo "rej $rej"
		if [ "$pass" = yes ]; then echo "smoke $n: PASS"; else echo "smoke $n: FAIL"; fi
		echo "kept: the probe's exit status and its bad and rej counts, nothing else of its output (a functional session)"
	} > "$f"
	fact "smoke-$n" exit i "$rc"
	fact "smoke-$n" result_line b "$([ "$res" = yes ] && echo true || echo false)"
	case "$bad" in ''|*[!0-9]*) fact "smoke-$n" bad s "${bad:-none}" ;; *) fact "smoke-$n" bad i "$bad" ;; esac
	case "$rej" in ''|*[!0-9]*) fact "smoke-$n" rej s "${rej:-none}" ;; *) fact "smoke-$n" rej i "$rej" ;; esac
	fact "smoke-$n" pass b "$([ "$pass" = yes ] && echo true || echo false)"
	say "smoke $n on :7100: $([ "$pass" = yes ] && echo PASS || echo FAIL) (exit $rc)"
}
smoke_not_run() {   # N WHY
	printf '%s\n' "smoke $1: not run: $2" "smoke $1: FAIL" > "$OUT/smoke-$1.txt"
	fact "smoke-$1" pass b false
	fact "smoke-$1" not_run s "$2"
}

# --- the probes (step 11) ----------------------------------------------------------------------------------------
modes_of() {   # IMAGE: the suite's modes that need it
	case "$1" in
		bridge|host-venv) echo "broker replay can" ;;
		*) echo broker ;;
	esac
}
klog_read() {   # the kernel log's `undefined instruction` lines, read with sudo -n; returns 1 when the read failed
	local out rc=0
	out="$(sudo -n dmesg 2>/dev/null)" || rc=$?
	[ "$rc" = 0 ] || return 1
	printf '%s\n' "$out" | grep -i 'undefined instruction' || true
}
klog_before() { KB_OK=yes; KB="$(klog_read)" || KB_OK=no; }
klog_after() {   # NAME: the matching lines logged since klog_before, or "unreadable"
	local ka ok=yes new=""
	ka="$(klog_read)" || ok=no
	if [ "$KB_OK" = yes ] && [ "$ok" = yes ]; then
		pfact "$1" kernel_log s read
		new="$(printf '%s\n' "$ka" | grep -vxF -f <(printf '%s\n' "$KB") || true)"
	else
		pfact "$1" kernel_log s unreadable
	fi
	pfact "$1" kernel_lines lines "$new"
}
verdict() {   # NAME RC [WHY]: pass or not; an image that does not pass puts its modes into the skip list
	local name="$1" rc="$2" why="${3:-}" klog kl
	klog="$(cat "$WORK/probes/$name/kernel_log.s")"
	kl="$(cat "$WORK/probes/$name/kernel_lines.lines")"
	if [ -z "$why" ]; then
		case "$rc" in
			132) why="exit 132 (SIGILL)" ;;
			124) why="exit 124: no exit within the probe's bound" ;;
			125|126|127) why="exit $rc: docker could not run the probe" ;;
			*) [ "$rc" -lt 128 ] || why="exit $rc: ended by signal $((rc - 128))" ;;
		esac
	fi
	[ -n "$why" ] || [ "$klog" = read ] || why="kernel log unreadable"
	[ -n "$why" ] || [ -z "$kl" ] || why="a kernel line matching 'undefined instruction' since the probe began"
	pfact "$name" sigill b "$([ "$rc" = 132 ] && echo true || echo false)"
	if [ -z "$why" ]; then
		pfact "$name" pass b true; pfact "$name" result s pass
		say "probe $name: pass (exit $rc)"
	else
		# shellcheck disable=SC2046  # the modes are words
		skip_modes probes "$name: $why" $(modes_of "$name")
		pfact "$name" pass b false; pfact "$name" result s "$why"
		say "probe $name: $why; skipped: $(modes_of "$name")"
	fi
	python3 "$TOOL" probes-json --work "$WORK" --out "$OUT/probes.json"
}
still_runs() {   # PID: whether a probe's `sudo -n docker run` still runs, read from /proc, never by kill -0: sudo is
	# setuid root, and this user may signal it only while its front-end keeps this user's real uid (UNVERIFIED on jammy).
	# Like kill -0, it still sees a child this shell has not reaped yet.
	[ -d "/proc/$1" ]
}
probe_gone() {   # PID CONTAINER: a probe's container removed and its `sudo -n docker run` waited for. Never a signal into
	# the container: a PID 1 with no handler ignores TERM, and the docker CLI goes on waiting for it. docker rm -f, 30 s
	# for the CLI to return: the bound. Only then TERM to sudo (which relays it), 10 s, and KILL to sudo alone, each of
	# which sudo may refuse (EPERM, above); the step's cap is the last bound.
	local pid="$1" c="$2" i
	timeout 60 sudo -n docker rm -f "$c" >/dev/null 2>&1 || true
	for i in $(seq 1 60); do still_runs "$pid" || return 0; sleep 0.5; done
	kill "$pid" 2>/dev/null || true
	for i in $(seq 1 20); do still_runs "$pid" || return 0; sleep 0.5; done
	kill -KILL "$pid" 2>/dev/null || true
}
probe_docker() {   # NAME KIND REF RUN-ARGS...: one probe container, --rm, --network none, named for the clean stop; at
	# its bound the container is removed (probe_gone), so the bound holds whatever the container does with TERM
	local name="$1" kind="$2" ref="$3" c="sdv-setup-probe-$1" log="$WORK/probe-$1.log" pid end rc=0 bound=no why=""
	shift 3
	pfact "$name" kind s "$kind"; pfact "$name" ref s "$ref"
	pfact "$name" probe lines "$(printf '%s\n' "$@")"
	[ "$HOST_MODE" != orin ] || pfact "$name" cpuset s "$SDV_CONTAINER_CPUSET"
	klog_before
	sudo -n docker run --rm --network none --name "$c" --label sdv.setup.probe=1 ${PROBE_CPUSET[@]+"${PROBE_CPUSET[@]}"} "$@" \
		> "$log" 2>&1 < /dev/null &
	pid=$!
	end=$((SECONDS + PROBE_BOUND_S))
	while still_runs "$pid" && [ "$SECONDS" -lt "$end" ]; do sleep 0.2; done
	if still_runs "$pid"; then bound=yes; probe_gone "$pid" "$c"; fi
	wait "$pid" || rc=$?
	klog_after "$name"
	pfact "$name" exit i "$rc"
	pfact "$name" bound_fired b "$([ "$bound" = yes ] && echo true || echo false)"
	pfact "$name" output_tail lines "$(tail -n 12 "$log" 2>/dev/null || true)"
	rm -f "$log"
	[ "$bound" = no ] || why="no exit within the probe's bound ($PROBE_BOUND_S s): its container removed"
	verdict "$name" "$rc" "$why"
}
probe_databroker() {   # NAME REF: the stack's arguments until Listening, a settle, then the harness stops it
	local name="$1" ref="$2" c="sdv-setup-probe-$1" log="$WORK/probe-$1.log" pid end listening=no early=no stop_rc="" rc=0 why=""
	pfact "$name" kind s upstream; pfact "$name" ref s "$ref"
	pfact "$name" probe lines "$(printf '%s\n' "--read-only" "-v VSS_HOME/gen:/in:ro" "--vss /in/vss-databroker.json" \
		"--address 127.0.0.1 --port 55555 --insecure" "until: Listening on 127.0.0.1:55555, then docker stop -t 5")"
	[ "$HOST_MODE" != orin ] || pfact "$name" cpuset s "$SDV_CONTAINER_CPUSET"
	klog_before
	sudo -n docker run --rm --network none --name "$c" --label sdv.setup.probe=1 ${PROBE_CPUSET[@]+"${PROBE_CPUSET[@]}"} --read-only \
		-e KUKSA_DATABROKER_ADDR=127.0.0.1 -v "$VSS_HOME/gen:/in:ro" "$ref" \
		--vss /in/vss-databroker.json --address 127.0.0.1 --port 55555 --insecure > "$log" 2>&1 &
	pid=$!
	end=$((SECONDS + LISTEN_BOUND_S))
	while :; do
		if grep -q 'Listening on 127\.0\.0\.1:55555' "$log" 2>/dev/null; then listening=yes; break; fi
		still_runs "$pid" || break
		[ "$SECONDS" -lt "$end" ] || break
		sleep 0.2
	done
	[ "$listening" = no ] || sleep "$LISTEN_SETTLE_S"
	if still_runs "$pid"; then
		stop_rc=0; timeout 60 sudo -n docker stop -t 5 "$c" >/dev/null 2>&1 || stop_rc=$?
		for _ in $(seq 1 60); do still_runs "$pid" || break; sleep 0.5; done
		if still_runs "$pid"; then probe_gone "$pid" "$c"; fi
	else
		early=yes
	fi
	wait "$pid" || rc=$?
	klog_after "$name"
	pfact "$name" listening b "$([ "$listening" = yes ] && echo true || echo false)"
	pfact "$name" exited_before_stop b "$([ "$early" = yes ] && echo true || echo false)"
	[ -z "$stop_rc" ] || pfact "$name" stop_exit i "$stop_rc"
	pfact "$name" exit i "$rc"
	pfact "$name" output_tail lines "$(tail -n 12 "$log" 2>/dev/null || true)"
	rm -f "$log"
	if [ "$listening" = no ] && [ "$early" = yes ]; then
		why="exit $rc before a Listening line"
		[ "$rc" != 132 ] || why="exit 132 (SIGILL) before a Listening line"
	elif [ "$listening" = no ]; then
		why="no Listening line within the bound"
	elif [ "$early" = yes ]; then
		why="exit $rc before the harness stopped it"
	fi
	# Its exit status after the stop is recorded above, apart from the verdict: 0 on a stop, 137 had the -t 5 run out.
	verdict "$name" 0 "$why"
	pfact "$name" sigill b "$([ "$rc" = 132 ] && echo true || echo false)"
	python3 "$TOOL" probes-json --work "$WORK" --out "$OUT/probes.json"
}
probe_not_started() {   # NAME KIND REF WHY: the Orin mode's probe container not started (a QEMU still runs at step 11);
	# it does not pass, and its image's modes go into the skip list, as verdict() does for a probe that fails
	local name="$1" why="$4"
	pfact "$name" kind s "$2"; pfact "$name" ref s "$3"
	pfact "$name" started b false
	# shellcheck disable=SC2046  # the modes are words
	skip_modes probes "$name: $why" $(modes_of "$name")
	pfact "$name" pass b false; pfact "$name" result s "$why"
	say "probe $name: not started; skipped: $(modes_of "$name")"
	python3 "$TOOL" probes-json --work "$WORK" --out "$OUT/probes.json"
}
probe_venv() {   # the host venv's imports, then a load of the staged DBC
	local name=host-venv v="$VSS_HOME/venv/bin/python" dbc out="" rc=0 out2="" rc2=""
	dbc="$(ls "$VSS_HOME"/cache/dbc/*.dbc)"
	pfact "$name" kind s venv; pfact "$name" ref s "VSS_HOME/venv/bin/python"
	pfact "$name" probe lines "$(printf '%s\n' "-c $PROBE_VENV" "-c $PROBE_DBC (the staged DBC)")"
	klog_before
	out="$(timeout --foreground --kill-after=10s "$PROBE_BOUND_S" "$v" -c "$PROBE_VENV" 2>&1)" || rc=$?
	if [ "$rc" = 0 ]; then
		rc2=0; out2="$(timeout --foreground --kill-after=10s "$PROBE_BOUND_S" "$v" -c "$PROBE_DBC" "$dbc" 2>&1)" || rc2=$?
	fi
	klog_after "$name"
	pfact "$name" exit i "$rc"
	[ -z "$rc2" ] || pfact "$name" dbc_load_exit i "$rc2"
	pfact "$name" output_tail lines "$(printf '%s\n%s\n' "$out" "$out2" | grep -v '^$' | tail -n 12 || true)"
	if [ "$rc" = 0 ] && [ -n "$rc2" ]; then rc="$rc2"; fi
	verdict "$name" "$rc"
}

# --- the steps ----------------------------------------------------------------------------------------------------
step_preflight() {
	local s=preflight rc=0 out c_repo c_bundle
	[ -d "$REPO/sdv" ] || die_step $s "no $REPO/sdv: the repo tarball is not the vss form (scripts/aws/.env.example)"
	[ -r "$STACK/bundle.py" ] || die_step $s "no $STACK/bundle.py"
	[ -r "$IFS_BIN" ] && [ -r "$DISK" ] || die_step $s "IFS_BIN or DISK is not readable"
	if guest_runs; then die_step $s "a QEMU runs already: the guest this harness boots would be a second one"; fi
	fact $s qemu_running b false
	fact $s image s "$(basename "$IFS_BIN")"
	{
		echo "== preflight: df -h /"
		rc=0; df -h / 2>&1 || rc=$?; echo "== exit $rc"
		echo "== preflight: free -m"
		rc=0; free -m 2>&1 || rc=$?; echo "== exit $rc"
	} >> "$OUT/df.txt"
	rc=0; out="$(python3 "$STACK/bundle.py" verify --in "$VSS_IN" 2>&1)" || rc=$?
	fact $s verify_exit i "$rc"
	printf '%s\n' "$out" | python3 "$TOOL" bundle --facts "$WORK/facts/$s" --prefix verify_
	[ "$rc" = 0 ] || die_step $s "bundle.py verify --in VSS_IN failed (exit $rc; its problems are in run.log)"
	c_repo="$(sed -n 's/^REPO_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' "$W/inputs.env" 2>/dev/null | head -n 1)"
	c_bundle="$(python3 "$TOOL" field --file "$VSS_IN/bundle.json" --key commit)" || c_bundle=""
	fact $s repo_commit s "$c_repo"
	fact $s bundle_commit s "$c_bundle"
	if [ -z "$c_repo" ] || [ "$c_bundle" != "$c_repo" ]; then
		fact $s commit_match b false
		die_step $s "bundle.json's commit '$c_bundle' is not inputs.env's REPO_COMMIT '$c_repo'"
	fi
	fact $s commit_match b true
	say "preflight: the bundle verified, its commit the tarball's"
}

step_net_before() {
	net_record "$OUT/net-before.txt" net-before
}

step_guest() {
	local s=guest c="$OUT/guest/00-setup-console.log" l="$OUT/guest/00-setup-launch.log" rc=0 t0 i ready=no n=0
	mkdir -p "$OUT/guest" "$WORK/state"
	: > "$WORK/state/launched"
	t0="$(vss_now)"
	IFS_BIN="$IFS_BIN" DISK="$DISK" LOG="$c" bash "$HERE/launch-qnx-kvm-bridged.sh" 2>&1 \
		| sed -E 's/^guest up after [0-9]+s /guest up /' > "$l" || rc=$?
	fact $s operational_s/boot i "$(( $(vss_now) - t0 ))"
	fact $s launch_exit i "$rc"
	if [ "$rc" != 0 ]; then
		fact $s booted b false
		say "the guest did not boot (the launch script exited $rc): recorded, QEMU stopped, setup goes on"
		stop_guest $s
		smoke_not_run 1 "the guest did not boot"
		return 0
	fi
	if [ "$HOST_MODE" = orin ] && ! repin_after_boot $s; then
		fact $s booted b false
		say "the guest's QEMU could not be pinned to its cores (VSS_REPIN boot exited $REPIN_RC): recorded as a guest that did" \
			"not boot, QEMU stopped, setup goes on"
		stop_guest $s
		smoke_not_run 1 "VSS_REPIN boot exited $REPIN_RC: the guest's QEMU is not on its cores"
		return 0
	fi
	fact $s booted b true
	: > "$WORK/state/guest-booted"
	# Readiness: one connect-and-close, no bytes, never a held descriptor; never the banner.
	for i in $(seq 1 "$READY_TRIES"); do
		n="$i"
		if timeout "$READY_BOUND_S" bash -c "exec 3<>/dev/tcp/$GUEST/7160 && exec 3>&-" 2>/dev/null; then ready=yes; break; fi
		sleep 1
	done
	fact $s ready_7160 b "$([ "$ready" = yes ] && echo true || echo false)"
	fact $s ready_7160_attempts i "$n"
	# C12b's lines: information; the five instances share one console and their lines can interleave.
	for i in $(seq 1 $((RULES_WAIT_S * 2))); do
		if [ "$(python3 "$TOOL" rules --console "$c" --images "$STACK/images.json" --facts "$WORK/facts/$s")" -ge 5 ]; then break; fi
		if [ "$i" -lt $((RULES_WAIT_S * 2)) ]; then sleep 0.5; fi
	done
	say "guest up; :7160 readiness $ready after $n attempt(s); vss rules lines: $(cat "$WORK/facts/$s/c12b_lines.i" 2>/dev/null || echo none)"
	run_smoke 1
}

step_docker() {
	local s=docker rc=0 pol cand ver="" ds dt sd major i user groups sum f="$OUT/docker-facts.txt" a="$OUT/apt.log"
	if [ "$HOST_MODE" = orin ]; then
		user="$(id -un)" || die_step $s "id -un failed"
		# Docker as the host has it (ORIN MODE): daemon.json hashed, never written or read for its content; no apt
		sum="$(daemon_json_sha256)" || die_step $s "sudo -n sha256sum $DAEMON_JSON failed: its hash is what the close compares"
		fact $s daemon_json_sha256 s "$sum"
		groups="$(id -nG "$user" 2>&1)" || die_step $s "id -nG for this login failed"
		case " $groups " in
			*" docker "*) fact $s docker_group_before b true ;;
			*) fact $s docker_group_before b false ;;
		esac
	else
		printf '%s\n' '{"features": {"containerd-snapshotter": true}}' > "$WORK/daemon.json"
		sudo -n mkdir -p /etc/docker || die_step $s "sudo -n mkdir -p /etc/docker failed"
		sudo -n install -m 0644 "$WORK/daemon.json" /etc/docker/daemon.json || die_step $s "writing /etc/docker/daemon.json failed"
		fact $s daemon_json s '{"features": {"containerd-snapshotter": true}}'
		echo "== apt-get update" >> "$a"
		rc=0; sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update -qq >> "$a" 2>&1 || rc=$?
		echo "== exit $rc" >> "$a"
		fact $s apt_update_exit i "$rc"
		rc=0; pol="$(apt-cache policy docker.io 2>&1)" || rc=$?
		cand="$(printf '%s\n' "$pol" | sed -n 's/^ *Candidate: *//p' | head -n 1)"
		fact $s candidate s "${cand:-none}"
		if [ "$rc" != 0 ] || [ -z "$cand" ] || [ "$cand" = "(none)" ]; then
			die_step $s "apt-cache policy shows no candidate for docker.io (exit $rc)"
		fi
		echo "== apt-get install -y -qq docker.io" >> "$a"
		rc=0; sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >> "$a" 2>&1 || rc=$?
		echo "== exit $rc" >> "$a"
		fact $s install_exit i "$rc"
		[ "$rc" = 0 ] || die_step $s "apt-get install docker.io exited $rc (apt.log)"
	fi
	sudo -n usermod -aG docker "${user:-$(id -un)}" || die_step $s "sudo -n usermod -aG docker failed"
	for i in $(seq 1 "$DOCKERD_WAIT_S"); do
		ver="$(sudo -n docker version -f '{{.Server.Version}}' 2>/dev/null)" && [ -n "$ver" ] && break
		ver=""; sleep 1
	done
	ver="${ver%%$'\n'*}"
	[ -n "$ver" ] || die_step $s "dockerd does not answer"
	ds="$(sudo -n docker info -f '{{json .DriverStatus}}' 2>&1)" || die_step $s "docker info (its DriverStatus) failed"
	dt="$(printf '%s\n' "$ds" | python3 "$TOOL" driver-type)"
	sd="$(sudo -n docker info -f '{{.Driver}}' 2>&1)" || die_step $s "docker info (its storage driver) failed"
	major="${ver%%.*}"
	{
		echo "== dpkg-query -W docker.io containerd"
		rc=0; dpkg-query -W docker.io containerd 2>&1 || rc=$?; echo "== exit $rc"
		if [ "$HOST_MODE" != orin ]; then
			rc=0; pol="$(apt-cache policy docker.io containerd 2>&1)" || rc=$?
			echo "== apt-cache policy docker.io containerd: the package, installed, candidate, version and source lines"
			printf '%s\n' "$pol" | grep -E "$POLICY_LINES" || true
			echo "== exit $rc"
		fi
		echo "== docker server version: $ver"
		echo "== docker storage driver: $sd"
		echo "== docker image store driver-type: ${dt:-none}"
	} > "$f"
	fact $s server_version s "$ver"
	case "$major" in ''|*[!0-9]*) fact $s server_major s "$major" ;; *) fact $s server_major i "$major" ;; esac
	fact $s storage_driver s "$sd"
	fact $s driver_type s "${dt:-none}"
	[ "$dt" = "$STORE" ] || die_step $s "the image store is not containerd's: driver-type '${dt:-none}', not $STORE"
	[ "$major" = "$MAJOR" ] || die_step $s "the server's major version is $major, not $MAJOR (section 5)"
	say "docker: server $ver, store $dt"
}

step_after_docker() {
	local s=after-docker k b a be ae v
	net_record "$OUT/net-after.txt" net-after
	for k in $NET_KEYS; do
		b="$(cat "$WORK/facts/net-before/$k.s" 2>/dev/null || echo missing)"
		a="$(cat "$WORK/facts/net-after/$k.s" 2>/dev/null || echo missing)"
		be="$(cat "$WORK/facts/net-before/${k}_exit.i" 2>/dev/null || echo missing)"
		ae="$(cat "$WORK/facts/net-after/${k}_exit.i" 2>/dev/null || echo missing)"
		if [ "$be" != 0 ] || [ "$ae" != 0 ]; then v=unreadable; elif [ "$b" = "$a" ]; then v=same; else v=changed; fi
		fact net-change "$k" s "$v"
	done
	if [ -e "$WORK/state/guest-booted" ] && guest_runs; then run_smoke 2; else smoke_not_run 2 "no guest booted by step 3 runs"; fi
	sync
	stop_guest $s
}

vcan_from_kernel() {   # PREFIX NOTE: vcan, can and can_raw from the running kernel's own modules, no apt: the Orin mode's
	# way, and the a1.metal path's when apt has no candidate for linux-modules-extra. The modules loaded before modprobe are
	# recorded, so that the Orin helper unloads only what this setup loaded. PREFIX goes before a skip's reason, NOTE before
	# the modules loaded before in run.log's line when vcan was loaded
	local s=vcan pre="$1" note="$2" rc out m before=() ok=yes why=""
	rc=0; out="$(lsmod 2>&1)" || rc=$?
	fact $s modules_loaded_before_exit i "$rc"
	if [ "$rc" = 0 ]; then
		for m in vcan can can_raw; do
			case $'\n'"$out" in *$'\n'"$m "*) before+=("$m") ;; esac
		done
		fact $s modules_loaded_before lines "$(printf '%s\n' ${before[@]+"${before[@]}"})"
	else
		ok=no; why="lsmod could not be read before modprobe (exit $rc): what this setup loads would not be known"
	fi
	rc=0; out="$(modinfo -F filename vcan 2>&1)" || rc=$?
	fact $s modinfo_filename s "$out"; fact $s modinfo_filename_exit i "$rc"
	if [ "$ok" = yes ] && [ "$rc" != 0 ]; then ok=no; why="no vcan module: modinfo -F filename vcan exited $rc"; fi
	rc=0; out="$(modinfo -F vermagic vcan 2>&1)" || rc=$?
	fact $s modinfo_vermagic s "$out"; fact $s modinfo_vermagic_exit i "$rc"
	if [ "$ok" = yes ]; then
		rc=0; out="$(sudo -n modprobe -a vcan can can_raw 2>&1)" || rc=$?
		fact $s modprobe_exit i "$rc"
		fact $s modprobe_output lines "$out"
		[ "$rc" = 0 ] || { ok=no; why="modprobe -a vcan can can_raw exited $rc"; }
	fi
	rc=0; out="$(lsmod 2>&1)" || rc=$?
	fact $s lsmod lines "$(printf '%s\n' "$out" | grep -E '^(vcan|can|can_raw) ' || true)"
	fact $s lsmod_exit i "$rc"
	fact $s ok b "$([ "$ok" = yes ] && echo true || echo false)"
	if [ "$ok" = no ]; then
		skip_modes $s "vcan: $pre$why" broker can
		say "vcan: $pre$why: broker and can go into the skip list (replay needs no vcan)"
	else
		say "vcan: loaded from the kernel's own modules (${note}before: ${before[*]:-none})"
	fi
}

step_vcan() {
	local s=vcan kr pkg pol prc=0 cand rc out ok=yes why=""
	if [ "$HOST_MODE" = orin ]; then vcan_from_kernel "" ""; return 0; fi
	kr="$(uname -r)"; pkg="linux-modules-extra-$kr"
	fact $s package s "$pkg"
	pol="$(apt-cache policy "$pkg" 2>&1)" || prc=$?
	cand="$(printf '%s\n' "$pol" | sed -n 's/^ *Candidate: *//p' | head -n 1)"
	{
		echo "== apt-cache policy $pkg: the package, installed, candidate, version and source lines"
		printf '%s\n' "$pol" | grep -E "$POLICY_LINES" || true
		echo "== exit $prc"
	} >> "$OUT/docker-facts.txt"
	fact $s candidate s "${cand:-none}"
	if [ "$prc" != 0 ] || [ -z "$cand" ] || [ "$cand" = "(none)" ]; then
		# no package to install (an AMI's kernel the archive has no extra package for): the running kernel's own modules,
		# as the Orin mode takes them; the one fact the package path never writes says so
		fact $s source s running-kernel
		vcan_from_kernel "no candidate for $pkg in apt-cache policy, and from the running kernel: " "no candidate for $pkg; "
		return 0
	fi
	echo "== apt-get install -y -qq $pkg" >> "$OUT/apt.log"
	rc=0; sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$pkg" >> "$OUT/apt.log" 2>&1 || rc=$?
	echo "== exit $rc" >> "$OUT/apt.log"
	fact $s install_exit i "$rc"
	[ "$rc" = 0 ] || { ok=no; why="apt-get install $pkg exited $rc (apt.log)"; }
	if [ "$ok" = yes ]; then
		rc=0; out="$(sudo -n modprobe -a vcan can can_raw 2>&1)" || rc=$?
		fact $s modprobe_exit i "$rc"
		fact $s modprobe_output lines "$out"
		[ "$rc" = 0 ] || { ok=no; why="modprobe -a vcan can can_raw exited $rc"; }
	fi
	rc=0; out="$(lsmod 2>&1)" || rc=$?
	fact $s lsmod lines "$(printf '%s\n' "$out" | grep -E '^(vcan|can|can_raw) ' || true)"
	fact $s lsmod_exit i "$rc"
	rc=0; out="$(modinfo -F filename vcan 2>&1)" || rc=$?
	fact $s modinfo_filename s "$out"; fact $s modinfo_filename_exit i "$rc"
	rc=0; out="$(modinfo -F vermagic vcan 2>&1)" || rc=$?
	fact $s modinfo_vermagic s "$out"; fact $s modinfo_vermagic_exit i "$rc"
	fact $s ok b "$([ "$ok" = yes ] && echo true || echo false)"
	if [ "$ok" = no ]; then
		skip_modes $s "vcan: $why" broker can
		say "vcan: $why: broker and can go into the skip list (replay needs no vcan)"
	else
		say "vcan: loaded"
	fi
}

step_load() {
	local s=load rc=0 out
	out="$(sudo -n docker load -i "$VSS_IN/$IMAGES_TAR" 2>&1)" || rc=$?
	fact $s docker_load_exit i "$rc"
	fact $s docker_load lines "$out"
	[ "$rc" = 0 ] || die_step $s "docker load exited $rc"
	rc=0; out="$(python3 "$STACK/bundle.py" verify --in "$VSS_IN" --loaded --docker 'sudo -n docker' 2>&1)" || rc=$?
	fact $s verify_exit i "$rc"
	printf '%s\n' "$out" | python3 "$TOOL" bundle --facts "$WORK/facts/$s" --prefix verify_loaded_
	[ "$rc" = 0 ] || die_step $s "bundle.py verify --loaded failed (exit $rc; its problems are in run.log)"
	say "load: the three arm64 images loaded and verified"
}

step_pulls() {
	local s=pulls list kind name ref rc out failed="" n=0
	list="$(python3 "$TOOL" images --file "$STACK/images.json" --kind upstream)"
	while read -r kind name ref <&3; do
		[ "$kind" = upstream ] || continue
		n=$((n + 1))
		rc=0; out="$(vss_capped sudo -n docker pull "$ref" 2>&1 < /dev/null)" || rc=$?
		fact $s "$name/exit" i "$rc"
		if vss_cap_fired "$rc"; then say "the pull of $name ran into its cap"; exit 124; fi
		fact $s "$name/output_tail" lines "$(printf '%s\n' "$out" | tail -n 3)"
		[ "$rc" = 0 ] || failed="$failed $name"
	done 3<<< "$list"
	[ "$n" = 4 ] || die_step $s "images.json names $n upstream images, not four"
	rc=0; out="$(python3 "$STACK/bundle.py" verify-upstream --docker 'sudo -n docker' 2>&1)" || rc=$?
	fact $s verify_exit i "$rc"
	printf '%s\n' "$out" | python3 "$TOOL" bundle --facts "$WORK/facts/$s" --prefix verify_upstream_
	[ -z "$failed" ] || die_step $s "docker pull failed for:$failed"
	[ "$rc" = 0 ] || die_step $s "bundle.py verify-upstream failed (exit $rc; its problems are in run.log)"
	say "pulls: the four upstream images pulled by digest and verified"
}

step_venv() {
	local s=venv up pbs py v rc=0 ver f="$OUT/venv.txt"
	up="$(python3 "$TOOL" field --file "$REPO/sdv/sim/python-aarch64.json" --key upload_name)" \
		|| die_step $s "sdv/sim/python-aarch64.json names no upload_name"
	pbs="$VSS_IN/$up"
	[ -r "$pbs" ] || die_step $s "no $up in VSS_IN"
	[ ! -e "$VSS_HOME/py312" ] && [ ! -e "$VSS_HOME/venv" ] || die_step $s "VSS_HOME/py312 or VSS_HOME/venv exists already"
	mkdir -p "$VSS_HOME/py312"
	tar -xzf "$pbs" -C "$VSS_HOME/py312" --no-same-owner || die_step $s "unpacking $up failed"
	py="$VSS_HOME/py312/python/bin/python3"
	[ -x "$py" ] || die_step $s "$up holds no python/bin/python3"
	"$py" -m venv "$VSS_HOME/venv" || die_step $s "python -m venv failed"
	v="$VSS_HOME/venv/bin/python"
	ver="$("$v" --version 2>&1)" || die_step $s "the venv's python does not run"
	{ echo "== venv/bin/python --version"; printf '%s\n' "$ver"; } > "$f"
	fact $s python_version s "$ver"
	echo "== pip install --require-hashes --no-deps -r sdv/sim/requirements.aarch64.lock" >> "$f"
	"$v" -m pip install --require-hashes --no-deps --no-input --disable-pip-version-check --progress-bar off \
		-r "$REPO/sdv/sim/requirements.aarch64.lock" >> "$f" 2>&1 || rc=$?
	echo "== exit $rc" >> "$f"
	fact $s pip_install_exit i "$rc"
	[ "$rc" = 0 ] || die_step $s "pip install exited $rc (venv.txt)"
	echo "== pip freeze" >> "$f"
	rc=0; "$v" -m pip freeze --disable-pip-version-check >> "$f" 2>&1 || rc=$?
	echo "== exit $rc" >> "$f"
	fact $s pip_freeze_exit i "$rc"
	[ "$rc" = 0 ] || die_step $s "pip freeze exited $rc (venv.txt)"
	say "venv: $ver, the aarch64 sim lock installed"
}

step_stage() {
	local s=stage t n log recs=() dbcs=() x b sha got
	[ ! -e "$VSS_HOME/gen" ] || die_step $s "VSS_HOME/gen exists already"
	tar -xf "$VSS_IN/sdv-gen.tar" -C "$VSS_HOME" --no-same-owner || die_step $s "unpacking sdv-gen.tar failed"
	[ -r "$VSS_HOME/gen/manifest.json" ] || die_step $s "sdv-gen.tar holds no gen/manifest.json"
	mkdir -p "$VSS_HOME/recordings"
	for t in "$VSS_IN"/rec-*.tar; do
		[ -e "$t" ] || continue
		n="$(basename "$t" .tar)"; n="${n#rec-}"
		[ ! -e "$VSS_HOME/recordings/$n" ] || die_step $s "VSS_HOME/recordings/$n exists already"
		tar -xf "$t" -C "$VSS_HOME/recordings" --no-same-owner || die_step $s "unpacking rec-$n.tar failed"
		# the log its manifest line names (vss_setup.py log: sigsim.log, or a CARLA recording's carla.log), never a fixed name
		log="$(python3 "$TOOL" log --dir "$VSS_HOME/recordings/$n" 2>&1)" || die_step $s "rec-$n.tar: $log"
		[ -r "$VSS_HOME/recordings/$n/$log" ] || die_step $s "rec-$n.tar holds no $n/$log"
		recs+=("$n")
	done
	[ "${#recs[@]}" -gt 0 ] || die_step $s "the bundle holds no recording"
	for x in "$VSS_IN"/*.dbc; do
		b="$(basename "$x")"
		if [[ "$b" =~ ^[0-9a-f]{64}\.dbc$ ]]; then dbcs+=("$x"); fi
	done
	[ "${#dbcs[@]}" = 1 ] || die_step $s "the bundle holds ${#dbcs[@]} DBC files, not one"
	sha="$(basename "${dbcs[0]}" .dbc)"
	mkdir -p "$VSS_HOME/cache/dbc"
	[ ! -e "$VSS_HOME/cache/dbc/$sha.dbc" ] || die_step $s "VSS_HOME/cache/dbc/$sha.dbc exists already"
	cp "${dbcs[0]}" "$VSS_HOME/cache/dbc/$sha.dbc"
	got="$(sha256sum "$VSS_HOME/cache/dbc/$sha.dbc" | cut -d' ' -f1)"
	[ "$got" = "$sha" ] || die_step $s "the staged DBC hashes to $got, not its name"
	fact $s gen b true
	fact $s recordings lines "$(printf '%s\n' "${recs[@]}")"
	fact $s dbc_sha256 s "$sha"
	say "stage: gen, ${#recs[@]} recording(s) and the DBC staged in VSS_HOME"
}

step_probes() {
	local list kind name ref et rc=0 held=""
	: > "$WORK/state/probes-started"
	# Whether the kernel logs a user-space SIGILL at all (arm64: only with debug.exception-trace set), read, never set
	et="$(sysctl -n debug.exception-trace 2>/dev/null)" || rc=$?
	if [ "$rc" = 0 ]; then fact probes exception_trace s "$et"; else fact probes exception_trace s "unreadable (exit $rc)"; fi
	if [ "$HOST_MODE" = orin ]; then
		# ORIN MODE: QEMU is re-pinned after every container start while the guest runs; this step re-pins nothing, so a
		# QEMU still listed here (step 5's stop, KILL included, did not end it: one no pin reaches) gets no container beside it
		if guest_runs; then
			fact probes qemu_listed b true
			held="not started: a QEMU still runs at step 11 (step 5's stop, KILL included, did not end it), and no container"
			held="$held starts beside the guest without a re-pin after it (plan 3.7)"
			say "probes: a QEMU still runs at step 11, so no probe container starts beside it; the host venv's probe still runs"
		else
			fact probes qemu_listed b false
		fi
	fi
	list="$(python3 "$TOOL" images --file "$STACK/images.json")"
	while read -r kind name ref <&3; do
		if [ -n "$held" ]; then probe_not_started "$name" "$kind" "$ref" "$held"; continue; fi
		case "$name" in
			kuksa-databroker) probe_databroker "$name" "$ref" ;;
			kuksa-can-provider|kuksa-csv-provider) probe_docker "$name" "$kind" "$ref" "$ref" --help ;;
			kuksa-mock-provider) probe_docker "$name" "$kind" "$ref" --entrypoint python "$ref" -c "$PROBE_MOCK" ;;
			hard-brake-hazard|kuksa-csv-provider-recorder) probe_docker "$name" "$kind" "$ref" --entrypoint python "$ref" -c "$PROBE_IMPORT" ;;
			bridge) probe_docker "$name" "$kind" "$ref" --read-only "$ref" check ;;
			*) die_step probes "images.json names $kind image $name, which has no probe here" ;;
		esac
	done 3<<< "$list"
	probe_venv
	python3 "$TOOL" probes-json --work "$WORK" --out "$OUT/probes.json"
}

step_30min_rule() {
	local left
	left=$((VSS_STOP_AT - $(vss_now)))
	fact 30min-rule operational_s/left_to_stop_at i "$left"
	if [ "$left" -lt "$RULE_LEFT_S" ]; then
		fact 30min-rule fired b true
		: > "$WORK/state/30min-rule"
		say "the 30-minute rule: under 30 minutes left before stop_at; stop, and hand over to decision 16"
	else
		fact 30min-rule fired b false
	fi
}

step_close() {
	local rc ln out before after
	{
		echo "== close: df -h /"
		rc=0; df -h / 2>&1 || rc=$?; echo "== exit $rc"
		echo "== close: sudo -n du -sh /var/lib/docker /var/lib/containerd"
		rc=0; sudo -n du -sh /var/lib/docker /var/lib/containerd 2>&1 || rc=$?; echo "== exit $rc"
	} >> "$OUT/df.txt"
	# The guest's verdict and the skip list, said here so that wait-run's tail of run.log shows them: the suite
	# refuses a setup whose guest booted without passing (vss_setup.py, THE GUEST RULE).
	out="$(python3 "$TOOL" guest-verdict --work "$WORK" 2>&1)" || out="the guest's verdict could not be read: $out"
	while IFS= read -r ln; do say "$ln"; done <<< "$out"
	if [ "$HOST_MODE" = orin ]; then   # ORIN MODE: daemon.json as step 4 found it, or a failure with its own reason
		before="$(cat "$WORK/facts/docker/daemon_json_sha256.s" 2>/dev/null || true)"
		after="$(daemon_json_sha256)" \
			|| die_step close "sudo -n sha256sum $DAEMON_JSON failed at the close: that setup left it as step 4 found it is not shown"
		fact close daemon_json_sha256 s "$after"
		[ "$after" = "$before" ] \
			|| die_step close "$DAEMON_JSON changed during setup: sha256 ${before:-unread} at step 4, $after at the close"
		say "close: $DAEMON_JSON as step 4 found it (its sha256, read under sudo -n)"
	fi
}

# --- the parent: check points, caps, the stops ---------------------------------------------------------------------
stop_verdict() {   # REASON...: facts.stop.verified, false with the reasons (facts.stop.unverified) when the sweep could
	# not show its removals done; said in run.log, whose last 30 lines wait-run prints. The status line is not changed
	local j
	if [ "$#" = 0 ]; then fact stop verified b true; return 0; fi
	fact stop verified b false
	fact stop unverified lines "$(printf '%s\n' "$@")"
	j="$(printf '%s; ' "$@")"
	say "the stop is unverified: ${j%; }"
}
sweep() {   # the idempotent removals of every stop, DONE included, recorded under facts.stop: the guest stopped if this
	# harness booted it and it runs; the probe containers removed by name, then those still labelled counted. A QEMU that
	# outlived its KILL, a list that fails, or a probe container still listed makes the stop unverified (stop_verdict)
	local n rc=0 left unv=()
	if [ -e "$WORK/state/launched" ]; then
		stop_guest stop
		[ "$(cat "$WORK/facts/stop/guest_stopped.b" 2>/dev/null)" != false ] || unv+=("QEMU still runs after a KILL")
	fi
	if [ -e "$WORK/state/probes-started" ]; then
		for n in kuksa-databroker kuksa-can-provider kuksa-csv-provider kuksa-mock-provider hard-brake-hazard \
			kuksa-csv-provider-recorder bridge; do
			timeout 60 sudo -n docker rm -f "sdv-setup-probe-$n" >/dev/null 2>&1 || true
		done
		left="$(timeout 60 sudo -n docker ps -aq --filter label=sdv.setup.probe=1 2>/dev/null)" || rc=$?
		fact stop probe_containers_list_exit i "$rc"
		if [ "$rc" != 0 ]; then
			unv+=("the probe containers could not be listed after the removals (docker ps exit $rc)")
		else
			n="$(printf '%s\n' "$left" | grep -c . || true)"
			fact stop probe_containers_left i "$n"
			[ "$n" = 0 ] || unv+=("$n probe container(s) labelled sdv.setup.probe=1 still listed after the removals")
		fi
	fi
	stop_verdict ${unv[@]+"${unv[@]}"}
}
clean_stop() {   # a stop other than DONE: sync, then the sweep
	say "a clean stop: sync, the guest stopped if it runs, the probe containers removed"
	timeout 120 sync || true
	sweep
}

write_record() {   # STATUS STATUS-LINE AT REASON; the Orin and c7g-metal modes' records say so (host_mode), a1.metal's as before
	local mode=()
	case "$HOST_MODE" in orin|c7g-metal) mode=(--host-mode "$HOST_MODE") ;; esac
	python3 "$TOOL" record --work "$WORK" --out "$OUT/setup.json" --status "$1" --status-line "$2" --at "$3" \
		--reason "$4" --steps "${STEPS[*]}" ${mode[@]+"${mode[@]}"}
}

finish() {   # STATUS [AT [REASON]]: the record, then the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line i notrun=""
	trap - EXIT
	set +e
	if [ "$st" = DONE ]; then sweep; else clean_stop; fi
	case "$st" in
		DONE) line="status=DONE" ;;
		TIMEOUT) line="status=TIMEOUT at=$at reason=$why" ;;
		*) line="status=FAILED at=$at" ;;
	esac
	if ! write_record "$st" "$line" "$at" "$why"; then
		say "setup.json could not be written"
		if [ "$st" = DONE ]; then
			st=FAILED; at=close; line="status=FAILED at=close"
		fi
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
	if [ "$name" = 30min-rule ] && [ -e "$WORK/state/30min-rule" ]; then finish TIMEOUT 30min-rule 30min-rule; fi
}

main() {
	local i why
	CUR=preflight
	rm -rf "$WORK"
	mkdir -p "$WORK/facts" "$WORK/state" "$OUT/guest"
	: > "$WORK/steps.tsv"
	trap on_exit EXIT
	say "run-vss-setup.sh: $NSTEPS steps; a functional session, nothing timed"
	why="$(host_refusal)"
	[ -z "$why" ] || finish FAILED preflight "$why"
	[ "$HOST_MODE" != orin ] || say "the Orin mode (VSS_HOST=orin): probe containers on $SDV_CONTAINER_CPUSET, QEMU re-pinned by VSS_REPIN"
	[ "$HOST_MODE" != c7g-metal ] || say "the c7g.metal mode (VSS_HOST=c7g-metal): the a1.metal path, setup.json's host_mode c7g-metal"
	if ! vss_deadline_load; then finish FAILED preflight "no readable deadline file (lib-vss-deadline.sh)"; fi
	fact preflight deadline_readable b true
	for i in "${!STEPS[@]}"; do run_step "$((i + 1))" "${STEPS[$i]}"; done
	finish DONE
}

if [ "${1:-}" = _step ]; then   # one step, as the parent runs it under its cap
	vss_deadline_load || exit 1
	case "${2:-}" in
		preflight) step_preflight ;;
		net-before) step_net_before ;;
		guest) step_guest ;;
		docker) step_docker ;;
		after-docker) step_after_docker ;;
		vcan) step_vcan ;;
		load) step_load ;;
		pulls) step_pulls ;;
		venv) step_venv ;;
		stage) step_stage ;;
		probes) step_probes ;;
		30min-rule) step_30min_rule ;;
		close) step_close ;;
		*) echo "run-vss-setup.sh: no step '${2:-}'" >&2; exit 2 ;;
	esac
	exit 0
fi
main
