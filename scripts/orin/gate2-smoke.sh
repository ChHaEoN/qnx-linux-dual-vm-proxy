#!/usr/bin/env bash
#
# Phase 3b (A6; the board after its upgrade to L4T R39, 2026-10-04)
# gate2-smoke.sh -- Gate 2: one functional smoke per harness family on the upgraded Jetson Orin
# Nano, each a fixed command with a fixed pass rule, and one line per attempt in a log.
#
#   usage: bash gate2-smoke.sh STEP...          STEP is G0 .. G21, run in the order given
#
#   Started detached from the session's pipes, waited for in the same session, and then read:
#     setsid --wait nohup bash gate2-smoke.sh G5 > ~/gate2/run-<utc>.log 2>&1 < /dev/null &
#     tail --pid=$! -f /dev/null; wait $!; echo "exit $?"; tail -n 1 ~/gate2/gate2.log
#   A harness undoes what it changed (confinement, idle states, governor, tracing, udev's queue)
#   in an exit trap, and a session that drops must not take the run with it. Every command of a
#   step writes to files in the attempt's own directory, never to this script's output.
#   BOTH are read after every call: its exit status, and its own lines of the log (one per step
#   asked for; G19 may leave two). A status that is not 0 after PASS lines is a stop, not a pass.
#   --wait is for a shell with job control (an interactive one): there setsid forks, and without
#   it $! would be a setsid that has already gone, and the status read would be its 0, at once.
#
#   Exit 0: every step asked for passed, and the board was left as a step must leave it. 1: a
#   step failed. 2, whatever else failed: a step was refused, or the call was; or the check
#   after a step found an item of AFTER EVERY STEP wrong, also after the call's last step, whose
#   own line then stands (the next call refuses by that item); or a line could not be written to
#   the log. 64: no step, or an argument that is not exactly one step (several steps in one
#   quoted argument are not a step: nothing is run and no line is written).
#
#   What the one who starts it may give, and nothing else is read:
#     GATE2_GPU_OWNER_PRESENT=1    the owner's: he is at the board for the GPU tier
#     PROVISION_ALLOW_REMOVABLE=1  the owner's: the installer-stick rule's one override
#     GATE2_NEW_BOOT=1             once, on the first call after a boot somebody chose
#     GATE2_FRESH_CURSOR=1         once, after a stop on a kernel line has been dealt with
#     GATE2_MANIFEST, GATE2_DEPLOY_MANIFEST   the two manifests' paths, when not the default
#
# WHAT A STEP IS. One row of the Gate 2 list: the command, with exactly the row's variables, and
# the row's functional pass rule and nothing more. The result is one line appended to
# ~/gate2/gate2.log, "<step> PASS" or "<step> FAIL <check>", where <check> is the name of the
# first check of the rule that did not hold, or "refused-<what>" when the step was not run. No
# other kind of line is ever written there. A line that cannot be appended to it is not said as
# if it were there: the call says NOT WRITTEN, runs no further step and exits 2 (an earlier line
# of the same step would otherwise be read as this attempt's). This script prints no figure: it
# says a check's name and where the files are. It reads the checks and the completeness line a
# harness prints, and never a prediction's verdict; of a prediction's line it reads only that the
# report left it unscored, where the row says so (G6, G9). The harnesses are run as they are.
#
#   tier 1
#   G0   QEMU's device tree, dumped with the launcher's machine and device options (no guest code
#        runs), checked by check_virt_dtb.py against the constants the guest side holds
#   G1   ifs-its.bin boots with two CPUs: the terminal marker, a line per CPU on the console, and
#        the second vCPU's thread seen to run for one second (a yes or a no; no value is kept)
#   G2   the same boot: ivshmem configured through ECAM, and no error from the shm mapping
#   G3   the same boot: the ITS selftest delivered every interrupt, MSI-X is configured, and
#        every one of 100 rings of the doorbell is echoed. Stop
#   G4   ifs-kick.bin with ivshmem and the kick console: run-ladder.sh with every transport, K=4;
#        the doorbell proof and completeness. Stop. Then ~/ladder/monitor-native and its
#        .source-sha256 are moved to ~/gate2/bin/<the attempt's stamp>/, whatever the ladder
#        returned: the ladder reads that fixed path, and no later ladder may find a binary there
#        that it did not choose
#   G5   run-bell.sh K=2: complete, and the report's check of the banner and msixcfg lines
#   G6   run-paths.sh SMOKE=1 K=6: complete, every prediction printed unscored
#   G7   run-mmio.sh K=6 (its registered K): the report's four checks
#   G8   ifs-stamp.bin: run-stamp.sh K=4: the window sampler verified, complete, and the stamp's
#        system object holding this release's values
#   G9   the same boot: run-metal.sh K=4: checks M1 to M5, the units back on all cores, the
#        predictions not scored, and a positive control of the login counter (the harness's own
#        journal query, over a window from boot, must count at least one login)
#   G10  the same boot: run-tick.sh K=4: checks M1 to M4 and a reduced heavy trace. Stop
#   G11  run-someip0.sh K=6: complete
#   G12  ifs-live.bin, a fresh boot: liveness-demo.sh exits 0. Stop
#   tier 2
#   G13  run-unmask.sh K=4: complete
#   G14  run-bellrobust.sh R=1: every scenario's line of the one repeat reads pass, the only
#        state in which the report shows every one of the scenario's checks held
#   G15  run-trace.sh K=6: complete, and the report's check that every guest trace is whole
#   G16  ifs-dds.bin: subv under timeout 30, pubbad at once under timeout 40; judged by subv's
#        five VERDICT lines and not by an exit status (one per claim pubbad sent, the four bad
#        ones rejected, each with its own reason, the good one accepted), with the guest's
#        console saying the same of each. Stop
#   G17  ifs-stamp.bin: run-queue.sh K=4: checks M2 and M3, no "queue may still be held" warning,
#        udev settled and its queue file gone. If the queue stayed held it is released once
#        (udevadm control --start-exec-queue, then settle); udevd is never restarted. Stop
#   the GPU tier (refused without GATE2_GPU_OWNER_PRESENT=1; in this order, each only after the
#   one before it passed)
#   G18  no guest; sync, the page cache dropped and that written down; fma 5 gate2 prints its
#        rounds with the GPU seen busy
#   G19  no guest; the page cache dropped; llama-cli loads the small model and prints tokens
#        within its timeout (its standard output holds something besides the prompt's own word,
#        which llama-cli echoes), with no NvMap failure in its output or in the kernel's new
#        lines, and positive evidence of the GPU as a yes or a no: layers offloaded, more than
#        none, with a CUDA device named, or the GPU seen busy during the run. If the load fails
#        with the NvMap error it is run once more with GGML_CUDA_ENABLE_UNIFIED_MEMORY=1, in a
#        directory of its own and with a line of its own; a second failure ends the tier. A
#        pass on the GPU seen busy alone, without the offload wording, is said: G20 reads that
#        wording alone
#   G20  ifs-svc.bin: vlm-demo.sh exits 0 and its server.log holds the same offload evidence.
#        Stop. Refused after the workaround was needed, until the deployed demo names the
#        variable itself
#   G21  ifs-kick.bin: run-llm-interference.sh K=2: the sampler verified, complete. Stop. Left
#        out for good once the workaround was needed
#
# BEFORE ANY STEP, each a refusal:
#   the provisioning script's check exits 0 (nothing missing, nothing differs); this login is in
#   the kvm group; br0 and tap-qnx exist and tap-qnx is a port of br0 (the bridge is made once
#   per boot, by setup-bridge-orin.sh); the deployed files match their manifest; the boot is the
#   one on record, and can be written down; a kernel journal cursor is held, and can be written
#   down; everything under AFTER EVERY STEP is as a step must leave it. The first of these that
#   fails names every step's line. Then, per step, and only for a step the call's own refusal
#   has not already taken: no installer stick for a step that creates a KVM VM (every step but
#   G18 and G19; G0 is one), by lib-stick.sh's rule, the one the provisioning script refuses by,
#   with its wording and its override, PROVISION_ALLOW_REMOVABLE=1; and the images the step
#   boots, and the disk, are the files the image manifest lists.
#   Before all of it: lib-stick.sh beside this script is read to its end and defines the rule
#   and first_line, or the call ends (exit 1) before it has made, started or written anything.
#
# THE MANIFESTS are local files on the board, read by path. No hash of an image is in this
# script: the images are QNX-derived and stay off the public repo, and so do their hashes.
#   ~/gate2/images.sha256   (GATE2_MANIFEST)         "<sha256>  <path>" per line; a line is an
#                           image's when its path is the image's file name, alone or below
#                           output/ (a leading ./ is taken off); an image listed with two hashes
#                           is refused, and so is one that is not listed
#   ~/gate2/deploy.sha256   (GATE2_DEPLOY_MANIFEST)  sha256sum's format, paths below ~/gate2/repo.
#                           Every file it lists has to match. The files this script itself
#                           starts or reads for a step (the launcher, the step's harness or
#                           tool) have to be among them, or the step is refused; and so have this
#                           script's own three, when the copy that runs is the deployed one. What
#                           a harness goes on to run is held only if the list names it: that the
#                           list is the whole deploy, and that no other file exists there, is the
#                           deploy's own check
# Either list may have CRLF line ends: both are made on another machine.
#
# LAUNCH, where a step boots a guest itself: launch-qnx-kvm-bridged.sh with the image, the disk,
# the console in the attempt's directory and the row's variables. It returns when :7100 answers,
# which is before the image's later start-up lines; so a console rule is read only once the
# image's terminal marker is there, within a wait of a minute.
# STOP: the step's line is in the log first; then sync, TERM to the QEMU the launcher named, a
# wait, KILL if it is still there, sync; then the ivshmem server is waited for, and the last
# guest's sockets and its shared file are removed (the launcher refuses to start over one). A
# QEMU the launcher named is stopped whatever the launcher returned. After a harness that boots
# its own guests, its last guest's server is waited for in the same way.
#
# AFTER EVERY STEP, and a refusal for the steps that follow, named by the first item. After the
# call's last step there is no step left to refuse: the call then says "REFUSED from here on"
# as its last line and exits 2, the step's own line stands, and the next call refuses by the item.
#   kernel-lines     a new kernel line since the cursor matches
#                    Internal error|Unable to handle|BUG:|WARNING:|Call trace|Oops:
#                    (the new lines are kept in the attempt's kernel-new.log, never printed; new
#                    lines at err level are listed in kernel-err.log for a human and are not a
#                    stop). The cursor then stays where it was: every later call refuses on the
#                    same lines until one is started with GATE2_FRESH_CURSOR=1. The pattern is
#                    the plan's, taken as it stands and unanchored: a line that only holds one
#                    of its words is a stop as well (DEBUG: holds BUG:). That errs to the safe
#                    side: the line is read, then the fresh cursor is asked for. A cursor that
#                    cannot be written past the lines that were read counts as this item too
#   boot-changed     the boot id is not the one on record (a call after a boot somebody chose is
#                    started once with GATE2_NEW_BOOT=1, after reset_reason and pstore were read)
#   pstore           /sys/fs/pstore is not empty
#   confinement      AllowedCPUs is neither empty nor all cores on system.slice, init.scope, a
#                    user@ service or a session scope, or a 50-AllowedCPUs.conf drop-in is left
#   tracing          an ftrace instance exists, or an event is enabled
#   idle-states      a cpuidle state is disabled
#   governor         a cpufreq policy is not schedutil
#   udev             udevadm settle fails, or /run/udev/queue exists, at two looks a second apart
#   leftover-netns   the netns ladder, or veth-l
#   leftover-process a qemu-system-aarch64, monitor-native, llama-*, fma, cpuload or
#                    ivshmem_server.py (found by its own name, never by a pattern over a whole
#                    command line)
#   leftover-files   an a6-* socket under /tmp or an a6-* file under /dev/shm
# An item that cannot be read counts as wrong.
#
# EVERY ATTEMPT HAS ITS OWN DIRECTORY, ~/gate2/out/<step>/<utc>/, made with a mkdir that fails
# on one that exists: never reused, never deleted. What a step's commands print is there and
# only there (run.log, the launcher's output, the guest's console, the harness's raw/), and holds
# timings and verdicts: it stays local. The call's own opening check writes under
# ~/gate2/out/session/<utc>/.
#
# A ROW'S COMMAND gets an emptied environment: the session's HOME, PATH, LD_LIBRARY_PATH, USER,
# LOGNAME, LANG and LC_ALL where the session has them (which of them it has is said, by name),
# and the row's own variables. Nothing else this script was started with reaches it, so every
# harness runs with its default N and warm-up and the K its row names.
#
# WHAT IT CHANGES ON THE BOARD, and nothing else: files under ~/gate2; the move of the ladder's
# native monitor after G4; the page cache dropped before G18 and G19; udev's queue released
# after G17 if the harness left it held; the last guest's sockets and shared file removed. It
# installs nothing, sets no governor, confinement, mode or unit, and never reboots.
#
# NO NAME AND NO ADDRESS. It runs no command that asks for the host's name or lists addresses,
# and asks journalctl only for bare messages (-o cat). The kernel's new lines and the err-level
# list go to files in the attempt's directory and are never printed: a kernel line can name a
# device, an address or an access point. The copy of ~/gate2/out to another machine, and the
# scan for identifiers before it, are not this script's.
#
# FOR TESTS ONLY: SYS_ROOT, PROC_ROOT, RUN_ROOT, SHM_ROOT and TMP_ROOT redirect what is read and
# where the guest's sockets and shared file are; GATE2_PROVISION names the provisioning script.
# Each is announced when set, and so is a copy of this script that is not the deployed one.
# tests/test_gate2.py runs this script against stubs.
#
# WHAT A PASS DOES NOT SHOW: any timing, or that a figure on this release is comparable with one
# on the release before; that a harness left out of the list works; isolation of any kind; that
# the board survives a hang (nothing here hangs it on purpose, and a step that boots a guest is
# run when the owner can reach the plug). G14 reads the scenario lines, which are also what its
# report's predictions are about; a line that does not read pass fails the step without saying
# which of the two it was. The wording this script takes for llama.cpp's offload lines and for
# an NvMap failure is from the upstream project and the vendor's forum, and is unverified at the
# pinned commit; so is what llama-cli puts on its standard output. G19's "tokens" is therefore
# only this: something was printed there besides the prompt's own word. A token cannot be told
# from anything else the program prints there (a banner, a template's role names). Every smoke
# here is a smoke: its outputs are not a record, and nothing in them is copied anywhere.
# Booting a guest under KVM on this board uses a startup we rebuilt, which is
# not a QNX-supported configuration, and no timing claim attaches to it.

set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SYSR="${SYS_ROOT:-/sys}"
PROC="${PROC_ROOT:-/proc}"
RUNR="${RUN_ROOT:-/run}"
SHMR="${SHM_ROOT:-/dev/shm}"
TMPR="${TMP_ROOT:-/tmp}"
PROVISION="${GATE2_PROVISION:-$here/provision-orin-r39.sh}"

# The installer-stick rule (stick_rule) and first_line: one copy, shared with the provisioning script.
# A file of that name that is not the rule (cut short, a syntax error, a function renamed) ends
# the call here, before anything is made or started: without the rule a VM step would be refused
# under no wording at all, and the two GPU loads, which the rule does not hold, would run.
[ -r "$here/lib-stick.sh" ] || { echo "FATAL: lib-stick.sh not found beside $0" >&2; exit 1; }
# shellcheck source=/dev/null
. "$here/lib-stick.sh" || { echo "FATAL: lib-stick.sh beside $0 could not be read to its end" >&2; exit 1; }
declare -F stick_rule first_line > /dev/null || { echo "FATAL: lib-stick.sh beside $0 does not define stick_rule and first_line" >&2; exit 1; }

G="$HOME/gate2"
REPO="$G/repo"
R="$REPO/orin-native/gpu-concurrency"
E="$REPO/orin-native/edge-llm"
O="$G/out"
IMG="$HOME/output"
GLOG="$G/gate2.log"
STATE="$G/state"
MANIFEST="${GATE2_MANIFEST:-$G/images.sha256}"
DEPLOY_MANIFEST="${GATE2_DEPLOY_MANIFEST:-$G/deploy.sha256}"
IVSHMEM="$SHMR/a6-ivshmem"
IVSHMEM_SERVER="$TMPR/a6-ivshmem.sock"
KICK_SOCK="$TMPR/a6-kick.sock"

USAGE="usage: bash gate2-smoke.sh STEP...   (STEP is G0 .. G21; the GPU tier, G18 to G21, needs GATE2_GPU_OWNER_PRESENT=1)"
ALL_STEPS="G0 G1 G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 G12 G13 G14 G15 G16 G17 G18 G19 G20 G21"
PASS_NAMES="HOME PATH LD_LIBRARY_PATH USER LOGNAME LANG LC_ALL"
STOP_PATTERN='Internal error|Unable to handle|BUG:|WARNING:|Call trace|Oops:'

A=""             # the attempt's directory
SESSION=""       # the call's own directory, for its opening check
WHY=""           # the first check of the step's rule that did not hold; empty: none
WRONG=""         # the first item that is not as a step must leave it; empty: none
REFUSAL=""       # set once an item is wrong: every later step of the call is refused by it
VM_PID=""        # the QEMU the launcher named, while this call has a guest up
BOOT=""          # which boot that guest is
CONSOLE=""       # its console log
CON=""           # the console's text, as last read
CURSOR=""        # the kernel journal cursor every "new line" is counted from
BOOT_ID=""       # the boot on record
DDS=""
WHY_NOT=""
SHARES=""
IMAGES=""
FILES=""
RC=0
NO_RECORD=0
GPU_RC=0
GPU_BUSY=no
P_QEMU=""; P_SERVER=""; P_LOAD=""; PS_OK=0
ROW=()
PASS_ENV=()
declare -A MAN=() DEP=()

# ------------------------------------------------------------------ output

# A print that fails is not an error: the reader of this script's output may have gone away, and
# the step in hand still has a guest to stop and a line to write.
say() {
	printf '%s\n' "$*" 2> /dev/null
	return 0
}

# One line per attempt, and no other kind of line, ever. Whatever a caller hands it, what follows
# FAIL is a check's name: lowercase words joined by hyphens.
record() {  # record <step> <the failed check's name, or nothing>
	local step="$1" why="$2" line
	# A line begins with one step's id: for anything else, no line at all.
	if ! [[ "$step" =~ ^G([0-9]|1[0-9]|2[01])$ ]]; then
		say "not a step, and no line is written for it"
		return 1
	fi
	if [ -z "$why" ]; then
		line="$step PASS"
	else
		[[ "$why" =~ ^[a-z]+(-[a-z]+)*$ ]] || why=malformed-reason
		line="$step FAIL $why"
	fi
	# The log is the one file a result is read from. A line that could not be appended is not
	# said as if it were there: an earlier line of the same step would be read as this attempt's.
	# The call then runs no further step, and its exit status is the refusal's.
	if ! { printf '%s\n' "$line" >> "$GLOG"; } 2> /dev/null; then
		say "NOT WRITTEN: \"$line\" could not be appended to $GLOG. No further step of this call is run, and its exit status is 2."
		RC=2
		[ -n "${REFUSAL:-}" ] || REFUSAL=log-write
		return 1
	fi
	say "$line"
}

fail() {  # a check of the step's rule did not hold; the first one names the FAIL
	say "  check failed: $1"
	[ -n "$WHY" ] || WHY="$1"
	return 1
}

wrong() {  # wrong <item> <what was found>: not as a step must leave it
	say "  not as a step must leave it: $1 -- $2"
	[ -n "$WRONG" ] || WRONG="$1"
	return 0
}

turn_away() {  # turn_away <step> <what>: the step is not run
	say "$1 refused: $2"
	record "$1" "refused-$2"
	RC=2
}

# ------------------------------------------------------------------ the steps, by kind

is_step() {  # exactly one of the steps: an argument that holds several of them is not one
	local s
	for s in $ALL_STEPS; do
		if [ "$1" = "$s" ]; then return 0; fi
	done
	return 1
}

is_gpu_step() {
	case "$1" in G18|G19|G20|G21) return 0 ;; esac
	return 1
}

# Every step creates a KVM VM but the two that load the GPU with no guest. G0 is one: its dump
# makes and tears down a VM without running guest code.
is_vm_step() {
	case "$1" in G18|G19) return 1 ;; esac
	return 0
}

boot_of() {  # SHARES = the boot a step shares with its neighbours, or nothing
	SHARES=""
	case "$1" in
		G1|G2|G3) SHARES=its ;;
		G8|G9|G10) SHARES=stamp ;;
	esac
	return 0
}

images_of() {  # IMAGES = the images a step boots, itself or through its harness
	IMAGES=""
	case "$1" in
		G1|G2|G3) IMAGES="ifs-its.bin" ;;
		G4|G21) IMAGES="ifs-kick.bin" ;;
		G5|G7) IMAGES="ifs-bell.bin" ;;
		G6) IMAGES="ifs-paths.bin" ;;
		G8|G9|G10|G17) IMAGES="ifs-stamp.bin" ;;
		G11) IMAGES="ifs-someip.bin" ;;
		G12) IMAGES="ifs-live.bin" ;;
		G13) IMAGES="ifs-unmask-a.bin ifs-unmask-b.bin" ;;
		G14) IMAGES="ifs-bell.bin ifs-robust.bin ifs-unmask-a.bin" ;;
		G15) IMAGES="ifs-trace.bin" ;;
		G16) IMAGES="ifs-dds.bin" ;;
		G20) IMAGES="ifs-svc.bin" ;;
	esac
	return 0
}

# FILES = the deployed files this script itself starts or reads for a step, by their paths below
# the repo root. What a harness goes on to run (its library, its probe, its report) is the
# harness's.
files_of() {
	local gc=orin-native/gpu-concurrency el=orin-native/edge-llm dds=ipc-test/qnx-dds-monitor
	local launcher="$gc/launch-qnx-kvm-bridged.sh"
	FILES=""
	case "$1" in
		G0) FILES="orin-native/tools/check_virt_dtb.py" ;;
		G1|G2) FILES="$launcher" ;;
		G3) FILES="$launcher $gc/ivshmem_ring.py" ;;
		G4) FILES="$launcher $gc/run-ladder.sh" ;;
		G5) FILES="$gc/run-bell.sh" ;;
		G6) FILES="$gc/run-paths.sh" ;;
		G7) FILES="$gc/run-mmio.sh" ;;
		G8) FILES="$launcher $gc/run-stamp.sh" ;;
		G9) FILES="$launcher $gc/run-metal.sh" ;;
		G10) FILES="$launcher $gc/run-tick.sh" ;;
		G11) FILES="$gc/run-someip0.sh" ;;
		G12) FILES="$launcher $el/liveness-demo.sh" ;;
		G13) FILES="$gc/run-unmask.sh" ;;
		G14) FILES="$gc/run-bellrobust.sh" ;;
		G15) FILES="$gc/run-trace.sh" ;;
		G16) FILES="$launcher $dds/cyclonedds-l4t.xml $dds/build-cyclonedds-qnx.sh" ;;
		G17) FILES="$launcher $gc/run-queue.sh" ;;
		G20) FILES="$launcher $el/vlm-demo.sh" ;;
		G21) FILES="$launcher $el/run-llm-interference.sh" ;;
	esac
	return 0
}

# ------------------------------------------------------------------ a row's command

# ROW = the command with the environment a row gives it: emptied, then the session's few, then
# the row's own variables. Run as "${ROW[@]}", with its output sent to a file of the attempt.
row() {  # row [VAR=value ...] -- command [argument ...]
	local -a vars=()
	while [ "$#" -gt 0 ] && [ "$1" != -- ]; do vars+=("$1"); shift; done
	shift
	ROW=(env -i ${PASS_ENV[@]+"${PASS_ENV[@]}"} ${vars[@]+"${vars[@]}"} "$@")
}

alive() {
	kill -0 "$1" 2>/dev/null
}

file_has() {  # file_has <file> <fixed string>: on some line
	local line
	[ -r "$1" ] || return 1
	while IFS= read -r line || [ -n "$line" ]; do
		if [[ "$line" == *"$2"* ]]; then return 0; fi
	done < "$1"
	return 1
}

file_matches() {  # file_matches <file> <regular expression>: on some line
	local line
	[ -r "$1" ] || return 1
	while IFS= read -r line || [ -n "$line" ]; do
		if [[ "$line" =~ $2 ]]; then return 0; fi
	done < "$1"
	return 1
}

# The harness's completeness line (lib-measure.sh, m_require_complete), for the K the row names.
complete_line() {  # complete_line <file> <K>
	file_matches "$1" "complete: [0-9]+ arm\(s\) x $2 round\(s\), "
}

# Each check named has its line in the report, and each of its lines ends "-> ok".
m_checks_ok() {  # m_checks_ok <file> <check> ...
	local f="$1" m line found
	shift
	[ -r "$f" ] || return 1
	for m in "$@"; do
		found=0
		while IFS= read -r line || [ -n "$line" ]; do
			line="${line%$'\r'}"
			if [[ "$line" =~ ^[[:space:]]+$m[[:space:]] ]]; then
				if [[ "$line" != *" -> ok" ]]; then return 1; fi
				found=1
			fi
		done < "$f"
		if [ "$found" = 0 ]; then return 1; fi
	done
	return 0
}

# The report printed its predictions, and every one of their lines says what the row expects of
# an unscored run. What a prediction's line says otherwise is not read.
predictions_say() {  # predictions_say <file> <fixed string>
	local line n=0
	[ -r "$1" ] || return 1
	while IFS= read -r line || [ -n "$line" ]; do
		if [[ "$line" =~ ^[[:space:]]+P[0-9]+[[:space:]] ]]; then
			if [[ "$line" != *"$2"* ]]; then return 1; fi
			n=$((n + 1))
		fi
	done < "$1"
	[ "$n" -gt 0 ]
}

# ------------------------------------------------------------------ processes and leftovers

# One listing, read by each process's own name: the last component of its first word, and for a
# Python program the script it runs. Never a pattern over the whole command line, which would
# match this script's own, or a shell that only names one of them.
procs_scan() {
	local out pid a0 rest w
	local -a words=()
	P_QEMU=""; P_SERVER=""; P_LOAD=""; PS_OK=0
	out=$(ps -e -o pid= -o args= 2>/dev/null) || return 0
	[ -n "$out" ] || return 0
	PS_OK=1
	while read -r pid a0 rest; do
		case "${a0##*/}" in
			qemu-system-aarch64) P_QEMU="$P_QEMU $pid" ;;
			monitor-native|fma|cpuload|llama-*) P_LOAD="$P_LOAD ${a0##*/}" ;;
			python*)
				read -r -a words <<< "$rest"
				for w in ${words[@]+"${words[@]}"}; do
					case "$w" in -*) continue ;; esac
					if [ "${w##*/}" = ivshmem_server.py ]; then P_SERVER="$P_SERVER $pid"; fi
					break
				done ;;
		esac
	done <<< "$out"
	return 0
}

# The last guest's sockets and its shared file, once no guest and no server is left: the launcher
# refuses to start over a socket it finds, and a harness that boots its own guests leaves its
# last one's behind.
tidy() {
	local i
	# A harness stops its last guest itself and returns; that guest's ivshmem server may still
	# be on its way out. It is waited for as Stop waits, and nothing is removed under one that
	# stays.
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
		procs_scan
		if [ "$PS_OK" != 1 ] || { [ -z "$P_QEMU" ] && [ -z "$P_SERVER" ]; }; then break; fi
		sleep 0.5
	done
	if [ "$PS_OK" != 1 ] || [ -n "$P_QEMU" ] || [ -n "$P_SERVER" ]; then return 0; fi
	rm -f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK" "$IVSHMEM"
}

# ------------------------------------------------------------------ after every step

sudo_lists_nothing() {  # the command, as root, succeeds and prints nothing
	local out
	out=$(sudo -n "$@" 2>/dev/null < /dev/null) || return 1
	[ -z "$out" ]
}

# The kernel's new lines since the cursor. They go to a file and are never printed. A line that
# matches the stop pattern is wrong, and the cursor then stays where it was; otherwise it moves
# past what was read. Lines at err level are listed in a second file, for a human.
check_kernel() {  # check_kernel <directory>
	local dir="$1" out line cur="" new="" stop=0
	if ! out=$(sudo -n journalctl -k -q --no-pager -o cat --after-cursor "$CURSOR" --show-cursor 2>/dev/null < /dev/null); then
		wrong kernel-lines "the kernel's journal cannot be read from the cursor on record (sudo -n journalctl -k); if the cursor itself is gone from the journal, GATE2_FRESH_CURSOR=1 takes a new one"
		return
	fi
	while IFS= read -r line; do
		case "$line" in
			"-- cursor: "*) cur="${line#-- cursor: }" ;;
			"") ;;
			*)
				new+="$line"$'\n'
				if [[ "$line" =~ $STOP_PATTERN ]]; then stop=1; fi ;;
		esac
	done <<< "$out"
	if [ -n "$new" ]; then
		printf '%s' "$new" >> "$dir/kernel-new.log"
		# Which of the new lines are at err level, asked only when there are new lines at all.
		if out=$(sudo -n journalctl -k -q --no-pager -o cat -p err --after-cursor "$CURSOR" 2>/dev/null < /dev/null) && [ -n "$out" ]; then
			printf '%s\n' "$out" >> "$dir/kernel-err.log"
			say "  new kernel lines at err level are listed in $dir/kernel-err.log for a human; they are not a stop by themselves"
		fi
	fi
	if [ "$stop" = 1 ]; then
		wrong kernel-lines "a new kernel line matches the stop pattern; the new lines are in $dir/kernel-new.log. Save dmesg, the journal and pstore before anything else runs, and tell the owner. Every call refuses on these lines until one is started with GATE2_FRESH_CURSOR=1"
		return
	fi
	if [ -n "$cur" ] && [ "$cur" != "$CURSOR" ]; then
		# Written first, taken as the cursor only then: the next call reads from the file.
		if ! { printf '%s\n' "$cur" > "$STATE/cursor"; } 2> /dev/null; then
			wrong kernel-lines "the kernel journal cursor cannot be written to $STATE/cursor: the next call would read the same lines again, from a cursor nobody moved"
			return
		fi
		CURSOR="$cur"
	fi
}

check_boot() {
	first_line "$PROC/sys/kernel/random/boot_id"
	if [ -z "$FL" ] || [ "$FL" != "$BOOT_ID" ]; then
		wrong boot-changed "the boot id is not the one on record: the board was reset. Read reset_reason first, then pstore; no further run until the cause is known"
	fi
}

# AllowedCPUs is empty or all cores on every unit a harness confines, and no drop-in is left.
conf_check() {
	local all out u line n=0 bad="" f
	local -a units=(system.slice init.scope)
	first_line "$SYSR/devices/system/cpu/online"; all="$FL"
	if [ -z "$all" ]; then say "    the online cores cannot be read"; return 1; fi
	if ! out=$(systemctl list-units --no-legend --plain 'user@*.service' 'session-*.scope' 2>/dev/null < /dev/null); then
		say "    the units cannot be listed"; return 1
	fi
	while read -r u _; do
		case "$u" in user@*.service|session-*.scope) units+=("$u") ;; esac
	done <<< "$out"
	if ! out=$(systemctl show -p AllowedCPUs "${units[@]}" 2>/dev/null < /dev/null); then
		say "    AllowedCPUs cannot be read"; return 1
	fi
	while IFS= read -r line; do
		case "$line" in
			AllowedCPUs=*)
				if [ -n "${line#AllowedCPUs=}" ] && [ "${line#AllowedCPUs=}" != "$all" ]; then bad="$bad ${units[$n]:-?}"; fi
				n=$((n + 1)) ;;
		esac
	done <<< "$out"
	if [ "$n" != "${#units[@]}" ]; then say "    AllowedCPUs was not answered for every unit"; return 1; fi
	if [ -n "$bad" ]; then say "    AllowedCPUs is still set on:$bad"; return 1; fi
	for f in "$RUNR"/systemd/system.control/*/50-AllowedCPUs.conf; do
		if [ -e "$f" ]; then say "    a 50-AllowedCPUs.conf drop-in is left under /run/systemd/system.control"; return 1; fi
	done
	return 0
}

# Settled, and no queue file. Looked at twice, a second apart, before udev is called busy: an
# event of the board's own may arrive between the settle and the look.
udev_idle() {
	local i
	for i in 1 2; do
		if udevadm settle --timeout=30 > /dev/null 2>&1 < /dev/null && [ ! -e "$RUNR/udev/queue" ]; then return 0; fi
		if [ "$i" = 1 ]; then sleep 1; fi
	done
	return 1
}

check_leftovers() {  # check_leftovers <keep: this call's own guest is up, on purpose, for the next step>
	local keep="$1" p f own="" bad=""
	if [ -e "$RUNR/netns/ladder" ] || [ -e "$SYSR/class/net/veth-l" ]; then
		wrong leftover-netns "the netns ladder or veth-l is still there"
	fi
	procs_scan
	if [ "$PS_OK" != 1 ]; then
		wrong leftover-process "the processes cannot be listed"
	else
		if [ -n "$keep" ]; then first_line "$IVSHMEM_SERVER.ready"; own="$FL"; fi
		for p in $P_QEMU; do
			if [ -z "$keep" ] || [ "$p" != "$VM_PID" ]; then bad="$bad qemu-system-aarch64"; fi
		done
		for p in $P_SERVER; do
			if [ -z "$keep" ] || [ "$p" != "$own" ]; then bad="$bad ivshmem_server.py"; fi
		done
		bad="$bad$P_LOAD"
		if [ -n "$bad" ]; then wrong leftover-process "still running:$bad"; fi
	fi
	for f in "$TMPR"/a6-*.sock* "$SHMR"/a6-*; do
		[ -e "$f" ] || continue
		if [ -n "$keep" ]; then
			case "$f" in "$IVSHMEM_SERVER"|"$IVSHMEM_SERVER.ready"|"$KICK_SOCK"|"$IVSHMEM") continue ;; esac
		fi
		wrong leftover-files "${f##*/} is still there"
	done
}

# WRONG = the first item that is not as a step must leave it (empty: none). Each one is said.
state_check() {  # state_check <directory for what is listed> [keep]
	local dir="$1" keep="${2:-}" f n bad
	WRONG=""
	check_kernel "$dir"
	check_boot
	sudo_lists_nothing ls -A "$SYSR/fs/pstore" || wrong pstore "/sys/fs/pstore is not empty, or cannot be listed"
	conf_check || wrong confinement "see the line above"
	if ! sudo_lists_nothing ls -A "$SYSR/kernel/tracing/instances"; then
		wrong tracing "an ftrace instance exists, or the instances cannot be listed"
	elif ! sudo_lists_nothing cat "$SYSR/kernel/tracing/set_event"; then
		wrong tracing "a trace event is enabled, or the enabled events cannot be read"
	fi
	# Every cpuidle state there is reads 0, and there is one; every cpufreq policy there is reads
	# schedutil, and there is one. A state or a policy whose file cannot be read is not at rest.
	n=0; bad=0
	for f in "$SYSR"/devices/system/cpu/cpu[0-9]*/cpuidle/state[0-9]*; do
		[ -d "$f" ] || continue
		n=$((n + 1))
		first_line "$f/disable"
		if [ "$FL" != 0 ]; then bad=1; fi
	done
	if [ "$n" = 0 ] || [ "$bad" = 1 ]; then wrong idle-states "a cpuidle state is disabled, or none can be read"; fi
	n=0; bad=0
	for f in "$SYSR"/devices/system/cpu/cpufreq/policy*; do
		[ -d "$f" ] || continue
		n=$((n + 1))
		first_line "$f/scaling_governor"
		if [ "$FL" != schedutil ]; then bad=1; fi
	done
	if [ "$n" = 0 ] || [ "$bad" = 1 ]; then wrong governor "a cpufreq policy is not schedutil, or none can be read: a run died without restoring it"; fi
	udev_idle || wrong udev "udevadm settle fails, or /run/udev/queue exists"
	check_leftovers "$keep"
}

# The check after a step, or after a guest was stopped. The first item that is wrong refuses every
# later step of the call, and is the call's exit status whatever the steps' own lines say: after
# the call's last step there is no later step to show it, and a session reads the status.
after_check() {  # after_check <directory for what is listed> [keep]
	[ -z "$REFUSAL" ] || return 0
	state_check "$1" "${2:-}"
	[ -n "$WRONG" ] || return 0
	REFUSAL="$WRONG"
	RC=2
	say "REFUSED from here on: $REFUSAL. No further step of this call is run, and its exit status is 2 whatever the steps' own lines say."
}

# ------------------------------------------------------------------ Launch and Stop

console_load() {
	CON=""
	if [ -r "$CONSOLE" ]; then CON=$(tr -d '\0\r' < "$CONSOLE" 2>/dev/null); fi
	return 0
}

console_has() {  # in the console as last read
	[[ "$CON" == *"$1"* ]]
}

wait_marks() {  # wait_marks <seconds> <marker> ...: every marker on the console, within the wait
	local n="$1" i m ok
	shift
	for ((i = 0; i <= n; i++)); do
		console_load
		ok=1
		for m in "$@"; do console_has "$m" || ok=0; done
		if [ "$ok" = 1 ]; then return 0; fi
		if [ "$i" != "$n" ]; then sleep 1; fi
	done
	return 1
}

# Stop. The step's line is already in the log, so the first sync flushes it with the rest.
stop_boot() {
	local i
	[ -n "$VM_PID" ] || return 0
	say "  stopping the guest (sync first: a panic in QEMU's teardown once lost unflushed files)"
	sync
	kill -TERM "$VM_PID" 2>/dev/null
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
		alive "$VM_PID" || break
		sleep 0.5
	done
	if alive "$VM_PID"; then
		kill -KILL "$VM_PID" 2>/dev/null
		sleep 1
	fi
	if alive "$VM_PID"; then
		say "  WARNING: the guest's QEMU would not stop"
		VM_PID=""; BOOT=""
		return 1
	fi
	VM_PID=""; BOOT=""
	sync
	# The ivshmem server exits when its QEMU goes; its sockets are removed after it, not under it.
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
		procs_scan
		if [ "$PS_OK" = 1 ] && [ -z "$P_SERVER" ]; then break; fi
		sleep 0.5
	done
	if [ "$PS_OK" != 1 ] || [ -n "$P_SERVER" ]; then
		say "  WARNING: ivshmem_server.py has not exited after its guest; its sockets are left where they are"
		return 1
	fi
	return 0
}

# The guest a step needs: the one this call already has up for the step before, or a Launch.
# Returns 1, with the check named, when there is no such guest to read a rule from.
boot() {  # boot <its|kick|kick-plain|stamp|live|dds|svc>
	local kind="$1" image="" rc line
	local -a extras=() marks=()
	case "$kind" in
		its)
			image=ifs-its.bin
			extras=(THREAD_NAMES=1 "IVSHMEM=$IVSHMEM" "IVSHMEM_SERVER=$IVSHMEM_SERVER" "KICK_SOCK=$KICK_SOCK")
			marks=("its: msixwait: attached") ;;
		kick)
			image=ifs-kick.bin
			extras=("IVSHMEM=$IVSHMEM" "IVSHMEM_SERVER=$IVSHMEM_SERVER" "KICK_SOCK=$KICK_SOCK")
			marks=("serving shm on ivshmem" "serving shm-kick") ;;
		kick-plain) image=ifs-kick.bin; marks=("safety monitor listening on :7100 (") ;;
		stamp) image=ifs-stamp.bin; marks=("stamping replies on :7103:") ;;
		live) image=ifs-live.bin; marks=("listening on :7102 (frame=64 bytes, conf_min=60%), liveness deadline") ;;
		dds) image=ifs-dds.bin; marks=("qnx-dds-monitor: waiting for claims") ;;
		svc) image=ifs-svc.bin; marks=("safety monitor listening on :7102 (") ;;
	esac
	if [ -n "$VM_PID" ] && [ "$BOOT" = "$kind" ] && alive "$VM_PID"; then
		say "  the same boot as the step before"
		wait_marks 0 "${marks[@]}" || { fail terminal-marker; return 1; }
		return 0
	fi
	# A guest of this call that is still on record here is another boot's, or has died by itself:
	# Stop it, and remove what it left, before the launcher is asked to start over it.
	if [ -n "$VM_PID" ]; then stop_boot; tidy; fi
	CONSOLE="$A/guest-console.log"
	say "  launching $image"
	row "IFS_BIN=$IMG/$image" "DISK=$IMG/disk-qemu" "LOG=$CONSOLE" ${extras[@]+"${extras[@]}"} -- bash "$R/launch-qnx-kvm-bridged.sh"
	"${ROW[@]}" > "$A/launch.log" 2>&1 < /dev/null; rc=$?
	# The QEMU the launcher named, whatever the launcher then returned: one that gave up waiting
	# for the guest leaves its QEMU running.
	VM_PID=""
	while IFS= read -r line; do
		if [[ "$line" =~ ^qemu\ pid:\ ([0-9]+)$ ]]; then VM_PID="${BASH_REMATCH[1]}"; fi
	done < "$A/launch.log"
	BOOT="$kind"
	if [ "$rc" != 0 ] || [ -z "$VM_PID" ] || ! file_has "$A/launch.log" "guest up after "; then
		fail launch
		return 1
	fi
	wait_marks 60 "${marks[@]}" || { fail terminal-marker; return 1; }
	return 0
}

# ------------------------------------------------------------------ tier 1

step_G0() {
	local dtb="$A/virt.dtb"
	row -- timeout 20 qemu-system-aarch64 \
		-machine "virt,gic-version=3,dumpdtb=$dtb" -cpu host -enable-kvm -smp 2 -m 1G -display none \
		-drive file=null-co://,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0 \
		-netdev user,id=n0 -device virtio-net-device,netdev=n0,mac=52:54:00:11:11:11 \
		-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-device,rng=rng0
	"${ROW[@]}" > "$A/qemu.log" 2>&1 < /dev/null || { fail qemu-dumpdtb; return; }
	[ -s "$dtb" ] || { fail dtb-written; return; }
	row -- python3 "$REPO/orin-native/tools/check_virt_dtb.py" "$dtb"
	"${ROW[@]}" > "$A/check.log" 2>&1 < /dev/null || fail dtb-check
}

# A yes or a no: the guest's second vCPU thread ran during one second. That QEMU has a thread of
# that name is no evidence (it names both whether or not the guest starts CPU 1); its run time
# growing is. No value is kept or said.
cpu_one_runs() {
	local t tid="" a b
	for t in "$PROC/$VM_PID"/task/*; do
		first_line "$t/comm"
		if [ "$FL" = "CPU 1/KVM" ]; then tid="$t"; fi
	done
	[ -n "$tid" ] || return 1
	first_line "$tid/schedstat"; a="${FL%% *}"
	sleep 1
	first_line "$tid/schedstat"; b="${FL%% *}"
	[[ "$a" =~ ^[0-9]+$ ]] && [[ "$b" =~ ^[0-9]+$ ]] && [ "$b" -gt "$a" ]
}

step_G1() {
	boot its || return
	if ! console_has "cpu0: MPIDR=" || ! console_has "cpu1: MPIDR="; then fail cpu-lines; return; fi
	cpu_one_runs || fail cpu-one-runs
}

step_G2() {
	boot its || return
	console_has "shm configured:" || { fail shm-configured; return; }
	# Every message of the shm mapping code that begins "shm: " is one of its errors.
	if console_has "shm: "; then fail shmcfg-error; fi
}

step_G3() {
	local line ok=0 rung=0 re='its: selftest: ([0-9]+) INT commands, ([0-9]+) LPIs delivered, 0 timeouts'
	local re_ring='^ring: ([0-9]+) rung, ([0-9]+) echoed, 0 timed out'
	boot its || return
	while IFS= read -r line; do
		if [[ "$line" =~ $re ]] && [ "${BASH_REMATCH[1]}" = "${BASH_REMATCH[2]}" ] && [ "${BASH_REMATCH[1]}" != 0 ] \
			&& [[ "$line" != *"with errors"* ]]; then ok=1; fi
	done <<< "$CON"
	[ "$ok" = 1 ] || { fail selftest; return; }
	console_has "its: msixcfg:" || { fail msixcfg; return; }
	# No --json: the ring's round trips are not kept.
	row -- python3 "$R/ivshmem_ring.py" --socket "$IVSHMEM_SERVER" --count 100 --gap-ms 2 --echo
	"${ROW[@]}" > "$A/ring.log" 2>&1 < /dev/null || { fail ring-echo; return; }
	while IFS= read -r line; do
		if [[ "$line" =~ $re_ring ]] && [ "${BASH_REMATCH[1]}" = "${BASH_REMATCH[2]}" ] && [ "${BASH_REMATCH[1]}" != 0 ]; then rung=1; fi
	done < "$A/ring.log"
	[ "$rung" = 1 ] || fail ring-echo
}

# Gap 4i. run-ladder.sh reads the monitor at a fixed path, so the build for G4 is at that path;
# afterwards it is moved away, with the hash of the source it was built from, so that no later
# ladder finds a binary it did not choose.
move_monitor() {
	local mon="$HOME/ladder/monitor-native" dest="$G/bin/${A##*/}"
	[ -e "$mon" ] || [ -e "$mon.source-sha256" ] || return 0
	mkdir -p "$dest" || return 1
	if [ -e "$mon.source-sha256" ]; then
		mv "$mon" "$mon.source-sha256" "$dest/" || return 1
	else
		mv "$mon" "$dest/" || return 1
	fi
	say "  the ladder's native monitor was moved to $dest"
	return 0
}

step_G4() {
	local rc moved=1
	boot kick || return
	row SHM=1 KICK=1 DB=1 UDP_IN_TCP=1 KVM_STATS=1 ARM_C_PORT=7000 CSTATE=shallow K=4 "OUT=$A/raw" -- bash "$R/run-ladder.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null; rc=$?
	move_monitor || moved=0
	[ "$rc" = 0 ] || fail harness-exit
	file_matches "$A/run.log" 'doorbell proof: .*"ok": true' || fail doorbell-proof
	complete_line "$A/run.log" 4 || fail complete
	[ "$moved" = 1 ] || fail monitor-moved
}

step_G5() {
	row K=2 "OUT=$A/raw" -- bash "$R/run-bell.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	complete_line "$A/run.log" 2 || fail complete
	# The report's M3 is its check of every boot's msixcfg line and of the two monitors' banners.
	m_checks_ok "$A/run.log" M3 || fail banner-and-msixcfg
}

step_G6() {
	row SMOKE=1 K=6 "OUT=$A/raw" -- bash "$R/run-paths.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	complete_line "$A/run.log" 6 || fail complete
	predictions_say "$A/run.log" "-> UNSCORED (" || fail predictions-unscored
}

step_G7() {
	row K=6 "OUT=$A/raw" -- bash "$R/run-mmio.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	m_checks_ok "$A/run.log" M1 M2 M3 M4 || fail m-checks
}

# The stamp's system object holds this release's values: the L4T release line and the OS name
# the provisioning script asserts, and a CONFIG_HZ that was read.
stamp_system() {
	local f="$1"
	file_matches "$f" '"l4t_release": "# R39 \(release\)' && file_matches "$f" '"os_release": "[^"]*24\.04' \
		&& file_matches "$f" '"config_hz": [0-9]+'
}

step_G8() {
	boot stamp || return
	row "CONSOLE=$CONSOLE" K=4 "OUT=$A/raw" -- bash "$R/run-stamp.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	file_has "$A/run.log" "window sampler verified:" || fail sampler-verified
	complete_line "$A/run.log" 4 || fail complete
	stamp_system "$A/raw/stamp.json" || fail stamp-system
}

# A yes or a no: the harness's own journal query (run-metal.sh's accepted= line), over a window
# that holds this session's own login, counts at least one. The window is from boot until now.
# The lines are counted and never shown: each carries an address.
login_control() {
	local k v t0="" n
	[ -r "$PROC/stat" ] || return 1
	while read -r k v _; do
		if [ "$k" = btime ]; then t0="$v"; fi
	done < "$PROC/stat"
	[[ "$t0" =~ ^[0-9]+$ ]] || return 1
	n=$(sudo -n journalctl -u ssh -u sshd --since "@$t0" --until "@$(date +%s)" -o cat 2>/dev/null < /dev/null | grep -c '^Accepted ')
	[ "${n:-0}" -ge 1 ]
}

step_G9() {
	boot stamp || return
	row "CONSOLE=$CONSOLE" K=4 "OUT=$A/raw" -- bash "$R/run-metal.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	m_checks_ok "$A/run.log" M1 M2 M3 M4 M5 || fail m-checks
	conf_check || fail confinement
	predictions_say "$A/run.log" "-> not scored (" || fail predictions-not-scored
	# M4 wants no login during the rounds, which a counter that cannot count also gives.
	login_control || fail login-control
}

step_G10() {
	local f reduced=0
	boot stamp || return
	row "CONSOLE=$CONSOLE" K=4 "OUT=$A/raw" -- bash "$R/run-tick.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	m_checks_ok "$A/run.log" M1 M2 M3 M4 || fail m-checks
	# The zone found and QEMU pinned back after each change are the harness's own refusals, and
	# so is a trace that does not reduce; what a heavy round's trace reduced to is its tk- file.
	for f in "$A"/raw/tk-*.log; do
		if [ -s "$f" ]; then reduced=1; fi
	done
	[ "$reduced" = 1 ] || fail heavy-trace
}

step_G11() {
	row K=6 "OUT=$A/raw" -- bash "$R/run-someip0.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	complete_line "$A/run.log" 6 || fail complete
}

step_G12() {
	boot live || return
	# The demo refuses an OUT that exists, and the attempt's directory does (the console is in
	# it): the demo gets a directory of its own under it.
	row "CONSOLE=$CONSOLE" "OUT=$A/demo" -- bash "$E/liveness-demo.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail demo-exit
}

# ------------------------------------------------------------------ tier 2

step_G13() {
	row K=4 "OUT=$A/raw" -- bash "$R/run-unmask.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	complete_line "$A/run.log" 4 || fail complete
}

# Every scenario has its line for the one repeat, and the line reads pass: the report's only
# state in which every check of the scenario was shown to hold.
scenarios_pass() {
	local s line found
	[ -r "$1" ] || return 1
	for s in S1 S2 S3 S4 S5 S6 S7 S8; do
		found=0
		while IFS= read -r line || [ -n "$line" ]; do
			if [[ "$line" =~ ^[[:space:]]+$s\ r1\ ([A-Za-z]+) ]]; then
				if [ "${BASH_REMATCH[1]}" != pass ]; then return 1; fi
				found=1
			fi
		done < "$1"
		if [ "$found" = 0 ]; then return 1; fi
	done
	return 0
}

step_G14() {
	row R=1 "OUT=$A/raw" -- bash "$R/run-bellrobust.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	scenarios_pass "$A/run.log" || fail scenario-checks
}

step_G15() {
	row K=6 "OUT=$A/raw" -- bash "$R/run-trace.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	complete_line "$A/run.log" 6 || fail complete
	# The report's M1: every window's guest trace is whole and was cut into its reads.
	m_checks_ok "$A/run.log" M1 || fail trace-reduces
}

# DDS = the one directory under ~/cyclonedds that is named by the commit the deployed build
# script pins and holds both L4T peers. The pin is read there, not written here.
dds_dir() {
	local line pin="" d name n=0
	local re='^CDDS_COMMIT="\$\{CDDS_COMMIT:-([0-9a-f]+)\}"'
	DDS=""
	[ -r "$REPO/ipc-test/qnx-dds-monitor/build-cyclonedds-qnx.sh" ] || return 1
	while IFS= read -r line; do
		if [[ "$line" =~ $re ]]; then pin="${BASH_REMATCH[1]}"; fi
	done < "$REPO/ipc-test/qnx-dds-monitor/build-cyclonedds-qnx.sh"
	[ -n "$pin" ] || return 1
	for d in "$HOME"/cyclonedds/*/; do
		name="${d%/}"; name="${name##*/}"
		[ "${#name}" -ge 7 ] && [[ "$pin" == "$name"* ]] || continue
		[ -x "$d/bin/subv" ] && [ -x "$d/bin/pubbad" ] || continue
		DDS="${d%/}"
		n=$((n + 1))
	done
	[ "$n" = 1 ]
}

# Judged by subv's lines, not by an exit status: subv exits 0 on a single verdict.
dds_judge() {
	local line seq word n=0 good=0
	local -A sent=() acc=() rsn=() conw=() conr=() used=()
	local re_s='^send seq=([0-9]+) ([a-z-]+) rc=0$' re_v='^VERDICT seq=([0-9]+) accepted=([0-9]+) reason=([0-9]+)$'
	local re_c='claim seq=([0-9]+) .* -> (ACCEPT|REJECT) \(reason=([0-9]+)\)'
	while IFS= read -r line || [ -n "$line" ]; do
		if [[ "$line" =~ $re_s ]]; then
			sent[${BASH_REMATCH[1]}]="${BASH_REMATCH[2]}"; n=$((n + 1))
			if [ "${BASH_REMATCH[2]}" = good ]; then good=$((good + 1)); fi
		fi
	done < "$A/pubbad.out"
	# Five claims, each with a number of its own: four bad ones and the good one.
	if [ "$n" != 5 ] || [ "${#sent[@]}" != 5 ] || [ "$good" != 1 ]; then fail claims-sent; return; fi
	n=0
	while IFS= read -r line || [ -n "$line" ]; do
		if [[ "$line" =~ $re_v ]]; then
			acc[${BASH_REMATCH[1]}]="${BASH_REMATCH[2]}"; rsn[${BASH_REMATCH[1]}]="${BASH_REMATCH[3]}"; n=$((n + 1))
		fi
	done < "$A/subv.out"
	# Five verdict lines, one for each claim that was sent.
	if [ "$n" != 5 ] || [ "${#acc[@]}" != 5 ]; then fail five-verdicts; return; fi
	for seq in "${!sent[@]}"; do
		if [ -z "${acc[$seq]:-}" ]; then fail five-verdicts; return; fi
	done
	while IFS= read -r line; do
		if [[ "$line" =~ $re_c ]]; then conw[${BASH_REMATCH[1]}]="${BASH_REMATCH[2]}"; conr[${BASH_REMATCH[1]}]="${BASH_REMATCH[3]}"; fi
	done <<< "$CON"
	# One rule at a time over the five, so that the first rule that does not hold is the one named
	# whatever order the claims come in: the four bad ones rejected, each with its own reason, the
	# good one accepted, and the guest's console saying of each what subv was told of it.
	for seq in "${!sent[@]}"; do
		[ "${sent[$seq]}" = good ] && continue
		if [ "${acc[$seq]}" != 0 ] || [ "${rsn[$seq]}" = 0 ]; then fail bad-rejected; fi
	done
	for seq in "${!sent[@]}"; do
		[ "${sent[$seq]}" = good ] && continue
		if [ -n "${used[${rsn[$seq]}]:-}" ]; then fail own-reasons; fi
		used[${rsn[$seq]}]=1
	done
	for seq in "${!sent[@]}"; do
		[ "${sent[$seq]}" = good ] || continue
		if [ "${acc[$seq]}" != 1 ] || [ "${rsn[$seq]}" != 0 ]; then fail good-accepted; fi
	done
	for seq in "${!sent[@]}"; do
		if [ "${acc[$seq]}" = 1 ]; then word=ACCEPT; else word=REJECT; fi
		if [ "${conw[$seq]:-}" != "$word" ] || [ "${conr[$seq]:-}" != "${rsn[$seq]}" ]; then fail console-agrees; fi
	done
}

step_G16() {
	local uri="file://$REPO/ipc-test/qnx-dds-monitor/cyclonedds-l4t.xml" sp
	dds_dir || { fail dds-peers; return; }
	boot dds || return
	# subv listens for a few seconds only, so pubbad starts at once; it waits for its match.
	row "CYCLONEDDS_URI=$uri" -- timeout 30 "$DDS/bin/subv"
	"${ROW[@]}" > "$A/subv.out" 2>&1 < /dev/null &
	sp=$!
	row "CYCLONEDDS_URI=$uri" -- timeout 40 "$DDS/bin/pubbad"
	"${ROW[@]}" > "$A/pubbad.out" 2>&1 < /dev/null
	wait "$sp"
	console_load
	dds_judge
}

step_G17() {
	boot stamp || return
	row "CONSOLE=$CONSOLE" K=4 "OUT=$A/raw" -- bash "$R/run-queue.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	# M3: held rounds have events waiting and run rounds an empty queue. Without it a hold that
	# does nothing on this udevd would pass.
	m_checks_ok "$A/run.log" M2 M3 || fail m-checks
	if file_has "$A/run.log" "queue may still be held"; then fail queue-warning; fi
	if ! udev_idle; then
		fail queue-released
		say "  udev's queue is still held: releasing it once (udevadm control --start-exec-queue, then settle). A udevd restart is the owner's word"
		sudo -n udevadm control --start-exec-queue > /dev/null 2>&1 < /dev/null
		if udev_idle; then say "  released and settled"; else say "  the queue is still held after the release"; fi
	fi
}

# ------------------------------------------------------------------ the GPU tier

# sync, then the page cache dropped, and that written down: a warm cache is how context creation
# failed on this board, and cudaMalloc does not reclaim it.
drop_cache() {
	sync
	sudo -n sh -c 'echo 3 > "$1"' _ "$PROC/sys/vm/drop_caches" 2>/dev/null < /dev/null || return 1
	printf 'the page cache was dropped (after a sync) before this load, at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$A/page-cache-dropped.txt"
}

# Runs ROW with its two outputs in files, and looks at the GPU beside it: GPU_BUSY is yes when a
# tegrastats line taken while it ran shows GR3D above zero. The lines are not kept. The load's
# input is named although it runs in the background: a bash that has run a loop with redirected
# input, as this one has by now, no longer gives a background command /dev/null by itself.
gpu_beside() {  # gpu_beside <prefix of the two output files>
	local pre="$1" pid line
	GPU_BUSY=no
	"${ROW[@]}" > "$pre.stdout" 2> "$pre.stderr" < /dev/null &
	pid=$!
	while :; do
		line=$(timeout 3 tegrastats --interval 1000 2>/dev/null < /dev/null | head -1)
		if [[ "$line" =~ GR3D_FREQ\ ([0-9]+)% ]] && [ "${BASH_REMATCH[1]}" -gt 0 ]; then GPU_BUSY=yes; fi
		alive "$pid" || break
		sleep 1
	done
	wait "$pid"; GPU_RC=$?
}

# Yes when a file given names an NvMap failure. The wording known is the vendor forum's
# "NvMapMemAllocInternalTagged failed: error 12"; any line that names NvMap with a failure or an
# error counts.
nvmap_in() {
	local f line re='[Nn][Vv][Mm][Aa][Pp].*([Ff]ail|[Ee]rror)|([Ff]ail|[Ee]rror).*[Nn][Vv][Mm][Aa][Pp]'
	for f in "$@"; do
		[ -r "$f" ] || continue
		while IFS= read -r line || [ -n "$line" ]; do
			if [[ "$line" =~ $re ]]; then return 0; fi
		done < "$f"
	done
	return 1
}

# The kernel's new lines since the cursor, into a file of the attempt, without moving the cursor:
# the check after the step reads them again.
kernel_peek() {  # kernel_peek <file>
	sudo -n journalctl -k -q --no-pager -o cat --after-cursor "$CURSOR" > "$1" 2>/dev/null < /dev/null
}

# Yes when a file given reports layers offloaded to the GPU, more than none, and names a CUDA
# device. A CUDA that fails to initialise leaves llama.cpp on the CPU, still printing tokens.
offloaded() {
	local f line layers=no dev=no re='offloaded ([0-9]+)/[0-9]+ layers to GPU'
	for f in "$@"; do
		[ -r "$f" ] || continue
		while IFS= read -r line || [ -n "$line" ]; do
			if [[ "$line" =~ $re ]] && [ "${BASH_REMATCH[1]}" -gt 0 ]; then layers=yes; fi
			case "$line" in *"CUDA devices"*|*"CUDA0"*|*"using device CUDA"*) dev=yes ;; esac
		done < "$f"
	done
	[ "$layers$dev" = yesyes ]
}

step_G18() {
	drop_cache || { fail page-cache; return; }
	row -- "$HOME/gpuload/fma" 5 gate2
	gpu_beside "$A/fma"
	[ "$GPU_RC" = 0 ] || fail fma-exit
	file_matches "$A/fma.stdout" '^round=[0-9]+ ' || fail fma-rounds
	[ "$GPU_BUSY" = yes ] || fail gpu-busy
}

llama_once() {  # one load of the small model; $1 = the workaround's assignment, or nothing
	local text off=no how="not set" prompt=hello
	WHY=""
	if [ -n "$1" ]; then how=set; fi
	drop_cache || { fail page-cache; return; }
	# Bounded, and with nothing on its standard input: this build's llama-cli once spun on end-of-input.
	row ${1:+"$1"} -- timeout 180 "$HOME/llama.cpp/build/bin/llama-cli" -m "$HOME/models/SmolVLM-500M-Instruct-Q8_0.gguf" -ngl 99 -n 16 -st -p "$prompt"
	gpu_beside "$A/llama"
	kernel_peek "$A/kernel-during.log" || { fail kernel-lines-read; return; }
	if offloaded "$A/llama.stderr" "$A/llama.stdout"; then off=yes; fi
	{
		printf 'layers offloaded to the GPU, with a CUDA device named: %s\n' "$off"
		printf 'the GPU seen busy during the run: %s\n' "$GPU_BUSY"
		printf 'the unified-memory workaround: %s\n' "$how"
	} > "$A/evidence.txt"
	# The NvMap failure first: it is what decides the one retry, whatever else it broke.
	if nvmap_in "$A/llama.stdout" "$A/llama.stderr" "$A/kernel-during.log"; then fail nvmap; fi
	[ "$GPU_RC" = 0 ] || fail llama-exit
	# "Prints tokens": llama-cli echoes the prompt, so the prompt's own word is taken out first,
	# and something has to be left. What is left is not shown to be a token (the header says so).
	text=""
	if [ -r "$A/llama.stdout" ]; then text=$(< "$A/llama.stdout"); fi
	[[ "${text//"$prompt"/}" =~ [^[:space:]] ]] || fail tokens
	if [ "$off" != yes ] && [ "$GPU_BUSY" != yes ]; then fail gpu-evidence; fi
	if [ -z "$WHY" ] && [ "$off" != yes ]; then
		say "  it passes on the GPU seen busy alone: the offload wording this script looks for is not in the load's output. G20's rule reads that wording alone, in the server's log: read $A/llama.stderr and settle the wording before G20"
	fi
}

step_G19() {
	llama_once ""
	[ "$WHY" = nvmap ] || return 0
	# Gap 4o: the load failed with the NvMap error. Its line and its check first; then one more
	# load, with the workaround, in a directory of its own. Never a third.
	record G19 "$WHY"
	if [ "$RC" = 0 ]; then RC=1; fi
	# No second load on a board the first one did not leave as a step must: the item is the
	# call's refusal, said and in its exit status as after any step.
	after_check "$A"
	if [ -n "$REFUSAL" ]; then NO_RECORD=1; return 0; fi
	say "  the load failed with the NvMap error: once more, with GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 (gap 4o)"
	new_attempt G19 || { turn_away G19 attempt-directory; NO_RECORD=1; return 0; }
	llama_once GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
	if [ -z "$WHY" ]; then
		: > "$STATE/nvmap-workaround"
		say "  it passes with the workaround. The edge-LLM scripts gain the variable and stamp it before G20 (a code change, with tests), and G21 is left out"
	else
		say "  a second failure: the GPU tier stops here"
	fi
}

step_G20() {
	local rc
	boot svc || return
	row "CONSOLE=$CONSOLE" "OUT=$A" "IMAGES=$HOME/mnist" -- bash "$E/vlm-demo.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null; rc=$?
	kernel_peek "$A/kernel-during.log" || { fail kernel-lines-read; return; }
	if nvmap_in "$A/server.log" "$A/run.log" "$A/kernel-during.log"; then
		fail nvmap
		: > "$STATE/nvmap-workaround"
	fi
	[ "$rc" = 0 ] || fail demo-exit
	offloaded "$A/server.log" || fail gpu-evidence
}

step_G21() {
	boot kick-plain || return
	row K=2 "OUT=$A/raw" -- bash "$E/run-llm-interference.sh"
	"${ROW[@]}" > "$A/run.log" 2>&1 < /dev/null || fail harness-exit
	file_has "$A/run.log" "window sampler verified:" || fail sampler-verified
	complete_line "$A/run.log" 2 || fail complete
}

# ------------------------------------------------------------------ before a step

# A = the attempt's own directory, <out>/<name>/<utc>: made by a mkdir that fails on one that
# exists, so never one that an earlier attempt wrote to.
new_attempt() {  # new_attempt <step, or session>
	local i utc
	mkdir -p "$O/$1" || return 1
	for i in 1 2 3; do
		utc=$(date -u +%Y%m%dT%H%M%SZ)
		if mkdir "$O/$1/$utc" 2>/dev/null; then
			A="$O/$1/$utc"
			return 0
		fi
		sleep 1
	done
	return 1
}

# MAN[name] = the sha256 the local manifest lists for an image. A line is an image's when its path
# is the image's name, alone or below output/ (the directory the images are in, as the list made
# on the board when it was backed up has them); a line for any other path is not read. An image
# listed twice with two hashes is listed by neither.
load_manifest() {
	local h p n
	[ -r "$MANIFEST" ] || return 1
	while read -r h p; do
		[[ "$h" =~ ^[0-9a-f]{64}$ ]] || continue
		p="${p%$'\r'}"; p="${p#\*}"; p="${p#./}"; n="${p#output/}"
		case "$n" in ""|*/*) continue ;; esac
		if [ -n "${MAN[$n]:-}" ] && [ "${MAN[$n]}" != "$h" ]; then MAN[$n]=listed-twice; else MAN[$n]="$h"; fi
	done < "$MANIFEST"
	return 0
}

images_match() {  # every image named, and the disk, is the file the manifest lists
	local n h p out
	local -a files=()
	local -A got=()
	for n in "$@" disk-qemu; do files+=("$IMG/$n"); done
	# One call for all of them; a file that cannot be read has no line, and is refused below.
	out=$(sha256sum -- "${files[@]}" 2>/dev/null < /dev/null)
	while read -r h p; do
		p="${p#\*}"
		if [ -n "$p" ]; then got[${p##*/}]="$h"; fi
	done <<< "$out"
	for n in "$@" disk-qemu; do
		if [ -z "${got[$n]:-}" ] || [ -z "${MAN[$n]:-}" ] || [ "${got[$n]}" != "${MAN[$n]}" ]; then
			say "  $IMG/$n is not the file $MANIFEST lists (or is not listed there once, or cannot be read)"
			return 1
		fi
	done
	return 0
}

# DEP[path] = 1 for every file the deploy manifest lists. That each of them matches is
# sha256sum's word, in the opening check; this is the list of what it was asked about.
load_deploy_list() {
	local h p
	[ -r "$DEPLOY_MANIFEST" ] || return 1
	while read -r h p; do
		[[ "$h" =~ ^[0-9a-f]{64}$ ]] || continue
		p="${p%$'\r'}"; p="${p#\*}"; p="${p#./}"
		if [ -n "$p" ]; then DEP["$p"]=1; fi
	done < "$DEPLOY_MANIFEST"
	return 0
}

deploy_lists() {  # every path given has its line in the deploy manifest
	local f
	for f in "$@"; do
		if [ -z "${DEP[$f]:-}" ]; then
			say "  $f has no line in $DEPLOY_MANIFEST: nothing held it to the deployed commit"
			return 1
		fi
	done
	return 0
}

last_passed() {  # the step's last line in the log is its PASS
	local line last=""
	[ -r "$GLOG" ] || return 1
	while IFS= read -r line; do
		case "$line" in "$1 "*) last="$line" ;; esac
	done < "$GLOG"
	[ "$last" = "$1 PASS" ]
}

# WHY_NOT = why a step is not run, by a rule of its own; empty when it may run. Each is said.
step_refusal() {  # step_refusal <step>
	local step="$1" prev=""
	WHY_NOT=""
	case "$step" in G19) prev=G18 ;; G20) prev=G19 ;; G21) prev=G20 ;; esac
	# The workaround first: it leaves G21 out for good, whatever passes before it.
	if [ -e "$STATE/nvmap-workaround" ] && [ "$step" = G21 ]; then
		say "  the NvMap workaround was needed: G21 is left out (gap 4o)"
		WHY_NOT=nvmap-workaround; return
	fi
	if [ -n "$prev" ] && ! last_passed "$prev"; then
		say "  the GPU tier goes in its order (CUDA alone, llama.cpp alone, then beside a guest), and $prev has no PASS as its last line in $GLOG"
		WHY_NOT=gpu-order; return
	fi
	if [ -e "$STATE/nvmap-workaround" ] && [ "$step" = G20 ] && ! file_has "$E/vlm-demo.sh" GGML_CUDA_ENABLE_UNIFIED_MEMORY; then
		say "  the NvMap workaround was needed, and the deployed vlm-demo.sh does not name GGML_CUDA_ENABLE_UNIFIED_MEMORY yet: the edge-LLM scripts gain the variable and stamp it first (gap 4o)"
		WHY_NOT=nvmap-workaround; return
	fi
	files_of "$step"
	# shellcheck disable=SC2086
	if [ -n "$FILES" ] && ! deploy_lists $FILES; then WHY_NOT=deploy-hash; return; fi
	images_of "$step"
	# shellcheck disable=SC2086
	if [ -n "$IMAGES" ] && ! images_match $IMAGES; then WHY_NOT=image-hash; fi
}

# The checks of the whole call, before its first step. REFUSAL is set by the first that fails.
opening() {
	local out
	# Into a file, as every command's output: whoever reads this script's own may have gone away.
	if ! bash "$PROVISION" check > "$SESSION/provision-check.log" 2>&1 < /dev/null; then
		say "provision-orin-r39.sh check did not exit 0: the board is not as provisioning leaves it. Its lines are in $SESSION/provision-check.log"
		REFUSAL=provision-check; return
	fi
	out=$(id -nG 2>/dev/null)
	case " $out " in
		*" kvm "*) ;;
		*) say "this login's session is not in the kvm group (a new login is needed after the provisioning script added it)"
			REFUSAL=kvm-group; return ;;
	esac
	if [ ! -e "$SYSR/class/net/br0" ] || [ ! -e "$SYSR/class/net/tap-qnx" ] || [ ! -e "$SYSR/class/net/br0/brif/tap-qnx" ]; then
		say "br0 or tap-qnx is missing, or tap-qnx is not a port of br0: the bridge is made once per boot (sudo bash setup-bridge-orin.sh)"
		REFUSAL=bridge; return
	fi
	# The list goes to sha256sum without its carriage returns: an older sha256sum takes one for
	# the last character of a file's name.
	if [ ! -r "$DEPLOY_MANIFEST" ] || ! tr -d '\r' < "$DEPLOY_MANIFEST" | (cd "$REPO" && sha256sum --strict --quiet -c -) > "$SESSION/deploy-check.log" 2>&1; then
		say "the files under $REPO are not what $DEPLOY_MANIFEST lists (or it cannot be read); see $SESSION/deploy-check.log"
		REFUSAL=deploy-hash; return
	fi
	load_deploy_list
	# This script's own three files, when the copy that runs is the deployed one. A step's own
	# are asked for with the step.
	if [ "$here" -ef "$REPO/scripts/orin" ] \
		&& ! deploy_lists scripts/orin/gate2-smoke.sh scripts/orin/lib-stick.sh scripts/orin/provision-orin-r39.sh; then
		REFUSAL=deploy-hash; return
	fi
	load_manifest || say "the image manifest $MANIFEST cannot be read: every step that boots an image will be refused"
	# The boot on record, and the cursor every new kernel line is counted from.
	first_line "$PROC/sys/kernel/random/boot_id"; BOOT_ID="$FL"
	first_line "$STATE/boot-id"
	if [ -z "$BOOT_ID" ]; then
		say "the boot id cannot be read"
		REFUSAL=boot-changed; return
	fi
	if [ -n "$FL" ] && [ "$FL" != "$BOOT_ID" ]; then
		if [ "${GATE2_NEW_BOOT:-}" != 1 ]; then
			say "the boot id is not the one on record: the board was reset or rebooted since the last call. Read reset_reason first, then pstore. A call after a boot somebody chose is started once with GATE2_NEW_BOOT=1"
			REFUSAL=boot-changed; return
		fi
		say "GATE2_NEW_BOOT=1: this boot is taken as the one on record from here on, with a fresh kernel journal cursor"
		rm -f "$STATE/cursor"
	fi
	# The boot on record is what the next call tells a reset by: a call that cannot write it down
	# is refused, or a reset between two calls would go unseen.
	if ! { printf '%s\n' "$BOOT_ID" > "$STATE/boot-id"; } 2> /dev/null; then
		say "the boot on record cannot be written to $STATE/boot-id: the next call would have nothing to tell a reset by"
		REFUSAL=boot-changed; return
	fi
	if [ "${GATE2_FRESH_CURSOR:-}" = 1 ]; then
		say "GATE2_FRESH_CURSOR=1: a fresh kernel journal cursor is taken; the kernel's lines before it are not read again"
		rm -f "$STATE/cursor"
	fi
	first_line "$STATE/cursor"; CURSOR="$FL"
	if [ -z "$CURSOR" ]; then
		out=$(sudo -n journalctl -k -q -n 0 --no-pager --show-cursor 2>/dev/null < /dev/null)
		CURSOR="${out##*-- cursor: }"
		if [ -z "$out" ] || [ "$CURSOR" = "$out" ] || [ -z "$CURSOR" ]; then
			say "no kernel journal cursor could be taken (sudo -n journalctl -k -n 0 --show-cursor)"
			CURSOR=""
			REFUSAL=kernel-cursor; return
		fi
		CURSOR="${CURSOR%%$'\n'*}"
		if ! { printf '%s\n' "$CURSOR" > "$STATE/cursor"; } 2> /dev/null; then
			say "the kernel journal cursor cannot be written to $STATE/cursor: the next call would count the kernel's new lines from somewhere else"
			REFUSAL=kernel-cursor; return
		fi
	fi
	state_check "$SESSION"
	REFUSAL="$WRONG"
}

cleanup() {
	if [ -n "$VM_PID" ]; then stop_boot; tidy; fi
}

# ------------------------------------------------------------------ main

if [ "$#" = 0 ]; then echo "$USAGE" >&2; exit 64; fi
for s in "$@"; do
	case "$s" in
		-h|--help) echo "$USAGE"; echo "  See the header of this file."; exit 0 ;;
	esac
	is_step "$s" || { echo "gate2-smoke.sh: not a step: $s" >&2; echo "$USAGE" >&2; exit 64; }
done

# A reader of this script's output that goes away must not end it in the middle of a step. A
# handler, not an ignore: an ignored signal would be inherited by every harness, and their
# `tegrastats | head -1` reads rely on SIGPIPE ending the writer.
trap ':' PIPE
trap cleanup EXIT

mkdir -p "$G" "$STATE" || { echo "FATAL: cannot make $G" >&2; exit 1; }

# The GPU tier first, before any command is run: with the first GPU load on a new release the
# owner is at the board, and says so.
todo=0
for s in "$@"; do
	if is_gpu_step "$s" && [ "${GATE2_GPU_OWNER_PRESENT:-}" != 1 ]; then continue; fi
	todo=$((todo + 1))
done
if [ "$todo" = 0 ]; then
	for s in "$@"; do turn_away "$s" gpu-owner-absent; done
	say "The GPU tier runs with the owner at the board, a serial capture running and no camera: GATE2_GPU_OWNER_PRESENT=1 is the owner's to give."
	exit 2
fi

UID_NOW=$(id -u 2>/dev/null)
if [ -z "$UID_NOW" ] || [ "$UID_NOW" = 0 ]; then
	echo "gate2-smoke.sh: refused: run it as the login that runs the guests, never as root (the harnesses call sudo -n themselves)" >&2
	exit 2
fi

passed=""
for v in $PASS_NAMES; do
	if [ -n "${!v+x}" ]; then PASS_ENV+=("$v=${!v}"); passed="$passed $v"; fi
done

say "gate2-smoke.sh $*"
say "a row's command gets, of this session's environment:$passed -- and nothing else but the row's own variables"
[ "$SYSR" = /sys ] || say "WARNING: SYS_ROOT overridden to $SYSR -- test use only"
[ "$PROC" = /proc ] || say "WARNING: PROC_ROOT overridden to $PROC -- test use only"
[ "$RUNR" = /run ] || say "WARNING: RUN_ROOT overridden to $RUNR -- test use only"
[ "$SHMR" = /dev/shm ] || say "WARNING: SHM_ROOT overridden to $SHMR -- test use only"
[ "$TMPR" = /tmp ] || say "WARNING: TMP_ROOT overridden to $TMPR -- test use only"
[ "$PROVISION" = "$here/provision-orin-r39.sh" ] || say "WARNING: GATE2_PROVISION overridden to $PROVISION -- test use only"
[ "$here" -ef "$REPO/scripts/orin" ] || say "WARNING: this gate2-smoke.sh is not the copy under $REPO/scripts/orin, so the deploy's manifest does not hold it -- test use only"

if new_attempt session; then
	SESSION="$A"
	opening
else
	say "no directory of its own could be made for this call under $O/session"
	REFUSAL=attempt-directory
fi
[ -z "$REFUSAL" ] || say "REFUSED before the first step: $REFUSAL. No step of this call is run."

steps=("$@")
for ((i = 0; i < ${#steps[@]}; i++)); do
	step="${steps[$i]}"
	next="${steps[$((i + 1))]:-}"
	say "---- $step"
	why=""
	if is_gpu_step "$step" && [ "${GATE2_GPU_OWNER_PRESENT:-}" != 1 ]; then
		why=gpu-owner-absent
	elif [ -n "$REFUSAL" ]; then
		# The call's own refusal first: every line of a refused call names what refused it, and
		# the stick is named only for a step that could otherwise run.
		why="$REFUSAL"
	else
		if is_vm_step "$step"; then
			stick_rule "every step that creates a KVM VM"
			case "$STICK_WORD" in
				ok) ;;
				note) say "installer stick: $STICK_TEXT" ;;
				*) say "installer stick: $STICK_TEXT"; why=stick ;;
			esac
		fi
		if [ -z "$why" ]; then step_refusal "$step"; why="$WHY_NOT"; fi
	fi
	if [ -n "$why" ]; then
		turn_away "$step" "$why"
		# A guest kept for this step is not kept past its refusal.
		if [ -n "$VM_PID" ]; then
			stop_boot
			tidy
			after_check "$SESSION"
		fi
		continue
	fi
	if ! new_attempt "$step"; then
		turn_away "$step" attempt-directory
		if [ -n "$VM_PID" ]; then stop_boot; tidy; fi
		continue
	fi
	say "$step: its files are in $A"
	WHY=""; NO_RECORD=0
	"step_$step"
	if [ "$NO_RECORD" = 0 ]; then
		record "$step" "$WHY"
		if [ -n "$WHY" ] && [ "$RC" = 0 ]; then RC=1; fi
	fi
	keep=""
	boot_of "$step"; shares="$SHARES"
	boot_of "$next"
	# Kept only for a next step that shares the boot, and never after a launch that failed: a
	# QEMU the launcher gave up on is not a guest to read the next step's rule from.
	if [ -n "$VM_PID" ] && [ "$WHY" != launch ] && [ -n "$shares" ] && [ "$shares" = "$SHARES" ] && alive "$VM_PID"; then
		keep=keep
		say "  the guest is kept for $next, which shares this boot"
	else
		stop_boot
		tidy
	fi
	after_check "$A" "$keep"
done
cleanup
exit "$RC"
