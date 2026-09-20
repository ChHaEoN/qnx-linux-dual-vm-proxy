#!/usr/bin/env bash
# build-cyclonedds-qnx.sh -- cross-build Eclipse Cyclone DDS for QNX SDP 8.0
# aarch64, and build the QNX-side DDS monitor against it.
#
# WHAT THIS NEEDS, AND WHY IT IS SPLIT ACROSS TWO MACHINES.
#   * The QNX cross-build runs on the SDP host (Windows here). It needs cmake,
#     a generator (Ninja), and qnxsdp-env.sh sourced.
#   * `idlc` CANNOT be built on that host if it has no host C compiler, and the
#     library does not need it (the DDSI XTypes sources ship pre-generated).
#     So `idlc` and the generated av.c/av.h come from a native build on the
#     Orin (aarch64 Linux), which also provides the L4T-side libddsc.
#
# Nothing built here may be committed: Cyclone DDS is EPL-2.0 OR BSD-3-Clause
# (BSD-3 elected) and distributing built binaries triggers obligations this
# repo deliberately avoids; QNX binaries are non-commercial-licensed outright.
set -euo pipefail

CDDS_COMMIT="${CDDS_COMMIT:-2f0d07d241f62f7121749b46721049e4dea5c58b}"   # v11.0.1
SRC="${SRC:-$PWD/cyclonedds}"
BUILD="${BUILD:-$PWD/build-qnx-static}"
NINJA="${NINJA:?set NINJA to a ninja binary (pip install ninja works)}"

[ -d "$SRC" ] || git clone --filter=blob:none https://github.com/eclipse-cyclonedds/cyclonedds.git "$SRC"
git -C "$SRC" checkout -q "$CDDS_COMMIT"

# The one upstream break on SDP 8.0. See 0001-qnx80-netstat.patch.
git -C "$SRC" apply --check ../0001-qnx80-netstat.patch 2>/dev/null &&
  git -C "$SRC" apply ../0001-qnx80-netstat.patch

cp qnx-sdp800-aarch64le.cmake "$SRC/ports/qnx/"

# Static: the guest then needs ONE executable staged, no .so.
# Upstream recommends a shared build first, then static as-if cross-compiling;
# a cross build already satisfies that.
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NINJA" \
  -DCMAKE_TOOLCHAIN_FILE="$SRC/ports/qnx/qnx-sdp800-aarch64le.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DBUILD_IDLC=OFF -DBUILD_DDSPERF=OFF -DBUILD_TESTING=OFF -DBUILD_EXAMPLES=OFF \
  -DENABLE_ICEORYX=OFF -DENABLE_ICEORYX2=OFF \
  -DENABLE_SSL=OFF -DENABLE_SECURITY=OFF -DENABLE_LTO=OFF
cmake --build "$BUILD" -j "$(nproc 2>/dev/null || echo 4)"

echo "built: $BUILD/lib/libddsc.a"
echo "next : qcc -Vgcc_ntoaarch64le -O2 -D_QNX_SOURCE=1 \\"
echo "         -I. -I$SRC/src/core/ddsc/include -I$SRC/src/ddsrt/include \\"
echo "         -I$BUILD/src/ddsrt/include -I$BUILD/src/core/ddsc/include \\"
echo "         -o qnx-dds-monitor qnx_dds_monitor.c av.c $BUILD/lib/libddsc.a -lsocket -lm"
