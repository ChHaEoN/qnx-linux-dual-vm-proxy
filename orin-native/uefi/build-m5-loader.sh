#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# build-m5-loader.sh - build M5LOAD.EFI and run the header gate.
#
# Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §4.2 and §6.1
# step 1, with §13's decisions B (the SDP cross toolchain) and G (two link
# bases, compared by the gate). The J7a options are s1-design.md §15.13.4.
#
# USAGE
#   KIMG=orin-native/shim/out/m1b/m1b-p1.kimg \
#   KIMG_SHA256=<the pin> \
#   [T0=1] ./orin-native/uefi/build-m5-loader.sh
#
#   T0=1 embeds t0/contract-probe instead of the kimg and writes to out/t0/.
#   Nothing else differs between the two builds (§3.4 gate item 8), and no QNX
#   byte is in the T0 build at all. KIMG and KIMG_SHA256 are needed only for a
#   board build.
#
# J7a (s1-design.md §15.13.4)
#   M5L_J7A=1              compile with -DM5L_J7A and gate with --variant j7a
#                          (items 11 and 12 apply, item 8 compares J7a builds
#                          only). Build it in a worktree, never in the main
#                          checkout, whose out/ holds M5's gated loader.
#   T0=1 T0_PAD_LIKE=<kimg>  pad the contract probe to the kimg's file length
#                          and copy the kimg's image_size into the probe's
#                          header; only header bytes our shim wrote are read.
#   T0_FORCE=um6-first|um6-later  T0l only: accepted only with T0=1 and
#                          M5L_J7A=1; defines M5L_T0_FORCE. Gate item 12
#                          refuses such an image as a board build.
#   OUT_DIR=<dir>          write to <dir> instead of out/ or out/t0/ (the
#                          T0_FORCE builds use separate scratch directories).
#   COMPARE=<pe>           the other build's PE for item 8, instead of the
#                          default sibling (out/M5LOAD.EFI or out/t0/M5LOAD.EFI;
#                          none by default for a T0_FORCE build).
#
# ENVIRONMENT
#   QNX_BASE   the SDP install (default: $HOME/qnx800), as build-shim.sh
#   QNX_HOST, QNX_TARGET  derived from QNX_BASE when not already set
#
# OUTPUT, all under orin-native/uefi/out/ (or OUT_DIR), which is git-ignored
# because the board build carries QNX bytes:
#   M5LOAD.EFI      the flat PE that gets staged
#   m5load.elf      the linked ELF the gate reads
#   gate.txt        the gate's report
#
# EXIT: 0 built and gated; 1 refused or failed; 2 usage.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROG="$(basename "$0")"

die() { echo "$PROG: FAIL: $*" >&2; exit 1; }
note() { echo "$PROG: $*" >&2; }
usage() {
	echo "usage: KIMG=<path> KIMG_SHA256=<sha> [T0=1] [M5L_J7A=1] $0" >&2
	echo "       T0=1 [M5L_J7A=1] [T0_PAD_LIKE=<kimg>] [T0_FORCE=um6-first|um6-later] $0" >&2
	exit 2
}

T0="${T0:-0}"
J7A="${M5L_J7A:-0}"
T0_PAD_LIKE="${T0_PAD_LIKE:-}"
T0_FORCE="${T0_FORCE:-}"

case "$T0" in 0|1) ;; *) usage ;; esac
case "$J7A" in 0|1) ;; *) usage ;; esac

if [ "$T0" != 1 ]; then
	[ -n "${KIMG:-}" ] && [ -n "${KIMG_SHA256:-}" ] || usage
	[ -z "$T0_PAD_LIKE" ] || die "T0_PAD_LIKE is accepted only with T0=1"
	[ -z "$T0_FORCE" ] || die "T0_FORCE is accepted only with T0=1"
fi

FORCE_DEF=""
case "$T0_FORCE" in
	"") ;;
	um6-first) FORCE_DEF=1 ;;
	um6-later) FORCE_DEF=2 ;;
	*) usage ;;
esac
[ -z "$T0_FORCE" ] || [ "$J7A" = 1 ] || die "T0_FORCE needs M5L_J7A=1"

VARIANT=m5
[ "$J7A" = 1 ] && VARIANT=j7a

OUT="$HERE/out"
[ "$T0" = 1 ] && OUT="$HERE/out/t0"
[ -n "${OUT_DIR:-}" ] && OUT="$OUT_DIR"
mkdir -p "$OUT"

# ---------------------------------------------------------------- toolchain
# The same derivation as orin-native/shim/build-shim.sh; PATH is appended to,
# never prepended, so the SDP cannot shadow a host tool.
QNX_BASE="${QNX_BASE:-$HOME/qnx800}"
if [ -z "${QNX_HOST:-}" ] || [ -z "${QNX_TARGET:-}" ]; then
	[ -d "$QNX_BASE" ] || die "QNX_BASE=$QNX_BASE does not exist"
	export QNX_HOST="$QNX_BASE/host/win64/x86_64"
	export QNX_TARGET="$QNX_BASE/target/qnx"
fi
[ -d "$QNX_HOST" ] || die "QNX_HOST=$QNX_HOST does not exist"
export PATH="$PATH:$QNX_HOST/usr/bin"

CC="ntoaarch64-gcc"
LD="ntoaarch64-ld"
OBJCOPY="ntoaarch64-objcopy"
OBJDUMP="ntoaarch64-objdump"
for t in "$CC" "$LD" "$OBJCOPY" "$OBJDUMP"; do
	command -v "$t" >/dev/null 2>&1 || die "$t is not on PATH (QNX_HOST=$QNX_HOST)"
done

PY=""
for p in python3 python py; do
	if command -v "$p" >/dev/null 2>&1 &&
		"$p" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' 2>/dev/null; then
		PY="$p"
		break
	fi
done
[ -n "$PY" ] || die "no python3 on PATH"

sha_of() { "$PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }

# ---------------------------------------------------------------- the blob
if [ "$T0" = 1 ]; then
	BLOB="$OUT/contract-probe.bin"
	note "T0 build: assembling the contract probe, no QNX byte in this image"
	"$CC" -c -x assembler-with-cpp -o "$OUT/contract-probe.o" "$HERE/t0/contract-probe.S"
	"$LD" -T "$HERE/t0/contract-probe.lds" -static -nostdlib --build-id=none \
		-o "$OUT/contract-probe.elf" "$OUT/contract-probe.o"
	"$OBJCOPY" -O binary "$OUT/contract-probe.elf" "$BLOB"
	if [ -n "$T0_PAD_LIKE" ]; then
		[ -f "$T0_PAD_LIKE" ] || die "T0_PAD_LIKE=$T0_PAD_LIKE does not exist"
		cp "$BLOB" "$OUT/contract-probe-raw.bin"
		"$PY" "$HERE/t0/pad-like.py" "$OUT/contract-probe-raw.bin" "$T0_PAD_LIKE" "$BLOB" >&2 ||
			die "could not pad the probe like $T0_PAD_LIKE"
	fi
else
	BLOB="$KIMG"
	[ -f "$BLOB" ] || die "KIMG=$BLOB does not exist"
	have="$(sha_of "$BLOB")"
	[ "$have" = "$KIMG_SHA256" ] || die "KIMG sha256 $have is not the pin $KIMG_SHA256"
	note "blob pin ok: $have"
fi

# The three constants the loader compiles against, derived from the blob and
# never typed by hand: its length, its CRC32, and the image_size its own arm64
# header advertises.
CONSTS="$("$PY" "$HERE/blob-consts.py" "$BLOB")" || die "the blob is not a usable arm64 image"
read -r BLOB_LEN BLOB_CRC BLOB_IMAGE_SIZE <<<"$CONSTS"
note "blob len=$BLOB_LEN crc32=$BLOB_CRC image_size=$BLOB_IMAGE_SIZE"

{
	echo "/* Generated by $PROG: the only file that differs between the T0 build"
	echo " * and the board build (m5-design.md §3.4 gate item 8). */"
	echo "	.section .data, \"aw\""
	echo "	.align 3"
	echo "	.globl m5_blob_len"
	echo "m5_blob_len:		.quad $BLOB_LEN"
	echo "	.globl m5_blob_crc32"
	echo "m5_blob_crc32:		.quad $BLOB_CRC"
	echo "	.globl m5_blob_image_size"
	echo "m5_blob_image_size:	.quad $BLOB_IMAGE_SIZE"
	echo ""
	echo "	.section .blob, \"a\""
	echo "	.align 12"
	echo "	.globl m5_blob_start"
	echo "m5_blob_start:"
	# The assembler is a Windows tool: give it a path it can open. A Git Bash
	# absolute path like /e/... is not one, though a repo-relative path is.
	echo "	.incbin \"$(cygpath -m "$BLOB" 2>/dev/null || echo "$BLOB")\""
} > "$OUT/m5load-blob.S"

# ---------------------------------------------------------------- compile
CFLAGS="-c -O2 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie -fno-jump-tables"
CFLAGS="$CFLAGS -mcmodel=small -mstrict-align -fno-common -Wall -Wextra -Werror -std=gnu99"
# The J7a switches are appended, never inserted: with both off, the compile line
# is M5's, so the switch-off object is M5's (UM8).
[ "$J7A" = 1 ] && CFLAGS="$CFLAGS -DM5L_J7A"
[ -n "$FORCE_DEF" ] && CFLAGS="$CFLAGS -DM5L_T0_FORCE=$FORCE_DEF"

note "compiling (variant=$VARIANT${T0_FORCE:+ force=$T0_FORCE})"
# shellcheck disable=SC2086  # CFLAGS is ours and is meant to word-split
"$CC" $CFLAGS -o "$OUT/m5load.o" "$HERE/m5load.c"
"$CC" -c -x assembler-with-cpp -o "$OUT/m5load-head.o" "$HERE/m5load-head.S"
"$CC" -c -x assembler-with-cpp -o "$OUT/m5load-blob.o" "$OUT/m5load-blob.S"

link_at() {
	"$LD" -T "$HERE/m5load.lds" --defsym IMAGE_BASE="$1" -static -nostdlib \
		--build-id=none -o "$2" \
		"$OUT/m5load-head.o" "$OUT/m5load.o" "$OUT/m5load-blob.o"
}

note "linking at base 0 and at 0x100000 (gate item 6)"
link_at 0 "$OUT/m5load.elf"
link_at 0x100000 "$OUT/m5load-alt.elf"

"$OBJCOPY" -O binary "$OUT/m5load.elf" "$OUT/M5LOAD.EFI"
"$OBJCOPY" -O binary "$OUT/m5load-alt.elf" "$OUT/M5LOAD-alt.bin"

# ---------------------------------------------------------------- the gate
note "running the gate"
GATE_ARGS=(--pe "$OUT/M5LOAD.EFI" --alt "$OUT/M5LOAD-alt.bin" --elf "$OUT/m5load.elf"
	--blob "$BLOB" --blob-len "$BLOB_LEN" --blob-crc "$BLOB_CRC"
	--objdump "$(command -v "$OBJDUMP")" --out "$OUT/gate.txt")
GATE_ARGS+=(--variant "$VARIANT" --force "${T0_FORCE:-none}"
	--rules-src "$HERE/m5load-rules.h" --startup-h "$HERE/../startup/t234-orin-nano/t234_startup.h")
if [ "$T0" = 1 ]; then
	GATE_ARGS+=(--build t0)
else
	GATE_ARGS+=(--build board --blob-sha256 "$KIMG_SHA256")
fi
if [ -n "${COMPARE:-}" ]; then
	GATE_ARGS+=(--compare "$COMPARE")
elif [ -n "$T0_FORCE" ]; then
	note "T0_FORCE build: no default compare build (item 8 skips)"
elif [ "$T0" = 1 ]; then
	if [ -f "$HERE/out/M5LOAD.EFI" ]; then GATE_ARGS+=(--compare "$HERE/out/M5LOAD.EFI"); fi
else
	if [ -f "$HERE/out/t0/M5LOAD.EFI" ]; then GATE_ARGS+=(--compare "$HERE/out/t0/M5LOAD.EFI"); fi
fi

"$PY" "$HERE/m5-gate.py" "${GATE_ARGS[@]}" || die "the gate refused this build; see $OUT/gate.txt"

echo "BUILD_OK build=$([ "$T0" = 1 ] && echo t0 || echo board) variant=$VARIANT force=${T0_FORCE:-none} out=$OUT/M5LOAD.EFI sha256=$(sha_of "$OUT/M5LOAD.EFI")"
