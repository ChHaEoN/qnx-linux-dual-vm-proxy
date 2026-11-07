"""run-aw-setup.sh and run-aw-suite.sh (SDV Phase 8 WP6 9.2): the Autoware session's two harnesses on a bare-metal AWS instance
(c7g.metal only: the owner, 2026-10-24), run here against stubs on the pattern of tests/test_vss_harness.py. No git runs here.

THE RIG. Each harness runs as remote-ladder.sh's detached runner runs it: from W/repo/orin-native/gpu-concurrency, with the
harness phase's environment (W, IFS_BIN, IMG_S, IMG_B, DISK, OUT, VSS_IN, AW_IN, VSS_HOME, STATUS, VPROBE, CSTATE,
VSS_HOST, and PLAN for the suite), stdout and stderr into the stem's run.log, the stem's host-before.txt already written by
the harness phase. W/repo holds the real harnesses, their helpers aw_setup.py and aw_suite.py, the real deadline library
and vss_setup.py (the record's writer), the real sdv/aw (the project entrypoint, ros-env.json and hostcheck.sh, which the
harnesses run), the real sdv/ctl modules and images.json, a scenario file of the real one's form whose map files are this
rig's stand-ins, and stand-ins for the launch script and latency_probe.py. repo.tar carries the commit in its pax header,
as `git archive` writes it. W/aw-in (AW_IN) holds the aw inputs of documentation values: aw-inputs.json, aw-scan.json
(9.1's form) and aw-map.tar, each hashed in inputs.env's FILES. W/rec/vss-setup is a finished run-vss-setup.sh of host
mode c7g-metal; for the suite, W/rec/aw-setup a finished run-aw-setup.sh, and W/sdv (VSS_HOME) holds the staged map and
the generation's vss_ctl.py (a stand-in with its DIGEST and COMPILED_PROFILE_IDS).

Every command either harness runs is a stub first on PATH, each logging one line (its name, whether it ran under the stub
sudo, its arguments) to calls.log: docker (a Python stand-in that also keeps each argv whole in docker-calls.jsonl and
keeps containers as files: pull, image inspect, info, run, exec, stop, logs, inspect, ps, rm, stats; the claim node, the
scenario driver, the bag recorder and the exporter leave what the real ones leave in their mounted output directories (the
driver's log holds its route line for STUB_ENGAGE_HOLD_S seconds before its engage line, when a test says so); a
`ros2 service list` that does not list every one of the simulator's services, or finds its container stopped, moves the
stub clock on by STUB_POLL_ADVANCE_S, 30 s unless a test says otherwise, since a poll takes time on a host),
id -nG, sudo (only `sudo -n`), pgrep, pkill, sync, install (the real one, unless STUB_INSTALL_FAIL_RE names the directories
it refuses), ip and sysctl (what hostcheck.sh reads: a test may change one once a container has started), sleep (a short
real sleep), date and timeout as in test_vss_harness.py (`date +%s` reads a fixed
clock that jumps once a regular expression matches run.log; `timeout` answers the :7150 readiness connect itself and cuts
a command matching STUB_CAP_RE after one second, the clock then at the cap's end). /proc/meminfo, L4T's release file and the
device tree's compatible are files of the rig's own (QNX_MEMINFO_FILE, QNX_L4T_RELEASE_FILE, QNX_DT_COMPATIBLE_FILE).

No container starts, no ROS runs, no AWS, no SSH, no board, no docker or QEMU of this machine.
The startup-qemu-virt used for the guest under KVM is ours, not a QNX-supported configuration; no boot timing is claimed.

Does not demonstrate: anything about an instance -- the pull, the image on Neoverse V1, Autoware's planning simulator, the
claim path, the guest; nor that the real claim node, scenario driver or exporter do what their stand-ins here do.
"""
import ast
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import string
import subprocess
import sys
import tarfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
G = os.path.join(REPO, "orin-native", "gpu-concurrency")
SETUP = os.path.join(G, "run-aw-setup.sh")
SUITE = os.path.join(G, "run-aw-suite.sh")
SETUP_TOOL = os.path.join(G, "aw_setup.py")
SUITE_TOOL = os.path.join(G, "aw_suite.py")
LIB = os.path.join(G, "lib-vss-deadline.sh")
VSS_SETUP = os.path.join(G, "vss_setup.py")
CAPTURE = os.path.join(REPO, "scripts", "aws", "capture.py")
AWS_README = os.path.join(REPO, "scripts", "aws", "README.md")
SDV_AW = os.path.join(REPO, "sdv", "aw")
SDV_CTL = os.path.join(REPO, "sdv", "ctl")
SCENARIO_SRC = os.path.join(SDV_CTL, "scenarios", "sample-lanelet-102.json")
IMAGES = os.path.join(REPO, "sdv", "stack", "images.json")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32",
                                reason="the harnesses run on Linux; their stubs need bash and coreutils' timeout")

T0 = 1800000000                        # the stub clock's epoch second
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GUEST = "192.168.100.10"
CTL_DIGEST = "0x12345678"              # the stand-in generation's kind 2 digest (a documentation value)
SETUP_STEPS = ["preflight", "stage", "pull", "smoke", "budget", "close"]
# spec-2 2.1: the containers of a run
CONTAINERS = ("aw-sim", "aw-claim-node", "aw-scenario", "ros-vss-feeder")
MAP_FILES = {"lanelet2_map.osm": b"<osm stand-in/>\n", "map_config.yaml": b"stand-in: 1\n",
             "map_projector_info.yaml": b"projector_type: MGRS\n", "pointcloud_map.pcd": b"# .PCD stand-in\n"}


def _images():
    with open(IMAGES, encoding="utf-8") as f:
        return json.load(f)


def _ref():
    aw = _images()["autoware"]
    return "%s@%s" % (aw["repo"], aw["arm64"]["manifest_digest"])


def _digest():
    return _images()["autoware"]["arm64"]["manifest_digest"]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(p, text, mode=None):
    os.makedirs(os.path.dirname(str(p)), exist_ok=True)
    with open(str(p), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode is not None:
        os.chmod(str(p), mode)


def _repo_tar(path, commit):
    """The repo tarball as `git archive <commit>` writes one: the commit in a pax global header."""
    data = b"stand-in"
    with tarfile.open(str(path), "w", format=tarfile.PAX_FORMAT, pax_headers={} if commit is None else {"comment": commit}) as t:
        info = tarfile.TarInfo("orin-native/gpu-concurrency/README.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))


def _map_tar(path, files=None, name="sample-map-planning", extra=None):
    files = dict(MAP_FILES if files is None else files)
    with tarfile.open(str(path), "w") as t:
        for n, data in sorted(files.items()):
            info = tarfile.TarInfo("%s/%s" % (name, n))
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        for info in extra or ():
            t.addfile(info, io.BytesIO(b"") if info.isreg() else None)


def _scenario():
    """The rig's scenario: the real one's form and values, its map files this rig's stand-ins."""
    with open(SCENARIO_SRC, encoding="utf-8") as f:
        doc = json.load(f)
    doc["map"]["files"] = {n: _sha(b) for n, b in sorted(MAP_FILES.items())}
    return doc


# --- the stubs ---------------------------------------------------------------------------------------------------

_LIB = r'''# the stubs' shared part (sourced)
stub_log() {
	local n="$1"; shift
	printf '%s\t%s\t%s\n' "$n" "${STUB_VIA_SUDO:-0}" "$*" >> "$STUB_DIR/calls.log"
}
st() { [ -e "$STUB_DIR/state/$1" ]; }
st_set() { mkdir -p "$STUB_DIR/state"; : > "$STUB_DIR/state/$1"; }
st_rm() { rm -f "$STUB_DIR/state/$1"; }
real() { PATH="$STUB_REAL_PATH" command -v "$1"; }
'''

_STUBS = {
    "sudo": r'''stub_log sudo "$@"
if [ "${1:-}" != -n ]; then echo "sudo: a terminal is required to read the password" >&2; exit 1; fi
shift
export STUB_VIA_SUDO=1
exec "$@"
''',
    "id": r'''if [ "$*" = -nG ]; then stub_log id "$@"; printf '%s\n' "${STUB_GROUPS-}"; exit 0; fi
exec "$(real id)" "$@"
''',
    "pgrep": r'''stub_log pgrep "$@"
[ "$*" = "-x qemu-system-aar" ] || exit 1
st qemu && { echo 4242; exit 0; }
exit 1
''',
    "pkill": r'''stub_log pkill "$@"
st qemu || exit 1
st_rm qemu
exit 0
''',
    "sync": 'stub_log sync "$@"\n',
    # the real install, unless a test names the directories it refuses (a work directory on a full or read-only disk)
    "install": r'''stub_log install "$@"
if [ -n "${STUB_INSTALL_FAIL_RE:-}" ] && printf '%s' "$*" | grep -qE "$STUB_INSTALL_FAIL_RE"; then
	echo "install: cannot create directory: the stub's failure" >&2; exit 1
fi
exec "$(real install)" "$@"
''',
    "sleep": r'''exec "$(real sleep)" 0.02
''',
    # hostcheck.sh's two reads (2.12): lo's flags and three sysctls; once a container has started a test may change one
    "ip": r'''stub_log ip "$@"
[ "$*" = "-br link show lo" ] || exit 1
flags="LOOPBACK,UP,LOWER_UP"
if [ -n "${STUB_LO_MULTICAST_AFTER:-}" ] && st container-started; then flags="LOOPBACK,MULTICAST,UP,LOWER_UP"; fi
echo "lo               UNKNOWN        00:00:00:00:00:00 <$flags> "
''',
    "sysctl": r'''stub_log sysctl "$@"
[ "${1:-}" = -n ] || exit 255
if [ -n "${STUB_SYSCTL_FAIL:-}" ] || { [ -n "${STUB_SYSCTL_FAIL_AFTER:-}" ] && st container-started; }; then
	echo "sysctl: cannot stat /proc/sys/${2//./\/}: the stub's failure" >&2; exit 255
fi
case "${2:-}" in
	net.core.rmem_max)
		if [ -n "${STUB_RMEM_AFTER:-}" ] && st container-started; then echo "$STUB_RMEM_AFTER"; else echo 212992; fi ;;
	net.ipv4.ipfrag_time) echo 30 ;;
	net.ipv4.ipfrag_high_thresh) echo 4194304 ;;
	*) exit 255 ;;
esac
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
case "$*" in
	*/dev/tcp/*)
		mkdir -p "$STUB_DIR/state"
		n=$(( $(cat "$STUB_DIR/state/ready-count" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STUB_DIR/state/ready-count"
		[ -z "${STUB_READY_NEVER:-}" ] || exit 1
		[ "$n" -gt "${STUB_READY_FAILS:-0}" ] && exit 0
		exit 1 ;;
esac
if [ -n "${STUB_CAP_RE:-}" ] && printf '%s' "$*" | grep -qE "$STUB_CAP_RE"; then
	rc=0; "$(real timeout)" --kill-after=1s "${STUB_CAP_S:-1}" "$@" || rc=$?
	if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then echo $(( $(cat "$QNX_METAL_DEADLINE_FILE") - 1500 + 600 )) > "$STUB_DIR/clock"; fi
	exit "$rc"
fi
exec "$(real timeout)" "${opts[@]}" "$dur" "$@"
''',
}

# docker, a stand-in (THE RIG above). Containers are files under state/docker/<name>.json.
_DOCKER = r'''#!/usr/bin/env python3
import json, os, re, sys, time
STUB = os.environ["STUB_DIR"]
CDIR = os.path.join(STUB, "state", "docker")
os.makedirs(CDIR, exist_ok=True)
argv = sys.argv[1:]
via = os.environ.get("STUB_VIA_SUDO", "0")
with open(os.path.join(STUB, "calls.log"), "a") as f:
    f.write("docker\t%s\t%s\n" % (via, " ".join(argv)))
with open(os.path.join(STUB, "docker-calls.jsonl"), "a") as f:
    f.write(json.dumps(argv) + "\n")
E = os.environ.get
if E("STUB_SLEEP_ON") and re.search(E("STUB_SLEEP_ON"), "docker " + " ".join(argv)):
    time.sleep(float(E("STUB_SLEEP_S", "10")))


def st(n):
    return os.path.exists(os.path.join(STUB, "state", n))


def st_set(n, text=""):
    with open(os.path.join(STUB, "state", n), "w") as f:
        f.write(text)


def die(msg, rc):
    sys.stderr.write(msg + "\n")
    sys.exit(rc)


if via != "1" and "docker" not in E("STUB_GROUPS", "").split():
    die("permission denied while trying to connect to the docker API at unix:///var/run/docker.sock", 1)


def path(n):
    return os.path.join(CDIR, n + ".json")


def load(n):
    try:
        with open(path(n)) as f:
            return json.load(f)
    except OSError:
        return None


def save(c):
    with open(path(c["name"]), "w") as f:
        json.dump(c, f)


def every():
    return [load(n[:-5]) for n in sorted(os.listdir(CDIR)) if n.endswith(".json")]


def host_of(mounts, p):
    best = ""
    for cont in mounts:
        if (p == cont or p.startswith(cont.rstrip("/") + "/")) and len(cont) > len(best):
            best = cont
    if not best:
        die("docker stub: %s is in no mount" % p, 125)
    return mounts[best] + p[len(best):]


def lines(p, docs, step=0.0):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        for d in docs:
            f.write(json.dumps(d, separators=(",", ":")) + "\n")
            f.flush()
            if d.get("step") == "engage" and d.get("outcome") == "done":
                st_set("engaged")
            if d.get("step") == "route" and d.get("outcome") == "done" and E("STUB_ENGAGE_HOLD_S"):
                time.sleep(float(E("STUB_ENGAGE_HOLD_S")))       # the engage step takes time on a host
            if step:
                time.sleep(step)


def opt(words, k):
    return words[words.index(k) + 1] if k in words else None


def poll_takes_time():
    # a poll of a simulator that is not up takes time on a host (the exec's own bound): the stub clock moves on
    with open(os.path.join(STUB, "clock")) as f:
        t = int(f.read())
    with open(os.path.join(STUB, "clock"), "w") as f:
        f.write(str(t + int(E("STUB_POLL_ADVANCE_S", "30"))))


cmd = argv[0] if argv else ""
if cmd == "pull":
    if E("STUB_PULL_RC", "0") != "0":
        die("Error response from daemon: the stub's pull failure", int(E("STUB_PULL_RC")))
    st_set("pulled")
    print("%s: Pulling from stub\nDigest: %s\nStatus: Downloaded newer image for %s\n%s" % (
        argv[1].split("@")[0], argv[1].split("@")[-1], argv[1], argv[1]))
elif argv[:2] == ["image", "inspect"]:
    if not (st("pulled") or E("STUB_IMAGE_PRESENT")):
        die("Error response from daemon: No such image: %s" % argv[2], 1)
    ref = argv[2]
    digests = E("STUB_REPO_DIGESTS", ref).split()
    print(json.dumps([{"Id": E("STUB_IMAGE_ID", ref.split("@")[-1]), "RepoDigests": digests, "RepoTags": [],
                       "Os": "linux", "Architecture": E("STUB_IMAGE_ARCH", "arm64"),
                       "Config": {"Labels": {"RAW-INSPECT-SENTINEL": "1"}, "Entrypoint": ["/docker-entrypoint.sh"]}}]))
elif cmd == "info":
    if argv[1:] == ["-f", "{{json .DriverStatus}}"]:
        print(E("STUB_DRIVER_STATUS", '[["driver-type","io.containerd.snapshotter.v1"]]'))
    else:
        print("RAW-DOCKER-INFO-SENTINEL")
elif cmd == "run":
    vals, flags, i = {}, set(), 1
    VALUE = ("--name", "--label", "--network", "--user", "--group-add", "--cap-drop", "--security-opt", "--entrypoint",
             "-v", "-e")
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a in ("--rm", "-d"):
            flags.add(a)
            i += 1
        elif a in VALUE and i + 1 < len(argv):
            vals.setdefault(a, []).append(argv[i + 1])
            i += 2
        else:
            die("docker stub: unknown run flag %s" % a, 125)
    image, words = argv[i], argv[i + 1:]
    name = (vals.get("--name") or [""])[0]
    mounts = {}
    for v in vals.get("-v", []):
        parts = v.split(":")
        mounts[parts[1]] = parts[0]
    if load(name) is not None:
        die("docker: Error response from daemon: Conflict. The container name \"/%s\" is already in use" % name, 125)
    st_set("container-started")
    labels = dict(x.split("=", 1) if "=" in x else (x, "") for x in vals.get("--label", []))
    c = {"name": name, "labels": labels, "running": True, "exit": 0, "mounts": mounts, "log": "", "image": image}
    if name == "aw-smoke":
        rc = int(E("STUB_SMOKE_RC", "0"))
        print("usage: ros2 [-h] [--use-python-default-buffering] Call `ros2 <command> -h` for more detailed usage. ...")
        if E("STUB_SMOKE_ERR"):
            sys.stderr.write(E("STUB_SMOKE_ERR") + "\n")
        if rc == 132:
            sys.stderr.write("Illegal instruction (core dumped)\n")
        sys.exit(rc)
    elif name == "aw-sim":
        c["running"] = not E("STUB_SIM_DIES")
        save(c)
        print("c0ffee%s" % ("0" * 58))
    elif name == "aw-claim-node":
        out = host_of(mounts, opt(words, "--out"))
        if E("STUB_CLAIM_REFUSE"):
            c.update(running=False, exit=2, log="ctl_claim_node: refused: the stub's refusal")
            save(c)
        else:
            inj = [w for w in words[words.index("--inject"):] if ":" in w] if "--inject" in words else []
            reasons = {"nan": 9, "undef": 10, "reserved": 10, "profile0": 8, "kind9": 5, "interval": 11, "speed": 12,
                       "accel": 13, "jerk": 14, "steer": 15, "steer-rate": 16, "lat-accel": 17, "overspeed": 18,
                       "rolling-back": 19}
            docs = [{"header": {"format": 1, "kind": 2, "mode": "node", "target": "%s:%s" % (opt(words, "--host"),
                                                                                         opt(words, "--port")),
                                "injections": inj, "demo": opt(words, "--demo")}}]
            n = max([40] + [int(w.split(":")[0]) + 5 for w in inj])
            for seq in range(1, n + 1):
                hit = [w.split(":")[1] for w in inj if int(w.split(":")[0]) == seq]
                r = reasons[hit[0]] if hit else 0
                docs.append({"seq": seq, "frame": "07" + "00" * 63, "outcome": "replied", "verdict": 0 if r == 0 else 1,
                             "reason": r, "mono_ns": 1000000 * seq})
            docs.append({"summary": {"counters": {"controls": n, "replied": n, "drop": 0, "lost_on_reconnect": 0},
                                     "identity": {"holds": True}}})
            lines(os.path.join(out, "replies.jsonl"), docs)
            c["log"] = ("ctl_claim_node: controls=%d replied=%d (accepted=%d rejected=%d) drop=0 lost_on_reconnect=0 "
                        "reconnects=0 identity=holds" % (n, n, n - len(inj), len(inj)))
            save(c)
        st_set("claim-started")
        print("c1aim%s" % ("0" * 59))
    elif name == "aw-scenario":
        out = host_of(mounts, opt(words, "--out"))
        rows = [{"step": "map", "outcome": "done", "success": None, "code": None, "message": None, "state": None,
                 "detail": "", "mono_ns": None, "ros_ns": None, "scenario": "sample-lanelet-102"}]
        claim = load("aw-claim-node")
        if "--require-claim-node" in words and not (claim and claim["running"]):
            rows.append({"step": "route", "outcome": "refused", "success": None, "code": None, "message": None,
                         "state": None, "detail": "no claim node", "mono_ns": 1, "ros_ns": 1})
            lines(os.path.join(out, "scenario.jsonl"), rows)
            sys.exit(2)
        timeout_re = E("STUB_SCENARIO_TIMEOUT_RE", "")
        timed_out = bool(timeout_re) and re.search(timeout_re, out) is not None
        for k, (step, state) in enumerate((("localize", 3), ("route", 2), ("engage", 2), ("arrive", 3), ("clear", None))):
            if step == "arrive" and timed_out:
                rows.append({"step": "arrive", "outcome": "timeout", "success": None, "code": None, "message": None,
                             "state": 2, "detail": "routing state never ARRIVED", "mono_ns": k, "ros_ns": k})
                break
            rows.append({"step": step, "outcome": "done", "success": None if step == "arrive" else True, "code": 0,
                         "message": "", "state": state, "detail": "", "mono_ns": k, "ros_ns": k})
        lines(os.path.join(out, "scenario.jsonl"), rows, step=float(E("STUB_SCENARIO_STEP_S", "0.05")))
        print("aw_scenario: %s" % ("timeout in step arrive" if timed_out else "arrived"), file=sys.stderr)
        sys.exit(3 if timed_out else 0)
    else:
        die("docker stub: no container %r of this rig" % name, 125)
elif cmd == "exec":
    words = argv[1:]
    detach = words[0] == "-d"
    if detach:
        words = words[1:]
    name, rest = words[0], words[1:]
    c = load(name)
    line = " ".join(rest)
    if c is None or not c["running"]:
        if line.endswith("ros2 service list"):
            poll_takes_time()         # the wait's bound is the clock's: a poll of a stopped simulator moves it on too
        die("Error response from daemon: container %s is not running" % name, 1)
    if line.endswith("ros2 service list"):
        n = int(open(os.path.join(STUB, "state", "sim-polls")).read()) + 1 if st("sim-polls") else 1
        st_set("sim-polls", str(n))
        print("/rosout/get_parameters")
        up = not E("STUB_SIM_NEVER_UP") and n > int(E("STUB_SIM_UP_AFTER", "0"))
        if E("STUB_SIM_PARTIAL"):
            print("/api/localization/initialize")      # part-way up: the first of the services the driver calls, no more
        elif up:
            print("/api/localization/initialize\n/api/routing/set_route_points\n/api/routing/clear_route\n"
                  "/api/operation_mode/change_to_autonomous")
        if E("STUB_SIM_PARTIAL") or not up:
            poll_takes_time()
    elif line.endswith("ros2 component list"):
        # the planning simulator's form: the controller a composable node in the container that also holds the gate
        print("/map/map_container\n  1  /map/pointcloud_map_loader\n/control/control_check_container\n"
              "  1  /control/trajectory_follower/lane_departure_checker_node\n/control/control_container\n"
              "  1  /control/autoware_shift_decider")
        if not E("STUB_NO_CONTROLLER"):
            print("  2  /control/trajectory_follower/controller_node_exe")
        print("  5  /control/vehicle_cmd_gate")
    elif rest[:4] == ["/sdv-aw/aw-entrypoint.sh", "ros2", "component", "unload"]:
        if rest[4:] != ["/control/control_container", "2"]:
            die("Failed to unload component %s from %s" % (rest[5:], rest[4:5]), 1)
        st_set("killed", "after-engage" if st("engaged") else "before-engage")
        print("Unloaded component 2 from '/control/control_container' container node")
    elif rest[:2] == ["pkill", "-f"] and "controller_node_exe" in rest:
        sys.exit(1)               # no process bears the composable node's name (the planning simulator's form)
    elif rest[:2] == ["/sdv-aw/aw-entrypoint.sh", "ros2"] and rest[2:4] == ["bag", "record"]:
        bag = host_of(c["mounts"], opt(rest, "-o"))
        os.makedirs(bag, exist_ok=True)
        st_set("recording", bag)
    elif rest[:3] == ["pkill", "-INT", "-f"] and "ros2 bag record" in rest[3]:
        bag = open(os.path.join(STUB, "state", "recording")).read()
        with open(os.path.join(bag, "metadata.yaml"), "w") as f:
            f.write("rosbag2_bagfile_information:\n  version: 9\n")
        with open(os.path.join(bag, "bag_0.mcap"), "w") as f:
            f.write("a bag stand-in\n")
    elif "ctl_export.py" in line:
        out = host_of(c["mounts"], opt(rest, "--out"))
        bag = host_of(c["mounts"], opt(rest, "--bag"))
        if not os.path.exists(os.path.join(bag, "metadata.yaml")):
            die("ctl_export: refused: no bag at %s" % opt(rest, "--bag"), 2)
        lines(out, [{"topic": "/control/command/control_cmd", "recv_ns": 1, "stamp_ns": 1, "fields": {}},
                    {"summary": {"messages": {"/control/command/control_cmd": 1}, "bag_sha256": {"bag_0.mcap": "0" * 64},
                                 "export_format": 1}}])
    else:
        die("docker stub: exec %s" % line, 2)
elif cmd == "stop":
    c = load(argv[-1])
    if c is None:
        die("Error response from daemon: No such container: %s" % argv[-1], 1)
    c["running"] = False
    if c["name"] == "aw-claim-node":
        c["exit"] = int(E("STUB_CLAIM_EXIT", "0"))
    save(c)
    print(argv[-1])
elif cmd == "logs":
    c = load(argv[-1])
    if c is None:
        die("Error response from daemon: No such container: %s" % argv[-1], 1)
    print(c["log"])
elif cmd == "inspect":
    c = load(argv[-1])
    if c is None:
        die("Error: No such object: %s" % argv[-1], 1)
    fmt = argv[2]
    print({"{{.State.ExitCode}}": str(c["exit"]), "{{.State.Running}}": "true" if c["running"] else "false"}[fmt])
elif cmd == "ps":
    if E("STUB_DOCKER_PS_FAIL") or (E("STUB_DOCKER_PS_FAIL_AFTER") and st("container-started")):
        die("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?", 1)
    key = argv[argv.index("--filter") + 1].split("=", 1)[1]
    for c in every():
        if key.split("=")[0] in c["labels"]:
            print(c["name"])
elif cmd == "rm":
    if E("STUB_DOCKER_RM_FAIL"):
        die("Error response from daemon: the stub's removal failure", 1)
    for n in argv[2:]:
        if os.path.exists(path(n)):
            os.remove(path(n))
elif cmd == "stats":
    for c in every():
        if c["running"]:
            print("%s\t1.25%%\t512MiB / 31.2GiB" % c["name"])
else:
    die("docker stub: %s" % " ".join(argv), 2)
'''

# The guest's launch script, a stand-in: the console, QEMU "running", the real one's output (test_vss_harness.py's).
# STUB_BOOT=hang: a boot that does not end, once QEMU "runs" (the cap on the boot cuts it).
_LAUNCH = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log launch "IFS_BIN=${IFS_BIN:?} DISK=${DISK:?} LOG=${LOG:?}"
if st qemu; then echo "ERROR: a qemu-system-aarch64 is already running." >&2; exit 1; fi
mkdir -p "$(dirname "$LOG")"
cp "$STUB_DIR/console.bin" "$LOG"
st_set qemu
if [ "${STUB_BOOT:-ok}" = hang ]; then exec "$(real sleep)" 30; fi
echo "ifs    : ${IFS_BIN}  sha256 0123456789abcdef..."
echo "console: ${LOG}"
echo "waiting for the guest to answer on 192.168.100.10 ..."
if [ "${STUB_BOOT:-ok}" = fail ]; then echo "ERROR: guest did not answer on :7100 within 60s." >&2; exit 1; fi
echo "guest up after 7s (monitor answering on :7100)"
'''

# latency_probe.py, a stand-in: the real one's RESULT line, with values that must reach no output.
# STUB_SMOKE7100_HANG: a smoke that does not end (the cap on the guest's checks cuts it).
_LATENCY = r'''#!/usr/bin/env python3
import json, os, sys, time
with open(os.path.join(os.environ["STUB_DIR"], "calls.log"), "a") as f:
    f.write("latency_probe\t0\t%s\n" % " ".join(sys.argv[1:]))
rc = int(os.environ.get("STUB_SMOKE7100_RC", "0"))
if rc:
    print("FATAL connect: [Errno 113] No route to host")
    sys.exit(rc)
if os.environ.get("STUB_SMOKE7100_HANG"):
    time.sleep(30)
res = {"tag": "run", "n": 20, "bad": int(os.environ.get("STUB_SMOKE7100_BAD", "0")),
       "rejected_by_monitor": int(os.environ.get("STUB_SMOKE7100_REJ", "0")), "min_ms": 7.654321, "p50_ms": 7.754321, "max_ms": 8.154321}
print("RESULT %s" % json.dumps(res))
'''

RULES_CTL = ("monitor: ctl rules: kind 2, catalog %s (vss 6.0), dt_max 100 ms, overspeed 1.2 x v_cmd + 2 m/s, rollback 0.5 m/s, "
             "tol17 0.5 m/s^2, profiles 1 2")


def _console(ctl=None):
    body = [b"\0\0Startup complete", b"monitor: claim kinds: 0 mnist (us <= 50000), 1 vlm model 1 (us <= 1), conf_min=60%",
            b"monitor: vss rules: kind 4, catalog 0x4D68EA68 (vss 6.0), age_max 300 ms, profiles 1 2 4",
            (RULES_CTL % CTL_DIGEST).encode() if ctl is None else ctl,
            b"monitor: ctl profile 1: L 2790 mm, v_max 25 m/s, a_max 5 m/s^2, jerk_max 80 m/s^3, steer_max 1 rad, "
            b"steer_rate_max 1 rad/s, lat_acc_max 5 m/s^2",
            b"monitor: service monitor listening on :7150 (frame=64 bytes), deadline 500 ms"]
    return b"".join(x + b"\r\n" for x in body)


class Rig:
    """W as the harness phase leaves it for one aw harness, the stubs, and the run (THE RIG above)."""

    def __init__(self, base, stem="aw-setup", plan=None):
        self.base = base
        self.stem_name = stem
        self.plan = plan
        self.w = base / "w"
        self.repo = self.w / "repo"
        self.g = self.repo / "orin-native" / "gpu-concurrency"
        self.stem = self.w / "rec" / stem
        self.out = self.stem / "raw"
        self.status = self.stem / "status"
        self.runlog = self.stem / "run.log"
        self.aw_in = self.w / "aw-in"
        self.vss_home = self.w / "sdv"
        self.stub = base / "stub"
        self.home = base / "home"
        self.tmp = base / "tmpdir"
        self.deadline = base / "deadline"
        self.meminfo = base / "meminfo"
        for d in (self.g, self.stem, self.aw_in, self.w / "in", self.home, self.tmp, self.w / "img", self.stub / "state"):
            os.makedirs(str(d), exist_ok=True)
        for f in (SETUP, SUITE, SETUP_TOOL, SUITE_TOOL, LIB, VSS_SETUP):
            shutil.copy(f, str(self.g / os.path.basename(f)))
        _write(self.g / "launch-qnx-kvm-bridged.sh", _LAUNCH)
        _write(self.g / "latency_probe.py", _LATENCY)
        shutil.copytree(SDV_AW, str(self.repo / "sdv" / "aw"))
        os.chmod(str(self.repo / "sdv" / "aw" / "aw-entrypoint.sh"), 0o755)
        os.makedirs(str(self.repo / "sdv" / "ctl" / "scenarios"))
        for n in ("ctl_claim_node.py", "aw_scenario.py", "ctl_export.py", "ctlclient.py", "ctlframe.py"):
            shutil.copy(os.path.join(SDV_CTL, n), str(self.repo / "sdv" / "ctl" / n))
        _write(self.repo / "sdv" / "ctl" / "scenarios" / "sample-lanelet-102.json", json.dumps(_scenario(), indent=2))
        os.makedirs(str(self.repo / "sdv" / "stack"))
        shutil.copy(IMAGES, str(self.repo / "sdv" / "stack" / "images.json"))
        _repo_tar(self.w / "repo.tar", COMMIT)
        (self.w / "img" / "ifs-ctl.bin").write_bytes(b"ifs-ctl stand-in")
        (self.w / "img" / "disk-qemu").write_bytes(b"disk stand-in")
        (self.w / "in" / "bundle.json").write_bytes(b'{"format": 1}\n')
        _write(self.stem / "host-before.txt", "== a stand-in host-before (the harness phase's)\n")
        self.set_vss_setup()
        self.aw_inputs()
        _write(self.vss_home / "gen" / "vss_ctl.py", "FORMAT = 1\nDIGEST = %s\nCOMPILED_PROFILE_IDS = (1, 2)\n" % CTL_DIGEST)
        _write(self.meminfo, "MemTotal:       32000000 kB\nMemFree:        30000000 kB\nMemAvailable:   29000000 kB\n")
        _write(self.stub / "_lib.sh", _LIB)
        for name, body in _STUBS.items():
            _write(self.stub / name, "#!/usr/bin/env bash\n. \"$STUB_DIR/_lib.sh\"\n" + body, 0o755)
        _write(self.stub / "docker", _DOCKER, 0o755)
        (self.stub / "console.bin").write_bytes(_console())
        _write(self.stub / "clock", str(T0))
        self.ahead(180 * 60)
        if stem == "aw-suite":
            self.set_aw_setup()
            for n, b in MAP_FILES.items():
                p = self.vss_home / "aw" / "map" / "sample-map-planning" / n
                os.makedirs(str(p.parent), exist_ok=True)
                p.write_bytes(b)

    def set_vss_setup(self, last="status=DONE", done=True, host_mode="c7g-metal", status="DONE"):
        d = self.w / "rec" / "vss-setup"
        _write(d / "status", last + "\n")
        if done:
            _write(d / "done", "")
        elif (d / "done").exists():
            os.remove(str(d / "done"))
        doc = {"format": 1, "harness": "run-vss-setup.sh", "status": status, "skip_modes": [], "skip": [], "facts": {}}
        if host_mode is not None:
            doc["host_mode"] = host_mode
        _write(d / "raw" / "setup.json", json.dumps(doc, indent=1))

    def set_aw_setup(self, last="status=DONE", done=True, budget_short=False, host_mode="c7g-metal", status="DONE"):
        d = self.w / "rec" / "aw-setup"
        _write(d / "status", last + "\n")
        if done:
            _write(d / "done", "")
        elif (d / "done").exists():
            os.remove(str(d / "done"))
        doc = {"format": 1, "harness": "run-aw-setup.sh", "status": status, "budget_short": budget_short,
               "image": {"ref": _ref(), "id": _digest()}, "facts": {}}
        if host_mode is not None:
            doc["host_mode"] = host_mode
        _write(d / "raw" / "setup.json", json.dumps(doc, indent=1))

    def aw_inputs(self, scan=None, files_env=None, listed=None, commit=COMMIT, map_files=None, wrong_listed=()):
        """AW_IN as remote-ladder.sh's setup leaves it: aw-inputs.json, aw-scan.json, aw-map.tar; FILES in inputs.env.
        wrong_listed: files aw-inputs.json gives another sha256 than theirs (FILES keeps theirs)."""
        scan = scan if scan is not None else {"format": 1, "image_digest": _digest(), "elf_files": 3,
                                               "findings": [{"layer": "sha256:" + "ab" * 32, "path": "usr/lib/libx.so.1",
                                                             "unguarded": 2}],
                                               "exceptions_applied": [], "verdict": "fail"}
        _write(self.aw_in / "aw-scan.json", scan if isinstance(scan, str) else json.dumps(scan))
        _map_tar(self.aw_in / "aw-map.tar", files=map_files)
        files = {n: _sha((self.aw_in / n).read_bytes()) for n in ("aw-scan.json", "aw-map.tar")}
        doc = {"format": 1, "commit": commit, "files": dict(files) if listed is None else listed}
        for n in wrong_listed:
            doc["files"][n] = "0" * 64
        _write(self.aw_in / "aw-inputs.json", json.dumps(doc, indent=1))
        files["aw-inputs.json"] = _sha((self.aw_in / "aw-inputs.json").read_bytes())
        env = dict(files, **{"bundle.json": _sha(b'{"format": 1}\n')})
        if files_env is not None:
            env = files_env(env)
        _write(self.w / "inputs.env", "IFS_NAME=ifs-ctl.bin\nIFS_SHA256=%s\nREPO_COMMIT=%s\nFILES=%s\n" % (
            "a" * 64, COMMIT, " ".join("%s:%s" % kv for kv in sorted(env.items()))))

    def ahead(self, seconds):
        _write(self.deadline, str(T0 + seconds))

    def env(self, **cfg):
        drop = {k for k in os.environ if k.startswith(("STUB_", "VSS_", "SDV_", "QNX_", "AW_"))} | {
            "PLAN", "K", "STATUS", "OUT", "IFS_BIN", "DISK", "W", "PYTHONDONTWRITEBYTECODE"}
        e = {k: v for k, v in os.environ.items() if k not in drop}
        img = str(self.w / "img" / "ifs-ctl.bin")
        e.update(W=str(self.w), IFS_BIN=img, IMG_S=img, IMG_B=img, DISK=str(self.w / "img" / "disk-qemu"),
                 VPROBE=str(self.w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), OUT=str(self.out), CSTATE="shallow",
                 VSS_IN=str(self.w / "in"), AW_IN=str(self.aw_in), VSS_HOME=str(self.vss_home), STATUS=str(self.status),
                 VSS_HOST="c7g-metal", QNX_METAL_DEADLINE_FILE=str(self.deadline), QNX_MEMINFO_FILE=str(self.meminfo),
                 QNX_L4T_RELEASE_FILE=str(self.base / "nv_tegra_release"),
                 QNX_DT_COMPATIBLE_FILE=str(self.base / "dt-compatible"),
                 PATH=str(self.stub) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.stub),
                 STUB_REAL_PATH=os.environ["PATH"], STUB_JUMP_FILE=str(self.runlog), STUB_GROUPS="ubuntu adm kvm docker",
                 HOME=str(self.home), TMPDIR=str(self.tmp), PYTHONDONTWRITEBYTECODE="1")
        if self.plan is not None:
            e["PLAN"] = self.plan
        for k, v in cfg.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def run(self, timeout=240, **cfg):
        harness = "run-aw-setup.sh" if self.stem_name == "aw-setup" else "run-aw-suite.sh"
        with open(str(self.runlog), "ab") as log:
            p = subprocess.run([BASH, str(self.g / harness)], stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, cwd=str(self.g), env=self.env(**cfg), timeout=timeout)
        return Result(self, p.returncode)


class Result:
    def __init__(self, rig, rc):
        self.rig, self.rc = rig, rc
        self.log = rig.runlog.read_text(encoding="utf-8", errors="replace")
        self.status = rig.status.read_text(encoding="utf-8").splitlines() if rig.status.exists() else []
        name = "setup.json" if rig.stem_name == "aw-setup" else "suite.json"
        p = rig.out / name
        self.doc = None
        if p.exists():
            with open(str(p), encoding="utf-8") as f:
                self.doc = json.load(f)
        cl = rig.stub / "calls.log"
        self.calls = [tuple(ln.split("\t", 2)) for ln in cl.read_text(encoding="utf-8").splitlines()] if cl.exists() else []
        dc = rig.stub / "docker-calls.jsonl"
        self.docker = [json.loads(ln) for ln in dc.read_text(encoding="utf-8").splitlines()] if dc.exists() else []
        self.before, self.after = {}, {}

    def why(self):
        return "rc %s, status %s\n%s" % (self.rc, self.status, self.log[-5000:])

    def idx(self, name, pattern=""):
        for i, (n, _v, args) in enumerate(self.calls):
            if n == name and re.search(pattern, args):
                return i
        return -1

    def idx_all(self, name, pattern=""):
        return [i for i, (n, _v, args) in enumerate(self.calls) if n == name and re.search(pattern, args)]

    def runs(self, name=None):
        """Every `docker run` argv, or those of one container name."""
        out = [a for a in self.docker if a and a[0] == "run"]
        return [a for a in out if name is None or _opt(a, "--name") == name]

    def facts(self, *path):
        d = self.doc["facts"]
        for k in path:
            d = d[k]
        return d

    def state(self, name):
        return self.rig.stub / "state" / name


def _opt(argv, k):
    return argv[argv.index(k) + 1] if k in argv else None


def _opts(argv, k):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == k]


def _image_and_cmd(argv):
    """A `docker run` argv's image and command (after its flags, each flag but --rm and -d taking one value)."""
    i = 1
    while argv[i].startswith("-"):
        i += 1 if argv[i] in ("--rm", "-d") else 2
    return argv[i], argv[i + 1:]


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


def holds_2_12(argv, repo):
    """Why a `docker run` argv of the Autoware image breaks 2.12 on a metal host (spec-2 9.2), or [] when it holds."""
    bad = []
    if _opt(argv, "--entrypoint") != "/sdv-aw/aw-entrypoint.sh":
        bad.append("no --entrypoint /sdv-aw/aw-entrypoint.sh")
    if "%s/sdv/aw:/sdv-aw:ro" % repo not in _opts(argv, "-v"):
        bad.append("the tarball's sdv/aw not mounted read-only at /sdv-aw")
    if _opt(argv, "--user") != "aw":
        bad.append("no --user aw")
    if "ALL" not in _opts(argv, "--cap-drop"):
        bad.append("no --cap-drop ALL")
    if "no-new-privileges" not in _opts(argv, "--security-opt"):
        bad.append("no --security-opt no-new-privileges")
    if "CYCLONEDDS_URI=file:///sdv-dds/cyclonedds.xml" not in _opts(argv, "-e"):
        bad.append("CYCLONEDDS_URI does not name 2.7's file")
    if not any(v.endswith(":/sdv-dds:ro") for v in _opts(argv, "-v")):
        bad.append("2.7's file not mounted read-only")
    for a in argv:
        if a == "--privileged" or a.startswith("--privileged=") or a.startswith("--cap-add") or "cyclonedds.xml" in a and \
                "/home/aw" in a:
            bad.append("forbidden: %s" % a)
    for v in _opts(argv, "-v"):
        target = v.split(":")[1] if ":" in v else v
        if target == "/proc" or target.startswith("/proc/") or target == "/sys" or target.startswith("/sys/"):
            bad.append("a /proc or /sys mount: %s" % v)
    image, _cmd = _image_and_cmd(argv)
    if image != _ref():
        bad.append("image %s, not the pinned digest's reference" % image)
    return bad


# --- run-aw-setup.sh: a whole run ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def setup_done(tmp_path_factory):
    """One whole run-aw-setup.sh with every stub answering as c7g.metal should: the run most setup tests read."""
    rig = Rig(tmp_path_factory.mktemp("aw-setup"))
    before = _snapshot(rig.base)
    res = rig.run()
    res.before, res.after = before, _snapshot(rig.base)
    return res


def test_setup_a_whole_run_ends_done_with_its_setup_json_written_first(setup_done):
    r = setup_done
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.doc["status"] == "DONE" and r.doc["status_line"] == "status=DONE" and r.doc["harness"] == "run-aw-setup.sh"
    assert r.doc["host_mode"] == "c7g-metal" and r.doc["budget_short"] is False
    assert [s["name"] for s in r.doc["steps"]] == SETUP_STEPS and r.doc["not_run"] == []
    assert all(s["outcome"] == "ok" and s["rc"] == 0 for s in r.doc["steps"]), r.doc["steps"]
    assert sorted(os.listdir(str(r.rig.out))) == ["inputs.txt", "setup.json"], "2.11's two files, no temporary one"
    assert r.log.index("step 6/6 close: end") < r.log.index("status=DONE")
    assert r.doc["image"] == {"ref": _ref(), "id": _digest()}
    assert r.facts("preflight", "ifs_bin") == "ifs-ctl.bin", "the session's METAL_IFS, by its name"


def test_setup_steps_run_in_order_each_under_its_cap(setup_done):
    r = setup_done
    caps = [c[2] for c in r.calls if c[0] == "timeout" and "_step " in c[2]]
    assert [c.split("_step ")[1] for c in caps] == SETUP_STEPS, caps
    assert all(c.startswith("--kill-after=30s ") for c in caps), caps
    sweep = r.idx_all("docker", r"^ps -aq --filter label=sdv\.aw\.run$")
    assert len(sweep) == 2, "the preflight's listing and the sweep's"
    order = [sweep[0], r.idx("ip"), r.idx("docker", r"^pull "), r.idx("docker", r"^image inspect "),
             r.idx("docker", r"^info "), r.idx("docker", r"^run .*--name aw-smoke"), sweep[1]]
    assert -1 not in order and order == sorted(order), order
    assert r.idx_all("ip")[-1] > sweep[1], "the host check after the sweep"


def test_setup_pulls_by_the_arm64_digest_never_by_a_tag(setup_done):
    pulls = [a for a in setup_done.docker if a[0] == "pull"]
    assert pulls == [["pull", _ref()]], pulls
    assert ":universe" not in _ref() and "@sha256:" in _ref()
    assert _digest() == "sha256:596bf8a41a7957b8e57af02adf410d3ce65782f3f7afaa6ba3f8bef2db7e7919", "W4 S1's arm64 manifest"


def test_setup_records_what_it_read_back_and_the_pulls_whole_seconds(setup_done):
    p = setup_done.facts("pull")
    assert p["ref"] == _ref() and p["pull_exit"] == 0
    assert p["repo_digests"] == [_ref()] and p["in_repo_digests"] is True
    assert p["image_id"] == _digest() and p["id_is_digest"] is True and p["architecture"] == "arm64"
    assert p["store"] == "io.containerd.snapshotter.v1"
    assert p["operational_s"] == {"pull": 0}, "the pull's wall time, whole seconds of the stub clock"
    out = json.dumps(setup_done.doc)
    assert "RAW-INSPECT-SENTINEL" not in out and "RAW-DOCKER-INFO-SENTINEL" not in out, "never the raw inspect or info"


def test_setup_smoke_runs_ros2_help_under_2_12_and_records_its_exit_and_stderr(setup_done):
    runs = setup_done.runs("aw-smoke")
    assert len(runs) == 1, setup_done.runs()
    argv = runs[0]
    assert holds_2_12(argv, str(setup_done.rig.repo)) == [], holds_2_12(argv, str(setup_done.rig.repo))
    assert "--rm" in argv and _opt(argv, "--network") == "none" and _opt(argv, "--label") == "sdv.aw.run=aw-setup"
    assert _opt(argv, "--group-add") == str(os.getgid()), "how aw writes to the 0775 log directory: the login's gid, not 0777"
    assert _image_and_cmd(argv)[1] == ["ros2", "--help"]
    s = setup_done.facts("smoke")
    assert s["exit"] == 0 and s["sigill"] is False and s["pass"] is True and s["stderr"] == []


def _mode(p):
    return os.stat(str(p)).st_mode & 0o777


def test_setup_makes_the_smoke_log_directory_0775_and_never_0777(setup_done):
    """2.12: the directory aw writes its ROS logs in is made writable for aw through --group-add <the login's gid> (the
    smoke's docker run), at mode 0775, never by chmod 777."""
    d = setup_done.rig.vss_home / "aw-setup-work" / "smoke-ros-log"
    assert d.is_dir() and _mode(d) == 0o775, oct(_mode(d))


def test_setup_meminfo_before_and_after_and_the_budget(setup_done):
    f = setup_done.facts
    assert f("preflight", "mem_available_kb") == 29000000 and f("budget", "mem_available_kb") == 29000000
    assert f("budget", "budget_short") is False and f("budget", "operational_s") == {"left_to_stop_at": 180 * 60 - 1500}


def test_setup_checks_the_inputs_and_writes_inputs_txt(setup_done):
    i = setup_done.facts("preflight", "inputs")
    assert i["commit"] == COMMIT and i["repo_commit"] == COMMIT and i["files_ok"] is True
    assert sorted(i["files"]) == ["aw-map.tar", "aw-scan.json"]
    txt = (setup_done.rig.out / "inputs.txt").read_text(encoding="utf-8")
    for n in ("aw-inputs.json", "aw-scan.json", "aw-map.tar"):
        assert re.search(r"^%s [0-9a-f]{64} ok$" % re.escape(n), txt, re.M), (n, txt)
    assert "commit %s" % COMMIT in txt and "image %s" % _ref() in txt


def test_setup_records_the_scans_verdict_and_does_not_require_a_pass(setup_done):
    """2026-10-24: after the arm64 image's A72 scan the owner took a1.metal off the hosts. Its verdict is recorded, not
    required; its digest must be the one pulled."""
    s = setup_done.facts("preflight", "scan")
    assert s == {"image_digest": _digest(), "digest_matches": True, "verdict": "fail", "findings": 1, "elf_files": 3,
                 "exceptions_applied": 0}, s


def test_setup_stages_the_map_by_the_scenarios_sha256(setup_done):
    d = setup_done.rig.vss_home / "aw" / "map" / "sample-map-planning"
    assert sorted(os.listdir(str(d))) == sorted(MAP_FILES)
    assert all((d / n).read_bytes() == b for n, b in MAP_FILES.items())
    st = setup_done.facts("stage")
    assert st["map"] == "sample-map-planning" and st["files_ok"] is True


def test_setup_host_check_goes_into_the_stems_host_before_and_after(setup_done):
    stem = setup_done.rig.stem
    before = (stem / "host-before.txt").read_text(encoding="utf-8")
    after = (stem / "host-after.txt").read_text(encoding="utf-8")
    assert before.startswith("== a stand-in host-before (the harness phase's)\n"), "appended, the harness phase's kept"
    for text in (before, after):
        assert "format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=212992\nnet.ipv4.ipfrag_time=30\n" \
               "net.ipv4.ipfrag_high_thresh=4194304\n" in text, text
    hc = setup_done.facts("host_check")
    assert hc["before_read"] is True and hc["after_read"] is True and hc["changed"] == [] and hc["same"] is True


def test_setup_runs_docker_through_the_docker_group_and_every_container_is_swept(setup_done):
    assert all(v == "0" for n, v, _a in setup_done.calls if n == "docker"), "the docker group, never sudo"
    assert not list((setup_done.rig.stub / "state" / "docker").glob("*.json")), "no container left"
    s = setup_done.facts("stop")
    assert s["verified"] is True and s["containers_left"] == 0


def test_setup_json_strings_are_one_line_and_nothing_is_written_outside_out_status_and_vss_home(setup_done):
    for s in _strings(setup_done.doc):
        assert "\n" not in s and "\r" not in s, s
    changed = {p for p in set(setup_done.after) | set(setup_done.before)
               if setup_done.before.get(p) != setup_done.after.get(p)}
    allowed = ("w/rec/aw-setup/raw/", "w/rec/aw-setup/status", "w/rec/aw-setup/run.log", "w/rec/aw-setup/host-before.txt",
               "w/rec/aw-setup/host-after.txt", "w/sdv/", "stub/")
    assert [p for p in changed if not p.startswith(allowed)] == [], sorted(changed)


# --- run-aw-setup.sh: refusals, stops, the host check -------------------------------------------------------------

def _no_container(res):
    assert not [a for a in res.docker if a and a[0] in ("pull", "run")], "nothing pulled or started"


def _aw_repo(rig, how):
    """The rig's images.json with autoware.repo = HOW(its repo, its autoware entry), the rest (the arm64 digest) kept."""
    p = rig.repo / "sdv" / "stack" / "images.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["autoware"]["repo"] = how(doc["autoware"]["repo"], doc["autoware"])
    _write(p, json.dumps(doc, indent=2) + "\n")


@pytest.mark.parametrize("change,cfg,msg", [
    (lambda r: r.set_vss_setup(done=False), {}, "rec/vss-setup has no done"),
    (lambda r: r.set_vss_setup(last="status=TIMEOUT at=probes reason=deadline"), {},
     "run-vss-setup.sh's last status line is 'status=TIMEOUT at=probes reason=deadline', not status=DONE"),
    (lambda r: r.set_vss_setup(host_mode="a1-metal"), {}, "records host mode a1-metal"),
    (lambda r: r.set_vss_setup(host_mode=None), {}, "records host mode a1-metal"),
    (lambda r: r.set_vss_setup(status="FAILED"), {}, "says status 'FAILED', not DONE"),
    (None, {"STUB_GROUPS": "ubuntu adm kvm"}, "this login is not in the docker group"),
    (lambda r: os.remove(str(r.aw_in / "aw-inputs.json")), {}, "aw-inputs.json"),
    (lambda r: (r.aw_in / "aw-map.tar").write_bytes(b"another map"), {}, "aw-map.tar"),
    (lambda r: r.aw_inputs(wrong_listed=("aw-map.tar",)), {}, "aw-in/aw-map.tar hashes to"),
    (lambda r: os.remove(str(r.aw_in / "aw-scan.json")), {}, "aw-scan.json"),
    (lambda r: r.aw_inputs(listed={"aw-map.tar": "0" * 64}), {}, "does not list aw-scan.json, which this harness reads"),
    (lambda r: r.aw_inputs(files_env=lambda e: {k: v for k, v in e.items() if k != "aw-map.tar"}), {},
     "aw-map.tar is not in inputs.env's FILES"),
    (lambda r: r.aw_inputs(files_env=lambda e: dict(e, **{"aw-scan.json": "f" * 64})), {}, "aw-scan.json"),
    (lambda r: r.aw_inputs(files_env=lambda e: dict(e, **{"aw-inputs.json": "f" * 64})), {},
     "aw-inputs.json is " + "f" * 64),
    (lambda r: (r.aw_in / "aw-extra.bin").write_bytes(b"x"), {}, "aw-extra.bin"),
    (lambda r: r.aw_inputs(commit="f" * 40), {}, "is not the repo tarball's"),
    (lambda r: _repo_tar(r.w / "repo.tar", None), {}, "the repo tarball carries no commit"),
    (lambda r: r.aw_inputs(scan={"format": 1, "image_digest": "sha256:" + "1" * 64, "elf_files": 1, "findings": [],
                                 "exceptions_applied": [], "verdict": "pass"}), {}, "is not the digest to pull"),
    (lambda r: r.aw_inputs(scan="not json"), {}, "aw-scan.json"),
    (lambda r: os.remove(str(r.repo / "sdv" / "aw" / "hostcheck.sh")), {}, "the repo tarball lacks sdv/aw/hostcheck.sh"),
    (None, {"STUB_SYSCTL_FAIL": "1"}, "the host check cannot be read"),
    (lambda r: _write(r.deadline, "soon"), {}, "no readable deadline file"),
    (lambda r: os.chmod(str(r.repo / "sdv" / "aw" / "aw-entrypoint.sh"), 0o644), {},
     "sdv/aw/aw-entrypoint.sh is not executable"),
    (lambda r: _write(r.repo / "sdv" / "aw" / "ros-env.json", json.dumps({"format": 2})), {}, "ros-env.json is not"),
    (lambda r: os.remove(str(r.repo / "sdv" / "ctl" / "scenarios" / "sample-lanelet-102.json")), {},
     "the repo tarball lacks sdv/ctl/scenarios/sample-lanelet-102.json"),
    (lambda r: _write(r.repo / "sdv" / "stack" / "images.json", "{}"), {}, "images.json names no autoware.repo"),
    # 9.2's pull never by a tag: pull_ref takes autoware.repo only by aw_setup.py's REPOSITORY (no ':', no upper case)
    pytest.param(lambda r: _aw_repo(r, lambda repo, aw: "%s:%s" % (repo, aw["tag"])), {}, "is not a repository", id="REPO-TAG"),
    pytest.param(lambda r: _aw_repo(r, lambda repo, aw: repo.upper()), {}, "is not a repository", id="REPO-UPPER"),
    pytest.param(lambda r: _aw_repo(r, lambda repo, aw: "localhost:5000/" + repo), {}, "is not a repository", id="REPO-PORT"),
])
def test_setup_preflight_refuses(tmp_path, change, cfg, msg):
    rig = Rig(tmp_path)
    if change is not None:
        change(rig)
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert msg in r.log, (msg, r.log[-3000:])
    _no_container(r)
    assert r.doc is not None and r.doc["status"] == "FAILED" and r.doc["at"] == "preflight"


@pytest.mark.parametrize("mode", [None, "", "a1-metal", "orin", "c7g.metal", "C7G-METAL"])
def test_setup_takes_vss_host_c7g_metal_only(tmp_path, mode):
    """The owner, 2026-10-24: the Autoware image runs on c7g.metal and the Orin only; the Orin's days are WP8's helper's."""
    r = Rig(tmp_path).run(VSS_HOST=mode)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "is not c7g-metal" in r.log, r.log[-2000:]
    _no_container(r)


@pytest.mark.parametrize("what", ["release", "compatible"])
def test_setup_refuses_a_host_l4t_or_an_nvidia_device_tree_marks_as_a_jetson(tmp_path, what):
    rig = Rig(tmp_path)
    if what == "release":
        _write(rig.base / "nv_tegra_release", "# R39 (release), REVISION: 2.1\n")
    else:
        (rig.base / "dt-compatible").write_bytes(b"nvidia,p3768-0000+p3767-0005\0nvidia,tegra234\0")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"] and "marks as a Jetson" in r.log, r.why()


@pytest.mark.parametrize("ifs,shown", [("ifs-vss.bin", "ifs-vss.bin"), ("ifs-ctl-p5.bin", "ifs-ctl-p5.bin"),
                                       ("ifs-ctl.bin.old", "ifs-ctl.bin.old"), ("ifs ctl.bin", "ifs?ctl.bin"),
                                       (None, "<unset>")])
def test_setup_refuses_an_ifs_bin_other_than_ifs_ctl_bin_first_before_any_effect(tmp_path, ifs, shown):
    """The suite boots WP5's ifs-ctl.bin alone and its preflight refuses any other image, so a setup that took another
    would spend the session's one run-aw-setup.sh and its pull on a suite that cannot run (critic#9, the orchestrator's
    call of 2026-10-27: the refusal is setup's preflight's). It comes first, in the suite's words: no docker call, no host
    check, no inputs.txt, no map, and the stem's host-before.txt as the harness phase left it."""
    rig = Rig(tmp_path)
    r = rig.run(IFS_BIN=None if ifs is None else str(rig.w / "img" / ifs))
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    words = "not ifs-ctl.bin: the suite's guest is WP5's image, which serves kind 2 on :7150"
    with open(SUITE, encoding="utf-8") as f:
        assert words in f.read(), "the suite's own refusal"
    assert "IFS_BIN is %s, %s" % (shown, words) in r.log, r.log[-2000:]
    assert r.docker == [] and r.idx("ip") == r.idx("sysctl") == -1, "no docker call and no host check: nothing read or started"
    assert sorted(os.listdir(str(rig.out))) == ["setup.json"], "no inputs.txt"
    assert not (rig.vss_home / "aw" / "map").exists()
    assert (rig.stem / "host-before.txt").read_text(encoding="utf-8") == "== a stand-in host-before (the harness phase's)\n"
    assert r.doc["at"] == "preflight" and r.facts("preflight", "ifs_bin") == shown
    assert r.doc["not_run"] == SETUP_STEPS[1:]


def test_setup_refuses_a_leftover_aw_container_before_anything_starts(tmp_path):
    rig = Rig(tmp_path)
    _write(rig.stub / "state" / "docker" / "aw-sim.json", json.dumps(
        {"name": "aw-sim", "labels": {"sdv.aw.run": "aw-suite"}, "running": True, "exit": 0, "mounts": {}, "log": ""}))
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "a container labelled sdv.aw.run is still there" in r.log
    # the reason whole, both of its strings (the r2 fix stage: die_step had kept only the first)
    why = "a container labelled sdv.aw.run is still there (an earlier aw run's: aw-sim ): this harness's names would collide"
    assert r.doc["reason"] == why and "FAILED in preflight: %s" % why in r.log, (r.doc["reason"], r.log[-2000:])
    _no_container(r)


def test_setup_a_map_that_is_not_the_scenarios_fails_at_stage(tmp_path):
    rig = Rig(tmp_path)
    rig.aw_inputs(map_files=dict(MAP_FILES, **{"map_config.yaml": b"another: 2\n"}))
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert "map_config.yaml" in r.log
    _no_container(r)


def test_setup_a_map_tar_with_a_link_or_a_path_outside_its_map_is_refused(tmp_path):
    rig = Rig(tmp_path)
    link = tarfile.TarInfo("sample-map-planning/evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    _map_tar(rig.aw_in / "aw-map.tar", extra=[link])
    sha = _sha((rig.aw_in / "aw-map.tar").read_bytes())          # the hashes below follow the tar as it now is
    doc = json.loads((rig.aw_in / "aw-inputs.json").read_text(encoding="utf-8"))
    doc["files"]["aw-map.tar"] = sha
    _write(rig.aw_in / "aw-inputs.json", json.dumps(doc, indent=1))
    env = (rig.w / "inputs.env").read_text(encoding="utf-8")
    env = re.sub(r"aw-map\.tar:[0-9a-f]{64}", "aw-map.tar:" + sha, env)
    env = re.sub(r"aw-inputs\.json:[0-9a-f]{64}", "aw-inputs.json:" + _sha((rig.aw_in / "aw-inputs.json").read_bytes()), env)
    _write(rig.w / "inputs.env", env)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert "aw-map.tar holds sample-map-planning/evil, which is not a regular file" in r.log, r.log[-2000:]
    assert not (rig.vss_home / "aw" / "map" / "sample-map-planning").exists(), "nothing written"


def test_setup_a_map_tar_whose_scenario_file_is_a_link_is_refused_as_one(tmp_path):
    rig = Rig(tmp_path)
    files = {n: b for n, b in MAP_FILES.items() if n != "map_config.yaml"}
    link = tarfile.TarInfo("sample-map-planning/map_config.yaml")
    link.type, link.linkname = tarfile.SYMTYPE, "../../../etc/hostname"
    _map_tar(rig.aw_in / "aw-map.tar", files=files, extra=[link])
    sha = _sha((rig.aw_in / "aw-map.tar").read_bytes())
    doc = json.loads((rig.aw_in / "aw-inputs.json").read_text(encoding="utf-8"))
    doc["files"]["aw-map.tar"] = sha
    _write(rig.aw_in / "aw-inputs.json", json.dumps(doc, indent=1))
    env = (rig.w / "inputs.env").read_text(encoding="utf-8")
    env = re.sub(r"aw-map\.tar:[0-9a-f]{64}", "aw-map.tar:" + sha, env)
    env = re.sub(r"aw-inputs\.json:[0-9a-f]{64}", "aw-inputs.json:" + _sha((rig.aw_in / "aw-inputs.json").read_bytes()), env)
    _write(rig.w / "inputs.env", env)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert "aw-map.tar holds sample-map-planning/map_config.yaml, which is not a regular file" in r.log, r.log[-2000:]
    assert not (rig.vss_home / "aw" / "map" / "sample-map-planning").exists()


def test_setup_a_map_tar_member_below_a_scenario_file_is_refused_though_its_bytes_are_the_files(tmp_path):
    """A member `sample-map-planning/lanelet2_map.osm/x` is one level too deep, whatever bytes it carries: it is not
    `sample-map-planning/<file>`, so nothing is staged (the hashes below follow the tar as it is)."""
    rig = Rig(tmp_path)
    files = {n: b for n, b in MAP_FILES.items() if n != "lanelet2_map.osm"}
    files["lanelet2_map.osm/x"] = MAP_FILES["lanelet2_map.osm"]
    rig.aw_inputs(map_files=files)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert "aw-map.tar holds sample-map-planning/lanelet2_map.osm/x, which is not sample-map-planning/<file>" in r.log, \
        r.log[-2000:]
    assert not (rig.vss_home / "aw" / "map" / "sample-map-planning").exists(), "nothing written"
    _no_container(r)


def test_setup_a_map_already_staged_is_refused_with_its_reason_and_left_as_it_is(tmp_path):
    rig = Rig(tmp_path)
    staged = rig.vss_home / "aw" / "map" / "sample-map-planning"
    _write(staged / "earlier.txt", "an earlier staging's file\n")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert "VSS_HOME/aw/map/sample-map-planning exists already" in r.log, r.log[-2000:]
    assert os.listdir(str(staged)) == ["earlier.txt"], "nothing written into it"
    _no_container(r)


@pytest.mark.parametrize("cfg,why", [
    ({"STUB_PULL_RC": "1"}, "docker pull"),
    ({"STUB_REPO_DIGESTS": "ghcr.io/autowarefoundation/autoware@sha256:" + "9" * 64}, "RepoDigests"),
])
def test_setup_a_pull_that_fails_or_reads_back_another_digest_fails_at_pull_and_still_sweeps(tmp_path, cfg, why):
    r = Rig(tmp_path).run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=pull"], r.why()
    assert why in r.log and r.doc["not_run"] == ["smoke", "budget", "close"]
    assert r.idx_all("docker", r"^ps -aq --filter label=sdv.aw.run")[-1] > r.idx("docker", r"^pull "), "the sweep ran"
    assert r.facts("host_check", "after_read") is True


@pytest.mark.parametrize("rc,err", [(132, ""), (1, "ros2: error: the stub's failure")])
def test_setup_a_smoke_that_does_not_pass_fails_at_smoke_with_its_exit_and_stderr(tmp_path, rc, err):
    r = Rig(tmp_path).run(STUB_SMOKE_RC=str(rc), STUB_SMOKE_ERR=err)
    assert r.rc == 1 and r.status == ["status=FAILED at=smoke"], r.why()
    s = r.facts("smoke")
    assert s["exit"] == rc and s["pass"] is False and s["sigill"] is (rc == 132)
    assert s["stderr"] == ([err] if err else []) + (["Illegal instruction (core dumped)"] if rc == 132 else [])
    assert r.doc["not_run"] == ["budget", "close"]
    assert r.doc["reason"] == "ros2 --help exited %d in the image under the project entrypoint%s: the image does not start " \
        "on this host (its stderr is in setup.json)" % (rc, " (SIGILL)" if rc == 132 else ""), r.doc["reason"]


def test_setup_sets_budget_short_when_under_30_minutes_are_left_after_the_pull(tmp_path):
    """D7's rule: setup ends DONE with budget_short true, and the suite refuses it."""
    rig = Rig(tmp_path)
    rig.ahead(1500 + 29 * 60)
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.doc["budget_short"] is True and r.facts("budget", "budget_short") is True
    assert "budget_short" in r.log


def test_setup_with_30_minutes_left_is_not_short(tmp_path):
    rig = Rig(tmp_path)
    rig.ahead(1500 + 30 * 60)
    r = rig.run()
    assert r.rc == 0 and r.doc["budget_short"] is False, r.why()


def test_setup_stops_cleanly_at_a_check_point_past_stop_at(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run(STUB_JUMP_RE="step 2/6 stage: end", STUB_JUMP_S=str(180 * 60))
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=pull reason=deadline"], r.why()
    assert r.doc["not_run"] == ["pull", "smoke", "budget", "close"]
    assert not [a for a in r.docker if a[0] == "pull"]
    assert r.facts("host_check", "after_read") is True and r.idx("sync") >= 0


def test_setup_a_cap_that_fires_is_a_step_timeout_and_the_sweep_runs(tmp_path):
    r = Rig(tmp_path).run(STUB_CAP_RE="_step pull", STUB_SLEEP_ON="^docker pull ", STUB_SLEEP_S="5")
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=pull reason=step-timeout"], r.why()
    assert r.idx_all("docker", r"^ps -aq --filter label=sdv.aw.run")[-1] > r.idx("docker", r"^pull ")


@pytest.mark.parametrize("cfg,setting", [({"STUB_RMEM_AFTER": "2147483647"}, "net.core.rmem_max"),
                                         ({"STUB_LO_MULTICAST_AFTER": "1"}, "lo.flags")])
def test_setup_a_host_setting_that_changes_during_the_stem_ends_it_failed_at_host_check(tmp_path, cfg, setting):
    r = Rig(tmp_path).run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=host-check"], r.why()
    assert "changed %s before=" % setting in r.log
    hc = r.facts("host_check")
    assert hc["same"] is False and [ln.split()[1] for ln in hc["changed"]] == [setting]
    assert hc["outcome_before_host_check"] == "status=DONE"
    after = (r.rig.stem / "host-after.txt").read_text(encoding="utf-8")
    assert re.search(r"^%s=" % re.escape(setting), after, re.M) and "changed %s before=" % setting in after, after


def test_setup_a_host_check_after_that_cannot_be_read_ends_failed_at_host_check(tmp_path):
    r = Rig(tmp_path).run(STUB_SYSCTL_FAIL_AFTER="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=host-check"], r.why()
    hc = r.facts("host_check")
    assert hc["before_read"] is True and hc["after_read"] is False and hc["same"] is False
    assert "the host check after the sweep cannot be read" in r.log


def test_setup_a_sweep_that_cannot_list_containers_removes_them_by_name_and_records_the_stop_unverified(tmp_path):
    r = Rig(tmp_path).run(STUB_DOCKER_PS_FAIL_AFTER="1")
    assert r.rc == 0 and r.status == ["status=DONE"], "the status line is not changed: " + r.why()
    s = r.facts("stop")
    assert s["verified"] is False and s["containers_list_exit"] != 0 and s["unverified"]
    assert "the stop is unverified" in r.log
    assert r.idx_all("docker", r"^rm -f aw-sim aw-claim-node aw-scenario ros-vss-feeder aw-smoke$"), "removed by name"


# --- run-aw-suite.sh: the plans ------------------------------------------------------------------------------------

PLANS = {
    "a1": ["01-psim"],
    "a2": ["01-honest", "02-inject"],
    "b1": ["01-honest", "02-inject"],
    "b2": ["01-kill", "02-inject", "03-demo"],
    "s": ["01-sizing"],
}


def _suite_tool(*args):
    return subprocess.run([sys.executable, "-B", SUITE_TOOL] + list(args), capture_output=True, text=True, timeout=60)


def _plan_rows(plan):
    p = _suite_tool("plan", "--plan", plan)
    assert p.returncode == 0, p.stderr
    return [ln.split("\t") for ln in p.stdout.splitlines()]


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_each_plan_lists_its_units_in_order(plan):
    rows = _plan_rows(plan)
    assert [r[1] for r in rows] == PLANS[plan] and [r[0] for r in rows] == ["%02d" % (i + 1) for i in range(len(rows))]


def test_another_plan_is_refused():
    p = _suite_tool("plan", "--plan", "v2")
    assert p.returncode == 1 and "a1, a2, b1, b2 or s" in p.stderr


def _injections():
    sys.path.insert(0, SDV_CTL)
    try:
        import ctlclient
        return tuple(ctlclient.INJECTIONS)
    finally:
        sys.path.remove(SDV_CTL)


def test_the_inject_units_inject_wp2s_whole_list_each_at_its_own_fixed_seq():
    for plan in ("a2", "b1", "b2"):
        row = [r for r in _plan_rows(plan) if r[1] == "02-inject"][0]
        words = row[6].split()
        got = [w for w in words if ":" in w and words[words.index(w) - 1] == "--inject"]
        assert [w.split(":")[1] for w in got] == list(_injections()), got
        seqs = [int(w.split(":")[0]) for w in got]
        assert seqs == sorted(set(seqs)) and seqs[0] >= 2, seqs
        assert words.count("--inject") == len(_injections())


def test_the_demo_unit_sends_profile_2_inside_its_window_and_no_other_unit_does():
    for plan in PLANS:
        for row in _plan_rows(plan):
            assert ("--demo" in row[6].split()) is (row[1] == "03-demo"), row
    demo = [r for r in _plan_rows("b2") if r[1] == "03-demo"][0][6].split()
    start, dur = (int(x) for x in demo[demo.index("--demo") + 1].split(":"))
    assert start >= 0 and 0 < dur <= 30000, "within profile 2's run_window_max_ms"


def test_the_plans_flags_name_their_claim_node_kill_record_and_sampler():
    flags = {(plan, r[1]): tuple(r[2:6]) for plan in PLANS for r in _plan_rows(plan)}
    assert flags[("a1", "01-psim")] == ("0", "0", "0", "0"), "a1: one planning-sim run, no claim node"
    assert all(v[0] == "1" for k, v in flags.items() if k != ("a1", "01-psim")), "every other unit has the claim node"
    assert [k for k, v in flags.items() if v[1] == "1"] == [("b2", "01-kill")]
    assert [k for k, v in flags.items() if v[2] == "1"] == [("b1", "01-honest")]
    assert [k for k, v in flags.items() if v[3] == "1"] == [("s", "01-sizing")]


# --- run-aw-suite.sh: whole runs -----------------------------------------------------------------------------------

def _suite(base, plan, **cfg):
    rig = Rig(base, stem="aw-suite", plan=plan)
    before = _snapshot(rig.base)
    res = rig.run(**dict({"STUB_IMAGE_PRESENT": "1"}, **cfg))
    res.before, res.after = before, _snapshot(rig.base)
    return res


@pytest.fixture(scope="module")
def suite_runs(tmp_path_factory):
    """One whole run of each plan with every stub answering as the instance should."""
    return {p: _suite(tmp_path_factory.mktemp("aw-suite-" + p), p) for p in sorted(PLANS)}


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_a_whole_suite_run_ends_done_with_suite_json_first(suite_runs, plan):
    r = suite_runs[plan]
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    doc = r.doc
    assert doc["harness"] == "run-aw-suite.sh" and doc["host_mode"] == "c7g-metal" and doc["plan"] == plan
    assert doc["status"] == "DONE" and doc["not_run"] == [] and doc["guest_host"] == GUEST
    assert [u["name"] for u in doc["units"]] == PLANS[plan]
    assert all(u["state"] == "ran" for u in doc["units"]), doc["units"]
    assert sorted(os.listdir(str(r.rig.out))) == sorted(["suite.json", "00-guest"] + PLANS[plan])
    assert r.log.index("unit %s: end" % PLANS[plan][-1]) < r.log.index("status=DONE")


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_every_docker_run_of_the_autoware_image_holds_2_12(suite_runs, plan):
    r = suite_runs[plan]
    assert r.runs(), "containers ran"
    for argv in r.runs():
        assert holds_2_12(argv, str(r.rig.repo)) == [], (argv, holds_2_12(argv, str(r.rig.repo)))
        assert _opt(argv, "--name") in CONTAINERS and _opt(argv, "--label") == "sdv.aw.run=aw-suite"
        assert _opt(argv, "--group-add") == str(os.getgid()), "how aw writes to the 0775 directories: the login's gid"
        assert _opt(argv, "--network") == "host", "2.7's single-host form needs --network host"
        assert "%s:/sdv-ros-log" % (r.rig.vss_home / "aw-suite-work" / "units" / _unit_of(r, argv) / "ros-log") in \
            _opts(argv, "-v") and "ROS_LOG_DIR=/sdv-ros-log" in _opts(argv, "-e"), "ROS_LOG_DIR under the unit's work"
        assert "ROS_DOMAIN_ID=73" in _opts(argv, "-e") and "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in _opts(argv, "-e")
    for argv in [a for a in r.docker if a and a[0] == "exec"]:
        assert "--privileged" not in argv and "-u" not in argv and "--user" not in argv, argv
    xml = (r.rig.vss_home / "aw-suite-work" / "dds" / "cyclonedds.xml").read_text(encoding="utf-8")
    with open(os.path.join(SDV_AW, "ros-env.json"), encoding="utf-8") as f:
        assert xml == json.load(f)["cyclonedds_single_host"], "2.7's XML as it is"


def _unit_of(res, argv):
    for v in _opts(argv, "-v"):
        m = re.search(r"/aw-suite-work/units/([^/]+)/", v)
        if m:
            return m.group(1)
    raise AssertionError("no unit mount in %s" % argv)


def test_the_suites_work_directories_are_made_0775_and_never_0777(suite_runs):
    """2.12: every directory aw writes in (the unit's own, its ROS logs, the claim node's and the driver's outputs, the
    recording unit's bag) is made writable for aw through --group-add <the login's gid>, at mode 0775, never by chmod 777."""
    for plan in ("a2", "b1"):
        r = suite_runs[plan]
        for unit in PLANS[plan]:
            u = r.rig.vss_home / "aw-suite-work" / "units" / unit
            dirs = [u, u / "ros-log", u / "claim", u / "scn"] + ([u / "bag"] if (plan, unit) == ("b1", "01-honest") else [])
            for d in dirs:
                assert d.is_dir() and _mode(d) == 0o775, (str(d), oct(_mode(d)))


def test_each_unit_starts_the_sim_then_the_claim_node_then_the_driver(suite_runs):
    """W4 G2: no Control flows before a route, so the claim node starts before the driver sets one, and the driver is
    told to require it."""
    r = suite_runs["a2"]
    for unit in ("01-honest", "02-inject"):
        names = [_opt(a, "--name") for a in r.runs() if _unit_of(r, a) == unit]
        assert names == ["aw-sim", "aw-claim-node", "aw-scenario"], names
        drv = [a for a in r.runs("aw-scenario") if _unit_of(r, a) == unit][0]
        assert "--require-claim-node" in _image_and_cmd(drv)[1]
    sim = r.idx("docker", r"^run .*--name aw-sim")
    ready = r.idx("docker", r"^exec aw-sim /sdv-aw/aw-entrypoint\.sh ros2 service list$")
    claim = r.idx("docker", r"^run .*--name aw-claim-node")
    drv = r.idx("docker", r"^run .*--name aw-scenario")
    stop_claim = r.idx("docker", r"^stop -t \d+ aw-claim-node$")
    stop_sim = r.idx("docker", r"^stop -t \d+ aw-sim$")
    assert -1 < sim < ready < claim < drv < stop_claim < stop_sim, (sim, ready, claim, drv, stop_claim, stop_sim)


def test_a1_runs_the_planning_sim_and_the_driver_with_no_claim_node(suite_runs):
    r = suite_runs["a1"]
    assert [_opt(a, "--name") for a in r.runs()] == ["aw-sim", "aw-scenario"]
    assert "--require-claim-node" not in _image_and_cmd(r.runs("aw-scenario")[0])[1]
    u = json.loads((r.rig.out / "01-psim" / "unit.json").read_text(encoding="utf-8"))
    assert u["claim_node"] is False and u["state"] == "ran" and u["scenario_exit"] == 0
    assert sorted(os.listdir(str(r.rig.out / "01-psim"))) == ["guest-console.log", "scenario.jsonl", "unit.json"]


def test_the_planning_sim_and_the_driver_get_the_staged_map_and_the_tarballs_scenario(suite_runs):
    r = suite_runs["a2"]
    sim = r.runs("aw-sim")[0]
    assert "%s:/sdv-map:ro" % (r.rig.vss_home / "aw" / "map") in _opts(sim, "-v")
    assert _image_and_cmd(sim)[1] == ["ros2", "launch", "autoware_launch", "planning_simulator.launch.xml",
                                      "map_path:=/sdv-map/sample-map-planning", "vehicle_model:=sample_vehicle",
                                      "sensor_model:=sample_sensor_kit", "rviz:=false"]
    drv = r.runs("aw-scenario")[0]
    assert "%s/sdv/ctl:/sdv/sdv/ctl:ro" % r.rig.repo in _opts(drv, "-v")
    assert _image_and_cmd(drv)[1][:8] == ["python3", "/sdv/sdv/ctl/aw_scenario.py", "--scenario",
                                          "/sdv/sdv/ctl/scenarios/sample-lanelet-102.json", "--map-dir",
                                          "/sdv-map/sample-map-planning", "--out", "/sdv-scn/run"]


def test_the_claim_node_judges_on_the_guests_7150_by_the_generations_contract(suite_runs):
    r = suite_runs["a2"]
    claim = r.runs("aw-claim-node")[0]
    assert "%s:/sdv-gen:ro" % (r.rig.vss_home / "gen") in _opts(claim, "-v")
    assert "%s/sdv/ctl:/sdv/sdv/ctl:ro" % r.rig.repo in _opts(claim, "-v")
    assert _image_and_cmd(claim)[1] == ["python3", "/sdv/sdv/ctl/ctl_claim_node.py", "--host", GUEST, "--port", "7150",
                                        "--contract", "/sdv-gen/vss_ctl.py", "--out", "/sdv-claim/run"]
    inj = [a for a in r.runs("aw-claim-node") if _unit_of(r, a) == "02-inject"][0]
    assert _image_and_cmd(inj)[1][:10] == _image_and_cmd(claim)[1] and _image_and_cmd(inj)[1].count("--inject") == 14


def test_a2s_units_keep_their_records_as_2_11_names_them(suite_runs):
    r = suite_runs["a2"]
    for unit in ("01-honest", "02-inject"):
        d = r.rig.out / unit
        assert sorted(os.listdir(str(d))) == ["claim-node.log", "guest-console.log", "replies.jsonl", "scenario.jsonl",
                                              "unit.json"], unit
        u = json.loads((d / "unit.json").read_text(encoding="utf-8"))
        assert u["state"] == "ran" and u["claim_node"] is True and u["claim_exit"] == 0 and u["scenario_exit"] == 0
        replies = [json.loads(ln) for ln in (d / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
        assert u["replies"]["summary"]["counters"]["controls"] == len([x for x in replies if "seq" in x]) >= 40
        assert u["replies"]["replied"] == len([x for x in replies if x.get("outcome") == "replied"])
        assert [s["step"] for s in u["scenario"]] == ["map", "localize", "route", "engage", "arrive", "clear"]
        assert "identity=holds" in (d / "claim-node.log").read_text(encoding="utf-8")
        # 2.11's guest console of a unit is the part the unit saw: from the console's size when the unit started (the boot's
        # lines are 00-guest's), to its size when the unit ended
        seen = (d / "guest-console.log").read_bytes()
        assert u["console_from"] == len(_console()) and seen == _console()[u["console_from"]:u["console_to"]], (unit, seen)
        assert b"Startup complete" not in seen, unit
    u = json.loads((r.rig.out / "02-inject" / "unit.json").read_text(encoding="utf-8"))
    assert sorted(int(k) for k in u["replies"]["by_reason"] if k != "0") == [5, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]


def test_the_guest_is_booted_once_smoked_on_7100_and_read_for_its_ctl_rules(suite_runs):
    r = suite_runs["a2"]
    assert len(r.idx_all("launch")) == 1
    assert [c[2] for c in r.calls if c[0] == "latency_probe"] == ["--host %s --port 7100 --n 20 --warmup 0" % GUEST]
    ready = [c[2] for c in r.calls if c[0] == "timeout" and "/dev/tcp/" in c[2]]
    assert ready == ["3 bash -c exec 3<>/dev/tcp/%s/7150 && exec 3>&-" % GUEST], ready
    g = r.doc["guest"]
    assert g["booted"] is True and g["ready_7150"] is True and g["smoke_7100"]["pass"] is True
    assert g["ctl_rules"]["catalog"] == CTL_DIGEST and g["ctl_rules"]["digest_matches"] is True
    assert g["ctl_rules"]["profiles"] == [1, 2]
    u = json.loads((r.rig.out / "00-guest" / "unit.json").read_text(encoding="utf-8"))
    assert u["state"] == "ran"
    assert (r.rig.out / "00-guest" / "guest-console.log").read_bytes() == _console(), "the boot's slice of the console"
    assert not (r.rig.stub / "state" / "qemu").exists(), "QEMU stopped at the end"
    out = json.dumps(r.doc)
    assert "7.754321" not in out and "p50" not in out, "the smoke keeps its exit and counts only"


def test_b2_unloads_the_controller_from_its_container_inside_aw_sim_only_once_the_drive_is_engaged(suite_runs):
    """W4 G4's controller is a composable node in the component container that also holds the gate: no process bears its
    name, and a process kill would end the gate too. The kill unit reads its container and id with `ros2 component list`
    before the route, and unloads it once the driver's log says the engage step is done."""
    r = suite_runs["b2"]
    execs = [a for a in r.docker if a[:2] == ["exec", "aw-sim"]]
    lists = [i for i, a in enumerate(r.docker) if a[:2] == ["exec", "aw-sim"] and a[-3:] == ["ros2", "component", "list"]]
    unloads = [a for a in execs if "unload" in a]
    assert unloads == [["exec", "aw-sim", "/sdv-aw/aw-entrypoint.sh", "ros2", "component", "unload",
                        "/control/control_container", "2"]], unloads
    assert len(lists) == 1 and lists[0] < r.docker.index(r.runs("aw-scenario")[0]), "read before the driver sets the route"
    assert not [a for a in execs if "pkill" in a and "controller_node_exe" in a]
    assert (r.rig.stub / "state" / "killed").read_text() == "after-engage"
    u = json.loads((r.rig.out / "01-kill" / "unit.json").read_text(encoding="utf-8"))
    assert u["killed"] is True and u["kill_exit"] == 0
    assert u["kill_container"] == "/control/control_container" and u["kill_id"] == "2"
    assert all(not [a for a in x.docker if "component" in a] for p, x in suite_runs.items() if p != "b2"), "b2's kill only"
    demo = [a for a in r.runs("aw-claim-node") if _unit_of(r, a) == "03-demo"][0]
    assert "--demo" in _image_and_cmd(demo)[1]


def test_b2_waits_for_the_engage_step_itself_and_not_the_route_before_it(tmp_path):
    """Spec-2 9.2 item 3 (R4: the controller is killed while driving). The stub driver's log holds its route line for 2 s
    before the engage line, the kill's poll runs many times in that gap, and the unload still comes after the engage."""
    r = _suite(tmp_path, "b2", STUB_ENGAGE_HOLD_S="2")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert (r.rig.stub / "state" / "killed").read_text() == "after-engage"
    u = {x["name"]: x for x in r.doc["units"]}["01-kill"]
    assert u["killed"] is True and u["kill_exit"] == 0 and u["scenario_exit"] == 0, u


def test_a_component_list_without_the_controller_is_recorded_and_the_drive_goes_on_unkilled(tmp_path):
    r = _suite(tmp_path, "b2", STUB_NO_CONTROLLER="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = {x["name"]: x for x in r.doc["units"]}["01-kill"]
    assert u["state"] == "ran" and u["killed"] is False and "kill_exit" not in u
    assert "0 node(s) named controller_node_exe" in u["kill_problem"]
    assert not [a for a in r.docker if "unload" in a] and not (r.rig.stub / "state" / "killed").exists()


def test_the_component_reader_takes_exactly_one_node_of_the_name():
    listing = "/a/c1\n  1  /a/x/controller_node_exe\n  2  /a/gate\n/b/c2\n  1  /b/other\n"
    p = subprocess.run([sys.executable, "-B", SUITE_TOOL, "component", "--name", "controller_node_exe"], input=listing,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stdout.strip() == "/a/c1 1", (p.stdout, p.stderr)
    for text in ("/a/c1\n  1  /a/gate\n", listing + "/c/c3\n  4  /c/controller_node_exe\n", "  1  /a/controller_node_exe\n",
                 "/a/c1\n  1  /a/controller_node_exe_2\n"):
        p = subprocess.run([sys.executable, "-B", SUITE_TOOL, "component", "--name", "controller_node_exe"], input=text,
                           capture_output=True, text=True, timeout=60)
        assert p.returncode == 1 and p.stdout == "", (text, p.stdout, p.stderr)


def test_b1_records_its_honest_drive_as_a_bag_outside_the_record_and_keeps_its_export(suite_runs):
    r = suite_runs["b1"]
    rec = [a for a in r.docker if a[:3] == ["exec", "-d", "aw-sim"]]
    assert len(rec) == 1 and rec[0][3:7] == ["/sdv-aw/aw-entrypoint.sh", "ros2", "bag", "record"], rec
    sys.path.insert(0, SDV_CTL)
    try:
        import ctl_export
        topics = list(ctl_export.TOPICS)
    finally:
        sys.path.remove(SDV_CTL)
    assert rec[0][rec[0].index("-o") + 2:] == topics, "ctl_export.py's six topics"
    exp = [a for a in r.docker if a[:2] == ["exec", "aw-sim"] and "/sdv/sdv/ctl/ctl_export.py" in a]
    assert exp and exp[0][2:] == ["/sdv-aw/aw-entrypoint.sh", "python3", "/sdv/sdv/ctl/ctl_export.py", "--bag",
                                  "/sdv-bag/bag", "--out", "/sdv-bag/export.jsonl"]
    d = r.rig.out / "01-honest"
    assert "export.jsonl" in os.listdir(str(d)) and json.loads((d / "export.jsonl").read_text().splitlines()[-1])["summary"]
    for root, dirs, files in os.walk(str(r.rig.out)):
        assert not {"bag", "ros-log", ".ros"} & set(dirs) and "metadata.yaml" not in files and \
            not [f for f in files if f.endswith((".mcap", ".db3"))], (root, dirs, files)
    sim = [a for a in r.runs("aw-sim") if _unit_of(r, a) == "01-honest"][0]
    assert any(v.endswith(":/sdv-bag") for v in _opts(sim, "-v"))
    assert not any(v.endswith(":/sdv-bag") for a in r.runs("aw-sim") if _unit_of(r, a) != "01-honest"
                   for v in _opts(a, "-v"))


def test_s_samples_memavailable_and_docker_stats_at_a_fixed_spacing_by_no_new_login(suite_runs):
    """No login is made in this rig at all, so what stands in for "never by new logins" (spec-2 9.2 item 3) is what the
    harness's own sampler shows: every `docker stats` is made inside the unit's own child (after its cap's call, before
    the unit's sweep) as the harness's own user through the docker group, never under sudo, and the samples it read are
    the unit's, in order."""
    r = suite_runs["s"]
    u = json.loads((r.rig.out / "01-sizing" / "unit.json").read_text(encoding="utf-8"))
    assert u["samples"] and u["sample_spacing_s"] == 5
    s = u["samples"][0]
    assert s["mem_available_kb"] == 29000000 and isinstance(s["t_s"], int)
    start = r.idx("timeout", r"_unit 01 01-sizing$")
    sweep = [i for i in r.idx_all("docker", r"^rm -f aw-sim aw-claim-node aw-scenario$") if i > start]
    stats = r.idx_all("docker", r"^stats --no-stream --format ")
    assert start > -1 and sweep and stats and all(start < i < sweep[0] for i in stats), (start, sweep, stats)
    assert all(r.calls[i][1] == "0" for i in stats), "the harness's own user, never sudo"
    ts = [x["t_s"] for x in u["samples"]]
    assert len(ts) >= 2 and all(isinstance(t, int) for t in ts) and ts == sorted(ts), ts


def test_the_suites_host_check_goes_into_the_stems_host_before_and_after(suite_runs):
    r = suite_runs["a2"]
    before = (r.rig.stem / "host-before.txt").read_text(encoding="utf-8")
    after = (r.rig.stem / "host-after.txt").read_text(encoding="utf-8")
    assert before.startswith("== a stand-in host-before (the harness phase's)\n")
    hc = "format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=212992\nnet.ipv4.ipfrag_time=30\nnet.ipv4.ipfrag_high_thresh=4194304\n"
    assert hc in before and hc in after, (before, after)
    assert r.doc["host_check"] == {"before_read": True, "after_read": True, "changed": [], "compare_exit": 0, "same": True}
    first_run = r.idx("docker", r"^run ")
    assert r.idx("sysctl") < first_run < r.idx_all("sysctl")[-1], "the host check before the first container, after the sweep"
    assert r.idx_all("sysctl")[-1] > r.idx_all("docker", r"^ps -aq")[-1]


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_each_unit_is_swept_on_its_end_and_the_suite_on_its_own(suite_runs, plan):
    r = suite_runs[plan]
    rms = [a for a in r.docker if a[:2] == ["rm", "-f"]]
    assert sum(1 for a in rms if a[2:] == ["aw-sim", "aw-claim-node", "aw-scenario"]) >= len(PLANS[plan]) + 1, rms
    assert not list((r.rig.stub / "state" / "docker").glob("*.json"))
    assert r.doc["stop"]["verified"] is True and r.doc["stop"]["containers_left"] == 0


@pytest.mark.parametrize("plan", sorted(PLANS))
def test_the_suites_record_is_one_line_strings_and_nothing_is_written_outside_its_places(suite_runs, plan):
    r = suite_runs[plan]
    for s in _strings(r.doc):
        assert "\n" not in s, s
    changed = {p for p in set(r.after) | set(r.before) if r.before.get(p) != r.after.get(p)}
    allowed = ("w/rec/aw-suite/raw/", "w/rec/aw-suite/status", "w/rec/aw-suite/run.log", "w/rec/aw-suite/host-before.txt",
               "w/rec/aw-suite/host-after.txt", "w/sdv/aw-suite-work/", "stub/")
    assert [p for p in changed if not p.startswith(allowed)] == [], sorted(changed)


def test_every_file_of_both_records_is_on_captures_whitelist_and_ros_logs_bags_and_dot_ros_are_not(suite_runs, setup_done):
    with open(CAPTURE, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] in (["VSS_WHITELIST"],
                                                                                               ["NEVER_DIRS"],
                                                                                               ["NEVER_FILES"]):
            exec(compile(ast.Module(body=[node], type_ignores=[]), CAPTURE, "exec"), {}, ns)
        if isinstance(node, ast.FunctionDef) and node.name == "vss_excluded":
            exec(compile(ast.Module(body=[node], type_ignores=[]), CAPTURE, "exec"), {"fnmatch": __import__("fnmatch")}, ns)
    excluded = ns["vss_excluded"]
    excluded.__globals__.update(VSS_WHITELIST=ns["VSS_WHITELIST"], NEVER_DIRS=ns["NEVER_DIRS"], NEVER_FILES=ns["NEVER_FILES"])
    for res in list(suite_runs.values()) + [setup_done]:
        stem = res.rig.stem
        for root, _d, files in os.walk(str(stem)):
            for n in files:
                rel = os.path.relpath(os.path.join(root, n), str(stem.parent)).replace(os.sep, "/")
                if n in ("detach.log", "done"):
                    continue
                assert excluded(rel) == "", rel
    for rel in ("aw-suite/raw/01-honest/ros-log/x.log", "aw-suite/raw/01-honest/bag/metadata.yaml",
                "aw-suite/raw/01-honest/.ros/log/x", "aw-suite/raw/01-honest/samples.txt", "aw-suite/raw/scenario.log",
                "aw-setup/raw/smoke.err", "aw-suite/detach.log", "aw-setup/raw/01-x/replies.jsonl"):
        assert excluded(rel) != "", rel


# --- run-aw-suite.sh: refusals, stops ------------------------------------------------------------------------------

@pytest.mark.parametrize("change,cfg,msg", [
    (None, {"PLAN": "v2"}, "PLAN='v2' is not a1, a2, b1, b2 or s"),
    (None, {"PLAN": None}, "PLAN='' is not a1, a2, b1, b2 or s"),
    (None, {"STUB_GROUPS": "ubuntu adm"}, "this login is not in the docker group"),
    (lambda r: r.set_aw_setup(done=False), {}, "rec/aw-setup has no done"),
    (lambda r: r.set_aw_setup(last="status=FAILED at=smoke"), {}, "run-aw-setup.sh's last status line is"),
    (lambda r: r.set_aw_setup(budget_short=True), {}, "budget_short"),
    (lambda r: r.set_aw_setup(host_mode="a1-metal"), {}, "records host mode a1-metal"),
    (lambda r: _write(r.stub / "state" / "qemu", ""), {}, "a QEMU runs already"),
    (lambda r: shutil.move(str(r.w / "img" / "ifs-ctl.bin"), str(r.w / "img" / "ifs-vss.bin")),
     {"IFS_BIN": "IMG_PLACEHOLDER"}, "not ifs-ctl.bin"),
    (lambda r: os.remove(str(r.vss_home / "gen" / "vss_ctl.py")), {}, "vss_ctl.py"),
    (lambda r: _write(r.vss_home / "gen" / "vss_ctl.py", "FORMAT = 1\nDIGEST = 0x12345678\nCOMPILED_PROFILE_IDS = (1,)\n"),
     {}, "profile 2"),
    (lambda r: (r.vss_home / "aw" / "map" / "sample-map-planning" / "map_config.yaml").write_bytes(b"x: 1\n"), {},
     "map_config.yaml"),
    (lambda r: (r.vss_home / "aw" / "map" / "sample-map-planning" / "extra.pcd").write_bytes(b"x"), {},
     "is not one of the scenario's map files"),
    (lambda r: os.remove(str(r.repo / "sdv" / "ctl" / "ctl_claim_node.py")), {}, "sdv/ctl/ctl_claim_node.py"),
    (None, {"STUB_SYSCTL_FAIL": "1"}, "the host check cannot be read"),
    (lambda r: _write(r.stub / "state" / "docker" / "aw-sim.json", json.dumps(
        {"name": "aw-sim", "labels": {"sdv.aw.run": "aw-suite"}, "running": True, "exit": 0, "mounts": {}, "log": ""})), {},
     "a container labelled sdv.aw.run is still there"),
    (lambda r: os.remove(str(r.w / "img" / "disk-qemu")), {}, "IFS_BIN, DISK or the launch script is not readable"),
    (lambda r: os.remove(str(r.g / "launch-qnx-kvm-bridged.sh")), {}, "IFS_BIN, DISK or the launch script is not readable"),
    (lambda r: os.remove(str(r.repo / "sdv" / "ctl" / "aw_scenario.py")), {}, "sdv/ctl/aw_scenario.py"),
    (lambda r: _write(r.w / "rec" / "aw-setup" / "raw" / "setup.json",
                      json.dumps({"status": "DONE", "budget_short": False, "host_mode": "c7g-metal"})), {},
     "names no image pulled by its digest"),
])
def test_suite_preflight_refuses(tmp_path, change, cfg, msg):
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    rig.set_aw_setup()
    if change is not None:
        change(rig)
    cfg = dict(STUB_IMAGE_PRESENT="1", **cfg)
    if cfg.get("IFS_BIN") == "IMG_PLACEHOLDER":
        cfg["IFS_BIN"] = str(rig.w / "img" / "ifs-vss.bin")
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert msg in r.log, (msg, r.log[-3000:])
    assert not r.runs() and not r.idx_all("launch"), "nothing started, no guest booted"


def test_suite_refuses_an_image_that_is_not_in_the_store(tmp_path):
    r = Rig(tmp_path, stem="aw-suite", plan="a1").run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"] and "is not in the image store" in r.log, r.why()


@pytest.mark.parametrize("mode", [None, "a1-metal", "orin"])
def test_suite_takes_vss_host_c7g_metal_only(tmp_path, mode):
    r = Rig(tmp_path, stem="aw-suite", plan="a1").run(VSS_HOST=mode, STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"] and "is not c7g-metal" in r.log, r.why()


@pytest.mark.parametrize("what", ["release", "compatible"])
def test_suite_refuses_a_host_l4t_or_an_nvidia_device_tree_marks_as_a_jetson(tmp_path, what):
    """As run-aw-setup.sh does (the board's days are its own helper's), before any effect: no docker call, no guest."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    if what == "release":
        _write(rig.base / "nv_tegra_release", "# R39 (release), REVISION: 2.1\n")
    else:
        (rig.base / "dt-compatible").write_bytes(b"nvidia,p3768-0000+p3767-0005\0nvidia,tegra234\0")
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"] and "marks as a Jetson" in r.log, r.why()
    assert r.docker == [] and r.idx("launch") == -1, "no docker call, no guest booted"


@pytest.mark.parametrize("cfg,console,msg", [
    ({"STUB_BOOT": "fail"}, None, "the guest did not boot"),
    ({"STUB_READY_NEVER": "1"}, None, ":7150 did not accept"),
    ({}, (RULES_CTL % "0x0BADF00D").encode(), "is not vss_ctl.py's DIGEST"),
    ({}, b"monitor: nothing of kind 2", "no `ctl rules:` line"),
    ({}, (RULES_CTL % CTL_DIGEST).replace("profiles 1 2", "profiles 1").encode(), "profile 2"),
    ({}, (RULES_CTL % CTL_DIGEST).encode() + b"\r\n" + (RULES_CTL % CTL_DIGEST).replace("profiles 1 2", "profiles 1").encode(),
     "disagree"),
    ({"STUB_SMOKE7100_RC": "1"}, None, ":7100's smoke"),
    ({"STUB_SMOKE7100_BAD": "1"}, None, ":7100's smoke"),
    ({"STUB_SMOKE7100_REJ": "1"}, None, ":7100's smoke"),
])
def test_a_guest_that_cannot_judge_the_plan_is_refused_at_preflight_and_stopped(tmp_path, cfg, console, msg):
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    if console is not None:
        (rig.stub / "console.bin").write_bytes(_console(console))
    r = rig.run(STUB_IMAGE_PRESENT="1", **cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert msg in r.log, (msg, r.log[-3000:])
    assert not r.runs() and not (rig.stub / "state" / "qemu").exists(), "no container; QEMU stopped"
    assert (rig.out / "00-guest" / "unit.json").exists()


def test_a_check_point_past_stop_at_stops_the_suite_before_its_next_unit(tmp_path):
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_JUMP_RE="unit 01-honest: end", STUB_JUMP_S=str(180 * 60))
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=02-inject reason=deadline"], r.why()
    assert r.doc["not_run"] == ["02-inject"] and [u["state"] for u in r.doc["units"]] == ["ran", "not-run"]
    assert not [a for a in r.runs() if _unit_of(r, a) == "02-inject"]
    assert r.doc["host_check"]["after_read"] is True and not (rig.stub / "state" / "qemu").exists()


def test_a_check_point_past_stop_at_before_the_guest_stops_the_suite_with_no_boot(tmp_path):
    """Unit 00-guest has a check point of its own (guest_unit's first line): the preflight can end at or past stop_at, and
    then the guest is not booted, nor probed, nor any unit run; every unit is not run."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_JUMP_RE="preflight: PLAN=", STUB_JUMP_S=str(180 * 60))
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=00-guest reason=deadline"], r.why()
    assert r.idx("launch") == -1 and r.idx("latency_probe") == -1 and not r.runs(), "no boot, no smoke, no container"
    assert r.doc["not_run"] == ["01-honest", "02-inject"] and [u["state"] for u in r.doc["units"]] == ["not-run", "not-run"]
    assert r.doc["host_check"]["after_read"] is True and not (rig.stub / "state" / "qemu").exists()


@pytest.mark.parametrize("cfg", [{"STUB_BOOT": "hang", "STUB_CAP_RE": r"launch-qnx-kvm-bridged\.sh"},
                                 {"STUB_SMOKE7100_HANG": "1", "STUB_CAP_RE": r"_guest$"}], ids=["boot", "checks"])
def test_a_cap_that_fires_in_the_guests_boot_or_checks_is_a_step_timeout_at_00_guest(tmp_path, cfg):
    """Unit 00-guest has two caps, one on the boot and one on the guest's checks (:7150's readiness, the `ctl rules:` line,
    the :7100 smoke), each vss_capped (spec-2 section 13's "a unit without vss_capped"; 9.2 item 7's steps in order under
    the cap): a boot or a check that hangs does not run past stop_at. The stand-in launch script never ends once QEMU
    "runs", or the stand-in probe sleeps; the stub timeout cuts it after a second and puts the clock at the cap's end. The
    suite ends TIMEOUT at 00-guest, runs no unit, and stops the guest."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", **cfg)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=00-guest reason=step-timeout"], r.why()
    assert r.doc["not_run"] == ["01-honest", "02-inject"] and not r.runs(), "no unit ran"
    assert not (rig.stub / "state" / "qemu").exists(), "QEMU stopped"
    u = json.loads((rig.out / "00-guest" / "unit.json").read_text(encoding="utf-8"))
    assert u["state"] == "step-timeout", u


def test_a_cap_that_fires_in_a_unit_is_a_step_timeout_and_its_containers_are_swept(tmp_path):
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_CAP_RE="_unit 01 01-honest", STUB_SLEEP_ON="^docker run .*--name aw-scenario",
                STUB_SLEEP_S="5")
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest reason=step-timeout"], r.why()
    assert [u["state"] for u in r.doc["units"]] == ["step-timeout", "not-run"]
    assert not list((rig.stub / "state" / "docker").glob("*.json")), "the unit's containers removed"
    assert (rig.out / "01-honest" / "unit.json").exists()
    # 2.11's claim node log: the cap cut the unit while the claim node ran, so the sweep reads it, as it stands, before the
    # removal (a container removed has no log left to read)
    d = rig.out / "01-honest"
    assert "identity=holds" in (d / "claim-node.log").read_text(encoding="utf-8"), sorted(os.listdir(str(d)))
    logs = r.idx("docker", r"^logs aw-claim-node$")
    assert -1 < logs < r.idx_all("docker", r"^rm -f aw-sim aw-claim-node aw-scenario$")[0], logs
    u = json.loads((d / "unit.json").read_text(encoding="utf-8"))
    assert u["claim_log_at_sweep"] is True and "claim-node.log" in u["kept"], u
    # the header's "every stop but DONE syncs first": the sync comes before the stop's pkill of QEMU
    sync, pkill = r.idx("sync"), r.idx("pkill", r"qemu-system-aar")
    assert -1 < sync < pkill, (sync, pkill)


def test_a_unit_whose_child_fails_without_its_cap_firing_is_recorded_failed_and_the_suite_goes_on(tmp_path):
    """The header's unit form (each unit a child under its cap, `rc=0; vss_capped ... || rc=$?`): a child that exits
    non-zero while its cap has not fired is a unit that failed. It is recorded so in its unit.json and in suite.json, never
    not-run (which says it never started), its containers are swept and its record kept, and the suite goes on to its
    next unit and ends DONE. The failure point (critic#6, chosen by the r2 fix stage): the stand-in install refuses the
    unit's work directory, as a full or read-only disk would on a host; it is the child's first effect, and set -e ends the
    child there, before any container starts."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_INSTALL_FAIL_RE="/aw-suite-work/units/01-honest ")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = {x["name"]: x for x in r.doc["units"]}
    assert u["01-honest"]["state"] == "failed" and u["01-honest"]["unit_exit"] == 1, u["01-honest"]
    assert u["02-inject"]["state"] == "ran" and r.doc["not_run"] == [], r.doc["units"]
    assert r.idx("install", r"/aw-suite-work/units/01-honest ") > -1, "the failure point was reached"
    assert not [a for a in r.runs() if _unit_of(r, a) == "01-honest"], "the failed unit started no container"
    assert [_opt(a, "--name") for a in r.runs() if _unit_of(r, a) == "02-inject"] == ["aw-sim", "aw-claim-node", "aw-scenario"]
    start, nxt = r.idx("timeout", r"_unit 01 01-honest$"), r.idx("timeout", r"_unit 02 02-inject$")
    swept = [i for i in r.idx_all("docker", r"^rm -f aw-sim aw-claim-node aw-scenario$") if start < i < nxt]
    assert -1 < start < nxt and swept and u["01-honest"]["swept"] is True, (start, nxt, swept)
    d = json.loads((rig.out / "01-honest" / "unit.json").read_text(encoding="utf-8"))
    assert d["state"] == "failed" and d["unit_exit"] == 1, d
    assert "unit 01-honest: end (failed, exit 1)" in r.log, r.log[-3000:]


def test_every_unit_runs_under_its_cap(suite_runs):
    r = suite_runs["b2"]
    caps = [c[2] for c in r.calls if c[0] == "timeout" and "_unit " in c[2]]
    assert [c.split("_unit ")[1] for c in caps] == ["01 01-kill", "02 02-inject", "03 03-demo"], caps
    assert all(c.startswith("--kill-after=30s ") for c in caps)
    # unit 00-guest's two caps: the boot (the launch script), then the guest's checks (the harness again, as _guest)
    guest = [c[2] for c in r.calls if c[0] == "timeout" and ("launch-qnx-kvm-bridged.sh" in c[2] or c[2].endswith("_guest"))]
    assert len(guest) == 2 and "launch-qnx-kvm-bridged.sh" in guest[0] and guest[1].endswith("_guest"), guest
    assert all(c.startswith("--kill-after=30s ") for c in guest), guest


def test_a_drive_that_times_out_is_a_result_and_the_suite_goes_on(tmp_path):
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_SCENARIO_TIMEOUT_RE="01-honest")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = {x["name"]: x for x in r.doc["units"]}
    assert u["01-honest"]["state"] == "ran" and u["01-honest"]["scenario_exit"] == 3
    assert u["02-inject"]["scenario_exit"] == 0


def test_a_sim_that_never_comes_up_is_recorded_and_its_unit_ends(tmp_path):
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_SIM_NEVER_UP="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.doc["units"][0]["state"] == "sim-not-up" and not r.runs("aw-scenario")


def test_the_simulators_wait_ends_once_sim_up_s_have_passed_whatever_each_poll_took(tmp_path):
    """The header's "up to SIM_UP_S, every SIM_POLL_S" is a bound on the time the wait takes, not a count of polls: each poll
    is a `docker exec` with its own bound and then a pause, so SIM_UP_S / SIM_POLL_S polls could hold a unit for many times
    SIM_UP_S. Here each poll that lists none of the services moves the stub clock on by 100 s, so the wait gives up after
    the poll that ends at 300 s, its third."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_SIM_NEVER_UP="1", STUB_POLL_ADVANCE_S="100")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = r.doc["units"][0]
    assert u["state"] == "sim-not-up" and u["sim_up"] is False and u["sim_polls"] == 3, u
    polls = r.idx_all("docker", r"^exec aw-sim /sdv-aw/aw-entrypoint\.sh ros2 service list$")
    assert len(polls) == 3, len(polls)
    assert r.idx("docker", r"^stop -t \d+ aw-sim$") > polls[-1] and not r.runs("aw-scenario")
    assert u["operational_s"]["unit"] == 300, "the stub clock: three polls of 100 s"


def test_a_sim_that_lists_only_some_of_the_services_the_driver_calls_is_not_up(tmp_path):
    """sim_lists_services wants every one of SIM_SERVICES. A simulator part-way up, here listing only the first of them
    (/api/localization/initialize), is not up: the wait runs to its bound, and neither the claim node nor the driver starts."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_SIM_PARTIAL="1", STUB_POLL_ADVANCE_S="100")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = r.doc["units"][0]
    assert u["state"] == "sim-not-up" and u["sim_up"] is False and u["sim_polls"] == 3, u
    assert (rig.stub / "state" / "sim-polls").read_text() == "3", "the stand-in answered every poll, listing the first service"
    assert [_opt(a, "--name") for a in r.runs()] == ["aw-sim"] and not r.runs("aw-scenario")


def test_a_sim_container_that_has_stopped_ends_the_wait_at_the_poll_that_finds_it_so(tmp_path):
    """The poll loop's other way out: `docker inspect` says aw-sim is not running (it exited), so polling on to the time
    bound would only wait for a simulator that is gone. The unit ends sim-not-up after one poll."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_SIM_DIES="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    u = r.doc["units"][0]
    assert u["state"] == "sim-not-up" and u["sim_up"] is False and u["sim_polls"] == 1, u
    assert r.idx("docker", r"^inspect -f \{\{\.State\.Running\}\} aw-sim$") > -1
    assert [_opt(a, "--name") for a in r.runs()] == ["aw-sim"] and not r.runs("aw-scenario")


@pytest.mark.parametrize("cfg,setting", [({"STUB_RMEM_AFTER": "2147483647"}, "net.core.rmem_max"),
                                         ({"STUB_LO_MULTICAST_AFTER": "1"}, "lo.flags")])
def test_a_host_setting_that_changes_during_the_suite_ends_it_failed_at_host_check(tmp_path, cfg, setting):
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", **cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=host-check"], r.why()
    assert "changed %s before=" % setting in r.log and r.doc["host_check"]["same"] is False


def test_a_suite_whose_containers_cannot_be_listed_at_its_start_is_refused(tmp_path):
    r = Rig(tmp_path, stem="aw-suite", plan="a1").run(STUB_IMAGE_PRESENT="1", STUB_DOCKER_PS_FAIL="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "the containers labelled sdv.aw.run cannot be listed" in r.log


def test_a_sweep_that_cannot_list_the_containers_removes_them_by_name_and_is_unverified(tmp_path):
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    r = rig.run(STUB_IMAGE_PRESENT="1", STUB_DOCKER_PS_FAIL_AFTER="1")
    assert r.rc == 0 and r.status == ["status=DONE"], "the status line is not changed: " + r.why()
    assert r.doc["stop"]["verified"] is False and r.doc["stop"]["unverified"], r.doc["stop"]
    assert r.idx_all("docker", r"^rm -f aw-sim aw-claim-node aw-scenario ros-vss-feeder aw-smoke$")
    assert "the stop is unverified" in r.log


# --- the two harnesses' texts ---------------------------------------------------------------------------------------

def _code(text):
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


@pytest.mark.parametrize("path", [SETUP, SUITE, SETUP_TOOL, SUITE_TOOL])
def test_the_harnesses_are_host_neutral(path):
    """Spec-2 9.2 item 3: no instance type, core count or core list in either harness (their helpers included); the host
    is VSS_HOST's role word alone."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "a1.metal" not in text and "c7g.metal" not in text, path
    code = _code(text)
    for w in ("--cpuset", "cpuset-cpus", "taskset", "nproc", "AllowedCPUs", "cpu_count"):
        assert w not in code, (path, w)


def test_images_json_records_the_arm64_pull_wp6s_one_field():
    """Spec-2 2.6 and 9.1: autoware.arm64.pulled is filled once WP6's pull read the image back (9.1's pull by the arm64
    manifest digest, its ID read back as that digest, 2026-10-20); nothing else of the entry moves."""
    aw = _images()["autoware"]
    assert aw["arm64"] == {"manifest_digest": "sha256:596bf8a41a7957b8e57af02adf410d3ce65782f3f7afaa6ba3f8bef2db7e7919",
                           "pulled": "2026-10-20"}, aw["arm64"]
    assert aw["index_digest"] == "sha256:2c3ae9b76b205f2bad7b4906e2096cd9929f44627aa87813faa6e366c21cc274"
    assert aw["amd64"]["pulled"] == "2026-10-18" and aw["entrypoint"] == "never run (2.12)"


def test_the_two_harnesses_name_one_scenario_the_tarball_has_and_2_1s_containers():
    texts = {}
    for p in (SETUP, SUITE):
        with open(p, encoding="utf-8") as f:
            texts[p] = f.read()
        m = re.search(r'^SCENARIO=([a-z0-9-]+)$', texts[p], re.M)
        assert m and m.group(1) == "sample-lanelet-102", p
        assert os.path.exists(os.path.join(SDV_CTL, "scenarios", m.group(1) + ".json"))
    for p in (SETUP, SUITE):
        m = re.search(r"^AW_CONTAINERS=\(([^)]*)\)$", texts[p], re.M)
        assert m and tuple(m.group(1).split()) == CONTAINERS + ("aw-smoke",), "the sweep's names: 2.1's and the smoke's"


def _header(src):
    out = []
    for ln in src.splitlines()[1:]:
        if not ln.startswith("#"):
            break
        out.append(ln.lstrip("#"))
    return re.sub(r"\s+", " ", " ".join(out))


@pytest.mark.parametrize("path,lines", [
    (SETUP, ["status=DONE", "status=TIMEOUT at=<step> reason=deadline", "status=TIMEOUT at=<step> reason=step-timeout",
             "status=FAILED at=preflight", "status=FAILED at=host-check", "status=FAILED at=<step>"]),
    (SUITE, ["status=DONE", "status=TIMEOUT at=<unit> reason=deadline", "status=TIMEOUT at=<unit> reason=step-timeout",
             "status=FAILED at=preflight", "status=FAILED at=host-check", "status=FAILED at=record"]),
])
def test_each_header_lists_its_status_lines_and_what_it_does_not_show(path, lines):
    with open(path, encoding="utf-8") as f:
        h = _header(f.read())
    for ln in lines:
        assert ln in h, (path, ln)
    assert "WHAT IT DOES NOT SHOW" in h and "2.12" in h and "hostcheck.sh" in h


@pytest.mark.parametrize("path", [SETUP, SUITE, AWS_README])
def test_the_runnable_prose_holds_no_asserted_hit_of_the_claims_gates_denylist(path):
    """scripts/ci/claims_gate.py hard-fails a runnable file (scripts/**/*.sh and *.md, orin-native/**/*.sh) on an asserted
    denylist hit, and reads a shell header one comment line at a time, so a "NOT SHOW" on one line covers nothing on the
    next. The two harnesses and the README that carries the aw session, read here as the gate reads them, hold none."""
    ci = os.path.join(REPO, "scripts", "ci")
    sys.path.insert(0, ci)
    try:
        import claims_lib as C
    finally:
        sys.path.remove(ci)
    rules = C.load_denylist(os.path.join(ci, "claim-denylist.txt"))
    exempt = C.load_exemptions(os.path.join(ci, "claim-denylist.txt"))
    hits = C.scan_denylist(C.strip_superseded(C._read(path)), rules, exempt)
    assert rules and hits == [], [(why, " ".join(s.split())[:160]) for _p, why, s in hits]


@pytest.mark.parametrize("path", [SETUP_TOOL, SUITE_TOOL])
def test_the_helpers_parse_as_python_3_10_and_use_the_standard_library_only(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), feature_version=(3, 10))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert mods <= {"__future__", "argparse", "hashlib", "json", "os", "re", "sys", "tarfile", "typing", "vss_setup",
                    "aw_setup", "stat", "shutil"}, mods


def test_the_readmes_map_tar_command_makes_a_tar_that_setup_stages_and_a_dot_slash_one_is_refused(tmp_path):
    """The README's aw-map.tar bullet names the command that makes the tar, and says that a member named with a leading
    `./` is refused only at stage, after the preflight has passed, when the session's one run-aw-setup.sh is spent. The
    command, run here as the README gives it with GNU tar on a maps directory of this rig's stand-ins, makes a tar that
    aw_setup.py stage-map takes; the two `./` forms are refused and nothing is written."""
    with open(AWS_README, encoding="utf-8") as f:
        text = f.read()
    sec = re.sub(r"\s+", " ", text[text.index("### An aw session (SDV plan Phase 8)"):text.index("## What bounds the cost")])
    m = re.search(r"`(tar -cf aw-map\.tar -C <maps dir> sample-map-planning)`", sec)
    assert m, "the README names the command that makes aw-map.tar"
    assert "member named with a leading `./`" in sec and "refused at stage, after the preflight" in sec
    maps = tmp_path / "maps"
    os.makedirs(str(maps / "sample-map-planning"))
    for n, b in MAP_FILES.items():
        (maps / "sample-map-planning" / n).write_bytes(b)
    scn = tmp_path / "scenario.json"
    _write(scn, json.dumps(_scenario()))

    def made_by(cmd, name):
        d = tmp_path / name
        os.makedirs(str(d))
        p = subprocess.run(shlex.split(cmd.replace("<maps dir>", shlex.quote(str(maps)))), cwd=str(d), capture_output=True,
                           text=True, timeout=60)
        assert p.returncode == 0, (cmd, p.stderr)
        dest = d / "dest"
        st = subprocess.run([sys.executable, "-B", SETUP_TOOL, "stage-map", "--tar", str(d / "aw-map.tar"), "--scenario",
                             str(scn), "--dest", str(dest), "--facts", str(d / "facts")], capture_output=True, text=True,
                            timeout=60)
        return st, dest / "sample-map-planning"

    st, staged = made_by(m.group(1), "readme")
    assert st.returncode == 0, (st.stdout, st.stderr)
    assert sorted(os.listdir(str(staged))) == sorted(MAP_FILES)
    assert all((staged / n).read_bytes() == b for n, b in MAP_FILES.items())
    for k, cmd in enumerate(("tar -cf aw-map.tar -C <maps dir>/sample-map-planning .",
                             "tar -cf aw-map.tar -C <maps dir> ./sample-map-planning")):
        st, staged = made_by(cmd, "dot-slash-%d" % k)
        assert st.returncode == 1 and "aw-map.tar holds ./" in st.stdout, (cmd, st.stdout, st.stderr)
        assert not staged.exists(), cmd


# --- WP6 9.2's four open NITs (SDV Phase 8; the 9.2 critic's k16 and k32, 2026-10-27) ----------------------

@pytest.mark.parametrize("outcomes,replied,by_reason", [
    (["replied", "drop", "replied", "lost", "lost"], 2, {"0": 1, "12": 1}),
    (["drop", "drop", "lost"], 0, {}),
    (["lost", "replied"], 1, {"0": 1}),
    (["replied", "drop", "replied", "replied", "lost"], 3, {"0": 2, "12": 1}),
], ids=["mixed", "none-replied", "lost-then-replied", "repeated-reason"])
def test_a_units_record_counts_only_the_reply_logs_replied_lines_as_replies(tmp_path, outcomes, replied, by_reason):
    """ctlclient.py writes each frame's outcome as replied, drop or lost (its _outcome calls), and a drop or lost line has
    verdict and reason null: a frame the guest never answered. unit.json counts every frame line among the frames, and only
    a replied one as replied and under its reason (the replied frames here alternate reasons 0 and 12)."""
    with open(os.path.join(SDV_CTL, "ctlclient.py"), encoding="utf-8") as f:
        written = set(re.findall(r'self\._outcome\(p, "([a-z]+)"', f.read()))
    assert written == {"replied", "drop", "lost"}, "the outcomes ctlclient.py writes: %s" % sorted(written)
    work, unit, out = tmp_path / "work", tmp_path / "unit", tmp_path / "unit.json"
    _write(work / "facts" / "02-inject" / "state.s", "ran")
    docs, k = [{"header": {"format": 1, "kind": 2, "mode": "node"}}], 0
    for seq, outcome in enumerate(outcomes, start=1):
        if outcome == "replied":
            reason, k = (0, 12)[k % 2], k + 1
            docs.append({"seq": seq, "frame": "07" + "00" * 63, "outcome": "replied", "verdict": 0 if reason == 0 else 1,
                         "reason": reason, "mono_ns": 1000000 * seq})
        else:
            docs.append({"seq": seq, "frame": "07" + "00" * 63, "outcome": outcome, "verdict": None, "reason": None,
                         "mono_ns": 1000000 * seq})
    counters = {"controls": len(outcomes), "replied": replied, "drop": outcomes.count("drop"),
                "lost_on_reconnect": outcomes.count("lost")}
    docs.append({"summary": {"counters": counters}})
    _write(unit / "replies.jsonl", "".join(json.dumps(d, separators=(",", ":")) + "\n" for d in docs))
    p = _suite_tool("unit-json", "--work", str(work), "--name", "02-inject", "--unit-dir", str(unit), "--plan", "a2",
                    "--out", str(out))
    assert p.returncode == 0, (p.stdout, p.stderr)
    u = json.loads(out.read_text(encoding="utf-8"))
    assert u["state"] == "ran" and u["unit"] == "02-inject", u
    assert u["replies"] == {"frames": len(outcomes), "replied": replied, "by_reason": by_reason,
                            "summary": {"counters": counters}}, u["replies"]


@pytest.mark.parametrize("ref", ["TAG", "REPO", "ID", "AT-SHA512", "EMPTY-DIGEST", "TAG-AND-DIGEST", "LONG-DIGEST",
                                 "SHORT-DIGEST", "UPPER-DIGEST", "SHA512-64", "REGISTRY-PORT", "NO-SLASH", "TRAILING-NEWLINE",
                                 "UPPER-REPO", "LEADING-SLASH", "EMPTY-SEGMENT", "NO-AT", "NO-COLON", "TRAILING-SLASH", "AT-AT",
                                 "UPPER-FIRST-SEGMENT", "UPPER-LAST-LETTER", "DOMAIN-ONLY", "COLON-FOR-AT", "TWO-DIGESTS",
                                 "LEADING-SPACE", "UNDERSCORE-FIRST", "SPACE-IN-REPO", "AT-NOTHING", "SPACE-AFTER-AT"])
def test_suite_refuses_a_setup_json_whose_image_ref_is_not_by_digest_before_any_docker_call(tmp_path, ref):
    """2.6: the Autoware image runs only as repo@sha256:<digest>. A setup.json whose image.ref is the repository by its tag,
    the repository alone, the image ID alone, the repository at a sha512 digest, the repository at `sha256:` with no
    digest, the repository by its tag and then at its digest, the repository at a digest one hex digit too long, one
    short, upper-case, `sha512:` with 64 hex, a registry port before the repository, a repository with no '/' in it, the
    whole reference and then a newline, the repository upper-cased at its digest, a '/' before the whole reference, the
    repository with its first '/' doubled (an empty segment), the digest glued to the repository with no '@', the
    repository at `sha256` and the 64 hex with no ':', the repository and a '/' before the '@', the repository at '@@', the
    repository with its first letter upper-case, or its last, the repository's first segment alone (its domain) at the
    digest, the repository and a ':' for the '@', the whole reference and then '@' and a second digest, a space before the
    whole reference, a '_' in the repository's first segment, a space inside one of its later segments, the repository and
    '@' with nothing after it, or the repository, '@', a space and the digest (2.6's form is the whole of
    <repo>@sha256:<64 lowercase hex>, no tag before the '@') is refused at the preflight before any docker call (the
    stand-in docker echoes any reference into RepoDigests, so its image inspect would take each that has an '@';
    aw_setup.py inspect refuses the others itself, the test below): nothing inspected, nothing started, no guest booted,
    and suite.json names no image."""
    aw = _images()["autoware"]
    ref = {"TAG": "%s:%s" % (aw["repo"], aw["tag"]), "REPO": aw["repo"], "ID": _digest(),
           "AT-SHA512": "%s@sha512:%s" % (aw["repo"], "ab" * 64), "EMPTY-DIGEST": "%s@sha256:" % aw["repo"],
           "TAG-AND-DIGEST": "%s:%s@%s" % (aw["repo"], aw["tag"], _digest()),
           "LONG-DIGEST": "%s@%s0" % (aw["repo"], _digest()), "SHORT-DIGEST": "%s@%s" % (aw["repo"], _digest()[:-1]),
           "UPPER-DIGEST": "%s@sha256:%s" % (aw["repo"], _digest()[7:].upper()),
           "SHA512-64": "%s@sha512:%s" % (aw["repo"], _digest()[7:]),
           "REGISTRY-PORT": "localhost:5000/%s@%s" % (aw["repo"], _digest()), "NO-SLASH": "autoware@%s" % _digest(),
           "TRAILING-NEWLINE": _ref() + "\n", "UPPER-REPO": "%s@%s" % (aw["repo"].upper(), _digest()),
           "LEADING-SLASH": "/" + _ref(), "EMPTY-SEGMENT": _ref().replace("/", "//", 1), "NO-AT": aw["repo"] + _digest(),
           "NO-COLON": "%s@sha256%s" % (aw["repo"], _digest()[7:]), "TRAILING-SLASH": aw["repo"] + "/@" + _digest(),
           "AT-AT": aw["repo"] + "@@" + _digest(), "UPPER-FIRST-SEGMENT": aw["repo"][0].upper() + aw["repo"][1:] + "@" + _digest(),
           "UPPER-LAST-LETTER": aw["repo"][:-1] + aw["repo"][-1].upper() + "@" + _digest(),
           "DOMAIN-ONLY": aw["repo"].split("/")[0] + "@" + _digest(), "COLON-FOR-AT": aw["repo"] + ":" + _digest(),
           "TWO-DIGESTS": _ref() + "@" + _digest(), "LEADING-SPACE": " " + _ref(),
           "UNDERSCORE-FIRST": "gh_cr.io/autowarefoundation/autoware@" + _digest(),
           "SPACE-IN-REPO": aw["repo"].replace("/", "/a ", 1) + "@" + _digest(), "AT-NOTHING": aw["repo"] + "@",
           "SPACE-AFTER-AT": aw["repo"] + "@ " + _digest()}[ref]
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    _write(rig.w / "rec" / "aw-setup" / "raw" / "setup.json", json.dumps(
        {"format": 1, "harness": "run-aw-setup.sh", "status": "DONE", "budget_short": False, "host_mode": "c7g-metal",
         "image": {"ref": ref, "id": _digest()}, "facts": {}}, indent=1))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "names no image pulled by its digest (image.ref)" in r.log, r.log[-3000:]
    assert r.docker == [] and r.idx("launch") == -1, "no docker call, no guest booted"
    assert r.doc["image"] is None and "image_ref" not in r.doc["preflight"], r.doc["preflight"]


@pytest.mark.parametrize("ref", ["REPO", "TAG", "ID"])
def test_setup_tools_inspect_refuses_a_reference_with_no_at_in_words_and_writes_no_fact(tmp_path, ref):
    """aw_setup.py inspect reads the digest after the reference's '@': a reference with none (the repository alone, by its
    tag, or the image ID alone) is refused in one line naming 2.6's form, exit 1, no traceback and no fact written,
    though the image read back lists that reference in its RepoDigests. run-aw-suite.sh reaches inspect only past setup's
    own refusal of such a reference (the k32 test above) and run-aw-setup.sh only with aw_setup.py ref's output, so this
    calls the tool directly."""
    aw = _images()["autoware"]
    ref = {"REPO": aw["repo"], "TAG": "%s:%s" % (aw["repo"], aw["tag"]), "ID": _digest()}[ref]
    inspect = json.dumps([{"Id": _digest(), "RepoDigests": [_ref(), ref], "Os": "linux", "Architecture": "arm64"}])
    facts = tmp_path / "facts"
    p = subprocess.run([sys.executable, "-B", SETUP_TOOL, "inspect", "--ref", ref, "--facts", str(facts)], input=inspect,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1 and p.stderr == "", (p.returncode, p.stdout, p.stderr)
    assert p.stdout.count("\n") == 1 and "the reference %s has no '@'" % ref in p.stdout, p.stdout
    assert "<repo>@sha256:<64 lowercase hex>" in p.stdout and not facts.exists(), p.stdout


@pytest.mark.parametrize("repo", ["UPPER", "UPPER-FIRST", "PORT", "NO-SLASH", "LEADING-SLASH", "TRAILING-SLASH", "EMPTY-SEGMENT",
                                  "TRAILING-NEWLINE", "AT", "SPACE", "UNDERSCORE-FIRST", "PREFIX-JUNK", "NULL", "NUMBER"])
def test_setup_tools_ref_refuses_an_images_json_repository_not_of_the_repository_rule_in_one_line(tmp_path, repo):
    """aw_setup.py ref takes images.json's autoware.repo only by REPOSITORY, whole (pull_ref): lower-case segments joined
    by '/', at least two, the first with no '_'. A repository upper-cased, upper-case in its first segment only, with a
    registry port, with no '/', with a '/' before it or after it, with an empty segment, with a newline after it, with an
    '@' in it, with a space in it, with a '_' in its first segment, with a '!' before it, or that is null or the number 5,
    is refused in one line naming it, exit 1, no traceback. The chain test below reaches pull_ref only with images.json's own
    repository, and the k32 test above reaches REPOSITORY only through the suite's IMAGE_REF, which keeps the pattern and
    not the compiled rule, so this calls the tool directly."""
    repo = {"UPPER": "GHCR.IO/AUTOWAREFOUNDATION/AUTOWARE", "UPPER-FIRST": "Ghcr.io/autowarefoundation/autoware",
            "PORT": "localhost:5000/autowarefoundation/autoware", "NO-SLASH": "autoware", "LEADING-SLASH": "/ghcr.io/a/b",
            "TRAILING-SLASH": "ghcr.io/a/b/", "EMPTY-SEGMENT": "ghcr.io//a", "TRAILING-NEWLINE": "ghcr.io/a/b\n",
            "AT": "ghcr.io/a/b@x", "SPACE": "ghcr.io/a b/c", "UNDERSCORE-FIRST": "gh_cr.io/a/b", "PREFIX-JUNK": "!ghcr.io/a/b",
            "NULL": None, "NUMBER": 5}[repo]
    doc = _images()
    doc["autoware"]["repo"] = repo
    images = tmp_path / "images.json"
    _write(images, json.dumps(doc, indent=2) + "\n")
    p = subprocess.run([sys.executable, "-B", SETUP_TOOL, "ref", "--images", str(images)], capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 1 and p.stderr == "", (p.returncode, p.stdout, p.stderr)
    assert p.stdout == "images.json's autoware.repo %r is not a repository\n" % (repo,), p.stdout


def test_the_setup_json_run_aw_setup_writes_passes_the_suites_preflight_and_the_suite_runs_its_image_ref(setup_done, tmp_path):
    """2.11's setup.json between the two harnesses: the one run-aw-setup.sh wrote (setup_done's, copied byte for byte into
    a suite rig's rec/aw-setup) passes run-aw-suite.sh's preflight, and the suite runs the image.ref it records,
    images.json's <repo>@<arm64 digest>. That ref is aw_setup.py ref's (pull_ref: the repository by aw_setup.py's
    REPOSITORY, '@', the digest) and the check is aw_suite.py's IMAGE_REF, built from that REPOSITORY and DIGEST in 2.6's
    whole form: should one side change alone so that the two no longer agree on images.json's own ref (pull_ref on a rule
    of its own, its join, or IMAGE_REF's form), setup would not end DONE, or a session whose setup ended DONE would have
    its suite refused at the preflight, and this test fails."""
    assert setup_done.rc == 0 and setup_done.status == ["status=DONE"], setup_done.why()
    ref = setup_done.doc["image"]["ref"]
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    shutil.copy(str(setup_done.rig.out / "setup.json"), str(rig.w / "rec" / "aw-setup" / "raw" / "setup.json"))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert "names no image pulled by its digest (image.ref)" not in r.log, r.log[-3000:]
    assert "preflight: PLAN=a1, run-aw-setup.sh DONE as c7g-metal, the image %s in the store" % ref in r.log, r.log[-3000:]
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.doc["preflight"]["image_ref"] == ref and ref == _ref(), (ref, r.doc["preflight"])


# the child below: aw_setup imported from argv[1], its constant argv[2] widened to an alternation with argv[3], aw_suite
# imported after it, and IMAGE_REF's verdict on each reference read from stdin
_WIDENED = """import json, re, sys
sys.path.insert(0, sys.argv[1])
import aw_setup
setattr(aw_setup, sys.argv[2], re.compile(getattr(aw_setup, sys.argv[2]).pattern + "|" + sys.argv[3]))
import aw_suite
print(json.dumps([aw_suite.IMAGE_REF.fullmatch(s) is not None for s in json.load(sys.stdin)]))
"""


@pytest.mark.parametrize("side", ["DIGEST", "REPOSITORY"])
def test_image_ref_keeps_an_alternation_in_either_of_aw_setups_constants_on_its_own_side_of_the_at(side):
    """aw_suite.py's IMAGE_REF is aw_setup.py's REPOSITORY, '@' and its DIGEST, each in a group of its own, and its comment
    gives the reason: an alternation in either cannot leak past the '@'. Neither holds one today, so a child imports
    aw_setup, makes DIGEST also take `sha512:<128 hex>` (or REPOSITORY also `LOCAL/<upper-case letters>`), and imports
    aw_suite after it: IMAGE_REF takes images.json's ref and the new branch joined by '@' to the other part, and refuses
    either digest alone (or either repository alone). Neither branch is of its constant's own rule, so only an IMAGE_REF
    built from the widened constant can take it. This holds IMAGE_REF's form, not a reference a session meets."""
    aw = _images()["autoware"]
    extra, taken, refused = {
        "DIGEST": ("sha512:[0-9a-f]{128}", ["%s@sha512:%s" % (aw["repo"], "a" * 128)], ["sha512:" + "a" * 128, _digest()]),
        "REPOSITORY": ("LOCAL/[A-Z]+", ["LOCAL/AUTOWARE@" + _digest()], [aw["repo"], "LOCAL/AUTOWARE"])}[side]
    probes = [_ref()] + taken + refused
    p = subprocess.run([sys.executable, "-B", "-c", _WIDENED, G, side, extra], input=json.dumps(probes),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stderr == "", (p.returncode, p.stdout, p.stderr)
    got = json.loads(p.stdout)
    assert got == [True] * (1 + len(taken)) + [False] * len(refused), list(zip(probes, got))


# --- the third NIT package (SDV Phase 8; the aw harness's NITs and the second NIT critic's cases, 2026-10-31) --

# 9.1's whole aw-scan.json lists every ELF read under elf_files (its entries carry more keys than these)
_ELF_FILES = [{"layer": 1, "path": "usr/lib/liba.so.1"}, {"layer": 1, "path": "usr/lib/libb.so.2"},
              {"layer": 2, "path": "usr/bin/c"}]


def _scan_doc(elf_files):
    return {"format": 1, "image_digest": _digest(), "elf_files": elf_files, "findings": [], "exceptions_applied": [],
            "verdict": "pass"}


@pytest.mark.parametrize("elf_files,kind,text", [(_ELF_FILES, "i", "3"), ([], "i", "0"), (3, "i", "3"), (True, "s", "True"),
                                                 ("3", "s", "3"), (None, "s", "None"), ({"a": 1, "b": 2}, "s", "{'a': 1, 'b': 2}"),
                                                 (3.0, "s", "3.0"), ([{"layer": 1}, None, [1, 2], "x"], "i", "4")],
                         ids=["LIST", "EMPTY-LIST", "INT", "BOOL", "STRING", "NULL", "DICT", "FLOAT", "MIXED-LIST-OF-FOUR"])
def test_setup_tools_scan_records_elf_files_as_a_lists_length_an_int_as_it_is_else_as_its_string(tmp_path, elf_files, kind, text):
    """9.1's whole aw-scan.json lists every ELF read under elf_files (awscan.py's record), and a summary of it holds their
    count: aw_setup.py scan records the list's length (every entry counted, whatever it is, a nested list as one), or the
    int as it is, an int fact either way, and anything else (a bool is not an int, nor a float; a dict is not a list) as its
    string, so the list's repr, one long string, never becomes a fact of setup.json."""
    scan, facts, txt = tmp_path / "aw-scan.json", tmp_path / "facts", tmp_path / "inputs.txt"
    _write(scan, json.dumps(_scan_doc(elf_files)))
    p = subprocess.run([sys.executable, "-B", SETUP_TOOL, "scan", "--scan", str(scan), "--images", IMAGES, "--facts", str(facts),
                        "--txt", str(txt)], capture_output=True, text=True, timeout=60)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", ""), (p.returncode, p.stdout, p.stderr)
    got = sorted(n for n in os.listdir(str(facts / "scan")) if n.startswith("elf_files."))
    assert got == ["elf_files." + kind], got
    assert (facts / "scan" / got[0]).read_text(encoding="utf-8") == text


def test_setup_records_a_whole_scans_elf_files_as_their_count_and_no_entry_of_the_list(tmp_path):
    """The session's aw-scan.json may be 9.1's whole record, elf_files its list: run-aw-setup.sh ends DONE with their count,
    an int, under facts.preflight.scan, and no entry of the list reaches setup.json, which capture.py publishes as it is."""
    rig = Rig(tmp_path)
    rig.aw_inputs(scan=_scan_doc(_ELF_FILES))
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.facts("preflight", "scan", "elf_files") == 3, r.facts("preflight", "scan")
    assert "usr/lib/liba.so.1" not in json.dumps(r.doc), "never the list's repr"


def test_the_guests_ctl_rules_problem_is_empty_when_the_rules_tool_passes(suite_runs):
    """run-aw-suite.sh records the rules tool's last output line as ctl_rules_problem only when the tool exits other than 0
    (its refusal, which ends the suite); on a pass the fact is the empty string, though the tool's last line is then its
    count of `ctl rules:` lines, which ctl_rules.lines records. suite.json's guest and 00-guest's unit.json alike."""
    r = suite_runs["a2"]
    u = json.loads((r.rig.out / "00-guest" / "unit.json").read_text(encoding="utf-8"))
    for g in (r.doc["guest"], u):
        assert g["ctl_rules_exit"] == 0 and g["ctl_rules"]["lines"] == 1 and g["ctl_rules_problem"] == "", g


@pytest.mark.parametrize("console,problem", [
    ((RULES_CTL % "0x0BADF00D").encode(), "the guest's `ctl rules:` catalog 0x0BADF00D is not vss_ctl.py's DIGEST %s: the "
     "guest judges another kind 2 contract than the claim node packs by" % CTL_DIGEST),
    (b"monitor: nothing of kind 2", "the guest's console holds no `ctl rules:` line: its image is not the ctl monitor's "
     "(WP5's ifs-ctl.bin), or its :7150 process did not start"),
    ((RULES_CTL % CTL_DIGEST).replace("profiles 1 2", "profiles 1").encode(),
     "the guest's `ctl rules:` profiles [1] lack profile 2, which the plans send"),
], ids=["CATALOG", "NONE", "PROFILES"])
def test_a_rules_refusal_is_the_guests_ctl_rules_problem_and_the_suites_reason(tmp_path, console, problem):
    """A rules tool that exits 1 leaves its refusal as its last output line: run-aw-suite.sh records that line as
    ctl_rules_problem, with ctl_rules_exit 1, and ends the suite FAILED at the preflight with it as the reason."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    (rig.stub / "console.bin").write_bytes(_console(console))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    u = json.loads((r.rig.out / "00-guest" / "unit.json").read_text(encoding="utf-8"))
    for g in (r.doc["guest"], u):
        assert g["ctl_rules_exit"] == 1 and g["ctl_rules_problem"] == problem, g
    assert "FAILED at preflight: %s\n" % problem in r.log, r.log[-3000:]


# a rules tool of its own in place of aw_suite.py's `rules` (every other subcommand the real tool's, moved to
# aw_suite_real.py): it prints a count, then a problem line, and exits 2
_RULES_EXIT_2_LINE = "the stand-in rules tool stopped here, exit 2"
_RULES_EXIT_2 = '''#!/usr/bin/env python3
import os, runpy, sys
HERE = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:2] == ["rules"]:
    sys.stdout.write("7\\n%s\\n")
    sys.stdout.flush()
    sys.exit(2)
real = os.path.join(HERE, "aw_suite_real.py")
sys.argv[0] = real
runpy.run_path(real, run_name="__main__")
''' % _RULES_EXIT_2_LINE


def test_a_rules_tool_that_exits_2_leaves_its_last_line_as_the_problem_and_the_suite_stops_before_any_container(tmp_path):
    """The fact is the tool's last output line whenever its exit is not 0, not only on exit 1: a tool that prints a count and
    then a problem line and exits 2 gives ctl_rules_exit 2, that line as ctl_rules_problem (not the count) in suite.json's
    guest and 00-guest's unit.json, and the suite's reason; FAILED at the preflight, no container, QEMU stopped."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a2")
    os.rename(str(rig.g / "aw_suite.py"), str(rig.g / "aw_suite_real.py"))
    _write(rig.g / "aw_suite.py", _RULES_EXIT_2, 0o755)
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    u = json.loads((r.rig.out / "00-guest" / "unit.json").read_text(encoding="utf-8"))
    for g in (r.doc["guest"], u):
        assert g["ctl_rules_exit"] == 2 and g["ctl_rules_problem"] == _RULES_EXIT_2_LINE, g
    assert "FAILED at preflight: %s\n" % _RULES_EXIT_2_LINE in r.log, r.log[-3000:]
    assert not r.runs() and not (rig.stub / "state" / "qemu").exists(), "no container; QEMU stopped"


RULES_OK = (RULES_CTL % CTL_DIGEST).encode()
_NEAR = RULES_OK.replace(b"ctl rules:", b"ctl rulesX:")
# the same line with a long `(vss ...)` version: over 200 characters from where it starts to where it ends
_LONG = RULES_OK.replace(b"(vss 6.0)", b"(vss 6.0 " + b"x" * 200 + b")")
# the vss monitor's rules line (monitor.c's vss_announce), which ends in its own `, profiles`, as a ctl rules line does
_VSS = b"monitor: vss rules: kind 4, catalog 0x4D68EA68 (vss 6.0), age_max 300 ms, profiles 1 2 4"
# seven `monitor: ctl rules:` lines, six of them after something on the same console line: another process's line, not yet
# ended (four, one of them a ctl rules line cut short), or NUL or spaces before it (two), which the reading drops
_INTERLEAVED = [b"Startup complete" + RULES_OK, RULES_OK, _VSS + RULES_OK,
                b"\0\0" + RULES_OK, b"   " + RULES_OK, b"pci-server: done. " + RULES_OK,
                b"monitor: ctl rules: kind 2, catalog" + RULES_OK]


@pytest.mark.parametrize("lines,count", [
    (_INTERLEAVED, 7),
    ([RULES_OK, _NEAR, b"Startup complete" + _NEAR, b"Startup complete" + RULES_OK.replace(b"monitor: ", b"monitor:"),
      RULES_OK.replace(b"monitor:", b"Monitor:")], 1),
    ([RULES_OK, RULES_OK + b"Startup complete", b"Startup complete" + RULES_OK + b" pci-server: done.", RULES_OK + _VSS,
      b"Startup complete" + RULES_OK + _VSS], 1),
    ([RULES_OK + b"\t"], 1),
    ([_LONG, b"Startup complete" + _LONG], 2),
], ids=["INTERLEAVED-SEVEN", "NEAR-MISS-PREFIX", "TEXT-AFTER-THE-PROFILES", "TRAILING-TAB", "LONG-LINE"])
def test_the_rules_tool_counts_a_ctl_rules_line_where_it_starts_in_a_console_line_and_only_one_that_ends_it(tmp_path, lines,
                                                                                                          count):
    """Each monitor process the guest starts prints one `monitor: ctl rules:` line (monitor.c's ctl_announce), and on the
    console another process's boot text can come before it on the same line: aw_suite.py rules counts the line where it
    starts in the console line (NUL and CR removed, white space at its ends stripped, a trailing tab included), its catalog
    and profiles parsed as before, so all seven here, and a line of over 200 characters wherever it starts. A near-miss of
    its prefix (`monitor: ctl rulesX:`, `monitor:ctl rules:`, `Monitor: ctl rules:`) is not counted, nor a line with text
    after its profiles, which end the line: digits run on after them could not be told from a profile. That text may be the
    vss monitor's rules line, which ends in its own `, profiles 1 2 4`: the ctl line's middle holds no ':', so the reading
    does not run on to them, and the line is not counted rather than counted with the vss monitor's profiles."""
    console, facts = tmp_path / "console.log", tmp_path / "facts"
    console.write_bytes(_console(b"\r\n".join(lines)))
    p = _suite_tool("rules", "--console", str(console), "--digest", CTL_DIGEST, "--facts", str(facts))
    assert (p.returncode, p.stdout, p.stderr) == (0, "%d\n" % count, ""), (p.returncode, p.stdout, p.stderr)
    assert (facts / "lines.i").read_text(encoding="utf-8") == str(count)
    assert (facts / "catalog.s").read_text(encoding="utf-8") == CTL_DIGEST
    assert (facts / "profiles.lines").read_text(encoding="utf-8") == "1\n2\n"


def test_the_suite_records_every_ctl_rules_line_of_an_interleaved_guest_console(tmp_path):
    """The same seven lines through run-aw-suite.sh: suite.json's guest holds ctl_rules.lines 7, the digest matching, and
    an empty ctl_rules_problem, and the suite runs its plan."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    (rig.stub / "console.bin").write_bytes(_console(b"\r\n".join(_INTERLEAVED)))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.doc["guest"]
    assert g["ctl_rules"]["lines"] == 7 and g["ctl_rules"]["digest_matches"] is True and g["ctl_rules_problem"] == "", g


def test_the_suite_does_not_count_a_ctl_rules_line_that_the_vss_monitors_line_follows_on_its_console_line(tmp_path):
    """A ctl rules line after boot text with the vss monitor's rules line after it, the ctl monitor's CRLF not yet come,
    then a bare ctl rules line: the guest is healthy, so the suite runs its plan with ctl_rules.lines 1 and profiles 1 2,
    never refused at the preflight because the first line is read with the vss monitor's profiles 1 2 4."""
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    (rig.stub / "console.bin").write_bytes(_console(b"\r\n".join([b"Startup complete" + RULES_OK + _VSS, RULES_OK])))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.doc["guest"]
    assert g["ctl_rules"]["lines"] == 1 and g["ctl_rules"]["profiles"] == [1, 2] and g["ctl_rules_problem"] == "", g


def test_a_guest_whose_only_ctl_rules_line_the_vss_monitors_line_follows_is_refused_as_holding_none(tmp_path):
    """The same line with no bare one after it is not counted, so the rules tool refuses with its `no ctl rules:` words
    and the suite ends FAILED at the preflight with them: its count is never 1 with the vss monitor's profiles 1 2 4."""
    problem = ("the guest's console holds no `ctl rules:` line: its image is not the ctl monitor's (WP5's ifs-ctl.bin), or "
               "its :7150 process did not start")
    rig = Rig(tmp_path, stem="aw-suite", plan="a1")
    (rig.stub / "console.bin").write_bytes(_console(RULES_OK + _VSS))
    r = rig.run(STUB_IMAGE_PRESENT="1")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    g = r.doc["guest"]
    assert g["ctl_rules_exit"] == 1 and g["ctl_rules"]["lines"] == 0 and g["ctl_rules_problem"] == problem, g
    assert "FAILED at preflight: %s\n" % problem in r.log, r.log[-3000:]
    assert not r.runs() and not (rig.stub / "state" / "qemu").exists(), "no container; QEMU stopped"


# repositories of REPOSITORY's grammar (lower-case segments joined by '/', at least two, the first with no '_'), between
# them using every character of both its classes in a first segment and in a later one (documentation values); fable#3's
# tightening of the grammar rewrites this list
_GRAMMAR_REPOS = ["a/b", "0/9", "reg-1.example/auto_ware/a.b-c", "x.y-z/_/-/.", "ghcr.io/autowarefoundation/autoware",
                  "a-b/c_d", "p.q/r_s.t-u/v/w/x/y/z0",
                  "abcdefghijklmnopqrstuvwxyz0123456789.-/abcdefghijklmnopqrstuvwxyz0123456789._-"]
# characters no repository and no digest may hold: every printable ASCII one outside [a-z0-9._/-], NUL, and four others
# (an Arabic-Indic digit one, a fullwidth a, an e acute, the Kelvin sign)
_OUTSIDE = sorted(set(string.printable) - set(string.ascii_lowercase + string.digits + "._/-")) + [
    "\x00", "\u0661", "\uff41", "\u00e9", "\u212a"]

# the child below: aw_setup and aw_suite imported from argv[1]; REPOSITORY's verdict on each "repo" string and IMAGE_REF's
# on each "ref" string read from stdin, IMAGE_REF's pattern, the join of aw_setup's two constants, and their groups
_JUDGE = """import json, sys
sys.path.insert(0, sys.argv[1])
import aw_setup, aw_suite
req = json.load(sys.stdin)
print(json.dumps({"repo": [aw_setup.REPOSITORY.fullmatch(s) is not None for s in req["repo"]],
                  "ref": [aw_suite.IMAGE_REF.fullmatch(s) is not None for s in req["ref"]],
                  "pattern": aw_suite.IMAGE_REF.pattern,
                  "join": "(?:%s)@(?:%s)" % (aw_setup.REPOSITORY.pattern, aw_setup.DIGEST.pattern),
                  "groups": [aw_setup.REPOSITORY.groups, aw_suite.IMAGE_REF.groups]}))
"""


def _judge(repos, refs):
    p = subprocess.run([sys.executable, "-B", "-c", _JUDGE, G], input=json.dumps({"repo": repos, "ref": refs}),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0 and p.stderr == "", (p.returncode, p.stdout, p.stderr)
    return json.loads(p.stdout)


def _one_char_edits(s, chars):
    """Every string one character of CHARS away from S: each put in at each place, and each in place of each character."""
    out = {s[:i] + c + s[i:] for i in range(len(s) + 1) for c in chars}
    out |= {s[:i] + c + s[i + 1:] for i in range(len(s)) for c in chars}
    out.discard(s)
    return sorted(out)


def test_image_ref_is_the_join_of_aw_setups_repository_and_digest_and_neither_has_a_group():
    """aw_suite.py's IMAGE_REF pattern is exactly "(?:REPOSITORY)@(?:DIGEST)" of aw_setup.py's two constants' patterns, and
    neither it nor REPOSITORY holds a capturing group."""
    got = _judge([], [])
    assert got["pattern"] == got["join"], (got["pattern"], got["join"])
    assert got["groups"] == [0, 0], got["groups"]


def test_every_repository_of_the_grammar_here_is_taken_by_repository_and_at_the_digest_by_image_ref():
    """Each repository of _GRAMMAR_REPOS is taken whole by aw_setup.py's REPOSITORY, and joined by '@' to the arm64 digest by
    aw_suite.py's IMAGE_REF: no class character, no single later segment and no one-character first segment is refused on
    either side."""
    got = _judge(_GRAMMAR_REPOS, ["%s@%s" % (r, _digest()) for r in _GRAMMAR_REPOS])
    assert got["repo"] == [True] * len(_GRAMMAR_REPOS), list(zip(_GRAMMAR_REPOS, got["repo"]))
    assert got["ref"] == [True] * len(_GRAMMAR_REPOS), list(zip(_GRAMMAR_REPOS, got["ref"]))


@pytest.mark.parametrize("repo", _GRAMMAR_REPOS)
def test_setup_tools_ref_prints_each_repository_of_the_grammar_at_the_arm64_digest_and_the_suites_setup_takes_it(tmp_path, repo):
    """aw_setup.py ref prints images.json's autoware.repo, here each repository of the grammar, at the arm64 digest, and
    aw_suite.py setup takes a setup.json naming that reference and prints it with the ID."""
    doc = _images()
    doc["autoware"]["repo"] = repo
    images = tmp_path / "images.json"
    _write(images, json.dumps(doc, indent=2) + "\n")
    p = subprocess.run([sys.executable, "-B", SETUP_TOOL, "ref", "--images", str(images)], capture_output=True, text=True,
                       timeout=60)
    want = "%s@%s" % (repo, doc["autoware"]["arm64"]["manifest_digest"])
    assert (p.returncode, p.stdout, p.stderr) == (0, want + "\n", ""), (p.returncode, p.stdout, p.stderr)
    setup = tmp_path / "setup.json"
    _write(setup, json.dumps({"status": "DONE", "budget_short": False, "host_mode": "c7g-metal",
                              "image": {"ref": want, "id": _digest()}}))
    q = _suite_tool("setup", "--setup", str(setup), "--host-mode", "c7g-metal", "--facts", str(tmp_path / "facts"))
    assert (q.returncode, q.stdout, q.stderr) == (0, "%s %s\n" % (want, _digest()), ""), (q.returncode, q.stdout, q.stderr)


def test_one_character_outside_the_classes_put_in_or_in_place_of_any_character_of_the_ref_is_refused_by_image_ref():
    """Every character of _OUTSIDE put in at each place of images.json's whole reference, or in place of each of its
    characters, gives a string aw_suite.py's IMAGE_REF refuses: on either side of the '@', and the '@' itself."""
    edits = _one_char_edits(_ref(), _OUTSIDE)
    got = _judge([], edits)
    taken = [e for e, ok in zip(edits, got["ref"]) if ok]
    assert taken == [], taken[:10]


def test_one_character_outside_the_classes_put_in_or_in_place_of_any_character_of_the_repository_is_refused_by_repository():
    """The same edits of images.json's autoware.repo alone (a ':' or an '@' among them) give strings aw_setup.py's
    REPOSITORY refuses."""
    repo = _images()["autoware"]["repo"]
    edits = _one_char_edits(repo, _OUTSIDE)
    got = _judge(edits, [])
    taken = [e for e, ok in zip(edits, got["repo"]) if ok]
    assert taken == [], taken[:10]
