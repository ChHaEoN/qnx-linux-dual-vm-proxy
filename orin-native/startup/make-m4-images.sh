#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# make-m4-images.sh — generate, build, check and wrap one M4 image.
#
# Phase 3b, the M4 design's §3.4 (results/orin-native-port/20260909T1100Z/
# m4-design.md, revision 2), with the implementation notes of its §14.
# Compile-only: nothing here talks to the board, and no image it builds has run
# there. A copy of make-m3-images.sh with the design's changes; that generator
# is not edited.
#
#   BSP=/path/to/extracted/BSP QNX_BASE=/path/to/qnx800 \
#       ./make-m4-images.sh [--generate-only] m4-r0
#   BSP=... QNX_BASE=... ./make-m4-images.sh [--generate-only] m4-r1 --from-size <size file>
#   BSP=... QNX_BASE=... ./make-m4-images.sh [--generate-only] m4-r2 --from-size <size file>
#
#   rung  mode   trace                               iterations  blocks (design §3.3)
#   r0    trace  probe -r -k 64; L0 linear -s 10     -           v 262,144
#   r1    full   -r -k K1 (size-r1) or -c (lin)      15          v, c
#   r2    full   -r -k K2 (size-r2) or -c (lin)      N2          c, v
#
# The image name of r1 and r2 (m4-r1-k256, m4-r2-k512-n2000, ...) comes from the
# size file that orin-native/m4/parse-m4.py size-r1 or size-r2 wrote; it is never
# typed. r1 and r2 without --from-size are refused.
#
# Steps, numbered as the design's §3.4:
#    1. output guard: out/m4 must not resolve into out/m1b, out/m2 or out/m3 and
#       must be git-ignored
#    2. snapshot of git status --porcelain
#    3. PO-A: the earlier milestones' sources match git HEAD
#    4. PO-B: the startup, smpcheck and IPC client match their pins; the other
#       tools' sha256 are recorded
#    5. PO-C: the kimgs M1b and M2 ran match their records; out/m3's kimgs are
#       hashed for the record (M4_M3_RAN_SHA256 checks m3-r2.kimg); out/m3 is
#       never written
#    6. PO-D: the guest IFS and disk match their pins; md5s for baking
#    7. PO-E: g2-m3.conf is the as-run configuration with only its load line
#       substituted
#    8. parameters: r0's fixed values, or the size file's, range-checked and
#       recomputed from §8.1 and §8.2
#    9. generate <image>.build, <image>.ksh, <image>.params and the fixtures;
#       no marker; the verbatim ranges; the script block; kshcheck self-test,
#       the generated script, and an injected pipe; bash -n
#   --generate-only stops here (after the step-19 guard) and needs no SDP.
#   10. SDP environment and inputs
#   11. the size check before mkifs
#   12. mkifs
#   13. dumpifs -vv: the script, every listed name once, the absent names absent
#   14. geometry
#   15. startup arguments baked into the IFS
#   16. byte identity of the guest pair, configuration, host script and fixtures
#   17. build-shim.sh jump: the kimg is the 8 KiB shim page plus this IFS
#   18. the startup and every tool unchanged since step 4
#   19. every file written is git-ignored and git status equals the snapshot
#   20. table: sizes, hashes and the .params contents
# It stops at the first failure with "FAIL: <step>".
#
# Everything lands in orin-native/shim/out/m4/, which .gitignore covers. An IFS
# and a kimg carry QNX binaries, the guest IFS and the guest disk (NCEULA), and
# so does the procnto .sym mkifs drops beside them; none of it may reach a
# tracked path. QNX files are handled as opaque bytes only.
set -Eeuo pipefail

BOARD=t234-orin-nano
HERE="$(cd "$(dirname "$0")" && pwd)"
NATIVE="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$NATIVE/.." && pwd)"
TOOLS="$NATIVE/tools"
SHIM="$NATIVE/shim"
QHVCONF="$NATIVE/qhv"
OUT="$SHIM/out/m4"
GATE="$OUT/gate"
M1B_OUT="$SHIM/out/m1b"
M2_OUT="$SHIM/out/m2"
M3_OUT="$SHIM/out/m3"
BSP="${BSP:-$HOME/orin-native-port-bsp}"
BOARD_LE="$BSP/src/hardware/startup/boards/$BOARD/aarch64/le"
STARTUP_BIN="$BOARD_LE/startup-$BOARD"
BUILD_TEMPLATE="$HERE/m4.build.in"
KSH_TEMPLATE="$HERE/m4-host.ksh.in"
M3_BUILD_TEMPLATE="$HERE/m3.build.in"
CONF_SRC="$QHVCONF/g2-m3.conf"
ASRUN_POST="$REPO/qhv/host/output/build/post_startup.sh"
GUEST_IFS="$REPO/qhv/guest/output/ifs.bin"
GUEST_DISK="$REPO/qhv/guest/output/disk-qvm"
CLIENT="$REPO/ipc-test/qnx-host-client/qnx-host-client"
FIX_SRC_DIR="$NATIVE/m4/fixtures"
PARSER="$NATIVE/m4/parse-m4.py"
DESIGN="results/orin-native-port/20260909T1100Z/m4-design.md"

# Pins, exactly as make-m3-images.sh:96-100 (design §3.4 steps 4 and 6).
PIN_STARTUP=90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896
PIN_SMPCHECK=f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0
PIN_CLIENT=52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb
PIN_GUEST=968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f
PIN_DISK=cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b

# PO-A (step 3): M3's list plus M3's own sources and the tools M4 does not revise.
PO_A_PATHS=(
	orin-native/startup/m2.build.in
	orin-native/startup/make-m2-images.sh
	orin-native/startup/make-m1b-images.sh
	orin-native/startup/t234-orin-nano
	orin-native/startup/m3.build.in
	orin-native/startup/m3-host.ksh.in
	orin-native/startup/m3-fake-guest.txt
	orin-native/startup/make-m3-images.sh
	orin-native/startup/m3-board.sh
	orin-native/qhv/g2-m3.conf
	orin-native/qhv/g2-m3-diag.conf
	orin-native/qhv/g2-noblk.conf
	orin-native/tools/stamp.c
	orin-native/tools/bwait.c
	orin-native/tools/smpcheck.c
	orin-native/tools/trcctl.c
	orin-native/tools/clkcmp.c
)

# Every /proc/boot name of design §3.1, each exactly once (step 13).
IFS_NAMES=(
	.script procnto-smp-instr ldqnx-64.so.2
	libc.so.6 libgcc_s.so.1 libsecpol.so.1 libm.so.3 libqh.so.1 libregex.so.1
	libjail.so.1 libfsnotify.so.1 libsocket.so.4 libsocket.so libfdt.so.1 libfdt.so
	libcam.so.2 io-blk.so cam-disk.so libslog2.so.1 libslog2.so libslog2parse.so.1
	libslog2shim.so.1 libjson.so.1
	libz.so.2 libcrypto.so.3 libqcrypto.so.1.0 qcrypto-openssl-3.so libpci.so.3.0 qcrypto.conf
	libtracelog.so.1 libtraceparser.so.1
	tcu-cat stamp bwait smpcheck trcctl clkcmp m4count qnx-host-client m4-host.ksh g2.conf
	m4fix-1.txt m4fix-2.txt m4fix-3.txt m4fix-4.txt guest-ifs.bin disk-qvm
	ksh pidin on slay waitfor shutdown devc-pty slogger2 slog2info pipe
	qvm qvm-check vdev-pl011.so vdev-virtio-console.so vdev-virtio-blk.so vdev-shmem.so
	devb-loopback toybox cat cp cmp grep head md5sum tail wc
	tracelogger traceprinter cksum rm
)
# Deliberately absent (design §3.1).
ABSENT_NAMES=(vpctl vdev-virtio-net.so fs-qnx6.so random io-sock gawk awk gzip base64 m3-host.ksh m3-fake-guest.txt)
# SDP files, relative to target/qnx/aarch64le; checked for presence before mkifs.
SDP_FILES=(
	sbin/qvm bin/qvm-check lib/dll/vdev-pl011.so lib/dll/vdev-virtio-console.so
	lib/dll/vdev-virtio-blk.so lib/dll/vdev-shmem.so usr/lib/libfdt.so.1
	sbin/devb-loopback lib/dll/io-blk.so lib/dll/cam-disk.so lib/libcam.so.2
	bin/slogger2 bin/slog2info lib/libslog2.so.1 lib/libslog2parse.so.1
	lib/libslog2shim.so.1 lib/libjson.so.1 sbin/pipe usr/bin/toybox lib/libm.so.3
	lib/libqh.so.1 lib/libregex.so.1 lib/libjail.so.1 lib/libfsnotify.so.1
	lib/libsocket.so.4
	usr/lib/libz.so.2 usr/lib/libcrypto.so.3 usr/lib/libqcrypto.so.1.0
	lib/dll/qcrypto-openssl-3.so lib/libpci.so.3.0
	usr/sbin/tracelogger usr/bin/traceprinter lib/libtracelog.so.1 usr/lib/libtraceparser.so.1
)
HASHED_NAMES=(qvm qvm-check vdev-pl011.so vdev-virtio-console.so vdev-virtio-blk.so vdev-shmem.so
	tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1)
TOOL_NAMES=(tcu-cat stamp smpcheck bwait trcctl clkcmp m4count)

# The .params keys, in the design's order (§3.3), and the extra key e3 (§14): r0 status0, and
# r1 and r2 none unless their size file names e3 (owner decision N15, §14.7).
PARAM_KEYS=(image rung mode p kind k s_mb tl_args tl_bound trace_need_mb fmt_need_mb cnt_need_mb iters
	ipc_bound banner_bound grace tp_bound cnt_bound hash_bound forms cap_v cap_c send_v send_c send_t_v
	send_t_c clean_pred p2_reachable p99_reachable accept_low_n ksh_worst_s guard_s return_bound_s
	capture_s size_file size_sha256 ksh_sha256 kimg_sha256 e3 transport fixtures)

STEP="argument parsing"
die() { echo "FAIL: $*" >&2; exit 1; }
trap 'echo "FAIL: $STEP (line $LINENO exited non-zero)" >&2' ERR

usage() {
	echo "usage: $0 [--generate-only] m4-r0" >&2
	echo "       $0 [--generate-only] m4-r1 --from-size <size file>" >&2
	echo "       $0 [--generate-only] m4-r2 --from-size <size file>" >&2
	exit 2
}

GEN_ONLY=0
RUNG_ARG=""
SIZE_FILE=""
while [ $# -gt 0 ]; do
	case "$1" in
	--generate-only) GEN_ONLY=1 ;;
	--from-size)
		[ $# -ge 2 ] || usage
		SIZE_FILE="$2"
		shift
		;;
	-h|--help) usage ;;
	m4-r0|m4-r1|m4-r2)
		[ -z "$RUNG_ARG" ] || usage
		RUNG_ARG="$1"
		;;
	*) echo "unknown argument: $1" >&2; usage ;;
	esac
	shift
done
[ -n "$RUNG_ARG" ] || usage
RUNG="${RUNG_ARG#m4-}"
case "$RUNG" in
r0) [ -z "$SIZE_FILE" ] || die "m4-r0 takes no --from-size: its values are fixed (design §3.3)" ;;
*)  [ -n "$SIZE_FILE" ] || die "m4-$RUNG needs --from-size <size file> from parse-m4.py size-$RUNG (design §3.4)" ;;
esac

# ---- helpers -------------------------------------------------------------------
sha() { sha256sum "$1" | cut -d' ' -f1; }
md5() { md5sum "$1" | cut -d' ' -f1; }
hostpath() {
	if command -v cygpath >/dev/null 2>&1; then cygpath -m -- "$1"; else echo "$1"; fi
}
count_line() {
	awk -v want="$2" '{ sub(/\r$/, ""); $1 = $1 } $0 == want { c++ } END { print c + 0 }' "$1"
}
strip_conf() {
	awk '{ sub(/\r$/, "") } /^[[:space:]]*(#|$)/ { next } { print }' "$1"
}
# Literal marker substitution, as make-m3-images.sh:244-274.
subst() {
	local strip="$1" in="$2" out="$3" kv i=0
	local -a envs=()
	shift 3
	for kv in "$@"; do
		envs+=("SUBST_K$i=${kv%%=*}" "SUBST_V$i=${kv#*=}")
		i=$((i + 1))
	done
	env "${envs[@]}" SUBST_N="$i" awk -v strip="$strip" '
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
		strip == "hash"  && /^[[:space:]]*#/ { next }
		strip == "notes" && /^##/ { next }
		{
			line = $0
			for (i = 0; i < n; i++) line = repl(line, "@" K[i] "@", V[i])
			print line
		}
	' "$in" > "$out"
}
no_markers() {
	local left
	left=$(grep -nE '@[A-Z0-9_]+@' "$1" || true)
	[ -z "$left" ] || die "$STEP: markers survive substitution in $1: $left"
}
# How many times the lines of file $1 occur as a contiguous block in file $2.
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
find_python() {
	local t
	PY_BIN=""
	for t in python3 python py; do
		if command -v "$t" >/dev/null 2>&1 && "$t" -c pass >/dev/null 2>&1; then
			PY_BIN="$t"
			return 0
		fi
	done
	die "no working python (make-m4-images.sh runs parse-m4.py kshcheck and the startup-argument check)"
}
ceil_div() { echo $(( ($1 + $2 - 1) / $2 )); }
ring_mb() { ceil_div $(( $1 * 64 )) 1024; }
s_of_k() { echo $(( $(ring_mb "$1") + 4 )); }

# ---- steps 1-7 --------------------------------------------------------------------

guard_output() {
	local out_r r p
	STEP="output directory (step 1)"
	out_r="$(realpath -m -- "$OUT")"
	for r in "$M1B_OUT" "$M2_OUT" "$M3_OUT"; do
		r="$(realpath -m -- "$r")"
		case "${out_r,,}/" in
		"${r,,}/"*) die "output directory $OUT resolves to $out_r, inside $r, which this script must never write" ;;
		esac
	done
	command -v git >/dev/null 2>&1 || die "git is needed for the ignore checks and PO-A"
	for p in "$OUT/x.build" "$OUT/x.ksh" "$OUT/x.ifs" "$OUT/x.kimg" "$OUT/x.params" "$OUT/x.procnto-smp-instr.sym" \
	         "$GATE/x.conf" "$OUT/xtr-x/disk-qvm" "$OUT/size-r1.size" "$OUT/m4fix-1.txt" "$OUT/g2-m3.conf" \
	         "$SHIM/out/t234-qnx.kimg"; do
		git -C "$REPO" check-ignore -q -- "$p" \
			|| die "$p would not be git-ignored; fix .gitignore before building QNX images here"
	done
	mkdir -p "$OUT" "$GATE"
	echo "   output: $OUT (git-ignored, outside out/m1b/, out/m2/ and out/m3/): ok"
}

snapshot_status() {
	STEP="git status snapshot (step 2)"
	STATUS_A="$(git -C "$REPO" status --porcelain)"
	echo "   git status --porcelain snapshot taken"
}

po_a() {
	local rc=0
	STEP="PO-A (step 3)"
	git -C "$REPO" ls-files --error-unmatch -- "${PO_A_PATHS[@]}" >/dev/null 2>&1 \
		|| die "PO-A: one of the earlier milestones' sources is not tracked by git"
	git -C "$REPO" diff --quiet HEAD -- "${PO_A_PATHS[@]}" || rc=$?
	case "$rc" in
	0) ;;
	1) die "PO-A: an earlier milestone's source differs from git HEAD (M4 adds files and never edits these; design §3.5)" ;;
	*) die "PO-A: git diff failed (exit $rc)" ;;
	esac
	echo "   PO-A ${#PO_A_PATHS[@]} earlier sources (M1b, M2, M3 and the unrevised tools) match git HEAD: ok"
}

check_pin() {
	local got
	[ -f "$1" ] || die "$STEP: no $1 ($3)"
	got=$(sha "$1")
	[ "$got" = "$2" ] || die "$STEP: $1 has sha256 $got, but $3 is pinned at $2"
	echo "   $STEP: $3, sha256 $got: ok"
}

po_b() {
	local f
	STEP="PO-B (step 4)"
	[ -f "$STARTUP_BIN" ] || die "PO-B: no $STARTUP_BIN; set BSP="
	check_pin "$STARTUP_BIN" "$PIN_STARTUP" "the M1b startup build"
	check_pin "$TOOLS/smpcheck" "$PIN_SMPCHECK" "M1b's smpcheck"
	check_pin "$CLIENT" "$PIN_CLIENT" "the IPC client"
	for f in tcu-cat stamp bwait trcctl clkcmp m4count; do
		if [ -f "$TOOLS/$f" ]; then
			echo "   PO-B $f: sha256 $(sha "$TOOLS/$f") (recorded)"
		else
			echo "   PO-B $f: not built yet (make -C orin-native/tools); needed before mkifs"
		fi
	done
}

po_c_pin() {
	case "$1" in
	out/m1b/reg-p6.kimg) echo c391551a8e4b16bbc6f0e626 ;;
	out/m1b/m1b-p1.kimg) echo cf0715ef7f0e447228d33655 ;;
	out/m1b/m1b-p6.kimg) echo 85970fe84cb5ed644e2cced6 ;;
	out/m2/m2-p6.kimg)   echo 5cae65e821edcdb9c2355310 ;;
	*) die "no PO-C pin for $1" ;;
	esac
}
po_c() {
	local rel f got want
	STEP="PO-C (step 5)"
	for rel in out/m1b/reg-p6.kimg out/m1b/m1b-p1.kimg out/m1b/m1b-p6.kimg out/m2/m2-p6.kimg; do
		f="$SHIM/$rel"
		if [ ! -e "$f" ]; then
			echo "   PO-C $rel: absent, not checked"
			continue
		fi
		got=$(sha "$f" | cut -c1-24)
		want=$(po_c_pin "$rel")
		[ "$got" = "$want" ] \
			|| die "PO-C: $f sha256 begins $got, but the run record says $want; something rebuilt an earlier milestone's image"
		echo "   PO-C $rel sha256 begins $got, the image that milestone ran: ok"
	done
	if [ -d "$M3_OUT" ]; then
		for f in "$M3_OUT"/*.kimg; do
			[ -e "$f" ] || continue
			echo "   PO-C out/m3/$(basename "$f") sha256 $(sha "$f") (for the record; out/m3 is never written)"
		done
	fi
	if [ -n "${M4_M3_RAN_SHA256:-}" ]; then
		[ -f "$M3_OUT/m3-r2.kimg" ] || die "PO-C: M4_M3_RAN_SHA256 is set but out/m3/m3-r2.kimg is absent"
		got=$(sha "$M3_OUT/m3-r2.kimg")
		[ "$got" = "$M4_M3_RAN_SHA256" ] || die "PO-C: out/m3/m3-r2.kimg sha256 $got is not the kimg M3's T-runs ran"
		echo "   PO-C out/m3/m3-r2.kimg equals M4_M3_RAN_SHA256: ok"
	fi
}

po_d() {
	STEP="PO-D (step 6)"
	check_pin "$GUEST_IFS" "$PIN_GUEST" "the cloud-leg guest IFS"
	check_pin "$GUEST_DISK" "$PIN_DISK" "the pristine guest disk"
	GUEST_MD5=$(md5 "$GUEST_IFS")
	DISK_MD5=$(md5 "$GUEST_DISK")
	echo "   PO-D md5 for baking: guest $GUEST_MD5, disk $DISK_MD5"
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

po_e() {
	local n
	STEP="PO-E (step 7)"
	[ -f "$ASRUN_POST" ] || die "PO-E: no $ASRUN_POST; the QNX-generated host build tree is the as-run configuration's only source"
	expand_printf "$ASRUN_POST" > "$GATE/asrun.conf" \
		|| die "PO-E: could not take the configuration out of $ASRUN_POST (reason above)"
	n=$(count_line "$GATE/asrun.conf" "load /data/hypervisor/guest/ifs.bin")
	[ "$n" = 1 ] || die "PO-E: the as-run configuration has $n 'load /data/hypervisor/guest/ifs.bin' lines, expected exactly 1"
	awk '$0 == "load /data/hypervisor/guest/ifs.bin" { $0 = "load /proc/boot/guest-ifs.bin" } { print }' \
		"$GATE/asrun.conf" > "$GATE/asrun-native.conf"
	[ -f "$CONF_SRC" ] || die "PO-E: no $CONF_SRC"
	strip_conf "$CONF_SRC" > "$OUT/g2-m3.conf"
	if ! cmp -s "$GATE/asrun-native.conf" "$OUT/g2-m3.conf"; then
		diff "$GATE/asrun-native.conf" "$OUT/g2-m3.conf" >&2 || true
		die "PO-E: stripped g2-m3.conf is not the as-run configuration with only its load line substituted"
	fi
	echo "   PO-E g2-m3.conf is the as-run text with only the load line substituted (unchanged from M3): ok"
}

# ---- step 8: parameters ------------------------------------------------------------

declare -A PARAM

set_param() { PARAM[$1]="$2"; }
need_int() {
	local k="$1" lo="$2" hi="$3" v="${PARAM[$1]:-}"
	[[ "$v" =~ ^[0-9]+$ ]] || die "$STEP: size file key $k='$v' is not a whole number"
	(( v >= lo && v <= hi )) || die "$STEP: size file key $k=$v is outside $lo-$hi (design §3.4 step 8)"
}
same() {
	local k="$1" want="$2"
	[ "${PARAM[$k]:-}" = "$want" ] || die "$STEP: size file key $k='${PARAM[$k]:-}' differs from the recomputed '$want' (design §8.1, §8.2)"
}

params_r0() {
	STEP="parameters (step 8)"
	set_param image m4-r0; set_param rung r0; set_param mode trace; set_param p 4
	set_param kind probe; set_param k 64; set_param s_mb 8; set_param tl_args "-r -k 64 -M -S 8M"
	set_param tl_bound 300; set_param trace_need_mb 44
	set_param iters 15; set_param ipc_bound 240; set_param banner_bound 240; set_param grace 90
	set_param tp_bound 600; set_param cnt_bound 120; set_param hash_bound 20; set_param forms v
	set_param cap_v 262144; set_param cap_c 0; set_param send_v 68; set_param send_c 30
	set_param send_t_v 63; set_param send_t_c 25
	set_param clean_pred -; set_param p2_reachable -; set_param p99_reachable -; set_param accept_low_n -
	set_param size_file -; set_param size_sha256 -; set_param e3 status0; set_param transport tcu
	# §8.2: L0's -S 32M for the format gate, applied to the probe too.
	set_param fmt_need_mb $(( 5 * 32 + 270 + $(ceil_div 262144 1048576) + 32 ))
	set_param cnt_need_mb $(( 270 + $(ceil_div 262144 1048576) + 32 ))
	# §8.1's r0 column: 1341 fixed seconds plus the L0 traceprinter, counter and send bounds.
	set_param ksh_worst_s $(( 1341 + ${PARAM[tp_bound]} + ${PARAM[cnt_bound]} + ${PARAM[send_v]} ))
	set_param guard_s $(( ( (${PARAM[ksh_worst_s]} + 125 + 240 + 299) / 300 ) * 300 ))
	set_param return_bound_s $(( ${PARAM[guard_s]} + 300 ))
	set_param capture_s $(( ${PARAM[return_bound_s]} + 3000 ))
	[ "${PARAM[ksh_worst_s]}" = 2129 ] && [ "${PARAM[guard_s]}" = 2700 ] && [ "${PARAM[fmt_need_mb]}" = 463 ] \
		&& [ "${PARAM[cnt_need_mb]}" = 303 ] && [ "${PARAM[capture_s]}" = 6000 ] \
		|| die "parameters: r0's recomputed values differ from the design's table (§3.3, §8.1, §8.2)"
	IMAGE=m4-r0
	echo "   r0 fixed values: guard ${PARAM[guard_s]} s, capture ${PARAM[capture_s]} s, fmt_need ${PARAM[fmt_need_mb]} MiB: ok"
}

params_sized() {
	local line key val kk s want_image worst caps
	STEP="parameters (step 8)"
	[ -f "$SIZE_FILE" ] || die "no size file $SIZE_FILE"
	while IFS= read -r line || [ -n "$line" ]; do
		line="${line%$'\r'}"
		case "$line" in ''|'#'*) continue ;; esac
		[[ "$line" == *=* ]] || die "size file line '$line' is not key=value"
		key="${line%%=*}"
		val="${line#*=}"
		[[ "$key" =~ ^[a-z0-9_]+$ ]] || die "size file key '$key' has characters outside [a-z0-9_]"
		[[ "$val" =~ ^[A-Za-z0-9\ ._-]*$ ]] || die "size file value of $key has characters outside [A-Za-z0-9 ._-]"
		PARAM[$key]="$val"
	done < "$SIZE_FILE"
	for key in image rung mode p kind k s_mb tl_args tl_bound trace_need_mb fmt_need_mb cnt_need_mb iters \
	           ipc_bound banner_bound grace tp_bound cnt_bound hash_bound forms cap_v cap_c send_v send_c \
	           send_t_v send_t_c clean_pred p2_reachable p99_reachable accept_low_n ksh_worst_s guard_s \
	           return_bound_s capture_s; do
		[ -n "${PARAM[$key]+set}" ] || die "size file lacks key $key"
	done
	# N15 (m4-design.md 14.7): r1 and r2 default to E3 none; a size file that names e3 still decides.
	[ -n "${PARAM[e3]+set}" ] || PARAM[e3]=none
	[ -n "${PARAM[transport]+set}" ] || PARAM[transport]=tcu
	case "${PARAM[e3]}" in status0|none) ;; *) die "size file e3=${PARAM[e3]} is not status0 or none" ;; esac
	[ "${PARAM[transport]}" = tcu ] || die "a board image sends over the TCU (transport=${PARAM[transport]})"
	same rung "$RUNG"
	same mode full
	same p 4
	if [ "${PARAM[k]}" = lin ]; then
		kk=512
		same kind linear
		same s_mb "$(s_of_k 512)"
		same tl_args "-c -S ${PARAM[s_mb]}M"
	else
		need_int k 64 512
		kk="${PARAM[k]}"
		same kind ring
		same s_mb "$(s_of_k "$kk")"
		same tl_args "-r -k $kk -M -S ${PARAM[s_mb]}M"
	fi
	need_int iters 15 13200
	need_int ipc_bound 240 900
	need_int banner_bound 60 900
	need_int grace 10 300
	need_int tp_bound 120 900
	need_int cnt_bound 60 600
	need_int hash_bound 10 120
	need_int cap_v 65536 1048576
	need_int cap_c 65536 1048576
	for key in send_v send_c send_t_v send_t_c; do need_int "$key" 25 600; done
	need_int send_v 30 600
	need_int send_c 30 600
	same send_t_v $(( ${PARAM[send_v]} - 5 ))
	same send_t_c $(( ${PARAM[send_c]} - 5 ))
	same tl_bound $(( 2 + ${PARAM[ipc_bound]} + 5 + 160 + 30 ))
	(( ${PARAM[trace_need_mb]} >= $(ring_mb "$kk") + ${PARAM[s_mb]} + 32 )) \
		|| die "parameters: trace_need_mb=${PARAM[trace_need_mb]} is below ring + S + 32 MiB (§2.4 step 3)"
	caps=$(ceil_div $(( ${PARAM[cap_v]} + ${PARAM[cap_c]} )) 1048576)
	same fmt_need_mb $(( 5 * ${PARAM[s_mb]} + 270 + caps + 32 ))
	same cnt_need_mb $(( 270 + caps + 32 ))
	worst=$(( 736 + ${PARAM[banner_bound]} + ${PARAM[ipc_bound]} + ${PARAM[tp_bound]} + ${PARAM[cnt_bound]} + ${PARAM[send_v]} + ${PARAM[send_c]} ))
	same ksh_worst_s "$worst"
	same guard_s $(( ( (worst + 125 + 240 + 299) / 300 ) * 300 ))
	same return_bound_s $(( ${PARAM[guard_s]} + 300 ))
	same capture_s $(( ${PARAM[return_bound_s]} + 3000 ))
	if [ "$RUNG" = r1 ]; then
		same iters 15
		same ipc_bound 240
		same forms "v c"
		(( ${PARAM[guard_s]} <= 2700 )) || die "parameters: r1's guard ${PARAM[guard_s]} s exceeds 2,700 s (§2.4 step 7)"
		if [ "${PARAM[k]}" = lin ]; then want_image=m4-r1-lin; else want_image="m4-r1-k${PARAM[k]}"; fi
	else
		same forms "c v"
		same ipc_bound $(( 240 + (5 * ${PARAM[iters]} + 99) / 100 ))
		(( ${PARAM[guard_s]} <= 3600 )) || die "parameters: r2's guard ${PARAM[guard_s]} s exceeds 3,600 s (§2.4 step 10)"
		case "${PARAM[p2_reachable]}" in
		yes) ;;
		*) die "parameters: r2 size file has p2_reachable=${PARAM[p2_reachable]}; a T-series predicted to miss P2 goes to the owner (§2.4 step 11)" ;;
		esac
		case "${PARAM[p99_reachable]}" in
		yes|short-margin) ;;
		no) [ "${PARAM[accept_low_n]}" = 1 ] || die "parameters: r2 size file has p99_reachable=no without accept_low_n=1 (§2.4 step 11)" ;;
		*) die "parameters: r2 size file has p99_reachable=${PARAM[p99_reachable]}" ;;
		esac
		if [ "${PARAM[k]}" = lin ]; then want_image="m4-r2-lin-n${PARAM[iters]}"; else want_image="m4-r2-k${PARAM[k]}-n${PARAM[iters]}"; fi
	fi
	same image "$want_image"
	IMAGE="$want_image"
	PARAM[size_file]="$(basename "$SIZE_FILE")"
	PARAM[size_sha256]="$(sha "$SIZE_FILE")"
	echo "   $IMAGE from $(basename "$SIZE_FILE"): ranges and the recomputed bounds agree (guard ${PARAM[guard_s]} s, capture ${PARAM[capture_s]} s): ok"
}

cnt_out_of() {
	local e=""
	[ "${PARAM[e3]}" = none ] && e=" -E none"
	case "$RUNG" in
	r0) echo "-v /dev/shmem/flt.v -V ${PARAM[cap_v]}$e" ;;
	r1) echo "-v /dev/shmem/flt.v -V ${PARAM[cap_v]} -c /dev/shmem/flt.c -C ${PARAM[cap_c]}$e" ;;
	r2) echo "-c /dev/shmem/flt.c -C ${PARAM[cap_c]} -v /dev/shmem/flt.v -V ${PARAM[cap_v]}$e" ;;
	esac
}

write_params() {
	local f="$OUT/$IMAGE.params" k
	# I24 (m4-design.md 14.5): the fixtures this image carries, so the parser expects exactly these.
	PARAM[fixtures]="m4fix-1.txt,m4fix-2.txt,m4fix-3.txt,m4fix-4.txt"
	: > "$f"
	for k in "${PARAM_KEYS[@]}"; do
		printf '%s=%s\n' "$k" "${PARAM[$k]:--}" >> "$f"
	done
}

# ---- step 9: generate ---------------------------------------------------------------

STARTUP_WANT="startup-$BOARD -vvv -P4 -Q enable,el2-host -m992M -Wkeep -A -Dtcu"

generate() {
	local build="$OUT/$IMAGE.build" ksh="$OUT/$IMAGE.ksh" body="$OUT/$IMAGE.build.body" line l c i conf="$OUT/g2-m3.conf"
	local inj last out
	STEP="$IMAGE: generate (step 9)"

	for i in 1 2 3 4; do
		[ -f "$FIX_SRC_DIR/m4fix-$i.txt" ] || die "no $FIX_SRC_DIR/m4fix-$i.txt"
		awk '{ sub(/\r$/, "") } { print }' "$FIX_SRC_DIR/m4fix-$i.txt" > "$OUT/m4fix-$i.txt"
		head -n 1 "$OUT/m4fix-$i.txt" | grep -qx '# m4fix: synthetic' || die "m4fix-$i.txt lost its '# m4fix: synthetic' first line"
	done

	# The two verbatim ranges of §3.2 against m3.build.in.
	sed -n '95,128p' "$M3_BUILD_TEMPLATE" > "$GATE/m3-95-128.txt"
	sed -n '148,173p' "$M3_BUILD_TEMPLATE" > "$GATE/m3-148-173.txt"
	[ "$(wc -l < "$GATE/m3-95-128.txt")" -eq 34 ] && [ "$(wc -l < "$GATE/m3-148-173.txt")" -eq 26 ] \
		|| die "$IMAGE: m3.build.in no longer has lines 95-128 and 148-173"
	head -n 1 "$GATE/m3-95-128.txt" | grep -qx 'libc.so.6' && tail -n 1 "$GATE/m3-148-173.txt" | grep -qx '\[type=link\] wc=toybox' \
		|| die "$IMAGE: m3.build.in:95 is not libc.so.6 or :173 is not the wc link; the verbatim ranges moved"
	[ "$(block_matches "$GATE/m3-95-128.txt" "$BUILD_TEMPLATE")" = 1 ] \
		|| die "$IMAGE: m4.build.in does not carry m3.build.in:95-128 verbatim exactly once"
	[ "$(block_matches "$GATE/m3-148-173.txt" "$BUILD_TEMPLATE")" = 1 ] \
		|| die "$IMAGE: m4.build.in does not carry m3.build.in:148-173 verbatim exactly once"
	echo "   verbatim ranges m3.build.in:95-128 and :148-173 found once each in m4.build.in: ok"

	subst hash "$BUILD_TEMPLATE" "$body" \
		RUNG="$RUNG" P=4 GUARD="${PARAM[guard_s]}" \
		CLIENT="$(hostpath "$CLIENT")" \
		GUEST_IFS="$(hostpath "$GUEST_IFS")" \
		GUEST_DISK="$(hostpath "$GUEST_DISK")" \
		KSH="$(hostpath "$ksh")" \
		CONF="$(hostpath "$conf")" \
		FIX1="$(hostpath "$OUT/m4fix-1.txt")" \
		FIX2="$(hostpath "$OUT/m4fix-2.txt")" \
		FIX3="$(hostpath "$OUT/m4fix-3.txt")" \
		FIX4="$(hostpath "$OUT/m4fix-4.txt")"
	{
		echo "# $IMAGE - M4 rung $RUNG, mode ${PARAM[mode]}."
		echo "# Generated from orin-native/startup/m4.build.in by make-m4-images.sh: comment"
		echo "# lines removed, markers replaced. Edit the template, never this copy."
		echo "# No image generated from this has run on the board."
		echo "# Design: $DESIGN, sections 3.2 to 3.4."
		echo
		cat "$body"
	} > "$build"
	rm -f "$body"
	no_markers "$build"

	c=$(awk -v s="startup-$BOARD" '$1 == s { c++ } END { print c + 0 }' "$build")
	[ "$c" = 1 ] || die "$IMAGE: $c startup lines in $build, expected 1"
	[ "$(count_line "$build" "$STARTUP_WANT")" = 1 ] || die "$IMAGE: expected exactly one line '$STARTUP_WANT' in $build"
	c=$(awk '/^\[\+script\] \.script = \{/ { in_s = 1; next } in_s && /^\}/ { in_s = 0 } in_s && NF { c++ } END { print c + 0 }' "$build")
	[ "$c" = 13 ] || die "$IMAGE: $c script lines in $build, expected 13"
	for l in "display_msg \"T234 M4 $RUNG -P4: procnto up\"" \
	         "display_msg \"T234 M4 $RUNG -P4: resetting so the log can be recovered\"" \
	         "bwait -g ${PARAM[guard_s]} &" "smpcheck -i -n 4" "ksh /proc/boot/m4-host.ksh" "shutdown -S reboot"; do
		[ "$(count_line "$build" "$l")" = 1 ] || die "$IMAGE: expected exactly one line '$l' in $build"
	done

	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$build")
	[ "$line" = "$STARTUP_WANT" ] || die "$IMAGE: startup line '$line' in $build is not '$STARTUP_WANT'"
	subst notes "$KSH_TEMPLATE" "$ksh" \
		RUNG="$RUNG" MODE="${PARAM[mode]}" P=4 CPUS="0 1 2 3" RATES=1 IO_BOUND=30 \
		B=/proc/boot X=/proc/boot \
		GUEST_IFS=/proc/boot/guest-ifs.bin GUEST_DISK=/proc/boot/disk-qvm CONF=/proc/boot/g2.conf \
		CLIENT=/proc/boot/qnx-host-client \
		STARTUP_LINE="$line" A=1 \
		GUEST_SHA256="$PIN_GUEST" DISK_SHA256="$PIN_DISK" CONF_SHA256="$(sha "$conf")" CLIENT_SHA256="$PIN_CLIENT" \
		GUEST_MD5="$GUEST_MD5" DISK_MD5="$DISK_MD5" CONF_MD5="$(md5 "$conf")" \
		ITERS="${PARAM[iters]}" IPC_BOUND="${PARAM[ipc_bound]}" BANNER_BOUND="${PARAM[banner_bound]}" \
		GRACE="${PARAM[grace]}" GRACE_WAIT=$(( ${PARAM[grace]} + 10 )) \
		KIND="${PARAM[kind]}" TL_ARGS="${PARAM[tl_args]}" TL_BOUND="${PARAM[tl_bound]}" \
		TRACE_NEED_MB="${PARAM[trace_need_mb]}" FMT_NEED="${PARAM[fmt_need_mb]}" CNT_NEED="${PARAM[cnt_need_mb]}" \
		TP_BOUND="${PARAM[tp_bound]}" CNT_BOUND="${PARAM[cnt_bound]}" HASH_BOUND="${PARAM[hash_bound]}" \
		CNT_OUT="$(cnt_out_of)" FORMS="${PARAM[forms]}" \
		SEND_V="${PARAM[send_v]}" SEND_T_V="${PARAM[send_t_v]}" SEND_C="${PARAM[send_c]}" SEND_T_C="${PARAM[send_t_c]}" \
		TRANSPORT=tcu \
		FIX="/proc/boot/m4fix-1.txt /proc/boot/m4fix-2.txt /proc/boot/m4fix-3.txt /proc/boot/m4fix-4.txt"
	no_markers "$ksh"
	for l in "RUNG=$RUNG" "MODE=${PARAM[mode]}" "P=4" "CPUS=\"0 1 2 3\"" \
	         "md5ok \"\$S/md5.pre\" $GUEST_MD5 guest md5_pre" \
	         "md5ok \"\$S/md5.pre\" $DISK_MD5 disk md5_pre" \
	         "md5ok \"\$S/md5.pre\" $(md5 "$conf") conf md5_pre" \
	         "md5ok \"\$S/md5.post\" $GUEST_MD5 guest md5_post" \
	         "md5ok \"\$S/md5.post\" $DISK_MD5 disk md5_post"; do
		[ "$(count_line "$ksh" "$l")" = 1 ] || die "$IMAGE: expected exactly one line '$l' in $ksh"
	done
	l="startup='$line' q=el2-host w=keep A=1 cpus=\$P guest_sha256=$PIN_GUEST disk_sha256=$PIN_DISK conf_sha256=$(sha "$conf") client_sha256=$PIN_CLIENT clock=unverified"
	[ "$(grep -cF -- "$l" "$ksh" || true)" = 1 ] || die "$IMAGE: the CONFIG line in $ksh does not carry the image's fields"

	# The pipe-free rule (§3.4 step 9, review V2): the checker's own test, the
	# generated script, then a copy with a pipe on its last command line.
	STEP="$IMAGE: kshcheck (step 9)"
	"$PY_BIN" "$PARSER" kshcheck --selftest > "$GATE/kshcheck-selftest.txt" 2>&1 \
		|| { cat "$GATE/kshcheck-selftest.txt" >&2; die "$IMAGE: kshcheck --selftest failed"; }
	echo "   kshcheck --selftest: ok"
	out="$("$PY_BIN" "$PARSER" kshcheck "$ksh" 2>&1)" || { printf '%s\n' "$out" >&2; die "$IMAGE: the generated host script breaks the pipe-free rule"; }
	echo "   kshcheck $IMAGE.ksh: $out"
	inj="$GATE/inject-pipe.ksh"
	last=$(awk '{ sub(/\r$/, "") } NF && $1 !~ /^#/ { n = NR } END { print n + 0 }' "$ksh")
	awk -v n="$last" '{ sub(/\r$/, "") } NR == n { $0 = $0 " | cat" } { print }' "$ksh" > "$inj"
	if out="$("$PY_BIN" "$PARSER" kshcheck "$inj" 2>&1)"; then
		rm -f "$inj"
		die "$IMAGE: kshcheck accepted a script with a pipe appended to line $last"
	fi
	rm -f "$inj"
	printf '%s\n' "$out" | grep -q "line=$last rule=1" || die "$IMAGE: kshcheck did not name line $last for the injected pipe: $out"
	echo "   kshcheck on a copy with ' | cat' appended to line $last: rejected, naming that line: ok"

	STEP="$IMAGE: generate (step 9)"
	bash -n "$ksh" || die "$IMAGE: $ksh does not parse (bash -n)"
	PARAM[ksh_sha256]="$(sha "$ksh")"
	PARAM[kimg_sha256]=-
	write_params
	printf '   %-22s %-5s %-6s k=%-4s iters=%-5s guard=%s capture=%s\n' "$IMAGE" "$RUNG" "${PARAM[mode]}" \
		"${PARAM[k]}" "${PARAM[iters]}" "${PARAM[guard_s]}" "${PARAM[capture_s]}"
	printf '   %-22s build  sha256 %s\n' "" "$(sha "$build")"
	printf '   %-22s ksh    sha256 %s\n' "" "${PARAM[ksh_sha256]}"
}

tracked_guard() {
	local not_ignored now rc=0 n_in n_out f
	local list="$GATE/written.list" res="$GATE/written.check"
	STEP="tracked-path guard (step 19)"
	{
		find "$OUT" -type f ! -path "$list" ! -path "$res"
		for f in t234-shim.o t234-shim.elf t234-shim.bin t234-qnx.kimg; do
			[ ! -e "$SHIM/out/$f" ] || echo "$SHIM/out/$f"
		done
	} | awk -v r="$REPO/" 'index($0, r) == 1 { print substr($0, length(r) + 1); next } { print "OUTSIDE-REPO:" $0 }' > "$list"
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

# ---- steps 10-17 ----------------------------------------------------------------------

setup_sdp() {
	local t
	STEP="SDP environment (step 10)"
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
	for t in mkifs dumpifs; do
		command -v "$t" >/dev/null || die "$t not on PATH — source qnxsdp-env or set QNX_BASE"
	done
	if command -v cygpath >/dev/null 2>&1; then
		SDP_TGT="$(cygpath -u "$QNX_TARGET")/aarch64le"
		MKIFS_PATH="$(cygpath -w "$BOARD_LE");$(cygpath -w "$TOOLS")"
	else
		SDP_TGT="$QNX_TARGET/aarch64le"
		MKIFS_PATH="$BOARD_LE:$TOOLS"
	fi
	export MKIFS_PATH
	echo "== MKIFS_PATH=$MKIFS_PATH"
}

check_inputs() {
	local f
	STEP="inputs (step 10)"
	[ -f "$STARTUP_BIN" ] || die "no $STARTUP_BIN"
	for f in "${TOOL_NAMES[@]}"; do
		[ -f "$TOOLS/$f" ] || die "no $TOOLS/$f — run make -C orin-native/tools in the SDP environment first"
	done
	[ -f "$SHIM/build-shim.sh" ] || die "no $SHIM/build-shim.sh"
	for f in "${SDP_FILES[@]}"; do
		[ -f "$SDP_TGT/$f" ] || die "no $SDP_TGT/$f in the SDP"
	done
	echo "   inputs: startup, ${#TOOL_NAMES[@]} tools, build-shim.sh and ${#SDP_FILES[@]} SDP files present: ok"
}

# Step 11: every file the buildfile names, by ls size, plus 262,144 B of slack.
size_check() {
	local build="$OUT/$IMAGE.build" sum=262144 unresolved="" line name src d f sz end
	STEP="$IMAGE: size check (step 11)"
	while IFS= read -r line; do
		line="${line%$'\r'}"
		line="${line#"${line%%[![:space:]]*}"}"
		case "$line" in
		''|'#'*|'[image='*|'[-'*|'[+script]'*|'[virtual='*|'}'*|'PATH='*|'display_msg'*|'procmgr_'*|'openssl-3'*) continue ;;
		'[type=link]'*) continue ;;
		esac
		# script-block commands have blanks; files are single tokens with an optional [attrs] prefix
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
			for d in "$BOARD_LE" "$TOOLS" "$SDP_TGT/boot/sys" "$SDP_TGT/sbin" "$SDP_TGT/usr/sbin" "$SDP_TGT/bin" \
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
	(( end <= 0x8C000000 )) || die "$IMAGE: the files the buildfile names sum to $sum B; 0x80082fa0 + that passes 0x8C000000"
	printf '   size check: %d B named (262,144 B slack included), image would end near 0x%x, below 0x8c000000: ok\n' "$sum" "$end"
	[ -z "$unresolved" ] || echo "   size check note: names not resolved to a host file (mkifs resolves them; step 14 checks the real end):$unresolved"
}

build_ifs() {
	STEP="$IMAGE: mkifs (step 12)"
	rm -f "$OUT/$IMAGE.ifs" "$OUT/$IMAGE.kimg"
	if ! ( cd "$OUT" && mkifs -v "$IMAGE.build" "$IMAGE.ifs" ) > "$OUT/$IMAGE.mkifs.txt" 2>&1; then
		tail -n 30 "$OUT/$IMAGE.mkifs.txt" >&2
		die "$IMAGE: mkifs failed; full output in $OUT/$IMAGE.mkifs.txt"
	fi
	[ -s "$OUT/$IMAGE.ifs" ] || die "$IMAGE: mkifs exited 0 but wrote no $IMAGE.ifs"
	if [ -f "$OUT/procnto-smp-instr.sym" ]; then
		mv -f "$OUT/procnto-smp-instr.sym" "$OUT/$IMAGE.procnto-smp-instr.sym"
	fi
	echo "   mkifs: $OUT/$IMAGE.ifs ($(stat -c %s "$OUT/$IMAGE.ifs") bytes)"
}

check_dumpifs() {
	local f="$OUT/$IMAGE.dumpifs.txt" s="$OUT/$IMAGE.script.txt" got name l extras
	STEP="$IMAGE: dumpifs (step 13)"
	( cd "$OUT" && dumpifs -vv "$IMAGE.ifs" ) 2>&1 | tr -d '\r' > "$f" || die "$IMAGE: dumpifs failed; see $f"
	grep -q 'compress=0 ' "$f" || die "$IMAGE: image is not uncompressed (see $f)"
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
	for l in "display_msg \"T234 M4 $RUNG -P4: procnto up\"" \
	         "display_msg \"T234 M4 $RUNG -P4: resetting so the log can be recovered\"" \
	         "bwait -g ${PARAM[guard_s]} &" "slogger2" "pipe" "devc-pty" "pidin info" "smpcheck -i -n 4" \
	         "ksh /proc/boot/m4-host.ksh" "smpcheck -z 3" "shutdown -S reboot"; do
		got=$(grep -cxF -- "$l" "$s" || true)
		[ "$got" = 1 ] || die "$IMAGE: dumpifs shows $got script lines '$l', expected 1 (see $s)"
	done
	for name in "${IFS_NAMES[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 1 ] || die "$IMAGE: dumpifs lists proc/boot/$name $got time(s), expected exactly 1 (see $f)"
	done
	got=$(awk '$4 == "usr/lib/ldqnx-64.so.2" && $5 == "->" { c++ } END { print c + 0 }' "$f")
	[ "$got" = 1 ] || die "$IMAGE: dumpifs lists the usr/lib/ldqnx-64.so.2 link $got time(s), expected 1 (see $f)"
	for name in "${ABSENT_NAMES[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 0 ] || die "$IMAGE: dumpifs lists proc/boot/$name, which no M4 image may carry (see $f)"
	done
	got=$(awk '$4 ~ /\.sym$/ { c++ } END { print c + 0 }' "$f")
	[ "$got" = 0 ] || die "$IMAGE: dumpifs lists $got .sym file(s) inside the image (see $f)"
	extras=$(awk -v list="${IFS_NAMES[*]}" '
		BEGIN { n = split(list, a, " "); for (i = 1; i <= n; i++) want["proc/boot/" a[i]] = 1 }
		$4 ~ /^proc\/boot\// && !($4 in want) { printf("%s ", $4) }' "$f")
	echo "   dumpifs: uncompressed; 13 script lines with 'T234 M4 $RUNG -P4' and bwait -g ${PARAM[guard_s]} &; ${#IFS_NAMES[@]} names once each; ${#ABSENT_NAMES[@]} excluded names and .sym absent: ok"
	[ -z "$extras" ] || echo "   dumpifs note: entries beyond the design's list (not an error): $extras"
}

check_geometry() {
	local f="$OUT/$IMAGE.dumpifs.txt" v ip ss end
	STEP="$IMAGE: geometry (step 14)"
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
	[ "$ip" = 0x80082fa0 ] || die "$IMAGE: image_paddr=$ip, expected 0x80082fa0 (see $f)"
	end=$(( ip + ss ))
	[ "$end" -le $((0x8C000000)) ] \
		|| die "$IMAGE: the image ends at $(printf 0x%x "$end"), beyond 0x8c000000"
	printf '   geometry: image_paddr=%s stored_size=%s, ends at 0x%x, %d MiB of the window left above it: ok\n' \
		"$ip" "$ss" "$end" $(( (0xBE000000 - end) / 1048576 ))
}

check_startup_args() {
	local line limit
	STEP="$IMAGE: startup-argument check (step 15)"
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$OUT/$IMAGE.build")
	limit=$(( PREBOOT + STARTUP_SIZE ))
	( cd "$OUT" && "$PY_BIN" - "$IMAGE.ifs" 4 "enable,el2-host" 1 "$line" "$limit" <<'PY'
import sys

path, n, q = sys.argv[1], int(sys.argv[2]), sys.argv[3]
want_a, line, limit = sys.argv[4] == "1", sys.argv[5], int(sys.argv[6])
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
if argv != want:
    sys.exit("startup arguments %r differ from the buildfile's %r" % (argv, want))
print("   exactly -P%d, -Q %s and one -A, and otherwise the buildfile's startup line: ok" % (n, q))
PY
	) || die "$IMAGE: the IFS does not carry the startup arguments it was built for"
}

check_identity() {
	local x="xtr-$IMAGE" d f want got
	d="$OUT/$x"
	STEP="$IMAGE: byte identity inside the IFS (step 16)"
	rm -rf "$d"
	mkdir -p "$d"
	if ! ( cd "$OUT" && dumpifs -x -b -d "$x" -f guest-ifs.bin -f disk-qvm -f g2.conf -f m4-host.ksh \
	       -f m4fix-1.txt -f m4fix-2.txt -f m4fix-3.txt -f m4fix-4.txt "$IMAGE.ifs" ) > "$OUT/$IMAGE.extract.txt" 2>&1; then
		rm -rf "$d"
		tail -n 20 "$OUT/$IMAGE.extract.txt" >&2
		die "$IMAGE: dumpifs -x failed; see $OUT/$IMAGE.extract.txt"
	fi
	for f in guest-ifs.bin disk-qvm g2.conf m4-host.ksh m4fix-1.txt m4fix-2.txt m4fix-3.txt m4fix-4.txt; do
		case "$f" in
		guest-ifs.bin) want="$PIN_GUEST" ;;
		disk-qvm)      want="$PIN_DISK" ;;
		g2.conf)       want=$(sha "$OUT/g2-m3.conf") ;;
		m4-host.ksh)   want=$(sha "$OUT/$IMAGE.ksh") ;;
		*)             want=$(sha "$OUT/$f") ;;
		esac
		if [ ! -f "$d/$f" ]; then
			rm -rf "$d"
			die "$IMAGE: dumpifs did not extract $f from $IMAGE.ifs"
		fi
		got=$(sha "$d/$f")
		if [ "$got" != "$want" ]; then
			rm -rf "$d"
			die "$IMAGE: $f extracted from $IMAGE.ifs has sha256 $got, expected $want"
		fi
		echo "   identity: /proc/boot/$f extracted from the IFS, sha256 $got: ok"
	done
	rm -rf "$d"
}

wrap() {
	local isz ksz want_is
	STEP="$IMAGE: build-shim.sh jump (step 17)"
	if ! OUT_DIR="$SHIM/out" bash "$SHIM/build-shim.sh" jump "$OUT/$IMAGE.ifs" > "$OUT/$IMAGE.shim.txt" 2>&1; then
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

resolved_path() {
	local p
	p=$(awk -v k=" proc/boot/$2=" '{ sub(/\r$/, ""); i = index($0, k); if (i > 0) { print substr($0, i + length(k)); exit } }' "$1")
	[ -n "$p" ] || return 0
	if command -v cygpath >/dev/null 2>&1; then cygpath -u -- "$p"; else echo "$p"; fi
}

# ---- main ------------------------------------------------------------------------

echo "== M4 image ($DESIGN, section 3): m4-$RUNG${SIZE_FILE:+ from $(basename "$SIZE_FILE")}"
echo "== guards and pins (steps 1-7)"
guard_output
snapshot_status
po_a
po_b
po_c
po_d
po_e

echo "== parameters (step 8)"
if [ "$RUNG" = r0 ]; then params_r0; else params_sized; fi

echo "== generating $IMAGE into $OUT (step 9)"
find_python
generate

if [ "$GEN_ONLY" = 1 ]; then
	tracked_guard
	echo "== --generate-only: stopping before mkifs; no image was built"
	exit 0
fi

setup_sdp
check_inputs
declare -A SUM_A
STEP="inputs (step 10)"
SUM_A[startup]=$(sha "$STARTUP_BIN")
for t in "${TOOL_NAMES[@]}"; do SUM_A[$t]=$(sha "$TOOLS/$t"); done
SUM_A[client]=$(sha "$CLIENT")
[ "${SUM_A[startup]}" = "$PIN_STARTUP" ] || die "$STARTUP_BIN changed after PO-B"
[ "${SUM_A[smpcheck]}" = "$PIN_SMPCHECK" ] || die "$TOOLS/smpcheck changed after PO-B"
[ "${SUM_A[client]}" = "$PIN_CLIENT" ] || die "$CLIENT changed after PO-B"

echo "== $IMAGE (-P4, ${PARAM[mode]})"
size_check
build_ifs
check_dumpifs
check_geometry
check_startup_args
check_identity
wrap

STEP="input stability (step 18)"
[ "$(sha "$STARTUP_BIN")" = "${SUM_A[startup]}" ] || die "$STARTUP_BIN changed during this run; rebuild the image"
for t in "${TOOL_NAMES[@]}"; do
	[ "$(sha "$TOOLS/$t")" = "${SUM_A[$t]}" ] || die "$TOOLS/$t changed during this run; rebuild the image"
done
[ "$(sha "$CLIENT")" = "${SUM_A[client]}" ] || die "$CLIENT changed during this run; rebuild the image"
echo "   startup, ${#TOOL_NAMES[@]} tools and the client unchanged during the run: ok"

tracked_guard

STEP="sha256 table (step 20)"
echo
echo "== sha256 (the kimg is what goes to the board; sha256sum it there before kexec)"
row() { printf '%-18s %-28s %10s  %s\n' "$@"; }
row kind file bytes sha256
for f in "$IMAGE.kimg" "$IMAGE.ifs" "$IMAGE.build" "$IMAGE.ksh" "$IMAGE.params" g2-m3.conf m4fix-1.txt m4fix-2.txt m4fix-3.txt m4fix-4.txt; do
	row generated "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
done
row input "startup-$BOARD" "$(stat -c %s "$STARTUP_BIN")" "${SUM_A[startup]}"
for t in "${TOOL_NAMES[@]}"; do row input "$t" "$(stat -c %s "$TOOLS/$t")" "${SUM_A[$t]}"; done
row input qnx-host-client "$(stat -c %s "$CLIENT")" "${SUM_A[client]}"
row guest ifs.bin "$(stat -c %s "$GUEST_IFS")" "$PIN_GUEST"
row guest "ifs.bin md5" - "$GUEST_MD5"
row guest disk-qvm "$(stat -c %s "$GUEST_DISK")" "$PIN_DISK"
row guest "disk-qvm md5" - "$DISK_MD5"
for name in "${HASHED_NAMES[@]}"; do
	hp=$(resolved_path "$OUT/$IMAGE.mkifs.txt" "$name")
	[ -n "$hp" ] && [ -f "$hp" ] || die "cannot find the host file mkifs used for $name in $OUT/$IMAGE.mkifs.txt"
	row sdp "$name" "$(stat -c %s "$hp")" "$(sha "$hp")"
done
echo
echo "== $IMAGE.params"
sed 's/^/   /' "$OUT/$IMAGE.params"
echo "   PO-A to PO-E passed before the build (top of this output)"
echo "== done: $OUT/$IMAGE.kimg"
