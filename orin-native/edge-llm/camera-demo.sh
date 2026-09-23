#!/usr/bin/env bash
# camera-demo.sh -- the liveness deadline's end-to-end demo (OD14), with a camera.
#
# Phase 3b / A6. A USB camera on L4T; a resident SmolVLM-500M reads each frame;
# every answer crosses to the QNX guest as a kind-1 claim to the deadline-mode
# monitor (ifs-live.bin, TCP 7102, 2 s). While it runs, the owner UNPLUGS THE
# CAMERA and plugs it back, as often as they like: the claim stream stops at its
# source, the monitor reports LIVENESS MISS, and the next claim after the camera
# returns prints LIVENESS RESTORED. camera_client.py --check then judges the run
# against the guest console by seq (see its docstring).
#
# NO CAMERA FRAME IS KEPT: camera_client.py writes each one only to a scratch
# file under /dev/shm and deletes it at exit. NO TIMING IS PUBLISHED: the
# governor is left as found.
#
#   CONSOLE=... OUT=... SECONDS_RUN=240 bash camera-demo.sh
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

OUT="${OUT:-$HOME/camera-demo-out/$(date -u +%Y%m%dT%H%M%SZ)}"
GUEST="${GUEST:-192.168.100.10}"
SVC_PORT="${SVC_PORT:-7102}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
SECONDS_RUN="${SECONDS_RUN:-240}"
SIZE="${SIZE:-64}"
SRV_PORT="${SRV_PORT:-8089}"
CORE_SRV="${CORE_SRV:-3,5}"
BIN="${LLAMA_BIN:-$HOME/llama.cpp/build/bin}"
MODELS="${LLAMA_MODELS:-$HOME/models}"
MODEL="${MODEL:-SmolVLM-500M-Instruct-Q8_0.gguf}"
MMPROJ="${MMPROJ:-mmproj-SmolVLM-500M-Instruct-Q8_0.gguf}"
IMAGES="${IMAGES:-/usr/src/tensorrt/data/mnist}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"

SRV_PID=""
SRV_ARGV=(taskset -c "$CORE_SRV" "$BIN/llama-server"
	-m "$MODELS/$MODEL" --mmproj "$MODELS/$MMPROJ"
	-ngl 99 -c 2048 -b 512 -ub 128 -t 2 -np 1
	--host 127.0.0.1 --port "$SRV_PORT")

srv_stop() {
	[ -n "$SRV_PID" ] || return 0
	local i
	kill -TERM "$SRV_PID" 2>/dev/null
	for i in 1 2 3 4 5 6; do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.5; done
	kill -KILL "$SRV_PID" 2>/dev/null
	wait "$SRV_PID" 2>/dev/null
	SRV_PID=""
}
trap 'say "cleanup"; srv_stop; rm -f /dev/shm/camera-claim.png' EXIT

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another GPU run holds $LOCK"
[ -z "$(m_pids_of llama-server)" ] || die "a llama-server is already resident; stop it first"
for f in "$BIN/llama-server" "$MODELS/$MODEL" "$MODELS/$MMPROJ" "$here/camera_client.py" "$CONSOLE"; do
	[ -r "$f" ] || die "missing: $f"
done
python3 -c 'import cv2' 2>/dev/null || die "python3 has no OpenCV (apt: python3-opencv)"
ls /dev/video* >/dev/null 2>&1 || die "no /dev/video* -- plug the camera in before the run starts"
tr -d '\0\r' < "$CONSOLE" | grep -aq "listening on :$SVC_PORT (frame=64 bytes, conf_min=60%), liveness deadline 2000 ms" \
	|| die "the guest console shows no 2000 ms deadline-mode monitor on :$SVC_PORT -- is this ifs-live?"
[ -e "$OUT" ] && die "$OUT already exists"
mkdir -p "$OUT" || die "cannot create $OUT"
sync
sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || die "cannot drop the page cache"

"${SRV_ARGV[@]}" > "$OUT/server.log" 2>&1 < /dev/null &
SRV_PID=$!
up=0
for _ in $(seq 1 90); do
	kill -0 "$SRV_PID" 2>/dev/null || die "llama-server exited during load"
	curl -s "http://127.0.0.1:$SRV_PORT/health" 2>/dev/null | grep -q '"ok"' && { up=1; break; }
	sleep 1
done
[ "$up" = 1 ] || die "llama-server did not report healthy in 90 s"
python3 "$here/vlm_request.py" --server "http://127.0.0.1:$SRV_PORT" --image "$IMAGES/0.pgm" \
	> "$OUT/warmup.json" 2>&1 || die "the warm-up request failed"

# ---------------------------------------------------------------- the stream
mark=$(stat -c %s "$CONSOLE")
echo "$mark" > "$OUT/console.mark"
# Did the monitor already stand in a reported silence? Then the stream's first
# claim must print RESTORED; on a boot never armed it must not.
silence=()
head -c "$mark" "$CONSOLE" | tr -d '\0\r' | grep -a "LIVENESS" | tail -1 | grep -q "LIVENESS MISS" \
	&& silence=(--opened-in-silence)
echo "opened_in_silence=${#silence[@]}" >> "$OUT/console.mark"
say "streaming for ${SECONDS_RUN} s: unplug the camera and plug it back whenever you like"
taskset -c 5 python3 "$here/camera_client.py" --host "$GUEST" --port "$SVC_PORT" \
	--server "http://127.0.0.1:$SRV_PORT" --size "$SIZE" --seconds "$SECONDS_RUN" \
	--log "$OUT/claims.jsonl" > "$OUT/client.log" 2>&1
crc=$?
srv_stop
[ "$crc" -eq 0 ] || die "camera_client.py exited $crc -- see $OUT/client.log"
sleep 3                         # the run's own trailing silence: 2 s, then its MISS line
tail -c +"$((mark + 1))" "$CONSOLE" | tr -d '\0\r' > "$OUT/guest-console.demo.log"

# ---------------------------------------------------------------- corroborate
python3 "$here/camera_client.py" --log "$OUT/claims.jsonl" --check "$OUT/guest-console.demo.log" "${silence[@]}" \
	| tee "$OUT/summary.txt"
chk=${PIPESTATUS[0]}

python3 - "$OUT" "$here" <<'PY' || die "stamp failed"
import hashlib, json, os, subprocess, sys, time
out, here = sys.argv[1], sys.argv[2]
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
q = subprocess.run(["sudo", "-n", "nvpmodel", "-q"], capture_output=True, text=True)
s = {"experiment": "camera-demo", "publishes_timing": False,
     "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "service_port": int(os.environ.get("SVC_PORT", "7102")), "deadline_ms": 2000,
     "frame_size_px": int(os.environ.get("SIZE", "64")), "frames_kept": 0,
     "model": os.environ.get("MODEL", "SmolVLM-500M-Instruct-Q8_0.gguf"),
     "nvpmodel": " ".join(q.stdout.split()) if q.returncode == 0 else "unavailable",
     "governor": "left as found", "page_cache": "dropped before the server started",
     "camera_client_sha256": sha(os.path.join(here, "camera_client.py")),
     "camera_demo_sha256": sha(os.path.join(here, "camera-demo.sh"))}
try:
    s["camera"] = open("/sys/class/video4linux/video0/name").read().strip()
except OSError:
    s["camera"] = "absent at stamp time"
json.dump(s, open(os.path.join(out, "stamp.json"), "w"), indent=1)
PY
[ "$chk" -eq 0 ] || die "the run and the guest console disagree -- see $OUT/summary.txt"
say "done -> $OUT"
