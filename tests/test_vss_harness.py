"""run-vss-setup.sh (plan Phase 3 WP4): the setup harness
of a vss session on a bare-metal AWS instance, run here against stubs; and run-vss-suite.sh (WP5), the suite harness,
the second half of this file (its own rig, SUITE RIG below). No git runs here.

THE RIG. The harness runs as the detached runner runs it (remote-ladder.sh _detached): from W/repo/orin-native/
gpu-concurrency, with the harness phase's environment (W, IFS_BIN, IMG_S, IMG_B, DISK, OUT, VSS_IN, VSS_HOME, STATUS,
VPROBE, CSTATE), stdout and stderr into the stem's run.log. W/repo holds the real harness, the real deadline library and
the real vss_setup.py, beside stand-ins for the launch script, latency_probe.py and sdv/stack/bundle.py (which runs docker
through its --docker prefix, as the real one does). W/in holds a bundle of small stand-in members; its Python tarball
carries a stand-in python3 whose venv holds a stand-in python.

Every other command the harness runs is a stub first on PATH, each logging one line (its name, whether it ran under the
stub sudo, its arguments) to calls.log: sudo (only `sudo -n`; a path under /etc/docker goes to the stub's own root, so the
real /etc is never written), apt-get, apt-cache, dpkg-query, usermod, docker, iptables, iptables-save, sysctl, lsmod,
modprobe, modinfo, dmesg, pgrep, pkill, sync, df, free, du, uname, date and timeout. Each stub that needs root refuses
(as the real command would) when it did not run under sudo. `date +%s` reads a fixed clock (T0), plus a jump once a
regular expression matches run.log (a check point is then due); `timeout` runs the real one, with a cap of one second
when its command matches STUB_CAP_RE (a step overrunning its cap), and answers the readiness connect to the guest
itself. No AWS, no SSH, no board, no apt, docker, modprobe or QEMU of this machine.

SDV PHASE 7 WP3b. Setup stages each rec-*.tar by the log its manifest line names (vss_setup.py
log; a CARLA recording's carla.log), refusing a tar whose named log is missing or whose line pairs a generator with
another log (the stack's one rule, bundle.py's log_name_of, held equal whatever the form of the line's path), and its
rules facts carry the profile list the console's `vss rules:` lines agree on. The suite takes
PLAN=carla, v2's units and compares over the CARLA pair (the plans' table held equal to bundle.py's), and refuses it at
its preflight unless each of the pair's own logs is staged and setup's recorded profiles list the pair's profile; v1 and v2
read neither (their runs are the reference commits' call for call and file for file, setup.json's new fact aside).

Does not demonstrate: anything about the instance -- Docker on jammy, the A72, the guest, the kernel's real log lines.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import ast
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
G = os.path.join(REPO, "orin-native", "gpu-concurrency")
HARNESS = os.path.join(G, "run-vss-setup.sh")
LIB = os.path.join(G, "lib-vss-deadline.sh")
TOOL = os.path.join(G, "vss_setup.py")
CAPTURE = os.path.join(REPO, "scripts", "aws", "capture.py")
ATTRIBUTION = os.path.join(REPO, "sdv", "stack", "attribution.py")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32",
                                reason="the harness runs on Linux; its stubs need bash and coreutils' timeout")

STEPS = ["preflight", "net-before", "guest", "docker", "after-docker", "vcan", "load", "pulls", "venv", "stage", "probes",
         "30min-rule", "close"]
T0 = 1800000000                        # the stub clock's epoch second
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GUEST = "192.168.100.10"
RULES = b"monitor: vss rules: kind 4, catalog 0x4D68EA68 (vss 6.0), age_max 300 ms, profiles 1 2"
BANNER = b"monitor: service monitor listening on :7160 (frame=64 bytes, conf_min=60%), liveness deadline 500 ms"
# latency_probe.py's own fields, and the stand-in's values for them: none may reach anything the harness writes
LATENCY_FIELD = re.compile(r'(?<![A-Za-z0-9_])(?:min|max|mean|p50|p90|p99|p999)(?:_ms)?(?:=|":)|p99\.9=')
LATENCY_VALUES = ("7.654", "7.754", "7.854", "7.954", "8.054", "8.154", "7.704")
SENTINELS = ("RAW-DOCKER-INFO-SENTINEL", "RAW-DOCKER-VERSION-SENTINEL", "RAW-INSPECT-SENTINEL", "RAW-MODINFO-SENTINEL",
             "RAW-KERNEL-LOG-SENTINEL", "sig_key")
UPSTREAM = ("kuksa-can-provider", "kuksa-csv-provider", "kuksa-databroker", "kuksa-mock-provider")
PROBED = ("bridge", "hard-brake-hazard", "host-venv", "kuksa-can-provider", "kuksa-csv-provider", "kuksa-databroker",
          "kuksa-csv-provider-recorder", "kuksa-mock-provider")

# --- the stubs ---------------------------------------------------------------------------------------------------

_LIB = r'''# the stubs' shared part (sourced)
stub_log() {
	local n="$1"; shift
	printf '%s\t%s\t%s\n' "$n" "${STUB_VIA_SUDO:-0}" "$*" >> "$STUB_DIR/calls.log"
	if [ -n "${STUB_SLEEP_ON:-}" ] && printf '%s %s' "$n" "$*" | grep -qE "$STUB_SLEEP_ON"; then sleep "${STUB_SLEEP_S:-10}"; fi
}
st() { [ -e "$STUB_DIR/state/$1" ]; }
st_set() { mkdir -p "$STUB_DIR/state"; : > "$STUB_DIR/state/$1"; }
st_rm() { rm -f "$STUB_DIR/state/$1"; }
root_or() { [ "${STUB_VIA_SUDO:-0}" = 1 ] && return 0; echo "$1" >&2; exit "${2:-1}"; }
kernel_line() {
	mkdir -p "$STUB_DIR/state"
	echo "[  123.456789] $1[4242]: undefined instruction: pc=0000ffff8a2b3c4d" >> "$STUB_DIR/state/kernel-lines"
}
real() { PATH="$STUB_REAL_PATH" command -v "$1"; }
'''

_STUBS = {
    "sudo": r'''stub_log sudo "$@"
if [ "${1:-}" != -n ]; then echo "sudo: a terminal is required to read the password" >&2; exit 1; fi
shift
args=()
for a in "$@"; do case "$a" in /etc/docker|/etc/docker/*) args+=("$STUB_DIR/root$a") ;; *) args+=("$a") ;; esac; done
if [ -n "${STUB_SUDO_FAIL:-}" ] && printf '%s' "${args[*]}" | grep -qE "$STUB_SUDO_FAIL"; then
	echo "sudo: refused (the stub's STUB_SUDO_FAIL)" >&2; exit 1
fi
export STUB_VIA_SUDO=1
exec "${args[@]}"
''',
    "apt-get": r'''stub_log apt-get "$@"
root_or "E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)" 100
case "$*" in
	*update*) echo "Reading package lists..."; exit "${STUB_APT_UPDATE_RC:-0}" ;;
	*install*docker.io*)
		[ "${STUB_DOCKER_INSTALL_RC:-0}" = 0 ] || { echo "E: Sub-process /usr/bin/dpkg returned an error code (1)"; exit "$STUB_DOCKER_INSTALL_RC"; }
		st_set docker; st_set br_netfilter
		echo "Setting up docker.io (29.1.3-0ubuntu3~22.04.2) ..." ;;
	*install*linux-modules-extra-*)
		[ "${STUB_MODX_INSTALL_RC:-0}" = 0 ] || { echo "E: Unable to locate package"; exit "$STUB_MODX_INSTALL_RC"; }
		st_set modx
		echo "Setting up linux-modules-extra-6.8.0-1063-aws (6.8.0-1063.69~22.04.1) ..." ;;
	*) echo "apt-get stub: $*" >&2; exit 100 ;;
esac
''',
    "apt-cache": r'''stub_log apt-cache "$@"
block() {
	local inst="(none)"
	{ [ "$1" = docker.io ] && st docker; } && inst="$2"
	{ [ "$1" = containerd ] && st docker; } && inst="$2"
	echo "$1:"; echo "  Installed: $inst"; echo "  Candidate: $2"; echo "  Version table:"
	[ "$2" = "(none)" ] && return 0
	echo "     $2 500"; echo "        500 http://ports.ubuntu.com/ubuntu-ports jammy-updates/universe arm64 Packages"
}
[ "$1" = policy ] || exit 100
shift
for p in "$@"; do
	case "$p" in
		docker.io) block docker.io "${STUB_DOCKER_CANDIDATE:-29.1.3-0ubuntu3~22.04.2}" ;;
		containerd) block containerd "1.7.28-0ubuntu1~22.04.1" ;;
		linux-modules-extra-*) block "$p" "${STUB_MODX_CANDIDATE:-6.8.0-1063.69~22.04.1}" ;;
		*) block "$p" "(none)" ;;
	esac
done
''',
    "dpkg-query": r'''stub_log dpkg-query "$@"
printf 'containerd\t1.7.28-0ubuntu1~22.04.1\ndocker.io\t29.1.3-0ubuntu3~22.04.2\n'
''',
    "usermod": r'''stub_log usermod "$@"
root_or "usermod: Permission denied." 1
''',
    # the group database's view of one login (`id -nG USER`, what the Orin mode records before its usermod); any other
    # id call is the real one, unlogged
    "id": r'''if [ "${1:-}" = -nG ] && [ "$#" = 2 ]; then
	stub_log id "$@"
	printf '%s\n' "${STUB_GROUPS_DB-ubuntu adm sudo kvm}"; exit 0
fi
exec "$(real id)" "$@"
''',
    "docker": r'''stub_log docker "$@"
root_or "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" 1
up() { st docker || { echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 1; }; }
case "$1" in
version) up
	if [ "$*" = "version -f {{.Server.Version}}" ]; then printf '%s\n' "${STUB_DOCKER_SERVER-29.1.3}"; else echo "RAW-DOCKER-VERSION-SENTINEL"; fi ;;
info) up
	case "$*" in
		"info -f {{json .DriverStatus}}") printf '%s\n' "${STUB_DOCKER_DRIVER_STATUS-[[\"driver-type\",\"io.containerd.snapshotter.v1\"]]}" ;;
		"info -f {{.Driver}}") echo overlayfs ;;
		*) echo "RAW-DOCKER-INFO-SENTINEL" ;;
	esac ;;
image|inspect) up
	[ "$1 ${2:-}" = "image inspect" ] && shift
	shift
	printf '[{"Id": "%s", "Os": "linux", "Architecture": "arm64", "RepoDigests": ["%s"], ' "$1" "$1"
	printf '"Config": {"Labels": {"RAW-INSPECT-SENTINEL": "1"}}}]\n' ;;
load) up
	[ "${STUB_DOCKER_LOAD_RC:-0}" = 0 ] || { echo "Error: the stub's load failure"; exit "$STUB_DOCKER_LOAD_RC"; }
	echo "Loaded image ID: sha256:1111111111111111111111111111111111111111111111111111111111111111"
	# something on the host rewrites daemon.json during setup (the Orin mode's close must fail on it)
	[ -z "${STUB_DAEMON_JSON_CHANGE:-}" ] || printf '%s\n' '{"runtimes": {}, "changed": true}' > "$STUB_DIR/root/etc/docker/daemon.json"
	st_set loaded ;;
pull) up
	if [ -n "${STUB_PULL_FAIL:-}" ] && printf '%s' "$2" | grep -qE "$STUB_PULL_FAIL"; then
		echo "Error response from daemon: the stub's pull failure" >&2; exit "${STUB_PULL_RC:-1}"
	fi
	printf '%s\n' "${2%@*}: Pulling from stub" "Digest: ${2#*@}" "Status: Downloaded newer image for $2" "$2" ;;
run) up; shift
	name=""
	while [ $# -gt 0 ]; do
		case "$1" in
			--rm|--read-only) shift ;;
			--name) name="$2"; shift 2 ;;
			--network|-e|-v|--entrypoint|--label|--platform|--user|--cpuset-cpus) shift 2 ;;
			-*) echo "docker stub: unknown run flag $1" >&2; exit 125 ;;
			*) shift; break ;;
		esac
	done
	key="${name#sdv-setup-probe-}"; key="${key//-/_}"
	if [ "$key" = kuksa_databroker ]; then
		case "${STUB_DATABROKER:-ok}" in
			sigill) kernel_line databroker; echo "Illegal instruction"; exit 132 ;;
			early) echo "Listening on 127.0.0.1:55555"; exit 0 ;;
			silent) echo "TLS is not enabled"      # runs, never listens, until the harness stops it
				for _ in $(seq 1 300); do st "stopped-$name" && break; sleep 0.1; done
				exit "${STUB_DATABROKER_STOP_RC:-0}" ;;
			*) echo "TLS is not enabled"; echo "Listening on 127.0.0.1:55555"
				for _ in $(seq 1 300); do st "stopped-$name" && break; sleep 0.1; done
				exit "${STUB_DATABROKER_STOP_RC:-0}" ;;
		esac
	fi
	v="STUB_PROBE_RC_$key"; rc="${!v:-0}"
	k="STUB_PROBE_KLINE_$key"       # a kernel line whatever the exit status
	echo "probe $key: output line one"; echo "probe $key: output line two"
	{ [ "$rc" != 132 ] && [ -z "${!k:-}" ]; } || kernel_line "$key"
	exit "$rc" ;;
stop) up; st_set "stopped-${*: -1}" ;;
rm) exit 0 ;;
ps) up
	[ -z "${STUB_DOCKER_PS_FAIL:-}" ] || { echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock" >&2; exit 1; }
	[ -z "${STUB_PROBE_LEFT:-}" ] || echo "c0ffee0000aa" ;;
*) echo "docker stub: $*" >&2; exit 2 ;;
esac
''',
    "iptables": r'''stub_log iptables "$@"
root_or "iptables v1.8.7 (nf_tables): Could not fetch rule set generation id: Permission denied (you must be root)" 4
[ -z "${STUB_IPTABLES_FAIL:-}" ] || { echo "iptables: the stub's failure" >&2; exit 4; }
[ "$*" = "-S FORWARD" ] || { echo "iptables stub: $*" >&2; exit 2; }
[ -z "${STUB_IPTABLES_WARN:-}" ] || echo "# Warning: iptables-legacy tables present, use iptables-legacy to see them" >&2
if st docker; then printf '%s\n' "-P FORWARD DROP" "-N DOCKER-USER" "-A FORWARD -j DOCKER-USER"; else echo "-P FORWARD ACCEPT"; fi
''',
    "iptables-save": r'''stub_log iptables-save "$@"
root_or "iptables-save v1.8.7 (nf_tables): Could not fetch rule set generation id: Permission denied (you must be root)" 1
[ -z "${STUB_IPTABLES_FAIL:-}" ] || { echo "iptables-save: the stub's failure" >&2; exit 1; }
st docker || exit 0
printf '%s\n' "# Generated by iptables-save" "*nat" ":PREROUTING ACCEPT [0:0]" "-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER" \
	"-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE" "COMMIT" "*filter" ":INPUT ACCEPT [0:0]" \
	"-A FORWARD -j DOCKER-USER" "-A FORWARD -j DOCKER-FORWARD" "-A DOCKER-USER -j RETURN" "COMMIT"
''',
    "sysctl": r'''stub_log sysctl "$@"
case "$1" in
	-n) [ "${2:-}" = debug.exception-trace ] && [ -z "${STUB_NO_EXCEPTION_TRACE:-}" ] || exit 255
		echo "${STUB_EXCEPTION_TRACE:-0}" ;;
	net.ipv4.ip_forward) if st docker; then echo "net.ipv4.ip_forward = 1"; else echo "net.ipv4.ip_forward = 0"; fi ;;
	net.bridge.bridge-nf-call-iptables)
		if st br_netfilter; then echo "net.bridge.bridge-nf-call-iptables = 1"
		else echo "sysctl: cannot stat /proc/sys/net/bridge/bridge-nf-call-iptables: No such file or directory" >&2; exit 255; fi ;;
	*) exit 255 ;;
esac
''',
    "lsmod": r'''stub_log lsmod "$@"
[ -z "${STUB_LSMOD_FAIL:-}" ] || { echo "lsmod: ERROR: could not open '/proc/modules': the stub's failure" >&2; exit 1; }
echo "Module                  Size  Used by"
if st br_netfilter; then echo "br_netfilter           32768  0"; echo "bridge                352256  1 br_netfilter"; fi
# the modules loaded before modprobe (STUB_LSMOD_BEFORE: names among can_raw, can and vcan), or all three after it
for m in can_raw can vcan; do
	if st modprobed || case " ${STUB_LSMOD_BEFORE:-} " in *" $m "*) true ;; *) false ;; esac; then
		case "$m" in
			can_raw) echo "can_raw                24576  0" ;;
			can) echo "can                    28672  1 can_raw" ;;
			vcan) echo "vcan                   12288  0" ;;
		esac
	fi
done
echo "nls_iso8859_1          12288  1"
''',
    # STUB_VCAN_IN_KERNEL: vcan, can and can_raw ship in the kernel's own package (R39); without it
    # they come only with linux-modules-extra (state modx, a1.metal's apt-get install)
    "modprobe": r'''stub_log modprobe "$@"
root_or "modprobe: ERROR: could not insert 'vcan': Operation not permitted" 1
{ st modx || [ -n "${STUB_VCAN_IN_KERNEL:-}" ]; } \
	|| { echo "modprobe: FATAL: Module vcan not found in directory /lib/modules/6.8.0-1063-aws" >&2; exit 1; }
[ "${STUB_MODPROBE_RC:-0}" = 0 ] || { echo "modprobe: ERROR: the stub's failure" >&2; exit "$STUB_MODPROBE_RC"; }
[ "$1" = -a ] && st_set modprobed
exit 0
''',
    "modinfo": r'''stub_log modinfo "$@"
{ st modx || [ -n "${STUB_VCAN_IN_KERNEL:-}" ]; } || { echo "modinfo: ERROR: Module vcan not found." >&2; exit 1; }
case "$*" in
	"-F filename vcan") echo "/lib/modules/6.8.0-1063-aws/kernel/drivers/net/can/vcan.ko.zst"
		[ -z "${STUB_MULTILINE:-}" ] || echo "/lib/modules/6.8.0-1063-aws/updates/vcan.ko" ;;
	"-F vermagic vcan") echo "6.8.0-1063-aws SMP mod_unload modversions aarch64" ;;
	*) echo "RAW-MODINFO-SENTINEL filename: /lib/modules/vcan.ko.zst"
		echo "sig_key:        1A:2B:3C:4D:5E:6F:70:81:92:A3:B4:C5:D6:E7:F8:09:1A:2B:3C:4D" ;;
esac
''',
    "dmesg": r'''stub_log dmesg "$@"
root_or "dmesg: read kernel buffer failed: Operation not permitted" 1
[ -z "${STUB_DMESG_FAIL:-}" ] || { echo "dmesg: read kernel buffer failed: Operation not permitted" >&2; exit 1; }
echo "[    0.000000] RAW-KERNEL-LOG-SENTINEL Booting Linux on physical CPU 0x0000000000 [0x410fd083]"
cat "$STUB_DIR/state/kernel-lines" 2>/dev/null || true
''',
    "pgrep": r'''stub_log pgrep "$@"
[ "$*" = "-x qemu-system-aar" ] || exit 1
st qemu && { echo 4242; exit 0; }
exit 1
''',
    "pkill": r'''stub_log pkill "$@"
st qemu || exit 1
[ -n "${STUB_QEMU_STUCK:-}" ] || st_rm qemu
exit 0
''',
    "sync": 'stub_log sync "$@"\n',
    "df": r'''stub_log df "$@"
printf '%s\n' "Filesystem      Size  Used Avail Use% Mounted on" "/dev/root        31G  9.1G   22G  30% /"
''',
    "free": r'''stub_log free "$@"
printf '%s\n' "               total        used        free      shared  buff/cache   available" \
	"Mem:          31800        2100       27000           2        2700       29300"
''',
    "du": r'''stub_log du "$@"
root_or "du: cannot read directory '/var/lib/docker': Permission denied" 1
printf '2.1G\t/var/lib/docker\n1.5G\t/var/lib/containerd\n'
''',
    "uname": r'''stub_log uname "$@"
[ "$*" = -r ] && { echo "6.8.0-1063-aws"; exit 0; }
exec "$(real uname)" "$@"
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
		[ "$n" -gt "${STUB_READY_FAILS:-0}" ] && exit 0
		exit 1 ;;
esac
if [ -n "${STUB_CAP_RE:-}" ] && printf '%s' "$*" | grep -qE "$STUB_CAP_RE"; then
	# A cap that fires: cut to STUB_CAP_S seconds; then the clock reads the cap's end, stop_at + 10 minutes, as it does
	# when a real cap fires (lib-vss-deadline.sh: vss_cap_fired takes 124 or 137 for the cap's only from then on).
	rc=0; "$(real timeout)" --kill-after=1s "${STUB_CAP_S:-1}" "$@" || rc=$?
	if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then echo $(( $(cat "$QNX_METAL_DEADLINE_FILE") - 1500 + 600 )) > "$STUB_DIR/clock"; fi
	exit "$rc"
fi
exec "$(real timeout)" "${opts[@]}" "$dur" "$@"
''',
}

# The guest's launch script, a stand-in: the console the test gives it, QEMU "running", and the real one's output.
_LAUNCH = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log launch "IFS_BIN=${IFS_BIN:?} DISK=${DISK:?} LOG=${LOG:?}"
mkdir -p "$(dirname "$LOG")"
[ -n "${STUB_NO_CONSOLE:-}" ] || cp "$STUB_DIR/console.bin" "$LOG"
st_set qemu
echo "ifs    : ${IFS_BIN}  sha256 0123456789abcdef..."
echo "console: ${LOG}"
echo "qemu pid: 4242"
echo "waiting for the guest to answer on 192.168.100.10 ..."
if [ "${STUB_BOOT:-ok}" = fail ]; then echo "ERROR: guest did not answer on :7100 within 60s. Console tail:" >&2; exit 1; fi
echo "guest up after 7s (monitor answering on :7100)"
'''

# latency_probe.py, a stand-in printing the real one's RESULT and summary lines with values no output may carry.
_LATENCY = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["STUB_DIR"], "calls.log"), "a") as f:
    f.write("latency_probe\t%s\t%s\n" % (os.environ.get("STUB_VIA_SUDO", "0"), " ".join(sys.argv[1:])))
rc = int(os.environ.get("STUB_SMOKE_RC", "0"))
bad = int(os.environ.get("STUB_SMOKE_BAD", "0"))
rej = int(os.environ.get("STUB_SMOKE_REJ", "0"))
if rc:
    print("FATAL connect: [Errno 113] No route to host")
    sys.exit(rc)
res = {"tag": "run", "proto": "tcp", "claim": "mnist", "n": 20, "warmup_discarded": 0, "bad": bad, "rejected_by_monitor": rej,
       "min_ms": 7.654321, "p50_ms": 7.754321, "p90_ms": 7.854321, "p99_ms": 7.954321, "p999_ms": 8.054321,
       "max_ms": 8.154321, "mean_ms": 7.704321, "interval_ms": 2.0}
print("RESULT %s" % json.dumps(res))
print("  tag=%-12s n=%-5d min=%.3f p50=%.3f p90=%.3f p99=%.3f p99.9=%.3f max=%.3f  bad=%d rej=%d"
      % (res["tag"], res["n"], res["min_ms"], res["p50_ms"], res["p90_ms"], res["p99_ms"], res["p999_ms"], res["max_ms"], bad, rej))
'''

# sdv/stack/bundle.py, a stand-in: its argv logged, docker run through --docker's prefix as the real one does, one record.
_BUNDLE = r'''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys
with open(os.path.join(os.environ["STUB_DIR"], "calls.log"), "a") as f:
    f.write("bundle.py\t%s\t%s\n" % (os.environ.get("STUB_VIA_SUDO", "0"), " ".join(sys.argv[1:])))
a = sys.argv[1:]
pre = shlex.split(a[a.index("--docker") + 1]) if "--docker" in a else ["docker"]


def dock(*x):
    return subprocess.run(pre + list(x), capture_output=True, text=True)


fail = os.environ.get("STUB_BUNDLE_FAIL", "")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "images.json")) as f:
    images = json.load(f)
rec = {"tool": "bundle.py " + a[0], "problems": []}
if a[0] == "verify":
    with open(os.path.join(a[a.index("--in") + 1], "bundle.json")) as f:
        rec["commit"] = json.load(f).get("commit")
    rec["loaded"] = "--loaded" in a
    if rec["loaded"]:
        v = dock("version", "-f", "{{.Server.Version}}")
        rec["docker"] = {"server": v.stdout.strip() or None, "driver_type": "io.containerd.snapshotter.v1"}
        pins = {n: s["arm64"]["id"] for n, s in images["local"].items()}
        pins["bridge"] = images["bridge"]["arm64"]["id"]
        rec["loaded_images"] = {}
        for n, pid in sorted(pins.items()):
            p = dock("image", "inspect", pid)
            if p.returncode:
                rec["problems"].append("%s: %s is not in the image store (%s)" % (n, pid, p.stderr.strip()))
            else:
                rec["loaded_images"][n] = {"id": pid, "platform": "linux/arm64"}
        if fail == "loaded":
            rec["problems"].append("bridge: image ID sha256:%s, pinned sha256:%s\nthe second line of a problem" % ("2" * 64, "3" * 64))
    elif fail == "verify":
        rec["problems"].append("sdv-gen.tar: sha256 %s, bundle.json says %s" % ("4" * 64, "5" * 64))
elif a[0] == "verify-upstream":
    rec["images"] = {}
    for n, u in sorted(images["upstream"].items()):
        ref = "%s@%s" % (u["repo"], u["index_digest"])
        p = dock("image", "inspect", ref)
        if p.returncode:
            rec["problems"].append("%s: %s is not in the image store (%s)" % (n, ref, p.stderr.strip()))
        else:
            rec["images"][n] = {"ref": ref, "id": u["index_digest"], "revision": u["revision"], "platform": "linux/arm64",
                                "in_repo_digests": True}
    if fail == "upstream":
        rec["problems"].append("kuksa-databroker: revision label 'x', pinned 'y'")
rec["ok"] = not rec["problems"]
print(json.dumps(rec, sort_keys=True))
sys.exit(0 if rec["ok"] else 1)
'''

# The python-build-standalone tarball's python3, a stand-in, and the venv's python it makes.
_PBS_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log pbs-python "$@"
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
	mkdir -p "$3/bin"; cp "$STUB_DIR/venv-python" "$3/bin/python"; chmod +x "$3/bin/python"
	exit "${STUB_VENV_CREATE_RC:-0}"
fi
[ "${1:-}" = --version ] && { echo "Python 3.12.15"; exit 0; }
exit 2
'''
_VENV_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log venv-python "$@"
case "${1:-}" in
	--version) echo "Python 3.12.15" ;;
	-m) case "$2 $3" in
		"pip install") echo "Collecting cantools==44.1.0"; echo "Successfully installed cantools-44.1.0 python-can-4.6.1"; exit "${STUB_PIP_RC:-0}" ;;
		"pip freeze") printf '%s\n' "argparse-addons==0.12.0" "bitstruct==8.23.0" "cantools==44.1.0" ;;
		*) exit 2 ;;
		esac ;;
	-c) rc="${STUB_VENV_PROBE_RC:-0}"; [ "$rc" != 132 ] || kernel_line python3; exit "$rc" ;;
	*) exit 2 ;;
esac
'''


def _console(lines=None):
    """A guest console as QEMU's serial log has it: NULs, CRLF, five `vss rules:` lines and the :7160 banner."""
    if lines is None:
        lines = [RULES] * 5
    body = [b"\0\0Startup complete", b"monitor: claim kinds: 0 mnist, 1 vlm, conf_min=60%"] + list(lines) + [
        BANNER, b"monitor: client done: seen=0 accepted=0 rejected=0"]
    return b"".join(x + b"\r\n" for x in body)


def _write(p, text, mode=None):
    os.makedirs(os.path.dirname(str(p)), exist_ok=True)
    with open(str(p), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode is not None:
        os.chmod(str(p), mode)


REC_LOGS = {"sigsim": "sigsim.log", "carla": "carla.log"}      # a recording's log by its generator, this file's spelling
CARLA_PAIR = ("20261019-carla-1", "20261019-carla-1-inj")          # the honest CARLA recording and its injected twin


def _rec_line(name, gen="", log=None, profile=None):
    """A recording's manifest line as its tool writes one, as far as the harnesses read it: its name, profile, the
    recording.path naming its log (log: another basename), its generator (by default carla for a name holding "-carla-")."""
    gen = gen or ("carla" if "-carla-" in name else "sigsim")
    log = log or REC_LOGS.get(gen, "sigsim.log")
    return (json.dumps({"name": name, "profile_id": profile if profile is not None else (3 if gen == "carla" else 1),
                        "recording": {"format": "candump-log", "path": "~/sdv-recordings/%s/%s" % (name, log), "sha256": "0" * 64},
                        "source": {"generator": gen, "params": {"seed": 1}}}) + "\n").encode()


def _tar(path, members, gz=False):
    """members: {arcname: (bytes, mode)}."""
    with tarfile.open(str(path), "w:gz" if gz else "w") as t:
        for name, (data, mode) in sorted(members.items()):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), mode
            t.addfile(ti, io.BytesIO(data))


class Rig:
    """W as setup, quiesce and the harness phase leave it for run-vss-setup.sh, the stubs, and the run."""

    def __init__(self, base):
        self.base = base
        self.w = base / "w"
        self.repo = self.w / "repo"
        self.g = self.repo / "orin-native" / "gpu-concurrency"
        self.stem = self.w / "rec" / "vss-setup"
        self.out = self.stem / "raw"
        self.status = self.stem / "status"
        self.runlog = self.stem / "run.log"
        self.vss_in = self.w / "in"
        self.vss_home = self.w / "sdv"
        self.stub = base / "stub"
        self.home = base / "home"
        self.tmp = base / "tmpdir"
        self.deadline = base / "deadline"
        for d in (self.g, self.stem, self.vss_in, self.home, self.tmp, self.w / "img", self.stub / "state"):
            os.makedirs(str(d), exist_ok=True)
        for f in (HARNESS, LIB, TOOL):
            shutil.copy(f, str(self.g / os.path.basename(f)))
        _write(self.g / "launch-qnx-kvm-bridged.sh", _LAUNCH)
        _write(self.g / "latency_probe.py", _LATENCY)
        stack = self.repo / "sdv" / "stack"
        _write(stack / "bundle.py", _BUNDLE)
        _write(stack / "step3.py", "# stand-in\n")
        shutil.copy(os.path.join(REPO, "sdv", "stack", "images.json"), str(stack / "images.json"))
        os.makedirs(str(self.repo / "sdv" / "sim"))
        for f in ("python-aarch64.json", "requirements.aarch64.lock"):
            shutil.copy(os.path.join(REPO, "sdv", "sim", f), str(self.repo / "sdv" / "sim" / f))
        (self.w / "img" / "ifs-vss.bin").write_bytes(b"ifs-vss stand-in")
        (self.w / "img" / "disk-qemu").write_bytes(b"disk stand-in")
        _write(self.w / "inputs.env", "IFS_NAME=ifs-vss.bin\nIFS_SHA256=%s\nREPO_COMMIT=%s\n" % ("a" * 64, COMMIT))
        _write(self.stem / "host-before.txt", "== a stand-in host-before\n")
        self._bundle()
        _write(self.stub / "_lib.sh", _LIB)
        for name, body in _STUBS.items():
            _write(self.stub / name, "#!/usr/bin/env bash\n. \"$STUB_DIR/_lib.sh\"\n" + body, 0o755)
        _write(self.stub / "venv-python", _VENV_PYTHON, 0o755)
        (self.stub / "console.bin").write_bytes(_console())
        _write(self.stub / "clock", str(T0))
        self.ahead(180 * 60)

    def _bundle(self, commit=COMMIT):
        with open(os.path.join(REPO, "sdv", "sim", "python-aarch64.json"), encoding="utf-8") as f:
            up = json.load(f)["upload_name"]
        _tar(self.vss_in / "sdv-gen.tar", {"gen/manifest.json": (b'{"stand-in": true}\n', 0o644),
                                           "gen/vss-databroker.json": (b"{}\n", 0o644)})
        for r in ("20260930-sigsim-1b", "20261002-sigsim-1b-inj4"):
            _tar(self.vss_in / ("rec-%s.tar" % r), {"%s/sigsim.log" % r: (b"(0.0) vcan0 123#00\n", 0o644),
                                                     "%s/manifest-line.json" % r: (_rec_line(r), 0o644)})
        dbc = b'VERSION ""\n'
        self.dbc_sha = hashlib.sha256(dbc).hexdigest()
        (self.vss_in / ("%s.dbc" % self.dbc_sha)).write_bytes(dbc)
        _tar(self.vss_in / up, {"python/bin/python3": (_PBS_PYTHON.encode(), 0o755)}, gz=True)
        (self.vss_in / "sdv-arm64-images.tar").write_bytes(b"an image tar stand-in")
        _write(self.vss_in / "bundle.json", json.dumps({"format": 1, "commit": commit, "members": []}))

    def ahead(self, seconds):
        """The deadline file: the stub clock's T0 plus this."""
        _write(self.deadline, str(T0 + seconds))

    def env(self, **cfg):
        drop = {k for k in os.environ if k.startswith(("STUB_", "VSS_", "SDV_"))} | {
            "PLAN", "K", "STATUS", "OUT", "IFS_BIN", "DISK", "W", "PYTHONDONTWRITEBYTECODE", "QNX_METAL_DEADLINE_FILE"}
        e = {k: v for k, v in os.environ.items() if k not in drop}
        img = str(self.w / "img" / "ifs-vss.bin")
        e.update(W=str(self.w), IFS_BIN=img, IMG_S=img, IMG_B=img, DISK=str(self.w / "img" / "disk-qemu"),
                 VPROBE=str(self.w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), OUT=str(self.out), CSTATE="shallow",
                 VSS_IN=str(self.vss_in), VSS_HOME=str(self.vss_home), STATUS=str(self.status),
                 QNX_METAL_DEADLINE_FILE=str(self.deadline), PATH=str(self.stub) + os.pathsep + os.environ["PATH"],
                 STUB_DIR=str(self.stub), STUB_REAL_PATH=os.environ["PATH"], STUB_JUMP_FILE=str(self.runlog),
                 HOME=str(self.home), TMPDIR=str(self.tmp))
        e.update({k: str(v) for k, v in cfg.items()})
        return e

    def run(self, timeout=180, **cfg):
        with open(str(self.runlog), "ab") as log:
            p = subprocess.run([BASH, str(self.g / "run-vss-setup.sh")], stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, cwd=str(self.g), env=self.env(**cfg), timeout=timeout)
        return Result(self, p.returncode)


class Result:
    def __init__(self, rig, rc):
        self.rig, self.rc = rig, rc
        self.before = {}             # the rig's files around the run (the module's whole run only)
        self.after = {}
        self.log = rig.runlog.read_text(encoding="utf-8", errors="replace")
        self.status = rig.status.read_text(encoding="utf-8").splitlines() if rig.status.exists() else []
        self.setup = self._json("setup.json")
        self.probes = self._json("probes.json")
        cl = rig.stub / "calls.log"
        self.calls = [tuple(ln.split("\t", 2)) for ln in cl.read_text(encoding="utf-8").splitlines()] if cl.exists() else []

    def _json(self, name):
        p = self.rig.out / name
        if not p.exists():
            return None
        with open(str(p), encoding="utf-8") as f:
            return json.load(f)

    def why(self):
        return "rc %s, status %s\n%s" % (self.rc, self.status, self.log[-4000:])

    def idx(self, name, pattern=""):
        """The index in calls.log of the first call of NAME whose arguments match PATTERN (-1 when none)."""
        for i, (n, _v, args) in enumerate(self.calls):
            if n == name and re.search(pattern, args):
                return i
        return -1

    def facts(self, *path):
        d = self.setup["facts"]
        for k in path:
            d = d[k]
        return d

    def outputs(self):
        """{relative path: text} of every file the harness wrote under OUT, its STATUS and run.log."""
        got = {"run.log": self.log, "status": "\n".join(self.status)}
        for root, _dirs, files in os.walk(str(self.rig.out)):
            for n in files:
                p = os.path.join(root, n)
                with open(p, "rb") as f:
                    got[os.path.relpath(p, str(self.rig.out)).replace(os.sep, "/")] = f.read().decode("utf-8", "replace")
        return got


def _strings(o, keys=True):
    if isinstance(o, dict):
        for k, v in o.items():
            if keys:
                yield k
            yield from _strings(v, keys)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v, keys)
    elif isinstance(o, str):
        yield o


def _operational(o, under=False):
    """Every (key, value) under an operational_s key."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "operational_s":
                if isinstance(v, dict):
                    yield from v.items()
                else:
                    yield (k, v)
            else:
                yield from _operational(v)
    elif isinstance(o, list):
        for v in o:
            yield from _operational(v)


@pytest.fixture(scope="module")
def done(tmp_path_factory):
    """One whole run with every stub answering as a1.metal should: the run most tests below read."""
    rig = Rig(tmp_path_factory.mktemp("done"))
    before = _snapshot(rig.base)
    res = rig.run()
    res.before = before
    res.after = _snapshot(rig.base)
    return res


def _snapshot(base):
    got = {}
    for root, _dirs, files in os.walk(str(base)):
        for n in files:
            p = os.path.join(root, n)
            with open(p, "rb") as f:
                got[os.path.relpath(p, str(base)).replace(os.sep, "/")] = hashlib.sha256(f.read()).hexdigest()
    return got


# --- a whole run ---------------------------------------------------------------------------------------------------

def test_a_whole_run_ends_done_with_its_setup_json_written_first(done):
    assert done.rc == 0 and done.status == ["status=DONE"], done.why()
    assert done.setup is not None and done.setup["status"] == "DONE" and done.setup["status_line"] == "status=DONE"
    assert [s["name"] for s in done.setup["steps"]] == STEPS
    assert all(s["outcome"] == "ok" and s["rc"] == 0 for s in done.setup["steps"]), done.setup["steps"]
    assert done.setup["not_run"] == [] and done.setup["skip_modes"] == [] and done.setup["skip"] == []
    for s in done.setup["steps"]:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s["start_utc"]) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s["end_utc"])
    # the result file is written whole before the status line: no temporary file is left beside it
    assert sorted(os.listdir(str(done.rig.out))) == sorted(
        ["apt.log", "df.txt", "docker-facts.txt", "guest", "net-after.txt", "net-before.txt", "probes.json", "setup.json",
         "smoke-1.txt", "smoke-2.txt", "venv.txt"])
    assert sorted(os.listdir(str(done.rig.out / "guest"))) == ["00-setup-console.log", "00-setup-launch.log"]
    assert done.log.index("step 13/13 close: end") < done.log.index("status=DONE")


def test_the_steps_run_in_the_order_prep_gives(done):
    r = done
    order = [
        r.idx("bundle.py", r"^verify --in \S+$"),                                    # 1 preflight
        r.idx("sysctl", "ip_forward"),                                              # 2 net-before
        r.idx("iptables", "-S FORWARD"),
        r.idx("iptables-save"),
        r.idx("launch"),                                                            # 3 the guest
        r.idx("timeout", "/dev/tcp/%s/7160" % re.escape(GUEST)),
        r.idx("latency_probe"),
        r.idx("sudo", r"^-n install .*/etc/docker/daemon\.json$"),                  # 4 Docker
        r.idx("apt-cache", r"policy docker\.io$"),
        r.idx("apt-get", r"install .*docker\.io"),
        r.idx("usermod"),
        r.idx("docker", "^version"),
        r.idx("docker", r"^info -f \{\{json"),
        r.idx("dpkg-query"),
    ]
    assert -1 not in order and order == sorted(order), order
    after_docker = r.idx("dpkg-query")
    rest = [
        next(i for i, c in enumerate(r.calls) if c[0] == "sysctl" and i > after_docker),     # 5 net-after
        next(i for i, c in enumerate(r.calls) if c[0] == "latency_probe" and i > after_docker),
        next(i for i, c in enumerate(r.calls) if c[0] == "sync" and i > after_docker),
        r.idx("pkill", "^-x qemu-system-aar$"),
        r.idx("apt-cache", "policy linux-modules-extra-6.8.0-1063-aws"),           # 6 vcan
        r.idx("apt-get", "install .*linux-modules-extra-6.8.0-1063-aws"),
        r.idx("modprobe"),
        r.idx("modinfo", "^-F filename vcan$"),
        r.idx("docker", "^load -i "),                                               # 7 load
        r.idx("bundle.py", "^verify --in .* --loaded"),
        r.idx("docker", "^pull "),                                                  # 8 pulls
        r.idx("bundle.py", "^verify-upstream"),
        r.idx("pbs-python", "^-m venv "),                                           # 9 the venv
        r.idx("venv-python", "^-m pip install"),
        r.idx("venv-python", "^-m pip freeze"),
        r.idx("dmesg"),                                                             # 11 the probes (10 runs no stub)
        r.idx("docker", "^run "),
        r.idx("venv-python", "^-c "),
        r.idx("du"),                                                                # 13 close
    ]
    assert -1 not in rest and rest == sorted(rest) and rest[0] > order[-1], rest
    # the venv exists and the staged files are where step 10 puts them before the probes (11) read the DBC
    assert (r.rig.vss_home / "gen" / "manifest.json").exists()
    assert (r.rig.vss_home / "recordings" / "20260930-sigsim-1b" / "sigsim.log").exists()
    assert (r.rig.vss_home / "recordings" / "20261002-sigsim-1b-inj4" / "sigsim.log").exists()
    assert (r.rig.vss_home / "cache" / "dbc" / ("%s.dbc" % r.rig.dbc_sha)).exists()
    assert (r.rig.vss_home / "venv" / "bin" / "python").exists() and (r.rig.vss_home / "py312" / "python" / "bin" / "python3").exists()
    assert [c[2] for c in r.calls if c[0] == "docker" and c[2].startswith("pull ")] == [
        "pull %s@%s" % (u["repo"], u["index_digest"]) for _n, u in sorted(_images()["upstream"].items())]


def _images():
    with open(os.path.join(REPO, "sdv", "stack", "images.json"), encoding="utf-8") as f:
        return json.load(f)


def test_docker_gets_its_daemon_json_first_and_is_installed_alone(done):
    r = done
    daemon = r.rig.stub / "root" / "etc" / "docker" / "daemon.json"
    with open(str(daemon), encoding="utf-8") as f:
        assert json.load(f) == {"features": {"containerd-snapshotter": True}}
    wrote = r.idx("sudo", r"^-n install .*/etc/docker/daemon\.json$")
    assert 0 <= wrote < r.idx("apt-get", r"install .*docker\.io"), "daemon.json before the package starts dockerd"
    assert r.idx("sysctl") < r.idx("apt-get", r"install .*docker\.io"), "net-before before the install"
    installs = [c[2] for c in r.calls if c[0] == "apt-get" and " install " in " %s " % c[2]]
    assert installs == ["install -y -qq docker.io", "install -y -qq linux-modules-extra-6.8.0-1063-aws"], installs
    assert r.idx("apt-cache", r"^policy docker\.io$") < r.idx("apt-get", r"install .*docker\.io"), "a candidate is checked first"
    assert [c[2] for c in r.calls if c[0] == "usermod"] == ["-aG docker %s" % _user()]
    d = r.facts("docker")
    assert d["server_version"] == "29.1.3" and d["server_major"] == 29 and d["driver_type"] == "io.containerd.snapshotter.v1"
    facts = (r.rig.out / "docker-facts.txt").read_text(encoding="utf-8")
    for want in ("docker.io\t29.1.3-0ubuntu3~22.04.2", "jammy-updates/universe arm64 Packages", "29.1.3", "overlayfs",
                 "io.containerd.snapshotter.v1", "linux-modules-extra-6.8.0-1063-aws"):
        assert want in facts, want
    apt = (r.rig.out / "apt.log").read_text(encoding="utf-8")
    assert "docker.io (29.1.3" in apt and "linux-modules-extra-6.8.0-1063-aws" in apt


def _user():
    return subprocess.run(["id", "-un"], capture_output=True, text=True, check=True).stdout.strip()


def test_every_docker_call_and_both_iptables_reads_run_under_sudo_n(done):
    r = done
    docker = [c for c in r.calls if c[0] == "docker"]
    assert docker and all(v == "1" for _n, v, _a in docker), [c for c in docker if c[1] != "1"]
    # bundle.py's own docker calls: through the prefix the harness gives it
    for c in r.calls:
        if c[0] == "bundle.py" and ("--loaded" in c[2] or c[2].startswith("verify-upstream")):
            assert "--docker sudo -n docker" in c[2], c
    assert any(c[2].startswith("image inspect") for c in docker), "bundle.py's inspects reached docker"
    for name in ("iptables", "iptables-save"):
        calls = [c for c in r.calls if c[0] == name]
        assert len(calls) == 2 and all(v == "1" for _n, v, _a in calls), calls
    assert all(c[2].startswith("-n ") for c in r.calls if c[0] == "sudo"), "sudo is always sudo -n"
    for name in ("apt-get", "usermod", "modprobe", "dmesg", "du"):
        assert all(v == "1" for n, v, _a in r.calls if n == name), name


def test_the_net_records_hold_each_value_and_exit_status_before_and_after_docker(done):
    before = (done.rig.out / "net-before.txt").read_text(encoding="utf-8")
    after = (done.rig.out / "net-after.txt").read_text(encoding="utf-8")
    assert "net.ipv4.ip_forward = 0" in before and "net.ipv4.ip_forward = 1" in after
    assert "-P FORWARD ACCEPT" in before and "-P FORWARD DROP" in after and "-N DOCKER-USER" not in after, "the policy line only"
    assert "-A FORWARD" not in after, "rule counts, never the rules"
    assert before.count("== exit ") == 5 and after.count("== exit ") == 5
    assert "FAILED-to-read" in before, "bridge-nf-call-iptables is absent before Docker: unreadable, never a value"
    assert "nat=2 filter=3" in after
    nb, na, nc = done.facts("net-before"), done.facts("net-after"), done.facts("net-change")
    assert nb["ip_forward_exit"] == 0 and nb["bridge_nf_call_iptables_exit"] == 255
    assert nb["br_netfilter"] == "0" and na["br_netfilter"] == "1"
    assert nc == {"ip_forward": "changed", "forward_policy": "changed", "br_netfilter": "changed",
                  "bridge_nf_call_iptables": "unreadable", "rule_counts": "changed"}


def test_the_guest_boots_with_c12b_lines_readiness_and_both_smokes(done):
    g = done.facts("guest")
    assert g["booted"] is True and g["launch_exit"] == 0
    assert g["c12b_lines"] == 5 and g["c12b_agree"] is True and g["c12b_ok"] is True
    assert g["catalog"] == "0x4D68EA68" and g["catalog_is_bridge_label"] is True and g["banner_7160_seen"] is True
    assert g["ready_7160"] is True and g["ready_7160_attempts"] == 1
    ready = [c[2] for c in done.calls if c[0] == "timeout" and "/dev/tcp/" in c[2]]
    assert ready == ["3 bash -c exec 3<>/dev/tcp/%s/7160 && exec 3>&-" % GUEST], "one connect-and-close, no bytes, no held descriptor"
    assert done.facts("smoke-1") == {"exit": 0, "result_line": True, "bad": 0, "rej": 0, "pass": True}
    assert done.facts("smoke-2") == {"exit": 0, "result_line": True, "bad": 0, "rej": 0, "pass": True}
    probes = [c[2] for c in done.calls if c[0] == "latency_probe"]
    assert probes == ["--host %s --port 7100 --n 20 --warmup 0" % GUEST] * 2
    launch = (done.rig.out / "guest" / "00-setup-launch.log").read_text(encoding="utf-8")
    assert "guest up (monitor answering on :7100)" in launch and "after 7s" not in launch, "the boot time only under operational_s"
    assert done.facts("after-docker")["guest_stopped"] is True and not (done.rig.stub / "state" / "qemu").exists()
    console = (done.rig.out / "guest" / "00-setup-console.log").read_bytes()
    assert console == _console(), "the raw console, as QEMU wrote it"


def test_vcan_and_the_probes_pass_on_a_host_that_has_them(done):
    v = done.facts("vcan")
    assert v["ok"] is True and v["modprobe_exit"] == 0
    assert [c[2] for c in done.calls if c[0] == "modprobe"] == ["-a vcan can can_raw"]
    assert v["lsmod"] == ["can_raw                24576  0", "can                    28672  1 can_raw", "vcan                   12288  0"]
    assert v["modinfo_filename"] == "/lib/modules/6.8.0-1063-aws/kernel/drivers/net/can/vcan.ko.zst"
    assert v["modinfo_vermagic"] == "6.8.0-1063-aws SMP mod_unload modversions aarch64"
    assert [c[2] for c in done.calls if c[0] == "modinfo"] == ["-F filename vcan", "-F vermagic vcan"]
    p = done.probes
    assert p is not None and sorted(p["probes"]) == sorted(PROBED) and p["skip"] == [], p
    for name, e in p["probes"].items():
        assert e["pass"] is True and e["result"] == "pass" and e["kernel_log"] == "read" and e["kernel_lines"] == [], (name, e)
    db = p["probes"]["kuksa-databroker"]
    assert db["listening"] is True and db["exited_before_stop"] is False and db["stop_exit"] == 0 and db["exit"] == 0
    runs = [c[2] for c in done.calls if c[0] == "docker" and c[2].startswith("run ")]
    assert len(runs) == 7 and all(" --rm --network none --name sdv-setup-probe-" in " " + x for x in runs), runs
    by = {re.search(r"--name sdv-setup-probe-(\S+)", x).group(1): x for x in runs}
    assert by["kuksa-databroker"].endswith("--vss /in/vss-databroker.json --address 127.0.0.1 --port 55555 --insecure")
    assert "-v %s/gen:/in:ro" % done.rig.vss_home in by["kuksa-databroker"]
    assert by["kuksa-can-provider"].endswith(" --help") and by["kuksa-csv-provider"].endswith(" --help")
    assert by["kuksa-mock-provider"].endswith("-c import numpy, scipy.linalg, grpc; numpy.linalg.inv(numpy.eye(4))")
    for local in ("hard-brake-hazard", "kuksa-csv-provider-recorder"):
        assert by[local].endswith("-c import kuksa_client, grpc, google.protobuf, websockets, wcwidth"), by[local]
        assert "--entrypoint python %s " % _images()["local"][local]["arm64"]["id"] in by[local]
    assert " --read-only %s check" % _images()["bridge"]["arm64"]["id"] in by["bridge"]
    assert [c[2] for c in done.calls if c[0] == "docker" and c[2].startswith("stop ")] == ["stop -t 5 sdv-setup-probe-kuksa-databroker"]
    venv = [c[2] for c in done.calls if c[0] == "venv-python" and c[2].startswith("-c ")]
    assert venv[0] == "-c import cantools, can, bitstruct, wrapt"
    assert venv[1].endswith(str(done.rig.vss_home / "cache" / "dbc" / ("%s.dbc" % done.rig.dbc_sha))) and "load_file" in venv[1]


def test_the_venv_and_the_close_are_recorded(done):
    venv = (done.rig.out / "venv.txt").read_text(encoding="utf-8")
    assert "Python 3.12.15" in venv and "cantools==44.1.0" in venv and "Successfully installed" in venv
    pip = [c[2] for c in done.calls if c[0] == "venv-python" and c[2].startswith("-m pip install")][0]
    assert "--require-hashes --no-deps" in pip and pip.endswith("-r %s" % (done.rig.repo / "sdv" / "sim" / "requirements.aarch64.lock"))
    df = (done.rig.out / "df.txt").read_text(encoding="utf-8")
    assert df.count("/dev/root") == 2 and "Mem:" in df and "/var/lib/docker" in df and "/var/lib/containerd" in df
    assert [c[2] for c in done.calls if c[0] == "du"] == ["-sh /var/lib/docker /var/lib/containerd"]
    assert done.facts("30min-rule") == {"fired": False, "operational_s": {"left_to_stop_at": 180 * 60 - 25 * 60}}
    pf = done.facts("preflight")
    assert pf["commit_match"] is True and pf["bundle_commit"] == COMMIT and pf["repo_commit"] == COMMIT
    assert pf["verify_ok"] is True and pf["verify_exit"] == 0
    assert done.facts("load")["verify_loaded_ok"] is True and done.facts("pulls")["verify_upstream_ok"] is True


def test_no_raw_docker_info_inspect_modinfo_or_kernel_log_is_written(done):
    for path, text in done.outputs().items():
        for s in SENTINELS:
            assert s not in text, (path, s)


def test_no_latency_field_of_latency_probe_reaches_any_output(done):
    outs = done.outputs()
    assert "smoke-1.txt" in outs and "smoke-2.txt" in outs
    for path, text in outs.items():
        assert not LATENCY_FIELD.search(text), (path, LATENCY_FIELD.search(text).group(0))
        for v in LATENCY_VALUES:
            assert v not in text, (path, v)
    smoke = outs["smoke-1.txt"]
    assert "exit 0" in smoke and "bad 0" in smoke and "rej 0" in smoke and "PASS" in smoke


def test_every_json_string_is_one_line_and_every_duration_sits_under_operational_s(done):
    for doc in (done.setup, done.probes):
        for s in _strings(doc):
            assert "\n" not in s and "\r" not in s, s
    ops = list(_operational(done.setup))
    assert ops and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for _k, v in ops), ops
    assert {k for k, _v in ops} == {"step", "boot", "left_to_stop_at"}
    for k in _keys(done.setup) | _keys(done.probes):
        assert not re.search(r"(_ms|_us|_ns|latency|rtt)$", k), k


def _keys(o):
    out = set()
    if isinstance(o, dict):
        for k, v in o.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(o, list):
        for v in o:
            out |= _keys(v)
    return out


def test_nothing_is_written_outside_out_status_vss_home_and_daemon_json(done):
    r = done.rig
    allowed = [os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") + "/" for p in (r.out, r.vss_home, r.stub)]
    allowed_files = {os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") for p in (r.status, r.runlog)}
    changed = sorted(p for p in set(done.after) | set(done.before) if done.after.get(p) != done.before.get(p))
    outside = [p for p in changed if p not in allowed_files and not any(p.startswith(a) for a in allowed)]
    assert outside == [], outside
    assert os.listdir(str(r.home)) == [] and os.listdir(str(r.tmp)) == []
    assert (r.stub / "root" / "etc" / "docker" / "daemon.json").exists(), "/etc/docker/daemon.json, through sudo -n"


def test_every_file_setup_writes_is_on_captures_vss_whitelist(done, tmp_path):
    """capture.py, run on a copy of the record (done touched, a redactor that changes nothing), leaves out none of it."""
    rec = tmp_path / "rec"
    shutil.copytree(str(done.rig.w / "rec"), str(rec))
    (rec / "vss-setup" / "done").write_text("")
    _write(tmp_path / "red.sh", "cat\n")
    p = subprocess.run([sys.executable, CAPTURE, str(rec), str(tmp_path / "pub"), str(tmp_path / "red.sh")],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "vss-setup: DONE (status=DONE, with raw/setup.json)" in p.stdout
    assert [ln for ln in p.stdout.splitlines() if ln.startswith("excluded:")] == ["excluded: vss-setup/done (not on the vss whitelist)"]
    published = {os.path.relpath(os.path.join(a, n), str(tmp_path / "pub")).replace(os.sep, "/")
                 for a, _d, fs in os.walk(str(tmp_path / "pub")) for n in fs}
    for root, _dirs, files in os.walk(str(done.rig.out)):
        for n in files:
            rel = "vss-setup/raw/" + os.path.relpath(os.path.join(root, n), str(done.rig.out)).replace(os.sep, "/")
            assert rel in published, rel


def test_the_close_repeats_the_guest_verdict_where_wait_run_shows_it(done):
    """The guest step's verdict is information here, and run-vss-suite.sh refuses a setup whose guest
    booted without it; the close says it, in the last 30 lines of run.log that wait-run prints."""
    tail = done.log.splitlines()[-30:]
    v = [ln for ln in tail if "the guest's verdict (step 3):" in ln]
    assert len(v) == 1 and "booted true, ready_7160 true, c12b_ok true, catalog_is_bridge_label true" in v[0], tail
    assert "smoke 1 PASS, smoke 2 PASS" in v[0], v
    assert any(ln.endswith("run-vss-suite.sh takes this setup's guest") for ln in tail), tail
    assert any(ln.endswith("the skip list: none") for ln in tail), tail


def test_a_done_setup_still_sweeps_the_guest_and_the_probe_containers(done):
    """The idempotent removals run before status=DONE too, and the record says what they found."""
    assert done.facts("stop") == {"guest_was_running": False, "probe_containers_list_exit": 0, "probe_containers_left": 0,
                                  "verified": True}
    rm = [c for c in done.calls if c[0] == "docker" and c[2].startswith("rm -f ")]
    assert [c[2] for c in rm] == ["rm -f sdv-setup-probe-%s" % n for n in (
        "kuksa-databroker", "kuksa-can-provider", "kuksa-csv-provider", "kuksa-mock-provider", "hard-brake-hazard",
        "kuksa-csv-provider-recorder", "bridge")] and all(c[1] == "1" for c in rm), rm
    assert done.idx("docker", r"^ps -aq --filter label=sdv\.setup\.probe=1$") > done.idx("du")


def test_the_probes_record_whether_the_kernel_logs_a_user_sigill(done):
    """arm64 logs a user-space SIGILL only with debug.exception-trace set; its value is recorded,
    read without root, so the record says whether the kernel-line check could fire."""
    assert done.facts("probes") == {"exception_trace": "0"}
    assert [c for c in done.calls if c[0] == "sysctl" and c[2] == "-n debug.exception-trace"] == [
        ("sysctl", "0", "-n debug.exception-trace")]


# --- the deadline: check points, the 30-minute rule, a cap ---------------------------------------------------------

@pytest.mark.parametrize("k", range(1, 14), ids=lambda k: "%d-%s" % (k, STEPS[k - 1]))
def test_a_check_point_past_stop_at_stops_cleanly_with_a_timeout(tmp_path, k):
    """Before each of the 13 steps: now >= stop_at stops the harness there, a TIMEOUT line, the steps not run listed,
    exit 0. Step 1's check point sees a deadline already within the margin; each later one, a clock that jumps once
    the step before it has ended (run.log's end line)."""
    rig = Rig(tmp_path)
    if k == 1:
        rig.ahead(25 * 60)                       # stop_at is now
        cfg = {}
    else:
        cfg = {"STUB_JUMP_RE": r"step %d/13 %s: end" % (k - 1, re.escape(STEPS[k - 2])), "STUB_JUMP_S": 180 * 60}
    r = rig.run(**cfg)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=%s reason=deadline" % STEPS[k - 1]], r.why()
    assert r.setup is not None and r.setup["status"] == "TIMEOUT" and r.setup["at"] == STEPS[k - 1] and r.setup["reason"] == "deadline"
    assert [s["name"] for s in r.setup["steps"]] == STEPS[:k - 1] and r.setup["not_run"] == STEPS[k - 1:]
    assert "not run: %s" % " ".join(STEPS[k - 1:]) in r.log
    if 3 < k <= 5:
        assert not (rig.stub / "state" / "qemu").exists() and r.facts("stop")["guest_was_running"] is True, "the guest stopped"
    assert r.idx("sync") >= 0, "a clean stop syncs"


@pytest.mark.parametrize("jump,fired", [(180 * 60 - 25 * 60 - 1799, True), (180 * 60 - 25 * 60 - 1800, False)],
                         ids=["1799-left", "1800-left"])
def test_the_30_minute_rule_stops_setup_with_under_thirty_minutes_left(tmp_path, jump, fired):
    """left = stop_at - now after the probes: under 1800 s is status=TIMEOUT at=30min-rule reason=30min-rule (the
    harness phase refuses the suite after it)."""
    rig = Rig(tmp_path)
    r = rig.run(STUB_JUMP_RE=r"step 11/13 probes: end", STUB_JUMP_S=jump)
    left = 180 * 60 - 25 * 60 - jump
    assert r.rc == 0, r.why()
    assert r.facts("30min-rule") == {"fired": fired, "operational_s": {"left_to_stop_at": left}}
    if fired:
        assert r.status == ["status=TIMEOUT at=30min-rule reason=30min-rule"], r.why()
        assert r.setup["status"] == "TIMEOUT" and r.setup["not_run"] == ["close"] and r.idx("du") == -1
    else:
        assert r.status == ["status=DONE"], r.why()


@pytest.mark.parametrize("step,cap,sleep_on", [
    ("guest", r"_step guest$", r"^latency_probe"),
    ("docker", r"_step docker$", r"^apt-get .*install .*docker\.io"),
    ("pulls", r"sudo -n docker pull .*mock-provider", r"^docker pull .*mock-provider"),      # one pull's own cap
    ("probes", r"_step probes$", r"^docker run "),
], ids=["guest", "docker", "one-pull", "probes"])
def test_a_step_overrunning_its_cap_ends_in_a_timeout_not_a_failed_run(tmp_path, step, cap, sleep_on):
    """The step's cap fires, or one pull's (the stub timeout gives it one second; the stub it runs sleeps ten):
    status=TIMEOUT at=<step> reason=step-timeout and exit 0, never the runner's status=FAILED rc=124 -- the documented
    call form."""
    rig = Rig(tmp_path)
    if step == "guest":
        _write(rig.g / "latency_probe.py", "import time\ntime.sleep(10)\n")
        r = rig.run(STUB_CAP_RE=cap)
    else:
        r = rig.run(STUB_CAP_RE=cap, STUB_SLEEP_ON=sleep_on, STUB_SLEEP_S=10)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=%s reason=step-timeout" % step], r.why()
    assert r.setup["status"] == "TIMEOUT" and r.setup["steps"][-1]["name"] == step
    assert r.setup["steps"][-1]["outcome"] == "step-timeout" and r.setup["steps"][-1]["rc"] in (124, 137)
    assert r.setup["not_run"] == STEPS[STEPS.index(step) + 1:]
    if step in ("guest", "docker"):
        assert not (rig.stub / "state" / "qemu").exists(), "the clean stop stopped the guest"
    if step == "probes":
        assert r.idx("docker", "^rm -f sdv-setup-probe-") >= 0, "the clean stop removed the probe containers"


def test_no_readable_deadline_is_a_real_failure_of_the_preflight_with_its_record(tmp_path):
    """No readable deadline: a real failure in the preflight, with setup.json and a FAILED line."""
    rig = Rig(tmp_path)
    os.remove(str(rig.deadline))
    r = rig.run()
    assert r.rc != 0 and r.status == ["status=FAILED at=preflight"], r.why()
    assert r.setup["status"] == "FAILED" and r.setup["at"] == "preflight" and r.setup["steps"] == []


# --- real failures -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,step,why", [
    ({"STUB_DOCKER_DRIVER_STATUS": '[["Backing Filesystem","extfs"],["Supports d_type","true"]]'}, "docker", "containerd"),
    ({"STUB_DOCKER_DRIVER_STATUS": '[["driver-type","io.containerd.content.v1"]]'}, "docker", "containerd"),
    ({"STUB_DOCKER_SERVER": "28.5.1"}, "docker", "major"),
    ({"STUB_DOCKER_SERVER": "290.1.0"}, "docker", "major"),
    ({"STUB_DOCKER_CANDIDATE": "(none)"}, "docker", "candidate"),
    ({"STUB_DOCKER_INSTALL_RC": "100"}, "docker", "apt-get install docker.io"),
    ({"STUB_BUNDLE_FAIL": "verify"}, "preflight", "bundle.py verify"),
    ({"STUB_DOCKER_LOAD_RC": "1"}, "load", "docker load"),
    ({"STUB_BUNDLE_FAIL": "loaded"}, "load", "verify --loaded"),
    ({"STUB_PULL_FAIL": "mock-provider"}, "pulls", "kuksa-mock-provider"),
    ({"STUB_BUNDLE_FAIL": "upstream"}, "pulls", "verify-upstream"),
    ({"STUB_PIP_RC": "1"}, "venv", "pip install"),
], ids=["store-classic", "store-other", "major-28", "major-290", "no-candidate", "install", "bundle", "load", "loaded",
        "pull", "upstream", "pip"])
def test_a_real_failure_ends_failed_with_its_record(tmp_path, cfg, step, why):
    rig = Rig(tmp_path)
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=%s" % step], r.why()
    assert r.setup["status"] == "FAILED" and r.setup["at"] == step and why in r.setup["reason"], r.setup["reason"]
    assert r.setup["steps"][-1] == dict(r.setup["steps"][-1], name=step, outcome="failed")
    assert r.setup["not_run"] == STEPS[STEPS.index(step) + 1:]
    if step == "docker":
        facts = (rig.out / "docker-facts.txt").read_text(encoding="utf-8") if (rig.out / "docker-facts.txt").exists() else ""
        if why in ("containerd", "major"):
            assert "driver-type" in facts and "server version" in facts, "docker-facts.txt is written before the check fails"
        assert not (rig.stub / "state" / "qemu").exists(), "the clean stop stopped the guest"
    for s in _strings(r.setup):
        assert "\n" not in s, s


@pytest.mark.parametrize("what", ["commit", "qemu", "no-sdv"])
def test_the_preflight_refuses(tmp_path, what):
    rig = Rig(tmp_path)
    if what == "commit":
        _write(rig.vss_in / "bundle.json", json.dumps({"format": 1, "commit": "f" * 40, "members": []}))
    elif what == "qemu":
        (rig.stub / "state" / "qemu").write_text("")
    else:
        shutil.rmtree(str(rig.repo / "sdv"))
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert r.setup["status"] == "FAILED" and r.idx("launch") == -1 and r.idx("apt-get") == -1
    assert r.idx("pkill") == -1, "the clean stop stops only a guest this harness booted"


# --- recorded, the harness carries on -----------------------------------------------------------------------------

def test_a_probe_that_exits_132_goes_into_the_skip_list_not_failed(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run(STUB_PROBE_RC_kuksa_can_provider=132)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"]["kuksa-can-provider"]
    assert e["exit"] == 132 and e["sigill"] is True and e["pass"] is False and "132" in e["result"]
    assert len(e["kernel_lines"]) == 1 and "undefined instruction" in e["kernel_lines"][0]
    assert r.setup["skip_modes"] == ["broker"]
    assert [(s["mode"], s["step"]) for s in r.setup["skip"]] == [("broker", "probes")] and "132" in r.setup["skip"][0]["reason"]
    assert r.probes["skip"] == r.setup["skip"]
    assert all(r.probes["probes"][n]["pass"] for n in PROBED if n != "kuksa-can-provider")


@pytest.mark.parametrize("name,rc,modes", [
    ("bridge", 139, ["broker", "can", "replay"]),
    ("hard-brake-hazard", 132, ["broker"]),
    ("kuksa-mock-provider", 137, ["broker"]),
])
def test_a_probe_killed_by_a_signal_is_recorded_and_skips_the_modes_that_need_its_image(tmp_path, name, rc, modes):
    rig = Rig(tmp_path)
    r = rig.run(**{"STUB_PROBE_RC_" + name.replace("-", "_"): rc})
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.probes["probes"][name]["exit"] == rc and r.probes["probes"][name]["pass"] is False
    assert r.setup["skip_modes"] == modes


def test_an_unknown_flags_exit_2_still_passes_its_probe(tmp_path):
    """An exit status below 128 (an unknown flag's 2) shows the binary ran its start-up."""
    r = Rig(tmp_path).run(STUB_PROBE_RC_kuksa_csv_provider=2)
    assert r.status == ["status=DONE"] and r.probes["probes"]["kuksa-csv-provider"]["pass"] is True
    assert r.setup["skip_modes"] == []


def test_the_host_venv_probe_that_exits_132_skips_every_mode(tmp_path):
    r = Rig(tmp_path).run(STUB_VENV_PROBE_RC=132)
    assert r.status == ["status=DONE"], r.why()
    assert r.probes["probes"]["host-venv"]["pass"] is False and r.setup["skip_modes"] == ["broker", "can", "replay"]


@pytest.mark.parametrize("how,listening,why", [("ok", True, ""), ("sigill", False, "132"), ("early", True, "before")])
def test_the_databroker_probe_passes_only_listening_until_the_harness_stops_it(tmp_path, how, listening, why):
    r = Rig(tmp_path).run(STUB_DATABROKER=how)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"]["kuksa-databroker"]
    assert e["listening"] is listening
    if how == "ok":
        assert e["pass"] is True and e["exited_before_stop"] is False and e["stop_exit"] == 0 and r.setup["skip_modes"] == []
    else:
        assert e["pass"] is False and why in e["result"] and r.setup["skip_modes"] == ["broker"], e
        assert e["exited_before_stop"] is True and r.idx("docker", "^stop ") == -1
        if how == "sigill":
            assert e["exit"] == 132 and e["sigill"] is True


def test_the_databroker_exit_status_after_the_stop_is_recorded_apart_from_its_verdict(tmp_path):
    """A databroker that a stop ends with 137 (a SIGKILL after the -t 5) still listened until the harness stopped it."""
    r = Rig(tmp_path).run(STUB_DATABROKER_STOP_RC=137)
    e = r.probes["probes"]["kuksa-databroker"]
    assert e["pass"] is True and e["exit"] == 137 and r.setup["skip_modes"] == [], e


@pytest.mark.parametrize("cfg,why", [
    ({"STUB_MODX_CANDIDATE": "(none)"}, "no candidate"),
    ({"STUB_MODX_INSTALL_RC": "100"}, "apt-get install"),
    ({"STUB_MODPROBE_RC": "1"}, "modprobe"),
], ids=["no-modules-extra", "install-fails", "modprobe-fails"])
def test_vcan_that_cannot_be_had_skips_broker_and_can_not_failed(tmp_path, cfg, why):
    rig = Rig(tmp_path)
    r = rig.run(**cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.setup["skip_modes"] == ["broker", "can"]
    assert {(s["mode"], s["step"]) for s in r.setup["skip"]} == {("broker", "vcan"), ("can", "vcan")}
    assert all(why in s["reason"] for s in r.setup["skip"]), r.setup["skip"]
    assert r.facts("vcan")["ok"] is False
    if why == "no candidate":
        assert [c for c in r.calls if c[0] == "apt-get" and "linux-modules-extra" in c[2]] == [] and r.idx("modprobe") == -1


@pytest.mark.parametrize("host", [None, "c7g-metal"], ids=["a1-metal", "c7g-metal"])
def test_vcan_with_no_candidate_comes_from_the_running_kernel_when_its_modules_have_it(tmp_path, host):
    """2026-10-17: apt with no candidate for linux-modules-extra-$(uname -r) (an AMI's kernel the archive has no extra
    package for, its own modules holding vcan). Vcan then comes from the running kernel as the Orin mode takes it: lsmod
    first, modinfo -F filename and -F vermagic, then sudo -n modprobe -a vcan can can_raw, with no apt-get install of
    the package and facts.vcan.source running-kernel; nothing goes into the skip list."""
    cfg = {"STUB_MODX_CANDIDATE": "(none)", "STUB_VCAN_IN_KERNEL": "1"}
    if host:
        cfg["VSS_HOST"] = host
    rig = Rig(tmp_path)
    r = rig.run(**cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.setup["skip_modes"] == [] and r.setup["skip"] == [], r.setup["skip"]
    v = r.facts("vcan")
    assert v["ok"] is True and v["source"] == "running-kernel" and v["candidate"] == "(none)", v
    assert v["package"] == "linux-modules-extra-6.8.0-1063-aws" and "install_exit" not in v, v
    assert v["modules_loaded_before"] == [] and v["modules_loaded_before_exit"] == 0 and v["modprobe_exit"] == 0, v
    assert v["modinfo_filename"] == "/lib/modules/6.8.0-1063-aws/kernel/drivers/net/can/vcan.ko.zst"
    assert v["modinfo_vermagic"] == "6.8.0-1063-aws SMP mod_unload modversions aarch64"
    assert v["lsmod"] == ["can_raw                24576  0", "can                    28672  1 can_raw", "vcan                   12288  0"]
    pol = r.idx("apt-cache", "^policy linux-modules-extra-6.8.0-1063-aws$")
    lsmod = [j for j, c in enumerate(r.calls) if c[0] == "lsmod" and j > pol]
    assert 0 <= pol < lsmod[0] < r.idx("modinfo") < r.idx("modprobe") < lsmod[-1], (pol, lsmod, r.idx("modprobe"))
    assert [c[2] for c in r.calls if c[0] == "modinfo"] == ["-F filename vcan", "-F vermagic vcan"]
    assert [(c[1], c[2]) for c in r.calls if c[0] == "modprobe"] == [("1", "-a vcan can can_raw")]
    assert [c for c in r.calls if c[0] == "apt-get" and "linux-modules-extra" in c[2]] == []
    assert "linux-modules-extra" not in (rig.out / "apt.log").read_text(encoding="utf-8")
    facts = (rig.out / "docker-facts.txt").read_text(encoding="utf-8")
    assert "== apt-cache policy linux-modules-extra-6.8.0-1063-aws" in facts and "Candidate: (none)" in facts, facts
    assert re.search(r"vcan: loaded from the kernel's own modules \(no candidate for "
                     r"linux-modules-extra-6\.8\.0-1063-aws; before: none\)", r.log), r.log[-2000:]


def test_vcan_with_a_candidate_writes_no_source_fact(done):
    """The package path is the reference harness's, file for file (A1.METAL UNCHANGED): only the running kernel's way says
    its source."""
    v = done.facts("vcan")
    assert v["ok"] is True and "source" not in v and "modules_loaded_before" not in v and v["install_exit"] == 0, v


@pytest.mark.parametrize("cfg,why,modprobed", [
    ({}, "modinfo -F filename vcan exited 1", False),
    ({"STUB_VCAN_IN_KERNEL": "1", "STUB_MODPROBE_RC": "1"}, "modprobe -a vcan can can_raw exited 1", True),
    ({"STUB_VCAN_IN_KERNEL": "1", "STUB_LSMOD_FAIL": "1"}, "lsmod could not be read before modprobe", False),
], ids=["module-absent", "modprobe-fails", "lsmod-unreadable"])
def test_vcan_with_no_candidate_that_the_running_kernel_cannot_give_skips_broker_and_can(tmp_path, cfg, why, modprobed):
    """Only when the running kernel's way fails as well do broker and can go into the skip list, the reason naming both:
    the package's missing candidate and why the kernel's modules did not do (no module, a failed modprobe, or an lsmod
    that cannot be read first, then no modprobe, as in the Orin mode)."""
    r = Rig(tmp_path).run(STUB_MODX_CANDIDATE="(none)", **cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.setup["skip_modes"] == ["broker", "can"]
    assert {(s["mode"], s["step"]) for s in r.setup["skip"]} == {("broker", "vcan"), ("can", "vcan")}
    for s in r.setup["skip"]:
        assert "no candidate for linux-modules-extra-6.8.0-1063-aws" in s["reason"] and why in s["reason"], s
    v = r.facts("vcan")
    assert v["ok"] is False and v["source"] == "running-kernel", v
    assert (r.idx("modprobe") >= 0) is modprobed
    assert [c for c in r.calls if c[0] == "apt-get" and "linux-modules-extra" in c[2]] == []
    assert "broker and can go into the skip list" in r.log


def test_a_failing_iptables_or_kernel_log_read_is_unreadable_never_a_pass(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run(STUB_IPTABLES_FAIL=1, STUB_DMESG_FAIL=1, STUB_NO_EXCEPTION_TRACE=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.facts("probes") == {"exception_trace": "unreadable (exit 255)"}
    for name in ("net-before.txt", "net-after.txt"):
        text = (rig.out / name).read_text(encoding="utf-8")
        assert "-P FORWARD" not in text and text.count("FAILED-to-read") >= 2, text
    for step in ("net-before", "net-after"):
        f = r.facts(step)
        assert f["forward_policy"].startswith("FAILED-to-read") and f["rule_counts"].startswith("FAILED-to-read"), f
        assert f["forward_policy_exit"] == 4 and f["rule_counts_exit"] == 1
    assert r.facts("net-change")["forward_policy"] == "unreadable" and r.facts("net-change")["rule_counts"] == "unreadable"
    for name, e in r.probes["probes"].items():
        assert e["kernel_log"] == "unreadable" and e["pass"] is False and "kernel log unreadable" in e["result"], (name, e)
    assert r.setup["skip_modes"] == ["broker", "can", "replay"]


def test_a_sudo_that_refuses_iptables_leaves_the_net_records_unreadable(tmp_path):
    """sudo -n that cannot run iptables (no passwordless rule for it, say): the read fails, and the record says so."""
    rig = Rig(tmp_path)
    r = rig.run(STUB_SUDO_FAIL=r"iptables")
    assert r.status == ["status=DONE"], r.why()
    assert r.facts("net-before")["forward_policy"].startswith("FAILED-to-read (exit 1)")


def test_a_guest_that_does_not_boot_is_recorded_and_stopped_and_setup_goes_on(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run(STUB_BOOT="fail")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.facts("guest")
    assert g["booted"] is False and g["launch_exit"] == 1 and g["guest_stopped"] is True
    assert not (rig.stub / "state" / "qemu").exists() and r.idx("latency_probe") == -1
    assert r.facts("smoke-1")["pass"] is False and r.facts("smoke-2")["pass"] is False
    assert "not run" in (rig.out / "smoke-1.txt").read_text(encoding="utf-8")
    assert r.idx("apt-get", r"install .*docker\.io") >= 0


def test_a_smoke_that_fails_and_a_slow_readiness_are_recorded(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run(STUB_SMOKE_BAD=3, STUB_READY_FAILS=2)
    assert r.status == ["status=DONE"], r.why()
    assert r.facts("smoke-1") == {"exit": 0, "result_line": True, "bad": 3, "rej": 0, "pass": False}
    assert r.facts("guest")["ready_7160"] is True and r.facts("guest")["ready_7160_attempts"] == 3
    assert "FAIL" in (rig.out / "smoke-1.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("lines,count,agree", [
    ([RULES] * 4 + [b"monitor: vss rumonitor: vss rules: kind 4, catalog 0x4D68EA68 (vss 6.0), age_max 300 ms, profiles 1 2"], 4, True),
    ([RULES] * 4 + [RULES.replace(b"0x4D68EA68", b"0x11111111")], 5, False),
    ([b"monitor: vss r", b"ules: kind 4"], 0, False),
], ids=["one-garbled", "one-disagrees", "none-parses"])
def test_c12b_counts_the_lines_that_parse_and_notes_rather_than_fails(tmp_path, lines, count, agree):
    """Every line that parses must agree; a count other than five is noted, not failed (banners interleave)."""
    rig = Rig(tmp_path)
    (rig.stub / "console.bin").write_bytes(_console(lines))
    r = rig.run()
    assert r.status == ["status=DONE"], r.why()
    g = r.facts("guest")
    assert g["c12b_lines"] == count and g["c12b_agree"] is agree and g["c12b_ok"] is (count >= 1 and agree)


def test_a_console_the_launch_never_wrote_is_recorded_not_failed(tmp_path):
    r = Rig(tmp_path).run(STUB_NO_CONSOLE=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.facts("guest")
    assert g["console_readable"] is False and g["c12b_lines"] == 0 and g["c12b_ok"] is False


def test_the_close_says_when_the_suite_will_refuse_the_setups_guest(tmp_path):
    """A guest whose `vss rules:` lines name another catalog than the bridge's label
    is information here (DONE), and the close says, where wait-run shows it, that the suite will refuse it."""
    rig = Rig(tmp_path)
    (rig.stub / "console.bin").write_bytes(_console([RULES.replace(b"0x4D68EA68", b"0xDEADBEEF")] * 5))
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.facts("guest")
    assert g["booted"] is True and g["c12b_ok"] is True and g["catalog"] == "0xDEADBEEF" and g["catalog_is_bridge_label"] is False
    tail = r.log.splitlines()[-30:]
    assert any("catalog_is_bridge_label false" in ln for ln in tail if "the guest's verdict (step 3):" in ln), tail
    assert any(ln.endswith("run-vss-suite.sh will refuse this setup: its guest booted, but catalog_is_bridge_label is false")
               for ln in tail), tail


def test_a_probe_container_left_at_done_is_recorded_and_said(tmp_path):
    """A probe container that the removals did not remove is in the DONE record and run.log."""
    r = Rig(tmp_path).run(STUB_PROBE_LEFT=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.facts("stop")["probe_containers_left"] == 1 and r.facts("stop")["probe_containers_list_exit"] == 0
    assert "1 probe container(s) labelled sdv.setup.probe=1 still listed after the removals" in r.log
    assert r.facts("stop")["verified"] is False, r.facts("stop")


# sudo as it relays a TERM it gets to the command it runs (sudo(8)); and docker whose run of the can-provider's probe
# ignores TERM, as a container's PID 1 with no handler does, until the probe's container is removed (docker rm -f).
_RELAY_SUDO = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log sudo "$@"
[ "${1:-}" = -n ] || { echo "sudo: a terminal is required" >&2; exit 1; }
shift
args=(); for a in "$@"; do case "$a" in /etc/docker|/etc/docker/*) args+=("$STUB_DIR/root$a") ;; *) args+=("$a") ;; esac; done
export STUB_VIA_SUDO=1
"${args[@]}" & child=$!
trap 'kill -TERM "$child" 2>/dev/null' TERM
rc=0; wait "$child" || rc=$?
while kill -0 "$child" 2>/dev/null; do rc=0; wait "$child" || rc=$?; done
exit "$rc"
'''
_DEAF_DOCKER = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
case "$*" in
	"rm -f "*) for n in "${@:3}"; do st_set "removed-$n"; done ;;
	*"--name sdv-setup-probe-kuksa-can-provider "*) stub_log docker "$@"; trap '' TERM
		echo "the probe ignores TERM"; echo "$$" > "$STUB_DIR/state/deaf-pid"
		while ! st removed-sdv-setup-probe-kuksa-can-provider; do sleep 0.1; done
		exit 137 ;;
esac
exec "$STUB_DIR/docker.orig" "$@"
'''


def test_a_probe_that_ignores_term_is_ended_by_its_own_bound_not_the_steps_cap(tmp_path):
    """A probe whose container ignores TERM. Its bound (2 s in this copy of the harness)
    ends it by removing its container, so the probe fails on its bound and setup goes on to DONE; the step's own cap
    (20 s here) never fires. A bound by `timeout --foreground ... sudo` signals sudo alone: sudo relays TERM to the
    docker CLI, which passes it to the container and goes on waiting, and the step hangs until its cap."""
    rig = Rig(tmp_path)
    h = rig.g / "run-vss-setup.sh"
    text = h.read_text(encoding="utf-8")
    assert text.count("PROBE_BOUND_S=600\n") == 1
    _write(h, text.replace("PROBE_BOUND_S=600\n", "PROBE_BOUND_S=2\n"))
    (rig.stub / "docker").rename(rig.stub / "docker.orig")
    _write(rig.stub / "docker", _DEAF_DOCKER, 0o755)
    _write(rig.stub / "sudo", _RELAY_SUDO, 0o755)
    r = rig.run(STUB_CAP_RE=r"_step probes$", STUB_CAP_S=20)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"]["kuksa-can-provider"]
    assert e["pass"] is False and e["bound_fired"] is True and "no exit within the probe's bound" in e["result"], e
    assert r.setup["skip_modes"] == ["broker"] and [s["outcome"] for s in r.setup["steps"]] == ["ok"] * 13
    removed = r.idx("sudo", "^-n docker rm -f sdv-setup-probe-kuksa-can-provider$")
    assert 0 <= r.idx("docker", "^run .*--name sdv-setup-probe-kuksa-can-provider ") < removed
    pid = (rig.stub / "state" / "deaf-pid").read_text().strip()
    assert subprocess.run(["kill", "-0", pid], capture_output=True).returncode != 0, "the probe's process ended with its container"


# A sudo this user may not signal, as the kernel would answer (kill(2): EPERM) had sudo's front-end left the user's real
# uid. A shell function `kill`, sourced through BASH_ENV into every bash of the run (the harness, its steps, the stubs),
# answers EPERM for any pid whose command line is the stub sudo, and logs each such call to state/eperm.
_EPERM_KILL = r'''kill() {
	local a
	for a in "$@"; do
		case "$a" in -*) continue ;; esac
		if [ "$(tr '\0' '\n' < "/proc/$a/cmdline" 2>/dev/null | sed -n 2p)" = "$STUB_DIR/sudo" ]; then
			echo "bash: kill: ($a) - Operation not permitted" >&2
			mkdir -p "$STUB_DIR/state"; printf '%s\n' "$*" >> "$STUB_DIR/state/eperm"
			return 1
		fi
	done
	builtin kill "$@"
}
'''


def test_the_probes_never_signal_sudo_to_see_whether_it_still_runs(tmp_path):
    """Whether a probe's `sudo -n docker run` still runs is read from /proc, not by `kill -0` into sudo,
    which works only while sudo's front-end keeps this user's real uid (UNVERIFIED on jammy). Here every signal into
    sudo fails as EPERM: the deaf probe still ends on its own bound by its container's removal, the databroker probe
    still reaches Listening and is stopped, setup ends DONE, and no signal into sudo was ever attempted."""
    rig = Rig(tmp_path)
    h = rig.g / "run-vss-setup.sh"
    text = h.read_text(encoding="utf-8")
    assert text.count("PROBE_BOUND_S=600\n") == 1
    _write(h, text.replace("PROBE_BOUND_S=600\n", "PROBE_BOUND_S=2\n"))
    (rig.stub / "docker").rename(rig.stub / "docker.orig")
    _write(rig.stub / "docker", _DEAF_DOCKER, 0o755)
    _write(rig.stub / "sudo", _RELAY_SUDO, 0o755)
    shim = tmp_path / "eperm-kill.sh"
    _write(shim, _EPERM_KILL)
    r = rig.run(STUB_CAP_RE=r"_step probes$", STUB_CAP_S=20, BASH_ENV=str(shim))
    eperm = rig.stub / "state" / "eperm"
    tried = eperm.read_text().splitlines() if eperm.exists() else []
    assert r.rc == 0 and r.status == ["status=DONE"], (tried[:6], r.why())
    assert tried == [], tried
    e = r.probes["probes"]["kuksa-can-provider"]
    assert e["pass"] is False and e["bound_fired"] is True and "no exit within the probe's bound" in e["result"], e
    d = r.probes["probes"]["kuksa-databroker"]
    assert d["pass"] is True and d["listening"] is True and d["exited_before_stop"] is False and d["stop_exit"] == 0, d
    assert r.setup["skip_modes"] == ["broker"] and [s["outcome"] for s in r.setup["steps"]] == ["ok"] * 13
    # the shim was live in this run's bashes: a bash with it gets EPERM from a signal into the stub sudo
    p = subprocess.run([BASH, "-c", '"$STUB_DIR/sudo" -n sleep 5 & s=$!; sleep 0.5; rc=0; kill -0 "$s" || rc=$?; '
                        'echo "rc=$rc"; builtin kill "$s"; wait "$s" || true'],
                       capture_output=True, text=True, timeout=30, env=rig.env(BASH_ENV=str(shim)))
    assert p.stdout.split() == ["rc=1"] and "Operation not permitted" in p.stderr, (p.stdout, p.stderr)


def test_a_pull_that_exits_137_on_its_own_is_a_failed_pull_not_a_cap(tmp_path):
    """A pull's own 137 (an OOM kill), long before the cap's end, is a failed pull (a real
    failure), not a cap that fired."""
    r = Rig(tmp_path).run(STUB_PULL_FAIL="mock-provider", STUB_PULL_RC=137)
    assert r.rc == 1 and r.status == ["status=FAILED at=pulls"], r.why()
    assert "kuksa-mock-provider" in r.setup["reason"] and r.facts("pulls")["kuksa-mock-provider"]["exit"] == 137


def test_multi_line_output_never_becomes_a_multi_line_json_string(tmp_path):
    """Every string in setup.json and probes.json is one line: output the harness keeps that holds several lines (a
    second modinfo line, two kernel lines, a problem bundle.py prints over two lines) becomes an array of lines."""
    rig = Rig(tmp_path)
    (rig.stub / "state" / "kernel-lines").write_text("")
    r = rig.run(STUB_MULTILINE=1, STUB_PROBE_RC_kuksa_mock_provider=132, STUB_VENV_PROBE_RC=132)
    assert r.status == ["status=DONE"], r.why()
    for doc in (r.setup, r.probes):
        for s in _strings(doc):
            assert "\n" not in s and "\r" not in s, s
    assert r.facts("vcan")["modinfo_filename"] == ["/lib/modules/6.8.0-1063-aws/kernel/drivers/net/can/vcan.ko.zst",
                                                   "/lib/modules/6.8.0-1063-aws/updates/vcan.ko"]
    r2 = Rig(tmp_path / "loaded").run(STUB_BUNDLE_FAIL="loaded")
    assert r2.status == ["status=FAILED at=load"], r2.why()
    probs = r2.facts("load")["verify_loaded_problems"]
    assert "the second line of a problem" in probs, probs
    for s in _strings(r2.setup):
        assert "\n" not in s, s


# --- what a surviving verifier mutant or the plan sync left untested -------------------------------------------------

def _fast(rig, harness, old, new):
    """A design value shrunk in the rig's copy of a harness (the original text must occur once)."""
    h = rig.g / harness
    text = h.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    _write(h, text.replace(old, new))


def test_a_databroker_that_runs_but_never_listens_fails_its_probe(tmp_path):
    """Verifier mutant v02: a databroker that keeps running without printing its Listening line within LISTEN_BOUND_S
    (2 s in this copy of the harness) is stopped by the harness and fails its probe: never a silent pass."""
    rig = Rig(tmp_path)
    _fast(rig, "run-vss-setup.sh", "LISTEN_BOUND_S=60;", "LISTEN_BOUND_S=2;")
    r = rig.run(STUB_DATABROKER="silent")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"]["kuksa-databroker"]
    assert e["listening"] is False and e["exited_before_stop"] is False and e["stop_exit"] == 0, e
    assert e["pass"] is False and e["result"] == "no Listening line within the bound", e
    assert r.setup["skip_modes"] == ["broker"]
    assert r.idx("docker", "^stop -t 5 sdv-setup-probe-kuksa-databroker$") >= 0


@pytest.mark.parametrize("rc", [0, 2])
def test_a_kernel_undefined_instruction_line_fails_a_probe_whose_exit_is_below_128(tmp_path, rc):
    """Verifier mutant v03: a probe whose exit status would pass (0, or an unknown flag's 2) still fails when the kernel
    logged an `undefined instruction` line since it began; its image's modes go into the skip list."""
    r = Rig(tmp_path).run(STUB_PROBE_RC_kuksa_csv_provider=rc, STUB_PROBE_KLINE_kuksa_csv_provider=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"]["kuksa-csv-provider"]
    assert e["exit"] == rc and e["sigill"] is False and e["kernel_log"] == "read", e
    assert len(e["kernel_lines"]) == 1 and "undefined instruction" in e["kernel_lines"][0], e
    assert e["pass"] is False and e["result"] == "a kernel line matching 'undefined instruction' since the probe began", e
    assert r.setup["skip_modes"] == ["broker"]
    assert all(r.probes["probes"][n]["pass"] for n in PROBED if n != "kuksa-csv-provider")


@pytest.mark.parametrize("probe,rc,why,modes", [
    ("kuksa-csv-provider", 124, "exit 124: no exit within the probe's bound", ["broker"]),
    ("kuksa-csv-provider", 125, "exit 125: docker could not run the probe", ["broker"]),
    ("kuksa-csv-provider", 126, "exit 126: docker could not run the probe", ["broker"]),
    ("kuksa-csv-provider", 127, "exit 127: docker could not run the probe", ["broker"]),
    ("host-venv", 124, "exit 124: no exit within the probe's bound", ["broker", "can", "replay"]),
], ids=["docker-124", "docker-125", "docker-126", "docker-127", "venv-124"])
def test_a_probe_that_exits_124_to_127_fails_by_the_stricter_rule(tmp_path, probe, rc, why, modes):
    """Verifier mutant v16 (WP4's rule, stricter than "below 128 and never 132"): 124 is a probe's own bound
    (timeout's, for the host venv) and 125-127 docker's own failure to run it; each fails the probe, its image's modes go
    into the skip list, and setup ends DONE."""
    cfg = {"STUB_VENV_PROBE_RC": rc} if probe == "host-venv" else {"STUB_PROBE_RC_" + probe.replace("-", "_"): rc}
    r = Rig(tmp_path).run(**cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    e = r.probes["probes"][probe]
    assert e["exit"] == rc and e["pass"] is False and e["result"] == why and e["sigill"] is False, e
    assert r.setup["skip_modes"] == modes
    assert {s["reason"] for s in r.setup["skip"]} == {"%s: %s" % (probe, why)}, r.setup["skip"]


@pytest.mark.parametrize("case,why", [
    ("no-recording", "the bundle holds no recording"),
    ("two-dbcs", "the bundle holds 2 DBC files, not one"),
    ("dbc-hash", "not its name"),
    ("gen-exists", "VSS_HOME/gen exists already"),
    ("recording-exists", "VSS_HOME/recordings/20260930-sigsim-1b exists already"),
    ("dbc-exists", ".dbc exists already"),
], ids=["no-recording", "two-dbcs", "dbc-hash", "gen-exists", "recording-exists", "dbc-exists"])
def test_each_staging_refusal_ends_failed_at_stage(tmp_path, case, why):
    """Verifier mutant v11: every check of step 10 is a real failure: a bundle with no recording, a DBC count
    other than one, a DBC whose bytes do not hash to its name, and a target that exists already (never staged over)."""
    rig = Rig(tmp_path)
    dbc = rig.vss_in / ("%s.dbc" % rig.dbc_sha)
    if case == "no-recording":
        for t in rig.vss_in.glob("rec-*.tar"):
            os.remove(str(t))
    elif case == "two-dbcs":
        (rig.vss_in / ("%s.dbc" % ("ab" * 32))).write_bytes(b'VERSION "another"\n')
    elif case == "dbc-hash":
        os.rename(str(dbc), str(rig.vss_in / ("%s.dbc" % ("cd" * 32))))
    elif case == "gen-exists":
        os.makedirs(str(rig.vss_home / "gen"))
    elif case == "recording-exists":
        os.makedirs(str(rig.vss_home / "recordings" / "20260930-sigsim-1b"))
    else:
        os.makedirs(str(rig.vss_home / "cache" / "dbc"))
        shutil.copy(str(dbc), str(rig.vss_home / "cache" / "dbc" / dbc.name))
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert r.setup["status"] == "FAILED" and r.setup["at"] == "stage" and why in r.setup["reason"], r.setup["reason"]
    assert r.setup["steps"][-1]["name"] == "stage" and r.setup["steps"][-1]["outcome"] == "failed"
    assert r.setup["not_run"] == ["probes", "30min-rule", "close"]


def _carla_tar(rig, name, members=None, line=None):
    """rec-NAME.tar in the rig's bundle: its log (by default carla.log) and its manifest line (line: other bytes, or False
    for none), as bundle.py writes a CARLA recording's tar."""
    m = dict(members) if members is not None else {"%s/carla.log" % name: (b"(0.0) vcan0 123#00\n", 0o644)}
    if line is not False:
        m["%s/manifest-line.json" % name] = (line if line is not None else _rec_line(name), 0o644)
    _tar(rig.vss_in / ("rec-%s.tar" % name), m)


def test_setup_stages_each_tar_by_the_log_its_manifest_line_names(tmp_path):
    """SDV Phase 7 WP3b: a bundle carrying every plan's recordings, the CARLA pair's carla.log beside the
    sigsim pair's sigsim.log, is staged whole: each tar's log is the one its line names (vss_setup.py log)."""
    rig = Rig(tmp_path)
    for name in CARLA_PAIR:
        _carla_tar(rig, name)
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert sorted(r.facts("stage")["recordings"]) == sorted(["20260930-sigsim-1b", "20261002-sigsim-1b-inj4"] + list(CARLA_PAIR))
    for name in CARLA_PAIR:
        assert (rig.vss_home / "recordings" / name / "carla.log").is_file()
        assert not (rig.vss_home / "recordings" / name / "sigsim.log").exists()


@pytest.mark.parametrize("members, line, why", [
    ({"20261019-carla-1/sigsim.log": (b"(0.0) vcan0 123#00\n", 0o644)}, None, "rec-20261019-carla-1.tar holds no 20261019-carla-1/carla.log"),
    (None, _rec_line("20261019-carla-1", log="sigsim.log"), "'carla' with the log 'sigsim.log'"),
    (None, _rec_line("20261019-carla-1", gen="sigsim", log="carla.log"), "'sigsim' with the log 'carla.log'"),
    (None, False, "rec-20261019-carla-1.tar: 20261019-carla-1/manifest-line.json cannot be read"),
    (None, b"{not json\n", "rec-20261019-carla-1.tar: 20261019-carla-1/manifest-line.json is not a JSON object"),
], ids=["named-log-missing", "carla-names-sigsim-log", "sigsim-names-carla-log", "no-line", "line-not-json"])
def test_setup_refuses_a_tar_whose_named_log_is_missing_or_does_not_pair(tmp_path, members, line, why):
    rig = Rig(tmp_path)
    _carla_tar(rig, "20261019-carla-1", members, line)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=stage"], r.why()
    assert why in r.setup["reason"], r.setup["reason"]


def test_setup_records_the_vss_rules_profiles_with_its_rules_facts(done):
    """Setup's rules facts carry the profile list its console's `vss rules:` lines agree on, which the
    suite's PLAN=carla preflight reads (the console here lists profiles 1 2)."""
    assert done.facts("guest")["profiles"] == ["1", "2"] and done.facts("guest")["c12b_agree"] is True


@pytest.mark.parametrize("lines, profiles", [
    ([RULES] * 5, ["1", "2"]),
    ([RULES.replace(b"profiles 1 2", b"profiles 1 2 3")] * 5, ["1", "2", "3"]),
    ([RULES, RULES.replace(b"profiles 1 2", b"profiles 1 2 3")], []),           # lines that disagree: no list
    ([], []),
], ids=["ifs-vss", "ifs-vss-carla", "disagreeing", "none"])
def test_the_rules_reading_records_the_profile_list_its_lines_agree_on(tmp_path, lines, profiles):
    console = tmp_path / "console.log"
    console.write_bytes(_console(lines))
    facts = tmp_path / "facts"
    p = _tool("rules", "--console", str(console), "--images", os.path.join(REPO, "sdv", "stack", "images.json"), "--facts", str(facts))
    assert p.returncode == 0, p.stderr
    assert (facts / "profiles.lines").read_text(encoding="utf-8").splitlines() == profiles


@pytest.mark.parametrize("line, out, rc", [
    (_rec_line("20261019-carla-1"), "carla.log", 0),
    (_rec_line("20260930-sigsim-1b"), "sigsim.log", 0),
    (_rec_line("20261019-carla-1", log="sigsim.log"), "'carla' with the log 'sigsim.log'", 1),
    (_rec_line("x", gen="vtd"), "'vtd' with the log 'sigsim.log'", 1),
    (json.dumps({"name": "x", "source": {"generator": "carla"}}).encode(), "'carla' with the log None", 1),
], ids=["carla", "sigsim", "carla-sigsim-log", "another-generator", "no-path"])
def test_the_log_reading_prints_the_log_a_recordings_line_names_or_refuses_naming_both(tmp_path, line, out, rc):
    d = tmp_path / "rec"
    d.mkdir()
    (d / "manifest-line.json").write_bytes(line)
    p = _tool("log", "--dir", str(d))
    assert p.returncode == rc and out in p.stdout and len(p.stdout.splitlines()) == 1, (p.stdout, p.stderr)
    if rc == 0:
        assert p.stdout == out + "\n"


def _module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def test_the_harness_log_table_is_the_injectors():
    """One table; vss_setup.py (standard library only, Python 3.10) holds its own copy, held equal here to
    sdv/inject/inject.py's LOG_NAMES (the stack's copy, bundle.py's, is held by tests/test_sdv_stack.py)."""
    d = os.path.join(REPO, "sdv", "inject")
    if d not in sys.path:
        sys.path.insert(0, d)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        import inject
    finally:
        sys.dont_write_bytecode = saved
    assert _module(TOOL, "_vss_setup_for_test").LOG_NAMES == inject.LOG_NAMES


def test_setups_log_rule_is_the_bundles_whatever_the_form_of_the_path(tmp_path):
    """One rule for a line's log: setup's log reading accepts what sdv/stack/bundle.py's log_name_of (the
    stack's and step 3's) accepts, with the same name, and refuses what it refuses; neither reads the form of the path."""
    setup = _module(TOOL, "_vss_setup_for_test")
    bundle = _module(os.path.join(REPO, "sdv", "stack", "bundle.py"), "_bundle_for_vss_harness_test")
    forms = ["~/sdv-recordings/x/%s", "/home/u/rec/x/%s", "sdv-out/rec/x/%s", "%s", "/tmp/my rec/%s", "/home/u/sdv_recordings/x/%s",
             "../other/%s"]
    lines = [{"name": "x", "recording": {"path": form % log}, "source": {"generator": gen}}
             for form in forms for gen in ("sigsim", "carla", "vtd") for log in ("sigsim.log", "carla.log", "drive.log")]
    lines += [{"name": "x", "recording": {}, "source": {"generator": "sigsim"}}, {"name": "x", "source": {"generator": "carla"}}]
    taken = 0
    for i, line in enumerate(lines):
        d = tmp_path / str(i)
        d.mkdir()
        (d / "manifest-line.json").write_text(json.dumps(line), encoding="utf-8")
        got, why = setup.log_name(str(d))
        want, want_why = bundle.log_name_of(line)
        assert got == want, (line, got, why, want, want_why)
        taken += got is not None
    assert taken == 2 * len(forms)


def test_a_smoke_whose_monitor_rejected_a_frame_fails(tmp_path):
    """Verifier mutant v06: a smoke passes only with exit 0, a RESULT line, bad 0 and rej 0; a rej above 0 fails it."""
    rig = Rig(tmp_path)
    r = rig.run(STUB_SMOKE_REJ=2)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    for n in (1, 2):
        assert r.facts("smoke-%d" % n) == {"exit": 0, "result_line": True, "bad": 0, "rej": 2, "pass": False}
        text = (rig.out / ("smoke-%d.txt" % n)).read_text(encoding="utf-8")
        assert "rej 2" in text and "smoke %d: FAIL" % n in text, text


def test_a_warning_on_stderr_is_never_recorded_as_the_forward_policy(tmp_path):
    """A net item's value is read from its command's stdout alone; its stderr is kept apart. A warning printed on stderr
    before the rules is not the FORWARD policy: it goes into the net file as a `stderr:` line and into setup.json as
    <key>_stderr."""
    rig = Rig(tmp_path)
    r = rig.run(STUB_IPTABLES_WARN=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    warn = "# Warning: iptables-legacy tables present, use iptables-legacy to see them"
    for step, name, policy in (("net-before", "net-before.txt", "-P FORWARD ACCEPT"), ("net-after", "net-after.txt", "-P FORWARD DROP")):
        f = r.facts(step)
        assert f["forward_policy"] == policy, (step, "forward_policy", f["forward_policy"])
        assert f["forward_policy_exit"] == 0 and f.get("forward_policy_stderr") == warn, f
        lines = (rig.out / name).read_text(encoding="utf-8").splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith("== sudo -n iptables -S FORWARD"))
        assert lines[i + 1:i + 4] == [policy, "stderr: " + warn, "== exit 0"], lines[i:i + 4]
    assert r.facts("net-change")["forward_policy"] == "changed"


def test_a_qemu_that_outlives_its_kill_is_recorded_and_the_sweep_tries_again(tmp_path):
    """The stop's KILL fallback: a QEMU that the TERM leaves running gets `sudo -n pkill -KILL`; one that outlives that too
    (STUB_QEMU_STUCK) is recorded as not stopped and setup goes on; the sweep at DONE tries once more, and records the
    stop unverified. STOP_WAIT_S is 1 s in this copy of the harness."""
    rig = Rig(tmp_path)
    _fast(rig, "run-vss-setup.sh", "STOP_WAIT_S=10\n", "STOP_WAIT_S=1\n")
    r = rig.run(STUB_QEMU_STUCK=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.facts("after-docker")["guest_was_running"] is True and r.facts("after-docker")["guest_stopped"] is False
    assert [(c[1], c[2]) for c in r.calls if c[0] == "pkill"] == [("1", "-x qemu-system-aar"), ("1", "-KILL -x qemu-system-aar")] * 2
    stop = r.facts("stop")
    assert stop["guest_was_running"] is True and stop["guest_stopped"] is False, stop
    assert stop["verified"] is False and stop["unverified"] == ["QEMU still runs after a KILL"], stop
    tail = r.log.splitlines()[-30:]
    assert any(ln.endswith("the stop is unverified: QEMU still runs after a KILL") for ln in tail), tail


@pytest.mark.parametrize("cfg,why", [
    ({"STUB_DOCKER_PS_FAIL": 1}, "the probe containers could not be listed after the removals (docker ps exit 1)"),
    ({"STUB_PROBE_LEFT": 1}, "1 probe container(s) labelled sdv.setup.probe=1 still listed after the removals"),
], ids=["list-fails", "one-left"])
def test_a_setup_stop_that_cannot_show_the_probe_containers_gone_is_recorded_unverified(tmp_path, cfg, why):
    """A sweep whose `docker ps` fails, or still lists a probe container, is no verified clean stop, DONE included:
    facts.stop says verified false and why, and run.log says so where wait-run shows it."""
    r = Rig(tmp_path).run(**cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    stop = r.facts("stop")
    assert stop["verified"] is False and stop["unverified"] == [why], stop
    tail = r.log.splitlines()[-30:]
    assert any(ln.endswith("the stop is unverified: " + why) for ln in tail), tail


# --- the helper ----------------------------------------------------------------------------------------------------

def test_vss_setup_py_parses_as_python_3_10_and_takes_attributions_rules_pattern():
    """It runs on the instance's system python3 (jammy's 3.10), before any venv exists."""
    with open(TOOL, encoding="utf-8") as f:
        src = f.read()
    ast.parse(src, feature_version=(3, 10))
    for name in ("tomllib", "file_digest", "ExceptionGroup", "TaskGroup", "Self"):
        assert not re.search(r"\b%s\b" % name, src), name
    with open(ATTRIBUTION, encoding="utf-8") as f:
        m = re.search(r'_VSS_RULES = re\.compile\((r"[^"]+")\)', f.read())
    got = re.search(r'VSS_RULES = re\.compile\((r"[^"]+")\)', src)
    assert m is not None and got is not None and got.group(1) == m.group(1), "vss_setup.py's C12b pattern is attribution.py's"


def _tool(*args, stdin=""):
    return subprocess.run([sys.executable, TOOL] + list(args), input=stdin, capture_output=True, text=True, timeout=60)


def test_the_smoke_parser_prints_only_the_status_and_the_counts():
    res = {"bad": 1, "rejected_by_monitor": 2, "p50_ms": 7.754321, "min_ms": 7.654321}
    text = "RESULT %s\n  tag=run n=20 min=7.654 p50=7.754 max=8.154  bad=1 rej=2\n" % json.dumps(res)
    p = _tool("smoke", stdin=text)
    assert p.returncode == 0 and p.stdout.splitlines() == ["result_line yes", "bad 1", "rej 2"], p.stdout
    p = _tool("smoke", stdin="FATAL connect: refused\n")
    assert p.stdout.splitlines() == ["result_line no", "bad none", "rej none"]


def test_the_record_writer_splits_every_multi_line_string(tmp_path):
    work = tmp_path / "work"
    _write(work / "facts" / "x" / "a.s", "one\ntwo\r\nthree")
    _write(work / "facts" / "x" / "b.s", "single")
    _write(work / "facts" / "x" / "n" / "c.i", "7")
    _write(work / "facts" / "x" / "d.b", "true")
    _write(work / "facts" / "x" / "e.lines", "l1\nl2\n")
    _write(work / "steps.tsv", "1\tpreflight\t2026-10-03T00:00:00Z\t2026-10-03T00:00:01Z\t1\t0\tok\n")
    _write(work / "skip.tsv", "broker\tvcan\ta reason\n")
    out = tmp_path / "out" / "setup.json"
    os.makedirs(str(out.parent))
    p = _tool("record", "--work", str(work), "--out", str(out), "--status", "DONE", "--status-line", "status=DONE",
              "--at", "", "--reason", "", "--steps", "preflight net-before")
    assert p.returncode == 0, p.stderr
    with open(str(out), encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["facts"]["x"] == {"a": ["one", "two", "three"], "b": "single", "n": {"c": 7}, "d": True, "e": ["l1", "l2"]}
    assert doc["not_run"] == ["net-before"] and doc["skip_modes"] == ["broker"]
    assert doc["steps"] == [{"n": 1, "name": "preflight", "start_utc": "2026-10-03T00:00:00Z", "end_utc": "2026-10-03T00:00:01Z",
                             "operational_s": {"step": 1}, "rc": 0, "outcome": "ok"}]
    assert os.listdir(str(out.parent)) == ["setup.json"]


# =====================================================================================================================
# run-vss-suite.sh (plan Phase 3 WP5)
#
# SUITE RIG. The suite runs as the detached runner runs it, with the harness phase's environment (W, IFS_BIN, IMG_S,
# IMG_B, DISK, OUT, PLAN, VSS_IN, VSS_HOME, STATUS, VPROBE, CSTATE), from W/repo/orin-native/gpu-concurrency, stdout
# and stderr into the stem's run.log. W/rec/vss-setup is a finished setup (status=DONE, done, raw/setup.json with its
# skip list); VSS_HOME is what setup staged (gen, cache/dbc, recordings, a venv whose python is a stand-in that logs
# and runs this machine's python3). W/repo holds the real harness, deadline library, vss_suite.py and vss_setup.py, the
# real images.json and step3-runs.json, beside stand-ins for the launch script and sdv/stack/step3.py.
#
# The step3.py stand-in takes the real one's arguments with the real one's argparse shapes (--modes nargs="+" with its
# choices, the directories positional), refuses an existing --name as stack.new_run_dir does, refuses a guest console
# that fails the freshness gate and a recording of the other kind than the spec's, writes a run directory with the
# real one's file names, and logs each call (argv, the SDV_ environment, its working directory) to step3-calls.jsonl.
# The launch stand-in refuses a second QEMU as the real one does, and leaves QEMU "running" after a boot that failed.
#
# The guest's :7160 is a listener in this process (StubGuest), bound to 127.0.0.1: a client that closes inside its
# deadline leaves `client done: seen=0` on the console the launch last opened; one held past it leaves `client
# closed: no complete frame for N ms` first, as monitor.c does. The stub python3 sends the readiness probe there (its
# original argv, 192.168.100.10:7160, logged), or to a closed port while no QEMU "runs". Stubs first on PATH, as for
# setup: sudo, pgrep, pkill, sync, date, timeout (setup's), and id, docker and python3 (the suite's).
#
# Does not demonstrate: anything about the instance -- the guest, step 3 on the A72, Docker on jammy.
# =====================================================================================================================

SUITE = os.path.join(G, "run-vss-suite.sh")
SUITE_TOOL = os.path.join(G, "vss_suite.py")
STEP3_SRC = os.path.join(REPO, "sdv", "stack", "step3.py")
SIX = ["honest", "inject", "pause-tick", "pause-both", "injected-to-end", "injected-stop"]
RECORDING = {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"}


def _names(pairs):
    return ["%02d-%s-%s" % (i + 1, s, m) for i, (s, m) in enumerate(pairs)]


V1 = _names([("honest", "replay"), ("honest", "broker")])
V2_PAIRS = [(s, "broker") for s in SIX] + [(s, "replay") for s in SIX + ["injected-stop"]] + [(s, "can") for s in SIX]
V2 = _names(V2_PAIRS)
V2_COMPARES = ["20-compare-broker-replay", "21-compare-broker-replay-can"]
# setup.json's facts.guest as run-vss-setup.sh's step 3 leaves them for a guest that booted and passed
GUEST_OK = {"booted": True, "launch_exit": 0, "ready_7160": True, "ready_7160_attempts": 1, "c12b_lines": 5, "c12b_agree": True,
            "c12b_ok": True, "catalog": "0x4D68EA68", "catalog_is_bridge_label": True, "banner_7160_seen": True}


def _spec_kinds():
    with open(os.path.join(REPO, "sdv", "stack", "step3-runs.json"), encoding="utf-8") as f:
        return {k: v["recording"] for k, v in json.load(f)["specs"].items()}


_SUITE_STUBS = {
    "id": r'''if [ "$*" = -nG ]; then stub_log id "$@"; printf '%s\n' "${STUB_GROUPS-}"; exit 0; fi
exec "$(real id)" "$@"
''',
    "docker": r'''stub_log docker "$@"
if [ "${STUB_VIA_SUDO:-0}" != 1 ]; then
	case " ${STUB_GROUPS-} " in
		*" docker "*) ;;
		*) echo "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock" >&2; exit 1 ;;
	esac
fi
case "$*" in
	"ps -aq --filter label=sdv.stack.run")
		if [ -n "${STUB_DOCKER_PS_FAIL:-}" ]; then
			echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 1
		fi
		cut -d' ' -f1 "$STUB_DIR/state/containers" 2>/dev/null || true ;;
	"rm -f "*) shift 2      # by ID or by name: state/containers holds "ID NAME" lines
		[ -z "${STUB_DOCKER_RM_FAIL:-}" ] || { echo "Error response from daemon: the stub's removal failure" >&2; exit 1; }
		for id in "$@"; do
			{ awk -v x="$id" '$1 != x && $2 != x' "$STUB_DIR/state/containers" 2>/dev/null || true; } > "$STUB_DIR/state/containers.new"
			mv "$STUB_DIR/state/containers.new" "$STUB_DIR/state/containers"
		done ;;
	*) echo "docker stub: $*" >&2; exit 2 ;;
esac
''',
    "python3": r'''stub_log python3 "$@"
args=("$@")
if [ "${2:-}" = record ]; then      # the status file as it stands when suite.json is written
	cat "$STATUS" > "$STUB_DIR/state/status-at-record" 2>/dev/null || : > "$STUB_DIR/state/status-at-record"
fi
if [ "${2:-}" = ready ]; then
	port="${STUB_GUEST_PORT:?}"
	console=""
	for i in "${!args[@]}"; do [ "${args[$i]}" != --console ] || console="${args[$((i + 1))]}"; done
	dead="${STUB_READY_DEAD:-}"       # every boot's :7160 dead, or (STUB_READY_DEAD_RE) the boots whose console matches
	if [ -n "${STUB_READY_DEAD_RE:-}" ] && printf '%s' "$console" | grep -qE "$STUB_READY_DEAD_RE"; then dead=1; fi
	{ st qemu && [ -z "$dead" ]; } || port="${STUB_DEAD_PORT:?}"
	for i in "${!args[@]}"; do
		case "${args[$i]}" in
			--host) args[$((i + 1))]=127.0.0.1 ;;
			--port) args[$((i + 1))]="$port" ;;
			--tries) [ -z "${STUB_READY_TRIES:-}" ] || args[$((i + 1))]="$STUB_READY_TRIES" ;;
		esac
	done
fi
exec "$(real python3)" "${args[@]}"
''',
    # taskset -c LIST CMD...: CMD run, with STUB_TASKSET_CPUS=LIST in its environment (the step3.py stand-in records it);
    # nothing is pinned (the Orin mode's step-3 calls, ORIN RIG below)
    "taskset": r'''stub_log taskset "$@"
[ "${1:-}" = -c ] && [ -n "${2:-}" ] && [ "$#" -gt 2 ] || { echo "taskset stub: $*" >&2; exit 1; }
export STUB_TASKSET_CPUS="$2"
shift 2
exec "$@"
''',
}

# The guest's launch script, a stand-in for the suite: a second QEMU refused (as launch-qnx-kvm-bridged.sh:92-96 does),
# the console, QEMU "running", the real one's output; a boot that fails leaves QEMU running (as 186-190 do).
_SUITE_LAUNCH = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log launch "IFS_BIN=${IFS_BIN:?} DISK=${DISK:?} LOG=${LOG:?}"
if st qemu; then
	echo "ERROR: a qemu-system-aarch64 is already running. The measurement scripts" >&2
	echo "       pick the guest by process and cannot tell two apart. Stop it first." >&2
	exit 1
fi
mkdir -p "$(dirname "$LOG")"
printf '%s' "$LOG" > "$STUB_DIR/state/console-path"
cp "$STUB_DIR/console.bin" "$LOG"
st_set qemu
echo "ifs    : ${IFS_BIN}  sha256 0123456789abcdef..."
echo "console: ${LOG}"
echo "qemu pid: 4242"
echo "waiting for the guest to answer on 192.168.100.10 ..."
if [ -n "${STUB_BOOT_FAIL:-}" ] && printf '%s' "$LOG" | grep -qE "$STUB_BOOT_FAIL"; then
	echo "ERROR: guest did not answer on :7100 within 60s. Console tail:" >&2; exit 1
fi
echo "guest up after 7s (monitor answering on :7100)"
'''

_SUITE_VENV_PYTHON = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log venv-python "$@"
exec "$(real python3)" "$@"
'''

# sdv/stack/step3.py, a stand-in (SUITE RIG above).
_STEP3 = r'''#!/usr/bin/env python3
import argparse, datetime, glob, json, os, re, signal, sys, time
STUB = os.environ["STUB_DIR"]
MODES = ("broker", "can", "replay")
KIND = {"20260930-sigsim-1b": "honest", "20261002-sigsim-1b-inj4": "injected", "20261019-carla-1": "honest",
        "20261019-carla-1-inj": "injected"}
HERE = os.path.dirname(os.path.abspath(__file__))
ENV = ("SDV_HOST_ROLE", "SDV_GEN", "SDV_CACHE", "SDV_RUNS", "SDV_SIM_VENV", "SDV_RECORDING", "SDV_BRIDGE_IMAGE")
EXTRA = ("SDV_CONTAINER_CPUSET", "SDV_AFTER_START", "STUB_TASKSET_CPUS")     # the Orin mode's, each only when set
with open(os.path.join(STUB, "step3-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "env": {k: os.environ.get(k) for k in ENV}, "cwd": os.getcwd(),
                        "env_extra": {k: os.environ[k] for k in EXTRA if k in os.environ}}) + "\n")


def wj(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(doc, f, indent=1)


def new_dir(name):
    d = os.path.join(os.environ["SDV_RUNS"], "%s-%s" % (datetime.datetime.now().strftime("%Y%m%d"), name))
    if os.path.exists(d):
        sys.exit("step3.py: %s exists: pick another --name" % d)
    return d


def stale(path):
    with open(path, "rb") as f:
        text = f.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
    out = []
    if "LIVENESS" in text:
        out.append("a LIVENESS line")
    if "client closed:" in text:
        out.append("%d `client closed:` line(s)" % text.count("client closed:"))
    if any(int(s) > 0 for s in re.findall(r"client done: seen=(\d+)", text)):
        out.append("a `client done:` with seen above 0")
    return out


def hit(var, name):
    rx = os.environ.get(var, "")
    return bool(rx) and re.search(rx, name) is not None


def run(a):
    name = a.name or "step3-%s" % a.mode
    d = new_dir(name)
    if a.monitor == "guest":
        if len(a.spec) != 1 or a.repeat != 1:
            sys.exit("step3.py: guest mode refused: one spec, run once")
        problems = stale(a.guest_console)
        if problems:
            sys.exit("step3.py: guest mode refused: the guest console %s is not fresh: %s" % (a.guest_console, "; ".join(problems)))
    with open(os.path.join(HERE, "step3-runs.json")) as f:
        specs = json.load(f)["specs"]
    spec = a.spec[0]
    kind = KIND.get(os.path.basename(os.environ.get("SDV_RECORDING", "")))
    if specs[spec]["recording"] != kind:
        sys.exit("step3.py: spec %s needs an %s recording; SDV_RECORDING is %s" % (spec, specs[spec]["recording"], kind))
    os.makedirs(os.path.join(d, "in"))
    log = "carla.log" if "-carla-" in os.path.basename(os.environ.get("SDV_RECORDING", "")) else "sigsim.log"
    with open(os.path.join(d, "in", log), "w") as f:
        f.write("(0.0) vcan0 123#00\n")
    wj(os.path.join(d, "manifest.json"), {"host_role": os.environ.get("SDV_HOST_ROLE"), "name": name})
    wj(os.path.join(d, "ownership.json"), {"rows": []})
    print("prepared %s" % d, flush=True)
    if hit("STUB_STEP3_KILLED", name):           # a death of its own (an OOM kill): no cap takes part
        os.kill(os.getpid(), signal.SIGKILL)
    if hit("STUB_STEP3_NORESULT", name):         # returns after prepare, its run directory holding no result.json
        sys.exit("step3.py: the stand-in stopped after prepare: no result.json")
    if hit("STUB_STEP3_SLEEP", name):
        with open(os.path.join(STUB, "state", "containers"), "w") as f:
            f.write("c0ffee000001 sdv-stack-databroker\nc0ffee000002 sdv-stack-bridge\n")
        time.sleep(30)
    failed = hit("STUB_STEP3_FAIL", name)
    rid = "%s-%s-1" % (spec, a.mode)
    rd = os.path.join(d, rid)
    gates = {"reason_set": not failed, "console": True, "console_end": True, "c12b": True, "accounting": True}
    got = [["inject-nan", 24]] if spec == "inject" else []
    for n in ("plan.json", "bridge-script.json", "bridge-header.json", "listeners.json", "attribution.json"):
        wj(os.path.join(rd, n), {"stand-in": n})
    os.makedirs(os.path.join(rd, "bridge"))
    with open(os.path.join(rd, "bridge", "replies.jsonl"), "w") as f:
        f.write('{"event": "reply", "seq": 1}\n')
    with open(a.guest_console, "ab") as f:
        f.write(b"monitor: client done: seen=42 accepted=42 rejected=0\r\n")
    with open(a.guest_console, "rb") as f, open(os.path.join(rd, "guest-console.log"), "wb") as g:
        g.write(f.read().replace(b"\0", b"").replace(b"\r", b""))
    wj(os.path.join(rd, "result.json"), {"step3": 1, "run": rid, "spec": spec, "mode": a.mode, "ok": not failed, "gates": gates,
                                         "reason_set": {"got": got}, "recording": {"sha256": "%064x" % (1 if kind == "honest" else 2)},
                                         "c12b_lines": 5})
    wj(os.path.join(d, "step3.json"), {"mode": a.mode, "runs": [{"run": rid, "spec": spec, "ok": not failed, "gates": gates}]})
    print("%s: ok %s gates %s set %s" % (rid, not failed, json.dumps(gates, sort_keys=True), got), flush=True)
    return 1 if failed else 0


def compare(a):
    d = new_dir(a.name)
    if hit("STUB_STEP3_SLEEP", a.name):
        with open(os.path.join(STUB, "state", "containers"), "w") as f:
            f.write("c0ffee000003 sdv-stack-bridge\n")
        time.sleep(30)
    modes = list(dict.fromkeys(a.modes))
    results = []
    for x in a.dirs:
        for p in sorted(glob.glob(os.path.join(x, "*", "result.json"))):
            with open(p) as f:
                results.append(json.load(f))
    groups = {}
    for r in results:
        if r["mode"] in modes:
            groups.setdefault(r["spec"], []).append(r)
    out = []
    for spec, rs in sorted(groups.items()):
        have = {r["mode"] for r in rs}
        probs = ["no %s run" % m for m in modes if m not in have] + ["%s failed its own gates" % r["run"] for r in rs if not r["ok"]]
        out.append({"spec": spec, "ok": not probs, "problems": probs})
    ok = bool(out) and all(g["ok"] for g in out)
    wj(os.path.join(d, "compare.json"), {"ok": ok, "modes": modes, "left_out": [r["run"] for r in results if r["mode"] not in modes],
                                         "groups": out, "inputs": a.dirs})
    print(json.dumps({"ok": ok, "modes": modes}), flush=True)
    return 0 if ok else 1


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
p = sub.add_parser("run")
p.add_argument("--mode", choices=MODES, required=True)
p.add_argument("--spec", nargs="+", required=True)
p.add_argument("--repeat", type=int, default=1)
p.add_argument("--name", default=None)
p.add_argument("--images", choices=("build", "loaded"), default="build")
p.add_argument("--monitor", choices=("native", "guest"), default="native")
p.add_argument("--guest-host", default=None)
p.add_argument("--guest-console", default=None)
p.add_argument("--guest-image", default=None)
c = sub.add_parser("compare")
c.add_argument("--name", default="step3-compare")
c.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
c.add_argument("dirs", nargs="+")
args = ap.parse_args()
sys.exit(compare(args) if args.cmd == "compare" else run(args))
'''


class StubGuest:
    """The guest's :7160 for a client that sends nothing, as monitor.c answers one (SUITE RIG above)."""
    DEADLINE_S = 0.3

    def __init__(self, stub_dir):
        self.stub = stub_dir
        self.events = []
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.is_set():
            try:
                conn, _addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        conn.settimeout(self.DEADLINE_S)
        lines, outcome = [], "closed in time"
        try:
            if conn.recv(64):
                outcome = "sent bytes"
        except socket.timeout:
            outcome = "held past the deadline"
            lines.append(b"monitor: client closed: no complete frame for %d ms" % int(self.DEADLINE_S * 1000))
        except OSError:
            outcome = "reset"
        lines.append(b"monitor: client done: seen=0 accepted=0 rejected=0")
        conn.close()
        with self.lock:
            path = (self.stub / "state" / "console-path").read_text(encoding="utf-8")
            with open(path, "ab") as f:
                f.write(b"".join(x + b"\r\n" for x in lines))
            self.events.append((os.path.basename(path), outcome))

    def close(self):
        self.stopping.set()
        self.sock.close()
        self.thread.join(5)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class SuiteRig:
    """W as setup and the harness phase leave it for run-vss-suite.sh, the stubs, the stub guest, and the run."""

    def __init__(self, base, plan="v2", skip=()):
        self.base = base
        self.plan = plan
        self.w = base / "w"
        self.repo = self.w / "repo"
        self.g = self.repo / "orin-native" / "gpu-concurrency"
        self.stack = self.repo / "sdv" / "stack"
        self.stem = self.w / "rec" / "vss-suite"
        self.out = self.stem / "raw"
        self.status = self.stem / "status"
        self.runlog = self.stem / "run.log"
        self.setup = self.w / "rec" / "vss-setup"
        self.vss_home = self.w / "sdv"
        self.stub = base / "stub"
        self.home = base / "home"
        self.tmp = base / "tmpdir"
        self.deadline = base / "deadline"
        for d in (self.g, self.stack, self.stem, self.setup / "raw", self.home, self.tmp, self.w / "img", self.w / "in",
                  self.stub / "state"):
            os.makedirs(str(d), exist_ok=True)
        for f in (SUITE, LIB, SUITE_TOOL, TOOL):
            shutil.copy(f, str(self.g / os.path.basename(f)))
        _write(self.g / "launch-qnx-kvm-bridged.sh", _SUITE_LAUNCH)
        _write(self.stack / "step3.py", _STEP3)
        for f in ("images.json", "step3-runs.json"):
            shutil.copy(os.path.join(REPO, "sdv", "stack", f), str(self.stack / f))
        (self.w / "img" / "ifs-vss.bin").write_bytes(b"ifs-vss stand-in")
        (self.w / "img" / "disk-qemu").write_bytes(b"disk stand-in")
        _write(self.stem / "host-before.txt", "== a stand-in host-before\n")
        self.set_setup("status=DONE", skip=skip)
        for name in list(RECORDING.values()) + list(CARLA_PAIR):        # every plan's recordings, as setup stages a whole bundle
            _write(self.vss_home / "recordings" / name / REC_LOGS["carla" if "-carla-" in name else "sigsim"], "(0.0) vcan0 123#00\n")
            _write(self.vss_home / "recordings" / name / "manifest-line.json", _rec_line(name).decode())
        _write(self.vss_home / "gen" / "manifest.json", '{"stand-in": true}\n')
        dbc = b'VERSION ""\n'
        os.makedirs(str(self.vss_home / "cache" / "dbc"))
        (self.vss_home / "cache" / "dbc" / ("%s.dbc" % hashlib.sha256(dbc).hexdigest())).write_bytes(dbc)
        _write(self.vss_home / "venv" / "bin" / "python", _SUITE_VENV_PYTHON, 0o755)
        _write(self.stub / "_lib.sh", _LIB)
        for name in ("sudo", "pgrep", "pkill", "sync", "date", "timeout"):
            _write(self.stub / name, "#!/usr/bin/env bash\n. \"$STUB_DIR/_lib.sh\"\n" + _STUBS[name], 0o755)
        for name, body in _SUITE_STUBS.items():
            _write(self.stub / name, "#!/usr/bin/env bash\n. \"$STUB_DIR/_lib.sh\"\n" + body, 0o755)
        (self.stub / "console.bin").write_bytes(_console())
        _write(self.stub / "clock", str(T0))
        self.ahead(180 * 60)
        self.guest = StubGuest(self.stub)
        self.dead_port = _free_port()

    def set_setup(self, last, done=True, skip=(), guest=GUEST_OK, host_mode=None):
        """rec/vss-setup as the detached runner leaves a setup that ended with LAST; its setup.json with this skip list
        and this guest step's facts (None: no facts.guest at all), and the host mode an Orin-mode setup records (None:
        none, as an a1.metal setup writes it)."""
        _write(self.setup / "status", last + "\n")
        if done:
            _write(self.setup / "done", "")
        elif (self.setup / "done").exists():
            os.remove(str(self.setup / "done"))
        skip = sorted(skip)
        doc = {"format": 1, "harness": "run-vss-setup.sh", "status": last[len("status="):].split(" ")[0], "skip_modes": skip,
               "skip": [{"mode": m, "step": "probes", "reason": "a stand-in probe for %s did not pass" % m} for m in skip],
               "facts": {} if guest is None else {"guest": dict(guest)}}
        if host_mode is not None:
            doc["host_mode"] = host_mode
        _write(self.setup / "raw" / "setup.json", json.dumps(doc, indent=1))

    def ahead(self, seconds):
        _write(self.deadline, str(T0 + seconds))

    def env(self, **cfg):
        drop = {k for k in os.environ if k.startswith(("STUB_", "VSS_", "SDV_"))} | {
            "PLAN", "K", "STATUS", "OUT", "IFS_BIN", "DISK", "W", "PYTHONDONTWRITEBYTECODE", "QNX_METAL_DEADLINE_FILE"}
        e = {k: v for k, v in os.environ.items() if k not in drop}
        img = str(self.w / "img" / "ifs-vss.bin")
        e.update(W=str(self.w), IFS_BIN=img, IMG_S=img, IMG_B=img, DISK=str(self.w / "img" / "disk-qemu"),
                 VPROBE=str(self.w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), OUT=str(self.out), CSTATE="shallow",
                 PLAN=self.plan, VSS_IN=str(self.w / "in"), VSS_HOME=str(self.vss_home), STATUS=str(self.status),
                 QNX_METAL_DEADLINE_FILE=str(self.deadline), PATH=str(self.stub) + os.pathsep + os.environ["PATH"],
                 STUB_DIR=str(self.stub), STUB_REAL_PATH=os.environ["PATH"], STUB_JUMP_FILE=str(self.runlog),
                 STUB_GROUPS="ubuntu adm kvm docker", STUB_GUEST_PORT=str(self.guest.port), STUB_DEAD_PORT=str(self.dead_port),
                 HOME=str(self.home), TMPDIR=str(self.tmp))
        for k, v in cfg.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def run(self, timeout=300, **cfg):
        try:
            with open(str(self.runlog), "ab") as log:
                p = subprocess.run([BASH, str(self.g / "run-vss-suite.sh")], stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, cwd=str(self.g), env=self.env(**cfg), timeout=timeout)
        finally:
            self.guest.close()
        return SuiteResult(self, p.returncode)


class SuiteResult:
    def __init__(self, rig, rc):
        self.rig, self.rc = rig, rc
        self.before, self.after = {}, {}
        self.log = rig.runlog.read_text(encoding="utf-8", errors="replace")
        self.status = rig.status.read_text(encoding="utf-8").splitlines() if rig.status.exists() else []
        p = rig.out / "suite.json"
        self.suite = None
        if p.exists():
            with open(str(p), encoding="utf-8") as f:
                self.suite = json.load(f)
        cl = rig.stub / "calls.log"
        self.calls = [tuple(ln.split("\t", 2)) for ln in cl.read_text(encoding="utf-8").splitlines()] if cl.exists() else []
        sc = rig.stub / "step3-calls.jsonl"
        self.step3 = [json.loads(ln) for ln in sc.read_text(encoding="utf-8").splitlines()] if sc.exists() else []
        self.events = list(rig.guest.events)

    def why(self):
        return "rc %s, status %s\n%s" % (self.rc, self.status, self.log[-5000:])

    def runs(self):
        return {r["name"]: r for r in self.suite["runs"]}

    def compares(self):
        return {c["name"]: c for c in self.suite["compares"]}

    def step3_names(self, cmd):
        return [_argmap(c["argv"])["--name"][0] for c in self.step3 if c["argv"][0] == cmd]

    def idx_all(self, name, pattern=""):
        return [i for i, (n, _v, args) in enumerate(self.calls) if n == name and re.search(pattern, args)]


def _argmap(argv):
    """step3.py's argv after its command: {flag: [values]} (a flag's words up to the next flag)."""
    out, key = {}, ""
    for w in argv[1:]:
        if w.startswith("--"):
            key = w
            out.setdefault(key, [])
        else:
            out.setdefault(key, []).append(w)
    return out


def _bridge_pin():
    return _images()["bridge"]["arm64"]["id"]


@pytest.fixture(scope="module")
def v2(tmp_path_factory):
    """One whole PLAN=v2 run with every stub answering as the instance should: the run most suite tests below read."""
    rig = SuiteRig(tmp_path_factory.mktemp("suite-v2"))
    before = _snapshot(rig.base)
    res = rig.run()
    res.before = before
    res.after = _snapshot(rig.base)
    return res


def _suite_run(tmp_path, plan="v1", skip=(), **cfg):
    return SuiteRig(tmp_path, plan=plan, skip=skip).run(**cfg)


# --- the plans and step 3's calls ---------------------------------------------------------------------------------

def test_suite_v2_runs_the_plan_in_order_with_step3s_environment(v2):
    r = v2
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.step3_names("run") == V2 and r.step3_names("compare") == V2_COMPARES
    assert [x["name"] for x in r.suite["runs"]] == V2 and [x["name"] for x in r.suite["compares"]] == V2_COMPARES
    kinds = _spec_kinds()
    runs = [c for c in r.step3 if c["argv"][0] == "run"]
    for (spec, mode), name, c in zip(V2_PAIRS, V2, runs):
        a = _argmap(c["argv"])
        console = str(r.rig.out / "guest" / ("%s-console.log" % name))
        assert a == {"--mode": [mode], "--spec": [spec], "--name": [name], "--images": ["loaded"], "--monitor": ["guest"],
                     "--guest-host": [GUEST], "--guest-console": [console],
                     "--guest-image": [str(r.rig.w / "img" / "ifs-vss.bin")]}, a
        assert c["env"] == {"SDV_HOST_ROLE": "a1-metal", "SDV_GEN": str(r.rig.vss_home / "gen"),
                            "SDV_CACHE": str(r.rig.vss_home / "cache"), "SDV_RUNS": str(r.rig.out / "runs"),
                            "SDV_SIM_VENV": str(r.rig.vss_home / "venv"),
                            "SDV_RECORDING": str(r.rig.vss_home / "recordings" / RECORDING[kinds[spec]]),
                            "SDV_BRIDGE_IMAGE": _bridge_pin()}, (name, c["env"])
        assert c["cwd"] == str(r.rig.repo), "step 3 runs from W/repo"
    venv = [args for n, _v, args in r.calls if n == "venv-python"]
    assert len(venv) == len(V2) + len(V2_COMPARES), venv[:3]
    assert all(a.startswith(str(r.rig.stack / "step3.py") + " ") for a in venv), venv[:3]
    for x in r.suite["runs"]:
        assert x["state"] == "ran" and x["ok"] is True and x["step3_exit"] == 0 and x["result_ok"] is True, x
        assert x["gates"] and all(v is True for v in x["gates"].values()), x
        console = r.rig.out / "guest" / ("%s-console.log" % x["name"])
        assert x["console_sha256"] == hashlib.sha256(console.read_bytes()).hexdigest()
        assert x["dir"] == "runs/" + os.path.basename(x["dir"]) and x["dir"].endswith("-" + x["name"])
        assert x["spec"] in SIX and x["recording"] == RECORDING[kinds[x["spec"]]]
    assert all(c["state"] == "ran" and c["ok"] is True and c["exit"] == 0 for c in r.suite["compares"]), r.suite["compares"]
    assert r.suite["plan"] == "v2" and r.suite["status"] == "DONE" and r.suite["not_run"] == [] and r.suite["can_complete"] is True


def test_suite_v1_runs_replay_honest_then_broker_honest_and_compares_nothing(tmp_path):
    r = _suite_run(tmp_path)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.step3_names("run") == V1 and r.step3_names("compare") == [] and r.suite["compares"] == []
    assert [(x["spec"], x["mode"], x["state"], x["ok"]) for x in r.suite["runs"]] == [
        ("honest", "replay", "ran", True), ("honest", "broker", "ran", True)]
    assert len(r.idx_all("launch")) == 2


def test_suite_plan_tool_gives_each_run_its_recording_and_refuses_another_plan():
    runs_file = os.path.join(REPO, "sdv", "stack", "step3-runs.json")
    p = _suite_tool("plan", "--plan", "v2", "--runs-file", runs_file)
    assert p.returncode == 0, p.stderr
    rows = [ln.split("\t") for ln in p.stdout.splitlines()]
    kinds = _spec_kinds()
    assert [x[2] for x in rows if x[0] == "run"] == V2 and [x[2] for x in rows if x[0] == "compare"] == V2_COMPARES
    for x in rows:
        if x[0] == "run":
            assert x[1] == x[2][:2] and x[5] == RECORDING[kinds[x[3]]], x
    assert [x[3:] for x in rows if x[0] == "compare"] == [["always", "broker replay"], ["can-complete", "broker replay can"]]
    p = _suite_tool("plan", "--plan", "v1", "--runs-file", runs_file)
    assert [ln.split("\t")[2] for ln in p.stdout.splitlines()] == V1
    assert _suite_tool("plan", "--plan", "v3", "--runs-file", runs_file).returncode != 0


# SDV Phase 7 WP3b: PLAN=carla, v2's units and compares over the CARLA pair, on an image whose
# `vss rules:` lines list profile 3 (setup's rules facts record the list).
CARLA_RECORDING = {"honest": CARLA_PAIR[0], "injected": CARLA_PAIR[1]}
GUEST_CARLA = dict(GUEST_OK, profiles=["1", "2", "3"])        # setup's guest step on ifs-vss-carla.bin: its lines list 1 2 3


def _plan_rows(plan):
    p = _suite_tool("plan", "--plan", plan, "--runs-file", os.path.join(REPO, "sdv", "stack", "step3-runs.json"))
    assert p.returncode == 0, p.stderr
    return [ln.split("\t") for ln in p.stdout.splitlines()]


def test_suite_plan_tool_plans_carla_as_v2_over_the_carla_pair():
    v2, carla, kinds = _plan_rows("v2"), _plan_rows("carla"), _spec_kinds()
    assert [x[:5] for x in carla] == [x[:5] for x in v2] and len(carla) == len(V2) + len(V2_COMPARES)
    for x in carla:
        if x[0] == "run":
            assert x[5] == CARLA_RECORDING[kinds[x[3]]], x
    assert [x[5] for x in v2 if x[0] == "run"] == [RECORDING[kinds[x[3]]] for x in v2 if x[0] == "run"], "v2 as before"
    assert [x[5] for x in _plan_rows("v1")] == [RECORDING["honest"]] * 2, "v1 as before"


def test_the_suites_plan_table_is_the_bundles():
    """vss_suite.py and bundle.py each hold the plans' table, and the two are held equal here."""
    vsu = _module(SUITE_TOOL, "_vss_suite_for_test")
    bdl = _module(os.path.join(REPO, "sdv", "stack", "bundle.py"), "_bundle_for_test")
    assert vsu.PLAN_RECORDINGS == bdl.PLAN_RECORDINGS and vsu.PLANS == tuple(bdl.PLAN_RECORDINGS) == ("v1", "v2", "carla")
    assert vsu.PLAN_RECORDINGS["carla"] == CARLA_RECORDING and vsu.PLAN_RECORDINGS["v1"] == vsu.PLAN_RECORDINGS["v2"] == RECORDING


def test_suite_carla_runs_v2s_units_over_the_carla_pair(tmp_path):
    rig = SuiteRig(tmp_path, plan="carla")
    rig.set_setup("status=DONE", guest=GUEST_CARLA)
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.step3_names("run") == V2 and r.step3_names("compare") == V2_COMPARES
    kinds = _spec_kinds()
    runs = [c for c in r.step3 if c["argv"][0] == "run"]
    for (spec, _mode), c in zip(V2_PAIRS, runs):
        assert c["env"]["SDV_RECORDING"] == str(rig.vss_home / "recordings" / CARLA_RECORDING[kinds[spec]]), c["env"]
    assert r.suite["plan"] == "carla" and [x["recording"] for x in r.suite["runs"]] == [CARLA_RECORDING[kinds[s]] for s, _m in V2_PAIRS]
    assert all(x["state"] == "ran" and x["ok"] for x in r.suite["runs"]) and all(c["ok"] for c in r.suite["compares"])
    pre = r.suite["preflight"]
    assert pre["setup_profiles"] == ["1", "2", "3"] and pre["recordings"] == ["%s carla.log profile 3" % n for n in CARLA_PAIR], pre


@pytest.mark.parametrize("guest, why", [
    (dict(GUEST_OK, profiles=["1", "2"]), "profile 3, which setup's `vss rules:` profiles [1, 2] do not list"),
    (dict(GUEST_OK, profiles=[]), "profile 3, which setup's `vss rules:` profiles [] do not list"),
    (GUEST_OK, "setup.json records no `vss rules:` profiles"),
    ({"booted": False, "launch_exit": 1, "guest_stopped": True}, "setup.json records no `vss rules:` profiles"),
], ids=["profiles-1-2", "no-agreed-list", "no-profiles-fact", "guest-did-not-boot"])
def test_suite_refuses_plan_carla_unless_setups_profiles_list_its_recordings_profile(tmp_path, guest, why):
    rig = SuiteRig(tmp_path, plan="carla")
    rig.set_setup("status=DONE", guest=guest)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.suite["reason"], r.suite["reason"]
    assert r.idx_all("launch") == [] and r.step3 == [] and r.idx_all("pkill") == []


@pytest.mark.parametrize("profile, listed, ok", [(2, ["1", "2"], True), (4, ["1", "2", "3"], False)], ids=["profile-2-listed", "profile-4-unlisted"])
def test_suite_judges_plan_carla_under_each_recordings_own_profile(tmp_path, profile, listed, ok):
    """The preflight reads the profile from each recording's manifest line (its profile_id), not a fixed 3: lines of profile
    2 pass a setup that lists 1 2, lines of profile 4 are refused by one that lists 1 2 3 (the refusal names profile 4)."""
    rig = SuiteRig(tmp_path, plan="carla")
    rig.set_setup("status=DONE", guest=dict(GUEST_OK, profiles=listed))
    for name in CARLA_PAIR:
        _write(rig.vss_home / "recordings" / name / "manifest-line.json", _rec_line(name, profile=profile).decode())
    r = rig.run()
    if ok:
        assert r.rc == 0 and r.status == ["status=DONE"] and r.step3_names("run") == V2, r.why()
        pre = r.suite["preflight"]
        assert pre["setup_profiles"] == listed and pre["recordings"] == ["%s carla.log profile %d" % (n, profile) for n in CARLA_PAIR], pre
    else:
        assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
        assert "recording 20261019-carla-1 is judged under profile 4, which setup's `vss rules:` profiles [1, 2, 3] do not list" in r.suite["reason"]
        assert r.idx_all("launch") == [] and r.step3 == []


@pytest.mark.parametrize("change, why", [
    (lambda d: os.remove(str(d / "carla.log")), "no VSS_HOME/recordings/20261019-carla-1/carla.log"),
    (lambda d: (d / "manifest-line.json").write_bytes(_rec_line("20261019-carla-1", log="sigsim.log")), "'carla' with the log 'sigsim.log'"),
    (lambda d: os.remove(str(d / "manifest-line.json")), "20261019-carla-1/manifest-line.json cannot be read"),
], ids=["log-missing", "log-does-not-pair", "no-line"])
def test_suite_refuses_plan_carla_without_a_recordings_own_log(tmp_path, change, why):
    rig = SuiteRig(tmp_path, plan="carla")
    rig.set_setup("status=DONE", guest=GUEST_CARLA)
    change(rig.vss_home / "recordings" / "20261019-carla-1")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.suite["reason"], r.suite["reason"]
    assert r.idx_all("launch") == [] and r.step3 == []


def test_suite_v1_reads_no_profiles_and_no_line(tmp_path):
    """v1 and v2 are as they were: a setup whose profiles lack 3, and recordings without manifest lines, change nothing."""
    rig = SuiteRig(tmp_path, plan="v1")
    rig.set_setup("status=DONE", guest=dict(GUEST_OK, profiles=["1"]))
    for name in RECORDING.values():
        os.remove(str(rig.vss_home / "recordings" / name / "manifest-line.json"))
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert "setup_profiles" not in r.suite["preflight"] and "recordings" not in r.suite["preflight"]


@pytest.mark.parametrize("profiles, ok", [(b"1 2 3", True), (b"1 2", False)])
def test_suite_carla_takes_or_refuses_the_setup_record_run_vss_setup_wrote(tmp_path, profiles, ok):
    """End to end: run-vss-setup.sh on a guest whose `vss rules:` lines list PROFILES, then run-vss-suite.sh PLAN=carla fed
    exactly its setup.json."""
    srig = Rig(tmp_path / "setup")
    (srig.stub / "console.bin").write_bytes(_console([RULES.replace(b"profiles 1 2", b"profiles " + profiles)] * 5))
    s = srig.run()
    assert s.status == ["status=DONE"] and s.facts("guest")["profiles"] == profiles.decode().split(), s.why()
    rig = SuiteRig(tmp_path / "suite", plan="carla")
    shutil.copy(str(srig.out / "setup.json"), str(rig.setup / "raw" / "setup.json"))
    r = rig.run()
    if ok:
        assert r.rc == 0 and r.status == ["status=DONE"] and r.step3_names("run") == V2, r.why()
    else:
        assert r.rc == 1 and r.status == ["status=FAILED at=preflight"] and "profile 3" in r.suite["reason"], r.why()


def test_suite_names_are_unique_and_no_step3_call_is_refused(v2, tmp_path):
    """step3.py refuses an existing --name (stack.new_run_dir), as the stand-in does: the 19 runs' and the compares' names
    are unique, and every call was taken."""
    names = v2.step3_names("run") + v2.step3_names("compare")
    assert len(names) == 21 and len(set(names)) == 21, names
    assert "exists: pick another --name" not in v2.log
    assert all(x["step3_exit"] == 0 for x in v2.suite["runs"]) and all(c["exit"] == 0 for c in v2.suite["compares"])
    # the stand-in's refusal has teeth: the same name twice in one SDV_RUNS
    env = dict(os.environ, STUB_DIR=str(tmp_path), SDV_RUNS=str(tmp_path / "runs"))
    argv = [sys.executable, str(v2.rig.stack / "step3.py"), "compare", "--name", "01-x", str(tmp_path), "--modes", "replay"]
    assert subprocess.run(argv, env=env, capture_output=True, timeout=60).returncode == 1      # no result.json: ok false
    p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 1 and "pick another --name" in p.stderr


def test_suite_compare_takes_the_run_directories_before_modes(v2):
    r = v2
    comps = [c["argv"] for c in r.step3 if c["argv"][0] == "compare"]
    dirs = {x["name"]: str(r.rig.out / x["dir"]) for x in r.suite["runs"]}
    want20 = [dirs[n] for n in V2 if not n.endswith("-can")]
    assert comps[0] == ["compare", "--name", "20-compare-broker-replay"] + want20 + ["--modes", "broker", "replay"], comps[0]
    assert comps[1] == (["compare", "--name", "21-compare-broker-replay-can"] + [dirs[n] for n in V2]
                        + ["--modes", "broker", "replay", "can"]), comps[1]
    c = r.compares()
    assert c["20-compare-broker-replay"]["compare_ok"] is True and c["20-compare-broker-replay"]["modes"] == ["broker", "replay"]
    assert c["20-compare-broker-replay"]["dirs"] == ["runs/" + os.path.basename(d) for d in want20]
    for name in V2_COMPARES:
        d = c[name]["dir"]
        assert "compare" in d and (r.rig.out / d / "compare.json").exists(), d


# --- per run: the boot, readiness, the stops --------------------------------------------------------------------------

def test_suite_qemu_is_stopped_after_every_boot_and_every_unit_runs_under_its_cap(v2):
    r = v2
    launches = r.idx_all("launch")
    assert len(launches) == 19
    for k, i in enumerate(launches):
        nxt = launches[k + 1] if k + 1 < len(launches) else len(r.calls)
        sync = [j for j in r.idx_all("sync") if i < j < nxt]
        pkill = [j for j in r.idx_all("pkill", r"^-x qemu-system-aar$") if i < j < nxt]
        pgrep = [j for j in r.idx_all("pgrep", r"^-x qemu-system-aar$") if pkill and pkill[0] < j < nxt]
        assert sync and pkill and pgrep and sync[0] < pkill[0], (k, sync, pkill, pgrep)
        assert r.calls[pkill[0]][1] == "1", "sudo -n pkill"
    assert not (r.rig.stub / "state" / "qemu").exists()
    caps = [args for n, _v, args in r.calls if n == "timeout" and args.startswith("--kill-after=30s ")]
    assert sum(1 for a in caps if "launch-qnx-kvm-bridged.sh" in a) == 19
    assert sum(1 for a in caps if " ready " in a) == 19
    assert sum(1 for a in caps if "step3.py run " in a) == 19 and sum(1 for a in caps if "step3.py compare " in a) == 2
    for x in r.suite["runs"]:
        assert x["booted"] is True and x["boot_exit"] == 0 and x["qemu_stopped"] is True, x
    launch = (r.rig.out / "guest" / "01-honest-broker-launch.log").read_text(encoding="utf-8")
    assert "guest up (monitor answering on :7100)" in launch and "after 7s" not in launch


def test_suite_readiness_is_one_connect_and_close_inside_the_guests_deadline(v2):
    """Each boot's :7160 readiness opens and closes in one step: the stub guest saw nineteen clients that closed in time,
    the consoles hold no `client closed:`, and the freshness read after the settle passed."""
    r = v2
    assert r.events == [("%s-console.log" % n, "closed in time") for n in V2], r.events
    ready = [args for n, _v, args in r.calls if n == "python3" and re.search(r"vss_suite\.py ready ", args)]
    assert len(ready) == 19 and all("--host %s --port 7160 " % GUEST in a for a in ready), ready[:2]
    for x in r.suite["runs"]:
        assert x["ready_7160"] is True and x["ready_7160_attempts"] == 1 and x["fresh_before_step3"] is True, x
        assert x["fresh_problems"] == [] and x["banner_7160_seen"] is True
        console = (r.rig.out / "guest" / ("%s-console.log" % x["name"])).read_bytes()
        assert b"client closed:" not in console and console.count(b"client done: seen=0 ") == 2, console


def test_suite_a_console_that_is_not_fresh_is_recorded_and_step3_refuses_it(tmp_path):
    """What a probe held past the guest's deadline leaves: `client closed:` before step 3. The suite records the freshness
    it read, step 3 refuses the console (exit 1), and that is a result."""
    rig = SuiteRig(tmp_path, plan="v1")
    (rig.stub / "console.bin").write_bytes(_console() + b"monitor: client closed: no complete frame for 500 ms\r\n")
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    for x in r.suite["runs"]:
        assert x["fresh_before_step3"] is False and any("client closed:" in p for p in x["fresh_problems"]), x
        assert x["state"] == "ran" and x["step3_exit"] == 1 and x["ok"] is False and x["result"] is False, x
    assert "is not fresh" in r.log


def test_suite_a_guest_that_never_answers_on_7160_stops_the_plan_after_its_first_run(tmp_path):
    """A run whose guest is not ready on :7160 is recorded and skipped; while no run has been ready,
    the rest of the plan is listed (skipped, with why), not booted: the session's one suite run is not spent on
    nineteen boots of a guest that does not answer."""
    r = _suite_run(tmp_path, STUB_READY_DEAD=1, STUB_READY_TRIES=2)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "not-ready" and first["ready_7160"] is False and first["ready_7160_attempts"] == 2, first
    assert first["ok"] is False and first["qemu_stopped"] is True
    assert second["state"] == "skipped" and second["ok"] is False and "booted" not in second, second
    assert "01-honest-replay" in second["why"] and ":7160" in second["why"], second
    assert r.suite["plan_stopped_after"] == "01-honest-replay" and r.suite["not_run"] == []
    assert r.step3 == [] and len(r.idx_all("launch")) == 1 and not (r.rig.stub / "state" / "qemu").exists()


def test_suite_a_guest_not_ready_after_a_ready_run_is_recorded_and_the_plan_goes_on(tmp_path):
    """Once one run's guest was ready, a later run that is not is recorded (not-ready) and the plan goes on."""
    r = _suite_run(tmp_path, plan="v2", skip=("broker", "can"), STUB_READY_DEAD_RE="/08-inject-replay-console", STUB_READY_TRIES=2)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    states = {x["name"]: x["state"] for x in r.suite["runs"] if x["mode"] == "replay"}
    assert states == dict(dict.fromkeys(V2[6:13], "ran"), **{"08-inject-replay": "not-ready"}), states
    assert len(r.idx_all("launch")) == 7 and r.suite["plan_stopped_after"] is None
    assert r.step3_names("run") == [n for n in V2[6:13] if n != "08-inject-replay"]


def test_suite_a_boot_failure_is_recorded_qemu_stopped_and_the_next_run_boots(tmp_path):
    r = _suite_run(tmp_path, STUB_BOOT_FAIL="01-honest-replay")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "boot-failed" and first["booted"] is False and first["boot_exit"] == 1 and first["ok"] is False
    assert first["qemu_stopped"] is True and "step3_exit" not in first
    launches = r.idx_all("launch")
    assert len(launches) == 2
    stops = [j for j in r.idx_all("pkill", r"^-x qemu-system-aar$") if launches[0] < j < launches[1]]
    assert stops, "QEMU stopped before the next boot"
    assert second["state"] == "ran" and second["ok"] is True, second
    assert r.step3_names("run") == ["02-honest-broker"]
    launch2 = (r.rig.out / "guest" / "02-honest-broker-launch.log").read_text(encoding="utf-8")
    assert "a qemu-system-aarch64 is already running" not in launch2


def test_suite_a_step3_killed_on_its_own_is_its_result_not_a_cap(tmp_path):
    """Step 3 dying of a KILL of its own (an OOM kill: 137) long before the cap's end is that
    run's result, recorded, and the suite goes on; it is not a cap that fired."""
    r = _suite_run(tmp_path, STUB_STEP3_KILLED="^01-honest-replay$")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "ran" and first["step3_exit"] == 137 and first["ok"] is False, first
    assert second["state"] == "ran" and second["ok"] is True, second


def test_suite_a_run_that_fails_its_gates_is_recorded_and_the_suite_goes_on(tmp_path):
    r = _suite_run(tmp_path, STUB_STEP3_FAIL="^01-honest-replay$")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "ran" and first["step3_exit"] == 1 and first["ok"] is False and first["result_ok"] is False
    assert first["gates"]["reason_set"] is False
    assert second["ok"] is True and r.suite["status"] == "DONE"


# --- the deadline -------------------------------------------------------------------------------------------------------

def test_suite_a_timeout_between_runs_stops_cleanly_and_lists_the_rest_as_not_run(tmp_path):
    rig = SuiteRig(tmp_path, plan="v1")
    r = rig.run(STUB_JUMP_RE=r"01-honest-replay: end", STUB_JUMP_S=180 * 60)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=02-honest-broker reason=deadline"], r.why()
    assert r.suite["status"] == "TIMEOUT" and r.suite["at"] == "02-honest-broker" and r.suite["reason"] == "deadline"
    assert [x["state"] for x in r.suite["runs"]] == ["ran", "not-run"] and r.suite["not_run"] == ["02-honest-broker"]
    assert "not run: 02-honest-broker" in r.log
    assert len(r.idx_all("launch")) == 1 and not (rig.stub / "state" / "qemu").exists()
    assert r.idx_all("sync")[-1] > r.idx_all("pkill")[-1], "the clean stop syncs"
    assert r.idx_all("docker", r"^ps -aq --filter label=sdv\.stack\.run$"), "the clean stop looks for the stack's containers"


def test_suite_a_timeout_at_a_compare_lists_both_compares_as_not_run(tmp_path):
    """The check point before a compare; the skipped can runs before it are listed, and stand behind no check point."""
    rig = SuiteRig(tmp_path, plan="v2", skip=("can",))
    r = rig.run(STUB_JUMP_RE=r"13-injected-stop-replay: end", STUB_JUMP_S=180 * 60)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=20-compare-broker-replay reason=deadline"], r.why()
    assert r.suite["not_run"] == V2_COMPARES and r.step3_names("compare") == []
    assert [x["name"] for x in r.suite["runs"] if x["state"] == "ran"] == V2[:13]
    assert [x["name"] for x in r.suite["runs"] if x["state"] == "skipped"] == V2[13:]


def test_suite_a_step3_cap_ends_in_a_timeout_with_its_containers_removed(tmp_path):
    """step 3 overruns its cap (the stub timeout gives it one second; the stand-in sleeps with two containers up):
    status=TIMEOUT at=<run> reason=step-timeout and exit 0, never the runner's FAILED rc=124; QEMU stopped, and every
    container labelled sdv.stack.run removed with plain docker (the docker group)."""
    rig = SuiteRig(tmp_path, plan="v1")
    r = rig.run(STUB_CAP_RE=r"step3\.py run .*--name 01-honest-replay( |$)", STUB_STEP3_SLEEP="^01-honest-replay$")
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=step-timeout"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "step-timeout" and first["step3_exit"] in (124, 137) and first["ok"] is False, first
    assert second["state"] == "not-run" and r.suite["not_run"] == ["02-honest-broker"]
    assert not (rig.stub / "state" / "qemu").exists()
    assert (rig.stub / "state" / "containers").read_text(encoding="utf-8").split() == []
    rm = [(v, args) for n, v, args in r.calls if n == "docker" and args.startswith("rm -f ")]
    assert rm == [("0", "rm -f c0ffee000001 c0ffee000002")], rm
    assert r.suite["stop"] == {"containers_list_exit": 0, "containers_found": 2, "containers_rm_exit": 0,
                               "containers_removed": True, "verified": True}, r.suite["stop"]


def _stack_containers():
    """stack.py's CONTAINERS (every container a run may start), read from the real module."""
    code = ("import json, sys; sys.path.insert(0, %r); import stack; print(json.dumps(sorted(stack.CONTAINERS.values())))"
            % os.path.join(REPO, "sdv", "stack"))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_suite_a_clean_stop_that_cannot_list_the_containers_removes_the_stacks_names(tmp_path):
    """A step 3 cut by its cap leaves its stack up, and `docker ps` fails. The clean stop
    says so, records containers_removed false, and removes the stack's own container names, which needs no listing."""
    rig = SuiteRig(tmp_path, plan="v1")
    r = rig.run(STUB_CAP_RE=r"step3\.py run .*--name 01-honest-replay( |$)", STUB_STEP3_SLEEP="^01-honest-replay$",
                STUB_DOCKER_PS_FAIL=1)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=step-timeout"], r.why()
    stop = r.suite["stop"]
    assert stop["containers_list_exit"] == 1 and stop["containers_removed"] is False, stop
    assert stop["containers_fallback_rm_exit"] == 0 and "containers_found" not in stop, stop
    rm = [args for n, _v, args in r.calls if n == "docker" and args.startswith("rm -f ")]
    assert rm == ["rm -f " + " ".join(_stack_containers())], rm
    assert (rig.stub / "state" / "containers").read_text(encoding="utf-8").split() == [], "both removed by name"
    assert "could not be listed (docker ps exit 1)" in r.log
    # removed unseen: the stop is recorded unverified, and said where wait-run shows it
    assert stop["verified"] is False and stop["unverified"] == [
        "the containers labelled sdv.stack.run could not be listed (docker ps exit 1)"], stop
    assert any("the stop is unverified: the containers labelled sdv.stack.run could not be listed" in ln
               for ln in r.log.splitlines()[-30:]), r.log[-3000:]


def test_suite_falls_back_to_exactly_the_stacks_container_names():
    with open(SUITE, encoding="utf-8") as f:
        m = re.search(r"^STACK_CONTAINERS=\(([^)]*)\)$", f.read(), re.M)
    assert m is not None and m.group(1).split() == _stack_containers()


@pytest.mark.parametrize("unit", ["boot", "readiness"])
def test_suite_a_boot_or_readiness_overrunning_its_cap_ends_in_a_timeout(tmp_path, unit):
    """The boot (a launch that hangs) and the readiness (a guest that never answers) each run under the cap too."""
    rig = SuiteRig(tmp_path, plan="v1")
    if unit == "boot":
        r = rig.run(STUB_CAP_RE=r"launch-qnx-kvm-bridged\.sh", STUB_SLEEP_ON=r"^launch ", STUB_SLEEP_S=10)
    else:
        r = rig.run(STUB_CAP_RE=r"vss_suite\.py ready ", STUB_READY_DEAD=1)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=step-timeout"], r.why()
    first = r.suite["runs"][0]
    assert first["state"] == "step-timeout" and first["ok"] is False and r.suite["not_run"] == ["02-honest-broker"], first
    assert r.step3 == [] and not (rig.stub / "state" / "qemu").exists()


def test_suite_a_check_point_before_the_first_run_stops_before_any_boot(tmp_path):
    rig = SuiteRig(tmp_path, plan="v1")
    rig.ahead(25 * 60)                           # stop_at is now
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=deadline"], r.why()
    assert r.suite["not_run"] == V1 and r.idx_all("launch") == [] and r.step3 == []


def test_suite_a_compare_overrunning_its_cap_ends_in_a_timeout(tmp_path):
    rig = SuiteRig(tmp_path, plan="v2", skip=("can",))
    r = rig.run(STUB_CAP_RE=r"step3\.py compare ", STUB_STEP3_SLEEP="^20-compare-broker-replay$")
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=20-compare-broker-replay reason=step-timeout"], r.why()
    c = r.compares()
    assert c["20-compare-broker-replay"]["state"] == "step-timeout" and c["20-compare-broker-replay"]["exit"] in (124, 137)
    assert r.suite["not_run"] == ["21-compare-broker-replay-can"]
    assert (rig.stub / "state" / "containers").read_text(encoding="utf-8").split() == [], "the clean stop removed them"


# --- the skip list and the compares -------------------------------------------------------------------------------------

def test_suite_lists_the_modes_setup_skipped_and_runs_none_of_them(tmp_path):
    r = _suite_run(tmp_path, skip=("broker",))
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "ran" and second["state"] == "skipped" and "a stand-in probe for broker" in second["why"], second
    assert r.step3_names("run") == ["01-honest-replay"] and len(r.idx_all("launch")) == 1
    assert r.suite["skip_modes"] == ["broker"] and r.suite["not_run"] == []


def test_suite_runs_no_compare_over_a_mode_setup_skipped(tmp_path):
    r = _suite_run(tmp_path, plan="v2", skip=("broker", "can"))
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert [x["name"] for x in r.suite["runs"] if x["state"] == "ran"] == V2[6:13]
    assert {x["state"] for x in r.suite["runs"] if x["mode"] != "replay"} == {"skipped"}
    assert r.step3_names("compare") == [] and [c["state"] for c in r.suite["compares"]] == ["not-compared"] * 2
    assert all("broker" in c["why"] for c in r.suite["compares"])


def test_suite_runs_the_second_compare_only_when_can_finished_all_six(tmp_path):
    r = _suite_run(tmp_path, plan="v2", STUB_BOOT_FAIL="19-injected-stop-can")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.runs()["19-injected-stop-can"]["state"] == "boot-failed" and r.suite["can_complete"] is False
    assert r.step3_names("compare") == ["20-compare-broker-replay"]
    c = r.compares()
    assert c["20-compare-broker-replay"]["state"] == "ran" and c["20-compare-broker-replay"]["ok"] is True
    assert c["21-compare-broker-replay-can"]["state"] == "not-compared" and "six" in c["21-compare-broker-replay-can"]["why"]


# --- refusals -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["no-plan", "plan-v3", "no-docker-group", "setup-timeout", "setup-no-done", "setup-runner-failed",
                                  "setup-json-not-done"])
def test_suite_refuses_without_a_plan_the_docker_group_or_a_finished_setup(tmp_path, case):
    """setup-runner-failed: setup wrote DONE and its setup.json, but exited non-zero, so the detached runner appended
    status=FAILED rc=1 (remote-ladder.sh _detached): the last status line, not setup.json, decides."""
    rig = SuiteRig(tmp_path, plan="v1")
    cfg = {}
    if case == "no-plan":
        cfg["PLAN"] = None
    elif case == "plan-v3":
        cfg["PLAN"] = "v3"
    elif case == "no-docker-group":
        cfg["STUB_GROUPS"] = "ubuntu adm kvm"
    elif case == "setup-timeout":
        rig.set_setup("status=TIMEOUT at=30min-rule reason=30min-rule")
    elif case == "setup-no-done":
        rig.set_setup("status=DONE", done=False)
    elif case == "setup-runner-failed":
        _write(rig.setup / "status", "status=DONE\nstatus=FAILED rc=1\n")
    else:
        doc = json.loads((rig.setup / "raw" / "setup.json").read_text(encoding="utf-8"))
        doc["status"] = "TIMEOUT"
        _write(rig.setup / "raw" / "setup.json", json.dumps(doc))
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert r.suite is not None and r.suite["status"] == "FAILED" and r.suite["at"] == "preflight"
    assert r.idx_all("launch") == [] and r.step3 == [] and r.idx_all("pkill") == []


def test_suite_refuses_a_qemu_that_runs_already_and_leaves_it(tmp_path):
    rig = SuiteRig(tmp_path, plan="v1")
    (rig.stub / "state" / "qemu").write_text("")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert r.idx_all("launch") == [] and r.idx_all("pkill") == [], "a QEMU found at the preflight is refused, not killed"


@pytest.mark.parametrize("guest,why", [
    (dict(GUEST_OK, ready_7160=False, ready_7160_attempts=30), "ready_7160 is false"),
    (dict(GUEST_OK, c12b_ok=False, c12b_agree=False, c12b_lines=0, catalog="", catalog_is_bridge_label=False),
     "c12b_ok is false; catalog_is_bridge_label is false"),
    (dict(GUEST_OK, catalog="0xDEADBEEF", catalog_is_bridge_label=False), "catalog_is_bridge_label is false"),
    ({"booted": True, "launch_exit": 0}, "ready_7160 is missing; c12b_ok is missing; catalog_is_bridge_label is missing"),
    (None, "holds no guest verdict"),
], ids=["not-ready", "no-c12b", "other-catalog", "verdict-missing", "no-guest-facts"])
def test_suite_refuses_a_setup_whose_guest_booted_without_passing(tmp_path, guest, why):
    """Setup records its guest step's readiness, C12b and catalog as information and ends DONE; the
    suite boots the same image against the same images.json, so a guest that booted there without passing all three is
    a cannot-go-on: status=FAILED at=preflight, nothing booted."""
    rig = SuiteRig(tmp_path, plan="v2")
    rig.set_setup("status=DONE", guest=guest)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.suite["reason"], r.suite["reason"]
    assert r.idx_all("launch") == [] and r.step3 == [] and r.idx_all("pkill") == []
    if guest is not None:
        assert r.suite["preflight"]["setup_guest"] == {k: guest.get(k) for k in ("booted", "ready_7160", "c12b_ok",
                                                                                  "catalog_is_bridge_label") if k in guest}


def test_suite_takes_a_setup_whose_guest_did_not_boot(tmp_path):
    """A guest that did not boot in setup is not judged there: each suite run boots afresh and records its own boot."""
    rig = SuiteRig(tmp_path, plan="v1")
    rig.set_setup("status=DONE", guest={"booted": False, "launch_exit": 1, "guest_stopped": True})
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert [x["state"] for x in r.suite["runs"]] == ["ran", "ran"] and r.suite["preflight"]["setup_guest"] == {"booted": False}


def test_suite_refuses_the_setup_that_recorded_its_guest_reading_another_catalog(tmp_path):
    """End to end: run-vss-setup.sh with a guest whose `vss rules:` lines name 0xDEADBEEF ends DONE,
    and run-vss-suite.sh fed exactly its setup.json refuses at its preflight instead of booting nineteen guests whose
    every frame step 3 would fail as vss-catalog-mismatch."""
    srig = Rig(tmp_path / "setup")
    (srig.stub / "console.bin").write_bytes(_console([RULES.replace(b"0x4D68EA68", b"0xDEADBEEF")] * 5))
    s = srig.run()
    assert s.status == ["status=DONE"] and s.facts("guest")["catalog_is_bridge_label"] is False, s.why()
    rig = SuiteRig(tmp_path / "suite", plan="v2")
    shutil.copy(str(srig.out / "setup.json"), str(rig.setup / "raw" / "setup.json"))
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "catalog_is_bridge_label is false" in r.suite["reason"] and r.idx_all("launch") == [] and r.step3 == []


def test_suite_under_v2_a_first_run_not_ready_lists_the_rest_of_the_plan_unbooted(tmp_path):
    """The plan stop under PLAN=v2: the first run's guest never answers on :7160, so no later run boots.
    The other eighteen are listed, none run (state skipped, each with the stop's why: the plan's stop, not setup's skip
    list), both compares are listed not-compared, and every unit has its state (not_run is empty)."""
    r = _suite_run(tmp_path, plan="v2", STUB_READY_DEAD=1, STUB_READY_TRIES=2)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    runs = r.suite["runs"]
    assert [x["name"] for x in runs] == V2
    assert runs[0]["state"] == "not-ready" and runs[0]["qemu_stopped"] is True and runs[0]["ok"] is False, runs[0]
    for x in runs[1:]:
        assert x["state"] == "skipped" and x["ok"] is False and "booted" not in x and "step3_exit" not in x, x
        assert "01-honest-broker" in x["why"] and ":7160" in x["why"] and "skip list" not in x["why"], x
    assert [(c["name"], c["state"]) for c in r.suite["compares"]] == [(n, "not-compared") for n in V2_COMPARES]
    assert r.suite["plan_stopped_after"] == "01-honest-broker" and r.suite["not_run"] == [] and r.suite["can_complete"] is False
    assert len(r.idx_all("launch")) == 1 and r.step3 == [] and not (r.rig.stub / "state" / "qemu").exists()
    assert len(r.idx_all("python3", r"vss_suite\.py ready ")) == 1


def test_suite_a_can_run_that_left_no_result_json_did_not_finish(tmp_path):
    """Verifier mutant y05: "can finished all six" needs each can run's result.json, not only its state: a can run whose
    step 3 returned (exit 1) without one is recorded as ran with no result, and the all-modes compare is not run."""
    r = _suite_run(tmp_path, plan="v2", STUB_STEP3_NORESULT="^17-pause-both-can$")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    x = r.runs()["17-pause-both-can"]
    assert x["state"] == "ran" and x["step3_exit"] == 1 and x["result"] is False and x["ok"] is False, x
    assert [y["state"] for y in r.suite["runs"]] == ["ran"] * len(V2)
    assert r.suite["can_complete"] is False and r.step3_names("compare") == ["20-compare-broker-replay"]
    c = r.compares()["21-compare-broker-replay-can"]
    assert c["state"] == "not-compared" and "six" in c["why"], c


def test_suite_a_qemu_that_outlives_its_kill_is_kept_for_the_sweep(tmp_path):
    """The stop's KILL fallback, and a QEMU that outlives it too (STUB_QEMU_STUCK): the run records qemu_stopped false and
    keeps state/launched, so the sweep at the stop tries again and records the stop unverified. The next launch refuses
    the QEMU still running (boot-failed). STOP_WAIT_S is 1 s in this copy of the harness."""
    rig = SuiteRig(tmp_path, plan="v1")
    _fast(rig, "run-vss-suite.sh", "STOP_WAIT_S=10\n", "STOP_WAIT_S=1\n")
    r = rig.run(STUB_QEMU_STUCK=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    first, second = r.suite["runs"]
    assert first["state"] == "ran" and first["qemu_stopped"] is False, first
    assert second["state"] == "boot-failed" and second["qemu_stopped"] is False, second
    assert "a qemu-system-aarch64 is already running" in (rig.out / "guest" / "02-honest-broker-launch.log").read_text(encoding="utf-8")
    # each stop's TERM, then its KILL: the first run's, the second's, and the sweep's at DONE
    assert [(v, a) for n, v, a in r.calls if n == "pkill"] == [("1", "-x qemu-system-aar"), ("1", "-KILL -x qemu-system-aar")] * 3
    stop = r.suite["stop"]
    assert stop["qemu_stopped"] is False and stop["verified"] is False and stop["unverified"] == ["QEMU still runs after a KILL"], stop
    tail = r.log.splitlines()[-30:]
    assert any(ln.endswith("the stop is unverified: QEMU still runs after a KILL") for ln in tail), tail


def test_suite_a_stop_that_cannot_list_the_stacks_containers_is_recorded_unverified(tmp_path):
    """A sweep whose `docker ps` fails is no verified clean stop, DONE included: suite.json's stop says verified false and
    why, and run.log says so where wait-run shows it. The status line stays status=DONE."""
    r = _suite_run(tmp_path, STUB_DOCKER_PS_FAIL=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    stop = r.suite["stop"]
    assert stop["containers_list_exit"] == 1 and stop["containers_removed"] is False and stop["verified"] is False, stop
    assert stop["unverified"] == ["the containers labelled sdv.stack.run could not be listed (docker ps exit 1)"], stop
    tail = r.log.splitlines()[-30:]
    assert any("the stop is unverified: the containers labelled sdv.stack.run could not be listed" in ln for ln in tail), tail


def test_suite_a_stop_whose_container_removal_fails_is_recorded_unverified(tmp_path):
    """A step 3 cut by its cap leaves two containers up, and their `docker rm -f` fails: the stop is recorded unverified,
    with the removal's exit status."""
    rig = SuiteRig(tmp_path, plan="v1")
    r = rig.run(STUB_CAP_RE=r"step3\.py run .*--name 01-honest-replay( |$)", STUB_STEP3_SLEEP="^01-honest-replay$",
                STUB_DOCKER_RM_FAIL=1)
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=step-timeout"], r.why()
    stop = r.suite["stop"]
    assert stop["containers_found"] == 2 and stop["containers_rm_exit"] == 1 and stop["containers_removed"] is False, stop
    assert stop["verified"] is False and stop["unverified"] == [
        "docker rm -f of the containers labelled sdv.stack.run exited 1"], stop


def test_suite_a_done_suite_still_sweeps_the_stacks_containers(v2):
    """After any step-3 call the removal by label runs before status=DONE too, recorded."""
    assert v2.suite["stop"] == {"containers_list_exit": 0, "containers_found": 0, "containers_removed": True,
                                "verified": True}, v2.suite["stop"]
    ps = v2.idx_all("docker", r"^ps -aq --filter label=sdv\.stack\.run$")
    assert len(ps) == 1 and ps[0] > v2.idx_all("launch")[-1]


# --- the record ---------------------------------------------------------------------------------------------------------

def test_suite_json_is_written_whole_with_one_line_strings_and_whole_seconds_under_operational_s(v2):
    r = v2
    assert sorted(os.listdir(str(r.rig.out))) == ["guest", "runs", "suite.json"]
    assert sorted(os.listdir(str(r.rig.out / "guest"))) == sorted(["%s-console.log" % n for n in V2] + ["%s-launch.log" % n for n in V2])
    assert r.log.index("unit 21/21 21-compare-broker-replay-can: end") < r.log.index("status=DONE")
    for s in _strings(r.suite):
        assert "\n" not in s and "\r" not in s, s
    ops = list(_operational(r.suite))
    assert {k for k, _v in ops} == {"boot", "step3", "compare"}
    assert all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for _k, v in ops), ops
    for k in _keys(r.suite):
        assert not re.search(r"(_ms|_us|_ns|latency|rtt)$", k), k
    assert "no field is a measurement" in r.suite["note"] and "Docker" in r.suite["note"] and "pre-registered" in r.suite["note"]
    for path in [r.rig.out / "suite.json", r.rig.runlog] + sorted((r.rig.out / "guest").iterdir()):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not LATENCY_FIELD.search(text), (str(path), LATENCY_FIELD.search(text).group(0))


def test_suite_json_is_written_before_the_status_line(v2):
    """Verifier mutant y01: suite.json is in place before status=DONE. The stub python3 copies the status file when the
    record tool starts: it held no line yet."""
    snap = v2.rig.stub / "state" / "status-at-record"
    assert snap.exists() and snap.read_text(encoding="utf-8") == "", "the status file when suite.json was written"
    assert v2.status == ["status=DONE"] and v2.suite["status"] == "DONE" and v2.suite["status_line"] == "status=DONE"


def test_suite_writes_nothing_outside_out_status_and_vss_home(v2):
    r = v2.rig
    allowed = [os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") + "/" for p in (r.out, r.vss_home, r.stub)]
    allowed_files = {os.path.relpath(str(p), str(r.base)).replace(os.sep, "/") for p in (r.status, r.runlog)}
    changed = sorted(p for p in set(v2.after) | set(v2.before) if v2.after.get(p) != v2.before.get(p))
    outside = [p for p in changed if p not in allowed_files and not any(p.startswith(a) for a in allowed)]
    assert outside == [], outside
    assert os.listdir(str(r.home)) == [] and os.listdir(str(r.tmp)) == []


def test_suite_every_file_it_writes_is_on_captures_vss_whitelist(v2, tmp_path):
    """capture.py, run on a copy of the record (done touched, a redactor that changes nothing), leaves out nothing the
    suite writes; of step 3's directories it leaves out only what capture never takes (in/)."""
    rec = tmp_path / "rec"
    shutil.copytree(str(v2.rig.w / "rec"), str(rec))
    (rec / "vss-suite" / "done").write_text("")
    _write(tmp_path / "red.sh", "cat\n")
    p = subprocess.run([sys.executable, CAPTURE, str(rec), str(tmp_path / "pub"), str(tmp_path / "red.sh")],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "vss-suite: DONE (status=DONE, with raw/suite.json)" in p.stdout
    excluded = [ln for ln in p.stdout.splitlines() if ln.startswith("excluded:")]
    others = [ln for ln in excluded if not re.match(r"excluded: vss-suite/raw/runs/[^/]+/in/sigsim\.log ", ln)]
    assert sorted(others) == ["excluded: vss-setup/done (not on the vss whitelist)",
                              "excluded: vss-suite/done (not on the vss whitelist)"], others
    published = {os.path.relpath(os.path.join(a, n), str(tmp_path / "pub")).replace(os.sep, "/")
                 for a, _d, fs in os.walk(str(tmp_path / "pub")) for n in fs}
    for root, _dirs, files in os.walk(str(v2.rig.out)):
        for n in files:
            rel = "vss-suite/raw/" + os.path.relpath(os.path.join(root, n), str(v2.rig.out)).replace(os.sep, "/")
            if "/in/" not in rel:
                assert rel in published, rel


# --- the helper ---------------------------------------------------------------------------------------------------------

def test_vss_suite_py_parses_as_python_3_10_and_takes_step3s_freshness_operands():
    with open(SUITE_TOOL, encoding="utf-8") as f:
        src = f.read()
    ast.parse(src, feature_version=(3, 10))
    for name in ("tomllib", "file_digest", "ExceptionGroup", "TaskGroup", "Self"):
        assert not re.search(r"\b%s\b" % name, src), name
    with open(STEP3_SRC, encoding="utf-8") as f:
        step3 = f.read()
    for const in ("FRESH_LIVENESS", "FRESH_CLOSED", "FRESH_DONE_RX", "GUEST_HOST"):
        want = re.search(r"^%s = (.+?)\s*(#.*)?$" % const, step3, re.M)
        got = re.search(r"^%s = (.+?)\s*(#.*)?$" % const, src, re.M)
        assert want is not None and got is not None and got.group(1) == want.group(1), const


def _suite_tool(*args):
    return subprocess.run([sys.executable, SUITE_TOOL] + list(args), capture_output=True, text=True, timeout=60)


def test_suite_record_writer_splits_multi_line_problems_and_lists_what_did_not_run(tmp_path):
    work = tmp_path / "work"
    _write(work / "plan.tsv", "run\t01\t01-honest-replay\thonest\treplay\t20260930-sigsim-1b\n"
                              "run\t02\t02-honest-broker\thonest\tbroker\t20260930-sigsim-1b\n"
                              "compare\t03\t03-compare-broker-replay\talways\tbroker replay\n")
    _write(work / "facts" / "01-honest-replay" / "state.s", "ran")
    _write(work / "facts" / "01-honest-replay" / "step3_exit.i", "0")
    _write(work / "facts" / "01-honest-replay" / "result_ok.b", "true")
    _write(work / "facts" / "01-honest-replay" / "operational_s" / "step3.i", "61")
    _write(work / "facts" / "03-compare-broker-replay" / "state.s", "ran")
    _write(work / "facts" / "03-compare-broker-replay" / "exit.i", "1")
    _write(work / "facts" / "03-compare-broker-replay" / "groups" / "honest" / "problems.lines", "one\ntwo\r\nthree\n")
    _write(work / "facts" / "03-compare-broker-replay" / "why.s", "a reason\nover two lines")
    setup = tmp_path / "setup.json"
    _write(setup, json.dumps({"status": "DONE", "skip_modes": ["can"], "skip": [{"mode": "can", "step": "vcan", "reason": "r"}]}))
    out = tmp_path / "out" / "suite.json"
    os.makedirs(str(out.parent))
    p = _suite_tool("record", "--work", str(work), "--out", str(out), "--setup", str(setup), "--plan", "v1", "--status", "TIMEOUT",
                    "--status-line", "status=TIMEOUT at=02-honest-broker reason=deadline", "--at", "02-honest-broker",
                    "--reason", "deadline")
    assert p.returncode == 0, p.stderr
    with open(str(out), encoding="utf-8") as f:
        doc = json.load(f)
    assert [(x["name"], x["state"], x["ok"]) for x in doc["runs"]] == [("01-honest-replay", "ran", True),
                                                                         ("02-honest-broker", "not-run", False)]
    assert doc["runs"][0]["operational_s"] == {"step3": 61}
    comp = doc["compares"][0]
    assert comp["groups"]["honest"]["problems"] == ["one", "two", "three"] and comp["ok"] is False
    assert comp["why"] == ["a reason", "over two lines"] and comp["modes"] == ["broker", "replay"]
    assert doc["not_run"] == ["02-honest-broker"] and doc["skip_modes"] == ["can"] and doc["status"] == "TIMEOUT"
    for s in _strings(doc):
        assert "\n" not in s and "\r" not in s, s
    assert os.listdir(str(out.parent)) == ["suite.json"]


# --- the headers and the README ---------------------------------------------------------------------------------------

AWS_README = os.path.join(REPO, "scripts", "aws", "README.md")


def _flat(text):
    return re.sub(r"\s+", " ", text)


def _header(src):
    """A harness's header comment, its lines joined: the leading lines that begin with #."""
    lines = []
    for ln in src.splitlines():
        if not ln.startswith("#"):
            break
        lines.append(ln.lstrip("#"))
    return _flat(" ".join(lines))


def test_the_headers_and_the_readme_list_every_failed_status_line_and_pips_cache():
    """Every FAILED status line a harness can write is in its header's THE STATUS LINE and in the README --
    the literal ones its code holds (at=preflight, setup's at=close, the suite's at=record), the step's or unit's own,
    and its EXIT trap's -- and the code holds no other form; and setup's header and the README name pip's cache
    (~/.cache/pip), the one write outside OUT, STATUS and VSS_HOME besides /etc/docker/daemon.json."""
    with open(AWS_README, encoding="utf-8") as f:
        readme = _flat(f.read())
    for path, unit in ((HARNESS, "<step>"), (SUITE, "<unit>")):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        head = _header(src)
        block = head[head.index("THE STATUS LINE"):head.index("THE RECORD")]
        forms = set(re.findall(r'\bfinish FAILED (\S+)', src))
        assert forms <= {"preflight", '"$name"', '"${CUR:-preflight}"', '"$at"'}, (path, forms)
        literal = ["status=FAILED at=%s" % x for x in sorted(forms) if not x.startswith('"')]
        literal += re.findall(r'line="(status=FAILED at=[a-z0-9-]+)"', src)
        assert len(literal) == 2, (path, literal)
        for line in literal + ["status=FAILED at=%s" % unit]:
            assert line in block, (path, line)
            assert line in readme, ("README.md", line)
        assert "stopped unexpectedly" in block, path
        assert "EXIT trap" in block, path
    assert readme.count("the harness stopped unexpectedly") >= 2, "README.md: the EXIT trap's FAILED, in both harnesses"
    with open(HARNESS, encoding="utf-8") as f:
        head = _header(f.read())
    assert "~/.cache/pip" in head[head.index("THE RECORD"):head.index("DESIGN VALUES")], "setup's header: pip's cache"
    assert "~/.cache/pip" in readme, "README.md: pip's cache"


# =====================================================================================================================
# Orin mode, both harnesses (plan Phase 5 WP2): VSS_HOST=orin
#
# ORIN RIG. The setup's and the suite's rigs above, with the environment the board's helper gives them (VSS_HOST=orin,
# VSS_REPIN, SDV_CONTAINER_CPUSET=3,5, the rig's own deadline file), R39's facts where a stub needs them (vcan, can and
# can_raw in the kernel's own package, STUB_VCAN_IN_KERNEL; an /etc/docker/daemon.json that holds the nvidia runtime,
# under the stub sudo's root), and, in the rig's copy of the harness, system.slice's cgroup.subtree_control pointed at a
# file of the rig. VSS_REPIN is a stand-in (_REPIN) that logs its call, answers as vss-repin.sh does while a QEMU "runs"
# and fails when told. The suite's taskset stub (above) runs its command with STUB_TASKSET_CPUS set, which the step3.py
# stand-in records beside SDV_CONTAINER_CPUSET and SDV_AFTER_START (env_extra).
#
# A1.METAL UNCHANGED. A1_GOLDEN holds the digest of the a1.metal runs these rigs make (the setup's `done`, the suite's
# `v2`, and a suite's v1): every call a stub logged, every step-3 call (argv, environment, working directory), and every
# file the harness wrote (OUT, run.log, the status file), with the rig's path, the login, the clock's times and the run
# directories' dates normalized (_a1_digest). The two reference harnesses, two tools and deadline library ran in these
# same rigs. Any change to a call or file of an a1.metal run changes the digest. Regenerate it only with the reference
# versions in these rigs. One fact is left out of the digest, here and under ORIN UNCHANGED: setup.json's
# facts.guest.profiles, the parsed `vss rules:` profile list SDV Phase 7 WP3b added to setup's rules facts,
# which neither reference commit wrote (_without_profiles); its own tests hold it.
#
# Does not demonstrate: a command the rig does not stub (cat, sed, awk, tar, `id -un` and the like run unlogged, so the
# digest cannot see one move), nor anything about the Orin -- L4T, Docker 29 there, its cgroups, QEMU's threads, the real
# re-pin.
# =====================================================================================================================

SUBTREE = "/sys/fs/cgroup/system.slice/cgroup.subtree_control"       # the harnesses' path, pointed into the rig
DEFAULT_DEADLINE = "/var/lib/qnx-metal-deadline"                    # lib-vss-deadline.sh's default
# an /etc/docker/daemon.json as L4T's Docker has it: the nvidia runtime, nothing else
DAEMON_JSON = (b'{\n    "runtimes": {\n        "nvidia": {\n            "args": [],\n'
               b'            "path": "nvidia-container-runtime"\n        }\n    }\n}\n')
REPIN_OK = "repin tag=boot cores=0-2 qemu=4242 threads=7 off_before=7 pin_failed=0 gone=0 threads_after=7 off_after=0 on_cores=yes"
A1_GOLDEN = {        # (sha256 of _a1_digest's text, its line count), the reference harnesses in these rigs
    "setup": ("589a61f0ac9a39a478dbf91fee74d22499ec3ec4953bd23a31eff6488ad604c6", 202),
    "suite-v1": ("81f168ab890d29aad865baf627fb43b2df020ffbeda45f4b548ee28a959aa271", 73),
    "suite-v2": ("e4fc9b41de6dd0b09d212a07f31b381e452f53b34434b8fd9ba6461afd8ffdf7", 610),
}
# ORIN UNCHANGED (2026-10-17, beside VSS_HOST=c7g-metal). ORIN_GOLDEN is A1_GOLDEN's kind for the Orin mode's runs in these
# rigs (orin_done's setup, orin_v2's suite, an Orin v1), with the login of the mode's `id -nG <login>` normalized as well.
# It was taken with the reference harnesses, tools and deadline library in these rigs, the tree before c7g-metal existed,
# so a change to a call or a file of an Orin run changes it. Regenerate it only that way.
ORIN_GOLDEN = {      # (sha256 of _a1_digest(login=True)'s text, its line count), the reference harnesses in these rigs
    "setup": ("f85f918adb13f15c0f5065a3242356e7b44eff54fefd83f607a7411384c4c26a", 195),
    "suite-v1": ("c2fc3eede6213c16b0b6d2ee15e0acf9b1bf2d32023f7b77b9963f2e2da194ab", 80),
    "suite-v2": ("cf1161d6dc986054835e758e1e75b5b3c5370b18249d06c27eb77a961ef7292e", 460),
}

# VSS_REPIN, a stand-in: one line as vss-repin.sh prints it, exit 3 while no QEMU "runs", exit 1 when STUB_REPIN_RC=1
# or when the console the launch last opened matches STUB_REPIN_FAIL_RE.
_REPIN = r'''#!/usr/bin/env bash
. "$STUB_DIR/_lib.sh"
stub_log vss-repin "$@"
if ! st qemu; then echo "repin tag=${1:-} cores=0-2 qemu=none error=no-qemu"; exit 3; fi
rc="${STUB_REPIN_RC:-0}"
if [ -n "${STUB_REPIN_FAIL_RE:-}" ] && grep -qE "$STUB_REPIN_FAIL_RE" "$STUB_DIR/state/console-path" 2>/dev/null; then rc=1; fi
if [ "$rc" = 0 ]; then
	echo "repin tag=$1 cores=0-2 qemu=4242 threads=7 off_before=7 pin_failed=0 gone=0 threads_after=7 off_after=0 on_cores=yes"
else
	echo "repin tag=$1 cores=0-2 qemu=4242 threads=7 off_before=7 pin_failed=0 gone=0 threads_after=7 off_after=1 on_cores=no"
fi
exit "$rc"
'''


def _point_subtree(harness, target):
    """The harness's system.slice subtree_control path pointed at TARGET, in the rig's copy (the text stands once)."""
    text = harness.read_text(encoding="utf-8")
    old = "SLICE_SUBTREE=%s\n" % SUBTREE
    assert text.count(old) == 1, "%s holds SLICE_SUBTREE=%s once" % (harness.name, SUBTREE)
    _write(harness, text.replace(old, "SLICE_SUBTREE=%s\n" % target))


def _orin_env(rig, cfg):
    """The board's environment for the Orin mode, CFG over it; a value of None unsets that variable."""
    want = {"VSS_HOST": "orin", "VSS_REPIN": str(rig.stub / "vss-repin.sh"), "SDV_CONTAINER_CPUSET": "3,5",
            "STUB_VCAN_IN_KERNEL": "1"}
    want.update(cfg)
    return want


class OrinRig(Rig):
    """The setup's rig with the board's environment (ORIN RIG above); SUBTREE_TEXT is system.slice's subtree_control
    (None: no such file)."""

    def __init__(self, base, subtree_text="cpuset cpu io memory pids"):
        super().__init__(base)
        self.subtree = base / "cgroup" / "system.slice" / "cgroup.subtree_control"
        if subtree_text is not None:
            _write(self.subtree, subtree_text + "\n")
        _point_subtree(self.g / "run-vss-setup.sh", self.subtree)
        self.daemon = self.stub / "root" / "etc" / "docker" / "daemon.json"
        os.makedirs(str(self.daemon.parent))
        self.daemon.write_bytes(DAEMON_JSON)
        for st in ("docker", "br_netfilter"):      # R39: Docker installed and running, br_netfilter loaded at boot
            (self.stub / "state" / st).write_text("")
        _write(self.stub / "vss-repin.sh", _REPIN, 0o755)

    def env(self, **cfg):
        want = _orin_env(self, cfg)
        e = super().env(**{k: v for k, v in want.items() if v is not None})
        for k, v in want.items():
            if v is None:
                e.pop(k, None)
        return e


class OrinSuiteRig(SuiteRig):
    """The suite's rig with the board's environment, after an Orin-mode setup (ORIN RIG above)."""

    def __init__(self, base, plan="v1", skip=(), subtree_text="cpuset cpu io memory pids", setup_mode="orin"):
        super().__init__(base, plan=plan, skip=skip)
        self.set_setup("status=DONE", skip=skip, host_mode=setup_mode)
        self.subtree = base / "cgroup" / "system.slice" / "cgroup.subtree_control"
        if subtree_text is not None:
            _write(self.subtree, subtree_text + "\n")
        _point_subtree(self.g / "run-vss-suite.sh", self.subtree)
        _write(self.stub / "vss-repin.sh", _REPIN, 0o755)

    def env(self, **cfg):
        return super().env(**_orin_env(self, cfg))


def _without_profiles(text):
    """setup.json's text without facts.guest.profiles, written back as vss_setup.py writes the document (json indent 1,
    a final newline): the one fact SDV Phase 7 WP3b added (setup's rules facts gain the parsed profile
    list), which the reference commits' setups did not write. Every other byte stays the run's; the fact itself is held
    by its own tests (test_setup_records_the_vss_rules_profiles_with_its_rules_facts)."""
    doc = json.loads(text)
    guest = (doc.get("facts") or {}).get("guest")
    if not isinstance(guest, dict) or "profiles" not in guest:
        return text
    guest.pop("profiles")
    return json.dumps(doc, indent=1) + "\n"


def _norm(t, base):
    """T with the rig's path BASE, the clock's times and the run directories' dates normalized (_a1_digest's rule)."""
    t = t.replace(base, "<BASE>")
    t = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "<UTC>", t)
    t = re.sub(r"\[\d\d:\d\d:\d\d\]", "[<T>]", t)
    return re.sub(r"(?<![0-9])20\d{6}-", "<DATE>-", t)


def _a1_digest(res, login=False):
    """An a1.metal run's normalized calls, step-3 calls and files (A1.METAL UNCHANGED above): (sha256, lines, text).
    LOGIN: the login in an `id -nG <login>` call normalized too (the Orin mode's call; ORIN UNCHANGED below)."""
    base = str(res.rig.base)

    def norm(t):
        return _norm(t, base)

    lines = []
    for n, v, a in res.calls:
        a = re.sub(r"^(-n usermod -aG docker |-aG docker )\S+$", r"\1<USER>", norm(a))
        if login and n == "id":
            a = re.sub(r"^-nG \S+$", "-nG <USER>", a)
        lines.append("call\t%s\t%s\t%s" % (n, v, a))
    for c in getattr(res, "step3", []):
        lines.append("step3\t" + norm(json.dumps(c, sort_keys=True)))
    files = {"run.log": str(res.rig.runlog), "status": str(res.rig.status)}
    for root, _dirs, fs in os.walk(str(res.rig.out)):
        for n in fs:
            p = os.path.join(root, n)
            files["raw/" + os.path.relpath(p, str(res.rig.out)).replace(os.sep, "/")] = p
    for k in sorted(files, key=norm):
        with open(files[k], "rb") as f:
            text = f.read().decode("utf-8", "replace")
        if k == "raw/setup.json":
            text = _without_profiles(text)
        lines.append("file\t%s\t%s" % (norm(k), hashlib.sha256(norm(text).encode("utf-8")).hexdigest()))
    text = "\n".join(lines) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(lines), text


def _assert_golden(res, key, tmp_path, orin=False):
    """RES's digest against A1_GOLDEN[KEY], or with ORIN against ORIN_GOLDEN[KEY] (the login normalized: ORIN UNCHANGED
    below)."""
    path, golden, ref, why = ("a1.metal", A1_GOLDEN, "cf7efe88", "A1.METAL UNCHANGED") if not orin else (
        "Orin", ORIN_GOLDEN, "9d83ab91", "ORIN UNCHANGED")
    sha, n, text = _a1_digest(res, login=orin)
    got = tmp_path / ("%s-%s-normalized.txt" % ("orin" if orin else "a1", key))
    got.write_text(text, encoding="utf-8")
    assert (sha, n) == golden[key], (
        "the %s %s run is not %s's: %d normalized lines, sha256 %s (%s: %d, %s); this run's lines are in %s: compare them "
        "with %s's harness run in this rig (%s)" % (path, key, ref, n, sha, ref, golden[key][1], golden[key][0], got, ref, why))


@pytest.fixture(scope="module")
def orin_done(tmp_path_factory):
    """One whole Orin-mode setup with every stub answering as the board should: the run most Orin tests below read."""
    rig = OrinRig(tmp_path_factory.mktemp("orin-done"))
    before = _snapshot(rig.base)
    res = rig.run()
    res.before = before
    res.after = _snapshot(rig.base)
    return res


@pytest.fixture(scope="module")
def orin_alt(tmp_path_factory):
    """An Orin-mode setup on another host state: the login in docker already, can loaded before, the container cpuset 5."""
    return OrinRig(tmp_path_factory.mktemp("orin-alt")).run(STUB_GROUPS_DB="ubuntu adm docker kvm", STUB_LSMOD_BEFORE="can",
                                                           SDV_CONTAINER_CPUSET="5")


# --- the setup, Orin mode ---------------------------------------------------------------------------------------------

def test_orin_setup_ends_done_writing_no_daemon_json_and_running_no_apt(orin_done):
    """No write of /etc/docker/daemon.json, no apt-get update or install (nor apt-cache):
    Docker as the host has it, asserted (server major 29, the containerd image store), its file hashed under sudo -n
    before and after, never read for its content; docker-facts.txt as on a1.metal without the apt lines; no apt.log."""
    r = orin_done
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert [s["name"] for s in r.setup["steps"]] == STEPS and all(s["outcome"] == "ok" for s in r.setup["steps"]), r.setup["steps"]
    assert r.rig.daemon.read_bytes() == DAEMON_JSON, "daemon.json as the host had it"
    assert [c for c in r.calls if c[0] in ("apt-get", "apt-cache")] == []
    assert [c[2] for c in r.calls if c[0] == "sudo" and "/etc/docker" in c[2]] == ["-n sha256sum /etc/docker/daemon.json"] * 2
    assert "apt.log" not in os.listdir(str(r.rig.out)) and r.setup["host_mode"] == "orin"
    facts = (r.rig.out / "docker-facts.txt").read_text(encoding="utf-8")
    for want in ("== dpkg-query -W docker.io containerd", "== docker server version: 29.1.3", "== docker storage driver: overlayfs",
                 "== docker image store driver-type: io.containerd.snapshotter.v1"):
        assert want in facts, (want, facts)
    assert "apt-cache" not in facts and "Candidate" not in facts and "linux-modules-extra" not in facts, facts
    d, sha = r.facts("docker"), hashlib.sha256(DAEMON_JSON).hexdigest()
    assert d["daemon_json_sha256"] == sha and r.facts("close")["daemon_json_sha256"] == sha, (d, r.facts("close"))
    assert d["server_major"] == 29 and d["driver_type"] == "io.containerd.snapshotter.v1" and "daemon_json" not in d, d
    assert not [k for k in d if k.startswith(("apt_", "install_", "candidate"))], d
    changed = sorted(p for p in set(r.after) | set(r.before) if r.after.get(p) != r.before.get(p))
    assert "stub/root/etc/docker/daemon.json" not in changed


def test_orin_setup_records_the_docker_group_before_its_usermod(orin_done, orin_alt):
    """Whether the login was in docker before, read from the group database, then
    usermod -aG docker as on a1.metal (the helper removes it at the day's end only when it was not there before)."""
    for r, before in ((orin_done, False), (orin_alt, True)):
        assert r.status == ["status=DONE"], r.why()
        assert r.facts("docker")["docker_group_before"] is before
        gi, ui = r.idx("id", r"^-nG \S+$"), r.idx("usermod", "^-aG docker ")
        assert 0 <= r.idx("sudo", "^-n sha256sum ") < gi < ui and r.calls[gi][2] == "-nG %s" % _user(), r.calls[gi]
        assert [(c[1], c[2]) for c in r.calls if c[0] == "usermod"] == [("1", "-aG docker %s" % _user())]


def test_orin_vcan_comes_from_the_kernel_with_the_modules_loaded_before_recorded(orin_done, orin_alt):
    """Setup item 4: no apt; lsmod read BEFORE modprobe (which of vcan, can and can_raw were loaded, the fact the helper
    unloads by), modinfo -F filename and -F vermagic as on a1.metal, then sudo -n modprobe -a vcan can can_raw."""
    for r, before in ((orin_done, []), (orin_alt, ["can"])):
        v = r.facts("vcan")
        assert v["ok"] is True and v["modprobe_exit"] == 0 and r.setup["skip_modes"] == [], v
        assert v["modules_loaded_before"] == before and v["modules_loaded_before_exit"] == 0, v
        i = r.idx("timeout", "_step vcan$")
        lsmod = [j for j, c in enumerate(r.calls) if c[0] == "lsmod" and j > i]
        assert lsmod and lsmod[0] < r.idx("modinfo") < r.idx("modprobe") < lsmod[-1], (lsmod, r.idx("modprobe"))
        assert [c[2] for c in r.calls if c[0] == "modinfo"] == ["-F filename vcan", "-F vermagic vcan"]
        assert [(c[1], c[2]) for c in r.calls if c[0] == "modprobe"] == [("1", "-a vcan can can_raw")]
        assert v["lsmod"] == ["can_raw                24576  0", "can                    28672  1 can_raw", "vcan                   12288  0"]
        assert not [c for c in r.calls if "linux-modules-extra" in c[2]] and r.idx("uname", "^-r$") == -1


def test_orin_vcan_reads_r39s_mttcan_and_can_dev_as_neither_can_nor_vcan(tmp_path):
    """R39 boots with mttcan and can_dev loaded: a module whose name only begins with can is not can, so the helper
    is told to unload can after the day as well."""
    rig = OrinRig(tmp_path)
    _write(rig.stub / "lsmod", '#!/usr/bin/env bash\n. "$STUB_DIR/_lib.sh"\nstub_log lsmod "$@"\n'
           'echo "Module                  Size  Used by"\necho "mttcan                 65536  0"\n'
           'echo "can_dev                45056  1 mttcan"\n'
           'if st modprobed; then echo "can_raw                24576  0"; echo "can                    28672  1 can_raw"; '
           'echo "vcan                   12288  0"; fi\n', 0o755)
    r = rig.run()
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    v = r.facts("vcan")
    assert v["modules_loaded_before"] == [] and v["modules_loaded_before_exit"] == 0 and v["ok"] is True, v
    assert v["modinfo_vermagic_exit"] == 0 and v["lsmod_exit"] == 0, v


@pytest.mark.parametrize("cfg,why,modprobed", [
    ({"STUB_VCAN_IN_KERNEL": None}, "modinfo -F filename vcan exited 1", False),
    ({"STUB_MODPROBE_RC": "1"}, "modprobe -a vcan can can_raw exited 1", True),
    ({"STUB_LSMOD_FAIL": "1"}, "lsmod could not be read before modprobe", False),
], ids=["no-module", "modprobe-fails", "lsmod-unreadable"])
def test_orin_vcan_that_cannot_be_had_skips_broker_and_can(tmp_path, cfg, why, modprobed):
    """A missing module or a failed modprobe puts broker and can into the skip list, as on a1.metal; so does an lsmod
    that cannot be read first (what this setup loaded would be unknown to the helper): no modprobe then."""
    r = OrinRig(tmp_path).run(**cfg)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.setup["skip_modes"] == ["broker", "can"] and r.facts("vcan")["ok"] is False
    assert all(why in s["reason"] for s in r.setup["skip"]), r.setup["skip"]
    assert (r.idx("modprobe") >= 0) is modprobed and [c for c in r.calls if c[0] in ("apt-get", "apt-cache")] == []


def test_orin_probe_containers_run_on_the_container_cpuset(orin_done, orin_alt):
    """Setup item 5: each probe container gets --cpuset-cpus with SDV_CONTAINER_CPUSET's value, recorded per probe."""
    for r, cpus in ((orin_done, "3,5"), (orin_alt, "5")):
        runs = [c for c in r.calls if c[0] == "docker" and c[2].startswith("run ")]
        assert len(runs) == 7, runs
        for c in runs:
            assert re.match(r"run --rm --network none --name sdv-setup-probe-\S+ --label sdv\.setup\.probe=1 --cpuset-cpus %s "
                            % re.escape(cpus), c[2]), c
        p = r.probes["probes"]
        assert all(p[n]["cpuset"] == cpus for n in PROBED if n != "host-venv") and "cpuset" not in p["host-venv"], p
        assert all(e["pass"] is True for e in p.values()), p


def test_orin_setup_starts_no_probe_container_beside_a_qemu_that_outlived_its_kill(tmp_path, orin_done):
    """QEMU is re-pinned after every container start while the guest runs, and a QEMU that outlived the
    KILL of step 5 (STUB_QEMU_STUCK) is one no pin reaches. In the Orin mode step 11 then starts no probe container: each
    image is recorded as not started, with why, and its modes go into the skip list; the host venv's probe (no container)
    still runs, and the setup ends DONE with its stop unverified as before. With QEMU gone every probe runs."""
    r = OrinRig(tmp_path).run(STUB_QEMU_STUCK=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.facts("after-docker")["guest_stopped"] is False
    assert [c[2].split(" --label ")[0] for c in r.calls if c[0] == "docker" and c[2].startswith("run ")] == [], "no probe container"
    assert [(c[1], c[2]) for c in r.calls if c[0] == "vss-repin"] == [("0", "boot")] and r.facts("probes")["qemu_listed"] is True
    p = r.probes["probes"]
    assert sorted(p) == sorted(PROBED) and p["host-venv"]["pass"] is True and "started" not in p["host-venv"], p["host-venv"]
    for n in PROBED:
        if n != "host-venv":
            assert p[n]["started"] is False and p[n]["pass"] is False, p[n]
            assert p[n]["result"].startswith("not started: a QEMU still runs at step 11"), p[n]
            assert "exit" not in p[n] and "cpuset" not in p[n], p[n]
    assert r.setup["skip_modes"] == ["broker", "can", "replay"] and r.probes["skip_modes"] == ["broker", "can", "replay"]
    assert all("a QEMU still runs at step 11" in s["reason"] for s in r.setup["skip"]), r.setup["skip"]
    assert r.facts("stop")["verified"] is False and "QEMU still runs after a KILL" in r.facts("stop")["unverified"]
    assert "no probe container starts beside it" in r.log
    done = orin_done.probes["probes"]
    assert orin_done.facts("probes")["qemu_listed"] is False and not [n for n in PROBED if "started" in done[n]], done


def test_orin_setup_repins_qemu_after_its_boot_and_before_its_smoke(orin_done):
    """Setup item 2: after the launcher's exit 0, `VSS_REPIN boot` (QEMU's threads to 0-2), recorded, before smoke 1."""
    r = orin_done
    assert [(c[1], c[2]) for c in r.calls if c[0] == "vss-repin"] == [("0", "boot")]
    assert 0 <= r.idx("launch") < r.idx("vss-repin") < r.idx("latency_probe"), (r.idx("launch"), r.idx("vss-repin"))
    g = r.facts("guest")
    assert g["booted"] is True and g["pinned"] is True and g["repin_exit"] == 0 and g["repin"] == [REPIN_OK], g
    pf = r.facts("preflight")
    assert pf["host_mode"] == "orin" and pf["container_cpuset"] == "3,5" and pf["system_slice_cpuset"] is True, pf
    assert pf["repin"] == str(r.rig.stub / "vss-repin.sh"), pf


def test_orin_setup_a_failed_repin_is_a_guest_that_did_not_boot(tmp_path):
    """Setup item 2: a failed pin is recorded and the guest treated as not booted: stopped, no smoke, setup goes on."""
    r = OrinRig(tmp_path).run(STUB_REPIN_RC=1)
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    g = r.facts("guest")
    assert g["launch_exit"] == 0 and g["repin_exit"] == 1 and g["pinned"] is False and g["booted"] is False, g
    assert g["guest_stopped"] is True and not (r.rig.stub / "state" / "qemu").exists() and r.idx("latency_probe") == -1
    assert r.facts("smoke-1")["pass"] is False and "VSS_REPIN boot exited 1" in r.facts("smoke-1")["not_run"]
    assert r.facts("smoke-2")["pass"] is False and r.idx("docker", "^version") >= 0, "setup went on"
    assert any(ln.endswith("its guest did not boot here, and each suite run boots its own") for ln in r.log.splitlines()[-30:])


def test_orin_setup_fails_at_its_close_when_daemon_json_changed_during_it(tmp_path):
    """Setup item 6: daemon.json's sha256 read again at the close; a difference fails the setup with its own reason."""
    r = OrinRig(tmp_path).run(STUB_DAEMON_JSON_CHANGE=1)
    assert r.rc == 1 and r.status == ["status=FAILED at=close"], r.why()
    assert "daemon.json" in r.setup["reason"] and "changed" in r.setup["reason"], r.setup["reason"]
    assert r.setup["at"] == "close" and r.setup["steps"][-1]["name"] == "close" and r.setup["steps"][-1]["outcome"] == "failed"
    before, after = r.facts("docker")["daemon_json_sha256"], r.facts("close")["daemon_json_sha256"]
    assert before == hashlib.sha256(DAEMON_JSON).hexdigest() and after != before and re.fullmatch(r"[0-9a-f]{64}", after)


def test_orin_setup_that_cannot_hash_daemon_json_fails_before_its_usermod(tmp_path):
    """The hash the close compares is read first: an unreadable daemon.json is a real failure of step 4, before the
    group is touched."""
    r = OrinRig(tmp_path).run(STUB_SUDO_FAIL="sha256sum")
    assert r.rc == 1 and r.status == ["status=FAILED at=docker"], r.why()
    assert "daemon.json" in r.setup["reason"] and r.idx("usermod") == -1 and r.idx("id", "^-nG ") == -1


def test_orin_setup_that_reads_no_sha256_from_sha256sum_fails_before_its_usermod(tmp_path):
    rig = OrinRig(tmp_path)
    _write(rig.stub / "sha256sum", '#!/usr/bin/env bash\n. "$STUB_DIR/_lib.sh"\nstub_log sha256sum "$@"\necho "not-a-digest  $1"\n', 0o755)
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=docker"], r.why()
    assert "daemon.json" in r.setup["reason"] and r.idx("usermod") == -1


@pytest.mark.parametrize("cfg,subtree,why", [
    ({"QNX_METAL_DEADLINE_FILE": None}, "cpuset cpu", "QNX_METAL_DEADLINE_FILE is not set"),
    ({"QNX_METAL_DEADLINE_FILE": DEFAULT_DEADLINE}, "cpuset cpu", "QNX_METAL_DEADLINE_FILE is the deadline library's default"),
    ({"VSS_REPIN": None}, "cpuset cpu", "VSS_REPIN is not set"),
    ({"VSS_REPIN": "<a file that is not executable>"}, "cpuset cpu", "VSS_REPIN is not an executable file"),
    ({"VSS_REPIN": "vss-repin.sh"}, "cpuset cpu", "VSS_REPIN is not an absolute path"),
    ({}, "cpu io memory pids", "cpuset is not among system.slice's subtree controllers"),
    ({}, None, "cannot be read"),
    ({"SDV_CONTAINER_CPUSET": None}, "cpuset cpu", "SDV_CONTAINER_CPUSET is not set"),
    ({"SDV_CONTAINER_CPUSET": "3,4"}, "cpuset cpu", "SDV_CONTAINER_CPUSET holds 4"),
    ({"VSS_HOST": "Orin"}, "cpuset cpu", "VSS_HOST"),
    ({"VSS_HOST": ""}, "cpuset cpu", "VSS_HOST"),
], ids=["no-deadline-file", "default-deadline-file", "no-repin", "repin-not-executable", "repin-relative", "no-cpuset-controller",
        "no-subtree-file", "no-cpuset", "cpuset-core-4", "host-misspelt", "host-empty"])
def test_orin_setup_refuses_before_any_step(tmp_path, cfg, subtree, why):
    """Setup item 1 (and VSS_HOST's rule): each refusal is status=FAILED at=preflight before step 1, with its reason in
    setup.json; nothing was booted, run under sudo, installed or started. An empty VSS_HOST is refused, never a1-metal."""
    rig = OrinRig(tmp_path, subtree_text=subtree)
    if cfg.get("VSS_REPIN") == "<a file that is not executable>":
        _write(rig.stub / "not-executable.sh", "#!/usr/bin/env bash\n", 0o644)
        cfg = dict(cfg, VSS_REPIN=str(rig.stub / "not-executable.sh"))
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.setup["reason"], r.setup["reason"]
    assert r.setup["steps"] == [] and r.setup["not_run"] == STEPS
    assert [c for c in r.calls if c[0] in ("launch", "sudo", "apt-get", "docker", "vss-repin", "usermod")] == [], r.calls


@pytest.mark.parametrize("case,why", [
    ("empty-deadline-variable", "QNX_METAL_DEADLINE_FILE is not set"),
    ("symlink-to-the-default-deadline", "QNX_METAL_DEADLINE_FILE is the deadline library's default"),
    ("repin-path-shlex-would-split", "VSS_REPIN holds a character other than"),
], ids=["empty-deadline-variable", "symlink-to-the-default-deadline", "repin-path-shlex-would-split"])
def test_orin_setup_refuses_an_empty_deadline_a_link_to_the_default_and_a_repin_path_with_a_space(tmp_path, case, why):
    rig = OrinRig(tmp_path)
    if case == "empty-deadline-variable":
        cfg = {"QNX_METAL_DEADLINE_FILE": ""}
    elif case == "symlink-to-the-default-deadline":
        os.symlink(DEFAULT_DEADLINE, str(tmp_path / "deadline-link"))
        cfg = {"QNX_METAL_DEADLINE_FILE": str(tmp_path / "deadline-link")}
    else:
        _write(tmp_path / "a dir" / "vss-repin.sh", _REPIN, 0o755)
        cfg = {"VSS_REPIN": str(tmp_path / "a dir" / "vss-repin.sh")}
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.setup["reason"], r.setup["reason"]
    assert [c for c in r.calls if c[0] in ("launch", "sudo", "docker", "vss-repin", "usermod")] == [], r.calls


@pytest.mark.parametrize("value,ok", [
    ("3,5", True), ("5", True), ("5,3", True), ("3", True), ("3,5,6", True),
    ("", False), ("4", False), ("3,4", False), ("0,3", False), ("1", False), ("2,5", False), ("3,3", False), ("3-5", False),
    ("03", False), ("3, 5", False), (" 3", False), ("3,", False), (",3", False), ("x", False), ("3,5\n", False), (None, False),
], ids=lambda v: repr(v))
def test_the_container_cpuset_rule_is_section_2s(tmp_path, value, ok):
    """A CPU list N[,N...] of distinct decimal integers, never empty, never holding 0, 1, 2 (QEMU's
    cores on the Orin) or 4 (the probe's core). vss_setup.py orin-check holds the rule for both harnesses."""
    subtree = tmp_path / "subtree_control"
    _write(subtree, "cpuset cpu\n")
    repin = tmp_path / "vss-repin.sh"
    _write(repin, "#!/usr/bin/env bash\n", 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VSS_", "SDV_", "QNX_"))}
    env.update(VSS_REPIN=str(repin), QNX_METAL_DEADLINE_FILE=str(tmp_path / "deadline"))
    if value is not None:
        env["SDV_CONTAINER_CPUSET"] = value
    p = subprocess.run([sys.executable, TOOL, "orin-check", "--facts", str(tmp_path / "facts"), "--default-deadline",
                        DEFAULT_DEADLINE, "--subtree", str(subtree)], env=env, capture_output=True, text=True, timeout=60)
    assert (p.returncode == 0) is ok, (p.returncode, p.stdout, p.stderr)
    assert (p.stdout.strip() == "") is ok and ("SDV_CONTAINER_CPUSET" in p.stdout) is (not ok), p.stdout
    assert "\n" not in p.stdout.strip(), "the refusals on one line"
    facts = tmp_path / "facts"
    assert (facts / "host_mode.s").read_text() == "orin" and (facts / "system_slice_cpuset.b").read_text() == "true"


def test_the_runners_and_the_stack_hold_one_cpuset_rule():
    """The rule is written twice, in vss_setup.py (both runners' preflight) and in
    stack.container_cpuset (the stack's Context). Each value of the test above is put to both, as role orin, in one
    subprocess that has both modules; they must refuse exactly the same ones."""
    (mark,) = [m for m in test_the_container_cpuset_rule_is_section_2s.pytestmark if m.name == "parametrize"]
    values = [v for v, _ok in mark.args[1]]
    assert len(values) >= 21 and None in values and "" in values, values
    code = (
        "import json, os, sys\n"
        "sys.path.insert(0, os.path.join(%r, 'orin-native', 'gpu-concurrency'))\n"
        "sys.path.insert(0, os.path.join(%r, 'sdv', 'stack'))\n"
        "import stack\n"
        "import vss_setup\n"
        "out = []\n"
        "for v in json.loads(sys.argv[1]):\n"
        "    if v is None:\n"
        "        os.environ.pop('SDV_CONTAINER_CPUSET', None)\n"
        "    else:\n"
        "        os.environ['SDV_CONTAINER_CPUSET'] = v\n"
        "    try:\n"
        "        stack.container_cpuset('orin')\n"
        "        stack_refuses = False\n"
        "    except stack.StackError:\n"
        "        stack_refuses = True\n"
        "    runner_refuses = vss_setup.cpuset_problem(v) is not None\n"
        "    out.append([v, stack_refuses, runner_refuses])\n"
        "print(json.dumps(out))\n") % (REPO, REPO)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SDV_", "VSS_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, "-B", "-c", code, json.dumps(values)], capture_output=True, text=True, timeout=120, env=env)
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout)
    assert [v for v, _s, _r in got] == values
    assert [(v, s, r) for v, s, r in got if s != r] == [], "the stack and the runners must refuse the same values"


@pytest.mark.parametrize("marker", ["l4t-release", "device-tree"])
def test_a1metal_mode_refuses_a_host_that_is_a_jetson(tmp_path, marker):
    """Unset VSS_HOST is a1-metal, which writes /etc/docker/daemon.json and installs packages: on a host that L4T's
    release file or an NVIDIA device tree marks as a Jetson it is refused at the preflight, before any of it."""
    rig = Rig(tmp_path)
    release, dt = tmp_path / "nv_tegra_release", tmp_path / "compatible"
    _fast(rig, "run-vss-setup.sh", "L4T_RELEASE=/etc/nv_tegra_release\n", "L4T_RELEASE=%s\n" % release)
    _fast(rig, "run-vss-setup.sh", "DT_COMPATIBLE=/proc/device-tree/compatible\n", "DT_COMPATIBLE=%s\n" % dt)
    if marker == "l4t-release":
        _write(release, "# R39 (release), REVISION: 2.1\n")
    else:
        dt.write_bytes(b"nvidia,p3768-0000+p3767-0005-super\0nvidia,p3767-0005\0nvidia,tegra234\0")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "VSS_HOST=orin" in r.setup["reason"] and r.setup["steps"] == [], r.setup["reason"]
    assert [c for c in r.calls if c[0] in ("launch", "sudo", "apt-get", "apt-cache", "docker", "usermod")] == [], r.calls


def test_orin_setup_writes_one_line_strings_and_nothing_outside_out_status_and_vss_home(orin_done):
    r = orin_done
    for doc in (r.setup, r.probes):
        for s in _strings(doc):
            assert "\n" not in s and "\r" not in s, s
    allowed = [os.path.relpath(str(p), str(r.rig.base)).replace(os.sep, "/") + "/" for p in (r.rig.out, r.rig.vss_home, r.rig.stub)]
    allowed_files = {os.path.relpath(str(p), str(r.rig.base)).replace(os.sep, "/") for p in (r.rig.status, r.rig.runlog)}
    changed = sorted(p for p in set(r.after) | set(r.before) if r.after.get(p) != r.before.get(p))
    assert [p for p in changed if p not in allowed_files and not any(p.startswith(a) for a in allowed)] == []
    assert os.listdir(str(r.rig.home)) == [] and os.listdir(str(r.rig.tmp)) == []


# --- the suite, Orin mode ---------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def orin_v2(tmp_path_factory):
    """A PLAN=v2 suite in Orin mode, can skipped by its setup: thirteen runs and the broker-replay compare."""
    return OrinSuiteRig(tmp_path_factory.mktemp("orin-v2"), plan="v2", skip=("can",)).run()


def test_orin_suite_gives_step3_the_orin_role_the_cpuset_and_the_hook_under_taskset(orin_v2):
    """Suite items 2 and 4: SDV_HOST_ROLE=orin, SDV_CONTAINER_CPUSET passed through, SDV_AFTER_START="$VSS_REPIN", and
    every step-3 call (each run and the compare) under `taskset -c "$SDV_CONTAINER_CPUSET"`, inside its cap."""
    r = orin_v2
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert r.step3_names("run") == V2[:13] and r.step3_names("compare") == ["20-compare-broker-replay"]
    repin = str(r.rig.stub / "vss-repin.sh")
    for c in r.step3:
        assert c["env"]["SDV_HOST_ROLE"] == "orin", c["env"]
        assert c["env_extra"] == {"SDV_CONTAINER_CPUSET": "3,5", "SDV_AFTER_START": repin, "STUB_TASKSET_CPUS": "3,5"}, c
    caps = [a for n, _v, a in r.calls if n == "timeout" and "step3.py" in a]
    assert len(caps) == 14 and all(re.match(r"--kill-after=30s \d+ taskset -c 3,5 env SDV_HOST_ROLE=orin ", a) for a in caps), caps[:2]
    ts = [a for n, _v, a in r.calls if n == "taskset"]
    assert len(ts) == 14 and all(a.startswith("-c 3,5 env SDV_HOST_ROLE=orin ") for a in ts), ts[:2]
    assert r.suite["host_mode"] == "orin" and r.suite["container_cpuset"] == "3,5"


def test_orin_suite_places_step3_on_the_cpuset_it_is_given(tmp_path):
    r = OrinSuiteRig(tmp_path, plan="v1").run(SDV_CONTAINER_CPUSET="5")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    ts = [a for n, _v, a in r.calls if n == "taskset"]
    assert len(ts) == 2 and all(a.startswith("-c 5 env SDV_HOST_ROLE=orin ") for a in ts), ts
    repin = str(r.rig.stub / "vss-repin.sh")
    assert all(c["env_extra"] == {"SDV_CONTAINER_CPUSET": "5", "SDV_AFTER_START": repin, "STUB_TASKSET_CPUS": "5"} for c in r.step3)
    assert r.suite["container_cpuset"] == "5" and r.suite["preflight"]["container_cpuset"] == "5"


def test_orin_suite_repins_after_each_boot_and_before_its_readiness(orin_v2):
    """Suite item 3: after each boot's exit 0 and before the readiness check, `VSS_REPIN boot`; recorded per run."""
    r = orin_v2
    launches = r.idx_all("launch")
    assert len(launches) == 13
    for k, i in enumerate(launches):
        nxt = launches[k + 1] if k + 1 < len(launches) else len(r.calls)
        rp = [j for j in r.idx_all("vss-repin") if i < j < nxt]
        ready = [j for j in r.idx_all("python3", r"vss_suite\.py ready ") if i < j < nxt]
        assert len(rp) == 1 and ready and rp[0] < ready[0] and r.calls[rp[0]][2] == "boot", (k, rp, ready)
    for x in r.suite["runs"]:
        if x["mode"] == "can":
            assert x["state"] == "skipped" and "pinned" not in x, x
            continue
        assert x["state"] == "ran" and x["ok"] is True and x["pinned"] is True and x["repin_exit"] == 0, x
        assert x["repin"] == [REPIN_OK], x
    pf = r.suite["preflight"]
    assert pf["host_mode"] == "orin" and pf["container_cpuset"] == "3,5" and pf["setup_host_mode"] == "orin", pf


def test_orin_suite_a_failed_repin_skips_that_run_as_a_boot_that_failed(tmp_path):
    """Suite item 3: once a run was pinned, a later pin that fails is recorded and that run skipped as a boot that failed
    (QEMU stopped, no readiness, no step 3); the plan goes on."""
    rig = OrinSuiteRig(tmp_path, plan="v2", skip=("broker", "can"))
    r = rig.run(STUB_REPIN_FAIL_RE="/08-inject-replay-console")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    runs = r.runs()
    failed = runs["08-inject-replay"]
    assert failed["state"] == "boot-failed" and failed["pinned"] is False and failed["repin_exit"] == 1, failed
    assert failed["boot_exit"] == 0 and failed["booted"] is False and failed["qemu_stopped"] is True and "VSS_REPIN" in failed["why"]
    assert "step3_exit" not in failed and "ready_7160" not in failed, failed
    ran = [n for n in V2[6:13] if n != "08-inject-replay"]
    assert all(runs[n]["state"] == "ran" and runs[n]["ok"] is True and runs[n]["pinned"] is True for n in ran), runs
    assert r.step3_names("run") == ran and len(r.idx_all("python3", r"vss_suite\.py ready ")) == 6
    assert len(r.idx_all("launch")) == 7 and r.suite["plan_stopped_after"] is None


def test_orin_suite_a_repin_that_overruns_its_cap_ends_in_a_timeout(tmp_path):
    r = OrinSuiteRig(tmp_path, plan="v1").run(STUB_CAP_RE=r"vss-repin\.sh boot", STUB_SLEEP_ON="^vss-repin boot", STUB_SLEEP_S="5")
    assert r.rc == 0 and r.status == ["status=TIMEOUT at=01-honest-replay reason=step-timeout"], r.why()
    assert r.suite["runs"][0]["state"] == "step-timeout" and r.step3 == []
    caps = [a for n, _v, a in r.calls if n == "timeout" and a.endswith("vss-repin.sh boot")]
    assert len(caps) == 1 and re.match(r"--kill-after=30s \d+ ", caps[0]), caps


def test_orin_suite_stops_the_plan_when_a_pin_fails_before_any_run_was_pinned(tmp_path):
    """A pin that fails while no run before it was pinned (a host reason: sudo's rule, no taskset) would fail
    on every boot. As for a guest not ready while none has been, the plan stops there: that run is a boot that failed
    (suite item 3), every later run is listed (skipped, with why) instead of booted, and plan_stopped_after names it."""
    r = OrinSuiteRig(tmp_path, plan="v2").run(STUB_REPIN_RC="1")
    assert r.rc == 0 and r.status == ["status=DONE"], r.why()
    assert len(r.idx_all("launch")) == 1 and len(r.idx_all("vss-repin")) == 1 and r.step3 == []
    first, rest = r.suite["runs"][0], r.suite["runs"][1:]
    assert first["name"] == "01-honest-broker" and first["state"] == "boot-failed" and first["pinned"] is False, first
    assert first["repin_exit"] == 1 and first["qemu_stopped"] is True and "VSS_REPIN" in first["why"], first
    assert r.suite["plan_stopped_after"] == "01-honest-broker" and r.suite["not_run"] == []
    assert len(rest) == 18 and all(x["state"] == "skipped" and "booted" not in x for x in rest), rest[:2]
    assert all("01-honest-broker" in x["why"] and "no run before it had been pinned" in x["why"] for x in rest), rest[:2]
    assert [c["state"] for c in r.suite["compares"]] == ["not-compared", "not-compared"]
    assert "no run's QEMU has been pinned" in r.log and not (r.rig.stub / "state" / "qemu").exists()


@pytest.mark.parametrize("case,why", [
    ("setup-a1-metal", "host mode"),
    ("default-deadline-file", "QNX_METAL_DEADLINE_FILE is the deadline library's default"),
    ("no-cpuset-controller", "cpuset is not among system.slice's subtree controllers"),
    ("no-repin", "VSS_REPIN is not set"),
    ("cpuset-core-4", "SDV_CONTAINER_CPUSET holds 4"),
    ("host-misspelt", "VSS_HOST"),
    ("no-deadline-file", "QNX_METAL_DEADLINE_FILE is not set"),
    ("repin-not-executable", "VSS_REPIN is not an executable file"),
    ("repin-relative", "VSS_REPIN is not an absolute path"),
    ("no-subtree-file", "cannot be read"),
    ("no-cpuset", "SDV_CONTAINER_CPUSET is not set"),
    ("host-empty", "VSS_HOST"),
])
def test_orin_suite_refuses_before_any_boot(tmp_path, case, why):
    """Suite item 1: the setup's checks, and a setup.json whose host mode is not orin (an a1.metal setup records none)."""
    rig = OrinSuiteRig(tmp_path, setup_mode=None if case == "setup-a1-metal" else "orin",
                       subtree_text=None if case == "no-subtree-file" else
                       "cpu io memory pids" if case == "no-cpuset-controller" else "cpuset cpu")
    if case == "repin-not-executable":
        _write(rig.stub / "not-executable.sh", "#!/usr/bin/env bash\n", 0o644)
    cfg = {"default-deadline-file": {"QNX_METAL_DEADLINE_FILE": DEFAULT_DEADLINE}, "no-repin": {"VSS_REPIN": None},
           "cpuset-core-4": {"SDV_CONTAINER_CPUSET": "4,5"}, "host-misspelt": {"VSS_HOST": "orin "},
           "no-deadline-file": {"QNX_METAL_DEADLINE_FILE": None},
           "repin-not-executable": {"VSS_REPIN": str(rig.stub / "not-executable.sh")},
           "repin-relative": {"VSS_REPIN": "vss-repin.sh"}, "no-cpuset": {"SDV_CONTAINER_CPUSET": None},
           "host-empty": {"VSS_HOST": ""}}.get(case, {})
    r = rig.run(**cfg)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert why in r.suite["reason"], r.suite["reason"]
    assert r.idx_all("launch") == [] and r.step3 == [] and r.idx_all("vss-repin") == [] and r.idx_all("taskset") == []


def test_an_a1metal_suite_refuses_a_setup_of_the_orin_mode(tmp_path):
    """The other way round: a setup.json that records host_mode orin is not an a1.metal suite's."""
    rig = SuiteRig(tmp_path, plan="v1")
    rig.set_setup("status=DONE", host_mode="orin")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "host mode" in r.suite["reason"] and r.idx_all("launch") == [], r.suite["reason"]


@pytest.mark.parametrize("marker", ["l4t-release", "device-tree"])
def test_a1metal_suite_refuses_a_host_that_is_a_jetson_by_either_marker(tmp_path, marker):
    rig = SuiteRig(tmp_path, plan="v1")
    release, dt = tmp_path / "nv_tegra_release", tmp_path / "compatible"
    _fast(rig, "run-vss-suite.sh", "L4T_RELEASE=/etc/nv_tegra_release\n", "L4T_RELEASE=%s\n" % release)
    _fast(rig, "run-vss-suite.sh", "DT_COMPATIBLE=/proc/device-tree/compatible\n", "DT_COMPATIBLE=%s\n" % dt)
    if marker == "l4t-release":
        _write(release, "# R39 (release), REVISION: 2.1\n")
    else:
        dt.write_bytes(b"nvidia,p3768-0000+p3767-0005-super\0nvidia,p3767-0005\0nvidia,tegra234\0")
    r = rig.run()
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "VSS_HOST=orin" in r.suite["reason"] and r.idx_all("launch") == [] and r.step3 == [], r.suite["reason"]


# --- a1.metal unchanged ------------------------------------------------------------------------------------------------

def test_an_a1metal_setup_is_cf7efe88s_call_for_call_and_file_for_file(done, tmp_path):
    """With VSS_HOST unset every command the rig stubs and every file the setup writes is as the reference harness's
    (A1.METAL UNCHANGED above); none of the Orin mode's calls or records appears."""
    assert done.status == ["status=DONE"], done.why()
    _assert_golden(done, "setup", tmp_path)
    assert "host_mode" not in done.setup and "host_mode" not in done.facts("preflight")
    assert not [c for c in done.calls if c[0] in ("vss-repin", "taskset", "id") or "--cpuset-cpus" in c[2] or "sha256sum" in c[2]]


def test_an_explicit_vss_host_a1_metal_is_the_unset_one(tmp_path):
    r = Rig(tmp_path).run(VSS_HOST="a1-metal")
    assert r.status == ["status=DONE"], r.why()
    _assert_golden(r, "setup", tmp_path)


def test_an_a1metal_setup_asks_id_un_in_its_usermod_line_as_cf7efe88_did(tmp_path):
    """The golden's id stub logs only `id -nG USER`, so it cannot see where `id -un` runs; here every id call is logged,
    and on the a1.metal path `id -un` comes after apt-get install docker.io and before usermod, as in the reference
    harness."""
    rig = Rig(tmp_path)
    _write(rig.stub / "id", '#!/usr/bin/env bash\n. "$STUB_DIR/_lib.sh"\nstub_log id "$@"\nexec "$(real id)" "$@"\n', 0o755)
    r = rig.run()
    assert r.status == ["status=DONE"], r.why()
    a, i, u = r.idx("apt-get", r"install .*docker\.io"), r.idx("id", "^-un$"), r.idx("usermod")
    assert 0 <= a < i < u and [c for c in r.calls if c[0] == "id"] == [("id", "0", "-un")], (a, i, u)


def test_an_a1metal_suite_is_cf7efe88s_call_for_call_and_file_for_file(v2, tmp_path):
    assert v2.status == ["status=DONE"], v2.why()
    _assert_golden(v2, "suite-v2", tmp_path)
    assert "host_mode" not in v2.suite and "container_cpuset" not in v2.suite and "setup_host_mode" not in v2.suite["preflight"]
    assert all(c["env_extra"] == {} for c in v2.step3) and v2.idx_all("taskset") == [] and v2.idx_all("vss-repin") == []


def test_an_explicit_vss_host_a1_metal_suite_is_the_unset_one(tmp_path):
    r = SuiteRig(tmp_path, plan="v1").run(VSS_HOST="a1-metal")
    assert r.status == ["status=DONE"], r.why()
    _assert_golden(r, "suite-v1", tmp_path)


# --- the Orin mode unchanged (ORIN UNCHANGED above) ------------------------------------------------------------------

def test_an_orin_setup_is_9d83ab91s_call_for_call_and_file_for_file(orin_done, tmp_path):
    assert orin_done.status == ["status=DONE"], orin_done.why()
    _assert_golden(orin_done, "setup", tmp_path, orin=True)


def test_an_orin_suite_is_9d83ab91s_call_for_call_and_file_for_file(orin_v2, tmp_path):
    assert orin_v2.status == ["status=DONE"], orin_v2.why()
    _assert_golden(orin_v2, "suite-v2", tmp_path, orin=True)
    r = OrinSuiteRig(tmp_path / "v1", plan="v1").run()
    assert r.status == ["status=DONE"], r.why()
    _assert_golden(r, "suite-v1", tmp_path, orin=True)


# =====================================================================================================================
# c7g.metal (2026-10-17): VSS_HOST=c7g-metal, the a1.metal path on AWS c7g.metal (Graviton3)
#
# C7G RIG. The setup's and the suite's rigs above with VSS_HOST=c7g-metal, and for the suite a setup.json that records
# host_mode c7g-metal. A c7g-metal run is held line for line to the a1.metal run of the same rig (_a1_digest's lines,
# done's and v2's): every stubbed call the same, but in the suite each step-3 call's cap (its env names the role) and the
# suite tool's setup and record calls (--host-mode c7g-metal last); every step-3 call the same but its SDV_HOST_ROLE;
# every file the same but setup.json or suite.json (host_mode; the suite's container_cpuset null and
# preflight.setup_host_mode as well), each step-3 run's manifest.json (the stand-in records the role it was given) and
# run.log (one line naming the mode).
#
# Does not demonstrate: anything about c7g.metal itself (the rig stubs every command of the a1.metal path, as it does for
# a1.metal), nor that the host is the one the word names: VSS_HOST is the operator's word, never read from the host.
# =====================================================================================================================

def _differing(a, b):
    """The (a, b) line pairs at which digests A and B (_a1_digest's) differ, their line counts asserted equal."""
    la, lb = a[2].splitlines(), b[2].splitlines()
    assert len(la) == len(lb), "a call, a step-3 call or a file more or fewer: %d lines, not %d" % (len(lb), len(la))
    return [(x, y) for x, y in zip(la, lb) if x != y]


def _one_more_line(a1, c7g):
    """The one run.log line of C7G that A1's lacks, normalized, once their counts differ by exactly that line."""
    la = _norm(a1.rig.runlog.read_text(encoding="utf-8"), str(a1.rig.base)).splitlines()
    lc = _norm(c7g.rig.runlog.read_text(encoding="utf-8"), str(c7g.rig.base)).splitlines()
    extra = [ln for ln in lc if ln not in la]
    assert len(lc) == len(la) + 1 and len(extra) == 1, extra
    return extra[0]


def test_a_c7g_metal_setup_is_the_a1_metal_one_but_the_host_mode_it_records(done, tmp_path):
    r = Rig(tmp_path).run(VSS_HOST="c7g-metal")
    assert r.status == ["status=DONE"], r.why()
    diff = _differing(_a1_digest(done), _a1_digest(r))
    assert [x.rsplit("\t", 1)[0] for x, _y in diff] == ["file\traw/setup.json", "file\trun.log"], diff
    keys = list(r.setup)
    got = dict(r.setup)
    assert got.pop("host_mode") == "c7g-metal" and keys[keys.index("harness") + 1] == "host_mode", keys
    assert (_norm(json.dumps(got, sort_keys=True), str(r.rig.base))
            == _norm(json.dumps(done.setup, sort_keys=True), str(done.rig.base))), "setup.json is a1.metal's but host_mode"
    assert _one_more_line(done, r).startswith("[<T>] the c7g.metal mode (VSS_HOST=c7g-metal): the a1.metal path")


def test_a_c7g_metal_suite_is_the_a1_metal_one_but_step3s_role_and_the_host_mode_it_records(v2, tmp_path):
    rig = SuiteRig(tmp_path, plan="v2")
    rig.set_setup("status=DONE", host_mode="c7g-metal")
    r = rig.run(VSS_HOST="c7g-metal")
    assert r.status == ["status=DONE"], r.why()
    diff = _differing(_a1_digest(v2), _a1_digest(r))
    step3 = [(x, y) for x, y in diff if x.startswith("step3\t")]
    files = sorted(x.rsplit("\t", 1)[0] for x, _y in diff if x.startswith("file\t"))
    calls = [(x, y) for x, y in diff if x.startswith("call\t")]
    assert len(step3) + len(files) + len(calls) == len(diff)
    # The stubbed calls that differ: each step-3 call's cap, whose env carries the role, and the tool's setup and record
    # calls, which take --host-mode c7g-metal last; nothing else.
    capped = [(x, y) for x, y in calls if x.startswith("call\ttimeout\t")]
    assert len(capped) == len(v2.step3) and all(y == x.replace(" env SDV_HOST_ROLE=a1-metal ", " env SDV_HOST_ROLE=c7g-metal ", 1)
                                                for x, y in capped), capped
    tool = [(x, y) for x, y in calls if (x, y) not in capped]
    assert [re.search(r"vss_suite\.py (\S+)", x).group(1) for x, _y in tool] == ["setup", "record"], tool
    assert all(y == x + " --host-mode c7g-metal" for x, y in tool), tool
    assert step3 and len(step3) == len(v2.step3), "every step-3 call differs, in its role alone (below)"
    for x, y in step3:
        a, c = json.loads(x[len("step3\t"):]), json.loads(y[len("step3\t"):])
        assert (a["env"]["SDV_HOST_ROLE"], c["env"]["SDV_HOST_ROLE"]) == ("a1-metal", "c7g-metal"), (a, c)
        c["env"]["SDV_HOST_ROLE"] = "a1-metal"
        assert c == a
    manifests = [f for f in files if re.match(r"^file\traw/runs/<DATE>-\d\d-[a-z-]+/manifest\.json$", f)]
    assert sorted(set(files) - set(manifests)) == ["file\traw/suite.json", "file\trun.log"], files
    assert len(manifests) == len([c for c in v2.step3 if c["argv"][0] == "run"]), manifests
    for p in (r.rig.out / "runs").glob("*/manifest.json"):
        assert json.loads(p.read_text(encoding="utf-8"))["host_role"] == "c7g-metal", p
    got = json.loads(json.dumps(r.suite))
    assert (got.pop("host_mode"), got.pop("container_cpuset"), got["preflight"].pop("setup_host_mode")) == (
        "c7g-metal", None, "c7g-metal"), r.suite
    assert (_norm(json.dumps(got, sort_keys=True), str(r.rig.base))
            == _norm(json.dumps(v2.suite, sort_keys=True), str(v2.rig.base))), "suite.json is a1.metal's but the host mode"
    assert _one_more_line(v2, r).startswith("[<T>] the c7g.metal mode (VSS_HOST=c7g-metal): the a1.metal path")


@pytest.mark.parametrize("setup_mode,suite_mode", [(None, "c7g-metal"), ("orin", "c7g-metal"), ("c7g-metal", None),
                                                   ("c7g-metal", "a1-metal")])
def test_a_suite_refuses_a_setup_of_another_host_mode_c7g_metal_either_way(tmp_path, setup_mode, suite_mode):
    """A setup.json with no host_mode is an a1.metal setup's: a c7g-metal suite refuses it, and an a1.metal suite (VSS_HOST
    unset or a1-metal) refuses a c7g-metal setup, before any boot."""
    rig = SuiteRig(tmp_path, plan="v1")
    rig.set_setup("status=DONE", host_mode=setup_mode)
    r = rig.run(VSS_HOST=suite_mode)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    assert "host mode" in r.suite["reason"] and r.idx_all("launch") == [] and r.step3 == [], r.suite["reason"]


@pytest.mark.parametrize("harness", ["run-vss-setup.sh", "run-vss-suite.sh"])
def test_c7g_metal_mode_refuses_a_host_that_is_a_jetson(tmp_path, harness):
    """c7g-metal is the a1.metal path (daemon.json written, packages installed; no pin, no placement): refused where L4T's
    release file marks the host as a Jetson, as a1-metal is, before any step."""
    rig = Rig(tmp_path) if harness == "run-vss-setup.sh" else SuiteRig(tmp_path, plan="v1")
    if harness == "run-vss-suite.sh":
        rig.set_setup("status=DONE", host_mode="c7g-metal")
    release = tmp_path / "nv_tegra_release"
    _fast(rig, harness, "L4T_RELEASE=/etc/nv_tegra_release\n", "L4T_RELEASE=%s\n" % release)
    _write(release, "# R39 (release), REVISION: 2.1\n")
    r = rig.run(VSS_HOST="c7g-metal")
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    doc = r.setup if harness == "run-vss-setup.sh" else r.suite
    assert "VSS_HOST=c7g-metal" in doc["reason"] and "VSS_HOST=orin" in doc["reason"], doc["reason"]
    assert [c for c in r.calls if c[0] in ("launch", "sudo", "apt-get", "apt-cache", "docker", "usermod")] == [], r.calls


@pytest.mark.parametrize("harness", ["run-vss-setup.sh", "run-vss-suite.sh"])
@pytest.mark.parametrize("value", ["c7g.metal", "C7G-METAL", "c7g-metal ", "c7g"])
def test_a_misspelt_c7g_metal_is_refused_naming_every_mode(tmp_path, harness, value):
    rig = Rig(tmp_path) if harness == "run-vss-setup.sh" else SuiteRig(tmp_path, plan="v1")
    r = rig.run(VSS_HOST=value)
    assert r.rc == 1 and r.status == ["status=FAILED at=preflight"], r.why()
    doc = r.setup if harness == "run-vss-setup.sh" else r.suite
    assert all(m in doc["reason"] for m in ("a1-metal", "c7g-metal", "orin")), doc["reason"]
    assert "host_mode" not in doc, "a refused value is never recorded as a host mode"
    assert [c for c in r.calls if c[0] in ("launch", "sudo", "apt-get", "docker", "usermod")] == [], r.calls
