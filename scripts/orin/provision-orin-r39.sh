#!/usr/bin/env bash
#
# Phase 3b (A6; the board after its upgrade to L4T R39, 2026-10-04)
# provision-orin-r39.sh -- say where a freshly installed Jetson Orin Nano (L4T R39, Ubuntu 24.04)
# stands against what this project's builds and smokes need, and install the packages it lacks.
#
#   usage: bash provision-orin-r39.sh [check|apply] [--bridge] [FAMILY ...]
#
#   check     (the default) reads and reports. It changes nothing and writes no file, not even a
#             log. Every item is one line:
#               ok       as wanted
#               missing  apply would make it
#               differs  not as wanted, and this script will not change it
#               note     a value reported with no judgement
#             Exit 0: nothing for apply to do. 1: apply has something to do. 2: an item differs,
#             so apply would stop there.
#   apply     takes the same steps in the same order: first everything that is only asserted,
#             then the changes. Each change is: check, act only if needed, check again. The
#             first step that differs or fails stops the run. A second apply changes nothing.
#             Exit 0: every step ok. 1: an action failed. 2: stopped at a refusal or at an item
#             that differs.
#   FAMILY    the package families to look at: core, build and someip when none is named; cuda
#             only when it is named (apply cuda).
#   --bridge  apply runs setup-bridge-orin.sh once, when br0 or tap-qnx is missing.
#
# Run it as the login that will run the guests, never as root. It calls sudo -n for the few
# commands that need it and for nothing else.
#
# WHAT APPLY CHANGES, and nothing else:
#   1. Packages, by family. Only the packages dpkg reports missing are passed to apt, with
#      --no-install-recommends and --no-upgrade. The package lists are refreshed, the install is
#      simulated, and the simulation is printed. The run stops if apt would remove anything,
#      upgrade an installed package, or touch an nvidia-l4t-* or kernel package, and the core
#      family stops if the candidate build of qemu-system-arm is not the installed one. What is
#      then installed is exactly what the simulation listed: each package is named with the
#      version the simulation showed, with --no-remove and --trivial-only, so that apt itself
#      refuses to do anything more than was named. Each package is checked afterwards. A package
#      named this way is marked manually installed. needrestart, where installed, is suspended
#      for the install (NEEDRESTART_SUSPEND=1), so that this script restarts no service. The
#      install waits for dpkg's lock (-o DPkg::Lock::Timeout=120) when another apt holds it, as
#      the daily timers' runs do. The refresh of the lists does not wait, with that option or
#      without (apt 2.8): when it meets such a run it fails at once, nothing is installed, and
#      apply is started again.
#   2. The login joins the kvm group (usermod -aG kvm), announced before and after. A new login
#      is needed before it takes effect.
#   3. With --bridge: setup-bridge-orin.sh, once. Its output is not shown and not logged, because
#      it prints the tap's MAC address.
#   4. Its own log, ~/provision/provision-<utc>.log, once the host is known to be the board.
#
# WHAT IT ONLY ASSERTS. Each of these is read before the first change, so a difference stops
# apply with no list refreshed, nothing installed and nobody added to a group; nothing is
# written:
#   the L4T and Ubuntu releases; sudo -k -n (the sudoers line; a cached credential does not
#   count); no installer stick (see below); Docker as installed (the package, its three units
#   enabled, the nvidia runtime in daemon.json; nobody is added to the docker group); the
#   nvpmodel mode; the cpufreq governor at rest; gdm's WaylandEnable=false; kvm's halt_poll_ns;
#   that there is a kvm group to join; with --bridge, that the bridge script is there; and, for
#   each selected family, that dpkg has left none of its packages unfinished (half-installed,
#   unpacked, half-configured, waiting for triggers) and, for someip, that no unversioned Boost
#   -dev package is installed.
# What depends on the archive is read after the package lists are refreshed, family by family:
# the candidate build of qemu-system-arm, and each family's simulation. A stop there comes after
# the refresh, and after the families before it were installed.
#
# WHAT IT NEVER DOES. It writes no sudoers file: without sudo -n it prints the line the owner has
# to add, and stops. It sets no auto-login, installs no unit for the bridge, and does not touch the
# kernel command line. It has no code path that changes the nvpmodel mode, a governor, gdm's
# configuration, Docker, swap, auditd, br_netfilter or a sysctl, and no option that would. It runs
# no apt upgrade and does not reboot.
#
# THE INSTALLER STICK. apply refuses while a removable or USB block device is present, or
# anything is mounted under /media. The installer's boot entry installs unattended, and a reset
# nobody chose would walk the boot order with the stick attached. The only override is
# PROVISION_ALLOW_REMOVABLE=1, and it is the owner's to give. A device list that cannot be read
# counts as a stick. One kind of mount under /media does not: the vendor's own image, which the
# desktop session mounts by itself with no stick in. A mount is taken for it only when all three
# hold: its source is a loop device, the file behind that device (the first line of
# /sys/block/<loopN>/loop/backing_file) is under /opt/nvidia/, and it is mounted read-only. With
# any one of them wrong, or the backing file not readable, the mount counts as any other. The
# item then names the image, and a removable or USB device beside it is refused as before.
#
# A LOST SESSION. apply ignores SIGPIPE and SIGHUP, and writes each line to its log before it
# prints it. When the reader of its output goes away (an SSH session that drops, a caller that
# times out) it runs on: an install that has started is not cut off, each step is still checked,
# and the log ends with the outcome. Read the log's last line before starting apply again. check
# changes nothing, so it keeps the default: it dies with its reader.
#
# NO NAME AND NO ADDRESS. It prints and logs no host name and no address. It runs no command that
# asks for the host's name, never lists interface addresses, and asks systemd only is-enabled and
# is-active. Mount points are counted, not printed; of the vendor's image under /media the last
# component of its mount point is said, and nothing of one that sits directly under /media, where
# the desktop keeps a directory per login. Other commands can name the host: sudo does,
# on stderr at every call, when the name does not resolve. Before a command's output is logged or
# printed, sudo's "unable to resolve host" line loses the name, and so does any line that holds
# the name as the shell has it (its HOSTNAME variable, which is used for that and never said).
# What sudo answers to the one question asked of sudo itself is not shown at all.
#
# FOR TESTS ONLY: ETC_ROOT, SYS_ROOT, PROC_ROOT and BRIDGE_SCRIPT redirect what is read and which
# bridge script runs. Each is announced when set. tests/test_provision.py runs this script against
# stubs.
#
# WHAT A PASS DOES NOT SHOW: that /dev/kvm access survives a reboot with nobody logged in at the
# display; anything about Docker, auditd or br_netfilter beyond their state; that the package set
# is what a later archive update leaves; that anything installed here builds or runs anything;
# that the real sudo and apt run on through a lost session as the stubs of the tests do; that
# apply outlives a session logind cleans up (KillUserProcesses=yes sends SIGTERM and SIGKILL,
# which are not ignored, and the setting is not read here); what a package's maintainer scripts
# and triggers did besides installing it (a boot file rewritten, a service restarted, a unit
# enabled: nothing is compared before and after); that a host-naming line in a wording this
# script does not know is struck out when the shell's HOSTNAME is not the name in it; that a
# read-only loop mount on a file under /opt/nvidia/ is the vendor's image and nothing else (the
# file's path is all that is read of it; who may write under /opt/nvidia/ is not looked at).
# Booting a guest under KVM on this board uses a startup we rebuilt, which is not a QNX-supported
# configuration, and nothing here times anything.

set -u
set -o pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ETC="${ETC_ROOT:-/etc}"
SYSR="${SYS_ROOT:-/sys}"
PROC="${PROC_ROOT:-/proc}"
BRIDGE_SCRIPT="${BRIDGE_SCRIPT:-$here/setup-bridge-orin.sh}"

WANT_L4T=39
WANT_OS=24.04
WANT_NVPMODEL=1
WANT_GOVERNOR=schedutil
WANT_HALT_POLL=500000

FAMILIES="core build someip cuda"
DEFAULT_FAMILIES="core build someip"
PKGS_core="qemu-system-arm qemu-utils ipxe-qemu iproute2 bridge-utils ethtool build-essential device-tree-compiler curl"
PKGS_build="g++ cmake git bison"
PKGS_someip="libboost1.74-dev libboost-system1.74-dev libboost-thread1.74-dev libboost-filesystem1.74-dev"
PKGS_cuda="cuda-nvcc-13-2 cuda-cudart-dev-13-2 libcublas-dev-13-2"
# The default Boost of this Ubuntu release. Its -dev packages and the 1.74 ones own the same
# headers, so the two sets cannot coexist.
BOOST_UNVERSIONED="libboost-dev libboost-all-dev libboost-system-dev libboost-thread-dev libboost-filesystem-dev"
QEMU_PKG=qemu-system-arm
USAGE="usage: bash provision-orin-r39.sh [check|apply] [--bridge] [core|build|someip|cuda ...]"

MODE=check
WANT_BRIDGE=0
SELECTED=""
LOG=""
PRELOG=""
LOGIN=""
SUDO_OK=0
APT_UPDATED=0
N_OK=0
N_MISSING=0
N_DIFFERS=0
declare -A HAVE=()
declare -A HALF=()
declare -A FAM_STOPPED=()
KVM_GROUP=0
BRIDGE_STOPPED=0
SIM_WHY=""
SIM_LIST=()
QEMU_INST=""
QEMU_CAND=""
FL=""
UNIT_WORD=""

# ------------------------------------------------------------------ output

# Everything said goes to the log (under apply) and to stdout, in that order: the log does not
# depend on anybody reading stdout. Before the log exists (the host is not yet known to be the
# board) the lines are kept, and written when it is opened. A print that fails is not an error:
# under apply SIGPIPE is ignored, and a reader that has gone away must not stop the run.
say() {
	if [ -n "$LOG" ]; then
		printf '%s\n' "$*" >> "$LOG"
	elif [ "$MODE" = apply ]; then
		PRELOG+="$*"$'\n'
	fi
	printf '%s\n' "$*" 2> /dev/null
	return 0
}

# A command's output, line by line, marked as such. A command can name the host, which this
# script never does: sudo says "unable to resolve host <name>" on stderr at every call when the
# name does not resolve, and names the host again when it refuses a command. The known line is
# cut after "host", whatever follows it; and whatever the line, the name as this shell has it is
# struck out. The shell's HOSTNAME is used here and nowhere else, and is never said.
emit() {
	local l
	while IFS= read -r l || [ -n "$l" ]; do
		case "$l" in
			"sudo: unable to resolve host "*) l="sudo: unable to resolve host [not shown]" ;;
		esac
		if [ -n "${HOSTNAME:-}" ]; then l="${l//"$HOSTNAME"/[host]}"; fi
		say "  | $l"
	done
}

item() {  # item <ok|missing|differs|note> <what> <detail>
	local line
	case "$1" in
		ok) N_OK=$((N_OK + 1)) ;;
		missing) N_MISSING=$((N_MISSING + 1)) ;;
		differs) N_DIFFERS=$((N_DIFFERS + 1)) ;;
	esac
	printf -v line '%-8s %s: %s' "$1" "$2" "$3"
	say "$line"
}

finish() {  # finish <apply's exit status>
	local rc=0 verdict="nothing for apply to do"
	if [ "$MODE" = check ]; then
		if [ "$N_MISSING" != 0 ]; then rc=1; verdict="apply has something to do"; fi
		if [ "$N_DIFFERS" != 0 ]; then rc=2; verdict="apply would stop: what differs is not changed by this script"; fi
		say "check: $N_OK ok, $N_MISSING missing, $N_DIFFERS differs -- $verdict"
		exit "$rc"
	fi
	[ "$1" != 0 ] || say "apply: every step ok ($N_OK items)"
	exit "$1"
}

# A state this script will not change. check counts it and goes on; apply stops there.
differs() {  # differs <what> <detail>
	item differs "$1" "$2"
	[ "$MODE" = apply ] || return 0
	say "STOP at $1: $2. Nothing further was done."
	finish 2
}

# An action was taken and did not do what it was for.
failed() {
	say "FAILED: $*. Nothing further was done."
	finish 1
}

first_line() {  # FL = the first line of a file, or nothing; never an error
	FL=""
	if [ -r "$1" ]; then IFS= read -r FL < "$1" 2>/dev/null; fi
	return 0
}

# systemd is asked two questions about a unit and no other. Neither prints anything about the
# host. One unit at a time, so that a unit systemd does not know cannot shift another's answer.
unit_enabled() {  # UNIT_WORD = enabled, disabled, static, not-found, ...
	UNIT_WORD=$(systemctl is-enabled "$1" 2>/dev/null)
	UNIT_WORD="${UNIT_WORD%%[[:space:]]*}"
	UNIT_WORD="${UNIT_WORD:-unknown}"
}

unit_active() {  # UNIT_WORD = active, inactive, failed, ...
	UNIT_WORD=$(systemctl is-active "$1" 2>/dev/null)
	UNIT_WORD="${UNIT_WORD%%[[:space:]]*}"
	UNIT_WORD="${UNIT_WORD:-unknown}"
}

# ------------------------------------------------------------------ 1. identity

step_release() {
	local rel="" rev="" osv="" k v q='"'
	local re='^# R([0-9]+) \(release\), REVISION: ([0-9.]+)'
	if [ ! -r "$ETC/nv_tegra_release" ]; then
		differs "L4T release" "nv_tegra_release is absent: this is not an L4T system"
	else
		first_line "$ETC/nv_tegra_release"
		if [[ "$FL" =~ $re ]]; then rel="${BASH_REMATCH[1]}"; rev="${BASH_REMATCH[2]}"; fi
		if [ "$rel" = "$WANT_L4T" ]; then
			item ok "L4T release" "R$rel, revision $rev"
		else
			differs "L4T release" "R${rel:-?} is not R$WANT_L4T, the release this script was written and checked for"
		fi
	fi
	if [ -r "$ETC/os-release" ]; then
		while IFS='=' read -r k v; do
			if [ "$k" = VERSION_ID ]; then osv="${v//$q/}"; fi
		done < "$ETC/os-release"
	fi
	if [ "$osv" = "$WANT_OS" ]; then
		item ok "OS release" "Ubuntu $osv"
	else
		differs "OS release" "VERSION_ID is ${osv:-unread}, not $WANT_OS"
	fi
}

# The log is opened only after the releases are as expected: on a host that is not the board,
# apply writes nothing at all.
open_log() {
	local dir="$HOME/provision"
	mkdir -p "$dir" || { echo "FATAL: cannot make $dir" >&2; exit 1; }
	LOG="$dir/provision-$(date -u +%Y%m%dT%H%M%SZ).log"
	printf '%s' "$PRELOG" >> "$LOG" || { echo "FATAL: cannot write the log" >&2; exit 1; }
	PRELOG=""
	say "log: $LOG"
}

# -k: sudo neither uses nor renews a cached credential, so success means the sudoers line and not
# a password typed a few minutes ago, and check leaves sudo's own state as it was. What sudo
# prints by itself is kept only to know that it printed something: it is never shown.
step_sudo() {
	local noise rc
	noise=$(sudo -k -n true 2>&1 > /dev/null < /dev/null); rc=$?
	if [ "$rc" = 0 ]; then
		SUDO_OK=1
		item ok "sudo" "sudo -k -n works with no password and no cached credential; this script writes no sudoers file"
		[ -z "$noise" ] || item note "sudo stderr" "sudo itself writes to stderr at every call (not shown: such a line can name the host). If it says that the host's name does not resolve, /etc/hosts is the owner's"
		return
	fi
	SUDO_OK=0
	say "  sudo -n does not work for this login without a cached credential. This script never writes a sudoers file."
	say "  The owner adds this one line, as root, to a file of his own under /etc/sudoers.d (visudo checks it):"
	say "    $LOGIN ALL=(ALL) NOPASSWD:ALL"
	differs "sudo" "sudo -k -n true fails (what sudo said is not shown); the sudoers line is the owner's to add"
}

# ------------------------------------------------------------------ 11. the installer stick

step_stick() {
	local out rc line name removable tran found="" mounts=0 unknown="" what=""
	local target src opts label vendor=""
	local re_name='NAME="([^"]*)"' re_rm='RM="([^"]*)"' re_tran='TRAN="([^"]*)"' re_loop='^/dev/(loop[0-9]+)$'
	out=$(lsblk -d -n -P -o NAME,RM,TRAN,TYPE 2>/dev/null); rc=$?
	if [ "$rc" != 0 ] || [ -z "$out" ]; then
		unknown="lsblk listed no block device (exit $rc)"
	else
		while IFS= read -r line; do
			name=""; removable=""; tran=""
			if [[ "$line" =~ $re_name ]]; then name="${BASH_REMATCH[1]}"; fi
			if [[ "$line" =~ $re_rm ]]; then removable="${BASH_REMATCH[1]}"; fi
			if [[ "$line" =~ $re_tran ]]; then tran="${BASH_REMATCH[1]}"; fi
			if [ "$removable" = 1 ] || [ "$tran" = usb ]; then found="$found $name"; fi
		done <<< "$out"
	fi
	out=$(findmnt -r -n -o TARGET,SOURCE,OPTIONS 2>/dev/null); rc=$?
	if [ "$rc" != 0 ] || [ -z "$out" ]; then
		unknown="${unknown:+$unknown; }findmnt listed no mount (exit $rc)"
	else
		while read -r target src opts; do
			case "$target" in /media|/media/*) ;; *) continue ;; esac
			# One kind of mount under /media is not a stick: the vendor's own image, which the
			# desktop session mounts by itself. A mount is taken for it only when all three hold:
			# its source is a loop device, the file behind that device is under /opt/nvidia/, and
			# it is mounted read-only. A backing file that cannot be read is under nothing.
			FL=""
			if [[ "$src" =~ $re_loop ]]; then first_line "$SYSR/block/${BASH_REMATCH[1]}/loop/backing_file"; fi
			if [[ "$FL" == /opt/nvidia/* ]] && [[ ",$opts," == *,ro,* ]]; then
				# Named by the last component of its mount point. One level under /media is where
				# the desktop keeps a directory per login, so a name at that level is not said.
				label="[not shown]"
				case "$target" in /media/*/*) label="${target##*/}" ;; esac
				vendor="${vendor:+$vendor, }$label"
			else
				mounts=$((mounts + 1))
			fi
		done <<< "$out"
	fi
	if [ -n "$found" ]; then what="removable block device:$found"; fi
	if [ "$mounts" = 1 ]; then what="${what:+$what; }1 mount under /media"; fi
	if [ "$mounts" -gt 1 ]; then what="${what:+$what; }$mounts mounts under /media"; fi
	if [ -n "$unknown" ]; then what="${what:+$what; }cannot tell whether a stick is in: $unknown"; fi
	if [ -n "$vendor" ]; then
		vendor="the vendor's read-only image ($vendor: a loop device on a file under /opt/nvidia/)"
		if [ -n "$what" ]; then what="$what; not counted: $vendor"; fi
	fi
	if [ -z "$what" ] && [ -n "$vendor" ]; then
		item ok "installer stick" "no removable or USB block device; under /media only $vendor, which is not a stick"
	elif [ -z "$what" ]; then
		item ok "installer stick" "no removable or USB block device, nothing mounted under /media"
	elif [ "${PROVISION_ALLOW_REMOVABLE:-}" = 1 ]; then
		item note "installer stick" "$what -- allowed by PROVISION_ALLOW_REMOVABLE=1, the owner's override"
	else
		differs "installer stick" "$what -- apply refuses while it is there: a reset would walk the boot order with an unattended installer attached. The owner removes it; PROVISION_ALLOW_REMOVABLE=1 is the owner's override"
	fi
}

# ------------------------------------------------------------------ 2. packages

# A package is installed when its state is "ok installed", whatever dpkg has been told to want of
# it: a package on hold is on the system, and apt would skip it. It is missing when dpkg does not
# know it, or has it as not-installed or with only its configuration left. Any other status is
# one dpkg left unfinished (half-installed, unpacked, half-configured, waiting for triggers, or
# installed and marked for reinstallation): an install was interrupted or failed. That is
# neither installed nor missing: apt's simulation skips such a package, and says nothing of
# dpkg's state.
query_installed() {  # for each of "$@": HAVE[pkg]=version when installed, HALF[pkg]=dpkg's status when unfinished
	local out p st v
	for p in "$@"; do unset "HAVE[$p]" "HALF[$p]"; done
	out=$(dpkg-query -W -f='${Package}|${Status}|${Version}\n' "$@" 2>/dev/null)
	while IFS='|' read -r p st v; do
		[ -n "$p" ] || continue
		case "$st" in
			*" ok installed") HAVE["$p"]="$v" ;;
			*" not-installed"|*" config-files") ;;
			*) HALF["$p"]="$st" ;;
		esac
	done <<< "$out"
}

# The packages this script must never see apt touch: NVIDIA's L4T packages (the kernel is one of
# them on this board) and a distribution kernel. linux-libc-dev is the C library's headers, not a
# kernel, and is not in the list.
is_protected() {
	case "$1" in
		nvidia-l4t-*|linux-image*|linux-headers*|linux-modules*|linux-tegra*|linux-nvidia*|linux-generic*|linux-firmware*) return 0 ;;
	esac
	return 1
}

# Read a simulation: SIM_WHY says why it may not be installed (empty: it may), SIM_LIST is every
# package it would newly install, as name=version.
sim_read() {  # sim_read <exit status> <text> <requested package ...>
	local rc="$1" text="$2" line verb rest pkg ver p
	local re_up='^Inst [^ ]+ \[' re_new='^Inst ([^ ]+) \(([^ ]+) .*\)'
	local re_pkg='^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?$' re_ver='^[0-9][0-9A-Za-z.+:~-]*$'
	local -A listed=()
	shift 2
	SIM_WHY=""
	SIM_LIST=()
	if [ "$rc" != 0 ]; then SIM_WHY+=" the simulation exited $rc;"; fi
	while IFS= read -r line; do
		case "$line" in
			"Inst "*|"Conf "*|"Remv "*|"Purg "*) ;;
			*) continue ;;
		esac
		verb="${line%% *}"; rest="${line#* }"; pkg="${rest%% *}"
		if is_protected "$pkg"; then SIM_WHY+=" apt would touch $pkg, an NVIDIA L4T or kernel package;"; fi
		case "$verb" in
			Remv|Purg) SIM_WHY+=" apt would remove $pkg;" ;;
			Inst)
				if [[ "$line" =~ $re_up ]]; then
					SIM_WHY+=" apt would upgrade the installed $pkg;"
				elif [[ "$line" =~ $re_new ]]; then
					pkg="${BASH_REMATCH[1]}"; ver="${BASH_REMATCH[2]}"
					if [[ "$pkg" =~ $re_pkg ]] && [[ "$ver" =~ $re_ver ]]; then
						if [ -z "${listed[$pkg]:-}" ]; then SIM_LIST+=("$pkg=$ver"); listed["$pkg"]=1; fi
					else
						SIM_WHY+=" a line of the simulation cannot be read ($line);"
					fi
				else
					SIM_WHY+=" a line of the simulation cannot be read ($line);"
				fi ;;
		esac
	done <<< "$text"
	if [ "${#SIM_LIST[@]}" = 0 ]; then SIM_WHY+=" the simulation lists nothing to install;"; fi
	for p in "$@"; do
		if [ -z "${listed[$p]:-}" ]; then SIM_WHY+=" the simulation does not install $p;"; fi
	done
	SIM_WHY="${SIM_WHY# }"
	SIM_WHY="${SIM_WHY%;}"
}

apt_update_once() {
	local rc
	[ "$APT_UPDATED" = 0 ] || return 0
	say "  refreshing the package lists before any simulation"
	sudo -n apt-get update < /dev/null 2>&1 | emit
	rc="${PIPESTATUS[0]}"
	[ "$rc" = 0 ] || failed "apt-get update exited $rc"
	APT_UPDATED=1
}

qemu_builds() {  # QEMU_INST and QEMU_CAND, as apt sees them
	local out k v
	QEMU_INST=""; QEMU_CAND=""
	out=$(LC_ALL=C apt-cache policy "$QEMU_PKG" 2>/dev/null)
	while read -r k v; do
		case "$k" in
			Installed:) QEMU_INST="$v" ;;
			Candidate:) QEMU_CAND="$v" ;;
		esac
	done <<< "$out"
}

# What dpkg already says against a family, read for every selected family before the first
# change: apt is not called for a family this stops, and under apply it is not called at all.
step_family_state() {
	local fam="$1" ref="PKGS_$1" p found="" half=""
	local -a pkgs=() ub=()
	read -r -a pkgs <<< "${!ref}"

	query_installed "${pkgs[@]}"
	for p in "${pkgs[@]}"; do
		if [ -n "${HALF[$p]:-}" ]; then half="$half $p is '${HALF[$p]}';"; fi
	done
	if [ -n "$half" ]; then
		half="${half# }"
		FAM_STOPPED[$fam]=1
		differs "packages $fam" "dpkg has left a package unfinished: ${half%;} -- an earlier install was interrupted or failed, and apt is not called for this family until dpkg's database is right. Putting it right is the owner's (sudo dpkg --configure -a finishes an interrupted install)"
		return
	fi

	if [ "$fam" = someip ]; then
		read -r -a ub <<< "$BOOST_UNVERSIONED"
		query_installed "${ub[@]}"
		for p in "${ub[@]}"; do
			if [ -n "${HAVE[$p]:-}" ]; then found="$found $p"; fi
		done
		if [ -n "$found" ]; then
			FAM_STOPPED[$fam]=1
			differs "packages someip" "an unversioned Boost -dev package is installed (${found# }): it and the 1.74 set cannot coexist, and removing a package is the owner's"
			return
		fi
	fi
}

step_family() {
	local fam="$1" ref="PKGS_$1" p v sim rc name
	local -a pkgs=() missing=() names=()
	[ -z "${FAM_STOPPED[$fam]:-}" ] || return 0
	read -r -a pkgs <<< "${!ref}"

	query_installed "${pkgs[@]}"
	for p in "${pkgs[@]}"; do
		if [ -z "${HAVE[$p]:-}" ]; then missing+=("$p"); fi
	done

	if [ "${#missing[@]}" = 0 ]; then
		item ok "packages $fam" "all ${#pkgs[@]} installed"
		if [ "$fam" = core ]; then
			qemu_builds
			item note "$QEMU_PKG build" "installed ${QEMU_INST:-unread}; candidate ${QEMU_CAND:-unread}; nothing of core is missing, so apt is not called"
		fi
		return
	fi

	if [ "$MODE" = check ]; then
		item missing "packages $fam" "${missing[*]}"
	else
		say "packages $fam: missing ${missing[*]}"
		apt_update_once
	fi

	# The installed QEMU is the build the guest images are run on and the one the cloud twin is
	# held to. Its companions (qemu-utils, ipxe-qemu) are installed at the candidate, so a
	# candidate that has moved would leave a mixed set, and moving the installed build is the
	# owner's.
	if [ "$fam" = core ] && [ -n "${HAVE[$QEMU_PKG]:-}" ]; then
		qemu_builds
		if [ -z "$QEMU_CAND" ] || [ "$QEMU_CAND" = "(none)" ]; then
			differs "$QEMU_PKG build" "its candidate cannot be read from apt-cache policy"
			return
		elif [ "$QEMU_CAND" != "$QEMU_INST" ]; then
			differs "$QEMU_PKG build" "installed $QEMU_INST, candidate $QEMU_CAND: the installed build is the one the guest images are run on, and moving it is the owner's"
			return
		fi
		item ok "$QEMU_PKG build" "installed $QEMU_INST is the candidate"
	fi

	if [ "$MODE" = check ]; then
		say "  simulating the install of: ${missing[*]} (with the package lists as they are; apply refreshes them first)"
	else
		say "  simulating the install of: ${missing[*]}"
	fi
	sim=$(LC_ALL=C apt-get -s install --no-install-recommends --no-upgrade "${missing[@]}" 2>&1 < /dev/null); rc=$?
	printf '%s\n' "$sim" | emit
	sim_read "$rc" "$sim" "${missing[@]}"
	if [ -n "$SIM_WHY" ]; then
		differs "packages $fam simulation" "$SIM_WHY"
		return
	fi
	if [ "$MODE" = check ]; then
		say "  apply would install (${#SIM_LIST[@]}): ${SIM_LIST[*]}"
		return
	fi

	say "  installing exactly what the simulation listed (${#SIM_LIST[@]}): ${SIM_LIST[*]}"
	# NEEDRESTART_SUSPEND: where needrestart is installed its apt hook restarts services after any
	# install, and no library is upgraded here, so it has nothing to do and must restart nothing.
	# DPkg::Lock::Timeout: apt-get by itself gives up at once when another apt holds dpkg's lock.
	sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -o DPkg::Lock::Timeout=120 --no-install-recommends --no-upgrade --no-remove --trivial-only "${SIM_LIST[@]}" < /dev/null 2>&1 | emit
	rc="${PIPESTATUS[0]}"
	[ "$rc" = 0 ] || failed "apt-get install for $fam exited $rc"

	for p in "${SIM_LIST[@]}"; do names+=("${p%%=*}"); done
	query_installed "${names[@]}" "${missing[@]}"
	for p in "${SIM_LIST[@]}"; do
		name="${p%%=*}"; v="${p#*=}"
		[ -n "${HAVE[$name]:-}" ] || failed "apt-get returned 0 but $name is not installed"
		[ "${HAVE[$name]}" = "$v" ] || failed "$name is installed at ${HAVE[$name]}, not at the simulated $v"
	done
	for p in "${missing[@]}"; do
		[ -n "${HAVE[$p]:-}" ] || failed "apt-get returned 0 but $p is not installed"
	done
	item ok "packages $fam" "installed ${#SIM_LIST[@]}: ${SIM_LIST[*]}"
}

# ------------------------------------------------------------------ 3. the kvm group

in_group() {  # is the login a member of <group>, by the group database (not this session's groups)
	local g groups
	groups=$(id -nG "$LOGIN" 2>/dev/null)
	for g in $groups; do
		if [ "$g" = "$1" ]; then return 0; fi
	done
	return 1
}

# Read before the first change: there has to be a kvm group for the login to join.
step_kvm_group() {
	if getent group kvm > /dev/null 2>&1; then
		KVM_GROUP=1
	else
		differs "kvm group" "there is no kvm group on this system, and this script does not make one"
	fi
}

step_kvm() {
	local rc
	[ "$KVM_GROUP" = 1 ] || return 0
	if in_group kvm; then
		item ok "kvm group" "the login is a member"
		return
	fi
	if [ "$MODE" = check ]; then
		item missing "kvm group" "the login is not a member; apply adds it (usermod -aG kvm), announced"
		return
	fi
	say "ANNOUNCE: adding the login '$LOGIN' to the group kvm (sudo usermod -aG kvm $LOGIN), so that a guest can start with nobody logged in at the display."
	sudo -n usermod -aG kvm "$LOGIN" < /dev/null 2>&1 | emit
	rc="${PIPESTATUS[0]}"
	[ "$rc" = 0 ] || failed "usermod exited $rc; the login is not in the group kvm"
	in_group kvm || failed "usermod returned 0 but the login is still not in the group kvm"
	say "ANNOUNCE: the login '$LOGIN' is now in the group kvm. A NEW LOGIN is needed before it takes effect; this session keeps its old groups."
	item ok "kvm group" "the login was added; a new login is needed"
}

# ------------------------------------------------------------------ 4. Docker, as installed

step_docker() {
	local u en ac states="" bad="" n="not counted" out rc group running=""
	for u in docker.service docker.socket containerd.service; do
		unit_enabled "$u"; en="$UNIT_WORD"
		unit_active "$u"; ac="$UNIT_WORD"
		states="$states $u=$en/$ac"
		if [ "$en" != enabled ]; then bad="$bad $u is $en;"; fi
		if [ "$u" = docker.service ]; then running="$ac"; fi
	done
	query_installed docker.io
	if [ -n "${HALF[docker.io]:-}" ]; then
		bad="$bad dpkg has docker.io in state '${HALF[docker.io]}';"
	elif [ -z "${HAVE[docker.io]:-}" ]; then
		bad="$bad docker.io is not installed;"
	fi
	if ! grep -q '"runtimes"' "$ETC/docker/daemon.json" 2>/dev/null || ! grep -q '"nvidia"' "$ETC/docker/daemon.json" 2>/dev/null; then
		bad="$bad the nvidia runtime is not in daemon.json;"
	fi
	# Only a running service is asked: a connection to the socket would start a stopped one. A
	# daemon that is wedged never answers, so the question is given 20 s (and 5 more before
	# SIGKILL). The timeout sits inside sudo, where it signals the client itself; outside, it
	# would depend on sudo passing a signal on to a command that is root's.
	if [ "$SUDO_OK" = 1 ] && [ "$running" = active ]; then
		out=$(sudo -n timeout -k 5 20 docker ps -a -q 2>/dev/null < /dev/null); rc=$?
		case "$rc" in
			0)
				n=0
				while IFS= read -r u; do
					if [ -n "$u" ]; then n=$((n + 1)); fi
				done <<< "$out" ;;
			124|137) n="not counted (no answer in 20 s)" ;;
		esac
	fi
	if in_group docker; then group="the login is in the docker group"; else group="the login is not in the docker group, and this script adds nobody"; fi
	if [ -z "$bad" ]; then
		item ok "docker" "as installed: docker.io ${HAVE[docker.io]};$states; nvidia runtime in daemon.json; containers: $n; $group"
	else
		bad="${bad# }"
		differs "docker" "not as installed: ${bad%;} (units:$states; containers: $n) -- left as it is: Docker is the owner's"
	fi
}

# ------------------------------------------------------------------ 5 to 8. asserted, never changed

step_nvpmodel() {
	local out rc line mode=""
	out=$(nvpmodel -q 2>/dev/null < /dev/null); rc=$?
	while IFS= read -r line; do
		line="${line//[[:space:]]/}"
		if [[ "$line" =~ ^[0-9]+$ ]]; then mode="$line"; fi
	done <<< "$out"
	if [ "$rc" != 0 ] || [ -z "$mode" ]; then
		differs "nvpmodel" "the mode cannot be read (the query exited $rc)"
	elif [ "$mode" = "$WANT_NVPMODEL" ]; then
		item ok "nvpmodel" "mode $mode"
	else
		differs "nvpmodel" "mode $mode, not mode $WANT_NVPMODEL, the mode this project's runs assume -- asserted and never changed here: the mode is the owner's"
	fi
}

step_governor() {
	local f p n=0 other="" died=""
	for f in "$SYSR"/devices/system/cpu/cpufreq/policy*/scaling_governor; do
		[ -r "$f" ] || continue
		first_line "$f"
		n=$((n + 1))
		if [ "$FL" != "$WANT_GOVERNOR" ]; then
			p="${f%/scaling_governor}"
			other="$other ${p##*/}=$FL"
			if [ "$FL" = performance ]; then died=" 'performance' at rest means a run died without restoring it."; fi
		fi
	done
	if [ "$n" = 0 ]; then
		differs "governor" "no cpufreq policy could be read"
	elif [ -z "$other" ]; then
		item ok "governor" "$WANT_GOVERNOR on $n policies"
	else
		differs "governor" "at rest every policy reads $WANT_GOVERNOR, as shipped, and here:$other.$died Asserted and never written here: the harnesses pin it for a run and restore it"
	fi
}

step_gdm() {
	local f="$ETC/gdm3/custom.conf"
	if [ ! -r "$f" ]; then
		item note "auto-login" "gdm3/custom.conf cannot be read"
		differs "gdm Xorg" "gdm3/custom.conf cannot be read"
		return
	fi
	if grep -Eiq '^[[:space:]]*(AutomaticLoginEnable|TimedLoginEnable)[[:space:]]*=[[:space:]]*(true|1)[[:space:]]*$' "$f" 2>/dev/null; then
		item note "auto-login" "ON in gdm3/custom.conf; the owner's decision is no auto-login, and this script never changes it"
	else
		item note "auto-login" "off: the board rests at the greeter; this script never changes it"
	fi
	if grep -Eq '^[[:space:]]*WaylandEnable[[:space:]]*=[[:space:]]*false[[:space:]]*$' "$f" 2>/dev/null; then
		item ok "gdm Xorg" "WaylandEnable=false is set"
	else
		differs "gdm Xorg" "WaylandEnable=false is not set in gdm3/custom.conf, so the desktop session may not be Xorg -- asserted and never written here: the edit is the owner's"
	fi
}

step_haltpoll() {
	first_line "$SYSR/module/kvm/parameters/halt_poll_ns"
	if [ "$FL" = "$WANT_HALT_POLL" ]; then
		item ok "halt_poll_ns" "$FL"
	else
		differs "halt_poll_ns" "kvm's halt_poll_ns reads ${FL:-nothing}, not $WANT_HALT_POLL -- asserted and never set here: a harness that changes it restores it"
	fi
}

# ------------------------------------------------------------------ 9. the bridge

# Read before the first change: with --bridge and no bridge yet, the script apply would run has
# to be there.
step_bridge_script() {
	[ "$WANT_BRIDGE" = 1 ] || return 0
	if [ -e "$SYSR/class/net/br0" ] && [ -e "$SYSR/class/net/tap-qnx" ]; then return 0; fi
	[ ! -r "$BRIDGE_SCRIPT" ] || return 0
	BRIDGE_STOPPED=1
	differs "bridge" "br0 or tap-qnx is missing, and setup-bridge-orin.sh is not beside this script: --bridge has nothing to run"
}

step_bridge() {
	local rc br=absent tap=absent
	[ "$BRIDGE_STOPPED" = 0 ] || return 0
	if [ -e "$SYSR/class/net/br0" ]; then br=present; fi
	if [ -e "$SYSR/class/net/tap-qnx" ]; then tap=present; fi
	if [ "$WANT_BRIDGE" = 0 ]; then
		item note "bridge" "br0 $br, tap-qnx $tap; it is not made at boot, and no unit is installed for it (--bridge makes it once)"
		return
	fi
	if [ "$br" = present ] && [ "$tap" = present ]; then
		item ok "bridge" "br0 and tap-qnx exist"
		return
	fi
	if [ "$MODE" = check ]; then
		item missing "bridge" "br0 $br, tap-qnx $tap; apply --bridge runs setup-bridge-orin.sh once"
		return
	fi
	say "bridge: running setup-bridge-orin.sh once. Its output is not shown and not logged: it prints the tap's MAC."
	sudo -n bash "$BRIDGE_SCRIPT" < /dev/null > /dev/null 2>&1; rc=$?
	[ "$rc" = 0 ] || failed "setup-bridge-orin.sh exited $rc; its output was not kept, so run it by hand to read it"
	if [ ! -e "$SYSR/class/net/br0" ] || [ ! -e "$SYSR/class/net/tap-qnx" ]; then
		failed "setup-bridge-orin.sh returned 0 but br0 or tap-qnx is still missing"
	fi
	item ok "bridge" "br0 and tap-qnx were made; they do not survive a reboot"
}

# ------------------------------------------------------------------ 10. reported, never changed

step_notes() {
	local d n kind v l first=1 count=0 net="" a b

	if [ -d "$SYSR/module/br_netfilter" ]; then v=loaded; else v="not loaded"; fi
	first_line "$PROC/sys/net/bridge/bridge-nf-call-iptables"
	if [ -e "$ETC/modules-load.d/nemoclaw.conf" ]; then a=present; else a=absent; fi
	if [ -e "$ETC/sysctl.d/99-nemoclaw.conf" ]; then b=present; else b=absent; fi
	item note "br_netfilter" "$v; bridge-nf-call-iptables ${FL:-absent}; nemoclaw.conf $a; 99-nemoclaw.conf $b"

	unit_enabled auditd.service; a="$UNIT_WORD"
	unit_active auditd.service; b="$UNIT_WORD"
	item note "auditd" "$a, $b"

	if [ -r "$PROC/swaps" ]; then
		while IFS= read -r l; do
			if [ "$first" = 1 ]; then first=0; continue; fi
			if [ -n "$l" ]; then count=$((count + 1)); fi
		done < "$PROC/swaps"
		if [ "$count" = 0 ]; then item note "swap" "none"; else item note "swap" "$count active"; fi
	else
		item note "swap" "unread"
	fi

	query_installed needrestart
	if [ -n "${HAVE[needrestart]:-}" ]; then
		item note "needrestart" "installed; apply suspends it for its own install, so it restarts no service"
	else
		item note "needrestart" "not installed"
	fi

	unit_enabled apt-daily.timer; a="$UNIT_WORD"
	unit_enabled apt-daily-upgrade.timer; b="$UNIT_WORD"
	item note "apt timers" "apt-daily.timer $a, apt-daily-upgrade.timer $b"

	# The interfaces that are devices, by what sysfs says of each: its state and its carrier.
	for d in "$SYSR"/class/net/*; do
		[ -e "$d/device" ] || continue
		n="${d##*/}"
		if [ -d "$d/phy80211" ]; then kind=wireless; else kind=wired; fi
		first_line "$d/operstate"; v="$FL"
		first_line "$d/carrier"
		net="${net:+$net; }$n $kind operstate=${v:-unread} carrier=${FL:-unread}"
	done
	item note "network" "${net:-no device interface}"

	first_line "$PROC/sys/kernel/panic"; v="$FL"
	first_line "$PROC/sys/kernel/panic_on_oops"
	item note "kernel.panic" "${v:-unread}; kernel.panic_on_oops ${FL:-unread}"
}

# ------------------------------------------------------------------ main

case "${1:-}" in
	check|apply) MODE="$1"; shift ;;
esac
for a in "$@"; do
	case "$a" in
		--bridge) WANT_BRIDGE=1 ;;
		-h|--help)
			echo "$USAGE"
			echo "  check (the default) reads and reports; apply installs what is missing. See the header of this file."
			exit 0 ;;
		--set-xorg)
			echo "provision-orin-r39.sh: there is no --set-xorg: gdm's Xorg setting is asserted and never written by this script" >&2
			exit 64 ;;
		core|build|someip|cuda)
			case " $SELECTED " in
				*" $a "*) ;;
				*) SELECTED="$SELECTED $a" ;;
			esac ;;
		*)
			echo "provision-orin-r39.sh: unknown argument: $a" >&2
			echo "$USAGE" >&2
			exit 64 ;;
	esac
done
[ -n "$SELECTED" ] || SELECTED="$DEFAULT_FAMILIES"

LOGIN=$(id -un 2>/dev/null)
UID_NOW=$(id -u 2>/dev/null)
if [ -z "$LOGIN" ] || [ -z "$UID_NOW" ] || [ "$UID_NOW" = 0 ]; then
	echo "provision-orin-r39.sh: refused: run it as the login that will run the guests, never as root (it calls sudo -n itself)" >&2
	exit 2
fi

sel=""
for fam in $FAMILIES; do
	case " $SELECTED " in *" $fam "*) sel="${sel:+$sel }$fam" ;; esac
done
if [ "$WANT_BRIDGE" = 1 ]; then bridge_word=asked; else bridge_word="not asked"; fi
# apply is not stopped by a lost session: a broken pipe or a hangup in the middle of an install
# would leave packages half configured, with nothing in the log to say so. Both are ignored from
# here on, and every command apply starts inherits that.
[ "$MODE" = check ] || trap '' PIPE HUP
say "provision-orin-r39.sh $MODE; families: $sel; bridge: $bridge_word"
[ "$ETC" = /etc ] || say "WARNING: ETC_ROOT overridden to $ETC -- test use only"
[ "$SYSR" = /sys ] || say "WARNING: SYS_ROOT overridden to $SYSR -- test use only"
[ "$PROC" = /proc ] || say "WARNING: PROC_ROOT overridden to $PROC -- test use only"
[ "$BRIDGE_SCRIPT" = "$here/setup-bridge-orin.sh" ] || say "WARNING: BRIDGE_SCRIPT overridden to $BRIDGE_SCRIPT -- test use only"

step_release
[ "$MODE" = check ] || open_log
step_sudo
step_stick
# Everything that is only asserted, before the first change: a stop here leaves the package
# lists, the packages and the groups as they were.
step_docker
step_nvpmodel
step_governor
step_gdm
step_haltpoll
step_kvm_group
step_bridge_script
for fam in $sel; do step_family_state "$fam"; done
# The changes.
for fam in $sel; do step_family "$fam"; done
case " $sel " in
	*" cuda "*) ;;
	*) item note "cuda" "not looked at: the family is opt-in (name it: apply cuda)" ;;
esac
step_kvm
step_bridge
step_notes
finish 0
