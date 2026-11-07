"""run-ota-drill.sh (SDV Phase 6 WP6): the OTA drill's harness of a vss session on a
bare-metal AWS instance, run here against stubs, on the pattern of tests/test_vss_harness.py. No git runs here.

THE RIG. The harness runs as the detached runner runs it (remote-ladder.sh _detached): from W/repo/orin-native/
gpu-concurrency, with the harness phase's environment (W, IFS_BIN, IMG_S, IMG_B, DISK, OUT, VSS_IN, VSS_HOME, STATUS,
VPROBE, CSTATE and VSS_HOST when given), stdout and stderr into the stem's run.log. W/repo holds the real harness, the real
deadline library and the real vss_setup.py (the record's writer), the real sdv/ota/ota_docker.py (the proof of a pinned
image), and stand-ins for sdv/drill/drill.py (WP3's, by its interface) and sdv/stack/stack.py, each
logging its argument vector (and stack.py its SDV_ environment) and leaving what the real one leaves: a run directory and
its manifest.json, the stack's containers, the updater's container and unit while the drill runs, and the drill's record.
W/drill-in (DRILL_IN) holds the drill's three files, hashed in inputs.env's FILES (remote-ladder.sh's setup moves them
there from in/ once checked); its tar is one docker save of the three pinned images, which drill.py manifest
(WP3's) checks against the pins and splits into one tar per version. W/in
(VSS_IN) holds a bundle member only, which the harness never reads. W/rec/vss-setup is a finished setup; W/sdv (VSS_HOME)
what setup left: the sim venv's python, python-build-standalone's python3 (each a stand-in that logs and runs this test's
own Python), gen/, cache/dbc/ and the honest recording. Its python3 makes a venv whose python answers pip as a stand-in.

Every other command the harness runs is a stub first on PATH, each logging one line (its name, whether it ran under the
stub sudo, its arguments) to calls.log: sudo (only `sudo -n`; as root, it reads a file of mode 0, which stands for one the
updater wrote 0600 as root, for `sudo -n cat FILE`), docker (load; save from a docker-save tar this test built
of each pinned image; ps and rm over a containers directory, each file a container named by its ID and holding its
label), systemctl (the unit ota-lite), pgrep, pkill, ps (a containerd-shim line for each container, and one more when a
test asks; cut to $COLUMNS columns, as procps cuts a line, unless it is asked with -ww), sync, sleep (returns at once),
id -nG, date and timeout as in test_vss_harness.py: `date +%s` reads a fixed clock that jumps once a regular expression
matches run.log, and `timeout` runs the real one, with a cap of one second when its command matches STUB_CAP_RE (or,
with STUB_CAP_AT_ONCE, cuts that command before it does anything: a cap that fires in a call that would not take a
second). L4T's release file and the device tree's compatible are files of the rig's own, absent unless a test writes
them. No AWS, no SSH, no board, no docker, systemd, sudo or QEMU of this machine.

Does not demonstrate: anything about an instance -- the drill there, Docker, the updater, vcan, the noble AMI; nor WP3's
drill.py, whose stand-in here keeps only its command line.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import ast
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
G = os.path.join(REPO, "orin-native", "gpu-concurrency")
HARNESS = os.path.join(G, "run-ota-drill.sh")
LIB = os.path.join(G, "lib-vss-deadline.sh")
VSS_SETUP = os.path.join(G, "vss_setup.py")
CAPTURE = os.path.join(REPO, "scripts", "aws", "capture.py")
OTA_DOCKER = os.path.join(REPO, "sdv", "ota", "ota_docker.py")
APP_LOCK = os.path.join(REPO, "sdv", "apps", "hard-brake-hazard", "requirements.aarch64.lock")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32",
                                reason="the harness runs on Linux; its stubs need bash and coreutils' timeout")

UNITS = ["load", "venv", "prepare", "up", "manifest", "drill", "down"]
T0 = 1800000000                        # the stub clock's epoch second
COMMIT = "0123456789abcdef0123456789abcdef01234567"
RECORDING = "20260930-sigsim-1b"
CAP = 180 * 60 - 1500 + 600            # stop_at + 10 minutes - now, with the deadline 180 minutes ahead of the clock
APP_ID = "ab" * 32                     # the updater's container while the drill runs (a stand-in's ID)
STACK_IDS = ["5a" * 32, "5b" * 32, "5c" * 32]
RECORD_FILES = ["drill-result.json", "ota-lite.jsonl", "state.json"] + ["status-%d.json" % n for n in range(1, 7)]
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"


# --- the drill's images, and docker save's stream of each ---------------------------------------------------------------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _image(version):
    """One platform's image as the containerd store keeps a loaded one: its config, and a manifest whose digest is the
    store's ID. Documentation values only."""
    config = json.dumps({"architecture": "arm64", "os": "linux",
                         "config": {"Labels": {"org.opencontainers.image.version": version}}}, sort_keys=True).encode()
    cfg = "sha256:" + _sha(config)
    manifest = json.dumps({"schemaVersion": 2, "mediaType": OCI_MANIFEST,
                           "config": {"mediaType": OCI_CONFIG, "digest": cfg, "size": len(config)}, "layers": []},
                          sort_keys=True).encode()
    return {"version": version, "id": "sha256:" + _sha(manifest), "config_digest": cfg, "manifest": manifest,
            "config": config}


def _save(img):
    """`docker save <the store ID>`: an OCI layout holding the manifest and the config blobs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        def add(name, data):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        add("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        add("index.json", json.dumps({"schemaVersion": 2, "manifests": [
            {"mediaType": OCI_MANIFEST, "digest": img["id"], "size": len(img["manifest"])}]}).encode())
        add("blobs/sha256/" + img["id"].split(":")[1], img["manifest"])
        add("blobs/sha256/" + img["config_digest"].split(":")[1], img["config"])
    return buf.getvalue()


def _save_many(imgs):
    """`docker save` of several store IDs in one tar: its index.json lists each image's manifest."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        def add(name, data):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        add("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        add("index.json", json.dumps({"schemaVersion": 2, "manifests": [
            {"mediaType": OCI_MANIFEST, "digest": i["id"], "size": len(i["manifest"])} for i in imgs]}).encode())
        for i in imgs:
            add("blobs/sha256/" + i["id"].split(":")[1], i["manifest"])
            add("blobs/sha256/" + i["config_digest"].split(":")[1], i["config"])
    return buf.getvalue()


def _tar(files):
    """A tar of these names and bytes, nothing else."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


IMAGES = [_image(v) for v in ("1.0.0", "1.1.0", "1.2.0")]


def _pins(images=IMAGES):
    """drill-images.json as this test lays it out (WP3 owns the layout; the harness reads every object that holds an `id`
    and a `config_digest`, both sha256 digests, wherever it stands): v2's base names v1's pin, which counts once."""
    v1, v2, v3 = images
    return {"format": 1, "about": "the drill's arm64 pins (a stand-in of WP3's file)", "arm64": {
        "v1": {"id": v1["id"], "config_digest": v1["config_digest"], "tag": "sdv-local/hard-brake-hazard:1.0.0-arm64"},
        "v2": {"id": v2["id"], "config_digest": v2["config_digest"], "tag": "sdv-local/hard-brake-hazard:1.1.0-arm64",
               "base": {"id": v1["id"], "config_digest": v1["config_digest"]}},
        "v3": {"id": v3["id"], "config_digest": v3["config_digest"], "tag": "sdv-local/hard-brake-hazard:1.2.0-arm64",
               "base": v2["id"]}}}


# --- the stubs ---------------------------------------------------------------------------------------------------

_LIB = r'''# the stubs' shared part (sourced)
stub_log() {
	local n="$1"; shift
	printf '%s\t%s\t%s\n' "$n" "${STUB_VIA_SUDO:-0}" "$(printf '%s' "$*" | tr '\n\t' '  ')" >> "$STUB_DIR/calls.log"
}
st() { [ -e "$STUB_DIR/state/$1" ]; }
st_set() { mkdir -p "$STUB_DIR/state"; : > "$STUB_DIR/state/$1"; }
st_rm() { rm -f "$STUB_DIR/state/$1"; }
root_or() { [ "${STUB_VIA_SUDO:-0}" = 1 ] && return 0; echo "$1" >&2; exit "${2:-1}"; }
real() { PATH="$STUB_REAL_PATH" command -v "$1"; }
'''

_STUBS = {
    "sudo": r'''stub_log sudo "$@"
if [ "${1:-}" != -n ]; then echo "sudo: a terminal is required to read the password" >&2; exit 1; fi
shift
export STUB_VIA_SUDO=1
if [ "${1:-}" = cat ] && [ "$#" = 2 ] && [ -f "$2" ] && [ ! -r "$2" ]; then
	# root reads a file only root may read (mode 0 here, the updater's 0600 files there): lent for this one call
	[ -z "${STUB_ROOT_CAT_FAIL:-}" ] || { echo "cat: $2: the stub's failure" >&2; exit 1; }
	m="$(stat -c %a "$2")"; chmod u+r "$2"; rc=0; "$(real cat)" "$2" || rc=$?; chmod "$m" "$2"; exit "$rc"
fi
exec "$@"
''',
    # the containers: one file per container in $STUB_DIR/containers, named by its full ID and holding its label key
    "docker": r'''stub_log docker "$@"
root_or "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" 1
C="$STUB_DIR/containers"
mkdir -p "$C"
case "$1" in
load) [ "${STUB_LOAD_RC:-0}" = 0 ] || { echo "Error: the stub's load failure"; exit "$STUB_LOAD_RC"; }
	echo "Loaded image ID: sha256:1111111111111111111111111111111111111111111111111111111111111111" ;;
save) f="$STUB_DIR/saves/${2#sha256:}.tar"
	[ -r "$f" ] || { echo "Error response from daemon: No such image: $2" >&2; exit 1; }
	cat "$f" ;;
ps) [ -z "${STUB_DOCKER_PS_FAIL:-}" ] || { echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock" >&2; exit 1; }
	want=""
	for a in "$@"; do case "$a" in label=*) want="${a#label=}" ;; esac; done
	for f in "$C"/*; do
		[ -e "$f" ] || continue
		if [ -z "$want" ] || [ "$(cat "$f")" = "$want" ]; then basename "$f"; fi
	done ;;
rm) [ -z "${STUB_RM_FAIL:-}" ] || { echo "Error response from daemon: the stub's rm failure" >&2; exit 1; }
	shift
	for a in "$@"; do case "$a" in -f) ;; *) rm -f "$C/$a" ;; esac; done ;;
*) echo "docker stub: $*" >&2; exit 2 ;;
esac
''',
    "systemctl": r'''stub_log systemctl "$@"
case "${1:-}" in
	is-active) if st unit-active; then echo active; exit 0; fi; echo inactive; exit 3 ;;
	stop) root_or "Failed to stop ota-lite.service: Access denied" 1
		[ -n "${STUB_UNIT_STUCK:-}" ] || st_rm unit-active ;;
	*) exit 1 ;;
esac
''',
    "pgrep": r'''stub_log pgrep "$@"
[ "$*" = "-x qemu-system-aar" ] && [ -n "${STUB_QEMU:-}" ] && { echo 4242; exit 0; }
exit 1
''',
    "pkill": 'stub_log pkill "$@"\n',
    # procps cuts each line to $COLUMNS when it is set, unless the width is asked unlimited (-ww): a shim cut short loses its
    # -id, and a test that sets COLUMNS shows the harness asking
    "ps": r'''stub_log ps "$@"
wide=""; for a in "$@"; do [ "$a" != -ww ] || wide=1; done
shim() { echo "/usr/bin/containerd-shim-runc-v2 -namespace moby -id $1 -address /run/containerd/containerd.sock"; }
lines() {
	printf '%s\n' "/sbin/init" "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock"
	for f in "$STUB_DIR/containers"/*; do
		[ -e "$f" ] || continue
		shim "$(basename "$f")"
	done
	[ -z "${STUB_ORPHAN_SHIM:-}" ] || shim "$STUB_ORPHAN_SHIM"
}
if [ -n "${COLUMNS:-}" ] && [ -z "$wide" ]; then lines | cut -c1-"$COLUMNS"; else lines; fi
''',
    "sync": 'stub_log sync "$@"\n',
    "sleep": 'stub_log sleep "$@"\n',
    "id": r'''if [ "$*" = -nG ]; then
	stub_log id "$@"
	printf '%s\n' "${STUB_GROUPS-ubuntu adm sudo kvm docker}"; exit 0
fi
exec "$(real id)" "$@"
''',
    "date": r'''if [ "$*" = "+%s" ] && [ -r "$STUB_DIR/clock" ]; then
	t="$(cat "$STUB_DIR/clock")"
	if [ -n "${STUB_JUMP_RE:-}" ] && [ -r "${STUB_JUMP_FILE:-}" ] && grep -qE "$STUB_JUMP_RE" "$STUB_JUMP_FILE"; then t=$((t + STUB_JUMP_S)); fi
	echo "$t"; exit 0
fi
exec "$(real date)" "$@"
''',
    "timeout": r'''stub_log timeout "$@"
opts=()
while [ "${1#-}" != "$1" ]; do opts+=("$1"); shift; done
dur="$1"; shift
if [ -n "${STUB_CAP_RE:-}" ] && printf '%s' "$*" | grep -qE -e "$STUB_CAP_RE"; then
	# A cap that fires: cut to one second (or, with STUB_CAP_AT_ONCE, before it ran at all: lib-vss-deadline.sh runs
	# nothing and returns 124 for a cap of 0); then the clock reads the cap's end, stop_at + 10 minutes, as it does when a
	# real cap fires (lib-vss-deadline.sh: vss_cap_fired takes 124 or 137 for the cap's only from then on).
	rc=124
	[ -n "${STUB_CAP_AT_ONCE:-}" ] || { rc=0; "$(real timeout)" --kill-after=1s 1 "$@" || rc=$?; }
	if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then echo $(( $(cat "$QNX_METAL_DEADLINE_FILE") - 1500 + 600 )) > "$STUB_DIR/clock"; fi
	exit "$rc"
fi
exec "$(real timeout)" "${opts[@]}" "$dur" "$@"
''',
}

# python-build-standalone's python3 (setup's py312/): logged; `-m venv DIR` makes a venv whose python is the stand-in
# below; anything else runs this test's own Python (the proof, through the real ota_docker.py).
_PBS_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log pbs-python "$@"
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
	[ "${STUB_VENV_CREATE_RC:-0}" = 0 ] || { echo "Error: the stub's venv failure"; exit "$STUB_VENV_CREATE_RC"; }
	mkdir -p "$3/bin"; cp "$STUB_DIR/ota-python" "$3/bin/python"; chmod +x "$3/bin/python"; exit 0
fi
exec "$STUB_REAL_PY" "$@"
'''
# the updater's venv's python: pip answered here; anything else (drill.py) runs this test's own Python
_OTA_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log ota-python "$@"
if [ "${1:-}" = -m ] && [ "${2:-}" = pip ]; then
	case "${3:-}" in
		install) echo "Successfully installed grpcio-1.68.1 kuksa-client-0.6.0 protobuf-5.29.1"; exit "${STUB_PIP_RC:-0}" ;;
		freeze) printf '%s\n' "grpcio==1.68.1" "kuksa-client==0.6.0" "protobuf==5.29.1"; exit 0 ;;
	esac
	exit 2
fi
exec "$STUB_REAL_PY" "$@"
'''
# setup's sim venv's python (python-can's player, stack.py's interpreter): logged, then this test's own Python
_SIM_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log sim-python "$@"
exec "$STUB_REAL_PY" "$@"
'''

# sdv/stack/stack.py, a stand-in: its argv and SDV_ environment logged; prepare and up make their run directory and its
# manifest.json; up starts the stack's containers (but the app), down removes them (but with STUB_DOWN_LEAVE, which leaves
# them). STUB_<CMD>_RC its exit status.
_STACK = r'''#!/usr/bin/env python3
import datetime, json, os, sys
STUB = os.environ["STUB_DIR"]
argv = sys.argv[1:]
env = {k: v for k, v in sorted(os.environ.items()) if k.startswith("SDV_")}
with open(os.path.join(STUB, "calls.log"), "a") as f:
    f.write("stack.py\t%s\t%s\n" % (os.environ.get("STUB_VIA_SUDO", "0"), " ".join(argv)))
with open(os.path.join(STUB, "stack-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv, "env": env, "cwd": os.getcwd()}) + "\n")
cmd = argv[0]
rc = int(os.environ.get("STUB_%s_RC" % cmd.upper(), "0"))
C = os.path.join(STUB, "containers")
os.makedirs(C, exist_ok=True)
IDS = ["5a" * 32, "5b" * 32, "5c" * 32]
if cmd in ("prepare", "up"):
    name = argv[argv.index("--name") + 1]
    d = os.path.join(os.environ["SDV_RUNS"], "%s-%s" % (datetime.date.today().strftime("%Y%m%d"), name))
    os.makedirs(os.path.join(d, "in"))
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"run": os.path.basename(d), "host_role": env.get("SDV_HOST_ROLE"), "app": "external" if cmd == "up" else "stack"}, f)
    with open(os.path.join(d, "in", "sigsim.log"), "w") as f:
        f.write("(0.0) vcan0 123#00\n")
    if cmd == "up":
        with open(os.path.join(d, "ownership.json"), "w") as f:
            f.write("{}\n")
        for i in IDS:
            with open(os.path.join(C, i), "w") as f:
                f.write("sdv.stack.run")
elif cmd == "down" and not os.environ.get("STUB_DOWN_LEAVE"):
    for i in IDS:
        if os.path.exists(os.path.join(C, i)):
            os.remove(os.path.join(C, i))
print("stack.py stand-in: %s" % cmd)
sys.exit(rc)
'''

# sdv/drill/drill.py, WP3's, a stand-in by its command line: manifest writes --out; run refuses an
# existing --record, starts the updater's container and unit (as `unit start` would), writes the updater's log and state
# into --state, then (after STUB_DRILL_SLEEP seconds) the record, and at its end stops both (unless STUB_DRILL_LEAVE).
# STUB_STATE_ROOT_ONLY and STUB_RECORD_ROOT_ONLY leave the state's or the record's files of mode 0 (root's 0600 files, as
# the stub sudo reads them); STUB_DRILL_NO_RESULT leaves a record without drill-result.json and the status files;
# STUB_DRILL_BREAK_FACTS leaves a directory where the harness writes the drill's exit status next (<work>/facts/drill/
# exit.i, work being the directory of --state), so that write fails under set -e and the harness ends by its EXIT trap;
# STUB_DRILL_FACTS_FILE leaves a regular file where all the harness's facts of the drill unit go (<work>/facts/drill), so that
# not one of them can be written, the EXIT trap's own included; STUB_DRILL_BREAK_TOOL, as its last act, overwrites the
# harness's tool (<work>/drill-tool.py) with text that is not Python, so that drill.json cannot be written.
_DRILL = r'''#!/usr/bin/env python3
import json, os, sys, time
STUB = os.environ["STUB_DIR"]
argv = sys.argv[1:]
with open(os.path.join(STUB, "calls.log"), "a") as f:
    f.write("drill.py\t%s\t%s\n" % (os.environ.get("STUB_VIA_SUDO", "0"), " ".join(argv)))
with open(os.path.join(STUB, "drill-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\n")


def opt(k):
    return argv[argv.index(k) + 1] if k in argv else None


def wj(p, doc):
    with open(p, "w") as f:
        json.dump(doc, f)


cmd = argv[0]
if cmd == "manifest":
    rc = int(os.environ.get("STUB_MANIFEST_RC", "0"))
    if rc == 0:
        wj(opt("--out"), {"manifest_version": 1, "stand-in": True})
    sys.exit(rc)
rc = int(os.environ.get("STUB_DRILL_RC", "0"))
rec, state = opt("--record"), opt("--state")
if rc == 2 or os.path.exists(rec):
    print("drill.py: refused (the stand-in's): nothing started")
    sys.exit(2)
APP = os.path.join(STUB, "containers", "ab" * 32)
os.makedirs(os.path.dirname(APP), exist_ok=True)
with open(APP, "w") as f:
    f.write("sdv.ota.app")
os.makedirs(os.path.join(STUB, "state"), exist_ok=True)
open(os.path.join(STUB, "state", "unit-active"), "w").close()
with open(os.path.join(state, "ota-lite.jsonl"), "w") as f:
    f.write('{"event":"updater-start","host_role":"a1-metal"}\n')
wj(os.path.join(state, "state.json"), {"current": None, "starts": []})
if os.environ.get("STUB_STATE_ROOT_ONLY"):
    for n in ("ota-lite.jsonl", "state.json"):
        os.chmod(os.path.join(state, n), 0)
time.sleep(float(os.environ.get("STUB_DRILL_SLEEP", "0")))
os.makedirs(rec)
if not os.environ.get("STUB_DRILL_NO_RESULT"):
    steps = [{"n": n, "asks": "step %d" % n, "result": "applied"} for n in range(1, 7)]
    wj(os.path.join(rec, "drill-result.json"), {"format": 1, "verdict": "ok" if rc == 0 else "not ok", "steps": steps,
                                                 "problems": []})
    for n in range(1, 7):
        wj(os.path.join(rec, "status-%d.json" % n), {"image_id": None, "scenario": None, "result": "applied"})
with open(os.path.join(rec, "ota-lite.jsonl"), "w") as f:
    f.write('{"event":"updater-start","host_role":"a1-metal"}\n{"event":"updater-stop"}\n')
wj(os.path.join(rec, "state.json"), {"current": None, "starts": []})
if os.environ.get("STUB_RECORD_ROOT_ONLY"):
    for n in os.listdir(rec):
        os.chmod(os.path.join(rec, n), 0)
if not os.environ.get("STUB_DRILL_LEAVE"):
    os.remove(APP)
    os.remove(os.path.join(STUB, "state", "unit-active"))
if os.environ.get("STUB_DRILL_BREAK_FACTS"):
    os.makedirs(os.path.join(os.path.dirname(state), "facts", "drill", "exit.i"))
if os.environ.get("STUB_DRILL_FACTS_FILE"):
    open(os.path.join(os.path.dirname(state), "facts", "drill"), "w").close()
if os.environ.get("STUB_DRILL_BREAK_TOOL"):
    with open(os.path.join(os.path.dirname(state), "drill-tool.py"), "w") as f:
        f.write("this is not python (\n")
print("drill.py stand-in: verdict %s" % ("ok" if rc == 0 else "not ok"))
sys.exit(rc)
'''


def _write(p, text, mode=None):
    os.makedirs(os.path.dirname(str(p)), exist_ok=True)
    with open(str(p), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode is not None:
        os.chmod(str(p), mode)


def _repo_tar(path, commit):
    """The repo tarball as `git archive <commit>` writes one: the commit in a pax global header (git get-tar-commit-id)."""
    data = b"stand-in"
    with tarfile.open(str(path), "w", format=tarfile.PAX_FORMAT, pax_headers={} if commit is None else {"comment": commit}) as t:
        info = tarfile.TarInfo("orin-native/gpu-concurrency/README.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))


class Rig:
    """W as setup, quiesce, run-vss-setup.sh and the harness phase leave it for run-ota-drill.sh, the stubs, and the run."""

    def __init__(self, base, host_mode=None, setup_mode=None, skip=(), images=IMAGES):
        self.base = base
        self.w = base / "w"
        self.repo = self.w / "repo"
        self.g = self.repo / "orin-native" / "gpu-concurrency"
        self.stem = self.w / "rec" / "ota-drill"
        self.out = self.stem / "raw"
        self.status = self.stem / "status"
        self.runlog = self.stem / "run.log"
        self.setup = self.w / "rec" / "vss-setup"
        self.vss_in = self.w / "in"
        self.drill_in = self.w / "drill-in"
        self.vss_home = self.w / "sdv"
        self.stub = base / "stub"
        self.home = base / "home"
        self.tmp = base / "tmpdir"
        self.deadline = base / "deadline"
        self.l4t_release = base / "nv_tegra_release"          # L4T's release file and the device tree's compatible, which
        self.dt_compatible = base / "dt-compatible"           # mark a Jetson: absent unless a test writes them
        self.host_mode = host_mode
        for d in (self.g, self.stem, self.vss_in, self.drill_in, self.home, self.tmp, self.w / "img", self.stub / "state",
                  self.stub / "saves", self.stub / "containers"):
            os.makedirs(str(d), exist_ok=True)
        _write(self.vss_in / "bundle.json", '{"format": 1, "about": "the upload bundle (a stand-in)"}\n')
        if os.path.exists(HARNESS):
            shutil.copy(HARNESS, str(self.g / "run-ota-drill.sh"))
        for f in (LIB, VSS_SETUP):
            shutil.copy(f, str(self.g / os.path.basename(f)))
        sdv = self.repo / "sdv"
        os.makedirs(str(sdv / "ota"))
        shutil.copy(OTA_DOCKER, str(sdv / "ota" / "ota_docker.py"))
        _write(sdv / "ota" / "ota_lite.py", "# stand-in: drill.py runs the updater, never this harness\n")
        _write(sdv / "drill" / "drill.py", _DRILL)
        _write(sdv / "stack" / "stack.py", _STACK)
        os.makedirs(str(sdv / "apps" / "hard-brake-hazard"))
        shutil.copy(APP_LOCK, str(sdv / "apps" / "hard-brake-hazard" / "requirements.aarch64.lock"))
        self.pins_text = json.dumps(_pins(images), indent=1)
        _write(sdv / "drill" / "drill-images.json", self.pins_text)
        _repo_tar(self.w / "repo.tar", COMMIT)
        (self.w / "img" / "ifs-vss.bin").write_bytes(b"ifs-vss stand-in")
        (self.w / "img" / "disk-qemu").write_bytes(b"disk stand-in")
        for img in IMAGES:
            (self.stub / "saves" / (img["id"].split(":")[1] + ".tar")).write_bytes(_save(img))
        self.files = {}
        self.drill_files()
        self.inputs()
        self.setup_record(setup_mode if setup_mode is not None else host_mode, skip)
        _write(self.stem / "host-before.txt", "== a stand-in host-before\n")
        home = self.vss_home
        _write(home / "py312" / "python" / "bin" / "python3", _PBS_PYTHON, 0o755)
        _write(home / "venv" / "bin" / "python", _SIM_PYTHON, 0o755)
        _write(home / "gen" / "manifest.json", '{"stand-in": true}\n')
        dbc = b'VERSION ""\n'
        (home / "cache" / "dbc").mkdir(parents=True)
        (home / "cache" / "dbc" / ("%s.dbc" % _sha(dbc))).write_bytes(dbc)
        _write(home / "recordings" / RECORDING / "sigsim.log", "(0.0) vcan0 123#00\n")
        _write(self.stub / "_lib.sh", _LIB)
        for name, body in _STUBS.items():
            _write(self.stub / name, "#!/usr/bin/env bash\n. \"$STUB_DIR/_lib.sh\"\n" + body, 0o755)
        _write(self.stub / "ota-python", _OTA_PYTHON, 0o755)
        _write(self.stub / "clock", str(T0))
        self.ahead(180 * 60)

    def drill_files(self, tar=None, commit=COMMIT, sumline=None, pins=None):
        """W/drill-in's three drill files: drill-images.json (the repo's copy), sdv-drill.tar (by default
        `build_drill.py save`'s form, its docker save of the three pinned images in one tar) and its sha256 file."""
        tar = _save_many(IMAGES) if tar is None else tar
        (self.drill_in / "sdv-drill.tar").write_bytes(tar)
        _write(self.drill_in / "drill-images.json", self.pins_text if pins is None else pins)
        line = "%s  sdv-drill.tar" % _sha(tar) if sumline is None else sumline
        _write(self.drill_in / "sdv-drill.tar.sha256", line + "\n" + ("" if commit is None else "commit %s\n" % commit))
        self.files = {n: _sha((self.drill_in / n).read_bytes())
                      for n in ("drill-images.json", "sdv-drill.tar", "sdv-drill.tar.sha256")}

    def inputs(self, files=None):
        """inputs.env as drive-metal.sh's upload writes it, its FILES the drill's three and a bundle member."""
        f = dict(self.files, **{"bundle.json": "c" * 64}) if files is None else files
        _write(self.w / "inputs.env", "IFS_NAME=ifs-vss.bin\nIFS_SHA256=%s\nDISK_SHA256=%s\nREMOTE_LADDER_SHA256=%s\n"
               "CAPTURE_SHA256=%s\nREPO_COMMIT=%s\nFILES=%s\n" % ("a" * 64, "b" * 64, "d" * 64, "e" * 64, COMMIT,
                                                                 " ".join("%s:%s" % kv for kv in sorted(f.items()))))

    def setup_record(self, mode=None, skip=(), status="DONE", lines=("status=DONE",), done=True):
        """rec/vss-setup as run-vss-setup.sh and the detached runner leave it: an a1.metal setup records no host_mode."""
        doc = {"format": 1, "harness": "run-vss-setup.sh", "status": status, "skip_modes": sorted(skip),
               "skip": [{"mode": m, "step": "vcan", "reason": "the stub's"} for m in sorted(skip)]}
        if mode not in (None, "a1-metal"):
            doc = dict({"host_mode": mode}, **doc)
        _write(self.setup / "raw" / "setup.json", json.dumps(doc))
        _write(self.setup / "status", "".join(ln + "\n" for ln in lines))
        if done:
            (self.setup / "done").write_text("")
        elif (self.setup / "done").exists():
            (self.setup / "done").unlink()

    def ahead(self, seconds):
        """The deadline file: the stub clock's T0 plus this."""
        _write(self.deadline, str(T0 + seconds))

    def env(self, **cfg):
        drop = {k for k in os.environ if k.startswith(("STUB_", "VSS_", "SDV_", "QNX_"))} | {
            "PLAN", "K", "IMAGE", "STATUS", "OUT", "IFS_BIN", "DISK", "W", "COLUMNS"}
        e = {k: v for k, v in os.environ.items() if k not in drop}
        img = str(self.w / "img" / "ifs-vss.bin")
        e.update(W=str(self.w), IFS_BIN=img, IMG_S=img, IMG_B=img, DISK=str(self.w / "img" / "disk-qemu"),
                 VPROBE=str(self.w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), OUT=str(self.out), CSTATE="shallow",
                 VSS_IN=str(self.vss_in), DRILL_IN=str(self.drill_in), VSS_HOME=str(self.vss_home), STATUS=str(self.status),
                 QNX_METAL_DEADLINE_FILE=str(self.deadline), QNX_L4T_RELEASE_FILE=str(self.l4t_release),
                 QNX_DT_COMPATIBLE_FILE=str(self.dt_compatible), PATH=str(self.stub) + os.pathsep + os.environ["PATH"],
                 STUB_DIR=str(self.stub), STUB_REAL_PATH=os.environ["PATH"], STUB_REAL_PY=sys.executable,
                 STUB_JUMP_FILE=str(self.runlog), HOME=str(self.home), TMPDIR=str(self.tmp), PYTHONDONTWRITEBYTECODE="1")
        if self.host_mode is not None:
            e["VSS_HOST"] = self.host_mode
        e.update({k: str(v) for k, v in cfg.items()})
        return e

    def run(self, timeout=180, **cfg):
        with open(str(self.runlog), "ab") as log:
            p = subprocess.run([BASH, str(self.g / "run-ota-drill.sh")], stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, cwd=str(self.g), env=self.env(**cfg), timeout=timeout)
        return Result(self, p.returncode)


class Result:
    def __init__(self, rig, rc):
        self.rig, self.rc = rig, rc
        self.log = rig.runlog.read_text(encoding="utf-8", errors="replace") if rig.runlog.exists() else ""
        self.status = rig.status.read_text(encoding="utf-8").splitlines() if rig.status.exists() else []
        p = rig.out / "drill.json"
        self.doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        cl = rig.stub / "calls.log"
        self.calls = [tuple(ln.split("\t", 2)) for ln in cl.read_text(encoding="utf-8").splitlines()] if cl.exists() else []
        self.stack = self._jsonl("stack-calls.jsonl")
        self.drill = self._jsonl("drill-calls.jsonl")

    def _jsonl(self, name):
        p = self.rig.stub / name
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def why(self):
        return "rc %s, status %s\n%s" % (self.rc, self.status, self.log[-4000:])

    def idx(self, name, pattern=""):
        """The index in calls.log of the first call of NAME whose arguments match PATTERN (-1 when none)."""
        for i, (n, _v, args) in enumerate(self.calls):
            if n == name and re.search(pattern, args):
                return i
        return -1

    def unit(self, name):
        return [u for u in self.doc["units"] if u["name"] == name][0]

    def containers(self):
        return sorted(os.listdir(str(self.rig.stub / "containers")))


def _strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _snapshot(base):
    got = {}
    for root, _dirs, files in os.walk(str(base)):
        for n in files:
            p = os.path.join(root, n)
            with open(p, "rb") as f:
                got[os.path.relpath(p, str(base)).replace(os.sep, "/")] = hashlib.sha256(f.read()).hexdigest()
    return got


@pytest.fixture(scope="module")
def done(tmp_path_factory):
    """One whole run with every stub answering as a bare-metal instance should, VSS_HOST unset: the run most tests read."""
    rig = Rig(tmp_path_factory.mktemp("done"))
    before = _snapshot(rig.base)
    res = rig.run()
    res.before, res.after = before, _snapshot(rig.base)
    return res


# --- a whole run ---------------------------------------------------------------------------------------------------

def test_a_whole_run_ends_done_with_drill_json_written_first(done):
    assert done.rc == 0 and done.status == ["status=DONE"], done.why()
    d = done.doc
    assert d is not None and d["harness"] == "run-ota-drill.sh" and d["format"] == 1, done.why()
    assert (d["status"], d["status_line"], d["at"], d["reason"]) == ("DONE", "status=DONE", None, None)
    assert [u["name"] for u in d["units"]] == UNITS and all(u["state"] == "ran" for u in d["units"]), d["units"]
    assert d["not_run"] == [] and d["host_mode"] == "a1-metal"
    assert done.log.rstrip().splitlines()[-1].endswith("status=DONE"), done.log[-2000:]


def _capped(res, pattern):
    """The index of the timeout line (lib-vss-deadline.sh's cap: --kill-after=30s, then the cap) whose command matches."""
    return res.idx("timeout", r"^--kill-after=30s %d %s" % (CAP, pattern))


CAPPED = [
    ("load", r"sudo -n docker load -i \S+/w/drill-in/sdv-drill\.tar$"),
    ("prove", r"\S+/w/sdv/py312/python/bin/python3 -B \S+/drill-tool\.py prove "),
    ("venv", r"\S+/w/sdv/py312/python/bin/python3 -m venv \S+/w/sdv/ota-venv$"),
    ("pip", r"\S+/w/sdv/ota-venv/bin/python -m pip install "),
    ("freeze", r"\S+/w/sdv/ota-venv/bin/python -m pip freeze "),
    ("prepare", r"env .*\S+/w/sdv/venv/bin/python \S+/sdv/stack/stack\.py prepare "),
    ("up", r"env .*\S+/w/sdv/venv/bin/python \S+/sdv/stack/stack\.py up "),
    ("manifest", r"\S+/w/sdv/ota-venv/bin/python \S+/sdv/drill/drill\.py manifest "),
    ("drill", r"\S+/w/sdv/ota-venv/bin/python \S+/sdv/drill/drill\.py run "),
    ("down", r"env .*\S+/w/sdv/venv/bin/python \S+/sdv/stack/stack\.py down$"),
]


def test_the_units_run_in_order_each_under_its_cap(done):
    """Each unit under vss_capped, in the harness's order."""
    at = [(name, _capped(done, pat)) for name, pat in CAPPED]
    assert all(i >= 0 for _n, i in at), [n for n, i in at if i < 0]
    assert [i for _n, i in at] == sorted(i for _n, i in at), at
    # and each command ran after its timeout line, inside it
    assert done.idx("docker", r"^load -i ") > _capped(done, CAPPED[0][1])
    assert done.idx("drill.py", r"^run ") > _capped(done, CAPPED[8][1])
    assert done.idx("stack.py", r"^down$") > _capped(done, CAPPED[9][1])


def test_the_drill_tar_is_loaded_under_sudo_and_each_pin_proved_by_its_config_digest(done):
    load = [c for c in done.calls if c[0] == "docker" and c[2].startswith("load ")]
    assert load == [("docker", "1", "load -i %s" % (done.rig.drill_in / "sdv-drill.tar"))], load
    saves = [c[2] for c in done.calls if c[0] == "docker" and c[2].startswith("save ")]
    assert saves == ["save " + img["id"] for img in IMAGES], saves           # three distinct pins, v1 counted once
    assert all(c[1] == "1" for c in done.calls if c[0] == "docker"), "every docker call of the harness under sudo -n"
    assert done.unit("load")["proved"] == 3 and done.unit("load")["load_exit"] == 0
    assert done.doc["preflight"]["pins"] == 3


def test_the_updaters_venv_is_made_from_setups_python_with_hashes_and_binaries_only(done):
    pip = [c[2] for c in done.calls if c[0] == "ota-python" and c[2].startswith("-m pip install ")]
    assert len(pip) == 1, pip
    words = pip[0].split()
    for w in ("--require-hashes", "--no-deps", "--only-binary=:all:", "--no-input"):
        assert w in words, (w, pip)
    assert words[words.index("-r") + 1] == str(done.rig.repo / "sdv" / "apps" / "hard-brake-hazard" /
                                              "requirements.aarch64.lock")
    assert not [w for w in words if w.startswith(("--cache-dir", "--no-cache"))], "pip's cache stays its default, outside the record"
    venv = (done.rig.out / "venv.txt").read_text(encoding="utf-8")
    assert "Successfully installed grpcio-1.68.1 kuksa-client-0.6.0" in venv and "kuksa-client==0.6.0" in venv, venv
    assert done.unit("venv")["pip_install_exit"] == 0 and done.unit("venv")["pip_freeze_exit"] == 0


def test_the_stack_comes_up_without_the_app_by_its_loaded_images_on_the_hosts_role(done):
    w, home = done.rig.w, done.rig.vss_home
    assert [c["argv"] for c in done.stack] == [
        ["prepare", "--images", "loaded", "--name", "ota-drill-prepare"],
        ["up", "--feed", "vcan", "--app", "external", "--images", "loaded", "--name", "ota-drill"],
        ["down"]], done.stack
    base = {"SDV_HOST_ROLE": "a1-metal", "SDV_GEN": str(home / "gen"), "SDV_CACHE": str(home / "cache"),
            "SDV_SIM_VENV": str(home / "venv"), "SDV_RUNS": str(home / "drill-work" / "runs"),
            "SDV_RECORDING": str(home / "recordings" / RECORDING)}
    assert done.stack[0]["env"] == base and done.stack[2]["env"] == base, done.stack
    assert done.stack[1]["env"] == dict(base, SDV_SPOOL_DIR="/run/sdv-local/spool/v1",
                                        SDV_STATUS_DIR="/run/sdv-local/status/v1"), done.stack[1]
    assert all(c["cwd"] == str(w / "repo") for c in done.stack)


def test_the_drill_is_called_by_its_interface_on_tar_transport_and_local_spool_records(done):
    """The drill's command line, word for word; no --cpuset (off the Orin the stack and the updater take none)."""
    home = done.rig.vss_home
    work = home / "drill-work"
    stack_run = str(work / "runs" / ("%s-ota-drill" % datetime.date.today().strftime("%Y%m%d")))
    assert [c["argv"] for c in done.drill] == [
        ["manifest", "--host-role", "a1-metal", "--arch", "arm64", "--transport", "tar", "--stack-run", stack_run,
         "--out", str(work / "manifest.json"), "--pins", str(done.rig.drill_in / "drill-images.json"),
         "--tar", str(done.rig.drill_in / "sdv-drill.tar")],
        ["run", "--manifest", str(work / "manifest.json"), "--state", str(work / "ota-state"), "--record", str(work / "record"),
         "--stack-run", stack_run, "--sim-python", str(home / "venv" / "bin" / "python"),
         "--ota-python", str(home / "ota-venv" / "bin" / "python"), "--via", "spool",
         "--spool-dir", "/run/sdv-local/spool/v1", "--status-dir", "/run/sdv-local/status/v1", "--sudo", "sudo -n"]], done.drill
    assert done.unit("up")["stack_run"] == os.path.basename(stack_run), done.unit("up")
    assert done.unit("drill")["exit"] == 0 and done.doc["record"]["verdict"] == "ok"
    assert not [w for c in done.drill for w in c["argv"] if "cpuset" in w or w.startswith("--cpus")]


def test_the_record_holds_exactly_its_files(done):
    """drill-result.json, the updater's log and state, the status files the run kept, the up
    run's manifest.json, venv.txt and drill.json, and nothing else."""
    got = sorted(os.listdir(str(done.rig.out)))
    assert got == sorted(RECORD_FILES + ["manifest.json", "venv.txt", "drill.json"]), got
    man = json.loads((done.rig.out / "manifest.json").read_text(encoding="utf-8"))
    assert man["app"] == "external" and man["run"].endswith("-ota-drill"), man
    assert done.doc["record"]["kept"] == sorted(RECORD_FILES + ["manifest.json"]), done.doc["record"]


def test_every_file_of_the_record_is_on_captures_whitelist_and_nothing_else_of_the_stem(done, tmp_path):
    """capture.py, run on a copy of the session's rec (done touched, a redactor that changes nothing), publishes every
    file the harness wrote, and of the stem's own files run.log and status (host-before.txt and host-after.txt too)."""
    rec = tmp_path / "rec"
    shutil.copytree(str(done.rig.w / "rec"), str(rec))
    (rec / "ota-drill" / "done").write_text("")
    _write(rec / "ota-drill" / "host-after.txt", "== a stand-in host-after\n")
    _write(rec / "ota-drill" / "detach.log", "[05:00:00] _detached: run-ota-drill.sh starts\n")
    _write(rec / "ota-drill" / "raw" / "notes.txt", "an unlisted file\n")
    _write(rec / "vss-setup" / "raw" / "setup.json", json.dumps({"status": "DONE"}))
    _write(tmp_path / "red.sh", "cat\n")
    p = subprocess.run([sys.executable, CAPTURE, str(rec), str(tmp_path / "pub"), str(tmp_path / "red.sh")],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "ota-drill: DONE (status=DONE, with raw/drill.json)" in p.stdout, p.stdout
    excluded = sorted(ln for ln in p.stdout.splitlines() if ln.startswith("excluded: ota-drill/"))
    assert excluded == ["excluded: ota-drill/detach.log (not on the vss whitelist)",
                        "excluded: ota-drill/done (not on the vss whitelist)",
                        "excluded: ota-drill/raw/notes.txt (not on the vss whitelist)"], excluded
    pub = tmp_path / "pub"
    published = sorted(os.path.relpath(os.path.join(a, n), str(pub)).replace(os.sep, "/")
                       for a, _d, fs in os.walk(str(pub)) for n in fs if a.startswith(str(pub / "ota-drill")))
    assert published == sorted(["ota-drill/" + n for n in ("host-after.txt", "host-before.txt", "run.log", "status")]
                               + ["ota-drill/raw/" + n for n in RECORD_FILES + ["manifest.json", "venv.txt", "drill.json"]])


def test_a_done_run_still_sweeps_the_unit_the_containers_and_their_shims(done):
    stop = done.doc["stop"]
    assert stop == {"swept": True, "unit_state_before": "inactive", "unit_state_after": "inactive", "unit_inactive": True,
                    "containers_list_exit": 0, "containers_found": 0, "containers_removed": True, "shims_list_exit": 0,
                    "shims_left": 0, "verified": True}, stop
    i = done.idx("systemctl", r"^is-active ota-lite$")
    assert i > done.idx("stack.py", r"^down$") >= 0
    lists = [c[2] for c in done.calls if c[0] == "docker" and c[2].startswith("ps ")]
    assert lists == ["ps -aq --no-trunc --filter label=sdv.ota.app", "ps -aq --no-trunc --filter label=sdv.stack.run",
                     "ps -aq --no-trunc"], lists
    assert done.containers() == []


def test_drill_json_strings_are_one_line_and_durations_sit_under_operational_s(done):
    assert all("\n" not in s and "\r" not in s for s in _strings(done.doc))
    for u in done.doc["units"]:
        assert set(u["operational_s"]) == {u["name"]} and isinstance(u["operational_s"][u["name"]], int), u
    assert "no field is a measurement" in done.doc["note"]


def test_nothing_is_written_outside_out_status_vss_home_and_the_stubs(done):
    r = done.rig
    allowed = [os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") + "/" for p in (r.out, r.vss_home, r.stub)]
    allowed_files = {os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") for p in (r.status, r.runlog)}
    changed = sorted(p for p in set(done.after) | set(done.before) if done.after.get(p) != done.before.get(p))
    outside = [p for p in changed if p not in allowed_files and not any(p.startswith(a) for a in allowed)]
    assert outside == [], outside
    assert os.listdir(str(r.home)) == [] and os.listdir(str(r.tmp)) == []
    assert not [p for p in done.after if "__pycache__" in p], "no bytecode written into the session's tree"


# --- the host modes ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [None, "a1-metal", "c7g-metal"], ids=["unset", "a1-metal", "c7g-metal"])
def test_the_host_mode_is_the_drills_role_everywhere_and_never_assumed(tmp_path, mode):
    """VSS_HOST names the role (a1-metal or c7g-metal; unset is a1-metal): stack.py's SDV_HOST_ROLE, drill.py's
    --host-role, drill.json's host_mode. c7g-metal is never read as a1-metal."""
    want = mode or "a1-metal"
    res = Rig(tmp_path, host_mode=mode).run()
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert {c["env"]["SDV_HOST_ROLE"] for c in res.stack} == {want}, res.stack
    roles = [c["argv"][c["argv"].index("--host-role") + 1] for c in res.drill if "--host-role" in c["argv"]]
    assert roles == [want], res.drill
    assert res.doc["host_mode"] == want and res.doc["preflight"]["setup_host_mode"] == want


@pytest.mark.parametrize("mode", ["orin", "", "c7g.metal", "a1.metal", "laptop"])
def test_a_mode_other_than_the_two_bare_metal_roles_is_refused_before_the_preflight(tmp_path, mode):
    res = Rig(tmp_path, host_mode=mode).run()
    assert res.rc == 1 and res.status == ["status=FAILED at=preflight"], res.why()
    assert "is none of a1-metal and c7g-metal" in res.log, res.log
    assert not [c for c in res.calls if c[0] in ("docker", "stack.py", "drill.py", "pbs-python", "id")], res.calls


JETSON = [
    ("l4t-release", "# R39 (release), REVISION: 2.1, GCID: 0, BOARD: generic, EABI: aarch64\n", None, True),
    ("nvidia-device-tree", None, b"nvidia,p3768-0000+p3767-0005-super\0nvidia,p3767-0005\0nvidia,tegra234\0", True),
    # a device tree that is no NVIDIA board's (QEMU's virt board here) marks no Jetson
    ("other-device-tree", None, b"linux,dummy-virt\0", False),
]


@pytest.mark.parametrize("mode", [None, "c7g-metal"], ids=["unset", "c7g-metal"])
@pytest.mark.parametrize("what,release,compatible,refused", JETSON, ids=[j[0] for j in JETSON])
def test_either_role_is_refused_on_a_host_l4t_or_an_nvidia_device_tree_marks_as_a_jetson(tmp_path, what, release,
                                                                                          compatible, refused, mode):
    """HOST-NEUTRAL: the bare-metal drill is not the board's (WP7's helper runs that one). A host whose L4T release file
    exists, or whose device tree's first compatible is an NVIDIA board's, is refused before the preflight with either
    role, nothing called; another device tree refuses nothing."""
    rig = Rig(tmp_path, host_mode=mode)
    if release is not None:
        _write(rig.l4t_release, release)
    if compatible is not None:
        rig.dt_compatible.write_bytes(compatible)
    res = rig.run()
    if not refused:
        assert res.rc == 0 and res.status == ["status=DONE"], res.why()
        return
    assert res.rc == 1 and res.status == ["status=FAILED at=preflight"], res.why()
    assert "VSS_HOST=%s on a host that L4T's release file or an NVIDIA device tree marks as a Jetson" % (mode or "a1-metal") \
        in res.log, res.log[-2000:]
    assert not [c for c in res.calls if c[0] in ("docker", "stack.py", "drill.py", "pbs-python", "ota-python", "id")], res.calls
    assert res.doc["at"] == "preflight" and res.doc["not_run"] == UNITS and res.doc["stop"]["swept"] is False, res.doc


# --- the preflight -------------------------------------------------------------------------------------------------

def _no_deadline(rig):
    rig.deadline.unlink()


def _files(rig, **over):
    rig.inputs(dict(rig.files, **over))


def _pins_differ(rig):
    _write(rig.repo / "sdv" / "drill" / "drill-images.json", rig.pins_text.replace('"format": 1', '"format": 2'))


PREFLIGHT = [
    ("no-deadline", _no_deadline, {}, "no readable deadline file"),
    ("no-docker-group", None, {"STUB_GROUPS": "ubuntu adm sudo kvm"}, "this login is not in the docker group"),
    # the group is a word of `id -nG`, not a substring of one: dockerd is a group of some other host's, not docker
    ("no-docker-group-dockerd", None, {"STUB_GROUPS": "ubuntu adm sudo kvm dockerd"}, "this login is not in the docker group"),
    ("setup-not-done", lambda r: r.setup_record(done=False), {}, "has no done: run-vss-setup.sh has not finished"),
    ("setup-timeout", lambda r: r.setup_record(lines=("status=TIMEOUT at=30min-rule reason=30min-rule",)), {},
     "not status=DONE"),
    ("setup-failed-last", lambda r: r.setup_record(lines=("status=DONE", "status=FAILED rc=0")), {}, "not status=DONE"),
    ("setup-json-not-done", lambda r: r.setup_record(status="TIMEOUT"), {}, "says status 'TIMEOUT', not DONE"),
    ("setup-json-missing", lambda r: (r.setup / "raw" / "setup.json").unlink(), {}, "cannot be read"),
    ("setup-c7g-for-a1", lambda r: r.setup_record(mode="c7g-metal"), {}, "records host mode c7g-metal"),
    ("setup-orin", lambda r: r.setup_record(mode="orin"), {}, "records host mode orin"),
    ("skip-broker", lambda r: r.setup_record(skip=("broker", "can")), {}, "skip list holds broker, can"),
    ("skip-broker-only", lambda r: r.setup_record(skip=("broker",)), {}, "skip list holds broker:"),
    ("skip-can", lambda r: r.setup_record(skip=("can",)), {}, "skip list holds can"),
    ("no-skip-list", lambda r: _write(r.setup / "raw" / "setup.json", json.dumps({"status": "DONE"})), {},
     "holds no skip list"),
    ("qemu", None, {"STUB_QEMU": "1"}, "a QEMU runs"),
    ("tar-not-in-files", lambda r: r.inputs({k: v for k, v in r.files.items() if k != "sdv-drill.tar"}), {},
     "sdv-drill.tar is not among inputs.env's FILES"),
    ("tar-wrong-hash", lambda r: _files(r, **{"sdv-drill.tar": "0" * 64}), {}, "sdv-drill.tar's sha256 is not inputs.env's"),
    ("pins-wrong-hash", lambda r: _files(r, **{"drill-images.json": "0" * 64}), {},
     "drill-images.json's sha256 is not inputs.env's"),
    ("sum-wrong-hash", lambda r: _files(r, **{"sdv-drill.tar.sha256": "0" * 64}), {},
     "sdv-drill.tar.sha256's sha256 is not inputs.env's"),
    ("tar-missing", lambda r: (r.drill_in / "sdv-drill.tar").unlink(), {}, "no drill-in/sdv-drill.tar"),
    ("no-files-line", lambda r: _write(r.w / "inputs.env", "IFS_NAME=ifs-vss.bin\nREPO_COMMIT=%s\n" % COMMIT), {},
     "inputs.env names no FILES"),
    ("sum-not-the-tars", lambda r: (r.drill_files(sumline="%s  sdv-drill.tar" % ("f" * 64)), r.inputs()), {},
     "names sha256 %s, and sdv-drill.tar's is " % ("f" * 64)),
    ("sum-two-hashes", lambda r: (r.drill_files(sumline="%s  sdv-drill.tar\n%s  sdv-drill.tar" % ("f" * 64, "f" * 64)),
                                  r.inputs()), {}, "holds 2 sha256 lines"),
    ("sum-no-commit", lambda r: (r.drill_files(commit=None), r.inputs()), {}, "holds 0 commit lines"),
    # one commit line only: the sum file's own, here a second beside the one the rig writes (both right, its tar line right)
    ("sum-two-commits", lambda r: (r.drill_files(sumline="%s  sdv-drill.tar\ncommit %s" % (_sha(_save_many(IMAGES)), COMMIT)),
                                   r.inputs()), {}, "holds 2 commit lines"),
    # the sum file is its two lines and nothing else: a third, whatever it says, is refused (its tar line here is right)
    ("sum-junk-line", lambda r: (r.drill_files(sumline="%s  sdv-drill.tar\nbuilt on the PC" % _sha(_save_many(IMAGES))),
                                 r.inputs()),
     {}, "holds a line that is neither its tar's sha256 nor its commit"),
    ("commit-mismatch", lambda r: (r.drill_files(commit="f" * 40), r.inputs()), {},
     "sdv-drill.tar was built at commit %s and the repo tarball is %s" % ("f" * 40, COMMIT)),
    ("repo-tar-no-commit", lambda r: _repo_tar(r.w / "repo.tar", None), {}, "the repo tarball carries no commit"),
    # a pax comment that is no commit (not 40 hex) is no commit either
    ("repo-tar-bad-commit", lambda r: _repo_tar(r.w / "repo.tar", "not-a-commit"), {}, "the repo tarball carries no commit"),
    ("pins-not-the-repos", _pins_differ, {}, "in/drill-images.json differs from the repo tarball's sdv/drill/drill-images.json"),
    ("no-pins", lambda r: (_write(r.repo / "sdv" / "drill" / "drill-images.json", "{}"),
                           r.drill_files(pins="{}"), r.inputs()), {}, "drill-images.json names no pin"),
    ("no-drill", lambda r: (r.repo / "sdv" / "drill" / "drill.py").unlink(), {}, "no repo/sdv/drill/drill.py"),
    # the other two files of the repo tarball the run calls: the proof of a pin (ota_docker.py) and the stack (stack.py)
    ("no-ota-docker", lambda r: (r.repo / "sdv" / "ota" / "ota_docker.py").unlink(), {}, "no repo/sdv/ota/ota_docker.py"),
    ("no-stack", lambda r: (r.repo / "sdv" / "stack" / "stack.py").unlink(), {}, "no repo/sdv/stack/stack.py"),
    ("no-app-lock", lambda r: (r.repo / "sdv" / "apps" / "hard-brake-hazard" / "requirements.aarch64.lock").unlink(), {},
     "no repo/sdv/apps/hard-brake-hazard/requirements.aarch64.lock"),
    ("no-sim-venv", lambda r: (r.vss_home / "venv" / "bin" / "python").unlink(), {}, "no VSS_HOME/venv/bin/python"),
    ("no-py312", lambda r: (r.vss_home / "py312" / "python" / "bin" / "python3").unlink(), {},
     "no VSS_HOME/py312/python/bin/python3"),
    ("no-recording", lambda r: shutil.rmtree(str(r.vss_home / "recordings")), {},
     "no VSS_HOME/recordings/%s/sigsim.log" % RECORDING),
    ("no-dbc", lambda r: shutil.rmtree(str(r.vss_home / "cache")), {}, "no VSS_HOME/cache/dbc/<sha256>.dbc"),
    ("no-gen", lambda r: shutil.rmtree(str(r.vss_home / "gen")), {}, "no VSS_HOME/gen/manifest.json"),
    ("venv-exists", lambda r: os.makedirs(str(r.vss_home / "ota-venv")), {}, "VSS_HOME/ota-venv exists already"),
    # the tar is one save of the three pinned IDs: its index.json lists exactly the pins' IDs, drill.py manifest's
    # first check of it (WP3's check_save) made here before anything starts; a tar of other images is refused
    ("tar-one-image", lambda r: (r.drill_files(tar=_save(IMAGES[0])), r.inputs()), {},
     "sdv-drill.tar's index.json lists other images than drill-images.json's pins (1 listed, 3 pinned)"),
    ("tar-other-image", lambda r: (r.drill_files(tar=_save_many(IMAGES[:2] + [_image("9.9.9")])), r.inputs()), {},
     "sdv-drill.tar's index.json lists other images than drill-images.json's pins (3 listed, 3 pinned)"),
    ("tar-a-pin-twice", lambda r: (r.drill_files(tar=_save_many(IMAGES + IMAGES[:1])), r.inputs()), {},
     "sdv-drill.tar's index.json lists other images than drill-images.json's pins (4 listed, 3 pinned)"),
    ("tar-no-index", lambda r: (r.drill_files(tar=_tar({"manifest.json": b"[]", "oci-layout": b"{}"})), r.inputs()), {},
     "sdv-drill.tar holds no index.json listing its images: it is not docker save's OCI layout"),
    ("tar-not-a-tar", lambda r: (r.drill_files(tar=b"not a tar"), r.inputs()), {}, "sdv-drill.tar cannot be read as a tar"),
]


@pytest.mark.parametrize("what,change,cfg,msg", PREFLIGHT, ids=[p[0] for p in PREFLIGHT])
def test_the_preflight_refuses(tmp_path, what, change, cfg, msg):
    """Every refusal is status=FAILED at=preflight before anything starts, with its record."""
    rig = Rig(tmp_path)
    if change is not None:
        change(rig)
    res = rig.run(**cfg)
    assert res.rc == 1 and res.status == ["status=FAILED at=preflight"], res.why()
    assert msg in res.log, (msg, res.log[-3000:])
    assert not [c for c in res.calls if c[0] in ("docker", "stack.py", "drill.py", "pbs-python", "ota-python", "systemctl",
                                                  "pkill")], res.calls
    assert res.doc is not None and res.doc["status"] == "FAILED" and res.doc["at"] == "preflight", res.why()
    assert res.doc["not_run"] == UNITS and res.doc["stop"] == {"swept": False, "why": "no unit began: nothing to sweep"}


def test_a_qemu_that_runs_is_refused_and_left_running(tmp_path):
    res = Rig(tmp_path).run(STUB_QEMU="1")
    assert res.status == ["status=FAILED at=preflight"] and res.doc["preflight"]["qemu_running"] is True, res.why()
    assert res.idx("pkill") == -1 and res.idx("sudo", "pkill") == -1


def test_the_preflight_records_what_it_read(done):
    p = done.doc["preflight"]
    assert p["docker_group"] is True and p["setup_done"] is True and p["setup_status_line"] == "status=DONE"
    assert p["setup_host_mode"] == "a1-metal" and p["skip_modes"] == [] and p["qemu_running"] is False
    assert p["drill_tar_commit"] == COMMIT and p["repo_commit"] == COMMIT and p["recording"] == RECORDING
    assert p["drill_files"] == ["%s %s" % (n, done.rig.files[n]) for n in ("drill-images.json", "sdv-drill.tar",
                                                                              "sdv-drill.tar.sha256")], p
    assert p["pins"] == 3 and p["drill_tar_images"] == 3, p
    assert "drill_tar_manifest" not in p, "no one-image reading of the tar: the drill's tar holds the three images"


def test_spec_2_2_3s_tar_the_save_of_the_three_pinned_images_ends_done_with_three_pins_proved(tmp_path):
    """`build_drill.py save` writes one docker save of the three arm64 IDs, the metal session's transport, and
    the drill takes it as one --tar. drill.py manifest (WP3's) checks it against the pins and splits it into one tar per version
    (the updater's tar transport takes a tar of one image), so the harness refuses no save for holding three images and
    hands it over whole: the run ends DONE with the three pins proved, and drill.py manifest gets the session's own tar."""
    rig = Rig(tmp_path)
    tar = _save_many(IMAGES)
    rig.drill_files(tar=tar)
    rig.inputs()
    res = rig.run()
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        listed = json.loads(t.extractfile("index.json").read())["manifests"]
    assert [d["digest"] for d in listed] == [img["id"] for img in IMAGES]
    assert res.unit("load")["proved"] == 3 and res.doc["preflight"]["drill_tar_images"] == 3, res.doc
    saves = [c[2] for c in res.calls if c[0] == "docker" and c[2].startswith("save ")]
    assert saves == ["save " + img["id"] for img in IMAGES], saves
    man = [c["argv"] for c in res.drill if c["argv"][0] == "manifest"]
    assert len(man) == 1 and man[0][man[0].index("--tar") + 1] == str(rig.drill_in / "sdv-drill.tar"), man
    assert (rig.drill_in / "sdv-drill.tar").read_bytes() == tar and res.doc["record"]["verdict"] == "ok"


def test_a_setup_whose_skip_list_holds_only_replay_is_taken(tmp_path):
    """Only broker and can need vcan0; a mode the drill does not use in the skip list refuses nothing."""
    res = Rig(tmp_path, skip=("replay",)).run()
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert res.doc["preflight"]["skip_modes"] == ["replay"]


def test_a_c7g_metal_drill_refuses_an_a1_metal_setup(tmp_path):
    res = Rig(tmp_path, host_mode="c7g-metal", setup_mode="a1-metal").run()
    assert res.status == ["status=FAILED at=preflight"], res.why()
    assert "records host mode a1-metal" in res.log and "not this drill's c7g-metal" in res.log, res.log


def test_a_sum_file_in_the_form_git_bashs_sha256sum_prints_is_taken(tmp_path):
    """sha256sum in binary mode, Git Bash's on the PC, prints `<64 hex> *sdv-drill.tar`: taken as the two-space form is,
    so a sum file written there does not spend the session's one drill run on a preflight refusal."""
    rig = Rig(tmp_path)
    tar = (rig.drill_in / "sdv-drill.tar").read_bytes()
    rig.drill_files(tar=tar, sumline="%s *sdv-drill.tar" % _sha(tar))
    rig.inputs()
    res = rig.run()
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert res.doc["preflight"]["drill_tar_commit"] == COMMIT


def test_the_drill_reads_its_files_from_drill_in_and_nothing_from_setups_bundle_directory(tmp_path):
    """The drill's three files are in DRILL_IN (remote-ladder.sh's setup moved them out of in/, which setup's bundle.py
    verify takes whole): the harness reads nothing from VSS_IN, and runs whole with VSS_IN naming no directory."""
    rig = Rig(tmp_path)
    res = rig.run(VSS_IN=str(rig.base / "no-such-directory"))
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert res.doc["preflight"]["drill_files"] == ["%s %s" % (n, rig.files[n]) for n in ("drill-images.json", "sdv-drill.tar",
                                                                                          "sdv-drill.tar.sha256")]
    with open(HARNESS, encoding="utf-8") as f:
        assert "VSS_IN" not in _code(f.read()), "the harness reads no file of setup's bundle directory"


def test_a_second_start_by_hand_is_refused_before_it_touches_the_first_runs_work(tmp_path):
    """The harness phase starts the drill once per session; a start by hand after a run that began its units is refused
    first, before drill-work (the first run's drill record and the updater's state) or the record is touched."""
    rig = Rig(tmp_path)
    first = rig.run()
    assert first.status == ["status=DONE"], first.why()
    work = rig.vss_home / "drill-work"
    kept, doc, calls = _snapshot(work), (rig.out / "drill.json").read_bytes(), len(first.calls)
    res = rig.run()
    assert res.rc == 1 and res.status == ["status=DONE", "status=FAILED at=preflight"], res.why()
    assert "VSS_HOME/drill-work holds an earlier run that began its units" in res.log, res.log[-2000:]
    assert _snapshot(work) == kept and (rig.out / "drill.json").read_bytes() == doc
    assert (work / "record" / "drill-result.json").exists() and len(res.calls) == calls, res.calls[calls:]


# --- a unit that fails, a result, the deadline ----------------------------------------------------------------------

FAILS = [
    ("load", {"STUB_LOAD_RC": "1"}, None, "sudo -n docker load of sdv-drill.tar exited 1"),
    ("load", {}, "prove", "a pinned image's config digest was not proved"),
    ("venv", {"STUB_VENV_CREATE_RC": "1"}, None, "python -m venv from setup's py312 exited 1"),
    ("venv", {"STUB_PIP_RC": "1"}, None, "pip install exited 1"),
    ("prepare", {"STUB_PREPARE_RC": "1"}, None, "stack.py prepare exited 1"),
    ("up", {"STUB_UP_RC": "1"}, None, "stack.py up exited 1"),
    ("manifest", {"STUB_MANIFEST_RC": "2"}, None, "drill.py manifest exited 2"),
    ("drill", {"STUB_DRILL_RC": "2"}, None, "drill.py run refused (exit 2)"),
    ("drill", {"STUB_DRILL_RC": "3"}, None, "drill.py run exited 3"),
    # exit 0 or 1 says the run wrote its record, whose first file is drill-result.json
    ("drill", {"STUB_DRILL_NO_RESULT": "1"}, None, "drill.py run exited 0 and left no drill-result.json in its record"),
    ("drill", {"STUB_DRILL_NO_RESULT": "1", "STUB_DRILL_RC": "1"}, None,
     "drill.py run exited 1 and left no drill-result.json in its record"),
]


@pytest.mark.parametrize("unit,cfg,special,msg", FAILS, ids=["%s-%d" % (f[0], i) for i, f in enumerate(FAILS)])
def test_a_unit_that_fails_ends_failed_and_still_sweeps(tmp_path, unit, cfg, special, msg):
    rig = Rig(tmp_path)
    if special == "prove":                         # the second pin's saved config is not the pinned one
        other = _image("9.9.9")
        os.remove(str(rig.stub / "saves" / (IMAGES[1]["id"].split(":")[1] + ".tar")))
        bad = dict(other, id=IMAGES[1]["id"])
        bad["manifest"] = other["manifest"]
        (rig.stub / "saves" / (IMAGES[1]["id"].split(":")[1] + ".tar")).write_bytes(_save(bad))
    res = rig.run(**cfg)
    assert res.rc == 1 and res.status == ["status=FAILED at=%s" % unit], res.why()
    assert msg in res.log, (msg, res.log[-3000:])
    assert res.doc["status"] == "FAILED" and res.doc["at"] == unit and res.unit(unit)["state"] == "failed"
    k = UNITS.index(unit)
    assert res.doc["not_run"] == UNITS[k + 1:], res.doc["not_run"]
    stop = res.doc["stop"]
    assert stop["swept"] is True and stop["verified"] is True and res.containers() == [], stop
    assert res.idx("systemctl", r"^is-active ota-lite$") > 0 and res.idx("sync") >= 0


def test_a_harness_that_stops_without_a_status_line_ends_failed_in_its_unit_through_its_exit_trap(tmp_path):
    """The EXIT trap: a command the harness does not guard fails under set -e (here its fact store, which the drill.py
    stand-in leaves unwritable for the drill's exit status, after the drill ran). The run still ends status=FAILED at the
    unit it was in, drill.json records that unit failed with why and only the units after it as not run, and the sweep
    removes what was up (the stack's containers: its down never ran)."""
    rig = Rig(tmp_path)
    res = rig.run(STUB_DRILL_BREAK_FACTS="1")
    why = "the harness stopped unexpectedly (exit 1)"
    assert res.rc == 1 and res.status == ["status=FAILED at=drill"], res.why()
    assert why in res.log and "FAILED at drill: " + why in res.log, res.log[-3000:]
    d = res.doc
    assert (d["status"], d["status_line"], d["at"], d["reason"]) == ("FAILED", "status=FAILED at=drill", "drill", why), d
    u = res.unit("drill")
    assert u["state"] == "failed" and u["why"] == why and isinstance(u["operational_s"]["drill"], int), u
    assert d["not_run"] == ["down"] and res.unit("manifest")["state"] == "ran", d["units"]
    stop = d["stop"]
    assert stop["swept"] is True and stop["containers_found"] == 3 and stop["verified"] is True, stop
    assert res.containers() == [] and d["record"]["result_found"] is True, d["record"]


def test_a_harness_whose_fact_store_cannot_be_written_still_ends_failed_through_its_exit_trap(tmp_path):
    """The EXIT trap's own facts are best effort: a drill.py stand-in leaves a regular file where the harness's
    facts of the drill unit go (<work>/facts/drill), so the write of the drill's exit status fails under set -e and not one
    fact of that unit can be written afterwards, the trap's own included. The trap must still end the run: status=FAILED
    at=drill, its reason in run.log and in drill.json, the sweep run and the stack's containers removed (its down never ran).
    The unit's own state is not asserted: here it cannot be written, so it stays not run whatever the trap does."""
    res = Rig(tmp_path).run(STUB_DRILL_FACTS_FILE="1")
    why = "the harness stopped unexpectedly (exit 1)"
    assert res.rc == 1 and res.status == ["status=FAILED at=drill"], res.why()
    assert why in res.log and "FAILED at drill: " + why in res.log, res.log[-3000:]
    d = res.doc
    assert d is not None, res.why()
    assert (d["status"], d["status_line"], d["at"], d["reason"]) == ("FAILED", "status=FAILED at=drill", "drill", why), d
    stop = d["stop"]
    assert stop["swept"] is True and stop["containers_found"] == 3 and stop["containers_removed"] is True, stop
    assert stop["verified"] is True and res.containers() == [], stop


def test_a_record_that_cannot_be_written_ends_failed_at_record_and_not_done(tmp_path):
    """drill.json is the last thing the harness writes, by its tool: a run whose every unit ran and whose sweep
    is done still cannot end DONE when the record cannot be written. A drill.py stand-in overwrites <work>/drill-tool.py with
    text that is not Python as its last act; the run ends status=FAILED at=record, says so in run.log, and leaves no
    drill.json, but the files it copied into the record and the sweep's work stand."""
    rig = Rig(tmp_path)
    res = rig.run(STUB_DRILL_BREAK_TOOL="1")
    assert res.rc == 1 and res.status == ["status=FAILED at=record"], res.why()
    assert "drill.json could not be written" in res.log and "FAILED at record" in res.log, res.log[-2000:]
    assert res.doc is None and not (rig.out / "drill.json").exists(), "no drill.json: it could not be written"
    assert (rig.out / "drill-result.json").exists() and (rig.out / "manifest.json").exists(), sorted(os.listdir(str(rig.out)))
    assert res.containers() == [] and res.idx("systemctl", r"^is-active ota-lite$") >= 0, res.calls


def test_a_drill_that_ran_and_whose_verdict_is_not_ok_is_a_result(tmp_path):
    """drill.py run's exit 1 (it ran; the verdict is not ok) is a result: the harness ends DONE and says so."""
    res = Rig(tmp_path).run(STUB_DRILL_RC="1")
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert res.unit("drill")["exit"] == 1 and res.unit("drill")["state"] == "ran"
    assert res.doc["record"]["verdict"] == "not ok" and res.unit("down")["state"] == "ran"


@pytest.mark.parametrize("k", range(len(UNITS)), ids=UNITS)
def test_a_check_point_past_stop_at_stops_cleanly_with_a_timeout(tmp_path, k):
    """Before each unit: now >= stop_at stops the harness there, a TIMEOUT line, the units not run listed, exit 0. The
    first unit's check point sees a deadline already within the margin; each later one, a clock that jumps once the
    unit before it has ended (run.log's end line)."""
    rig = Rig(tmp_path)
    if k == 0:
        rig.ahead(25 * 60)
        res = rig.run()
    else:
        res = rig.run(STUB_JUMP_RE=r"unit %s: end" % UNITS[k - 1], STUB_JUMP_S=200 * 60)
    unit = UNITS[k]
    assert res.rc == 0 and res.status == ["status=TIMEOUT at=%s reason=deadline" % unit], res.why()
    assert res.doc["not_run"] == UNITS[k:] and res.doc["status"] == "TIMEOUT", res.doc
    assert res.idx("sync") >= 0
    if k == 0:
        assert res.doc["stop"] == {"swept": False, "why": "no unit began: nothing to sweep"}
        assert res.idx("docker") == -1
    else:
        assert res.doc["stop"]["swept"] is True and res.doc["stop"]["verified"] is True and res.containers() == []


def test_a_drill_that_overruns_its_cap_ends_in_a_timeout_and_the_sweep_stops_what_it_left(tmp_path):
    """The cap's TERM ends drill.py before its own end: the updater's container and unit are left. The clean stop stops
    the unit, removes every labelled container, and keeps the updater's log and state from its state directory."""
    rig = Rig(tmp_path)
    res = rig.run(STUB_CAP_RE=r"drill\.py run ", STUB_DRILL_SLEEP="20")
    assert res.rc == 0 and res.status == ["status=TIMEOUT at=drill reason=step-timeout"], res.why()
    assert res.unit("drill")["state"] == "step-timeout" and res.doc["not_run"] == ["down"]
    stop = res.doc["stop"]
    assert stop["unit_state_before"] == "active" and stop["unit_inactive"] is True, stop
    assert stop["containers_found"] == 4 and stop["containers_removed"] is True and stop["verified"] is True, stop
    assert res.containers() == []
    assert res.idx("sudo", r"^-n systemctl stop ota-lite$") >= 0 and res.idx("systemctl", "^stop ota-lite$") >= 0
    assert sorted(os.listdir(str(rig.out))) == ["drill.json", "manifest.json", "ota-lite.jsonl", "state.json", "venv.txt"]
    assert res.doc["record"]["kept_from_state"] == ["ota-lite.jsonl", "state.json"]


# every capped call, by CAPPED's names, with the pattern that picks its timeout line, and how many of the stack's containers
# are up when it is cut (the stack's up ran before manifest, drill and down)
CAP_CUTS = [
    ("load", r"sudo -n docker load", 0),
    ("prove", r"drill-tool\.py prove", 0),
    ("venv", r"-m venv", 0),
    ("pip", r"-m pip install", 0),
    ("freeze", r"-m pip freeze", 0),
    ("prepare", r"stack\.py prepare", 0),
    ("up", r"stack\.py up", 0),
    ("manifest", r"drill\.py manifest", 3),
    ("drill", r"drill\.py run", 3),
    ("down", r"stack\.py down", 3),
]
CAP_UNIT = {"prove": "load", "pip": "venv", "freeze": "venv"}


def test_the_cap_cases_are_every_capped_call():
    assert [c[0] for c in CAP_CUTS] == [n for n, _pat in CAPPED]


@pytest.mark.parametrize("name,pattern,up", CAP_CUTS, ids=[c[0] for c in CAP_CUTS])
def test_a_cap_that_fires_in_any_capped_call_is_a_step_timeout_in_its_unit_and_the_sweep_runs(tmp_path, name, pattern, up):
    """Each capped call in turn is cut (the timeout stub reports the cap fired, the clock at the cap's end): the unit it
    belongs to ends `step-timeout`, not as a failure of that unit (a cut docker load, venv, pip, stack.py or drill.py) and
    not as DONE (a cut stack.py down), the units after it are not run, and the sweep removes what the cut left up."""
    unit = CAP_UNIT.get(name, name)
    res = Rig(tmp_path).run(STUB_CAP_RE=pattern, STUB_CAP_AT_ONCE="1")
    assert res.rc == 0 and res.status == ["status=TIMEOUT at=%s reason=step-timeout" % unit], res.why()
    assert (res.doc["status"], res.doc["at"], res.doc["reason"]) == ("TIMEOUT", unit, "step-timeout"), res.doc
    assert res.unit(unit)["state"] == "step-timeout", res.doc["units"]
    assert res.doc["not_run"] == UNITS[UNITS.index(unit) + 1:], res.doc["not_run"]
    stop = res.doc["stop"]
    assert stop["swept"] is True and stop["containers_found"] == up and stop["verified"] is True, stop
    assert res.containers() == [] and res.idx("systemctl", r"^is-active ota-lite$") >= 0 and res.idx("sync") >= 0


def test_a_stack_down_that_fails_is_recorded_and_the_sweep_removes_what_it_left(tmp_path):
    """stack.py down's exit status is recorded, not a failure of the run (the sweep is the one that removes the stack's
    containers, and says whether it could): the run ends DONE, the down unit `ran` with its exit, the containers gone."""
    res = Rig(tmp_path).run(STUB_DOWN_RC="1", STUB_DOWN_LEAVE="1")
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    assert res.unit("down")["state"] == "ran" and res.unit("down")["exit"] == 1, res.unit("down")
    assert "stack.py down exited 1: the sweep removes what it left" in res.log, res.log[-2000:]
    stop = res.doc["stop"]
    assert stop["containers_found"] == 3 and stop["containers_removed"] is True and stop["verified"] is True, stop
    assert res.containers() == []


def test_a_narrow_columns_setting_does_not_cut_the_shim_lines_the_sweep_reads(tmp_path):
    """`ps -eo args=` cuts each line to $COLUMNS when it is set, even into a pipe: a containerd-shim line then loses its
    -id, and the shim of a container docker still lists (here one that is no drill's, which the sweep leaves alone) counts
    as an orphan, so the stop is called unverified. The harness asks ps for unlimited width."""
    rig = Rig(tmp_path)
    (rig.stub / "containers" / ("99" * 32)).write_text("com.example.other")
    res = rig.run(COLUMNS="80")
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    stop = res.doc["stop"]
    assert stop["shims_left"] == 0 and stop["verified"] is True, stop
    assert res.containers() == ["99" * 32], "a container of another owner is left alone"
    assert res.idx("ps", r"-ww") >= 0 and res.idx("ps", r"-eo args=") >= 0


def _root_only_bytes(path):
    """A file of mode 0 read as the stub sudo reads it: its mode lent back for the read."""
    m = os.stat(str(path)).st_mode
    os.chmod(str(path), 0o600)
    try:
        return path.read_bytes()
    finally:
        os.chmod(str(path), m)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads a file of mode 0: no refusal to show")
@pytest.mark.parametrize("case", ["state-after-a-cap", "record", "unreadable"])
def test_the_record_copies_what_only_root_may_read_through_sudo(tmp_path, case):
    """The updater runs as root in a system unit and writes its log and state 0600 (ota_lite.py): the login cannot read
    them, so a copy the login cannot make goes through `sudo -n cat`, into a file the login owns. A file that cannot be
    read either way is named under record.not_kept and leaves no file in the record."""
    rig = Rig(tmp_path)
    work = rig.vss_home / "drill-work"
    if case == "record":
        res, src, names = rig.run(STUB_RECORD_ROOT_ONLY="1"), work / "record", RECORD_FILES
        assert res.status == ["status=DONE"] and res.doc["record"].get("verdict") == "ok", res.why()
    else:
        cfg = dict(STUB_CAP_RE=r"drill\.py run ", STUB_DRILL_SLEEP="20", STUB_STATE_ROOT_ONLY="1")
        if case == "unreadable":
            cfg["STUB_ROOT_CAT_FAIL"] = "1"
        res, src, names = rig.run(**cfg), work / "ota-state", ["ota-lite.jsonl", "state.json"]
        assert res.status == ["status=TIMEOUT at=drill reason=step-timeout"], res.why()
    if case == "unreadable":
        assert res.doc["record"]["not_kept"] == ["ota-state/ota-lite.jsonl", "ota-state/state.json"], res.doc["record"]
        assert sorted(os.listdir(str(rig.out))) == ["drill.json", "manifest.json", "venv.txt"]
        assert "not kept in the record" in res.log, res.log[-3000:]
        return
    for n in names:
        assert (rig.out / n).read_bytes() == _root_only_bytes(src / n), n
        assert res.idx("sudo", r"^-n cat %s$" % re.escape(str(src / n))) >= 0, (n, res.calls)
    assert "not_kept" not in res.doc["record"], res.doc["record"]
    if case == "state-after-a-cap":
        assert res.doc["record"]["kept_from_state"] == names


# --- the sweep -----------------------------------------------------------------------------------------------------

def test_a_sweep_that_cannot_list_the_containers_removes_them_by_name_and_is_unverified(tmp_path):
    res = Rig(tmp_path).run(STUB_DOCKER_PS_FAIL="1")
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    stop = res.doc["stop"]
    assert stop["containers_list_exit"] == 1 and stop["containers_removed"] is False and stop["verified"] is False, stop
    names = ["sdv-ota-app"] + _stack_containers()
    rm = [c[2] for c in res.calls if c[0] == "docker" and c[2].startswith("rm -f ")]
    assert rm == ["rm -f " + " ".join(names)], rm
    assert "the containers labelled sdv.ota.app or sdv.stack.run could not be listed (docker ps exit 1)" in stop["unverified"]
    assert any("the stop is unverified:" in ln for ln in res.log.splitlines()[-30:]), res.log[-3000:]


def test_a_sweep_that_finds_an_orphan_containerd_shim_is_unverified(tmp_path):
    res = Rig(tmp_path).run(STUB_ORPHAN_SHIM="ee" * 32)
    assert res.rc == 0 and res.status == ["status=DONE"], res.why()
    stop = res.doc["stop"]
    assert stop["shims_left"] == 1 and stop["verified"] is False, stop
    assert stop["unverified"] == ["1 containerd-shim(s) of a container docker no longer lists still run"], stop


def test_a_sweep_whose_unit_stays_active_is_unverified(tmp_path):
    res = Rig(tmp_path).run(STUB_DRILL_LEAVE="1", STUB_UNIT_STUCK="1")
    stop = res.doc["stop"]
    assert res.status == ["status=DONE"] and stop["unit_inactive"] is False and stop["verified"] is False, stop
    assert stop["unit_stop_exit"] == 0 and stop["unit_state_after"] == "active", stop
    assert "the unit ota-lite is active after a stop" in stop["unverified"], stop


def test_a_sweep_whose_removal_fails_is_unverified(tmp_path):
    res = Rig(tmp_path).run(STUB_DRILL_LEAVE="1", STUB_RM_FAIL="1")
    stop = res.doc["stop"]
    assert res.status == ["status=DONE"] and stop["containers_found"] == 1 and stop["containers_rm_exit"] == 1, stop
    assert stop["containers_removed"] is False and stop["verified"] is False, stop
    assert "docker rm -f of the containers labelled sdv.ota.app or sdv.stack.run exited 1" in stop["unverified"], stop


def test_a_sweep_removes_what_a_drill_left_and_stops_its_unit(tmp_path):
    res = Rig(tmp_path).run(STUB_DRILL_LEAVE="1")
    stop = res.doc["stop"]
    assert res.status == ["status=DONE"] and stop["unit_state_before"] == "active" and stop["unit_inactive"] is True, stop
    assert stop["containers_found"] == 1 and stop["containers_removed"] is True and stop["verified"] is True, stop
    rm = [c for c in res.calls if c[0] == "docker" and c[2].startswith("rm -f ")]
    assert rm == [("docker", "1", "rm -f " + APP_ID)], rm


def _stack_containers():
    """stack.py's CONTAINERS (every container a run may start), read from the real module."""
    code = ("import json, sys; sys.path.insert(0, %r); import stack; print(json.dumps(sorted(stack.CONTAINERS.values())))"
            % os.path.join(REPO, "sdv", "stack"))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_the_sweeps_names_are_the_updaters_container_and_exactly_the_stacks():
    with open(HARNESS, encoding="utf-8") as f:
        m = re.search(r"^FALLBACK_NAMES=\(([^)]*)\)$", f.read(), re.M)
    code = ("import sys; sys.path.insert(0, %r); import ota_lite; print(ota_lite.APP_CONTAINER)"
            % os.path.join(REPO, "sdv", "ota"))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert m is not None and m.group(1).split() == [p.stdout.strip()] + _stack_containers()


# --- the harness itself ----------------------------------------------------------------------------------------------

def _code(text):
    """The harness without its comment lines."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_the_harness_is_host_neutral_and_reads_no_image_plan_k_or_img_word():
    """No a1.metal name, core count or core list in the harness; the role by VSS_HOST,
    the instance by nothing; no IMAGE, PLAN, K or IMG_ word read, and no image booted."""
    with open(HARNESS, encoding="utf-8") as f:
        text = f.read()
    assert "a1.metal" not in text and "c7g.metal" not in text
    code = _code(text)
    for w in ("--cpuset", "taskset", "nproc", "AllowedCPUs", "SDV_CONTAINER_CPUSET", "launch-qnx-kvm-bridged"):
        assert w not in code, w
    assert not re.search(r"\$\{?(PLAN|IMAGE|K|IMG_[A-Z]+|IFS_BIN|DISK)\b", code), "an image, plan or round word read"
    assert re.search(r'^HOST_MODE="\$\{VSS_HOST-a1-metal\}"$', text, re.M)


AWS_README = os.path.join(REPO, "scripts", "aws", "README.md")


def _flat(text):
    return re.sub(r"\s+", " ", text)


def _header(src):
    """The harness's header comment, its lines joined: the leading lines that begin with #."""
    lines = []
    for ln in src.splitlines():
        if not ln.startswith("#"):
            break
        lines.append(ln.lstrip("#"))
    return _flat(" ".join(lines))


def test_the_header_and_the_readme_list_every_failed_status_line_and_pips_cache():
    """As tests/test_vss_harness.py holds the two vss harnesses: every FAILED status line the harness can write is in its
    header's THE STATUS LINE and in the README's drill section -- the literal ones (at=preflight, at=record), a unit's
    own (drill.py run's exit 0 or 1 without its drill-result.json among them) and its EXIT trap's -- and the code holds no
    other form; and both name pip's cache, outside the record."""
    with open(AWS_README, encoding="utf-8") as f:
        text = f.read()
    readme = _flat(text[text.index("### An OTA drill session"):text.index("## What bounds the cost")])
    with open(HARNESS, encoding="utf-8") as f:
        src = f.read()
    head = _header(src)
    block = head[head.index("THE STATUS LINE"):head.index("THE RECORD")]
    assert set(re.findall(r"\bfinish FAILED (\S+)", src)) == {"preflight", '"$1"', '"${CUR:-preflight}"'}
    literal = ["status=FAILED at=preflight"] + re.findall(r'line="(status=FAILED at=[a-z0-9-]+)"', src)
    assert literal == ["status=FAILED at=preflight", "status=FAILED at=record"], literal
    for line in literal + ["status=FAILED at=<unit>"]:
        assert line in block and line in readme, line
    assert "stopped unexpectedly" in block and "EXIT trap" in block and "the harness stopped unexpectedly" in readme
    assert "left no drill-result.json" in block and "left no drill-result.json" in readme
    assert "~/.cache/pip" in head and "~/.cache/pip" in readme


def test_the_harness_tool_parses_as_python_3_10():
    with open(HARNESS, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"<<'PY'\n(.*?)\nPY\n", text, re.S)
    assert m is not None
    ast.parse(m.group(1), feature_version=(3, 10))
