"""The board's four build scripts and the library they share, run against stubs only (Phase 3b / A6,
2026-10-05).

    orin-native/gpu-concurrency/lib-build.sh              the job count, the memory cap, a detached run's state
    orin-native/someip/build-vsomeip.sh                   vsomeip and someip_vprobe
    ipc-test/qnx-dds-monitor/build-cyclonedds-l4t.sh      Cyclone DDS, idlc's output for av.idl, the two L4T peers
    orin-native/edge-llm/build-llama.sh                   llama.cpp with CUDA: llama-server, llama-cli, llama-bench
    orin-native/gpu-concurrency/build-fma.sh              the FMA load

Nothing here needs a board, a network, a compiler or CUDA: git, cmake, make, gcc, g++, nvcc,
idlc, bison, dpkg-query, systemd-run and sudo are stubs (on PATH, or where the scripts look for
them), HOME is a temporary directory, and /proc/meminfo, /proc/self/cgroup, /sys/fs/cgroup and
/usr/local are made-up files and trees the scripts are pointed at. sha256sum, install and the
shell's own tools are the real ones; flock is the real one where there is one (Git Bash on
Windows has none, and gets a stub that always grants the lock). One test puts the real gcc,
where there is one, behind the script's own compile line for the two peers, with made-up
sources: the peers' own sources are not in the repo. One puts the real git, where there is
one, behind the scripts' question for a checkout's HEAD, in a directory `git init` made: it
reaches no network, and no git setting of the session that runs pytest reaches a script.

Every value below is made up: package versions, compiler versions, memory sizes, the unit's
name. The layouts are the real ones: dpkg-query's status words, MemTotal and SwapTotal lines, a
cgroup v2 line, systemd-run's own two messages (read from the real tool on the PC, not on the
board), cmake's "Could NOT find ... (missing: ...)" and "links to ... but the target was not
found" errors.

What "built" means here: the stubs leave, where a real build would leave a binary, a small
script that writes a line to a file when it is run. So "nothing built is executed" is a test
that the file does not exist afterwards, for every script.

What these tests do NOT show: that anything builds. No source is fetched and nothing of the
builds is compiled; the flags are pinned as text and as the stubs' argv, not by a compiler: what
g++ does with the one -Wno-error=<kind> word of vsomeip's configure is its manual's to say. The
systemd-run stub writes the limit into a made-up cgroup tree as systemd writes it into the real
one, and the first stub that runs inside a scope writes the peak and the oom_kill count the
test gave that scope, as the kernel counts them while a scope's command runs; where a test says
so, that stub also sends the scope's processes the TERM the user manager sends when it stops a
scope after a kill. That the board's user manager takes the two properties, that the kernel
enforces them, that the manager there stops a scope as the PC's does, and that a build killed
by the cap leaves the board responsive, are not exercised here. Nor is what a real session's
end does to a scope under the user manager.
"""
import hashlib
import os
import re
import shutil
import signal
import subprocess
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GC = os.path.join(REPO, "orin-native", "gpu-concurrency")
DDS = os.path.join(REPO, "ipc-test", "qnx-dds-monitor")
LIB = os.path.join(GC, "lib-build.sh")
SCRIPTS = {
    "vsomeip": os.path.join(REPO, "orin-native", "someip", "build-vsomeip.sh"),
    "cyclonedds": os.path.join(DDS, "build-cyclonedds-l4t.sh"),
    "llama": os.path.join(REPO, "orin-native", "edge-llm", "build-llama.sh"),
    "fma": os.path.join(GC, "build-fma.sh"),
}
NAMES = {"vsomeip": "build-vsomeip", "cyclonedds": "build-cyclonedds-l4t", "llama": "build-llama", "fma": "build-fma"}
ALL = sorted(SCRIPTS)
WITH_JOBS = ("cyclonedds", "llama", "vsomeip")          # build-fma.sh makes one compiler call
BASH = shutil.which("bash")
FLOCK = shutil.which("flock")
SETSID = shutil.which("setsid")
GCC = None if os.name == "nt" else shutil.which("gcc")  # looked for before the stubs are on PATH
GIT = shutil.which("git")                               # the real one, for the test that puts it behind the scripts
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")
real_flock = pytest.mark.skipif(FLOCK is None, reason="no flock here: the stub one always grants the lock")
posix_signals = pytest.mark.skipif(os.name == "nt", reason="Windows cannot send the script's process group a signal")

VSOMEIP_PIN = "02c199dff8aba814beebe3ca417fd991058fe90c"
CDDS_PIN = "2f0d07d241f62f7121749b46721049e4dea5c58b"
LLAMA_PIN = "e6ab7c1a41054a888ada952eab4c886444c2f5ad"
NOT_A_PIN = "f" * 40                                    # where a clone's default branch stands
CAP = "MemoryMax=4G,MemorySwapMax=0"                    # the scope's properties, as the systemd-run stub passes them on
CAP_ARGV = ["--user", "--scope", "-p", "MemoryMax=4G", "-p", "MemorySwapMax=0"]
FOUR_G = str(4 * 1024 ** 3)
REST_KB = 1572864                                       # what a cap must leave of MemTotal, in kB: the library's MEM_REST_KB
# The words every git call that can reach the network carries: a transfer that stalls is ended.
GIT_NET = ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60"]
LLAMA_FLAGS = ["-DGGML_CUDA=ON", "-DCMAKE_CUDA_ARCHITECTURES=87", "-DLLAMA_CURL=OFF", "-DCMAKE_BUILD_TYPE=Release",
               "-DLLAMA_USE_PREBUILT_UI=OFF", "-DLLAMA_BUILD_UI=OFF"]
# The one kind of warning vsomeip's build does not treat as an error, as the configure word that says so.
VSOMEIP_WARN = "-DCMAKE_CXX_FLAGS=-Wno-error=stringop-overflow"
VSOMEIP_FLAGS = ["-DCMAKE_BUILD_TYPE=Release", "-DENABLE_SIGNAL_HANDLING=1", "-DDISABLE_DLT=1", "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON",
                 VSOMEIP_WARN]
# A word that takes a warning, or its force, away: -Wno- in any form (-Wno-error with or without a kind, a kind switched
# off), a kind's level set to 0 (-W<kind>=0, which switches off a kind that takes a level: gcc's manual says it of
# -Wformat=0), -fpermissive, and -w, alone or as what a -D gives. WEAKER is for one word of an argv; WEAKER_TEXT finds
# them in a file's text. There its bare -w would also name a `[ -w file ]` or a `grep -w`: none is in the four scripts
# or the library today, and one that comes has to be told from a flag here.
WEAKER = re.compile(r"-Wno-|-W[A-Za-z][A-Za-z0-9+-]*=0(?![0-9])|-fpermissive|(?:^|=)-w$")
WEAKER_TEXT = re.compile(r"-Wno-[A-Za-z0-9=_+-]*|-W[A-Za-z][A-Za-z0-9+-]*=0(?![0-9])|-fpermissive|(?<![A-Za-z0-9_-])-w(?![A-Za-z0-9_=-])")
# The environment's words a compiler driver or cmake takes flags from. No build script sets one.
FLAG_ENV = ("CXXFLAGS", "CFLAGS", "CPPFLAGS", "LDFLAGS")

BOOST_V = ("libboost1.74-dev", "libboost-system1.74-dev", "libboost-thread1.74-dev", "libboost-filesystem1.74-dev")
BOOST_U = ("libboost-system-dev", "libboost-thread-dev", "libboost-filesystem-dev")
V174, U183, U174 = "1.74.0-v1", "1.83.0-u1", "1.74.0-j1"
VERSIONED = {p: V174 for p in BOOST_V}

# A host with under 8 GB and no swap, one with more memory, and the small one with swap.
SMALL = ("MemTotal:        7000000 kB\nMemFree:         5000000 kB\nSwapCached:            0 kB\n"
         "SwapTotal:             0 kB\nSwapFree:              0 kB\n")
BIG = SMALL.replace("7000000", "32000000")
SMALL_WITH_SWAP = SMALL.replace("SwapTotal:             0 kB", "SwapTotal:       3000000 kB")
CGROUP_LINE = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/run-stub.scope"

# cmake's own words for a CUDA component it cannot find, in the two forms the llama.cpp configure
# can end in; and a failure that names nothing.
MISSING_CUDART = ('CMake Error at /usr/share/cmake/Modules/FindPackageHandleStandardArgs.cmake:230 (message):\n'
                  '  Could NOT find CUDAToolkit (missing: CUDA_CUDART) (found version "0.0")\n'
                  'Call Stack (most recent call first):\n-- Configuring incomplete, errors occurred!\n')
MISSING_CUBLAS = ('CMake Error at ggml/src/ggml-cuda/CMakeLists.txt:1 (target_link_libraries):\n  Target "ggml-cuda" links to:\n\n'
                  '    CUDA::cublas\n\n  but the target was not found.  Possible reasons include:\n\n'
                  '-- Generating done\nCMake Generate step failed.  Build files cannot be regenerated correctly.\n')
MISSING_NOTHING = "CMake Error: The source directory does not appear to contain CMakeLists.txt.\n"

# ------------------------------------------------------------------ the stubs

STUB_HEAD = r'''#!/bin/bash
S="$STUB_STATE"
me="${0##*/}"
printf '[%s] %s %s\n' "${STUB_SCOPE:--}" "$me" "$*" >> "$S/calls.log"
# What this call saw of the environment's flag words, CXXFLAGS first: cmake and a compiler read them.
printf '%s|%s|%s|%s\n' "${CXXFLAGS-unset}" "${CFLAGS-unset}" "${CPPFLAGS-unset}" "${LDFLAGS-unset}" >> "$S/flag_env"
st() { local v="${2:-}"; if [ -e "$S/$1" ]; then IFS= read -r v < "$S/$1" || true; fi; printf '%s' "$v"; }
show() { if [ -e "$S/$1" ]; then cat "$S/$1"; fi; }
# What a build leaves where a binary would be: a script that says so when it is run.
built() { printf '#!/bin/bash\necho "%s ran" >> "%s/executed"\n' "${1##*/}" "$S" > "$1"; chmod +x "$1"; }
# A test may keep a stub here until it says go.
hold() { local n=0; [ -e "$S/$1" ] || return 0; : > "$S/holding"; while [ ! -e "$S/go" ] && [ "$n" -lt 2400 ]; do sleep 0.05; n=$((n + 1)); done; }
# Inside a scope (the systemd-run stub says so): by now the kernel has counted, for the scope's
# cgroup, what the test gave this scope. A read before the scope's command ran sees a new
# cgroup's zeros. And where the test has the user manager stop the scope after a kill, every
# process of the scope gets TERM: its first one, which is the library's `step` shell, and this.
# The oom line is how often the cgroup's own limit was reached; oom_kill counts every process of
# the cgroup that the kernel killed for memory, whoever's limit it was.
if [ -n "${STUB_CG:-}" ]; then
	echo "$STUB_PEAK" > "$STUB_CG/memory.peak"
	{
		printf 'low 0\nhigh 0\nmax 0\n'
		if [ "$STUB_OOM" != none ]; then printf 'oom %s\n' "$STUB_OOM"; fi
		printf 'oom_kill %s\noom_group_kill 0\n' "$STUB_KILLS"
	} > "$STUB_CG/memory.events"
	if [ -n "${STUB_STOP:-}" ]; then
		kill "-$STUB_SIG" "$STUB_STOP"; kill "-$STUB_SIG" $$
		sleep 2; echo "$me outlived its $STUB_SIG" >> "$S/term_outlived"; exit 143      # only where TERM came to it ignored
	fi
fi
'''

STUBS = {
    # systemd-run --user --scope -p K=V ... COMMAND: what the real one does that the scripts lean
    # on. It refuses without a user bus (the real tool's own message), it sets the scope's
    # memory.max, it says which unit it made on stderr, and it runs the command with the command's
    # own exit status. A command line with a dollar sign in it is noted: the real tool warns that
    # a later release will expand it.
    "systemd-run": r'''
n="$(st sdrun_calls 0)"; n=$((n + 1)); echo "$n" > "$S/sdrun_calls"
if [ "${1:-}" != --user ] || [ "${2:-}" != --scope ]; then echo "stub systemd-run: unexpected arguments: $*" >&2; exit 64; fi
shift 2
props=""; max=""
while [ "${1:-}" = -p ]; do
	props="${props:+$props,}$2"
	case "$2" in MemoryMax=*) max="${2#MemoryMax=}" ;; esac
	shift 2
done
case "${1:-}" in -*|"") echo "stub systemd-run: unexpected arguments: $*" >&2; exit 64 ;; esac
if [ -e "$S/sdrun_refuse" ] || [ "$n" -ge "$(st sdrun_refuse_from 1000000)" ]; then
	echo "Failed to connect to bus: No medium found" >&2
	exit 1
fi
case "$*" in *'$'*) : > "$S/sdrun_dollar" ;; esac
echo "Running as unit: run-stub$n.scope; invocation ID: stub" >&2
IFS= read -r line < "$SELF_CGROUP"
cg="$CGROUP_FS${line#0::}"
mkdir -p "$cg"
lim=max
if [ -n "$max" ] && [ ! -e "$S/sdrun_nocap" ]; then
	num="${max%[KMGT]}"
	case "$max" in
		*K) lim=$((num * 1024)) ;; *M) lim=$((num * 1024 * 1024)) ;;
		*G) lim=$((num * 1024 * 1024 * 1024)) ;; *T) lim=$((num * 1024 * 1024 * 1024 * 1024)) ;;
		*) lim="$max" ;;
	esac
fi
if [ -e "$S/sdrun_limit" ]; then lim="$(st sdrun_limit)"; fi       # a test says what the kernel holds
echo "$lim" > "$cg/memory.max"
# What the kernel keeps for the scope besides: its peak, and how often it killed for memory. A
# test may give one peak for every call (sdrun_peak), or one a call (sdrun_peaks, line by line),
# and a count of kills for every call (sdrun_oom_kill), or for one call only (sdrun_oom_at). A
# new cgroup has counted nothing: the two files start at zero here, and the first stub that runs
# inside the scope writes what the test gave (STUB_HEAD). With sdrun_oom_stops a scope that
# counts a kill is stopped as the user manager stops one: that stub sends TERM to this process,
# which the exec below makes the scope's first, and to itself. A manager whose policy is `kill`
# sends KILL instead: sdrun_oom_stops holds the word KILL. A kill under the scope's own limit
# counts in the scope's oom line as well. With sdrun_oom_elsewhere the kill was not the scope's
# limit's (the system-wide killer, or a limit above the scope) and the oom line stays 0; with
# sdrun_no_oom_line the kernel gives no such line.
rm -f "$cg/memory.peak" "$cg/memory.events"
STUB_CG=""; STUB_PEAK=""; STUB_KILLS=""; STUB_OOM=""; STUB_STOP=""; STUB_SIG="$(st sdrun_oom_stops)"; STUB_SIG="${STUB_SIG:-TERM}"
if [ ! -e "$S/sdrun_no_stats" ]; then
	STUB_CG="$cg"
	STUB_PEAK="$(st sdrun_peak 300000000)"
	if [ -e "$S/sdrun_peaks" ]; then STUB_PEAK="$(sed -n "${n}p" "$S/sdrun_peaks")"; fi
	STUB_KILLS="$(st sdrun_oom_kill 0)"
	if [ -e "$S/sdrun_oom_at" ] && [ "$(st sdrun_oom_at)" != "$n" ]; then STUB_KILLS=0; fi
	STUB_OOM="$STUB_KILLS"
	if [ -e "$S/sdrun_oom_elsewhere" ]; then STUB_OOM=0; fi
	if [ -e "$S/sdrun_no_oom_line" ]; then STUB_OOM=none; fi
	if [ -e "$S/sdrun_oom_stops" ] && [ "$STUB_KILLS" != 0 ]; then STUB_STOP=$$; fi
	echo 0 > "$cg/memory.peak"
	printf 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n' > "$cg/memory.events"
fi
export STUB_CG STUB_PEAK STUB_KILLS STUB_OOM STUB_STOP STUB_SIG
STUB_SCOPE="$props" exec "$@"
''',
    # git: the words in front of the verb (-c key=value) are in the log, as every argument is, and
    # are skipped here. A .git without the stub's HEAD file is a clone that did not finish, and
    # gets the real git's two answers for one (read from the real git on the PC).
    "git": r'''
echo "${GIT_TERMINAL_PROMPT:-unset}" >> "$S/git_prompt"
while [ "${1:-}" = -c ]; do shift 2; done
if [ "${1:-}" = clone ]; then
	rc="$(st git_clone_rc 0)"
	if [ "$rc" != 0 ]; then echo "fatal: the stub was told to fail the clone" >&2; exit "$rc"; fi
	dir="${!#}"
	mkdir -p "$dir/.git"
	case " $* " in
		*" --branch "*) st git_tag_head > "$dir/.git/STUB_HEAD" ;;
		*) st git_clone_head > "$dir/.git/STUB_HEAD" ;;
	esac
	exit 0
fi
if [ "${1:-}" = -C ]; then
	dir="$2"; shift 2
	if [ ! -d "$dir/.git" ]; then echo "fatal: not a git repository (or any of the parent directories): .git" >&2; exit 128; fi
	case "$*" in
		"rev-parse HEAD")
			if [ ! -e "$dir/.git/STUB_HEAD" ]; then
				echo HEAD
				echo "fatal: ambiguous argument 'HEAD': unknown revision or path not in the working tree." >&2
				exit 128
			fi
			cat "$dir/.git/STUB_HEAD"; echo; exit 0 ;;
		"status --porcelain --untracked-files=no") show git_dirty; exit "$(st git_status_rc 0)" ;;
		"checkout --quiet --detach "*)
			if [ "$(st git_checkout_rc 0)" != 0 ] || [ ! -e "$dir/.git/STUB_HEAD" ]; then echo "fatal: reference is not a tree: $4" >&2; exit 128; fi
			if [ ! -e "$S/git_checkout_stays" ]; then printf '%s' "$4" > "$dir/.git/STUB_HEAD"; fi
			exit 0 ;;
	esac
fi
echo "stub git: unexpected arguments: $*" >&2
exit 64
''',
    "cmake": r'''
case "${1:-}" in
	--version) echo "cmake version 0.0.0-stub"; exit 0 ;;
	--build)
		dir="$2"; kind="$(cat "$dir/STUB_KIND")"
		hold "build_waits_$kind"
		rc="$(st "build_rc_$kind" 0)"
		if [ "$rc" != 0 ]; then echo "stub cmake --build: told to fail"; exit "$rc"; fi
		if [ "$kind" = llama ]; then
			mkdir -p "$dir/bin"; t=0
			for a in "$@"; do
				if [ "$a" = --target ]; then t=1; continue; fi
				case "$a" in -*) t=0 ;; esac
				if [ "$t" = 1 ] && [ ! -e "$S/llama_skips_$a" ]; then built "$dir/bin/$a"; fi
			done
			if [ -e "$S/llama_libs" ]; then echo "stub libllama" > "$dir/bin/libllama.so"; echo "stub libggml-cuda" > "$dir/bin/libggml-cuda.so"; fi
		fi
		exit 0 ;;
	--install)
		dir="$2"; kind="$(cat "$dir/STUB_KIND")"; prefix="$(cat "$dir/STUB_PREFIX")"
		rc="$(st "install_rc_$kind" 0)"
		if [ "$rc" != 0 ]; then echo "stub cmake --install: told to fail"; exit "$rc"; fi
		if [ "$kind" = cyclonedds ]; then
			mkdir -p "$prefix/bin" "$prefix/lib" "$prefix/include/dds"
			if [ -e "$S/real_libddsc" ]; then        # a test with a real compiler: a library a linker takes, under the name it asks for
				cp "$S/real_libddsc" "$prefix/lib/libddsc.so.0.0.0"; ln -sf libddsc.so.0.0.0 "$prefix/lib/libddsc.so"
			elif [ ! -e "$S/no_libddsc" ]; then
				echo "stub libddsc" > "$prefix/lib/libddsc.so.0.0.0"
			fi
			echo "int dds_stub(void);  /* stub dds.h */" > "$prefix/include/dds/dds.h"
			if [ ! -e "$S/no_idlc" ]; then cp "$STUB_BIN/idlc-template" "$prefix/bin/idlc"; chmod +x "$prefix/bin/idlc"; fi
		fi
		exit 0 ;;
esac
bld=""; prefix=""; kind=other
while [ "$#" -gt 0 ]; do
	case "$1" in
		-S) shift ;;
		-B) bld="$2"; shift ;;
		-DCMAKE_INSTALL_PREFIX=*) prefix="${1#*=}" ;;
		-Dvsomeip3_DIR=*) kind=probe ;;
		-DENABLE_SIGNAL_HANDLING=*) kind=vsomeip ;;
		-DBUILD_IDLC=*) kind=cyclonedds ;;
		-DGGML_CUDA=*) kind=llama ;;
	esac
	shift
done
mkdir -p "$bld"
echo "$kind" > "$bld/STUB_KIND"
echo "$prefix" > "$bld/STUB_PREFIX"
if [ -e "$S/cmake_fail_$kind" ]; then cat "$S/cmake_fail_$kind"; exit 1; fi
{ echo "CMAKE_INSTALL_PREFIX:PATH=$prefix"; if [ "$kind" = vsomeip ]; then show boost_dir_line; fi; } > "$bld/CMakeCache.txt"
echo "-- Configuring done (stub)"
''',
    "make": r'''
dir=""; inst=0
while [ "$#" -gt 0 ]; do
	case "$1" in -C) dir="$2"; shift ;; install) inst=1 ;; esac
	shift
done
kind="$(cat "$dir/STUB_KIND")"
if [ "$inst" = 0 ]; then
	hold "make_waits_$kind"
	rc="$(st "make_rc_$kind" 0)"
	if [ "$rc" != 0 ]; then echo "make: *** [stub] Error $rc"; exit "$rc"; fi
	if [ "$kind" = probe ] && [ ! -e "$S/probe_stays" ]; then built "$dir/someip_vprobe"; fi        # probe_stays: "is up to date"
	exit 0
fi
rc="$(st "install_rc_$kind" 0)"
if [ "$rc" != 0 ]; then echo "make: *** [install] Error $rc"; exit "$rc"; fi
prefix="$(cat "$dir/STUB_PREFIX")"
mkdir -p "$prefix/lib/cmake/vsomeip3"
for l in "" -cfg -sd; do echo "stub libvsomeip3$l" > "$prefix/lib/libvsomeip3$l.so.3.4.10"; done
if [ -e "$S/with_symlinks" ]; then ln -s libvsomeip3.so.3.4.10 "$prefix/lib/libvsomeip3.so.3"; fi
''',
    # gcc, g++ and nvcc: a version line, or an output where -o says.
    "gcc": r'''
if [ "${1:-}" = --version ]; then echo "$me (Stub 0.0-s1) 0.0.0"; echo "Copyright (C) nobody"; exit 0; fi
out=""; prev=""
for a in "$@"; do if [ "$prev" = -o ]; then out="$a"; fi; prev="$a"; done
rc="$(st "${me}_rc" 0)"
if [ "$rc" != 0 ]; then echo "$me: the stub was told to fail"; exit "$rc"; fi
if [ -n "$out" ]; then built "$out"; fi
''',
    "idlc-template": r'''
printf '%s\n%s\n' "$PWD" "${LD_LIBRARY_PATH:-}" > "$S/idlc_env"
rc="$(st idlc_rc 0)"
if [ "$rc" != 0 ]; then echo "idlc: the stub was told to fail"; exit "$rc"; fi
if [ ! -e "$S/idlc_noout" ]; then echo "/* av.c, from the stub idlc */" > av.c; echo "/* av.h, from the stub idlc */" > av.h; fi
''',
    "dpkg-query": r'''
if [ "$1" != -W ] || [ "$2" != '-f=${Package}|${Status}|${Version}\n' ]; then echo "stub dpkg-query: unexpected arguments: $*" >&2; exit 64; fi
shift 2
rc=0
for p in "$@"; do
	found=""
	for f in installed residual; do
		[ -e "$S/$f" ] || continue
		while read -r k v; do
			if [ "$k" = "$p" ] && [ -z "$found" ]; then
				found=1
				if [ "$f" = installed ]; then echo "$p|install ok installed|$v"; else echo "$p|deinstall ok config-files|$v"; fi
			fi
		done < "$S/$f"
	done
	if [ -z "$found" ]; then echo "dpkg-query: no packages found matching $p" >&2; rc=1; fi
done
exit "$rc"
''',
    "bison": 'echo "bison (GNU Bison) 0.0-stub"\n',
    # No build script may call sudo. This one fails, so a call would also show as a failed run.
    "sudo": 'echo "sudo: the stub refuses" >&2\nexit 1\n',
}
STUBS["g++"] = STUBS["gcc"]
NVCC_STUB = STUBS["gcc"].replace(
    'echo "$me (Stub 0.0-s1) 0.0.0"; echo "Copyright (C) nobody"',
    'echo "nvcc: NVIDIA (R) Cuda compiler driver"; echo "Cuda compilation tools, release 0.0, V0.0.0-stub"')
FLOCK_STUB = "exit 0\n"

BUILD_TOOLS = ("cmake", "make", "gcc", "g++", "nvcc", "idlc")


def _fwd(p):
    return str(p).replace("\\", "/")


_SPELT = {}


def _bash_spells(path):
    """How the scripts' shell spells a directory it has gone to (`cd`, then `pwd`). Asked once a
    directory. Git Bash on Windows has names of its own: a drive is /c, and the user's temporary
    directory is /tmp, wherever it is."""
    if path not in _SPELT:
        _SPELT[path] = subprocess.run([BASH, "-c", 'cd "$1" && pwd', "_", path], capture_output=True, text=True, timeout=60,
                                      check=True).stdout.rstrip("\n")
    return _SPELT[path]


def _abs_sh(path):
    """An absolute path as a POSIX shell knows one. Git Bash on Windows: C:/x is /c/x."""
    p = _fwd(path)
    return "/%s%s" % (p[0].lower(), p[2:]) if os.name == "nt" else p


def _put(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(text.encode())


def _text(path):
    with open(str(path), "rb") as f:
        return f.read().decode("utf-8")


def _sha(path):
    with open(str(path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _code(text):
    """A shell script's text without its comments: full-line comments and a trailing ` # ...`."""
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s#\s.*$", "", line))
    return "\n".join(out)


class Call:
    """One line of the stubs' log: the scope the stub ran in ("-" for none), its name, its argv."""

    def __init__(self, line):
        m = re.match(r"^\[([^\]]*)\] (\S+) ?(.*)$", line)
        assert m, line
        self.line, self.scope, self.name, self.args = line, m.group(1), m.group(2), m.group(3).split()

    def __repr__(self):
        return self.line


class Host:
    """A made-up host under one directory: a home, the stubs and their state, a /proc/meminfo, a
    cgroup tree, a /usr/local with one CUDA toolkit, and a directory with the two peers' sources.
    The defaults are the board after provisioning, in shape: under 8 GB, no swap, the versioned
    Boost 1.74 set, one nvcc."""

    def __init__(self, root):
        self.root = root
        self.home, self.state, self.bin = root / "home", root / "state", root / "bin"
        self.cg, self.usr_local, self.peers = root / "cgroup", root / "usr-local", root / "peers"
        for d in (self.home, self.state, self.bin, self.cg, self.usr_local):
            d.mkdir(parents=True)
        self.meminfo, self.self_cgroup = root / "meminfo", root / "self-cgroup"
        _put(self.meminfo, SMALL)
        _put(self.self_cgroup, CGROUP_LINE + "\n")
        for n, body in STUBS.items():
            _put(self.bin / n, STUB_HEAD + body)
        if FLOCK is None:
            _put(self.bin / "flock", STUB_HEAD + FLOCK_STUB)
        self.nvcc = self.usr_local / "cuda-0.0" / "bin" / "nvcc"
        _put(self.nvcc, STUB_HEAD + NVCC_STUB)
        for p in list(self.bin.iterdir()) + [self.nvcc]:
            p.chmod(0o755)
        _put(self.peers / "pubbad.c", "/* a made-up pubbad.c */\n")
        _put(self.peers / "subv.c", "/* a made-up subv.c */\n")
        self.packages(VERSIONED)
        self.set("git_tag_head", VSOMEIP_PIN)
        self.set("git_clone_head", NOT_A_PIN)
        # where the scripts put things, by default
        self.builds = self.home / "builds"
        self.vs_prefix, self.vs_src = self.home / "vsomeip" / "3.4.10", self.home / "vsomeip" / "src-3.4.10"
        self.dds_prefix, self.dds_src = self.home / "cyclonedds" / CDDS_PIN, self.home / "cyclonedds" / "src"
        self.dds_build = self.home / "cyclonedds" / ("build-" + CDDS_PIN)
        self.llama_src = self.home / "llama.cpp"
        self.llama_bin = self.llama_src / "build" / "bin"
        self.fma = self.home / "gpuload" / "fma"
        self.info = {"vsomeip": self.vs_prefix / "BUILD-INFO", "cyclonedds": self.dds_prefix / "BUILD-INFO",
                     "llama": self.llama_bin / "BUILD-INFO", "fma": self.home / "gpuload" / "BUILD-INFO"}
        # How the script's shell spells HOME, and this checkout. Git Bash on Windows rewrites the
        # HOME it is given (C:/Users/x/AppData/Local/Temp/y becomes /tmp/y), and a script that
        # finds its own directory with `cd` and `pwd` gets the checkout's path the same way: a
        # clone under the user's temporary directory is /tmp/... to it. Elsewhere both are the
        # paths as given.
        self.home_sh, self.repo_sh = _fwd(self.home), _fwd(REPO)
        if os.name == "nt":
            self.home_sh = subprocess.run([BASH, "-c", 'printf %s "$HOME"'], capture_output=True, text=True, timeout=60,
                                          env=self.env(), check=True).stdout
            self.repo_sh = _bash_spells(_fwd(REPO))

    def canon(self, s):
        """One spelling for every path in what a script or a stub wrote: this file's own. On
        Windows the script's shell spells HOME and the checkout its own way, and any other path
        it worked out with `pwd` or `readlink` comes as /c/x for C:/x. Elsewhere nothing is
        changed."""
        if os.name != "nt":
            return s
        s = s.replace(self.home_sh, _fwd(self.home)).replace(self.repo_sh, _fwd(REPO))
        return re.sub(r"(^|[ (=])/([A-Za-z])/", lambda m: m.group(1) + m.group(2).upper() + ":/", s, flags=re.M)

    def read_calls(self):
        calls = self.state / "calls.log"
        return [Call(self.canon(l)) for l in _text(calls).splitlines()] if calls.exists() else []

    def info_text(self, which):
        return self.canon(_text(self.info[which]))

    def set(self, name, text=""):
        _put(self.state / name, text)

    def unset(self, name):
        p = self.state / name
        if p.exists():
            p.unlink()

    def packages(self, installed, residual=None):
        self.set("installed", "".join("%s %s\n" % kv for kv in installed.items()))
        self.set("residual", "".join("%s %s\n" % kv for kv in (residual or {}).items()))

    def env(self, **env):
        e = dict(os.environ, STUB_STATE=_fwd(self.state), STUB_BIN=_fwd(self.bin), HOME=_fwd(self.home),
                 MEMINFO=_fwd(self.meminfo), SELF_CGROUP=_fwd(self.self_cgroup), CGROUP_FS=_fwd(self.cg),
                 CUDA_BASE=_fwd(self.usr_local), PATH=_fwd(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        for k in ("JOBS", "MEM_MAX", "NVCC", "PEER_SRC", "CC", "PREFIX", "SRC", "BUILD", "OUT", "BUILD_STATE", "STUB_SCOPE",
                  "STUB_CG", "STUB_PEAK", "STUB_KILLS", "STUB_OOM", "STUB_STOP", "STUB_SIG",
                  "VSOMEIP_TAG", "VSOMEIP_COMMIT", "VSOMEIP_URL", "CDDS_COMMIT", "CDDS_URL", "LLAMA_COMMIT", "LLAMA_URL",
                  "LD_LIBRARY_PATH") + FLAG_ENV:
            e.pop(k, None)
        for k in [k for k in e if k.startswith("GIT_")]:    # no git setting of the session that runs pytest reaches a script
            e.pop(k)
        e.update(env)
        return e

    def defaults(self, which, env):
        """The environment a script needs for its whole job: the peers' sources for Cyclone."""
        if which == "cyclonedds" and "PEER_SRC" not in env:
            env = dict(env, PEER_SRC=_fwd(self.peers))
        return env

    def _read(self, r):
        r.calls = self.read_calls()
        r.out = self.canon(r.stdout.replace("\r\n", "\n"))
        r.err = self.canon(r.stderr.replace("\r\n", "\n"))
        r.all = r.out + r.err
        return r

    def run(self, which, _cwd=None, **env):
        calls = self.state / "calls.log"
        if calls.exists():
            calls.unlink()
        self.unset("sdrun_calls")
        self.unset("git_prompt")
        self.unset("flag_env")
        r = subprocess.run([BASH, _fwd(SCRIPTS[which])], capture_output=True, text=True, timeout=300, cwd=_cwd,
                           env=self.env(**self.defaults(which, env)), stdin=subprocess.DEVNULL)
        return self._read(r)

    def start(self, which, **env):
        """The script as the leader of a session of its own, which is what setsid makes of it."""
        calls = self.state / "calls.log"
        if calls.exists():
            calls.unlink()
        self.unset("sdrun_calls")
        return subprocess.Popen([BASH, _fwd(SCRIPTS[which])], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                stdin=subprocess.DEVNULL, env=self.env(**self.defaults(which, env)), start_new_session=True)

    def status(self, which):
        return subprocess.run([BASH, _fwd(LIB), "status", NAMES[which]], capture_output=True, text=True, timeout=60,
                              env=self.env(), stdin=subprocess.DEVNULL)

    def done(self, which):
        """The lines of the script's done-file, or None when there is none."""
        p = self.builds / (NAMES[which] + ".done")
        return _text(p).splitlines() if p.exists() else None

    def executed(self):
        p = self.state / "executed"
        return _text(p).splitlines() if p.exists() else []

    def flag_env(self):
        """What each stub of the last run saw of FLAG_ENV's words, a line a call: "unset" for one that was not set."""
        p = self.state / "flag_env"
        return _text(p).splitlines() if p.exists() else []

    def wait_for(self, name, proc, seconds=60.0):
        """Until a stub says it is holding. A script that has ended will never get there."""
        end = time.time() + seconds
        while time.time() < end and proc.poll() is None:
            if (self.state / name).exists():
                return
            time.sleep(0.05)
        raise AssertionError("the stubs never reached %s; the script %s" % (
            name, "is still running" if proc.poll() is None else "ended with %s: %s" % (proc.returncode, proc.stdout.read())))

    def calls_now(self):
        return self.read_calls()


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path / "host")


def tools(calls, *names):
    """The stubs' calls that are part of a build: not a version question, not systemd-run itself."""
    names = names or BUILD_TOOLS
    return [c for c in calls if c.name in names and c.args[:1] != ["--version"]]


def scopes(calls):
    return [c for c in calls if c.name == "systemd-run"]


def clones(calls):
    return [c for c in calls if c.name == "git" and "clone" in c.args]


def step_cmd(host, scope):
    """The command one scope was made for: what follows the library's `step` words."""
    assert scope.args[:6] == CAP_ARGV or scope.args[3].startswith("MemoryMax="), scope
    assert scope.args[6:11] == ["bash", _fwd(LIB), "step", _fwd(host.self_cgroup), _fwd(host.cg)], scope
    assert re.match(r"^%s/build-[a-z0-9-]+\.step$" % re.escape(_fwd(host.builds)), scope.args[11]), scope
    return scope.args[12:]


def uncapped(calls):
    """Every build call that did not run inside a scope with both properties."""
    return [c for c in tools(calls) if c.scope != CAP]


def jobs_of(calls, which):
    """The job counts on the build lines of one script, as the stubs saw them."""
    out = []
    for c in tools(calls, "make", "cmake"):
        if which == "vsomeip" and c.name == "make":
            out += [a[2:] for a in c.args if re.match(r"^-j\d+$", a)]
        if which != "vsomeip" and c.name == "cmake" and c.args[:1] == ["--build"]:
            out += [c.args[i + 1] for i, a in enumerate(c.args) if a == "--parallel"]
    return out


def info_lines(host, which):
    return host.info_text(which).splitlines()


def one(lines, start):
    got = [l for l in lines if l.startswith(start)]
    assert len(got) == 1, "one line that starts with %r, got %r" % (start, got)
    return got[0]


def outputs(host, which):
    """What a finished build leaves that a later step would run or load."""
    return {
        "vsomeip": [host.vs_prefix / "bin" / "someip_vprobe"],
        "cyclonedds": [host.dds_prefix / "bin" / "pubbad", host.dds_prefix / "bin" / "subv"],
        "llama": [host.llama_bin / n for n in ("llama-server", "llama-cli", "llama-bench")],
        "fma": [host.fma],
    }[which]


# ------------------------------------------------------------------ the files themselves

@pytest.mark.parametrize("which", ALL)
def test_a_build_script_has_its_header_its_phase_tag_and_unix_line_ends(which):
    text = _text(SCRIPTS[which])
    assert text.startswith("#!/usr/bin/env bash\n") and "\r" not in text
    head = text.split("\nset -euo pipefail\n")[0]
    assert head != text, "one `set -euo pipefail` line of its own ends the header"
    assert re.search(r"\(Phase 3b / A6, \d{4}-\d\d-\d\d", head), "the header carries its Phase tag"
    assert "%s.sh -- " % NAMES[which] in head.split("\n")[1]


def test_the_library_has_its_header_and_is_sourced_by_all_four():
    text = _text(LIB)
    assert text.startswith("# lib-build.sh -- ") and "\r" not in text
    assert re.search(r"Phase 3b / A6, \d{4}-\d\d-\d\d", text.split("\nBUILD_LIB_LOADED=1\n")[0])
    for which in ALL:
        code = _code(_text(SCRIPTS[which]))
        assert len(re.findall(r'^\. "\$here/[./a-z-]*lib-build\.sh"$', code, re.M)) == 1, which
        assert '[ "${BUILD_LIB_LOADED:-}" = 1 ]' in code, which
        assert re.search(r"^b_begin %s$" % NAMES[which], code, re.M), "%s takes the lock and the done-file under its own name" % which


def test_the_vsomeip_header_no_longer_describes_the_r36_host():
    """Gap 4e: the two header lines that named Ubuntu 22.04 are rewritten, and the Phase tag and
    the date the script was first written stay."""
    head = _text(SCRIPTS["vsomeip"]).split("\nset -euo pipefail\n")[0]
    assert "22.04, Boost 1.74)" not in head and "Ubuntu 22.04's Boost 1.74" not in head
    assert "(Phase 3b / A6, 2026-09-27, OD12)" in head
    assert "Ubuntu 24.04" in head and "universe" in head and "1.83" in head
    for p in BOOST_V + BOOST_U:
        assert p in _text(SCRIPTS["vsomeip"]), p


@pytest.mark.parametrize("which", ALL + ["lib"])
def test_no_build_script_has_a_sudo_in_it(which):
    code = _code(_text(LIB if which == "lib" else SCRIPTS[which]))
    assert not re.search(r"\bsudo\b", code), "not as a command and not as advice in a message"


@pytest.mark.parametrize("which", ALL)
def test_every_build_command_in_the_text_goes_through_the_cap(which):
    """A text test beside the behavioural one: no line of code starts a compiler, cmake or make
    by itself. Version questions sit inside $( ) and do not start a line."""
    code = re.sub(r"\\\n\s*", " ", _code(_text(SCRIPTS[which])))            # a continued line is one line
    bare = [l for l in code.split("\n")
            if re.match(r'^\s*(\(\s*cd [^&]*&&\s*)?(env [^"]*)?(cmake|make|gcc|g\+\+|nvcc|"\$NVCC"|"\$CC"|"\$PREFIX/bin/idlc")(\s|$)', l)]
    assert bare == []
    steps = re.findall(r"^\s*(?:if ! )?(b_step|b_try) ", code, re.M)
    assert len(steps) == {"vsomeip": 5, "cyclonedds": 5, "llama": 2, "fma": 1}[which], steps
    assert "capped" not in code and "systemd-run" not in code, "the scope is the library's to ask for, in one place"


def test_the_cap_is_one_function_with_no_way_round_it():
    code = _code(_text(LIB))
    assert '\ncapped() { systemd-run --user --scope -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 "$@"; }\n' in code
    assert '\nMEM_MAX="${MEM_MAX:-4G}"\n' in code
    assert '\n\tcapped bash "$B_LIB" step "$SELF_CGROUP" "$CGROUP_FS" "$stats" "$@" > "$log" 2>&1 || rc=$?\n' in code
    assert code.count("capped bash ") == 2 and len(re.findall(r"\bcapped\b(?! scope)", code)) == 3, \
        "its definition, the question at the start, and every build step: nothing else makes a scope"
    assert len(re.findall(r"\bsystemd-run --user --scope -p", code)) == 1, "the one place a scope is asked for"
    assert len(re.findall(r"(^|[;&|({]\s*)systemd-run\b", code, re.M)) == 1, "and nothing but capped starts systemd-run"
    assert not re.search(r"UNCAPPED|NO_CAP|SKIP_CAP|ALLOW_", code), "no switch builds without the cap"


def test_the_pins_are_the_ones_the_repo_already_holds():
    assert 'COMMIT="${VSOMEIP_COMMIT:-%s}"' % VSOMEIP_PIN in _text(SCRIPTS["vsomeip"])
    line = 'CDDS_COMMIT="${CDDS_COMMIT:-%s}"' % CDDS_PIN
    assert line in _text(SCRIPTS["cyclonedds"]) and line in _text(os.path.join(DDS, "build-cyclonedds-qnx.sh")), \
        "both halves of the Cyclone build are at one commit"
    assert 'LLAMA_COMMIT="${LLAMA_COMMIT:-%s}"' % LLAMA_PIN in _text(SCRIPTS["llama"])


def test_the_cyclone_switches_are_the_qnx_script_s_with_two_changed_on_purpose():
    qnx = dict(re.findall(r"-D((?:BUILD|ENABLE)_[A-Z0-9_]+)=(ON|OFF)", _text(os.path.join(DDS, "build-cyclonedds-qnx.sh"))))
    l4t = dict(re.findall(r"-D((?:BUILD|ENABLE)_[A-Z0-9_]+)=(ON|OFF)", _code(_text(SCRIPTS["cyclonedds"]))))
    assert qnx["BUILD_SHARED_LIBS"] == "OFF" and qnx["BUILD_IDLC"] == "OFF" and len(qnx) == 10
    assert l4t == dict(qnx, BUILD_SHARED_LIBS="ON", BUILD_IDLC="ON")


def test_the_peers_sources_are_not_in_the_repo():
    """The owner's decision: pubbad.c and subv.c stay on the board. So no test here can compile
    them, and the build script takes them from PEER_SRC."""
    for d, _dirs, names in os.walk(os.path.join(REPO, "ipc-test")):
        assert "pubbad.c" not in names and "subv.c" not in names, d
    assert 'PEER_SRC="${PEER_SRC:-}"' in _text(SCRIPTS["cyclonedds"])


# ------------------------------------------------------------------ every script: the whole build

@pytest.mark.parametrize("which", ALL)
def test_a_build_ends_well_and_leaves_its_build_info_and_a_done_file(host, which):
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert host.done(which)[0] == "0"
    started = _text(host.builds / (NAMES[which] + ".started")).splitlines()
    assert len(started) == 2 and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", started[0]) and re.match(r"^pid \d+$", started[1])
    lines = info_lines(host, which)
    assert host.info_text(which).endswith("\n") and all(lines), "BUILD-INFO is whole lines"
    assert host.info_text(which) in r.out, "and it is printed, so the build's log holds it too"
    for out in outputs(host, which):
        assert out.exists(), out
        assert [l for l in lines if l.startswith("%s sha256 %s" % (out.name, _sha(out)))], "BUILD-INFO holds the sha256 of %s" % out.name
    assert one(lines, "memory cap ") == ("memory cap MemoryMax=4G MemorySwapMax=0 by systemd-run --user --scope; "
                                         "the scope's memory.max read back as %s" % FOUR_G)
    assert one(lines, "build steps ") == ("build steps %d, each in a scope of its own; the largest memory.peak 300000000 bytes; "
                                          "oom_kill 0" % len(tools(r.calls)))
    assert not [c for c in r.calls if c.name == "sudo"]
    assert not list(host.builds.glob("*.step")) and not list(host.builds.glob("*.tmp"))


@pytest.mark.parametrize("which", ALL)
def test_nothing_that_was_built_is_ever_executed(host, which):
    """The outputs here are scripts that leave a line when run. fma started without arguments is
    a 30 s GPU load, a CUDA build of llama.cpp may initialise CUDA before it reads --version, and
    the peers and the probe open sockets: none is started, not for a version string either."""
    host.set("llama_libs")
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert host.executed() == []
    for out in outputs(host, which):
        subprocess.run([BASH, _fwd(out)], check=True, env=host.env(), timeout=60)      # the marker does work
    assert len(host.executed()) == len(outputs(host, which))


@pytest.mark.parametrize("which", ALL)
def test_every_build_step_runs_inside_the_capped_scope(host, which):
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert tools(r.calls), "the stubs were called"
    assert uncapped(r.calls) == []
    for c in scopes(r.calls):
        assert c.args[:6] == CAP_ARGV, c
        assert c.scope == "-", "a scope is not asked for from inside a scope"
    # the first scope is the question whether the cap holds; then one scope for each build call, in order
    assert scopes(r.calls)[0].args[6:] == ["bash", _fwd(LIB), "memory-max", _fwd(host.self_cgroup), _fwd(host.cg)]
    assert len(scopes(r.calls)) == 1 + len(tools(r.calls))
    for scope, tool in zip(scopes(r.calls)[1:], tools(r.calls)):
        cmd = step_cmd(host, scope)
        assert [a for a in cmd if a.rsplit("/", 1)[-1] == tool.name], (scope, tool)
        assert cmd[len(cmd) - len(tool.args):] == tool.args, (scope, tool)
    assert not (host.state / "sdrun_dollar").exists(), "no command line handed to systemd-run holds a dollar sign"


@pytest.mark.parametrize("which", ALL)
def test_a_refused_systemd_run_stops_the_script_and_nothing_is_built(host, which):
    host.set("sdrun_refuse")
    r = host.run(which)
    assert r.returncode == 1
    assert "Failed to connect to bus" in r.err, "systemd-run's own message is shown"
    assert "systemd-run refused" in r.err and "Nothing is built without the memory cap" in r.err
    assert tools(r.calls) == [], "not capped, so not built: there is no uncapped build"
    assert not host.info[which].exists() and not any(o.exists() for o in outputs(host, which))
    assert host.done(which)[0] == "1"


@pytest.mark.parametrize("which", ALL)
def test_a_scope_that_is_refused_later_does_not_turn_into_an_uncapped_build(host, which):
    """The question at the start is answered, and systemd-run refuses from the next call on."""
    host.set("sdrun_refuse_from", "2")
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert tools(r.calls) == []
    assert not host.info[which].exists()
    assert host.done(which)[0] == "1"


@pytest.mark.parametrize("which", ALL)
def test_a_scope_whose_limit_is_not_the_one_asked_for_stops_the_script(host, which):
    """systemd-run makes the scope and the memory controller is not there for it: memory.max
    reads `max`. Accepted is not the same as in force."""
    host.set("sdrun_nocap")
    r = host.run(which)
    assert r.returncode == 1
    assert "memory.max reads 'max'" in r.err and "not in force" in r.err
    assert tools(r.calls) == [] and not host.info[which].exists()
    assert host.done(which)[0] == "1"


@pytest.mark.parametrize("limit, taken", [(str(8 * 1024 ** 3), False), (str(4 * 1024 ** 3 + 1), False), ("0", False), ("", False),
                                          ("4G", False), ("-1", False), (str(4 * 1024 ** 3 - 4096), True), (FOUR_G, True)],
                         ids=["twice-the-cap", "one-byte-over", "zero", "nothing", "not-a-number", "negative", "a-page-under", "the-cap"])
def test_the_limit_read_back_is_the_cap_or_tighter_and_nothing_else(host, limit, taken):
    host.set("sdrun_limit", limit)
    r = host.run("fma")
    if taken:
        assert r.returncode == 0, r.all
        assert one(info_lines(host, "fma"), "memory cap ").endswith(" read back as %s" % limit)
    else:
        assert r.returncode == 1 and "the cap is not in force" in r.err, r.all
        assert tools(r.calls) == [] and len(scopes(r.calls)) == 1 and not host.fma.exists()


@pytest.mark.parametrize("which", ALL)
def test_a_cgroup_line_that_is_not_v2_cannot_be_read_back_and_stops_the_script(host, which):
    _put(host.self_cgroup, "12:memory:/user.slice\n0::/user.slice/x.scope\n")
    r = host.run(which)
    assert r.returncode == 1
    assert "Nothing is built without the memory cap" in r.err and tools(r.calls) == []


@pytest.mark.parametrize("which", ALL)
def test_another_cap_is_passed_on_and_checked(host, which):
    r = host.run(which, MEM_MAX="512M")
    assert r.returncode == 0, r.all
    assert all(c.args[:6] == ["--user", "--scope", "-p", "MemoryMax=512M", "-p", "MemorySwapMax=0"] for c in scopes(r.calls))
    assert all(c.scope == "MemoryMax=512M,MemorySwapMax=0" for c in tools(r.calls))
    assert "memory cap MemoryMax=512M MemorySwapMax=0" in one(info_lines(host, which), "memory cap ")
    assert one(info_lines(host, which), "memory cap ").endswith(" read back as %d" % (512 * 1024 ** 2))


@pytest.mark.parametrize("bad", ["", "infinity", "0", "0G", "4g", "4 G", "-1G", "4096", "max", "4G -p MemoryMax=infinity", "1000000000G"])
def test_a_cap_that_is_no_cap_is_refused_before_anything_runs(host, bad):
    r = host.run("fma", MEM_MAX=bad)
    if bad == "":
        assert r.returncode == 0 and scopes(r.calls)[0].args[:6] == CAP_ARGV, "an empty MEM_MAX is the default, not no cap"
        return
    assert r.returncode == 1 and "MEM_MAX" in r.err and "is not a cap this script takes" in r.err
    assert scopes(r.calls) == [] and tools(r.calls) == []


@pytest.mark.parametrize("which", ALL)
def test_a_cap_as_large_as_the_host_s_memory_is_no_cap_and_is_refused(host, which):
    """A scope's memory.max is whatever was asked for: the kernel takes a limit the host cannot
    back, and reads it back as asked. Under such a cap an over-large build is not killed inside
    its own cgroup; the system-wide killer ends it, or reclaim does not end it at all, which is
    the hang the cap is there to prevent. The small host has 7000000 kB."""
    r = host.run(which, MEM_MAX="8G")
    assert r.returncode == 1, r.all
    assert "MEM_MAX=8G" in r.err and "MemTotal is 7000000 kB" in r.err and _fwd(host.meminfo) in r.err
    assert scopes(r.calls) == [], "refused before a scope is asked for"
    assert tools(r.calls) == [] and not [c for c in r.calls if c.name == "git"]
    assert not host.info[which].exists() and host.done(which)[0] == "1"


@pytest.mark.parametrize("cap, taken", [("8G", False), ("7G", False), ("7000000K", False), ("6G", False), ("5300M", False),
                                        ("5299M", True), ("5G", True), ("4G", True)])
def test_a_cap_leaves_the_rest_of_the_host_its_memory(host, cap, taken):
    """Below MemTotal less what everything that is not the build keeps: on the small host,
    7000000 kB less the rest, which lies between 5299M and 5300M."""
    assert 5299 * 1024 < 7000000 - REST_KB <= 5300 * 1024
    r = host.run("fma", MEM_MAX=cap)
    if taken:
        assert r.returncode == 0, r.all
        assert scopes(r.calls)[0].args[3] == "MemoryMax=" + cap and tools(r.calls)[0].scope == "MemoryMax=%s,MemorySwapMax=0" % cap
    else:
        assert r.returncode == 1 and "MEM_MAX=%s" % cap in r.err and "MemTotal is 7000000 kB" in r.err, r.all
        assert "below %d kB" % (7000000 - REST_KB) in r.err, "the message says what this host would take"
        assert scopes(r.calls) == [] and tools(r.calls) == [] and not host.fma.exists()


def test_the_rest_of_the_host_is_counted_to_the_kilobyte(host):
    four_g_kb = 4 * 1024 * 1024
    for kb, taken in ((four_g_kb + REST_KB, False), (four_g_kb + REST_KB + 1, True)):
        _put(host.meminfo, "MemTotal:        %d kB\nSwapTotal:             0 kB\n" % kb)
        r = host.run("fma")
        assert (r.returncode == 0) == taken, (kb, r.all)
        if not taken:
            assert "MEM_MAX=4G" in r.err and "MemTotal is %d kB" % kb in r.err and scopes(r.calls) == []


def test_a_host_with_the_memory_takes_a_larger_cap(host):
    _put(host.meminfo, BIG)
    r = host.run("fma", MEM_MAX="8G")
    assert r.returncode == 0, r.all
    assert one(info_lines(host, "fma"), "memory cap ").endswith(" read back as %d" % (8 * 1024 ** 3))


def test_where_memtotal_cannot_be_read_no_cap_above_the_default_is_taken(host):
    for text in (None, "MemTotal:        junk kB\n", "SwapTotal:             0 kB\n"):
        if text is None:
            host.meminfo.unlink()
        else:
            _put(host.meminfo, text)
        for cap in ("5G", "4097M"):
            r = host.run("fma", MEM_MAX=cap)
            assert r.returncode == 1 and "MEM_MAX=%s" % cap in r.err and "MemTotal could not be read" in r.err, (text, cap, r.all)
            assert scopes(r.calls) == [] and tools(r.calls) == []
        for cap in ("4G", "4096M", "512M"):
            r = host.run("fma", MEM_MAX=cap)
            assert r.returncode == 0, (text, cap, r.all)


# ------------------------------------------------------------------ the job count

@pytest.mark.parametrize("which", WITH_JOBS)
@pytest.mark.parametrize("meminfo, want", [(SMALL, "2"), (BIG, "4"), (SMALL_WITH_SWAP, "4")], ids=["small-no-swap", "big", "small-with-swap"])
def test_jobs_defaults_to_two_on_a_host_with_under_8_gb_and_no_swap(host, which, meminfo, want):
    _put(host.meminfo, meminfo)
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert jobs_of(r.calls, which) == [want], "the job count reaches the build's command line"
    assert one(info_lines(host, which), "jobs ").startswith("jobs %s (" % want)
    if want == "2" and meminfo is SMALL:
        assert "under 8 GB and no swap" in one(info_lines(host, which), "jobs ")


@pytest.mark.parametrize("which", WITH_JOBS)
def test_a_meminfo_that_cannot_be_read_gets_the_small_host_s_job_count(host, which):
    for text in (None, "MemTotal:        junk kB\n", "SwapTotal:             0 kB\n"):
        if text is None:
            host.meminfo.unlink()
        else:
            _put(host.meminfo, text)
        r = host.run(which)
        assert r.returncode == 0, r.all
        assert jobs_of(r.calls, which) == ["2"], text
        assert "could not be read" in one(info_lines(host, which), "jobs ")


def test_the_threshold_is_eight_gibibytes_of_memtotal(host):
    for kb, want in ((8 * 1024 * 1024 - 1, "2"), (8 * 1024 * 1024, "4")):
        _put(host.meminfo, "MemTotal:        %d kB\nSwapTotal:             0 kB\n" % kb)
        r = host.run("vsomeip")
        assert r.returncode == 0 and jobs_of(r.calls, "vsomeip") == [want], kb


@pytest.mark.parametrize("which", WITH_JOBS)
def test_a_job_count_in_the_environment_wins(host, which):
    r = host.run(which, JOBS="3")
    assert r.returncode == 0, r.all
    assert jobs_of(r.calls, which) == ["3"]
    assert one(info_lines(host, which), "jobs ") == "jobs 3 (JOBS given)"
    r = host.run(which, JOBS="many")
    assert r.returncode == 1 and "JOBS" in r.err and tools(r.calls) == []


def test_fma_is_one_compiler_call_and_says_so(host):
    r = host.run("fma")
    assert r.returncode == 0 and one(info_lines(host, "fma"), "jobs ") == "jobs 1 (one compiler call)"


@pytest.mark.parametrize("which", ALL)
def test_a_path_a_test_redirects_is_said_out_loud(host, which):
    r = host.run(which)
    for name in ("MEMINFO", "SELF_CGROUP", "CGROUP_FS") + (("CUDA_BASE",) if which in ("llama", "fma") else ()):
        assert re.search(r"^WARNING: %s=\S+ replaces /\S+" % name, r.err, re.M), name


# ------------------------------------------------------------------ the done-file and a second run

@pytest.mark.parametrize("which, knob", [("vsomeip", "make_rc_vsomeip"), ("cyclonedds", "build_rc_cyclonedds"),
                                          ("llama", "build_rc_llama"), ("fma", "nvcc_rc")])
def test_a_failed_build_leaves_a_done_file_with_its_status_and_no_build_info(host, which, knob):
    host.set(knob, "2")
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "FATAL: " in r.err and "failed" in r.err
    done = host.done(which)
    assert done is not None, "a failed build is a finished one: the done-file says how it ended"
    assert done[0] == "1" and re.match(r"^%s ended \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$" % NAMES[which], done[1])
    assert not host.info[which].exists() and host.executed() == []
    assert not (host.builds / (NAMES[which] + ".done.tmp")).exists()


@pytest.mark.parametrize("which, knob, scope", [("vsomeip", "make_rc_vsomeip", 3), ("cyclonedds", "build_rc_cyclonedds", 3),
                                                 ("llama", "build_rc_llama", 3), ("fma", "nvcc_rc", 2)])
def test_a_failed_step_says_whether_the_memory_cap_ended_it(host, which, knob, scope):
    """From the oom_kill count of the step's own cgroup, read inside the scope when the step's
    command has ended: not from the compiler's last words. `scope` is which of the run's scopes
    the failing step is: the first is the question at the start."""
    host.set(knob, "2")
    host.set("sdrun_oom_kill", "3")
    host.set("sdrun_oom_at", str(scope))
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "counts 3 oom_kill: the memory cap (4G) was hit" in r.err and "ended well all the same" not in r.err
    # what to do about it: fewer jobs, where there is more than one
    assert ("It ran one job at a time" in r.err) == (which == "fma") and ("Run again with JOBS=1" in r.err) == (which != "fma")
    if which != "fma":
        r = host.run(which, JOBS="1")
        assert "It ran one job at a time" in r.err and "Run again with JOBS=1" not in r.err
    host.set("sdrun_oom_kill", "0")
    r = host.run(which)
    assert r.returncode == 1 and "counts no oom_kill: the memory cap did not end it" in r.err and "was hit" not in r.err
    host.set("sdrun_no_stats")
    r = host.run(which)
    assert r.returncode == 1 and "could not be read" in r.err and "is not known" in r.err and "was hit" not in r.err


@pytest.mark.parametrize("which, scope", [("vsomeip", 3), ("cyclonedds", 3), ("llama", 3), ("llama", 2), ("fma", 2)],
                         ids=["vsomeip", "cyclonedds", "llama-build", "llama-configure", "fma"])
def test_a_step_the_user_manager_stopped_after_a_kill_still_says_the_cap_ended_it(host, which, scope):
    """systemd's user manager does not leave a scope running in which the kernel has killed for
    memory: with its default OOMPolicy=stop it stops the scope, TERM to every process in it. The
    shell that is to read the scope's counts is one of them. It holds TERM off until its command
    has ended, and the message is the count's, not "could not be read". Here the stub tool, as
    the scope's command, sends both TERMs when the count is written; nothing was told to fail.
    (From one stub to another, so this runs under Git Bash too, where it fails the same way
    without the handler.)"""
    host.set("sdrun_oom_kill", "2")
    host.set("sdrun_oom_at", str(scope))
    host.set("sdrun_oom_stops")
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "counts 2 oom_kill: the memory cap (4G) was hit" in r.err, r.err
    assert "could not be read" not in r.err and "ended well all the same" not in r.err and "names as missing" not in r.err
    assert len(scopes(r.calls)) == scope, "the stopped step is the last"
    assert host.done(which)[0] == "1" and not host.info[which].exists() and host.executed() == []
    assert not list(host.builds.glob("*.step"))
    assert not (host.state / "term_outlived").exists(), \
        "the step's command got TERM as any process does: held off by a handler in the shell above it, not ignored and inherited"


def test_a_step_whose_scope_was_killed_outright_says_that_its_counts_are_gone(host):
    """A user manager whose policy for a kill is `kill` ends the whole scope with KILL, the shell
    that was to write the counts too, and so does the KILL after a stop that took too long. No
    handler outlasts that. The message says what is known: the counts are gone, and the step's
    shell was killed outright. It does not say that the cap was hit, and not that it was not."""
    host.set("sdrun_oom_kill", "1")
    host.set("sdrun_oom_at", "2")
    host.set("sdrun_oom_stops", "KILL")
    r = host.run("fma")
    assert r.returncode == 1, r.all
    assert "could not be read" in r.err and "is not known" in r.err and "killed outright (status 137)" in r.err
    assert "was hit" not in r.err and "did not end it" not in r.err
    assert host.done("fma")[0] == "1" and not host.info["fma"].exists() and not host.fma.exists()
    # and a step that fails by itself where the kernel keeps no counts is not called killed
    host.unset("sdrun_oom_stops")
    host.set("sdrun_no_stats")
    host.set("nvcc_rc", "2")
    r = host.run("fma")
    assert r.returncode == 1 and "could not be read" in r.err and "killed outright" not in r.err


@pytest.mark.parametrize("which", ALL)
def test_a_step_that_ends_well_with_something_killed_under_it_is_not_taken(host, which):
    """A configure check the kernel killed for memory reads, to cmake, as a feature that is not
    there, and the configure ends well. The count says otherwise, and the build stops there."""
    host.set("sdrun_oom_kill", "1")
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "ended well all the same, and what it left is not trusted" in r.err and "counts 1 oom_kill" in r.err
    assert len(tools(r.calls)) == 1, "the first step is the last"
    assert not host.info[which].exists() and host.done(which)[0] == "1"


@pytest.mark.parametrize("which, knob, scope", [("vsomeip", "make_rc_vsomeip", 3), ("cyclonedds", "build_rc_cyclonedds", 3),
                                                 ("llama", "build_rc_llama", 3), ("llama", "cmake_fail_llama", 2), ("fma", "nvcc_rc", 2)],
                         ids=["vsomeip", "cyclonedds", "llama-build", "llama-configure", "fma"])
def test_a_kill_that_was_not_the_scope_s_own_cap_is_not_called_the_cap(host, which, knob, scope):
    """oom_kill counts every process of the cgroup that the kernel killed for memory: the
    system-wide killer's victims too, and those of a limit on a cgroup above the scope. That the
    scope's own limit was reached is its oom line. A kill with that line at 0 is not the cap's,
    and one job at a time is not the remedy for it."""
    host.set(knob, "2")
    host.set("sdrun_oom_kill", "1")
    host.set("sdrun_oom_at", str(scope))
    host.set("sdrun_oom_elsewhere")
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "counts 1 oom_kill and no oom of its own" in r.err and "not because this scope reached its cap (4G)" in r.err, r.err
    assert "was hit" not in r.err and "JOBS=1" not in r.err and "did not end it" not in r.err and "names as missing" not in r.err
    assert host.done(which)[0] == "1" and not host.info[which].exists()
    # the same kill with the scope's own limit reached is the cap's
    host.unset("sdrun_oom_elsewhere")
    r = host.run(which)
    assert r.returncode == 1 and "counts 1 oom_kill: the memory cap (4G) was hit" in r.err and "no oom of its own" not in r.err


def test_a_step_that_ends_well_with_a_kill_from_elsewhere_under_it_is_not_taken_either(host):
    host.set("sdrun_oom_kill", "1")
    host.set("sdrun_oom_elsewhere")
    r = host.run("fma")
    assert r.returncode == 1, r.all
    assert "ended well all the same, and what it left is not trusted" in r.err and "counts 1 oom_kill and no oom of its own" in r.err
    assert "was hit" not in r.err and not host.info["fma"].exists()


def test_a_kernel_that_counts_kills_and_has_no_oom_line_is_read_as_the_cap(host):
    """Without the line there is nothing to tell the two apart by; the kill is the cap's until
    something says otherwise, which is what the advice (fewer jobs) fits."""
    host.set("nvcc_rc", "2")
    host.set("sdrun_oom_kill", "2")
    host.set("sdrun_no_oom_line")
    r = host.run("fma")
    assert r.returncode == 1 and "counts 2 oom_kill: the memory cap (4G) was hit" in r.err and "no oom of its own" not in r.err


def test_build_info_holds_the_largest_peak_among_the_build_s_steps(host):
    host.set("sdrun_peaks", "999\n100\n700\n300\n200\n100\n")       # the first scope is the question, not a step
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    assert one(info_lines(host, "vsomeip"), "build steps ") == \
        "build steps 5, each in a scope of its own; the largest memory.peak 700 bytes; oom_kill 0"


@pytest.mark.parametrize("which", ALL)
def test_a_kernel_that_keeps_no_peak_for_a_cgroup_fails_nothing_and_is_said(host, which):
    host.set("sdrun_no_stats")
    r = host.run(which)
    assert r.returncode == 0, r.all
    n = len(tools(r.calls))
    assert one(info_lines(host, which), "build steps ") == \
        "build steps %d, each in a scope of its own; the largest memory.peak 0 bytes; oom_kill 0; unread for %d of them" % (n, n)


@pytest.mark.parametrize("which", ["cyclonedds", "llama", "vsomeip"])
def test_a_clone_that_fails_is_said_and_nothing_is_built(host, which):
    host.set("git_clone_rc", "128")
    r = host.run(which)
    assert r.returncode == 1 and "FATAL: the clone of https://" in r.err
    assert tools(r.calls) == [] and host.done(which)[0] == "1"


SRC_OF = {"vsomeip": "vs_src", "cyclonedds": "dds_src", "llama": "llama_src"}


@pytest.mark.parametrize("which", ["cyclonedds", "llama", "vsomeip"])
def test_a_clone_that_did_not_finish_is_said_as_that(host, which):
    """A clone that was cut (a power loss, a KILL) leaves a .git whose HEAD names a branch with
    no commit. Its checkout fails with `reference is not a tree`, which reads as "the pin is not
    in the clone" and is not: nothing is, and every re-run would say the same."""
    src = getattr(host, SRC_OF[which])
    (src / ".git").mkdir(parents=True)
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "FATAL: no HEAD in %s" % _fwd(src) in r.err and "a clone that did not finish" in r.err, r.err
    assert "Remove %s and run again" % _fwd(src) in r.err
    assert "fatal: ambiguous argument 'HEAD'" in r.err, "git's own line is shown above the script's"
    assert "cannot check out" not in r.err and "reference is not a tree" not in r.err
    assert not [c for c in r.calls if c.name == "git" and "checkout" in c.args] and clones(r.calls) == []
    assert tools(r.calls) == [] and (src / ".git").is_dir(), "and the script removes nothing itself"
    assert host.done(which)[0] == "1"


@pytest.mark.skipif(GIT is None, reason="no git here")
@pytest.mark.parametrize("which", ["cyclonedds", "llama", "vsomeip"])
def test_a_clone_that_did_not_finish_is_said_as_that_by_the_real_git_too(host, which):
    """The same with the real git behind the script: `git init` is a clone's first step, and
    what it leaves is what a clone that was cut before its first object leaves. No network."""
    src = getattr(host, SRC_OF[which])
    subprocess.run([GIT, "init", "--quiet", _fwd(src)], check=True, env=host.env(), timeout=60, capture_output=True,
                   stdin=subprocess.DEVNULL)
    (host.bin / "git").unlink()
    r = host.run(which)
    assert r.returncode == 1, r.all
    assert "FATAL: no HEAD in %s" % _fwd(src) in r.err and "Remove %s and run again" % _fwd(src) in r.err, r.err
    assert "cannot check out" not in r.err and tools(r.calls) == [] and (src / ".git").is_dir()


def test_every_git_call_that_can_reach_the_network_is_ended_when_it_stalls_and_none_can_ask(host):
    """A clone whose server accepts and then says nothing waits for as long as TCP lets it, with
    the build's lock held; and a git that wants a user name asks the terminal for one, where
    there is one. So the clone and the checkout (a partial clone fetches file contents at its
    checkout) give up on a transfer that stays under a floor for a minute, and no git prompts."""
    code = _code(_text(LIB))
    assert '\nb_git() { git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 "$@"; }\n' in code
    begin = code.split("\nb_begin() {\n")[1].split("\n}\n")[0]
    assert "\n\texport GIT_TERMINAL_PROMPT=0\n" in begin, "set where every script starts, before any git"
    for which, n in (("vsomeip", 1), ("cyclonedds", 2), ("llama", 2)):
        lines = [l.strip() for l in _code(_text(SCRIPTS[which])).split("\n")]
        net = [l for l in lines if l.startswith("b_git ")]
        assert len(net) == n and all(l.startswith(("b_git clone ", 'b_git -C "$SRC" checkout ')) for l in net), (which, net)
        assert not [l for l in lines if re.search(r"(?<![\w-])git (-C \S+ )?(clone|checkout|fetch|pull|submodule) ", l)], \
            "and no clone or checkout goes round it"
        r = host.run(which)
        assert r.returncode == 0, r.all
        reach = [c for c in r.calls if c.name == "git" and ("clone" in c.args or "checkout" in c.args)]
        assert len(reach) == n and all(c.args[:4] == GIT_NET for c in reach), reach
        asked = _text(host.state / "git_prompt").split()
        assert len(asked) == len([c for c in r.calls if c.name == "git"]) and set(asked) == {"0"}, asked


@pytest.mark.parametrize("which, knob", [("vsomeip", "make_rc_vsomeip"), ("cyclonedds", "build_rc_cyclonedds"),
                                          ("llama", "build_rc_llama"), ("fma", "nvcc_rc")])
def test_a_second_run_after_a_failed_one_says_what_it_found_and_builds(host, which, knob):
    host.set(knob, "2")
    assert host.run(which).returncode == 1
    host.unset(knob)
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert "found: an earlier %s ended with exit status 1" % NAMES[which] in r.out
    assert host.done(which)[0] == "0" and host.info[which].exists()
    assert clones(r.calls) == [], "what was cloned is not cloned again"


@pytest.mark.parametrize("which", ALL)
def test_a_second_run_after_a_finished_one_is_safe_and_says_what_it_found(host, which):
    r1 = host.run(which)
    assert r1.returncode == 0, r1.all
    assert "found: no earlier %s" % NAMES[which] in r1.out
    hashes = [_sha(o) for o in outputs(host, which)]
    r2 = host.run(which)
    assert r2.returncode == 0, r2.all
    assert "found: an earlier %s ended with exit status 0" % NAMES[which] in r2.out
    assert "of an earlier build" in r2.out, "the BUILD-INFO it found is named, removed, and written again at the end"
    assert [_sha(o) for o in outputs(host, which)] == hashes
    assert host.done(which)[0] == "0" and uncapped(r2.calls) == [] and host.executed() == []
    assert len(clones(r1.calls)) == (0 if which == "fma" else 1) and clones(r2.calls) == []


@pytest.mark.parametrize("which", ALL)
def test_a_build_info_never_outlives_the_build_it_describes(host, which):
    """A run that fails at its first build step, after an earlier run ended well: the earlier
    BUILD-INFO is gone before that step is tried."""
    assert host.run(which).returncode == 0
    assert host.info[which].exists()
    host.set("sdrun_refuse_from", "2")
    r = host.run(which)
    assert r.returncode == 1 and len(scopes(r.calls)) == 2, r.all
    assert not host.info[which].exists()


@pytest.mark.parametrize("which", ALL)
def test_a_run_that_is_refused_before_it_builds_leaves_an_earlier_build_as_it_was(host, which):
    """No cap, so nothing is touched: the earlier outputs and the BUILD-INFO that describes them
    are still there, byte for byte."""
    assert host.run(which).returncode == 0
    before = {str(p): _sha(p) for p in outputs(host, which) + [host.info[which]]}
    host.set("sdrun_refuse")
    assert host.run(which).returncode == 1
    assert {p: _sha(p) for p in before} == before


@pytest.mark.parametrize("which", ALL)
def test_a_run_that_died_is_told_from_one_that_ended(host, which):
    """No done-file and nothing holding the lock: the earlier run was killed, or the board went
    down. Here the state is written as such a run leaves it."""
    assert host.status(which).returncode == 4 and "no run found" in host.status(which).stdout
    _put(host.builds / (NAMES[which] + ".started"), "2026-01-01T00:00:00Z\npid 4242\n")
    s = host.status(which)
    assert s.returncode == 3 and "DIED" in s.stdout and "2026-01-01T00:00:00Z" in s.stdout
    r = host.run(which)
    assert r.returncode == 0, r.all
    assert "found: an earlier %s started 2026-01-01T00:00:00Z and wrote no done-file: it died or was killed" % NAMES[which] in r.out
    s = host.status(which)
    assert s.returncode == 0 and "%s: ended with exit status 0" % NAMES[which] in s.stdout
    host.set("sdrun_refuse")
    assert host.run(which).returncode == 1
    s = host.status(which)
    assert s.returncode == 1 and "ended with exit status 1" in s.stdout


def test_the_library_run_by_itself_builds_nothing_and_says_what_it_takes(host):
    r = subprocess.run([BASH, _fwd(LIB)], capture_output=True, text=True, timeout=60, env=host.env())
    assert r.returncode == 64 and "status NAME" in r.stderr and "memory-max" in r.stderr
    r = subprocess.run([BASH, _fwd(LIB), "memory-max", _fwd(host.self_cgroup), _fwd(host.cg)], capture_output=True, text=True,
                       timeout=60, env=host.env())
    assert r.returncode != 0, "outside a scope there is no such cgroup in the made-up tree"
    assert host.calls_now() == [] and not host.builds.exists()


@real_flock
@posix_signals
def test_a_second_run_while_the_first_is_building_starts_nothing_and_leaves_the_done_file_alone(host):
    host.set("make_waits_vsomeip")
    p = host.start("vsomeip")
    try:
        host.wait_for("holding", p)
        assert host.done("vsomeip") is None
        s = host.status("vsomeip")
        assert s.returncode == 2 and "build-vsomeip: running since 2" in s.stdout
        assert ", pid %d (" % p.pid in s.stdout, "the pid to signal: with setsid, the process group's"
        before = len(host.calls_now())
        r = subprocess.run([BASH, _fwd(SCRIPTS["vsomeip"])], capture_output=True, text=True, timeout=60, env=host.env())
        assert r.returncode == 75 and "another build-vsomeip is running" in r.stderr
        assert len(host.calls_now()) == before, "the second run called nothing"
        assert host.done("vsomeip") is None, "and wrote no done-file: that is the first run's"
    finally:
        host.set("go")
        out = p.communicate(timeout=120)[0]
    assert p.returncode == 0, out
    assert host.done("vsomeip")[0] == "0"
    assert host.status("vsomeip").returncode == 0


@posix_signals
@pytest.mark.parametrize("which, knob", [("vsomeip", "make_waits_vsomeip"), ("llama", "build_waits_llama")])
def test_a_build_that_is_told_to_stop_still_writes_its_done_file(host, which, knob):
    """TERM to the script's process group, as `kill -TERM -- -<pid>` sends it to a detached run."""
    host.set(knob)
    p = host.start(which)
    host.wait_for("holding", p)
    os.killpg(p.pid, signal.SIGTERM)
    out = p.communicate(timeout=120)[0]
    assert p.returncode != 0, out
    done = host.done(which)
    assert done is not None and done[0] == str(p.returncode) and done[0] != "0"
    assert not host.info[which].exists()
    assert host.status(which).returncode == 1


@posix_signals
@pytest.mark.parametrize("sig, status", [(2, 130), (1, 129)], ids=["INT", "HUP"])
def test_a_build_that_is_interrupted_or_hung_up_on_ends_with_that_status_in_its_done_file(host, sig, status):
    """INT as Ctrl-C sends it to a build started in the foreground, HUP as a terminal that went
    away does, each to the whole group. Without a handler of its own the shell would run the
    EXIT trap with the status of whatever command ended last, which may be 0."""
    if signal.getsignal(sig) == signal.SIG_IGN:
        pytest.skip("this pytest was started with the signal ignored (in a shell's background, or under nohup): "
                    "a script cannot trap what it inherits as ignored")
    host.set("make_waits_vsomeip")
    p = host.start("vsomeip")
    try:
        host.wait_for("holding", p)
        os.killpg(p.pid, sig)
        out = p.communicate(timeout=120)[0]
    finally:
        host.set("go")
    assert p.returncode == status, out
    assert host.done("vsomeip") == ["%d" % status, host.done("vsomeip")[1]]
    assert not host.info["vsomeip"].exists() and host.status("vsomeip").returncode == 1


@posix_signals
def test_a_build_whose_reader_went_away_still_writes_its_done_file(host):
    """Started in the foreground, and whoever read its output is gone: the next line the script
    prints ends it, and the done-file says with what."""
    host.set("make_waits_vsomeip")
    p = host.start("vsomeip")
    host.wait_for("holding", p)
    p.stdout.close()
    host.set("go")
    p.wait(timeout=120)
    done = host.done("vsomeip")
    assert done is not None and done[0] == str(p.returncode), (done, p.returncode)
    assert host.status("vsomeip").returncode in (0, 1)


@posix_signals
def test_a_failed_step_whose_message_has_no_reader_ends_with_the_pipe_s_status(host):
    """The same, and the line that finds the reader gone is the script's own FATAL line: a
    write by the shell itself, not by a tool it started. The PIPE handler gives the run one
    status whatever the shell was doing: 141."""
    host.set("make_waits_vsomeip")
    host.set("make_rc_vsomeip", "2")
    p = host.start("vsomeip")
    try:
        host.wait_for("holding", p)
        p.stdout.close()
    finally:
        host.set("go")
    p.wait(timeout=120)
    assert p.returncode == 141
    assert host.done("vsomeip")[0] == "141" and not host.info["vsomeip"].exists()


@real_flock
def test_a_done_file_beside_a_held_lock_is_not_yet_read_as_ended(host):
    """What a run leaves when something it started outlives it: the script wrote how it ended,
    and the lock, which everything it started inherits, is still held. `status` says both and
    answers as for a run that is alive; a new run starts nothing and leaves the done-file alone."""
    fcntl = pytest.importorskip("fcntl")
    assert host.run("fma").returncode == 0 and host.status("fma").returncode == 0
    with open(str(host.builds / "build-fma.lock"), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        s = host.status("fma")
        assert s.returncode == 2, s.stdout
        assert "build-fma: a done-file says exit status 0 (" in s.stdout and "something still holds" in s.stdout
        assert "running since" not in s.stdout and re.search(r"the script that started last: pid \d+\)", s.stdout)
        r = host.run("fma")
        assert r.returncode == 75 and "or something one started is still alive" in r.err
        assert r.calls == [] and host.done("fma")[0] == "0"
    s = host.status("fma")
    assert s.returncode == 0 and "ended with exit status 0" in s.stdout


@posix_signals
def test_a_build_that_is_killed_outright_leaves_no_done_file_and_reads_as_died(host):
    """After a run that ended well, so that a done-file is there when the second run starts: it
    is that run's, and it must not be read as the killed one's."""
    assert host.run("vsomeip").returncode == 0 and host.done("vsomeip")[0] == "0"
    host.set("make_waits_vsomeip")
    p = host.start("vsomeip")
    host.wait_for("holding", p)
    os.killpg(p.pid, signal.SIGKILL)
    p.communicate(timeout=120)
    assert host.done("vsomeip") is None
    end = time.time() + 30
    while time.time() < end and host.status("vsomeip").returncode == 2:
        time.sleep(0.1)                                # the lock goes with the last process that held it
    s = host.status("vsomeip")
    assert s.returncode == 3 and "DIED" in s.stdout
    host.unset("make_waits_vsomeip")
    r = host.run("vsomeip")
    assert r.returncode == 0 and "it died or was killed" in r.out


@pytest.mark.skipif(SETSID is None or os.name == "nt", reason="no setsid here")
def test_the_detached_start_of_the_runbook_runs_to_its_done_file(host):
    """setsid nohup bash <script> > build.log 2>&1 < /dev/null &   -- and nobody waits for it."""
    log = host.home / "build.log"
    cmd = 'setsid nohup bash "%s" > "%s" 2>&1 < /dev/null &' % (_fwd(SCRIPTS["fma"]), _fwd(log))
    subprocess.run([BASH, "-c", cmd], check=True, env=host.env(), timeout=60, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 60
    while time.time() < end and host.done("fma") is None:
        time.sleep(0.1)
    assert host.done("fma") is not None and host.done("fma")[0] == "0", _text(log) if log.exists() else "no log"
    assert _text(host.info["fma"]) in _text(log)
    assert host.status("fma").returncode == 0


# ------------------------------------------------------------------ build-vsomeip.sh

def boost_line(host):
    return one(info_lines(host, "vsomeip"), "boost 1.")


def test_vsomeip_the_versioned_boost_set_passes_and_is_named(host):
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    assert boost_line(host) == "boost 1.74 from the versioned dev set: " + " ".join("%s=%s" % (p, V174) for p in BOOST_V)


def test_vsomeip_the_unversioned_boost_set_passes_and_its_version_is_dpkg_s(host):
    host.packages({p: U183 for p in BOOST_U})
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    assert boost_line(host) == "boost 1.83 from the unversioned dev set: " + " ".join("%s=%s" % (p, U183) for p in BOOST_U)
    assert tools(r.calls, "cmake")[0].args[4:-1] == VSOMEIP_FLAGS, "the configure's flags are the same whichever Boost set was found"


def test_vsomeip_the_unversioned_set_of_ubuntu_22_04_is_one_boost_with_its_own_dependencies(host):
    """On 22.04 the unversioned packages are 1.74 and depend on the versioned 1.74 ones, so both
    are installed. That is one Boost, not a mix."""
    host.packages(dict({p: U174 for p in BOOST_U}, **VERSIONED))
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    assert boost_line(host).startswith("boost 1.74 from the unversioned dev set: libboost-system-dev=%s " % U174)
    assert tools(r.calls, "cmake")[0].args[4:-1] == VSOMEIP_FLAGS, "the configure's flags are the same whichever Boost set was found"


MIXES = {
    "versioned-set-and-one-unversioned-of-another-boost": dict(VERSIONED, **{"libboost-system-dev": U183}),
    "unversioned-set-of-another-boost-and-one-versioned": dict({p: U183 for p in BOOST_U}, **{"libboost1.74-dev": V174}),
    "half-of-each": {"libboost-system1.74-dev": V174, "libboost1.74-dev": V174, "libboost-thread-dev": U183},
    "versioned-set-incomplete": {p: V174 for p in BOOST_V[:3]},
    "unversioned-set-incomplete": {p: U183 for p in BOOST_U[:2]},
    "unversioned-set-of-two-boosts": {"libboost-system-dev": U183, "libboost-thread-dev": U174, "libboost-filesystem-dev": U183},
    "versioned-set-and-part-of-the-unversioned-1.74": dict(VERSIONED, **{"libboost-thread-dev": U174}),
}


@pytest.mark.parametrize("name", sorted(MIXES))
def test_vsomeip_a_mix_of_boost_packages_is_refused_by_name(host, name):
    host.packages(MIXES[name])
    r = host.run("vsomeip")
    assert r.returncode == 1, r.all
    assert "Boost" in r.err and ("a mix" in r.err or "incomplete" in r.err)
    for p in MIXES[name]:
        assert p in r.err, "what is installed is named: %s" % p
    for p in BOOST_V + BOOST_U:
        if p not in MIXES[name]:
            assert p in r.err, "what is missing is named: %s" % p
    assert tools(r.calls) == [] and scopes(r.calls) == [] and not [c for c in r.calls if c.name == "git"]
    assert not host.info["vsomeip"].exists() and host.done("vsomeip")[0] == "1"


def test_vsomeip_no_boost_dev_at_all_is_refused_by_name(host):
    host.packages({"libboost-system1.74.0": V174})          # the runtime library is not a dev package
    r = host.run("vsomeip")
    assert r.returncode == 1 and "Neither set is installed" in r.err
    for p in BOOST_V + BOOST_U:
        assert p in r.err, p
    assert tools(r.calls) == [] and not [c for c in r.calls if c.name == "git"]


def test_vsomeip_a_removed_package_that_left_its_configuration_is_not_installed(host):
    host.packages({}, residual=VERSIONED)
    r = host.run("vsomeip")
    assert r.returncode == 1 and "Neither set is installed" in r.err
    host.packages(VERSIONED, residual={p: U183 for p in BOOST_U})
    r = host.run("vsomeip")
    assert r.returncode == 0, "an unversioned package that is only configuration is no mix: %s" % r.all


def test_vsomeip_build_info_holds_the_commit_the_flags_the_compiler_and_each_output(host):
    host.set("boost_dir_line", "Boost_DIR:PATH=/usr/lib/stub/cmake/Boost-1.74.0\n")
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    lines = info_lines(host, "vsomeip")
    assert lines[0] == "vsomeip 3.4.10 commit %s from https://github.com/COVESA/vsomeip.git" % VSOMEIP_PIN
    assert lines[1] == "someip_vprobe sha256 %s" % _sha(host.vs_prefix / "bin" / "someip_vprobe")
    # scripts/aws/remote-ladder.sh greps this line whole, to know the probe was built from this source
    assert lines[2] == "source sha256 %s" % _sha(os.path.join(REPO, "orin-native", "someip", "someip_vprobe.cpp"))
    assert re.match(r"^built \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ with g\+\+ \(Stub 0\.0-s1\) 0\.0\.0$", lines[3])
    assert one(lines, "flags ") == "flags " + " ".join(VSOMEIP_FLAGS)
    assert one(lines, "boost as cmake found it: ") == "boost as cmake found it: /usr/lib/stub/cmake/Boost-1.74.0"
    assert one(lines, "tracked files changed against the commit: ").endswith(": 0")
    libs = sorted(l for l in lines if l.startswith("lib sha256 "))
    assert libs == sorted("lib sha256 %s %s" % (_sha(host.vs_prefix / "lib" / n), n)
                          for n in ("libvsomeip3.so.3.4.10", "libvsomeip3-cfg.so.3.4.10", "libvsomeip3-sd.so.3.4.10"))
    configure = [c for c in tools(r.calls, "cmake") if "-DENABLE_SIGNAL_HANDLING=1" in c.args][0]
    assert configure.args == ["-S", _fwd(host.vs_src), "-B", _fwd(host.vs_src / "build")] + VSOMEIP_FLAGS + [
        "-DCMAKE_INSTALL_PREFIX=%s" % _fwd(host.vs_prefix)]
    assert "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON" in VSOMEIP_FLAGS, \
        "vsomeip's export(PACKAGE) would otherwise write the build tree's path into ~/.cmake/packages"


def test_vsomeip_one_kind_of_warning_is_not_an_error_for_vsomeip_s_configure_and_the_probe_s_gets_nothing(host):
    """g++ 13 reports -Wstringop-overflow inside a Boost 1.74 header that vsomeip's security
    policy header brings in, and the flags vsomeip's CMakeLists.txt sets include -Werror. So
    vsomeip's configure gets one word, for that one kind, once. The probe's configure does not:
    it is this repo's CMakeLists.txt, which makes no warning an error, and its argv stays what
    it was. The three make lines carry a directory, a job count or a target, and no flag."""
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    assert VSOMEIP_WARN == "-DCMAKE_CXX_FLAGS=-Wno-error=stringop-overflow" and VSOMEIP_FLAGS[-1] == VSOMEIP_WARN
    configure, probe = tools(r.calls, "cmake")
    assert [a for a in configure.args if "FLAGS" in a] == [VSOMEIP_WARN], "once, whole, and no other flags variable beside it"
    assert configure.args == ["-S", _fwd(host.vs_src), "-B", _fwd(host.vs_src / "build")] + VSOMEIP_FLAGS + [
        "-DCMAKE_INSTALL_PREFIX=%s" % _fwd(host.vs_prefix)]
    pre = _fwd(host.vs_prefix)
    assert probe.args == ["-S", _fwd(os.path.join(REPO, "orin-native", "someip")), "-B", pre + "/probe-build", "-DCMAKE_BUILD_TYPE=Release",
                          "-Dvsomeip3_DIR=%s/lib/cmake/vsomeip3" % pre, "-DCMAKE_INSTALL_RPATH=%s/lib" % pre,
                          "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON"], "the probe's configure is as it was"
    # the same through what each scope was made for: the step that configures vsomeip, and no other step
    steps = [step_cmd(host, s) for s in scopes(r.calls)[1:]]
    assert [VSOMEIP_WARN in s for s in steps] == [True, False, False, False, False], steps
    # make's own command line can hand a compiler flags as well (a variable after the directory): each of the three, whole
    bld = _fwd(host.vs_src / "build")
    assert [c.args for c in tools(r.calls, "make")] == [["-C", bld, "-j2"], ["-C", bld, "install"], ["-C", pre + "/probe-build"]]


def test_vsomeip_the_header_says_why_one_kind_of_warning_is_not_an_error():
    """The header names the way from vsomeip's sources to the Boost header, which can be read in
    them, and gives no count of the files that go that way: a count would be a compile's. It
    says which of its statements are readings and which one is the compiler's."""
    head = " ".join(_text(SCRIPTS["vsomeip"]).split("\nset -euo pipefail\n")[0].replace("\n#", " ").split())
    for said in (VSOMEIP_WARN, "g++ 13", "-Wstringop-overflow", "boost/icl/detail/interval_set_algo.hpp", "-Werror",
                 "implementation/security/include/policy.hpp", "boost/icl/interval_set.hpp",
                 "leaves it a warning", "every other kind stays an error", "No generated code depends on it",
                 "vsomeip's source is not changed", "another Boost", "what the binary is built against",
                 "is the compiler's own word", "is read from those files and from the two manuals"):
        assert said in head, said
    assert not re.search(r"\b(\d+|two|three|four|five|six|several|some|both) of vsomeip's (own )?(source )?files\b", head)


def test_vsomeip_the_checkout_s_files_are_as_they_were_after_a_build(host):
    """vsomeip's source is not changed: the one word goes to cmake, and no file of the checkout is
    edited, removed or added so that the build passes. BUILD-INFO's count of changed tracked
    files is read before the build steps and would not see an edit the script made itself; this
    does. What is new under the checkout after a run is under build/, which is the build's own."""
    made_up = {".git/STUB_HEAD": VSOMEIP_PIN, "CMakeLists.txt": 'set(OS_CXX_FLAGS "-Wall -Wextra -Werror -fPIE")  # made up\n',
               "implementation/security/include/policy.hpp": "// a made-up policy.hpp\n"}
    for name, text in made_up.items():
        _put(host.vs_src / name, text)

    def files():
        inside = [p for p in host.vs_src.rglob("*") if p.is_file()]
        return {_fwd(p.relative_to(host.vs_src)): _sha(p) for p in inside if p.relative_to(host.vs_src).parts[0] != "build"}

    before = files()
    assert sorted(before) == sorted(made_up)
    r = host.run("vsomeip")
    assert r.returncode == 0 and clones(r.calls) == [], r.all
    assert (host.vs_src / "build" / "CMakeCache.txt").is_file(), "the build wrote, and under build/"
    assert files() == before, "no file of the checkout was edited, removed or added"


def test_vsomeip_the_probe_s_own_build_makes_no_warning_an_error_and_hides_none():
    """Why the probe's configure is left alone: nothing gives its compile a -Werror. Not this
    script, and not the CMakeLists.txt beside it, which asks for -Wall -Wextra. A warning in the
    probe's compile, the Boost header's or any other, stays a warning in its log."""
    cmakelists = "\n".join(l for l in _text(os.path.join(REPO, "orin-native", "someip", "CMakeLists.txt")).split("\n")
                           if not l.lstrip().startswith("#"))
    assert "target_compile_options(someip_vprobe PRIVATE -O2 -Wall -Wextra)" in cmakelists
    assert re.findall(r"-W[A-Za-z][A-Za-z0-9=_+-]*", cmakelists) == ["-Wall", "-Wextra"], "no -Werror, and no -Wno- either"
    assert WEAKER_TEXT.findall(cmakelists) == [] and "CMAKE_CXX_FLAGS" not in cmakelists
    assert "-Werror" not in _code(_text(SCRIPTS["vsomeip"])), "and this script hands nobody one"


def test_vsomeip_build_info_s_flags_line_is_what_the_configure_got(host):
    """BUILD-INFO says with which flags the libraries were built: the words of its flags line are
    the configure's own, in order, the warning's word among them."""
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    lines = info_lines(host, "vsomeip")
    configure = tools(r.calls, "cmake")[0]
    flags = one(lines, "flags ")
    assert flags.split(" ") == ["flags"] + configure.args[4:-1], "the line's words are the configure's, between its directories and its prefix"
    assert flags.endswith(" -DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON " + VSOMEIP_WARN), flags
    assert [l for l in lines if "stringop-overflow" in l] == [flags], "in that line and in no other"


def test_vsomeip_build_info_s_first_four_lines_are_in_the_form_they_had(host):
    """Whatever reads BUILD-INFO by line number or by a whole line finds the first four as they
    were: the commit, the probe's sha256, its source's sha256, when and with which compiler.
    scripts/aws/remote-ladder.sh asks for the third whole (grep -qx "source sha256 <hash>").
    The flags line is below them."""
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    lines = info_lines(host, "vsomeip")
    assert re.fullmatch(r"vsomeip 3\.4\.10 commit %s from https://github\.com/COVESA/vsomeip\.git" % VSOMEIP_PIN, lines[0]), lines[0]
    assert re.fullmatch(r"someip_vprobe sha256 [0-9a-f]{64}", lines[1]), lines[1]
    assert re.fullmatch(r"source sha256 [0-9a-f]{64}", lines[2]), lines[2]
    assert re.fullmatch(r"built \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ with g\+\+ \(Stub 0\.0-s1\) 0\.0\.0", lines[3]), lines[3]
    assert lines.count("source sha256 %s" % _sha(os.path.join(REPO, "orin-native", "someip", "someip_vprobe.cpp"))) == 1
    assert [l.split(" ")[0] for l in lines[:8]] == ["vsomeip", "someip_vprobe", "source", "built", "boost", "boost", "flags", "tracked"]


@pytest.mark.parametrize("which", ALL)
def test_no_build_passes_a_word_that_takes_a_warning_s_force_away_but_vsomeip_s_one(host, which):
    """-Wno-error with no kind named would stop every kind of warning from being an error in
    vsomeip's build, a kind switched off (-Wno-<kind>, or -W<kind>=0) or -w would take a
    warning's line out of a log, and -fpermissive would let through what the compiler refuses.
    None is passed by any of the four scripts: not in an argv, not through the environment's
    flag words, and not in the text of a script or of the library. vsomeip's configure has its
    one word, seen once in its scope's argv and once in cmake's."""
    host.set("llama_libs")
    r = host.run(which)
    assert r.returncode == 0, r.all
    want = [("systemd-run", VSOMEIP_WARN), ("cmake", VSOMEIP_WARN)] if which == "vsomeip" else []
    assert [(c.name, a) for c in r.calls for a in c.args if WEAKER.search(a)] == want, "every such word in every argv of the run"
    assert host.flag_env() and set(host.flag_env()) == {"|".join(["unset"] * len(FLAG_ENV))}, "no stub saw a flag word in its environment"
    for path, own in ((SCRIPTS[which], ["-Wno-error=stringop-overflow"] if which == "vsomeip" else []), (LIB, [])):
        code = _code(_text(path))
        assert WEAKER_TEXT.findall(code) == own, path
        assert not re.search(r"\b(%s|CMAKE_C_FLAGS)\b" % "|".join(FLAG_ENV), code), path
        assert len(re.findall(r"CMAKE_CXX_FLAGS", code)) == len(own), path


def test_vsomeip_a_cache_without_a_boost_line_is_said_not_guessed(host):
    assert host.run("vsomeip").returncode == 0
    assert one(info_lines(host, "vsomeip"), "boost as cmake found it: ").endswith(": not in CMakeCache.txt")


@pytest.mark.skipif(os.name == "nt", reason="no symbolic links for a test on Windows")
def test_vsomeip_a_library_s_symlinks_are_not_listed_as_outputs(host):
    host.set("with_symlinks")
    assert host.run("vsomeip").returncode == 0
    assert len([l for l in info_lines(host, "vsomeip") if l.startswith("lib sha256 ")]) == 3


def test_vsomeip_the_steps_and_their_order(host):
    r = host.run("vsomeip")
    assert r.returncode == 0, r.all
    got = [(c.name, ("clone" if "clone" in c.args else c.args[0]) if c.name == "git" else ("install" if "install" in c.args else ""))
           for c in r.calls if c.name in ("git", "cmake", "make")]
    assert got == [("git", "clone"), ("git", "-C"), ("git", "-C"), ("cmake", ""), ("make", ""), ("make", "install"), ("cmake", ""), ("make", "")]
    clone = [c for c in r.calls if c.name == "git"][0]
    assert clone.args == GIT_NET + ["clone", "--quiet", "--branch", "3.4.10", "--depth", "1", "https://github.com/COVESA/vsomeip.git",
                                    _fwd(host.vs_src)]
    probe = [c for c in tools(r.calls, "cmake")][1]
    assert probe.args[:4] == ["-S", _fwd(os.path.join(REPO, "orin-native", "someip")), "-B", _fwd(host.vs_prefix / "probe-build")]
    assert "-Dvsomeip3_DIR=%s/lib/cmake/vsomeip3" % _fwd(host.vs_prefix) in probe.args
    assert "-DCMAKE_INSTALL_RPATH=%s/lib" % _fwd(host.vs_prefix) in probe.args and "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON" in probe.args


def test_vsomeip_a_checkout_that_is_not_the_pinned_commit_is_refused(host):
    host.set("git_tag_head", NOT_A_PIN)
    r = host.run("vsomeip")
    assert r.returncode == 1 and NOT_A_PIN in r.err and VSOMEIP_PIN in r.err
    assert tools(r.calls) == []


def test_vsomeip_changed_tracked_files_are_counted_in_build_info(host):
    host.set("git_dirty", " M implementation/a.cpp\n M implementation/b.cpp\n")
    assert host.run("vsomeip").returncode == 0
    assert one(info_lines(host, "vsomeip"), "tracked files changed against the commit: ").endswith(": 2")
    host.set("git_status_rc", "128")
    assert host.run("vsomeip").returncode == 0
    assert one(info_lines(host, "vsomeip"), "tracked files changed against the commit: ").endswith(": unread")


def test_vsomeip_a_probe_an_earlier_run_left_is_not_installed_as_this_run_s(host):
    """A run that was cut in its last link (a power loss, a KILL) leaves the probe half written
    and newer than its objects, because a linker writes its output in place. make then has
    nothing to do for it, and without the removal the next run would install the cut file and
    hash it into BUILD-INFO under its own commit. Here make leaves the target as it finds it."""
    assert host.run("vsomeip").returncode == 0
    built, installed = host.vs_prefix / "probe-build" / "someip_vprobe", host.vs_prefix / "bin" / "someip_vprobe"
    assert built.exists() and installed.exists()
    host.set("probe_stays")
    r = host.run("vsomeip")
    assert r.returncode == 1 and "left no someip_vprobe" in r.err, r.all
    assert not built.exists() and not installed.exists() and not host.info["vsomeip"].exists()
    assert host.done("vsomeip")[0] == "1" and host.executed() == []
    host.unset("probe_stays")
    assert host.run("vsomeip").returncode == 0 and installed.exists(), "what make links again is taken"


def test_vsomeip_a_probe_build_that_leaves_no_probe_is_said_by_name(host):
    host.set("probe_stays")
    r = host.run("vsomeip")
    assert r.returncode == 1, r.all
    assert "FATAL: the probe's build ended well and left no someip_vprobe" in r.err and "probe-build.make.log" in r.err


# ------------------------------------------------------------------ build-cyclonedds-l4t.sh

def test_cyclonedds_clones_checks_out_the_pin_and_checks_it_afterwards(host):
    r = host.run("cyclonedds")
    assert r.returncode == 0, r.all
    git = [c.args for c in r.calls if c.name == "git"]
    assert git[0] == GIT_NET + ["clone", "--quiet", "--filter=blob:none", "https://github.com/eclipse-cyclonedds/cyclonedds.git",
                                _fwd(host.dds_src)]
    assert git[1] == ["-C", _fwd(host.dds_src), "rev-parse", "HEAD"]
    assert git[2] == GIT_NET + ["-C", _fwd(host.dds_src), "checkout", "--quiet", "--detach", CDDS_PIN], \
        "the clone holds no file contents yet: the checkout fetches them, so it carries the same words"
    assert git[3] == ["-C", _fwd(host.dds_src), "rev-parse", "HEAD"], "the pin is read back after the checkout"
    assert info_lines(host, "cyclonedds")[0] == "cyclonedds commit %s from https://github.com/eclipse-cyclonedds/cyclonedds.git" % CDDS_PIN


def test_cyclonedds_a_checkout_that_did_not_reach_the_pin_is_refused(host):
    host.set("git_checkout_stays")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and NOT_A_PIN in r.err and CDDS_PIN in r.err
    assert tools(r.calls) == []
    host.unset("git_checkout_stays")
    host.set("git_checkout_rc", "128")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and tools(r.calls) == []
    assert "FATAL: cannot check out %s in " % CDDS_PIN in r.err, "a checkout that fails is said as that, with git's own line above it"


def test_cyclonedds_configures_a_shared_library_with_idlc_under_its_commit_s_directory(host):
    r = host.run("cyclonedds")
    assert r.returncode == 0, r.all
    cm = tools(r.calls, "cmake")
    assert cm[0].args[:4] == ["-S", _fwd(host.dds_src), "-B", _fwd(host.home / "cyclonedds" / ("build-" + CDDS_PIN))]
    assert cm[0].args[4:] == ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_LIBDIR=lib", "-DBUILD_SHARED_LIBS=ON", "-DBUILD_IDLC=ON",
                              "-DBUILD_DDSPERF=OFF", "-DBUILD_TESTING=OFF", "-DBUILD_EXAMPLES=OFF", "-DENABLE_ICEORYX=OFF",
                              "-DENABLE_ICEORYX2=OFF", "-DENABLE_SSL=OFF", "-DENABLE_SECURITY=OFF", "-DENABLE_LTO=OFF",
                              "-DCMAKE_INSTALL_PREFIX=%s" % _fwd(host.dds_prefix)]
    assert cm[1].args == ["--build", cm[0].args[3], "--parallel", "2"]
    assert cm[2].args == ["--install", cm[0].args[3]]
    lines = info_lines(host, "cyclonedds")
    assert one(lines, "flags ") == "flags " + " ".join(a for a in cm[0].args[4:] if "INSTALL_PREFIX" not in a)
    assert one(lines, "bison ") == "bison (GNU Bison) 0.0-stub"
    assert re.match(r"^built \S+Z with gcc \(Stub 0\.0-s1\) 0\.0\.0; cmake version 0\.0\.0-stub$", one(lines, "built "))
    assert one(lines, "libddsc sha256 ") == "libddsc sha256 %s libddsc.so.0.0.0" % _sha(host.dds_prefix / "lib" / "libddsc.so.0.0.0")
    assert one(lines, "idlc sha256 ") == "idlc sha256 %s" % _sha(host.dds_prefix / "bin" / "idlc")


def test_cyclonedds_runs_idlc_on_av_idl_under_the_cap_and_keeps_its_output(host):
    r = host.run("cyclonedds")
    assert r.returncode == 0, r.all
    idlc = tools(r.calls, "idlc")
    assert len(idlc) == 1 and idlc[0].scope == CAP
    assert idlc[0].args == ["-l", "c", _fwd(os.path.join(DDS, "av.idl"))]
    cwd, libpath = _text(host.state / "idlc_env").splitlines()
    assert host.canon(cwd) == _fwd(host.dds_prefix / "gen"), "idlc writes where it stands: in the gen directory"
    libpath = host.canon(libpath)
    assert libpath == _fwd(host.dds_prefix / "lib"), "and finds the library it was built with"
    gen = host.dds_prefix / "gen"
    assert "stub idlc" in _text(gen / "av.c") and "stub idlc" in _text(gen / "av.h")
    lines = info_lines(host, "cyclonedds")
    assert one(lines, "av.c sha256 ") == "av.c sha256 %s" % _sha(gen / "av.c")
    assert one(lines, "av.h sha256 ") == "av.h sha256 %s" % _sha(gen / "av.h")
    assert one(lines, "av.idl sha256 ") == "av.idl sha256 %s" % _sha(os.path.join(DDS, "av.idl"))


def test_cyclonedds_builds_the_two_peers_after_idlc_with_an_rpath_into_the_prefix(host):
    r = host.run("cyclonedds")
    assert r.returncode == 0, r.all
    names = [c.name for c in tools(r.calls)]
    assert names == ["cmake", "cmake", "cmake", "idlc", "gcc", "gcc"], "configure, build, install, idlc, then the peers"
    pre = _fwd(host.dds_prefix)
    copies = host.dds_build / "l4t-peers"
    for c, p in zip(tools(r.calls, "gcc"), ("pubbad", "subv")):
        assert c.args == ["-O2", "-Wall", "-Wextra", "-I", pre + "/gen", "-I", pre + "/include", "-o", pre + "/bin/" + p,
                          _fwd(copies / (p + ".c")), pre + "/gen/av.c", "-L", pre + "/lib", "-lddsc", "-Wl,-rpath," + pre + "/lib"]
        assert _sha(copies / (p + ".c")) == _sha(host.peers / (p + ".c")), "what is compiled is a copy of the source that was given"
    assert sorted(f.name for f in copies.iterdir()) == ["pubbad.c", "subv.c"], "and nothing else lies beside the copies"
    lines = info_lines(host, "cyclonedds")
    for p in ("pubbad", "subv"):
        assert one(lines, p + " sha256 ") == "%s sha256 %s, from %s.c sha256 %s" % (
            p, _sha(host.dds_prefix / "bin" / p), p, _sha(host.peers / (p + ".c")))
    assert one(lines, "peer flags ") == "peer flags gcc -O2 -Wall -Wextra, rpath %s/lib" % pre
    assert one(lines, "peer sources ") == ("peer sources copied from %s to %s, which holds nothing else: the av.h compiled in is this run's"
                                           % (_fwd(host.peers), _fwd(copies)))
    assert "NOT used" not in r.out, "no av.h or av.c lay beside the sources"


def test_cyclonedds_an_av_h_beside_the_peers_sources_is_named_and_left_out(host):
    """A directory the peers were built in before holds an av.h and an av.c of an earlier idlc
    beside the two sources. A source says #include "av.h", and compiled where it lies it would
    get that one. Stubs only: where the compiler is pointed, and what the script says."""
    _put(host.peers / "av.h", "/* an av.h of another idlc */\n")
    _put(host.peers / "av.c", "/* an av.c of another idlc */\n")
    _put(host.dds_build / "l4t-peers" / "av.h", "/* left in the copies' directory by hand */\n")
    r = host.run("cyclonedds")
    assert r.returncode == 0, r.all
    copies = host.dds_build / "l4t-peers"
    assert sorted(f.name for f in copies.iterdir()) == ["pubbad.c", "subv.c"]
    for f in ("av.h", "av.c"):
        assert "found: %s/%s; NOT used: the peers get this run's %s/gen/%s" % (_fwd(host.peers), f, _fwd(host.dds_prefix), f) in r.out
    for c in tools(r.calls, "gcc"):
        assert not [a for a in c.args if a.startswith(_fwd(host.peers))], "nothing is compiled where the sources lie"
        assert c.args[3:5] == ["-I", _fwd(host.dds_prefix) + "/gen"], "the generated directory is the first place -I names"
    assert _text(host.peers / "av.h") == "/* an av.h of another idlc */\n", "what lies in PEER_SRC is not touched"


@pytest.mark.parametrize("stray", ["kept/av.h", ".pubbad.c.swp"], ids=["a-directory", "a-dot-file"])
def test_cyclonedds_a_copies_directory_that_cannot_be_emptied_is_refused_before_anything_is_built(host, stray):
    """What `rm -f dir/*` leaves: a directory, a file whose name starts with a dot. Refused
    where every other refusal is, before the cap is asked for and before the library is built:
    not after configure, build, install and idlc have run, with nothing to show for them."""
    _put(host.dds_build / "l4t-peers" / stray, "/* something this script does not remove */\n")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and "holds something this script did not put there" in r.err, r.all
    assert stray.split("/")[0] in r.err, "what is in the way is named"
    assert tools(r.calls) == [] and scopes(r.calls) == [] and not [c for c in r.calls if c.name == "git"]
    assert not host.dds_prefix.exists() and not host.info["cyclonedds"].exists() and host.done("cyclonedds")[0] == "1"
    assert (host.dds_build / "l4t-peers" / stray).exists(), "and it is left where it is"


def test_cyclonedds_the_copies_directory_is_looked_at_again_right_before_the_copy(host):
    """Empty at the start, and something is in it by the time the peers are due: here idlc, the
    step before them, leaves a directory there."""
    _put(host.bin / "idlc-template", STUB_HEAD + r"""
echo "/* av.c, from the stub idlc */" > av.c; echo "/* av.h, from the stub idlc */" > av.h
mkdir -p "$HOME/cyclonedds/build-%s/l4t-peers/late"
""" % CDDS_PIN)
    r = host.run("cyclonedds")
    assert r.returncode == 1 and "holds something this script did not put there" in r.err, r.all
    assert [c.name for c in tools(r.calls)] == ["cmake", "cmake", "cmake", "idlc"] and not host.info["cyclonedds"].exists()
    assert not (host.dds_build / "l4t-peers" / "pubbad.c").exists(), "nothing was copied beside it"


@pytest.mark.parametrize("where", ["the-copies-directory", "the-build-directory", "under-the-prefix"])
def test_cyclonedds_peer_sources_inside_the_script_s_own_directories_are_refused_and_left(host, where):
    """PEER_SRC is only read. The copies' directory is emptied before the copy, and an earlier
    run's av.c and av.h are removed from the prefix: sources kept in either would be removed
    by the script that was to compile them. (A directory that holds the two sources after a
    run is exactly the copies' directory.)"""
    sub = {"the-copies-directory": "cyclonedds/build-%s/l4t-peers" % CDDS_PIN, "the-build-directory": "cyclonedds/build-%s" % CDDS_PIN,
           "under-the-prefix": "cyclonedds/%s/gen" % CDDS_PIN}[where]
    for name in ("pubbad.c", "subv.c", "av.h"):
        _put(host.home / sub / name, "/* %s, kept where the script works */\n" % name)
    r = host.run("cyclonedds", PEER_SRC=host.home_sh + "/" + sub)
    assert r.returncode == 1, r.all
    assert "FATAL: PEER_SRC=%s" % _fwd(host.home / sub) in r.err and "Keep the two sources somewhere else" in r.err, r.err
    for name in ("pubbad.c", "subv.c", "av.h"):
        assert (host.home / sub / name).exists(), "%s is still there" % name
    assert tools(r.calls) == [] and scopes(r.calls) == [] and not [c for c in r.calls if c.name == "git"]
    assert host.done("cyclonedds")[0] == "1"


@pytest.mark.skipif(os.name == "nt", reason="no symbolic links for a test on Windows")
def test_cyclonedds_a_copies_directory_that_is_a_link_to_the_sources_is_not_emptied(host):
    """By its name PEER_SRC is nowhere near the build; the copies' directory is a link to it.
    The same directory is the same directory, whatever it is called."""
    host.dds_build.mkdir(parents=True)
    os.symlink(str(host.peers), str(host.dds_build / "l4t-peers"))
    r = host.run("cyclonedds")
    assert r.returncode == 1 and "FATAL: PEER_SRC=%s" % _fwd(host.peers) in r.err, r.all
    assert (host.peers / "pubbad.c").exists() and (host.peers / "subv.c").exists()
    assert tools(r.calls) == [] and scopes(r.calls) == []


PEER_C = '''#include "dds/dds.h"
#include "av.h"
#include <stdio.h>
int main(void) { puts(AV_WHICH); puts(av_desc); return dds_stub(); }
'''


@pytest.mark.skipif(GCC is None, reason="no gcc here, or Windows: nothing to compile the made-up peers with")
def test_cyclonedds_the_av_h_compiled_into_the_peers_is_this_run_s(host):
    """The one test with a real compiler behind the script's own compile line. The sources are
    made up (the peers' own are not in the repo), the library is a real shared one with one
    function, and idlc's two files and a stale pair in PEER_SRC each carry a word of their own.
    Which pair was compiled in is read from the binaries' bytes: no peer is started."""
    lib = host.state / "real_libddsc"
    subprocess.run([GCC, "-shared", "-fPIC", "-x", "c", "-", "-o", str(lib)], input="int dds_stub(void) { return 0; }\n",
                   text=True, check=True, timeout=120)
    _put(host.bin / "idlc-template", STUB_HEAD + r"""
printf '#define AV_WHICH "AVH-OF-THIS-RUN"\nextern const char *av_desc;\n' > av.h
printf '#include "av.h"\nconst char *av_desc = "AVC-OF-THIS-RUN";\n' > av.c
""")
    for p in ("pubbad", "subv"):
        _put(host.peers / (p + ".c"), PEER_C)
    _put(host.peers / "av.h", '#define AV_WHICH "AVH-STALE-IN-PEER-SRC"\nextern const char *av_desc;\n')
    _put(host.peers / "av.c", '#include "av.h"\nconst char *av_desc = "AVC-STALE-IN-PEER-SRC";\n')
    r = host.run("cyclonedds", CC=GCC)
    logs = "".join("\n--- %s\n%s" % (f.name, _text(f)) for f in sorted(host.dds_build.glob("*.log")))
    assert r.returncode == 0, r.all + logs
    for p in ("pubbad", "subv"):
        with open(str(host.dds_prefix / "bin" / p), "rb") as f:
            binary = f.read()
        assert binary[:4] == b"\x7fELF", "a real compiler's output"
        assert b"AVH-OF-THIS-RUN" in binary and b"AVC-OF-THIS-RUN" in binary, p
        assert b"STALE-IN-PEER-SRC" not in binary, "%s was compiled with the av.h that lay beside its source" % p
    assert uncapped(r.calls) == [] and len(scopes(r.calls)) == 7, "the real compiler ran in a scope like every other step"
    assert host.info["cyclonedds"].exists() and host.done("cyclonedds")[0] == "0"


@pytest.mark.parametrize("how", ["no-output", "fails", "fails-after-writing", "one-file", "other-file", "empty-files", "no-idlc"])
def test_cyclonedds_without_idlc_s_output_no_peer_is_built(host, how):
    if how == "no-output":
        host.set("idlc_noout")
    elif how == "fails":
        host.set("idlc_rc", "3")
    elif how == "no-idlc":
        host.set("no_idlc")
    else:
        body = {"one-file": "echo x > av.c\n", "other-file": "echo x > av.h\n", "empty-files": ": > av.c; : > av.h\n",
                "fails-after-writing": "echo x > av.c; echo x > av.h; echo 'idlc: error' >&2; exit 3\n"}[how]
        _put(host.bin / "idlc-template", STUB_HEAD + body)
    r = host.run("cyclonedds")
    assert r.returncode == 1, r.all
    assert "idlc" in r.err and tools(r.calls, "gcc") == []
    assert not (host.dds_prefix / "bin" / "pubbad").exists() and not host.info["cyclonedds"].exists()
    assert host.done("cyclonedds")[0] == "1"


def test_cyclonedds_an_earlier_run_s_av_files_do_not_stand_in_for_this_run_s(host):
    assert host.run("cyclonedds").returncode == 0
    assert (host.dds_prefix / "gen" / "av.c").exists() and (host.dds_prefix / "bin" / "subv").exists()
    host.set("idlc_noout")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and tools(r.calls, "gcc") == [], "the files of the first run were there; they are not this run's"
    assert not (host.dds_prefix / "gen" / "av.c").exists()
    assert not (host.dds_prefix / "bin" / "subv").exists(), "nor do the first run's peers stay beside a build that has no BUILD-INFO"


@pytest.mark.parametrize("knob, says", [("no_idlc", "the install left no idlc"), ("no_libddsc", "the install left no libddsc.so")])
def test_cyclonedds_an_earlier_run_s_idlc_and_library_do_not_stand_in_for_this_run_s(host, knob, says):
    """BUILD-INFO would hash the earlier files as this run's, and idlc would be the earlier one."""
    assert host.run("cyclonedds").returncode == 0
    assert (host.dds_prefix / "bin" / "idlc").exists() and (host.dds_prefix / "lib" / "libddsc.so.0.0.0").exists()
    host.set(knob)
    r = host.run("cyclonedds")
    assert r.returncode == 1 and says in r.err, r.all
    assert tools(r.calls, "idlc") == [] and tools(r.calls, "gcc") == []
    assert not host.info["cyclonedds"].exists() and host.done("cyclonedds")[0] == "1"


@pytest.mark.parametrize("how", ["unset", "empty", "no-pubbad", "no-subv", "no-directory"])
def test_cyclonedds_without_the_peers_sources_the_library_is_built_and_the_exit_status_says_so(host, how):
    env = {"PEER_SRC": _fwd(host.peers)}
    if how == "unset":
        env = {"PEER_SRC": ""}
    elif how == "empty":
        (host.peers / "pubbad.c").unlink()
        (host.peers / "subv.c").unlink()
    elif how == "no-pubbad":
        (host.peers / "pubbad.c").unlink()
    elif how == "no-subv":
        (host.peers / "subv.c").unlink()
    else:
        env = {"PEER_SRC": _fwd(host.root / "nowhere")}
    r = host.run("cyclonedds", **env)
    assert r.returncode == 3, r.all
    assert "NOT BUILT: the peers pubbad and subv" in r.err
    if how == "unset":
        assert "PEER_SRC is not set" in r.err
    for p in ("pubbad", "subv"):
        gone = how in ("empty", "no-directory") or how == "no-" + p
        assert ("%s.c is missing" % p in r.err) == gone, (p, r.err)
        assert not (host.dds_prefix / "bin" / p).exists(), "both or neither: one peer alone is not built"
    assert tools(r.calls, "gcc") == [] and [c.name for c in tools(r.calls)] == ["cmake", "cmake", "cmake", "idlc"]
    lines = info_lines(host, "cyclonedds")
    assert one(lines, "peers NOT BUILT").startswith("peers NOT BUILT (pubbad, subv): ")
    assert not [l for l in lines if l.startswith(("pubbad sha256", "subv sha256"))]
    assert one(lines, "libddsc sha256 ") and one(lines, "av.c sha256 ") and one(lines, "idlc sha256 ")
    assert host.done("cyclonedds")[0] == "3"
    s = host.status("cyclonedds")
    assert s.returncode == 1 and "ended with exit status 3" in s.stdout


def test_cyclonedds_a_peer_that_does_not_compile_fails_the_build(host):
    host.set("gcc_rc", "1")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and "pubbad" in r.err
    assert not host.info["cyclonedds"].exists() and host.done("cyclonedds")[0] == "1"


@pytest.mark.parametrize("name", ["SRC", "PREFIX", "BUILD"])
def test_cyclonedds_a_relative_path_is_refused_before_anything_runs(host, name):
    """idlc is started in the gen directory: a relative path would name something else there."""
    r = host.run("cyclonedds", **{name: "somewhere/relative"})
    assert r.returncode == 1 and "absolute" in r.err and "somewhere/relative" in r.err
    assert scopes(r.calls) == [] and not [c for c in r.calls if c.name == "git"]


def test_cyclonedds_a_source_directory_that_is_no_checkout_is_left_alone(host):
    _put(host.dds_src / "keep.txt", "somebody's\n")
    r = host.run("cyclonedds")
    assert r.returncode == 1 and "not a git checkout" in r.err
    assert _text(host.dds_src / "keep.txt") == "somebody's\n" and not [c for c in r.calls if c.name == "git"]


# ------------------------------------------------------------------ build-llama.sh

def test_llama_a_head_that_is_not_the_pin_is_refused(host):
    host.set("git_checkout_stays")
    r = host.run("llama")
    assert r.returncode == 1, r.all
    assert NOT_A_PIN in r.err and LLAMA_PIN in r.err
    assert tools(r.calls) == [] and not host.info["llama"].exists()
    assert host.done("llama")[0] == "1"


def test_llama_an_existing_checkout_at_another_commit_is_moved_to_the_pin_and_read_back(host):
    _put(host.llama_src / ".git" / "STUB_HEAD", NOT_A_PIN)
    r = host.run("llama")
    assert r.returncode == 0, r.all
    src = ["-C", _fwd(host.llama_src)]
    assert [c.args for c in r.calls if c.name == "git"] == [
        src + ["rev-parse", "HEAD"], GIT_NET + src + ["checkout", "--quiet", "--detach", LLAMA_PIN], src + ["rev-parse", "HEAD"],
        src + ["status", "--porcelain", "--untracked-files=no"]]
    _put(host.llama_src / ".git" / "STUB_HEAD", LLAMA_PIN)
    r = host.run("llama")
    assert r.returncode == 0 and not [c for c in r.calls if c.name == "git" and "checkout" in c.args], \
        "at the pin already: nothing is fetched or moved"


def test_llama_the_clone_stays_a_git_checkout(host):
    r = host.run("llama")
    assert r.returncode == 0, r.all
    clone = [c for c in r.calls if c.name == "git"][0]
    assert clone.args == GIT_NET + ["clone", "--quiet", "--filter=blob:none", "https://github.com/ggml-org/llama.cpp.git",
                                    _fwd(host.llama_src)]
    assert (host.llama_src / ".git").is_dir(), "the stamp reads the commit with git -C ~/llama.cpp"
    code = _code(_text(SCRIPTS["llama"]))
    assert not re.search(r"\brm\b[^\n]*\$SRC[\"/ ]*(\n|$)|\.git\b[^\n]*\brm\b|\brm\b[^\n]*\.git\b|archive|tarball|\.tar|curl|wget", code), \
        "the source comes by git and is never replaced by an archive or removed"


def test_llama_a_directory_in_the_clone_s_place_that_is_no_checkout_is_left_alone(host):
    _put(host.llama_src / "notes.txt", "somebody's\n")
    r = host.run("llama")
    assert r.returncode == 1 and "not a git checkout" in r.err
    assert _text(host.llama_src / "notes.txt") == "somebody's\n" and tools(r.calls) == []


def test_llama_no_nvcc_is_refused_by_name_before_anything_is_fetched(host):
    shutil.rmtree(str(host.usr_local / "cuda-0.0"))
    r = host.run("llama")
    assert r.returncode == 1
    assert "no nvcc under %s/cuda*/bin" % _fwd(host.usr_local) in r.err
    assert not [c for c in r.calls if c.name == "git"] and tools(r.calls) == [] and scopes(r.calls) == []
    assert host.done("llama")[0] == "1"


def test_llama_the_flags_and_the_found_nvcc_reach_cmake(host):
    """The plan's three, Release, and the two that keep the build off the network: at the pin
    the server's build would otherwise fetch the web UI's files while it runs and embed
    whatever came, so the commit and the flags would not say what was built."""
    r = host.run("llama")
    assert r.returncode == 0, r.all
    cm = tools(r.calls, "cmake")
    assert len(cm) == 2 and uncapped(r.calls) == []
    assert LLAMA_FLAGS[:3] == ["-DGGML_CUDA=ON", "-DCMAKE_CUDA_ARCHITECTURES=87", "-DLLAMA_CURL=OFF"]
    assert LLAMA_FLAGS[4:] == ["-DLLAMA_USE_PREBUILT_UI=OFF", "-DLLAMA_BUILD_UI=OFF"]
    assert cm[0].args == ["-S", _fwd(host.llama_src), "-B", _fwd(host.llama_src / "build")] + LLAMA_FLAGS + [
        "-DCMAKE_CUDA_COMPILER=%s" % _fwd(host.nvcc), "-DCUDAToolkit_ROOT=%s" % _fwd(host.usr_local / "cuda-0.0")]
    assert cm[1].args == ["--build", _fwd(host.llama_src / "build"), "--config", "Release", "--parallel", "2",
                          "--target", "llama-server", "llama-cli", "llama-bench"]


def test_llama_build_info_holds_the_commit_the_flags_the_nvcc_and_each_binary(host):
    host.set("llama_libs")
    r = host.run("llama")
    assert r.returncode == 0, r.all
    lines = info_lines(host, "llama")
    assert lines[0] == "llama.cpp commit %s from https://github.com/ggml-org/llama.cpp.git" % LLAMA_PIN
    assert one(lines, "flags ") == "flags %s -DCMAKE_CUDA_COMPILER=%s -DCUDAToolkit_ROOT=%s" % (
        " ".join(LLAMA_FLAGS), _fwd(host.nvcc), _fwd(host.usr_local / "cuda-0.0"))
    assert one(lines, "targets ") == "targets llama-server llama-cli llama-bench"
    assert one(lines, "nvcc ").startswith("nvcc %s" % _fwd(host.nvcc))
    assert one(lines, "nvcc ").endswith(": Cuda compilation tools, release 0.0, V0.0.0-stub")
    assert re.match(r"^built \S+Z with g\+\+ \(Stub 0\.0-s1\) 0\.0\.0; cmake version 0\.0\.0-stub$", one(lines, "built "))
    for n in ("llama-server", "llama-cli", "llama-bench"):
        assert one(lines, n + " sha256 ") == "%s sha256 %s" % (n, _sha(host.llama_bin / n))
    assert sorted(l for l in lines if l.startswith("lib sha256 ")) == sorted(
        "lib sha256 %s %s" % (_sha(host.llama_bin / n), n) for n in ("libllama.so", "libggml-cuda.so"))
    assert one(lines, "tracked files changed against the commit: ").endswith(": 0")


@pytest.mark.parametrize("log, names", [(MISSING_CUDART, ["CUDA_CUDART", "CUDAToolkit"]), (MISSING_CUBLAS, ["CUDA::cublas"])],
                         ids=["cudart", "cublas"])
def test_llama_a_missing_cuda_component_is_named_from_cmake_s_failure(host, log, names):
    host.set("cmake_fail_llama", log)
    r = host.run("llama")
    assert r.returncode == 1, r.all
    said = [l for l in r.err.splitlines() if "names as missing" in l]
    assert len(said) == 1, r.err
    assert said[0].split("names as missing: ")[1].split(". ")[0].split() == sorted(names)
    assert "not by the full toolkit" in r.err and _fwd(host.llama_src / "build" / "cmake.log") in r.err
    assert [c.name for c in tools(r.calls)] == ["cmake"], "nothing is built after a failed configure"
    assert host.done("llama")[0] == "1" and not host.info["llama"].exists()


def test_llama_a_configure_the_cap_ended_is_not_reported_as_missing_components(host):
    """A configure check the kernel killed reads, to cmake, as something that is not there, so
    the log of such a configure names things as missing too. The count comes before the log."""
    host.set("cmake_fail_llama", MISSING_CUDART)
    host.set("sdrun_oom_kill", "1")
    r = host.run("llama")
    assert r.returncode == 1, r.all
    assert "counts 1 oom_kill: the memory cap (4G) was hit" in r.err
    assert "names as missing" not in r.err and "Widen" not in r.err and "widen" not in r.err
    assert _fwd(host.llama_src / "build" / "cmake.log") in r.err
    host.set("sdrun_oom_kill", "0")
    r = host.run("llama")
    assert r.returncode == 1 and "names as missing: CUDAToolkit CUDA_CUDART. If these are CUDA components, widen" in r.err
    assert "counts no oom_kill: the memory cap did not end it" in r.err, "and a configure the cap did not end says that too"


def test_llama_a_failure_that_names_nothing_shows_cmake_s_own_error_lines(host):
    host.set("cmake_fail_llama", MISSING_NOTHING)
    r = host.run("llama")
    assert r.returncode == 1 and "names nothing as missing" in r.err
    assert "CMake Error: The source directory does not appear to contain CMakeLists.txt." in r.err


@pytest.mark.parametrize("missing", ["llama-server", "llama-cli", "llama-bench"])
def test_llama_a_target_the_build_did_not_leave_fails_it_by_name(host, missing):
    host.set("llama_skips_" + missing)
    r = host.run("llama")
    assert r.returncode == 1 and "no %s" % missing in r.err
    assert not host.info["llama"].exists() and host.executed() == []


@pytest.mark.parametrize("target", ["llama-server", "llama-cli", "llama-bench"])
def test_llama_a_binary_an_earlier_run_left_is_not_taken_for_this_run_s(host, target):
    """A run that was cut in its last link leaves the binary half written and newer than its
    objects, because a linker writes its output in place. The next run's make has nothing to
    do for it; the file is there and not empty; and it would be hashed into BUILD-INFO under
    this build's commit. Here the build ends well and leaves that target as it finds it."""
    assert host.run("llama").returncode == 0 and (host.llama_bin / target).exists()
    host.set("llama_skips_" + target)
    r = host.run("llama")
    assert r.returncode == 1 and "left no %s" % target in r.err, r.all
    assert not (host.llama_bin / target).exists() and not host.info["llama"].exists()
    assert host.done("llama")[0] == "1" and host.executed() == []


def test_llama_build_info_says_what_web_ui_the_server_holds(host):
    """With both flags off the pin's build still embeds a web UI it finds: a tools/ui/dist in
    the source, else one in the build tree (which an earlier build that did fetch leaves there).
    Neither comes with the commit and the flags, so BUILD-INFO says which was there."""
    r = host.run("llama")
    assert r.returncode == 0, r.all
    src, bld = host.llama_src / "tools" / "ui" / "dist", host.llama_src / "build" / "tools" / "ui" / "dist"
    assert one(info_lines(host, "llama"), "web UI: ") == (
        "web UI: none embedded -- not fetched and not built (the two UI flags above), and no index.html in %s or %s"
        % (_fwd(src), _fwd(bld)))
    _put(bld / "index.html", "<html>left by an earlier build</html>\n")
    assert host.run("llama").returncode == 0
    assert one(info_lines(host, "llama"), "web UI: ") == (
        "web UI: NOT fetched by this build, and %s holds one (index.html sha256 %s): at the pin the server's build embeds it"
        % (_fwd(bld), _sha(bld / "index.html")))
    _put(src / "index.html", "<html>put into the source</html>\n")
    assert host.run("llama").returncode == 0
    assert one(info_lines(host, "llama"), "web UI: ").startswith("web UI: NOT fetched by this build, and %s holds one (index.html sha256 %s)"
                                                                  % (_fwd(src), _sha(src / "index.html"))), "the source's comes first"


def test_llama_the_header_says_why_the_web_ui_is_left_out():
    head = _text(SCRIPTS["llama"]).split("\nset -euo pipefail\n")[0]
    assert "-DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_UI=OFF" in head and "huggingface.co" in head and "HTTP API" in head
    assert "not run" in head, "what was read from the pin's files and not tried is said as that"


def test_llama_an_nvcc_named_in_the_environment_is_the_one_used(host):
    other = host.root / "elsewhere" / "cuda" / "bin" / "nvcc"
    _put(other, STUB_HEAD + NVCC_STUB)
    other.chmod(0o755)
    r = host.run("llama", NVCC=_abs_sh(other))
    assert r.returncode == 0, r.all
    assert "-DCMAKE_CUDA_COMPILER=%s" % _fwd(other) in tools(r.calls, "cmake")[0].args
    assert "-DCUDAToolkit_ROOT=%s" % _fwd(host.root / "elsewhere" / "cuda") in tools(r.calls, "cmake")[0].args
    r = host.run("llama", NVCC=_abs_sh(host.root / "elsewhere" / "nothing"))
    assert r.returncode == 1 and "is not an executable file" in r.err and tools(r.calls) == []


@pytest.mark.parametrize("which", ["llama", "fma"])
def test_an_nvcc_given_by_a_relative_path_is_refused(host, which):
    """It is a file and it can be run, from where the script was started; cmake is handed the
    words as they are and reads them from its own directory, or not at all."""
    rel = "usr-local/cuda-0.0/bin/nvcc"
    assert (host.root / rel).exists()
    r = host.run(which, _cwd=str(host.root), NVCC=rel)
    assert r.returncode == 1, r.all
    assert "NVCC='%s' is not an absolute path" % rel in r.err
    assert tools(r.calls) == [] and scopes(r.calls) == [] and not [c for c in r.calls if c.name == "git"]
    assert host.done(which)[0] == "1"


def test_two_cuda_toolkits_are_not_chosen_between(host):
    second = host.usr_local / "cuda-9.9" / "bin" / "nvcc"
    _put(second, STUB_HEAD + NVCC_STUB)
    second.chmod(0o755)
    for which in ("llama", "fma"):
        r = host.run(which)
        assert r.returncode == 1 and "more than one nvcc" in r.err, which
        assert "%s, %s" % (_fwd(host.nvcc), _fwd(second)) in r.err and "NVCC=<path>" in r.err
        assert tools(r.calls) == []


@pytest.mark.skipif(os.name == "nt", reason="no symbolic links for a test on Windows")
def test_the_cuda_symlink_beside_its_toolkit_is_one_nvcc(host):
    """/usr/local/cuda and /usr/local/cuda-<major> are links to the versioned directory. The
    name that is kept is the longest, whatever order the shell lists them in."""
    os.symlink(str(host.usr_local / "cuda-0.0"), str(host.usr_local / "cuda"))
    os.symlink(str(host.usr_local / "cuda-0.0"), str(host.usr_local / "cuda-0"))
    for which in ("llama", "fma"):
        for locale in ("C", "en_US.UTF-8"):
            r = host.run(which, LC_ALL=locale)
            assert r.returncode == 0, r.all
            assert one(info_lines(host, which), "nvcc ").startswith("nvcc %s (%s): " % (_fwd(host.nvcc), _fwd(host.nvcc))), (which, locale)
    r = host.run("llama")
    assert "-DCUDAToolkit_ROOT=%s" % _fwd(host.usr_local / "cuda-0.0") in tools(r.calls, "cmake")[0].args


# ------------------------------------------------------------------ build-fma.sh

def test_fma_no_nvcc_is_refused_by_name(host):
    shutil.rmtree(str(host.usr_local / "cuda-0.0"))
    r = host.run("fma")
    assert r.returncode == 1 and "no nvcc under %s/cuda*/bin" % _fwd(host.usr_local) in r.err
    assert tools(r.calls) == [] and scopes(r.calls) == []
    assert not host.fma.exists() and host.done("fma")[0] == "1"


def test_fma_is_the_readme_s_line_with_the_nvcc_that_was_found(host):
    r = host.run("fma")
    assert r.returncode == 0, r.all
    nv = tools(r.calls)
    assert len(nv) == 1 and nv[0].name == "nvcc" and nv[0].scope == CAP
    assert nv[0].args == ["-O3", "-arch=sm_87", "-o", _fwd(host.fma), _fwd(os.path.join(GC, "fma.cu"))]
    assert step_cmd(host, scopes(r.calls)[1])[0] == _fwd(host.nvcc), "the nvcc under /usr/local/cuda*, by its path: none is taken from PATH"


def test_fma_writes_a_sha256_beside_the_binary_and_a_build_info(host):
    r = host.run("fma")
    assert r.returncode == 0, r.all
    side = host.home / "gpuload" / "fma.sha256"
    assert _text(side) == "%s  fma\n" % _sha(host.fma), "in the form `sha256sum -c` reads, from the binary's directory"
    lines = info_lines(host, "fma")
    assert lines[0] == "fma from fma.cu sha256 %s" % _sha(os.path.join(GC, "fma.cu"))
    assert one(lines, "flags ") == "flags -O3 -arch=sm_87"
    assert one(lines, "nvcc ") == "nvcc %s (%s): Cuda compilation tools, release 0.0, V0.0.0-stub" % (_fwd(host.nvcc), _fwd(host.nvcc))
    assert one(lines, "fma sha256 ") == "fma sha256 %s" % _sha(host.fma)
    assert re.match(r"^built \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", one(lines, "built "))


def test_fma_a_failed_compile_leaves_no_binary_of_an_earlier_run_and_no_sha256(host):
    assert host.run("fma").returncode == 0
    host.set("nvcc_rc", "1")
    r = host.run("fma")
    assert r.returncode == 1
    for p in (host.fma, host.home / "gpuload" / "fma.sha256", host.info["fma"]):
        assert not p.exists(), p
    assert host.done("fma")[0] == "1"


def test_fma_a_compile_that_ends_well_and_leaves_nothing_is_a_failure(host):
    _put(host.nvcc, STUB_HEAD + 'if [ "${1:-}" = --version ]; then echo "Cuda compilation tools, release 0.0"; fi\n')
    host.nvcc.chmod(0o755)
    r = host.run("fma")
    assert r.returncode == 1 and "left no" in r.err and not host.info["fma"].exists()
