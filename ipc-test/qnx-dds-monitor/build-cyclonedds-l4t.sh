#!/usr/bin/env bash
# build-cyclonedds-l4t.sh -- build Eclipse Cyclone DDS natively on the L4T side, run its idlc on
# av.idl, and build the two L4T peers of the DDS demo against it (Phase 3b / A6, 2026-10-05).
#
# THE OTHER HALF OF build-cyclonedds-qnx.sh, AT THE SAME COMMIT. That script cross-builds a
# static libddsc for the QNX guest on the SDP host, where idlc cannot be built. This one runs on
# the Orin and leaves, under PREFIX = ~/cyclonedds/<commit>:
#   lib/libddsc.so*     the shared library the L4T peers load
#   bin/idlc            the IDL compiler
#   gen/av.c, gen/av.h  idlc's output for av.idl -- what BOTH sides compile; the QNX monitor's
#                       build takes these two files, it does not generate its own
#   bin/pubbad, bin/subv  the two L4T peers, when their sources are given (below)
#   BUILD-INFO          the commit, the switches, the compiler, the sha256 of each of the above,
#                       and the largest memory peak of a build step
#
# THE PEERS' SOURCES ARE NOT IN THIS REPO (owner, 2026-10-04): pubbad.c and subv.c are kept on
# the board. Give their directory as PEER_SRC=<dir>. With PEER_SRC unset, or with either file
# missing, the library, idlc and av.c/av.h are still built, neither peer is, the script says so
# by name, BUILD-INFO says so, and THE EXIT STATUS IS 3. Both peers or neither.
#   exit 0   everything above, the two peers included
#   exit 3   the library, idlc and av.c/av.h; the peers NOT built
#   exit 1   a refusal or a failed step;  exit 75  another run of this script is still alive
#
# THE PEERS ARE COMPILED FROM COPIES of the two files, in a directory of the build that holds
# nothing else. Each says #include "av.h", and a compiler looks for a quoted header beside the
# source before it looks where -I says: compiled where they lie, a PEER_SRC that also holds an
# av.h of an earlier idlc (a directory the peers were built in before does) would have that
# one compiled in, with this run's av.c linked beside it and BUILD-INFO naming this run's
# av.h. So an av.h or av.c in PEER_SRC is named and not used. Anything else the two sources
# include from their own directory is not found either, and the compile fails by its name.
#   PEER_SRC IS ONLY READ, so it may not be this script's BUILD or PREFIX, nor lie in either:
# the copies' directory is emptied before the copy and an earlier run's av.c and av.h are
# removed from the prefix, and sources kept there would be removed by the script that was to
# compile them. The copies' directory (<BUILD>/l4t-peers) is emptied at the start, with the
# other refusals and before anything is built, and must then be empty: what `rm -f` leaves in
# it (a directory, a file whose name starts with a dot) is somebody's to remove. It is looked
# at again right before the copy.
#
# THE SWITCHES are build-cyclonedds-qnx.sh's, with two changed on purpose: BUILD_SHARED_LIBS=ON
# (the peers are small programs that load the library; nothing here is staged into an image) and
# BUILD_IDLC=ON (idlc is what this half is for). No toolchain file, no generator named (the board
# has make and no ninja), and no patch: 0001-qnx80-netstat.patch is for SDP 8.0 only. The library
# directory is named (lib), so that the rpath and idlc's library path below do not depend on
# what the host's cmake would choose. The line the R36 board's copy was built with was never
# written down, so these switches are this script's own and not a reproduction of that build.
#
# idlc IS THE ONE THING THIS SCRIPT RUNS OF WHAT IT BUILT. It is a code generator: it reads
# av.idl and writes two files. It runs once, under the memory cap like every other step, with an
# earlier run's av.c and av.h removed first, and the peers are compiled only when it has left
# both files. THE PEERS ARE NEVER STARTED HERE: each opens a DDS participant and waits.
#
# NEEDS: git, cmake (3.15 or newer, for `cmake --install`), make, gcc, systemd-run, flock. bison
# is used by Cyclone's build when it is there (whether the build needs it is not known);
# BUILD-INFO says whether it was. It installs nothing itself.
#
# THE RULES OF ../../orin-native/gpu-concurrency/lib-build.sh APPLY: JOBS defaults to 2 on a host
# with under 8 GB and no swap; every step runs under the memory cap or not at all; a done-file
# holds the exit status (~/builds/build-cyclonedds-l4t.done). AFTER A RUN THAT DIED, remove
# BUILD (~/cyclonedds/build-<commit>) before the next run: the installed library and idlc are
# removed before every run, but the install copies them from that directory, and a file there
# that was cut short while it was written is one make keeps (lib-build.sh says why).
#
# Nothing built here may be committed: Cyclone DDS is EPL-2.0 OR BSD-3-Clause (BSD-3 elected)
# and distributing built binaries triggers obligations this repo deliberately avoids. av.c and
# av.h carry no licence header and are generated at build time, never committed.
set -euo pipefail

CDDS_COMMIT="${CDDS_COMMIT:-2f0d07d241f62f7121749b46721049e4dea5c58b}"   # v11.0.1
URL="${CDDS_URL:-https://github.com/eclipse-cyclonedds/cyclonedds.git}"
SRC="${SRC:-$HOME/cyclonedds/src}"
PREFIX="${PREFIX:-$HOME/cyclonedds/$CDDS_COMMIT}"
BUILD="${BUILD:-$HOME/cyclonedds/build-$CDDS_COMMIT}"
PEER_SRC="${PEER_SRC:-}"
CC="${CC:-gcc}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAGS=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_LIBDIR=lib
	-DBUILD_SHARED_LIBS=ON
	-DBUILD_IDLC=ON -DBUILD_DDSPERF=OFF -DBUILD_TESTING=OFF -DBUILD_EXAMPLES=OFF
	-DENABLE_ICEORYX=OFF -DENABLE_ICEORYX2=OFF
	-DENABLE_SSL=OFF -DENABLE_SECURITY=OFF -DENABLE_LTO=OFF)
PEERS="pubbad subv"
PEER_CFLAGS=(-O2 -Wall -Wextra)
PEER_COPY="$BUILD/l4t-peers"

# shellcheck source=../../orin-native/gpu-concurrency/lib-build.sh
. "$here/../../orin-native/gpu-concurrency/lib-build.sh"
[ "${BUILD_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-build.sh did not load" >&2; exit 1; }
b_begin build-cyclonedds-l4t

missing=()
for c in git cmake make "$CC" sha256sum; do command -v "$c" >/dev/null || missing+=("$c"); done
[ ${#missing[@]} = 0 ] || die "missing: ${missing[*]} -- this script installs nothing"
[ -r "$here/av.idl" ] || die "no av.idl beside this script"
# idlc is started in another directory than this script's (below), so none of these is relative.
for d in "$SRC" "$PREFIX" "$BUILD"; do
	case "$d" in /*) ;; *) die "SRC, PREFIX and BUILD are absolute paths; '$d' is not" ;; esac
done

# is_inside PATH DIR: PATH is DIR, or lies in it, by whatever names and links either is reached.
is_inside() {
	local p q
	p="$(readlink -f "$1" 2>/dev/null)" || p="$1"
	while [ -n "$p" ]; do
		if [ "$p" -ef "$2" ]; then return 0; fi
		q="$(dirname "$p")"
		[ "$q" != "$p" ] || break
		p="$q"
	done
	return 1
}

# The copies' directory, emptied; what `rm -f` leaves in it is not this script's to remove.
peer_copy_empty() {
	rm -f "$PEER_COPY"/* 2>/dev/null || true
	[ -z "$(ls -A "$PEER_COPY")" ] || die "$PEER_COPY holds something this script did not put there: it must be empty before the peers' sources are copied into it. Remove what is in it: $(ls -A "$PEER_COPY" | head -n 5 | tr '\n' ' ')"
}

# PEER_SRC is only read. In BUILD or PREFIX it would be among what this script empties and
# removes: the sources would be gone before they were copied. The copies' directory is asked by
# itself as well, for one that is a link to somewhere else.
if [ -n "$PEER_SRC" ]; then
	for d in "$PEER_COPY" "$BUILD" "$PREFIX"; do
		if is_inside "$PEER_SRC" "$d"; then
			die "PEER_SRC=$PEER_SRC is, or lies in, $d, which this script empties and writes. Keep the two sources somewhere else."
		fi
	done
fi

# The peers: both sources, or neither peer. Decided before anything is built, said at the end.
peers_why=""
if [ -z "$PEER_SRC" ]; then
	peers_why="PEER_SRC is not set"
else
	for p in $PEERS; do
		[ -r "$PEER_SRC/$p.c" ] || peers_why="${peers_why:+$peers_why; }$PEER_SRC/$p.c is missing"
	done
fi
if [ -n "$peers_why" ]; then
	say "the peers will NOT be built: $peers_why"
else
	for f in av.h av.c; do
		if [ -e "$PEER_SRC/$f" ]; then say "found: $PEER_SRC/$f; NOT used: the peers get this run's $PREFIX/gen/$f"; fi
	done
	# With the other refusals, before the cap is asked for and before anything is built.
	if [ -e "$PEER_COPY" ]; then peer_copy_empty; fi
fi

b_jobs
b_cap_check

if [ -e "$SRC" ] && [ ! -d "$SRC/.git" ]; then
	die "$SRC is there and is not a git checkout: it is left alone. Move it away, or give another SRC."
fi
if [ ! -d "$SRC/.git" ]; then
	b_git clone --quiet --filter=blob:none "$URL" "$SRC" || die "the clone of $URL failed"
else
	say "found: $SRC, a git checkout; not cloned again"
fi
b_head "$SRC" "Cyclone DDS"     # a HEAD that cannot be read is said as that, not as a failed checkout
if [ "$B_HEAD" != "$CDDS_COMMIT" ]; then
	b_git -C "$SRC" checkout --quiet --detach "$CDDS_COMMIT" || die "cannot check out $CDDS_COMMIT in $SRC"
fi
b_require_head "$SRC" "$CDDS_COMMIT" "Cyclone DDS"     # read back AFTER the checkout
changed="$(b_tracked_changes "$SRC")"

# What this script checks or hashes of an earlier run goes first: a failed run leaves no peer,
# no generated file and no BUILD-INFO that describe another build, and an install that leaves
# no library or no idlc cannot pass on an earlier run's. The headers and cmake files of an
# earlier install stay under PREFIX; this run's install writes over them.
BI="$PREFIX/BUILD-INFO"
GEN="$PREFIX/gen"
b_drop_info "$BI"
for p in $PEERS; do rm -f "$PREFIX/bin/$p"; done
rm -f "$GEN/av.c" "$GEN/av.h" "$PREFIX/bin/idlc" "$PREFIX"/lib/libddsc.so*

mkdir -p "$BUILD"
b_step "$BUILD/cmake.log" "Cyclone's cmake" cmake -S "$SRC" -B "$BUILD" "${FLAGS[@]}" -DCMAKE_INSTALL_PREFIX="$PREFIX"
b_step "$BUILD/build.log" "Cyclone's build" cmake --build "$BUILD" --parallel "$JOBS"
b_step "$BUILD/install.log" "Cyclone's install" cmake --install "$BUILD"

lib=""
for f in "$PREFIX"/lib/libddsc.so*; do
	if [ -f "$f" ] && [ ! -L "$f" ]; then lib="$f"; fi
done
[ -n "$lib" ] || die "the install left no libddsc.so under $PREFIX/lib (BUILD_SHARED_LIBS=ON was asked for)"
[ -f "$PREFIX/bin/idlc" ] && [ -x "$PREFIX/bin/idlc" ] || die "the install left no idlc under $PREFIX/bin (BUILD_IDLC=ON was asked for)"

# idlc writes where it stands, so env puts it in $GEN (-C). LD_LIBRARY_PATH: it finds the library
# it was built with whether or not the install gave it an rpath.
mkdir -p "$GEN"
b_step "$BUILD/idlc.log" "idlc on av.idl" \
	env -C "$GEN" LD_LIBRARY_PATH="$PREFIX/lib" "$PREFIX/bin/idlc" -l c "$here/av.idl"
[ -s "$GEN/av.c" ] && [ -s "$GEN/av.h" ] \
	|| die "idlc ended well and left no av.c and av.h in $GEN -- see $BUILD/idlc.log. The peers are not built."

if [ -z "$peers_why" ]; then
	# Copies, in a directory that holds nothing else: the header says why. It was empty at the
	# start; it is asked again here, after everything that ran in between.
	mkdir -p "$PEER_COPY"
	peer_copy_empty
	for p in $PEERS; do
		cp "$PEER_SRC/$p.c" "$PEER_COPY/$p.c" || die "cannot copy $PEER_SRC/$p.c to $PEER_COPY"
		b_step "$BUILD/$p.log" "the compile of the peer $p" "$CC" "${PEER_CFLAGS[@]}" -I "$GEN" -I "$PREFIX/include" \
			-o "$PREFIX/bin/$p" "$PEER_COPY/$p.c" "$GEN/av.c" -L "$PREFIX/lib" -lddsc -Wl,-rpath,"$PREFIX/lib"
		[ -s "$PREFIX/bin/$p" ] || die "the compiler ended well and left no $PREFIX/bin/$p"
	done
fi

bison_line="$(bison --version 2>/dev/null | head -n 1)" || bison_line=""
{
	echo "cyclonedds commit $CDDS_COMMIT from $URL"
	echo "flags ${FLAGS[*]}"
	echo "built $(date -u +%FT%TZ) with $("$CC" --version | head -n 1); $(cmake --version | head -n 1)"
	echo "${bison_line:-bison absent: the build went without it}"
	echo "tracked files changed against the commit: $changed"
	echo "libddsc sha256 $(b_sha "$lib") ${lib##*/}"
	echo "idlc sha256 $(b_sha "$PREFIX/bin/idlc")"
	echo "av.idl sha256 $(b_sha "$here/av.idl")"
	echo "av.c sha256 $(b_sha "$GEN/av.c")"
	echo "av.h sha256 $(b_sha "$GEN/av.h")"
	if [ -z "$peers_why" ]; then
		for p in $PEERS; do
			echo "$p sha256 $(b_sha "$PREFIX/bin/$p"), from $p.c sha256 $(b_sha "$PEER_COPY/$p.c")"
		done
		echo "peer flags $CC ${PEER_CFLAGS[*]}, rpath $PREFIX/lib"
		echo "peer sources copied from $PEER_SRC to $PEER_COPY, which holds nothing else: the av.h compiled in is this run's"
	else
		echo "peers NOT BUILT (${PEERS// /, }): $peers_why"
	fi
	b_info_common
} > "$BI.tmp"
mv -f "$BI.tmp" "$BI"
cat "$BI"

if [ -n "$peers_why" ]; then
	echo "NOT BUILT: the peers pubbad and subv ($peers_why). The library, idlc and av.c/av.h are built. Exit status 3 says so." >&2
	exit 3
fi
