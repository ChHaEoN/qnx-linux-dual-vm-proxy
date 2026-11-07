#!/usr/bin/env bash
# run-ota-drill.sh -- the OTA drill on a bare-metal AWS instance: the drill's images loaded from the session's tar and
# proved, the updater's venv, the slice's stack up without its app, WP3's drill.py (the manifest on tar transport, then its
# six steps by local spool records), the stack down, and the sweep. SDV plan Phase 6 (WP6),
# 2026-10-19. A functional session: no field of its record is a measurement.
#
# HOW IT RUNS. Only as remote-ladder.sh's harness phase starts it, detached, in a vss session (scripts/aws/README.md, "An
# OTA drill session"): LADDER_ENV="HARNESS=run-ota-drill.sh [VSS_HOST=a1-metal|c7g-metal]", once per session, after
# run-vss-setup.sh ended status=DONE, from a later login than setup's (the docker group setup added applies from it). It
# takes no IMAGE, PLAN, K or IMG_ word and boots no image: the drill runs without the guest and the bridge. The
# detached runner runs it from $R = $W/repo/orin-native/gpu-concurrency with stdout and stderr in rec/ota-drill/run.log and
# SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored (a unit under its cap starts with only SIGPIPE of them ignored:
# remote-ladder.sh, SIGNALS), then reads its last status line. Its environment:
#   W         the session's directory (~/a1): inputs.env, repo.tar and repo/ (the vss tarball), drill-in/, rec/vss-setup
#   OUT       rec/ota-drill/raw, the record; STATUS rec/ota-drill/status (lib-vss-deadline.sh's vss_status writes it)
#   DRILL_IN  $W/drill-in, the drill's three files (THE DRILL'S FILES). The session's METAL_FILES carried them to in/ beside
#             the upload bundle, and remote-ladder.sh's setup moved them here once their hashes were checked: in/ is the
#             bundle's directory, which run-vss-setup.sh's `bundle.py verify` takes whole, a file it does not list refused
#   VSS_HOME  $W/sdv, what setup left: py312/ (python-build-standalone), venv/ (the sim venv, python-can's player), gen/,
#             cache/dbc/, recordings/; drill-work/, this harness's own working files (never captured): its tool, its
#             facts, the stack's run directories (runs/), the drill's manifest, the updater's state and the drill's record
#             directory; and ota-venv/, the updater's venv, which this harness makes
#   VSS_HOST  the host's role: a1-metal (unset is a1-metal) or c7g-metal, the role of the instance METAL_TYPE launched
# IFS_BIN, IMG_S, IMG_B, DISK, VPROBE, CSTATE and VSS_IN (in/, the bundle) come with the phase's environment, not used here.
# For the tests, QNX_METAL_DEADLINE_FILE overrides the deadline file, and QNX_L4T_RELEASE_FILE and QNX_DT_COMPATIBLE_FILE
# L4T's release file (/etc/nv_tegra_release) and the device tree's compatible (/proc/device-tree/compatible), HOST-NEUTRAL's.
#
# HOST-NEUTRAL. The instance is METAL_TYPE's and the role is VSS_HOST's: nothing here names an instance type, a core
# count or a core list. Off the Orin the stack and the updater take no cpuset (the stack's cpuset variable unset, drill.py
# run given none), so both run on the instance's own cores. Any VSS_HOST but the two roles, an empty one included, is
# refused before the preflight (status=FAILED at=preflight), orin too: the board's drill is its own helper's (WP7); and so
# is either role on a host that L4T's release file or an NVIDIA device tree marks as a Jetson.
#
# THE DRILL'S FILES, in DRILL_IN, each named in inputs.env's FILES with its sha256 (drive-metal.sh's upload; remote-ladder.sh
# setup checked them once and moved them, the preflight checks them again):
#   drill-images.json     the drill's pins (sdv/drill, WP3's), byte for byte the repo tarball's sdv/drill/drill-images.json
#   sdv-drill.tar         `build_drill.py save` (WP3's): one docker save of the three pinned arm64 IDs, the
#                         metal session's transport, handed whole to drill.py manifest --tar. drill.py (WP3's) checks it
#                         against the pins and splits it into one tar per version beside its --out (drill-work/drill-tars),
#                         since the updater's tar transport loads a tar of one image; this harness splits nothing
#   sdv-drill.tar.sha256  two lines: the tar's sha256 as sha256sum prints it, `<64 hex>  sdv-drill.tar` (in binary mode,
#                         Git Bash's on the PC, `<64 hex> *sdv-drill.tar`: taken too), and `commit <40 hex>`, the commit
#                         the tar was built at, which must be the repo tarball's: the commit `git archive` wrote into its
#                         pax header, which git get-tar-commit-id reads, read here with Python's tarfile
#
# PREFLIGHT, in this order; a refusal is status=FAILED at=preflight, exit 1, and nothing has started. First, before
# drill-work or OUT is touched: a VSS_HOME/drill-work in which a unit began (a start by hand after a run: the phase starts
# this harness once per session) is refused, its status line its only write. Then, drill-work made anew:
#   the deadline file readable; `id -nG` includes docker; rec/vss-setup has done and its status file's last status= line
#   is exactly status=DONE; its raw/setup.json says DONE, its host_mode (none is a1-metal) is VSS_HOST's, and its skip list
#   holds neither broker nor can (the drill needs vcan0: --app external needs the vcan feed); no QEMU runs (one found is
#   refused, never stopped); the repo tarball's sdv/drill/drill.py, sdv/stack/stack.py, sdv/drill/drill-images.json, the
#   app's requirements.aarch64.lock and sdv/ota/ota_docker.py; the drill's three files, each in FILES and of its sha256
#   there; the sum file's tar line and commit line, the commit the repo tarball's; drill-in/drill-images.json the repo's,
#   and at least one pin in it (an object holding an `id` and a `config_digest`, both sha256 digests, wherever it stands in
#   WP3's layout; one pair counts once); sdv-drill.tar's index.json (docker save's OCI layout) listing exactly those pins'
#   IDs, each once: the first check drill.py manifest makes of the save before it splits it (WP3's check_save), made here
#   before anything starts, so a tar of other images never spends the session's one drill run; VSS_HOME's venv/bin/python,
#   py312/python/bin/python3, gen/manifest.json, a cache/dbc/<sha256>.dbc and the drill's recording's sigsim.log; and no
#   VSS_HOME/ota-venv yet.
#
# THE UNITS, in this order, each behind the deadline's check point (now >= stop_at stops here) and under its cap, in
# lib-vss-deadline.sh's call form (rc=0; vss_capped CMD... || rc=$?, then vss_cap_fired "$rc"):
#   load      `sudo -n docker load -i drill-in/sdv-drill.tar`; then each pin proved by setup's py312 running sdv/ota/
#             ota_docker.py's proof: its config digest read from a `sudo -n docker save <its ID>` stream, an index refused
#   venv      py312's `python -m venv VSS_HOME/ota-venv`, then `pip install --require-hashes --no-deps --only-binary=:all:
#             -r sdv/apps/hard-brake-hazard/requirements.aarch64.lock` (kuksa-client, the updater's AppState reader) and
#             `pip freeze`, each into venv.txt. pip keeps its download cache in the session user's ~/.cache/pip: outside
#             OUT and VSS_HOME, never captured
#   prepare   stack.py prepare --images loaded --name ota-drill-prepare
#   up        stack.py up --feed vcan --app external --images loaded --name ota-drill: every container but the app. Its run
#             directory, drill-work/runs/<YYYYMMDD>-ota-drill, is drill.py's --stack-run
#   manifest  drill.py manifest --host-role VSS_HOST --arch arm64 --transport tar --stack-run DIR --out drill-work/
#             manifest.json --pins drill-in/drill-images.json --tar drill-in/sdv-drill.tar (it ends with ota_lite.py check's
#             status)
#   drill     drill.py run --manifest drill-work/manifest.json --state drill-work/ota-state --record drill-work/record
#             --stack-run DIR --sim-python VSS_HOME/venv/bin/python --ota-python VSS_HOME/ota-venv/bin/python --via spool
#             --spool-dir /run/sdv-local/spool/v1 --status-dir /run/sdv-local/status/v1 --sudo 'sudo -n'. Its exit 0 (the
#             verdict ok) and 1 (it ran, and the verdict is not ok) are results, once its record holds drill-result.json;
#             2 (a refusal) and any other a failure
#   down      stack.py down. A non-zero exit is recorded, and the sweep removes what it left
# stack.py runs from W/repo with the sim venv's python and SDV_HOST_ROLE=VSS_HOST, SDV_GEN, SDV_CACHE, SDV_SIM_VENV,
# SDV_RUNS=drill-work/runs and SDV_RECORDING=VSS_HOME/recordings/20260930-sigsim-1b (the drill's one scenario, the honest
# recording); up also with SDV_SPOOL_DIR and SDV_STATUS_DIR, the host's spool and status directories (the updater's unit
# makes them; the stack reads the pair only beside a connector, and this host runs none). drill.py runs with the
# updater's venv's python.
#
# THE STATUS LINE, the last one in STATUS, through vss_status:
#   status=DONE                                  every unit ran; drill.json written first (a temporary file, a rename)
#   status=TIMEOUT at=<unit> reason=deadline     a check point found now >= stop_at; <unit> and the rest did not run
#   status=TIMEOUT at=<unit> reason=step-timeout <unit>'s cap fired: it was cut, the rest did not run
#   status=FAILED at=preflight                   the preflight refused, or the mode, or no readable deadline file
#   status=FAILED at=<unit>                      a unit failed: the load or a pin's proof, the venv, the stack's prepare
#                                                or up, drill.py manifest, drill.py run's refusal or another exit status,
#                                                or its exit 0 or 1 when it left no drill-result.json in its record (a
#                                                run that ran writes it); or the harness ended without a status line,
#                                                through its EXIT trap
#                                                (reason "the harness stopped unexpectedly", at the unit it was in,
#                                                which drill.json records failed, with that reason as its why)
#   status=FAILED at=record                      every unit ran, but drill.json could not be written
# Every FAILED exits 1, a TIMEOUT 0. Every stop but DONE syncs first. Every stop once a unit has begun, DONE included,
# sweeps before its record: the unit ota-lite stopped when it is not inactive (sudo -n systemctl stop) and read back; every
# container labelled sdv.ota.app or sdv.stack.run removed (sudo -n docker rm -f) or, when they cannot be listed, the
# updater's and the stack's container names (FALLBACK_NAMES, which need no listing); then no containerd-shim left whose
# container docker no longer lists (from ps, waited for up to SHIM_WAIT_S). A unit still active, containers that cannot be
# listed, a removal that fails or a shim left records the stop unverified (stop.verified false, with why under
# stop.unverified) and says so in run.log; the status line is not changed. Then what the drill and the stack left is copied
# into OUT (THE RECORD), the units not run go to run.log and drill.json, and drill.json is written in every case.
#
# THE RECORD, in OUT (each name on capture.py's whitelist under ota-drill/raw): drill.json (this harness's facts: the
# preflight's, each unit's state, exit statuses and whole seconds under operational_s, what was kept, the sweep's, the
# status), venv.txt, the up run's manifest.json, and from the drill's record directory drill-result.json, the updater's
# ota-lite.jsonl and state.json (from the updater's state directory when the record has none: a drill its cap cut short)
# and the status files the run kept (status*.json). Each is copied into a file the login owns: by cp, and when the login
# cannot read it by `sudo -n cat` (the updater runs as root in a system unit and writes its log and state 0600); a file
# neither can read is left out, named under record.not_kept and in run.log. Every string in drill.json is one line. Every
# docker call, systemctl stop and such read this harness runs itself runs under sudo -n; stack.py and drill.py reach
# Docker through the login's docker group.
#
# DESIGN VALUES (not measured): the wait for a removed container's shim (SHIM_WAIT_S, 10 s); the sweep's bounds (60 s a
# listing or a stop, 120 s a removal or a sync).
#
# WHAT IT DOES NOT SHOW: that the drill passes (drill-result.json's verdict is drill.py's); any timing (the operational_s
# values are whole seconds of this session's own units, with Docker up); secure OTA (no signing, no root of trust: an image
# is proved by its config digest, nothing more); anything about the guest, the bridge or the claim path (the drill runs
# without them); that a container stayed on any cores (none are given); physical CAN.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
# shellcheck source=lib-vss-deadline.sh
. "$HERE/lib-vss-deadline.sh"
: "${W:?run-ota-drill.sh runs from the harness phase (W)}" "${OUT:?no OUT}" "${DRILL_IN:?no DRILL_IN}" "${VSS_HOME:?no VSS_HOME}"
: "${STATUS:?no STATUS}"

REPO="$W/repo"
STACK="$REPO/sdv/stack/stack.py"
DRILL="$REPO/sdv/drill/drill.py"
REPO_PINS="$REPO/sdv/drill/drill-images.json"
OTA_DOCKER="$REPO/sdv/ota/ota_docker.py"
APP_LOCK="$REPO/sdv/apps/hard-brake-hazard/requirements.aarch64.lock"
SETUP_REC="$W/rec/vss-setup"
WORK="$VSS_HOME/drill-work"
TOOL="$WORK/drill-tool.py"
RUNS="$WORK/runs"
SIM_PY="$VSS_HOME/venv/bin/python"
PBS_PY="$VSS_HOME/py312/python/bin/python3"
OTA_VENV="$VSS_HOME/ota-venv"
OTA_PY="$OTA_VENV/bin/python"
PINS="$DRILL_IN/drill-images.json"
TAR="$DRILL_IN/sdv-drill.tar"
TARSUM="$DRILL_IN/sdv-drill.tar.sha256"
DRILL_FILES=(drill-images.json sdv-drill.tar sdv-drill.tar.sha256)
RECORDING=20260930-sigsim-1b       # the drill's one scenario: the honest recording run-vss-setup.sh staged
STACK_NAME=ota-drill
PREPARE_NAME=ota-drill-prepare
SPOOL_DIR=/run/sdv-local/spool/v1  # the updater's defaults (sdv/ota/ota_lite.py SPOOL_DIR, STATUS_DIR)
STATUS_DIR=/run/sdv-local/status/v1
UNIT=ota-lite
LABELS=(sdv.ota.app sdv.stack.run)
# the updater's container (ota_lite.py's APP_CONTAINER) and stack.py's CONTAINERS, every container a run may start (a test
# holds them equal): the sweep's names when the labels cannot be listed
FALLBACK_NAMES=(sdv-ota-app sdv-stack-app sdv-stack-bridge sdv-stack-can-provider sdv-stack-connector sdv-stack-databroker
	sdv-stack-mock-provider sdv-stack-recorder sdv-stack-witness)
UNITS=(load venv prepare up manifest drill down)
SHIM_WAIT_S=10
# HOST-NEUTRAL: VSS_HOST unset is a1-metal; a1-metal and c7g-metal are taken; any other value is refused
HOST_MODE="${VSS_HOST-a1-metal}"
L4T_RELEASE="${QNX_L4T_RELEASE_FILE:-/etc/nv_tegra_release}"
DT_COMPATIBLE="${QNX_DT_COMPATIBLE_FILE:-/proc/device-tree/compatible}"
STACK_ENV=()
STACK_RUN=""
RC=0
T0=0

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

fact() {   # UNIT KEY TYPE VALUE: one fact for drill.json (vss_setup.py, FACTS); a KEY with "/" is a nested object
	local f="$WORK/facts/$1/$2.$3"
	mkdir -p "$(dirname "$f")"
	printf '%s' "$4" > "$f"
}

tool() { DRILL_HERE="$HERE" python3 -B "$TOOL" "$@"; }

write_tool() {   # the harness's readings and its record writer (Python 3.10, standard library and vss_setup.py)
	cat > "$TOOL" <<'PY'
"""drill-tool.py -- run-ota-drill.sh's readings of its inputs and its record, drill.json; written by the harness into its
work directory at each start, never captured. Standard library only, Python 3.10: the system python3 runs it, and setup's
python-build-standalone runs `prove`. The facts and the record's writer are vss_setup.py's, beside the harness
(DRILL_HERE). One subcommand per call; a refusal prints its reason on one line and exits 1.

  setup SETUP_JSON MODE FACTS          setup.json DONE, its host_mode (none: a1-metal) MODE, a skip list without broker, can
  files INPUTS_ENV DIR FACTS NAME...   each NAME in inputs.env's FILES, DIR/NAME of that sha256; prints `NAME SHA256` lines
  tarsum SUMFILE SHA256                the sum file's one tar line names SHA256; prints its one commit line's commit
  tarindex TAR PINS_TXT                TAR's index.json lists exactly PINS_TXT's IDs (drill.py manifest's first check of
                                       the save); prints how many images it lists
  repocommit TAR                       prints the commit git archive wrote into TAR's pax header
  pins PINS_JSON                       prints `ID CONFIG_DIGEST` for each distinct pin, in the file's order
  prove OTA_DIR PINS_TXT               each pin proved by OTA_DIR/ota_docker.py through `sudo -n docker save`
  verdict RESULT_JSON                  prints drill-result.json's verdict
  record WORK OUT STATUS LINE AT REASON MODE UNITS   drill.json from WORK/facts, written whole
"""
import hashlib
import json
import os
import re
import sys
import tarfile

sys.dont_write_bytecode = True
SHA = re.compile(r"sha256:[0-9a-f]{64}")
TAR_LINE = re.compile(r"[0-9a-f]{64} [ *]sdv-drill[.]tar")   # sha256sum's text mode, and its binary mode (Git Bash's)
COMMIT_LINE = re.compile(r"commit [0-9a-f]{40}")
COMMIT = re.compile(r"[0-9a-f]{40}")
VCAN_MODES = ("broker", "can")
ABOUT = ("run-ota-drill.sh's record (SDV plan Phase 6 WP6): the OTA drill on this bare-metal host, the drill's "
         "images loaded from the session's tar and proved, the updater's venv, the slice's stack up without its app, "
         "WP3's drill.py on tar transport with local spool records, the stack down, and the sweep.")
NOTE = ("A functional session: no field is a measurement and nothing is pre-registered. Docker is up on this host. Values "
        "under operational_s are whole seconds of this session's own units, not timings of the updater or of a switch.")


def one(x):
    return " ".join(str(x).replace("\t", " ").splitlines())


def refuse(msg):
    print(one(msg))
    return 1


def vs():
    sys.path.insert(0, os.environ["DRILL_HERE"])
    import vss_setup
    return vss_setup


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_setup(path, mode, facts):
    v = vs()
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        return refuse("%s cannot be read: %s" % (path, one(exc)))
    if not isinstance(doc, dict) or doc.get("status") != "DONE":
        return refuse("%s says status %r, not DONE" % (path, doc.get("status") if isinstance(doc, dict) else None))
    got = doc.get("host_mode", "a1-metal")
    v.put(facts, "setup_host_mode", str(got))
    if got != mode:
        return refuse("%s records host mode %s (a setup.json with none is an a1-metal setup's), not this drill's %s: a "
                      "setup of another host mode is refused" % (path, one(got), mode))
    modes, skip = doc.get("skip_modes"), doc.get("skip")
    if not isinstance(modes, list) or not isinstance(skip, list):
        return refuse("%s holds no skip list (skip_modes and skip)" % path)
    modes = sorted({str(m) for m in modes})
    v.put(facts, "skip_modes", modes)
    held = [m for m in modes if m in VCAN_MODES]
    if held:
        return refuse("setup's skip list holds %s: the drill needs vcan0 (--app external needs the vcan feed)" % ", ".join(held))
    return 0


def cmd_files(inputs, drill_in, facts, names):
    where = os.path.basename(os.path.normpath(drill_in))
    words = None
    try:
        with open(inputs, encoding="utf-8") as f:
            for ln in f.read().splitlines():
                if ln.startswith("FILES="):
                    words = ln[len("FILES="):].split()
    except OSError as exc:
        return refuse("inputs.env cannot be read: %s" % one(exc))
    if words is None:
        return refuse("inputs.env names no FILES: the session's METAL_FILES carried none of the drill's files")
    want = {}
    for w in words:
        name, _sep, sha = w.partition(":")
        want[name] = sha
    got = []
    for n in names:
        if n not in want:
            return refuse("%s is not among inputs.env's FILES: the session's METAL_FILES did not carry it" % n)
        p = os.path.join(drill_in, n)
        if not os.path.isfile(p):
            return refuse("no %s/%s: the upload and setup's move did not leave it" % (where, n))
        h = sha256_file(p)
        if h != want[n]:
            return refuse("%s's sha256 is not inputs.env's: %s/%s is %s, inputs.env says %s" % (n, where, n, h, want[n]))
        got.append("%s %s" % (n, h))
    vs().put(facts, "drill_files", got)
    print("\n".join(got))
    return 0


def cmd_tarsum(path, tar_hex):
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except (OSError, ValueError) as exc:
        return refuse("%s cannot be read: %s" % (name, one(exc)))
    sums = [ln for ln in lines if TAR_LINE.fullmatch(ln)]
    commits = [ln for ln in lines if COMMIT_LINE.fullmatch(ln)]
    other = [ln for ln in lines if not TAR_LINE.fullmatch(ln) and not COMMIT_LINE.fullmatch(ln)]
    if other:
        return refuse("%s holds a line that is neither its tar's sha256 nor its commit: %s" % (name, other[0][:80]))
    if len(sums) != 1:
        return refuse("%s holds %d sha256 lines (`<64 hex>  sdv-drill.tar`), not one" % (name, len(sums)))
    if len(commits) != 1:
        return refuse("%s holds %d commit lines (`commit <40 hex>`), not one" % (name, len(commits)))
    if sums[0][:64] != tar_hex:
        return refuse("%s names sha256 %s, and sdv-drill.tar's is %s" % (name, sums[0][:64], tar_hex or "unknown"))
    print(commits[0][len("commit "):])
    return 0


def cmd_tarindex(path, pins_txt):
    name = os.path.basename(path)
    with open(pins_txt, encoding="utf-8") as f:
        pins = sorted(ln.split()[0] for ln in f.read().splitlines() if ln.strip())
    raw = None
    try:
        with tarfile.open(path, "r:") as t:
            for m in t:
                if m.isreg() and (m.name[2:] if m.name.startswith("./") else m.name) == "index.json":
                    f = t.extractfile(m)
                    raw = f.read() if f is not None else None
                    break
    except (OSError, tarfile.TarError, EOFError) as exc:
        return refuse("%s cannot be read as a tar: %s" % (name, one(exc)))
    try:
        listed = json.loads(raw)["manifests"] if raw is not None else None
    except (ValueError, TypeError, KeyError, IndexError):
        listed = None
    if not isinstance(listed, list) or not all(isinstance(d, dict) for d in listed):
        return refuse("%s holds no index.json listing its images: it is not docker save's OCI layout" % name)
    got = sorted(str(d.get("digest")) for d in listed)
    if got != pins:
        return refuse("%s's index.json lists other images than drill-images.json's pins (%d listed, %d pinned): its tar is "
                      "build_drill.py save's docker save of the pinned IDs, at the pins' commit"
                      % (name, len(got), len(pins)))
    print(len(got))
    return 0


def cmd_repocommit(path):
    try:
        with tarfile.open(path, "r:") as t:
            c = t.pax_headers.get("comment")
    except (OSError, tarfile.TarError) as exc:
        return refuse("the repo tarball cannot be read as a tar: %s" % one(exc))
    if not isinstance(c, str) or not COMMIT.fullmatch(c):
        return refuse("the repo tarball carries no commit (the pax header git get-tar-commit-id reads): make it with "
                      "git archive <commit>")
    print(c)
    return 0


def cmd_pins(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        return refuse("drill-images.json cannot be read: %s" % one(exc))
    pairs = []

    def walk(o):
        if isinstance(o, dict):
            i, c = o.get("id"), o.get("config_digest")
            if isinstance(i, str) and isinstance(c, str) and SHA.fullmatch(i) and SHA.fullmatch(c) and (i, c) not in pairs:
                pairs.append((i, c))
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(doc)
    if not pairs:
        return refuse("drill-images.json names no pin (an object with an id and a config_digest, both sha256 digests)")
    for i, c in pairs:
        print("%s %s" % (i, c))
    return 0


def cmd_prove(ota_dir, pins_txt):
    sys.path.insert(0, ota_dir)
    import ota_docker
    docker = ota_docker.Docker(["sudo", "-n", "docker"])
    with open(pins_txt, encoding="utf-8") as f:
        pins = [ln.split() for ln in f.read().splitlines() if ln.strip()]
    for i, c in pins:
        try:
            docker.prove(i, i, c)
        except (ota_docker.ProofError, ota_docker.DockerError) as exc:
            print("not proved: %s (its pin's config digest %s): %s" % (i, c, one(exc)))
            return 1
        print("proved %s: config digest %s" % (i, c))
    return 0


def cmd_verdict(path):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f).get("verdict")
    except (OSError, ValueError, AttributeError) as exc:
        return refuse("drill-result.json cannot be read: %s" % one(exc))
    if not isinstance(v, str):
        return refuse("drill-result.json holds no verdict")
    print(one(v))
    return 0


def cmd_record(work, out, status, line, at, reason, mode, unit_names):
    v = vs()
    facts = v.read_facts(os.path.join(work, "facts"))
    units = []
    for u in unit_names.split():
        f = dict(facts.get(u) or {})
        state = f.pop("state", None)
        units.append(dict({"name": u, "state": state or "not-run"}, **f))
    doc = {"format": 1, "harness": "run-ota-drill.sh", "host_mode": mode, "about": ABOUT, "note": NOTE, "status": status,
           "status_line": line, "at": at or None, "reason": reason or None, "preflight": facts.get("preflight") or {},
           "units": units, "not_run": [u["name"] for u in units if u["state"] == "not-run"],
           "record": facts.get("record") or {}, "stop": facts.get("stop") or {}}
    v.write_json(out, doc)
    return 0


def main(argv):
    cmd, a = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "setup" and len(a) == 3:
        return cmd_setup(*a)
    if cmd == "files" and len(a) >= 4:
        return cmd_files(a[0], a[1], a[2], a[3:])
    if cmd == "tarsum" and len(a) == 2:
        return cmd_tarsum(*a)
    if cmd == "tarindex" and len(a) == 2:
        return cmd_tarindex(*a)
    if cmd == "repocommit" and len(a) == 1:
        return cmd_repocommit(*a)
    if cmd == "pins" and len(a) == 1:
        return cmd_pins(*a)
    if cmd == "prove" and len(a) == 2:
        return cmd_prove(*a)
    if cmd == "verdict" and len(a) == 1:
        return cmd_verdict(*a)
    if cmd == "record" and len(a) == 8:
        return cmd_record(*a)
    print("drill-tool.py: no such call: %s" % one(" ".join(argv)))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
PY
}

# --- the mode (HOST-NEUTRAL) -----------------------------------------------------------------------------------------
on_jetson() {   # whether L4T's release file or an NVIDIA device tree marks this host as a Jetson: builtins only, no command
	local c=""
	[ ! -e "$L4T_RELEASE" ] || return 0
	[ -r "$DT_COMPATIBLE" ] || return 1
	IFS= read -r -d '' c < "$DT_COMPATIBLE" || true
	case "$c" in nvidia,*) return 0 ;; esac
	return 1
}
host_refusal() {   # why this mode or host is refused before the preflight, or nothing
	case "$HOST_MODE" in
		a1-metal|c7g-metal)
			if on_jetson; then
				echo "VSS_HOST=$HOST_MODE on a host that L4T's release file or an NVIDIA device tree marks as a Jetson: the" \
					"bare-metal drill is not the board's (its own helper's)"
			fi ;;
		*) echo "VSS_HOST='${HOST_MODE//[^A-Za-z0-9._-]/?}' is none of a1-metal and c7g-metal (unset is a1-metal; the board's" \
			"drill is its own helper's)" ;;
	esac
}

# --- the preflight ---------------------------------------------------------------------------------------------------
refuse() { finish FAILED preflight "$1"; }

preflight() {
	local s=preflight groups last out commit repo f dbc tarhex
	groups="$(id -nG 2>/dev/null)" || groups=""
	case " $groups " in
		*" docker "*) fact $s docker_group b true ;;
		*) fact $s docker_group b false
		   refuse "this login is not in the docker group: run-vss-setup.sh adds it, and it applies from the next login" ;;
	esac
	last="$(grep '^status=' "$SETUP_REC/status" 2>/dev/null | tail -n 1 || true)"
	fact $s setup_status_line s "${last:-none}"
	fact $s setup_done b "$([ -e "$SETUP_REC/done" ] && echo true || echo false)"
	[ -e "$SETUP_REC/done" ] || refuse "$SETUP_REC has no done: run-vss-setup.sh has not finished (wait for it with wait-run)"
	[ "$last" = status=DONE ] || refuse "run-vss-setup.sh's last status line is '${last:-none}', not status=DONE"
	out="$(tool setup "$SETUP_REC/raw/setup.json" "$HOST_MODE" "$WORK/facts/$s" 2>&1)" || refuse "setup's record: $out"
	if pgrep -x qemu-system-aar >/dev/null 2>&1; then
		fact $s qemu_running b true
		refuse "a QEMU runs: the drill runs without the guest (D6), and this harness stops none"
	fi
	fact $s qemu_running b false
	for f in "$DRILL" "$STACK" "$REPO_PINS" "$APP_LOCK" "$OTA_DOCKER"; do
		[ -r "$f" ] || refuse "no ${f#"$W"/}: the repo tarball is not the drill's (its vss form from a commit with sdv/drill)"
	done
	out="$(tool files "$W/inputs.env" "$DRILL_IN" "$WORK/facts/$s" "${DRILL_FILES[@]}" 2>&1)" || refuse "the drill's files: $out"
	tarhex="$(printf '%s\n' "$out" | awk '$1 == "sdv-drill.tar" { print $2 }')"
	commit="$(tool tarsum "$TARSUM" "$tarhex" 2>&1)" || refuse "the drill's files: $commit"
	fact $s drill_tar_commit s "$commit"
	repo="$(tool repocommit "$W/repo.tar" 2>&1)" || refuse "$repo"
	fact $s repo_commit s "$repo"
	[ "$commit" = "$repo" ] || refuse "sdv-drill.tar was built at commit $commit and the repo tarball is $repo (the sum file's" \
		"commit line, the tarball's git archive header): build both from one commit"
	cmp -s "$PINS" "$REPO_PINS" \
		|| refuse "drill-in/drill-images.json differs from the repo tarball's sdv/drill/drill-images.json: the pins are another commit's"
	tool pins "$PINS" > "$WORK/pins.txt" 2>&1 || refuse "$(cat "$WORK/pins.txt")"
	fact $s pins i "$(grep -c . "$WORK/pins.txt" || true)"
	out="$(tool tarindex "$TAR" "$WORK/pins.txt" 2>&1)" || refuse "the drill's files: $out"
	fact $s drill_tar_images i "$out"
	[ -x "$SIM_PY" ] || refuse "no VSS_HOME/venv/bin/python: setup did not build the sim venv"
	[ -x "$PBS_PY" ] || refuse "no VSS_HOME/py312/python/bin/python3: setup did not unpack python-build-standalone"
	[ -r "$VSS_HOME/gen/manifest.json" ] || refuse "no VSS_HOME/gen/manifest.json: setup did not stage gen"
	dbc="$(find "$VSS_HOME/cache/dbc" -maxdepth 1 -name '*.dbc' 2>/dev/null | head -n 1 || true)"
	[ -n "$dbc" ] || refuse "no VSS_HOME/cache/dbc/<sha256>.dbc: setup did not stage the DBC"
	[ -r "$VSS_HOME/recordings/$RECORDING/sigsim.log" ] \
		|| refuse "no VSS_HOME/recordings/$RECORDING/sigsim.log: setup did not stage the drill's recording"
	fact $s recording s "$RECORDING"
	[ ! -e "$OTA_VENV" ] || refuse "VSS_HOME/ota-venv exists already: the updater's venv is made once, by this harness"
	STACK_ENV=(SDV_HOST_ROLE="$HOST_MODE" SDV_GEN="$VSS_HOME/gen" SDV_CACHE="$VSS_HOME/cache" SDV_SIM_VENV="$VSS_HOME/venv"
		SDV_RUNS="$RUNS" SDV_RECORDING="$VSS_HOME/recordings/$RECORDING")
	say "preflight: VSS_HOST=$HOST_MODE, setup DONE, $(grep -c . "$WORK/pins.txt" || true) pin(s), the drill's tar at the" \
		"repo tarball's commit"
}

# --- the units -------------------------------------------------------------------------------------------------------
check_point() {   # UNIT: the deadline's check point; then UNIT is the one this harness is in
	CUR="$1"
	if vss_past_stop; then finish TIMEOUT "$1" deadline; fi
	: > "$WORK/state/started"
	T0="$(vss_now)"
	say "unit $1: start"
}
secs() { fact "$1" "operational_s/$1" i "$(( $(vss_now) - T0 ))"; }
cap_check() {   # UNIT: a cap that fired in UNIT (its status in RC) stops the harness there
	if vss_cap_fired "$RC"; then
		fact "$1" state s step-timeout
		secs "$1"
		finish TIMEOUT "$1" step-timeout
	fi
}
unit_failed() {   # UNIT WHY
	fact "$1" state s failed
	fact "$1" why s "$2"
	secs "$1"
	finish FAILED "$1" "$2"
}
unit_ran() {   # UNIT WHAT
	fact "$1" state s ran
	secs "$1"
	say "unit $1: end ($2)"
}

unit_load() {
	local u=load n
	check_point $u
	RC=0; vss_capped sudo -n docker load -i "$TAR" < /dev/null || RC=$?
	cap_check $u
	fact $u load_exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "sudo -n docker load of sdv-drill.tar exited $RC"
	RC=0; vss_capped "$PBS_PY" -B "$TOOL" prove "$REPO/sdv/ota" "$WORK/pins.txt" > "$WORK/prove.out" 2>&1 < /dev/null || RC=$?
	cat "$WORK/prove.out"
	cap_check $u
	n="$(grep -c '^proved sha256:' "$WORK/prove.out" || true)"
	fact $u proof_exit i "$RC"
	fact $u proved i "$n"
	[ "$RC" = 0 ] || unit_failed $u "a pinned image's config digest was not proved (the proof exited $RC; its line is above)"
	unit_ran $u "sdv-drill.tar loaded and $n pin(s) proved by their config digests"
}

unit_venv() {
	local u=venv f="$OUT/venv.txt" ver
	check_point $u
	RC=0; vss_capped "$PBS_PY" -m venv "$OTA_VENV" < /dev/null || RC=$?
	cap_check $u
	fact $u venv_exit i "$RC"
	[ "$RC" = 0 ] && [ -x "$OTA_PY" ] || unit_failed $u "python -m venv from setup's py312 exited $RC"
	ver="$("$OTA_PY" --version 2>&1)" || unit_failed $u "the updater's venv's python does not run"
	{ echo "== ota-venv/bin/python --version"; printf '%s\n' "$ver"; } > "$f"
	fact $u python_version s "$ver"
	echo "== pip install --require-hashes --no-deps --only-binary=:all: -r ${APP_LOCK#"$REPO"/}" >> "$f"
	RC=0; vss_capped "$OTA_PY" -m pip install --require-hashes --no-deps --only-binary=:all: --no-input \
		--disable-pip-version-check --progress-bar off -r "$APP_LOCK" >> "$f" 2>&1 < /dev/null || RC=$?
	echo "== exit $RC" >> "$f"
	cap_check $u
	fact $u pip_install_exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "pip install exited $RC (venv.txt)"
	echo "== pip freeze" >> "$f"
	RC=0; vss_capped "$OTA_PY" -m pip freeze --disable-pip-version-check >> "$f" 2>&1 < /dev/null || RC=$?
	echo "== exit $RC" >> "$f"
	cap_check $u
	fact $u pip_freeze_exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "pip freeze exited $RC (venv.txt)"
	unit_ran $u "$ver, the app's aarch64 lock installed"
}

unit_prepare() {
	local u=prepare
	check_point $u
	RC=0; vss_capped env "${STACK_ENV[@]}" "$SIM_PY" "$STACK" prepare --images loaded --name "$PREPARE_NAME" < /dev/null || RC=$?
	cap_check $u
	fact $u exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "stack.py prepare exited $RC"
	unit_ran $u "stack.py prepare exited 0"
}

stack_run_dir() {   # the up run's directory, <YYYYMMDD>-ota-drill under drill-work/runs, when there is exactly one
	local d
	if [ -n "$STACK_RUN" ]; then printf '%s\n' "$STACK_RUN"; return 0; fi
	d="$(find "$RUNS" -mindepth 1 -maxdepth 1 -type d -name "[0-9]*-$STACK_NAME" 2>/dev/null || true)"
	if [ -n "$d" ] && [ "$(printf '%s\n' "$d" | grep -c .)" = 1 ]; then printf '%s\n' "$d"; fi
	return 0
}

unit_up() {
	local u=up
	check_point $u
	RC=0; vss_capped env "${STACK_ENV[@]}" SDV_SPOOL_DIR="$SPOOL_DIR" SDV_STATUS_DIR="$STATUS_DIR" "$SIM_PY" "$STACK" up \
		--feed vcan --app external --images loaded --name "$STACK_NAME" < /dev/null || RC=$?
	cap_check $u
	fact $u exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "stack.py up exited $RC"
	STACK_RUN="$(stack_run_dir)"
	[ -n "$STACK_RUN" ] || unit_failed $u "stack.py up left no one run directory <YYYYMMDD>-$STACK_NAME in drill-work/runs"
	fact $u stack_run s "$(basename "$STACK_RUN")"
	unit_ran $u "the stack is up without its app: $(basename "$STACK_RUN")"
}

unit_manifest() {
	local u=manifest
	check_point $u
	RC=0; vss_capped "$OTA_PY" "$DRILL" manifest --host-role "$HOST_MODE" --arch arm64 --transport tar --stack-run "$STACK_RUN" \
		--out "$WORK/manifest.json" --pins "$PINS" --tar "$TAR" < /dev/null || RC=$?
	cap_check $u
	fact $u exit i "$RC"
	[ "$RC" = 0 ] || unit_failed $u "drill.py manifest exited $RC (its ota_lite.py check: a manifest the updater does not take)"
	unit_ran $u "drill.py manifest exited 0"
}

unit_drill() {
	local u=drill
	check_point $u
	mkdir -p "$WORK/ota-state"
	RC=0; vss_capped "$OTA_PY" "$DRILL" run --manifest "$WORK/manifest.json" --state "$WORK/ota-state" --record "$WORK/record" \
		--stack-run "$STACK_RUN" --sim-python "$SIM_PY" --ota-python "$OTA_PY" --via spool --spool-dir "$SPOOL_DIR" \
		--status-dir "$STATUS_DIR" --sudo "sudo -n" < /dev/null || RC=$?
	cap_check $u
	fact $u exit i "$RC"
	case "$RC" in
		0|1) ;;
		2) unit_failed $u "drill.py run refused (exit 2): nothing started, or what started was undone" ;;
		*) unit_failed $u "drill.py run exited $RC" ;;
	esac
	[ -f "$WORK/record/drill-result.json" ] \
		|| unit_failed $u "drill.py run exited $RC and left no drill-result.json in its record: a run that ran writes it"
	unit_ran $u "drill.py run exited $RC (0: its verdict ok; 1: it ran, and its verdict is not ok)"
}

unit_down() {
	local u=down
	check_point $u
	RC=0; vss_capped env "${STACK_ENV[@]}" "$SIM_PY" "$STACK" down < /dev/null || RC=$?
	cap_check $u
	fact $u exit i "$RC"
	[ "$RC" = 0 ] || say "stack.py down exited $RC: the sweep removes what it left"
	unit_ran $u "stack.py down exited $RC"
}

# --- the stops -------------------------------------------------------------------------------------------------------
unit_state() {   # systemctl's word for the unit ota-lite, or unknown
	local st=""
	st="$(timeout 60 systemctl is-active "$UNIT" 2>/dev/null)" || true
	st="${st%%$'\n'*}"
	printf '%s\n' "${st:-unknown}"
}

remove_containers() {   # every container labelled sdv.ota.app or sdv.stack.run removed; when they cannot be listed, the
	# updater's and the stack's names, removed unseen (containers_removed false)
	local ids="" out lab n rc=0
	for lab in "${LABELS[@]}"; do
		out="$(timeout 60 sudo -n docker ps -aq --no-trunc --filter "label=$lab" 2>/dev/null)" || { rc=$?; break; }
		ids="$ids $out"
	done
	fact stop containers_list_exit i "$rc"
	if [ "$rc" != 0 ]; then
		say "the containers labelled ${LABELS[*]} could not be listed (docker ps exit $rc): removing the updater's and the stack's names"
		rc=0; timeout 120 sudo -n docker rm -f "${FALLBACK_NAMES[@]}" > /dev/null 2>&1 || rc=$?
		fact stop containers_fallback_rm_exit i "$rc"
		fact stop containers_removed b false
		return 0
	fi
	# shellcheck disable=SC2086  # the IDs are words
	set -- $ids
	n=$#
	fact stop containers_found i "$n"
	if [ "$n" -gt 0 ]; then
		rc=0; timeout 120 sudo -n docker rm -f "$@" > /dev/null 2>&1 || rc=$?
		fact stop containers_rm_exit i "$rc"
		say "removed $n container(s) labelled ${LABELS[*]} (exit $rc)"
	fi
	fact stop containers_removed b "$({ [ "$n" = 0 ] || [ "$rc" = 0 ]; } && echo true || echo false)"
}

shims_left() {   # the containerd-shims whose container docker no longer lists, waited for up to SHIM_WAIT_S (a removed
	# container's shim ends once its task is deleted); the program's own path names a shim, never a word of its arguments
	local out ids known s rc=0 left=0
	for _ in $(seq 1 $((SHIM_WAIT_S * 2))); do
		out="$(ps -ww -eo args= 2>/dev/null)" || out=""   # -ww: a $COLUMNS in the environment would cut a shim's -id short
		ids="$(printf '%s\n' "$out" | awk '$1 ~ /containerd-shim/ { for (k = 2; k < NF; k++) if ($k == "-id") print $(k + 1) }')"
		rc=0; known="$(timeout 60 sudo -n docker ps -aq --no-trunc 2>/dev/null)" || rc=$?
		[ "$rc" = 0 ] || break
		left=0
		for s in $ids; do
			case $'\n'"$known"$'\n' in *$'\n'"$s"$'\n'*) ;; *) left=$((left + 1)) ;; esac
		done
		[ "$left" -gt 0 ] || break
		sleep 0.5
	done
	fact stop shims_list_exit i "$rc"
	if [ "$rc" = 0 ]; then fact stop shims_left i "$left"; fi
	return 0
}

stop_verdict() {   # REASON...: drill.json's stop.verified, false with the reasons (stop.unverified) when the sweep could
	# not show its removals done; said in run.log, whose last 30 lines wait-run prints. The status line is not changed
	local j
	if [ "$#" = 0 ]; then fact stop verified b true; return 0; fi
	fact stop verified b false
	fact stop unverified lines "$(printf '%s\n' "$@")"
	j="$(printf '%s; ' "$@")"
	say "the stop is unverified: ${j%; }"
}

sweep() {   # every stop's removals once a unit has begun, DONE included, recorded under drill.json's stop
	local unv=() st rc le
	if [ ! -e "$WORK/state/started" ]; then
		fact stop swept b false
		fact stop why s "no unit began: nothing to sweep"
		return 0
	fi
	fact stop swept b true
	# the updater's unit first: one still running could start a container while the rest are removed
	st="$(unit_state)"
	fact stop unit_state_before s "$st"
	case "$st" in
		inactive|failed) ;;
		*) rc=0; timeout 60 sudo -n systemctl stop "$UNIT" > /dev/null 2>&1 || rc=$?
		   fact stop unit_stop_exit i "$rc"
		   st="$(unit_state)" ;;
	esac
	fact stop unit_state_after s "$st"
	case "$st" in
		inactive|failed) fact stop unit_inactive b true ;;
		*) fact stop unit_inactive b false
		   unv+=("the unit $UNIT is $st after a stop") ;;
	esac
	remove_containers
	le="$(cat "$WORK/facts/stop/containers_list_exit.i" 2>/dev/null || echo missing)"
	if [ "$le" != 0 ]; then
		unv+=("the containers labelled sdv.ota.app or sdv.stack.run could not be listed (docker ps exit $le)")
	elif [ "$(cat "$WORK/facts/stop/containers_removed.b" 2>/dev/null)" != true ]; then
		le="$(cat "$WORK/facts/stop/containers_rm_exit.i" 2>/dev/null || echo missing)"
		unv+=("docker rm -f of the containers labelled sdv.ota.app or sdv.stack.run exited $le")
	fi
	shims_left
	le="$(cat "$WORK/facts/stop/shims_list_exit.i" 2>/dev/null || echo missing)"
	if [ "$le" != 0 ]; then
		unv+=("the containers could not be listed to tell a containerd-shim's apart (docker ps exit $le)")
	elif [ "$(cat "$WORK/facts/stop/shims_left.i" 2>/dev/null)" != 0 ]; then
		unv+=("$(cat "$WORK/facts/stop/shims_left.i") containerd-shim(s) of a container docker no longer lists still run")
	fi
	stop_verdict ${unv[@]+"${unv[@]}"}
}

keep_file() {   # SRC: SRC copied into OUT under its own name, into a file the login owns: by cp, and when the login cannot
	# read SRC (the updater, root, writes its log and state 0600) by sudo -n cat; a copy that fails leaves no file
	local src="$1" dst
	dst="$OUT/$(basename "$1")"
	cp "$src" "$dst" 2>/dev/null && return 0
	rm -f "$dst"
	timeout 60 sudo -n cat "$src" > "$dst" 2>/dev/null && return 0
	rm -f "$dst"
	return 1
}

keep_record() {   # what the drill and the stack left, copied into OUT (THE RECORD); idempotent, whatever happened
	local f n run v kept=() from_state=() lost=()
	mkdir -p "$OUT"
	for f in "$WORK/record/drill-result.json" "$WORK/record/ota-lite.jsonl" "$WORK/record/state.json" \
		"$WORK/record"/status*.json; do
		[ -f "$f" ] || continue
		if keep_file "$f"; then kept+=("$(basename "$f")"); else lost+=("record/$(basename "$f")"); fi
	done
	for n in ota-lite.jsonl state.json; do   # a drill its cap cut short copied none: the updater's own, from its state
		if [ ! -f "$OUT/$n" ] && [ -f "$WORK/ota-state/$n" ]; then
			if keep_file "$WORK/ota-state/$n"; then kept+=("$n"); from_state+=("$n"); else lost+=("ota-state/$n"); fi
		fi
	done
	run="$(stack_run_dir)"
	if [ -n "$run" ] && [ -f "$run/manifest.json" ]; then
		if keep_file "$run/manifest.json"; then kept+=(manifest.json); else lost+=("runs/$(basename "$run")/manifest.json"); fi
	fi
	fact record kept lines "$(printf '%s\n' ${kept[@]+"${kept[@]}"} | sort)"
	[ "${#from_state[@]}" = 0 ] || fact record kept_from_state lines "$(printf '%s\n' "${from_state[@]}")"
	if [ "${#lost[@]}" != 0 ]; then
		fact record not_kept lines "$(printf '%s\n' "${lost[@]}")"
		say "not kept in the record (neither cp nor sudo -n cat could read them): ${lost[*]}"
	fi
	if [ -f "$OUT/drill-result.json" ]; then
		fact record result_found b true
		v="$(tool verdict "$OUT/drill-result.json" 2>&1)" || v="unreadable: $v"
		fact record verdict s "$v"
	else
		fact record result_found b false
	fi
	return 0
}

write_record() {   # STATUS STATUS-LINE AT REASON: drill.json, written whole
	tool record "$WORK" "$OUT/drill.json" "$1" "$2" "$3" "$4" "$HOST_MODE" "${UNITS[*]}"
}

finish() {   # STATUS [AT [REASON]]: the sweep, the record, then the status line; exits
	local st="$1" at="${2:-}" why="${3:-}" line u notrun=""
	trap - EXIT
	set +e
	if [ "$st" != DONE ]; then
		say "a clean stop: sync, then the sweep once a unit has begun (the unit ota-lite, the labelled containers, their shims)"
		timeout 120 sync
	fi
	sweep
	keep_record
	case "$st" in
		DONE) line="status=DONE" ;;
		TIMEOUT) line="status=TIMEOUT at=$at reason=$why" ;;
		*) line="status=FAILED at=$at" ;;
	esac
	if ! write_record "$st" "$line" "$at" "$why"; then
		say "drill.json could not be written"
		if [ "$st" = DONE ]; then st=FAILED; at=record; line="status=FAILED at=record"; fi
	fi
	if [ "$st" != DONE ]; then
		for u in "${UNITS[@]}"; do
			[ -n "$(cat "$WORK/facts/$u/state.s" 2>/dev/null)" ] || notrun="$notrun $u"
		done
		say "not run:${notrun:- none}"
	fi
	[ "$st" != FAILED ] || say "FAILED at $at: $why"
	# shellcheck disable=SC2086  # the status line's words; vss_status writes the status= itself
	vss_status ${line#status=}
	[ "$st" != FAILED ] || exit 1
	exit 0
}

on_exit() {   # the harness ended without a status line: a FAILED record all the same, the unit it was in recorded failed
	# (as unit_failed records one); each fact is best effort, for the fact store may be what failed
	local rc=$? why
	why="the harness stopped unexpectedly (exit $rc)"
	if [ "${CUR:-preflight}" != preflight ]; then
		fact "$CUR" state s failed || true
		fact "$CUR" why s "$why" || true
		secs "$CUR" || true
	fi
	finish FAILED "${CUR:-preflight}" "$why"
}

main() {
	local why
	CUR=preflight
	if [ -e "$WORK/state/started" ]; then   # a start by hand after a run: refused before anything of that run is touched
		say "VSS_HOME/drill-work holds an earlier run that began its units: this harness runs once per session (the harness" \
			"phase starts it); drill-work and OUT are left as that run left them"
		vss_status FAILED at=preflight
		exit 1
	fi
	rm -rf "$WORK"
	mkdir -p "$WORK/facts" "$WORK/state" "$OUT"
	write_tool
	trap on_exit EXIT
	say "run-ota-drill.sh VSS_HOST=${HOST_MODE//[^A-Za-z0-9._-]/?}: the OTA drill, a functional session, nothing timed"
	why="$(host_refusal)"
	[ -z "$why" ] || refuse "$why"
	if ! vss_deadline_load; then refuse "no readable deadline file (lib-vss-deadline.sh)"; fi
	fact preflight deadline_readable b true
	preflight
	cd "$REPO"
	unit_load
	unit_venv
	unit_prepare
	unit_up
	unit_manifest
	unit_drill
	unit_down
	finish DONE
}

main
