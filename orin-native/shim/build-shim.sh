#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# build-shim.sh — assemble the M0 shim and, optionally, prefix it to a QNX IFS.
# Phase 3b, docs/orin-native-port-plan.md §3.2/§6.1.  Compile-only: this script
# never talks to the board.
#
#   ./build-shim.sh [probe|hang|jump] [path/to/ifs.bin]
#
# With no IFS it writes t234-shim.kimg, the 8 KiB shim alone — that is the M0
# image.  With an IFS it writes t234-qnx.kimg = shim || ifs and patches the
# header's image_size to cover the pair, rounded up to 2 MiB.
#
# Needs the QNX SDP environment on PATH (source qnxsdp-env.sh, or run the
# Windows qnxsdp-env.bat first): ntoaarch64-gcc, ntoaarch64-ld, ntoaarch64-objcopy.
#
# The IFS must be built with [image=0x80082000] so it lands right after this
# page; see the buildfile in ../startup/ and §6.2 of the plan.
set -euo pipefail

MODE="${1:-probe}"
IFS_BIN="${2:-}"
# Resolve now, while we are still in the caller's directory: the script cds
# into the output directory later, and a relative path would then miss.
if [ -n "$IFS_BIN" ]; then
  [ -f "$IFS_BIN" ] || { echo "no such IFS: $IFS_BIN" >&2; exit 1; }
  IFS_BIN="$(cd "$(dirname "$IFS_BIN")" && pwd)/$(basename "$IFS_BIN")"
fi
LINK_ADDR=0x80080000
PAYLOAD_OFF=0x2000            # 8 KiB shim page
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT_DIR:-$HERE/out}"

case "$MODE" in
  probe) MODE_CH="'p'" ;;
  hang)  MODE_CH="'h'" ;;
  jump)  MODE_CH="'j'" ;;
  *) echo "usage: $0 [probe|hang|jump] [ifs.bin]" >&2; exit 2 ;;
esac

# The toolchain needs QNX_HOST/QNX_TARGET, and its own bin/ on PATH.  When
# qnxsdp-env has been sourced both are already right; otherwise derive them
# from QNX_BASE (default: the standard install location).  Deriving from
# `command -v` is not reliable here — a nested shell can rewrite PATH.
if [ -z "${QNX_HOST:-}" ] || [ -z "${QNX_TARGET:-}" ]; then
  QNX_BASE="${QNX_BASE:-$HOME/qnx800}"
  [ -d "$QNX_BASE" ] || { echo "no SDP at $QNX_BASE — set QNX_BASE or source qnxsdp-env" >&2; exit 1; }
  qhost="$QNX_BASE/host/win64/x86_64"
  [ -d "$qhost" ] || qhost="$QNX_BASE/host/linux/x86_64"
  qtgt="$QNX_BASE/target/qnx"
  if command -v cygpath >/dev/null 2>&1; then
    export QNX_HOST="$(cygpath -w "$qhost")"
    export QNX_TARGET="$(cygpath -w "$qtgt")"
  else
    export QNX_HOST="$qhost"
    export QNX_TARGET="$qtgt"
  fi
  # Append, never prepend: this directory ships its own cat/cp/mkdir, and a
  # Windows-native cat cannot open the MSYS-style paths used below.
  export PATH="$PATH:$qhost/usr/bin"
  echo "== using SDP at $QNX_BASE"
fi

for t in ntoaarch64-gcc ntoaarch64-ld ntoaarch64-objcopy; do
  command -v "$t" >/dev/null || { echo "$t not on PATH — source qnxsdp-env or set QNX_BASE" >&2; exit 1; }
done

mkdir -p "$OUT"
cd "$OUT"

# image_size is how many bytes the image needs from its own start; kexec
# reserves image_size + text_offset for it.  The 2 MiB figure in the kernel is
# the alignment of the *base address* it picks, not a size granularity, so
# round to a page and no further — over-reserving here would silently take
# memory the plan accounts for elsewhere.
if [ -n "$IFS_BIN" ]; then
  ifs_sz=$(stat -c %s "$IFS_BIN")
  total=$(( 0x2000 + ifs_sz ))
else
  ifs_sz=0
  total=$(( 0x2000 ))
fi
image_size=$(( (total + 0xfff) / 0x1000 * 0x1000 ))

echo "== assembling (mode=$MODE, image_size=$(printf 0x%x "$image_size"))"
ntoaarch64-gcc -c -x assembler-with-cpp \
  -DSHIM_MODE="$MODE_CH" \
  -DIMAGE_SIZE="$image_size" \
  -DLINK_ADDR="$LINK_ADDR" \
  -DPAYLOAD_OFF="$PAYLOAD_OFF" \
  -o t234-shim.o "$HERE/t234-shim.S"

ntoaarch64-ld -N -e _start -Ttext="$LINK_ADDR" --no-warn-rwx-segments -o t234-shim.elf t234-shim.o
ntoaarch64-objcopy -O binary t234-shim.elf t234-shim.bin

sz=$(stat -c %s t234-shim.bin)
if [ "$sz" -ne 8192 ]; then
  echo "FAIL: shim page is $sz bytes, expected exactly 8192" >&2
  exit 1
fi

echo "== header check"
PY_BIN=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "pass" >/dev/null 2>&1; then PY_BIN="$c"; break; fi
done
[ -n "$PY_BIN" ] || { echo "no working python for the header check" >&2; exit 1; }
"$PY_BIN" - "$image_size" <<'PY'
import struct, sys
want_image = int(sys.argv[1])
b = open("t234-shim.bin", "rb").read()
code0, code1 = struct.unpack_from("<II", b, 0)
text_off, image_sz, flags, r2, r3, r4 = struct.unpack_from("<QQQQQQ", b, 8)
magic = b[0x38:0x3c]
ok = True
def chk(name, got, want, fmt="0x%x"):
    global ok
    good = got == want
    ok &= good
    print("  %-12s %-20s %s" % (name, fmt % got if isinstance(got, int) else got,
                                "ok" if good else "EXPECTED " + (fmt % want if isinstance(want, int) else str(want))))
chk("magic", magic, b"ARM\x64", "%s")
chk("text_offset", text_off, 0x80000)
chk("image_size", image_sz, want_image)
chk("flags", flags, 0)
chk("res2/3/4", r2 | r3 | r4, 0)
print("  code0        0x%08x         (branch to shim_body)" % code0)
if not ok:
    sys.exit("header check FAILED")
print("  header ok")
PY

if [ -n "$IFS_BIN" ]; then
  cat t234-shim.bin "$IFS_BIN" > t234-qnx.kimg
  echo "== wrote $OUT/t234-qnx.kimg ($(stat -c %s t234-qnx.kimg) bytes: 8192 shim + $ifs_sz IFS)"
  echo "   IFS must have been built with [image=0x80082000]"
  sha256sum t234-qnx.kimg
else
  cp t234-shim.bin t234-shim.kimg
  echo "== wrote $OUT/t234-shim.kimg (8192 bytes, shim only — this is the M0 image)"
  sha256sum t234-shim.kimg
fi

cat <<'NOTE'

Next, on the board (nothing persistent, no reboot):
    sudo kexec -s -l t234-shim.kimg && cat /sys/kernel/kexec_loaded && sudo kexec -u
That proves the header format and the syscall path before any reboot is risked.
NOTE
