#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# make-m1b-images.sh — generate, build, check and wrap the M1b images.
#
# Phase 3b, the M1b design's §5 (results/orin-native-port/20260909T1100Z/
# m1b-design.md, revision 2). Compile-only: nothing here talks to the board, and
# no image it builds has run there.
#
#   BSP=/path/to/extracted/BSP_hyp-guest-arm_be-800_... QNX_BASE=/path/to/qnx800 \
#       ./make-m1b-images.sh [--generate-only] [image ...]
#
# M1b re-runs M2's payload with the QNX host kept at EL2 (-Q enable,el2-host).
# There is no M1b template. m2.build.in and make-m2-images.sh are the exact
# sources of the images M2 ran; this script never edits them, never calls the M2
# generator and never writes under out/m2/ (design §2 rule 4, §5.1). Every
# buildfile here is one of M2's own expansions instead:
#   reg-pN    byte for byte the m2-pN.build M2 ran;
#   m1b-pN    that buildfile with its comment lines removed and exactly two
#   el1h-pN   things changed: the -Q token of the startup line, and the label
#             inside the two display_msg strings. A plain diff against reg-pN
#             shows it.
#
#   image    -P  -Q                run      role (design §5.2, §6.3)
#   reg-p1    1  disable           C5       bisect only, if R0 fails
#   reg-p6    6  disable           R0       -Q disable regression on M2's path
#   m1b-p1    1  enable,el2-host   R1       the plan's M1b: one core at EL2
#   m1b-p2    2  enable,el2-host   C3       bisect only, if R2 hangs naming no core
#   m1b-p4    4  enable,el2-host   C4       cluster-1 degraded fallback
#   m1b-p6    6  enable,el2-host   R2, R2b  six cores at EL2 with VHE
#   el1h-p1   1  enable,el1-host   C1       el1-host contingency, one core
#   el1h-p6   6  enable,el1-host   C2       el1-host contingency, six cores
#
# No image passes -t, so under el2-host the startup's INTID 28 probe keeps its
# default stop policy (design §4.6, §5.2).
#
# With no names it does all eight, in that order; name some to do a subset.
# Whatever is named, it first proves M2's record is intact (design §5.3):
#   1. the output directory must not resolve into out/m2/, and must be
#      git-ignored (step 1);
#   2. PO-1: m2.build.in and make-m2-images.sh match git HEAD (step 2);
#   3. PO-2: m2.build.in re-expands, for all six M2 images, into out/m1b/gate/
#      byte for byte as the buildfiles M2 ran, by pinned sha256 (step 3);
#   4. PO-3: any out/m2/*.kimg still present is the one m2-runs.md records
#      (step 4; read only).
# Then, for each named image,
#   5. reg-pN is copied from the gate and its sha256 re-checked (step 5), or
#      m1b-pN / el1h-pN is derived from the gate copy (step 6) and must differ
#      from it in the -Q token and the label and nothing else, both once those
#      are blanked out and in a raw diff of the non-comment lines (step 7);
#   6. every buildfile must carry §5.2's exact startup line and labels.
# --generate-only stops there. It needs git, awk, grep, diff, cmp, sha256sum and
# realpath (GNU, for -m in step 1), and no SDP, no startup and no smpcheck, so the
# buildfiles can be reviewed first.
#
# Without it, the script goes on:
#   7. the startup must carry the M1b board code (step 11): t234_hvt_probe and
#      t234_install_el2_vectors defined, one board_init, and not the library's;
#   8. per image: mkifs, then dumpifs and startup-argument (-P and -Q) checks
#      on the image (step 8), then ../shim/build-shim.sh jump into
#      out/m1b/<image>.kimg, checked to be the shim page plus this IFS (step 9);
#   9. the startup and smpcheck must not have changed during the run, and a
#      sha256 table is printed (step 10).
# It stops at the first failure.
#
# Everything lands in orin-native/shim/out/m1b/, which .gitignore:83 covers. An
# IFS and a kimg carry QNX binaries (NCEULA), and so does the procnto .sym that
# mkifs drops beside them; none of it may reach a tracked path.
set -Eeuo pipefail

BOARD=t234-orin-nano
HERE="$(cd "$(dirname "$0")" && pwd)"
NATIVE="$(cd "$HERE/.." && pwd)"
TEMPLATE="$HERE/m2.build.in"
TOOLS="$NATIVE/tools"
SHIM="$NATIVE/shim"
M2_OUT="$SHIM/out/m2"
OUT="$SHIM/out/m1b"
GATE="$OUT/gate"
BSP="${BSP:-$HOME/orin-native-port-bsp}"
BOARD_LE="$BSP/src/hardware/startup/boards/$BOARD/aarch64/le"
STARTUP_BIN="$BOARD_LE/startup-$BOARD"
STARTUP_MAP="$BOARD_LE/startup-$BOARD.map"
DESIGN="results/orin-native-port/20260909T1100Z/m1b-design.md"
ALL_IMAGES=(reg-p1 reg-p6 m1b-p1 m1b-p2 m1b-p4 m1b-p6 el1h-p1 el1h-p6)
M2_IMAGES=(m2-p1 m2-p2 m2-p4 m2-p5 m2-p6 m2-p6t)

# As make-m2-images.sh:45-48.
STEP="argument parsing"
die() { echo "FAIL: $*" >&2; exit 1; }
# A command that fails without a message of its own still says where it stopped.
trap 'echo "FAIL: $STEP (line $LINENO exited non-zero)" >&2' ERR

usage() {
	echo "usage: $0 [--generate-only] [image ...]" >&2
	echo "  images: ${ALL_IMAGES[*]} (default: all, in that order)" >&2
	exit 2
}

GEN_ONLY=0
IMAGES=()
for a in "$@"; do
	case "$a" in
	--generate-only) GEN_ONLY=1 ;;
	-h|--help) usage ;;
	reg-p1|reg-p6|m1b-p1|m1b-p2|m1b-p4|m1b-p6|el1h-p1|el1h-p6) IMAGES+=("$a") ;;
	*) echo "unknown image or option: $a" >&2; usage ;;
	esac
done
[ "${#IMAGES[@]}" -gt 0 ] || IMAGES=("${ALL_IMAGES[@]}")

# PO-2 pins (design §5.3 step 3): the sha256 of each buildfile make-m2-images.sh
# generated for the M2 ladder, computed from out/m2/*.build, whose kimgs are the
# ones m2-runs.md records.
m2_build_sha() {
	case "$1" in
	m2-p1)  echo 040824e3272e7f18b25e7153ff0042d0f5314eb1981efb3d3176a2f0a999443a ;;
	m2-p2)  echo 8a4d8b5816ad9bb8012e959e4e3dab27352555cc80342020f5df81953c82c99e ;;
	m2-p4)  echo 2213045eed2d4a78d889b536120635ba407d915e401b5181a582ab4f08592cb7 ;;
	m2-p5)  echo c268682d67137bb35afcab5ecf7b8459eef16a13f803cd252a8b8168ce38b10c ;;
	m2-p6)  echo 1830b690ce2722d27c319a2357f5189c3819250f84def58ae2fd610bd3acc7a8 ;;
	m2-p6t) echo 9cfe1653aeee829ffaf4b100a23b618fc9793662d4d1aca3ca8a233694cb5dff ;;
	*) die "no PO-2 pin for $1" ;;
	esac
}

# PO-3 pins (design §5.3 step 4): the first 24 hex digits of the sha256 of each
# kimg M2 ran, as m2-runs.md:23-30 records them.
m2_kimg_sha24() {
	case "$1" in
	m2-p1)  echo 1f5f1331bd2dd11d5799e82d ;;
	m2-p2)  echo 6e2ce6b76de95eac8d5260ec ;;
	m2-p4)  echo 0a4e20c2c54b1002a4a3d044 ;;
	m2-p5)  echo ca5839e104c160594b196f5a ;;
	m2-p6)  echo 5cae65e821edcdb9c2355310 ;;
	m2-p6t) echo ffbf7a08eedc8f967fb22de0 ;;
	*) die "no PO-3 pin for $1" ;;
	esac
}

# <mode>-p<N> starts N CPUs; the mode names the -Q value and the display_msg label.
cpus_of() { echo "${1##*-p}"; }
mode_of() { echo "${1%-p*}"; }
# The M2 buildfile an image is copied or derived from: the one with the same N.
src_of()  { echo "m2-p$(cpus_of "$1")"; }
q_of() {
	case "$(mode_of "$1")" in
	reg)  echo disable ;;
	m1b)  echo enable,el2-host ;;
	el1h) echo enable,el1-host ;;
	esac
}
# reg-* keep M2's label because their buildfiles are M2's, byte for byte; the
# el1-host contingency is labelled el1-host, never VHE (design §5.2).
label_of() {
	case "$(mode_of "$1")" in
	reg)  echo M2 ;;
	m1b)  echo M1b ;;
	el1h) echo M1b-el1host ;;
	esac
}
role_of() {
	case "$1" in
	reg-p1)  echo "C5, bisect only if R0 fails: M2's -P1 buildfile" ;;
	reg-p6)  echo "R0, the -Q disable regression: M2's -P6 buildfile" ;;
	m1b-p1)  echo "R1, the plan's M1b: one core at EL2 with VHE" ;;
	m1b-p2)  echo "C3, bisect only if R2 hangs naming no core: two cores at EL2 with VHE" ;;
	m1b-p4)  echo "C4, the cluster-1 degraded fallback: cluster 0 at EL2 with VHE" ;;
	m1b-p6)  echo "R2 and R2b: six cores at EL2 with VHE" ;;
	el1h-p1) echo "C1, only if INTID 28 is not usable on cpu 0: one core, el1-host" ;;
	el1h-p6) echo "C2, only after C1 passes: six cores, el1-host" ;;
	esac
}

# The M2 image names, read as make-m2-images.sh:68-70 reads them.
m2_cpus_of()  { local n="${1#m2-p}"; echo "${n%t}"; }
m2_trace_of() { case "$1" in *t) echo 1 ;; *) echo 0 ;; esac; }

# As make-m2-images.sh:73-78. How many lines of a file equal a given line once
# blanks are squeezed and the ends trimmed. Whole-line equality, so a comment
# that mentions a command never counts as the command.
count_line() {
	awk -v want="$2" '{ $1 = $1 } $0 == want { c++ } END { print c + 0 }' "$1"
}

sha() { sha256sum "$1" | cut -d' ' -f1; }

# Design §5.3 step 1.
guard_output() {
	local out_r m2_r p
	STEP="output directory"
	# OUT is fixed above; this catches an edit that points it at M2's record.
	# Compared case-folded, because NTFS resolves out/M2 to out/m2.
	out_r="$(realpath -m -- "$OUT")"
	m2_r="$(realpath -m -- "$M2_OUT")"
	case "${out_r,,}/" in
	"${m2_r,,}/"*) die "output directory $OUT resolves to $out_r, inside M2's $m2_r, which this script must never write" ;;
	esac
	# Every file written here carries QNX binaries or sits beside them, so the
	# directory must be ignored before anything lands in it. check-ignore
	# answers for paths that do not exist yet.
	command -v git >/dev/null 2>&1 || die "git is needed for the ignore check and for PO-1"
	for p in "$OUT/x.build" "$OUT/x.ifs" "$OUT/x.kimg" "$OUT/x.procnto-smp-instr.sym" "$GATE/x.build"; do
		git -C "$HERE" check-ignore -q -- "$p" \
			|| die "$p would not be git-ignored; fix .gitignore before building QNX images here"
	done
	echo "   output: $OUT (git-ignored, outside out/m2/): ok"
}

# Design §5.3 step 2. Against HEAD rather than the index, so a staged edit fails
# as well as an unstaged one; and both files must be tracked, or the diff proves
# nothing.
po1() {
	local rc=0
	STEP="PO-1"
	git -C "$HERE" ls-files --error-unmatch -- m2.build.in make-m2-images.sh >/dev/null 2>&1 \
		|| die "PO-1: m2.build.in or make-m2-images.sh is not tracked by git"
	git -C "$HERE" diff --quiet HEAD -- m2.build.in make-m2-images.sh || rc=$?
	case "$rc" in
	0) ;;
	1) die "PO-1: m2.build.in or make-m2-images.sh differs from git HEAD; M2's record must not be edited (design §2 rule 4)" ;;
	*) die "PO-1: git diff failed (exit $rc)" ;;
	esac
	echo "   PO-1 m2.build.in and make-m2-images.sh match git HEAD: ok"
}

# make-m2-images.sh:80-99, its generate() reduced to the expansion itself. The awk
# is copied verbatim, with n and trace set as its cpus_of/trace_of set them.
expand_m2() {
	local img="$1" n t
	n=$(m2_cpus_of "$img")
	t=$(m2_trace_of "$img")
	awk -v n="$n" -v trace="$t" '
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
	' "$TEMPLATE" > "$GATE/$img.build"
}

# Design §5.3 step 3: all six, whichever images were named.
po2() {
	local img got want
	STEP="PO-2"
	[ -f "$TEMPLATE" ] || die "no template at $TEMPLATE"
	mkdir -p "$GATE"
	for img in "${M2_IMAGES[@]}"; do
		expand_m2 "$img"
		got=$(sha "$GATE/$img.build")
		want=$(m2_build_sha "$img")
		[ "$got" = "$want" ] \
			|| die "PO-2: $GATE/$img.build has sha256 $got, but the $img.build M2 ran has $want"
		echo "   PO-2 $img.build re-expands byte for byte (sha256 $got): ok"
	done
}

# Design §5.3 step 4. Read only: a kimg that is absent is reported, not judged.
po3() {
	local img f got want
	STEP="PO-3"
	for img in "${M2_IMAGES[@]}"; do
		f="$M2_OUT/$img.kimg"
		if [ ! -e "$f" ]; then
			echo "   PO-3 $img.kimg: absent, not checked"
			continue
		fi
		got=$(sha "$f" | cut -c1-24)
		want=$(m2_kimg_sha24 "$img")
		[ "$got" = "$want" ] \
			|| die "PO-3: $f sha256 begins $got, but the $img.kimg M2 ran begins $want (m2-runs.md); something rebuilt M2's images"
		echo "   PO-3 $img.kimg sha256 begins $got, the image M2 ran: ok"
	done
}

# Design §5.3 step 5.
make_reg() {
	local img="$1" src out
	src=$(src_of "$img")
	out="$OUT/$img.build"
	STEP="$img: copy"
	cp "$GATE/$src.build" "$out"
	[ "$(sha "$out")" = "$(m2_build_sha "$src")" ] \
		|| die "$img: $out is not byte for byte the $src.build M2 ran"
}

# Design §5.3 step 6: one awk pass over the gate copy, behind a generated header.
derive() {
	local img="$1" src q label n in out tmp
	src=$(src_of "$img")
	q=$(q_of "$img")
	label=$(label_of "$img")
	n=$(cpus_of "$img")
	in="$GATE/$src.build"
	out="$OUT/$img.build"
	tmp="$OUT/$img.build.tmp"
	STEP="$img: derive"
	{
		echo "# $img - $(role_of "$img")."
		echo "# M2's -P$n payload under -Q $q."
		echo "#"
		echo "# Derived from $src.build"
		echo "# (sha256 $(m2_build_sha "$src"))"
		echo "# by make-m1b-images.sh: comments removed, -Q and the display_msg label changed,"
		echo "# nothing else. Edit the generator, never this copy."
		echo "# Per-line rationale: orin-native/startup/m2.build.in."
		echo "# No image generated from this has run on the board."
		echo "# Design: $DESIGN, section 5."
	} > "$tmp"
	# 1. Every comment line goes; mkifs compiles none of them into the image
	#    (design §2 rule 3). Blank lines stay.
	# 2. On the startup line, the disable after -Q becomes the image's value, in
	#    place, so nothing else on the line moves. Exactly one such line with
	#    exactly one -Q, or it stops.
	# 3. In display_msg lines, "T234 M2 -P becomes "T234 <label> -P. Exactly two
	#    replacements, or it stops.
	if ! awk -v board="startup-$BOARD" -v q="$q" \
	         -v from="\"T234 M2 -P" -v to="\"T234 $label -P" '
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
	' "$in" >> "$tmp"; then
		rm -f "$tmp"
		die "$img: could not derive it from $in (reason above)"
	fi
	mv -f "$tmp" "$out"
}

# Comment lines dropped, nothing else touched.
strip_comments() {
	awk '{ sub(/\r$/, "") } /^[[:space:]]*#/ { next } { print }' "$1"
}

# The same, with the two things a derived buildfile may change blanked out: the
# argument after -Q on the startup line, and the label in a display_msg string.
# Written apart from derive() on purpose, so the gate is not derive() checking
# its own work.
normalise() {
	awk -v board="startup-$BOARD" '
		{ sub(/\r$/, "") }
		/^[[:space:]]*#/ { next }
		$1 == board { gsub(/ -Q [^ ]+/, " -Q <Q>") }
		$1 == "display_msg" { gsub(/"T234 [^ "]+ -P/, "\"T234 <MS> -P") }
		{ print }
	' "$1"
}

# Design §5.3 step 7, the one-variable gate. The working files stay in gate/ as
# the evidence: <image>.src.norm and <image>.norm, and <image>.diff.
one_variable_gate() {
	local img="$1" src d rc old new other s_old s_new m_old m_new
	src=$(src_of "$img")
	d="$GATE/$img"
	STEP="$img: one-variable gate"

	normalise "$GATE/$src.build" > "$d.src.norm"
	normalise "$OUT/$img.build" > "$d.norm"
	cmp -s "$d.src.norm" "$d.norm" \
		|| die "$img: with -Q and the label blanked out, $img.build is not $src.build (compare $d.src.norm with $d.norm)"

	strip_comments "$GATE/$src.build" > "$d.src.nc"
	strip_comments "$OUT/$img.build" > "$d.nc"
	rc=0
	diff "$d.src.nc" "$d.nc" > "$d.diff" || rc=$?
	[ "$rc" -le 1 ] || die "$img: diff failed (exit $rc)"
	old=$(grep -c '^< ' "$d.diff" || true)
	new=$(grep -c '^> ' "$d.diff" || true)
	# Change hunks only: a line added or removed would appear as NaN or NdN.
	other=$(grep -cvE '^([<>] |---$|[0-9]+(,[0-9]+)?c[0-9]+(,[0-9]+)?$)' "$d.diff" || true)
	s_old=$(awk -v s="startup-$BOARD" '$1 == "<" && $2 == s { c++ } END { print c + 0 }' "$d.diff")
	s_new=$(awk -v s="startup-$BOARD" '$1 == ">" && $2 == s { c++ } END { print c + 0 }' "$d.diff")
	m_old=$(awk '$1 == "<" && $2 == "display_msg" { c++ } END { print c + 0 }' "$d.diff")
	m_new=$(awk '$1 == ">" && $2 == "display_msg" { c++ } END { print c + 0 }' "$d.diff")
	if [ "$old" != 3 ] || [ "$new" != 3 ] || [ "$other" != 0 ] ||
	   [ "$s_old" != 1 ] || [ "$s_new" != 1 ] || [ "$m_old" != 2 ] || [ "$m_new" != 2 ]; then
		cat "$d.diff" >&2
		die "$img: the non-comment diff against $src.build must change exactly the startup line and the two display_msg lines (see $d.diff)"
	fi
	echo "   gate: $img vs $src.build: identical with -Q and label blanked; raw diff changes exactly the startup and two display_msg lines: ok"
}

# §5.2's exact startup line and labels, for every image, copied or derived.
check_lines() {
	local img="$1" n q label out l c
	n=$(cpus_of "$img")
	q=$(q_of "$img")
	label=$(label_of "$img")
	out="$OUT/$img.build"
	STEP="$img: startup line and labels"
	local want=(
		"startup-$BOARD -vvv -P$n -Q $q -m992M -Wkeep -Dtcu"
		"display_msg \"T234 $label -P$n: procnto up\""
		"display_msg \"T234 $label -P$n: resetting so the log can be recovered\""
	)
	for l in "${want[@]}"; do
		[ "$(count_line "$out" "$l")" = 1 ] || die "$img: expected exactly one line '$l' in $out"
	done
	c=$(awk -v s="startup-$BOARD" '$1 == s { c++ } END { print c + 0 }' "$out")
	[ "$c" = 1 ] || die "$img: $c startup lines in $out, expected 1"
	c=$(awk '$1 == "display_msg" { c++ } END { print c + 0 }' "$out")
	[ "$c" = 2 ] || die "$img: $c display_msg lines in $out, expected 2"
}

generate() {
	local img="$1" src how
	src=$(src_of "$img")
	case "$(mode_of "$img")" in
	reg)
		make_reg "$img"
		how="byte for byte $src.build"
		;;
	*)
		derive "$img"
		one_variable_gate "$img"
		how="derived from $src.build"
		;;
	esac
	check_lines "$img"
	printf '   %-8s -P%s  -Q %-15s  %s\n' "$img" "$(cpus_of "$img")" "$(q_of "$img")" "$(role_of "$img")"
	printf '   %-8s %s, sha256 %s\n' "" "$how" "$(sha "$OUT/$img.build")"
}

# As make-m2-images.sh:140-186, plus ntoaarch64-nm for the symbol precondition.
setup_sdp() {
	local t
	STEP="SDP environment"
	# The tools need QNX_HOST/QNX_TARGET and the SDP's bin on PATH; qnxsdp-env
	# normally sets them. Derived from QNX_BASE otherwise, the way build-board.sh
	# and ../shim/build-shim.sh do it, and appended rather than prepended so the
	# SDP's own cat/cp/mkdir cannot shadow the shell's.
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

	# mkifs resolves bare file names through MKIFS_PATH and then under
	# QNX_TARGET. Our startup and tools are in neither the SDP nor each other's
	# directory, so both directories are named, ours first.
	if command -v cygpath >/dev/null 2>&1; then
		MKIFS_PATH="$(cygpath -w "$BOARD_LE");$(cygpath -w "$TOOLS")"
	else
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

# As make-m2-images.sh:188-196.
check_inputs() {
	local f
	STEP="inputs"
	[ -f "$STARTUP_BIN" ] || die "no $STARTUP_BIN — run orin-native/startup/build-board.sh with the same BSP= first"
	for f in tcu-cat stamp smpcheck; do
		[ -f "$TOOLS/$f" ] || die "no $TOOLS/$f — run make in orin-native/tools first"
	done
	[ -f "$SHIM/build-shim.sh" ] || die "no $SHIM/build-shim.sh"
}

# Design §5.3 step 11, repeating build-board.sh's symbol gate (design §3.9) so that
# no image is built from a startup that skipped it. nm on our own linked startup
# only; nothing is disassembled.
check_symbols() {
	local syms s c
	STEP="symbol precondition"
	syms=$(ntoaarch64-nm "$STARTUP_BIN") || die "ntoaarch64-nm failed on $STARTUP_BIN"
	for s in t234_install_el2_vectors t234_hvt_probe; do
		c=$(printf '%s\n' "$syms" | awk -v s="$s" '$NF == s && $(NF-1) ~ /^[TtW]$/ { c++ } END { print c + 0 }')
		[ "$c" = 1 ] || die "$STARTUP_BIN defines $s $c time(s), expected 1: rebuild it with the M1b board code (build-board.sh)"
	done
	c=$(printf '%s\n' "$syms" | awk '$NF == "board_init" && $(NF-1) ~ /[TtWD]/ { c++ } END { print c + 0 }')
	[ "$c" = 1 ] || die "$STARTUP_BIN defines board_init $c time(s), expected 1"
	# One definition does not say whose. A startup linked without the board's
	# override defines board_init exactly once too, from the library's empty
	# member (lib/board_init.c:28-34), and then CPU0 keeps the shim's EL2 vectors
	# (design §3.9). The link map names every archive member it pulled in, so the
	# library's must not be among them.
	[ -f "$STARTUP_MAP" ] || die "no link map at $STARTUP_MAP; build-board.sh's link writes it beside the startup"
	if grep -q 'libstartup\.a(board_init\.o)' "$STARTUP_MAP"; then
		die "$STARTUP_MAP pulled in libstartup.a(board_init.o): the linked board_init is the library's empty one, not the board's"
	fi
	echo "   symbols: t234_install_el2_vectors and t234_hvt_probe defined, one board_init and not the library's: ok"
}

# As make-m2-images.sh:198-215.
build_ifs() {
	local img="$1"
	STEP="$img: mkifs"
	# A failed mkifs must not leave an older image behind for the checks to pass.
	rm -f "$OUT/$img.ifs"
	if ! ( cd "$OUT" && mkifs -v "$img.build" "$img.ifs" ) > "$OUT/$img.mkifs.txt" 2>&1; then
		tail -n 30 "$OUT/$img.mkifs.txt" >&2
		die "$img: mkifs failed; full output in $OUT/$img.mkifs.txt"
	fi
	[ -s "$OUT/$img.ifs" ] || die "$img: mkifs exited 0 but wrote no $img.ifs"
	# [+keeplinked] leaves procnto's linked copy in the working directory under
	# the same name for every image; keep one per image so none is mistaken for
	# another's.
	if [ -f "$OUT/procnto-smp-instr.sym" ]; then
		mv -f "$OUT/procnto-smp-instr.sym" "$OUT/$img.procnto-smp-instr.sym"
	fi
	echo "   mkifs: $OUT/$img.ifs ($(stat -c %s "$OUT/$img.ifs") bytes)"
}

# As make-m2-images.sh:217-240 for an image without the trace lines, plus the
# display_msg labels (design §5.3 step 8).
check_dumpifs() {
	local img="$1" n="$2" label="$3" f="$OUT/$img.dumpifs.txt" got l
	STEP="$img: dumpifs"
	( cd "$OUT" && dumpifs -vv "$img.ifs" ) 2>&1 | tr -d '\r' > "$f" \
		|| die "$img: dumpifs failed; see $f"

	# The startup-argument check below searches the file's bytes as they are,
	# which is only meaningful for an uncompressed image; the buildfile asks for
	# one with [-compress].
	grep -q 'compress=0 ' "$f" || die "$img: image is not uncompressed (see $f)"

	# The script mkifs compiled into the image, as dumpifs decodes it, must be
	# M2's script for N, and the file list must be M2's without the trace files.
	got=$(grep -cE -- "[[:space:]]smpcheck -i -n $n\$" "$f" || true)
	[ "$got" = 1 ] || die "$img: dumpifs shows $got census lines for -n $n (see $f)"
	got=$(grep -cE -- '[[:space:]]smpcheck -b 60 -C [0-9]+ -o /dev/shmem/m2c[0-9]+ &$' "$f" || true)
	[ "$got" = "$n" ] || die "$img: dumpifs shows $got busy workers, expected $n (see $f)"
	grep -qE -- '[[:space:]]proc/boot/smpcheck$' "$f" || die "$img: no proc/boot/smpcheck in the image (see $f)"
	for l in tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1; do
		got=$(grep -cE -- "[[:space:]]proc/boot/$l\$" "$f" || true)
		[ "$got" = 0 ] || die "$img: dumpifs lists proc/boot/$l $got time(s); no M1b image carries the trace files (see $f)"
	done

	# Both display_msg lines of the compiled script, and no others, carry this
	# image's label. The black box is read by these strings (design §8).
	got=$(grep -cE -- '^[[:space:]]+display_msg ' "$f" || true)
	[ "$got" = 2 ] || die "$img: dumpifs shows $got display_msg lines, expected 2 (see $f)"
	got=$(grep -cE -- "^[[:space:]]+display_msg \"T234 $label -P$n: " "$f" || true)
	[ "$got" = 2 ] || die "$img: dumpifs shows $got display_msg lines labelled 'T234 $label -P$n', expected 2 (see $f)"
	echo "   dumpifs: uncompressed, census -n $n, $n busy workers, trace files absent, both display_msg lines 'T234 $label -P$n': ok"
}

# As make-m2-images.sh:242-294, plus the -Q check of design §5.3 step 8.
# -P and -Q are baked into the IFS, so the IFS is what gets checked, not the
# buildfile. dumpifs -vv lists the startup header and the script but not the
# startup's arguments, so they are read out of the image bytes. mkifs writes them
# over the "ddpvbskr" signature the library reserves (lib/aarch64/cstart.S:36-37)
# as a struct bootargs_entry (lib/public/sys/startup.h:320-333): size_lo, size_hi,
# argc, envc, a 32-bit shdr_addr, then argc + envc NUL-terminated strings, where
# the size counts the 8-byte head and the strings (plus a 64-bit shdr_addr when
# the 32-bit one is SHDR_ADDR_64). _main.c:79-84 walks the strings as argv.
check_startup_args() {
	local img="$1" n="$2" q="$3" line
	STEP="$img: startup-argument check"
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$OUT/$img.build")
	( cd "$OUT" && "$PY_BIN" - "$img.ifs" "$n" "$q" "$line" <<'PY'
import sys

path, n, q, line = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
want = line.split()
name = want[0].encode("ascii")
nul = bytes([0])
data = open(path, "rb").read()

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
    sys.exit("found %d well-formed startup argument blocks for %s in %s, expected exactly 1"
             % (len(entries), want[0], path))
off, argc, envc, shdr, argv = entries[0]
print("   bootargs_entry at file offset 0x%x: argc=%d envc=%d shdr_addr=0x%08x"
      % (off, argc, envc, shdr))
print("   startup arguments in the IFS: " + " ".join(argv))
p_args = [a for a in argv[1:] if a.startswith("-P")]
if p_args != ["-P%d" % n]:
    sys.exit("startup -P arguments are %r, expected exactly ['-P%d']" % (p_args, n))
# Exactly one -Q, as its own argument, followed by this image's value.
q_args = [a for a in argv[1:] if a.startswith("-Q")]
q_vals = [argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] == "-Q"]
if q_args != ["-Q"] or q_vals != [q]:
    sys.exit("startup -Q arguments are %r with values %r, expected exactly ['-Q'] with [%r]"
             % (q_args, q_vals, q))
if argv != want:
    sys.exit("startup arguments %r differ from the buildfile's %r" % (argv, want))
print("   exactly -P%d and -Q %s, and otherwise the buildfile's startup line: ok" % (n, q))
PY
	) || die "$img: the IFS does not carry the startup arguments it was built for"
}

# As make-m2-images.sh:296-315.
wrap() {
	local img="$1" isz ksz
	STEP="$img: build-shim.sh jump"
	# build-shim.sh writes one fixed name, t234-qnx.kimg, into its output
	# directory. OUT_DIR pins that directory, so the copy reads the file this
	# call wrote even if the caller's environment points OUT_DIR elsewhere.
	if ! OUT_DIR="$SHIM/out" bash "$SHIM/build-shim.sh" jump "$OUT/$img.ifs" > "$OUT/$img.shim.txt" 2>&1; then
		tail -n 30 "$OUT/$img.shim.txt" >&2
		die "$img: build-shim.sh failed; full output in $OUT/$img.shim.txt"
	fi
	cp "$SHIM/out/t234-qnx.kimg" "$OUT/$img.kimg"
	# The copy must be the 8 KiB shim page followed by this IFS and nothing else;
	# a stale t234-qnx.kimg from an earlier build fails here.
	isz=$(stat -c %s "$OUT/$img.ifs")
	ksz=$(stat -c %s "$OUT/$img.kimg")
	[ "$ksz" -eq $((isz + 8192)) ] || die "$img: $img.kimg is $ksz bytes, expected 8192 + $isz"
	tail -c +8193 "$OUT/$img.kimg" | cmp -s - "$OUT/$img.ifs" \
		|| die "$img: $img.kimg does not end with $img.ifs"
	echo "   wrapped: $OUT/$img.kimg ($ksz bytes = 8192 shim + $isz IFS)"
}

echo "== M2's record (design §5.3 steps 1-4)"
guard_output
po1
po2
po3

echo "== buildfiles into $OUT (design §5.3 steps 5-7)"
for img in "${IMAGES[@]}"; do
	generate "$img"
done

if [ "$GEN_ONLY" = 1 ]; then
	echo "== --generate-only: stopping before mkifs; no image was built"
	exit 0
fi

setup_sdp
check_inputs
# Hashed before the symbol check, so the startup it passes is the one the
# stability check below compares against.
startup_sum=$(sha "$STARTUP_BIN")
smpcheck_sum=$(sha "$TOOLS/smpcheck")
check_symbols

for img in "${IMAGES[@]}"; do
	n=$(cpus_of "$img")
	q=$(q_of "$img")
	echo "== $img (-P$n -Q $q)"
	build_ifs "$img"
	check_dumpifs "$img" "$n" "$(label_of "$img")"
	check_startup_args "$img" "$n" "$q"
	wrap "$img"
done

# As make-m2-images.sh:347-351. One startup build and one smpcheck build behind
# every image (M1b design §2 rule 3). If either changed underneath this run, the
# images are not comparable.
STEP="input stability"
[ "$(sha "$STARTUP_BIN")" = "$startup_sum" ] || die "$STARTUP_BIN changed during this run; rebuild the images"
[ "$(sha "$TOOLS/smpcheck")" = "$smpcheck_sum" ] || die "$TOOLS/smpcheck changed during this run; rebuild the images"

# As make-m2-images.sh:353-367, with the -Q column.
STEP="sha256 table"
echo
echo "== sha256 (the kimg is what goes to the board; sha256sum it there before kexec)"
row() { printf '%-8s %-3s %-16s %-22s %9s  %s\n' "$@"; }
row image -P -Q file bytes sha256
for img in "${IMAGES[@]}"; do
	n=$(cpus_of "$img")
	q=$(q_of "$img")
	for f in "$img.kimg" "$img.ifs"; do
		row "$img" "$n" "$q" "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
	done
done
row input - - "startup-$BOARD" "$(stat -c %s "$STARTUP_BIN")" "$startup_sum"
row input - - smpcheck "$(stat -c %s "$TOOLS/smpcheck")" "$smpcheck_sum"
echo "   startup: $STARTUP_BIN"
echo "   PO-1, PO-2 and PO-3 passed before the build (top of this output)"
echo "== done: ${#IMAGES[@]} image(s) in $OUT"
