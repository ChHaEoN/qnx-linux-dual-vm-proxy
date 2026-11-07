#!/usr/bin/env bash
# build-monitor-native.sh -- build the SAME monitor source for the host.
#
# WHY THIS EXISTS. run-ladder.sh's arms A and B need a server on the host side,
# and the whole point of the ladder is that all arms run the SAME server
# program -- otherwise a difference between arms could be a difference between
# programs. Until 2026-09-21 this binary existed only on the Orin, built by
# hand, with the command line recorded in prose in a results file. Nothing in
# the repo built it, so a second host could not reproduce it. That is what this
# fixes.
#
# DO NOT USE ipc-test/qnx-safety-monitor/Makefile for this. That Makefile is
# qcc with LDFLAGS=-lsocket, which is QNX-only: on Linux the socket calls are
# in libc and -lsocket fails the link. The QNX Makefile is right for the guest
# binary and wrong for this one.
#
# The source is pure POSIX -- verified by reading, not by trusting the comment:
# monitor.c, frame.h and frame_io.h contain no ClockCycles, MsgSend, name_attach,
# devctl, iofunc, dispatch_, resmgr, neutrino, ThreadCtl or InterruptAttach in
# code, only in prose. That is the reason one source can serve two targets, and
# the reason the native control arm is a valid control at all.
#
# THE EXTENSION-KIND SWITCH (sdv Phase 2; the kind 4 wire specification,
# section 11). MONITOR_EXT_KINDS=0x10 builds the vss monitor instead: monitor.c
# with MONITOR_EXT_KINDS defined, the generated contract headers vss_contract.h
# and vss_profiles.h from MONITOR_VSS_GEN (default: the in-tree sdv-out/gen that
# sdv/vss/generate.py writes), and -ffp-contract=off (Phase 2 design decision
# e; the Makefile's `make vss` passes it too). That is not the ladder's host
# arm, so it is refused at the default OUT, and its source-sha256 also covers
# both headers, the switch value and the extra flag. MONITOR_VSS_GEN without
# MONITOR_EXT_KINDS is refused rather than ignored. With neither set, the gcc
# line and the hash are exactly what they were before the switch existed.
#
# THE CTL MONITOR (sdv Phase 8, WP1b). MONITOR_EXT_KINDS=0x14 builds the ctl
# monitor (kinds 2 and 4; the guest's build is `make ctl`), and 0x1C reaches
# monitor.c's not-implemented #error: for both, the kind 2 contract vss_ctl.h,
# which sdv/vss/generate.py writes beside the other two, is taken from
# MONITOR_VSS_GEN after them, so the source-sha256 covers it too, and a
# generation without it is refused before any compiler runs. 0x10's gcc line
# and hash are what they were before kind 2 existed. A ctl monitor is not the
# ladder's host arm either: give it its own OUT (Phase 8 uses
# OUT=$HOME/aw/monitor-ctl).
#
# BOTH ARE READ FROM THE ENVIRONMENT, as OUT, CC and FORCE are, so a harness
# that runs this script hands it whatever its own environment holds. They
# carry this project's prefix for that reason: a generic EXT_KINDS or VSS_GEN
# left in a harness's environment (VSS_GEN is also the Makefile's variable for
# `make vss`) is not read here, so it can neither switch a harness's host arm
# to the vss monitor nor make its default build refuse.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"

SRC="${repo}/ipc-test/qnx-safety-monitor/monitor.c"
INC="${repo}/ipc-test/common"
# OD12 (2026-09-22): the shm transport's region is mapped by a separate file per
# target -- this one on the host (a /dev/shm file), shm_map_qnx.c in the guest
# (QEMU's ivshmem device, configured through ECAM). monitor.c calls shm_map() and never learns
# which one it got.
MAP="${INC}/shm_map_posix.c"
IVC="${INC}/ivshm_client.c"   # the host side's ivshmem peer (the notified variant)
OUT="${OUT:-${HOME}/ladder/monitor-native}"
CC="${CC:-gcc}"

MONITOR_EXT_KINDS="${MONITOR_EXT_KINDS:-}"
GEN_HDRS=()
if [ -n "${MONITOR_EXT_KINDS}" ]; then
	case "${MONITOR_EXT_KINDS}" in
		0x10|0x14|0x1C) ;;
		*)
			echo "ERROR: MONITOR_EXT_KINDS=${MONITOR_EXT_KINDS}: monitor.c takes 0x10 (vss), 0x14 (ctl) or 0x1C (gap), spelt so." >&2
			exit 1 ;;
	esac
	MONITOR_VSS_GEN="${MONITOR_VSS_GEN:-${repo}/sdv-out/gen}"
	GEN_HDRS=("${MONITOR_VSS_GEN}/vss_contract.h" "${MONITOR_VSS_GEN}/vss_profiles.h")
	case "${MONITOR_EXT_KINDS}" in
		0x14|0x1C) GEN_HDRS+=("${MONITOR_VSS_GEN}/vss_ctl.h") ;;   # kind 2's contract, after kind 4's two
	esac
	if [ "$(realpath -m -- "${OUT}")" = "$(realpath -m -- "${HOME}/ladder/monitor-native")" ]; then
		echo "ERROR: MONITOR_EXT_KINDS=${MONITOR_EXT_KINDS} builds the vss or ctl monitor, not the ladder's host arm, so it" >&2
		echo "       may not take the default OUT (${HOME}/ladder/monitor-native). Give it its own OUT." >&2
		exit 1
	fi
elif [ -n "${MONITOR_VSS_GEN:-}" ]; then
	echo "ERROR: MONITOR_VSS_GEN is set but MONITOR_EXT_KINDS is not, so this would build the default monitor." >&2
	echo "       Set MONITOR_EXT_KINDS=0x10 for the vss monitor, or unset MONITOR_VSS_GEN." >&2
	exit 1
fi

for f in "${SRC}" "${INC}/frame.h" "${INC}/frame_io.h" "${INC}/shm_chan.h" "${INC}/shm_map.h" "${MAP}" "${IVC}" "${INC}/ivshm_client.h"; do
	[ -r "$f" ] || { echo "ERROR: missing source: $f" >&2; exit 1; }
done
for f in ${GEN_HDRS[@]+"${GEN_HDRS[@]}"}; do
	[ -r "$f" ] || { echo "ERROR: missing generated header: $f -- generate it with sdv/vss/generate.py, or point MONITOR_VSS_GEN at its output" >&2; exit 1; }
done

# Refuse to build if a QNX-only symbol has appeared in the shared source since
# this was written. Silently producing a binary that no longer matches the
# guest's would invalidate the control without anything failing.
if grep -nE '^[^*/]*\b(ClockCycles|MsgSend|MsgReceive|MsgReply|name_attach|name_open|devctl|iofunc_|dispatch_|resmgr_|ThreadCtl|InterruptAttach|mmap_device_memory|pci_device_[a-z_]+)\b' \
	"${SRC}" "${INC}/frame.h" "${INC}/frame_io.h" "${INC}/shm_chan.h" >/dev/null 2>&1; then
	echo "ERROR: a QNX-only symbol appeared in the shared source." >&2
	echo "       The host and guest servers would no longer be the same program," >&2
	echo "       so the ladder's arms would not be comparable. Fix the source or" >&2
	echo "       stop calling this a control." >&2
	exit 1
fi

# ONE SOURCE PER BINARY PATH (2026-09-23). The ladder runs ${OUT} as its host
# arms A and B and compares them with the guest's monitor in arm D, so the two
# must be the same program. The VLM service arm (OD13) changed monitor.c while
# the published guest images keep their old monitor; rebuilding the default
# path from the new source would then pair a new host monitor with an old
# guest one, and nothing downstream would notice. So the source that built a
# binary is recorded beside it, and a rebuild from a different source is
# refused unless FORCE=1 -- build a service-arm monitor to its own OUT instead.
SIDE="${OUT}.source-sha256"
# With the switch on, the generated headers follow the eight sources and one
# line names the switch value and the extra flag (the -I path is not hashed;
# the headers' bytes are). With it off the input is the eight sources alone.
want_src="$( {
	cat "${SRC}" "${MAP}" "${IVC}" "${INC}/frame.h" "${INC}/frame_io.h" "${INC}/shm_chan.h" \
		"${INC}/shm_map.h" "${INC}/ivshm_client.h"
	if [ -n "${MONITOR_EXT_KINDS}" ]; then
		cat "${GEN_HDRS[@]}"
		printf 'MONITOR_EXT_KINDS=%s -ffp-contract=off\n' "${MONITOR_EXT_KINDS}"
	fi
} | sha256sum | cut -d' ' -f1)"
if [ -e "${OUT}" ] && [ "${FORCE:-0}" != 1 ]; then
	have_src="$(cat "${SIDE}" 2>/dev/null || echo unrecorded)"
	if [ "${have_src}" != "${want_src}" ]; then
		echo "ERROR: ${OUT} exists and was built from other source (${have_src:0:16})." >&2
		echo "       Rebuilding it from this tree (${want_src:0:16}) would change the ladder's" >&2
		echo "       host arms under a guest image that still runs the old monitor. Build to" >&2
		echo "       another OUT, or pass FORCE=1 if the guest image matches this source." >&2
		exit 1
	fi
fi

mkdir -p "$(dirname "${OUT}")"
if [ -z "${MONITOR_EXT_KINDS}" ]; then
	set -x
	"${CC}" -O2 -std=gnu99 -Wall -Wextra -I "${INC}" -o "${OUT}" "${SRC}" "${MAP}" "${IVC}"
	set +x
else
	# The switch-on line: today's, plus the switch, the contract's directory and
	# the flag the source-sha256 input above names. Keep the two in step.
	set -x
	"${CC}" -O2 -std=gnu99 -Wall -Wextra -I "${INC}" -o "${OUT}" "${SRC}" "${MAP}" "${IVC}" -DMONITOR_EXT_KINDS="${MONITOR_EXT_KINDS}" -I "${MONITOR_VSS_GEN}" -ffp-contract=off
	set +x
fi
echo "${want_src}" > "${SIDE}"

echo
echo "built:  ${OUT}"
echo "sha256: $(sha256sum "${OUT}" | cut -d' ' -f1)"
echo "source: $(sha256sum "${SRC}" | cut -d' ' -f1)  monitor.c"
echo "source: $(sha256sum "${MAP}" | cut -d' ' -f1)  $(basename "${MAP}")"
echo "source: $(sha256sum "${IVC}" | cut -d' ' -f1)  $(basename "${IVC}")"
for f in ${GEN_HDRS[@]+"${GEN_HDRS[@]}"}; do
	echo "source: $(sha256sum "$f" | cut -d' ' -f1)  $(basename "$f")"
done
[ -z "${MONITOR_EXT_KINDS}" ] || echo "switch: MONITOR_EXT_KINDS=${MONITOR_EXT_KINDS} -ffp-contract=off  (the guest's build: make $([ "${MONITOR_EXT_KINDS}" = 0x14 ] && echo ctl || echo vss))"
echo "tree:   ${want_src}  (recorded in $(basename "${SIDE}"))"
echo
echo "The guest runs this same monitor.c, cross-compiled with qcc. The binaries"
echo "differ; the program does not."
