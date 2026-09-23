#!/usr/bin/env bash
# liveness-demo.sh -- the liveness deadline's synthetic demo (OD14).
#
# Phase 3b / A6. Runs liveness_demo.py on L4T against the deadline-mode monitor
# instance in ifs-live.bin (TCP 7102, `svc 2000`): pre-built claims at controlled
# cadences, just under and just over the deadline, plus a quiet connection, a
# frame cut short, keepalives with no claims and a hung client holding the only
# slot. Every expected outcome is corroborated on the guest's serial console;
# the scenarios and their checks are in liveness_demo.py's docstring.
#
# NO MODEL RUNS and NO LATENCY FIGURE is taken: the governor is left as found.
# Each MISS carries the silence the guest measured and the host's time to see
# the line, which show the deadline is kept -- nothing more.
#
# Run it on a FRESH boot of ifs-live: the first claim of a boot is what checks
# that the monitor waited without a deadline until then. On a boot that has
# already been armed the check is recorded as not applicable, not passed.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${LIB:-$here/../gpu-concurrency/lib-measure.sh}"
[ -r "$LIB" ] || { echo "FATAL: lib-measure.sh not found at $LIB" >&2; exit 1; }
# shellcheck source=/dev/null
. "$LIB"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }

OUT="${OUT:-$HOME/liveness-demo-out/$(date -u +%Y%m%dT%H%M%SZ)}"
GUEST="${GUEST:-192.168.100.10}"
SVC_PORT="${SVC_PORT:-7102}"
CONSOLE="${CONSOLE:?set CONSOLE to the guest console log the launcher writes}"
LOCK="${LOCK:-/tmp/vlm-characterize.lock}"   # shared with the service's other users

exec 9>"$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another run holds $LOCK"
[ -r "$CONSOLE" ] || die "missing: $CONSOLE"
[ -e "$OUT" ] && die "$OUT already exists"
tr -d '\0\r' < "$CONSOLE" | grep -aq "listening on :$SVC_PORT (frame=64 bytes, conf_min=60%), liveness deadline" \
	|| die "the guest console shows no deadline-mode monitor on :$SVC_PORT -- is this ifs-live?"
# NOT m_reachable: its connect-and-close is harmless to the deadline (it is not
# a claim), but a failed one would leave the demo nothing to say. The driver's
# first claim is the reachability check, and it fails loudly.

say "liveness demo -> $OUT"
python3 "$here/liveness_demo.py" --host "$GUEST" --port "$SVC_PORT" --console "$CONSOLE" --out "$OUT"
rc=$?
python3 - "$OUT" "$here" <<'PY' || die "stamp failed"
import hashlib, json, os, subprocess, sys
out, here = sys.argv[1], sys.argv[2]
p = os.path.join(out, "stamp.json")
s = json.load(open(p))
s["liveness_demo_sh_sha256"] = hashlib.sha256(open(os.path.join(here, "liveness-demo.sh"), "rb").read()).hexdigest()
q = subprocess.run(["sudo", "-n", "nvpmodel", "-q"], capture_output=True, text=True)
s["nvpmodel"] = " ".join(q.stdout.split()) if q.returncode == 0 else "unavailable"
s["governor"] = "left as found"
json.dump(s, open(p, "w"), indent=1)
PY
[ "$rc" -eq 0 ] || die "the demo's checks failed -- see $OUT/summary.txt"
say "done -> $OUT"
