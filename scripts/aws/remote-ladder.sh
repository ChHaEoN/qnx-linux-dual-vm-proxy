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
#   run-aw-g1.sh's PLAN=p6a is taken the same way, LADDER_ENV="HARNESS=run-aw-g1.sh IMAGE=ifs-ctl.bin PLAN=p6a
#   VSS_HOST=c7g-metal" and nothing more: any other word is one the harness phase does not read, and is refused.
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
# A G5G SESSION (2026-11-10; README.md, "A g5g session"), on METAL_TYPE=g5g.metal: the A6 phases above for its first
# boot (setup, quiesce, launch-live, liveness, stop), and five phases of its own, each refused under the session marker
# as the A6 phases are, each writing into its own stem under rec/:
#
#   gpu-facts    read only; may run more than once (stems gpu-facts, gpu-facts-2, ...): the CPU's implementer and part,
#                /dev/kvm, the NVIDIA PCI devices with their device ids, bound drivers and vendor id (from /sys, no
#                lspci), the nvidia and nvidia_uvm modules, the four device nodes, and, when the driver's tool is there,
#                each GPU's index, name, compute capability, memory and driver version -- named fields only, never a
#                UUID or a serial number; the tool is given 60 s, and one that does not answer is a recorded word. It
#                prints each GPU's name, then, as its last line, the summary the session reads, also the stem's
#                summary.txt. With no rec/ (setup did not finish) it prints that line and writes nothing.
#   gpu-install  LADDER_ENV="MODE=plan", then "MODE=apply" (THE INSTALL, below)
#   llama-build  build-llama.sh for CUDA architecture 75, detached, sized by build_size (or JOBS= and MEM_MAX= as
#                words); LADDER_ENV="MODE=wait" blocks in one ssh session until it ended, and ends at once, by a word,
#                when no build is running and none ended whole; "MODE=stop" ends a running one
#   launch-svc   LADDER_ENV="IMAGE=<an uploaded image>": boots it plainly, console into the vlm stem, and checks the
#                service's port by an exchange (a TCP connection accepted), not by its banner
#   vlm          vlm-demo.sh, unchanged, on the first GPU only; its exit status is recorded (demo-exit.txt) and is not
#                this phase's failure; it prints the host's two words after the demo and the stamp's board and
#                visible-devices words
#
#   HOST-AFTER, AND THE TWO WORDS. Every g5g phase ends by writing its stem's host-after.txt, on its failure branches
#   too (an EXIT trap); launch-svc, which has no stem of its own, writes launch-svc-host-after.txt into the vlm stem and
#   never a file named host-after.txt there. Each carries kernel_oops=yes|no|unread, whether the kernel's log of this
#   boot holds an Oops or a BUG: line (the word only): root's read of the journal (sudo -n journalctl -k -b), of dmesg
#   only when the journal cannot be read, unread only when both fail. And boot=same|new: gpu-facts' first run writes a
#   marker, $W/g5g-boot (outside rec, never captured; never under /run, where a login's directory goes with the login),
#   holding the sha256 of the kernel's boot id and never the id. same: the marker equals the running boot's hash. new:
#   it differs, or it is gone beside a gpu-facts stem. Only gpu-facts' first run writes it (one that cannot read the
#   boot id writes none, and says so: the next phase reads boot=new); on boot=new gpu-facts also reads the previous
#   boot's word (kernel_oops_prev, journalctl -k -b -1) and counts the pstore entries, and every other g5g phase
#   refuses: setup's bridge and the guest are gone. No g5g phase reboots the host.
#
#   THE INSTALL. Three files decide it: the list file (orin-native/edge-llm/g5g-packages.list, in the tarball: the
#   top-level names), the approved-names file (in/g5g-approved.txt, uploaded and verified by setup: every package of the
#   closure as `pkg NAME=VERSION ubuntu|nvidia SIZE SHA256`, `key PACKAGE FILE.deb SHA256` with a `keyfile PATH SHA256`
#   line for each file that package installs, `pins g5g-nvidia-pins SHA256`, `llama COMMIT CAP`, `index-cap BYTES`,
#   `total all BYTES`), and the pin file g5g_pins.py writes from it. MODE=plan first reads the approved file whole and
#   changes nothing unless every line it needs is there once and of its form, every list name has its pkg line, the key
#   package in in/ has the sha256 the file names and the generated pin file has the sha256 the file names. Then it
#   makes three changes and says each: it installs the key package from in/ (its installed files compared after),
#   writes the pin file into apt's preferences directory, and refreshes the indexes (the bytes apt says it fetched
#   held to the index cap). It prints the enabled components and adds none, reads every pinned name's candidate back
#   from apt, then resolves the list file's names for this kernel (apt-get -s, --no-install-recommends, each as
#   name=version; each .deb's hash is asked of apt as its SHA256, since apt prints one hash a file, by itself the
#   strongest its index carries) and compares the set with the approved file: every line of the set a line of the
#   file, from the source it names, with the size and sha256 it names, the bytes at most the total; a kernel
#   package, a removal, an upgrade of an installed
#   package or a module package for another kernel is refused by name. Its last line is `plan: approved set SHA256` or
#   `plan: refused`. MODE=apply refuses without an approved plan, the plan's pin file and the same set; unloads nouveau
#   first when it is there (modprobe -r), installs exactly the set, unloads nouveau once more if the install brought it
#   back (rmmod: the driver's own modprobe file then aliases the name away), loads nvidia and nvidia_uvm, and checks
#   the four nodes, saying how many stand after each installed tool that can make them (the driver's tool is given 60 s
#   there too); it makes no node itself. set.txt holds versions as apt gives them; set-v.txt holds them with "_"
#   for ".", which the redactor's IPv4 rule leaves whole; equality is shown by hashes.
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
PHASE="${1:?phase: setup|quiesce|launch|ladder|launch-live|liveness|launch-stamp|stamp|metal|someip|harness|wait-run|capture|stop|gpu-facts|gpu-install|llama-build|launch-svc|vlm}"
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

# ------------------------------------------------------------------ a g5g session (2026-11-10)
# The header's A G5G SESSION says what the phases do; these are their parts. G5G_ROOT (tests only, announced) stands
# before /dev and /etc/apt, and before the paths dpkg lists for the key package, as PROC_ROOT and SYS_ROOT stand for
# /proc and /sys. GUEST and SVC_PORT are vlm-demo.sh's own words, with its defaults.
G5G_ROOT="${G5G_ROOT:-}"
G5G_E="$W/repo/orin-native/edge-llm"
G5G_LIST="$G5G_E/g5g-packages.list"
G5G_PINGEN="$G5G_E/g5g_pins.py"
G5G_APPROVED="$W/in/g5g-approved.txt"
# One fixed name with no extension: apt passes over a preferences file of any other form (apt_preferences(5)).
G5G_PINS="$G5G_ROOT/etc/apt/preferences.d/g5g-nvidia-pins"
G5G_MARKER="$W/g5g-boot"
G5G_NODES="nvidiactl nvidia0 nvidia1 nvidia-uvm"
GUEST="${GUEST:-192.168.100.10}"
SVC_PORT="${SVC_PORT:-7102}"
# How long the driver's tool may take (gpu-facts, apply): a wedged module is those steps' own case, and an ssh call
# that never returns bills the session. G5G_SMI_WAIT_S is a test's word; any value that is no such number is 60.
G5G_SMI_WAIT_S="${G5G_SMI_WAIT_S:-60}"
[[ "$G5G_SMI_WAIT_S" =~ ^[1-9][0-9]{0,2}$ ]] || G5G_SMI_WAIT_S=60
G5G_BOOT=same
G5G_PREV=""
G5G_LOG=plan.txt
g5g_announce() {
	[ -z "$G5G_ROOT" ] || say "WARNING: G5G_ROOT overridden to $G5G_ROOT -- test use only"
	roots_announce
}

# kernel_oops: yes, no or unread ($1 = prev: of the boot before this one, from the journal alone).
kernel_oops_word() {
	local t
	if [ "${1:-}" = prev ]; then
		t="$(sudo -n journalctl -k -b -1 --no-pager 2>/dev/null)" || { echo unread; return 0; }
	elif t="$(sudo -n journalctl -k -b --no-pager 2>/dev/null)"; then :
	elif t="$(sudo -n dmesg 2>/dev/null)"; then :
	else echo unread; return 0; fi
	if grep -Eq 'Oops|BUG:' <<< "$t"; then echo yes; else echo no; fi
}
g5g_boot_hash() {   # the sha256 of the kernel's boot id, never the id; "unread" when it cannot be read
	local f="$PROC_ROOT/sys/kernel/random/boot_id" h
	[ -r "$f" ] || { printf unread; return 0; }
	h="$(sha256sum < "$f" | cut -c1-64)"
	printf '%s' "${h:-unread}"
}
g5g_boot() {   # same | new | none (no marker and no gpu-facts stem: gpu-facts has not run)
	local h
	h="$(g5g_boot_hash)"
	if [ -r "$G5G_MARKER" ]; then
		if [ "$h" != unread ] && [ "$(cat "$G5G_MARKER")" = "$h" ]; then echo same; else echo new; fi
	elif [ -d "$REC/gpu-facts" ]; then echo new
	else echo none; fi
}
g5g_host_after() {   # $1 the file: the host now, and the two words
	{
		host_snapshot
		echo "kernel_oops=$(kernel_oops_word)"
		echo "boot=$G5G_BOOT"
		[ -z "$G5G_PREV" ] || echo "kernel_oops_prev=$G5G_PREV"
	} > "$1" 2>/dev/null || true
}
g5g_begin() {   # $1 the phase: what every g5g phase but gpu-facts refuses on first
	marker_refuses "the $1 phase"
	[ -d "$REC" ] || die "no $REC: run setup first"
	G5G_BOOT="$(g5g_boot)"
	case "$G5G_BOOT" in
		none) die "no $G5G_MARKER and no gpu-facts stem: run gpu-facts first (its first run writes the boot marker)" ;;
		new) die "boot=new: this host has booted since gpu-facts first ran, so setup's bridge and the guest are gone and the $1 phase does not run. Run gpu-facts, then stop and capture." ;;
	esac
}
g5g_open() {   # $1 the stem, $2 its host-after file's name: makes the stem, and arms the file for every way out
	S="$REC/$1"
	mkdir -p "$S"
	G5G_AFTER="$S/${2:-host-after.txt}"
	trap 'g5g_host_after "$G5G_AFTER"' EXIT
}
g5g_words() {   # $1 the names this phase takes: sets G5G_W_<NAME> for each given; fails on any other word
	local w n
	[ -n "$LADDER_GIVEN" ] || return 0
	for w in $LADDER_ENV; do
		[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
		n="${w%%=*}"
		case " $1 " in *" $n "*) ;; *) return 1 ;; esac
		printf -v "G5G_W_$n" '%s' "${w#*=}"
	done
}
g5g_once() {   # after g5g_words: fails when LADDER_ENV gives one name twice, equal or not (gpu-install's, llama-build's and launch-svc's words)
	local w seen=" "
	[ -n "$LADDER_GIVEN" ] || return 0
	for w in $LADDER_ENV; do
		case "$seen" in *" ${w%%=*} "*) return 1 ;; esac
		seen="$seen${w%%=*} "
	done
}
g5g_mod() { grep -q "^$1 " "$PROC_ROOT/modules" 2>/dev/null; }
g5g_pci() {   # one line for each PCI device of NVIDIA's vendor id: its device id, the driver bound to it, its vendor id
	local d v
	for d in "$SYS_ROOT"/bus/pci/devices/*; do
		v="$(cat "$d/vendor" 2>/dev/null || true)"
		[ "$v" = 0x10de ] || continue
		echo "$(cat "$d/device" 2>/dev/null || echo unread) $(basename "$(readlink "$d/driver" 2>/dev/null || echo none)") $v"
	done
}
g5g_bound() {   # the drivers bound to those devices, each once: "none", "nouveau", "none nvidia", ...
	local b
	b="$(g5g_pci | awk '{ print $2 }' | LC_ALL=C sort -u | tr '\n' ' ')"
	printf '%s' "${b% }"
}
g5g_nodes() {   # one line a device node: usable, not usable or missing; G5G_NODES_OK counts the usable
	local n f
	G5G_NODES_OK=0
	for n in $G5G_NODES; do
		f="$G5G_ROOT/dev/$n"
		if [ ! -e "$f" ]; then echo "$n missing"
		elif [ -r "$f" ] && [ -w "$f" ]; then echo "$n usable"; G5G_NODES_OK=$((G5G_NODES_OK + 1))
		else echo "$n not usable"; fi
	done
}
g5g_fact() {   # $1 a key of the newest gpu-facts summary of this session: its value, or nothing
	local n=1 d="$REC/gpu-facts" last=""
	while [ -d "$d" ]; do last="$d"; n=$((n + 1)); d="$REC/gpu-facts-$n"; done
	[ -n "$last" ] && [ -r "$last/summary.txt" ] || return 0
	tr ' ' '\n' < "$last/summary.txt" | sed -n "s/^$1=//p"
}

# --- gpu-install (THE INSTALL, in the header)
pl() { printf '%s\n' "$*"; printf '%s\n' "$*" >> "$S/$G5G_LOG"; }
g5g_refuse() { pl "refused: $*"; G5G_REFUSED=$((G5G_REFUSED + 1)); }
g5g_plan_end() { pl "plan: refused"; exit 1; }
g5g_sha() { sha256sum < "$1" | cut -c1-64; }
g5g_fetched() {   # $1 apt-get update's output: the bytes it says it fetched (0 when it fetched nothing); fails on a unit it does not know
	awk '/^Fetched / {
			v = $2; gsub(/,/, "", v); u = $3; seen = 1
			m = (u == "B") ? 1 : (u == "kB") ? 1000 : (u == "MB") ? 1000000 : (u == "GB") ? 1000000000 : -1
			if (m < 0 || v !~ /^[0-9]+([.][0-9]+)?$/) bad = 1; else n = sprintf("%.0f", v * m)
		}
		END { if (bad) exit 1; print (seen ? n : 0) }' "$1"
}
g5g_components() {   # the components of Ubuntu's archive this host's sources enable, in the archive's order
	local f c got="" out=""
	for f in "$G5G_ROOT/etc/apt/sources.list" "$G5G_ROOT"/etc/apt/sources.list.d/*.list "$G5G_ROOT"/etc/apt/sources.list.d/*.sources; do
		[ -r "$f" ] || continue
		case "$f" in
			# a stanza is read whole before its URIs are judged: its fields stand in any order
			*.sources) got="$got $(awk 'function flush() { if (u) printf "%s", c; u = 0; c = "" }
				/^[ \t]*$/ { flush(); next }
				/^URIs:/ { if ($0 ~ /ubuntu[.]com/) u = 1 }
				/^Components:/ { for (i = 2; i <= NF; i++) c = c $i "\n" }
				END { flush() }' "$f" | tr '\n' ' ')" ;;
			*) got="$got $(awk '$1 == "deb" { i = 2; if ($i ~ /^\[/) { while (i <= NF && $i !~ /\]$/) i++; i++ } if ($i ~ /ubuntu[.]com/) for (j = i + 2; j <= NF; j++) print $j }' "$f" | tr '\n' ' ')" ;;
		esac
	done
	for c in main restricted universe multiverse; do
		case " $got " in *" $c "*) out="${out:+$out }$c" ;; esac
	done
	printf '%s' "${out:-none read}"
}
# A fresh resolve into directory $1: set.txt (sorted name=version), set-v.txt, debs.txt (name, source, the .deb's size
# and SHA256 as apt's index gives them), with g5g_refuse for every difference from the approved file; G5G_BYTES is the
# bytes to fetch. Nothing is installed: apt-get -s simulates, and --print-uris prints what it would fetch. apt prints
# ONE hash a file there, the strongest its index carries unless Acquire::ForceHash names another, and Ubuntu's and
# NVIDIA's indexes carry SHA512 beside SHA256: so the SHA256 the approved file holds is asked for by name, and a line
# that still carries another hash is refused by that hash's type, not as a sha256 that differs.
g5g_resolve() {
	local d="$1" asks=() list name ver line
	G5G_BYTES=0
	while read -r list name; do
		name="${name//@KREL@/$KREL}"
		ver="$(awk -v n="$name" '$1 == "pkg" { split($2, a, "="); if (a[1] == n) print a[2] }' "$G5G_APPROVED")"
		if [ -z "$ver" ]; then g5g_refuse "not in the approved file: $name"; continue; fi
		asks+=("$name=${ver%%$'\n'*}")
	done < <(grep -v '^#' "$G5G_LIST" | grep . || true)
	[ "$G5G_REFUSED" = 0 ] && [ "${#asks[@]}" -gt 0 ] || { [ "$G5G_REFUSED" != 0 ] || g5g_refuse "the list file names nothing"; return 0; }
	if ! sudo -n apt-get -s install --no-install-recommends "${asks[@]}" > "$d/apt-sim.log" 2>&1 \
		|| ! sudo -n apt-get -o Acquire::ForceHash=SHA256 --print-uris -qq install --no-install-recommends "${asks[@]}" > "$d/apt-uris.log" 2>&1; then
		g5g_refuse "apt could not resolve the list file's names at the approved versions (apt-sim.log, apt-uris.log)"
		return 0
	fi
	: > "$d/set.raw"; : > "$d/debs.raw"
	while IFS= read -r line; do
		case "$line" in
			"S "*) echo "${line#S }" >> "$d/set.raw" ;;
			"D "*) echo "${line#D }" >> "$d/debs.raw" ;;
			"R "*) g5g_refuse "${line#R }" ;;
			"T "*) G5G_BYTES="${line#T }" ;;
		esac
	done < <(awk -v A="$G5G_APPROVED" -v U="$d/apt-uris.log" -v K="$KREL" '
		FILENAME == A { if ($1 == "pkg") { split($2, a, "="); aver[a[1]] = a[2]; asrc[a[1]] = $3; asize[a[1]] = $4; asha[a[1]] = $5 } next }
		FILENAME == U {
			u = $1; gsub("\047", "", u); n = $2; sub(/_.*/, "", n)
			h = u; sub(/^[a-z]+:\/\//, "", h); sub(/\/.*/, "", h)
			uhost[n] = h; usize[n] = $3; usha[n] = ($4 ~ /^SHA256:/) ? substr($4, 8) : "none"
			t = $4; sub(/:.*/, "", t); utype[n] = (t == "") ? "no hash" : t
			next
		}
		$1 == "Remv" { print "R removal: " $2; next }
		$1 == "Inst" {
			n = $2; i = 3; up = 0
			if ($i ~ /^\[/) { up = 1; i++ }
			v = $i; sub(/^\(/, "", v)
			names[++cnt] = n; ver[n] = v; origin[n] = $(i + 1); upg[n] = up
		}
		END {
			for (k = 1; k <= cnt; k++) {
				n = names[k]
				src = (uhost[n] == "developer.download.nvidia.com") ? "nvidia" : (origin[n] ~ /^Ubuntu:/) ? "ubuntu" : "other"
				print "S " n "=" ver[n]
				print "D " n " " src " " (usize[n] == "" ? "unread" : usize[n]) " " (usha[n] == "" ? "unread" : usha[n])
				total += usize[n]
				if (n ~ /^linux-(modules|objects|signatures)-nvidia-/) {
					if (length(n) <= length(K) || substr(n, length(n) - length(K)) != "-" K) { print "R module package for another kernel: " n; continue }
				} else if (n ~ /^linux-(image|headers|modules|modules-extra|tools|cloud-tools|buildinfo)(-|$)/ \
					|| n ~ /^linux-(aws|generic|virtual|kvm|lowlatency|oem|gcp|azure|oracle|ibm|raspi|nvidia)(-|$)/) {
					print "R kernel package: " n; continue
				}
				if (upg[n]) { print "R upgrade of an installed package: " n; continue }
				if (!(n in aver)) { print "R not in the approved file: " n; continue }
				if (aver[n] != ver[n]) { print "R version differs from the approved file: " n; continue }
				if (asrc[n] != src) { print "R source differs from the approved file: " n; continue }
				if ((n in uhost) && usha[n] == "none") { print "R no SHA256 from apt (it printed " utype[n] "): " n; continue }
				if (asize[n] != usize[n] || asha[n] != usha[n]) print "R size or sha256 differs from the approved file: " n
			}
			printf "T %.0f\n", total
		}' "$G5G_APPROVED" "$d/apt-uris.log" "$d/apt-sim.log")
	LC_ALL=C sort "$d/set.raw" > "$d/set.txt"
	LC_ALL=C sort "$d/debs.raw" > "$d/debs.txt"
	{
		echo '# set.txt with every "." of the version field written as "_": the redactor leaves these whole (its IPv4 rule rewrites some dotted versions)'
		awk -F= '{ v = $0; sub(/^[^=]*=/, "", v); gsub(/[.]/, "_", v); print $1 "=" v }' "$d/set.txt"
	} > "$d/set-v.txt"
	rm -f "$d/set.raw" "$d/debs.raw"
}
g5g_lines() {   # how many lines of the approved file begin with the word $1 (and have $2 as their second, when given)
	awk -v k="$1" -v k2="${2:-}" '$1 == k && (k2 == "" || $2 == k2) { n++ } END { print n + 0 }' "$G5G_APPROVED"
}
g5g_plan() {
	local key_pkg="" key_deb="" key_sha="" got p pins_name="" pins_want="" pins_got="" cap fetched n=0 ok=0 name ver total sha list
	G5G_LOG=plan.txt; G5G_REFUSED=0
	rm -f "$S/plan-approved.txt" "$S/set.txt" "$S/set-v.txt" "$S/debs.txt" "$S/pins.tmp"
	: > "$S/plan.txt"
	g5g_announce
	pl "list file $(g5g_sha "$G5G_LIST")"
	pl "approved file $(g5g_sha "$G5G_APPROVED")"
	# Before anything is changed: every line of the approved file the plan reads, there once and of its form; a pkg
	# line for every name of the list file; the key package's sha256; the generated pin file's sha256. Each failure is
	# a refusal by its word, all of them said, and the plan ends there with this host as it was.
	read -r key_pkg key_deb key_sha <<< "$(awk '$1 == "key" { print $2, $3, $4 }' "$G5G_APPROVED")" || true
	[ "$(g5g_lines key)" = 1 ] \
		&& [[ "$key_pkg" =~ ^[a-z0-9][a-z0-9+.-]+$ ]] && [[ "$key_deb" =~ ^[A-Za-z0-9._-]+[.]deb$ ]] && [[ "$key_sha" =~ ^[0-9a-f]{64}$ ]] \
		|| { g5g_refuse "the approved file has no one line \`key PACKAGE FILE.deb SHA256\`"; key_deb=""; }
	read -r pins_name pins_want <<< "$(awk '$1 == "pins" { print $2, $3 }' "$G5G_APPROVED")" || true
	[ "$(g5g_lines pins)" = 1 ] && [ "$pins_name" = "${G5G_PINS##*/}" ] && [[ "$pins_want" =~ ^[0-9a-f]{64}$ ]] \
		|| { g5g_refuse "the approved file has no one line \`pins ${G5G_PINS##*/} SHA256\`"; pins_want=""; }
	cap="$(awk '$1 == "index-cap" { print $2 }' "$G5G_APPROVED")"
	[ "$(g5g_lines index-cap)" = 1 ] && [[ "$cap" =~ ^[1-9][0-9]{0,11}$ ]] \
		|| g5g_refuse "the approved file has no one line \`index-cap BYTES\`"
	total="$(awk '$1 == "total" && $2 == "all" { print $3 }' "$G5G_APPROVED")"
	[ "$(g5g_lines total all)" = 1 ] && [[ "$total" =~ ^[0-9]{1,15}$ ]] \
		|| g5g_refuse "the approved file has no one line \`total all BYTES\`"
	while IFS= read -r p; do
		[ -z "$p" ] || g5g_refuse "$p"
	done < <(awk '$1 == "pkg" {
			split($2, a, "=")
			if (NF != 5 || a[1] == "" || a[2] == "" || $3 !~ /^(ubuntu|nvidia)$/ || $4 !~ /^[0-9]+$/ || length($5) != 64 || $5 ~ /[^0-9a-f]/) print "a pkg line of another form in the approved file: " a[1]
			if (seen[a[1]]++ == 1) print "named twice in the approved file: " a[1]
		}' "$G5G_APPROVED")
	while read -r list name; do
		n=$((n + 1))
		name="${name//@KREL@/$KREL}"
		[ "$(awk -v n="$name" '$1 == "pkg" { split($2, a, "="); if (a[1] == n) c++ } END { print c + 0 }' "$G5G_APPROVED")" != 0 ] \
			|| g5g_refuse "not in the approved file: $name"
	done < <(grep -v '^#' "$G5G_LIST" | grep . || true)
	[ "$n" != 0 ] || g5g_refuse "the list file names nothing"
	n=0
	if [ -n "$key_deb" ]; then
		got=""
		[ ! -r "$W/in/$key_deb" ] || got="$(g5g_sha "$W/in/$key_deb")"
		[ "$got" = "$key_sha" ] || g5g_refuse "key package sha256 differs"
	fi
	if [ -n "$pins_want" ]; then
		if python3 "$G5G_PINGEN" "$G5G_APPROVED" > "$S/pins.tmp" 2>> "$S/plan.txt"; then
			pins_got="$(g5g_sha "$S/pins.tmp")"
			[ "$pins_got" = "$pins_want" ] || g5g_refuse "pin file sha256 differs"
		else
			g5g_refuse "the pin generator refused the approved file"
		fi
	fi
	[ "$G5G_REFUSED" = 0 ] || { rm -f "$S/pins.tmp"; g5g_plan_end; }
	# Change 1: the key package, from in/ (its sha256 was checked above, before dpkg sees it); the files it installed after.
	sudo -n dpkg -i "$W/in/$key_deb" > "$S/key-install.log" 2>&1 || { rm -f "$S/pins.tmp"; tail -5 "$S/key-install.log"; die "installing the key package failed (key-install.log)"; }
	pl "change 1 of 3: the key package $key_pkg installed from in/ (uploaded, never fetched by this host)"
	{ dpkg -L "$key_pkg" 2>/dev/null || true; } | while IFS= read -r p; do
		if [ -f "$G5G_ROOT$p" ] && [ ! -L "$G5G_ROOT$p" ]; then echo "$p $(g5g_sha "$G5G_ROOT$p")"; fi
	done | LC_ALL=C sort > "$S/key-files.txt"
	if [ ! -s "$S/key-files.txt" ]; then
		g5g_refuse "key package files unread (dpkg -L $key_pkg named no file)"
	else
		while IFS= read -r p; do
			[ -z "$p" ] || g5g_refuse "key package files differ: $p"
		done < <(awk '$1 == "keyfile" { print $2, $3 }' "$G5G_APPROVED" | LC_ALL=C sort | LC_ALL=C comm -3 - "$S/key-files.txt" | tr -d '\t' | cut -d' ' -f1 | LC_ALL=C sort -u)
	fi
	[ "$G5G_REFUSED" = 0 ] || { rm -f "$S/pins.tmp"; g5g_plan_end; }
	pl "key package verified"
	# Change 2: the pin file, the generator's bytes from the approved file, under the one name apt reads.
	sudo -n install -m 0644 "$S/pins.tmp" "$G5G_PINS" || { rm -f "$S/pins.tmp"; die "the pin file could not be written"; }
	rm -f "$S/pins.tmp"
	pl "change 2 of 3: the pin file, into apt's preferences directory"
	pl "pins written $pins_got"
	# Change 3: the indexes, refreshed; the bytes apt says it fetched, against the index cap.
	sudo -n apt-get update > "$S/apt-update.log" 2>&1 || { tail -5 "$S/apt-update.log"; die "apt-get update failed (apt-update.log)"; }
	fetched="$(g5g_fetched "$S/apt-update.log")" || die "apt's Fetched line could not be read (apt-update.log)"
	pl "change 3 of 3: indexes refreshed: $fetched bytes fetched (index cap $cap)"
	[ "$fetched" -le "$cap" ] || { g5g_refuse "index bytes $fetched over the index cap $cap"; g5g_plan_end; }
	pl "enabled components: $(g5g_components) (none added: the key package's source is the only new one)"
	# The pins, read back from apt before anything is resolved.
	while read -r name ver; do
		n=$((n + 1))
		got="$(apt-cache policy "$name" 2>/dev/null | sed -n 's/^  Candidate: //p')" || got=""
		if [ "${got%%$'\n'*}" = "$ver" ]; then ok=$((ok + 1)); else g5g_refuse "pin not in force: $name"; fi
	done < <(awk '$1 == "pkg" && $3 == "nvidia" { split($2, a, "="); print a[1], a[2] }' "$G5G_APPROVED")
	pl "pins in force: $ok of $n"
	[ "$G5G_REFUSED" = 0 ] || g5g_plan_end
	g5g_resolve "$S"
	if [ -r "$S/set.txt" ]; then
		pl "set $(g5g_sha "$S/set.txt")"
		[ "$G5G_BYTES" -le "$total" ] || g5g_refuse "bytes to fetch $G5G_BYTES over the approved total $total"
		pl "bytes to fetch: $G5G_BYTES (approved total $total)"
		[ -s "$S/set.txt" ] || pl "the set is empty: apt would install nothing for the list file's names (each is already here at its approved version)"
	fi
	[ "$G5G_REFUSED" = 0 ] || g5g_plan_end
	sha="$(g5g_sha "$S/set.txt")"
	printf 'set %s\npins %s\n' "$sha" "$pins_got" > "$S/plan-approved.txt"
	pl "plan: approved set $sha"
}
g5g_nouveau_there() { g5g_mod nouveau || case " $(g5g_bound) " in *" nouveau "*) true ;; *) false ;; esac; }
g5g_apply() {
	local want_set want_pins d names=() inst nok mp="" smi
	G5G_LOG=apply.txt; G5G_REFUSED=0
	: > "$S/apply.txt"
	g5g_announce
	[ -r "$S/plan-approved.txt" ] || die "no approved plan in this session: run gpu-install with MODE=plan first (nothing installed)"
	want_set="$(sed -n 's/^set //p' "$S/plan-approved.txt")"; want_pins="$(sed -n 's/^pins //p' "$S/plan-approved.txt")"
	[ -r "$G5G_PINS" ] && [ "$(g5g_sha "$G5G_PINS")" = "$want_pins" ] \
		|| die "the pin file is not the plan's (gone, or changed since): nothing installed"
	d="$S/apply-resolve"; rm -rf "$d"; mkdir "$d"
	g5g_resolve "$d"
	[ "$G5G_REFUSED" = 0 ] && [ -r "$d/set.txt" ] && [ "$(g5g_sha "$d/set.txt")" = "$want_set" ] \
		|| die "a fresh resolve's set is not the plan's: nothing installed (run the plan again)"
	rm -rf "$d"
	# Nouveau, before any package: unloaded, read back, or nothing is installed.
	if g5g_nouveau_there || case ",$(g5g_fact bound)," in *,nouveau,*) true ;; *) false ;; esac; then
		sudo -n modprobe -r nouveau >> "$S/modules.log" 2>&1 || true
		if ! g5g_mod nouveau && case "$(g5g_bound)" in ''|none) true ;; *) false ;; esac; then
			pl "nouveau unloaded"
		else
			pl "nouveau held: nothing installed"; exit 1
		fi
	fi
	mapfile -t names < "$S/set.txt"
	if [ "${#names[@]}" -gt 0 ]; then
		sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends "${names[@]}" > "$S/apt.log" 2>&1 \
			|| { tail -20 "$S/apt.log"; die "the install failed (apt.log)"; }
	fi
	# A dpkg-query that fails gives the hash of what it printed, which is not the plan's: said below, not a silent end.
	# shellcheck disable=SC2016,SC2046  # dpkg-query's own format fields; one word a package name
	# With no name dpkg-query would list every package of the host: an empty set is the hash of nothing.
	if [ "${#names[@]}" -gt 0 ]; then
		inst="$({ dpkg-query -W -f='${Package}=${Version}\n' $(cut -d= -f1 "$S/set.txt") 2>/dev/null || true; } | LC_ALL=C sort | sha256sum | cut -c1-64)"
	else
		inst="$(: | sha256sum | cut -c1-64)"
	fi
	[ "$inst" = "$want_set" ] || die "installed set $inst is not the plan's $want_set: no module is loaded"
	# Nouveau once more: the install's scripts or a udev trigger may have loaded it again. By rmmod: the driver's
	# modprobe file now says `alias nouveau off`, through which modprobe -r would ask for a module named off.
	if g5g_nouveau_there; then
		sudo -n rmmod nouveau >> "$S/modules.log" 2>&1 || true
		if g5g_nouveau_there; then
			pl "nouveau held after the install: nvidia not loaded"; exit 1
		fi
		pl "nouveau unloaded again"
	fi
	sudo -n modprobe nvidia >> "$S/modules.log" 2>&1 || true
	sudo -n modprobe nvidia_uvm >> "$S/modules.log" 2>&1 || true
	if g5g_mod nvidia && g5g_mod nvidia_uvm; then
		pl "nvidia and nvidia_uvm loaded, no reboot"
	else
		pl "nvidia not loaded: no reboot is made, and no other module package is tried"
		pl "installed set $inst"
		exit 1
	fi
	# The nodes, by the driver's own installed tools only, in this order; never a mknod here. How many of the four
	# stand after each tool is said, so that which tool made them can be read from this phase's own words.
	sudo -n udevadm settle >> "$S/modules.log" 2>&1 || true
	g5g_nodes > /dev/null; pl "nodes after the udev rule and helper (udevadm settle): $G5G_NODES_OK of 4"
	smi=0
	sudo -n timeout -k 5 "$G5G_SMI_WAIT_S" nvidia-smi > /dev/null 2>&1 || smi=$?
	case "$smi" in 124|137) pl "nvidia-smi as root did not end within $G5G_SMI_WAIT_S s: ended, and the node check goes on" ;; esac
	g5g_nodes > /dev/null; pl "nodes after nvidia-smi as root: $G5G_NODES_OK of 4"
	if grep -q '^pkg nvidia-modprobe=' "$G5G_APPROVED"; then
		sudo -n nvidia-modprobe -u -c 0 >> "$S/modules.log" 2>&1 || true
		mp=", then nvidia-modprobe -u -c 0"
		g5g_nodes > /dev/null; pl "nodes after nvidia-modprobe -u -c 0: $G5G_NODES_OK of 4"
	fi
	pl "device nodes: by the udev rule and helper nvidia-kernel-common-580-server installs (71-nvidia.rules, ub-device-create), then one run of nvidia-smi as root$mp; none made by hand"
	g5g_nodes > "$S/nodes.txt"
	nok="$G5G_NODES_OK"
	while read -r name ver; do
		case "$ver" in missing) pl "node missing: $name" ;; not*) pl "node not usable: $name" ;; esac
	done < "$S/nodes.txt"
	pl "nodes: $nok of 4 present and usable"
	pl "installed set $inst"
	[ "$nok" = 4 ] || exit 1
}
# --- llama-build
g5g_build_lock() { printf '%s' "${BUILD_STATE:-$HOME/builds}/build-llama.lock"; }
g5g_build_running() { [ -e "$(g5g_build_lock)" ] && ! flock -n "$(g5g_build_lock)" true; }
g5g_signal_group() { kill "-$1" -- "-$2" 2>/dev/null || true; }   # $1 the signal, $2 the runner's pid, its group's leader

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
	elif [ "$H" = run-aw-g1.sh ]; then   # SDV Phase 8 WP8: the rehearsal, and p6a: the two plans a bare-metal host takes
		case "$P" in rehearsal|p6a) ;; *) die "run-aw-g1.sh needs PLAN=rehearsal or PLAN=p6a here (the Orin's arms are its own helper's)" ;; esac
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
	# A g5g record (2026-11-10): capture.py's g5g lines, which the two lines below would not show. Only when the log's
	# first line is one of its two g5g first lines; for every other record this prints nothing.
	g5g_first="$(head -n 1 "$W/capture.log" 2>/dev/null || true)"
	case "$g5g_first" in
		"capture: a g5g record ("*|"capture: today's A6 evidence, with g5g stems ("*)
			printf '%s\n' "$g5g_first"
			grep -E '^(gpu-facts(-[1-9][0-9]*)?|gpu-install|llama-build|vlm): (evidence|no evidence \()' "$W/capture.log" || true
			grep -E '^excluded: (gpu-facts(-[1-9][0-9]*)?|gpu-install|llama-build|vlm)/' "$W/capture.log" || true ;;
	esac
	grep -E '^(vss-[A-Za-z0-9._-]+|ota-drill|aw-setup|aw-suite|aw-g1): (DONE|TIMEOUT|FAILED|INCOMPLETE|NO STATUS) ' "$W/capture.log" || true
	tail -2 "$W/capture.log" || true
	say "captured $(wc -l < "$W/pub.sha256") files into pub.tgz ($(du -h "$W/pub.tgz" | cut -f1))"
	;;
gpu-facts)
	marker_refuses "the gpu-facts phase"
	g5g_announce
	G5G_BOOT="$(g5g_boot)"
	first=0
	if [ "$G5G_BOOT" = none ]; then G5G_BOOT=same; first=1; fi
	S=""
	if [ -d "$REC" ]; then
		n=1; S="$REC/gpu-facts"
		while [ -e "$S" ]; do n=$((n + 1)); S="$REC/gpu-facts-$n"; done
		g5g_open "${S##*/}"
		if [ "$first" = 1 ]; then
			h="$(g5g_boot_hash)"
			[ "$h" = unread ] || echo "$h" > "$G5G_MARKER"
			# No marker: every later g5g phase reads boot=new (g5g_boot) and refuses, so the first run says so.
			[ "$h" != unread ] || say "the boot id was not read, so no boot marker was written ($G5G_MARKER): the next phase will read this boot as new (boot=new)"
		fi
	fi
	cpu="$(awk -F: '/^CPU implementer/ { gsub(/[ \t]/, "", $2); i = $2 }
		/^CPU part/ { gsub(/[ \t]/, "", $2); k = i ":" $2; if (!(k in seen)) { seen[k] = 1; out = out (out == "" ? "" : ",") k } }
		END { print out }' "$PROC_ROOT/cpuinfo" 2>/dev/null || true)"
	kvm=no
	if [ -r "$G5G_ROOT/dev/kvm" ] && [ -w "$G5G_ROOT/dev/kvm" ]; then kvm=yes; fi
	pci="$(g5g_pci)"
	npci=0; ids=none; bound=none
	if [ -n "$pci" ]; then
		npci="$(wc -l <<< "$pci")"
		ids="$(awk '{ printf "%s%s", (NR > 1 ? "," : ""), $1 }' <<< "$pci")"
		bound="$(awk '{ printf "%s%s", (NR > 1 ? "," : ""), $2 }' <<< "$pci")"
	fi
	nodes="$(g5g_nodes)"; g5g_nodes > /dev/null
	gpus=0; cap=none; smiv=""; names=""
	if ! command -v nvidia-smi > /dev/null 2>&1; then
		gp="driver tool: absent"
	else
		# The tool is given G5G_SMI_WAIT_S: against a wedged module it may never answer, and this is a read.
		smi=0
		gp="$(timeout -k 5 "$G5G_SMI_WAIT_S" nvidia-smi --query-gpu=index,name,compute_cap,memory.total,driver_version --format=csv,noheader 2>/dev/null)" || smi=$?
		if [ "$smi" = 0 ] && [ -n "$gp" ]; then
			gpus="$(wc -l <<< "$gp")"
			cap="$(awk -F', *' '{ printf "%s%s", (NR > 1 ? "," : ""), $3 }' <<< "$gp")"
			smiv="$(awk -F', *' 'NR == 1 { print $5 }' <<< "$gp")"
			names="$(awk -F', *' '{ print "gpu " $1 ": " $2 " (compute_cap " $3 ")" }' <<< "$gp")"
		elif [ "$smi" = 124 ] || [ "$smi" = 137 ]; then
			gp="driver tool: failed (no answer within $G5G_SMI_WAIT_S s)"
		else
			gp="driver tool: failed"
		fi
	fi
	drv=absent; uvm=no
	if g5g_mod nvidia; then
		drv="$(cat "$SYS_ROOT/module/nvidia/version" 2>/dev/null || true)"
		drv="${drv:-${smiv:-loaded}}"
	fi
	if g5g_mod nvidia_uvm; then uvm=yes; fi
	oops="$(kernel_oops_word)"
	line="gpu-facts: cpu_part=${cpu:-unread} kvm=$kvm nvidia_pci=$npci pci_ids=$ids bound=$bound driver=$drv uvm=$uvm nodes=$G5G_NODES_OK/4 gpus=$gpus compute_cap=$cap kernel_oops=$oops boot=$G5G_BOOT"
	if [ "$G5G_BOOT" = new ]; then
		# The boot that ended: its word from the journal's previous boot, and how many pstore entries it left (the
		# count only; no entry is read).
		G5G_PREV="$(kernel_oops_word prev)"
		ps="$(sudo -n ls -A "$SYS_ROOT/fs/pstore" 2>/dev/null | wc -l)" || ps=unread
		line="$line kernel_oops_prev=$G5G_PREV pstore=$ps"
	fi
	if [ -n "$S" ]; then
		printf '%s\n' "$pci" > "$S/pci.txt"
		printf '%s\n' "$nodes" > "$S/nodes.txt"
		printf '%s\n' "$gp" > "$S/gpus.txt"
		printf '%s\n' "$line" > "$S/summary.txt"
	else
		say "no $REC (setup did not finish): nothing was written; the summary line follows"
	fi
	# Each GPU by its name (gpus.txt holds the rest), then the summary, which stays the last line.
	[ -z "$names" ] || printf '%s\n' "$names"
	printf '%s\n' "$line"
	;;
gpu-install)
	g5g_begin gpu-install
	G5G_W_MODE=""
	g5g_words MODE && g5g_once && case "$G5G_W_MODE" in plan|apply) true ;; *) false ;; esac \
		|| die "gpu-install takes one word, MODE=plan or MODE=apply (LADDER_ENV), and no other"
	g5g_open gpu-install
	[ -r "$G5G_LIST" ] && [ -r "$G5G_PINGEN" ] || die "the repo tarball lacks orin-native/edge-llm/g5g-packages.list or g5g_pins.py"
	[ -r "$G5G_APPROVED" ] || die "no in/g5g-approved.txt: the approved-names file is a session input (METAL_FILES), and nothing is resolved without it"
	KREL="$(uname -r)"
	if [ "$G5G_W_MODE" = plan ]; then g5g_plan; else g5g_apply; fi
	;;
llama-build)
	g5g_begin llama-build
	G5G_W_MODE=""; G5G_W_JOBS=""; G5G_W_MEM_MAX=""
	g5g_words "MODE JOBS MEM_MAX" && g5g_once && case "$G5G_W_MODE" in ''|stop|wait) true ;; *) false ;; esac \
		|| die "llama-build takes MODE=stop or MODE=wait, or JOBS= and MEM_MAX= together, and no other word (LADDER_ENV)"
	if [ -n "$G5G_W_JOBS$G5G_W_MEM_MAX" ]; then
		[[ "$G5G_W_JOBS" =~ ^[1-9][0-9]{0,2}$ ]] && [[ "$G5G_W_MEM_MAX" =~ ^[1-9][0-9]{0,3}[MG]$ ]] && [ -z "$G5G_W_MODE" ] \
			|| die "JOBS='$G5G_W_JOBS' MEM_MAX='$G5G_W_MEM_MAX': a job count and a cap (a whole number with M or G), both or neither, and with no MODE"
	fi
	S="$REC/llama-build"
	if [ "$G5G_W_MODE" = stop ]; then
		if ! g5g_build_running; then say "no build is running: nothing changed"; exit 0; fi
		g5g_open llama-build
		pid="$(cat "$S/runner.pid" 2>/dev/null || true)"
		[[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "a build holds $(g5g_build_lock), and this session's stem names no runner: not stopped"
		g5g_signal_group TERM "$pid"
		for _ in $(seq 1 30); do { g5g_build_running || pgrep -g "$pid" > /dev/null; } || break; sleep 1; done
		if g5g_build_running || pgrep -g "$pid" > /dev/null; then g5g_signal_group KILL "$pid"; sleep 2; fi
		if g5g_build_running || pgrep -g "$pid" > /dev/null; then die "the build could not be ended: something of it is still alive"; fi
		date -u +%FT%TZ > "$S/stopped"
		say "stopped"
		exit 0
	fi
	if [ "$G5G_W_MODE" = wait ]; then
		[ -d "$S" ] || die "no $S: no build was started in this session"
		# A build that is not running and did not end whole is never waited for: a refused start made the stem too, a
		# stop ends the runner before it writes done, and a runner can die. The runner writes done as its last act, so
		# done is read once more after its pid is found gone.
		for _ in $(seq 1 "${G5G_BUILD_WAIT_S:-5400}"); do
			[ -e "$S/done" ] && break
			pid="$(cat "$S/runner.pid" 2>/dev/null || true)"
			if ! { [[ "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null; }; then
				[ -e "$S/done" ] && break
				[ ! -e "$S/stopped" ] || die "the build was stopped (MODE=stop) and did not end whole: nothing to wait for"
				die "no build is running and none ended whole (a start that was refused, or a runner that died): nothing to wait for"
			fi
			sleep 1
		done
		[ -e "$S/done" ] || { tail -5 "$S/build.log" 2>/dev/null || true; say "the build has not ended: wait again, or MODE=stop"; exit 2; }
		rc="$(cat "$S/build-exit.txt" 2>/dev/null || echo unread)"
		tail -15 "$S/build.log" 2>/dev/null || true
		[ ! -r "$S/BUILD-INFO" ] || cat "$S/BUILD-INFO"
		say "checkout size: $(cat "$S/checkout-size.txt" 2>/dev/null || echo unread)"
		say "build-llama.sh done with exit $rc"
		[ "$rc" = 0 ] || exit 1
		exit 0
	fi
	g5g_open llama-build
	g5g_build_running && die "a build is running: wait for it (MODE=wait) or end it (MODE=stop)"
	cap="$(g5g_fact compute_cap)"; gpus="$(g5g_fact gpus)"
	[[ "$gpus" =~ ^[1-9][0-9]*$ ]] && [[ "$cap" =~ ^7[.]5(,7[.]5)*$ ]] \
		|| die "the newest gpu-facts of this session did not read compute_cap 7.5 on every GPU (gpus=${gpus:-unread} compute_cap=${cap:-unread}): no build for CUDA architecture 75 is started"
	pin="$(awk '$1 == "llama" { print $2 }' "$G5G_APPROVED" 2>/dev/null || true)"
	[[ "$pin" =~ ^[0-9a-f]{40}$ ]] \
		|| die "the approved file names no llama.cpp pin (one line \`llama COMMIT CAP\`): the clone is a download, and none is made without it"
	[ -r "$G5G_E/build-llama.sh" ] || die "the repo tarball lacks orin-native/edge-llm/build-llama.sh"
	# lib-build.sh runs every build step in a scope of the user's own manager, which ends with the user's last login:
	# lingering first, read back, or nothing is started detached.
	u="${USER:-$(id -un)}"
	sudo -n loginctl enable-linger "$u" > /dev/null 2>&1 || true
	[ "$(loginctl show-user "$u" -p Linger 2>/dev/null || true)" = "Linger=yes" ] \
		|| die "lingering is not enabled for $u (loginctl show-user reads back no Linger=yes): the build's scopes would end with this login, so it is not started detached"
	say "lingering enabled"
	g5g_announce
	jobs="$G5G_W_JOBS"; mem="$G5G_W_MEM_MAX"
	if [ -n "$jobs" ]; then
		line="llama-build: JOBS=$jobs MEM_MAX=$mem (given as words)"
	else
		build_size
		jobs="$BUILD_JOBS"; mem="$BUILD_MEM_MAX"
		if [ -n "$jobs" ]; then
			line="llama-build: JOBS=$jobs MEM_MAX=$mem (the cap is half this host's memory; one job for every 2 GiB of it, at most one a core)"
		else
			line="llama-build: this host's memory was not read, or is too small to size the build to: lib-build.sh's own defaults apply (4 jobs under a 4G cap)"
		fi
	fi
	say "$line"
	echo "$line" > "$S/size.txt"
	rm -f "$S/done" "$S/build-exit.txt" "$S/BUILD-INFO" "$S/stopped" "$S/runner.pid"
	G5G_JOBS="$jobs" G5G_MEM="$mem" G5G_PIN="$pin" setsid nohup bash "$W/remote-ladder.sh" _llama-build > "$S/detach.log" 2>&1 < /dev/null &
	for _ in $(seq 1 20); do [ -s "$S/runner.pid" ] && break; sleep 0.5; done
	[ -s "$S/runner.pid" ] || { cat "$S/detach.log" 2>/dev/null || true; die "the detached build did not start"; }
	say "started"
	;;
_llama-build)
	# Internal: the detached runner llama-build starts (drive-metal.sh's PHASES does not list it). It leads its own
	# process group (setsid), which MODE=stop signals. Nothing built is run.
	S="$REC/llama-build"
	[ -d "$S" ] || die "no $S"
	trap '' PIPE HUP
	echo "$$" > "$S/runner.pid"
	G5G_BOOT="$(g5g_boot)"
	rc=0
	# shellcheck disable=SC2086  # two NAME=value words, or none
	env -u JOBS -u MEM_MAX CUDA_ARCH=75 LLAMA_COMMIT="${G5G_PIN:-}" ${G5G_JOBS:+JOBS="$G5G_JOBS" MEM_MAX="${G5G_MEM:-}"} \
		bash "$G5G_E/build-llama.sh" > "$S/build.log" 2>&1 || rc=$?
	echo "$rc" > "$S/build-exit.txt"
	if [ "$rc" = 0 ] && [ -r "$HOME/llama.cpp/build/bin/BUILD-INFO" ]; then cp "$HOME/llama.cpp/build/bin/BUILD-INFO" "$S/BUILD-INFO"; fi
	lim="$(awk '$1 == "llama" { print $3 }' "$G5G_APPROVED" 2>/dev/null || true)"
	echo "$(du -sb "$HOME/llama.cpp" 2>/dev/null | cut -f1 || true) bytes (the approved cap: ${lim:-unread})" > "$S/checkout-size.txt"
	g5g_host_after "$S/host-after.txt"
	sync
	touch "$S/done"
	;;
launch-svc)
	g5g_begin launch-svc
	G5G_W_IMAGE=""
	g5g_words IMAGE && g5g_once && [ -n "$G5G_W_IMAGE" ] \
		|| die "launch-svc takes one word, IMAGE=<an image this session uploaded> (LADDER_ENV), and no other"
	[[ "$SVC_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || die "SVC_PORT='$SVC_PORT' is not a port"
	inputs
	img="$(image_path "$G5G_W_IMAGE")" || die "IMAGE=$G5G_W_IMAGE is not an image this session uploaded"
	! pgrep -x qemu-system-aar > /dev/null || die "a QEMU is running: run stop first"
	# The vlm stem, but never its host-after.txt: that name there is the vlm phase's, and the capture reads it as that.
	g5g_open vlm launch-svc-host-after.txt
	C="$S/console.log"
	cd "$R"
	IFS_BIN="$img" DISK="$W/img/disk-qemu" LOG="$C" bash launch-qnx-kvm-bridged.sh \
		> "$S/launch-svc.log" 2>&1 || { cat "$S/launch-svc.log"; die "launch failed"; }
	cat "$S/launch-svc.log"
	# "guest up" is the launcher's own exchange on :7100. The service's port: two reads of the console, then the proof,
	# a connection the guest accepts. grep reads the console whole (no -q): a pipe closed early is a failure under pipefail.
	B="safety monitor listening on :$SVC_PORT ("
	for _ in $(seq 1 "${G5G_BANNER_WAIT_S:-30}"); do tr -d '\0\r' < "$C" | grep -aF "$B" > /dev/null && break; sleep 1; done
	tr -d '\0\r' < "$C" | grep -aF "$B" > /dev/null \
		|| { tail -20 "$C"; die "no plain monitor banner for :$SVC_PORT on the console -- is the image ifs-svc?"; }
	if tr -d '\0\r' < "$C" | grep -aF "liveness deadline" > /dev/null; then
		die "the console shows a deadline-mode monitor (ifs-live's), not the plain service monitor on :$SVC_PORT"
	fi
	timeout 3 bash -c "echo > /dev/tcp/$GUEST/$SVC_PORT" 2>/dev/null \
		|| die "the banner is on the console, but nothing accepts a connection on $GUEST:$SVC_PORT: the port is checked by an exchange, not by its banner"
	say "plain monitor answers on :$SVC_PORT"
	;;
vlm)
	g5g_begin vlm
	C="$REC/vlm/console.log"
	[ -r "$C" ] || die "no $C: run launch-svc first"
	[ ! -e "$REC/vlm/demo-exit.txt" ] || die "the vlm stem already holds a demo's exit status: one demo a session"
	g5g_open vlm
	[ -r "$G5G_E/vlm-demo.sh" ] || die "the repo tarball lacks orin-native/edge-llm/vlm-demo.sh"
	# By name, the programs the demo needs that user-data does not install, and the four device nodes.
	miss=""
	for c in curl flock taskset python3; do command -v "$c" > /dev/null 2>&1 || miss="$miss $c"; done
	[ -z "$miss" ] || die "the demo needs programs this host lacks:$miss (this phase installs nothing)"
	g5g_announce
	g5g_nodes > "$S/nodes.txt"
	[ "$G5G_NODES_OK" = 4 ] || die "a device node is missing or not usable ($(grep -v ' usable$' "$S/nodes.txt" | tr '\n' ';')): the demo is not started"
	# One GPU, the first: the server sees no other, and the stamp says so (vlm_stamp.py, cuda_visible_devices).
	rc=0
	CUDA_VISIBLE_DEVICES=0 IMAGES="$W/in" LLAMA_MODELS="$W/in" CONSOLE="$C" OUT="$S" \
		bash "$G5G_E/vlm-demo.sh" > "$S/demo.log" 2>&1 || rc=$?
	echo "$rc" > "$S/demo-exit.txt"
	tail -25 "$S/demo.log" || true
	say "demo exit $rc (recorded in demo-exit.txt; a claim that did not get its expected verdict is a finding, not this phase's failure)"
	# What the session reads after a demo, printed: the host's two words (host-after.txt gets them at this phase's end),
	# and what the stamp says of the board and of the GPUs the server could see.
	say "host after: kernel_oops=$(kernel_oops_word) boot=$G5G_BOOT"
	if [ ! -e "$S/stamp.json" ]; then say "stamp: absent"
	else
		say "stamp: $(python3 -c 'import json, sys
try:
    d = json.load(open(sys.argv[1]))
    w = ["%s=%s" % (k, " ".join(str(d[k]).split())[:80]) for k in ("board", "cuda_visible_devices")]
    print(" ".join(w))
except Exception:
    print("unreadable")' "$S/stamp.json" 2>/dev/null || echo unreadable)"
	fi
	;;
stop)
	sudo pkill -x qemu-system-aar 2>/dev/null || true
	sleep 1
	pgrep -x qemu-system-aar >/dev/null && die "QEMU still running"
	say "stopped"
	;;
*) die "unknown phase $PHASE" ;;
esac
