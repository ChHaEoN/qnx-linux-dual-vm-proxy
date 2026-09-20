# QNX SDP 8.0, aarch64le. Not upstream: upstream ships only qnx-sdp710-*.
# CMAKE_SYSTEM becomes "QNX-8.0.0", so both QNX branches in
# src/ddsrt/CMakeLists.txt (CMAKE_SYSTEM MATCHES and CMAKE_SYSTEM_NAME MATCHES)
# fire correctly.
set(QNX_VERSION 8.0.0)
set(QNX_PROCESSOR aarch64le)
set(QNX_TOOLCHAIN_ARCH gcc_ntoaarch64le)

# pthread_* and clock_gettime live in libc on QNX 8.0; there is no libpthread.so
# or librt.so to link. CMake's FindThreads probes libc first and succeeds, so
# this is belt-and-braces against a stale cache rather than a live bug --
# verified 2026-09-20: Threads_FOUND=TRUE with CMAKE_THREAD_LIBS_INIT empty.
set(CMAKE_HAVE_LIBC_PTHREAD 1 CACHE INTERNAL "QNX: pthread_* are in libc")
set(CMAKE_THREAD_LIBS_INIT "" CACHE INTERNAL "QNX: no separate thread library")
set(CMAKE_USE_PTHREADS_INIT 1 CACHE INTERNAL "QNX: pthreads semantics")
# qcc accepts -pthread but warns "unnecessary for qnx" on every compile.
set(THREADS_PREFER_PTHREAD_FLAG OFF)

include("${CMAKE_CURRENT_LIST_DIR}/qnx-common.cmake")
