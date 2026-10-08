#!/usr/bin/env bash
# build-fma.sh -- build the FMA load, fma.cu, on the board (Phase 3b / A6, 2026-10-05).
#
# WHY THIS EXISTS. The harnesses that load the GPU start ~/gpuload/fma, and until now that binary
# was built by hand from the line in this directory's README, with an nvcc path that was the
# board's at the time. This is that line as a script:
#     nvcc -O3 -arch=sm_87 -o ~/gpuload/fma fma.cu
# with the one nvcc found under /usr/local/cuda* (or NVCC=<path>), by its path: no nvcc is taken
# from PATH, none is a refusal by name, and two different ones are not chosen between.
#
# fma IS NEVER STARTED HERE. It has no usage text and no version: started without arguments it
# loads the GPU for half a minute, and the first GPU load on a freshly installed board is not
# this script's to start. That the binary runs is not shown here.
#
# OUT: $OUT (~/gpuload/fma); $OUT.sha256 in the form `sha256sum -c` reads from that directory;
# and BUILD-INFO beside them with the source's sha256, the flags, nvcc and the binary's sha256.
# An earlier run's binary, sha256 and BUILD-INFO are removed before the compile, so a failed
# compile leaves none of the three. Exit 0, 1, or 75 when another run is still alive.
#
# THE RULES OF lib-build.sh APPLY: the compile runs under the memory cap or not at all; a
# done-file holds the exit status (~/builds/build-fma.done). It is one compiler call, so there
# is no job count to choose.
set -euo pipefail

OUT="${OUT:-$HOME/gpuload/fma}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAGS=(-O3 -arch=sm_87)

# shellcheck source=lib-build.sh
. "$here/lib-build.sh"
[ "${BUILD_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-build.sh did not load" >&2; exit 1; }
b_begin build-fma

command -v sha256sum >/dev/null || die "missing: sha256sum"
[ -r "$here/fma.cu" ] || die "no fma.cu beside this script"
b_find_nvcc
JOBS=1
B_JOBS_WHY="one compiler call"
b_cap_check

dir="$(dirname "$OUT")"
BI="$dir/BUILD-INFO"
mkdir -p "$dir"
b_drop_info "$BI"
rm -f "$OUT" "$OUT.sha256"

b_step "$dir/fma-build.log" "the compile of fma.cu" "$NVCC" "${FLAGS[@]}" -o "$OUT" "$here/fma.cu"
[ -s "$OUT" ] || die "nvcc ended well and left no $OUT -- see $dir/fma-build.log"

sum="$(b_sha "$OUT")"
echo "$sum  ${OUT##*/}" > "$OUT.sha256"
{
	echo "fma from fma.cu sha256 $(b_sha "$here/fma.cu")"
	echo "flags ${FLAGS[*]}"
	b_nvcc_line
	echo "built $(date -u +%FT%TZ)"
	echo "fma sha256 $sum"
	b_info_common
} > "$BI.tmp"
mv -f "$BI.tmp" "$BI"
cat "$BI"
