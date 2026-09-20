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
QT_WIN="$(printf '%s' "$QNX_TARGET" | sed 's|^/\([a-z]\)/|\U\1:/|')"
BSP_WIN="$(printf '%s' "$BSP" | sed 's|^/\([a-z]\)/|\U\1:/|')"
export MKFS_PATH="${BSP_WIN};${QT_WIN}/aarch64le;${QT_WIN}/aarch64le/boot/sys;${QT_WIN};."

cd "$BUILD_DIR"
mkifs -r "$QT_WIN" "$BUILDFILE" "$OUT"

echo "--- acceptance (exit code is not evidence) ---"
dumpifs "$OUT" | grep -E 'startup\.\*|proc/boot/qnx-|proc/boot/cyclone'
echo "startup entry must be 40081ab8 (ours), not 40081da8 (SDP, hangs under KVM)"
