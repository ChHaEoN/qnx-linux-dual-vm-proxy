# Phase 3b / A6 (2026-09-27, OD12): the vsomeip client of the SOME/IP arm (someip_vprobe.cpp).
# Built by build-vsomeip.sh against the vsomeip it installs; nothing here is committed built.
cmake_minimum_required(VERSION 3.13)
project(someip_vprobe CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(vsomeip3 3.4 REQUIRED)
find_package(Threads REQUIRED)

add_executable(someip_vprobe someip_vprobe.cpp)
target_include_directories(someip_vprobe PRIVATE ${VSOMEIP3_INCLUDE_DIRS})
target_link_libraries(someip_vprobe PRIVATE vsomeip3 Threads::Threads)
target_compile_definitions(someip_vprobe PRIVATE VPROBE_VSOMEIP_VERSION="${vsomeip3_VERSION}")
target_compile_options(someip_vprobe PRIVATE -O2 -Wall -Wextra)
