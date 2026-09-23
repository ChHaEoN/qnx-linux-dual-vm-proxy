#!/usr/bin/env bash
#
# characterize-load.sh -- is an LLM a different LOAD from fma.cu?
#
# Phase 3b / A6 prep. This runs on L4T ALONE, with no QNX guest: it measures
# nothing about the partition and produces no latency figure. Its only job is to
# decide whether an `llm` arm would stress something the existing `gpu` arm does
# not, before a board session is spent on it.
#
# WHY IT MIGHT. fma.cu burns FP32 ALUs out of registers: in the A6 records its
# arms never moved the memory controller. LLM decode is memory-bandwidth-bound by
# construction -- every generated token streams the whole weight matrix past the
# ALUs -- so it should show up as EMC utilisation where fma shows none.
#
# EACH WINDOW IS TRACED ALONE. tegrastats runs across one load at a time, so the
# statistics describe that load rather than the idle time around it. Even so the
# medians of a window that includes model loading are diluted by it, and the
# record says which ones those are.
#
# THREE TRAPS, ALL PAID FOR ON 2026-09-23:
#
#   1. tegrastats runs as ROOT under sudo. A plain kill from this shell is
#      silently ignored and `wait` on it never returns -- that hung the first
#      session for ten minutes. Kill EVERY match, as root, and never wait.
#   2. cudaMalloc does NOT reclaim page cache on this board. With 3.7 GB in
#      buff/cache a 2.32 GiB model cannot create a context (NvMap error 12);
#      after drop_caches the identical command runs. So the drop is part of the
#      procedure, and it is recorded, not done quietly.
#   3. A model's DEFAULT context can ask for more KV cache than the board has
#      (1512 MiB for the 4B). Context and batch are explicit parameters here.
#
# Usage: characterize-load.sh [OUTDIR]
set -eu

OUT="${1:-$HOME/llm-prep/loadcompare}"
BIN="${LLAMA_BIN:-$HOME/llama.cpp/build/bin}"
MODELS="${LLAMA_MODELS:-$HOME/models}"
FMA="${FMA_BIN:-$HOME/gpuload/fma}"
BIG="${BIG_GGUF:-Qwen3VL-4B-Instruct-Q4_K_M.gguf}"
SMALL="${SMALL_GGUF:-SmolVLM-500M-Instruct-Q8_0.gguf}"
SECS="${SECS:-60}"

mkdir -p "$OUT"
for f in "$BIN/llama-bench" "$FMA" "$MODELS/$BIG" "$MODELS/$SMALL"; do
	[ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

ts_stop() {
	local p
	for p in $(pgrep -f '[t]egrastats --interval' || true); do sudo -n kill "$p" 2>/dev/null || true; done
	sleep 1
	if pgrep -f '[t]egrastats --interval' >/dev/null; then echo "FATAL: tegrastats survived" >&2; exit 1; fi
}

drop_cache() {
	sync
	sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || { echo "FATAL: cannot drop caches" >&2; exit 1; }
	sleep 1
}

window() {   # $1 tag  $2 timeout  rest: command (none = idle)
	local tag="$1" lim="$2"; shift 2
	ts_stop
	drop_cache
	free -m | sed -n 2p > "$OUT/$tag.mem"
	sudo -n tegrastats --interval 500 > "$OUT/ts-$tag.log" 2>/dev/null &
	sleep 2
	date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/$tag.start"
	if [ "$#" -gt 0 ]; then
		timeout "$lim" "$@" > "$OUT/$tag.log" 2>&1 || echo "(exit $?)" >> "$OUT/$tag.log"
	else
		sleep "$lim"
	fi
	date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/$tag.end"
	sleep 1
	ts_stop
	echo "--- $tag: $(wc -l < "$OUT/ts-$tag.log") samples"
}

# A loaded window that produced no throughput line measured nothing: an OOM or a
# segfault would otherwise be filed as a quiet, low-utilisation arm.
require_rate() {   # $1 tag  $2 pattern
	grep -qE "$2" "$OUT/$1.log" || {
		echo "FATAL: $1 produced no throughput line -- the window measured nothing" >&2
		grep -iE "error|out of memory|failed|Segmentation" "$OUT/$1.log" | tail -3 >&2
		exit 1
	}
}

{
	echo "date_utc          $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "board             $(tr -d '\0' < /proc/device-tree/model)"
	echo "l4t               $(head -1 /etc/nv_tegra_release)"
	echo "nvpmodel          $(sudo -n nvpmodel -q 2>/dev/null | tr '\n' ' ')"
	echo "governor          $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
	echo "qemu_running      $(pgrep -c '[q]emu-system-aarch64' || echo 0)"
	echo "llama_cpp         $(cd "$BIN/../.." 2>/dev/null && git log -1 --format=%H 2>/dev/null || echo '?')"
	echo "big_gguf          $BIG"
	echo "small_gguf        $SMALL"
	echo "secs              $SECS"
} | tee "$OUT/state.txt"
echo

# The governor is NOT pinned and c7 is NOT disabled: this run takes no latency
# figure, so the ladder's discipline does not apply and pretending otherwise
# would imply these numbers are comparable with A6 rungs. They are not.

window idle "$((SECS / 2))"
window fma "$((SECS + 5))" "$FMA" "$SECS" characterize

# Decode only (-p 0). Token counts are sized to roughly SECS at the rates this
# board gives: ~17 tok/s for the 4B, ~97 for the 500M.
window llm-big "$((SECS * 3))" "$BIN/llama-bench" -m "$MODELS/$BIG" -ngl 99 -p 0 -n "$((SECS * 17))" -r 1
require_rate llm-big '^\| .*\| *tg'
window llm-small "$((SECS * 3))" "$BIN/llama-bench" -m "$MODELS/$SMALL" -ngl 99 -p 0 -n "$((SECS * 97))" -r 1
require_rate llm-small '^\| .*\| *tg'

echo
echo "=== per-window statistics ==="
python3 - "$OUT" <<'PY'
import glob, os, re, statistics as st, sys
base = sys.argv[1]
order = {"idle": 0, "fma": 1, "llm-big": 2, "llm-small": 3}
rows = []
for f in glob.glob(os.path.join(base, "ts-*.log")):
    tag = os.path.basename(f)[3:-4]
    if tag not in order:
        continue
    gr, ep, ec, vd, tj = [], [], [], [], []
    for line in open(f, errors="replace"):
        m = re.search(r"GR3D_FREQ (\d+)%", line)
        if m: gr.append(int(m.group(1)))
        m = re.search(r"EMC_FREQ (\d+)%@(\d+)", line)
        if m: ep.append(int(m.group(1))); ec.append(int(m.group(2)))
        m = re.search(r"VDD_IN (\d+)mW", line)
        if m: vd.append(int(m.group(1)))
        m = re.search(r"tj@([\d.]+)C", line)
        if m: tj.append(float(m.group(1)))
    med = lambda xs: round(st.median(xs), 1) if xs else None
    mx = lambda xs: max(xs) if xs else None
    rows.append((order[tag], tag, len(gr), med(gr), mx(gr), med(ep), mx(ep),
                 med(ec), mx(ec), med(vd), mx(vd), mx(tj)))
rows.sort()
print("%-10s %4s | %-11s | %-11s | %-13s | %-15s | %s" %
      ("window", "n", "GR3D med/max", "EMCu med/max", "EMC MHz med/max", "VDD_IN mW med/max", "tj max"))
for r in rows:
    print("%-10s %4d | %5s %5s | %5s %5s | %6s %6s | %7s %7s | %5s" % r[1:])
PY

echo
echo "=== throughput ==="
grep -hE "^\| .*\| *tg" "$OUT"/llm-big.log "$OUT"/llm-small.log 2>/dev/null || true
tail -1 "$OUT/fma.log" 2>/dev/null || true
