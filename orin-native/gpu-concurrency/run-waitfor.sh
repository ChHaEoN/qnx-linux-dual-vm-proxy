#!/usr/bin/env bash
# run-waitfor.sh -- the boot-timeout falsification (measurement-design.md section 3.7): change
# the constant and see whether the boot metric moves by the predicted amount. Phase 3b / A6,
# 2026-09-26; the last but one item of the OD11 campaign. The owner asked for this run
# (2026-09-26); it boots guests only, changing no setting of the board but the governor and
# c7 for the run, both restored.
#
# WHAT IS KNOWN. On 2026-09-20 (findings.md), a diskless boot of the guest from QEMU exec to
# "Startup complete" was found to be ~89-92% one fixed wait: `waitfor /dev/hd0` in the stock
# mkqnximage startup.sh, which passes no timeout and so takes QNX's 5 s default -- 5001.3 ms on
# the Orin, 5000.3 ms on a1.metal. That rests on the wait agreeing across two vendors'
# silicon to about a millisecond: strong, but a coincidence argument. The direct test is to
# change the constant.
#
# THE IMAGES (none committed: QNX-derived), each accepted by compare-ifs.py against
# ifs-stamp.bin with only startup.sh, build/ifs.build and build.date differing:
#   W5  ifs-stamp.bin   the stock startup.sh: `waitfor /dev/hd0` (the 5 s default)
#   W2  ifs-wait2.bin   `waitfor /dev/hd0 2`   (ifs-wait2.build)
#   W8  ifs-wait8.bin   `waitfor /dev/hd0 8`   (ifs-wait8.build)
#
# THE RUN. Nine diskless boots in the pattern W5 W2 W8 W8 W2 W5 W5 W2 W8 (three per image,
# each image early, middle and late), each by scripts/twin/time-kvm-boot.py with --runs 1
# --warmup 0 and no --disk, so the launch line is 2026-09-20's diskless control
# (-machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G -kernel <ifs> -nographic).
# The governor pinned and c7 off for the run, as every A6 measurement; nothing else runs a
# guest. Each boot's record is boot-iN-WX.json. The timer stamps the board's host name into
# the record and its log; the harness replaces it with <board> as each boot ends (redaction
# at capture) and refuses to finish if the name survives anywhere in the output.
#
# THE RULE, fixed here before any run (waitfor_report.py applies it). Per boot, from the
# serial marks time-kvm-boot.py timestamps against QEMU exec:
#   WAIT  = mount_fs - fsevmgr      ("---> Starting fsevmgr" to "---> Mounting file systems":
#                                    devb-virtio's start and the disk wait; with no disk the
#                                    script then gives up on /system and returns)
#   PRE   = fsevmgr                 (exec to "---> Starting fsevmgr")
#   POST  = startup_end - mount_fs  (to "Startup complete")
# Per image: the median of its three boots.
#
# THE PREDICTION, written and committed before any run of this harness, smoke runs
# included. It is not to be amended. H: the wait is QNX's waitfor timeout and nothing else,
# so it moves second for second with the constant and nothing around it moves.
#   P1 WAIT(W2) - WAIT(W5) = -3000 ms, within 100 ms.
#   P2 WAIT(W8) - WAIT(W5) = +3000 ms, within 100 ms.
#   P3 nothing else moves: PRE and POST each within 100 ms across the three images.
# THE CHECKS (a prediction resting on a failed one prints VOID; none counts an outcome a
# prediction is about):
#   M1 every boot reached "Startup complete" and every mark was seen -> all
#   M2 nine boots in the pattern, three per image -> all
#   M3 every boot diskless: the record's devices "none" and disk "none" -> all
#   M4 each image's sha256 in its records is the one the harness hashed at the start -> all
#   M5 the governor pinned for the run (every record's cpu_before) -> all
#
# NEEDS: NO guest running. IMG_W5, IMG_W2, IMG_W8 (defaults ~/output/ifs-stamp.bin,
# ifs-wait2.bin, ifs-wait8.bin). CSTATE=shallow (set before the library).
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSTATE="${CSTATE-shallow}"      # before the library, which empties it when sourced
LIB="${LIB:-$here/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

TIMER="${TIMER:-$here/../../scripts/twin/time-kvm-boot.py}"
REPORT="${REPORT:-$here/waitfor_report.py}"
IMG_W5="${IMG_W5:-$HOME/output/ifs-stamp.bin}"
IMG_W2="${IMG_W2:-$HOME/output/ifs-wait2.bin}"
IMG_W8="${IMG_W8:-$HOME/output/ifs-wait8.bin}"
PAT=(W5 W2 W8 W8 W2 W5 W5 W2 W8)
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"

cleanup() {
	say "cleanup"
	m_cstate_restore; m_governor_restore
}
trap cleanup EXIT

img_of() { case "$1" in W5) echo "$IMG_W5" ;; W2) echo "$IMG_W2" ;; W8) echo "$IMG_W8" ;; esac; }
BOARD="$(python3 -c 'import platform; print(platform.node())')"
redact() { sed -i "s/$BOARD/<board>/g" "$@"; }

# ---------------------------------------------------------------- preflight
[ -n "$BOARD" ] || die "cannot read the host name to redact"
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
for f in "$TIMER" "$REPORT" "$IMG_W5" "$IMG_W2" "$IMG_W8"; do [ -r "$f" ] || die "missing: $f"; done
[ -z "$(m_pids_of qemu-system-aarch64)" ] || die "a guest is running -- this run boots its own"
m_prepare_out "${OUT:-}" "$HOME/waitfor-out"
for w in W5 W2 W8; do echo "$w $(basename "$(img_of $w)") $(sha256sum < "$(img_of $w)" | cut -d' ' -f1)" >> "$OUT/images.txt"; done
m_governor_pin
m_cstate_apply

# ---------------------------------------------------------------- the run
say "nine diskless boots in the pattern ${PAT[*]} -> $OUT"
i=0
for w in "${PAT[@]}"; do
	i=$((i + 1))
	echo "boot $i image $w" >> "$OUT/order.log"
	python3 "$TIMER" --ifs "$(img_of $w)" --runs 1 --warmup 0 --json "$OUT/boot-i$i-$w.json" --label "waitfor $w boot $i" \
		> "$OUT/boot-i$i-$w.log" 2>&1 || { redact "$OUT/boot-i$i-$w.log"; die "boot $i ($w) did not reach Startup complete -- see $OUT/boot-i$i-$w.log"; }
	redact "$OUT/boot-i$i-$w.json" "$OUT/boot-i$i-$w.log"
	sync
	say "boot $i/${#PAT[@]} ($w) done: $(grep -o 'mount_fs=[0-9.]*' "$OUT/boot-i$i-$w.log" | head -1)"
done
m_governor_recheck
! grep -rlF "$BOARD" "$OUT" || die "the host name survived in the files above"
say "the disk wait at 5, 2 and 8 s: does the metric follow the constant?"
python3 "$REPORT" "$OUT" || die "the report could not be made -- see above"
