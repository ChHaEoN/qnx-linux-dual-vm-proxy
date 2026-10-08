"""scripts/orin/provision-orin-r39.sh, run against stubs only (2026-10-04).

The script says where a freshly installed board stands (check) and installs what is missing
(apply). Its installer-stick rule is lib-stick.sh's, which it sources (2026-10-05: one copy,
shared with gate2-smoke.sh), so the tests of the script's text read both files. Nothing here
needs a board: every command it calls that could read or change a system
is a stub on PATH (sudo, apt-get, apt-cache, dpkg-query, usermod, getent, id, lsblk, findmnt,
nvpmodel, systemctl, docker), /etc, /sys and /proc are made-up trees, and HOME is a temporary
directory. Stubs for hostname, uname, ip and journalctl print a marker and must never run. The
one real command besides bash's own is timeout, which the script puts in front of docker.

Every value below is made up: package versions, the release line's revision, the login, the
group ids, the device names, the host's name. The layouts are the real ones (apt's simulation
lines, lsblk -P, findmnt -r with its three columns, a loop device's backing_file under /sys,
nvpmodel -q, a gdm custom.conf, dpkg's status words, sudo's own messages).

What these tests do NOT show: that the script works on the board. The apt-get stub re-implements,
from apt's manual, the behaviour the script leans on (--no-upgrade skips an installed package,
--trivial-only refuses anything beyond the packages named, a version that is not the candidate
is not found, a held dpkg lock ends the install at once unless it was told to wait); --no-remove
is only checked to be passed. The sudo stub models -k, a cached credential and a refused command
from sudo's manual, and runs what it is given: the real sudo's rules for passing a signal on are
not modelled, so a timeout that sits outside sudo passes here whatever the real one does. The
real apt, the real package archive and the real sudo are not exercised here. The lsblk and
findmnt stubs answer from a file, and what is behind a loop device is a file in the made-up /sys:
the real findmnt's line for a loop mount and the kernel's own backing_file are not read here.
The lost-session tests take away the reader of the script's output, or send the script a hangup,
while the apt-get stub is in the middle of an install; what the real sudo, apt and dpkg do with
those two signals is not exercised either.
"""
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ORIN = os.path.join(REPO, "scripts", "orin")
SCRIPT = os.path.join(ORIN, "provision-orin-r39.sh")
LIB = os.path.join(ORIN, "lib-stick.sh")        # the installer-stick rule, sourced by the script
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")

MARKER = "marker-zq7-not-a-real-host"
STUB_HOST = "stubhost-kx4"              # what the script's shell takes for the host's name, unless a test says otherwise
LOGIN = "tester"
DOC_MAC = "00:00:5e:00:53:2a"          # RFC 7042's documentation range

# The package families the script may install. cuda is opt-in: it is looked at only when named.
FAMILIES = {
    "core": "qemu-system-arm qemu-utils ipxe-qemu iproute2 bridge-utils ethtool build-essential device-tree-compiler curl",
    "build": "g++ cmake git bison",
    "someip": "libboost1.74-dev libboost-system1.74-dev libboost-thread1.74-dev libboost-filesystem1.74-dev",
    "cuda": "cuda-nvcc-13-2 cuda-cudart-dev-13-2 libcublas-dev-13-2",
}
DEFAULT_FAMILIES = ("core", "build", "someip")

# What a fresh board has, in shape (made-up versions): QEMU without its Recommends, no g++, no
# cmake, no Boost, no CUDA toolkit; curl and bison installed with newer candidates on offer.
INSTALLED = {
    "qemu-system-arm": "1:8.0-q1", "iproute2": "6.0-i1", "bridge-utils": "1.0-b1", "ethtool": "6.0-e1",
    "device-tree-compiler": "1.0-d1", "curl": "8.0-c1", "git": "2.0-g1", "bison": "3.0-y1",
    "docker.io": "29.0-k1", "gcc": "13.0-s1",
}
CANDIDATES = dict(INSTALLED, **{
    "curl": "8.0-c2", "bison": "3.0-y2",
    "qemu-utils": "1:8.0-q1", "ipxe-qemu": "1.0-x1", "build-essential": "12.0-be1",
    "g++": "13.0-s1", "g++-13": "13.0-s2", "libstdc++-13-dev": "13.0-s2", "dpkg-dev": "1.0-dd1",
    "cmake": "3.0-m1", "cmake-data": "3.0-m1",
    "libboost1.74-dev": "1.74-o1", "libboost-system1.74-dev": "1.74-o1", "libboost-thread1.74-dev": "1.74-o1",
    "libboost-filesystem1.74-dev": "1.74-o1", "libboost-system1.74.0": "1.74-o1", "libboost-thread1.74.0": "1.74-o1",
    "libboost-filesystem1.74.0": "1.74-o1",
    "cuda-nvcc-13-2": "13.2-n1", "cuda-cudart-dev-13-2": "13.2-n1", "libcublas-dev-13-2": "13.2-n1",
    "cuda-cudart-13-2": "13.2-n1", "libcublas-13-2": "13.2-n1",
    "libboost-dev": "1.83-u1", "libboost-system-dev": "1.83-u1", "late-dependency": "0.1-z1",
})
DEPS = {
    "build-essential": "g++ dpkg-dev", "g++": "g++-13", "g++-13": "libstdc++-13-dev", "cmake": "cmake-data",
    "libboost-system1.74-dev": "libboost1.74-dev libboost-system1.74.0",
    "libboost-thread1.74-dev": "libboost1.74-dev libboost-thread1.74.0",
    "libboost-filesystem1.74-dev": "libboost1.74-dev libboost-filesystem1.74.0",
    "cuda-cudart-dev-13-2": "cuda-cudart-13-2", "libcublas-dev-13-2": "libcublas-13-2",
}

# apt-get and usermod: the two stubs with behaviour worth modelling. The apt-get stub resolves a
# small dependency graph, prints apt's simulation lines, and re-implements what the script leans
# on: --no-upgrade, --trivial-only, and a version pin that must be the candidate. Its real install
# works package by package and says each one first; when a line cannot be written it stops there,
# as a command killed by a broken pipe does, and what it had not yet installed stays missing.
# When another apt holds dpkg's lock it gives up at once, unless it was told how long to wait.
STUBS_PY = r'''
import os
import sys
import time

S = os.environ["STUB_STATE"]
name, args = sys.argv[1], sys.argv[2:]
sys.stdout.reconfigure(newline="\n")
sys.stderr.reconfigure(newline="\n")
root = os.environ.get("STUB_AS_ROOT") == "1"


def rd(n, default=""):
    p = os.path.join(S, n)
    if not os.path.exists(p):
        return default
    with open(p, "r", newline="") as f:
        return f.read()


def wr(n, text):
    with open(os.path.join(S, n), "w", newline="\n") as f:
        f.write(text)


def table(n):
    d = {}
    for line in rd(n).splitlines():
        if line.strip():
            k, _, v = line.partition(" ")
            d[k] = v.strip()
    return d


def bye(rc, *lines):
    sys.stdout.write("".join(l + "\n" for l in lines))
    sys.exit(rc)


with open(os.path.join(S, "calls.log"), "a", newline="\n") as f:
    f.write(" ".join([name] + args) + "\n")

if name == "usermod":
    if not root:
        sys.stderr.write("usermod: Permission denied.\n")
        sys.exit(1)
    rc = int(rd("usermod_rc", "0"))
    if rc:
        sys.stderr.write("usermod: the stub was told to fail\n")
        sys.exit(rc)
    sys.stdout.write("stub usermod ran\n")
    if len(args) == 3 and args[0] == "-aG" and not rd("usermod_noop"):
        rows = [l.split(":") for l in rd("groups").splitlines() if l.count(":") == 3]
        for row in rows:
            members = [m for m in row[3].split(",") if m]
            if row[0] == args[1] and args[2] not in members:
                row[3] = ",".join(members + [args[2]])
        wr("groups", "".join(":".join(row) + "\n" for row in rows))
    sys.exit(0)

assert name == "apt-get", name
flags, words, opts, rest = [], [], [], list(args)
while rest:
    a = rest.pop(0)
    if a == "-o":                   # -o takes the next argument: a configuration item
        opts.append(rest.pop(0) if rest else "")
    elif a.startswith("-"):
        flags.append(a)
    else:
        words.append(a)
sim = "-s" in flags or "--simulate" in flags
if words[:1] == ["update"]:
    if not root:
        bye(100, "E: Could not open lock file /var/lib/apt/lists/lock - open (13: Permission denied)")
    rc = int(rd("update_rc", "0"))
    if rc == 0 and os.path.exists(os.path.join(S, "candidates.after-update")):
        wr("candidates", rd("candidates.after-update"))
    bye(rc, "Hit:1 http://archive.example.invalid/ubuntu-ports noble InRelease", "Reading package lists...")
if words[:1] != ["install"]:
    wr("apt-other", " ".join(args) + "\n")
    sys.exit(0)
inst, cand = table("installed"), table("candidates")
deps = dict((k, v.split()) for k, v in table("deps").items())
plan, head = [], ["Reading package lists...", "Building dependency tree...", "Reading state information..."]


def add(p):
    if any(x[0] == p for x in plan):
        return
    for d in deps.get(p, []):
        if d not in inst:
            add(d)
    plan.append((p, inst.get(p), cand[p]))


named = []
for n in words[1:]:
    p, _, pin = n.partition("=")
    if p not in cand:
        bye(100, *(head + ["E: Unable to locate package %s" % p]))
    if pin and pin != cand[p]:
        bye(100, *(head + ["E: Version '%s' for '%s' was not found" % (pin, p)]))
    if p in inst and ("--no-upgrade" in flags or inst[p] == cand[p]):
        head.append("Skipping %s, it is already installed and upgrade is not set." % p)
        continue
    named.append(p)
    add(p)
if not sim:
    for p in rd("install_needs_also").split():      # a dependency that appeared after the simulation
        add(p)
origin = "Ubuntu:24.04/noble-updates [arm64]"
extra = [l for l in rd("sim_extra").splitlines() if l]
lines = ["Inst %s%s (%s %s)" % (p, " [%s]" % old if old else "", new, origin) for p, old, new in plan]
lines += extra
lines += ["Conf %s (%s %s)" % (p, new, origin) for p, old, new in plan]
new_n = len([x for x in plan if x[1] is None])
counts = "%d upgraded, %d newly installed, %d to remove and 4 not upgraded." % (
    len(plan) - new_n, new_n, len([l for l in extra if l.startswith("Remv ")]))
if sim:
    with open(os.path.join(S, "sim_lc_all"), "a", newline="\n") as f:
        f.write(os.environ.get("LC_ALL", "(unset)") + "\n")
    note = [] if root else ["NOTE: This is only a simulation!", "      apt-get needs root privileges for real execution."]
    if plan:
        head += ["The following NEW packages will be installed:", "  " + " ".join(x[0] for x in plan)]
    bye(int(rd("sim_rc", "0")), *(note + head + [counts] + lines))
# ---- the real thing
if not root:
    bye(100, "E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)",
        "E: Unable to acquire the dpkg frontend lock, are you root?")
rc = int(rd("install_rc", "0"))
if rc:
    bye(rc, *(head + ["E: the stub was told to fail"]))
# Another apt holds dpkg's lock, as the daily timers' runs do. apt-get does not wait for it; told
# to (-o DPkg::Lock::Timeout=<seconds>), it does, and here the other apt is done within the wait.
waits_for_lock = [o for o in opts if o.startswith("DPkg::Lock::Timeout=") and o.split("=", 1)[1].isdigit() and int(o.split("=", 1)[1]) > 0]
if rd("dpkg_locked") and not waits_for_lock:
    bye(100, "E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 4242 (unattended-upgr)",
        "E: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), is another process using it?")
trivial = set(x[0] for x in plan) == set(named)
if not trivial:
    if "--trivial-only" in flags:
        bye(100, *(head + [counts, "E: Trivial Only specified but this is not a trivial operation."]))
    if not any(f in flags for f in ("-y", "--yes", "--assume-yes")):
        bye(1, *(head + [counts, "Do you want to continue? [Y/n] Abort."]))


def out(line):
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except OSError:                 # nobody reads any more: the install is cut off where it is
        os._exit(141)


waits = bool(rd("install_waits"))
if waits:                           # the test decides when the install goes on
    for _ in range(1200):
        if os.path.exists(os.path.join(S, "go")):
            break
        time.sleep(0.05)
    else:
        os._exit(98)
for line in head + [counts]:
    out(line)
if waits:
    time.sleep(0.8)                 # a reader that dies at its first line is gone by now
drops = rd("install_drops").split()
other = table("install_as")         # a package the stub installs at another version than asked
for p, old, new in plan:
    if p in drops:
        continue
    out("Setting up %s (%s) ..." % (p, other.get(p, new)))
    inst[p] = other.get(p, new)
    wr("installed", "".join("%s %s\n" % kv for kv in inst.items()))
sys.exit(0)
'''

# The stubs that only answer from a file: bash builtins, no other process.
STUB_HEAD = '''#!/bin/bash
S="$STUB_STATE"
echo "%s $*" >> "$S/calls.log"
show() { local l; [ -e "$S/$1" ] || return 0; while IFS= read -r l || [ -n "$l" ]; do printf '%%s\\n' "$l"; done < "$S/$1"; }
code() { local c=0; if [ -e "$S/$1" ]; then read -r c < "$S/$1"; fi; exit "$c"; }
hold() { local n=0; [ -e "$S/$1" ] || return 0; while [ ! -e "$S/go" ] && [ "$n" -lt 1200 ]; do sleep 0.05; n=$((n + 1)); done; }
'''

BASH_STUBS = {
    "dpkg-query": r'''
if [ "$1" != -W ] || [ "$2" != '-f=${Package}|${Status}|${Version}\n' ]; then echo "stub dpkg-query: unexpected arguments: $*" >&2; exit 64; fi
shift 2
declare -A inst=() resid=() held=() odd=()
while read -r k v; do if [ -n "$k" ]; then inst[$k]="$v"; fi; done < "$S/installed"
if [ -e "$S/residual" ]; then while read -r k v; do if [ -n "$k" ]; then resid[$k]="$v"; fi; done < "$S/residual"; fi
if [ -e "$S/held" ]; then while read -r k v; do if [ -n "$k" ]; then held[$k]=1; fi; done < "$S/held"; fi
# dpkg_state: "<package> <want> <flag> <state> <version>", for a package dpkg has in any other state.
if [ -e "$S/dpkg_state" ]; then while read -r k w f s v; do if [ -n "$k" ]; then odd[$k]="$w $f $s|$v"; fi; done < "$S/dpkg_state"; fi
rc=0
for p in "$@"; do
	if [ -n "${odd[$p]:-}" ]; then echo "$p|${odd[$p]}"
	elif [ -n "${inst[$p]:-}" ] && [ -n "${held[$p]:-}" ]; then echo "$p|hold ok installed|${inst[$p]}"
	elif [ -n "${inst[$p]:-}" ]; then echo "$p|install ok installed|${inst[$p]}"
	elif [ -n "${resid[$p]:-}" ]; then echo "$p|deinstall ok config-files|${resid[$p]}"
	else echo "dpkg-query: no packages found matching $p" >&2; rc=1
	fi
done
exit "$rc"
''',
    "apt-cache": r'''
if [ "$#" != 2 ] || [ "$1" != policy ]; then exit 64; fi
echo "${LC_ALL:-(unset)}" >> "$S/policy_lc_all"
i="(none)"; c="(none)"
while read -r k v; do if [ "$k" = "$2" ]; then i="$v"; fi; done < "$S/installed"
while read -r k v; do if [ "$k" = "$2" ]; then c="$v"; fi; done < "$S/candidates"
printf '%s:\n  Installed: %s\n  Candidate: %s\n  Version table:\n' "$2" "$i" "$c"
''',
    "getent": r'''
if [ "$#" != 2 ] || [ "$1" != group ]; then exit 2; fi
while IFS= read -r line; do case "$line" in "$2":*) echo "$line"; exit 0 ;; esac; done < "$S/groups"
exit 2
''',
    "id": r'''
hold id_waits                                   # the script's first call: a test may keep it here
read -r login < "$S/login"; read -r uid < "$S/uid"
case "$*" in
	-u) echo "$uid" ;;
	-un) echo "$login" ;;
	"-nG "*)
		out="$2"
		while IFS=: read -r g _x _gid members; do case ",$members," in *",$2,"*) out="$out $g" ;; esac; done < "$S/groups"
		echo "$out" ;;
	*) exit 64 ;;
esac
''',
    "lsblk": r'''
if [ "$*" != "-d -n -P -o NAME,RM,TRAN,TYPE" ]; then echo "stub lsblk: unexpected arguments: $*" >&2; exit 64; fi
show lsblk; code lsblk_rc
''',
    "findmnt": r'''
if [ "$*" != "-r -n -o TARGET,SOURCE,OPTIONS" ]; then echo "stub findmnt: unexpected arguments: $*" >&2; exit 64; fi
show findmnt; code findmnt_rc
''',
    "nvpmodel": r'''
if [ "$*" = -q ]; then show nvpmodel; code nvpmodel_rc; fi
# Anything else would change the mode: the stub does change it, so that a test sees it.
printf 'NV Power Mode: CHANGED\n%s\n' "${2:-?}" > "$S/nvpmodel"
exit 0
''',
    "systemctl": r'''
case "${1:-}" in
	is-enabled|is-active)
		if [ "$#" != 2 ]; then exit 64; fi
		w=""
		while read -r u en ac; do
			if [ "$u" = "$2" ]; then if [ "$1" = is-enabled ]; then w="$en"; else w="$ac"; fi; fi
		done < "$S/units"
		if [ -z "$w" ]; then if [ "$1" = is-enabled ]; then w=not-found; else w=inactive; fi; fi
		echo "$w"
		case "$w" in enabled|active|static) exit 0 ;; esac
		exit 1 ;;
	status|show) echo "$STUB_MARKER"; exit 0 ;;
esac
echo "$*" > "$S/systemctl-changed"
exit 0
''',
    "docker": r'''
if [ "$*" = "ps -a -q" ]; then
	if [ "${STUB_AS_ROOT:-}" != 1 ]; then echo "permission denied while trying to connect to the Docker daemon socket" >&2; exit 1; fi
	if [ -e "$S/docker_hangs" ]; then exec sleep 60; fi         # a daemon that does not answer
	if [ -e "$S/docker_fails" ]; then echo "Cannot connect to the Docker daemon" >&2; exit 1; fi
	show containers; exit 0
fi
echo "$*" > "$S/docker-changed"
exit 0
''',
}
# Each of these would print something that names the machine. None may ever run.
for _name in ("hostname", "uname", "ip", "journalctl"):
    BASH_STUBS[_name] = '\necho "$STUB_MARKER"\n'

SUDO_STUB = r'''#!/bin/bash
S="$STUB_STATE"
echo "sudo $*" >> "$S/calls.log"
# sudo_noise: what sudo says by itself, on stderr, at every call and before it runs anything.
if [ -e "$S/sudo_noise" ]; then while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l" >&2; done < "$S/sudo_noise"; fi
if [ -e "$S/sudo_denied" ]; then echo "sudo: a password is required" >&2; exit 1; fi
k=0
if [ "${1:-}" = -k ]; then k=1; shift; fi
if [ "${1:-}" != -n ]; then echo "stub sudo: called without -n" >&2; exit 64; fi
shift
# sudo_cached: no NOPASSWD line, only a credential cached by an earlier sudo with a password.
# -k does not use it, and it has run out by the time anything after the first question is asked.
if [ -e "$S/sudo_cached" ] && { [ "$k" = 1 ] || [ "${1:-}" != true ]; }; then echo "sudo: a password is required" >&2; exit 1; fi
# sudo_refuses: "<command> <what sudo says>", for a sudoers line that does not allow that command.
if [ -e "$S/sudo_refuses" ]; then
	while read -r c msg; do if [ "$c" = "${1:-}" ]; then printf '%s\n' "$msg" >&2; exit 1; fi; done < "$S/sudo_refuses"
fi
STUB_AS_ROOT=1 exec "$@"
'''

BRIDGE_STUB = '''#!/bin/bash
echo "bridge-stub $*" >> "$STUB_STATE/calls.log"
echo "%s"
echo "tap-qnx          UNKNOWN        %s <BROADCAST,MULTICAST,UP,LOWER_UP>"
if [ -e "$STUB_STATE/bridge_fails" ]; then exit 1; fi
if [ -e "$STUB_STATE/bridge_noop" ]; then exit 0; fi
mkdir -p "$SYS_ROOT/class/net/br0" "$SYS_ROOT/class/net/tap-qnx"
''' % (MARKER, DOC_MAC)

PY_STUBS = ("apt-get", "usermod")

# What lsblk and findmnt say on a board with no stick in it, in the layout of the two calls the
# script makes: lsblk -d -n -P -o NAME,RM,TRAN,TYPE, and findmnt -r -n -o TARGET,SOURCE,OPTIONS
# (one mount a line, the three columns a space apart).
LSBLK = 'NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="zram0" RM="0" TRAN="" TYPE="disk"\n'
MOUNTS = ("/ /dev/nvme0n1p1 rw,relatime\n/boot/efi /dev/nvme0n1p10 rw,relatime,fmask=0077,dmask=0077,errors=remount-ro\n"
          "/run tmpfs rw,nosuid,nodev,noexec,relatime\n/run/user/1000 tmpfs rw,nosuid,nodev,relatime\n")
STICK = 'NAME="sda" RM="1" TRAN="usb" TYPE="disk"\n'
# The vendor's own documentation image, as the desktop session of a freshly installed board mounts
# it by itself: a loop device on a file under /opt/nvidia/, vfat, read-only, under /media/<login>.
VENDOR_IMG = "/opt/nvidia/l4t-usb-device-mode/filesystem.img"
VENDOR_AT = "/media/%s/L4T-README" % LOGIN
RO_VFAT = ("ro,nosuid,nodev,relatime,uid=1000,gid=1000,fmask=0022,dmask=0022,codepage=437,iocharset=iso8859-1,"
           "shortname=mixed,showexec,utf8,flush,errors=remount-ro")
RW_VFAT = "rw" + RO_VFAT[2:]
LOOP0 = 'NAME="loop0" RM="0" TRAN="" TYPE="loop"\n'


# ------------------------------------------------------------------ a made-up board

def _fwd(p):
    return str(p).replace("\\", "/")


def _put(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(text.encode())


def _table(d):
    return "".join("%s %s\n" % kv for kv in d.items())


class Board:
    """A made-up board under one directory: fake /etc, /sys and /proc, a home, the stubs and
    their state. The defaults are a freshly installed board, in shape."""

    def __init__(self, root):
        self.root = root
        self.etc, self.sys, self.proc = root / "etc", root / "sys", root / "proc"
        self.home, self.state, self.bin = root / "home", root / "state", root / "bin"
        for d in (self.home, self.state, self.bin):
            d.mkdir(parents=True)
        # /etc
        _put(self.etc / "nv_tegra_release", "# R39 (release), REVISION: 9.9, GCID: 12345678, BOARD: generic, EABI: aarch64, DATE: made up\n")
        _put(self.etc / "os-release", 'PRETTY_NAME="Ubuntu 24.04.9 LTS (made up)"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n')
        _put(self.etc / "hostname", MARKER + "\n")
        _put(self.etc / "gdm3" / "custom.conf", "# GDM configuration storage\n[daemon]\n# AutomaticLoginEnable = true\n"
             "# AutomaticLogin = user1\nWaylandEnable=false\n\n[security]\n\n[xdmcp]\n")
        _put(self.etc / "docker" / "daemon.json", '{\n    "runtimes": {\n        "nvidia": {\n            "args": [],\n'
             '            "path": "nvidia-container-runtime"\n        }\n    }\n}\n')
        _put(self.etc / "modules-load.d" / "nemoclaw.conf", "br_netfilter\n")
        _put(self.etc / "sysctl.d" / "99-nemoclaw.conf", "net.bridge.bridge-nf-call-iptables=1\n")
        # /sys
        for pol in ("policy0", "policy4"):
            _put(self.sys / "devices" / "system" / "cpu" / "cpufreq" / pol / "scaling_governor", "schedutil\n")
        _put(self.sys / "module" / "kvm" / "parameters" / "halt_poll_ns", "500000\n")
        (self.sys / "module" / "br_netfilter").mkdir(parents=True)
        net = self.sys / "class" / "net"
        _put(net / "wlan9" / "operstate", "up\n")
        _put(net / "wlan9" / "carrier", "1\n")
        (net / "wlan9" / "device").mkdir()
        (net / "wlan9" / "phy80211").mkdir()
        _put(net / "eth9" / "operstate", "down\n")
        _put(net / "eth9" / "carrier", "0\n")
        (net / "eth9" / "device").mkdir()
        _put(net / "lo" / "operstate", "unknown\n")
        # /proc
        _put(self.proc / "swaps", "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n")
        _put(self.proc / "sys" / "kernel" / "panic", "0\n")
        _put(self.proc / "sys" / "kernel" / "panic_on_oops", "1\n")
        _put(self.proc / "sys" / "net" / "bridge" / "bridge-nf-call-iptables", "1\n")
        # the stubs' state
        self.set("installed", _table(INSTALLED))
        self.set("candidates", _table(CANDIDATES))
        self.set("deps", _table(DEPS))
        self.set("groups", "kvm:x:901:\ndocker:x:902:\nsudo:x:27:%s\n" % LOGIN)
        self.set("login", LOGIN + "\n")
        self.set("uid", "1000\n")
        self.set("units", "docker.service enabled active\ndocker.socket enabled active\ncontainerd.service enabled active\n"
                          "auditd.service enabled active\napt-daily.timer enabled active\napt-daily-upgrade.timer enabled active\n")
        self.set("lsblk", LSBLK)
        self.set("findmnt", MOUNTS)
        self.set("nvpmodel", "NV Power Mode: EXAMPLE\n1\n")
        self.set("containers", "")
        # the stubs
        _put(self.root / "stubs.py", STUBS_PY)
        for n in PY_STUBS:
            _put(self.bin / n, '#!/bin/bash\nexec "%s" -S -E "%s" %s "$@"\n' % (_fwd(sys.executable), _fwd(self.root / "stubs.py"), n))
        for n, body in BASH_STUBS.items():
            _put(self.bin / n, STUB_HEAD % n + body)
        _put(self.bin / "sudo", SUDO_STUB)
        _put(self.root / "bridge-stub.sh", BRIDGE_STUB)
        for p in list(self.bin.iterdir()) + [self.root / "bridge-stub.sh"]:
            p.chmod(0o755)

    def set(self, name, text):
        _put(self.state / name, text)

    def get(self, name):
        p = self.state / name
        return p.read_bytes().decode() if p.exists() else None

    def installed(self):
        return dict(l.split(" ", 1) for l in self.get("installed").splitlines())

    def backing(self, dev, text):
        """What the fake /sys says is behind a loop device: <dev>/loop/backing_file, as the kernel
        has it for a loop device that is bound to a file (one that is not bound has no such file)."""
        p = self.sys / "block" / dev / "loop" / "backing_file"
        _put(p, text)
        return p

    def provisioned(self):
        """Every default family installed and the login in kvm: what a finished apply leaves."""
        inst = dict(INSTALLED)
        for fam in DEFAULT_FAMILIES:
            todo = FAMILIES[fam].split()
            while todo:
                p = todo.pop()
                if p not in inst:
                    inst[p] = CANDIDATES[p]
                    todo += DEPS.get(p, "").split()
        self.set("installed", _table(inst))
        self.set("groups", "kvm:x:901:%s\ndocker:x:902:\nsudo:x:27:%s\n" % (LOGIN, LOGIN))
        return self

    def tree(self):
        """Every file and directory under the fake roots and the home, with each file's hash."""
        out = {}
        for top in (self.etc, self.sys, self.proc, self.home):
            for d, _dirs, names in os.walk(str(top)):
                rel = os.path.relpath(d, str(self.root)).replace(os.sep, "/")
                out[rel + "/"] = "dir"
                for n in names:
                    with open(os.path.join(d, n), "rb") as f:
                        out[rel + "/" + n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def state_of(self):
        return {n: self.get(n) for n in ("installed", "groups", "nvpmodel", "units", "candidates")}

    def logs(self):
        d = self.home / "provision"
        return sorted(d.iterdir()) if d.exists() else []

    def env(self, **env):
        e = dict(os.environ, STUB_STATE=_fwd(self.state), STUB_MARKER=MARKER, HOME=_fwd(self.home), HOSTNAME=STUB_HOST,
                 ETC_ROOT=_fwd(self.etc), SYS_ROOT=_fwd(self.sys), PROC_ROOT=_fwd(self.proc),
                 BRIDGE_SCRIPT=_fwd(self.root / "bridge-stub.sh"),
                 PATH=_fwd(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        e.pop("PROVISION_ALLOW_REMOVABLE", None)
        e.update(env)
        return e

    def start(self, *args, **env):
        """The script as a process whose output the caller reads, and may stop reading. stderr
        goes where stdout goes: a session that is lost takes both."""
        calls = self.state / "calls.log"
        if calls.exists():
            calls.unlink()
        return subprocess.Popen([BASH, SCRIPT, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=self.env(**env))

    def run(self, *args, **env):
        calls = self.state / "calls.log"
        if calls.exists():
            calls.unlink()
        r = subprocess.run([BASH, SCRIPT, *args], capture_output=True, text=True, timeout=300, env=self.env(**env),
                           stdin=subprocess.DEVNULL)
        r.calls = calls.read_bytes().decode().splitlines() if calls.exists() else []
        r.out = r.stdout.replace("\r\n", "\n")
        r.err = r.stderr.replace("\r\n", "\n")
        r.items = {}
        for line in r.out.split("\n"):
            m = re.match(r"^(ok|missing|differs|note) +(.+?): (.*)$", line)
            if m:
                assert m.group(2) not in r.items, "one line per item: %s" % line
                r.items[m.group(2)] = (m.group(1), m.group(3))
        return r


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path / "board")


def changing(calls):
    """The stub calls that would change a system. A simulation, a query and a listing do not.
    A command run through sudo that is not one of the stubs counts as a change: nothing here could
    see what it did."""
    out = []
    for c in calls:
        w = c.split()
        if w[0] == "sudo":
            cmd = w[1:]
            for opt in ("-k", "-n"):
                cmd = cmd[1:] if cmd[:1] == [opt] else cmd
            if cmd[:1] == ["env"]:
                cmd = cmd[1:]
                while cmd and re.match(r"^[A-Z_]+=", cmd[0]):
                    cmd = cmd[1:]
            if cmd[:5] == ["timeout", "-k", "5", "20", "docker"]:
                cmd = cmd[4:]           # a bound on how long the command may take changes nothing
            if not cmd or cmd[0] not in ("true", "apt-get", "usermod", "docker", "bash"):
                out.append(c)
            elif cmd[0] == "bash" and not cmd[1].endswith("/bridge-stub.sh"):
                out.append(c)
            continue                    # a stub it ran is on the next line, and is judged there
        if w[0] == "apt-get" and not ("install" in w and "-s" in w):
            out.append(c)
        elif w[0] in ("usermod", "bridge-stub"):
            out.append(c)
        elif w[0] == "nvpmodel" and w[1:] != ["-q"]:
            out.append(c)
        elif w[0] == "systemctl" and w[1] not in ("is-active", "is-enabled"):
            out.append(c)
        elif w[0] == "docker" and w[1:] != ["ps", "-a", "-q"]:
            out.append(c)
    return out


def installs(calls):
    """(simulated, argv) for every apt-get call that names `install`."""
    return [("-s" in c.split(), c.split()[1:]) for c in calls if c.split()[0] == "apt-get" and "install" in c.split()]


def names_of(argv):
    """The packages an apt-get argv names: not its options, and not the item an -o carries."""
    return [a for i, a in enumerate(argv) if not a.startswith("-") and a != "install" and argv[i - 1:i] != ["-o"]]


def docker_calls(calls):
    """Every call of the docker client, and every sudo call that names it."""
    return [c for c in calls if c.split()[0] == "docker" or (c.split()[0] == "sudo" and "docker" in c.split())]


def apt_items(argv):
    """The configuration items an apt-get argv sets with -o."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-o"]


def said(r):
    return r.out + r.err


def everything(r, b):
    """Everything a run printed or logged."""
    return said(r) + "".join(p.read_bytes().decode() for p in b.logs())


def one_log(b):
    """The text of the one log an apply leaves."""
    logs = b.logs()
    assert len(logs) == 1, logs
    return logs[0].read_bytes().decode()


def placeless(text, b):
    """A run's text without what differs from one made-up board to the next: where it is, and when."""
    text = text.replace("\r\n", "\n").replace(_fwd(b.root), "<board>")
    text = re.sub(r"provision-\d{8}T\d{6}Z\.log", "provision-<utc>.log", text)
    # The log's own path is $HOME's, and a bash on Windows rewrites HOME into its own form.
    return re.sub(r"(?m)^log: .*/home/provision/", "log: <board>/home/provision/", text)


# ------------------------------------------------------------------ the script's text

def _text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def _program():
    """Everything that runs when the script runs: the script, then the library it sources."""
    return _text(SCRIPT) + "\n" + _text(LIB)


def _code(text):
    """The script without its comments: full-line comments and a trailing ` # ...` are dropped."""
    lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s#\s.*$", "", line))
    return "\n".join(lines)


def _cmds(code):
    """The code with every double-quoted string emptied, so that what a message says is not taken
    for a command. The script keeps to that: a command substitution is assigned without outer
    quotes, and no message holds an escaped quote."""
    return re.sub(r'"[^"\n]*"', '""', code)


def test_the_script_is_there_and_the_placeholder_it_replaces_is_gone():
    text = _text(SCRIPT)
    assert text.startswith("#!/usr/bin/env bash\n") and "\r" not in text
    assert re.search(r"^# Phase \d", text, re.M), "the header carries its Phase tag"
    lib = _text(LIB)
    assert re.search(r"^# Phase \d", lib, re.M) and "\r" not in lib, "so does the library it sources"
    assert not os.path.exists(os.path.join(ORIN, "bootstrap-orin-l4t.sh")), "the TODO placeholder is deleted, not kept beside it"
    launch = _text(os.path.join(ORIN, "launch-qnx-on-orin.sh"))
    assert "bootstrap-orin-l4t.sh" not in launch and "provision-orin-r39.sh" in launch
    for d, _dirs, names in os.walk(os.path.join(REPO, "scripts")):
        for n in names:
            if n.endswith((".sh", ".md", ".py", ".ps1", ".bat")):
                assert "bootstrap-orin-l4t" not in _text(os.path.join(d, n)), "%s still names the deleted script" % n


def test_the_families_are_the_four_listed_and_cuda_is_opt_in():
    code = _code(_text(SCRIPT))
    for fam, pkgs in FAMILIES.items():
        assert '\nPKGS_%s="%s"\n' % (fam, pkgs) in code, fam
    assert '\nDEFAULT_FAMILIES="core build someip"\n' in code
    assert '\nFAMILIES="core build someip cuda"\n' in code


def test_the_script_never_changes_what_it_only_asserts_or_reports():
    """No nvpmodel mode change, no governor write, no gdm or auto-login edit, no sudoers file, no
    unit, no kernel command line, no upgrade, no reboot: none of these has a code path, in the
    script or in the library it sources."""
    text = _program()
    code = _code(text)
    cmds = _cmds(code)
    assert "nvpmodel -m" not in text and "nvpmodel --mode" not in text, "the mode is asserted; the script cannot change it"
    assert re.findall(r"\bnvpmodel +(\S+)", cmds) == ["-q"], "one call, the query"
    # systemd only answers two questions; `status` would print the host name.
    assert re.findall(r"\bsystemctl +(\S+)", cmds) == ["is-enabled", "is-active"]
    for word in ("sed -i", "tee ", "visudo", "groupadd", "gpasswd", "adduser", "update-grub", "extlinux", "kexec",
                 "reboot", "shutdown", "poweroff", "daemon-reload", "upgrade ", "dist-upgrade", "full-upgrade",
                 "autoremove", "apt-mark", "dpkg -i", "modprobe", "sysctl ", "swapoff", "swapon", "eval ", "source ",
                 "curl ", "wget "):
        assert word not in cmds.replace("--no-upgrade ", ""), "%r has a code path" % word
    for cmd in ("cp", "mv", "ln", "dd", "rm", "chmod", "chown", "touch", "truncate", "install", "tee"):
        assert not re.search(r"(^|[;&|(]\s*|\bsudo -n |\bthen |\bdo |\belse )%s\s" % cmd, cmds, re.M), "%s is called" % cmd
    # Everything it runs through sudo, by name; and sudo is never asked for a password. The one
    # question asked of sudo itself goes with -k, so that a cached credential is not the answer.
    assert "sudo" not in re.sub(r"\bsudo (-k )?-n |\bstep_sudo\b", "", cmds), "every sudo is sudo -n"
    assert sorted(set(re.findall(r"\bsudo -n (\S+)", cmds))) == ["apt-get", "bash", "env", "timeout", "usermod"]
    assert re.findall(r"\bsudo -k -n (\S+)", cmds) == ["true"], "-k with the question, and with nothing that runs a command"
    assert "noise=$(sudo -k -n true 2>&1 > /dev/null < /dev/null); rc=$?" in code
    # What sudo said by itself is kept for one test, whether it said anything, and never shown.
    assert re.findall(r"\S*\$\{?noise\b\S*", code) == ['"$noise"'] and '[ -z "$noise" ] || item note "sudo stderr" ' in code
    assert re.findall(r"\busermod (\S+ \S+ \S+)", cmds) == ['-aG kvm ""'], "kvm, and no other group"
    assert 'sudo -n usermod -aG kvm "$LOGIN" ' in code
    # docker is asked one thing, and the bound on it sits inside sudo: a timeout outside would
    # have to rely on sudo passing its signal on to a command that is root's.
    assert re.findall(r"\bdocker (\S+ \S+ \S+)", cmds) == ["ps -a -q"]
    assert "out=$(sudo -n timeout -k 5 20 docker ps -a -q 2>/dev/null < /dev/null); rc=$?" in code
    assert re.findall(r"\btimeout (\S+)", cmds) == ["-k"], "one timeout, and it is that one"
    assert re.findall(r"sudo -n bash (\S+)", code) == ['"$BRIDGE_SCRIPT"']
    # The only file it writes is its own log: every output redirection goes to the log, to
    # /dev/null or to stderr.
    targets = set(t.rstrip(");") for t in re.findall(r"(?<![<&\d-])\d?>>?\s*(\S+)", code))
    assert targets == {'"$LOG"', "/dev/null", "&2", "&1"}, targets
    assert re.findall(r"\bmkdir (\S+ \S+)", code) == ['-p "$dir"'] and code.count('local dir="$HOME/provision"') == 1
    assert code.count('LOG="$dir/provision-$(date -u +%Y%m%dT%H%M%SZ).log"') == 1
    assert len(re.findall(r"(?<![A-Z_])LOG=", code)) == 2, "the log is named once, after its empty start"


def test_no_sudoers_auto_login_or_bridge_unit_write_anywhere_in_the_script():
    code = _code(_program())
    seen = 0
    for line in code.split("\n"):
        if re.search(r"sudoers|visudo|NOPASSWD", line):
            assert re.match(r"^\s*(say|item ok|differs) \"", line), "sudoers is named only in what is said: %s" % line
            seen += 1
        if re.search(r"AutomaticLogin|TimedLogin", line):
            assert re.match(r"^\s*if grep -Eiq '[^']*' \"\$f\" 2>/dev/null; then$", line), "auto-login is only read: %s" % line
            seen += 1
        if "custom.conf" in line or "gdm3" in line:
            assert ">" not in line.replace("2>/dev/null", ""), line
    assert seen >= 5
    for word in ("/etc/systemd", "systemd/system", ".service.d", "WantedBy", "[Unit]", "cmdline", "APPEND", "isolcpus",
                 "--install-bridge-unit", "sudoers.d/$", "> /etc", ">/etc", '> "$ETC', '>"$ETC', '>> "$ETC'):
        assert word not in code, "%r: no unit, no kernel command line, no write under /etc" % word
    # The fake roots are only ever read: no command is given a path under one as a place to write.
    for root in ("$ETC", "$SYSR", "$PROC"):
        for line in code.split("\n"):
            if root in line:
                assert not re.search(r"(?<![<&\d-])\d?>>?\s*\S*%s" % re.escape(root), line), line


def test_the_script_never_asks_the_system_its_name():
    code = _code(_program())
    cmds = _cmds(code)
    for word in ("hostname", "uname", "journalctl", "nmcli", "ifconfig", "machine-id", "/sys/class/dmi", "serial", "address",
                 "hostnamectl", "iwgetid", "ssid", "SSID"):
        assert word not in cmds, word
    assert "hostname" not in code and "uname" not in code and "journalctl" not in code
    assert not re.search(r"(^|[\s;(|&])ip\s", code, re.M), "ip is never called"
    assert "/address" not in code and not re.search(r"\bether\b", code), "no interface address is read"
    # The name the shell itself holds is used in one place, to strike it out of what other
    # commands print, and is never said: it is no argument of anything.
    assert [l.strip() for l in code.split("\n") if "HOSTNAME" in l] == \
        ['if [ -n "${HOSTNAME:-}" ]; then l="${l//"$HOSTNAME"/[host]}"; fi']
    body = re.search(r"\nemit\(\) \{\n(.*?)\n\}\n", code, re.S).group(1)
    assert "HOSTNAME" in body and body.index("HOSTNAME") < body.index('say "  | $l"'), "struck out before the line is said"
    assert body.index('"sudo: unable to resolve host "*) l="sudo: unable to resolve host [not shown]" ;;') < body.index('say "  | $l"')
    # Every command whose own words are logged goes through emit; nothing is logged past it.
    assert len(re.findall(r"2>&1 \| emit$", code, re.M)) == 3 and code.count("| emit") == 4


def test_every_apt_get_install_in_the_text_is_bounded():
    cmds = _cmds(_code(_program()))
    assert re.findall(r"\bapt-get +(\S+)", cmds) == ["update", "-s", "install"], "update, the simulation, the install; nothing else"
    sites = re.findall(r"apt-get (.*\binstall\b.*)$", cmds, re.M)
    assert len(sites) == 2, sites
    for site in sites:
        assert " --no-install-recommends " in site and " --no-upgrade " in site, site
        assert not re.search(r"(^| )(-y|--yes|--assume-yes|--force-yes|--allow-\S+|-f|--fix-broken)( |$)", site), site
    sim, real = sites
    assert sim.startswith("-s install ") and "sudo -n" not in cmds.split("apt-get -s install")[0].split("\n")[-1]
    assert real.startswith("install ") and " --no-remove " in real and " --trivial-only " in real
    assert "sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install " in cmds
    assert "sudo -n apt-get update " in cmds
    # One configuration item is set, on the real install and nowhere else: how long apt-get waits
    # for dpkg's lock. An -o could set anything (a yes to every question among them), so it is
    # held to this one.
    items = [m for line in cmds.split("\n") if "apt-get" in line for m in re.findall(r"\s(?:-o\s*|--option[= ])(\S+)", line)]
    assert items == ["DPkg::Lock::Timeout=120"], items
    assert real.startswith("install -o DPkg::Lock::Timeout=120 --no-install-recommends ") and "-o" not in sim.split()
    # What the stop rules read is apt's own wording, not a translation of it.
    assert "sim=$(LC_ALL=C apt-get -s install " in cmds and "out=$(LC_ALL=C apt-cache policy " in cmds


def test_apply_ignores_a_broken_pipe_and_a_hangup_and_the_log_comes_before_the_print():
    code = _code(_text(SCRIPT))
    lines = code.split("\n")
    assert code.count("trap ") == 1, "one trap, and no other"
    trap = lines.index("[ \"$MODE\" = check ] || trap '' PIPE HUP")
    top = [i for i, l in enumerate(lines) if re.match(r"^(say|item|differs|failed|finish|open_log|step_\w+)\b(?!\(\))", l)]
    assert top and trap < top[0], "ignored before the first line is said and before any step runs"
    body = re.search(r"\nsay\(\) \{\n(.*?)\n\}\n", code, re.S).group(1)
    assert body.index('>> "$LOG"') < body.index("printf '%s\\n' \"$*\" 2> /dev/null"), "the log does not wait on a reader"


# ------------------------------------------------------------------ check

@needs_bash
def test_check_on_a_fresh_board_lists_what_is_missing_and_writes_nothing(board):
    before, state = board.tree(), board.state_of()
    r = board.run("check")
    assert r.returncode == 1, said(r)
    assert board.tree() == before, "check wrote under a fake root or the home"
    assert board.logs() == [] and not (board.home / "provision").exists(), "check writes no log"
    assert board.state_of() == state
    assert changing(r.calls) == [], changing(r.calls)
    assert r.items["packages core"] == ("missing", "qemu-utils ipxe-qemu build-essential")
    assert r.items["packages build"] == ("missing", "g++ cmake")
    assert r.items["packages someip"][0] == "missing" and r.items["packages someip"][1] == FAMILIES["someip"]
    assert "packages cuda" not in r.items and r.items["cuda"][0] == "note"
    assert r.items["kvm group"][0] == "missing"
    assert "sudo stderr" not in r.items, "a sudo that says nothing by itself gets no line"
    for what in ("L4T release", "OS release", "sudo", "installer stick", "qemu-system-arm build", "docker", "nvpmodel",
                 "governor", "gdm Xorg", "halt_poll_ns"):
        assert r.items[what][0] == "ok", (what, r.items[what])
    assert r.out.rstrip().split("\n")[-1] == "check: 10 ok, 4 missing, 0 differs -- apply has something to do", r.out[-300:]
    # What apply would install is shown, from simulations that are themselves bounded and not run as root.
    sims = installs(r.calls)
    assert len(sims) == 3 and all(simulated for simulated, _ in sims), sims
    for _simulated, argv in sims:
        assert "--no-upgrade" in argv and "--no-install-recommends" in argv, argv
    assert not [c for c in r.calls if c.startswith("sudo ") and "apt-get" in c]
    lines = r.out.split("\n")
    assert "  apply would install (7): qemu-utils=1:8.0-q1 ipxe-qemu=1.0-x1 libstdc++-13-dev=13.0-s2 g++-13=13.0-s2 g++=13.0-s1 " \
           "dpkg-dev=1.0-dd1 build-essential=12.0-be1" in lines, r.out
    assert "  apply would install (5): libstdc++-13-dev=13.0-s2 g++-13=13.0-s2 g++=13.0-s1 cmake-data=3.0-m1 cmake=3.0-m1" in lines


@needs_bash
def test_check_on_a_provisioned_board_has_nothing_to_do_and_writes_nothing(board):
    board.provisioned()
    before, state = board.tree(), board.state_of()
    r = board.run("check")
    assert r.returncode == 0, said(r)
    assert board.tree() == before and board.logs() == [] and board.state_of() == state
    assert changing(r.calls) == []
    assert not [c for c in r.calls if c.startswith("apt-get")], "nothing is missing, so apt is not even asked"
    assert [w for w, _ in r.items.values()].count("missing") == 0
    assert r.out.rstrip().split("\n")[-1] == "check: 13 ok, 0 missing, 0 differs -- nothing for apply to do"


@needs_bash
def test_check_is_the_default_and_takes_families(board):
    r = board.run()
    assert r.returncode == 1 and "packages core" in r.items and board.logs() == []
    r = board.run("cuda")
    assert set(k for k in r.items if k.startswith("packages ")) == {"packages cuda"}
    assert r.items["packages cuda"] == ("missing", FAMILIES["cuda"])
    assert changing(r.calls) == [] and board.logs() == []


@needs_bash
def test_check_reports_what_is_only_reported_and_never_changes_it(board):
    r = board.run("check")
    notes = {k: v[1] for k, v in r.items.items() if v[0] == "note"}
    assert "off" in notes["auto-login"] and "never changes it" in notes["auto-login"]
    assert notes["br_netfilter"].startswith("loaded; bridge-nf-call-iptables 1; nemoclaw.conf present; 99-nemoclaw.conf present")
    assert notes["auditd"] == "enabled, active"
    assert notes["swap"] == "none"
    assert notes["apt timers"] == "apt-daily.timer enabled, apt-daily-upgrade.timer enabled"
    assert notes["needrestart"] == "not installed"
    assert notes["network"] == "eth9 wired operstate=down carrier=0; wlan9 wireless operstate=up carrier=1"
    assert notes["kernel.panic"] == "0; kernel.panic_on_oops 1"
    assert notes["bridge"].startswith("br0 absent, tap-qnx absent")
    assert "docker.service=enabled/active" in r.items["docker"][1] and "containers: 0" in r.items["docker"][1]
    assert "is not in the docker group" in r.items["docker"][1]
    board.set("installed", _table(dict(INSTALLED, needrestart="3.0-r1")))
    assert board.run("check").items["needrestart"][1].startswith("installed; apply suspends it")
    # An auto-login that is on is said, and still only said.
    _put(board.etc / "gdm3" / "custom.conf", "[daemon]\nAutomaticLoginEnable = true\nAutomaticLogin = user1\nWaylandEnable=false\n")
    before = board.tree()
    r = board.run("check")
    assert r.items["auto-login"][0] == "note" and "ON" in r.items["auto-login"][1] and "user1" not in said(r)
    assert board.tree() == before


# ------------------------------------------------------------------ apply

@pytest.fixture(scope="module")
def applied(tmp_path_factory):
    """One apply on a fresh board, a second one, then a check."""
    if BASH is None:
        pytest.skip("bash not available")
    b = Board(tmp_path_factory.mktemp("applied") / "board")
    first = b.run("apply")
    first.logs = [p.read_bytes().decode() for p in b.logs()]
    first.installed = b.installed()
    first.tree, first.state = b.tree(), b.state_of()
    second = b.run("apply")
    second.tree, second.state = b.tree(), b.state_of()
    check = b.run("check")
    return b, first, second, check


def test_apply_updates_then_simulates_then_installs_exactly_what_the_simulation_listed(applied):
    b, r, _second, _check = applied
    assert r.returncode == 0, said(r)
    apt = [c for c in r.calls if c.startswith("apt-get")]
    assert apt[0] == "apt-get update", "the lists are refreshed before the first simulation"
    assert len([c for c in apt if c == "apt-get update"]) == 1
    seq = installs(r.calls)
    assert [s for s, _ in seq] == [True, False, True, False, True, False], "simulate, then install, family by family"
    have = set(INSTALLED)
    for (_s, sim), (_i, real), fam in zip(seq[0::2], seq[1::2], DEFAULT_FAMILIES):
        missing = [p for p in FAMILIES[fam].split() if p not in have]
        assert missing and names_of(sim) == missing, "apt is asked only for what is missing"
        have |= set(a.split("=")[0] for a in names_of(real))
        # What the simulation listed: the Inst lines of the stub's output, as printed and logged.
        listed = names_of(real)
        assert listed and all("=" in a for a in listed), "every package is named with the version the simulation showed"
        assert set(a.split("=")[0] for a in listed) >= set(missing)
        for a in listed:
            p, v = a.split("=")
            assert "  | Inst %s (%s " % (p, v) in r.out, "installed something the simulation did not list: %s" % a
            assert b.installed()[p] == v
        assert len(listed) == len(re.findall(r"^  \| Inst ", r.out.split("packages %s:" % fam)[1].split("installing exactly")[0], re.M))
    # Nothing but the listed packages changed, and nothing that was installed moved.
    new = set(r.installed) - set(INSTALLED)
    assert new == set(a.split("=")[0] for _s, argv in seq[1::2] for a in names_of(argv))
    for p, v in INSTALLED.items():
        assert r.installed[p] == v, "%s was upgraded" % p
    assert not set(FAMILIES["cuda"].split()) & set(r.installed), "cuda is opt-in"


def test_every_apt_get_install_carries_no_upgrade_and_no_install_recommends(applied):
    _b, r, _second, _check = applied
    seq = installs(r.calls)
    assert len(seq) == 6
    for simulated, argv in seq:
        assert "--no-upgrade" in argv and "--no-install-recommends" in argv, argv
        if not simulated:
            assert "--no-remove" in argv and "--trivial-only" in argv, argv
            assert not {"-y", "--yes", "--assume-yes", "--force-yes", "--allow-downgrades"} & set(argv), argv
        # The one configuration item ever set: the real install waits for dpkg's lock.
        assert apt_items(argv) == ([] if simulated else ["DPkg::Lock::Timeout=120"]), argv
        assert not [a for a in argv if a.startswith(("-o", "--option")) and a != "-o"], argv
    # The simulation needs no root and gets none; the install and the update go through sudo -n.
    sudo = [c for c in r.calls if c.startswith("sudo ")]
    assert not [c for c in sudo if " -s " in c], "the simulation is not run as root"
    # No prompt can be answered, and needrestart (where installed) is kept from restarting services.
    assert len([c for c in sudo if c.startswith("sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install ")]) == 3
    assert "sudo -n apt-get update" in sudo
    assert sudo[0] == "sudo -k -n true" and all(c.startswith("sudo -n ") for c in sudo[1:]), "-k once, with the question; -n always"


def test_an_installed_package_with_a_newer_candidate_is_not_passed_to_apt_and_not_upgraded(applied):
    _b, r, _second, _check = applied
    assert r.returncode == 0 and len(installs(r.calls)) == 6 and "g++" in r.installed, "apt was called, and installed something"
    for p in ("curl", "bison", "git", "qemu-system-arm"):
        assert CANDIDATES[p] and r.installed[p] == INSTALLED[p]
        for _s, argv in installs(r.calls):
            assert p not in [a.split("=")[0] for a in names_of(argv)], "%s is installed and was named to apt" % p
    assert CANDIDATES["curl"] != INSTALLED["curl"] and CANDIDATES["bison"] != INSTALLED["bison"], "the fixture offers upgrades"


def test_the_kvm_group_addition_is_announced_and_never_silent(applied):
    b, r, _second, _check = applied
    assert [c for c in r.calls if c.startswith("usermod")] == ["usermod -aG kvm %s" % LOGIN]
    assert "sudo -n usermod -aG kvm %s" % LOGIN in r.calls
    lines = r.out.split("\n")
    ann = [i for i, l in enumerate(lines) if l.startswith("ANNOUNCE: ")]
    ran = lines.index("  | stub usermod ran")
    assert len(ann) == 2 and ann[0] < ran < ann[1], "said before it is done, and again after"
    assert "kvm" in lines[ann[0]] and "usermod -aG kvm" in lines[ann[0]] and LOGIN in lines[ann[0]]
    assert "NEW LOGIN" in lines[ann[1]] and "kvm" in lines[ann[1]]
    assert r.items["kvm group"][0] == "ok"
    assert "kvm:x:901:%s\n" % LOGIN in b.get("groups") and "docker:x:902:\n" in b.get("groups"), "kvm, and no other group"
    for text in r.logs:
        assert lines[ann[0]] in text and lines[ann[1]] in text, "the announcement is in the log as well"
    # usermod comes after every package step.
    assert max(i for i, c in enumerate(r.calls) if c.startswith("apt-get")) < r.calls.index("usermod -aG kvm %s" % LOGIN)


def test_apply_writes_one_log_and_nothing_else(applied):
    b, r, second, _check = applied
    assert len(r.logs) == 1
    assert re.match(r"^provision-\d{8}T\d{6}Z\.log$", b.logs()[0].name)
    log = r.logs[0]
    for line in r.out.split("\n"):
        assert line in log, "printed and not logged: %s" % line
    assert "  | Inst qemu-utils (1:8.0-q1 " in log, "the simulation is in the log"
    home = sorted(k for k in r.tree if k.startswith("home/"))
    assert home == ["home/", "home/provision/", "home/provision/" + b.logs()[0].name]
    assert r.out.rstrip().split("\n")[-1] == "apply: every step ok (14 items)"


def test_a_second_apply_changes_nothing(applied):
    b, first, second, check = applied
    assert second.returncode == 0, said(second)
    assert changing(second.calls) == [], changing(second.calls)
    assert not [c for c in second.calls if c.startswith("apt-get")], "nothing is missing: no update, no simulation, no install"
    assert second.state == first.state
    assert "ANNOUNCE" not in second.out
    new = sorted(set(second.tree) - set(first.tree))
    assert len(new) <= 1 and all(re.match(r"^home/provision/provision-\d{8}T\d{6}Z\.log$", n) for n in new), new
    assert {k: v for k, v in second.tree.items() if not k.startswith("home/provision/")} == \
           {k: v for k, v in first.tree.items() if not k.startswith("home/provision/")}
    assert second.out.rstrip().split("\n")[-1] == "apply: every step ok (13 items)"
    assert check.returncode == 0 and check.out.rstrip().split("\n")[-1] == "check: 13 ok, 0 missing, 0 differs -- nothing for apply to do"


@needs_bash
def test_apt_is_asked_in_the_c_locale_whatever_the_callers_is(board):
    """The stop rules and the QEMU rule read apt's own words (Inst, Remv, Installed:, Candidate:).
    apt translates the second pair; the script asks in the C locale, not in the session's."""
    r = board.run("check", LC_ALL="C.UTF-8", LANGUAGE="de")
    assert r.returncode == 1 and len(installs(r.calls)) == 3, said(r)
    r = board.run("apply", LC_ALL="C.UTF-8", LANGUAGE="de")
    assert r.returncode == 0 and len(installs(r.calls)) == 6, said(r)
    assert board.get("sim_lc_all").split("\n") == ["C"] * 6 + [""], "every simulation, in check and in apply"
    policy = board.get("policy_lc_all").split("\n")
    assert len(policy) >= 3 and set(policy) == {"C", ""}, policy


# ------------------------------------------------------------------ a session that is lost

def _lose_the_session(b, mode, how):
    """Run the script and lose its session at a point a stub holds it at, so that nothing here
    depends on who is faster. Returns the exit status and what was read of its output.

    before-the-first-line     the reader of stdout and stderr goes away while the script is in its
                              first call (id), before it has said anything
    during-the-install        the same, once apply has said it is installing and the apt-get stub
                              is in its real install, with nothing installed yet
    hangup-during-the-install the script is sent SIGHUP at that point, and is still read"""
    b.set("id_waits" if how == "before-the-first-line" else "install_waits", "1\n")
    p = b.start(mode)
    guard = threading.Timer(240, p.kill)
    guard.start()
    try:
        read = []
        if how != "before-the-first-line":
            for raw in p.stdout:
                read.append(raw.decode().replace("\r\n", "\n"))
                if read[-1].startswith("  installing exactly what the simulation listed"):
                    break
            assert read and read[-1].startswith("  installing exactly"), "".join(read)[-600:]
            assert b.installed() == INSTALLED, "the install is under way and has installed nothing yet"
        if how == "hangup-during-the-install":
            p.send_signal(signal.SIGHUP)
        else:
            p.stdout.close()                    # nobody reads stdout or stderr from here on
        b.set("go", "1\n")
        if how == "hangup-during-the-install":
            read.append(p.stdout.read().decode().replace("\r\n", "\n"))
        return p.wait(timeout=240), "".join(read)
    finally:
        guard.cancel()
        if p.poll() is None:
            p.kill()
            p.wait()


@needs_bash
@pytest.mark.parametrize("how", ["before-the-first-line", "during-the-install", "hangup-during-the-install"])
def test_apply_runs_on_and_logs_its_outcome_when_its_session_is_lost(board, applied, how):
    """What runbook A would otherwise risk: apply attached to an SSH session that drops, at worst
    while apt is installing. The install must not be cut off, the steps after it must run and be
    checked, and the log must end with the outcome: the same log, line for line, as that of a run
    somebody read to its end."""
    if how.startswith("hangup") and (sys.platform == "win32" or not hasattr(signal, "SIGHUP")):
        pytest.skip("a hangup cannot be sent to the script from this platform")
    ref_board, ref, _second, _check = applied
    rc, read = _lose_the_session(board, "apply", how)
    assert rc == 0, (rc, read[-600:])
    log = one_log(board)
    assert log.rstrip("\n").split("\n")[-1] == "apply: every step ok (14 items)", log[-600:]
    assert board.installed() == ref.installed, "the install was cut off"
    assert "kvm:x:901:%s\n" % LOGIN in board.get("groups"), "the steps after the install ran"
    assert placeless(log, board) == placeless(ref.logs[0], ref_board), "a line was lost or written twice"
    if how.startswith("hangup"):
        assert placeless(read, board) == placeless(ref.out, ref_board), "what was printed is what a run in peace prints"


@needs_bash
def test_check_keeps_the_default_and_dies_with_its_reader(board):
    """check changes nothing, so nothing is owed to a check nobody reads, and it is not left
    running. The board is a provisioned one: a check that ran to its end there would exit 0."""
    board.provisioned()
    rc, _read = _lose_the_session(board, "check", "before-the-first-line")
    assert rc != 0 and board.logs() == []
    calls = (board.state / "calls.log").read_bytes().decode().splitlines()
    assert calls == ["id -un", "id -u"], "it died at the first line it had nobody to say to"


@needs_bash
def test_apply_cuda_installs_that_family_and_no_other(board):
    r = board.run("apply", "cuda")
    assert r.returncode == 0, said(r)
    named = [a.split("=")[0] for s, argv in installs(r.calls) if not s for a in names_of(argv)]
    assert sorted(named) == sorted(FAMILIES["cuda"].split() + ["cuda-cudart-13-2", "libcublas-13-2"])
    assert "g++" not in board.installed() and "qemu-utils" not in board.installed()
    assert set(k for k in r.items if k.startswith("packages ")) == {"packages cuda"}


# ------------------------------------------------------------------ the refusals

def _refused(board, r, where):
    """apply stopped: nothing was installed, nobody was added to a group, and it says where."""
    assert r.returncode == 2, said(r)
    assert not [c for c in changing(r.calls) if c != "apt-get update"], changing(r.calls)
    assert not [1 for s, _ in installs(r.calls) if not s], "an install ran"
    assert not [c for c in r.calls if c.startswith("usermod")]
    stop = [l for l in r.out.split("\n") if l.startswith("STOP at ")]
    assert len(stop) == 1 and stop[0].startswith("STOP at %s: " % where), r.out[-600:]
    assert "apply: every step ok" not in r.out
    return stop[0]


@needs_bash
@pytest.mark.parametrize("lsblk, findmnt, says", [
    ('NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="sda" RM="1" TRAN="usb" TYPE="disk"\n', MOUNTS, "removable block device: sda"),
    ('NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="sdb" RM="0" TRAN="usb" TYPE="disk"\n', MOUNTS, "removable block device: sdb"),
    ('NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="mmcblk1" RM="1" TRAN="" TYPE="disk"\n', MOUNTS, "removable block device: mmcblk1"),
    ('NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\n', MOUNTS + "/media/%s/writable /dev/sda1 rw,nosuid,nodev,relatime\n" % LOGIN,
     "1 mount under /media"),
    ('NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="sda" RM="1" TRAN="usb" TYPE="disk"\n',
     MOUNTS + "/media/%s/writable /dev/sda1 rw,nosuid,nodev,relatime\n/media/%s/two /dev/sda2 ro,nosuid,nodev,relatime\n" % (LOGIN, LOGIN),
     "removable block device: sda; 2 mounts under /media"),
    (LSBLK, "/media tmpfs rw,relatime\n", "1 mount under /media"),
    # A findmnt that says less than it was asked for: a mount point with no source and no options.
    (LSBLK, "/\n/media/%s/writable\n" % LOGIN, "1 mount under /media"),
], ids=["removable", "usb-not-flagged-removable", "removable-not-usb", "mounted", "both", "media-itself", "mount-point-only"])
def test_apply_refuses_while_an_installer_stick_is_plugged_in_or_mounted(board, lsblk, findmnt, says):
    board.set("lsblk", lsblk)
    board.set("findmnt", findmnt)
    before, state = board.tree(), board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "installer stick")
    assert says in stop and "PROVISION_ALLOW_REMOVABLE=1" in stop
    assert "vendor" not in stop, "nothing here is the vendor's image"
    assert changing(r.calls) == [], "refused before the package lists were even refreshed"
    assert not [c for c in r.calls if c.startswith("apt-get")]
    assert board.state_of() == state
    assert LOGIN not in stop, "the mount point is counted, not printed"
    assert stop in one_log(board).split("\n"), "the host is the board, so the refusal is in the log"
    # check reports it and says apply would stop.
    r = board.run("check")
    assert r.returncode == 2 and r.items["installer stick"][0] == "differs" and says in r.items["installer stick"][1]
    assert {k: v for k, v in board.tree().items() if not k.startswith("home/provision")} == before


@needs_bash
def test_a_mount_point_that_only_begins_like_media_is_not_under_it(board):
    board.set("findmnt", MOUNTS + "/media-archive /dev/nvme0n1p3 rw,relatime\n/mediafiles/a /dev/nvme0n1p4 rw,relatime\n"
                                  "/srv/media/a /dev/nvme0n1p5 rw,relatime\n")
    r = board.run("check")
    assert r.items["installer stick"] == ("ok", "no removable or USB block device, nothing mounted under /media"), said(r)


@needs_bash
def test_the_stick_refusal_fails_closed_when_the_devices_cannot_be_listed(board):
    for name in ("lsblk_rc", "findmnt_rc"):
        b = Board(board.root.parent / ("closed-" + name))
        b.set(name, "32\n")
        r = b.run("apply")
        stop = _refused(b, r, "installer stick")
        assert "cannot tell" in stop and changing(r.calls) == []
    for name in ("lsblk", "findmnt"):
        b = Board(board.root.parent / ("closed-empty-" + name))
        b.set(name, "")
        assert "cannot tell" in _refused(b, b.run("apply"), "installer stick")
    # With a mount list that cannot be read nothing is known of /media, so nothing is called the
    # vendor's image, whatever the list would have held.
    b = Board(board.root.parent / "closed-vendor")
    b.set("lsblk", LSBLK + LOOP0)
    b.set("findmnt", MOUNTS + "%s /dev/loop0 %s\n" % (VENDOR_AT, RO_VFAT))
    b.backing("loop0", VENDOR_IMG + "\n")
    b.set("findmnt_rc", "32\n")
    stop = _refused(b, b.run("apply"), "installer stick")
    assert "cannot tell" in stop and "vendor" not in stop


@needs_bash
def test_the_owners_override_lets_apply_proceed_with_a_stick_and_says_so(board):
    board.set("lsblk", 'NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="sda" RM="1" TRAN="usb" TYPE="disk"\n')
    board.set("findmnt", MOUNTS + "/media/%s/writable /dev/sda1 rw,nosuid,nodev,relatime\n" % LOGIN)
    r = board.run("apply", PROVISION_ALLOW_REMOVABLE="1")
    assert r.returncode == 0, said(r)
    assert r.items["installer stick"][0] == "note" and "PROVISION_ALLOW_REMOVABLE=1" in r.items["installer stick"][1]
    assert "removable block device: sda; 1 mount under /media" in r.items["installer stick"][1]
    assert "g++" in board.installed()
    # check says the same, and does not count the stick against apply while the override is given.
    r = board.run("check", PROVISION_ALLOW_REMOVABLE="1")
    assert r.returncode == 0 and r.items["installer stick"][0] == "note", said(r)
    assert board.run("check").returncode == 2
    # Any other value is not the override.
    b = Board(board.root.parent / "other")
    b.set("lsblk", 'NAME="sda" RM="1" TRAN="usb" TYPE="disk"\n')
    _refused(b, b.run("apply", PROVISION_ALLOW_REMOVABLE="yes"), "installer stick")


# ------------------------------------------------------------------ the vendor's image under /media

def _stick_item(r):
    word, text = r.items["installer stick"]
    assert LOGIN not in text, "of a mount point only the last component is ever said: %s" % text
    return word, text


@needs_bash
@pytest.mark.parametrize("loop_line", [LOOP0, 'NAME="loop0" TYPE="loop" RM="0" TRAN=""\n'],
                         ids=["columns-as-asked", "columns-in-another-order"])
def test_the_vendors_read_only_image_under_media_is_not_taken_for_a_stick(board, loop_line):
    """A freshly installed board with no stick in it still has one mount under /media: the
    vendor's documentation image, which the desktop session mounts read-only by itself. lsblk
    lists its loop device as neither removable nor USB, and /sys names the file behind it. Every
    line here has that layout; the login in the mount point is made up."""
    board.set("lsblk", LSBLK + loop_line)
    board.set("findmnt", MOUNTS + "%s /dev/loop0 %s\n" % (VENDOR_AT, RO_VFAT))
    board.backing("loop0", VENDOR_IMG + "\n")
    before, state = board.tree(), board.state_of()
    r = board.run("check")
    assert r.returncode == 1, said(r)            # a fresh board: packages and the group are missing, nothing differs
    word, text = _stick_item(r)
    assert word == "ok", (word, text)
    assert "the vendor's read-only image" in text and "L4T-README" in text and "/opt/nvidia/" in text, text
    assert "no removable or USB block device" in text and "nothing mounted under /media" not in text, text
    assert "/media/" + LOGIN not in said(r) and VENDOR_IMG not in said(r), "neither the mount point nor the file's path is said"
    assert "findmnt -r -n -o TARGET,SOURCE,OPTIONS" in r.calls and "lsblk -d -n -P -o NAME,RM,TRAN,TYPE" in r.calls
    assert board.tree() == before and board.state_of() == state and changing(r.calls) == []
    assert r.out.rstrip().split("\n")[-1] == "check: 10 ok, 4 missing, 0 differs -- apply has something to do"
    # apply goes on, and its log says the same of the stick.
    r = board.run("apply")
    assert r.returncode == 0, said(r)
    assert _stick_item(r) == (word, text) and "g++" in board.installed()
    assert "%-8s %s: %s" % ("ok", "installer stick", text) in one_log(board).split("\n")
    assert "/media/" + LOGIN not in everything(r, board) and VENDOR_IMG not in everything(r, board)
    # And afterwards nothing is left for apply to do. Nothing was refused, so the owner's override
    # has nothing to allow: with it the line is the same.
    r = board.run("check")
    assert r.returncode == 0 and _stick_item(r) == (word, text), said(r)
    assert _stick_item(board.run("check", PROVISION_ALLOW_REMOVABLE="1")) == (word, text)


def _unreadable(p):
    os.chmod(str(p), 0)
    if os.access(str(p), os.R_OK):
        pytest.skip("a file cannot be made unreadable here (Windows, or root)")


# Each row: the mounts under /media, what /sys says is behind each device, and what the refusal
# says. One thing is wrong in each, against the vendor's image as the test above has it.
_STILL_COUNTS = {
    "read-write": ("%s /dev/loop0 %s" % (VENDOR_AT, RW_VFAT), {"loop0": VENDOR_IMG + "\n"}),
    "no-ro-option-of-its-own": ("%s /dev/loop0 nosuid,nodev,relatime,errors=remount-ro" % VENDOR_AT, {"loop0": VENDOR_IMG + "\n"}),
    "ro-inside-another-option": ("%s /dev/loop0 rw,nosuid,zero,euro,ro=1,x-ro" % VENDOR_AT, {"loop0": VENDOR_IMG + "\n"}),
    "no-options-column": ("%s /dev/loop0" % VENDOR_AT, {"loop0": VENDOR_IMG + "\n"}),
    "backing-file-elsewhere": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "/var/lib/made-up/installer.iso\n"}),
    "backing-file-in-a-home": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "/home/%s/Downloads/installer.iso\n" % LOGIN}),
    "backing-file-missing": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {}),
    "backing-file-empty": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": ""}),
    "backing-file-a-blank-line": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "\n" + VENDOR_IMG + "\n"}),
    "backing-file-unreadable": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": (VENDOR_IMG + "\n", _unreadable)}),
    "backing-file-a-directory": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0/loop/backing_file": VENDOR_IMG + "\n"}),
    "another-directory-that-begins-alike": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "/opt/nvidia-other/filesystem.img\n"}),
    "the-directory-and-no-file": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "/opt/nvidia\n"}),
    "the-directory-further-down": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "/srv/opt/nvidia/filesystem.img\n"}),
    "a-relative-path": ("%s /dev/loop0 %s" % (VENDOR_AT, RO_VFAT), {"loop0": "opt/nvidia/filesystem.img\n"}),
    # No such tree exists on a real system (only a loop device has loop/backing_file): it is made
    # here so that the source's name is what decides.
    "not-a-loop-device": ("%s /dev/sda1 %s" % (VENDOR_AT, RO_VFAT), {"sda1": VENDOR_IMG + "\n", "loop0": VENDOR_IMG + "\n"}),
    "a-device-named-like-one": ("%s /dev/mapper/loop0 %s" % (VENDOR_AT, RO_VFAT), {"mapper/loop0": VENDOR_IMG + "\n", "loop0": VENDOR_IMG + "\n"}),
    "a-partition-of-a-loop-device": ("%s /dev/loop0p1 %s" % (VENDOR_AT, RO_VFAT), {"loop0": VENDOR_IMG + "\n", "loop0p1": VENDOR_IMG + "\n"}),
    "a-directory-of-a-loop-device": ("%s /dev/loop0[/docs] %s" % (VENDOR_AT, RO_VFAT), {"loop0": VENDOR_IMG + "\n"}),
    "the-next-loop-device": ("%s /dev/loop1 %s" % (VENDOR_AT, RO_VFAT), {"loop0": VENDOR_IMG + "\n"}),
    "no-source": ("%s  %s" % (VENDOR_AT, RO_VFAT), {"loop0": VENDOR_IMG + "\n"}),
}


@needs_bash
@pytest.mark.parametrize("case", sorted(_STILL_COUNTS))
def test_a_mount_under_media_counts_unless_all_three_hold(board, case):
    """Not a stick only when the source is a loop device, the file behind that device is under
    /opt/nvidia/, and the mount is read-only. With any one of the three wrong, or not readable,
    the mount counts as before."""
    mounts, sysfs = _STILL_COUNTS[case]
    board.set("lsblk", LSBLK + LOOP0)
    board.set("findmnt", MOUNTS + mounts + "\n")
    for dev, text in sysfs.items():
        text, after = text if isinstance(text, tuple) else (text, None)
        p = board.backing(dev, text)
        if after:
            after(p)
    state = board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "installer stick")
    assert "1 mount under /media" in stop and "vendor" not in stop and LOGIN not in stop, stop
    assert changing(r.calls) == [] and not [c for c in r.calls if c.startswith("apt-get")] and board.state_of() == state
    r = board.run("check")
    assert r.returncode == 2 and _stick_item(r)[0] == "differs" and "1 mount under /media" in _stick_item(r)[1], said(r)


@needs_bash
def test_a_loop_mount_whose_file_is_on_a_stick_counts_and_so_does_the_stick(board):
    """An image mounted from the stick itself: the file behind the loop device is under the
    stick's own mount point, which is not /opt/nvidia/, and lsblk's rule sees the stick as before."""
    board.set("lsblk", LSBLK + STICK + LOOP0)
    board.set("findmnt", MOUNTS + "/media/%s/INSTALLER /dev/sda1 ro,nosuid,nodev,relatime\n%s /dev/loop0 %s\n" % (LOGIN, VENDOR_AT, RO_VFAT))
    board.backing("loop0", "/media/%s/INSTALLER/casper/filesystem.img\n" % LOGIN)
    stop = _refused(board, board.run("apply"), "installer stick")
    assert "removable block device: sda; 2 mounts under /media" in stop and "vendor" not in stop and LOGIN not in stop, stop


@needs_bash
@pytest.mark.parametrize("lsblk, says", [
    (LSBLK + STICK + LOOP0, "removable block device: sda"),
    (LSBLK + 'NAME="sdb" RM="0" TRAN="usb" TYPE="disk"\n' + LOOP0, "removable block device: sdb"),
    (LSBLK + 'NAME="loop0" RM="1" TRAN="" TYPE="loop"\n', "removable block device: loop0"),
    (LSBLK + 'NAME="loop0" RM="0" TRAN="usb" TYPE="loop"\n', "removable block device: loop0"),
], ids=["a-stick-beside-it", "a-usb-disk-beside-it", "the-loop-device-removable", "the-loop-device-usb"])
def test_the_vendors_image_does_not_hide_a_removable_or_usb_device(board, lsblk, says):
    """lsblk's rule is as it was. The image is still named, as what was not counted."""
    board.set("lsblk", lsblk)
    board.set("findmnt", MOUNTS + "%s /dev/loop0 %s\n" % (VENDOR_AT, RO_VFAT))
    board.backing("loop0", VENDOR_IMG + "\n")
    r = board.run("apply")
    stop = _refused(board, r, "installer stick")
    assert says in stop and "under /media" not in stop.split("; not counted: ")[0], stop
    assert stop.count("the vendor's read-only image") == 1 and "not counted: the vendor's read-only image (L4T-README" in stop, stop
    assert LOGIN not in stop and changing(r.calls) == []
    r = board.run("check")
    assert r.returncode == 2 and _stick_item(r)[0] == "differs" and says in _stick_item(r)[1]
    # The owner's override says both as well.
    r = board.run("check", PROVISION_ALLOW_REMOVABLE="1")
    word, text = _stick_item(r)
    assert word == "note" and says in text and "not counted: the vendor's read-only image (L4T-README" in text, text


@needs_bash
@pytest.mark.parametrize("order", ["image-first", "image-last"])
def test_the_vendors_image_does_not_hide_another_mount_under_media(board, order):
    """Each mount is judged by its own device and its own options: the image beside a stick's
    partition, read-write or read-only, and beside a second loop device whose file is somewhere
    else."""
    image = "%s /dev/loop0 %s\n" % (VENDOR_AT, RO_VFAT)
    for n, other in enumerate(["/media/%s/writable /dev/sda1 rw,nosuid,nodev,relatime\n" % LOGIN,
                               "/media/%s/two /dev/sda2 ro,nosuid,nodev,relatime\n" % LOGIN,
                               "/media/%s/OTHER /dev/loop1 %s\n" % (LOGIN, RO_VFAT)]):
        b = Board(board.root.parent / ("beside-%d" % n))
        b.set("lsblk", LSBLK + LOOP0 + 'NAME="loop1" RM="0" TRAN="" TYPE="loop"\n')
        b.set("findmnt", MOUNTS + (image + other if order == "image-first" else other + image))
        b.backing("loop0", VENDOR_IMG + "\n")
        b.backing("loop1", "/var/lib/made-up/installer.iso\n")
        r = b.run("apply")
        stop = _refused(b, r, "installer stick")
        assert "STOP at installer stick: 1 mount under /media; not counted: the vendor's read-only image (L4T-README" in stop, stop
        assert "OTHER" not in stop and "writable" not in stop and LOGIN not in stop, stop
        assert changing(r.calls) == []
        assert _stick_item(b.run("check"))[0] == "differs"


@needs_bash
@pytest.mark.parametrize("target, source, backing, named", [
    (VENDOR_AT, "/dev/loop12", VENDOR_IMG + "\n", "L4T-README"),
    (VENDOR_AT, "/dev/loop0", VENDOR_IMG, "L4T-README"),
    (VENDOR_AT, "/dev/loop0", "/opt/nvidia/made-up/dir/other.img (deleted)\n", "L4T-README"),
    ("/media/%s/a/b/NOTES" % LOGIN, "/dev/loop0", VENDOR_IMG + "\n", "NOTES"),
    ("/media/L4T-README", "/dev/loop0", VENDOR_IMG + "\n", "[not shown]"),
    ("/media/%s" % LOGIN, "/dev/loop0", VENDOR_IMG + "\n", "[not shown]"),
    ("/media", "/dev/loop0", VENDOR_IMG + "\n", "[not shown]"),
], ids=["a-two-digit-loop-device", "no-newline", "file-deleted-since", "further-down", "directly-under-media",
        "at-the-logins-own-directory", "media-itself"])
def test_how_the_vendors_image_is_named(board, target, source, backing, named):
    """By the last component of its mount point and nothing more. A mount point one level under
    /media (or /media itself) is not named at all: that level is the login's own directory where
    the desktop mounts things, so its name can be a login."""
    board.set("lsblk", LSBLK + 'NAME="%s" RM="0" TRAN="" TYPE="loop"\n' % source[len("/dev/"):])
    board.set("findmnt", MOUNTS + "%s %s %s\n" % (target, source, RO_VFAT))
    board.backing(source[len("/dev/"):], backing)
    r = board.run("check")
    word, text = _stick_item(r)
    assert word == "ok" and "the vendor's read-only image (%s: " % named in text, (word, text)
    assert LOGIN not in text and backing.strip() not in said(r)
    assert r.returncode == 1, said(r)


@needs_bash
def test_two_images_of_the_vendors_are_both_named_and_neither_counts(board):
    board.set("lsblk", LSBLK + LOOP0 + 'NAME="loop1" RM="0" TRAN="" TYPE="loop"\n')
    board.set("findmnt", MOUNTS + "%s /dev/loop0 %s\n/media/%s/SECOND /dev/loop1 ro,relatime\n" % (VENDOR_AT, RO_VFAT, LOGIN))
    board.backing("loop0", VENDOR_IMG + "\n")
    board.backing("loop1", "/opt/nvidia/made-up/second.img\n")
    word, text = _stick_item(board.run("check"))
    assert word == "ok" and "the vendor's read-only image (L4T-README, SECOND: " in text, (word, text)


def test_the_stick_step_asks_for_three_columns_and_reads_the_backing_file_under_the_sys_root():
    code = _code(_program())
    cmds = _cmds(code)
    assert re.findall(r"\bfindmnt (.*?) 2>", cmds) == ["-r -n -o TARGET,SOURCE,OPTIONS"], "the source and the options as well as the target"
    assert re.findall(r"\blsblk (.*?) 2>", cmds) == ["-d -n -P -o NAME,RM,TRAN,TYPE"], "lsblk is asked what it was"
    # What is behind a loop device is read from sysfs, under the root a test can redirect, and by
    # no command: nothing is run that would print the file's whole path, or change a mount.
    assert code.count("/loop/backing_file") == 1 and 'first_line "$SYSR/block/${BASH_REMATCH[1]}/loop/backing_file"' in code
    assert "/sys/block" not in code
    for word in ("losetup", "udisksctl", "blkid", "umount", "mount ", "mountpoint", "eject"):
        assert word not in cmds, "%r has a code path" % word
    # The mount point is never said whole: of the three columns only the last component of the
    # first reaches a message, and only for the vendor's image. The rule's body is the library's
    # stick_rule since the rule moved there, and what it says leaves it in STICK_TEXT.
    body = re.search(r"\nstick_rule\(\) \{\n(.*?)\n\}\n", _code(_text(LIB)), re.S).group(1)
    assert re.findall(r"\$\{?target\b[^\s\"]*", body) == ["$target", "$target", "${target##*/}"], "tested twice, and its last component taken"
    said_lines = [l for l in body.split("\n") if re.search(r"\b(item|differs|say)\b|\b(what|vendor|unknown|STICK_TEXT)=", l)]
    assert len(said_lines) >= 8 and not re.search(r"\$\{?(target|src|opts|FL|line|out)\b", "\n".join(said_lines)), said_lines


def test_the_stick_rule_is_the_librarys_and_the_script_holds_no_copy_of_it():
    """The rule moved to lib-stick.sh, which gate2-smoke.sh sources as well: one rule, one text.
    The script keeps the step that says the rule's outcome as its item, and nothing of the rule."""
    script, lib = _code(_text(SCRIPT)), _code(_text(LIB))
    # Sourced once, from beside the script, after the roots it reads are set; and no other file is.
    assert re.findall(r"(?m)^\s*(?:\.|source)\s+(\S+)", script) == ['"$here/lib-stick.sh"']
    assert script.index('SYSR="${SYS_ROOT:-/sys}"') < script.index('. "$here/lib-stick.sh"') < script.index("\nMODE=check\n")
    assert not re.search(r"(?m)^\s*(?:\.|source)\s", lib), "the library sources nothing"
    # What the script still has of the stick: the call, and the item.
    body = re.search(r"\nstep_stick\(\) \{\n(.*?)\n\}\n", script, re.S).group(1)
    assert [l.strip() for l in body.split("\n")] == [
        "stick_rule apply",
        'case "$STICK_WORD" in',
        'ok|note) item "$STICK_WORD" "installer stick" "$STICK_TEXT" ;;',
        '*) differs "installer stick" "$STICK_TEXT" ;;',
        "esac"]
    for word in ("lsblk", "findmnt", "backing_file", "/media", "PROVISION_ALLOW_REMOVABLE", "first_line()"):
        assert word not in script, "%r is the library's, and the script holds no second copy" % word
    assert lib.count("stick_rule() {") == 1 and lib.count("first_line() {") == 1
    # The override is one variable, read in one place, and the refusal's words are one string
    # whose only variable part is who refuses.
    assert re.findall(r"\$\{(\w*ALLOW\w*)[:}]", lib) == ["PROVISION_ALLOW_REMOVABLE"]
    assert lib.count('STICK_TEXT="$what -- $who refuses while it is there: a reset would walk the boot order with an '
                     "unattended installer attached. The owner removes it; PROVISION_ALLOW_REMOVABLE=1 is the owner's override\"") == 1
    assert lib.count('STICK_TEXT="$what -- allowed by PROVISION_ALLOW_REMOVABLE=1, the owner\'s override"') == 1
    # Sourcing it runs nothing: outside its two functions it only gives three variables their
    # empty start.
    inside, top = False, []
    for line in lib.split("\n"):
        if re.match(r"^\w+\(\) \{", line):
            inside = True
        elif line == "}":
            inside = False
        elif not inside and line.strip():
            top.append(line)
    assert top == ['FL=""', 'STICK_WORD=""', 'STICK_TEXT=""'], top


@needs_bash
@pytest.mark.parametrize("release, osr, where", [
    ("# R36 (release), REVISION: 4.7, GCID: 12345678, BOARD: generic, EABI: aarch64, DATE: made up\n", None, "L4T release"),
    (None, 'PRETTY_NAME="Ubuntu 22.04.9 LTS (made up)"\nVERSION_ID="22.04"\nID=ubuntu\n', "OS release"),
    ("", None, "L4T release"),
    ("# R3 (release), REVISION: 9.9\n", None, "L4T release"),
    ("# R390 (release), REVISION: 9.9\n", None, "L4T release"),
], ids=["r36", "jammy", "no-release-line", "r3", "r390"])
def test_apply_refuses_a_host_that_is_not_the_expected_release_and_writes_nothing_there(board, release, osr, where):
    if release is not None:
        _put(board.etc / "nv_tegra_release", release)
    if osr is not None:
        _put(board.etc / "os-release", osr)
    before = board.tree()
    r = board.run("apply")
    _refused(board, r, where)
    assert changing(r.calls) == [] and not [c for c in r.calls if c.startswith(("apt-get", "sudo"))], r.calls
    assert board.tree() == before, "not the board: not even a log is written"
    r = board.run("check")
    assert r.returncode == 2 and r.items[where][0] == "differs"


@needs_bash
def test_a_host_without_the_release_file_is_refused(board):
    (board.etc / "nv_tegra_release").unlink()
    before = board.tree()
    r = board.run("apply")
    assert "absent" in _refused(board, r, "L4T release")
    assert board.tree() == before


@needs_bash
def test_without_sudo_apply_stops_with_the_owners_line_and_writes_no_sudoers_file(board):
    board.set("sudo_denied", "1")
    r = board.run("apply")
    stop = _refused(board, r, "sudo")
    assert "the owner's" in stop
    assert "    %s ALL=(ALL) NOPASSWD:ALL" % LOGIN in r.out.split("\n"), "the line the owner has to add, printed"
    log = one_log(board).split("\n")
    assert stop in log and "    %s ALL=(ALL) NOPASSWD:ALL" % LOGIN in log, "the host is the board, so the refusal is in the log"
    assert changing(r.calls) == []
    assert [c for c in r.calls if c.startswith("sudo ")] == ["sudo -k -n true"], "asked once, and nothing else was tried"
    assert not (board.etc / "sudoers.d").exists() and not (board.etc / "sudoers").exists()
    for c in r.calls:
        assert "sudoers" not in c and "visudo" not in c and "tee" not in c.split(), c
    assert "a password is required" not in everything(r, board), "what sudo answered is not shown: sudo may name the host there"
    r = board.run("check")
    assert r.returncode == 2 and r.items["sudo"][0] == "differs"
    assert "not counted" in r.items["docker"][1]
    assert [c for c in r.calls if c.startswith("sudo ")] == ["sudo -k -n true"]


@needs_bash
def test_a_cached_sudo_credential_is_not_taken_for_the_owners_sudoers_line(board):
    """`sudo -n true` also succeeds for a while after any sudo with a password. The script would
    say sudo works and then fail at its first real call, or later, after a long install. Asked
    with -k, sudo does not use the cached credential (and does not renew it), so the answer is
    about the sudoers line."""
    board.set("sudo_cached", "1\n")
    state = board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "sudo")
    assert "the owner's" in stop and "    %s ALL=(ALL) NOPASSWD:ALL" % LOGIN in r.out.split("\n")
    assert [c for c in r.calls if c.startswith("sudo ")] == ["sudo -k -n true"]
    assert changing(r.calls) == [] and not [c for c in r.calls if c.startswith("apt-get")] and board.state_of() == state
    r = board.run("check")
    assert r.returncode == 2 and r.items["sudo"][0] == "differs"
    assert [c for c in r.calls if c.startswith("sudo ")] == ["sudo -k -n true"]


@needs_bash
def test_the_script_refuses_to_run_as_root(board):
    board.set("uid", "0\n")
    before = board.tree()
    for mode in ("apply", "check"):
        r = board.run(mode)
        assert r.returncode == 2 and "as root" in r.err, said(r)
        assert [c for c in r.calls if not c.startswith("id ")] == [], r.calls
    assert board.tree() == before


@needs_bash
@pytest.mark.parametrize("args, says", [
    (("apply", "tensorrt"), "unknown argument: tensorrt"),
    (("apply", "--install-bridge-unit"), "unknown argument: --install-bridge-unit"),
    (("apply", "--set-xorg"), "--set-xorg"),
    (("upgrade",), "unknown argument: upgrade"),
    (("apply", "check"), "unknown argument: check"),
])
def test_an_unknown_argument_is_a_usage_error_before_anything_is_read(board, args, says):
    before = board.tree()
    r = board.run(*args)
    assert r.returncode == 64 and says in r.err, said(r)
    assert r.calls == [] and board.tree() == before


@needs_bash
def test_help_prints_the_usage_and_reads_nothing(board):
    r = board.run("--help")
    assert r.returncode == 0 and r.out.startswith("usage: bash provision-orin-r39.sh [check|apply] [--bridge] ")
    assert r.calls == [] and board.logs() == []


# ------------------------------------------------------------------ the simulation's stop rules

@needs_bash
@pytest.mark.parametrize("extra, says", [
    ("Remv libold-thing [1.0-r1]\n", "apt would remove libold-thing"),
    ("Purg libold-thing [1.0-r1]\n", "apt would remove libold-thing"),
    ("Inst nvidia-l4t-core (39.9-n2 made-up:r39 [arm64])\n", "apt would touch nvidia-l4t-core"),
    ("Inst nvidia-l4t-kernel [6.8-n1] (6.8-n2 made-up:r39 [arm64])\n", "apt would touch nvidia-l4t-kernel"),
    ("Inst linux-image-6.8.0-99-generic (6.8-k1 Ubuntu:24.04/noble-updates [arm64])\n", "apt would touch linux-image-6.8.0-99-generic"),
    ("Inst linux-headers-6.8.0-99 (6.8-k1 Ubuntu:24.04/noble-updates [arm64])\n", "apt would touch linux-headers-6.8.0-99"),
    ("Conf nvidia-l4t-core (39.9-n2 made-up:r39 [arm64])\n", "apt would touch nvidia-l4t-core"),
    ("Inst linux-modules-6.8.0-99-generic (6.8-k1 Ubuntu:24.04/noble-updates [arm64])\n", "apt would touch linux-modules-6.8.0-99-generic"),
    ("Inst linux-tegra-6.8 (6.8-k1 made-up:r39 [arm64])\n", "apt would touch linux-tegra-6.8"),
    ("Inst linux-nvidia-tegra (6.8-k1 made-up:r39 [arm64])\n", "apt would touch linux-nvidia-tegra"),
    ("Inst linux-generic (6.8-k1 Ubuntu:24.04/noble-updates [arm64])\n", "apt would touch linux-generic"),
    ("Inst linux-firmware (2024-f1 Ubuntu:24.04/noble-updates [arm64])\n", "apt would touch linux-firmware"),
    ("Inst libcurl4t64 [8.0-c1] (8.0-c2 Ubuntu:24.04/noble-updates [arm64])\n", "apt would upgrade the installed libcurl4t64"),
    ("Inst something unreadable\n", "cannot be read"),
    ("Inst bad_name (1.0 Ubuntu:24.04/noble [arm64])\n", "cannot be read"),
    ("Inst okname (1.0;rm Ubuntu:24.04/noble [arm64])\n", "cannot be read"),
], ids=["removal", "purge", "nvidia-l4t-new", "nvidia-l4t-kernel", "kernel-image", "kernel-headers", "nvidia-l4t-conf-only",
        "kernel-modules", "linux-tegra", "linux-nvidia", "linux-generic", "linux-firmware", "upgrade", "unreadable",
        "bad-name", "bad-version"])
def test_a_simulation_that_removes_upgrades_or_touches_nvidia_or_the_kernel_stops_before_any_install(board, extra, says):
    board.set("sim_extra", extra)
    state = board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "packages core simulation")
    assert says in stop, stop
    assert board.state_of() == state
    assert [c for c in changing(r.calls)] == ["apt-get update"]
    assert len(installs(r.calls)) == 1 and installs(r.calls)[0][0], "one simulation, and nothing after it"
    assert "  | " + extra.strip() in r.out, "the simulation is printed before the stop"
    r = board.run("check")
    assert r.returncode == 2 and r.items["packages core simulation"][0] == "differs" and says in r.items["packages core simulation"][1]


@needs_bash
def test_linux_libc_dev_is_not_taken_for_a_kernel_package(board):
    """The g++ chain may pull the C library's kernel headers; that is a userspace package."""
    c = dict(CANDIDATES, **{"linux-libc-dev": "6.8-h1"})
    board.set("candidates", _table(c))
    board.set("deps", _table(dict(DEPS, **{"g++-13": "libstdc++-13-dev linux-libc-dev"})))
    r = board.run("apply")
    assert r.returncode == 0, said(r)
    assert board.installed()["linux-libc-dev"] == "6.8-h1"


@needs_bash
def test_a_simulation_that_fails_or_lists_nothing_stops(board):
    board.set("sim_rc", "100\n")
    assert "exited 100" in _refused(board, board.run("apply"), "packages core simulation")
    b = Board(board.root.parent / "nothing")
    c = dict(CANDIDATES)
    del c["qemu-utils"]
    b.set("candidates", _table(c))                  # apt cannot locate a package the family names
    r = b.run("apply")
    stop = _refused(b, r, "packages core simulation")
    assert "exited 100" in stop and "lists nothing to install" in stop and "does not install qemu-utils" in stop


@needs_bash
def test_a_newer_qemu_candidate_is_refused_by_name_before_any_simulation(board):
    board.set("candidates", _table(dict(CANDIDATES, **{"qemu-system-arm": "1:8.0-q2", "qemu-utils": "1:8.0-q2"})))
    state = board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "qemu-system-arm build")
    assert "installed 1:8.0-q1" in stop and "candidate 1:8.0-q2" in stop and "the owner's" in stop
    assert installs(r.calls) == [], "not even simulated"
    assert board.state_of() == state
    r = board.run("check")
    assert r.returncode == 2 and r.items["qemu-system-arm build"][0] == "differs"


@needs_bash
def test_the_qemu_candidate_is_read_after_the_lists_are_refreshed(board):
    """The candidate that matters is the one apt would install: the one after apt-get update."""
    board.set("candidates.after-update", _table(dict(CANDIDATES, **{"qemu-system-arm": "1:8.0-q3"})))
    r = board.run("apply")
    assert "candidate 1:8.0-q3" in _refused(board, r, "qemu-system-arm build")
    assert r.calls.index("apt-get update") < r.calls.index("apt-cache policy qemu-system-arm")


@needs_bash
def test_a_moved_qemu_candidate_is_only_a_note_when_core_has_nothing_to_install(board):
    board.provisioned()
    board.set("candidates", _table(dict(CANDIDATES, **{"qemu-system-arm": "1:8.0-q2"})))
    r = board.run("apply")
    assert r.returncode == 0, said(r)
    assert r.items["qemu-system-arm build"] == ("note", "installed 1:8.0-q1; candidate 1:8.0-q2; nothing of core is missing, so apt is not called")
    assert board.installed()["qemu-system-arm"] == "1:8.0-q1" and changing(r.calls) == []


@needs_bash
def test_an_unversioned_boost_dev_package_refuses_the_someip_family(board):
    board.set("installed", _table(dict(INSTALLED, **{"libboost-system-dev": "1.83-u1"})))
    r = board.run("apply")
    assert r.returncode == 2
    stop = [l for l in r.out.split("\n") if l.startswith("STOP at ")]
    assert stop and stop[0].startswith("STOP at packages someip: ") and "libboost-system-dev" in stop[0] and "cannot coexist" in stop[0]
    for _s, argv in installs(r.calls):
        assert not [a for a in argv if "boost" in a], "no Boost package was simulated or installed"
    assert not [c for c in r.calls if c.startswith("usermod")]
    r = board.run("check")
    assert r.returncode == 2 and r.items["packages someip"][0] == "differs"


# ------------------------------------------------------------------ nothing is changed before a refusal

def _differs_on_a_fresh_board(b, where):
    """Make one thing the script only asserts differ, on a board that is otherwise fresh: three
    families to install and a group to join. Returns the run's extra arguments and environment."""
    args, env = (), {}
    if where == "docker":
        (b.etc / "docker" / "daemon.json").unlink()
    elif where == "nvpmodel":
        b.set("nvpmodel", "NV Power Mode: OTHER\n2\n")
    elif where == "governor":
        _put(b.sys / "devices" / "system" / "cpu" / "cpufreq" / "policy4" / "scaling_governor", "performance\n")
    elif where == "gdm Xorg":
        _put(b.etc / "gdm3" / "custom.conf", "[daemon]\n")
    elif where == "halt_poll_ns":
        _put(b.sys / "module" / "kvm" / "parameters" / "halt_poll_ns", "0\n")
    elif where == "kvm group":
        b.set("groups", "docker:x:902:\nsudo:x:27:%s\n" % LOGIN)
    elif where == "bridge":
        args, env = ("--bridge",), {"BRIDGE_SCRIPT": _fwd(b.root / "no-such-bridge-script.sh")}
    elif where == "packages someip":
        b.set("installed", _table(dict(INSTALLED, **{"libboost-system-dev": "1.83-u1"})))
    else:
        assert where == "packages build", where
        b.set("installed", _table(dict(INSTALLED, cmake=CANDIDATES["cmake"])))
        b.set("dpkg_state", "cmake install ok half-configured %s\n" % CANDIDATES["cmake"])
    return args, env


@needs_bash
@pytest.mark.parametrize("where", ["docker", "nvpmodel", "governor", "gdm Xorg", "halt_poll_ns", "kvm group", "bridge",
                                   "packages someip", "packages build"])
def test_what_is_only_asserted_is_read_before_the_first_change(board, where):
    """A fresh board has three families to install and a group to join. Whatever the script only
    asserts must stop apply before any of that: before the package lists are refreshed, before a
    package is installed, before the login joins a group. (The refusals that read the archive, a
    moved QEMU candidate and a simulation's stop rules, come after the refresh; they are tested
    with the simulation.)"""
    args, env = _differs_on_a_fresh_board(board, where)
    before, state = board.tree(), board.state_of()
    r = board.run("apply", *args, **env)
    _refused(board, r, where)
    assert changing(r.calls) == [], "the board was changed before apply stopped"
    assert not [c for c in r.calls if c.startswith("apt-get")], "not a simulation, and the lists were not refreshed"
    assert not [c for c in r.calls if c.startswith(("usermod", "bridge-stub"))]
    assert board.state_of() == state, "a package was installed, or the login joined a group"
    assert {k: v for k, v in board.tree().items() if not k.startswith("home/provision")} == before
    r = board.run("check", *args, **env)
    assert r.returncode == 2 and r.items[where][0] == "differs", said(r)
    assert r.items["packages core"][0] == "missing", "check goes on, and still says what apply would install"


@needs_bash
@pytest.mark.parametrize("status", ["install ok half-configured", "install ok unpacked", "install ok half-installed",
                                    "install reinstreq half-installed", "install reinstreq installed",
                                    "install ok triggers-awaited", "install ok triggers-pending", "hold ok half-configured"])
def test_a_package_dpkg_left_unfinished_is_named_with_its_state_and_apt_is_not_called(board, status):
    """An install that was interrupted or failed leaves a package between states. Read as plain
    missing it went to apt, whose simulation skips it (apt's own table has it), and the stop named
    the simulation: a simulation takes no dpkg lock, so apt's own "dpkg was interrupted" never
    shows in one. The script names dpkg's state, and calls no apt at all."""
    board.set("installed", _table(dict(INSTALLED, cmake=CANDIDATES["cmake"])))
    board.set("dpkg_state", "cmake %s %s\n" % (status, CANDIDATES["cmake"]))
    state = board.state_of()
    r = board.run("apply", "build")
    stop = _refused(board, r, "packages build")
    assert "cmake is '%s'" % status in stop and "dpkg --configure -a" in stop and "the owner's" in stop, stop
    assert not [c for c in r.calls if c.startswith("apt-get")], "no update, no simulation, no install"
    assert changing(r.calls) == [] and board.state_of() == state
    r = board.run("check")
    what = r.items["packages build"]
    assert r.returncode == 2 and what[0] == "differs" and "cmake is '%s'" % status in what[1], said(r)
    assert "packages build simulation" not in r.items, "the family is not simulated: what stops it is dpkg's state"
    sims = installs(r.calls)
    assert len(sims) == 2 and not [1 for _s, argv in sims if {"cmake", "g++"} & set(names_of(argv))], sims


@needs_bash
def test_every_unfinished_package_of_a_family_is_named_and_the_other_families_are_still_looked_at(board):
    board.set("installed", _table(dict(INSTALLED, **{"cmake": CANDIDATES["cmake"], "g++": CANDIDATES["g++"]})))
    board.set("dpkg_state", "cmake install ok unpacked %s\ng++ install ok half-configured %s\n" % (CANDIDATES["cmake"], CANDIDATES["g++"]))
    r = board.run("check")
    what = r.items["packages build"]
    assert r.returncode == 2 and what[0] == "differs", said(r)
    assert "g++ is 'install ok half-configured'; cmake is 'install ok unpacked'" in what[1], what
    assert r.items["packages core"][0] == "missing" and r.items["packages someip"][0] == "missing"


# ------------------------------------------------------------------ an action that fails stops the run

def _failed(r, says):
    assert r.returncode == 1, said(r)
    fail = [l for l in r.out.split("\n") if l.startswith("FAILED: ")]
    assert len(fail) == 1 and says in fail[0], r.out[-600:]
    assert not [c for c in r.calls if c.startswith("usermod")], "the run went on to usermod"
    assert "apply: every step ok" not in r.out


@needs_bash
def test_a_failing_apt_get_stops_the_run_before_usermod(board):
    board.set("install_rc", "100\n")
    r = board.run("apply")
    _failed(r, "apt-get install for core exited 100")
    assert len([1 for s, _ in installs(r.calls) if not s]) == 1, "the next family was not tried"
    assert board.installed() == INSTALLED and LOGIN not in board.get("groups").split("\n")[0]


@needs_bash
def test_a_failing_apt_get_update_stops_before_any_simulation(board):
    board.set("update_rc", "100\n")
    r = board.run("apply")
    _failed(r, "apt-get update exited 100")
    assert installs(r.calls) == []


@needs_bash
def test_the_install_waits_for_dpkgs_lock_where_apt_get_alone_gives_up_at_once(board):
    """The board's daily apt timers can hold dpkg's lock when apply gets to an install. apt-get
    does not wait for it unless it is told to; a run that ends there has installed nothing, but
    it reads like a failure and has to be started again by hand."""
    board.set("dpkg_locked", "1\n")
    r = board.run("apply")
    assert r.returncode == 0, said(r)
    assert "Could not get lock" not in r.out and "g++" in board.installed()
    assert [apt_items(argv) for s, argv in installs(r.calls) if not s] == [["DPkg::Lock::Timeout=120"]] * 3


@needs_bash
def test_apt_is_not_left_to_install_more_than_the_simulation_listed(board):
    """A dependency that appears between the simulation and the install: apt is told to do only
    the trivial thing (exactly the named packages), so it refuses, and the run stops."""
    board.set("install_needs_also", "late-dependency\n")
    r = board.run("apply")
    _failed(r, "apt-get install for core exited 100")
    assert "Trivial Only specified but this is not a trivial operation." in r.out
    assert board.installed() == INSTALLED


@needs_bash
def test_each_package_is_checked_after_the_install(board):
    board.set("install_drops", "ipxe-qemu\n")
    r = board.run("apply")
    _failed(r, "ipxe-qemu")
    assert "is not installed" in r.out


@needs_bash
def test_a_package_installed_at_another_version_than_the_simulated_one_fails_the_step(board):
    board.set("install_as", "ipxe-qemu 1.0-x0\n")
    r = board.run("apply")
    _failed(r, "ipxe-qemu is installed at 1.0-x0, not at the simulated 1.0-x1")
    assert board.installed()["ipxe-qemu"] == "1.0-x0", "the fixture did install it, at the other version"
    assert len([1 for s, _ in installs(r.calls) if not s]) == 1, "the next family was not tried"


@needs_bash
def test_a_package_left_with_only_its_configuration_counts_as_missing(board):
    board.provisioned()
    inst = board.installed()
    del inst["cmake"]
    board.set("installed", _table(inst))
    board.set("residual", "cmake 3.0-m0\n")
    r = board.run("check")
    assert r.items["packages build"] == ("missing", "cmake")


@needs_bash
def test_a_package_on_hold_counts_as_installed(board):
    """dpkg's `hold ok installed`: the package is on the system. Read as missing it would be passed
    to apt, which skips it, and the family would stop on a simulation that installs nothing."""
    board.provisioned()
    board.set("held", "cmake\nlibboost-system-dev\n")
    r = board.run("check")
    assert r.returncode == 0 and r.items["packages build"] == ("ok", "all 4 installed"), said(r)
    assert installs(r.calls) == []
    # An unversioned Boost on hold is installed too, and still refuses the someip family.
    board.set("installed", _table(dict(board.installed(), **{"libboost-system-dev": "1.83-u1"})))
    r = board.run("check")
    assert r.returncode == 2 and r.items["packages someip"][0] == "differs" and "libboost-system-dev" in r.items["packages someip"][1]


@needs_bash
@pytest.mark.parametrize("name, says", [("usermod_rc", "usermod exited 6"), ("usermod_noop", "still not in the group kvm")])
def test_the_kvm_step_is_checked_after_it(board, name, says):
    board.provisioned()
    board.set("groups", "kvm:x:901:\ndocker:x:902:\n")
    board.set(name, "6\n")
    r = board.run("apply")
    assert r.returncode == 1 and says in r.out, said(r)
    assert [l for l in r.out.split("\n") if l.startswith("ANNOUNCE: ")][0].count("kvm"), "announced before it was tried"
    assert "NEW LOGIN" not in r.out, "not announced as done"


@needs_bash
def test_a_system_without_a_kvm_group_is_not_given_one(board):
    board.provisioned()
    board.set("groups", "docker:x:902:\n")
    r = board.run("apply")
    assert "no kvm group" in _refused(board, r, "kvm group")
    assert changing(r.calls) == []


# ------------------------------------------------------------------ the assertions that change nothing

@needs_bash
@pytest.mark.parametrize("mode", ["0", "2"])
def test_nvpmodel_in_another_mode_fails_the_step_and_is_never_changed(board, mode):
    board.provisioned()
    board.set("nvpmodel", "NV Power Mode: OTHER\n%s\n" % mode)
    before, state = board.tree(), board.state_of()
    r = board.run("apply")
    stop = _refused(board, r, "nvpmodel")
    assert "mode %s" % mode in stop and "mode 1" in stop and "the owner's" in stop
    assert [c for c in r.calls if c.startswith("nvpmodel")] == ["nvpmodel -q"], "queried once; nothing else is ever passed"
    assert not [c for c in r.calls if "nvpmodel" in c and c != "nvpmodel -q"], r.calls
    assert board.state_of() == state and board.get("nvpmodel") == "NV Power Mode: OTHER\n%s\n" % mode
    r = board.run("check")
    assert r.returncode == 2 and r.items["nvpmodel"][0] == "differs"
    assert [c for c in r.calls if "nvpmodel" in c] == ["nvpmodel -q"]
    assert {k: v for k, v in board.tree().items() if not k.startswith("home/provision")} == before


@needs_bash
@pytest.mark.parametrize("text, rc", [
    ("NVPM ERROR: made up\n", "255\n"),
    ("NV Power Mode: EXAMPLE\n1\n", "255\n"),       # the wanted mode on a query that failed is not an answer
    ("NV Power Mode: EXAMPLE\n", "0\n"),
], ids=["error", "mode-line-but-failed", "no-mode-line"])
def test_an_unreadable_nvpmodel_fails_the_step(board, text, rc):
    board.provisioned()
    board.set("nvpmodel", text)
    board.set("nvpmodel_rc", rc)
    r = board.run("apply")
    assert "cannot be read" in _refused(board, r, "nvpmodel")
    assert [c for c in r.calls if "nvpmodel" in c] == ["nvpmodel -q"]


@needs_bash
@pytest.mark.parametrize("now", ["performance", "ondemand"])
def test_a_governor_other_than_schedutil_fails_the_step_and_writes_nothing(board, now):
    board.provisioned()
    gov = board.sys / "devices" / "system" / "cpu" / "cpufreq" / "policy4" / "scaling_governor"
    _put(gov, now + "\n")
    before = board.tree()
    r = board.run("apply")
    stop = _refused(board, r, "governor")
    assert "policy4=%s" % now in stop and "policy0" not in stop
    # Only `performance` is what a harness pins: only that one is read as a run that died.
    assert ("died without restoring" in stop) == (now == "performance"), stop
    assert gov.read_bytes() == (now + "\n").encode()
    assert {k: v for k, v in board.tree().items() if not k.startswith("home/provision")} == before
    r = board.run("check")
    assert r.returncode == 2 and r.items["governor"][0] == "differs"


@needs_bash
def test_no_cpufreq_policy_to_read_is_not_a_pass(board):
    board.provisioned()
    shutil.rmtree(str(board.sys / "devices"))
    assert "no cpufreq policy" in _refused(board, board.run("apply"), "governor")


@needs_bash
@pytest.mark.parametrize("conf", [
    "[daemon]\n#WaylandEnable=false\n",
    "[daemon]\nWaylandEnable=true\n",
    "[daemon]\n",
], ids=["commented", "true", "absent"])
def test_gdm_without_the_xorg_setting_fails_the_step_and_the_file_is_not_written(board, conf):
    board.provisioned()
    _put(board.etc / "gdm3" / "custom.conf", conf)
    before = board.tree()
    r = board.run("apply")
    stop = _refused(board, r, "gdm Xorg")
    assert "WaylandEnable=false is not set" in stop and "the owner's" in stop
    after = {k: v for k, v in board.tree().items() if not k.startswith("home/provision")}
    assert after == before, "custom.conf was written, or a backup copy was made"
    assert sorted(p.name for p in (board.etc / "gdm3").iterdir()) == ["custom.conf"]
    r = board.run("check")
    assert r.returncode == 2 and r.items["gdm Xorg"][0] == "differs"


@needs_bash
def test_halt_poll_ns_is_asserted_and_not_set(board):
    board.provisioned()
    f = board.sys / "module" / "kvm" / "parameters" / "halt_poll_ns"
    _put(f, "0\n")
    assert "reads 0" in _refused(board, board.run("apply"), "halt_poll_ns")
    assert f.read_bytes() == b"0\n"


@needs_bash
@pytest.mark.parametrize("change, says", [
    ("no-runtime", "the nvidia runtime is not in daemon.json"),
    ("no-daemon-json", "the nvidia runtime is not in daemon.json"),
    ("disabled", "docker.socket is disabled"),
    ("no-package", "docker.io is not installed"),
    ("unfinished", "dpkg has docker.io in state 'install ok half-configured'"),
])
def test_docker_is_asserted_as_installed_and_never_changed(board, change, says):
    board.provisioned()
    if change == "no-runtime":
        _put(board.etc / "docker" / "daemon.json", "{}\n")
    elif change == "no-daemon-json":
        (board.etc / "docker" / "daemon.json").unlink()
    elif change == "disabled":
        board.set("units", board.get("units").replace("docker.socket enabled active", "docker.socket disabled inactive"))
    elif change == "unfinished":
        board.set("dpkg_state", "docker.io install ok half-configured %s\n" % INSTALLED["docker.io"])
    else:
        inst = board.installed()
        del inst["docker.io"]
        board.set("installed", _table(inst))
    state, before = board.state_of(), board.tree()
    r = board.run("apply")
    assert says in _refused(board, r, "docker")
    assert board.state_of() == state and changing(r.calls) == []
    assert {k: v for k, v in board.tree().items() if not k.startswith("home/provision")} == before
    assert not [c for c in r.calls if c.startswith("usermod")], "nobody is added to a group"
    assert [c for c in r.calls if c.startswith("docker")] in ([], ["docker ps -a -q"])
    assert board.get("systemctl-changed") is None and board.get("docker-changed") is None


@needs_bash
def test_docker_is_left_running_and_its_containers_are_only_counted(board):
    board.provisioned()
    board.set("containers", "0a1b2c3d4e5f\n1a2b3c4d5e6f\n")
    r = board.run("apply")
    assert r.returncode == 0 and "containers: 2" in r.items["docker"][1], said(r)
    assert docker_calls(r.calls) == ["sudo -n timeout -k 5 20 docker ps -a -q", "docker ps -a -q"]
    # A stopped service is recorded, and the socket is not poked (asking it would start the service).
    board.set("units", board.get("units").replace("docker.service enabled active", "docker.service enabled inactive"))
    r = board.run("apply")
    assert r.returncode == 0 and "docker.service=enabled/inactive" in r.items["docker"][1], said(r)
    assert "containers: not counted" in r.items["docker"][1] and "no answer" not in r.items["docker"][1]
    assert docker_calls(r.calls) == []
    assert board.get("systemctl-changed") is None and board.get("docker-changed") is None


@needs_bash
def test_a_container_count_that_fails_is_left_out_and_is_not_called_a_daemon_that_does_not_answer(board):
    board.provisioned()
    board.set("docker_fails", "1\n")
    r = board.run("check")
    assert r.returncode == 0 and r.items["docker"][0] == "ok", said(r)
    assert "containers: not counted;" in r.items["docker"][1] and "no answer" not in r.items["docker"][1], r.items["docker"]
    assert "Cannot connect" not in said(r), "what the client said is not shown"


@needs_bash
def test_a_docker_daemon_that_does_not_answer_does_not_hold_the_script(board):
    """The container count asks the daemon, and a wedged daemon never answers. The count is given
    20 s, from inside sudo, and is then left out; nothing else said about Docker depends on it."""
    board.provisioned()
    board.set("docker_hangs", "1\n")                    # the stub would sit there for a minute
    t0 = time.monotonic()
    r = board.run("check")
    took = time.monotonic() - t0
    assert r.returncode == 0, said(r)
    assert r.items["docker"][0] == "ok" and "containers: not counted (no answer in 20 s)" in r.items["docker"][1], r.items["docker"]
    assert took < 45, "the script waited for the daemon: %.0f s" % took
    assert docker_calls(r.calls) == ["sudo -n timeout -k 5 20 docker ps -a -q", "docker ps -a -q"]
    assert changing(r.calls) == []


# ------------------------------------------------------------------ no name, no address

@needs_bash
@pytest.mark.parametrize("args", [("check",), ("apply",), ("apply", "--bridge"), ("check", "--bridge")],
                         ids=["check", "apply", "apply-bridge", "check-bridge"])
def test_no_command_that_names_the_machine_is_called_and_no_marker_is_printed_or_logged(board, args):
    r = board.run(*args)
    assert r.returncode == (1 if args[0] == "check" else 0), said(r)
    for c in r.calls:
        w = c.split()
        assert w[0] not in ("hostname", "uname", "ip", "journalctl"), c
        if w[0] == "systemctl":
            assert w[1] in ("is-enabled", "is-active"), c
    text = everything(r, board)
    assert MARKER not in text and DOC_MAC not in text and STUB_HOST not in text
    if args[0] == "apply":
        assert len(board.logs()) == 1 and "kvm" in board.logs()[0].read_bytes().decode()


@needs_bash
@pytest.mark.parametrize("line", [
    "sudo: unable to resolve host %s: Name or service not known",
    "sudo: unable to resolve host %s: Temporary failure in name resolution",
    "sudo: unable to resolve host %s",
], ids=["not-known", "temporary-failure", "no-reason"])
@pytest.mark.parametrize("args", [("apply",), ("apply", "--bridge"), ("check",)], ids=["apply", "apply-bridge", "check"])
def test_what_sudo_itself_says_of_the_hosts_name_is_neither_printed_nor_logged(board, args, line):
    """On a host whose name does not resolve, sudo says so on stderr at every call, with the name.
    apply logs what three of the commands it runs through sudo print, their stderr included. The
    script's own shell holds another name here, so the line can only be known by its wording."""
    board.set("sudo_noise", line % MARKER + "\n")
    r = board.run(*args)
    assert r.returncode == (1 if args[0] == "check" else 0), said(r)
    text = everything(r, board)
    assert MARKER not in text, [l for l in text.split("\n") if MARKER in l][:3]
    assert len([c for c in r.calls if c.startswith("sudo ")]) >= 2, "sudo was called, and said it each time"
    assert r.items["sudo"][0] == "ok"
    note = r.items["sudo stderr"]
    assert note[0] == "note" and "not shown" in note[1] and "/etc/hosts is the owner's" in note[1], note
    if args[0] == "apply":
        # The update, the three installs and usermod: sudo's line stays each time, without the name.
        assert r.out.count("  | sudo: unable to resolve host [not shown]\n") == 5
        assert one_log(board).count("  | sudo: unable to resolve host [not shown]\n") == 5


@needs_bash
def test_the_hosts_name_is_struck_out_of_whatever_a_command_says(board):
    """sudo names the host in more lines than one, and in the session's language. Whatever a
    command prints, the name the script's shell holds for the host is struck out of it."""
    board.set("sudo_noise", "sudo: der Rechnername %s ist nicht aufloesbar (%s)\n" % (MARKER, MARKER))
    r = board.run("apply", HOSTNAME=MARKER)
    assert r.returncode == 0, said(r)
    assert MARKER not in everything(r, board)
    assert r.out.count("  | sudo: der Rechnername [host] ist nicht aufloesbar ([host])\n") == 5, "every place in the line"
    assert one_log(board).count("  | sudo: der Rechnername [host] ist nicht aufloesbar ([host])\n") == 5
    # A sudoers line that allows some commands and not this one: sudo's refusal names the host.
    b = Board(board.root.parent / "refused")
    b.provisioned()
    b.set("groups", "kvm:x:901:\ndocker:x:902:\n")
    b.set("sudo_refuses", "usermod Sorry, user %s is not allowed to execute '/usr/sbin/usermod -aG kvm %s' as root on %s.\n"
          % (LOGIN, LOGIN, MARKER))
    r = b.run("apply", HOSTNAME=MARKER)
    assert r.returncode == 1 and "FAILED: usermod exited 1" in r.out, said(r)
    assert MARKER not in everything(r, b)
    assert "  | Sorry, user %s is not allowed to execute '/usr/sbin/usermod -aG kvm %s' as root on [host]." % (LOGIN, LOGIN) in r.out.split("\n")


@needs_bash
def test_the_bridge_is_made_once_when_asked_and_its_output_is_kept_out(board):
    r = board.run("check", "--bridge")
    assert r.items["bridge"][0] == "missing" and "bridge-stub" not in " ".join(r.calls)
    r = board.run("apply", "--bridge")
    assert r.returncode == 0, said(r)
    assert [c for c in r.calls if c.startswith("bridge-stub")] == ["bridge-stub "]
    assert [c for c in r.calls if "bridge-stub.sh" in c] == ["sudo -n bash %s" % _fwd(board.root / "bridge-stub.sh")]
    assert r.items["bridge"][0] == "ok" and (board.sys / "class" / "net" / "tap-qnx").is_dir()
    assert MARKER not in everything(r, board) and DOC_MAC not in everything(r, board)
    r = board.run("apply", "--bridge")
    assert r.returncode == 0 and not [c for c in r.calls if "bridge-stub" in c], "the bridge exists: the script is not run again"
    assert r.items["bridge"] == ("ok", "br0 and tap-qnx exist")
    # Without --bridge it is a note either way, and the script is never run.
    b = Board(board.root.parent / "nobridge")
    r = b.run("apply")
    assert r.items["bridge"][0] == "note" and not [c for c in r.calls if "bridge-stub" in c]


@needs_bash
@pytest.mark.parametrize("there", ["br0", "tap-qnx"])
def test_one_half_of_the_bridge_is_not_the_bridge(board, there):
    board.provisioned()
    (board.sys / "class" / "net" / there).mkdir()
    r = board.run("check", "--bridge")
    assert r.returncode == 1 and r.items["bridge"][0] == "missing", said(r)
    r = board.run("apply", "--bridge")
    assert r.returncode == 0, said(r)
    assert [c for c in r.calls if c.startswith("bridge-stub")] == ["bridge-stub "], "the bridge script ran, once"
    assert r.items["bridge"] == ("ok", "br0 and tap-qnx were made; they do not survive a reboot")


@needs_bash
@pytest.mark.parametrize("there", [None, "br0", "tap-qnx"], ids=["neither", "br0-only", "tap-qnx-only"])
def test_the_bridge_script_is_looked_for_only_when_there_is_a_bridge_to_make(board, there):
    """With --bridge and no bridge yet, a bridge script that is not there stops apply before the
    first change. Without --bridge, or with the bridge standing, the script is not needed and is
    not looked for."""
    gone = _fwd(board.root / "no-such-bridge-script.sh")
    if there:
        (board.sys / "class" / "net" / there).mkdir()
    state = board.state_of()
    r = board.run("apply", "--bridge", BRIDGE_SCRIPT=gone)
    stop = _refused(board, r, "bridge")
    assert "setup-bridge-orin.sh is not beside this script" in stop
    assert changing(r.calls) == [] and not [c for c in r.calls if c.startswith("apt-get")] and board.state_of() == state
    r = board.run("check", "--bridge", BRIDGE_SCRIPT=gone)
    assert r.returncode == 2 and r.items["bridge"][0] == "differs", said(r)
    # Not asked for: the board is provisioned as if the script were there, and the bridge stays a note.
    r = board.run("apply", BRIDGE_SCRIPT=gone)
    assert r.returncode == 0 and r.items["bridge"][0] == "note", said(r)
    # The bridge stands: nothing would be run, so nothing is looked for.
    for name in ("br0", "tap-qnx"):
        (board.sys / "class" / "net" / name).mkdir(exist_ok=True)
    r = board.run("apply", "--bridge", BRIDGE_SCRIPT=gone)
    assert r.returncode == 0 and r.items["bridge"] == ("ok", "br0 and tap-qnx exist"), said(r)


@needs_bash
@pytest.mark.parametrize("name, says", [("bridge_fails", "exited 1"), ("bridge_noop", "still missing")])
def test_a_bridge_script_that_fails_or_makes_nothing_fails_the_step(board, name, says):
    board.provisioned()
    board.set(name, "1\n")
    r = board.run("apply", "--bridge")
    assert r.returncode == 1 and says in r.out, said(r)
    assert MARKER not in everything(r, board)


@needs_bash
def test_the_real_bridge_script_is_the_default_and_an_override_is_announced(board):
    code = _code(_text(SCRIPT))
    assert 'BRIDGE_SCRIPT="${BRIDGE_SCRIPT:-$here/setup-bridge-orin.sh}"' in code
    assert os.path.exists(os.path.join(ORIN, "setup-bridge-orin.sh"))
    r = board.run("check")
    for name in ("ETC_ROOT", "SYS_ROOT", "PROC_ROOT", "BRIDGE_SCRIPT"):
        assert [l for l in r.out.split("\n") if l.startswith("WARNING: %s overridden" % name)], name
