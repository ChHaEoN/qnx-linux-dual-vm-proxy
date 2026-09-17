#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# make-s1-images.sh — generate, check, build and wrap the S1-F host images, and
# emit the TCG profile of the S1 host script for the TCG builder.
#
# Phase 3b, the S1-F design's §3.9, §4.2, §5.1 and §6.1 steps 4, 5 and 7
# (results/orin-native-port/20260909T1100Z/s1-design.md, revision 2; the owner
# took D1-D19 as recommended). Compile-only: nothing here talks to the board,
# and no image it builds has run there. Derived from make-m4-images.sh and
# make-m1b-images.sh, whose patterns it keeps; neither is edited.
#
#   BSP=/path/to/BSP QNX_BASE=/path/to/qnx800 \
#       ./make-s1-images.sh [--generate-only] [--out DIR] [--q2-limit 0xADDR] [image ...]
#   ./make-s1-images.sh --tcg [--out DIR] [--q2-limit 0xADDR] [variant ...]
#   ./make-s1-images.sh --selftest [--out DIR]
#
#   image      startup line                              role (design §6.12)
#   s1-m1b-p6  M1b's -P6 line, no -b                     B1: M1b's m1b-p6 buildfile byte for byte, S1's startup
#   s1-h1      ... -m992M -Wkeep -A -b w2,canary -Dtcu   B2: host mode, no qvm launch
#   s1-n1      the same                                  B3: boot mode, pass item 2
#   s1-n2      the same                                  B4: hold mode, pass item 4
#   s1-d1      the same                                  diagnostic, boot mode with s1-d1.conf; never a pass run
#   s1-q2      the same                                  B5: q2 mode; refused without --q2-limit (D1, D14).
#                                                        OD9 (2026-09-17) reversed the guest set to QNX
#                                                        plus Linux, so B5 is owed. D14's limit is
#                                                        derived: 0x8E000000 (see the geometry gate).
#                                                        Never built; B5 has never run.
#   s1-j1      the same                                  J6 (revision 3, §15.4.8): host mode with memcanary-w
#                                                        and a large hold in place of B2's allocation; never a pass run
# With no names the board form does the first five, in that order; s1-q2 and s1-j1
# only when named.
#
#   variant    mode    at /data/s1/s1-linux.conf         role (TCG profile, design §6.2-§6.4, §5.3)
#   lin-dryrun dryrun  the pinned configuration          T1
#   lin-boot   boot    the pinned configuration          T2
#   hold       hold    the pinned configuration          T3 (memcanary hold -s 64)
#   d1-dryrun  dryrun  logger with debug,verbose         diagnostic (§3.7); never a pass run
#   d1-boot    boot    logger with debug,verbose         diagnostic; never a pass run
#   d2         boot    rdinit=/bin/sh, the stock initrd  diagnostic I-c: the L4T initrd at /data/s1/initrd.cpio.gz
#   q2         q2      the pinned configuration, M3's guest  T3's optional q2 rehearsal; refused without --q2-limit
#   j1         dryrun  the pinned configuration          T-J1 (§15.5 B8.5): memcanary-w --selftest; never a pass run
# With no names --tcg does the first six; q2 and j1 only when named. The names and the staging (a diagnostic's
# configuration and d2's initrd under the pinned names) are build-s1tcg-image.ps1's
# -Variant, -Mode and data_files lines, so its -HostScript can take these scripts.
#
# Output root: --out DIR, else S1_OUT, else orin-native/shim/out/s1, beside M1b-M4's
# shim/out/m1b..m4 and the directory s1-board.sh reads <image>.kimg and
# <image>.params from by default (its S1_KIMG_DIR). It must resolve inside this
# repository, be git-ignored, and lie outside the earlier milestones' outputs and
# orin-native/s1/out/ (the inputs), so a test run never clobbers a real one. A build
# into another --out needs S1_KIMG_DIR set to it on the board harness's side.
#
# Board steps, stopping at the first failure with "FAIL: <step>":
#    1. output guard; 2. git status snapshot
#    3. PO-A: the earlier milestones' sources and S1's inputs match git HEAD
#    4. pins: the Image (sha256 and its arm64 header), the L4T initrd, the initrd
#       and its cpio stream, init.sh and the manifest's pins, the configuration
#       and its cmdline, the tools, PIN_STARTUP_S1 (and, when BSP is set, that
#       the shared BSP output still holds the M1b-M4 build)
#    5. the configuration gate (parse-s1.py conf) and the parser's own selftest
#    6. the constant check: t234_startup.h's T234_* against memcanary.c's S1_*,
#       the design's values and parse-s1.py's; overlaps and edges (§3.3)
#    7. the diagnostic configurations, each checked to differ from the pinned one
#       only where it should; for s1-q2, the guest pins and PO-E (as M4)
#    8. per image: the bound table, guard and return bound (C14); the
#       buildfile (verbatim ranges, startup line, script lines); the host script
#       (markers, CONFIG fields, the profile check); kshcheck --selftest, each
#       script, an injected pipe; bash -n; <image>.params; the profile check's own
#       self-test (§15.5 B5's injections); for s1-j1 the black-box text estimate (B8.6)
#   --generate-only stops here (after the step-15 guard) and needs no SDP.
#    9. SDP environment, inputs, the symbol precondition on S1's startup
#   10. per image: the size check, mkifs, dumpifs (names, script), geometry
#   11. the startup arguments baked into the IFS
#   12. dumpifs extraction of every payload file and the host script, re-hashed
#   13. build-shim.sh jump: the kimg is the 8 KiB shim page plus this IFS
#   14. the startup and every tool unchanged since step 4
#   15. every file written is git-ignored and git status equals the snapshot
#   16. table: sizes, hashes and the .params contents
#
# --tcg runs steps 1-7, then per variant writes <out>/tcg/s1tcg-<variant>/
# (s1-host.ksh, s1tcg.params, files.list, system_files.lines, data_files.lines)
# with kshcheck and the profile check, then step 15. It needs no SDP.
#
# --selftest runs steps 1-2, the constant check, the profile check's self-test, s1-j1's
# black-box estimate and kshcheck's pipe injection on scripts it generates under
# <out>/gate/selftest, then step 15. It skips PO-A and the pins, so it runs on an
# uncommitted edit; it needs the S1 payload inputs present (their md5s go into the
# scripts) and no SDP, and nothing it writes is an image input.
#
# QNX files are handled as opaque bytes only: mkifs, dumpifs and hashes, as the
# M3 and M4 generators do; dumpifs -x extracts only our own payload from our
# own IFS. The Linux Image and the initrd's files are GPL and LGPL private
# copies and stay under git-ignored paths (design, Licence status).
set -Eeuo pipefail

BOARD=t234-orin-nano
HERE="$(cd "$(dirname "$0")" && pwd)"
NATIVE="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$NATIVE/.." && pwd)"
TOOLS="$NATIVE/tools"
SHIM="$NATIVE/shim"
S1="$NATIVE/s1"
QHVCONF="$NATIVE/qhv"
S1_STARTUP_DIR="$S1/out/startup"
STARTUP_BIN="$S1_STARTUP_DIR/startup-$BOARD"
STARTUP_MAP="$S1_STARTUP_DIR/startup-$BOARD.map"
BUILD_TEMPLATE="$HERE/s1.build.in"
KSH_TEMPLATE="$HERE/s1-host.ksh.in"
M3_BUILD_TEMPLATE="$HERE/m3.build.in"
M2_TEMPLATE="$HERE/m2.build.in"
STARTUP_HDR="$HERE/$BOARD/t234_startup.h"
MEMCANARY_C="$TOOLS/memcanary.c"
CONF_SRC="$S1/s1-linux.conf"
INIT_SRC="$S1/init.sh"
MANIFEST="$S1/initrd.manifest"
PARSER="$S1/parse-s1.py"
IMAGE_SRC="$S1/out/l4t/Image"
L4T_INITRD_SRC="$S1/out/l4t/initrd"
INITRD_SRC="$S1/out/initrd.cpio.gz"
G2_SRC="$QHVCONF/g2-m3.conf"
ASRUN_POST="$REPO/qhv/host/output/build/post_startup.sh"
GUEST_IFS="$REPO/qhv/guest/output/ifs.bin"
GUEST_DISK="$REPO/qhv/guest/output/disk-qvm"
CLIENT="$REPO/ipc-test/qnx-host-client/qnx-host-client"
DESIGN="results/orin-native-port/20260909T1100Z/s1-design.md"
OUT="${S1_OUT:-$SHIM/out/s1}"
BSP="${BSP:-}"

# ---- pins ---------------------------------------------------------------------------
# S1's startup (-b), kept at orin-native/s1/out/startup. The shared BSP output keeps
# the M1b-M4 build, which make-m1b..m4-images.sh read; this script never writes it.
# 2026-09-15, revision 4 (s1-design §16.3-16.4, D66-D68): moved with the -b-only data cache
# clean by VA at site B; the determinism rebuild matched, the symbol gates re-run, PIN_STARTUP_M
# unchanged.
PIN_STARTUP_S1=4df167a5739e8669dce59046550173eaac90d925f9004b9b599b569e7dc8a424
PIN_STARTUP_M=90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896
# D3's copies of the board's /boot/Image and /boot/initrd (L4T R36.4.7).
PIN_IMAGE=b844b7cfaafd071a25f1dc91d2ad1d7369008c28ce84b25625efc425825a2120
PIN_L4T_INITRD=f0cdcc61064ff6e9ac99b1c4ff02468dbe9cf0c0e9404cf429524d741f6883f8
# mkcpio.py's output from initrd.manifest: the gzip file, then the cpio stream in it.
PIN_INITRD=44e81ea65903e25a66cafe6b35f28776bba1f6ae8082251cc8a988a689495ab6
PIN_CPIO=3bf6a9878d3a53d752303ddc895c6527ed448494e97bc9bf7b42464ad87d65fe
PIN_INIT=2736648fbc5ce165ff942f93020dcfe933c14551879b36c0246ba5ad934d443e
# The configuration, and the sha256 of its cmdline string between the quotes.
PIN_CONF=85d51359229ea4fa9860de76519a523250e71c5c77666821a07e7f4561196e31
PIN_CMDLINE=da47f63ebedf99e1c560e1157ce176d6c56ad2953d040287bf6db8704f337638
# The tools as built at T0 part 1 (s1con, memcanary) and as M4 left them.
PIN_S1CON=ed4a5a0be95e96b091d9bffc8780070e44265663775f2dfb4e41dd323a83cfe9
PIN_MEMCANARY=d3749ffff064f5a3b7f9c4de9afb6bd849c22824a9531e2fc4b50d894bde5dc4
# Revision 3's watcher (s1-design.md §15.4.8, §15.5 B2 and B5): memcanary.c built with
# -DMEMCANARY_WATCH, checked only when s1-j1 or the TCG variant j1 is named. memcanary's
# own pin above never moves. The sha256 of the memcanary-w built beside gate B8.1's
# determinism builds (the same toolchain and flags, identical in two scratch builds and the
# tree), set in the commit that adds the watcher; pins_tools refuses any other binary.
# 2026-09-14, before J6's pre-registration: moved with the watcher's revert, whole_heal, dump-name
# and class-precedence amendments (s1-design §15.12); gate B8.1 re-run, PIN_MEMCANARY unchanged.
PIN_MEMCANARY_W=197b66ff6b31a38b6f1099544866f58c726236187fb2c0a8d0a5ed2c78259e4e
PIN_STAMP=b41cde750fea863d549c6978f08098e59189a705555cb76f681ec8a5b0c450bb
PIN_BWAIT=81daef09bfbb4cac6931a0f67d1ef2336a0b4a239a621312addd59dff9a98eca
PIN_TCUCAT=2dd6099a9d9dac3f7ad25d8e573553097d1fef74990c445578267b874dff066e
PIN_SMPCHECK=f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0
# B1: M2's m2-p6.build (make-m1b-images.sh:121), the m1b-p6.build M1b derived from it
# (the buildfile of the m1b-p6 kimg R2 and R2b ran), and that kimg's sha256 prefix.
PIN_M2_P6_BUILD=1830b690ce2722d27c319a2357f5189c3819250f84def58ae2fd610bd3acc7a8
PIN_M1B_P6_BUILD=6063a5b9aa53cf6fe2ed41d4d8dfb95db082663bed9031d59729a6f558e1d8bf
PIN_M1B_P6_KIMG24=85970fe84cb5ed644e2cced6
# s1-q2 only (make-m4-images.sh:92-96).
PIN_GUEST=434647a7cabfe5a1b503fab6c6309894aceccd03d74bb3882ea81caff22a83bd
PIN_DISK=55571618524e6cbc7a691b8109734783b479261a2f97206b71fa75f07ee31477
PIN_CLIENT=52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb

# ---- design constants -----------------------------------------------------------------
STARTUP_WANT="startup-$BOARD -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -b w2,canary -Dtcu"
M1B_STARTUP_WANT="startup-$BOARD -vvv -P6 -Q enable,el2-host -m992M -Wkeep -Dtcu"
GEOMETRY_CAP=0x8C000000       # m3-design.md:972, s1-design.md §4.4; s1-q2 uses --q2-limit
CANARY_C1_BASE=0xBD000000     # §3.3; a --q2-limit may not reach it

# D14's limit, derived 2026-09-17 under OD9, as design §6.1 step 7 requires: "compute
# D14's limit ... write it into the generator's geometry gate with its derivation as a
# comment; then build s1-q2, which must pass it".
#
# The rule: "window 1 keeps the two-guest budget's non-guest share". Window 1 is 992 MiB at
# 0x80000000; canary c1 takes its top 16 MiB from 0xBD000000, so 976 MiB is usable below c1.
# §4.5's gate of 1,255 MiB decomposes as 512 (Linux guest) + 512 (QNX guest) + 146.3
# (/dev/shmem/disk-qvm, 153,432,576 B = 146.32, the copy devb-loopback holds) + 20 (qvm) +
# 64 (margin) = 1,254.3, which §4.5 rounds up to the 1,255 the gate states.
# Window 2 carries the 1,024 MiB of guest RAM, so window 1 must keep the NON-guest share:
#
#   ceiling, §4.5's terms   146.3 + 20 + 64 = 230.3, + 15.4 kernel/syspage = 246 MiB
#                            0xBD000000 - 0xF600000  = 0xADA00000
#   ceiling, step 7 literal  ("§3.3's table with the QNX rows restored") also adds the
#                            4 MiB daemons row and io-blk's 21.8 = 271.5 -> 272 MiB
#                            0xBD000000 - 0x11000000 = 0xAC000000   <- the stricter reading
#   floor                    size_check's pre-mkifs sum (it dies BEFORE mkifs, so this binds,
#                            not the real geometry): 0x80082fa0 + 217,557,819 = 0x8CFFDADB
#
# 0x8E000000 is chosen as a tight cap that satisfies the rule, not as the rule's ceiling:
# 16.01 MiB above the projected end. mkifs padding is not knowable beforehand, and size_check
# OVER-estimates: on m4 r0 it named an end of 0x8a738d82 against a real 0x8a5e9ccc, 1,372,342 B
# high (results/orin-native-port/20260916T1500Z/m4/m4-r0-rebuild.log, its size-check and
# geometry lines). That is the one measured precedent on file; no s1-n1 build log exists to
# corroborate it. So a limit clearing only the real end can still be refused at step 10, and
# 16 MiB covers an order more error than the single precedent shows. It leaves 752 MiB below
# c1 -- 2.8x the STRICTER reading's non-guest requirement, 3.2x the looser one. The stricter
# figure is the one that binds, and is the one quoted. A looser limit would be a weaker gate,
# not a safer one.
#
# What this derivation does NOT establish, stated because the numbers look firmer than they
# are: io-blk's 21.8 MiB is VENDOR_CLAIM with an UNKNOWN basis (total or free RAM) and qvm's
# own budget is UNKNOWN (m3-design.md:280-300); and D14's premise is not enforced anywhere --
# under -b w2 qvm may place guest RAM in EITHER window (design §3.3, Q14), so "window 2
# carries the 1,024 MiB" is a budget convention, not a guarantee. Under OD7 the guest disk is
# regenerated at the freeze and is not byte-reproducible, so PIN_DISK -- and with it the
# 146.3 MiB term and the floor above -- moves, and this limit is re-derived when it does.
Q2_LIMIT_DERIVED=0x8E000000
W1_MIB=992
# §5.1's memory gate constants, MiB.
declare -A MEM_GATE=([tcg:dryrun]=596 [tcg:boot]=596 [tcg:hold]=660 [tcg:q2]=1255
                     [board:host]=992 [board:dryrun]=596 [board:boot]=596 [board:hold]=852 [board:q2]=1255)
declare -A HOLD_MIB_OF=([tcg]=64 [board]=256)
HOLD_S=600
HB_COUNT=10
B2_ALLOC_MIB=1536
# J6 (s1-design.md §15.4.8, D27): the size of s1-j1's hold, design arithmetic only, never a
# FreeMem value (§2 rule 8). Windows 1 and 2 are 992 + 2,208 MiB, less the three 16 MiB
# canaries: 3,152 MiB. D27 leaves the margin below that to the implementation; it is set
# here, and each row is a design estimate (HYPOTHESIS):
#     64  the IFS in window 1, which alloc_ram keeps out of sysram (§4.4 estimates about 52)
#     16  procnto, the syspage, startup and the early processes (§3.3's 15.4, from M1b)
#     16  slogger2, pipe, devc-pty, ksh, the bwaits, toybox runs and memcanary's own process
#         (§3.3 budgets 4 for the first of these)
#     32  memcanary-w's two heap copies of a 16 MiB canary (base and prev), while watches c
#         and d run beside the hold
#      8  page tables for the hold's mapping (2,896 MiB of 4 KiB pages at 8 B each is under 6)
#      8  /dev/shmem: the four bitmaps (about 2 KiB each), pidin, bwait and slog2info output
#    112  slack for procnto's allocator and whatever this list misses
#    256  in all. Too small a margin shows as map=fail, F28: diagnostic incomplete, no verdict.
#         Watches c and d allocate their two copies after the fill, so it can also show as
#         watch=fail reason=nomem on c or d: F40, incomplete for an image reason (s1-design §15.12).
# By pigeonhole on the design sizes (R70), 2,896 MiB covers at least 1,920 of window 2's
# 2,176 MiB outside the canaries and at least 720 of window 1's 976; where procnto places the
# pages is HYPOTHESIS (R75). constant_check holds the sum and memcanary's 3,072 MiB limit.
J1_HOLD_MARGIN_MIB=256
J1_HOLD_MIB=2896
# §15.4.8's watch table as label:name:interval_ms:count:deadline_s. The bounds are the
# bound table's J1_W<label>_K; the profile check accepts exactly these four calls.
J1_WATCH_ROWS="a:c2:0:100000:20 b:c2:1000:180:190 c:c2:1000:180:190 d:c1:1000:60:70"
# M3's rebuild-at--vv threshold, R22's gate (parse-s1.py BB_GATE), for s1-j1's estimate (B8.6).
BB_GATE=60000
ITEM5_FIELDS="image_sha256 initrd_sha256 conf_sha256 cmdline_sha256 init_sha256 s1con_sha256 memcanary_sha256 stamp_sha256 bwait_sha256 startup_sha256 startup_line cpu_lines ram_line windows canaries guest_set hold_s guard_s gpu_range"

# PO-A (step 3): M1b-M4's sources, the shim, and every source S1's images are built from.
PO_A_PATHS=(
	orin-native/startup/m2.build.in
	orin-native/startup/make-m2-images.sh
	orin-native/startup/make-m1b-images.sh
	orin-native/startup/m3.build.in
	orin-native/startup/m3-host.ksh.in
	orin-native/startup/make-m3-images.sh
	orin-native/startup/m4.build.in
	orin-native/startup/m4-host.ksh.in
	orin-native/startup/make-m4-images.sh
	orin-native/startup/t234-orin-nano
	orin-native/shim/build-shim.sh
	orin-native/qhv/g2-m3.conf
	orin-native/tools/stamp.c
	orin-native/tools/bwait.c
	orin-native/tools/smpcheck.c
	orin-native/tools/tcu-cat.c
	orin-native/tools/s1con.c
	orin-native/tools/memcanary.c
	orin-native/s1/s1-linux.conf
	orin-native/s1/s1-conf.allow
	orin-native/s1/init.sh
	orin-native/s1/initrd.manifest
	# Revision 3 (§15.5 B5): S1's own templates, this generator, the tools' Makefile and the parser.
	orin-native/startup/s1.build.in
	orin-native/startup/s1-host.ksh.in
	orin-native/startup/make-s1-images.sh
	orin-native/tools/Makefile
	orin-native/s1/parse-s1.py
)

# /proc/boot names of a Linux-only image (design §3.9), each exactly once (step 10).
S1_IFS_NAMES=(
	.script procnto-smp-instr ldqnx-64.so.2
	libc.so.6 libgcc_s.so.1 libsecpol.so.1 libm.so.3 libqh.so.1 libregex.so.1
	libjail.so.1 libfsnotify.so.1 libsocket.so.4 libsocket.so libfdt.so.1 libfdt.so
	libcam.so.2 libslog2.so.1 libslog2.so libslog2parse.so.1 libslog2shim.so.1 libjson.so.1
	libz.so.2 libcrypto.so.3 libqcrypto.so.1.0 qcrypto-openssl-3.so libpci.so.3.0 qcrypto.conf
	tcu-cat stamp bwait smpcheck s1con memcanary s1-host.ksh
	ksh pidin on slay waitfor shutdown devc-pty slogger2 slog2info pipe
	qvm qvm-check vdev-pl011.so vdev-virtio-console.so
	toybox cat cp cmp grep head md5sum tail wc base64 od mkdir rm
)
# s1-q2 adds M3's guest-side names back.
Q2_NAMES=(io-blk.so cam-disk.so vdev-virtio-blk.so vdev-shmem.so devb-loopback qnx-host-client g2.conf guest-ifs.bin disk-qvm)
# Never in any S1 image.
ABSENT_NAMES=(vpctl vdev-virtio-net.so fs-qnx6.so random io-sock gawk awk gzip tracelogger traceprinter
	libtracelog.so.1 libtraceparser.so.1 m3-host.ksh m4-host.ksh m3-fake-guest.txt)
SDP_FILES=(
	sbin/qvm bin/qvm-check lib/dll/vdev-pl011.so lib/dll/vdev-virtio-console.so usr/lib/libfdt.so.1
	lib/libcam.so.2 bin/slogger2 bin/slog2info lib/libslog2.so.1 lib/libslog2parse.so.1
	lib/libslog2shim.so.1 lib/libjson.so.1 sbin/pipe usr/bin/toybox lib/libm.so.3
	lib/libqh.so.1 lib/libregex.so.1 lib/libjail.so.1 lib/libfsnotify.so.1 lib/libsocket.so.4
	usr/lib/libz.so.2 usr/lib/libcrypto.so.3 usr/lib/libqcrypto.so.1.0
	lib/dll/qcrypto-openssl-3.so lib/libpci.so.3.0
)
Q2_SDP_FILES=(lib/dll/vdev-virtio-blk.so lib/dll/vdev-shmem.so sbin/devb-loopback lib/dll/io-blk.so lib/dll/cam-disk.so)
HASHED_NAMES=(qvm qvm-check vdev-pl011.so vdev-virtio-console.so)
TOOL_NAMES=(tcu-cat stamp bwait smpcheck s1con memcanary)

STEP="argument parsing"
die() { echo "FAIL: $*" >&2; exit 1; }
trap 'echo "FAIL: $STEP (line $LINENO exited non-zero)" >&2' ERR

usage() {
	echo "usage: $0 [--generate-only] [--out DIR] [--q2-limit 0xADDR] [image ...]" >&2
	echo "       $0 --tcg [--out DIR] [--q2-limit 0xADDR] [variant ...]" >&2
	echo "       $0 --selftest [--out DIR]" >&2
	echo "  images:   s1-m1b-p6 s1-h1 s1-n1 s1-n2 s1-d1 (default), s1-q2 (needs --q2-limit), s1-j1 (needs PIN_MEMCANARY_W)" >&2
	echo "  variants: lin-dryrun lin-boot hold d1-dryrun d1-boot d2 (default), q2 (needs --q2-limit), j1 (needs PIN_MEMCANARY_W)" >&2
	exit 2
}

GEN_ONLY=0
TCG=0
SELFTEST=0
Q2_LIMIT=""
NAMES=()
while [ $# -gt 0 ]; do
	case "$1" in
	--generate-only) GEN_ONLY=1 ;;
	--tcg) TCG=1 ;;
	--selftest) SELFTEST=1 ;;
	--out)
		[ $# -ge 2 ] || usage
		OUT="$2"
		shift
		;;
	--q2-limit)
		[ $# -ge 2 ] || usage
		Q2_LIMIT="$2"
		shift
		;;
	-h|--help) usage ;;
	-*) echo "unknown option: $1" >&2; usage ;;
	*) NAMES+=("$1") ;;
	esac
	shift
done
if [ "$SELFTEST" = 1 ]; then
	[ "$GEN_ONLY" = 0 ] && [ "$TCG" = 0 ] && [ -z "$Q2_LIMIT" ] && [ "${#NAMES[@]}" = 0 ] \
		|| die "--selftest takes only --out: it generates its own scripts under <out>/gate/selftest and builds nothing"
elif [ "$TCG" = 1 ]; then
	[ "$GEN_ONLY" = 0 ] || die "--tcg generates only; --generate-only belongs to the board form"
	[ "${#NAMES[@]}" -gt 0 ] || NAMES=(lin-dryrun lin-boot hold d1-dryrun d1-boot d2)
	for n in "${NAMES[@]}"; do
		case "$n" in lin-dryrun|lin-boot|hold|d1-dryrun|d1-boot|d2|q2|j1) ;; *) echo "unknown variant: $n" >&2; usage ;; esac
	done
else
	[ "${#NAMES[@]}" -gt 0 ] || NAMES=(s1-m1b-p6 s1-h1 s1-n1 s1-n2 s1-d1)
	for n in "${NAMES[@]}"; do
		case "$n" in s1-m1b-p6|s1-h1|s1-n1|s1-n2|s1-d1|s1-q2|s1-j1) ;; *) echo "unknown image: $n" >&2; usage ;; esac
	done
fi
WANT_Q2=0
WANT_J1=0
for n in "${NAMES[@]}"; do
	case "$n" in s1-q2|q2) WANT_Q2=1 ;; s1-j1|j1) WANT_J1=1 ;; esac
done
# Revision 3's watcher is an input of s1-j1 and j1 only (§15.5 B5): pinned, present and
# unchanged during the run only when one of them is named.
if [ "$WANT_J1" = 1 ]; then
	TOOL_NAMES+=(memcanary-w)
fi
if [ "$WANT_Q2" = 1 ]; then
	[ -n "$Q2_LIMIT" ] || die "s1-q2 and the q2 variant are refused without --q2-limit: OD9 (2026-09-17) keeps the QNX guest and D14's limit is derived as $Q2_LIMIT_DERIVED (see its derivation above); pass it explicitly (design §6.1 step 7, §4.5)"
fi
if [ -n "$Q2_LIMIT" ]; then
	[ "$WANT_Q2" = 1 ] || die "--q2-limit is only for s1-q2 or the q2 variant"
	[[ "$Q2_LIMIT" =~ ^0x[0-9a-fA-F]{8,9}$ ]] || die "--q2-limit '$Q2_LIMIT' is not a hex address such as 0x8f000000"
	(( Q2_LIMIT > GEOMETRY_CAP && Q2_LIMIT <= CANARY_C1_BASE )) \
		|| die "--q2-limit $Q2_LIMIT must lie above the Linux-only cap $GEOMETRY_CAP and at or below canary c1's base $CANARY_C1_BASE"
	# The range above is the code's outer bound; D14's derived value is the one the design
	# gate asks for, so a different in-range number is refused rather than silently built.
	(( Q2_LIMIT == Q2_LIMIT_DERIVED )) \
		|| die "--q2-limit $Q2_LIMIT is not D14's derived limit $Q2_LIMIT_DERIVED; if the inputs moved (OD7 regenerates the guest disk and PIN_DISK with it), re-derive it at the geometry gate and change Q2_LIMIT_DERIVED with its arithmetic"
fi

# ---- helpers ------------------------------------------------------------------------
sha() { sha256sum "$1" | cut -d' ' -f1; }
md5() { md5sum "$1" | cut -d' ' -f1; }
hostpath() {
	if command -v cygpath >/dev/null 2>&1; then cygpath -m -- "$1"; else echo "$1"; fi
}
count_line() {
	awk -v want="$2" '{ sub(/\r$/, ""); $1 = $1 } $0 == want { c++ } END { print c + 0 }' "$1"
}
no_markers() {
	local left
	left=$(grep -nE '@[A-Z0-9_]+@' "$1" || true)
	[ -z "$left" ] || die "$STEP: markers survive substitution in $1: $left"
}
# How many times the lines of file $1 occur as a contiguous block in file $2 (make-m4-images.sh:249).
block_matches() {
	awk '
		FNR == NR { sub(/\r$/, ""); b[++n] = $0; next }
		{ sub(/\r$/, ""); h[++m] = $0 }
		END {
			c = 0
			for (i = 1; i + n - 1 <= m; i++) {
				ok = 1
				for (j = 1; j <= n; j++) if (h[i + j - 1] != b[j]) { ok = 0; break }
				if (ok) c++
			}
			print c
		}' "$1" "$2"
}
# expand KIND KEEP IN OUT KEY=VALUE...: make-m4-images.sh's literal substitution
# (its subst), plus line prefixes. KIND build drops every comment line; KIND ksh
# drops ## lines. A line that begins @BOARD@, @TCG@, @D1@, @D2@, @DIAG@, @Q2@ or @J1@
# is kept without the prefix when that name is in KEEP, and dropped otherwise. A line
# that begins @NOTJ1@ is kept without it unless J1 is in KEEP: s1-j1's watcher replaces
# B2's allocation lines (§15.4.8), and every other script keeps them byte for byte.
expand() {
	local kind="$1" keep="$2" in="$3" out="$4" kv i=0
	local -a envs=()
	shift 4
	for kv in "$@"; do
		envs+=("SUBST_K$i=${kv%%=*}" "SUBST_V$i=${kv#*=}")
		i=$((i + 1))
	done
	env "${envs[@]}" SUBST_N="$i" awk -v kind="$kind" -v keep=" $keep " '
		function repl(s, from, to,    o, k) {
			o = ""
			while ((k = index(s, from)) > 0) {
				o = o substr(s, 1, k - 1) to
				s = substr(s, k + length(from))
			}
			return o s
		}
		BEGIN {
			n = ENVIRON["SUBST_N"] + 0
			for (i = 0; i < n; i++) { K[i] = ENVIRON["SUBST_K" i]; V[i] = ENVIRON["SUBST_V" i] }
		}
		{ sub(/\r$/, "") }
		kind == "build" && /^[[:space:]]*#/ { next }
		kind == "ksh" && /^##/ { next }
		{
			line = $0
			drop = 0
			while (match(line, /^@(BOARD|TCG|D1|D2|DIAG|Q2|J1|NOTJ1)@/)) {
				p = substr(line, 2, RLENGTH - 2)
				if (p == "NOTJ1") {
					if (index(keep, " J1 ") > 0) drop = 1
				} else if (index(keep, " " p " ") == 0) drop = 1
				line = substr(line, RLENGTH + 1)
			}
			if (drop) next
			if (kind == "build" && line ~ /^[[:space:]]*#/) next
			for (i = 0; i < n; i++) line = repl(line, "@" K[i] "@", V[i])
			print line
		}
	' "$in" > "$out"
}
find_python() {
	local t
	PY_BIN=""
	# python, then py; never python3, which is a Store alias on some Windows hosts.
	for t in python py; do
		if command -v "$t" >/dev/null 2>&1 && timeout 60 "$t" -c pass >/dev/null 2>&1; then
			PY_BIN="$t"
			return 0
		fi
	done
	die "no working python (make-s1-images.sh runs parse-s1.py and the constant and startup-argument checks)"
}
check_pin() {
	local got
	[ -f "$1" ] || die "$STEP: no $1 ($3)"
	got=$(sha "$1")
	[ "$got" = "$2" ] || die "$STEP: $1 has sha256 $got, but $3 is pinned at $2"
	echo "   $STEP: $3, sha256 $got: ok"
}

# ---- steps 1-2 ------------------------------------------------------------------------

guard_output() {
	local out_r r p repo_r
	STEP="output directory (step 1)"
	out_r="$(realpath -m -- "$OUT")"
	repo_r="$(realpath -m -- "$REPO")"
	case "${out_r,,}/" in
	"${repo_r,,}/"*) ;;
	*) die "output directory $OUT resolves to $out_r, outside the repository; the ignore checks need it inside (for example orin-native/shim/out/s1-test)" ;;
	esac
	[ "${out_r,,}" != "${repo_r,,}" ] || die "output directory $OUT is the repository root"
	for r in "$SHIM/out/m1b" "$SHIM/out/m2" "$SHIM/out/m3" "$SHIM/out/m4" "$S1/out" "$REPO/qhv"; do
		r="$(realpath -m -- "$r")"
		case "${out_r,,}/" in
		"${r,,}/"*) die "output directory $OUT resolves to $out_r, inside $r, which this script must never write" ;;
		esac
	done
	OUT="$out_r"
	command -v git >/dev/null 2>&1 || die "git is needed for the ignore checks and PO-A"
	for p in "$OUT/x.build" "$OUT/x.ksh" "$OUT/x.ifs" "$OUT/x.kimg" "$OUT/x.params" "$OUT/x.procnto-smp-instr.sym" \
	         "$OUT/gate/x.build" "$OUT/conf/s1-d1.conf" "$OUT/xtr-x/Image" "$OUT/tcg/s1tcg-boot/s1-host.ksh" \
	         "$OUT/tcg/s1tcg-boot/files.list" "$SHIM/out/t234-qnx.kimg"; do
		git -C "$REPO" check-ignore -q -- "$p" \
			|| die "$p would not be git-ignored; choose a git-ignored --out before building QNX or Linux files there"
	done
	GATE="$OUT/gate"
	mkdir -p "$OUT" "$GATE" "$OUT/conf"
	echo "   output: $OUT (inside the repository, git-ignored, outside the earlier outputs and the S1 inputs): ok"
}

snapshot_status() {
	STEP="git status snapshot (step 2)"
	STATUS_A="$(git -C "$REPO" status --porcelain)"
	echo "   git status --porcelain snapshot taken"
}

# ---- step 3 ----------------------------------------------------------------------------

po_a() {
	local rc=0
	STEP="PO-A (step 3)"
	git -C "$REPO" ls-files --error-unmatch -- "${PO_A_PATHS[@]}" >/dev/null 2>&1 \
		|| die "PO-A: one of the earlier milestones' sources or S1's inputs is not tracked by git"
	git -C "$REPO" diff --quiet HEAD -- "${PO_A_PATHS[@]}" || rc=$?
	case "$rc" in
	0) ;;
	1) die "PO-A: a source S1 builds from, or an earlier milestone's, differs from git HEAD: commit it or restore it, then rebuild" ;;
	*) die "PO-A: git diff failed (exit $rc)" ;;
	esac
	echo "   PO-A ${#PO_A_PATHS[@]} sources (M1b-M4, the shim, the tools and their Makefile, the S1 inputs, templates, generator and parser, and the startup board source) match git HEAD: ok"
}

# ---- step 4: pins --------------------------------------------------------------------

pins_payload() {
	local hdr got
	STEP="payload pins (step 4)"
	check_pin "$IMAGE_SRC" "$PIN_IMAGE" "the board's /boot/Image (D3)"
	# §6.1 step 1: our reading of a Linux arm64 header (booting.html), not a QNX binary.
	hdr=$(od -An -tx1 -v -N64 "$IMAGE_SRC" | tr -d ' \n')
	[ "${hdr:0:4}" = 4d5a ] || die "$STEP: Image does not begin with MZ"
	[ "${hdr:16:16}" = 0000000000000000 ] || die "$STEP: Image text_offset is not 0"
	[ "${hdr:32:16}" = 00009b0200000000 ] || die "$STEP: Image image_size is not 0x029b0000"
	[ "${hdr:48:16}" = 0a00000000000000 ] || die "$STEP: Image flags are not 0xa"
	[ "${hdr:112:8}" = 41524d64 ] || die "$STEP: Image has no ARMd magic at 0x38"
	echo "   $STEP: Image header MZ, ARMd at 0x38, text_offset 0, image_size 0x029b0000, flags 0xa: ok"
	check_pin "$L4T_INITRD_SRC" "$PIN_L4T_INITRD" "the board's /boot/initrd (D3)"
	check_pin "$INITRD_SRC" "$PIN_INITRD" "the S1 initrd (gzip)"
	got=$(gzip -dc "$INITRD_SRC" | sha256sum | cut -d' ' -f1)
	[ "$got" = "$PIN_CPIO" ] || die "$STEP: the cpio stream inside $INITRD_SRC has sha256 $got, pinned at $PIN_CPIO"
	echo "   $STEP: the cpio stream inside it, sha256 $got: ok"
	check_pin "$INIT_SRC" "$PIN_INIT" "the guest's /init (init.sh)"
	[ "$(count_line "$MANIFEST" "file init 0755 $PIN_INIT local init.sh")" = 1 ] \
		|| die "$STEP: initrd.manifest does not pin init.sh at $PIN_INIT"
	[ "$(count_line "$MANIFEST" "output out/initrd.cpio.gz $PIN_INITRD $PIN_CPIO")" = 1 ] \
		|| die "$STEP: initrd.manifest's output pins are not this script's"
	[ "$(count_line "$MANIFEST" "source l4t out/l4t/initrd $PIN_L4T_INITRD")" = 1 ] \
		|| die "$STEP: initrd.manifest's source pin is not this script's"
	echo "   $STEP: initrd.manifest pins the same init.sh, source and output: ok"
	check_pin "$CONF_SRC" "$PIN_CONF" "the S1 configuration"
}

pins_tools() {
	STEP="tool pins (step 4)"
	check_pin "$TOOLS/s1con" "$PIN_S1CON" "s1con"
	check_pin "$TOOLS/memcanary" "$PIN_MEMCANARY" "memcanary"
	if [ "$WANT_J1" = 1 ]; then
		[[ "$PIN_MEMCANARY_W" =~ ^[0-9a-f]{64}$ ]] \
			|| die "$STEP: PIN_MEMCANARY_W is not a sha256 yet ($PIN_MEMCANARY_W): s1-j1 and j1 wait until memcanary-w passes gate B8.1 and its pin is committed (§15.5 B9)"
		check_pin "$TOOLS/memcanary-w" "$PIN_MEMCANARY_W" "memcanary-w (revision 3's watcher)"
	fi
	check_pin "$TOOLS/stamp" "$PIN_STAMP" "stamp"
	check_pin "$TOOLS/bwait" "$PIN_BWAIT" "bwait"
	check_pin "$TOOLS/tcu-cat" "$PIN_TCUCAT" "tcu-cat"
	check_pin "$TOOLS/smpcheck" "$PIN_SMPCHECK" "M1b's smpcheck"
}

pins_startup() {
	local shared
	STEP="startup pins (step 4)"
	check_pin "$STARTUP_BIN" "$PIN_STARTUP_S1" "S1's startup (PIN_STARTUP_S1)"
	if [ -n "$BSP" ]; then
		shared="$BSP/src/hardware/startup/boards/$BOARD/aarch64/le/startup-$BOARD"
		if [ -f "$shared" ]; then
			[ "$(sha "$shared")" = "$PIN_STARTUP_M" ] \
				|| die "$STEP: the shared BSP output $shared no longer holds the M1b-M4 build $PIN_STARTUP_M; restore it (make-m1b..m4-images.sh read it) before any build"
			echo "   $STEP: the shared BSP output still holds the M1b-M4 build: ok (not used here)"
		else
			echo "   $STEP: no shared startup under BSP=; not checked (not used here)"
		fi
	else
		echo "   $STEP: BSP is not set; the shared M1b-M4 startup is not checked (not used here)"
	fi
}

# ---- step 5: the configuration gate -----------------------------------------------------

conf_gate() {
	local out rc=0
	STEP="configuration gate (step 5)"
	out="$(timeout 120 "$PY_BIN" "$PARSER" conf "$CONF_SRC" 2>&1)" || rc=$?
	printf '%s\n' "$out" | sed 's/^/   /'
	[ "$rc" = 0 ] || die "$STEP: parse-s1.py conf exited $rc on $CONF_SRC"
	grep -qx 'S1CONF gate=pass rejects=0 allow_errors=0' <<< "$out" || die "$STEP: no gate=pass line"
	grep -qx "S1CONF cmdline_sha256=$PIN_CMDLINE" <<< "$out" || die "$STEP: cmdline_sha256 is not the pin $PIN_CMDLINE"
	out="$(timeout 600 "$PY_BIN" "$PARSER" --selftest 2>&1)" || { grep -v ' ok$' <<< "$out" >&2 || true; die "$STEP: parse-s1.py --selftest failed"; }
	tail -n 1 <<< "$out" | sed 's/^/   /'
	echo "   $STEP: the configuration passes s1-conf.allow with the pinned cmdline; the parser's selftest passes: ok"
}

# ---- step 6: the constant check ----------------------------------------------------------

constant_check() {
	STEP="constant check (step 6)"
	timeout 120 "$PY_BIN" - "$STARTUP_HDR" "$MEMCANARY_C" "$PARSER" "$ITEM5_FIELDS" \
		"${MEM_GATE[tcg:dryrun]},${MEM_GATE[tcg:boot]},${MEM_GATE[tcg:hold]},${MEM_GATE[tcg:q2]},${MEM_GATE[board:dryrun]},${MEM_GATE[board:boot]},${MEM_GATE[board:hold]},${MEM_GATE[board:q2]}" \
		"${HOLD_MIB_OF[tcg]},${HOLD_MIB_OF[board]},$HOLD_S,$HB_COUNT,$B2_ALLOC_MIB,$W1_MIB" \
		"$GEOMETRY_CAP" "${Q2_LIMIT:-0}" "$J1_HOLD_MIB,$J1_HOLD_MARGIN_MIB,$WANT_J1" <<'PY' || die "$STEP: the startup header, memcanary.c, the design and parse-s1.py disagree (reason above)"
import importlib.util
import re
import sys

hdr, mc, parser, item5, gates, misc, cap, q2, j1 = sys.argv[1:10]
bad = []

def defs(path, prefix):
    text = open(path, encoding="latin-1").read()
    d = {}
    for m in re.finditer(r"^#define\s+(" + prefix + r"\w+)\s+(0x[0-9A-Fa-f]+|\d+)[uUlL]*\b", text, re.M):
        d[m.group(1)] = int(m.group(2), 0)
    return d

T = defs(hdr, "T234_")
S = defs(mc, "S1_")
# The two name sets (s1-design.md §4.2, §4.3).
PAIRS = (("T234_RAM_BASE", "S1_W1_BASE"), ("T234_RAM_SIZE", "S1_W1_SIZE"),
         ("T234_RAM2_BASE", "S1_W2_BASE"), ("T234_RAM2_SIZE", "S1_W2_SIZE"),
         ("T234_GPU_BASE", "S1_GPU_BASE"), ("T234_GPU_SIZE", "S1_GPU_SIZE"),
         ("T234_CANARY_SIZE", "S1_CANARY_SIZE"), ("T234_CANARY1_BASE", "S1_CANARY_C1_BASE"),
         ("T234_CANARY2_BASE", "S1_CANARY_C2_BASE"), ("T234_CANARY3_BASE", "S1_CANARY_C3_BASE"),
         ("T234_BB_BASE", "S1_BB_BASE"), ("T234_BB_MAP", "S1_BB_SIZE"))
# §3.3's table and D18, and the black box (t234_startup.h:141-143).
DESIGN = {"T234_RAM_BASE": 0x80000000, "T234_RAM_SIZE": 0x3E000000, "T234_RAM2_BASE": 0x100000000,
          "T234_RAM2_SIZE": 0x8A000000, "T234_GPU_BASE": 0x18A000000, "T234_GPU_SIZE": 0xC0000000,
          "T234_CANARY_SIZE": 0x1000000, "T234_CANARY1_BASE": 0xBD000000, "T234_CANARY2_BASE": 0x100000000,
          "T234_CANARY3_BASE": 0x189000000, "T234_BB_BASE": 0x272770000, "T234_BB_MAP": 0x10000,
          "T234_SHIM_BASE": 0x80080000, "T234_SHIM_SIZE": 0x2000}
for t, s in PAIRS:
    if t not in T or s not in S:
        bad.append(f"missing {t if t not in T else s}")
    elif T[t] != S[s]:
        bad.append(f"{t}=0x{T[t]:x} but {s}=0x{S[s]:x}")
for k, v in DESIGN.items():
    if T.get(k) != v:
        bad.append(f"{k}={T.get(k)!r} is not the design's 0x{v:x}")
if S.get("S1_CMA_BASE") != 0x24A000000:
    bad.append("S1_CMA_BASE is not 0x24a000000")
if T.get("T234_RAM_SIZE") != 992 << 20:
    bad.append("T234_RAM_SIZE is not the -m992M window")

W1 = (T["T234_RAM_BASE"], T["T234_RAM_SIZE"])
W2 = (T["T234_RAM2_BASE"], T["T234_RAM2_SIZE"])
GPU = (T["T234_GPU_BASE"], T["T234_GPU_SIZE"])
SZ = T["T234_CANARY_SIZE"]
CAN = {"c1": T["T234_CANARY1_BASE"], "c2": T["T234_CANARY2_BASE"], "c3": T["T234_CANARY3_BASE"]}
BB = (T["T234_BB_BASE"], T["T234_BB_MAP"])
SHIM = (T["T234_SHIM_BASE"], T["T234_SHIM_SIZE"])
CMA = S["S1_CMA_BASE"]

def overlap(a, b):
    return a[0] < b[0] + b[1] and b[0] < a[0] + a[1]

def inside(a, w):
    return w[0] <= a[0] and a[0] + a[1] <= w[0] + w[1]

# Windows and the GPU range (§3.3): W1 below W2, W2 ending where the GPU range starts,
# the GPU range ending at CMA, below ramoops and the black box. The never-claim list of
# §2 rule 5 stays outside both windows.
if not W1[0] + W1[1] <= W2[0]:
    bad.append("window 1 does not end below window 2")
if W2[0] + W2[1] != GPU[0]:
    bad.append("window 2 does not end where the GPU range starts")
if GPU[0] + GPU[1] != CMA or not CMA < BB[0]:
    bad.append("the GPU range does not end at CMA below the black box")
for name, rng in (("0x40000000", (0x40000000, 1)), ("0xbe000000-0xc1ffffff", (0xBE000000, 0x4000000)),
                  ("cma", (CMA, 1)), ("ramoops", (0x2725F0000, 0x200000)), ("blackbox", BB)):
    for wname, w in (("w1", W1), ("w2", W2), ("gpu", GPU)):
        if overlap(rng, w):
            bad.append(f"{name} overlaps {wname}")
# Canaries: inside a window, off the GPU range, the black box and the shim page, off each
# other; none ends where another ram_list entry starts (lib/ram.c:297-299).
starts = {W1[0], W2[0]} | set(CAN.values())
for c, b in CAN.items():
    r = (b, SZ)
    if not (inside(r, W1) or inside(r, W2)):
        bad.append(f"{c} is not wholly inside window 1 or window 2")
    for oname, o in (("gpu", GPU), ("blackbox", BB), ("shim", SHIM)):
        if overlap(r, o):
            bad.append(f"{c} overlaps {oname}")
    for c2, b2 in CAN.items():
        if c2 != c and overlap(r, (b2, SZ)):
            bad.append(f"{c} overlaps {c2}")
    if b + SZ in starts:
        bad.append(f"{c} ends at 0x{b + SZ:x}, where another ram_list entry starts")
# The geometry gate keeps every image below c1 (§4.4); a --q2-limit likewise.
if not int(cap, 0) <= CAN["c1"]:
    bad.append("the geometry cap reaches canary c1")
if int(q2, 0) and not int(q2, 0) <= CAN["c1"]:
    bad.append("--q2-limit reaches canary c1")

# parse-s1.py, the contract: its constants must be the ones the images carry.
spec = importlib.util.spec_from_file_location("parse_s1", parser)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
if P.CANARIES != CAN or P.CANARY_SIZE != SZ:
    bad.append("parse-s1.py CANARIES or CANARY_SIZE differ from t234_startup.h")
if "base=0x100000000 size=0x8a000000" not in P.RX["ram_w2"].pattern:
    bad.append("parse-s1.py's ram w2 token is not window 2")
if "base=0x18a000000 size=0xc0000000" not in P.RX["gpu_range"].pattern:
    bad.append("parse-s1.py's gpu range token is not the GPU range")
if " ".join(P.ITEM5_FIELDS) != item5:
    bad.append("parse-s1.py ITEM5_FIELDS differ from the generator's list")
g = [int(x) for x in gates.split(",")]
want = [P.MEM_GATE_MIB[k] for k in (("tcg", "dryrun"), ("tcg", "boot"), ("tcg", "hold"), ("tcg", "q2"),
                                    ("board", "dryrun"), ("board", "boot"), ("board", "hold"), ("board", "q2"))]
if g != want:
    bad.append(f"memory gates {g} differ from parse-s1.py's {want}")
hm_tcg, hm_board, hold_s, hb, b2, w1 = (int(x) for x in misc.split(","))
if (hm_tcg, hm_board, hold_s, hb, b2, w1) != (P.HOLD_MIB["tcg"], P.HOLD_MIB["board"], P.HOLD_SECS, P.HB_COUNT,
                                             P.B2_ALLOC_MIB, P.W1_MIB):
    bad.append("hold sizes, hold seconds, heartbeat count, B2 allocation or W1 differ from parse-s1.py")

# Revision 3 (s1-design.md 15.5 B5). The J6 hold: below windows 1 and 2 less the canaries, by
# exactly the stated margin, and within memcanary's MIB_MAX. The watcher's DRAM bound, used by
# its pte and ptr_ram classes: T234_RAM_BASE + 8 GiB. It sits in memcanary.c's MEMCANARY_WATCH
# block as S1_DRAM_END (or _LIMIT or _TOP, exclusive), or S1_DRAM_SIZE with an optional
# S1_DRAM_BASE, each on its own line in the S1_* form; checked whenever that block exists, and
# required when s1-j1 or j1 is named.
j1_hold, j1_margin, want_j1 = (int(x) for x in j1.split(","))
mc_text = open(mc, encoding="latin-1").read()
w_sysram = (W1[1] + W2[1] - len(CAN) * SZ) >> 20
if not 0 < j1_hold < w_sysram:
    bad.append(f"J1_HOLD_MIB={j1_hold} is not below windows 1 and 2 less the canaries ({w_sysram} MiB)")
if j1_hold + j1_margin != w_sysram:
    bad.append(f"J1_HOLD_MIB={j1_hold} plus J1_HOLD_MARGIN_MIB={j1_margin} is not {w_sysram} MiB")
m = re.search(r"^#define\s+MIB_MAX\s+(\d+)[uU]?\b", mc_text, re.M)
if m is None or j1_hold > int(m.group(1)):
    bad.append("J1_HOLD_MIB is above memcanary.c's MIB_MAX, or MIB_MAX is missing")
if hasattr(P, "J1_HOLD_MIB") and P.J1_HOLD_MIB != j1_hold:
    bad.append(f"parse-s1.py J1_HOLD_MIB={P.J1_HOLD_MIB} differs from the generator's {j1_hold}")
dram_end = T["T234_RAM_BASE"] + (8 << 30)
watch = "MEMCANARY_WATCH" in mc_text
if watch:
    dram = {k: v for k, v in S.items() if k.startswith("S1_DRAM_")}
    ends = [v for k, v in dram.items() if k in ("S1_DRAM_END", "S1_DRAM_LIMIT", "S1_DRAM_TOP")]
    if "S1_DRAM_BASE" in dram and dram["S1_DRAM_BASE"] != T["T234_RAM_BASE"]:
        bad.append(f"memcanary.c S1_DRAM_BASE=0x{dram['S1_DRAM_BASE']:x} is not T234_RAM_BASE")
    if "S1_DRAM_SIZE" in dram:
        ends.append(dram.get("S1_DRAM_BASE", T["T234_RAM_BASE"]) + dram["S1_DRAM_SIZE"])
    if not ends:
        bad.append("memcanary.c has a MEMCANARY_WATCH block but no S1_DRAM_END, _LIMIT, _TOP or _SIZE define in the S1_* form")
    for e in ends:
        if e != dram_end:
            bad.append(f"memcanary.c's DRAM bound 0x{e:x} is not T234_RAM_BASE + 8 GiB (0x{dram_end:x})")
elif want_j1:
    bad.append("s1-j1 or j1 is named, but memcanary.c has no MEMCANARY_WATCH block")

if bad:
    for b in bad:
        print("   constant check: " + b)
    sys.exit(1)
print("   constant check: t234_startup.h's T234_* equal memcanary.c's S1_* and the design's values; windows,")
print("   GPU range and canaries are placed as section 3.3 says, and parse-s1.py carries the same constants: ok")
print(f"   constant check: the s1-j1 hold {j1_hold} MiB plus its {j1_margin} MiB margin is windows 1 and 2 less the"
      f" canaries, within MIB_MAX; DRAM bound {'T234_RAM_BASE + 8 GiB' if watch else 'not checked (no MEMCANARY_WATCH block)'}: ok")
PY
}

# ---- step 7: diagnostic configurations and the q2 inputs ------------------------------

diag_confs() {
	local n out
	STEP="diagnostic configurations (step 7)"
	# s1-d1 on the board (§5.3, §7.2 F18-F20): qvm's logger at debug and verbose, and every
	# unsupported class aborting. Never a pass run: s1-conf.allow rejects the unsupported lines.
	awk '{ sub(/\r$/, "") }
		$0 == "logger error,fatal,internal,warn,info stderr" { $0 = "logger error,fatal,internal,warn,info,debug,verbose stderr"; c++ }
		{ print }
		END { print "unsupported instruction abort"; print "unsupported register abort"; print "unsupported reference abort"; exit (c == 1 ? 0 : 1) }' \
		"$CONF_SRC" > "$OUT/conf/s1-d1.conf" || die "$STEP: s1-linux.conf has no single logger line to widen"
	# d1 on TCG (§3.7): the logger line only, as build-s1tcg-image.ps1 derives it.
	awk '{ sub(/\r$/, "") }
		$0 == "logger error,fatal,internal,warn,info stderr" { $0 = "logger error,fatal,internal,warn,info,debug,verbose stderr"; c++ }
		{ print }
		END { exit (c == 1 ? 0 : 1) }' \
		"$CONF_SRC" > "$OUT/conf/s1-d1-tcg.conf" || die "$STEP: s1-linux.conf has no single logger line to widen"
	# d2 on TCG (§3.5 I-c, §5.3 stage 2): rdinit=/bin/sh; the stock L4T initrd is staged
	# under the pinned initrd's name, so the initrd line stays (build-s1tcg-image.ps1's d2).
	awk '{ sub(/\r$/, "") }
		/^cmdline "/ { if (sub(/ rdinit=\/init /, " rdinit=/bin/sh ")) c++ }
		{ print }
		END { exit (c == 1 ? 0 : 1) }' \
		"$CONF_SRC" > "$OUT/conf/s1-d2.conf" || die "$STEP: s1-linux.conf has no single rdinit=/init to replace"
	n=$(diff "$CONF_SRC" "$OUT/conf/s1-d1.conf" | grep -c '^[<>]' || true)
	[ "$n" = 5 ] || die "$STEP: s1-d1.conf differs from s1-linux.conf in $n diff lines, expected 5 (one logger line changed, three added)"
	n=$(diff "$CONF_SRC" "$OUT/conf/s1-d1-tcg.conf" | grep -c '^[<>]' || true)
	[ "$n" = 2 ] || die "$STEP: s1-d1-tcg.conf differs from s1-linux.conf in $n diff lines, expected 2 (the logger line changed)"
	n=$(diff "$CONF_SRC" "$OUT/conf/s1-d2.conf" | grep -c '^[<>]' || true)
	[ "$n" = 2 ] || die "$STEP: s1-d2.conf differs from s1-linux.conf in $n diff lines, expected 2 (the cmdline changed)"
	timeout 120 "$PY_BIN" "$PARSER" conf "$OUT/conf/s1-d1-tcg.conf" > "$GATE/d1-tcg.gate" 2>&1 \
		|| { cat "$GATE/d1-tcg.gate" >&2; die "$STEP: s1-d1-tcg.conf does not pass the gate"; }
	out="$(timeout 120 "$PY_BIN" "$PARSER" conf "$OUT/conf/s1-d1.conf" 2>&1 || true)"
	[ "$(grep -c 'reject line=.* reason=keyword-not-allowed word=unsupported$' <<< "$out" || true)" = 3 ] \
		&& grep -q 'gate=fail rejects=3 allow_errors=0' <<< "$out" \
		|| { printf '%s\n' "$out" >&2; die "$STEP: s1-d1.conf must fail the gate on its three unsupported lines and nothing else"; }
	out="$(timeout 120 "$PY_BIN" "$PARSER" conf "$OUT/conf/s1-d2.conf" 2>&1)" \
		|| { printf '%s\n' "$out" >&2; die "$STEP: s1-d2.conf does not pass the gate"; }
	# s1-d1 keeps the pinned cmdline; s1-d2's, with rdinit=/bin/sh, is read from the gate's line.
	D2_CMDLINE_SHA=$(awk -F= '/^S1CONF cmdline_sha256=/ { print $2 }' <<< "$out")
	[[ "$D2_CMDLINE_SHA" =~ ^[0-9a-f]{64}$ ]] && [ "$D2_CMDLINE_SHA" != "$PIN_CMDLINE" ] \
		|| die "$STEP: could not read s1-d2.conf's cmdline_sha256"
	echo "   $STEP: s1-d1.conf (board: logger widened, unsupported abort; fails the gate on those lines only),"
	echo "   s1-d1-tcg.conf (logger widened) and s1-d2.conf (rdinit=/bin/sh), both passing the gate, derived from the pinned configuration: ok"
}

expand_printf() {
	awk '
		{ sub(/\r$/, "") }
		index($0, "printf '\''system mkqnximage-guest") == 1 {
			found++
			s = substr($0, length("printf '\''") + 1)
			k = index(s, "'\''")
			if (k == 0) { bad = "no closing quote"; next }
			s = substr(s, 1, k - 1)
			o = ""
			while ((k = index(s, "\\n")) > 0) {
				o = o substr(s, 1, k - 1) "\n"
				s = substr(s, k + 2)
			}
			o = o s
			if (index(o, "\\") > 0) { bad = "an escape other than \\n"; next }
			text = o
		}
		END {
			if (found != 1) { printf("found %d lines beginning printf '\''system mkqnximage-guest, expected exactly 1\n", found) > "/dev/stderr"; exit 1 }
			if (bad != "")  { printf("the printf argument has %s\n", bad) > "/dev/stderr"; exit 1 }
			printf "%s", text
		}
	' "$1"
}

# s1-q2 and the q2 variant: M4's PO-D and PO-E (make-m4-images.sh:383-435).
q2_inputs() {
	local n
	STEP="q2 inputs (step 7)"
	check_pin "$GUEST_IFS" "$PIN_GUEST" "the cloud-leg guest IFS"
	check_pin "$GUEST_DISK" "$PIN_DISK" "the pristine guest disk"
	check_pin "$CLIENT" "$PIN_CLIENT" "the IPC client"
	GUEST_MD5=$(md5 "$GUEST_IFS")
	DISK_MD5=$(md5 "$GUEST_DISK")
	[ -f "$ASRUN_POST" ] || die "$STEP: no $ASRUN_POST; the QNX-generated host build tree is the as-run configuration's only source"
	expand_printf "$ASRUN_POST" > "$GATE/asrun.conf" || die "$STEP: could not take the configuration out of $ASRUN_POST"
	n=$(count_line "$GATE/asrun.conf" "load /data/hypervisor/guest/ifs.bin")
	[ "$n" = 1 ] || die "$STEP: the as-run configuration has $n 'load /data/hypervisor/guest/ifs.bin' lines, expected 1"
	awk '$0 == "load /data/hypervisor/guest/ifs.bin" { $0 = "load /proc/boot/guest-ifs.bin" } { print }' \
		"$GATE/asrun.conf" > "$GATE/asrun-native.conf"
	[ -f "$G2_SRC" ] || die "$STEP: no $G2_SRC"
	awk '{ sub(/\r$/, "") } /^[[:space:]]*(#|$)/ { next } { print }' "$G2_SRC" > "$OUT/conf/g2-m3.conf"
	cmp -s "$GATE/asrun-native.conf" "$OUT/conf/g2-m3.conf" \
		|| die "$STEP: stripped g2-m3.conf is not the as-run configuration with only its load line substituted"
	cp "$GATE/asrun.conf" "$OUT/conf/s1-g2-tcg.conf"
	echo "   $STEP: guest pair and client pinned; g2-m3.conf is the as-run text with only the load line substituted: ok"
}

# ---- step 8: bounds, generation and the checks --------------------------------------------

declare -A BT
# bounds PROFILE: the wait bound table (seconds; memory in MiB). Every figure is a
# bound, never a result (§2 rule 8). Board values follow §6.8-§6.9; TCG values are
# generous because nested TCG speed is UNKNOWN (§6.3). On TCG the exports are
# cat to the serial console, so their send bounds are 0 and unused.
bounds() {
	BT=()
	if [ "$1" = board ]; then
		BT=([PTY_T]=10 [ASINFO_K]=20 [VERIFY_K]=30 [ALLOC_K]=120 [HOSTHOLD_S]=60 [IO_K]=60 [QC_K]=10
		    [DRY_K]=60 [HASH_K]=15 [TCU_K]=5 [READER_T]=5 [LK]=240 [IR]=480 [SHELL_T]=60 [FILL_T]=60
		    [HB_S]=60 [END_T]=60 [HOLDV_T]=120 [HOLD_T]=900 [TD_TERM]=15 [TD_KILL]=5 [EOF_T]=5 [SLOG_K]=15
		    [SEND_FDT]=30 [SEND_LOG]=30 [SEND_STREAM]=60 [BANNER_T]=240 [GRACE]=90 [IPC_K]=240 [CAP]=65536)
		# J6 (§15.4.8), s1-j1 only: the watch table's bounds; the hold's fill and verify waits,
		# not B4's FILL_T and HOLDV_T because the hold is eleven times B4's; its -T, which counts
		# from its fill; and the bitmap send bound (each file is a few KiB, like the FDT).
		BT+=([J1_WA_K]=60 [J1_WB_K]=230 [J1_WC_K]=230 [J1_WD_K]=110 [J1_FILL_T]=300 [J1_HOLDV_T]=300
		     [J1_HOLD_T]=600 [J1_SEND]=30 [J1_HOLD_MIB]="$J1_HOLD_MIB")
	else
		BT=([PTY_T]=10 [ASINFO_K]=0 [VERIFY_K]=0 [ALLOC_K]=0 [HOSTHOLD_S]=0 [IO_K]=600 [QC_K]=60
		    [DRY_K]=600 [HASH_K]=120 [TCU_K]=0 [READER_T]=30 [LK]=900 [IR]=1800 [SHELL_T]=120 [FILL_T]=300
		    [HB_S]=60 [END_T]=120 [HOLDV_T]=600 [HOLD_T]=1800 [TD_TERM]=60 [TD_KILL]=30 [EOF_T]=30 [SLOG_K]=60
		    [SEND_FDT]=0 [SEND_LOG]=0 [SEND_STREAM]=0 [BANNER_T]=600 [GRACE]=90 [IPC_K]=600 [CAP]=65536)
		# No watch or large hold runs under TCG (§15.4.8): zero and unused.
		BT+=([J1_WA_K]=0 [J1_WB_K]=0 [J1_WC_K]=0 [J1_WD_K]=0 [J1_FILL_T]=0 [J1_HOLDV_T]=0
		     [J1_HOLD_T]=0 [J1_SEND]=0 [J1_HOLD_MIB]=0)
	fi
	BT[HOLD_MIB]="${HOLD_MIB_OF[$1]}"
	BT[LK_WAIT]=$(( ${BT[LK]} + 5 ))
	BT[IR_REST]=$(( ${BT[IR]} - ${BT[LK]} + 5 ))
	BT[HOLD_K]=$(( ${BT[FILL_T]} + ${BT[HOLD_T]} + ${BT[HOLDV_T]} + 60 ))
	BT[GRACE_WAIT]=$(( ${BT[GRACE]} + 10 ))
	BT[SEND_FDT_T]=$(( ${BT[SEND_FDT]} > 5 ? ${BT[SEND_FDT]} - 5 : 0 ))
	BT[SEND_LOG_T]=$(( ${BT[SEND_LOG]} > 5 ? ${BT[SEND_LOG]} - 5 : 0 ))
	BT[SEND_STREAM_T]=$(( ${BT[SEND_STREAM]} > 5 ? ${BT[SEND_STREAM]} - 5 : 0 ))
	BT[J1_HOLD_K]=$(( ${BT[J1_FILL_T]} + ${BT[J1_HOLD_T]} + ${BT[J1_HOLDV_T]} + 60 ))
	BT[J1_SEND_T]=$(( ${BT[J1_SEND]} > 5 ? ${BT[J1_SEND]} - 5 : 0 ))
	(( ${BT[IR]} > ${BT[LK]} )) || die "bound table: i_ready's bound must exceed l_kernel's"
	(( HB_COUNT * ${BT[HB_S]} == HOLD_S )) || die "bound table: $HB_COUNT heartbeats of ${BT[HB_S]} s are not the $HOLD_S s hold"
	(( ${BT[HOLD_T]} > HOLD_S + ${BT[END_T]} + 30 )) || die "bound table: memcanary hold -T ${BT[HOLD_T]} does not outlast the hold and probe 2"
	# §14.10: s1con opens hvc0's slave only after the launch, so its open wait, bounded by
	# DRY_K (qvm opens the master in the configuration pass its dryrun finished inside
	# DRY_K), is the first launch-relative wait. The timer files started at the launch hold
	# l_kernel and i_ready to LK and IR from it: the open wait must end before l_kernel's
	# timer, and no chained -t may end its wait before its timer does.
	(( ${BT[DRY_K]} < ${BT[LK]} )) || die "bound table: the hvc0 open wait (DRY_K) must end before l_kernel's timer"
	(( ${BT[LK_WAIT]} > ${BT[LK]} && ${BT[LK]} + ${BT[IR_REST]} > ${BT[IR]} )) \
		|| die "bound table: a chained -t would end its wait before the launch timer"
	# J6: each watch's bound outlasts its own -T, and the hold's -T, which starts at its fill,
	# outlasts watches c and d, so a verify=timeout means the trigger never came.
	if [ "$1" = board ]; then
		local row lab dl
		for row in $J1_WATCH_ROWS; do
			lab="${row%%:*}"
			dl="${row##*:}"
			(( ${BT[J1_W${lab^^}_K]} > dl )) \
				|| die "bound table: watch $lab's bound ${BT[J1_W${lab^^}_K]} s does not outlast its -T $dl s"
		done
		(( ${BT[J1_HOLD_T]} > ${BT[J1_WC_K]} + 5 + ${BT[J1_WD_K]} + 5 + 30 )) \
			|| die "bound table: the s1-j1 hold's -T ${BT[J1_HOLD_T]} does not outlast watches c and d after its fill"
	fi
}

# ksh_worst PROFILE MODE [DIAG]: the host script's worst case from the bound table, each
# bwait -k counted as its bound plus bwait's 5 s kill grace (bwait.c:22-28), each
# -p, -s and heartbeat as its bound. pidin and the console are not bounded and are
# not counted, as in M3 and M4. DIAG j1 is revision 3's watcher (s1-j1, TCG j1).
ksh_worst() {
	local p="$1" m="$2" diag="${3:-}" w set=0 ex
	w=$(( 2 * ${BT[PTY_T]} + 10 ))
	[ "$m" = q2 ] && w=$(( w + 2 * ${BT[PTY_T]} ))
	# TCG only: memcanary --selftest under the qvm-check bound (§6.1 step 6).
	[ "$p" = tcg ] && w=$(( w + ${BT[QC_K]} + 5 ))
	# TCG j1 only: memcanary-w --selftest under the same bound (§15.5 B8.5).
	[ "$p" = tcg ] && [ "$diag" = j1 ] && w=$(( w + ${BT[QC_K]} + 5 ))
	if [ "$p" = board ]; then
		set=$(( 3 * (${BT[VERIFY_K]} + 5) ))
		w=$(( w + ${BT[ASINFO_K]} + 5 + set ))
	fi
	ex=$(( 3 * (${BT[HASH_K]} + 5) + 2 * (${BT[TCU_K]} + 5) ))
	[ "$p" = tcg ] && ex=$(( 3 * (${BT[HASH_K]} + 5) ))
	case "$m" in
	host)
		if [ "$diag" = j1 ]; then
			# J6 (§15.4.8): watches a to d, the hold's fill and verify waits (the hold itself
			# runs in the background, as in hold mode), canaries end, and four bitmap exports.
			w=$(( w + ${BT[J1_WA_K]} + 5 + ${BT[J1_WB_K]} + 5 + ${BT[J1_FILL_T]} + ${BT[J1_WC_K]} + 5 + ${BT[J1_WD_K]} + 5 ))
			w=$(( w + ${BT[J1_HOLDV_T]} + set + 4 * (ex + ${BT[J1_SEND]}) ))
		else
			w=$(( w + ${BT[ALLOC_K]} + 5 + ${BT[HOSTHOLD_S]} + set ))
		fi
		;;
	*)
		w=$(( w + 2 * (${BT[IO_K]} + 5) + ${BT[QC_K]} + 5 + ${BT[DRY_K]} + 5 + 2 * (${BT[HASH_K]} + 5) ))
		w=$(( w + 2 * ex + ${BT[SEND_FDT]} + ${BT[SEND_LOG]} ))
		[ "$p" = board ] && w=$(( w + 10 ))
		if [ "$m" != dryrun ]; then
			# pl011's reader before the launch; then, chained from the launch, the hvc0
			# open wait (DRY_K, §14.10), l_kernel, the rest to i_ready, and shell_ok.
			w=$(( w + ${BT[READER_T]} + ${BT[DRY_K]} + ${BT[LK_WAIT]} + ${BT[IR_REST]} + ${BT[SHELL_T]} + 5 ))
			w=$(( w + 2 * ${BT[TD_TERM]} + 2 * ${BT[TD_KILL]} + 2 * ${BT[EOF_T]} + set ))
			w=$(( w + 2 * ex + 2 * ${BT[SEND_STREAM]} ))
			[ "$p" = board ] && w=$(( w + 10 ))
		fi
		[ "$m" = hold ] && w=$(( w + ${BT[FILL_T]} + HB_COUNT * ${BT[HB_S]} + ${BT[END_T]} + ${BT[HOLDV_T]} + set ))
		[ "$m" = q2 ] && w=$(( w + 5 * (${BT[IO_K]} + 5) + 10 + ${BT[READER_T]} + ${BT[BANNER_T]} + ${BT[GRACE_WAIT]} + ${BT[IPC_K]} + 5 ))
		;;
	esac
	echo $(( w + ${BT[SLOG_K]} + 5 ))
}

mode_of() {
	case "$1" in
	s1-h1|s1-j1) echo host ;;
	s1-n1|s1-d1) echo boot ;;
	s1-n2) echo hold ;;
	s1-q2) echo q2 ;;
	lin-dryrun|d1-dryrun|j1) echo dryrun ;;
	lin-boot|d1-boot|d2) echo boot ;;
	hold|q2) echo "$1" ;;
	esac
}
diag_of() {
	case "$1" in
	s1-d1|d1-dryrun|d1-boot) echo d1 ;;
	d2) echo d2 ;;
	s1-j1|j1) echo j1 ;;
	*) echo "" ;;
	esac
}
# The configuration file staged at /data/s1/s1-linux.conf in a TCG variant, and the
# initrd staged at /data/s1/initrd.cpio.gz.
tcg_conf_file() {
	case "$1" in d1) echo "$OUT/conf/s1-d1-tcg.conf" ;; d2) echo "$OUT/conf/s1-d2.conf" ;; *) echo "$CONF_SRC" ;; esac
}
tcg_initrd_file() {
	case "$1" in d2) echo "$L4T_INITRD_SRC" ;; *) echo "$INITRD_SRC" ;; esac
}

# gen_ksh PROFILE MODE DIAG RUNG GUARD OUTFILE: the host script, then its checks.
gen_ksh() {
	local prof="$1" m="$2" diag="$3" rung="$4" guard="$5" f="$6" keep pv
	# conf_file: the configuration qvm runs; base_file and initrd_file: the bytes staged at
	# /data/s1/s1-linux.conf and /data/s1/initrd.cpio.gz.
	local conf=/data/s1/s1-linux.conf conf_file="$CONF_SRC" base_file="$CONF_SRC" initrd_file="$INITRD_SRC"
	local cmd_sha="$PIN_CMDLINE" initrd_sha="$PIN_INITRD" diag_args="" extra="" l c
	case "$prof" in board) keep=BOARD ;; tcg) keep=TCG ;; esac
	case "$prof:$diag" in
	board:d1) keep="$keep DIAG"; conf=/data/s1/s1-d1.conf; conf_file="$OUT/conf/s1-d1.conf"; diag_args=" /data/s1/s1-d1.conf" ;;
	tcg:d1)   conf_file="$(tcg_conf_file d1)"; base_file="$conf_file" ;;
	tcg:d2)   conf_file="$(tcg_conf_file d2)"; base_file="$conf_file"; initrd_file="$(tcg_initrd_file d2)"
	          cmd_sha="$D2_CMDLINE_SHA"; initrd_sha="$PIN_L4T_INITRD" ;;
	board:j1|tcg:j1) keep="$keep J1" ;;
	board:) ;;
	tcg:) ;;
	*) die "gen_ksh: no $prof profile for diagnostic $diag" ;;
	esac
	[ "$m" = q2 ] && keep="$keep Q2"
	extra=" tcucat_sha256=$PIN_TCUCAT"
	if [ "$prof" = board ]; then extra="$extra cpus=4 q=el2-host A=1"; else extra="$extra smp=4 not-a-twin-leg"; fi
	[ "$m" = host ] && extra="$extra fdt=none"
	[ -n "$diag" ] && extra="$extra diag=$diag base_conf_sha256=$PIN_CONF"
	[ "$diag" = j1 ] && extra="$extra memcanary_w_sha256=$PIN_MEMCANARY_W"
	[ "$m" = q2 ] && extra="$extra guest_sha256=$PIN_GUEST disk_sha256=$PIN_DISK client_sha256=$PIN_CLIENT q2_limit=$Q2_LIMIT"
	local cpu_lines ram_line guest_set=linux hold_s=0 cfgline stripped
	cpu_lines=$(awk '{ sub(/\r$/, "") } /^cpu / { o = o (o == "" ? "" : ";") $0 } END { print o }' "$conf_file")
	ram_line=$(awk '{ sub(/\r$/, "") } /^ram / { print; exit }' "$conf_file")
	[ "$m" = host ] && guest_set=none
	[ "$m" = q2 ] && guest_set=linux,qnx
	[ "$m" = hold ] && hold_s="$HOLD_S"
	local -a kv=(
		RUNG="$rung" MODE="$m" PROFILE="$prof" CONF="$conf"
		IMAGE_PATH=/data/s1/Image INITRD_PATH=/data/s1/initrd.cpio.gz BASECONF_PATH=/data/s1/s1-linux.conf
		DIAG_MD5_ARGS="$diag_args"
		MD5_IMAGE="$(md5 "$IMAGE_SRC")" MD5_INITRD="$(md5 "$initrd_file")" MD5_BASECONF="$(md5 "$base_file")"
		MD5_CONF="$(md5 "$conf_file")"
		IMAGE_SHA256="$PIN_IMAGE" INITRD_SHA256="$initrd_sha" CONF_SHA256="$(sha "$conf_file")"
		CMDLINE_SHA256="$cmd_sha" INIT_SHA256="$PIN_INIT" S1CON_SHA256="$PIN_S1CON"
		MEMCANARY_SHA256="$PIN_MEMCANARY" STAMP_SHA256="$PIN_STAMP" BWAIT_SHA256="$PIN_BWAIT"
		CPU_LINES="$cpu_lines" RAM_LINE="$ram_line" HOLD_S="$hold_s" GUEST_SET="$guest_set"
		EXTRA_FIELDS="$extra" MEM_GATE="${MEM_GATE[$prof:$m]:-992}"
	)
	if [ "$prof" = board ]; then
		kv+=(B=/proc/boot X=/proc/boot STARTUP_SHA256="$PIN_STARTUP_S1" STARTUP_LINE="$STARTUP_WANT"
		     WINDOWS="w1=0x80000000/992M,w2=0x100000000/0x8a000000" CANARIES=c1,c2,c3
		     GPU_RANGE=0x18a000000/0xc0000000 GUARD_S="$guard")
	else
		kv+=(B=/system/bin X=/system/bin STARTUP_SHA256=tcg-profile STARTUP_LINE=tcg-profile
		     WINDOWS="tcg -m 2G" CANARIES=none GPU_RANGE=none GUARD_S=none)
	fi
	for pv in PTY_T ASINFO_K VERIFY_K ALLOC_K HOSTHOLD_S IO_K QC_K DRY_K HASH_K TCU_K READER_T LK LK_WAIT IR IR_REST \
	          SHELL_T FILL_T HB_S END_T HOLDV_T HOLD_T HOLD_K HOLD_MIB TD_TERM TD_KILL EOF_T SLOG_K SEND_FDT SEND_FDT_T \
	          SEND_LOG SEND_LOG_T SEND_STREAM SEND_STREAM_T CAP BANNER_T GRACE GRACE_WAIT IPC_K \
	          J1_WA_K J1_WB_K J1_WC_K J1_WD_K J1_FILL_T J1_HOLDV_T J1_HOLD_T J1_HOLD_K J1_HOLD_MIB J1_SEND J1_SEND_T; do
		kv+=("$pv=${BT[$pv]}")
	done
	if [ "$m" = q2 ]; then
		if [ "$prof" = board ]; then
			kv+=(GUEST_IFS=/proc/boot/guest-ifs.bin GUEST_DISK=/proc/boot/disk-qvm G2CONF=/proc/boot/g2.conf
			     CLIENT=/proc/boot/qnx-host-client G2CONF_MD5="$(md5 "$OUT/conf/g2-m3.conf")")
		else
			kv+=(GUEST_IFS=/data/hypervisor/guest/ifs.bin GUEST_DISK=/data/hypervisor/guest/disk-qvm
			     G2CONF=/system/bin/s1-g2.conf CLIENT=/data/hypervisor/qnx-host-client
			     G2CONF_MD5="$(md5 "$OUT/conf/s1-g2-tcg.conf")")
		fi
		kv+=(GUEST_MD5="$GUEST_MD5" DISK_MD5="$DISK_MD5")
	fi
	STEP="$rung: host script (step 8)"
	expand ksh "$keep" "$KSH_TEMPLATE" "$f" "${kv[@]}"
	no_markers "$f"

	# The records parse-s1.py reads (§5.1, §5.2 item 5): every item-5 field once in S1 CONFIG.
	l=$(grep -c '^say "CONFIG ' "$f" || true)
	[ "$l" = 1 ] || die "$rung: $l S1 CONFIG lines in $f, expected 1"
	cfgline=$(grep '^say "CONFIG ' "$f" || true)
	for c in $ITEM5_FIELDS; do
		# occurrences of " <field>=": the length the line loses when every one is removed
		stripped="${cfgline//" $c="/}"
		[ $(( (${#cfgline} - ${#stripped}) / (${#c} + 2) )) = 1 ] || die "$rung: S1 CONFIG in $f does not carry $c exactly once"
	done
	[[ "$cfgline" == *" conf_sha256=$(sha "$conf_file") "* ]] || die "$rung: S1 CONFIG does not carry the configuration's sha256"
	[[ "$cfgline" == *" guard_s=$guard "* ]] || die "$rung: S1 CONFIG guard_s is not $guard"
	if [ "$m" = host ]; then
		[[ "$cfgline" == *" fdt=none"* ]] || die "$rung: host mode's S1 CONFIG lacks fdt=none"
	fi
	for l in "MODE=$m" "PROFILE=$prof" "CONF=$conf" \
	         "md5ok \"\$S/md5.pre\" $(md5 "$IMAGE_SRC") image md5_pre /data/s1/Image" \
	         "md5ok \"\$S/md5.post\" $(md5 "$initrd_file") initrd md5_post /data/s1/initrd.cpio.gz" \
	         "md5ok \"\$S/md5.pre\" $(md5 "$base_file") conf md5_pre /data/s1/s1-linux.conf"; do
		[ "$(count_line "$f" "$l")" = 1 ] || die "$rung: expected exactly one line '$l' in $f"
	done
	[ "$(grep -cF -- "-ge ${MEM_GATE[$prof:$m]:-992} ]" "$f" || true)" = 1 ] || die "$rung: the memory gate line does not carry this mode's constant"
	grep -qF -- "-w 'i_ready=echo S1-SHELL-\$((40+2))-OK' -t '/dev/shmem/probe2.go=echo S1-END-\$((42+1))-OK'" "$f" \
		|| die "$rung: s1con's two probes are not the design's (§3.4)"
	if [ "$prof" = tcg ]; then
		grep -qF 'say "BEGIN name=$n bytes=$XB md5=$XM enc=base64"' "$f" || die "$rung: the TCG export frame is missing"
	else
		grep -qF -- '-m "S1 BEGIN name=$n bytes=$XB md5=$XM enc=base64"' "$f" || die "$rung: the TCU export frame is missing"
	fi
	profile_check "$f" "$prof" "$diag"

	STEP="$rung: kshcheck (step 8)"
	out="$("$PY_BIN" "$PARSER" kshcheck "$f" 2>&1)" || { printf '%s\n' "$out" >&2; die "$rung: the generated host script breaks the pipe-free rule"; }
	echo "   kshcheck $(basename "$f"): $out"
	bash -n "$f" || die "$rung: $f does not parse (bash -n)"
}

# profile_scan FILE PROFILE [DIAG] prints ok or its reasons (design §3.8, §4.2, §7.3;
# revision 3's §15.5 B5). A TCG script never calls memcanary asinfo or verify and carries
# no canary, asinfo or TCU text; a board script calls verify only with c1, c2 and c3, each
# at least once, and asinfo once. alloc only with -s 1536 on the board, and never in s1-j1;
# hold only with the profile's size, except s1-j1's own hold (trigger /dev/shmem/j1hold.go),
# which only s1-j1 may carry, once, with J1_HOLD_MIB; s1-j1 on the board also carries exactly
# one other hold, the template's B4 line, unreachable in host mode. memcanary-w only with DIAG j1: on the
# board exactly the four watch calls of J1_WATCH_ROWS, each with a compiled name, the
# bounded flags in their order, its dump at /dev/shmem/j1<label>.bin and no address; on
# TCG exactly one --selftest. The tool name is matched as a whole word, so memcanary-w is
# neither read as memcanary nor skipped as a longer word.
profile_scan() {
	local j1=0
	[ "${3:-}" = j1 ] && j1=1
	awk -v prof="$2" -v hold="${HOLD_MIB_OF[$2]}" -v alloc="$B2_ALLOC_MIB" -v j1="$j1" \
	    -v j1hold="$J1_HOLD_MIB" -v rows="$J1_WATCH_ROWS" '
		function num(s, lo, hi) { return s ~ /^[0-9]+$/ && s + 0 >= lo && s + 0 <= hi }
		# memcanary-w, whose words after the tool name are w[1] to w[nw]
		function scan_w(    i, lab) {
			if (w[1] == "--selftest") {
				if (prof != "tcg") bad = bad " line" NR ":w-selftest-in-board"
				wself++
				return
			}
			if (w[1] != "watch") { bad = bad " line" NR ":w-mode-" w[1]; return }
			if (prof != "board") { bad = bad " line" NR ":watch-in-tcg"; return }
			for (i = 2; i <= nw; i++)
				if (w[i] ~ /0[xX][0-9a-fA-F]/) { bad = bad " line" NR ":watch-address"; return }
			if (w[2] != "-n" || w[4] != "-l" || w[6] != "-i" || w[8] != "-c" || w[10] != "-T" || w[12] != "-d" ||
			    (nw > 13 && w[14] != ">")) { bad = bad " line" NR ":watch-form"; return }
			if (w[3] != "c1" && w[3] != "c2" && w[3] != "c3") { bad = bad " line" NR ":watch-name-" w[3]; return }
			lab = w[5]
			if (lab !~ /^[a-z0-9]+$/ || length(lab) > 8) { bad = bad " line" NR ":watch-label"; return }
			if (!num(w[7], 0, 60000)) { bad = bad " line" NR ":watch-interval-" w[7]; return }
			if (!num(w[9], 1, 100000)) { bad = bad " line" NR ":watch-count-" w[9]; return }
			if (!num(w[11], 1, 3600)) { bad = bad " line" NR ":watch-deadline-" w[11]; return }
			if (w[13] != "/dev/shmem/j1" lab ".bin") { bad = bad " line" NR ":watch-dump-path"; return }
			if (!(lab in want) || want[lab] != w[3] ":" w[7] ":" w[9] ":" w[11]) { bad = bad " line" NR ":watch-row-" lab; return }
			seen_w[lab]++
		}
		BEGIN {
			n = split(rows, r, " ")
			for (i = 1; i <= n; i++) { split(r[i], x, ":"); want[x[1]] = x[2] ":" x[3] ":" x[4] ":" x[5] }
		}
		{ sub(/\r$/, "") }
		/^[[:space:]]*#/ { next }
		{
			if (prof == "tcg" && (index($0, "tcu-cat") || index($0, "CANARY") || index($0, "asinfo") || index($0, "ASINFO")))
				bad = bad " line" NR ":board-only-text"
			if (!j1 && index($0, "memcanary-w"))
				bad = bad " line" NR ":memcanary-w-outside-j1"
			line = $0
			while ((k = index(line, "memcanary")) > 0) {
				nxt = substr(line, k + 9, 1)
				line = substr(line, k + 9)
				tool = "m"
				if (nxt == "-" && substr(line, 2, 1) == "w") {
					tool = "w"
					nxt = substr(line, 3, 1)
					line = substr(line, 3)
				}
				if (nxt != "\"" && nxt != " " && nxt != "\t") continue
				rest = line
				sub(/^"?[ \t]+/, "", rest)
				nw = split(rest, w, /[ \t]+/)
				if (tool == "w") {
					scan_w()
				} else if (w[1] == "verify") {
					if (prof != "board") { bad = bad " line" NR ":verify-in-tcg"; continue }
					if (w[2] != "-n" || (w[3] != "c1" && w[3] != "c2" && w[3] != "c3")) { bad = bad " line" NR ":verify-" w[2] "-" w[3]; continue }
					seen[w[3]]++
				} else if (w[1] == "asinfo") {
					if (prof != "board") { bad = bad " line" NR ":asinfo-in-tcg"; continue }
					asinfo++
				} else if (w[1] == "alloc") {
					if (prof != "board" || w[2] != "-s" || w[3] != alloc) bad = bad " line" NR ":alloc-" w[3]
					else if (j1) bad = bad " line" NR ":alloc-in-j1"
				} else if (w[1] == "hold") {
					if (w[4] == "-f" && w[5] == "/dev/shmem/j1hold.go") {
						# the s1-j1 hold (section 15.4.8)
						if (!j1 || prof != "board") bad = bad " line" NR ":hold-j1-outside-j1"
						else if (w[2] != "-s" || w[3] != j1hold) bad = bad " line" NR ":hold-j1-" w[3]
						j1holds++
					} else {
						if (w[2] != "-s" || w[3] != hold) bad = bad " line" NR ":hold-" w[3]
						holds++
					}
				} else if (w[1] == "--selftest") {
					# §6.1 step 6: the self-test runs on the TCG host only.
					if (prof != "tcg") bad = bad " line" NR ":selftest-in-board"
					selftest++
				} else {
					bad = bad " line" NR ":mode-" w[1]
				}
			}
		}
		END {
			if (prof == "board") {
				if (!seen["c1"] || !seen["c2"] || !seen["c3"]) bad = bad " verify-names-missing"
				if (asinfo != 1) bad = bad " asinfo-calls-" (asinfo + 0)
			}
			if (prof == "tcg" && selftest != 1) bad = bad " selftest-calls-" (selftest + 0)
			if (j1 && prof == "board") {
				for (lab in want) if (seen_w[lab] != 1) bad = bad " watch-rows-" lab "-" (seen_w[lab] + 0)
				if (j1holds != 1) bad = bad " j1-hold-calls-" (j1holds + 0)
				# one B4 hold line from the template, unreachable in host mode, and no other
				if (holds != 1) bad = bad " b4-hold-calls-" (holds + 0)
			}
			if (j1 && prof == "tcg" && wself != 1) bad = bad " w-selftest-calls-" (wself + 0)
			print (bad == "" ? "ok" : bad)
		}' "$1"
}

profile_check() {
	local f="$1" prof="$2" res
	STEP="$(basename "$f"): profile check (step 8)"
	res=$(profile_scan "$f" "$prof" "${3:-}")
	[ "$res" = ok ] || die "$STEP: $res"
	echo "   profile check $(basename "$f") ($prof): ok"
}

# pst_case FILE PROFILE DIAG REASON sub FROM TO | add LINE | del NEEDLE: a copy of FILE with
# one change must be refused by profile_scan with REASON among its reasons. Text reaches awk
# through ENVIRON, never -v, which would expand backslashes.
PST_N=0
pst_case() {
	local f="$1" prof="$2" diag="$3" want="$4" how="$5" inj res
	inj="$GATE/selftest/inject-$PST_N.ksh"
	case "$how" in
	sub)
		FROM="$6" TO="$7" awk '
			{ sub(/\r$/, "") }
			!done && (k = index($0, ENVIRON["FROM"])) > 0 {
				$0 = substr($0, 1, k - 1) ENVIRON["TO"] substr($0, k + length(ENVIRON["FROM"]))
				done = 1
			}
			{ print }
			END { exit (done ? 0 : 1) }' "$f" > "$inj" \
			|| die "$STEP: '$6' is not in $(basename "$f"); the self-test no longer matches the template"
		;;
	add)
		{ cat "$f"; printf '%s\n' "$6"; } > "$inj"
		;;
	del)
		NEEDLE="$6" awk '{ sub(/\r$/, "") } index($0, ENVIRON["NEEDLE"]) > 0 { c++; next } { print } END { exit (c == 1 ? 0 : 1) }' \
			"$f" > "$inj" || die "$STEP: '$6' is not on exactly one line of $(basename "$f")"
		;;
	esac
	res=$(profile_scan "$inj" "$prof" "$diag")
	case "$res" in
	*"$want"*) ;;
	*) die "$STEP: a copy of $(basename "$f") with $how '$6' was not refused as $want (the scan said: $res)" ;;
	esac
	rm -f "$inj"
	echo "   profile check on $(basename "$f") with $how '$6': refused as $want: ok"
	PST_N=$((PST_N + 1))
}

# profile_selftest (§15.5 B5): the profile check still refuses each form revision 3 forbids.
# It generates an s1-h1 host script, an s1-j1 script and the TCG j1 script under
# <out>/gate/selftest; gen_ksh runs the profile check and kshcheck on each, so the real
# scripts pass first. Then one changed copy per form must be refused by name. Nothing
# written here is an image input.
profile_selftest() {
	local d="$GATE/selftest" h1 j1 tj
	local wl='bwait -k 60 -o "$S/j1a.out" -e "$S/j1a.err" -- "$B/memcanary-w" watch -n c2 -l a -i 0 -c 100000 -T 20 -d /dev/shmem/j1a.bin > "$S/j1a.b" 2>&1'
	local sl='bwait -k 60 -o "$S/x.out" -e "$S/x.err" -- "$B/memcanary-w" --selftest > "$S/x.b" 2>&1'
	local al='bwait -k 120 -o "$S/alloc.out" -e "$S/alloc.err" -- "$B/memcanary" alloc -s 1536 > "$S/alloc.b" 2>&1'
	mkdir -p "$d"
	h1="$d/s1-h1.ksh"; j1="$d/s1-j1.ksh"; tj="$d/tcg-j1.ksh"
	bounds board
	gen_ksh board host "" s1-h1 900 "$h1"
	gen_ksh board host j1 s1-j1 900 "$j1"
	bounds tcg
	gen_ksh tcg dryrun j1 tcg-j1 none "$tj"
	STEP="profile check self-test (step 8)"
	PST_N=0
	pst_case "$j1" board j1 watch-name-c4 sub "-n c2 -l a " "-n c4 -l a "
	pst_case "$j1" board j1 watch-address sub "-n c2 -l a " "-n 0x100000000 -l a "
	pst_case "$j1" board j1 watch-dump-path sub "-d /dev/shmem/j1a.bin" "-d /tmp/j1a.bin"
	pst_case "$j1" board j1 watch-interval-60001 sub "-l b -i 1000 " "-l b -i 60001 "
	pst_case "$tj" tcg j1 watch-in-tcg add "$wl"
	pst_case "$j1" board j1 w-selftest-in-board add "$sl"
	pst_case "$h1" board "" memcanary-w-outside-j1 add "$wl"
	pst_case "$j1" board j1 "hold-j1-$((J1_HOLD_MIB - 1))" sub "hold -s $J1_HOLD_MIB -f /dev/shmem/j1hold.go" \
		"hold -s $((J1_HOLD_MIB - 1)) -f /dev/shmem/j1hold.go"
	pst_case "$j1" board j1 b4-hold-calls-2 add \
		"bwait -k 60 -o \"\$S/x.bo\" -e \"\$S/x.be\" -- \"\$B/memcanary\" hold -s ${HOLD_MIB_OF[board]} -f /dev/shmem/x.go -T 900 -o /dev/shmem/x.out > \"\$S/x.b\" 2>&1 &"
	pst_case "$j1" board j1 watch-rows-d-0 del "-n c1 -l d "
	pst_case "$j1" board j1 alloc-in-j1 add "$al"
	pst_case "$tj" tcg j1 w-selftest-calls-2 add "$sl"
	pst_case "$tj" tcg "" memcanary-w-outside-j1 add "$sl"
	echo "   profile check self-test: the generated s1-h1, s1-j1 and TCG j1 scripts pass; $PST_N changed copies refused by name: ok"
}

# bb_worst_j1 FILE (§15.5 B8.6, R22): the worst-case console text of s1-j1's host script,
# in parse-s1.py's bb_text_bytes scope (from the first S1 line; the board's export bodies
# go by tcu-cat and never reach the black box), counting every failure path as taken as
# well as its success path. Terms: the S1 CONFIG line as generated; one S1 STATE line per
# state call in the whole script, reachable in host mode or not; memcanary-w's line
# contract, at most 255 B a line (§15.4.8), for 8 lines a watch; the caps the script
# itself sets (headc 256 of each .err, 4,096 of pidin syspage=asinfo, 1,024 of slog2info);
# and two allowances (HYPOTHESIS): 160 B for one of our record lines, 512 B for a bwait
# status file shown on a failure path.
bb_worst_j1() {
	local f="$1" cfg states t
	local line_b=160 bwait_b=512 wline_b=256 err_b=256 state_b=40
	cfg=$(grep -m 1 '^say "CONFIG ' "$f" || true)
	states=$(grep -cE '^[[:space:]]*state [a-z0-9_]+$' "$f" || true)
	t=$(( ${#cfg} + 64 + states * state_b ))
	# preflight's two NOTE lines, MEM boot and end, W2 reflected, FAIL_STATE twice
	t=$(( t + 7 * line_b ))
	# S1 ASINFO or its failure path, and pidin syspage=asinfo's cap
	t=$(( t + line_b + bwait_b + err_b + 4096 ))
	# canaries start and end: each verify line, and its tool=no-output path
	t=$(( t + 2 * 3 * (line_b + line_b + bwait_b + err_b) ))
	# four watches: 9 lines at the tool's limit (8 on success, one fail line), and the failure path
	t=$(( t + 4 * (9 * wline_b + bwait_b + err_b) ))
	# the hold: its fill and verify lines, its failure path, the two wait lines
	t=$(( t + 2 * line_b + bwait_b + err_b + 2 * bwait_b ))
	# four exports: S1 EXPORT and four shown status files, and the skip path
	t=$(( t + 4 * (line_b + 4 * bwait_b + line_b + bwait_b + err_b) ))
	# slog2info's head
	t=$(( t + 1024 ))
	echo "$t"
}

kshcheck_selftest() {
	local out inj last
	STEP="kshcheck self-test (step 8)"
	out="$("$PY_BIN" "$PARSER" kshcheck --selftest 2>&1)" || { printf '%s\n' "$out" >&2; die "kshcheck --selftest failed"; }
	echo "   kshcheck --selftest: ok"
	# The checker must still see a pipe in a generated script (make-m4-images.sh:711-720).
	inj="$GATE/inject-pipe.ksh"
	last=$(awk '{ sub(/\r$/, "") } NF && $1 !~ /^#/ { n = NR } END { print n + 0 }' "$1")
	awk -v n="$last" '{ sub(/\r$/, "") } NR == n { $0 = $0 " | cat" } { print }' "$1" > "$inj"
	if out="$("$PY_BIN" "$PARSER" kshcheck "$inj" 2>&1)"; then
		rm -f "$inj"
		die "kshcheck accepted a script with a pipe appended to line $last"
	fi
	rm -f "$inj"
	grep -q "line=$last rule=1" <<< "$out" || die "kshcheck did not name line $last for the injected pipe: $out"
	echo "   kshcheck on a copy of $(basename "$1") with ' | cat' appended to line $last: rejected, naming that line: ok"
}

declare -A PARAM
# image, rung (= image) and mode are what s1-board.sh checks against its step table.
PARAM_KEYS=(image rung mode profile p b_opt diag conf conf_sha256 cmdline_sha256 image_sha256 initrd_sha256 init_sha256
	s1con_sha256 memcanary_sha256 stamp_sha256 bwait_sha256 tcucat_sha256 smpcheck_sha256 startup_sha256
	startup_line mem_gate_mib hold_mib hold_s geometry_limit bounds ksh_worst_s guard_s return_bound_s capture_s
	build_sha256 ksh_sha256 kimg_sha256 transport q2_limit)
# s1-j1 only (§15.5 B9), appended after the common keys so no other image's .params changes.
PARAM_KEYS_J1=(memcanary_w_sha256 j1_hold_mib j1_hold_t bb_worst_b)
write_params() {
	local f="$OUT/$IMAGE.params" k
	{
		echo "# $IMAGE.params: written by make-s1-images.sh ($DESIGN, C14); bounds, never results."
		for k in "${PARAM_KEYS[@]}"; do
			printf '%s=%s\n' "$k" "${PARAM[$k]:--}"
		done
		if [ "${PARAM[diag]:-}" = j1 ]; then
			for k in "${PARAM_KEYS_J1[@]}"; do
				printf '%s=%s\n' "$k" "${PARAM[$k]:--}"
			done
		fi
	} > "$f"
}
# bounds_string [DIAG]: DIAG j1 appends the J6 bounds.
bounds_string() {
	local k o="" keys="LK IR SHELL_T IO_K DRY_K HB_S END_T FILL_T HOLDV_T HOLD_T VERIFY_K SEND_FDT SEND_LOG SEND_STREAM"
	if [ "${1:-}" = j1 ]; then keys="$keys J1_WA_K J1_WB_K J1_WC_K J1_WD_K J1_FILL_T J1_HOLD_T J1_HOLDV_T J1_SEND"; fi
	for k in $keys; do
		o="$o${o:+,}$k:${BT[$k]}"
	done
	echo "$o"
}

# §6.1 step 5, board images other than s1-m1b-p6.
gen_board() {
	local img="$1" m diag build body keep conf_key l c want
	m=$(mode_of "$img")
	diag=$(diag_of "$img")
	IMAGE="$img"
	STEP="$img: bounds (step 8)"
	bounds board
	PARAM=()
	PARAM[ksh_worst_s]=$(ksh_worst board "$m" "$diag")
	# C14: guard = ceil((ksh worst + 125 + 240) / 300) x 300; return bound = guard + 300
	# (m4-design.md:1252-1267); capture = return bound + 3000, as make-m4-images.sh.
	PARAM[guard_s]=$(( ( (${PARAM[ksh_worst_s]} + 125 + 240 + 299) / 300 ) * 300 ))
	PARAM[return_bound_s]=$(( ${PARAM[guard_s]} + 300 ))
	PARAM[capture_s]=$(( ${PARAM[return_bound_s]} + 3000 ))
	(( ${PARAM[guard_s]} <= 3600 )) || die "$img: guard ${PARAM[guard_s]} s is over an hour; check the bound table"

	STEP="$img: buildfile (step 8)"
	build="$OUT/$img.build"
	body="$OUT/$img.build.body"
	keep=""
	[ "$diag" = d1 ] && keep="D1"
	[ "$diag" = j1 ] && keep="$keep J1"
	[ "$m" = q2 ] && keep="$keep Q2"
	local -a kv=(RUNG="$img" P=4 GUARD="${PARAM[guard_s]}" B_OPT="-b w2,canary" KSH="$(hostpath "$OUT/$img.ksh")"
		IMAGE="$(hostpath "$IMAGE_SRC")" INITRD="$(hostpath "$INITRD_SRC")" CONF="$(hostpath "$CONF_SRC")"
		D1CONF="$(hostpath "$OUT/conf/s1-d1.conf")")
	if [ "$m" = q2 ]; then
		kv+=(CLIENT="$(hostpath "$CLIENT")" G2CONF="$(hostpath "$OUT/conf/g2-m3.conf")"
		     GUEST_IFS="$(hostpath "$GUEST_IFS")" GUEST_DISK="$(hostpath "$GUEST_DISK")")
	else
		kv+=(CLIENT=- G2CONF=- GUEST_IFS=- GUEST_DISK=-)
	fi
	expand build "$keep" "$BUILD_TEMPLATE" "$body" "${kv[@]}"
	{
		echo "# $img - S1 $m mode$([ -n "$diag" ] && echo ", diagnostic $diag")."
		echo "# Generated from orin-native/startup/s1.build.in by make-s1-images.sh: comment"
		echo "# lines removed, prefixes resolved, markers replaced. Edit the template, never this copy."
		echo "# No image generated from this has run on the board."
		echo "# Design: $DESIGN, sections 3.9 and 4.2."
		echo
		cat "$body"
	} > "$build"
	rm -f "$body"
	no_markers "$build"
	c=$(awk -v s="startup-$BOARD" '$1 == s { c++ } END { print c + 0 }' "$build")
	[ "$c" = 1 ] || die "$img: $c startup lines in $build, expected 1"
	[ "$(count_line "$build" "$STARTUP_WANT")" = 1 ] || die "$img: expected exactly one line '$STARTUP_WANT' in $build"
	c=$(awk '/^\[\+script\] \.script = \{/ { in_s = 1; next } in_s && /^\}/ { in_s = 0 } in_s && NF { c++ } END { print c + 0 }' "$build")
	[ "$c" = 13 ] || die "$img: $c script lines in $build, expected 13"
	for l in "display_msg \"T234 S1 $img -P4: procnto up\"" \
	         "display_msg \"T234 S1 $img -P4: resetting so the log can be recovered\"" \
	         "bwait -g ${PARAM[guard_s]} &" "smpcheck -i -n 4" "ksh /proc/boot/s1-host.ksh" "shutdown -S reboot" \
	         "[+raw perms=0444] /data/s1/Image=$(hostpath "$IMAGE_SRC")" \
	         "[+raw perms=0444] /data/s1/initrd.cpio.gz=$(hostpath "$INITRD_SRC")" \
	         "[perms=0444] /data/s1/s1-linux.conf=$(hostpath "$CONF_SRC")"; do
		[ "$(count_line "$build" "$l")" = 1 ] || die "$img: expected exactly one line '$l' in $build"
	done
	want=0; [ "$diag" = d1 ] && want=1
	[ "$(grep -c 's1-d1.conf=' "$build" || true)" = "$want" ] || die "$img: s1-d1.conf is staged $([ "$want" = 1 ] && echo "not ")as it should be"
	want=0; [ "$m" = q2 ] && want=1
	[ "$(grep -c '^\[+raw perms=0444\] /proc/boot/guest-ifs.bin=' "$build" || true)" = "$want" ] \
		|| die "$img: the guest pair is $([ "$want" = 1 ] && echo "missing" || echo "present in a Linux-only image")"
	want=0; [ "$diag" = j1 ] && want=1
	[ "$(count_line "$build" "/proc/boot/memcanary-w=memcanary-w")" = "$want" ] \
		|| die "$img: memcanary-w is $([ "$want" = 1 ] && echo "not staged" || echo "staged, which only s1-j1 may be")"

	gen_ksh board "$m" "$diag" "$img" "${PARAM[guard_s]}" "$OUT/$img.ksh"
	if [ "$diag" = j1 ]; then
		STEP="$img: black-box text estimate (step 8, §15.5 B8.6)"
		PARAM[bb_worst_b]=$(bb_worst_j1 "$OUT/$img.ksh")
		(( ${PARAM[bb_worst_b]} < BB_GATE )) \
			|| die "$STEP: the worst-case console text is ${PARAM[bb_worst_b]} B, not under $BB_GATE B (R22); rebuild at -vv or cut the script's text first"
		echo "   $STEP: worst case ${PARAM[bb_worst_b]} B, under $BB_GATE B: ok"
	fi

	PARAM[image]="$img"; PARAM[rung]="$img"; PARAM[mode]="$m"; PARAM[profile]=board; PARAM[p]=4; PARAM[b_opt]="w2,canary"
	PARAM[diag]="${diag:--}"
	case "$diag" in d1) PARAM[conf]=s1-d1.conf; PARAM[conf_sha256]=$(sha "$OUT/conf/s1-d1.conf") ;;
	                *)  PARAM[conf]=s1-linux.conf; PARAM[conf_sha256]="$PIN_CONF" ;; esac
	PARAM[cmdline_sha256]="$PIN_CMDLINE"; PARAM[image_sha256]="$PIN_IMAGE"; PARAM[initrd_sha256]="$PIN_INITRD"
	PARAM[init_sha256]="$PIN_INIT"; PARAM[s1con_sha256]="$PIN_S1CON"; PARAM[memcanary_sha256]="$PIN_MEMCANARY"
	PARAM[stamp_sha256]="$PIN_STAMP"; PARAM[bwait_sha256]="$PIN_BWAIT"; PARAM[tcucat_sha256]="$PIN_TCUCAT"
	PARAM[smpcheck_sha256]="$PIN_SMPCHECK"; PARAM[startup_sha256]="$PIN_STARTUP_S1"; PARAM[startup_line]="$STARTUP_WANT"
	PARAM[mem_gate_mib]="${MEM_GATE[board:$m]}"; PARAM[hold_mib]="$([ "$m" = hold ] && echo "${BT[HOLD_MIB]}" || echo -)"
	PARAM[hold_s]="$([ "$m" = hold ] && echo "$HOLD_S" || echo 0)"
	PARAM[geometry_limit]="$([ "$m" = q2 ] && echo "$Q2_LIMIT" || printf '0x%x' "$GEOMETRY_CAP")"
	PARAM[bounds]="$(bounds_string "$diag")"; PARAM[build_sha256]="$(sha "$build")"; PARAM[ksh_sha256]="$(sha "$OUT/$img.ksh")"
	PARAM[kimg_sha256]=-; PARAM[transport]=tcu; PARAM[q2_limit]="${Q2_LIMIT:--}"
	if [ "$diag" = j1 ]; then
		PARAM[memcanary_w_sha256]="$PIN_MEMCANARY_W"; PARAM[j1_hold_mib]="$J1_HOLD_MIB"; PARAM[j1_hold_t]="${BT[J1_HOLD_T]}"
	fi
	write_params
	printf '   %-10s %-5s guard=%s return=%s capture=%s ksh_worst=%s\n' "$img" "$m" "${PARAM[guard_s]}" \
		"${PARAM[return_bound_s]}" "${PARAM[capture_s]}" "${PARAM[ksh_worst_s]}"
	printf '   %-10s build  sha256 %s\n' "" "${PARAM[build_sha256]}"
	printf '   %-10s ksh    sha256 %s\n' "" "${PARAM[ksh_sha256]}"
}

# B1 (§6.6): make-m1b-images.sh's recipe for m1b-p6 alone, into this output
# directory: PO-1, PO-2 for m2-p6, the derivation, then the pin of the buildfile
# M1b ran. Byte for byte; only MKIFS_PATH changes, to S1's startup.
gen_m1b_p6() {
	local img=s1-m1b-p6 rc=0 got f l c
	IMAGE="$img"
	STEP="$img: PO-1"
	git -C "$REPO" ls-files --error-unmatch -- orin-native/startup/m2.build.in orin-native/startup/make-m2-images.sh >/dev/null 2>&1 \
		|| die "$STEP: m2.build.in or make-m2-images.sh is not tracked"
	git -C "$REPO" diff --quiet HEAD -- orin-native/startup/m2.build.in orin-native/startup/make-m2-images.sh || rc=$?
	[ "$rc" = 0 ] || die "$STEP: m2.build.in or make-m2-images.sh differs from git HEAD (exit $rc)"
	STEP="$img: PO-2"
	awk -v n=6 -v trace=0 '
		{ sub(/\r$/, "") }
		/^[[:space:]]*##/ { next }
		/^@TRACE@/ { if (!trace) next; sub(/^@TRACE@/, "") }
		/@CPU@/ {
			for (c = 0; c < n; c++) {
				l = $0; gsub(/@CPU@/, "" c, l); gsub(/@P@/, n, l); print l
			}
			next
		}
		{ gsub(/@P@/, n); print }
	' "$M2_TEMPLATE" > "$GATE/m2-p6.build"
	got=$(sha "$GATE/m2-p6.build")
	[ "$got" = "$PIN_M2_P6_BUILD" ] || die "$STEP: m2.build.in expands to m2-p6.build sha256 $got, not the $PIN_M2_P6_BUILD M2 ran"
	echo "   $STEP m2-p6.build re-expands byte for byte (sha256 $got): ok"
	f="$SHIM/out/m1b/m1b-p6.kimg"
	if [ -e "$f" ]; then
		got=$(sha "$f" | cut -c1-24)
		[ "$got" = "$PIN_M1B_P6_KIMG24" ] || die "$img: out/m1b/m1b-p6.kimg sha256 begins $got, not the $PIN_M1B_P6_KIMG24 R2 ran"
		echo "   $img: out/m1b/m1b-p6.kimg begins $got, the kimg R2 and R2b ran (read only): ok"
	fi
	STEP="$img: derive"
	{
		echo "# m1b-p6 - R2 and R2b: six cores at EL2 with VHE."
		echo "# M2's -P6 payload under -Q enable,el2-host."
		echo "#"
		echo "# Derived from m2-p6.build"
		echo "# (sha256 $PIN_M2_P6_BUILD)"
		echo "# by make-m1b-images.sh: comments removed, -Q and the display_msg label changed,"
		echo "# nothing else. Edit the generator, never this copy."
		echo "# Per-line rationale: orin-native/startup/m2.build.in."
		echo "# No image generated from this has run on the board."
		echo "# Design: results/orin-native-port/20260909T1100Z/m1b-design.md, section 5."
	} > "$OUT/$img.build.tmp"
	awk -v board="startup-$BOARD" -v q="enable,el2-host" \
	    -v from="\"T234 M2 -P" -v to="\"T234 M1b -P" '
		{ sub(/\r$/, "") }
		/^[[:space:]]*#/ { next }
		$1 == board {
			lines++
			nq = 0
			for (i = 2; i <= NF; i++) if ($i ~ /^-Q/) nq++
			k = index($0, " -Q disable")
			rest = (k > 0) ? substr($0, k + length(" -Q disable")) : ""
			if (nq != 1 || k == 0 || (rest != "" && rest !~ /^[ \t]/)) bad++
			else $0 = substr($0, 1, k - 1) " -Q " q rest
		}
		$1 == "display_msg" {
			s = $0; o = ""
			while ((k = index(s, from)) > 0) {
				o = o substr(s, 1, k - 1) to
				s = substr(s, k + length(from))
				msgs++
			}
			$0 = o s
		}
		{ print }
		END {
			if (lines != 1) { printf("found %d %s lines, expected exactly 1\n", lines, board) > "/dev/stderr"; exit 1 }
			if (bad)        { printf("the %s line does not carry exactly one -Q, followed by disable\n", board) > "/dev/stderr"; exit 1 }
			if (msgs != 2)  { printf("made %d display_msg label replacements, expected exactly 2\n", msgs) > "/dev/stderr"; exit 1 }
		}
	' "$GATE/m2-p6.build" >> "$OUT/$img.build.tmp" || { rm -f "$OUT/$img.build.tmp"; die "$img: could not derive it (reason above)"; }
	mv -f "$OUT/$img.build.tmp" "$OUT/$img.build"
	got=$(sha "$OUT/$img.build")
	[ "$got" = "$PIN_M1B_P6_BUILD" ] || die "$img: the derived buildfile has sha256 $got, not M1b's m1b-p6.build $PIN_M1B_P6_BUILD"
	for l in "$M1B_STARTUP_WANT" "display_msg \"T234 M1b -P6: procnto up\"" \
	         "display_msg \"T234 M1b -P6: resetting so the log can be recovered\""; do
		[ "$(count_line "$OUT/$img.build" "$l")" = 1 ] || die "$img: expected exactly one line '$l'"
	done
	# Only the startup line: M2's busy workers pass smpcheck its own -b.
	c=$(awk -v s="startup-$BOARD" '$1 == s { for (i = 2; i <= NF; i++) if ($i ~ /^-b/) c++ } END { print c + 0 }' "$OUT/$img.build")
	[ "$c" = 0 ] || die "$img: the startup line carries -b"
	echo "   $img: M1b's m1b-p6.build byte for byte (sha256 $got), no -b: ok"
	PARAM=()
	PARAM[image]="$img"; PARAM[rung]="$img"; PARAM[mode]=b1; PARAM[profile]=board; PARAM[p]=6; PARAM[b_opt]=none
	PARAM[startup_sha256]="$PIN_STARTUP_S1"; PARAM[startup_line]="$M1B_STARTUP_WANT"; PARAM[smpcheck_sha256]="$PIN_SMPCHECK"
	PARAM[stamp_sha256]="$PIN_STAMP"; PARAM[tcucat_sha256]="$PIN_TCUCAT"
	PARAM[geometry_limit]="$(printf '0x%x' "$GEOMETRY_CAP")"
	# §6.12: M1b's guard (the buildfile arms none) and m3-board.sh:41's 1,200 s return bound.
	PARAM[guard_s]=none; PARAM[return_bound_s]=1200; PARAM[capture_s]=4200; PARAM[ksh_worst_s]=-
	PARAM[build_sha256]="$got"; PARAM[kimg_sha256]=-; PARAM[transport]=tcu
	write_params
}

# ---- --tcg: the TCG profile for the TCG builder --------------------------------------------

add_file() {  # DIR AREA PERMS TARGET SOURCE
	local d="$1" area="$2" perms="$3" target="$4" src="$5"
	[ -f "$src" ] || die "$STEP: no $src for $area $target"
	printf '%s %s %s %s %s\n' "$area" "$perms" "$target" "$(sha "$src")" "$(hostpath "$src")" >> "$d/files.list"
	printf '[perms=%s] %s=%s\n' "$perms" "$target" "$(hostpath "$src")" >> "$d/${area}_files.lines"
}

gen_tcg() {
	local v="$1" m diag d
	m=$(mode_of "$v")
	diag=$(diag_of "$v")
	d="$OUT/tcg/s1tcg-$v"
	mkdir -p "$d"
	rm -f "$d/files.list" "$d/system_files.lines" "$d/data_files.lines"
	STEP="tcg-$v: bounds (step 8)"
	bounds tcg
	# RUNG is build-s1tcg-image.ps1's tcg-<Variant> (lin, hold, d1, d2, q2).
	gen_ksh tcg "$m" "$diag" "tcg-${v%%-*}" none "$d/s1-host.ksh"
	STEP="tcg-$v: file lists (step 8)"
	: > "$d/files.list"; : > "$d/system_files.lines"; : > "$d/data_files.lines"
	add_file "$d" system 555 bin/s1con "$TOOLS/s1con"
	add_file "$d" system 555 bin/memcanary "$TOOLS/memcanary"
	# §15.5 B6: the watcher only in j1, so no T1-T3 files.list or lines file changes.
	if [ "$diag" = j1 ]; then
		add_file "$d" system 555 bin/memcanary-w "$TOOLS/memcanary-w"
	fi
	add_file "$d" system 555 bin/stamp "$TOOLS/stamp"
	add_file "$d" system 555 bin/bwait "$TOOLS/bwait"
	add_file "$d" system 555 bin/s1-host.ksh "$d/s1-host.ksh"
	[ "$m" = q2 ] && add_file "$d" system 444 bin/s1-g2.conf "$OUT/conf/s1-g2-tcg.conf"
	add_file "$d" data 444 s1/Image "$IMAGE_SRC"
	add_file "$d" data 444 s1/initrd.cpio.gz "$(tcg_initrd_file "$diag")"
	add_file "$d" data 444 s1/s1-linux.conf "$(tcg_conf_file "$diag")"
	{
		echo "# s1tcg.params: the S1 TCG profile's parameters (make-s1-images.sh --tcg; $DESIGN §6.2-§6.4)."
		echo "# Emulated rehearsal values, never a board image's; bounds, never results."
		echo "image=tcg-$v"
		echo "variant=$v"
		echo "profile=tcg"
		echo "mode=$m"
		echo "diag=${diag:--}"
		echo "conf=/data/s1/s1-linux.conf"
		echo "conf_src=$(basename "$(tcg_conf_file "$diag")")"
		echo "conf_sha256=$(sha "$(tcg_conf_file "$diag")")"
		echo "cmdline_sha256=$([ "$diag" = d2 ] && echo "$D2_CMDLINE_SHA" || echo "$PIN_CMDLINE")"
		echo "base_conf_sha256=$PIN_CONF"
		echo "image_sha256=$PIN_IMAGE"
		echo "initrd_sha256=$([ "$diag" = d2 ] && echo "$PIN_L4T_INITRD" || echo "$PIN_INITRD")"
		echo "init_sha256=$PIN_INIT"
		echo "s1con_sha256=$PIN_S1CON"
		echo "memcanary_sha256=$PIN_MEMCANARY"
		if [ "$diag" = j1 ]; then echo "memcanary_w_sha256=$PIN_MEMCANARY_W"; fi
		echo "stamp_sha256=$PIN_STAMP"
		echo "bwait_sha256=$PIN_BWAIT"
		echo "mem_gate_mib=${MEM_GATE[tcg:$m]}"
		echo "hold_mib=$([ "$m" = hold ] && echo "${BT[HOLD_MIB]}" || echo -)"
		echo "hold_s=$([ "$m" = hold ] && echo "$HOLD_S" || echo 0)"
		echo "qemu_smp=4"
		echo "qemu_mem=2G"
		echo "bounds=$(bounds_string)"
		echo "ksh_worst_s=$(ksh_worst tcg "$m" "$diag")"
		echo "sends=console-unbounded"
		echo "ksh_sha256=$(sha "$d/s1-host.ksh")"
		echo "files_list_sha256=$(sha "$d/files.list")"
		echo "q2_limit=${Q2_LIMIT:--}"
		echo "post_start=ksh /system/bin/s1-host.ksh"
	} > "$d/s1tcg.params"
	printf '   tcg-%-7s mode=%-6s ksh_worst=%s files=%s ksh sha256 %s\n' "$v" "$m" "$(ksh_worst tcg "$m" "$diag")" \
		"$(wc -l < "$d/files.list")" "$(sha "$d/s1-host.ksh")"
}

tracked_guard() {
	local not_ignored now rc=0 n_in n_out f
	local list="$GATE/written.list" res="$GATE/written.check"
	STEP="tracked-path guard (step 15)"
	{
		find "$OUT" -type f ! -path "$list" ! -path "$res"
		for f in t234-shim.o t234-shim.elf t234-shim.bin t234-qnx.kimg; do
			[ ! -e "$SHIM/out/$f" ] || echo "$SHIM/out/$f"
		done
	} | awk -v r="$(realpath -m -- "$REPO")/" 'index($0, r) == 1 { print substr($0, length(r) + 1); next } { print "OUTSIDE-REPO:" $0 }' > "$list"
	! grep -q '^OUTSIDE-REPO:' "$list" || die "files written outside the repository: $(grep '^OUTSIDE-REPO:' "$list")"
	git -C "$REPO" check-ignore --stdin -n -v < "$list" > "$res" || rc=$?
	[ "$rc" -le 1 ] || die "git check-ignore failed (exit $rc)"
	n_in=$(wc -l < "$list")
	n_out=$(wc -l < "$res")
	[ "$n_in" -gt 0 ] && [ "$n_in" = "$n_out" ] || die "git check-ignore answered $n_out of $n_in paths (see $res)"
	not_ignored=$(awk -F'\t' '$1 == "::" { print $2 }' "$res")
	[ -z "$not_ignored" ] || die "files written here are not git-ignored: $not_ignored"
	now="$(git -C "$REPO" status --porcelain)"
	if [ "$now" != "$STATUS_A" ]; then
		diff <(printf '%s\n' "$STATUS_A") <(printf '%s\n' "$now") >&2 || true
		die "git status --porcelain changed during this run"
	fi
	echo "   $(find "$OUT" -type f | wc -l) file(s) under $OUT, all git-ignored; git status unchanged: ok"
}

# ---- steps 9-13 ---------------------------------------------------------------------------

setup_sdp() {
	local t
	STEP="SDP environment (step 9)"
	if [ -z "${QNX_HOST:-}" ] || [ -z "${QNX_TARGET:-}" ]; then
		QNX_BASE="${QNX_BASE:-$HOME/qnx800}"
		[ -d "$QNX_BASE" ] || die "no SDP at $QNX_BASE — set QNX_BASE or source qnxsdp-env"
		local qhost="$QNX_BASE/host/win64/x86_64"
		[ -d "$qhost" ] || qhost="$QNX_BASE/host/linux/x86_64"
		if command -v cygpath >/dev/null 2>&1; then
			QNX_HOST="$(cygpath -w "$qhost")"
			QNX_TARGET="$(cygpath -w "$QNX_BASE/target/qnx")"
		else
			QNX_HOST="$qhost"
			QNX_TARGET="$QNX_BASE/target/qnx"
		fi
		export QNX_HOST QNX_TARGET
		export PATH="$PATH:$qhost/usr/bin"
		echo "== using SDP at $QNX_BASE"
	fi
	for t in mkifs dumpifs ntoaarch64-nm; do
		command -v "$t" >/dev/null || die "$t not on PATH — source qnxsdp-env or set QNX_BASE"
	done
	# S1's startup directory first and the BSP's board directory not at all, so the
	# shared M1b-M4 startup can never be the one mkifs picks.
	if command -v cygpath >/dev/null 2>&1; then
		SDP_TGT="$(cygpath -u "$QNX_TARGET")/aarch64le"
		MKIFS_PATH="$(cygpath -w "$S1_STARTUP_DIR");$(cygpath -w "$TOOLS")"
	else
		SDP_TGT="$QNX_TARGET/aarch64le"
		MKIFS_PATH="$S1_STARTUP_DIR:$TOOLS"
	fi
	export MKIFS_PATH
	echo "== MKIFS_PATH=$MKIFS_PATH"
}

check_inputs() {
	local f
	STEP="inputs (step 9)"
	[ -f "$STARTUP_BIN" ] || die "no $STARTUP_BIN"
	for f in "${TOOL_NAMES[@]}"; do
		[ -f "$TOOLS/$f" ] || die "no $TOOLS/$f — run make -C orin-native/tools in the SDP environment first"
	done
	[ -f "$SHIM/build-shim.sh" ] || die "no $SHIM/build-shim.sh"
	for f in "${SDP_FILES[@]}"; do
		[ -f "$SDP_TGT/$f" ] || die "no $SDP_TGT/$f in the SDP"
	done
	if [ "$WANT_Q2" = 1 ]; then
		for f in "${Q2_SDP_FILES[@]}"; do
			[ -f "$SDP_TGT/$f" ] || die "no $SDP_TGT/$f in the SDP"
		done
	fi
	echo "   inputs: S1's startup, ${#TOOL_NAMES[@]} tools, build-shim.sh and the SDP files present: ok"
}

# make-m1b-images.sh:514-534 on S1's startup: nm on our own linked startup only.
check_symbols() {
	local syms s c
	STEP="symbol precondition (step 9)"
	syms=$(ntoaarch64-nm "$STARTUP_BIN") || die "ntoaarch64-nm failed on $STARTUP_BIN"
	for s in t234_install_el2_vectors t234_hvt_probe; do
		c=$(printf '%s\n' "$syms" | awk -v s="$s" '$NF == s && $(NF-1) ~ /^[TtW]$/ { c++ } END { print c + 0 }')
		[ "$c" = 1 ] || die "$STARTUP_BIN defines $s $c time(s), expected 1"
	done
	c=$(printf '%s\n' "$syms" | awk '$NF == "board_init" && $(NF-1) ~ /[TtWD]/ { c++ } END { print c + 0 }')
	[ "$c" = 1 ] || die "$STARTUP_BIN defines board_init $c time(s), expected 1"
	[ -f "$STARTUP_MAP" ] || die "no link map at $STARTUP_MAP"
	if grep -q 'libstartup\.a(board_init\.o)' "$STARTUP_MAP"; then
		die "$STARTUP_MAP pulled in libstartup.a(board_init.o): the linked board_init is the library's empty one"
	fi
	echo "   symbols: t234_install_el2_vectors and t234_hvt_probe defined, one board_init and not the library's: ok"
}

size_check() {
	local build="$OUT/$IMAGE.build" limit="$1" sum=262144 unresolved="" line name src d f sz end
	STEP="$IMAGE: size check (step 10)"
	while IFS= read -r line; do
		line="${line%$'\r'}"
		line="${line#"${line%%[![:space:]]*}"}"
		case "$line" in
		''|'#'*|'[image='*|'[-'*|'[+script]'*|'[virtual='*|'}'*|'PATH='*|'display_msg'*|'procmgr_'*|'openssl-3'*) continue ;;
		'[type=link]'*) continue ;;
		esac
		line="$(printf '%s' "$line" | sed -E 's/^\[[^]]*\][[:space:]]*//')"
		case "$line" in *' '*) continue ;; esac
		name="${line%%=*}"
		src="${line#*=}"
		[ "$src" != "$line" ] || src="$name"
		case "$src" in *'{'*) continue ;; esac
		f=""
		if [ -f "$src" ]; then
			f="$src"
		elif command -v cygpath >/dev/null 2>&1 && [ -f "$(cygpath -u -- "$src" 2>/dev/null)" ]; then
			f="$(cygpath -u -- "$src")"
		else
			for d in "$S1_STARTUP_DIR" "$TOOLS" "$SDP_TGT/boot/sys" "$SDP_TGT/sbin" "$SDP_TGT/usr/sbin" "$SDP_TGT/bin" \
			         "$SDP_TGT/usr/bin" "$SDP_TGT/lib" "$SDP_TGT/usr/lib" "$SDP_TGT/lib/dll"; do
				if [ -f "$d/$src" ]; then f="$d/$src"; break; fi
			done
		fi
		if [ -z "$f" ]; then
			unresolved="$unresolved $src"
			continue
		fi
		sz=$(stat -c %s "$f")
		sum=$(( sum + sz ))
	done < "$build"
	end=$(( 0x80082fa0 + sum ))
	(( end <= limit )) || die "$IMAGE: the files the buildfile names sum to $sum B; 0x80082fa0 + that passes $(printf 0x%x "$limit")"
	printf '   size check: %d B named (262,144 B slack included), image would end near 0x%x, below 0x%x: ok\n' "$sum" "$end" "$limit"
	[ -z "$unresolved" ] || echo "   size check note: names not resolved to a host file (mkifs resolves them; the geometry step checks the real end):$unresolved"
}

build_ifs() {
	STEP="$IMAGE: mkifs (step 10)"
	rm -f "$OUT/$IMAGE.ifs" "$OUT/$IMAGE.kimg"
	if ! ( cd "$OUT" && timeout 900 mkifs -v "$IMAGE.build" "$IMAGE.ifs" ) > "$OUT/$IMAGE.mkifs.txt" 2>&1; then
		tail -n 30 "$OUT/$IMAGE.mkifs.txt" >&2
		die "$IMAGE: mkifs failed; full output in $OUT/$IMAGE.mkifs.txt"
	fi
	[ -s "$OUT/$IMAGE.ifs" ] || die "$IMAGE: mkifs exited 0 but wrote no $IMAGE.ifs"
	if [ -f "$OUT/procnto-smp-instr.sym" ]; then
		mv -f "$OUT/procnto-smp-instr.sym" "$OUT/$IMAGE.procnto-smp-instr.sym"
	fi
	echo "   mkifs: $OUT/$IMAGE.ifs ($(stat -c %s "$OUT/$IMAGE.ifs") bytes)"
}

dumpifs_list() {
	( cd "$OUT" && timeout 600 dumpifs -vv "$IMAGE.ifs" ) 2>&1 | tr -d '\r' > "$OUT/$IMAGE.dumpifs.txt" \
		|| die "$IMAGE: dumpifs failed; see $OUT/$IMAGE.dumpifs.txt"
	grep -q 'compress=0 ' "$OUT/$IMAGE.dumpifs.txt" || die "$IMAGE: image is not uncompressed (see $OUT/$IMAGE.dumpifs.txt)"
}

check_dumpifs_s1() {
	local m="$1" diag="$2" f="$OUT/$IMAGE.dumpifs.txt" s="$OUT/$IMAGE.script.txt" got name l extras
	local -a names=("${S1_IFS_NAMES[@]}") absent=("${ABSENT_NAMES[@]}") data=(Image initrd.cpio.gz s1-linux.conf)
	STEP="$IMAGE: dumpifs (step 10)"
	dumpifs_list
	if [ "$m" = q2 ]; then names+=("${Q2_NAMES[@]}"); else absent+=("${Q2_NAMES[@]}"); fi
	# §15.5 B5: memcanary-w only in s1-j1.
	if [ "$diag" = j1 ]; then names+=(memcanary-w); else absent+=(memcanary-w); fi
	[ "$diag" = d1 ] && data+=(s1-d1.conf)
	awk '
		$4 == "proc/boot/.script" { in_s = 1; next }
		in_s && /^([0-9a-f]+|    ----)[[:space:]]/ { in_s = 0 }
		in_s {
			l = $0
			sub(/^[[:space:]]+/, "", l)
			if (l ~ /^gid=/) next
			sub(/^PATH=\/proc\/boot LD_LIBRARY_PATH=\/proc\/boot /, "", l)
			print l
		}' "$f" > "$s"
	got=$(wc -l < "$s")
	[ "$got" -eq 13 ] || die "$IMAGE: dumpifs shows $got script lines, expected 13 (see $s)"
	for l in "display_msg \"T234 S1 $IMAGE -P4: procnto up\"" \
	         "display_msg \"T234 S1 $IMAGE -P4: resetting so the log can be recovered\"" \
	         "bwait -g ${PARAM[guard_s]} &" "slogger2" "pipe" "devc-pty" "pidin info" "smpcheck -i -n 4" \
	         "ksh /proc/boot/s1-host.ksh" "smpcheck -z 3" "shutdown -S reboot"; do
		got=$(grep -cxF -- "$l" "$s" || true)
		[ "$got" = 1 ] || die "$IMAGE: dumpifs shows $got script lines '$l', expected 1 (see $s)"
	done
	for name in "${names[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 1 ] || die "$IMAGE: dumpifs lists proc/boot/$name $got time(s), expected exactly 1 (see $f)"
	done
	for name in "${absent[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 0 ] || die "$IMAGE: dumpifs lists proc/boot/$name, which this image may not carry (see $f)"
	done
	for name in "${data[@]}"; do
		got=$(awk -v w="data/s1/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 1 ] || die "$IMAGE: dumpifs lists data/s1/$name $got time(s), expected exactly 1 (see $f)"
	done
	got=$(awk -v list="${data[*]}" '
		BEGIN { n = split(list, a, " "); for (i = 1; i <= n; i++) want["data/s1/" a[i]] = 1 }
		$4 ~ /^data\/s1\/./ && !($4 in want) { c++ } END { print c + 0 }' "$f")
	[ "$got" = 0 ] || die "$IMAGE: dumpifs lists $got data/s1 entries beyond ${data[*]} (see $f)"
	got=$(awk '$4 == "usr/lib/ldqnx-64.so.2" && $5 == "->" { c++ } END { print c + 0 }' "$f")
	[ "$got" = 1 ] || die "$IMAGE: dumpifs lists the usr/lib/ldqnx-64.so.2 link $got time(s), expected 1 (see $f)"
	got=$(awk '$4 ~ /\.sym$/ { c++ } END { print c + 0 }' "$f")
	[ "$got" = 0 ] || die "$IMAGE: dumpifs lists $got .sym file(s) inside the image (see $f)"
	extras=$(awk -v list="${names[*]}" '
		BEGIN { n = split(list, a, " "); for (i = 1; i <= n; i++) want["proc/boot/" a[i]] = 1 }
		$4 ~ /^proc\/boot\// && !($4 in want) { printf("%s ", $4) }' "$f")
	echo "   dumpifs: uncompressed; 13 script lines with 'T234 S1 $IMAGE -P4' and bwait -g ${PARAM[guard_s]} &; ${#names[@]} names and ${#data[@]} data/s1 files once each; ${#absent[@]} excluded names and .sym absent: ok"
	[ -z "$extras" ] || echo "   dumpifs note: entries beyond the list (not an error): $extras"
}

# make-m1b-images.sh:558-588 for m1b-p6.
check_dumpifs_m1b() {
	local f="$OUT/$IMAGE.dumpifs.txt" got l
	STEP="$IMAGE: dumpifs (step 10)"
	dumpifs_list
	got=$(grep -cE -- "[[:space:]]smpcheck -i -n 6\$" "$f" || true)
	[ "$got" = 1 ] || die "$IMAGE: dumpifs shows $got census lines for -n 6 (see $f)"
	got=$(grep -cE -- '[[:space:]]smpcheck -b 60 -C [0-9]+ -o /dev/shmem/m2c[0-9]+ &$' "$f" || true)
	[ "$got" = 6 ] || die "$IMAGE: dumpifs shows $got busy workers, expected 6 (see $f)"
	for l in tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1 s1con memcanary s1-host.ksh; do
		got=$(grep -cE -- "[[:space:]]proc/boot/$l\$" "$f" || true)
		[ "$got" = 0 ] || die "$IMAGE: dumpifs lists proc/boot/$l $got time(s); m1b-p6 carries none (see $f)"
	done
	got=$(grep -cE -- '^[[:space:]]+display_msg "T234 M1b -P6: ' "$f" || true)
	[ "$got" = 2 ] || die "$IMAGE: dumpifs shows $got display_msg lines labelled 'T234 M1b -P6', expected 2 (see $f)"
	echo "   dumpifs: uncompressed, census -n 6, 6 busy workers, no trace or S1 files, both display_msg lines 'T234 M1b -P6': ok"
}

check_geometry() {
	local limit="$1" f="$OUT/$IMAGE.dumpifs.txt" v ip ss end
	STEP="$IMAGE: geometry (step 10)"
	v=$(awk '
		{
			for (i = 1; i <= NF; i++) {
				if ($i ~ /^image_paddr=/)  ip = substr($i, 13)
				if ($i ~ /^stored_size=/)  ss = substr($i, 13)
				if ($i ~ /^startup_size=/) su = substr($i, 14)
				if ($i ~ /^preboot_size=/) pb = substr($i, 14)
			}
		}
		END { print ip, ss, su, pb }' "$f")
	# shellcheck disable=SC2086
	set -- $v
	[ "$#" = 4 ] || die "$IMAGE: could not read image_paddr, stored_size, startup_size and preboot_size from $f"
	ip="$1"; ss="$2"; STARTUP_SIZE=$(( $3 )); PREBOOT=$(( $4 ))
	# M3 and M4 read 0x80082fa0 exactly; S1's startup is a different build, so the page is checked.
	(( ip >= 0x80082000 && ip < 0x80083000 )) || die "$IMAGE: image_paddr=$ip is not in the page at 0x80082000 (see $f)"
	end=$(( ip + ss ))
	(( end <= limit )) || die "$IMAGE: the image ends at $(printf 0x%x "$end"), beyond $(printf 0x%x "$limit")"
	(( end <= CANARY_C1_BASE )) || die "$IMAGE: the image ends at $(printf 0x%x "$end"), beyond canary c1"
	printf '   geometry: image_paddr=%s stored_size=%s, ends at 0x%x, below 0x%x and canary c1: ok\n' "$ip" "$ss" "$end" "$limit"
}

check_startup_args() {
	local n="$1" q="$2" wa="$3" wb="$4" line limit
	STEP="$IMAGE: startup-argument check (step 11)"
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$OUT/$IMAGE.build")
	limit=$(( PREBOOT + STARTUP_SIZE ))
	( cd "$OUT" && timeout 120 "$PY_BIN" - "$IMAGE.ifs" "$n" "$q" "$wa" "$wb" "$line" "$limit" <<'PY'
import sys

path, n, q = sys.argv[1], int(sys.argv[2]), sys.argv[3]
want_a, want_b, line, limit = sys.argv[4] == "1", sys.argv[5], sys.argv[6], int(sys.argv[7])
want = line.split()
name = want[0].encode("ascii")
nul = bytes([0])
with open(path, "rb") as fh:
    data = fh.read(limit)
if len(data) != limit:
    sys.exit("%s is shorter than its startup region of %d bytes" % (path, limit))

entries = []
pos = data.find(name + nul)
while pos >= 0:
    if pos >= 8:
        size = data[pos - 8] | (data[pos - 7] << 8)
        argc, envc = data[pos - 6], data[pos - 5]
        shdr = int.from_bytes(data[pos - 4:pos], "little")
        strs = data[pos:pos - 8 + size].split(nul)
        if argc >= 1 and len(strs) >= argc + envc:
            used = sum(len(s) + 1 for s in strs[:argc + envc])
            extra = 8 if shdr == 0xFFFFFFFF else 0
            if size == 8 + used + extra:
                argv = [s.decode("ascii", "replace") for s in strs[:argc]]
                entries.append((pos - 8, argc, envc, shdr, argv))
    pos = data.find(name + nul, pos + 1)

if len(entries) != 1:
    sys.exit("found %d well-formed startup argument blocks for %s in the first %d bytes of %s, expected exactly 1"
             % (len(entries), want[0], limit, path))
off, argc, envc, shdr, argv = entries[0]
print("   bootargs_entry at file offset 0x%x: argc=%d envc=%d shdr_addr=0x%08x" % (off, argc, envc, shdr))
print("   startup arguments in the IFS: " + " ".join(argv))
p_args = [x for x in argv[1:] if x.startswith("-P")]
if p_args != ["-P%d" % n]:
    sys.exit("startup -P arguments are %r, expected exactly ['-P%d']" % (p_args, n))
q_args = [x for x in argv[1:] if x.startswith("-Q")]
q_vals = [argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] == "-Q"]
if q_args != ["-Q"] or q_vals != [q]:
    sys.exit("startup -Q arguments are %r with values %r, expected exactly ['-Q'] with [%r]" % (q_args, q_vals, q))
a_args = [x for x in argv[1:] if x.startswith("-A")]
if a_args != (["-A"] if want_a else []):
    sys.exit("startup -A arguments are %r, expected %r" % (a_args, ["-A"] if want_a else []))
b_args = [x for x in argv[1:] if x.startswith("-b")]
b_vals = [argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] == "-b"]
if want_b:
    if b_args != ["-b"] or b_vals != [want_b]:
        sys.exit("startup -b arguments are %r with values %r, expected exactly ['-b'] with [%r]" % (b_args, b_vals, want_b))
elif b_args:
    sys.exit("startup carries -b arguments %r, expected none" % (b_args,))
if argv != want:
    sys.exit("startup arguments %r differ from the buildfile's %r" % (argv, want))
print("   exactly -P%d, -Q %s, %s and %s, and otherwise the buildfile's startup line: ok"
      % (n, q, "one -A" if want_a else "no -A", ("-b " + want_b) if want_b else "no -b"))
PY
	) || die "$IMAGE: the IFS does not carry the startup arguments it was built for"
}

# Step 12: every payload file and the host script, extracted by dumpifs from our own
# IFS (as the M3 and M4 generators do) and re-hashed against its pin.
check_identity() {
	local m="$1" diag="$2" x="xtr-$IMAGE" d f want got
	local -a files=(Image initrd.cpio.gz s1-linux.conf s1-host.ksh) args=()
	d="$OUT/$x"
	STEP="$IMAGE: identity inside the IFS (step 12)"
	[ "$diag" = d1 ] && files+=(s1-d1.conf)
	[ "$m" = q2 ] && files+=(guest-ifs.bin disk-qvm g2.conf)
	for f in "${files[@]}"; do args+=(-f "$f"); done
	rm -rf "$d"
	mkdir -p "$d"
	if ! ( cd "$OUT" && timeout 600 dumpifs -x -b -d "$x" "${args[@]}" "$IMAGE.ifs" ) > "$OUT/$IMAGE.extract.txt" 2>&1; then
		rm -rf "$d"
		tail -n 20 "$OUT/$IMAGE.extract.txt" >&2
		die "$IMAGE: dumpifs -x failed; see $OUT/$IMAGE.extract.txt"
	fi
	for f in "${files[@]}"; do
		case "$f" in
		Image)           want="$PIN_IMAGE" ;;
		initrd.cpio.gz)  want="$PIN_INITRD" ;;
		s1-linux.conf)   want="$PIN_CONF" ;;
		s1-host.ksh)     want=$(sha "$OUT/$IMAGE.ksh") ;;
		s1-d1.conf)      want=$(sha "$OUT/conf/s1-d1.conf") ;;
		guest-ifs.bin)   want="$PIN_GUEST" ;;
		disk-qvm)        want="$PIN_DISK" ;;
		g2.conf)         want=$(sha "$OUT/conf/g2-m3.conf") ;;
		esac
		if [ ! -f "$d/$f" ]; then
			rm -rf "$d"
			die "$IMAGE: dumpifs did not extract $f from $IMAGE.ifs (see $OUT/$IMAGE.extract.txt)"
		fi
		got=$(sha "$d/$f")
		if [ "$got" != "$want" ]; then
			rm -rf "$d"
			die "$IMAGE: $f extracted from $IMAGE.ifs has sha256 $got, expected $want"
		fi
		echo "   identity: $f extracted from the IFS, sha256 $got: ok"
	done
	rm -rf "$d"
}

wrap() {
	local isz ksz want_is
	STEP="$IMAGE: build-shim.sh jump (step 13)"
	if ! OUT_DIR="$SHIM/out" timeout 300 bash "$SHIM/build-shim.sh" jump "$OUT/$IMAGE.ifs" > "$OUT/$IMAGE.shim.txt" 2>&1; then
		tail -n 30 "$OUT/$IMAGE.shim.txt" >&2
		die "$IMAGE: build-shim.sh failed; full output in $OUT/$IMAGE.shim.txt"
	fi
	cp "$SHIM/out/t234-qnx.kimg" "$OUT/$IMAGE.kimg"
	isz=$(stat -c %s "$OUT/$IMAGE.ifs")
	ksz=$(stat -c %s "$OUT/$IMAGE.kimg")
	[ "$ksz" -eq $((isz + 8192)) ] || die "$IMAGE: $IMAGE.kimg is $ksz bytes, expected 8192 + $isz"
	tail -c +8193 "$OUT/$IMAGE.kimg" | cmp -s - "$OUT/$IMAGE.ifs" || die "$IMAGE: $IMAGE.kimg does not end with $IMAGE.ifs"
	want_is=$(printf '0x%x' $(( (8192 + isz + 4095) / 4096 * 4096 )))
	tr -d '\r' < "$OUT/$IMAGE.shim.txt" | grep -qE "^  image_size +$want_is +ok$" \
		|| die "$IMAGE: build-shim.sh's header check did not report image_size $want_is ok (see $OUT/$IMAGE.shim.txt)"
	echo "   wrapped: $OUT/$IMAGE.kimg ($ksz bytes = 8192 shim + $isz IFS), image_size $want_is page-rounded: ok"
	PARAM[kimg_sha256]="$(sha "$OUT/$IMAGE.kimg")"
	write_params
}

# Re-read an image's .params into PARAM (the build loop runs after every generation).
load_params() {
	local line key
	PARAM=()
	while IFS= read -r line || [ -n "$line" ]; do
		line="${line%$'\r'}"
		case "$line" in ''|'#'*) continue ;; esac
		key="${line%%=*}"
		PARAM[$key]="${line#*=}"
	done < "$OUT/$1.params"
}

resolved_path() {
	local p
	p=$(awk -v k=" proc/boot/$2=" '{ sub(/\r$/, ""); i = index($0, k); if (i > 0) { print substr($0, i + length(k)); exit } }' "$1")
	[ -n "$p" ] || return 0
	if command -v cygpath >/dev/null 2>&1; then cygpath -u -- "$p"; else echo "$p"; fi
}

# ---- main ------------------------------------------------------------------------------

if [ "$SELFTEST" = 1 ]; then
	echo "== S1 ($DESIGN): self-tests only"
	echo "== no PO-A, no pins, no image: the output guard, the constant check, the profile check's injections (§15.5 B5),"
	echo "   s1-j1's black-box text estimate (B8.6) and kshcheck's pipe injection"
	guard_output
	snapshot_status
	find_python
	constant_check
	profile_selftest
	STEP="black-box text estimate self-test (§15.5 B8.6)"
	BBW=$(bb_worst_j1 "$GATE/selftest/s1-j1.ksh")
	(( BBW < BB_GATE )) || die "$STEP: s1-j1's worst-case console text is $BBW B, not under $BB_GATE B"
	echo "   $STEP: s1-j1's worst case $BBW B, under $BB_GATE B: ok"
	kshcheck_selftest "$GATE/selftest/s1-j1.ksh"
	tracked_guard
	echo "== done: every self-test passed; the scripts under $GATE/selftest are test copies, never image inputs"
	exit 0
fi

echo "== S1 ($DESIGN): $([ "$TCG" = 1 ] && echo "TCG profile" || echo "board images"): ${NAMES[*]}"
echo "== guards, pins and gates (steps 1-7)"
guard_output
snapshot_status
find_python
po_a
pins_payload
pins_tools
conf_gate
constant_check
diag_confs
[ "$WANT_Q2" = 1 ] && q2_inputs

if [ "$TCG" = 1 ]; then
	echo "== TCG profile into $OUT/tcg (step 8)"
	FIRST=""
	for v in "${NAMES[@]}"; do
		gen_tcg "$v"
		[ -n "$FIRST" ] || FIRST="$OUT/tcg/s1tcg-$v/s1-host.ksh"
	done
	profile_selftest
	kshcheck_selftest "$FIRST"
	tracked_guard
	echo "== done: the TCG builder reads $OUT/tcg/s1tcg-<variant>/ (s1-host.ksh, s1tcg.params, files.list, *_files.lines)"
	exit 0
fi

pins_startup
echo "== verbatim ranges (step 8)"
STEP="verbatim ranges (step 8)"
sed -n '95,128p' "$M3_BUILD_TEMPLATE" > "$GATE/m3-95-128.txt"
sed -n '148,173p' "$M3_BUILD_TEMPLATE" > "$GATE/m3-148-173.txt"
[ "$(wc -l < "$GATE/m3-95-128.txt")" -eq 34 ] && [ "$(wc -l < "$GATE/m3-148-173.txt")" -eq 26 ] \
	|| die "m3.build.in no longer has lines 95-128 and 148-173"
head -n 1 "$GATE/m3-95-128.txt" | grep -qx 'libc.so.6' && tail -n 1 "$GATE/m3-148-173.txt" | grep -qx '\[type=link\] wc=toybox' \
	|| die "m3.build.in:95 is not libc.so.6 or :173 is not the wc link; the verbatim ranges moved"
sed 's/^@Q2@//' "$BUILD_TEMPLATE" > "$GATE/s1.build.q2view"
[ "$(block_matches "$GATE/m3-95-128.txt" "$GATE/s1.build.q2view")" = 1 ] \
	|| die "s1.build.in with @Q2@ removed does not carry m3.build.in:95-128 verbatim exactly once"
[ "$(block_matches "$GATE/m3-148-173.txt" "$GATE/s1.build.q2view")" = 1 ] \
	|| die "s1.build.in with @Q2@ removed does not carry m3.build.in:148-173 verbatim exactly once"
Q2N=$(grep -c '^@Q2@' "$BUILD_TEMPLATE" || true)
[ "$Q2N" = 9 ] || die "s1.build.in has $Q2N @Q2@ lines, expected 9"
echo "   m3.build.in:95-128 and :148-173 found once each in s1.build.in with its 9 @Q2@ prefixes removed: ok"

echo "== generating into $OUT (step 8)"
FIRST=""
for img in "${NAMES[@]}"; do
	case "$img" in
	s1-m1b-p6) gen_m1b_p6 ;;
	*)
		gen_board "$img"
		[ -n "$FIRST" ] || FIRST="$OUT/$img.ksh"
		;;
	esac
done
[ -z "$FIRST" ] || kshcheck_selftest "$FIRST"
profile_selftest

if [ "$GEN_ONLY" = 1 ]; then
	tracked_guard
	echo "== --generate-only: stopping before mkifs; no image was built"
	exit 0
fi

setup_sdp
check_inputs
declare -A SUM_A
STEP="inputs (step 9)"
SUM_A[startup]=$(sha "$STARTUP_BIN")
for t in "${TOOL_NAMES[@]}"; do SUM_A[$t]=$(sha "$TOOLS/$t"); done
[ "${SUM_A[startup]}" = "$PIN_STARTUP_S1" ] || die "$STARTUP_BIN changed after step 4"
check_symbols

for img in "${NAMES[@]}"; do
	IMAGE="$img"
	echo "== $img"
	load_params "$img"
	case "$img" in
	s1-m1b-p6)
		size_check "$GEOMETRY_CAP"
		build_ifs
		check_dumpifs_m1b
		check_geometry "$GEOMETRY_CAP"
		check_startup_args 6 enable,el2-host 0 ""
		wrap
		;;
	*)
		m=$(mode_of "$img")
		diag=$(diag_of "$img")
		limit=$GEOMETRY_CAP
		[ "$m" = q2 ] && limit=$Q2_LIMIT
		size_check "$limit"
		build_ifs
		check_dumpifs_s1 "$m" "$diag"
		check_geometry "$limit"
		check_startup_args 4 enable,el2-host 1 w2,canary
		check_identity "$m" "$diag"
		wrap
		;;
	esac
done

STEP="input stability (step 14)"
[ "$(sha "$STARTUP_BIN")" = "${SUM_A[startup]}" ] || die "$STARTUP_BIN changed during this run; rebuild the images"
for t in "${TOOL_NAMES[@]}"; do
	[ "$(sha "$TOOLS/$t")" = "${SUM_A[$t]}" ] || die "$TOOLS/$t changed during this run; rebuild the images"
done
for f in "$IMAGE_SRC:$PIN_IMAGE" "$INITRD_SRC:$PIN_INITRD" "$CONF_SRC:$PIN_CONF"; do
	[ "$(sha "${f%:*}")" = "${f##*:}" ] || die "${f%:*} changed during this run; rebuild the images"
done
echo "   S1's startup, ${#TOOL_NAMES[@]} tools, the Image, the initrd and the configuration unchanged during the run: ok"

tracked_guard

STEP="sha256 table (step 16)"
echo
echo "== sha256 (the kimg is what goes to the board; sha256sum it there before kexec)"
row() { printf '%-10s %-24s %10s  %s\n' "$@"; }
row kind file bytes sha256
for img in "${NAMES[@]}"; do
	for f in "$img.kimg" "$img.ifs" "$img.build" "$img.params"; do
		row generated "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
	done
	[ ! -f "$OUT/$img.ksh" ] || row generated "$img.ksh" "$(stat -c %s "$OUT/$img.ksh")" "$(sha "$OUT/$img.ksh")"
done
row input "startup-$BOARD (S1)" "$(stat -c %s "$STARTUP_BIN")" "${SUM_A[startup]}"
for t in "${TOOL_NAMES[@]}"; do row input "$t" "$(stat -c %s "$TOOLS/$t")" "${SUM_A[$t]}"; done
row payload Image "$(stat -c %s "$IMAGE_SRC")" "$PIN_IMAGE"
row payload initrd.cpio.gz "$(stat -c %s "$INITRD_SRC")" "$PIN_INITRD"
row payload s1-linux.conf "$(stat -c %s "$CONF_SRC")" "$PIN_CONF"
for img in "${NAMES[@]}"; do
	[ "$img" != s1-m1b-p6 ] || continue
	for name in "${HASHED_NAMES[@]}"; do
		hp=$(resolved_path "$OUT/$img.mkifs.txt" "$name")
		[ -n "$hp" ] && [ -f "$hp" ] || die "cannot find the host file mkifs used for $name in $OUT/$img.mkifs.txt"
		row sdp "$name" "$(stat -c %s "$hp")" "$(sha "$hp")"
	done
	break
done
for img in "${NAMES[@]}"; do
	echo
	echo "== $img.params"
	sed 's/^/   /' "$OUT/$img.params"
done
echo "== done: ${#NAMES[@]} image(s) in $OUT"
echo "   s1-board.sh reads <image>.kimg and <image>.params from S1_KIMG_DIR (default orin-native/shim/out/s1): S1_KIMG_DIR=$OUT"
