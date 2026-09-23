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

for f in "${SRC}" "${INC}/frame.h" "${INC}/frame_io.h" "${INC}/shm_chan.h" "${INC}/shm_map.h" "${MAP}" "${IVC}" "${INC}/ivshm_client.h"; do
	[ -r "$f" ] || { echo "ERROR: missing source: $f" >&2; exit 1; }
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
want_src="$(cat "${SRC}" "${MAP}" "${IVC}" "${INC}/frame.h" "${INC}/frame_io.h" "${INC}/shm_chan.h" \
	"${INC}/shm_map.h" "${INC}/ivshm_client.h" | sha256sum | cut -d' ' -f1)"
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
set -x
"${CC}" -O2 -std=gnu99 -Wall -Wextra -I "${INC}" -o "${OUT}" "${SRC}" "${MAP}" "${IVC}"
set +x
echo "${want_src}" > "${SIDE}"

echo
echo "built:  ${OUT}"
echo "sha256: $(sha256sum "${OUT}" | cut -d' ' -f1)"
echo "source: $(sha256sum "${SRC}" | cut -d' ' -f1)  monitor.c"
echo "source: $(sha256sum "${MAP}" | cut -d' ' -f1)  $(basename "${MAP}")"
echo "source: $(sha256sum "${IVC}" | cut -d' ' -f1)  $(basename "${IVC}")"
echo "tree:   ${want_src}  (recorded in $(basename "${SIDE}"))"
echo
echo "The guest runs this same monitor.c, cross-compiled with qcc. The binaries"
echo "differ; the program does not."
