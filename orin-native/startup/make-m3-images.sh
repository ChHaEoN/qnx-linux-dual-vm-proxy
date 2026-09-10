#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# make-m3-images.sh — generate, build, check and wrap the M3 images.
#
# Phase 3b, the M3 design's §5 (results/orin-native-port/20260909T1100Z/
# m3-design.md, revision 2). Compile-only: nothing here talks to the board, and
# no image it builds has run there.
#
#   BSP=/path/to/extracted/BSP QNX_BASE=/path/to/qnx800 \
#       ./make-m3-images.sh [--generate-only] [image ...]
#
#   image   rung  mode     IPC bound  configuration    role (design §5.1, §6.6)
#   m3-r0   r0    harness  20 s       g2-m3.conf       R0: everything but qvm
#   m3-r1   r1    boot     240 s      g2-m3.conf       R1: first qvm launch, no IPC
#   m3-r2   r2    full     240 s      g2-m3.conf       R2 (Q) and T1-T5
#   m3-d1   d1    boot     240 s      g2-m3-diag.conf  diagnostic D1, never timed
#   m3-d2   d2    boot     240 s      g2-noblk.conf    diagnostic D2, never timed
#
# With no names it does those five, in that order. Only when named (design §5.1):
#   m3n-<rung>     the same image without -A (owner decision O3 declined)
#   m3-<rung>-p6   contingency C2: -P6, CPUs 0-5, the same payload
# and m3n-<rung>-p6 for both. The gzip'd-disk images m3z-* (O7) are not built
# here: they carry a different payload and wait on a licence confirmation.
#
# Every image uses one startup build (the M1b one, pinned), one smpcheck build
# (pinned), one build each of stamp and bwait, the pinned IPC client and one
# buildfile template. The images differ only in the rung, the mode, the IPC
# bound and the configuration.
#
# Steps, numbered as the design's §5.2:
#    1. output guard: out/m3 must not resolve into out/m1b or out/m2 and must be
#       git-ignored; this script never calls the M1b or M2 generators
#    2. snapshot of git status --porcelain
#    3. PO-A: m2.build.in, make-m2-images.sh, make-m1b-images.sh and the board
#       directory match git HEAD
#    4. PO-B: the startup, smpcheck and IPC client match their sha256 pins
#    5. PO-C: the kimgs M1b and M2 ran, where still present, match their records
#    6. PO-D: the guest IFS and disk match their sha256 pins; md5s for baking
#    7. PO-E: g2-m3.conf is the as-run configuration with only its load line
#       substituted; the two diagnostic variants derive from it exactly
#    8. generate <image>.build and <image>.ksh; no marker may survive
#   --generate-only stops here (after the step-17 guard) and needs no SDP.
#    9. SDP environment and inputs (stamp and bwait built, SDP files present)
#   10. mkifs
#   11. dumpifs -vv: uncompressed, the script, every listed name exactly once,
#       the excluded names absent, no .sym
#   12. geometry: image_paddr and the image end inside the RAM window
#   13. startup arguments baked into the IFS: -P, -Q, -A and the whole line
#   14. the guest IFS, disk, configuration and host script extracted back out
#       of the IFS and hashed; the extraction is deleted afterwards
#   15. build-shim.sh jump: the kimg is the 8 KiB shim page plus this IFS
#   16. the startup, smpcheck, stamp, bwait and client did not change
#   17. every file written is git-ignored and git status equals the snapshot
#   18. sha256 table
# It stops at the first failure with "FAIL: <step>".
#
# Everything lands in orin-native/shim/out/m3/, which .gitignore:83 covers. An
# IFS and a kimg carry QNX binaries, the guest IFS and the guest disk (NCEULA),
# and so does the procnto .sym mkifs drops beside them; none of it may reach a
# tracked path. QNX files are handled as opaque bytes only: sizes, hashes,
# copies into our IFS, and extraction of the same files back out to hash them.
set -Eeuo pipefail

BOARD=t234-orin-nano
HERE="$(cd "$(dirname "$0")" && pwd)"
NATIVE="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$NATIVE/.." && pwd)"
TOOLS="$NATIVE/tools"
SHIM="$NATIVE/shim"
QHVCONF="$NATIVE/qhv"
OUT="$SHIM/out/m3"
GATE="$OUT/gate"
M1B_OUT="$SHIM/out/m1b"
M2_OUT="$SHIM/out/m2"
BSP="${BSP:-$HOME/orin-native-port-bsp}"
BOARD_LE="$BSP/src/hardware/startup/boards/$BOARD/aarch64/le"
STARTUP_BIN="$BOARD_LE/startup-$BOARD"
BUILD_TEMPLATE="$HERE/m3.build.in"
KSH_TEMPLATE="$HERE/m3-host.ksh.in"
FAKE_SRC="$HERE/m3-fake-guest.txt"
CONF_SRC_M3="$QHVCONF/g2-m3.conf"
CONF_SRC_DIAG="$QHVCONF/g2-m3-diag.conf"
CONF_SRC_NOBLK="$QHVCONF/g2-noblk.conf"
# The QNX-generated host build tree (git-ignored text) holds the configuration the
# timed TCG series ran; the committed snippet holds the three-vdev text.
ASRUN_POST="$REPO/qhv/host/output/build/post_startup.sh"
COMMITTED_POST="$REPO/scripts/qhv/post_start.custom"
GUEST_IFS="$REPO/qhv/guest/output/ifs.bin"
GUEST_DISK="$REPO/qhv/guest/output/disk-qvm"
CLIENT="$REPO/ipc-test/qnx-host-client/qnx-host-client"
DESIGN="results/orin-native-port/20260909T1100Z/m3-design.md"
DEFAULT_IMAGES=(m3-r0 m3-r1 m3-r2 m3-d1 m3-d2)

# Pins (design §2 rules 3-4, §5.2 steps 4 and 6).
PIN_STARTUP=90bf724c222b61f9791ad3bcaff60c6516be7180012333be9186a58d06d61896
PIN_SMPCHECK=f8e2c3078f12ac8ef27f1c482e77bd98d2188293195721d8168892a605c666b0
PIN_CLIENT=52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb
PIN_GUEST=968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f
PIN_DISK=cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b

# PO-A: the earlier generators and the board code (design §5.2 step 3).
PO_A_PATHS=(
	orin-native/startup/m2.build.in
	orin-native/startup/make-m2-images.sh
	orin-native/startup/make-m1b-images.sh
	orin-native/startup/t234-orin-nano
)

# Every /proc/boot name of design §3.1, both names of each linked library
# included; each must be listed exactly once (step 11).
IFS_NAMES=(
	.script procnto-smp-instr ldqnx-64.so.2
	libc.so.6 libgcc_s.so.1 libsecpol.so.1 libm.so.3 libqh.so.1 libregex.so.1
	libjail.so.1 libfsnotify.so.1 libsocket.so.4 libsocket.so libfdt.so.1 libfdt.so
	libcam.so.2 io-blk.so cam-disk.so libslog2.so.1 libslog2.so libslog2parse.so.1
	libslog2shim.so.1 libjson.so.1
	libz.so.2 libcrypto.so.3 libqcrypto.so.1.0 qcrypto-openssl-3.so libpci.so.3.0 qcrypto.conf
	tcu-cat stamp bwait smpcheck qnx-host-client m3-host.ksh g2.conf
	m3-fake-guest.txt guest-ifs.bin disk-qvm
	ksh pidin on slay waitfor shutdown devc-pty slogger2 slog2info pipe
	qvm qvm-check vdev-pl011.so vdev-virtio-console.so vdev-virtio-blk.so vdev-shmem.so
	devb-loopback toybox cat cp cmp grep head md5sum tail wc
)
# Deliberately absent (design §3.1).
ABSENT_NAMES=(vpctl vdev-virtio-net.so fs-qnx6.so random io-sock tracelogger traceprinter)
# SDP files the M3 additions need, relative to target/qnx/aarch64le (sizes in
# design §3.1); checked for presence before mkifs.
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
)
# The hypervisor files whose sha256 goes in the table (step 18), as mkifs resolved them.
HASHED_NAMES=(qvm qvm-check vdev-pl011.so vdev-virtio-console.so vdev-virtio-blk.so vdev-shmem.so)

# As make-m1b-images.sh:89-92.
STEP="argument parsing"
die() { echo "FAIL: $*" >&2; exit 1; }
# A command that fails without a message of its own still says where it stopped.
trap 'echo "FAIL: $STEP (line $LINENO exited non-zero)" >&2' ERR

usage() {
	echo "usage: $0 [--generate-only] [image ...]" >&2
	echo "  images: ${DEFAULT_IMAGES[*]} (default: all five, in that order)" >&2
	echo "  on demand: m3n-<rung> (no -A), m3-<rung>-p6 (-P6), m3n-<rung>-p6; rung r0 r1 r2 d1 d2" >&2
	exit 2
}

GEN_ONLY=0
IMAGES=()
for a in "$@"; do
	case "$a" in
	--generate-only) GEN_ONLY=1 ;;
	-h|--help) usage ;;
	*)
		if [[ "$a" =~ ^m3n?-(r0|r1|r2|d1|d2)(-p6)?$ ]]; then
			for b in "${IMAGES[@]}"; do
				[ "$b" != "$a" ] || { echo "image named twice: $a" >&2; usage; }
			done
			IMAGES+=("$a")
		else
			echo "unknown image or option: $a" >&2
			usage
		fi
		;;
	esac
done
[ "${#IMAGES[@]}" -gt 0 ] || IMAGES=("${DEFAULT_IMAGES[@]}")

# ---- per-image attributes (design §3.6, §3.7, §5.1) ---------------------------
rung_of() { local s="${1#m3-}"; s="${s#m3n-}"; echo "${s%-p6}"; }
cpus_of() { case "$1" in *-p6) echo 6 ;; *) echo 4 ;; esac; }
with_a()  { case "$1" in m3n-*) echo 0 ;; *) echo 1 ;; esac; }
mode_of() {
	case "$(rung_of "$1")" in
	r0) echo harness ;;
	r2) echo full ;;
	*)  echo boot ;;
	esac
}
ipc_bound_of() { if [ "$(mode_of "$1")" = harness ]; then echo 20; else echo 240; fi; }
conf_of() {
	case "$(rung_of "$1")" in
	d1) echo g2-m3-diag.conf ;;
	d2) echo g2-noblk.conf ;;
	*)  echo g2-m3.conf ;;
	esac
}
cpu_list() {
	local n="$1" i out=""
	for ((i = 0; i < n; i++)); do out="$out${out:+ }$i"; done
	echo "$out"
}
startup_line_of() {
	local a=""
	if [ "$(with_a "$1")" = 1 ]; then a=" -A"; fi
	echo "startup-$BOARD -vvv -P$(cpus_of "$1") -Q enable,el2-host -m992M -Wkeep$a -Dtcu"
}
role_of() {
	local r
	case "$(rung_of "$1")" in
	r0) r="R0, the harness: the whole M3 image except qvm, fake guest text through the pty" ;;
	r1) r="R1: first qvm launch, the guest boots with its disk to the banner, no IPC" ;;
	r2) r="R2 (Q) and T1-T5: banner plus the IPC pair" ;;
	d1) r="D1, diagnostic, never timed: qvm debug logging, unsupported instruction/register abort" ;;
	d2) r="D2, diagnostic, never timed: no guest disk; marker Startup complete" ;;
	esac
	case "$1" in *-p6) r="$r; contingency C2 at -P6" ;; esac
	case "$1" in m3n-*) r="$r; without -A (O3 declined)" ;; esac
	echo "$r"
}

# ---- helpers -------------------------------------------------------------------
sha() { sha256sum "$1" | cut -d' ' -f1; }
md5() { md5sum "$1" | cut -d' ' -f1; }

# A path mkifs (a native Windows program here) can open: E:/... on Windows.
hostpath() {
	if command -v cygpath >/dev/null 2>&1; then cygpath -m -- "$1"; else echo "$1"; fi
}

# As make-m1b-images.sh:182-184: lines equal to a given line once blanks are
# squeezed and the ends trimmed.
count_line() {
	awk -v want="$2" '{ sub(/\r$/, ""); $1 = $1 } $0 == want { c++ } END { print c + 0 }' "$1"
}

# A qvm configuration with its comment and blank lines dropped (design §3.3).
strip_conf() {
	awk '{ sub(/\r$/, "") } /^[[:space:]]*(#|$)/ { next } { print }' "$1"
}

# Literal marker substitution, never a regex, with values passed through the
# environment so awk does not process escapes in them. $1 is what to strip first:
# "hash" drops every comment line (buildfiles, as in M1b), "notes" drops only
# the template's own ## lines (the host script keeps its # header).
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

# ---- steps 1-7: record guards and input pins ------------------------------------

# Step 1.
guard_output() {
	local out_r r p
	STEP="output directory (step 1)"
	# OUT is fixed above; this catches an edit that points it at an earlier record.
	# Compared case-folded, because NTFS resolves out/M1B to out/m1b.
	out_r="$(realpath -m -- "$OUT")"
	for r in "$M1B_OUT" "$M2_OUT"; do
		r="$(realpath -m -- "$r")"
		case "${out_r,,}/" in
		"${r,,}/"*) die "output directory $OUT resolves to $out_r, inside $r, which this script must never write" ;;
		esac
	done
	command -v git >/dev/null 2>&1 || die "git is needed for the ignore checks and PO-A"
	# check-ignore answers for paths that do not exist yet.
	for p in "$OUT/x.build" "$OUT/x.ksh" "$OUT/x.ifs" "$OUT/x.kimg" "$OUT/x.procnto-smp-instr.sym" \
	         "$OUT/g2-m3.conf" "$OUT/m3-fake-guest.txt" "$GATE/x.conf" "$OUT/xtr-x/disk-qvm" \
	         "$SHIM/out/t234-qnx.kimg"; do
		git -C "$REPO" check-ignore -q -- "$p" \
			|| die "$p would not be git-ignored; fix .gitignore before building QNX images here"
	done
	mkdir -p "$OUT" "$GATE"
	echo "   output: $OUT (git-ignored, outside out/m1b/ and out/m2/): ok"
}

# Step 2.
snapshot_status() {
	STEP="git status snapshot (step 2)"
	STATUS_A="$(git -C "$REPO" status --porcelain)"
	echo "   git status --porcelain snapshot taken"
}

# Step 3. Against HEAD rather than the index, so a staged edit fails as well as an
# unstaged one; and the paths must be tracked, or the diff proves nothing.
po_a() {
	local rc=0
	STEP="PO-A (step 3)"
	git -C "$REPO" ls-files --error-unmatch -- "${PO_A_PATHS[@]}" >/dev/null 2>&1 \
		|| die "PO-A: one of ${PO_A_PATHS[*]} is not tracked by git"
	git -C "$REPO" diff --quiet HEAD -- "${PO_A_PATHS[@]}" || rc=$?
	case "$rc" in
	0) ;;
	1) die "PO-A: ${PO_A_PATHS[*]} differ from git HEAD; the earlier generators and the board code must not change under M3 (design §2 rules 4-5)" ;;
	*) die "PO-A: git diff failed (exit $rc)" ;;
	esac
	echo "   PO-A m2.build.in, make-m2-images.sh, make-m1b-images.sh and t234-orin-nano/ match git HEAD: ok"
}

check_pin() {
	local got
	[ -f "$1" ] || die "$STEP: no $1 ($3)"
	got=$(sha "$1")
	[ "$got" = "$2" ] || die "$STEP: $1 has sha256 $got, but $3 is pinned at $2"
	echo "   $STEP: $3, sha256 $got: ok"
}

# Step 4.
po_b() {
	local f
	STEP="PO-B (step 4)"
	[ -f "$STARTUP_BIN" ] \
		|| die "PO-B: no $STARTUP_BIN; set BSP=, or rebuild the M1b startup with build-board.sh (design §6.1 item 1)"
	check_pin "$STARTUP_BIN" "$PIN_STARTUP" "the M1b startup build"
	check_pin "$TOOLS/smpcheck" "$PIN_SMPCHECK" "M1b's smpcheck"
	check_pin "$CLIENT" "$PIN_CLIENT" "the IPC client"
	for f in stamp bwait; do
		if [ -f "$TOOLS/$f" ]; then
			echo "   PO-B $f: new build, sha256 $(sha "$TOOLS/$f") (recorded)"
		else
			echo "   PO-B $f: not built yet (make -C orin-native/tools); needed before mkifs"
		fi
	done
}

# Step 5: the first 24 hex digits of the kimgs M1b and M2 ran. Read only; an
# absent kimg is reported, not judged.
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
}

# Step 6.
po_d() {
	STEP="PO-D (step 6)"
	check_pin "$GUEST_IFS" "$PIN_GUEST" "the cloud-leg guest IFS"
	check_pin "$GUEST_DISK" "$PIN_DISK" "the pristine guest disk"
	GUEST_MD5=$(md5 "$GUEST_IFS")
	DISK_MD5=$(md5 "$GUEST_DISK")
	echo "   PO-D md5 for baking: guest $GUEST_MD5, disk $DISK_MD5"
}

# The single-quoted printf argument that writes g2.conf, with \n expanded (step 7.1-7.2).
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

# Step 7.
po_e() {
	local n lt gt at
	STEP="PO-E (step 7)"
	[ -f "$ASRUN_POST" ] || die "PO-E: no $ASRUN_POST; the QNX-generated host build tree is the as-run configuration's only source"
	at=$(grep -n "^printf 'system mkqnximage-guest" "$ASRUN_POST" | cut -d: -f1 | tr '\n' ' ')
	expand_printf "$ASRUN_POST" > "$GATE/asrun.conf" \
		|| die "PO-E: could not take the configuration out of $ASRUN_POST (reason above)"
	n=$(count_line "$GATE/asrun.conf" "load /data/hypervisor/guest/ifs.bin")
	[ "$n" = 1 ] || die "PO-E: the as-run configuration has $n 'load /data/hypervisor/guest/ifs.bin' lines, expected exactly 1"
	awk '$0 == "load /data/hypervisor/guest/ifs.bin" { $0 = "load /proc/boot/guest-ifs.bin" } { print }' \
		"$GATE/asrun.conf" > "$GATE/asrun-native.conf"

	[ -f "$CONF_SRC_M3" ] || die "PO-E: no $CONF_SRC_M3"
	strip_conf "$CONF_SRC_M3" > "$OUT/g2-m3.conf"
	if ! cmp -s "$GATE/asrun-native.conf" "$OUT/g2-m3.conf"; then
		diff "$GATE/asrun-native.conf" "$OUT/g2-m3.conf" >&2 || true
		die "PO-E: stripped g2-m3.conf is not the as-run configuration with only its load line substituted (compare $GATE/asrun-native.conf with $OUT/g2-m3.conf)"
	fi
	echo "   PO-E g2-m3.conf is the as-run text (post_startup.sh line ${at% }) with only the load line substituted: ok"

	[ -f "$CONF_SRC_DIAG" ] || die "PO-E: no $CONF_SRC_DIAG"
	strip_conf "$CONF_SRC_DIAG" > "$OUT/g2-m3-diag.conf"
	awk 'NR == 1 {
			print
			print "logger fatal,internal,error,warn,info,debug stderr"
			print "unsupported instruction abort"
			print "unsupported register abort"
			next
		}
		{ print }' "$OUT/g2-m3.conf" > "$GATE/diag-expected.conf"
	cmp -s "$GATE/diag-expected.conf" "$OUT/g2-m3-diag.conf" \
		|| die "PO-E: stripped g2-m3-diag.conf is not g2-m3.conf with exactly the three §3.3 lines after line 1 (compare $GATE/diag-expected.conf)"
	echo "   PO-E g2-m3-diag.conf is g2-m3.conf plus the logger and two unsupported lines after line 1: ok"

	[ -f "$CONF_SRC_NOBLK" ] || die "PO-E: no $CONF_SRC_NOBLK"
	strip_conf "$CONF_SRC_NOBLK" > "$OUT/g2-noblk.conf"
	awk '
		/^[^ \t]/ { stanza = ($1 == "vdev") ? $2 : "" }
		stanza == "virtio-blk" { blk++; next }
		stanza == "shmem"      { shm++; next }
		{ print }
		END {
			if (blk != 5 || shm != 4) {
				printf("dropped %d virtio-blk and %d shmem lines, expected 5 and 4\n", blk, shm) > "/dev/stderr"
				exit 1
			}
		}' "$OUT/g2-m3.conf" > "$GATE/noblk-expected.conf" \
		|| die "PO-E: g2-m3.conf does not carry the expected virtio-blk and shmem stanzas (reason above)"
	cmp -s "$GATE/noblk-expected.conf" "$OUT/g2-noblk.conf" \
		|| die "PO-E: stripped g2-noblk.conf is not g2-m3.conf without its five virtio-blk and four shmem lines (compare $GATE/noblk-expected.conf)"
	echo "   PO-E g2-noblk.conf is g2-m3.conf without the five virtio-blk and four shmem lines: ok"

	# Step 7.6, for the record only: against the committed three-vdev text.
	[ -f "$COMMITTED_POST" ] || die "PO-E: no $COMMITTED_POST"
	expand_printf "$COMMITTED_POST" > "$GATE/committed.conf" \
		|| die "PO-E: could not take the configuration out of $COMMITTED_POST (reason above)"
	diff "$GATE/committed.conf" "$OUT/g2-m3.conf" > "$GATE/committed-vs-g2-m3.diff" || true
	lt=$(grep -c '^< ' "$GATE/committed-vs-g2-m3.diff" || true)
	gt=$(grep -c '^> ' "$GATE/committed-vs-g2-m3.diff" || true)
	echo "   PO-E for the record: g2-m3.conf against the committed scripts/qhv/post_start.custom text:"
	sed 's/^/      /' "$GATE/committed-vs-g2-m3.diff"
	if [ "$lt" = 1 ] && [ "$gt" = 5 ] \
	   && grep -qx '< load /data/hypervisor/guest/ifs.bin' "$GATE/committed-vs-g2-m3.diff" \
	   && [ "$(grep -c '^> \(vdev shmem\| loc 0x1c0f0000\| intr gic:43\| allow phase2-rq2-probe\)$' "$GATE/committed-vs-g2-m3.diff" || true)" = 4 ]; then
		echo "   PO-E record: the load line and the four shmem lines, as the design expects"
	else
		echo "   PO-E record NOTE: the diff is not just the load line and the four shmem lines ($lt removed, $gt added)"
	fi
}

# ---- step 8: generate -------------------------------------------------------------

copy_fake() {
	STEP="harness text (step 8)"
	[ -f "$FAKE_SRC" ] || die "no $FAKE_SRC"
	awk '{ sub(/\r$/, "") } { print }' "$FAKE_SRC" > "$OUT/m3-fake-guest.txt"
	grep -q '^QNX qnx-guest HARNESS-FAKE not-a-guest$' "$OUT/m3-fake-guest.txt" \
		|| die "$FAKE_SRC lost its fake banner line"
	# The fake banner must never pass for the real one (design §3.7, §8 item 5).
	if grep -qE 'QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le' "$OUT/m3-fake-guest.txt"; then
		die "$FAKE_SRC matches the real banner pattern"
	fi
}

generate() {
	local img="$1" rung p a mode bound conf cpus build ksh body line want l c
	rung=$(rung_of "$img")
	p=$(cpus_of "$img")
	a=$(with_a "$img")
	mode=$(mode_of "$img")
	bound=$(ipc_bound_of "$img")
	conf="$OUT/$(conf_of "$img")"
	cpus=$(cpu_list "$p")
	build="$OUT/$img.build"
	ksh="$OUT/$img.ksh"
	body="$OUT/$img.build.body"
	want=$(startup_line_of "$img")
	STEP="$img: generate (step 8)"
	[ -f "$conf" ] || die "$img: no generated configuration $conf (PO-E writes it)"

	# The buildfile.
	subst hash "$BUILD_TEMPLATE" "$body" \
		RUNG="$rung" P="$p" \
		CLIENT="$(hostpath "$CLIENT")" \
		GUEST_IFS="$(hostpath "$GUEST_IFS")" \
		GUEST_DISK="$(hostpath "$GUEST_DISK")" \
		KSH="$(hostpath "$ksh")" \
		CONF="$(hostpath "$conf")" \
		FAKE="$(hostpath "$OUT/m3-fake-guest.txt")"
	if [ "$a" = 0 ]; then
		# m3n-*: the template's -A token goes, and nothing else moves.
		awk -v s="startup-$BOARD" '
			$1 == s {
				lines++
				n = 0
				for (i = 2; i <= NF; i++) if ($i == "-A") n++
				if (n != 1 || !sub(/ -A /, " ")) bad++
			}
			{ print }
			END { if (lines != 1 || bad) exit 1 }' "$body" > "$body.noA" \
			|| die "$img: could not remove exactly one -A from the one startup line"
		mv -f "$body.noA" "$body"
	fi
	{
		echo "# $img - $(role_of "$img")."
		echo "# Generated from orin-native/startup/m3.build.in by make-m3-images.sh: comment"
		echo "# lines removed, markers replaced. Edit the template, never this copy."
		echo "# No image generated from this has run on the board."
		echo "# Design: $DESIGN, sections 3.6 and 5."
		echo
		cat "$body"
	} > "$build"
	rm -f "$body"
	no_markers "$build"

	c=$(awk -v s="startup-$BOARD" '$1 == s { c++ } END { print c + 0 }' "$build")
	[ "$c" = 1 ] || die "$img: $c startup lines in $build, expected 1"
	[ "$(count_line "$build" "$want")" = 1 ] || die "$img: expected exactly one line '$want' in $build"
	c=$(awk '$1 == "display_msg" { c++ } END { print c + 0 }' "$build")
	[ "$c" = 2 ] || die "$img: $c display_msg lines in $build, expected 2"
	for l in "display_msg \"T234 M3 $rung -P$p: procnto up\"" \
	         "display_msg \"T234 M3 $rung -P$p: resetting so the log can be recovered\"" \
	         "bwait -g 900 &" "smpcheck -i -n $p" "ksh /proc/boot/m3-host.ksh" "shutdown -S reboot"; do
		[ "$(count_line "$build" "$l")" = 1 ] || die "$img: expected exactly one line '$l' in $build"
	done

	# The host script, with the startup line read back from the buildfile.
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$build")
	[ "$line" = "$want" ] || die "$img: startup line '$line' in $build is not '$want'"
	subst notes "$KSH_TEMPLATE" "$ksh" \
		RUNG="$rung" P="$p" MODE="$mode" CPUS="$cpus" IPC_BOUND="$bound" \
		STARTUP_LINE="$line" A="$a" \
		GUEST_SHA256="$PIN_GUEST" DISK_SHA256="$PIN_DISK" \
		CONF_SHA256="$(sha "$conf")" CLIENT_SHA256="$PIN_CLIENT" \
		GUEST_MD5="$GUEST_MD5" DISK_MD5="$DISK_MD5" CONF_MD5="$(md5 "$conf")"
	no_markers "$ksh"
	for l in "RUNG=$rung" "MODE=$mode" "P=$p" "CPUS=\"$cpus\"" "IPC_BOUND=$bound" \
	         "md5ok \"\$S/md5.pre\" $GUEST_MD5 guest md5_pre" \
	         "md5ok \"\$S/md5.pre\" $DISK_MD5 disk md5_pre" \
	         "md5ok \"\$S/md5.pre\" $(md5 "$conf") conf md5_pre" \
	         "md5ok \"\$S/md5.post\" $GUEST_MD5 guest md5_post" \
	         "md5ok \"\$S/md5.post\" $DISK_MD5 disk md5_post"; do
		[ "$(count_line "$ksh" "$l")" = 1 ] || die "$img: expected exactly one line '$l' in $ksh"
	done
	l="startup='$line' q=el2-host w=keep A=$a cpus=\$P guest_sha256=$PIN_GUEST disk_sha256=$PIN_DISK conf_sha256=$(sha "$conf") client_sha256=$PIN_CLIENT clock=unverified\""
	[ "$(grep -cF -- "$l" "$ksh" || true)" = 1 ] || die "$img: the CONFIG line in $ksh does not carry the image's fields"
	# Syntax only, and through bash: a proxy for the board's ksh, not proof (design R8).
	bash -n "$ksh" || die "$img: $ksh does not parse (bash -n)"

	printf '   %-12s -P%s A=%s  %-7s ipc=%-3s  %-16s %s\n' "$img" "$p" "$a" "$mode" "$bound" "$(conf_of "$img")" "$(role_of "$img")"
	printf '   %-12s build sha256 %s\n' "" "$(sha "$build")"
	printf '   %-12s ksh   sha256 %s\n' "" "$(sha "$ksh")"
}

# Step 17: every file under out/m3/ and the shim's own outputs must be ignored,
# and nothing tracked or untracked-but-visible may have changed.
tracked_guard() {
	local not_ignored now rc=0 n_in n_out f
	local list="$GATE/written.list" res="$GATE/written.check"
	STEP="tracked-path guard (step 17)"
	# Paths go to git relative to the repository: a native git cannot open the
	# /e/... form on stdin, where MSYS does not convert arguments.
	{
		find "$OUT" -type f ! -path "$list" ! -path "$res"
		for f in t234-shim.o t234-shim.elf t234-shim.bin t234-qnx.kimg; do
			[ ! -e "$SHIM/out/$f" ] || echo "$SHIM/out/$f"
		done
	} | awk -v r="$REPO/" 'index($0, r) == 1 { print substr($0, length(r) + 1); next } { print "OUTSIDE-REPO:" $0 }' > "$list"
	! grep -q '^OUTSIDE-REPO:' "$list" || die "files written outside the repository: $(grep '^OUTSIDE-REPO:' "$list")"
	git -C "$REPO" check-ignore --stdin -n -v < "$list" > "$res" || rc=$?
	# 0: some path is ignored, 1: none is; anything else is git failing.
	[ "$rc" -le 1 ] || die "git check-ignore failed (exit $rc)"
	n_in=$(wc -l < "$list")
	n_out=$(wc -l < "$res")
	[ "$n_in" -gt 0 ] && [ "$n_in" = "$n_out" ] \
		|| die "git check-ignore answered $n_out of $n_in paths (see $res)"
	not_ignored=$(awk -F'\t' '$1 == "::" { print $2 }' "$res")
	[ -z "$not_ignored" ] || die "files written here are not git-ignored: $not_ignored"
	now="$(git -C "$REPO" status --porcelain)"
	if [ "$now" != "$STATUS_A" ]; then
		diff <(printf '%s\n' "$STATUS_A") <(printf '%s\n' "$now") >&2 || true
		die "git status --porcelain changed during this run"
	fi
	echo "   $(find "$OUT" -type f | wc -l) file(s) under $OUT, all git-ignored; git status unchanged: ok"
}

# ---- steps 9-15: build and check ----------------------------------------------------

# Step 9, as make-m1b-images.sh:452-498 without the nm precondition: the startup
# is pinned by sha256 (PO-B), which is stronger.
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
		# Appended, so the SDP's own cat/cp/mkdir cannot shadow the shell's.
		export PATH="$PATH:$qhost/usr/bin"
		echo "== using SDP at $QNX_BASE"
	fi
	for t in mkifs dumpifs; do
		command -v "$t" >/dev/null || die "$t not on PATH — source qnxsdp-env or set QNX_BASE"
	done
	# mkifs resolves bare names through MKIFS_PATH and then under QNX_TARGET; our
	# startup and tools are in neither, so both directories are named, ours first.
	if command -v cygpath >/dev/null 2>&1; then
		SDP_TGT="$(cygpath -u "$QNX_TARGET")/aarch64le"
		MKIFS_PATH="$(cygpath -w "$BOARD_LE");$(cygpath -w "$TOOLS")"
	else
		SDP_TGT="$QNX_TARGET/aarch64le"
		MKIFS_PATH="$BOARD_LE:$TOOLS"
	fi
	export MKIFS_PATH
	echo "== MKIFS_PATH=$MKIFS_PATH"
	PY_BIN=""
	for t in python3 python py; do
		if command -v "$t" >/dev/null 2>&1 && "$t" -c pass >/dev/null 2>&1; then
			PY_BIN="$t"
			break
		fi
	done
	[ -n "$PY_BIN" ] || die "no working python for the startup-argument check"
}

check_inputs() {
	local f
	STEP="inputs (step 9)"
	[ -f "$STARTUP_BIN" ] || die "no $STARTUP_BIN"
	for f in tcu-cat stamp smpcheck bwait; do
		[ -f "$TOOLS/$f" ] || die "no $TOOLS/$f — run make -C orin-native/tools in the SDP environment first"
	done
	[ -f "$SHIM/build-shim.sh" ] || die "no $SHIM/build-shim.sh"
	for f in "${SDP_FILES[@]}"; do
		[ -f "$SDP_TGT/$f" ] || die "no $SDP_TGT/$f in the SDP"
	done
	echo "   inputs: startup, four tools, build-shim.sh and ${#SDP_FILES[@]} SDP files present: ok"
}

# Step 10, as make-m1b-images.sh:537-554.
build_ifs() {
	local img="$1"
	STEP="$img: mkifs (step 10)"
	# A failed mkifs must not leave an older image behind for the checks to pass.
	rm -f "$OUT/$img.ifs" "$OUT/$img.kimg"
	if ! ( cd "$OUT" && mkifs -v "$img.build" "$img.ifs" ) > "$OUT/$img.mkifs.txt" 2>&1; then
		tail -n 30 "$OUT/$img.mkifs.txt" >&2
		die "$img: mkifs failed; full output in $OUT/$img.mkifs.txt"
	fi
	[ -s "$OUT/$img.ifs" ] || die "$img: mkifs exited 0 but wrote no $img.ifs"
	# [+keeplinked] leaves procnto's linked copy in the working directory under
	# one name for every image; keep one per image.
	if [ -f "$OUT/procnto-smp-instr.sym" ]; then
		mv -f "$OUT/procnto-smp-instr.sym" "$OUT/$img.procnto-smp-instr.sym"
	fi
	echo "   mkifs: $OUT/$img.ifs ($(stat -c %s "$OUT/$img.ifs") bytes)"
}

# Step 11.
check_dumpifs() {
	local img="$1" p="$2" rung="$3" f="$OUT/$img.dumpifs.txt" s="$OUT/$img.script.txt" got name l extras
	STEP="$img: dumpifs (step 11)"
	( cd "$OUT" && dumpifs -vv "$img.ifs" ) 2>&1 | tr -d '\r' > "$f" \
		|| die "$img: dumpifs failed; see $f"
	grep -q 'compress=0 ' "$f" || die "$img: image is not uncompressed (see $f)"

	# The script as dumpifs decodes it: the indented lines under the .script
	# entry, without its gid= line and without the PATH prefix mkifs adds.
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
	[ "$got" -eq 13 ] || die "$img: dumpifs shows $got script lines, expected 13 (see $s)"
	got=$(grep -c '^display_msg ' "$s" || true)
	[ "$got" = 2 ] || die "$img: dumpifs shows $got display_msg lines, expected 2 (see $s)"
	for l in "display_msg \"T234 M3 $rung -P$p: procnto up\"" \
	         "display_msg \"T234 M3 $rung -P$p: resetting so the log can be recovered\"" \
	         "bwait -g 900 &" "slogger2" "pipe" "devc-pty" "pidin info" "smpcheck -i -n $p" \
	         "ksh /proc/boot/m3-host.ksh" "smpcheck -z 3" "shutdown -S reboot"; do
		got=$(grep -cxF -- "$l" "$s" || true)
		[ "$got" = 1 ] || die "$img: dumpifs shows $got script lines '$l', expected 1 (see $s)"
	done

	for name in "${IFS_NAMES[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 1 ] || die "$img: dumpifs lists proc/boot/$name $got time(s), expected exactly 1 (see $f)"
	done
	got=$(awk '$4 == "usr/lib/ldqnx-64.so.2" && $5 == "->" { c++ } END { print c + 0 }' "$f")
	[ "$got" = 1 ] || die "$img: dumpifs lists the usr/lib/ldqnx-64.so.2 link $got time(s), expected 1 (see $f)"
	for name in "${ABSENT_NAMES[@]}"; do
		got=$(awk -v w="proc/boot/$name" '$4 == w { c++ } END { print c + 0 }' "$f")
		[ "$got" = 0 ] || die "$img: dumpifs lists proc/boot/$name, which no M3 image may carry (see $f)"
	done
	got=$(awk '$4 ~ /\.sym$/ { c++ } END { print c + 0 }' "$f")
	[ "$got" = 0 ] || die "$img: dumpifs lists $got .sym file(s) inside the image (see $f)"
	extras=$(awk -v list="${IFS_NAMES[*]}" '
		BEGIN { n = split(list, a, " "); for (i = 1; i <= n; i++) want["proc/boot/" a[i]] = 1 }
		$4 ~ /^proc\/boot\// && !($4 in want) { printf("%s ", $4) }' "$f")
	echo "   dumpifs: uncompressed; 13 script lines with 'T234 M3 $rung -P$p', bwait -g 900 &, smpcheck -i -n $p, the host script and shutdown -S reboot; ${#IFS_NAMES[@]} names once each; ${#ABSENT_NAMES[@]} excluded names and .sym absent: ok"
	[ -z "$extras" ] || echo "   dumpifs note: entries beyond the design's list (not an error): $extras"
}

# Step 12.
check_geometry() {
	local img="$1" f="$OUT/$img.dumpifs.txt" v ip ss end
	STEP="$img: geometry (step 12)"
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
	[ "$#" = 4 ] || die "$img: could not read image_paddr, stored_size, startup_size and preboot_size from $f"
	ip="$1"; ss="$2"; STARTUP_SIZE=$(( $3 )); PREBOOT=$(( $4 ))
	[ "$ip" = 0x80082fa0 ] || die "$img: image_paddr=$ip, expected 0x80082fa0 (see $f)"
	end=$(( ip + ss ))
	[ "$end" -le $((0x8C000000)) ] \
		|| die "$img: the image ends at $(printf 0x%x "$end"), beyond 0x8c000000; it would leave less than 800 MiB of the RAM window"
	printf '   geometry: image_paddr=%s stored_size=%s, ends at 0x%x, %d MiB of the window left above it: ok\n' \
		"$ip" "$ss" "$end" $(( (0xBE000000 - end) / 1048576 ))
}

# Step 13, as make-m1b-images.sh:590-649 plus -A. The startup arguments are read
# out of the image bytes, where mkifs writes them over the startup library's
# reserved bootargs_entry (lib/aarch64/cstart.S:36-37). Only the startup region
# is read (preboot + startup_size from the startup header), so the search never
# touches the guest pair or the other QNX files further into the image.
check_startup_args() {
	local img="$1" p="$2" a="$3" line limit
	STEP="$img: startup-argument check (step 13)"
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$OUT/$img.build")
	limit=$(( PREBOOT + STARTUP_SIZE ))
	( cd "$OUT" && "$PY_BIN" - "$img.ifs" "$p" "enable,el2-host" "$a" "$line" "$limit" <<'PY'
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
print("   exactly -P%d, -Q %s and %s, and otherwise the buildfile's startup line: ok"
      % (n, q, "one -A" if want_a else "no -A"))
PY
	) || die "$img: the IFS does not carry the startup arguments it was built for"
}

# Step 14: the guest pair, the configuration and the host script, extracted back
# out of our own IFS by basename and hashed; the extraction never persists.
check_identity() {
	local img="$1" x="xtr-$img" d f want got
	d="$OUT/$x"
	STEP="$img: byte identity inside the IFS (step 14)"
	rm -rf "$d"
	mkdir -p "$d"
	if ! ( cd "$OUT" && dumpifs -x -b -d "$x" -f guest-ifs.bin -f disk-qvm -f g2.conf -f m3-host.ksh "$img.ifs" ) \
	     > "$OUT/$img.extract.txt" 2>&1; then
		rm -rf "$d"
		tail -n 20 "$OUT/$img.extract.txt" >&2
		die "$img: dumpifs -x failed; see $OUT/$img.extract.txt"
	fi
	for f in guest-ifs.bin disk-qvm g2.conf m3-host.ksh; do
		case "$f" in
		guest-ifs.bin) want="$PIN_GUEST" ;;
		disk-qvm)      want="$PIN_DISK" ;;
		g2.conf)       want=$(sha "$OUT/$(conf_of "$img")") ;;
		m3-host.ksh)   want=$(sha "$OUT/$img.ksh") ;;
		esac
		if [ ! -f "$d/$f" ]; then
			rm -rf "$d"
			die "$img: dumpifs did not extract $f from $img.ifs"
		fi
		got=$(sha "$d/$f")
		if [ "$got" != "$want" ]; then
			rm -rf "$d"
			die "$img: $f extracted from $img.ifs has sha256 $got, expected $want"
		fi
		echo "   identity: /proc/boot/$f extracted from the IFS, sha256 $got: ok"
	done
	rm -rf "$d"
}

# Step 15, as make-m1b-images.sh:651-671, plus the page-rounded image_size.
wrap() {
	local img="$1" isz ksz want_is
	STEP="$img: build-shim.sh jump (step 15)"
	# build-shim.sh writes one fixed name, t234-qnx.kimg; OUT_DIR pins its directory.
	if ! OUT_DIR="$SHIM/out" bash "$SHIM/build-shim.sh" jump "$OUT/$img.ifs" > "$OUT/$img.shim.txt" 2>&1; then
		tail -n 30 "$OUT/$img.shim.txt" >&2
		die "$img: build-shim.sh failed; full output in $OUT/$img.shim.txt"
	fi
	cp "$SHIM/out/t234-qnx.kimg" "$OUT/$img.kimg"
	isz=$(stat -c %s "$OUT/$img.ifs")
	ksz=$(stat -c %s "$OUT/$img.kimg")
	[ "$ksz" -eq $((isz + 8192)) ] || die "$img: $img.kimg is $ksz bytes, expected 8192 + $isz"
	tail -c +8193 "$OUT/$img.kimg" | cmp -s - "$OUT/$img.ifs" \
		|| die "$img: $img.kimg does not end with $img.ifs"
	want_is=$(printf '0x%x' $(( (8192 + isz + 4095) / 4096 * 4096 )))
	tr -d '\r' < "$OUT/$img.shim.txt" | grep -qE "^  image_size +$want_is +ok$" \
		|| die "$img: build-shim.sh's header check did not report image_size $want_is ok (see $OUT/$img.shim.txt)"
	echo "   wrapped: $OUT/$img.kimg ($ksz bytes = 8192 shim + $isz IFS), image_size $want_is page-rounded: ok"
}

# The host file mkifs actually took for a /proc/boot name, from its -v listing.
resolved_path() {
	local p
	p=$(awk -v k=" proc/boot/$2=" '{ sub(/\r$/, ""); i = index($0, k); if (i > 0) { print substr($0, i + length(k)); exit } }' "$1")
	[ -n "$p" ] || return 0
	if command -v cygpath >/dev/null 2>&1; then cygpath -u -- "$p"; else echo "$p"; fi
}

# ---- main ------------------------------------------------------------------------

echo "== M3 images ($DESIGN, section 5): ${IMAGES[*]}"
echo "== guards and pins (steps 1-7)"
guard_output
snapshot_status
po_a
po_b
po_c
po_d
po_e

echo "== generating into $OUT (step 8)"
copy_fake
for img in "${IMAGES[@]}"; do
	generate "$img"
done

if [ "$GEN_ONLY" = 1 ]; then
	tracked_guard
	echo "== --generate-only: stopping before mkifs; no image was built"
	exit 0
fi

setup_sdp
check_inputs
startup_sum=$(sha "$STARTUP_BIN")
smpcheck_sum=$(sha "$TOOLS/smpcheck")
stamp_sum=$(sha "$TOOLS/stamp")
bwait_sum=$(sha "$TOOLS/bwait")
client_sum=$(sha "$CLIENT")
STEP="inputs (step 9)"
[ "$startup_sum" = "$PIN_STARTUP" ] || die "$STARTUP_BIN changed after PO-B"
[ "$smpcheck_sum" = "$PIN_SMPCHECK" ] || die "$TOOLS/smpcheck changed after PO-B"
[ "$client_sum" = "$PIN_CLIENT" ] || die "$CLIENT changed after PO-B"

for img in "${IMAGES[@]}"; do
	p=$(cpus_of "$img")
	echo "== $img (-P$p, $(mode_of "$img"), $(conf_of "$img"))"
	build_ifs "$img"
	check_dumpifs "$img" "$p" "$(rung_of "$img")"
	check_geometry "$img"
	check_startup_args "$img" "$p" "$(with_a "$img")"
	check_identity "$img"
	wrap "$img"
done

# Step 16: one startup, smpcheck, stamp, bwait and client behind every image.
STEP="input stability (step 16)"
[ "$(sha "$STARTUP_BIN")" = "$startup_sum" ] || die "$STARTUP_BIN changed during this run; rebuild the images"
[ "$(sha "$TOOLS/smpcheck")" = "$smpcheck_sum" ] || die "$TOOLS/smpcheck changed during this run; rebuild the images"
[ "$(sha "$TOOLS/stamp")" = "$stamp_sum" ] || die "$TOOLS/stamp changed during this run; rebuild the images"
[ "$(sha "$TOOLS/bwait")" = "$bwait_sum" ] || die "$TOOLS/bwait changed during this run; rebuild the images"
[ "$(sha "$CLIENT")" = "$client_sum" ] || die "$CLIENT changed during this run; rebuild the images"
echo "   startup, smpcheck, stamp, bwait and client unchanged during the run: ok"

tracked_guard

# Step 18: hashes only, never contents.
STEP="sha256 table (step 18)"
echo
echo "== sha256 (the kimg is what goes to the board; sha256sum it there before kexec)"
row() { printf '%-14s %-8s %-16s %-28s %10s  %s\n' "$@"; }
row image mode configuration file bytes sha256
for img in "${IMAGES[@]}"; do
	for f in "$img.kimg" "$img.ifs" "$img.build" "$img.ksh"; do
		row "$img" "$(mode_of "$img")" "$(conf_of "$img")" "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
	done
done
for f in g2-m3.conf g2-m3-diag.conf g2-noblk.conf m3-fake-guest.txt; do
	row generated - - "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
done
row input - - "startup-$BOARD" "$(stat -c %s "$STARTUP_BIN")" "$startup_sum"
row input - - smpcheck "$(stat -c %s "$TOOLS/smpcheck")" "$smpcheck_sum"
row input - - stamp "$(stat -c %s "$TOOLS/stamp")" "$stamp_sum"
row input - - bwait "$(stat -c %s "$TOOLS/bwait")" "$bwait_sum"
row input - - qnx-host-client "$(stat -c %s "$CLIENT")" "$client_sum"
row guest - - "ifs.bin" "$(stat -c %s "$GUEST_IFS")" "$PIN_GUEST"
row guest - - "ifs.bin md5" - "$GUEST_MD5"
row guest - - "disk-qvm" "$(stat -c %s "$GUEST_DISK")" "$PIN_DISK"
row guest - - "disk-qvm md5" - "$DISK_MD5"
first="$OUT/${IMAGES[0]}.mkifs.txt"
for name in "${HASHED_NAMES[@]}"; do
	hp=$(resolved_path "$first" "$name")
	[ -n "$hp" ] && [ -f "$hp" ] || die "cannot find the host file mkifs used for $name in $first"
	for img in "${IMAGES[@]}"; do
		[ "$(resolved_path "$OUT/$img.mkifs.txt" "$name")" = "$hp" ] \
			|| die "$img took $name from a different host file than ${IMAGES[0]}"
	done
	row sdp - - "$name" "$(stat -c %s "$hp")" "$(sha "$hp")"
done
echo "   PO-A to PO-E passed before the build (top of this output)"
echo "== done: ${#IMAGES[@]} image(s) in $OUT"
