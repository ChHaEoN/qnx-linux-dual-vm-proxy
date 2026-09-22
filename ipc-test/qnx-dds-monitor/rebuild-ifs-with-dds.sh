#!/usr/bin/env bash
# rebuild-ifs-with-dds.sh -- rebuild ONLY the IFS, with our own startup-qemu-virt
# and the DDS monitor staged in. Does not touch disk-qemu.
#
# WHY IFS-ONLY. `mkqnximage --build` regenerates the disk as well, and on this
# tree that fails ("Bad superblock signature in output/system.part"). It also
# pulls startup-qemu-virt from the SDP, which is the SHIPPED binary -- and that
# one hangs under KVM after 17 bytes ("FOUND GICv3 ITS"), the historic
# GICv3/NISV defect. mkifs alone avoids both problems.
#
# THE SEARCH-PATH TRICK. ifs.build resolves `startup-qemu-virt` by name through
# [search=${MKFS_PATH}]. Putting our rebuilt startup's directory FIRST makes
# mkifs pick ours (614,992 bytes) over the SDP's (1,599,632).
#
# EXIT CODE PROVES NOTHING. ifs.build carries [+optional], so an unresolved file
# is silently skipped and mkifs still exits 0. Verify by dumpifs instead:
#   startup entry 40081ab8 = ours;  40081da8 = the SDP's, which will hang.
set -euo pipefail

: "${QNX_TARGET:?source qnxsdp-env.sh first}"
BSP="${BSP:?set BSP to the dir holding the rebuilt startup-qemu-virt}"
BUILD_DIR="${BUILD_DIR:-qnx-safety-vm}"
BUILDFILE="${BUILDFILE:-output/build/ifs.build}"
OUT="${OUT:?set OUT to the output image path}"

# Windows form with semicolons: mkifs.exe is a native PE32+ binary and does not
# understand POSIX paths or colon separators.
#
# Converted in pure bash, not sed. FOUND 2026-09-22: after qnxsdp-env.sh the
# SDP's own msys-linked host tools come first on PATH, and when Git Bash starts
# one of them, any argument containing a glob character -- ( * ? [ { -- loses its
# backslashes on the way in. The sed expression's \( \) arrived as ( ), never
# matched, and "/c/Users/..." passed through unconverted; mkifs then said "Host
# file 'raw.boot' not available" with raw.boot on the search path. (A first note
# here blamed the SDP's sed for lacking \U. It has it; a review showed the
# argument never reached it intact.) Keep backslashes out of any pattern handed
# to an SDP tool below.
win_path() {
	local p="$1" d
	case "$p" in
		/[a-zA-Z]/*) d="${p:1:1}"; printf '%s:%s' "${d^^}" "${p:2}" ;;
		*) printf '%s' "$p" ;;
	esac
}
QT_WIN="$(win_path "$QNX_TARGET")"
BSP_WIN="$(win_path "$BSP")"
# Each path on its own, and it must be drive-letter form: a POSIX or relative
# BSP entry is unreadable to mkifs.exe, and mkifs would then fall through to the
# SDP's startup-qemu-virt -- the one that hangs under KVM. (The first version of
# this guard looked only at the first character of the two paths joined.)
for p in "$QT_WIN" "$BSP_WIN"; do
	case "$p" in
		[A-Za-z]:/*) ;;
		*) echo "FATAL: not an absolute Windows path, mkifs.exe cannot use it: $p" >&2; exit 1 ;;
	esac
done
export MKFS_PATH="${BSP_WIN};${QT_WIN}/aarch64le;${QT_WIN}/aarch64le/boot/sys;${QT_WIN};."

cd "$BUILD_DIR"
# A build file may embed its own build time from BUILD_DATE_FILE (relative to
# BUILD_DIR). Written here, per build, so an image never carries the date of
# whichever earlier build last touched a shared file.
if [ -n "${BUILD_DATE_FILE:-}" ]; then
	date -u +%Y-%m-%dT%H:%M:%SZ > "$BUILD_DATE_FILE"
fi
mkifs -r "$QT_WIN" "$BUILDFILE" "$OUT"

echo "--- acceptance (exit code is not evidence) ---"
dumpifs "$OUT" | grep -E 'startup[.][*]|proc/boot/qnx-|proc/boot/cyclone'
entry="$(dumpifs "$OUT" | awk '$4 == "startup.*" { print $3 }')"
if [ "$entry" != 40081ab8 ]; then
	echo "FATAL: startup entry is '$entry', not 40081ab8 -- this image carries a startup that is not ours" >&2
	exit 1
fi
echo "startup entry 40081ab8: ours (40081da8 would be the SDP's, which hangs under KVM)"
