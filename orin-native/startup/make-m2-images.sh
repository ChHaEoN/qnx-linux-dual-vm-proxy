#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# make-m2-images.sh — generate, build, check and wrap the M2 images.
#
# Phase 3b, the M2 design's §3.10 and §4. Compile-only: nothing here talks to
# the board, and nothing it builds has run there.
#
#   BSP=/path/to/extracted/BSP_hyp-guest-arm_be-800_... ./make-m2-images.sh \
#       [--generate-only] [m2-p1 m2-p2 m2-p4 m2-p5 m2-p6 m2-p6t]
#
# With no names it does all six, in ladder order; name some to do a subset. For
# each image it
#   1. expands m2.build.in into out/m2/<image>.build and checks the expansion:
#      the -P, the per-CPU busy lines, the counts, and the trace lines in m2-p6t
#      only, which are the only things that differ between images;
#   2. runs mkifs into out/m2/<image>.ifs;
#   3. checks, with dumpifs, that the image holds the script and file list for
#      its N, and, in the image bytes, that its startup arguments carry exactly
#      -P<N> and are otherwise the buildfile's startup line;
#   4. wraps it with ../shim/build-shim.sh jump and copies the result to
#      out/m2/<image>.kimg, checking the copy is the shim page plus this IFS;
# and finally prints a sha256 table. It stops at the first failure.
#
# --generate-only does step 1 and nothing else. It needs no SDP, no startup and
# no smpcheck, so the buildfiles can be reviewed before any of those exist.
#
# Every output lands in orin-native/shim/out/m2/, which .gitignore covers. An
# IFS and a kimg carry QNX binaries (NCEULA), and so does the procnto .sym that
# mkifs drops beside them; none of it may reach a tracked path.
set -Eeuo pipefail

BOARD=t234-orin-nano
HERE="$(cd "$(dirname "$0")" && pwd)"
NATIVE="$(cd "$HERE/.." && pwd)"
TEMPLATE="$HERE/m2.build.in"
TOOLS="$NATIVE/tools"
SHIM="$NATIVE/shim"
OUT="$SHIM/out/m2"
BSP="${BSP:-$HOME/orin-native-port-bsp}"
BOARD_LE="$BSP/src/hardware/startup/boards/$BOARD/aarch64/le"
STARTUP_BIN="$BOARD_LE/startup-$BOARD"
ALL_IMAGES=(m2-p1 m2-p2 m2-p4 m2-p5 m2-p6 m2-p6t)

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
	m2-p1|m2-p2|m2-p4|m2-p5|m2-p6|m2-p6t) IMAGES+=("$a") ;;
	*) echo "unknown image or option: $a" >&2; usage ;;
	esac
done
[ "${#IMAGES[@]}" -gt 0 ] || IMAGES=("${ALL_IMAGES[@]}")

# m2-pN starts N CPUs; a trailing t adds the trace lines.
cpus_of()  { local n="${1#m2-p}"; echo "${n%t}"; }
trace_of() { case "$1" in *t) echo 1 ;; *) echo 0 ;; esac; }
yesno()    { if [ "$1" = 1 ]; then echo "$2"; else echo "$3"; fi; }

# How many lines of a file equal a given line once blanks are squeezed and the
# ends trimmed. Whole-line equality, so a comment that mentions a command never
# counts as the command.
count_line() {
	awk -v want="$2" '{ $1 = $1 } $0 == want { c++ } END { print c + 0 }' "$1"
}

generate() {
	local img="$1" n t out l c busy
	n=$(cpus_of "$img")
	t=$(trace_of "$img")
	out="$OUT/$img.build"
	STEP="$img: generate"

	# Marker rules are described in the template's own ## lines.
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
	' "$TEMPLATE" > "$out"

	if grep -n '@[A-Z]*@' "$out" >&2; then
		die "$img: marker left unexpanded in $out"
	fi

	local want=(
		"startup-$BOARD -vvv -P$n -Q disable -m992M -Wkeep -Dtcu"
		"display_msg \"T234 M2 -P$n: procnto up\""
		"smpcheck -i -n $n"
		"smpcheck -R $n -p /dev/shmem/m2c -T 15"
		"smpcheck -c $n -p /dev/shmem/m2c -T 90"
		"shutdown -S reboot"
		"/proc/boot/smpcheck=smpcheck"
	)
	for ((c = 0; c < n; c++)); do
		want+=("smpcheck -b 60 -C $c -o /dev/shmem/m2c$c &")
	done
	local trace_want=(
		"tracelogger -s 2 -f /dev/shmem/m2.kev &"
		"smpcheck -z 6"
		"traceprinter -f /dev/shmem/m2.kev -o /dev/shmem/m2.txt"
		"smpcheck -k /dev/shmem/m2.txt -n $n"
		"tracelogger"
		"traceprinter"
		"libtracelog.so.1"
		"libtraceparser.so.1"
	)
	for l in "${want[@]}"; do
		[ "$(count_line "$out" "$l")" = 1 ] || die "$img: expected exactly one line '$l' in $out"
	done
	for l in "${trace_want[@]}"; do
		[ "$(count_line "$out" "$l")" = "$t" ] || die "$img: expected $t line(s) '$l' in $out"
	done
	busy=$(awk '$1 == "smpcheck" && $2 == "-b" { c++ } END { print c + 0 }' "$out")
	[ "$busy" = "$n" ] || die "$img: $busy busy-worker lines in $out, expected $n"

	printf '   %-7s -P%s  %s busy workers  trace lines: %-3s -> %s\n' \
		"$img" "$n" "$busy" "$(yesno "$t" yes no)" "$out"
}

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
	for t in mkifs dumpifs; do
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

check_inputs() {
	local f
	STEP="inputs"
	[ -f "$STARTUP_BIN" ] || die "no $STARTUP_BIN — run orin-native/startup/build-board.sh with the same BSP= first"
	for f in tcu-cat stamp smpcheck; do
		[ -f "$TOOLS/$f" ] || die "no $TOOLS/$f — run make in orin-native/tools first"
	done
	[ -f "$SHIM/build-shim.sh" ] || die "no $SHIM/build-shim.sh"
}

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

check_dumpifs() {
	local img="$1" n="$2" t="$3" f="$OUT/$img.dumpifs.txt" got l
	STEP="$img: dumpifs"
	( cd "$OUT" && dumpifs -vv "$img.ifs" ) 2>&1 | tr -d '\r' > "$f" \
		|| die "$img: dumpifs failed; see $f"

	# The startup-argument check below searches the file's bytes as they are,
	# which is only meaningful for an uncompressed image; the template asks for
	# one with [-compress].
	grep -q 'compress=0 ' "$f" || die "$img: image is not uncompressed (see $f)"

	# The script mkifs compiled into the image, as dumpifs decodes it, must be
	# the one generated for N, and the file list must match the variant.
	got=$(grep -cE -- "[[:space:]]smpcheck -i -n $n\$" "$f" || true)
	[ "$got" = 1 ] || die "$img: dumpifs shows $got census lines for -n $n (see $f)"
	got=$(grep -cE -- '[[:space:]]smpcheck -b 60 -C [0-9]+ -o /dev/shmem/m2c[0-9]+ &$' "$f" || true)
	[ "$got" = "$n" ] || die "$img: dumpifs shows $got busy workers, expected $n (see $f)"
	grep -qE -- '[[:space:]]proc/boot/smpcheck$' "$f" || die "$img: no proc/boot/smpcheck in the image (see $f)"
	for l in tracelogger traceprinter libtracelog.so.1 libtraceparser.so.1; do
		got=$(grep -cE -- "[[:space:]]proc/boot/$l\$" "$f" || true)
		[ "$got" = "$t" ] || die "$img: dumpifs lists proc/boot/$l $got time(s), expected $t (see $f)"
	done
	echo "   dumpifs: uncompressed, census -n $n, $n busy workers, trace files $(yesno "$t" present absent): ok"
}

# -P is baked into the IFS, so the IFS is what gets checked, not the buildfile.
# dumpifs -vv lists the startup header and the script but not the startup's
# arguments, so they are read out of the image bytes. mkifs writes them over the
# "ddpvbskr" signature the library reserves (lib/aarch64/cstart.S:36-37) as a
# struct bootargs_entry (lib/public/sys/startup.h:320-333): size_lo, size_hi,
# argc, envc, a 32-bit shdr_addr, then argc + envc NUL-terminated strings, where
# the size counts the 8-byte head and the strings (plus a 64-bit shdr_addr when
# the 32-bit one is SHDR_ADDR_64). _main.c:79-84 walks the strings as argv.
check_startup_args() {
	local img="$1" n="$2" line
	STEP="$img: startup-argument check"
	line=$(awk -v s="startup-$BOARD" '$1 == s { $1 = $1; print }' "$OUT/$img.build")
	( cd "$OUT" && "$PY_BIN" - "$img.ifs" "$n" "$line" <<'PY'
import sys

path, n, line = sys.argv[1], int(sys.argv[2]), sys.argv[3]
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
if argv != want:
    sys.exit("startup arguments %r differ from the buildfile's %r" % (argv, want))
print("   exactly -P%d, and otherwise the buildfile's startup line: ok" % n)
PY
	) || die "$img: the IFS does not carry the startup arguments it was built for"
}

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

sha() { sha256sum "$1" | cut -d' ' -f1; }

mkdir -p "$OUT"
[ -f "$TEMPLATE" ] || die "no template at $TEMPLATE"

echo "== generating buildfiles into $OUT"
for img in "${IMAGES[@]}"; do
	generate "$img"
done

if [ "$GEN_ONLY" = 1 ]; then
	echo "== --generate-only: stopping before mkifs"
	exit 0
fi

setup_sdp
check_inputs
startup_sum=$(sha "$STARTUP_BIN")
smpcheck_sum=$(sha "$TOOLS/smpcheck")

for img in "${IMAGES[@]}"; do
	n=$(cpus_of "$img")
	t=$(trace_of "$img")
	echo "== $img (-P$n$(yesno "$t" ', trace' ''))"
	build_ifs "$img"
	check_dumpifs "$img" "$n" "$t"
	check_startup_args "$img" "$n"
	wrap "$img"
done

# One startup build and one smpcheck build behind every image (design §2 rule 2,
# §4). If either changed underneath this run, the images are not comparable.
STEP="input stability"
[ "$(sha "$STARTUP_BIN")" = "$startup_sum" ] || die "$STARTUP_BIN changed during this run; rebuild the images"
[ "$(sha "$TOOLS/smpcheck")" = "$smpcheck_sum" ] || die "$TOOLS/smpcheck changed during this run; rebuild the images"

STEP="sha256 table"
echo
echo "== sha256 (the kimg is what goes to the board; sha256sum it there before kexec)"
row() { printf '%-8s %-3s %-22s %9s  %s\n' "$@"; }
row image -P file bytes sha256
for img in "${IMAGES[@]}"; do
	n=$(cpus_of "$img")
	for f in "$img.kimg" "$img.ifs"; do
		row "$img" "$n" "$f" "$(stat -c %s "$OUT/$f")" "$(sha "$OUT/$f")"
	done
done
row input - "startup-$BOARD" "$(stat -c %s "$STARTUP_BIN")" "$startup_sum"
row input - smpcheck "$(stat -c %s "$TOOLS/smpcheck")" "$smpcheck_sum"
echo "   startup: $STARTUP_BIN"
echo "== done: ${#IMAGES[@]} image(s) in $OUT"
