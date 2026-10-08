#!/usr/bin/env bash
# build-llama.sh -- build llama.cpp with CUDA on the board, at the pinned commit: llama-server,
# llama-cli and llama-bench (Phase 3b / A6, 2026-10-05).
#
# WHAT THE EDGE-LLM ARM RUNS. The harnesses in this directory start
# ~/llama.cpp/build/bin/llama-server, llama-cli and llama-bench, and until now nothing in the
# repo built them: the commit and the flags were prose in a held record. This is that build.
#
# ~/llama.cpp MUST STAY A GIT CHECKOUT. vlm_stamp.py and characterize-load.sh read the commit a
# run used with `git -C ~/llama.cpp log -1`, so the source comes by `git clone` and is never
# replaced by an archive. A directory in its place that is not a checkout is left alone and the
# script stops. The commit is checked out and then READ BACK: a HEAD that is not the pin is
# refused before anything is configured. How many tracked files differ from the commit is
# counted into BUILD-INFO, so a patched tree cannot carry the pin's name unnoticed.
#
# THE FLAGS: -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DLLAMA_CURL=OFF, Release. 87 is the
# Orin's GPU; no model is fetched by the binaries, so no curl. The CUDA compiler is the one nvcc
# under /usr/local/cuda* (or NVCC=<absolute path>), handed to cmake by its path with the toolkit
# directory it sits in: no nvcc is taken from PATH, and none is a refusal by name.
#
# THE WEB UI IS NOT FETCHED: -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_UI=OFF. At the pin,
# building llama-server also builds tools/ui, whose step (scripts/ui-assets.cmake) would, with
# the first of the two left on as it is by default, download the web UI's files from
# huggingface.co while the build runs and embed what came: a version it works out, else
# `latest`, and nothing at all, with a warning and no error, when the download fails. The
# commit and the flags would then not say what llama-server holds, and two builds of one commit
# could differ. The harnesses use the server's HTTP API only, so the UI is left out. With both
# off that step still embeds an index.html it finds in tools/ui/dist of the source, else of the
# build tree (where an earlier build that did fetch leaves one); BUILD-INFO says which of
# these was there. Read from the pin's files, not run: that the server builds without the UI's
# files, and answers the harnesses without them, is not shown here.
#
# IF CMAKE CANNOT FIND A CUDA COMPONENT, the script reads cmake's log and names what it calls
# missing. The board's CUDA packages are three on purpose (the compiler, the runtime's and
# cuBLAS's dev files); whether they are enough for cmake's toolkit search is not known until
# this has run there. The set is then widened by the name printed here, not by the full toolkit.
# The names are cmake's: an optional package it did not find is among them, and which of them
# is a CUDA component is the reader's to tell. A configure in which the kernel killed for
# memory is reported as that and not as missing components: a check that was killed reads, to
# cmake, as something that is not there.
#
# NOTHING BUILT IS RUN, not for a version string either: a CUDA build may initialise CUDA before
# it reads its arguments, and the first GPU load on a freshly installed board is not this
# script's to start. That the binaries load a model is not shown here.
#
# NEEDS: git, cmake (3.15 or newer), make, g++, systemd-run, flock, and nvcc with the CUDA dev
# files (scripts/orin/provision-orin-r39.sh apply cuda). It installs nothing itself.
#
# OUT: ~/llama.cpp/build/bin/llama-server, llama-cli, llama-bench, and BUILD-INFO beside them:
# the commit, the flags, what web UI was there to embed, nvcc, the compiler, the sha256 of each
# binary and of each shared library the build put beside them, and the largest memory peak of a
# build step. Exit 0, 1, or 75 when another run is still alive.
#
# AN EARLIER RUN'S THREE BINARIES ARE REMOVED before the first build step, so each is linked by
# this run or is missing at the end: a run that was cut in its last link leaves a binary that
# is not empty and that make takes as built. The rest of ~/llama.cpp/build is make's to judge;
# after a run that DIED, remove that directory before the next run (lib-build.sh says why).
#
# THE RULES OF ../gpu-concurrency/lib-build.sh APPLY: JOBS defaults to 2 on a host with under
# 8 GB and no swap; every step runs under the memory cap or not at all; a done-file holds the
# exit status (~/builds/build-llama.done). CUDA sources compile slowly and their memory use on
# this board is not known until a first build's BUILD-INFO has said what its steps peaked at:
# start it detached, and with somebody who can reach the board.
set -euo pipefail

LLAMA_COMMIT="${LLAMA_COMMIT:-e6ab7c1a41054a888ada952eab4c886444c2f5ad}"
URL="${LLAMA_URL:-https://github.com/ggml-org/llama.cpp.git}"
SRC="${SRC:-$HOME/llama.cpp}"
BUILD="$SRC/build"          # not settable: the harnesses look for $HOME/llama.cpp/build/bin
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAGS=(-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
	-DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_UI=OFF)
TARGETS="llama-server llama-cli llama-bench"

# shellcheck source=../gpu-concurrency/lib-build.sh
. "$here/../gpu-concurrency/lib-build.sh"
[ "${BUILD_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-build.sh did not load" >&2; exit 1; }
b_begin build-llama

missing=()
for c in git cmake make g++ sha256sum; do command -v "$c" >/dev/null || missing+=("$c"); done
[ ${#missing[@]} = 0 ] || die "missing: ${missing[*]} -- this script installs nothing"

b_find_nvcc
FLAGS+=("-DCMAKE_CUDA_COMPILER=$NVCC" "-DCUDAToolkit_ROOT=$(dirname "$(dirname "$NVCC")")")
b_jobs
b_cap_check

if [ -e "$SRC" ] && [ ! -d "$SRC/.git" ]; then
	die "$SRC is there and is not a git checkout: it is left alone. The stamp reads this build's commit from a checkout at that path, so move what is there away."
fi
if [ ! -d "$SRC/.git" ]; then
	b_git clone --quiet --filter=blob:none "$URL" "$SRC" || die "the clone of $URL failed"
else
	say "found: $SRC, a git checkout; not cloned again"
fi
b_head "$SRC" "llama.cpp"     # a HEAD that cannot be read is said as that, not as a failed checkout
if [ "$B_HEAD" != "$LLAMA_COMMIT" ]; then
	b_git -C "$SRC" checkout --quiet --detach "$LLAMA_COMMIT" || die "cannot check out $LLAMA_COMMIT in $SRC"
fi
b_require_head "$SRC" "$LLAMA_COMMIT" "llama.cpp"     # read back AFTER the checkout
changed="$(b_tracked_changes "$SRC")"

# What cmake's log calls missing, one name a word: the variables of a "(missing: ...)", the
# package of a "Could NOT find", an imported CUDA:: target that was not found, the compiler.
cmake_missing() {
	{
		grep -o '(missing: [^)]*)' "$1" | sed 's/^(missing: //; s/)$//' | tr ' ' '\n'
		sed -n 's/.*Could N[Oo][Tt] find \([A-Za-z0-9_+:-]*\).*/\1/p' "$1"
		if grep -q 'but the target was not found' "$1"; then grep -o 'CUDA::[A-Za-z0-9_]*' "$1"; fi
		if grep -q 'No CMAKE_CUDA_COMPILER could be found' "$1"; then echo CMAKE_CUDA_COMPILER; fi
	} 2>/dev/null | grep . | LC_ALL=C sort -u | tr '\n' ' ' | sed 's/ $//'
}

# What the pin's tools/ui step embeds in llama-server when it may neither build the web UI nor
# fetch it: an index.html in tools/ui/dist of the source, else of the build tree, else nothing.
ui_line() {
	local d
	for d in "$SRC/tools/ui/dist" "$BUILD/tools/ui/dist"; do
		if [ -e "$d/index.html" ]; then
			echo "web UI: NOT fetched by this build, and $d holds one (index.html sha256 $(b_sha "$d/index.html")): at the pin the server's build embeds it"
			return 0
		fi
	done
	echo "web UI: none embedded -- not fetched and not built (the two UI flags above), and no index.html in $SRC/tools/ui/dist or $BUILD/tools/ui/dist"
}

# An earlier run's BUILD-INFO and its three binaries go first: each binary is linked by this
# run, or is missing at the end. One that was cut in its link is not empty, and make keeps it.
BI="$BUILD/bin/BUILD-INFO"
b_drop_info "$BI"
for t in $TARGETS; do rm -f "$BUILD/bin/$t"; done
mkdir -p "$BUILD"
if ! b_try "$BUILD/cmake.log" cmake -S "$SRC" -B "$BUILD" "${FLAGS[@]}"; then
	# The count before the log: what a configure names as missing after a kill is not missing.
	if [[ "$B_STEP_OOM" =~ ^[0-9]+$ ]] && [ "$B_STEP_OOM" -gt 0 ]; then
		die "llama.cpp's cmake failed -- see $BUILD/cmake.log. $B_STEP_NOTE"
	fi
	miss="$(cmake_missing "$BUILD/cmake.log")" || miss=""
	if [ -n "$miss" ]; then
		die "llama.cpp's cmake failed. Its log names as missing: $miss. If these are CUDA components, widen the CUDA packages by that name, not by the full toolkit -- see $BUILD/cmake.log. $B_STEP_NOTE"
	fi
	grep -A 3 'CMake Error' "$BUILD/cmake.log" | head -n 24 >&2 || true
	die "llama.cpp's cmake failed, and its log names nothing as missing in a form this script reads (its error lines, if it has any, are above) -- see $BUILD/cmake.log. $B_STEP_NOTE"
fi
# shellcheck disable=SC2086
b_step "$BUILD/build.log" "llama.cpp's build" cmake --build "$BUILD" --config Release --parallel "$JOBS" --target $TARGETS
for t in $TARGETS; do
	[ -s "$BUILD/bin/$t" ] || die "the build ended well and left no $t under $BUILD/bin -- see $BUILD/build.log"
done

{
	echo "llama.cpp commit $LLAMA_COMMIT from $URL"
	echo "flags ${FLAGS[*]}"
	echo "targets $TARGETS"
	ui_line
	b_nvcc_line
	echo "built $(date -u +%FT%TZ) with $(g++ --version | head -n 1); $(cmake --version | head -n 1)"
	echo "tracked files changed against the commit: $changed"
	for t in $TARGETS; do echo "$t sha256 $(b_sha "$BUILD/bin/$t")"; done
	for f in "$BUILD"/bin/lib*.so*; do
		if [ -f "$f" ] && [ ! -L "$f" ]; then echo "lib sha256 $(b_sha "$f") ${f##*/}"; fi
	done
	b_info_common
} > "$BI.tmp"
mv -f "$BI.tmp" "$BI"
cat "$BI"
