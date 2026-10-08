#!/usr/bin/env bash
# build-vsomeip.sh -- build vsomeip 3.4.10 and the SOME/IP arm's client (someip_vprobe) on the
# Linux host (Phase 3b / A6, 2026-09-27, OD12). Run on the Orin (L4T R39, Ubuntu 24.04, Boost 1.74
# from universe) or on any Linux host with one of the two package sets below.
#
# vsomeip is COVESA's, MPL-2.0: fetched by tag and checked against the pinned commit, built and
# installed under $PREFIX, never committed. 3.4.10 is the newest release that builds against
# Boost 1.74 (3.5 wants >= 1.75), the Boost this arm was first built with. DLT is disabled;
# signal handling is on. -DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON: the tag's CMakeLists.txt has an
# export(PACKAGE ...), which with the policy its cmake_minimum_required leaves at its old
# setting writes the BUILD tree's path into ~/.cmake/packages, outside the build and the
# prefix, where a later find_package(vsomeip3) with no directory given would find it. Read
# from the tag's file, not run.
#
# ONE KIND OF WARNING IS NOT AN ERROR: -DCMAKE_CXX_FLAGS=-Wno-error=stringop-overflow. g++ 13
# reports -Wstringop-overflow inside a Boost 1.74 header, boost/icl/detail/interval_set_algo.hpp,
# which vsomeip's security policy header brings in (implementation/security/include/policy.hpp,
# through boost/icl/interval_set.hpp), and the flags the tag's CMakeLists.txt sets for Linux
# include -Werror, so that every warning is an error. The flag stops that one kind from being
# an error and leaves it a warning, in make's log; every other kind stays an error. No
# generated code depends on it: it changes what the compiler does with a diagnostic, not the
# code it generates. vsomeip's source is not changed. The alternative, another Boost (the
# fallback named below), would change what the binary is built against. Where the word stands
# does not matter: the tag's file appends its own flags to a CMAKE_CXX_FLAGS it is given, so
# its -Werror follows this word, and gcc's manual gives the more specific warning option
# priority over the less specific one wherever each stands, and has -Wno-error=<kind> hold
# while -Werror is in effect. With CMAKE_CXX_FLAGS given, cmake does not read CXXFLAGS from the
# environment for this configure. The word is one of FLAGS, so BUILD-INFO's flags line has it.
# The probe's configure does not get it: the CMakeLists.txt beside this script asks for -Wall
# -Wextra and for no -Werror, and the tag's file gives the vsomeip3 target no compile option to
# pass on. Which warning, and in which header, is the compiler's own word. What is said here of
# the tag's files, of Boost's (as its 1.74.0 release has them), of gcc's rule for the two
# options and of cmake is read from those files and from the two manuals.
#
# BOOST: ONE, KNOWN BY NAME, OR NO BUILD. Ubuntu 22.04's default Boost is 1.74, and its
# unversioned -dev packages are that. Ubuntu 24.04's default is 1.83; 1.74 is there as the
# versioned packages from universe, which cannot be installed beside the default ones. So the
# check takes either
#   the versioned 1.74 set, with no unversioned package beside it:
#     libboost1.74-dev libboost-system1.74-dev libboost-thread1.74-dev libboost-filesystem1.74-dev
#   or the unversioned set, all three at one Boost:
#     libboost-system-dev libboost-thread-dev libboost-filesystem-dev
#     (on 22.04 these are 1.74 and bring the versioned ones as their own dependencies: one Boost)
# and refuses a mix, an incomplete set, or neither, naming the packages. BUILD-INFO records
# which Boost that was, as dpkg has it and as cmake's cache has it. The unversioned set on 24.04
# is 1.83: the named fallback, which this project has not built 3.4.10 against.
#
# NEEDS: git, cmake >= 3.13, make, g++, dpkg-query, systemd-run, flock, and one Boost set. It
# checks and names what is missing; it installs nothing itself.
#
# OUT: $PREFIX/bin/someip_vprobe (the probe, rpath to $PREFIX/lib), and $PREFIX/BUILD-INFO with
# the vsomeip commit, the Boost, the flags, the compiler, the sha256 of the probe and of each
# vsomeip library, and the largest memory peak of a build step. Exit 0, 1, or 75 when another run
# of this script is still alive.
#
# AN EARLIER RUN'S PROBE IS REMOVED before the first build step, where it was linked and where
# it was installed, so the probe is linked by this run or is missing at the end: a run that was
# cut in its last link leaves one that is not empty and that make takes as built. The rest of
# $SRC/build and $PREFIX/probe-build is make's to judge; after a run that DIED, remove both
# directories before the next run (lib-build.sh says why).
#
# THE RULES OF ../gpu-concurrency/lib-build.sh APPLY: JOBS defaults to 2 on a host with under
# 8 GB and no swap; every step runs under the memory cap or not at all; a done-file holds the
# exit status (~/builds/build-vsomeip.done); the probe is never started here.
set -euo pipefail

TAG="${VSOMEIP_TAG:-3.4.10}"
COMMIT="${VSOMEIP_COMMIT:-02c199dff8aba814beebe3ca417fd991058fe90c}"
URL="${VSOMEIP_URL:-https://github.com/COVESA/vsomeip.git}"
PREFIX="${PREFIX:-$HOME/vsomeip/$TAG}"
SRC="${SRC:-$HOME/vsomeip/src-$TAG}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLAGS=(-DCMAKE_BUILD_TYPE=Release -DENABLE_SIGNAL_HANDLING=1 -DDISABLE_DLT=1 -DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON)
FLAGS+=(-DCMAKE_CXX_FLAGS=-Wno-error=stringop-overflow)     # one kind of warning is not an error: the header says why
BOOST_V="libboost1.74-dev libboost-system1.74-dev libboost-thread1.74-dev libboost-filesystem1.74-dev"
BOOST_U="libboost-system-dev libboost-thread-dev libboost-filesystem-dev"

# shellcheck source=../gpu-concurrency/lib-build.sh
. "$here/../gpu-concurrency/lib-build.sh"
[ "${BUILD_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-build.sh did not load" >&2; exit 1; }
b_begin build-vsomeip

missing=()
for c in git cmake make g++ dpkg-query sha256sum; do command -v "$c" >/dev/null || missing+=("$c"); done
[ ${#missing[@]} = 0 ] || die "missing: ${missing[*]} -- this script installs nothing"

# ---- Boost: what dpkg has of the two sets. A package that was removed and left its
# configuration behind is not installed, which is why this asks for the status and not only for
# the name. A package dpkg does not know prints nothing here.
# shellcheck disable=SC2086
boost_state="$(dpkg-query -W -f='${Package}|${Status}|${Version}\n' $BOOST_V $BOOST_U 2>/dev/null)" || true
declare -A boost_ver=()
while IFS='|' read -r p st v; do
	case "$st" in *" ok installed") boost_ver[$p]="$v" ;; esac
done <<< "$boost_state"
have_v=""; lack_v=""; have_u=""; lack_u=""; u_boosts=""
for p in $BOOST_V; do
	if [ -n "${boost_ver[$p]:-}" ]; then have_v="$have_v $p=${boost_ver[$p]}"; else lack_v="$lack_v $p"; fi
done
for p in $BOOST_U; do
	if [ -n "${boost_ver[$p]:-}" ]; then
		have_u="$have_u $p=${boost_ver[$p]}"
		mm="unreadable"
		if [[ "${boost_ver[$p]}" =~ ^([0-9]+:)?([0-9]+\.[0-9]+) ]]; then mm="${BASH_REMATCH[2]}"; fi
		case " $u_boosts " in *" $mm "*) ;; *) u_boosts="${u_boosts:+$u_boosts }$mm" ;; esac
	else
		lack_u="$lack_u $p"
	fi
done
if [ -z "$have_v" ] && [ -z "$have_u" ]; then
	die "missing: the Boost dev packages. Neither set is installed: the versioned 1.74 set ($BOOST_V) or the unversioned set ($BOOST_U)"
elif [ -z "$lack_v" ] && [ -z "$have_u" ]; then
	BOOST_LINE="boost 1.74 from the versioned dev set:$have_v"
elif [ -z "$lack_u" ] && [[ "$u_boosts" =~ ^[0-9]+\.[0-9]+$ ]] && { [ -z "$have_v" ] || [ "$u_boosts" = 1.74 ]; }; then
	BOOST_LINE="boost $u_boosts from the unversioned dev set:$have_u"
else
	die "a mix of Boost dev packages, or an incomplete set: this build takes one whole set and nothing of another Boost. Versioned 1.74 set -- installed:${have_v:- none}; missing:${lack_v:- none}. Unversioned set -- installed:${have_u:- none}; missing:${lack_u:- none}."
fi
say "$BOOST_LINE"

b_jobs
b_cap_check

if [ ! -d "$SRC/.git" ]; then
	b_git clone --quiet --branch "$TAG" --depth 1 "$URL" "$SRC" || die "the clone of $URL at $TAG failed"
else
	say "found: $SRC, a git checkout; not cloned again"
fi
b_require_head "$SRC" "$COMMIT" "$TAG"
changed="$(b_tracked_changes "$SRC")"

# An earlier run's BUILD-INFO and its probe go first, the probe where it was linked and where it
# was installed: it is linked by this run, or is missing at the end. One that was cut in its
# link is not empty, and make keeps it.
BI="$PREFIX/BUILD-INFO"
PB="$PREFIX/probe-build"
b_drop_info "$BI"
rm -f "$PB/someip_vprobe" "$PREFIX/bin/someip_vprobe"
mkdir -p "$SRC/build"
b_step "$SRC/build/cmake.log" "vsomeip's cmake" cmake -S "$SRC" -B "$SRC/build" "${FLAGS[@]}" -DCMAKE_INSTALL_PREFIX="$PREFIX"
b_step "$SRC/build/make.log" "vsomeip's build" make -C "$SRC/build" -j"$JOBS"
b_step "$SRC/build/install.log" "vsomeip's install" make -C "$SRC/build" install

b_step "$PB.cmake.log" "the probe's cmake" cmake -S "$here" -B "$PB" -DCMAKE_BUILD_TYPE=Release \
	-Dvsomeip3_DIR="$PREFIX/lib/cmake/vsomeip3" -DCMAKE_INSTALL_RPATH="$PREFIX/lib" -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON
b_step "$PB.make.log" "the probe's build" make -C "$PB"
[ -s "$PB/someip_vprobe" ] || die "the probe's build ended well and left no someip_vprobe under $PB -- see $PB.make.log"
mkdir -p "$PREFIX/bin"
install -m 0755 "$PB/someip_vprobe" "$PREFIX/bin/someip_vprobe"

boost_dir="$(sed -n 's/^Boost_DIR:[A-Z]*=//p' "$SRC/build/CMakeCache.txt" 2>/dev/null | head -n 1)" || boost_dir=""
{
	echo "vsomeip $TAG commit $COMMIT from $URL"
	echo "someip_vprobe sha256 $(b_sha "$PREFIX/bin/someip_vprobe")"
	echo "source sha256 $(b_sha "$here/someip_vprobe.cpp")"
	echo "built $(date -u +%FT%TZ) with $(g++ --version | head -1)"
	echo "$BOOST_LINE"
	echo "boost as cmake found it: ${boost_dir:-not in CMakeCache.txt}"
	echo "flags ${FLAGS[*]}"
	echo "tracked files changed against the commit: $changed"
	for f in "$PREFIX"/lib/libvsomeip3*.so.*; do
		if [ -f "$f" ] && [ ! -L "$f" ]; then echo "lib sha256 $(b_sha "$f") ${f##*/}"; fi
	done
	b_info_common
} > "$BI.tmp"
mv -f "$BI.tmp" "$BI"
cat "$BI"
