#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# build-qemu-virt.sh — build startup-qemu-virt from this repo's own board.
#
# A sibling of build-board.sh rather than a parameterisation of it. That script
# is the working t234-orin-nano path and its symbol gate checks Tegra-only
# symbols (display_char_tcu, t234_ap_entry, ...) that this board will never
# define; making one script serve both would either weaken that gate or break
# it. The staging and toolchain logic below is deliberately the same shape, so
# a fix to one is easy to carry to the other.
#
#   BSP=/path/to/extracted/BSP_hyp-guest-arm_be-800_* ./build-qemu-virt.sh
#
# WHAT THIS PRODUCES AND WHY
#
# The SDP ships startup-qemu-virt as a binary but not its board source, so the
# shipped one cannot be relinked with the compiler flag that removes the
# instruction KVM cannot emulate. This builds a replacement from qemu-virt/
# against a library rebuilt with that flag.
#
# 2026-09-18: the product of this script boots under KVM on the Orin Nano,
# where the shipped startup hangs on the same launch line. See the findings
# log entry of that date; this script still only builds and checks, and the
# boot evidence comes from the board, not from here.
set -euo pipefail

BOARD=qemu-virt
HERE="$(cd "$(dirname "$0")" && pwd)"
BSP="${BSP:-$HOME/orin-native-port-bsp}"
STARTUP="$BSP/src/hardware/startup"

[ -d "$STARTUP/lib" ] || {
	echo "no BSP startup tree at $STARTUP" >&2
	echo "set BSP=/path/to/extracted/BSP_hyp-guest-arm_be-800_*" >&2
	exit 1
}

if [ -z "${QNX_HOST:-}" ] || [ -z "${QNX_TARGET:-}" ]; then
	QNX_BASE="${QNX_BASE:-$HOME/qnx800}"
	[ -d "$QNX_BASE" ] || { echo "no SDP at $QNX_BASE — set QNX_BASE or source qnxsdp-env" >&2; exit 1; }
	qhost="$QNX_BASE/host/win64/x86_64"
	[ -d "$qhost" ] || qhost="$QNX_BASE/host/linux/x86_64"
	if command -v cygpath >/dev/null 2>&1; then
		export QNX_HOST="$(cygpath -w "$qhost")"
		export QNX_TARGET="$(cygpath -w "$QNX_BASE/target/qnx")"
	else
		export QNX_HOST="$qhost"
		export QNX_TARGET="$QNX_BASE/target/qnx"
	fi
	export PATH="$PATH:$qhost/usr/bin"
	export MAKEFLAGS="-I$QNX_BASE/target/qnx/usr/include"
	echo "== using SDP at $QNX_BASE"
fi

# ---------------------------------------------------------------- the fix
#
# -fno-auto-inc-dec on the library's aarch64 build. This is the entire point of
# the exercise: it turns the writeback MMIO store in gic_v3.c
#
#     str  w3, [x0], #4        <- address written back, ISS not valid (ISV=0)
#
# into a plain offset form
#
#     add  x0, x0, #4
#     stur w3, [x0, #-4]       <- ISV=1, KVM's vgic MMIO path can decode it
#
# with the same addresses, values and iteration count. Recorded in
# docs/findings.md (2026-09-08, compile-verified: writeback-store count 4 -> 0).
#
# Applied as an edit rather than a patch file because it appends to a variable
# the BSP already uses for exactly this class of thing — the neighbouring
# -fno-store-merging is the BSP's own codegen control — so there is no context
# to keep in sync. Idempotent, and it refuses to proceed silently if the line it
# expects is not there.
CMK="$STARTUP/lib/common.mk"
if grep -q 'fno-auto-inc-dec' "$CMK"; then
	echo "== -fno-auto-inc-dec already in $(basename "$CMK")"
elif grep -q '^CCFLAGS_aarch64 += ' "$CMK"; then
	sed -i 's/^\(CCFLAGS_aarch64 += .*\)$/\1 -fno-auto-inc-dec/' "$CMK"
	echo "== added -fno-auto-inc-dec to CCFLAGS_aarch64"
	grep -n 'CCFLAGS_aarch64' "$CMK" | sed 's/^/   /'
else
	echo "CCFLAGS_aarch64 line not found in $CMK — the BSP layout changed;" >&2
	echo "do not proceed, the fix would silently not be applied" >&2
	exit 1
fi

# The same bounded-rwp change build-board.sh applies, for the same reason: an
# unbounded spin in the GIC wait is unrecoverable, and this board has no
# watchdog behind it either.
GICH="$STARTUP/lib/public/aarch64/gic.h"
if [ -f "$GICH" ] && ! grep -q __rwp_limit "$GICH"; then
	echo "== bounding wait_for_rwp (patches/gic-bounded-rwp.patch)"
	git apply --directory="$(cd "$STARTUP/../../.." && pwd)" \
	          "$HERE/patches/gic-bounded-rwp.patch" 2>/dev/null \
	  || echo "   git apply did not take; patch it by hand or see the patch header" >&2
fi

echo "== staging $BOARD into the BSP tree"
rm -rf "${STARTUP:?}/boards/$BOARD"
mkdir -p "$STARTUP/boards/$BOARD"
cp -r "$HERE/$BOARD/." "$STARTUP/boards/$BOARD/"

# The library must be built and installed before the board: `make hinstall`
# alone leaves out asmoff.def, which the callout assembly includes.
#
# The flag above changes the library's code generation, so a library built
# before it was added would link cleanly and still carry the instruction this
# whole exercise removes. The install must therefore be newer than the flag —
# but it must NOT be rebuilt blindly on every run either, because on Windows
# the install step only works from PowerShell/cmd: under Git Bash the SDK's
# qnx_cp wrapper loses its second argument and mkdir/cp die with "missing
# operand" (build-board.sh documents the same trap). An earlier version of this
# script forced `make clean` every time and so destroyed a good library it could
# not then rebuild.
#
# So: verify rather than rebuild. If the installed library predates the flag, or
# is absent, say exactly what to run and stop.
LIBA="$BSP/install/aarch64le/usr/lib/libstartup.a"
ASMOFF="$BSP/install/usr/include/aarch64/asmoff.def"
GICO="$(find "$STARTUP/lib" -name 'gic_v3.o' 2>/dev/null | head -1)"

need_lib=0
[ -f "$LIBA" ] && [ -f "$ASMOFF" ] || need_lib=1
if [ "$need_lib" = "0" ] && [ -n "$GICO" ] && [ "$GICO" -nt "$LIBA" ]; then
	need_lib=1   # objects newer than the archive: a partial rebuild happened
fi

if [ "$need_lib" = "1" ]; then
	echo "== the startup library needs building with the flag"
	echo "   Under Git Bash the install step fails (qnx_cp argument mangling)." >&2
	echo "   Run it from PowerShell, with FORWARD slashes in MAKEFLAGS:" >&2
	echo "" >&2
	echo '     $env:QNX_HOST   = "C:\Users\<you>\qnx800\host\win64\x86_64"' >&2
	echo '     $env:QNX_TARGET = "C:\Users\<you>\qnx800\target\qnx"' >&2
	echo '     $env:PATH       = "$env:PATH;$env:QNX_HOST\usr\bin"' >&2
	echo '     $env:MAKEFLAGS  = "-IC:/Users/<you>/qnx800/target/qnx/usr/include"' >&2
	echo "     cd $STARTUP/lib ; make install" >&2
	echo "" >&2
	echo "   then re-run this script." >&2
	exit 1
fi
echo "== reusing the installed startup library ($(stat -c %s "$LIBA") bytes)"

# ------------------------------------------------- did the flag actually work
#
# A flag that is accepted but ineffective would leave the fault in place and the
# boot would fail exactly as before, with nothing to say why. So count the
# writeback MMIO stores in the object this build just produced and require zero.
#
# This disassembles an artifact built here from the BSP's Apache-2.0 source, not
# a QNX-shipped binary, so NC QDL v7 4.6(c) is not engaged. It is the same
# measurement docs/findings.md recorded on 2026-09-08 (4 -> 0).
GICO="$(find "$STARTUP/lib" -name 'gic_v3.o' 2>/dev/null | head -1)"
if [ -z "$GICO" ]; then
	echo "  gic_v3.o not found: cannot verify the flag took effect" >&2
	exit 1
fi

# Prove the disassembler ran before believing any count from it. Without the
# QNX bin directory on PATH, ntoaarch64-objdump produces nothing, grep -c
# returns 0, and a gate written the obvious way reports success because it
# measured an empty string. That trap cost three wrong numbers while this was
# being written.
dis=$(ntoaarch64-objdump -d "$GICO" 2>/dev/null | wc -l)
if [ "$dis" -lt 100 ]; then
	echo "  ntoaarch64-objdump produced $dis lines for $(basename "$GICO"):" >&2
	echo "  it is not on PATH or cannot read the object, so the check below would" >&2
	echo "  pass vacuously. Refusing to report a result." >&2
	exit 1
fi

# What counts is a writeback store through a register that is NOT the stack
# pointer: that is an MMIO access whose syndrome comes back ISV=0. Frame
# pushes (str x30,[sp,#-16]!) and restores (ldp ...,[sp],#160) are writebacks
# too and are entirely normal; counting them says nothing. findings.md's 4 -> 0
# was over exactly this narrower set.
n=$(ntoaarch64-objdump -d "$GICO" 2>/dev/null \
    | grep -E '\b(str|strh|strb)\b\s+[wx][0-9]+,\s*\[x[0-9]+\](,\s*#-?[0-9]+)?!|\b(str|strh|strb)\b\s+[wx][0-9]+,\s*\[x[0-9]+\],\s*#-?[0-9]+' \
    | grep -vc '\[sp' || true)
echo "== non-SP writeback stores in $(basename "$GICO"): $n (want 0, from $dis disassembled lines)"
if [ "$n" != "0" ]; then
	echo "  the flag did not take effect; the NISV fault would remain" >&2
	ntoaarch64-objdump -d "$GICO" 2>/dev/null \
	  | grep -E '\b(str|strh|strb)\b\s+[wx][0-9]+,\s*\[x[0-9]+\](,\s*#-?[0-9]+)?!|\b(str|strh|strb)\b\s+[wx][0-9]+,\s*\[x[0-9]+\],\s*#-?[0-9]+' \
	  | grep -v '\[sp' | head -8 >&2
	exit 1
fi

echo "== building $BOARD"
( cd "$STARTUP/boards/$BOARD/aarch64/le" && make )

OUT="$STARTUP/boards/$BOARD/aarch64/le/startup-$BOARD"
[ -f "$OUT" ] || { echo "no output at $OUT" >&2; exit 1; }
echo "== built $OUT ($(stat -c %s "$OUT") bytes)"

MAP="$OUT.map"

echo "== symbol gate"
fail=0
# The board's own entry points, and the library paths this board depends on
# rather than replacing. psci_hvc and fdt_psci_configure are listed because the
# conduit is chosen from the device tree here, not hard-coded as on t234: if
# either were dropped from the link, CPU_ON would call through a null pointer.
for s in init_intrinfo board_smp_start board_smp_num_cpu init_asinfo \
         gic_v3_set_paddr_range gic_v3_initialize gic_sendipi \
         psci_hvc psci_smp_start fdt_psci_configure init_raminfo_fdt \
         fdt_init fdt_asinfo fdt_num_cpu hypervisor_init; do
	if ! ntoaarch64-nm "$OUT" | awk -v s="$s" '$NF==s' | grep -q .; then
		echo "  MISSING $s" >&2
		fail=1
	fi
done

# The entry point, checked rather than merely reported.
#
# The library ships two objects that are easy to confuse: _start.S, whose
# _start is a single branch to cstart, and _start_el1.S, which despite its
# name defines NO _start — it provides the EL-transition helpers that cstart
# and smp_start call (_start_el2_or_el1, _start_el1, at_el3, at_el2). Both are
# linked, and that is correct. An earlier version of this gate printed both
# object names and passed unconditionally, which asserted nothing.
#
# What actually matters for a KVM guest, which enters at EL1:
#   - _start is the bare branch, so control reaches cstart with x0-x3 intact;
#   - _start_el2_or_el1 is present, because cstart calls it, and its EL1 path
#     is `mrs CurrentEL; cmp #3; cmp #2; ret` — it returns without touching
#     EL3 or EL2 state, which is why entering at EL1 is safe.
entry="$(ntoaarch64-objdump -d --start-address=0x0 "$OUT" 2>/dev/null \
         | grep -A1 '<_start>:' | tail -1)"
case "$entry" in
	*"b"*"<cstart>"*)
		echo "== entry: _start branches to cstart (correct for EL1 entry)" ;;
	"")
		echo "  could not disassemble _start: refusing to report an entry check" >&2
		fail=1 ;;
	*)
		echo "  _start is not a branch to cstart:" >&2
		echo "    $entry" >&2
		echo "  a KVM guest enters at EL1; an EL3-flavoured entry hangs silently" >&2
		fail=1 ;;
esac

if ! ntoaarch64-nm "$OUT" | awk '$NF=="_start_el2_or_el1"' | grep -q .; then
	echo "  _start_el2_or_el1 is missing: cstart calls it, so this cannot boot" >&2
	fail=1
fi

# This startup is entered by QEMU's -kernel, never by firmware.
if ntoaarch64-nm "$OUT" | grep -iE " (efi_|acpi_)" | grep -q .; then
	echo "  EFI/ACPI code linked in, which this entry path never uses" >&2
	fail=1
fi

[ "$fail" = "0" ] && echo "  all checks passed"
exit "$fail"
