#!/usr/bin/env bash
# remote-ladder.sh -- the instance side of a bare-metal AWS ladder session.
# One phase per call, so the operator (drive-metal.sh run PHASE) sees each step:
#
#   setup     host facts, METAL_QEMU_PKG, unpack, verify the image and disk against
#             inputs.env, bridge, probe, native monitor, KVM counters readable
#   quiesce   let cloud-init and snap settle, stop the apt timers for the session
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
# capture accepts any of these sessions, but only a FINISHED one.
#
# W (default ~/a1) holds repo.tar, inputs.env, remote-ladder.sh, capture.py and
# img/<ifs> + img/disk-qemu.gz. Nothing under W leaves the host except pub.tgz,
# and everything in pub.tgz went through redact-aws.sh or capture.py's check here.
set -euo pipefail
PHASE="${1:?phase: setup|quiesce|launch|ladder|launch-live|liveness|launch-stamp|stamp|metal|someip|harness|capture|stop}"
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
	say "artefacts verified: $IFS_NAME ${IFS_SHA256:0:16} disk ${DISK_SHA256:0:16}${IFS_EXTRA:+ and $IFS_EXTRA}"
	# The record names what actually ran: the instance-side tooling and its inputs.
	mkdir -p "$REC/tooling"
	cp "$W/remote-ladder.sh" "$W/capture.py" "$W/inputs.env" "$REC/tooling/"
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
	# A fresh AMI is busy: cloud-init's tail, snap seeding, apt timers. Settle
	# them for the session, and record the load so a noisy round can be seen.
	cloud-init status --wait >/dev/null 2>&1 || true
	command -v snap >/dev/null && timeout 120 sudo snap wait system seed.loaded 2>/dev/null || true
	sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service 2>/dev/null || true
	for _ in $(seq 1 60); do pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null || break; sleep 5; done
	pgrep -x 'apt|apt-get|dpkg|unattended-upgr' >/dev/null && die "apt/dpkg/unattended-upgrades still running after 5 min"
	say "quiet: loadavg $(cut -d' ' -f1-3 /proc/loadavg)"
	;;
launch)
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
	cd "$R"
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	for w in $LADDER_ENV; do
		[[ "$w" =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._/-]*$ ]] || die "LADDER_ENV word '$w' is not NAME=value"
	done
	echo "LADDER_ENV=$LADDER_ENV K=${K:-12}" > "$REC/ladder/ladder-env.txt"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/ladder/host-before.txt"
	# shellcheck disable=SC2086  # LADDER_ENV is a list of validated NAME=value words
	env -- $LADDER_ENV OUT="$REC/ladder/raw" K="${K:-12}" bash run-ladder.sh > "$REC/ladder/run.log" 2>&1 \
		|| { tail -30 "$REC/ladder/run.log"; die "run-ladder.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/ladder/host-after.txt"
	tail -5 "$REC/ladder/run.log"
	;;
launch-live)
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
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/liveness/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-live first"
	E="$W/repo/orin-native/edge-llm"
	[ -r "$E/liveness-demo.sh" ] && [ -r "$E/run-live-cost.sh" ] || die "the repo tarball lacks orin-native/edge-llm"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/liveness/host-before.txt"
	CONSOLE="$C" OUT="$REC/liveness/demo" bash "$E/liveness-demo.sh" > "$REC/liveness/demo.log" 2>&1 \
		|| { tail -20 "$REC/liveness/demo.log"; die "liveness-demo.sh failed"; }
	tail -12 "$REC/liveness/demo.log"
	CONSOLE="$C" OUT="$REC/liveness/cost" K="${K:-12}" bash "$E/run-live-cost.sh" > "$REC/liveness/cost.log" 2>&1 \
		|| { tail -30 "$REC/liveness/cost.log"; die "run-live-cost.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/liveness/host-after.txt"
	tail -8 "$REC/liveness/cost.log"
	;;
launch-stamp)
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
	case "${K:-12}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	C="$REC/stamp/guest-console.log"
	[ -r "$C" ] || die "no $C -- run launch-stamp first"
	[ -r "$R/run-stamp.sh" ] || die "the repo tarball lacks run-stamp.sh"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/stamp/host-before.txt"
	CONSOLE="$C" OUT="$REC/stamp/raw" MON="$W/stamp-monitor-native" K="${K:-12}" \
		bash "$R/run-stamp.sh" > "$REC/stamp/run.log" 2>&1 \
		|| { tail -30 "$REC/stamp/run.log"; die "run-stamp.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/stamp/host-after.txt"
	tail -22 "$REC/stamp/run.log"
	;;
metal)
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
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/metal/host-before.txt"
	CONSOLE="$C" OUT="$REC/metal/raw" K="${K:-40}" bash "$R/run-metal.sh" > "$REC/metal/run.log" 2>&1 \
		|| { tail -30 "$REC/metal/run.log"; die "run-metal.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/metal/host-after.txt"
	tail -24 "$REC/metal/run.log"
	;;
someip)
	case "${K:-16}" in *[!0-9]*|'') die "K='${K:-}' is not a round count" ;; esac
	inputs
	[ -r "$R/run-someip.sh" ] && [ -r "$R/run-someip0.sh" ] || die "the repo tarball lacks run-someip.sh or run-someip0.sh"
	[ -e "$REC/someip" ] && die "$REC/someip exists: one someip run per session"
	mkdir -p "$REC/someip"
	build_vsomeip "$REC/someip"
	cd "$R"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/someip/host-before.txt"
	IMG_S="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/someip/raw" K="${K:-16}" CSTATE=shallow bash "$R/run-someip.sh" > "$REC/someip/run.log" 2>&1 \
		|| { tail -30 "$REC/someip/run.log"; die "run-someip.sh failed"; }
	tail -30 "$REC/someip/run.log"
	IMG_S="$W/img/$IFS_NAME" DISK="$W/img/disk-qemu" VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/someip/raw0" K=12 CSTATE=shallow bash "$R/run-someip0.sh" > "$REC/someip/run0.log" 2>&1 \
		|| { tail -30 "$REC/someip/run0.log"; die "run-someip0.sh failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/someip/host-after.txt"
	tail -30 "$REC/someip/run0.log"
	;;
harness)
	# A leading zero is octal to the harnesses' own arithmetic, and "k": 08 is not JSON in a stamp.
	case "${K:-}" in *[!0-9]*|0*) die "K='${K:-}' is not a round count (digits, no leading zero)" ;; esac
	inputs
	[ -n "$LADDER_GIVEN" ] || die "the harness phase needs LADDER_ENV=\"HARNESS=<name> IMAGE=<image> ...\""
	H=""; I=""; imgs=(); declare -A role=() seen=()
	once() { [ -z "${seen[$1]:-}" ] || die "LADDER_ENV names $1 twice"; seen[$1]=1; }
	for w in ${LADDER_ENV:-}; do
		case "$w" in
			HARNESS=?*) once HARNESS; H="${w#HARNESS=}" ;;
			IMAGE=?*) once IMAGE; I="${w#IMAGE=}" ;;
			IMG_B=*|IMG_R=*|IMG_UA=*|IMG_UB=*)
				once "${w%%=*}"
				p="$(image_path "${w#*=}")" || die "image '${w#*=}' (${w%%=*}) was not uploaded in this session"
				role[${w%%=*}]="$p"; imgs+=("${w%%=*}=$p") ;;
			HARNESS=|IMAGE=) die "LADDER_ENV word '$w' has no value" ;;
			IMG_*) die "LADDER_ENV word '$w': the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB (IMG_S, IFS_BIN and IMG_P are IMAGE's)" ;;
			*) die "LADDER_ENV word '$w' is not one the harness phase reads: HARNESS=, IMAGE=, IMG_B=, IMG_R=, IMG_UA=, IMG_UB= (K is its own variable)" ;;
		esac
	done
	case "$H" in
		run-someip.sh|run-someip0.sh|run-someip1.sh|run-trace.sh|run-trace2.sh|run-haltpoll.sh|run-bell.sh|run-paths.sh|run-mmio.sh|run-bellrate.sh|run-unmask.sh|run-bellrobust.sh) ;;
		*) die "HARNESS='$H' is not one the harness phase runs" ;;
	esac
	case "$H" in   # a multi-image harness must be given each image, and K as it takes it, before $REC/<name> exists
		run-unmask.sh) takes="IMG_UA IMG_UB"
			[ -z "${K:-}" ] || [ $((K % 4)) = 0 ] || die "run-unmask.sh needs K a multiple of 4 (default 16)" ;;
		run-bellrobust.sh) takes="IMG_B IMG_R IMG_UA"
			[ -z "${K:-}" ] || die "run-bellrobust.sh takes no K: its three repeats are pre-registered" ;;
		*) takes="" ;;
	esac
	why=" (its image is IMAGE=)"; [ -z "$takes" ] || why=" (it takes $takes)"
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
	[ -r "$R/$H" ] || die "the repo tarball lacks $H"
	img="$(image_path "${I:-$IFS_NAME}")" || die "image '${I:-$IFS_NAME}' was not uploaded in this session"
	stem="${H#run-}"; stem="${stem%.sh}"
	[ -e "$REC/$stem" ] && die "$REC/$stem exists: one $stem run per session"
	mkdir -p "$REC/$stem"
	case "$H" in run-someip*) build_vsomeip "$REC/$stem" ;; esac
	cd "$R"
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/$stem/host-before.txt"
	# The IMG_ words come after IMAGE's defaults, so they win (env applies its assignments in order).
	env IMG_S="$img" IMG_B="$img" IFS_BIN="$img" ${imgs[@]+"${imgs[@]}"} DISK="$W/img/disk-qemu" \
		VPROBE="$W/vsomeip/3.4.10/bin/someip_vprobe" \
		OUT="$REC/$stem/raw" CSTATE=shallow ${K:+K="$K"} bash "$R/$H" > "$REC/$stem/run.log" 2>&1 \
		|| { tail -30 "$REC/$stem/run.log"; die "$H failed"; }
	{ date -u +%FT%TZ; cat /proc/loadavg; cat /proc/interrupts; } > "$REC/$stem/host-after.txt"
	tail -30 "$REC/$stem/run.log"
	;;
capture)
	# The session must have FINISHED: host-after.txt is written only after the
	# ladder, the liveness phase or the stamp phase returned 0. Without it the
	# run was interrupted, or refused as incomplete, and a partial record must
	# not be packed and fetched as a whole one.
	[ -e "$REC/ladder/host-after.txt" ] || [ -e "$REC/liveness/host-after.txt" ] || [ -e "$REC/stamp/host-after.txt" ] \
		|| [ -e "$REC/metal/host-after.txt" ] || [ -e "$REC/someip/host-after.txt" ] \
		|| ls "$REC"/*/host-after.txt > /dev/null 2>&1 \
		|| die "no host-after.txt under $REC/ladder, $REC/liveness, $REC/stamp, $REC/metal or $REC/someip -- the session did not finish; there is no complete record to capture"
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
	USER= python3 "$W/capture.py" "$REC" "$W/pub" "$RED" > "$W/capture.log" 2>&1 \
		|| { tail -5 "$W/capture.log" || true; die "capture refused -- see $W/capture.log"; }
	tar -czf "$W/pub.tgz" -C "$W/pub" . 2>> "$W/capture.log" || die "packing pub.tgz failed -- see $W/capture.log"
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
