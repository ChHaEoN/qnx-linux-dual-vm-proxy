"""A g5g session's phases on the instance side (SDV Phase 8, the g5g leg: T3, T4, T5): remote-ladder.sh's gpu-facts,
gpu-install (plan, apply), llama-build, launch-svc and vlm, run against stand-ins only.

No AWS call, no GPU, no package archive, no download: a stub `sudo`, `apt-get`, `apt-cache`, `dpkg`, `dpkg-query`,
`modprobe`, `rmmod`, `journalctl`, `dmesg`, `loginctl`, `udevadm`, the driver's tool, a fake `uname -r`, made-up /proc,
/sys, /dev and /etc/apt trees, and stub copies of build-llama.sh, vlm-demo.sh and the guest's launcher. Every version,
size, hash and id is made up. The stub apt answers in apt's own output forms as this package's author read them from
apt's documentation, not from an instance.

What these tests do not show: that a real apt, dpkg, kmod, udev or logind answers as the stubs do, that any package
named here exists or installs, that a module loads, or that any phase ran on a g5g.metal instance.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import time

import pytest

import test_aws_tooling as aws
from test_aws_tooling import BASH, REMOTE, REPO

pytestmark = pytest.mark.skipif(os.name == "nt" or BASH is None, reason="made-up /proc, /sys and /dev trees: Linux only")

EDGE = os.path.join(REPO, "orin-native", "edge-llm")
KREL = "0.0.0-1-stub"
BOOT_ID = "0a1b2c3d-1111-2222-3333-0e1f2a3b4c5d"          # made up
GPU_UUID = "GPU-0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"      # made up
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NODES = ("nvidiactl", "nvidia0", "nvidia1", "nvidia-uvm")
NEW_PHASES = ("gpu-install", "llama-build", "launch-svc", "vlm")
SMI_ROOT = "nvidia-smi  root=1"                            # the stub's line for the driver's tool run bare, as root
LLAMA_PIN = "e6ab7c1a41054a888ada952eab4c886444c2f5ad"
# Made-up versions, each put together here so that this file's text holds no run of four dotted numbers (the shape of
# an address, which tests/test_no_real_identifiers.py allows only from its list): an Ubuntu revision and a four-part
# version, the two forms the redactor's IPv4 rule rewrites.
UB = "0.0.1-0ubuntu0.24" + ".04.1"
V4 = "13.0.0" + ".1-1"
# name, version, source, size: the made-up closure. The first nine are what the list file's names install here.
PKGS = [
    ("linux-modules-nvidia-580-server-" + KREL, "0.0.0-1.1+1", "ubuntu", 1000),
    ("nvidia-kernel-common-580-server", "580.0.04-" + UB[6:], "ubuntu", 2000),
    ("libnvidia-compute-580-server", "580.0.04-" + UB[6:], "ubuntu", 3000),
    ("nvidia-utils-580-server", "580.0.04-" + UB[6:], "ubuntu", 4000),
    ("cuda-nvcc-13-2", V4, "nvidia", 5000),
    ("cuda-cudart-dev-13-2", "13.0.86-1", "nvidia", 6000),
    ("libcublas-dev-13-2", V4, "nvidia", 7000),
    ("cuda-toolkit-config-common", "13.0.86-1", "nvidia", 800),
    ("cmake", UB, "ubuntu", 9000),
    ("cmake-data", UB, "ubuntu", 100),          # approved, and already on this made-up AMI: never in the set
]
SET = PKGS[:9]
HOSTS = {"ubuntu": "http://ports.ubuntu.com/ubuntu-ports", "nvidia":
         "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/sbsa"}
ORIGIN = {"ubuntu": "Ubuntu:24.04/noble-updates", "nvidia": "NVIDIA:/"}
KEYFILES = {"/etc/apt/preferences.d/cuda-repository-pin-600": "Package: *\nPin: release l=NVIDIA CUDA\nPin-Priority: 600\n",
            "/etc/apt/sources.list.d/cuda-ubuntu2404-sbsa.list": "deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] "
            + HOSTS["nvidia"] + "/ /\n",
            "/usr/share/keyrings/cuda-archive-keyring.gpg": "a stand-in keyring\n"}
DEB = b"a stand-in for the key package\n"
# The stub directory, then the system directories and nothing else: a phase under test must never find a real driver
# tool, package tool or model server of the machine the tests run on (WSL puts the host GPU's tool on PATH).
SAFE_PATH = "%s" + os.pathsep + "/usr/bin" + os.pathsep + "/bin"


def _h(x):
    return hashlib.sha256(x if isinstance(x, bytes) else x.encode()).hexdigest()


def _deb_sha(name):
    return _h("deb of " + name)


def sim_lines(pkgs, upgrade=(), remove=()):
    """apt-get -s install, as apt prints a simulation: Inst NAME [OLD] (NEW ORIGIN [ARCH]), Remv NAME [OLD]."""
    out = ["Reading package lists...", "Building dependency tree..."]
    out += ["Remv %s [0.0.0-1]" % n for n in remove]
    for n, v, src, _size in pkgs:
        out.append("Inst %s %s(%s %s [arm64])" % (n, "[0.0.0-0] " if n in upgrade else "", v, ORIGIN[src]))
    out += ["Conf %s (%s %s [arm64])" % (n, v, ORIGIN[src]) for n, v, src, _size in pkgs]
    return "\n".join(out) + "\n"


def uri_lines(pkgs, host=None, sizes=None, shas=None):
    """apt-get --print-uris install: 'URI' FILE SIZE SHA256:HASH."""
    out = []
    for n, v, src, size in pkgs:
        f = "%s_%s_arm64.deb" % (n, v.replace(":", "%3a"))
        out.append("'%s/pool/%s' %s %d SHA256:%s" % ((host or {}).get(n, HOSTS[src]), f, f, (sizes or {}).get(n, size),
                                                    (shas or {}).get(n, _deb_sha(n))))
    return "\n".join(out) + "\n"


def approved_text(pkgs=PKGS, extra="", pins_sha=None, key_sha=None, total=40000, cap=60000000, llama=True):
    lines = ["# a made-up approved-names file: every version, size and hash is a stand-in"]
    lines += ["pkg %s=%s %s %d %s" % (n, v, src, size, _deb_sha(n)) for n, v, src, size in pkgs]
    lines.append("key cuda-keyring cuda-keyring_1.1-1_all.deb %s" % (key_sha or _h(DEB)))
    lines += ["keyfile %s %s" % (p, _h(t)) for p, t in sorted(KEYFILES.items())]
    if llama:
        lines.append("llama %s 2000000000" % LLAMA_PIN)
    lines += ["index-cap %d" % cap, "total all %d" % total]
    body = "\n".join(lines) + "\n" + extra
    if pins_sha is None:
        p = subprocess.run([sys.executable, os.path.join(EDGE, "g5g_pins.py"), "/dev/stdin"], input=body.encode(),
                           capture_output=True, timeout=60)
        pins_sha = _h(p.stdout) if p.returncode == 0 else "0" * 64
    return body + "pins g5g-nvidia-pins %s\n" % pins_sha


STUBS = {
    "sudo": r'''
echo "sudo $*" >> "$STUB/calls.log"
while [ "${1:-}" = -n ]; do shift; done
STUB_ROOT=1 exec "$@"
''',
    "uname": r'''
case "${1:-}" in -r) cat "$STUB/krel" ;; *) exec /usr/bin/uname "$@" ;; esac
''',
    "journalctl": r'''
echo "journalctl $* root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
[ "${STUB_ROOT:-0}" = 1 ] || { echo "journalctl: not permitted" >&2; exit 1; }
case " $* " in *" -b -1 "*) f=journal-prev ;; *) f=journal ;; esac
[ -r "$STUB/$f" ] || exit 1
cat "$STUB/$f"
''',
    "dmesg": r'''
echo "dmesg root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
[ "${STUB_ROOT:-0}" = 1 ] || { echo "dmesg: read kernel buffer failed: Operation not permitted" >&2; exit 1; }
[ -r "$STUB/dmesg.out" ] || exit 1
cat "$STUB/dmesg.out"
''',
    "nvidia-smi": r'''
echo "nvidia-smi $* root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
[ ! -e "$STUB/smi-fail" ] || { echo "NVIDIA-SMI has failed" >&2; exit 9; }
[ ! -e "$STUB/smi-hang" ] || exec sleep 30
[ ! -e "$STUB/smi-makes-uvm" ] || [ "${STUB_ROOT:-0}" != 1 ] || : > "$G5G_ROOT/dev/nvidia-uvm"
q=""; for a; do case "$a" in --query-gpu=*) q="${a#--query-gpu=}" ;; esac; done
[ -n "$q" ] || { echo "a table of two stub GPUs"; exit 0; }
for i in 0 1; do
  out=""
  for f in ${q//,/ }; do
    case "$f" in index) v=$i ;; name) v="Stub T4G" ;; compute_cap) v="$(cat "$STUB/cap" 2>/dev/null || echo 7.5)" ;;
      driver_version) v=580.0.04 ;; memory.total) v="16384 MiB" ;; uuid|gpu_uuid) v=GPU-0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d ;;
      serial|gpu_serial) v=0123456789012 ;; *) v="[N/A]" ;; esac
    out="${out:+$out, }$v"
  done
  echo "$out"
done
''',
    # kmod, as the driver's modprobe file leaves it once installed: "alias nouveau off" turns -r nouveau into nothing
    "modprobe": r'''
echo "modprobe $*" >> "$STUB/calls.log"
M="$PROC_ROOT/modules"
bind() { for d in "$SYS_ROOT"/bus/pci/devices/*; do
  [ "$(cat "$d/vendor")" = 0x10de ] && [ ! -e "$d/driver" ] && ln -s "../../../drivers/$1" "$d/driver"; done; return 0; }
case "$*" in
  "-r nouveau")
    [ ! -e "$STUB/alias-off" ] || exit 0
    [ ! -e "$STUB/nouveau-held" ] || { echo "modprobe: FATAL: Module nouveau is in use." >&2; exit 1; }
    sed -i '/^nouveau /d' "$M"; [ ! -e "$STUB/nouveau-stays-bound" ] || exit 0
    for d in "$SYS_ROOT"/bus/pci/devices/*; do
      [ "$(readlink "$d/driver" 2>/dev/null)" = ../../../drivers/nouveau ] && rm -f "$d/driver"; done; exit 0 ;;
  nvidia)
    [ ! -e "$STUB/nvidia-noload" ] || { echo "modprobe: ERROR: could not insert 'nvidia'" >&2; exit 1; }
    echo "nvidia 1 0 - Live 0x0 (POE)" >> "$M"; bind nvidia
    for n in $(cat "$STUB/nodes-made" 2>/dev/null || echo "nvidiactl nvidia0 nvidia1 nvidia-uvm"); do : > "$G5G_ROOT/dev/$n"; done ;;
  nvidia_uvm|nvidia-uvm)
    [ ! -e "$STUB/uvm-noload" ] || { echo "modprobe: ERROR: could not insert 'nvidia_uvm'" >&2; exit 1; }
    echo "nvidia_uvm 1 0 - Live 0x0 (OE)" >> "$M" ;;
  *) exit 1 ;;
esac
''',
    "rmmod": r'''
echo "rmmod $*" >> "$STUB/calls.log"
[ "$*" = nouveau ] || exit 1
[ ! -e "$STUB/nouveau-held-again" ] || { echo "rmmod: ERROR: Module nouveau is in use" >&2; exit 1; }
sed -i '/^nouveau /d' "$PROC_ROOT/modules"
for d in "$SYS_ROOT"/bus/pci/devices/*; do
  [ "$(readlink "$d/driver" 2>/dev/null)" = ../../../drivers/nouveau ] && rm -f "$d/driver"; done; exit 0
''',
    # apt, pin-sensitive the way apt is: only a file of exactly this name in the preferences directory is read. And
    # --print-uris prints one hash a file, the strongest the index carries (SHA512 beside SHA256 in every index the
    # prep read) unless Acquire::ForceHash names another: apt's HashStringList::find as this package's authors know
    # it, not as an instance showed it.
    "apt-get": r'''
echo "apt-get $* root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
v=unpinned; [ -s "$G5G_ROOT/etc/apt/preferences.d/g5g-nvidia-pins" ] && v=pinned
case " $* " in
  *" update "*) cat "$STUB/apt-update.out" ;;
  *" -s "*) cat "$STUB/apt-sim.$v.out" ;;
  *" --print-uris "*)
    if [ ! -e "$STUB/forcehash-ignored" ] && case " $* " in *" -o Acquire::ForceHash=SHA256 "*) true ;; *) false ;; esac; then
      cat "$STUB/apt-uris.$v.out"
    else
      sed -E 's/ SHA256:([0-9a-f]{64})$/ SHA512:\1\1/' "$STUB/apt-uris.$v.out"
    fi ;;
  *" install "*)
    [ "${STUB_ROOT:-0}" = 1 ] || exit 100
    : > "$STUB/installed"; : > "$STUB/alias-off"
    [ ! -e "$STUB/nouveau-back" ] || echo "nouveau 1 0 - Live 0x0" >> "$PROC_ROOT/modules"
    # a device bound to a nouveau that no /proc/modules line shows (a built-in one)
    [ ! -e "$STUB/nouveau-bound-back" ] || for d in "$SYS_ROOT"/bus/pci/devices/*; do
      [ "$(cat "$d/vendor")" = 0x10de ] && [ ! -e "$d/driver" ] && ln -s ../../../drivers/nouveau "$d/driver"; done
    echo "Setting up the stub packages ..." ;;
  *) exit 1 ;;
esac
''',
    "apt-cache": r'''
echo "apt-cache $*" >> "$STUB/calls.log"
[ "${1:-}" = policy ] || exit 1
c=""; f="$G5G_ROOT/etc/apt/preferences.d/g5g-nvidia-pins"
[ ! -s "$f" ] || c="$(awk -v n="$2" '$1 == "Package:" { p = $2 } $1 == "Pin:" && p == n { print $3 }' "$f")"
[ ! -e "$STUB/cand.$2" ] || c="$(cat "$STUB/cand.$2")"
printf '%s:\n  Installed: (none)\n  Candidate: %s\n  Version table:\n' "$2" "${c:-99.9.9-1}"
''',
    "dpkg": r'''
echo "dpkg $* root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
case "${1:-}" in
  -i) [ "${STUB_ROOT:-0}" = 1 ] || exit 2
      for f in "$STUB"/keyfiles/*; do p="$(tr '%' '/' <<< "${f##*/}")"; mkdir -p "$G5G_ROOT${p%/*}"; cp "$f" "$G5G_ROOT$p"; done
      [ ! -e "$STUB/key-extra" ] || echo "an unlisted file" > "$G5G_ROOT/etc/apt/apt.conf.d-extra" ;;
  -L) [ ! -e "$STUB/dpkg-L-fail" ] || { echo "dpkg-query: package is not installed" >&2; exit 1; }
      echo /.; echo /etc; echo /etc/apt
      for f in "$STUB"/keyfiles/*; do tr '%' '/' <<< "${f##*/}"; done
      [ ! -e "$STUB/key-extra" ] || echo /etc/apt/apt.conf.d-extra ;;
  *) exit 1 ;;
esac
''',
    "dpkg-query": r'''
echo "dpkg-query $*" >> "$STUB/calls.log"
case "$*" in *qemu-system-arm*) echo "1:0.0+stub"; exit 0 ;; esac
[ ! -e "$STUB/dpkg-query-fail" ] || { echo "dpkg-query: no packages found matching cmake" >&2; exit 1; }
cat "$STUB/dpkg-query.out"
''',
    "udevadm": 'echo "udevadm $*" >> "$STUB/calls.log"\n',
    "loginctl": r'''
echo "loginctl $* root=${STUB_ROOT:-0}" >> "$STUB/calls.log"
case "${1:-}" in
  enable-linger) [ -e "$STUB/linger-refused" ] || : > "$STUB/linger" ;;
  show-user) if [ -e "$STUB/linger" ]; then echo "Linger=yes"; else echo "Linger=no"; fi ;;
esac
''',
    "pgrep": r'''
case "$*" in *qemu-system-aar*) [ -e "$STUB/qemu-running" ]; exit $? ;; esac
exec /usr/bin/pgrep "$@"
''',
    "reboot": 'echo "reboot $*" >> "$STUB/calls.log"\n',
    "shutdown": 'echo "shutdown $*" >> "$STUB/calls.log"\n',
    "systemctl": 'echo "systemctl $*" >> "$STUB/calls.log"\n',
    "nvidia-modprobe": 'echo "nvidia-modprobe $*" >> "$STUB/calls.log"\n',
    "nproc": "echo 64\n", "curl": "exit 0\n", "flock": 'exec /usr/bin/flock "$@"\n', "taskset": "exit 0\n",
}
STUB_BUILD = r'''#!/usr/bin/env bash
# a stand-in for build-llama.sh: what it was given, the lock lib-build.sh holds, and a BUILD-INFO
printf '%s\n' "CUDA_ARCH=${CUDA_ARCH:-}" "JOBS=${JOBS:-}" "MEM_MAX=${MEM_MAX:-}" "LLAMA_COMMIT=${LLAMA_COMMIT:-}" > "$STUB/build.env"
mkdir -p "$HOME/builds" "$HOME/llama.cpp/build/bin"
exec 9>"$HOME/builds/build-llama.lock"; flock -n 9 || exit 75
echo "$$" > "$STUB/build.pid"
[ ! -e "$STUB/build-sleep" ] || sleep 120
[ ! -e "$STUB/build-fail" ] || { echo "FATAL: llama.cpp's cmake failed. Its log names as missing: CUDA_CUDART" >&2; exit 1; }
echo "flags -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH:-87}" > "$HOME/llama.cpp/build/bin/BUILD-INFO"
echo "jobs: ${JOBS:-default}"
'''
STUB_DEMO = r'''#!/usr/bin/env bash
# a stand-in for vlm-demo.sh: what it was given, the files the demo writes, and an exit status
printf '%s\n' "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}" "IMAGES=$IMAGES" "LLAMA_MODELS=$LLAMA_MODELS" "CONSOLE=$CONSOLE" \
  "OUT=$OUT" > "$STUB/demo.env"
mkdir -p "$OUT"
for f in server.log warmup.json console.mark requests.start claims.log expected.txt guest-console.demo.log summary.txt; do
  echo "{}" > "$OUT/$f"; done
[ -e "$STUB/no-stamp" ] || printf '{"board": "a stub that is no Tegra host", "cuda_visible_devices": "%s"}' \
  "${CUDA_VISIBLE_DEVICES:-unset}" > "$OUT/stamp.json"
# a made-up summary line in vlm-demo.sh's form, no run's count
echo "1 of 2 claims: client verdict as expected AND corroborated by the guest console"
exit "$(cat "$STUB/demo-rc" 2>/dev/null || echo 0)"
'''
STUB_LAUNCHER = r'''#!/usr/bin/env bash
echo "launcher IFS_BIN=$IFS_BIN DISK=$DISK LOG=$LOG" >> "$STUB/calls.log"
[ ! -e "$STUB/launch-fail" ] || { echo "guest did not answer"; exit 1; }
cat "$STUB/console" > "$LOG"
echo "guest up"
'''
PLAIN = "safety monitor listening on :%s (frame=64 bytes, conf_min=60%%)\nclaim kinds: 0 mnist\n"
DEADLINE = "listening on :%s (frame=64 bytes, conf_min=60%%), liveness deadline 2000 ms\n"


class Rig:
    def __init__(self, tmp, rec=True):
        self.tmp = tmp
        self.w, self.stub, self.root = tmp / "w", tmp / "stub", tmp / "root"
        self.home, self.run_dir = tmp / "home", tmp / "xdg"
        for d in (self.w / "img", self.w / "in", self.home, self.run_dir, self.root / "dev",
                  self.root / "etc" / "apt" / "preferences.d", self.root / "etc" / "apt" / "sources.list.d",
                  self.root / "proc" / "sys" / "kernel" / "random", self.root / "sys" / "fs" / "pstore",
                  self.root / "sys" / "bus" / "pci" / "devices", self.stub / "keyfiles"):
            d.mkdir(parents=True)
        aws._stubs(self.stub, STUBS)
        e, g = self.w / "repo" / "orin-native" / "edge-llm", self.w / "repo" / "orin-native" / "gpu-concurrency"
        e.mkdir(parents=True)
        g.mkdir(parents=True)
        for n in ("g5g-packages.list", "g5g_pins.py"):
            if os.path.exists(os.path.join(EDGE, n)):
                shutil.copy(os.path.join(EDGE, n), str(e / n))
        aws._write(e / "build-llama.sh", STUB_BUILD, newline=False)
        aws._write(e / "vlm-demo.sh", STUB_DEMO, newline=False)
        aws._write(g / "launch-qnx-kvm-bridged.sh", STUB_LAUNCHER, newline=False)
        shutil.copy(REMOTE, str(self.w / "remote-ladder.sh"))
        for n, b in (("ifs-vss.bin", b"vss"), ("ifs-svc.bin", b"svc"), ("disk-qemu", b"disk")):
            (self.w / "img" / n).write_bytes(b)
        aws._inputs_env(self.w, IFS_NAME="ifs-vss.bin", IFS_SHA256=_h(b"vss"), DISK_SHA256=_h(b"disk"))
        with open(self.w / "inputs.env", "a", newline="\n") as f:
            f.write("IFS_EXTRA=ifs-svc.bin:%s\n" % _h(b"svc"))
        (self.w / "in" / "cuda-keyring_1.1-1_all.deb").write_bytes(DEB)
        for p, t in KEYFILES.items():
            aws._write(self.stub / "keyfiles" / p.replace("/", "%"), t, newline=False)
        self.approve(approved_text())
        self.put("krel", KREL)
        self.put("journal", "kernel: a quiet boot")
        self.put("apt-update.out", "Get:1 http://ports.ubuntu.com noble-updates InRelease [126 kB]\nFetched 30.8 MB in 3s (10.0 MB/s)")
        self.apt(SET)
        self.apt(SET[:7] + [("cuda-toolkit-config-common", "13.9.37-1", "nvidia", 900)] + SET[8:], "unpinned")
        self.put("dpkg-query.out", "".join(sorted("%s=%s\n" % (n, v) for n, v, _s, _z in SET)), nl=False)
        aws._write(self.root / "etc" / "apt" / "sources.list.d" / "ubuntu.sources",
                   "Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble noble-updates\n"
                   "Components: main universe restricted multiverse\n\nTypes: deb\nSuites: noble-security\nComponents: main universe")
        proc = self.root / "proc"
        aws._write(proc / "sys" / "kernel" / "random" / "boot_id", BOOT_ID)
        aws._write(proc / "cpuinfo", "".join("processor\t: %d\nCPU implementer\t: 0x41\nCPU part\t: 0xd0c\n\n" % i for i in (0, 1)))
        aws._write(proc / "modules", "kvm 1 0 - Live 0x0")
        aws._write(proc / "meminfo", "MemTotal:       %d kB\nSwapTotal:             0 kB".replace("%d", "131000000"))
        (self.root / "dev" / "kvm").write_text("")
        for i, (vendor, dev) in enumerate((("0x10de", "0x1eb4"), ("0x1d0f", "0xec20"), ("0x10de", "0x1eb4"))):
            d = self.root / "sys" / "bus" / "pci" / "devices" / ("0000:00:0%d.0" % i)
            d.mkdir()
            aws._write(d / "vendor", vendor)
            aws._write(d / "device", dev)
        if rec:
            (self.w / "rec" / "ladder").mkdir(parents=True)

    def put(self, name, text="", nl=True):
        aws._write(self.stub / name, text, newline=nl)

    def flag(self, name):
        (self.stub / name).write_text("")

    def approve(self, text):
        (self.w / "in" / "g5g-approved.txt").write_bytes(text.encode())

    def apt(self, pkgs, v="pinned", **kw):
        up, rm = kw.pop("upgrade", ()), kw.pop("remove", ())
        self.put("apt-sim.%s.out" % v, sim_lines(pkgs, up, rm), nl=False)
        self.put("apt-uris.%s.out" % v, uri_lines(pkgs, **kw), nl=False)

    def bind(self, driver):
        for d in sorted((self.root / "sys" / "bus" / "pci" / "devices").iterdir()):
            if (d / "vendor").read_text().strip() == "0x10de":
                os.symlink("../../../drivers/" + driver, str(d / "driver"))
        with open(self.root / "proc" / "modules", "a") as f:
            f.write("%s 1 0 - Live 0x0\n" % driver)

    def driver_up(self):
        self.bind("nvidia")
        with open(self.root / "proc" / "modules", "a") as f:
            f.write("nvidia_uvm 1 0 - Live 0x0\n")
        for n in NODES:
            (self.root / "dev" / n).write_text("")

    def env(self, **env):
        e = dict(os.environ, W=str(self.w), STUB=str(self.stub), HOME=str(self.home), PROC_ROOT=str(self.root / "proc"),
                 SYS_ROOT=str(self.root / "sys"), G5G_ROOT=str(self.root), XDG_RUNTIME_DIR=str(self.run_dir),
                 PATH=SAFE_PATH % self.stub, GUEST="127.0.0.1", USER="ubuntu", G5G_BANNER_WAIT_S="1",
                 G5G_BUILD_WAIT_S="60")
        for k in ("LADDER_ENV", "K", "MODE", "SVC_PORT", "CUDA_VISIBLE_DEVICES"):
            e.pop(k, None)
        e.update({k: str(v) for k, v in env.items()})
        return e

    def run(self, phase, words=None, timeout=120, **env):
        if words:
            env["LADDER_ENV"] = words
        r = subprocess.run([BASH, REMOTE, phase], capture_output=True, text=True, timeout=timeout, env=self.env(**env),
                           stdin=subprocess.DEVNULL)
        r.out = r.stdout + r.stderr
        return r

    def calls(self, prefix=""):
        p = self.stub / "calls.log"
        return [ln for ln in (p.read_text().splitlines() if p.exists() else []) if ln.startswith(prefix)]

    def rec(self, *parts):
        return self.w.joinpath("rec", *parts)

    def everything(self):
        """Every byte a phase wrote under W's rec and its marker, for "no output holds X"."""
        out = []
        for d, _s, fs in os.walk(str(self.w / "rec")):
            out += [open(os.path.join(d, f), errors="replace").read() for f in fs]
        return "\n".join(out)


@pytest.fixture
def g(tmp_path):
    return Rig(tmp_path)


def facts(g, **env):
    r = g.run("gpu-facts", **env)
    assert r.returncode == 0, r.out
    return r


def summary_of(text):
    line = [ln for ln in text.splitlines() if ln.startswith("gpu-facts: cpu_part=")]
    assert len(line) == 1, text
    return dict(kv.split("=", 1) for kv in line[0].split()[1:])


# ------------------------------------------------------------------ gpu-facts

def test_gpu_facts_reads_the_host_writes_its_stem_and_never_a_uuid(g):
    g.driver_up()
    r = facts(g)
    s = summary_of(r.stdout)
    assert s == {"cpu_part": "0x41:0xd0c", "kvm": "yes", "nvidia_pci": "2", "pci_ids": "0x1eb4,0x1eb4",
                 "bound": "nvidia,nvidia", "driver": "580.0.04", "uvm": "yes", "nodes": "4/4", "gpus": "2",
                 "compute_cap": "7.5,7.5", "kernel_oops": "no", "boot": "same"}, s
    stem = g.rec("gpu-facts")
    assert (stem / "summary.txt").read_text() == r.stdout.splitlines()[-1] + "\n"
    after = (stem / "host-after.txt").read_text().splitlines()
    assert "kernel_oops=no" in after and "boot=same" in after, after
    assert "Stub T4G" in (stem / "gpus.txt").read_text() and "16384 MiB" in (stem / "gpus.txt").read_text()
    everything = r.out + g.everything()
    assert not UUID_RE.search(everything) and "0123456789012" not in everything, "no UUID, no serial number"
    asked = g.calls("nvidia-smi")
    assert asked and all("uuid" not in a and "serial" not in a and "--query-gpu=" in a for a in asked), asked
    assert not g.calls("apt-get") and not g.calls("modprobe") and not g.calls("dpkg "), "read only"


@pytest.mark.parametrize("how", ["missing", "not writable"])
def test_gpu_facts_reads_kvm_no_when_dev_kvm_is_missing_or_cannot_be_written(g, how):
    """kvm=yes only when /dev/kvm can be read and written; without it, or with one this user cannot write, the summary
    reads kvm=no and is otherwise the one before."""
    yes = summary_of(facts(g).stdout)
    kvm = g.root / "dev" / "kvm"
    if how == "missing":
        kvm.unlink()
    else:
        if os.geteuid() == 0:
            pytest.skip("root writes a file its mode does not let it write")
        kvm.chmod(0o444)
    no = summary_of(facts(g).stdout)
    assert (yes["kvm"], no["kvm"]) == ("yes", "no") and dict(no, kvm="yes") == yes, (yes, no)


@pytest.mark.parametrize("driver,want", [(None, "none,none"), ("nouveau", "nouveau,nouveau")])
def test_gpu_facts_reads_the_bound_driver_and_the_device_ids_from_sys_with_no_driver_tool(g, driver, want):
    os.remove(str(g.stub / "nvidia-smi"))
    if driver:
        g.bind(driver)
    s = summary_of(facts(g).stdout)
    assert (s["nvidia_pci"], s["pci_ids"], s["bound"]) == ("2", "0x1eb4,0x1eb4", want), s
    assert (s["driver"], s["uvm"], s["nodes"], s["gpus"], s["compute_cap"]) == ("absent", "no", "0/4", "0", "none"), s
    assert "driver tool: absent" in g.rec("gpu-facts", "gpus.txt").read_text()


def test_a_failing_driver_tool_and_a_missing_node_are_recorded_words_not_failures(g):
    g.driver_up()
    g.flag("smi-fail")
    os.remove(str(g.root / "dev" / "nvidia-uvm"))
    os.chmod(str(g.root / "dev" / "nvidia1"), 0)
    s = summary_of(facts(g).stdout)
    assert (s["gpus"], s["compute_cap"]) == ("0", "none"), s
    nodes = g.rec("gpu-facts", "nodes.txt").read_text()
    assert "nvidia-uvm missing" in nodes and "nvidiactl usable" in nodes, nodes
    if os.geteuid() != 0:
        assert s["nodes"] == "2/4" and "nvidia1 not usable" in nodes, nodes
    assert "driver tool: failed" in g.rec("gpu-facts", "gpus.txt").read_text()


def test_a_second_gpu_facts_writes_gpu_facts_2_and_leaves_the_first_as_it_was(g):
    facts(g)
    first = {p.name: p.read_bytes() for p in g.rec("gpu-facts").iterdir()}
    g.driver_up()
    r = facts(g)
    assert {p.name: p.read_bytes() for p in g.rec("gpu-facts").iterdir()} == first
    assert summary_of(g.rec("gpu-facts-2", "summary.txt").read_text())["bound"] == "nvidia,nvidia"
    assert g.rec("gpu-facts-2", "host-after.txt").exists() and "boot=same" in r.stdout
    facts(g)
    assert g.rec("gpu-facts-3", "summary.txt").exists()


def test_gpu_facts_with_no_record_directory_prints_the_summary_only_and_says_nothing_was_written(tmp_path):
    g = Rig(tmp_path, rec=False)
    r = facts(g)
    assert summary_of(r.stdout)["cpu_part"] == "0x41:0xd0c" and "nothing was written" in r.out, r.out
    assert not (g.w / "rec").exists() and not (g.w / "g5g-boot").exists()


@pytest.mark.parametrize("journal,dmesg,want", [
    ("kernel: Oops: 0000 [#1] SMP", None, "yes"), ("kernel: BUG: unable to handle page fault", None, "yes"),
    ("kernel: a quiet boot", None, "no"), (None, "[ 1.0] Internal error: Oops: 96000004", "yes"),
    (None, "[ 1.0] a quiet boot", "no"), (None, None, "unread")])
def test_kernel_oops_is_roots_read_of_the_journal_then_of_dmesg_and_unread_only_when_both_fail(g, journal, dmesg, want):
    os.remove(str(g.stub / "journal"))
    if journal:
        g.put("journal", journal)
    if dmesg:
        g.put("dmesg.out", dmesg)
    r = facts(g)
    assert summary_of(r.stdout)["kernel_oops"] == want, r.out
    assert "kernel_oops=%s" % want in g.rec("gpu-facts", "host-after.txt").read_text().splitlines()
    assert "Oops" not in g.everything() and "BUG:" not in g.everything(), "the word only, never the log's text"
    assert all("root=1" in c for c in g.calls("journalctl") + g.calls("dmesg")), "root's read"


def test_the_boot_marker_is_in_w_outside_rec_and_run_and_holds_a_hash_not_the_boot_id(g):
    r = facts(g)
    marker = g.w / "g5g-boot"
    assert marker.read_text() == _h(BOOT_ID + "\n") + "\n"
    assert BOOT_ID not in r.out + g.everything() + marker.read_text()
    assert list(g.run_dir.iterdir()) == [] and not list(g.w.joinpath("rec").rglob("g5g-boot"))
    assert "kernel_oops_prev" not in r.out + g.everything() and "pstore" not in r.out
    # every login is a session of its own: the user's runtime directory is gone between two steps
    shutil.rmtree(str(g.run_dir))
    g.run_dir.mkdir()
    assert summary_of(facts(g).stdout)["boot"] == "same"


BOOT_UNREAD = "the boot id was not read, so no boot marker was written (%s): the next phase will read this boot as new (boot=new)"
SAY_STAMP = re.compile(r"^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\] ")


def ran_facts(g):
    """One gpu-facts run as the test below compares two: its exit status; its printed lines, say's clock stamp and the
    rig's own directory taken out; and every file under W by its path, with its bytes, host-after.txt by its two words
    alone (the rest of it is the host's clock, load and interrupt counts, which differ from run to run). Last, for each
    printed line of stdout in its order, whether it carried say's clock stamp."""
    r = g.run("gpu-facts")
    tmp = str(g.tmp)
    files = {}
    for p in sorted(g.w.rglob("*")):
        if p.is_file():
            b = p.read_bytes().replace(tmp.encode(), b"<tmp>")
            if p.name == "host-after.txt":
                b = b"\n".join(ln for ln in b.splitlines() if ln.startswith((b"kernel_oops", b"boot=")))
            files[str(p.relative_to(g.w))] = b
    lines = lambda text: [SAY_STAMP.sub("", ln).replace(tmp, "<tmp>") for ln in text.splitlines()]   # noqa: E731
    stamped = [SAY_STAMP.match(ln) is not None for ln in r.stdout.splitlines()]
    return r.returncode, lines(r.stdout), lines(r.stderr), files, stamped


def test_a_first_gpu_facts_that_cannot_read_the_boot_id_says_so_and_differs_by_that_line_and_the_marker_alone(tmp_path):
    """A first gpu-facts that cannot read the boot id writes no marker, so the next phase reads boot=new. It says so in
    one line of its own; nothing else of its run differs from one with a readable boot id but that line and the marker
    (its exit status, every other line, every file it writes), and a later phase reads boot=new and refuses as before.
    The line is say's, with its clock stamp, as the phase's other lines are."""
    read, unread = Rig(tmp_path / "read"), Rig(tmp_path / "unread")
    os.remove(str(unread.root / "proc" / "sys" / "kernel" / "random" / "boot_id"))
    rc_r, out_r, err_r, files_r, _stamped_r = ran_facts(read)
    rc_u, out_u, err_u, files_u, stamped_u = ran_facts(unread)
    line = BOOT_UNREAD % "<tmp>/w/g5g-boot"
    assert rc_r == rc_u == 0 and err_r == err_u, (rc_r, rc_u, err_r, err_u)
    assert line not in out_r and out_u.count(line) == 1, out_u
    assert len(stamped_u) == len(out_u) and stamped_u[out_u.index(line)], "the unread line carries say's clock stamp"
    assert [ln for ln in out_u if ln != line] == out_r, (out_r, out_u)
    assert "g5g-boot" in files_r and "g5g-boot" not in files_u, (sorted(files_r), sorted(files_u))
    assert {k: v for k, v in files_r.items() if k != "g5g-boot"} == files_u, "every other file, byte for byte"
    later = unread.run("gpu-install", "MODE=plan")
    assert later.returncode != 0 and "boot=new: this host has booted since gpu-facts first ran" in later.out, later.out


@pytest.mark.parametrize("how", ["boot id changed", "marker gone beside a gpu-facts stem"])
@pytest.mark.parametrize("prev,want", [("kernel: Oops: 0 [#1]", "yes"), ("kernel: a clean end", "no"), (None, "unread")])
def test_a_new_boot_is_said_with_the_previous_boots_word_and_every_other_new_phase_refuses(g, how, prev, want):
    facts(g)
    kept = (g.w / "g5g-boot").read_text()
    if how == "boot id changed":
        aws._write(g.root / "proc" / "sys" / "kernel" / "random" / "boot_id", "ffffffff-1111-2222-3333-0e1f2a3b4c5d")
    else:
        os.remove(str(g.w / "g5g-boot"))
    if prev:
        g.put("journal-prev", prev)
    for n in ("dmesg-efi-1", "dmesg-efi-2"):
        (g.root / "sys" / "fs" / "pstore" / n).write_text("an entry's text, never read")
    r = facts(g)
    s = summary_of(r.stdout)
    assert (s["boot"], s["kernel_oops_prev"], s["pstore"]) == ("new", want, "2"), s
    after = g.rec("gpu-facts-2", "host-after.txt").read_text().splitlines()
    assert "boot=new" in after and "kernel_oops_prev=%s" % want in after, after
    assert "never read" not in g.everything()
    if how == "boot id changed":
        assert (g.w / "g5g-boot").read_text() == kept, "only the first run writes the marker: a new boot stays new"
    for phase in NEW_PHASES:
        x = g.run(phase, "MODE=plan" if phase == "gpu-install" else "IMAGE=ifs-svc.bin" if phase == "launch-svc" else None)
        assert x.returncode != 0 and "boot=new" in x.out, phase + ": " + x.out
    assert not g.calls("apt-get") and not g.calls("dpkg -i") and not g.calls("launcher") and not g.calls("loginctl")


@pytest.mark.parametrize("phase", ("gpu-facts",) + NEW_PHASES)
def test_each_new_phase_refuses_under_the_vss_session_marker(g, phase):
    (g.w / "vss-session").write_text("")
    r = g.run(phase)
    assert r.returncode != 0 and "vss-session exists" in r.out and "the %s phase" % phase in r.out, r.out
    assert not g.rec(phase).exists()


@pytest.mark.parametrize("phase", NEW_PHASES)
def test_another_new_phase_that_finds_no_marker_refuses_gpu_facts_runs_first(g, phase):
    r = g.run(phase, "MODE=plan" if phase == "gpu-install" else None)
    assert r.returncode != 0 and "run gpu-facts first" in r.out, r.out


# ------------------------------------------------------------------ gpu-install: the plan

def plan(g, **env):
    return g.run("gpu-install", "MODE=plan", **env)


def set_sha(pkgs=SET):
    return _h("".join(sorted("%s=%s\n" % (n, v) for n, v, _s, _z in pkgs)))


def test_the_plan_ends_approved_with_its_words_and_its_files(g):
    facts(g)
    r = plan(g)
    assert r.returncode == 0, r.out
    out = r.stdout
    pins = g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins"
    for word in ("key package verified", "pins written %s" % _h(pins.read_bytes()), "pins in force: 4 of 4",
                 "indexes refreshed: 30800000 bytes fetched (index cap 60000000)",
                 "enabled components: main restricted universe multiverse",
                 "list file %s" % _h(open(os.path.join(EDGE, "g5g-packages.list"), "rb").read()),
                 "approved file %s" % _h((g.w / "in" / "g5g-approved.txt").read_bytes()),
                 "bytes to fetch: 37800 (approved total 40000)"):
        assert word in out, word + "\n" + r.out
    assert out.splitlines()[-1] == "plan: approved set %s" % set_sha(), out
    stem = g.rec("gpu-install")
    assert (stem / "set.txt").read_text() == "".join(sorted("%s=%s\n" % (n, v) for n, v, _s, _z in SET))
    sv = (stem / "set-v.txt").read_text().splitlines()
    assert sv[0].startswith("#") and "_" in sv[0] and sorted(sv[1:]) == sorted(
        "%s=%s" % (n, v.replace(".", "_")) for n, v, _s, _z in SET), sv
    debs = (stem / "debs.txt").read_text()
    assert "cmake ubuntu 9000 %s" % _deb_sha("cmake") in debs and "cuda-nvcc-13-2 nvidia 5000 " in debs, debs
    after = (stem / "host-after.txt").read_text()
    assert "kernel_oops=no" in after and "boot=same" in after
    # the names apt was asked for: the list file's, each by name=version, with the word that keeps recommends out
    asked = [c for c in g.calls("apt-get") if " install " in c]
    assert len(asked) == 2 and all("--no-install-recommends" in c for c in asked), asked
    for n, v, _s, _z in SET[:7] + SET[8:9]:
        assert all(" %s=%s " % (n, v) in c for c in asked), n
    assert not any("cuda-toolkit-config-common" in c for c in asked), "a name apt is not asked for: the pin file holds it"
    assert not g.calls("apt-get -y") and not (g.stub / "installed").exists(), "a plan installs nothing else"
    # it adds no source and no component: the key package's own files are the only new ones
    srcs = sorted(p.name for p in (g.root / "etc" / "apt" / "sources.list.d").iterdir())
    assert srcs == ["cuda-ubuntu2404-sbsa.list", "ubuntu.sources"], srcs
    assert "multiverse\n\nTypes" in (g.root / "etc" / "apt" / "sources.list.d" / "ubuntu.sources").read_text()
    assert sorted(p.name for p in pins.parent.iterdir()) == ["cuda-repository-pin-600", "g5g-nvidia-pins"]
    assert not g.calls("add-apt-repository") and not g.calls("reboot") and not g.calls("shutdown")


def test_a_newer_unversioned_config_package_resolves_to_the_approved_line_under_the_pin_file(g):
    """The stub index offers cuda-toolkit-config-common newer, as NVIDIA's repository does; no list name asks for it."""
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and "cuda-toolkit-config-common=13.0.86-1\n" in g.rec("gpu-install", "set.txt").read_text(), r.out
    assert "13.9.37" not in g.rec("gpu-install", "set.txt").read_text()


def refusing(g, reason, **env):
    facts(g)
    r = plan(g, **env)
    assert r.returncode != 0, r.out
    assert r.stdout.splitlines()[-1] == "plan: refused", r.out
    assert "refused: " + reason in r.stdout, r.out
    assert not (g.stub / "installed").exists() and not g.rec("gpu-install", "plan-approved.txt").exists()
    assert g.rec("gpu-install", "host-after.txt").exists()
    return r


@pytest.mark.parametrize("case,reason", [
    ("outside", "not in the approved file: libstub-extra1"),
    ("version", "version differs from the approved file: cmake"),
    ("source", "source differs from the approved file: cmake"),
    ("sha", "size or sha256 differs from the approved file: cuda-nvcc-13-2"),
    ("total", "bytes to fetch 37800 over the approved total 37799"),
    ("kernel-image", "kernel package: linux-image-0.0.0-2-stub"),
    ("kernel-meta", "kernel package: linux-aws"),
    ("kernel-modules", "kernel package: linux-modules-0.0.0-2-stub"),
    ("kernel-headers", "kernel package: linux-headers-0.0.0-2-stub"),
    ("kernel-tools", "kernel package: linux-tools-0.0.0-2-stub"),
    ("removal", "removal: libstub-old"),
    ("abi", "module package for another kernel: linux-modules-nvidia-580-server-0.0.0-2-stub"),
    ("objects-abi", "module package for another kernel: linux-objects-nvidia-580-server-0.0.0-2-stub"),
    ("signatures-abi", "module package for another kernel: linux-signatures-nvidia-580-server-0.0.0-2-stub"),
    ("flavour-meta", "module package for another kernel: linux-modules-nvidia-580-server-aws"),
    ("upgrade", "upgrade of an installed package: cmake-data"),
    ("upgrade-approved", "upgrade of an installed package: cmake-data"),
])
def test_the_plan_refuses_each_difference_alone_by_name(g, case, reason):
    extra = lambda n, v="0.0.1-1", src="ubuntu": (n, v, src, 10)   # noqa: E731
    if case == "outside":
        g.apt(SET + [extra("libstub-extra1")])
    elif case == "version":
        g.apt(SET[:8] + [("cmake", "0.0.2" + UB[5:], "ubuntu", 9000)])
    elif case == "source":
        g.apt(SET, host={"cmake": HOSTS["nvidia"]})
    elif case == "sha":
        g.apt(SET, shas={"cuda-nvcc-13-2": "f" * 64})
    elif case == "total":
        g.approve(approved_text(total=37799))
    elif case.startswith("kernel") or case in ("abi", "flavour-meta", "objects-abi", "signatures-abi"):
        name = reason.split(": ")[1]
        g.approve(approved_text(PKGS + [extra(name)]))      # even an approved line cannot let one in
        g.apt(SET + [extra(name)])
    elif case == "removal":
        g.apt(SET, remove=("libstub-old",))
    elif case == "upgrade":
        g.apt(SET + [("cmake-data", "0.0.9-1", "ubuntu", 100)], upgrade=("cmake-data",))
    elif case == "upgrade-approved":
        g.apt(SET + [PKGS[9]], upgrade=("cmake-data",))     # to the very version the approved file lists
    refusing(g, reason)
    assert g.rec("gpu-install", "set.txt").exists(), "a plan that resolved, refused: T10's evidence"


def test_the_plan_refuses_a_package_of_a_third_origin_as_neither_source(g):
    """A package fetched from a host that is not NVIDIA's, with an origin that is not Ubuntu's (a PPA's here), is of
    neither source an approved line can name, so the approved line's ubuntu differs and the plan refuses it by name."""
    third = "LP-PPA-stub:24.04/noble"
    g.apt(SET, host={"cmake": "https://ppa.launchpadcontent.net/stub/ppa/ubuntu"})
    sim = sim_lines(SET)
    assert sim.count("(%s %s [arm64])" % (UB, ORIGIN["ubuntu"])) == 2, "cmake's Inst and Conf lines alone carry this version"
    g.put("apt-sim.pinned.out", sim.replace("(%s %s [arm64])" % (UB, ORIGIN["ubuntu"]), "(%s %s [arm64])" % (UB, third)), nl=False)
    r = refusing(g, "source differs from the approved file: cmake")
    assert r.stdout.count("refused: ") == 1, r.out
    assert "cmake other " in g.rec("gpu-install", "debs.txt").read_text(), "neither nvidia nor ubuntu: the word other"


def test_the_plan_refuses_a_key_package_whose_sha256_differs_before_dpkg_sees_it(g):
    g.approve(approved_text(key_sha="0" * 64))
    refusing(g, "key package sha256 differs")
    assert not g.calls("dpkg") and not g.calls("apt-get")


def test_the_plan_refuses_when_the_key_packages_installed_files_differ_from_the_approved_list(g):
    g.flag("key-extra")
    refusing(g, "key package files differ: /etc/apt/apt.conf.d-extra")
    assert not g.calls("apt-get")
    g2 = Rig(g.tmp / "second")
    g2.put("keyfiles/" + "/usr/share/keyrings/cuda-archive-keyring.gpg".replace("/", "%"), "another key")
    refusing(g2, "key package files differ: /usr/share/keyrings/cuda-archive-keyring.gpg")


def test_the_plan_refuses_a_pin_file_whose_sha256_differs_before_anything_is_resolved(g):
    g.approve(approved_text(pins_sha="0" * 64))
    refusing(g, "pin file sha256 differs")
    assert not g.calls("apt-get") and not (g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins").exists()


def test_the_plan_refuses_index_bytes_over_the_index_cap(g):
    g.approve(approved_text(cap=30799999))
    refusing(g, "index bytes 30800000 over the index cap 30799999")
    assert not any(" install " in c for c in g.calls("apt-get"))


def test_index_bytes_equal_to_the_index_cap_pass_the_plan(g):
    g.approve(approved_text(cap=30800000))
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "plan: approved set %s" % set_sha(), r.out
    assert "indexes refreshed: 30800000 bytes fetched (index cap 30800000)" in r.stdout, r.out


def test_bytes_to_fetch_equal_to_the_approved_total_pass_and_one_more_is_refused(g):
    g.approve(approved_text(total=37800))       # the made-up closure's sizes: 1000 + ... + 9000
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "plan: approved set %s" % set_sha(), r.out
    assert "bytes to fetch: 37800 (approved total 37800)" in r.stdout, r.out
    g2 = Rig(g.tmp / "second")
    g2.approve(approved_text(total=37799))
    refusing(g2, "bytes to fetch 37800 over the approved total 37799")


def test_a_plan_refused_after_its_resolve_still_says_the_sets_sha256(g):
    g.approve(approved_text(total=100))
    refusing(g, "bytes to fetch 37800 over the approved total 100")
    sha = _h(g.rec("gpu-install", "set.txt").read_bytes())
    assert "\nset %s\n" % sha in "\n" + g.rec("gpu-install", "plan.txt").read_text()
    assert sha == set_sha(), "the sorted name=version lines of the set"


def test_the_plan_refuses_an_approved_keyfile_the_key_package_did_not_install_and_writes_no_pin_file(g):
    g.approve(approved_text(extra="keyfile /etc/apt/extra-key %s\n" % _h("not installed")))
    refusing(g, "key package files differ: /etc/apt/extra-key")
    assert not g.calls("apt-get") and not (g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins").exists()


@pytest.mark.parametrize("comp", ["main restricted", "universe"])
def test_the_plan_prints_the_components_the_hosts_sources_enable(g, comp):
    aws._write(g.root / "etc" / "apt" / "sources.list.d" / "ubuntu.sources",
               "Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble\nComponents: %s" % comp)
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and "enabled components: %s (none added" % comp in r.stdout, r.out


@pytest.mark.parametrize("line,want", [("Fetched 1,234 kB in 1s (1 kB/s)", "1234000"), ("Fetched 512 B in 0s (0 B/s)", "512"),
                                       ("Hit:1 http://ports.ubuntu.com noble InRelease", "0")])
def test_the_plan_reads_the_bytes_apt_says_it_fetched_in_apts_units(g, line, want):
    g.put("apt-update.out", line)
    facts(g)
    r = plan(g)
    assert "indexes refreshed: %s bytes fetched" % want in r.stdout, r.out


def test_the_plan_reads_the_pins_back_from_apt_and_names_a_package_whose_candidate_differs(g):
    g.put("cand.cuda-nvcc-13-2", "13.9.9" + ".9-1")
    refusing(g, "pin not in force: cuda-nvcc-13-2")
    assert not any(" install " in c for c in g.calls("apt-get")), "read back before it resolves"
    assert len(g.calls("apt-cache policy")) == 4


def test_a_plan_whose_set_is_a_strict_subset_of_the_approved_file_is_approved(g):
    g.apt(SET[:8])          # cmake is already there on this made-up AMI
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "plan: approved set %s" % set_sha(SET[:8]), r.out


def test_gpu_install_needs_a_mode_word_and_takes_no_other(g):
    facts(g)
    for words in (None, "MODE=install", "MODE=plan EXTRA=1"):
        r = g.run("gpu-install", words)
        assert r.returncode != 0 and "MODE=plan or MODE=apply" in r.out, r.out
    assert not g.calls("dpkg") and not g.calls("apt-get")


ONE_MODE = "gpu-install takes one word, MODE=plan or MODE=apply (LADDER_ENV), and no other"
LLAMA_WORDS = "llama-build takes MODE=stop or MODE=wait, or JOBS= and MEM_MAX= together, and no other word (LADDER_ENV)"


def tree_of(d):
    """Every file under d, by its path there, with its bytes (empty when d is not there)."""
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


@pytest.mark.parametrize("words", ["MODE=plan MODE=apply", "MODE=apply MODE=plan", "MODE=plan MODE=plan", "MODE=apply MODE=apply",
                                   "MODE=plan MODE=plan MODE=apply", "MODE=apply MODE=apply MODE=apply"])
def test_gpu_install_refuses_two_mode_words_by_its_refusal_before_any_effect(g, words):
    """gpu-install takes one MODE word, as its refusal says. Two, equal or not, are refused by that refusal before any
    effect, as a wrong word is: after an approved plan, "MODE=plan MODE=apply" is no apply (the last word does not win),
    nothing is asked of a package tool and the plan's stem is as it was."""
    planned(g)
    before = tree_of(g.rec("gpu-install"))
    r = g.run("gpu-install", words)
    assert r.returncode != 0 and ONE_MODE in r.out, r.out
    assert g.calls() == [] and not (g.stub / "installed").exists(), g.calls()
    assert tree_of(g.rec("gpu-install")) == before, "the plan's stem as it was: no host-after.txt rewritten, no apply.txt"


@pytest.mark.parametrize("words", ["MODE=stop MODE=wait", "MODE=wait MODE=stop", "MODE=wait MODE=wait", "JOBS=4 JOBS=8 MEM_MAX=16G",
                                   "JOBS=8 MEM_MAX=8G MEM_MAX=16G", "JOBS=8 MEM_MAX=16G JOBS=8", "MODE=stop MODE=stop",
                                   "MEM_MAX=16G JOBS=8 MEM_MAX=16G"])
def test_llama_build_refuses_a_word_given_twice_by_its_refusal_before_any_effect(g, words):
    """llama-build's words are MODE=stop or MODE=wait, or JOBS= and MEM_MAX= together, each once; a word given twice,
    equal or not, is refused by llama-build's own refusal before its stem is made, a build is started, waited for or
    stopped, or anything is asked of logind."""
    gpu_ready(g)
    (g.stub / "calls.log").unlink()
    r = g.run("llama-build", words)
    assert r.returncode != 0 and LLAMA_WORDS in r.out, r.out
    assert g.calls() == [] and not g.rec("llama-build").exists() and not (g.stub / "build.env").exists(), g.calls()


def test_the_plan_asks_apt_for_each_debs_sha256_and_names_another_hash_by_its_type(g):
    """apt prints one hash a file; the stub prints SHA512, the strongest its index carries, unless asked for SHA256."""
    facts(g)
    r = plan(g)
    assert r.returncode == 0, r.out
    uris = [c for c in g.calls("apt-get") if "--print-uris" in c]
    assert len(uris) == 1 and " -o Acquire::ForceHash=SHA256 " in uris[0], uris
    debs = g.rec("gpu-install", "debs.txt").read_text().splitlines()
    assert len(debs) == 9 and all(re.fullmatch(r"\S+ (ubuntu|nvidia) \d+ [0-9a-f]{64}", d) for d in debs), debs
    g2 = Rig(g.tmp / "second")
    g2.flag("forcehash-ignored")
    r = refusing(g2, "no SHA256 from apt (it printed SHA512): cuda-nvcc-13-2")
    assert r.stdout.count("refused: no SHA256 from apt (it printed SHA512): ") == 9 and "size or sha256 differs" not in r.stdout, r.out


def _approved_without(prefix, add=""):
    return "".join(ln + "\n" for ln in approved_text().splitlines() if not ln.startswith(prefix)) + add


@pytest.mark.parametrize("case,reason", [
    ("no index-cap", "the approved file has no one line `index-cap BYTES`"),
    ("two index-caps", "the approved file has no one line `index-cap BYTES`"),
    ("an index-cap that is no number", "the approved file has no one line `index-cap BYTES`"),
    ("no total", "the approved file has no one line `total all BYTES`"),
    ("two keys", "the approved file has no one line `key PACKAGE FILE.deb SHA256`"),
    ("no key", "the approved file has no one line `key PACKAGE FILE.deb SHA256`"),
    ("no pins", "the approved file has no one line `pins g5g-nvidia-pins SHA256`"),
    ("two pins", "the approved file has no one line `pins g5g-nvidia-pins SHA256`"),
    ("a list name with no pkg line", "not in the approved file: cmake"),
    ("a pkg line twice", "named twice in the approved file: cmake"),
    ("a pkg line of another form", "a pkg line of another form in the approved file: cmake"),
])
def test_the_plan_reads_the_whole_approved_file_before_it_changes_anything(g, case, reason):
    cmake = "pkg cmake=%s ubuntu 9000 %s\n" % (UB, _deb_sha("cmake"))
    g.approve({
        "no index-cap": lambda: _approved_without("index-cap "),
        "two index-caps": lambda: approved_text() + "index-cap 60000000\n",
        "an index-cap that is no number": lambda: _approved_without("index-cap ", "index-cap 60MB\n"),
        "no total": lambda: _approved_without("total all "),
        "two keys": lambda: approved_text() + "key cuda-keyring cuda-keyring_1.1-1_all.deb %s\n" % _h(DEB),
        "no key": lambda: _approved_without("key "),
        "no pins": lambda: _approved_without("pins "),
        "two pins": lambda: approved_text() + "pins g5g-nvidia-pins %s\n" % ("0" * 64),
        "a list name with no pkg line": lambda: _approved_without("pkg cmake="),
        "a pkg line twice": lambda: approved_text() + cmake,
        "a pkg line of another form": lambda: _approved_without("pkg cmake=", "pkg cmake=%s ubuntu 9000\n" % UB),
    }[case]())
    refusing(g, reason)
    changed = g.calls("dpkg") + g.calls("apt-get") + g.calls("apt-cache") + g.calls("sudo -n install")
    assert not changed, "refused with nothing changed: %s" % changed
    assert not (g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins").exists()
    assert not (g.root / "etc" / "apt" / "sources.list.d" / "cuda-ubuntu2404-sbsa.list").exists()


def test_the_plan_refuses_by_a_word_when_the_key_packages_files_cannot_be_listed(g):
    g.flag("dpkg-L-fail")
    refusing(g, "key package files unread")
    assert not g.calls("apt-get") and not (g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins").exists()


def test_the_plan_says_an_empty_set(g):
    g.apt([])               # everything the list names is already there on this made-up AMI
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and "the set is empty: " in r.stdout, r.out
    assert r.stdout.splitlines()[-1] == "plan: approved set %s" % _h(""), r.out


def test_the_plan_reads_a_sources_stanza_whole_whatever_the_order_of_its_fields(g):
    aws._write(g.root / "etc" / "apt" / "sources.list.d" / "ubuntu.sources",
               "Types: deb\nComponents: main restricted\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble\n\n"
               "Types: deb\nComponents: universe\nURIs: https://repo.example.invalid/apt\nSuites: stable\n\n"
               "Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble-security")
    facts(g)
    r = plan(g)
    assert r.returncode == 0 and "enabled components: main restricted (none added" in r.stdout, r.out


def test_gpu_facts_writes_each_nvidia_devices_vendor_id_beside_its_device_id_and_driver(g):
    g.bind("nouveau")
    facts(g)
    assert g.rec("gpu-facts", "pci.txt").read_text() == "0x1eb4 nouveau 0x10de\n" * 2


# ------------------------------------------------------------------ gpu-install: apply

def apply(g, **env):
    return g.run("gpu-install", "MODE=apply", **env)


def planned(g):
    facts(g)
    r = plan(g)
    assert r.returncode == 0, r.out
    (g.stub / "calls.log").unlink()


def order(g, *needles):
    """The index of the first call holding each needle, in the order given: all there and ascending."""
    calls = g.calls()
    idx = [next((i for i, c in enumerate(calls) if n in c), -1) for n in needles]
    assert -1 not in idx and idx == sorted(idx), "%s -> %s\n%s" % (needles, idx, "\n".join(calls))


def test_apply_installs_exactly_the_set_loads_the_modules_and_checks_the_nodes(g):
    planned(g)
    r = apply(g)
    assert r.returncode == 0, r.out
    out = r.stdout
    assert "nouveau" not in out
    assert "nvidia and nvidia_uvm loaded, no reboot" in out and "nodes: 4 of 4 present and usable" in out, out
    assert "71-nvidia.rules" in out and "ub-device-create" in out and "nvidia-smi as root" in out, out
    assert out.splitlines()[-1] == "installed set %s" % set_sha(), out
    inst = [c for c in g.calls("apt-get") if " install " in c and " -s " not in c and "--print-uris" not in c]
    assert len(inst) == 1 and "--no-install-recommends" in inst[0] and "root=1" in inst[0], inst
    words = inst[0].split()
    assert words[:4] == ["apt-get", "-y", "install", "--no-install-recommends"] and words[-1] == "root=1", inst
    assert sorted(words[4:-1]) == sorted("%s=%s" % (n, v) for n, v, _s, _z in SET), "exactly the set, each by name=version"
    order(g, "apt-get -y", "dpkg-query", "modprobe nvidia", "modprobe nvidia_uvm", "udevadm settle", SMI_ROOT)
    assert not g.calls("nvidia-modprobe") and not g.calls("mknod") and not g.calls("rmmod")
    assert not g.calls("reboot") and not g.calls("shutdown") and not any("reboot" in c for c in g.calls("systemctl"))
    assert "installed set %s" % set_sha() in g.rec("gpu-install", "apply.txt").read_text()


def test_apply_refuses_without_an_approved_plan_and_after_a_refused_one(g):
    facts(g)
    r = apply(g)
    assert r.returncode != 0 and "no approved plan in this session" in r.out, r.out
    planned(g)
    g.apt(SET, remove=("libstub-old",))
    assert plan(g).returncode != 0
    r = apply(g)
    assert r.returncode != 0 and "no approved plan in this session" in r.out, r.out
    assert not (g.stub / "installed").exists()


@pytest.mark.parametrize("how", ["set", "pins-gone", "pins-changed"])
def test_apply_refuses_when_the_set_or_the_pin_file_is_no_longer_the_plans(g, how):
    planned(g)
    pins = g.root / "etc" / "apt" / "preferences.d" / "g5g-nvidia-pins"
    if how == "set":
        g.apt(SET[:8])
    elif how == "pins-gone":
        pins.unlink()
    else:
        pins.write_text(pins.read_text() + "\n")
    r = apply(g)
    assert r.returncode != 0 and ("is not the plan's" in r.out), r.out
    assert not (g.stub / "installed").exists() and not g.calls("modprobe")


def test_apply_refuses_when_its_fresh_resolve_refuses_though_the_set_is_the_plans(g):
    """Apply's fresh resolve can refuse while its set is the plan's (here apt now gives one .deb a sha256 the approved
    file does not name); apply then installs nothing, loads no module and says why, though the set's sha256 is the one
    the plan approved."""
    planned(g)
    g.apt(SET, shas={"cuda-nvcc-13-2": "f" * 64})
    r = apply(g)
    assert r.returncode != 0 and "a fresh resolve's set is not the plan's: nothing installed" in r.out, r.out
    assert "refused: size or sha256 differs from the approved file: cuda-nvcc-13-2" in r.stdout, r.out
    fresh = g.rec("gpu-install", "apply-resolve", "set.txt")
    assert _h(fresh.read_bytes()) == set_sha(), "the fresh set is the plan's: the resolve's refusal alone stops the apply"
    assert not (g.stub / "installed").exists() and not g.calls("modprobe") and not g.calls("apt-get -y"), g.calls()


def test_apply_fails_when_the_installed_set_is_not_the_plans(g):
    planned(g)
    g.put("dpkg-query.out", "".join(sorted("%s=%s\n" % (n, v) for n, v, _s, _z in SET[:8])) + "cmake=0.0.2-1")
    r = apply(g)
    assert r.returncode != 0 and "installed set" in r.out and "is not the plan's" in r.out, r.out
    assert not g.calls("modprobe nvidia"), "no module is loaded over a set that is not the approved one"


@pytest.mark.parametrize("made,word", [("nvidiactl nvidia0 nvidia1", "node missing: nvidia-uvm"),
                                       ("nvidiactl nvidia0 nvidia-uvm", "node missing: nvidia1")])
def test_apply_with_a_device_node_missing_says_which_and_fails_and_makes_none_by_hand(g, made, word):
    planned(g)
    g.put("nodes-made", made)
    r = apply(g)
    assert r.returncode != 0 and word in r.stdout and "nodes: 3 of 4 present and usable" in r.stdout, r.out
    assert "installed set %s" % set_sha() in r.stdout
    assert not g.calls("mknod") and not (g.root / "dev" / word.split(": ")[1]).exists()


def test_apply_unloads_a_bound_nouveau_before_any_package_then_loads_nvidia(g):
    g.bind("nouveau")
    planned(g)
    r = apply(g)
    assert r.returncode == 0 and "nouveau unloaded\n" in r.stdout and "unloaded again" not in r.stdout, r.out
    order(g, "modprobe -r nouveau", "apt-get -y", "modprobe nvidia")
    assert "nouveau" not in (g.root / "proc" / "modules").read_text()


def test_apply_installs_nothing_when_nouveau_cannot_be_unloaded(g):
    g.bind("nouveau")
    planned(g)
    g.flag("nouveau-held")
    r = apply(g)
    assert r.returncode != 0 and r.stdout.splitlines()[-1] == "nouveau held: nothing installed", r.out
    assert not (g.stub / "installed").exists() and not g.calls("apt-get -y") and not g.calls("modprobe nvidia")
    assert g.rec("gpu-install", "host-after.txt").exists()


def test_apply_unloads_nouveau_again_by_rmmod_when_the_install_brought_it_back(g):
    planned(g)
    g.flag("nouveau-back")
    r = apply(g)
    assert r.returncode == 0 and "nouveau unloaded again" in r.stdout, r.out
    order(g, "apt-get -y", "rmmod nouveau", "modprobe nvidia")
    assert not g.calls("modprobe -r"), "after the install the driver's alias turns modprobe -r nouveau into nothing"
    assert "nouveau" not in (g.root / "proc" / "modules").read_text()


def test_apply_loads_no_module_when_nouveau_is_held_after_the_install(g):
    planned(g)
    g.flag("nouveau-back")
    g.flag("nouveau-held-again")
    r = apply(g)
    assert r.returncode != 0 and r.stdout.splitlines()[-1] == "nouveau held after the install: nvidia not loaded", r.out
    assert (g.stub / "installed").exists() and not g.calls("modprobe nvidia")


def test_apply_records_a_module_that_does_not_load_and_does_not_reboot(g):
    planned(g)
    g.flag("nvidia-noload")
    r = apply(g)
    assert r.returncode != 0 and "nvidia not loaded: no reboot is made" in r.stdout, r.out
    assert not g.calls("reboot") and not g.calls("shutdown")


def test_apply_calls_nvidia_modprobe_only_when_the_approved_file_names_it(g):
    g.approve(approved_text(PKGS + [("nvidia-modprobe", "0.0.1-1", "ubuntu", 10)]))
    planned(g)
    r = apply(g)
    assert r.returncode == 0 and g.calls("nvidia-modprobe") == ["nvidia-modprobe -u -c 0"], r.out
    order(g, SMI_ROOT, "nvidia-modprobe -u -c 0")
    assert "nodes after nvidia-modprobe -u -c 0: 4 of 4" in r.stdout, r.out


def test_apply_says_how_many_nodes_stand_after_each_tool_that_can_make_them(g):
    planned(g)
    g.put("nodes-made", "nvidiactl nvidia0 nvidia1")
    g.flag("smi-makes-uvm")
    r = apply(g)
    assert r.returncode == 0, r.out
    out = r.stdout.splitlines()
    first, second = "nodes after the udev rule and helper (udevadm settle): 3 of 4", "nodes after nvidia-smi as root: 4 of 4"
    assert first in out and second in out and out.index(first) < out.index(second), r.out
    assert not [ln for ln in out if ln.startswith("nodes after nvidia-modprobe")], "not run: the approved file does not name it"
    assert first in g.rec("gpu-install", "apply.txt").read_text()


def test_apply_goes_on_by_a_word_when_the_driver_tool_does_not_end(g):
    planned(g)
    g.flag("smi-hang")
    t0 = time.monotonic()
    r = apply(g, G5G_SMI_WAIT_S=1)
    assert time.monotonic() - t0 < 20, "the tool's run is bounded"
    assert r.returncode == 0 and "nvidia-smi as root did not end within 1 s" in r.stdout, r.out
    assert "nodes: 4 of 4 present and usable" in r.stdout, r.out


def test_apply_fails_by_a_word_when_the_installed_set_cannot_be_read(g):
    planned(g)
    g.flag("dpkg-query-fail")
    r = apply(g)
    assert r.returncode != 0 and "installed set" in r.out and "is not the plan's" in r.out and "no module is loaded" in r.out, r.out
    assert not g.calls("modprobe nvidia")


def test_apply_installs_nothing_when_the_unload_leaves_a_device_bound_to_nouveau(g):
    g.bind("nouveau")
    planned(g)
    g.flag("nouveau-stays-bound")       # modprobe -r ends well and the module is gone, the devices' driver links are not
    r = apply(g)
    assert "nouveau " not in (g.root / "proc" / "modules").read_text()
    assert r.returncode != 0 and r.stdout.splitlines()[-1] == "nouveau held: nothing installed", r.out
    assert not (g.stub / "installed").exists() and not g.calls("apt-get -y") and not g.calls("modprobe nvidia")


def test_apply_loads_no_module_when_a_device_is_bound_to_nouveau_after_the_install_with_no_module_line(g):
    planned(g)
    g.flag("nouveau-bound-back")        # a built-in nouveau: /proc/modules has no line for it
    g.flag("nouveau-held-again")        # and rmmod cannot take it
    r = apply(g)
    assert "nouveau" not in (g.root / "proc" / "modules").read_text()
    assert r.returncode != 0 and r.stdout.splitlines()[-1] == "nouveau held after the install: nvidia not loaded", r.out
    assert g.calls("rmmod nouveau") and not g.calls("modprobe nvidia")


def test_apply_on_an_empty_set_asks_no_install_and_no_package_query_and_goes_on(g):
    g.apt([])               # everything the list names is already installed at its approved version
    planned(g)
    r = apply(g)
    assert r.returncode == 0, r.out
    assert not g.calls("apt-get -y") and not g.calls("dpkg-query"), "no name to ask for: no query that lists the whole host"
    assert "installed set %s" % _h("") in r.out and "is not the plan's" not in r.out and g.calls("modprobe nvidia")


def test_apply_reads_nvidia_uvm_back_and_says_when_it_did_not_load(g):
    planned(g)
    g.flag("uvm-noload")
    r = apply(g)
    assert r.returncode != 0 and "nvidia not loaded: no reboot is made" in r.stdout, r.out
    assert "nvidia and nvidia_uvm loaded" not in r.stdout and g.calls("modprobe nvidia_uvm"), r.out
    assert not g.calls("reboot") and not g.calls("shutdown")


# ------------------------------------------------------------------ llama-build

def gpu_ready(g):
    g.driver_up()
    facts(g)


def wait_build(g):
    return g.run("llama-build", "MODE=wait", timeout=120)


def test_llama_build_sizes_the_build_to_the_host_enables_lingering_and_runs_detached(g):
    gpu_ready(g)
    r = g.run("llama-build")
    assert r.returncode == 0, r.out
    assert "lingering enabled" in r.stdout and "llama-build: JOBS=31 MEM_MAX=62G" in r.stdout, r.out
    assert r.stdout.splitlines()[-1].endswith("started"), r.out
    w = wait_build(g)
    assert w.returncode == 0 and "build-llama.sh done with exit 0" in w.stdout and "checkout size: " in w.stdout, w.out
    env = (g.stub / "build.env").read_text().split()
    assert env == ["CUDA_ARCH=75", "JOBS=31", "MEM_MAX=62G", "LLAMA_COMMIT=" + LLAMA_PIN], env
    stem = g.rec("llama-build")
    assert "ARCHITECTURES=75" in (stem / "BUILD-INFO").read_text()
    after = (stem / "host-after.txt").read_text()
    assert "kernel_oops=no" in after and "boot=same" in after
    assert "JOBS=31 MEM_MAX=62G" in (stem / "size.txt").read_text()
    order(g, "loginctl enable-linger ubuntu root=1", "loginctl show-user ubuntu")
    assert SMI_ROOT not in g.calls(), "nothing built is run by this phase"


def test_llama_build_says_when_the_hosts_memory_cannot_be_read_and_takes_validated_words(g):
    gpu_ready(g)
    os.remove(str(g.root / "proc" / "meminfo"))
    r = g.run("llama-build")
    assert r.returncode == 0 and "memory was not read" in r.stdout and "lib-build.sh's own defaults apply" in r.stdout, r.out
    assert wait_build(g).returncode == 0
    assert (g.stub / "build.env").read_text().split()[1:3] == ["JOBS=", "MEM_MAX="]
    g2 = Rig(g.tmp / "second")
    gpu_ready(g2)
    assert g2.run("llama-build", "JOBS=8 MEM_MAX=16G").returncode == 0 and wait_build(g2).returncode == 0
    assert (g2.stub / "build.env").read_text().split()[1:3] == ["JOBS=8", "MEM_MAX=16G"]
    g3 = Rig(g.tmp / "third")
    gpu_ready(g3)
    for bad in ("JOBS=0", "JOBS=08", "MEM_MAX=16", "MEM_MAX=G", "JOBS=4", "MODE=go"):
        r = g3.run("llama-build", bad)
        assert r.returncode != 0 and not (g3.stub / "build.env").exists(), bad + ": " + r.out


@pytest.mark.parametrize("how", ["no driver", "cap 8.7", "one of two"])
def test_llama_build_refuses_unless_gpu_facts_read_7_5_on_every_gpu(g, how):
    if how == "no driver":
        os.remove(str(g.stub / "nvidia-smi"))
        facts(g)
    else:
        g.put("cap", "8.7")
        gpu_ready(g)
        if how == "one of two":
            s = g.rec("gpu-facts", "summary.txt")
            s.write_text(s.read_text().replace("compute_cap=8.7,8.7", "compute_cap=7.5,8.7"))
    r = g.run("llama-build")
    assert r.returncode != 0 and "compute_cap" in r.out and "7.5" in r.out, r.out
    assert not (g.stub / "build.env").exists() and not g.calls("loginctl")
    assert g.rec("llama-build", "host-after.txt").exists()


def test_llama_build_refuses_to_start_detached_without_the_lingering_read_back(g):
    gpu_ready(g)
    g.flag("linger-refused")
    r = g.run("llama-build")
    assert r.returncode != 0 and "lingering" in r.out and "not started" in r.out, r.out
    time.sleep(0.5)
    assert not (g.stub / "build.env").exists()


def test_llama_build_clones_only_when_the_approved_file_names_the_pin(g):
    g.approve(approved_text(llama=False))
    gpu_ready(g)
    r = g.run("llama-build")
    assert r.returncode != 0 and "the approved file names no llama.cpp pin" in r.out, r.out
    assert not (g.stub / "build.env").exists()


def test_a_failed_build_is_said_with_its_own_words_and_leaves_host_after_and_no_build_info(g):
    gpu_ready(g)
    g.flag("build-fail")
    assert g.run("llama-build").returncode == 0
    w = wait_build(g)
    assert w.returncode != 0 and "build-llama.sh done with exit 1" in w.stdout and "names as missing: CUDA_CUDART" in w.out, w.out
    stem = g.rec("llama-build")
    assert (stem / "host-after.txt").exists() and not (stem / "BUILD-INFO").exists()


def test_stop_mode_ends_a_running_build_and_with_none_running_changes_nothing(g):
    gpu_ready(g)
    r = g.run("llama-build", "MODE=stop")
    assert r.returncode == 0 and "no build is running: nothing changed" in r.stdout, r.out
    assert not g.rec("llama-build", "stopped").exists()
    g.flag("build-sleep")
    assert g.run("llama-build").returncode == 0
    for _ in range(100):
        if (g.stub / "build.pid").exists():
            break
        time.sleep(0.1)
    pid = int((g.stub / "build.pid").read_text())
    os.kill(pid, 0)
    stem = g.rec("llama-build")
    (stem / "host-after.txt").unlink()          # the start's own: what stands after the stop is the stop's
    r = g.run("llama-build", "MODE=stop")
    assert r.returncode == 0 and r.stdout.splitlines()[-1].endswith("stopped"), r.out
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert (stem / "stopped").exists() and "kernel_oops=" in (stem / "host-after.txt").read_text()
    assert subprocess.run(["flock", "-n", str(g.home / "builds" / "build-llama.lock"), "true"]).returncode == 0
    # a wait after the stop: no build is running and none ended whole, said at once and not waited for
    t0 = time.monotonic()
    w = g.run("llama-build", "MODE=wait", G5G_BUILD_WAIT_S=30)
    assert w.returncode not in (0, 2) and "stopped" in w.out and "nothing to wait for" in w.out, w.out
    assert time.monotonic() - t0 < 15


def sleeping_build(g):
    """A started build whose stub sleeps: the stub's pid, once it holds the build's lock."""
    g.flag("build-sleep")
    assert g.run("llama-build").returncode == 0
    for _ in range(100):
        if (g.stub / "build.pid").exists():
            break
        time.sleep(0.1)
    return int((g.stub / "build.pid").read_text())


def end_build(g):
    r = g.run("llama-build", "MODE=stop")
    assert r.returncode == 0, r.out


def test_a_wait_that_outlives_its_time_exits_2_and_can_be_made_again(g):
    gpu_ready(g)
    sleeping_build(g)
    try:
        for _ in range(2):
            w = g.run("llama-build", "MODE=wait", G5G_BUILD_WAIT_S=1)
            assert w.returncode == 2 and "the build has not ended: wait again, or MODE=stop" in w.out, w.out
    finally:
        end_build(g)


def test_a_second_start_while_a_build_runs_is_refused_and_leaves_the_first_as_it_is(g):
    gpu_ready(g)
    pid = sleeping_build(g)
    try:
        stem = g.rec("llama-build")
        runner = (stem / "runner.pid").read_text()
        r = g.run("llama-build")
        assert r.returncode != 0 and "a build is running" in r.out, r.out
        assert (stem / "runner.pid").read_text() == runner and int((g.stub / "build.pid").read_text()) == pid
        os.kill(pid, 0)
    finally:
        end_build(g)


def test_a_wait_after_a_start_that_was_refused_ends_at_once_by_a_word(g):
    g.put("cap", "8.7")
    gpu_ready(g)
    assert g.run("llama-build").returncode != 0 and g.rec("llama-build").is_dir()
    t0 = time.monotonic()
    w = g.run("llama-build", "MODE=wait", G5G_BUILD_WAIT_S=30)
    assert w.returncode not in (0, 2) and "no build is running and none ended whole" in w.out, w.out
    assert "nothing to wait for" in w.out and time.monotonic() - t0 < 15


# ------------------------------------------------------------------ launch-svc and vlm

class Listener:
    """A TCP listener on 127.0.0.1 standing in for the guest's :7102."""

    def __enter__(self):
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(8)
        self.port = self.s.getsockname()[1]
        return self

    def __exit__(self, *a):
        self.s.close()


def free_port():
    with Listener() as ln:
        return ln.port


def launch_svc(g, port, words="IMAGE=ifs-svc.bin"):
    return g.run("launch-svc", words, SVC_PORT=port)


def test_launch_svc_boots_the_named_image_and_checks_the_port_by_an_exchange(g):
    facts(g)
    with Listener() as ln:
        g.put("console", PLAIN % ln.port, nl=False)
        r = launch_svc(g, ln.port)
    assert r.returncode == 0, r.out
    assert "guest up" in r.stdout and r.stdout.splitlines()[-1].endswith("plain monitor answers on :%d" % ln.port), r.out
    stem = g.rec("vlm")
    assert sorted(p.name for p in stem.iterdir()) == ["console.log", "launch-svc-host-after.txt", "launch-svc.log"]
    assert "kernel_oops=no" in (stem / "launch-svc-host-after.txt").read_text()
    call = g.calls("launcher")[0]
    assert "IFS_BIN=%s/img/ifs-svc.bin" % g.w in call and "LOG=%s" % (stem / "console.log") in call, call


@pytest.mark.parametrize("case", ["banner alone", "deadline banner", "no banner", "launch fails"])
def test_launch_svc_refuses_on_the_banner_alone_and_on_the_deadline_banner(g, case):
    facts(g)
    with Listener() as ln:
        port = ln.port if case != "banner alone" else free_port()
        g.put("console", {"banner alone": PLAIN % port, "deadline banner": PLAIN % port + DEADLINE % port,
                          "no banner": "claim kinds: 0 mnist\n", "launch fails": ""}[case], nl=False)
        if case == "launch fails":
            g.flag("launch-fail")
        r = launch_svc(g, port)
    assert r.returncode != 0 and "plain monitor answers" not in r.stdout, r.out
    stem = g.rec("vlm")
    assert (stem / "launch-svc-host-after.txt").exists() and not (stem / "host-after.txt").exists()


def test_launch_svc_refuses_while_a_qemu_runs_and_an_image_this_session_did_not_upload(g):
    facts(g)
    for words, msg in ((None, "IMAGE="), ("IMAGE=ifs-other.bin", "not an image this session uploaded"),
                       ("IMAGE=ifs-svc.bin EXTRA=1", "IMAGE=")):
        r = g.run("launch-svc", words)
        assert r.returncode != 0 and msg in r.out, r.out
    g.flag("qemu-running")
    r = g.run("launch-svc", "IMAGE=ifs-svc.bin")
    assert r.returncode != 0 and "a QEMU is running" in r.out and not g.calls("launcher"), r.out


ONE_IMAGE = "launch-svc takes one word, IMAGE=<an image this session uploaded> (LADDER_ENV), and no other"


@pytest.mark.parametrize("words", ["IMAGE=ifs-other.bin IMAGE=ifs-svc.bin", "IMAGE=ifs-svc.bin IMAGE=ifs-other.bin",
                                   "IMAGE=ifs-svc.bin IMAGE=ifs-svc.bin", "IMAGE=ifs-svc.bin IMAGE=ifs-svc.bin IMAGE=ifs-svc.bin"])
def test_launch_svc_refuses_an_image_word_given_twice_by_its_refusal_before_any_effect(g, words):
    """launch-svc takes one IMAGE word, as its refusal says. Two, equal or not, are refused by that refusal before any
    effect, as gpu-install's and llama-build's words are (g5g_once): the last word does not win, though it names the
    image this session uploaded and a guest would answer; no stem is made, nothing is launched and nothing is asked of
    a stub."""
    facts(g)
    (g.stub / "calls.log").unlink(missing_ok=True)
    with Listener() as ln:
        g.put("console", PLAIN % ln.port, nl=False)
        r = launch_svc(g, ln.port, words)
    assert r.returncode != 0 and ONE_IMAGE in r.out, r.out
    assert "not an image this session uploaded" not in r.out and "plain monitor answers" not in r.out, r.out
    assert g.calls() == [] and not g.rec("vlm").exists(), g.calls()


def svc_up(g):
    g.driver_up()
    facts(g)
    with Listener() as ln:
        g.put("console", PLAIN % ln.port, nl=False)
        assert launch_svc(g, ln.port).returncode == 0


@pytest.mark.parametrize("rc", [0, 1])
def test_vlm_runs_the_demo_on_one_gpu_and_records_its_exit_status_which_is_not_fatal(g, rc):
    svc_up(g)
    g.put("demo-rc", str(rc))
    r = g.run("vlm")
    assert r.returncode == 0 and "demo exit %d" % rc in r.stdout and "1 of 2 claims" in r.stdout, r.out
    stem = g.rec("vlm")
    assert (stem / "demo-exit.txt").read_text() == "%d\n" % rc
    after = (stem / "host-after.txt").read_text()
    assert "kernel_oops=no" in after and "boot=same" in after
    env = dict(ln.split("=", 1) for ln in (g.stub / "demo.env").read_text().splitlines())
    assert env == {"CUDA_VISIBLE_DEVICES": "0", "IMAGES": str(g.w / "in"), "LLAMA_MODELS": str(g.w / "in"),
                   "CONSOLE": str(stem / "console.log"), "OUT": str(stem)}, env
    assert (stem / "launch-svc-host-after.txt").exists()
    # what the phase prints for the session to read: the host after the demo, and what the stamp says of the board and
    # the GPUs seen
    assert "host after: kernel_oops=no boot=same" in r.stdout, r.out
    assert "stamp: board=a stub that is no Tegra host cuda_visible_devices=0" in r.stdout, r.out


def test_vlm_says_a_stamp_that_is_absent_or_unreadable(g):
    svc_up(g)
    g.flag("no-stamp")
    r = g.run("vlm")
    assert r.returncode == 0 and "stamp: absent" in r.stdout, r.out
    g2 = Rig(g.tmp / "second")
    svc_up(g2)
    aws._write(g2.w / "repo" / "orin-native" / "edge-llm" / "vlm-demo.sh",
               STUB_DEMO.replace('echo "1 of 2', 'echo "not json" > "$OUT/stamp.json"\necho "1 of 2'), newline=False)
    r = g2.run("vlm")
    assert r.returncode == 0 and "stamp: unreadable" in r.stdout, r.out


def test_a_second_demo_in_a_session_is_refused_and_the_firsts_exit_status_stands(g):
    svc_up(g)
    assert g.run("vlm").returncode == 0
    (g.stub / "demo.env").unlink()
    g.put("demo-rc", "1")
    after = g.rec("vlm", "host-after.txt")
    kept = after.read_bytes()
    os.utime(str(after), (1, 1))
    r = g.run("vlm")
    assert r.returncode != 0 and "one demo a session" in r.out, r.out
    assert after.read_bytes() == kept and after.stat().st_mtime == 1, "the refusal comes before the stem's exit trap is armed"
    assert g.rec("vlm", "demo-exit.txt").read_text() == "0\n" and not (g.stub / "demo.env").exists()


def test_gpu_facts_prints_each_gpus_name_before_its_summary_line(g):
    g.driver_up()
    out = facts(g).stdout.splitlines()
    assert out[-3:-1] == ["gpu 0: Stub T4G (compute_cap 7.5)", "gpu 1: Stub T4G (compute_cap 7.5)"], out
    assert out[-1].startswith("gpu-facts: cpu_part=")


def test_gpu_facts_ends_by_a_word_when_the_driver_tool_does_not_answer(g):
    g.driver_up()
    g.flag("smi-hang")
    t0 = time.monotonic()
    r = facts(g, G5G_SMI_WAIT_S=1)
    assert time.monotonic() - t0 < 20, "the tool's run is bounded"
    s = summary_of(r.stdout)
    assert (s["gpus"], s["compute_cap"], s["bound"]) == ("0", "none", "nvidia,nvidia"), s
    assert g.rec("gpu-facts", "gpus.txt").read_text() == "driver tool: failed (no answer within 1 s)\n"


@pytest.mark.parametrize("gone", ["curl", "taskset", "node:nvidia-uvm", "console"])
def test_vlm_checks_the_demos_programs_the_nodes_and_the_console_by_name_first(g, gone):
    svc_up(g)
    if gone.startswith("node:"):
        os.remove(str(g.root / "dev" / gone[5:]))
    elif gone == "console":
        os.remove(str(g.rec("vlm", "console.log")))
    else:
        os.remove(str(g.stub / gone))
    env = {}
    if gone in ("curl", "taskset"):         # this host's own tools, less the one that is gone
        tools = g.tmp / "tools"
        tools.mkdir()
        for n in os.listdir("/usr/bin"):
            if n != gone:
                os.symlink(os.path.join("/usr/bin", n), str(tools / n))
        env = {"PATH": str(g.stub) + os.pathsep + str(tools)}
    r = g.run("vlm", **env)
    assert r.returncode != 0 and gone.split(":")[-1].replace("console", "run launch-svc first") in r.out, r.out
    assert not (g.stub / "demo.env").exists() and not g.rec("vlm", "demo-exit.txt").exists()
    assert g.rec("vlm", "host-after.txt").exists() or gone == "console"


def test_no_new_phase_writes_an_arm_file_name_into_its_stem_or_reboots(g):
    g.bind("nouveau")
    facts(g)
    assert plan(g).returncode == 0 and apply(g).returncode == 0
    facts(g)
    assert g.run("llama-build").returncode == 0 and wait_build(g).returncode == 0
    with Listener() as ln:
        g.put("console", PLAIN % ln.port, nl=False)
        assert launch_svc(g, ln.port).returncode == 0
    assert g.run("vlm").returncode == 0
    names = [f for _d, _s, fs in os.walk(str(g.w / "rec")) for f in fs]
    assert names and not [n for n in names if n.startswith(("lat-", "kvm-", "db-burst", "ex-"))], names
    assert not g.calls("reboot") and not g.calls("shutdown") and not any(
        w in c for c in g.calls() for w in ("systemctl reboot", "systemctl kexec", "sudo reboot", "sudo shutdown"))
    for stem in ("gpu-facts", "gpu-facts-2", "gpu-install", "llama-build", "vlm"):
        after = g.rec(stem, "host-after.txt").read_text()
        assert re.search(r"^kernel_oops=(yes|no|unread)$", after, re.M) and re.search(r"^boot=(same|new)$", after, re.M), stem
