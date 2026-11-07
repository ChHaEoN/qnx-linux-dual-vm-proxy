#!/usr/bin/env bash
# KVM here boots our startup-qemu-virt; this is not a QNX-supported
# configuration, and no timing claim attaches to the boot.
# remote-ladder.sh -- the instance side of a bare-metal AWS ladder session.
# One phase per call, so the operator (drive-metal.sh run PHASE) sees each step:
#
#   setup     host facts, METAL_QEMU_PKG, unpack, verify the images, disk and uploaded
#             files (in/) against inputs.env, bridge, probe, native monitor, KVM counters readable
#   quiesce   let cloud-init and snap settle, stop the apt timers for the session, and stop
#             and record the platform's units (QUIESCE ON THIS TOOLING, below)
#   launch    boot the guest with the ivshmem server and the kick console, and check
#             that its shm services came up
#   ladder    run-ladder.sh with LADDER_ENV (default: the notified-shm ladder of
#             record `20260922T-a6-orin-kick`, held locally) and K=12
#   capture   redact on THIS host into pub/, then pack pub.tgz (see capture.py)
#   stop      stop QEMU (a rehearsal on the Orin uses this)
#
# SETUP AND THE HOST'S FACTS (2026-10-08). setup PRINTS what it learns about the host
# before it checks anything, and writes host-facts.txt as soon as the record has a
# directory and not last. METAL_QEMU_PKG, the QEMU package version a session may
# expect, is refused on before that directory exists, so a setup stopped by a
# mistyped value can be run again: see "the host's facts", below.
#
# A LIVENESS SESSION (OD14, 2026-09-23) runs two other phases instead of launch
# and ladder, with ifs-live.bin as the image:
#
#   launch-live  boot the guest plainly -- no ivshmem, no kick console -- and
#                check that :7102 runs the 2000 ms deadline mode
#   liveness     liveness-demo.sh (the synthetic demo), then run-live-cost.sh
#                (plain TCP against the deadline mode, K rounds). On a host
#                without Tegra tools the cost run's GPU checks and window
#                sampler are recorded as not applicable (see its header).
#
# A STAMP SESSION (OD15, 2026-09-23), with ifs-stamp.bin as the image:
#
#   launch-stamp  boot the guest plainly and check :7100 (plain) and :7103
#                 (stamping) both came up
#   stamp         run-stamp.sh: plain against stamped, on the guest and on the
#                 native control, K rounds (a multiple of 4)
#
# A METAL SESSION (2026-09-25), with ifs-stamp.bin as the image:
#
#   metal         boot the guest plainly and check :7103 came up, then run-metal.sh
#                 (open against confined host userspace, and the tick bin; K rounds,
#                 default 40) IN THE SAME SSH SESSION: the harness confines every
#                 other session scope, so a guest booted by an earlier phase would be
#                 confined with them
#
# A SOME/IP SESSION (OD12, 2026-09-27), with ifs-someip.bin as the image:
#
#   someip        install Boost 1.74 (the versioned packages, as on the Orin) and a toolchain,
#                 build vsomeip 3.4.10 and someip_vprobe with
#                 orin-native/someip/build-vsomeip.sh (the commit it pins; the build stays on
#                 this host, with a job count and a memory cap sized to it), then
#                 run-someip.sh (K rounds, a multiple of 8, default 16) and
#                 run-someip0.sh (12 rounds), each booting its own guests
#
# A HARNESS SESSION (2026-09-27): one or more images (METAL_IFS, plus METAL_IFS_EXTRA, each verified
# by setup), and one call per harness:
#
#   harness       LADDER_ENV="HARNESS=<name> IMAGE=<image>", K optional. Runs one harness from a
#                 fixed list -- run-someip.sh, run-someip0.sh, run-someip1.sh, run-trace.sh,
#                 run-trace2.sh, run-haltpoll.sh, run-bell.sh, run-paths.sh, run-mmio.sh, run-bellrate.sh
#                 (2026-09-29), run-unmask.sh and run-bellrobust.sh (2026-09-29, later) -- each of
#                 which boots its own guests, on an image
#                 this session uploaded and verified, into $REC/<name without run- and .sh>. The
#                 SOME/IP harnesses first build vsomeip here, once per session.
#                 A harness that boots more than one image names them with IMG_ words (2026-09-29,
#                 later), each an image this session uploaded:
#                   run-unmask.sh      IMG_UA=ifs-unmask-a.bin IMG_UB=ifs-unmask-b.bin (two different
#                                      images; K a multiple of 4; it reads no IMAGE=)
#                   run-bellrobust.sh  IMAGE=ifs-bell.bin (or IMG_B=) IMG_R=ifs-robust.bin
#                                      IMG_UA=ifs-unmask-a.bin (no K: its three repeats are
#                                      pre-registered)
#                 Before it makes $REC/<name>, the phase refuses: no LADDER_ENV; a word it does not
#                 read, or one with no value; a word given twice; an IMG_ word it does not take for
#                 that harness (only these two take any; every other harness's image is IMAGE=,
#                 even one that reads IMG_B); a K with a leading zero, or 0; and a multi-image
#                 harness missing one of its images. An omitted IMG_R, IMG_UA or IMG_UB would fall
#                 back to the harness's own $HOME/output default, absent here, and the run would
#                 fail at its preflight; an omitted IMG_B would be the session's first image, and
#                 the run would go on with it. Either way it would use up that harness's one run
#                 per session.
#                 Both list a1.metal among what their pre-registrations do not test, so a run here
#                 is a replication outside them, not part of either; run-unmask.sh's stated reason
#                 (one IMAGE=, and not in this list) predates these words.
#
# A VSS SESSION (plan Phase 3, 2026-10-03; README.md, "A vss session instead"), with
# ifs-vss.bin as the image, a repo tarball that also carries sdv, and the upload bundle as METAL_FILES
# (in/, verified by setup). Two harnesses join the harness phase's list, and each runs DETACHED:
#
#   harness       LADDER_ENV="HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin", then (a later login, so the
#                 docker group applies) LADDER_ENV="HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1|v2" (or
#                 IMAGE=ifs-vss-carla.bin PLAN=carla, SDV Phase 7 WP3d: the CARLA pair, in a session whose
#                 METAL_IFS is that image; this phase passes the word through, and the suite's own preflight
#                 refuses it, spending its one run, when the profiles setup's guest listed in its `vss rules:`
#                 lines do not include 3, when setup recorded no list, or when a recording's log is not
#                 staged).
#                 Both refuse K and every IMG_ word and need IMAGE=, the session's METAL_IFS and no other
#                 image; PLAN= is the suite's alone. VSS_HOST=a1-metal|c7g-metal (2026-10-17), either harness's
#                 and optional, is the host mode the harness gets as VSS_HOST (run-vss-setup.sh, THE MODES):
#                 none is a1-metal, c7g-metal names this tooling's METAL_TYPE=c7g.metal; orin and any other
#                 value are refused (the board's mode is its own helper's), and so is the word on an A6
#                 harness. Setup's word is kept in $W/vss-host (outside $REC: never captured), and the
#                 suite is refused unless its word is setup's (no word on either side is a1-metal): the
#                 suite's own preflight would refuse a setup of another mode, spending its one run.
#                 Before it makes anything the phase refuses a vss harness
#                 when the tarball lacks sdv/stack/step3.py or lib-vss-deadline.sh; when quiesce has not
#                 written rec/quiesce.txt; when inputs.env is no longer the copy setup verified and kept in
#                 rec/tooling (an upload after setup); while rec holds an A6 record (a directory other than
#                 tooling/, a vss stem or setup's own empty ladder/), which a vss capture would leave out; and,
#                 for the suite, unless rec/vss-setup has done and a last status line status=DONE. It then
#                 writes the session marker, makes rec/<vss-setup|vss-suite> and its host-before.txt, and
#                 starts the harness with setsid nohup (its own output to detach.log, so this ssh session's
#                 pipe reaches EOF at once). The runner's run.log is the proof that it started: once it
#                 appears the phase prints `started` and returns 0; if it does not, the phase sends TERM to
#                 the runner's process group (under setsid the runner leads its own; to its pid alone when
#                 there is no such group), prints detach.log, removes the stem directory it made (so the
#                 phase can run again; the marker stays) and fails. The detached runner (_detached,
#                 internal: drive-metal.sh's PHASES does not list it) runs with SIGPIPE, SIGHUP, SIGINT and
#                 SIGQUIT ignored (SIGNALS, below), opens run.log only once its own checks passed, runs the
#                 harness into it, and then: exit 0 with a last status= line of DONE or TIMEOUT writes
#                 host-after.txt; anything else appends `status=FAILED rc=N` and writes no host-after. Either
#                 way it syncs and touches done.
#   wait-run      LADDER_ENV="HARNESS=<that harness>", nothing else. Blocks in this one ssh session (sleeps
#                 on this host, never logins) until done exists, and gives up at stop_at + 12 minutes (the
#                 deadline - 13 minutes; lib-vss-deadline.sh). Prints the last status line, whether done
#                 exists and run.log's last 30 lines; exits 0 for DONE and TIMEOUT, 2 when it gave up, 1
#                 otherwise. The operator runs it as a background task with no tool timeout, and after a
#                 disconnect once more by hand, never in a loop. It cannot tell a runner that never started
#                 from one still running: when the harness phase's own session ended during its start wait
#                 and the runner then failed to start, nothing removes the stem, and wait-run waits to the
#                 give-up point and prints "(no run.log)".
#
#   THE OTA DRILL (SDV plan Phase 6 WP6, 2026-10-19; README.md, "An OTA drill session"). A third detached
#   harness, run-ota-drill.sh, joins the two: LADDER_ENV="HARNESS=run-ota-drill.sh [VSS_HOST=a1-metal|c7g-metal]", in a
#   later login than setup's, into rec/ota-drill. It boots no image and takes no IMAGE=, PLAN=, K or IMG_ word: each is
#   refused (it gets the session's image paths in its environment only as every vss harness does). VSS_HOST= is as
#   above. Before it makes anything the phase refuses it as it refuses the suite, without a finished setup whose last
#   status line is status=DONE or with a VSS_HOST that is not setup's, and when the tarball lacks sdv/drill/drill.py; and
#   neither it nor the suite starts while the other still runs (its stem without done): each needs setup DONE only, and
#   the two would share the host's Docker and the stack. The other refusals, the session marker, the detached start,
#   wait-run and one run per session are a vss harness's. Its
#   stem, ota-drill, is a vss stem wherever one is read: not an A6 record, the capture's gate, capture.py's evidence.
#   Its three files (DRILL_FILES) come in METAL_FILES beside the upload bundle; setup checks their hashes with the others
#   and then moves them from in/ to drill-in/, because run-vss-setup.sh's bundle.py verify refuses a file in in/ that
#   bundle.json does not list. The phase gives the drill DRILL_IN=$W/drill-in, and the other two harnesses no such word.
#
#   THE AW SESSION (SDV Phase 8 WP6 9.2, 2026-10-26; README.md, "An aw session"). Two more detached harnesses,
#   run-aw-setup.sh and run-aw-suite.sh, join the list, into rec/aw-setup and rec/aw-suite (each a vss stem wherever one
#   is read: not an A6 record, the capture's gate, capture.py's evidence). Their session runs run-vss-setup.sh first with
#   IMAGE=ifs-ctl.bin (the session's METAL_IFS), then LADDER_ENV="HARNESS=run-aw-setup.sh IMAGE=ifs-ctl.bin
#   VSS_HOST=c7g-metal" in a later login, then LADDER_ENV="HARNESS=run-aw-suite.sh IMAGE=ifs-ctl.bin PLAN=a1|a2|b1|b2|s
#   VSS_HOST=c7g-metal". Each needs IMAGE=, the session's METAL_IFS, and VSS_HOST=c7g-metal and no other host word (the
#   owner took the a1-metal role off the Autoware image's hosts on 2026-10-24; none is refused too); PLAN= is the
#   suite's, its five words; K and every IMG_ word are refused. Before it makes anything the phase refuses either one
#   when the tarball lacks sdv/aw, as it refuses the suite: without a finished run-vss-setup.sh whose last status line is
#   status=DONE, with a VSS_HOST that is not setup's, or while another vss harness still runs; and the aw suite also
#   unless rec/aw-setup has done and a last status line status=DONE. The marker, the detached start, wait-run and one run
#   per session are a vss harness's. Their inputs (aw-inputs.json, aw-scan.json, aw-map.tar: each name aw-*) come in
#   METAL_FILES beside the upload bundle; setup checks their hashes with the others and then moves every aw-* file from
#   in/ to aw-in/, for the reason it moves the drill's, and the phase gives the two AW_IN=$W/aw-in. Each harness writes
#   the host check into its stem's host-before.txt and host-after.txt itself, so the detached runner appends its
#   host-after.txt there instead of writing it anew.
#   SDV Phase 8 WP8: run-aw-g1.sh, the c7g.metal rehearsal of gate G1, is one more aw harness, into rec/aw-g1,
#   under the suite's rule: LADDER_ENV="HARNESS=run-aw-g1.sh IMAGE=ifs-ctl.bin PLAN=rehearsal VSS_HOST=c7g-metal" after run-aw-setup.sh ended DONE.
#   Its record's figures are never G1's. On the Orin its helper starts it, never this phase.
#
#   THE SESSION MARKER. Starting a vss harness writes $W/vss-session (outside rec, never captured). While it
#   exists Docker may have run here, so the harness phase refuses every A6 harness of its list by name, and
#   launch, ladder, launch-live, liveness, launch-stamp, stamp, metal and someip refuse at their first line.
#
#   SIGNALS. The
#   detached runner and its harness run with SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored: INT and QUIT because
#   bash ignores both for a command it starts in the background with no job control (this phase's `setsid nohup
#   ... &`), HUP through nohup and the runner's trap, PIPE through that trap. Every child inherits them as
#   ignored, and neither the runner nor the harness traps or resets them (bash 5.2 can reset an inherited
#   ignored INT with `trap - INT`; nothing here does). So a SIGHUP,
#   SIGINT or SIGQUIT sent to the runner or the harness does nothing, and a Python the harness runs directly
#   (the suite's vss_suite.py calls outside a cap, say) installs no KeyboardInterrupt: Python sets its SIGINT
#   handler only when SIGINT is at its default as it starts. A unit under its cap differs: GNU timeout catches
#   HUP, INT, QUIT and TERM before it forks, and an exec resets a caught signal to its default, so the unit starts
#   with only SIGPIPE ignored: step3.py, which runs under its cap, does install its
#   KeyboardInterrupt. Python's own children get SIGPIPE back at its default (subprocess's restore_signals). The
#   caps signal with TERM and KILL, which are not ignored by anything here (lib-vss-deadline.sh, THE CONTRACT); a
#   process that ignores the TERM does so itself.
#
#   CAPTURE OF A VSS RECORD. capture takes a vss stem that has done and a terminal status line (DONE, TIMEOUT or
#   FAILED; a FAILED one, which has no host-after.txt, is packed for its diagnostics and marked so). While a vss
#   stem has no done the capture refuses, until wait-run's give-up point has passed; then capture.py packs that
#   stem as it stands, named INCOMPLETE. capture.py publishes a vss record by a whitelist and names what it leaves
#   out in capture.log, which goes into pub.tgz too: in/ and bin/ always, a file it cannot read, and a JSON or
#   JSONL file that does not parse in a stem that did not end whole (TIMEOUT, FAILED, INCOMPLETE, NO STATUS).
#
# QUIESCE ON THIS TOOLING (every session, A6 included): after the apt timers, it runs
# platform-quiesce.sh stop with one fixed state path, $W/platform-quiesce.state, then
# /usr/local/bin/k3s-killall.sh as root when that is executable, both outputs and exit statuses into
# rec/quiesce.txt -- so it needs setup first -- and that record heads every later host-before.txt. A stop
# that refused before it changed anything (exit 3) is recorded and is not fatal; any other non-zero status of
# either is fatal. It never restores: an instance is discarded. A rehearsal host that lives on is restored by
# hand (platform-quiesce.sh restore $W/platform-quiesce.state).
#
# capture accepts any of these sessions, but only a FINISHED one (a vss session's stems: CAPTURE OF A VSS RECORD,
# above).
#
# W (default ~/a1) holds repo.tar, inputs.env, remote-ladder.sh, capture.py,
# img/<ifs> + img/disk-qemu.gz, and in/<file> for every METAL_FILES file (drill-in/<file> for the OTA drill's three,
# which setup moves there once checked). Nothing under W leaves the
# host except pub.tgz, and everything in pub.tgz went through redact-aws.sh or capture.py's check here.
set -euo pipefail
PHASE="${1:?phase: setup|quiesce|launch|ladder|launch-live|liveness|launch-stamp|stamp|metal|someip|harness|wait-run|capture|stop}"
W="${W:-$HOME/a1}"
R="$W/repo/orin-native/gpu-concurrency"
REC="$W/rec"
LADDER_GIVEN="${LADDER_ENV:+1}"   # the harness phase takes no default: it needs the operator's words
LADDER_ENV="${LADDER_ENV:-SHM=1 KICK=1 DB=1 UDP_IN_TCP=1 KVM_STATS=1 ARM_C_PORT=7000 CSTATE=shallow}"
say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { say "FATAL: $*" >&2; exit 1; }
inputs() {
	[ -r "$W/inputs.env" ] || die "no $W/inputs.env (drive-metal.sh upload writes it)"
	# Parsed, not sourced: fixed names, fixed shapes.
	IFS_NAME="$(sed -n 's/^IFS_NAME=\([A-Za-z0-9._-][A-Za-z0-9._-]*\)$/\1/p' "$W/inputs.env")"
	IFS_SHA256="$(sed -n 's/^IFS_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	DISK_SHA256="$(sed -n 's/^DISK_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	RL_SHA256="$(sed -n 's/^REMOTE_LADDER_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	CAP_SHA256="$(sed -n 's/^CAPTURE_SHA256=\([0-9a-f]\{64\}\)$/\1/p' "$W/inputs.env")"
	REPO_COMMIT="$(sed -n 's/^REPO_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' "$W/inputs.env")"
	[ -n "$IFS_NAME" ] && [ -n "$IFS_SHA256" ] && [ -n "$DISK_SHA256" ] \
		&& [ -n "$RL_SHA256" ] && [ -n "$CAP_SHA256" ] || die "inputs.env is malformed"
	# 2026-09-27: more images, "NAME:SHA256" words; absent in older sessions' files.
	IFS_EXTRA=""
	if grep -q '^IFS_EXTRA=' "$W/inputs.env"; then
		IFS_EXTRA="$(sed -n 's/^IFS_EXTRA=\([A-Za-z0-9._: -]*\)$/\1/p' "$W/inputs.env")"
		[ -n "$IFS_EXTRA" ] || die "inputs.env is malformed (IFS_EXTRA)"
		for x in $IFS_EXTRA; do
			[[ "$x" =~ ^[A-Za-z0-9._-]+:[0-9a-f]{64}$ ]] || die "inputs.env is malformed (IFS_EXTRA word '$x')"
		done
	fi
	# 2026-10-03: the uploaded files (METAL_FILES, in in/), "NAME:SHA256" words the same way.
	FILES=""
	if grep -q '^FILES=' "$W/inputs.env"; then
		FILES="$(sed -n 's/^FILES=\([A-Za-z0-9._: -]*\)$/\1/p' "$W/inputs.env")"
		[ -n "$FILES" ] || die "inputs.env is malformed (FILES)"
		for x in $FILES; do
			[[ "$x" =~ ^[A-Za-z0-9._-]+:[0-9a-f]{64}$ ]] && [ "${x%%:*}" != . ] && [ "${x%%:*}" != .. ] \
				|| die "inputs.env is malformed (FILES word '$x')"
		done
	fi
}

# The host, before and after a run. host-before.txt starts with the quiesce record when there is one (SDV).
host_snapshot() { date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; }
host_before() {   # $1 the file
	{ [ ! -r "$REC/quiesce.txt" ] || cat "$REC/quiesce.txt"; host_snapshot; } > "$1"
}

# plan Phase 3: the vss harnesses, which run detached, and the session marker they leave.
VSS_HARNESSES="run-vss-setup.sh run-vss-suite.sh run-ota-drill.sh run-aw-setup.sh run-aw-suite.sh run-aw-g1.sh"
# SDV Phase 6 WP6: the OTA drill's files, which setup moves from in/ (the upload bundle's) to drill-in/ once checked
DRILL_FILES="drill-images.json sdv-drill.tar sdv-drill.tar.sha256"
is_vss() { case " $VSS_HARNESSES " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
# SDV Phase 8 WP6 9.2: the Autoware session's two harnesses (THE AW SESSION)
is_aw() { case "$1" in run-aw-setup.sh|run-aw-suite.sh|run-aw-g1.sh) return 0 ;; *) return 1 ;; esac; }
marker_refuses() {   # $1 what is refused: an A6 measuring phase or harness, while a vss harness has run here
	[ ! -e "$W/vss-session" ] || die "$W/vss-session exists: a vss harness ran in this session, so Docker may have run on this host and $1 does not run here (the session marker, scripts/aws/README.md)"
}

image_path() {   # $1 an image name: its path, if this session uploaded it (setup verified its hash)
	local x
	if [ "$1" = "$IFS_NAME" ]; then echo "$W/img/$1"; return 0; fi
	for x in $IFS_EXTRA; do
		if [ "${x%%:*}" = "$1" ]; then echo "$W/img/$1"; return 0; fi
	done
	return 1
}

# ------------------------------------------------------------------ the host's facts
# 2026-10-08, for the move to an Ubuntu 24.04 image. What setup learns about the host is
# PRINTED first, before any check, and WRITTEN to $REC/host-facts.txt as soon as the
# record has a directory. Until then the file was setup's last act, after the KVM
# counter check: the check a new kernel is most likely to fail, so the setup that most
# needed to say which kernel it had met said nothing. The printed lines hold no
# identifier (a kernel release, CONFIG_HZ, the tick handler's name, the lockdown state,
# whether the KVM counters read, the QEMU package's version, what a panic does), and
# reach the operator's transcript through the driver's red() as they are.
#
# TICK_HANDLERS is tick_trace.py's list: the facts are read before the repository is
# unpacked, so that file cannot be read here. tests/test_aws_noble.py holds the two
# lists equal. The name is the one kallsyms has, whole: "unknown" when it has none of
# the three, and every one it has, once each and comma-separated, when it has more than
# one. Mainline up to 6.6 does: tick_sched_timer, and tick_nohz_handler as the name of
# another function than the one that took it later.
#
# CONFIG_HZ is read the way lib-measure.sh's m_config_hz reads it: the gzipped config
# in /proc, else the boot config of this release. It is said here and never judged:
# the harnesses whose rules are fixed on one tick grid refuse another by themselves.
#
# WHETHER THE KVM COUNTERS READ is a fact too (2026-10-08, later), and not only the
# check further down that stops setup: a setup refused before that check, on
# METAL_QEMU_PKG, has then still said it, and it is what a fallback is planned from.
# The names are lib-measure.sh's KVM_COUNTERS, taken out of the uploaded tarball
# without unpacking it: the list the check reads. "readable"; "unreadable:" and the
# names that did not give an integer; "unread" when the list could not be taken or
# /sys/kernel/debug/kvm could not be looked at (no debugfs there yet, or sudo wants a
# password). Read with sudo -n and nothing else: nothing is mounted for it.
#
# PROC_ROOT, SYS_ROOT, KCONFIG_GZ and KCONFIG_BOOT are overridable so the tests can fake
# a host, as lib-measure.sh's are. An override of a root is announced, and
# host-facts.txt records the roots it was read under and the file CONFIG_HZ came from.
TICK_HANDLERS="tick_sched_timer tick_nohz_highres_handler tick_nohz_handler"
PROC_ROOT="${PROC_ROOT:-/proc}"
SYS_ROOT="${SYS_ROOT:-/sys}"
roots_announce() {
	[ "$PROC_ROOT" = /proc ] || say "WARNING: PROC_ROOT overridden to $PROC_ROOT -- test use only; host-facts.txt records it"
	[ "$SYS_ROOT" = /sys ] || say "WARNING: SYS_ROOT overridden to $SYS_ROOT -- test use only; host-facts.txt records it"
	return 0
}

qemu_pkg_read() {   # dpkg's version of qemu-system-arm as it is now, or "none"
	local v
	# shellcheck disable=SC2016  # ${Version} is dpkg-query's own format field
	v="$(dpkg-query -W -f='${Version}' qemu-system-arm 2>/dev/null || true)"
	printf '%s\n' "${v:-none}"
}

kvm_counters_read() {   # prints readable | unreadable:NAME[,NAME...] | unread. Reads only; never fails.
	local names c v bad=""
	names="$(tar -xOf "$W/repo.tar" orin-native/gpu-concurrency/lib-measure.sh 2>/dev/null \
		| sed -n 's/^KVM_COUNTERS="\([A-Za-z0-9_ ]*\)"$/\1/p' || true)"
	names="${names%%$'\n'*}"
	if [ -z "$names" ] || ! sudo -n test -d /sys/kernel/debug/kvm 2>/dev/null; then
		echo unread
		return 0
	fi
	for c in $names; do
		v="$(sudo -n cat "/sys/kernel/debug/kvm/$c" 2>/dev/null || true)"
		case "$v" in ''|*[!0-9]*) bad="${bad:+$bad,}$c" ;; esac
	done
	echo "${bad:+unreadable:}${bad:-readable}"
}

facts_read() {   # sets the F_ variables from the running host. Reads only; never stops setup.
	local text="" gz boot
	F_KERNEL="$(uname -r 2>/dev/null || true)"; F_KERNEL="${F_KERNEL:-unread}"
	gz="${KCONFIG_GZ:-$PROC_ROOT/config.gz}"
	boot="${KCONFIG_BOOT:-/boot/config-$F_KERNEL}"
	F_HZ_SRC=unread
	if text="$(zcat "$gz" 2>/dev/null)"; then
		F_HZ_SRC="$gz"
	elif text="$(cat "$boot" 2>/dev/null)"; then
		F_HZ_SRC="$boot"
	else
		text=""
	fi
	# sed reads the whole text and bash takes the first line, as m_config_hz does: a
	# `| head -1` could close the pipe early, which under pipefail is a failure.
	F_HZ="$(printf '%s\n' "$text" | sed -n 's/^CONFIG_HZ=\([0-9][0-9]*\)$/\1/p')" || F_HZ=""
	F_HZ="${F_HZ%%$'\n'*}"
	[ -n "$F_HZ" ] || { F_HZ=unread; F_HZ_SRC=unread; }
	F_TICK="$(awk -v want="$TICK_HANDLERS" '
		BEGIN { n = split(want, w, " "); for (i = 1; i <= n; i++) is[w[i]] = 1 }
		($3 in is) && !seen[$3]++ { out = out (out == "" ? "" : ",") $3 }
		END { print out }' "$PROC_ROOT/kallsyms" 2>/dev/null || true)"
	F_TICK="${F_TICK:-unknown}"
	F_LOCKDOWN="$(cat "$SYS_ROOT/kernel/security/lockdown" 2>/dev/null || true)"; F_LOCKDOWN="${F_LOCKDOWN:-absent}"
	F_KVM="$(kvm_counters_read 2>/dev/null || true)"; F_KVM="${F_KVM:-unread}"
	F_QEMU_PKG="$(qemu_pkg_read)"
	# cat, not a redirection: a `<` that cannot open its file is reported by the shell
	# before a later 2>/dev/null applies.
	F_PANIC_CMDLINE="$(cat "$PROC_ROOT/cmdline" 2>/dev/null | tr ' ' '\n' | sed -n 's/^panic=//p' | tail -1 || true)"
	F_PANIC_CMDLINE="${F_PANIC_CMDLINE:-absent}"
	F_PANIC="$(cat "$PROC_ROOT/sys/kernel/panic" 2>/dev/null || true)"; F_PANIC="${F_PANIC:-unread}"
	return 0
}

facts_print() {   # the facts that carry no identifier, to the terminal
	roots_announce
	say "host facts, before any check (a setup that stops has still said them):"
	printf 'host fact: %s\n' "kernel_release=$F_KERNEL" "config_hz=$F_HZ" "config_hz_source=$F_HZ_SRC" \
		"tick_handler=$F_TICK" "lockdown=$F_LOCKDOWN" "kvm_counters=$F_KVM" "qemu_pkg=$F_QEMU_PKG" \
		"qemu_pkg_expected=${METAL_QEMU_PKG:-unset}" "cmdline_panic=$F_PANIC_CMDLINE" "kernel_panic=$F_PANIC"
	# What a panic does is read from the running kernel, not taken from the image:
	# kernel.panic other than 0 reboots, and userdata.sh's per-boot script re-arms the
	# deadline; 0 halts, and a halted host runs no timer. Said, and not a reason to
	# stop: README.md names what the deadline cannot bound.
	if [[ "$F_PANIC" =~ ^-?[0-9]+$ ]] && [ "$F_PANIC" -ne 0 ]; then
		say "a host panic reboots this kernel (kernel.panic is $F_PANIC); the per-boot script re-arms the deadline after any reboot"
	elif [[ "$F_PANIC" =~ ^-?0+$ ]]; then
		say "WARNING: a host panic HALTS this kernel (kernel.panic is 0): a halted host runs no timer, so nothing on the instance bounds it -- if SSH is lost, terminate from the operator's machine"
	else
		say "WARNING: what this kernel does on a panic could not be read (kernel.panic: $F_PANIC)"
	fi
	if [ -n "${METAL_QEMU_PKG:-}" ] && [ "$F_QEMU_PKG" != "$METAL_QEMU_PKG" ]; then
		say "WARNING: qemu-system-arm is '$F_QEMU_PKG' here and METAL_QEMU_PKG expects '$METAL_QEMU_PKG': setup will refuse on it before it makes a record"
	fi
	return 0
}

facts_write() {   # $1 the file: the host as it is now. setup calls it twice (see there).
	local n m p c x f
	: > "$1"
	# Nothing in the block may stop setup: every command in it is left of the `||`.
	{
		echo "== uname -v"; uname -v
		echo "== uname -r"; echo "$F_KERNEL"
		echo "== nproc"; nproc
		echo "== lockdown"; echo "$F_LOCKDOWN"
		# The root PARTUUID is masked: probably AMI-level, but not confirmed.
		echo "== cmdline"; sed -E 's/PARTUUID=[0-9a-fA-F-]+/PARTUUID=<partuuid>/g' "$PROC_ROOT/cmdline"
		echo "== transparent_hugepage"; cat "$SYS_ROOT/kernel/mm/transparent_hugepage/enabled" 2>/dev/null || echo absent
		echo "== br_netfilter"; lsmod | grep -c '^br_netfilter' || true
		echo "== bridge ports (port master)"
		for n in "$SYS_ROOT"/class/net/*; do m="$(readlink "$n/master" 2>/dev/null || true)"; [ -n "$m" ] && echo "$(basename "$n") $(basename "$m")"; done
		echo "== kvm halt_poll"; for p in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do echo "$p=$(cat "$SYS_ROOT/module/kvm/parameters/$p" 2>/dev/null || echo NA)"; done
		echo "== qemu package"; echo "qemu_pkg=$F_QEMU_PKG"
		echo "== lscpu -e"; lscpu -e 2>/dev/null || true
		echo "== cache sharing, cpu0-5"
		for c in 0 1 2 3 4 5; do for x in 2 3; do f="$SYS_ROOT/devices/system/cpu/cpu$c/cache/index$x/shared_cpu_list"; [ -r "$f" ] && echo "cpu$c L$x: $(cat "$f")"; done; done
		# 2026-10-08, after everything the file held before:
		echo "== qemu package expected (METAL_QEMU_PKG)"; echo "qemu_pkg_expected=${METAL_QEMU_PKG:-unset}"
		echo "== tick handler (kallsyms)"; echo "tick_handler=$F_TICK"
		echo "== CONFIG_HZ"; echo "config_hz=$F_HZ"; echo "config_hz_source=$F_HZ_SRC"
		echo "== panic"; echo "cmdline_panic=$F_PANIC_CMDLINE"; echo "kernel_panic=$F_PANIC"
		echo "== read under"; echo "proc_root=$PROC_ROOT"; echo "sys_root=$SYS_ROOT"
		echo "== kvm counters (read before any check)"; echo "kvm_counters=$F_KVM"
	} >> "$1" 2>&1 || true
	return 0
}

# ------------------------------------------------------------- the vsomeip build
# 2026-10-08. build-vsomeip.sh runs its build under a memory cap (MEM_MAX, by default the
# cap its two jobs on the Orin run under), and this phase used to ask it for one job a
# core: on a sixteen-core host that is sixteen compilers under the Orin's cap, and the
# kernel ends them inside it. So both are sized to the host, at the Orin's ratio: the
# cap is half the host's memory in whole GiB, and one job goes with every 2 GiB of it,
# never more than one a core. A host whose memory cannot be read, or that cannot give
# one job that share, is not sized: both stay empty, and the build script's own
# defaults apply.
build_size() {   # sets BUILD_JOBS and BUILD_MEM_MAX, or leaves both empty
	local kb half jobs cores
	BUILD_JOBS=""; BUILD_MEM_MAX=""
	kb="$(sed -n 's/^MemTotal:[[:space:]]*\([0-9][0-9]*\) kB$/\1/p' "$PROC_ROOT/meminfo" 2>/dev/null || true)"
	kb="${kb%%$'\n'*}"
	case "$kb" in ''|*[!0-9]*) return 0 ;; esac
	half=$(( 10#$kb / 2097152 ))
	[ "$half" -ge 2 ] || return 0
	cores="$(nproc 2>/dev/null || true)"
	case "$cores" in ''|*[!0-9]*|0*) cores=1 ;; esac
	jobs=$(( half / 2 ))
	[ "$jobs" -le "$cores" ] || jobs="$cores"
	BUILD_JOBS="$jobs"; BUILD_MEM_MAX="${half}G"
	return 0
}

build_vsomeip() {   # $1 the phase's record directory: apt and the vsomeip build, once per session
	local b="$W/vsomeip/3.4.10/BUILD-INFO" want
	want="$(sha256sum < "$W/repo/orin-native/someip/someip_vprobe.cpp" | cut -d' ' -f1)"
	if [ -r "$b" ] && grep -qx "source sha256 $want" "$b"; then
		say "vsomeip and someip_vprobe already built in this session"
		return 0
	fi
	# Boost 1.74 by its versioned packages (2026-10-08): the four the Orin's provisioning
	# installs (scripts/orin/provision-orin-r39.sh, PKGS_someip). 1.74 is the Boost behind
	# every held SOME/IP record, and on Ubuntu 24.04 the plain -dev names are a later
	# Boost, which these four exclude from the host. build-vsomeip.sh says which Boost it
	# found before it builds. --no-upgrade: a package named here that the host already has
	# stays at the version it has, so a rehearsal on the Orin moves nothing on the board.
	sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq > "$1/apt.log" 2>&1 \
		&& sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade build-essential cmake git \
			libboost1.74-dev libboost-system1.74-dev libboost-thread1.74-dev libboost-filesystem1.74-dev >> "$1/apt.log" 2>&1 \
		|| { tail -20 "$1/apt.log"; die "installing the vsomeip build's packages failed"; }
	roots_announce
	build_size
	if [ -n "$BUILD_JOBS" ]; then
		say "vsomeip build: JOBS=$BUILD_JOBS MEM_MAX=$BUILD_MEM_MAX (the cap is half this host's memory; one job for every 2 GiB of it, at most one a core)"
	else
		say "vsomeip build: this host's memory was not read, or is too small to size the build to: build-vsomeip.sh's own defaults apply"
	fi
	# shellcheck disable=SC2086  # two NAME=value words, or none
	env PREFIX="$W/vsomeip/3.4.10" SRC="$W/vsomeip/src-3.4.10" ${BUILD_JOBS:+JOBS="$BUILD_JOBS" MEM_MAX="$BUILD_MEM_MAX"} \
		bash "$W/repo/orin-native/someip/build-vsomeip.sh" > "$1/vsomeip-build.log" 2>&1 \
		|| { tail -20 "$1/vsomeip-build.log"; die "the vsomeip build failed"; }
}

case "$PHASE" in
setup)
	# The host's facts first, before any check (2026-10-08): whatever stops this phase,
	# the kernel it stopped on is already in the operator's transcript.
	facts_read
	facts_print
	inputs
	[ -e /var/lib/cloud/instance/PROVISIONED ] || [ -n "${REHEARSAL:-}" ] || die "user-data has not finished"
	id -nG | tr ' ' '\n' | grep -qx kvm || [ -w /dev/kvm ] || die "no access to /dev/kvm (log in again after user-data)"
	[ -e "$REC" ] && die "$REC exists -- a leftover; use a fresh W"
	# METAL_QEMU_PKG (2026-10-08): the qemu-system-arm version this session expects, the
	# other host's. user-data installs the day's package while the Orin keeps the build
	# it has, and until now nothing failed when the two parted. Unset, or equal, it
	# stops nothing. A REFUSAL LIKE THE FOUR ABOVE, before the record has a directory:
	# the value is the operator's and can be mistyped, and a setup that stopped on it
	# after $REC was made left a leftover that refused the corrected run, in the one W
	# the driver gives a session. Whether the counters read was read with the facts, and
	# is said again here.
	if [ -n "${METAL_QEMU_PKG:-}" ] && [ "$F_QEMU_PKG" != "$METAL_QEMU_PKG" ]; then
		die "qemu-system-arm is '$F_QEMU_PKG' here and METAL_QEMU_PKG expects '$METAL_QEMU_PKG': the two hosts would not run one QEMU build (KVM counters: $F_KVM). Nothing was made: a mistyped METAL_QEMU_PKG can be corrected and setup run again; if it is right, no harness may run in this session."
	fi
	mkdir -p "$REC/ladder"
	# And into the record the moment it has a directory. The five checks above refuse
	# before one exists (a re-run after them must find none); every check below can
	# stop setup, and none may leave a record without this file.
	F="$REC/host-facts.txt"
	facts_write "$F"
	rm -rf "$W/repo"; mkdir -p "$W/repo"; tar -xf "$W/repo.tar" -C "$W/repo"
	[ -e "$W/img/disk-qemu" ] || gunzip -k "$W/img/disk-qemu.gz"
	echo "$IFS_SHA256  $W/img/$IFS_NAME" | sha256sum -c --quiet || die "$IFS_NAME hash mismatch"
	echo "$DISK_SHA256  $W/img/disk-qemu" | sha256sum -c --quiet || die "disk-qemu hash mismatch"
	echo "$RL_SHA256  $W/remote-ladder.sh" | sha256sum -c --quiet || die "remote-ladder.sh differs from what was uploaded"
	echo "$CAP_SHA256  $W/capture.py" | sha256sum -c --quiet || die "capture.py differs from what was uploaded"
	for x in $IFS_EXTRA; do
		echo "${x#*:}  $W/img/${x%%:*}" | sha256sum -c --quiet || die "${x%%:*} hash mismatch"
	done
	# The uploaded files live in $W/in, outside $W/repo, which this phase deleted above.
	names=""
	for x in $FILES; do
		echo "${x#*:}  $W/in/${x%%:*}" | sha256sum -c --quiet || die "in/${x%%:*} hash mismatch"
		names="${names:+$names }${x%%:*}"
	done
	say "artefacts verified: $IFS_NAME ${IFS_SHA256:0:16} disk ${DISK_SHA256:0:16}${IFS_EXTRA:+ and $IFS_EXTRA}${names:+; files in/: $names}"
	# SDV Phase 6 WP6: in/ is the upload bundle's directory, and run-vss-setup.sh's preflight runs bundle.py verify on it,
	# which refuses a file bundle.json does not list. The OTA drill's files, checked above, move to drill-in/, which the
	# harness phase gives run-ota-drill.sh as DRILL_IN.
	for x in $names; do
		case " $DRILL_FILES " in *" $x "*) mkdir -p "$W/drill-in"; mv -f "$W/in/$x" "$W/drill-in/$x" ;; esac
	done
	[ ! -d "$W/drill-in" ] || say "the OTA drill's files moved to drill-in/: $(ls "$W/drill-in" | tr '\n' ' ')"
	# SDV Phase 8 WP6 9.2: the aw session's inputs, every aw-* file, move to aw-in/ (the aw harnesses' AW_IN) for the same
	# reason, once checked
	for x in $names; do
		case "$x" in aw-*) mkdir -p "$W/aw-in"; mv -f "$W/in/$x" "$W/aw-in/$x" ;; esac
	done
	[ ! -d "$W/aw-in" ] || say "the aw session's files moved to aw-in/: $(ls "$W/aw-in" | tr '\n' ' ')"
	# The record names what actually ran: the instance-side tooling and its inputs (the bundle's own
	# manifest too, when the session carries one).
	mkdir -p "$REC/tooling"
	cp "$W/remote-ladder.sh" "$W/capture.py" "$W/inputs.env" "$REC/tooling/"
	case " $names " in *" bundle.json "*) cp "$W/in/bundle.json" "$REC/tooling/" ;; esac
	echo "commit ${REPO_COMMIT:-unknown}" > "$REC/tooling/repo-commit.txt"
	if ! ip link show br0 >/dev/null 2>&1 || ! ip link show tap-qnx >/dev/null 2>&1; then
		sudo bash "$W/repo/scripts/setup-bridge.sh"
		# The Orin's bridge (setup-bridge-orin.sh) has tap-qnx only; match it.
		sudo ip link del tap-linux 2>/dev/null || true
	fi
	ip -br addr show br0
	# Again, now that the bridge is up: its ports, and br_netfilter, as the run has them.
	facts_write "$F"
	mkdir -p "$HOME/interference"
	cp "$R/latency_probe.py" "$HOME/interference/latency_probe.py"
	bash "$R/build-monitor-native.sh"
	sudo -n true || die "passwordless sudo is required"
	sudo sh -c 'mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug'
	# Every counter m_kvm_snap reads must read as an integer NOW: under kernel
	# lockdown debugfs refuses the 0644 stat files, and the snapshot would store
	# null and fail the doorbell check with a misleading message.
	eval "$(grep '^KVM_COUNTERS=' "$R/lib-measure.sh")"
	for c in $KVM_COUNTERS; do
		v="$(sudo cat "/sys/kernel/debug/kvm/$c" 2>/dev/null || true)"
		case "$v" in ''|*[!0-9]*) die "KVM counter $c unreadable ('$v') -- lockdown: $F_LOCKDOWN" ;; esac
	done
	say "KVM counters readable: $KVM_COUNTERS"
	# METAL_QEMU_PKG once more, as setup's last act and on a fresh read. The refusal at
	# the top compared what dpkg said then; the package timers are stopped only by
	# quiesce, which comes after this phase, and a package that changed while setup ran
	# would be the other QEMU build under a session that had passed.
	if [ -n "${METAL_QEMU_PKG:-}" ]; then
		now="$(qemu_pkg_read)"
		[ "$now" = "$METAL_QEMU_PKG" ] \
			|| die "qemu-system-arm is now '$now' and METAL_QEMU_PKG expects '$METAL_QEMU_PKG': the package changed while setup ran. No harness may run in this session."
	fi
	say "setup done: $(nproc) cores, kernel $F_KERNEL, $(qemu-system-aarch64 --version | head -1)"
	;;
quiesce)
	# (plan Phase 3, WP3h): the platform's record goes into $REC, so setup comes first.
	[ -d "$REC" ] || die "no $REC: run setup first (quiesce records the platform into $REC/quiesce.txt)"
	[ -r "$R/platform-quiesce.sh" ] || die "the repo tarball lacks platform-quiesce.sh"
	# A fresh AMI is busy: cloud-init's tail, snap seeding, apt timers. Settle
	# them for the session, and record the load so a noisy round can be seen.
	cloud-init status --wait >/dev/null 2>&1 || true
	command -v snap >/dev/null && timeout 120 sudo snap wait system seed.loaded 2>/dev/null || true
	sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service 2>/dev/null || true
	for _ in $(seq 1 60); do pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null || break; sleep 5; done
	pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null && die "apt/dpkg/unattended-upgrades still running after 5 min"
	# The platform (owner's S6): docker.socket, docker and containerd stopped through
	# platform-quiesce.sh with ONE fixed state path, as its HARNESS USE rule requires, then k3s when it is
	# installed. Both outputs and exit statuses go to quiesce.txt, appended (a second quiesce keeps the
	# first's record), and every later host-before.txt starts with it. platform-quiesce.sh exits 3 when it
	# refused before it changed anything -- every refusal path, its own marker from an earlier stop
	# included -- so that is recorded and the session goes on; any other failure may have changed the host,
	# and is fatal. Nothing here restores: the instance is discarded (README.md).
	Q="$REC/quiesce.txt"
	K3S_KILLALL="${K3S_KILLALL:-/usr/local/bin/k3s-killall.sh}"
	echo "== quiesce $(date -u +%FT%TZ)" >> "$Q"
	echo "== platform-quiesce.sh stop W/platform-quiesce.state" >> "$Q"
	rc=0; bash "$R/platform-quiesce.sh" stop "$W/platform-quiesce.state" >> "$Q" 2>&1 || rc=$?
	echo "== platform-quiesce.sh stop exit $rc" >> "$Q"
	case "$rc" in
		0) ;;
		3) say "platform-quiesce.sh refused before it changed anything (exit 3): recorded, the session goes on" ;;
		*) cat "$Q"; die "platform-quiesce.sh stop exited $rc: it may have changed the host -- see $Q" ;;
	esac
	if [ -x "$K3S_KILLALL" ]; then
		echo "== sudo -n k3s-killall.sh" >> "$Q"
		rc=0; sudo -n "$K3S_KILLALL" >> "$Q" 2>&1 || rc=$?
		echo "== k3s-killall.sh exit $rc" >> "$Q"
		[ "$rc" = 0 ] || { cat "$Q"; die "k3s-killall.sh exited $rc -- see $Q"; }
	else
		echo "== k3s-killall.sh: not executable here ($K3S_KILLALL)" >> "$Q"
	fi
	cat "$Q"
	say "quiet: loadavg $(cut -d' ' -f1-3 /proc/loadavg)"
	;;
launch)
	marker_refuses "the launch phase"
	inputs
	cd "$R"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" IVSHMEM=/dev/shm/a6-ivshmem \
		IVSHMEM_SERVER=/tmp/a6-ivshmem.sock KICK_SOCK=/tmp/a6-kick.sock \
		LOG="$REC/ladder/guest-console.log" bash launch-qnx-kvm-bridged.sh \
		> "$REC/ladder/guest-launch.log" 2>&1 || { cat "$REC/ladder/guest-launch.log"; die "launch failed"; }
	cat "$REC/ladder/guest-launch.log"
	# "guest up" means the TCP monitor answers; the shm services start after it.
	# Check them here, so a failure is named here and not in the ladder.
	C="$REC/ladder/guest-console.log"
	for _ in $(seq 1 30); do
		grep -aq 'serving shm on ivshmem' "$C" && grep -aq 'serving shm-kick' "$C" && break
		sleep 1
	done
	grep -aq 'serving shm-kick' "$C" && grep -aq 'serving shm on ivshmem' "$C" \
		|| { tail -20 "$C"; die "the guest's shm services did not start"; }
	grep -a 'shm configured:' "$C" | cut -c1-120
	;;
ladder)
	marker_refuses "the ladder phase"
	cd "$R"
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	for w in $LADDER_ENV; do
		[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
	done
	echo "LADDER_ENV=$LADDER_ENV K=${K:-12}" > "$REC/ladder/ladder-env.txt"
	host_before "$REC/ladder/host-before.txt"
	# shellcheck disable=SC2086  # LADDER_ENV is a list of validated NAME=value words
	env -- $LADDER_ENV OUT="$REC/ladder/raw" K="${K:-12}" bash run-ladder.sh > "$REC/ladder/run.log" 2>&1 \
		|| { tail -30 "$REC/ladder/run.log"; die "run-ladder.sh failed"; }
	host_snapshot > "$REC/ladder/host-after.txt"
	tail -5 "$REC/ladder/run.log"
	;;
launch-live)
	marker_refuses "the launch-live phase"
	inputs
	cd "$R"
	mkdir -p "$REC/liveness"
	C="$REC/liveness/guest-console.log"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$REC/liveness/guest-launch.log" 2>&1 || { cat "$REC/liveness/guest-launch.log"; die "launch failed"; }
	cat "$REC/liveness/guest-launch.log"
	# "guest up" means :7100 answers; the image must also run :7102 in deadline mode.
	B='listening on :7102 (frame=64 bytes, conf_min=60%), liveness deadline 2000 ms'
	for _ in $(seq 1 30); do tr -d '\0\r' < "$C" | grep -aqF "$B" && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aqF "$B" \
		|| { tail -20 "$C"; die "no 2000 ms deadline-mode monitor on :7102 -- is the image ifs-live?"; }
	say "deadline-mode monitor up on :7102"
	;;
liveness)
	marker_refuses "the liveness phase"
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/liveness/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-live first"
	E="$W/repo/orin-native/edge-llm"
	[ -r "$E/liveness-demo.sh" ] && [ -r "$E/run-live-cost.sh" ] || die "the repo tarball lacks orin-native/edge-llm"
	host_before "$REC/liveness/host-before.txt"
	CONSOLE="$C" OUT="$REC/liveness/demo" bash "$E/liveness-demo.sh" > "$REC/liveness/demo.log" 2>&1 \
		|| { tail -20 "$REC/liveness/demo.log"; die "liveness-demo.sh failed"; }
	tail -12 "$REC/liveness/demo.log"
	CONSOLE="$C" OUT="$REC/liveness/cost" K="${K:-12}" bash "$E/run-live-cost.sh" > "$REC/liveness/cost.log" 2>&1 \
		|| { tail -30 "$REC/liveness/cost.log"; die "run-live-cost.sh failed"; }
	host_snapshot > "$REC/liveness/host-after.txt"
	tail -8 "$REC/liveness/cost.log"
	;;
launch-stamp)
	marker_refuses "the launch-stamp phase"
	inputs
	cd "$R"
	mkdir -p "$REC/stamp"
	C="$REC/stamp/guest-console.log"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$REC/stamp/guest-launch.log" 2>&1 || { cat "$REC/stamp/guest-launch.log"; die "launch failed"; }
	cat "$REC/stamp/guest-launch.log"
	B='stamping replies on :7103: t_in payload[8..15]'
	for _ in $(seq 1 30); do tr -d '\0\r' < "$C" | grep -aqF "$B" && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aqF "$B" \
		|| { tail -20 "$C"; die "no stamping monitor on :7103 -- is the image ifs-stamp?"; }
	say "plain monitor on :7100 and stamping monitor on :7103 up"
	;;
stamp)
	marker_refuses "the stamp phase"
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/stamp/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-stamp first"
	[ -r "$R/run-stamp.sh" ] || die "the repo tarball lacks run-stamp.sh"
	host_before "$REC/stamp/host-before.txt"
	CONSOLE="$C" OUT="$REC/stamp/raw" MON="$W/stamp-monitor-native" K="${K:-12}" \
		bash "$R/run-stamp.sh" > "$REC/stamp/run.log" 2>&1 \
		|| { tail -30 "$REC/stamp/run.log"; die "run-stamp.sh failed"; }
	host_snapshot > "$REC/stamp/host-after.txt"
	tail -22 "$REC/stamp/run.log"
	;;
metal)
	marker_refuses "the metal phase"
	case "${K:-40}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	inputs
	[ -r "$R/run-metal.sh" ] || die "the repo tarball lacks run-metal.sh"
	[ -e "$REC/metal" ] && die "$REC/metal exists: one metal run per session"
	cd "$R"
	mkdir -p "$REC/metal"
	C="$REC/metal/guest-console.log"
	IFS_BIN="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$REC/metal/guest-launch.log" 2>&1 || { cat "$REC/metal/guest-launch.log"; die "launch failed"; }
	cat "$REC/metal/guest-launch.log"
	B='stamping replies on :7103: t_in payload[8..15]'
	for _ in $(seq 1 30); do tr -d '\0\r' < "$C" | grep -aqF "$B" && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aqF "$B" \
		|| { tail -20 "$C"; die "no stamping monitor on :7103 -- is the image ifs-stamp?"; }
	host_before "$REC/metal/host-before.txt"
	CONSOLE="$C" OUT="$REC/metal/raw" K="${K:-40}" bash "$R/run-metal.sh" > "$REC/metal/run.log" 2>&1 \
		|| { tail -30 "$REC/metal/run.log"; die "run-metal.sh failed"; }
	host_snapshot > "$REC/metal/host-after.txt"
	tail -24 "$REC/metal/run.log"
	;;
someip)
	marker_refuses "the someip phase"
	case "${K:-16}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	inputs
	[ -r "$R/run-someip.sh" ] && [ -r "$R/run-someip0.sh" ] || die "the repo tarball lacks run-someip.sh or run-someip0.sh"
	[ -e "$REC/someip" ] && die "$REC/someip exists: one someip run per session"
	mkdir -p "$REC/someip"
	build_vsomeip "$REC/someip"
	cd "$R"
	host_before "$REC/someip/host-before.txt"
	IMG_S="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/someip/raw" K="${K:-16}" CSTATE=shallow bash "$R/run-someip.sh" > "$REC/someip/run.log" 2>&1 \
		|| { tail -30 "$REC/someip/run.log"; die "run-someip.sh failed"; }
	tail -30 "$REC/someip/run.log"
	IMG_S="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/someip/raw0" K=12 CSTATE=shallow bash "$R/run-someip0.sh" > "$REC/someip/run0.log" 2>&1 \
		|| { tail -30 "$REC/someip/run0.log"; die "run-someip0.sh failed"; }
	host_snapshot > "$REC/someip/host-after.txt"
	tail -30 "$REC/someip/run0.log"
	;;
harness)
	# A leading zero is octal to the harnesses' own arithmetic, and "k": 08 is not JSON in a stamp.
	case "${K:-}" in *[!0-9]*|0*) die "K='${K:-}' is not a round count (digits, no leading zero)" ;; esac
	inputs
	[ -n "$LADDER_GIVEN" ] || die "the harness phase needs LADDER_ENV=\"HARNESS=<name> IMAGE=<image> ...\""
	H=""; I=""; P=""; V=""; imgs=(); declare -A role=() seen=()
	once() { [ -z "${seen[$1]:-}" ] || die "LADDER_ENV names $1 twice"; seen[$1]=1; }
	for w in ${LADDER_ENV:-}; do
		case "$w" in
			HARNESS=?*) once HARNESS; H="${w#HARNESS=}" ;;
			IMAGE=?*) once IMAGE; I="${w#IMAGE=}" ;;
			PLAN=?*) once PLAN; P="${w#PLAN=}" ;;
			VSS_HOST=?*) once VSS_HOST; V="${w#VSS_HOST=}" ;;
			IMG_B=*|IMG_R=*|IMG_UA=*|IMG_UB=*)
				once "${w%%=*}"
				p="$(image_path "${w#*=}")" || die "image '${w#*=}' (${w%%=*}) was not uploaded in this session"
				role[${w%%=*}]="$p"; imgs+=("${w%%=*}=$p") ;;
			HARNESS=|IMAGE=|PLAN=|VSS_HOST=) die "LADDER_ENV word '$w' has no value" ;;
			IMG_*) die "LADDER_ENV word '$w': the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB (IMG_S, IFS_BIN and IMG_P are IMAGE's)" ;;
			*) die "LADDER_ENV word '$w' is not one the harness phase reads: HARNESS=, IMAGE=, PLAN=, VSS_HOST=, IMG_B=, IMG_R=, IMG_UA=, IMG_UB= (K is its own variable)" ;;
		esac
	done
	case "$H" in
		run-someip.sh|run-someip0.sh|run-someip1.sh|run-trace.sh|run-trace2.sh|run-haltpoll.sh|run-bell.sh|run-paths.sh|run-mmio.sh|run-bellrate.sh|run-unmask.sh|run-bellrobust.sh)
			marker_refuses "the A6 harness $H" ;;
		run-vss-setup.sh|run-vss-suite.sh|run-ota-drill.sh|run-aw-setup.sh|run-aw-suite.sh|run-aw-g1.sh) ;;   # plan Phases 3, 6 and 8: detached (below)
		*) die "HARNESS='$H' is not one the harness phase runs" ;;
	esac
	case "$H" in   # a multi-image harness must be given each image, and K as it takes it, before $REC/<name> exists
		run-unmask.sh) takes="IMG_UA IMG_UB"
			[ -z "${K:-}" ] || [ $((K % 4)) = 0 ] || die "run-unmask.sh needs K a multiple of 4 (default 16)" ;;
		run-bellrobust.sh) takes="IMG_B IMG_R IMG_UA"
			[ -z "${K:-}" ] || die "run-bellrobust.sh takes no K: its three repeats are pre-registered" ;;
		run-vss-setup.sh|run-vss-suite.sh|run-ota-drill.sh|run-aw-setup.sh|run-aw-suite.sh|run-aw-g1.sh) takes=""
			[ -z "${K:-}" ] || die "$H takes no K: a vss session is functional, with no rounds" ;;
		*) takes="" ;;
	esac
	why=" (its image is IMAGE=)"; [ -z "$takes" ] || why=" (it takes $takes)"
	[ "$H" != run-ota-drill.sh ] || why=" (it boots no image)"
	for v in "${!role[@]}"; do
		case " $takes " in *" $v "*) ;; *) die "$H takes no $v word$why" ;; esac
	done
	for v in $takes; do
		if [ "$v" = IMG_B ]; then   # IMAGE= sets it too
			[ -n "${role[IMG_B]:-}" ] || [ -n "$I" ] \
				|| die "$H boots more than one image: LADDER_ENV needs IMAGE= or IMG_B=, its first image"
		else
			[ -n "${role[$v]:-}" ] || die "$H boots more than one image: LADDER_ENV needs $v=<an image this session uploaded>"
		fi
	done
	[ "$H" != run-unmask.sh ] || [ "${role[IMG_UA]}" != "${role[IMG_UB]}" ] \
		|| die "IMG_UA and IMG_UB are the same image: run-unmask.sh swaps two"
	if [ "$H" = run-vss-suite.sh ]; then   # PLAN= is the suite's alone
		case "$P" in v1|v2|carla) ;; *) die "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla" ;; esac
	elif [ "$H" = run-aw-suite.sh ]; then   # SDV Phase 8 WP6 9.2: the aw suite's own five plans
		case "$P" in a1|a2|b1|b2|s) ;; *) die "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s" ;; esac
	elif [ "$H" = run-aw-g1.sh ]; then   # SDV Phase 8 WP8: the rehearsal, the one plan a bare-metal host takes
		[ "$P" = rehearsal ] || die "run-aw-g1.sh needs PLAN=rehearsal here (the Orin's arms are its own helper's)"
	elif [ "$H" = run-aw-setup.sh ] && [ -n "$P" ]; then
		die "run-aw-setup.sh takes no PLAN word (only run-aw-suite.sh does)"
	elif [ -n "$P" ]; then
		die "$H takes no PLAN word (only run-vss-suite.sh does)"
	fi
	if [ -n "$V" ]; then   # 2026-10-17: a vss harness's bare-metal AWS host mode (run-vss-setup.sh, THE MODES)
		is_vss "$H" || die "$H takes no VSS_HOST word (only the vss harnesses do)"
		case "$V" in
			a1-metal|c7g-metal) ;;
			*) die "VSS_HOST=$V is not a bare-metal AWS host: a1-metal or c7g-metal (orin is the board's, started by its own helper)" ;;
		esac
	fi
	if is_aw "$H" && [ "$V" != c7g-metal ]; then   # SDV Phase 8 WP6 9.2: the owner's decision of 2026-10-24
		die "$H takes VSS_HOST=c7g-metal only (given: ${V:-none}): the Autoware image runs on the c7g-metal role and the Orin only (the owner, 2026-10-24), and the Orin's days are its own helper's"
	fi
	if is_vss "$H"; then
		if [ "$H" = run-ota-drill.sh ]; then   # SDV Phase 6 WP6: the drill boots no image, and needs the drill
			[ -z "$I" ] || die "run-ota-drill.sh takes no IMAGE word: it boots no image (the drill runs without the guest)"
			[ -r "$W/repo/sdv/drill/drill.py" ] \
				|| die "the repo tarball lacks sdv/drill/drill.py: the drill needs the tarball of a commit that has it"
		else
			[ -n "$I" ] || die "$H needs IMAGE=<the vss image this session uploaded>"
		fi
		[ -r "$W/repo/sdv/stack/step3.py" ] \
			|| die "the repo tarball lacks sdv/stack/step3.py: a vss harness needs the tarball's vss form (scripts/aws/.env.example)"
		[ -r "$R/lib-vss-deadline.sh" ] \
			|| die "the repo tarball lacks lib-vss-deadline.sh: a vss harness needs the tarball's vss form (scripts/aws/.env.example)"
		[ -r "$REC/quiesce.txt" ] || die "no $REC/quiesce.txt: run quiesce first (a vss harness's host-before.txt starts with its record)"
		if is_aw "$H"; then   # SDV Phase 8 WP6 9.2: the project entrypoint and the host check every aw container runs under
			[ -r "$W/repo/sdv/aw/aw-entrypoint.sh" ] && [ -r "$W/repo/sdv/aw/hostcheck.sh" ] \
				|| die "the repo tarball lacks sdv/aw: an aw harness needs the tarball of a commit that has sdv/aw (its entrypoint and host check)"
		fi
	fi
	[ -r "$R/$H" ] || die "the repo tarball lacks $H"
	img="$(image_path "${I:-$IFS_NAME}")" || die "image '${I:-$IFS_NAME}' was not uploaded in this session"
	# (WP3fix): a vss harness boots the session's own image, METAL_IFS. Another uploaded image would pass
	# here and fail the harness's own check later, spending its one run.
	if is_vss "$H" && [ "$H" != run-ota-drill.sh ] && [ "$I" != "$IFS_NAME" ]; then
		die "$H boots the session's METAL_IFS, $IFS_NAME, not $I"
	fi
	stem="${H#run-}"; stem="${stem%.sh}"
	[ -e "$REC/$stem" ] && die "$REC/$stem exists: one $stem run per session"
	if is_vss "$H"; then
		# (WP3fix): what must hold before the marker and the stem directory are written.
		# The inputs setup verified, still. A second upload would leave $W/repo the first tarball's beside the
		# second's inputs.env (drive-metal.sh's upload refuses one too); setup keeps the copy it verified.
		if [ -e "$REC/tooling/inputs.env" ]; then
			cmp -s "$W/inputs.env" "$REC/tooling/inputs.env" \
				|| die "$W/inputs.env differs from $REC/tooling/inputs.env, the copy setup verified: an upload after setup? A changed input needs a new session"
		fi
		# No A6 record beside a vss one: capture.py publishes a vss record by its whitelist, so an A6 harness's
		# directory would be left out and lost with the instance. setup's own ladder/ is one only once it holds a file.
		a6=""
		for ent in "$REC"/*/; do
			[ -d "$ent" ] || continue
			ent="$(basename "$ent")"
			case "$ent" in tooling|vss-*|ota-drill|aw-setup|aw-suite|aw-g1) continue ;; esac
			[ "$ent" != ladder ] || [ -n "$(ls -A "$REC/ladder")" ] || continue
			a6="${a6:+$a6 }$ent"
		done
		[ -z "$a6" ] || die "$REC holds an A6 record ($a6): a vss record is captured by its whitelist, which would leave it out, so no vss harness runs in this session"
		# The suite, and the drill (SDV Phase 6 WP6), only after a setup that finished DONE. Started earlier (a wait-run
		# cut short, say), either would spend the session's one run of it on a preflight failure.
		# SDV Phase 8 WP6 9.2: and each aw harness, the same way (THE AW SESSION).
		if [ "$H" = run-vss-suite.sh ] || [ "$H" = run-ota-drill.sh ] || is_aw "$H"; then
			sl="$(grep '^status=' "$REC/vss-setup/status" 2>/dev/null | tail -1 || true)"
			sd=no; [ ! -e "$REC/vss-setup/done" ] || sd=yes
			[ "$sd" = yes ] && [ "$sl" = status=DONE ] \
				|| die "$H needs a finished run-vss-setup.sh: $REC/vss-setup with done and a last status line status=DONE (done: $sd; last: ${sl:-none}). Wait for setup with wait-run"
			# Its host mode must be setup's (2026-10-17): its own preflight would refuse a setup of another, and spend its
			# one run there.
			sv="$(cat "$W/vss-host" 2>/dev/null || true)"
			[ "${V:-a1-metal}" = "${sv:-a1-metal}" ] \
				|| die "$H needs the VSS_HOST run-vss-setup.sh ran with (${sv:-a1-metal}), not VSS_HOST=${V:-a1-metal} (no word is a1-metal): its preflight would refuse a setup of another host mode and spend its one run"
			# SDV Phase 6 WP6: neither the suite nor the drill while another vss harness still runs (its stem without done,
			# as wait-run reads it): each needs setup DONE only, and two would share this host's Docker and the stack.
			for running in "$REC"/vss-*/ "$REC"/ota-drill/ "$REC"/aw-setup/ "$REC"/aw-suite/ "$REC"/aw-g1/; do
				[ -d "$running" ] && [ ! -e "$running/done" ] || continue
				running="$(basename "$running")"
				die "$H is refused while $running still runs ($REC/$running has no done): two vss harnesses would share this host's Docker and the stack, and each would likely spend its one run. Wait for it with wait-run (a runner that died leaves no done: capture then takes its stem as it stands)"
			done
			# SDV Phase 8 WP6 9.2: the aw suite after a run-aw-setup.sh that ended DONE alone (its own preflight would refuse
			# any other and spend its one run)
			if [ "$H" = run-aw-suite.sh ] || [ "$H" = run-aw-g1.sh ]; then
				al="$(grep '^status=' "$REC/aw-setup/status" 2>/dev/null | tail -1 || true)"
				ad=no; [ ! -e "$REC/aw-setup/done" ] || ad=yes
				[ "$ad" = yes ] && [ "$al" = status=DONE ] \
					|| die "$H needs a finished run-aw-setup.sh: $REC/aw-setup with done and a last status line status=DONE (done: $ad; last: ${al:-none}). Wait for it with wait-run"
			fi
		fi
		# DETACHED (plan Phase 3, WP3e). A vss harness outlives any one ssh session, so it does not run in
		# this one. The marker comes first: from here this host may run Docker, and no A6 measuring phase
		# may follow (the session marker, above). Then the record and host-before.txt, as below, and the
		# harness under setsid nohup with ALL its output in detach.log: left on this ssh session's pipe,
		# `rsh ... | red` on the operator's side would wait for the harness, and a disconnect would end the
		# runner by SIGPIPE (launch-qnx-kvm-bridged.sh starts its ivshmem server the same way).
		echo "$H $(date -u +%FT%TZ)" >> "$W/vss-session"
		if [ "$H" = run-vss-setup.sh ]; then   # setup's word, for the suite's check above; never in $REC
			if [ -n "$V" ]; then echo "$V" > "$W/vss-host"; else rm -f "$W/vss-host"; fi
		fi
		mkdir -p "$REC/$stem"
		cd "$R"
		host_before "$REC/$stem/host-before.txt"
		din=(); [ "$H" != run-ota-drill.sh ] || din=(DRILL_IN="$W/drill-in")   # the drill's files (setup moved them)
		! is_aw "$H" || din=(AW_IN="$W/aw-in")                                  # the aw inputs (setup moved them)
		env W="$W" IMG_S="$img" IMG_B="$img" IFS_BIN="$img" DISK="$W/img/disk-qemu" \
			VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" OUT="$REC/$stem/raw" CSTATE=shallow ${P:+PLAN="$P"} \
			${V:+VSS_HOST="$V"} VSS_IN="$W/in" ${din[@]+"${din[@]}"} VSS_HOME="$W/sdv" STATUS="$REC/$stem/status" \
			setsid nohup bash "$W/remote-ladder.sh" _detached "$stem" "$H" < /dev/null >> "$REC/$stem/detach.log" 2>&1 &
		pid=$!
		# The proof of a start (WP3fix): run.log, which the runner opens only once its own checks passed, just before
		# the harness. Without it nothing runs (a setsid that failed, say) and wait-run would wait to its give-up
		# point: the stem directory goes, so this phase can run again, and the marker stays.
		ws="${VSS_START_WAIT_S:-30}"
		case "$ws" in ''|*[!0-9]*) die "VSS_START_WAIT_S='$ws' is not whole seconds" ;; esac
		for _ in $(seq 1 $((ws * 5))); do
			[ ! -e "$REC/$stem/run.log" ] || break
			sleep 0.2
		done
		if [ ! -e "$REC/$stem/run.log" ]; then
			# The runner's whole process group, so that a child started before its exec cannot outlive it:
			# setsid, from this shell with no job control, does not fork, so $pid leads a session and group of its own.
			# The pid alone when no such group exists (a setsid that failed before it made one).
			kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
			echo "== detach.log"
			cat "$REC/$stem/detach.log" 2>/dev/null || true
			rm -rf "${REC:?}/${stem:?}"
			die "the detached runner of $H did not start: no run.log after $ws seconds (detach.log above). $REC/$stem is removed, so this phase can run again; $W/vss-session stays"
		fi
		say "started $H, detached, into $REC/$stem: wait for it with LADDER_ENV=\"HARNESS=$H\" drive-metal.sh run wait-run"
		exit 0
	fi
	mkdir -p "$REC/$stem"
	case "$H" in run-someip*) build_vsomeip "$REC/$stem" ;; esac
	cd "$R"
	host_before "$REC/$stem/host-before.txt"
	# The IMG_ words come after IMAGE's defaults, so they win (env applies its assignments in order).
	env IMG_S="$img" IMG_B="$img" IFS_BIN="$img" ${imgs[@]+"${imgs[@]}"} DISK="$W/img/disk-qemu" \
		VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/$stem/raw" CSTATE=shallow ${K:+K="$K"} bash "$R/$H" > "$REC/$stem/run.log" 2>&1 \
		|| { tail -30 "$REC/$stem/run.log"; die "$H failed"; }
	host_snapshot > "$REC/$stem/host-after.txt"
	tail -30 "$REC/$stem/run.log"
	;;
wait-run)
	# plan Phase 3 (WP3e): wait, in this one ssh session, until a detached vss harness is done.
	# Short sleeps on this host, never a login per look: repeated logins disturb what runs (they inject tail events into a run).
	[ -z "${K:-}" ] || die "wait-run takes no K"
	[ -n "$LADDER_GIVEN" ] || die "wait-run needs LADDER_ENV=\"HARNESS=<the vss harness to wait for>\""
	H=""
	for w in $LADDER_ENV; do
		case "$w" in
			HARNESS=?*) [ -z "$H" ] || die "LADDER_ENV names HARNESS twice"; H="${w#HARNESS=}" ;;
			*) die "LADDER_ENV word '$w': wait-run reads only HARNESS=" ;;
		esac
	done
	is_vss "$H" || die "HARNESS='$H' is not a detached (vss) harness: only $VSS_HARNESSES run detached"
	stem="${H#run-}"; stem="${stem%.sh}"; D="$REC/$stem"
	[ -d "$D" ] || die "no $D: $H was not started in this session"
	[ -r "$R/lib-vss-deadline.sh" ] || die "the repo tarball lacks lib-vss-deadline.sh"
	# shellcheck source=/dev/null
	. "$R/lib-vss-deadline.sh"
	vss_deadline_load || die "no deadline to give up at (the line above says why)"
	# The give-up point (stop_at + 12 minutes, the deadline - 13 minutes) follows the latest end of a capped
	# unit and its clean stop. Past it, the record is captured as it stands: capture, fetch and terminate
	# need the time left.
	giveup="$(vss_giveup_at)"
	gave_up=""
	while [ ! -e "$D/done" ]; do
		if [ "$(vss_now)" -ge "$giveup" ]; then gave_up=1; break; fi
		sleep "${WAIT_POLL_S:-10}"
	done
	[ ! -e "$D/done" ] || gave_up=""
	last="$(grep '^status=' "$D/status" 2>/dev/null | tail -1 || true)"
	say "$H: ${last:-no status line}"
	if [ -e "$D/done" ]; then echo "done: yes"; else echo "done: no"; fi
	echo "== run.log, last 30 lines"
	tail -30 "$D/run.log" 2>/dev/null || echo "(no run.log)"
	if [ -n "$gave_up" ]; then
		say "gave up at the give-up point (stop_at + 12 minutes, the deadline - 13 minutes) with no done: go straight to capture"
		exit 2
	fi
	case "$last" in status=DONE|status=TIMEOUT|"status=TIMEOUT "*) exit 0 ;; *) exit 1 ;; esac
	;;
_detached)
	# INTERNAL (plan Phase 3, WP3e): the detached runner of a vss harness, which the harness phase starts with
	# setsid nohup, its output in detach.log. drive-metal.sh's PHASES does not list it, so no operator runs it.
	# It opens run.log only once the checks below passed: the harness phase reads run.log as the proof of a start.
	# SIGPIPE and SIGHUP are set to ignored first, so no ssh session's end can stop it; SIGINT and SIGQUIT arrive
	# ignored already (the harness phase started it in the background, with no job control), and nohup ignored
	# SIGHUP before this trap. The harness inherits all four as ignored (bash cannot reset a signal ignored when it
	# starts): its output goes to files, and a pipe that closes inside it reads as EPIPE, not a signal. What that
	# means for its children, and for a unit under its cap, is in SIGNALS (header).
	trap '' PIPE HUP
	set +e   # whatever the harness or the host snapshot does, done is touched
	stem="${2:-}"; H="${3:-}"
	is_vss "$H" || die "_detached runs a vss harness, not '$H'"
	want="${H#run-}"; want="${want%.sh}"
	[ "$stem" = "$want" ] || die "_detached: '$stem' is not $H's record"
	D="$REC/$stem"
	[ -d "$D" ] && [ ! -e "$D/done" ] || die "_detached: $D is missing, or already done"
	say "_detached: $H starts"
	cd "$R" || die "_detached: no $R"
	bash "$R/$H" > "$D/run.log" 2>&1
	rc=$?
	last="$(grep '^status=' "$D/status" 2>/dev/null | tail -1)"
	# A finished run is exit 0 AND a last status line of DONE or TIMEOUT (a stop at the deadline is a
	# finished run: the harness listed what it did not run). Only then is host-after.txt written.
	case "$rc:$last" in
		0:status=DONE|0:status=TIMEOUT|"0:status=TIMEOUT "*)
			# SDV Phase 8 WP6 9.2: an aw harness wrote the host check there after its sweep; the snapshot follows it
			if is_aw "$H"; then host_snapshot >> "$D/host-after.txt"; else host_snapshot > "$D/host-after.txt"; fi
			say "_detached: $H exited 0 with $last; host-after.txt written" ;;
		*)
			echo "status=FAILED rc=$rc" >> "$D/status"
			say "_detached: $H exited $rc with ${last:-no status line}: status=FAILED rc=$rc, no host-after.txt" ;;
	esac
	sync
	touch "$D/done"
	say "_detached: done"
	;;
capture)
	# The session must have FINISHED: host-after.txt is written only after the
	# ladder, the liveness phase or the stamp phase returned 0. Without it the
	# run was interrupted, or refused as incomplete, and a partial record must
	# not be packed and fetched as a whole one.
	#
	# plan Phase 3 (WP3i): a vss stem has finished when it has done and a terminal
	# status line, DONE, TIMEOUT or FAILED. A FAILED one has no host-after.txt and is packed all the same, for its
	# diagnostics: its status line and capture.log say what it is, so it is not read as a whole record. A vss stem
	# with no done may be a harness still running, so the capture refuses while one exists, until wait-run's give-up
	# point (lib-vss-deadline.sh) has passed. Past it, capture.py packs that stem as it stands, named INCOMPLETE in
	# capture.log: capture, fetch and terminate need the time that is left.
	vss_done=""; vss_open=""
	# ota-drill: run-ota-drill.sh's stem (SDV Phase 6 WP6); aw-setup and aw-suite: the aw harnesses' (SDV Phase 8 WP6 9.2)
	for d in "$REC"/vss-*/ "$REC"/ota-drill/ "$REC"/aw-setup/ "$REC"/aw-suite/ "$REC"/aw-g1/; do
		[ -d "$d" ] || continue
		s="$(basename "$d")"
		if [ ! -e "$d/done" ]; then vss_open="${vss_open:+$vss_open }$s"; continue; fi
		last="$(grep '^status=' "$d/status" 2>/dev/null | tail -1 || true)"
		case "$last" in status=DONE|status=TIMEOUT|"status=TIMEOUT "*|status=FAILED|"status=FAILED "*) vss_done=1 ;; esac
	done
	if [ -n "$vss_open" ]; then
		[ -r "$R/lib-vss-deadline.sh" ] \
			|| die "$vss_open has no done, and the repo tarball lacks lib-vss-deadline.sh: the give-up point cannot be read"
		# shellcheck source=/dev/null
		. "$R/lib-vss-deadline.sh"
		vss_deadline_load || die "$vss_open has no done, and there is no deadline to read the give-up point from (the line above says why)"
		left=$(( $(vss_giveup_at) - $(vss_now) ))
		[ "$left" -le 0 ] || die "$vss_open has no done: its harness may still be running. Wait for it with wait-run; the capture packs it as it stands only past wait-run's give-up point, $(( (left + 59) / 60 )) min from now"
		vss_done=1
	fi
	[ -n "$vss_done" ] || [ -e "$REC/ladder/host-after.txt" ] || [ -e "$REC/liveness/host-after.txt" ] || [ -e "$REC/stamp/host-after.txt" ] \
		|| [ -e "$REC/metal/host-after.txt" ] || [ -e "$REC/someip/host-after.txt" ] \
		|| ls "$REC"/*/host-after.txt > /dev/null 2>&1 \
		|| die "no host-after.txt under $REC/ladder, $REC/liveness, $REC/stamp, $REC/metal or $REC/someip, and no vss stem with done and a terminal status line -- the session did not finish; there is no complete record to capture"
	# 2026-09-27: a capture outlived the operator's SSH, and its last line of output then failed
	# and aborted the phase before pub.tgz was packed. So nothing here needs the terminal:
	# SIGPIPE is ignored, capture.py writes to $W/capture.log, and pub.tgz is packed before
	# anything more is printed.
	trap '' PIPE
	RED="$R/redact-aws.sh"
	bash "$RED" selftest >/dev/null || die "redactor selftest failed"
	rm -rf "$W/pub" "$W/pub.sha256" "$W/pub.tgz"; mkdir -p "$W/pub"
	# USER empty: the login is Ubuntu's public default, "ubuntu", and masking it would
	# rewrite the QEMU package version in the stamp and logs, where the word stands inside
	# it (on Ubuntu 24.04 the version has the form 1:<upstream>+ds-0ubuntu<build>; 22.04's
	# was 1:6.2+dfsg-2ubuntu6.31).
	# A trailing "@ubuntu" prompt is still masked through AWS_SSH_USER.
	# CAPTURE_INCOMPLETE: the vss stems with no done, which the gate above lets through only past the give-up point.
	USER= CAPTURE_INCOMPLETE="$vss_open" python3 "$W/capture.py" "$REC" "$W/pub" "$RED" > "$W/capture.log" 2>&1 \
		|| { tail -5 "$W/capture.log" || true; die "capture refused -- see $W/capture.log"; }
	tar -czf "$W/pub.tgz" -C "$W/pub" . 2>> "$W/capture.log" || die "packing pub.tgz failed -- see $W/capture.log"
	grep -E '^(vss-[A-Za-z0-9._-]+|ota-drill|aw-setup|aw-suite|aw-g1): (DONE|TIMEOUT|FAILED|INCOMPLETE|NO STATUS) ' "$W/capture.log" || true
	tail -2 "$W/capture.log" || true
	say "captured $(wc -l < "$W/pub.sha256") files into pub.tgz ($(du -h "$W/pub.tgz" | cut -f1))"
	;;
stop)
	sudo pkill -x qemu-system-aar 2>/dev/null || true
	sleep 1
	pgrep -x qemu-system-aar >/dev/null && die "QEMU still running"
	say "stopped"
	;;
*) die "unknown phase $PHASE" ;;
esac
