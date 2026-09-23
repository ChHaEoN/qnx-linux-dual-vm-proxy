#!/usr/bin/env bash
# vlm-demo.sh -- the VLM service arm's functional demonstration (OD13).
#
# Phase 3b / A6. A resident vision model on L4T answers MNIST digits; each
# answer crosses the VM boundary as a kind-1 claim to the QNX guest's service
# monitor (ifs-svc, TCP 7102); the monitor answers with a verdict. Two parts:
#
#   honest   every digit 0-9, the model's own answer, confidence and time --
#            each must ACCEPT
#   corrupt  one real claim per reason code, each changed in exactly one field
#            by vlm_client.py --corrupt -- each must REJECT with the reason the
#            client names
#
# CORROBORATED BY THE GUEST, NOT ONLY BY THE CLIENT. The monitor prints a line
# per rejected claim and a "client done" line per connection on the guest's
# serial console. Every verdict the client read back is matched against the
# console by its seq: a REJECT must appear with the same reason; an ACCEPT must
# appear as a connection that saw one claim, accepted one, rejected none.
#
# NO TIMING IS PUBLISHED. This is a functional record: the governor is left as
# found, and no latency figure is taken from it. It runs outside the latency
# harness's completeness gate on purpose -- the gate requires zero rejections,
# and this record exists to show them.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

OUT="${OUT:-$HOME/vlm-demo-out/$(date -u +%Y%m%dT%H%M%SZ)}"
GUEST="${GUEST:-192.168.100.10}"
SVC_PORT="${SVC_PORT:-7102}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
SRV_PORT="${SRV_PORT:-8089}"
CORE_SRV="${CORE_SRV:-3,5}"
BIN="${LLAMA_BIN:-$HOME/llama.cpp/build/bin}"
MODELS="${LLAMA_MODELS:-$HOME/models}"
MODEL="${MODEL:-SmolVLM-500M-Instruct-Q8_0.gguf}"
MMPROJ="${MMPROJ:-mmproj-SmolVLM-500M-Instruct-Q8_0.gguf}"
IMAGES="${IMAGES:-/usr/src/tensorrt/data/mnist}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"   # the same lock: one GPU user at a time

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
trap 'say "cleanup"; srv_stop' EXIT

# ---------------------------------------------------------------- preflight
exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another GPU run holds $LOCK"
[ -z "$(m_pids_of llama-server)" ] || die "a llama-server is already resident; stop it first"
for f in "$BIN/llama-server" "$MODELS/$MODEL" "$MODELS/$MMPROJ" "$here/vlm_client.py" "$CONSOLE"; do
	[ -r "$f" ] || die "missing: $f"
done
mkdir -p "$OUT" || die "cannot create $OUT"
[ -e "$OUT/claims.log" ] && die "$OUT already holds a run"
m_reachable "$GUEST" "$SVC_PORT" "the service's monitor instance"
tr -d '\0\r' < "$CONSOLE" | grep -aq "claim kinds: 0 mnist" \
	|| die "the guest console shows no claim-kind monitor -- is this ifs-svc?"
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
# One warm-up request, answered but never sent: the first after a start is cold.
python3 "$here/vlm_request.py" --server "http://127.0.0.1:$SRV_PORT" --image "$IMAGES/0.pgm" \
	> "$OUT/warmup.json" 2>&1 || die "the warm-up request failed"

# ---------------------------------------------------------------- the claims
mark=$(stat -c %s "$CONSOLE")
echo "$mark" > "$OUT/console.mark"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/requests.start"   # the stamp's utc
: > "$OUT/claims.log"
seq=1000
claim() {   # $1 label  $2 digit  $3 expected verdict  $4 expected reason  [$5 corrupt]
	local label="$1" d="$2" want_v="$3" want_r="$4" how="${5:-}" args rc
	seq=$((seq + 1))
	args=(--host "$GUEST" --port "$SVC_PORT" --server "http://127.0.0.1:$SRV_PORT"
		--images "$IMAGES" --digit "$d" --seq "$seq")
	[ -n "$how" ] && args+=(--corrupt "$how")
	{
		echo "=== $label seq=$seq want=$want_v/$want_r"
		taskset -c 5 python3 "$here/vlm_client.py" "${args[@]}"
		echo "exit=$?"
	} >> "$OUT/claims.log" 2>&1
	printf '%s %s %s %s %s\n' "$seq" "$label" "$want_v" "$want_r" "${how:--}" >> "$OUT/expected.txt"
}
: > "$OUT/expected.txt"
for d in 0 1 2 3 4 5 6 7 8 9; do claim "honest-digit-$d" "$d" ACCEPT ok; done
claim corrupt-class    3 REJECT class-out-of-range          class
claim corrupt-conf     3 REJECT confidence-not-a-percentage conf
claim corrupt-conf-low 3 REJECT confidence-below-threshold  conf-low
claim corrupt-slow     3 REJECT inference-time-implausible  slow
claim corrupt-kind     3 REJECT claim-kind-unknown          kind
claim corrupt-model    3 REJECT vlm-model-unbounded         model
claim corrupt-sum      3 REJECT vlm-time-inconsistent       sum
claim as-mnist         3 REJECT inference-time-implausible  as-mnist
sleep 1
srv_stop
[ -z "$(m_pids_of llama-server)" ] || die "a llama-server is still resident after the stop"

tail -c +"$((mark + 1))" "$CONSOLE" | tr -d '\0\r' > "$OUT/guest-console.demo.log"

# ---------------------------------------------------------------- corroborate
python3 - "$OUT" <<'PY' || die "the client and the guest console disagree"
import os, re, sys
out = sys.argv[1]
claims = open(os.path.join(out, "claims.log")).read()
console = open(os.path.join(out, "guest-console.demo.log"), errors="replace").read()
exp = [l.split() for l in open(os.path.join(out, "expected.txt")) if l.strip()]

# One "client done" line per connection, in order; the service instance gets
# only these claims, so the n-th line belongs to the n-th claim.
done = re.findall(r"client done: seen=(\d+) accepted=(\d+) rejected=(\d+)", console)
rejects = {int(m.group(1)): m.group(2) for m in re.finditer(r"REJECT seq=(\d+) .*?reason=([a-z-]+)", console)}

rows, bad = [], 0
blocks = re.split(r"^=== ", claims, flags=re.M)[1:]
if len(blocks) != len(exp):
    print("claims.log has %d blocks, expected %d" % (len(blocks), len(exp))); sys.exit(1)
if len(done) != len(exp):
    print("guest console has %d 'client done' lines for %d claims" % (len(done), len(exp))); sys.exit(1)
for (seq, label, want_v, want_r, how), block, (seen, acc, rej) in zip(exp, blocks, done):
    seq = int(seq)
    m = re.search(r"verdict=(ACCEPT|REJECT) reason=([a-z-]+)", block)
    got_v, got_r = (m.group(1), m.group(2)) if m else ("NONE", "none")
    ans = re.search(r"-> class=(\d+) confidence=([\d.]+)%", block)
    client_ok = (got_v, got_r) == (want_v, want_r)
    if want_v == "ACCEPT":
        console_ok = (seen, acc, rej) == ("1", "1", "0") and seq not in rejects
    else:
        console_ok = (seen, acc, rej) == ("1", "0", "1") and rejects.get(seq) == want_r
    ok = client_ok and console_ok
    bad += not ok
    rows.append("%-18s seq=%d answer=%s conf=%s%%  client=%s/%s  console=%s  %s" % (
        label, seq, ans.group(1) if ans else "?", ans.group(2) if ans else "?",
        got_v, got_r, "REJECT " + rejects[seq] if seq in rejects else "accept (seen=%s acc=%s rej=%s)" % (seen, acc, rej),
        "ok" if ok else "MISMATCH"))
open(os.path.join(out, "summary.txt"), "w").write("\n".join(rows) + "\n")
print("\n".join(rows))
print("%d of %d claims: client verdict as expected AND corroborated by the guest console" % (len(rows) - bad, len(rows)))
sys.exit(1 if bad else 0)
PY

# ---------------------------------------------------------------- the stamp
BIN="$BIN" MODELS="$MODELS" MODEL="$MODEL" MMPROJ="$MMPROJ" CORE_SRV="$CORE_SRV" \
	REPS=0 ROUNDS=0 WARMUP=1 IMAGES="$IMAGES" NO_GUEST=0 \
	SRV_ARGV_STR="${SRV_ARGV[*]}" python3 "$here/vlm_stamp.py" "$OUT" >/dev/null || die "stamp failed"
python3 - "$OUT" "$here" <<'PY'
import hashlib, json, os, sys
out, here = sys.argv[1], sys.argv[2]
p = os.path.join(out, "stamp.json")
s = json.load(open(p))
def sha(f):
    return hashlib.sha256(open(f, "rb").read()).hexdigest()
s["experiment"] = "vlm-demo"
s["publishes_timing"] = False
s["service_port"] = int(os.environ.get("SVC_PORT", "7102"))
s["vlm_client_sha256"] = sha(os.path.join(here, "vlm_client.py"))
s["vlm_demo_sha256"] = sha(os.path.join(here, "vlm-demo.sh"))
for k in ("reps", "rounds", "warmup_excluded", "script_sha256", "vlm_stamp_sha256"):
    s.pop(k, None)
json.dump(s, open(p, "w"), indent=1)
PY
say "done -> $OUT"
