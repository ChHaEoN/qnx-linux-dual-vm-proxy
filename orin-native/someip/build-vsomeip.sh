#!/usr/bin/env bash
# build-vsomeip.sh -- build vsomeip 3.4.10 and the SOME/IP arm's client (someip_vprobe) on the
# Linux host (Phase 3b / A6, 2026-09-27, OD12). Run on the Orin (L4T, Ubuntu 22.04, Boost 1.74)
# or any Linux host with the same packages.
#
# vsomeip is COVESA's, MPL-2.0: fetched by tag and checked against the pinned commit, built and
# installed under $PREFIX, never committed. 3.4.10 is the newest release that builds against
# Ubuntu 22.04's Boost 1.74 (3.5 wants >= 1.75). DLT is disabled; signal handling is on.
#
# NEEDS: git, cmake >= 3.13, g++, libboost-system-dev libboost-thread-dev
# libboost-filesystem-dev. It checks and names what is missing; it installs nothing itself.
#
# OUT: $PREFIX/bin/someip_vprobe (the probe, rpath to $PREFIX/lib), and $PREFIX/BUILD-INFO with
# the vsomeip commit and the probe's sha256.
set -euo pipefail

TAG="${VSOMEIP_TAG:-3.4.10}"
COMMIT="${VSOMEIP_COMMIT:-02c199dff8aba814beebe3ca417fd991058fe90c}"
URL="${VSOMEIP_URL:-https://github.com/COVESA/vsomeip.git}"
PREFIX="${PREFIX:-$HOME/vsomeip/$TAG}"
SRC="${SRC:-$HOME/vsomeip/src-$TAG}"
JOBS="${JOBS:-4}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "FATAL: $*" >&2; exit 1; }

missing=()
for c in git cmake g++; do command -v "$c" >/dev/null || missing+=("$c"); done
for p in libboost-system-dev libboost-thread-dev libboost-filesystem-dev; do
	dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
[ ${#missing[@]} = 0 ] || die "missing: ${missing[*]} -- e.g. sudo apt-get install ${missing[*]}"

if [ ! -d "$SRC/.git" ]; then
	git clone --quiet --branch "$TAG" --depth 1 "$URL" "$SRC"
fi
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || die "$SRC is at $got, not the pinned $COMMIT for $TAG"

mkdir -p "$SRC/build"
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
	-DENABLE_SIGNAL_HANDLING=1 -DDISABLE_DLT=1 > "$SRC/build/cmake.log" 2>&1 \
	|| die "vsomeip's cmake failed -- see $SRC/build/cmake.log"
make -C "$SRC/build" -j"$JOBS" > "$SRC/build/make.log" 2>&1 || die "vsomeip's build failed -- see $SRC/build/make.log"
make -C "$SRC/build" install > "$SRC/build/install.log" 2>&1 || die "vsomeip's install failed"

PB="$PREFIX/probe-build"
cmake -S "$here" -B "$PB" -DCMAKE_BUILD_TYPE=Release -Dvsomeip3_DIR="$PREFIX/lib/cmake/vsomeip3" \
	-DCMAKE_INSTALL_RPATH="$PREFIX/lib" -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON > "$PB.cmake.log" 2>&1 \
	|| die "the probe's cmake failed -- see $PB.cmake.log"
make -C "$PB" > "$PB.make.log" 2>&1 || die "the probe's build failed -- see $PB.make.log"
mkdir -p "$PREFIX/bin"
install -m 0755 "$PB/someip_vprobe" "$PREFIX/bin/someip_vprobe"
{
	echo "vsomeip $TAG commit $COMMIT from $URL"
	echo "someip_vprobe sha256 $(sha256sum < "$PREFIX/bin/someip_vprobe" | cut -d' ' -f1)"
	echo "source sha256 $(sha256sum < "$here/someip_vprobe.cpp" | cut -d' ' -f1)"
	echo "built $(date -u +%FT%TZ) with $(g++ --version | head -1)"
} > "$PREFIX/BUILD-INFO"
cat "$PREFIX/BUILD-INFO"
